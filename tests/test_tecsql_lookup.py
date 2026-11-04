"""Il dizionario dei nomi e le funzioni di ricerca del traduttore TecSQL (portati da JCTNT, da pytest a unittest):
mappe giuste dopo `update_mappings`, maiuscole/minuscole originali conservate, `_find_matching_descriptors`."""
import unittest

import tecsql_fixtures as fx
from jt.tecsql_translator import Dictionary, _normalize_table_key


class MappingLoadedTests(fx.TecsqlCase):
    def test_logical_to_physical_table(self):
        key = _normalize_table_key('RigaListino')
        self.assertEqual(self.d.table_map.get(key, '').upper(), 'GD_LIRIG')

    def test_logical_to_physical_field(self):
        key = _normalize_table_key('RigaListino')
        # il nome logico del campo e' normalizzato (minuscolo, senza spazi)
        self.assertEqual(self.d.field_map.get(key, {}).get('codlistino', '').upper(), 'LIRIG_LICOD')

    def test_reverse_field_map(self):
        descriptor_map = self.d.reverse_field_map.get('gd_lirig', {}).get('lirig_licod', {})
        self.assertTrue(descriptor_map, 'REVERSE_FIELD_MAP non ha LIRIG_LICOD per GD_LIRIG')
        self.assertTrue(any('codlistino' in v for v in descriptor_map.values()))


class OriginalCaseTests(fx.TecsqlCase):
    def test_table_original_case(self):
        key = _normalize_table_key('RigaListino')
        self.assertEqual(self.d.table_original_case.get(key, ''), '$RigaListino')

    def test_field_original_case(self):
        table_key = _normalize_table_key('RigaListino')
        self.assertEqual(self.d.field_original_case.get((table_key, 'codlistino'), ''), 'CodListino')


class FindMatchingDescriptorsTests(fx.TecsqlCase):
    def test_exact_match_single_descriptor(self):
        result = self.d.find_descriptors('GD_LIRIG', ['LIRIG_LICOD', 'LIRIG_CATLI'])
        self.assertEqual(len(result['exact_matches']), 1)
        self.assertIn('rigalistino', result['exact_matches'][0])

    def test_unknown_table_returns_no_match(self):
        result = self.d.find_descriptors('TABELLA_CHE_NON_ESISTE', [])
        self.assertEqual(len(result['exact_matches']), 0)
        self.assertIsNone(result['best_match'])

    def test_no_fields_still_finds_descriptor(self):
        result = self.d.find_descriptors('GD_LIRIG', [])
        self.assertGreaterEqual(len(result['exact_matches']), 1)

    def test_lites_descriptor(self):
        result = self.d.find_descriptors('GD_LITES', ['LITES_LICOD'])
        self.assertEqual(len(result['exact_matches']), 1)
        self.assertIn('testatalistino', result['exact_matches'][0])


class AmbiguousDescriptorTests(unittest.TestCase):
    """Due nomi logici per la stessa tabella fisica (il caso che nell'originale era un TODO)."""

    def setUp(self):
        rows = fx.rows_as_dicts(fx.MOCK_ROWS) + fx.rows_as_dicts([
            ('GD_LIRIG', '$RigaListinoBis', 'LIRIG_LICOD', 'Codice', 'C', 10, 0),
            ('GD_LIRIG', '$RigaListinoBis', 'LIRIG_CATLI', 'Categoria', 'C', 2, 0),
        ])
        self.d = Dictionary(rows)

    def test_a_table_with_two_descriptors_has_two_exact_matches_when_both_cover_the_fields(self):
        result = self.d.find_descriptors('GD_LIRIG', ['LIRIG_LICOD'])
        self.assertEqual(sorted(result['exact_matches']), ['$rigalistino', '$rigalistinobis'])

    def test_a_field_only_one_descriptor_has_picks_that_one_and_lists_the_other_as_partial(self):
        result = self.d.find_descriptors('GD_LIRIG', ['LIRIG_PREZO'])
        self.assertEqual(result['exact_matches'], ['$rigalistino'])
        self.assertEqual(result['best_match'], '$rigalistino')
        partial = result['partial_matches']
        self.assertEqual([p['descriptor'] for p in partial], ['$rigalistinobis'])
        self.assertEqual(partial[0]['missing'], ['LIRIG_PREZO'])
        self.assertEqual(partial[0]['coverage'], 0)


if __name__ == '__main__':
    unittest.main()
