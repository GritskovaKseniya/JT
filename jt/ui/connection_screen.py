"""Passo 1: connessione al database."""
import tkinter as tk
from tkinter import ttk

from .scale import pad, px
from .texts import reason
from .widgets import StatusBar, WrapTracker, coming_soon

FIELDS = (('Host name', 'host', ''), ('Port', 'port', ''), ('SID', 'sid', ''),
          ('Username', 'username', ''), ('Password', 'password', '*'))


class ConnectionScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        saved = app.settings.connection()
        self.vars = {key: tk.StringVar(self, value=saved[key]) for _label, key, _mask in FIELDS}

        card = ttk.LabelFrame(self, text='DATABASE', style='Card.TLabelframe', padding=px(12))
        card.pack(fill='x')
        card.columnconfigure(1, weight=1)
        self.entries = {}
        for row, (label, key, mask) in enumerate(FIELDS):
            ttk.Label(card, text=label).grid(row=row, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
            entry = ttk.Entry(card, textvariable=self.vars[key], show=mask)
            entry.grid(row=row, column=1, sticky='ew', pady=px(5))
            entry.bind('<Return>', lambda _e: self.connect())
            self.entries[key] = entry

        buttons = self.buttons = ttk.Frame(self)
        buttons.pack(fill='x', pady=px(12))
        self.connect_button = ttk.Button(buttons, text='Connect', style='Secondary.TButton', command=self.connect)
        self.connect_button.pack(side='left', expand=True, fill='x', padx=(0, px(6)))
        self.next_button = ttk.Button(buttons, text='Next  →', style='Primary.TButton', state='disabled',
                                      command=app.show_translation)
        self.next_button.pack(side='left', expand=True, fill='x', padx=(px(6), 0))

        # il banner non c'e' finche' non succede qualcosa (il promemoria sta nella riga in basso); si chiude con la crocetta
        self.status = StatusBar(self, '', on_change=app.fit_window, closable=True)
        self.wrap.add(self.status, 95)
        coming_soon(self, 'Microsoft SQL Server (MSS) connection.', self.wrap).pack(fill='x', pady=(px(10), 0))
        self.entries['host'].focus_set()

        # cambiare i dati dopo essersi collegati: la connessione aperta non corrisponde piu' a quello che si vede
        for var in self.vars.values():
            var.trace_add('write', self._settings_changed)

    def _banner(self, state, text):
        if not self.status.winfo_manager():
            self.status.pack(fill='x', after=self.buttons)
        self.status.show(state, text)

    def connect(self):
        values = {key: var.get() for key, var in self.vars.items()}
        self._banner('info', 'Connecting...')
        self.app.set_busy(True)
        try:
            self.app.connect(values)
        except Exception as e:
            print(e)
            why = reason(e)
            self._banner('error', f'Connection failed: {why}' if why else 'Connection failed')
            self.next_button.config(state='disabled')
            return
        finally:
            self.app.set_busy(False)
        self._banner('ok', 'Connection established.')
        self.next_button.config(state='normal')

    def _settings_changed(self, *_):
        if not self.app.db.connected:
            return
        self.app.disconnect()
        self.next_button.config(state='disabled')
        self._banner('info', 'Connection settings changed. Press Connect to use the new ones.')
