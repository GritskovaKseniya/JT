"""Colori, font e stile ttk dell'applicazione. Tutto l'aspetto grafico si cambia da qui.

I contrasti (WCAG) sono stati calcolati: testo normale >= 4,5:1, bordi dei campi ~3:1.
"""
from tkinter import ttk

from .scale import pad

PALETTE = {
    'bg': '#f3f5f9',
    'text': '#1f2937',
    'muted': '#5b6370',          # 5,55:1 sullo sfondo
    'accent': '#0b5cab',
    'accent_dark': '#084a8c',
    'accent_soft': '#e6effa',
    'border': '#c3cbd9',         # contorni delle schede (decorativi)
    'field_border': '#8a94a6',   # contorni di campi e menu (3:1)
    'trough': '#d3dbe8',
    'disabled_bg': '#d3dbe8',
    'disabled_fg': '#4a5565',    # 5,42:1 sul fondo del pulsante disattivato
    'disabled_soft_bg': '#e8ecf3',
    'ok': '#14703a',
    'error': '#b91c1c',
    'warn': '#b45309',
}
FONT = 'Segoe UI'
FONT_SYMBOL = 'Segoe UI Symbol'


def setup_style(root):
    c = PALETTE
    root.configure(bg=c['bg'])

    # elenco che si apre dai menu a discesa
    for option, value in (('background', 'white'), ('foreground', c['text']), ('selectBackground', c['accent']),
                          ('selectForeground', 'white'), ('font', '{%s} 10' % FONT), ('relief', 'flat'),
                          ('borderWidth', 0), ('highlightThickness', 0)):
        root.option_add('*TCombobox*Listbox.' + option, value)

    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', background=c['bg'], foreground=c['text'], font=(FONT, 10))
    style.configure('TFrame', background=c['bg'])
    style.configure('TLabel', background=c['bg'])
    style.configure('Muted.TLabel', foreground=c['muted'], font=(FONT, 9))
    style.configure('Card.TLabelframe', background=c['bg'], bordercolor=c['border'], relief='solid')
    style.configure('Card.TLabelframe.Label', background=c['bg'], foreground=c['accent'], font=(FONT, 9, 'bold'))

    # divisore tra due riquadri: niente puntini, solo una fascia libera da trascinare (il cursore cambia)
    style.configure('Sash', gripcount=0, sashthickness=pad(10)[0], background=c['bg'], lightcolor=c['bg'], darkcolor=c['bg'],
                    bordercolor=c['bg'])
    style.configure('TEntry', fieldbackground='white', bordercolor=c['field_border'], padding=pad(4))
    style.map('TEntry', fieldbackground=[('disabled', c['disabled_soft_bg'])], foreground=[('disabled', c['muted'])])
    style.configure('TCombobox', fieldbackground='white', bordercolor=c['field_border'], padding=pad(4))
    style.map('TCombobox', fieldbackground=[('readonly', 'white'), ('disabled', c['disabled_soft_bg'])],
              background=[('readonly', 'white'), ('active', c['accent_soft'])],
              foreground=[('readonly', c['text']), ('disabled', c['muted'])],
              selectbackground=[('readonly', 'white')], selectforeground=[('readonly', c['text'])],
              arrowcolor=[('!disabled', c['accent'])])
    style.configure('Vertical.TScrollbar', background='#c9d3e3', troughcolor='#eef1f6', bordercolor=c['border'],
                    arrowcolor=c['accent'], relief='flat')
    style.configure('Horizontal.TProgressbar', troughcolor=c['trough'], background=c['accent'],
                    bordercolor=c['border'], thickness=pad(5)[0])
    # tabella dell'anteprima
    style.configure('Treeview', rowheight=pad(22)[0], background='white', fieldbackground='white',
                    bordercolor=c['border'], font=(FONT, 9))
    style.configure('Treeview.Heading', font=(FONT, 9, 'bold'), background=c['accent_soft'], foreground=c['accent'],
                    relief='flat')
    style.map('Treeview', background=[('selected', c['accent'])], foreground=[('selected', 'white')])

    # Pulsanti: Primary (azione principale, pieno), Secondary (bordo e testo blu su bianco), Danger (azione che ferma).
    # Il rettangolo tratteggiato di default e' nascosto (focuscolor = colore del pulsante).
    button = dict(padding=(pad(10)[0], pad(4)[0]), font=(FONT, 10, 'bold'))
    style.configure('Primary.TButton', background=c['accent'], foreground='white', bordercolor=c['accent'],
                    focuscolor=c['accent'], **button)
    style.map('Primary.TButton',
              background=[('disabled', c['disabled_bg']), ('pressed', c['accent_dark']), ('active', c['accent_dark'])],
              foreground=[('disabled', c['disabled_fg'])],
              bordercolor=[('disabled', c['border']), ('focus', c['accent_dark'])])
    style.configure('Secondary.TButton', background='white', foreground=c['accent'], bordercolor=c['accent'],
                    focuscolor='white', **button)
    style.map('Secondary.TButton',
              background=[('disabled', c['disabled_soft_bg']), ('pressed', '#cfe0f5'), ('active', c['accent_soft'])],
              foreground=[('disabled', c['muted'])],
              bordercolor=[('disabled', c['border']), ('focus', c['accent_dark'])])
    style.configure('Danger.TButton', background='white', foreground=c['error'], bordercolor=c['error'],
                    focuscolor='white', **button)
    style.map('Danger.TButton',
              background=[('disabled', c['disabled_soft_bg']), ('pressed', '#f8cfcc'), ('active', '#fdeceb')],
              foreground=[('disabled', c['muted'])],
              bordercolor=[('disabled', c['border'])])
    # versioni piccole per le finestre di dialogo: ereditano colori e stati dal nome ("Small.Primary" da "Primary")
    for kind in ('Primary', 'Secondary'):
        style.configure(f'Small.{kind}.TButton', padding=(pad(14)[0], pad(3)[0]), font=(FONT, 9, 'bold'))
