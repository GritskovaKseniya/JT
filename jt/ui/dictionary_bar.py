"""La riga "Dictionary: N fields in M tables  [Reload]" degli strumenti dei nomi: legge il dizionario dal database collegato
(una volta per connessione) e lo tiene in `dictionary`."""
import tkinter as tk
from tkinter import ttk

from .. import dictionary as dictionary_reader
from .scale import px
from .theme import PALETTE
from .widgets import ToolTip


class DictionaryBar(tk.Frame):
    def __init__(self, parent, app, on_message, on_reload=None):
        super().__init__(parent, bg=PALETTE['bg'])
        self.app, self.on_message, self.on_reload = app, on_message, on_reload
        self.dictionary = None
        self.label = ttk.Label(self, text='', style='Muted.TLabel')
        self.label.pack(side='left')
        self.button = ttk.Button(self, text='Reload', style='Secondary.TButton', command=self.reload)
        self.button.pack(side='right')
        ToolTip(self.button, {'title': 'Reload dictionary',
                              'intro': 'The names are read from the database once. Reload them if they changed.'})

    def load(self, force=False):
        """Legge il dizionario (cursore di attesa). Ritorna True se c'e'."""
        self.app.set_busy(True)
        try:
            self.dictionary = dictionary_reader.load(self.app.db, force=force)
        except Exception as e:
            print(e)
            self.dictionary = None
            self.label.config(text='Dictionary not loaded')
            self.on_message('error', f"Could not read the dictionary of names: {' '.join(str(e).split())[:200]}")
            return False
        finally:
            self.app.set_busy(False)
        self.label.config(text=f'Dictionary: {len(self.dictionary.rows):,} fields in {len(self.dictionary.table_map):,} tables')
        return True

    def reload(self):
        dictionary_reader.forget()
        if self.load(force=True):
            self.on_message('ok', f'Dictionary reloaded: {len(self.dictionary.rows):,} fields.')
        if self.on_reload:
            self.on_reload()

    def get(self):
        """Il dizionario; se non e' stato letto (errore alla partenza) riprova."""
        if self.dictionary is None:
            self.load()
        return self.dictionary
