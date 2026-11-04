"""L'etichetta dell'ambiente di un database: dove si scrive e con quanta cautela.

Il programma non puo' sapere se un database e' di prova o di un cliente: lo dice una volta chi lo usa (`dev`, `test`, `prod`)
e l'etichetta si ricorda per quel database. Non impostata vale come prod: la scelta prudente.
"""

ENVIRONMENTS = ('dev', 'test', 'prod')
NOT_SET = 'Not set'
CHOICES = (NOT_SET,) + ENVIRONMENTS         # le scelte del campo Environment

_CHIPS = {'dev': ('DEV', 'accent'), 'test': ('TEST', 'ok'), 'prod': ('PROD', 'error'), '': ('NOT SET', 'warn')}


def normalize(value):
    """'dev', 'test' o 'prod'; altrimenti '' (non impostata o sconosciuta)."""
    text = str(value or '').strip().lower()
    return text if text in ENVIRONMENTS else ''


def is_strict(env):
    """Non impostata o prod: prima di scrivere bisogna scrivere il nome del database."""
    return normalize(env) in ('', 'prod')


def to_label(env):
    return normalize(env) or NOT_SET


def from_label(label):
    return '' if label == NOT_SET else normalize(label)


def key(host, port, sid):
    """Come si riconosce un database: maiuscole e spazi non contano."""
    return f'{str(host).strip().lower()}:{str(port).strip()}/{str(sid).strip().upper()}'


def chip(env):
    """(testo, nome del colore in PALETTE) del segno colorato che dice l'ambiente."""
    return _CHIPS[normalize(env)]
