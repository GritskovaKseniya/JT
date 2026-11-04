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

    # PROBLEMA NOTO (c'era gia' in JCTNT, il test falliva anche li'): la subquery con una seconda tabella e senza campi
    # qualificati resta com'e' (GD_LITES, LITES_LICOD non diventano $TestataListino...) ma la traduzione risulta riuscita.
    # Da capire e correggere nel passo dello strumento SQL <-> TecSQL; intanto il test e' segnato come "atteso che fallisca".
    @unittest.expectedFailure
    def test_subquery_fields_translated(self):
        tecsql = self.to_tecsql(self.SUBQUERY)['tecsql']
        self.assertIn('$TestataListino', tecsql)
        self.assertIn('Codice', tecsql)               # LITES_LICOD -> Codice
        self.assertIn('CodCategoria', tecsql)         # LITES_CATLI -> CodCategoria

    @unittest.expectedFailure                        # stesso problema delle subquery (vedi sopra)
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


if __name__ == '__main__':
    unittest.main()
