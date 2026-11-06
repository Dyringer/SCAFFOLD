from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.resource_manager import local_dir
from app.core.settings_store import settings_store
from app.subapps.serial_terminal.demo_port import DEMO_PORT_NAME
from app.subapps.serial_terminal.file_port import FILE_PORT_NAME
from app.subapps.serial_terminal.port_io import SerialPort, usb_badges
from app.subapps.serial_terminal.session import TerminalSession
from app.ui.widgets import Card, PortItem, mark_modern, set_state


class SerialTerminalPanel(QWidget):
    """Serial (UART) terminal host.

    Left: a list of every available port that doubles as the session
    switcher. A dot + badge shows each port's state — green/LIVE: the session
    on screen, blue/OPEN: connected in the background, none: free. Clicking a free port connects
    it (spawning a session); clicking an open port switches the console to
    its session. Right: a stacked area showing the active session's console.

    One session per physical port (an OS serial port can't be opened twice).
    """

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setObjectName("SerialTerminal")
        mark_modern(self)

        # port name -> its session (only ports with a live/lingering session)
        self._sessions: dict[str, TerminalSession] = {}
        # Last rendered port list (name, desc, status); the 1 s rescan only
        # rebuilds the item widgets when this changes, so the list never flickers.
        self._port_snapshot: list[tuple[str, str, str]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([270, 730])
        outer.addWidget(splitter, 1)

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(1000)
        self._scan_timer.timeout.connect(self._refresh_ports)
        self._scan_timer.start()

        settings_store.changed.connect(self._on_setting_changed)
        self._refresh_ports()
        self._update_buttons()

    # ------------------------------------------------------------------
    # construction

    def _build_left(self) -> QWidget:
        card = Card("Ports")
        refresh_btn = QPushButton("⟳")
        refresh_btn.setObjectName("IconBtn")
        refresh_btn.setToolTip("Rescan ports")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(lambda: self._refresh_ports(force=True))
        card.header.addWidget(refresh_btn)

        self._port_list = QListWidget()
        self._port_list.setObjectName("PortList")
        self._port_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._port_list.currentItemChanged.connect(self._on_row_changed)
        self._port_list.itemDoubleClicked.connect(lambda _i: self._activate_selected())
        card.body.addWidget(self._port_list, 1)

        self._connect_btn = QPushButton("Connect")
        self._connect_btn.setObjectName("PrimaryBtn")
        self._connect_btn.setProperty("compact", True)
        self._connect_btn.setCursor(Qt.PointingHandCursor)
        self._connect_btn.clicked.connect(self._activate_selected)
        card.body.addWidget(self._connect_btn)
        return card

    def _build_right(self) -> QWidget:
        self._stack = QStackedWidget()
        self._stack.setObjectName("Plain")

        # Empty state, shown until the first session is opened.
        self._placeholder = Card()
        lay = self._placeholder.body
        lay.addStretch(1)
        for text, name in (
            ("🔌", "EmptyIcon"),
            ("No session open", "EmptyTitle"),
            ("Pick a port on the left and press Connect (or double-click it).\n"
             "DEMO streams synthetic data; FILE replays a saved capture.", "Hint"),
        ):
            lbl = QLabel(text)
            lbl.setObjectName(name)
            lbl.setAlignment(Qt.AlignCenter)
            lay.addWidget(lbl)
        lay.addStretch(1)
        self._stack.addWidget(self._placeholder)
        return self._stack

    # ------------------------------------------------------------------
    # sessions

    def _active_session(self) -> TerminalSession | None:
        w = self._stack.currentWidget()
        return w if isinstance(w, TerminalSession) else None

    def _open_session(self, port: str) -> TerminalSession | None:
        """Create (or reuse) a session for `port`, show and connect it.

        For the FILE source, a file picker opens first (Connect/double-click on
        FILE means "load a file"); the chosen path is handed to the session
        before it connects. Cancelling the dialog aborts without a session.
        """
        # FILE means "load a file": pick it up front; cancelling aborts.
        file_path = self._pick_replay_file() if port == FILE_PORT_NAME else None
        if port == FILE_PORT_NAME and not file_path:
            return None

        session = self._sessions.get(port)
        if session is None:
            session = TerminalSession(port)
            session.connection_changed.connect(self._refresh_ports)
            session.status_changed.connect(self._on_session_status)
            self._sessions[port] = session
            self._stack.addWidget(session)
        self._stack.setCurrentWidget(session)
        if file_path:
            # Reload the (possibly different) file on each activation. open()
            # re-reads from scratch, so no need to disconnect a prior load first.
            session.set_source_path(file_path)
            session.connect()
        elif not session.is_open:
            session.connect()
        self._refresh_ports()
        self._update_buttons()
        return session

    def _pick_replay_file(self) -> str | None:
        """Ask for a capture file to replay. Returns the path, or None if
        cancelled. Defaults to the logs folder and our capture formats."""
        start_dir = local_dir() / "logs"
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open capture to replay",
            str(start_dir if start_dir.exists() else local_dir()),
            "Captures (*.log.bin *.log);;All files (*)",
        )
        return path or None

    def _on_session_status(self, text: str) -> None:
        if self.sender() is self._active_session():
            self.status_changed.emit(text)

    # ------------------------------------------------------------------
    # port list (also the session switcher)

    def _port_status(self, name: str, active_port: str | None) -> str:
        session = self._sessions.get(name)
        if session is None or not session.is_open:
            return ""         # not connected (history kept if a session exists)
        return "live" if name == active_port else "open"

    def _refresh_ports(self, force: bool = False) -> None:
        active = self._active_session()
        active_port = active.port_name if active is not None and active.is_open else None
        ports = [(name, desc, self._port_status(name, active_port))
                 for name, desc in SerialPort.available_ports()]
        if ports == self._port_snapshot and not force:
            self._update_buttons()
            return
        self._port_snapshot = ports
        chips = usb_badges()
        current = self._selected_port()

        self._port_list.blockSignals(True)
        self._port_list.clear()
        for name, desc, status in ports:
            badges: list[tuple[str, str]] = []
            if status == "live":
                badges.append(("LIVE", "live"))
            elif status == "open":
                badges.append(("OPEN", "bridge"))
            if name in (DEMO_PORT_NAME, FILE_PORT_NAME):
                badges.append((name, ""))
            elif name in chips:
                badges.append(chips[name])
            widget = PortItem(name, desc, badges, status)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            item.setSizeHint(widget.sizeHint())
            self._port_list.addItem(item)
            self._port_list.setItemWidget(item, widget)
            if name == current:
                self._port_list.setCurrentItem(item)
        self._port_list.blockSignals(False)
        self._update_buttons()

    def _selected_port(self) -> str | None:
        item = self._port_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _on_row_changed(self, _cur, _prev) -> None:
        # Selecting a row that already has a session switches to its console.
        port = self._selected_port()
        session = self._sessions.get(port) if port else None
        if session is not None:
            self._stack.setCurrentWidget(session)
            self._refresh_ports()  # repaint markers (LIVE moves)
        self._update_buttons()

    def _activate_selected(self) -> None:
        """Connect button / double-click: open or switch to the selected port."""
        port = self._selected_port()
        if not port:
            return
        self._open_session(port)

    def _update_buttons(self) -> None:
        port = self._selected_port()
        session = self._sessions.get(port) if port else None
        if session is not None and session.is_open:
            self._connect_btn.setText("Disconnect")
            self._connect_btn.setEnabled(True)
            set_state(self._connect_btn, "danger")
            self._rebind(self._disconnect_selected)
        else:
            self._connect_btn.setText("Connect")
            self._connect_btn.setEnabled(port is not None)
            set_state(self._connect_btn, "")
            self._rebind(self._activate_selected)

    def _rebind(self, slot) -> None:
        with contextlib.suppress(RuntimeError, TypeError):
            self._connect_btn.clicked.disconnect()
        self._connect_btn.clicked.connect(slot)

    def _disconnect_selected(self) -> None:
        port = self._selected_port()
        session = self._sessions.get(port) if port else None
        if session is not None:
            session.disconnect()
        self._refresh_ports()
        self._update_buttons()

    # ------------------------------------------------------------------
    # settings reactions

    def _on_setting_changed(self, key: str, _value) -> None:
        if key == "serial.history":
            for session in self._sessions.values():
                session.apply_history_limit()
        elif key == "serial.rx_watchdog":
            for session in self._sessions.values():
                session.apply_rx_watchdog()

    # ------------------------------------------------------------------
    # public API (called by the subapp / command palette)

    def clear_console(self) -> None:
        session = self._active_session()
        if session is not None:
            session.clear_console()

    def release_port(self, port: str) -> bool:
        """Disconnect `port` if a session holds it open, so another tool (the
        ESP flasher) can use it. History is kept. Returns True if it was open."""
        session = self._sessions.get(port)
        if session is None or not session.is_open:
            return False
        session.disconnect()
        self._refresh_ports()
        return True

    def open_port(self, port: str) -> None:
        """Select `port` in the list and connect (or switch to) its session."""
        self._refresh_ports()
        for i in range(self._port_list.count()):
            item = self._port_list.item(i)
            if item.data(Qt.UserRole) == port:
                self._port_list.setCurrentItem(item)
                break
        self._open_session(port)

    def close_port(self) -> None:
        """Tear down all sessions (called on app shutdown)."""
        self._scan_timer.stop()
        for session in list(self._sessions.values()):
            session.close_port()
