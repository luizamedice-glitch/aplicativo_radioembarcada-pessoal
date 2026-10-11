import unittest
from update_r2_programming import merge


class ProgrammingUpdateTest(unittest.TestCase):
    def setUp(self):
        self.current = dict(stationId='alce', version=5, rules={'preserve': True},
                            stationIds=[], jingles=[{'id': 'jingle'}], other='preserve')
        self.item = dict(id='new', type='STATION_ID', title='New',
                        url='https://pub-e38948fd737d4d969bb4e65eebed0249.r2.dev/new.mp3')

    def test_preserves_unrelated_fields_and_bumps_version_once(self):
        result = merge(self.current, [self.item])
        self.assertEqual(6, result['version'])
        self.assertEqual([self.item], result['stationIds'])
        for field in ('rules', 'jingles', 'other'):
            self.assertEqual(self.current[field], result[field])
        self.assertEqual([], self.current['stationIds'])
        self.assertEqual(result, merge(result, [self.item]))

    def test_conflict_does_not_overwrite_remote_configuration(self):
        self.current['stationIds'] = [dict(self.item, title='Existing')]
        with self.assertRaises(ValueError):
            merge(self.current, [self.item])

    def test_rejects_unapproved_urls(self):
        with self.assertRaises(ValueError):
            merge(self.current, [dict(self.item, url='http://example.org/a.mp3')])

    def test_all_three_approved_additions(self):
        import json
        from pathlib import Path
        items = json.loads(Path(__file__).with_name('station-id-additions.json').read_text())
        self.assertEqual(3, len(merge(self.current, items)['stationIds']))
