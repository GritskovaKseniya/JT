"""Esecuzione di un lavoro lungo fuori dal thread dell'interfaccia.

Il lavoro gira in un thread; quello che ha da dire (avanzamento, fine, errore) passa da una coda che l'interfaccia
legge a intervalli con `poll()`. Il thread non tocca mai Tkinter. `InlineRunner` esegue tutto subito, nello stesso
thread: serve ai test, che cosi' restano deterministici.
"""
import queue
import threading

PROGRESS, DONE, ERROR = 'progress', 'done', 'error'


class BackgroundRunner:
    def __init__(self):
        self._events = queue.Queue()
        self._stop = threading.Event()
        self._thread = None

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self, work):
        """work(emit, should_stop) -> risultato. `emit(x)` manda un avanzamento; `should_stop()` dice se fermarsi."""
        if self.running:
            raise RuntimeError('a job is already running')
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(work,), daemon=True, name='jt-worker')
        self._thread.start()

    def _run(self, work):
        try:
            result = work(lambda progress: self._events.put((PROGRESS, progress)), self._stop.is_set)
        except Exception as e:                      # l'errore torna all'interfaccia, non si perde nel thread
            self._events.put((ERROR, e))
        else:
            self._events.put((DONE, result))

    def stop(self):
        """Chiede di fermarsi: il lavoro si ferma alla prossima riga."""
        self._stop.set()

    def join(self, timeout=None):
        """Aspetta che il lavoro finisca (al massimo `timeout` secondi)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def poll(self):
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                return events


class InlineRunner(BackgroundRunner):
    """Come BackgroundRunner ma esegue subito nel thread chiamante (test)."""

    def start(self, work):
        self._stop.clear()
        self._run(work)

    @property
    def running(self):
        return False
