"""Moduli di supporto: esecuzione in un thread, testi, informazioni sulla connessione, timeout di Azure, log."""
import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import helpers
from helpers import FakeAzure, FakeDriver, JtCase
from jt.azure import AzureTranslator
from jt.config import AZURE_TIMEOUT
from jt.db import Database
from jt.glossary import Glossary
from jt.logs import write_csv, write_run_logs
from jt.runner import DONE, ERROR, PROGRESS, BackgroundRunner, InlineRunner
from jt.service import RunResult
from jt.tables import MAX_KEYS, TooManyKeys, get_table
from jt.ui.texts import fmt_count, reason, shorten


def wait_for(runner, timeout=5.0):
    """Raccoglie gli eventi finche' non arriva DONE o ERROR (con un limite di tempo)."""
    events, deadline = [], time.time() + timeout
    while time.time() < deadline:
        events += runner.poll()
        if any(kind in (DONE, ERROR) for kind, _ in events):
            return events
        time.sleep(0.01)
    raise AssertionError(f'il lavoro non e finito entro {timeout} s: {events}')


class BackgroundRunnerTests(unittest.TestCase):
    def test_work_runs_in_another_thread_and_reports_progress_then_done(self):
        runner = BackgroundRunner()
        seen = {}

        def work(emit, should_stop):
            seen['thread'] = threading.current_thread()
            emit(1)
            emit(2)
            return 'result'

        runner.start(work)
        events = wait_for(runner)
        self.assertEqual(events, [(PROGRESS, 1), (PROGRESS, 2), (DONE, 'result')])
        self.assertIsNot(seen['thread'], threading.current_thread())
        self.assertEqual(seen['thread'].name, 'jt-worker')

    def test_an_exception_becomes_an_error_event(self):
        runner = BackgroundRunner()

        def work(emit, should_stop):
            raise ValueError('boom')

        runner.start(work)
        (kind, error), = wait_for(runner)
        self.assertEqual(kind, ERROR)
        self.assertIsInstance(error, ValueError)

    def test_stop_is_seen_by_the_work_and_cleared_by_the_next_start(self):
        runner = BackgroundRunner()
        started = threading.Event()

        def work(emit, should_stop):
            started.set()
            while not should_stop():
                time.sleep(0.005)
            return 'stopped'

        runner.start(work)
        self.assertTrue(started.wait(2))
        self.assertTrue(runner.running)
        runner.stop()
        self.assertEqual(wait_for(runner)[-1], (DONE, 'stopped'))
        runner.start(lambda emit, should_stop: should_stop())      # un nuovo lavoro riparte senza il vecchio stop
        self.assertEqual(wait_for(runner)[-1], (DONE, False))

    def test_a_second_job_cannot_start_while_one_runs(self):
        runner = BackgroundRunner()
        release = threading.Event()
        runner.start(lambda emit, should_stop: release.wait(5))
        try:
            with self.assertRaises(RuntimeError):
                runner.start(lambda emit, should_stop: None)
        finally:
            release.set()
            wait_for(runner)
        self.assertFalse(self._wait_not_running(runner))

    @staticmethod
    def _wait_not_running(runner):
        deadline = time.time() + 2
        while runner.running and time.time() < deadline:
            time.sleep(0.005)
        return runner.running

    def test_poll_without_events_is_empty_and_drains(self):
        runner = BackgroundRunner()
        self.assertEqual(runner.poll(), [])
        runner.start(lambda emit, should_stop: emit('x') or 'y')
        wait_for(runner)
        self.assertEqual(runner.poll(), [])


class InlineRunnerTests(unittest.TestCase):
    def test_runs_immediately_in_the_calling_thread(self):
        runner = InlineRunner()
        seen = []
        runner.start(lambda emit, should_stop: (seen.append(threading.current_thread()), emit(7), 'r')[2])
        self.assertIs(seen[0], threading.current_thread())
        self.assertFalse(runner.running)
        self.assertEqual(runner.poll(), [(PROGRESS, 7), (DONE, 'r')])

    def test_errors_and_stop_work_like_the_background_runner(self):
        runner = InlineRunner()
        runner.start(lambda emit, should_stop: 1 / 0)
        (kind, error), = runner.poll()
        self.assertEqual((kind, type(error)), (ERROR, ZeroDivisionError))
        runner.stop()
        runner.start(lambda emit, should_stop: should_stop())
        self.assertEqual(runner.poll(), [(DONE, False)])


class TextsTests(unittest.TestCase):
    def test_fmt_count(self):
        self.assertEqual([fmt_count(n) for n in (0, 7, 1234, 1234567, None)], ['0', '7', '1.234', '1.234.567', '?'])

    def test_shorten_cuts_at_a_word_boundary_and_adds_dots(self):
        text = 'ORA-12541: TNS:no listener while connecting to the database server on this host'
        short = shorten(text, 40)
        self.assertTrue(short.endswith('...'))
        self.assertLessEqual(len(short), 40)               # puntini compresi
        self.assertNotIn('listene...', short)               # mai a meta' parola
        self.assertEqual(shorten('short text', 40), 'short text')
        self.assertEqual(shorten('a   b\n c', 40), 'a b c')   # spazi e a capo compattati

    def test_shorten_handles_a_single_very_long_word(self):
        self.assertEqual(shorten('x' * 300, 20), 'x' * 17 + '...')

    def test_shorten_never_exceeds_the_limit_for_any_input(self):
        samples = ['', 'a', 'word ' * 50, 'x' * 99, 'a, b; c: d. ' * 20, 'ORA-12541: ' * 30, 'lungo' * 40]
        for text in samples:
            for limit in range(4, 130, 7):
                short = shorten(text, limit)
                self.assertLessEqual(len(short), limit, (text[:12], limit))
                if len(' '.join(text.split())) > limit:
                    self.assertTrue(short.endswith('...'), (text[:12], limit))

    def test_reason_is_the_first_line_only(self):
        self.assertEqual(reason(RuntimeError('ORA-12541: no listener\nsecond line\nthird')), 'ORA-12541: no listener')
        self.assertEqual(reason(RuntimeError('')), '')
        self.assertTrue(reason(RuntimeError('word ' * 100)).endswith('...'))


class DatabaseInfoTests(JtCase):
    def setUp(self):
        super().setUp()
        self.driver = FakeDriver()
        self.state = self.driver.db
        self.db = Database(self.driver)

    def test_info_is_none_before_connecting(self):
        self.assertIsNone(self.db.info)

    def test_info_has_the_typed_values_and_the_name_declared_by_the_server(self):
        self.state.db_name = 'PRODDB'
        self.db.connect('vm-1', '1521', 'ORCL', 'scott', 'secret')
        self.assertEqual(self.db.info, {'host': 'vm-1', 'port': '1521', 'sid': 'ORCL', 'user': 'scott',
                                        'db_name': 'PRODDB'})
        self.assertNotIn('secret', repr(self.db.info))      # la password non resta nelle informazioni

    def test_db_name_is_none_when_the_server_does_not_answer(self):
        self.state.db_name = None
        self.db.connect('h', '1521', 'S', 'u', 'p')
        self.assertIsNone(self.db.info['db_name'])
        self.assertTrue(self.db.connected)                  # il nome mancante non impedisce la connessione

    def test_info_is_cleared_on_close_and_replaced_on_reconnect(self):
        self.db.connect('h1', '1521', 'S1', 'u1', 'p')
        self.db.connect('h2', '1521', 'S2', 'u2', 'p')
        self.assertEqual((self.db.info['host'], self.db.info['user']), ('h2', 'u2'))
        self.db.close()
        self.assertIsNone(self.db.info)
        self.db.close()
        self.assertIsNone(self.db.info)

    def test_failed_connect_leaves_no_info(self):
        self.db.connect('h', '1521', 'S', 'u', 'p')
        self.state.fail_connect = True
        with self.assertRaises(Exception):
            self.db.connect('h2', '1521', 'S', 'u', 'p')
        self.assertIsNone(self.db.info)
        self.assertFalse(self.db.connected)

    def test_the_name_query_does_not_pollute_the_work_log(self):
        self.db.connect('h', '1521', 'S', 'u', 'p')
        self.assertEqual(self.state.log, [])


class KeyLimitTests(unittest.TestCase):
    def test_too_many_keys_is_its_own_error_but_still_a_value_error(self):
        spec = get_table('FW_STRINGS')
        keys = ','.join(str(i) for i in range(MAX_KEYS + 1))
        with self.assertRaises(TooManyKeys):
            spec.parse_keys(keys)
        self.assertTrue(issubclass(TooManyKeys, ValueError))
        self.assertEqual(len(spec.parse_keys(','.join(str(i) for i in range(MAX_KEYS)))), MAX_KEYS)

    def test_invalid_key_is_not_the_too_many_error(self):
        with self.assertRaises(ValueError) as caught:
            get_table('FW_STRINGS').parse_keys('12, x')
        self.assertNotIsInstance(caught.exception, TooManyKeys)


class AzureTimeoutTests(unittest.TestCase):
    def translate(self, **kwargs):
        azure = FakeAzure()
        translator = AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=azure, **kwargs)
        translator.translate('Ciao', 'it', 'en')
        return azure.calls[0]

    def test_every_call_has_a_timeout(self):
        self.assertEqual(self.translate()['timeout'], AZURE_TIMEOUT)

    def test_the_default_timeout_is_finite_and_the_timeout_can_be_changed(self):
        connect, read = AZURE_TIMEOUT
        self.assertTrue(0 < connect <= 10 and 0 < read <= 60)
        self.assertEqual(self.translate(timeout=(1, 2))['timeout'], (1, 2))

    def test_a_timeout_error_propagates_so_the_row_is_skipped(self):
        def slow(url, params=None, headers=None, json=None, timeout=None):
            raise TimeoutError('read timed out')
        with self.assertRaises(TimeoutError):
            AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=slow).translate('Ciao', 'it', 'en')


class LogFolderTests(JtCase):
    ROWS = [{'date': 'd', 'action': 'insert', 'code': 1, 'lng_in': 'it', 'lng_out': 'en', 'input': 'a', 'output': 'b'}]

    def test_the_folder_is_created_on_demand(self):
        folder = os.path.join(self.tmp, 'Logs', 'nested')
        path = write_csv(self.ROWS, 'JT_inserts_log_', folder)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.dirname(path), folder)

    def test_run_logs_return_the_written_paths_and_nothing_for_an_empty_run(self):
        folder = os.path.join(self.tmp, 'Logs')
        self.assertEqual(write_run_logs(RunResult(), folder), [])
        self.assertFalse(os.path.exists(folder))              # niente righe = niente cartella
        result = RunResult(successes=self.ROWS, errors=[{'date': 'd', 'code': 2, 'lng_in': 'it', 'lng_out': 'en', 'input': 'x'}])
        paths = write_run_logs(result, folder)
        self.assertEqual(len(paths), 2)
        self.assertTrue(os.path.basename(paths[0]).startswith('JT_inserts_log_'))
        self.assertTrue(os.path.basename(paths[1]).startswith('JT_errors_log_'))


class EntryPointTests(unittest.TestCase):
    """JT.py e' l'unico punto che apre la finestra: si controlla leggendone il codice (senza aprire nulla)."""

    @staticmethod
    def main_function():
        import ast
        with open(os.path.join(helpers.ROOT, 'JT.py'), encoding='utf-8') as f:
            tree = ast.parse(f.read())
        return next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')

    def test_dpi_awareness_is_declared_before_the_window_is_created(self):
        import ast
        lines = {ast.unparse(node.func): node.lineno for node in ast.walk(self.main_function())
                 if isinstance(node, ast.Call)}
        self.assertIn('enable_dpi_awareness', lines)
        self.assertIn('tk.Tk', lines)
        self.assertLess(lines['enable_dpi_awareness'], lines['tk.Tk'])

    def test_the_connection_is_closed_even_if_the_window_loop_fails(self):
        import ast
        tries = [node for node in ast.walk(self.main_function()) if isinstance(node, ast.Try)]
        self.assertTrue(tries)
        closing = [ast.unparse(call.func) for call in ast.walk(ast.Module(body=tries[0].finalbody, type_ignores=[]))
                   if isinstance(call, ast.Call)]
        self.assertIn('app.shutdown', closing)


if __name__ == '__main__':
    unittest.main()


class AzureErrorTests(unittest.TestCase):
    def translate(self, payload):
        response = MagicMock()
        response.json.return_value = payload
        return AzureTranslator(helpers.FAKE_AZURE, Glossary(), post=lambda *a, **k: response).translate('Ciao', 'it', 'en')

    def test_the_real_azure_error_is_reported(self):
        with self.assertRaisesRegex(RuntimeError, 'Azure error 401000: The request is not authorized'):
            self.translate({'error': {'code': 401000, 'message': 'The request is not authorized'}})

    def test_a_good_answer_still_works(self):
        self.assertEqual(self.translate([{'translations': [{'text': 'Hello'}]}]), 'Hello')


class RunnerJoinTests(unittest.TestCase):
    def test_join_waits_for_the_job_and_is_harmless_without_one(self):
        from jt.runner import BackgroundRunner
        runner = BackgroundRunner()
        runner.join(1)
        runner.start(lambda emit, should_stop: time.sleep(0.2) or 'x')
        runner.join(5)
        self.assertFalse(runner.running)


class CsvForExcelTests(JtCase):
    def test_the_log_starts_with_a_bom_so_excel_reads_accents_correctly(self):
        path = write_csv([{'input': 'Utenti e Men\u00f9', 'output': 'Men\u00fcs'}], 'x_', self.tmp)
        with open(path, 'rb') as f:
            raw = f.read()
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'))
        self.assertIn('Men\u00f9'.encode('utf-8'), raw)
        self.assertNotIn(b'\xef\xbb\xbf', raw[3:])


class DataFilesTests(unittest.TestCase):
    def test_no_data_file_contains_a_replacement_character(self):
        for name in os.listdir(os.path.join(helpers.ROOT, 'Data')):
            with open(os.path.join(helpers.ROOT, 'Data', name), encoding='utf-8') as f:
                self.assertNotIn('\ufffd', f.read(), name)

    def test_norwegian_bokmal_is_spelled_correctly(self):
        from jt.catalog import Catalog
        from jt.config import Paths
        self.assertIn('Norwegian Bokm\u00e5l', Catalog(Paths(helpers.ROOT)).languages())

    def test_a_packaged_program_looks_for_its_files_next_to_the_exe(self):
        from jt.config import Paths
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\Apps\JT\JT.exe'):
            self.assertEqual(Paths.default().base, r'C:\Apps\JT')
        self.assertTrue(os.path.isdir(Paths.default().base + os.sep + 'Data'))
