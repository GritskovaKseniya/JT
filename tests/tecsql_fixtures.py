"""Il dizionario di prova per i test del traduttore TecSQL (portato da JCTNT) e la base dei test.

Ogni riga: (TABELLA_FISICA, TABELLA_LOGICA, CAMPO_FISICO, CAMPO_LOGICO, TIPO, AMPIEZZA, DECIMALI), come le restituirebbe
la SELECT su FW_TABLES / FW_TABLE_FIELDS. Ogni classe di test
crea il suo `Dictionary` in `setUpClass`: nessuno stato condiviso tra i test.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jt.tecsql_translator import Dictionary  # noqa: E402

MOCK_ROWS = [
    ('GD_LIRIG', '$RigaListino', 'LIRIG_LICOD', 'CodListino', 'C', 10, 0),
    ('GD_LIRIG', '$RigaListino', 'LIRIG_CATLI', 'CatListino', 'C', 2, 0),
    ('GD_LIRIG', '$RigaListino', 'LIRIG_ARTCO', 'CodArticolo', 'C', 20, 0),
    ('GD_LIRIG', '$RigaListino', 'LIRIG_PREZO', 'Prezzo', 'N', 15, 4),
    ('GD_LITES', '$TestataListino', 'LITES_LICOD', 'Codice', 'C', 10, 0),
    ('GD_LITES', '$TestataListino', 'LITES_CATLI', 'CodCategoria', 'C', 2, 0),
    ('GD_LITES', '$TestataListino', 'LITES_DESCR', 'Descrizione', 'C', 50, 0),
]


def rows_as_dicts(mock_rows=MOCK_ROWS):
    """Le righe come le vuole `update_mappings` (il nome logico senza il `$`: lo aggiunge lei)."""
    result = []
    for physical_table, logical_table, physical_field, logical_field, kind, width, decimals in mock_rows:
        result.append({'TABELLA_FISICA': physical_table, 'CAMPO_FISICO': physical_field,
                       'TABELLA_LOGICA': logical_table.lstrip('$'), 'CAMPO_LOGICO': logical_field,
                       'TIPO': kind, 'AMPIEZZA': width, 'DECIMALI': decimals})
    return result


class TecsqlCase(unittest.TestCase):
    """Un test con il dizionario di prova caricato (`self.d`)."""

    @classmethod
    def setUpClass(cls):
        cls.d = Dictionary(rows_as_dicts())
