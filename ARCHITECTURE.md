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
  layers.py               livelli di Jflex (FW, AP, CW, CT, CK, CC): intervalli dei codici, prefissi dei nomi, utente scritto, livelli visibili
  tables.py               UNA CLASSE PER TABELLA: SQL di selezione (anche per livello), traduzione di una riga, INSERT, UPDATE
  db.py                   connessione Oracle, cursori, metadati (niente logica di traduzione)
  service.py              il lavoro: sceglie le righe, traduce, scrive (INSERT o UPDATE), avanzamento
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

**Sezioni che si aprono e si chiudono.** I blocchi del passo 2 (LANGUAGES, WHAT TO TRANSLATE, PROGRESS) e "Advanced" (Max rows,
Update by keys) e "Details" (tempi) sono `Collapsible` (`ui/widgets.py`): chiuse mostrano solo la riga con un riassunto
(`TranslationScreen._update_summaries`). Nel passo 1 il banner (`StatusBar(closable=True)`) compare solo quando succede qualcosa. Ogni apertura o chiusura fa riadattare la
finestra (`app.fit_window`); se non entra nello schermo compare la barra di `ScrollArea`.

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
