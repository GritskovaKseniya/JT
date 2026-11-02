"""jt.db.Database con un driver Oracle finto."""
import unittest

from helpers import COLUMNS, FakeDriver, JtCase
from jt.db import Database
from jt.tables import get_table


class DatabaseCase(JtCase):
    def setUp(self):
        super().setUp()
        self.driver = FakeDriver()
        self.state = self.driver.db
        self.db = Database(self.driver)

    def connect(self):
        self.db.connect('host', '1521', 'SID', 'user', 'pwd')
        return self.state.conns[-1]


class ConnectionTests(DatabaseCase):
    def test_connect(self):
        self.assertFalse(self.db.connected)
        conn = self.connect()
        self.assertTrue(self.db.connected)
        self.assertEqual(self.driver.dsns, ['host:1521/SID'])
        self.assertEqual(self.driver.connects, [('user', 'pwd', 'host:1521/SID')])
        self.assertFalse(conn.closed)

    def test_connect_twice_closes_previous_connection(self):
        first = self.connect()
        second = self.connect()
        self.assertTrue(first.closed)
        self.assertFalse(second.closed)
        self.assertEqual(len(self.state.conns), 2)

    def test_connect_twice_closes_open_cursors(self):
        self.connect()
        cursor = self.db.open_cursor()
        self.connect()
        self.assertTrue(cursor.closed)

    def test_failed_connect_leaves_no_connection_and_closes_old_one(self):
        first = self.connect()
        self.state.fail_connect = True
        with self.assertRaises(RuntimeError):
            self.db.connect('host', '1521', 'SID', 'user', 'pwd')
        self.assertTrue(first.closed)
        self.assertFalse(self.db.connected)
        self.assertEqual(len(self.state.conns), 1)

    def test_failed_first_connect(self):
        self.state.fail_connect = True
        with self.assertRaises(RuntimeError):
            self.connect()
        self.assertFalse(self.db.connected)

    def test_close_closes_cursors_and_connection(self):
        conn = self.connect()
        c1, c2 = self.db.open_cursor(), self.db.open_cursor()
        self.db.close()
        self.assertTrue(c1.closed and c2.closed and conn.closed)
        self.assertFalse(self.db.connected)

    def test_close_is_idempotent_and_safe_without_connection(self):
        self.db.close()
        conn = self.connect()
        self.db.close()
        self.db.close()
        self.assertTrue(conn.closed)
        self.assertFalse(self.db.connected)

    def test_close_tolerates_close_error(self):
        self.connect()
        self.state.close_error = True
        self.db.close()                      # non solleva
        self.assertFalse(self.db.connected)
        self.db.close()

    def test_close_tolerates_cursor_close_error(self):
        self.connect()
        cursor = self.db.open_cursor()

        def boom():
            raise RuntimeError('cursor close failed')
        cursor.close = boom
        other = self.db.open_cursor()
        self.db.close_cursors()
        self.assertTrue(other.closed)

    def test_reconnect_after_close(self):
        self.connect()
        self.db.close()
        conn = self.connect()
        self.assertTrue(self.db.connected)
        self.assertFalse(conn.closed)


class ColumnsTests(DatabaseCase):
    def test_columns_come_from_cursor_description(self):
        self.connect()
        self.assertEqual(self.db.columns('FW_STRINGS'), COLUMNS['FW_STRINGS'])
        self.assertEqual(self.state.log[0][0], 'SELECT * FROM FW_STRINGS WHERE 1 = 0')

    def test_columns_never_use_user_tab_columns(self):
        self.connect()
        for name in COLUMNS:
            self.db.columns(name)
        self.assertEqual(self.state.count('user_tab_columns'), 0)
        self.assertEqual(self.state.count('USER_TAB_COLUMNS'), 0)

    def test_columns_are_cached(self):
        conn = self.connect()
        self.db.columns('FW_STRINGS')
        self.db.columns('FW_STRINGS')
        self.assertEqual(self.state.count('WHERE 1 = 0'), 1)
        self.db.columns('FW_OPZIONI')
        self.assertEqual(self.state.count('WHERE 1 = 0'), 2)
        self.assertTrue(all(c.closed for c in conn.cursors))

    def test_cache_cleared_on_reconnect(self):
        self.connect()
        self.db.columns('FW_STRINGS')
        self.state.columns['FW_STRINGS'] = ['A', 'B']
        self.connect()
        self.assertEqual(self.db.columns('FW_STRINGS'), ['A', 'B'])

    def test_columns_closes_cursor_on_error(self):
        conn = self.connect()
        self.state.fail_sql = ['WHERE 1 = 0']
        with self.assertRaises(RuntimeError):
            self.db.columns('FW_STRINGS')
        self.assertTrue(conn.cursors[-1].closed)

    def test_resolve(self):
        self.connect()
        plain = get_table('FW_STRINGS')
        self.assertIs(self.db.resolve(plain), plain)
        self.assertEqual(self.state.count('WHERE 1 = 0'), 0)
        bound = self.db.resolve(get_table('FW_DOCU_NODES_T'))
        self.assertEqual((bound.lang_col, bound.select_key), ('LANG', 'NODEID'))


class ExistingTablesTests(DatabaseCase):
    ENTRIES = [{'table': 'FW_STRINGS'}, {'table': 'BAD'}, {'table': 'FW_OPZIONI'}]

    def test_empty_when_not_connected(self):
        self.assertEqual(self.db.existing_tables(self.ENTRIES), [])
        self.assertEqual(self.state.log, [])

    def test_invalid_tables_are_skipped(self):
        self.connect()
        self.state.invalid_tables = {'BAD'}
        self.assertEqual(self.db.existing_tables(self.ENTRIES), [{'table': 'FW_STRINGS'}, {'table': 'FW_OPZIONI'}])
        self.assertEqual(self.state.log[0][0], 'SELECT 1 FROM FW_STRINGS WHERE ROWNUM = 1')

    def test_an_empty_table_still_exists(self):
        self.connect()
        self.state.empty_tables = {'FW_OPZIONI', 'FW_STRINGS'}
        self.state.invalid_tables = {'BAD'}
        self.assertEqual(self.db.existing_tables(self.ENTRIES), [{'table': 'FW_STRINGS'}, {'table': 'FW_OPZIONI'}])

    def test_all_valid(self):
        self.connect()
        self.assertEqual(self.db.existing_tables(self.ENTRIES), self.ENTRIES)

    def test_after_close_returns_empty(self):
        self.connect()
        self.db.close()
        self.assertEqual(self.db.existing_tables(self.ENTRIES), [])


class StatementTests(DatabaseCase):
    def test_scalar_and_fetch_all_close_their_cursor(self):
        conn = self.connect()
        self.state.missing['FW_STRINGS'] = 7
        sql = 'SELECT COUNT(*) FROM FW_STRINGS X WHERE X.language = :li'
        self.assertEqual(self.db.scalar(sql, {'li': 'it'}), 7)
        self.assertEqual(self.db.fetch_all('SELECT * FROM FW_STRINGS X WHERE X.language = :li', {'li': 'it'}),
                         self.state.source['FW_STRINGS'])
        self.assertEqual(self.state.log[0], (sql, {'li': 'it'}))
        self.assertTrue(all(c.closed for c in conn.cursors))

    def test_scalar_without_binds_sends_empty_dict(self):
        self.connect()
        self.db.scalar('SELECT 1 FROM FW_STRINGS WHERE ROWNUM = 1')
        self.assertEqual(self.state.log[0][1], {})

    def test_scalar_closes_cursor_on_error(self):
        conn = self.connect()
        self.state.fail_sql = ['ROWNUM']
        with self.assertRaises(RuntimeError):
            self.db.scalar('SELECT 1 FROM FW_STRINGS WHERE ROWNUM = 1')
        self.assertTrue(conn.cursors[-1].closed)

    def test_execute_and_commit(self):
        conn = self.connect()
        self.db.execute('INSERT INTO T VALUES (:1, :2)', ['a', 1])
        self.db.execute('UPDATE T SET x = :s0', {'s0': 'v'})
        self.db.execute('INSERT INTO T VALUES (1)')
        self.assertEqual(self.state.log, [('INSERT INTO T VALUES (:1, :2)', ['a', 1]),
                                          ('UPDATE T SET x = :s0', {'s0': 'v'}),
                                          ('INSERT INTO T VALUES (1)', None)])
        self.assertEqual(conn.commits, 0)
        self.db.commit()
        self.assertEqual(conn.commits, 1)

    def test_write_cursor_is_reused_then_renewed_after_close_cursors(self):
        conn = self.connect()
        base = len(conn.cursors)          # connect() usa un cursore (poi chiuso) per leggere il nome del database
        self.db.execute('INSERT INTO T VALUES (1)')
        self.db.execute('INSERT INTO T VALUES (2)')
        self.assertEqual(len(conn.cursors), base + 1)
        self.db.close_cursors()
        self.assertTrue(conn.cursors[base].closed)
        self.db.execute('INSERT INTO T VALUES (3)')
        self.assertEqual(len(conn.cursors), base + 2)
        self.assertFalse(conn.cursors[base + 1].closed)

    def test_open_cursors_are_tracked_and_closed(self):
        conn = self.connect()
        cursors = [self.db.open_cursor() for _ in range(3)]
        self.assertTrue(all(c in conn.cursors for c in cursors))
        self.assertFalse(any(c.closed for c in cursors))
        self.db.close_cursors()
        self.assertTrue(all(c.closed for c in cursors))
        self.db.close_cursors()              # seconda volta: niente da fare
        self.assertTrue(self.db.connected)


if __name__ == '__main__':
    unittest.main()
