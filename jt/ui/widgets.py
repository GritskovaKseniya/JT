"""Widget riutilizzabili: suggerimento, banner di stato, barra della connessione, pannello dei passi, testi che vanno a capo."""
import os
import tkinter as tk
from tkinter import ttk

from .. import environments
from . import scale
from .scale import px
from .texts import shorten
from .theme import FONT, FONT_SYMBOL, PALETTE


def work_area_bottom(widget):
    """Il bordo basso dell'area utile dello schermo: sopra la barra delle applicazioni di Windows, che copre il resto.
    Senza Windows (o se la chiamata fallisce) e' il bordo dello schermo."""
    screen_height = widget.winfo_screenheight()
    try:
        import ctypes
        from ctypes import wintypes
        rect = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):      # SPI_GETWORKAREA
            return min(rect.bottom, screen_height)
    except (AttributeError, ImportError, OSError):
        pass
    return screen_height


def widen_dropdown(combo, width):
    """L'elenco di un Combobox e' largo come il campo e taglia i nomi lunghi: all'apertura lo si allarga a `width` pixel
    (senza uscire dallo schermo). Serve quando il campo mostra solo la parte corta del nome."""
    def widen():
        popdown = f'{combo}.popdown'
        try:
            if not int(combo.tk.call('winfo', 'ismapped', popdown)):
                return
            wide = max(width, combo.winfo_width())
            x, y = int(combo.tk.call('winfo', 'rootx', popdown)), int(combo.tk.call('winfo', 'rooty', popdown))
            height = int(combo.tk.call('winfo', 'height', popdown))
            x = max(0, min(x, combo.winfo_screenwidth() - wide))
            combo.tk.call('wm', 'geometry', popdown, f'={wide}x{height}+{x}+{y}')
        except tk.TclError:
            pass                                   # l'elenco si e' gia' chiuso

    combo.configure(postcommand=lambda: combo.after(1, widen))


class ToolTip:
    """Suggerimento che compare passando il mouse sul widget (o su uno qualsiasi di quelli indicati: un solo riquadro).
    content: dict (title, intro, rows, footer), un testo semplice oppure funzione che lo restituisce."""

    def __init__(self, widget, content, *more_widgets):
        self.widget = widget
        self.widgets = (widget,) + more_widgets
        self.content = content
        self.tip = None
        for w in self.widgets:
            w.bind('<Enter>', self.show, add='+')
            w.bind('<Leave>', self._leave, add='+')

    def show(self, _event=None):
        if self.tip:
            return
        data = self.content() if callable(self.content) else self.content
        if isinstance(data, (str, os.PathLike)):
            data = {'title': str(data)}                   # un testo semplice (es. il percorso della cartella dei log)
        c = PALETTE
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        outer = tk.Frame(self.tip, bg=c['border'], padx=1, pady=1)
        outer.pack()
        body = tk.Frame(outer, bg='white', padx=px(10), pady=px(7))
        body.pack()
        tk.Label(body, text=data['title'], bg='white', fg=c['accent'], font=(FONT, 9, 'bold')).pack(anchor='w')
        if data.get('intro'):
            tk.Label(body, text=data['intro'], bg='white', fg=c['text'], font=(FONT, 9),
                     wraplength=px(300), justify='left').pack(anchor='w', pady=(px(1), px(4)))
        grid = tk.Frame(body, bg='white')
        grid.pack(anchor='w', fill='x', pady=(px(2), 0))
        for i, (name, desc) in enumerate(data.get('rows', [])):
            tk.Label(grid, text=name, bg='white', fg=c['text'], font=(FONT, 9, 'bold'),
                     justify='left', anchor='nw').grid(row=i, column=0, sticky='nw', padx=(0, px(12)), pady=px(1))
            tk.Label(grid, text=desc, bg='white', fg=c['muted'], font=(FONT, 9),
                     wraplength=px(210), justify='left', anchor='nw').grid(row=i, column=1, sticky='nw', pady=px(1))
        if data.get('footer'):
            tk.Frame(body, bg=c['border'], height=1).pack(fill='x', pady=(px(5), px(4)))
            tk.Label(body, text=data['footer'], bg='white', fg=c['muted'], font=(FONT, 9),
                     wraplength=px(300), justify='left').pack(anchor='w')
        # posizione: sotto il widget, ma sempre dentro lo schermo
        self.tip.update_idletasks()
        w, h = self.tip.winfo_reqwidth(), self.tip.winfo_reqheight()
        x = min(self.widget.winfo_rootx() + px(10), self.widget.winfo_screenwidth() - w - px(10))
        limit = work_area_bottom(self.widget) - px(8)          # non sotto la barra delle applicazioni
        below = self.widget.winfo_rooty() + self.widget.winfo_height() + px(6)
        above = self.widget.winfo_rooty() - h - px(6)
        if below + h <= limit:
            y = below
        elif above >= 0:
            y = above
        else:                                  # ne' sotto ne' sopra: si tiene tutta in vista, anche se copre il widget
            y = max(0, limit - h)
        self.tip.wm_geometry(f'+{max(x, 0)}+{max(y, 0)}')
        self.tip.lift()

    def _leave(self, _event=None):
        """Passare da un widget all'altro dello stesso suggerimento non lo chiude."""
        try:
            under_pointer = self.widget.winfo_containing(*self.widget.winfo_pointerxy())
        except (tk.TclError, KeyError):
            under_pointer = None
        if under_pointer not in self.widgets:
            self.hide()

    def hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class StatusBar(tk.Frame):
    """Banner di stato: barra colorata a sinistra, icona e testo su fondo tenue. L'altezza segue il testo
    (minimo due righe). `show(stato, testo)` con stato in info/ok/error/warn; `config(text=, fg=)` come una Label.
    `on_change` viene chiamata quando cambia il testo (la finestra puo' doversi adattare)."""

    STYLES = {   # stato: (sfondo, barra, testo, icona, simbolo)
        'info': ('#eef1f6', '#9aa7bd', PALETTE['muted'], PALETTE['muted'], 'ⓘ'),
        'ok': ('#e8f5ec', PALETTE['ok'], '#14532d', PALETTE['ok'], '✔'),
        'error': ('#fdeceb', PALETTE['error'], '#7f1d1d', PALETTE['error'], '✖'),
        'warn': ('#fff4e0', PALETTE['warn'], '#7c2d12', PALETTE['warn'], '⚠'),
    }
    BY_COLOR = {PALETTE['ok']: 'ok', 'green': 'ok', PALETTE['error']: 'error', 'red': 'error',
                PALETTE['warn']: 'warn', 'orange': 'warn'}

    def __init__(self, parent, text, on_change=None, closable=False):
        super().__init__(parent, bd=0, highlightthickness=0)
        self.on_change = on_change
        self._idle_job = None
        self.columnconfigure(2, weight=1)
        self.rowconfigure(0, minsize=px(38))
        self.bar = tk.Frame(self, width=px(5), bd=0)
        self.bar.grid(row=0, column=0, sticky='ns')
        self.icon = tk.Label(self, font=(FONT_SYMBOL, 12), padx=px(10))
        self.icon.grid(row=0, column=1)
        self.message = tk.Label(self, text=text, anchor='w', justify='left', font=(FONT, 9),
                                wraplength=px(320), pady=px(6))
        self.message.grid(row=0, column=2, sticky='ew')
        self.close_button = None
        if closable:                 # con la crocetta il banner si toglie; chi lo usa lo rimette quando serve (pack)
            self.close_button = tk.Label(self, text='\u2715', font=(FONT_SYMBOL, 9), cursor='hand2', padx=px(10))
            self.close_button.grid(row=0, column=3)
            self.close_button.bind('<Button-1>', self.dismiss)
        self.state = 'info'
        self.set_state('info')

    def set_state(self, name):
        self.state = name
        bg, bar, fg, icon, glyph = self.STYLES[name]
        tk.Frame.configure(self, bg=bg)
        self.bar.configure(bg=bar)
        self.icon.configure(bg=bg, fg=icon, text=glyph)
        self.message.configure(bg=bg, fg=fg)
        if self.close_button is not None:
            self.close_button.configure(bg=bg, fg=fg)

    def dismiss(self, _event=None):
        """Toglie il banner dalla finestra (che si adatta)."""
        self.pack_forget()
        self._notify()

    def show(self, state, text):
        self.message.configure(text=text)
        self.set_state(state)
        self._notify()

    def config(self, text=None, fg=None, **kw):
        if text is not None:
            self.message.configure(text=text)
        if fg is not None:
            self.set_state(self.BY_COLOR.get(fg, 'info'))
        if kw:
            tk.Frame.configure(self, **kw)
        if text is not None:
            self._notify()

    configure = config

    def set_wrap(self, width):
        self.message.configure(wraplength=width)

    def _notify(self):
        if self.on_change and self._idle_job is None:
            self._idle_job = self.after_idle(self._fire)

    def _fire(self):
        self._idle_job = None
        if self.on_change:
            self.on_change()

    def destroy(self):
        if self._idle_job is not None:
            try:
                self.after_cancel(self._idle_job)
            except tk.TclError:
                pass
        super().destroy()


NOT_CONNECTED = 'Not connected   \u00b7   try the connection to continue'


class InfoBar(tk.Frame):
    """Riga in basso, sempre visibile e a bassa enfasi: a quale database si e' collegati.
    Mostra il nome del database dichiarato dal server (se lo da') altrimenti l'SID digitato; il dettaglio e' nel suggerimento."""

    def __init__(self, parent):
        super().__init__(parent, bg=PALETTE['bg'])
        tk.Frame(self, height=1, bg=PALETTE['border']).pack(fill='x')
        row = tk.Frame(self, bg=PALETTE['bg'], padx=px(20), pady=px(5))
        row.pack(fill='x')
        self.dot = tk.Label(row, text='●', font=(FONT_SYMBOL, 8), bg=PALETTE['bg'])
        self.dot.pack(side='left')
        self.label = tk.Label(row, font=(FONT, 9), fg=PALETTE['muted'], bg=PALETTE['bg'], anchor='w')
        self.label.pack(side='left', padx=(px(6), 0))
        self.chip = tk.Label(row, font=(FONT, 8, 'bold'), fg='white', padx=px(6), pady=px(1))      # dev / test / prod
        self.info = None
        ToolTip(row, self._hint, self.dot, self.label, self.chip)
        self.set_disconnected()

    def set_connected(self, info):
        self.info = info
        name = shorten(info.get('db_name') or info.get('sid') or '?', 30)
        self.dot.configure(fg=PALETTE['ok'])
        self.label.configure(text=f"Connected to {name}   ·   {shorten(info.get('host', ''), 30)}   ·   "
                                  f"user {shorten(info.get('user', ''), 24)}")
        text, color = environments.chip(info.get('environment', ''))
        self.chip.configure(text=text, bg=PALETTE[color])
        self.chip.pack(side='right')

    def set_disconnected(self):
        self.info = None
        self.dot.configure(fg='#8a94a6')
        self.label.configure(text=NOT_CONNECTED)
        self.chip.pack_forget()

    def _hint(self):
        if not self.info:
            return {'title': 'Database connection', 'rows': [('Status', 'Not connected')]}
        info = self.info
        rows = [('Database', info.get('db_name') or '(not reported by the server)')]
        if info.get('sid') and info['sid'].lower() != str(info.get('db_name') or '').lower():
            rows.append(('SID', info['sid']))                 # solo se e' diverso dal nome dichiarato dal server
        rows += [('Host', f"{info.get('host', '')}:{info.get('port', '')}"), ('User', info.get('user', ''))]
        env = environments.normalize(info.get('environment', ''))
        rows.append(('Environment', env or 'not set (treated as prod)'))
        return {'title': 'Database connection', 'rows': rows}


class WrapTracker:
    """Ricalcola l'"a capo" dei testi quando cambia la larghezza della schermata."""

    def __init__(self):
        self._items = []

    def add(self, widget, margin):
        self._items.append((widget, margin))

    def update(self, frame_width):
        for widget, margin in self._items:
            width = max(px(180), frame_width - px(margin))
            if hasattr(widget, 'set_wrap'):
                widget.set_wrap(width)
            else:
                widget.config(wraplength=width)


def coming_soon(parent, text, wrap):
    """Riga "COMING SOON  <testo>" per le funzioni in arrivo."""
    row = ttk.Frame(parent)
    tk.Label(row, text='COMING SOON', bg=PALETTE['accent_soft'], fg=PALETTE['accent'], font=(FONT, 8, 'bold'),
             padx=px(6), pady=px(1)).pack(side='left', anchor='n', padx=(0, px(8)))
    label = ttk.Label(row, text=text, style='Muted.TLabel', wraplength=px(262), justify='left')
    label.pack(side='left', anchor='w')
    wrap.add(label, 150)
    return row


class Stepper(tk.Frame):
    """Pannello dei passi: (1) Connection ── (2) Translation, con il link "New connection" a destra.

    I pallini sono immagini (Graphics/step_<n>_<stato>[_<px>].png, antialiasing, una per scala dello schermo).
    Senza immagini si usa un'etichetta di testo. `states` dice lo stato di ogni passo: 'done', 'current' o 'todo'."""

    NAMES = ('Connection', 'Translation')
    STATES = ('done', 'current', 'todo')
    IMAGES = ((1, 'current'), (1, 'done'), (2, 'todo'), (2, 'current'))   # gli unici pallini che compaiono

    def __init__(self, parent, on_new_connection, graphics_dir=None):
        super().__init__(parent, bg=PALETTE['bg'], padx=px(20), pady=px(12))
        self.step = 1
        self.states = ['current', 'todo']
        self.columnconfigure(2, weight=1)
        self._images = self._load_images(graphics_dir)
        self._badges, self._names = [], []
        for index, (name, column) in enumerate(zip(self.NAMES, (0, 3))):
            badge = tk.Label(self, bg=PALETTE['bg'], font=(FONT, 9, 'bold'), width=2)
            badge.grid(row=0, column=column)
            label = tk.Label(self, text=name, bg=PALETTE['bg'], font=(FONT, 10))
            label.grid(row=0, column=column + 1, padx=(px(6), 0))
            self._badges.append(badge)
            self._names.append(label)
        tk.Frame(self, height=2, bg=PALETTE['border']).grid(row=0, column=2, sticky='ew', padx=px(8))
        self.link = tk.Label(self, text='New connection', bg=PALETTE['bg'], fg=PALETTE['accent'],
                             cursor='hand2', font=(FONT, 9, 'underline'))
        self.link.grid(row=0, column=5, padx=(px(14), 0))
        self.link.bind('<Button-1>', lambda _e: self._click(on_new_connection))
        self.link_enabled = True
        self.set_active(1)

    @staticmethod
    def _load_images(graphics_dir):
        """Pallini della dimensione adatta alla scala dello schermo (24, 30, 36 o 48 px)."""
        factor = scale.factor()
        size = 24 if factor < 1.1 else 30 if factor < 1.35 else 36 if factor < 1.75 else 48
        suffix = '' if size == 24 else f'_{size}'
        images = {}
        for number, state in Stepper.IMAGES:
            try:
                images[(number, state)] = tk.PhotoImage(
                    file=os.path.join(graphics_dir, f'step_{number}_{state}{suffix}.png'))
            except (tk.TclError, TypeError):
                return {}                # anche una sola immagine mancante: tutto in modalita' testo
        return images

    def _click(self, callback):
        if self.link_enabled:
            callback()

    def set_link_enabled(self, enabled):
        self.link_enabled = enabled
        self.link.configure(fg=PALETTE['accent'] if enabled else PALETTE['muted'],
                            cursor='hand2' if enabled else 'arrow')

    def _style_badge(self, badge, number, state):
        if self._images:
            badge.configure(image=self._images[(number, state)], width=0)
            return
        c = PALETTE                       # modalita' testo
        text, bg, fg = {'done': ('✔', c['ok'], 'white'), 'current': (str(number), c['accent'], 'white'),
                        'todo': (str(number), c['trough'], c['muted'])}[state]
        badge.configure(text=text, bg=bg, fg=fg)

    def set_active(self, step):
        self.step = step
        self.states = ['done' if i < step else 'current' if i == step else 'todo' for i in (1, 2)]
        for i, (badge, label, state) in enumerate(zip(self._badges, self._names, self.states), start=1):
            self._style_badge(badge, i, state)
            label.configure(fg=PALETTE['text'] if state == 'current' else PALETTE['muted'],
                            font=(FONT, 10, 'bold') if state == 'current' else (FONT, 10))
        if step == 2:
            self.link.grid()
        else:
            self.link.grid_remove()


class ScrollArea(tk.Frame):
    """Contenitore che mostra una barra di scorrimento verticale solo se il contenuto non entra: una finestra piu' bassa
    del suo contenuto (schermo piccolo, scala 150%) non lo taglia in silenzio. I passi si costruiscono dentro `inner`."""

    def __init__(self, parent):
        super().__init__(parent, bg=PALETTE['bg'])
        self.canvas = tk.Canvas(self, bg=PALETTE['bg'], highlightthickness=0, bd=0, width=1, height=1)
        self.bar = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = tk.Frame(self.canvas, bg=PALETTE['bg'])
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', self._sync)
        self.canvas.bind('<Configure>', self._fit_width)
        self.bind_all('<MouseWheel>', self._wheel, add='+')

    @property
    def scrolling(self):
        """True se il contenuto e' piu' alto dell'area visibile (e quindi c'e' la barra)."""
        return self.bar.winfo_manager() != ''

    def _fit_width(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._sync()

    def _sync(self, _event=None):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() > 1
        if needed and not self.scrolling:
            self.bar.pack(side='right', fill='y', before=self.canvas)
        elif not needed and self.scrolling:
            self.bar.pack_forget()
            self.canvas.yview_moveto(0)

    def to_top(self):
        self.canvas.yview_moveto(0)

    def _wheel(self, event):
        """La rotella scorre il contenuto, ma non quando il mouse e' su un menu a tendina (lo cambierebbe)."""
        if not self.scrolling:
            return
        widget = event.widget
        if not str(widget).startswith(str(self.inner)) or isinstance(widget, ttk.Combobox):
            return
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')


class Collapsible(tk.Frame):
    """Sezione comprimibile: una riga con freccia, titolo e un riassunto; un clic (o Invio/Spazio) apre o chiude il corpo
    (`body`). Chiusa mostra solo la riga: il riassunto dice cosa c'e' dentro. A destra della riga c'e' `extra`, per un
    elemento che deve restare visibile anche a sezione chiusa. `on_toggle` viene chiamata dopo ogni cambio (la finestra
    si adatta)."""

    OPEN, CLOSED = '\u25be', '\u25b8'

    def __init__(self, parent, title, summary='', expanded=False, on_toggle=None):
        super().__init__(parent, bg=PALETTE['bg'])
        self.on_toggle = on_toggle
        self.expanded = False
        self.header = tk.Frame(self, bg=PALETTE['bg'], cursor='hand2', takefocus=True, highlightthickness=1,
                               highlightbackground=PALETTE['bg'], highlightcolor=PALETTE['accent'])
        self.header.pack(fill='x')
        self.arrow = tk.Label(self.header, text=self.CLOSED, font=(FONT_SYMBOL, 9), fg=PALETTE['accent'], bg=PALETTE['bg'])
        self.title = tk.Label(self.header, text=title, font=(FONT, 9, 'bold'), fg=PALETTE['accent'], bg=PALETTE['bg'])
        self.summary = tk.Label(self.header, text=summary, font=(FONT, 9), fg=PALETTE['muted'], bg=PALETTE['bg'], anchor='w')
        self.extra = tk.Frame(self.header, bg=PALETTE['bg'])
        self.arrow.pack(side='left')
        self.title.pack(side='left', padx=(px(4), 0))
        self.summary.pack(side='left', padx=(px(10), 0))
        self.extra.pack(side='right')
        for widget in (self.header, self.arrow, self.title, self.summary):
            widget.bind('<Button-1>', self.toggle, add='+')
        for key in ('<Return>', '<space>'):
            self.header.bind(key, self.toggle, add='+')
        self.body = tk.Frame(self, bg=PALETTE['bg'])
        if expanded:
            self.expand(notify=False)

    def set_summary(self, text):
        self.summary.config(text=text)

    def expand(self, _event=None, notify=True):
        if self.expanded:
            return
        self.expanded = True
        self.arrow.config(text=self.OPEN)
        self.body.pack(fill='x')
        if notify and self.on_toggle:
            self.on_toggle()

    def collapse(self, _event=None, notify=True):
        if not self.expanded:
            return
        self.expanded = False
        self.arrow.config(text=self.CLOSED)
        self.body.pack_forget()
        if notify and self.on_toggle:
            self.on_toggle()

    def toggle(self, _event=None):
        (self.collapse if self.expanded else self.expand)()
