"""Traduzione SQL -> TecSQL (`translate_sql_to_tecsql`), portata da JCTNT (da pytest a unittest): campi qualificati e non,
costanti passate dal JAS (nessun avviso), refusi nei nomi (avviso), subquery con piu' tabelle."""
import unittest

import tecsql_fixtures as fx


class SqlToTecsqlCase(fx.TecsqlCase):
    def to_tecsql(self, query, chosen_descriptor=None):
        """Traduce e controlla che sia riuscita e non ambigua."""
        result = self.d.to_tecsql(query, chosen_descriptor)
        self.assertTrue(result['success'], f"Traduzione fallita: {result.get('error')}")
        self.assertFalse(result.get('ambiguous'),
                         f"Descrittore ambiguo, serve chosen_descriptor. Candidati: {result.get('candidates')}")
        return result


class QualifiedFieldsTests(SqlToTecsqlCase):
    def test_simple_select(self):
        r = self.to_tecsql('SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertIn('$RigaListino.CodListino', r['tecsql'])
        self.assertIn('$RigaListino', r['tecsql'])

    def test_multiple_fields(self):
        r = self.to_tecsql('SELECT GD_LIRIG.LIRIG_LICOD, GD_LIRIG.LIRIG_CATLI FROM GD_LIRIG')
        self.assertIn('$RigaListino.CodListino', r['tecsql'])
        self.assertIn('$RigaListino.CatListino', r['tecsql'])

    def test_where_qualified(self):
        r = self.to_tecsql("SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE GD_LIRIG.LIRIG_CATLI = 'LL'")
        self.assertIn("$RigaListino.CatListino = 'LL'", r['tecsql'])

    def test_original_case_preserved(self):
        r = self.to_tecsql('SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertNotIn('$rigalistino', r['tecsql'])          # i nomi logici hanno le maiuscole del database
        self.assertIn('$RigaListino', r['tecsql'])


class UnqualifiedFieldsTests(SqlToTecsqlCase):
    def test_unqualified_in_select(self):
        r = self.to_tecsql('SELECT LIRIG_LICOD FROM GD_LIRIG')
        self.assertIn('CodListino', r['tecsql'])
        self.assertFalse(r['partial_translation'])

    def test_unqualified_uppercase_in_where(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_CATLI = 'LL'")
        self.assertIn('CatListino', r['tecsql'])
        self.assertFalse(r['partial_translation'], f"Non tradotti: {r['untranslated_fields']}")

    def test_count_star_no_warning(self):
        r = self.to_tecsql("SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_CATLI = 'LL'")
        self.assertFalse(r['partial_translation'], f"Non tradotti: {r['untranslated_fields']}")


class ConstantsVsTyposTests(SqlToTecsqlCase):
    def test_jas_constant_no_warning(self):
        """Un parametro del JAS a destra di = non e' un campo: nessun avviso, e resta nel risultato."""
        r = self.to_tecsql('SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD = CODICE_PASSATO_AL_JAS')
        self.assertNotIn('CODICE_PASSATO_AL_JAS', r.get('untranslated_fields', []))
        self.assertIn('CODICE_PASSATO_AL_JAS', r['tecsql'])

    def test_multiple_jas_constants_no_warning(self):
        r = self.to_tecsql('SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD = CODICE_PASSATO_AL_JAS '
                           'AND LIRIG_CATLI != CATEGORIA_PASSATA_AL_JAS')
        untranslated = r.get('untranslated_fields', [])
        self.assertNotIn('CODICE_PASSATO_AL_JAS', untranslated)
        self.assertNotIn('CATEGORIA_PASSATA_AL_JAS', untranslated)

    def test_field_typo_warns(self):
        """Un refuso maiuscolo di un campo vero (a sinistra di =) deve dare un avviso: LIRIG_CATLIT non esiste."""
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_CATLIT = 'LL'")
        self.assertTrue(r['partial_translation'])
        self.assertIn('LIRIG_CATLIT', r['untranslated_fields'])


class MultiTableTests(SqlToTecsqlCase):
    SUBQUERY = ('SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_LICOD IN ('
                '  SELECT LITES_LICOD FROM GD_LITES '
                "  WHERE LITES_CATLI = 'LL'"
                ')')

    def test_subquery_no_false_positive(self):
        """Regressione: tradotta la subquery, il nome del descrittore non compare tra i campi non tradotti."""
        untranslated = self.to_tecsql(self.SUBQUERY).get('untranslated_fields', [])
        self.assertNotIn('TestataListino', untranslated)
        self.assertNotIn('RigaListino', untranslated)

    def test_subquery_fields_translated(self):
        tecsql = self.to_tecsql(self.SUBQUERY)['tecsql']
        self.assertIn('$TestataListino', tecsql)
        self.assertIn('Codice', tecsql)               # LITES_LICOD -> Codice
        self.assertIn('CodCategoria', tecsql)         # LITES_CATLI -> CodCategoria

    def test_full_multiline_query(self):
        sql = ('SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_LICOD IN ('
               '  SELECT DISTINCT LITES_LICOD FROM GD_LITES '
               "  WHERE LITES_CATLI = 'LL'"
               ') '
               "AND LIRIG_CATLI = 'LL' "
               'ORDER BY 1 DESC')
        r = self.to_tecsql(sql)
        self.assertFalse(r['partial_translation'], f"Non tradotti: {r['untranslated_fields']}")
        self.assertIn('$RigaListino', r['tecsql'])
        self.assertIn('$TestataListino', r['tecsql'])


class SubqueryTests(SqlToTecsqlCase):
    """Le subquery si traducono con le parentesi abbinate davvero. Il difetto che c'era (gia' in JCTNT): una `( SELECT` con uno
    spazio dopo la parentesi, o una subquery con una funzione dentro (`MAX(x)`), non veniva riconosciuta: restava in SQL e la
    traduzione risultava lo stesso "riuscita"."""

    def test_a_space_after_the_bracket(self):
        r = self.to_tecsql("SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_LICOD IN ( SELECT LITES_LICOD FROM GD_LITES WHERE LITES_CATLI = 'LL' )")
        self.assertIn('$TestataListino.Codice', r['tecsql'])
        self.assertNotIn('GD_LITES', r['tecsql'])
        self.assertFalse(r['partial_translation'], r['untranslated_fields'])

    def test_no_space_after_the_bracket(self):
        r = self.to_tecsql("SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT LITES_LICOD FROM GD_LITES)")
        self.assertIn('(SELECT $TestataListino.Codice FROM $TestataListino)', r['tecsql'])

    def test_a_function_inside_the_subquery(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_PREZO = (SELECT MAX(LITES_LICOD) FROM GD_LITES)")
        self.assertNotIn('GD_LITES', r['tecsql'])
        self.assertNotIn('LITES_LICOD', r['tecsql'])
        self.assertIn('$TestataListino.Codice', r['tecsql'])
        self.assertFalse(r['partial_translation'], r['untranslated_fields'])

    def test_a_subquery_inside_a_subquery(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT LITES_LICOD FROM GD_LITES WHERE "
                           "LITES_CATLI IN (SELECT LIRIG_CATLI FROM GD_LIRIG WHERE LIRIG_PREZO > 0))")
        for physical in ('GD_LIRIG', 'GD_LITES', 'LITES_', 'LIRIG_'):
            self.assertNotIn(physical, r['tecsql'])
        self.assertEqual(r['tecsql'].count('$RigaListino.'), 4)
        self.assertEqual(r['tecsql'].count('$TestataListino.'), 2)

    def test_two_subqueries_side_by_side(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT LITES_LICOD FROM GD_LITES) "
                           "AND LIRIG_CATLI IN (SELECT LITES_CATLI FROM GD_LITES)")
        self.assertNotIn('GD_LITES', r['tecsql'])
        self.assertIn('$TestataListino.Codice', r['tecsql'])
        self.assertIn('$TestataListino.CodCategoria', r['tecsql'])

    def test_a_bracket_inside_a_string_is_not_a_subquery(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_CATLI = '(SELECT x FROM y)'")
        self.assertIn("'(SELECT x FROM y)'", r['tecsql'])
        self.assertFalse(r['partial_translation'], r['untranslated_fields'])

    def test_a_subquery_that_cannot_be_translated_is_said(self):
        """Prima: lasciata com'era e nessun avviso. Ora il resto si traduce, la subquery resta e la traduzione e' 'in parte'."""
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT X FROM NON_ESISTE)")
        self.assertIn('$RigaListino.CodListino', r['tecsql'])
        self.assertIn('(SELECT X FROM NON_ESISTE)', r['tecsql'])
        self.assertTrue(r['partial_translation'])
        self.assertIn('subquery not translated: Table NON_ESISTE not found in the dictionary', r['untranslated_fields'])

    def test_a_field_the_subquery_does_not_know_is_reported(self):
        r = self.to_tecsql("SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT LITES_LICOD FROM GD_LITES WHERE LITES_NOPE = 1)")
        self.assertTrue(r['partial_translation'])
        self.assertIn('LITES_NOPE', r['untranslated_fields'])

    def test_a_subquery_in_the_from(self):
        r = self.to_tecsql("SELECT T.LIRIG_LICOD FROM (SELECT LIRIG_LICOD FROM GD_LIRIG) T")
        self.assertIn('(SELECT $RigaListino.CodListino FROM $RigaListino)', r['tecsql'])


class AmbiguousSubqueryTests(unittest.TestCase):
    """Una subquery su una tabella con piu' nomi logici: si chiede quale, come per la query (prima: restava com'era)."""

    def setUp(self):
        from jt.tecsql_translator import Dictionary
        self.d = Dictionary(fx.rows_as_dicts() + fx.rows_as_dicts([
            ('MD_ARTI', '$Articolo', 'ARTI_ARTCO', 'Codice', 'C', 20, 0),
            ('MD_ARTI', '$ArticoloEsteso', 'ARTI_ARTCO', 'Codice', 'C', 20, 0)]))
        self.sql = 'SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_ARTCO IN (SELECT ARTI_ARTCO FROM MD_ARTI)'

    def test_the_question_comes_from_the_subquery(self):
        r = self.d.to_tecsql(self.sql)
        self.assertTrue(r.get('ambiguous'))
        self.assertEqual(r['table'], 'MD_ARTI')
        self.assertEqual(sorted(r['candidates']), ['$Articolo', '$ArticoloEsteso'])

    def test_with_the_choice_it_is_translated(self):
        r = self.d.to_tecsql(self.sql, '$articoloesteso')
        self.assertTrue(r['success'], r)
        self.assertIn('(SELECT $ArticoloEsteso.Codice FROM $ArticoloEsteso)', r['tecsql'])
        self.assertIn('$RigaListino.CodArticolo', r['tecsql'])


if __name__ == '__main__':
    unittest.main()
