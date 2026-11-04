"""Passo 2: scelta di tabella e lingue, caricamento della selezione e traduzione."""
import os
import re
import tkinter as tk
from tkinter import ttk

from .. import environments
from ..layers import DEFAULT_LEVEL, LEVEL_ALL, LEVEL_CHOICES, level_label, users_written
from ..logs import write_run_logs
from ..runner import DONE, ERROR, PROGRESS
from ..tables import TooManyKeys, get_table
from .scale import pad, px
from .secret import open_secret_panel
from .texts import describe_duration, fmt_count, reason, rows, shorten
from .theme import FONT, PALETTE
from .widgets import Collapsible, StatusBar, ToolTip, WrapTracker

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
    'footer': 'Keys of a level other than the chosen one are skipped and written in the skipped log. '
              'Leave empty to translate the missing rows.',
}

LEVEL_HINT = {
    'title': 'Level',
    'intro': 'Which layer of the Jflex data to translate.',
    'rows': [('All levels', 'Every level: no filter.'),
             ('Standard', 'The standard product: strings 100000-2999999, options without a Cw/Ct/... prefix.'),
             ('CW - Integrations', 'Strings 4000000-4999999, options named Cw... Written with user ZFXINTEGR.'),
             ('CT - Customizations', 'Tecnest customizations: strings 3000000-3999999, options named Ct... '
                                     'Written with user ZFXCUSTOM.')],
    'footer': 'FW_DOCU_NODES_T and FW_OBJ_DESCRS have no levels: the field is switched off for them and they '
              'translate everything.',
}

MAX_PREVIEW_ROWS = 500          # righe mostrate nella tabella dell'anteprima (si scrivono tutte, anche le altre)

PREVIEW_HINT = {
    'title': 'Preview',
    'intro': 'Translate the loaded rows without writing anything, then check the table before it goes to the database.',
    'rows': [('Write', 'Writes exactly these translations. Azure is not called again, so you pay for the characters once.'),
             ('Discard', 'Throws the preview away. Nothing was written; press Load to start again.')],
    'footer': 'Translate (without Preview) translates and writes in one go.',
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
        self._stale_message = False    # il banner dice com'e' finito un Load senza selezione (errore, nulla da tradurre)
        self.preview = None            # l'anteprima fatta e non ancora scritta (service.Preview)
        self._shown = []               # le righe dell'anteprima nella tabella (stesso ordine)
        self._folded = []              # le sezioni che l'anteprima ha chiuso per fare posto alla tabella
        self._job = 'translate'        # cosa sta girando: translate | preview | write
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
        self.var_level = tk.StringVar(self, value=_pick(saved.get('level'), list(LEVEL_CHOICES), 1))     # Standard
        self._levelless = False        # la tabella scelta non ha livelli: il campo Level e' spento (dice 'All levels')
        self._level_before = self.var_level.get()
        self.var_max = tk.StringVar(self, value='1')
        self.var_keys = tk.StringVar(self, value='')

        self._build_languages(languages)
        self._build_selection(descriptions)
        self._build_actions()
        self._build_preview()
        self._build_progress()
        self._build_hidden_button()
        self._update_level_state()
        self._update_advanced_summary()
        self._update_summaries()

        # qualsiasi modifica ai campi rende non valida la selezione gia' caricata
        for var in (self.var_in, self.var_out, self.var_table, self.var_level, self.var_max, self.var_keys):
            var.trace_add('write', self._invalidate)
        for var in (self.var_max, self.var_keys):
            var.trace_add('write', self._update_advanced_summary)
        for var in (self.var_in, self.var_out, self.var_table, self.var_level):
            var.trace_add('write', self._update_summaries)
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

    def _section(self, title, first=False):
        """Un blocco con titolo che si chiude (aperto all'inizio). Chiuso resta una riga con un riassunto.
        Ritorna (la sezione, la scheda dove mettere i campi)."""
        section = Collapsible(self, title, expanded=True, on_toggle=self.app.fit_window)
        section.pack(fill='x', pady=(0 if first else px(8), 0))
        card = tk.Frame(section.body, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'],
                        padx=px(10), pady=px(5))
        card.pack(fill='x', pady=(px(2), 0))
        return section, card

    def _update_summaries(self, *_):
        """Il riassunto di ogni sezione (si vede anche a sezione chiusa)."""
        self.languages_section.set_summary(f'{self.var_in.get()} \u2192 {self.var_out.get()}')
        parts = [self.var_table.get()]
        if not self._levelless and self._level() is not None:
            parts.append(level_label(self._level()))
        elif not self._levelless:
            parts.append('all levels')
        try:
            missing = self.counts.get(self.app.catalog.table_name(self.var_table.get()))
        except KeyError:
            missing = None
        if missing is not None:
            parts.append(f'{fmt_count(missing)} missing')
        self.selection_section.set_summary(' \u00b7 '.join(p for p in parts if p))

    def _build_languages(self, languages):
        self.languages_section, card = self._section('LANGUAGES', first=True)
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
        self.selection_section, card = self._section('WHAT TO TRANSLATE')
        card.columnconfigure(1, weight=1)

        ttk.Label(card, text='Table').grid(row=0, column=0, sticky='w', padx=(0, px(14)), pady=px(3))
        self.cmb_table = ttk.Combobox(card, textvariable=self.var_table, values=descriptions, state='readonly')
        self.cmb_table.grid(row=0, column=1, sticky='ew', pady=px(3))
        self.cmb_table.bind('<<ComboboxSelected>>', self.on_table_selected)

        label_level = ttk.Label(card, text='Level  (?)')
        label_level.grid(row=1, column=0, sticky='w', padx=(0, px(14)), pady=px(3))
        self.cmb_level = ttk.Combobox(card, textvariable=self.var_level, values=list(LEVEL_CHOICES), state='readonly')
        self.cmb_level.grid(row=1, column=1, sticky='ew', pady=px(3))
        self.cmb_level.bind('<<ComboboxSelected>>', self.refresh_missing)
        self.level_tip = ToolTip(label_level, LEVEL_HINT, self.cmb_level)
        for event in ('<ButtonPress-1>', '<<ComboboxSelected>>'):      # il suggerimento non sta sopra l'elenco aperto
            self.cmb_level.bind(event, self.level_tip.hide, add='+')

        self.label_missing = tk.Label(card, text='Counting missing translations...', bg=PALETTE['bg'],
                                      fg=PALETTE['muted'], font=(FONT, 9), wraplength=px(340), justify='left',
                                      anchor='nw')
        self.label_missing.grid(row=2, column=0, columnspan=2, sticky='w', pady=(0, px(4)))
        self.wrap.add(self.label_missing, 80)
        ToolTip(self.label_missing, self.missing_hint)

        # "Advanced": Max rows e Update by keys. Aperta all'inizio; chiusa dice cosa c'e' dentro e si riapre da sola se
        # servono (chiavi, errore)
        self.advanced = Collapsible(card, 'Advanced', expanded=True, on_toggle=self.app.fit_window)
        self.advanced.grid(row=3, column=0, columnspan=2, sticky='ew')
        body = self.advanced.body
        body.columnconfigure(3, weight=1)                   # una riga sola: Max rows [..]  Update by keys (?) [........]
        ttk.Label(body, text='Max rows').grid(row=0, column=0, sticky='w', padx=(0, px(8)), pady=px(3))
        # solo cifre: non si puo' scrivere (ne' incollare) altro; 'Load' controlla che sia almeno 1
        self.entry_max = ttk.Entry(body, width=6, textvariable=self.var_max, validate='key',
                                   validatecommand=(self.register(self._digits_only), '%P'))
        self.entry_max.grid(row=0, column=1, sticky='w', padx=(0, px(10)), pady=px(3))

        label_keys = ttk.Label(body, text='Update by keys  (?)')
        label_keys.grid(row=0, column=2, sticky='w', padx=(0, px(8)), pady=px(3))
        self.entry_keys = ttk.Entry(body, textvariable=self.var_keys)
        self.entry_keys.grid(row=0, column=3, sticky='ew', pady=px(3))
        ToolTip(label_keys, KEYS_HINT)
        ToolTip(self.entry_keys, KEYS_HINT)
        for entry in (self.entry_max, self.entry_keys):
            entry.bind('<Return>', lambda _e: self.load())

    @staticmethod
    def _digits_only(proposed):
        return proposed == '' or (proposed.isascii() and proposed.isdigit())

    def _update_advanced_summary(self, *_):
        """Il riassunto di "Advanced" a sezione chiusa; con delle chiavi la sezione si apre (sono un'altra modalita')."""
        keys = [k for k in re.split(r'[\s,;]+', self.var_keys.get().strip()) if k]
        if keys:
            self.advanced.set_summary(f'Update by keys: {len(keys)}')
            self.advanced.expand()
        else:
            self.advanced.set_summary(f"Max rows {self.var_max.get().strip() or '-'}")

    def _build_actions(self):
        buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=px(8))
        self.load_button = ttk.Button(buttons, text='Load', style='Secondary.TButton', command=self.load)
        self.load_button.pack(side='left', expand=True, fill='x', padx=(0, px(6)))
        self.preview_button = ttk.Button(buttons, text='Preview', style='Secondary.TButton', state='disabled',
                                         command=self.run_preview)
        self.preview_button.pack(side='left', expand=True, fill='x', padx=px(6))
        ToolTip(self.preview_button, PREVIEW_HINT)
        self.translate_button = ttk.Button(buttons, text='Translate', style='Primary.TButton', state='disabled',
                                           command=self.translate)
        self.translate_button.pack(side='left', expand=True, fill='x', padx=(px(6), 0))
        self.status = StatusBar(self, 'Load the data for the translation.', on_change=self.app.fit_window)
        self.status.pack(fill='x')
        self.wrap.add(self.status, 95)

    def _build_preview(self):
        """La tabella dell'anteprima: nascosta finche' non c'e' un'anteprima (vedi _show_preview_section)."""
        self.preview_section, card = self._section('PREVIEW')
        frame = tk.Frame(card, bg=PALETTE['bg'])
        frame.pack(fill='x')
        columns = (('code', 'Code', 70, False), ('level', 'Level', 62, False), ('action', 'Action', 62, False),
                   ('source', 'Source', 130, True), ('translation', 'Translation', 130, True))
        self.preview_tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show='headings', height=7,
                                         selectmode='browse')
        for name, title, width, stretch in columns:
            self.preview_tree.heading(name, text=title, anchor='w')
            self.preview_tree.column(name, width=px(width), minwidth=px(40), stretch=stretch, anchor='w')
        bar = ttk.Scrollbar(frame, orient='vertical', command=self.preview_tree.yview)
        self.preview_tree.configure(yscrollcommand=bar.set)
        self.preview_tree.pack(side='left', fill='x', expand=True)
        bar.pack(side='right', fill='y')
        self.preview_tree.tag_configure('update', background='#fff4e0')
        self.preview_tree.tag_configure('skip', foreground=PALETTE['muted'])
        self.preview_tree.bind('<<TreeviewSelect>>', self._show_preview_detail)
        self.preview_summary = ttk.Label(card, text='', style='Muted.TLabel')
        self.preview_summary.pack(anchor='w', pady=(px(6), 0))
        self.preview_detail = tk.Label(card, text='Select a row to read it in full.', bg=PALETTE['bg'], fg=PALETTE['muted'],
                                       font=(FONT, 9), wraplength=px(340), justify='left', anchor='nw')
        self.preview_detail.pack(fill='x', pady=(px(2), 0))
        self.wrap.add(self.preview_detail, 80)
        row = ttk.Frame(card)
        row.pack(fill='x', pady=(px(8), 0))
        self.write_button = ttk.Button(row, text='Write', style='Primary.TButton', state='disabled', command=self.write)
        self.write_button.pack(side='left', expand=True, fill='x', padx=(0, px(6)))
        self.discard_button = ttk.Button(row, text='Discard', style='Secondary.TButton', state='disabled',
                                         command=self.discard)
        self.discard_button.pack(side='left', expand=True, fill='x', padx=(px(6), 0))
        self.preview_section.pack_forget()

    def _build_progress(self):
        self.progress_section, card = self._section('PROGRESS')
        self.progress = ttk.Progressbar(card, mode='determinate', maximum=1, value=0)
        self.progress.pack(fill='x')
        self.label_bar = ttk.Label(card, text='Waiting to start', style='Muted.TLabel')
        self.label_bar.pack(anchor='w', pady=(px(8), 0))
        ToolTip(self.label_bar, PROGRESS_HINT)
        # "Details" (i tempi) si apre a richiesta; il link ai log sta sulla stessa riga e si vede sempre
        self.details = Collapsible(card, 'Details', on_toggle=self.app.fit_window)
        self.details.pack(fill='x', pady=(px(2), 0))
        self.label_time = ttk.Label(self.details.body, text='Elapsed time: --', style='Muted.TLabel')
        self.label_time.pack(anchor='w', padx=(px(16), 0))
        self.link_logs = tk.Label(self.details.extra, text='Open the logs folder', bg=PALETTE['bg'], fg=PALETTE['accent'],
                                  cursor='hand2', font=(FONT, 9, 'underline'))
        self.link_logs.pack(side='right')
        self.link_logs.bind('<Button-1>', lambda _e: self.open_logs())
        ToolTip(self.link_logs, self.app.paths.logs)

    def open_logs(self):
        """Apre la cartella dei log in Esplora file (la crea se non c'e' ancora)."""
        try:
            os.makedirs(self.app.paths.logs, exist_ok=True)
            os.startfile(self.app.paths.logs)
        except OSError as e:
            self.status.show('error', f'Could not open {self.app.paths.logs}: {reason(e)}')

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

    def _level(self):
        """Il Layer scelto nel campo Level (None = All, nessun filtro)."""
        return LEVEL_CHOICES.get(self.var_level.get())

    def _update_level_state(self):
        """Le tabelle senza livelli (FW_DOCU_NODES_T, FW_OBJ_DESCRS): il campo Level si spegne e dice 'All levels'; tornando a
        una tabella con livelli rimette la scelta di prima. Ritorna True se la scelta e' cambiata (i conteggi vanno rifatti)."""
        try:
            spec = get_table(self.app.catalog.table_name(self.var_table.get()))
        except KeyError:
            return False
        levelless = not spec.supports_levels
        before = self.var_level.get()
        if levelless and not self._levelless:
            self._level_before = before
            self.var_level.set(LEVEL_ALL)
        elif self._levelless and not levelless:
            self.var_level.set(self._level_before if self._level_before in LEVEL_CHOICES else DEFAULT_LEVEL)
        self._levelless = levelless
        self.cmb_level.config(state='disabled' if levelless or self.running else 'readonly')
        return self.var_level.get() != before

    def _level_note(self, spec, level):
        """' (CT)' dopo il numero di righe da tradurre: si vede su che livello si sta per scrivere. Standard non si scrive."""
        if not spec.supports_levels:
            return ''
        if level is None:
            return ' (all levels)'
        return '' if level.name == 'AP' else f' ({level_label(level)})'

    def on_table_selected(self, _event=None):
        if self._update_level_state():
            self.refresh_missing()               # la scelta e' cambiata: i conteggi vanno rifatti
        else:
            self.update_missing_label()

    def _invalidate(self, *_):
        if self.running:
            return
        if self.selection is None:
            if self._stale_message:        # il messaggio d'errore del Load riguardava il valore di prima: non vale piu'
                self._stale_message = False
                self.status.show('info', 'Load the data for the translation.')
            return
        self.selection = None
        self._clear_preview()
        self.translate_button.config(state='disabled')
        self.preview_button.config(state='disabled')
        self.status.show('info', 'Selection changed. Press Load to prepare it again.')

    def _reset_progress(self):
        self.progress_section.set_summary('')
        self.progress.config(maximum=1, value=0)
        self.label_bar.config(text='Waiting to start')
        self.label_time.config(text='Elapsed time: --')

    def load(self):
        if self.running:
            return
        try:
            self._load()
        finally:
            self._stale_message = self.selection is None        # niente selezione: il banner e' un errore o un "niente da fare"

    def _load(self):
        self.selection = None
        self._clear_preview()
        self.translate_button.config(state='disabled')
        self.preview_button.config(state='disabled')
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
            self.advanced.expand()                           # il campo da correggere si vede
            self.status.show('error', 'Max rows must be a whole number of at least 1.')
            return
        self.status.show('info', 'Loading...')
        self.app.set_busy(True)
        level = self._level()
        try:
            if keys_text:
                self._load_keys(spec, lan_in, lan_out, keys_text, level)
            else:
                self._load_missing(spec, lan_in, lan_out, level)
        except Exception as e:
            print(e)
            self.status.show('error', f'Could not load the rows: {reason(e)}')
        finally:
            self.app.set_busy(False)

    def _max_rows_ok(self):
        text = self.var_max.get().strip()
        return text.isascii() and text.isdigit() and int(text) >= 1

    def _load_missing(self, spec, lan_in, lan_out, level):
        selection = self.app.service.load_missing(spec, lan_in, lan_out, int(self.var_max.get()), level)
        if not selection.total:
            self.status.show('info', 'Nothing to translate: no missing rows for this selection.')
            return
        self._accept(selection, 'ok', f'{rows(selection.total)} to translate{self._level_note(spec, level)}: '
                                      f'{describe_duration(selection.estimated_seconds)}, '
                                      f'{fmt_count(selection.chars)} characters.')

    def _load_keys(self, spec, lan_in, lan_out, keys_text, level):
        try:
            keys = spec.parse_keys(keys_text)
        except TooManyKeys:
            self.status.show('error', 'Too many keys: the limit is 1000.')
            return
        except ValueError as e:
            self.status.show('error', f'Not a valid key: {e}')
            return
        selection = self.app.service.load_keys(spec, lan_in, lan_out, keys, level)
        if not selection.total:
            if selection.other_level:
                self.status.show('warn', f'Nothing to translate: {self._other_level_text(selection)}')
            else:
                self.status.show('error', f'No {self.var_in.get()} rows found for these keys.')
            return
        text = (f'Update mode{self._level_note(spec, level)}: {rows(selection.total)}, '
                f'{describe_duration(selection.estimated_seconds)} '
                f'for {fmt_count(selection.chars)} characters.')
        if selection.missing_keys:
            missing = selection.missing_keys
            text += f" Not found: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}"
        if selection.other_level:
            text += f' {self._other_level_text(selection)}'
        self._accept(selection, 'warn' if selection.missing_keys or selection.other_level else 'ok', text)

    @staticmethod
    def _other_level_text(selection):
        """'Skipped, not CT: 100000 (Standard), ...': chiavi trovate ma di un altro livello (non si scrivono)."""
        spec, shown, seen = selection.spec, [], set()
        for row, layer in selection.other_level:
            key = spec.row_key(row, selection.columns)
            if key not in seen:
                seen.add(key)
                shown.append(f"{key} ({level_label(layer) if layer else 'unknown level'})")
        text = f"Skipped, not {level_label(selection.level)}: {', '.join(shown[:5])}"
        return text + ('...' if len(shown) > 5 else '')

    def _accept(self, selection, state, text):
        self.selection = selection
        self.app.settings.save_last_query(self.var_in.get(), self.var_out.get(), self.var_table.get(),
                                          self.var_level.get())
        self.status.show(state, text)
        self.translate_button.config(state='normal')
        self.preview_button.config(state='normal')

    # ------------------------------------------------------------------ traduzione

    def _make_translator(self):
        """Il traduttore Azure, oppure None (con il messaggio) se la chiave non c'e' o non vale."""
        try:
            return self.app.make_translator()
        except Exception as e:
            print(e)
            self.status.show('error', f'Azure settings not found or not valid ({self.app.paths.azure}).')
            return None

    def translate(self):
        """Traduce e scrive, una riga alla volta (senza anteprima)."""
        selection = self.selection          # tabella e lingue sono quelle del "Load", non quelle dei campi
        if selection is None or self.running or self.preview is not None:
            return
        translator = self._make_translator()
        if translator is None:
            return
        if not self._confirm_write(selection):
            self.status.show('info', 'Cancelled. Nothing was translated or written.')
            return
        self._begin_run(selection)
        service, app = self.app.service, self.app
        app.runner.start(lambda emit, should_stop: service.run(
            selection, translator, on_progress=emit, should_stop=lambda: should_stop() or app.closing))
        self._poll()

    def run_preview(self):
        """Traduce senza scrivere: poi si controlla la tabella e si sceglie Write o Discard."""
        selection = self.selection
        if selection is None or self.running or self.preview is not None:
            return
        translator = self._make_translator()
        if translator is None:
            return
        self._begin_run(selection, 'preview')
        service, app = self.app.service, self.app
        app.runner.start(lambda emit, should_stop: service.preview(
            selection, translator, on_progress=emit, should_stop=lambda: should_stop() or app.closing))
        self._poll()

    def write(self):
        """Scrive le traduzioni dell'anteprima (Azure non si richiama)."""
        selection, preview = self.selection, self.preview
        if selection is None or preview is None or self.running or not preview.writable:
            return
        if not self._confirm_write(selection, preview):
            self.status.show('info', 'Cancelled. Nothing was written: the preview is still here.')
            return
        self._begin_run(selection, 'write', total=len(preview.rows))
        service, app = self.app.service, self.app
        app.runner.start(lambda emit, should_stop: service.write(
            selection, preview, on_progress=emit, should_stop=lambda: should_stop() or app.closing))
        self._poll()

    def _confirm_write(self, selection, preview=None):
        """La conferma prima di scrivere, con un riepilogo (database, ambiente, livello, utente). La si chiede solo sul database
        prod o senza etichetta, e per confermare si scrive il nome del database: su dev e test non si chiede niente.
        Ritorna True se si puo' procedere."""
        app, spec = self.app, selection.spec
        env = app.environment
        if not environments.is_strict(env):
            return True
        info = app.db.info or {}
        database = info.get('db_name') or info.get('sid') or info.get('host') or ''
        if preview is not None:
            question = f'Write {rows(preview.writable)} to {spec.name}?'
            users = sorted({row.base['user'] for row in preview.rows if row.action != 'SKIP'})
            counts = f'{preview.inserts} insert, {preview.updates} update'
            ok_text = 'Write'
        else:
            question = f'Translate and write {rows(selection.total)} to {spec.name}?'
            users = users_written(selection.level, spec.supports_levels)
            counts = ('Rows that already have a translation are replaced.' if selection.update_mode else '')
            ok_text = 'Translate'
        if not spec.supports_levels:
            level = 'no levels (every row)'
        else:
            level = 'all levels' if selection.level is None else level_label(selection.level)
        lines = [f"Database: {database}  \u00b7  {info.get('host', '')}  \u00b7  user {info.get('user', '')}",
                 f"Environment: {environments.to_label(env)}" + ('' if env else ' (treated as prod)'),
                 f'Languages: {self.var_in.get()} \u2192 {self.var_out.get()}',
                 f"Level: {level}  \u00b7  written as user {', '.join(users)}"]
        if counts:
            lines.append(counts)
        return app.confirm_write(question, '\n'.join(lines), database or 'WRITE', ok_text)

    def discard(self):
        """Butta l'anteprima: non e' stato scritto niente. La selezione va ricaricata (le righe si leggono una volta sola)."""
        if self.running or self.preview is None:
            return
        self._clear_preview()
        self.selection = None
        self.translate_button.config(state='disabled')
        self.preview_button.config(state='disabled')
        self.status.show('info', 'Preview discarded. Nothing was written. Press Load to prepare the selection again.')

    def _begin_run(self, selection, job='translate', total=None):
        self._job = job
        self._stale_message = False
        self.running = self.app.translating = True
        self._stopping = False
        if self._counting_job is not None:      # un conteggio ancora in attesa userebbe la connessione insieme al thread
            self.after_cancel(self._counting_job)
            self._counting_job = None
        self._update_run = selection.update_mode
        self._lock(True)
        self.translate_button.config(text='Stop', style='Danger.TButton', command=self.stop, state='normal')
        self.progress.config(maximum=max(total if total is not None else selection.total, 1), value=0)
        if self.progress_section in self._folded:        # scrivendo si vuole vedere l'avanzamento
            self._folded.remove(self.progress_section)
            self.progress_section.expand(notify=False)
            self.app.fit_window()
        what = {'translate': 'Translating', 'preview': 'Previewing (nothing is written)', 'write': 'Writing'}[job]
        self.status.show('info', f'{what}... you can press Stop at any time.')

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
                self._finish_job(payload if kind == DONE else None, payload if kind == ERROR else None)
                return
        if latest is not None:
            self._show_progress(latest)
        self._poll_job = self.after(POLL_MS, self._poll)

    def _show_progress(self, p):
        skipped = f' · Skipped {p.skipped}' if p.skipped else ''
        if self._job == 'preview':
            self.label_bar.config(text=f'Previewed {p.done}/{p.total} · Insert {p.inserts} · Update {p.updates}{skipped}')
        else:
            done = (f'Inserted {p.inserts} · Updated {p.updates}' if self._update_run else f'Inserted {p.inserts}')
            self.label_bar.config(text=f'Processed {p.done}/{p.total} · {done} · Errors {p.errors}{skipped}')
        self.label_time.config(text=f'Elapsed (min): {p.elapsed_min} · Expected (min): {p.expected_min}')
        self.progress.config(value=p.done)
        self.progress_section.set_summary(f'{p.done}/{p.total}')

    def _finish_job(self, payload, error):
        """Fine del lavoro in corso: l'anteprima mostra la tabella, traduzione e scrittura mostrano il riepilogo."""
        if self._job == 'preview':
            self._finish_preview(payload, error)
        else:
            self._finish(payload, error)

    def _finish_preview(self, preview, error):
        self.running = self.app.translating = False
        self._stale_message = False
        if error is not None:
            print(error)
        self.translate_button.config(text='Translate', style='Primary.TButton', command=self.translate, state='disabled')
        if self.app.closing:
            self.app.finish_close()
            return
        self._lock(False)
        failure = error if error is not None else (preview.failure if preview is not None else None)
        if failure is not None or preview is None or preview.stopped:
            self.selection = None                    # le righe si leggono una volta sola: si ricarica
            if failure is not None:
                self.status.show('error', f'The preview stopped because of an error: {reason(failure)}. '
                                          'Nothing was written. Press Load to prepare it again.')
            else:
                self.status.show('warn', 'Preview stopped. Nothing was written. Press Load to prepare it again.')
            return
        self.preview = preview
        self._fill_preview(preview)
        self._show_preview_section()
        self._lock(False)
        counts = f'{preview.inserts} insert, {preview.updates} update, {preview.skipped} skipped'
        if preview.writable:
            self.status.show('warn' if preview.skipped else 'ok',
                             f'Preview ready: {counts}. Check the translations, then press Write.')
        else:
            self.status.show('warn', f'Nothing to write: {counts}. See the table for the reasons.')

    def _fill_preview(self, preview):
        tree = self.preview_tree
        tree.delete(*tree.get_children())
        self._shown = preview.rows[:MAX_PREVIEW_ROWS]
        for i, row in enumerate(self._shown):
            if row.action == 'SKIP':
                text, tag = f'skipped: {row.reason}', 'skip'
            else:
                text, tag = row.translated.primary or '', ('update' if row.action == 'UPDATE' else '')
            tree.insert('', 'end', iid=str(i), tags=(tag,), values=(
                row.base['code'], row.base['level'], row.action, shorten(str(row.base['input'] or ''), 60),
                shorten(text, 60)))
        shown = f' (showing the first {len(self._shown)})' if len(preview.rows) > len(self._shown) else ''
        self.preview_summary.config(text=f'{preview.inserts} insert \u00b7 {preview.updates} update \u00b7 '
                                         f'{preview.skipped} skipped{shown}')
        self.preview_detail.config(text='Select a row to read it in full.')

    def _show_preview_detail(self, _event=None):
        chosen = self.preview_tree.selection()
        if not chosen:
            return
        row = self._shown[int(chosen[0])]
        base = row.base
        lines = [f"{base['code']} \u00b7 level {base['level'] or '-'} \u00b7 user {base['user'] or '-'} \u00b7 {row.action}",
                 f"From: {shorten(str(base['input'] or ''), 300)}"]
        if row.action == 'SKIP':
            lines.append(f'Skipped: {row.reason}')
        else:
            lines.append(f"To: {shorten(row.translated.primary or '', 300)}")
            if row.action == 'UPDATE':
                lines.append(f'Was: {shorten(row.old, 300)}')
        self.preview_detail.config(text='\n'.join(lines))

    def _show_preview_section(self):
        if not self.preview_section.winfo_manager():
            self.preview_section.pack(fill='x', pady=(px(8), 0), before=self.progress_section)
        # chi controlla la tabella non ha bisogno dei campi: si chiudono (il riassunto resta in riga) per fare posto
        # e si riaprono da soli quando l'anteprima finisce (_clear_preview)
        self._folded = [section for section in (self.languages_section, self.selection_section, self.progress_section)
                        if section.expanded]
        for section in self._folded:
            section.collapse(notify=False)
        self.app.fit_window()

    def _clear_preview(self):
        """Toglie l'anteprima (e la tabella): dopo la scrittura, Discard, un nuovo Load o un campo cambiato."""
        self.preview = None
        self._shown = []
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.write_button.config(state='disabled')
        self.discard_button.config(state='disabled')
        refit = bool(self._folded) or bool(self.preview_section.winfo_manager())
        for section in self._folded:
            section.expand(notify=False)
        self._folded = []
        if self.preview_section.winfo_manager():
            self.preview_section.pack_forget()
        if refit:
            self.app.fit_window()

    def _finish(self, result, error):
        self.running = self.app.translating = False
        self._stale_message = False                  # il riepilogo della corsa resta finche' non si fa un altro Load
        self.selection = None
        self._clear_preview()
        self.preview_button.config(state='disabled')
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
        if result.errors:
            text += f"\nFirst error (code {result.errors[0]['code']}): {shorten(result.errors[0]['reason'], 160)}"
        self.status.show('warn' if (result.errors or result.skipped or result.stopped) else 'ok', text)

    def _lock(self, locked):
        """Durante la traduzione i campi non si possono cambiare."""
        for widget in (self.entry_max, self.entry_keys, self.load_button):
            widget.config(state='disabled' if locked else 'normal')
        for combo in (self.cmb_in, self.cmb_out, self.cmb_table):
            combo.config(state='disabled' if locked else 'readonly')
        self.cmb_level.config(state='disabled' if locked or self._levelless else 'readonly')
        if locked:
            self.preview_button.config(state='disabled')
        has_preview = self.preview is not None
        self.write_button.config(state='normal' if has_preview and not locked and self.preview.writable else 'disabled')
        self.discard_button.config(state='normal' if has_preview and not locked else 'disabled')
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
            self.counts = self.app.service.missing_counts([get_table(e['table']) for e in self.entries], lan_in, lan_out,
                                                          self._level())
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
        level = (f' ({level_label(self._level())})' if self._level() is not None and get_table(table).supports_levels
                 else '')
        text = (f'Missing in {self.var_out.get()}{level}: {fmt_count(self.counts.get(table))} in this table, '
                f'{fmt_count(total)} in all tables')
        if failed:
            text += ' (some tables could not be counted)'
        self.label_missing.config(text=text, fg=PALETTE['warn'] if failed else PALETTE['accent'] if total else PALETTE['ok'])
        self._update_summaries()

    def missing_hint(self):
        rows = [(e['description'], fmt_count(self.counts.get(e['table']))) for e in self.entries
                if e['table'] in self.counts]
        level = f' [{level_label(self._level())}]' if self._level() is not None else ''
        return {'title': f'Missing translations: {self.var_in.get()} → {self.var_out.get()}{level}',
                'rows': rows or [('-', 'not counted yet')]}
