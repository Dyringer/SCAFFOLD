from __future__ import annotations

import contextlib

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.settings_store import settings_store
from app.subapps.serial_terminal.port_io import SerialPort
from app.subapps.serial_terminal.session import TerminalSession


class SerialTerminalPanel(QWidget):
    """Serial (UART) terminal host.

    Left: a list of every available port that doubles as the session
    switcher. A marker shows each port's state — ▶ active session,
    ● open in a background session, ○ free. Clicking a free port connects
    it (spawning a session); clicking an open port switches the console to
    its session. Right: a stacked area showing the active session's console.

    One session per physical port (an OS serial port can't be opened twice).
    """

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        # port name -> its session (only ports with a live/lingering session)
        self._sessions: dict[str, TerminalSession] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([240, 720])
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
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)

        title = QLabel("Ports")
        title.setStyleSheet("font-weight: 600;")
        ll.addWidget(title)

        self._port_list = QListWidget()
        self._port_list.currentItemChanged.connect(self._on_row_changed)
        self._port_list.itemDoubleClicked.connect(lambda _i: self._activate_selected())
        ll.addWidget(self._port_list, 1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self._connect_btn = QPushButton("Connect")
        self._connect_btn.clicked.connect(self._activate_selected)
        btn_row.addWidget(self._connect_btn, 1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_ports)
        btn_row.addWidget(refresh_btn)
        ll.addLayout(btn_row)

        return left

    def _build_right(self) -> QWidget:
        self._stack = QStackedWidget()
        self._placeholder = QLabel(
            "Select a port on the left and press Connect\n"
            "to open a serial session."
        )
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color: #888;")
        self._stack.addWidget(self._placeholder)
        return self._stack

    # ------------------------------------------------------------------
    # sessions

    def _active_session(self) -> TerminalSession | None:
        w = self._stack.currentWidget()
        return w if isinstance(w, TerminalSession) else None

    def _open_session(self, port: str) -> TerminalSession:
        """Create (or reuse) a session for `port`, show and connect it."""
        session = self._sessions.get(port)
        if session is None:
            session = TerminalSession(port)
            session.connection_changed.connect(self._refresh_ports)
            session.status_changed.connect(self._on_session_status)
            self._sessions[port] = session
            self._stack.addWidget(session)
        self._stack.setCurrentWidget(session)
        if not session.is_open:
            session.connect()
        self._refresh_ports()
        self._update_buttons()
        return session

    def _on_session_status(self, text: str) -> None:
        if self.sender() is self._active_session():
            self.status_changed.emit(text)

    # ------------------------------------------------------------------
    # port list (also the session switcher)

    def _refresh_ports(self) -> None:
        ports = SerialPort.available_ports()
        active = self._active_session()
        active_port = active.port_name if active is not None and active.is_open else None
        current = self._selected_port()

        self._port_list.blockSignals(True)
        self._port_list.clear()
        for name, desc in ports:
            session = self._sessions.get(name)
            if session is not None and session.is_open and name == active_port:
                mark = "▶ "   # connected and showing in the console
            elif session is not None and session.is_open:
                mark = "● "   # connected in the background
            else:
                mark = "○ "   # not connected (history kept if a session exists)
            text = f"{mark}{name}" + (f"   {desc}" if desc else "")
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, name)
            self._port_list.addItem(item)
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
            self._refresh_ports()  # repaint markers (▶ moves)
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
            self._rebind(self._disconnect_selected)
        else:
            self._connect_btn.setText("Connect")
            self._connect_btn.setEnabled(port is not None)
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

    def close_port(self) -> None:
        """Tear down all sessions (called on app shutdown)."""
        self._scan_timer.stop()
        for session in list(self._sessions.values()):
            session.close_port()
