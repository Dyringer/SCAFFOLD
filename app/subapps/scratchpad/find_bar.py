from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)


class FindBar(QFrame):
    find_requested = Signal(str)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in all notes…  (use #tag to filter by tag)")
        self._input.returnPressed.connect(self._fire)
        layout.addWidget(self._input, 1)

        btn = QPushButton("Find")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(self._fire)
        layout.addWidget(btn)

        close = QPushButton("✕")
        close.setObjectName("IconBtn")
        close.setToolTip("Close")
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.closed)
        layout.addWidget(close)

        self.hide()

    def _fire(self) -> None:
        self.find_requested.emit(self._input.text())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()
