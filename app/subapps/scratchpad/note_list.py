from __future__ import annotations

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMenu,
    QVBoxLayout, QWidget,
)

from .models import format_modified
from .store import Note


class _NoteItemWidget(QWidget):
    def __init__(self, note: Note, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)

        pin = QLabel("📌" if note.pinned else "")
        pin.setFixedWidth(14)
        title_row.addWidget(pin)

        self._title = QLabel(note.title or "Untitled")
        f = self._title.font()
        f.setBold(True)
        self._title.setFont(f)
        self._title.setTextInteractionFlags(Qt.NoTextInteraction)
        title_row.addWidget(self._title, 1)

        layout.addLayout(title_row)

        self._meta = QLabel(format_modified(note.modified))
        mf = self._meta.font()
        mf.setPointSize(max(8, mf.pointSize() - 1))
        self._meta.setFont(mf)
        self._meta.setStyleSheet("color: #888;")
        layout.addWidget(self._meta)


class NoteListWidget(QListWidget):
    """Sidebar note list. Emits signals instead of acting directly."""

    note_selected = Signal(str)          # note_id
    action_requested = Signal(str, str)  # action, note_id  ("pin","unpin","duplicate","rename","delete")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.currentItemChanged.connect(self._on_item_changed)

    _PINNED_ROLE = Qt.UserRole + 1

    def populate(self, notes: list[Note], select_id: str | None = None) -> None:
        self.blockSignals(True)
        self.clear()
        for note in notes:
            item = QListWidgetItem()
            widget = _NoteItemWidget(note)
            item.setSizeHint(QSize(0, max(40, widget.sizeHint().height())))
            item.setData(Qt.UserRole, note.id)
            item.setData(self._PINNED_ROLE, note.pinned)
            self.addItem(item)
            self.setItemWidget(item, widget)
        self.blockSignals(False)

        if select_id is not None:
            self._select(select_id)
        elif self.count():
            self.setCurrentRow(0)

    def refresh_item(self, note: Note) -> None:
        """Rebuild only the widget for one item, avoiding a full repopulate."""
        item = self.currentItem()
        if item is None or item.data(Qt.UserRole) != note.id:
            return
        widget = _NoteItemWidget(note)
        item.setSizeHint(QSize(0, max(40, widget.sizeHint().height())))
        self.setItemWidget(item, widget)

    def select_id(self, note_id: str) -> None:
        self._select(note_id)

    def _select(self, note_id: str) -> None:
        for i in range(self.count()):
            if self.item(i).data(Qt.UserRole) == note_id:
                self.setCurrentRow(i)
                return

    def _on_item_changed(self, current: QListWidgetItem | None, _prev) -> None:
        if current is not None:
            self.note_selected.emit(current.data(Qt.UserRole))

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("New note", lambda: self.action_requested.emit("new", ""))
            menu.exec(self.viewport().mapToGlobal(pos))
            return
        note_id = item.data(Qt.UserRole)
        is_pinned = bool(item.data(self._PINNED_ROLE))

        menu = QMenu(self)
        menu.addAction(
            "Unpin" if is_pinned else "Pin to top",
            lambda nid=note_id, p=is_pinned: self.action_requested.emit("unpin" if p else "pin", nid),
        )
        menu.addAction("Duplicate", lambda nid=note_id: self.action_requested.emit("duplicate", nid))
        menu.addAction("Rename…", lambda nid=note_id: self.action_requested.emit("rename", nid))
        menu.addSeparator()
        menu.addAction("Delete", lambda nid=note_id: self.action_requested.emit("delete", nid))
        menu.exec(self.viewport().mapToGlobal(pos))
