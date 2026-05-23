from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .command_palette import CommandPalette
from .commands import Command, CommandRegistry
from .quick_open import QuickOpen
from .find_bar import FindBar
from .models import extract_tags, smart_title
from .note_list import NoteListWidget
from .note_view import NoteView
from .store import Note, NoteStore
from .tab_bar import TabBar
from .tag_bar import TagFilterBar
from .welcome import WELCOME_BODY


@dataclass
class TabState:
    scroll: int = 0
    cursor: int = 0
    editing: bool = False


class ScratchpadPanel(QWidget):
    status_changed = Signal(str)

    AUTOSAVE_MS = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = NoteStore()
        if not self._store.notes:
            self._store.add(title="Welcome", body=WELCOME_BODY)

        self._tab_states: dict[str, TabState] = {}
        self._closed_tabs: list[str] = []  # for Ctrl+Shift+T reopen, max 10

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._flush)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # --- Sidebar ---
        sidebar = QWidget()
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        new_btn = QPushButton("+ New note")
        new_btn.clicked.connect(self.new_note)
        sb_layout.addWidget(new_btn)

        self._tag_bar = TagFilterBar()
        self._tag_bar.tag_selected.connect(self._on_tag_selected)
        sb_layout.addWidget(self._tag_bar)

        self._note_list = NoteListWidget()
        self._note_list.note_selected.connect(self._on_sidebar_single_click)
        self._note_list.note_new_tab.connect(self._open_tab_new)
        self._note_list.action_requested.connect(self._on_list_action)
        sb_layout.addWidget(self._note_list, 1)

        splitter.addWidget(sidebar)

        # --- Main area ---
        main = QWidget()
        m_layout = QVBoxLayout(main)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(0)

        self._tab_bar = TabBar()
        self._tab_bar.tab_selected.connect(self._on_tab_selected)
        self._tab_bar.tab_closed.connect(self._on_tab_closed)
        self._tab_bar.tab_reordered.connect(self._on_tab_reordered)
        m_layout.addWidget(self._tab_bar)

        self._find_bar = FindBar()
        self._find_bar.find_requested.connect(self._on_find)
        self._find_bar.closed.connect(self._find_bar.hide)
        m_layout.addWidget(self._find_bar)

        self._view = NoteView()
        self._view.body_changed.connect(self._on_body_changed)
        m_layout.addWidget(self._view, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(0)

        self._counts = QLabel("")
        self._counts.setStyleSheet("color: #888; padding: 4px 8px;")
        footer.addWidget(self._counts, 1)

        open_folder_btn = QPushButton("Open notes folder")
        open_folder_btn.setFlat(True)
        open_folder_btn.setStyleSheet("color: #888; padding: 2px 8px;")
        open_folder_btn.clicked.connect(self._open_notes_folder)
        footer.addWidget(open_folder_btn)

        m_layout.addLayout(footer)

        splitter.addWidget(main)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 700])

        self._refresh_list(select_id=self._store.active_id)
        self._restore_tabs()

        self._registry = CommandRegistry()
        self._register_commands()

        if self._store.warnings:
            self.status_changed.emit(" | ".join(self._store.warnings))

    # ------------------------------------------------------------------
    # Tab restore on startup

    def _restore_tabs(self) -> None:
        valid_ids = {n.id for n in self._store.notes}
        tabs = [t for t in self._store.open_tabs if t in valid_ids]

        if not tabs:
            # Fall back: open the active note, or the most-recently-modified one.
            fallback = self._store.active_id or (
                self._store.sorted_notes()[0].id if self._store.notes else None
            )
            if fallback:
                tabs = [fallback]

        for note_id in tabs:
            note = self._store.get(note_id)
            if note:
                self._tab_bar.add_tab(note_id, note.title)

        # Activate the stored active tab.
        active = self._store.active_id if self._store.active_id in valid_ids else None
        if active and self._tab_bar.has_note(active):
            self._tab_bar.focus_tab(active)
            self._load_note_into_view(active)
        elif self._tab_bar.count():
            first_id = self._tab_bar.tabData(0)
            self._tab_bar.focus_tab(first_id)
            self._load_note_into_view(first_id)

    # ------------------------------------------------------------------
    # Commands + shortcuts

    def _register_commands(self) -> None:
        has_note = lambda: self._tab_bar.current_note_id() is not None
        has_closed = lambda: bool(self._closed_tabs)
        cmds = [
            Command("scratchpad.new_note",       "New note",              self.new_note,                  "Ctrl+N"),
            Command("scratchpad.close_tab",      "Close tab",             self._close_current_tab,        "Ctrl+W",         has_note),
            Command("scratchpad.reopen_tab",     "Reopen closed tab",     self._reopen_last_closed_tab,   "Ctrl+Shift+T",   has_closed),
            Command("scratchpad.delete_note",    "Delete note",           self._delete_current,           None,             has_note),
            Command("scratchpad.save",           "Save",                  self._flush,                    "Ctrl+S",         has_note),
            Command("scratchpad.toggle_mode",    "Toggle Edit / Preview", self._view.toggle_mode,         "Ctrl+E",         has_note),
            Command("scratchpad.find",           "Find in notes",         self._open_find,                "Ctrl+F"),
            Command("scratchpad.next_tab",       "Next tab",              lambda: self._cycle_tabs(+1),   "Ctrl+Tab"),
            Command("scratchpad.prev_tab",       "Previous tab",          lambda: self._cycle_tabs(-1),   "Ctrl+Shift+Tab"),
            Command("scratchpad.duplicate_line", "Duplicate line",        self._duplicate_line,           "Ctrl+D",         has_note),
            Command("scratchpad.quick_open",     "Go to note…",           self._open_quick_open,          "Ctrl+P"),
            Command("scratchpad.open_folder",    "Open notes folder",     self._open_notes_folder),
            Command("scratchpad.palette",        "Open command palette",  self._open_palette,             "Ctrl+Shift+P"),
        ]
        for cmd in cmds:
            self._registry.register(cmd)
            if cmd.shortcut:
                sc = QShortcut(QKeySequence(cmd.shortcut), self)
                sc.setContext(Qt.WidgetWithChildrenShortcut)
                sc.activated.connect(lambda cid=cmd.id: self._registry.execute(cid))

    # ------------------------------------------------------------------
    # Sidebar → tab interaction

    def _on_sidebar_single_click(self, note_id: str) -> None:
        if self._tab_bar.has_note(note_id):
            # Already open — just focus it.
            self._switch_to_tab(note_id)
        else:
            # Replace the active tab (VS Code preview-tab semantics).
            active = self._tab_bar.current_note_id()
            if active:
                self._save_tab_state(active)
                self._tab_bar.remove_tab_by_id(active)
            self._open_tab(note_id)

    def _open_tab_new(self, note_id: str) -> None:
        """Open note_id as an additional tab without closing the current one."""
        if self._tab_bar.has_note(note_id):
            self._switch_to_tab(note_id)
            return
        self._open_tab(note_id)

    def _open_tab(self, note_id: str) -> None:
        """Add a new tab for note_id and activate it."""
        note = self._store.get(note_id)
        if note is None:
            return
        self._flush_current_tab()
        idx = self._tab_bar.add_tab(note_id, note.title)
        self._tab_bar.blockSignals(True)
        self._tab_bar.setCurrentIndex(idx)
        self._tab_bar.blockSignals(False)
        self._store.active_id = note_id
        self._persist_tabs()
        self._load_note_into_view(note_id)
        self._update_sidebar_selection(note_id)

    def _switch_to_tab(self, note_id: str) -> None:
        self._flush_current_tab()
        self._save_tab_state(self._tab_bar.current_note_id())
        self._tab_bar.focus_tab(note_id)
        self._store.active_id = note_id
        self._persist_tabs()
        self._load_note_into_view(note_id)
        self._update_sidebar_selection(note_id)

    # ------------------------------------------------------------------
    # Tab bar signals

    def _on_tab_selected(self, note_id: str) -> None:
        self._save_tab_state(self._store.active_id)
        self._store.active_id = note_id
        self._persist_tabs()
        self._load_note_into_view(note_id)
        self._update_sidebar_selection(note_id)

    def _on_tab_closed(self, note_id: str) -> None:
        self._flush_current_tab()
        self._save_tab_state(note_id)

        # Remember for reopen.
        if note_id not in self._closed_tabs:
            self._closed_tabs.append(note_id)
            if len(self._closed_tabs) > 10:
                self._closed_tabs.pop(0)

        was_active = self._tab_bar.current_note_id() == note_id
        self._tab_bar.remove_tab_by_id(note_id)

        if self._tab_bar.count() == 0:
            self._store.active_id = None
            self._view.clear()
            self._counts.setText("")
        elif was_active:
            # Focus whatever tab is now current after removal.
            new_id = self._tab_bar.current_note_id()
            if new_id:
                self._store.active_id = new_id
                self._load_note_into_view(new_id)
                self._update_sidebar_selection(new_id)

        self._persist_tabs()

    def _on_tab_reordered(self, new_order: list[str]) -> None:
        self._store.open_tabs = new_order
        self._store.save()

    # ------------------------------------------------------------------
    # Tab state save/restore

    def _save_tab_state(self, note_id: str | None) -> None:
        if note_id is None:
            return
        sb = self._view.editor.verticalScrollBar()
        self._tab_states[note_id] = TabState(
            scroll=sb.value(),
            cursor=self._view.editor.textCursor().position(),
            editing=self._view.is_editing(),
        )

    def _load_note_into_view(self, note_id: str) -> None:
        note = self._store.get(note_id)
        if note is None:
            return
        state = self._tab_states.get(note_id)
        self._view.load_note(note)
        if state:
            if state.editing:
                self._view.enter_edit()
            else:
                self._view.enter_preview()
            cursor = self._view.editor.textCursor()
            cursor.setPosition(min(state.cursor, len(note.body)))
            self._view.editor.setTextCursor(cursor)
            self._view.editor.verticalScrollBar().setValue(state.scroll)
        self._update_counts()
        self.status_changed.emit(note.title)

    # ------------------------------------------------------------------
    # Sidebar sync

    def _update_sidebar_selection(self, note_id: str) -> None:
        self._note_list.blockSignals(True)
        self._note_list.select_id(note_id)
        self._note_list.blockSignals(False)

    # ------------------------------------------------------------------
    # Persist tabs to store

    def _persist_tabs(self) -> None:
        self._store.open_tabs = self._tab_bar.all_note_ids()
        self._store.save()

    # ------------------------------------------------------------------
    # Tab commands

    def _close_current_tab(self) -> None:
        note_id = self._tab_bar.current_note_id()
        if note_id:
            self._on_tab_closed(note_id)

    def _reopen_last_closed_tab(self) -> None:
        while self._closed_tabs:
            note_id = self._closed_tabs.pop()
            if self._store.get(note_id) is not None:
                self._open_tab_new(note_id)
                return

    def _cycle_tabs(self, direction: int) -> None:
        count = self._tab_bar.count()
        if count < 2:
            return
        idx = (self._tab_bar.currentIndex() + direction) % count
        self._tab_bar.setCurrentIndex(idx)

    def _flush_current_tab(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()

    # ------------------------------------------------------------------
    # Note list

    def _refresh_list(self, *, select_id: str | None = None) -> None:
        active_tag = self._tag_bar.active()
        notes = [
            n for n in self._store.sorted_notes()
            if not active_tag or active_tag in extract_tags(n.body)
        ]
        self._note_list.populate(notes, select_id=select_id or self._store.active_id)
        self._refresh_tag_bar()

    def _refresh_tag_bar(self) -> None:
        counts: dict[str, int] = {}
        for note in self._store.notes:
            for tag in extract_tags(note.body):
                counts[tag] = counts.get(tag, 0) + 1
        self._tag_bar.set_tags(counts)

    def _on_tag_selected(self, _tag: object) -> None:
        self._refresh_list(select_id=self._store.active_id)

    def _on_list_action(self, action: str, note_id: str) -> None:
        if action == "new":
            self.new_note()
        elif action == "pin":
            self._store.set_pinned(note_id, True)
            self._refresh_list(select_id=note_id)
        elif action == "unpin":
            self._store.set_pinned(note_id, False)
            self._refresh_list(select_id=note_id)
        elif action == "duplicate":
            copy = self._store.duplicate(note_id)
            if copy:
                self._refresh_list(select_id=copy.id)
                self._open_tab_new(copy.id)
        elif action == "rename":
            self._rename_note(note_id)
        elif action == "delete":
            self._delete_note(note_id)

    # ------------------------------------------------------------------
    # Body change → autosave

    def _on_body_changed(self, body: str) -> None:
        note_id = self._tab_bar.current_note_id()
        if not note_id:
            return
        note = self._store.get(note_id)
        if note is None:
            return
        inferred = smart_title(body)
        if note.title in ("", "Untitled") or note.title == smart_title(note.body):
            note.title = inferred
            self._tab_bar.update_title(note_id, inferred)
        note.body = body
        self._save_timer.start()
        self._update_counts()

    def _flush(self) -> None:
        note_id = self._tab_bar.current_note_id()
        if not note_id:
            return
        note = self._store.get(note_id)
        if note is None:
            return
        note.modified = time.time()
        self._store.save_note(note)
        self._note_list.refresh_item(note)
        self._refresh_tag_bar()
        self.status_changed.emit(f"Saved · {note.title}")

    # ------------------------------------------------------------------
    # Counts

    def _update_counts(self) -> None:
        text = self._view.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        chars = len(text)
        lines = text.count("\n") + (1 if text else 0)
        self._counts.setText(f"{words} words · {chars} chars · {lines} lines")

    # ------------------------------------------------------------------
    # Note actions

    def _rename_note(self, note_id: str) -> None:
        note = self._store.get(note_id)
        if note is None:
            return
        new_title, ok = QInputDialog.getText(
            self, "Rename note", "Title:", QLineEdit.Normal, note.title
        )
        if ok and new_title.strip():
            note.title = new_title.strip()
            self._store.save_note(note)
            self._tab_bar.update_title(note_id, note.title)
            self._refresh_list(select_id=note_id)

    def _delete_note(self, note_id: str) -> None:
        note = self._store.get(note_id)
        if note is None:
            return
        reply = QMessageBox.question(
            self, "Delete note",
            f"Delete '{note.title}'?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        # Close the tab first if open.
        if self._tab_bar.has_note(note_id):
            self._tab_bar.remove_tab_by_id(note_id)
            if self._tab_bar.count() == 0:
                self._view.clear()
                self._counts.setText("")
            elif self._store.active_id == note_id:
                new_id = self._tab_bar.current_note_id()
                if new_id:
                    self._store.active_id = new_id
                    self._load_note_into_view(new_id)
        self._store.remove(note_id)
        self._persist_tabs()
        self._refresh_list(select_id=self._store.active_id)

    def _delete_current(self) -> None:
        note_id = self._tab_bar.current_note_id()
        if note_id:
            self._delete_note(note_id)

    # ------------------------------------------------------------------
    # Find

    def _open_find(self) -> None:
        self._find_bar.show()
        self._find_bar.focus_input()

    def _on_find(self, query: str) -> None:
        q_raw = query.strip()
        if not q_raw:
            return

        tag_match = re.fullmatch(r"#([A-Za-z][\w\-]*)", q_raw)
        if tag_match:
            tag = tag_match.group(1).lower()
            matching = [n for n in self._store.notes if tag in extract_tags(n.body)]
            if not matching:
                self.status_changed.emit(f"No notes tagged #{tag}")
                return
            self._tag_bar.set_active(tag)
            active = self._store.active_id
            target = next((n for n in matching if n.id == active), matching[0])
            self._open_tab_new(target.id)
            self.status_changed.emit(
                f"Filtered by #{tag} · {len(matching)} note{'s' if len(matching) != 1 else ''}"
            )
            return

        q = q_raw.lower()
        notes = self._store.sorted_notes()
        active = self._store.active_id
        if active:
            notes = sorted(notes, key=lambda n: 0 if n.id == active else 1)
        for note in notes:
            idx = note.body.lower().find(q)
            if idx >= 0 or q in note.title.lower():
                if note.id != active:
                    self._open_tab_new(note.id)
                if idx >= 0:
                    self._view.enter_edit()
                    cursor = self._view.editor.textCursor()
                    cursor.setPosition(idx)
                    cursor.setPosition(idx + len(q_raw), QTextCursor.KeepAnchor)
                    self._view.editor.setTextCursor(cursor)
                    self._view.editor.ensureCursorVisible()
                self.status_changed.emit(f"Found in '{note.title}'")
                return
        self.status_changed.emit("No match")

    # ------------------------------------------------------------------
    # Editor commands

    def _duplicate_line(self) -> None:
        editor = self._view.editor
        cursor = editor.textCursor()
        cursor.beginEditBlock()
        cursor.movePosition(QTextCursor.StartOfLine)
        cursor.movePosition(QTextCursor.EndOfLine, QTextCursor.KeepAnchor)
        line = cursor.selectedText()
        cursor.movePosition(QTextCursor.EndOfLine)
        cursor.insertText("\n" + line)
        cursor.endEditBlock()

    # ------------------------------------------------------------------
    # Notes folder + palette

    def _open_quick_open(self) -> None:
        notes = self._store.sorted_notes()
        dialog = QuickOpen(notes, self)
        dialog.adjustSize()
        center = self.rect().center()
        dialog.move(self.mapToGlobal(center) - dialog.rect().center())
        if dialog.exec() and dialog.selected_id:
            self._open_tab_new(dialog.selected_id)

    def _open_notes_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._store.notes_folder())))

    def _open_palette(self) -> None:
        palette = CommandPalette(self._registry, self)
        palette.adjustSize()
        center = self.rect().center()
        palette.move(self.mapToGlobal(center) - palette.rect().center())
        palette.exec()

    # ------------------------------------------------------------------
    # Public API

    def new_note(self) -> None:
        note = self._store.add(title="Untitled", body="")
        self._tag_bar.blockSignals(True)
        self._tag_bar.clear_selection()
        self._tag_bar.blockSignals(False)
        self._refresh_list(select_id=note.id)
        self._open_tab_new(note.id)
        self._view.enter_edit()
        self._view.editor.setFocus()

    def deactivate(self) -> None:
        self._flush_current_tab()
