"""Glossario: termini sostituiti (UMV -> HU) e termini lasciati com'erano (Supply Chain Planning, MES...).

Azure non va chiamato per un testo che e' solo un termine; dentro una frase il termine viene marcato
`notranslate` (modalita' html) e il testo viene ripristinato dopo la traduzione.
"""
import html
import re
from dataclasses import dataclass, field
from typing import NamedTuple, Optional

from .jsonstore import read_json


class Prepared(NamedTuple):
    payload: str              # testo da inviare ad Azure
    html: bool                # True se contiene marcatori (textType=html)
    direct: Optional[str]     # se non None e' il risultato: Azure non va chiamato


@dataclass
class Glossary:
    replace: dict = field(default_factory=dict)             # {"UMV": "HU"}
    keep: list = field(default_factory=list)                # termini da non tradurre
    source_languages: list = field(default_factory=list)    # vuoto = qualsiasi lingua sorgente
    replace_skip_targets: list = field(default_factory=list)  # lingue di destinazione senza sostituzioni

    @classmethod
    def load(cls, path):
        """Il file e' opzionale: se manca o e' rotto, nessuna regola."""
        try:
            data = read_json(path)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return cls(replace=data.get('replace', {}), keep=data.get('keep', []),
                   source_languages=data.get('source_languages', []),
                   replace_skip_targets=data.get('replace_skip_targets', []))

    def prepare(self, lan_in, lan_out, text):
        if not isinstance(text, str) or (self.source_languages and lan_in not in self.source_languages):
            return Prepared(text, False, None)

        # le sostituzioni non valgono per le lingue di destinazione che usano il termine originale
        replace = {} if lan_out in self.replace_skip_targets else self.replace

        stripped = text.strip()
        if stripped in replace:
            return Prepared(text, False, replace[stripped])
        if stripped in self.keep:
            return Prepared(text, False, text)

        terms = sorted(list(replace) + list(self.keep), key=len, reverse=True)
        if not terms:
            return Prepared(text, False, None)
        pattern = re.compile(r'(?<!\w)(?:' + '|'.join(re.escape(t) for t in terms) + r')(?!\w)')

        parts, last, found = [], 0, False
        for match in pattern.finditer(text):
            found = True
            parts.append(html.escape(text[last:match.start()], quote=False))
            term = match.group(0)
            # sia 'replace' che 'keep' diventano testo notranslate: per 'replace' il valore sostitutivo e'
            # scritto direttamente nel sorgente (il dizionario dinamico di Azure funziona solo con l'inglese)
            parts.append(f'<span class="notranslate">{html.escape(replace.get(term, term), quote=False)}</span>')
            last = match.end()
        if not found:
            return Prepared(text, False, None)
        parts.append(html.escape(text[last:], quote=False))
        return Prepared(''.join(parts), True, None)

    @staticmethod
    def restore(translated):
        """Toglie i marcatori e riporta le entita' html a testo."""
        return html.unescape(re.sub(r'</?span[^>]*>', '', translated))
