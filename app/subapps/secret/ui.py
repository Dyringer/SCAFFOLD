from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QSizePolicy, QVBoxLayout, QWidget

from app.ui.widgets import Card, mark_modern


class SecretPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Secret")
        mark_modern(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setAlignment(Qt.AlignCenter)

        card = Card()
        card.setFixedWidth(420)
        card.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        for text, name in (
            ("🎉", "EmptyIcon"),
            ("You found the secret!", "EmptyTitle"),
            ("You are one of the few.", "Hint"),
        ):
            lbl = QLabel(text)
            lbl.setObjectName(name)
            lbl.setAlignment(Qt.AlignCenter)
            card.body.addWidget(lbl)
        layout.addWidget(card)
