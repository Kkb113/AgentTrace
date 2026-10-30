"""One bounded audit worker keeps analytical network latency off the incoming-mail loop."""

from threading import Event, Lock, Thread

from .errors import OutlookError
from .source_collector import SenderCollector


class SourceWorker:
    def __init__(self, collector: SenderCollector):
        self.collector = collector
        self._stop, self._wake = Event(), Event()
        self._mutex = Lock()
        self._busy = False
        self._error: str | None = None
        self._thread = Thread(target=self._run, name="agenttrace-audit-reader", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while self._wake.wait():
            self._wake.clear()
            if self._stop.is_set():
                return
            error = None
            try:
                self.collector.step()
            except OutlookError as caught:
                error = caught.code
            except Exception:
                error = "audit_worker_unavailable"
            with self._mutex:
                self._error, self._busy = error, False
            if self._stop.is_set():
                return

    def tick(self) -> dict[str, object]:
        with self._mutex:
            if not self._busy and not self._stop.is_set():
                self._busy = True
                self._wake.set()
            return {"source_worker_busy": self._busy, "source_worker_error": self._error}

    def close(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=0.2)
        # StateStore.close fences and closes under its transaction mutex. A late
        # network result cannot write after that closure or retain the OS lease.
