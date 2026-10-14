"""Copy/verify, update catalog preserving IDs, then remove legacy hash folders."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import subprocess
import tempfile
import json
import os
from pathlib import Path
import time
from urllib.parse import quote, unquote, urlsplit

from import_r2_zip import R2
from r2_music_paths import IMPORT_PREFIX, flat_key, content_digest


def plan_moves(objects, catalog):
    occupied = {obj['Key']: content_digest(obj) for obj in objects}
    moves = []
    for obj in sorted(objects, key=lambda o: o['Key']):
        relative = obj['Key'][len(IMPORT_PREFIX):]
        if '/' not in relative or not relative.lower().endswith('.mp3'):
            continue
        digest = content_digest(obj)
        if not digest:
            raise ValueError('Unknown nested structure; refusing an ambiguous move')
        target = flat_key(relative, digest, occupied)
        occupied[target] = digest
        moves.append({'source': obj['Key'], 'target': target, 'sha256': digest,
                      'size': obj['Size'], 'etag': obj['ETag']})
    replacements = {m['source']: m['target'] for m in moves}
    result = copy.deepcopy(catalog)
    base = os.environ.get('R2_PUBLIC_BASE', 'https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev').rstrip('/')
    for item in result['items']:
        parsed = urlsplit(item['url'])
        key = unquote(parsed.path.lstrip('/'))
        if key in replacements:
            if parsed.scheme != 'https' or parsed.netloc != urlsplit(base).netloc or parsed.query:
                raise ValueError('Unexpected catalog URL')
            item['url'] = base + '/' + quote(replacements[key], safe='/')
    if result != catalog:
        result['version'] += 1
    return moves, result


def head(r2, key):
    return json.loads(r2.aws('s3api', 'head-object', '--bucket', r2.bucket, '--key', key))


def check_object(data, move):
    if data['ContentLength'] != move['size'] or data.get('Metadata', {}).get('sha256') != move['sha256']:
        raise ValueError('Audio size/hash metadata mismatch; aborting')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['plan', 'apply'], required=True)
    parser.add_argument('--directory', required=True)
    args = parser.parse_args()
    directory = Path(args.directory)
    directory.mkdir(parents=True, exist_ok=True)
    r2 = R2()
    before = directory / 'music-before.json'
    after = directory / 'music-after.json'
    mapping = directory / 'moves.json'
    if args.stage == 'plan':
        r2.download('music_catalog.json', before)
        objects = r2.listing(IMPORT_PREFIX)
        for obj in objects:
            if '/' not in obj['Key'][len(IMPORT_PREFIX):] and obj['Size'] > 0:
                obj['Metadata'] = head(r2, obj['Key']).get('Metadata', {})
        moves, catalog = plan_moves(objects, json.loads(before.read_text()))
        mapping.write_text(json.dumps(moves, ensure_ascii=False, indent=2))
        after.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
        print(f'Plan: {len(moves)} MP3s; {len(catalog["items"])} tracks; version {catalog["version"]}')
        return
    moves = json.loads(mapping.read_text())
    check = directory / 'remote-check.json'
    r2.download('music_catalog.json', check)
    if check.read_bytes() != before.read_bytes():
        raise ValueError('Catalog changed since planning; rerun')
    existing = {o['Key'] for o in r2.listing(IMPORT_PREFIX)}

    def copy_verified(move):
        source = head(r2, move['source'])
        check_object(source, move)
        if source['ETag'] != move['etag']:
            raise ValueError('Source changed since planning')
        if move['target'] in existing:
            # Never overwrite even a same-name destination; require exact identity.
            check_object(head(r2, move['target']), move)
        else:
            try:
                # AWS CLI handles CopySource URL encoding; do not double-encode names.
                r2.aws('s3api', 'copy-object', '--bucket', r2.bucket, '--key', move['target'],
                       '--copy-source', r2.bucket + '/' + move['source'],
                       '--copy-source-if-match', move['etag'], '--metadata-directive', 'COPY')
            except subprocess.CalledProcessError:
                # Compatible fallback using the same authenticated R2 read/write operations.
                # Verify actual bytes before upload; originals remain until final cleanup.
                with tempfile.TemporaryDirectory(prefix='alce-move-') as tmp:
                    track = Path(tmp) / 'track.mp3'
                    r2.download(move['source'], track)
                    if (track.stat().st_size != move['size']
                            or hashlib.sha256(track.read_bytes()).hexdigest() != move['sha256']):
                        raise ValueError('Downloaded audio hash mismatch')
                    r2.upload(track, move['target'], move['sha256'])
            check_object(head(r2, move['target']), move)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, _ in enumerate(pool.map(copy_verified, moves), 1):
            if index % 20 == 0 or index == len(moves):
                print(f'Copied and verified: {index}/{len(moves)}', flush=True)
    r2.download('music_catalog.json', check)
    if check.read_bytes() != before.read_bytes():
        raise ValueError('Catalog changed during copying; no sources removed')
    if json.loads(after.read_text()) != json.loads(before.read_text()):
        r2.aws('s3', 'cp', str(after), 's3://' + r2.bucket + '/music_catalog.json',
               '--content-type', 'application/json; charset=utf-8', '--cache-control', 'no-cache, max-age=0',
               '--only-show-errors')
    r2.download('music_catalog.json', check)
    if json.loads(check.read_text()) != json.loads(after.read_text()):
        raise ValueError('Published catalog mismatch; no sources removed')
    if moves:
        print('Catalog published; allowing 75 seconds for station refresh before cleanup.', flush=True)
        time.sleep(75)
    r2.download('music_catalog.json', check)
    if json.loads(check.read_text()) != json.loads(after.read_text()):
        raise ValueError('Catalog changed before cleanup; no sources removed')

    def delete_verified(move):
        check_object(head(r2, move['target']), move)
        source = head(r2, move['source'])
        if source['ETag'] != move['etag']:
            raise ValueError('Source changed; refusing deletion')
        r2.aws('s3api', 'delete-object', '--bucket', r2.bucket, '--key', move['source'])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(delete_verified, moves))
    remaining = r2.listing(IMPORT_PREFIX)
    if any('/' in obj['Key'][len(IMPORT_PREFIX):] and obj['Key'].lower().endswith('.mp3') for obj in remaining):
        raise ValueError('Nested MP3s remain; inspect report before rerunning')
    catalog = json.loads(after.read_text())
    summary = f'Organizados: {len(moves)} MP3s; catálogo versão {catalog["version"]}, {len(catalog["items"])} músicas; IDs preservados.'
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write(summary + '\n')


if __name__ == '__main__':
    main()
