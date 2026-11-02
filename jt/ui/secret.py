"""Messaggio nascosto (si apre dal pulsante di 6 pixel in basso a sinistra del passo 2).

Il testo si scrive lettera per lettera senza bloccare l'app (con `after`, non con un ciclo)."""
import tkinter as tk

from .scale import px
from .winicon import set_window_icons

MESSAGE = (
    'MASTER MESSAGE:',
    '-------------------------------------------',
    'Welcome nosy user!',
    "I'm here to inform you that",
    'JT has been happily created on 18-06-2021',
    'and updated on 10-04-2025',
    'by Angelo J. Marin :)',
    '-------------------------------------------',
)


def open_secret_panel(app, button, interval_ms=25):
    button.config(state='disabled')
    window = tk.Toplevel(app.root)
    window.title('Secret Creator Panel')
    try:
        window.iconbitmap(app.paths.icon)
    except tk.TclError:
        pass
    set_window_icons(window, app.paths.icon)
    window.geometry(f'{px(300)}x{px(125)}')
    window.resizable(False, False)

    def close():
        window.destroy()
        try:
            button.config(state='normal')
        except tk.TclError:
            pass                                 # il passo e' cambiato nel frattempo

    window.protocol('WM_DELETE_WINDOW', close)
    label = tk.Label(window, bg='white', text='', anchor='nw', justify='left')
    label.pack(fill='both', expand=True)
    text = '\n'.join(MESSAGE)

    def type_next(count=0):
        if not window.winfo_exists():
            return
        label.config(text=text[:count])
        if count < len(text):
            window.after(interval_ms, type_next, count + 1)

    type_next()
    return window
