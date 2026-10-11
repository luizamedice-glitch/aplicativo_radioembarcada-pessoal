"""Real small MP3 fixtures; no licensed library, internet or credentials needed."""
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_programming import EngineFixture, FakeCache, item, programming
from audio_cache import probe
from sync_catalog import Planner

class EmergencyTests(EngineFixture):
    def planner(self):
        cache = FakeCache(self.tmp.name)
        catalogs = Mock(music={'items': [item('m')]}, programming=programming())
        return Planner(catalogs, self.engine, cache, Mock(), Mock(), lambda: self.now)

    def audio(self, planner, name):
        path = planner.cache.directory / (name + '.mp3')
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.2', '-c:a', 'libmp3lame', str(path)], check=True)
        path.chmod(0o644)
        return dict(item(name), path=str(path), duration=probe(path))

    def test_m3u_contains_only_real_local_valid_audio_and_no_metadata_or_secrets(self):
        planner = self.planner()
        values = [self.audio(planner, name) for name in ('first', 'second', 'third', 'fourth')]
        for value in values: planner._emergency(value)
        lines = (Path(self.tmp.name) / 'emergency.m3u').read_text().splitlines()
        self.assertEqual('#EXTM3U', lines[0])
        self.assertEqual([value['path'] for value in values[-3:]], lines[1:])
        for line in lines[1:]:
            self.assertTrue(Path(line).is_absolute() and Path(line).is_file())
            self.assertGreater(probe(line), 0)
            self.assertNotIn('annotate:', line)
            self.assertNotIn('http', line)
            self.assertNotIn('token', line)
            self.assertNotIn('metadata:', line)

    def test_restart_replaces_legacy_annotated_m3u_without_network_or_new_music(self):
        planner = self.planner(); value = self.audio(planner, 'cached')
        root = Path(self.tmp.name)
        (root / 'emergency.json').write_text(json.dumps([value]))
        (root / 'emergency.m3u').write_text('#EXTM3U\nannotate:radio_token="emergency":'+value['path']+'\n')
        restored = Planner(planner.catalogs, self.engine, planner.cache, Mock(), Mock(), lambda:self.now)
        self.assertTrue(restored.restored_emergency)
        self.assertEqual(['#EXTM3U',value['path']], (root/'emergency.m3u').read_text().splitlines())
        self.assertFalse(self.store.history())

    def test_unsafe_paths_missing_files_and_non_music_are_never_written(self):
        planner = self.planner()
        for path in ['https://example.test/audio.mp3','annotate:x:/data/a.mp3',
                     '/tmp/outside.mp3',str(planner.cache.directory/'missing.mp3'),
                     str(planner.cache.directory/'a\nsecret.mp3'),None]:
            planner._emergency(dict(item('bad'),path=path))
        self.assertEqual([],planner.emergency)
        value=self.audio(planner,'intro')
        planner._emergency(dict(value,type='STATION_ID'))
        self.assertEqual([],planner.emergency)

    def test_fallback_ack_never_mutates_official_history_or_cycle(self):
        planner=self.planner(); value=self.audio(planner,'cached')
        planner._emergency(value)
        before=self.engine.checkpoint()
        planner.started('emergency',value['id'])
        planner.started('unknown',value['id'])
        self.assertEqual({},self.store.history())
        self.assertEqual(before,self.engine.checkpoint())

    def test_next_skips_disappeared_audio_and_preserves_principal_annotations(self):
        planner=self.planner()
        first=planner.cache.prepare(item('first')); second=planner.cache.prepare(item('second'))
        planner._append(first); planner._append(second)
        Path(first['path']).unlink()
        uri=planner.next()
        self.assertTrue(uri.startswith('annotate:'))
        self.assertIn('radio_id="second"',uri)
        self.assertEqual(1,len(planner.delivered))

if __name__=='__main__': unittest.main()
