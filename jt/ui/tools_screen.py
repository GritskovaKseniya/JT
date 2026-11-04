"""Il guscio del passo 2: la riga degli strumenti (schede piatte con sottolineatura, nascondibile) e, sotto, lo strumento scelto.
Si usa solo quando gli strumenti sono piu' di uno (con uno solo l'app mostra direttamente la sua schermata, come prima)."""
import tkinter as tk
from tkinter import ttk

from .scale import px
from .theme import FONT, FONT_SYMBOL, PALETTE
from .widgets import ToolTip, WrapTracker


class _WrapAll:
    """Il `wrap` della schermata del guscio: gira la larghezza a tutte le schermate degli strumenti gia' costruite."""

    def __init__(self, shell):
        self._shell = shell

    def update(self, width):
        for screen in self._shell.built.values():
            wrap = getattr(screen, 'wrap', None)
            if isinstance(wrap, WrapTracker):
                wrap.update(width)


class ToolBar(tk.Frame):
    """La riga delle schede. Una scheda e' un testo con una linea sotto: blu quando e' lo strumento aperto, grigia se e' spenta
    (il motivo compare in un suggerimento). A sinistra una freccia nasconde la riga: nascosta resta il nome dello strumento
    aperto e la freccia per riaprirla. `on_select(nome)` si chiama al clic su una scheda accesa; `on_toggle()` dopo ogni cambio."""

    OPEN, CLOSED = '▾', '▸'

    def __init__(self, parent, tools, problems, on_select, on_toggle):
        super().__init__(parent, bg=PALETTE['bg'])
        self.on_select, self.on_toggle = on_select, on_toggle
        self.expanded = True
        self.tabs, self.lines, self.tips = {}, {}, []
        self.problems = problems
        self.selected = None

        top = tk.Frame(self, bg=PALETTE['bg'])
        top.pack(fill='x')
        self.arrow = tk.Label(top, text=self.OPEN, font=(FONT_SYMBOL, 9), fg=PALETTE['accent'], bg=PALETTE['bg'],
                              cursor='hand2', takefocus=True, highlightthickness=1, highlightbackground=PALETTE['bg'],
                              highlightcolor=PALETTE['accent'])
        self.arrow.pack(side='left', padx=(0, px(6)))
        self.arrow.bind('<Button-1>', self.toggle)
        for key in ('<Return>', '<space>'):
            self.arrow.bind(key, self.toggle)
        self.strip = tk.Frame(top, bg=PALETTE['bg'])                 # le schede
        self.strip.pack(side='left')
        self.summary = tk.Label(top, text='', font=(FONT, 10, 'bold'), fg=PALETTE['accent'], bg=PALETTE['bg'])  # da chiusa
        self.rule = tk.Frame(self, height=1, bg=PALETTE['border'])
        self.rule.pack(fill='x')

        for tool in tools:
            cell = tk.Frame(self.strip, bg=PALETTE['bg'])
            cell.pack(side='left', padx=(0, px(2)))
            off = bool(problems[tool.name])
            label = tk.Label(cell, text=tool.title, font=(FONT, 10), bg=PALETTE['bg'], padx=px(10), pady=px(5),
                             fg=PALETTE['muted'] if off else PALETTE['text'], cursor='arrow' if off else 'hand2',
                             takefocus=not off, highlightthickness=1, highlightbackground=PALETTE['bg'],
                             highlightcolor=PALETTE['accent'])
            line = tk.Frame(cell, height=px(3), bg=PALETTE['bg'])      # la linea sotto la scheda aperta
            label.pack()
            line.pack(fill='x')
            self.tabs[tool.name], self.lines[tool.name] = label, line
            if off:
                self.tips.append(ToolTip(label, {'title': 'Not available', 'intro': problems[tool.name]}))
            else:
                label.bind('<Button-1>', lambda _e, name=tool.name: self.on_select(name))
                for key in ('<Return>', '<space>'):
                    label.bind(key, lambda _e, name=tool.name: self.on_select(name))
                label.bind('<Enter>', lambda _e, name=tool.name: self._hover(name, True), add='+')
                label.bind('<Leave>', lambda _e, name=tool.name: self._hover(name, False), add='+')

    # --------------------------------------------------------------------- aspetto

    def _hover(self, name, inside):
        if name != self.selected:
            self.tabs[name].config(fg=PALETTE['accent_dark'] if inside else PALETTE['text'])

    def set_selected(self, name, title):
        self.selected = name
        for other, label in self.tabs.items():
            if self.problems[other]:
                continue
            chosen = other == name
            label.config(fg=PALETTE['accent'] if chosen else PALETTE['text'])
            self.lines[other].config(bg=PALETTE['accent'] if chosen else PALETTE['bg'])
        self.summary.config(text=title)

    # ------------------------------------------------------------------ nascondere

    def collapse(self, _event=None):
        if not self.expanded:
            return
        self.expanded = False
        self.arrow.config(text=self.CLOSED)
        self.strip.pack_forget()
        self.summary.pack(side='left')
        self.on_toggle()

    def expand(self, _event=None):
        if self.expanded:
            return
        self.expanded = True
        self.arrow.config(text=self.OPEN)
        self.summary.pack_forget()
        self.strip.pack(side='left')
        self.on_toggle()

    def toggle(self, _event=None):
        (self.collapse if self.expanded else self.expand)()


class ToolsScreen(ttk.Frame):
    def __init__(self, parent, app, tools):
        super().__init__(parent)
        self.app = app
        self.tools = list(tools)
        self.built = {}                    # nome -> la schermata dello strumento (costruita al primo uso, poi tenuta)
        self.problems = {tool.name: app.tool_problem(tool) for tool in self.tools}      # nome -> perche' e' spento
        self.selected = None               # il nome dello strumento mostrato
        self.wrap = _WrapAll(self)
        self.menu = ToolBar(self, self.tools, self.problems, self.select, lambda: app.fit_window())
        self.menu.pack(fill='x', pady=(0, px(6)))
        self.content = ttk.Frame(self)
        self.content.pack(fill='both', expand=True)
        first = next((tool for tool in self.tools if not self.problems[tool.name]), None)
        if first is not None:               # si apre da solo il primo strumento acceso
            self.select(first.name, notify=False)

    # --------------------------------------------------------------- scelta dello strumento

    def tool(self, name):
        return next(tool for tool in self.tools if tool.name == name)

    def select(self, name, notify=True):
        """Mostra lo strumento `name` (costruito al primo uso e poi tenuto). Spento o durante una traduzione: niente."""
        if name == self.selected or self.problems[name]:
            return
        if self.app.translating:                         # durante una traduzione non si cambia strumento
            return
        if self.selected is not None:
            self.built[self.selected].pack_forget()
        if name not in self.built:
            self.built[name] = self.tool(name).build(self.content, self.app)
        self.built[name].pack(fill='both', expand=True)
        self.selected = name
        self.menu.set_selected(name, self.tool(name).title)
        if notify:
            self.app.fit_window()

    @property
    def current(self):
        return self.built.get(self.selected)

    # ---------------------------------------------- quello che l'app chiede alla schermata corrente

    @property
    def preview(self):
        return getattr(self.current, 'preview', None)

    def on_close_requested(self):
        current = self.current
        if current is not None and hasattr(current, 'on_close_requested'):
            current.on_close_requested()
