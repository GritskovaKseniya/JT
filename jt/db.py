"""Accesso a Oracle: connessione, cursori e metadati. Nessuna logica di traduzione."""


class Database:
    def __init__(self, driver=None):
        """`driver` e' il modulo Oracle (cx_Oracle); sostituibile nei test."""
        self._driver = driver
        self._conn = None
        self._cursors = []
        self._write_cursor = None
        self._columns = {}
        self.info = None          # {host, port, sid, user, db_name} della connessione aperta

    @property
    def driver(self):
        if self._driver is None:
            import cx_Oracle
            self._driver = cx_Oracle
        return self._driver

    @property
    def connected(self):
        return self._conn is not None

    # ------------------------------------------------------------- connessione

    def connect(self, host, port, sid, user, password):
        self.close()          # niente connessioni orfane se si ricollega piu' volte
        dsn = self.driver.makedsn(host, port, sid)
        self._conn = self.driver.connect(user, password, dsn=dsn, threaded=True)     # usata anche dal thread di traduzione
        self._columns = {}
        self.info = {'host': host, 'port': port, 'sid': sid, 'user': user, 'db_name': self._server_db_name()}

    def _server_db_name(self):
        """Nome del database cosi' come lo dichiara il server (non quello digitato); None se non lo da'."""
        try:
            return self.scalar("SELECT SYS_CONTEXT('USERENV', 'DB_NAME') FROM dual")
        except Exception:
            return None

    def close(self):
        """Chiude cursori e connessione. Sicuro da chiamare piu' volte e senza connessione: non solleva errori."""
        self.info = None
        self.close_cursors()
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as e:
                print(f'Error while closing the connection: {e}')
            self._conn = None

    # ------------------------------------------------------------------ cursori

    def open_cursor(self):
        cursor = self._conn.cursor()
        self._cursors.append(cursor)
        return cursor

    def close_cursors(self):
        for cursor in self._cursors:
            try:
                cursor.close()
            except Exception:
                pass
        self._cursors = []
        self._write_cursor = None

    # ------------------------------------------------------------------- letture

    def scalar(self, sql, binds=None):
        """Primo valore della prima riga."""
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, binds or {})
            return cursor.fetchone()[0]
        finally:
            cursor.close()

    def fetch_all(self, sql, binds=None):
        cursor = self._conn.cursor()
        try:
            cursor.execute(sql, binds or {})
            return cursor.fetchall()
        finally:
            cursor.close()

    def columns(self, table):
        """Nomi colonna nell'ordine della tabella. Letti dal cursore: funziona anche quando la tabella e' un
        sinonimo o sta in un altro schema (dove user_tab_columns e' vuota)."""
        if table not in self._columns:
            cursor = self._conn.cursor()
            try:
                cursor.execute(f'SELECT * FROM {table} WHERE 1 = 0')
                self._columns[table] = [d[0] for d in cursor.description]
            finally:
                cursor.close()
        return self._columns[table]

    def resolve(self, spec):
        """La tabella con i nomi colonna reali, per le tabelle che li leggono dal DB."""
        return spec.bind_columns(self.columns(spec.name)) if spec.needs_columns else spec

    def table_exists(self, name):
        """True se la tabella esiste (e si puo' leggere) su questo DB."""
        if not self.connected:
            return False
        try:
            self.fetch_all(f"SELECT 1 FROM {name} WHERE ROWNUM = 1")
            return True
        except Exception as e:
            print(f"Table {name} not valid: {e}")
            return False

    def existing_tables(self, entries):
        """Le voci di tables.json la cui tabella esiste (e si puo' leggere) su questo DB."""
        if not self.connected:
            return []
        valid = []
        for entry in entries:
            try:
                self.fetch_all(f"SELECT 1 FROM {entry['table']} WHERE ROWNUM = 1")      # nessuna riga = tabella vuota, ma c'e'
                valid.append(entry)
            except Exception as e:
                print(f"Table {entry['table']} not valid: {e}")
        return valid

    # ------------------------------------------------------------------- scritture

    def execute(self, sql, binds=None):
        if self._write_cursor is None:
            self._write_cursor = self.open_cursor()
        if binds is None:
            self._write_cursor.execute(sql)
        else:
            self._write_cursor.execute(sql, binds)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        """Annulla quello che non e' stato confermato. Non solleva mai: serve proprio quando qualcosa e' gia' andato storto."""
        try:
            if self._conn is not None:
                self._conn.rollback()
        except Exception as e:
            print(f'Rollback failed: {e}')
