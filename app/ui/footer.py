from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizeGrip, QWidget,
)

from app.core.base_subapp import BaseSubApp


class FooterBar(QWidget):
    log_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FooterBar")
        self.setFixedHeight(24)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._status = QLabel()
        self._status.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        layout.addWidget(self._status)
        layout.addStretch()

        self._log_btn = QPushButton("Logs")
        self._log_btn.setObjectName("LogToggleBtn")
        self._log_btn.setFlat(True)
        self._log_btn.setFixedHeight(22)
        self._log_btn.clicked.connect(self.log_toggled)
        layout.addWidget(self._log_btn)

        self._grip = QSizeGrip(self)
        layout.addWidget(self._grip, 0, Qt.AlignBottom | Qt.AlignRight)

        self._active_subapp: BaseSubApp | None = None

    def connect_subapp(self, subapp: BaseSubApp) -> None:
        if self._active_subapp is not None:
            try:
                self._active_subapp.status_changed.disconnect(self._status.setText)
            except RuntimeError:
                pass
        self._active_subapp = subapp
        self._status.setText("")
        subapp.status_changed.connect(self._status.setText)
