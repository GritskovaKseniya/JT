"""Lo strumento Names: cercare una tabella per nome (fisico o logico) e vederne i campi (nome fisico e logico, tipo, ampiezza,
decimali), tutti o solo quelli chiesti. Se il nome non e' esatto propone i piu' simili. Legge soltanto il dizionario."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .datatable import DataTable
from .dictionary_bar import DictionaryBar
from .scale import pad, px
from .table_picker import TablePicker
from .theme import FONT, PALETTE
from .widgets import Collapsible, ScrolledText, StatusBar, ToolTip, WrapTracker

FIELD_TABLE_COLUMNS = (('CAMPO_FISICO', 'Physical field', 130, False), ('CAMPO_LOGICO', 'Logical field', 130, False),
                       ('TIPO', 'Type', 45, False), ('AMPIEZZA', 'Width', 55, True), ('DECIMALI', 'Dec.', 45, True))
LOGICAL_TABLE_COLUMN = ('TABELLA_LOGICA', 'Logical table', 110, False)
HINT = 'Type a table name (physical like MD_ARTI or logical like Articolo) and press Search.'


class NamesScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        self.table = None                            # la TableMatch mostrata
        self.var_recent = tk.StringVar(value='')
        self.recent = []                             # [(testo mostrato, nome fisico)]

        self.status = StatusBar(self, HINT, on_change=lambda: app.fit_window())
        self.bar = DictionaryBar(self, app, self.message)
        self.bar.pack(fill='x', pady=(0, px(6)))

        # --- la ricerca
        self.search_section, card = self._section('SEARCH', first=True)
        self.recent_box = ttk.Combobox(card, textvariable=self.var_recent, state='readonly', width=1)
        self.recent_box.pack(fill='x', pady=(0, px(6)))
        self.recent_box.bind('<<ComboboxSelected>>', self._recent_chosen)
        ToolTip(self.recent_box, {'title': 'Recent searches', 'intro': 'The tables you looked for before.'})
        self.picker = TablePicker(card, self.bar.get, self.show_table, self.message, on_layout=lambda: app.fit_window(),
                                  on_suggest=lambda: self.search_section.expand(notify=False))
        self.picker.pack(fill='x')
        tk.Label(card, text='Fields (optional)', bg=PALETTE['bg'], fg=PALETTE['text'], font=(FONT, 9), anchor='w').pack(
            fill='x', pady=(px(8), 0))
        self.fields_box = ScrolledText(card, height=2)
        self.fields = self.fields_box.text
        self.fields_box.pack(fill='x', pady=(px(2), 0))
        ToolTip(self.fields, {'title': 'Fields', 'intro': 'Leave empty for every field, or type names (physical or logical) '
                                                          'separated by commas, spaces or new lines.'})

        # --- il risultato
        self.result_section, card = self._section('FIELDS', grow=True)
        self.title = tk.Label(card, text='', bg=PALETTE['bg'], fg=PALETTE['text'], font=(FONT, 10, 'bold'), anchor='w')
        self.title.pack(fill='x')
        top = tk.Frame(card, bg=PALETTE['bg'])
        top.pack(fill='x', pady=(px(2), px(4)))
        self.hint = ttk.Label(top, text='Click a cell to copy it', style='Muted.TLabel')
        self.hint.pack(side='left')
        self.copy_button = ttk.Button(top, text='Copy all', style='Secondary.TButton', command=self.copy_all, state='disabled')
        self.copy_button.pack(side='right')
        self.grid = DataTable(card, FIELD_TABLE_COLUMNS, height=9, on_copy=self._copied)
        self.grid.pack(fill='both', expand=True)

        self.status.pack(fill='x', pady=(px(10), 0))
        self.wrap.add(self.status, 95)
        if self.bar.load():
            self._fill_recent()

    def _section(self, title, first=False, grow=False):
        """Un blocco con titolo che si chiude; con `grow` (i risultati) si allarga anche in altezza con la finestra."""
        section = Collapsible(self, title, expanded=True, on_toggle=lambda: self.app.fit_window(), grow=grow)
        section.pack(fill='both' if grow else 'x', expand=grow, pady=(0 if first else px(8), 0))
        card = tk.Frame(section.body, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'],
                        padx=px(10), pady=px(8))
        card.pack(fill='both' if grow else 'x', expand=grow, pady=(px(2), 0))
        return section, card

    def message(self, state, text):
        self.status.show(state, text)

    # ------------------------------------------------------------------------------------------- ricerche recenti

    def _fill_recent(self):
        history = self.app.settings.search_history()
        self.recent = [(f"{h['fisico']} → {h.get('logico', '')}", h['fisico']) for h in history]
        self.recent_box.config(values=['Recent searches...'] + [text for text, _ in self.recent] if self.recent else [])
        self.var_recent.set('Recent searches...' if self.recent else '')

    def _recent_chosen(self, _event=None):
        chosen = self.var_recent.get()
        physical = next((p for text, p in self.recent if text == chosen), None)
        self.var_recent.set('Recent searches...')
        if physical:
            self.picker.set_value(physical)
            self.search()

    # ---------------------------------------------------------------------------------------------------- ricerca

    def fields_text(self):
        return self.fields.get('1.0', 'end').strip()

    def search(self):
        return self.picker.search()

    def show_table(self, table):
        """Mostra i campi di una tabella trovata (tutti o quelli chiesti)."""
        dictionary = self.bar.get()
        rows = names.table_rows(dictionary, table)
        results = names.search_fields(rows, self.fields_text())
        self.table = table
        logicals = {r.get('TABELLA_LOGICA') for r in results}
        columns = list(FIELD_TABLE_COLUMNS)
        if len(logicals) > 1:                               # piu' descrittori della stessa tabella: si dice di quale e' ogni campo
            columns.insert(0, LOGICAL_TABLE_COLUMN)
        self._set_columns(columns)
        self.grid.set_rows(results)
        name = table.physical if table.physical != names.VIRTUAL else '(no physical table)'
        self.title.config(text=f'{name} → {table.logical}' if len(logicals) <= 1 else f'{name}  ({len(logicals)} logical names)')
        missing = sum(1 for r in results if r.get('notFound'))
        self.copy_button.config(state='normal' if results else 'disabled')
        self.result_section.set_summary(f'{len(results)} fields')
        self.search_section.set_summary(f'{table.physical} → {table.logical}')
        self.search_section.collapse(notify=False)           # lo spazio serve ai risultati
        self.result_section.expand(notify=False)
        self.app.current_table = {'physical': table.physical, 'logical': table.logical}
        if table.physical != names.VIRTUAL:
            self.app.settings.add_search(table.physical, table.logical)
            self._fill_recent()
        if missing:
            self.message('warn', f'{missing} of the requested fields were not found (red).')
        else:
            self.message('ok', f'{len(results)} fields.')
        self.app.fit_window()

    def _set_columns(self, columns):
        tree = self.grid.tree
        self.grid.columns = list(columns)
        tree.config(columns=[c[0] for c in columns])
        for key, title, width, right in columns:
            tree.heading(key, text=title, anchor='w', command=lambda k=key: self.grid.sort_by(k))
            tree.column(key, width=px(width), minwidth=px(40), stretch=True, anchor='e' if right else 'w')

    def copy_all(self):
        if self.grid.rows:
            self.grid.copy_all()

    def _copied(self, text):
        shown = text if len(text) <= 40 else text[:37] + '...'
        self.message('ok', 'All rows copied to the clipboard.' if '\t' in text else f'Copied: {shown}')
