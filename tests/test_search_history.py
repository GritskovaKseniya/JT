"""La storia delle ricerche di tabelle (`SearchHistory`, `Settings.searches`): una per database, le piu' recenti prima."""
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))

import helpers  # noqa: E402
from jt.jsonstore import write_json  # noqa: E402
from jt.search_history import SearchHistory  # noqa: E402
from jt.settings import Settings  # noqa: E402

DB = 'rete-ud-6:1521/ORA319'


class SearchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = helpers.make_paths(self.tmp)
        self.settings = Settings(self.paths)
        self.history = self.settings.searches(DB)

    def texts(self, history=None):
        return [e['text'] for e in (history or self.history).entries()]

    def test_the_file_lives_with_the_other_user_files(self):
        self.assertEqual(os.path.basename(self.paths.searches), 'search_history.json')
        self.assertEqual(os.path.dirname(self.paths.searches), os.path.dirname(self.paths.query))

    def test_it_starts_empty(self):
        self.assertEqual(self.history.entries(), [])

    def test_what_you_typed_is_what_is_remembered_with_the_table_found(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        self.history.add('MD_ARTI', 'MD_ARTI', 'Articolo')
        self.assertEqual(self.texts(), ['MD_ARTI', 'Articolo'])
        self.assertEqual(self.history.entries()[1]['physical'], 'MD_ARTI')
        self.assertTrue(self.history.entries()[0]['last_used'])

    def test_the_most_recent_is_first_and_a_repeated_search_moves_up_without_a_double(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        self.history.add('GD_LIRIG', 'GD_LIRIG', 'RigaListino')
        self.history.add('articolo', 'MD_ARTI', 'Articolo')               # maiuscole e minuscole contano come uno
        self.assertEqual(self.texts(), ['articolo', 'GD_LIRIG'])

    def test_each_database_has_its_own_history(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        other = self.settings.searches('altro:1521/XE')
        self.assertEqual(other.entries(), [])
        other.add('FW_TABLES', 'FW_TABLES', 'FwTables')
        self.assertEqual(self.texts(), ['Articolo'])
        self.assertEqual(self.texts(other), ['FW_TABLES'])

    def test_one_search_can_be_removed_and_everything_can_be_cleared(self):
        for text in ('A', 'B', 'C'):
            self.history.add(text, text, text)
        self.history.remove('b')
        self.assertEqual(self.texts(), ['C', 'A'])
        other = self.settings.searches('altro:1521/XE')
        other.add('X', 'X', 'X')
        self.history.clear()
        self.assertEqual(self.history.entries(), [])
        self.assertEqual(self.texts(other), ['X'])                       # le altre basi non si toccano

    def test_it_filters_on_what_is_typed_in_the_text_the_physical_or_the_logical_name(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        self.history.add('GD_LIRIG', 'GD_LIRIG', 'RigaListino')
        self.assertEqual([e['text'] for e in self.history.matching('art')], ['Articolo'])
        self.assertEqual([e['text'] for e in self.history.matching('md_')], ['Articolo'])          # dal nome fisico
        self.assertEqual([e['text'] for e in self.history.matching('lisT')], ['GD_LIRIG'])         # dal nome logico
        self.assertEqual(len(self.history.matching('')), 2)
        self.assertEqual(self.history.matching('zzz'), [])

    def test_the_limit_comes_from_the_preferences(self):
        for number in range(60):
            self.history.add(f'TAB_{number:02d}', 'x', 'x')
        self.assertEqual(len(self.history.entries()), 50)                # predefinito
        self.assertEqual(self.texts()[0], 'TAB_59')
        write_json(self.paths.preferences, {'history': {'max': 3}})
        self.assertEqual(self.texts(self.settings.searches(DB)), ['TAB_59', 'TAB_58', 'TAB_57'])
        write_json(self.paths.preferences, {'history': {'max': 0}})                                 # valore assurdo: almeno una
        self.assertEqual(len(self.settings.searches(DB).entries()), 1)

    def test_the_fields_are_part_of_the_search_and_a_search_with_other_fields_is_another_entry(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        self.history.add('Articolo', 'MD_ARTI', 'Articolo', 'arti_camp1, arti_camp2')
        self.history.add('articolo', 'MD_ARTI', 'Articolo', ' ARTI_CAMP1, arti_camp2 ')            # la stessa: sale in cima, nessun doppione
        entries = self.history.entries()
        self.assertEqual([self.history.label(e) for e in entries], ['articolo \u00b7 ARTI_CAMP1, arti_camp2', 'Articolo'])
        self.assertEqual([e['text'] for e in self.history.matching('camp2')], ['articolo'])        # si cerca anche nei campi

    def test_removing_one_search_keeps_the_same_table_with_other_fields(self):
        self.history.add('Articolo', 'MD_ARTI', 'Articolo')
        self.history.add('Articolo', 'MD_ARTI', 'Articolo', 'a, b')
        self.history.remove('articolo', 'A, B')
        self.assertEqual([e['fields'] for e in self.history.entries()], [''])

    def test_each_tool_has_its_own_history_and_only_names_inherits_the_one_from_before(self):
        write_json(self.paths.searches, {'databases': {DB: [{'text': 'MD_ARTI', 'physical': 'MD_ARTI', 'logical': 'Articolo'}]}})
        names, indexes = self.settings.searches(DB, 'names'), self.settings.searches(DB, 'indexes')
        self.assertEqual([e['text'] for e in names.entries()], ['MD_ARTI'])
        self.assertEqual(indexes.entries(), [])
        indexes.add('GD_LIRIG', 'GD_LIRIG', 'RigaListino')
        self.assertEqual([e['text'] for e in names.entries()], ['MD_ARTI'])
        self.assertEqual([e['text'] for e in indexes.entries()], ['GD_LIRIG'])

    def test_the_old_file_passes_once_to_the_first_database_without_doubles(self):
        write_json(self.paths.searches, [{'fisico': 'MD_ARTI', 'logico': 'Articolo'}, {'fisico': 'MD_ARTI', 'logico': 'ArticoloEsteso'},
                                         {'fisico': 'GD_LIRIG', 'logico': 'RigaListino'}])
        self.assertEqual(sorted(self.texts()), ['GD_LIRIG', 'MD_ARTI'])
        self.assertEqual(self.settings.searches('altro:1521/XE').entries(), [])      # il secondo database non le eredita
        with open(self.paths.searches, encoding='utf-8') as f:
            self.assertIn('databases', json.load(f))

    def test_a_damaged_file_is_treated_as_empty(self):
        for content in ('{not json', '{"a": 1}', '[1, "x", {"fisico": ""}]', '{"databases": 5}'):
            with self.subTest(content=content):
                with open(self.paths.searches, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.assertEqual(self.history.entries(), [])

    def test_the_standalone_class_works_without_settings(self):
        history = SearchHistory(self.paths.searches, 'db', limit=2)
        for text in ('a', 'b', 'c'):
            history.add(text, text, text)
        self.assertEqual([e['text'] for e in history.entries()], ['c', 'b'])

    def test_the_release_check_treats_it_as_personal_data(self):
        sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
        import release
        self.assertIn('search_history.json', release.PERSONAL_NAMES)
        with open(os.path.join(HERE, '..', '.gitignore'), encoding='utf-8') as f:
            self.assertIn('Data/search_history.json', f.read())


if __name__ == '__main__':
    unittest.main()
