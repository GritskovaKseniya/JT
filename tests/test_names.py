"""Cercare nomi nel dizionario (`jt/names.py`, portato da JCTNT) e gli indici di una tabella (`jt/indexes.py`)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from jt import indexes as index_reader, names  # noqa: E402
from jt.tecsql_translator import Dictionary  # noqa: E402


def row(physical, logical, field, logical_field, kind='C', width='10', decimals='0'):
    return {'TABELLA_FISICA': physical, 'CAMPO_FISICO': field, 'TABELLA_LOGICA': logical, 'CAMPO_LOGICO': logical_field,
            'TIPO': kind, 'AMPIEZZA': width, 'DECIMALI': decimals}


ROWS = [
    row('MD_ARTI', 'Articolo', 'ARTI_ARTCO', 'Codice', width='20'),
    row('MD_ARTI', 'Articolo', 'ARTI_DESCR', 'Descrizione', width='50'),
    row('MD_ARTI', 'ArticoloEsteso', 'ARTI_ARTCO', 'Codice', width='20'),
    row('GD_LIRIG', 'RigaListino', 'LIRIG_LICOD', 'CodListino'),
    row('GD_LIRIG', 'RigaListino', 'LIRIG_PREZO', 'Prezzo', 'N', '15', '4'),
    row('GD_LITES', 'TestataListino', 'LITES_LICOD', 'Codice'),
    row('FW_STRINGS', 'FwStrings', 'CODE', 'Code', 'N', '10', '0'),
]


class DictionaryStub:
    """Quello che names.py chiede a un dizionario: le righe."""

    def __init__(self, rows):
        self.rows = rows


def dictionary():
    return DictionaryStub(list(ROWS))


class SimilarityTests(unittest.TestCase):
    def test_levenshtein(self):
        self.assertEqual(names.levenshtein('kitten', 'sitting'), 3)
        self.assertEqual(names.levenshtein('ABC', 'abc'), 0)               # maiuscole ignorate
        self.assertEqual(names.levenshtein('', 'abc'), 3)
        self.assertEqual(names.levenshtein('abc', ''), 3)
        self.assertEqual(names.levenshtein('', ''), 0)
        self.assertEqual(names.levenshtein('md_arti', 'md_arty'), 1)

    def test_similarity(self):
        self.assertEqual(names.similarity('abc', 'abc'), 1.0)
        self.assertEqual(names.similarity('', ''), 1.0)
        self.assertEqual(names.similarity('abc', 'xyz'), 0.0)
        self.assertAlmostEqual(names.similarity('md_arti', 'md_arty'), 6 / 7)

    def test_partial_match_ignores_case_and_spaces(self):
        self.assertTrue(names.partial_match('MD_ARTICOLI', 'rti co'))
        self.assertFalse(names.partial_match('MD_ARTI', 'xyz'))


class ScoreTableTests(unittest.TestCase):
    def test_exact_by_physical_and_by_logical(self):
        m = names.score_table('MD_ARTI', 'Articolo', 'md_arti')
        self.assertEqual((m.score, m.type, m.match), (1000, 'exact', 'fisico'))
        m = names.score_table('MD_ARTI', 'Articolo', ' ARTICOLO ')
        self.assertEqual((m.score, m.type, m.match), (1000, 'exact', 'logico'))

    def test_starts_with_scores_500_to_900(self):
        m = names.score_table('MD_ARTI', 'Articolo', 'md_')
        self.assertEqual((m.type, m.match), ('starts_with', 'fisico'))
        self.assertAlmostEqual(m.score, 500 + 400 * (1 - 4 / 7))
        self.assertEqual(names.score_table('MD_ARTI', 'Articolo', 'artic').match, 'logico')

    def test_contains_scores_200_to_500(self):
        m = names.score_table('MD_ARTI', 'Articolo', 'rti')
        self.assertEqual(m.type, 'contains')
        self.assertTrue(200 <= m.score <= 500)

    def test_a_typo_is_fuzzy_up_to_100(self):
        m = names.score_table('MD_ARTI', 'Articolo', 'md_arty')
        self.assertEqual((m.type, m.match), ('fuzzy', 'fisico'))
        self.assertAlmostEqual(m.score, 100 * 6 / 7)

    def test_nothing_in_common_is_no_match(self):
        self.assertEqual(names.score_table('MD_ARTI', 'Articolo', 'zzzzzz'), names.Match(0, 'no_match'))

    def test_a_missing_logical_name_is_ok(self):
        self.assertEqual(names.score_table('MD_ARTI', None, 'md_arti').type, 'exact')


class TableSearchTests(unittest.TestCase):
    def test_the_summary_has_one_entry_per_descriptor_with_its_fields(self):
        summary = sorted(names.table_summary(dictionary()))
        self.assertIn(('MD_ARTI', 'Articolo', 2), summary)
        self.assertIn(('MD_ARTI', 'ArticoloEsteso', 1), summary)
        self.assertEqual(len(summary), 5)

    def test_the_summary_is_kept(self):
        d = dictionary()
        self.assertIs(names.table_summary(d), names.table_summary(d))

    def test_exact_by_physical_name(self):
        exact, suggestions = names.best_table_matches(dictionary(), 'gd_lirig')
        self.assertEqual([t.physical for t in exact], ['GD_LIRIG'])

    def test_exact_by_logical_name(self):
        exact, _ = names.best_table_matches(dictionary(), 'RigaListino')
        self.assertEqual([(t.physical, t.logical) for t in exact], [('GD_LIRIG', 'RigaListino')])

    def test_a_table_with_two_logical_names_appears_once_with_the_best_one(self):
        exact, suggestions = names.best_table_matches(dictionary(), 'md_arti')
        self.assertEqual(len(exact), 1)
        self.assertEqual(exact[0].physical, 'MD_ARTI')
        self.assertEqual(exact[0].logical, 'Articolo')                  # a parita' vince quello con piu' campi

    def test_without_an_exact_match_there_are_suggestions_best_first(self):
        exact, suggestions = names.best_table_matches(dictionary(), 'lis')
        self.assertEqual(exact, [])
        self.assertTrue(suggestions)
        scores = [s.score for s in suggestions]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(s.score >= names.MIN_SCORE for s in suggestions))
        self.assertEqual({s.physical for s in suggestions}, {'GD_LIRIG', 'GD_LITES'})

    def test_a_typo_still_finds_the_table(self):
        _, suggestions = names.best_table_matches(dictionary(), 'md_arty')
        self.assertEqual(suggestions[0].physical, 'MD_ARTI')
        self.assertEqual(suggestions[0].type, 'fuzzy')

    def test_the_number_of_suggestions_is_limited(self):
        many = DictionaryStub([row(f'TAB_{i:02d}', f'Tab{i}', 'F', 'F') for i in range(30)])
        _, suggestions = names.best_table_matches(many, 'tab', max_results=4)
        self.assertEqual(len(suggestions), 4)
        _, suggestions = names.best_table_matches(many, 'tab')
        self.assertEqual(len(suggestions), 10)

    def test_empty_input_and_empty_dictionary(self):
        self.assertEqual(names.best_table_matches(dictionary(), ''), ([], []))
        self.assertEqual(names.best_table_matches(dictionary(), '   '), ([], []))
        self.assertEqual(names.best_table_matches(DictionaryStub([]), 'x'), ([], []))

    def test_nothing_close_gives_nothing(self):
        self.assertEqual(names.best_table_matches(dictionary(), 'qqqqqqqq'), ([], []))

    def test_rows_of_a_table_found_by_physical_name_include_every_descriptor(self):
        exact, _ = names.best_table_matches(dictionary(), 'MD_ARTI')
        rows = names.table_rows(dictionary(), exact[0])
        self.assertEqual({r['TABELLA_LOGICA'] for r in rows}, {'Articolo', 'ArticoloEsteso'})

    def test_rows_of_a_table_found_by_logical_name_are_that_descriptor_only(self):
        exact, _ = names.best_table_matches(dictionary(), 'ArticoloEsteso')
        rows = names.table_rows(dictionary(), exact[0])
        self.assertEqual({r['TABELLA_LOGICA'] for r in rows}, {'ArticoloEsteso'})

    def test_descriptors_without_a_physical_table_stay_apart(self):
        virtual = DictionaryStub([row('-', 'Uno', 'F', 'F'), row('-', 'Due', 'G', 'G'), row('MD_X', 'Xx', 'H', 'H')])
        exact, _ = names.best_table_matches(virtual, 'due')
        self.assertEqual([(t.physical, t.logical) for t in exact], [('-', 'Due')])
        self.assertEqual([r['CAMPO_FISICO'] for r in names.table_rows(virtual, exact[0])], ['G'])          # solo il suo
        _, suggestions = names.best_table_matches(virtual, 'u')
        self.assertEqual(sorted(s.logical for s in suggestions if s.physical == '-'), ['Due', 'Uno'])   # non si fondono in uno solo

    def test_normalize_table_name(self):
        self.assertEqual(names.normalize_table_name(' md arti '), 'MDARTI')
        self.assertEqual(names.normalize_table_name(None), '')


class FieldSearchTests(unittest.TestCase):
    TABLE = [r for r in ROWS if r['TABELLA_FISICA'] == 'GD_LIRIG']

    def test_empty_means_every_field(self):
        self.assertEqual(names.search_fields(self.TABLE, ''), self.TABLE)
        self.assertEqual(names.search_fields(self.TABLE, '  \n '), self.TABLE)

    def test_physical_or_logical_names_in_any_case_separated_by_comma_space_or_newline(self):
        found = names.search_fields(self.TABLE, 'lirig_licod, prezzo')
        self.assertEqual([r['CAMPO_FISICO'] for r in found], ['LIRIG_LICOD', 'LIRIG_PREZO'])
        found = names.search_fields(self.TABLE, 'Prezzo\nCodListino')
        self.assertEqual([r['CAMPO_FISICO'] for r in found], ['LIRIG_PREZO', 'LIRIG_LICOD'])

    def test_an_unknown_field_becomes_a_not_found_row(self):
        found = names.search_fields(self.TABLE, 'Prezzo, Nope')
        self.assertEqual(len(found), 2)
        missing = found[1]
        self.assertTrue(missing['notFound'])
        self.assertEqual((missing['CAMPO_FISICO'], missing['CAMPO_LOGICO'], missing['TIPO']), ('Nope', 'NOT FOUND', '-'))
        self.assertEqual(missing['TABELLA_FISICA'], 'GD_LIRIG')

    def test_no_rows_no_results(self):
        self.assertEqual(names.search_fields([], 'a'), [])

    def test_field_suggestions(self):
        suggestions = names.best_field_matches(self.TABLE, 'prez')
        self.assertEqual(suggestions[0][0]['CAMPO_FISICO'], 'LIRIG_PREZO')
        self.assertEqual(suggestions[0][2], 'starts_with')
        self.assertEqual(names.best_field_matches(self.TABLE, 'zzzzzzzz'), [])
        self.assertEqual(names.best_field_matches(self.TABLE, ''), [])
        self.assertEqual(names.best_field_matches(self.TABLE, 'Prezzo')[0][2], 'exact')


class ResultsTests(unittest.TestCase):
    def test_numbers_sort_as_numbers_and_dashes_go_last(self):
        values = ['10', '9', '-', '100']
        ordered = sorted(values, key=lambda v: names.sort_key('AMPIEZZA', v))
        self.assertEqual(ordered, ['9', '10', '100', '-'])

    def test_text_sorts_without_case(self):
        ordered = sorted(['b', 'A', 'c'], key=lambda v: names.sort_key('CAMPO_FISICO', v))
        self.assertEqual(ordered, ['A', 'b', 'c'])
        self.assertEqual(names.sort_key('CAMPO_FISICO', None), (0, ''))

    def test_tsv_has_a_header_and_tabs(self):
        text = names.tsv([ROWS[0], {'CAMPO_FISICO': 'X'}])
        lines = text.split('\n')
        self.assertEqual(lines[0], '\t'.join(names.FIELD_COLUMNS))
        self.assertEqual(lines[1], 'MD_ARTI\tARTI_ARTCO\tArticolo\tCodice\tC\t20\t0')
        self.assertEqual(lines[2], '\tX\t\t\t\t\t')
        self.assertTrue(text.endswith('\n'))


def index(table, name, unique='NONUNIQUE', owner='JFLEX', index_owner=None):
    return {'TABLE_OWNER': owner, 'TABLE_NAME': table, 'INDEX_NAME': name, 'UNIQUENESS': unique,
            'INDEX_OWNER': index_owner or owner}


def column(table, index_name, name, position, owner='JFLEX'):
    return {'TABLE_OWNER': owner, 'TABLE_NAME': table, 'INDEX_OWNER': owner, 'INDEX_NAME': index_name, 'COLUMN_NAME': name,
            'COLUMN_POSITION': position}


class IndexRulesTests(unittest.TestCase):
    def test_split_owner_and_name(self):
        self.assertEqual(names.split_owner_and_name('jflex.md_arti'), ('JFLEX', 'MD_ARTI'))
        self.assertEqual(names.split_owner_and_name('MD_ARTI'), ('', 'MD_ARTI'))
        self.assertEqual(names.split_owner_and_name(''), ('', ''))
        self.assertEqual(names.split_owner_and_name('a.b.c'), ('A.B', 'C'))

    def test_matches_table_entry(self):
        entry = index('MD_ARTI', 'IX1')
        self.assertTrue(names.matches_table_entry(entry, 'md_arti'))
        self.assertTrue(names.matches_table_entry(entry, 'JFLEX.MD_ARTI'))
        self.assertFalse(names.matches_table_entry(entry, 'OTHER.MD_ARTI'))
        self.assertFalse(names.matches_table_entry(entry, 'GD_LIRIG'))
        self.assertFalse(names.matches_table_entry(entry, ''))

    def test_index_key_has_the_owner(self):
        self.assertEqual(names.index_key(index('T', 'ix', index_owner='own')), 'OWN.IX')
        self.assertEqual(names.index_key({'INDEX_NAME': 'ix'}), 'IX')

    def test_the_schema_with_more_indexes_wins(self):
        indexes = [index('T', 'A', owner='ONE'), index('T', 'B', owner='TWO'), index('T', 'C', owner='TWO')]
        self.assertEqual(names.pick_index_owner(indexes, []), 'TWO')
        self.assertEqual(names.pick_index_owner([index('T', 'A', owner='ONE')], []), 'ONE')
        self.assertEqual(names.pick_index_owner([], []), '')
        tie = [index('T', 'A', owner='ZED'), index('T', 'B', owner='ABC')]
        self.assertEqual(names.pick_index_owner(tie, []), 'ABC')                  # parita': per nome
        self.assertEqual(names.pick_index_owner(tie, [column('T', 'A', 'X', 1, owner='ZED'), column('T', 'A', 'Y', 2, owner='ZED')]), 'ZED')

    def test_duplicates_are_dropped(self):
        rows = [index('T', 'A'), index('T', 'A'), index('T', 'B')]
        self.assertEqual(len(names.dedupe_indexes(rows)), 2)
        cols = [column('T', 'A', 'X', 1), column('T', 'A', 'X', 1), column('T', 'A', 'Y', 2)]
        self.assertEqual(len(names.dedupe_index_columns(cols)), 2)

    def test_table_indexes_keeps_one_schema_and_its_columns(self):
        indexes = [index('T', 'A', owner='ONE'), index('T', 'B', owner='TWO'), index('T', 'C', owner='TWO'), index('OTHER', 'Z')]
        columns = [column('T', 'A', 'X', 1, owner='ONE'), column('T', 'B', 'Y', 1, owner='TWO'), column('OTHER', 'Z', 'W', 1)]
        kept, kept_columns = names.table_indexes(indexes, columns, 'T')
        self.assertEqual([i['INDEX_NAME'] for i in kept], ['B', 'C'])
        self.assertEqual([c['COLUMN_NAME'] for c in kept_columns], ['Y'])

    def test_the_text_to_copy(self):
        indexes = [index('T', 'IX1', 'UNIQUE'), index('T', 'IX2')]
        columns = [column('T', 'IX1', 'A', 1), column('T', 'IX1', 'B', 2)]
        text = names.indexes_text('T', indexes, columns)
        self.assertTrue(text.startswith('INDEXES OF TABLE: T\n\nINDEX: IX1 (UNIQUE)\nCOLUMNS:\n  1. A\n  2. B\n\n'))
        self.assertIn('INDEX: IX2 (NONUNIQUE)\n\n', text)


class FakeDb:
    def __init__(self):
        self.calls = []

    def fetch_all(self, sql, binds=None):
        self.calls.append((sql, binds))
        if 'all_ind_columns' in sql:
            return [('JFLEX', 'MD_ARTI', 'JFLEX', 'IX1', 'ARTI_ARTCO', 1), ('JFLEX', 'MD_ARTI', 'JFLEX', 'IX1', 'ARTI_DESCR', 2),
                    ('JFLEX', 'MD_ARTI', 'JFLEX', 'IX1', 'ARTI_DESCR', 2), ('JFLEX', 'MD_ARTI', 'JFLEX', 'IX2', None, None)]
        return [('JFLEX', 'MD_ARTI', 'IX1', 'UNIQUE', 'JFLEX'), ('JFLEX', 'MD_ARTI', 'IX2', 'NONUNIQUE', None),
                ('JFLEX', 'MD_ARTI', 'IX1', 'UNIQUE', 'JFLEX')]


class IndexReaderTests(unittest.TestCase):
    def test_only_the_requested_table_is_read_with_a_bind_variable(self):
        db = FakeDb()
        index_reader.read(db, 'md_arti')
        self.assertEqual(len(db.calls), 2)
        for sql, binds in db.calls:
            self.assertTrue(sql.lstrip().upper().startswith('SELECT'))
            self.assertIn('table_name = :t', sql)
            self.assertEqual(binds, {'t': 'MD_ARTI'})

    def test_an_owner_in_the_name_is_not_sent_as_the_table_name(self):
        db = FakeDb()
        index_reader.read(db, 'jflex.md_arti')
        self.assertEqual(db.calls[0][1], {'t': 'MD_ARTI'})

    def test_rows_become_dicts_without_doubles_and_nulls_become_blank(self):
        indexes, columns = index_reader.read(FakeDb(), 'MD_ARTI')
        self.assertEqual([(i['INDEX_NAME'], i['UNIQUENESS']) for i in indexes], [('IX1', 'UNIQUE'), ('IX2', 'NONUNIQUE')])
        self.assertEqual(indexes[1]['INDEX_OWNER'], '')
        self.assertEqual([(c['INDEX_NAME'], c['COLUMN_NAME'], c['COLUMN_POSITION']) for c in columns],
                         [('IX1', 'ARTI_ARTCO', 1), ('IX1', 'ARTI_DESCR', 2), ('IX2', '', '')])

    def test_an_empty_name_reads_nothing(self):
        db = FakeDb()
        self.assertEqual(index_reader.read(db, ''), ([], []))
        self.assertEqual(db.calls, [])

    def test_the_views_the_tool_needs(self):
        self.assertEqual(index_reader.VIEWS, ('ALL_INDEXES', 'ALL_IND_COLUMNS'))


class WithTheRealDictionaryClassTests(unittest.TestCase):
    def test_it_works_on_a_dictionary_object(self):
        d = Dictionary([{'TABELLA_FISICA': 'MD_ARTI', 'CAMPO_FISICO': 'ARTI_ARTCO', 'TABELLA_LOGICA': 'Articolo',
                         'CAMPO_LOGICO': 'Codice'}])
        exact, _ = names.best_table_matches(d, 'articolo')
        self.assertEqual(exact[0].physical, 'MD_ARTI')
        self.assertEqual(len(names.table_rows(d, exact[0])), 1)


if __name__ == '__main__':
    unittest.main()
