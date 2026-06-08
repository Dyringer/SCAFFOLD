from __future__ import annotations

from collections import deque
from collections.abc import Callable
from typing import ClassVar

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.settings_store import settings_store
from app.subapps.serial_terminal.ansi import AnsiToHtml, _esc_html
from app.subapps.serial_terminal.port_io import BAUD_RATES, SerialPort

# Maps the line-ending setting value -> bytes appended to each sent message.
_LINE_ENDINGS: list[tuple[str, str]] = [
    ("none", "None"),
    ("lf", r"LF  \n"),
    ("cr", r"CR  \r"),
    ("crlf", r"CRLF  \r\n"),
]
_ENDING_BYTES = {"none": b"", "lf": b"\n", "cr": b"\r", "crlf": b"\r\n"}

# Color for locally-echoed sent text in text/ANSI mode.
_TX_COLOR = "#4a90d9"

# How many raw chunks to retain for re-rendering. Generous; chunks are
# small and this caps memory regardless of the line-based scrollback bound.
_MAX_CHUNKS = 20000

# How often (ms) auto-reconnect retries the target port after a drop.
_RECONNECT_INTERVAL = 1000

# How often (ms) buffered RX/TX is flushed to the console. readyRead can fire
# thousands of times a second when a device floods (e.g. after a firmware
# segfault dumps garbage with no flow control); rendering per-chunk on the GUI
# thread then starves the event loop and the window appears frozen. Instead we
# coalesce: the data path only appends to the ring buffer and arms this timer,
# and the actual (expensive) render happens at most once per window. ~33 ms is
# ~30 fps — visually live, but render cost is bounded by frame rate, not by the
# device's output rate.
_FLUSH_INTERVAL = 33

# How many sent commands to keep in the per-session input history.
_MAX_HISTORY = 200


class _HistoryLineEdit(QLineEdit):
    """QLineEdit that recalls previously-sent input with the Up/Down arrows.

    The arrows are delegated to callbacks supplied by the session, which own
    the history list. Plain QLineEdit ignores Up/Down, so this is the natural
    place to capture them without affecting normal text entry.
    """

    def __init__(
        self,
        on_prev: Callable[[], None],
        on_next: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_prev = on_prev
        self._on_next = on_next

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key_Up:
            self._on_prev()
            event.accept()
            return
        if event.key() == Qt.Key_Down:
            self._on_next()
            event.accept()
            return
        super().keyPressEvent(event)


def key_event_to_bytes(event: QKeyEvent, newline: bytes) -> bytes | None:
    """Translate a key press into the bytes a terminal would send to the device.

    `newline` is the configured line ending sent for Enter. Returns None for
    keys we don't forward (so the caller can fall back to default handling,
    e.g. let Ctrl+C copy when nothing is selected — handled by the caller).
    """
    key = event.key()
    mods = event.modifiers()

    # Enter / Return -> configured line ending.
    if key in (Qt.Key_Return, Qt.Key_Enter):
        return newline
    # Common control keys with fixed byte values.
    fixed = {
        Qt.Key_Backspace: b"\x7f",   # most shells expect DEL on backspace
        Qt.Key_Tab: b"\t",
        Qt.Key_Escape: b"\x1b",
        Qt.Key_Delete: b"\x1b[3~",
        Qt.Key_Home: b"\x1b[H",
        Qt.Key_End: b"\x1b[F",
        Qt.Key_Up: b"\x1b[A",
        Qt.Key_Down: b"\x1b[B",
        Qt.Key_Right: b"\x1b[C",
        Qt.Key_Left: b"\x1b[D",
        Qt.Key_PageUp: b"\x1b[5~",
        Qt.Key_PageDown: b"\x1b[6~",
    }
    if key in fixed:
        return fixed[key]

    text = event.text()

    # Ctrl+A..Ctrl+Z -> 0x01..0x1a (Ctrl-C, Ctrl-D, Ctrl-Z, …).
    if mods & Qt.ControlModifier and Qt.Key_A <= key <= Qt.Key_Z:
        return bytes([key - Qt.Key_A + 1])

    # Any other character that produced text (letters, digits, symbols, space).
    if text:
        return text.encode("utf-8", errors="replace")

    return None


class _RawConsole(QTextEdit):
    """Console that, in interactive ("raw") mode, captures keystrokes and
    forwards them to the device as bytes instead of accepting local editing.

    Output is always whatever the device echoes back — we never echo locally,
    so shell autocompletion and line editing on the device render correctly.
    """

    def __init__(
        self,
        on_key_bytes: Callable[[QKeyEvent], bytes | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_key_bytes = on_key_bytes
        self._raw = False

    def set_raw(self, raw: bool) -> None:
        self._raw = raw
        # In raw mode the console takes keyboard focus and forwards keys; in
        # normal mode it's a read-only, selectable log.
        if raw:
            self.setReadOnly(False)
            self.setFocus()
        else:
            self.setReadOnly(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt override)
        if not self._raw:
            super().keyPressEvent(event)
            return
        # Let the standard copy shortcut work when there's a selection.
        if event.matches(QKeySequence.Copy) and self.textCursor().hasSelection():
            super().keyPressEvent(event)
            return
        data = self._on_key_bytes(event)
        if data is not None:
            event.accept()
            return
        # Unhandled keys are swallowed in raw mode (no local editing).
        event.accept()


class TerminalSession(QWidget):
    """One self-contained serial terminal: its own port, console, toolbar,
    history buffer, and pause/hex state.

    Baud / line-ending / view-mode are per-session, seeded from the
    last-used values in settings_store; the most recent choice is persisted
    back as the default for the next new session.
    """

    # Emitted whenever the connection state or selected port changes, so the
    # host can relabel the tab and refresh the shared port list.
    connection_changed = Signal()
    # Emitted with a human-readable status string for the subapp status bar.
    status_changed = Signal(str)

    def __init__(self, port: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._port = port
        self._serial = SerialPort(self)
        self._serial.data_received.connect(self._on_data_received)
        self._serial.opened.connect(self._on_opened)
        self._serial.closed.connect(self._on_closed)
        self._serial.error.connect(self._on_error)

        # Raw byte history: (direction, bytes) where direction is "rx"/"tx".
        # Source of truth for re-rendering when the view mode toggles.
        self._buffer: deque[tuple[str, bytes]] = deque(maxlen=_MAX_CHUNKS)
        self._paused = False
        self._ansi = AnsiToHtml()           # live state for incremental append
        self._view_mode = str(settings_store.get("serial.view_mode", "text"))

        # Coalesced rendering: incoming chunks are appended to _buffer and a
        # flush is scheduled rather than rendered inline (see _FLUSH_INTERVAL).
        # _pending holds the chunks received since the last flush so text mode
        # can append just the new ones; hex mode re-renders the whole buffer.
        self._pending: list[tuple[str, bytes]] = []
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(_FLUSH_INTERVAL)
        self._flush_timer.timeout.connect(self._flush_pending)

        # RX-activity watchdog (opt-in via serial.rx_watchdog). Detects a link
        # that went silent *after* talking — i.e. a device that wedged or
        # segfaulted while its CDC handle stayed open, which surfaces no Qt
        # error. Armed on the first RX byte and fed by every subsequent one;
        # _rx_seen gates it so a device that's merely awaiting a command (never
        # spoke yet) is never flagged. 0 = disabled.
        self._rx_seen = False
        self._rx_stalled = False
        self._rx_watchdog = QTimer(self)
        self._rx_watchdog.setSingleShot(True)
        self._rx_watchdog.timeout.connect(self._on_rx_stall)

        # Auto-reconnect: when on, a drop that wasn't a user disconnect starts
        # a retry timer that reopens the target port once it reappears.
        self._user_disconnect = False
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(_RECONNECT_INTERVAL)
        self._reconnect_timer.timeout.connect(self._try_reconnect)

        # Per-session input history (shell-style Up/Down recall). `_hist_index`
        # points one past the last entry when not browsing; `_hist_draft` holds
        # whatever the user was typing before they started scrolling back.
        self._history: list[str] = []
        self._hist_index = 0
        self._hist_draft = ""

        rl = QVBoxLayout(self)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.addLayout(self._build_toolbar())

        self._console = _RawConsole(self._on_console_key)
        self._console.setReadOnly(True)
        self._console.setLineWrapMode(QTextEdit.NoWrap)
        self._console.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self._console.setFont(QFont("Consolas", 9))
        rl.addWidget(self._console, 1)

        self._input_row = QWidget()
        input_row = QHBoxLayout(self._input_row)
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(6)
        self._input = _HistoryLineEdit(self._history_prev, self._history_next)
        self._input.setPlaceholderText(
            "Type a message and press Enter to send  (↑/↓ for history)…"
        )
        self._input.returnPressed.connect(self._send_input)
        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._send_input)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn)
        rl.addWidget(self._input_row)

        self._apply_history_limit()
        self._apply_raw_mode(self._raw_chk.isChecked())
        self._update_io_enabled()

    # ------------------------------------------------------------------
    # construction

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        bar.addWidget(QLabel("Baud:"))
        self._baud_combo = QComboBox()
        for b in BAUD_RATES:
            self._baud_combo.addItem(str(b), b)
        saved_baud = int(settings_store.get("serial.baud", 115200))
        idx = self._baud_combo.findData(saved_baud)
        self._baud_combo.setCurrentIndex(idx if idx >= 0 else BAUD_RATES.index(115200))
        self._baud_combo.currentIndexChanged.connect(self._on_baud_changed)
        bar.addWidget(self._baud_combo)

        bar.addWidget(QLabel("End:"))
        self._ending_combo = QComboBox()
        for value, label in _LINE_ENDINGS:
            self._ending_combo.addItem(label, value)
        saved_end = str(settings_store.get("serial.line_ending", "lf"))
        eidx = self._ending_combo.findData(saved_end)
        self._ending_combo.setCurrentIndex(eidx if eidx >= 0 else 1)
        self._ending_combo.currentIndexChanged.connect(self._on_ending_changed)
        bar.addWidget(self._ending_combo)

        bar.addStretch(1)

        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause_toggled)
        bar.addWidget(self._pause_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_console)
        bar.addWidget(clear_btn)

        self._hex_btn = QPushButton("Hex")
        self._hex_btn.setCheckable(True)
        self._hex_btn.setChecked(self._view_mode == "hex")
        self._hex_btn.toggled.connect(self._on_hex_toggled)
        bar.addWidget(self._hex_btn)

        self._auto_chk = QCheckBox("Auto-reconnect")
        self._auto_chk.setChecked(bool(settings_store.get("serial.auto_reconnect", False)))
        self._auto_chk.setToolTip(
            "Auto-reconnect: when the device drops (e.g. after reflashing), "
            "keep retrying the same port until it comes back."
        )
        self._auto_chk.toggled.connect(self._on_auto_toggled)
        bar.addWidget(self._auto_chk)

        self._raw_chk = QCheckBox("Interactive")
        self._raw_chk.setChecked(bool(settings_store.get("serial.raw_mode", False)))
        self._raw_chk.setToolTip(
            "Interactive (raw) mode: type directly into the console and every "
            "keystroke is sent live to the device — Tab, Ctrl-C, arrows, "
            "backspace, etc. Enables shell autocompletion and line editing. "
            "Output is the device's echo (no local echo)."
        )
        self._raw_chk.toggled.connect(self._on_raw_toggled)
        bar.addWidget(self._raw_chk)

        return bar

    # ------------------------------------------------------------------
    # connection state

    @property
    def is_open(self) -> bool:
        return self._serial.is_open

    @property
    def port_name(self) -> str:
        """The port this session owns (fixed for the session's lifetime)."""
        return self._port

    def connect(self) -> None:
        """Open this session's port at its current baud."""
        self._user_disconnect = False
        baud = int(self._baud_combo.currentData())
        self._serial.open(self._port, baud)

    def disconnect(self) -> None:
        # An explicit disconnect cancels any pending auto-reconnect.
        self._user_disconnect = True
        self._reconnect_timer.stop()
        self._serial.close("user disconnect")

    def _on_opened(self, name: str) -> None:
        baud = int(self._baud_combo.currentData())
        self._reconnect_timer.stop()
        # Fresh connection: the watchdog only arms once this link has produced
        # its first byte, so reset its "seen RX" gate here.
        self._rx_seen = False
        self._rx_stalled = False
        self._rx_watchdog.stop()
        self._append_system(f"— connected to {name} @ {baud} (8N1) —")
        self.status_changed.emit(f"{name} @ {baud}  connected")
        self._baud_combo.setEnabled(False)
        self._update_io_enabled()
        self.connection_changed.emit()

    def _on_closed(self, reason: str) -> None:
        self._rx_watchdog.stop()
        self._append_system(f"— disconnected ({reason}) —")
        self.status_changed.emit("disconnected")
        self._baud_combo.setEnabled(True)
        self._update_io_enabled()
        # Auto-reconnect only on unexpected drops, not on user disconnect.
        if self._auto_chk.isChecked() and not self._user_disconnect:
            self._append_system(f"— auto-reconnect: waiting for {self._port} —")
            self._reconnect_timer.start()
        self.connection_changed.emit()

    def _try_reconnect(self) -> None:
        if self._serial.is_open:
            self._reconnect_timer.stop()
            return
        # Only attempt once the port actually reappears, so we don't hammer
        # open() on a port that's still gone.
        available = {name for name, _ in SerialPort.available_ports()}
        if self._port in available:
            self._append_system(f"— auto-reconnect: reopening {self._port} —")
            baud = int(self._baud_combo.currentData())
            self._serial.open(self._port, baud)

    def _on_auto_toggled(self, on: bool) -> None:
        settings_store.set("serial.auto_reconnect", on)
        if not on:
            self._reconnect_timer.stop()

    def _on_error(self, msg: str) -> None:
        self._append_system(f"⚠ {msg}")

    def _update_io_enabled(self) -> None:
        is_open = self._serial.is_open
        self._input.setEnabled(is_open)
        self._send_btn.setEnabled(is_open)
        if self._raw_chk.isChecked() and is_open:
            self._console.setFocus()

    # ------------------------------------------------------------------
    # RX-activity watchdog (detect a wedged-but-open link)

    def _watchdog_secs(self) -> int:
        return int(settings_store.get("serial.rx_watchdog", 0))

    def _feed_rx_watchdog(self) -> None:
        """Called on every received chunk: mark the link live and (re)arm the
        silence timer so genuine ongoing traffic keeps it from firing."""
        # Any byte means the link recovered — clear a prior stall notice.
        if self._rx_stalled:
            self._rx_stalled = False
            self._append_system(f"— {self._port}: data resumed —")
            self.status_changed.emit(f"{self._port}  connected")
        self._rx_seen = True
        secs = self._watchdog_secs()
        if secs > 0:
            self._rx_watchdog.start(secs * 1000)
        else:
            self._rx_watchdog.stop()

    def _on_rx_stall(self) -> None:
        """Silence timer expired: the link spoke and then went quiet. Warn, and
        if auto-reconnect is on, drop the (apparently dead) port so the existing
        reconnect loop can recover a CDC handle that wedged without erroring."""
        if not self._serial.is_open or not self._rx_seen:
            return
        self._rx_stalled = True
        secs = self._watchdog_secs()
        self._append_system(
            f"⚠ {self._port}: no data for {secs}s — link may be stalled"
        )
        self.status_changed.emit(f"{self._port}  stalled (no data {secs}s)")
        # Proactive recovery is opt-in via the existing auto-reconnect toggle:
        # without an error the OS handle looks fine, so only force a reopen when
        # the user has already asked us to chase the device.
        if self._auto_chk.isChecked():
            self._append_system(f"— {self._port}: forcing reconnect —")
            # _on_closed sees auto-reconnect on + not a user disconnect, so it
            # starts the retry loop; reopening resets the watchdog cleanly.
            self._serial.close("stalled — forcing reconnect")

    def apply_rx_watchdog(self) -> None:
        """Re-evaluate the watchdog when its setting changes mid-session."""
        secs = self._watchdog_secs()
        if secs > 0 and self._serial.is_open and self._rx_seen:
            self._rx_watchdog.start(secs * 1000)
        else:
            self._rx_watchdog.stop()

    # ------------------------------------------------------------------
    # interactive ("raw") mode

    def _on_raw_toggled(self, on: bool) -> None:
        settings_store.set("serial.raw_mode", on)
        self._apply_raw_mode(on)

    def _apply_raw_mode(self, on: bool) -> None:
        # In raw mode the console captures keystrokes and forwards them live;
        # the line-buffered input row is hidden.
        self._console.set_raw(on)
        self._input_row.setVisible(not on)
        if on and self._serial.is_open:
            self._console.setFocus()

    def _on_console_key(self, event: QKeyEvent) -> bytes | None:
        """Called by the raw console for each keystroke. Send it live to the
        device; do NOT echo locally (the device echoes what it accepts)."""
        if not self._serial.is_open:
            return None
        newline = _ENDING_BYTES.get(str(self._ending_combo.currentData()), b"\n")
        data = key_event_to_bytes(event, newline)
        if data:
            self._serial.write(data)
            return data
        return None

    # ------------------------------------------------------------------
    # sending

    def _send_input(self) -> None:
        if not self._serial.is_open:
            return
        text = self._input.text()
        ending = _ENDING_BYTES.get(str(self._ending_combo.currentData()), b"")
        payload = text.encode("utf-8", errors="replace") + ending
        if self._serial.write(payload) <= 0:
            return
        # Echo what we sent (with ending) into the buffer + console.
        self._record("tx", payload)
        self._remember(text)
        self._input.clear()

    # ------------------------------------------------------------------
    # input history (per session, Up/Down recall)

    def _remember(self, text: str) -> None:
        """Append a sent command to history and reset the scroll position."""
        if text and (not self._history or self._history[-1] != text):
            self._history.append(text)
            del self._history[:-_MAX_HISTORY]  # cap; keep most recent
        # After a send, browsing starts fresh from the end with an empty draft.
        self._hist_index = len(self._history)
        self._hist_draft = ""

    def _history_prev(self) -> None:
        """Up arrow: step to an older command."""
        if not self._history or self._hist_index == 0:
            return
        if self._hist_index == len(self._history):
            # Entering history — stash the current draft so Down can restore it.
            self._hist_draft = self._input.text()
        self._hist_index -= 1
        self._set_input(self._history[self._hist_index])

    def _history_next(self) -> None:
        """Down arrow: step to a newer command, or back to the live draft."""
        if self._hist_index >= len(self._history):
            return
        self._hist_index += 1
        if self._hist_index == len(self._history):
            self._set_input(self._hist_draft)
        else:
            self._set_input(self._history[self._hist_index])

    def _set_input(self, text: str) -> None:
        self._input.setText(text)
        self._input.end(False)  # cursor to end, no selection

    # ------------------------------------------------------------------
    # receiving / rendering

    def _on_data_received(self, data: bytes) -> None:
        self._feed_rx_watchdog()
        self._record("rx", data)

    def _record(self, direction: str, data: bytes) -> None:
        """Add bytes to the ring buffer and queue them for the next flush.

        Rendering is deferred to _flush_pending on a timer so a fast/garbage
        flood can't starve the GUI thread (see _FLUSH_INTERVAL). _buffer is the
        re-render source of truth; _pending is just this frame's new chunks.
        """
        self._buffer.append((direction, data))
        if self._paused:
            return
        self._pending.append((direction, data))
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending(self) -> None:
        """Render everything buffered since the last flush, in one batch."""
        if not self._pending:
            return
        if self._view_mode == "hex":
            # Hex is a continuous dump over the whole rx/tx stream (offsets and
            # 16-byte rows run across read boundaries), so we can't append just
            # the new chunks — re-render the whole buffer. Doing it once per
            # flush (not once per chunk) is what keeps this affordable under a
            # flood; cost is bounded by scrollback and frame rate.
            self._render_hex()
        else:
            # Text mode: concatenate the new chunks into one HTML insert. One
            # insertHtml per frame instead of one per chunk.
            html = "".join(self._text_html(d, data) for d, data in self._pending)
            self._append_html(html)
        self._pending.clear()

    def _text_html(self, direction: str, data: bytes) -> str:
        text = data.decode("utf-8", errors="replace")
        if direction == "tx":
            # Sent text is shown verbatim in a distinct color (no ANSI parse).
            body = _esc_html(text).replace("\n", "<br>")
            return f'<span style="color:{_TX_COLOR}">{body}</span>'
        return self._ansi.feed(text)

    def _render_hex(self) -> None:
        """Replace the console with a continuous hex dump of the whole buffer."""
        all_bytes = b"".join(data for _direction, data in self._buffer)
        self._console.setPlainText(self._hex_dump(all_bytes))
        bar = self._console.verticalScrollBar()
        bar.setValue(bar.maximum())

    # Control-byte glyphs (Unicode "Control Pictures" block, U+2400+). One
    # char wide each so the gutter stays 1 column per byte and never jumps.
    _CTRL_GLYPHS: ClassVar[dict[int, str]] = {
        0x00: "␀",  # ␀ NUL
        0x08: "␈",  # ␈ BS
        0x09: "␉",  # ␉ TAB
        0x0a: "␊",  # ␊ LF
        0x0b: "␋",  # ␋ VT
        0x0c: "␌",  # ␌ FF
        0x0d: "␍",  # ␍ CR
        0x1b: "␛",  # ␛ ESC
        0x7f: "␡",  # ␡ DEL
    }

    @classmethod
    def _gutter_char(cls, b: int) -> str:
        if 32 <= b < 127:
            return chr(b)
        glyph = cls._CTRL_GLYPHS.get(b)
        if glyph is not None:
            return glyph
        return "·"  # · middle dot for any other non-printable byte

    @classmethod
    def _hex_dump(cls, data: bytes) -> str:
        """`hexdump -C` style: continuous 8-digit offset, then 16 bytes/row as
        two 8-byte groups, then a constant-width gutter. The hex field is
        padded to a fixed width so the gutter never shifts on a partial row.
        Special bytes (CR, LF, TAB, …) show as single-width control glyphs.
        """
        lines: list[str] = []
        for i in range(0, len(data), 16):
            row = data[i:i + 16]
            # two 8-byte halves, space-separated, like hexdump -C
            left = " ".join(f"{b:02x}" for b in row[:8])
            right = " ".join(f"{b:02x}" for b in row[8:])
            # fixed widths: 8 bytes * 3 - 1 = 23 chars per half
            hexs = f"{left:<23}  {right:<23}"
            gutter = "".join(cls._gutter_char(b) for b in row)
            lines.append(f"{i:08x}  {hexs}  |{gutter}|")
        return "\n".join(lines)

    def _append_html(self, html: str) -> None:
        if not html:
            return
        bar = self._console.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 4
        cursor = self._console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml(html)
        if at_bottom:
            bar.setValue(bar.maximum())

    def _append_system(self, text: str) -> None:
        self._append_html(
            f'<span style="color:#888;font-style:italic">{_esc_html(text)}</span><br>'
        )

    def _rerender(self) -> None:
        """Rebuild the whole console from the raw byte buffer in current mode."""
        # _buffer already contains anything sitting in _pending, so drop the
        # pending queue (and its timer) to avoid rendering those chunks twice.
        self._flush_timer.stop()
        self._pending.clear()
        self._console.clear()
        self._ansi.reset()
        if self._view_mode == "hex":
            self._render_hex()
        else:
            parts = [self._text_html(d, data) for d, data in self._buffer]
            self._append_html("".join(parts))

    # ------------------------------------------------------------------
    # toolbar handlers — persist the most recent choice as the new default

    def _on_baud_changed(self, _i: int) -> None:
        settings_store.set("serial.baud", int(self._baud_combo.currentData()))

    def _on_ending_changed(self, _i: int) -> None:
        settings_store.set("serial.line_ending", str(self._ending_combo.currentData()))

    def _on_pause_toggled(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("Resume" if paused else "Pause")
        if not paused:
            # Flush everything we buffered while paused by re-rendering.
            self._rerender()

    def _on_hex_toggled(self, hexed: bool) -> None:
        self._view_mode = "hex" if hexed else "text"
        self._hex_btn.setText("Text" if hexed else "Hex")
        settings_store.set("serial.view_mode", self._view_mode)
        self._rerender()

    # ------------------------------------------------------------------
    # history (shared setting, applied per-session)

    def apply_history_limit(self) -> None:
        self._apply_history_limit()

    def _apply_history_limit(self) -> None:
        history = int(settings_store.get("serial.history", 5000))
        self._console.document().setMaximumBlockCount(history)

    # ------------------------------------------------------------------
    # public API

    def clear_console(self) -> None:
        # Drop any queued flush too, or it would re-populate the just-cleared
        # console on the next timer tick.
        self._flush_timer.stop()
        self._pending.clear()
        self._buffer.clear()
        self._ansi.reset()
        self._console.clear()

    def close_port(self) -> None:
        self._reconnect_timer.stop()
        self._flush_timer.stop()
        self._serial.close("shutdown")
