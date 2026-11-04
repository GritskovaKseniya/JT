"""Gli indici di una tabella, letti dal database (le viste ALL_INDEXES e ALL_IND_COLUMNS di Oracle).

JCTNT leggeva tutti gli indici del database alla connessione (decine di migliaia di righe); qui si legge solo la tabella che serve.
"""
from . import names

INDEXES_SQL = ('SELECT table_owner, table_name, index_name, uniqueness, owner FROM all_indexes '
               'WHERE table_name = :t ORDER BY index_name')
COLUMNS_SQL = ('SELECT table_owner, table_name, index_owner, index_name, column_name, column_position FROM all_ind_columns '
               'WHERE table_name = :t ORDER BY index_name, column_position')
VIEWS = ('ALL_INDEXES', 'ALL_IND_COLUMNS')                  # cio' che lo strumento richiede


def read(db, table):
    """(indici, colonne) della tabella (nome fisico, anche 'PROPRIETARIO.TABELLA'), come liste di dict."""
    _, name = names.split_owner_and_name(table)
    if not name:
        return [], []
    indexes = [{'TABLE_OWNER': r[0] or '', 'TABLE_NAME': r[1] or '', 'INDEX_NAME': r[2] or '', 'UNIQUENESS': r[3] or '',
                'INDEX_OWNER': r[4] or ''} for r in db.fetch_all(INDEXES_SQL, {'t': name})]
    columns = [{'TABLE_OWNER': r[0] or '', 'TABLE_NAME': r[1] or '', 'INDEX_OWNER': r[2] or '', 'INDEX_NAME': r[3] or '',
                'COLUMN_NAME': r[4] or '', 'COLUMN_POSITION': r[5] if r[5] is not None else ''}
               for r in db.fetch_all(COLUMNS_SQL, {'t': name})]
    return names.table_indexes(indexes, columns, table)
