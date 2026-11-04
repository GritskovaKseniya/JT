"""Traduzione TecSQL -> SQL (`translate_tecsql`), portata da JCTNT (da pytest a unittest): SELECT di base, alias,
subquery, parametri (`?nome`) tolti con `strip_params`, ORDER BY."""
import unittest

import tecsql_fixtures as fx


class TecsqlToSqlCase(fx.TecsqlCase):
    def translate(self, query, strip_params=False):
        """`translate_tecsql` ritorna l'SQL (testo) e solleva ValueError se non riesce. Nell'originale JCTNT i test si
        aspettavano un dict con 'success': era un'API piu' vecchia, 15 test su 33 fallivano gia' li'."""
        return self.d.to_sql(query, strip_params=strip_params).strip()


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


class AliasTests(TecsqlToSqlCase):
    """Un campo scritto con un alias resta scritto con l'alias: nella FROM c'e' `TABELLA alias` e l'alias nasconde il nome
    della tabella (con `TABELLA.CAMPO` Oracle da' ORA-00904). Prima usciva il nome della tabella."""

    def test_the_alias_is_kept_in_the_fields(self):
        sql = self.translate("SELECT RL.CodListino FROM $RigaListino RL WHERE RL.CatListino = 'LL'")
        self.assertEqual(sql, "SELECT RL.LIRIG_LICOD FROM GD_LIRIG RL WHERE RL.LIRIG_CATLI = 'LL'")

    def test_as_in_the_from_is_dropped_and_the_alias_kept(self):
        self.assertEqual(self.translate('SELECT RL.CodListino FROM $RigaListino AS RL'),
                         'SELECT RL.LIRIG_LICOD FROM GD_LIRIG RL')

    def test_a_self_join_keeps_the_two_aliases_apart(self):
        sql = self.translate('SELECT A.CodListino, B.CodListino FROM $RigaListino A, $RigaListino B '
                             'WHERE A.CodArticolo = B.CodArticolo')
        self.assertEqual(sql, 'SELECT A.LIRIG_LICOD, B.LIRIG_LICOD FROM GD_LIRIG A, GD_LIRIG B '
                              'WHERE A.LIRIG_ARTCO = B.LIRIG_ARTCO')

    def test_star_with_an_alias(self):
        self.assertEqual(self.translate('SELECT RL.* FROM $RigaListino RL'), 'SELECT RL.* FROM GD_LIRIG RL')

    def test_a_join_with_aliases(self):
        sql = self.translate('SELECT RL.CodListino FROM $RigaListino RL LEFT JOIN $TestataListino TL '
                             'ON RL.CodListino = TL.Codice')
        self.assertEqual(sql, 'SELECT RL.LIRIG_LICOD FROM GD_LIRIG RL LEFT JOIN GD_LITES TL ON RL.LIRIG_LICOD = TL.LITES_LICOD')

    def test_a_subquery_sees_the_aliases_of_the_outer_query(self):
        sql = self.translate('SELECT RL.CodListino FROM $RigaListino RL WHERE RL.Prezzo = '
                             '(SELECT MAX(RL2.Prezzo) FROM $RigaListino RL2 WHERE RL2.CodListino = RL.CodListino)')
        self.assertIn('(SELECT MAX (RL2.LIRIG_PREZO) FROM GD_LIRIG RL2 WHERE RL2.LIRIG_LICOD = RL.LIRIG_LICOD)', sql)

    def test_a_table_without_an_alias_is_still_written_with_its_name(self):
        self.assertEqual(self.translate('SELECT $RigaListino.CodListino FROM $RigaListino'),
                         'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')


class DateTests(TecsqlToSqlCase):
    """DATE('gg/mm/aaaa') diventa TO_DATE('aaaa-mm-gg'), come in Orione."""

    def test_a_date_becomes_to_date(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.Prezzo > DATE('04/12/2008')")
        self.assertIn("> TO_DATE('2008-12-04')", sql)

    def test_a_day_or_month_with_one_digit(self):
        self.assertIn("TO_DATE('2008-01-05')", self.translate("SELECT DATE('5/1/2008') FROM $RigaListino"))

    def test_dates_in_expressions_and_in_lower_case(self):
        sql = self.translate("SELECT date('04/12/2008') + 10 FROM $RigaListino")
        self.assertIn("TO_DATE('2008-12-04') + 10", sql)

    def test_a_bad_argument_is_an_error(self):
        for argument, text in (("DATE(1)", 'one string'), ("DATE('2008-12-04')", 'dd/mm/yyyy'),
                               ("DATE('31/02/2008')", 'not a real date'), ("DATE($RigaListino.Prezzo)", 'one string')):
            with self.subTest(argument=argument):
                with self.assertRaises(ValueError) as caught:
                    self.d.to_sql(f'SELECT {argument} FROM $RigaListino')
                self.assertIn(text, str(caught.exception))


class LimitTests(TecsqlToSqlCase):
    """LIMIT n diventa ROWNUM <= n nel WHERE (come Orione): funziona anche su Oracle 11, FETCH FIRST no."""

    def test_limit_without_a_where(self):
        self.assertEqual(self.translate('SELECT $RigaListino.CodListino FROM $RigaListino LIMIT 10'),
                         'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE ROWNUM <= 10')

    def test_limit_with_a_where(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CatListino = 'LL' LIMIT 5")
        self.assertEqual(sql, "SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE GD_LIRIG.LIRIG_CATLI = 'LL' AND ROWNUM <= 5")

    def test_conditions_with_an_or_are_put_in_brackets(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CatListino = 'A' "
                             "OR $RigaListino.CatListino = 'B' LIMIT 3")
        self.assertEqual(sql, "SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE (GD_LIRIG.LIRIG_CATLI = 'A' "
                              "OR GD_LIRIG.LIRIG_CATLI = 'B') AND ROWNUM <= 3")

    def test_an_or_inside_brackets_is_not_wrapped_again(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino WHERE ($RigaListino.CatListino = 'A' "
                             "OR $RigaListino.CatListino = 'B') AND $RigaListino.Prezzo > 0 LIMIT 3")
        self.assertIn("WHERE (GD_LIRIG.LIRIG_CATLI = 'A' OR GD_LIRIG.LIRIG_CATLI = 'B') AND GD_LIRIG.LIRIG_PREZO > 0 AND ROWNUM <= 3", sql)
        self.assertNotIn('((', sql)

    def test_the_limit_goes_before_group_by_having_and_order_by(self):
        sql = self.translate('SELECT $RigaListino.CatListino FROM $RigaListino GROUP BY $RigaListino.CatListino '
                             'ORDER BY $RigaListino.CatListino LIMIT 4')
        self.assertEqual(sql, 'SELECT GD_LIRIG.LIRIG_CATLI FROM GD_LIRIG WHERE ROWNUM <= 4 GROUP BY GD_LIRIG.LIRIG_CATLI '
                              'ORDER BY GD_LIRIG.LIRIG_CATLI')

    def test_limit_with_a_where_and_an_order_by(self):
        sql = self.translate("SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.Prezzo > 0 "
                             'ORDER BY $RigaListino.CodListino LIMIT 2')
        self.assertEqual(sql, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE GD_LIRIG.LIRIG_PREZO > 0 AND ROWNUM <= 2 '
                              'ORDER BY GD_LIRIG.LIRIG_LICOD')

    def test_limit_with_a_parameter(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino LIMIT ?P1')
        self.assertEqual(sql, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE ROWNUM <= ?P1')

    def test_a_limit_inside_a_subquery_stays_in_the_subquery(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CodListino IN '
                             '(SELECT $TestataListino.Codice FROM $TestataListino LIMIT 2)')
        self.assertIn('(SELECT GD_LITES.LITES_LICOD FROM GD_LITES WHERE ROWNUM <= 2)', sql)
        self.assertNotIn('FETCH', sql)

    def test_limit_in_every_part_of_a_union(self):
        sql = self.translate('SELECT $RigaListino.CodListino FROM $RigaListino LIMIT 1 UNION '
                             'SELECT $TestataListino.Codice FROM $TestataListino LIMIT 2')
        self.assertIn('WHERE ROWNUM <= 1', sql)
        self.assertIn('WHERE ROWNUM <= 2', sql)

    def test_limit_without_a_number_is_an_error(self):
        with self.assertRaises(ValueError):
            self.d.to_sql('SELECT $RigaListino.CodListino FROM $RigaListino LIMIT abc')


if __name__ == '__main__':
    unittest.main()
