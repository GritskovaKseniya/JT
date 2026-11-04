"""Le ultime tabelle cercate nello strumento Names (`Settings.search_history`, `add_search`)."""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))

import helpers  # noqa: E402
from jt.settings import Settings  # noqa: E402


class SearchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.paths = helpers.make_paths(self.tmp)
        self.settings = Settings(self.paths)

    def test_the_file_lives_with_the_other_user_files(self):
        self.assertEqual(os.path.basename(self.paths.searches), 'search_history.json')
        self.assertEqual(os.path.dirname(self.paths.searches), os.path.dirname(self.paths.query))

    def test_it_starts_empty(self):
        self.assertEqual(self.settings.search_history(), [])

    def test_searches_are_kept_once_and_sorted_by_the_physical_name(self):
        self.settings.add_search('MD_ARTI', 'Articolo')
        self.settings.add_search('GD_LIRIG', 'RigaListino')
        self.settings.add_search('MD_ARTI', 'Articolo')
        self.assertEqual(self.settings.search_history(), [{'fisico': 'GD_LIRIG', 'logico': 'RigaListino'},
                                                          {'fisico': 'MD_ARTI', 'logico': 'Articolo'}])

    def test_the_same_physical_table_with_another_logical_name_is_another_entry(self):
        self.settings.add_search('MD_ARTI', 'Articolo')
        self.settings.add_search('MD_ARTI', 'ArticoloEsteso')
        self.assertEqual(len(self.settings.search_history()), 2)

    def test_it_never_holds_more_than_the_limit(self):
        for number in range(Settings.MAX_SEARCHES + 10):
            self.settings.add_search(f'TAB_{number:03d}', 'x')
        history = self.settings.search_history()
        self.assertEqual(len(history), Settings.MAX_SEARCHES)
        self.assertEqual(history[-1]['fisico'], f'TAB_{Settings.MAX_SEARCHES + 9:03d}')

    def test_a_damaged_file_is_treated_as_empty(self):
        for content in ('{not json', '{"a": 1}', '[1, "x", {"fisico": ""}, {"fisico": "OK", "logico": "y"}]'):
            with self.subTest(content=content):
                with open(self.paths.searches, 'w', encoding='utf-8') as f:
                    f.write(content)
                history = self.settings.search_history()
                self.assertEqual(history, [{'fisico': 'OK', 'logico': 'y'}] if 'OK' in content else [])

    def test_the_release_check_treats_it_as_personal_data(self):
        sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
        import release
        self.assertIn('search_history.json', release.PERSONAL_NAMES)
        with open(os.path.join(HERE, '..', '.gitignore'), encoding='utf-8') as f:
            self.assertIn('Data/search_history.json', f.read())


if __name__ == '__main__':
    unittest.main()
