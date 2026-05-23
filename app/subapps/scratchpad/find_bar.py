from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QPushButton, QWidget,
)


class FindBar(QFrame):
    find_requested = Signal(str)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in all notes…  (use #tag to filter by tag)")
        self._input.returnPressed.connect(self._fire)
        layout.addWidget(self._input, 1)

        btn = QPushButton("Find")
        btn.clicked.connect(self._fire)
        layout.addWidget(btn)

        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.clicked.connect(self.closed)
        layout.addWidget(close)

        self.hide()

    def _fire(self) -> None:
        self.find_requested.emit(self._input.text())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()
