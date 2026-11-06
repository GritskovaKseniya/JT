# JTools

Programma Windows (Tkinter) che traduce con **Azure Translator** i testi di un database **Jflex su Oracle**:
`FW_STRINGS`, `FW_FIELD_STRINGS`, le tabelle `FW_OPZIONI*`, `FW_DOCU_NODES_T`, `FW_OBJ_DESCRS`. Versione 3.1
(erede di JCT 2.2.2).

- Guida per chi lo usa: [GUIDA_UTENTE.md](GUIDA_UTENTE.md)
- Com'e' fatto il codice: [ARCHITECTURE.md](ARCHITECTURE.md)
- Test: [TESTS.md](TESTS.md) - Note di design: [UX_REVIEW.md](UX_REVIEW.md)

## Per chi riceve il programma

Nel pacchetto che si da' ai colleghi ci sono solo due file da leggere: `LEGGIMI.txt` (cosa serve e come installare, breve:
il sorgente e' `tools\LEGGIMI.txt`) e [GUIDA_UTENTE.md](GUIDA_UTENTE.md) (come si usa).

## Avvio da sorgente

Serve Python 3.10 con `cx_Oracle` e `requests`, e un client Oracle a 64 bit sul PC.

```
uv venv --python 3.10 .venv
uv pip install --python .venv\Scripts\python.exe cx_Oracle requests sqlparse==0.5.0
copy Data\azure_services.example.json Data\azure_services.json     (poi scrivi la chiave Azure)
.venv\Scripts\python.exe JT.py          oppure doppio clic su run_JT.bat
```

I file `Data\azure_services.json`, `Data\connection_data.json` e `Data\query_data.json` contengono segreti o scelte personali:
sono in `.gitignore` e non vanno mai su GitHub (restano i modelli `*.example.json`).

## Test

```
run_tests.bat
.venv\Scripts\python.exe -W error::ResourceWarning -m unittest discover -s tests
```

Solo libreria standard. Oracle e Azure sono simulati: nessuna connessione, nessuna chiamata di rete. Dettagli in
[TESTS.md](TESTS.md).

## Creare il programma da dare agli altri

**Procedura consigliata:** doppio clic su `release.bat` (test, costruzione, firma, controllo dello .zip e prova di avvio, tutto in
un passo). Vedi [RILASCIO.md](RILASCIO.md). Quello che segue spiega i singoli strumenti.

```
uv pip install --python .venv\Scripts\python.exe pyinstaller         (una volta sola)
.venv\Scripts\python.exe tools\build.py
```

Risultato in `dist\`:

| File | Cosa e' |
|---|---|
| `dist\JTools\JTools.exe` | il programma con tutto dentro (non serve Python); accanto ci sono `Data`, `Graphics`, `LEGGIMI.txt`, `GUIDA_UTENTE.md` (e `JT-TestDB.exe` se non si usa `--no-testdb`) |
| `dist\JTools-3.0.zip` | la cartella `JT` compressa: si scompatta e si lancia `JTools.exe` |
| `dist\JT-Setup-3.0.exe` | programma di installazione (collegamento nel menu Start, disinstallazione). Solo se e' installato [Inno Setup 6](https://jrsoftware.org/isdl.php) |

Opzioni:

- `--with-azure` include la chiave Azure vera. Senza, il pacchetto ha un modello da compilare: **scegli con cura a chi
  dai la chiave** (e' a pagamento).
- `--oracle-client "C:\percorso\client\bin"` copia il client Oracle a 64 bit (cartella con `oci.dll`) in `oracle_client`:
  JT lo usa da solo e il PC non ha bisogno di Oracle. Verifica la licenza prima di ridistribuirlo.
- `--no-installer` salta il setup anche se Inno Setup c'e'.
- `--no-testdb` non mette nel pacchetto `JT-TestDB.exe` (lo strumento del database di prova): per i colleghi che usano solo JT.
- `--sign` firma `JTools.exe`, `JT-TestDB.exe` (se c'e') e il setup con un certificato di code signing, con marca temporale. Il certificato si
  cerca prima nel file `.pfx` indicato da `JT_SIGN_PFX` (password in `JT_SIGN_PASSWORD`: il certificato dell'azienda), poi nel
  Magazzino certificati dell'utente (`Cert:\CurrentUser\My`, soggetto `JT Jflex Translator`). Il pacchetto contiene anche
  `JT-certificato.cer` (solo la parte pubblica). Un certificato **autofirmato** non e' noto agli altri PC: finche' non lo importano
  tra gli editori attendibili Windows continua a segnalare l'editore come sconosciuto. Per un risultato pulito serve un
  certificato dell'azienda o di un'autorita' riconosciuta.

Creare un certificato autofirmato per le prove (una volta, PowerShell):

```
New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=JT Jflex Translator - Nome Cognome" -KeyUsage DigitalSignature `
  -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(3)
```

L'installazione e' per utente (`%LOCALAPPDATA%\Programs\JTools`, senza diritti di amministratore). Come le altre applicazioni,
JT tiene **separati il programma e i dati dell'utente**:

| Dove | Cosa |
|---|---|
| `%LOCALAPPDATA%\Programs\JTools` | programma, `Data` (tabelle, lingue, glossario), `Graphics`: sola lettura, si sostituisce a ogni aggiornamento |
| `%LOCALAPPDATA%\JTools` | `Logs\`, `connections\` (un file per database salvato), `azure_services.json`, `connection_data.json`, `query_data.json`: restano dopo aggiornamenti e disinstallazione |

Alla prima partenza JT copia il modello della chiave Azure in `%LOCALAPPDATA%\JTools`. Da sorgente (`JT.py`) non cambia nulla:
tutto resta nella cartella del progetto (`Data\`, `Logs\`). La scelta e' in `Paths` (`jt\config.py`).

## Simulatore di Oracle

Per provare tutto senza un database vero (anche senza rete e senza client Oracle). Il database e' SQLite in memoria con le
tabelle e le righe di `tools\create_test_db.py`, corretto per comportarsi come Oracle dove conta per JT (`LIKE` che distingue
maiuscole e minuscole, `ROWNUM`, `sysdate`, `NVL`, `ORA-12899` per i testi troppo lunghi, `ORA-01400`). Il codice di JT e' quello
vero; Azure e' finto: negli scenari risponde `[lingua] testo`, nella finestra (`--gui`) le stringhe del database di prova hanno
una traduzione vera in en, fr, de, es e hi (le altre restano `[lingua] testo`), e con `--azure` si usa il **vero Azure**.

```
run_simulator.bat                    esegue gli scenari (livelli, utente, categoria, Update by keys, errori) e dice cosa non va
run_simulator.bat --gui              apre la finestra di JT collegata al database simulato: si prova con il mouse
run_simulator.bat --gui --azure      come sopra, ma con il vero Azure (chiave di Data\azure_services.json: costa pochi caratteri)
run_simulator.bat --gui --nokey      come lo vede chi non ha la chiave Azure: Load conta, ma Preview/Translate/Write sono spenti
run_simulator.bat --gui --one-tool   senza gli strumenti di prova (con --gui di solito ci sono due strumenti finti per vedere le schede): JT come e' oggi
run_simulator.bat --gui --fw             (con gli indici veri, se il database li lascia leggere) con il dizionario dei nomi COMPLETO di un Jflex vero (circa 1.700 tabelle e 38.000 campi): per provare SQL <> TecSQL con i dati veri
run_simulator.bat --gui --fw --fw-connect HOST:PORT/SID --fw-user USER     la prima volta (o per rileggerlo): lo legge dal database FW (solo SELECT, la password si chiede) e lo salva in `tools\fw_dictionary.json`
run_simulator.bat --translate "SELECT $FwTables.Title FROM $FwTables" --fw       senza finestra: traduce una query e la stampa (con `$` e' TecSQL, senza e' SQL; `--descriptor $Nome` se la tabella ne ha piu' d'uno)
```

Con `--azure` il database resta simulato: niente di reale viene scritto, ma le traduzioni sono quelle vere (utile per vedere come
appaiono in tabella, per esempio in hindi). Se la chiave non c'e' o e' il segnaposto, si usano le traduzioni di prova.

**Il dizionario dei nomi vero (`--fw`).** Per provare lo strumento SQL <> TecSQL serve un dizionario vero: `tools\fw_dictionary.py` legge (solo `SELECT`) tutte le tabelle e i campi di un database FW e li salva in `tools\fw_dictionary.json` (in `.gitignore`: dati dell'azienda, non vanno su GitHub; la password si chiede e non si salva). Poi `--fw` lo carica nel simulatore, da solo o insieme a `--sample`.

**Con righe vere.** `tools\extract_sample.py` copia da un Oracle vero (solo `SELECT`) una piccola selezione di righe in
`tools\sample_data.json`: tutte le stringhe e triplette CT/CW, una parte di FW, AP e CC con le loro traduzioni, le opzioni `Fw...`
e un campione degli altri tipi, un campione dei nodi di documentazione e **il dizionario dei nomi** (FW_TABLES e FW_TABLE_FIELDS: circa 260 tabelle logiche e 6.700 campi, compresi i casi con due nomi logici per la stessa tabella fisica). Con `--only FW_TABLES,FW_TABLE_FIELDS` si aggiunge una sola parte al file che c'e' gia' (anche da un altro database) senza rileggere il resto. Il file e' in `.gitignore` (dati di un database vero: non
va su GitHub). Poi `run_simulator.bat --gui --sample tools\sample_data.json` apre JT sul simulatore con le righe di prova **piu'**
quelle vere, e `create_test_db.py --sample tools\sample_data.json` fa lo stesso in un Oracle di prova.

```
.venv\Scripts\python.exe tools\extract_sample.py --host <server> --sid <sid> --user <utente>    (la password si chiede)
```

Alla fine della prova con `--gui` elenca le righe scritte (lingua, codice, utente). I file dell'utente (connessione, log) non si
toccano: la prova lavora in una cartella temporanea. Non sostituisce una prova su un Oracle vero: non conosce PL/SQL, la
lunghezza in byte invece che in caratteri, gli indici, ecc.

## Database di prova

`tools\create_test_db.py` (nel pacchetto: `JT-TestDB.exe`; l'installazione lo propone alla fine) crea in un Oracle
**gia' raggiungibile** un piccolo database di prova: le tabelle che JT traduce, con righe in italiano da tradurre, alcune
gia' tradotte (per provare Update by keys) e i casi particolari (testo vuoto, solo spazi, apostrofi, accenti, `UMV`,
*Supply Chain Planning*, una descrizione che tradotta supera i 100 caratteri).

```
.venv\Scripts\python.exe tools\create_test_db.py
```

- Con un utente amministratore (SYSTEM...) crea l'utente `JTTEST` / `jttest` e le tabelle li'.
- Senza amministratore crea le tabelle nello schema dell'utente con cui ti colleghi.
- Non tocca mai tabelle esistenti: se nello schema c'e' gia' una tabella di JT e non e' un database di prova creato da
  questo strumento, si ferma. `--recreate` rifa' solo un database di prova creato da lui.
- Le lunghezze delle colonne sono quelle di un database Jflex vero (lingua di 2 caratteri, `value` 255, `caption` 100, descrizione
  delle opzioni 100, codice opzione `CHAR(1)`/2/3/`NUMBER(5)` nelle quattro tabelle). Con `--sample FILE` si aggiungono righe vere
  (vedi "Simulatore di Oracle").

Non puo' creare un server Oracle: serve un'istanza Oracle (anche quella di sviluppo). Le colonne sono quelle che JT usa
(vedi `jt	ables.py`) ma non sono la copia esatta delle tabelle Jflex: per prove con i dati veri serve un DB demo.

## Cartelle

| Cartella | Contenuto |
|---|---|
| `JT.py` | punto di ingresso |
| `jt\` | logica (connessione, tabelle, traduzione, Azure, glossario, log) senza Tkinter |
| `jt\ui\` | interfaccia |
| `Data\` | tabelle, lingue, glossario; impostazioni e chiave Azure |
| `Graphics\` | icone e pallini dei passi (rigenerabili con `tools\make_icons.py` e `tools\make_step_badges.py`) |
| `tests\` | test automatici |
| `tools\` | strumenti: icone, `build.py`, `installer.iss`, `create_test_db.py`, `simulate.py` (simulatore di Oracle) |

## Per modificare

- Una tabella in piu': si aggiunge una classe in `jt\tables.py` e una voce in `Data\tables.json`.
- I livelli Jflex (FW, AP, CW, CT, CK, CC): intervalli dei codici e prefissi dei nomi sono in `jt\layers.py`; quali livelli si
  vedono nella finestra e' `VISIBLE` (per mostrare anche CK basta aggiungerlo; CC e' gia' visibile, con utente `ZFXCCSYS`).
- Il logo: `ICON_NAME` in `jt\config.py` (`bubbles`, `pixel_cube`, `pixel_block`).
- Le lingue fisse in cima ai menu: `PINNED_LANGUAGES` in `jt\config.py`.
- La sigla scritta nel database: `DB_MARKER` in `jt\config.py` (`JT`).
