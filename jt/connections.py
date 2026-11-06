"""I profili di connessione: una cartella (`connections`, tra i file dell'utente) con un file .json per ogni database salvato.
Si possono copiare e modificare a mano (come preferences.json). Il profilo e' nome, host, porta, SID, utente, password (in chiaro,
come nell'ultima connessione), etichetta dev/test/prod e `last_used`: il piu' recente sta in cima."""
import datetime
import os
import re

from . import environments
from .jsonstore import read_json, write_json

FIELDS = ('host', 'port', 'sid', 'username', 'password')


def _slug(name):
    """Il nome del file per questo nome (senza caratteri che Windows non accetta)."""
    return re.sub(r'[^\w.\- @()]', '_', name).strip(' .') or 'connection'


def _profile(data, fallback_name):
    """Un profilo valido da un file letto (None se non lo e'): i campi mancanti diventano vuoti."""
    if not isinstance(data, dict):
        return None
    name = data.get('name') if isinstance(data.get('name'), str) and data['name'].strip() else fallback_name
    profile = {'name': name.strip()}
    for key in FIELDS:
        profile[key] = str(data.get(key, '') if data.get(key) is not None else '')
    profile['environment'] = environments.normalize(data.get('environment', ''))
    profile['last_used'] = str(data.get('last_used') or '')
    return profile if profile['host'] or profile['sid'] else None


class ConnectionProfiles:
    def __init__(self, folder):
        self.folder = folder

    def _files(self):
        try:
            return sorted(f for f in os.listdir(self.folder) if f.lower().endswith('.json'))
        except OSError:
            return []

    def list(self):
        """Tutti i profili validi, il piu' recente per primo (a parita' in ordine di nome)."""
        profiles = []
        for file in self._files():
            try:
                profile = _profile(read_json(os.path.join(self.folder, file)), os.path.splitext(file)[0])
            except (OSError, ValueError):
                continue
            if profile:
                profile['file'] = file
                profiles.append(profile)
        profiles.sort(key=lambda p: p['name'].casefold())
        profiles.sort(key=lambda p: p['last_used'], reverse=True)
        return profiles

    def names(self):
        return [p['name'] for p in self.list()]

    def get(self, name):
        key = (name or '').strip().casefold()
        return next((p for p in self.list() if p['name'].casefold() == key), None)

    def exists(self):
        return os.path.isdir(self.folder)

    def save(self, name, values, last_used=None):
        """Salva (o sostituisce) il profilo con questo nome; ritorna il profilo salvato."""
        name = name.strip()
        old = self.get(name)
        file = old['file'] if old else self._free_file(name)
        data = {'name': name, **{key: str(values.get(key, '')) for key in FIELDS},
                'environment': environments.normalize(values.get('environment', '')),
                'last_used': last_used if last_used is not None else (old['last_used'] if old else '')}
        write_json(os.path.join(self.folder, file), data)
        return {**data, 'file': file}

    def _free_file(self, name):
        base, number = _slug(name), 1
        taken = {f.casefold() for f in self._files()}
        file = base + '.json'
        while file.casefold() in taken:
            number += 1
            file = f'{base}-{number}.json'
        return file

    def delete(self, name):
        profile = self.get(name)
        if profile:
            os.remove(os.path.join(self.folder, profile['file']))

    def touch(self, name):
        """Segna il profilo come usato adesso (va in cima)."""
        profile = self.get(name)
        if profile:
            self.save(name, profile, last_used=datetime.datetime.now().isoformat(timespec='seconds'))

    def same_database(self, profile, values):
        """Il profilo e' questa connessione? (host, porta, SID e utente; maiuscole e spazi non contano)"""
        def norm(v):
            return str(v).strip().casefold()
        return all(norm(profile[key]) == norm(values.get(key, '')) for key in ('host', 'port', 'sid', 'username'))

    def migrate(self, saved, environment=''):
        """Una volta sola: l'ultima connessione dell'utente (connection_data.json) diventa il primo profilo. Se la cartella c'e' gia'
        (anche vuota) non fa niente: chi ha cancellato i profili non se li ritrova."""
        if self.exists() or not (saved.get('host') and saved.get('sid')):
            return None
        name = f"{saved['sid']} @ {saved['host']}"
        return self.save(name, {**saved, 'environment': environment}, last_used=datetime.datetime.now().isoformat(timespec='seconds'))
