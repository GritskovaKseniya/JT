"""Interfaccia Tkinter di JT: schermate, widget, tema, finestra e chiusura.

Ogni test usa una finestra Tk propria e nascosta (`withdraw`), un finto Oracle e un finto Azure: nessuna rete,
nessuna credenziale reale, nessun file nella cartella del progetto (Data e log stanno in una cartella temporanea).
Se non c'e' un display la classe viene saltata.
"""
import contextlib
import glob
import json
import os
import re
import struct
import sys
import threading
import time
import tkinter as tk
import unittest
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402

sys.path.insert(0, os.path.join(helpers.ROOT, 'tools'))
import simulate  # noqa: E402
from jt.layers import LEVEL_CHOICES  # noqa: E402

L_ALL, L_STD, L_CW, L_CT, L_CC = LEVEL_CHOICES          # i nomi del campo Level, nell'ordine
from helpers import FAKE_AZURE, FAKE_CONNECTION, FakeAzure, FakeDB, FakeDriver, JtCase, read_json, write_json  # noqa: E402
from jt.azure import AzureTranslator  # noqa: E402
from jt.config import APP_TITLE, VERSION, WINDOW_MIN_WIDTH  # noqa: E402
from jt.db import Database  # noqa: E402
from jt.glossary import Glossary  # noqa: E402
from jt.runner import BackgroundRunner, InlineRunner  # noqa: E402
from jt.service import Progress  # noqa: E402
from jt.tables import get_table  # noqa: E402
from jt.ui import scale  # noqa: E402
from jt.ui.app import JTApp  # noqa: E402
from jt.ui.connection_screen import ConnectionScreen  # noqa: E402
from jt.ui.dialogs import ConfirmDialog  # noqa: E402
from jt.ui.widgets import NOT_CONNECTED, Collapsible, StatusBar  # noqa: E402
from jt.ui.dpi import enable_dpi_awareness  # noqa: E402
from jt.ui.secret import MESSAGE, open_secret_panel  # noqa: E402
from jt.ui.texts import fmt_count, reason, shorten  # noqa: E402
from jt.ui.theme import FONT, PALETTE  # noqa: E402
from jt.ui.translation_screen import KEYS_HINT, TranslationScreen  # noqa: E402
from jt.tools import Tool  # noqa: E402
from jt.ui.tools_screen import ToolsScreen  # noqa: E402
from jt.ui.app import default_tools  # noqa: E402
from jt.ui.widgets import InfoBar, Stepper, StatusBar, ToolTip, WrapTracker  # noqa: E402

SECONDARY, PRIMARY, DANGER = 'Secondary.TButton', 'Primary.TButton', 'Danger.TButton'
SEP = '·'                      # separatore dei testi (punto mediano)


# ------------------------------------------------------------------ funzioni di supporto

def all_widgets(widget):
    yield widget
    for child in widget.winfo_children():
        yield from all_widgets(child)


def all_texts(widget):
    texts = []
    for w in all_widgets(widget):
        try:
            texts.append(str(w.cget('text')))
        except tk.TclError:
            pass
    return texts


def fire(widget, sequence):
    """Esegue lo script collegato (bind) a un evento, senza bisogno di focus ne' di mouse reale."""
    script = widget.bind(sequence)
    assert script, f'nessun bind per {sequence} su {widget}'
    for code, value in (('%W', str(widget)), ('%A', 'a'), ('%K', 'a'), ('%T', '2')):
        script = script.replace(code, value)
    widget.tk.eval(re.sub(r'%[#bfhkstwxyXYNED]', '0', script))


def strings_only():
    """Gli strumenti dei test dell'interfaccia di Strings: solo Strings (con piu' strumenti il passo 2 e' il guscio)."""
    return [tool for tool in default_tools() if tool.name == 'strings']


def state(widget):
    return str(widget.cget('state'))


def wraplength(widget):
    return int(str(widget.cget('wraplength')))


def quiet_destroy(root):
    """destroy() che prima annulla le chiamate "a riposo" rimaste (il banner ne lascia una per adattare la finestra):
    senza, Tcl scrive 'invalid command name' sulla console quando la finestra sparisce prima che partano."""
    destroy = root.destroy

    def run():
        with contextlib.suppress(tk.TclError):
            for call_id in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', call_id)
        destroy()

    return run


def luminance(color, root):
    """Luminanza relativa WCAG di un colore Tk (nome o #rrggbb)."""
    channels = []
    for value in root.winfo_rgb(color):
        c = value / 65535
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(foreground, background, root):
    """Rapporto di contrasto WCAG tra due colori (da 1 a 21)."""
    a, b = luminance(foreground, root), luminance(background, root)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def plain_rows(count, first=100000):
    return [('it', first + i, f'Testo {i}', None, None, None) for i in range(count)]


class UiCase(JtCase):
    """Un'app completa su una finestra Tk nascosta, con finto database."""

    def setUp(self):
        super().setUp()
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'nessun display: {e}')
        self.root.withdraw()
        self.callback_errors = []
        self.root.report_callback_exception = lambda *exc: self.callback_errors.append(exc)
        self.addCleanup(self._no_callback_errors)       # ultimo a partire (LIFO)
        self.addCleanup(self._close_root)
        self.fake_db = FakeDB()
        self.driver = FakeDriver(self.fake_db)
        self.db = Database(driver=self.driver)
        self.paths = helpers.make_paths(self.tmp)
        self.addCleanup(scale.set_factor, 1.0)           # la scala e' globale: ogni test la ripristina
        self.runner = self.make_runner()
        self.app = JTApp(self.root, self.paths, self.db, runner=self.runner, scale_factor=1.0, tools=strings_only())
        # la conferma prima di scrivere e' una finestra modale: nei test si risponde da sola (self.confirm_answer) e si
        # registra la richiesta; i test della finestra vera la disattivano con self.use_real_confirmation()
        self.key_reason = ''
        self.confirmations = []
        self.confirm_answer = True

        def auto_confirm(_app, question, detail, type_to_confirm=None, ok_text='Write'):
            self.confirmations.append({'question': question, 'detail': detail, 'type_to_confirm': type_to_confirm,
                                       'ok_text': ok_text})
            return self.confirm_answer

        self.confirm_patch = patch.object(JTApp, 'confirm_write', auto_confirm)
        self.key_patch = patch.object(JTApp, 'azure_key_problem', lambda _app: self.key_reason)    # '' = c'e' una chiave valida
        self.key_patch.start()
        self.addCleanup(self.key_patch.stop)
        self.confirm_patch.start()
        self.addCleanup(self.use_real_confirmation)

    def use_real_confirmation(self):
        with contextlib.suppress(RuntimeError):
            self.confirm_patch.stop()

    def make_runner(self):
        """Nei test normali il lavoro gira subito nello stesso thread: nessuna attesa, nessuna corsa."""
        return InlineRunner()

    def _no_callback_errors(self):
        self.assertEqual(self.callback_errors, [], 'eccezioni dentro callback di Tk')

    def _close_root(self):
        self.db.close()
        root = self.root
        try:
            root.update_idletasks()            # prima le chiamate "a riposo", con l'app ancora viva
            for call_id in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', call_id)     # grezzo: i widget cancellano i propri comandi
        except tk.TclError:
            pass                                # la finestra e' gia' stata chiusa dal test
        with contextlib.suppress(tk.TclError):
            root.destroy()

    # ---- scorciatoie

    @property
    def screen(self):
        return self.app.screen

    def step2(self, saved=None, connect=True):
        """Passo 2 (con connessione al finto DB, salvo connect=False). `saved` = query_data.json precedente."""
        if saved is not None:
            write_json(self.paths.query, saved)
        if connect and not self.db.connected:
            self.app.connect(dict(FAKE_CONNECTION))
            self.assertTrue(self.db.connected)
        self.app.show_translation()
        return self.screen

    def use_azure(self, fail_on=None):
        azure = FakeAzure(fail_on)
        translator = AzureTranslator(FAKE_AZURE, Glossary.load(self.paths.glossary), post=azure)
        patcher = patch.object(JTApp, 'make_translator', lambda _self: translator)
        patcher.start()
        self.addCleanup(patcher.stop)
        return azure

    def hook_progress(self, screen, hook):
        """Dopo ogni riga tradotta chiama hook(progress): permette di guardare la finestra a meta' lavoro.
        Con InlineRunner l'hook gira dentro il lavoro, quando la schermata e' nello stato "in corso"
        (le etichette di avanzamento invece si aggiornano solo a fine lavoro: la lettura e' differita)."""
        original = self.app.service.run

        def run(selection, translator, on_progress=None, should_stop=None):
            def progress(p):
                if on_progress:
                    on_progress(p)
                hook(p)

            return original(selection, translator, on_progress=progress, should_stop=should_stop)

        patcher = patch.object(self.app.service, 'run', run)
        patcher.start()
        self.addCleanup(patcher.stop)

    def log_name(self, text):
        """Nome del file di log citato nel banner finale (dopo 'Log: Logs' e una barra rovesciata), o None."""
        match = re.search(r'Log: Logs\\(\S+\.csv)(?:\s|$)', text)
        return match.group(1) if match else None

    def choose(self, screen, lan_in='Italian', lan_out='English', table='JFX: Strings', max_rows='5', keys=''):
        screen.var_in.set(lan_in)
        screen.var_out.set(lan_out)
        screen.var_table.set(table)
        screen.var_max.set(max_rows)
        screen.var_keys.set(keys)

    def loaded_strings(self, rows=2, **choice):
        """Passo 2 con FW_STRINGS it -> en caricata ('Load' gia' premuto); `rows` righe da tradurre."""
        self.fake_db.source['FW_STRINGS'] = plain_rows(rows)
        self.fake_db.missing['FW_STRINGS'] = rows
        screen = self.step2()
        self.choose(screen, **choice)
        screen.load()
        self.assertIsNotNone(screen.selection)
        return screen

    def wait_for(self, predicate, timeout=3.0):
        end = time.time() + timeout
        while not predicate() and time.time() < end:
            self.root.update()
            time.sleep(0.01)
        return predicate()

    def logs(self, prefix):
        return glob.glob(os.path.join(self.paths.logs, f'JT_{prefix}_log_*.csv'))

    def drive_dialog(self, trigger, action, delay=10):
        """Esegue `trigger()` (apre il dialogo reale e aspetta) e, a dialogo aperto, `action(dialog, seen)`.
        Ritorna (valore di trigger, seen). Un errore nell'action viene rilanciato; il dialogo si chiude sempre."""
        seen = {}

        def run():
            dialog = self.app.last_dialog
            try:
                action(dialog, seen)
            except BaseException as e:           # noqa: BLE001 - rilanciata dopo, fuori da Tk
                seen['error'] = e
            finally:
                with contextlib.suppress(tk.TclError):
                    if dialog.top.winfo_exists():
                        dialog.top.destroy()

        def failsafe():
            seen.setdefault('error', AssertionError('dialogo rimasto aperto'))
            for w in self.root.winfo_children():
                if isinstance(w, tk.Toplevel):
                    w.destroy()

        self.root.after(delay, run)
        guard = self.root.after(5000, failsafe)
        value = trigger()
        with contextlib.suppress(tk.TclError):
            self.root.after_cancel(guard)
        if 'error' in seen:
            raise seen['error']
        return value, seen

    def geometry_for(self, show, screen_height=None, window_y=None):
        """Mostra una schermata e ritorna (larghezza, altezza, x, y) richiesti alla finestra."""
        with contextlib.ExitStack() as stack:
            geometry = stack.enter_context(patch.object(self.root, 'geometry'))
            if screen_height:
                stack.enter_context(patch.object(self.root, 'winfo_screenheight', return_value=screen_height))
            if window_y is not None:
                self.app._placed = True              # la finestra e' gia' stata posizionata dall'utente
                stack.enter_context(patch.object(self.root, 'winfo_y', return_value=window_y))
            show()
        match = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', geometry.call_args.args[0])
        return tuple(int(v) for v in match.groups())


# ===================================================================== passo 1: connessione

class ConnectionScreenTests(UiCase):
    def test_builds_with_the_saved_values(self):
        self.assertIsInstance(self.screen, ConnectionScreen)
        self.assertEqual({k: v.get() for k, v in self.screen.vars.items()}, FAKE_CONNECTION)
        self.root.update_idletasks()
        self.assertEqual(self.screen.entries['host'].get(), 'fake-host')

    def test_password_is_masked_and_other_fields_are_not(self):
        self.assertEqual(str(self.screen.entries['password'].cget('show')), '*')
        for key in ('host', 'port', 'sid', 'username'):
            self.assertEqual(str(self.screen.entries[key].cget('show')), '', key)

    def test_missing_settings_file_gives_empty_fields(self):
        os.remove(self.paths.connection)
        self.app.show_connection()
        self.assertEqual({k: v.get() for k, v in self.screen.vars.items()},
                         dict.fromkeys(FAKE_CONNECTION, ''))

    def focus_calls(self, build):
        calls, original = [], tk.Misc.focus_set

        def spy(widget):
            calls.append(widget)
            return original(widget)

        with patch.object(tk.Misc, 'focus_set', spy):
            build()
        return calls

    def test_initial_focus_is_on_the_host_field(self):
        calls = self.focus_calls(self.app.show_connection)
        self.assertEqual(str(calls[-1]), str(self.screen.entries['host']))

    def test_initial_state_next_disabled_and_status_info(self):
        self.assertEqual(state(self.screen.next_button), 'disabled')
        self.assertEqual(self.screen.status.state, 'info')
        self.assertFalse(self.db.connected)

    def test_connect_success_enables_next_and_saves_the_settings(self):
        self.screen.vars['host'].set('other-host')
        self.screen.vars['sid'].set('OTHERSID')
        self.screen.connect_button.invoke()
        self.assertEqual(self.screen.status.state, 'ok')
        self.assertIn('Connection established', self.screen.status.message.cget('text'))
        self.assertEqual(state(self.screen.next_button), 'normal')
        self.assertTrue(self.db.connected)
        self.assertEqual(self.driver.connects, [('fake_user', 'fake_password', 'other-host:1521/OTHERSID')])
        saved = read_json(self.paths.connection)
        self.assertEqual(saved['host'], 'other-host')
        self.assertEqual(saved['sid'], 'OTHERSID')
        self.assertEqual(saved['password'], 'fake_password')

    def test_connect_failure_shows_the_first_line_and_keeps_next_disabled(self):
        self.fake_db.fail_connect = True            # FakeDriver: "ORA-12541: no listener"
        before = read_json(self.paths.connection)
        self.screen.connect_button.invoke()
        self.assertEqual(self.screen.status.state, 'error')
        self.assertIn('ORA-12541: no listener', self.screen.status.message.cget('text'))
        self.assertEqual(state(self.screen.next_button), 'disabled')
        self.assertFalse(self.db.connected)
        self.assertEqual(read_json(self.paths.connection), before)       # un tentativo fallito non salva nulla

    def test_connect_failure_message_is_only_the_first_line_and_is_cut(self):
        error = RuntimeError('ORA-01017: invalid username/password\nsecond line of the stack\nthird')
        with patch.object(self.driver, 'connect', side_effect=error):
            self.screen.connect()
        text = self.screen.status.message.cget('text')
        self.assertIn('ORA-01017: invalid username/password', text)
        self.assertNotIn('second line', text)
        with patch.object(self.driver, 'connect', side_effect=RuntimeError('X' * 500)):
            self.screen.connect()
        text = self.screen.status.message.cget('text')
        self.assertTrue(text.startswith('Connection failed: XXX') and text.endswith('...'))
        self.assertLess(len(text), 200)                  # (shorten aggiunge '...' oltre il limite: vedi TextsTests)
        words = RuntimeError('ORA-12154: ' + 'word ' * 60)
        with patch.object(self.driver, 'connect', side_effect=words):
            self.screen.connect()
        text = self.screen.status.message.cget('text')
        self.assertTrue(text.endswith('word...'), text)  # taglio a confine di parola

    def test_connect_failure_with_empty_message(self):
        with patch.object(self.driver, 'connect', side_effect=RuntimeError('')):
            self.screen.connect()
        self.assertEqual(self.screen.status.message.cget('text'), 'Connection failed')
        self.assertEqual(self.screen.status.state, 'error')

    def test_failure_after_a_success_disables_next_and_leaves_no_connection(self):
        self.screen.connect()
        self.assertEqual(state(self.screen.next_button), 'normal')
        self.fake_db.fail_connect = True
        self.screen.connect()
        self.assertEqual(state(self.screen.next_button), 'disabled')
        self.assertFalse(self.db.connected)
        self.assertTrue(self.fake_db.conns[0].closed)

    def test_return_key_in_every_entry_triggers_connect(self):
        for key, entry in self.screen.entries.items():
            with self.subTest(field=key):
                self.db.close()
                self.screen.status.show('info', 'idle')
                fire(entry, '<Return>')
                self.assertEqual(self.screen.status.state, 'ok')
                self.assertTrue(self.db.connected)

    def test_connect_twice_closes_the_previous_connection(self):
        self.screen.connect()
        self.screen.connect()
        first, second = self.fake_db.conns
        self.assertTrue(first.closed)
        self.assertFalse(second.closed)

    def test_next_goes_to_step_two_and_the_stepper_follows(self):
        self.screen.connect()
        self.screen.next_button.invoke()
        self.assertIsInstance(self.screen, TranslationScreen)
        self.assertEqual(self.app.stepper.step, 2)
        self.assertTrue(self.db.connected)

    def test_next_does_nothing_while_disabled(self):
        self.screen.next_button.invoke()
        self.assertIsInstance(self.screen, ConnectionScreen)
        self.assertEqual(self.app.stepper.step, 1)

    def test_pressing_connect_shows_connecting_before_the_result(self):
        seen = []
        original = self.app.connect

        def spy(values):
            seen.append((self.screen.status.state, self.screen.status.message.cget('text'),
                         str(self.root.cget('cursor'))))
            original(values)

        with patch.object(self.app, 'connect', spy):
            self.screen.connect()
        self.assertEqual(seen, [('info', 'Connecting...', 'watch')])
        self.assertEqual(self.screen.status.state, 'ok')
        self.assertEqual(str(self.root.cget('cursor')), '')

    def test_failed_connect_resets_the_busy_cursor(self):
        self.fake_db.fail_connect = True
        self.screen.connect()
        self.assertEqual(str(self.root.cget('cursor')), '')

    def test_editing_any_field_while_connected_closes_the_connection(self):
        for key in self.screen.vars:
            with self.subTest(field=key):
                self.screen.connect()
                self.assertTrue(self.db.connected)
                self.assertEqual(state(self.screen.next_button), 'normal')
                self.screen.vars[key].set(self.screen.vars[key].get() + 'x')
                self.assertFalse(self.db.connected)
                self.assertTrue(self.fake_db.conns[-1].closed)
                self.assertEqual(state(self.screen.next_button), 'disabled')
                self.assertEqual(self.screen.status.state, 'info')
                self.assertEqual(self.screen.status.message.cget('text'),
                                 'Connection settings changed. Press Connect to use the new ones.')
                self.assertEqual(self.app.infobar.label.cget('text'), NOT_CONNECTED)

    def test_editing_a_field_without_a_connection_changes_nothing(self):
        self.screen.status.show('error', 'previous')
        self.screen.vars['host'].set('somewhere')
        self.assertEqual(self.screen.status.message.cget('text'), 'previous')
        self.assertEqual(state(self.screen.next_button), 'disabled')

    def test_typing_into_the_entry_closes_the_connection_too(self):
        self.screen.connect()
        self.screen.entries['host'].insert('end', 'x')
        self.assertFalse(self.db.connected)

    def test_connect_works_again_after_the_settings_changed(self):
        self.screen.connect()
        self.screen.vars['sid'].set('OTHER')
        self.screen.connect()
        self.assertTrue(self.db.connected)
        self.assertEqual(self.screen.status.state, 'ok')
        self.assertEqual(state(self.screen.next_button), 'normal')
        self.assertEqual(self.driver.connects[-1][2], 'fake-host:1521/OTHER')

    def test_connect_does_not_touch_the_infobar_on_failure(self):
        self.fake_db.fail_connect = True
        self.screen.connect()
        self.assertEqual(self.app.infobar.label.cget('text'), NOT_CONNECTED)


# ===================================================================== barra della connessione

class InfoBarTests(UiCase):
    def text(self):
        return self.app.infobar.label.cget('text')

    def dot(self):
        return str(self.app.infobar.dot.cget('fg'))

    def test_starts_not_connected_with_a_grey_dot(self):
        self.assertIsInstance(self.app.infobar, InfoBar)
        self.assertEqual(self.text(), NOT_CONNECTED)
        self.assertNotIn(self.dot(), (PALETTE['ok'], PALETTE['error'], PALETTE['warn']))
        self.assertEqual(self.dot(), '#8a94a6')

    def test_it_sits_at_the_bottom_of_the_window(self):
        self.assertEqual(self.app.infobar.pack_info()['side'], 'bottom')
        self.assertEqual(self.app.stepper.pack_info()['side'], 'top')

    def test_connected_shows_the_database_name_the_server_reports(self):
        self.fake_db.db_name = 'PRODDB'
        self.screen.connect()
        self.assertEqual(self.text(), f'Connected to PRODDB   {SEP}   fake-host   {SEP}   user fake_user')
        self.assertEqual(self.dot(), PALETTE['ok'])
        self.assertEqual(self.db.info, {'host': 'fake-host', 'port': '1521', 'sid': 'FAKESID', 'user': 'fake_user',
                                        'db_name': 'PRODDB', 'environment': ''})

    def test_it_falls_back_to_the_typed_sid_when_the_server_does_not_answer(self):
        self.fake_db.db_name = None
        self.screen.connect()
        self.assertEqual(self.db.info['db_name'], None)
        self.assertEqual(self.text(), f'Connected to FAKESID   {SEP}   fake-host   {SEP}   user fake_user')

    def test_the_db_name_query_is_not_a_write_and_is_answered_after_connecting(self):
        self.screen.connect()
        self.assertEqual(self.fake_db.writes(), [])

    def test_failed_first_connection_keeps_it_not_connected(self):
        self.fake_db.fail_connect = True
        self.screen.connect()
        self.assertEqual(self.text(), NOT_CONNECTED)
        self.assertNotEqual(self.dot(), PALETTE['ok'])

    def test_failed_reconnection_must_not_leave_the_old_database_on_display(self):
        # Database.connect() chiude prima la vecchia connessione: se la nuova fallisce la barra non deve restare su
        # "Connected to ..." mentre non c'e' nulla di aperto.
        self.screen.connect()
        self.fake_db.fail_connect = True
        self.screen.connect()
        self.assertFalse(self.db.connected)
        self.assertEqual(self.text(), NOT_CONNECTED)

    def test_new_connection_goes_back_to_not_connected(self):
        self.step2()
        self.assertTrue(self.text().startswith('Connected to FAKEDB'))
        fire(self.app.stepper.link, '<Button-1>')
        self.assertEqual(self.text(), NOT_CONNECTED)
        self.assertEqual(self.dot(), '#8a94a6')
        self.assertIsNone(self.app.infobar.info)

    def test_the_infobar_survives_the_change_of_step(self):
        self.step2()
        self.assertTrue(self.app.infobar.winfo_exists())
        self.assertTrue(self.text().startswith('Connected to'))
        self.assertEqual(self.app.infobar.winfo_manager(), 'pack')

    def test_closing_the_application_resets_it(self):
        self.step2()
        with patch.object(JTApp, 'confirm', return_value=True):
            self.app.on_closing()
        # (la finestra e' stata distrutta: lo stato lo si legge dal database)
        self.assertFalse(self.db.connected)
        self.assertIsNone(self.db.info)

    def test_disconnect_resets_the_infobar_and_the_database_info(self):
        self.step2()
        self.app.disconnect()
        self.assertEqual(self.text(), NOT_CONNECTED)
        self.assertIsNone(self.db.info)
        self.app.disconnect()                      # ripetibile
        self.assertEqual(self.text(), NOT_CONNECTED)

    def test_long_text_is_shortened(self):
        self.app.infobar.set_connected({'db_name': 'D' * 10, 'host': 'h ' * 100, 'port': 1, 'sid': 's', 'user': 'u'})
        self.assertLessEqual(len(self.text()), 85)
        self.assertIn('...', self.text())                          # il pezzo troppo lungo (host) e' accorciato
        self.assertTrue(self.text().endswith('user u'))            # e il resto della riga resta intero
        self.assertIn(f'   {SEP}   ', self.text())                 # gli spazi attorno ai separatori non si compattano

    def test_tooltip_lists_database_sid_host_and_user(self):
        hint = self.app.infobar._hint()
        self.assertEqual(hint['rows'], [('Status', 'Not connected')])
        self.fake_db.db_name = 'PRODDB'
        self.screen.connect()
        hint = self.app.infobar._hint()
        self.assertEqual(hint['title'], 'Database connection')
        self.assertEqual(hint['rows'], [('Database', 'PRODDB'), ('SID', 'FAKESID'), ('Host', 'fake-host:1521'),
                                        ('User', 'fake_user'), ('Environment', 'not set (treated as prod)')])
        self.assertNotIn('footer', hint)                    # suggerimento compatto: niente piede

    def test_tooltip_hides_the_sid_when_it_is_the_same_as_the_database_name(self):
        self.fake_db.db_name = 'fakesid'                    # stesso nome, maiuscole diverse
        self.screen.connect()
        self.assertEqual(self.app.infobar._hint()['rows'],
                         [('Database', 'fakesid'), ('Host', 'fake-host:1521'), ('User', 'fake_user'),
                          ('Environment', 'not set (treated as prod)')])

    def test_tooltip_without_a_reported_name_says_so(self):
        self.fake_db.db_name = None
        self.screen.connect()
        self.assertEqual(self.app.infobar._hint()['rows'][0], ('Database', '(not reported by the server)'))

    def tips_of_the_infobar(self):
        row = self.app.infobar.label.master
        return [w for w in row.winfo_children() if isinstance(w, tk.Toplevel)]

    def test_one_tooltip_only_whichever_part_of_the_line_is_hovered(self):
        self.screen.connect()
        bar = self.app.infobar
        row = bar.label.master
        for widget in (row, bar.dot, bar.label, row, bar.label):
            fire(widget, '<Enter>')
            self.assertEqual(len(self.tips_of_the_infobar()), 1)
        # passare da un pezzo all'altro (il puntatore e' ancora sulla riga) non lo chiude
        with patch.object(row, 'winfo_containing', return_value=bar.label):
            fire(row, '<Leave>')
        self.assertEqual(len(self.tips_of_the_infobar()), 1)
        # uscire davvero dalla riga lo chiude
        with patch.object(row, 'winfo_containing', return_value=None):
            fire(bar.label, '<Leave>')
        self.assertEqual(self.tips_of_the_infobar(), [])

    def test_tooltip_opens_on_the_label_and_the_row(self):
        self.screen.connect()
        label = self.app.infobar.label
        fire(label, '<Enter>')
        tips = self.tips_of_the_infobar()
        self.assertEqual(len(tips), 1)
        texts = ' '.join(all_texts(tips[0]))
        for text in ('Database connection', 'FAKEDB', 'FAKESID', 'fake-host:1521', 'fake_user'):
            self.assertIn(text, texts)
        with patch.object(label, 'winfo_containing', return_value=None):
            fire(label, '<Leave>')
        self.assertEqual(self.tips_of_the_infobar(), [])
        row = label.master
        fire(row, '<Enter>')
        self.assertEqual(len(self.tips_of_the_infobar()), 1)
        with patch.object(row, 'winfo_containing', return_value=None):
            fire(row, '<Leave>')


# ===================================================================== pannello dei passi

class StepperTests(UiCase):
    def test_step_one_is_active(self):
        stepper = self.app.stepper
        self.assertEqual(stepper.step, 1)
        self.assertEqual(list(stepper.states), ['current', 'todo'])

    def test_done_step_is_marked_done(self):
        self.step2()
        stepper = self.app.stepper
        self.assertEqual(stepper.step, 2)
        self.assertEqual(list(stepper.states), ['done', 'current'])
        self.app.show_connection()
        self.assertEqual(list(stepper.states), ['current', 'todo'])

    def test_new_connection_link_is_hidden_on_step_one_and_visible_on_step_two(self):
        link = self.app.stepper.link
        self.assertEqual(link.cget('text'), 'New connection')
        self.assertEqual(link.winfo_manager(), '')
        self.step2()
        self.assertEqual(link.winfo_manager(), 'grid')
        self.app.show_connection()
        self.assertEqual(link.winfo_manager(), '')

    def test_clicking_the_link_closes_the_connection_and_returns_to_step_one(self):
        self.step2()
        fire(self.app.stepper.link, '<Button-1>')
        self.assertIsInstance(self.screen, ConnectionScreen)
        self.assertEqual(self.app.stepper.step, 1)
        self.assertFalse(self.db.connected)
        self.assertTrue(self.fake_db.conns[0].closed)
        self.assertEqual(state(self.screen.next_button), 'disabled')

    def test_disabled_link_is_greyed_and_ignored(self):
        self.step2()
        stepper = self.app.stepper
        stepper.set_link_enabled(False)
        self.assertEqual(str(stepper.link.cget('fg')), PALETTE['muted'])
        self.assertEqual(str(stepper.link.cget('cursor')), 'arrow')
        fire(stepper.link, '<Button-1>')
        self.assertIsInstance(self.screen, TranslationScreen)
        self.assertTrue(self.db.connected)
        stepper.set_link_enabled(True)
        self.assertEqual(str(stepper.link.cget('fg')), PALETTE['accent'])
        self.assertEqual(str(stepper.link.cget('cursor')), 'hand2')

    def test_link_is_ignored_while_a_translation_runs(self):
        screen = self.loaded_strings(2)
        self.use_azure()
        seen = {}

        def during(progress):
            if 'link' in seen:
                return
            seen['link'] = str(self.app.stepper.link.cget('fg'))
            fire(self.app.stepper.link, '<Button-1>')
            seen['still_here'] = self.app.screen is screen and self.db.connected

        self.hook_progress(screen, during)
        screen.translate()
        self.assertEqual(seen['link'], PALETTE['muted'])
        self.assertTrue(seen['still_here'])
        self.assertEqual(str(self.app.stepper.link.cget('fg')), PALETTE['accent'])    # riabilitato a fine lavoro

    def test_go_back_is_ignored_while_translating(self):
        self.step2()
        self.app.translating = True
        self.app.go_back()
        self.assertIsInstance(self.screen, TranslationScreen)
        self.assertTrue(self.db.connected)
        self.app.translating = False
        self.app.go_back()
        self.assertIsInstance(self.screen, ConnectionScreen)

    GRAPHICS = os.path.join(helpers.ROOT, 'Graphics')

    def stepper_at(self, factor, graphics=GRAPHICS):
        scale.set_factor(factor)
        stepper = Stepper(self.root, lambda: None, graphics)
        self.addCleanup(stepper.destroy)
        return stepper

    def test_badge_images_follow_the_scale_factor(self):
        for factor, size in ((1.0, 24), (1.25, 30), (1.5, 36), (2.0, 48)):
            with self.subTest(factor=factor):
                stepper = self.stepper_at(factor)
                self.assertEqual(sorted(stepper._images), sorted(Stepper.IMAGES))      # solo i 4 pallini che compaiono
                for image in stepper._images.values():
                    self.assertEqual((image.width(), image.height()), (size, size))
                badge = stepper._badges[0]
                self.assertEqual(str(badge.cget('image')), str(stepper._images[(1, 'current')]))

    def test_badge_size_thresholds(self):
        for factor, size in ((1.0, 24), (1.09, 24), (1.1, 30), (1.34, 30), (1.35, 36), (1.74, 36), (1.75, 48),
                             (3.0, 48)):
            with self.subTest(factor=factor):
                self.assertEqual(self.stepper_at(factor)._images[(1, 'done')].width(), size)

    def test_badges_follow_the_states(self):
        stepper = self.stepper_at(1.0)
        stepper.set_active(2)
        self.assertEqual(str(stepper._badges[0].cget('image')), str(stepper._images[(1, 'done')]))
        self.assertEqual(str(stepper._badges[1].cget('image')), str(stepper._images[(2, 'current')]))
        stepper.set_active(1)
        self.assertEqual(str(stepper._badges[1].cget('image')), str(stepper._images[(2, 'todo')]))

    def test_without_images_the_stepper_falls_back_to_text_badges(self):
        for graphics in (self.tmp, None):
            with self.subTest(graphics=graphics):
                stepper = self.stepper_at(1.0, graphics)
                self.assertEqual(stepper._images, {})
                self.assertEqual([str(b.cget('text')) for b in stepper._badges], ['1', '2'])
                stepper.set_active(2)
                self.assertEqual([str(b.cget('text')) for b in stepper._badges], ['✔', '2'])
                self.assertEqual(str(stepper._badges[0].cget('bg')), PALETTE['ok'])
                self.assertEqual(str(stepper._badges[1].cget('bg')), PALETTE['accent'])

    def test_a_single_missing_image_means_text_mode_for_all(self):
        folder = os.path.join(self.tmp, 'g')
        os.mkdir(folder)
        for name in os.listdir(self.GRAPHICS):
            if name.startswith('step_') and name != 'step_2_todo.png':
                with open(os.path.join(self.GRAPHICS, name), 'rb') as src, open(os.path.join(folder, name), 'wb') as dst:
                    dst.write(src.read())
        self.assertEqual(self.stepper_at(1.0, folder)._images, {})

    def test_link_is_muted_when_disabled_and_accent_when_enabled(self):
        stepper = self.stepper_at(1.0)
        stepper.set_link_enabled(False)
        self.assertEqual(str(stepper.link.cget('fg')), PALETTE['muted'])
        stepper.set_link_enabled(True)
        self.assertEqual(str(stepper.link.cget('fg')), PALETTE['accent'])


# ===================================================================== passo 2: costruzione

class TranslationScreenBuildTests(UiCase):
    DISABLED = {'linput': 'Italian', 'loutput': 'German', 'table': 'SFC: Strings & Triplets'}

    def test_saved_disabled_table_is_not_selected(self):
        screen = self.step2(self.DISABLED)
        self.assertNotEqual(screen.var_table.get(), 'SFC: Strings & Triplets')
        self.assertEqual(screen.var_table.get(), 'JFX: Strings')           # la prima tabella abilitata
        self.assertNotIn('SFC: Strings & Triplets', list(screen.cmb_table.cget('values')))

    def test_saved_disabled_table_is_not_selected_without_connection_either(self):
        screen = self.step2(self.DISABLED, connect=False)
        self.assertEqual(screen.var_table.get(), 'JFX: Strings')

    def test_saved_languages_and_table_are_honoured(self):
        screen = self.step2({'linput': 'French', 'loutput': 'Spanish', 'table': 'JFX: Options'})
        self.assertEqual((screen.var_in.get(), screen.var_out.get(), screen.var_table.get()),
                         ('French', 'Spanish', 'JFX: Options'))

    def test_unknown_saved_language_falls_back_to_the_first_one(self):
        screen = self.step2({'linput': 'Klingon', 'loutput': 'German', 'table': 'JFX: Strings'})
        self.assertEqual(screen.var_in.get(), screen.cmb_in.cget('values')[0])
        self.assertEqual(screen.var_out.get(), 'German')

    def test_tables_that_do_not_exist_on_the_db_are_not_offered(self):
        self.fake_db.invalid_tables = {'FW_OPZIONI_TRE'}
        screen = self.step2()
        self.assertNotIn('JFX: Options three', list(screen.cmb_table.cget('values')))
        self.assertIn('JFX: Options two', list(screen.cmb_table.cget('values')))

    def test_without_a_connection_all_the_enabled_tables_are_offered(self):
        self.fake_db.invalid_tables = {'FW_OPZIONI_TRE'}            # senza connessione non si puo' sapere
        screen = self.step2(connect=False)
        enabled = [e['description'] for e in self.app.catalog.tables()]
        self.assertEqual(list(screen.cmb_table.cget('values')), enabled)
        self.assertEqual(self.app.available_tables(), self.app.catalog.tables())
        self.assertEqual(self.fake_db.count('ROWNUM'), 0)

    def test_available_tables_uses_the_existence_check_only_when_connected(self):
        self.fake_db.invalid_tables = {'FW_OPZIONI_TRE', 'FW_STRINGS'}
        self.assertEqual(len(self.app.available_tables()), len(self.app.catalog.tables()))
        self.app.connect(dict(FAKE_CONNECTION))
        names = [e['table'] for e in self.app.available_tables()]
        self.assertNotIn('FW_STRINGS', names)
        self.assertNotIn('FW_OPZIONI_TRE', names)
        self.assertIn('FW_OPZIONI', names)

    def test_when_no_table_exists_the_screen_explains_it_and_load_is_disabled(self):
        self.fake_db.invalid_tables = {e['table'] for e in self.app.catalog.tables()}
        screen = self.step2()
        self.assertEqual(list(screen.cmb_table.cget('values')), [])
        self.assertEqual(screen.var_table.get(), '')
        self.assertEqual(state(screen.load_button), 'disabled')
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(screen.label_missing.cget('text'), 'No table available.')
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'),
                         'None of the configured tables exist in this database. Check Data/tables.json.')
        screen.load_button.invoke()                                  # disabilitato: nessuna query
        self.assertEqual(self.fake_db.count('SELECT * FROM'), 0)
        self.wait_for(lambda: False, timeout=0.3)                     # e il conteggio non parte
        self.assertEqual(self.fake_db.count('SELECT COUNT'), 0)
        self.assertEqual(screen.label_missing.cget('text'), 'No table available.')

    def test_initial_defaults(self):
        screen = self.step2()
        self.assertEqual(screen.var_max.get(), '1')
        self.assertEqual(screen.var_keys.get(), '')
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertIsNone(screen.selection)
        self.assertEqual(screen.status.state, 'info')
        self.assertEqual(screen.label_bar.cget('text'), 'Waiting to start')

    def test_label_missing_asks_to_connect_when_there_is_no_connection(self):
        screen = self.step2(connect=False)
        screen.refresh_missing()
        self.assertIn('Connect', screen.label_missing.cget('text'))
        self.assertEqual(self.fake_db.count('COUNT'), 0)

    def test_counting_starts_by_itself_after_a_short_delay(self):
        self.fake_db.missing = {'FW_STRINGS': 7}
        screen = self.step2()
        self.assertEqual(screen.label_missing.cget('text'), 'Counting missing translations...')
        self.assertTrue(self.wait_for(lambda: screen.label_missing.cget('text').startswith('Missing in')))
        self.assertIn('7 in this table', screen.label_missing.cget('text'))

    def test_leaving_the_screen_before_the_delay_cancels_the_counting(self):
        self.step2()
        self.app.go_back()
        self.wait_for(lambda: False, timeout=0.25)       # lascia passare i 150 ms
        self.assertEqual(self.fake_db.count('SELECT COUNT'), 0)
        self.assertEqual(self.callback_errors, [])

    def test_refresh_missing_shows_thousands_separators_and_the_totals(self):
        self.fake_db.missing = {'FW_STRINGS': 1234, 'FW_FIELD_STRINGS': 5, 'FW_OPZIONI': 20000}
        screen = self.step2()
        screen.refresh_missing()
        self.assertEqual(screen.label_missing.cget('text'),
                         'Missing in German (Standard): 1.234 in this table, 21.239 in all tables')
        self.assertEqual(str(screen.label_missing.cget('fg')), PALETTE['accent'])
        self.assertEqual(screen.counts['FW_FIELD_STRINGS'], 5)

    def test_missing_label_follows_the_selected_table(self):
        self.fake_db.missing = {'FW_STRINGS': 1234, 'FW_FIELD_STRINGS': 5}
        screen = self.step2()
        screen.refresh_missing()
        screen.var_table.set('JFX: Triplets')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.label_missing.cget('text'),
                         'Missing in German (Standard): 5 in this table, 1.239 in all tables')
        screen.var_table.set('JFX: Options')                    # nessun conteggio > 0: "0"
        screen.update_missing_label()
        self.assertIn('0 in this table', screen.label_missing.cget('text'))

    def test_missing_label_follows_the_languages(self):
        self.fake_db.missing = {'FW_STRINGS': 3}
        screen = self.step2()
        screen.var_out.set('French')
        screen.cmb_out.event_generate('<<ComboboxSelected>>')
        self.assertIn('Missing in French (Standard): 3 in this table', screen.label_missing.cget('text'))
        binds = [b for s, b in self.fake_db.log if s.startswith('SELECT COUNT(*)')]
        self.assertTrue(binds and all((b['li'], b['lo']) == ('it', 'fr') for b in binds[-9:]))     # + filtro Standard

    def test_nothing_missing_anywhere_is_shown_in_the_ok_colour(self):
        screen = self.step2()
        screen.refresh_missing()
        self.assertEqual(screen.label_missing.cget('text'),
                         'Missing in German (Standard): 0 in this table, 0 in all tables')
        self.assertEqual(str(screen.label_missing.cget('fg')), PALETTE['ok'])

    def test_same_language_message_and_counts_cleared(self):
        self.fake_db.missing = {'FW_STRINGS': 3}
        screen = self.step2()
        screen.refresh_missing()
        screen.var_out.set(screen.var_in.get())
        screen.refresh_missing()
        self.assertEqual(screen.label_missing.cget('text'), 'Choose two different languages.')
        self.assertEqual(screen.counts, {})

    def test_failed_count_of_one_table_shows_a_question_mark_and_does_not_block_the_others(self):
        self.fake_db.missing = {'FW_STRINGS': 1500}
        screen = self.step2()
        self.fake_db.fail_sql = ['FROM FW_OPZIONI_DUE X']
        screen.refresh_missing()
        rows = dict(screen.missing_hint()['rows'])
        self.assertEqual(rows['JFX: Options two'], '?')
        self.assertEqual(rows['JFX: Strings'], '1.500')
        self.assertIn('1.500 in this table', screen.label_missing.cget('text'))
        self.assertTrue(screen.label_missing.cget('text').endswith('(some tables could not be counted)'))
        self.assertEqual(str(screen.label_missing.cget('fg')), PALETTE['warn'])

    def test_when_every_count_fails_the_label_says_so_in_the_warning_colour(self):
        screen = self.step2()
        self.fake_db.fail_sql = ['SELECT COUNT']
        screen.refresh_missing()
        self.assertEqual(screen.label_missing.cget('text'),
                         'Could not count the missing translations (see the console).')
        self.assertEqual(str(screen.label_missing.cget('fg')), PALETTE['warn'])
        self.assertTrue(all(n is None for n in screen.counts.values()))
        self.assertEqual(str(self.root.cget('cursor')), '')
        screen.update_missing_label()                               # anche da un cambio di tabella
        self.assertIn('Could not count', screen.label_missing.cget('text'))

    def test_the_colour_goes_back_to_normal_when_a_later_count_succeeds(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        screen = self.step2()
        self.fake_db.fail_sql = ['SELECT COUNT']
        screen.refresh_missing()
        self.fake_db.fail_sql = []
        screen.refresh_missing()
        self.assertEqual(str(screen.label_missing.cget('fg')), PALETTE['accent'])
        self.assertIn('4 in this table', screen.label_missing.cget('text'))

    def test_a_failed_count_of_the_selected_table_shows_a_question_mark(self):
        self.fake_db.missing = {'FW_FIELD_STRINGS': 2}
        screen = self.step2()
        self.fake_db.fail_sql = ['FROM FW_STRINGS X']
        screen.refresh_missing()
        self.assertIn('? in this table, 2 in all tables (some tables could not be counted)',
                      screen.label_missing.cget('text'))

    def test_count_error_leaves_the_busy_cursor_reset(self):
        screen = self.step2()
        with patch.object(self.app.service, 'missing_counts', side_effect=RuntimeError('boom')):
            screen.refresh_missing()
        self.assertEqual(str(self.root.cget('cursor')), '')

    def test_missing_hint_rows(self):
        self.fake_db.missing = {'FW_STRINGS': 1234, 'FW_FIELD_STRINGS': 5}
        screen = self.step2()
        self.assertEqual(screen.missing_hint()['rows'], [('-', 'not counted yet')])
        screen.refresh_missing()
        hint = screen.missing_hint()
        self.assertEqual(hint['title'], 'Missing translations: Italian → German [Standard]')
        self.assertNotIn('intro', hint)
        self.assertEqual(hint['rows'][0], ('JFX: Strings', '1.234'))
        self.assertEqual(hint['rows'][1], ('JFX: Triplets', '5'))
        self.assertEqual(len(hint['rows']), len(screen.entries))
        self.assertNotIn('footer', hint)                      # compatto

    def test_both_screens_use_the_status_bar(self):
        self.assertIsInstance(self.screen.status, StatusBar)
        self.assertIsInstance(self.step2().status, StatusBar)

    def test_buttons_use_the_primary_and_secondary_styles(self):
        step1 = self.screen
        self.assertEqual(str(step1.connect_button.cget('style')), SECONDARY)
        self.assertEqual(str(step1.next_button.cget('style')), PRIMARY)
        screen = self.step2()
        self.assertEqual(str(screen.load_button.cget('style')), SECONDARY)
        self.assertEqual(str(screen.translate_button.cget('style')), PRIMARY)

    def test_tooltips_are_wired_to_the_label_and_the_keys_field(self):
        screen = self.step2()
        screen.refresh_missing()
        for widget in (screen.label_missing, screen.entry_keys):
            tips = lambda: [w for w in widget.winfo_children() if isinstance(w, tk.Toplevel)]
            fire(widget, '<Enter>')
            self.assertEqual(len(tips()), 1, widget)
            fire(widget, '<Enter>')
            self.assertEqual(len(tips()), 1, 'una sola copia')
            fire(widget, '<Leave>')
            self.assertEqual(tips(), [])

    def test_progress_label_has_a_tooltip(self):
        screen = self.step2()
        fire(screen.label_bar, '<Enter>')
        tips = [w for w in screen.label_bar.winfo_children() if isinstance(w, tk.Toplevel)]
        self.assertEqual(len(tips), 1)
        texts = ' '.join(all_texts(tips[0]))
        for text in ('Progress', 'Processed', 'Inserted / Updated', 'Errors', 'Skipped'):
            self.assertIn(text, texts)
        fire(screen.label_bar, '<Leave>')
        self.assertEqual([w for w in screen.label_bar.winfo_children() if isinstance(w, tk.Toplevel)], [])

    def test_enter_in_max_rows_and_keys_triggers_load(self):
        screen = self.step2()
        for entry in (screen.entry_max, screen.entry_keys):
            with patch.object(screen, 'load') as load:
                fire(entry, '<Return>')
            load.assert_called_once()


# ===================================================================== stale selection

class LevelFieldTests(UiCase):
    """Il campo Level del passo 2: scelte, valore predefinito, tabelle senza livelli, conteggi e chiavi di altri livelli."""

    def test_the_table_list_has_the_full_names_and_the_field_shows_only_the_part_after_the_colon(self):
        screen = self.step2()
        self.assertEqual(screen.cmb_table.get(), 'Strings')
        screen.cmb_table.set('JFX: Triplets')                       # come scegliere dal menu
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.var_table.get(), 'JFX: Triplets')   # la tabella resta quella intera
        self.assertEqual(screen.cmb_table.get(), 'Triplets')
        self.assertIn('JFX: Strings', list(screen.cmb_table.cget('values')))
        screen.cmb_table.set('JFX: Triplets')                       # la stessa voce di nuovo
        self.assertEqual(screen.cmb_table.get(), 'Triplets')

    def test_the_list_has_the_full_titles_and_the_field_shows_only_the_part_after_the_dash(self):
        screen = self.step2()
        self.assertEqual(screen.cmb_level.get(), 'Standard')
        screen.cmb_level.set(L_CW)                                  # come scegliere "CW - Integrations" dal menu
        screen.cmb_level.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.var_level.get(), L_CW)              # il livello resta quello intero
        self.assertEqual(screen.cmb_level.get(), 'Integrations')    # il campo mostra la parte corta
        self.assertEqual(screen._level().name, 'CW')
        self.assertEqual(list(screen.cmb_level.cget('values'))[2:], [L_CW, L_CT, L_CC])   # il menu resta intero
        screen.cmb_level.set(L_CW)                                  # la stessa voce scelta di nuovo
        self.assertEqual((screen.var_level.get(), screen.cmb_level.get()), (L_CW, 'Integrations'))
        screen.var_level.set(L_CC)                                  # cambiato dal programma (es. tabella senza livelli)
        self.assertEqual(screen.cmb_level.get(), 'Client Customization')
        screen.var_level.set(L_ALL)
        self.assertEqual(screen.cmb_level.get(), 'All levels')

    def test_default_is_standard_and_the_visible_levels_are_offered(self):
        screen = self.step2()
        self.assertEqual(screen.var_level.get(), L_STD)
        self.assertEqual(list(screen.cmb_level.cget('values')), ['All levels', 'Standard', 'CW - Integrations',
                                                                  'CT - Customizations', 'CC - Client Customization'])
        self.assertEqual(str(screen.cmb_level.cget('state')), 'readonly')

    def test_the_saved_level_is_restored_and_an_unknown_one_ignored(self):
        self.assertEqual(self.step2({'level': L_CT}).var_level.get(), L_CT)
        self.assertEqual(self.step2({'level': 'CK'}).var_level.get(), L_STD)      # nascosto: non e' una scelta
        self.assertEqual(self.step2({'level': 'CT'}).var_level.get(), L_STD)      # il vecchio nome breve non vale piu'

    def test_changing_the_level_recounts_and_invalidates_the_selection(self):
        screen = self.step2()
        self.fake_db.missing = {'FW_STRINGS': 3}
        screen.refresh_missing()
        screen.load()
        self.assertIsNotNone(screen.selection)
        self.fake_db.log.clear()
        screen.var_level.set(L_CW)
        screen.cmb_level.event_generate('<<ComboboxSelected>>')
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'disabled')
        counts = [b for s, b in self.fake_db.log if s.startswith('SELECT COUNT(*) FROM FW_STRINGS X')]
        self.assertEqual(counts[-1]['lvl_lo'], 4000000)
        self.assertIn('Missing in German (CW):', screen.label_missing.cget('text'))

    def test_all_levels_means_no_filter(self):
        screen = self.step2()
        screen.var_level.set(L_ALL)
        screen.cmb_level.event_generate('<<ComboboxSelected>>')
        counts = [b for s, b in self.fake_db.log if s.startswith('SELECT COUNT(*) FROM FW_STRINGS X')]
        self.assertNotIn('lvl_lo', counts[-1])
        self.assertIn('Missing in German:', screen.label_missing.cget('text'))

    def test_tables_without_levels_switch_the_field_off_and_restore_it_afterwards(self):
        screen = self.step2({'level': L_CT})
        screen.var_table.set('JFX: Docu nodes')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(str(screen.cmb_level.cget('state')), 'disabled')
        self.assertEqual(screen.var_level.get(), L_ALL)
        self.assertNotIn('(', screen.label_missing.cget('text'))                  # il livello non filtra nulla qui
        screen.var_table.set('JFX: Strings')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(str(screen.cmb_level.cget('state')), 'readonly')
        self.assertEqual(screen.var_level.get(), L_CT)                            # la scelta di prima e' tornata
        self.assertIn('(CT)', screen.label_missing.cget('text'))

    def test_a_switched_off_field_stays_off_after_a_translation_unlocks_the_fields(self):
        screen = self.step2()
        screen.var_table.set('JFX: Object descriptions')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        screen._lock(True)
        screen._lock(False)
        self.assertEqual(str(screen.cmb_level.cget('state')), 'disabled')

    def test_the_hint_does_not_stay_on_top_of_the_open_list(self):
        screen = self.step2()
        screen.level_tip.show()
        self.assertIsNotNone(screen.level_tip.tip)
        screen.cmb_level.event_generate('<<ComboboxSelected>>')
        self.assertIsNone(screen.level_tip.tip)

    def test_the_hint_names_every_level_in_full(self):
        from jt.ui.translation_screen import LEVEL_HINT
        self.assertEqual([name for name, _ in LEVEL_HINT['rows']], list(LEVEL_CHOICES))

    def test_load_says_the_level_when_it_is_not_standard(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, max_rows='5')
        for level, note in ((L_STD, ''), (L_CT, ' (CT)'), (L_CW, ' (CW)'), (L_ALL, ' (all levels)')):
            screen.var_level.set(level)
            screen.load()
            self.assertIn(f'to translate{note}: ', screen.status.message.cget('text'), level)
        screen.var_table.set('JFX: Docu nodes')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.fake_db.missing = {'FW_DOCU_NODES_T': 2}
        screen.load()
        self.assertNotIn('(', screen.status.message.cget('text'))

    def test_update_by_keys_says_the_level_too(self):
        self.fake_db.source['FW_STRINGS'] = [('it', 3000001, 'Testo CT', None, None, None)]
        screen = self.step2()
        screen.var_level.set(L_CT)
        screen.var_keys.set('3000001')
        screen.load()
        self.assertTrue(screen.status.message.cget('text').startswith('Update mode (CT): 1 row'),
                        screen.status.message.cget('text'))

    def test_the_logs_link_is_always_visible_and_the_times_open_on_request(self):
        screen = self.step2()
        self.assertIs(screen.link_logs.master, screen.details.extra)           # sulla riga di "Details", sempre visibile
        self.assertFalse(screen.details.expanded)
        self.assertFalse(screen.label_time.winfo_ismapped())
        screen.details.toggle()
        self.assertTrue(screen.details.expanded)
        self.assertEqual(screen.label_time.master, screen.details.body)

    def test_the_level_is_locked_while_translating(self):
        screen = self.step2()
        screen._lock(True)
        self.assertEqual(str(screen.cmb_level.cget('state')), 'disabled')
        screen._lock(False)
        self.assertEqual(str(screen.cmb_level.cget('state')), 'readonly')

    def test_update_by_keys_skips_keys_of_another_level_with_a_warning(self):
        self.fake_db.source['FW_STRINGS'] = [('it', 100000, 'Standard', None, None, None),
                                             ('it', 3000001, 'Testo CT', None, None, None)]
        screen = self.step2()
        screen.var_level.set(L_CT)
        screen.var_keys.set('100000, 3000001')
        screen.load()
        self.assertEqual(screen.status.state, 'warn')
        text = screen.status.message.cget('text')
        self.assertIn('Update mode (CT): 1 row', text)
        self.assertIn('Skipped, not CT: 100000 (Standard)', text)
        self.assertEqual(state(screen.translate_button), 'normal')

    def test_update_by_keys_with_only_other_level_keys_loads_nothing(self):
        self.fake_db.source['FW_STRINGS'] = [('it', 100000, 'Standard', None, None, None)]
        screen = self.step2()
        screen.var_level.set(L_CT)
        screen.var_keys.set('100000')
        screen.load()
        self.assertEqual(screen.status.state, 'warn')
        self.assertIn('Nothing to translate: Skipped, not CT: 100000 (Standard)', screen.status.message.cget('text'))
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'disabled')

    def test_update_by_keys_of_the_chosen_level_has_no_warning(self):
        self.fake_db.source['FW_STRINGS'] = [('it', 100000, 'Standard', None, None, None)]
        screen = self.step2()
        screen.var_keys.set('100000')
        screen.load()
        self.assertEqual(screen.status.state, 'ok')
        self.assertNotIn('Skipped', screen.status.message.cget('text'))


class SimulatedOracleWindowTests(UiCase):
    """La finestra vera di JT sul database Oracle simulato (tools/simulate.py): dal clic su Load al contenuto delle tabelle."""

    def setUp(self):
        super().setUp()
        self.oracle = simulate.Simulator()
        self.db._driver = self.oracle                       # al posto del finto database dei test normali
        patcher = patch.object(JTApp, 'make_translator', lambda _self: simulate.SimTranslator())
        patcher.start()
        self.addCleanup(patcher.stop)

    def rows(self, sql):
        return self.oracle.query(sql)

    def test_translating_the_ct_level_writes_only_ct_rows_with_their_user_and_category(self):
        screen = self.step2()
        self.choose(screen, lan_in='Italian', lan_out='French', table='JFX: Strings', max_rows='100')
        screen.var_level.set(L_CT)
        screen.load()
        self.assertEqual(screen.status.state, 'ok')
        screen.translate_button.invoke()
        self.assertEqual(self.rows("SELECT code, usr, info FROM FW_STRINGS WHERE language = 'fr' ORDER BY code"),
                         [(3000001, 'ZFXCUSTOM', 'MES'), (3000002, 'ZFXCUSTOM', None), (3000003, 'ZFXCUSTOM', ' ')])
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 3 inserted.'),
                        screen.status.message.cget('text'))

    def test_the_default_level_is_standard_and_leaves_ct_and_cw_alone(self):
        screen = self.step2()
        self.choose(screen, lan_in='Italian', lan_out='French', table='JFX: Strings', max_rows='100')
        self.assertEqual(screen.var_level.get(), 'Standard')
        screen.load()
        screen.translate_button.invoke()
        codes = [row[0] for row in self.rows("SELECT code FROM FW_STRINGS WHERE language = 'fr'")]
        self.assertTrue(codes and all(100000 <= code <= 2999999 for code in codes), codes)
        self.assertEqual(self.rows("SELECT DISTINCT usr FROM FW_STRINGS WHERE language = 'fr'"), [('JT',)])

    def test_the_missing_counter_follows_the_level(self):
        screen = self.step2()
        self.choose(screen, lan_in='Italian', lan_out='French', table='JFX: Strings')
        counts = {}
        for label, title in (('Standard', L_STD), ('CW', L_CW), ('CT', L_CT), ('CC', L_CC), ('All', L_ALL)):
            screen.var_level.set(title)
            screen.cmb_level.event_generate('<<ComboboxSelected>>')
            counts[label] = screen.counts['FW_STRINGS']
        self.assertEqual((counts['CW'], counts['CT'], counts['CC']), (2, 3, 2))
        self.assertEqual(counts['Standard'] + counts['CW'] + counts['CT'] + counts['CC'], counts['All'])

    def test_update_by_keys_skips_another_level_and_the_skipped_log_says_why(self):
        screen = self.step2()
        self.choose(screen, lan_in='Italian', lan_out='German', table='JFX: Strings', keys='100000, 3000001, 3000003')
        screen.var_level.set(L_CT)
        screen.load()
        self.assertEqual(screen.status.state, 'warn')
        self.assertIn('Skipped, not CT: 100000 (Standard)', screen.status.message.cget('text'))
        screen.translate_button.invoke()
        self.assertEqual(self.rows("SELECT value FROM FW_STRINGS WHERE language = 'de' AND code = 100000"),
                         [('Auftragsverwaltung',)])                                       # non toccata
        self.assertEqual(self.rows("SELECT value, usr FROM FW_STRINGS WHERE language = 'de' AND code = 3000003"),
                         [('[de] Campo extra del cliente', 'ZFXCUSTOM')])                 # UPDATE
        skipped = glob.glob(os.path.join(self.paths.logs, 'JT_skipped_log_*.csv'))
        self.assertEqual(len(skipped), 1)
        with open(skipped[0], encoding='utf-8-sig') as f:
            self.assertIn('key 100000 is level AP, selected level is CT', f.read())

    def test_a_too_long_description_shows_the_oracle_error_in_the_summary(self):
        screen = self.step2()
        self.choose(screen, lan_in='Italian', lan_out='French', table='JFX: Object descriptions', max_rows='100')
        screen.var_level.set(L_ALL)
        screen.load()
        screen.translate_button.invoke()
        text = screen.status.message.cget('text')
        self.assertIn('1 errors', text)
        self.assertIn('ORA-12899', text)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM FW_OBJ_DESCRS WHERE language = 'fr'"), [(3,)])


class ScrollAreaTests(UiCase):
    """Se la finestra e' piu' bassa del passo, compare la barra di scorrimento (prima il fondo veniva tagliato in silenzio)."""

    def fit_to(self, height):
        """Dice al passo che lo schermo e' alto `height` pixel e lascia lavorare l'interfaccia."""
        with patch.object(self.root, 'winfo_screenheight', return_value=height):
            self.app.fit_window()
            for _ in range(5):
                self.root.update()

    def test_no_scrollbar_when_the_step_fits(self):
        self.step2()
        self.root.deiconify()
        self.fit_to(2000)
        self.assertFalse(self.app.area.scrolling)

    def test_scrollbar_appears_when_the_window_is_lower_than_the_step(self):
        screen = self.step2()
        self.root.deiconify()
        self.fit_to(560)
        self.assertTrue(self.app.area.scrolling)
        self.assertGreater(screen.winfo_reqheight(), self.app.area.canvas.winfo_height())
        region = [int(v) for v in self.app.area.canvas.cget('scrollregion').split()]
        self.assertEqual(region[3], self.app.area.inner.winfo_reqheight())

    def test_scrollbar_goes_away_when_there_is_room_again(self):
        self.step2()
        self.root.deiconify()
        self.fit_to(560)
        self.assertTrue(self.app.area.scrolling)
        self.fit_to(2000)
        self.assertFalse(self.app.area.scrolling)

    def test_the_wheel_scrolls_only_when_there_is_a_bar(self):
        screen = self.step2()
        self.root.deiconify()
        self.fit_to(560)
        before = self.app.area.canvas.yview()[0]
        self.app.area._wheel(SimpleNamespace(widget=screen.entry_max, delta=-120))
        self.assertGreater(self.app.area.canvas.yview()[0], before)
        self.app.area._wheel(SimpleNamespace(widget=screen.cmb_table, delta=-120))          # sul menu a tendina: no
        position = self.app.area.canvas.yview()[0]
        self.app.area._wheel(SimpleNamespace(widget=screen.cmb_table, delta=-120))
        self.assertEqual(self.app.area.canvas.yview()[0], position)

    def test_a_new_step_starts_at_the_top(self):
        self.step2()
        self.root.deiconify()
        self.fit_to(560)
        self.app.area.canvas.yview_moveto(1.0)
        self.app.go_back()
        self.assertEqual(self.app.area.canvas.yview()[0], 0.0)


class CollapsibleTests(UiCase):
    """La sezione comprimibile (freccia, titolo, riassunto, corpo che si apre)."""

    def make(self, **kwargs):
        calls = []
        section = Collapsible(self.root, 'Advanced', summary='Max rows 1', on_toggle=lambda: calls.append(1), **kwargs)
        section.pack()
        ttk.Label(section.body, text='dentro').pack()
        return section, calls

    def test_it_starts_closed_and_shows_only_the_header(self):
        section, calls = self.make()
        self.assertFalse(section.expanded)
        self.assertEqual(section.body.winfo_manager(), '')
        self.assertEqual(section.arrow.cget('text'), Collapsible.CLOSED)
        self.assertEqual(section.summary.cget('text'), 'Max rows 1')
        self.assertEqual(calls, [])

    def test_a_click_opens_and_closes_it_and_tells_the_window(self):
        section, calls = self.make()
        fire(section.title, '<Button-1>')
        self.assertTrue(section.expanded)
        self.assertEqual((section.body.winfo_manager(), section.arrow.cget('text')), ('pack', Collapsible.OPEN))
        fire(section.arrow, '<Button-1>')
        self.assertFalse(section.expanded)
        self.assertEqual(calls, [1, 1])

    def test_the_header_answers_to_enter_and_space(self):
        section, _ = self.make()
        fire(section.header, '<Return>')
        self.assertTrue(section.expanded)
        fire(section.header, '<space>')
        self.assertFalse(section.expanded)

    def test_expanding_twice_or_closing_twice_does_not_notify_again(self):
        section, calls = self.make()
        section.expand()
        section.expand()
        section.collapse()
        section.collapse()
        self.assertEqual(calls, [1, 1])

    def test_it_can_start_open_without_notifying(self):
        section, calls = self.make(expanded=True)
        self.assertTrue(section.expanded)
        self.assertEqual(calls, [])

    def test_the_summary_changes_and_the_extra_slot_stays_on_the_header(self):
        section, _ = self.make()
        section.set_summary('Update by keys: 3')
        self.assertEqual(section.summary.cget('text'), 'Update by keys: 3')
        self.assertIs(section.extra.master, section.header)


class AdvancedAndDetailsTests(UiCase):
    """Max rows e Update by keys stanno in "Advanced"; i tempi in "Details". Chiusi, ma sempre al loro posto."""

    def test_advanced_starts_open_and_closed_it_keeps_a_summary_of_what_is_inside(self):
        screen = self.step2()
        self.assertTrue(screen.advanced.expanded)
        self.assertEqual(screen.advanced.summary.cget('text'), 'Max rows 1')
        screen.advanced.collapse()
        self.assertFalse(screen.entry_max.winfo_ismapped())
        self.assertEqual(screen.advanced.summary.cget('text'), 'Max rows 1')

    def test_max_rows_and_update_by_keys_share_one_line(self):
        screen = self.step2()
        self.assertEqual(screen.entry_max.grid_info()['row'], screen.entry_keys.grid_info()['row'])
        self.assertLess(int(screen.entry_max.grid_info()['column']), int(screen.entry_keys.grid_info()['column']))

    def test_the_fields_still_work_while_closed(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        screen = self.step2()
        screen.advanced.collapse()
        screen.var_max.set('25')
        self.assertEqual(screen.advanced.summary.cget('text'), 'Max rows 25')
        screen.load()
        selects = [b for s, b in self.fake_db.log if s.startswith('SELECT * FROM FW_STRINGS')]
        self.assertEqual(selects[-1]['n'], 25)

    def test_keys_open_a_closed_section_and_the_summary_counts_them(self):
        screen = self.step2()
        screen.advanced.collapse()
        screen.var_keys.set('100000, 100001; 100002')
        self.assertTrue(screen.advanced.expanded)
        self.assertEqual(screen.advanced.summary.cget('text'), 'Update by keys: 3')
        screen.var_keys.set('')
        self.assertEqual(screen.advanced.summary.cget('text'), 'Max rows 1')

    def test_a_wrong_max_rows_opens_a_closed_section_so_the_field_is_visible(self):
        screen = self.step2()
        screen.advanced.collapse()
        screen.var_max.set('')
        self.assertEqual(screen.advanced.summary.cget('text'), 'Max rows -')
        screen.load()
        self.assertTrue(screen.advanced.expanded)
        self.assertEqual(screen.status.state, 'error')

    def test_opening_a_section_refits_the_window(self):
        with patch.object(JTApp, 'fit_window') as fit:          # i pannelli la chiamano: va sostituita prima di costruirli
            screen = self.step2()
            fit.reset_mock()
            screen.advanced.toggle()
            screen.details.toggle()
            self.assertEqual(fit.call_count, 2)

    def test_the_fields_are_locked_during_a_translation_even_inside_the_closed_section(self):
        screen = self.step2()
        screen._lock(True)
        self.assertEqual(str(screen.entry_max.cget('state')), 'disabled')
        self.assertEqual(str(screen.entry_keys.cget('state')), 'disabled')
        screen._lock(False)
        self.assertEqual(str(screen.entry_max.cget('state')), 'normal')


class WindowEdgeTests(UiCase):
    def test_the_window_never_starts_beyond_the_right_edge(self):
        self.app._placed = True
        with patch.object(self.root, 'winfo_x', return_value=1200), \
                patch.object(self.root, 'winfo_width', return_value=460):
            w, h, x, y = self.geometry_for(self.app.show_translation)
        self.assertLessEqual(x + w, self.root.winfo_screenwidth())


class SectionsTests(UiCase):
    """LANGUAGES, WHAT TO TRANSLATE e PROGRESS si chiudono (aperte all'inizio) e chiuse dicono cosa contengono."""

    def sections(self, screen):
        return screen.languages_section, screen.selection_section, screen.progress_section

    def test_all_three_start_open(self):
        screen = self.step2()
        for section in self.sections(screen):
            self.assertTrue(section.expanded)
        self.assertEqual([s.title.cget('text') for s in self.sections(screen)],
                         ['LANGUAGES', 'WHAT TO TRANSLATE', 'PROGRESS'])

    def test_a_closed_section_hides_its_fields_and_the_window_refits(self):
        with patch.object(JTApp, 'fit_window') as fit:
            screen = self.step2()
            fit.reset_mock()
            screen.languages_section.collapse()
            self.assertFalse(screen.cmb_in.winfo_ismapped())
            self.assertEqual(fit.call_count, 1)
            screen.languages_section.expand()
        self.assertEqual(screen.var_in.get(), 'Italian')                           # i valori restano

    def test_languages_summary_follows_the_choice(self):
        screen = self.step2()
        self.assertEqual(screen.languages_section.summary.cget('text'), 'Italian \u2192 German')
        screen.var_out.set('French')
        self.assertEqual(screen.languages_section.summary.cget('text'), 'Italian \u2192 French')

    def test_selection_summary_has_table_level_and_missing_count(self):
        self.fake_db.missing = {'FW_STRINGS': 5}
        screen = self.step2()
        screen.refresh_missing()
        self.assertEqual(screen.selection_section.summary.cget('text'), 'JFX: Strings \u00b7 Standard \u00b7 5 missing')
        screen.var_level.set(L_CT)
        self.assertTrue(screen.selection_section.summary.cget('text').startswith('JFX: Strings \u00b7 CT'))
        screen.var_level.set(L_ALL)
        self.assertIn('all levels', screen.selection_section.summary.cget('text'))

    def test_the_summary_of_a_table_without_levels_does_not_mention_a_level(self):
        screen = self.step2()
        screen.var_table.set('JFX: Docu nodes')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.selection_section.summary.cget('text').split(' \u00b7 ')[0], 'JFX: Docu nodes')
        self.assertNotIn('all levels', screen.selection_section.summary.cget('text'))
        self.assertNotIn('Standard', screen.selection_section.summary.cget('text'))

    def test_progress_summary_follows_the_run(self):
        self.fake_db.missing = {'FW_STRINGS': 2}
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        self.use_azure()
        screen = self.step2()
        self.choose(screen, lan_out='English', max_rows='5')
        screen.load()
        self.assertEqual(screen.progress_section.summary.cget('text'), '')
        screen.translate_button.invoke()
        self.assertEqual(screen.progress_section.summary.cget('text'), '2/2')

    def test_the_progress_bar_is_thin(self):
        self.step2()
        thickness = int(float(str(ttk.Style(self.root).lookup('Horizontal.TProgressbar', 'thickness'))))
        self.assertEqual(thickness, scale.px(5))


class ConnectionBannerTests(UiCase):
    """Passo 1: il banner compare quando succede qualcosa e si chiude con la crocetta; il promemoria sta in basso."""

    def test_no_banner_at_the_start_and_the_reminder_is_in_the_bottom_line(self):
        screen = self.screen
        self.assertEqual(screen.status.winfo_manager(), '')
        self.assertEqual(self.app.infobar.label.cget('text'), NOT_CONNECTED)
        self.assertIn('try the connection to continue', NOT_CONNECTED)

    def test_a_connection_shows_the_banner_between_the_buttons_and_the_notice(self):
        screen = self.screen
        screen.connect()
        self.assertEqual(screen.status.winfo_manager(), 'pack')
        self.assertEqual((screen.status.state, screen.status.message.cget('text')), ('ok', 'Connection established.'))
        order = screen.pack_slaves()
        self.assertEqual(order.index(screen.status), order.index(screen.buttons) + 1)

    def test_an_error_shows_the_banner_too(self):
        self.fake_db.fail_connect = True
        screen = self.screen
        screen.connect()
        self.assertEqual(screen.status.winfo_manager(), 'pack')
        self.assertEqual(screen.status.state, 'error')

    def test_the_cross_closes_it_and_the_next_event_brings_it_back(self):
        screen = self.screen
        screen.connect()
        with patch.object(screen.status, 'on_change') as changed:
            fire(screen.status.close_button, '<Button-1>')
            self.root.update()                                         # la finestra si adatta quando l'interfaccia e' libera
            self.assertEqual(screen.status.winfo_manager(), '')
            self.assertEqual(changed.call_count, 1)
        screen.vars['host'].set('altro-host')                        # cambiare i dati chiude la connessione: di nuovo un avviso
        self.assertEqual(screen.status.winfo_manager(), 'pack')
        self.assertEqual(screen.status.state, 'info')

    def test_the_connect_and_next_buttons_are_unaffected(self):
        screen = self.screen
        self.assertEqual(state(screen.next_button), 'disabled')
        screen.connect()
        self.assertEqual(state(screen.next_button), 'normal')

    def test_only_a_closable_banner_has_a_cross(self):
        plain = StatusBar(self.root, 'x')
        closable = StatusBar(self.root, 'x', closable=True)
        self.assertIsNone(plain.close_button)
        self.assertIsNotNone(closable.close_button)
        self.assertEqual(str(closable.close_button.cget('bg')), str(closable.message.cget('bg')))
        closable.show('error', 'boom')
        self.assertEqual(str(closable.close_button.cget('bg')), str(closable.message.cget('bg')))


class StaleLoadMessageTests(UiCase):
    """Dopo un Load fallito il messaggio d'errore parla del valore di prima: se si cambia il campo, torna il messaggio normale."""

    NEUTRAL = 'Load the data for the translation.'

    def test_a_bad_key_error_goes_away_when_the_keys_change(self):
        screen = self.step2()
        screen.var_keys.set('ttt')
        screen.load()
        self.assertEqual((screen.status.state, screen.status.message.cget('text')), ('error', 'Not a valid key: ttt'))
        screen.var_keys.set('')
        self.assertEqual((screen.status.state, screen.status.message.cget('text')), ('info', self.NEUTRAL))

    def test_a_wrong_max_rows_error_goes_away_when_it_is_fixed(self):
        screen = self.step2()
        screen.var_max.set('')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        screen.var_max.set('5')
        self.assertEqual((screen.status.state, screen.status.message.cget('text')), ('info', self.NEUTRAL))

    def test_no_rows_found_is_stale_too(self):
        self.fake_db.source['FW_STRINGS'] = []
        screen = self.step2()
        screen.var_keys.set('999')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        screen.var_keys.set('998')
        self.assertEqual(screen.status.message.cget('text'), self.NEUTRAL)

    def test_a_database_error_while_loading_is_stale_too(self):
        screen = self.step2()
        self.fake_db.fail_sql = ['FROM FW_STRINGS X']
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        screen.var_level.set(L_CT)
        self.assertEqual(screen.status.message.cget('text'), self.NEUTRAL)

    def test_the_message_is_reset_only_once(self):
        screen = self.step2()
        screen.var_keys.set('ttt')
        screen.load()
        screen.var_keys.set('tt')
        screen.status.show('warn', 'qualcos\'altro')
        screen.var_keys.set('t')
        self.assertEqual(screen.status.message.cget('text'), 'qualcos\'altro')       # non si tocca un messaggio nuovo

    def test_a_loaded_selection_still_says_selection_changed(self):
        screen = self.loaded_strings(2)
        screen.var_keys.set('1')
        self.assertEqual(screen.status.message.cget('text'), 'Selection changed. Press Load to prepare it again.')

    def test_the_summary_of_a_run_is_not_wiped_by_a_change(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate_button.invoke()
        summary = screen.status.message.cget('text')
        self.assertTrue(summary.startswith('Done'), summary)
        screen.var_max.set('9')
        self.assertEqual(screen.status.message.cget('text'), summary)

    def test_a_successful_load_after_an_error_is_not_stale(self):
        self.fake_db.missing = {'FW_STRINGS': 2}
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        screen.var_keys.set('ttt')
        screen.load()
        screen.var_keys.set('')
        screen.var_max.set('3')
        screen.load()
        self.assertEqual(screen.status.state, 'ok')
        screen.var_max.set('4')
        self.assertEqual(screen.status.message.cget('text'), 'Selection changed. Press Load to prepare it again.')


class PreviewFlowTests(UiCase):
    """Load -> Preview (traduce senza scrivere) -> controllo della tabella -> Write (senza richiamare Azure) o Discard."""

    def previewed(self, rows=2, **choice):
        azure = self.use_azure(choice.pop('fail_on', None))
        screen = self.loaded_strings(rows, **choice)
        screen.preview_button.invoke()
        return screen, azure

    def test_the_preview_button_follows_the_loaded_selection(self):
        screen = self.step2()
        self.assertEqual(state(screen.preview_button), 'disabled')
        screen = self.loaded_strings(2)
        self.assertEqual(state(screen.preview_button), 'normal')
        screen.var_max.set('9')
        self.assertEqual(state(screen.preview_button), 'disabled')

    def test_the_preview_section_is_hidden_until_there_is_a_preview(self):
        screen = self.loaded_strings(2)
        self.assertEqual(screen.preview_section.winfo_manager(), '')
        self.assertEqual(state(screen.write_button), 'disabled')
        self.assertEqual(state(screen.discard_button), 'disabled')

    def test_preview_fills_the_table_and_writes_nothing(self):
        screen, azure = self.previewed(2)
        self.assertIsNotNone(screen.preview)
        self.assertEqual(len(screen.preview_tree.get_children()), 2)
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual(len(azure.calls), 2)
        self.assertEqual(screen.preview_section.winfo_manager(), 'pack')
        self.assertTrue(screen.status.message.cget('text').startswith('Preview ready: 2 insert, 0 update, 0 skipped.'),
                        screen.status.message.cget('text'))
        self.assertEqual(screen.status.state, 'ok')
        self.assertEqual(screen.label_bar.cget('text'), 'Previewed 2/2 · Insert 2 · Update 0')

    def test_after_a_preview_only_write_and_discard_are_possible(self):
        screen, azure = self.previewed(2)
        self.assertEqual([state(b) for b in (screen.preview_button, screen.translate_button, screen.write_button,
                                              screen.discard_button)], ['disabled', 'disabled', 'normal', 'normal'])
        screen.translate()                               # tradurre di nuovo costerebbe il doppio: non parte
        screen.run_preview()
        self.assertEqual(len(azure.calls), 2)
        self.assertEqual(self.fake_db.writes(), [])

    def test_write_writes_the_previewed_translations_without_calling_azure_again(self):
        screen, azure = self.previewed(2)
        screen.write_button.invoke()
        self.assertEqual(len(azure.calls), 2)
        inserts = self.fake_db.inserts()
        self.assertEqual([binds[2] for _sql, binds in inserts], ['T:Testo 0', 'T:Testo 1'])
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 2 inserted.'),
                        screen.status.message.cget('text'))
        self.assertIsNone(screen.preview)
        self.assertEqual(screen.preview_section.winfo_manager(), '')
        self.assertIsNone(screen.selection)
        self.assertEqual(len(self.logs('inserts')), 1)

    def test_write_gives_the_same_database_as_translating_directly(self):
        screen, _ = self.previewed(2)
        screen.write_button.invoke()
        via_preview = self.fake_db.inserts()
        self.fake_db.log.clear()
        self.use_azure()
        direct = self.loaded_strings(2)
        direct.translate_button.invoke()
        self.assertEqual(self.fake_db.inserts(), via_preview)

    def test_discard_throws_the_preview_away_and_asks_for_a_new_load(self):
        screen, _ = self.previewed(2)
        screen.discard_button.invoke()
        self.assertIsNone(screen.preview)
        self.assertIsNone(screen.selection)
        self.assertEqual(screen.preview_section.winfo_manager(), '')
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual([state(b) for b in (screen.preview_button, screen.translate_button)], ['disabled', 'disabled'])
        self.assertTrue(screen.status.message.cget('text').startswith('Preview discarded. Nothing was written.'))
        screen.load()
        self.assertEqual(state(screen.preview_button), 'normal')

    def test_changing_a_field_discards_the_preview(self):
        screen, _ = self.previewed(2)
        screen.var_max.set('9')
        self.assertIsNone(screen.preview)
        self.assertEqual(screen.preview_section.winfo_manager(), '')
        self.assertEqual(screen.status.message.cget('text'), 'Selection changed. Press Load to prepare it again.')

    def test_a_new_load_clears_the_preview(self):
        screen, _ = self.previewed(2)
        screen.load()
        self.assertIsNone(screen.preview)
        self.assertEqual(screen.preview_section.winfo_manager(), '')

    def test_update_rows_are_marked_and_the_detail_shows_the_old_text(self):
        key = ('FW_STRINGS', (('language', 'en'), ('code', 100000)))
        self.fake_db.existing = {key}
        self.fake_db.old_values = {key: {'value': 'Vecchio testo'}}
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        screen.preview_button.invoke()
        self.assertEqual(screen.preview_tree.set('0', 'action'), 'UPDATE')
        self.assertIn('update', screen.preview_tree.item('0', 'tags'))
        self.assertEqual(screen.preview_tree.set('1', 'action'), 'INSERT')
        screen.preview_tree.selection_set('0')
        screen._show_preview_detail()
        detail = screen.preview_detail.cget('text')
        self.assertIn('Was: Vecchio testo', detail)
        self.assertIn('To: T:Testo 0', detail)
        self.assertIn('user JT', detail)
        self.assertTrue(screen.status.message.cget('text').startswith('Preview ready: 1 insert, 1 update, 0 skipped.'))

    def test_skipped_rows_show_why_and_the_banner_warns(self):
        screen, _ = self.previewed(2, fail_on='Testo 1')
        self.assertEqual([screen.preview_tree.set(str(i), 'action') for i in (0, 1)], ['INSERT', 'SKIP'])
        self.assertIn('skip', screen.preview_tree.item('1', 'tags'))
        self.assertIn('skipped: Azure down', screen.preview_tree.set('1', 'translation'))
        self.assertEqual(screen.status.state, 'warn')
        screen.write_button.invoke()
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 1 inserted. 0 errors, 1 skipped.'))
        self.assertEqual(len(self.logs('skipped')), 1)

    def test_when_every_row_is_skipped_there_is_nothing_to_write(self):
        screen, _ = self.previewed(2, fail_on='Testo')
        self.assertEqual(state(screen.write_button), 'disabled')
        self.assertEqual(state(screen.discard_button), 'normal')
        self.assertTrue(screen.status.message.cget('text').startswith('Nothing to write: 0 insert, 0 update, 2 skipped.'))

    def test_the_table_shows_the_first_rows_but_write_writes_them_all(self):
        with patch('jt.ui.translation_screen.MAX_PREVIEW_ROWS', 3):
            screen, _ = self.previewed(5, max_rows='5')
            self.assertEqual(len(screen.preview_tree.get_children()), 3)
            self.assertIn('showing the first 3', screen.preview_summary.cget('text'))
        screen.write_button.invoke()
        self.assertEqual(len(self.fake_db.inserts()), 5)

    def test_without_an_azure_key_the_preview_says_so_and_the_selection_stays(self):
        screen = self.loaded_strings(2)
        with patch.object(JTApp, 'make_translator', side_effect=RuntimeError('no key')):
            screen.preview_button.invoke()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Azure settings not found or not valid', screen.status.message.cget('text'))
        self.assertIsNotNone(screen.selection)
        self.assertIsNone(screen.preview)

    def test_an_error_during_the_preview_writes_nothing_and_asks_for_a_new_load(self):
        key = ('FW_STRINGS', (('language', 'en'), ('code', 100000)))
        self.fake_db.existing = {key}
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        self.fake_db.fail_sql = ['SELECT value, USR, DT FROM']
        screen.preview_button.invoke()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('The preview stopped because of an error', screen.status.message.cget('text'))
        self.assertIn('Nothing was written', screen.status.message.cget('text'))
        self.assertIsNone(screen.preview)
        self.assertIsNone(screen.selection)
        self.assertEqual(self.fake_db.writes(), [])

    def test_the_input_sections_fold_while_the_preview_is_open_and_come_back_after(self):
        screen, _ = self.previewed(2)
        for section in (screen.languages_section, screen.selection_section, screen.progress_section):
            self.assertFalse(section.expanded)
        self.assertIn('Italian', screen.languages_section.summary.cget('text'))          # il riassunto resta in riga
        screen.discard_button.invoke()
        for section in (screen.languages_section, screen.selection_section, screen.progress_section):
            self.assertTrue(section.expanded)

    def test_a_section_the_user_had_closed_stays_closed(self):
        screen = self.loaded_strings(2)
        self.use_azure()
        screen.languages_section.collapse()
        screen.preview_button.invoke()
        screen.discard_button.invoke()
        self.assertFalse(screen.languages_section.expanded)
        self.assertTrue(screen.selection_section.expanded)

    def test_writing_keeps_the_progress_open_and_brings_the_fields_back(self):
        screen, _ = self.previewed(2)
        screen.write_button.invoke()
        self.assertTrue(screen.progress_section.expanded)
        self.assertTrue(screen.languages_section.expanded)
        self.assertTrue(screen.selection_section.expanded)

    def test_changing_a_field_brings_the_folded_sections_back(self):
        screen, _ = self.previewed(2)
        screen.var_max.set('9')
        self.assertTrue(screen.languages_section.expanded)
        self.assertTrue(screen.selection_section.expanded)
        self.assertEqual(screen._folded, [])

    def test_the_window_refits_when_the_preview_folds_and_unfolds_the_sections(self):
        with patch.object(JTApp, 'fit_window') as fit:
            screen, _ = self.previewed(2)
            self.assertGreaterEqual(fit.call_count, 1)
            fit.reset_mock()
            screen.discard_button.invoke()
            self.assertGreaterEqual(fit.call_count, 1)

    def test_the_fields_are_unlocked_after_the_preview(self):
        screen, _ = self.previewed(2)
        self.assertEqual(str(screen.entry_max.cget('state')), 'normal')
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertEqual(screen.translate_button.cget('text'), 'Translate')

    def test_the_preview_shows_the_level_and_the_user_of_every_row(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = [('it', 3000001, 'Testo CT', None, None, None)]
        screen = self.step2()
        self.choose(screen, keys='3000001')
        screen.var_level.set(L_CT)
        screen.load()
        screen.preview_button.invoke()
        self.assertEqual(screen.preview_tree.set('0', 'level'), 'CT')
        screen.preview_tree.selection_set('0')
        screen._show_preview_detail()
        self.assertIn('user ZFXCUSTOM', screen.preview_detail.cget('text'))


class EnvironmentFieldTests(UiCase):
    """Passo 1: l'etichetta dell'ambiente (dev/test/prod) di un database: si sceglie una volta e si ricorda."""

    def test_the_field_offers_not_set_dev_test_prod_and_starts_not_set(self):
        self.assertEqual(list(self.screen.cmb_env.cget('values')), ['Not set', 'dev', 'test', 'prod'])
        self.assertEqual(self.screen.env_var.get(), 'Not set')
        self.assertEqual(str(self.screen.cmb_env.cget('state')), 'readonly')

    def test_connect_remembers_the_label_for_that_database(self):
        self.screen.env_var.set('test')
        self.screen.connect()
        self.assertEqual(self.app.environment, 'test')
        self.assertEqual(self.db.info['environment'], 'test')
        self.assertEqual(self.app.settings.environment('fake-host', '1521', 'FAKESID'), 'test')

    def test_the_saved_label_is_there_when_the_program_starts_again(self):
        self.app.settings.save_environment('fake-host', '1521', 'FAKESID', 'prod')
        self.app.show_connection()
        self.assertEqual(self.app.screen.env_var.get(), 'prod')

    def test_typing_another_database_proposes_its_own_label_and_the_old_one_is_kept(self):
        screen = self.screen
        screen.env_var.set('prod')
        screen.connect()
        screen.vars['sid'].set('OTHER')
        self.assertEqual(screen.env_var.get(), 'Not set')
        self.assertEqual(self.app.settings.environment('fake-host', '1521', 'FAKESID'), 'prod')   # non si cancella
        screen.vars['sid'].set('fakesid')                                  # maiuscole e minuscole non contano
        self.assertEqual(screen.env_var.get(), 'prod')

    def test_changing_the_label_while_connected_applies_at_once_without_reconnecting(self):
        screen = self.screen
        screen.connect()
        self.assertEqual(self.app.environment, '')
        screen.env_var.set('prod')
        self.assertEqual(self.app.environment, 'prod')
        self.assertEqual(self.app.infobar.chip.cget('text'), 'PROD')
        self.assertEqual(self.app.settings.environment('fake-host', '1521', 'FAKESID'), 'prod')
        self.assertTrue(self.db.connected)
        self.assertEqual(state(screen.next_button), 'normal')

    def test_choosing_not_set_removes_the_saved_label(self):
        screen = self.screen
        screen.env_var.set('test')
        screen.connect()
        screen.env_var.set('Not set')
        self.assertEqual(self.app.environment, '')
        self.assertEqual(self.app.settings.environment('fake-host', '1521', 'FAKESID'), '')

    def test_without_a_connection_the_label_is_only_saved_when_connecting(self):
        self.screen.env_var.set('prod')
        self.assertEqual(self.app.settings.environment('fake-host', '1521', 'FAKESID'), '')

    def test_a_failed_connection_keeps_the_infobar_without_a_label(self):
        self.fake_db.fail_connect = True
        self.screen.env_var.set('prod')
        self.screen.connect()
        self.assertEqual(self.app.infobar.chip.winfo_manager(), '')

    def test_going_back_to_step_one_forgets_the_label_of_the_closed_connection(self):
        self.screen.env_var.set('prod')
        self.screen.connect()
        self.app.go_back()
        self.assertEqual(self.app.environment, '')

    def test_the_field_has_a_hint(self):
        from jt.ui.connection_screen import ENV_HINT
        self.assertEqual(ENV_HINT['title'], 'Environment')
        self.assertIn('prod', ' '.join(name for name, _ in ENV_HINT['rows']))


class InfoBarEnvironmentTests(UiCase):
    """Il segno colorato in basso: dev, test, prod o non impostata."""

    CASES = (('dev', 'DEV', 'accent'), ('test', 'TEST', 'ok'), ('prod', 'PROD', 'error'), ('', 'NOT SET', 'warn'))

    def test_no_chip_when_not_connected(self):
        self.assertEqual(self.app.infobar.chip.winfo_manager(), '')

    def test_each_label_has_its_own_text_and_colour(self):
        for env, text, color in self.CASES:
            with self.subTest(env=env):
                self.app.connect(dict(FAKE_CONNECTION, environment=env))
                chip = self.app.infobar.chip
                self.assertEqual((chip.cget('text'), str(chip.cget('bg'))), (text, PALETTE[color]))
                self.assertEqual(chip.winfo_manager(), 'pack')

    def test_the_chip_is_readable(self):
        for _env, text, color in self.CASES:
            self.assertGreaterEqual(contrast('white', PALETTE[color], self.root), 4.5, text)

    def test_disconnecting_hides_the_chip(self):
        self.app.connect(dict(FAKE_CONNECTION, environment='prod'))
        self.app.disconnect()
        self.assertEqual(self.app.infobar.chip.winfo_manager(), '')

    def test_the_tooltip_says_the_environment(self):
        self.app.connect(dict(FAKE_CONNECTION, environment='prod'))
        self.assertIn(('Environment', 'prod'), self.app.infobar._hint()['rows'])
        self.app.set_environment('')
        self.assertIn(('Environment', 'not set (treated as prod)'), self.app.infobar._hint()['rows'])

    def test_an_unknown_label_counts_as_not_set(self):
        self.app.connect(dict(FAKE_CONNECTION, environment='production'))
        self.assertEqual((self.app.environment, self.app.infobar.chip.cget('text')), ('', 'NOT SET'))


class TypedConfirmationDialogTests(UiCase):
    """ConfirmDialog con `type_to_confirm`: per andare avanti si scrive il nome del database."""

    def make(self, expected='ORA319'):
        dialog = ConfirmDialog(self.root, 'Write 2 rows?', 'detail', 'Write', 'Cancel', type_to_confirm=expected)
        self.addCleanup(lambda: dialog.top.winfo_exists() and dialog.top.destroy())
        return dialog

    def test_ok_stays_off_until_the_name_is_typed_ignoring_case_and_edge_spaces(self):
        dialog = self.make()
        self.assertEqual(state(dialog.ok_button), 'disabled')
        for typed, expected in (('ora', 'disabled'), ('ORA3190', 'disabled'), ('ora319', 'normal'), ('  ORA319 ', 'normal'),
                                ('', 'disabled'), ('ORA319', 'normal')):
            dialog.typed.set(typed)
            self.assertEqual(state(dialog.ok_button), expected, repr(typed))

    def test_enter_in_the_field_confirms_only_with_the_right_name(self):
        dialog = self.make()
        with patch.object(dialog.top, 'focus_get', return_value=dialog.entry):
            dialog.typed.set('nope')
            dialog._enter()
            self.assertTrue(dialog.top.winfo_exists())                     # non succede niente
            dialog.typed.set('ORA319')
            dialog._enter()
        self.assertTrue(dialog.result)

    def test_cancel_and_escape_never_need_the_name(self):
        dialog = self.make()
        dialog.cancel_button.invoke()
        self.assertFalse(dialog.result)

    def test_the_dialog_says_what_to_type(self):
        dialog = self.make()
        self.assertIn('To confirm, type the database name:  ORA319', ' '.join(all_texts(dialog.top)))

    def test_the_field_gets_the_focus_when_the_dialog_opens(self):
        dialog = self.make()
        calls, original = [], tk.Misc.focus_set

        def spy(widget):
            calls.append(widget)
            return original(widget)

        with patch.object(tk.Misc, 'focus_set', spy):
            self.drive_dialog_for(dialog, lambda: None)
        self.assertIs(calls[-1], dialog.entry)

    def drive_dialog_for(self, dialog, action):
        """Mostra il dialogo `dialog` e, a finestra aperta, esegue action; poi lo chiude."""
        self.root.after(10, lambda: (action(), dialog.cancel_button.invoke()))
        dialog.show()

    def test_a_plain_dialog_has_no_field(self):
        dialog = ConfirmDialog(self.root, 'Quit?', '', 'Quit', 'Stay')
        self.addCleanup(dialog.top.destroy)
        self.assertIsNone(dialog.entry)
        self.assertEqual(state(dialog.ok_button), 'normal')
        self.assertFalse(dialog.matches())


class WriteConfirmationTests(UiCase):
    """Prima di scrivere (Translate diretto o Write dopo l'anteprima) si chiede conferma con un riepilogo."""

    def loaded(self, rows=2, **choice):
        self.azure = self.use_azure()
        return self.loaded_strings(rows, **choice)

    def test_translate_asks_first_with_a_summary(self):
        screen = self.loaded(2)
        screen.translate_button.invoke()
        self.assertEqual(len(self.confirmations), 1)
        asked = self.confirmations[0]
        self.assertEqual((asked['question'], asked['ok_text']), ('Translate and write 2 rows to FW_STRINGS?', 'Translate'))
        lines = asked['detail'].split('\n')
        self.assertEqual(lines[0], 'Database: FAKEDB  ·  fake-host  ·  user fake_user')
        self.assertEqual(lines[1], 'Environment: Not set (treated as prod)')
        self.assertEqual(lines[2], 'Languages: Italian → English')
        self.assertEqual(lines[3], 'Level: Standard  ·  written as user JT')
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 2 inserted.'))

    def test_prod_and_not_set_ask_for_the_database_name(self):
        screen = self.loaded(2)
        for env in ('', 'prod'):
            with self.subTest(env=env):
                self.confirmations.clear()
                self.app.set_environment(env)
                screen.load()
                screen.translate_button.invoke()
                self.assertEqual(len(self.confirmations), 1)
                self.assertEqual(self.confirmations[0]['type_to_confirm'], 'FAKEDB')

    def test_dev_and_test_never_ask_neither_for_translate_nor_after_a_preview(self):
        screen = self.loaded(2)
        for env in ('dev', 'test'):
            with self.subTest(env=env):
                self.confirmations.clear()
                self.fake_db.log.clear()
                self.app.set_environment(env)
                screen.load()
                screen.translate_button.invoke()                              # traduzione diretta
                self.assertEqual(len(self.fake_db.inserts()), 2)
                self.fake_db.log.clear()
                screen.load()
                screen.preview_button.invoke()
                screen.write_button.invoke()                                  # dopo l'anteprima
                self.assertEqual(len(self.fake_db.inserts()), 2)
                self.assertEqual(self.confirmations, [])

    def test_the_summary_of_the_dialog_is_still_there_for_prod_after_a_preview(self):
        screen = self.loaded(2)
        self.app.set_environment('prod')
        screen.preview_button.invoke()
        screen.write_button.invoke()
        self.assertEqual(len(self.confirmations), 1)
        self.assertEqual(self.confirmations[0]['type_to_confirm'], 'FAKEDB')

    def test_without_a_database_name_the_sid_is_asked_and_failing_that_the_host(self):
        self.fake_db.db_name = None
        screen = self.loaded(2)
        screen.translate_button.invoke()
        self.assertEqual(self.confirmations[0]['type_to_confirm'], 'FAKESID')

    def test_the_environment_is_in_the_summary(self):
        screen = self.loaded(2)
        self.app.set_environment('prod')
        screen.translate_button.invoke()
        self.assertIn('Environment: prod', self.confirmations[0]['detail'].split('\n'))

    def test_cancelling_translate_translates_and_writes_nothing_and_keeps_the_selection(self):
        screen = self.loaded(2)
        self.confirm_answer = False
        screen.translate_button.invoke()
        self.assertEqual(len(self.azure.calls), 0)                           # niente costo
        self.assertEqual(self.fake_db.writes(), [])
        self.assertIsNotNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'normal')
        self.assertEqual(screen.status.message.cget('text'), 'Cancelled. Nothing was translated or written.')
        self.confirm_answer = True
        screen.translate_button.invoke()                                     # si puo' riprovare
        self.assertEqual(len(self.fake_db.inserts()), 2)

    def test_the_preview_never_asks_only_the_write_does(self):
        screen = self.loaded(2)
        screen.preview_button.invoke()
        self.assertEqual(self.confirmations, [])
        screen.write_button.invoke()
        self.assertEqual(len(self.confirmations), 1)
        asked = self.confirmations[0]
        self.assertEqual((asked['question'], asked['ok_text']), ('Write 2 rows to FW_STRINGS?', 'Write'))
        self.assertIn('2 insert, 0 update', asked['detail'].split('\n'))

    def test_cancelling_the_write_keeps_the_preview_and_writes_nothing(self):
        screen = self.loaded(2)
        screen.preview_button.invoke()
        self.confirm_answer = False
        screen.write_button.invoke()
        self.assertIsNotNone(screen.preview)
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual(state(screen.write_button), 'normal')
        self.assertEqual(screen.status.message.cget('text'), 'Cancelled. Nothing was written: the preview is still here.')
        self.confirm_answer = True
        screen.write_button.invoke()
        self.assertEqual(len(self.fake_db.inserts()), 2)
        self.assertEqual(len(self.azure.calls), 2)

    def test_the_summary_says_level_and_user_of_the_rows(self):
        screen = self.loaded(2)
        for level, expected in ((L_CT, 'Level: CT  ·  written as user ZFXCUSTOM'),
                                (L_CW, 'Level: CW  ·  written as user ZFXINTEGR'),
                                (L_CC, 'Level: CC  ·  written as user ZFXCCSYS'),
                                (L_ALL, 'Level: all levels  ·  written as user JT, ZFXCUSTOM, ZFXINTEGR, ZFXCCSYS')):
            with self.subTest(level=level):
                self.confirmations.clear()
                screen.var_level.set(level)
                screen.load()
                if screen.selection is None:
                    continue                                                 # niente righe di quel livello nel finto database
                screen.translate_button.invoke()
                self.assertIn(expected, self.confirmations[0]['detail'].split('\n'))

    def test_the_summary_of_a_preview_lists_the_users_actually_written(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = [('it', 100000, 'Standard', None, None, None),
                                             ('it', 3000001, 'Testo CT', None, None, None)]
        screen = self.step2()
        self.choose(screen, keys='100000, 3000001')
        screen.var_level.set(L_ALL)
        screen.load()
        screen.preview_button.invoke()
        screen.write_button.invoke()
        self.assertIn('written as user JT, ZFXCUSTOM', self.confirmations[0]['detail'].split('\n')[3])

    def test_update_by_keys_says_that_existing_translations_are_replaced(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        screen.translate_button.invoke()
        self.assertIn('Rows that already have a translation are replaced.', self.confirmations[0]['detail'].split('\n'))

    def test_a_table_without_levels_says_so(self):
        self.use_azure()
        self.fake_db.missing['FW_OBJ_DESCRS'] = 2
        screen = self.step2()
        self.choose(screen, table='JFX: Object descriptions')
        screen.load()
        screen.translate_button.invoke()
        self.assertIn('Level: no levels (every row)  ·  written as user JT', self.confirmations[0]['detail'].split('\n'))

    def test_a_missing_azure_key_is_reported_before_asking_anything(self):
        screen = self.loaded_strings(2)
        with patch.object(JTApp, 'make_translator', side_effect=RuntimeError('no key')):
            screen.translate_button.invoke()
        self.assertEqual(self.confirmations, [])
        self.assertIn('Azure settings not found or not valid', screen.status.message.cget('text'))

    # --- con la finestra vera (non la risposta automatica)

    def test_a_test_database_writes_without_opening_any_dialog(self):
        self.use_real_confirmation()
        screen = self.loaded(2)
        self.app.set_environment('test')
        with patch.object(JTApp, 'confirm', side_effect=AssertionError('nessuna finestra su un database di test')):
            screen.translate_button.invoke()
        self.assertEqual(len(self.fake_db.inserts()), 2)

    def test_the_real_dialog_for_prod_needs_the_name_before_it_writes(self):
        self.use_real_confirmation()
        screen = self.loaded(2)
        self.app.set_environment('prod')

        def act(dialog, seen):
            seen['before'] = state(dialog.ok_button)
            seen['text'] = ' '.join(all_texts(dialog.top))
            dialog.typed.set('FAKEDB')
            seen['after'] = state(dialog.ok_button)
            dialog.ok_button.invoke()

        _value, seen = self.drive_dialog(lambda: screen.translate_button.invoke(), act)
        self.assertEqual((seen['before'], seen['after']), ('disabled', 'normal'))
        self.assertIn('Environment: prod', seen['text'])
        self.assertIn('To confirm, type the database name:  FAKEDB', seen['text'])
        self.assertEqual(len(self.fake_db.inserts()), 2)

    def test_the_real_dialog_cancelled_writes_nothing(self):
        self.use_real_confirmation()
        screen = self.loaded(2)
        _value, _seen = self.drive_dialog(lambda: screen.translate_button.invoke(),
                                          lambda dialog, seen: dialog.cancel_button.invoke())
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual(len(self.azure.calls), 0)
        self.assertEqual(screen.status.message.cget('text'), 'Cancelled. Nothing was translated or written.')


class UndoLinkTests(UiCase):
    """Dopo una corsa che ha scritto, lo script che la annulla e' pronto e c'e' il collegamento per aprirlo."""

    def ran(self, rows=2, **choice):
        self.azure = self.use_azure(choice.pop('fail_on', None))
        screen = self.loaded_strings(rows, **choice)
        screen.translate_button.invoke()
        return screen

    def script(self, screen):
        with open(screen._undo_path, encoding='utf-8') as f:
            return f.read()

    def test_no_link_before_anything_was_written(self):
        screen = self.step2()
        self.assertEqual(screen.link_undo.winfo_manager(), '')
        self.assertIsNone(screen._undo_path)

    def test_a_run_that_wrote_leaves_a_script_and_a_link(self):
        screen = self.ran(2)
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        self.assertTrue(os.path.exists(screen._undo_path))
        self.assertEqual(os.path.dirname(screen._undo_path), self.paths.logs)
        text = self.script(screen)
        self.assertIn("DELETE FROM FW_STRINGS WHERE language = 'en' AND code = 100001;", text)
        self.assertIn("DELETE FROM FW_STRINGS WHERE language = 'en' AND code = 100000;", text)
        self.assertIn('for the database FAKEDB (fake-host)', text)

    def test_the_summary_names_the_script(self):
        screen = self.ran(2)
        text = screen.status.message.cget('text')
        self.assertRegex(text, r'Log: Logs\\JT_inserts_log_\d+\.csv Undo script: Logs\\JT_undo_\d+\.sql')

    def test_write_after_a_preview_leaves_the_script_too(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.preview_button.invoke()
        self.assertEqual(screen.link_undo.winfo_manager(), '')                    # l'anteprima non scrive: niente da annullare
        screen.write_button.invoke()
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        self.assertIn('DELETE FROM FW_STRINGS', self.script(screen))

    def test_a_run_that_wrote_nothing_leaves_no_script(self):
        screen = self.ran(2, fail_on='Testo')
        self.assertEqual(screen.link_undo.winfo_manager(), '')
        self.assertIsNone(screen._undo_path)
        self.assertEqual(glob.glob(os.path.join(self.paths.logs, 'JT_undo_*.sql')), [])
        self.assertNotIn('Undo script', screen.status.message.cget('text'))

    def test_an_update_script_puts_the_previous_text_back(self):
        key = ('FW_STRINGS', (('language', 'en'), ('code', 100000)))
        self.fake_db.existing = {key}
        self.fake_db.old_values = {key: {'value': "L'ordine & il vecchio", 'usr': 'ZFXCUSTOM'}}
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        screen.translate_button.invoke()
        text = self.script(screen)
        self.assertIn("UPDATE FW_STRINGS SET value = 'L''ordine & il vecchio', USR = 'ZFXCUSTOM', DT = 'old dt' "
                      "WHERE language = 'en' AND code = 100000;", text)
        self.assertIn("DELETE FROM FW_STRINGS WHERE language = 'en' AND code = 100001;", text)
        self.assertIn('SET DEFINE OFF;', text)

    def test_the_link_goes_away_when_a_new_run_starts_and_comes_back_with_the_new_script(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate_button.invoke()
        first = screen._undo_path
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        seen = {}
        self.hook_progress(screen_for_hook := self.reload(screen), lambda p: seen.setdefault(
            'during', (screen_for_hook.link_undo.winfo_manager(), screen_for_hook._undo_path)))
        screen_for_hook.translate_button.invoke()
        self.assertEqual(seen['during'], ('', None))                              # durante la corsa non c'e' lo script vecchio
        self.assertEqual(screen_for_hook.link_undo.winfo_manager(), 'pack')

    def test_a_preview_does_not_take_the_link_of_the_last_write_away(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate_button.invoke()
        script = screen._undo_path
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        self.reload(screen)
        screen.preview_button.invoke()                                            # l'anteprima non scrive niente
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        self.assertEqual(screen._undo_path, script)

    def test_any_error_building_the_script_unlocks_the_screen_and_says_so(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        with patch('jt.ui.translation_screen.write_undo_script', side_effect=ValueError('bad column name')):
            screen.translate_button.invoke()
        self.assertFalse(screen.running)
        self.assertEqual(state(screen.load_button), 'normal')                     # i campi non restano bloccati
        text = screen.status.message.cget('text')
        self.assertIn('The undo script could not be created: bad column name', text)
        self.assertIn('Log: Logs', text)                                          # il resto del riepilogo c'e' lo stesso
        self.assertEqual(screen.link_undo.winfo_manager(), '')

    def reload(self, screen):
        """Un nuovo Load (le righe si leggono una volta sola): ritorna la stessa schermata pronta a tradurre."""
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.load()
        return screen

    def test_the_script_is_written_even_when_the_csv_logs_cannot_be_written(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        with patch('jt.ui.translation_screen.write_run_logs', side_effect=PermissionError('locked')):
            screen.translate_button.invoke()
        self.assertEqual(screen.link_undo.winfo_manager(), 'pack')
        self.assertTrue(os.path.exists(screen._undo_path))

    def test_the_link_opens_the_script_and_falls_back_to_the_folder(self):
        screen = self.ran(2)
        with patch('os.startfile', create=True) as start:
            screen.open_undo()
        start.assert_called_once_with(screen._undo_path)
        with patch('os.startfile', create=True, side_effect=[OSError('no application'), None]) as start:
            screen.open_undo()
        self.assertEqual([c.args[0] for c in start.call_args_list], [screen._undo_path, self.paths.logs])

    def test_a_script_that_cannot_be_opened_is_reported(self):
        screen = self.ran(2)
        with patch('os.startfile', create=True, side_effect=OSError('nope')):
            screen.open_undo()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Could not open', screen.status.message.cget('text'))

    def test_the_tooltip_has_the_path_and_the_instructions(self):
        screen = self.ran(2)
        hint = screen._undo_hint()
        self.assertEqual(hint['title'], 'Undo script')
        self.assertIn('SQL Developer', hint['intro'])
        self.assertEqual(hint['rows'], [('File', screen._undo_path)])

    def test_opening_without_a_script_does_nothing(self):
        screen = self.step2()
        with patch('os.startfile', create=True) as start:
            screen.open_undo()
        start.assert_not_called()


class OneRowSelectionTests(UiCase):
    """Se i due menu ci stanno, Table e Level stanno su una riga sola; se no, su due."""

    def setUp(self):
        super().setUp()
        # senza adattare la finestra non arrivano i veri <Configure> della scheda a rimettere la disposizione com'era:
        # l'ampiezza si dice a mano. Il test della finestra vera riattiva l'adattamento.
        self.fit_patch = patch.object(JTApp, 'fit_window')
        self.fit = self.fit_patch.start()
        self.addCleanup(self.stop_fit_patch)

    def stop_fit_patch(self):
        with contextlib.suppress(RuntimeError):
            self.fit_patch.stop()

    def manual_screen(self):
        """Il passo 2 senza i veri <Configure> della scheda (arriverebbero a rimettere la disposizione secondo la finestra
        nascosta): l'ampiezza della scheda la dice il test con resize()."""
        screen = self.step2()
        screen._selection_card.unbind('<Configure>')
        return screen

    def grid(self, widget):
        info = widget.grid_info()
        return int(info['row']), int(info['column'])

    def resize(self, screen, width):
        screen._on_card_resize(SimpleNamespace(width=width))

    def test_a_narrow_card_keeps_table_and_level_on_two_rows(self):
        screen = self.manual_screen()
        self.assertFalse(screen._one_row)
        self.assertEqual((self.grid(screen.cmb_table), self.grid(screen.cmb_level)), ((0, 1), (1, 1)))
        self.assertEqual(self.grid(screen.label_missing)[0], 2)
        self.assertEqual(self.grid(screen.advanced)[0], 3)

    def test_a_wide_card_puts_them_on_one_row_and_the_rest_moves_up(self):
        screen = self.manual_screen()
        self.resize(screen, screen._one_row_threshold + 20)
        self.assertTrue(screen._one_row)
        self.assertEqual([self.grid(w) for w in (screen.label_table, screen.cmb_table, screen.label_level, screen.cmb_level)],
                         [(0, 0), (0, 1), (0, 2), (0, 3)])
        self.assertEqual(self.grid(screen.label_missing)[0], 1)
        self.assertEqual(self.grid(screen.advanced)[0], 2)
        self.assertEqual(int(screen.advanced.grid_info()['columnspan']), 4)

    def test_it_goes_back_to_two_rows_when_the_card_shrinks_with_a_little_hysteresis(self):
        screen = self.manual_screen()
        threshold = screen._one_row_threshold
        self.resize(screen, threshold)
        self.assertTrue(screen._one_row)
        self.resize(screen, threshold - 10)                  # appena sotto: resta com'e' (niente sfarfallio)
        self.assertTrue(screen._one_row)
        self.resize(screen, threshold - 21)
        self.assertFalse(screen._one_row)
        self.assertEqual((self.grid(screen.cmb_table), self.grid(screen.cmb_level)), ((0, 1), (1, 1)))
        self.resize(screen, threshold - 1)                   # sotto la soglia di salita: non risale
        self.assertFalse(screen._one_row)

    def test_the_window_refits_only_when_the_layout_really_changes(self):
        screen = self.manual_screen()
        threshold = screen._one_row_threshold
        self.fit.reset_mock()
        self.resize(screen, threshold - 100)
        self.resize(screen, threshold - 60)
        self.assertEqual(self.fit.call_count, 0)
        self.resize(screen, threshold + 80)
        self.resize(screen, threshold + 180)
        self.assertEqual(self.fit.call_count, 1)
        self.resize(screen, threshold - 60)
        self.assertEqual(self.fit.call_count, 2)

    def test_a_click_closes_the_tooltip_and_keeps_it_closed_until_the_mouse_leaves(self):
        screen = self.step2()
        tip = ToolTip(screen.label_missing, {'title': 'Hint'})
        tip.show()
        self.assertIsNotNone(tip.tip)
        screen.label_missing.event_generate('<ButtonPress-1>')          # per esempio aprire il menu a tendina
        self.assertIsNone(tip.tip)
        tip.show()                                                       # <Enter> dopo lo scatto del mouse: resta chiuso
        self.assertIsNone(tip.tip)
        with patch.object(screen.label_missing, 'winfo_containing', return_value=None):
            tip._leave()                                                 # il mouse esce davvero
        tip.show()
        self.assertIsNotNone(tip.tip)
        tip.hide()

    def test_a_tooltip_with_a_plain_text_shows_it(self):
        screen = self.step2()
        tip = ToolTip(screen.label_missing, 'C:\some\folder')
        tip.show()
        try:
            self.assertIn('C:\some\folder', all_texts(tip.tip))
        finally:
            tip.hide()

    def test_the_threshold_comes_from_the_short_names_the_fields_show(self):
        screen = self.manual_screen()
        font = screen._font
        extra = scale.px(28)
        longest_table = max(font.measure(e['description'].split(': ', 1)[-1]) for e in screen.entries) + extra
        longest_level = max(font.measure(t.split(' - ', 1)[-1]) for t in LEVEL_CHOICES) + extra
        labels = font.measure('Table') + font.measure('Level  (?)')
        self.assertEqual((screen._table_need, screen._level_need), (longest_table, longest_level))
        menu = max(longest_table, longest_level)                          # i due menu sono larghi uguale
        self.assertEqual(screen._menu_need, menu)
        self.assertGreater(screen._one_row_threshold, 2 * menu + labels)
        self.assertLess(screen._one_row_threshold, 2 * menu + labels + sum(screen._gaps) + scale.px(40))

    def test_the_columns_have_a_fixed_width_whatever_table_is_chosen(self):
        screen = self.manual_screen()
        self.resize(screen, screen._one_row_threshold + 20)
        card = screen._selection_card
        for table in ('JFX: Strings', 'JFX: Object descriptions', 'JFX: Options three'):
            screen.var_table.set(table)
            screen.cmb_table.event_generate('<<ComboboxSelected>>')            # Object descriptions: Level dice 'All levels'
            self.assertEqual(card.grid_columnconfigure(1)['minsize'], screen._menu_need, table)
            self.assertEqual(card.grid_columnconfigure(3)['minsize'], screen._menu_need, table)

    def test_on_two_rows_the_columns_have_no_minimum(self):
        screen = self.manual_screen()
        self.resize(screen, screen._one_row_threshold + 20)
        self.resize(screen, screen._one_row_threshold - 30)
        card = screen._selection_card
        self.assertEqual((card.grid_columnconfigure(1)['minsize'], card.grid_columnconfigure(3)['minsize']), (0, 0))

    def test_everything_keeps_working_on_one_row(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        screen = self.manual_screen()
        self.resize(screen, screen._one_row_threshold + 80)
        screen.var_level.set(L_CT)
        screen.cmb_level.event_generate('<<ComboboxSelected>>')
        self.assertIn('Missing in German (CT):', screen.label_missing.cget('text'))
        screen.var_table.set('JFX: Docu nodes')
        screen.cmb_table.event_generate('<<ComboboxSelected>>')
        self.assertEqual(str(screen.cmb_level.cget('state')), 'disabled')
        self.assertEqual(screen.var_level.get(), L_ALL)

    def test_the_level_hint_is_still_attached_to_its_label_and_field(self):
        screen = self.manual_screen()
        self.resize(screen, screen._one_row_threshold + 80)
        screen.level_tip.show()
        self.assertIsNotNone(screen.level_tip.tip)
        screen.level_tip.hide()

    def test_in_a_real_window_nothing_is_cut_at_the_usual_width_and_when_it_grows(self):
        self.stop_fit_patch()                                  # qui l'adattamento della finestra e' quello vero
        screen = self.step2()
        self.root.deiconify()
        extra = scale.px(28)

        def settle():
            for _ in range(15):
                self.root.update()

        for width in (WINDOW_MIN_WIDTH, 700, 900):                           # WINDOW_MIN_WIDTH: la larghezza della finestra al primo avvio
            self.root.geometry(f'{width}x720')
            settle()
            self.assertTrue(screen._one_row, width)
            widths = set()
            for table in ('JFX: Object descriptions', 'JFX: Options three', 'JFX: Strings'):
                screen.var_table.set(table)
                screen.cmb_table.event_generate('<<ComboboxSelected>>')
                settle()
                short = table.split(': ', 1)[-1]
                self.assertGreaterEqual(screen.cmb_table.winfo_width(), screen._font.measure(short) + extra, (width, table))
                self.assertGreaterEqual(screen.cmb_level.winfo_width(), screen._level_need, (width, table))
                widths.add((screen.cmb_table.winfo_width(), screen.cmb_level.winfo_width()))
                self.assertAlmostEqual(screen.cmb_table.winfo_width(), screen.cmb_level.winfo_width(), delta=1,
                                       msg=(width, table))                # sempre pari (1 pixel di arrotondamento)
            self.assertEqual(len(widths), 1, (width, widths))                  # scegliendo un'altra tabella nulla si muove

    def test_the_open_list_is_wide_enough_for_the_full_names(self):
        self.stop_fit_patch()
        screen = self.step2()
        self.root.deiconify()
        for _ in range(15):
            self.root.update()
        extra = scale.px(28)
        for combo, longest in ((screen.cmb_table, 'JFX: Object descriptions'), (screen.cmb_level, L_CC)):
            popdown = f'{combo}.popdown'
            self.root.tk.call('ttk::combobox::Post', combo)
            for _ in range(15):
                self.root.update()
                time.sleep(0.005)
            try:
                width = int(self.root.tk.call('winfo', 'width', popdown))
            finally:
                self.root.tk.call('ttk::combobox::Unpost', combo)
            self.assertGreaterEqual(width, screen._font.measure(longest) + extra, longest)

    def test_a_card_narrower_than_the_names_falls_back_to_two_rows_in_a_real_window(self):
        self.stop_fit_patch()
        screen = self.step2()
        self.root.deiconify()
        self.root.minsize(200, 200)                            # per provare una finestra piu' stretta del minimo di JT
        self.root.geometry('380x720')
        for _ in range(15):
            self.root.update()
        self.assertFalse(screen._one_row)
        self.assertEqual(self.grid(screen.cmb_level), (1, 1))


class StaleSelectionTests(UiCase):
    CHANGES = (('var_in', 'French'), ('var_out', 'Spanish'), ('var_table', 'JFX: Options'),
               ('var_max', '7'), ('var_keys', '100000'))

    def test_changing_any_field_after_load_invalidates_the_selection(self):
        for name, value in self.CHANGES:
            with self.subTest(field=name):
                screen = self.loaded_strings(2)
                self.assertEqual(state(screen.translate_button), 'normal')
                getattr(screen, name).set(value)
                self.assertIsNone(screen.selection)
                self.assertEqual(state(screen.translate_button), 'disabled')
                self.assertEqual(screen.status.state, 'info')
                self.assertIn('Selection changed', screen.status.message.cget('text'))

    def test_invalidation_message_only_when_there_was_a_selection(self):
        screen = self.step2()
        screen.status.show('info', 'custom text')
        screen.var_max.set('9')
        self.assertEqual(screen.status.message.cget('text'), 'custom text')

    def test_translate_without_selection_writes_nothing(self):
        make = MagicMock()
        with patch.object(JTApp, 'make_translator', make):
            screen = self.loaded_strings(2)
            screen.var_max.set('9')                   # invalida
            screen.translate()
            screen.translate_button.invoke()          # disabilitato: non fa niente
        self.assertEqual(self.fake_db.writes(), [])
        make.assert_not_called()
        self.assertFalse(self.app.translating)

    def test_translate_never_starts_without_a_load(self):
        screen = self.step2()
        with patch.object(JTApp, 'make_translator', MagicMock()) as make:
            screen.translate()
        make.assert_not_called()
        self.assertEqual(self.fake_db.writes(), [])

    def test_changing_the_table_without_reloading_cannot_write_into_the_other_table(self):
        self.use_azure()
        screen = self.loaded_strings(2, lan_in='Italian', lan_out='English', table='JFX: Strings')
        screen.var_table.set('JFX: Options')                       # senza ricaricare
        self.assertEqual(state(screen.translate_button), 'disabled')
        screen.translate_button.invoke()
        screen.translate()                                         # anche chiamato a forza
        self.assertEqual(self.fake_db.writes(), [])

    def test_a_run_uses_the_table_and_languages_captured_at_load_time(self):
        self.use_azure()
        screen = self.loaded_strings(3, lan_in='Italian', lan_out='English', table='JFX: Strings')

        def change_everything(progress):
            # durante il lavoro i campi non invalidano piu' nulla, ma il motore non li deve leggere
            screen.var_table.set('JFX: Options')
            screen.var_in.set('French')
            screen.var_out.set('Spanish')

        self.hook_progress(screen, change_everything)
        screen.translate()
        inserts = self.fake_db.inserts()
        self.assertEqual(len(inserts), 3)
        for sql, binds in inserts:
            self.assertTrue(sql.startswith('INSERT INTO FW_STRINGS '), sql)
            self.assertEqual(binds[0], 'en')
        self.assertFalse([s for s, _ in self.fake_db.writes() if 'FW_OPZIONI' in s])

    def test_reload_after_a_change_works_again(self):
        screen = self.loaded_strings(2)
        screen.var_max.set('1')
        self.assertIsNone(screen.selection)
        screen.load()
        self.assertIsNotNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'normal')


# ===================================================================== Load

class LoadTests(UiCase):
    def setUp(self):
        super().setUp()
        self.screen2 = None

    def open(self, **choice):
        screen = self.step2()
        self.choose(screen, **choice)
        return screen

        self.fake_db.missing = {'FW_STRINGS': 1}
        self.fake_db.source['FW_STRINGS'] = plain_rows(1)
        screen = self.open(lan_in='Italian', lan_out='English', table='JFX: Strings', max_rows='1')
        screen.load()
        text = screen.status.message.cget('text')
        self.assertEqual(text, '1 row to translate: less than a minute, 100 characters.')
        self.assertNotIn('0.0', text)

    def test_missing_mode_reports_rows_and_estimate_and_saves_the_choice(self):
        self.fake_db.missing = {'FW_STRINGS': 1600}
        self.fake_db.source['FW_STRINGS'] = plain_rows(3)
        screen = self.open(lan_in='Italian', lan_out='English', table='JFX: Strings', max_rows='2000')
        screen.load()
        self.assertEqual(screen.status.state, 'ok')
        self.assertEqual(screen.status.message.cget('text'),
                         '1.600 rows to translate: about 17 minutes, 100 characters.')
        self.assertEqual(state(screen.translate_button), 'normal')
        selection = screen.selection
        self.assertEqual((selection.spec.name, selection.lan_in, selection.lan_out, selection.mode),
                         ('FW_STRINGS', 'it', 'en', 'missing'))
        saved = read_json(self.paths.query)
        self.assertEqual((saved['linput'], saved['loutput'], saved['table']), ('Italian', 'English', 'JFX: Strings'))

    def test_max_rows_goes_to_the_query(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        screen = self.open(max_rows='25')
        screen.load()
        selects = [b for s, b in self.fake_db.log if s.startswith('SELECT * FROM FW_STRINGS')]
        self.assertEqual(selects[-1], {'li': 'it', 'lo': 'en', 'lvl_lo': 100000, 'lvl_hi': 2999999, 'n': 25})

    def test_level_goes_to_the_query_and_is_saved(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        screen = self.open(max_rows='25')
        screen.var_level.set(L_CT)
        screen.load()
        selects = [b for s, b in self.fake_db.log if s.startswith('SELECT * FROM FW_STRINGS')]
        self.assertEqual((selects[-1]['lvl_lo'], selects[-1]['lvl_hi']), (3000000, 3999999))
        self.assertEqual(screen.selection.level.name, 'CT')
        self.assertEqual(read_json(self.paths.query)['level'], L_CT)

    def test_max_rows_must_be_a_whole_number_of_at_least_one(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        for text in ('abc', '', '   ', '0', '00', '-3', '1.5', '1e3', '٣'):
            with self.subTest(max_rows=text):
                screen = self.open(max_rows=text)
                screen.load()
                self.assertEqual(screen.status.state, 'error')
                self.assertEqual(screen.status.message.cget('text'), 'Max rows must be a whole number of at least 1.')
                self.assertIsNone(screen.selection)
                self.assertEqual(state(screen.translate_button), 'disabled')
                self.assertEqual(self.fake_db.count('SELECT * FROM FW_STRINGS'), 0)
                self.assertEqual(self.fake_db.count('SELECT COUNT(*) FROM FW_STRINGS X'), 0)
        self.assertEqual(str(self.root.cget('cursor')), '')

    def test_valid_max_rows_values_are_accepted(self):
        self.fake_db.missing = {'FW_STRINGS': 4}
        for text, expected in (('1', 1), ('007', 7), (' 12 ', 12), ('100000', 100000)):
            with self.subTest(max_rows=text):
                screen = self.open(max_rows=text)
                screen.load()
                self.assertEqual(screen.status.state, 'ok')
                selects = [b for s, b in self.fake_db.log if s.startswith('SELECT * FROM FW_STRINGS')]
                self.assertEqual(selects[-1]['n'], expected)

    def test_a_wrong_max_rows_clears_a_previous_selection_and_progress(self):
        screen = self.loaded_strings(2)
        screen.label_bar.config(text='Processed 1/2')
        screen.entry_max.delete(0, 'end')               # (la selezione e' gia' stata invalidata dalla modifica)
        screen.load()
        self.assertIsNone(screen.selection)
        self.assertEqual(screen.label_bar.cget('text'), 'Waiting to start')

    def test_max_rows_entry_accepts_only_digits_typed_or_pasted(self):
        screen = self.step2()
        entry = screen.entry_max
        entry.delete(0, 'end')
        self.assertEqual(screen.var_max.get(), '')                  # cancellare e' sempre permesso
        for text in ('a', '-', '.', ' ', '1.5', '12a', '٣', 'x1'):
            entry.insert('end', text)                                # incollare = inserire il testo intero
            self.assertEqual(screen.var_max.get(), '', text)
        entry.insert('end', '12')
        entry.insert('end', 'z')
        entry.insert(0, '-')
        self.assertEqual(screen.var_max.get(), '12')
        entry.insert('end', '345')
        self.assertEqual(screen.var_max.get(), '12345')
        entry.delete(0, 1)
        self.assertEqual(screen.var_max.get(), '2345')
        self.assertEqual(str(entry.cget('validate')), 'key')

    def test_keys_field_accepts_any_text(self):
        screen = self.step2()
        screen.entry_keys.insert('end', 'abc, 12; X_1')
        self.assertEqual(screen.var_keys.get(), 'abc, 12; X_1')

    def test_loading_banner_is_shown_while_working_and_the_cursor_is_busy(self):
        self.fake_db.missing = {'FW_STRINGS': 2}
        screen = self.open()
        seen = []
        original = self.app.service.load_missing

        def spy(*args):
            seen.append((screen.status.state, screen.status.message.cget('text'), str(self.root.cget('cursor'))))
            return original(*args)

        with patch.object(self.app.service, 'load_missing', spy):
            screen.load()
        self.assertEqual(seen, [('info', 'Loading...', 'watch')])
        self.assertEqual(screen.status.state, 'ok')

    def test_keys_mode_also_shows_loading_first(self):
        screen = self.open(keys='100000')
        seen = []
        original = self.app.service.load_keys
        with patch.object(self.app.service, 'load_keys',
                          lambda *a: (seen.append(screen.status.message.cget('text')), original(*a))[1]):
            screen.load()
        self.assertEqual(seen, ['Loading...'])

    def test_more_than_1000_keys_is_an_error_and_exactly_1000_is_fine(self):
        screen = self.open(keys=', '.join(str(n) for n in range(100000, 101001)))
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'), 'Too many keys: the limit is 1000.')
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(self.fake_db.count('SELECT * FROM FW_STRINGS'), 0)
        self.assertEqual(str(self.root.cget('cursor')), '')
        screen = self.open(keys=', '.join(str(n) for n in range(100000, 101000)))
        screen.load()
        self.assertIn(screen.status.state, ('ok', 'warn'))
        self.assertIsNotNone(screen.selection)

    def test_unexpected_load_error_shows_only_the_first_line_shortened(self):
        screen = self.open()
        error = RuntimeError('ORA-00942: ' + 'long ' * 60 + '\nsecond line of the trace')
        with patch.object(self.app.service, 'load_missing', side_effect=error):
            screen.load()
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'error')
        self.assertTrue(text.startswith('Could not load the rows: ORA-00942: long'), text)
        self.assertTrue(text.endswith('long...'), text)
        self.assertNotIn('second line', text)
        self.assertLess(len(text), len('Could not load the rows: ') + 120)
        self.assertIsNone(screen.selection)

    def test_nothing_to_translate_keeps_translate_disabled_and_saves_nothing(self):
        before = read_json(self.paths.query)
        screen = self.open(lan_in='Italian', lan_out='English')         # missing = 0
        screen.load()
        self.assertEqual(screen.status.state, 'info')
        self.assertIn('Nothing to translate', screen.status.message.cget('text'))
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertIsNone(screen.selection)
        self.assertEqual(read_json(self.paths.query), before)

    def test_same_language_is_an_error(self):
        screen = self.open(lan_in='Italian', lan_out='Italian')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('two different languages', screen.status.message.cget('text'))
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(self.fake_db.count('SELECT * FROM FW_STRINGS'), 0)

    def test_empty_table_or_language_choice_is_an_error(self):
        screen = self.open()
        screen.var_table.set('')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Choose a table', screen.status.message.cget('text'))
        self.assertEqual(state(screen.translate_button), 'disabled')

    def test_load_after_a_previous_load_replaces_the_selection(self):
        self.fake_db.missing = {'FW_STRINGS': 2, 'FW_OPZIONI': 1}
        screen = self.open()
        screen.load()
        first = screen.selection
        screen.var_table.set('JFX: Options')
        screen.load()
        self.assertIsNot(screen.selection, first)
        self.assertEqual(screen.selection.spec.name, 'FW_OPZIONI')

    def test_keys_mode_loads_the_listed_entries(self):
        screen = self.open(keys='100000, 100001')
        screen.load()
        self.assertEqual(screen.status.state, 'ok')
        self.assertTrue(screen.status.message.cget('text').startswith('Update mode: 2 rows'))
        self.assertEqual(screen.selection.mode, 'keys')
        self.assertEqual(state(screen.translate_button), 'normal')

    def test_keys_mode_ignores_max_rows(self):
        screen = self.open(keys='100000', max_rows='abc')
        screen.load()
        self.assertEqual(screen.selection.total, 1)

    def test_invalid_key_is_an_error(self):
        screen = self.open(keys='100000; drop table x')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'), 'Not a valid key: drop')
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertIsNone(screen.selection)

    def test_keys_not_found_are_listed_in_a_warning(self):
        screen = self.open(keys='100000, 999, 998')
        screen.load()
        self.assertEqual(screen.status.state, 'warn')
        text = screen.status.message.cget('text')
        self.assertIn('Update mode: 1 row,', text)
        self.assertIn('Not found: 999, 998', text)
        self.assertEqual(state(screen.translate_button), 'normal')
        self.assertEqual(screen.selection.missing_keys, ['999', '998'])

    def test_more_than_five_keys_not_found_are_abbreviated(self):
        screen = self.open(keys='100000, ' + ', '.join(str(n) for n in range(900, 907)))
        screen.load()
        text = screen.status.message.cget('text')
        self.assertIn('Not found: 900, 901, 902, 903, 904...', text)
        self.assertNotIn('905', text)

    def test_keys_with_no_row_is_an_error(self):
        screen = self.open(keys='999')
        screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('No Italian rows found', screen.status.message.cget('text'))
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertIsNone(screen.selection)

    def test_database_error_shows_query_error_and_resets_the_busy_cursor(self):
        screen = self.open()
        self.fake_db.fail_sql = ['FROM FW_STRINGS X']
        busy = []
        original = self.app.set_busy
        with patch.object(self.app, 'set_busy', side_effect=lambda b: (busy.append(b), original(b))):
            screen.load()
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'), 'Could not load the rows: simulated DB error')
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(busy, [True, False])
        self.assertEqual(str(self.root.cget('cursor')), '')

    def test_load_does_nothing_while_running(self):
        screen = self.open()
        screen.running = True
        screen.load()
        self.assertEqual(self.fake_db.count('SELECT * FROM FW_STRINGS'), 0)
        screen.running = False

    def test_busy_cursor_is_reset_after_a_successful_load(self):
        self.fake_db.missing = {'FW_STRINGS': 2}
        screen = self.open()
        screen.load()
        self.assertEqual(str(self.root.cget('cursor')), '')


# ===================================================================== Translate end-to-end

class TranslateTests(UiCase):
    """Traduzione con InlineRunner: il lavoro finisce prima che translate() ritorni (poi l'interfaccia legge i risultati)."""

    def test_inserts_reach_the_db_with_bind_variables_and_the_summary_is_ok(self):
        azure = self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate_button.invoke()
        inserts = self.fake_db.inserts()
        self.assertEqual(len(inserts), 2)
        for (sql, binds), code in zip(inserts, (100000, 100001)):
            self.assertEqual(sql, "INSERT INTO FW_STRINGS VALUES (:1, :2, :3, :4, 'JT', sysdate)")
            self.assertEqual(binds[:2], ['en', code])
            self.assertNotIn('Testo', sql)
        self.assertEqual(inserts[0][1][2], 'T:Testo 0')
        self.assertEqual([c['text'] for c in azure.calls], ['Testo 0', 'Testo 1'])
        self.assertEqual(self.fake_db.conns[0].commits, 2)
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'ok')
        self.assertTrue(text.startswith('Done: 2 inserted. Log: Logs\\JT_inserts_log_'), text)
        self.assertEqual(self.log_name(text), os.path.basename(self.logs('inserts')[0]))

    def test_the_summary_has_no_error_part_when_all_went_well(self):
        self.use_azure()
        screen = self.loaded_strings(1)
        screen.translate()
        self.assertNotIn('errors', screen.status.message.cget('text'))
        self.assertNotIn('skipped', screen.status.message.cget('text'))

    def test_the_run_uses_the_translator_built_from_the_saved_credentials(self):
        screen = self.loaded_strings(1)
        with patch('jt.ui.app.AzureTranslator') as translator_class:
            translator_class.return_value.translate.side_effect = lambda text, a, b: 'T:' + text
            screen.translate()
        self.assertEqual(translator_class.call_args.args[0], FAKE_AZURE)
        self.assertEqual(len(self.fake_db.inserts()), 1)

    def test_progress_bar_label_and_times_after_the_run(self):
        self.use_azure()
        screen = self.loaded_strings(3)
        screen.translate()
        self.assertEqual(float(str(screen.progress.cget('maximum'))), 3.0)
        self.assertEqual(float(str(screen.progress.cget('value'))), 3.0)
        self.assertEqual(screen.label_bar.cget('text'), f'Processed 3/3 {SEP} Inserted 3 {SEP} Errors 0')
        self.assertRegex(screen.label_time.cget('text'),
                         rf'^Elapsed \(min\): [\d.]+ {SEP} Expected \(min\): [\d.]+$')

    def test_progress_text_in_missing_mode(self):
        screen = self.step2()
        screen._update_run = False
        screen._show_progress(Progress(done=4, total=10, inserts=3, updates=0, errors=1, skipped=0,
                                       elapsed_min=0.5, expected_min=0.75))
        self.assertEqual(screen.label_bar.cget('text'), f'Processed 4/10 {SEP} Inserted 3 {SEP} Errors 1')
        self.assertEqual(screen.label_time.cget('text'), f'Elapsed (min): 0.5 {SEP} Expected (min): 0.75')
        self.assertEqual(float(str(screen.progress.cget('value'))), 4.0)

    def test_progress_text_appends_skipped_only_when_there_are_some(self):
        screen = self.step2()
        screen._update_run = False
        screen._show_progress(Progress(5, 10, 3, 0, 1, 1, 1.0, 1.0))
        self.assertEqual(screen.label_bar.cget('text'),
                         f'Processed 5/10 {SEP} Inserted 3 {SEP} Errors 1 {SEP} Skipped 1')
        screen._show_progress(Progress(6, 10, 4, 0, 1, 0, 1.0, 1.0))
        self.assertNotIn('Skipped', screen.label_bar.cget('text'))

    def test_progress_text_in_keys_mode_has_updated(self):
        screen = self.step2()
        screen._update_run = True
        screen._show_progress(Progress(2, 3, 1, 1, 0, 2, 0.1, 0.2))
        self.assertEqual(screen.label_bar.cget('text'),
                         f'Processed 2/3 {SEP} Inserted 1 {SEP} Updated 1 {SEP} Errors 0 {SEP} Skipped 2')

    def test_the_separator_is_the_middle_dot(self):
        self.assertEqual(SEP, '·')
        screen = self.step2()
        screen._update_run = False
        screen._show_progress(Progress(1, 2, 1, 0, 0, 0, 0.0, 0.0))
        self.assertIn('·', screen.label_bar.cget('text'))
        self.assertNotIn(' - ', screen.label_bar.cget('text'))

    def test_the_ui_shows_only_the_latest_of_many_progress_events(self):
        screen = self.step2()
        screen.running = self.app.translating = True
        screen._update_run = False
        for done in (1, 2, 3):
            self.runner._events.put(('progress', Progress(done, 3, done, 0, 0, 0, 0.0, 0.0)))
        with patch.object(screen, '_show_progress', wraps=screen._show_progress) as show:
            screen._poll()
        self.assertEqual([c.args[0].done for c in show.call_args_list], [3])
        screen.after_cancel(screen._poll_job)           # il lavoro non e' finito: la lettura si ripete
        screen.running = self.app.translating = False

    def test_csv_logs_are_written_in_the_logs_folder(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        self.assertFalse(os.path.exists(self.paths.logs))                 # la cartella nasce quando serve
        screen.translate()
        self.assertEqual(self.paths.logs, os.path.join(self.tmp, 'Logs'))
        self.assertEqual(len(self.logs('inserts')), 1)
        self.assertEqual(self.logs('errors'), [])
        self.assertEqual(os.path.dirname(self.logs('inserts')[0]), self.paths.logs)
        with open(self.logs('inserts')[0], encoding='utf-8-sig') as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 3)           # intestazione + 2 righe
        self.assertIn('insert', lines[1])

    def test_when_nothing_was_written_only_the_skipped_rows_are_logged(self):
        self.use_azure(fail_on='Testo')
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertEqual((self.logs('inserts'), self.logs('errors')), ([], []))
        skipped = glob.glob(os.path.join(self.paths.logs, 'JT_skipped_log_*.csv'))
        self.assertEqual(len(skipped), 1)
        with open(skipped[0], encoding='utf-8-sig') as f:
            self.assertEqual(len(f.read().splitlines()), 3)      # intestazione + 2 righe, con il motivo
        text = screen.status.message.cget('text')
        self.assertTrue(text.startswith('Done: 0 inserted. 0 errors, 2 skipped. Log: Logs\JT_skipped_log_'), text)
        self.assertEqual(screen.status.state, 'warn')

    def test_failed_inserts_give_a_warning_and_an_error_log(self):
        self.use_azure()
        self.fake_db.fail_write = lambda sql, binds: binds[1] == 100001
        screen = self.loaded_strings(2)
        screen.translate()
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'warn')
        self.assertTrue(text.startswith('Done: 1 inserted. 1 errors, 0 skipped. Log: Logs\\JT_errors_log_'), text)
        self.assertEqual(self.log_name(text), os.path.basename(self.logs('errors')[0]))
        self.assertIn('First error (code 100001): simulated write error', text)     # il motivo si vede subito, senza aprire il log
        with open(self.logs('errors')[0], encoding='utf-8-sig') as f:
            self.assertIn('simulated write error', f.read())
        self.assertEqual(len(self.logs('errors')), 1)
        self.assertEqual(len(self.logs('inserts')), 1)
        self.assertIn('Errors 1', screen.label_bar.cget('text'))

    def test_azure_failures_are_counted_as_skipped(self):
        self.use_azure(fail_on='Testo 1')
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertEqual(screen.status.state, 'warn')
        self.assertIn('0 errors, 1 skipped', screen.status.message.cget('text'))
        self.assertIn(f'{SEP} Skipped 1', screen.label_bar.cget('text'))
        self.assertEqual(len(self.fake_db.inserts()), 1)

    def test_controls_are_locked_during_the_run_and_unlocked_after(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        during = []

        def snapshot(progress):
            during.append({
                'entries': [state(w) for w in (screen.entry_max, screen.entry_keys)],
                'load': state(screen.load_button), 'hidden': state(screen.hidden_button),
                'combos': [state(c) for c in (screen.cmb_in, screen.cmb_out, screen.cmb_table)],
                'link': self.app.stepper.link_enabled, 'translating': self.app.translating,
                'running': screen.running})

        self.hook_progress(screen, snapshot)
        screen.translate()
        self.assertEqual(len(during), 2)
        for shot in during:
            self.assertEqual(shot['entries'], ['disabled', 'disabled'])
            self.assertEqual((shot['load'], shot['hidden']), ('disabled', 'disabled'))
            self.assertEqual(shot['combos'], ['disabled'] * 3)
            self.assertFalse(shot['link'])
            self.assertTrue(shot['translating'] and shot['running'])
        self.assertEqual([state(w) for w in (screen.entry_max, screen.entry_keys, screen.load_button)], ['normal'] * 3)
        self.assertEqual(state(screen.hidden_button), 'normal')
        self.assertEqual([state(c) for c in (screen.cmb_in, screen.cmb_out, screen.cmb_table)], ['readonly'] * 3)
        self.assertTrue(self.app.stepper.link_enabled)
        self.assertFalse(self.app.translating or screen.running)

    def test_the_translate_button_becomes_a_red_stop_button_during_the_run(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        seen = []
        self.hook_progress(screen, lambda p: seen.append((
            str(screen.translate_button.cget('text')), str(screen.translate_button.cget('style')),
            state(screen.translate_button), screen.status.state, screen.status.message.cget('text'),
            float(str(screen.progress.cget('maximum'))))))
        self.assertEqual(str(screen.translate_button.cget('text')), 'Translate')
        screen.translate()
        self.assertEqual(len(seen), 2)
        for shot in seen:
            self.assertEqual(shot, ('Stop', DANGER, 'normal', 'info', 'Translating... you can press Stop at any time.',
                                    2.0))

    def test_the_stop_button_is_wired_to_stop(self):
        self.use_azure()
        screen = self.loaded_strings(3)
        calls = []

        def press(progress):
            calls.append(progress.done)
            if len(calls) == 1:
                screen.translate_button.invoke()

        self.hook_progress(screen, press)
        screen.translate()
        self.assertEqual(calls, [1])                     # invoke() ha chiamato stop(): il lavoro si e' fermato
        self.assertTrue(screen.status.message.cget('text').startswith('Stopped: 1 inserted.'))

    def test_stop_ends_the_run_after_the_current_row(self):
        self.use_azure()
        screen = self.loaded_strings(5)
        seen = []

        def press_stop(progress):
            if progress.done == 2:
                screen.stop()
                seen.append((state(screen.translate_button), str(screen.translate_button.cget('text')),
                             screen.status.state, screen.status.message.cget('text')))
                screen.stop()                            # un secondo clic non cambia niente

        self.hook_progress(screen, press_stop)
        screen.translate()
        self.assertEqual(seen, [('disabled', 'Stop', 'warn', 'Stopping after the current row...')])
        self.assertEqual(len(self.fake_db.inserts()), 2)
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'warn')
        self.assertTrue(text.startswith('Stopped: 2 inserted. Log: Logs\\JT_inserts_log_'), text)
        self.assertEqual(len(self.logs('inserts')), 1)
        self.assertEqual(screen.label_bar.cget('text'), f'Processed 2/5 {SEP} Inserted 2 {SEP} Errors 0')
        self.assertFalse(self.app.translating or screen.running)

    def test_after_a_stop_the_button_is_translate_again_and_disabled(self):
        self.use_azure()
        screen = self.loaded_strings(3)
        self.hook_progress(screen, lambda p: screen.stop())
        screen.translate()
        self.assertEqual(str(screen.translate_button.cget('text')), 'Translate')
        self.assertEqual(str(screen.translate_button.cget('style')), PRIMARY)
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertTrue(self.app.stepper.link_enabled)

    def test_stop_outside_a_run_does_nothing(self):
        screen = self.loaded_strings(2)
        screen.stop()
        self.assertEqual(screen.status.state, 'ok')
        self.assertEqual(state(screen.translate_button), 'normal')
        self.assertFalse(self.runner._stop.is_set())

    def test_stopped_keys_run_mentions_updated_too(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(3)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001, 100002')
        screen.load()
        self.hook_progress(screen, lambda p: screen.stop())
        screen.translate()
        self.assertTrue(screen.status.message.cget('text').startswith('Stopped: 1 inserted, 0 updated.'))

    def test_the_button_works_again_after_a_run_and_a_new_load(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate()
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.load()
        self.assertEqual(state(screen.translate_button), 'normal')
        screen.translate_button.invoke()
        self.assertEqual(len(self.fake_db.inserts()), 4)

    def test_load_resets_the_progress_after_a_run(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertEqual(float(str(screen.progress.cget('value'))), 2.0)
        self.assertTrue(screen.label_bar.cget('text').startswith('Processed'))
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.load()
        self.assertEqual(float(str(screen.progress.cget('value'))), 0.0)
        self.assertEqual(float(str(screen.progress.cget('maximum'))), 1.0)
        self.assertEqual(screen.label_bar.cget('text'), 'Waiting to start')
        self.assertEqual(screen.label_time.cget('text'), 'Elapsed time: --')

    def test_translate_is_disabled_after_the_run_because_the_selection_is_consumed(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.translate_button), 'disabled')
        writes = len(self.fake_db.writes())
        screen.translate()                       # un secondo clic non riscrive niente
        self.assertEqual(len(self.fake_db.writes()), writes)

    def test_missing_counts_are_refreshed_after_the_run(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        self.assertEqual(screen.label_missing.cget('text'), 'Counting missing translations...')
        self.hook_progress(screen, lambda p: self.fake_db.missing.update(FW_STRINGS=0) if p.done == 2 else None)
        screen.translate()
        self.assertEqual(screen.label_missing.cget('text'),
                         'Missing in English (Standard): 0 in this table, 0 in all tables')

    def test_keys_mode_updates_existing_rows_and_inserts_the_missing_ones(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        self.fake_db.existing = {('FW_STRINGS', (('language', 'en'), ('code', 100000)))}
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        screen.translate()
        self.assertEqual(len(self.fake_db.updates()), 1)
        self.assertEqual(len(self.fake_db.inserts()), 1)
        sql, binds = self.fake_db.updates()[0]
        self.assertTrue(sql.startswith('UPDATE FW_STRINGS SET value = :s0'), sql)
        self.assertNotIn('Testo', sql)
        self.assertIn('T:Testo 0', binds.values())
        self.assertEqual(self.fake_db.inserts()[0][1][:2], ['en', 100001])
        self.assertEqual(screen.label_bar.cget('text'),
                         f'Processed 2/2 {SEP} Inserted 1 {SEP} Updated 1 {SEP} Errors 0')
        self.assertEqual(screen.status.state, 'ok')
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 1 inserted, 1 updated. Log: Logs\\'))

    def test_keys_mode_with_not_found_keys_still_runs(self):
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(1)
        screen = self.step2()
        self.choose(screen, keys='100000, 4242')
        screen.load()
        self.assertEqual(screen.status.state, 'warn')
        screen.translate()
        self.assertEqual(len(self.fake_db.inserts()), 1)
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 1 inserted, 0 updated.'))

    def test_missing_azure_settings_give_an_error_and_write_nothing(self):
        screen = self.loaded_strings(2)
        os.remove(self.paths.azure)               # niente patch: make_translator reale
        screen.translate()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Azure settings', screen.status.message.cget('text'))
        self.assertEqual(self.fake_db.writes(), [])
        self.assertFalse(self.app.translating or screen.running)
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertEqual(str(screen.translate_button.cget('text')), 'Translate')

    def test_unexpected_error_during_the_run_unlocks_everything_and_reports_it(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        with patch.object(self.app.service, 'run', side_effect=RuntimeError('boom')):
            screen.translate()
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'), 'The run stopped because of an error: boom')
        self.assertFalse(self.app.translating or screen.running)
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertTrue(self.app.stepper.link_enabled)
        self.assertEqual(self.logs('inserts') + self.logs('errors'), [])
        self.assertEqual((str(screen.translate_button.cget('text')), str(screen.translate_button.cget('style'))),
                         ('Translate', PRIMARY))
        self.assertEqual(state(screen.translate_button), 'disabled')

    def test_error_text_is_the_first_line_and_shortened(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        with patch.object(self.app.service, 'run', side_effect=RuntimeError('bad ' * 80 + '\nsecond line')):
            screen.translate()
        text = screen.status.message.cget('text')
        self.assertTrue(text.startswith('The run stopped because of an error: bad bad') and text.endswith('bad...'))
        self.assertNotIn('second line', text)

    def test_a_second_run_after_reload_works(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.translate()
        screen.load()
        self.assertIsNotNone(screen.selection)
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.translate()
        self.assertEqual(len(self.fake_db.inserts()), 4)


# ===================================================================== chiusura

class ToolsShellTests(UiCase):
    """Il passo 2 con piu' strumenti: la griglia (che si puo' nascondere) e lo strumento scelto."""

    def setUp(self):
        super().setUp()
        self.builds = {}

    def fake_tool(self, name, title, **kw):
        built = self.builds.setdefault(name, [])

        def build(parent, app):
            frame = ttk.Frame(parent)
            ttk.Label(frame, text=f'{title} screen').pack()
            built.append(frame)
            return frame

        return Tool(name, title, build, **kw)

    @staticmethod
    def strings_tool():
        return Tool('strings', 'Strings', lambda parent, app: TranslationScreen(parent, app), writes=True)

    def shell(self, *tools):
        self.app.tools = list(tools)
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        return self.app.screen

    def press(self, widget, key):
        """Un tasto arriva al widget col focus: si da' il focus al widget e poi si preme."""
        self.root.deiconify()
        widget.focus_force()
        self.root.update()
        widget.event_generate(key)

    def test_with_one_tool_the_screen_is_the_tool_itself(self):
        screen = self.step2()
        self.assertIsInstance(screen, TranslationScreen)
        self.assertEqual(self.app.stepper._names[1].cget('text'), 'Translation')

    def test_with_more_tools_the_step_is_called_tools_and_the_shell_opens_the_first_one_that_is_on(self):
        self.app.stepper.set_name(2, 'Tools')            # lo fa JTApp quando nasce con piu' strumenti
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        self.assertIsInstance(screen, ToolsScreen)
        self.assertEqual(screen.selected, 'strings')
        self.assertIsInstance(screen.current, TranslationScreen)
        self.assertEqual(self.builds['names'], [])                       # gli altri non si costruiscono finche' non servono

    def test_the_app_names_the_step_tools_when_it_starts_with_more_than_one_tool(self):
        other = tk.Tk()
        self.addCleanup(other.destroy)
        app = JTApp(other, self.paths, self.db, runner=self.make_runner(), scale_factor=1.0,
                    tools=[self.strings_tool(), self.fake_tool('names', 'Names')])
        self.assertEqual(app.stepper._names[1].cget('text'), 'Tools')

    def test_a_tool_without_its_tables_is_off_with_the_reason_and_the_first_on_one_opens(self):
        self.fake_db.invalid_tables = {'FW_STRINGS_X'}
        screen = self.shell(self.fake_tool('names', 'Names', requires=('FW_STRINGS_X',)), self.strings_tool())
        tabs = screen.menu.tabs
        self.assertEqual(str(tabs['names'].cget('fg')), PALETTE['muted'])        # spenta: grigia
        self.assertEqual(screen.problems['names'], 'needs FW_STRINGS_X: not found on this database')
        self.assertEqual(screen.selected, 'strings')                       # il primo acceso, non il primo della lista
        screen.select('names')                                              # uno spento non si apre
        self.assertEqual(screen.selected, 'strings')
        tabs['names'].event_generate('<Button-1>')                          # nemmeno con un clic
        self.assertEqual(screen.selected, 'strings')

    def test_the_reason_of_an_off_tool_is_in_its_tooltip(self):
        self.fake_db.invalid_tables = {'FW_STRINGS_X'}
        screen = self.shell(self.fake_tool('names', 'Names', requires=('FW_STRINGS_X',)), self.strings_tool())
        tip = screen.menu.tips[0]
        tip.show()
        try:
            texts = all_texts(tip.tip)
            self.assertIn('Not available', texts)
            self.assertIn('needs FW_STRINGS_X: not found on this database', texts)
        finally:
            tip.hide()

    def test_switching_keeps_each_tool_as_it_was(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        first = screen.current
        screen.select('names')
        self.assertEqual(screen.selected, 'names')
        self.assertEqual(first.winfo_manager(), '')                        # lo strumento di prima non si vede
        self.assertEqual(len(self.builds['names']), 1)
        screen.select('strings')
        self.assertIs(screen.current, first)                               # e' lo stesso, non ricostruito
        screen.select('names')
        self.assertEqual(len(self.builds['names']), 1)

    def test_the_selected_tool_is_highlighted(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        menu = screen.menu

        def look(name):
            return str(menu.tabs[name].cget('fg')), str(menu.lines[name].cget('bg'))

        self.assertEqual(look('strings'), (PALETTE['accent'], PALETTE['accent']))      # aperta: blu con la linea sotto
        self.assertEqual(look('names'), (PALETTE['text'], PALETTE['bg']))
        screen.select('names')
        self.assertEqual(look('names'), (PALETTE['accent'], PALETTE['accent']))
        self.assertEqual(look('strings'), (PALETTE['text'], PALETTE['bg']))

    def test_a_click_on_a_tab_opens_that_tool(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        screen.menu.tabs['names'].event_generate('<Button-1>')
        self.assertEqual(screen.selected, 'names')
        self.press(screen.menu.tabs['strings'], '<Return>')
        self.assertEqual(screen.selected, 'strings')

    def test_the_hover_colours_a_tab_that_is_not_open_but_never_the_open_one(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        menu = screen.menu
        menu.tabs['names'].event_generate('<Enter>')
        self.assertEqual(str(menu.tabs['names'].cget('fg')), PALETTE['accent_dark'])
        menu.tabs['names'].event_generate('<Leave>')
        self.assertEqual(str(menu.tabs['names'].cget('fg')), PALETTE['text'])
        menu.tabs['strings'].event_generate('<Enter>')
        self.assertEqual(str(menu.tabs['strings'].cget('fg')), PALETTE['accent'])

    def test_the_tool_grid_can_be_hidden_and_the_tool_stays(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        menu = screen.menu
        self.assertTrue(menu.expanded)
        self.assertEqual(menu.strip.winfo_manager(), 'pack')
        menu.arrow.event_generate('<Button-1>')                            # la freccia nasconde la riga
        self.assertFalse(menu.expanded)
        self.assertEqual(menu.strip.winfo_manager(), '')                   # le schede spariscono
        self.assertEqual(menu.summary.cget('text'), 'Strings')             # si vede quale strumento e' aperto
        self.assertEqual(menu.summary.winfo_manager(), 'pack')
        self.assertEqual(screen.current.winfo_manager(), 'pack')           # lo strumento resta
        self.press(menu.arrow, '<Return>')                                 # e la stessa freccia la riapre
        self.assertTrue(menu.expanded)
        self.assertEqual(menu.summary.winfo_manager(), '')
        screen.select('names')
        menu.collapse()
        self.assertEqual(menu.summary.cget('text'), 'Names')

    def test_hiding_the_grid_makes_the_window_adapt(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        with patch.object(JTApp, 'fit_window') as fit:
            screen.menu.collapse()
            screen.menu.expand()
        self.assertEqual(fit.call_count, 2)

    def test_no_switching_while_something_is_running(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        self.app.translating = True
        screen.select('names')
        self.assertEqual(screen.selected, 'strings')
        self.app.translating = False
        screen.select('names')
        self.assertEqual(screen.selected, 'names')

    def test_the_app_asks_the_shell_about_the_preview_of_the_current_tool(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        self.assertIsNone(screen.preview)
        self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.current.load()
        screen.current.preview_button.invoke()
        self.assertIsNotNone(screen.preview)
        with patch.object(JTApp, 'confirm', return_value=False) as confirm, patch.object(JTApp, 'finish_close') as finish:
            self.app.on_closing()                                          # c'e' un'anteprima da scrivere: chiede
        self.assertEqual(confirm.call_args.args[0], 'Discard the preview and quit?')
        finish.assert_not_called()
        screen.select('names')                                             # un altro strumento: nessuna anteprima da perdere
        self.assertIsNone(screen.preview)

    def test_closing_during_a_run_goes_to_the_tool_that_runs(self):
        screen = self.shell(self.strings_tool(), self.fake_tool('names', 'Names'))
        with patch.object(type(screen.current), 'on_close_requested') as asked:
            screen.on_close_requested()
        asked.assert_called_once()

    def test_a_shell_with_nothing_on_shows_all_tools_off_and_no_screen(self):
        self.fake_db.invalid_tables = {'A', 'B'}
        screen = self.shell(self.fake_tool('a', 'Aa', requires=('A',)), self.fake_tool('b', 'Bb', requires=('B',)))
        self.assertIsNone(screen.selected)
        self.assertIsNone(screen.current)
        self.assertIsNone(screen.preview)
        self.assertEqual({str(label.cget('fg')) for label in screen.menu.tabs.values()}, {PALETTE['muted']})
        screen.on_close_requested()                                        # senza strumento aperto non fa danni

    def test_table_exists_on_the_database(self):
        self.app.connect(dict(FAKE_CONNECTION))
        self.fake_db.invalid_tables = {'MISSING'}
        self.assertTrue(self.db.table_exists('FW_STRINGS'))
        self.assertFalse(self.db.table_exists('MISSING'))
        self.db.close()
        self.assertFalse(self.db.table_exists('FW_STRINGS'))


class TecsqlScreenTests(UiCase):
    """Lo strumento SQL <-> TecSQL: si incolla una query e si traduce; non scrive e non serve la chiave Azure."""

    ROWS = [
        ('GD_LIRIG', 'LIRIG_LICOD', 'RigaListino', 'CodListino', 'C', '10', '0'),
        ('GD_LIRIG', 'LIRIG_CATLI', 'RigaListino', 'CatListino', 'C', '2', '0'),
        ('GD_LIRIG', 'LIRIG_PREZO', 'RigaListino', 'Prezzo', 'N', '15', '4'),
        ('GD_LITES', 'LITES_LICOD', 'TestataListino', 'Codice', 'C', '10', '0'),
        ('MD_ARTI', 'ARTI_ARTCO', 'Articolo', 'Codice', 'C', '20', '0'),
        ('MD_ARTI', 'ARTI_ARTCO', 'ArticoloEsteso', 'Codice', 'C', '20', '0'),
    ]

    def setUp(self):
        super().setUp()
        from jt import dictionary
        dictionary.forget()
        self.addCleanup(dictionary.forget)
        self.fake_db.dictionary_rows = list(self.ROWS)

    def open(self):
        """Il passo 2 con Strings e SQL <> TecSQL, aperto sul secondo."""
        self.app.tools = [ToolsShellTests.strings_tool(), next(t for t in default_tools() if t.name == 'tecsql')]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        shell = self.app.screen
        shell.select('tecsql')
        return shell.current

    def run_translate(self, screen, text):
        screen.input.delete('1.0', 'end')
        screen.input.insert('1.0', text)
        screen.translate_button.invoke()

    def test_it_opens_with_the_dictionary_read_once(self):
        screen = self.open()
        self.assertEqual(screen.label_dictionary.cget('text'), 'Names dictionary: 6 fields')
        self.assertEqual(state(screen.copy_button), 'disabled')
        self.assertEqual(state(screen.swap_button), 'disabled')
        self.assertEqual(len(self.fake_db.dictionary_queries), 1)

    def test_tecsql_to_sql(self):
        screen = self.open()
        self.run_translate(screen, "SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CatListino = 'LL'")
        self.assertEqual(screen.result_text(), "SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG WHERE GD_LIRIG.LIRIG_CATLI = 'LL'")
        self.assertEqual(screen.label_direction.cget('text'), 'TecSQL → SQL')
        self.assertEqual(screen.direction, 'tecsql_to_sql')
        self.assertEqual(screen.status.message.cget('text'), 'Translated to SQL.')
        self.assertEqual((state(screen.copy_button), state(screen.swap_button)), ('normal', 'normal'))

    def test_sql_to_tecsql(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertEqual(screen.result_text(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertEqual(screen.label_direction.cget('text'), 'SQL → TecSQL')
        self.assertEqual(screen.status.message.cget('text'), 'Translated to TecSQL.')

    def test_a_multiline_query_is_normalized(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD\\n   FROM   GD_LIRIG\\n WHERE GD_LIRIG.LIRIG_CATLI = 1'.replace('\\n', '\n'))
        self.assertEqual(screen.result_text(),
                         'SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CatListino = 1')

    def test_an_empty_query_says_what_to_do(self):
        screen = self.open()
        self.run_translate(screen, '   \\n  '.replace('\\n', '\n'))
        self.assertEqual(screen.result_text(), '')
        self.assertIn('Paste a query', screen.status.message.cget('text'))

    def test_an_error_is_shown_and_the_old_result_is_cleared(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.run_translate(screen, 'SELECT $Nope.X FROM $Nope')
        self.assertEqual(screen.result_text(), '')
        self.assertEqual(screen.status.message.cget('text'), 'Logical table not mapped: $Nope')
        self.assertEqual((state(screen.copy_button), state(screen.swap_button)), ('disabled', 'disabled'))
        self.run_translate(screen, 'SELECT X FROM NON_ESISTE')
        self.assertEqual(screen.status.message.cget('text'), 'Table NON_ESISTE not found in the dictionary')

    def test_remove_parameters_only_matters_for_tecsql(self):
        screen = self.open()
        query = 'SELECT $RigaListino.CodListino FROM $RigaListino WHERE $RigaListino.CatListino = ?categoria'
        self.run_translate(screen, query)
        self.assertIn('?categoria', screen.result_text())
        screen.var_strip.set(True)
        screen.translate_button.invoke()
        self.assertNotIn('?categoria', screen.result_text())
        self.assertNotIn('WHERE', screen.result_text())

    def test_a_table_with_two_logical_names_asks_which(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT ARTI_ARTCO FROM MD_ARTI')
        self.assertEqual(screen.result_text(), '')
        self.assertEqual(screen.choice_row.winfo_manager(), 'pack')
        self.assertIn('MD_ARTI has 2 logical names', screen.choice_label.cget('text'))
        self.assertEqual(sorted(screen.choice_box.cget('values')), ['$Articolo', '$ArticoloEsteso'])
        self.assertIn('choose one', screen.status.message.cget('text'))
        screen.var_choice.set('$ArticoloEsteso')                      # come sceglierlo dal menu
        screen.choice_box.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.result_text(), 'SELECT $ArticoloEsteso.Codice FROM $ArticoloEsteso')
        self.assertEqual(screen.choice_row.winfo_manager(), '')       # scelto: la domanda sparisce

    def test_a_new_translation_hides_an_old_question(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT ARTI_ARTCO FROM MD_ARTI')
        self.assertEqual(screen.choice_row.winfo_manager(), 'pack')
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertEqual(screen.choice_row.winfo_manager(), '')

    def test_a_partial_translation_is_a_warning_with_the_fields(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT LIRIG_LICOD FROM GD_LIRIG WHERE LIRIG_NOPE = 1')
        self.assertIn('$RigaListino.CodListino', screen.result_text())
        self.assertEqual(screen.status.state, 'warn')
        self.assertIn('LIRIG_NOPE', screen.status.message.cget('text'))

    def test_use_the_result_as_query_goes_the_other_way(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        screen.swap_button.invoke()
        self.assertEqual(screen.query_text(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertEqual(screen.result_text(), '')
        screen.translate_button.invoke()
        self.assertEqual(screen.result_text(), 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')

    def test_copy_puts_the_result_on_the_clipboard(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        screen.copy_button.invoke()
        self.assertEqual(self.root.clipboard_get(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertEqual(screen.status.message.cget('text'), 'Result copied to the clipboard.')

    def test_clear_empties_everything(self):
        screen = self.open()
        self.run_translate(screen, 'SELECT ARTI_ARTCO FROM MD_ARTI')
        screen.clear_button.invoke()
        self.assertEqual((screen.query_text(), screen.result_text()), ('', ''))
        self.assertEqual(screen.choice_row.winfo_manager(), '')
        self.assertIn('Paste a query', screen.status.message.cget('text'))

    def test_control_return_translates(self):
        screen = self.open()
        screen.input.insert('1.0', 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.root.deiconify()
        screen.input.focus_force()
        self.root.update()
        screen.input.event_generate('<Control-Return>')
        self.assertEqual(screen.result_text(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertNotIn('\n', screen.input.get('1.0', 'end').strip())          # il tasto non aggiunge un a capo

    def test_reload_reads_the_dictionary_again(self):
        screen = self.open()
        self.fake_db.dictionary_rows = self.ROWS[:2]
        screen.reload_button.invoke()
        self.assertEqual(len(self.fake_db.dictionary_queries), 2)
        self.assertEqual(screen.label_dictionary.cget('text'), 'Names dictionary: 2 fields')
        self.assertIn('Dictionary reloaded', screen.status.message.cget('text'))
        self.run_translate(screen, 'SELECT ARTI_ARTCO FROM MD_ARTI')                 # il dizionario nuovo non ha MD_ARTI
        self.assertEqual(screen.status.message.cget('text'), 'Table MD_ARTI not found in the dictionary')

    def test_a_dictionary_that_cannot_be_read_is_said_and_retried_at_the_next_translation(self):
        self.fake_db.dictionary_error = True
        screen = self.open()
        self.assertEqual(screen.label_dictionary.cget('text'), 'Names dictionary not loaded')
        self.assertIn('Could not read the dictionary of names', screen.status.message.cget('text'))
        self.fake_db.dictionary_error = False
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertEqual(screen.result_text(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertTrue(screen.label_dictionary.cget('text').startswith('Names dictionary: '))

    def test_it_needs_no_azure_key_and_writes_nothing(self):
        self.key_reason = 'the key file was not found'
        screen = self.open()
        self.run_translate(screen, 'SELECT GD_LIRIG.LIRIG_LICOD FROM GD_LIRIG')
        self.assertEqual(screen.result_text(), 'SELECT $RigaListino.CodListino FROM $RigaListino')
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual(screen.status.state, 'ok')

    def test_the_tool_is_off_without_the_dictionary_tables(self):
        self.fake_db.invalid_tables = {'FW_TABLES'}
        self.app.tools = [ToolsShellTests.strings_tool(), next(t for t in default_tools() if t.name == 'tecsql')]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        shell = self.app.screen
        self.assertEqual(shell.problems['tecsql'], 'needs FW_TABLES: not found on this database')
        shell.select('tecsql')
        self.assertEqual(shell.selected, 'strings')

    def test_the_real_app_offers_both_tools(self):
        self.assertEqual([t.name for t in default_tools()], ['strings', 'tecsql', 'names', 'indexes'])
        tecsql = default_tools()[1]
        self.assertEqual((tecsql.requires, tecsql.writes), (('FW_TABLES', 'FW_TABLE_FIELDS'), False))


class NamesToolsCase(UiCase):
    """Base degli strumenti Names e Indexes: un dizionario di prova e gli indici di prova nel finto database."""

    ROWS = [
        ('GD_LIRIG', 'LIRIG_LICOD', 'RigaListino', 'CodListino', 'C', '10', '0'),
        ('GD_LIRIG', 'LIRIG_PREZO', 'RigaListino', 'Prezzo', 'N', '15', '4'),
        ('GD_LITES', 'LITES_LICOD', 'TestataListino', 'Codice', 'C', '10', '0'),
        ('MD_ARTI', 'ARTI_ARTCO', 'Articolo', 'Codice', 'C', '20', '0'),
        ('MD_ARTI', 'ARTI_DESCR', 'Articolo', 'Descrizione', 'C', '50', '0'),
        ('MD_ARTI', 'ARTI_ARTCO', 'ArticoloEsteso', 'Codice', 'C', '20', '0'),
        ('FW_STRINGS', 'CODE', 'FwStrings', 'Code', 'N', '10', '0'),
        ('-', '-', 'Virtuale', 'Campo', 'C', '5', '0'),
    ]
    INDEXES = [('JFLEX', 'GD_LIRIG', 'IDX_LIRIG_1', 'UNIQUE', 'JFLEX'), ('JFLEX', 'GD_LIRIG', 'IDX_LIRIG_2', 'NONUNIQUE', 'JFLEX'),
               ('JFLEX', 'FW_STRINGS', 'IDX_STR', 'UNIQUE', 'JFLEX')]
    COLUMNS = [('JFLEX', 'GD_LIRIG', 'JFLEX', 'IDX_LIRIG_1', 'LIRIG_LICOD', 1), ('JFLEX', 'GD_LIRIG', 'JFLEX', 'IDX_LIRIG_1', 'LIRIG_PREZO', 2),
               ('JFLEX', 'GD_LIRIG', 'JFLEX', 'IDX_LIRIG_2', 'LIRIG_PREZO', 1)]

    def setUp(self):
        super().setUp()
        from jt import dictionary
        dictionary.forget()
        self.addCleanup(dictionary.forget)
        self.fake_db.dictionary_rows = list(self.ROWS)
        self.fake_db.index_rows = list(self.INDEXES)
        self.fake_db.index_column_rows = list(self.COLUMNS)

    def open(self, name='names'):
        tools = {t.name: t for t in default_tools()}
        self.app.tools = [ToolsShellTests.strings_tool(), tools['names'], tools['indexes']]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        shell = self.app.screen
        shell.select(name)
        return shell.current

    def search(self, screen, table, fields=''):
        screen.picker.set_value(table)
        if hasattr(screen, 'fields'):
            screen.fields.delete(0, 'end')
            screen.fields.insert(0, fields)
        screen.picker.search()


class PreferencesFileTests(NamesToolsCase):
    def prefer(self, **data):
        from jt.jsonstore import write_json
        write_json(self.paths.preferences, data)

    def test_the_tool_opened_first_is_the_preferred_one(self):
        self.prefer(default_tool='indexes')
        self.assertEqual(self.open('indexes').__class__.__name__, 'IndexesScreen')
        self.assertEqual(self.app.screen.selected, 'indexes')

    def test_a_preferred_tool_that_does_not_exist_leaves_the_first(self):
        self.prefer(default_tool='nope')
        self.open('names')
        self.assertEqual(self.app.screen.tools[0].name, 'strings')

    def test_names_hides_the_columns_and_sorts_as_the_file_says(self):
        self.prefer(names={'sort': 'CAMPO_LOGICO', 'descending': True, 'hide_columns': ['DECIMALI', 'TIPO']})
        screen = self.open('names')
        self.search(screen, 'MD_ARTI')
        keys = [c[0] for c in screen.grid.columns]
        self.assertNotIn('DECIMALI', keys)
        self.assertNotIn('TIPO', keys)
        self.assertEqual(screen.grid.rows[0]['CAMPO_LOGICO'], 'Descrizione')
        self.assertEqual(screen.grid.sorted_by, ('CAMPO_LOGICO', False))

    def test_the_sort_of_a_hidden_column_is_skipped(self):
        self.prefer(names={'sort': 'TIPO', 'hide_columns': ['TIPO']})
        screen = self.open('names')
        self.search(screen, 'MD_ARTI')
        self.assertIsNone(screen.grid.sorted_by)

    def test_indexes_open_with_their_columns_when_asked(self):
        self.prefer(indexes={'expand_all': True})
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        self.assertTrue(all(screen.tree.item(i, 'open') for i in screen.tree.get_children()))

    def test_remove_parameters_can_start_on(self):
        self.prefer(tecsql={'strip_parameters': True})
        screen = self.open('names')
        from jt.ui.tecsql_screen import TecsqlScreen
        self.assertTrue(TecsqlScreen(self.root, self.app).var_strip.get())


class NamesScreenTests(NamesToolsCase):
    def test_it_opens_with_the_dictionary_and_nothing_to_copy(self):
        screen = self.open()
        self.assertEqual(screen.bar.label.cget('text'), 'Names dictionary: 8 fields')
        self.assertEqual(state(screen.copy_button), 'disabled')
        self.assertTrue(screen.search_section.expanded)

    def test_a_table_by_physical_name_shows_its_fields(self):
        screen = self.open()
        self.search(screen, 'gd_lirig')
        self.assertEqual([r['CAMPO_FISICO'] for r in screen.grid.rows], ['LIRIG_LICOD', 'LIRIG_PREZO'])
        self.assertEqual(screen.summary_text.split('  ·  ')[0], 'GD_LIRIG → RigaListino')
        self.assertEqual(screen.status.message.cget('text'), '2 fields. Click a cell to copy it.')
        self.assertEqual(screen.result_section.summary.cget('text'), 'GD_LIRIG → RigaListino · 2 fields')
        self.assertEqual(state(screen.copy_button), 'normal')
        self.assertEqual(self.app.current_table, {'physical': 'GD_LIRIG', 'logical': 'RigaListino'})

    def test_after_a_result_the_search_folds_to_leave_room(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG')
        self.assertFalse(screen.search_section.expanded)
        self.assertEqual(screen.search_section.summary.cget('text'), 'GD_LIRIG → RigaListino')
        self.assertTrue(screen.result_section.expanded)

    def test_a_table_by_logical_name_in_any_case(self):
        screen = self.open()
        self.search(screen, 'testatalistino')
        self.assertEqual(screen.summary_text.split('  ·  ')[0], 'GD_LITES → TestataListino')

    def test_a_table_with_two_logical_names_shows_which_field_is_of_which(self):
        screen = self.open()
        self.search(screen, 'MD_ARTI')
        self.assertEqual(len(screen.grid.rows), 3)
        self.assertEqual(screen.grid.columns[0][0], 'TABELLA_LOGICA')
        self.assertIn('2 logical names', screen.summary_text.split('  ·  ')[0])
        self.search(screen, 'ArticoloEsteso')                            # il nome logico: solo il suo
        self.assertEqual(len(screen.grid.rows), 1)
        self.assertNotEqual(screen.grid.columns[0][0], 'TABELLA_LOGICA')

    def test_some_fields_only_and_the_missing_ones_in_red(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG', 'Prezzo, Nope')
        self.assertEqual([r['CAMPO_FISICO'] for r in screen.grid.rows], ['LIRIG_PREZO', 'Nope'])
        self.assertTrue(screen.grid.rows[1]['notFound'])
        self.assertEqual(screen.status.state, 'warn')
        self.assertIn('1 of the requested fields were not found', screen.status.message.cget('text'))
        self.assertIn('notfound', screen.grid.tree.item('1', 'tags'))

    def test_no_exact_match_offers_suggestions_and_opens_the_search(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG')                                  # il risultato ripiega la ricerca
        self.search(screen, 'lis')
        self.assertEqual(screen.picker.box.winfo_manager(), 'pack')
        self.assertTrue(screen.search_section.expanded)                  # si riapre per far vedere i suggerimenti
        shown = [screen.picker.list.item(i, 'text') for i in screen.picker.list.get_children()]
        self.assertEqual(sorted(shown), ['GD_LIRIG → RigaListino', 'GD_LITES → TestataListino'])
        self.assertEqual(screen.status.state, 'warn')
        screen.picker.list.selection_set(screen.picker.list.get_children()[0])
        screen.picker._choose()                                          # il doppio clic
        self.assertEqual(screen.picker.box.winfo_manager(), '')
        self.assertIn(screen.summary_text.split('  ·  ')[0], ('GD_LIRIG → RigaListino', 'GD_LITES → TestataListino'))

    def test_a_typo_is_suggested(self):
        screen = self.open()
        self.search(screen, 'gd_liryg')
        names_shown = [screen.picker.list.item(i, 'text') for i in screen.picker.list.get_children()]
        self.assertIn('GD_LIRIG → RigaListino', names_shown)
        self.assertIn('similar', screen.picker.list.set(screen.picker.list.get_children()[0], 'why'))

    def test_nothing_close_is_an_error_with_advice(self):
        screen = self.open()
        self.search(screen, 'qqqqqqqq')
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Table "QQQQQQQQ" not found in the dictionary', screen.status.message.cget('text'))

    def test_an_empty_name_says_what_to_type(self):
        screen = self.open()
        self.search(screen, '   ')
        self.assertEqual(screen.status.state, 'info')
        self.assertIn('Type a table name', screen.status.message.cget('text'))

    def test_a_descriptor_without_a_table_is_shown_but_not_remembered(self):
        screen = self.open()
        self.search(screen, 'Virtuale')
        self.assertEqual(screen.summary_text.split('  ·  ')[0], '(no physical table) → Virtuale')
        self.assertEqual(self.app.settings.search_history(), [])
        self.assertEqual(self.app.current_table['physical'], '-')

    def test_a_click_on_a_column_heading_sorts_and_again_reverses(self):
        screen = self.open()
        self.search(screen, 'MD_ARTI')
        screen.grid.sort_by('CAMPO_LOGICO')
        self.assertEqual([r['CAMPO_LOGICO'] for r in screen.grid.rows], ['Codice', 'Codice', 'Descrizione'])
        self.assertIn('▲', screen.grid.tree.heading('CAMPO_LOGICO', 'text'))
        screen.grid.sort_by('CAMPO_LOGICO')
        self.assertEqual(screen.grid.rows[0]['CAMPO_LOGICO'], 'Descrizione')
        self.assertIn('▼', screen.grid.tree.heading('CAMPO_LOGICO', 'text'))
        screen.grid.sort_by('AMPIEZZA')                                    # numeri come numeri: 20, 20, 50
        self.assertEqual([r['AMPIEZZA'] for r in screen.grid.rows], ['20', '20', '50'])

    def test_a_cell_is_copied_with_a_click(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG')
        tree = screen.grid.tree
        with patch.object(tree, 'identify_region', return_value='cell'), patch.object(tree, 'identify_row', return_value='1'), \
                patch.object(tree, 'identify_column', return_value='#2'):
            screen.grid._click(SimpleNamespace(x=5, y=5))
        self.assertEqual(self.root.clipboard_get(), 'Prezzo')
        self.assertEqual(screen.status.message.cget('text'), 'Copied: Prezzo')

    def test_copy_all_is_text_with_tabs_and_a_header(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG')
        screen.copy_button.invoke()
        lines = self.root.clipboard_get().split('\n')
        self.assertEqual(lines[0], 'TABELLA_FISICA\tCAMPO_FISICO\tTABELLA_LOGICA\tCAMPO_LOGICO\tTIPO\tAMPIEZZA\tDECIMALI')
        self.assertEqual(lines[1], 'GD_LIRIG\tLIRIG_LICOD\tRigaListino\tCodListino\tC\t10\t0')
        self.assertEqual(screen.status.message.cget('text'), 'All rows copied to the clipboard.')

    def test_recent_searches_are_remembered_and_run_again(self):
        screen = self.open()
        self.search(screen, 'GD_LIRIG')
        self.search(screen, 'FW_STRINGS')
        self.assertEqual(self.app.settings.search_history(), [{'fisico': 'FW_STRINGS', 'logico': 'FwStrings'},
                                                               {'fisico': 'GD_LIRIG', 'logico': 'RigaListino'}])
        self.assertEqual(list(screen.picker.entry.cget('values')), ['FW_STRINGS', 'GD_LIRIG'])
        screen.picker.set_value('GD_LIRIG')                                # si sceglie dal menu: la ricerca parte da sola
        screen.picker.entry.event_generate('<<ComboboxSelected>>')
        self.assertEqual(screen.summary_text.split('  ·  ')[0], 'GD_LIRIG → RigaListino')

    def test_it_reads_and_writes_nothing_in_the_database_and_needs_no_key(self):
        self.key_reason = 'the key file was not found'
        screen = self.open()
        self.search(screen, 'GD_LIRIG')
        self.assertEqual(self.fake_db.writes(), [])
        self.assertEqual(screen.status.state, 'ok')

    def test_a_dictionary_that_cannot_be_read_is_said_and_retried(self):
        self.fake_db.dictionary_error = True
        screen = self.open()
        self.assertEqual(screen.bar.label.cget('text'), 'Names dictionary not loaded')
        self.assertEqual(screen.status.state, 'error')
        self.fake_db.dictionary_error = False
        self.search(screen, 'GD_LIRIG')
        self.assertEqual(screen.summary_text.split('  ·  ')[0], 'GD_LIRIG → RigaListino')

    def test_the_tool_is_off_without_the_dictionary_tables(self):
        self.fake_db.invalid_tables = {'FW_TABLE_FIELDS'}
        self.app.tools = [ToolsShellTests.strings_tool(), next(t for t in default_tools() if t.name == 'names')]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        self.assertEqual(self.app.screen.problems['names'], 'needs FW_TABLE_FIELDS: not found on this database')


class IndexesScreenTests(NamesToolsCase):
    def test_the_indexes_of_a_table_with_their_columns_in_order(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        top = screen.tree.get_children()
        self.assertEqual([screen.tree.item(i, 'text') for i in top], ['IDX_LIRIG_1', 'IDX_LIRIG_2'])
        self.assertEqual([screen.tree.set(i, 'kind') for i in top], ['UNIQUE', 'NONUNIQUE'])
        first = [screen.tree.item(c, 'text') for c in screen.tree.get_children(top[0])]
        self.assertEqual(first, ['LIRIG_LICOD', 'LIRIG_PREZO'])
        self.assertEqual([screen.tree.set(c, 'kind') for c in screen.tree.get_children(top[0])], ['1', '2'])
        self.assertEqual(screen.summary_text.split('  ·  ')[0], 'GD_LIRIG → RigaListino')
        self.assertEqual(screen.status.message.cget('text'), '2 indexes. Open one to see its columns.')
        self.assertFalse(screen.table_section.expanded)
        self.assertEqual(screen.table_section.summary.cget('text'), 'GD_LIRIG')

    def test_only_the_table_asked_is_read_with_a_bind_variable(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        self.assertEqual(len(self.fake_db.index_queries), 2)
        self.assertTrue(all(binds == {'t': 'GD_LIRIG'} for _, binds in self.fake_db.index_queries))

    def test_a_table_without_indexes_says_so(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LITES')
        self.assertEqual(screen.tree.get_children(), ())
        self.assertEqual(screen.status.state, 'info')
        self.assertEqual(screen.status.message.cget('text'), 'No index found for GD_LITES.')
        self.assertEqual(state(screen.copy_button), 'disabled')

    def test_expand_and_collapse_all(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        screen.expand_button.invoke()
        self.assertTrue(all(screen.tree.item(i, 'open') for i in screen.tree.get_children()))
        screen.collapse_button.invoke()
        self.assertFalse(any(screen.tree.item(i, 'open') for i in screen.tree.get_children()))

    def test_copy_all_puts_every_index_and_its_columns_on_the_clipboard(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        screen.copy_button.invoke()
        text = self.root.clipboard_get()
        self.assertTrue(text.startswith('INDEXES OF TABLE: GD_LIRIG\n\nINDEX: IDX_LIRIG_1 (UNIQUE)\nCOLUMNS:\n  1. LIRIG_LICOD\n  2. LIRIG_PREZO\n'))
        self.assertIn('INDEX: IDX_LIRIG_2 (NONUNIQUE)', text)

    def test_a_click_copies_a_name_or_a_value(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        with patch.object(screen.tree, 'identify_row', return_value='i0'), patch.object(screen.tree, 'identify_region', return_value='tree'), \
                patch.object(screen.tree, 'identify_column', return_value='#0'):
            screen._click(SimpleNamespace(x=5, y=5))
        self.assertEqual(self.root.clipboard_get(), 'IDX_LIRIG_1')
        with patch.object(screen.tree, 'identify_row', return_value='i0'), patch.object(screen.tree, 'identify_region', return_value='cell'), \
                patch.object(screen.tree, 'identify_column', return_value='#1'):
            screen._click(SimpleNamespace(x=5, y=5))
        self.assertEqual(self.root.clipboard_get(), 'UNIQUE')

    def test_the_table_searched_in_names_is_proposed_when_the_tab_opens(self):
        shell_screen = self.open('names')
        self.search(shell_screen, 'FW_STRINGS')
        shell = self.app.screen
        shell.select('indexes')
        screen = shell.current
        self.assertEqual(screen.picker.value(), 'FW_STRINGS')
        self.assertEqual([screen.tree.item(i, 'text') for i in screen.tree.get_children()], ['IDX_STR'])
        shell.select('names')                                            # tornando e riaprendo non rilegge la stessa tabella
        before = len(self.fake_db.index_queries)
        shell.select('indexes')
        self.assertEqual(len(self.fake_db.index_queries), before)

    def test_a_new_connection_forgets_the_last_table(self):
        shell_screen = self.open('names')
        self.search(shell_screen, 'FW_STRINGS')
        self.assertIsNotNone(self.app.current_table)
        self.app.connect(dict(FAKE_CONNECTION))
        self.assertIsNone(self.app.current_table)

    def test_a_descriptor_without_a_table_has_no_indexes(self):
        screen = self.open('indexes')
        self.search(screen, 'Virtuale')
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('has no physical table', screen.status.message.cget('text'))

    def test_an_error_reading_the_indexes_is_shown(self):
        screen = self.open('indexes')
        with patch('jt.indexes.read', side_effect=RuntimeError('ORA-00942 boom')):
            self.search(screen, 'GD_LIRIG')
        self.assertEqual(screen.status.state, 'error')
        self.assertIn('Could not read the indexes: ORA-00942 boom', screen.status.message.cget('text'))
        self.assertEqual(self.root['cursor'], '')                           # il cursore di attesa torna normale

    def test_the_tool_is_off_without_the_index_views(self):
        self.fake_db.invalid_tables = {'ALL_IND_COLUMNS'}
        self.app.tools = [ToolsShellTests.strings_tool(), next(t for t in default_tools() if t.name == 'indexes')]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        self.assertEqual(self.app.screen.problems['indexes'], 'needs ALL_IND_COLUMNS: not found on this database')

    def test_suggestions_open_the_table_section(self):
        screen = self.open('indexes')
        self.search(screen, 'GD_LIRIG')
        self.assertFalse(screen.table_section.expanded)
        self.search(screen, 'lis')
        self.assertTrue(screen.table_section.expanded)
        self.assertEqual(screen.picker.box.winfo_manager(), 'pack')


class DataTableTests(UiCase):
    COLUMNS = (('A', 'Name', 100, False), ('AMPIEZZA', 'Width', 60, True))

    def table(self):
        from jt.ui.datatable import DataTable
        copied = []
        table = DataTable(self.root, self.COLUMNS, on_copy=copied.append)
        table.copied = copied
        return table

    def test_rows_are_shown_and_cleared(self):
        table = self.table()
        table.set_rows([{'A': 'x', 'AMPIEZZA': 3}, {'A': 'y', 'AMPIEZZA': None}])
        self.assertEqual(len(table.tree.get_children()), 2)
        self.assertEqual(table.tree.set('1', 'AMPIEZZA'), '')
        table.clear()
        self.assertEqual(table.tree.get_children(), ())

    def test_sorting_toggles_and_numbers_are_numbers(self):
        table = self.table()
        table.set_rows([{'A': 'b', 'AMPIEZZA': '10'}, {'A': 'A', 'AMPIEZZA': '9'}, {'A': 'c', 'AMPIEZZA': '-'}])
        table.sort_by('A')
        self.assertEqual([r['A'] for r in table.rows], ['A', 'b', 'c'])
        table.sort_by('AMPIEZZA')
        self.assertEqual([r['AMPIEZZA'] for r in table.rows], ['9', '10', '-'])
        table.sort_by('AMPIEZZA')
        self.assertEqual([r['AMPIEZZA'] for r in table.rows], ['-', '10', '9'])
        table.set_rows(table.rows)                                         # nuove righe: niente freccia
        self.assertNotIn('▲', table.tree.heading('AMPIEZZA', 'text'))

    def test_copy_text_and_the_callback(self):
        table = self.table()
        table.copy_text('hello')
        self.assertEqual(self.root.clipboard_get(), 'hello')
        self.assertEqual(table.copied, ['hello'])


class TreeBoxTests(UiCase):
    def settle(self):
        for _ in range(10):
            self.root.update()

    def test_a_column_is_as_wide_as_its_text_but_never_above_the_maximum(self):
        from jt.ui.widgets import TreeBox
        box = TreeBox(self.root, columns=('a', 'b'), show='headings')
        box.fit_columns([('a', 'A'), ('b', 'B')], [{'a': 'x' * 400, 'b': 'y'}])
        self.assertEqual(int(box.tree.column('a', 'width')), scale.px(260))
        self.assertEqual(int(box.tree.column('b', 'width')), scale.px(50))               # il minimo

    def test_a_very_wide_table_does_not_widen_the_window_and_gets_a_scroll_bar(self):
        from jt.ui.widgets import TreeBox
        self.root.deiconify()
        self.root.geometry('500x300')
        box = TreeBox(self.root, columns=tuple(f'c{i}' for i in range(12)), show='headings')
        box.pack(fill='both', expand=True)
        columns = [(f'c{i}', f'Column {i}') for i in range(12)]
        box.fit_columns(columns, [{c: 'z' * 60 for c, _ in columns}])
        for c, title in columns:
            box.tree.heading(c, text=title)
        box.tree.insert('', 'end', values=['z' * 60] * 12)
        self.settle()
        self.assertEqual(self.root.winfo_width(), 500)
        self.assertEqual(box.hbar.winfo_manager(), 'grid')                         # le colonne non entrano: si scorre

    def test_the_scroll_bars_are_hidden_when_everything_fits(self):
        from jt.ui.widgets import TreeBox
        self.root.deiconify()
        self.root.geometry('500x300')
        box = TreeBox(self.root, columns=('a',), show='headings')
        box.pack(fill='both', expand=True)
        box.tree.insert('', 'end', values=['x'])
        self.settle()
        self.assertEqual(box.hbar.winfo_manager(), '')
        self.assertEqual(box.vbar.winfo_manager(), '')


class ScrolledTextTests(UiCase):
    def test_the_bar_shows_only_when_the_text_is_longer_than_the_field(self):
        from jt.ui.widgets import ScrolledText
        box = ScrolledText(self.root, height=3)
        box.pack(fill='both', expand=True)
        self.root.deiconify()
        self.root.geometry('300x200')
        for _ in range(10):
            self.root.update()
        self.assertEqual(box.bar.winfo_manager(), '')
        box.text.insert('1.0', '\n'.join(str(i) for i in range(40)))
        for _ in range(10):
            self.root.update()
        self.assertEqual(box.bar.winfo_manager(), 'pack')
        box.text.delete('1.0', 'end')
        for _ in range(10):
            self.root.update()
        self.assertEqual(box.bar.winfo_manager(), '')

    def test_a_read_only_one_can_be_filled_by_the_code(self):
        from jt.ui.widgets import ScrolledText
        box = ScrolledText(self.root, height=3, readonly=True)
        self.assertEqual(str(box.text.cget('state')), 'disabled')


class ResizableWindowTests(UiCase):
    def test_the_content_stretches_when_the_window_is_taller(self):
        screen = self.step2()
        self.root.deiconify()
        self.root.geometry('700x1000')
        for _ in range(15):
            self.root.update()
        area = self.app.area
        self.assertGreaterEqual(area.inner.winfo_height(), area.canvas.winfo_height() - 2)
        self.assertFalse(area.scrolling)

    def test_a_window_made_bigger_by_hand_is_not_shrunk_by_the_next_layout_change(self):
        self.step2()
        self.root.deiconify()
        for _ in range(10):
            self.root.update()
        self.root.geometry(f'{self.root.winfo_width() + 200}x{self.root.winfo_height() + 150}')
        for _ in range(15):
            self.root.update()
        self.assertTrue(self.app.user_sized)
        height = self.root.winfo_height()
        self.app.fit_window()
        for _ in range(10):
            self.root.update()
        self.assertGreaterEqual(self.root.winfo_height(), height - 2)

    def test_a_maximized_window_is_left_alone_but_the_minimum_stays_right(self):
        self.step2()
        self.root.deiconify()
        for _ in range(10):
            self.root.update()
        with patch.object(self.root, 'state', return_value='zoomed'), patch.object(self.root, 'geometry') as geometry:
            self.app.fit_window()
        geometry.assert_not_called()
        self.assertTrue(self.app.user_sized)

    def test_the_sql_tecsql_boxes_grow_with_the_window_and_have_a_divider(self):
        from jt import dictionary
        dictionary.forget()
        self.addCleanup(dictionary.forget)
        self.fake_db.dictionary_rows = list(TecsqlScreenTests.ROWS)
        self.app.tools = [ToolsShellTests.strings_tool(), next(t for t in default_tools() if t.name == 'tecsql')]
        self.app.connect(dict(FAKE_CONNECTION))
        self.app.show_translation()
        shell = self.app.screen
        shell.select('tecsql')
        screen = shell.current
        self.root.deiconify()
        self.root.geometry('900x500')
        for _ in range(15):
            self.root.update()
        small = screen.input.winfo_height(), screen.output.winfo_height()
        self.root.geometry('1100x900')
        for _ in range(20):
            self.root.update()
        big = screen.input.winfo_height(), screen.output.winfo_height()
        self.assertGreater(big[0], small[0])
        self.assertGreater(big[1], small[1])
        self.assertEqual(len(screen.panes.panes()), 2)                        # il divisore tra query e risultato


class NoKeyTests(UiCase):
    """Senza una chiave Azure valida JT legge e conta, ma non traduce e non scrive: nessun percorso porta a una scrittura."""

    NO_KEY = 'the key file was not found'

    def keyless(self, rows=2):
        self.key_reason = self.NO_KEY
        self.azure = self.use_azure()
        return self.loaded_strings(rows)

    def test_the_notice_names_the_reason_the_contact_and_the_folder(self):
        screen = self.keyless()
        text = screen.label_key.cget('text')
        self.assertIn('No Azure key (the key file was not found)', text)
        self.assertIn('can read and count rows, but it cannot translate or write', text)
        self.assertIn('Ask Kseniia Hrytskova for the key file', text)
        self.assertIn(os.path.dirname(self.paths.azure), text)
        self.assertEqual(screen.label_key.winfo_manager(), 'pack')

    def test_with_a_key_there_is_no_notice(self):
        screen = self.step2()
        self.assertEqual(screen.label_key.winfo_manager(), '')
        self.assertEqual(screen.key_problem, '')

    def test_load_still_works_and_counts_rows_but_translating_is_off(self):
        screen = self.keyless(3)
        self.assertIsNotNone(screen.selection)                       # Load ha letto le righe
        for button in (screen.preview_button, screen.translate_button, screen.write_button):
            self.assertEqual(state(button), 'disabled')

    def test_no_way_reaches_azure_or_the_database_without_the_key(self):
        screen = self.keyless(2)
        for action in (screen.translate, screen.run_preview, screen.write):
            action()
        self.assertEqual(self.azure.calls, [])
        self.assertEqual(self.fake_db.writes(), [])
        self.assertIn('No Azure key', screen.status.message.cget('text'))

    def test_update_by_keys_cannot_write_either(self):
        self.key_reason = self.NO_KEY
        self.azure = self.use_azure()
        self.fake_db.source['FW_STRINGS'] = plain_rows(2)
        screen = self.step2()
        self.choose(screen, keys='100000, 100001')
        screen.load()
        self.assertIsNotNone(screen.selection)
        screen.translate()
        self.assertEqual((self.azure.calls, self.fake_db.writes()), ([], []))

    def test_a_ready_preview_cannot_be_written_if_the_key_goes_away(self):
        self.azure = self.use_azure()
        screen = self.loaded_strings(2)
        screen.preview_button.invoke()
        self.assertIsNotNone(screen.preview)
        self.key_reason = self.NO_KEY                                # il file della chiave sparisce a programma aperto
        screen.write()
        self.assertEqual(self.fake_db.writes(), [])
        self.assertIn('No Azure key', screen.status.message.cget('text'))

    def test_the_key_put_in_place_with_the_program_open_is_picked_up_at_the_next_load(self):
        screen = self.keyless(2)
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.key_reason = ''
        self.fake_db.missing['FW_STRINGS'] = 2
        screen.load()
        self.assertEqual(screen.label_key.winfo_manager(), '')
        self.assertEqual(state(screen.translate_button), 'normal')
        screen.translate_button.invoke()
        self.assertEqual(len(self.fake_db.inserts()), 2)


class RealKeyCheckTests(UiCase):
    """Il controllo vero del file (negli altri test la chiave e' data per buona)."""

    def setUp(self):
        super().setUp()
        self.key_patch.stop()
        self.addCleanup(self.key_patch.start)

    def test_the_app_checks_the_real_file(self):
        if os.path.exists(self.paths.azure):
            os.remove(self.paths.azure)
        self.assertIn('not found', JTApp.azure_key_problem(self.app))
        os.makedirs(os.path.dirname(self.paths.azure), exist_ok=True)
        with open(self.paths.azure, 'w', encoding='utf-8') as f:
            json.dump({'subscription_key': 'A' * 32, 'endpoint': 'https://x.example', 'location': 'italynorth'}, f)
        self.assertEqual(JTApp.azure_key_problem(self.app), '')
        with open(self.paths.azure, 'w', encoding='utf-8') as f:
            json.dump({'subscription_key': 'INSERISCI-QUI-LA-CHIAVE-AZURE', 'endpoint': 'https://x.example',
                       'location': 'italynorth'}, f)
        self.assertIn('placeholder', JTApp.azure_key_problem(self.app))
        with self.assertRaises(RuntimeError):
            JTApp.make_translator(self.app)                           # nemmeno il traduttore si crea senza chiave


class ClosingTests(UiCase):
    def watch_destroy(self):
        patcher = patch.object(self.root, 'destroy', wraps=quiet_destroy(self.root))
        mock = patcher.start()
        self.addCleanup(patcher.stop)
        return mock

    def test_closing_when_idle_asks_nothing_and_closes_the_connection_and_the_window(self):
        self.step2()
        destroy = self.watch_destroy()
        with patch.object(JTApp, 'confirm', return_value=False) as confirm:
            self.app.on_closing()
        confirm.assert_not_called()                  # niente in corso: si chiude subito, senza domande
        self.assertTrue(self.fake_db.conns[0].closed)
        destroy.assert_called_once()
        with self.assertRaises(tk.TclError):
            self.root.winfo_exists()

    def previewed(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        screen.preview_button.invoke()
        self.assertIsNotNone(screen.preview)
        return screen

    def test_closing_with_an_unwritten_preview_asks_and_staying_keeps_everything(self):
        screen = self.previewed()
        destroy = self.watch_destroy()
        with patch.object(JTApp, 'confirm', return_value=False) as confirm:
            self.app.on_closing()
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.args[0], 'Discard the preview and quit?')
        self.assertEqual(confirm.call_args.args[2:], ('Discard and quit', 'Keep the preview'))
        self.assertIn('charged', confirm.call_args.args[1])
        destroy.assert_not_called()
        self.assertTrue(self.db.connected)
        self.assertIsNotNone(screen.preview)                     # l'anteprima e' ancora li'

    def test_closing_with_an_unwritten_preview_and_confirming_quits(self):
        self.previewed()
        destroy = self.watch_destroy()
        with patch.object(JTApp, 'confirm', return_value=True):
            self.app.on_closing()
        destroy.assert_called_once()
        self.assertTrue(self.fake_db.conns[0].closed)

    def test_no_question_once_the_preview_is_written_or_discarded(self):
        screen = self.previewed()
        screen.write_button.invoke()
        with patch.object(JTApp, 'confirm', return_value=False) as confirm, patch.object(JTApp, 'finish_close') as finish:
            self.app.on_closing()
        confirm.assert_not_called()
        finish.assert_called_once()
        screen = self.reload_preview_screen()
        screen.discard_button.invoke()
        with patch.object(JTApp, 'confirm', return_value=False) as confirm, patch.object(JTApp, 'finish_close') as finish:
            self.app.on_closing()
        confirm.assert_not_called()
        finish.assert_called_once()

    def reload_preview_screen(self):
        self.fake_db.missing['FW_STRINGS'] = 2
        screen = self.app.screen
        screen.load()
        screen.preview_button.invoke()
        self.assertIsNotNone(screen.preview)
        return screen

    def test_the_connection_screen_has_no_preview_to_ask_about(self):
        self.app.show_connection()
        with patch.object(JTApp, 'confirm', return_value=False) as confirm, patch.object(JTApp, 'finish_close') as finish:
            self.app.on_closing()
        confirm.assert_not_called()
        finish.assert_called_once()

    def test_error_in_close_does_not_prevent_quitting(self):
        self.fake_db.close_error = True
        self.step2()
        destroy = self.watch_destroy()
        with patch.object(JTApp, 'confirm', return_value=True):
            self.app.on_closing()
        destroy.assert_called_once()
        self.assertFalse(self.db.connected)

    def test_quit_without_connection_works(self):
        destroy = self.watch_destroy()
        with patch.object(JTApp, 'confirm', return_value=True):
            self.app.on_closing()
        destroy.assert_called_once()

    def test_the_window_close_button_is_wired_to_on_closing(self):
        script = self.root.protocol('WM_DELETE_WINDOW')
        self.assertTrue(script)
        with patch.object(JTApp, 'finish_close') as finish:
            self.root.tk.eval(script)                # la X o "Chiudi" dal pannello di Windows: da fermo chiude
        finish.assert_called_once()

    def test_shutdown_closes_the_connection_only(self):
        self.step2()
        self.app.shutdown()
        self.assertTrue(self.fake_db.conns[0].closed)
        self.assertTrue(self.root.winfo_exists())
        self.app.shutdown()                         # ripetibile

    # ---- dialogo reale (quello che si apre solo durante una traduzione)

    def ask_quit(self):
        return self.app.confirm('Stop the translation and quit?', 'Rows already written stay in the database.',
                                'Stop and quit', 'Keep translating')

    def test_real_dialog_has_the_same_title_as_the_main_window(self):
        self.step2()

        def look(dialog, seen):
            seen['title'] = dialog.top.title()
            dialog.cancel_button.invoke()

        _, seen = self.drive_dialog(self.ask_quit, look)
        self.assertEqual(seen['title'], self.root.title())
        self.assertEqual(seen['title'], f'{APP_TITLE} v{VERSION}')            # la versione cambia a ogni rilascio

    def test_real_dialog_buttons_are_labelled_stop_and_quit_and_keep_translating(self):
        self.step2()

        def look(dialog, seen):
            seen['ok'] = str(dialog.ok_button.cget('text'))
            seen['cancel'] = str(dialog.cancel_button.cget('text'))
            seen['texts'] = all_texts(dialog.top)
            dialog.cancel_button.invoke()

        with patch.object(JTApp, 'finish_close') as finish:
            _, seen = self.drive_dialog(self.ask_quit, look)
        self.assertEqual((seen['ok'], seen['cancel']), ('Stop and quit', 'Keep translating'))
        for text in ('Stop the translation and quit?', 'Rows already written stay in the database.'):
            self.assertIn(text, seen['texts'])
        finish.assert_not_called()
        self.assertTrue(self.db.connected)
        self.assertTrue(self.root.winfo_exists())

    def test_real_dialog_quit_button_confirms(self):
        self.step2()
        value, _ = self.drive_dialog(self.ask_quit, lambda d, s: d.ok_button.invoke())
        self.assertIs(value, True)

    def test_real_dialog_escape_means_cancel(self):
        self.step2()
        with patch.object(JTApp, 'finish_close') as finish:
            self.drive_dialog(self.ask_quit, lambda d, s: fire(d.top, '<Escape>'))
        finish.assert_not_called()
        self.assertTrue(self.db.connected)

    def test_real_dialog_window_x_means_cancel(self):
        self.step2()

        def press_x(dialog, seen):
            dialog.top.tk.eval(dialog.top.protocol('WM_DELETE_WINDOW'))

        with patch.object(JTApp, 'finish_close') as finish:
            self.drive_dialog(self.ask_quit, press_x)
        finish.assert_not_called()
        self.assertTrue(self.db.connected)

    def test_real_dialog_enter_activates_the_focused_button_and_by_default_that_is_stay(self):
        self.step2()
        with patch.object(JTApp, 'finish_close') as finish:             # Invio senza toccare il focus: "Stay"
            value, _ = self.drive_dialog(self.ask_quit, lambda d, s: fire(d.top, '<Return>'))
        finish.assert_not_called()
        self.assertTrue(self.db.connected)

    def test_real_dialog_enter_on_the_focused_quit_button_confirms(self):
        self.step2()

        def enter_on_quit(dialog, seen):
            with patch.object(dialog.top, 'focus_get', return_value=dialog.ok_button):
                fire(dialog.top, '<Return>')

        value, _ = self.drive_dialog(self.ask_quit, enter_on_quit)
        self.assertIs(value, True)

    def test_real_dialog_enter_on_the_focused_stay_button_cancels(self):
        self.step2()

        def enter_on_stay(dialog, seen):
            with patch.object(dialog.top, 'focus_get', return_value=dialog.cancel_button):
                fire(dialog.top, '<Return>')

        with patch.object(JTApp, 'finish_close') as finish:
            self.drive_dialog(self.ask_quit, enter_on_stay)
        finish.assert_not_called()

    def test_real_dialog_enter_with_the_focus_somewhere_else_means_cancel(self):
        def enter_elsewhere(dialog, seen):
            with patch.object(dialog.top, 'focus_get', return_value=dialog.top):
                fire(dialog.top, '<Return>')

        value, _ = self.drive_dialog(lambda: self.app.confirm('Q?', '', 'Yes', 'No'), enter_elsewhere)
        self.assertIs(value, False)

    def test_real_dialog_initial_focus_is_on_the_cancel_button(self):
        calls = []
        original = tk.Misc.focus_set
        patcher = patch.object(tk.Misc, 'focus_set', lambda w: (calls.append(w), original(w))[1])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.drive_dialog(lambda: self.app.confirm('Q?', '', 'Yes', 'No'), lambda d, s: d.cancel_button.invoke())
        self.assertIs(calls[-1], self.app.last_dialog.cancel_button)

    def test_only_one_dialog_at_a_time(self):
        def ask_again(dialog, seen):
            with patch.object(dialog.top, 'lift', wraps=dialog.top.lift) as lift:
                seen['second'] = self.app.confirm('Other?', '', 'Yes', 'No')
            seen['lifted'] = lift.called
            seen['windows'] = len([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)])
            seen['same_dialog'] = self.app.last_dialog is dialog
            dialog.ok_button.invoke()

        value, seen = self.drive_dialog(lambda: self.app.confirm('First?', '', 'Yes', 'No'), ask_again)
        self.assertIs(value, True)                     # la prima domanda resta quella valida
        self.assertIs(seen['second'], False)
        self.assertTrue(seen['lifted'])
        self.assertEqual(seen['windows'], 1)
        self.assertTrue(seen['same_dialog'])
        result, _ = self.drive_dialog(lambda: self.app.confirm('Again?', '', 'Yes', 'No'),
                                      lambda d, s: d.ok_button.invoke())
        self.assertIs(result, True)                    # chiusa la prima, se ne puo' aprire un'altra

    def test_closing_the_window_twice_does_not_open_two_dialogs(self):
        self.step2()

        def press_x_again(dialog, seen):
            self.ask_quit()
            seen['windows'] = len([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)])
            dialog.ok_button.invoke()

        _, seen = self.drive_dialog(self.ask_quit, press_x_again)
        self.assertEqual(seen['windows'], 1)

    def test_a_dialog_is_not_a_nested_pause_of_the_application(self):
        ticks = []
        self.root.after(1, lambda: ticks.append(1))
        self.drive_dialog(lambda: self.app.confirm('Q?', '', 'Yes', 'No'),
                          lambda d, s: (self.root.update(), s.update(ticks=len(ticks)), d.cancel_button.invoke()))
        self.assertEqual(ticks, [1])

    def test_real_dialog_is_compact_and_has_no_image(self):
        def measure(dialog, seen):
            dialog.top.update_idletasks()
            seen['size'] = (dialog.top.winfo_reqwidth(), dialog.top.winfo_reqheight())
            images = []
            for w in all_widgets(dialog.top):
                with contextlib.suppress(tk.TclError):
                    if str(w.cget('image')):
                        images.append(w)
            seen['images'] = images
            seen['canvases'] = [w for w in all_widgets(dialog.top) if isinstance(w, tk.Canvas)]
            seen['resizable'] = tuple(dialog.top.resizable())
            dialog.cancel_button.invoke()

        _, seen = self.drive_dialog(lambda: self.app.confirm('Quit JT?', 'The database connection will be closed.',
                                                             'Quit', 'Stay'), measure)
        width, height = seen['size']
        self.assertLess(width, 360)
        self.assertLess(height, 170)
        self.assertEqual(seen['images'], [])
        self.assertEqual(seen['canvases'], [])
        self.assertEqual(seen['resizable'], (False, False))

    def test_confirm_returns_the_choice_and_removes_the_dialog(self):
        for button, expected in (('ok_button', True), ('cancel_button', False)):
            with self.subTest(button=button):
                result, _ = self.drive_dialog(lambda: self.app.confirm('Q?', 'detail', 'Yes', 'No'),
                                              lambda d, s: getattr(d, button).invoke())
                self.assertIs(result, expected)
                self.assertEqual([w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)], [])

    def test_dialog_is_transient_to_the_main_window(self):
        def look(dialog, seen):
            seen['master'] = str(dialog.top.wm_transient())
            dialog.cancel_button.invoke()

        _, seen = self.drive_dialog(lambda: self.app.confirm('Q?'), look)
        self.assertEqual(seen['master'], str(self.root))

    def test_real_dialog_during_a_translation_has_its_own_labels_and_sets_closing_on_confirm(self):
        self.step2()
        self.app.translating = True

        def look(dialog, seen):
            seen['labels'] = (str(dialog.ok_button.cget('text')), str(dialog.cancel_button.cget('text')))
            seen['texts'] = all_texts(dialog.top)
            dialog.ok_button.invoke()

        with patch.object(JTApp, 'finish_close') as finish:
            _, seen = self.drive_dialog(self.app.on_closing, look)
        self.assertEqual(seen['labels'], ('Stop and quit', 'Keep translating'))
        self.assertIn('Stop the translation and quit?', seen['texts'])
        self.assertTrue(self.app.closing)
        self.assertTrue(self.runner._stop.is_set())                   # il motore e' stato fermato
        self.assertEqual(self.screen.status.state, 'warn')
        self.assertEqual(self.screen.status.message.cget('text'), 'Closing: finishing the current row first...')
        self.assertEqual(state(self.screen.translate_button), 'disabled')
        finish.assert_not_called()                  # si chiude quando il lavoro ha finito la riga corrente
        self.app.translating = False

    def test_real_dialog_during_a_translation_can_be_cancelled(self):
        self.step2()
        self.app.translating = True
        with patch.object(JTApp, 'finish_close') as finish:
            self.drive_dialog(self.app.on_closing, lambda d, s: d.cancel_button.invoke())
        self.assertFalse(self.app.closing)
        self.assertFalse(self.runner._stop.is_set())
        finish.assert_not_called()
        self.app.translating = False

    def test_if_the_run_finished_while_the_dialog_was_open_confirming_just_closes_the_app(self):
        self.step2()
        self.app.translating = True

        def finished_meanwhile(dialog, seen):
            self.app.translating = False
            dialog.ok_button.invoke()

        with patch.object(JTApp, 'finish_close') as finish:
            self.drive_dialog(self.app.on_closing, finished_meanwhile)
        finish.assert_called_once()
        self.assertFalse(self.app.closing)
        self.assertFalse(self.runner._stop.is_set())

    # ---- chiusura durante la traduzione

    def test_quit_during_a_translation_stops_after_the_current_row_and_closes_everything(self):
        self.use_azure()
        screen = self.loaded_strings(5)
        destroy = self.watch_destroy()
        calls = []

        banner = []

        def user_closes_the_window(progress):
            calls.append(progress.done)
            if len(calls) == 1:
                self.app.on_closing()
                banner.append((screen.status.state, screen.status.message.cget('text')))

        self.hook_progress(screen, user_closes_the_window)
        with patch.object(JTApp, 'confirm', return_value=True):
            screen.translate()
        self.assertTrue(self.app.closing)
        self.assertEqual(banner, [('warn', 'Closing: finishing the current row first...')])
        self.assertEqual(len(self.fake_db.inserts()), 1)      # la riga in corso e' completata, le altre no
        self.assertEqual(calls, [1])
        self.assertTrue(self.fake_db.conns[0].closed)
        destroy.assert_called_once()
        self.assertFalse(self.app.translating)
        self.assertEqual(len(self.logs('inserts')), 1)        # il lavoro fatto resta nel log

    def test_cancelling_the_quit_during_a_translation_keeps_the_run_going(self):
        self.use_azure()
        screen = self.loaded_strings(5)
        destroy = self.watch_destroy()
        asked = []

        def user_hesitates(progress):
            if not asked:
                asked.append(True)
                self.app.on_closing()

        self.hook_progress(screen, user_hesitates)
        with patch.object(JTApp, 'confirm', return_value=False) as confirm:
            screen.translate()
        confirm.assert_called_once()
        self.assertFalse(self.app.closing)
        self.assertEqual(len(self.fake_db.inserts()), 5)
        destroy.assert_not_called()
        self.assertTrue(self.db.connected)
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 5 inserted.'))


# ===================================================================== finestra

class WindowTests(UiCase):
    def test_title_and_version(self):
        self.assertTrue(self.root.title().startswith('JTools'))

    def test_window_is_resizable_both_ways(self):
        self.assertEqual(tuple(self.root.resizable()), (True, True))
        self.step2()
        self.assertEqual(tuple(self.root.resizable()), (True, True))

    def test_window_does_not_stay_on_top_of_other_applications(self):
        self.assertFalse(int(self.root.attributes('-topmost')))
        self.step2()
        self.assertFalse(int(self.root.attributes('-topmost')))

    def needed_height(self):
        return min(self.app.stepper.winfo_reqheight() + self.screen.winfo_reqheight()
                   + self.app.infobar.winfo_reqheight(), self.root.winfo_screenheight() - 100)

    def test_minsize_equals_the_needed_size_and_width_is_at_least_the_minimum(self):
        for show in (self.app.show_connection, self.app.show_translation):
            with self.subTest(step=show.__name__):
                show()
                self.root.update_idletasks()
                width, height = self.root.minsize()
                self.assertGreaterEqual(width, WINDOW_MIN_WIDTH)
                self.assertEqual(width, max(WINDOW_MIN_WIDTH, self.screen.winfo_reqwidth(), self.app.stepper.winfo_reqwidth()))
                self.assertEqual(height, self.needed_height())

    def test_height_fits_the_content_on_both_steps(self):
        with patch.object(self.root, 'winfo_screenheight', return_value=2000):
            for show in (self.app.show_connection, self.app.show_translation):
                with self.subTest(step=show.__name__):
                    w, h, x, y = self.geometry_for(show)
                    self.assertEqual(h, self.app.stepper.winfo_reqheight() + self.screen.winfo_reqheight()
                                     + self.app.infobar.winfo_reqheight())
                    self.assertGreaterEqual(w, 460)
                    self.assertGreaterEqual(w, self.app.stepper.winfo_reqwidth())

    def test_the_infobar_is_part_of_the_height(self):
        with patch.object(self.root, 'winfo_screenheight', return_value=2000):
            h_without = self.geometry_for(self.app.show_connection)[1]
            self.assertGreater(self.app.infobar.winfo_reqheight(), 0)
            with patch.object(self.app.infobar, 'winfo_reqheight', return_value=self.app.infobar.winfo_reqheight() + 40):
                h_with = self.geometry_for(self.app.show_connection)[1]
        self.assertEqual(h_with - h_without, 40)

    def test_minsize_uses_the_scaled_minimum_width(self):
        scale.set_factor(1.5)
        self.app.fit_window()
        self.assertGreaterEqual(self.root.minsize()[0], 690)             # px(460) a 150%
        scale.set_factor(1.0)
        self.app.fit_window()
        self.assertLess(self.root.minsize()[0], 690)

    def test_window_is_never_topmost_even_after_fitting(self):
        self.app.fit_window()
        self.assertFalse(int(self.root.attributes('-topmost')))

    def test_step_two_is_taller_than_step_one(self):
        with patch.object(self.root, 'winfo_screenheight', return_value=2000):
            h1 = self.geometry_for(self.app.show_connection)[1]
            h2 = self.geometry_for(self.app.show_translation)[1]
        self.assertGreater(h2, h1)

    def test_window_is_centered_the_first_time_and_keeps_its_position_after(self):
        with patch.object(self.root, 'winfo_screenheight', return_value=2000), \
                patch.object(self.root, 'winfo_screenwidth', return_value=1600):
            self.app._placed = False
            w, h, x, y = self.geometry_for(self.app.show_connection)
            self.assertEqual(x, (1600 - w) // 2)
            with patch.object(self.root, 'winfo_x', return_value=33), patch.object(self.root, 'winfo_y', return_value=44):
                w2, h2, x2, y2 = self.geometry_for(self.app.show_translation)
            self.assertEqual((x2, y2), (33, 44))

    def test_window_never_goes_below_the_screen_edge(self):
        for show in (self.app.show_connection, self.app.show_translation):
            with self.subTest(step=show.__name__):
                w, h, x, y = self.geometry_for(show, screen_height=700)
                self.assertLessEqual(h, 700 - 100)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(y + h, 700)

    def test_window_already_placed_low_moves_up_to_stay_inside_the_screen(self):
        w, h, x, y = self.geometry_for(self.app.show_translation, screen_height=900, window_y=600)
        self.assertLessEqual(y + h, 900 - 80)
        self.assertGreaterEqual(y, 0)

    def test_window_keeps_a_user_made_larger_width(self):
        self.app._placed = True
        with patch.object(self.root, 'winfo_width', return_value=900):
            w, h, x, y = self.geometry_for(self.app.show_translation)
        self.assertEqual(w, 900)

    def test_texts_wrap_with_the_screen_width_through_the_tracker(self):
        screen = self.step2()
        screen.refresh_missing()
        self.app._on_screen_resize(SimpleNamespace(widget=screen, width=700))
        self.assertEqual(wraplength(screen.status.message), 700 - 95)
        self.assertEqual(wraplength(screen.label_missing), 700 - 80)
        self.app._on_screen_resize(SimpleNamespace(widget=screen, width=100))      # mai sotto il minimo leggibile
        for widget in (screen.status.message, screen.label_missing):
            self.assertEqual(wraplength(widget), 180)

    def test_step_one_texts_wrap_too(self):
        screen = self.screen
        soon = next(w for w in all_widgets(screen) if 'text' in w.keys()
                    and str(w.cget('text')).startswith('Microsoft SQL Server'))
        self.app._on_screen_resize(SimpleNamespace(widget=screen, width=640))
        self.assertEqual(wraplength(screen.status.message), 640 - 95)
        self.assertEqual(wraplength(soon), 640 - 150)
        self.app._on_screen_resize(SimpleNamespace(widget=screen, width=50))
        self.assertEqual(wraplength(screen.status.message), 180)

    def test_resize_of_a_child_widget_does_not_change_the_wrap(self):
        screen = self.screen
        before = wraplength(screen.status.message)
        self.app._on_screen_resize(SimpleNamespace(widget=screen.status, width=900))
        self.assertEqual(wraplength(screen.status.message), before)

    def test_screens_listen_to_configure_events(self):
        self.assertTrue(self.screen.bind('<Configure>'))
        self.assertTrue(self.step2().bind('<Configure>'))

    def test_wrap_tracker_floor_and_both_kinds_of_widget(self):
        tracker = WrapTracker()
        label = tk.Label(self.root)
        bar = StatusBar(self.root, 'x')
        tracker.add(label, 50)
        tracker.add(bar, 95)
        tracker.update(500)
        self.assertEqual(wraplength(label), 450)
        self.assertEqual(wraplength(bar.message), 405)
        tracker.update(10)
        self.assertEqual((wraplength(label), wraplength(bar.message)), (180, 180))         # px(180) a 100%
        scale.set_factor(1.5)
        tracker.update(10)
        self.assertEqual((wraplength(label), wraplength(bar.message)), (270, 270))
        tracker.update(1000)                                       # anche il margine segue la scala
        self.assertEqual(wraplength(label), 1000 - scale.px(50))
        self.assertEqual(wraplength(bar.message), 1000 - scale.px(95))

    def test_showing_a_step_replaces_the_previous_screen(self):
        first = self.screen
        self.app.show_translation()
        self.assertFalse(first.winfo_exists())
        self.assertEqual(len([w for w in self.app.area.inner.winfo_children() if isinstance(w, (ConnectionScreen,
                                                                                                 TranslationScreen))]), 1)

    def test_coming_soon_notices_on_both_screens(self):
        step1 = ' '.join(all_texts(self.screen))
        self.assertIn('COMING SOON', step1)
        self.assertIn('Microsoft SQL Server (MSS)', step1)
        step2 = ' '.join(all_texts(self.step2()))
        self.assertNotIn('COMING SOON', step2)      # i livelli CK e CC nascosti non si annunciano: serve spazio alla finestra

    def test_hidden_button_blends_with_the_background(self):
        screen = self.step2()
        button = screen.hidden_button
        self.assertEqual(str(button.cget('bg')), PALETTE['bg'])
        self.assertEqual(str(button.cget('text')), '')
        self.assertEqual(int(str(button.cget('bd'))), 0)
        self.assertEqual(int(str(button.cget('highlightthickness'))), 0)
        info = button.place_info()
        self.assertEqual((info['width'], info['height']), ('6', '6'))

    def panels(self):
        return [w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)]

    def close_panel(self, window):
        window.tk.eval(window.protocol('WM_DELETE_WINDOW'))

    def test_hidden_button_opens_the_secret_panel_and_the_panel_closes_cleanly(self):
        screen = self.step2()
        screen.hidden_button.invoke()                       # non blocca: ritorna subito
        panels = self.panels()
        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0].title(), 'Secret Creator Panel')
        self.assertEqual(state(screen.hidden_button), 'disabled')
        label = panels[0].winfo_children()[0]
        self.assertTrue('\n'.join(MESSAGE).startswith(str(label.cget('text'))))      # si sta scrivendo
        self.close_panel(panels[0])
        self.assertEqual(state(screen.hidden_button), 'normal')
        self.assertEqual(self.panels(), [])

    def test_secret_panel_types_the_whole_message_without_blocking(self):
        button = tk.Button(self.root)
        window = open_secret_panel(self.app, button, interval_ms=0)
        self.assertIsInstance(window, tk.Toplevel)
        self.assertEqual(state(button), 'disabled')
        label = window.winfo_children()[0]
        self.assertEqual(str(label.cget('text')), '')                  # ritorna prima di aver scritto
        self.assertTrue(self.wait_for(lambda: str(label.cget('text')) == '\n'.join(MESSAGE), timeout=5))
        self.assertEqual(state(button), 'disabled')                    # resta disattivato finche' e' aperto
        self.close_panel(window)
        self.assertEqual(state(button), 'normal')

    def test_secret_panel_keeps_the_event_loop_running_while_typing(self):
        button = tk.Button(self.root)
        window = open_secret_panel(self.app, button, interval_ms=5)
        ticks = []
        self.root.after(1, lambda: ticks.append(1))
        label = window.winfo_children()[0]
        self.assertTrue(self.wait_for(lambda: len(str(label.cget('text'))) >= 10, timeout=5))
        self.assertTrue(ticks)
        self.close_panel(window)

    def test_secret_panel_survives_being_closed_while_writing(self):
        button = tk.Button(self.root)
        window = open_secret_panel(self.app, button, interval_ms=2)
        label = window.winfo_children()[0]
        self.assertTrue(self.wait_for(lambda: len(str(label.cget('text'))) >= 5, timeout=5))
        self.close_panel(window)                                       # a meta' scrittura
        self.assertEqual(state(button), 'normal')
        self.wait_for(lambda: False, timeout=0.15)                     # lascia scattare i `after` rimasti
        self.assertEqual(self.panels(), [])
        self.assertEqual(state(button), 'normal')

    def test_secret_panel_closed_after_the_screen_changed_does_not_fail(self):
        screen = self.step2()
        screen.hidden_button.invoke()
        self.app.show_connection()                                     # il pulsante non esiste piu'
        self.close_panel(self.panels()[0])
        self.assertEqual(self.panels(), [])

    def test_hidden_button_stays_disabled_while_the_panel_is_open(self):
        screen = self.step2()
        screen.hidden_button.invoke()
        screen.hidden_button.invoke()                                  # disattivato: non apre un secondo pannello
        self.assertEqual(len(self.panels()), 1)
        self.close_panel(self.panels()[0])

    def test_secret_panel_cannot_be_opened_while_translating_and_reenabled_afterwards(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        seen = []
        self.hook_progress(screen, lambda p: (screen.hidden_button.invoke(), seen.append(len(self.panels()))))
        screen.translate()
        self.assertEqual(seen, [0, 0])
        self.assertEqual(state(screen.hidden_button), 'normal')


# ===================================================================== widget e tema

class WidgetTests(UiCase):
    def test_status_bar_states_and_colours(self):
        bar = StatusBar(self.root, 'Try')
        self.assertEqual(bar.state, 'info')
        self.assertEqual(bar.message.cget('text'), 'Try')
        for name, (bg, accent, fg, icon, glyph) in StatusBar.STYLES.items():
            with self.subTest(state=name):
                bar.show(name, f'text {name}')
                self.assertEqual(bar.state, name)
                self.assertEqual(bar.message.cget('text'), f'text {name}')
                self.assertEqual(str(bar.cget('bg')), bg)
                self.assertEqual(str(bar.bar.cget('bg')), accent)
                self.assertEqual(str(bar.icon.cget('fg')), icon)
                self.assertEqual(str(bar.icon.cget('text')), glyph)
                self.assertEqual(str(bar.message.cget('fg')), fg)

    def test_status_bar_has_distinct_colours_per_state(self):
        self.assertEqual(len({v[1] for v in StatusBar.STYLES.values()}), 4)
        self.assertEqual(StatusBar.STYLES['ok'][1], PALETTE['ok'])
        self.assertEqual(StatusBar.STYLES['error'][1], PALETTE['error'])
        self.assertEqual(StatusBar.STYLES['warn'][1], PALETTE['warn'])

    def test_status_bar_config_with_a_colour_changes_the_state_like_a_label(self):
        bar = StatusBar(self.root, 'Try')
        for colour, expected in ((PALETTE['ok'], 'ok'), (PALETTE['error'], 'error'), (PALETTE['warn'], 'warn'),
                                 ('green', 'ok'), ('red', 'error'), ('orange', 'warn'), ('unknown', 'info')):
            with self.subTest(colour=colour):
                bar.config(text='msg', fg=colour)
                self.assertEqual(bar.state, expected)
                self.assertEqual(bar.message.cget('text'), 'msg')
        bar.config(text='only text')                       # senza colore lo stato non cambia
        self.assertEqual(bar.state, 'info')
        bar.configure(text='alias', fg='red')
        self.assertEqual((bar.state, bar.message.cget('text')), ('error', 'alias'))

    def test_status_bar_config_passes_other_options_to_the_frame(self):
        bar = StatusBar(self.root, 'Try')
        bar.config(width=77)
        self.assertEqual(int(str(bar.cget('width'))), 77)

    def test_status_bar_set_wrap(self):
        bar = StatusBar(self.root, 'Try')
        bar.set_wrap(250)
        self.assertEqual(wraplength(bar.message), 250)

    def test_status_bar_has_no_fixed_two_line_height(self):
        bar = StatusBar(self.root, 'Try')
        self.assertEqual(int(str(bar.message.cget('height'))), 0)

    def test_status_bar_has_a_minimum_row_height_and_grows_with_the_text(self):
        bar = StatusBar(self.root, 'Try')
        bar.pack(fill='x')
        self.assertEqual(bar.grid_rowconfigure(0)['minsize'], scale.px(38))
        self.root.update_idletasks()
        short = bar.winfo_reqheight()
        self.assertGreaterEqual(short, scale.px(38))
        self.assertLess(short, scale.px(54))                  # una riga non deve occupare piu' di cosi'
        bar.set_wrap(150)
        bar.show('info', 'a long message that needs several lines ' * 6)
        self.root.update_idletasks()
        self.assertGreater(bar.winfo_reqheight(), short)
        bar.show('info', 'Try')
        self.root.update_idletasks()
        self.assertEqual(bar.winfo_reqheight(), short)

    def test_status_bar_minimum_height_follows_the_scale(self):
        scale.set_factor(2.0)
        bar = StatusBar(self.root, 'Try')
        self.assertEqual(bar.grid_rowconfigure(0)['minsize'], 76)

    def test_status_bar_calls_on_change_when_the_text_changes(self):
        changes = []
        bar = StatusBar(self.root, 'Try', on_change=lambda: changes.append(1))
        self.root.update()
        self.assertEqual(changes, [])                       # nessuna chiamata alla costruzione
        bar.show('ok', 'one')
        self.assertEqual(changes, [])                       # differita: a riposo
        self.root.update()
        self.assertEqual(changes, [1])
        bar.config(text='two')
        self.root.update()
        self.assertEqual(changes, [1, 1])
        bar.config(fg=PALETTE['ok'])                        # solo il colore: il testo non cambia
        bar.set_wrap(300)
        self.root.update()
        self.assertEqual(changes, [1, 1])

    def test_status_bar_without_on_change_is_fine(self):
        bar = StatusBar(self.root, 'Try')
        bar.show('ok', 'x')
        self.root.update()

    def test_both_screens_pass_fit_window_to_their_status_bar(self):
        self.assertEqual(self.screen.status.on_change, self.app.fit_window)
        self.assertEqual(self.step2().status.on_change, self.app.fit_window)

    def test_a_longer_banner_makes_the_window_adapt(self):
        screen = self.step2()
        self.root.update()
        with patch.object(self.root, 'geometry') as geometry:
            screen.status.show('error', 'Something happened ' * 30)
            self.root.update()
        self.assertTrue(geometry.called)

    def test_tooltip_opens_once_is_themed_and_hides(self):
        label = tk.Label(self.root, text='x')
        label.pack()
        for content in (KEYS_HINT, lambda: {'title': 'T', 'intro': 'I', 'rows': [('a', 'b')], 'footer': 'F'}):
            with self.subTest(content=type(content).__name__):
                tip = ToolTip(label, content)
                tip.show()
                self.assertIsNotNone(tip.tip)
                self.assertEqual(tip.tip.winfo_children()[0].cget('bg'), PALETTE['border'])
                first = tip.tip
                tip.show()
                self.assertIs(tip.tip, first)
                self.assertEqual(len([w for w in label.winfo_children() if isinstance(w, tk.Toplevel)]), 1)
                tip.hide()
                self.assertIsNone(tip.tip)
                tip.hide()                      # ripetibile
                self.assertEqual([w for w in label.winfo_children() if isinstance(w, tk.Toplevel)], [])

    def test_tooltip_shows_the_given_texts(self):
        label = tk.Label(self.root, text='x')
        tip = ToolTip(label, KEYS_HINT)
        tip.show()
        texts = ' | '.join(all_texts(tip.tip))
        self.assertIn(KEYS_HINT['title'], texts)
        self.assertIn(KEYS_HINT['footer'], texts)
        self.assertIn('FW_OBJ_DESCRS', texts)
        tip.hide()

    def test_tooltip_stays_on_screen_even_near_the_right_and_bottom_edges(self):
        label = tk.Label(self.root, text='x')
        label.pack()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        with patch.object(label, 'winfo_rootx', return_value=screen_w - 3), \
                patch.object(label, 'winfo_rooty', return_value=screen_h - 3):
            tip = ToolTip(label, KEYS_HINT)
            tip.show()
            tip.tip.update_idletasks()
            width, height = tip.tip.winfo_reqwidth(), tip.tip.winfo_reqheight()
            x, y = (int(v) for v in tip.tip.wm_geometry().split('+')[1:3])
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + width, screen_w)
            self.assertLessEqual(y + height, screen_h)
            tip.hide()

    def tip_geometry(self, rooty, work_bottom, content=KEYS_HINT, height=20):
        """(x, y, larghezza, altezza) del suggerimento per un widget a `rooty`, con l'area utile che finisce a `work_bottom`."""
        label = tk.Label(self.root, text='x')
        label.pack()
        with patch.object(label, 'winfo_rooty', return_value=rooty), \
                patch.object(label, 'winfo_height', return_value=height), \
                patch('jt.ui.widgets.work_area_bottom', return_value=work_bottom):
            tip = ToolTip(label, content)
            tip.show()
            tip.tip.update_idletasks()
            x, y = (int(v) for v in tip.tip.wm_geometry().split('+')[1:3])
            size = tip.tip.winfo_reqwidth(), tip.tip.winfo_reqheight()
            tip.hide()
        return x, y, size[0], size[1]

    def test_tooltip_is_never_hidden_under_the_taskbar(self):
        _x, _y, _w, h = self.tip_geometry(100, 10000)
        for rooty in (300, 400, 500):
            work_bottom = 600                                  # lo schermo e' piu' alto: sotto ci sono la barra e il resto
            x, y, w, h = self.tip_geometry(rooty, work_bottom)
            self.assertLessEqual(y + h, work_bottom, rooty)
            self.assertGreaterEqual(y, 0, rooty)

    def test_tooltip_opens_below_when_there_is_room_and_above_when_there_is_not(self):
        _x, _y, _w, h = self.tip_geometry(100, 10000)
        _x, below, _w, _h = self.tip_geometry(100, 10000)
        self.assertEqual(below, 100 + 20 + scale.px(6))
        _x, above, _w, _h = self.tip_geometry(400, 400 + h)
        self.assertEqual(above, 400 - h - scale.px(6))

    def test_a_tooltip_taller_than_the_room_on_either_side_stays_fully_in_view(self):
        _x, _y, _w, h = self.tip_geometry(100, 10000)
        x, y, w, h = self.tip_geometry(h // 2, h + 30)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(y + h, h + 30)

    def test_the_work_area_is_never_taller_than_the_screen(self):
        from jt.ui.widgets import work_area_bottom
        label = tk.Label(self.root, text='x')
        label.pack()
        bottom = work_area_bottom(label)
        self.assertGreater(bottom, 0)
        self.assertLessEqual(bottom, self.root.winfo_screenheight())

    def test_without_the_windows_call_the_work_area_is_the_whole_screen(self):
        from jt.ui.widgets import work_area_bottom
        label = tk.Label(self.root, text='x')
        label.pack()
        with patch.dict(sys.modules, {'ctypes': SimpleNamespace()}):                  # niente windll, niente wintypes
            self.assertEqual(work_area_bottom(label), self.root.winfo_screenheight())

    def test_combobox_dropdown_uses_the_app_style(self):
        combo = ttk.Combobox(self.root, values=['a', 'b'], state='readonly')
        combo.pack()
        self.root.update_idletasks()
        popdown = self.root.tk.eval('ttk::combobox::PopdownWindow ' + str(combo))
        listbox = popdown + '.f.l'
        get = lambda option: str(self.root.tk.call(listbox, 'cget', '-' + option))
        self.assertEqual(get('selectbackground'), PALETTE['accent'])
        self.assertEqual(get('selectforeground'), 'white')
        self.assertIn(FONT, get('font'))

    def test_button_styles_exist_and_small_ones_inherit_the_colours(self):
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup('Primary.TButton', 'background'), PALETTE['accent'])
        self.assertEqual(style.lookup('Primary.TButton', 'foreground'), 'white')
        self.assertEqual(style.lookup('Secondary.TButton', 'background'), 'white')
        self.assertEqual(style.lookup('Secondary.TButton', 'foreground'), PALETTE['accent'])
        for kind in ('Primary', 'Secondary'):
            small = f'Small.{kind}.TButton'
            self.assertEqual(str(style.lookup(small, 'padding')), '14 3', small)
            self.assertEqual(style.lookup(small, 'background'), style.lookup(f'{kind}.TButton', 'background'))
            self.assertEqual(style.lookup(small, 'foreground'), style.lookup(f'{kind}.TButton', 'foreground'))
        for name in ('Card.TLabelframe', 'Muted.TLabel', 'Dialog.TLabel'):
            self.assertTrue(style.lookup(name, 'background') or style.lookup(name, 'foreground')
                            or style.lookup(name, 'font'), name)

    def test_disabled_buttons_are_visibly_different(self):
        style = ttk.Style(self.root)
        for name in ('Primary.TButton', 'Secondary.TButton'):
            normal = style.lookup(name, 'background')
            disabled = style.lookup(name, 'background', ['disabled'])
            self.assertNotEqual(normal, disabled, name)

    def test_window_background_follows_the_palette(self):
        self.assertEqual(str(self.root.cget('bg')), PALETTE['bg'])
        self.assertEqual(str(self.app.stepper.cget('bg')), PALETTE['bg'])
        self.assertEqual(ttk.Style(self.root).theme_use(), 'clam')

    def test_stepper_is_a_stepper_with_two_named_steps(self):
        self.assertIsInstance(self.app.stepper, Stepper)
        self.assertEqual([n.cget('text') for n in self.app.stepper._names], ['Connection', 'Translation'])


# ===================================================================== traduzione in un thread vero

class SlowTranslator:
    """Traduttore finto che a ogni chiamata aspetta il via del test: l'ordine degli eventi e' deciso dal test,
    non dal caso. `entered` conta le chiamate iniziate, `gate` le lascia finire."""

    def __init__(self):
        self.entered = threading.Semaphore(0)
        self.gate = threading.Semaphore(0)
        self.calls = 0
        self.threads = set()

    def translate(self, text, lan_in, lan_out):
        self.calls += 1
        self.threads.add(threading.current_thread().name)
        self.entered.release()
        if not self.gate.acquire(timeout=5):
            raise RuntimeError('the test never released this row')
        return 'T:' + text

    def release(self, count=1):
        for _ in range(count):
            self.gate.release()


class BackgroundTranslateTests(UiCase):
    """Con il BackgroundRunner vero: l'interfaccia resta viva mentre il thread lavora e legge gli avanzamenti a intervalli.
    Ogni attesa ha un limite di 5 secondi; il thread viene fermato e atteso a fine test."""

    def make_runner(self):
        return BackgroundRunner()

    def setUp(self):
        super().setUp()
        self.translator = SlowTranslator()
        patcher = patch.object(JTApp, 'make_translator', lambda _self: self.translator)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._stop_worker)               # registrato dopo la chiusura della finestra: parte prima

    def _stop_worker(self):
        self.translator.release(1000)
        self.runner.stop()
        thread = self.runner._thread
        if thread is not None:
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'il thread di traduzione non si e\' fermato')

    def pump(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.005)

    def wait_row_started(self, timeout=5.0):
        """Aspetta (con l'interfaccia viva) che il thread inizi a tradurre una riga."""
        end = time.time() + timeout
        while time.time() < end:
            if self.translator.entered.acquire(blocking=False):
                return True
            self.root.update()
            time.sleep(0.005)
        return False

    def alive(self):
        try:
            return bool(self.root.winfo_exists())
        except tk.TclError:
            return False

    def test_the_ui_keeps_running_while_the_thread_works_and_progress_arrives_by_polling(self):
        screen = self.loaded_strings(3)
        ticks = []

        def tick():
            ticks.append(1)
            self.root.after(5, tick)

        screen.translate()                               # ritorna subito: il lavoro e' in un thread
        self.assertTrue(self.app.translating and screen.running)
        self.assertTrue(self.runner.running)
        self.assertEqual(self.fake_db.inserts(), [])
        self.assertTrue(self.wait_row_started())          # il thread e' dentro la prima riga, bloccato
        tick()
        self.pump(0.3)
        self.assertGreater(len(ticks), 5)                 # il ciclo degli eventi non si e' fermato
        self.assertEqual(screen.label_bar.cget('text'), 'Waiting to start')    # ancora nessun avanzamento
        self.assertEqual(str(screen.translate_button.cget('text')), 'Stop')

        self.translator.release()                          # prima riga finita: l'avanzamento arriva col polling
        self.assertTrue(self.wait_for(lambda: screen.label_bar.cget('text').startswith('Processed 1/3'), timeout=5))
        self.assertEqual(screen.label_bar.cget('text'), f'Processed 1/3 {SEP} Inserted 1 {SEP} Errors 0')
        self.assertEqual(float(str(screen.progress.cget('value'))), 1.0)
        self.assertTrue(self.app.translating)             # il lavoro non e' finito
        self.assertEqual(screen.status.message.cget('text'), 'Translating... you can press Stop at any time.')
        self.assertEqual(state(screen.load_button), 'disabled')

        self.translator.release(10)
        self.assertTrue(self.wait_for(lambda: not self.app.translating, timeout=5))
        self.assertEqual(self.translator.threads, {'jt-worker'})        # mai nel thread dell'interfaccia
        self.assertEqual(len(self.fake_db.inserts()), 3)
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'ok')
        self.assertTrue(text.startswith('Done: 3 inserted. Log: Logs\\JT_inserts_log_'), text)
        self.assertEqual(screen.label_bar.cget('text'), f'Processed 3/3 {SEP} Inserted 3 {SEP} Errors 0')
        self.assertEqual((str(screen.translate_button.cget('text')), state(screen.translate_button)),
                         ('Translate', 'disabled'))
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertTrue(self.app.stepper.link_enabled)

    def test_stop_ends_the_run_after_the_current_row(self):
        screen = self.loaded_strings(5)
        screen.translate()
        self.assertTrue(self.wait_row_started())          # il thread e' dentro la riga 1
        screen.translate_button.invoke()                  # il pulsante e' Stop
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertEqual(screen.status.state, 'warn')
        self.assertEqual(screen.status.message.cget('text'), 'Stopping after the current row...')
        self.assertTrue(self.app.translating)             # la riga in corso non e' ancora finita
        self.translator.release(10)
        self.assertTrue(self.wait_for(lambda: not self.app.translating, timeout=5))
        self.assertEqual(self.translator.calls, 1)
        self.assertEqual(len(self.fake_db.inserts()), 1)
        text = screen.status.message.cget('text')
        self.assertEqual(screen.status.state, 'warn')
        self.assertTrue(text.startswith('Stopped: 1 inserted. Log: Logs\\JT_inserts_log_'), text)
        self.assertEqual((str(screen.translate_button.cget('text')), str(screen.translate_button.cget('style')),
                          state(screen.translate_button)), ('Translate', PRIMARY, 'disabled'))
        self.assertIsNone(screen.selection)
        self.assertEqual(state(screen.load_button), 'normal')

    def test_a_second_translate_while_running_is_ignored(self):
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertTrue(self.wait_row_started())
        screen.translate()                                # niente nuovo thread, niente eccezione
        screen.load()
        self.translator.release(10)
        self.assertTrue(self.wait_for(lambda: not self.app.translating, timeout=5))
        self.assertEqual(self.translator.calls, 2)
        self.assertEqual(len(self.fake_db.inserts()), 2)

    def test_an_error_in_the_thread_comes_back_to_the_interface(self):
        screen = self.loaded_strings(2)
        with patch.object(self.app.service, 'run', side_effect=RuntimeError('boom')):
            screen.translate()
            self.assertTrue(self.wait_for(lambda: not self.app.translating, timeout=5))
        self.assertEqual(screen.status.state, 'error')
        self.assertEqual(screen.status.message.cget('text'), 'The run stopped because of an error: boom')
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertEqual(str(screen.translate_button.cget('text')), 'Translate')

    def test_closing_during_the_run_stops_after_the_row_and_closes_once_the_thread_is_done(self):
        screen = self.loaded_strings(5)
        destroy = patch.object(self.root, 'destroy', wraps=quiet_destroy(self.root))
        destroy_mock = destroy.start()
        self.addCleanup(destroy.stop)
        screen.translate()
        self.assertTrue(self.wait_row_started())
        with patch.object(JTApp, 'confirm', return_value=True) as confirm:
            self.app.on_closing()
        confirm.assert_called_once()
        self.assertEqual(confirm.call_args.args[0], 'Stop the translation and quit?')
        self.assertTrue(self.app.closing)
        self.assertEqual(screen.status.message.cget('text'), 'Closing: finishing the current row first...')
        self.assertEqual(state(screen.translate_button), 'disabled')
        self.assertTrue(self.alive())                     # la riga in corso non e' finita: la finestra resta
        destroy_mock.assert_not_called()
        self.assertTrue(self.db.connected)
        self.translator.release(10)
        self.assertTrue(self.wait_for(lambda: not self.alive(), timeout=5))
        destroy_mock.assert_called_once()
        self.assertFalse(self.db.connected)
        self.assertTrue(self.fake_db.conns[0].closed)
        self.assertEqual(self.translator.calls, 1)
        self.assertEqual(len(self.fake_db.inserts()), 1)
        self.assertEqual(len(self.logs('inserts')), 1)    # il lavoro fatto resta nel log

    def test_cancelling_the_quit_during_the_run_keeps_it_going(self):
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertTrue(self.wait_row_started())
        with patch.object(JTApp, 'confirm', return_value=False):
            self.app.on_closing()
        self.assertFalse(self.app.closing)
        self.translator.release(10)
        self.assertTrue(self.wait_for(lambda: not self.app.translating, timeout=5))
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 2 inserted.'))
        self.assertTrue(self.alive())

    def test_the_run_is_not_paused_while_the_quit_dialog_is_open(self):
        screen = self.loaded_strings(3)
        screen.translate()
        self.assertTrue(self.wait_row_started())

        def let_the_run_go_on(dialog, seen):
            self.translator.release()
            seen['advanced'] = self.wait_for(lambda: screen.label_bar.cget('text').startswith('Processed 1/3'),
                                             timeout=5)
            seen['dialog_open'] = bool(dialog.top.winfo_exists())
            dialog.cancel_button.invoke()

        with patch.object(JTApp, 'finish_close') as finish:
            _, seen = self.drive_dialog(self.app.on_closing, let_the_run_go_on)
        self.assertTrue(seen['advanced'] and seen['dialog_open'])     # l'avanzamento e' arrivato a dialogo aperto
        finish.assert_not_called()
        self.assertFalse(self.app.closing)
        self.assertTrue(self.app.translating)

    def test_the_run_finishing_while_the_dialog_is_open_then_confirming_just_closes(self):
        screen = self.loaded_strings(2)
        screen.translate()
        self.assertTrue(self.wait_row_started())

        def finish_then_confirm(dialog, seen):
            self.translator.release(10)
            seen['finished'] = self.wait_for(lambda: not self.app.translating, timeout=5)
            dialog.ok_button.invoke()

        with patch.object(JTApp, 'finish_close') as finish:
            _, seen = self.drive_dialog(self.app.on_closing, finish_then_confirm)
        self.assertTrue(seen['finished'])
        finish.assert_called_once()
        self.assertFalse(self.app.closing)
        self.assertEqual(len(self.fake_db.inserts()), 2)


# ===================================================================== scala dello schermo

class ScaleUnitTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(scale.set_factor, 1.0)
        scale.set_factor(1.0)

    def test_px_scales_and_rounds(self):
        self.assertEqual(scale.px(10), 10)
        scale.set_factor(1.5)
        self.assertEqual(scale.px(10), 15)
        self.assertEqual(scale.px(7), 10)                 # 10,5 -> arrotondamento di Python
        scale.set_factor(2.0)
        self.assertEqual((scale.px(0), scale.px(54), scale.px(460)), (0, 108, 920))
        self.assertIsInstance(scale.px(3), int)

    def test_pad_returns_a_scaled_tuple(self):
        self.assertEqual(scale.pad(10), (10,))
        scale.set_factor(1.5)
        self.assertEqual(scale.pad(10), (15,))
        self.assertEqual(scale.pad(18, 14, 18, 12), (27, 21, 27, 18))
        self.assertEqual(scale.pad(), ())

    def test_set_factor_never_goes_below_one_and_accepts_numbers_as_text(self):
        for value, expected in ((0.5, 1.0), (0, 1.0), (-2, 1.0), (1.25, 1.25), ('1.5', 1.5), (2, 2.0)):
            with self.subTest(value=value):
                scale.set_factor(value)
                self.assertEqual(scale.factor(), expected)
        self.assertEqual(scale.factor(), 2.0)

    def test_init_reads_the_dpi_of_the_screen_the_window_is_on(self):
        for dpi, expected in ((96.0, 1.0), (120.0, 1.25), (144.0, 1.5), (192.0, 2.0), (72.0, 1.0)):
            with self.subTest(dpi=dpi):
                scale.init(SimpleNamespace(winfo_fpixels=lambda unit, dpi=dpi: dpi))
                self.assertAlmostEqual(scale.factor(), expected)

    def test_init_with_a_real_window_follows_tk_scaling(self):
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'nessun display: {e}')
        self.addCleanup(root.destroy)
        root.withdraw()
        previous = root.tk.call('tk', 'scaling')
        self.addCleanup(root.tk.call, 'tk', 'scaling', previous)  # vale per tutto il processo: va rimessa
        root.tk.call('tk', 'scaling', 1.5 * 96 / 72)
        scale.init(root)
        self.assertAlmostEqual(scale.factor(), 1.5, places=2)


class ScaleWindowTests(UiCase):
    """L'interfaccia a 100%, 125%, 150% e 200%: i font crescono con 'tk scaling', le misure con scale.px."""

    FACTORS = (1.0, 1.25, 1.5, 2.0)

    def build(self, factor, scale_factor=True):
        root = tk.Tk()
        root.withdraw()
        root.report_callback_exception = lambda *exc: self.callback_errors.append(exc)
        db = Database(driver=FakeDriver(FakeDB()))
        self.addCleanup(self._destroy, root, db)
        previous = root.tk.call('tk', 'scaling')
        self.addCleanup(root.tk.call, 'tk', 'scaling', previous)  # vale per tutto il processo: va rimessa (prima di distruggere)
        root.tk.call('tk', 'scaling', factor * 96 / 72)           # i font scalano prima che nasca l'applicazione
        original = root.geometry
        root._geometries = []

        def geometry(spec=None):                                  # una finestra nascosta non dice la misura data
            if spec:
                root._geometries.append(spec)
            return original(spec) if spec else original()

        root.geometry = geometry
        app = JTApp(root, self.paths, db, runner=InlineRunner(), scale_factor=factor if scale_factor else None,
                    tools=strings_only())
        return root, app, db

    @staticmethod
    def _destroy(root, db):
        db.close()
        with contextlib.suppress(tk.TclError):
            root.update_idletasks()
            for call_id in root.tk.splitlist(root.tk.call('after', 'info')):
                root.tk.call('after', 'cancel', call_id)
        with contextlib.suppress(tk.TclError):
            root.destroy()

    @staticmethod
    def window_geometry(root):
        """(larghezza, altezza, x, y) dell'ultima geometria richiesta dall'applicazione."""
        match = re.match(r'(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$', root._geometries[-1])
        return tuple(int(v) for v in match.groups())

    def window_width(self, root):
        return self.window_geometry(root)[0]

    def steps(self, root, app, db):
        yield 'connection', app.screen
        app.connect(dict(FAKE_CONNECTION))
        app.show_translation()
        yield 'translation', app.screen

    def test_the_application_uses_the_given_factor(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                self.assertEqual(scale.factor(), factor)
                self.assertGreaterEqual(root.minsize()[0], round(460 * factor))

    def test_without_a_given_factor_it_reads_it_from_the_screen(self):
        root, app, db = self.build(1.5, scale_factor=False)
        self.assertAlmostEqual(scale.factor(), 1.5, places=2)

    def test_the_stepper_always_fits_in_the_window_width(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                for name, screen in self.steps(root, app, db):
                    root.update_idletasks()
                    self.assertLessEqual(app.stepper.winfo_reqwidth(), self.window_width(root), name)
                    self.assertGreaterEqual(self.window_width(root), round(460 * factor), name)
                    self.assertLessEqual(self.window_width(root), root.winfo_screenwidth(), name)

    def test_wrapped_texts_never_exceed_the_screen_width(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                screen_width = root.winfo_screenwidth()
                for name, screen in self.steps(root, app, db):
                    screen.status.show('error', 'A rather long message to be wrapped over several lines. ' * 5)
                    app._on_screen_resize(SimpleNamespace(widget=screen, width=self.window_width(root)))
                    root.update_idletasks()
                    checked = 0
                    for widget in all_widgets(screen):
                        try:
                            wrap = int(str(widget.cget('wraplength')))
                        except (tk.TclError, ValueError):
                            continue
                        if wrap:
                            checked += 1
                            self.assertLessEqual(wrap, screen_width, (name, str(widget)))
                            self.assertLessEqual(widget.winfo_reqwidth(), screen_width, (name, str(widget)))
                    self.assertGreaterEqual(checked, 2, name)             # banner e testo "coming soon" almeno

    def test_the_banner_text_fits_the_window_width(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                for name, screen in self.steps(root, app, db):
                    screen.status.show('error', 'A rather long message to be wrapped over several lines. ' * 5)
                    app._on_screen_resize(SimpleNamespace(widget=screen, width=self.window_width(root)))
                    root.update_idletasks()
                    self.assertLessEqual(screen.status.winfo_reqwidth(), self.window_width(root), name)

    def test_the_infobar_fits_in_the_window_width(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                for name, screen in self.steps(root, app, db):
                    root.update_idletasks()
                    self.assertLessEqual(app.infobar.winfo_reqwidth(), self.window_width(root), name)

    def test_the_window_stays_inside_the_screen_at_every_scale(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
                for name, screen in self.steps(root, app, db):
                    root.update_idletasks()
                    w, h, x, y = self.window_geometry(root)
                    self.assertGreaterEqual((x, y), (0, 0), name)
                    self.assertLessEqual(h, screen_h - scale.px(100), name)
                    self.assertLessEqual(y + h, screen_h, name)

    def test_the_status_bar_minimum_height_follows_the_scale(self):
        for factor in self.FACTORS:
            with self.subTest(factor=factor):
                root, app, db = self.build(factor)
                self.assertEqual(app.screen.status.grid_rowconfigure(0)['minsize'], round(38 * factor))


# ===================================================================== testi, contrasto, tema, DPI

class TextsTests(unittest.TestCase):
    def test_fmt_count(self):
        for value, expected in ((None, '?'), (0, '0'), (7, '7'), (999, '999'), (1000, '1.000'), (1234, '1.234'),
                                (1234567, '1.234.567'), (-1500, '-1.500')):
            with self.subTest(value=value):
                self.assertEqual(fmt_count(value), expected)

    def test_shorten_leaves_short_texts_alone_and_collapses_whitespace(self):
        self.assertEqual(shorten('hello'), 'hello')
        self.assertEqual(shorten('a   b\t\nc'), 'a b c')
        self.assertEqual(shorten('x' * 110), 'x' * 110)
        self.assertEqual(shorten(''), '')
        self.assertEqual(shorten(12345), '12345')

    def test_shorten_cuts_at_a_word_boundary_and_adds_dots(self):
        text = 'alpha beta gamma delta'
        self.assertEqual(shorten(text, 12), 'alpha...')             # 'alpha beta...' sarebbe 13: oltre il limite
        self.assertEqual(shorten(text, 13), 'alpha beta...')           # entra esattamente
        self.assertEqual(shorten(text, 17), 'alpha beta...')           # 'alpha beta gamma...' sarebbe 19
        self.assertEqual(shorten('alpha beta gamma delta', 16), 'alpha beta...')
        long = 'word ' * 60
        cut = shorten(long)
        self.assertTrue(cut.endswith('word...'))
        self.assertNotIn('wor...', cut)

    def test_shorten_drops_punctuation_before_the_dots(self):
        self.assertEqual(shorten('first, second; third', 13), 'first...')
        self.assertEqual(shorten('alpha: beta gamma', 8), 'alpha...')

    def test_shorten_cuts_hard_when_there_is_no_space(self):
        self.assertEqual(shorten('X' * 500), 'X' * 107 + '...')
        self.assertEqual(shorten('abcdefghij', 4), 'a...')

    def test_shorten_result_never_exceeds_the_limit_dots_included(self):
        for text in ('X' * 500, 'word ' * 100, 'a, ' * 100):
            for limit in (5, 20, 110):
                with self.subTest(limit=limit, text=text[:6]):
                    self.assertLessEqual(len(shorten(text, limit)), limit)

    def test_reason_is_the_first_line_shortened(self):
        self.assertEqual(reason(RuntimeError('ORA-01017: bad login\nstack line 2\nstack line 3')), 'ORA-01017: bad login')
        self.assertEqual(reason(RuntimeError('\n\n  padded  \nsecond')), 'padded')
        self.assertEqual(reason('plain text'), 'plain text')
        self.assertEqual(reason(RuntimeError('')), '')
        self.assertEqual(reason(RuntimeError('   \n  ')), '')
        long = reason(RuntimeError('error ' * 60 + '\nsecond'))
        self.assertTrue(long.endswith('error...'))
        self.assertLessEqual(len(long), 110)
        self.assertEqual(reason(RuntimeError('one two three four'), 9), 'one...')   # 'one two...' (10) supererebbe il limite


class DpiTests(unittest.TestCase):
    def test_enable_dpi_awareness_returns_a_bool_and_never_raises(self):
        result = enable_dpi_awareness()
        self.assertIsInstance(result, bool)
        self.assertIsInstance(enable_dpi_awareness(), bool)           # ripetibile

    def run_with_fake_ctypes(self, fake):
        with patch.dict(sys.modules, {'ctypes': fake}):
            return enable_dpi_awareness()

    def test_it_reports_success_with_the_modern_api(self):
        fake = SimpleNamespace(windll=SimpleNamespace(shcore=MagicMock(), user32=MagicMock()))
        self.assertIs(self.run_with_fake_ctypes(fake), True)
        fake.windll.shcore.SetProcessDpiAwareness.assert_called_once_with(1)
        fake.windll.user32.SetProcessDPIAware.assert_not_called()

    def test_it_falls_back_to_the_old_api(self):
        shcore = MagicMock()
        shcore.SetProcessDpiAwareness.side_effect = OSError('no shcore')
        fake = SimpleNamespace(windll=SimpleNamespace(shcore=shcore, user32=MagicMock()))
        self.assertIs(self.run_with_fake_ctypes(fake), True)
        fake.windll.user32.SetProcessDPIAware.assert_called_once()

    def test_it_returns_false_when_no_api_exists(self):
        self.assertIs(self.run_with_fake_ctypes(SimpleNamespace()), False)
        shcore, user32 = MagicMock(), MagicMock()
        shcore.SetProcessDpiAwareness.side_effect = OSError('no')
        user32.SetProcessDPIAware.side_effect = OSError('no')
        self.assertIs(self.run_with_fake_ctypes(SimpleNamespace(windll=SimpleNamespace(shcore=shcore, user32=user32))),
                      False)


class ThemeTests(UiCase):
    """Contrasto WCAG delle coppie colore principali: testo >= 4,5:1; bordi dei campi >= 3:1."""

    def ratio(self, foreground, background):
        return contrast(foreground, background, self.root)

    def assertContrast(self, foreground, background, minimum=4.5):
        value = self.ratio(foreground, background)
        self.assertGreaterEqual(value, minimum, f'{foreground} su {background}: {value:.2f}:1')

    def test_the_contrast_function_is_correct(self):
        self.assertAlmostEqual(self.ratio('#000000', '#ffffff'), 21.0, places=1)
        self.assertAlmostEqual(self.ratio('#ffffff', '#ffffff'), 1.0, places=2)
        self.assertAlmostEqual(self.ratio('#777777', '#ffffff'), 4.48, places=1)       # valore noto della tabella WCAG
        self.assertEqual(self.ratio('red', 'white'), self.ratio('white', 'red'))

    def test_muted_text_on_the_backgrounds(self):
        self.assertContrast(PALETTE['muted'], PALETTE['bg'])
        self.assertContrast(PALETTE['muted'], 'white')
        self.assertContrast(PALETTE['muted'], StatusBar.STYLES['info'][0])
        self.assertContrast(PALETTE['muted'], PALETTE['disabled_soft_bg'])
        self.assertEqual(PALETTE['muted'], '#5b6370')

    def test_main_text_and_accents_on_the_backgrounds(self):
        self.assertContrast(PALETTE['text'], PALETTE['bg'])
        self.assertContrast(PALETTE['text'], 'white')
        for name in ('accent', 'ok', 'warn', 'error'):
            with self.subTest(colour=name):
                self.assertContrast(PALETTE[name], PALETTE['bg'])
                self.assertContrast(PALETTE[name], 'white')

    def test_banner_texts_on_their_backgrounds(self):
        for name, (bg, bar, fg, icon, glyph) in StatusBar.STYLES.items():
            with self.subTest(state=name):
                self.assertContrast(fg, bg)
                self.assertContrast(icon, bg, 3.0)                # il simbolo e' un elemento grafico

    def test_banner_texts_are_the_ones_on_screen(self):
        bar = StatusBar(self.root, 'x')
        for name, (bg, _bar, fg, _icon, _glyph) in StatusBar.STYLES.items():
            bar.show(name, 'text')
            self.assertContrast(str(bar.message.cget('fg')), str(bar.message.cget('bg')))

    def test_buttons_text_on_their_backgrounds(self):
        style = ttk.Style(self.root)
        self.assertContrast('white', PALETTE['accent'])
        self.assertContrast('white', PALETTE['accent_dark'])
        self.assertContrast(PALETTE['accent'], 'white')                                   # Secondary
        self.assertContrast(PALETTE['error'], 'white')                                    # Danger
        for name in ('Primary.TButton', 'Secondary.TButton', 'Danger.TButton'):
            with self.subTest(button=name):
                self.assertContrast(style.lookup(name, 'foreground', ['disabled']),
                                    style.lookup(name, 'background', ['disabled']))

    def test_disabled_primary_button_text_is_readable(self):
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup('Primary.TButton', 'foreground', ['disabled']), PALETTE['disabled_fg'])
        self.assertEqual(style.lookup('Primary.TButton', 'background', ['disabled']), PALETTE['disabled_bg'])
        self.assertContrast(PALETTE['disabled_fg'], PALETTE['disabled_bg'])

    def test_field_borders_are_visible_on_white(self):
        self.assertContrast(PALETTE['field_border'], 'white', 3.0)
        style = ttk.Style(self.root)
        for name in ('TEntry', 'TCombobox'):
            self.assertEqual(style.lookup(name, 'bordercolor'), PALETTE['field_border'])

    def test_disabled_fields_look_disabled(self):
        style = ttk.Style(self.root)
        for name in ('TEntry', 'TCombobox'):
            with self.subTest(widget=name):
                self.assertIn(('disabled', PALETTE['disabled_soft_bg']), style.map(name, 'fieldbackground'))
                self.assertEqual(style.lookup(name, 'fieldbackground', ['disabled']), PALETTE['disabled_soft_bg'])
                self.assertNotEqual(style.lookup(name, 'fieldbackground', ['disabled']),
                                    style.lookup(name, 'fieldbackground', []))
                self.assertContrast(style.lookup(name, 'foreground', ['disabled']), PALETTE['disabled_soft_bg'])

    def test_a_readonly_combobox_stays_white_and_a_disabled_one_does_not(self):
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup('TCombobox', 'fieldbackground', ['readonly']), 'white')
        self.assertEqual(style.lookup('TCombobox', 'fieldbackground', ['disabled']), PALETTE['disabled_soft_bg'])
        combo = ttk.Combobox(self.root, values=['a'], state='readonly')
        combo.config(state='disabled')                       # come fa _lock(): lo stato e' solo "disabled"
        self.assertEqual(style.lookup('TCombobox', 'fieldbackground', combo.state()), PALETTE['disabled_soft_bg'])

    def test_the_danger_button_style_is_red_on_white(self):
        style = ttk.Style(self.root)
        self.assertEqual(style.lookup('Danger.TButton', 'foreground'), PALETTE['error'])
        self.assertEqual(style.lookup('Danger.TButton', 'background'), 'white')
        self.assertEqual(style.lookup('Danger.TButton', 'bordercolor'), PALETTE['error'])
        self.assertNotEqual(style.lookup('Danger.TButton', 'background', ['disabled']),
                            style.lookup('Danger.TButton', 'background'))

    def test_the_palette_has_the_documented_values(self):
        self.assertEqual(PALETTE['ok'], '#14703a')
        for name in ('bg', 'text', 'muted', 'accent', 'accent_dark', 'accent_soft', 'border', 'field_border', 'trough',
                     'disabled_bg', 'disabled_fg', 'disabled_soft_bg', 'ok', 'error', 'warn'):
            self.assertRegex(PALETTE[name], r'^#[0-9a-f]{6}$', name)


class AssetTests(unittest.TestCase):
    """I file veri di Graphics (nessun Tk)."""

    GRAPHICS = os.path.join(helpers.ROOT, 'Graphics')
    ICONS = os.path.join(GRAPHICS, 'icons')
    CHOICES = ['bubbles.ico', 'pixel_block.ico', 'pixel_cube.ico']

    def read_icon(self, name):
        with open(os.path.join(self.ICONS, name), 'rb') as f:
            return f.read()

    def test_the_logo_choices_are_available(self):
        self.assertEqual(sorted(os.listdir(self.ICONS)), self.CHOICES)

    def test_the_configured_logo_is_one_of_them(self):
        from jt import config
        self.assertIn(config.ICON_NAME + '.ico', self.CHOICES)
        self.assertEqual(helpers.Paths(helpers.ROOT).icon, os.path.join(self.ICONS, config.ICON_NAME + '.ico'))

    def test_every_logo_holds_all_the_expected_sizes(self):
        for name in self.CHOICES:
            with self.subTest(icon=name):
                data = self.read_icon(name)
                reserved, kind, count = struct.unpack('<HHH', data[:6])
                self.assertEqual((reserved, kind), (0, 1))
                sizes = {(data[6 + 16 * i] or 256) for i in range(count)}
                self.assertTrue({16, 20, 24, 32, 40, 48, 64, 128, 256} <= sizes, sorted(sizes))

    def test_every_icon_entry_is_a_png_rendered_at_its_own_size(self):
        # ogni dimensione e' un'immagine a se' (non un ridimensionamento sfocato di un'altra)
        for name in self.CHOICES:
            data = self.read_icon(name)
            count = struct.unpack('<H', data[4:6])[0]
            for i in range(count):
                width, height, _c, _r, _planes, _bpp, length, offset = struct.unpack('<BBBBHHII', data[6 + 16 * i:22 + 16 * i])
                blob = data[offset:offset + length]
                with self.subTest(icon=name, entry=i):
                    self.assertEqual(blob[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>II', blob[16:24]), (width or 256, height or 256))

    def test_graphics_folder_holds_only_what_the_app_uses(self):
        needed = {'icons'}
        for number, state in Stepper.IMAGES:
            for suffix in ('', '_30', '_36', '_48'):
                needed.add(f'step_{number}_{state}{suffix}.png')
        self.assertEqual(set(os.listdir(self.GRAPHICS)), needed)

    def test_default_paths_point_to_these_files(self):
        self.assertTrue(os.path.isfile(helpers.Paths(helpers.ROOT).icon))


class LanguageOrderTests(UiCase):
    """Italiano e inglese in cima ai menu, poi tutte le altre in ordine alfabetico; da = italiano, a = inglese."""

    def names(self):
        from jt.catalog import Catalog
        return Catalog(self.paths).languages()

    def test_italian_and_english_come_first_then_the_rest_in_alphabetical_order(self):
        names = self.names()
        self.assertEqual(names[:2], ['Italian', 'English'])
        rest = names[2:]
        self.assertEqual(rest, sorted(rest, key=str.lower))
        self.assertNotIn('Italian', rest)
        self.assertNotIn('English', rest)

    def test_nothing_is_lost_or_duplicated(self):
        from jt.jsonstore import read_json
        names = self.names()
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), {item['language'] for item in read_json(self.paths.languages)})

    def test_a_catalog_without_the_pinned_languages_is_just_alphabetical(self):
        write_json(self.paths.languages, [{'language': 'Zulu', 'code': 'zu'}, {'language': 'Basque', 'code': 'eu'}])
        self.assertEqual(self.names(), ['Basque', 'Zulu'])

    def test_a_pinned_language_that_is_missing_is_skipped(self):
        write_json(self.paths.languages, [{'language': 'English', 'code': 'en'}, {'language': 'Basque', 'code': 'eu'},
                                          {'language': 'Arabic', 'code': 'ar'}])
        self.assertEqual(self.names(), ['English', 'Arabic', 'Basque'])

    def test_the_menus_use_this_order(self):
        screen = self.step2({})
        for combo in (screen.cmb_in, screen.cmb_out):
            self.assertEqual(list(combo.cget('values'))[:3], ['Italian', 'English', 'Albanian'])

    def test_without_a_saved_choice_it_is_italian_to_english(self):
        screen = self.step2({})
        self.assertEqual((screen.var_in.get(), screen.var_out.get()), ('Italian', 'English'))

    def test_a_saved_choice_wins_over_the_defaults(self):
        screen = self.step2({'linput': 'German', 'loutput': 'French', 'table': 'JFX: Strings'})
        self.assertEqual((screen.var_in.get(), screen.var_out.get()), ('German', 'French'))

    def test_a_saved_language_that_no_longer_exists_falls_back_to_the_defaults(self):
        screen = self.step2({'linput': 'Klingon', 'loutput': 'Elvish', 'table': 'JFX: Strings'})
        self.assertEqual((screen.var_in.get(), screen.var_out.get()), ('Italian', 'English'))


class TextWordingTests(unittest.TestCase):
    def test_rows_singular_and_plural(self):
        from jt.ui.texts import rows
        self.assertEqual([rows(n) for n in (0, 1, 2, 21053)], ['0 rows', '1 row', '2 rows', '21.053 rows'])

    def test_duration_in_words(self):
        from jt.ui.texts import describe_duration
        cases = ((0, 'less than a minute'), (0.6, 'less than a minute'), (59.9, 'less than a minute'),
                 (60, 'about 1 minute'), (89, 'about 1 minute'), (100, 'about 2 minutes'), (1000, 'about 17 minutes'),
                 (5399, 'about 90 minutes'), (5400, 'about 1.5 hours'), (7200, 'about 2.0 hours'))
        for seconds, expected in cases:
            with self.subTest(seconds=seconds):
                self.assertEqual(describe_duration(seconds), expected)


class ReviewFixesUiTests(UiCase):
    """Cose emerse dalla revisione del codice."""

    def test_a_log_folder_that_cannot_be_written_does_not_leave_the_screen_locked(self):
        self.use_azure()
        screen = self.loaded_strings(2)
        with patch('jt.ui.translation_screen.write_run_logs', side_effect=PermissionError('read-only')):
            screen.translate()
        self.assertFalse(screen.running)
        self.assertEqual(state(screen.entry_max), 'normal')
        self.assertEqual(state(screen.load_button), 'normal')
        self.assertTrue(screen.status.message.cget('text').startswith('Done: 2 inserted.'))

    def test_a_connection_file_that_cannot_be_written_does_not_undo_the_connection(self):
        with patch.object(self.app.settings, 'save_connection', side_effect=PermissionError('read-only')):
            self.screen.connect_button.invoke()
        self.assertTrue(self.db.connected)
        self.assertEqual(self.screen.status.state, 'ok')
        self.assertEqual(state(self.screen.next_button), 'normal')

    def test_a_pending_count_is_cancelled_when_the_translation_starts(self):
        screen = self.loaded_strings(1)
        screen._counting_job = screen.after(150, screen.refresh_missing)
        screen._begin_run(screen.selection)
        self.assertIsNone(screen._counting_job)

    def test_no_count_runs_while_the_translation_is_running(self):
        screen = self.loaded_strings(1)
        screen.running = True
        before = self.fake_db.count('COUNT')
        screen.refresh_missing()
        self.assertEqual(self.fake_db.count('COUNT'), before)

    def test_the_window_is_never_wider_than_the_screen(self):
        screen_w = self.root.winfo_screenwidth()
        self.app.screen.configure(width=screen_w * 3)
        self.app.fit_window()
        self.assertLessEqual(int(self.root.geometry().split('x')[0]), screen_w)

    def test_shutdown_waits_for_a_running_translation_before_closing_the_connection(self):
        events = []
        self.app.runner.stop = lambda: events.append('stop')
        self.app.runner.join = lambda timeout=None: events.append(('join', timeout))
        with patch.object(self.app.db, 'close', side_effect=lambda: events.append('close')):
            self.app.shutdown()
        self.assertEqual(events, ['stop', ('join', 10), 'close'])


class LogsFolderTests(UiCase):
    """L'utente deve poter trovare i log senza sapere dove sono."""

    def test_the_link_opens_the_logs_folder_and_creates_it_when_missing(self):
        screen = self.step2()
        self.assertFalse(os.path.exists(self.paths.logs))
        with patch('jt.ui.translation_screen.os.startfile', create=True) as startfile:
            fire(screen.link_logs, '<Button-1>')
        startfile.assert_called_once_with(self.paths.logs)
        self.assertTrue(os.path.isdir(self.paths.logs))

    def test_a_folder_that_cannot_be_opened_is_explained(self):
        screen = self.step2()
        with patch('jt.ui.translation_screen.os.startfile', create=True, side_effect=OSError('no explorer')):
            screen.open_logs()
        self.assertEqual(screen.status.state, 'error')
        self.assertIn(self.paths.logs, screen.status.message.cget('text'))

    def test_the_full_path_is_in_the_tooltip_text_of_the_link(self):
        screen = self.step2()
        self.assertEqual(screen.link_logs.cget('text'), 'Open the logs folder')


class DocuNodesInsertTests(unittest.TestCase):
    def test_the_insert_names_its_columns_so_the_table_may_have_any_number_of_them(self):
        for columns in (['NODEID', 'LANG', 'TEXT'], ['NODEID', 'LANG', 'TEXT', 'DESCR'], ['A', 'B', 'C', 'D', 'E']):
            bound = get_table('FW_DOCU_NODES_T').bind_columns(columns)
            sql, binds = bound.insert((7, 'it', 'ciao'), 'es', {'text': 'hola'})
            self.assertEqual(sql, f'INSERT INTO FW_DOCU_NODES_T ({columns[0]}, {columns[1]}, {columns[2]}) VALUES (:1, :2, :3)')
            self.assertEqual(binds, [7, 'es', 'hola'])


class GeometryRecorder:
    """Sostituisce root.geometry: ricorda ogni valore impostato e ritorna quello attuale se letto."""

    def __init__(self, current):
        self.current = current
        self.sets = []

    def __call__(self, value=None):
        if value is None:
            return self.current
        self.sets.append(value)
        self.current = value
        return ''


class StepTransitionTests(UiCase):
    """Passare da un passo all'altro (Next, New connection) senza scatti: la finestra cambia misura una volta sola,
    non si sposta, non resta mai vuota e non accumula schermate."""

    def setUp(self):
        super().setUp()
        self.screen.connect()
        self.root.update()
        self.recorder = GeometryRecorder(self.root.geometry())
        for name, value in (('geometry', self.recorder), ('winfo_x', lambda: int(self.recorder.current.split('+')[1])),
                            ('winfo_y', lambda: int(self.recorder.current.split('+')[2])),
                            ('winfo_width', lambda: int(self.recorder.current.split('x')[0]))):
            patcher = patch.object(self.root, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def settle(self, seconds=0.45):
        """Lascia girare l'interfaccia: tocca anche il conteggio che parte 150 ms dopo l'apertura del passo 2."""
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.02)

    @staticmethod
    def position(geometry):
        return geometry.split('+', 1)[1]

    def screens(self):
        return [w for w in self.app.area.inner.winfo_children() if isinstance(w, ttk.Frame)]

    def test_next_resizes_the_window_once_and_leaves_it_alone_afterwards(self):
        self.screen.next_button.invoke()
        self.settle()
        self.assertEqual(len(self.recorder.sets), 1, self.recorder.sets)

    def test_new_connection_resizes_the_window_once_and_leaves_it_alone_afterwards(self):
        self.screen.next_button.invoke()
        self.settle()
        self.recorder.sets.clear()
        fire(self.app.stepper.link, '<Button-1>')
        self.settle()
        self.assertEqual(len(self.recorder.sets), 1, self.recorder.sets)

    def test_the_counts_arriving_later_do_not_resize_the_window(self):
        self.fake_db.missing = {'FW_STRINGS': 21053, 'FW_FIELD_STRINGS': 13872}
        self.screen.next_button.invoke()
        self.root.update()
        after_opening = len(self.recorder.sets)
        self.settle()                                  # qui arriva il conteggio (dopo 150 ms)
        self.assertIn('Missing in', self.app.screen.label_missing.cget('text'))
        self.assertEqual(len(self.recorder.sets), after_opening, self.recorder.sets)

    def test_repeated_round_trips_never_move_the_window_or_pile_up_screens(self):
        origin = self.position(self.recorder.current)
        for _ in range(4):
            self.app.screen.connect() if self.app.stepper.step == 1 else None
            self.app.screen.next_button.invoke()
            self.settle(0.3)
            self.assertEqual(len(self.screens()), 1)
            fire(self.app.stepper.link, '<Button-1>')
            self.settle(0.1)
            self.assertEqual(len(self.screens()), 1)
            self.screen.connect()
        origin_x, origin_y = origin.split('+')
        for geometry in self.recorder.sets:
            _, x, y = geometry.split('+')
            self.assertEqual(x, origin_x, self.recorder.sets)                   # mai di lato
            self.assertLessEqual(int(y), int(origin_y), self.recorder.sets)     # al massimo piu' su, se non c'e' spazio sotto

    def test_the_size_goes_straight_to_the_final_one_without_an_in_between_size(self):
        before = self.recorder.current
        self.screen.next_button.invoke()
        self.settle()
        sizes = {geometry.split('+')[0] for geometry in self.recorder.sets}
        self.assertEqual(len(sizes), 1)
        self.assertNotEqual(before.split('+')[0], sizes.pop())      # ed e' davvero la misura nuova del passo 2

    def test_the_new_step_is_built_before_the_old_one_goes_away(self):
        seen = {}
        original = TranslationScreen.__init__

        def watch(screen, parent, app):
            seen['old_screen_still_there'] = app.screen is not None and bool(app.screen.winfo_exists())
            original(screen, parent, app)
        with patch.object(TranslationScreen, '__init__', watch):
            self.screen.next_button.invoke()
        self.assertTrue(seen['old_screen_still_there'])        # nessun momento con la finestra vuota
        self.assertIsInstance(self.app.screen, TranslationScreen)

    def test_fitting_twice_with_nothing_changed_does_not_touch_the_geometry(self):
        self.screen.next_button.invoke()
        self.settle()
        self.app.fit_window()                          # la prima puo' ancora correggere la misura
        self.recorder.sets.clear()
        self.app.fit_window()
        self.app.fit_window()
        self.assertEqual(self.recorder.sets, [])

    def test_the_stepper_and_the_database_bar_are_never_rebuilt(self):
        stepper, infobar = self.app.stepper, self.app.infobar
        self.screen.next_button.invoke()
        self.settle(0.2)
        fire(self.app.stepper.link, '<Button-1>')
        self.settle(0.2)
        self.assertIs(self.app.stepper, stepper)
        self.assertIs(self.app.infobar, infobar)
        self.assertTrue(stepper.winfo_exists() and infobar.winfo_exists())


@unittest.skipUnless(sys.platform == 'win32', 'le icone della finestra sono una cosa di Windows')
class WindowIconTests(unittest.TestCase):
    """La finestra deve avere DUE icone: piccola per la barra del titolo, grande per la barra delle applicazioni.
    Con il solo `wm iconbitmap` di Tk c'e' una sola immagine, ingrandita o ridotta da Windows (sfocata)."""

    WM_GETICON = 0x007F

    def setUp(self):
        import ctypes
        from ctypes import wintypes

        class IconInfo(ctypes.Structure):
            _fields_ = [('fIcon', wintypes.BOOL), ('xHotspot', wintypes.DWORD), ('yHotspot', wintypes.DWORD),
                        ('hbmMask', ctypes.c_void_p), ('hbmColor', ctypes.c_void_p)]

        class Bitmap(ctypes.Structure):
            _fields_ = [('bmType', wintypes.LONG), ('bmWidth', wintypes.LONG), ('bmHeight', wintypes.LONG),
                        ('bmWidthBytes', wintypes.LONG), ('bmPlanes', wintypes.WORD), ('bmBitsPixel', wintypes.WORD),
                        ('bmBits', ctypes.c_void_p)]

        self.ctypes, self.IconInfo, self.Bitmap = ctypes, IconInfo, Bitmap
        self.user32, self.gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
        self.user32.SendMessageW.restype = ctypes.c_void_p
        self.user32.SendMessageW.argtypes = [ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p]
        self.user32.GetParent.restype = ctypes.c_void_p
        self.user32.GetParent.argtypes = [ctypes.c_void_p]
        self.user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(IconInfo)]
        self.gdi32.GetObjectW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        try:
            self.root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f'nessun display: {e}')
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.icon = helpers.Paths(helpers.ROOT).icon

    def icon_width(self, window, kind):
        """Larghezza in pixel dell'icona (0 piccola, 1 grande) che Windows ha per la finestra; 0 se non ne ha."""
        self.root.update_idletasks()
        hwnd = self.user32.GetParent(window.winfo_id()) or window.winfo_id()
        handle = self.user32.SendMessageW(hwnd, self.WM_GETICON, kind, 0)
        if not handle:
            return 0
        info = self.IconInfo()
        self.user32.GetIconInfo(handle, self.ctypes.byref(info))
        bitmap = self.Bitmap()
        self.gdi32.GetObjectW(info.hbmColor, self.ctypes.sizeof(self.Bitmap), self.ctypes.byref(bitmap))
        return bitmap.bmWidth

    def test_small_and_big_icons_have_the_sizes_the_system_asks_for(self):
        from jt.ui.winicon import set_window_icons
        small, big = self.user32.GetSystemMetrics(49), self.user32.GetSystemMetrics(11)
        self.assertTrue(set_window_icons(self.root, self.icon))
        self.assertEqual(self.icon_width(self.root, 0), small)
        self.assertEqual(self.icon_width(self.root, 1), big)
        self.assertGreater(big, small)

    def test_a_missing_file_does_not_raise(self):
        from jt.ui.winicon import set_window_icons
        self.assertFalse(set_window_icons(self.root, os.path.join(helpers.ROOT, 'Graphics', 'icons', 'non_esiste.ico')))

    def test_the_application_window_gets_both_icons(self):
        app = JTApp(self.root, helpers.Paths(helpers.ROOT), Database(driver=FakeDriver(FakeDB())),
                    runner=InlineRunner(), scale_factor=1.0)
        self.assertEqual(self.icon_width(self.root, 0), self.user32.GetSystemMetrics(49))
        self.assertEqual(self.icon_width(self.root, 1), self.user32.GetSystemMetrics(11))
        self.assertIsNotNone(app)

    def test_the_confirm_dialog_gets_both_icons_too(self):
        app = JTApp(self.root, helpers.Paths(helpers.ROOT), Database(driver=FakeDriver(FakeDB())),
                    runner=InlineRunner(), scale_factor=1.0)
        sizes = {}

        def look():
            top = app.last_dialog.top
            sizes['small'], sizes['big'] = self.icon_width(top, 0), self.icon_width(top, 1)
            app.last_dialog.cancel_button.invoke()
        self.root.after(50, look)
        app.confirm('Question?', '', 'Yes', 'No')
        self.assertEqual(sizes['small'], self.user32.GetSystemMetrics(49))
        self.assertEqual(sizes['big'], self.user32.GetSystemMetrics(11))


if __name__ == '__main__':
    unittest.main(verbosity=2)
