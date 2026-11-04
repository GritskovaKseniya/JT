"""Il dizionario completo di un database FW per il simulatore (`tools/fw_dictionary.py`) e i flag --fw / --translate."""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))

import fw_dictionary  # noqa: E402
import simulate as sim  # noqa: E402


class FakeCursor:
    def __init__(self, tables):
        self.tables, self.description, self.rows, self.executed = tables, None, [], []

    def execute(self, sql):
        self.executed.append(sql)
        for name, (columns, rows) in self.tables.items():
            if f'FROM {name} ' in sql + ' ':
                self.description = [(c,) for c in columns]
                self.rows = rows
                return
        raise AssertionError(sql)

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self):
        self.cursor_ = FakeCursor({
            'FW_TABLES': (['TABLENAME', 'TABLEDBNAME'], [('RigaListino   ', 'GD_LIRIG'), ('Articolo', 'MD_ARTI'), ('Vuota', None)]),
            'FW_TABLE_FIELDS': (['TABLENAME', 'TABLEFIELDNAME', 'DBFIELDNAME', 'TYPE', 'WIDTH', 'DECIMALS'],
                                [('RigaListino', 'CodListino', 'LIRIG_LICOD', 'C', '10', '0'),
                                 ('Articolo', 'Codice', 'ARTI_ARTCO', 'C', '20', None)]),
        })

    def cursor(self):
        return self.cursor_


class FetchSaveLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'fw.json')

    def test_fetch_reads_the_two_tables_with_select_only_and_cleans_the_values(self):
        connection = FakeConnection()
        data = fw_dictionary.fetch(connection, out=lambda *_: None)
        self.assertEqual(set(data['tables']), {'FW_TABLES', 'FW_TABLE_FIELDS'})
        self.assertEqual(data['tables']['FW_TABLES']['columns'], ['TABLENAME', 'TABLEDBNAME'])
        self.assertEqual(data['tables']['FW_TABLES']['rows'][0], ['RigaListino', 'GD_LIRIG'])        # senza gli spazi in fondo
        self.assertEqual(data['tables']['FW_TABLES']['rows'][2], ['Vuota', None])
        self.assertTrue(all(sql.lstrip().upper().startswith('SELECT') for sql in connection.cursor_.executed))
        self.assertEqual(len(connection.cursor_.executed), 2)

    def test_the_queries_read_only_the_columns_jt_needs_in_the_order_of_the_test_schema(self):
        import create_test_db as tool
        self.assertEqual(fw_dictionary.SELECTS['FW_TABLES'].split(' FROM ')[0], 'SELECT tablename, tabledbname')
        self.assertEqual(len(fw_dictionary.SELECTS['FW_TABLE_FIELDS'].split(' FROM ')[0].split(',')),
                         len(tool._columns('FW_TABLE_FIELDS')))

    def test_save_and_load_round_trip(self):
        data = fw_dictionary.fetch(FakeConnection(), out=lambda *_: None)
        fw_dictionary.save(data, 'h:1521/S', self.path)
        loaded = fw_dictionary.load(self.path)
        self.assertEqual(loaded['tables'], data['tables'])
        self.assertEqual(loaded['source'], 'h:1521/S')
        self.assertRegex(loaded['taken'], r'^\d{4}-\d{2}-\d{2}$')

    def test_load_without_a_file_says_how_to_create_it(self):
        with self.assertRaises(FileNotFoundError) as caught:
            fw_dictionary.load(self.path)
        self.assertIn('--fw-connect HOST:PORT/SID', str(caught.exception))

    def test_merge_the_full_dictionary_wins_and_the_rest_of_the_sample_stays(self):
        sample = {'source': 'x', 'tables': {'FW_STRINGS': {'rows': [1]}, 'FW_TABLES': {'rows': ['old']}}}
        merged = fw_dictionary.merge(sample, {'tables': {'FW_TABLES': {'rows': ['new']}}})
        self.assertEqual(merged['tables'], {'FW_STRINGS': {'rows': [1]}, 'FW_TABLES': {'rows': ['new']}})
        self.assertEqual(merged['source'], 'x')
        self.assertEqual(fw_dictionary.merge(None, {'tables': {'A': 1}}), {'tables': {'A': 1}})

    def test_a_bad_connection_spec_is_an_error_before_any_password_is_asked(self):
        with patch('getpass.getpass', side_effect=AssertionError('asked for a password')):
            for spec in ('', 'host', 'host:1521', ':1521/S'):
                with self.subTest(spec=spec):
                    with self.assertRaises(ValueError):
                        fw_dictionary.connect(spec, 'u')

    def test_the_cache_file_is_ignored_by_git(self):
        with open(os.path.join(HERE, '..', '.gitignore'), encoding='utf-8') as f:
            self.assertIn('tools/fw_dictionary.json', f.read())


class SimulatorWithTheFullDictionaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = os.path.join(self.tmp, 'fw.json')
        data = fw_dictionary.fetch(FakeConnection(), out=lambda *_: None)
        fw_dictionary.save(data, 'h:1521/S', self.cache)
        self.sample = fw_dictionary.merge(None, fw_dictionary.load(self.cache))

    def run_main(self, *args):
        """sim.main con il dizionario salvato di prova al posto di quello vero."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch.object(fw_dictionary, 'CACHE', self.cache):
            code = sim.main(list(args))
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_the_simulator_database_gets_the_whole_dictionary(self):
        from jt import dictionary
        from jt.db import Database
        db = Database(driver=sim.Simulator(self.sample))
        db.connect('sim', '1521', 'SIM', 'u', 'x')
        dictionary.forget()
        self.addCleanup(dictionary.forget)
        d = dictionary.load(db)
        self.assertEqual(d.table_map['$rigalistino'], 'GD_LIRIG')
        self.assertEqual(d.field_map['$articolo']['codice'], 'ARTI_ARTCO')

    def test_translate_tecsql_to_sql(self):
        code, out, err = self.run_main('--fw', '--translate', 'SELECT $RigaListino.CodListino FROM $RigaListino LIMIT 3')
        self.assertEqual(code, 0, err)
        self.assertEqual(out, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE ROWNUM <= 3')

    def test_translate_sql_to_tecsql(self):
        code, out, err = self.run_main('--fw', '--translate', 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertEqual((code, out), (0, 'SELECT $RigaListino.CodListino FROM $RigaListino'))

    def test_an_ambiguous_table_exits_with_2_and_names_the_candidates(self):
        code, out, err = self.run_main('--translate', 'SELECT ARTI_ARTCO FROM MD_ARTI')       # senza --fw: il dizionario di prova
        self.assertEqual((code, out), (2, ''))
        self.assertIn('AMBIGUOUS: MD_ARTI has several logical names: $Articolo, $ArticoloEsteso', err)
        code, out, err = self.run_main('--translate', 'SELECT ARTI_ARTCO FROM MD_ARTI', '--descriptor', '$ArticoloEsteso')
        self.assertEqual((code, out), (0, 'SELECT $ArticoloEsteso.Codice FROM $ArticoloEsteso'))

    def test_with_fw_the_saved_dictionary_is_the_one_used(self):
        code, out, err = self.run_main('--fw', '--translate', 'SELECT ARTI_ARTCO FROM MD_ARTI')       # qui MD_ARTI ha un solo nome
        self.assertEqual((code, out), (2, ''))                          # i descrittori di prova ci sono ancora (si sommano)

    def test_an_error_exits_with_1_and_says_why(self):
        code, out, err = self.run_main('--translate', 'SELECT $Nope.X FROM $Nope')
        self.assertEqual((code, out), (1, ''))
        self.assertIn('ERROR: Logical table not mapped: $Nope', err)

    def test_fw_without_a_saved_dictionary_is_an_error(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with patch.object(fw_dictionary, 'CACHE', os.path.join(self.tmp, 'missing.json')):
                with self.assertRaises(SystemExit):
                    sim.main(['--fw', '--translate', 'SELECT 1 FROM X'])
        self.assertIn('No saved FW dictionary', err.getvalue())

    def test_the_flags_that_need_other_flags_say_so(self):
        for argv in (['--fw-connect', 'h:1/S'], ['--fw-user', 'u'], ['--descriptor', '$A'], ['--fw'],
                     ['--fw', '--fw-connect', 'h:1521/S']):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sim.main(argv)


if __name__ == '__main__':
    unittest.main()
