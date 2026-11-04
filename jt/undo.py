"""Lo script che annulla una corsa: un DELETE per ogni riga inserita e un UPDATE che rimette i valori di prima per ogni riga aggiornata.

Il servizio annota, per ogni riga scritta, un `UndoRecord` (tabella, come si riconosce la riga, valori di prima). Lo script e' testo
SQL per SQL Developer (Run Script, F5): solo ASCII (i caratteri speciali sono scritti con UNISTR, cosi' la codifica del file non
conta) e con `SET DEFINE OFF` (altrimenti una `&` nel testo farebbe chiedere un valore).
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

IDENTIFIER = re.compile(r'[A-Za-z][A-Za-z0-9_$#]*$')


@dataclass
class UndoRecord:
    table: str
    action: str                                   # 'insert' (si annulla con DELETE) oppure 'update' (si rimette `old`)
    where: dict                                   # colonna -> valore che riconosce la riga (la lingua compresa)
    old: dict = field(default_factory=dict)       # colonna -> valore di prima (solo update; con utente e data se la tabella li ha)


def identifier(name):
    """Il nome di una tabella o colonna: solo quelli normali (vengono dal programma e dal database, mai dai testi)."""
    if not isinstance(name, str) or not IDENTIFIER.match(name):
        raise ValueError(f'Invalid SQL name: {name!r}')
    return name


def _text(text):
    """Un testo come costante SQL. Se ha caratteri fuori dall'ASCII stampabile (accenti, hindi, a capo) si scrive con UNISTR."""
    if all(' ' <= ch <= '~' for ch in text):
        return "'" + text.replace("'", "''") + "'"
    pieces = []
    for ch in text:
        if ch == "'":
            pieces.append("''")
        elif ch == '\\':
            pieces.append('\\005C')
        elif ' ' <= ch <= '~':
            pieces.append(ch)
        else:                                      # UNISTR vuole unita' UTF-16 (i caratteri oltre U+FFFF sono due)
            data = ch.encode('utf-16-be')
            pieces.extend(f'\\{int.from_bytes(data[i:i + 2], "big"):04X}' for i in range(0, len(data), 2))
    return "UNISTR('" + ''.join(pieces) + "')"


def literal(value):
    """Un valore come costante SQL."""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        stamp = value if isinstance(value, datetime) else datetime(value.year, value.month, value.day)
        return f"TO_DATE('{stamp:%Y-%m-%d %H:%M:%S}', 'YYYY-MM-DD HH24:MI:SS')"
    if isinstance(value, str):
        return _text(value)
    raise TypeError(f'cannot write a value of type {type(value).__name__} in the undo script')


def _conditions(where):
    return ' AND '.join(f'{identifier(column)} = {literal(value)}' for column, value in where.items())


def statement(record):
    if record.action == 'insert':
        return f'DELETE FROM {identifier(record.table)} WHERE {_conditions(record.where)};'
    values = ', '.join(f'{identifier(column)} = {literal(value)}' for column, value in record.old.items())
    return f'UPDATE {identifier(record.table)} SET {values} WHERE {_conditions(record.where)};'


def build_script(records, database='', host='', when=None):
    """Il testo dello script. Si annulla dall'ultima riga scritta alla prima."""
    when = when or datetime.now()
    inserts = sum(1 for record in records if record.action == 'insert')
    updates = len(records) - inserts
    lines = ['-- JT undo script',
             f"-- Generated {when:%Y-%m-%d %H:%M:%S} for the database {database or '?'} ({host or '?'})",
             f'-- Undoes {inserts} insert(s) (DELETE) and {updates} update(s) (the previous values are put back).',
             '-- Run it in SQL Developer (Run Script, F5) on the SAME database, as soon as possible.',
             '-- It does not check whether somebody changed these rows after JT wrote them.',
             '',
             'SET DEFINE OFF;']
    lines += [statement(record) for record in reversed(records)]
    lines += ['COMMIT;', '']
    return '\n'.join(lines)
