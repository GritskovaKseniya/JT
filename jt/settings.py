"""Impostazioni salvate: ultima connessione, ultima scelta, credenziali Azure."""
from . import environments
from .jsonstore import read_json, write_json
from .connections import ConnectionProfiles
from .preferences import Preferences
from .search_history import SearchHistory


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

    def profiles(self):
        """I profili di connessione salvati."""
        return ConnectionProfiles(self._paths.connections)

    def searches(self, database, tool=''):
        """La storia delle ricerche di tabelle di questo database e di questo strumento (`database` = environments.key); il massimo si sceglie in
        preferences.json ("history": {"max": 50})."""
        limit = self.preferences().get('history', 'max')
        key = f'{database}|{tool}' if tool else database          # una storia per strumento (Names e Indexes non la dividono)
        return SearchHistory(self._paths.searches, key, limit if limit > 0 else 1, inherit=(database if tool == 'names' else None) if tool else '')

    def azure_credentials(self):
        return read_json(self._paths.azure)
