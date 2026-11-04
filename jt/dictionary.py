"""Il dizionario dei nomi di Jflex (tabelle e campi logici <-> fisici), letto dal database una volta per connessione.

Lo usano gli strumenti dei nomi (SQL <-> TecSQL, ricerca nomi). Si legge con una `SELECT` su FW_TABLES e FW_TABLE_FIELDS
(circa 36.000 righe) e si tiene in memoria finche' la connessione e' la stessa; `load` riempie le mappe di
`tecsql_translator` e ritorna le righe (le servono anche gli strumenti di ricerca).
"""
from . import tecsql_translator

TABLES = ('FW_TABLES', 'FW_TABLE_FIELDS')              # le tabelle che il dizionario richiede

FIELDS_SQL = """
    SELECT TAB.TABLEDBNAME, FIE.DBFIELDNAME, TAB.TABLENAME, FIE.TABLEFIELDNAME, FIE.TYPE, FIE.WIDTH, FIE.DECIMALS
    FROM FW_TABLES TAB
    JOIN FW_TABLE_FIELDS FIE ON (FIE.TABLENAME = TAB.TABLENAME)
"""

_cache = {'key': None, 'rows': None}


def connection_key(db):
    """Identifica il database collegato (host, porta, SID, utente): con la stessa chiave il dizionario non si rilegge."""
    info = db.info or {}
    return (info.get('host'), info.get('port'), info.get('sid'), info.get('user'))


def read_rows(db):
    """Le righe del dizionario come le vuole `tecsql_translator.update_mappings` (un dict per campo)."""
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
    """Carica il dizionario del database collegato (o lo riusa se e' lo stesso) e riempie le mappe del traduttore."""
    key = connection_key(db)
    if not force and _cache['rows'] is not None and _cache['key'] == key:
        return _cache['rows']
    rows = read_rows(db)
    tecsql_translator.update_mappings(rows)
    _cache['key'], _cache['rows'] = key, rows
    return rows


def forget():
    """Dimentica il dizionario (nuova connessione o ricarica forzata)."""
    _cache['key'], _cache['rows'] = None, None
    tecsql_translator.update_mappings([])
