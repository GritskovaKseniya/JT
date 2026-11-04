"""Traduzione SQL <-> TecSQL: i nomi logici dei descrittori ($RigaListino.CodListino) e i nomi fisici di Oracle (GD_LIRIG.LIRIG_LICOD).

Portato da JCTNT (scritto da Angelo J. Marin) com'e': le mappe del dizionario sono ancora
globali di modulo e `update_mappings(rows)` le riempie. Il dizionario si legge dal database con `jt/dictionary.py`; i messaggi
d'errore sono ancora in italiano come nell'originale. Passo successivo (vedi PIANO_TOOLKIT.md): trasformare le mappe globali in
una classe `Dictionary` senza stato condiviso. Usa `sqlparse`.
"""
import re
import sqlparse

# --- Dynamic mapping (populated after DB connect) ---
TABLE_MAP = {}
FIELD_MAP = {}
PHYSICAL_TABLE_MAP = {}
REVERSE_FIELD_MAP = {}  # physical_table → {physical_field → {descriptor → logical_field}}
TABLE_ORIGINAL_CASE = {}   # normalized_key → original logical table name with $ (original case)
FIELD_ORIGINAL_CASE = {}   # (normalized_table_key, normalized_field_key) → original logical field name

KEYWORDS = {
    'SELECT', 'FROM', 'WHERE', 'JOIN', 'LEFT', 'RIGHT', 'FULL', 'INNER', 'OUTER',
    'CROSS', 'ON', 'ORDER', 'BY', 'GROUP', 'HAVING', 'AS', 'AND', 'OR', 'DISTINCT',
    'IN', 'EXISTS', 'NOT', 'NULL', 'IS', 'LIKE', 'BETWEEN',
    'UNION', 'INTERSECT', 'MINUS', 'EXCEPT', 'LIMIT'
}

TWO_CHAR_OPS = {'>=', '<=', '<>', '!=', '==', '||'}


def normalize_query_text(query):
    # Normalize by removing newlines and trimming extra whitespace.
    text = '' if query is None else str(query)
    text = re.sub(r'[\r\n]+', ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _tokenize(query):
    tokens = []
    i = 0
    length = len(query)

    while i < length:
        ch = query[i]

        if ch.isspace():
            i += 1
            continue

        if ch == "'":
            start = i
            i += 1
            while i < length:
                if query[i] == "'":
                    if i + 1 < length and query[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            tokens.append({'type': 'STRING', 'text': query[start:i]})
            continue

        if ch == '?':
            start = i
            i += 1
            if i < length and query[i] == '!':
                i += 1
            while i < length and (query[i].isalnum() or query[i] == '_'):
                i += 1
            tokens.append({'type': 'PARAM', 'text': query[start:i]})
            continue

        if ch == '$':
            start = i
            i += 1
            while i < length and (query[i].isalnum() or query[i] == '_'):
                i += 1
            table = query[start:i]
            if i < length and query[i] == '.':
                if i + 1 < length and query[i + 1] == '*':
                    i += 2
                    tokens.append({
                        'type': 'LOGICAL_TABLE_STAR',
                        'text': f'{table}.*',
                        'table': table
                    })
                    continue
                i += 1
                field_start = i
                while i < length and (query[i].isalnum() or query[i] == '_'):
                    i += 1
                field = query[field_start:i]
                tokens.append({
                    'type': 'LOGICAL_FIELD',
                    'text': f'{table}.{field}',
                    'table': table,
                    'field': field
                })
            else:
                tokens.append({'type': 'LOGICAL_NAME', 'text': table, 'name': table})
            continue

        if ch.isalpha() or ch == '_':
            start = i
            i += 1
            while i < length and (query[i].isalnum() or query[i] == '_'):
                i += 1
            text = query[start:i]
            token_type = 'KEYWORD' if text.upper() in KEYWORDS else 'IDENT'
            tokens.append({'type': token_type, 'text': text})
            continue

        if ch.isdigit():
            start = i
            i += 1
            while i < length and (query[i].isdigit() or query[i] == '.'):
                i += 1
            tokens.append({'type': 'NUMBER', 'text': query[start:i]})
            continue

        if ch == '#':
            start = i
            i += 1
            if i < length and query[i].isalpha():
                while i < length and query[i].isalpha():
                    i += 1
                tokens.append({'type': 'OP', 'text': query[start:i]})
                continue
            if i < length and query[i] in '=<>!':
                i += 1
                if i < length and query[i] == '=':
                    i += 1
                tokens.append({'type': 'OP', 'text': query[start:i]})
                continue
            tokens.append({'type': 'OP', 'text': '#'})
            continue

        if i + 1 < length and query[i:i + 2] in TWO_CHAR_OPS:
            tokens.append({'type': 'OP', 'text': query[i:i + 2]})
            i += 2
            continue

        tokens.append({'type': 'SYMBOL', 'text': ch})
        i += 1

    return tokens


def _normalize_table_key(logical_table):
    text = '' if logical_table is None else str(logical_table).strip()
    if text.startswith('$'):
        text = text[1:]
    text = re.sub(r'\s+', '', text).lower()
    return f'${text}' if text else ''


def _normalize_field_key(logical_field):
    text = '' if logical_field is None else str(logical_field).strip()
    text = re.sub(r'\s+', '', text).lower()
    return text


def _extract_tables_and_aliases(stmt):
    """
    Estrae tabelle fisiche e alias da un sqlparse statement.
    Usa get_real_name() e get_alias() per evitare contaminazione alias.

    Returns: {'tables': [...], 'alias_map': {'o': 'ORDERS_TBL', ...}}
    """
    tables = []
    alias_map = {}
    FROM_KW = {'FROM', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'FULL', 'CROSS'}

    def process_identifier(identifier):
        # Salta subquery (FROM (SELECT ...) alias)
        first = next(
            (t for t in identifier.tokens
             if t.ttype not in (sqlparse.tokens.Text.Whitespace, sqlparse.tokens.Newline)
             and str(t).strip()),
            None
        )
        if isinstance(first, sqlparse.sql.Parenthesis):
            return
        real_name = identifier.get_real_name()
        alias = identifier.get_alias()
        if real_name:
            upper = real_name.upper()
            if upper not in tables:
                tables.append(upper)
            if alias:
                alias_map[alias.lower()] = upper

    in_from = False
    for token in stmt.tokens:
        if token.ttype in (sqlparse.tokens.Keyword, sqlparse.tokens.Keyword.DML):
            kw = token.value.upper().strip()
            if kw in FROM_KW or kw == 'FROM':
                in_from = True
            elif kw in ('WHERE', 'SELECT', 'SET', 'HAVING', 'ORDER', 'GROUP', 'LIMIT', 'FOR'):
                in_from = False
        elif in_from:
            if isinstance(token, sqlparse.sql.IdentifierList):
                for ident in token.get_identifiers():
                    if isinstance(ident, sqlparse.sql.Identifier):
                        process_identifier(ident)
                in_from = False
            elif isinstance(token, sqlparse.sql.Identifier):
                process_identifier(token)
                in_from = False

    return {'tables': tables, 'alias_map': alias_map}


def _is_comparison_value(sql, identifier):
    """
    Return True if `identifier` appears as a VALUE (right-hand side) of a
    comparison operator in `sql`, meaning it is a constant / JAS parameter,
    NOT a field name.

    Examples that return True:
        bolla_ck = BOLLA_PASSATA_AL_JAS
        ncode_ck != UMV_PASSATA_AL_SERVIZIO
        status <> ACTIVE_FLAG

    Examples that return False (identifier is a field, left-hand side):
        LIRIG_CATLIT = 'LL'
        LIRIG_CATLIT > 0
    """
    pattern = r'(?:[=!<>]{1,2})\s*\b' + re.escape(identifier) + r'\b'
    return bool(re.search(pattern, sql, re.IGNORECASE))


def _extract_fields_from_sql(sql_query):
    """
    Extract tables, aliases and fields from SQL query.

    Qualified fields (TABLE.FIELD) are found via regex scan of the entire
    query (WHERE, ON, ORDER BY included) — not just the SELECT clause.
    Unqualified fields are extracted from the SELECT clause via sqlparse.

    Returns:
        {
            'tables': ['ORDERS_TBL', 'CUSTOMERS_TBL'],
            'fields': {
                'ORDERS_TBL': ['ORDER_ID', 'STATUS'],
                'CUSTOMERS_TBL': ['CUSTOMER_ID', 'NAME']
            },
            'unqualified_fields': ['TOTAL'],
            'alias_map': {'o': 'ORDERS_TBL', 'c': 'CUSTOMERS_TBL'}
        }
    """
    parsed = sqlparse.parse(sql_query)
    if not parsed:
        return {'tables': [], 'fields': {}, 'unqualified_fields': [], 'alias_map': {}}

    stmt = parsed[0]

    # Tables and aliases via the structural parser
    table_info = _extract_tables_and_aliases(stmt)
    tables = table_info['tables']
    alias_map = table_info['alias_map']

    fields = {}
    unqualified = []

    # Map every known prefix (table name or alias) → physical table name
    prefix_to_table = {}
    for t in tables:
        prefix_to_table[t.lower()] = t
    for alias, phys in alias_map.items():
        prefix_to_table[alias.lower()] = phys

    # Scan the entire SQL for PREFIX.FIELD — covers SELECT, WHERE, ON, ORDER BY, etc.
    # First strip string literals to avoid false matches inside quoted values.
    clean_sql = re.sub(r"'(?:[^']|'')*'", "''", sql_query)
    for m in re.finditer(r'\b(\w+)\.(\w+)\b', clean_sql):
        prefix = m.group(1)
        field = m.group(2).upper()
        table = prefix_to_table.get(prefix.lower())
        if table and field != '*':
            if table not in fields:
                fields[table] = []
            if field not in fields[table]:
                fields[table].append(field)

    # Unqualified fields: scan SELECT clause identifiers via sqlparse
    for token in stmt.tokens:
        if isinstance(token, sqlparse.sql.IdentifierList):
            for identifier in token.get_identifiers():
                if isinstance(identifier, sqlparse.sql.Identifier):
                    _extract_unqualified_field(identifier, unqualified)
        elif isinstance(token, sqlparse.sql.Identifier):
            _extract_unqualified_field(token, unqualified)

    # Also scan the entire query for lowercase unqualified identifiers.
    # Physical Oracle field names are typically lowercase/snake_case (e.g. bolla_ck),
    # while constants/variables passed to JAS are UPPERCASE (e.g. BOLLA_PASSATA_AL_JAS).
    # This lets us find field references in WHERE/HAVING/ON that have no table prefix.
    _SQL_NON_FIELD_WORDS = {
        'select', 'from', 'where', 'join', 'left', 'right', 'full', 'inner', 'outer',
        'cross', 'on', 'order', 'by', 'group', 'having', 'as', 'and', 'or', 'not',
        'in', 'exists', 'like', 'between', 'is', 'null', 'distinct', 'union',
        'intersect', 'minus', 'except', 'limit', 'fetch', 'first', 'rows', 'only',
        'offset', 'all', 'any', 'true', 'false', 'asc', 'desc', 'case', 'when',
        'then', 'else', 'end', 'cast', 'coalesce', 'sum', 'count', 'avg', 'min',
        'max', 'nvl', 'nvl2', 'decode', 'upper', 'lower', 'trim', 'substr',
        'length', 'to_date', 'to_char', 'to_number', 'rownum', 'rowid',
        'sysdate', 'dual', 'into', 'values', 'set', 'over', 'partition', 'row',
    }
    already_unqualified = {u.lower() for u in unqualified}
    known_prefixes = set(prefix_to_table.keys())

    for m in re.finditer(r'(?<![.$])\b([A-Za-z][A-Za-z0-9_]+)\b', clean_sql):
        ident = m.group(1)
        ident_lower = ident.lower()
        if (ident_lower not in _SQL_NON_FIELD_WORDS
                and ident_lower not in already_unqualified
                and ident_lower not in known_prefixes):
            unqualified.append(ident)
            already_unqualified.add(ident_lower)

    # sqlparse sometimes includes FROM-clause table names as top-level Identifiers,
    # causing them to appear in unqualified as if they were SELECT columns.
    # Remove any entry that matches a known table name (case-insensitive).
    known_table_upper = {t.upper() for t in tables}
    unqualified = [u for u in unqualified if u.upper() not in known_table_upper]

    return {'tables': tables, 'fields': fields, 'unqualified_fields': unqualified, 'alias_map': alias_map}


def _extract_unqualified_field(identifier, unqualified):
    """Add an unqualified field name (no table prefix) to the list."""
    if identifier.get_parent_name() is not None:
        return  # qualified field, handled by regex scan
    real_name = identifier.get_real_name()
    if real_name:
        field = real_name.upper()
        _SKIP = {'*', 'SELECT', 'FROM', 'WHERE', 'AS', 'NULL', 'AND', 'OR', 'NOT'}
        if field and field not in _SKIP and field not in unqualified:
            unqualified.append(field)


def _find_matching_descriptors(physical_table, used_fields):
    """
    Find which descriptors contain used fields.

    Returns:
        {
            'exact_matches': ['$orders'],  # All fields present
            'partial_matches': [           # Some fields present
                {
                    'descriptor': '$ordermain',
                    'matched': ['ORDER_ID'],
                    'missing': ['STATUS'],
                    'coverage': 0.5
                }
            ],
            'best_match': '$orders'  # Highest coverage
        }
    """
    physical_key = str(physical_table).strip().lower()
    all_descriptors = PHYSICAL_TABLE_MAP.get(physical_key, [])

    if not all_descriptors:
        return {'exact_matches': [], 'partial_matches': [], 'best_match': None}

    if len(all_descriptors) == 1:
        return {'exact_matches': all_descriptors, 'partial_matches': [], 'best_match': all_descriptors[0]}

    exact_matches = []
    partial_matches = []

    for descriptor in all_descriptors:
        available_fields = FIELD_MAP.get(descriptor, {})
        available_physical = set()
        for logical_field, physical_field in available_fields.items():
            available_physical.add(str(physical_field).strip().upper())

        matched = []
        missing = []

        for used_field in used_fields:
            if str(used_field).strip().upper() in available_physical:
                matched.append(used_field)
            else:
                missing.append(used_field)

        if len(missing) == 0:
            exact_matches.append(descriptor)
        else:
            coverage = len(matched) / len(used_fields) if used_fields else 0
            partial_matches.append({
                'descriptor': descriptor,
                'matched': matched,
                'missing': missing,
                'coverage': coverage
            })

    # Sort partial by coverage
    partial_matches.sort(key=lambda x: x['coverage'], reverse=True)
    best_match = exact_matches[0] if exact_matches else (partial_matches[0]['descriptor'] if partial_matches else None)

    return {
        'exact_matches': exact_matches,
        'partial_matches': partial_matches,
        'best_match': best_match
    }


def update_mappings(rows):
    # Build logical->physical maps from DB dictionary rows.
    # Now supports multiple descriptors per physical table.
    TABLE_MAP.clear()
    FIELD_MAP.clear()
    PHYSICAL_TABLE_MAP.clear()
    REVERSE_FIELD_MAP.clear()
    TABLE_ORIGINAL_CASE.clear()
    FIELD_ORIGINAL_CASE.clear()

    for row in rows:
        logical_table = row.get('TABELLA_LOGICA')
        physical_table = row.get('TABELLA_FISICA')
        logical_field = row.get('CAMPO_LOGICO')
        physical_field = row.get('CAMPO_FISICO')

        table_key = _normalize_table_key(logical_table)
        if not table_key or not physical_table:
            continue

        # Logical → Physical (unchanged)
        TABLE_MAP.setdefault(table_key, physical_table)

        # Original case storage (for SQL → TecSQL reverse translation)
        TABLE_ORIGINAL_CASE.setdefault(table_key, '$' + str(logical_table).strip())

        # Physical → Logical (FIXED: store all descriptors in list)
        physical_key = str(physical_table).strip().lower()
        if physical_key not in PHYSICAL_TABLE_MAP:
            PHYSICAL_TABLE_MAP[physical_key] = []
        if table_key not in PHYSICAL_TABLE_MAP[physical_key]:
            PHYSICAL_TABLE_MAP[physical_key].append(table_key)

        # Field maps (Logical → Physical)
        field_key = _normalize_field_key(logical_field)
        if field_key and physical_field:
            FIELD_MAP.setdefault(table_key, {})
            FIELD_MAP[table_key].setdefault(field_key, physical_field)

            # Reverse field map (Physical → Logical for each descriptor)
            REVERSE_FIELD_MAP.setdefault(physical_key, {})
            physical_field_lower = str(physical_field).strip().lower()
            REVERSE_FIELD_MAP[physical_key].setdefault(physical_field_lower, {})
            REVERSE_FIELD_MAP[physical_key][physical_field_lower][table_key] = field_key

            # Original case storage for field names
            FIELD_ORIGINAL_CASE.setdefault((table_key, field_key), str(logical_field).strip())


def _resolve_table(logical_table):
    key = _normalize_table_key(logical_table)
    if key not in TABLE_MAP:
        raise ValueError(f'Tabella logica non mappata: {logical_table}')
    return TABLE_MAP[key]


def _resolve_field(logical_table, logical_field):
    table_key = _normalize_table_key(logical_table)
    fields = FIELD_MAP.get(table_key, {})
    field_key = _normalize_field_key(logical_field)
    if field_key not in fields:
        raise ValueError(f'Campo logico non mappato: {logical_table}.{logical_field}')
    return fields[field_key]


def _format_tokens(tokens):
    result = ''
    prev_text = ''

    for token in tokens:
        text = token['text']
        if not result:
            result = text
        elif text in {',', ')', ';'}:
            result += text
        elif text == '.' or prev_text in {'(', '.'}:
            result += text
        else:
            result += f' {text}'
        prev_text = text

    return result


def _collect_subquery_tokens(tokens, open_paren_idx):
    """
    A partire da un token '(' all'indice dato, raccoglie tutti i token fino
    alla parentesi di chiusura corrispondente (tracking depth).

    Returns: (inner_tokens_without_parens, close_paren_idx)
    """
    depth = 1
    inner = []
    i = open_paren_idx + 1
    while i < len(tokens):
        token = tokens[i]
        if token['type'] == 'SYMBOL' and token['text'] == '(':
            depth += 1
        elif token['type'] == 'SYMBOL' and token['text'] == ')':
            depth -= 1
            if depth == 0:
                return inner, i
        inner.append(token)
        i += 1
    return inner, i - 1


def _pre_scan_tables(tokens):
    context = None
    expecting_table = False
    outer_next = False
    base_table_key = None
    first_table_key = None
    outer_table_keys = set()
    paren_depth = 0
    subquery_depth = 0

    for i, token in enumerate(tokens):
        token_type = token['type']
        text = token['text']

        # Track parenthesis / subquery depth
        if token_type == 'SYMBOL' and text == '(':
            next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
            if next_tok and next_tok['type'] == 'KEYWORD' and next_tok['text'].upper() == 'SELECT':
                subquery_depth += 1
            else:
                paren_depth += 1
            continue

        if token_type == 'SYMBOL' and text == ')':
            if subquery_depth > 0:
                subquery_depth -= 1
            elif paren_depth > 0:
                paren_depth -= 1
            continue

        # Skip all logic inside subqueries (they have their own tables)
        if subquery_depth > 0:
            continue

        if token_type == 'KEYWORD':
            keyword = text.upper()
            if keyword == 'FROM':
                context = 'FROM'
                expecting_table = True
                outer_next = False
                continue
            if keyword == 'JOIN':
                context = 'JOIN'
                expecting_table = True
                outer_next = False
                continue
            if keyword == 'OUTER' and context in {'FROM', 'JOIN'} and expecting_table:
                outer_next = True
                continue

        if token_type == 'SYMBOL' and text == ',' and context == 'FROM':
            expecting_table = True
            outer_next = False
            continue

        if expecting_table:
            table_key = None
            if token_type == 'LOGICAL_NAME':
                table_key = _normalize_table_key(token['name'])
            elif token_type == 'IDENT':
                logical_guess = _normalize_table_key(text)
                if logical_guess in TABLE_MAP:
                    table_key = logical_guess
                else:
                    phys_result = PHYSICAL_TABLE_MAP.get(text.strip().lower())
                    table_key = phys_result[0] if isinstance(phys_result, list) and phys_result else phys_result

            if table_key:
                if first_table_key is None:
                    first_table_key = table_key
                if outer_next:
                    outer_table_keys.add(table_key)
                if base_table_key is None and not outer_next:
                    base_table_key = table_key

            expecting_table = False
            outer_next = False

    if base_table_key is None:
        base_table_key = first_table_key

    return base_table_key, outer_table_keys


def _format_physical_field(physical_table, physical_field, is_outer, context):
    if is_outer and context in {'WHERE', 'ON', 'HAVING'}:
        return f'{physical_table}.{physical_field}(+)'
    return f'{physical_table}.{physical_field}'


def _format_unqualified_field(physical_field, is_outer, context):
    if is_outer and context in {'WHERE', 'ON', 'HAVING'}:
        return f'{physical_field}(+)'
    return physical_field


def _translate_subqueries_in_sql(sql, chosen_descriptor=None):
    """
    Traduce le subquery (SELECT...) nella stringa SQL lavorando inside-out:
    prima le più interne (che non contengono parentesi), poi le più esterne.
    Usa placeholder per evitare interferenze regex durante il processo.

    Ritorna il SQL con le subquery tradotte in TecSQL.
    """
    placeholders = {}
    counter = [0]

    def replace_innermost(sql_text):
        # Trova (SELECT...senza parentesi annidate...) più interni
        pattern = re.compile(r'\(SELECT\b[^()]*\)', re.IGNORECASE)
        matches = list(pattern.finditer(sql_text))
        if not matches:
            return sql_text, False

        # Sostituisce da destra a sinistra per preservare gli indici
        for m in reversed(matches):
            inner_with_parens = m.group(0)
            inner = inner_with_parens[1:-1].strip()  # rimuove parentesi esterne

            result = translate_sql_to_tecsql(inner, chosen_descriptor)
            if result.get('success'):
                translated_inner = result['tecsql']
            else:
                translated_inner = inner  # lascia non tradotto in caso di errore

            key = f'__SUBQ_{counter[0]}__'
            counter[0] += 1
            placeholders[key] = f'({translated_inner})'
            sql_text = sql_text[:m.start()] + key + sql_text[m.end():]

        return sql_text, True

    # Itera inside-out finché non ci sono più subquery da tradurre
    changed = True
    iterations = 0
    while changed and iterations < 20:
        sql, changed = replace_innermost(sql)
        iterations += 1

    # Ripristina i placeholder in ordine inverso: i più recenti (più esterni)
    # prima, così i riferimenti a placeholder interni vengono risolti correttamente
    for key in reversed(list(placeholders.keys())):
        sql = sql.replace(key, placeholders[key])

    return sql


def _split_sql_at_top_level_unions(sql):
    """
    Divide una stringa SQL ai punti UNION/UNION ALL/INTERSECT/MINUS/EXCEPT
    di primo livello (non dentro subquery/parentesi).

    Returns: (list_of_sql_parts, list_of_operators)
    """
    depth = 0
    split_points = []

    for m in re.finditer(
        r'(?i)\b(UNION\s+ALL|UNION|INTERSECT|MINUS|EXCEPT)\b|[()]',
        sql
    ):
        ch = m.group(0)
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif depth == 0:
            op = re.sub(r'\s+', ' ', ch).upper().strip()
            split_points.append((m.start(), m.end(), op))

    if not split_points:
        return [sql], []

    parts = []
    operators = []
    prev = 0
    for start, end, op in split_points:
        parts.append(sql[prev:start].strip())
        operators.append(op)
        prev = end
    parts.append(sql[prev:].strip())

    return parts, operators


def translate_sql_to_tecsql(sql_query, chosen_descriptor=None):
    """
    Translate SQL (physical names) to TecSQL (logical names).

    Returns:
        {
            'success': True/False,
            'tecsql': '...' (if success),
            'error': '...' (if failure),
            'ambiguous': True/False,
            'candidates': [...],
            'partial_translation': True/False,
            'untranslated_fields': [...]
        }
    """
    if not sql_query or not TABLE_MAP:
        return {'success': False, 'error': 'Query vuota o dizionario non caricato'}

    normalized = normalize_query_text(sql_query)

    # Gestione UNION/INTERSECT/MINUS: divide, traduce ogni parte, ricongiunge
    parts, operators = _split_sql_at_top_level_unions(normalized)
    if len(parts) > 1:
        translated_parts = []
        for part in parts:
            result = translate_sql_to_tecsql(part, chosen_descriptor)
            if not result['success'] and not result.get('ambiguous'):
                return result  # Propaga primo errore
            if result.get('ambiguous'):
                return result  # Propaga richiesta di scelta descrittore
            translated_parts.append(result['tecsql'])

        combined = translated_parts[0]
        for op, part in zip(operators, translated_parts[1:]):
            combined = f'{combined} {op} {part}'
        return {'success': True, 'tecsql': combined, 'descriptors_used': {},
                'partial_translation': False, 'untranslated_fields': []}

    # Pre-processa subquery: traduce dentro-fuori (subquery più interne per prime)
    normalized = _translate_subqueries_in_sql(normalized, chosen_descriptor)

    extraction = _extract_fields_from_sql(normalized)
    tables = extraction['tables']
    fields_by_table = extraction['fields']
    alias_map = extraction.get('alias_map', {})

    if not tables:
        return {'success': False, 'error': 'Nessuna tabella trovata nella query'}

    # Find descriptor for each table
    descriptor_choices = {}
    untranslated_fields = []

    for table in tables:
        used_fields = fields_by_table.get(table, [])
        matches = _find_matching_descriptors(table, used_fields)

        if len(matches['exact_matches']) == 0:
            if not matches['best_match']:
                return {'success': False, 'error': f'Tabella {table} non trovata nel dizionario'}

            # Partial match: use best match but track missing fields
            descriptor_choices[table] = matches['best_match']
            partial_info = matches['partial_matches'][0]
            untranslated_fields.extend([f"{table}.{f}" for f in partial_info['missing']])

        elif len(matches['exact_matches']) == 1:
            descriptor_choices[table] = matches['exact_matches'][0]

        else:
            # Ambiguous - multiple exact matches
            # chosen_descriptor may arrive as display name ($CentroDiLavoro) or normalized key
            normalized_choice = _normalize_table_key(chosen_descriptor) if chosen_descriptor else None
            if normalized_choice and normalized_choice in matches['exact_matches']:
                descriptor_choices[table] = normalized_choice
            else:
                return {
                    'success': False,
                    'ambiguous': True,
                    'table': table,
                    # Return display names (original case) so the UI shows them correctly
                    'candidates': [TABLE_ORIGINAL_CASE.get(c, c) for c in matches['exact_matches']],
                    'fields_used': used_fields
                }

    # Translate using descriptor_choices.
    # IMPORTANT: replace TABLE.FIELD pairs FIRST (as atomic units), then replace
    # standalone table names. Doing it the other way would corrupt the table prefix
    # inside qualified fields before the field regex can match.
    tecsql = normalized

    # Step 1: Replace qualified field names (TABLE.FIELD and ALIAS.FIELD → $descriptor.LogicalField)
    # - Physical table prefix  → replaced with descriptor name (original case)
    # - Alias prefix           → kept as-is, only the field name is translated
    for table, descriptor in descriptor_choices.items():
        physical_key = table.lower()
        reverse_fields = REVERSE_FIELD_MAP.get(physical_key, {})
        descriptor_display = TABLE_ORIGINAL_CASE.get(descriptor, descriptor)

        # Valid prefixes: physical table name + any alias pointing to this table
        all_prefixes = [table]
        for alias, phys in alias_map.items():
            if phys == table:
                all_prefixes.append(alias)

        for physical_field, descriptor_map in reverse_fields.items():
            logical_field = descriptor_map.get(descriptor)
            if logical_field:
                logical_field_display = FIELD_ORIGINAL_CASE.get((descriptor, logical_field), logical_field)
                for prefix in all_prefixes:
                    pattern = re.escape(prefix) + r'\.' + re.escape(physical_field.upper())
                    if prefix.upper() == table.upper():
                        # Physical table name → replace with $Descriptor.LogicalField
                        replacement = f'{descriptor_display}.{logical_field_display}'
                    else:
                        # Alias → keep the alias, only translate the field name
                        replacement = f'{prefix}.{logical_field_display}'
                    tecsql = re.sub(pattern, replacement, tecsql, flags=re.IGNORECASE)

    # Step 2: Replace standalone table names (now that TABLE.FIELD pairs are already done)
    for table, descriptor in descriptor_choices.items():
        descriptor_display = TABLE_ORIGINAL_CASE.get(descriptor, descriptor)
        pattern = r'\b' + re.escape(table) + r'\b'
        tecsql = re.sub(pattern, descriptor_display, tecsql, flags=re.IGNORECASE)

    # Replace unqualified field names (FIELD → $descriptor.LogicalField)
    # This handles fields without table prefix (e.g., SELECT FIELD FROM TABLE)
    unqualified_fields = extraction.get('unqualified_fields', [])

    if unqualified_fields:
        # If single table, we know all unqualified fields belong to it
        if len(tables) == 1:
            table = tables[0]
            descriptor = descriptor_choices.get(table)
            if descriptor:
                physical_key = table.lower()
                reverse_fields = REVERSE_FIELD_MAP.get(physical_key, {})
                descriptor_display = TABLE_ORIGINAL_CASE.get(descriptor, descriptor)

                for unqualified_field in unqualified_fields:
                    physical_field_lower = unqualified_field.lower()
                    descriptor_map = reverse_fields.get(physical_field_lower, {})
                    logical_field = descriptor_map.get(descriptor)

                    if logical_field:
                        logical_field_display = FIELD_ORIGINAL_CASE.get((descriptor, logical_field), logical_field)
                        pattern = r'\b' + re.escape(unqualified_field) + r'\b'
                        replacement = f'{descriptor_display}.{logical_field_display}'
                        tecsql = re.sub(pattern, replacement, tecsql, flags=re.IGNORECASE)
                    else:
                        if not _is_comparison_value(tecsql, unqualified_field):
                            untranslated_fields.append(unqualified_field)
        else:
            # Multiple tables: try to find field in any table's descriptor
            for unqualified_field in unqualified_fields:
                physical_field_lower = unqualified_field.lower()
                found = False

                for table, descriptor in descriptor_choices.items():
                    physical_key = table.lower()
                    reverse_fields = REVERSE_FIELD_MAP.get(physical_key, {})
                    descriptor_map = reverse_fields.get(physical_field_lower, {})
                    logical_field = descriptor_map.get(descriptor)

                    if logical_field:
                        descriptor_display = TABLE_ORIGINAL_CASE.get(descriptor, descriptor)
                        logical_field_display = FIELD_ORIGINAL_CASE.get((descriptor, logical_field), logical_field)
                        pattern = r'\b' + re.escape(unqualified_field) + r'\b'
                        replacement = f'{descriptor_display}.{logical_field_display}'
                        tecsql = re.sub(pattern, replacement, tecsql, flags=re.IGNORECASE)
                        found = True
                        break

                if not found:
                    if not _is_comparison_value(tecsql, unqualified_field):
                        untranslated_fields.append(unqualified_field)

    return {
        'success': True,
        'tecsql': tecsql,
        'descriptors_used': descriptor_choices,
        'partial_translation': len(untranslated_fields) > 0,
        'untranslated_fields': untranslated_fields
    }


def _split_at_top_level_unions(tokens):
    """
    Divide una lista di token ai punti UNION/INTERSECT/MINUS/EXCEPT di primo livello
    (non dentro parentesi annidate).
    Gestisce UNION ALL come operatore singolo.

    Returns: (list_of_token_sublists, list_of_operators)
    """
    parts = []
    operators = []
    current = []
    paren_depth = 0
    SET_OPS = {'UNION', 'INTERSECT', 'MINUS', 'EXCEPT'}

    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token['type'] == 'SYMBOL' and token['text'] == '(':
            paren_depth += 1
            current.append(token)
        elif token['type'] == 'SYMBOL' and token['text'] == ')':
            paren_depth -= 1
            current.append(token)
        elif paren_depth == 0 and token['type'] == 'KEYWORD' and token['text'].upper() in SET_OPS:
            op = token['text'].upper()
            # Controlla UNION ALL
            if op == 'UNION' and i + 1 < len(tokens):
                next_tok = tokens[i + 1]
                if next_tok['type'] == 'KEYWORD' and next_tok['text'].upper() == 'ALL':
                    op = 'UNION ALL'
                    i += 1  # consuma ALL
            parts.append(current)
            operators.append(op)
            current = []
        else:
            current.append(token)
        i += 1

    parts.append(current)
    return parts, operators


def _strip_param_conditions(normalized_query):
    """
    Remove conditions from WHERE/HAVING clauses that reference parameter tokens
    (?name, #?name, #op?name, #between?name, etc.).
    Conditions without parameters are preserved as-is.
    If all conditions in a clause are removed, the clause keyword (WHERE/HAVING) is
    also dropped. AND/OR connectors are cleaned up automatically.
    """
    tokens = _tokenize(normalized_query)

    CLAUSE_KEYWORDS = {'WHERE', 'HAVING'}
    CLAUSE_ENDERS = {'GROUP', 'ORDER', 'HAVING', 'UNION', 'INTERSECT', 'MINUS', 'EXCEPT', 'LIMIT', 'FETCH', 'FOR'}

    result = []
    i = 0

    while i < len(tokens):
        token = tokens[i]
        ttype = token['type']
        text = token['text']

        if ttype == 'KEYWORD' and text.upper() in CLAUSE_KEYWORDS:
            clause_keyword = token
            i += 1

            # Collect clause body until a top-level clause ender or end of tokens
            clause_body = []
            depth = 0
            while i < len(tokens):
                t = tokens[i]
                if t['type'] == 'SYMBOL' and t['text'] == '(':
                    depth += 1
                    clause_body.append(t)
                    i += 1
                elif t['type'] == 'SYMBOL' and t['text'] == ')':
                    if depth == 0:
                        break  # closing paren of parent context — stop
                    depth -= 1
                    clause_body.append(t)
                    i += 1
                elif depth == 0 and t['type'] == 'KEYWORD' and t['text'].upper() in CLAUSE_ENDERS:
                    break
                else:
                    clause_body.append(t)
                    i += 1

            # Split clause body by top-level AND/OR into (connector_token, cond_tokens) pairs
            segments = []
            current = []
            connector = None
            pdepth = 0

            for t in clause_body:
                if t['type'] == 'SYMBOL' and t['text'] == '(':
                    pdepth += 1
                    current.append(t)
                elif t['type'] == 'SYMBOL' and t['text'] == ')':
                    pdepth -= 1
                    current.append(t)
                elif pdepth == 0 and t['type'] == 'KEYWORD' and t['text'].upper() in ('AND', 'OR'):
                    if current:
                        segments.append((connector, current))
                    connector = t
                    current = []
                else:
                    current.append(t)

            if current:
                segments.append((connector, current))

            # Keep only segments that contain no PARAM tokens
            kept = [
                (conn, cond) for conn, cond in segments
                if not any(t['type'] == 'PARAM' for t in cond)
            ]

            if kept:
                result.append(clause_keyword)
                for j, (conn, cond) in enumerate(kept):
                    if j > 0 and conn:
                        result.append(conn)
                    result.extend(cond)
            # If nothing kept: drop the clause keyword too (don't append anything)

            continue  # i already points past the clause body

        result.append(token)
        i += 1

    return _format_tokens(result)


def translate_tecsql(normalized_query, strip_params=False):
    """
    Entry point pubblico. Gestisce UNION/INTERSECT/MINUS traducendo ogni
    SELECT indipendentemente e ricongiungedoli.

    strip_params: if True, removes WHERE/HAVING conditions that reference
                  parameter tokens before translating.
    """
    if not normalized_query:
        raise ValueError('Query TecSql vuota')
    if not TABLE_MAP:
        raise ValueError('Dizionario TecSql non caricato. Connetti al database prima di tradurre.')

    if strip_params:
        normalized_query = _strip_param_conditions(normalized_query)

    tokens = _tokenize(normalized_query)
    parts, operators = _split_at_top_level_unions(tokens)

    if len(parts) == 1:
        return _translate_tecsql_single(normalized_query)

    # Traduce ogni SELECT indipendentemente e ricongiunge
    translated = []
    for part_tokens in parts:
        part_text = _format_tokens(part_tokens)
        translated.append(_translate_tecsql_single(part_text))

    result = translated[0]
    for op, part in zip(operators, translated[1:]):
        result = f'{result} {op} {part}'
    return result


def _pre_scan_aliases(tokens):
    """
    Pre-scan tokens to collect alias → table mappings from FROM/JOIN clauses.
    Called before the main translation loop so that aliases referenced in SELECT/WHERE
    are already resolved when the parser first encounters them.
    """
    alias_map = {}
    context = None
    expecting_table = False
    pending_alias = False
    expecting_alias = False
    last_table_logical_key = None
    last_table_physical = None
    last_table_mode = None
    subquery_depth = 0

    i = 0
    while i < len(tokens):
        token = tokens[i]
        ttype = token['type']
        text = token['text']

        if ttype == 'SYMBOL' and text == '(':
            next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
            if next_tok and next_tok['type'] == 'KEYWORD' and next_tok['text'].upper() == 'SELECT':
                subquery_depth += 1
            i += 1
            continue

        if ttype == 'SYMBOL' and text == ')':
            if subquery_depth > 0:
                subquery_depth -= 1
            i += 1
            continue

        if subquery_depth > 0:
            i += 1
            continue

        if pending_alias:
            if ttype == 'KEYWORD' and text.upper() == 'AS':
                expecting_alias = True
                pending_alias = False
                i += 1
                continue
            if ttype == 'IDENT':
                alias_map[text.lower()] = {
                    'logical_key': last_table_logical_key,
                    'physical': last_table_physical,
                    'mode': last_table_mode,
                    'outer': False
                }
                pending_alias = False
                i += 1
                continue
            pending_alias = False

        if expecting_alias:
            if ttype == 'IDENT':
                alias_map[text.lower()] = {
                    'logical_key': last_table_logical_key,
                    'physical': last_table_physical,
                    'mode': last_table_mode,
                    'outer': False
                }
                expecting_alias = False
                i += 1
                continue
            expecting_alias = False

        if ttype == 'KEYWORD':
            keyword = text.upper()
            if keyword in ('FROM', 'JOIN'):
                context = keyword
                expecting_table = True
            elif keyword in ('LEFT', 'RIGHT', 'FULL', 'INNER', 'CROSS', 'OUTER'):
                pass  # JOIN modifiers - keep expecting_table state
            elif keyword not in ('FROM', 'JOIN'):
                if context not in ('FROM', 'JOIN'):
                    expecting_table = False
            i += 1
            continue

        if ttype == 'SYMBOL' and text == ',' and context == 'FROM':
            expecting_table = True
            i += 1
            continue

        if expecting_table:
            if ttype == 'LOGICAL_NAME':
                logical_key = _normalize_table_key(token['name'])
                try:
                    physical_table = _resolve_table(token['name'])
                except ValueError:
                    physical_table = None
                last_table_logical_key = logical_key
                last_table_physical = physical_table
                last_table_mode = 'logical'
                expecting_table = False
                pending_alias = True
            elif ttype == 'IDENT':
                logical_key = _normalize_table_key(text)
                if logical_key in TABLE_MAP:
                    last_table_logical_key = logical_key
                    last_table_physical = TABLE_MAP[logical_key]
                    last_table_mode = 'logical'
                else:
                    phys_result = PHYSICAL_TABLE_MAP.get(text.strip().lower())
                    last_table_logical_key = phys_result[0] if isinstance(phys_result, list) and phys_result else phys_result
                    last_table_physical = text
                    last_table_mode = 'physical'
                expecting_table = False
                pending_alias = True

        i += 1

    return alias_map


def _translate_tecsql_single(normalized_query):
    # Parse the query, track clause context, and translate logical names.
    if not normalized_query:
        raise ValueError('Query TecSql vuota')
    if not TABLE_MAP:
        raise ValueError('Dizionario TecSql non caricato. Connetti al database prima di tradurre.')

    tokens = _tokenize(normalized_query)
    base_table_key, outer_table_keys = _pre_scan_tables(tokens)
    output = []
    context = None
    context_stack = []
    expecting_table = False
    expecting_alias = False
    pending_alias = False
    skip_next_ident = False
    as_is_mode = False
    outer_next_table = False
    alias_table_map = _pre_scan_aliases(tokens)
    tables = []
    fields = []
    last_table_physical = None
    last_table_logical_key = None
    last_table_mode = None
    last_table_outer = False

    i = 0
    while i < len(tokens):
        token = tokens[i]
        token_type = token['type']
        text = token['text']

        if as_is_mode:
            output.append(token)
            i += 1
            continue

        if token_type == 'KEYWORD' and text.upper() == 'AS':
            next_token = tokens[i + 1] if i + 1 < len(tokens) else None
            if next_token and next_token['type'] == 'KEYWORD' and next_token['text'].upper() == 'IS':
                output.append(token)
                output.append(next_token)
                as_is_mode = True
                i += 2
                continue

        if pending_alias:
            if token_type == 'KEYWORD' and text.upper() == 'AS':
                # Drop AS in FROM/JOIN context: output "TABLE alias" not "TABLE AS alias"
                expecting_alias = True
                pending_alias = False
                i += 1
                continue
            if token_type == 'IDENT':
                alias_table_map[text.lower()] = {
                    'logical_key': last_table_logical_key,
                    'physical': last_table_physical,
                    'mode': last_table_mode,
                    'outer': last_table_outer
                }
                output.append(token)
                pending_alias = False
                i += 1
                continue
            pending_alias = False

        if expecting_alias:
            if token_type == 'IDENT':
                alias_table_map[text.lower()] = {
                    'logical_key': last_table_logical_key,
                    'physical': last_table_physical,
                    'mode': last_table_mode,
                    'outer': last_table_outer
                }
                output.append(token)
                expecting_alias = False
                i += 1
                continue
            expecting_alias = False

        if skip_next_ident:
            output.append({'type': token_type, 'text': text})
            skip_next_ident = False
            i += 1
            continue

        if token_type == 'SYMBOL':
            if text == '(':
                # Detect subquery: (SELECT ...)
                next_tok = tokens[i + 1] if i + 1 < len(tokens) else None
                if next_tok and next_tok['type'] == 'KEYWORD' and next_tok['text'].upper() == 'SELECT':
                    # Collect inner tokens up to matching ')'
                    inner_tokens, close_idx = _collect_subquery_tokens(tokens, i)
                    inner_text = _format_tokens(inner_tokens)
                    # Translate recursively
                    translated_inner = _translate_tecsql_single(inner_text)
                    output.append({'type': 'SYMBOL', 'text': '('})
                    output.append({'type': 'IDENT', 'text': translated_inner})
                    output.append({'type': 'SYMBOL', 'text': ')'})
                    i = close_idx + 1
                    continue
                context_stack.append(context)
            elif text == ')' and context_stack:
                context = context_stack.pop()
            if text == ',' and context == 'FROM':
                expecting_table = True
                last_table_physical = None
                last_table_logical_key = None
                outer_next_table = False
            output.append({'type': token_type, 'text': text})
            i += 1
            continue

        if token_type == 'KEYWORD':
            keyword = text.upper()
            if keyword == 'FROM':
                context = 'FROM'
                expecting_table = True
                outer_next_table = False
            elif keyword == 'JOIN':
                context = 'JOIN'
                expecting_table = True
                outer_next_table = False
            elif keyword == 'OUTER' and context in {'FROM', 'JOIN'} and expecting_table:
                outer_next_table = True
                i += 1
                continue
            elif keyword == 'ORDER':
                context = 'ORDER'
            elif keyword == 'GROUP':
                context = 'GROUP'
            elif keyword == 'BY' and context in {'ORDER', 'GROUP'}:
                context = f'{context}_BY'
            elif keyword in {'SELECT', 'WHERE', 'ON', 'HAVING'}:
                context = keyword
            elif keyword == 'LIMIT':
                # TecSQL LIMIT n → Oracle FETCH FIRST n ROWS ONLY
                if i + 1 < len(tokens) and tokens[i + 1]['type'] == 'NUMBER':
                    n = tokens[i + 1]['text']
                    output.append({'type': 'KEYWORD', 'text': f'FETCH FIRST {n} ROWS ONLY'})
                    i += 2
                    continue
                # No number follows: keep LIMIT as-is (best-effort)
            elif keyword == 'AS' and context not in {'FROM', 'JOIN'}:
                skip_next_ident = True
            output.append({'type': token_type, 'text': text})
            i += 1
            continue

        if token_type == 'LOGICAL_TABLE_STAR':
            physical_table = _resolve_table(token['table'])
            output.append({'type': 'IDENT', 'text': f'{physical_table}.*'})
            i += 1
            continue

        if token_type == 'LOGICAL_NAME' and expecting_table:
            logical_key = _normalize_table_key(token['name'])
            physical_table = _resolve_table(token['name'])
            last_table_logical_key = logical_key
            last_table_physical = physical_table
            last_table_mode = 'logical'
            last_table_outer = outer_next_table
            if outer_next_table:
                outer_table_keys.add(logical_key)
            tables.append({'logical': token['name'], 'physical': physical_table})
            output.append({'type': 'IDENT', 'text': physical_table})
            expecting_table = False
            pending_alias = True
            outer_next_table = False
            i += 1
            continue

        if token_type == 'LOGICAL_FIELD':
            physical_table = _resolve_table(token['table'])
            physical_field = _resolve_field(token['table'], token['field'])
            is_outer = _normalize_table_key(token['table']) in outer_table_keys
            fields.append({
                'logical_table': token['table'],
                'logical_field': token['field'],
                'physical_table': physical_table,
                'physical_field': physical_field
            })
            output.append({
                'type': 'IDENT',
                'text': _format_physical_field(physical_table, physical_field, is_outer, context)
            })
            i += 1
            continue

        if token_type == 'LOGICAL_NAME':
            if not base_table_key:
                raise ValueError(f'Campo logico non risolvibile: {token["name"]}')
            physical_table = TABLE_MAP.get(base_table_key)
            field_name = token['name'][1:] if token['name'].startswith('$') else token['name']
            physical_field = _resolve_field(base_table_key, field_name)
            is_outer = base_table_key in outer_table_keys
            fields.append({
                'logical_table': base_table_key,
                'logical_field': field_name,
                'physical_table': physical_table,
                'physical_field': physical_field
            })
            output.append({
                'type': 'IDENT',
                'text': _format_unqualified_field(physical_field, is_outer, context)
            })
            i += 1
            continue

        if token_type == 'IDENT' and i + 2 < len(tokens):
            if tokens[i + 1]['type'] == 'SYMBOL' and tokens[i + 1]['text'] == '.':
                right = tokens[i + 2]
                if right['type'] in {'IDENT', 'SYMBOL'}:
                    alias_key = text.lower()
                    if alias_key in alias_table_map:
                        alias_entry = alias_table_map[alias_key]
                        physical_table = alias_entry['physical']
                        is_outer = alias_entry.get('outer', False)
                        if right['type'] == 'SYMBOL' and right['text'] == '*':
                            output.append({'type': 'IDENT', 'text': f'{physical_table}.*'})
                            i += 3
                            continue
                        if alias_entry['mode'] == 'logical':
                            logical_table = alias_entry['logical_key']
                            if not logical_table:
                                raise ValueError(f'Tabella logica non mappata per alias: {text}')
                            physical_field = _resolve_field(logical_table, right['text'])
                            output.append({
                                'type': 'IDENT',
                                'text': _format_physical_field(physical_table, physical_field, is_outer, context)
                            })
                        else:
                            output.append({
                                'type': 'IDENT',
                                'text': _format_physical_field(physical_table, right['text'], is_outer, context)
                            })
                        i += 3
                        continue

                    logical_key = _normalize_table_key(text)
                    if logical_key in TABLE_MAP:
                        physical_table = TABLE_MAP[logical_key]
                        is_outer = logical_key in outer_table_keys
                        if right['type'] == 'SYMBOL' and right['text'] == '*':
                            output.append({'type': 'IDENT', 'text': f'{physical_table}.*'})
                        else:
                            physical_field = _resolve_field(logical_key, right['text'])
                            output.append({
                                'type': 'IDENT',
                                'text': _format_physical_field(physical_table, physical_field, is_outer, context)
                            })
                        i += 3
                        continue

        if token_type == 'IDENT' and expecting_table and context in {'FROM', 'JOIN'}:
            logical_key = _normalize_table_key(text)
            if logical_key in TABLE_MAP:
                physical_table = TABLE_MAP[logical_key]
                last_table_logical_key = logical_key
                last_table_physical = physical_table
                last_table_mode = 'logical'
                last_table_outer = outer_next_table
                if outer_next_table:
                    outer_table_keys.add(logical_key)
                tables.append({'logical': text, 'physical': physical_table})
                output.append({'type': 'IDENT', 'text': physical_table})
                expecting_table = False
                pending_alias = True
            else:
                last_table_physical = text
                phys_result = PHYSICAL_TABLE_MAP.get(text.strip().lower())
                last_table_logical_key = phys_result[0] if isinstance(phys_result, list) and phys_result else phys_result
                last_table_mode = 'physical'
                last_table_outer = outer_next_table
                output.append({'type': token_type, 'text': text})
                expecting_table = False
                pending_alias = True
            outer_next_table = False
            i += 1
            continue

        output.append({'type': token_type, 'text': text})
        i += 1

    return _format_tokens(output)
