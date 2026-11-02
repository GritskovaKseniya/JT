"""Funzioni per i testi mostrati all'utente."""


def fmt_count(n):
    """1234 -> '1.234'; None -> '?'."""
    return '?' if n is None else f'{n:,}'.replace(',', '.')


def rows(n):
    """1 -> '1 row'; 21053 -> '21.053 rows'."""
    return f"{fmt_count(n)} {'row' if n == 1 else 'rows'}"


def describe_duration(seconds):
    """Durata stimata in parole: sotto un minuto non ha senso scrivere 'circa 0.0 minuti'."""
    if seconds < 60:
        return 'less than a minute'
    if seconds < 5400:
        minutes = round(seconds / 60)
        return f"about {minutes} {'minute' if minutes == 1 else 'minutes'}"
    return f'about {seconds / 3600:.1f} hours'


def shorten(text, limit=110):
    """Accorcia a `limit` caratteri al massimo (puntini compresi), a un confine di parola quando possibile.
    Spazi e a capo vengono compattati. Il testo intero resta sulla console."""
    text = ' '.join(str(text).split())
    if len(text) <= limit:
        return text
    budget = max(limit - 3, 1)
    cut = text[:budget]
    if text[budget] != ' ' and ' ' in cut:          # il taglio cade dentro una parola: si torna all'ultimo spazio
        cut = cut.rsplit(' ', 1)[0]
    return cut.rstrip(' ,;:.') + '...'


def reason(error, limit=110):
    """La prima riga del messaggio di un errore, accorciata."""
    lines = str(error).strip().splitlines()
    return shorten(lines[0], limit) if lines else ''
