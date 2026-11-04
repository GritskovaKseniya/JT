"""TranslationService contro il finto database, e i log CSV di jt.logs."""
import csv
import glob
import os
import re
import unittest
from unittest.mock import patch

import helpers
from helpers import COLUMNS, FakeAzure, FakeDriver, JtCase
from jt.azure import AzureTranslator
from jt.config import SECONDS_PER_ROW
from jt.db import Database
from jt.glossary import Glossary
from jt.layers import BY_NAME
from jt.logs import write_run_logs
from jt.service import Progress, RunResult, Selection, TranslationService
from jt.tables import TABLES, SchemaError, get_table

ALL_NAMES = list(TABLES)

# prima riga di helpers.SOURCE tradotta de -> fr con il traduttore finto ('T:' + testo)
FIRST_INSERT = {
    'FW_STRINGS': ("INSERT INTO FW_STRINGS VALUES (:1, :2, :3, :4, 'JT', sysdate)",
                   ['fr', 100000, 'T:Ordine UMV', None]),
    'FW_FIELD_STRINGS': ("INSERT INTO FW_FIELD_STRINGS VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)",
                         ['fr', 10, 'T:Cod UMV', None, None, None]),
    'FW_OPZIONI': ("INSERT INTO FW_OPZIONI VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)",
                   ['fr', 'ProcessiLunghi', '0', 'T:Si', 1, 2]),
    'FW_OPZIONI_DUE': ("INSERT INTO FW_OPZIONI_DUE VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)",
                       ['fr', 'Due', '0', 'T:Uno', None, None]),
    'FW_OPZIONI_TRE': ("INSERT INTO FW_OPZIONI_TRE VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)",
                       ['fr', 'ProcessiLunghi', '0', 'T:Si', 1, 2]),
    'FW_OPZIONI_INT': ("INSERT INTO FW_OPZIONI_INT VALUES (:1, :2, :3, :4, :5, :6, 'JT', sysdate)",
                       ['fr', 'Int', '5', 'T:Cinque', 5, None]),
    'FW_DOCU_NODES_T': ('INSERT INTO FW_DOCU_NODES_T (NODEID, LANG, NODETITLE) VALUES (:1, :2, :3)', [100000, 'fr', 'T:Risorse UMV']),
    'FW_OBJ_DESCRS': ('INSERT INTO FW_OBJ_DESCRS VALUES (:1, :2, :3, :4, :5)',
                      [555, 'MD_ARTI', 'ARTI_DESCR1', 'fr', 'T:Vite']),
    'FWK_STRINGS': ("INSERT INTO FWK_STRINGS VALUES (:1, :2, :3, :4, :5, :6, :7, :8, 'JT', :9)",
                    ['NEWID', 77, 'packA', 'T:Lungo', 'T:Corto', None, 'fr', None, 'T:Valore']),
}


class ServiceCase(JtCase):
    def setUp(self):
        super().setUp()
        self.driver = FakeDriver()
        self.state = self.driver.db
        self.db = Database(self.driver)
        self.db.connect('h', '1521', 'S', 'u', 'p')
        self.service = TranslationService(self.db)
        self.azure = FakeAzure()
        self.translator = self.make_translator(self.azure)
        patcher = patch('jt.tables.generate_id', return_value='NEWID')
        patcher.start()
        self.addCleanup(patcher.stop)

    @staticmethod
    def make_translator(post):
        return AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=post)

    @property
    def conn(self):
        return self.state.conns[-1]

    def set_missing(self):
        self.state.missing = {n: len(rows) for n, rows in self.state.source.items()}

    def missing_selection(self, name='FW_STRINGS', limit=100):
        self.set_missing()
        return self.service.load_missing(get_table(name), 'de', 'fr', limit)

    def keys_selection(self, name, keys):
        spec = get_table(name)
        return self.service.load_keys(spec, 'it', 'de', spec.parse_keys(keys))


class LoadMissingTests(ServiceCase):
    def test_selection_fields_and_queries(self):
        self.state.missing['FW_STRINGS'] = 2
        self.state.chars = 321
        selection = self.service.load_missing(get_table('FW_STRINGS'), 'de', 'fr', 10)
        spec = get_table('FW_STRINGS')
        self.assertEqual((selection.mode, selection.lan_in, selection.lan_out), ('missing', 'de', 'fr'))
        self.assertEqual((selection.total, selection.chars), (2, 321))
        self.assertFalse(selection.update_mode)
        self.assertEqual(selection.columns, [])
        self.assertEqual(selection.missing_keys, [])
        self.assertEqual(self.state.log[0], spec.read_missing('de', 'fr', 10))
        (count_sql, count_binds), (sum_sql, sum_binds) = spec.count_batch('de', 'fr', 10)
        self.assertEqual(self.state.log[1], (count_sql, count_binds))
        self.assertEqual(self.state.log[2], (sum_sql, sum_binds))
        self.assertIn('SUM(LENGTH(value))', sum_sql)

    def test_level_goes_to_the_queries_and_is_remembered(self):
        self.state.missing['FW_STRINGS'] = 2
        spec, ct = get_table('FW_STRINGS'), BY_NAME['CT']
        selection = self.service.load_missing(spec, 'de', 'fr', 10, level=ct)
        self.assertIs(selection.level, ct)
        self.assertEqual(self.state.log[0], spec.read_missing('de', 'fr', 10, ct))
        (count_query, sum_query) = spec.count_batch('de', 'fr', 10, ct)
        self.assertEqual(self.state.log[1:3], [count_query, sum_query])
        self.assertEqual(self.state.log[0][1]['lvl_lo'], 3000000)

    def test_without_level_the_selection_has_none(self):
        self.assertIsNone(self.missing_selection().level)

    def test_cursor_is_kept_open_and_yields_rows(self):
        selection = self.missing_selection()
        self.assertFalse(selection.rows.closed)
        self.assertEqual(list(selection.rows), self.state.source['FW_STRINGS'])

    def test_chars_none_becomes_zero(self):
        self.state.chars = None
        self.assertEqual(self.missing_selection().chars, 0)

    def test_previous_cursors_closed_on_reload(self):
        first = self.missing_selection()
        second = self.missing_selection()
        self.assertTrue(first.rows.closed)
        self.assertFalse(second.rows.closed)

    def test_docu_nodes_is_resolved_with_db_columns(self):
        selection = self.missing_selection('FW_DOCU_NODES_T')
        self.assertEqual(selection.spec.lang_col, 'LANG')
        self.assertIn('X.LANG = :li', self.state.log[1][0])

    def test_docu_nodes_with_unreadable_columns_raises_schema_error(self):
        self.state.columns['FW_DOCU_NODES_T'] = ['A']
        with self.assertRaises(SchemaError):
            self.service.load_missing(get_table('FW_DOCU_NODES_T'), 'de', 'fr', 5)

    def test_estimated_minutes(self):
        selection = Selection(None, 'it', 'de', 'missing', [], 96, 0)
        self.assertEqual(selection.estimated_minutes, round(96 * SECONDS_PER_ROW / 60, 1))
        self.assertEqual(selection.estimated_minutes, 1.0)
        self.assertEqual(Selection(None, 'it', 'de', 'missing', [], 1000, 0).estimated_minutes, 10.4)
        self.assertEqual(Selection(None, 'it', 'de', 'missing', [], 0, 0).estimated_minutes, 0)


class LoadKeysTests(ServiceCase):
    def test_found_and_missing_keys(self):
        selection = self.keys_selection('FW_STRINGS', '100000, 999')
        self.assertEqual(selection.mode, 'keys')
        self.assertTrue(selection.update_mode)
        self.assertEqual(selection.total, 1)
        self.assertEqual(selection.rows, [self.state.source['FW_STRINGS'][0]])
        self.assertEqual(selection.missing_keys, ['999'])
        self.assertEqual(selection.columns, COLUMNS['FW_STRINGS'])
        self.assertEqual(selection.chars, len('it') + len('Ordine UMV'))
        sql, binds = self.state.log[-1]
        self.assertEqual(binds, {'li': 'it', 'k0': 100000, 'k1': 999})

    def test_all_keys_found(self):
        selection = self.keys_selection('FW_STRINGS', '100000 100001')
        self.assertEqual((selection.total, selection.missing_keys), (2, []))

    def test_no_key_found(self):
        selection = self.keys_selection('FW_STRINGS', '5, 6')
        self.assertEqual((selection.total, selection.chars, selection.missing_keys), (0, 0, ['5', '6']))
        self.assertEqual(selection.rows, [])

    def test_option_names_load_all_their_codes(self):
        selection = self.keys_selection('FW_OPZIONI', 'ProcessiLunghi, Nope')
        self.assertEqual(selection.total, 2)
        self.assertEqual(selection.missing_keys, ['Nope'])

    def test_docu_nodes_uses_db_columns(self):
        selection = self.keys_selection('FW_DOCU_NODES_T', '100000')
        self.assertEqual(selection.columns, COLUMNS['FW_DOCU_NODES_T'])
        self.assertEqual(selection.total, 1)
        self.assertIn('X.NODEID IN (:k0)', self.state.log[-1][0])

    def test_obj_descrs_and_field_strings(self):
        self.assertEqual(self.keys_selection('FW_OBJ_DESCRS', '555').missing_keys, [])
        self.assertEqual(self.keys_selection('FW_FIELD_STRINGS', '10, 11').missing_keys, ['11'])

    def test_fwk_found_by_code_column_name(self):
        selection = self.keys_selection('FWK_STRINGS', '77')
        self.assertEqual((selection.total, selection.missing_keys), (1, []))

    def test_unreadable_columns_tolerated_when_table_does_not_need_them(self):
        self.state.fail_sql = ['WHERE 1 = 0']
        selection = self.keys_selection('FW_STRINGS', '100000')
        self.assertEqual(selection.columns, [])
        self.assertEqual(selection.total, 1)

    def test_unreadable_columns_raise_when_table_needs_them(self):
        self.state.fail_sql = ['WHERE 1 = 0']
        with self.assertRaises(RuntimeError):
            self.keys_selection('FWK_STRINGS', '77')

    def test_previous_cursors_closed(self):
        first = self.missing_selection()
        self.keys_selection('FW_STRINGS', '100000')
        self.assertTrue(first.rows.closed)


class LoadKeysByLevelTests(ServiceCase):
    CT_ROW = ('it', 3000001, 'Testo CT', None, None, None)

    def setUp(self):
        super().setUp()
        self.state.source['FW_STRINGS'].append(self.CT_ROW)
        self.state.source['FW_OPZIONI'] += [('it', 'CtOpz', '0', 'Si', 1, 2, None, None),
                                            ('it', 'ctOpz', '0', 'Si', 1, 2, None, None)]

    def load(self, name, keys, level):
        spec = get_table(name)
        return self.service.load_keys(spec, 'it', 'de', spec.parse_keys(keys), level)

    def test_rows_of_the_chosen_level_are_kept_and_the_others_set_aside(self):
        selection = self.load('FW_STRINGS', '100000, 3000001', BY_NAME['CT'])
        self.assertEqual(selection.rows, [self.CT_ROW])
        self.assertEqual((selection.total, selection.chars), (1, len('it') + len('Testo CT')))
        self.assertEqual([(row[1], layer.name) for row, layer in selection.other_level], [(100000, 'AP')])
        self.assertIs(selection.level, BY_NAME['CT'])
        self.assertEqual(selection.missing_keys, [])           # trovata, solo di un altro livello

    def test_without_level_nothing_is_set_aside(self):
        selection = self.load('FW_STRINGS', '100000, 3000001', None)
        self.assertEqual((selection.total, selection.other_level, selection.level), (2, [], None))

    def test_a_code_outside_every_range_is_set_aside_with_no_layer(self):
        self.state.source['FW_STRINGS'].append(('it', 7000000, 'Fuori', None, None, None))
        selection = self.load('FW_STRINGS', '7000000', BY_NAME['AP'])
        self.assertEqual((selection.total, [layer for _, layer in selection.other_level]), (0, [None]))

    def test_options_are_split_by_name_prefix(self):
        selection = self.load('FW_OPZIONI', 'CtOpz, ctOpz, ProcessiLunghi', BY_NAME['CT'])
        self.assertEqual([row[1] for row in selection.rows], ['CtOpz'])
        self.assertEqual(sorted((row[1], layer.name if layer else None) for row, layer in selection.other_level),
                         [('ProcessiLunghi', 'AP'), ('ProcessiLunghi', 'AP'), ('ctOpz', None)])

    def test_tables_without_levels_keep_every_row(self):
        selection = self.load('FW_DOCU_NODES_T', '100000', BY_NAME['CT'])
        self.assertEqual((selection.total, selection.other_level), (1, []))

    def test_run_skips_other_level_rows_and_writes_the_reason(self):
        selection = self.load('FW_STRINGS', '100000, 3000001', BY_NAME['CT'])
        result = self.service.run(selection, self.translator)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(len(result.successes), 1)
        self.assertEqual(result.successes[0]['code'], 3000001)
        entry = result.skipped_rows[0]
        self.assertEqual((entry['code'], entry['input']), (100000, 'Ordine UMV'))
        self.assertEqual(entry['reason'], 'key 100000 is level AP, selected level is CT')
        self.assertEqual(len(self.state.writes()), 1)

    def test_run_writes_the_user_of_the_level_in_insert_and_update(self):
        self.state.source['FW_STRINGS'].append(('it', 4000001, 'Testo CW', None, None, None))
        self.state.existing.add(('FW_STRINGS', (('language', 'de'), ('code', 3000001))))      # CT gia' presente: UPDATE
        self.service.run(self.load('FW_STRINGS', '3000001, 4000001, 100000', None), self.translator)
        statements = [sql for sql, binds in self.state.writes()]
        self.assertEqual(len(statements), 3)
        self.assertTrue(any(s.startswith('UPDATE') and "= 'ZFXCUSTOM'" in s for s in statements), statements)
        self.assertTrue(any(s.startswith('INSERT') and "'ZFXINTEGR', sysdate" in s for s in statements), statements)
        self.assertTrue(any(s.startswith('INSERT') and "'JT', sysdate" in s for s in statements), statements)

    def test_logs_say_the_level_and_the_user_written(self):
        self.state.source['FW_STRINGS'].append(('it', 4000001, 'Testo CW', None, None, None))
        # senza livello (All) ogni riga ha il suo
        result = self.service.run(self.load('FW_STRINGS', '3000001, 4000001, 100000', None), self.translator)
        seen = {entry['code']: (entry['level'], entry['user']) for entry in result.successes}
        self.assertEqual(seen, {3000001: ('CT', 'ZFXCUSTOM'), 4000001: ('CW', 'ZFXINTEGR'), 100000: ('Standard', 'JT')})

    def test_skipped_log_of_another_level_has_the_level_of_the_row_and_no_user(self):
        selection = self.load('FW_STRINGS', '100000, 3000001', BY_NAME['CT'])
        entry = self.service.run(selection, self.translator).skipped_rows[0]
        self.assertEqual((entry['code'], entry['level'], entry['user']), (100000, 'Standard', ''))
        selection = self.load('FW_OPZIONI', 'ctOpz', BY_NAME['CT'])
        entry = self.service.run(selection, self.translator).skipped_rows[0]
        self.assertEqual((entry['level'], entry['user']), ('unknown', ''))

    def test_run_reason_for_a_row_with_no_layer(self):
        selection = self.load('FW_OPZIONI', 'ctOpz', BY_NAME['CT'])
        result = self.service.run(selection, self.translator)
        self.assertEqual(result.skipped_rows[0]['reason'], 'key ctOpz is unknown level, selected level is CT')
        self.assertEqual(self.state.writes(), [])


class MissingCountsTests(ServiceCase):
    def test_counts_for_every_table(self):
        self.state.missing = {name: i + 1 for i, name in enumerate(ALL_NAMES)}
        counts = self.service.missing_counts(list(TABLES.values()), 'de', 'fr')
        self.assertEqual(counts, {name: i + 1 for i, name in enumerate(ALL_NAMES)})
        for sql, binds in self.state.log:
            if sql.startswith('SELECT COUNT(*)'):
                self.assertEqual(binds, {'li': 'de', 'lo': 'fr'})

    def test_one_failure_gives_none_for_that_table_only(self):
        self.state.missing = {name: 4 for name in ALL_NAMES}
        self.state.fail_sql = ['FROM FW_OPZIONI X']
        counts = self.service.missing_counts(list(TABLES.values()), 'de', 'fr')
        self.assertIsNone(counts['FW_OPZIONI'])
        self.assertEqual([n for n, c in counts.items() if c is None], ['FW_OPZIONI'])
        self.assertEqual(counts['FW_OPZIONI_DUE'], 4)

    def test_docu_nodes_with_unreadable_columns_gives_none(self):
        self.state.columns['FW_DOCU_NODES_T'] = ['ONLY_ONE']
        self.state.missing = {name: 3 for name in ALL_NAMES}
        counts = self.service.missing_counts([get_table('FW_DOCU_NODES_T'), get_table('FW_STRINGS')], 'de', 'fr')
        self.assertEqual(counts, {'FW_DOCU_NODES_T': None, 'FW_STRINGS': 3})

    def test_empty_list(self):
        self.assertEqual(self.service.missing_counts([], 'de', 'fr'), {})

    def test_level_goes_to_every_count_query(self):
        self.state.missing = {name: 2 for name in ALL_NAMES}
        self.service.missing_counts([get_table('FW_STRINGS'), get_table('FW_OPZIONI')], 'de', 'fr', BY_NAME['CW'])
        counts = [(sql, binds) for sql, binds in self.state.log if sql.startswith('SELECT COUNT(*)')]
        self.assertEqual(len(counts), 2)
        self.assertEqual(counts[0][1]['lvl_lo'], 4000000)
        self.assertEqual(counts[1][1]['lvl_p'], 'Cw%')


class RunMissingModeTests(ServiceCase):
    def test_insert_shape_for_every_table(self):
        for name in ALL_NAMES:
            with self.subTest(table=name):
                self.state.log.clear()
                selection = self.missing_selection(name)
                result = self.service.run(selection, self.translator)
                sql, binds = self.state.inserts()[0]
                self.assertEqual((sql, binds), FIRST_INSERT[name])
                self.assertEqual(result.inserts, len(self.state.source[name]))
                self.assertEqual((result.updates, result.skipped, result.errors, result.stopped), (0, 0, [], False))
                self.assertEqual(len(self.state.writes()), len(self.state.source[name]))
                self.assertEqual(self.state.updates(), [])

    def test_non_italian_pair_reaches_azure_and_sql(self):
        selection = self.missing_selection()
        self.service.run(selection, self.translator)
        self.assertEqual([c['params']['from'] for c in self.azure.calls], ['de', 'de'])
        self.assertEqual([c['params']['to'] for c in self.azure.calls], [['fr'], ['fr']])
        for sql, binds in self.state.writes():
            self.assertNotIn("'fr'", sql)
            self.assertEqual(binds[0], 'fr')

    def test_log_dict_contents(self):
        selection = self.missing_selection()
        with patch('jt.service.datetime') as dt:
            dt.now.return_value.isoformat.return_value = '2026-01-02T03:04:05'
            result = self.service.run(selection, self.translator)
        self.assertEqual(result.successes[0], {'date': '2026-01-02T03:04:05', 'action': 'insert', 'code': 100000,
                                               'level': 'Standard', 'user': 'JT', 'lng_in': 'de', 'lng_out': 'fr',
                                               'input': 'Ordine UMV', 'output': 'T:Ordine UMV'})
        self.assertEqual(list(result.successes[0]), ['date', 'action', 'code', 'level', 'user', 'lng_in', 'lng_out',
                                                     'input', 'output'])
        self.assertEqual(result.successes[1]['code'], 100001)

    def test_commit_per_row(self):
        selection = self.missing_selection()
        self.service.run(selection, self.translator)
        self.assertEqual(self.conn.commits, 2)

    def test_apostrophes_and_special_chars_only_in_binds(self):
        self.state.source['FW_STRINGS'] = [('it', 1, "l'ordine & 100% 'x'", None, None, None)]
        selection = self.missing_selection()
        self.service.run(selection, self.translator)
        sql, binds = self.state.inserts()[0]
        self.assertEqual(binds, ['fr', 1, "T:l'ordine & 100% 'x'", None])
        for text in ("l'ordine", '&', '%'):
            self.assertNotIn(text, sql)

    def test_azure_failure_skips_only_that_row(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Nuovo'))
        selection = self.missing_selection()
        result = self.service.run(selection, self.translator)
        self.assertEqual((result.inserts, result.skipped, result.errors), (1, 1, []))
        self.assertEqual(len(self.state.inserts()), 1)
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual([s['code'] for s in result.successes], [100000])

    def test_azure_failure_on_first_row_continues_with_next(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Ordine'))
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual((result.inserts, result.skipped), (1, 1))
        self.assertEqual(self.state.inserts()[0][1][1], 100001)

    def test_empty_required_text_is_skipped(self):
        self.state.source['FW_STRINGS'] = [('it', 1, None, None, None, None), ('it', 2, 'ok', None, None, None)]
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual((result.inserts, result.skipped, result.errors), (1, 1, []))
        self.assertEqual(self.azure.calls[0]['text'], 'ok')

    def test_insert_error_goes_to_errors_and_run_continues(self):
        self.state.fail_write = lambda sql, binds: 'T:Ordine UMV' in binds
        with patch('jt.service.datetime') as dt:
            dt.now.return_value.isoformat.return_value = 'NOW'
            result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual((result.inserts, result.skipped), (1, 0))
        self.assertEqual(result.errors, [{'date': 'NOW', 'code': 100000, 'level': 'Standard', 'user': 'JT',
                                          'lng_in': 'de', 'lng_out': 'fr', 'input': 'Ordine UMV',
                                          'reason': 'simulated write error'}])
        self.assertEqual(self.conn.commits, 1)
        self.assertEqual([s['code'] for s in result.successes], [100001])

    def test_progress_callbacks(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Nuovo'))
        events = []
        self.service.run(self.missing_selection(), self.translator, on_progress=events.append)
        self.assertEqual([(p.done, p.total, p.inserts, p.updates, p.errors, p.skipped) for p in events],
                         [(1, 2, 1, 0, 0, 0), (2, 2, 1, 0, 0, 1)])
        self.assertTrue(all(isinstance(p, Progress) for p in events))
        self.assertEqual(events[-1].expected_min, 0)
        self.assertGreaterEqual(events[0].elapsed_min, 0)

    def test_progress_counts_errors(self):
        self.state.fail_write = lambda sql, binds: True
        events = []
        self.service.run(self.missing_selection(), self.translator, on_progress=events.append)
        self.assertEqual([(p.done, p.errors, p.inserts) for p in events], [(1, 1, 0), (2, 2, 0)])

    def test_progress_expected_time(self):
        events = []
        with patch('jt.service.time.time', side_effect=[1000.0, 1060.0, 1120.0]):
            self.service.run(self.missing_selection(), self.translator, on_progress=events.append)
        self.assertEqual((events[0].elapsed_min, events[0].expected_min), (1.0, 1.0))
        self.assertEqual((events[1].elapsed_min, events[1].expected_min), (2.0, 0.0))

    def test_should_stop_after_current_row(self):
        selection = self.missing_selection()
        events = []
        result = self.service.run(selection, self.translator, on_progress=events.append,
                                  should_stop=lambda: len(self.state.writes()) >= 1)
        self.assertTrue(result.stopped)
        self.assertEqual(result.inserts, 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(self.azure.calls), 1)
        self.assertEqual(self.conn.commits, 1)

    def test_should_stop_immediately(self):
        result = self.service.run(self.missing_selection(), self.translator, should_stop=lambda: True)
        self.assertTrue(result.stopped)
        self.assertEqual((result.inserts, self.azure.calls, self.state.writes()), (0, [], []))

    def test_should_stop_false_runs_everything(self):
        result = self.service.run(self.missing_selection(), self.translator, should_stop=lambda: False)
        self.assertFalse(result.stopped)
        self.assertEqual(result.inserts, 2)

    def test_empty_selection(self):
        self.state.source['FW_STRINGS'] = []
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual((result.inserts, result.updates, result.skipped, result.stopped), (0, 0, 0, False))
        self.assertEqual(result.successes, [])

    def test_field_strings_empty_optional_columns_are_null(self):
        self.service.run(self.missing_selection('FW_FIELD_STRINGS'), self.translator)
        binds = self.state.inserts()[0][1]
        self.assertEqual(binds[3:], [None, None, None])
        self.assertEqual([c['text'] for c in self.azure.calls], ['Cod UMV'])


class RunKeysModeTests(ServiceCase):
    def run_keys(self, name, keys, **kw):
        return self.service.run(self.keys_selection(name, keys), self.translator, **kw)

    def test_update_when_row_exists_insert_otherwise(self):
        self.state.existing = {('FW_STRINGS', (('language', 'de'), ('code', 100000)))}
        result = self.run_keys('FW_STRINGS', '100000, 100001')
        self.assertEqual((result.updates, result.inserts), (1, 1))
        self.assertEqual(self.state.updates(), [(
            "UPDATE FW_STRINGS SET value = :s0, USR = 'JT', DT = sysdate WHERE language = :w0 AND code = :w1",
            {'w0': 'de', 'w1': 100000, 's0': 'T:Ordine UMV'})])
        self.assertEqual(self.state.inserts(), [(
            "INSERT INTO FW_STRINGS VALUES (:1, :2, :3, :4, 'JT', sysdate)", ['de', 100001, 'T:Nuovo testo', None])])
        self.assertEqual([s['action'] for s in result.successes], ['update', 'insert'])
        self.assertEqual(self.conn.commits, 2)

    def test_existence_check_uses_bind_variables(self):
        self.run_keys('FW_STRINGS', '100000')
        checks = [(s, b) for s, b in self.state.log if s.startswith('SELECT COUNT(*) FROM FW_STRINGS WHERE')]
        self.assertEqual(checks, [('SELECT COUNT(*) FROM FW_STRINGS WHERE language = :w0 AND code = :w1',
                                   {'w0': 'de', 'w1': 100000})])

    def test_update_with_apostrophes_stays_in_binds(self):
        self.state.source['FW_STRINGS'] = [('it', 1, "l'ordine & 5%", None, None, None)]
        self.state.existing = {('FW_STRINGS', (('language', 'de'), ('code', 1)))}
        self.run_keys('FW_STRINGS', '1')
        sql, binds = self.state.updates()[0]
        self.assertEqual(binds['s0'], "T:l'ordine & 5%")
        for text in ("l'ordine", '&', '%'):
            self.assertNotIn(text, sql)

    def test_update_without_audit_columns_when_shape_unexpected(self):
        self.state.columns['FW_STRINGS'] = ['A', 'B', 'C']
        self.state.existing = {('FW_STRINGS', (('language', 'de'), ('code', 100000)))}
        self.run_keys('FW_STRINGS', '100000')
        self.assertEqual(self.state.updates()[0][0],
                         'UPDATE FW_STRINGS SET value = :s0 WHERE language = :w0 AND code = :w1')

    def test_update_when_columns_unreadable_updates_text_only(self):
        self.state.fail_sql = ['WHERE 1 = 0']
        self.state.existing = {('FW_STRINGS', (('language', 'de'), ('code', 100000)))}
        result = self.run_keys('FW_STRINGS', '100000')
        self.assertEqual(result.updates, 1)
        self.assertEqual(self.state.updates()[0][0],
                         'UPDATE FW_STRINGS SET value = :s0 WHERE language = :w0 AND code = :w1')

    def test_options_all_codes_of_a_name(self):
        self.state.existing = {('FW_OPZIONI', (('lingua', 'de'), ('tipo', 'ProcessiLunghi'), ('codice', '0')))}
        result = self.run_keys('FW_OPZIONI', 'ProcessiLunghi')
        self.assertEqual((result.updates, result.inserts), (1, 1))
        self.assertEqual(self.state.updates()[0], (
            "UPDATE FW_OPZIONI SET descrizione = :s0, USR = 'JT', DT = sysdate "
            "WHERE lingua = :w0 AND tipo = :w1 AND codice = :w2",
            {'w0': 'de', 'w1': 'ProcessiLunghi', 'w2': '0', 's0': 'T:Si'}))
        self.assertEqual(self.state.inserts()[0][1], ['de', 'ProcessiLunghi', '1', 'T:No', 1, 2])

    def test_field_strings_update(self):
        self.state.existing = {('FW_FIELD_STRINGS', (('language', 'de'), ('code', 10)))}
        self.run_keys('FW_FIELD_STRINGS', '10')
        self.assertEqual(self.state.updates()[0], (
            "UPDATE FW_FIELD_STRINGS SET caption = :s0, description = :s1, tip = :s2, USR = 'JT', DT = sysdate "
            "WHERE language = :w0 AND code = :w1",
            {'w0': 'de', 'w1': 10, 's0': 'T:Cod UMV', 's1': None, 's2': None}))

    def test_docu_nodes_update_uses_db_column_names(self):
        self.state.existing = {('FW_DOCU_NODES_T', (('lang', 'de'), ('nodeid', 100000)))}
        result = self.run_keys('FW_DOCU_NODES_T', '100000')
        self.assertEqual(result.updates, 1)
        self.assertEqual(self.state.updates()[0], (
            'UPDATE FW_DOCU_NODES_T SET NODETITLE = :s0 WHERE LANG = :w0 AND NODEID = :w1',
            {'w0': 'de', 'w1': 100000, 's0': 'T:Risorse UMV'}))

    def test_obj_descrs_update(self):
        self.state.existing = {('FW_OBJ_DESCRS', (('objid', 555), ('tablename', 'MD_ARTI'),
                                                  ('tablefieldname', 'ARTI_DESCR1'), ('language', 'de')))}
        self.run_keys('FW_OBJ_DESCRS', '555')
        self.assertEqual(self.state.updates()[0], (
            'UPDATE FW_OBJ_DESCRS SET description = :s0 WHERE objid = :w0 AND tablename = :w1 '
            'AND tablefieldname = :w2 AND language = :w3',
            {'w0': 555, 'w1': 'MD_ARTI', 'w2': 'ARTI_DESCR1', 'w3': 'de', 's0': 'T:Vite'}))

    def test_fwk_update_sets_three_values(self):
        self.state.existing = {('FWK_STRINGS', (('lang', 'de'), ('pack', 'packA'), ('code', 77)))}
        self.run_keys('FWK_STRINGS', '77')
        self.assertEqual(self.state.updates()[0], (
            'UPDATE FWK_STRINGS SET long_value = :s0, short_value = :s1, value = :s2 '
            'WHERE lang = :w0 AND pack = :w1 AND code = :w2',
            {'w0': 'de', 'w1': 'packA', 'w2': 77, 's0': 'T:Lungo', 's1': 'T:Corto', 's2': 'T:Valore'}))

    def test_missing_target_row_for_every_table_is_inserted(self):
        keys = {'FW_STRINGS': '100000', 'FW_FIELD_STRINGS': '10', 'FW_OPZIONI': 'ProcessiLunghi', 'FW_OPZIONI_DUE': 'Due',
                'FW_OPZIONI_TRE': 'ProcessiLunghi', 'FW_OPZIONI_INT': 'Int', 'FW_DOCU_NODES_T': '100000',
                'FW_OBJ_DESCRS': '555', 'FWK_STRINGS': '77'}
        for name, key in keys.items():
            with self.subTest(table=name):
                self.state.log.clear()
                result = self.run_keys(name, key)
                self.assertEqual(result.updates, 0)
                self.assertGreaterEqual(result.inserts, 1)
                self.assertEqual(self.state.updates(), [])
                self.assertTrue(self.state.inserts()[0][0].startswith((f'INSERT INTO {name} VALUES', f'INSERT INTO {name} (')))

    def test_azure_failure_in_keys_mode_skips_row(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Ordine'))
        result = self.run_keys('FW_STRINGS', '100000 100001')
        self.assertEqual((result.skipped, result.inserts, result.updates), (1, 1, 0))

    def test_update_error_goes_to_errors(self):
        self.state.existing = {('FW_STRINGS', (('language', 'de'), ('code', 100000)))}
        self.state.fail_write = lambda sql, binds: sql.startswith('UPDATE')
        result = self.run_keys('FW_STRINGS', '100000 100001')
        self.assertEqual((len(result.errors), result.inserts, result.updates), (1, 1, 0))
        self.assertEqual(result.errors[0]['code'], 100000)

    def test_stop_in_keys_mode(self):
        result = self.run_keys('FW_STRINGS', '100000 100001', should_stop=lambda: len(self.state.writes()) >= 1)
        self.assertTrue(result.stopped)
        self.assertEqual(result.inserts + result.updates, 1)


class LogTests(JtCase):
    def read(self, path):
        with open(path, newline='', encoding='utf-8-sig') as f:
            return list(csv.DictReader(f))

    def sample(self):
        success = {'date': 'd', 'action': 'insert', 'code': 1, 'lng_in': 'de', 'lng_out': 'fr',
                   'input': 'a, "b"\nc', 'output': 'T:a'}
        error = {'date': 'd', 'code': 2, 'lng_in': 'de', 'lng_out': 'fr', 'input': 'x'}
        return success, error

    def test_both_files_written_into_directory(self):
        success, error = self.sample()
        paths = write_run_logs(RunResult(successes=[success], errors=[error]), self.tmp)
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(os.path.dirname(p) == self.tmp for p in paths))
        self.assertRegex(os.path.basename(paths[0]), r'^JT_inserts_log_\d{14}\.csv$')
        self.assertRegex(os.path.basename(paths[1]), r'^JT_errors_log_\d{14}\.csv$')
        rows = self.read(paths[0])
        self.assertEqual(list(rows[0]), ['date', 'action', 'code', 'lng_in', 'lng_out', 'input', 'output'])
        self.assertEqual(rows[0]['action'], 'insert')
        self.assertEqual(rows[0]['input'], 'a, "b"\nc')
        self.assertEqual(self.read(paths[1])[0]['code'], '2')

    def test_nothing_written_when_empty(self):
        self.assertEqual(write_run_logs(RunResult(), self.tmp), [])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_only_non_empty_lists_are_written(self):
        success, error = self.sample()
        paths = write_run_logs(RunResult(successes=[success]), self.tmp)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(glob.glob(os.path.join(self.tmp, 'JT_errors_log_*.csv'))), 0)
        paths = write_run_logs(RunResult(errors=[error]), self.tmp)
        self.assertRegex(os.path.basename(paths[0]), r'^JT_errors_log_')

    def test_logs_of_a_real_run_have_action_column(self):
        driver = FakeDriver()
        db = Database(driver)
        db.connect('h', '1', 's', 'u', 'p')
        driver.db.missing['FW_STRINGS'] = 2
        service = TranslationService(db)
        selection = service.load_missing(get_table('FW_STRINGS'), 'de', 'fr', 5)
        result = service.run(selection, AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=FakeAzure()))
        (path,) = write_run_logs(result, self.tmp)
        rows = self.read(path)
        self.assertEqual([r['action'] for r in rows], ['insert', 'insert'])
        self.assertEqual([r['code'] for r in rows], ['100000', '100001'])
        self.assertEqual(os.listdir(self.tmp), [os.path.basename(path)])


if __name__ == '__main__':
    unittest.main()


class ReviewFixesTests(ServiceCase):
    """Cose emerse dalla revisione del codice: rollback, righe saltate registrate, chiavi con zeri iniziali, errori di Azure."""

    def test_a_failed_commit_is_rolled_back_and_the_row_goes_to_errors(self):
        self.state.commit_error = True
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual((result.inserts, len(result.errors)), (0, 2))
        self.assertEqual(self.conn.rollbacks, 2)

    def test_a_failed_write_is_rolled_back(self):
        self.state.fail_write = lambda sql, binds: True
        self.service.run(self.missing_selection(), self.translator)
        self.assertEqual(self.conn.rollbacks, 2)

    def test_a_good_row_is_never_rolled_back(self):
        self.service.run(self.missing_selection(), self.translator)
        self.assertEqual(self.conn.rollbacks, 0)

    def test_a_rollback_that_fails_does_not_stop_the_run(self):
        self.state.fail_write = lambda sql, binds: True
        self.conn.rollback = lambda: (_ for _ in ()).throw(RuntimeError('gone'))
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual(len(result.errors), 2)

    def test_skipped_rows_are_recorded_with_the_reason(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Nuovo'))
        result = self.service.run(self.missing_selection(), self.translator)
        self.assertEqual(result.skipped, 1)
        self.assertEqual([(r['code'], r['reason']) for r in result.skipped_rows], [(100001, 'Azure down')])
        self.assertEqual(result.skipped_rows[0]['input'], 'Nuovo testo')

    def test_the_skipped_rows_get_their_own_log(self):
        self.translator = self.make_translator(FakeAzure(fail_on='Nuovo'))
        result = self.service.run(self.missing_selection(), self.translator)
        paths = write_run_logs(result, self.tmp)
        self.assertEqual(len(paths), 2)
        self.assertRegex(os.path.basename(paths[-1]), r'^JT_skipped_log_\d{14}\.csv$')

    def test_a_key_with_leading_zeros_is_found_when_the_row_exists(self):
        selection = self.keys_selection('FW_STRINGS', '000100000, 999')
        self.assertEqual(selection.total, 1)
        self.assertEqual(selection.missing_keys, ['999'])

    def test_the_connection_is_opened_for_use_from_another_thread(self):
        self.assertEqual(self.driver.options, {'threaded': True})


class PreviewAndWriteTests(ServiceCase):
    """Anteprima: tradurre senza scrivere; poi scrivere quelle stesse traduzioni senza richiamare Azure."""

    def key(self, table, code, lang='de'):
        return (table, (('language', lang), ('code', code)))

    def test_preview_writes_nothing_and_translates_each_row_once(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        self.assertEqual(self.state.writes(), [])
        self.assertEqual(self.conn.commits, 0)
        self.assertEqual(len(self.azure.calls), 2)
        self.assertEqual((preview.inserts, preview.updates, preview.skipped, preview.writable), (2, 0, 0, 2))
        self.assertEqual([row.action for row in preview.rows], ['INSERT', 'INSERT'])
        self.assertEqual([row.translated.primary for row in preview.rows], ['T:Ordine UMV', 'T:Nuovo testo'])
        self.assertFalse(preview.stopped)
        self.assertIsNone(preview.failure)

    def test_write_uses_the_preview_and_never_calls_azure_again(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        calls = len(self.azure.calls)
        result = self.service.write(selection, preview)
        self.assertEqual(len(self.azure.calls), calls)
        self.assertEqual((result.inserts, result.updates, result.skipped, result.errors), (2, 0, 0, []))
        self.assertEqual(self.conn.commits, 2)

    def test_preview_then_write_is_the_same_as_translating_directly(self):
        selection = self.missing_selection()
        written = self.service.write(selection, self.service.preview(selection, self.translator))
        via_preview = (self.state.writes(), [(s['action'], s['code'], s['output']) for s in written.successes])
        self.state.log.clear()
        selection = self.missing_selection()
        direct = self.service.run(selection, self.translator)
        self.assertEqual(self.state.writes(), via_preview[0])
        self.assertEqual([(s['action'], s['code'], s['output']) for s in direct.successes], via_preview[1])
        self.assertEqual((direct.inserts, direct.updates), (written.inserts, written.updates))

    def test_by_keys_the_preview_says_update_or_insert_and_shows_the_old_text(self):
        key = self.key('FW_STRINGS', 100000)
        self.state.existing = {key}
        self.state.old_values = {key: {'value': 'Vecchio testo'}}
        selection = self.keys_selection('FW_STRINGS', '100000, 100001')
        preview = self.service.preview(selection, self.translator)
        self.assertEqual({row.base['code']: (row.action, row.old) for row in preview.rows},
                         {100000: ('UPDATE', 'Vecchio testo'), 100001: ('INSERT', '')})
        self.assertEqual(self.state.writes(), [])
        result = self.service.write(selection, preview)
        self.assertEqual((result.updates, result.inserts), (1, 1))

    def test_the_old_text_of_a_triplet_is_the_one_that_matches_the_main_text(self):
        key = self.key('FW_FIELD_STRINGS', 10)
        self.state.existing = {key}
        self.state.old_values = {key: {'caption': 'Vecchia caption', 'description': 'Vecchia descrizione'}}
        preview = self.service.preview(self.keys_selection('FW_FIELD_STRINGS', '10'), self.translator)
        self.assertEqual((preview.rows[0].action, preview.rows[0].old), ('UPDATE', 'Vecchia caption'))

    def test_rows_without_text_and_azure_errors_are_skipped_with_the_reason(self):
        self.state.source['FW_STRINGS'] = [('it', 1, None, None, None, None), ('it', 2, 'ok', None, None, None),
                                           ('it', 3, 'Nuovo', None, None, None)]
        self.translator = self.make_translator(FakeAzure(fail_on='Nuovo'))
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        self.assertEqual([(row.base['code'], row.action, row.reason) for row in preview.rows],
                         [(1, 'SKIP', 'empty source text'), (2, 'INSERT', ''), (3, 'SKIP', 'Azure down')])
        result = self.service.write(selection, preview)
        self.assertEqual((result.inserts, result.skipped), (1, 2))
        self.assertEqual([(e['code'], e['reason']) for e in result.skipped_rows],
                         [(1, 'empty source text'), (3, 'Azure down')])
        self.assertEqual(len(self.state.writes()), 1)

    def test_keys_of_another_level_are_skip_rows_with_the_reason(self):
        self.state.source['FW_STRINGS'].append(('it', 3000001, 'Testo CT', None, None, None))
        spec = get_table('FW_STRINGS')
        selection = self.service.load_keys(spec, 'it', 'de', spec.parse_keys('100000, 3000001'), BY_NAME['CT'])
        preview = self.service.preview(selection, self.translator)
        skipped = [row for row in preview.rows if row.action == 'SKIP']
        self.assertEqual([(row.base['code'], row.base['level'], row.reason) for row in skipped],
                         [(100000, 'Standard', 'key 100000 is level AP, selected level is CT')])
        self.assertEqual(preview.inserts, 1)
        result = self.service.write(selection, preview)
        self.assertEqual(result.skipped_rows[0]['reason'], 'key 100000 is level AP, selected level is CT')
        self.assertEqual([e['code'] for e in result.successes], [3000001])

    def test_the_rows_say_level_and_user_of_the_write(self):
        self.state.source['FW_STRINGS'].append(('it', 3000001, 'Testo CT', None, None, None))
        spec = get_table('FW_STRINGS')
        selection = self.service.load_keys(spec, 'it', 'de', spec.parse_keys('3000001'), None)
        row = self.service.preview(selection, self.translator).rows[0]
        self.assertEqual((row.base['level'], row.base['user']), ('CT', 'ZFXCUSTOM'))

    def test_stop_ends_the_preview_and_keeps_what_was_done(self):
        asked = []
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator, should_stop=lambda: asked.append(1) or len(asked) > 1)
        self.assertTrue(preview.stopped)
        self.assertEqual(len(preview.rows), 1)

    def test_stop_ends_the_write_after_the_current_row(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        asked = []
        result = self.service.write(selection, preview, should_stop=lambda: asked.append(1) or len(asked) > 1)
        self.assertTrue(result.stopped)
        self.assertEqual(len(self.state.writes()), 1)

    def test_progress_of_the_preview_counts_what_would_be_written(self):
        events = []
        self.state.existing = {self.key('FW_STRINGS', 100000)}
        selection = self.keys_selection('FW_STRINGS', '100000, 100001')
        self.service.preview(selection, self.translator, on_progress=events.append)
        self.assertEqual([(p.done, p.total, p.inserts, p.updates, p.errors, p.skipped) for p in events],
                         [(1, 2, 0, 1, 0, 0), (2, 2, 1, 1, 0, 0)])

    def test_progress_of_the_write_counts_what_was_written(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        events = []
        self.service.write(selection, preview, on_progress=events.append)
        self.assertEqual([(p.done, p.total, p.inserts, p.errors) for p in events], [(1, 2, 1, 0), (2, 2, 2, 0)])

    def test_an_unexpected_error_in_the_preview_is_kept_and_the_rows_so_far_too(self):
        self.state.existing = {self.key('FW_STRINGS', 100000)}
        selection = self.keys_selection('FW_STRINGS', '100000, 100001')
        self.state.fail_sql = ['SELECT value FROM']
        preview = self.service.preview(selection, self.translator)
        self.assertIsNotNone(preview.failure)
        self.assertEqual(preview.rows, [])

    def test_a_database_error_while_writing_goes_to_the_errors_and_the_rest_goes_on(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator)
        self.state.fail_write = lambda sql, binds: 'T:Ordine UMV' in binds
        result = self.service.write(selection, preview)
        self.assertEqual((result.inserts, len(result.errors)), (1, 1))
        self.assertEqual(result.errors[0]['code'], 100000)
        self.assertEqual(self.conn.commits, 1)

    def test_an_empty_preview_writes_nothing(self):
        selection = self.missing_selection()
        preview = self.service.preview(selection, self.translator, should_stop=lambda: True)
        result = self.service.write(selection, preview)
        self.assertEqual((result.inserts, result.skipped, self.state.writes()), (0, 0, []))
