# JT - revisione UI/UX

Prima revisione: 2026-11-02, fatta provando la finestra vera (ridimensionamento, tastiera, chiusura, reattivita', contrasto,
scala dello schermo) su un Oracle finto. Script, output e screenshot dell'indagine sono in `scratchpad\ux\`.

## Stato dei punti

| # | Problema | Stato |
|---|---|---|
| 1 | Nella finestra di uscita Invio chiudeva sempre l'app | **Fatto**: Invio attiva il pulsante con il focus; all'apertura il focus e' su "Stay" |
| 2 | Nessun Stop; finestra bloccata durante la traduzione; Azure senza timeout | **Fatto**: traduzione in un thread, pulsante Stop (rosso), timeout 5 s + 30 s sulle chiamate ad Azure, chiusura che aspetta la riga in corso |
| 3 | Con un DB lento la finestra si blocca senza avviso | **Da decidere** (proposta sotto) |
| 4 | Tastiera: link "New connection" non raggiungibile con Tab, pulsante nascosto in Tab, nessun focus iniziale al passo 2 | Da decidere |
| 5 | Contorno di focus quasi invisibile (1,32:1) | Da decidere |
| 6 | "Max rows" accettava testo e diventava 0 | **Fatto**: solo cifre (anche incollando), minimo 1, messaggio chiaro |
| 7 | Conteggio fallito in verde; tabelle inesistenti mostrate lo stesso | **Fatto**: avviso con motivo; senza tabelle valide "No table available" e Load disattivato |
| 8 | Dopo "Connection established" cambiare i campi lasciava Next attivo sulla vecchia connessione | **Fatto**: ogni modifica chiude la connessione, disattiva Next e lo dice |
| 9 | Avanzamento vecchio dopo un nuovo Load; banner non coerente durante la corsa; campo chiavi sembra attivo; log nella cartella del codice | **Fatto**: avanzamento azzerato, banner "Translating...", campi disabilitati anche nell'aspetto, log in `Logs\` con il nome nel messaggio finale |
| 10 | Contrasto sotto 4,5:1 | **Fatto**: grigio `#5b6370` (5,55:1), pulsanti disattivati 5,4:1, bordi dei campi 3:1, icone dei banner >= 4,5:1 |
| 11 | Messaggi tagliati, banner a 2 righe fisse, "Trasl:" in italiano, "max 1000 keys", "Query error" senza causa, "progress will be lost" non vero | **Fatto**: banner che cresce col testo, accorciamento a parola intera (mai oltre il limite), tutto in inglese, motivo dell'errore mostrato, messaggi precisi |
| 12 | Scala dello schermo (testo sfocato / tagli) | **Fatto**: l'app dichiara "DPI aware", misure in `px()`, pallini dei passi in 4 dimensioni; verificato a 100/125/150/200% (limite al punto 14) |
| 13 | Seconda X apre una seconda conferma; conferma mette in pausa la traduzione; messaggio nascosto bloccante | **Fatto**: una sola conferma alla volta, la traduzione continua, messaggio nascosto non bloccante e disattivato durante la traduzione |
| 14 | A 200% su uno schermo alto 1440 px la finestra e' piu' alta dello schermo e la riga in fondo (COMING SOON) viene tagliata | Nuovo, da decidere: layout compatto (meno margini, avvisi in una riga) o scorrimento |
| 15 | Il nome del database collegato non si vedeva | **Fatto**: riga grigia in basso "Connected to <database> · <host> · user <utente>", con i dettagli nel suggerimento |

## Proposta per il punto 3 (DB lento)

Oggi ogni operazione con il database blocca la finestra. Due livelli:

1. **A basso costo.** All'apertura del passo 2 si fa una query per tabella per sapere quali esistono e se ne contano 8: si controllano le
   tabelle una volta sola al collegamento, e all'apertura si conta solo la tabella scelta (le altre a richiesta, dal suggerimento).
2. **Strutturale.** Collegamento, caricamento e conteggio girano nel thread di lavoro (lo stesso gia' usato per la traduzione), con
   il testo "Connecting... / Counting... / Loading..." e senza blocchi, qualunque sia la velocita' del DB.

## Gia' funzionava (provato)

La connessione si chiude in tutti i 10 scenari di chiusura provati; ridimensionamento con testi che vanno a capo e barra che si allunga;
la selezione si invalida a ogni modifica dei campi; i suggerimenti restano dentro lo schermo; il cursore di attesa torna normale dopo un errore.

## Non provato

Una vera chiamata Azure bloccata (il timeout e' provato con un finto), il comportamento di `ROWNUM` su Oracle vero, il "non risponde" che
Windows mostra dopo 5 s (ora la finestra resta viva), piu' monitor con scale diverse, finestra alta su schermo 1080p.
