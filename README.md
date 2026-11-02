# JT - Jflex Translator

Programma Windows (Tkinter) che traduce con **Azure Translator** i testi di un database **Jflex su Oracle**:
`FW_STRINGS`, `FW_FIELD_STRINGS`, le tabelle `FW_OPZIONI*`, `FW_DOCU_NODES_T`, `FW_OBJ_DESCRS`. Versione 3.0
(erede di JCT 2.2.2).

- Guida per chi lo usa: [GUIDA_UTENTE.md](GUIDA_UTENTE.md)
- Com'e' fatto il codice: [ARCHITECTURE.md](ARCHITECTURE.md)
- Test: [TESTS.md](TESTS.md) - Note di design: [UX_REVIEW.md](UX_REVIEW.md)

## Avvio da sorgente

Serve Python 3.10 con `cx_Oracle` e `requests`, e un client Oracle a 64 bit sul PC.

```
uv venv --python 3.10 .venv
uv pip install --python .venv\Scripts\python.exe cx_Oracle requests
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

```
uv pip install --python .venv\Scripts\python.exe pyinstaller         (una volta sola)
.venv\Scripts\python.exe tools\build.py
```

Risultato in `dist\`:

| File | Cosa e' |
|---|---|
| `dist\JT\JT.exe` | il programma con tutto dentro (non serve Python); accanto ci sono `Data`, `Graphics`, le guide e `JT-TestDB.exe` |
| `dist\JT-3.0.zip` | la cartella `JT` compressa: si scompatta e si lancia `JT.exe` |
| `dist\JT-Setup-3.0.exe` | programma di installazione (collegamento nel menu Start, disinstallazione). Solo se e' installato [Inno Setup 6](https://jrsoftware.org/isdl.php) |

Opzioni:

- `--with-azure` include la chiave Azure vera. Senza, il pacchetto ha un modello da compilare: **scegli con cura a chi
  dai la chiave** (e' a pagamento).
- `--oracle-client "C:\percorso\client\bin"` copia il client Oracle a 64 bit (cartella con `oci.dll`) in `oracle_client`:
  JT lo usa da solo e il PC non ha bisogno di Oracle. Verifica la licenza prima di ridistribuirlo.
- `--no-installer` salta il setup anche se Inno Setup c'e'.

L'installazione e' per utente (`%LOCALAPPDATA%\Programs\JT`, senza diritti di amministratore). Come le altre applicazioni,
JT tiene **separati il programma e i dati dell'utente**:

| Dove | Cosa |
|---|---|
| `%LOCALAPPDATA%\Programs\JT` | programma, `Data` (tabelle, lingue, glossario), `Graphics`: sola lettura, si sostituisce a ogni aggiornamento |
| `%LOCALAPPDATA%\JT` | `Logs\`, `azure_services.json`, `connection_data.json`, `query_data.json`: restano dopo aggiornamenti e disinstallazione |

Alla prima partenza JT copia il modello della chiave Azure in `%LOCALAPPDATA%\JT`. Da sorgente (`JT.py`) non cambia nulla:
tutto resta nella cartella del progetto (`Data\`, `Logs\`). La scelta e' in `Paths` (`jt\config.py`).

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
| `tools\` | strumenti: icone, `build.py`, `installer.iss`, `create_test_db.py` |

## Per modificare

- Una tabella in piu': si aggiunge una classe in `jt\tables.py` e una voce in `Data\tables.json`.
- Il logo: `ICON_NAME` in `jt\config.py` (`bubbles`, `pixel_cube`, `pixel_block`).
- Le lingue fisse in cima ai menu: `PINNED_LANGUAGES` in `jt\config.py`.
- La sigla scritta nel database: `DB_MARKER` in `jt\config.py` (`JT`).
