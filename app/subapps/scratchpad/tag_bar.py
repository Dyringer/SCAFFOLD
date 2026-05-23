from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)


class TagFilterBar(QWidget):
    """Search box + horizontal chips above the note list. Single-select."""

    tag_selected = Signal(object)  # str | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active: str | None = None
        self._tag_counts: dict[str, int] = {}

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 4, 6, 4)
        root.setSpacing(4)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter tags…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        root.addWidget(self._search)

        self._chip_host = QWidget()
        self._chip_layout = QHBoxLayout(self._chip_host)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(4)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._chip_host)
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._scroll.setFixedHeight(38)
        root.addWidget(self._scroll)

        self.hide()

    def set_tags(self, tag_counts: dict[str, int]) -> None:
        self._tag_counts = dict(tag_counts)
        if self._active and self._active not in tag_counts:
            self._active = None
            self.tag_selected.emit(None)
        self._rebuild_chips()
        if not tag_counts:
            self.hide()
        else:
            self.show()

    def _rebuild_chips(self) -> None:
        while self._chip_layout.count() > 0:
            item = self._chip_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        needle = self._search.text().strip().lstrip("#").lower()
        for tag in sorted(self._tag_counts):
            if needle and needle not in tag:
                continue
            count = self._tag_counts[tag]
            chip = QPushButton(f"#{tag} {count}")
            chip.setCheckable(True)
            chip.setChecked(tag == self._active)
            chip.setCursor(Qt.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { padding: 2px 8px; border-radius: 9px; "
                "border: 1px solid palette(mid); background: palette(button); }"
                "QPushButton:checked { background: palette(highlight); "
                "color: palette(highlighted-text); border-color: palette(highlight); }"
            )
            chip.clicked.connect(lambda _checked=False, t=tag: self._on_chip_clicked(t))
            self._chip_layout.addWidget(chip)

        self._chip_host.adjustSize()

    def _on_search_changed(self, _text: str) -> None:
        self._rebuild_chips()

    def _on_chip_clicked(self, tag: str) -> None:
        new = None if self._active == tag else tag
        self._active = new
        for i in range(self._chip_layout.count()):
            w = self._chip_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(new is not None and w.text().startswith(f"#{new} "))
        self.tag_selected.emit(new)

    def active(self) -> str | None:
        return self._active

    def clear_selection(self) -> None:
        if self._active is None:
            return
        self._active = None
        for i in range(self._chip_layout.count()):
            w = self._chip_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(False)
        self.tag_selected.emit(None)

    def set_active(self, tag: str | None) -> None:
        if self._active == tag:
            return
        self._active = tag
        for i in range(self._chip_layout.count()):
            w = self._chip_layout.itemAt(i).widget()
            if isinstance(w, QPushButton):
                w.setChecked(tag is not None and w.text().startswith(f"#{tag} "))
        self.tag_selected.emit(tag)
