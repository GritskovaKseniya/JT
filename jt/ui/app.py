"""La finestra principale: passi, dimensioni, chiusura. Qui si collegano interfaccia e logica."""
import tkinter as tk

from ..azure import AzureTranslator
from ..catalog import Catalog
from ..config import APP_TITLE, VERSION, WINDOW_MIN_WIDTH, Paths
from ..db import Database
from ..glossary import Glossary
from ..runner import BackgroundRunner
from ..service import TranslationService
from ..settings import Settings
from . import scale
from .connection_screen import ConnectionScreen
from .dialogs import ConfirmDialog
from .scale import px
from .theme import setup_style
from .translation_screen import TranslationScreen
from .winicon import set_window_icons
from .. import environments
from .widgets import InfoBar, ScrollArea, Stepper

BOTTOM_MARGIN = 80        # spazio lasciato per la barra delle applicazioni


class JTApp:
    def __init__(self, root, paths=None, db=None, runner=None, scale_factor=None):
        self.root = root
        self.paths = paths or Paths.default()
        self.catalog = Catalog(self.paths)
        self.settings = Settings(self.paths)
        self.db = db or Database()
        self.service = TranslationService(self.db)
        self.runner = runner or BackgroundRunner()      # la traduzione gira in un thread (i test usano InlineRunner)
        self.translating = False     # traduzione in corso
        self.closing = False         # chiusura richiesta durante la traduzione
        self.screen = None
        self.last_dialog = None
        self._dialog = None
        self._placed = False
        self.environment = ''        # etichetta del database collegato: dev, test, prod ('' = non impostata, vale come prod)

        if scale_factor is None:
            scale.init(root)
        else:
            scale.set_factor(scale_factor)
        root.title(f'{APP_TITLE} v{VERSION}')
        try:
            root.iconbitmap(self.paths.icon)
        except tk.TclError:
            pass
        set_window_icons(root, self.paths.icon)      # piccola per il titolo, grande per la barra delle applicazioni
        root.resizable(True, True)
        setup_style(root)
        self.stepper = Stepper(root, self.go_back, self.paths.graphics)
        self.stepper.pack(side='top', fill='x')
        self.infobar = InfoBar(root)                    # in basso: a quale database si e' collegati
        self.infobar.pack(side='bottom', fill='x')
        self.area = ScrollArea(root)                    # se la finestra non basta per il passo: barra di scorrimento
        self.area.pack(side='top', fill='both', expand=True)
        self.show_connection()
        root.protocol('WM_DELETE_WINDOW', self.on_closing)

    # ------------------------------------------------------------------- passi

    def _show(self, screen_class, step):
        new = screen_class(self.area.inner, self)          # prima si costruisce il nuovo passo, poi si toglie il vecchio:
        if self.screen is not None:                  # nessun momento con la finestra vuota
            self.screen.destroy()
        self.screen = new
        self.area.to_top()
        new.pack(fill='both', expand=True)
        new.bind('<Configure>', self._on_screen_resize)
        self.stepper.set_active(step)
        self.fit_window()

    def show_connection(self):
        self._show(ConnectionScreen, 1)

    def show_translation(self):
        self._show(TranslationScreen, 2)

    def go_back(self):
        """Nuova connessione: chiude quella aperta e torna al passo 1."""
        if self.translating:
            return
        self.disconnect()
        self.show_connection()

    # ------------------------------------------------------------ servizi per le schermate

    def connect(self, values):
        try:
            self.db.connect(values['host'], values['port'], values['sid'], values['username'], values['password'])
        except Exception:
            self.infobar.set_disconnected()      # db.connect ha gia' chiuso la connessione precedente
            raise
        self.environment = environments.normalize(values.get('environment', ''))
        self.db.info['environment'] = self.environment
        self.infobar.set_connected(self.db.info)
        try:
            self.settings.save_connection(values['host'], values['port'], values['sid'], values['username'],
                                          values['password'])
            self.settings.save_environment(values['host'], values['port'], values['sid'], self.environment)
        except OSError as e:                     # la connessione e' riuscita: un file non scrivibile non la annulla
            print(f'Could not save the connection data: {e}')

    def set_environment(self, env):
        """Cambia l'etichetta del database collegato (subito, senza ricollegarsi) e la ricorda per quel database."""
        self.environment = environments.normalize(env)
        info = self.db.info
        if not info:
            return
        info['environment'] = self.environment
        self.infobar.set_connected(info)
        try:
            self.settings.save_environment(info['host'], info['port'], info['sid'], self.environment)
        except OSError as e:
            print(f'Could not save the environment: {e}')

    def disconnect(self):
        self.db.close()
        self.environment = ''
        self.infobar.set_disconnected()

    def available_tables(self):
        """Le tabelle abilitate. Con una connessione aperta, solo quelle che esistono su questo database."""
        entries = self.catalog.tables()
        return self.db.existing_tables(entries) if self.db.connected else entries

    def make_translator(self):
        return AzureTranslator(self.settings.azure_credentials(), Glossary.load(self.paths.glossary))

    def set_busy(self, busy):
        self.root.config(cursor='watch' if busy else '')
        if busy:
            self.root.update_idletasks()

    # ----------------------------------------------------------------- finestra

    def fit_window(self):
        """Adatta la finestra al contenuto, la tiene intera nello schermo e ne consente il ridimensionamento."""
        if self.screen is None:
            return
        self.root.update_idletasks()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        needed_w = min(max(px(WINDOW_MIN_WIDTH), self.screen.winfo_reqwidth(), self.stepper.winfo_reqwidth()), screen_w)
        needed_h = min(self.stepper.winfo_reqheight() + self.screen.winfo_reqheight() + self.infobar.winfo_reqheight(),
                       screen_h - px(100))
        width = min(max(needed_w, self.root.winfo_width()), screen_w) if self._placed else needed_w
        self.root.minsize(needed_w, needed_h)
        if self._placed:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            x = max(0, min(x, screen_w - width))             # mai oltre il bordo destro
        else:
            x, y = (screen_w - width) // 2, max(20, (screen_h - needed_h) // 4)
            self._placed = True
        y = max(0, min(y, screen_h - needed_h - px(BOTTOM_MARGIN)))      # mai oltre il bordo basso
        geometry = f'{width}x{needed_h}+{x}+{y}'
        if self.root.geometry() != geometry:          # solo se cambia davvero: niente scatti per ridimensionamenti inutili
            self.root.geometry(geometry)

    def _on_screen_resize(self, event):
        if event.widget is self.screen:
            self.screen.wrap.update(event.width)

    # ------------------------------------------------------------------ chiusura

    def confirm_write(self, question, detail, type_to_confirm=None, ok_text='Write'):
        """La conferma prima di scrivere sul database. Con `type_to_confirm` (database prod o senza etichetta) per
        confermare si deve scrivere quel nome."""
        return self.confirm(question, detail, ok_text, 'Cancel', type_to_confirm=type_to_confirm, wrap=360)

    def confirm(self, question, detail='', ok_text='OK', cancel_text='Cancel', **options):
        """Una conferma alla volta: una seconda richiesta con una gia' aperta la porta in primo piano."""
        if self._dialog is not None:
            self._dialog.top.lift()
            return False
        self._dialog = self.last_dialog = ConfirmDialog(self.root, question, detail, ok_text, cancel_text,
                                                        icon=self.paths.icon, **options)
        try:
            return self._dialog.show()
        finally:
            self._dialog = None

    def on_closing(self):
        if self.translating:
            if self.confirm('Stop the translation and quit?', 'Rows already written stay in the database.',
                            'Stop and quit', 'Keep translating'):
                if self.translating:             # potrebbe essere finita mentre la conferma era aperta
                    self.closing = True          # il thread si ferma alla riga corrente, poi si chiude tutto
                    self.runner.stop()
                    self.screen.on_close_requested()
                else:
                    self.finish_close()
            return
        self.finish_close()                  # niente in corso: si chiude subito (anche dal pannello di Windows)

    def finish_close(self):
        self.db.close()
        self.root.destroy()

    def shutdown(self):
        """Chiude la connessione anche se l'app esce per un errore (prima aspetta la riga in corso)."""
        self.runner.stop()
        self.runner.join(10)
        self.db.close()
