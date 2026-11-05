"""JTools: traduzione di stringhe e opzioni di Jflex con Azure Translator.

Livelli (dall'alto verso il basso, ognuno usa solo quelli sotto di se'):

    ui/        interfaccia Tkinter (schermate, widget, tema)        - nessuna logica di business
    service    selezione delle righe, traduzione, scrittura          - nessun Tkinter
    tables     una classe per tabella (SQL, righe, INSERT/UPDATE)
    azure      client Azure Translator (usa il glossario)
    glossary   termini da sostituire / non tradurre
    db         connessione Oracle, cursori, metadati
    settings, catalog, jsonstore, config, logs   supporto
"""
