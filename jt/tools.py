"""Gli strumenti di JTools: nome, titolo, tabelle che richiedono, se scrivono. Nessuna interfaccia qui.

Dopo il Connect il guscio (`ui/tools_screen.py`) mostra gli strumenti come schede: quello che non puo' funzionare su questo
database (tabelle mancanti) resta visibile ma spento, con il motivo. Il registro lo riempie `ui/app.py`: ogni strumento sa
costruire la sua schermata (`build(parent, app)`).
"""
from dataclasses import dataclass
from typing import Callable, Optional, Tuple


@dataclass(frozen=True)
class Tool:
    name: str                                       # identificativo breve (strings, tecsql...)
    title: str                                      # il testo della scheda
    build: Callable                                 # build(parent, app) -> la schermata dello strumento
    requires: Tuple[str, ...] = ()                  # tabelle che devono esistere sul database
    writes: bool = False                            # scrive sul database (serve la chiave Azure per tradurre)
    check: Optional[Callable] = None                # check(app) -> motivo se non puo' funzionare, '' altrimenti


def problem(tool, db_has_table, extra=None):
    """Perche' lo strumento e' spento ('' = acceso). `db_has_table(nome)` dice se la tabella esiste su questo database."""
    missing = [name for name in tool.requires if not db_has_table(name)]
    if missing:
        return f"needs {', '.join(missing)}: not found on this database"
    if tool.check is not None:
        return tool.check(extra) or ''
    return ''
