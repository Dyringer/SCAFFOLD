from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon, QWidget

from app.core.notification_bus import notification_bus


class SystemTrayIcon(QSystemTrayIcon):
    def __init__(self, window: QWidget) -> None:
        icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        super().__init__(icon, window)
        self._window = window
        self._unread = 0

        menu = QMenu()
        restore_action = menu.addAction("Restore")
        restore_action.triggered.connect(self._restore)
        menu.addSeparator()
        quit_action = menu.addAction("Exit")
        quit_action.triggered.connect(QApplication.quit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)
        notification_bus.notify.connect(self._on_notify)
        self.show()

    def _restore(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()
        self._unread = 0
        self._update_icon()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            if self._window.isVisible():
                self._window.hide()
            else:
                self._restore()

    def _on_notify(self, level: str, title: str, message: str) -> None:
        if not self._window.isVisible() and level == "error":
            self.showMessage(title, message, QSystemTrayIcon.Warning, 4000)
            self._unread += 1
            self._update_icon()

    def _update_icon(self) -> None:
        pass  # badge overlay is out of scope for now
