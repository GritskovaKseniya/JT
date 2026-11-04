"""Impostazioni salvate: ultima connessione, ultima scelta, credenziali Azure."""
from .jsonstore import read_json, write_json


class Settings:
    def __init__(self, paths):
        self._paths = paths

    def _read_optional(self, path):
        try:
            data = read_json(path)
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def connection(self):
        data = self._read_optional(self._paths.connection)
        return {key: data.get(key, '') for key in ('host', 'port', 'sid', 'username', 'password')}

    def save_connection(self, host, port, sid, username, password):
        data = self._read_optional(self._paths.connection)
        data.update(host=host, port=port, sid=sid, username=username, password=password)
        write_json(self._paths.connection, data)

    def last_query(self):
        return self._read_optional(self._paths.query)

    def save_last_query(self, language_in, language_out, table_description, level=None):
        data = self._read_optional(self._paths.query)
        data.update(linput=language_in, loutput=language_out, table=table_description)
        if level is not None:
            data['level'] = level
        write_json(self._paths.query, data)

    def azure_credentials(self):
        return read_json(self._paths.azure)
