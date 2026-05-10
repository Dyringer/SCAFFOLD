from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QRect, QKeyCombination
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMainWindow, QSplitter,
    QVBoxLayout, QWidget,
)

from app.core.registry import registry
from app.core.settings_store import settings_store
from app.core.theme_manager import theme_manager
from app.ui.body import BodyStack
from app.ui.command_palette import CommandPalette
from app.ui.footer import FooterBar
from app.ui.header import HeaderBar
from app.ui.log_panel import LogPanel
from app.ui.notification_history import NotificationHistory
from app.ui.sidebar import SidePanel
from app.ui.toast import ToastManager
from app.ui.tray import SystemTrayIcon

_DEFAULT_W = 1024
_DEFAULT_H = 768
_MIN_W = 800
_MIN_H = 600


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("S.C.A.F.F.O.L.D.")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        self._drag_pos: QPoint | None = None

        self._build_ui()
        self._wire_signals()
        self._restore_geometry()
        self._setup_shortcuts()

        # tray (must be after window is fully built)
        self._tray = SystemTrayIcon(self)

        registry.bind_ui(
            header=self._header,
            body_stack=self._body_stack,
            footer=self._footer,
            command_palette=self._palette,
        )
        registry.subapp_registered.connect(self._on_subapp_registered)
        registry.subapp_activated.connect(self._sidebar.set_active)

    # ------------------------------------------------------------------
    # UI construction

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        self._header = HeaderBar(self)
        root.addWidget(self._header)

        # upper area: sidebar + body side-by-side
        upper = QWidget()
        upper_layout = QHBoxLayout(upper)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        upper_layout.setSpacing(0)

        self._sidebar = SidePanel(self)
        upper_layout.addWidget(self._sidebar)

        self._body_stack = BodyStack(self)
        upper_layout.addWidget(self._body_stack, 1)

        # vertical splitter: upper area on top, log panel below (full width)
        self._vsplitter = QSplitter(Qt.Vertical)
        self._log_panel = LogPanel(self)
        self._vsplitter.addWidget(upper)
        self._vsplitter.addWidget(self._log_panel)
        self._vsplitter.setStretchFactor(0, 1)
        self._vsplitter.setStretchFactor(1, 0)
        self._vsplitter.setSizes([_DEFAULT_H - 40 - 24, 0])  # upper | log (collapsed)
        self._log_panel.set_splitter(self._vsplitter)
        self._log_panel.set_badge_callback(self._update_log_badge)

        root.addWidget(self._vsplitter, 1)

        # footer
        self._footer = FooterBar(self)
        root.addWidget(self._footer)

        # overlays (no layout parent — positioned manually)
        self._toast_manager = ToastManager(self, self._header)
        self._palette = CommandPalette(self)
        self._notif_history = NotificationHistory(self)

    # ------------------------------------------------------------------
    # signals

    def _wire_signals(self) -> None:
        self._header.menu_toggled.connect(self._sidebar.toggle)
        self._header.theme_toggled.connect(theme_manager.toggle)
        self._header.settings_requested.connect(
            lambda: registry.activate("settings")
        )
        self._header.minimize_requested.connect(self.showMinimized)
        self._header.exit_requested.connect(QApplication.quit)
        self._header.notifications_toggled.connect(
            lambda: self._notif_history.toggle(self._header.notif_button)
        )
        self._sidebar.subapp_selected.connect(registry.activate)
        self._footer.log_toggled.connect(self._log_panel.toggle)

    def _setup_shortcuts(self) -> None:
        # Ctrl+K → command palette
        sc_palette = QShortcut(QKeySequence("Ctrl+K"), self)
        sc_palette.activated.connect(self._palette.show_palette)

        # Ctrl+` → log panel toggle
        sc_log = QShortcut(QKeySequence(Qt.CTRL | Qt.Key_QuoteLeft), self)
        sc_log.activated.connect(self._log_panel.toggle)

    # ------------------------------------------------------------------
    # subapp registration callback

    def _update_log_badge(self, count: int) -> None:
        self._footer.set_log_badge(count)

    def _on_subapp_registered(self, subapp) -> None:
        if not subapp.hidden:
            self._sidebar.add_subapp(subapp)

    # ------------------------------------------------------------------
    # frameless window drag

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            # only drag from header area
            if self._header.rect().contains(
                self._header.mapFromGlobal(event.globalPosition().toPoint())
            ):
                self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # geometry persistence

    def _restore_geometry(self) -> None:
        geo = settings_store.get("window.geometry")
        pos = settings_store.get("window.pos")
        if geo:
            self.resize(geo[0], geo[1])
        if pos:
            self.move(pos[0], pos[1])

    def _save_geometry(self) -> None:
        update: dict = {
            "window.geometry": [self.width(), self.height()],
            "window.pos": [self.x(), self.y()],
        }
        lp_sizes = self._vsplitter.sizes()
        if len(lp_sizes) > 1 and lp_sizes[1] > 0:
            update["app.log_panel_height"] = lp_sizes[1]
        settings_store.set_many(update)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_geometry()
        # minimise to tray instead of closing
        event.ignore()
        self.hide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # keep palette and toast overlay in sync
        if hasattr(self, "_palette"):
            self._palette._center_on_parent()
