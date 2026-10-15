import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_boundaries import prepared_boundaries
from sync_catalog import request_uri


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.mp3'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
            'sine=frequency=440:duration=2', '-af', 'adelay=400,apad=pad_dur=1',
            '-c:a', 'libmp3lame', str(self.path)], check=True)

    def test_music_always_ends_twenty_seconds_before_physical_file_end(self):
        music = Path(self.tmp.name) / 'music.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',
            'sine=frequency=440:duration=25','-c:a','libmp3lame',str(music)],check=True)
        before = hashlib.sha256(music.read_bytes()).digest()
        result = prepared_boundaries(music, 'MUSIC')
        self.assertEqual(0, result['cue_in'])
        self.assertAlmostEqual(5., result['cue_out'], delta=.08)
        self.assertAlmostEqual(5., result['duration'], delta=.08)
        self.assertEqual(before, hashlib.sha256(music.read_bytes()).digest())

    def test_music_too_short_for_mandatory_twenty_second_trim_is_rejected(self):
        with self.assertRaises(ValueError):
            prepared_boundaries(self.path, 'MUSIC')

    def test_inserts_keep_entire_voice_and_tail_only_trim_silent_head(self):
        for kind in ('STATION_ID', 'JINGLE'):
            result = prepared_boundaries(self.path, kind)
            self.assertAlmostEqual(.38, result['cue_in'], delta=.05)
            self.assertAlmostEqual(3.4, result['cue_out'], delta=.05)
            uri = request_uri(dict(result, id='s', type=kind, title='s', path=str(self.path)), 't')
            self.assertIn('liq_fade_out="0.0"', uri)
            self.assertIn('liq_cue_in=', uri)

    def test_news_and_time_not_changed(self):
        for kind in ('NEWS_INTRO', 'NEWS_DROP', 'TIME_ANNOUNCEMENT'):
            self.assertEqual({}, prepared_boundaries(self.path, kind))

    def test_analysis_reused_after_restart(self):
        result = prepared_boundaries(self.path, 'STATION_ID')
        with patch('audio_boundaries.measure', side_effect=AssertionError('unnecessary decode')):
            self.assertEqual(result, prepared_boundaries(self.path, 'STATION_ID'))

    def test_music_end_policy_does_not_depend_on_tail_amplitude(self):
        quiet = Path(self.tmp.name) / 'quiet.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=25',
            '-af','volume=0.001','-c:a','libmp3lame',str(quiet)],check=True)
        result=prepared_boundaries(quiet,'MUSIC')
        self.assertAlmostEqual(5.,result['cue_out'],delta=.08)

    def test_internal_silence_does_not_change_fixed_music_end(self):
        internal = Path(self.tmp.name) / 'internal.mp3'
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=440:duration=25',
            '-af',"volume=0:enable='between(t,1,2)'",'-c:a','libmp3lame',str(internal)],check=True)
        result=prepared_boundaries(internal,'MUSIC')
        self.assertAlmostEqual(5.,result['duration'],delta=.08)
