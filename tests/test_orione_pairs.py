"""Il traduttore TecSQL -> SQL di JT contro le coppie che Orione (il vero traduttore) dichiara corrette nei suoi test.

`orione_pairs.json` (79 coppie TecSQL -> SQL Oracle, estratte da TecSqlParserTest.java con `tools\\orione_pairs.py`) e
`orione_dictionary.json` (i descrittori Fw... usati, letti da un Jflex vero) sono i dati. Le coppie dove JT differisce sono
elencate in `orione_known_gaps.json`, ognuna con il motivo: il test e' **esatto** (una coppia nelle lacune deve ancora
differire, una fuori deve combaciare), quindi quando si corregge una lacuna il test dice di toglierla dall'elenco.

Per rigenerare l'elenco delle lacune dopo una correzione:  python tests\\test_orione_pairs.py --regenerate

I tre file di dati NON sono nel repository (e' pubblico: sono casi di test e metadati dell'azienda): si creano in locale con
`tools\\orione_pairs.py pairs` e `tools\\orione_pairs.py dictionary ...` e `--regenerate`. Senza, questi test si saltano.
"""
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

from jt.tecsql_translator import Dictionary, normalize_query_text  # noqa: E402

PAIRS = os.path.join(HERE, 'orione_pairs.json')
DICTIONARY = os.path.join(HERE, 'orione_dictionary.json')
KNOWN_GAPS = os.path.join(HERE, 'orione_known_gaps.json')

REASONS = {
    'descriptor': "descrittore usato solo dai test di Orione (non e' in un dizionario vero)",
    'statement': 'istruzione non supportata (JT traduce solo SELECT: Orione anche UPDATE, INSERT, DELETE, LOCK TABLE)',
    'date': "DATE('gg/mm/aaaa') non diventa TO_DATE('aaaa-mm-gg')",
    'limit': 'LIMIT diventa FETCH FIRST n ROWS ONLY (Orione: AND ROWNUM <= n, che funziona anche su Oracle 11)',
    'alias': "un campo scritto con un alias ($Tab T1 ... T1.Campo) esce con il nome della tabella al posto dell'alias: "
             "SQL non valido in Oracle",
    'order': 'HAVING prima di GROUP BY non viene riordinato (innocuo in Oracle)',
}


def load():
    with open(PAIRS, encoding='utf-8') as f:
        pairs = json.load(f)
    with open(DICTIONARY, encoding='utf-8') as f:
        rows = json.load(f)
    return pairs, Dictionary([{'TABELLA_FISICA': r[0], 'CAMPO_FISICO': r[1], 'TABELLA_LOGICA': r[2], 'CAMPO_LOGICO': r[3],
                               'TIPO': r[4], 'AMPIEZZA': r[5], 'DECIMALI': r[6]} for r in rows])


def normalize(sql):
    """Cio' che per Oracle e' la stessa query: spazi, ASC (e' il predefinito), SELECT ALL, AS davanti a un alias,
    TRIM(BOTH ' ' FROM x) = TRIM(x), `NOT x IN` = `x NOT IN`."""
    sql = re.sub(r'\bAS\b', ' ', sql)
    sql = re.sub(r'\s+', '', sql)
    sql = re.sub(r"TRIM\(BOTH''FROM(.*?)\)", r'TRIM(\1)', sql)
    sql = sql.replace('SELECTALL', 'SELECT').replace('ASC,', ',').replace('ASC)', ')')
    sql = re.sub(r'ASC$', '', sql)
    return re.sub(r'NOT([\w.$]+)IN\(', r'\1NOTIN(', sql)


def pair_id(pair):
    return pair['test'] + '|' + re.sub(r'\s+', ' ', pair['tecsql']).strip()


def translate(dictionary, pair):
    """(SQL, errore): il risultato di JT per la coppia."""
    try:
        return dictionary.to_sql(normalize_query_text(pair['tecsql'])), ''
    except Exception as e:                        # il traduttore dice con un ValueError cosa non va
        return '', str(e)


def matches(dictionary, pair):
    sql, error = translate(dictionary, pair)
    return not error and normalize(sql) == normalize(pair['sql'])


def reason_key(pair, error):
    tecsql = pair['tecsql']
    if 'table not mapped' in error:
        return 'descriptor'
    if re.match(r'\s*(UPDATE|INSERT|DELETE|LOCK)\b', tecsql, re.I):
        return 'statement'
    if re.search(r'\bDATE\s*\(', tecsql, re.I):
        return 'date'
    if re.search(r'\bLIMIT\b', tecsql, re.I):
        return 'limit'
    if re.search(r'\bHAVING\b.*\bGROUP\s+BY\b', tecsql, re.I | re.S):
        return 'order'
    if re.search(r'\$\w+\s+(?!WHERE\b|ORDER\b|GROUP\b|HAVING\b|LEFT\b|RIGHT\b|INNER\b|FULL\b|CROSS\b|OUTER\b|JOIN\b|ON\b|'
                 r'UNION\b|SET\b|LIMIT\b|AS\b)[A-Za-z]\w*', tecsql):
        return 'alias'
    return 'other'


def current_gaps():
    pairs, dictionary = load()
    gaps = {}
    for pair in pairs:
        if not matches(dictionary, pair):
            _, error = translate(dictionary, pair)
            gaps[pair_id(pair)] = reason_key(pair, error)
    return gaps


AVAILABLE = all(os.path.exists(path) for path in (PAIRS, DICTIONARY, KNOWN_GAPS))


@unittest.skipUnless(AVAILABLE, 'dati di Orione non presenti in locale (vedi tools/orione_pairs.py): test saltati')
class OrionePairsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pairs, cls.dictionary = load()
        with open(KNOWN_GAPS, encoding='utf-8') as f:
            cls.known = json.load(f)

    def test_there_are_pairs_and_a_dictionary(self):
        self.assertGreaterEqual(len(self.pairs), 79)
        self.assertGreaterEqual(len(self.dictionary.table_map), 5)

    def test_every_pair_matches_or_is_a_documented_gap(self):
        for pair in self.pairs:
            with self.subTest(test=pair['test'], tecsql=pair['tecsql'][:80]):
                ok = matches(self.dictionary, pair)
                if pair_id(pair) in self.known:
                    self.assertFalse(ok, 'ora combacia: toglila da orione_known_gaps.json (tests\\test_orione_pairs.py --regenerate)')
                else:
                    sql, error = translate(self.dictionary, pair)
                    self.assertTrue(ok, f'JT: {sql or error}\nOrione: {pair["sql"]}')

    def test_every_gap_has_a_known_reason(self):
        self.assertTrue(self.known)
        for key, reason in self.known.items():
            with self.subTest(gap=key[:80]):
                self.assertIn(reason, REASONS)                      # niente "other": ogni lacuna e' spiegata

    def test_the_gap_list_only_names_pairs_that_exist(self):
        ids = {pair_id(p) for p in self.pairs}
        self.assertEqual(set(self.known) - ids, set())

    def test_the_basic_select_family_matches(self):
        simple = [p for p in self.pairs if p['test'] in ('testSimpleSelect', 'testCountAll', 'testDistinct')]
        self.assertTrue(simple)
        mismatched = [p['test'] for p in simple if not matches(self.dictionary, p)]
        self.assertEqual(mismatched, [])


if __name__ == '__main__':
    if '--regenerate' in sys.argv:
        gaps = current_gaps()
        with open(KNOWN_GAPS, 'w', encoding='utf-8') as f:
            json.dump(gaps, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write('\n')
        from collections import Counter
        print(len(gaps), 'gaps written:', dict(Counter(gaps.values())))
    else:
        unittest.main()
