#!/usr/bin/env python3
"""Catalog synchronizer + single station planner, serving only ready local audio to Liquidsoap."""
import json
import logging
import os
import signal
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import config
from audio_cache import AudioCache
from catalogs import Catalogs, atomic_json
from news import RemoteNewsProvider
from programming import ProgrammingEngine
from storage import Storage
from time_announcements import TimeAnnouncements

log = logging.getLogger('radio')


def quote(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ')


def request_uri(item, token):
    metadata = {'radio_token': token, 'radio_id': item['id'], 'program_type': item['type'],
                'title': item['title'], 'artist': item.get('artist', ''),
                'liq_gain': config.GAINS.get(item['type'], .8),
                'liq_fade_out': config.MUSIC_FADE_SECONDS if item['type'] == 'MUSIC' else 0.,
                'liq_fade_in': .1 if item['type'] == 'MUSIC' else .15}
    if item['type'] == 'MUSIC' and item.get('cue_out') is not None:
        metadata['liq_cue_out'] = item['cue_out']
    if item['type'] == 'TIME_ANNOUNCEMENT':
        metadata['time_valid_until'] = item['slot'] + config.TIME_MAX_LATENESS
    return 'annotate:' + ','.join(f'{key}="{quote(value)}"' for key, value in metadata.items()) + ':' + item['path']


class Planner:
    def __init__(self, catalogs, engine, cache, news, times, clock=time.time):
        self.catalogs, self.engine, self.cache, self.news, self.times = catalogs, engine, cache, news, times
        self.clock = clock
        self.lock = threading.RLock()
        self.ready = deque()
        self.delivered = {}
        self.current = None
        self.tail = None
        self.end_of_plan = clock()
        self.sequence = 0
        self.started_sequence = -1
        self.news_reserved = set()
        self.emergency = []
        emergency_snapshot = self.cache.directory.parent / 'emergency.json'
        if emergency_snapshot.exists():
            try:
                saved = json.loads(emergency_snapshot.read_text())
                from audio_cache import probe
                for value in saved:
                    path = self._emergency_path(value)
                    if path is not None:
                        try:
                            probe(path)
                            self.emergency.append(value)
                        except Exception:
                            log.warning('EMERGENCY cached audio unavailable; omitted')
            except Exception:
                log.warning('EMERGENCY snapshot unavailable; rebuilding verified pool')
        # Migrate an old annotated M3U even when R2 is temporarily unavailable.
        if self.emergency:
            self._write_emergency()
        self.restored_emergency = bool(self.emergency)
        self.last_fill = clock()
        self.reset_requested = False

    def _reserved_music(self):
        with self.lock:
            pending = sorted(list(self.ready) + [value for value in self.delivered.values()
                                                if not value.get('started')], key=lambda x: x['sequence'])
            return [value['item']['id'] for value in pending if value['item']['type'] == 'MUSIC']

    def _music(self):
        catalog = self.catalogs.music['items']
        reserved = self._reserved_music()
        for _ in range(len(catalog)):
            item = self.engine.music(catalog, reserved)
            if item is None:
                return None
            try:
                return self.cache.prepare(item)
            except Exception:
                self.engine.failed(item)
        return None

    def _append(self, item):
        with self.lock:
            self.sequence += 1
            delivery = {'item': item, 'token': uuid.uuid4().hex, 'sequence': self.sequence,
                        'checkpoint': self.engine.checkpoint()}
            self.ready.append(delivery)
            self.tail = item
            self.end_of_plan += item['duration']
        log.info('NEXT %s id=%s; cached/probed=true', item['type'], item['id'])

    def _news_block(self, boundary):
        played = self.engine.storage.played_news() | self.news_reserved
        candidate = self.news.candidate(played, self.cache.prepare)
        if candidate is None:
            return None  # No intro alone; leave due for the next safe musical boundary.
        try:
            intro = self.cache.prepare({'id': 'news-intro', 'type': 'NEWS_INTRO',
                'title': 'Notícias — Rádio Alce', 'url': config.NEWS_INTRO_URL})
        except Exception:
            log.warning('NEWS intro unavailable; block cancelled, music continues')
            return None
        # Announce only a valid cached slot at the projected start after the complete intro.
        announcement = self.times.ready(boundary + intro['duration'])
        self.engine.reserve_news(boundary)
        self.news_reserved.add(candidate['id'])
        return [intro] + ([announcement] if announcement else []) + [candidate]

    def reset_if_needed(self):
        with self.lock:
            if self.reset_requested:
                self.ready.clear()
                self.delivered.clear()
                self.news_reserved.clear()
                self.current = self.tail = None
                self.end_of_plan = self.clock()
                self.sequence = 0
                self.started_sequence = -1
                self.engine = ProgrammingEngine(self.engine.storage, self.clock)
                self.reset_requested = False
                log.info('STATE restored from actual playback checkpoint; Liquidsoap restarted')

    def fill_once(self):
        self.reset_if_needed()
        self.last_fill = self.clock()
        if hasattr(self.cache, 'pin'):
            pools = self.catalogs.programming['stationIds'] + self.catalogs.programming['jingles']
            self.cache.pin([item['url'] for item in pools] + [config.NEWS_INTRO_URL])
        with self.lock:
            if len(self.ready) >= config.PREPARED_ITEMS:
                return False
            initial = self.tail is None
            boundary = self.end_of_plan
        # Network/probe work NEVER holds the ready-queue lock. /next remains immediate.
        if initial:
            track = self._music()
            if track is None:
                return False
            self.end_of_plan = self.clock()
            self._append(track)
            self._emergency(track)
            return True
        # Complete the following MUSIC first, so no block can leave a stranded short item.
        following = self._music()
        if following is None:
            return False
        inserts = None
        if self.engine.news_due(boundary):
            inserts = self._news_block(boundary)
        if inserts is None:
            with self.lock:
                pending_jingle = any(
                    entry['item']['type'] == 'JINGLE'
                    for entry in list(self.ready) + list(self.delivered.values())
                    if not entry.get('started')
                )
            allow_jingle = (not pending_jingle) and self.engine.jingle_due(boundary)
            insertion = self.engine.insertion(
                self.catalogs.programming, self.cache.prepare, allow_jingle=allow_jingle)
            inserts = [insertion] if insertion else []
        # Publish the fully prepared block atomically; /next cannot observe a lone insert.
        with self.lock:
            for item in inserts:
                self._append(item)
            self._append(following)
        self._emergency(following)
        with self.lock:
            protected = [value['item']['path'] for value in list(self.ready) + list(self.delivered.values())]
        self.cache.prune(protected + [item['path'] for item in self.emergency])
        return True

    def _emergency_path(self, item):
        if not isinstance(item.get('path'), str):
            return None
        path = Path(item['path'])
        if (item.get('type') != 'MUSIC' or not path.is_absolute() or
                path.suffix.lower() != '.mp3' or any(char in str(path) for char in '\r\n?#')):
            return None
        if not path.resolve().is_relative_to(self.cache.directory.resolve()):
            return None
        try:
            return path if path.is_file() and path.stat().st_size > 0 else None
        except OSError:
            return None

    def _emergency(self, item):
        path = self._emergency_path(item)
        if path is None:
            return
        self.emergency = [value for value in self.emergency
                          if self._emergency_path(value) not in (None, path)] + [item]
        self.emergency = self.emergency[-3:]
        atomic_json(self.cache.directory.parent / 'emergency.json', self.emergency)
        self._write_emergency()

    def _write_emergency(self):
        path = self.cache.directory.parent / 'emergency.m3u'
        # This is a traditional M3U, not a request/metadata transport.
        paths = list(dict.fromkeys(str(local) for value in self.emergency
                                   if (local := self._emergency_path(value)) is not None))
        content = '#EXTM3U\n' + '\n'.join(paths) + '\n'
        if path.exists() and path.read_text() == content:
            return
        tmp = path.with_suffix('.tmp')
        with tmp.open('w') as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        tmp.chmod(0o644)
        tmp.replace(path)
        log.info('EMERGENCY playlist updated: %s tracks', len(paths))

    def next(self):
        with self.lock:
            if self.reset_requested or not self.ready:
                return ''
            while self.ready:
                value = self.ready.popleft()
                path = Path(value['item']['path'])
                try:
                    if path.is_file() and path.stat().st_size > 0:
                        break
                except OSError:
                    pass
                log.warning('READY audio disappeared id=%s; skipping unavailable request', value['item']['id'])
            else:
                return ''
            self.delivered[value['token']] = value
            return request_uri(value['item'], value['token'])

    def started(self, token, emergency_id=None):
        with self.lock:
            if self.reset_requested:
                return
            # Plain fallback paths have no trustworthy delivery token; never infer plays.
            if token == 'emergency':
                return
            value = self.delivered.get(token)
            if value is None or value['sequence'] <= self.started_sequence:
                return  # Ignore repeated/late acknowledgement; preload is never marked played.
            if self.current:
                previous = self.delivered.get(self.current)
                if previous:
                    log.info('COMPLETED %s id=%s; natural boundary', previous['item']['type'], previous['item']['id'])
                self.delivered.pop(self.current, None)
            self.current = token
            self.started_sequence = value['sequence']
            value['started'] = self.clock()
            self.engine.started(value['item'], value['checkpoint'])
            if value['item']['type'] == 'NEWS_DROP':
                self.news_reserved.discard(value['item']['id'])
            # Correct forecast to the real on-air start; all following items are already known.
            pending = [entry for entry in self.delivered.values() if not entry.get('started')] + list(self.ready)
            self.end_of_plan = self.clock() + value['item']['duration'] + sum(entry['item']['duration'] for entry in pending)

    def health(self):
        return (bool(self.catalogs.music['items']) and self.clock() - self.last_fill < 180 and
                (len(self.ready) >= 3 or bool(self.delivered) or self.restored_emergency))


def run():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    config.DATA.mkdir(parents=True, exist_ok=True)
    config.DATA.chmod(0o755)
    storage = Storage(config.DATA / 'station.sqlite3')
    catalogs = Catalogs(config.DATA)
    cache = AudioCache(config.DATA / 'cache')
    planner = Planner(catalogs, ProgrammingEngine(storage), cache, RemoteNewsProvider(),
                      TimeAnnouncements(config.DATA / 'time'))
    stop = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Do not print URLs, API headers or query strings.

        def response(self, status, body):
            self.send_response(status)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(body.encode())

        def do_GET(self):
            path = urlparse(self.path).path
            if path == '/next':
                self.response(200, planner.next())
            elif path == '/health':
                self.response(200 if planner.health() else 503, 'healthy' if planner.health() else 'waiting catalog')
            elif path == '/heartbeat':
                (config.DATA / 'liquidsoap.heartbeat').touch()
                self.response(200, 'ok')
            else:
                self.response(404, 'not found')

        def do_POST(self):
            if urlparse(self.path).path == '/reset':
                with planner.lock:
                    planner.reset_requested = True
                self.response(200, 'reset requested')
                return
            if urlparse(self.path).path != '/played':
                self.response(404, 'not found')
                return
            query = parse_qs(urlparse(self.path).query)
            planner.started(query.get('token', [''])[0], query.get('id', [''])[0])
            self.response(200, 'ok')

    def synchronize():
        while not stop.is_set():
            catalogs.refresh(config.CATALOG_URL, config.PROGRAMMING_URL)
            planner.news.refresh()
            stop.wait(config.SYNC_INTERVAL)

    def prepare():
        while not stop.is_set():
            try:
                if not planner.fill_once():
                    stop.wait(1)
            except Exception as error:
                log.error('PRELOAD failed (%s); keeping prepared items/emergency audio', type(error).__name__)
                stop.wait(5)

    def warm_time():
        while not stop.is_set():
            planner.times.warm_all(stop)
            stop.wait(config.NEWS_REFRESH)

    for target in (synchronize, prepare, warm_time):
        threading.Thread(target=target, daemon=True).start()
    server = ThreadingHTTPServer(('0.0.0.0', 8081), Handler)
    def shutdown(*_):
        stop.set()
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    run()
