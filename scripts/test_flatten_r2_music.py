import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

from flatten_r2_music import plan_moves
from r2_music_paths import IMPORT_PREFIX, flat_key

BASE = 'https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/'


class FlattenTest(unittest.TestCase):
    def setUp(self):
        self.key = IMPORT_PREFIX + 'a' * 64 + '/Canção.mp3'
        self.obj = {'Key': self.key, 'Size': 100, 'ETag': 'etag'}
        self.catalog = {'version': 9, 'station': 'Rádio Alce', 'items': [
            {'id': 'unchanged-id', 'type': 'MUSIC', 'title': 'Canção', 'artist': 'Artista',
             'url': BASE + quote(self.key, safe='/')}]}

    def test_moves_only_url_and_version_preserving_history_identity(self):
        before = copy.deepcopy(self.catalog)
        moves, result = plan_moves([self.obj], self.catalog)
        self.assertEqual(IMPORT_PREFIX + 'Canção.mp3', moves[0]['target'])
        self.assertEqual(10, result['version'])
        self.assertEqual('unchanged-id', result['items'][0]['id'])
        for field in ('type', 'title', 'artist'):
            self.assertEqual(before['items'][0][field], result['items'][0][field])
        self.assertEqual(before, self.catalog)
        self.assertEqual(BASE + quote(moves[0]['target'], safe='/'), result['items'][0]['url'])

    def test_equal_names_do_not_overwrite_different_audio(self):
        other = dict(self.obj, Key=self.key.replace('a' * 64, 'b' * 64))
        moves, _ = plan_moves([self.obj, other], self.catalog)
        self.assertEqual(2, len({m['target'] for m in moves}))
        self.assertTrue(all('/' not in m['target'][len(IMPORT_PREFIX):] for m in moves))

    def test_resume_reuses_verified_existing_destination(self):
        flat = dict(self.obj, Key=IMPORT_PREFIX + 'Canção.mp3', Metadata={'sha256': 'a' * 64})
        moves, _ = plan_moves([self.obj, flat], self.catalog)
        self.assertEqual(flat['Key'], moves[0]['target'])

    def test_unrelated_destination_is_not_overwritten(self):
        flat = dict(self.obj, Key=IMPORT_PREFIX + 'Canção.mp3')
        moves, _ = plan_moves([self.obj, flat], self.catalog)
        self.assertNotEqual(flat['Key'], moves[0]['target'])

    def test_no_moves_does_not_bump_version(self):
        moves, result = plan_moves([], self.catalog)
        self.assertEqual([], moves)
        self.assertEqual(self.catalog, result)

    def test_future_imports_are_flat(self):
        key = flat_key('uploads-zip/album/música.mp3', 'a' * 64, {})
        self.assertEqual(IMPORT_PREFIX + 'música.mp3', key)

    def test_next_catalog_sync_keeps_migrated_id(self):
        moves, updated = plan_moves([self.obj], self.catalog)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'keys.json').write_text(json.dumps([moves[0]['target']]))
            (folder / 'old.json').write_text(json.dumps(updated))
            subprocess.run([sys.executable, str(Path(__file__).with_name('sync_r2_catalog.py')),
                            '--keys', str(folder / 'keys.json'), '--old-catalog', str(folder / 'old.json'),
                            '--output', str(folder / 'new.json'), '--public-base', BASE.rstrip('/')], check=True,
                           capture_output=True)
            result = json.loads((folder / 'new.json').read_text())
            self.assertEqual(updated['items'], result['items'])
