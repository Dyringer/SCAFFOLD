from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, SubAppState


class SecretSubApp(BaseSubApp):
    id = "secret"
    name = "Secret"
    hidden = True
    _icon_char = "🎭"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_MessageBoxQuestion)

    def create_body(self) -> QWidget:
        from app.subapps.secret.ui import SecretPanel
        return SecretPanel()

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
