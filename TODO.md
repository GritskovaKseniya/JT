# TODO

Cose note da fare o da correggere, in ordine di importanza. Il piano completo di JTools e' in `PIANO_TOOLKIT.md`.

## Traduttore SQL <-> TecSQL

Fatto (passo 8): alias, `DATE()`, `LIMIT` e le subquery di SQL -> TecSQL (vedi sotto). Resta:

- **TecSQL -> SQL: UPDATE, INSERT, DELETE e LOCK TABLE non si traducono** (11 coppie dei test di Orione); Orione li traduce.
  Rimandato: per ora si traducono solo le SELECT.
- **`HAVING` prima di `GROUP BY` non viene riordinato** (1 coppia): innocuo in Oracle, Orione lo riordina.
- **`LIMIT` vale prima dell'`ORDER BY`** (come in Orione): `... ORDER BY x LIMIT 5` da' le prime 5 righe e poi le ordina, non le 5
  prime in ordine. Per averle in ordine serve una subquery ordinata. Da dire all'utente nello strumento.
- **Le funzioni di TecSQL (`YEAR`, `MONTH`, `DAY`, `WEEK`, `TODAY`, `TIME`, `LPAD`...) non si traducono**: Orione le converte per ogni
  database (per Oracle `TO_CHAR(...)`, `SYSDATE`...); JT le lascia com'e'. Le coppie dei test di Orione che le usano passano dai
  `ParameterValue` e non sono tra quelle confrontate: da verificare a parte.
- **I messaggi e i commenti dentro `tecsql_translator.py` sono in parte in italiano** (i commenti): da uniformare.
- **Dubbio di fondo:** il traduttore e' scritto a mano e copre una parte di TecSQL. La grammatica vera e' in Orione
  (`parser\TecSqlParser.cup`, 82 regole, e `TecSqlParser.jlex`): portarla in Python (per esempio con `lark`) darebbe un traduttore che
  capisce tutto TecSQL, con tutti i test di Orione come prova. E' un lavoro grande (la grammatica e' piccola, ma i costruttori di SQL
  sono ~3.000 righe): da decidere.
- **I dati dei test di Orione non stanno nel repository** (pubblico): `tests\orione_*.json`, creati con `tools\orione_pairs.py`.
  `python tests\test_orione_pairs.py --regenerate` aggiorna l'elenco delle lacune dopo una correzione.
- **SQL -> TecSQL esiste solo in JCTNT** (Orione non lo ha): non c'e' un riferimento, solo i nostri test.

## Idee rimandate

- Segnare nell'anteprima le righe troppo lunghe per la colonna.
- Modificare una traduzione nella tabella dell'anteprima prima di scrivere.
- "Undo last run" dentro l'app, con l'anteprima delle righe che cambierebbe.
- Profili di connessione salvati (passo 6b).
- Limiti facoltativi per chi ha la chiave (massimo di righe per corsa, anteprima obbligatoria, livelli ammessi).
- Passare a `oracledb` (`cx_Oracle` e' dichiarato obsoleto) quando serve.
