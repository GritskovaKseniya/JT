"""Passo 2: scelta di tabella e lingue, caricamento della selezione e traduzione."""
import os
import tkinter as tk
from tkinter import ttk

from ..logs import write_run_logs
from ..runner import DONE, ERROR, PROGRESS
from ..tables import TooManyKeys, get_table
from .scale import pad, px
from .secret import open_secret_panel
from .texts import describe_duration, fmt_count, reason, rows
from .theme import FONT, PALETTE
from .widgets import StatusBar, ToolTip, WrapTracker, coming_soon

POLL_MS = 100            # ogni quanto l'interfaccia legge gli avanzamenti del thread di traduzione

KEYS_HINT = {
    'title': 'Update by keys',
    'intro': 'Regenerate only the listed entries: UPDATE if present, INSERT if missing. "Max rows" is ignored.',
    'rows': [
        ('FW_STRINGS\nFW_FIELD_STRINGS', 'String ids, e.g. 100000, 100001'),
        ('FW_DOCU_NODES_T', 'Node ids'),
        ('FW_OBJ_DESCRS', 'Object ids (all fields of the object)'),
        ('FW_OPZIONI, _DUE,\n_TRE, _INT', 'Option names, e.g. ProcessiLunghi (all their codes). Pick the table that holds them.'),
        ('FWK_STRINGS', 'String codes'),
    ],
    'footer': 'Leave empty to translate the missing rows.',
}

PROGRESS_HINT = {
    'title': 'Progress',
    'rows': [('Processed', 'Rows handled so far, out of the rows loaded.'),
             ('Inserted / Updated', 'Rows written to the database.'),
             ('Errors', 'The database write failed. They are listed in the error log.'),
             ('Skipped', 'No source text, or Azure could not translate it.')],
}


def _pick(value, options, default_index=0):
    """Il valore salvato vale solo se e' ancora tra le scelte possibili; altrimenti si usa quella predefinita."""
    if value in options:
        return value
    return options[min(default_index, len(options) - 1)] if options else ''


class TranslationScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        self.selection = None          # selezione caricata con "Load": tabella e lingue sono salvate al suo interno
        self.running = False
        self.counts = {}
        self._update_run = False
        self._stopping = False
        self._poll_job = self._counting_job = None
        self.entries = app.available_tables()

        languages = app.catalog.languages()
        descriptions = [entry['description'] for entry in self.entries]
        saved = app.settings.last_query()
        self.var_in = tk.StringVar(self, value=_pick(saved.get('linput'), languages))
        self.var_out = tk.StringVar(self, value=_pick(saved.get('loutput'), languages, 1))
        self.var_table = tk.StringVar(self, value=_pick(saved.get('table'), descriptions))
        self.var_max = tk.StringVar(self, value='1')
        self.var_keys = tk.StringVar(self, value='')

        self._build_languages(languages)
        self._build_selection(descriptions)
        self._build_actions()
        self._build_progress()
        coming_soon(self, 'Translation of the CT (customizations), CW (cross-cutting integrations) and '
                          'CC (customer descriptor changes) levels.', self.wrap).pack(fill='x', pady=(px(10), 0))
        self._build_hidden_button()

        # qualsiasi modifica ai campi rende non valida la selezione gia' caricata
        for var in (self.var_in, self.var_out, self.var_table, self.var_max, self.var_keys):
            var.trace_add('write', self._invalidate)
        if self.entries:
            self._counting_job = self.after(150, self.refresh_missing)
        else:
            self.load_button.config(state='disabled')
            self.label_missing.config(text='No table available.')
            self.status.show('error', 'None of the configured tables exist in this database. Check Data/tables.json.')

    def destroy(self):
        for job in (self._counting_job, self._poll_job):
            if job is not None:
                try:
                    self.after_cancel(job)
                except (AttributeError, tk.TclError):
                    pass                 # gia' partito o annullato
        super().destroy()

    # ------------------------------------------------------------------ costruzione

    def _build_languages(self, languages):
        card = ttk.LabelFrame(self, text='LANGUAGES', style='Card.TLabelframe', padding=px(12))
        card.pack(fill='x')
        card.columnconfigure(0, weight=1)
        card.columnconfigure(2, weight=1)
        ttk.Label(card, text='From', style='Muted.TLabel').grid(row=0, column=0, sticky='w')
        ttk.Label(card, text='To', style='Muted.TLabel').grid(row=0, column=2, sticky='w')
        self.cmb_in = ttk.Combobox(card, width=14, textvariable=self.var_in, values=languages, state='readonly')
        self.cmb_in.grid(row=1, column=0, sticky='ew')
        ttk.Label(card, text='→', font=(FONT, 14, 'bold'), foreground=PALETTE['accent']).grid(row=1, column=1, padx=px(10))
        self.cmb_out = ttk.Combobox(card, width=14, textvariable=self.var_out, values=languages, state='readonly')
        self.cmb_out.grid(row=1, column=2, sticky='ew')
        self.cmb_in.bind('<<ComboboxSelected>>', self.refresh_missing)
        self.cmb_out.bind('<<ComboboxSelected>>', self.refresh_missing)

    def _build_selection(self, descriptions):
        card = ttk.LabelFrame(self, text='WHAT TO TRANSLATE', style='Card.TLabelframe', padding=px(12))
        card.pack(fill='x', pady=(px(10), 0))
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text='Table').grid(row=0, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
        self.cmb_table = ttk.Combobox(card, textvariable=self.var_table, values=descriptions, state='readonly')
        self.cmb_table.grid(row=0, column=1, sticky='ew', pady=px(5))
        self.cmb_table.bind('<<ComboboxSelected>>', self.update_missing_label)

        self.label_missing = tk.Label(card, text='Counting missing translations...', bg=PALETTE['bg'],
                                      fg=PALETTE['muted'], font=(FONT, 9), wraplength=px(340), justify='left',
                                      anchor='nw')
        self.label_missing.grid(row=1, column=0, columnspan=2, sticky='w', pady=(0, px(4)))
        self.wrap.add(self.label_missing, 80)
        ToolTip(self.label_missing, self.missing_hint)

        ttk.Label(card, text='Max rows').grid(row=2, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
        # solo cifre: non si puo' scrivere (ne' incollare) altro; 'Load' controlla che sia almeno 1
        self.entry_max = ttk.Entry(card, width=10, textvariable=self.var_max, validate='key',
                                   validatecommand=(self.register(self._digits_only), '%P'))
        self.entry_max.grid(row=2, column=1, sticky='w', pady=px(5))

        label_keys = ttk.Label(card, text='Update by keys  (?)')
        label_keys.grid(row=3, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
        self.entry_keys = ttk.Entry(card, textvariable=self.var_keys)
        self.entry_keys.grid(row=3, column=1, sticky='ew', pady=px(5))
        ToolTip(label_keys, KEYS_HINT)
        ToolTip(self.entry_keys, KEYS_HINT)
        for entry in (self.entry_max, self.entry_keys):
            entry.bind('<Return>', lambda _e: self.load())

    @staticmethod
    def _digits_only(proposed):
        return proposed == '' or (proposed.isascii() and proposed.isdigit())

    def _build_actions(self):
        buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=px(12))
        self.load_button = ttk.Button(buttons, text='Load', style='Secondary.TButton', command=self.load)
        self.load_button.pack(side='left', expand=True, fill='x', padx=(0, px(6)))
        self.translate_button = ttk.Button(buttons, text='Translate', style='Primary.TButton', state='disabled',
                                           command=self.translate)
        self.translate_button.pack(side='left', expand=True, fill='x', padx=(px(6), 0))
        self.status = StatusBar(self, 'Load the data for the translation.', on_change=self.app.fit_window)
        self.status.pack(fill='x')
        self.wrap.add(self.status, 95)

    def _build_progress(self):
        card = ttk.LabelFrame(self, text='PROGRESS', style='Card.TLabelframe', padding=px(12))
        card.pack(fill='x', pady=(px(12), 0))
        self.progress = ttk.Progressbar(card, mode='determinate', maximum=1, value=0)
        self.progress.pack(fill='x')
        self.label_bar = ttk.Label(card, text='Waiting to start', style='Muted.TLabel')
        self.label_bar.pack(anchor='w', pady=(px(8), 0))
        self.label_time = ttk.Label(card, text='Elapsed time: --', style='Muted.TLabel')
        self.label_time.pack(anchor='w')
        ToolTip(self.label_bar, PROGRESS_HINT)

    def _build_hidden_button(self):
        # pulsante nascosto (easter egg), mimetizzato con lo sfondo
        self.hidden_button = tk.Button(self, text='', bd=0, highlightthickness=0, bg=PALETTE['bg'],
                                       activebackground=PALETTE['border'],
                                       command=lambda: open_secret_panel(self.app, self.hidden_button))
        self.hidden_button.place(x=0, rely=1.0, anchor='sw', width=px(6), height=px(6))

    # ------------------------------------------------------------------- selezione

    def _current(self):
        """(tabella, lingua sorgente, lingua di output) scelte nei campi. KeyError se qualcosa non e' valido."""
        catalog = self.app.catalog
        return (get_table(catalog.table_name(self.var_table.get())),
                catalog.language_code(self.var_in.get()), catalog.language_code(self.var_out.get()))

    def _invalidate(self, *_):
        if self.running or self.selection is None:
            return
        self.selection = None
        self.translate_button.config(state='disabled')
        self.status.show('info', 'Selection changed. Press Load to prepare it again.')

    def _reset_progress(self):
        self.progress.config(maximum=1, value=0)
        self.label_bar.config(text='Waiting to start')
        self.label_time.config(text='Elapsed time: --')

    def load(self):
        if self.running:
            return
        self.selection = None
        self.translate_button.config(state='disabled')
        self._reset_progress()
        try:
            spec, lan_in, lan_out = self._current()
        except KeyError:
            self.status.show('error', 'Choose a table and two languages.')
            return
        if lan_in == lan_out:
            self.status.show('error', 'Choose two different languages.')
            return
        keys_text = self.var_keys.get().strip()
        if not keys_text and not self._max_rows_ok():
            self.status.show('error', 'Max rows must be a whole number of at least 1.')
            return
        self.status.show('info', 'Loading...')
        self.app.set_busy(True)
        try:
            if keys_text:
                self._load_keys(spec, lan_in, lan_out, keys_text)
            else:
                self._load_missing(spec, lan_in, lan_out)
        except Exception as e:
            print(e)
            self.status.show('error', f'Could not load the rows: {reason(e)}')
        finally:
            self.app.set_busy(False)

    def _max_rows_ok(self):
        text = self.var_max.get().strip()
        return text.isascii() and text.isdigit() and int(text) >= 1

    def _load_missing(self, spec, lan_in, lan_out):
        selection = self.app.service.load_missing(spec, lan_in, lan_out, int(self.var_max.get()))
        if not selection.total:
            self.status.show('info', 'Nothing to translate: no missing rows for this selection.')
            return
        self._accept(selection, 'ok', f'{rows(selection.total)} to translate: {describe_duration(selection.estimated_seconds)}, '
                                      f'{fmt_count(selection.chars)} characters.')

    def _load_keys(self, spec, lan_in, lan_out, keys_text):
        try:
            keys = spec.parse_keys(keys_text)
        except TooManyKeys:
            self.status.show('error', 'Too many keys: the limit is 1000.')
            return
        except ValueError as e:
            self.status.show('error', f'Not a valid key: {e}')
            return
        selection = self.app.service.load_keys(spec, lan_in, lan_out, keys)
        if not selection.total:
            self.status.show('error', f'No {self.var_in.get()} rows found for these keys.')
            return
        text = (f'Update mode: {rows(selection.total)}, {describe_duration(selection.estimated_seconds)} '
                f'for {fmt_count(selection.chars)} characters.')
        if selection.missing_keys:
            missing = selection.missing_keys
            text += f" Not found: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"
        self._accept(selection, 'warn' if selection.missing_keys else 'ok', text)

    def _accept(self, selection, state, text):
        self.selection = selection
        self.app.settings.save_last_query(self.var_in.get(), self.var_out.get(), self.var_table.get())
        self.status.show(state, text)
        self.translate_button.config(state='normal')

    # ------------------------------------------------------------------ traduzione

    def translate(self):
        selection = self.selection          # tabella e lingue sono quelle del "Load", non quelle dei campi
        if selection is None or self.running:
            return
        try:
            translator = self.app.make_translator()
        except Exception as e:
            print(e)
            self.status.show('error', f'Azure settings not found or not valid ({self.app.paths.azure}).')
            return
        self._begin_run(selection)
        service, app = self.app.service, self.app
        app.runner.start(lambda emit, should_stop: service.run(
            selection, translator, on_progress=emit, should_stop=lambda: should_stop() or app.closing))
        self._poll()

    def _begin_run(self, selection):
        self.running = self.app.translating = True
        self._stopping = False
        if self._counting_job is not None:      # un conteggio ancora in attesa userebbe la connessione insieme al thread
            self.after_cancel(self._counting_job)
            self._counting_job = None
        self._update_run = selection.update_mode
        self._lock(True)
        self.translate_button.config(text='Stop', style='Danger.TButton', command=self.stop, state='normal')
        self.progress.config(maximum=max(selection.total, 1), value=0)
        self.status.show('info', 'Translating... you can press Stop at any time.')

    def stop(self):
        """Ferma la traduzione dopo la riga in corso (le righe gia' scritte restano nel database)."""
        if not self.running or self._stopping:
            return
        self._stopping = True
        self.app.runner.stop()
        self.translate_button.config(state='disabled')
        self.status.show('warn', 'Stopping after the current row...')

    def on_close_requested(self):
        self._stopping = True
        self.translate_button.config(state='disabled')
        self.status.show('warn', 'Closing: finishing the current row first...')

    def _poll(self):
        """Legge gli avanzamenti arrivati dal thread di traduzione; si ripete finche' non e' finita."""
        self._poll_job = None
        latest = None
        for kind, payload in self.app.runner.poll():
            if kind == PROGRESS:
                latest = payload
            elif kind in (DONE, ERROR):
                if latest is not None:
                    self._show_progress(latest)
                self._finish(payload if kind == DONE else None, payload if kind == ERROR else None)
                return
        if latest is not None:
            self._show_progress(latest)
        self._poll_job = self.after(POLL_MS, self._poll)

    def _show_progress(self, p):
        done = (f'Inserted {p.inserts} · Updated {p.updates}' if self._update_run else f'Inserted {p.inserts}')
        skipped = f' · Skipped {p.skipped}' if p.skipped else ''
        self.label_bar.config(text=f'Processed {p.done}/{p.total} · {done} · Errors {p.errors}{skipped}')
        self.label_time.config(text=f'Elapsed (min): {p.elapsed_min} · Expected (min): {p.expected_min}')
        self.progress.config(value=p.done)

    def _finish(self, result, error):
        self.running = self.app.translating = False
        self.selection = None
        if error is not None:
            print(error)
        try:
            paths = write_run_logs(result, self.app.paths.logs) if result is not None else []
        except OSError as e:                     # cartella Logs non scrivibile / file bloccato: la fine della corsa non si ferma
            print(f'Could not write the logs: {e}')
            paths = []
        self.translate_button.config(text='Translate', style='Primary.TButton', command=self.translate, state='disabled')
        if self.app.closing:
            self.app.finish_close()
            return
        self._lock(False)
        self._show_summary(result, error, paths)
        self.refresh_missing()

    def _show_summary(self, result, error, paths):
        failure = error if error is not None else (result.failure if result is not None else None)
        if failure is not None:
            text = f'The run stopped because of an error: {reason(failure)}'
            written = (result.inserts + result.updates) if result is not None else 0
            if written:
                text += f' {written} rows were written before.'
            if paths:
                text += f' Log: Logs\{os.path.basename(paths[-1])}'
            self.status.show('error', text)
            return
        written = f'{result.inserts} inserted' + (f', {result.updates} updated' if self._update_run else '')
        text = f"{'Stopped' if result.stopped else 'Done'}: {written}."
        if result.errors or result.skipped:
            text += f' {len(result.errors)} errors, {result.skipped} skipped.'
        if paths:
            text += f' Log: Logs\\{os.path.basename(paths[-1])}'
        self.status.show('warn' if (result.errors or result.skipped or result.stopped) else 'ok', text)

    def _lock(self, locked):
        """Durante la traduzione i campi non si possono cambiare."""
        for widget in (self.entry_max, self.entry_keys, self.load_button):
            widget.config(state='disabled' if locked else 'normal')
        for combo in (self.cmb_in, self.cmb_out, self.cmb_table):
            combo.config(state='disabled' if locked else 'readonly')
        self.hidden_button.config(state='disabled' if locked else 'normal')
        self.app.stepper.set_link_enabled(not locked)

    # --------------------------------------------------------- conteggio dei mancanti

    def refresh_missing(self, _event=None):
        """Conta, per ogni tabella abilitata, quante righe mancano nella lingua di output."""
        if self.running:
            return                               # durante la traduzione la connessione e' del thread
        try:
            if not self.app.db.connected or not self.entries:
                self.label_missing.config(text='Connect to count the missing translations.')
                return
            catalog = self.app.catalog
            lan_in, lan_out = catalog.language_code(self.var_in.get()), catalog.language_code(self.var_out.get())
            if lan_in == lan_out:
                self.counts = {}
                self.label_missing.config(text='Choose two different languages.')
                return
            self.label_missing.config(text='Counting missing translations...')
            self.app.set_busy(True)
            self.counts = self.app.service.missing_counts([get_table(e['table']) for e in self.entries], lan_in, lan_out)
        except Exception as e:
            print(f'Count failed: {e}')
        finally:
            self.app.set_busy(False)
        self.update_missing_label()

    def update_missing_label(self, _event=None):
        if not self.counts:
            return
        try:
            table = self.app.catalog.table_name(self.var_table.get())
        except KeyError:
            return
        failed = [name for name, n in self.counts.items() if n is None]
        if len(failed) == len(self.counts):
            self.label_missing.config(text='Could not count the missing translations (see the console).',
                                      fg=PALETTE['warn'])
            return
        total = sum(n for n in self.counts.values() if n)
        text = (f'Missing in {self.var_out.get()}: {fmt_count(self.counts.get(table))} in this table, '
                f'{fmt_count(total)} in all tables')
        if failed:
            text += ' (some tables could not be counted)'
        self.label_missing.config(text=text, fg=PALETTE['warn'] if failed else PALETTE['accent'] if total else PALETTE['ok'])

    def missing_hint(self):
        rows = [(e['description'], fmt_count(self.counts.get(e['table']))) for e in self.entries
                if e['table'] in self.counts]
        return {'title': f'Missing translations: {self.var_in.get()} → {self.var_out.get()}',
                'rows': rows or [('-', 'not counted yet')]}
