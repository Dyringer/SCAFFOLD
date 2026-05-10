from typing import Callable, TypeVar

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
        worker = _Worker(fn, signals)
        QThreadPool.globalInstance().start(worker)


async_runner = AsyncRunner()
