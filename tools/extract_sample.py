"""Copia da un Oracle vero una piccola selezione di righe per il database di prova (solo lettura: soltanto SELECT).

    .venv\Scripts\python.exe tools\extract_sample.py --host SERVER --sid SID --user U     (la password si chiede, oppure JT_SAMPLE_PASSWORD)

Scrive `tools\sample_data.json` (e' in .gitignore: sono dati di un database vero, non vanno su GitHub). Poi:

    .venv\Scripts\python.exe tools\create_test_db.py --sample tools\sample_data.json    righe vere in piu' nel database di prova
    .venv\Scripts\python.exe tools\simulate.py --gui --sample tools\sample_data.json    la finestra di JT sul simulatore, con le righe vere

La selezione: tutte le stringhe e triplette CT e CW (poche), una parte di quelle FW, AP e CC (una ogni tanti codici), con le
loro traduzioni in tutte le lingue; le opzioni Fw... e un campione degli altri tipi; un campione dei nodi di documentazione.
"""
import argparse
import getpass
import json
import os
import sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, 'tools', 'sample_data.json')

# livello di una stringa dal codice (come jt/layers.py), per scegliere le righe
LEVEL_SQL = ("CASE WHEN {c} BETWEEN 10000 AND 99999 THEN 'FW' WHEN {c} BETWEEN 100000 AND 2999999 THEN 'AP' "
             "WHEN {c} BETWEEN 3000000 AND 3999999 THEN 'CT' WHEN {c} BETWEEN 4000000 AND 4999999 THEN 'CW' "
             "WHEN {c} BETWEEN 5000000 AND 5999999 THEN 'CK' WHEN {c} >= 9000000 THEN 'CC' ELSE 'other' END")


def _chosen_codes(table, lang_col='language'):
    """Codici scelti: tutti CT/CW/CK, e uno ogni tanti per gli altri livelli (cosi' si distribuiscono su tutto l'intervallo)."""
    level = LEVEL_SQL.format(c='code')
    return (f"SELECT DISTINCT code FROM {table} WHERE {lang_col} = 'it' AND ("
            f"{level} IN ('CT', 'CW', 'CK') OR ({level} = 'AP' AND MOD(code, 150) = 0) "
            f"OR ({level} = 'FW' AND MOD(code, 70) = 0) OR ({level} = 'CC' AND MOD(code, 6) = 0) "
            f"OR ({level} = 'other' AND MOD(code, 30) = 0))")


def _options(table):
    """Tutte le lingue dei tipi scelti: i tipi Fw..., quelli con prefisso Ct/Cw/Ck/Cc e uno ogni otto degli altri."""
    return (f"SELECT * FROM {table} WHERE tipo IN (SELECT tipo FROM (SELECT tipo, ROWNUM n FROM "
            f"(SELECT DISTINCT tipo FROM {table} WHERE lingua = 'it' ORDER BY tipo)) "
            f"WHERE MOD(n, 8) = 0 OR tipo LIKE 'Fw%' OR tipo LIKE 'Ct%' OR tipo LIKE 'Cw%' OR tipo LIKE 'Ck%' "
            f"OR tipo LIKE 'Cc%') ORDER BY tipo, codice, lingua")


SELECTS = {
    'FW_STRINGS': f"SELECT * FROM FW_STRINGS WHERE code IN ({_chosen_codes('FW_STRINGS')}) ORDER BY code, language",
    'FW_FIELD_STRINGS': (f"SELECT * FROM FW_FIELD_STRINGS WHERE code IN ({_chosen_codes('FW_FIELD_STRINGS')}) "
                         f"ORDER BY code, language"),
    'FW_OPZIONI': _options('FW_OPZIONI'),
    'FW_OPZIONI_DUE': _options('FW_OPZIONI_DUE'),
    'FW_OPZIONI_TRE': _options('FW_OPZIONI_TRE'),
    'FW_OPZIONI_INT': _options('FW_OPZIONI_INT'),
    'FW_DOCU_NODES_T': 'SELECT * FROM FW_DOCU_NODES_T WHERE MOD(nodeid, 25) = 0 ORDER BY nodeid, lang',
    'FW_OBJ_DESCRS': 'SELECT * FROM FW_OBJ_DESCRS WHERE MOD(objid, 10) = 0 ORDER BY objid, tablename, tablefieldname, language',
}


def clean(value):
    """Un valore letto dal database in una forma che sta in JSON. Le CHAR di Oracle sono riempite di spazi: si tolgono,
    ma un campo che era solo spazi resta un blank (in Oracle '' e' NULL e un campo obbligatorio non lo accetta)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        return value.rstrip() or ' '
    return value


def read_only(sql):
    """Garanzia: da questo script non parte nient'altro che SELECT."""
    if not sql.lstrip().upper().startswith('SELECT'):
        raise ValueError(f'Only SELECT statements are allowed: {sql[:40]}')
    return sql


def build_sample(connection, selects=None, out=print):
    """{'tables': {tabella: {'columns': [nomi], 'types': [tipi], 'rows': [[valori]]}}} letto con le SELECT indicate."""
    cursor = connection.cursor()
    sample = {}
    for table, sql in (selects or SELECTS).items():
        try:
            cursor.execute(read_only(sql))
            columns = [d[0] for d in cursor.description]
            types = [getattr(d[1], 'name', str(d[1])).replace('DB_TYPE_', '') for d in cursor.description]
            rows = [[clean(v) for v in row] for row in cursor.fetchall()]
        except Exception as e:          # una tabella che non c'e' o non si legge non ferma le altre
            out(f'  {table}: skipped ({e})')
            continue
        sample[table] = {'columns': columns, 'types': types, 'rows': rows}
        out(f'  {table}: {len(rows)} rows')
    return {'tables': sample}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', default='1521')
    parser.add_argument('--sid', required=True)
    parser.add_argument('--user', required=True)
    parser.add_argument('--password', help='meglio non scriverla qui: senza, si chiede (o JT_SAMPLE_PASSWORD)')
    parser.add_argument('--out', default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    password = args.password or os.environ.get('JT_SAMPLE_PASSWORD') or getpass.getpass(f'Password of {args.user}: ')
    import cx_Oracle
    connection = cx_Oracle.connect(args.user, password, dsn=cx_Oracle.makedsn(args.host, args.port, sid=args.sid))
    try:
        print(f'Reading from {args.host}:{args.port}/{args.sid} (SELECT only)...')
        sample = build_sample(connection)
    finally:
        connection.close()
    sample['source'] = f'{args.host}:{args.port}/{args.sid}'
    sample['taken'] = datetime.now().strftime('%Y-%m-%d')
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(sample, f, ensure_ascii=False, indent=0)
    print(f'Written {args.out} ({sum(len(t["rows"]) for t in sample["tables"].values())} rows). '
          f'Not for GitHub: it is in .gitignore.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
