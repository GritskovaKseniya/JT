"""Lo strumento che crea il database di prova (tools/create_test_db.py)."""
import os
import sqlite3
import sys
import unittest

import helpers
from jt.catalog import Catalog
from jt.config import Paths
from jt.tables import get_table

sys.path.insert(0, os.path.join(helpers.ROOT, 'tools'))
import create_test_db as tool  # noqa: E402


class RecordingCursor:
    def __init__(self, log, present=(), users=0):
        self.log, self.present, self.users, self._rows = log, present, users, []

    def execute(self, sql, binds=None):
        self.log.append(sql)
        if 'user_tables' in sql:
            self._rows = [(name,) for name in self.present]
        elif 'all_users' in sql:
            self._rows = [(self.users,)]

    def executemany(self, sql, rows):
        self.log.append(sql)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0]


class RecordingConnection:
    def __init__(self, log, **kwargs):
        self.log, self.kwargs, self.commits, self.closed = log, kwargs, 0, False

    def cursor(self):
        return RecordingCursor(self.log, **self.kwargs)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class RecordingDriver:
    def __init__(self, **kwargs):
        self.log, self.kwargs, self.connections = [], kwargs, []

    def makedsn(self, host, port, sid):
        return f'{host}:{port}/{sid}'

    def connect(self, user, password, dsn=None):
        self.log.append(f'CONNECT {user}@{dsn}')
        connection = RecordingConnection(self.log, **self.kwargs)
        self.connections.append(connection)
        return connection


class SampleDataTests(unittest.TestCase):
    def test_every_enabled_table_has_a_schema_and_sample_rows(self):
        tables = [e['table'] for e in Catalog(Paths(helpers.ROOT)).tables()]
        self.assertTrue(tables)
        for table in tables:
            with self.subTest(table=table):
                self.assertIn(table, tool.SCHEMA)
                self.assertTrue(tool.DATA[table])

    def test_every_row_has_one_value_per_column(self):
        for table, rows in tool.DATA.items():
            width = len(tool._columns(table))
            for row in rows:
                self.assertEqual(len(row), width, (table, row))

    def test_there_is_always_something_to_translate_from_italian_and_something_already_done(self):
        db = sqlite3.connect(':memory:')
        cursor = db.cursor()
        for name, columns in tool.SCHEMA.items():
            cursor.execute(f'CREATE TABLE {name} ({columns})')
        tool.fill_tables(cursor)
        for table in tool.SCHEMA:
            spec = get_table(table).bind_columns(tool._columns(table))
            sql, binds = spec.count_all('it', 'en')
            missing = cursor.execute(sql, binds).fetchone()[0]
            italian = cursor.execute(f'SELECT COUNT(*) FROM {table} WHERE {spec.lang_col} = ?', ['it']).fetchone()[0]
            with self.subTest(table=table):
                self.assertGreater(missing, 0)
                self.assertLess(missing, italian)           # almeno una riga e' gia' tradotta (prova di Update)

    def test_the_odd_cases_are_there(self):
        texts = [row[2] for row in tool.DATA['FW_STRINGS'] if row[0] == 'it']
        self.assertIn(None, texts)                                       # testo vuoto
        self.assertTrue(any(t and not t.strip() for t in texts))         # solo spazi
        self.assertTrue(any(t and 'UMV' in t for t in texts))            # glossario
        self.assertTrue(any(t and "'" in t for t in texts))              # apostrofo
        self.assertTrue(any(t and 'ù' in t for t in texts))         # accento
        self.assertTrue(any(len(row[4]) > 100 for row in tool.DATA['FW_OBJ_DESCRS'] if row[3] == 'it'))
        self.assertTrue(any(row[1] == 'ProcessiLunghi' for row in tool.DATA['FW_OPZIONI']))


class PopulateTests(unittest.TestCase):
    def populate(self, present=(), **kwargs):
        log = []
        connection = RecordingConnection(log, present=present)
        return log, connection, tool.populate(connection, **kwargs)

    def test_an_empty_schema_gets_all_tables_the_marker_and_the_rows(self):
        log, connection, counts = self.populate()
        created = [sql for sql in log if sql.startswith('CREATE TABLE')]
        self.assertEqual(len(created), len(tool.SCHEMA) + 1)
        self.assertEqual(sum(counts.values()), sum(len(r) for r in tool.DATA.values()))
        self.assertEqual(connection.commits, 1)
        self.assertFalse([sql for sql in log if sql.startswith('DROP')])

    def test_real_tables_are_never_touched(self):
        log = []
        with self.assertRaisesRegex(RuntimeError, 'not a JT test database'):
            tool.populate(RecordingConnection(log, present=['FW_STRINGS', 'OTHER']))
        self.assertFalse([sql for sql in log if sql.startswith(('CREATE', 'DROP', 'INSERT', 'UPDATE'))])

    def test_an_existing_test_database_is_kept_unless_recreate_is_asked(self):
        present = ['FW_STRINGS', tool.MARKER_TABLE]
        with self.assertRaisesRegex(RuntimeError, '--recreate'):
            tool.populate(RecordingConnection([], present=present))
        log = []
        tool.populate(RecordingConnection(log, present=present), recreate=True)
        self.assertEqual(sorted(sql for sql in log if sql.startswith('DROP')),
                         ['DROP TABLE FW_STRINGS PURGE', f'DROP TABLE {tool.MARKER_TABLE} PURGE'])

    def test_recreate_never_drops_tables_it_does_not_own(self):
        log = []
        tool.populate(RecordingConnection(log, present=[tool.MARKER_TABLE, 'MY_PRECIOUS_TABLE']), recreate=True)
        self.assertFalse([sql for sql in log if 'MY_PRECIOUS_TABLE' in sql])


class RunTests(unittest.TestCase):
    def test_with_an_admin_the_test_user_is_created_and_used(self):
        driver = RecordingDriver(users=0)
        out = []
        user, password = tool.run(driver, 'h', '1521', 'S', 'SYSTEM', 'pw', admin=True, out=out.append)
        self.assertEqual((user, password), (tool.TEST_USER, tool.TEST_PASSWORD))
        self.assertEqual([c for c in driver.log if c.startswith('CONNECT')], ['CONNECT SYSTEM@h:1521/S', 'CONNECT JTTEST@h:1521/S'])
        self.assertTrue(any(sql.startswith('CREATE USER JTTEST') for sql in driver.log))
        self.assertTrue(all(c.closed for c in driver.connections))

    def test_an_existing_test_user_is_not_created_again(self):
        driver = RecordingDriver(users=1)
        tool.run(driver, 'h', '1521', 'S', 'SYSTEM', 'pw', admin=True, out=lambda *_: None)
        self.assertFalse(any(sql.startswith('CREATE USER') for sql in driver.log))

    def test_without_an_admin_the_tables_go_to_the_given_user(self):
        driver = RecordingDriver()
        user, _ = tool.run(driver, 'h', '1521', 'S', 'MYUSER', 'pw', out=lambda *_: None)
        self.assertEqual(user, 'MYUSER')
        self.assertEqual([c for c in driver.log if c.startswith('CONNECT')], ['CONNECT MYUSER@h:1521/S'])
        self.assertFalse(any('CREATE USER' in sql for sql in driver.log))

    def test_the_connection_is_closed_even_when_something_fails(self):
        driver = RecordingDriver(present=['FW_STRINGS'])
        with self.assertRaises(RuntimeError):
            tool.run(driver, 'h', '1521', 'S', 'MYUSER', 'pw', out=lambda *_: None)
        self.assertTrue(all(c.closed for c in driver.connections))

    def test_a_user_name_that_is_not_a_plain_identifier_is_refused(self):
        for bad in ('x; DROP USER y', 'a b', '', '1abc', 'a' * 31):
            with self.subTest(name=bad), self.assertRaises(ValueError):
                tool.check_name(bad)
        self.assertEqual(tool.check_name('system'), 'SYSTEM')


if __name__ == '__main__':
    unittest.main()
