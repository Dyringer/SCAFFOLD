import logging

from PySide6.QtCore import QObject, Signal


class _LogRelay(QObject):
    record_emitted = Signal(object)


_relay = _LogRelay()


class LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _relay.record_emitted.emit(record)


log_handler = LogHandler()
log_relay = _relay
