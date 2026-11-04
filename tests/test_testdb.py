"""Lo strumento che crea il database di prova (tools/create_test_db.py)."""
import os
import sqlite3
import sys
import unittest

import helpers
from jt.catalog import Catalog
from jt.config import Paths
from jt.layers import BY_NAME, VISIBLE
from jt.tables import get_table

sys.path.insert(0, os.path.join(helpers.ROOT, 'tools'))
import create_test_db as tool  # noqa: E402
import simulate  # noqa: E402
import extract_sample  # noqa: E402


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
        # l'originale entra nella colonna (100 caratteri) ma tradotto la supera: ORA-12899 nel log degli errori
        italian = [row[4] for row in tool.DATA['FW_OBJ_DESCRS'] if row[3] == 'it']
        self.assertTrue(all(len(text) <= 100 for text in italian))
        self.assertTrue(any(len(text) + 5 > 100 for text in italian))
        self.assertTrue(any(row[1] == 'ProcessiLunghi' for row in tool.DATA['FW_OPZIONI']))


class LevelSampleDataTests(unittest.TestCase):
    """Le righe di prova per il campo Level: ognuno dei livelli visibili ha qualcosa da tradurre."""

    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.cursor = self.db.cursor()
        for name, columns in tool.SCHEMA.items():
            self.cursor.execute(f'CREATE TABLE {name} ({columns})')
        tool.fill_tables(self.cursor)
        self.addCleanup(self.db.close)

    def missing(self, table, level):
        spec = get_table(table).bind_columns(tool._columns(table))
        sql, binds = spec.count_all('it', 'en', level=level)
        return self.cursor.execute(sql, binds).fetchone()[0]

    def test_strings_and_triplets_have_rows_in_every_visible_level(self):
        for table in ('FW_STRINGS', 'FW_FIELD_STRINGS'):
            counts = {name: self.missing(table, BY_NAME[name]) for name in VISIBLE}
            counts['All'] = self.missing(table, None)
            with self.subTest(table=table):
                self.assertTrue(all(counts[name] > 0 for name in VISIBLE), counts)
                self.assertEqual(sum(counts[name] for name in VISIBLE), counts['All'])      # nessun livello perso

    def test_options_have_rows_in_every_visible_level_and_the_wrong_case_is_not_standard(self):
        counts = {name: self.missing('FW_OPZIONI', BY_NAME[name]) for name in VISIBLE}
        total = self.missing('FW_OPZIONI', None)
        self.assertTrue(all(count > 0 for count in counts.values()), counts)
        # Standard esclude CtStatoCliente, CwStatoIntegrazione e anche ctMinuscolo (UPPER). Il LIKE di CT/CW qui non si
        # prova per il minuscolo: SQLite non distingue le maiuscole, Oracle si' (lo dice il test su layer_of_name).
        self.assertEqual(counts['AP'], total - 3)

    def test_category_samples_exist_in_the_source_rows(self):
        categories = {row[3] for row in tool.DATA['FW_STRINGS'] if row[0] == 'it'}
        self.assertTrue({'MES', 'MCS', 'WMS', ' ', None} <= categories)

    def test_one_ct_row_is_already_translated_to_try_update_by_keys(self):
        self.assertTrue(any(row[:2] == ('de', 3000003) for row in tool.DATA['FW_STRINGS']))


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


class SampleFromARealDatabaseTests(unittest.TestCase):
    """Righe vere copiate con tools/extract_sample.py e aggiunte a quelle di prova."""

    TINY = {'tables': {
        'FW_STRINGS': {'columns': ['LANGUAGE', 'CODE', 'VALUE', 'CATEGORY', 'LASTUSER', 'LASTDATE'],
                       'types': ['VARCHAR', 'NUMBER', 'VARCHAR', 'VARCHAR', 'VARCHAR', 'DATE'],
                       'rows': [['it', 3000100, 'Riga vera CT', 'CT', ' ', '2025-03-19T10:20:30'],
                                ['it', 100000, 'Questa ha la chiave di una riga di prova', 'MES', ' ', None]]},
        'FW_DOCU_NODES_T': {'columns': ['NODEID', 'LANG', 'NODETITLE'], 'types': ['NUMBER', 'CHAR', 'VARCHAR'],
                            'rows': [[900, 'it', 'Nodo vero']]},
        'FW_FIELD_STRINGS': {'columns': ['SOLO', 'DUE'], 'types': ['VARCHAR', 'VARCHAR'], 'rows': [['a', 'b']]},
        'TABELLA_SCONOSCIUTA': {'columns': ['A'], 'types': ['VARCHAR'], 'rows': [['x']]},
    }}

    def test_real_rows_are_added_and_a_duplicate_key_is_skipped(self):
        merged = tool.with_sample(tool.DATA, self.TINY)
        codes = [row[1] for row in merged['FW_STRINGS'] if row[0] == 'it']
        self.assertEqual(codes.count(100000), 1)                                    # la riga di prova resta, quella vera no
        self.assertIn(3000100, codes)
        self.assertEqual(len(merged['FW_STRINGS']), len(tool.DATA['FW_STRINGS']) + 1)
        self.assertEqual(len(merged['FW_DOCU_NODES_T']), len(tool.DATA['FW_DOCU_NODES_T']) + 1)

    def test_dates_come_back_as_datetime_and_the_originals_are_untouched(self):
        before = {name: list(rows) for name, rows in tool.DATA.items()}
        merged = tool.with_sample(tool.DATA, self.TINY)
        row = next(r for r in merged['FW_STRINGS'] if r[1] == 3000100)
        self.assertEqual(row[5].isoformat(), '2025-03-19T10:20:30')
        self.assertEqual(tool.DATA, before)

    def test_a_table_with_another_shape_or_unknown_is_ignored(self):
        merged = tool.with_sample(tool.DATA, self.TINY)
        self.assertEqual(merged['FW_FIELD_STRINGS'], tool.DATA['FW_FIELD_STRINGS'])
        self.assertNotIn('TABELLA_SCONOSCIUTA', merged)

    def test_an_empty_sample_changes_nothing(self):
        self.assertEqual(tool.with_sample(tool.DATA, {}), tool.DATA)

    def test_the_simulator_loads_real_rows_and_jt_works_on_them(self):
        from jt.db import Database
        from jt.layers import BY_NAME
        from jt.service import TranslationService
        sim = simulate.Simulator(self.TINY)
        db = Database(driver=sim)
        db.connect('h', '1', 's', 'u', 'p')
        service = TranslationService(db)
        selection = service.load_missing(get_table('FW_STRINGS'), 'it', 'fr', 1000, BY_NAME['CT'])
        result = service.run(selection, simulate.SimTranslator())
        self.assertEqual(result.errors, [])
        row = sim.query("SELECT usr, info FROM FW_STRINGS WHERE language = 'fr' AND code = 3000100")[0]
        self.assertEqual(row, ('ZFXCUSTOM', 'CT'))

    def test_the_command_line_wants_gui_with_a_sample(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            simulate.main(['--sample', 'x.json'])


class _Description:
    def __init__(self, name):
        self.name = name


class ExtractSampleTests(unittest.TestCase):
    def test_values_become_json_friendly_and_char_padding_goes_away(self):
        from datetime import datetime
        self.assertEqual(extract_sample.clean(datetime(2025, 3, 19, 10, 20, 30)), '2025-03-19T10:20:30')
        self.assertEqual(extract_sample.clean('JT                  '), 'JT')
        self.assertEqual(extract_sample.clean('    '), ' ')              # un campo di soli spazi resta un blank (in Oracle '' e' NULL)
        self.assertEqual(extract_sample.clean(''), ' ')
        self.assertEqual(extract_sample.clean(42), 42)
        self.assertIsNone(extract_sample.clean(None))

    def test_only_select_statements_are_accepted(self):
        self.assertEqual(extract_sample.read_only('  select * from t'), '  select * from t')
        for sql in ('DELETE FROM t', 'UPDATE t SET a = 1', 'INSERT INTO t VALUES (1)', 'DROP TABLE t', 'BEGIN null; END;'):
            with self.assertRaises(ValueError):
                extract_sample.read_only(sql)

    def test_every_shipped_query_is_a_select(self):
        self.assertEqual(set(extract_sample.SELECTS), set(tool.SCHEMA))
        for table, sql in extract_sample.SELECTS.items():
            extract_sample.read_only(sql)
            self.assertIn(table, sql)

    def test_build_sample_reads_columns_types_and_rows_and_survives_a_missing_table(self):
        from datetime import datetime

        class Cursor:
            def __init__(self):
                self.executed, self.description, self.rows = [], [], []

            def execute(self, sql):
                self.executed.append(sql)
                if 'MISSING' in sql:
                    raise RuntimeError('ORA-00942: table or view does not exist')
                self.description = [('CODE', _Description('DB_TYPE_NUMBER'), 1, 1, 1, 0, 0),
                                    ('LASTUSER', _Description('DB_TYPE_CHAR'), 20, 80, None, None, 0),
                                    ('LASTDATE', _Description('DB_TYPE_DATE'), 23, None, None, None, 1)]
                self.rows = [(7, 'JT   ', datetime(2026, 1, 2, 3, 4, 5))]

            def fetchall(self):
                return self.rows

        class Connection:
            def __init__(self):
                self.cursor_ = Cursor()

            def cursor(self):
                return self.cursor_

        connection, lines = Connection(), []
        sample = extract_sample.build_sample(connection, {'T1': 'SELECT * FROM T1', 'MISSING': 'SELECT * FROM MISSING'},
                                 out=lines.append)
        self.assertEqual(sample['tables']['T1'], {'columns': ['CODE', 'LASTUSER', 'LASTDATE'],
                                                  'types': ['NUMBER', 'CHAR', 'DATE'],
                                                  'rows': [[7, 'JT', '2026-01-02T03:04:05']]})
        self.assertNotIn('MISSING', sample['tables'])
        self.assertTrue(any('MISSING: skipped' in line for line in lines))
        self.assertTrue(all(sql.startswith('SELECT') for sql in connection.cursor_.executed))

    def test_the_sample_file_is_never_committed(self):
        with open(os.path.join(helpers.ROOT, '.gitignore'), encoding='utf-8') as f:
            self.assertIn('tools/sample_data.json', f.read())
