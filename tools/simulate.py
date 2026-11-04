"""Simulatore di Oracle per JT: prova il codice vero senza un database vero.

    .venv\Scripts\python.exe tools\simulate.py            esegue gli scenari e dice cosa e' andato bene o male
    .venv\Scripts\python.exe tools\simulate.py --gui      apre la finestra di JT collegata al database simulato
    ... --gui --sample tools\sample_data.json                 con in piu' righe vere (le copia tools\extract_sample.py)
    ... --gui --azure                                         con il vero Azure (la chiave di Data\azure_services.json)

Il "database" e' SQLite in memoria con le tabelle e le righe di `create_test_db.py`, corretto per comportarsi come Oracle
dove conta per JT: LIKE che distingue maiuscole e minuscole, ROWNUM, sysdate, NVL, limiti di lunghezza (ORA-12899) e
colonne obbligatorie (ORA-01400). Il codice di JT (servizio, tabelle, finestra) e' quello vero; solo Azure e' finto: negli
scenari risponde "[lingua] testo"; nella finestra (--gui) le stringhe di prova hanno una traduzione vera in en, fr, de, es e hi
(le altre restano "[lingua] testo"); con --azure si usa il vero Azure (costa pochi caratteri) e il database resta simulato:
niente di reale viene scritto. Non sostituisce una prova su un Oracle vero: non conosce PL/SQL, byte contro caratteri, ecc.
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
from jt.tecsql_translator import normalize_query_text  # noqa: E402
from jt.undo import build_script  # noqa: E402

LEVELS = {'All': None, 'Standard': BY_NAME['AP'], 'CW': BY_NAME['CW'], 'CT': BY_NAME['CT'],
          'CC': BY_NAME['CC']}      # nomi brevi, per i rapporti
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
    text = re.sub(r"TO_DATE\('([^']*)', 'YYYY-MM-DD HH24:MI:SS'\)", r"'\1'", text)      # le date sono testo nel simulatore
    if text.endswith('WHERE ROWNUM = 1'):
        return text[:-len('WHERE ROWNUM = 1')] + 'LIMIT 1'
    if ' AND ROWNUM <= :n' in text:
        text = text.replace(' AND ROWNUM <= :n', '')
        match = re.match(r'(SELECT .+?) FROM (\w+) X WHERE (.*)$', text, re.S)
        if match and match.group(1) != 'SELECT *':       # COUNT / SUM sulle prime :n righe, come ROWNUM
            return f'{match.group(1)} FROM (SELECT X.* FROM {match.group(2)} X WHERE {match.group(3)} LIMIT :n) X'
        return text + ' LIMIT :n'
    return text


def _unistr(text):
    """UNISTR di Oracle: le sequenze \\XXXX sono unita' UTF-16."""
    def decode(match):
        return bytes.fromhex(match.group().replace('\\', '')).decode('utf-16-be')
    return re.sub(r'(?:\\[0-9A-Fa-f]{4})+', decode, text)


def statements(script):
    """Le istruzioni SQL di uno script, senza i commenti e senza i comandi di SQL Developer (SET ..., COMMIT)."""
    found, current, quoted, i = [], [], False, 0
    while i < len(script):
        if not quoted and script.startswith('--', i):            # un commento arriva fino a fine riga
            end = script.find('\n', i)
            i = len(script) if end < 0 else end
            continue
        ch = script[i]
        if ch == "'":
            quoted = not quoted                                 # '' dentro un testo si chiude e si riapre: va bene
        if ch == ';' and not quoted:
            found.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    found.append(''.join(current).strip())
    return [text for text in found if text and not text.upper().startswith(('SET ', 'COMMIT'))]


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
        self.raw.create_function('UNISTR', 1, _unistr)
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

    def run_script(self, script):
        """Esegue uno script SQL (come farebbe SQL Developer con F5): un'istruzione alla volta, poi COMMIT."""
        cursor = self.connect('script', '').cursor()
        for text in statements(script):
            cursor.execute(text)
        self.raw.commit()


# Traduzioni delle stringhe italiane del database di prova (create_test_db.py), per vedere nella finestra come appare un
# testo tradotto. "Supply Chain Planning" resta uguale e UMV diventa HU: lo fa il glossario di JT con il vero Azure.
TRANSLATIONS = {
    'Gestione ordini': {'en': 'Order management', 'fr': 'Gestion des commandes', 'de': 'Auftragsverwaltung',
                        'es': 'Gestión de pedidos', 'hi': 'ऑर्डर प्रबंधन'},
    'Utenti e Menù': {'en': 'Users and Menu', 'fr': 'Utilisateurs et menu', 'de': 'Benutzer und Menüs',
                      'es': 'Usuarios y menú', 'hi': 'उपयोगकर्ता और मेनू'},
    'Applicazioni e Contenitori': {'en': 'Applications and Containers', 'fr': 'Applications et conteneurs',
                                   'de': 'Anwendungen und Container', 'es': 'Aplicaciones y contenedores',
                                   'hi': 'एप्लिकेशन और कंटेनर'},
    'Ordine UMV confermato': {'en': 'HU order confirmed', 'fr': 'Commande HU confirmée', 'de': 'HU-Auftrag bestätigt',
                              'es': 'Pedido HU confirmado', 'hi': 'HU ऑर्डर की पुष्टि हो गई'},
    'Supply Chain Planning': {code: 'Supply Chain Planning' for code in ('en', 'fr', 'de', 'es', 'hi')},
    "L'ordine e' stato confermato dall'operatore": {
        'en': 'The order was confirmed by the operator', 'fr': "La commande a été confirmée par l'opérateur",
        'de': 'Der Auftrag wurde vom Bediener bestätigt', 'es': 'El pedido fue confirmado por el operador',
        'hi': 'ऑपरेटर द्वारा ऑर्डर की पुष्टि की गई'},
    'Copia i campi dalla tabella': {'en': 'Copy the fields from the table', 'fr': 'Copier les champs de la table',
                                    'de': 'Felder aus der Tabelle kopieren', 'es': 'Copiar los campos de la tabla',
                                    'hi': 'तालिका से फ़ील्ड कॉपी करें'},
    'Nessun risultato trovato': {'en': 'No results found', 'fr': 'Aucun résultat trouvé',
                                 'de': 'Keine Ergebnisse gefunden', 'es': 'No se encontraron resultados',
                                 'hi': 'कोई परिणाम नहीं मिला'},
    'Stampa etichette': {'en': 'Print labels', 'fr': 'Imprimer les étiquettes', 'de': 'Etiketten drucken',
                         'es': 'Imprimir etiquetas', 'hi': 'लेबल प्रिंट करें'},
    'Imballo con 5 UMV per pallet': {'en': 'Packaging with 5 HU per pallet', 'fr': 'Emballage avec 5 HU par palette',
                                     'de': 'Verpackung mit 5 HU pro Palette', 'es': 'Embalaje con 5 HU por palé',
                                     'hi': 'प्रति पैलेट 5 HU के साथ पैकेजिंग'},
    'Gestione del magazzino': {'en': 'Warehouse management', 'fr': "Gestion de l'entrepôt", 'de': 'Lagerverwaltung',
                               'es': 'Gestión del almacén', 'hi': 'गोदाम प्रबंधन'},
    'Etichetta personalizzata per il cliente': {
        'en': 'Custom label for the customer', 'fr': 'Étiquette personnalisée pour le client',
        'de': 'Kundenspezifisches Etikett', 'es': 'Etiqueta personalizada para el cliente',
        'hi': 'ग्राहक के लिए अनुकूलित लेबल'},
    'Report di produzione personalizzato': {
        'en': 'Custom production report', 'fr': 'Rapport de production personnalisé',
        'de': 'Kundenspezifischer Produktionsbericht', 'es': 'Informe de producción personalizado',
        'hi': 'अनुकूलित उत्पादन रिपोर्ट'},
    'Campo extra del cliente': {'en': 'Customer extra field', 'fr': 'Champ supplémentaire du client',
                                'de': 'Zusatzfeld des Kunden', 'es': 'Campo adicional del cliente',
                                'hi': 'ग्राहक का अतिरिक्त फ़ील्ड'},
    "Integrazione con l'ERP del cliente": {
        'en': "Integration with the customer's ERP", 'fr': "Intégration avec l'ERP du client",
        'de': 'Integration mit dem ERP des Kunden', 'es': 'Integración con el ERP del cliente',
        'hi': 'ग्राहक के ERP के साथ एकीकरण'},
    'Invio degli ordini al magazzino esterno': {
        'en': 'Sending orders to the external warehouse', 'fr': "Envoi des commandes à l'entrepôt externe",
        'de': 'Versand der Aufträge an das externe Lager', 'es': 'Envío de pedidos al almacén externo',
        'hi': 'बाहरी गोदाम को ऑर्डर भेजना'},
}


class SimTranslator:
    """Al posto di Azure: '[fr] testo'. Con `fail_on` quel testo non si traduce (come un errore di Azure).
    Con `realistic=True` i testi del database di prova (TRANSLATIONS) hanno una traduzione vera; gli altri restano '[fr] testo'."""

    def __init__(self, fail_on=None, realistic=False):
        self.fail_on = fail_on
        self.realistic = realistic
        self.calls = []

    def translate(self, text, lan_in, lan_out):
        self.calls.append(text)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError('Azure error (simulated)')
        if self.realistic and lan_out in TRANSLATIONS.get(text, {}):
            return TRANSLATIONS[text][lan_out]
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
        """Righe scritte da JT (utente JT, ZFXCUSTOM, ZFXINTEGR o ZFXCCSYS) nella lingua `lang`."""
        return self.sim.query(f"SELECT * FROM {table} WHERE {lang_col} = ? AND usr IN ('JT', 'ZFXCUSTOM', 'ZFXINTEGR', 'ZFXCCSYS')",
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
            s.check(f'{table}: Standard + CW + CT + CC = All',
                    counts['Standard'] + counts['CW'] + counts['CT'] + counts['CC'] == counts['All'],
                    counts)
    for table in ('FW_DOCU_NODES_T', 'FW_OBJ_DESCRS'):
        counts = {name: s.service.missing_counts([get_table(table)], 'it', 'fr', level)[table]
                  for name, level in LEVELS.items()}
        s.check(f'{table} (senza livelli): il livello non cambia il conteggio', len(set(counts.values())) == 1, counts)
    return s


def scenario_strings():
    s = Scenario('Stringhe: tradurre per livello, utente e categoria')
    source = {row[1]: row for row in s.sim.query("SELECT * FROM FW_STRINGS WHERE language = 'it'")}
    expected = {'CT': ('ZFXCUSTOM', {3000001, 3000002, 3000003}), 'CW': ('ZFXINTEGR', {4000001, 4000002}),
                'CC': ('ZFXCCSYS', {9000001, 9000002})}
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
    s.check('Standard: le righe di CT, CW e CC non si toccano',
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
    s.check('All: CC -> ZFXCCSYS', users.get(9000001) == 'ZFXCCSYS', users.get(9000001))
    s.check('All: Standard -> JT', users.get(100000) == 'JT', users.get(100000))
    return s


def scenario_triplets():
    s = Scenario('Triplette: livello e categoria')
    source = {row[1]: row for row in s.sim.query("SELECT * FROM FW_FIELD_STRINGS WHERE language = 'it'")}
    for name, code, user in (('CT', 3000100, 'ZFXCUSTOM'), ('CW', 4000100, 'ZFXINTEGR'),
                              ('CC', 9000100, 'ZFXCCSYS')):
        s.translate_missing('FW_FIELD_STRINGS', BY_NAME[name])
        rows = {row[1]: row for row in s.written('FW_FIELD_STRINGS', 'fr')}
        s.check(f'{name}: scritta solo la tripletta del livello', set(rows) == {code}, sorted(rows))
        s.check(f'{name}: utente {user}', rows[code][6] == user, rows[code][6])
        s.check(f'{name}: categoria copiata ({source[code][5]})', rows[code][5] == source[code][5], rows[code][5])
        s.sim.raw.execute("DELETE FROM FW_FIELD_STRINGS WHERE language = 'fr'")
    return s


def scenario_options():
    s = Scenario('Opzioni: livello dal prefisso del nome (Ct, Cw, Cc), maiuscole contano')
    for name, expected in (('CT', {'CtStatoCliente'}), ('CW', {'CwStatoIntegrazione'}),
                           ('CC', {'CcStatoDescrittore'})):
        s.translate_missing('FW_OPZIONI', BY_NAME[name])
        types = {row[1] for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
        s.check(f'{name}: solo le opzioni {name}', types == expected, types)
        s.sim.raw.execute("DELETE FROM FW_OPZIONI WHERE lingua = 'fr'")
    s.translate_missing('FW_OPZIONI', BY_NAME['AP'])
    types = {row[1] for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
    s.check('Standard: niente Ct/Cw/Cc e nemmeno ctMinuscolo',
            types == {'ProcessiLunghi', 'StatiOrdine'}, types)
    s.sim.raw.execute("DELETE FROM FW_OPZIONI WHERE lingua = 'fr'")
    s.translate_missing('FW_OPZIONI', None)
    rows = {row[1]: row for row in s.written('FW_OPZIONI', 'fr', 'lingua')}
    s.check('All: ctMinuscolo si traduce (nessun filtro) con utente JT', rows.get('ctMinuscolo', [None] * 7)[6] == 'JT',
            rows.get('ctMinuscolo'))
    s.check('All: CtStatoCliente -> ZFXCUSTOM, CwStatoIntegrazione -> ZFXINTEGR, CcStatoDescrittore -> ZFXCCSYS',
            rows['CtStatoCliente'][6] == 'ZFXCUSTOM' and rows['CwStatoIntegrazione'][6] == 'ZFXINTEGR'
            and rows['CcStatoDescrittore'][6] == 'ZFXCCSYS',
            (rows['CtStatoCliente'][6], rows['CwStatoIntegrazione'][6], rows['CcStatoDescrittore'][6]))
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


def _strings(scenario, lang):
    """Le stringhe di una lingua senza la data (che cambia a ogni corsa)."""
    return scenario.sim.query("SELECT language, code, value, info, usr FROM FW_STRINGS WHERE language = ? ORDER BY code",
                              (lang,))


def scenario_preview():
    s = Scenario('Anteprima: tradurre senza scrivere, poi scrivere le stesse traduzioni')
    everything = 'SELECT COUNT(*), SUM(code), MAX(dt) FROM FW_STRINGS'
    before = s.sim.query(everything)
    selection = s.service.load_missing(get_table('FW_STRINGS'), 'it', 'fr', 1000, BY_NAME['CT'])
    preview = s.service.preview(selection, s.translator)
    s.check("l'anteprima non scrive niente nel database", s.sim.query(everything) == before, s.sim.query(everything))
    counts = (preview.inserts, preview.updates, preview.skipped)
    s.check("l'anteprima ha una riga INSERT per ogni stringa CT", counts == (3, 0, 0), counts)
    calls = len(s.translator.calls)
    result = s.service.write(selection, preview)
    s.check('write non richiama Azure (si paga una volta sola)', len(s.translator.calls) == calls,
            (calls, len(s.translator.calls)))
    s.check("write scrive le righe dell'anteprima, senza errori", (result.inserts, result.errors) == (3, []),
            (result.inserts, result.errors))
    direct = Scenario('direct')
    direct.translate_missing('FW_STRINGS', BY_NAME['CT'])
    s.check("il database dopo anteprima + write e' uguale a quello della traduzione diretta",
            _strings(s, 'fr') == _strings(direct, 'fr'), (_strings(s, 'fr'), _strings(direct, 'fr')))

    u = Scenario('anteprima di un UPDATE')
    spec = get_table('FW_STRINGS')
    selection = u.service.load_keys(spec, 'it', 'de', spec.parse_keys('3000003, 3000001'), BY_NAME['CT'])
    preview = u.service.preview(selection, u.translator)
    rows = {row.base['code']: (row.action, row.old) for row in preview.rows}
    u.check("per chiavi: la riga gia' tradotta e' UPDATE e mostra il testo di prima",
            rows == {3000003: ('UPDATE', 'Zusatzfeld des Kunden'), 3000001: ('INSERT', '')}, rows)
    german = "SELECT value FROM FW_STRINGS WHERE language = 'de' AND code = 3000003"
    u.check("il testo di prima e' ancora nel database fino a Write", u.sim.query(german)[0][0] == 'Zusatzfeld des Kunden')
    u.service.write(selection, preview)
    u.check("dopo Write il testo e' quello nuovo", u.sim.query(german)[0][0] == '[de] Campo extra del cliente')
    s.checks += u.checks

    limits = Scenario('limite delle colonne')
    selection = limits.service.load_missing(get_table('FW_OBJ_DESCRS'), 'it', 'fr', 100, None)
    preview = limits.service.preview(selection, limits.translator)
    result = limits.service.write(selection, preview)
    s.check("un testo tradotto piu' lungo della colonna si vede solo scrivendo: ORA-12899 nel log "
            "(l'anteprima non conosce ancora i limiti)",
            preview.skipped == 0 and len(result.errors) == 1 and 'ORA-12899' in result.errors[0]['reason'],
            (preview.skipped, result.errors))
    return s


def scenario_undo():
    s = Scenario('Annullare con lo script di annullamento: il database torna com\'era')
    tables = ('FW_STRINGS', 'FW_FIELD_STRINGS', 'FW_OPZIONI')

    def snapshot():
        return {table: s.sim.query(f'SELECT * FROM {table} ORDER BY 1, 2, 3') for table in tables}

    s.translator = SimTranslator(realistic=True)
    s.translate_missing('FW_STRINGS', BY_NAME['AP'], lan_out='hi')       # righe in hindi, con accenti e apostrofi
    before = snapshot()
    plain = SimTranslator()
    s.translator = plain
    spec = get_table('FW_STRINGS')
    runs = []
    selection = s.service.load_keys(spec, 'it', 'hi', spec.parse_keys('100001, 100005'), None)
    runs.append(s.service.run(selection, plain))                          # UPDATE: il testo di prima e' in hindi
    runs.append(s.translate_missing('FW_STRINGS', BY_NAME['CT'], lan_out='hi')[1])
    runs.append(s.translate_missing('FW_FIELD_STRINGS', None, lan_out='hi')[1])
    runs.append(s.translate_missing('FW_OPZIONI', None, lan_out='hi')[1])
    records = [record for run in runs for record in run.undo]
    s.check('la corsa ha aggiornato righe e ne ha inserite in tre tabelle',
            sum(r.action == 'update' for r in records) == 2 and {r.table for r in records} == set(tables),
            [(r.table, r.action) for r in records][:6])
    changed = snapshot()
    s.check('dopo la corsa il database e\' diverso', changed != before)
    script = build_script(records, 'SIM', 'simulator')
    s.check('lo script e\' solo ASCII (accenti e hindi con UNISTR) e ha SET DEFINE OFF e COMMIT',
            script.isascii() and 'UNISTR(' in script and 'SET DEFINE OFF;' in script and script.rstrip().endswith('COMMIT;'))
    s.sim.run_script(script)
    after = snapshot()
    s.check('eseguito lo script, il database e\' uguale a prima (righe inserite tolte, testi, utente e data rimessi)',
            after == before, {t: (len(before[t]), len(after[t])) for t in tables})
    s.check('lo script rieseguito non rompe niente (le righe non ci sono piu\')',
            s.sim.run_script(script) is None and snapshot() == before)
    return s


def scenario_names():
    """Il dizionario dei nomi letto dal database simulato (FW_TABLES e FW_TABLE_FIELDS) e la traduzione SQL <-> TecSQL."""
    from jt import dictionary
    from jt.tecsql_translator import Dictionary
    s = Scenario('Nomi: dizionario letto dal database e traduzione SQL <-> TecSQL')
    dictionary.forget()
    try:
        expected = s.sim.query('SELECT COUNT(*) FROM FW_TABLES TAB JOIN FW_TABLE_FIELDS FIE ON (FIE.TABLENAME = TAB.TABLENAME)')[0][0]
        d = dictionary.load(s.db)
        s.check('il dizionario ha una riga per ogni campo', len(d.rows) == expected and expected > 0, (len(d.rows), expected))
        s.check('le mappe sono piene', d.table_map.get('$rigalistino') == 'GD_LIRIG', d.table_map.get('$rigalistino'))
        s.check('con la stessa connessione non si rilegge', dictionary.load(s.db) is d)

        sql = d.to_sql("SELECT $RigaListino.Prezzo FROM $RigaListino WHERE $RigaListino.CatListino = 'LL'")
        s.check('TecSQL -> SQL: nomi logici diventano fisici',
                'GD_LIRIG.LIRIG_PREZO' in sql and "GD_LIRIG.LIRIG_CATLI = 'LL'" in sql, sql)

        result = d.to_tecsql('SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        s.check('SQL -> TecSQL: nomi fisici diventano logici',
                result['success'] and '$RigaListino.CodListino' in result['tecsql'], result)

        ambiguous = d.to_tecsql('SELECT ARTI_ARTCO FROM MD_ARTI')
        s.check('SQL -> TecSQL: MD_ARTI ha due nomi logici, il traduttore chiede quale',
                ambiguous.get('ambiguous') and len(ambiguous.get('candidates', [])) == 2, ambiguous)
        chosen = d.to_tecsql('SELECT ARTI_ARTCO FROM MD_ARTI', '$articoloesteso')
        s.check('scelto il descrittore, la traduzione riesce', chosen['success'] and '$ArticoloEsteso' in chosen['tecsql'],
                chosen)

        s.check('un dizionario vuoto: errore chiaro (non un risultato vuoto)',
                _raises(lambda: Dictionary().to_sql('SELECT $A.B FROM $A')), 'nessun errore')
    finally:
        dictionary.forget()
    return s


def _raises(call):
    try:
        call()
    except ValueError:
        return True
    return False


SCENARIOS = (scenario_counts, scenario_strings, scenario_all_levels, scenario_triplets, scenario_options,
             scenario_update_by_keys, scenario_errors, scenario_preview, scenario_undo, scenario_names)


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

def real_azure_available(credentials_path):
    """True se nel file della chiave c'e' una chiave vera (non il segnaposto del modello)."""
    from jt.jsonstore import read_json
    try:
        key = str(read_json(credentials_path).get('subscription_key', ''))
    except (OSError, ValueError, AttributeError):
        return False
    return bool(key) and not key.upper().startswith('INSERISCI')


def demo_tools():
    """Gli strumenti veri (Strings, SQL <> TecSQL) e uno finto spento (richiede una tabella che non c'e'): per vedere come
    appare uno strumento che non puo' funzionare su questo database."""
    import tkinter as tk
    from tkinter import ttk
    from jt.tools import Tool
    from jt.ui.app import default_tools

    def demo(parent, app):
        frame = ttk.Frame(parent)
        tk.Label(frame, text='Demo tool (it is always off here).', pady=40).pack()
        return frame

    return default_tools() + [Tool('names', 'Names', demo, requires=('FW_TABLES_MISSING',))]


def run_gui(sample=None, azure=False, nokey=False, demo=True):
    """La finestra vera di JT, collegata al database simulato. Azure e' finto (traduzioni di prova) oppure, con `azure`,
    quello vero: il database resta simulato e i file di JT dell'utente non si toccano."""
    import tkinter as tk
    from jt.ui.app import JTApp
    from jt.ui.dpi import enable_dpi_awareness
    from jt.jsonstore import write_json

    folder = tempfile.mkdtemp(prefix='jt-simulator-')
    try:
        for name in ('Data', 'Graphics'):
            shutil.copytree(os.path.join(ROOT, name), os.path.join(folder, name))
        paths = Paths(folder)
        if nokey:                  # come nello zip senza chiave: il modello al posto della chiave
            write_json(paths.azure, {'subscription_key': 'INSERISCI-QUI-LA-CHIAVE-AZURE',
                                     'endpoint': 'https://api.cognitive.microsofttranslator.com', 'location': 'italynorth'})
        write_json(paths.query, {'linput': 'Italian', 'loutput': 'French', 'table': 'JFX: Strings'})
        write_json(paths.connection, {'host': 'simulator', 'port': '1521', 'sid': 'SIM', 'username': 'simulator',
                                      'password': 'x'})
        simulator = Simulator(sample)
        enable_dpi_awareness()
        root = tk.Tk()
        app = JTApp(root, paths, Database(driver=simulator), tools=demo_tools() if demo else None)
        if azure and not real_azure_available(paths.azure):
            print('Data\\azure_services.json non ha una chiave vera: si usano le traduzioni di prova.')
            azure = False
        if not azure:
            app.make_translator = lambda: SimTranslator(realistic=True)
        root.title(root.title() + ('  [SIMULATOR - no key]' if nokey else '  [SIMULATOR - real Azure]' if azure else '  [SIMULATOR]'))
        app.connect({'host': 'simulator', 'port': '1521', 'sid': 'SIM', 'username': 'simulator', 'password': 'x',
                     'environment': 'test'})            # test: conferma normale; per provare la conferma forte: New connection > prod
        app.show_translation()
        try:
            root.mainloop()
        finally:
            app.shutdown()
        print('\nRighe scritte da JT durante la prova (lingua, codice, utente):')
        for table, lang, code in (('FW_STRINGS', 'language', 'code'), ('FW_FIELD_STRINGS', 'language', 'code'),
                                  ('FW_OPZIONI', 'lingua', 'tipo')):
            for row in simulator.query(f"SELECT {lang}, {code}, usr FROM {table} "
                                       f"WHERE usr IN ('JT', 'ZFXCUSTOM', 'ZFXINTEGR', 'ZFXCCSYS') ORDER BY 3, 1, 2"):
                print(f'  {table}: {row}')
        print(f'(i log di questa prova erano in {paths.logs}: cancellati con la cartella temporanea)')
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--gui', action='store_true', help='apre la finestra di JT sul database simulato')
    parser.add_argument('--sample', help="file di extract_sample.py: righe vere in piu' (solo con --gui)")
    parser.add_argument('--azure', action='store_true',
                        help='con il vero Azure (la chiave di Data\\azure_services.json; costa pochi caratteri; solo con --gui)')
    parser.add_argument('--nokey', action='store_true',
                        help='senza chiave Azure (il modello del pacchetto): per vedere JT come lo vede chi non la ha ricevuta; solo con --gui')
    parser.add_argument('--fw', action='store_true',
                        help="il dizionario dei nomi COMPLETO di un database FW vero (da tools\\fw_dictionary.json, vedi tools\\fw_dictionary.py): "
                             "per provare SQL <> TecSQL con i dati veri")
    parser.add_argument('--fw-connect', metavar='HOST:PORT/SID',
                        help='con --fw: legge il dizionario da questo database FW (solo SELECT) e lo salva; la password si chiede')
    parser.add_argument('--fw-user', help='con --fw-connect: l\'utente del database FW')
    parser.add_argument('--translate', metavar='QUERY',
                        help='senza finestra: traduce questa query (con $ e\' TecSQL, senza e\' SQL) e la stampa; usa --fw per il dizionario vero')
    parser.add_argument('--descriptor', help='con --translate: il descrittore da usare se la tabella ne ha piu\' di uno (es. $Articolo)')
    parser.add_argument('--one-tool', action='store_true',
                        help='senza gli strumenti di prova: JT come e\' oggi, con il solo Strings (solo con --gui)')
    args = parser.parse_args(argv)
    gui_only = (args.sample or args.azure or args.nokey or args.one_tool)
    if gui_only and not args.gui:
        parser.error('--sample, --azure, --nokey e --one-tool servono solo con --gui: gli scenari contano le righe di prova e non spendono')
    if (args.fw_connect or args.fw_user) and not args.fw:
        parser.error('--fw-connect e --fw-user servono con --fw')
    if args.descriptor and not args.translate:
        parser.error('--descriptor serve con --translate')
    sample = tool.load_sample(args.sample) if args.sample else None
    if args.fw:
        sample = _with_fw_dictionary(parser, args, sample)
    if args.translate:
        return translate_command(args.translate, args.descriptor, sample)
    if args.gui:
        run_gui(sample, args.azure, args.nokey, not args.one_tool)
        return 0
    if args.fw:
        parser.error('--fw serve con --gui o con --translate')
    ok, total = run_scenarios()
    print(f'\n{ok}/{total} controlli riusciti.')
    return 0 if ok == total else 1


def _with_fw_dictionary(parser, args, sample):
    """Il campione piu' il dizionario completo di un database FW vero: letto ora (--fw-connect) o dal file salvato."""
    import fw_dictionary
    try:
        if args.fw_connect:
            if not args.fw_user:
                parser.error('--fw-connect vuole anche --fw-user')
            print(f'Reading the dictionary from {args.fw_connect} (SELECT only)...')
            connection = fw_dictionary.connect(args.fw_connect, args.fw_user)
            try:
                data = fw_dictionary.fetch(connection)
            finally:
                connection.close()
            print('Saved', fw_dictionary.save(data, args.fw_connect), '(not for GitHub: it is in .gitignore)')
        else:
            data = fw_dictionary.load()
    except (FileNotFoundError, ValueError) as e:
        parser.error(str(e))
    return fw_dictionary.merge(sample, data)


def translate_command(query, descriptor, sample):
    """Senza finestra: traduce una query con il dizionario del simulatore (quello di prova o, con --fw, quello vero)."""
    from jt import dictionary
    simulator = Simulator(sample)
    db = Database(driver=simulator)
    db.connect('sim', '1521', 'SIM', 'simulator', 'x')
    dictionary.forget()
    d = dictionary.load(db)
    print(f'Dictionary: {len(d.rows):,} fields in {len(d.table_map):,} tables', file=sys.stderr)
    text = normalize_query_text(query)
    if '$' in text:
        try:
            print(d.to_sql(text))
            return 0
        except ValueError as e:
            print(f'ERROR: {e}', file=sys.stderr)
            return 1
    result = d.to_tecsql(text, descriptor)
    if result.get('ambiguous'):
        print(f"AMBIGUOUS: {result['table']} has several logical names: {', '.join(result['candidates'])} (use --descriptor)",
              file=sys.stderr)
        return 2
    if not result.get('success'):
        print(f"ERROR: {result.get('error')}", file=sys.stderr)
        return 1
    print(result['tecsql'])
    if result.get('partial_translation'):
        print(f"WARNING: translated in part, not found: {', '.join(result.get('untranslated_fields') or [])}", file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
