"""Il dizionario dei nomi letto dal database (`jt/dictionary.py`): la SELECT, le righe, la cache per connessione."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jt import dictionary, tecsql_translator as tr  # noqa: E402

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


class DictionaryTests(unittest.TestCase):
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
                                   'AMPIEZZA': 10, 'DECIMALI': 0})
        self.assertEqual(rows[2]['CAMPO_FISICO'], '')
        self.assertEqual((rows[2]['TIPO'], rows[2]['AMPIEZZA'], rows[2]['DECIMALI']), ('', '', ''))

    def test_load_fills_the_translator_maps(self):
        dictionary.load(FakeDb())
        self.assertEqual(tr.TABLE_MAP['$rigalistino'], 'GD_LIRIG')
        self.assertEqual(tr.FIELD_MAP['$rigalistino']['prezzo'], 'LIRIG_PREZO')
        self.assertEqual(tr.translate_tecsql('SELECT $RigaListino.Prezzo FROM $RigaListino').upper(),
                         'SELECT GD_LIRIG.LIRIG_PREZO FROM GD_LIRIG')

    def test_the_same_connection_does_not_read_the_dictionary_again(self):
        db = FakeDb()
        first = dictionary.load(db)
        second = dictionary.load(db)
        self.assertIs(first, second)
        self.assertEqual(len(db.queries), 1)

    def test_another_database_or_a_forced_load_reads_it_again(self):
        dictionary.load(FakeDb(host='a'))
        other = FakeDb(rows=ROWS[:1], host='b')
        rows = dictionary.load(other)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(other.queries), 1)
        dictionary.load(other, force=True)
        self.assertEqual(len(other.queries), 2)

    def test_forget_empties_everything(self):
        dictionary.load(FakeDb())
        dictionary.forget()
        self.assertEqual(tr.TABLE_MAP, {})
        db = FakeDb()
        dictionary.load(db)                                # dopo forget si rilegge
        self.assertEqual(len(db.queries), 1)

    def test_a_database_without_info_still_loads(self):
        db = FakeDb()
        db.info = None
        self.assertEqual(len(dictionary.load(db)), 3)


if __name__ == '__main__':
    unittest.main()
