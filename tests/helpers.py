"""Supporto condiviso dei test: doppioni di Oracle e Azure, cartelle temporanee, silenziatore di stdout.

Solo libreria standard. Nessuna rete, nessuna credenziale reale, nessun DB reale.
"""
import io
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

for _name in ('requests', 'cx_Oracle'):          # libreria assente: basta uno stub, i test la simulano
    try:
        __import__(_name)
    except ImportError:
        sys.modules[_name] = types.ModuleType(_name)

from jt.config import Paths  # noqa: E402

FAKE_AZURE = {'subscription_key': 'FAKE-KEY', 'endpoint': 'https://azure.invalid', 'location': 'fakeland'}
FAKE_CONNECTION = {'host': 'fake-host', 'port': '1521', 'sid': 'FAKESID', 'username': 'fake_user',
                   'password': 'fake_password'}


def write_json(path, obj):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(obj, f)


def read_json(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def write_text(path, text):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def make_paths(tmp):
    """Copia la cartella Data reale in `tmp` e ne sostituisce le credenziali con valori finti.
    L'ultima scelta salvata (query_data.json) e' sempre la stessa: quella vera dipende da come si e' usata l'app."""
    shutil.copytree(os.path.join(ROOT, 'Data'), os.path.join(tmp, 'Data'))
    paths = Paths(tmp)
    write_json(paths.azure, FAKE_AZURE)
    write_json(paths.connection, FAKE_CONNECTION)
    write_json(paths.query, {'linput': 'Italian', 'loutput': 'German', 'table': 'JFX: Strings'})
    return paths


# ------------------------------------------------------------------ doppioni di test

COLUMNS = {
    'FW_STRINGS': ['LANGUAGE', 'CODE', 'VALUE', 'CATEGORY', 'USR', 'DT'],
    'FW_FIELD_STRINGS': ['LANGUAGE', 'CODE', 'CAPTION', 'DESCRIPTION', 'TIP', 'X', 'USR', 'DT'],
    'FW_OPZIONI': ['LINGUA', 'TIPO', 'CODICE', 'DESCRIZIONE', 'N1', 'N2', 'USR', 'DT'],
    'FW_OPZIONI_DUE': ['LINGUA', 'TIPO', 'CODICE', 'DESCRIZIONE', 'N1', 'N2', 'USR', 'DT'],
    'FW_OPZIONI_TRE': ['LINGUA', 'TIPO', 'CODICE', 'DESCRIZIONE', 'N1', 'N2', 'USR', 'DT'],
    'FW_OPZIONI_INT': ['LINGUA', 'TIPO', 'CODICE', 'DESCRIZIONE', 'N1', 'N2', 'USR', 'DT'],
    'FW_DOCU_NODES_T': ['NODEID', 'LANG', 'NODETITLE'],
    'FW_OBJ_DESCRS': ['OBJID', 'TABLENAME', 'TABLEFIELDNAME', 'LANGUAGE', 'DESCRIPTION'],
    'FWK_STRINGS': ['ID', 'CODE', 'PACK', 'LONG_VALUE', 'SHORT_VALUE', 'X', 'LANG', 'Y', 'USR', 'VALUE'],
}

# righe sorgente per tabella (come le restituirebbe "select *"): i campi vuoti sono None
SOURCE = {
    'FW_STRINGS': [('it', 100000, 'Ordine UMV', None, None, None), ('it', 100001, 'Nuovo testo', None, None, None)],
    'FW_FIELD_STRINGS': [('it', 10, 'Cod UMV', None, None, None, None, None)],
    'FW_OPZIONI': [('it', 'ProcessiLunghi', '0', 'Si', 1, 2, None, None),
                   ('it', 'ProcessiLunghi', '1', 'No', 1, 2, None, None)],
    'FW_OPZIONI_DUE': [('it', 'Due', '0', 'Uno', None, None, None, None)],
    'FW_OPZIONI_TRE': [('it', 'ProcessiLunghi', '0', 'Si', 1, 2, None, None)],
    'FW_OPZIONI_INT': [('it', 'Int', '5', 'Cinque', 5, None, None, None)],
    'FW_DOCU_NODES_T': [(100000, 'it', 'Risorse UMV', None), (100001, 'it', 'Pegging', None)],
    'FW_OBJ_DESCRS': [(555, 'MD_ARTI', 'ARTI_DESCR1', 'it', 'Vite'), (556, 'MD_ARTI', 'ARTI_DESCR1', 'it', None)],
    'FWK_STRINGS': [('ID1', 77, 'packA', 'Lungo', 'Corto', None, 'it', None, 'JT', 'Valore')],
}

# posizione della colonna usata da "Update by keys" nelle righe SOURCE (per filtrare le righe lette)
KEY_POSITION = {'FW_STRINGS': 1, 'FW_FIELD_STRINGS': 1, 'FW_OPZIONI': 1, 'FW_OPZIONI_DUE': 1, 'FW_OPZIONI_TRE': 1,
                'FW_OPZIONI_INT': 1, 'FW_DOCU_NODES_T': 0, 'FW_OBJ_DESCRS': 0, 'FWK_STRINGS': 1}


class FakeDB:
    """Stato condiviso del finto database."""

    def __init__(self):
        self.log = []                 # (sql, binds) di ogni execute
        self.existing = set()         # (tabella, ((colonna_minuscola, valore), ...)) gia' presenti in lingua di output
        self.old_values = {}          # stessa chiave -> {colonna_minuscola: testo di prima}; senza: 'old <colonna>'
        self.missing = {}             # tabella -> conteggio restituito dai COUNT(*) con :li
        self.source = {k: list(v) for k, v in SOURCE.items()}
        self.columns = {k: list(v) for k, v in COLUMNS.items()}
        self.chars = 100              # risultato di SUM(...)
        self.close_error = False      # conn.close() solleva
        self.commit_error = False     # conn.commit() solleva
        self.fail_sql = []            # frammenti di SQL per cui execute solleva
        self.empty_tables = set()     # tabelle esistenti ma senza righe: "SELECT 1 ... ROWNUM" non torna niente
        self.invalid_tables = set()   # tabelle per cui "SELECT 1 ... ROWNUM" solleva
        self.fail_write = None        # callable(sql, binds) -> True se la scrittura deve fallire
        self.fail_connect = False
        self.db_name = 'FAKEDB'       # risposta a SYS_CONTEXT('USERENV', 'DB_NAME'); None = il server non risponde
        self.conns = []

    def writes(self):
        return [(s, b) for s, b in self.log if s.startswith(('UPDATE', 'INSERT'))]

    def inserts(self):
        return [(s, b) for s, b in self.writes() if s.startswith('INSERT')]

    def updates(self):
        return [(s, b) for s, b in self.writes() if s.startswith('UPDATE')]

    def count(self, fragment):
        return sum(1 for s, _ in self.log if fragment in s)


class FakeCursor:
    def __init__(self, db):
        self.db = db
        self.res = []
        self.description = None
        self.closed = False
        self.executed = []

    def execute(self, sql, binds=None, **kwargs):
        if isinstance(binds, (list, tuple)):
            binds = list(binds)
        elif binds is not None:
            binds = dict(binds)
        if 'SYS_CONTEXT' in sql:
            if self.db.db_name is None:
                raise RuntimeError('ORA-00904')
            self.res = [(self.db.db_name,)]
            return
        self.db.log.append((sql, binds))
        self.executed.append(sql)
        s, low = sql.strip(), sql.strip().lower()
        if any(fragment in sql for fragment in self.db.fail_sql):
            raise RuntimeError('simulated DB error')
        if low.startswith(('insert', 'update')):
            if self.db.fail_write and self.db.fail_write(sql, binds):
                raise RuntimeError('simulated write error')
            self.res = []
        elif low.startswith('select * from') and 'where 1 = 0' in low:         # solo nomi colonna
            table = re.search(r'from (\w+) where', s, re.I).group(1)
            self.description = [(c,) for c in self.db.columns.get(table, [])]
            self.res = []
        elif low.startswith('select 1 from') and 'rownum' in low:              # la tabella esiste?
            table = re.search(r'from (\w+) where', s, re.I).group(1)
            if table in self.db.invalid_tables:
                raise RuntimeError('ORA-00942: table or view does not exist')
            self.res = [] if table in self.db.empty_tables else [(1,)]
        elif low.startswith('select count(*) from') and ':li' in low:           # righe mancanti
            table = re.search(r'FROM (\w+) X', s).group(1)
            self.res = [(self.db.missing.get(table, 0),)]
        elif low.startswith('select count(*)') and ':w0' in low:                # esiste gia' in lingua di output?
            table = re.search(r'FROM (\w+) WHERE', s).group(1)
            cols = re.findall(r'(\w+) = :w\d', s)
            key = (table, tuple((c.lower(), binds['w%d' % i]) for i, c in enumerate(cols)))
            self.res = [(1 if key in self.db.existing else 0,)]
        elif low.startswith('select') and ':w0' in low and 'count(*)' not in low:   # valori attuali di una riga (anteprima)
            table = re.search(r'FROM (\w+) WHERE', s).group(1)
            conditions = re.findall(r'(\w+) = :w\d', s)
            key = (table, tuple((c.lower(), binds['w%d' % i]) for i, c in enumerate(conditions)))
            selected = [c.strip() for c in s[len('SELECT '):s.upper().index(' FROM ')].split(',')]
            known = self.db.old_values.get(key, {})
            self.res = [tuple(known.get(c.lower(), f'old {c.lower()}') for c in selected)] if key in self.db.existing else []
        elif low.startswith('select sum('):
            self.res = [(self.db.chars,)]
        elif low.startswith('select *'):
            table = re.search(r'from (\w+) X', s, re.I).group(1)
            rows = list(self.db.source.get(table, []))
            wanted = [str(v) for k, v in (binds or {}).items() if re.fullmatch(r'k\d+', k)]
            if wanted:
                pos = KEY_POSITION[table]
                rows = [r for r in rows if str(r[pos]) in wanted]
            self.res = rows
        else:
            raise AssertionError(f'unexpected SQL in test: {sql}')

    def fetchall(self):
        return self.res

    def fetchone(self):
        return self.res[0]

    def __iter__(self):
        return iter(self.res)

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self, db):
        self.db = db
        self.closed = False
        self.cursors = []
        self.commits = 0
        self.rollbacks = 0
        db.conns.append(self)

    def cursor(self):
        cursor = FakeCursor(self.db)
        self.cursors.append(cursor)
        return cursor

    def commit(self):
        self.commits += 1
        if self.db.commit_error:
            raise RuntimeError('ORA-03113: end-of-file on communication channel')

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        if self.db.close_error:
            raise RuntimeError('close failed')
        self.closed = True


class FakeDriver:
    """Sostituisce il modulo cx_Oracle."""

    def __init__(self, db=None):
        self.db = db or FakeDB()
        self.dsns = []
        self.connects = []

    def makedsn(self, host, port, sid):
        dsn = f'{host}:{port}/{sid}'
        self.dsns.append(dsn)
        return dsn

    def connect(self, user, password, dsn=None, **options):
        self.connects.append((user, password, dsn))
        self.options = options
        if self.db.fail_connect:
            raise RuntimeError('ORA-12541: no listener')
        return FakeConn(self.db)


class FakeAzure:
    """Sostituisce requests.post: risponde 'T:' + testo ricevuto e registra le chiamate."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def __call__(self, url, params=None, headers=None, json=None, timeout=None):
        text = json[0]['text']
        self.calls.append({'url': url, 'params': dict(params), 'headers': dict(headers), 'text': text,
                           'timeout': timeout})
        if self.fail_on and self.fail_on in text:
            raise RuntimeError('Azure down')
        response = MagicMock()
        response.json.return_value = [{'translations': [{'text': 'T:' + text}]}]
        return response


class JtCase(unittest.TestCase):
    """Base: stdout silenziato e cartella temporanea per test (cancellata alla fine)."""

    def setUp(self):
        patcher = patch('sys.stdout', io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = self._tmp.name

    def paths(self):
        return make_paths(self.tmp)
