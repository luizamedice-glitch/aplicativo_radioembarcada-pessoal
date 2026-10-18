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
    def test_news_interval_is_four_hours_not_half_hour(self):
        self.assertEqual(14400, config.NEWS_INTERVAL)
        for elapsed in (1800, 3600, 7200, 14399):
            self.assertFalse(self.engine.news_due(self.now + elapsed))
        self.assertTrue(self.engine.news_due(self.now + 14400))

    def test_news_legacy_half_hour_checkpoint_migrates_without_resetting_cycle(self):
        legacy_boundary = int(self.now // 1800) * 1800
        self.store.put('programming', {'last_news_slot': int(self.now // 1800), 'position': 2})
        restarted = ProgrammingEngine(self.store, lambda: self.now)
        self.assertEqual(2, restarted.position)
        self.assertFalse(restarted.news_due(legacy_boundary + 14399))
        self.assertTrue(restarted.news_due(legacy_boundary + 14400))
        self.assertEqual(legacy_boundary, self.store.get('programming')['last_news_boundary'])

    def test_news_actual_playback_overrides_older_planned_boundary(self):
        self.engine.reserve_news(self.now)
        self.now += 120
        self.engine.started(item('news', 'NEWS_DROP'), self.engine.checkpoint())
        for engine in (self.engine, ProgrammingEngine(self.store, lambda: self.now)):
            self.assertFalse(engine.news_due(self.now + 14399))
            self.assertTrue(engine.news_due(self.now + 14400))

    def test_news_reservation_survives_restart_without_consuming_cycle(self):
        boundary = self.now + config.NEWS_INTERVAL
        self.engine.position = 1
        self.engine.reserve_news(boundary)
        self.engine.started(item('intro', 'NEWS_INTRO'), self.engine.checkpoint())
        self.store.close()
        self.store = Storage(self.path)
        restarted = ProgrammingEngine(self.store, lambda: boundary + 30)
        self.assertEqual(1, restarted.position)
        self.assertFalse(restarted.news_due(boundary + 1800))
        self.assertTrue(restarted.news_due(boundary + 14400))

    def test_news_initial_anchor_survives_restart_without_any_playback(self):
        started_at = self.now
        self.now += 7200
        restarted = ProgrammingEngine(self.store, lambda: self.now)
        self.assertFalse(restarted.news_due(started_at + 14399))
        self.assertTrue(restarted.news_due(started_at + 14400))

    def test_news_timestamp_supports_future_interval_change_and_legacy_rollback(self):
        self.engine.reserve_news(self.now)
        checkpoint = self.engine.checkpoint()
        self.assertEqual(int(self.now // 1800), checkpoint['last_news_slot'])
        self.store.put('programming', checkpoint)
        with patch.object(config, 'NEWS_INTERVAL', 5 * 3600):
            restarted = ProgrammingEngine(self.store, lambda: self.now)
            self.assertFalse(restarted.news_due(self.now + 14400))
            self.assertTrue(restarted.news_due(self.now + 18000))

    def test_reserved_genre_station_ids_never_enter_random_pool(self):
        p = programming()
        p['stationIds'] += [
            dict(item('rock-id', 'STATION_ID', 8), title='Vinheta Rock Internacional'),
            dict(item('disco-id', 'STATION_ID', 8), title='Disco Anos 80'),
        ]
        values = [self.engine.insertion(p, lambda x: x, allow_jingle=False)['id'] for _ in range(20)]
        self.assertNotIn('rock-id', values)
        self.assertNotIn('disco-id', values)

    def test_reserved_genre_station_ids_pair_only_with_target_music(self):
        p = programming()
        p['stationIds'] += [
            dict(item('rock-id', 'STATION_ID', 8), title='Rock Internacional'),
            dict(item('disco-id', 'STATION_ID', 8), title='Disco Anos 80'),
        ]
        rock = dict(item('cant-stop'), title="Can't Stop Loving You")
        disco = dict(item('tarzan'), title='Tarzan Boy')
        other = dict(item('other'), title='California Dreamin')
        self.assertEqual('rock-id', self.engine.paired_insertion(p, rock, lambda x: x)['id'])
        self.assertEqual('disco-id', self.engine.paired_insertion(p, disco, lambda x: x)['id'])
        self.assertIsNone(self.engine.paired_insertion(p, other, lambda x: x))

    def test_station_id_fills_every_boundary_until_hourly_jingle_is_due(self):
        p = programming()
        for _ in range(6):
            self.assertEqual('STATION_ID', self.engine.insertion(
                p, lambda value: value, allow_jingle=False)['type'])

    def test_jingle_is_time_based_and_resets_only_after_actual_playback(self):
        p = programming()
        self.assertFalse(self.engine.jingle_due())
        self.now += config.JINGLE_INTERVAL
        self.assertTrue(self.engine.jingle_due())
        jingle = self.engine.insertion(p, lambda value: value, allow_jingle=True)
        self.assertEqual('JINGLE', jingle['type'])
        # Preparation alone does not consume the one-hour clock.
        self.assertTrue(self.engine.jingle_due())
        self.engine.started(jingle, self.engine.checkpoint())
        self.assertFalse(self.engine.jingle_due())

    def test_unavailable_hourly_jingle_falls_back_to_station_id_not_music(self):
        p = programming()
        def prepare(value):
            if value['type'] == 'JINGLE':
                raise ValueError('fixture jingle failure')
            return value
        selected = self.engine.insertion(p, prepare, allow_jingle=True)
        self.assertEqual('STATION_ID', selected['type'])

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
        for _ in range(8):
            selected = self.engine.insertion(p, prepare, allow_jingle=False)
            self.assertNotIn(selected['id'], {'s0', 's1'})
        selected = self.engine.insertion(p, prepare, allow_jingle=True)
        self.assertEqual('JINGLE', selected['type'])
        self.assertNotEqual('j0', selected['id'])

    def test_all_short_files_invalid_returns_music_without_stopping(self):
        def broken(_): raise ValueError('fixture')
        for _ in range(3):
            self.assertIsNone(self.engine.insertion(programming(), broken, allow_jingle=False))
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

    def test_italian_block_sequence_and_schedule(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        planner = self.planner()
        slot = datetime(2026, 10, 18, 16, 10, tzinfo=ZoneInfo(config.TIME_ZONE)).timestamp()
        planner.end_of_plan = slot
        block = planner._italian_block(slot)
        self.assertEqual(5, len(block))
        self.assertEqual(['STATION_ID','MUSIC','MUSIC','STATION_ID','MUSIC'],
                         [value['type'] for value in block])
        self.assertEqual(3, len({value['id'] for value in block if value['type'] == 'MUSIC'}))
        self.assertEqual(slot, block[0]['special_block_slot'])
        self.assertIsNone(planner._italian_block(slot))

    def test_italian_block_only_runs_at_configured_times(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        planner = self.planner()
        outside = datetime(2026, 10, 18, 16, 30, tzinfo=ZoneInfo(config.TIME_ZONE)).timestamp()
        self.assertIsNone(planner._italian_block(outside))

    def test_timeline_music_insert_music_is_ready_before_boundary(self):
        planner = self.planner()
        planner.fill_once(); planner.fill_once()
        values = [entry['item']['type'] for entry in planner.ready]
        self.assertEqual(['MUSIC', 'STATION_ID', 'MUSIC'], values)
        self.assertFalse(self.store.history())
        self.assertTrue(all(entry['item'].get('path') for entry in planner.ready))


    def test_hour_announcement_is_additive_and_never_replaces_normal_insert(self):
        planner = self.planner()
        class Times:
            def ready(_, boundary):
                return {'id':'time-fixture','type':'TIME_ANNOUNCEMENT','title':'Hora certa',
                        'path':'/data/cache/time.mp3','duration':3,'slot':boundary}
        planner.times = Times()
        planner.fill_once()
        planner.end_of_plan = self.now
        planner.fill_once()
        self.assertEqual(['MUSIC','STATION_ID','TIME_ANNOUNCEMENT','MUSIC'],
                         [entry['item']['type'] for entry in planner.ready])

    def test_hour_slot_is_persisted_only_after_actual_playback(self):
        planner = self.planner()
        slot = self.now
        value = {'id':'time-fixture','type':'TIME_ANNOUNCEMENT','title':'Hora certa',
                 'path':'/data/cache/time.mp3','duration':3,'slot':slot}
        planner._append(value)
        token = planner.ready[-1]['token']
        planner.next()
        self.assertEqual(0, self.store.get('last_time_slot', 0))
        planner.started(token)
        self.assertEqual(slot, self.store.get('last_time_slot'))

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

    def test_music_request_always_carries_full_fifteen_second_fade_and_cue_out(self):
        self.assertIn('liq_fade_out="15.0"', request_uri(item('m', duration=5), 'token'))
        cued = item('m')
        cued['cue_out'] = 180.0
        self.assertIn('liq_cue_out="180.0"', request_uri(cued, 'token'))

    def test_short_pieces_have_no_music_fade_clipping_or_crossfade(self):
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
        self.assertFalse(self.engine.news_due(self.now + config.NEWS_INTERVAL - 1))
        self.assertTrue(self.engine.news_due(self.now + config.NEWS_INTERVAL))
        self.assertFalse(self.store.played_news())


class CatalogTests(unittest.TestCase):
    def test_temporarily_disabled_spots_are_filtered_without_changing_other_jingles(self):
        p = programming()
        p['jingles'] += [
            item('jingle-spot-bifao', 'JINGLE', 30),
            item('jingle-spot-salao-flack', 'JINGLE', 30),
        ]
        parsed = parse_programming(p)
        ids = {value['id'] for value in parsed['jingles']}
        self.assertNotIn('jingle-spot-bifao', ids)
        self.assertNotIn('jingle-spot-salao-flack', ids)
        self.assertEqual({'j0', 'j1', 'j2'}, ids)

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
