"""Merge approved station IDs without replacing remote rules, jingles or unknown fields."""
import argparse
import copy
import json
from pathlib import Path
from urllib.parse import urlsplit


def merge(current, additions):
    if current.get('stationId') != 'alce' or not isinstance(current.get('version'), int):
        raise ValueError('Invalid remote programming identity/version')
    result = copy.deepcopy(current)
    pool = result['stationIds']
    if not isinstance(pool, list) or len({item['id'] for item in pool}) != len(pool):
        raise ValueError('Invalid or duplicate station IDs')
    for item in additions:
        url = urlsplit(item['url'])
        if (item.get('type') != 'STATION_ID' or not item.get('id') or not item.get('title')
                or url.scheme != 'https' or url.hostname != 'pub-e38948fd737d4d969bb4e65eebed0249.r2.dev'
                or url.query or url.fragment or not url.path.endswith('.mp3')):
            raise ValueError('Invalid station ID addition')
        existing = next((p for p in pool if p['id'] == item['id']), None)
        if existing is not None:
            if existing != item:
                raise ValueError('Conflicting existing station ID: ' + item['id'])
        elif any(p.get('url') == item['url'] for p in pool):
            raise ValueError('Audio URL already registered with another ID')
        else:
            pool.append(copy.deepcopy(item))
    if result != current:
        result['version'] += 1
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--current', required=True)
    parser.add_argument('--additions', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = merge(json.loads(Path(args.current).read_text()), json.loads(Path(args.additions).read_text()))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(f"Programming version {result['version']}: {len(result['stationIds'])} station IDs, {len(result['jingles'])} jingles")
