# JT: come si crea un nuovo pacchetto per i colleghi

Procedura per quando hai sviluppato qualcosa di nuovo e vuoi rifare lo `.zip` da dare ai colleghi.

## In breve

1. Sviluppa e prova da sorgente (`run_JT.bat`).
2. **Chiudi JT** e doppio clic su **`release.bat`** (oppure `.venv\Scripts\python.exe tools\release.py`).
3. Se alla fine vedi `PRONTO`, lo .zip e' in `dist\JT-<versione>.zip`: e' controllato e si puo' mandare.
4. `git status`, commit e push del lavoro.

## Cosa fa `release.bat` (in ordine, si ferma al primo problema)

| # | Passo | Se non va |
|---|---|---|
| 1 | Controlla che JT non sia aperto e che il certificato di firma ci sia e non scada a breve | Chiudi JT / vedi "Certificato" sotto |
| 2 | Se indichi `--version 3.1`, scrive la nuova versione in `jt\config.py` | |
| 3 | Lancia tutti i test automatici | Non costruisce nulla finche' non passano |
| 4 | Costruisce il pacchetto: ricostruisce `JT.exe`, firma, **senza** la chiave Azure (e senza `JT-TestDB.exe`) | Leggi l'errore sopra `STOP` |
| 5 | Controlla lo .zip: file giusti, **nessun dato personale** (`connection_data.json`, `query_data.json`, log, CSV), **nessuna chiave Azure vera** (c'e' solo il modello), exe firmato | `STOP`: non dare lo zip |
| 6 | Scompatta lo .zip in una cartella temporanea e **avvia davvero** `JT.exe` per 6 secondi | `STOP`: l'exe non parte |

Non fa commit ne' push: li decidi tu.

## Opzioni

```
release.bat --version 3.1     nuova versione (cambia anche il nome dello zip: JT-3.1.zip)
release.bat --with-azure      include la chiave Azure vera: SOLO per un pacchetto personale (di norma NO, vedi sotto)
release.bat --installer       crea anche il setup .exe (serve Inno Setup 6 installato)
release.bat --skip-tests      salta i test (sconsigliato)
```

## Cosa c'e' nel pacchetto

`JT.exe` (firmato), `LEGGIMI.txt` (cosa serve e come installare, breve), `GUIDA_UTENTE.md` (come si usa), `JT-certificato.cer`,
`Data\` (tabelle, lingue, glossario, modello della chiave Azure), `Graphics\`, `_internal\`. **Non** ci sono: `JT-TestDB.exe`, il README per chi
sviluppa, i tuoi dati di connessione, i log.

I testi per i colleghi si modificano qui, e il pacchetto li prende da solo alla prossima costruzione:
- `tools\LEGGIMI.txt`
- `GUIDA_UTENTE.md`

## Quando cambi cose, cosa aggiornare

| Hai cambiato | Aggiorna |
|---|---|
| Come si usa il programma | `GUIDA_UTENTE.md` |
| Cosa serve per installarlo | `tools\LEGGIMI.txt` |
| Una tabella tradotta | `jt\tables.py`, `Data\tables.json`, `tools\create_test_db.py` (database di prova) |
| La versione | `release.bat --version X.Y` |
| Il glossario | `Data\glossary.json` |

## Certificato di firma

`release.bat` cerca il certificato "JT Jflex Translator" nel tuo Magazzino certificati (`Cert:\CurrentUser\My`) oppure nel file
indicato dalle variabili `JT_SIGN_PFX` (e `JT_SIGN_PASSWORD`). Quello attuale e' **autofirmato** e scade il **02/11/2029**:
30 giorni prima di quella data `release.bat` avvisa. Come crearne uno nuovo e come funziona: vedi
`C:\Development\projects\kse\JT-podpis-sertifikat.md`.

Un certificato autofirmato non toglie del tutto l'avviso di Windows ai colleghi (vedi `LEGGIMI.txt` nel pacchetto per cosa fare).
Se l'IT ti da un certificato dell'azienda, basta impostare `JT_SIGN_PFX` e `JT_SIGN_PASSWORD` e la procedura lo usa da sola.

## Se qualcosa si rompe

| Sintomo | Causa e rimedio |
|---|---|
| `STOP: JT.exe e' aperto` | Chiudi JT (anche dal Task Manager) e rilancia. La procedura non cancella nulla se l'exe e' in uso. |
| `STOP: i test non passano` | Guarda quale test fallisce con `run_tests.bat`: vuol dire che c'e' un problema nel codice nuovo. |
| `STOP: nessun certificato di firma valido` | Il certificato e' scaduto o e' stato perso (nuovo PC). Creane uno nuovo (vedi sopra). |
| `PermissionError ... dist` | Una cartella di `dist` e' aperta in Esplora file o in un terminale: chiudila. |
| `JT.exe si e' chiuso da solo` | Errore all'avvio dell'exe: provalo a mano da `dist\JT\JT.exe` e guarda il messaggio. |

## Dopo la costruzione

1. `git status` e commit con un messaggio che dice cosa e' cambiato; poi push.
2. Manda `dist\JT-<versione>.zip` ai colleghi. **Non contiene la chiave Azure**: senza chiave JT legge e conta ma non traduce
   e non scrive (la chiave e' il permesso di scrivere). La chiave si consegna a parte, a chi e' stato formato: il file
   `azure_services.json` da copiare in `%LOCALAPPDATA%\JT` (te lo spiega `LEGGIMI.txt`). Se la chiave esce, va rigenerata in Azure.
   Lo zip senza chiave si puo' anche mettere su GitHub Releases (`dist\` resta ignorata da git: lo carichi a mano).
3. Ricorda ai colleghi: scompattare lo zip (con "Sblocca" prima, se arriva per posta) e leggere `LEGGIMI.txt`.
