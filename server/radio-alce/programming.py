"""One global sequencer. Reservations are not executions; news does not consume the cycle."""
import copy
import logging
import random
import time
from collections import deque
import config

log = logging.getLogger('radio')

# Compatibility only: old checkpoints encoded epoch time in half-hour slots.
LEGACY_NEWS_SLOT_SECONDS = 30 * 60


class ShuffleBag:
    def __init__(self, state=None, rng=None):
        state = state or {}
        self.remaining = deque(state.get('remaining', []))
        self.keys = set(state.get('keys', []))
        self.last = state.get('last')
        self.rng = rng or random.SystemRandom()

    def invalidate(self):
        self.keys.clear()
        self.remaining.clear()

    def next(self, pool):
        entries = {item['id']: item for item in pool}
        if not entries:
            return None
        if self.keys != entries.keys():
            self.remaining.clear()
            self.keys = set(entries)
        if not self.remaining:
            ids = list(entries)
            self.rng.shuffle(ids)
            if len(ids) > 1 and ids[0] == self.last:
                index = self.rng.randrange(1, len(ids))
                ids[0], ids[index] = ids[index], ids[0]
            self.remaining.extend(ids)
        id = self.remaining.popleft()
        self.last = id
        return entries[id]

    def snapshot(self):
        return {'remaining': list(self.remaining), 'keys': sorted(self.keys), 'last': self.last}


class ProgrammingEngine:
    def __init__(self, storage, clock=time.time, rng=None):
        self.storage, self.clock = storage, clock
        self.rng = rng or random.SystemRandom()
        self.state = storage.get('programming', {})
        if 'last_news_boundary' not in self.state:
            legacy = self.state.get('last_news_slot')
            self.state['last_news_boundary'] = (
                legacy * LEGACY_NEWS_SLOT_SECONDS if legacy is not None else self.clock())
        # Actual playback may be later than its planned boundary (decoder/network delay).
        self.state['last_news_boundary'] = max(
            self.state['last_news_boundary'], storage.get('last_news_played_at', 0))
        storage.put('programming', self.state)
        log.info('NEWS schedule interval=%ss; last boundary=%.0f; next eligible=%.0f',
                 config.NEWS_INTERVAL, self.state['last_news_boundary'],
                 self.state['last_news_boundary'] + config.NEWS_INTERVAL)
        self.position = self.state.get('position', 0) % len(config.INSERTION_PATTERN)
        self.stations = ShuffleBag(self.state.get('stations'), self.rng)
        self.jingles = ShuffleBag(self.state.get('jingles'), self.rng)
        self.version = self.state.get('version')
        self.last_jingle_at = self.state.get('last_jingle_at', self.clock())
        self.last_music = storage.get('last_music')
        self.failed_until = {}

    def snapshot(self):
        return {'position': self.position, 'stations': self.stations.snapshot(),
                'jingles': self.jingles.snapshot(), 'version': self.version,
                'last_news_boundary': self.state['last_news_boundary'],
                # Keep old binaries able to read the state during rollback.
                'last_news_slot': int(self.state['last_news_boundary'] // LEGACY_NEWS_SLOT_SECONDS),
                'last_jingle_at': self.last_jingle_at}

    def update(self, programming):
        if self.version != programming['version']:
            self.stations.invalidate()
            self.jingles.invalidate()
            self.version = programming['version']

    def failed(self, item):
        self.failed_until[item['id']] = self.clock() + config.FAILURE_COOLDOWN
        log.warning('AUDIO ignored id=%s type=%s; cooldown=%ss', item['id'], item['type'], config.FAILURE_COOLDOWN)

    def available(self, pool):
        return [item for item in pool if self.failed_until.get(item['id'], 0) <= self.clock()]

    def music(self, catalog, reserved=()):
        self.storage.reconcile({item['id'] for item in catalog})
        last = reserved[-1] if reserved else self.last_music
        candidates = [item for item in self.available(catalog)
                      if (item['id'] not in reserved or len(catalog) == 1) and (item['id'] != last or len(catalog) == 1)]
        history = self.storage.history()
        for window in config.REPEAT_WINDOWS:
            eligible = [item for item in candidates if window == 0 or
                        self.clock() - history.get(item['id'], {}).get('played_at', float('-inf')) >= window]
            if window == config.REPEAT_WINDOWS[0]:
                log.info('HISTORY blocked tracks=%s eligible tracks=%s', len(candidates) - len(eligible), len(eligible))
            if not eligible:
                continue
            if window != config.REPEAT_WINDOWS[0]:
                log.info('HISTORY relaxed window=%ss; catalog exhausted', window)
            artist_times = {}
            for entry in history.values():
                if entry['artist']:
                    artist_times[entry['artist']] = max(artist_times.get(entry['artist'], 0), entry['played_at'])
            artists = [item for item in eligible if self.clock() - artist_times.get(
                item.get('artist', '').strip().casefold(), float('-inf')) >= config.ARTIST_WINDOW]
            eligible = artists or eligible
            never = [item for item in eligible if item['id'] not in history]
            if never:
                return self.rng.choice(never)
            oldest = sorted(eligible, key=lambda item: history[item['id']]['played_at'])
            # Shuffle within a least-recently-played group, rather than deterministic full cycles.
            return self.rng.choice(oldest[:max(1, min(5, (len(oldest) + 3) // 4))])
        return None

    def jingle_due(self, boundary=None):
        when = self.clock() if boundary is None else boundary
        return when - self.last_jingle_at >= config.JINGLE_INTERVAL

    def insertion(self, programming, prepare, allow_jingle=False):
        """Every normal boundary gets one insert: hourly JINGLE when due, otherwise STATION_ID.

        The old STATION_ID/STATION_ID/JINGLE cycle is intentionally no longer used for
        scheduling. Its position remains in persisted state only for rollback compatibility.
        A deferred or unavailable jingle must never create a blank insert slot.
        """
        self.update(programming)
        preferred = 'JINGLE' if allow_jingle else 'STATION_ID'
        kinds = [preferred] + (['STATION_ID'] if preferred == 'JINGLE' else [])
        for kind in kinds:
            pool = self.available(programming['stationIds' if kind == 'STATION_ID' else 'jingles'])
            bag = self.stations if kind == 'STATION_ID' else self.jingles
            for _ in range(len(pool)):
                item = bag.next(pool)
                try:
                    prepared = prepare(item)
                    if kind == 'JINGLE':
                        log.info('INTERSTITIAL JINGLE hourly slot: %s; bag remaining=%s',
                                 item['title'], len(bag.remaining))
                    else:
                        log.info('INTERSTITIAL STATION_ID: %s; bag remaining=%s',
                                 item['title'], len(bag.remaining))
                    return prepared
                except Exception:
                    self.failed(item)
                    pool = self.available(pool)
                    if not pool:
                        break
            if kind == 'JINGLE':
                log.warning('INTERSTITIAL JINGLE unavailable; using STATION_ID for this boundary')
        log.warning('INTERSTITIAL STATION_ID unavailable; following MUSIC directly')
        return None

    def news_due(self, boundary):
        last = max(self.state['last_news_boundary'],
                   self.storage.get('last_news_played_at', 0))
        return boundary - last >= config.NEWS_INTERVAL

    def reserve_news(self, boundary):
        self.state['last_news_boundary'] = boundary

    def started(self, item, checkpoint):
        now = self.clock()
        persisted = copy.deepcopy(checkpoint)
        if item['type'] == 'JINGLE':
            self.last_jingle_at = now
            persisted['last_jingle_at'] = now
        self.storage.started(item, persisted, now, config.HISTORY_RETENTION,
                             config.HISTORY_LIMIT, config.NEWS_HISTORY_LIMIT)
        if item['type'] == 'MUSIC':
            self.last_music = item['id']
        log.info('NOW PLAYING %s: %s / %s', item['type'], item['id'], item['title'])

    def checkpoint(self):
        return copy.deepcopy(self.snapshot())
