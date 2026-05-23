from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QTabBar, QWidget


class TabBar(QTabBar):
    """Tab bar for open notes. Emits signals; does not touch the store directly."""

    tab_selected = Signal(str)   # note_id
    tab_closed = Signal(str)     # note_id
    tab_reordered = Signal(list) # new ordered list of note_ids

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTabsClosable(True)
        self.setMovable(True)
        self.setExpanding(False)
        self.setDrawBase(False)

        self.tabCloseRequested.connect(self._on_close_requested)
        self.currentChanged.connect(self._on_current_changed)
        self.tabMoved.connect(self._on_tab_moved)

    # ------------------------------------------------------------------
    # Public API

    def add_tab(self, note_id: str, title: str) -> int:
        """Append a tab and return its index. Does NOT emit tab_selected."""
        self.blockSignals(True)
        idx = self.addTab(title)
        self.setTabData(idx, note_id)
        self.blockSignals(False)
        return idx

    def focus_tab(self, note_id: str) -> bool:
        """Switch to an existing tab by note_id. Returns True if found."""
        idx = self._index_of(note_id)
        if idx < 0:
            return False
        self.blockSignals(True)
        self.setCurrentIndex(idx)
        self.blockSignals(False)
        return True

    def remove_tab_by_id(self, note_id: str) -> None:
        idx = self._index_of(note_id)
        if idx >= 0:
            self.blockSignals(True)
            self.removeTab(idx)
            self.blockSignals(False)

    def update_title(self, note_id: str, title: str) -> None:
        idx = self._index_of(note_id)
        if idx >= 0:
            self.setTabText(idx, title)

    def current_note_id(self) -> str | None:
        idx = self.currentIndex()
        if idx < 0:
            return None
        return self.tabData(idx)

    def all_note_ids(self) -> list[str]:
        return [self.tabData(i) for i in range(self.count())]

    def has_note(self, note_id: str) -> bool:
        return self._index_of(note_id) >= 0

    # ------------------------------------------------------------------
    # Internal

    def _index_of(self, note_id: str) -> int:
        for i in range(self.count()):
            if self.tabData(i) == note_id:
                return i
        return -1

    def _on_close_requested(self, idx: int) -> None:
        note_id = self.tabData(idx)
        if note_id:
            self.tab_closed.emit(note_id)

    def _on_current_changed(self, idx: int) -> None:
        if idx < 0:
            return
        note_id = self.tabData(idx)
        if note_id:
            self.tab_selected.emit(note_id)

    def _on_tab_moved(self, _from: int, _to: int) -> None:
        self.tab_reordered.emit(self.all_note_ids())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MiddleButton:
            idx = self.tabAt(event.pos())
            if idx >= 0:
                self._on_close_requested(idx)
                return
        super().mouseReleaseEvent(event)
