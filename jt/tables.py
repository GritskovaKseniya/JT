"""Le tabelle traducibili.

Ogni tabella e' una classe che sa: quali righe mancano nella lingua di output, come tradurre una riga,
come inserirla e come aggiornarla. Per aggiungere una tabella basta una nuova classe e la sua riga in TABLES.

Le righe lette con `SELECT *` sono tuple: le posizioni (row[2], row[3]...) seguono l'ordine delle colonne
di ogni tabella e restano in un solo posto, qui.
"""
import copy
import random
import re
import string
from collections import namedtuple

from .config import DB_MARKER, MAX_KEYS
from .layers import LAYERS, layer_of_code, layer_of_name, user_of_layer

MARK = f"'{DB_MARKER}'"      # costante SQL scritta nella colonna "utente" insieme a sysdate

Translated = namedtuple('Translated', 'values primary')     # valori tradotti per colonna, testo principale (log)
UpdateTarget = namedtuple('UpdateTarget', 'where sets audit')


class EmptySourceText(ValueError):
    """Testo sorgente vuoto dove serve: la riga viene saltata."""


class TooManyKeys(ValueError):
    """Piu' chiavi del limite di Oracle per una lista IN."""


class SchemaError(Exception):
    """Le colonne della tabella non si possono leggere."""


def generate_id(length=22):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def _code_range_condition(level):
    """Livello di stringhe e triplette: intervallo del codice (colonna code)."""
    if level is None:
        return '', {}
    return 'X.code BETWEEN :lvl_lo AND :lvl_hi', {'lvl_lo': level.first, 'lvl_hi': level.last}


def _layer_of_code_column(code):
    """Layer di un codice; None se il codice non cade in nessun livello."""
    try:
        return layer_of_code(int(code))
    except ValueError:
        return None


class TableSpec:
    name = ''
    lang_col = ''            # colonna della lingua
    key_cols = ()            # chiave logica senza lingua: serve a capire "manca nella lingua di output"
    select_key = ''          # colonna usata da "Update by keys"
    numeric_keys = True      # le chiavi di "Update by keys" sono numeri (altrimenti nomi)
    key_index = 0            # posizione della chiave nella riga letta
    char_expr = ''           # SQL: lunghezza dei testi sorgente (per la stima)
    needs_columns = False    # i nomi colonna vanno letti dal DB
    supports_levels = True   # False: la tabella non ha livelli (il livello scelto non filtra nulla)

    def bind_columns(self, columns):
        """Ritorna la tabella con i nomi colonna reali (solo per le tabelle che li leggono dal DB)."""
        return self

    def level_condition(self, level):
        """(frammento SQL, bind) che limita le righe a un livello (Layer); level None = tutti i livelli.
        Predefinito: nessuna condizione (tabelle senza livelli)."""
        return '', {}

    def layer_of_row(self, row):
        """Il Layer di una riga letta; None se non si sa (o se la tabella non ha livelli)."""
        return None

    def user_sql(self, row):
        """Costante SQL per la colonna utente della riga scritta: ZFXCUSTOM (CT), ZFXINTEGR (CW) o la sigla del tool.
        Viene sempre da una tabella fissa (layers.py), mai dai dati: non e' una bind variable ma non si puo' iniettare."""
        return f"'{user_of_layer(self.layer_of_row(row))}'"

    # ---------------------------------------------------------------- selezione (SQL)

    def _predicate(self, limited, level=None):
        same_key = ' AND '.join(f'X.{k} = Y.{k}' for k in self.key_cols)
        limit = ' AND ROWNUM <= :n' if limited else ''
        level_sql = self.level_condition(level)[0]
        level_sql = f' AND {level_sql}' if level_sql else ''
        return (f'X.{self.lang_col} = :li{level_sql}{limit} AND NOT EXISTS (SELECT 1 FROM {self.name} Y '
                f'WHERE {same_key} AND Y.{self.lang_col} = :lo)')

    def _binds(self, lan_in, lan_out, limit=None, level=None):
        binds = {'li': lan_in, 'lo': lan_out}
        binds.update(self.level_condition(level)[1])
        if limit is not None:
            binds['n'] = limit
        return binds

    def read_missing(self, lan_in, lan_out, limit, level=None):
        """Righe con testo in lan_in e senza la corrispondente in lan_out (al massimo `limit`)."""
        return (f'SELECT * FROM {self.name} X WHERE {self._predicate(True, level)}',
                self._binds(lan_in, lan_out, limit, level))

    def count_batch(self, lan_in, lan_out, limit, level=None):
        """(righe, caratteri) della selezione di read_missing, per la stima della durata."""
        where, binds = self._predicate(True, level), self._binds(lan_in, lan_out, limit, level)
        return ((f'SELECT COUNT(*) FROM {self.name} X WHERE {where}', binds),
                (f'SELECT SUM({self.char_expr}) FROM {self.name} X WHERE {where}', binds))

    def count_all(self, lan_in, lan_out, level=None):
        """Tutte le righe che mancano in lan_out (senza limite)."""
        return (f'SELECT COUNT(*) FROM {self.name} X WHERE {self._predicate(False, level)}',
                self._binds(lan_in, lan_out, level=level))

    def read_keys(self, lan_in, keys):
        names = [f':k{i}' for i in range(len(keys))]
        binds = {'li': lan_in}
        binds.update({f'k{i}': (int(k) if self.numeric_keys else k) for i, k in enumerate(keys)})
        return (f'SELECT * FROM {self.name} X WHERE X.{self.lang_col} = :li '
                f"AND X.{self.select_key} IN ({', '.join(names)})", binds)

    def parse_keys(self, text):
        """Chiavi separate da virgola, spazio o ;: id numerici oppure nomi (lettere, cifre, _)."""
        keys = []
        for key in re.split(r'[\s,;]+', text.strip()):
            if not key or key in keys:
                continue
            pattern = r'[0-9]+' if self.numeric_keys else r'\w+'
            if not re.fullmatch(pattern, key, re.ASCII):
                raise ValueError(key)
            keys.append(key)
        if len(keys) > MAX_KEYS:
            raise TooManyKeys(f'max {MAX_KEYS} keys')
        return keys

    def row_key(self, row, columns=None):
        return str(row[self.key_index])

    # ----------------------------------------------------------- riga -> scrittura

    def translate_row(self, row, tr):
        """tr(testo, required=False) traduce un testo. Ritorna Translated."""
        raise NotImplementedError

    def log_info(self, row):
        """(codice, testo sorgente) per i log CSV."""
        return row[1], row[2]

    def insert(self, row, lan_out, values):
        """(sql, binds) dell'INSERT: valori sempre come bind variable, un campo vuoto diventa NULL."""
        raise NotImplementedError

    def update_target(self, row, lan_out, values, columns):
        """UpdateTarget(where, sets, audit) per l'UPDATE della riga gia' presente in lan_out."""
        raise NotImplementedError

    def _insert_sql(self, values_sql):
        return f'INSERT INTO {self.name} VALUES ({values_sql})'


def _audit(columns, first, total):
    """Colonne utente/data (per scrivere 'JT' e sysdate come fa l'INSERT), se la tabella ha la forma attesa."""
    return list(columns[first:first + 2]) if columns and len(columns) == total else []


class StringsTable(TableSpec):
    name = 'FW_STRINGS'
    lang_col = 'language'
    key_cols = ('code',)
    select_key = 'code'
    key_index = 1
    char_expr = 'LENGTH(value)'

    def level_condition(self, level):
        return _code_range_condition(level)

    def layer_of_row(self, row):
        return _layer_of_code_column(row[1])

    def translate_row(self, row, tr):
        value = tr(row[2], required=True)
        return Translated({'value': value}, value)

    def insert(self, row, lan_out, values):
        """La categoria (modulo: MES, WMS...) e' della stringa, non della lingua: si copia dalla riga sorgente."""
        return (self._insert_sql(f':1, :2, :3, :4, {self.user_sql(row)}, sysdate'),
                [lan_out, row[1], values['value'], row[3]])

    def update_target(self, row, lan_out, values, columns):
        return UpdateTarget({'language': lan_out, 'code': row[1]}, {'value': values['value']}, _audit(columns, 4, 6))


class FieldStringsTable(TableSpec):
    name = 'FW_FIELD_STRINGS'
    lang_col = 'language'
    key_cols = ('code',)
    select_key = 'code'
    key_index = 1
    char_expr = 'NVL(LENGTH(caption), 0) + NVL(LENGTH(description), 0) + NVL(LENGTH(tip), 0)'

    def level_condition(self, level):
        return _code_range_condition(level)

    def layer_of_row(self, row):
        return _layer_of_code_column(row[1])

    def translate_row(self, row, tr):
        values = {'caption': tr(row[2]), 'description': tr(row[3]), 'tip': tr(row[4])}
        primary = values['description'] or values['caption'] or values['tip']
        return Translated(values, primary)

    def insert(self, row, lan_out, values):
        """La categoria (modulo) si copia dalla riga sorgente, come per FW_STRINGS."""
        return (self._insert_sql(f':1, :2, :3, :4, :5, :6, {self.user_sql(row)}, sysdate'),
                [lan_out, row[1], values['caption'], values['description'], values['tip'], row[5]])

    def update_target(self, row, lan_out, values, columns):
        return UpdateTarget({'language': lan_out, 'code': row[1]}, dict(values), _audit(columns, 6, 8))


class OptionsTable(TableSpec):
    """FW_OPZIONI e le varianti _DUE, _TRE, _INT: una riga per (tipo, codice) e lingua."""
    lang_col = 'lingua'
    key_cols = ('tipo', 'codice')
    select_key = 'tipo'
    numeric_keys = False
    key_index = 1
    char_expr = 'LENGTH(descrizione)'

    def __init__(self, name):
        self.name = name

    def level_condition(self, level):
        """Livello dal prefisso del nome (tipo). Un livello con prefisso: LIKE esatto (maiuscole/minuscole contano,
        come layer_of_name). Standard: tutto cio' che non inizia con un prefisso, senza distinguere maiuscole,
        cosi' ctXxx non finisce in Standard."""
        if level is None:
            return '', {}
        if level.prefix:
            return 'X.tipo LIKE :lvl_p', {'lvl_p': level.prefix + '%'}
        prefixes = [layer.prefix.upper() + '%' for layer in LAYERS if layer.prefix]
        binds = {f'lvl_p{i}': prefix for i, prefix in enumerate(prefixes)}
        return ' AND '.join(f'UPPER(X.tipo) NOT LIKE :{name}' for name in binds), binds

    def layer_of_row(self, row):
        return layer_of_name(row[1]) if row[1] else None

    def translate_row(self, row, tr):
        description = tr(row[3], required=True)
        return Translated({'description': description}, description)

    def insert(self, row, lan_out, values):
        return (self._insert_sql(f':1, :2, :3, :4, :5, :6, {self.user_sql(row)}, sysdate'),
                [lan_out, row[1], row[2], values['description'], row[4], row[5]])

    def update_target(self, row, lan_out, values, columns):
        return UpdateTarget({'lingua': lan_out, 'tipo': row[1], 'codice': row[2]},
                            {'descrizione': values['description']}, _audit(columns, 6, 8))


class DocuNodesTable(TableSpec):
    """FW_DOCU_NODES_T: id nodo, lingua, testo. Nomi colonna letti dal DB (ordine dell'export .unl)."""
    name = 'FW_DOCU_NODES_T'
    needs_columns = True
    supports_levels = False
    char_expr = ''

    def bind_columns(self, columns):
        if len(columns) < 3:
            raise SchemaError(f'{self.name}: columns not readable')
        bound = copy.copy(self)
        key, lang, text = columns[:3]
        bound.lang_col, bound.key_cols, bound.select_key = lang, (key,), key
        bound.text_col, bound.char_expr = text, f'LENGTH({text})'
        return bound

    def translate_row(self, row, tr):
        text = tr(row[2])
        return Translated({'text': text}, text)

    def log_info(self, row):
        return row[0], row[2]

    def insert(self, row, lan_out, values):
        """Con i nomi delle colonne: le altre (se ci sono) restano vuote. Senza, il numero di valori deve combaciare
        con le colonne della tabella (ORA-00913 'troppi valori' se ne ha meno)."""
        sql = f'INSERT INTO {self.name} ({self.key_cols[0]}, {self.lang_col}, {self.text_col}) VALUES (:1, :2, :3)'
        return sql, [row[0], lan_out, values['text']]

    def update_target(self, row, lan_out, values, columns):
        key, lang, text = columns[:3]
        return UpdateTarget({lang: lan_out, key: row[0]}, {text: values['text']}, [])


class ObjDescrsTable(TableSpec):
    """FW_OBJ_DESCRS: descrizioni per lingua dei campi di altre tabelle (es. QL_CARAT.CARAT_DESCR)."""
    name = 'FW_OBJ_DESCRS'
    lang_col = 'language'
    key_cols = ('objid', 'tablename', 'tablefieldname')
    select_key = 'objid'
    key_index = 0
    supports_levels = False
    char_expr = 'LENGTH(description)'

    def translate_row(self, row, tr):
        description = tr(row[4])
        return Translated({'description': description}, description)

    def log_info(self, row):
        return f'{row[0]}/{row[1]}.{row[2]}', row[4]

    def insert(self, row, lan_out, values):
        return self._insert_sql(':1, :2, :3, :4, :5'), [row[0], row[1], row[2], lan_out, values['description']]

    def update_target(self, row, lan_out, values, columns):
        return UpdateTarget({'objid': row[0], 'tablename': row[1], 'tablefieldname': row[2], 'language': lan_out},
                            {'description': values['description']}, [])


class FwkStringsTable(TableSpec):
    """FWK_STRINGS (SFC). Disabilitata in tables.json: il codice resta per riattivarla."""
    name = 'FWK_STRINGS'
    lang_col = 'lang'
    key_cols = ('pack', 'code')
    select_key = 'code'
    numeric_keys = False
    needs_columns = True
    char_expr = 'NVL(LENGTH(value), 0) + NVL(LENGTH(short_value), 0) + NVL(LENGTH(long_value), 0)'

    @staticmethod
    def _index(columns, name):
        return [c.upper() for c in columns].index(name)

    def row_key(self, row, columns=None):
        return str(row[self._index(columns, 'CODE')])

    def translate_row(self, row, tr):
        values = {'long_value': tr(row[3]), 'short_value': tr(row[4]), 'value': tr(row[9])}
        return Translated(values, values['value'])

    def insert(self, row, lan_out, values):
        return (self._insert_sql(f':1, :2, :3, :4, :5, :6, :7, :8, {MARK}, :9'),
                [generate_id(), row[1], row[2], values['long_value'], values['short_value'], row[5],
                 lan_out, row[7], values['value']])

    def update_target(self, row, lan_out, values, columns):
        where = {'lang': lan_out, 'pack': row[self._index(columns, 'PACK')], 'code': row[self._index(columns, 'CODE')]}
        return UpdateTarget(where, dict(values), [])


TABLES = {spec.name: spec for spec in (
    StringsTable(), FieldStringsTable(),
    OptionsTable('FW_OPZIONI'), OptionsTable('FW_OPZIONI_DUE'), OptionsTable('FW_OPZIONI_TRE'), OptionsTable('FW_OPZIONI_INT'),
    DocuNodesTable(), ObjDescrsTable(), FwkStringsTable(),
)}


def get_table(name):
    return TABLES[name]
