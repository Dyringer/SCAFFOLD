from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLineEdit, QListWidget, QListWidgetItem,
    QVBoxLayout, QWidget,
)

from app.core.base_subapp import CommandDef
from app.core.registry import registry


class CommandPalette(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandPalette")
        self.setFixedWidth(520)
        self.hide()

        self._subapp_commands: list[CommandDef] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍  Search commands and sub-apps…")
        self._search.textChanged.connect(self._filter)
        outer.addWidget(self._search)

        self._list = QListWidget()
        self._list.setFocusPolicy(Qt.NoFocus)
        self._list.itemActivated.connect(self._activate_item)
        outer.addWidget(self._list)

        self.installEventFilter(self)
        self.setMaximumHeight(320)
        self.adjustSize()

    # ------------------------------------------------------------------

    def set_subapp_commands(self, commands: list[CommandDef]) -> None:
        self._subapp_commands = commands

    def show_palette(self) -> None:
        self._search.clear()
        self._populate("")
        self._center_on_parent()
        self.show()
        self.raise_()
        self._search.setFocus()

    def hide_palette(self) -> None:
        self.hide()

    def _center_on_parent(self) -> None:
        if self.parent():
            pr = self.parent().rect()  # type: ignore[union-attr]
            x = (pr.width() - self.width()) // 2
            y = pr.height() // 4
            self.move(x, y)

    def _populate(self, query: str) -> None:
        self._list.clear()
        q = query.lower()

        for subapp in registry.all():
            if q and q not in subapp.name.lower():
                continue
            item = QListWidgetItem(f"  ▶  {subapp.name}")
            item.setData(Qt.UserRole, ("subapp", subapp.id, None))
            self._list.addItem(item)

        for cmd in self._subapp_commands:
            if q and q not in cmd.label.lower():
                continue
            shortcut_text = f"  {cmd.shortcut}" if cmd.shortcut else ""
            item = QListWidgetItem(f"  ▶  {cmd.label}{shortcut_text}")
            item.setData(Qt.UserRole, ("command", None, cmd))
            self._list.addItem(item)

        if self._list.count():
            self._list.setCurrentRow(0)

    def _filter(self, text: str) -> None:
        self._populate(text)

    def _activate_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if data is None:
            return
        kind, subapp_id, cmd = data
        self.hide_palette()
        if kind == "subapp" and subapp_id:
            registry.activate(subapp_id)
        elif kind == "command" and cmd:
            cmd.callback()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide_palette()
        elif event.key() == Qt.Key_Return:
            item = self._list.currentItem()
            if item:
                self._activate_item(item)
        elif event.key() == Qt.Key_Down:
            row = self._list.currentRow()
            self._list.setCurrentRow(min(row + 1, self._list.count() - 1))
        elif event.key() == Qt.Key_Up:
            row = self._list.currentRow()
            self._list.setCurrentRow(max(row - 1, 0))
        else:
            super().keyPressEvent(event)
