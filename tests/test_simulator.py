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
        self.assertEqual(len(reader.fetchall()), 19)          # 20 righe italiane, una gia' letta
        self.assertEqual(first, (100000,))

    def test_the_database_is_shared_between_connections(self):
        other = self.db.connect('h', '1', 's')
        self.cursor.execute("INSERT INTO FW_OBJ_DESCRS VALUES (50, 'T', 'F', 'fr', 'a')")
        reader = other.cursor()
        reader.execute('SELECT COUNT(*) FROM FW_OBJ_DESCRS WHERE objid = 50')
        self.assertEqual(reader.fetchone(), (1,))


class TranslatorTests(unittest.TestCase):
    def test_realistic_mode_translates_the_test_strings_for_real(self):
        translator = sim.SimTranslator(realistic=True)
        self.assertEqual(translator.translate('Gestione ordini', 'it', 'en'), 'Order management')
        hindi = translator.translate('Gestione ordini', 'it', 'hi')
        self.assertNotIn('Gestione', hindi)
        self.assertTrue(any('\u0900' <= ch <= '\u097f' for ch in hindi), hindi)       # alfabeto devanagari

    def test_realistic_mode_falls_back_to_the_prefix_for_unknown_text_or_language(self):
        translator = sim.SimTranslator(realistic=True)
        self.assertEqual(translator.translate('Testo che non conosco', 'it', 'hi'), '[hi] Testo che non conosco')
        self.assertEqual(translator.translate('Gestione ordini', 'it', 'ja'), '[ja] Gestione ordini')

    def test_the_default_mode_keeps_the_prefix_the_scenarios_rely_on(self):
        self.assertEqual(sim.SimTranslator().translate('Gestione ordini', 'it', 'hi'), '[hi] Gestione ordini')

    def test_the_translations_cover_five_languages_and_real_test_strings(self):
        import create_test_db as tool
        italian = {row[2] for row in tool.DATA['FW_STRINGS'] if row[0] == 'it'}
        for text, languages in sim.TRANSLATIONS.items():
            self.assertIn(text, italian)                                            # la frase esiste nel database di prova
            self.assertEqual(sorted(languages), ['de', 'en', 'es', 'fr', 'hi'], text)
            if text != 'Supply Chain Planning':
                self.assertTrue(all(value != text for value in languages.values()), text)
        self.assertEqual(sim.TRANSLATIONS['Supply Chain Planning']['hi'], 'Supply Chain Planning')   # lo lascia uguale il glossario

    def test_real_azure_is_used_only_with_a_real_key(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'azure_services.json')
            self.assertFalse(sim.real_azure_available(path))                         # file mancante
            for key, expected in (('INSERISCI-QUI-LA-CHIAVE', False), ('', False), ('0123456789abcdef', True)):
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump({'subscription_key': key}, f)
                self.assertEqual(sim.real_azure_available(path), expected, key)
            with open(path, 'w', encoding='utf-8') as f:
                f.write('[1, 2]')
            self.assertFalse(sim.real_azure_available(path))                         # non e' un oggetto

    def test_azure_and_sample_need_the_window(self):
        import contextlib
        import io
        for flag in (['--azure'], ['--sample', 'x.json']):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                sim.main(flag)

    def test_translator_answers_with_the_language_and_can_fail_on_a_text(self):
        translator = sim.SimTranslator(fail_on='boom')
        self.assertEqual(translator.translate('ciao', 'it', 'fr'), '[fr] ciao')
        with self.assertRaises(RuntimeError):
            translator.translate('a boom here', 'it', 'fr')


class UndoScriptSupportTests(unittest.TestCase):
    """Il simulatore sa eseguire uno script di annullamento come farebbe SQL Developer."""

    def test_statements_split_outside_quotes_and_drop_comments_and_commands(self):
        script = ("-- header; with a semicolon\nSET DEFINE OFF;\nDELETE FROM T WHERE a = 'x;y';\n"
                  "UPDATE T SET b = 'it''s; ok' WHERE a = 1;\nCOMMIT;\n")
        self.assertEqual(sim.statements(script),
                         ["DELETE FROM T WHERE a = 'x;y'", "UPDATE T SET b = 'it''s; ok' WHERE a = 1"])

    def test_the_last_statement_counts_even_without_a_final_semicolon(self):
        self.assertEqual(sim.statements('DELETE FROM T WHERE a = 1'), ['DELETE FROM T WHERE a = 1'])
        self.assertEqual(sim.statements(''), [])

    def test_unistr_decodes_utf16_units(self):
        self.assertEqual(sim._unistr('Men\\00F9'), 'Menù')
        self.assertEqual(sim._unistr('\\D83D\\DE00'), '\U0001F600')                  # due unita': un carattere
        self.assertEqual(sim._unistr('C:\\005Cx'), 'C:\\x')
        self.assertEqual(sim._unistr('plain'), 'plain')

    def test_to_date_becomes_text_in_the_simulator(self):
        self.assertEqual(sim.to_sqlite("UPDATE T SET d = TO_DATE('2025-03-19 10:20:30', 'YYYY-MM-DD HH24:MI:SS') WHERE a = 1"),
                         "UPDATE T SET d = '2025-03-19 10:20:30' WHERE a = 1")

    def test_run_script_executes_every_statement(self):
        from jt.undo import UndoRecord, build_script
        db = sim.Simulator()
        before = db.query('SELECT COUNT(*) FROM FW_STRINGS')[0][0]
        script = build_script([UndoRecord('FW_STRINGS', 'insert', {'language': 'it', 'code': 100000}),
                               UndoRecord('FW_STRINGS', 'update', {'language': 'it', 'code': 100001}, {'value': "L'altro"})])
        db.run_script(script)
        self.assertEqual(db.query('SELECT COUNT(*) FROM FW_STRINGS')[0][0], before - 1)
        self.assertEqual(db.query("SELECT value FROM FW_STRINGS WHERE language = 'it' AND code = 100001"), [("L'altro",)])

    def test_a_broken_statement_in_a_script_is_an_oracle_style_error(self):
        with self.assertRaises(sim.OracleError):
            sim.Simulator().run_script('DELETE FROM NO_SUCH_TABLE WHERE a = 1;')


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

    def test_the_gui_only_options_need_gui(self):
        import contextlib
        import io
        for option in ('--nokey', '--azure'):
            with self.subTest(option=option), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sim.main([option])


if __name__ == '__main__':
    unittest.main()
