from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# Chips wrap onto new rows; past this many rows the chip area scrolls.
_CHIPS_MAX_ROWS = 3


class _FlowLayout(QLayout):
    """Left-to-right layout that wraps onto new rows (for the tag chips)."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 6) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802 (Qt override)
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802 (Qt override)
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self) -> Qt.Orientations:  # noqa: N802 (Qt override)
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 (Qt override)
        return self._arrange(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(rect)
        self._arrange(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 (Qt override)
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _arrange(self, rect: QRect, *, apply: bool) -> int:
        m = self.contentsMargins()
        area = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = area.x(), area.y(), 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            if x > area.x() and x + hint.width() > area.right() + 1:
                x, y, row_h = area.x(), y + row_h + gap, 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            row_h = max(row_h, hint.height())
        return y + row_h - rect.y() + m.bottom()


class TagFilterBar(QWidget):
    """Search box + wrapping pill chips above the note list. Single-select."""

    tag_selected = Signal(object)  # str | None

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        self._active: str | None = None
        self._tag_counts: dict[str, int] = {}

        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter tags…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)
        root.addWidget(self._search)

        self._chip_host = QWidget()
        self._chip_host.setObjectName("Plain")
        self._chip_layout = _FlowLayout(self._chip_host)

        self._scroll = QScrollArea()
        self._scroll.setObjectName("Scroll")
        self._scroll.setWidget(self._chip_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
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
                w.hide()
                w.deleteLater()

        needle = self._search.text().strip().lstrip("#").lower()
        for tag in sorted(self._tag_counts):
            if needle and needle not in tag:
                continue
            count = self._tag_counts[tag]
            chip = QPushButton(f"#{tag} {count}")
            chip.setObjectName("SpTagChip")
            chip.setCheckable(True)
            chip.setChecked(tag == self._active)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _checked=False, t=tag: self._on_chip_clicked(t))
            self._chip_layout.addWidget(chip)

        self._fit_chip_area()

    def _fit_chip_area(self) -> None:
        """Size the chip area to its wrapped content, up to _CHIPS_MAX_ROWS rows."""
        width = self.width()
        if width <= 0:
            return
        if not self._chip_layout.count():
            self._scroll.hide()
            return
        first = self._chip_layout.itemAt(0)
        row_h = first.sizeHint().height() if first is not None else 24
        gap = self._chip_layout.spacing()
        cap = _CHIPS_MAX_ROWS * row_h + (_CHIPS_MAX_ROWS - 1) * gap  # whole rows only
        needed = self._chip_layout.heightForWidth(width)
        if needed > cap:
            # The vertical scrollbar will take some width; wrap for what's left.
            bar = self._scroll.verticalScrollBar().sizeHint().width()
            needed = self._chip_layout.heightForWidth(width - bar)
        self._scroll.setFixedHeight(min(needed, cap))
        self._scroll.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._fit_chip_area()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._fit_chip_area()

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
