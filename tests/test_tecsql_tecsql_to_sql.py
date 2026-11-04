"""Traduzione TecSQL -> SQL (`translate_tecsql`), portata da JCTNT (da pytest a unittest): SELECT di base, alias,
subquery, parametri (`?nome`) tolti con `strip_params`, ORDER BY."""
import unittest

import tecsql_fixtures as fx
from jt.tecsql_translator import translate_tecsql


class TecsqlToSqlCase(fx.TecsqlCase):
    def translate(self, query, strip_params=False):
        """`translate_tecsql` ritorna l'SQL (testo) e solleva ValueError se non riesce. Nell'originale JCTNT i test si
        aspettavano un dict con 'success': era un'API piu' vecchia, 15 test su 33 fallivano gia' li'."""
        return translate_tecsql(query, strip_params=strip_params).strip()


class BasicSelectTests(TecsqlToSqlCase):
    def test_single_field(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertIn('GD_LIRIG.LIRIG_LICOD', sql)
        self.assertIn('GD_LIRIG', sql)

    def test_multiple_fields(self):
        sql = self.translate('SELECT $RigaListino.CodListino, $RigaListino.CatListino FROM $RigaListino')
        self.assertIn('GD_LIRIG.LIRIG_LICOD', sql)
        self.assertIn('GD_LIRIG.LIRIG_CATLI', sql)

    def test_where_clause(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino "
                             "WHERE $RigaListino.CatListino = 'LL'")
        self.assertIn('GD_LIRIG.LIRIG_LICOD', sql)
        self.assertIn("GD_LIRIG.LIRIG_CATLI = 'LL'", sql)

    def test_count_star(self):
        sql = self.translate('SELECT COUNT(*) FROM $RigaListino')
        self.assertIn('COUNT (*)', sql.upper())          # il traduttore scrive uno spazio prima della parentesi (Oracle lo accetta)
        self.assertIn('GD_LIRIG', sql)


class AliasesTests(TecsqlToSqlCase):
    def test_alias_in_from(self):
        """L'alias dichiarato in FROM vale gia' nella SELECT; i nomi dei campi si traducono, l'alias resta."""
        sql = self.translate("SELECT RL.CodListino FROM $RigaListino RL WHERE RL.CatListino = 'LL'")
        self.assertIn('LIRIG_LICOD', sql)
        self.assertIn('LIRIG_CATLI', sql)
        self.assertNotIn(' AS RL', sql)

    def test_as_keyword_dropped(self):
        sql = self.translate('SELECT RL.CodListino FROM $RigaListino AS RL')
        self.assertNotIn(' AS RL', sql)
        self.assertTrue('GD_LIRIG RL' in sql or 'GD_LIRIG\nRL' in sql.replace('  ', ' '))


class SubqueriesTests(TecsqlToSqlCase):
    def test_subquery_in_where(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino '
                             'WHERE $RigaListino.CodListino IN ('
                             '  SELECT $TestataListino.Codice FROM $TestataListino '
                             "  WHERE $TestataListino.CodCategoria = 'LL'"
                             ')')
        for text in ('GD_LIRIG', 'GD_LITES', 'LIRIG_LICOD', 'LITES_LICOD', 'LITES_CATLI'):
            self.assertIn(text, sql)


class StripParamsTests(TecsqlToSqlCase):
    def test_strip_single_param(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino '
                             'WHERE $RigaListino.CatListino = ?categoria', strip_params=True)
        self.assertNotIn('?categoria', sql)
        self.assertNotIn('WHERE', sql.upper())             # era l'unica condizione: sparisce anche WHERE

    def test_strip_keeps_non_param_conditions(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino '
                             'WHERE $RigaListino.CatListino = ?categoria '
                             'AND $RigaListino.Prezzo > 0', strip_params=True)
        self.assertNotIn('?categoria', sql)
        self.assertIn('WHERE', sql.upper())                # resta una condizione vera
        self.assertIn('LIRIG_PREZO', sql)

    def test_no_strip_by_default(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino '
                             'WHERE $RigaListino.CatListino = ?categoria')
        self.assertIn('?categoria', sql)


class EdgeCasesTests(TecsqlToSqlCase):
    def test_order_by_translated(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino '
                             'ORDER BY $RigaListino.CodListino DESC')
        self.assertIn('LIRIG_LICOD', sql)
        self.assertIn('DESC', sql.upper())


if __name__ == '__main__':
    unittest.main()
