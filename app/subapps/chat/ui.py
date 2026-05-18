from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from app.services.network import network_service
from app.services.network.types import PeerInfo
from app.subapps.chat.model import ChatLine, ChatModel, Direction, EVERYONE


_COLOR_INCOMING = "#dcdcdc"
_COLOR_OUTGOING = "#9cd";      # accent
_COLOR_SYSTEM = "#888"


class _Composer(QFrame):
    """Single-line composer with Enter-to-send."""

    send_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a message and press Enter")
        self._input.returnPressed.connect(self._submit)
        self._btn = QPushButton("Send")
        self._btn.clicked.connect(self._submit)
        row.addWidget(self._input, 1)
        row.addWidget(self._btn)

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self.send_requested.emit(text)
        self._input.clear()

    def set_enabled(self, enabled: bool, placeholder: str = "") -> None:
        self._input.setEnabled(enabled)
        self._btn.setEnabled(enabled)
        if placeholder:
            self._input.setPlaceholderText(placeholder)
        elif enabled:
            self._input.setPlaceholderText("Type a message and press Enter")

    def focus_input(self) -> None:
        self._input.setFocus()


class _ConversationView(QTextEdit):
    """Read-only scrolling transcript for the selected thread."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Segoe UI", 10))
        self.setStyleSheet("background: palette(base);")

    def clear_and_load(self, lines: list[ChatLine]) -> None:
        self.clear()
        for line in lines:
            self.append_line(line)

    def append_line(self, line: ChatLine) -> None:
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)

        if line.direction == Direction.SYSTEM:
            html = (
                f'<div style="color:{_COLOR_SYSTEM}; font-style:italic; '
                f'margin: 2px 0;">'
                f'<span style="font-size:10px;">{line.time_str}</span>  '
                f'{self._escape(line.text)}'
                f'</div>'
            )
        elif line.direction == Direction.OUTGOING:
            html = (
                f'<div style="margin: 2px 0;">'
                f'<span style="color:{_COLOR_SYSTEM}; font-size:10px;">'
                f'{line.time_str}  '
                f'</span>'
                f'<span style="color:{_COLOR_OUTGOING}; font-weight:600;">'
                f'{self._escape(line.sender_nick)}:'
                f'</span> '
                f'{self._escape(line.text)}'
                f'</div>'
            )
        else:
            html = (
                f'<div style="margin: 2px 0;">'
                f'<span style="color:{_COLOR_SYSTEM}; font-size:10px;">'
                f'{line.time_str}  '
                f'</span>'
                f'<span style="color:{_COLOR_INCOMING}; font-weight:600;">'
                f'{self._escape(line.sender_nick)}:'
                f'</span> '
                f'{self._escape(line.text)}'
                f'</div>'
            )
        cursor.insertHtml(html + "<br>")
        # auto-scroll to bottom
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    @staticmethod
    def _escape(s: str) -> str:
        return (s.replace("&", "&amp;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))


class ChatPanel(QWidget):
    """Two-column chat UI: thread list + conversation."""

    def __init__(self, model: ChatModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model
        self._current_thread: str = EVERYONE

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(6)

        # --- left: thread list ---
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(4)

        title = QLabel("Threads")
        title.setStyleSheet("font-weight: 600;")
        ll.addWidget(title)

        self._thread_list = QListWidget()
        self._thread_list.itemSelectionChanged.connect(self._on_thread_selected)
        ll.addWidget(self._thread_list, 1)

        splitter.addWidget(left)

        # --- right: conversation + composer ---
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)

        self._header_label = QLabel("")
        self._header_label.setStyleSheet("font-weight: 600;")
        rl.addWidget(self._header_label)

        self._convo = _ConversationView()
        rl.addWidget(self._convo, 1)

        self._composer = _Composer()
        self._composer.send_requested.connect(self._on_send)
        rl.addWidget(self._composer)

        splitter.addWidget(right)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([180, 600])
        outer.addWidget(splitter, 1)

        # initial population + bindings
        self._rebuild_threads()
        self._switch_thread(EVERYONE)

        self._model.line_added.connect(self._on_line_added)
        self._model.thread_changed.connect(self._on_thread_changed)
        network_service.peer_connected.connect(self._on_peer_event)
        network_service.peer_disconnected.connect(self._on_peer_event)

    # ------------------------------------------------------------------
    # thread list

    def _rebuild_threads(self) -> None:
        previous = self._current_thread
        self._thread_list.blockSignals(True)
        self._thread_list.clear()
        for tid in self._model.thread_ids():
            item = QListWidgetItem(self._format_thread_label(tid))
            item.setData(Qt.UserRole, tid)
            self._thread_list.addItem(item)
        self._thread_list.blockSignals(False)
        # restore selection
        if not self._select_thread_in_list(previous):
            self._select_thread_in_list(EVERYONE)

    def _format_thread_label(self, tid: str) -> str:
        name = self._model.thread_display_name(tid)
        unread = self._model.unread(tid)
        offline_marker = ""
        if tid != EVERYONE:
            connected = network_service.is_connected(tid)
            if not connected:
                offline_marker = "  (offline)"
        unread_marker = f"  ({unread})" if unread else ""
        return f"{name}{unread_marker}{offline_marker}"

    def _select_thread_in_list(self, tid: str) -> bool:
        for i in range(self._thread_list.count()):
            if self._thread_list.item(i).data(Qt.UserRole) == tid:
                self._thread_list.setCurrentRow(i)
                return True
        return False

    def _on_thread_selected(self) -> None:
        items = self._thread_list.selectedItems()
        if not items:
            return
        tid = items[0].data(Qt.UserRole)
        if tid != self._current_thread:
            self._switch_thread(tid)

    def _switch_thread(self, tid: str) -> None:
        self._current_thread = tid
        self._convo.clear_and_load(self._model.lines(tid))
        self._model.mark_read(tid)
        self._header_label.setText(self._model.thread_display_name(tid))
        self._refresh_composer()

    def _refresh_composer(self) -> None:
        if self._current_thread == EVERYONE:
            connected_count = sum(
                1 for p in network_service.peers()
                if network_service.is_connected(p.peer_id)
            )
            if connected_count == 0:
                self._composer.set_enabled(False, "no connected peers")
            else:
                self._composer.set_enabled(
                    True, f"Message {connected_count} peer(s) — Enter to send",
                )
        else:
            if network_service.is_connected(self._current_thread):
                self._composer.set_enabled(True)
            else:
                self._composer.set_enabled(False, "peer offline")

    # ------------------------------------------------------------------
    # sends

    def _on_send(self, text: str) -> None:
        if self._current_thread == EVERYONE:
            self._model.send_everyone(text)
        else:
            self._model.send_direct(self._current_thread, text)

    # ------------------------------------------------------------------
    # model signals

    def _on_line_added(self, thread_id: str, line: ChatLine) -> None:
        if thread_id == self._current_thread:
            self._convo.append_line(line)
            # mark read as soon as it lands if we're looking at it
            self._model.mark_read(thread_id)
        else:
            # New thread? rebuild list. Otherwise just update its label.
            if not self._select_thread_in_list(thread_id):
                self._rebuild_threads()
            else:
                self._refresh_thread_label(thread_id)

    def _on_thread_changed(self, thread_id: str) -> None:
        # If this is a new thread we haven't rendered, rebuild the list.
        for i in range(self._thread_list.count()):
            if self._thread_list.item(i).data(Qt.UserRole) == thread_id:
                self._refresh_thread_label(thread_id)
                return
        self._rebuild_threads()

    def _refresh_thread_label(self, thread_id: str) -> None:
        for i in range(self._thread_list.count()):
            item = self._thread_list.item(i)
            if item.data(Qt.UserRole) == thread_id:
                item.setText(self._format_thread_label(thread_id))
                return
        # Thread not in list yet — rebuild
        self._rebuild_threads()

    def _on_peer_event(self, *_args) -> None:
        # Peer connected/disconnected changes offline markers, composer state,
        # and may add new threads.
        self._rebuild_threads()
        self._refresh_composer()
