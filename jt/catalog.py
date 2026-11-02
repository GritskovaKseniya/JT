"""Elenchi statici: lingue e tabelle traducibili (Data/languages.json, Data/tables.json)."""
from .config import PINNED_LANGUAGES
from .jsonstore import read_json


class Catalog:
    def __init__(self, paths):
        self._paths = paths

    def languages(self):
        """Nomi delle lingue come compaiono nei menu: prima quelle fisse (PINNED_LANGUAGES), poi le altre A-Z."""
        pinned = {code: position for position, code in enumerate(PINNED_LANGUAGES)}
        items = sorted(read_json(self._paths.languages),
                       key=lambda item: (pinned.get(item['code'], len(pinned)), item['language'].lower()))
        return [item['language'] for item in items]

    def language_code(self, name):
        for item in read_json(self._paths.languages):
            if item['language'] == name:
                return item['code']
        raise KeyError(name)

    def tables(self):
        """Tabelle abilitate ("enabled": false in tables.json le nasconde; se manca il campo e' attiva)."""
        return [t for t in read_json(self._paths.tables) if t.get('enabled', True)]

    def table_name(self, description):
        for entry in self.tables():
            if entry['description'] == description:
                return entry['table']
        raise KeyError(description)
