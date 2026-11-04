"""Scegliere una tabella per nome (fisico o logico): si scrive, e se non c'e' un risultato esatto compare l'elenco dei nomi piu'
simili (suggerimenti "fuzzy") da cui scegliere. Lo usano Names e Indexes."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .scale import px
from .theme import FONT, PALETTE

BADGES = {names.STARTS_WITH: 'starts with', names.CONTAINS: 'contains', names.FUZZY: 'similar'}


class TablePicker(ttk.Frame):
    """`dictionary()` ritorna il Dictionary corrente (o None); `on_pick(TableMatch)` si chiama con la tabella scelta;
    `on_message(stato, testo)` per dire cosa e' successo (non trovata, suggerimenti...)."""

    def __init__(self, parent, dictionary, on_pick, on_message, button_text='Search', on_layout=None, on_suggest=None):
        super().__init__(parent)
        self.dictionary, self.on_pick, self.on_message = dictionary, on_pick, on_message
        self.on_layout = on_layout or (lambda: None)
        self.on_suggest = on_suggest or (lambda: None)          # si chiama quando compaiono i suggerimenti (apre la sezione)
        self.suggestions = []                       # i TableMatch mostrati
        self.var = tk.StringVar()

        tk.Label(self, text='Table name (physical or logical)', bg=PALETTE['bg'], fg=PALETTE['text'], font=(FONT, 9),
                 anchor='w').pack(fill='x')
        row = tk.Frame(self, bg=PALETTE['bg'])
        row.pack(fill='x', pady=(px(2), 0))
        self.entry = ttk.Entry(row, textvariable=self.var)
        self.entry.pack(side='left', fill='x', expand=True)
        self.button = ttk.Button(row, text=button_text, style='Primary.TButton', command=self.search)
        self.button.pack(side='left', padx=(px(6), 0))
        self.entry.bind('<Return>', lambda _e: self.search())

        self.box = tk.Frame(self, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'])
        head = tk.Frame(self.box, bg=PALETTE['bg'])
        head.pack(fill='x', padx=px(6), pady=(px(4), 0))
        self.title = tk.Label(head, text='', bg=PALETTE['bg'], fg=PALETTE['warn'], font=(FONT, 9, 'bold'), anchor='w',
                              justify='left', wraplength=px(380))
        self.title.pack(side='left', fill='x', expand=True)
        close = tk.Label(head, text='×', bg=PALETTE['bg'], fg=PALETTE['muted'], font=(FONT, 12), cursor='hand2')
        close.pack(side='right')
        close.bind('<Button-1>', lambda _e: self.hide_suggestions())
        self.list = ttk.Treeview(self.box, columns=('why', 'fields'), show='tree headings', height=5, selectmode='browse')
        self.list.heading('#0', text='Table', anchor='w')
        self.list.heading('why', text='Match', anchor='w')
        self.list.heading('fields', text='Fields', anchor='e')
        self.list.column('#0', width=px(200), stretch=True)
        self.list.column('why', width=px(95), stretch=False)
        self.list.column('fields', width=px(55), stretch=False, anchor='e')
        self.list.pack(fill='x', padx=px(6), pady=px(4))
        self.list.bind('<Double-Button-1>', self._choose)
        self.list.bind('<Return>', self._choose)

    # ------------------------------------------------------------------------------------------------------ ricerca

    def value(self):
        return self.var.get().strip()

    def set_value(self, text):
        self.var.set(text)

    def search(self, *_):
        """Cerca la tabella scritta: se c'e' un risultato esatto la sceglie, altrimenti mostra i suggerimenti."""
        text = names.normalize_table_name(self.value())
        self.hide_suggestions()
        if not text:
            self.on_message('info', 'Type a table name (physical or logical).')
            return False
        dictionary = self.dictionary()
        if dictionary is None:
            self.on_message('error', 'The dictionary of names is not loaded.')
            return False
        exact, suggestions = names.best_table_matches(dictionary, text)
        if exact:
            self.on_pick(exact[0])
            return True
        if suggestions:
            self.show_suggestions(suggestions, text)
            return False
        self.on_message('error', f'Table "{text}" not found in the dictionary. Try a part of the name (ARTI for MD_ARTI), '
                                 'the logical name (Articolo) or check the spelling.')
        return False

    def show_suggestions(self, suggestions, text):
        self.suggestions = list(suggestions)
        self.title.config(text=f'No exact match for "{text}". Try one of these:')
        self.list.delete(*self.list.get_children())
        for index, table in enumerate(self.suggestions):
            name = f'{table.logical} (no table)' if table.physical == names.VIRTUAL else f'{table.physical} → {table.logical}'
            percent = f' ({round(table.similarity * 100)}%)' if table.type == names.FUZZY else ''
            self.list.insert('', 'end', iid=str(index), text=name,
                             values=(BADGES.get(table.type, table.type) + percent, table.fields))
        self.list.config(height=min(6, len(self.suggestions)))
        self.box.pack(fill='x', pady=(px(6), 0))
        self.on_suggest()
        self.on_message('warn', 'No exact match: choose one of the suggestions (double-click).')
        self.on_layout()

    def hide_suggestions(self):
        if self.box.winfo_manager():
            self.box.pack_forget()
            self.on_layout()
        self.suggestions = []

    def _choose(self, _event=None):
        selected = self.list.selection()
        if not selected:
            return
        table = self.suggestions[int(selected[0])]
        self.var.set(table.physical if table.physical != names.VIRTUAL else table.logical)
        self.hide_suggestions()
        self.on_pick(table)
