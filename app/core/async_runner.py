from collections.abc import Callable
from typing import TypeVar

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

T = TypeVar("T")


class _WorkerSignals(QObject):
    done = Signal(object)
    error = Signal(object)


class _Worker(QRunnable):
    def __init__(self, fn: Callable, signals: _WorkerSignals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
            self._signals.done.emit(result)
        except Exception as exc:
            self._signals.error.emit(exc)


class AsyncRunner(QObject):
    def __init__(self) -> None:
        super().__init__()
        # In-flight jobs, held until their result is delivered. The pool only
        # owns the C++ side of a runnable: once run() returns, nothing on the
        # Python side references the worker or its signals object, so GC could
        # destroy them mid-job and the done/error callback was silently lost
        # (measured: ~half of 20 concurrent jobs never called back).
        self._inflight: set[_WorkerSignals] = set()

    def run(
        self,
        fn: Callable[[], T],
        on_done: Callable[[T], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        signals = _WorkerSignals()
        signals.done.connect(on_done)
        if on_error is not None:
            signals.error.connect(on_error)

        def release(_result: object) -> None:
            self._inflight.discard(signals)

        # Connected after the user callbacks, so those run first.
        signals.done.connect(release)
        signals.error.connect(release)
        worker = _Worker(fn, signals)
        signals.worker = worker          # keep the runnable's wrapper alive too
        self._inflight.add(signals)
        QThreadPool.globalInstance().start(worker)


async_runner = AsyncRunner()
