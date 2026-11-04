"""Impostazioni salvate: ultima connessione, ultima scelta, credenziali Azure."""
from . import environments
from .jsonstore import read_json, write_json
from .preferences import Preferences


class Settings:
    def __init__(self, paths):
        self._paths = paths

    def _read_optional(self, path):
        try:
            data = read_json(path)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def preferences(self):
        """Le preferenze scritte a mano (riletto a ogni uso: si cambia il file e basta)."""
        return Preferences(self._paths.preferences)

    def connection(self):
        data = self._read_optional(self._paths.connection)
        return {key: data.get(key, '') for key in ('host', 'port', 'sid', 'username', 'password')}

    def save_connection(self, host, port, sid, username, password):
        data = self._read_optional(self._paths.connection)
        data.update(host=host, port=port, sid=sid, username=username, password=password)
        write_json(self._paths.connection, data)

    def environment(self, host, port, sid):
        """L'etichetta (dev/test/prod) ricordata per questo database, oppure '' se non c'e'."""
        saved = self._read_optional(self._paths.connection).get('environments')
        if not isinstance(saved, dict):
            return ''
        return environments.normalize(saved.get(environments.key(host, port, sid)))

    def save_environment(self, host, port, sid, env):
        """Ricorda l'etichetta per questo database (insieme ai dati di connessione); '' la toglie."""
        data = self._read_optional(self._paths.connection)
        saved = data.get('environments')
        saved = dict(saved) if isinstance(saved, dict) else {}
        label, where = environments.normalize(env), environments.key(host, port, sid)
        if label:
            saved[where] = label
        else:
            saved.pop(where, None)
        data['environments'] = saved
        write_json(self._paths.connection, data)

    def last_query(self):
        return self._read_optional(self._paths.query)

    def save_last_query(self, language_in, language_out, table_description, level=None):
        data = self._read_optional(self._paths.query)
        data.update(linput=language_in, loutput=language_out, table=table_description)
        if level is not None:
            data['level'] = level
        write_json(self._paths.query, data)

    MAX_SEARCHES = 50

    def search_history(self):
        """Le tabelle cercate di recente, ordinate per nome fisico: [{'fisico': ..., 'logico': ...}]."""
        try:
            data = read_json(self._paths.searches)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict) and item.get('fisico')]

    def add_search(self, physical, logical):
        """Ricorda una tabella cercata (una volta sola, al massimo MAX_SEARCHES)."""
        history = self.search_history()
        entry = {'fisico': physical, 'logico': logical}
        if entry in history:
            return
        history.append(entry)
        history.sort(key=lambda item: item['fisico'].lower())
        write_json(self._paths.searches, history[-self.MAX_SEARCHES:])

    def azure_credentials(self):
        return read_json(self._paths.azure)
