"""Costanti e percorsi dell'applicazione."""
import os
import shutil
import sys
from dataclasses import dataclass

APP_TITLE = 'JTools'
VERSION = '3.4'

KEY_CONTACT = 'Kseniia Hrytskova'   # a chi chiedere il file della chiave Azure (si dice nel messaggio senza chiave)
USER_FOLDER = 'JTools'          # la cartella dei dati dell'utente in %LOCALAPPDATA% (fino alla 3.3 si chiamava 'JT')
OLD_USER_FOLDER = 'JT'
DB_MARKER = 'JT'            # scritto nella colonna "utente" delle righe inserite/aggiornate dal tool
SECONDS_PER_ROW = 0.625     # stima della durata: una riga = una chiamata Azure + un INSERT
MAX_KEYS = 1000             # limite di Oracle per una lista IN
WINDOW_MIN_WIDTH = 500
LOG_PREFIX = 'JT'
# Logo dell'app (icona della finestra): il nome di un file in Graphics/icons/ senza '.ico'.
#   bubbles      due fumetti di traduzione (liscio)
#   pixel_cube   cubo isometrico stile Minecraft, una lettera per faccia
#   pixel_block  blocco piatto stile Minecraft
ICON_NAME = 'bubbles'
# Lingue sempre in cima ai menu, in questo ordine (codici di Data/languages.json); le altre seguono in ordine alfabetico.
PINNED_LANGUAGES = ('it', 'en')
AZURE_TIMEOUT = (5, 30)     # secondi: per collegarsi, per la risposta (senza, una chiamata bloccata blocca tutto)


@dataclass(frozen=True)
class Paths:
    """Percorsi dei file, tutti relativi alla cartella del progetto (non alla cartella di lancio).

    Programma installato (.exe): i file fissi (Data, Graphics) stanno accanto all'exe, in sola lettura; quello che
    l'utente produce o modifica (log, ultima connessione, ultima scelta, chiave Azure) sta in %LOCALAPPDATA%\JTools, come
    fanno le altre applicazioni: sopravvive agli aggiornamenti e alla disinstallazione e non serve scrivere in Program Files.
    Da sorgente `user_base` coincide con `base` e tutto resta nella cartella del progetto."""
    base: str
    user_base: str = ''

    def __post_init__(self):
        if not self.user_base:
            object.__setattr__(self, 'user_base', self.base)

    @classmethod
    def default(cls):
        if getattr(sys, 'frozen', False):          # programma impacchettato (.exe)
            home = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
            return cls(os.path.dirname(sys.executable), os.path.join(home, USER_FOLDER))
        return cls(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _file(self, folder, name):
        return os.path.join(self.base, folder, name)

    def _user_file(self, name):
        """File dell'utente: in `Data` accanto al programma da sorgente, nella cartella dati dell'utente se installato."""
        if self.user_base == self.base:
            return self._file('Data', name)
        return os.path.join(self.user_base, name)

    def seed_user_files(self):
        """Alla prima partenza (programma installato): porta con se' i dati della vecchia cartella `JT` (chiave Azure, ultima
        connessione, log) e copia nella cartella dell'utente i file modello forniti col programma (chiave Azure da compilare,
        preferenze): da li' in poi si gestisce da solo e un aggiornamento del programma non li tocca."""
        if self.user_base == self.base:
            return
        old = os.path.join(os.path.dirname(self.user_base), OLD_USER_FOLDER)
        if not os.path.exists(self.user_base) and os.path.isdir(old):
            shutil.copytree(old, self.user_base)
        for name, target in (('azure_services.json', self.azure), ('preferences.json', self.preferences)):
            packaged = self._file('Data', name)
            if not os.path.exists(target) and os.path.exists(packaged):
                os.makedirs(self.user_base, exist_ok=True)
                shutil.copy(packaged, target)

    @property
    def azure(self):
        return self._user_file('azure_services.json')

    @property
    def tables(self):
        return self._file('Data', 'tables.json')

    @property
    def languages(self):
        return self._file('Data', 'languages.json')

    @property
    def connection(self):
        return self._user_file('connection_data.json')

    @property
    def query(self):
        return self._user_file('query_data.json')

    @property
    def searches(self):
        """Le ultime tabelle cercate nello strumento Names."""
        return self._user_file('search_history.json')

    @property
    def connections(self):
        """La cartella dei profili di connessione (un file .json per database, vedi jt/connections.py)."""
        return self._user_file('connections')

    @property
    def preferences(self):
        """Le preferenze di visualizzazione, scritte a mano (vedi jt/preferences.py)."""
        return self._user_file('preferences.json')

    @property
    def glossary(self):
        return self._file('Data', 'glossary.json')

    @property
    def graphics(self):
        return os.path.join(self.base, 'Graphics')

    @property
    def icon(self):
        return os.path.join(self.base, 'Graphics', 'icons', ICON_NAME + '.ico')

    @property
    def logs(self):
        return os.path.join(self.user_base, 'Logs')
