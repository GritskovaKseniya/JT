# JT - Jflex Translator: test

Ultimo aggiornamento: 2026-11-03 (livelli CT/CW, utente e categoria, log con livello e utente, simulatore di Oracle)

## Come eseguire i test automatici

Doppio clic su `run_tests.bat`, oppure dalla cartella del progetto:

```
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Solo libreria standard (`unittest`). Oracle e Azure sono **simulati**: nessuna connessione, nessuna chiamata di rete, nessuna
credenziale reale. Ogni test lavora su una copia temporanea di `Data` (con credenziali finte) e scrive i log CSV in una cartella
temporanea: i file del progetto non vengono toccati. I test dell'interfaccia (`test_ui.py`) usano una vera finestra Tk
nascosta e vengono saltati se non c'e' un display. Durata: circa 40 secondi.

## Risultato (2026-11-03)

```
Ran 839 tests in ~95 s
OK
```

Eseguiti anche con i `ResourceWarning` trattati come errori.

| File | Test | Cosa verifica |
|---|---|---|
| `test_glossary.py` | 27 | Termini sostituiti (UMV -> HU) e non tradotti; termine da solo senza chiamare Azure; termine dentro una frase protetto e poi ripristinato (`& < >` compresi); solo parola intera; qualsiasi lingua sorgente (anche de -> es); verso l'italiano UMV resta; file mancante/rotto tollerato; regole del `glossary.json` consegnato |
| `test_tables.py` | 72 | `Catalog` (tabelle abilitate, FWK disabilitata); chiavi di "Update by keys" per ogni tabella; per **ogni** tabella SQL di selezione/conteggio/chiavi (lingue e limiti sempre come bind variable), traduzione di una riga, INSERT e UPDATE esatti (campo vuoto = `NULL`, apici nei bind, marcatore `JT`, colonne utente/data solo se la tabella ha la forma attesa); `Settings`, `Paths` |
| `test_database.py` | 27 | Connessione e chiusura (ricollegare chiude la precedente, chiusura ripetibile e tollerante agli errori); nomi colonna letti dal cursore e messi in cache; tabelle esistenti; cursori tracciati |
| `test_service.py` | 108 | Selezione (righe mancanti e per chiavi, conteggio dei caratteri come somma, cursori vecchi chiusi); esecuzione in modalita' normale e per chiavi (INSERT oppure UPDATE), log, errore Azure = riga saltata, errore di INSERT = log errori e si prosegue, commit a ogni riga, avanzamento, arresto richiesto; log CSV; rollback dopo un errore di scrittura o di commit; righe saltate registrate in un log a parte; chiavi con zeri iniziali |
| `test_support.py` | 40 | Esecuzione in un thread (`BackgroundRunner`, `InlineRunner`: eventi, errori, Stop, un solo lavoro alla volta); testi (`fmt_count`, `shorten` mai oltre il limite, `reason`); informazioni sulla connessione (nome del database dichiarato dal server, password mai conservata); limite delle chiavi; timeout di Azure; cartella dei log creata e nomi unici; `JT.py` dichiara la scala dello schermo prima di aprire la finestra e chiude la connessione anche in caso di errore |
| `test_regressions.py` | 6 | Cifre simili a numeri (`²`) rifiutate, JSON che non e' un oggetto tollerato, log con caption se manca la descrizione, testo di soli spazi non inviato ad Azure |
| `test_ui.py` | 447
| `test_undo.py` | 19 | Script di annullamento: costanti SQL (apici raddoppiati, `&` lasciata stare, UNISTR per accenti/hindi/a capo/emoji, backslash protetta, date), nomi di tabella e colonna controllati (niente iniezioni), DELETE per gli INSERT e UPDATE per gli UPDATE (NULL compreso), intestazione, `SET DEFINE OFF`, `COMMIT`, ordine inverso, solo ASCII |
| `test_environments.py` | 13 | Etichette dell'ambiente: solo dev/test/prod valide, non impostata e sconosciuta valgono prod, riconoscere un database senza badare a maiuscole e spazi, segno colorato; come si ricordano nelle impostazioni (per database, senza cancellare i dati di connessione, file rotto tollerato); utenti scritti per livello |
| `test_layers.py` | 8 | Livelli: confini degli intervalli dei codici (2999999 Standard, 3000000 CT, 4999999 CW...), codice fuori livello = errore, nome dell'opzione dal prefisso (maiuscole contano, prefisso scritto male = nessun livello), livelli visibili |
| `test_simulator.py` | 28 | Simulatore di Oracle: riscrittura SQL (sysdate, ROWNUM, COUNT con limite), `LIKE` che distingue le maiuscole, `ORA-12899`, `ORA-01400`, righe lette che sopravvivono a un rollback, e tutti gli scenari (livelli, utente, categoria, Update by keys, errori) |
| `test_release.py` | 16 | Procedura di rilascio: controllo dello .zip (file mancanti, dati personali, README/TestDB che non devono esserci, chiave Azure vera o segnaposto), cambio versione |
| `test_testdb.py` | 28 | Database di prova: ogni tabella abilitata ha schema e righe, una riga ha tanti valori quante colonne, c'e' sempre qualcosa da tradurre (verificato con le query di JT su SQLite) e qualcosa gia' tradotto, casi particolari presenti; non tocca tabelle esistenti, `--recreate` solo su un suo database, crea `JTTEST` solo con l'amministratore, connessioni sempre chiuse, nomi non validi rifiutati; righe di prova per i livelli; **righe vere** copiate da un database (`with_sample`: righe aggiunte, chiavi duplicate saltate, date riconvertite, tabelle di forma diversa ignorate, simulatore e JT che funzionano sulle righe vere); `extract_sample.py` (valori puliti, solo `SELECT`, una tabella illeggibile non ferma le altre, il file dei dati e' in `.gitignore`)

### Cosa copre `test_ui.py`

Passo 1 (connessione, Invio, "Connecting...", errore con motivo accorciato, password nascosta, modifica dei campi dopo la connessione) e riga del database in basso; pannello dei passi
(pallini a immagine, scelti in base alla scala); passo 2 (tabella salvata ma disabilitata non selezionata, conteggi con avvisi, suggerimenti); **selezione obsoleta** (ogni modifica
ai campi disabilita Translate: non si scrive mai nella tabella sbagliata); "Max rows" (solo cifre, minimo 1); Load (righe mancanti e chiavi); traduzione dall'interfaccia con
esecuzione sincrona **e con un vero thread** (la finestra resta viva, avanzamento, **pulsante Stop**, campi bloccati, log nella cartella `Logs`, riepilogo); chiusura (da fermo chiude subito senza chiedere, anche dalla X o dal pannello di Windows; durante una traduzione
chiede conferma; errore in `close()`, una sola conferma alla volta, traduzione che continua mentre la conferma e' aperta); finestra di conferma compatta, senza logo, con lo stesso
titolo della finestra principale, Invio sul pulsante con il focus ("Keep translating" di default), Esc/X = annulla; finestra ridimensionabile, mai in primo piano, mai oltre il bordo basso; testi che
vanno a capo; banner che cresce col testo; contrasti WCAG; scala dello schermo a 100/125/150/200%; messaggio nascosto non bloccante; i loghi (tre scelte, quella configurata esiste,
tutte le dimensioni, ogni voce `.ico` e' un PNG della propria dimensione) e la cartella `Graphics` con solo i file usati; **ordine delle lingue** (italiano, inglese, poi A-Z; da = italiano, a = inglese; scelta salvata
che vince); testi ("1 row", "less than a minute"); **passaggi fra i passi senza scatti** (Next e New connection: una sola misura finale, la finestra non si sposta di lato, il passo nuovo si
costruisce prima di togliere il vecchio, niente schermate accumulate, stepper e riga del database mai ricostruiti, il conteggio che arriva dopo non ridimensiona).

### Verifica dei test (mutation check)

Per essere sicuri che i test servano davvero, il codice viene rotto di proposito in una copia, un punto per volta (41 rotture: connessione non chiusa, marcatore sbagliato, apici
di nuovo nell'SQL, update che fa sempre INSERT, selezione che non si invalida, Stop che non ferma, nessun timeout, finestra di nuovo in primo piano, scala dello schermo ignorata, ecc.).
Risultato: vedi sotto.

MUTATION_RESULT

Difetti trovati dai test durante lo sviluppo: il font del menu a discesa scritto in modo che Tk lo leggeva male; un errore sui nomi colonna di un sinonimo Oracle (visto dal tuo screenshot);
la riga del database che restava su "Connected" dopo una riconnessione fallita; i messaggi accorciati oltre il limite; il log perso se la corsa si interrompeva.

## Gia' verificato a mano

| Cosa | Esito |
|---|---|
| Codice originale ricostruito dal bytecode dell'exe | Identico: 30 funzioni su 30 |
| Aspetto delle schermate, banner, finestra di uscita, logo, riga del database, a 100/125/150/200% (catture della finestra) | OK; a 200% su uno schermo alto 1440 px la finestra e' piu' alta dello schermo (vedi `UX_REVIEW.md` punto 14) |
| Prova tua sul DB demo (screenshot): connessione, conteggi, traduzione di righe | Funziona (es. 21.177 mancanti in `FW_STRINGS`, riga "Connected to orcl") |
| Le immagini si rigenerano identiche con `tools/` | OK: 19 file su 19 uguali byte per byte |

## Da fare (richiedono il DB e Azure veri)

Fare le prove su un DB di test/demo: il tool scrive con `commit` a ogni riga e ogni traduzione e' una chiamata Azure a pagamento.

- [ ] **Connessioni davvero chiuse**: dopo "New connection" e dopo la chiusura dell'app, controllare in `v$session` che la sessione di JT non resti.
- [ ] **Stop e chiusura durante una traduzione su DB reale**: la riga in corso viene finita e la connessione si chiude; usare la connessione da un thread diverso da quello che l'ha aperta con `cx_Oracle` e' previsto, ma va visto dal vivo.
- [ ] **Glossario con Azure vero**: una riga con "UMV" dentro una frase (esce "HU"?) e con "Supply Chain Planning" (resta uguale?); anche con sorgente non italiana.
- [ ] Update per chiavi: id esistente (UPDATE, `action` = `update`), id mancante (INSERT), `ProcessiLunghi` su `FW_OPZIONI_TRE`.
- [x] `FW_DOCU_NODES_T`: verificata sul DB vero (3 colonne `NODEID`, `LANG`, `NODETITLE`). Con l'INSERT a 4 valori fallivano tutte le righe (`ORA-00913`): ora l'INSERT nomina le colonne.
- [ ] `FWK_STRINGS`: nomi colonna `pack`, `code`, `lang`, `value`, `short_value`, `long_value`; colonne utente/data (oggi non scritte in update).
- [ ] `FW_OBJ_DESCRS`: traduzione piu' lunga di 100 caratteri e lingue con codice di 2 lettere.
- [ ] `ROWNUM` con `NOT EXISTS`: "Max rows" rispettato davvero e stima dei caratteri.
- [ ] Una chiamata Azure che non risponde: dopo il timeout (5 s + 30 s) la riga viene saltata e la corsa prosegue.
- [ ] Nitidezza e dimensioni su altri monitor/scale (la finestra scala a 100-200% ma non si adatta se la si sposta tra due monitor con scale diverse).

## Limiti noti

- I log CSV sono scritti in UTF-8 con BOM (Excel legge bene gli accenti); con Excel in italiano il separatore e' il punto e virgola, quindi un CSV con la virgola si apre in una sola colonna (Dati > Da testo/CSV).
- Una riga con testo sorgente vuoto in `FW_STRINGS` o in `FW_OPZIONI*` viene saltata (non c'e' niente da tradurre); nelle altre tabelle il campo vuoto resta `NULL`.
- **Marcatore nel DB**: ogni INSERT scrive la costante `'JT'` nella colonna "utente" della riga (accanto a `sysdate`), per riconoscere le righe tradotte dal tool. Prima della rinomina il
  tool scriveva il vecchio nome (`JCT`): le righe gia' tradotte hanno il vecchio valore, le nuove `JT`. Report e query che cercano le righe tradotte dal tool devono cercare entrambi.
- `FWK_STRINGS` (SFC) e' disabilitata in `tables.json`; il codice resta e si riattiva con `"enabled": true`. In update non scrive le colonne utente/data.
- Una descrizione tradotta piu' lunga di 100 caratteri non entra in `FW_OBJ_DESCRS`: l'INSERT fallisce e la riga va nel log errori.
- I log CSV sono nella cartella `Logs` del progetto; quelli vecchi scritti nella cartella principale (`JT_*_log_*.csv`) sono di prove precedenti.
- Con un DB lento l'apertura del passo 2, il caricamento e il conteggio bloccano ancora la finestra (vedi `UX_REVIEW.md` punto 3).
