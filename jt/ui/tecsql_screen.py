"""Lo strumento SQL <-> TecSQL: si incolla una query e la si traduce nell'altra forma (la direzione si capisce da sola: il `$`
dice che e' TecSQL). Non scrive niente sul database e non serve la chiave Azure: legge solo il dizionario dei nomi."""
import tkinter as tk
from tkinter import ttk

from ..tecsql_translator import normalize_query_text
from .dictionary_bar import DictionaryBar
from .scale import pad, px
from .theme import FONT, PALETTE
from .widgets import ScrolledText, StatusBar, ToolTip, WrapTracker

MONO = ('Consolas', 10)
EMPTY_HINT = 'Paste a query: with a $ it is TecSQL (to SQL), without it is SQL (to TecSQL).'


class TecsqlScreen(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=pad(20, 4, 20, 6))           # come le altre schermate: 20 di margine ai lati
        self.app = app
        self.wrap = WrapTracker()
        self.dictionary = None              # il Dictionary del database collegato
        self.direction = ''                 # 'tecsql_to_sql' | 'sql_to_tecsql' dopo una traduzione
        self.candidates = {}                # nome mostrato -> chiave del descrittore (solo se la query e' ambigua)
        self.var_strip = tk.BooleanVar(value=app.settings.preferences().get('tecsql', 'strip_parameters'))
        self.var_choice = tk.StringVar(value='')

        # --- la query e il risultato: due riquadri uno sopra l'altro con un divisore da trascinare e che crescono con la finestra.
        # Titoli e pulsanti stanno sulla riga del titolo (niente righe di sola intestazione): lo spazio e' per il testo.
        self.panes = ttk.PanedWindow(self, orient='vertical')
        self.panes.pack(fill='both', expand=True)
        query_pane, card, header = self._pane('QUERY')
        self.bar = DictionaryBar(header, app, self._say, on_reload=self._reloaded)          # "Names dictionary: N fields  Reload"
        self.bar.pack(side='right')
        self.label_dictionary, self.reload_button = self.bar.label, self.bar.button
        self.input_box = ScrolledText(card, height=4)
        self.input = self.input_box.text
        self.input_box.pack(fill='both', expand=True)
        self.input.bind('<Control-Return>', lambda _e: (self.translate(), 'break')[1])
        buttons = tk.Frame(card, bg=PALETTE['bg'])
        buttons.pack(fill='x', pady=(px(6), 0))
        self.translate_button = ttk.Button(buttons, text='Translate', style='Small.Primary.TButton', command=self.translate)
        self.translate_button.pack(side='left', padx=(0, px(6)))
        self.clear_button = ttk.Button(buttons, text='Clear', style='Small.Secondary.TButton', command=self.clear)
        self.clear_button.pack(side='left')
        self.check_strip = ttk.Checkbutton(buttons, text='Remove ?parameters', variable=self.var_strip)
        self.check_strip.pack(side='right')
        ToolTip(self.check_strip, {'title': 'Remove ?parameters',
                                   'intro': 'TecSQL to SQL only: drops the WHERE/HAVING conditions that use a ?parameter, '
                                            'so the query can be run as it is.'})

        # se la tabella ha piu' nomi logici: quale (sotto la query)
        self.choice_row = tk.Frame(query_pane, bg=PALETTE['bg'])
        self.choice_label = tk.Label(self.choice_row, text='', bg=PALETTE['bg'], fg=PALETTE['warn'], font=(FONT, 9, 'bold'),
                                     justify='left', anchor='w', wraplength=px(420))
        self.choice_label.pack(fill='x')
        self.choice_box = ttk.Combobox(self.choice_row, textvariable=self.var_choice, state='readonly', width=1)
        self.choice_box.pack(fill='x', pady=(px(2), 0))
        self.choice_box.bind('<<ComboboxSelected>>', self._chosen)
        self.wrap.add(self.choice_label, 60)

        result_pane, card, header = self._pane('RESULT', top=px(6))
        self.label_direction = tk.Label(header, text='', bg=PALETTE['bg'], fg=PALETTE['muted'], font=(FONT, 9))
        self.label_direction.pack(side='left', padx=(px(8), 0))
        self.copy_button = ttk.Button(header, text='Copy', style='Small.Secondary.TButton', command=self.copy, state='disabled')
        self.copy_button.pack(side='right')
        self.swap_button = ttk.Button(header, text='Use as query', style='Small.Secondary.TButton', command=self.swap,
                                      state='disabled')
        self.swap_button.pack(side='right', padx=(0, px(6)))
        ToolTip(self.swap_button, {'title': 'Use as query',
                                   'intro': 'Puts the result in the query box, to translate it back to the other form.'})
        self.output_box = ScrolledText(card, height=4, readonly=True)
        self.output = self.output_box.text
        self.output_box.pack(fill='both', expand=True)

        self.status = StatusBar(self, EMPTY_HINT, on_change=lambda: app.fit_window(), compact=True)
        self.status.pack(fill='x', pady=(px(6), 0), side='bottom')
        self.wrap.add(self.status, 95)

        self.load_dictionary()

    def _pane(self, title, top=0):
        """Un riquadro del divisore: una riga con il titolo (a destra e a sinistra ci si mettono i pulsanti) e la scheda che cresce con
        la finestra. Ritorna (il riquadro, la scheda, la riga del titolo)."""
        pane = tk.Frame(self.panes, bg=PALETTE['bg'])
        self.panes.add(pane, weight=1)
        header = tk.Frame(pane, bg=PALETTE['bg'])
        header.pack(fill='x', pady=(top, px(6)))
        tk.Label(header, text=title, bg=PALETTE['bg'], fg=PALETTE['accent'], font=(FONT, 9, 'bold'), anchor='w').pack(side='left')
        card = tk.Frame(pane, bg=PALETTE['bg'], highlightthickness=1, highlightbackground=PALETTE['border'],
                        padx=px(6), pady=px(6))
        card.pack(fill='both', expand=True)
        return pane, card, header

    # ------------------------------------------------------------------ dizionario

    def _say(self, state, text):
        self.status.show(state, text)

    def load_dictionary(self, force=False):
        """Legge il dizionario dei nomi dal database collegato (una volta per connessione)."""
        ok = self.bar.load(force)
        self.dictionary = self.bar.dictionary
        return ok

    def _reloaded(self):
        self.dictionary = self.bar.dictionary
        self.clear_result()

    @staticmethod
    def _reason(error):
        return ' '.join(str(error).split())[:200]

    # ------------------------------------------------------------------- traduzione

    def query_text(self):
        return normalize_query_text(self.input.get('1.0', 'end'))

    def translate(self, chosen=None):
        """Traduce la query: con un `$` e' TecSQL (-> SQL), senza e' SQL (-> TecSQL)."""
        text = self.query_text()
        if not text:
            self.clear_result()
            self.status.show('info', EMPTY_HINT)
            return
        if self.dictionary is None and not self.load_dictionary():
            return
        self.hide_choice()
        try:
            if '$' in text:
                self._show_result(self.dictionary.to_sql(text, strip_params=self.var_strip.get()), 'tecsql_to_sql')
                self.status.show('ok', 'Translated to SQL.')
            else:
                self._to_tecsql(text, chosen)
        except Exception as e:                         # il traduttore dice con un ValueError cosa non va
            self.clear_result()
            self.status.show('error', self._reason(e))

    def _to_tecsql(self, text, chosen):
        result = self.dictionary.to_tecsql(text, chosen)
        if result.get('ambiguous'):
            self.clear_result()
            self._ask_which(result)
            return
        if not result.get('success'):
            self.clear_result()
            self.status.show('error', result.get('error') or 'The query could not be translated.')
            return
        self._show_result(result['tecsql'], 'sql_to_tecsql')
        untranslated = result.get('untranslated_fields') or []
        if result.get('partial_translation') and untranslated:
            shown = ', '.join(untranslated[:6]) + ('...' if len(untranslated) > 6 else '')
            self.status.show('warn', f'Translated in part. Not found in the dictionary: {shown}')
        else:
            self.status.show('ok', 'Translated to TecSQL.')

    def _ask_which(self, result):
        """La tabella fisica ha piu' nomi logici: si chiede quale usare (poi si traduce da capo)."""
        names = {}
        for key in result.get('candidates') or []:
            key = key.get('descriptor') if isinstance(key, dict) else key
            names[self.dictionary.table_original_case.get(key, key)] = key
        self.candidates = names
        self.choice_label.config(text=f"{result.get('table', 'This table')} has {len(names)} logical names. Which one?")
        self.choice_box.config(values=list(names))
        self.var_choice.set('')
        self.choice_row.pack(fill='x', pady=(px(8), 0))
        self.status.show('warn', 'More than one logical name fits: choose one above.')
        self.app.fit_window()

    def _chosen(self, _event=None):
        key = self.candidates.get(self.var_choice.get())
        if key:
            self.translate(chosen=key)

    def hide_choice(self):
        if self.choice_row.winfo_manager():
            self.choice_row.pack_forget()
            self.app.fit_window()
        self.candidates = {}

    # ------------------------------------------------------------------- risultato

    def _show_result(self, text, direction):
        self.direction = direction
        self.output.config(state='normal')
        self.output.delete('1.0', 'end')
        self.output.insert('1.0', text)
        self.output.config(state='disabled')
        self.label_direction.config(text='TecSQL → SQL' if direction == 'tecsql_to_sql' else 'SQL → TecSQL')
        for button in (self.copy_button, self.swap_button):
            button.config(state='normal')

    def result_text(self):
        return self.output.get('1.0', 'end').strip()

    def clear_result(self):
        self.direction = ''
        self.output.config(state='normal')
        self.output.delete('1.0', 'end')
        self.output.config(state='disabled')
        self.label_direction.config(text='')
        for button in (self.copy_button, self.swap_button):
            button.config(state='disabled')

    def clear(self):
        self.input.delete('1.0', 'end')
        self.clear_result()
        self.hide_choice()
        self.status.show('info', EMPTY_HINT)

    def swap(self):
        """Il risultato diventa la query (per ritradurlo dall'altra parte)."""
        text = self.result_text()
        if not text:
            return
        self.input.delete('1.0', 'end')
        self.input.insert('1.0', text)
        self.clear_result()
        self.hide_choice()
        self.status.show('info', EMPTY_HINT)

    def copy(self):
        text = self.result_text()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status.show('ok', 'Result copied to the clipboard.')
