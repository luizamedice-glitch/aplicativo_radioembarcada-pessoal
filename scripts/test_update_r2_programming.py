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

    def test_jingles_preserve_station_ids_rules_and_are_idempotent(self):
        import json
        from pathlib import Path
        items = json.loads(Path(__file__).with_name('jingle-additions.json').read_text())
        self.current['stationIds'] = [self.item]
        result = merge(self.current, items)
        self.assertEqual(2, len(items))
        self.assertTrue(all(item['type'] == 'JINGLE' for item in items))
        self.assertEqual(self.current['jingles'] + [{k: v for k, v in item.items() if k != 'replacesUrl'} for item in items], result['jingles'])
        self.assertEqual(self.current['stationIds'], result['stationIds'])
        self.assertEqual(self.current['rules'], result['rules'])
        self.assertEqual(6, result['version'])
        self.assertEqual(result, merge(result, items))

    def test_cross_pool_conflicts_are_rejected(self):
        self.current['stationIds'] = [self.item]
        with self.assertRaises(ValueError):
            merge(self.current, [dict(self.item, type='JINGLE')])

    def test_unsupported_type_is_rejected(self):
        with self.assertRaises(ValueError):
            merge(self.current, [dict(self.item, type='ADVERTISEMENT')])

    def test_explicit_url_replacement_preserves_id_and_pool(self):
        self.current['stationIds'] = [self.item]
        replacement = dict(self.item, url=self.item['url'].replace('new.mp3', 'corrected.mp3'),
                           replacesUrl=self.item['url'])
        result = merge(self.current, [replacement])
        self.assertEqual(1, len(result['stationIds']))
        self.assertEqual(replacement['url'], result['stationIds'][0]['url'])
        self.assertNotIn('replacesUrl', result['stationIds'][0])
        self.assertEqual(6, result['version'])
        self.assertEqual(result, merge(result, [replacement]))
        self.assertEqual(self.item, self.current['stationIds'][0])

    def test_replacement_requires_exact_previous_url(self):
        self.current['stationIds'] = [self.item]
        replacement = dict(self.item, url=self.item['url'].replace('new.mp3', 'corrected.mp3'),
                           replacesUrl='https://example.org/wrong.mp3')
        with self.assertRaises(ValueError):
            merge(self.current, [replacement])
