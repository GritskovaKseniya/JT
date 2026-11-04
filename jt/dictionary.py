"""Il dizionario dei nomi di Jflex (tabelle e campi logici <-> fisici), letto dal database una volta per connessione.

Lo usano gli strumenti dei nomi (SQL <-> TecSQL, ricerca nomi). Si legge con una `SELECT` su FW_TABLES e FW_TABLE_FIELDS
(circa 36.000 righe) e si tiene in memoria finche' la connessione e' la stessa. `load` ritorna un `Dictionary`
(`tecsql_translator.Dictionary`): ha le mappe, `to_sql`, `to_tecsql` e le righe lette (`rows`).
"""
from .tecsql_translator import Dictionary

TABLES = ('FW_TABLES', 'FW_TABLE_FIELDS')              # le tabelle che il dizionario richiede

FIELDS_SQL = """
    SELECT TAB.TABLEDBNAME, FIE.DBFIELDNAME, TAB.TABLENAME, FIE.TABLEFIELDNAME, FIE.TYPE, FIE.WIDTH, FIE.DECIMALS
    FROM FW_TABLES TAB
    JOIN FW_TABLE_FIELDS FIE ON (FIE.TABLENAME = TAB.TABLENAME)
"""

_cache = {'key': None, 'dictionary': None}


def connection_key(db):
    """Identifica il database collegato (host, porta, SID, utente): con la stessa chiave il dizionario non si rilegge."""
    info = db.info or {}
    return (info.get('host'), info.get('port'), info.get('sid'), info.get('user'))


def read_rows(db):
    """Le righe del dizionario come le vuole `Dictionary.update` (un dict per campo)."""
    rows = []
    for physical_table, physical_field, logical_table, logical_field, kind, width, decimals in db.fetch_all(FIELDS_SQL):
        rows.append({
            'TABELLA_FISICA': physical_table or '',
            'CAMPO_FISICO': physical_field or '',
            'TABELLA_LOGICA': logical_table or '',
            'CAMPO_LOGICO': logical_field or '',
            'TIPO': kind or '',
            'AMPIEZZA': width if width is not None else '',
            'DECIMALI': decimals if decimals is not None else '',
        })
    return rows


def load(db, force=False):
    """Il `Dictionary` del database collegato: lo legge, o riusa quello gia' letto se la connessione e' la stessa."""
    key = connection_key(db)
    if not force and _cache['dictionary'] is not None and _cache['key'] == key:
        return _cache['dictionary']
    dictionary = Dictionary(read_rows(db))
    _cache['key'], _cache['dictionary'] = key, dictionary
    return dictionary


def forget():
    """Dimentica il dizionario (nuova connessione o ricarica forzata)."""
    _cache['key'], _cache['dictionary'] = None, None
