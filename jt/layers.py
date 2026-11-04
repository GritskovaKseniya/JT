from dataclasses import dataclass

from .config import DB_MARKER


@dataclass(frozen=True)
class Layer:
    name: str
    label: str
    prefix: str
    first: int
    last: int
    user: str


# ordine: FW, AP, CT, CW, CK, CC
LAYERS = [
    Layer('FW', 'Framework', 'Fw', 10000, 99999, 'ZFXFW'),
    Layer('AP', 'Standard', '', 100000, 2999999, 'ZFXSYS'),
    Layer('CT', 'Tecnest', 'Ct', 3000000, 3999999, 'ZFXCUSTOM'),
    Layer('CW', 'Integrazioni', 'Cw', 4000000, 4999999, 'ZFXINTEGR'),
    Layer('CK', 'Cliente', 'Ck', 5000000, 5999999, 'ZFXCKSYS'),
    Layer('CC', 'Cliente descrittori', 'Cc', 9000000, 1999999999, 'ZFXCCSYS')
]


def layer_of_code(code):
    for layer in LAYERS:
        if layer.first <= code <= layer.last:
            return layer
    raise ValueError(f"Code {code} is out of range for any layer.")

BY_NAME = {layer.name: layer for layer in LAYERS}

# livelli mostrati nella finestra (gli altri restano nel codice ma nascosti)
VISIBLE = ('AP', 'CW', 'CT', 'CC')

def layer_of_name(name):
    """Layer di un'opzione dal prefisso del nome (Fw, Cw, Ct, Ck, Cc; nessun prefisso = AP).

    Un prefisso scritto con le maiuscole sbagliate (ctXxx) non e' ne' di quel layer ne' AP: ritorna None
    e chi chiama salta la riga.
    """
    if not name:
        raise ValueError("Name cannot be empty.")
    prefixed = [layer for layer in LAYERS if layer.prefix]
    for layer in prefixed:
        if name.startswith(layer.prefix):
            return layer
    for layer in prefixed:
        if name.lower().startswith(layer.prefix.lower()):
            return None
    return BY_NAME['AP']

# Le righe CT, CW e CC si scrivono con l'utente del loro livello; tutte le altre con la sigla del tool (DB_MARKER)
USER_FROM_LAYER = ('CT', 'CW', 'CC')


def user_of_layer(layer):
    """Utente da scrivere nelle colonne utente di una riga di questo livello (layer None = sconosciuto)."""
    return layer.user if layer is not None and layer.name in USER_FROM_LAYER else DB_MARKER


def users_written(level, supports_levels=True):
    """Gli utenti che si scrivono nelle righe: uno con un livello scelto, piu' d'uno con tutti i livelli."""
    if not supports_levels:
        return (DB_MARKER,)
    if level is not None:
        return (user_of_layer(level),)
    return (DB_MARKER,) + tuple(BY_NAME[name].user for name in USER_FROM_LAYER)


def level_label(layer):
    """Nome breve di un livello (messaggi, log): Standard, CW, CT..."""
    return 'Standard' if layer.name == 'AP' else layer.name


TITLES = {'AP': 'Standard', 'CW': 'CW - Integrations', 'CT': 'CT - Customizations',
          'CC': 'CC - Client Customization'}


def level_title(layer):
    """Nome per esteso, quello del campo Level: chi non conosce i livelli di Jflex capisce cosa sono."""
    return TITLES.get(layer.name, layer.name)


def level_short_title(title):
    """Quello che il campo Level mostra a scelta fatta: la parte dopo il trattino ('CW - Integrations' -> 'Integrations')."""
    return title.split(' - ', 1)[-1]


LEVEL_ALL = 'All levels'
# scelte del campo Level: tutti i livelli (nessun filtro) e quelli visibili
LEVEL_CHOICES = {LEVEL_ALL: None, **{level_title(BY_NAME[name]): BY_NAME[name] for name in VISIBLE}}
DEFAULT_LEVEL = level_title(BY_NAME['AP'])
