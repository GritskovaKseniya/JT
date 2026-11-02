# JT - Jflex Translator: guida utente

JT traduce con Azure Translator i testi di un database Jflex (Oracle): stringhe, descrizioni dei campi, opzioni, nodi di
documentazione. Scrive le traduzioni direttamente nelle tabelle, solo dove mancano (oppure, se lo chiedi, per le chiavi
che indichi).

## 1. Prima di cominciare

| Cosa serve | Note |
|---|---|
| Windows 10 / 11 | Non serve installare Python. |
| Client Oracle a 64 bit | Serve un client Oracle (cartella con `oci.dll`) sul PC. Se il pacchetto contiene la cartella `oracle_client`, e' gia' incluso. |
| Chiave di Azure Translator | Scritta in `Data\azure_services.json` (vedi sotto). |
| Accesso al database | Host, porta, SID, utente e password; l'utente deve poter scrivere nelle tabelle da tradurre. |

### La chiave di Azure

Apri `%LOCALAPPDATA%\JT\azure_services.json` con il Blocco note (la cartella si apre anche dal menu Start: "JT - log e
impostazioni"; compare dopo il primo avvio) e scrivi la chiave al posto di `INSERISCI-QUI-LA-CHIAVE-AZURE`:

```json
{"subscription_key": "la-tua-chiave",
 "endpoint": "https://api.cognitive.microsofttranslator.com",
 "location": "italynorth"}
```

`location` e' la regione della risorsa Azure. Non condividere questo file: la chiave e' a pagamento.

## 2. Avvio

Doppio clic su **JT.exe** (o sul collegamento creato dall'installazione). Il programma ha due passi, in alto a sinistra:
**1 Connection** e **2 Translation**.

## 3. Passo 1 - Connessione

1. Compila **Host name**, **Port**, **SID**, **Username**, **Password**. Dopo la prima volta i campi (password compresa)
   si ricordano.
2. Premi **Connect** (o Invio). In basso compare "Connecting...", poi "Connection established" oppure il motivo
   dell'errore.
3. Premi **Next** per passare alla traduzione. Se cambi un campo dopo essere collegata, la connessione si chiude e devi
   ricollegarti.

In basso a sinistra una riga mostra sempre lo stato: `Connected to <database> - <host> - user <utente>`. Passa il mouse
per vedere i dettagli.

## 4. Passo 2 - Traduzione

### Lingue

**From** e' la lingua da cui si traduce, **To** quella in cui si scrive. Italiano e inglese sono in cima all'elenco, poi
tutte le altre in ordine alfabetico. All'inizio: Italian -> English. La scelta si ricorda.

### Cosa tradurre

- **Table**: la tabella da tradurre (stringhe, campi, le quattro tabelle delle opzioni, nodi di documentazione, descrizioni
  oggetti).
- Sotto la tabella una riga dice **quante traduzioni mancano**, per questa tabella e per tutte
  (`Missing in German: 21.053 in this table, 41.841 in all tables`). Passa il mouse: vedi il conteggio per ogni tabella.
  Dopo ogni traduzione il conteggio si aggiorna da solo.
- **Max rows**: quante righe tradurre al massimo in questa corsa (minimo 1). Utile per provare con poche righe.
- **Update by keys**: vedi il capitolo 5. Se e' vuoto si traduce quello che manca.

### I tre pulsanti

1. **Load** legge dal database le righe da tradurre e dice quante sono, il tempo stimato e il numero di caratteri
   (che e' quello che Azure fattura): `1.600 rows to translate: about 17 minutes, 100 characters.`
2. **Translate** parte solo dopo un Load riuscito. Traduce e scrive **una riga alla volta**, con conferma (commit)
   a ogni riga.
3. **Stop** (al posto di Translate durante la corsa) ferma dopo la riga in corso. Le righe gia' scritte restano.

Se cambi lingua, tabella, Max rows o chiavi dopo il Load, Translate si spegne: bisogna rifare Load. Cosi' non si scrive
mai nella tabella sbagliata.

Durante la traduzione i campi sono bloccati e la barra mostra l'avanzamento
(`Processed 40/100 - Inserted 38 - Errors 1 - Skipped 1`). La finestra resta libera: puoi spostarla.

### Alla fine

Un messaggio riassume il risultato (`Done: 98 inserted. 1 errors, 1 skipped. Log: Logs\...`). Verde = tutto bene, giallo =
c'e' qualcosa da guardare.

## 5. "Update by keys": rifare traduzioni specifiche

Serve quando una stringa e' cambiata e vuoi rigenerare la traduzione, oppure vuoi tradurre solo alcune voci.

- Nelle tabelle di stringhe scrivi gli **id numerici**, separati da virgola, spazio o `;`: `100000, 100001, 100002`.
- Nelle tabelle delle **opzioni** scrivi il **nome dell'opzione**: `ProcessiLunghi` (tutti i codici di quel tipo).
- Premi **Load**: il testo di partenza si legge nella lingua **From**.

Per ogni riga trovata, JT guarda se esiste gia' nella lingua **To**:

| Situazione | Cosa succede |
|---|---|
| Esiste in From e in To | UPDATE: la traduzione viene rifatta e sostituita |
| Esiste in From, non in To | INSERT: viene creata |
| Non esiste in From | Non si fa nulla; Load la segnala nell'avviso giallo |
| Testo di partenza vuoto | Saltata (non c'e' niente da tradurre) |

Il controllo e' fatto chiave per chiave: con `100000, 100001` la prima puo' essere aggiornata e la seconda inserita.
Massimo 1000 chiavi; chiavi non valide (lettere in un campo numerico) vengono rifiutate con un messaggio.

## 6. Glossario

I testi passano da `Data\glossary.json`:

- **UMV** diventa **HU** nelle lingue diverse dall'italiano;
- i termini inglesi del prodotto (per esempio *Supply Chain Planning*) restano invariati.

Per aggiungere un termine modifica `Data\glossary.json` (e fai fare una prova con poche righe).

## 7. File che JT scrive

| Dove | Cosa |
|---|---|
| Nel database | Le traduzioni. Nella colonna "utente" delle righe inserite o aggiornate scrive la sigla `JT`, cosi' le riconosci. |
| `%LOCALAPPDATA%\JT\Logs\JT_inserts_log_<data>.csv` | Una riga per ogni traduzione scritta (data, azione, codice, lingue, testo, traduzione). |
| `...\Logs\JT_errors_log_<data>.csv` | Le righe che il database ha rifiutato (per esempio testo troppo lungo). |
| `...\Logs\JT_skipped_log_<data>.csv` | Le righe non tradotte perche' Azure ha dato errore, con il motivo. |
| `%LOCALAPPDATA%\JT\connection_data.json`, `query_data.json` | Ultima connessione e ultima scelta. |

I file stanno in `%LOCALAPPDATA%\JT` (scrivilo nella barra degli indirizzi di Esplora file, oppure usa il collegamento nel menu
Start): non nella cartella del programma, quindi restano anche se aggiorni o disinstalli JT. Se lanci JT dai sorgenti, log e
impostazioni stanno invece nella cartella del progetto.

I file CSV si aprono con Excel. Le lettere accentate sono corrette; se l'Excel italiano mette tutto in una colonna usa
**Dati > Da testo/CSV** e scegli il separatore "virgola".

## 8. Quando qualcosa non va

| Messaggio / sintomo | Cosa fare |
|---|---|
| Errore subito al Connect, tipo `DPI-1047` o "Cannot locate a 64-bit Oracle Client library" | Manca il client Oracle a 64 bit sul PC. Installalo o usa il pacchetto con `oracle_client`. |
| `ORA-12541: no listener` / `ORA-12154` | Host, porta o SID sbagliati, oppure il server non e' raggiungibile. |
| `ORA-01017: invalid username/password` | Utente o password errati. |
| "Azure settings not found or not valid" | Manca o e' sbagliato il file `azure_services.json` indicato nel messaggio (`%LOCALAPPDATA%\JT`). |
| Molte righe "Skipped" | Azure non risponde o rifiuta la chiave: controlla `Logs\JT_skipped_log_...` (c'e' il motivo, per esempio `Azure error 401000`). |
| Una tabella non compare | Non esiste in quel database: il programma mostra solo quelle presenti. |
| Il conteggio "Missing" non si calcola | Tabella non leggibile da questo utente: vedi la console/log; le altre tabelle funzionano. |
| Una descrizione in `FW_OBJ_DESCRS` finisce negli errori | La traduzione supera i 100 caratteri consentiti dalla colonna. |

## 9. Database di prova

Per provare JT senza toccare dati veri: `JT-TestDB.exe` (accanto a JT.exe; l'installazione lo propone alla fine) crea
tabelle di prova con righe in italiano da tradurre. Ti chiede host, porta, SID e un utente:

- se indichi un **amministratore** (per esempio SYSTEM) crea l'utente `JTTEST` (password `jttest`) e le tabelle li';
- se lasci vuoto l'amministratore, crea le tabelle nello schema dell'utente che indichi.

Alla fine mostra i dati con cui collegarti da JT. Non modifica mai tabelle che esistono gia': se nello schema ci sono
gia' tabelle di JT che non sono di prova, si ferma. Serve comunque un Oracle raggiungibile.

Cosa trovi dentro: stringhe, campi, opzioni (per esempio `ProcessiLunghi`), nodi di documentazione e descrizioni di
oggetti. Alcune righe sono gia' tradotte in inglese e tedesco (prova "Update by keys"), una e' vuota, una e' fatta di
soli spazi, una ha `UMV`, una e' troppo lunga per `FW_OBJ_DESCRS` (finisce nel log degli errori).

## 10. Buone pratiche

- Prova sempre con **Max rows = 1** o 5 su un database di prova prima di una corsa lunga.
- Ogni riga e' una chiamata Azure a pagamento: guarda i caratteri stimati dopo **Load**.
- Le traduzioni sono scritte subito (commit a ogni riga): per annullare bisogna usare il database, non basta chiudere JT.
- Chiudendo la finestra durante una traduzione, JT finisce la riga in corso, chiude la connessione ed esce.
