"""Import MP3s from uploads_zip via AWS CLI; never delete archives or overwrite music."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tempfile
import zipfile

from prepare_test_music import safe_path

MAX_ZIP_BYTES = 8 * 1024 ** 3
MAX_TRACK_BYTES = 150 * 1024 ** 2  # Same limit as the station's audio cache.
MAX_EXPANDED_BYTES = 20 * 1024 ** 3
IMPORT_PREFIX = 'music/zip-imports/'


def inspect_audio(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_entries',
                             'format=duration:stream=codec_type,codec_name', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True, timeout=30)
    audio = json.loads(result.stdout)
    if not any(s.get('codec_name') == 'mp3' and s.get('codec_type') == 'audio'
               for s in audio.get('streams', [])) or float(audio['format']['duration']) <= 0:
        raise ValueError('Not a valid MP3')
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(path),
                    '-map', '0:a:0', '-f', 'null', '-'], capture_output=True, check=True, timeout=180)


def import_archive(archive, work, known, upload, probe=inspect_audio):
    """known maps content SHA256 to an existing imported key; callbacks simplify tests."""
    report = {'uploaded': [], 'duplicates': [], 'ignored': []}
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 10000 or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES:
            raise ValueError('ZIP exceeds extraction limits')
        # Validate every path before processing any member; never use extractall.
        for entry in entries:
            safe_path(entry.filename)
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ValueError('ZIP contains a symlink or encrypted entry')
        for entry in entries:
            name = PurePosixPath(entry.filename.replace('\\', '/')).name
            if entry.is_dir():
                continue
            if (not name.lower().endswith('.mp3') or name.startswith('._')
                    or '__MACOSX' in entry.filename.split('/')):
                report['ignored'].append({'file': entry.filename, 'reason': 'not MP3'})
                continue
            if entry.file_size <= 0 or entry.file_size > MAX_TRACK_BYTES:
                report['ignored'].append({'file': entry.filename, 'reason': 'size outside limits'})
                continue
            target = Path(work) / 'track.mp3'
            try:
                digest = hashlib.sha256()
                size = 0
                with source.open(entry) as src, target.open('wb') as dst:
                    while chunk := src.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_TRACK_BYTES:
                            raise ValueError('Track exceeds size limit')
                        digest.update(chunk)
                        dst.write(chunk)
                if size != entry.file_size:
                    raise ValueError('ZIP size mismatch')
                sha = digest.hexdigest()
                if sha in known:
                    report['duplicates'].append({'file': entry.filename, 'key': known[sha]})
                    continue
                try:
                    probe(target)
                except (ValueError, KeyError, subprocess.SubprocessError) as error:
                    report['ignored'].append({'file': entry.filename, 'reason': 'invalid audio: ' + type(error).__name__})
                    continue
                key = IMPORT_PREFIX + sha + '/' + name
                # Upload failures propagate: never label a network failure as corrupt audio.
                upload(target, key, sha)
                known[sha] = key
                report['uploaded'].append({'file': entry.filename, 'key': key, 'bytes': size})
            finally:
                target.unlink(missing_ok=True)
    if not report['uploaded'] and not report['duplicates']:
        raise ValueError('ZIP contains no valid MP3s')
    return report


class R2:
    def __init__(self):
        self.bucket = os.environ['R2_BUCKET']
        self.endpoint = 'https://' + os.environ['R2_ACCOUNT_ID'] + '.r2.cloudflarestorage.com'

    def aws(self, *args):
        # No credential values in command arguments or captured error output.
        return subprocess.run(['aws', *args, '--endpoint-url', self.endpoint],
                              capture_output=True, text=True, check=True, timeout=1800).stdout

    def listing(self, prefix):
        return json.loads(self.aws('s3api', 'list-objects-v2', '--bucket', self.bucket,
                                   '--prefix', prefix, '--query', 'Contents[]', '--output', 'json')) or []

    def download(self, key, path):
        self.aws('s3', 'cp', 's3://' + self.bucket + '/' + key, str(path), '--only-show-errors')

    def upload(self, path, key, sha):
        self.aws('s3', 'cp', str(path), 's3://' + self.bucket + '/' + key,
                 '--content-type', 'audio/mpeg', '--metadata', 'sha256=' + sha, '--only-show-errors')
        result = json.loads(self.aws('s3api', 'head-object', '--bucket', self.bucket, '--key', key))
        if result['ContentLength'] != path.stat().st_size or result.get('Metadata', {}).get('sha256') != sha:
            raise ValueError('Uploaded object verification failed')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    r2 = R2()
    archives = sorted((x for x in r2.listing('uploads_zip/') if x['Key'].lower().endswith('.zip')),
                      key=lambda x: x['Key'])
    if not archives:
        raise ValueError('No ZIPs found in uploads_zip/')
    known = {}
    for item in r2.listing(IMPORT_PREFIX):
        parts = item['Key'][len(IMPORT_PREFIX):].split('/')
        if len(parts) == 2 and len(parts[0]) == 64 and item['Size'] > 0:
            known[parts[0]] = item['Key']
    reports = []
    try:
        for obj in archives:
            print('ZIP: ' + json.dumps({'key': obj['Key'], 'bytes': obj['Size']}), flush=True)
            if not 0 < obj['Size'] <= MAX_ZIP_BYTES:
                raise ValueError('ZIP size outside limits')
            with tempfile.TemporaryDirectory(prefix='alce-r2-import-') as directory:
                if shutil.disk_usage(directory).free < obj['Size'] + MAX_TRACK_BYTES + 512 * 1024 ** 2:
                    raise ValueError('Insufficient temporary disk space')
                archive = Path(directory) / 'archive.zip'
                r2.download(obj['Key'], archive)
                if archive.stat().st_size != obj['Size']:
                    raise ValueError('Downloaded ZIP size mismatch')
                result = import_archive(archive, directory, known, r2.upload)
            reports.append(dict(archive=obj['Key'], **result))
            print('IMPORT: ' + json.dumps({k: len(v) for k, v in result.items()}), flush=True)
    finally:
        Path(args.report).write_text(json.dumps(reports, ensure_ascii=False, indent=2) + '\n')
    summary = 'ZIPs: %s; MP3 enviados: %s; duplicados: %s; ignorados: %s.' % (
        len(reports), sum(len(r['uploaded']) for r in reports),
        sum(len(r['duplicates']) for r in reports), sum(len(r['ignored']) for r in reports))
    print(summary)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write(summary + '\n')


if __name__ == '__main__':
    main()
