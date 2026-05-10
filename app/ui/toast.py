from __future__ import annotations

import time

from PySide6.QtCore import (
    Property, QEasingCurve, QObject, QPropertyAnimation, QRect, Qt, QTimer,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.core.notification_bus import notification_bus

_LEVEL_COLORS = {
    "info":    "#3b82f6",
    "warning": "#f59e0b",
    "error":   "#ef4444",
}
_ICONS = {"info": "ℹ", "warning": "▲", "error": "✕"}
_MAX_VISIBLE = 5
_DISMISS_MS = 4000
_FADE_MS = 300
_WIDTH = 300
_GAP = 5   # px from header bottom and right border
_SPACING = 6


class ToastWidget(QWidget):
    def __init__(self, level: str, title: str, message: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ToastWidget")
        self._level = level
        self._opacity: float = 1.0

        color = _LEVEL_COLORS.get(level, _LEVEL_COLORS["info"])
        # Use QSS inline so the left accent border is always painted correctly.
        # WA_StyledBackground required for QWidget (not QFrame) to honour background.
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ToastWidget {{
                background-color: palette(base);
                border: 1px solid palette(mid);
                border-left: 5px solid {color};
                border-radius: 4px;
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 10, 8)
        layout.setSpacing(2)

        icon = _ICONS.get(level, "ℹ")
        title_label = QLabel(f"{icon}  {title}")
        title_label.setStyleSheet(f"font-weight: 600; color: {color}; background: transparent;")
        msg_label = QLabel(message)
        msg_label.setStyleSheet("background: transparent;")
        msg_label.setWordWrap(True)
        layout.addWidget(title_label)
        layout.addWidget(msg_label)

        self.adjustSize()
        self.setFixedWidth(_WIDTH)

    def get_opacity(self) -> float:
        return self._opacity

    def set_opacity(self, value: float) -> None:
        self._opacity = value
        from PySide6.QtWidgets import QGraphicsOpacityEffect
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
        effect.setOpacity(value)

    opacity = Property(float, get_opacity, set_opacity)


class ToastManager:
    """Not a QWidget — positions ToastWidgets directly on the parent window."""

    def __init__(self, parent: QWidget, header: QWidget | None = None) -> None:
        self._parent = parent
        self._header = header
        self._toasts: list[ToastWidget] = []
        notification_bus.notify.connect(self._on_notify)
        parent.installEventFilter(_ResizeWatcher(parent, self._reflow))

    def _on_notify(self, level: str, title: str, message: str) -> None:
        if len(self._toasts) >= _MAX_VISIBLE:
            self._remove_toast(self._toasts[0])
        toast = ToastWidget(level, title, message, self._parent)
        self._toasts.append(toast)
        toast.show()
        toast.raise_()
        self._reflow()
        QTimer.singleShot(_DISMISS_MS, lambda t=toast: self._fade_out(t))

    def _fade_out(self, toast: ToastWidget) -> None:
        if toast not in self._toasts:
            return
        anim = QPropertyAnimation(toast, b"opacity", toast)
        anim.setDuration(_FADE_MS)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.finished.connect(lambda t=toast: self._remove_toast(t))
        anim.start()

    def _remove_toast(self, toast: ToastWidget) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
            toast.deleteLater()
            self._reflow()

    def _reflow(self) -> None:
        pw = self._parent.width()
        header_bottom = self._header.height() if self._header else 0
        x = pw - _WIDTH - _GAP
        y = header_bottom + _GAP
        for toast in self._toasts:
            toast.adjustSize()
            toast.setFixedWidth(_WIDTH)
            toast.setGeometry(x, y, _WIDTH, toast.sizeHint().height())
            toast.raise_()
            y += toast.height() + _SPACING


class _ResizeWatcher(QObject):
    def __init__(self, parent: QWidget, callback) -> None:
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, obj, event) -> bool:
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Resize:
            self._callback()
        return False
