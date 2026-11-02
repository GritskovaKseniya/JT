"""Costanti e percorsi dell'applicazione."""
import os
import sys
from dataclasses import dataclass

APP_TITLE = 'JT - Jflex Translator'
VERSION = '3.0'

DB_MARKER = 'JT'            # scritto nella colonna "utente" delle righe inserite/aggiornate dal tool
SECONDS_PER_ROW = 0.625     # stima della durata: una riga = una chiamata Azure + un INSERT
MAX_KEYS = 1000             # limite di Oracle per una lista IN
WINDOW_MIN_WIDTH = 460
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
    """Percorsi dei file, tutti relativi alla cartella del progetto (non alla cartella di lancio)."""
    base: str

    @classmethod
    def default(cls):
        if getattr(sys, 'frozen', False):          # programma impacchettato (.exe): Data e Graphics stanno accanto all'exe
            return cls(os.path.dirname(sys.executable))
        return cls(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def _file(self, folder, name):
        return os.path.join(self.base, folder, name)

    @property
    def azure(self):
        return self._file('Data', 'azure_services.json')

    @property
    def tables(self):
        return self._file('Data', 'tables.json')

    @property
    def languages(self):
        return self._file('Data', 'languages.json')

    @property
    def connection(self):
        return self._file('Data', 'connection_data.json')

    @property
    def query(self):
        return self._file('Data', 'query_data.json')

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
        return os.path.join(self.base, 'Logs')
