from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStackedWidget, QWidget,
)


class HeaderBar(QWidget):
    menu_toggled = Signal()
    theme_toggled = Signal()
    settings_requested = Signal()
    minimize_requested = Signal()
    exit_requested = Signal()
    notifications_toggled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HeaderBar")
        self.setFixedHeight(40)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(2)

        # All icon buttons share the same font size so every glyph renders uniformly.
        _BTN_STYLE = "font-size: 16px; padding: 0;"

        def _btn(text: str, tooltip: str) -> QPushButton:
            b = QPushButton(text)
            b.setToolTip(tooltip)
            b.setFixedSize(36, 36)
            b.setStyleSheet(_BTN_STYLE)
            return b

        # menu / hamburger
        self._menu_btn = _btn("☰", "Toggle sidebar")
        self._menu_btn.clicked.connect(self.menu_toggled)
        layout.addWidget(self._menu_btn)

        # universal widget slot (swapped per sub-app)
        self._universal = QStackedWidget()
        self._universal.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._universal.setMaximumHeight(36)
        self._empty_page = QWidget()
        self._universal.addWidget(self._empty_page)
        layout.addWidget(self._universal)

        layout.addStretch()

        # notifications bell
        self._notif_btn = _btn("🔔", "Notification history")
        self._notif_btn.clicked.connect(self.notifications_toggled)
        layout.addWidget(self._notif_btn)

        # theme toggle — use text that exists in Segoe UI Emoji at the same size
        self._theme_btn = _btn("🌓", "Toggle theme")
        self._theme_btn.clicked.connect(self.theme_toggled)
        layout.addWidget(self._theme_btn)

        # settings
        self._settings_btn = _btn("⚙️", "Settings")
        self._settings_btn.clicked.connect(self.settings_requested)
        layout.addWidget(self._settings_btn)

        # minimize
        self._min_btn = _btn("—", "Minimize")
        self._min_btn.clicked.connect(self.minimize_requested)
        layout.addWidget(self._min_btn)

        # exit
        self._exit_btn = _btn("✕", "Exit")
        self._exit_btn.setObjectName("ExitButton")
        self._exit_btn.clicked.connect(self.exit_requested)
        layout.addWidget(self._exit_btn)

        self._widgets: dict[str, QWidget] = {}

    # ------------------------------------------------------------------
    # public API

    def set_universal_widget(self, widget: QWidget | None) -> None:
        if widget is None:
            self._universal.setCurrentWidget(self._empty_page)
            return
        widget_id = str(id(widget))
        if widget_id not in self._widgets:
            self._universal.addWidget(widget)
            self._widgets[widget_id] = widget
        self._universal.setCurrentWidget(widget)

    @property
    def notif_button(self) -> QPushButton:
        return self._notif_btn

    def set_notification_badge(self, count: int) -> None:
        if count:
            self._notif_btn.setText(f"🔔{count}")
        else:
            self._notif_btn.setText("🔔")
