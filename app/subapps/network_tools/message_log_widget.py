from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
    QWidget,
)


_MAX_LINES = 500


class MessageLogWidget(QFrame):
    """Append-only log of network events.

    In Phase A this just shows discovery sightings — the control channel
    in Phase B will start feeding it real messages.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)

        header = QHBoxLayout()
        title = QLabel("Event log")
        title.setStyleSheet("font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setFixedHeight(24)
        self._clear_btn.clicked.connect(self.clear)
        header.addWidget(self._clear_btn)
        root.addLayout(header)

        self._view = QPlainTextEdit()
        self._view.setReadOnly(True)
        self._view.setFont(QFont("Consolas", 9))
        self._view.setMaximumBlockCount(_MAX_LINES)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        root.addWidget(self._view, 1)

    # ------------------------------------------------------------------

    def append(self, kind: str, text: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._view.appendPlainText(f"{ts}  {kind:<10}  {text}")

    def clear(self) -> None:
        self._view.clear()
