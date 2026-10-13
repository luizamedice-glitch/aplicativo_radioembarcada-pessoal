import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

from import_r2_zip import import_archive
from prepare_test_music import MusicArchiveError


class ImportZipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.work = Path(self.tmp.name)
        self.uploads = []
        self.known = {}

    def archive(self, files):
        path = self.work / 'input.zip'
        with zipfile.ZipFile(path, 'w') as z:
            for name, data in files:
                z.writestr(name, data)
        return path

    def run_import(self, files, probe=lambda path: None):
        return import_archive(self.archive(files), self.work, self.known,
                              lambda path, key, sha: self.uploads.append((path.read_bytes(), key, sha)), probe)

    def test_subfolders_only_mp3_and_original_archive_preserved(self):
        result = self.run_import([('album/Áudio.MP3', b'audio'), ('cover.jpg', b'image')])
        self.assertEqual(1, len(result['uploaded']))
        self.assertEqual(1, len(result['ignored']))
        self.assertTrue(result['uploaded'][0]['key'].endswith('/Áudio.MP3'))
        self.assertTrue((self.work / 'input.zip').exists())
        self.assertFalse((self.work / 'track.mp3').exists())

    def test_same_bytes_different_names_and_rerun_do_not_duplicate(self):
        self.run_import([('a.mp3', b'audio'), ('b.mp3', b'audio')])
        self.assertEqual(1, len(self.uploads))
        result = self.run_import([('a.mp3', b'audio')])
        self.assertEqual(1, len(result['duplicates']))
        self.assertEqual(1, len(self.uploads))

    def test_identical_names_different_content_do_not_overwrite(self):
        result = self.run_import([('a/song.mp3', b'first'), ('b/song.mp3', b'second')])
        self.assertEqual(2, len({item['key'] for item in result['uploaded']}))

    def test_traversal_rejected_before_upload(self):
        with self.assertRaises(MusicArchiveError):
            self.run_import([('good.mp3', b'audio'), ('../bad.mp3', b'audio')])
        self.assertEqual([], self.uploads)

    def test_corrupt_audio_skipped_but_valid_music_kept(self):
        def probe(path):
            if path.read_bytes() == b'bad':
                raise ValueError('Bad audio')
        result = self.run_import([('a.mp3', b'good'), ('bad.mp3', b'bad')], probe)
        self.assertEqual(1, len(result['uploaded']))
        self.assertEqual(1, len(result['ignored']))

    def test_empty_archive_fails(self):
        with self.assertRaises(ValueError):
            self.run_import([('cover.jpg', b'image')])

    def test_upload_failure_propagates_without_marking_known(self):
        def fail(*args):
            raise RuntimeError('network failed')
        with self.assertRaises(RuntimeError):
            import_archive(self.archive([('a.mp3', b'a')]), self.work, self.known, fail, lambda p: None)
        self.assertEqual({}, self.known)

    def test_real_ffmpeg_audio_validation(self):
        from import_r2_zip import inspect_audio
        tone = self.work / 'tone.mp3'
        subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=0.2', '-c:a', 'libmp3lame', str(tone)], check=True)
        result = self.run_import([('tiny.mp3', tone.read_bytes()), ('broken.mp3', b'not audio')], inspect_audio)
        self.assertEqual(1, len(result['uploaded']))
        self.assertEqual(1, len(result['ignored']))
