from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import Card, mark_modern, set_state

from .commands import Command, CommandRegistry


def _fuzzy_score(needle: str, haystack: str) -> int | None:
    """Return a score >= 0 if needle is a subsequence of haystack, else None.
    Higher score = better match. Bonuses for consecutive chars and word starts."""
    if not needle:
        return 0
    h = haystack.lower()
    n = needle.lower()
    hi = 0
    score = 0
    consecutive = 0
    for ch in n:
        while hi < len(h) and h[hi] != ch:
            consecutive = 0
            hi += 1
        if hi >= len(h):
            return None
        consecutive += 1
        score += consecutive * 2
        if hi == 0 or h[hi - 1] in " _-":
            score += 4  # word boundary bonus
        hi += 1
    return score


class CommandPalette(QDialog):
    def __init__(self, registry: CommandRegistry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._registry = registry

        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setMinimumWidth(420)
        # A top-level popup sits outside the panel's modern="true" scope, so it
        # opts in itself; the rounded Card is drawn on a transparent window.
        self.setObjectName("SpPopup")
        mark_modern(self)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = Card(margins=(10, 10, 10, 10))
        outer.addWidget(card)
        layout = card.body

        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command…")
        self._input.textChanged.connect(self._on_filter)
        layout.addWidget(self._input)

        self._list = QListWidget()
        self._list.setObjectName("PortList")
        self._list.setFrameShape(QListWidget.NoFrame)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.itemActivated.connect(self._on_activate)
        layout.addWidget(self._list)

        self._populate("")

    def _populate(self, query: str) -> None:
        self._list.clear()
        scored: list[tuple[int, Command]] = []
        for cmd in self._registry.all():
            if query:
                s = _fuzzy_score(query, cmd.label)
                if s is None:
                    continue
                scored.append((s, cmd))
            else:
                scored.append((0, cmd))

        scored.sort(key=lambda x: -x[0])

        for _, cmd in scored:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, cmd.id)
            available = cmd.when is None or cmd.when()
            self._list.addItem(item)

            row = QWidget()
            row.setObjectName("PortItem")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)

            label = QLabel(cmd.label)
            label.setObjectName("SpRowText")
            if not available:
                set_state(label, "disabled")
            row_layout.addWidget(label, 1)

            if cmd.shortcut:
                sc_label = QLabel(cmd.shortcut)
                sc_label.setObjectName("SpRowMeta")
                row_layout.addWidget(sc_label)

            item.setSizeHint(row.sizeHint())
            self._list.setItemWidget(item, row)

        if self._list.count():
            self._list.setCurrentRow(0)

    def _on_filter(self, text: str) -> None:
        self._populate(text.strip())

    def _on_activate(self, item: QListWidgetItem) -> None:
        cmd_id = item.data(Qt.UserRole)
        self.accept()
        self._registry.execute(cmd_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        key = event.key()
        if key == Qt.Key_Escape:
            self.reject()
        elif key in (Qt.Key_Return, Qt.Key_Enter):
            item = self._list.currentItem()
            if item:
                self._on_activate(item)
        elif key == Qt.Key_Down:
            row = self._list.currentRow()
            if row < self._list.count() - 1:
                self._list.setCurrentRow(row + 1)
        elif key == Qt.Key_Up:
            row = self._list.currentRow()
            if row > 0:
                self._list.setCurrentRow(row - 1)
        else:
            super().keyPressEvent(event)
