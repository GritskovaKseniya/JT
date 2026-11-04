"""Lo strumento Indexes: gli indici di una tabella (nome, univoco o no) e, aprendo un indice, le sue colonne in ordine. Si legge
dal database solo la tabella chiesta (ALL_INDEXES e ALL_IND_COLUMNS). Non scrive niente."""
import tkinter as tk
from tkinter import ttk

from .. import indexes as index_reader, names
from .dictionary_bar import DictionaryBar
from .scale import pad, px
from .table_picker import TablePicker
from .texts import shorten
from .theme import PALETTE
from .widgets import Collapsible, StatusBar, TreeBox, WrapTracker

HINT = 'Type a table name and press Show: its indexes appear below.'


class IndexesScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        self.table = None                            # il nome fisico mostrato
        self.indexes, self.columns = [], []
        self.summary_text = ''
        self.status = StatusBar(self, HINT, on_change=lambda: app.fit_window(), compact=True)

        self.table_section, card = self._section('TABLE', first=True)
        self.bar = DictionaryBar(self.table_section.extra, app, self.message)
        self.bar.pack()
        self.picker = TablePicker(card, self.bar.get, self.show_table, self.message, button_text='Show',
                                  history=lambda: [h['fisico'] for h in app.settings.search_history()],
                                  on_layout=lambda: app.fit_window(),
                                  on_suggest=lambda: self.table_section.expand(notify=False))
        self.picker.pack(fill='x')

        self.result_section, card = self._section('INDEXES', grow=True)
        extra = self.result_section.extra                  # i pulsanti stanno sulla riga dell'intestazione
        self.copy_button = ttk.Button(extra, text='Copy all', style='Small.Secondary.TButton', command=self.copy_all,
                                      state='disabled')
        self.copy_button.pack(side='right')
        self.collapse_button = ttk.Button(extra, text='Collapse', style='Small.Secondary.TButton', command=self.collapse_all,
                                          state='disabled')
        self.collapse_button.pack(side='right', padx=(0, px(4)))
        self.expand_button = ttk.Button(extra, text='Expand', style='Small.Secondary.TButton', command=self.expand_all,
                                        state='disabled')
        self.expand_button.pack(side='right', padx=(0, px(4)))
        self.tree_box = TreeBox(card, height=6, columns=('kind',), show='tree headings', selectmode='browse')
        self.tree_box.pack(fill='both', expand=True)
        self.tree = self.tree_box.tree
        self.tree.heading('#0', text='Index / column', anchor='w')
        self.tree.heading('kind', text='Unique / position', anchor='w')
        self.tree.column('#0', width=px(260), stretch=True)
        self.tree.column('kind', width=px(110), stretch=False)
        self.tree.bind('<ButtonRelease-1>', self._click)

        self.status.pack(fill='x', pady=(px(6), 0))
        self.wrap.add(self.status, 95)
        self.bar.load()
        self.picker.refresh_history()

    def _section(self, title, first=False, grow=False):
        section = Collapsible(self, title, expanded=True, on_toggle=lambda: self.app.fit_window(), grow=grow)
        section.pack(fill='both' if grow else 'x', expand=grow, pady=(0 if first else px(4), 0))
        card = tk.Frame(section.body, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'],
                        padx=px(6), pady=px(6))
        card.pack(fill='both' if grow else 'x', expand=grow, pady=(px(6), 0))
        return section, card

    def message(self, state, text):
        self.status.show(state, text)

    def on_show(self):
        """Si e' aperta la scheda: se in Names si e' cercata un'altra tabella, si mostrano i suoi indici."""
        current = getattr(self.app, 'current_table', None)
        if current and current['physical'] != names.VIRTUAL and current['physical'] != self.table:
            self.picker.set_value(current['physical'])
            self.picker.search()

    def show_table(self, table):
        """Legge e mostra gli indici di una tabella trovata."""
        if table.physical == names.VIRTUAL:
            self.message('error', f'"{table.logical}" has no physical table: no indexes.')
            return
        self.app.set_busy(True)
        try:
            self.indexes, self.columns = index_reader.read(self.app.db, table.physical)
        except Exception as e:
            print(e)
            self.message('error', f"Could not read the indexes: {' '.join(str(e).split())[:200]}")
            return
        finally:
            self.app.set_busy(False)
        self.table = table.physical
        self._render()
        if self.app.settings.preferences().get('indexes', 'expand_all'):
            self.expand_all()
        self.summary_text = f'{table.physical} → {table.logical}  ·  {len(self.indexes)} indexes'
        self.result_section.set_summary(shorten(self.summary_text, 40))
        self.table_section.set_summary(shorten(table.physical, 30))
        self.table_section.collapse(notify=False)
        self.result_section.expand(notify=False)
        if self.indexes:
            self.message('ok', f'{len(self.indexes)} indexes. Open one to see its columns.')
        else:
            self.message('info', f'No index found for {table.physical}.')
        self.app.fit_window()

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        for number, index in enumerate(self.indexes):
            key = names.index_key(index)
            node = self.tree.insert('', 'end', iid=f'i{number}', text=index['INDEX_NAME'], values=(index['UNIQUENESS'],))
            for column in (c for c in self.columns if names.index_key(c) == key):
                self.tree.insert(node, 'end', text=column['COLUMN_NAME'], values=(column['COLUMN_POSITION'],))
        state = 'normal' if self.indexes else 'disabled'
        for button in (self.copy_button, self.expand_button, self.collapse_button):
            button.config(state=state)

    def expand_all(self):
        for item in self.tree.get_children():
            self.tree.item(item, open=True)

    def collapse_all(self):
        for item in self.tree.get_children():
            self.tree.item(item, open=False)

    def _click(self, event):
        """Un clic su un nome o su un valore lo copia (il triangolino apre e chiude, e' del Treeview)."""
        item = self.tree.identify_row(event.y)
        region = self.tree.identify_region(event.x, event.y)
        if not item or region not in ('tree', 'cell'):
            return
        column = self.tree.identify_column(event.x)
        text = self.tree.item(item, 'text') if column == '#0' else self.tree.set(item, 'kind')
        if text:
            self.clipboard_clear()
            self.clipboard_append(str(text))
            self.message('ok', f'Copied: {text}')

    def copy_all(self):
        if self.indexes:
            text = names.indexes_text(self.table, self.indexes, self.columns)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.message('ok', 'All indexes copied to the clipboard.')
