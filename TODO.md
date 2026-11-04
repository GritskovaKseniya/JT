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

- **Lacune del traduttore TecSQL -> SQL rispetto a Orione** (il vero traduttore: `JFlex2.Orione\srcJAVA\it\tec\framework\sql\parser`,
  grammatica in `parser\TecSqlParser.cup`; il traduttore di JT e' quello di JCTNT, scritto a mano su un modello piu' semplice).
  Misurato con i test di Orione (79 coppie TecSQL -> SQL Oracle, `tests\test_orione_pairs.py`): **23 combaciano, 56 no**.
  Le 56 per motivo (l'elenco esatto e' in `tests\orione_known_gaps.json`):
  - **un campo scritto con un alias esce con il nome della tabella invece dell'alias (5)**: `FROM $FwTables T1 ... T1.TableName`
    diventa `FW_TABLES.TABLENAME` ma la tabella e' `FW_TABLES T1`: in Oracle e' `ORA-00904`, e con un self-join i due alias
    diventano la stessa cosa. **E' il difetto piu' serio: gli alias sono normali.** (Gli esempi dei test di JCTNT lo mascheravano.)
  - **`DATE('gg/mm/aaaa')` non diventa `TO_DATE('aaaa-mm-gg')` (6)**.
  - **`LIMIT n` diventa `FETCH FIRST n ROWS ONLY` (1)**: funziona da Oracle 12c; Orione scrive `AND ROWNUM <= n` che va anche su
    Oracle 11 (JCTNT cita un client Oracle 11).
  - **solo SELECT (11)**: UPDATE, INSERT, DELETE e LOCK TABLE non si traducono (Orione si').
  - **`HAVING` prima di `GROUP BY` non si riordina (1)**: innocuo in Oracle.
  - **32 coppie non si possono confrontare**: usano descrittori che esistono solo nei test di Orione (`$TestTransSource`...).
  Niente di tutto questo e' stato corretto: serve decidere cosa conta per chi usa lo strumento (le query vere sono quasi tutte SELECT?).
  I dati dei test (coppie, descrittori, elenco delle lacune) **non stanno nel repository** (pubblico): si creano in locale con `tools\orione_pairs.py`. Quando si corregge una lacuna `tests\test_orione_pairs.py` lo dice (la coppia ora combacia): `python tests\test_orione_pairs.py
  --regenerate` aggiorna l'elenco.
- **SQL -> TecSQL esiste solo in JCTNT** (Orione non lo ha, non gli serve): non c'e' un riferimento, solo i nostri test.

## Idee rimandate

- Segnare nell'anteprima le righe troppo lunghe per la colonna.
- Modificare una traduzione nella tabella dell'anteprima prima di scrivere.
- "Undo last run" dentro l'app, con l'anteprima delle righe che cambierebbe.
- Profili di connessione salvati (passo 6b).
- Limiti facoltativi per chi ha la chiave (massimo di righe per corsa, anteprima obbligatoria, livelli ammessi).
- Passare a `oracledb` (`cx_Oracle` e' dichiarato obsoleto) quando serve.
