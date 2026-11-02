"""Il lavoro vero, senza interfaccia: scegliere le righe, tradurle e scriverle (INSERT o UPDATE).

Una `Selection` ricorda tabella e lingue con cui e' stata caricata: chi la usa non deve rileggerle dai campi
dell'interfaccia (e' cosi' che si evita di scrivere righe nella tabella sbagliata).
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List

from .config import SECONDS_PER_ROW
from .tables import MARK, EmptySourceText, SchemaError


@dataclass
class Selection:
    spec: Any                 # TableSpec con i nomi colonna risolti
    lan_in: str
    lan_out: str
    mode: str                 # 'missing' (righe senza traduzione) oppure 'keys' (update per chiavi)
    rows: Any                 # cursore (missing) o lista (keys)
    total: int
    chars: int
    columns: List[str] = field(default_factory=list)
    missing_keys: List[str] = field(default_factory=list)

    @property
    def update_mode(self):
        return self.mode == 'keys'

    @property
    def estimated_seconds(self):
        return self.total * SECONDS_PER_ROW

    @property
    def estimated_minutes(self):
        return round(self.estimated_seconds / 60, 1)


@dataclass
class Progress:
    done: int
    total: int
    inserts: int
    updates: int
    errors: int
    skipped: int
    elapsed_min: float
    expected_min: float


@dataclass
class RunResult:
    successes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    skipped_rows: list = field(default_factory=list)      # righe non tradotte (Azure o testo vuoto), con il motivo
    inserts: int = 0
    updates: int = 0
    skipped: int = 0
    stopped: bool = False
    failure: Any = None            # errore imprevisto che ha interrotto la corsa (le righe gia' scritte restano qui)


class TranslationService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ selezione

    def load_missing(self, spec, lan_in, lan_out, limit):
        """Le prime `limit` righe in lan_in che non hanno ancora la traduzione in lan_out."""
        spec = self.db.resolve(spec)
        self.db.close_cursors()
        cursor = self.db.open_cursor()
        cursor.execute(*spec.read_missing(lan_in, lan_out, limit))
        count_query, chars_query = spec.count_batch(lan_in, lan_out, limit)
        total = self.db.scalar(*count_query)
        chars = self.db.scalar(*chars_query) or 0
        return Selection(spec, lan_in, lan_out, 'missing', cursor, total, chars)

    def load_keys(self, spec, lan_in, lan_out, keys):
        """Le righe in lan_in con le chiavi indicate: il motore le inserira' o aggiornera' in lan_out."""
        spec = self.db.resolve(spec)
        self.db.close_cursors()
        columns = self._columns(spec)
        rows = self.db.fetch_all(*spec.read_keys(lan_in, keys))
        found = {spec.row_key(row, columns) for row in rows}
        chars = sum(len(v) for row in rows for v in row if isinstance(v, str))
        return Selection(spec, lan_in, lan_out, 'keys', rows, len(rows), chars, columns,
                         [k for k in keys if (str(int(k)) if spec.numeric_keys else k) not in found])   # '007' = 7

    def missing_counts(self, specs, lan_in, lan_out):
        """{tabella: righe mancanti in lan_out}; None per le tabelle che non si riescono a contare."""
        counts = {}
        for spec in specs:
            try:
                counts[spec.name] = self.db.scalar(*self.db.resolve(spec).count_all(lan_in, lan_out))
            except Exception as e:
                print(f'Count failed for {spec.name}: {e}')
                counts[spec.name] = None
        return counts

    def _columns(self, spec):
        try:
            return self.db.columns(spec.name)
        except Exception:
            if spec.needs_columns:
                raise
            return []         # servono solo per le colonne utente/data dell'UPDATE: senza, si aggiorna solo il testo

    # ----------------------------------------------------------------- esecuzione

    def run(self, selection, translator, on_progress=None, should_stop=None):
        """Traduce e scrive tutte le righe della selezione, una alla volta, con commit a ogni riga."""
        spec, lan_in, lan_out = selection.spec, selection.lan_in, selection.lan_out
        result = RunResult()
        started = time.time()
        done = 0

        def tr(text, required=False):
            if text is None:
                if required:
                    raise EmptySourceText('empty source text')
                return None
            if not text.strip():
                return text              # niente da tradurre: inutile chiamare Azure
            return translator.translate(text, lan_in, lan_out)

        try:
            for row in selection.rows:
                if should_stop and should_stop():
                    result.stopped = True
                    break
                code, source_text = spec.log_info(row)
                base = {'date': None, 'code': code, 'lng_in': lan_in, 'lng_out': lan_out, 'input': source_text}
                try:
                    translated = spec.translate_row(row, tr)
                except Exception as e:
                    print(f'[WARNING!] Problem with Azure services: {e}', flush=True)
                    result.skipped += 1
                    result.skipped_rows.append({**base, 'date': datetime.now().isoformat(), 'reason': str(e)})
                else:
                    self._write(selection, row, translated, base, result)
                done += 1
                if on_progress:
                    on_progress(self._progress(done, selection.total, result, started))
        except Exception as e:           # imprevisto: le righe gia' scritte restano nel risultato e nei log
            print(e)
            result.failure = e
        return result

    def _write(self, selection, row, translated, base, result):
        spec, lan_out = selection.spec, selection.lan_out
        now = datetime.now().isoformat()
        try:
            action, statement = 'insert', None
            if selection.update_mode:
                statement = self._update_statement(spec, spec.update_target(row, lan_out, translated.values,
                                                                            selection.columns))
            if statement:
                self.db.execute(*statement)
                action = 'update'
            else:
                self.db.execute(*spec.insert(row, lan_out, translated.values))
            self.db.commit()
        except Exception as e:
            print(e)
            self.db.rollback()           # niente righe a meta': il commit della riga dopo non le confermi per sbaglio
            result.errors.append({**base, 'date': now, 'reason': ' '.join(str(e).split())})     # il motivo dato dal database
            return
        if action == 'update':
            result.updates += 1
        else:
            result.inserts += 1
        result.successes.append({'date': now, 'action': action, 'code': base['code'], 'lng_in': base['lng_in'],
                                 'lng_out': base['lng_out'], 'input': base['input'], 'output': translated.primary})

    def _update_statement(self, spec, target):
        """(sql, binds) dell'UPDATE se la riga esiste gia' in lingua di output, altrimenti None (-> INSERT)."""
        conditions = ' AND '.join(f'{col} = :w{i}' for i, col in enumerate(target.where))
        binds = {f'w{i}': value for i, value in enumerate(target.where.values())}
        if self.db.scalar(f'SELECT COUNT(*) FROM {spec.name} WHERE {conditions}', binds) == 0:
            return None
        parts = [f'{col} = :s{i}' for i, col in enumerate(target.sets)]
        binds.update({f's{i}': value for i, value in enumerate(target.sets.values())})
        if len(target.audit) == 2:
            parts += [f'{target.audit[0]} = {MARK}', f'{target.audit[1]} = sysdate']
        return f"UPDATE {spec.name} SET {', '.join(parts)} WHERE {conditions}", binds

    @staticmethod
    def _progress(done, total, result, started):
        elapsed = time.time() - started
        return Progress(done, total, result.inserts, result.updates, len(result.errors), result.skipped,
                        round(elapsed / 60, 2), round(elapsed / done * (total - done) / 60, 2) if done else 0)
