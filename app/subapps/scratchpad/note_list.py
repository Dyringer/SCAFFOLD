from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu, QWidget

from app.ui.widgets import PortItem

from .models import extract_tags, format_modified
from .store import Note


def _note_item_widget(note: Note) -> PortItem:
    """Two-line kit row: bold title (+ PINNED badge) over muted date · #tags."""
    meta = format_modified(note.modified) or "—"
    tags = " ".join(f"#{t}" for t in sorted(extract_tags(note.body)))
    if tags:
        meta = f"{meta}  ·  {tags}"
    badges = [("PINNED", "")] if note.pinned else []
    return PortItem(note.title or "Untitled", meta, badges)


class NoteListWidget(QListWidget):
    """Sidebar note list. Emits signals instead of acting directly."""

    note_selected = Signal(str)          # note_id — single click / keyboard
    note_new_tab = Signal(str)           # note_id — double click → open new tab
    action_requested = Signal(str, str)  # action, note_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PortList")
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.currentItemChanged.connect(self._on_item_changed)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.setInterval(250)
        self._pending_single_click_id: str | None = None
        self._click_timer.timeout.connect(self._fire_single_click)

    _PINNED_ROLE = Qt.UserRole + 1

    def populate(self, notes: list[Note], select_id: str | None = None) -> None:
        self.blockSignals(True)
        self.clear()
        for note in notes:
            item = QListWidgetItem()
            widget = _note_item_widget(note)
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
        widget = _note_item_widget(note)
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
        if current is None:
            return
        note_id = current.data(Qt.UserRole)
        # Defer single-click so a double-click can cancel it.
        self._pending_single_click_id = note_id
        self._click_timer.start()

    def _fire_single_click(self) -> None:
        if self._pending_single_click_id is not None:
            self.note_selected.emit(self._pending_single_click_id)
            self._pending_single_click_id = None

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        super().keyPressEvent(event)
        # Fire immediately on keyboard navigation — no double-click ambiguity.
        self._click_timer.stop()
        self._fire_single_click()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt override)
        item = self.itemAt(event.pos())
        if item is not None:
            self._click_timer.stop()
            self._pending_single_click_id = None
            self.note_new_tab.emit(item.data(Qt.UserRole))
        else:
            super().mouseDoubleClickEvent(event)

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("New note", lambda: self.action_requested.emit("new", ""))
            menu.exec(self.viewport().mapToGlobal(pos))
            return
        note_id = item.data(Qt.UserRole)
        is_pinned = bool(item.data(self._PINNED_ROLE))

        emit = self.action_requested.emit
        menu = QMenu(self)
        menu.addAction(
            "Unpin" if is_pinned else "Pin to top",
            lambda nid=note_id, p=is_pinned: emit("unpin" if p else "pin", nid),
        )
        menu.addAction("Duplicate", lambda nid=note_id: emit("duplicate", nid))
        menu.addAction("Rename…", lambda nid=note_id: emit("rename", nid))
        menu.addSeparator()
        menu.addAction("Delete", lambda nid=note_id: emit("delete", nid))
        menu.exec(self.viewport().mapToGlobal(pos))
