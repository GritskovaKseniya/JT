"""La finestra principale: passi, dimensioni, chiusura. Qui si collegano interfaccia e logica."""
import tkinter as tk

from .. import azure_key, dictionary, indexes as index_reader, tools as tool_registry
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
from .indexes_screen import IndexesScreen
from .names_screen import NamesScreen
from .tecsql_screen import TecsqlScreen
from .tools_screen import ToolsScreen
from .translation_screen import TranslationScreen
from .winicon import set_window_icons
from .. import environments
from .widgets import InfoBar, ScrollArea, Stepper

BOTTOM_MARGIN = 80        # spazio lasciato per la barra delle applicazioni


def default_tools():
    """Gli strumenti di JTools: Strings (l'attuale JT, scrive) e quelli che leggono soltanto: SQL <-> TecSQL, Names (cercare
    una tabella e i suoi campi) e Indexes (gli indici di una tabella)."""
    return [tool_registry.Tool('strings', 'Strings', lambda parent, app: TranslationScreen(parent, app), writes=True),
            tool_registry.Tool('tecsql', 'SQL <> TecSQL', lambda parent, app: TecsqlScreen(parent, app),
                               requires=dictionary.TABLES),
            tool_registry.Tool('names', 'Names', lambda parent, app: NamesScreen(parent, app), requires=dictionary.TABLES),
            tool_registry.Tool('indexes', 'Indexes', lambda parent, app: IndexesScreen(parent, app),
                               requires=dictionary.TABLES + index_reader.VIEWS)]


class JTApp:
    def __init__(self, root, paths=None, db=None, runner=None, scale_factor=None, tools=None):
        self.root = root
        self.paths = paths or Paths.default()
        self.catalog = Catalog(self.paths)
        self.settings = Settings(self.paths)
        self.db = db or Database()
        self.service = TranslationService(self.db)
        self.runner = runner or BackgroundRunner()      # la traduzione gira in un thread (i test usano InlineRunner)
        self.translating = False     # traduzione in corso
        self.closing = False         # chiusura richiesta durante la traduzione
        self.tools = list(tools) if tools is not None else default_tools()
        self.screen = None
        self.last_dialog = None
        self._dialog = None
        self._placed = False
        self._set_size = None        # la misura (larghezza, altezza) che ha dato fit_window per ultima
        self.user_sized = False      # chi usa l'app ha ingrandito o ridimensionato la finestra: fit_window non la rimpicciolisce
        self.current_table = None    # l'ultima tabella cercata in Names ({'physical', 'logical'}): Indexes la propone
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
        if len(self.tools) > 1:
            self.stepper.set_name(2, 'Tools')
        self.stepper.pack(side='top', fill='x')
        self.infobar = InfoBar(root)                    # in basso: a quale database si e' collegati
        self.infobar.pack(side='bottom', fill='x')
        self.area = ScrollArea(root)                    # se la finestra non basta per il passo: barra di scorrimento
        self.area.pack(side='top', fill='both', expand=True)
        self.show_connection()
        root.protocol('WM_DELETE_WINDOW', self.on_closing)
        root.bind('<Configure>', self._on_root_configure, add='+')

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
        """Il passo 2: con piu' strumenti le schede (ToolsScreen), con uno solo la sua schermata direttamente."""
        if len(self.tools) > 1:
            self._show(lambda parent, app: ToolsScreen(parent, app, self.tools), 2)
        else:
            self._show(lambda parent, app: self.tools[0].build(parent, app), 2)

    def tool_problem(self, tool):
        """Perche' uno strumento e' spento su questo database ('' = acceso)."""
        return tool_registry.problem(tool, self.db.table_exists, self)

    def go_back(self):
        """Nuova connessione: chiude quella aperta e torna al passo 1."""
        if self.translating:
            return
        self.disconnect()
        self.show_connection()

    # ------------------------------------------------------------ servizi per le schermate

    def connect(self, values):
        self.current_table = None
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
        self.current_table = None
        self.environment = ''
        self.infobar.set_disconnected()

    def available_tables(self):
        """Le tabelle abilitate. Con una connessione aperta, solo quelle che esistono su questo database."""
        entries = self.catalog.tables()
        return self.db.existing_tables(entries) if self.db.connected else entries

    def azure_key_problem(self):
        """'' se c'e' una chiave Azure che puo' servire, altrimenti il motivo (vedi azure_key.py)."""
        return azure_key.problem(self.paths.azure)

    def make_translator(self):
        reason = self.azure_key_problem()
        if reason:
            raise RuntimeError(reason)
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
        self.area.refresh()
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        needed_w = min(max(px(WINDOW_MIN_WIDTH), self.screen.winfo_reqwidth(), self.stepper.winfo_reqwidth()), screen_w)
        needed_h = min(self.stepper.winfo_reqheight() + self.screen.winfo_reqheight() + self.infobar.winfo_reqheight(),
                       screen_h - px(100))
        width = min(max(needed_w, self.root.winfo_width()), screen_w) if self._placed else needed_w
        self.root.minsize(needed_w, needed_h)
        if self.root.state() == 'zoomed':               # a tutto schermo: la misura la da' Windows
            self.user_sized = True
            return
        if self.user_sized and self._placed:            # ridimensionata a mano: si cresce se serve, non si torna piu' piccoli
            needed_h = max(needed_h, min(self.root.winfo_height(), screen_h))
        if self._placed:
            x, y = self.root.winfo_x(), self.root.winfo_y()
            x = max(0, min(x, screen_w - width))             # mai oltre il bordo destro
        else:
            x, y = (screen_w - width) // 2, max(20, (screen_h - needed_h) // 4)
            self._placed = True
        if not self.user_sized:                                          # una finestra messa a mano resta dove e' stata messa
            y = max(0, min(y, screen_h - needed_h - px(BOTTOM_MARGIN)))      # mai oltre il bordo basso
        geometry = f'{width}x{needed_h}+{x}+{y}'
        self._set_size = (width, needed_h)
        if self.root.geometry() != geometry:          # solo se cambia davvero: niente scatti per ridimensionamenti inutili
            self.root.geometry(geometry)

    def _on_root_configure(self, event):
        """Una misura diversa da quella data da fit_window e' di chi usa l'app (trascina il bordo, ingrandisce la finestra)."""
        if event.widget is not self.root or self._set_size is None:
            return
        if (event.width, event.height) != self._set_size and self.root.state() in ('normal', 'zoomed'):
            if self.root.state() == 'zoomed' or event.height > self._set_size[1] or event.width != self._set_size[0]:
                self.user_sized = True

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
        preview = getattr(self.screen, 'preview', None)
        if preview is not None and preview.writable:         # tradotto (e pagato ad Azure) ma non ancora scritto
            if not self.confirm('Discard the preview and quit?',
                                'The translations in the preview have not been written. Azure already charged for them: '
                                'a new preview is charged again.', 'Discard and quit', 'Keep the preview'):
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
