"""Le etichette dell'ambiente (jt/environments.py) e come si ricordano (Settings)."""
import unittest

import helpers
from helpers import JtCase, read_json, write_json
from jt import environments
from jt.layers import BY_NAME, users_written
from jt.settings import Settings


class EnvironmentsModuleTests(unittest.TestCase):
    def test_only_the_three_labels_are_valid(self):
        for value, expected in (('dev', 'dev'), ('TEST', 'test'), (' Prod ', 'prod'), ('production', ''), ('', ''),
                                (None, ''), ('Not set', ''), (3, '')):
            self.assertEqual(environments.normalize(value), expected, repr(value))

    def test_not_set_and_prod_are_strict(self):
        for value, strict in (('', True), (None, True), ('prod', True), ('PROD', True), ('production', True),
                              ('dev', False), ('test', False), ('Test', False)):
            self.assertEqual(environments.is_strict(value), strict, repr(value))

    def test_labels_for_the_field(self):
        self.assertEqual(environments.CHOICES, ('Not set', 'dev', 'test', 'prod'))
        self.assertEqual([environments.to_label(v) for v in ('', 'dev', 'prod', 'x')], ['Not set', 'dev', 'prod', 'Not set'])
        self.assertEqual([environments.from_label(v) for v in ('Not set', 'dev', 'test', 'prod')], ['', 'dev', 'test', 'prod'])

    def test_a_database_is_recognised_ignoring_case_and_spaces(self):
        self.assertEqual(environments.key('Rete-UD-6 ', 1521, 'ora319'), environments.key('rete-ud-6', '1521', ' ORA319'))
        self.assertNotEqual(environments.key('a', '1521', 'X'), environments.key('a', '1522', 'X'))
        self.assertNotEqual(environments.key('a', '1521', 'X'), environments.key('b', '1521', 'X'))

    def test_each_label_has_a_chip_text_and_a_palette_colour(self):
        from jt.ui.theme import PALETTE
        self.assertEqual([environments.chip(v) for v in ('dev', 'test', 'prod', '')],
                         [('DEV', 'accent'), ('TEST', 'ok'), ('PROD', 'error'), ('NOT SET', 'warn')])
        for _text, color in (environments.chip(v) for v in ('dev', 'test', 'prod', '')):
            self.assertIn(color, PALETTE)
        self.assertEqual(environments.chip('production'), ('NOT SET', 'warn'))


class EnvironmentSettingsTests(JtCase):
    def setUp(self):
        super().setUp()
        self.paths_ = self.paths()
        self.settings = Settings(self.paths_)

    def test_a_label_is_remembered_per_database(self):
        self.assertEqual(self.settings.environment('h', '1521', 'S'), '')
        self.settings.save_environment('h', '1521', 'S', 'prod')
        self.settings.save_environment('h', '1521', 'OTHER', 'test')
        self.assertEqual(self.settings.environment('h', '1521', 'S'), 'prod')
        self.assertEqual(self.settings.environment('h', '1521', 'OTHER'), 'test')
        self.assertEqual(self.settings.environment('h2', '1521', 'S'), '')

    def test_case_and_spaces_of_the_database_do_not_matter(self):
        self.settings.save_environment('Host ', 1521, 'sid', 'dev')
        self.assertEqual(self.settings.environment('host', '1521', 'SID'), 'dev')

    def test_saving_not_set_or_garbage_removes_the_label(self):
        self.settings.save_environment('h', '1', 'S', 'prod')
        self.settings.save_environment('h', '1', 'S', '')
        self.assertEqual(self.settings.environment('h', '1', 'S'), '')
        self.settings.save_environment('h', '1', 'S', 'test')
        self.settings.save_environment('h', '1', 'S', 'whatever')
        self.assertEqual(self.settings.environment('h', '1', 'S'), '')

    def test_the_connection_data_and_the_labels_do_not_overwrite_each_other(self):
        self.settings.save_connection('h', '1521', 'S', 'u', 'p')
        self.settings.save_environment('h', '1521', 'S', 'prod')
        self.settings.save_connection('h2', '1522', 'S2', 'u2', 'p2')
        self.assertEqual(self.settings.environment('h', '1521', 'S'), 'prod')
        self.assertEqual(self.settings.connection(), {'host': 'h2', 'port': '1522', 'sid': 'S2', 'username': 'u2',
                                                      'password': 'p2'})                 # le etichette non si vedono qui

    def test_a_damaged_file_or_a_wrong_shape_is_tolerated(self):
        write_json(self.paths_.connection, {'host': 'h', 'environments': ['not', 'a', 'dict']})
        self.assertEqual(self.settings.environment('h', '1', 'S'), '')
        self.settings.save_environment('h', '1', 'S', 'dev')                          # si ricostruisce
        self.assertEqual(self.settings.environment('h', '1', 'S'), 'dev')
        write_json(self.paths_.connection, {'environments': {environments.key('h', '1', 'S'): 'weird'}})
        self.assertEqual(self.settings.environment('h', '1', 'S'), '')

    def test_the_labels_live_in_the_personal_connection_file(self):
        self.settings.save_environment('h', '1521', 'S', 'prod')
        self.assertEqual(read_json(self.paths_.connection)['environments'], {environments.key('h', '1521', 'S'): 'prod'})


class UsersWrittenTests(unittest.TestCase):
    def test_one_user_with_a_level_and_all_of_them_without(self):
        self.assertEqual(users_written(BY_NAME['CT']), ('ZFXCUSTOM',))
        self.assertEqual(users_written(BY_NAME['CW']), ('ZFXINTEGR',))
        self.assertEqual(users_written(BY_NAME['CC']), ('ZFXCCSYS',))
        self.assertEqual(users_written(BY_NAME['AP']), ('JT',))
        self.assertEqual(users_written(None), ('JT', 'ZFXCUSTOM', 'ZFXINTEGR', 'ZFXCCSYS'))

    def test_a_table_without_levels_always_writes_the_tool_marker(self):
        self.assertEqual(users_written(BY_NAME['CT'], supports_levels=False), ('JT',))
        self.assertEqual(users_written(None, supports_levels=False), ('JT',))


if __name__ == '__main__':
    unittest.main()
