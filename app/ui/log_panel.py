from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QPushButton, QTextEdit,
    QVBoxLayout, QWidget,
)

from collections import deque

from app.core.log_handler import log_relay
from app.core.settings_store import settings_store
from app.core.notification_bus import notification_bus
from app.ui._notif_style import LEVEL_COLORS

_MAX_ROWS = 1000
_LEVEL_ALL = "ALL"
_LEVELS = [_LEVEL_ALL, "INFO", "WARNING", "ERROR"]
_FILTER_LABELS: dict[str, str] = {
    _LEVEL_ALL: "All",
    "INFO": "ℹ",
    "WARNING": "▲",
    "ERROR": "✕",
}


class LogPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LogPanel")
        self.setMinimumHeight(0)
        self.setAttribute(Qt.WA_StyledBackground, True)

        self._expanded = False
        self._filter = _LEVEL_ALL
        self._unread = 0
        self._auto_scroll = True
        self._row_count = 0
        self._records: deque[logging.LogRecord] = deque(maxlen=_MAX_ROWS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header bar (visible only when expanded) ───────────
        self._header = QWidget()
        self._header.setObjectName("LogHeader")
        self._header.setFixedHeight(24)
        self._header.hide()
        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(6, 0, 6, 0)
        hl.setSpacing(4)

        hl.addStretch()

        self._filter_btns: dict[str, QPushButton] = {}
        for lvl in _LEVELS:
            btn = QPushButton(_FILTER_LABELS.get(lvl, lvl))
            btn.setObjectName("LogFilterBtn")
            btn.setFlat(False)
            btn.setCheckable(True)
            btn.setChecked(lvl == _LEVEL_ALL)
            btn.setFixedWidth(32 if lvl != _LEVEL_ALL else 28)
            btn.clicked.connect(lambda _, l=lvl: self._set_filter(l))
            self._filter_btns[lvl] = btn
            hl.addWidget(btn)

        self._auto_btn = QPushButton("⏎")
        self._auto_btn.setObjectName("LogFilterBtn")
        self._auto_btn.setToolTip("Auto-scroll")
        self._auto_btn.setFlat(False)
        self._auto_btn.setCheckable(True)
        self._auto_btn.setChecked(True)
        self._auto_btn.clicked.connect(self._toggle_auto_scroll)
        hl.addWidget(self._auto_btn)

        self._clear_btn = QPushButton("\U0001f5d1")
        self._clear_btn.setObjectName("LogFilterBtn")
        self._clear_btn.setFlat(False)
        self._clear_btn.clicked.connect(self._clear)
        hl.addWidget(self._clear_btn)

        outer.addWidget(self._header)

        # ── log view ──────────────────────────────────────────
        self._text = QTextEdit()
        self._text.setReadOnly(True)
        self._text.setObjectName("LogView")
        self._text.setMinimumHeight(60)
        self._text.viewport().setAutoFillBackground(False)
        self._text.hide()
        outer.addWidget(self._text)

        self._splitter = None
        self._expanded_height = settings_store.get("app.log_panel_height", 200)
        self._badge_callback = None

        log_relay.record_emitted.connect(self._on_record)

    # ------------------------------------------------------------------

    def set_splitter(self, splitter) -> None:
        self._splitter = splitter

    def set_badge_callback(self, cb) -> None:
        self._badge_callback = cb

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._header.setVisible(self._expanded)
        self._text.setVisible(self._expanded)

        if self._splitter is not None:
            total = sum(self._splitter.sizes())
            if self._expanded:
                target = self._expanded_height
                self._splitter.setSizes([max(0, total - target), target])
            else:
                current = self._splitter.sizes()
                if len(current) > 1 and current[1] > 0:
                    self._expanded_height = current[1]
                self._splitter.setSizes([total, 0])

        if self._expanded:
            self._unread = 0
            self._update_badge()

    def _set_filter(self, level: str) -> None:
        self._filter = level
        for lvl, btn in self._filter_btns.items():
            btn.setChecked(lvl == level)
        self._redraw()

    def _toggle_auto_scroll(self) -> None:
        self._auto_scroll = self._auto_btn.isChecked()

    def _clear(self) -> None:
        self._records.clear()
        self._text.clear()
        self._row_count = 0

    def _append_record(self, record: logging.LogRecord) -> None:
        level_name = record.levelname
        ts = self._format_time(record)
        line = f"{ts}  {level_name:<7}  {record.name:<20}  {record.getMessage()}"

        fmt = QTextCharFormat()
        if record.levelno >= logging.ERROR:
            fmt.setForeground(QColor(LEVEL_COLORS["error"]))
            fmt.setBackground(QColor("#fff0f0"))
        elif record.levelno >= logging.WARNING:
            fmt.setForeground(QColor(LEVEL_COLORS["warning"]))

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(line + "\n", fmt)

        self._row_count += 1
        if self._row_count > _MAX_ROWS:
            cursor2 = self._text.textCursor()
            cursor2.movePosition(QTextCursor.Start)
            cursor2.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor)
            cursor2.removeSelectedText()
            self._row_count -= 1

    def _redraw(self) -> None:
        self._text.clear()
        self._row_count = 0
        for record in self._records:
            if self._filter == _LEVEL_ALL or record.levelname == self._filter:
                self._append_record(record)
        if self._auto_scroll:
            self._text.verticalScrollBar().setValue(
                self._text.verticalScrollBar().maximum()
            )

    def _on_record(self, record: logging.LogRecord) -> None:
        self._records.append(record)

        if self._filter == _LEVEL_ALL or record.levelname == self._filter:
            self._append_record(record)
            if self._auto_scroll and self._expanded:
                self._text.verticalScrollBar().setValue(
                    self._text.verticalScrollBar().maximum()
                )

        if not self._expanded:
            self._unread += 1
            self._update_badge()

        if record.levelno >= logging.WARNING:
            notify = settings_store.get("app.log_notify", False)
            if notify:
                level_key = "error" if record.levelno >= logging.ERROR else "warning"
                notification_bus.notify.emit(level_key, record.name, record.getMessage())

    @staticmethod
    def _format_time(record: logging.LogRecord) -> str:
        import time
        lt = time.localtime(record.created)
        return f"{lt.tm_hour:02d}:{lt.tm_min:02d}:{lt.tm_sec:02d}"

    def _update_badge(self) -> None:
        if self._badge_callback:
            self._badge_callback(self._unread)
