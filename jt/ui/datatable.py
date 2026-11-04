"""Una tabella di risultati: colonne che si ordinano con un clic sull'intestazione, un clic su una cella la copia, e si possono
copiare tutte le righe (testo con tabulazioni, per Excel)."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .scale import px
from .theme import PALETTE

ASC, DESC = ' ▲', ' ▼'


class DataTable(ttk.Frame):
    """`columns` = [(chiave, titolo, larghezza in pixel a scala 100%, allinea a destra)]. Le righe sono dict."""

    def __init__(self, parent, columns, height=8, on_copy=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.on_copy = on_copy                      # on_copy(testo) dopo aver copiato una cella
        self.rows = []                              # nell'ordine mostrato
        self.sorted_by = None                       # (chiave, crescente)
        keys = [c[0] for c in self.columns]
        self.tree = ttk.Treeview(self, columns=keys, show='headings', height=height, selectmode='browse')
        for key, title, width, right in self.columns:
            self.tree.heading(key, text=title, anchor='w', command=lambda k=key: self.sort_by(k))
            self.tree.column(key, width=px(width), minwidth=px(40), stretch=True, anchor='e' if right else 'w')
        bar = ttk.Scrollbar(self, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        self.tree.pack(side='left', fill='both', expand=True)
        bar.pack(side='right', fill='y')
        self.tree.tag_configure('notfound', foreground=PALETTE['error'])
        self.tree.bind('<ButtonRelease-1>', self._click)

    def set_rows(self, rows):
        """Mostra queste righe (e toglie l'ordinamento)."""
        self.rows = list(rows)
        self.sorted_by = None
        self._render()

    def clear(self):
        self.set_rows([])

    def _render(self):
        self.tree.delete(*self.tree.get_children())
        for index, row in enumerate(self.rows):
            values = ['' if row.get(key) is None else str(row.get(key)) for key, *_ in self.columns]
            self.tree.insert('', 'end', iid=str(index), values=values, tags=('notfound',) if row.get('notFound') else ())
        for key, title, *_ in self.columns:
            mark = ''
            if self.sorted_by and self.sorted_by[0] == key:
                mark = ASC if self.sorted_by[1] else DESC
            self.tree.heading(key, text=title + mark)

    def sort_by(self, key):
        """Ordina per questa colonna; un secondo clic sulla stessa inverte l'ordine."""
        ascending = not (self.sorted_by and self.sorted_by[0] == key and self.sorted_by[1])
        self.rows.sort(key=lambda row: names.sort_key(key, row.get(key)), reverse=not ascending)
        self.sorted_by = (key, ascending)
        self._render()

    def _click(self, event):
        if self.tree.identify_region(event.x, event.y) != 'cell':
            return
        row, column = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        if not row or not column:
            return
        key = self.columns[int(column.lstrip('#')) - 1][0]
        self.copy_text(self.tree.set(row, key))

    def copy_text(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        if self.on_copy:
            self.on_copy(text)

    def copy_all(self, columns=names.FIELD_COLUMNS):
        """Tutte le righe come testo con tabulazioni (con l'intestazione)."""
        text = names.tsv(self.rows, columns)
        self.copy_text(text)
        return text
