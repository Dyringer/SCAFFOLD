from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)


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
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._label = QLabel("0")
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setStyleSheet("font-size: 64px; font-weight: 700;")

        btn_row = QWidget()
        bl = QHBoxLayout(btn_row)
        bl.setAlignment(Qt.AlignCenter)
        bl.setSpacing(24)

        self._dec_btn = QPushButton("−")
        self._dec_btn.setFixedSize(56, 56)
        self._dec_btn.setStyleSheet("font-size: 28px; border-radius: 28px;")
        self._dec_btn.clicked.connect(self.decrement_clicked)

        self._inc_btn = QPushButton("+")
        self._inc_btn.setFixedSize(56, 56)
        self._inc_btn.setStyleSheet("font-size: 28px; border-radius: 28px;")
        self._inc_btn.clicked.connect(self.increment_clicked)

        bl.addWidget(self._dec_btn)
        bl.addWidget(self._inc_btn)

        layout.addWidget(self._label)
        layout.addWidget(btn_row)

    def set_count(self, value: int) -> None:
        self._label.setText(str(value))
