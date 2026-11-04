"""Simulatore di Oracle per JT: prova il codice vero senza un database vero.

    .venv\Scripts\python.exe tools\simulate.py            esegue gli scenari e dice cosa e' andato bene o male
    .venv\Scripts\python.exe tools\simulate.py --gui      apre la finestra di JT collegata al database simulato
    ... --gui --sample tools\sample_data.json                 con in piu' righe vere (le copia tools\extract_sample.py)

Il "database" e' SQLite in memoria con le tabelle e le righe di `create_test_db.py`, corretto per comportarsi come Oracle
dove conta per JT: LIKE che distingue maiuscole e minuscole, ROWNUM, sysdate, NVL, limiti di lunghezza (ORA-12899) e
colonne obbligatorie (ORA-01400). Il codice di JT (servizio, tabelle, finestra) e' quello vero; solo Azure e' finto
(risponde "[lingua] testo"). Non sostituisce una prova su un Oracle vero: non conosce PL/SQL, byte contro caratteri, ecc.
"""
import argparse
import os
import re
import shutil
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _path in (ROOT, os.path.join(ROOT, 'tools')):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import create_test_db as tool  # noqa: E402
from jt.config import Paths  # noqa: E402
from jt.db import Database  # noqa: E402
from jt.layers import BY_NAME  # noqa: E402
from jt.service import TranslationService  # noqa: E402
from jt.tables import get_table  # noqa: E402

LEVELS = {'All': None, 'Standard': BY_NAME['AP'], 'CW': BY_NAME['CW'], 'CT': BY_NAME['CT']}      # nomi brevi, per i rapporti
PARTS = re.compile(r',\s*(?=[a-z_0-9]+ [A-Z])')


class OracleError(Exception):
    """Errore del database simulato, con il messaggio che darebbe Oracle (ORA-nnnnn)."""


# ------------------------------------------------------------------------- SQL Oracle -> SQLite

def to_sqlite(sql):
    """Riscrive le poche cose di Oracle che JT usa e SQLite non conosce."""
    text = sql.strip()
    if re.fullmatch(r"SELECT SYS_CONTEXT\('USERENV', 'DB_NAME'\) FROM dual", text, re.I):
        return "SELECT 'SIMULATOR'"
    text = re.sub(r'\bsysdate\b', 'CURRENT_TIMESTAMP', text, flags=re.I)
    if text.endswith('WHERE ROWNUM = 1'):
        return text[:-len('WHERE ROWNUM = 1')] + 'LIMIT 1'
    if ' AND ROWNUM <= :n' in text:
        text = text.replace(' AND ROWNUM <= :n', '')
        match = re.match(r'(SELECT .+?) FROM (\w+) X WHERE (.*)$', text, re.S)
        if match and match.group(1) != 'SELECT *':       # COUNT / SUM sulle prime :n righe, come ROWNUM
            return f'{match.group(1)} FROM (SELECT X.* FROM {match.group(2)} X WHERE {match.group(3)} LIMIT :n) X'
        return text + ' LIMIT :n'
    return text


def oracle_message(error, limits):
    """Il messaggio di Oracle che corrisponde a un errore di SQLite."""
    text = str(error)
    match = re.search(r'NOT NULL constraint failed: (\w+)\.(\w+)', text)
    if match:
        return f'ORA-01400: cannot insert NULL into ("{match.group(1).upper()}"."{match.group(2).upper()}")'
    match = re.search(r'CHECK constraint failed: (\w+)', text)
    if match and match.group(1) in limits:
        table, column, size = limits[match.group(1)]
        return f'ORA-12899: value too large for column "{table}"."{column.upper()}" (maximum: {size})'
    return f'ORA-00001: {text}'


class SimCursor:
    def __init__(self, connection):
        self._owner = connection
        self._cursor = connection.raw.cursor()
        self._rows = iter(())

    @property
    def description(self):
        return self._cursor.description

    def execute(self, sql, binds=None):
        try:
            self._cursor.execute(to_sqlite(sql), binds if binds is not None else ())
            if sql.lstrip().upper().startswith('SELECT'):
                # le righe si leggono subito: un commit/rollback di SQLite spezzerebbe il cursore, quello di Oracle no
                self._rows = iter(self._cursor.fetchall())
        except sqlite3.IntegrityError as e:
            raise OracleError(oracle_message(e, self._owner.limits)) from e
        except sqlite3.Error as e:
            raise OracleError(f'ORA-00900: {e}') from e

    def fetchone(self):
        return next(self._rows, None)

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return self._rows

    def close(self):
        self._cursor.close()


class SimConnection:
    def __init__(self, raw, limits):
        self.raw, self.limits = raw, limits

    def cursor(self):
        return SimCursor(self)

    def commit(self):
        self.raw.commit()

    def rollback(self):
        self.raw.rollback()

    def close(self):
        pass                     # il database e' uno solo e vive finche' vive il simulatore


class Simulator:
    """Il database simulato. Si usa al posto di cx_Oracle: `Database(driver=Simulator())`."""

    def __init__(self, sample=None):
        """`sample` = contenuto di un file di extract_sample.py: righe vere in piu' a quelle di prova."""
        self.raw = sqlite3.connect(':memory:', check_same_thread=False)    # il thread di traduzione usa la stessa connessione
        self.raw.execute('PRAGMA case_sensitive_like = ON')                 # come Oracle: 'ctX' non e' 'Ct%'
        self.raw.create_function('NVL', 2, lambda value, other: other if value is None else value)
        self.limits = {}
        cursor = self.raw.cursor()
        for name in tool.SCHEMA:
            cursor.execute(self._ddl(name))
        tool.fill_tables(cursor, tool.with_sample(tool.DATA, sample) if sample else tool.DATA)
        cursor.execute("UPDATE FW_STRINGS SET dt = CURRENT_TIMESTAMP WHERE usr = 'SEED'")
        self.raw.commit()

    def _ddl(self, name):
        """CREATE TABLE per SQLite dallo stesso schema di create_test_db, con i limiti di lunghezza di VARCHAR2(n)."""
        columns, checks = [], []
        for part in PARTS.split(tool.SCHEMA[name]):
            column, definition = part.strip().split(' ', 1)
            kind = definition.split()[0]
            size = re.match(r'(?:VARCHAR2|CHAR)\((\d+)\)', kind)
            sql_type = 'INTEGER' if kind.startswith('NUMBER') else 'TEXT'
            columns.append(f"{column} {sql_type}{' NOT NULL' if 'NOT NULL' in definition else ''}")
            if size:
                constraint = f'chk_{name}_{column}'
                self.limits[constraint] = (name, column, int(size.group(1)))
                checks.append(f'CONSTRAINT {constraint} CHECK (length({column}) <= {size.group(1)})')
        return f"CREATE TABLE {name} ({', '.join(columns + checks)})"

    # --- la parte "driver" (come cx_Oracle)
    def makedsn(self, host, port, sid):
        return f'{host}:{port}/{sid}'

    def connect(self, user, password, dsn=None, threaded=False):
        return SimConnection(self.raw, self.limits)

    # --- per guardare cosa c'e' nel database
    def query(self, sql, binds=()):
        return self.raw.execute(sql, binds).fetchall()


class SimTranslator:
    """Al posto di Azure: '[fr] testo'. Con `fail_on` quel testo non si traduce (come un errore di Azure)."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.calls = []

    def translate(self, text, lan_in, lan_out):
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError('Azure error (simulated)')
        return f'[{lan_out}] {text}'


# ------------------------------------------------------------------------------ scenari

class Check:
    def __init__(self, name, ok, detail=''):
        self.name, self.ok, self.detail = name, bool(ok), detail


class Scenario:
    """Un database simulato nuovo, il servizio vero di JT e un elenco di controlli."""

    def __init__(self, title):
        self.title = title
        self.sim = Simulator()
        self.db = Database(driver=self.sim)
        self.db.connect('sim', '1521', 'SIM', 'simulator', 'x')
        self.service = TranslationService(self.db)
        self.translator = SimTranslator()
        self.checks = []

    def check(self, name, condition, detail=''):
        self.checks.append(Check(name, condition, '' if condition else detail))

    def translate_missing(self, table, level, lan_in='it', lan_out='fr', limit=1000):
        selection = self.service.load_missing(get_table(table), lan_in, lan_out, limit, level)
        return selection, self.service.run(selection, self.translator)

    def translate_keys(self, table, keys, level, lan_in='it', lan_out='de'):
        spec = get_table(table)
        selection = self.service.load_keys(spec, lan_in, lan_out, spec.parse_keys(keys), level)
        return selection, self.service.run(selection, self.translator)

    def written(self, table, lang, lang_col='language'):
        """Righe scritte da JT (utente JT, ZFXCUSTOM o ZFXINTEGR) nella lingua `lang`."""
        return self.sim.query(f"SELECT * FROM {table} WHERE {lang_col} = ? AND usr IN ('JT', 'ZFXCUSTOM', 'ZFXINTEGR')",
                              (lang,))


def _in_range(code, level):
    return level.first <= code <= level.last


def scenario_counts():
    s = Scenario('Conteggi dei mancanti per livello (it -> fr)')
    tables = ['FW_STRINGS', 'FW_FIELD_STRINGS', 'FW_OPZIONI']
    for table in tables:
        counts = {name: s.service.missing_counts([get_table(table)], 'it', 'fr', level)[table]
                  for name, level in LEVELS.items()}
        s.check(f'{table}: ogni livello visibile ha righe da tradurre', all(counts[n] > 0 for n in counts), counts)
        if table != 'FW_OPZIONI':
            s.check(f'{table}: Standard + CW + CT = All', counts['Standard'] + counts['CW'] + counts['CT'] == counts['All'],
                    counts)
    for table in ('FW_DOCU_NODES_T', 'FW_OBJ_DESCRS'):
        counts = {name: s.service.missing_counts([get_table(table)], 'it', 'fr', level)[table]
                  for name, level in LEVELS.items()}
        s.check(f'{table} (senza livelli): il livello non cambia il conteggio', len(set(counts.values())) == 1, counts)
    return s


def scenario_strings():
    s = Scenario('Stringhe: tradurre per livello, utente e categoria')
    source = {row[1]: row for row in s.sim.query("SELECT * FROM FW_STRINGS WHERE language = 'it'")}
    expected = {'CT': ('ZFXCUSTOM', {3000001, 3000002, 3000003}), 'CW': ('ZFXINTEGR', {4000001, 4000002})}
    for name, (user, codes) in expected.items():
        level = BY_NAME[name]
        _, result = s.translate_missing('FW_STRINGS', level)
        rows = {row[1]: row for row in s.written('FW_STRINGS', 'fr')}
        s.check(f'{name}: si scrivono solo le stringhe del livello', set(rows) == codes, sorted(rows))
        s.check(f'{name}: tutte con utente {user}', {row[4] for row in rows.values()} == {user},
                {row[4] for row in rows.values()})
        s.check(f'{name}: la categoria e\' copiata dalla riga italiana',
                all(rows[c][3] == source[c][3] for c in rows), [(c, rows[c][3], source[c][3]) for c in rows])
        s.check(f'{name}: nessun errore', not result.errors and not result.failure, result.errors)
        s.sim.raw.execute("DELETE FROM FW_STRINGS WHERE language = 'fr'")
    _, result = s.translate_missing('FW_STRINGS', BY_NAME['AP'])
    rows = s.written('FW_STRINGS', 'fr')
    s.check('Standard: solo codici 100000-2999999', all(_in_range(r[1], BY_NAME['AP']) for r in rows), [r[1] for r in rows])
    s.check('Standard: utente JT', {r[4] for r in rows} == {'JT'}, {r[4] for r in rows})
    s.check('Standard: il testo vuoto (100011) e\' saltato, non e\' un errore', result.skipped == 1 and not result.errors,
            (result.skipped, result.errors))
    s.check('Standard: le righe di CT e CW non si toccano',
            not s.sim.query("SELECT 1 FROM FW_STRINGS WHERE language = 'fr' AND code >= 3000000"))
    _, again = s.translate_missing('FW_STRINGS', BY_NAME['CT'])
    s.check('CT dopo Standard: ne restano da tradurre (sono un altro livello)', again.inserts == 3, again.inserts)
    _, again = s.translate_missing('FW_STRINGS', BY_NAME['CT'])
    s.check('CT ripetuto: non resta piu\' nulla (niente doppioni)', again.inserts == 0 and not again.errors,
            (again.inserts, again.errors))
    return s


def scenario_all_levels():
    s = Scenario('Tutti i livelli insieme: ogni riga ha l\'utente del suo livello')
    s.translate_missing('FW_STRINGS', None)
    users = {row[1]: row[4] for row in s.written('FW_STRINGS', 'fr')}
    s.check('All: CT -> ZFXCUSTOM', users.get(3000001) == 'ZFXCUSTOM', users.get(3000001))
    s.check('All: CW -> ZFXINTEGR', users.get(4000001) == 'ZFXINTEGR', users.get(4000001))
    s.check('All: Standard -> JT', users.get(100000) == 'JT', users.get(100000))
    return s


def scenario_triplets():
    s = Scenario('Triplette: livello e categoria')
    source = {row[1]: row for row in s.sim.query("SELECT * FROM FW_FIELD_STRINGS WHERE language = 'it'")}
    for name, code, user in (('CT', 3000100, 'ZFXCUSTOM'), ('CW', 4000100, 'ZFXINTEGR')):
        s.translate_missing('FW_FIELD_STRINGS', BY_NAME[name])
        rows = {row[1]: row for row in s.written('FW_FIELD_STRINGS', 'fr')}
        s.check(f'{name}: scritta solo la tripletta del livello', set(rows) == {code}, sorted(rows))
        s.check(f'{name}: utente {user}', rows[code][6] == user, rows[code][6])
        s.check(f'{name}: categoria copiata ({source[code][5]})', rows[code][5] == source[code][5], rows[code][5])
        s.sim.raw.execute("DELETE FROM FW_FIELD_STRINGS WHERE language = 'fr'")
    return s


def scenario_options():
    s = Scenario('Opzioni: livello dal prefisso del nome (Ct, Cw), maiuscole contano')
    for name, expected in (('CT', {'CtStatoCliente'}), ('CW', {'CwStatoIntegrazione'})):
        s.translate_missing('FW_OPZIONI', BY_NAME[name])
        types = {row[1] for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
        s.check(f'{name}: solo le opzioni {name}', types == expected, types)
        s.sim.raw.execute("DELETE FROM FW_OPZIONI WHERE lingua = 'fr'")
    s.translate_missing('FW_OPZIONI', BY_NAME['AP'])
    types = {row[1] for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
    s.check('Standard: niente Ct/Cw e nemmeno ctMinuscolo',
            types == {'ProcessiLunghi', 'StatiOrdine'}, types)
    s.sim.raw.execute("DELETE FROM FW_OPZIONI WHERE lingua = 'fr'")
    s.translate_missing('FW_OPZIONI', None)
    rows = {row[1]: row for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
    s.check('All: ctMinuscolo si traduce (nessun filtro) con utente JT', rows.get('ctMinuscolo', [None] * 7)[6] == 'JT',
            rows.get('ctMinuscolo'))
    s.check('All: CtStatoCliente -> ZFXCUSTOM, CwStatoIntegrazione -> ZFXINTEGR',
            rows['CtStatoCliente'][6] == 'ZFXCUSTOM' and rows['CwStatoIntegrazione'][6] == 'ZFXINTEGR',
            (rows['CtStatoCliente'][6], rows['CwStatoIntegrazione'][6]))
    return s


def scenario_update_by_keys():
    s = Scenario('Update by keys con chiavi di livelli diversi (it -> de, livello CT)')
    selection, result = s.translate_keys('FW_STRINGS', '100000, 3000001, 3000003', BY_NAME['CT'])
    s.check('si caricano solo le due chiavi CT', sorted(r[1] for r in selection.rows) == [3000001, 3000003],
            [r[1] for r in selection.rows])
    s.check('la chiave Standard e\' messa da parte (livello AP)',
            [(r[1], layer.name) for r, layer in selection.other_level] == [(100000, 'AP')], selection.other_level)
    s.check('3000003 esiste gia\' in tedesco: UPDATE; 3000001: INSERT', (result.updates, result.inserts) == (1, 1),
            (result.updates, result.inserts))
    s.check('la chiave saltata e\' nel log con il motivo',
            [e['reason'] for e in result.skipped_rows] == ['key 100000 is level AP, selected level is CT'],
            [e['reason'] for e in result.skipped_rows])
    row = s.sim.query("SELECT value, usr FROM FW_STRINGS WHERE language = 'de' AND code = 3000003")[0]
    s.check('l\'UPDATE scrive il testo nuovo con utente ZFXCUSTOM', row == ('[de] Campo extra del cliente', 'ZFXCUSTOM'), row)
    s.check('la riga Standard in tedesco e\' rimasta com\'era',
            s.sim.query("SELECT value FROM FW_STRINGS WHERE language = 'de' AND code = 100000")[0][0]
            == 'Auftragsverwaltung')
    selection, _ = s.translate_keys('FW_STRINGS', '100000', BY_NAME['CT'])
    s.check('solo chiavi di un altro livello: niente da tradurre', selection.total == 0 and len(selection.other_level) == 1,
            (selection.total, selection.other_level))
    selection, _ = s.translate_keys('FW_STRINGS', '100000, 3000001', None)
    s.check('senza livello (All) non si scarta nulla', selection.total == 2 and not selection.other_level,
            (selection.total, selection.other_level))
    selection, _ = s.translate_keys('FW_OPZIONI', 'ctMinuscolo, CtStatoCliente', BY_NAME['CT'])
    s.check('opzione con prefisso in minuscolo: "livello sconosciuto", non e\' di CT',
            [(r[1], layer) for r, layer in selection.other_level] == [('ctMinuscolo', None)], selection.other_level)
    return s


def scenario_errors():
    s = Scenario('Errori come li darebbe Oracle')
    _, result = s.translate_missing('FW_OBJ_DESCRS', None)
    reasons = [e['reason'] for e in result.errors]
    s.check('descrizione tradotta troppo lunga: ORA-12899 nel log, le altre righe passano',
            len(reasons) == 1 and 'ORA-12899' in reasons[0] and result.inserts >= 3, (reasons, result.inserts))
    s.check('dopo l\'errore il database resta consistente (rollback)',
            s.sim.query("SELECT COUNT(*) FROM FW_OBJ_DESCRS WHERE language = 'fr'")[0][0] == result.inserts)
    s.translator = SimTranslator(fail_on='Spessore')
    _, result = s.translate_missing('FW_OBJ_DESCRS', None, lan_out='en')
    s.check('Azure che non risponde: la riga e\' saltata con il motivo, non e\' un errore del database',
            result.skipped == 1 and 'Azure' in result.skipped_rows[0]['reason'], (result.skipped, result.skipped_rows))
    s.check('... e le altre righe vanno avanti (una e\' la descrizione troppo lunga: ORA-12899)',
            result.inserts == 1 and len(result.errors) == 1, (result.inserts, result.errors))
    return s


SCENARIOS = (scenario_counts, scenario_strings, scenario_all_levels, scenario_triplets, scenario_options,
             scenario_update_by_keys, scenario_errors)


def run_scenarios(out=print):
    """Esegue tutti gli scenari. Ritorna (controlli riusciti, controlli totali)."""
    ok = total = 0
    for build in SCENARIOS:
        scenario = build()
        out(f'\n{scenario.title}')
        for check in scenario.checks:
            total += 1
            ok += check.ok
            out(f"  [{'OK' if check.ok else 'ERRORE'}] {check.name}" + (f'\n          -> {check.detail}' if check.detail else ''))
    return ok, total


# --------------------------------------------------------------------------------- finestra

def run_gui(sample=None):
    """La finestra vera di JT, collegata al database simulato e con un Azure finto. I file di JT dell'utente non si toccano."""
    import tkinter as tk
    from jt.ui.app import JTApp
    from jt.ui.dpi import enable_dpi_awareness
    from jt.jsonstore import write_json

    folder = tempfile.mkdtemp(prefix='jt-simulator-')
    try:
        for name in ('Data', 'Graphics'):
            shutil.copytree(os.path.join(ROOT, name), os.path.join(folder, name))
        paths = Paths(folder)
        write_json(paths.query, {'linput': 'Italian', 'loutput': 'French', 'table': 'JFX: Strings'})
        write_json(paths.connection, {'host': 'simulator', 'port': '1521', 'sid': 'SIM', 'username': 'simulator',
                                      'password': 'x'})
        simulator = Simulator(sample)
        enable_dpi_awareness()
        root = tk.Tk()
        app = JTApp(root, paths, Database(driver=simulator))
        app.make_translator = lambda: SimTranslator()
        root.title(root.title() + '  [SIMULATOR]')
        app.connect({'host': 'simulator', 'port': '1521', 'sid': 'SIM', 'username': 'simulator', 'password': 'x'})
        app.show_translation()
        try:
            root.mainloop()
        finally:
            app.shutdown()
        print('\nRighe scritte da JT durante la prova (lingua, codice, utente):')
        for table, lang, code in (('FW_STRINGS', 'language', 'code'), ('FW_FIELD_STRINGS', 'language', 'code'),
                                  ('FW_OPZIONI', 'lingua', 'tipo')):
            for row in simulator.query(f"SELECT {lang}, {code}, usr FROM {table} "
                                       f"WHERE usr IN ('JT', 'ZFXCUSTOM', 'ZFXINTEGR') ORDER BY 3, 1, 2"):
                print(f'  {table}: {row}')
        print(f'(i log di questa prova erano in {paths.logs}: cancellati con la cartella temporanea)')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gui', action='store_true', help='apre la finestra di JT sul database simulato')
    parser.add_argument('--sample', help='file di extract_sample.py: righe vere in piu' + "'" + ' (solo con --gui)')
    args = parser.parse_args(argv)
    if args.sample and not args.gui:
        parser.error('--sample serve solo con --gui: gli scenari contano le righe di prova')
    if args.gui:
        run_gui(tool.load_sample(args.sample) if args.sample else None)
        return 0
    ok, total = run_scenarios()
    print(f'\n{ok}/{total} controlli riusciti.')
    return 0 if ok == total else 1


if __name__ == '__main__':
    sys.exit(main())
