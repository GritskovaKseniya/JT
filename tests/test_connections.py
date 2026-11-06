"""I profili di connessione (`ConnectionProfiles`): un file .json per database nella cartella `connections`."""
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
from jt.connections import ConnectionProfiles  # noqa: E402
from jt.settings import Settings  # noqa: E402

VALUES = {'host': 'rete-ud-6', 'port': '1521', 'sid': 'ora319', 'username': 'u', 'password': 'p', 'environment': 'test'}


class ConnectionProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.profiles = ConnectionProfiles(os.path.join(self.tmp, 'connections'))

    def test_the_folder_is_among_the_user_files(self):
        paths = helpers.make_paths(self.tmp)
        self.assertEqual(os.path.basename(paths.connections), 'connections')
        self.assertEqual(os.path.dirname(paths.connections), os.path.dirname(paths.query))
        self.assertIsInstance(Settings(paths).profiles(), ConnectionProfiles)

    def test_it_starts_empty_even_without_the_folder(self):
        self.assertEqual(self.profiles.list(), [])
        self.assertFalse(self.profiles.exists())

    def test_a_profile_is_saved_read_and_replaced(self):
        self.profiles.save('Test 319', VALUES)
        profile = self.profiles.get('test 319')                         # maiuscole e minuscole non contano
        self.assertEqual((profile['host'], profile['sid'], profile['password'], profile['environment']),
                         ('rete-ud-6', 'ora319', 'p', 'test'))
        self.profiles.save('Test 319', {**VALUES, 'host': 'altro'})
        self.assertEqual([p['host'] for p in self.profiles.list()], ['altro'])
        self.assertEqual(len(os.listdir(self.profiles.folder)), 1)      # lo stesso file, non un doppione

    def test_the_file_is_readable_and_has_the_name_inside(self):
        self.profiles.save('Prod: Genova?', VALUES)                     # caratteri che Windows non accetta nel nome del file
        file = os.listdir(self.profiles.folder)[0]
        self.assertNotIn('?', file)
        self.assertNotIn(':', file)
        with open(os.path.join(self.profiles.folder, file), encoding='utf-8') as f:
            self.assertEqual(json.load(f)['name'], 'Prod: Genova?')

    def test_two_names_that_give_the_same_file_name_do_not_overwrite_each_other(self):
        self.profiles.save('a?b', VALUES)
        self.profiles.save('a:b', {**VALUES, 'host': 'altro'})
        self.assertEqual(sorted(p['host'] for p in self.profiles.list()), ['altro', 'rete-ud-6'])

    def test_the_most_recent_is_first_and_use_moves_a_profile_up(self):
        self.profiles.save('A', VALUES, last_used='2026-01-01T10:00:00')
        self.profiles.save('B', VALUES, last_used='2026-02-01T10:00:00')
        self.assertEqual(self.profiles.names(), ['B', 'A'])
        self.profiles.touch('A')
        self.assertEqual(self.profiles.names(), ['A', 'B'])

    def test_a_profile_can_be_deleted(self):
        self.profiles.save('A', VALUES)
        self.profiles.delete('a')
        self.assertEqual(self.profiles.list(), [])
        self.assertTrue(self.profiles.exists())                         # la cartella resta: non si migra di nuovo
        self.profiles.delete('niente')                                  # inesistente: niente

    def test_a_file_copied_by_hand_is_enough_and_a_broken_one_is_skipped(self):
        os.makedirs(self.profiles.folder)
        with open(os.path.join(self.profiles.folder, 'Collega.json'), 'w', encoding='utf-8') as f:
            f.write('{"host": "h", "port": 1521, "sid": "S", "username": "u", "environment": "weird"}')
        for name, text in (('rotto.json', '{not json'), ('lista.json', '[1]'), ('vuoto.json', '{}'), ('note.txt', 'x')):
            with open(os.path.join(self.profiles.folder, name), 'w', encoding='utf-8') as f:
                f.write(text)
        profiles = self.profiles.list()
        self.assertEqual([p['name'] for p in profiles], ['Collega'])         # senza nome nel file: quello del file
        self.assertEqual((profiles[0]['port'], profiles[0]['password'], profiles[0]['environment']), ('1521', '', ''))

    def test_same_database_ignores_case_and_spaces(self):
        profile = self.profiles.save('A', VALUES)
        self.assertTrue(self.profiles.same_database(profile, {**VALUES, 'host': ' RETE-UD-6 ', 'sid': 'ORA319'}))
        self.assertFalse(self.profiles.same_database(profile, {**VALUES, 'username': 'other'}))

    def test_the_last_connection_becomes_the_first_profile_once(self):
        saved = {'host': 'rete-ud-6', 'port': '1521', 'sid': 'ora319', 'username': 'u', 'password': 'p'}
        profile = self.profiles.migrate(saved, 'prod')
        self.assertEqual((profile['name'], profile['environment']), ('ora319 @ rete-ud-6', 'prod'))
        self.assertIsNone(self.profiles.migrate(saved, 'prod'))               # la seconda volta no
        self.profiles.delete('ora319 @ rete-ud-6')
        self.assertIsNone(self.profiles.migrate(saved, 'prod'))               # nemmeno se li ha cancellati
        self.assertEqual(self.profiles.list(), [])

    def test_nothing_to_migrate_without_a_saved_connection(self):
        self.assertIsNone(self.profiles.migrate({'host': '', 'sid': ''}))
        self.assertFalse(self.profiles.exists())


if __name__ == '__main__':
    unittest.main()
