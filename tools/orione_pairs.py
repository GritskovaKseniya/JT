"""Le coppie TecSQL -> SQL Oracle che Orione dichiara corrette nei suoi test, per controllare il traduttore di JT.

Orione (il framework Java di Jflex) ha il vero traduttore TecSQL -> SQL (`it.tec.framework.sql.parser`, grammatica in
`parser\\TecSqlParser.cup`) e i suoi test (`TecSqlParserTest.java`) dicono, query per query, che SQL deve uscire. Questo
strumento le estrae e prepara due file per i test di JT (`tests\\orione_pairs.json` e `tests\\orione_dictionary.json`):

    .venv\\Scripts\\python.exe tools\\orione_pairs.py pairs                       le coppie, da TecSqlParserTest.java
    .venv\\Scripts\\python.exe tools\\orione_pairs.py dictionary --host H --port P --sid S --user U     (password: JT_SAMPLE_PASSWORD)
                                                                                 i descrittori usati dalle coppie, letti in sola lettura

Le coppie sono quelle per Oracle senza parametri, "servant" e sicurezza (le altre prove di Orione usano contesti che JT non ha).
"""
import argparse
import getpass
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_ORIONE = 'C:/Development/JFlex2.Orione/srcJAVA/it/tec/framework/sql/parser/TecSqlParserTest.java'
PAIRS = os.path.join(ROOT, 'tests', 'orione_pairs.json')
DICTIONARY = os.path.join(ROOT, 'tests', 'orione_dictionary.json')

STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def unescape(text):
    return text.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t').replace('\\\\', '\\')


def evaluate(expression, env):
    """Il valore di un'espressione Java fatta di stringhe, nomi di variabile e `+`; None se non si sa."""
    parts = re.split(r'\s*\+\s*(?=(?:[^"]*"[^"]*")*[^"]*$)', expression.strip())
    out = ''
    for part in parts:
        part = part.strip()
        match = STRING.fullmatch(part)
        if match:
            out += unescape(match.group(1))
        elif part in env:
            out += env[part]
        else:
            return None
    return out


def statements(body):
    """Le istruzioni Java di un metodo (separate da ';' fuori dalle stringhe)."""
    result, current, in_string = [], '', False
    for index, char in enumerate(body):
        if char == '"' and (index == 0 or body[index - 1] != '\\'):
            in_string = not in_string
        if char == ';' and not in_string:
            result.append(current.strip())
            current = ''
        else:
            current += char
    return result


def split_arguments(text):
    args, depth, current, in_string = [], 0, '', False
    for index, char in enumerate(text):
        if char == '"' and text[index - 1] != '\\':
            in_string = not in_string
        if not in_string:
            if char in '([{':
                depth += 1
            elif char in ')]}':
                depth -= 1
            elif char == ',' and depth == 0:
                args.append(current.strip())
                current = ''
                continue
        current += char
    args.append(current.strip())
    return args


def extract_pairs(path):
    """Tutte le chiamate `assertEqualsSql(tecsql, sql, builder, parametri, servant, sicurezza)` dei test di Orione."""
    with open(path, encoding='utf-8', errors='replace') as f:
        source = f.read()
    chunks = re.split(r'\n  public void (test\w+)\(\)', source)
    pairs = []
    for name, body in zip(chunks[1::2], chunks[2::2]):
        env = {}
        for statement in statements(body):
            statement = re.sub(r'//[^\n]*', '', statement).strip()
            match = re.match(r'(?:String\s+)?(\w+)\s*=\s*(.+)$', statement, re.S)
            if match and not statement.startswith('return'):
                value = evaluate(match.group(2), env)
                if value is not None:
                    env[match.group(1)] = value
                continue
            match = re.match(r'assertEqualsSql\s*\((.*)\)\s*$', statement, re.S)
            if not match:
                continue
            args = split_arguments(match.group(1))
            if len(args) < 6:
                continue
            tecsql, sql = evaluate(args[0], env), evaluate(args[1], env)
            if tecsql is not None and sql is not None:
                pairs.append({'test': name, 'tecsql': tecsql, 'sql': sql, 'builder': args[2], 'params': args[3],
                              'servant': args[4], 'security': args[5]})
    return pairs


def oracle_pairs(pairs):
    return [{'test': p['test'], 'tecsql': p['tecsql'], 'sql': p['sql']} for p in pairs
            if p['builder'].endswith('ORACLE') and p['params'] == 'null' and p['servant'] == 'false'
            and p['security'] == 'false']


def used_tables(pairs):
    names = set()
    for p in pairs:
        names.update(re.findall(r'\$(\w+)', p['tecsql']))
    return names


def write_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')


def command_pairs(args):
    pairs = oracle_pairs(extract_pairs(args.orione))
    write_json(PAIRS, pairs)
    print(f'{len(pairs)} pairs written to {PAIRS}')
    return 0


def command_dictionary(args):
    import cx_Oracle
    pairs = json.load(open(PAIRS, encoding='utf-8'))
    wanted = sorted({n.upper() for n in used_tables(pairs)})
    password = args.password or os.environ.get('JT_SAMPLE_PASSWORD') or getpass.getpass(f'Password of {args.user}: ')
    connection = cx_Oracle.connect(args.user, password, dsn=cx_Oracle.makedsn(args.host, args.port, sid=args.sid))
    try:
        cursor = connection.cursor()
        sql = ('SELECT TAB.TABLEDBNAME, FIE.DBFIELDNAME, TAB.TABLENAME, FIE.TABLEFIELDNAME, FIE.TYPE, FIE.WIDTH, FIE.DECIMALS '
               'FROM FW_TABLES TAB JOIN FW_TABLE_FIELDS FIE ON (FIE.TABLENAME = TAB.TABLENAME) ORDER BY 3, 4')
        assert sql.lstrip().upper().startswith('SELECT')           # solo lettura
        cursor.execute(sql)
        rows = [list(row) for row in cursor.fetchall() if (row[2] or '').upper() in wanted]
    finally:
        connection.close()
    write_json(DICTIONARY, [[('' if v is None else v) for v in row] for row in rows])
    print(f'{len(rows)} dictionary rows of {len({r[2] for r in rows})} tables written to {DICTIONARY}')
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    first = sub.add_parser('pairs')
    first.add_argument('--orione', default=DEFAULT_ORIONE)
    second = sub.add_parser('dictionary')
    second.add_argument('--host', required=True)
    second.add_argument('--port', default='1521')
    second.add_argument('--sid', required=True)
    second.add_argument('--user', required=True)
    second.add_argument('--password')
    args = parser.parse_args(argv)
    return command_pairs(args) if args.command == 'pairs' else command_dictionary(args)


if __name__ == '__main__':
    sys.exit(main())
