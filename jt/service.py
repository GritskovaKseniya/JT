"""Il lavoro vero, senza interfaccia: scegliere le righe, tradurle e scriverle (INSERT o UPDATE).

Una `Selection` ricorda tabella e lingue con cui e' stata caricata: chi la usa non deve rileggerle dai campi
dell'interfaccia (e' cosi' che si evita di scrivere righe nella tabella sbagliata).
"""
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List

from .config import SECONDS_PER_ROW
from .layers import level_label, user_of_layer
from .tables import EmptySourceText, SchemaError
from .undo import UndoRecord


class AmbiguousKey(Exception):
    """Una riga da aggiornare ha piu' righe con la stessa chiave nel database."""


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
    level: Any = None         # Layer scelto (None = tutti i livelli)
    other_level: list = field(default_factory=list)    # (riga, Layer) delle righe per chiavi di un altro livello: non si scrivono

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
    undo: list = field(default_factory=list)       # un UndoRecord per ogni riga scritta (lo script che annulla la corsa)


@dataclass
class PreviewRow:
    """Una riga dell'anteprima: cosa si scriverebbe, senza averlo scritto."""
    row: Any                  # la riga sorgente (serve per scrivere)
    base: dict                # codice, livello, utente, lingue, testo: come nei log
    translated: Any = None    # Translated; None se la riga si salta
    action: str = 'INSERT'    # INSERT | UPDATE | SKIP
    old: str = ''             # il testo che c'e' gia' in lingua di output (solo UPDATE)
    reason: str = ''          # perche' si salta (solo SKIP)


@dataclass
class Preview:
    """Le traduzioni gia' fatte e non ancora scritte: `write` le scrive senza richiamare Azure (che fattura i caratteri)."""
    rows: list = field(default_factory=list)
    stopped: bool = False
    failure: Any = None            # errore imprevisto: le righe fatte fino a li' restano

    def count(self, action):
        return sum(1 for row in self.rows if row.action == action)

    @property
    def inserts(self):
        return self.count('INSERT')

    @property
    def updates(self):
        return self.count('UPDATE')

    @property
    def skipped(self):
        return self.count('SKIP')

    @property
    def writable(self):
        return self.inserts + self.updates


class TranslationService:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ selezione

    def load_missing(self, spec, lan_in, lan_out, limit, level=None):
        """Le prime `limit` righe in lan_in che non hanno ancora la traduzione in lan_out."""
        spec = self.db.resolve(spec)
        self.db.close_cursors()
        cursor = self.db.open_cursor()
        cursor.execute(*spec.read_missing(lan_in, lan_out, limit, level))
        count_query, chars_query = spec.count_batch(lan_in, lan_out, limit, level)
        total = self.db.scalar(*count_query)
        chars = self.db.scalar(*chars_query) or 0
        return Selection(spec, lan_in, lan_out, 'missing', cursor, total, chars, level=level)

    def load_keys(self, spec, lan_in, lan_out, keys, level=None):
        """Le righe in lan_in con le chiavi indicate: il motore le inserira' o aggiornera' in lan_out.
        Con un livello scelto, le righe di un altro livello restano fuori (in `other_level`)."""
        spec = self.db.resolve(spec)
        self.db.close_cursors()
        columns = self._columns(spec)
        all_rows = self.db.fetch_all(*spec.read_keys(lan_in, keys))
        found = {spec.row_key(row, columns) for row in all_rows}
        rows, other_level = self._split_by_level(spec, all_rows, level)
        chars = sum(len(v) for row in rows for v in row if isinstance(v, str))
        return Selection(spec, lan_in, lan_out, 'keys', rows, len(rows), chars, columns,
                         [k for k in keys if (str(int(k)) if spec.numeric_keys else k) not in found],   # '007' = 7
                         level, other_level)

    @staticmethod
    def _split_by_level(spec, rows, level):
        """(righe del livello scelto, [(riga, Layer)] di un altro livello o di livello sconosciuto)."""
        if level is None or not spec.supports_levels:
            return rows, []
        own, other = [], []
        for row in rows:
            layer = spec.layer_of_row(row)
            if layer == level:
                own.append(row)
            else:
                other.append((row, layer))
        return own, other

    def missing_counts(self, specs, lan_in, lan_out, level=None):
        """{tabella: righe mancanti in lan_out}; None per le tabelle che non si riescono a contare."""
        counts = {}
        for spec in specs:
            try:
                counts[spec.name] = self.db.scalar(*self.db.resolve(spec).count_all(lan_in, lan_out, level=level))
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
        for row, layer in selection.other_level:        # chiavi di un altro livello: non si toccano, si scrive il motivo
            result.skipped += 1
            result.skipped_rows.append(self._other_level_entry(selection, row, layer))
        tr = self._translator_fn(translator, lan_in, lan_out)

        try:
            for row in selection.rows:
                if should_stop and should_stop():
                    result.stopped = True
                    break
                base = self._base(spec, row, lan_in, lan_out)
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

    @staticmethod
    def _translator_fn(translator, lan_in, lan_out):
        """La funzione `tr(testo, required=False)` che le tabelle usano per tradurre un testo."""
        def tr(text, required=False):
            if text is None:
                if required:
                    raise EmptySourceText('empty source text')
                return None
            if not text.strip():
                return text              # niente da tradurre: inutile chiamare Azure
            return translator.translate(text, lan_in, lan_out)
        return tr

    @staticmethod
    def _base(spec, row, lan_in, lan_out):
        """Cio' che i log dicono di una riga: codice, livello, utente che si scrive (le righe CT e CW si ritrovano da qui)."""
        code, source_text = spec.log_info(row)
        layer = spec.layer_of_row(row)
        return {'date': None, 'code': code, 'level': level_label(layer) if layer else '',
                'user': user_of_layer(layer), 'lng_in': lan_in, 'lng_out': lan_out, 'input': source_text}

    # ------------------------------------------------------------ anteprima: tradurre prima, scrivere dopo

    def preview(self, selection, translator, on_progress=None, should_stop=None):
        """Traduce le righe della selezione SENZA scrivere niente: per ognuna dice cosa si farebbe (INSERT, UPDATE, SKIP).
        I risultati si conservano in un `Preview`: `write` li scrive senza richiamare Azure (si paga una volta sola)."""
        spec, lan_in, lan_out = selection.spec, selection.lan_in, selection.lan_out
        preview, counter = Preview(), RunResult()           # il secondo serve solo ai contatori dell'avanzamento
        started, done = time.time(), 0
        for row, layer in selection.other_level:            # chiavi di un altro livello: si vedono, ma non si scrivono
            entry = self._other_level_entry(selection, row, layer)
            reason = entry.pop('reason')
            preview.rows.append(PreviewRow(row, entry, action='SKIP', reason=reason))
            counter.skipped += 1
        tr = self._translator_fn(translator, lan_in, lan_out)
        try:
            for row in selection.rows:
                if should_stop and should_stop():
                    preview.stopped = True
                    break
                base = self._base(spec, row, lan_in, lan_out)
                try:
                    translated = spec.translate_row(row, tr)
                except Exception as e:
                    print(f'[WARNING!] Problem with Azure services: {e}', flush=True)
                    preview.rows.append(PreviewRow(row, base, action='SKIP', reason=str(e)))
                    counter.skipped += 1
                else:
                    planned = self._plan(selection, row, base, translated)
                    preview.rows.append(planned)
                    if planned.action == 'UPDATE':
                        counter.updates += 1
                    else:
                        counter.inserts += 1
                done += 1
                if on_progress:
                    on_progress(self._progress(done, selection.total, counter, started))
        except Exception as e:                  # imprevisto: le righe fatte restano nell'anteprima
            print(e)
            preview.failure = e
        return preview

    def _plan(self, selection, row, base, translated):
        """INSERT o UPDATE (con il testo di prima) per una riga tradotta. Solo letture."""
        if not selection.update_mode:
            return PreviewRow(row, base, translated, 'INSERT')
        spec = selection.spec
        target = spec.update_target(row, selection.lan_out, translated.values, selection.columns)
        try:
            existing = self._existing(spec, target)
        except AmbiguousKey as e:
            return PreviewRow(row, base, translated, 'SKIP', reason=str(e))
        if existing is None:
            return PreviewRow(row, base, translated, 'INSERT')
        return PreviewRow(row, base, translated, 'UPDATE', old=self._old_text(translated, target, existing))

    def _existing(self, spec, target):
        """I valori che la riga ha adesso in lingua di output ({colonna: valore}, con utente e data se la tabella li ha),
        oppure None se non c'e'."""
        conditions = ' AND '.join(f'{col} = :w{i}' for i, col in enumerate(target.where))
        binds = {f'w{i}': value for i, value in enumerate(target.where.values())}
        columns = list(target.sets) + list(target.audit)
        found = self.db.fetch_all(f"SELECT {', '.join(columns)} FROM {spec.name} WHERE {conditions}", binds)
        if len(found) > 1:                  # la chiave non e' unica: un UPDATE le cambierebbe tutte e l'undo non le distingue
            raise AmbiguousKey(f'{len(found)} rows in {spec.name} have the same key ({binds}): not updated')
        return dict(zip(columns, found[0])) if found else None

    @staticmethod
    def _old_text(translated, target, existing):
        """Il testo di prima che corrisponde al testo principale della traduzione (altrimenti il primo che c'e')."""
        for column, value in target.sets.items():
            if value is not None and value == translated.primary:
                return str(existing.get(column) or '')
        return str(next((existing[column] for column in target.sets if existing.get(column)), '') or '')

    def write(self, selection, preview, on_progress=None, should_stop=None):
        """Scrive le traduzioni di un'anteprima, senza richiamare Azure. Una riga alla volta, con commit a ogni riga;
        le righe SKIP finiscono nel log delle righe saltate con il loro motivo."""
        result = RunResult()
        started, done, total = time.time(), 0, len(preview.rows)
        try:
            for planned in preview.rows:
                if should_stop and should_stop():
                    result.stopped = True
                    break
                if planned.action == 'SKIP':
                    result.skipped += 1
                    result.skipped_rows.append({**planned.base, 'date': datetime.now().isoformat(),
                                                'reason': planned.reason})
                else:
                    self._write(selection, planned.row, planned.translated, planned.base, result)
                done += 1
                if on_progress:
                    on_progress(self._progress(done, total, result, started))
        except Exception as e:           # imprevisto: le righe gia' scritte restano nel risultato e nei log
            print(e)
            result.failure = e
        return result

    @staticmethod
    def _other_level_entry(selection, row, layer):
        code, source_text = selection.spec.log_info(row)
        actual = f'level {layer.name}' if layer else 'unknown level'
        return {'date': datetime.now().isoformat(), 'code': code, 'level': level_label(layer) if layer else 'unknown',
                'user': '', 'lng_in': selection.lan_in, 'lng_out': selection.lan_out, 'input': source_text,
                'reason': f'key {code} is {actual}, selected level is {selection.level.name}'}

    def _write(self, selection, row, translated, base, result):
        spec, lan_out = selection.spec, selection.lan_out
        now = datetime.now().isoformat()
        try:
            columns = selection.columns
            if spec.needs_columns and not columns:           # i nomi delle colonne servono a riconoscere la riga (in cache)
                columns = self._columns(spec)
            try:
                target = spec.update_target(row, lan_out, translated.values, columns)    # come si riconosce la riga
            except Exception as e:           # senza non c'e' modo di annullare questa riga: meglio non scriverla
                raise RuntimeError(f'cannot identify the row for the undo script: {e}') from e
            action, existing = 'insert', None
            if selection.update_mode:
                existing = self._existing(spec, target)       # una lettura: c'e' gia' e cosa c'era
            if existing is not None:
                self.db.execute(*self._update_statement(spec, target, spec.user_sql(row)))
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
        old_output = self._old_text(translated, target, existing) if existing is not None else ''
        result.undo.append(UndoRecord(spec.name, action, dict(target.where), dict(existing) if existing is not None else {}))
        result.successes.append({'date': now, 'action': action, 'code': base['code'], 'level': base['level'],
                                 'user': base['user'], 'lng_in': base['lng_in'], 'lng_out': base['lng_out'],
                                 'input': base['input'], 'output': translated.primary, 'old_output': old_output})

    def _update_statement(self, spec, target, user_sql):
        """(sql, binds) dell'UPDATE di una riga che esiste gia' in lingua di output."""
        conditions = ' AND '.join(f'{col} = :w{i}' for i, col in enumerate(target.where))
        binds = {f'w{i}': value for i, value in enumerate(target.where.values())}
        parts = [f'{col} = :s{i}' for i, col in enumerate(target.sets)]
        binds.update({f's{i}': value for i, value in enumerate(target.sets.values())})
        if len(target.audit) == 2:
            parts += [f'{target.audit[0]} = {user_sql}', f'{target.audit[1]} = sysdate']
        return f"UPDATE {spec.name} SET {', '.join(parts)} WHERE {conditions}", binds

    @staticmethod
    def _progress(done, total, result, started):
        elapsed = time.time() - started
        return Progress(done, total, result.inserts, result.updates, len(result.errors), result.skipped,
                        round(elapsed / 60, 2), round(elapsed / done * (total - done) / 60, 2) if done else 0)
