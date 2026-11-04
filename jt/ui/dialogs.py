"""Finestre di dialogo nello stile dell'app: compatte, una domanda e due pulsanti."""
import tkinter as tk
from tkinter import ttk

from .scale import pad, px
from .winicon import set_window_icons
from .theme import FONT, PALETTE


class ConfirmDialog:
    """Conferma con due pulsanti. `show()` ritorna True se l'utente conferma.

    Esc e la X della finestra annullano. Invio attiva il pulsante che ha il focus; all'apertura il focus e' su quello
    di annullamento ("Stay"), cosi' un Invio distratto non chiude l'app."""

    def __init__(self, root, question, detail='', ok_text='OK', cancel_text='Cancel', icon=None, type_to_confirm=None,
                 wrap=270):
        self.root = root
        self.icon = icon
        self.result = False
        top = self.top = tk.Toplevel(root)
        top.title(root.title())              # stesso titolo della finestra principale
        top.configure(bg=PALETTE['bg'])
        top.resizable(False, False)
        top.transient(root)
        if icon:
            try:
                top.iconbitmap(icon)
            except tk.TclError:
                pass
        body = ttk.Frame(top, padding=pad(18, 14, 18, 12))
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=question, font=(FONT, 10, 'bold'), wraplength=px(wrap), justify='left').pack(anchor='w')
        if detail:
            ttk.Label(body, text=detail, style='Muted.TLabel', wraplength=px(wrap), justify='left').pack(anchor='w', pady=(px(3), 0))
        self.expected = type_to_confirm
        self.entry = None
        if type_to_confirm:                  # conferma forte: per andare avanti si scrive il nome del database
            ttk.Label(body, text=f'To confirm, type the database name:  {type_to_confirm}',
                      font=(FONT, 9, 'bold')).pack(anchor='w', pady=(px(10), px(3)))
            self.typed = tk.StringVar(top)
            self.entry = ttk.Entry(body, textvariable=self.typed)
            self.entry.pack(fill='x')

        buttons = ttk.Frame(body)
        buttons.pack(fill='x', pady=(px(14), 0))
        self.ok_button = ttk.Button(buttons, text=ok_text, style='Small.Primary.TButton', command=lambda: self._close(True))
        self.ok_button.pack(side='right')
        if self.entry is not None:
            self.ok_button.config(state='disabled')
            self.typed.trace_add('write', self._typed_changed)
        self.cancel_button = ttk.Button(buttons, text=cancel_text, style='Small.Secondary.TButton',
                                        command=lambda: self._close(False))
        self.cancel_button.pack(side='right', padx=(0, px(8)))
        top.protocol('WM_DELETE_WINDOW', lambda: self._close(False))
        top.bind('<Escape>', lambda _e: self._close(False))
        top.bind('<Return>', self._enter)

    def matches(self):
        """Il testo scritto e' il nome atteso (maiuscole e spazi ai bordi non contano)."""
        return self.entry is not None and self.typed.get().strip().casefold() == self.expected.strip().casefold()

    def _typed_changed(self, *_):
        self.ok_button.config(state='normal' if self.matches() else 'disabled')

    def _enter(self, _event=None):
        focused = self.top.focus_get()
        if self.entry is not None and focused is self.entry:        # Invio nel campo: conferma solo se il nome e' giusto
            if self.matches():
                self.ok_button.invoke()
            return
        (focused if focused in (self.ok_button, self.cancel_button) else self.cancel_button).invoke()

    def _close(self, value):
        self.result = value
        self.top.destroy()

    def show(self):
        top = self.top
        top.update_idletasks()
        if self.icon:
            set_window_icons(top, self.icon)
        x = self.root.winfo_rootx() + (self.root.winfo_width() - top.winfo_reqwidth()) // 2
        y = self.root.winfo_rooty() + px(90)
        top.geometry(f'+{max(x, 0)}+{max(y, 0)}')
        top.grab_set()
        (self.entry or self.cancel_button).focus_set()
        self.root.wait_window(top)
        return self.result
