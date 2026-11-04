"""Lo script che annulla una corsa (jt/undo.py): costanti SQL, DELETE per gli INSERT, UPDATE che rimettono i valori di prima."""
import unittest
from datetime import date, datetime

from jt.undo import UndoRecord, build_script, identifier, literal, statement


class LiteralTests(unittest.TestCase):
    def test_simple_values(self):
        self.assertEqual(literal(None), 'NULL')
        self.assertEqual(literal(100000), '100000')
        self.assertEqual(literal(2.5), '2.5')
        self.assertEqual(literal(True), '1')
        self.assertEqual(literal('fr'), "'fr'")

    def test_apostrophes_are_doubled_and_an_ampersand_is_left_alone(self):
        self.assertEqual(literal("l'ordine & 100% 'x'"), "'l''ordine & 100% ''x'''")

    def test_characters_outside_printable_ascii_are_written_with_unistr(self):
        self.assertEqual(literal('Menù'), "UNISTR('Men\\00F9')")
        self.assertEqual(literal('ऑर्डर'), "UNISTR('\\0911\\0930\\094D\\0921\\0930')")
        self.assertEqual(literal('a\nb'), "UNISTR('a\\000Ab')")
        self.assertEqual(literal('\U0001F600'), "UNISTR('\\D83D\\DE00')")            # oltre U+FFFF: due unita' UTF-16

    def test_inside_unistr_the_backslash_and_the_apostrophe_are_protected(self):
        self.assertEqual(literal("C:\\x è l'ora"), "UNISTR('C:\\005Cx \\00E8 l''ora')")
        self.assertEqual(literal('C:\\x'), "'C:\\x'")                                  # senza caratteri speciali resta com'e'

    def test_dates(self):
        self.assertEqual(literal(datetime(2025, 3, 19, 10, 20, 30)), "TO_DATE('2025-03-19 10:20:30', 'YYYY-MM-DD HH24:MI:SS')")
        self.assertEqual(literal(date(2025, 3, 19)), "TO_DATE('2025-03-19 00:00:00', 'YYYY-MM-DD HH24:MI:SS')")

    def test_the_result_is_always_plain_ascii(self):
        for value in ('Menù', 'ऑर्डर', '\U0001F600', "l'è\n", 'x'):
            self.assertTrue(literal(value).isascii(), value)


class IdentifierTests(unittest.TestCase):
    def test_normal_names_pass(self):
        for name in ('FW_STRINGS', 'language', 'LASTDATE', 'a1', 'T$1', 'X#'):
            self.assertEqual(identifier(name), name)

    def test_anything_else_is_refused(self):
        for name in ('', 'a b', '1x', 'a;drop table t', "a'b", 'a-b', 'ta.ble', None):
            with self.assertRaises(ValueError, msg=repr(name)):
                identifier(name)

    def test_a_strange_table_or_column_never_reaches_the_script(self):
        for record in (UndoRecord('T; DROP TABLE X', 'insert', {'language': 'fr'}),
                       UndoRecord('T', 'insert', {'language; --': 'fr'}),
                       UndoRecord('T', 'update', {'a': 1}, {'b c': 'x'})):
            with self.assertRaises(ValueError):
                statement(record)


class StatementTests(unittest.TestCase):
    def test_an_insert_is_undone_with_a_delete(self):
        record = UndoRecord('FW_STRINGS', 'insert', {'language': 'fr', 'code': 100000})
        self.assertEqual(statement(record), "DELETE FROM FW_STRINGS WHERE language = 'fr' AND code = 100000;")

    def test_an_update_puts_the_previous_values_back(self):
        record = UndoRecord('FW_STRINGS', 'update', {'language': 'de', 'code': 3000003},
                            {'value': "Zusatz 'alt'", 'LASTUSER': 'ZFXCUSTOM', 'LASTDATE': datetime(2025, 3, 19, 1, 2, 3)})
        self.assertEqual(statement(record),
                         "UPDATE FW_STRINGS SET value = 'Zusatz ''alt''', LASTUSER = 'ZFXCUSTOM', "
                         "LASTDATE = TO_DATE('2025-03-19 01:02:03', 'YYYY-MM-DD HH24:MI:SS') "
                         "WHERE language = 'de' AND code = 3000003;")

    def test_a_null_before_is_put_back_as_null(self):
        record = UndoRecord('FW_FIELD_STRINGS', 'update', {'language': 'de', 'code': 10}, {'tip': None})
        self.assertEqual(statement(record), "UPDATE FW_FIELD_STRINGS SET tip = NULL WHERE language = 'de' AND code = 10;")

    def test_every_key_column_is_in_the_condition(self):
        record = UndoRecord('FW_OPZIONI', 'insert', {'lingua': 'fr', 'tipo': 'CtOpz', 'codice': 1})
        self.assertEqual(statement(record),
                         "DELETE FROM FW_OPZIONI WHERE lingua = 'fr' AND tipo = 'CtOpz' AND codice = 1;")


class ScriptTests(unittest.TestCase):
    RECORDS = [UndoRecord('FW_STRINGS', 'insert', {'language': 'fr', 'code': 1}),
               UndoRecord('FW_STRINGS', 'update', {'language': 'fr', 'code': 2}, {'value': 'old'}),
               UndoRecord('FW_OPZIONI', 'insert', {'lingua': 'fr', 'tipo': 'A', 'codice': 1})]

    def script(self, **kwargs):
        return build_script(self.RECORDS, 'ORA319', 'rete-ud-6', datetime(2026, 11, 4, 11, 30, 0), **kwargs)

    def test_header_says_what_it_is_and_how_to_use_it(self):
        lines = self.script().split('\n')
        self.assertEqual(lines[0], '-- JT undo script')
        self.assertEqual(lines[1], '-- Generated 2026-11-04 11:30:00 for the database ORA319 (rete-ud-6)')
        self.assertEqual(lines[2], '-- Undoes 2 insert(s) (DELETE) and 1 update(s) (the previous values are put back).')
        self.assertIn('SQL Developer', lines[3])
        self.assertIn('does not check whether somebody changed these rows', lines[4])

    def test_define_is_off_so_an_ampersand_does_not_ask_for_a_value_and_it_ends_with_a_commit(self):
        lines = self.script().split('\n')
        self.assertIn('SET DEFINE OFF;', lines)
        self.assertLess(lines.index('SET DEFINE OFF;'), lines.index('COMMIT;'))
        self.assertEqual(lines[-2:], ['COMMIT;', ''])

    def test_the_last_row_written_is_the_first_one_undone(self):
        body = [line for line in self.script().split('\n') if line.startswith(('DELETE', 'UPDATE'))]
        self.assertEqual(body, ["DELETE FROM FW_OPZIONI WHERE lingua = 'fr' AND tipo = 'A' AND codice = 1;",
                                "UPDATE FW_STRINGS SET value = 'old' WHERE language = 'fr' AND code = 2;",
                                "DELETE FROM FW_STRINGS WHERE language = 'fr' AND code = 1;"])

    def test_the_whole_script_is_plain_ascii_so_the_file_encoding_does_not_matter(self):
        records = [UndoRecord('FW_STRINGS', 'update', {'language': 'hi', 'code': 1}, {'value': 'ऑर्डर प्रबंधन è'})]
        self.assertTrue(build_script(records, 'DB', 'h').isascii())

    def test_unknown_database_and_host_show_a_question_mark_and_an_empty_script_is_valid(self):
        text = build_script([], when=datetime(2026, 1, 2, 3, 4, 5))
        self.assertIn('for the database ? (?)', text)
        self.assertIn('Undoes 0 insert(s) (DELETE) and 0 update(s)', text)
        self.assertEqual([line for line in text.split('\n') if line.startswith(('DELETE', 'UPDATE'))], [])

    def test_the_default_time_is_now(self):
        self.assertIn(f'{datetime.now():%Y-%m-%d}', build_script(self.RECORDS))


if __name__ == '__main__':
    unittest.main()
