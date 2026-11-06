"""Cercare nomi nel dizionario di Jflex: tabelle (nome fisico o logico, con suggerimenti "fuzzy" se non c'e' un risultato
esatto), campi di una tabella e indici. Nessuna interfaccia qui. Portato da JCTNT (`fuzzy-search.js` e `app.js`).

Il dizionario e' quello di `jt.dictionary` (`Dictionary.rows`: un dict per campo con TABELLA_FISICA, CAMPO_FISICO, TABELLA_LOGICA,
CAMPO_LOGICO, TIPO, AMPIEZZA, DECIMALI). Gli indici si leggono dal database con `jt.indexes`.
"""
import re
from dataclasses import dataclass

EXACT, STARTS_WITH, CONTAINS, FUZZY, NO_MATCH = 'exact', 'starts_with', 'contains', 'fuzzy', 'no_match'
VIRTUAL = '-'                       # nel dizionario un descrittore senza tabella fisica ha '-' come nome fisico
MAX_SUGGESTIONS = 10
MIN_SCORE = 50
FIELD_COLUMNS = ('TABELLA_FISICA', 'CAMPO_FISICO', 'TABELLA_LOGICA', 'CAMPO_LOGICO', 'TIPO', 'AMPIEZZA', 'DECIMALI')


# ----------------------------------------------------------------------------------------------------- somiglianza

def levenshtein(a, b):
    """Quante modifiche (inserire, togliere, sostituire un carattere) servono per trasformare `a` in `b`; maiuscole ignorate."""
    a, b = a.lower(), b.lower()
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        previous = current
    return previous[-1]


def similarity(a, b):
    """Da 0 (tutto diverso) a 1 (uguali)."""
    longest = max(len(a), len(b))
    return 1.0 if longest == 0 else 1 - levenshtein(a, b) / longest


def partial_match(text, part):
    """`text` contiene `part` (senza badare alle maiuscole e agli spazi)."""
    def squash(value):
        return re.sub(r'\s+', '', value.lower())
    return squash(part) in squash(text)


@dataclass(frozen=True)
class Match:
    score: float
    type: str
    match: str = ''              # 'fisico' o 'logico': quale dei due nomi ha combaciato
    similarity: float = 0.0


def score_table(physical, logical, text):
    """Quanto un nome di tabella (fisico e logico) somiglia a `text`: esatto 1000, inizia con 500-900, contiene 200-500,
    simile (oltre il 50%) fino a 100, altrimenti niente."""
    wanted = text.lower().strip()
    physical = (physical or '').lower().strip()
    logical = (logical or '').lower().strip()
    if physical == wanted or logical == wanted:
        return Match(1000, EXACT, 'fisico' if physical == wanted else 'logico')
    best = max(similarity(physical, wanted), similarity(logical, wanted))
    if physical.startswith(wanted) or logical.startswith(wanted):
        return Match(500 + best * 400, STARTS_WITH, 'fisico' if physical.startswith(wanted) else 'logico', best)
    if partial_match(physical, wanted) or partial_match(logical, wanted):
        return Match(200 + best * 300, CONTAINS, 'fisico' if partial_match(physical, wanted) else 'logico', best)
    if best > 0.5:
        return Match(best * 100, FUZZY, 'fisico' if similarity(physical, wanted) > similarity(logical, wanted) else 'logico', best)
    return Match(0, NO_MATCH)


# --------------------------------------------------------------------------------------------------------- tabelle

@dataclass
class TableMatch:
    physical: str
    logical: str
    score: float
    type: str
    match: str
    similarity: float
    fields: int                  # quanti campi ha il descrittore


def table_summary(dictionary):
    """[(tabella fisica, nome logico, quanti campi)] per ogni descrittore del dizionario (calcolato una volta e tenuto)."""
    cached = getattr(dictionary, '_table_summary', None)
    if cached is None:
        counts = {}
        for row in dictionary.rows:
            physical, logical = row.get('TABELLA_FISICA') or '', row.get('TABELLA_LOGICA') or ''
            if physical:
                counts[(physical, logical)] = counts.get((physical, logical), 0) + 1
        cached = dictionary._table_summary = [(p, l, n) for (p, l), n in counts.items()]
    return cached


def normalize_table_name(value):
    return re.sub(r'\s+', '', value or '').upper()


def best_table_matches(dictionary, text, max_results=MAX_SUGGESTIONS, min_score=MIN_SCORE):
    """(esatti, suggerimenti): le tabelle che combaciano esattamente col nome (fisico o logico) e le piu' simili, per punteggio.
    Una tabella fisica con piu' nomi logici compare una volta, con il nome logico che combacia meglio."""
    if not text or not text.strip():
        return [], []
    best = {}
    for physical, logical, fields in table_summary(dictionary):
        match = score_table(physical, logical, text)
        if match.score < min_score:
            continue
        key = physical if physical != VIRTUAL else (physical, logical)     # i descrittori senza tabella ('-') non si uniscono
        current = best.get(key)
        if current is None or match.score > current.score:
            best[key] = TableMatch(physical, logical, match.score, match.type, match.match, match.similarity, fields)
    ordered = sorted(best.values(), key=lambda t: (-t.score, -t.fields, t.physical))
    return [t for t in ordered if t.type == EXACT], [t for t in ordered if t.type != EXACT][:max_results]


def table_rows(dictionary, table):
    """Le righe (campi) di una tabella trovata: se ha combaciato il nome logico solo quelle di quel descrittore, se il fisico
    tutti i descrittori della tabella fisica."""
    if table.physical == VIRTUAL or (table.match == 'logico' and table.type == EXACT):
        return [r for r in dictionary.rows if r.get('TABELLA_FISICA') == table.physical and r.get('TABELLA_LOGICA') == table.logical]
    return [r for r in dictionary.rows if r.get('TABELLA_FISICA') == table.physical]


def search_fields(rows, fields_text):
    """Le righe dei campi chiesti (nomi fisici o logici separati da virgola, spazio o a capo; vuoto = tutti). Un campo che non c'e'
    diventa una riga `notFound` con CAMPO_LOGICO 'NOT FOUND'."""
    if not rows:
        return []
    names = [f for f in re.split(r'[\s,]+', (fields_text or '').strip()) if f]
    if not names:
        return list(rows)
    results = []
    for name in names:
        upper = name.upper()
        found = next((r for r in rows if (r.get('CAMPO_FISICO') or '').upper() == upper
                      or (r.get('CAMPO_LOGICO') or '').upper() == upper), None)
        if found:
            results.append(found)
        else:
            results.append({'TABELLA_FISICA': rows[0].get('TABELLA_FISICA'), 'CAMPO_FISICO': name,
                            'TABELLA_LOGICA': rows[0].get('TABELLA_LOGICA'), 'CAMPO_LOGICO': 'NOT FOUND',
                            'TIPO': '-', 'AMPIEZZA': '-', 'DECIMALI': '-', 'notFound': True})
    return results


def best_field_matches(rows, text, max_results=MAX_SUGGESTIONS):
    """I campi di una tabella piu' simili a `text` (per i suggerimenti sui campi): [(riga, punteggio, tipo)]."""
    if not text or not rows:
        return []
    wanted = text.lower().strip()
    scored = []
    for row in rows:
        physical = (row.get('CAMPO_FISICO') or '').lower().strip()
        logical = (row.get('CAMPO_LOGICO') or '').lower().strip()
        best = max(similarity(physical, wanted), similarity(logical, wanted))
        if physical == wanted or logical == wanted:
            score, kind = 1000, EXACT
        elif physical.startswith(wanted) or logical.startswith(wanted):
            score, kind = 500 + best * 400, STARTS_WITH
        elif wanted in physical or wanted in logical:
            score, kind = 200 + best * 300, CONTAINS
        elif best > 0.5:
            score, kind = best * 100, FUZZY
        else:
            continue
        scored.append((row, score, kind))
    scored.sort(key=lambda item: -item[1])
    return scored[:max_results]


def sort_key(column, value):
    """Per ordinare le colonne dei risultati: AMPIEZZA, DECIMALI e POSIZ_DB come numeri (i '-' e i vuoti in fondo), il resto come testo."""
    if column in ('AMPIEZZA', 'DECIMALI', 'POSIZ_DB'):
        try:
            return (0, float(value))
        except (TypeError, ValueError):
            return (1, 0.0)
    return (0, str(value if value is not None else '').lower())


def default_order(rows):
    """L'ordine di partenza dei campi di una tabella, come nei descrittori: per descrittore (nome logico della tabella) e, dentro
    ognuno, per posizione nel database ("Posiz. DB"); chi non ha la posizione in fondo, nell'ordine di prima."""
    return sorted(rows, key=lambda row: (str(row.get('TABELLA_LOGICA') or '').lower(), sort_key('POSIZ_DB', row.get('POSIZ_DB'))))


def tsv(rows, columns=FIELD_COLUMNS):
    """Le righe come testo da incollare in Excel: intestazione e valori separati da tabulazione."""
    lines = ['\t'.join(columns)]
    for row in rows:
        lines.append('\t'.join('' if row.get(c) is None else str(row.get(c)) for c in columns))
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------------------------------------- indici

def split_owner_and_name(value):
    """'OWNER.TABELLA' -> ('OWNER', 'TABELLA'); senza punto il proprietario e' vuoto."""
    normalized = normalize_table_name(value)
    if '.' not in normalized:
        return '', normalized
    owner, _, name = normalized.rpartition('.')
    return owner, name


def matches_table_entry(entry, table):
    owner, name = split_owner_and_name(table)
    if not name or normalize_table_name(entry.get('TABLE_NAME')) != name:
        return False
    entry_owner = normalize_table_name(entry.get('TABLE_OWNER') or '')
    return entry_owner == owner if owner and entry_owner else True


def index_key(entry):
    name = normalize_table_name(entry.get('INDEX_NAME'))
    owner = normalize_table_name(entry.get('INDEX_OWNER') or '')
    return f'{owner}.{name}' if owner else name


def pick_index_owner(indexes, columns):
    """Se la stessa tabella esiste in piu' schemi si tiene quello con piu' indici (poi piu' colonne, poi per nome)."""
    stats = {}
    for row in indexes:
        stats.setdefault(normalize_table_name(row.get('TABLE_OWNER') or ''), [0, 0])[0] += 1
    for row in columns:
        stats.setdefault(normalize_table_name(row.get('TABLE_OWNER') or ''), [0, 0])[1] += 1
    if len(stats) <= 1:
        return next(iter(stats), '')
    return sorted(stats.items(), key=lambda item: (-item[1][0], -item[1][1], item[0]))[0][0]


def dedupe_indexes(rows):
    seen, result = set(), []
    for row in rows:
        key = (normalize_table_name(row.get('TABLE_NAME')), index_key(row), row.get('UNIQUENESS') or '')
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def dedupe_index_columns(rows):
    seen, result = set(), []
    for row in rows:
        key = (normalize_table_name(row.get('TABLE_NAME')), index_key(row), normalize_table_name(row.get('COLUMN_NAME')),
               row.get('COLUMN_POSITION') or '')
        if key not in seen:
            seen.add(key)
            result.append(row)
    return result


def table_indexes(indexes, columns, table):
    """(indici, colonne) di una tabella: quelli che combaciano, dello schema scelto e senza doppioni."""
    own_indexes = [i for i in indexes if matches_table_entry(i, table)]
    own_columns = [c for c in columns if matches_table_entry(c, table)]
    owner = pick_index_owner(own_indexes, own_columns)
    if owner:
        own_indexes = [i for i in own_indexes if normalize_table_name(i.get('TABLE_OWNER') or '') == owner]
        own_columns = [c for c in own_columns if normalize_table_name(c.get('TABLE_OWNER') or '') == owner]
    return dedupe_indexes(own_indexes), dedupe_index_columns(own_columns)


def indexes_text(table, indexes, columns):
    """Gli indici come testo da copiare: ogni indice con le sue colonne in ordine."""
    text = f'INDEXES OF TABLE: {table}\n\n'
    for index in indexes:
        text += f"INDEX: {index.get('INDEX_NAME')} ({index.get('UNIQUENESS')})\n"
        own = [c for c in columns if index_key(c) == index_key(index)]
        if own:
            text += 'COLUMNS:\n' + ''.join(f"  {c.get('COLUMN_POSITION')}. {c.get('COLUMN_NAME')}\n" for c in own)
        text += '\n'
    return text
