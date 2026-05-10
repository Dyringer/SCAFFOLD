from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class SecretPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        lbl = QLabel("🎉  You found the secret!\n\nYou are one of the few.")
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet("font-size: 28px; font-weight: 300;")
        layout.addWidget(lbl)
