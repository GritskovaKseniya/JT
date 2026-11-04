# JT 3.1: traduzione per livello (Standard / CW / CT ...)

Piano di sviluppo, scritto per essere seguito **a mano, un passo alla volta**, lavorando in Python. Ogni passo dice: cosa fare,
dove, cosa ripassare di Python, il test da scrivere **prima**, come controllare.

Stato: solo piano. Nessuna riga di codice e' stata scritta per questa funzione.

## 1. Cosa vogliamo

Nel passo 2 un nuovo campo **Level**: si sceglie quali stringhe tradurre. Oggi JT traduce tutto quello che manca, di tutti i
livelli mescolati. In Jflex (Orione) esiste gia' la stessa idea (`TranslateStringsApp`, `TranslateTripletsApp`,
`TranslateOpzioniApp`), quindi seguiamo le sue regole.

## 2. Decisioni prese

| # | Argomento | Decisione |
|---|---|---|
| 1 | Versione | 3.1 |
| 2 | Livelli nel codice | **Tutti**: FW, AP, CW, CT, CK, CC |
| 3 | Livelli visibili nel menu | Solo **All / Standard / CW / CT** (gli altri nascosti, si accendono cambiando una lista) |
| 4 | Valore iniziale | **Standard** (non piu' All: attenzione, e' un cambio rispetto alla 3.0) |
| 5 | "Update by keys" con chiave di un altro livello | **Avviso + salta**, scrivendo il motivo nel log delle righe saltate |
| 6 | `FW_DOCU_NODES_T` e `FW_OBJ_DESCRS` | Non hanno livelli: il campo Level offre solo **Standard / All** (nessun filtro). Va scritto anche nei suggerimenti (hint) |
| 7 | Colonna "utente" delle righe scritte | Riga CT -> `ZFXCUSTOM`, riga CW -> `ZFXINTEGR`; le altre restano `JT` |
| 8 | Colonna "Categoria" | **Da verificare con il database** (passo 0), poi decidere |

## 3. Le regole dei livelli (da Orione, `framework\layers\Layer.java`)

| Livello | Stringhe e triplette (per **codice**) | Opzioni (per **nome**, colonna `tipo`) | Utente |
|---|---|---|---|
| FW | 10000 - 99999 | inizia con `Fw` | ZFXFW |
| AP (standard) | 100000 - 2999999 | senza prefisso | ZFXSYS |
| CW | 4000000 - 4999999 | inizia con `Cw` | ZFXINTEGR |
| CT | 3000000 - 3999999 | inizia con `Ct` | ZFXCUSTOM |
| CK | 5000000 - 5999999 | inizia con `Ck` | ZFXCKSYS |
| CC | 9000000 - 1999999999 (nel codice; tu avevi scritto fino a 9999999) | inizia con `Cc` | ZFXCCSYS |

- **Standard** per JT = FW + AP = codici sotto 3000000, e opzioni che **non** iniziano con Cw / Ct / Ck / Cc.
- Il prefisso e' **case sensitive**: `Ct...` e' CT, `CT...` no.
- Orione per AP usa `LIKE '%'` (prende tutto): per "Standard" bisogna escludere esplicitamente gli altri prefissi.
- Un codice fuori da ogni intervallo, per Orione, e' un errore ("Invalid code!").

## 4. Categoria: cosa sappiamo e cosa verificare (decisione 8)

**Cosa abbiamo trovato:**
- Nei file standard (`FW_STRINGSFW.unl`, `FW_FIELD_STRINGSFW.unl`) la categoria e' una **etichetta di modulo**: `FW`, `USERTOOLS`,
  `TCSTOOLS`, `CHART`... e **un solo spazio** (` `) vuol dire "nessuna categoria" (1464 stringhe su ~4000).
- Orione, quando traduce, scrive la categoria come **un solo spazio** (`Value.SINGLEBLANK`), non `NULL`. Il motivo piu'
  probabile: in Oracle `''` e' `NULL`, e la colonna potrebbe essere NOT NULL.
- Nelle tue schermate il vecchio inserimento JCT (riga `en`, utente JCT, 19/03/2025) ha **la stessa categoria della riga
  italiana** (`MES`): sembra che copiasse la categoria dalla riga di partenza.
- JT 3.0 scrive `NULL` nella colonna della categoria.

**Rischi:** (a) se la colonna e' NOT NULL, l'INSERT fallisce; (b) se funziona, le righe tradotte restano senza categoria e non
compaiono nei filtri per modulo.

**Verifiche da fare sul database (passo 0, nessun codice):**
```sql
-- 1) la colonna accetta NULL? quanto e' lunga?
SELECT table_name, column_name, nullable, data_type, data_length
FROM user_tab_columns
WHERE table_name IN ('FW_STRINGS','FW_FIELD_STRINGS') ORDER BY table_name, column_id;

-- 2) che valori contiene, nel tuo database?
SELECT category, COUNT(*) FROM fw_field_strings GROUP BY category ORDER BY 2 DESC;
SELECT category, COUNT(*) FROM fw_strings GROUP BY category ORDER BY 2 DESC;

-- 3) le righe scritte da JT hanno la categoria vuota? (usa il nome vero della colonna utente)
SELECT * FROM fw_strings WHERE <colonna_utente> = 'JT' AND ROWNUM <= 10;

-- 4) la riga tradotta e la riga di partenza hanno la stessa categoria? (esempio: codice 114936)
SELECT language, code, category FROM fw_field_strings WHERE code = 114936;
```
**Proposta (da confermare con i risultati):** nella riga tradotta **copiare la categoria della riga di partenza**; se e' vuota,
usare un solo spazio. Se la colonna accetta NULL e il tuo database non usa le categorie, si puo' lasciare `NULL`.

## 5. Passi di sviluppo

Ordine pensato per imparare: prima la parte "pura" (solo Python, facile da provare), poi il database, poi la finestra.
**Lavora con i test**: per ogni passo scrivi prima il test (deve fallire), poi il codice (deve passare).

Comandi utili (dalla cartella del progetto):
```
run_tests.bat                                              tutti i test
.venv\Scripts\python.exe -m unittest tests.test_layers     solo un file (cambia il nome)
.venv\Scripts\python.exe -m unittest tests.test_layers.LayerOfCodeTests.test_boundaries    un solo test
```

### Passo 0: verifiche sul database (nessun codice)
Esegui le query del capitolo 4 e annota i risultati qui sotto. Decide la categoria (decisione 8).

### Passo 1: il modulo dei livelli (`jt\layers.py`)  [piccolo]
- **Cosa**: un file nuovo, senza Tkinter e senza database, con una descrizione di ogni livello (nome, etichetta, prefisso, primo e
  ultimo codice, utente) e due funzioni: `layer_of_code(codice)` e `layer_of_name(nome)`. Una lista `VISIBLE` con i livelli
  mostrati nel menu.
- **Ripassa**: `dataclass(frozen=True)`, tuple, costanti, funzioni, eccezioni (`raise ValueError`).
- **Prima il test** (`tests\test_layers.py`): estremi degli intervalli (2999999 e' AP, 3000000 e' CT, 3999999 CT, 4000000 CW,
  4999999 CW, 5000000 CK), `Ct` e' CT ma `CT` no, nome senza prefisso = AP, codice fuori intervallo = errore.
- **Controllo**: i test passano; confronta i numeri con la tabella del capitolo 3 (e con `Layer.java`).

### Passo 2: il filtro per livello nelle query (`jt\tables.py`)  [medio]
- **Cosa**: ogni tabella impara a dire "per questo livello aggiungi questa condizione". Stringhe e triplette: condizione sul codice;
  opzioni: condizione sul nome (`LIKE`, e per Standard `NOT LIKE` per ogni prefisso); `FW_DOCU_NODES_T` e `FW_OBJ_DESCRS`:
  nessuna condizione e un segno `supports_levels = False`.
- Le funzioni che costruiscono le query (`read_missing`, `count_batch`, `count_all`) ricevono il livello (predefinito: All, cosi' i
  test vecchi continuano a passare). **Tutti i valori come variabili bind**, come ora.
- **Ripassa**: argomenti con valore predefinito, f-string, dizionari (unire due dict), `str.join`.
- **Prima il test** (`tests\test_tables.py`): per ogni tabella e ogni livello, il testo SQL e i bind attesi.
- **Controllo**: puoi provare le query sul database di prova (`JT-TestDB`) o con SQLite come fanno i test.

### Passo 3: il servizio (`jt\service.py`)  [medio]
- **Cosa**: `load_missing`, `missing_counts` e la selezione (`Selection`) ricevono e ricordano il livello.
- **"Update by keys"** (decisione 5): per ogni riga letta, calcola il suo livello (`layer_of_code` / `layer_of_name`). Se il
  livello scelto non e' All e la riga e' di un altro livello: **non si scrive**, la chiave va in una lista nuova della selezione
  e, durante la corsa, nel log delle righe saltate con il motivo (es. `la chiave 100000 e' di livello Standard, scelto CT`).
  Load mostra un avviso giallo con le chiavi escluse.
- **Ripassa**: dataclass con nuovi campi, list comprehension, `str.format`.
- **Prima il test** (`tests\test_service.py`): chiavi di livelli diversi con livello scelto; con All non si scarta nulla.

### Passo 4: l'utente scritto sulle righe (decisione 7)  [medio]
- **Cosa**: oggi l'INSERT/UPDATE scrive la sigla fissa `JT`. Diventa un valore calcolato per ogni riga: riga CT -> `ZFXCUSTOM`,
  riga CW -> `ZFXINTEGR`, il resto `JT`. Il livello della riga si ricava da codice o nome (non dal filtro scelto: con "All" righe
  di livelli diversi hanno utenti diversi). Meglio come variabile bind invece che testo fisso nell'SQL.
- **Conseguenza da sapere**: le righe CT/CW non si riconoscono piu' dalla sigla `JT`. Per ritrovarle servono i log CSV (aggiungi
  colonne `level` e `user`, passo 7) o il filtro per codice/utente.
- **Prima il test**: gli SQL di INSERT e UPDATE attesi (i test attuali con `'JT'` dentro l'SQL vanno cambiati apposta).

### Passo 5: la categoria (decisione 8)  [piccolo, dopo il passo 0]
- **Cosa**: secondo l'esito del passo 0, nell'INSERT di stringhe e triplette copiare la categoria dalla riga di partenza.
  L'UPDATE non la tocca.
- **Prima il test**: la categoria della riga di partenza arriva nell'INSERT; riga con categoria vuota -> comportamento deciso.

### Passo 6: la finestra (`jt\ui\translation_screen.py`)  [medio]
- **Cosa**: un menu **Level** nel riquadro "What to translate" (voci da `VISIBLE`, predefinito Standard), ricordato in
  `query_data.json` (campo nuovo). Per le tabelle senza livelli (`supports_levels = False`) il menu offre solo Standard / All.
  Ogni modifica del campo invalida il Load (come gli altri campi). Il conteggio "Missing in Spanish" tiene conto del livello
  (`Missing in Spanish (CT): 214 in this table, ...`).
- **Suggerimenti (hint)** (decisione 6): un tooltip su Level che spiega i livelli e gli intervalli, e che per `FW_DOCU_NODES_T` e
  `FW_OBJ_DESCRS` non ci sono livelli.
- **Ripassa**: `tk.StringVar`, `ttk.Combobox`, `trace_add`, abilitare/disabilitare un widget, `ToolTip` gia' presente in `widgets.py`.
- **Prima il test** (`tests\test_ui.py`): il menu mostra 4 voci, predefinito Standard, si ricorda la scelta, cambiare livello spegne
  Translate, tabelle senza livelli.

### Passo 7: log (`jt\logs.py`, `jt\service.py`)  [piccolo]
- Colonne `level` e `user` nei CSV (inserts, errori, saltate).

### Passo 8: database di prova (`tools\create_test_db.py`)  [piccolo]
- Aggiungere righe CT e CW (codici 3000001..., 4000001...; opzioni `CtProva`, `CwProva`) e controllare che ogni livello visibile
  abbia qualcosa da tradurre (il test `test_testdb.py` lo verifica gia' per le lingue: estenderlo ai livelli).

### Passo 9: documenti e testi  [piccolo]
- `GUIDA_UTENTE.md`: spiegare il campo Level e il cambio di valore iniziale (Standard).
- Banner "COMING SOON": toglierlo per CT/CW; resta solo per CK/CC se li nascondiamo.
- `TESTS.md` (conteggi), `README.md`, questa scheda (segna cosa e' fatto).

### Passo 10: rilascio 3.1
- `release.bat --version 3.1`, poi commit e push.

## 6. Ripasso di Python che serve (con dove si vede nel progetto)

| Concetto | Esempio nel progetto |
|---|---|
| `dataclass` | `jt\service.py` (`Selection`, `RunResult`) |
| Argomenti con valore predefinito | `TableSpec.read_missing` in `jt\tables.py` |
| Dizionari e bind SQL | `_binds` in `jt\tables.py` |
| f-string e `str.join` | `_insert_sql` in `jt\tables.py` |
| Eccezioni | `parse_keys` (`raise ValueError`) |
| `unittest` e `subTest` | `tests\test_tables.py` |
| Tkinter (`StringVar`, `Combobox`, `trace_add`) | `jt\ui\translation_screen.py` |

## 7. Rischi e punti di attenzione

- Il nuovo valore iniziale (Standard) cambia il comportamento rispetto alla 3.0: scrivilo nella guida.
- Il prefisso delle opzioni e' case sensitive e valuta solo l'inizio del nome: `Ctrl...` risulterebbe CT. E' la regola di Jflex (`startsWith("Ct")`).
- CC: nel codice di Orione il limite superiore e' 1999999999 (non 9999999).
- Con la scelta 7 le righe CT/CW non portano piu' la sigla `JT`: tienine conto in eventuali report.
- Quando CK e CC verranno mostrati, controlla che anche per loro intervalli e prefissi siano quelli giusti.

## 8. Risultati del passo 0 e decisione sulla categoria (2026-11-03)

- `user_tab_columns` non mostra le tabelle (stanno in un altro schema): non serve, perche' JT 3.0 ha gia' scritto righe con categoria
  `NULL` in `fw_strings` (utente `JT`): la colonna accetta `NULL`.
- Le categorie sono etichette di modulo (MCS, MES, PWP, WMS, RADAJET, PM, ...): 110 valori nelle triplette, 166 nelle stringhe. Il
  valore piu' frequente e' "vuoto" (un blank: 10.294 triplette, 15.889 stringhe); `NULL` c'e' ma e' molto meno frequente
  (3.225 e 2.148), in gran parte righe scritte da JT.
- Codice 114936: `it` e `en` hanno entrambe `MES`: lo strumento vecchio copiava la categoria della riga di partenza.
- **Decisione:** la categoria e' del modulo della stringa, non della lingua: l'INSERT copia la categoria della riga sorgente
  (un modulo, un blank o `NULL`, identica). L'UPDATE non la tocca. E' implementato in `FW_STRINGS` e `FW_FIELD_STRINGS`
  (`jt/tables.py`) con test; le tabelle delle opzioni non hanno la colonna.
