"""Nitidezza su schermi con scala diversa da 100%.

Senza dichiarare che l'app gestisce la scala, Windows la ingrandisce come un'immagine (testo sfocato).
Dichiarando "DPI aware" (come fa IDLE di Python) il testo e' disegnato alla risoluzione vera.
Va chiamata PRIMA di creare la finestra Tk.
"""


def enable_dpi_awareness():
    """Ritorna True se ha dichiarato la consapevolezza della scala (False su sistemi senza questa funzione)."""
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)      # 1 = scala del sistema (stabile con Tk)
        return True
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()       # Windows piu' vecchi
            return True
        except Exception:
            return False
