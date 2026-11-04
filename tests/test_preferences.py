import os
import tempfile
import unittest

from jt.preferences import Preferences


class PreferencesTests(unittest.TestCase):
    def make(self, text=None):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, 'preferences.json')
        if text is not None:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
        return Preferences(path)

    def test_a_missing_or_broken_file_gives_the_defaults(self):
        for text in (None, '{not json', '[1, 2]', ''):
            prefs = self.make(text)
            self.assertEqual(prefs.default_tool(), '')
            self.assertFalse(prefs.get('tecsql', 'strip_parameters'))
            self.assertIsNone(prefs.names_sort())
            self.assertEqual(prefs.names_hidden(), set())

    def test_values_are_read(self):
        prefs = self.make('{"default_tool": " Names ", "tecsql": {"strip_parameters": true},'
                          ' "names": {"sort": "campo_logico", "descending": true, "hide_columns": ["decimali"]},'
                          ' "indexes": {"expand_all": true}}')
        self.assertEqual(prefs.default_tool(), 'names')
        self.assertTrue(prefs.get('tecsql', 'strip_parameters'))
        self.assertEqual(prefs.names_sort(), ('CAMPO_LOGICO', False))
        self.assertEqual(prefs.names_hidden(), {'DECIMALI'})
        self.assertTrue(prefs.get('indexes', 'expand_all'))

    def test_a_value_of_the_wrong_type_or_an_unknown_column_is_ignored(self):
        prefs = self.make('{"default_tool": 5, "tecsql": {"strip_parameters": "yes"}, "names": {"sort": "NOPE", "hide_columns": "x"},'
                          ' "indexes": []}')
        self.assertEqual(prefs.default_tool(), '')
        self.assertFalse(prefs.get('tecsql', 'strip_parameters'))
        self.assertIsNone(prefs.names_sort())
        self.assertEqual(prefs.names_hidden(), set())
        self.assertFalse(prefs.get('indexes', 'expand_all'))

    def test_comments_with_double_slash_are_ignored_but_not_inside_strings(self):
        prefs = self.make("""{
  // un commento
  "order tools": ["strings",
    //"names",
    "indexes"], "default_tool": "http://x//y"
}""")
        self.assertEqual(prefs.order_tools(), ['strings', 'indexes'])
        self.assertEqual(prefs.default_tool(), 'http://x//y')

    def test_tools_are_ordered_and_the_missing_ones_hidden(self):
        from types import SimpleNamespace as T
        tools = [T(name=n) for n in ('strings', 'tecsql', 'names', 'indexes')]
        names = lambda prefs: [t.name for t in prefs.arrange(tools)]
        self.assertEqual(names(self.make('{"order tools": ["indexes", "strings", "tecsql"]}')), ['indexes', 'strings', 'tecsql'])
        self.assertEqual(names(self.make('{"order tools": ["strings", "strings", "nope"]}')), ['strings'])
        self.assertEqual(names(self.make('{"order tools": ["nope"]}')), ['strings', 'tecsql', 'names', 'indexes'])   # niente app vuota
        self.assertEqual(names(self.make('{"order tools": []}')), ['strings', 'tecsql', 'names', 'indexes'])
        self.assertEqual(names(self.make(None)), ['strings', 'tecsql', 'names', 'indexes'])


if __name__ == '__main__':
    unittest.main()
