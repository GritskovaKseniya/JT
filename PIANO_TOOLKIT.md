# Piano: JTools (JT + JCTNT) e uso da parte dei consulenti

Stato: **piano, nessun codice scritto**. Si decide e si fa **una cosa alla volta**: ogni passo si puo' rilasciare da solo.
Documento gemello di `PIANO_3.1_LIVELLI.md` (stesso schema: cosa, dove, test prima, controllo).

## 1. Cosa vogliamo

1. **Un'unica app desktop** (stile JT), che si chiamera' **JTools**, con piu' strumenti: oggi il traduttore di stringhe (JT) e, in
   piu', quelli di JCTNT (traduttore SQL <-> TecSQL, ricerca nomi fisico/logico, tabella, indici). Una connessione sola, un solo zip.
2. **Un uso sicuro da parte dei consulenti**, senza un'edizione separata: **senza chiave Azure non si scrive niente**. Chi non ha la
   chiave usa gli strumenti di lettura (si apre il traduttore SQL); chi serve davvero, dopo una formazione, riceve la chiave.
3. **Piu' sicurezza quando si scrive sul database** (per chi ha la chiave): anteprima, conferma, annullamento.

### Decisioni prese (da te)

| # | Decisione |
|---|---|
| 1 | Un'app sola con piu' strumenti (non due app); JCTNT si porta in Tkinter, non resta web |
| 2 | Il database "di dato" e' quello su cui **si scrivono le righe** (FW_STRINGS...): li' serve piu' attenzione |
| 3 | Capire lo strumento giusto **dalle tabelle che esistono** sul database |
| 4 | Nome del prodotto: **JTools** (gli strumenti dentro si chiamano per funzione: "Strings", "Names & SQL") |
| 5 | **Niente chiave Azure ai consulenti**: la chiave e' l'abilitazione a scrivere; gli strumenti di lettura funzionano senza. Chi la riceve e' formato. Nessuna edizione separata, per ora |
| 6 | Quello che si fa sul database con altri programmi non e' sotto la responsabilita' di JTools: l'app garantisce solo le proprie scritture |
| 7 | Anteprima (dry run) e log con annullamento: si fanno |
| 8 | Il livello **CC** (oggi nascosto e non rifinito) si completa: e' un passo di questo piano |
| 9 | I consulenti sono interni, ma si sta comunque attenti |
| 10 | Test: **unittest** (si portano i test di JCTNT da pytest a unittest) |
| 11 | Driver Oracle e le altre questioni tecniche: una alla volta, quando arriva il passo (capitolo 8) |

## 2. Come l'app capisce dove si trova e cosa puo' fare

Controlli indipendenti, dal piu' sicuro:

| Livello | Cosa controlla | Come | Cosa succede |
|---|---|---|---|
| **A. Chiave Azure** | si puo' tradurre (e quindi scrivere)? | all'avvio: il file della chiave esiste, non e' il segnaposto e ha la forma giusta | **senza chiave lo strumento Strings e' spento con il motivo** (`no Azure key: ask <referente>`); si apre lo strumento di sola lettura. Gia' oggi JT dice `Azure settings not found or not valid` solo al momento di tradurre: si anticipa |
| **B. Tabelle presenti** (la tua idea) | quali strumenti hanno senso su questo database | ogni strumento dichiara le tabelle che richiede; dopo il Connect si fa `SELECT ... WHERE ROWNUM = 1` come fa gia' JT | strumento senza le sue tabelle: **spento con il motivo** (`needs FW_STRINGS: not found`), non sparito |
| **C. Etichetta dell'ambiente** | e' un database dove scrivere con cautela? | ogni connessione salvata ha `env`: `dev` / `test` / `prod`, scelta una volta nella schermata di connessione; resta visibile (pallino colorato in basso) | `prod` o etichetta vuota (= trattata come prod): scrivere chiede una conferma piu' forte |
| **D. Permessi del database** (se il DBA li concede) | l'utente puo' scrivere? | si leggono i privilegi (`all_tab_privs`); se non si capisce, non si blocca | se manca INSERT/UPDATE: strumento Strings in sola lettura. Non e' richiesto: il DBA probabilmente non lo fara', e per questo c'e' la chiave |

Strumenti di sola lettura (SQL <-> TecSQL, nomi, tabella, indici) sono sicuri ovunque. Lo strumento che scrive usa A, B e C (e D se c'e').

**Limite dichiarato:** la chiave abilita JTools, non protegge il database. Scritture fatte con altri strumenti (SQL Developer...) non
dipendono da JTools e non sono sotto la sua responsabilita'. La chiave e' un file in chiaro: chi ce l'ha potrebbe passarla; se serve
si cambia la chiave in Azure (e si ridistribuisce solo a chi e' formato).

## 3. Architettura

```
jt/                         (il nome del repository si cambia dopo: JTools)
  core/    config, db, jsonstore, settings, logs, layers, runner     <- gia' senza Tkinter
  tools/
    strings/                tables, service, translation_screen          <- l'attuale JT
    names/                  dictionary, tecsql_translator, schermate      <- da JCTNT
  ui/      theme, widgets, app (guscio), connection_screen
```

**Registro degli strumenti** (`Tool`): nome, titolo, `requires` (tabelle), `writes` (True/False), schermata. Dopo il Connect il guscio
mostra gli strumenti e spegne quelli che non possono funzionare (senza tabelle, senza chiave), spiegando perche'. Lo strumento
che si apre da solo e' il primo **acceso**: senza chiave e' il traduttore SQL.

**Distribuzione:** lo zip di tutti e' **senza chiave** (il segnaposto che c'e' gia' con `--no-azure`); a chi e' formato si consegna a
parte il file `azure_services.json` da mettere in `%LOCALAPPDATA%\JT`. Cosi' la chiave esce anche dagli zip che girano.

**Limiti facoltativi per chi ha la chiave** (rimandati, si aggiungono se servono): massimo di righe per corsa (es. 200), anteprima
obbligatoria, livelli ammessi (es. solo CT e CC). Sarebbero impostazioni nel servizio (`policy.py`), non un'altra edizione:
oggi non servono, la formazione e gli altri controlli bastano.

## 4. Anteprima e conferma: cosa devono guardare

**Anteprima (dry run).** Dopo **Load** c'e' il pulsante **Preview**: traduce **senza scrivere** e mostra una tabella:

| Codice | Livello | Testo di partenza | Traduzione | Azione | Utente |
|---|---|---|---|---|---|
| 3000001 | CT | Etichetta personalizzata | Etiquette personnalisee | INSERT | ZFXCUSTOM |
| 3000003 | CT | Campo extra | Champ supplementaire | UPDATE (prima: "Champ en plus") | ZFXCUSTOM |
| 3000009 | CT | (vuoto) | - | SKIP | |

**Cosa devono guardare:**
1. **Le traduzioni hanno senso** (Azure puo' sbagliare; il glossario sostituisce UMV -> HU...).
2. **Livello e utente sono quelli attesi** (CT -> `ZFXCUSTOM`, CC -> `ZFXCCSYS`), e il database e' quello giusto (nome ed etichetta
   in basso).
3. **Le righe UPDATE**: sostituiscono un testo che c'era gia'; si vede il vecchio accanto al nuovo.
4. **Il riepilogo** (`24 righe, 22 INSERT, 1 UPDATE, 1 saltata`) e che il numero sia quello che si aspettano.

Poi **Write** scrive esattamente quelle traduzioni. **Le traduzioni dell'anteprima si conservano in memoria: scrivere non richiama
Azure.** Azure fattura i **caratteri tradotti** (non le chiamate): tradurre due volte costerebbe il doppio, cosi' si paga una
volta sola. Facoltativo: modificare una traduzione nella tabella prima di scrivere.

**Conferma prima di scrivere:** `Scrivere 24 righe in <database> (ambiente: test), livello CT, utente ZFXCUSTOM?`
Su `prod` o con etichetta vuota: bisogna scrivere il nome del database per confermare. La traduzione diretta (come oggi, senza
anteprima) resta disponibile a chi ha la chiave, finche' non si decide di rendere l'anteprima obbligatoria (capitolo 3).

## 5. Log con annullamento

I log CSV hanno gia' livello e utente. Si aggiunge `old_output` (il testo che c'era prima, per gli UPDATE) e un pulsante
**Create undo script** che scrive `undo_<data>.sql`: un `DELETE` per ogni riga inserita e un `UPDATE` che rimette il testo vecchio
per ogni riga aggiornata (apici raddoppiati con cura). Si lancia in SQL Developer, o piu' avanti da JTools stesso.
**Prova col simulatore:** si traduce, si esegue lo script, si confronta il database con la copia di prima.

## 6. Livello CC

Oggi CC e' nelle regole (`layers.py`: codici da 9000000, prefisso `Cc`, utente `ZFXCCSYS`) ma nascosto e **non scrive l'utente
giusto** (`USER_FROM_LAYER` ha solo CT e CW). Da fare: aggiungere CC all'utente scritto, un titolo (`CC - Customer
descriptors`), renderlo visibile (`VISIBLE`), verificare le regole di Orione (`LayerCC.java`: intervallo vero 9000000-1999999999 o
9000000-9999999? categoria? permessi), provare sul simulatore con le righe vere (nel database di prova ci sono 150 stringhe e 50
triplette CC) e aggiornare i test.

## 7. JCTNT in Tkinter: cosa si porta

Letto in `E:\Sviluppo\Development\JCTNT`: `app.py` (Flask, ~330 righe), `tecsql_translator.py` (~1000 righe, Python puro),
3 file di test (562 righe, pytest usato pochissimo: `assert` semplici e una sola fixture), `index.html` + `app.js` (~800 righe) +
`fuzzy-search.js` (~270), `style.css`. Il dizionario si carica con 3 `SELECT` (FW_TABLES + FW_TABLE_FIELDS, ~36.000 righe; indici da
`all_indexes`/`all_ind_columns`) e si tiene in memoria finche' la connessione e' la stessa.

| Nel web | In Tkinter |
|---|---|
| Flask + REST | **sparisce**: la schermata chiama direttamente il codice |
| `tecsql_translator.py` (mappe globali) | si porta com'e' (passo 7); poi si trasforma in una classe `Dictionary` senza stato globale |
| connessione + dizionario in cache | la schermata di connessione di JT + `Dictionary` caricato una volta, condiviso dagli strumenti |
| storico connessioni / ricerche | elenco di **profili di connessione** (con l'etichetta `env`) + elenco ricerche recenti |
| schede (Ricerca, Translator, Tabella, Indici) | `ttk.Notebook` |
| card comprimibili | le nostre `Collapsible` |
| tabella risultati, clic = copia cella, Copia tutto (TSV), ordina | `ttk.Treeview` con ordinamento sull'intestazione, copia cella (clic destro / Ctrl+C), Copia tutto |
| suggerimenti "fuzzy" (Levenshtein) | campo di testo + elenco a comparsa; algoritmo portato in Python (specifica in `docs/FUZZY_SEARCH_FEATURE.md`) |
| area SQL in/out | due `Text` monospazio, pulsanti di direzione, copia |

Il simulatore si estende con FW_TABLES, FW_TABLE_FIELDS e gli indici, cosi' anche questi strumenti si provano senza Oracle (e con
una piccola copia delle righe vere, in sola lettura, come per le stringhe).

## 8. Passi (ordine consigliato) e decisioni da prendere una alla volta

La fase A rende **piu' sicuro JT** e si usa subito; la B e' piccola; la C e' l'unione. Ogni passo = una versione.

### Fase A - Sicurezza di JT (3.2)
- **Passo 1 - Anteprima** [grande]: `service.preview` (traduce senza scrivere, conserva i risultati), `service.write` (scrive quelli),
  `run` resta come oggi (= preview + write). Schermata: pulsante Preview, tabella (Treeview), riepilogo. *Test prima:* nessuna
  scrittura durante la preview; Azure chiamato una volta sola; il database dopo Write e' uguale a quello della traduzione diretta.
- **Passo 2 - Conferma ed etichetta ambiente** [medio]: `env` nei profili di connessione, pallino colorato nella riga in basso,
  testo di conferma con riepilogo, conferma forte su prod/vuota. *Test:* ogni combinazione etichetta/conferma.
- **Passo 3 - Log con annullamento** [medio]: `old_output`, generatore dello script, pulsante. *Test:* col simulatore, eseguire lo
  script riporta il database com'era (INSERT e UPDATE, apici, accenti, triplette).
- **Passo 4 - Livello CC** [medio]: capitolo 6.

### Fase B - La chiave abilita la scrittura (3.3)
- **Passo 5 - Senza chiave non si scrive** [piccolo]: controllo della chiave all'avvio (assente, segnaposto, forma sbagliata), Strings
  spento con il motivo, si apre lo strumento di lettura; zip di tutti **senza chiave** (`release.bat --no-azure` diventa la regola; si
  aggiorna `RILASCIO.md`: la chiave si consegna a parte, a chi e' formato); testo per i consulenti. *Test:* ogni caso della chiave;
  nessun percorso di scrittura raggiungibile senza chiave (Load, Update by keys, Translate).
  Facoltativo, solo se servira': limiti per chi ha la chiave (Max rows, anteprima obbligatoria, livelli ammessi).

### Fase C - Unione in un'app sola: JTools (4.0)
- **Passo 6 - Registro strumenti e guscio** [medio]: scelta dello strumento dopo il Connect, strumenti spenti (tabelle mancanti,
  chiave mancante) con il motivo, profili di connessione. L'attuale JT diventa lo strumento "Strings".
- **Passo 7 - Nucleo di JCTNT** [medio]: `tecsql_translator.py` + caricamento del dizionario tramite `jt.db.Database`; test portati
  a `unittest` (sono 3 file di 562 righe, la traduzione e' meccanica: fixture -> `setUp`).
- **Passo 8 - Schermata SQL <-> TecSQL** [medio]: la piu' usata, e quella che si apre senza chiave.
- **Passo 9 - Ricerca nomi con suggerimenti** [grande]: tabella copiabile, fuzzy.
- **Passo 10 - Tabella e Indici** [grande].
- **Passo 11 - Rilascio e documenti** [piccolo]: un solo `release.bat`, guida per chi ha la chiave e per chi no.

### Decisioni aperte (una alla volta, quando arriva il passo)

| Quando | Decisione | Consiglio |
|---|---|---|
| Passo 7 | **Driver Oracle**: `cx_Oracle` (JT) o `oracledb` (JCTNT)? | Per ora **resta cx_Oracle**: il codice portato usa il `Database` di JT e non serve `oracledb`. Passare a `oracledb` (cx_Oracle e' dichiarato obsoleto) e' un passo a parte, da fare solo quando serve; va verificato che `connect(..., threaded=True)` funzioni uguale |
| Passo 7 | Client Oracle: JCTNT ha il percorso scritto nel codice (`C:\App\Oracle11\clix64\client\bin`) | non si porta: JT usa il client nel PATH o la cartella `oracle_client` accanto al programma |
| Passo 1 | Si puo' modificare una traduzione nella tabella prima di scrivere? | utile ai consulenti formati: si aggiunge dopo la prima versione |
| Passo 5 | Chi e' il referente della chiave e come si consegna? | nel messaggio che compare senza chiave (`ask <referente>`); la consegna e' un file |
| Passo 6 | Il repository e le cartelle (`jt/`) si rinominano? | dopo, a prodotto finito: il nome in finestra e nello zip si cambia prima |

## 9. Rischi

- **Azure puo' sbagliare** e chi ha la chiave non se ne accorge: per questo c'e' l'anteprima e la formazione.
- **La chiave non e' una barriera del database:** altri programmi possono scrivere senza JTools (non e' una sua responsabilita'). Se in
  futuro il DBA concede un utente con permessi minimi, il livello D lo usa.
- **La chiave e' un file in chiaro:** chi ce l'ha puo' passarla; si cambia in Azure e si ridistribuisce solo ai formati.
- **Etichetta ambiente sbagliata o dimenticata:** vuota = prod (la scelta prudente).
- **Il programma cresce:** ogni strumento e' un modulo con i suoi test e non conosce gli altri (il guscio li conosce).
- **Il piano di unione e' lungo** (fase C): la A e la B si usano subito, anche se la C non si fa mai.
- **Lo script di annullamento non e' una transazione:** se nel frattempo qualcuno ha modificato le stesse righe, lo script le
  sovrascrive; va lanciato subito e con attenzione (e mostra cosa fa prima di farlo, se eseguito da JTools).

## 10. Risultati e note (da compilare)

### Passo 1 - Anteprima: fatto (2026-11-04)

- `service.preview` traduce senza scrivere e conserva i risultati (`Preview` / `PreviewRow`: INSERT, UPDATE con il testo di prima,
  SKIP con il motivo); `service.write` scrive quei risultati senza richiamare Azure; `run` (Translate diretto) non cambia.
- Finestra: pulsante **Preview**, tabella PREVIEW (Treeview, prime 500 righe, UPDATE evidenziati, dettaglio della riga), **Write** e
  **Discard**; dopo una Preview Translate e Preview sono spenti (tradurre di nuovo costerebbe il doppio); Discard e un campo
  cambiato cancellano l'anteprima; le righe di un Load si leggono una volta sola, quindi dopo Discard si ricarica.
- Provato: test del servizio e della finestra, e lo scenario del simulatore (nessuna modifica dopo Preview; stesso database della
  traduzione diretta; UPDATE con il testo di prima; Azure chiamato una volta).
- **Idee per dopo** (non fatte): l'anteprima non conosce i limiti delle colonne (un testo piu' lungo di `value` 255 o `caption`
  100 si scopre solo scrivendo, `ORA-12899` nel log): si potrebbe segnarlo gia' in tabella leggendo le lunghezze da
  `cursor.description`; modificare una traduzione nella tabella prima di scrivere; la conferma con riepilogo (passo 2).

### Passo 2 - Conferma ed etichetta ambiente: fatto (2026-11-04)

- `jt/environments.py`: `dev` / `test` / `prod`; non impostata (o sconosciuta) vale come prod (`is_strict`). L'etichetta si sceglie nella
  schermata di connessione (campo **Environment**), si ricorda **per database** (host, porta, SID; maiuscole e spazi non contano) dentro
  il file dei dati di connessione (non serve un file nuovo: gia' escluso da git e dallo zip), si propone da sola quando si scrive
  un database gia' noto e si puo' cambiare anche da collegati.
- Segno colorato a destra della riga in basso (DEV blu, TEST verde, PROD rosso, NOT SET arancione) e riga `Environment` nel suggerimento.
- Conferma prima di **Translate** e **Write** (non prima di Preview), **solo su prod e non impostata** (su dev e test non si chiede
  niente: scelta di Kseniia dopo aver provato la prima versione, che la chiedeva ovunque): riepilogo con database, ambiente,
  lingue, livello, utenti scritti, INSERT/UPDATE; il pulsante si accende solo scrivendo il nome del database. Annullare non traduce
  e non scrive (quindi non costa); la selezione e l'anteprima restano.
- Trovato dai test: i gestori delle variabili di Tk non hanno un ordine garantito, e cambiando il SID da collegati la proposta della
  nuova etichetta poteva cancellare quella del database vecchio: la proposta del programma non si salva mai (`_refilling`).
- **Idee per dopo:** chiedere conferma anche per la sola "traduzione diretta" con meno righe (soglia)? un elenco di profili di
  connessione con l'etichetta (passo 6).

(scrivi qui le altre decisioni passo per passo e cio' che si scopre)
