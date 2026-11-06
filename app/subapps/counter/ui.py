from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import Card, mark_modern


class CounterHeaderWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        self._badge = QLabel("0")
        self._badge.setStyleSheet(
            "font-size: 18px; font-weight: 700; padding: 0 8px;"
        )
        layout.addWidget(self._badge)

    def set_count(self, value: int) -> None:
        self._badge.setText(str(value))


class CounterPanel(QWidget):
    increment_clicked = Signal()
    decrement_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Counter")
        mark_modern(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setAlignment(Qt.AlignCenter)

        card = Card("Counter")
        card.setFixedWidth(360)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        self._label = QLabel("0")
        self._label.setObjectName("Display")
        self._label.setAlignment(Qt.AlignCenter)
        card.body.addWidget(self._label)

        bl = QHBoxLayout()
        bl.setSpacing(8)
        self._dec_btn = QPushButton("−  Decrement")  # noqa: RUF001 (real minus sign)
        self._dec_btn.clicked.connect(self.decrement_clicked)
        self._inc_btn = QPushButton("+  Increment")
        self._inc_btn.setObjectName("PrimaryBtn")
        self._inc_btn.setProperty("compact", True)
        self._inc_btn.clicked.connect(self.increment_clicked)
        for b in (self._dec_btn, self._inc_btn):
            b.setCursor(Qt.PointingHandCursor)
            bl.addWidget(b, 1)
        card.body.addLayout(bl)
        layout.addWidget(card)

    def set_count(self, value: int) -> None:
        self._label.setText(str(value))
