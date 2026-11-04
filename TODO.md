# TODO

Cose note da fare o da correggere, in ordine di importanza. Il piano completo di JTools e' in `PIANO_TOOLKIT.md`.

## Bug

- **SQL -> TecSQL non traduce una subquery con una seconda tabella e senza campi qualificati, e dice "riuscito".**
  `translate_sql_to_tecsql('SELECT COUNT(*) FROM GD_LIRIG WHERE LIRIG_LICOD IN (SELECT LITES_LICOD FROM GD_LITES WHERE LITES_CATLI = \'LL\')')`
  traduce solo la query esterna: la subquery resta `SELECT LITES_LICOD FROM GD_LITES ...` ma `success` e' `True` e
  `partial_translation` e' `False`, quindi nessun avviso. Il problema c'era gia' in JCTNT (`tecsql_translator.py`, il suo test
  falliva anche li'). Provato con il dizionario di prova (RigaListino / TestataListino).
  Da fare: capire perche' `_translate_subqueries_in_sql` non lo prende (forse solo con campi qualificati), correggerlo,
  e se non si riesce almeno dire "tradotto in parte". I due test che lo mostrano sono `expectedFailure` in
  `tests/test_tecsql_sql_to_tecsql.py` (`test_subquery_fields_translated`, `test_full_multiline_query`): quando funziona,
  togliere `@unittest.expectedFailure`. Si affronta nel passo 8 (schermata SQL <-> TecSQL).

## Pulizia (passo 7 del piano)

- Trasformare le mappe globali di `tecsql_translator.py` in una classe `Dictionary` senza stato condiviso. *(in corso)*
- Messaggi d'errore del traduttore in inglese (oggi in italiano come nell'originale). *(in corso)*

## Idee rimandate

- Segnare nell'anteprima le righe troppo lunghe per la colonna.
- Modificare una traduzione nella tabella dell'anteprima prima di scrivere.
- "Undo last run" dentro l'app, con l'anteprima delle righe che cambierebbe.
- Profili di connessione salvati (passo 6b).
- Limiti facoltativi per chi ha la chiave (massimo di righe per corsa, anteprima obbligatoria, livelli ammessi).
- Passare a `oracledb` (`cx_Oracle` e' dichiarato obsoleto) quando serve.
