"""Il dizionario dei nomi COMPLETO di un database FW vero (tutte le tabelle e i campi), per provare gli strumenti dei nomi nel
simulatore con i dati veri: `tools\\simulate.py --gui --fw`.

    .venv\\Scripts\\python.exe tools\\simulate.py --gui --fw --fw-connect HOST:PORT/SID --fw-user USER     la prima volta (o per rileggerlo)
    .venv\\Scripts\\python.exe tools\\simulate.py --gui --fw                                                 le volte dopo: dal file

Legge solo con SELECT e salva tutto in `tools\\fw_dictionary.json` (e' in .gitignore: sono dati dell'azienda, non vanno su
GitHub). La password si chiede (oppure JT_SAMPLE_PASSWORD) e non si salva da nessuna parte.
"""
import getpass
import json
import os
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, 'tools', 'fw_dictionary.json')

# le colonne che JT legge, nell'ordine dello schema di prova (vedi create_test_db.py)
SELECTS = {
    'FW_TABLES': 'SELECT tablename, tabledbname FROM FW_TABLES ORDER BY tablename',
    'FW_TABLE_FIELDS': ('SELECT tablename, tablefieldname, dbfieldname, type, width, decimals, dbposition FROM FW_TABLE_FIELDS '
                        'ORDER BY tablename, tablefieldname'),
}
# gli indici (viste di Oracle) delle tabelle fisiche del dizionario: per lo strumento Indexes. Se non si leggono si salta.
OPTIONAL_SELECTS = {
    'ALL_INDEXES': ("SELECT table_owner, table_name, index_name, uniqueness, owner FROM all_indexes WHERE table_name IN "
                    "(SELECT tabledbname FROM FW_TABLES WHERE tabledbname <> '-') ORDER BY table_owner, table_name, index_name"),
    'ALL_IND_COLUMNS': ("SELECT table_owner, table_name, index_owner, index_name, column_name, column_position FROM all_ind_columns "
                        "WHERE table_name IN (SELECT tabledbname FROM FW_TABLES WHERE tabledbname <> '-') "
                        "ORDER BY table_owner, table_name, index_name, column_position"),
}


def clean(value):
    """Un valore in una forma che sta in JSON; i vuoti restano vuoti (le CHAR di Oracle hanno spazi in fondo)."""
    return value.rstrip() if isinstance(value, str) else value


def fetch(connection, out=print):
    """{'tables': {nome: {'columns': [...], 'types': [...], 'rows': [[...]]}}} letto con SELECT dal database FW collegato."""
    cursor = connection.cursor()
    tables = {}
    for optional, selects in ((False, SELECTS), (True, OPTIONAL_SELECTS)):
        for name, sql in selects.items():
            assert sql.lstrip().upper().startswith('SELECT')             # solo lettura
            try:
                cursor.execute(sql)
                columns = [d[0] for d in cursor.description]
                rows = [[clean(v) for v in row] for row in cursor.fetchall()]
            except Exception as e:
                if not optional:
                    raise
                out(f'  {name}: skipped ({e})')                         # senza gli indici si prova tutto il resto
                continue
            tables[name] = {'columns': columns, 'types': [''] * len(columns), 'rows': rows}
            out(f'  {name}: {len(rows):,} rows')
    return {'tables': tables}


def connect(spec, user, password=None):
    """Una connessione Oracle in lettura. `spec` = HOST:PORT/SID."""
    import cx_Oracle
    host_port, _, sid = spec.partition('/')
    host, _, port = host_port.partition(':')
    if not (host and sid):
        raise ValueError('use HOST:PORT/SID, for example myserver:1521/ORCL')
    password = password or os.environ.get('JT_SAMPLE_PASSWORD') or getpass.getpass(f'Password of {user}: ')
    return cx_Oracle.connect(user, password, dsn=cx_Oracle.makedsn(host, port or '1521', sid=sid))


def save(data, source, path=None):
    path = path or CACHE
    data = {**data, 'source': source, 'taken': datetime.now().strftime('%Y-%m-%d')}
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)
    return path


def load(path=None):
    """Il dizionario salvato; solleva FileNotFoundError con come crearlo se non c'e'."""
    path = path or CACHE
    if not os.path.exists(path):
        raise FileNotFoundError('No saved FW dictionary. Create it once with: simulate.py --gui --fw '
                                '--fw-connect HOST:PORT/SID --fw-user USER')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def merge(sample, dictionary):
    """Il campione (righe vere di Strings...) piu' il dizionario completo: quello del dizionario vince per FW_TABLES e
    FW_TABLE_FIELDS."""
    tables = dict((sample or {}).get('tables', {}))
    tables.update(dictionary['tables'])
    return {**(sample or {}), 'tables': tables}
