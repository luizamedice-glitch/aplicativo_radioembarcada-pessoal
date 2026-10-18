import importlib.util
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest

SPEC = importlib.util.spec_from_file_location('pipeline', Path(__file__).parents[1] / 'pipeline.py')
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)


class Store:
    def __init__(self):
        self.calls = []
        self.fail = False

    def put_object(self, **kwargs):
        if self.fail and kwargs['Key'].endswith('.ts'):
            raise OSError('simulated upload failure')
        self.calls.append(kwargs)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.name = 'a' * 32 + '-100.ts'
        (self.root / self.name).write_bytes(b'audio')
        (self.root / 'live.m3u8').write_text('#EXTM3U\n#EXTINF:10,\n' + self.name + '\n')
        self.store = Store()
        self.publisher = p.Publisher(self.store, 'test', 'alce-test')

    def test_segments_before_manifest_and_no_reupload(self):
        self.assertTrue(self.publisher.publish(self.root))
        self.assertTrue(self.store.calls[0]['Key'].endswith('.ts'))
        self.assertTrue(self.store.calls[-1]['Key'].endswith('.m3u8'))
        self.assertFalse(self.publisher.publish(self.root))
        self.assertEqual(2, len(self.store.calls))

    def test_failed_upload_never_publishes_playlist_and_recovers(self):
        self.store.fail = True
        with self.assertRaises(OSError):
            self.publisher.publish(self.root)
        self.assertEqual([], self.store.calls)
        self.store.fail = False
        self.assertTrue(self.publisher.publish(self.root))

    def test_missing_segment_preserves_previous_manifest(self):
        (self.root / self.name).unlink()
        with self.assertRaises(FileNotFoundError):
            self.publisher.publish(self.root)
        self.assertEqual([], self.store.calls)

    def test_path_traversal_and_remote_urls_rejected(self):
        for entry in ['../secret.ts', 'https://example.com/a.ts', '/etc/passwd']:
            with self.assertRaises(ValueError):
                p.segments('#EXTM3U\n' + entry)

    def test_stale_manifest_not_published(self):
        import os
        os.utime(self.root / 'live.m3u8', (0, 0))
        with self.assertRaises(ValueError):
            self.publisher.publish(self.root)
        self.assertFalse(self.store.calls)

    def test_cleanup_keeps_reader_grace_window(self):
        import os
        old = self.root / ('b' * 32 + '-1.ts')
        old.write_bytes(b'old')
        os.utime(old, (time.time() - 601, time.time() - 601))
        p.clean(self.root)
        self.assertFalse(old.exists())
        self.assertTrue((self.root / self.name).exists())


class AudioTests(unittest.TestCase):
    def test_real_mp3_to_hls_aac_is_audible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'input.mp3'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                'sine=frequency=440:duration=65', '-c:a', 'libmp3lame', '-b:a', '128k',
                str(source)], check=True)
            subprocess.run(p.command(str(source), root, 'a' * 32), check=True)
            names = p.segments((root / 'live.m3u8').read_text())
            self.assertEqual(6, len(names))
            self.assertTrue(all((root / n).stat().st_size > 0 for n in names))
            result = subprocess.run(['ffmpeg', '-hide_banner', '-i', str(root / 'live.m3u8'),
                '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True, check=True)
            mean = float(re.search(r'mean_volume: ([\d.-]+)', result.stderr)[1])
            peak = float(re.search(r'max_volume: ([\d.-]+)', result.stderr)[1])
            print(f'HLS synthetic output mean={mean}dB peak={peak}dB')
            self.assertGreater(mean, -40)
            self.assertGreater(peak, -25)
            codec = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0',
                '-show_entries', 'stream=codec_name', '-of', 'csv=p=0', str(root / names[0])],
                capture_output=True, text=True, check=True)
            self.assertIn('aac', codec.stdout)


if __name__ == '__main__':
    unittest.main()
