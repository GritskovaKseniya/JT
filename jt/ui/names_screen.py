"""Lo strumento Names: cercare una tabella per nome (fisico o logico) e vederne i campi (nome fisico e logico, tipo, ampiezza,
decimali), tutti o solo quelli chiesti. Se il nome non e' esatto propone i piu' simili. Legge soltanto il dizionario."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .datatable import DataTable
from .dictionary_bar import DictionaryBar
from .scale import pad, px
from .table_picker import TablePicker
from .texts import shorten
from .theme import FONT, PALETTE
from .widgets import Collapsible, StatusBar, ToolTip, WrapTracker

FIELD_TABLE_COLUMNS = (('POSIZ_DB', 'Pos.', 40, True), ('CAMPO_FISICO', 'Physical field', 130, False), ('CAMPO_LOGICO', 'Logical field', 130, False),
                       ('TIPO', 'Type', 45, False), ('AMPIEZZA', 'Width', 55, True), ('DECIMALI', 'Dec.', 45, True))
LOGICAL_TABLE_COLUMN = ('TABELLA_LOGICA', 'Logical table', 110, False)
HINT = 'Type a table name (physical like MD_ARTI or logical like Articolo) and press Search.'


class NamesScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        self.table = None                            # la TableMatch mostrata
        self.summary_text = ''
        self.status = StatusBar(self, HINT, on_change=lambda: app.fit_window(), compact=True)

        # --- la ricerca (nell'intestazione, a destra, il dizionario con Reload: niente riga sua)
        self.search_section, card = self._section('SEARCH', first=True)
        self.bar = DictionaryBar(self.search_section.extra, app, self.message)
        self.bar.pack()
        self.picker = TablePicker(card, self.bar.get, self.show_table, self.message, history=lambda: app.searches('names'),
                                  fields=lambda: self.fields_text(), on_restore=self._restore_fields,
                                  on_layout=lambda: app.fit_window(),
                                  on_suggest=lambda: self.search_section.expand(notify=False))
        self.picker.pack(fill='x')
        row = tk.Frame(card, bg=PALETTE['bg'])
        row.pack(fill='x', pady=(px(4), 0))
        tk.Label(row, text='Fields', bg=PALETTE['bg'], fg=PALETTE['text'], font=(FONT, 9), width=7, anchor='w').pack(side='left')
        self.fields = ttk.Entry(row)
        self.fields.pack(side='left', fill='x', expand=True)
        ToolTip(self.fields, {'title': 'Fields (optional)',
                              'intro': 'Leave empty for every field, or type names (physical or logical) separated by commas '
                                       'or spaces. Fields that do not exist appear in red.'})
        self.fields.bind('<Return>', lambda _e: self.search())

        # --- il risultato: titolo, riassunto e "Copy all" tutti sulla riga dell'intestazione
        self.result_section, card = self._section('FIELDS', grow=True)
        self.copy_button = ttk.Button(self.result_section.extra, text='Copy all', style='Small.Secondary.TButton',
                                      command=self.copy_all, state='disabled')
        self.copy_button.pack()
        self.grid = DataTable(card, FIELD_TABLE_COLUMNS, height=6, on_copy=self._copied)
        self.grid.pack(fill='both', expand=True)

        self.status.pack(fill='x', pady=(px(6), 0))
        self.wrap.add(self.status, 95)
        self.bar.load()
        self.picker.refresh_history()

    def _section(self, title, first=False, grow=False):
        """Un blocco con titolo che si chiude; con `grow` (i risultati) si allarga anche in altezza con la finestra."""
        section = Collapsible(self, title, expanded=True, on_toggle=lambda: self.app.fit_window(), grow=grow)
        section.pack(fill='both' if grow else 'x', expand=grow, pady=(0 if first else px(4), 0))
        card = tk.Frame(section.body, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'],
                        padx=px(6), pady=px(6))
        card.pack(fill='both' if grow else 'x', expand=grow, pady=(px(6), 0))
        return section, card

    def message(self, state, text):
        self.status.show(state, text)

    # ---------------------------------------------------------------------------------------------------- ricerca

    def _restore_fields(self, entry):
        """Scelta una ricerca della storia: i campi chiesti allora tornano nella casella."""
        self.fields.delete(0, 'end')
        self.fields.insert(0, entry.get('fields', ''))

    def fields_text(self):
        return self.fields.get().strip()

    def search(self):
        return self.picker.search()

    def show_table(self, table):
        """Mostra i campi di una tabella trovata (tutti o quelli chiesti)."""
        dictionary = self.bar.get()
        rows = names.table_rows(dictionary, table)
        results = names.search_fields(rows, self.fields_text())
        if not self.fields_text():                           # tutti i campi: nell'ordine dei descrittori (Posiz. DB); se ne chiedi alcuni, come scritti
            results = names.default_order(results)
        self.table = table
        logicals = {r.get('TABELLA_LOGICA') for r in results}
        preferences = self.app.settings.preferences()
        hidden = preferences.names_hidden()
        columns = [c for c in FIELD_TABLE_COLUMNS if c[0] not in hidden]
        if not any(r.get('POSIZ_DB') not in (None, '') for r in results):            # senza posizioni (database vecchio) niente colonna
            columns = [c for c in columns if c[0] != 'POSIZ_DB']
        if len(logicals) > 1:                               # piu' descrittori della stessa tabella: si dice di quale e' ogni campo
            columns.insert(0, LOGICAL_TABLE_COLUMN)
        self.grid.set_columns(columns)
        self.grid.set_rows(results)
        order = preferences.names_sort()                     # l'ordinamento scelto nel file (la colonna deve essere mostrata)
        if order and order[0] in [c[0] for c in columns]:
            self.grid.sort_by(*order)
        name = table.physical if table.physical != names.VIRTUAL else '(no physical table)'
        label = f'{name} → {table.logical}' if len(logicals) <= 1 else f'{name} ({len(logicals)} logical names)'
        missing = sum(1 for r in results if r.get('notFound'))
        self.copy_button.config(state='normal' if results else 'disabled')
        self.summary_text = f'{label}  ·  {len(results)} fields'
        self.result_section.set_summary(shorten(self.summary_text, 46))
        self.search_section.set_summary(shorten(f'{table.physical} → {table.logical}', 30))
        self.search_section.collapse(notify=False)           # lo spazio serve ai risultati
        self.result_section.expand(notify=False)
        self.app.current_table = {'physical': table.physical, 'logical': table.logical}
        if table.physical != names.VIRTUAL:
            self.app.searches('names').add(self.picker.value(), table.physical, table.logical, self.fields_text())
            self.picker.refresh_history()
        if missing:
            self.message('warn', f'{missing} of the requested fields were not found (red).')
        else:
            self.message('ok', f'{len(results)} fields. Click a cell to copy it.')
        self.app.fit_window()

    def copy_all(self):
        if self.grid.rows:
            self.grid.copy_all()

    def _copied(self, text):
        shown = text if len(text) <= 40 else text[:37] + '...'
        self.message('ok', 'All rows copied to the clipboard.' if '\t' in text else f'Copied: {shown}')
