"""Crea un piccolo database di prova per JT: le tabelle che JT traduce, con qualche riga in italiano da tradurre.

    JT-TestDB.exe                       (nel pacchetto: fa le domande una per una)
    .venv\Scripts\python.exe tools\create_test_db.py [--host H --port P --sid S --admin-user U --recreate]

Serve un database Oracle gia' raggiungibile (JT non puo' creare un server Oracle). Due modi:

1. con un utente amministratore (SYSTEM...): lo strumento crea l'utente di prova JTTEST (password jttest) e le sue tabelle;
2. senza amministratore: ci si collega con l'utente che si vuole usare e le tabelle si creano nel suo schema.

Con `--sample FILE` si aggiungono alle righe di prova quelle vere copiate da un database con `tools\extract_sample.py`.

Sicurezza: non tocca mai tabelle esistenti. Se nello schema c'e' gia' una delle tabelle e non e' un database di prova
creato da questo strumento, si ferma. `--recreate` rifa' solo un database di prova creato da questo strumento.
"""
import argparse
import getpass
import json
import re
import sys
from datetime import datetime

TEST_USER, TEST_PASSWORD = 'JTTEST', 'jttest'
MARKER_TABLE = 'JT_TEST_DB'                    # dice "questo schema l'ho creato io": solo cosi' si puo' ricreare
NAME = re.compile(r'[A-Za-z][A-Za-z0-9_$#]{0,29}$')

# Colonne nell'ordine in cui JT le legge e le scrive (vedi jt/tables.py). I nomi sono nostri (info = CATEGORY, usr = LASTUSER,
# dt = LASTDATE, n1/n2 = ORDINAMENTO/OBJID), le lunghezze sono quelle di un database Jflex vero (letti da un Oracle 2026-11-03):
# lingua di 2 caratteri, value 255, caption 100, descrizione delle opzioni 100, categoria 10, utente 20, codice opzione CHAR(1).
SCHEMA = {
    'FW_STRINGS': 'language VARCHAR2(2) NOT NULL, code NUMBER(10) NOT NULL, value VARCHAR2(255), info VARCHAR2(10), '
                  'usr VARCHAR2(20), dt DATE',
    'FW_FIELD_STRINGS': 'language VARCHAR2(2) NOT NULL, code NUMBER(10) NOT NULL, caption VARCHAR2(100), '
                        'description VARCHAR2(255), tip VARCHAR2(255), info VARCHAR2(10), usr VARCHAR2(20), dt DATE',
    'FW_OPZIONI': 'lingua VARCHAR2(2) NOT NULL, tipo VARCHAR2(30) NOT NULL, codice CHAR(1) NOT NULL, '
                  'descrizione VARCHAR2(100), n1 VARCHAR2(30), n2 VARCHAR2(30), usr VARCHAR2(20), dt DATE',
    'FW_DOCU_NODES_T': 'nodeid NUMBER(10) NOT NULL, lang CHAR(2) NOT NULL, nodetitle VARCHAR2(255)',   # 3 colonne, come nel DB vero
    'FW_OBJ_DESCRS': 'objid NUMBER(10) NOT NULL, tablename VARCHAR2(30) NOT NULL, tablefieldname VARCHAR2(30) NOT NULL, '
                     'language VARCHAR2(2) NOT NULL, description VARCHAR2(100)',
}
# le varianti delle opzioni differiscono solo per il codice: CHAR(1), VARCHAR2(2), VARCHAR2(3), NUMBER(5) (letto da un Oracle vero)
for _name, _code in (('FW_OPZIONI_DUE', 'VARCHAR2(2)'), ('FW_OPZIONI_TRE', 'VARCHAR2(3)'), ('FW_OPZIONI_INT', 'NUMBER(5)')):
    SCHEMA[_name] = SCHEMA['FW_OPZIONI'].replace('codice CHAR(1)', f'codice {_code}')


def _long_text():
    """Entra nei 100 caratteri della colonna (l'originale italiano), ma tradotta li supera: ORA-12899 nel log degli errori."""
    return "Questa descrizione e' molto lunga: tradotta supera i cento caratteri e finisce nel log degli errori."


def _data():
    """{tabella: [righe]} nell'ordine delle colonne. 'SEED' nella colonna utente = riga gia' tradotta in partenza."""
    it_strings = [
        (100000, 'Gestione ordini', 'Auftragsverwaltung', 'Order management'),
        (100001, 'Utenti e Menù', 'Benutzer und Menüs', 'Users and Menu'),
        (100002, 'Applicazioni e Contenitori', None, 'Applications and Containers'),
        (100003, 'Ordine UMV confermato', None, 'Order confirmed'),
        (100004, 'Supply Chain Planning', None, 'Supply Chain Planning'),
        (100005, "L'ordine e' stato confermato dall'operatore", None, "The order was confirmed by the operator"),
        (100006, 'Copia i campi dalla tabella', None, None),
        (100007, 'Nessun risultato trovato', None, None),
        (100008, 'Stampa etichette', None, None),
        (100009, 'Imballo con 5 UMV per pallet', None, None),
        (100010, '   ', None, None),                        # solo spazi: JT non la manda ad Azure
        (100011, None, None, None),                         # testo vuoto: JT la salta
    ]
    strings = []
    for code, it, de, en in it_strings:
        strings.append(('it', code, it, None, None, None))
        if de:
            strings.append(('de', code, de, None, 'SEED', None))
        if en:
            strings.append(('en', code, en, None, 'SEED', None))
    # Livelli (campo Level): CT = codici 3000000-3999999, CW = 4000000-4999999, il resto e' Standard.
    # La colonna "info" e' la categoria (il modulo): la traduzione la deve copiare dalla riga sorgente.
    strings += [('it', 100100, 'Gestione del magazzino', 'WMS', None, None),
                ('it', 3000001, 'Etichetta personalizzata per il cliente', 'MES', None, None),
                ('it', 3000002, 'Report di produzione personalizzato', None, None, None),
                ('it', 3000003, 'Campo extra del cliente', ' ', None, None),        # un blank = "nessuna categoria"
                ('de', 3000003, 'Zusatzfeld des Kunden', ' ', 'SEED', None),
                ('it', 4000001, "Integrazione con l'ERP del cliente", 'MCS', None, None),
                ('it', 4000002, 'Invio degli ordini al magazzino esterno', None, None, None)]
    fields = [
        (200000, 'Codice articolo', 'Codice univoco dell\'articolo', 'Scrivi il codice e premi Invio'),
        (200001, 'Quantita\'', 'Quantita\' da produrre', 'Numero intero maggiore di zero'),
        (200002, 'Data consegna', None, 'Formato gg/mm/aaaa'),
        (200003, 'Fornitore', 'Fornitore abituale dell\'articolo', None),
        (200004, 'UMV', 'Unita\' di movimentazione', 'Esempio: pallet, scatola'),
    ]
    field_rows = []
    for code, caption, description, tip in fields:
        field_rows.append(('it', code, caption, description, tip, None, None, None))
    field_rows.append(('en', 200000, 'Item code', 'Unique code of the item', 'Type the code and press Enter', None, 'SEED', None))
    field_rows += [('it', 3000100, 'Campo personalizzato', 'Descrizione del campo personalizzato', None, 'MES', None, None),
                   ('it', 4000100, 'Codice integrazione', None, "Codice usato dall'integrazione", 'MCS', None, None)]
    options = {
        'FW_OPZIONI': [('ProcessiLunghi', 1, 'Lavorazione standard'), ('ProcessiLunghi', 2, 'Lavorazione prolungata'),
                       ('ProcessiLunghi', 3, 'Lavorazione speciale'), ('StatiOrdine', 1, 'Aperto'),
                       ('StatiOrdine', 2, 'In lavorazione'), ('StatiOrdine', 3, 'Chiuso'),
                       ('CtStatoCliente', 1, 'Stato del cliente'),               # livello CT (prefisso Ct)
                       ('CwStatoIntegrazione', 1, 'Integrato'),                  # livello CW (prefisso Cw)
                       ('ctMinuscolo', 1, 'Prefisso scritto in minuscolo')],     # ne' CT ne' Standard: JT lo salta
        'FW_OPZIONI_DUE': [('TipiControllo', 1, 'Controllo visivo'), ('TipiControllo', 2, 'Controllo dimensionale')],
        'FW_OPZIONI_TRE': [('MotiviScarto', 1, 'Difetto di materiale'), ('MotiviScarto', 2, 'Errore operatore')],
        'FW_OPZIONI_INT': [('Priorita', 1, 'Alta'), ('Priorita', 2, 'Normale')],
    }
    data = {'FW_STRINGS': strings, 'FW_FIELD_STRINGS': field_rows}
    for table, items in options.items():
        rows = [('it', tipo, codice, text, None, None, None, None) for tipo, codice, text in items]
        rows.append(('en', items[0][0], items[0][1], {'Lavorazione standard': 'Standard processing',
                                                       'Controllo visivo': 'Visual check',
                                                       'Difetto di materiale': 'Material defect',
                                                       'Alta': 'High'}[items[0][2]], None, None, 'SEED', None))
        data[table] = rows
    data['FW_DOCU_NODES_T'] = [(1, 'it', 'Come si inserisce un ordine'), (2, 'it', 'Come si stampa un\'etichetta'),
                               (3, 'it', 'Come si cambia la lingua'), (4, 'it', 'Supply Chain Planning: panoramica'),
                               (1, 'en', 'How to enter an order')]
    data['FW_OBJ_DESCRS'] = [(1, 'QL_CARAT', 'CARAT_DESCR', 'it', 'Colore'), (2, 'QL_CARAT', 'CARAT_DESCR', 'it', 'Spessore'),
                             (3, 'QL_CARAT', 'CARAT_DESCR', 'it', 'Materiale'),
                             (4, 'QL_CARAT', 'CARAT_DESCR', 'it', _long_text()),
                             (1, 'QL_CARAT', 'CARAT_DESCR', 'en', 'Colour')]
    return data


DATA = _data()

# posizioni delle colonne che identificano una riga (lingua e codice...): per non duplicare le righe di prova con quelle vere
KEY_POSITIONS = {'FW_STRINGS': (0, 1), 'FW_FIELD_STRINGS': (0, 1), 'FW_OPZIONI': (0, 1, 2), 'FW_OPZIONI_DUE': (0, 1, 2),
                 'FW_OPZIONI_TRE': (0, 1, 2), 'FW_OPZIONI_INT': (0, 1, 2), 'FW_DOCU_NODES_T': (0, 1),
                 'FW_OBJ_DESCRS': (0, 1, 2, 3)}


def load_sample(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def with_sample(data, sample):
    """Le righe di prova piu' quelle copiate da un database vero (stesso ordine di colonne). Una riga vera che ha la stessa
    chiave di una di prova si salta; una tabella con un numero diverso di colonne non si mescola."""
    merged = {name: list(rows) for name, rows in data.items()}
    for table, entry in sample.get('tables', {}).items():
        if table not in SCHEMA or len(entry['columns']) != len(_columns(table)):
            continue
        positions = KEY_POSITIONS[table]
        seen = {tuple(row[i] for i in positions) for row in merged.get(table, [])}
        dates = [i for i, kind in enumerate(entry.get('types', [])) if kind == 'DATE']
        for raw in entry['rows']:
            row = list(raw)
            for i in dates:
                if isinstance(row[i], str):
                    row[i] = datetime.fromisoformat(row[i])
            key = tuple(row[i] for i in positions)
            if key not in seen:
                seen.add(key)
                merged.setdefault(table, []).append(tuple(row))
    return merged


def check_name(name):
    if not NAME.match(name or ''):
        raise ValueError(f'Invalid name: {name!r}')
    return name.upper()


def placeholders(count):
    return ', '.join(f':{i}' for i in range(1, count + 1))


def create_tables(cursor, tables=SCHEMA):
    for name, columns in tables.items():
        cursor.execute(f'CREATE TABLE {name} ({columns})')
    cursor.execute(f'CREATE TABLE {MARKER_TABLE} (created DATE)')
    cursor.execute(f'INSERT INTO {MARKER_TABLE} VALUES (sysdate)')


def fill_tables(cursor, data=DATA):
    counts = {}
    for name, rows in data.items():
        cursor.executemany(f'INSERT INTO {name} VALUES ({placeholders(len(_columns(name)))})', rows)
        counts[name] = len(rows)
    return counts


def _columns(name):
    """Nomi delle colonne di una tabella dello schema (la definizione e' 'nome TIPO, nome TIPO(n)...')."""
    return [part.strip().split()[0] for part in re.split(r',\s*(?=[a-z_0-9]+ [A-Z])', SCHEMA[name])]


def existing_tables(cursor):
    cursor.execute('SELECT table_name FROM user_tables')
    return {row[0].upper() for row in cursor.fetchall()}


def populate(connection, recreate=False, data=None):
    """Crea tabelle e dati nello schema dell'utente collegato. Ritorna {tabella: righe}. Non tocca mai altro."""
    cursor = connection.cursor()
    present = existing_tables(cursor)
    ours = MARKER_TABLE in present
    clash = sorted(present & (set(SCHEMA) | {MARKER_TABLE}))
    if clash and not ours:
        raise RuntimeError('This schema already has tables used by JT (' + ', '.join(clash) + ') and it is not a JT test '
                           'database: nothing was changed. Use another user.')
    if ours:
        if not recreate:
            raise RuntimeError('A JT test database already exists in this schema. Use --recreate to rebuild it.')
        for name in sorted(present & (set(SCHEMA) | {MARKER_TABLE})):
            cursor.execute(f'DROP TABLE {name} PURGE')
    create_tables(cursor)
    counts = fill_tables(cursor, data or DATA)
    for name in ('FW_STRINGS', 'FW_FIELD_STRINGS', 'FW_OPZIONI', 'FW_OPZIONI_DUE', 'FW_OPZIONI_TRE', 'FW_OPZIONI_INT'):
        cursor.execute(f"UPDATE {name} SET dt = sysdate WHERE usr = 'SEED'")
    connection.commit()
    return counts


def create_user(admin_connection):
    """Con un amministratore: crea l'utente di prova (se non c'e' gia'). Ritorna True se l'ha creato."""
    cursor = admin_connection.cursor()
    cursor.execute('SELECT COUNT(*) FROM all_users WHERE username = :1', [TEST_USER])
    if cursor.fetchone()[0]:
        return False
    cursor.execute(f'CREATE USER {TEST_USER} IDENTIFIED BY {TEST_PASSWORD}')
    cursor.execute(f'GRANT CREATE SESSION, CREATE TABLE, UNLIMITED TABLESPACE TO {TEST_USER}')
    return True


def connect(driver, user, password, host, port, sid):
    return driver.connect(user, password, dsn=driver.makedsn(host, port, sid))


def run(driver, host, port, sid, user, password, admin=False, recreate=False, out=print, data=None):
    """Con admin=True l'utente indicato e' un amministratore: si crea JTTEST e si lavora li'."""
    check_name(user)
    if admin:
        connection = connect(driver, user, password, host, port, sid)
        try:
            created = create_user(connection)
        finally:
            connection.close()
        out(f"User {TEST_USER} {'created' if created else 'already exists'}.")
        user, password = TEST_USER, TEST_PASSWORD
    connection = connect(driver, user, password, host, port, sid)
    try:
        counts = populate(connection, recreate, data)
    finally:
        connection.close()
    for table, rows in counts.items():
        out(f'  {table}: {rows} rows')
    return user, password


def ask(text, default=None, secret=False):
    shown = f' [{default}]' if default else ''
    reader = getpass.getpass if secret else input
    answer = reader(f'{text}{shown}: ').strip()
    return answer or default or ''


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host')
    parser.add_argument('--port')
    parser.add_argument('--sid')
    parser.add_argument('--user', help="utente con cui collegarsi (se non c'e' --admin-user: quello che avra' le tabelle)")
    parser.add_argument('--admin-user', help='utente amministratore: crea JTTEST e le tabelle')
    parser.add_argument('--password')
    parser.add_argument('--recreate', action='store_true')
    parser.add_argument('--sample', help='file di tools\\extract_sample.py: aggiunge alle righe di prova quelle vere')
    args = parser.parse_args(argv)
    print('JT - test database\n')
    print('Needs a reachable Oracle database. Nothing existing is ever modified.\n')
    host = args.host or ask('Host name')
    port = args.port or ask('Port', '1521')
    sid = args.sid or ask('SID', 'ORCL')
    admin = args.admin_user or (None if args.user else ask('Admin user (empty = create the tables with the user below)'))
    user = admin or args.user or ask('User for the tables')
    password = args.password or ask(f'Password of {user}', secret=True)
    import cx_Oracle
    try:
        data = with_sample(DATA, load_sample(args.sample)) if args.sample else None
        user, password = run(cx_Oracle, host, port, sid, user, password, admin=bool(admin), recreate=args.recreate,
                             data=data)
    except Exception as e:
        print(f'\nFailed: {e}')
        input('\nPress Enter to close...')
        return 1
    print(f'\nDone. Open JT and connect to:\n  Host {host}  Port {port}  SID {sid}\n  User {user}  Password {password}')
    input('\nPress Enter to close...')
    return 0


if __name__ == '__main__':
    sys.exit(main())
