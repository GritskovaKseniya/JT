"""Passo 1: connessione al database."""
import tkinter as tk
from tkinter import ttk

from .. import environments
from .scale import pad, px
from .theme import FONT, PALETTE
from .texts import reason
from .widgets import PopupMenu, StatusBar, ToolTip, WrapTracker, coming_soon, icon_button

ENV_HINT = {
    'title': 'Environment',
    'intro': 'What kind of database this is: where JT writes needs more care. Set it once, JT remembers it for this database.',
    'rows': [('dev / test', 'Writing does not ask for anything.'),
             ('prod', 'Writing asks you to type the database name to confirm.'),
             ('Not set', 'Treated like prod.')],
}

PROFILE_HINT = {
    'title': 'Saved connections',
    'intro': 'The databases you connected to: choose one to fill the fields, or remove it with the cross. A connection is saved by '
             'itself when it succeeds. They are files in the connections folder: you can copy them to a colleague.',
}
SAVE_HINT = {'title': 'Save', 'intro': 'Keeps these fields in the chosen connection (asks a name for a new one).'}

FIELDS = (('Host name', 'host', ''), ('Port', 'port', ''), ('SID', 'sid', ''),
          ('Username', 'username', ''), ('Password', 'password', '*'))


class ConnectionScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))
        self.app = app
        self.wrap = WrapTracker()
        saved = app.settings.connection()
        self.profiles = app.settings.profiles()
        self.profiles.migrate(saved, app.settings.environment(saved['host'], saved['port'], saved['sid']))   # la prima volta
        start = self._starting_profile(saved)               # senza una connessione ricordata si parte dall'ultimo profilo usato
        if start:
            saved = {key: start[key] for key in saved}
        self.vars = {key: tk.StringVar(self, value=saved[key]) for _label, key, _mask in FIELDS}
        self.profile_var = tk.StringVar(self, value=start['name'] if start else '')

        card = ttk.LabelFrame(self, text='DATABASE', style='Card.TLabelframe', padding=px(12))
        card.pack(fill='x')
        card.columnconfigure(1, weight=1)
        # prima riga: l'icona della lista delle connessioni salvate, il nome di quella scelta e l'icona per salvare
        self.profiles_button = icon_button(card, 'history', self._profile_list)
        self.profiles_button.box.grid(row=0, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
        ToolTip(self.profiles_button, PROFILE_HINT)
        saved_row = ttk.Frame(card)
        saved_row.grid(row=0, column=1, sticky='ew', pady=px(5))
        self.profile_label = tk.Label(saved_row, text='', anchor='w', bg=PALETTE['bg'], font=(FONT, 10), cursor='hand2')
        self.profile_label.pack(side='left', fill='x', expand=True)
        self.profile_label.bind('<Button-1>', lambda _e: self._profile_list())
        self.save_button = icon_button(saved_row, 'write', self.save_profile)
        self.save_button.box.pack(side='left', padx=(px(6), 0))
        ToolTip(self.save_button, SAVE_HINT)
        self._show_profile()
        self.profile_var.trace_add('write', self._show_profile)
        self.entries = {}
        for row, (label, key, mask) in enumerate(FIELDS, start=1):
            ttk.Label(card, text=label).grid(row=row, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
            entry = ttk.Entry(card, textvariable=self.vars[key], show=mask)
            entry.grid(row=row, column=1, sticky='ew', pady=px(5))
            entry.bind('<Return>', lambda _e: self.connect())
            self.entries[key] = entry

        row = len(FIELDS) + 1                               # dev / test / prod: dove si scrive, con quanta cautela
        label_env = ttk.Label(card, text='Environment  (?)')
        label_env.grid(row=row, column=0, sticky='w', padx=(0, px(14)), pady=px(5))
        self.env_var = tk.StringVar(self, value=environments.to_label(
            app.settings.environment(saved['host'], saved['port'], saved['sid'])))
        self._refilling = False                             # l'etichetta la sta proponendo il programma, non la sceglie chi usa
        self.cmb_env = ttk.Combobox(card, textvariable=self.env_var, values=list(environments.CHOICES), state='readonly')
        self.cmb_env.grid(row=row, column=1, sticky='ew', pady=px(5))
        ToolTip(label_env, ENV_HINT, self.cmb_env)

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
        for key in ('host', 'port', 'sid'):                 # un altro database: si propone la sua etichetta (se la conosciamo)
            self.vars[key].trace_add('write', self._refill_environment)
        for key in ('host', 'port', 'sid', 'username'):     # e la connessione salvata e' un'altra (o nessuna)
            self.vars[key].trace_add('write', self._sync_profile)
        self.env_var.trace_add('write', self._environment_changed)

    # ----------------------------------------------------------------------------------------- profili salvati

    def _starting_profile(self, saved):
        """Il profilo che corrisponde all'ultima connessione; se non se ne ricorda una, l'ultimo profilo usato."""
        profiles = self.profiles.list()
        if saved.get('host') or saved.get('sid'):
            return next((p for p in profiles if self.profiles.same_database(p, saved)), None)
        return profiles[0] if profiles else None

    def _values(self):
        values = {key: var.get() for key, var in self.vars.items()}
        values['environment'] = environments.from_label(self.env_var.get())
        return values

    def _show_profile(self, *_):
        """Il nome della connessione scelta (o l'invito a salvarne una) accanto all'icona."""
        name = self.profile_var.get().strip()
        self.profile_label.config(text=name or 'New connection', fg=PALETTE['accent'] if name else PALETTE['muted'],
                                  font=(FONT, 10, 'bold') if name else (FONT, 10))

    def _profiles_changed(self):
        self._show_profile()

    def _sync_profile(self, *_):
        """Cambiando i dati che dicono il database (host, porta, SID, utente) la connessione salvata non e' piu' quella: il nome
        sparisce (si salva da sola dopo la prossima connessione); se i dati tornano quelli di una salvata, ricompare."""
        match = next((p for p in self.profiles.list() if self.profiles.same_database(p, self._values())), None)
        self.profile_var.set(match['name'] if match else '')

    def choose_profile(self):
        """Si sceglie un profilo: i campi (e l'etichetta dev/test/prod) si riempiono."""
        name = self.profile_var.get()
        profile = self.profiles.get(name)
        if not profile:
            return
        for key in self.vars:
            self.vars[key].set(profile[key])
        self.profile_var.set(profile['name'])               # i campi cambiati l'hanno tolto un attimo: si rimette
        self._refilling = True                              # l'etichetta e' quella del profilo, non una scelta di adesso
        try:
            self.env_var.set(environments.to_label(profile['environment'] or self.app.settings.environment(
                profile['host'], profile['port'], profile['sid'])))
        finally:
            self._refilling = False
        self._banner('info', f'Connection "{profile["name"]}" loaded. Press Connect.')

    def _profile_list(self):
        """La lista delle connessioni salvate (la piu' recente per prima): un clic la sceglie, la crocetta la cancella."""
        items = [(p['name'], lambda n=p['name']: self._pick(n), True, lambda n=p['name']: self.delete_profile(n))
                 for p in self.profiles.list()]
        if items:
            items += [('-', None, False), ('Clear all', self.clear_profiles, True)]
        self.menu = PopupMenu(self.profiles_button.box, items or [('No saved connections yet', lambda: None, False)])

    def _pick(self, name):
        self.profile_var.set(name)
        self.choose_profile()

    def save_profile(self):
        """Salva i dati nella connessione scelta (se non ce n'e' una chiede il nome)."""
        name = self.profile_var.get().strip()
        if not name:
            return self.save_profile_as()
        self._store(name)

    def save_profile_as(self):
        sid, host = self.vars['sid'].get().strip(), self.vars['host'].get().strip()
        suggestion = self.profile_var.get().strip() or (f'{sid} @ {host}' if sid and host else sid or host)
        name = self._ask_name(suggestion)
        if not name or not name.strip():
            return
        if self.profiles.get(name) and not self._confirm(f'A connection called "{name.strip()}" already exists. Replace it?'):
            return
        self._store(name.strip())

    def _store(self, name, quiet=False):
        try:
            self.profiles.save(name, self._values())
        except OSError as e:
            self._banner('error', f'Could not save the connection: {reason(e)}')
            return
        self.profile_var.set(name)
        if not quiet:
            self._banner('ok', f'Connection "{name}" saved.')

    def delete_profile(self, name=None):
        name = (name or self.profile_var.get()).strip()
        profile = self.profiles.get(name)
        if not name or not profile:
            return
        if not self._confirm(f'Delete the saved connection "{name}"?'):
            return
        active = self.profiles.same_database(profile, self._values())      # era quella che si vede nei campi?
        try:
            self.profiles.delete(name)
        except OSError as e:
            self._banner('error', f'Could not delete the connection: {reason(e)}')
            return
        if self.profile_var.get().strip().casefold() == name.casefold():
            self.profile_var.set('')
        message = f'Connection "{name}" deleted.'
        if active:                                          # i suoi dati non devono restare: si mette l'ultima che resta (o niente)
            remaining = self.profiles.list()
            if remaining:
                self._pick(remaining[0]['name'])
                message += f' Now: "{remaining[0]["name"]}".'
            else:
                self._clear_fields()
            self._forget_last_connection()
        self._banner('info', message)

    def clear_profiles(self):
        """Cancella tutte le connessioni salvate (con una conferma). Se i campi mostravano una di loro si svuotano anche quelli."""
        profiles = self.profiles.list()
        if not profiles or not self._confirm(f'Delete all {len(profiles)} saved connections?', 'Delete all'):
            return
        active = any(self.profiles.same_database(p, self._values()) for p in profiles)
        failed = 0
        for profile in profiles:
            try:
                self.profiles.delete(profile['name'])
            except OSError:
                failed += 1
        if active:
            self._clear_fields()
            self._forget_last_connection()
        self.profile_var.set('')
        if failed:
            self._banner('error', f'Could not delete {failed} of the connections.')
        else:
            self._banner('info', f'{len(profiles)} connections deleted.')

    def _clear_fields(self):
        for var in self.vars.values():
            var.set('')
        self._refilling = True
        try:
            self.env_var.set(environments.to_label(''))
        finally:
            self._refilling = False
        self.profile_var.set('')

    def _forget_last_connection(self):
        """L'ultima connessione ricordata (quella con cui si riempiono i campi alla partenza) diventa quella che si vede adesso."""
        values = self._values()
        try:
            self.app.settings.save_connection(values['host'], values['port'], values['sid'], values['username'], values['password'])
        except OSError as e:
            print(f'Could not save the connection data: {e}')

    def _remember_connection(self, values):
        """Dopo una connessione riuscita: se il database e' gia' salvato si aggiornano i suoi dati (password, etichetta) e va in cima;
        altrimenti si salva una connessione nuova ("SID @ host")."""
        try:
            match = next((p for p in self.profiles.list() if self.profiles.same_database(p, values)), None)
            if match:
                self.profiles.save(match['name'], values)
                self.profiles.touch(match['name'])
                self.profile_var.set(match['name'])
                return
            sid, host, user = values['sid'].strip(), values['host'].strip(), values['username'].strip()
            name = f'{sid} @ {host}'
            if self.profiles.get(name):                      # stesso nome ma un altro utente: si distingue
                name = f'{name} ({user})'
            number = 2
            while self.profiles.get(name):
                name = f'{sid} @ {host} ({user}) {number}'
                number += 1
            self.profiles.save(name, values)
            self.profiles.touch(name)
            self.profile_var.set(name)
        except OSError as e:
            print(f'Could not save the connection: {e}')

    def _ask_name(self, suggestion):
        return self.app.ask_text('Name of the connection', suggestion, 'Save')

    def _confirm(self, text, ok_text='Delete'):
        return self.app.confirm(text, '', ok_text, 'Cancel')

    def _refill_environment(self, *_):
        values = {key: var.get() for key, var in self.vars.items()}
        self._refilling = True              # non e' una scelta: non si salva (l'ordine dei gestori di Tk non e' garantito)
        try:
            self.env_var.set(environments.to_label(
                self.app.settings.environment(values['host'], values['port'], values['sid'])))
        finally:
            self._refilling = False

    def _environment_changed(self, *_):
        """Cambiare l'etichetta mentre si e' collegati vale subito (non serve ricollegarsi)."""
        if self.app.db.connected and not self._refilling:
            self.app.set_environment(environments.from_label(self.env_var.get()))

    def _banner(self, state, text):
        if not self.status.winfo_manager():
            self.status.pack(fill='x', after=self.buttons)
        self.status.show(state, text)

    def connect(self):
        values = {key: var.get() for key, var in self.vars.items()}
        values['environment'] = environments.from_label(self.env_var.get())
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
        self._remember_connection(values)
        self._banner('ok', 'Connection established.')
        self.next_button.config(state='normal')

    def _settings_changed(self, *_):
        if not self.app.db.connected:
            return
        self.app.disconnect()
        self.next_button.config(state='disabled')
        self._banner('info', 'Connection settings changed. Press Connect to use the new ones.')
