import copy
import json
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config
from catalogs import Catalogs, parse_music, parse_programming
from programming import ProgrammingEngine, ShuffleBag
from storage import Storage
from sync_catalog import Planner, request_uri


def item(id, kind='MUSIC', duration=200):
    return {'id': id, 'type': kind, 'title': id, 'url': f'https://example.test/{id}.mp3',
            'duration': duration, 'path': f'/data/cache/{id}.mp3'}


def programming(count=8, version=1):
    return {'stationId': 'alce', 'version': version, 'rules': {'songsBetweenInsertions': 3},
            'stationIds': [item(f's{i}', 'STATION_ID', 10) for i in range(count)],
            'jingles': [item(f'j{i}', 'JINGLE', 30) for i in range(3)]}


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'state.sqlite3'
        self.store = Storage(self.path)
        self.now = 1_800_000_001.
        self.engine = ProgrammingEngine(self.store, lambda: self.now, random.Random(112))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def record(self, value, at=None):
        self.store.started(value, self.engine.checkpoint(), self.now if at is None else at,
                           config.HISTORY_RETENTION, config.HISTORY_LIMIT, config.NEWS_HISTORY_LIMIT)
        if value['type'] == 'MUSIC': self.engine.last_music = value['id']


class EngineTests(EngineFixture):
    def test_pattern_is_exactly_station_station_jingle_forever(self):
        p = programming()
        values = [self.engine.insertion(p, lambda value: value)['type'] for _ in range(12)]
        self.assertEqual(list(config.INSERTION_PATTERN) * 4, values)

    def test_independent_bags_use_all_eight_and_all_three_without_immediate_repeats(self):
        p = programming()
        for kind, pool in [('STATION_ID', p['stationIds']), ('JINGLE', p['jingles'])]:
            bag = ShuffleBag(rng=random.Random(2))
            ids = [bag.next(pool)['id'] for _ in range(len(pool) * 4)]
            for a, b in zip(ids, ids[1:]): self.assertNotEqual(a, b)
            for start in range(0, len(ids), len(pool)):
                self.assertEqual({value['id'] for value in pool}, set(ids[start:start + len(pool)]))

    def test_version_rebuilds_pool_and_accepts_new_ids(self):
        self.engine.insertion(programming(4), lambda x: x)
        self.engine.update(programming(8, 2))
        values = [self.engine.stations.next(programming(8)['stationIds'])['id'] for _ in range(8)]
        self.assertEqual(8, len(set(values)))
        self.assertTrue({'s4', 's5', 's6', 's7'}.issubset(values))

    def test_repeat_window_new_track_and_progressive_relaxation(self):
        self.record(item('a'))
        self.engine.last_music = 'a'  # Most recent actual playback, despite inserting backdated history.
        self.assertEqual('b', self.engine.music([item('a'), item('b')])['id'])
        self.record(item('b'), self.now - 100)
        self.engine.last_music = 'a'  # Most recent actual playback, despite inserting backdated history.
        self.assertEqual('b', self.engine.music([item('a'), item('b')])['id'])
        self.assertEqual('new', self.engine.music([item('a'), item('b'), item('new')])['id'])

    def test_six_hours_block_is_kept_when_eligible_options_exist(self):
        for i in range(10): self.record(item(str(i)), self.now - 1000)
        candidates = [item(str(i)) for i in range(10)] + [item('old'), item('new')]
        self.assertIn(self.engine.music(candidates)['id'], {'old', 'new'})

    def test_track_becomes_eligible_after_six_hours(self):
        self.record(item('old'), self.now - 6 * 3600 - 1)
        self.record(item('last'))
        self.assertEqual('old', self.engine.music([item('old'), item('last')])['id'])

    def test_restart_preserves_history_cycle_and_bag(self):
        self.record(item('m'))
        selected = self.engine.insertion(programming(), lambda x: x)
        self.record(selected)
        checkpoint = self.engine.checkpoint()
        self.store.close(); self.store = Storage(self.path)
        restarted = ProgrammingEngine(self.store, lambda: self.now)
        self.assertEqual(checkpoint, restarted.checkpoint())
        self.assertEqual('m', restarted.last_music)
        self.assertEqual({'m'}, set(restarted.storage.history()))
        self.assertEqual('STATION_ID', restarted.insertion(programming(), lambda x: x)['type'])

    def test_preload_and_short_content_do_not_count_as_music(self):
        self.engine.music([item('m')])
        self.engine.insertion(programming(), lambda x: x)
        self.assertFalse(self.store.history())
        for kind in ['STATION_ID', 'JINGLE', 'NEWS_INTRO', 'NEWS_DROP', 'TIME_ANNOUNCEMENT']:
            self.record(item(kind, kind))
        self.assertFalse(self.store.history())

    def test_removed_track_reconciled_new_music_immediately_eligible(self):
        self.record(item('removed'))
        self.assertEqual('new', self.engine.music([item('new')])['id'])
        self.assertFalse(self.store.history())

    def test_invalid_music_is_temporarily_excluded(self):
        self.engine.failed(item('bad'))
        self.assertEqual('good', self.engine.music([item('bad'), item('good')])['id'])

    def test_invalid_station_and_jingle_try_alternatives_without_double_insert(self):
        p = programming()
        def prepare(value):
            if value['id'] in {'s0', 's1', 'j0'}: raise ValueError('fixture')
            return value
        for _ in range(15):
            selected = self.engine.insertion(p, prepare)
            self.assertNotIn(selected['id'], {'s0', 's1', 'j0'})

    def test_all_short_files_invalid_returns_music_without_stopping(self):
        def broken(_): raise ValueError('fixture')
        for _ in range(3): self.assertIsNone(self.engine.insertion(programming(), broken))
        self.assertIsNotNone(self.engine.music([item('m')]))

    def test_single_music_catalog_never_strands_a_short_insert(self):
        self.assertEqual('only', self.engine.music([item('only')], ['only'])['id'])

    def test_artist_window_when_catalog_artist_exists(self):
        self.record(dict(item('a'), artist='Artist'))
        catalog = [dict(item('b'), artist='Artist'), dict(item('c'), artist='Other')]
        self.assertEqual('c', self.engine.music(catalog)['id'])


class FakeCache:
    def __init__(self, root): self.directory = Path(root) / 'cache'; self.directory.mkdir()
    def prepare(self, value):
        path = self.directory / (value['id'] + '.mp3')
        path.write_bytes(b'prepared fixture')
        return dict(value, path=str(path), duration=value.get('duration', 200))
    def prune(self, _): pass


class PlannerTests(EngineFixture):
    def planner(self, candidate=None):
        class News:
            def candidate(_, played, prepare): return None if candidate is None or candidate['id'] in played else prepare(candidate)
        class Times:
            def ready(_, boundary): return None
        catalogs = type('Catalogs', (), {'music': {'items': [item(f'm{i}') for i in range(30)]}, 'programming': programming()})()
        return Planner(catalogs, self.engine, FakeCache(self.tmp.name), News(), Times(), lambda: self.now)

    def test_timeline_music_insert_music_is_ready_before_boundary(self):
        planner = self.planner()
        planner.fill_once(); planner.fill_once()
        values = [entry['item']['type'] for entry in planner.ready]
        self.assertEqual(['MUSIC', 'STATION_ID', 'MUSIC'], values)
        self.assertFalse(self.store.history())
        self.assertTrue(all(entry['item'].get('path') for entry in planner.ready))

    def test_news_replaces_only_one_slot_and_never_consumes_cycle(self):
        planner = self.planner(item('news', 'NEWS_DROP', 60))
        self.engine.position = 1
        planner.fill_once()
        planner.end_of_plan += config.NEWS_INTERVAL
        planner.fill_once()
        self.assertEqual(['MUSIC', 'NEWS_INTRO', 'NEWS_DROP', 'MUSIC'], [entry['item']['type'] for entry in planner.ready])
        self.assertEqual(1, self.engine.position)
        planner.fill_once()
        self.assertEqual('STATION_ID', planner.ready[-2]['item']['type'])

    def test_missing_news_does_not_play_intro_alone(self):
        planner = self.planner()
        planner.fill_once(); planner.end_of_plan += config.NEWS_INTERVAL; planner.fill_once()
        self.assertEqual(['MUSIC', 'STATION_ID', 'MUSIC'], [entry['item']['type'] for entry in planner.ready])

    def test_acknowledgement_only_marks_actual_playback_and_is_idempotent(self):
        planner = self.planner(); planner.fill_once()
        token = planner.ready[0]['token']; id = planner.ready[0]['item']['id']
        planner.next(); self.assertFalse(self.store.history())
        planner.started(token); played = self.store.history()[id]['played_at']
        self.now += 10; planner.started(token)
        self.assertEqual(played, self.store.history()[id]['played_at'])

    def test_liquidsoap_restart_discards_unplayed_reservations_not_history(self):
        planner = self.planner(); planner.fill_once(); planner.fill_once()
        token = planner.ready[0]['token']; planner.next(); planner.started(token)
        planner.reset_requested = True
        self.assertEqual('', planner.next())
        planner.reset_if_needed()
        self.assertTrue(self.store.history())
        self.assertEqual(0, planner.engine.position)
        planner.fill_once()
        self.assertNotEqual(self.store.get('last_music'), planner.ready[0]['item']['id'])

    def test_short_pieces_have_no_music_fade_clipping_or_crossfade(self):
        self.assertIn('liq_fade_out="15.0"', request_uri(item('m'), 'token'))
        for kind in ['STATION_ID', 'JINGLE', 'NEWS_INTRO', 'NEWS_DROP', 'TIME_ANNOUNCEMENT']:
            value = item(kind, kind, 8)
            if kind == 'TIME_ANNOUNCEMENT': value['slot'] = self.now
            uri = request_uri(value, 'token')
            self.assertIn('liq_fade_out="0.0"', uri)
            self.assertNotIn('liq_cue_out', uri)
            self.assertEqual(8, value['duration'])

    def test_cold_health_waits_for_prepared_music_insert_music(self):
        planner = self.planner()
        self.assertFalse(planner.health())
        planner.fill_once()
        self.assertFalse(planner.health())
        planner.fill_once()
        self.assertTrue(planner.health())

    def test_news_clock_and_safe_boundary(self):
        self.assertFalse(self.engine.news_due(self.now))
        self.assertFalse(self.engine.news_due(self.now + 1700))
        self.assertTrue(self.engine.news_due(self.now + 1800))
        self.assertFalse(self.store.played_news())


class CatalogTests(unittest.TestCase):
    def test_programming_json_is_dynamic_and_invalid_items_are_ignored(self):
        p = programming(); p['stationIds'].append({'id': 'bad', 'type': 'STATION_ID'})
        self.assertEqual(8, len(parse_programming(p)['stationIds']))
        self.assertEqual(3, len(parse_programming(p)['jingles']))

    def test_music_parser_rejects_empty_catalog_and_missing_url(self):
        with self.assertRaises(ValueError): parse_music({'version': 1, 'items': []})
        p = {'version': 1, 'items': [item('ok'), {'id': 'bad', 'type': 'MUSIC', 'title': 'bad'}]}
        self.assertEqual(1, len(parse_music(p)['items']))

    def test_last_valid_catalog_and_programming_survive_network_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as root:
            fixture = {'music': {'version': 1, 'items': [item('m')]}, 'program': programming()}
            catalogs = Catalogs(root, lambda url: json.dumps(fixture[url]).encode())
            catalogs.refresh('music', 'program')
            def offline(_): raise OSError('fixture')
            catalogs = Catalogs(root, offline); catalogs.refresh('music', 'program')
            self.assertEqual(1, len(catalogs.music['items']))
            self.assertEqual(8, len(catalogs.programming['stationIds']))
            self.assertTrue((Path(root) / 'music.m3u').exists())


if __name__ == '__main__': unittest.main()
