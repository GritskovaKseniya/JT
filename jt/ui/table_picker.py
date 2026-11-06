"""Scegliere una tabella per nome (fisico o logico): una riga `Table [nome v] [Search]` (il menu ripropone le ultime tabelle cercate),
e se non c'e' un risultato esatto compare l'elenco dei nomi piu' simili (suggerimenti "fuzzy") da cui scegliere. Lo usano Names e
Indexes."""
import tkinter as tk
from tkinter import ttk

from .. import names
from .scale import px
from .theme import FONT, PALETTE
from .widgets import PopupMenu, ToolTip, TreeBox, icon_button

BADGES = {names.STARTS_WITH: 'starts with', names.CONTAINS: 'contains', names.FUZZY: 'similar'}
SUGGESTION_ROWS = 5
HISTORY_ROWS = 15                          # le voci della storia nella lista (le piu' recenti)


class TablePicker(ttk.Frame):
    """`dictionary()` ritorna il Dictionary corrente (o None); `on_pick(TableMatch)` si chiama con la tabella scelta;
    `on_message(stato, testo)` per dire cosa e' successo (non trovata, suggerimenti...); `history()` ritorna la SearchHistory del
    database (il menu mostra quello che hai cercato: tutto, oppure solo quello che contiene il testo se hai scritto qualcosa di nuovo);
    `fields()` i campi scritti accanto (Names: fanno parte della ricerca ricordata) e `on_restore(voce)` per rimetterli quando si
    sceglie una voce; `on_suggest()` quando compaiono i suggerimenti (la sezione che li contiene si apre)."""

    def __init__(self, parent, dictionary, on_pick, on_message, history=None, button_text='Search', on_layout=None,
                 on_suggest=None, label='Table', icon='search', fields=None, on_restore=None):
        super().__init__(parent)
        self.dictionary, self.on_pick, self.on_message = dictionary, on_pick, on_message
        self.history = history
        self.fields = fields or (lambda: '')
        self.on_restore = on_restore or (lambda entry: None)
        self._shown = []                            # le voci della storia nel menu, nell'ordine mostrato
        self.on_layout = on_layout or (lambda: None)
        self.on_suggest = on_suggest or (lambda: None)
        self.suggestions = []                       # i TableMatch mostrati
        self.var = tk.StringVar()

        row = tk.Frame(self, bg=PALETTE['bg'])
        row.pack(fill='x')
        tk.Label(row, text=label, bg=PALETTE['bg'], fg=PALETTE['text'], font=(FONT, 9), width=7, anchor='w').pack(side='left')
        self.entry = ttk.Combobox(row, textvariable=self.var, width=1, postcommand=self._open_list)   # si scrive; il menu ha le ultime cercate
        self.entry.pack(side='left', fill='x', expand=True)
        self.button = icon_button(row, icon, self.search)
        self.button.box.pack(side='left', padx=(px(6), 0))
        ToolTip(self.button, {'title': button_text, 'intro': 'Or press Enter.'})
        self.entry.bind('<Return>', lambda _e: self.search())
        self.entry.bind('<<ComboboxSelected>>', self._chosen)
        self.menu_button = icon_button(row, 'history', self._history_menu)
        self.menu_button.box.pack(side='left', padx=(px(2), 0))
        ToolTip(self.menu_button, {'title': 'History', 'intro': 'Remove the search you typed from the history, or clear it.'})
        self.refresh_history()

        self.box = tk.Frame(self, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'])
        head = tk.Frame(self.box, bg=PALETTE['bg'])
        head.pack(fill='x', padx=px(6), pady=(px(2), 0))
        self.title = tk.Label(head, text='', bg=PALETTE['bg'], fg=PALETTE['warn'], font=(FONT, 9, 'bold'), anchor='w',
                              justify='left', wraplength=px(380))
        self.title.pack(side='left', fill='x', expand=True)
        close = tk.Label(head, text='×', bg=PALETTE['bg'], fg=PALETTE['muted'], font=(FONT, 12), cursor='hand2')
        close.pack(side='right')
        close.bind('<Button-1>', lambda _e: self.hide_suggestions())
        self.tree_box = TreeBox(self.box, height=SUGGESTION_ROWS, columns=('why', 'fields'), show='tree headings',
                                selectmode='browse')
        self.tree_box.pack(fill='x', padx=px(6), pady=px(4))
        self.list = self.tree_box.tree
        self.list.heading('#0', text='Table', anchor='w')
        self.list.heading('why', text='Match', anchor='w')
        self.list.heading('fields', text='Fields', anchor='e')
        self.list.column('#0', width=px(200), stretch=True)
        self.list.column('why', width=px(95), stretch=False)
        self.list.column('fields', width=px(55), stretch=False, anchor='e')
        self.list.bind('<Double-Button-1>', self._choose)
        self.list.bind('<Return>', self._choose)

    # ----------------------------------------------------------------------------------------------- storia

    def refresh_history(self, typed=''):
        """Il menu della casella: le ricerche passate (le piu' recenti per prime) che contengono `typed` (tutte se e' vuoto)."""
        self._shown = self.history().matching(typed) if self.history else []
        self.entry.config(values=[self.history().label(e) for e in self._shown])

    def _open_list(self):
        """Si apre il menu: tutta la storia, a meno che nella casella ci sia un testo nuovo (allora solo quello che lo contiene)."""
        typed = self.value()
        known = self.history and any(e['text'].casefold() == typed.casefold() for e in self.history().entries())
        self.refresh_history('' if known else typed)

    def _chosen(self, _event=None):
        """Scelta una voce del menu: si rimettono il testo e i campi di allora e si cerca."""
        index = self.entry.current()
        if 0 <= index < len(self._shown):
            self._restore(self._shown[index])
        else:
            self.search()

    def _history_menu(self):
        """La lista della storia (le ricerche recenti per prime): un clic ne rifa' una, la crocetta la toglie (e la lista si riapre per
        toglierne altre), "Clear history" svuota tutto. Con la storia vuota non c'e' niente da scegliere: solo un avviso."""
        entries = self.history().entries()
        if not entries:
            self.on_message('info', 'The history is empty.')
            return
        items = [(self.history().label(e), lambda e=e: self._restore(e), True, lambda e=e: self._forget(e))
                 for e in entries[:HISTORY_ROWS]]
        if len(entries) > HISTORY_ROWS:
            items.append((f'... and {len(entries) - HISTORY_ROWS} older', lambda: None, False))
        items += [('-', None, False), ('Clear history', self.clear_history, True)]
        self.menu = PopupMenu(self.menu_button.box, items)

    def _restore(self, entry):
        """Si rifa' una ricerca della storia: il testo, i campi di allora e la ricerca."""
        self.var.set(entry['text'])
        self.on_restore(entry)
        self.search()

    def _forget(self, entry):
        self.history().remove(entry['text'], entry['fields'])
        self.refresh_history()
        self.on_message('info', f'"{self.history().label(entry)}" removed from the history.')
        if self.history().entries():
            self.after(1, self._history_menu)

    def remove_current(self):
        text, fields = self.value(), self.fields()
        self.history().remove(text, fields)
        self.refresh_history()
        self.on_message('info', f'"{text} \u00b7 {fields}" removed from the history.' if fields else f'"{text}" removed from the history.')

    def clear_history(self):
        self.history().clear()
        self.refresh_history()
        self.on_message('info', 'History cleared.')

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
        self.tree_box.configure(height=px(24 + 22 * min(SUGGESTION_ROWS, len(self.suggestions))))
        self.box.pack(fill='x', pady=(px(4), 0))
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
