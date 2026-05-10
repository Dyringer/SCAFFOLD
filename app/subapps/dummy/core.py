from __future__ import annotations

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, SubAppState


class DummySubApp(BaseSubApp):
    id = "dummy"
    name = "Test Suite"
    hidden = False
    _icon_char = "👋"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_FileIcon)

    def create_body(self) -> QWidget:
        from app.subapps.dummy.ui import TestSuitePanel
        return TestSuitePanel()

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
