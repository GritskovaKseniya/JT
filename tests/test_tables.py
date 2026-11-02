"""Catalogo, impostazioni e le classi delle tabelle (SQL, bind, INSERT/UPDATE di ogni tabella)."""
import copy
import os
import re
import unittest
from unittest.mock import patch

import helpers
from helpers import COLUMNS, JtCase, read_json, write_json, write_text
from jt.catalog import Catalog
from jt.config import MAX_KEYS, Paths
from jt.settings import Settings
from jt.tables import (MARK, TABLES, EmptySourceText, SchemaError, Translated, UpdateTarget, generate_id,
                       get_table)

ALL_NAMES = ['FW_STRINGS', 'FW_FIELD_STRINGS', 'FW_OPZIONI', 'FW_OPZIONI_DUE', 'FW_OPZIONI_TRE', 'FW_OPZIONI_INT',
             'FW_DOCU_NODES_T', 'FW_OBJ_DESCRS', 'FWK_STRINGS']
OPTION_NAMES = ['FW_OPZIONI', 'FW_OPZIONI_DUE', 'FW_OPZIONI_TRE', 'FW_OPZIONI_INT']


def fake_tr(text, required=False):
    """Come la funzione tr del servizio, ma senza Azure."""
    if text is None:
        if required:
            raise EmptySourceText('empty source text')
        return None
    return 'T:' + text


def resolved(name):
    return get_table(name).bind_columns(COLUMNS[name])


class CatalogTests(JtCase):
    def setUp(self):
        super().setUp()
        self.paths_ = self.paths()
        self.catalog = Catalog(self.paths_)

    def test_shipped_tables(self):
        entries = read_json(self.paths_.tables)
        self.assertEqual(len(entries), 9)
        self.assertEqual([e['table'] for e in entries], ALL_NAMES[:6] + ['FWK_STRINGS', 'FW_DOCU_NODES_T',
                                                                          'FW_OBJ_DESCRS'])
        enabled = [e['table'] for e in self.catalog.tables()]
        self.assertNotIn('FWK_STRINGS', enabled)
        self.assertEqual(len(enabled), 8)
        self.assertIn('FW_DOCU_NODES_T', enabled)
        self.assertIn('FW_OBJ_DESCRS', enabled)

    def test_every_shipped_table_has_a_spec(self):
        for entry in read_json(self.paths_.tables):
            self.assertIn(entry['table'], TABLES)

    def test_enabled_defaults_to_true(self):
        write_json(self.paths_.tables, [{'table': 'A', 'description': 'a'},
                                         {'table': 'B', 'description': 'b', 'enabled': False},
                                         {'table': 'C', 'description': 'c', 'enabled': True}])
        self.assertEqual([t['table'] for t in self.catalog.tables()], ['A', 'C'])

    def test_table_name(self):
        self.assertEqual(self.catalog.table_name('JFX: Strings'), 'FW_STRINGS')
        self.assertEqual(self.catalog.table_name('JFX: Object descriptions'), 'FW_OBJ_DESCRS')
        with self.assertRaises(KeyError):
            self.catalog.table_name('SFC: Strings & Triplets')       # disabilitata
        with self.assertRaises(KeyError):
            self.catalog.table_name('nope')

    def test_languages(self):
        names = self.catalog.languages()
        self.assertIn('Italian', names)
        self.assertIn('German', names)
        self.assertEqual(self.catalog.language_code('Italian'), 'it')
        self.assertEqual(self.catalog.language_code('German'), 'de')
        with self.assertRaises(KeyError):
            self.catalog.language_code('Klingon')


class SettingsAndPathsTests(JtCase):
    def setUp(self):
        super().setUp()
        self.paths_ = self.paths()
        self.settings = Settings(self.paths_)

    def test_connection_from_file(self):
        self.assertEqual(self.settings.connection(), helpers.FAKE_CONNECTION)

    def test_connection_missing_or_broken_file(self):
        empty = {k: '' for k in ('host', 'port', 'sid', 'username', 'password')}
        os.remove(self.paths_.connection)
        self.assertEqual(self.settings.connection(), empty)
        write_text(self.paths_.connection, '{broken')
        self.assertEqual(self.settings.connection(), empty)

    def test_save_connection_keeps_extra_keys(self):
        write_json(self.paths_.connection, {'extra': 1})
        self.settings.save_connection('h', '1', 's', 'u', 'p')
        data = read_json(self.paths_.connection)
        self.assertEqual(data, {'extra': 1, 'host': 'h', 'port': '1', 'sid': 's', 'username': 'u', 'password': 'p'})

    def test_last_query_round_trip(self):
        os.remove(self.paths_.query)
        self.assertEqual(self.settings.last_query(), {})
        self.settings.save_last_query('Italian', 'French', 'JFX: Strings')
        self.assertEqual(self.settings.last_query(), {'linput': 'Italian', 'loutput': 'French',
                                                      'table': 'JFX: Strings'})

    def test_azure_credentials(self):
        self.assertEqual(self.settings.azure_credentials(), helpers.FAKE_AZURE)
        os.remove(self.paths_.azure)
        with self.assertRaises(OSError):
            self.settings.azure_credentials()

    def test_paths(self):
        paths = Paths(self.tmp)
        self.assertEqual(paths.azure, os.path.join(self.tmp, 'Data', 'azure_services.json'))
        self.assertEqual(paths.logs, os.path.join(self.tmp, 'Logs'))
        self.assertEqual(paths.graphics, os.path.join(self.tmp, 'Graphics'))
        self.assertEqual(Paths.default().base, helpers.ROOT)


class KeyParsingTests(unittest.TestCase):
    NUMERIC = ['FW_STRINGS', 'FW_FIELD_STRINGS', 'FW_DOCU_NODES_T', 'FW_OBJ_DESCRS']
    NAMES = OPTION_NAMES + ['FWK_STRINGS']

    def test_numeric_tables_accept_mixed_separators(self):
        for name in self.NUMERIC:
            self.assertEqual(get_table(name).parse_keys(' 1, 2;3  4\n5 '), ['1', '2', '3', '4', '5'], name)

    def test_duplicates_removed_keeping_order(self):
        for name in ALL_NAMES:
            spec = get_table(name)
            self.assertEqual(spec.parse_keys('3,1,3,1,2'), ['3', '1', '2'], name)

    def test_names_tables(self):
        for name in self.NAMES:
            self.assertEqual(get_table(name).parse_keys('ProcessiLunghi , RdCategoriaEtichetta,Foo_1;x2'),
                             ['ProcessiLunghi', 'RdCategoriaEtichetta', 'Foo_1', 'x2'], name)

    def test_empty_text(self):
        for name in ALL_NAMES:
            self.assertEqual(get_table(name).parse_keys('  , ; '), [], name)
            self.assertEqual(get_table(name).parse_keys(''), [], name)

    def test_invalid_numeric_keys(self):
        for name in self.NUMERIC:
            for text in ('1; drop table x', 'abc', '1.5', '-1', "1' or '1'='1", '1,2,x'):
                with self.assertRaises(ValueError, msg=(name, text)):
                    get_table(name).parse_keys(text)

    def test_invalid_names(self):
        for name in self.NAMES:
            for text in ("x' or '1'='1", 'a-b', 'a.b', 'a(b)', '"q"', 'a%'):
                with self.assertRaises(ValueError, msg=(name, text)):
                    get_table(name).parse_keys(text)

    def test_value_error_carries_offending_key(self):
        with self.assertRaises(ValueError) as ctx:
            get_table('FW_STRINGS').parse_keys('1; drop table x')
        self.assertEqual(str(ctx.exception), 'drop')

    def test_too_many_keys(self):
        for name in ('FW_STRINGS', 'FW_OPZIONI'):
            spec = get_table(name)
            ok = ','.join(str(i) for i in range(MAX_KEYS))
            self.assertEqual(len(spec.parse_keys(ok)), MAX_KEYS)
            with self.assertRaises(ValueError):
                spec.parse_keys(ok + f',{MAX_KEYS}')

    def test_duplicates_do_not_count_toward_limit(self):
        spec = get_table('FW_STRINGS')
        text = ','.join(str(i) for i in range(MAX_KEYS)) + ',1,2,3'
        self.assertEqual(len(spec.parse_keys(text)), MAX_KEYS)


# parametri attesi per ogni tabella (con i nomi colonna risolti): lingua, chiave logica, colonna chiave, testo caratteri
EXPECTED = {
    'FW_STRINGS': dict(lang='language', keys=('code',), select='code', numeric=True, chars='LENGTH(value)'),
    'FW_FIELD_STRINGS': dict(lang='language', keys=('code',), select='code', numeric=True,
                             chars='NVL(LENGTH(caption), 0) + NVL(LENGTH(description), 0) + NVL(LENGTH(tip), 0)'),
    'FW_OPZIONI': dict(lang='lingua', keys=('tipo', 'codice'), select='tipo', numeric=False,
                       chars='LENGTH(descrizione)'),
    'FW_OPZIONI_DUE': dict(lang='lingua', keys=('tipo', 'codice'), select='tipo', numeric=False,
                           chars='LENGTH(descrizione)'),
    'FW_OPZIONI_TRE': dict(lang='lingua', keys=('tipo', 'codice'), select='tipo', numeric=False,
                           chars='LENGTH(descrizione)'),
    'FW_OPZIONI_INT': dict(lang='lingua', keys=('tipo', 'codice'), select='tipo', numeric=False,
                           chars='LENGTH(descrizione)'),
    'FW_DOCU_NODES_T': dict(lang='LANG', keys=('NODEID',), select='NODEID', numeric=True, chars='LENGTH(TEXT)'),
    'FW_OBJ_DESCRS': dict(lang='language', keys=('objid', 'tablename', 'tablefieldname'), select='objid',
                          numeric=True, chars='LENGTH(description)'),
    'FWK_STRINGS': dict(lang='lang', keys=('pack', 'code'), select='code', numeric=False,
                        chars='NVL(LENGTH(value), 0) + NVL(LENGTH(short_value), 0) + NVL(LENGTH(long_value), 0)'),
}


def predicate(name, e, limited):
    same = ' AND '.join(f'X.{k} = Y.{k}' for k in e['keys'])
    limit = ' AND ROWNUM <= :n' if limited else ''
    return (f"X.{e['lang']} = :li{limit} AND NOT EXISTS (SELECT 1 FROM {name} Y "
            f"WHERE {same} AND Y.{e['lang']} = :lo)")


class SelectionSqlTests(unittest.TestCase):
    EVIL = "x'; drop table t; --"

    def test_expected_covers_every_table(self):
        self.assertEqual(set(EXPECTED), set(TABLES))
        self.assertEqual(list(TABLES), ALL_NAMES)
        for name, spec in TABLES.items():
            self.assertEqual(spec.name, name)

    def test_read_missing_exact_for_strings(self):
        sql, binds = get_table('FW_STRINGS').read_missing('de', 'fr', 50)
        self.assertEqual(sql, 'SELECT * FROM FW_STRINGS X WHERE X.language = :li AND ROWNUM <= :n '
                              'AND NOT EXISTS (SELECT 1 FROM FW_STRINGS Y WHERE X.code = Y.code '
                              'AND Y.language = :lo)')
        self.assertEqual(binds, {'li': 'de', 'lo': 'fr', 'n': 50})

    def test_read_missing_every_table(self):
        for name, e in EXPECTED.items():
            sql, binds = resolved(name).read_missing('de', 'fr', 25)
            self.assertEqual(sql, f'SELECT * FROM {name} X WHERE {predicate(name, e, True)}', name)
            self.assertEqual(binds, {'li': 'de', 'lo': 'fr', 'n': 25}, name)

    def test_count_batch_every_table(self):
        for name, e in EXPECTED.items():
            (csql, cbinds), (ssql, sbinds) = resolved(name).count_batch('de', 'fr', 25)
            where = predicate(name, e, True)
            self.assertEqual(csql, f'SELECT COUNT(*) FROM {name} X WHERE {where}', name)
            self.assertEqual(ssql, f"SELECT SUM({e['chars']}) FROM {name} X WHERE {where}", name)
            self.assertEqual(cbinds, {'li': 'de', 'lo': 'fr', 'n': 25}, name)
            self.assertEqual(sbinds, cbinds, name)

    def test_count_all_every_table(self):
        for name, e in EXPECTED.items():
            sql, binds = resolved(name).count_all('de', 'fr')
            self.assertEqual(sql, f'SELECT COUNT(*) FROM {name} X WHERE {predicate(name, e, False)}', name)
            self.assertEqual(binds, {'li': 'de', 'lo': 'fr'}, name)
            self.assertNotIn(':n', sql)

    def test_languages_never_in_sql_text(self):
        for name in EXPECTED:
            spec = resolved(name)
            queries = [spec.read_missing(self.EVIL, 'fr', 5), spec.count_all(self.EVIL, 'fr'),
                       spec.read_keys(self.EVIL, ['1'])]
            queries += list(spec.count_batch(self.EVIL, 'fr', 5))
            for sql, binds in queries:
                self.assertNotIn(self.EVIL, sql, name)
                self.assertNotIn("'fr'", sql, name)
                self.assertNotIn('drop', sql, name)
                self.assertEqual(binds['li'], self.EVIL, name)

    def test_read_keys_every_table(self):
        for name, e in EXPECTED.items():
            spec = resolved(name)
            keys = ['10', '20', '30'] if e['numeric'] else ['ProcessiLunghi', 'Altro']
            sql, binds = spec.read_keys('it', keys)
            names = ', '.join(f':k{i}' for i in range(len(keys)))
            self.assertEqual(sql, f"SELECT * FROM {name} X WHERE X.{e['lang']} = :li AND X.{e['select']} IN ({names})",
                             name)
            expected = {'li': 'it'}
            expected.update({f'k{i}': (int(k) if e['numeric'] else k) for i, k in enumerate(keys)})
            self.assertEqual(binds, expected, name)
            if e['numeric']:
                self.assertTrue(all(isinstance(binds[f'k{i}'], int) for i in range(len(keys))), name)

    def test_read_keys_non_numeric_value_is_rejected_not_embedded(self):
        with self.assertRaises(ValueError):
            get_table('FW_STRINGS').read_keys('it', ['1; drop table x'])

    def test_needs_columns_flags(self):
        self.assertEqual([n for n, s in TABLES.items() if s.needs_columns], ['FW_DOCU_NODES_T', 'FWK_STRINGS'])

    def test_unresolved_docu_nodes_is_not_usable_and_unchanged_by_binding(self):
        spec = get_table('FW_DOCU_NODES_T')
        before = (spec.lang_col, spec.key_cols, spec.select_key)
        bound = spec.bind_columns(COLUMNS['FW_DOCU_NODES_T'])
        self.assertIsNot(bound, spec)
        self.assertEqual((spec.lang_col, spec.key_cols, spec.select_key), before)
        self.assertEqual(before, ('', (), ''))

    def test_docu_nodes_uses_db_column_names(self):
        bound = get_table('FW_DOCU_NODES_T').bind_columns(['ID_X', 'LNG_X', 'TXT_X', 'MORE'])
        sql, binds = bound.read_missing('de', 'fr', 5)
        self.assertEqual(sql, 'SELECT * FROM FW_DOCU_NODES_T X WHERE X.LNG_X = :li AND ROWNUM <= :n AND NOT EXISTS '
                              '(SELECT 1 FROM FW_DOCU_NODES_T Y WHERE X.ID_X = Y.ID_X AND Y.LNG_X = :lo)')
        self.assertEqual(bound.count_batch('de', 'fr', 5)[1][0].split(' FROM')[0], 'SELECT SUM(LENGTH(TXT_X))')
        self.assertIn('X.ID_X IN (:k0)', bound.read_keys('de', ['1'])[0])
        self.assertEqual(bound.update_target(('r',) * 4, 'fr', {'text': 'v'}, ['ID_X', 'LNG_X', 'TXT_X', 'MORE']),
                         UpdateTarget({'LNG_X': 'fr', 'ID_X': 'r'}, {'TXT_X': 'v'}, []))

    def test_docu_nodes_schema_error_with_few_columns(self):
        spec = get_table('FW_DOCU_NODES_T')
        for columns in ([], ['A'], ['A', 'B']):
            with self.assertRaises(SchemaError, msg=columns):
                spec.bind_columns(columns)
        spec.bind_columns(['A', 'B', 'C'])

    def test_other_tables_bind_columns_returns_self(self):
        for name in ALL_NAMES:
            if name != 'FW_DOCU_NODES_T':
                self.assertIs(get_table(name).bind_columns(['X']), get_table(name))

    def test_row_key(self):
        self.assertEqual(get_table('FW_STRINGS').row_key(('it', 100000, 'v')), '100000')
        self.assertEqual(get_table('FW_OPZIONI').row_key(('it', 'Tipo', '0')), 'Tipo')
        self.assertEqual(get_table('FW_DOCU_NODES_T').row_key((7, 'it', 't')), '7')
        self.assertEqual(get_table('FW_OBJ_DESCRS').row_key((555, 'T', 'F', 'it', 'd')), '555')
        fwk = get_table('FWK_STRINGS')
        self.assertEqual(fwk.row_key(('P', 'C1'), ['pack', 'code']), 'C1')
        self.assertEqual(fwk.row_key(('C1', 'P'), ['CODE', 'PACK']), 'C1')


def placeholders(sql):
    return re.findall(r':\d+', sql)


class RowWritingTests(unittest.TestCase):
    """translate_row / insert / update_target di ogni tabella."""

    def test_mark_constant(self):
        self.assertEqual(MARK, "'JT'")

    def check_no_literals(self, sql, *texts):
        for text in texts:
            self.assertNotIn(text, sql)
        self.assertNotIn('None', sql)

    # ------------------------------------------------------------- FW_STRINGS

    def test_strings(self):
        spec = get_table('FW_STRINGS')
        row = ('it', 100000, "l'ordine & 100% 'x'", None, None, None)
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(translated, Translated({'value': "T:l'ordine & 100% 'x'"}, "T:l'ordine & 100% 'x'"))
        sql, binds = spec.insert(row, 'fr', translated.values)
        self.assertEqual(sql, "INSERT INTO FW_STRINGS VALUES (:1, :2, :3, NULL, 'JT', sysdate)")
        self.assertEqual(binds, ['fr', 100000, "T:l'ordine & 100% 'x'"])
        self.check_no_literals(sql, "l'ordine", '&', '%', 'fr')
        self.assertEqual(spec.log_info(row), (100000, "l'ordine & 100% 'x'"))

    def test_strings_empty_source_is_rejected(self):
        spec = get_table('FW_STRINGS')
        with self.assertRaises(EmptySourceText):
            spec.translate_row(('it', 1, None, None, None, None), fake_tr)

    def test_strings_update_target(self):
        spec = get_table('FW_STRINGS')
        row = ('it', 100000, 'x', None, None, None)
        values = {'value': 'T:x'}
        self.assertEqual(spec.update_target(row, 'de', values, COLUMNS['FW_STRINGS']),
                         UpdateTarget({'language': 'de', 'code': 100000}, {'value': 'T:x'}, ['USR', 'DT']))
        for columns in (None, [], ['A', 'B', 'C', 'D', 'E'], ['A'] * 7):
            self.assertEqual(spec.update_target(row, 'de', values, columns).audit, [], columns)

    # ------------------------------------------------------- FW_FIELD_STRINGS

    def test_field_strings(self):
        spec = get_table('FW_FIELD_STRINGS')
        row = ('it', 10, "Cap's", 'Desc & more', "Tip 100%", None, None, None)
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(translated.values, {'caption': "T:Cap's", 'description': 'T:Desc & more',
                                             'tip': 'T:Tip 100%'})
        self.assertEqual(translated.primary, 'T:Desc & more')
        sql, binds = spec.insert(row, 'fr', translated.values)
        self.assertEqual(sql, "INSERT INTO FW_FIELD_STRINGS VALUES (:1, :2, :3, :4, :5, NULL, 'JT', sysdate)")
        self.assertEqual(binds, ['fr', 10, "T:Cap's", 'T:Desc & more', 'T:Tip 100%'])
        self.check_no_literals(sql, "Cap's", '&', '%')

    def test_field_strings_empty_optional_fields_are_null(self):
        spec = get_table('FW_FIELD_STRINGS')
        row = ('it', 10, 'Cap', None, None, None, None, None)
        translated = spec.translate_row(row, fake_tr)
        sql, binds = spec.insert(row, 'fr', translated.values)
        self.assertEqual(binds, ['fr', 10, 'T:Cap', None, None])
        self.assertNotIn('None', [b for b in binds if isinstance(b, str)])

    def test_field_strings_update_target(self):
        spec = get_table('FW_FIELD_STRINGS')
        values = {'caption': 'a', 'description': None, 'tip': 'c'}
        target = spec.update_target(('it', 10, 'x', None, 'y', None, None, None), 'de', values,
                                    COLUMNS['FW_FIELD_STRINGS'])
        self.assertEqual(target, UpdateTarget({'language': 'de', 'code': 10}, values, ['USR', 'DT']))
        self.assertEqual(spec.update_target(('it', 10), 'de', values, ['A'] * 7).audit, [])

    # ------------------------------------------------------------ opzioni

    def test_options_every_variant(self):
        for name in OPTION_NAMES:
            spec = get_table(name)
            row = ('it', 'ProcessiLunghi', '0', "Si' & 5%", 1, None, None, None)
            translated = spec.translate_row(row, fake_tr)
            self.assertEqual(translated, Translated({'description': "T:Si' & 5%"}, "T:Si' & 5%"), name)
            sql, binds = spec.insert(row, 'fr', translated.values)
            self.assertEqual(sql, f"INSERT INTO {name} VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)", name)
            self.assertEqual(binds, ['fr', 'ProcessiLunghi', '0', "T:Si' & 5%", 1, None], name)
            self.check_no_literals(sql, "Si'", '&', '%')
            self.assertEqual(spec.log_info(row), ('ProcessiLunghi', '0'), name)

    def test_options_empty_description_is_rejected(self):
        for name in OPTION_NAMES:
            with self.assertRaises(EmptySourceText, msg=name):
                get_table(name).translate_row(('it', 'T', '0', None, 1, 2, None, None), fake_tr)

    def test_options_update_target(self):
        for name in OPTION_NAMES:
            spec = get_table(name)
            target = spec.update_target(('it', 'Tipo', '3', 'x', 1, 2, None, None), 'de', {'description': 'T:x'},
                                        COLUMNS[name])
            self.assertEqual(target, UpdateTarget({'lingua': 'de', 'tipo': 'Tipo', 'codice': '3'},
                                                  {'descrizione': 'T:x'}, ['USR', 'DT']), name)
            self.assertEqual(spec.update_target(('it', 'Tipo', '3', 'x'), 'de', {'description': 'v'}, None).audit,
                             [], name)

    # --------------------------------------------------------- docu nodes

    def test_docu_nodes(self):
        spec = resolved('FW_DOCU_NODES_T')
        row = (100000, 'it', "Risorse 'UMV' & 5%", None)
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(translated, Translated({'text': "T:Risorse 'UMV' & 5%"}, "T:Risorse 'UMV' & 5%"))
        sql, binds = spec.insert(row, 'fr', translated.values)
        self.assertEqual(sql, 'INSERT INTO FW_DOCU_NODES_T VALUES (:1, :2, :3, NULL)')
        self.assertEqual(binds, [100000, 'fr', "T:Risorse 'UMV' & 5%"])
        self.assertEqual(spec.log_info(row), (100000, "Risorse 'UMV' & 5%"))

    def test_docu_nodes_empty_text_is_null_not_rejected(self):
        spec = resolved('FW_DOCU_NODES_T')
        row = (1, 'it', None, None)
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(translated, Translated({'text': None}, None))
        self.assertEqual(spec.insert(row, 'fr', translated.values)[1], [1, 'fr', None])

    def test_docu_nodes_update_target(self):
        spec = resolved('FW_DOCU_NODES_T')
        self.assertEqual(spec.update_target((7, 'it', 'x', None), 'de', {'text': 'T:x'}, COLUMNS['FW_DOCU_NODES_T']),
                         UpdateTarget({'LANG': 'de', 'NODEID': 7}, {'TEXT': 'T:x'}, []))

    # ------------------------------------------------------------ obj descrs

    def test_obj_descrs(self):
        spec = get_table('FW_OBJ_DESCRS')
        row = (555, 'MD_ARTI', 'ARTI_DESCR1', 'it', "Vite d'oro & 5%")
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(translated, Translated({'description': "T:Vite d'oro & 5%"}, "T:Vite d'oro & 5%"))
        sql, binds = spec.insert(row, 'fr', translated.values)
        self.assertEqual(sql, 'INSERT INTO FW_OBJ_DESCRS VALUES (:1, :2, :3, :4, :5)')
        self.assertEqual(binds, [555, 'MD_ARTI', 'ARTI_DESCR1', 'fr', "T:Vite d'oro & 5%"])
        self.assertEqual(spec.log_info(row), ('555/MD_ARTI.ARTI_DESCR1', "Vite d'oro & 5%"))
        self.check_no_literals(sql, "Vite", '&')

    def test_obj_descrs_empty_description_is_null(self):
        spec = get_table('FW_OBJ_DESCRS')
        row = (556, 'MD_ARTI', 'ARTI_DESCR1', 'it', None)
        translated = spec.translate_row(row, fake_tr)
        self.assertEqual(spec.insert(row, 'fr', translated.values)[1], [556, 'MD_ARTI', 'ARTI_DESCR1', 'fr', None])

    def test_obj_descrs_update_target(self):
        spec = get_table('FW_OBJ_DESCRS')
        target = spec.update_target((555, 'MD_ARTI', 'F', 'it', 'x'), 'de', {'description': 'T:x'}, COLUMNS['FW_OBJ_DESCRS'])
        self.assertEqual(target, UpdateTarget({'objid': 555, 'tablename': 'MD_ARTI', 'tablefieldname': 'F',
                                               'language': 'de'}, {'description': 'T:x'}, []))

    # -------------------------------------------------------------- FWK

    ROW = ('ID1', 77, 'packA', "Lungo's", 'Corto & x', None, 'it', None, 'JT', 'Valore 5%')

    def test_fwk_strings(self):
        spec = get_table('FWK_STRINGS')
        translated = spec.translate_row(self.ROW, fake_tr)
        self.assertEqual(translated.values, {'long_value': "T:Lungo's", 'short_value': 'T:Corto & x',
                                             'value': 'T:Valore 5%'})
        self.assertEqual(translated.primary, 'T:Valore 5%')
        with patch('jt.tables.generate_id', return_value='NEWID'):
            sql, binds = spec.insert(self.ROW, 'fr', translated.values)
        self.assertEqual(sql, "INSERT INTO FWK_STRINGS VALUES (:1, :2, :3, :4, :5, :6, :7, :8, 'JT', :9)")
        self.assertEqual(binds, ['NEWID', 77, 'packA', "T:Lungo's", 'T:Corto & x', None, 'fr', None, 'T:Valore 5%'])
        self.check_no_literals(sql, "Lungo", '&', '%')

    def test_fwk_update_target_finds_pack_and_code_by_name(self):
        spec = get_table('FWK_STRINGS')
        values = {'long_value': 'a', 'short_value': 'b', 'value': 'c'}
        target = spec.update_target(self.ROW, 'de', values, COLUMNS['FWK_STRINGS'])
        self.assertEqual(target, UpdateTarget({'lang': 'de', 'pack': 'packA', 'code': 77}, values, []))
        reordered = ('ID1', 'packB', 88)
        target = spec.update_target(reordered, 'de', values, ['id', 'pack', 'code'])
        self.assertEqual(target.where, {'lang': 'de', 'pack': 'packB', 'code': 88})

    def test_fwk_update_target_without_columns_fails(self):
        with self.assertRaises(Exception):
            get_table('FWK_STRINGS').update_target(self.ROW, 'de', {}, None)

    def test_generate_id(self):
        first, second = generate_id(), generate_id()
        self.assertEqual(len(first), 22)
        self.assertTrue(first.isalnum())
        self.assertNotEqual(first, second)
        self.assertEqual(len(generate_id(5)), 5)

    # ---------------------------------------------------------- tutte

    def test_every_insert_has_as_many_binds_as_placeholders(self):
        for name in ALL_NAMES:
            spec = resolved(name)
            row = helpers.SOURCE[name][0]
            translated = spec.translate_row(row, fake_tr)
            sql, binds = spec.insert(row, 'fr', translated.values)
            self.assertEqual(len(placeholders(sql)), len(binds), name)
            self.assertTrue(sql.startswith(f'INSERT INTO {name} VALUES ('), name)
            self.assertNotIn("'fr'", sql, name)

    def test_get_table(self):
        self.assertIs(get_table('FW_STRINGS'), TABLES['FW_STRINGS'])
        with self.assertRaises(KeyError):
            get_table('NOPE')

    def test_base_class_methods_not_implemented(self):
        from jt.tables import TableSpec
        spec = TableSpec()
        with self.assertRaises(NotImplementedError):
            spec.translate_row((), fake_tr)
        with self.assertRaises(NotImplementedError):
            spec.insert((), 'fr', {})
        with self.assertRaises(NotImplementedError):
            spec.update_target((), 'fr', {}, [])


if __name__ == '__main__':
    unittest.main()
