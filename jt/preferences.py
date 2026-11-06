"""Preferenze di visualizzazione scritte a mano dall'utente in Data/preferences.json (nessuna schermata: si apre il file e si cambia).
Il file e' facoltativo e tollerante: se manca, e' rotto o ha un valore sbagliato vale il predefinito, e l'app parte lo stesso.
Si possono commentare delle righe con `//` (come in un file di configurazione): `//"names",` nasconde lo strumento."""
import json


DEFAULTS = {
    'order tools': [],                                      # gli strumenti mostrati e il loro ordine; quelli che mancano sono nascosti
    'default_tool': '',                                     # strings | tecsql | names | indexes ('' = il primo)
    'tecsql': {'strip_parameters': False},                  # "Remove ?parameters" acceso all'apertura
    'names': {'sort': '', 'descending': False, 'hide_columns': []},      # colonna per ordinare, verso, colonne da nascondere
    'indexes': {'expand_all': False, 'follow_names': True},   # aprendo Indexes si mostra la tabella cercata in Names
    'tools_bar': {'collapsible': True, 'collapse_on_select': True},   # la riga delle schede si puo' chiudere (freccia); e si chiude scelto uno strumento              # scelto uno strumento, la riga delle schede si chiude (resta il nome)
    'history': {'max': 50},                                 # quante ricerche di tabelle si ricordano (per database)                       # gli indici si aprono mostrando le colonne
}
NAMES_COLUMNS = ('POSIZ_DB', 'CAMPO_FISICO', 'CAMPO_LOGICO', 'TIPO', 'AMPIEZZA', 'DECIMALI', 'TABELLA_LOGICA')


def strip_comments(text):
    """Toglie i commenti `// ...` a fine riga (non quelli dentro a una stringa, come un indirizzo http://...)."""
    out, quoted, escaped, index = [], False, False, 0
    while index < len(text):
        char = text[index]
        if quoted:
            out.append(char)
            escaped = char == chr(92) and not escaped           # il backslash: il carattere dopo e' protetto
            if char == '"' and not escaped:
                quoted = False
        elif char == '"':
            quoted = True
            out.append(char)
        elif text.startswith('//', index):
            while index < len(text) and text[index] != '\n':
                index += 1
            continue
        else:
            out.append(char)
        index += 1
    return ''.join(out)


class Preferences:
    def __init__(self, path=None):
        try:
            with open(path, 'r', encoding='utf-8-sig') as f:
                data = json.loads(strip_comments(f.read()))
        except (OSError, ValueError, TypeError):
            data = {}
        self.data = data if isinstance(data, dict) else {}

    def order_tools(self):
        """I nomi degli strumenti da mostrare, nell'ordine scelto, oppure None se non e' scelto (si mostrano tutti)."""
        value = self.data.get('order tools', self.data.get('order_tools'))
        if not isinstance(value, list):
            return None
        return [str(name).strip().lower() for name in value if isinstance(name, str)]

    def arrange(self, tools):
        """Gli strumenti nell'ordine del file e senza quelli che non ci sono. Nomi sconosciuti si ignorano; se non ne resta nessuno
        (file sbagliato) si mostrano tutti, perche' l'app non resti vuota."""
        order = self.order_tools()
        if order is None:
            return list(tools)
        by_name = {tool.name: tool for tool in tools}
        chosen = []
        for name in order:
            if name in by_name and by_name[name] not in chosen:
                chosen.append(by_name[name])
        return chosen or list(tools)

    def get(self, section, key, default=None):
        """Il valore scelto dall'utente se ha lo stesso tipo del predefinito, altrimenti il predefinito."""
        if default is None:
            default = DEFAULTS[section][key]
        block = self.data.get(section)
        value = block.get(key, default) if isinstance(block, dict) else default
        return value if isinstance(value, type(default)) else default

    def default_tool(self):
        value = self.data.get('default_tool', '')
        return value.strip().lower() if isinstance(value, str) else ''

    def names_sort(self):
        """(colonna, crescente) per ordinare i campi di Names, o None se non e' scelta o non esiste."""
        key = str(self.get('names', 'sort')).strip().upper()
        return (key, not self.get('names', 'descending')) if key in NAMES_COLUMNS else None

    def names_hidden(self):
        hidden = self.get('names', 'hide_columns')
        return {str(c).strip().upper() for c in hidden}
