"""Il dizionario dei nomi letto dal database (`jt/dictionary.py`) e l'oggetto `Dictionary` (senza stato globale)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jt import dictionary  # noqa: E402
from jt.tecsql_translator import Dictionary  # noqa: E402

ROWS = [
    ('GD_LIRIG', 'LIRIG_LICOD', 'RigaListino', 'CodListino', 'C', 10, 0),
    ('GD_LIRIG', 'LIRIG_PREZO', 'RigaListino', 'Prezzo', 'N', 15, 4),
    ('GD_LITES', None, 'TestataListino', 'Codice', None, None, None),          # valori vuoti: diventano ''
]


class FakeDb:
    def __init__(self, rows=ROWS, host='h', sid='S'):
        self.rows = rows
        self.queries = []
        self.info = {'host': host, 'port': '1521', 'sid': sid, 'user': 'u'}

    def fetch_all(self, sql, binds=None):
        self.queries.append(sql)
        return list(self.rows)


class DictionaryLoadTests(unittest.TestCase):
    def setUp(self):
        dictionary.forget()
        self.addCleanup(dictionary.forget)

    def test_the_select_reads_the_two_dictionary_tables(self):
        db = FakeDb()
        dictionary.load(db)
        self.assertEqual(len(db.queries), 1)
        for text in ('FW_TABLES', 'FW_TABLE_FIELDS', 'TABLEDBNAME', 'DBFIELDNAME', 'TABLENAME', 'TABLEFIELDNAME'):
            self.assertIn(text, db.queries[0])
        self.assertEqual(dictionary.TABLES, ('FW_TABLES', 'FW_TABLE_FIELDS'))

    def test_rows_are_dicts_with_empty_values_as_blank_text(self):
        rows = dictionary.read_rows(FakeDb())
        self.assertEqual(rows[0], {'TABELLA_FISICA': 'GD_LIRIG', 'CAMPO_FISICO': 'LIRIG_LICOD',
                                   'TABELLA_LOGICA': 'RigaListino', 'CAMPO_LOGICO': 'CodListino', 'TIPO': 'C',
                                   'AMPIEZZA': 10, 'DECIMALI': 0, 'POSIZ_DB': ''})
        self.assertEqual(rows[2]['CAMPO_FISICO'], '')
        self.assertEqual((rows[2]['TIPO'], rows[2]['AMPIEZZA'], rows[2]['DECIMALI']), ('', '', ''))

    def test_the_position_of_the_field_in_the_database_is_read(self):
        rows = dictionary.read_rows(FakeDb(rows=[('GD_LIRIG', 'LIRIG_LICOD', 'RigaListino', 'CodListino', 'C', 10, 0, 7),
                                                 ('GD_LIRIG', 'LIRIG_PREZO', 'RigaListino', 'Prezzo', 'N', 15, 4, None)]))
        self.assertEqual([r['POSIZ_DB'] for r in rows], [7, ''])
        self.assertIn('DBPOSITION', dictionary.FIELDS_SQL)

    def test_without_the_position_column_the_dictionary_still_loads(self):
        class OldDb(FakeDb):
            def fetch_all(self, sql, binds=None):
                self.queries.append(sql)
                if 'DBPOSITION' in sql:
                    raise RuntimeError('ORA-00904: invalid identifier')
                return list(self.rows)
        db = OldDb()
        rows = dictionary.read_rows(db)
        self.assertEqual(len(rows), 3)
        self.assertEqual({r['POSIZ_DB'] for r in rows}, {''})
        self.assertEqual(len(db.queries), 2)                                  # prima con la posizione, poi senza

    def test_a_real_error_is_still_an_error(self):
        class BrokenDb(FakeDb):
            def fetch_all(self, sql, binds=None):
                raise RuntimeError('ORA-00942: table or view does not exist')
        with self.assertRaises(RuntimeError) as caught:
            dictionary.read_rows(BrokenDb())
        self.assertIn('ORA-00942', str(caught.exception))

    def test_load_returns_a_dictionary_with_the_maps_the_rows_and_the_translators(self):
        d = dictionary.load(FakeDb())
        self.assertIsInstance(d, Dictionary)
        self.assertEqual(d.table_map['$rigalistino'], 'GD_LIRIG')
        self.assertEqual(d.field_map['$rigalistino']['prezzo'], 'LIRIG_PREZO')
        self.assertEqual(len(d.rows), 3)
        self.assertEqual(d.to_sql('SELECT $RigaListino.Prezzo FROM $RigaListino').upper(),
                         'SELECT GD_LIRIG.LIRIG_PREZO FROM GD_LIRIG')

    def test_the_same_connection_does_not_read_the_dictionary_again(self):
        db = FakeDb()
        first = dictionary.load(db)
        second = dictionary.load(db)
        self.assertIs(first, second)
        self.assertEqual(len(db.queries), 1)

    def test_another_database_or_a_forced_load_reads_it_again(self):
        first = dictionary.load(FakeDb(host='a'))
        other = FakeDb(rows=ROWS[:1], host='b')
        second = dictionary.load(other)
        self.assertIsNot(first, second)
        self.assertEqual(len(second.rows), 1)
        self.assertEqual(len(other.queries), 1)
        third = dictionary.load(other, force=True)
        self.assertIsNot(second, third)
        self.assertEqual(len(other.queries), 2)

    def test_forget_makes_the_next_load_read_again_and_leaves_the_old_dictionary_alone(self):
        db = FakeDb()
        old = dictionary.load(db)
        dictionary.forget()
        self.assertTrue(old)                               # chi lo teneva in mano lo ha ancora
        new = dictionary.load(db)
        self.assertIsNot(old, new)
        self.assertEqual(len(db.queries), 2)

    def test_a_database_without_info_still_loads(self):
        db = FakeDb()
        db.info = None
        self.assertEqual(len(dictionary.load(db).rows), 3)


class NoSharedStateTests(unittest.TestCase):
    """Due dizionari (due database) in memoria insieme non si mescolano."""

    def rows(self, physical):
        return [{'TABELLA_FISICA': physical, 'CAMPO_FISICO': 'F_ONE', 'TABELLA_LOGICA': 'Uno', 'CAMPO_LOGICO': 'Campo'}]

    def test_two_dictionaries_are_independent(self):
        a, b = Dictionary(self.rows('TAB_A')), Dictionary(self.rows('TAB_B'))
        self.assertEqual(a.table_map, {'$uno': 'TAB_A'})
        self.assertEqual(b.table_map, {'$uno': 'TAB_B'})
        self.assertEqual(a.to_sql('SELECT $Uno.Campo FROM $Uno').upper(), 'SELECT TAB_A.F_ONE FROM TAB_A')
        self.assertEqual(b.to_sql('SELECT $Uno.Campo FROM $Uno').upper(), 'SELECT TAB_B.F_ONE FROM TAB_B')

    def test_update_replaces_what_was_there(self):
        d = Dictionary(self.rows('TAB_A'))
        d.update(self.rows('TAB_C'))
        self.assertEqual(d.table_map, {'$uno': 'TAB_C'})
        self.assertEqual(list(d.physical_table_map), ['tab_c'])

    def test_an_empty_dictionary_is_false_and_refuses_to_translate_with_a_clear_message(self):
        d = Dictionary()
        self.assertFalse(d)
        with self.assertRaises(ValueError) as caught:
            d.to_sql('SELECT $A.B FROM $A')
        self.assertEqual(str(caught.exception), 'TecSQL dictionary not loaded. Connect to the database before translating.')


class EnglishMessagesTests(unittest.TestCase):
    def setUp(self):
        self.d = Dictionary([{'TABELLA_FISICA': 'GD_LIRIG', 'CAMPO_FISICO': 'LIRIG_LICOD', 'TABELLA_LOGICA': 'RigaListino',
                              'CAMPO_LOGICO': 'CodListino'}])

    def message(self, query):
        with self.assertRaises(ValueError) as caught:
            self.d.to_sql(query)
        return str(caught.exception)

    def test_an_empty_query(self):
        self.assertEqual(self.message(''), 'Empty TecSQL query')

    def test_an_unknown_table_and_an_unknown_field(self):
        self.assertEqual(self.message('SELECT $Nope.X FROM $Nope'), 'Logical table not mapped: $Nope')
        self.assertIn('Logical field', self.message('SELECT $RigaListino.Nope FROM $RigaListino'))

    def test_sql_to_tecsql_errors_come_in_the_result(self):
        self.assertEqual(self.d.to_tecsql('')['error'], 'Empty query or dictionary not loaded')
        self.assertEqual(self.d.to_tecsql('SELECT 1')['error'], 'No table found in the query')
        self.assertEqual(self.d.to_tecsql('SELECT x FROM nothing_here')['error'], 'Table NOTHING_HERE not found in the dictionary')

    def test_no_italian_message_is_left(self):
        path = os.path.join(os.path.dirname(__file__), '..', 'jt', 'tecsql_translator.py')
        with open(path, encoding='utf-8') as f:
            text = f.read()
        for word in ('non mappat', 'non trovata', 'non caricato', 'Query vuota', 'Nessuna tabella', 'non risolvibile'):
            self.assertNotIn(word, text)


if __name__ == '__main__':
    unittest.main()
