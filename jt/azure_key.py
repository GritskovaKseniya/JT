"""Controllo della chiave Azure: senza una chiave valida JT legge e conta ma non traduce e non scrive.

La chiave e' il permesso di scrivere: chi non l'ha ricevuta (zip senza chiave) usa JT in sola lettura. Il controllo guarda solo
il file e la forma dei valori, non chiama Azure (chiamarlo costerebbe e servirebbe la rete all'avvio).
"""
import json
import re

from .config import KEY_CONTACT

FIELDS = ('subscription_key', 'endpoint', 'location')
KEY_SHAPE = re.compile(r'[A-Za-z0-9]{20,}')              # le chiavi di Azure sono 32 o 84 lettere e cifre


def problem(path):
    """'' se il file della chiave puo' servire; altrimenti il motivo, breve (va dentro il messaggio all'utente)."""
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        return 'the key file was not found'
    except (OSError, ValueError):
        return 'the key file cannot be read'
    if not isinstance(data, dict):
        return 'the key file is not valid'
    missing = [name for name in FIELDS if not isinstance(data.get(name), str) or not data[name].strip()]
    if missing:
        return f"the key file has no {', '.join(missing)}"
    key = data['subscription_key'].strip()
    if 'INSERISCI' in key.upper():
        return 'the key is still the placeholder of the package'
    if not KEY_SHAPE.fullmatch(key):
        return 'the key does not look like an Azure key'
    if not data['endpoint'].strip().lower().startswith('https://'):
        return 'the endpoint is not an https address'
    return ''


def message(reason, folder):
    """Il messaggio per l'utente quando la chiave manca o non vale."""
    return (f'No Azure key ({reason}). JT can read and count rows, but it cannot translate or write. '
            f'Ask {KEY_CONTACT} for the key file and copy it to {folder}.')
