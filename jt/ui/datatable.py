"""Una tabella di risultati: colonne che si ordinano con un clic sull'intestazione, un clic su una cella la copia, e si possono
copiare tutte le righe (testo con tabulazioni, per Excel)."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .scale import px
from .theme import PALETTE
from .widgets import TreeBox

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
        self.box = TreeBox(self, height=height, columns=keys, show='headings', selectmode='browse')
        self.box.pack(fill='both', expand=True)
        self.tree = self.box.tree
        self.set_columns(self.columns)
        self.tree.tag_configure('notfound', foreground=PALETTE['error'])
        self.tree.bind('<ButtonRelease-1>', self._click)

    def set_columns(self, columns):
        """Le colonne mostrate (chiave, titolo, larghezza di partenza, a destra); la larghezza vera si calcola sulle righe."""
        self.columns = list(columns)
        self.tree.config(columns=[c[0] for c in self.columns])
        for key, title, width, right in self.columns:
            self.tree.heading(key, text=title, anchor='e' if right else 'w', command=lambda k=key: self.sort_by(k))   # sopra le cifre
            # l'ultima colonna riempie lo spazio che resta: anche a tabella vuota l'intestazione arriva fino in fondo
            self.tree.column(key, width=px(width), minwidth=px(40), stretch=key == self.columns[-1][0], anchor='e' if right else 'w')

    def set_rows(self, rows):
        """Mostra queste righe (e toglie l'ordinamento). Le colonne si allargano a quello che contengono, fino a un massimo: il
        resto si vede scorrendo (la tabella non allarga mai la finestra)."""
        self.rows = list(rows)
        self.unsorted = list(self.rows)               # l'ordine di partenza: ci si torna col terzo clic sulla colonna
        self.sorted_by = None
        self.box.fit_columns([(key, title) for key, title, *_ in self.columns], self.rows)
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

    def sort_by(self, key, ascending=None):
        """Ordina per questa colonna: il primo clic in ordine crescente, il secondo decrescente, il terzo toglie l'ordinamento e torna
        all'ordine di partenza (o il verso e' dato)."""
        if ascending is None:
            if self.sorted_by and self.sorted_by[0] == key and not self.sorted_by[1]:
                self.rows, self.sorted_by = list(self.unsorted), None
                self._render()
                return
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
