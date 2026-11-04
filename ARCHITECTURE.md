# JT - Jflex Translator: come e' fatto il codice

```
JT.py                     punto di ingresso (poche righe)
jt/
  config.py               costanti (titolo, versione, marcatore 'JT', limiti) e percorsi dei file
  jsonstore.py            lettura/scrittura JSON
  catalog.py              lingue e tabelle abilitate (Data/languages.json, Data/tables.json)
  settings.py             ultima connessione, ultima scelta, credenziali Azure
  glossary.py             termini sostituiti (UMV -> HU) e non tradotti (Supply Chain Planning, MES...)
  azure.py                client Azure Translator (usa il glossario)
  undo.py                 lo script che annulla una corsa: `UndoRecord` (come si riconosce la riga e cosa c'era prima), costanti SQL
                          sicure (apici raddoppiati, UNISTR per i caratteri speciali), `build_script`
environments.py         etichetta dell'ambiente di un database (dev/test/prod, non impostata = prod), chiave per ricordarla
  layers.py               livelli di Jflex (FW, AP, CW, CT, CK, CC): intervalli dei codici, prefissi dei nomi, utente scritto, livelli visibili
  tables.py               UNA CLASSE PER TABELLA: SQL di selezione (anche per livello), traduzione di una riga, INSERT, UPDATE
  db.py                   connessione Oracle, cursori, metadati (niente logica di traduzione)
  service.py              il lavoro: sceglie le righe, traduce, scrive (INSERT o UPDATE), avanzamento; anteprima (`preview`:
                          traduce senza scrivere) e `write` (scrive le traduzioni dell'anteprima senza richiamare Azure)
  logs.py                 log CSV di ogni esecuzione (cartella Logs\)
  runner.py               esegue un lavoro lungo in un thread e riporta avanzamento/fine/errore (senza Tkinter)
  ui/
    theme.py              colori, font, stile dei pulsanti: tutto l'aspetto si cambia qui
    scale.py, dpi.py      scala dello schermo: px() per le misure in pixel; nitidezza su schermi con scala diversa da 100%
    texts.py              testi per l'utente (numeri, messaggi accorciati)
    widgets.py            ToolTip, StatusBar (banner), InfoBar (database collegato), Stepper (passi), testi che vanno a capo,
                          ScrollArea (barra di scorrimento solo se serve), Collapsible (sezione che si apre e si chiude)
    dialogs.py            finestra di conferma
    connection_screen.py  passo 1
    translation_screen.py passo 2
    secret.py             messaggio nascosto
    app.py                finestra principale: passi, dimensioni, chiusura
Graphics/                 icone della finestra (icons/) e pallini dei passi
tools/                    script per rigenerare le immagini (servono Pillow e i font di Windows: non fanno parte dell'app),
                          creare il database di prova (create_test_db.py) e il simulatore di Oracle (simulate.py)
tests/                    test automatici (vedi TESTS.md)
```

## Regola dei livelli

Ogni livello usa solo quelli sotto di lui: `ui` -> `service` -> `tables` / `db` / `azure` -> `glossary` -> `config`.
Nessun file fuori da `ui/` importa `tkinter`; nessun file di `ui/` contiene SQL o chiama Azure.
Per questo la logica si prova senza aprire finestre (test veloci) e l'interfaccia si cambia senza toccare la logica.

## Come si fa...

**Aggiungere una tabella da tradurre.** Una classe in `jt/tables.py` (copia quella piu' simile) e la sua riga in `TABLES`,
poi una voce in `Data/tables.json`. La classe dice: colonna lingua, chiave logica, come tradurre una riga, come inserirla e
come aggiornarla. Servizio e interfaccia non cambiano.

**La conferma prima di scrivere.** `TranslationScreen._confirm_write` costruisce il riepilogo e chiede a `JTApp.confirm_write`, che
apre `ConfirmDialog`. La finestra si apre solo con un ambiente prod o non impostato (`environments.is_strict`; su dev e test
`_confirm_write` risponde subito di si') e il pulsante si accende solo quando si scrive il nome del database (`type_to_confirm`). L'etichetta si sceglie nella schermata di connessione, si salva per database nel file dei
dati di connessione (`Settings.environment` / `save_environment`) e vive in `JTApp.environment` e `db.info['environment']`. Nei
test `JTApp.confirm_write` e' sostituito da una risposta automatica (`UiCase`).

**Table e Level su una riga.** `TranslationScreen._arrange_selection` dispone i campi su una riga se ci stanno i nomi veri
(`_measure_selection` calcola la soglia dai nomi corti che i campi mostrano: `Object descriptions`, `Client Customization`) e su due altrimenti (con un po' d'isteresi); `_on_card_resize` lo decide dall'ampiezza vera della scheda. Su una
riga le due colonne sono sempre larghe uguale (`_size_selection_columns`: `uniform`, minimo = il nome corto piu' lungo; allargando la
finestra si dividono il resto a meta'; non cambia scegliendo un'altra tabella) e i menu dichiarano `width=1` (senza, pretenderebbero 20 caratteri). **Nome corto nel campo:** il menu elenca i nomi interi
(`JFX: Strings`, `CW - Integrations`), a scelta fatta il campo mostra solo la parte dopo i due punti o il trattino: `var_table` e
`var_level` tengono il nome intero, i campi usano `var_table_shown` / `var_level_shown` (allineati da due trace). L'elenco di un
Combobox e' largo come il campo e taglierebbe i nomi interi: `widen_dropdown` (`widgets.py`) lo allarga all'apertura.

**Sezioni che si aprono e si chiudono.** I blocchi del passo 2 (LANGUAGES, WHAT TO TRANSLATE, PROGRESS) e "Advanced" (Max rows,
Update by keys) e "Details" (tempi) sono `Collapsible` (`ui/widgets.py`): chiuse mostrano solo la riga con un riassunto
(`TranslationScreen._update_summaries`). Nel passo 1 il banner (`StatusBar(closable=True)`) compare solo quando succede qualcosa. Ogni apertura o chiusura fa riadattare la
finestra (`app.fit_window`); se non entra nello schermo compare la barra di `ScrollArea`.

**L'annullamento di una corsa.** `service._write` annota per ogni riga scritta un `UndoRecord` (la chiave della riga da
`spec.update_target(...).where`; per gli UPDATE i valori di prima, letti con una sola `SELECT` che dice anche se la riga c'e' gia',
utente e data compresi). `logs.write_undo_script` scrive `JT_undo_<data>.sql` dopo ogni corsa che ha scritto, anche se i CSV non si
possono scrivere. La chiave (`where`) di ogni tabella coincide con il suo indice univoco in Orione (`fwdb_up.ec`): strings e triplette
(language, code), opzioni (lingua, tipo, codice), FW_DOCU_NODES_T (NODEID, LANG), FW_OBJ_DESCRS (OBJID, TABLENAME, TABLEFIELDNAME,
LANGUAGE); la lingua e' sempre nella chiave, quindi lo script tocca solo la riga di quella lingua. Se per una chiave ci fossero
comunque piu' righe (`AmbiguousKey`) la riga non si aggiorna. Il simulatore esegue lo script (`Simulator.run_script`) e il suo scenario controlla che il database torni identico.

**Gli strumenti e il guscio.** `jt/tools.py` ha il registro: `Tool(name, title, build, requires, writes, check)` e `problem()`, che dice perche' uno strumento e' spento (tabelle richieste mancanti, o il suo `check`). `JTApp.tools` (`default_tools()`: oggi solo Strings) e' l'elenco; `JTApp.tool_problem` controlla le tabelle con `Database.table_exists`. Con **un solo** strumento il passo 2 e' direttamente la sua schermata (come prima); con **piu' d'uno** e' `ui/tools_screen.ToolsScreen`: in alto la riga delle schede (`ToolBar`: schede piatte, testo con una linea blu sotto quella aperta; una scheda spenta e' grigia e il motivo e' nel suo suggerimento; una freccia a sinistra nasconde la riga e, nascosta, resta il nome dello strumento aperto), sotto lo strumento scelto. Ogni strumento si costruisce al primo uso e poi si tiene (cambiando e tornando non perde lo stato); non si cambia strumento durante una traduzione. L'app chiede alla schermata corrente `preview` e `on_close_requested()` (il guscio le gira allo strumento aperto) e il passo 2 si chiama 'Tools'. Per aggiungere uno strumento: un `Tool(...)` in `default_tools()` con la sua schermata (un `ttk.Frame` che si adatta con `wrap`).

**I nomi (SQL <-> TecSQL).** `jt/tecsql_translator.py` e' il traduttore portato da JCTNT (usa `sqlparse`). Il dizionario e' un oggetto `Dictionary` (in fondo al modulo), uno per database collegato e **senza stato globale**: `update(rows)` costruisce le mappe (`table_map`, `field_map`, `physical_table_map`, `reverse_field_map`, e i nomi con le maiuscole originali) e tiene le righe in `rows`; traduce con `to_sql(query, strip_params)` e `to_tecsql(sql, descrittore)`, e `find_descriptors` dice quali nomi logici contengono i campi usati. Le funzioni di modulo che lo usano lo prendono come primo parametro (`d`). `jt/dictionary.py` legge le righe dal database (una `SELECT` su FW_TABLES e FW_TABLE_FIELDS, circa 36.000 righe) con `Database.fetch_all`, e `load(db)` ritorna il `Dictionary` tenendolo in memoria finche' la connessione (host, porta, SID, utente) e' la stessa; `forget()` lo dimentica. I messaggi d'errore sono in inglese. I test usano `tests/tecsql_fixtures.py`: ogni classe crea il suo `Dictionary` (`self.d`).

**Lo strumento SQL <> TecSQL.** `ui/tecsql_screen.TecsqlScreen`: una query in un `Text`, la direzione dal `$`, `Dictionary.to_sql` / `to_tecsql`; la domanda "Which one?" (un `Combobox` che compare solo se la tabella ha piu' nomi logici), l'avviso di traduzione parziale, copia / usa il risultato come query / svuota, "Remove ?parameters", "Reload dictionary". Legge il dizionario con `dictionary.load(app.db)` quando si apre (cursore di attesa) e non scrive mai: nessuna chiave Azure. E' registrato in `default_tools()` con `requires=('FW_TABLES', 'FW_TABLE_FIELDS')`, quindi senza quelle tabelle la scheda e' spenta. I test dell'interfaccia di Strings usano `strings_only()` (con due strumenti il passo 2 e' il guscio).

**Names e Indexes.** `jt/names.py` (senza interfaccia, portato da JCTNT `fuzzy-search.js` e `app.js`): `score_table` (esatto 1000, inizia con 500-900, contiene 200-500, simile fino a 100), `best_table_matches` (esatti e suggerimenti; una tabella fisica con piu' nomi logici compare una volta, i descrittori senza tabella `'-'` restano separati), `table_rows`, `search_fields` (con le righe `notFound`), `sort_key`, `tsv` e le regole sugli indici (`pick_index_owner`, `table_indexes`, `indexes_text`). `jt/indexes.py` legge da `ALL_INDEXES` e `ALL_IND_COLUMNS` solo la tabella chiesta (JCTNT leggeva tutti gli indici del database alla connessione: decine di migliaia di righe). Interfaccia: `ui/names_screen.NamesScreen` e `ui/indexes_screen.IndexesScreen`, con i pezzi in comune `ui/dictionary_bar.DictionaryBar` (la riga del dizionario con Reload), `ui/table_picker.TablePicker` (il nome della tabella con i suggerimenti) e `ui/datatable.DataTable` (tabella che si ordina e si copia). `JTApp.current_table` e' l'ultima tabella cercata in Names: Indexes la propone alla sua apertura (`ToolsScreen` chiama `on_show` dello strumento che si apre). Le ultime ricerche stanno in `search_history.json` (`Settings.search_history`, `add_search`; dato personale, non va nel pacchetto ne' su git). Il simulatore ha `ALL_INDEXES` e `ALL_IND_COLUMNS` (`SIM_SCHEMA`: non nello schema di create_test_db, in un Oracle vero nasconderebbero le viste) con righe di prova e, con `--fw`, quelle vere.

**Finestra ridimensionabile.** `ScrollArea` stira il contenuto in altezza quando la finestra e' piu' alta (`refresh()`, chiamato da `fit_window`) e ha la barra solo se non entra; `Collapsible(grow=True)` fa crescere una sezione (i risultati); `ScrolledText` e' un campo di testo con la sua barra che compare solo se serve; in SQL <> TecSQL un `ttk.PanedWindow` divide Query e Result con un divisore. `JTApp.fit_window` non rimpicciolisce una finestra messa a mano (`user_sized`, rilevato dal `<Configure>` di una misura diversa da quella data da fit_window) e a tutto schermo non tocca la geometria.

**Aggiungere un livello alla finestra.** I livelli sono gia' tutti in `jt/layers.py`: basta aggiungere il suo nome a `VISIBLE`.
Per i livelli la tabella dice come filtrare (`level_condition`), di che livello e' una riga (`layer_of_row`) e con quale utente si
scrive (`user_sql`); le tabelle senza livelli (`supports_levels = False`) ignorano la scelta.

**Disabilitare/riabilitare una tabella.** `"enabled": false` in `Data/tables.json` (se il campo manca la tabella e' attiva).

**Aggiungere un termine al glossario.** `Data/glossary.json`: `replace` (sostituzione) o `keep` (non tradurre).
`replace_skip_targets` elenca le lingue di destinazione dove le sostituzioni non valgono (oggi `it`).

**Cambiare il logo.** Una riga in `jt/config.py`: `ICON_NAME = 'bubbles'` (oppure `'pixel_cube'`, `'pixel_block'`: i file sono in `Graphics/icons/`).
Per ridisegnarli: `tools/make_icons.py`; per i pallini dei passi: `tools/make_step_badges.py`.

**Cambiare colori, font o pulsanti.** `jt/ui/theme.py` (`PALETTE`, stili `Primary`, `Secondary`, `Small.*`).

**Cambiare un testo o l'ordine dei campi.** `jt/ui/connection_screen.py` o `jt/ui/translation_screen.py`.

**Cambiare la stima della durata o il marcatore scritto nel DB.** `jt/config.py` (`SECONDS_PER_ROW`, `DB_MARKER`).

## Regole che il codice rispetta (e i test verificano)

- Tutti i valori nelle query (lingue, limite, chiavi, testi) sono **bind variable**: apici e caratteri speciali non rompono nulla.
- Una `Selection` ricorda tabella e lingue con cui e' stata caricata: "Translate" usa quelle, mai i campi di quel momento.
  Ogni modifica ai campi rende la selezione non valida e disabilita "Translate".
- La connessione si chiude sempre: nuovo "Connect", "New connection", chiusura della finestra (anche durante una traduzione) e
  uscita per errore (`app.shutdown()`).
- Un campo vuoto diventa `NULL`, mai la stringa `'None'`.
- La traduzione gira in un thread (`runner.py`): la finestra resta viva e c'e' il pulsante **Stop**. Il thread non tocca mai Tkinter:
  l'interfaccia legge l'avanzamento da una coda ogni 100 ms. Mentre il thread lavora, nessun altro codice usa la connessione.
- Ogni chiamata ad Azure ha un timeout (`AZURE_TIMEOUT`): una chiamata bloccata non blocca piu' l'app.
- Le misure in pixel dell'interfaccia passano da `px()` (`ui/scale.py`); i font seguono Tk. `JT.py` dichiara l'app "DPI aware" prima di aprire la finestra.
- In basso, `InfoBar` mostra sempre a quale database si e' collegati (nome dichiarato dal server, host, utente).
