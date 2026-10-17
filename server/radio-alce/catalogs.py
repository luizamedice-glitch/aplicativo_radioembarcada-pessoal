"""Validated provider models, last-good snapshots and hot refresh, independent of playout."""
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse
import urllib.request
import config

log = logging.getLogger('radio')


def valid_url(url):
    try:
        value = urlparse(url)
        return value.scheme == 'https' and bool(value.hostname) and not value.username and not value.fragment
    except (TypeError, ValueError):
        return False


def items(values, kind):
    result = {}
    for item in values if isinstance(values, list) else []:
        if (isinstance(item, dict) and item.get('type') == kind and
                isinstance(item.get('id'), str) and item['id'].strip() and
                isinstance(item.get('title'), str) and item['title'].strip() and valid_url(item.get('url'))):
            result[item['id']] = dict(item, type=kind, artist=item.get('artist') if isinstance(item.get('artist'), str) else '')
    return list(result.values())


def parse_music(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid catalog document')
    version = data.get('version')
    if type(version) is not int or version < 1:
        raise ValueError('Invalid catalog version')
    tracks = items(data.get('items'), 'MUSIC')
    if not tracks:
        raise ValueError('Empty catalog')
    return {'version': version, 'items': tracks}


def parse_programming(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid programming document')
    if not isinstance(data.get('stationId'), str) or not data['stationId'].strip():
        raise ValueError('Missing station')
    if type(data.get('version')) is not int or data['version'] < 1 or not isinstance(data.get('rules'), dict):
        raise ValueError('Invalid programming')
    station_ids = [item for item in items(data.get('stationIds'), 'STATION_ID')
                   if item['id'] not in config.DISABLED_PROGRAM_IDS]
    jingles = [item for item in items(data.get('jingles'), 'JINGLE')
               if item['id'] not in config.DISABLED_PROGRAM_IDS]
    return {'stationId': data['stationId'], 'version': data['version'], 'rules': data['rules'],
            'stationIds': station_ids, 'jingles': jingles}


def read_url(url, max_bytes=2 * 1024 ** 2):
    request = urllib.request.Request(url, headers={'User-Agent': 'RadioAlceServer/2.0'})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read(max_bytes + 1)
        if len(body) > max_bytes:
            raise ValueError('Document too large')
        return body


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as handle:
        json.dump(data, handle, ensure_ascii=False)
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)


class Catalogs:
    def __init__(self, directory, fetch=read_url):
        self.directory, self.fetch = Path(directory), fetch
        self.music = self._saved('music_catalog.json', parse_music, {'version': 0, 'items': []})
        self.programming = self._saved('programming.json', parse_programming,
                                       {'version': 0, 'stationIds': [], 'jingles': []})

    def _saved(self, name, parser, default):
        try:
            return parser(json.loads((self.directory / name).read_text()))
        except (OSError, ValueError, TypeError):
            return default

    def refresh(self, music_url, programming_url):
        for name, url, parser, attr in [('music_catalog.json', music_url, parse_music, 'music'),
                                      ('programming.json', programming_url, parse_programming, 'programming')]:
            try:
                current = parser(json.loads(self.fetch(url)))
                if current != getattr(self, attr):
                    atomic_json(self.directory / name, current)
                    setattr(self, attr, current)
                    if attr == 'music':
                        log.info('CATALOG version=%s tracks=%s', current['version'], len(current['items']))
                    else:
                        log.info('PROGRAMMING version=%s stationIds=%s jingles=%s', current['version'],
                                 len(current['stationIds']), len(current['jingles']))
                if attr == 'music':
                    # Preserve the original music-only Liquidsoap configuration as a rollback path.
                    path = self.directory / 'music.m3u'
                    tmp = path.with_suffix('.tmp')
                    tmp.write_text('#EXTM3U\n' + '\n'.join(item['url'] for item in current['items']) + '\n')
                    tmp.replace(path)
            except Exception as error:
                # Exception class only: URLs/API keys must never be included in logs.
                log.warning('SYNC %s failed (%s); retaining last valid snapshot', attr, type(error).__name__)
