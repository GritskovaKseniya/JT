# JT - Jflex Translator: guida utente

JT traduce con Azure Translator i testi di un database Jflex (Oracle): stringhe, descrizioni dei campi, opzioni, nodi di
documentazione. Scrive le traduzioni direttamente nelle tabelle, solo dove mancano (oppure, se lo chiedi, per le chiavi
che indichi).

## 1. Cosa serve

| Cosa | Note |
|---|---|
| Windows 10 / 11 | Non serve installare Python. |
| Client Oracle a 64 bit | Gia' installato sul PC (quello che usi per Jflex). Senza, "Connect" da' l'errore `DPI-1047`. |
| Accesso al database | Host, porta, SID, utente e password; l'utente deve poter scrivere nelle tabelle da tradurre. |
| Internet | La traduzione la fa Azure. |

## 2. Avvio

Scompatta lo .zip in una cartella e fai doppio clic su **JT.exe** (non lanciarlo da dentro lo zip).

**Avviso di Windows al primo avvio** ("Windows ha protetto il PC"): clicca **Ulteriori informazioni** e poi **Esegui comunque**.
Se lo zip e' arrivato per posta o scaricato, prima di scompattare fai clic destro sullo .zip > **Proprieta'** > spunta
**Sblocca** > OK.

Per non vedere piu' l'avviso puoi importare una volta `JT-certificato.cer` (clic destro > Installa certificato > Utente corrente >
"Autorita' di certificazione radice attendibili", poi di nuovo per "Autori attendibili"). Chiedi prima a chi ti ha dato il programma.

Il programma ha due passi, in alto a sinistra: **1 Connection** e **2 Translation**.

## 3. Passo 1 - Connessione

1. Compila **Host name**, **Port**, **SID**, **Username**, **Password**. Dopo la prima volta i campi si ricordano.
2. Premi **Connect** (o Invio). Sotto i pulsanti compare un avviso: "Connecting...", poi "Connection established" oppure il
   motivo dell'errore. L'avviso si chiude con la crocetta a destra e ricompare al prossimo evento.
3. Premi **Next** per passare alla traduzione. Se cambi un campo dopo essere collegata, la connessione si chiude e devi
   ricollegarti.

In basso a sinistra una riga mostra sempre lo stato: `Not connected - try the connection to continue` oppure
`Connected to <database> - <host> - user <utente>`. Passa il mouse per vedere i dettagli.

## 4. Passo 2 - Traduzione

### Lingue

**From** e' la lingua da cui si traduce, **To** quella in cui si scrive. Italiano e inglese sono in cima all'elenco, poi
tutte le altre in ordine alfabetico. All'inizio: Italian -> English. La scelta si ricorda.

I blocchi **LANGUAGES**, **WHAT TO TRANSLATE** e **PROGRESS** si chiudono con un clic sul titolo (all'inizio sono aperti): chiusi
restano una riga con il riassunto (`Italian -> French`, `JFX: Strings - Standard - 12 missing`, `10/10`), e la finestra si
rimpicciolisce. Anche **Advanced** e **Details** si aprono con un clic.

Se la finestra e' piu' bassa dello schermo (schermo piccolo, scala 150%) compare una barra di scorrimento a destra: la rotella
del mouse scorre, tranne sopra i menu a tendina.

### Cosa tradurre

- **Table**: la tabella da tradurre (stringhe, campi, le quattro tabelle delle opzioni, nodi di documentazione, descrizioni
  oggetti).
- **Level**: quale livello di Jflex tradurre. Passa il mouse sul campo per il dettaglio. **All levels** = tutti, senza filtro;
  **Standard** = il prodotto standard; **CW - Integrations** = integrazioni; **CT - Customizations** = personalizzazioni Tecnest.
  All'inizio e' **Standard** (e' cambiato rispetto alla versione 3.0, che traduceva tutto insieme): per tradurre anche le righe
  CT o CW scegli quel livello oppure All levels. Il livello si riconosce dal codice della stringa (CW 4000000-4999999, CT
  3000000-3999999) o, per le opzioni, dal prefisso del nome (`Cw...`, `Ct...`). Le tabelle dei nodi di documentazione e delle
  descrizioni oggetti non hanno livelli: per loro il campo e' spento (All levels) e si traduce sempre tutto. Dopo **Load** il
  messaggio ricorda il livello se non e' Standard (`3 rows to translate (CT): ...`).
- Sotto la tabella una riga dice **quante traduzioni mancano**, per questa tabella e per tutte
  (`Missing in German (Standard): 21.053 in this table, 41.841 in all tables`; tra parentesi il livello scelto, se non e' All levels). Passa il mouse:
  vedi il conteggio per ogni tabella.
  Dopo ogni traduzione il conteggio si aggiorna da solo.
- **Advanced** (aperto all'inizio; un clic sul titolo lo chiude e allora dice cosa c'e' dentro, per esempio `Max rows 1`).
  Sulla stessa riga:
  - **Max rows**: quante righe tradurre al massimo in questa corsa (minimo 1). Utile per provare con poche righe.
  - **Update by keys**: vedi il capitolo 5. Se e' vuoto si traduce quello che manca. Se la sezione e' chiusa, scrivendo delle
    chiavi si riapre da sola.

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
c'e' qualcosa da guardare; se ci sono errori il messaggio mostra anche il primo (`First error ...`).
Nella riga **Details** sotto la barra di avanzamento c'e' sempre il link **Open the logs folder**, che apre la cartella dei
log; cliccando su **Details** si vedono anche i tempi (trascorso e previsto).

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
| E' di un livello diverso da quello scelto in **Level** (per esempio la chiave 100000 con Level = CT) | Non si scrive: Load la segnala nell'avviso giallo (`Skipped, not CT: 100000 (Standard)`) e il motivo finisce nel log delle righe saltate. Con Level = All non si scarta nulla. |
| Testo di partenza vuoto | Saltata (non c'e' niente da tradurre) |

Il controllo e' fatto chiave per chiave: con `100000, 100001` la prima puo' essere aggiornata e la seconda inserita.
Massimo 1000 chiavi; chiavi non valide (lettere in un campo numerico) vengono rifiutate con un messaggio.

## 6. Glossario

I testi passano da un glossario: **UMV** diventa **HU** nelle lingue diverse dall'italiano e i termini inglesi del prodotto
(per esempio *Supply Chain Planning*) restano invariati.

## 7. File che JT scrive

| Dove | Cosa |
|---|---|
| Nel database | Le traduzioni. Nella colonna "utente" delle righe inserite o aggiornate scrive la sigla `JT`, ma per le righe del livello CT scrive `ZFXCUSTOM` e per quelle del livello CW `ZFXINTEGR`. La categoria (il modulo: MES, WMS...) la copia dalla riga di partenza. |
| `%LOCALAPPDATA%\JT\Logs\JT_inserts_log_<data>.csv` | Una riga per ogni traduzione scritta (data, azione, codice, livello, utente scritto, lingue, testo, traduzione). Le righe CT e CW si ritrovano da qui, non dalla sigla `JT`. |
| `...\Logs\JT_errors_log_<data>.csv` | Le righe che il database ha rifiutato, con il motivo (colonna `reason`). |
| `...\Logs\JT_skipped_log_<data>.csv` | Le righe non tradotte perche' Azure ha dato errore, con il motivo. |

I file stanno in `%LOCALAPPDATA%\JT` (scrivilo nella barra degli indirizzi di Esplora file, oppure clicca **Open the logs
folder** nel programma), non nella cartella di JT: restano anche se aggiorni o cancelli il programma.

I file CSV si aprono con Excel. Se l'Excel italiano mette tutto in una colonna usa **Dati > Da testo/CSV** e scegli il
separatore "virgola".

## 8. Quando qualcosa non va

| Messaggio / sintomo | Cosa fare |
|---|---|
| `DPI-1047` o "Cannot locate a 64-bit Oracle Client library" al Connect | Manca il client Oracle a 64 bit sul PC (un client a 32 bit non basta). |
| `ORA-12541: no listener` / `ORA-12154` / `ORA-12545` | Host, porta o SID sbagliati, oppure il server non e' raggiungibile. |
| `ORA-01017: invalid username/password` | Utente o password errati. |
| `ORA-12899: valore troppo grande per la colonna ... (massimo: 100)` | La traduzione e' piu' lunga di quanto la colonna consente (per esempio la "Descr. Breve" delle triplette). La riga non viene scritta: compare negli errori e va inserita a mano con un testo piu' corto. |
| "Azure settings not found or not valid", oppure molte righe "Skipped" con `Azure error 401...` | Il servizio di traduzione non e' configurato o la chiave non e' piu' valida: rivolgiti a chi ti ha dato il programma. |
| Una tabella non compare | Non esiste in quel database: il programma mostra solo quelle presenti. |
| Il conteggio "Missing" non si calcola | La tabella non e' leggibile da questo utente; le altre funzionano. |

## 9. Buone pratiche

- Prova sempre con **Max rows = 1** o 5 prima di una corsa lunga.
- Ogni riga e' una chiamata Azure a pagamento: guarda i caratteri stimati dopo **Load**.
- Le traduzioni sono scritte subito (commit a ogni riga): per annullare bisogna usare il database, non basta chiudere JT.
- Chiudendo la finestra durante una traduzione, JT finisce la riga in corso, chiude la connessione ed esce.
