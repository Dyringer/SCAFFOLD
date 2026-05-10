from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

from app.core.notification_bus import notification_bus
from app.ui._notif_style import LEVEL_COLORS, LEVEL_ICONS

_MAX_HISTORY = 100
_PANEL_W = 320
_PANEL_MAX_H = 360


@dataclass
class _Entry:
    level: str
    title: str
    message: str
    ts: str = field(default_factory=lambda: datetime.now().strftime("%H:%M"))


class NotificationHistory(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationHistory")
        self.setFrameShape(QFrame.StyledPanel)
        self.setFrameShadow(QFrame.Raised)
        self.setFixedWidth(_PANEL_W)
        self.setMaximumHeight(_PANEL_MAX_H)
        self.hide()

        self._entries: deque[_Entry] = deque(maxlen=_MAX_HISTORY)
        self._unread = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ── header row ──────────────────────────────────────
        header = QWidget()
        hl = QHBoxLayout(header)
        hl.setContentsMargins(10, 8, 8, 8)
        title_lbl = QLabel("Notifications")
        title_lbl.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._clear_btn = QPushButton("Clear all")
        self._clear_btn.setFlat(True)
        self._clear_btn.setStyleSheet("color: #888; font-size: 11px;")
        self._clear_btn.clicked.connect(self._clear_all)
        hl.addWidget(title_lbl)
        hl.addStretch()
        hl.addWidget(self._clear_btn)
        outer.addWidget(header)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        outer.addWidget(sep)

        # ── scrollable list ──────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setFrameShape(QFrame.NoFrame)

        self._content = QWidget()
        self._list_layout = QVBoxLayout(self._content)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._content)
        outer.addWidget(self._scroll)

        # ── empty-state label ────────────────────────────────
        self._empty_lbl = QLabel("No notifications")
        self._empty_lbl.setAlignment(Qt.AlignCenter)
        self._empty_lbl.setStyleSheet("color: #888; font-size: 12px; padding: 16px;")
        outer.addWidget(self._empty_lbl)

        notification_bus.notify.connect(self._on_notify)

    # ------------------------------------------------------------------

    def _on_notify(self, level: str, title: str, message: str) -> None:
        if len(self._entries) == _MAX_HISTORY:
            item = self._list_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        entry = _Entry(level, title, message)
        self._entries.append(entry)
        self._add_row(entry)
        self._update_empty_state()
        if not self.isVisible():
            self._unread += 1

    def _add_row(self, entry: _Entry) -> None:
        row = QFrame()
        row.setFrameShape(QFrame.NoFrame)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 7, 10, 7)
        rl.setSpacing(8)

        icon = LEVEL_ICONS.get(entry.level, "ℹ")
        color = LEVEL_COLORS.get(entry.level, LEVEL_COLORS["info"])
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(14)
        icon_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")

        text_lbl = QLabel(entry.title)
        text_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        text_lbl.setStyleSheet("font-size: 12px;")

        ts_lbl = QLabel(entry.ts)
        ts_lbl.setStyleSheet("color: #888; font-size: 11px;")

        rl.addWidget(icon_lbl)
        rl.addWidget(text_lbl)
        rl.addWidget(ts_lbl)

        # insert before the trailing stretch
        self._list_layout.insertWidget(self._list_layout.count() - 1, row)

    def _clear_all(self) -> None:
        self._entries.clear()
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._unread = 0
        self._update_empty_state()

    def _update_empty_state(self) -> None:
        has = bool(self._entries)
        self._scroll.setVisible(has)
        self._empty_lbl.setVisible(not has)

    # ------------------------------------------------------------------

    def toggle(self, anchor: QWidget) -> None:
        if self.isVisible():
            self.hide()
            return

        self._unread = 0
        self._update_empty_state()

        # position: right-align below the anchor button, stay inside parent
        if self.parent():
            parent = self.parent()  # type: ignore[assignment]
            btn_br = anchor.mapTo(parent, anchor.rect().bottomRight())
            x = btn_br.x() - _PANEL_W
            y = btn_br.y() + 2
            # clamp inside parent
            x = max(4, min(x, parent.width() - _PANEL_W - 4))
            y = max(0, min(y, parent.height() - 100))
            self.move(x, y)

        self.adjustSize()
        self.show()
        self.raise_()

    @property
    def unread(self) -> int:
        return self._unread
