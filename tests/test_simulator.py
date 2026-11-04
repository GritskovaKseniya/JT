"""Il simulatore di Oracle (tools/simulate.py): l'emulazione e gli scenari che prova il codice vero di JT."""
import os
import sys
import unittest

import helpers

sys.path.insert(0, os.path.join(helpers.ROOT, 'tools'))
import simulate as sim  # noqa: E402


class SqlRewriteTests(unittest.TestCase):
    def test_sysdate_and_dual(self):
        self.assertEqual(sim.to_sqlite("INSERT INTO T VALUES (:1, 'JT', sysdate)"),
                         "INSERT INTO T VALUES (:1, 'JT', CURRENT_TIMESTAMP)")
        self.assertEqual(sim.to_sqlite("SELECT SYS_CONTEXT('USERENV', 'DB_NAME') FROM dual"), "SELECT 'SIMULATOR'")

    def test_rownum_one_and_rownum_limit(self):
        self.assertEqual(sim.to_sqlite('SELECT 1 FROM FW_STRINGS WHERE ROWNUM = 1'), 'SELECT 1 FROM FW_STRINGS LIMIT 1')
        self.assertEqual(sim.to_sqlite('SELECT * FROM T X WHERE X.language = :li AND ROWNUM <= :n AND NOT EXISTS (SELECT 1)'),
                         'SELECT * FROM T X WHERE X.language = :li AND NOT EXISTS (SELECT 1) LIMIT :n')

    def test_counts_with_rownum_count_only_the_first_rows(self):
        text = sim.to_sqlite('SELECT COUNT(*) FROM T X WHERE X.language = :li AND ROWNUM <= :n AND NOT EXISTS (SELECT 1)')
        self.assertEqual(text, 'SELECT COUNT(*) FROM (SELECT X.* FROM T X WHERE X.language = :li AND NOT EXISTS (SELECT 1) '
                               'LIMIT :n) X')

    def test_other_statements_are_left_alone(self):
        sql = 'UPDATE T SET a = :s0 WHERE b = :w0'
        self.assertEqual(sim.to_sqlite(sql), sql)


class OracleBehaviourTests(unittest.TestCase):
    def setUp(self):
        self.db = sim.Simulator()
        self.cursor = self.db.connect('h', '1', 's').cursor()

    def test_like_distinguishes_case_like_oracle(self):
        self.cursor.execute("SELECT COUNT(*) FROM FW_OPZIONI WHERE tipo LIKE 'Ct%'")
        upper = self.cursor.fetchone()[0]
        self.cursor.execute("SELECT COUNT(*) FROM FW_OPZIONI WHERE UPPER(tipo) LIKE 'CT%'")
        self.assertEqual((upper, self.cursor.fetchone()[0]), (1, 2))             # CtStatoCliente; poi anche ctMinuscolo

    def test_value_too_large_is_ora_12899(self):
        with self.assertRaises(sim.OracleError) as raised:
            self.cursor.execute('INSERT INTO FW_OBJ_DESCRS VALUES (:1, :2, :3, :4, :5)', [9, 'T', 'F', 'fr', 'x' * 101])
        self.assertIn('ORA-12899', str(raised.exception))
        self.assertIn('"FW_OBJ_DESCRS"."DESCRIPTION"', str(raised.exception))

    def test_a_value_of_exactly_the_limit_is_accepted(self):
        self.cursor.execute('INSERT INTO FW_OBJ_DESCRS VALUES (:1, :2, :3, :4, :5)', [9, 'T', 'F', 'fr', 'x' * 100])

    def test_null_in_a_required_column_is_ora_01400(self):
        with self.assertRaises(sim.OracleError) as raised:
            self.cursor.execute('INSERT INTO FW_STRINGS VALUES (:1, :2, :3, :4, :5, :6)', [None, 1, 'x', None, None, None])
        self.assertIn('ORA-01400', str(raised.exception))

    def test_unknown_table_is_an_oracle_style_error(self):
        with self.assertRaises(sim.OracleError):
            self.cursor.execute('SELECT 1 FROM NO_SUCH_TABLE WHERE ROWNUM = 1')

    def test_nvl_and_rownum_limit_in_counts(self):
        self.cursor.execute('SELECT NVL(NULL, 5)')
        self.assertEqual(self.cursor.fetchone(), (5,))
        self.cursor.execute("SELECT COUNT(*) FROM FW_STRINGS X WHERE X.language = :li AND ROWNUM <= :n", {'li': 'it', 'n': 3})
        self.assertEqual(self.cursor.fetchone(), (3,))

    def test_select_rows_survive_a_rollback_like_in_oracle(self):
        connection = self.db.connect('h', '1', 's')
        reader = connection.cursor()
        reader.execute("SELECT code FROM FW_STRINGS WHERE language = 'it' ORDER BY code")
        first = next(iter(reader))
        connection.rollback()
        self.assertEqual(len(reader.fetchall()), 17)          # 18 righe italiane, una gia' letta
        self.assertEqual(first, (100000,))

    def test_the_database_is_shared_between_connections(self):
        other = self.db.connect('h', '1', 's')
        self.cursor.execute("INSERT INTO FW_OBJ_DESCRS VALUES (50, 'T', 'F', 'fr', 'a')")
        reader = other.cursor()
        reader.execute('SELECT COUNT(*) FROM FW_OBJ_DESCRS WHERE objid = 50')
        self.assertEqual(reader.fetchone(), (1,))


class TranslatorTests(unittest.TestCase):
    def test_translator_answers_with_the_language_and_can_fail_on_a_text(self):
        translator = sim.SimTranslator(fail_on='boom')
        self.assertEqual(translator.translate('ciao', 'it', 'fr'), '[fr] ciao')
        with self.assertRaises(RuntimeError):
            translator.translate('a boom here', 'it', 'fr')


class ScenarioTests(unittest.TestCase):
    def test_every_scenario_check_passes(self):
        import contextlib
        import io
        lines = []
        with contextlib.redirect_stdout(io.StringIO()):         # il servizio scrive gli errori con print
            ok, total = sim.run_scenarios(out=lines.append)
        self.assertGreater(total, 40)
        self.assertEqual(ok, total, '\n'.join(lines))

    def test_each_scenario_starts_from_a_fresh_database(self):
        first, second = sim.Scenario('a'), sim.Scenario('b')
        first.sim.raw.execute("DELETE FROM FW_STRINGS")
        self.assertGreater(second.sim.query('SELECT COUNT(*) FROM FW_STRINGS')[0][0], 0)

    def test_the_command_line_returns_zero_when_everything_passes(self):
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(sim.main([]), 0)


if __name__ == '__main__':
    unittest.main()
