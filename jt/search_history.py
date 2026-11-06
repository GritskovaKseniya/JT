"""La storia delle ricerche di tabelle (Names e Indexes), una per database: si ricorda quello che hai scritto (cercando "Articolo" resta
"Articolo", cercando MD_ARTI resta MD_ARTI), con la tabella trovata. Le piu' recenti stanno in cima. File: search_history.json."""
import datetime

from .jsonstore import read_json, write_json

LEGACY = '*'            # le ricerche del vecchio formato (senza database): passano al primo database che si apre


def _clean(items):
    """Le voci valide di una lista (testo non vuoto), senza doppioni (stesso testo e stessi campi; maiuscole e minuscole contano
    come uno)."""
    seen, result = set(), []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or not item['text'].strip():
            continue
        key = (item['text'].strip().casefold(), str(item.get('fields') or '').strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append({'text': item['text'].strip(), 'physical': str(item.get('physical') or ''),
                       'logical': str(item.get('logical') or ''), 'fields': str(item.get('fields') or '').strip(),
                       'last_used': str(item.get('last_used') or '')})
    return result


class SearchHistory:
    def __init__(self, path, database, limit=50, inherit=''):   # inherit=None: non eredita niente
        self.path, self.database, self.limit = path, database, max(1, int(limit))
        self.inherit = inherit                  # la storia di prima che fosse divisa per strumento: la eredita chi non ne ha una

    # ------------------------------------------------------------------------------------------------- file

    def _read(self):
        try:
            data = read_json(self.path)
        except (OSError, ValueError):
            return {}
        if isinstance(data, list):                  # il vecchio formato: [{'fisico', 'logico'}], una voce per nome logico
            old = [{'text': i['fisico'], 'physical': i['fisico'], 'logical': i.get('logico', '')}
                   for i in data if isinstance(i, dict) and isinstance(i.get('fisico'), str) and i['fisico']]
            old = _clean(old)
            return {LEGACY: old} if old else {}
        databases = data.get('databases') if isinstance(data, dict) else None
        if not isinstance(databases, dict):
            return {}
        return {key: _clean(items) for key, items in databases.items()}

    def _write(self, data):
        write_json(self.path, {'databases': data})

    # ---------------------------------------------------------------------------------------------- uso

    def entries(self):
        """Le ricerche di questo database, le piu' recenti per prime (al massimo `limit`)."""
        data = self._read()
        if self.database not in data and self.inherit is not None and (LEGACY in data or self.inherit in data):
            # una volta sola: le vecchie ricerche (di tutti gli strumenti, o senza database) passano a questo strumento
            data[self.database] = list(data.get(self.inherit) or data.pop(LEGACY))
            data.pop(LEGACY, None)
            try:
                self._write(data)
            except OSError:
                pass
        return data.get(self.database, [])[:self.limit]

    def matching(self, typed):
        """Le voci che contengono quello che stai scrivendo (nel testo, nel nome fisico o in quello logico)."""
        typed = (typed or '').strip().casefold()
        return [e for e in self.entries() if not typed or typed in e['text'].casefold() or typed in e['physical'].casefold()
                or typed in e['logical'].casefold() or typed in e['fields'].casefold()]

    def add(self, text, physical, logical, fields=''):
        """Ricorda una ricerca: il testo scritto, la tabella trovata e i campi chiesti (Names). Se c'era gia' (stesso testo e stessi
        campi) passa in cima."""
        text, fields = (text or '').strip(), (fields or '').strip()
        if not text:
            return
        current = self.entries()                         # porta con se' anche le vecchie ricerche, se e' la prima volta
        data = self._read()
        items = [e for e in current if not self._same(e, text, fields)]
        items.insert(0, {'text': text, 'physical': physical, 'logical': logical, 'fields': fields,
                         'last_used': datetime.datetime.now().isoformat(timespec='seconds')})
        data[self.database] = items[:self.limit]
        self._write(data)

    @staticmethod
    def _same(entry, text, fields):
        return (entry['text'].casefold() == text.strip().casefold()
                and entry['fields'].strip().casefold() == (fields or '').strip().casefold())

    @staticmethod
    def label(entry):
        """Come compare la voce nel menu: il testo, e dopo il punto a mezza altezza i campi se ce n'erano."""
        return f"{entry['text']} \u00b7 {entry['fields']}" if entry['fields'] else entry['text']

    def remove(self, text, fields=''):
        current = self.entries()
        data = self._read()
        data[self.database] = [e for e in current if not self._same(e, text, fields)]
        self._write(data)

    def clear(self):
        data = self._read()
        data[self.database] = []
        data.pop(LEGACY, None)
        self._write(data)
