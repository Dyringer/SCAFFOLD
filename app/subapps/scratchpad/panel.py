from __future__ import annotations

import re
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMessageBox,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from .find_bar import FindBar
from .models import extract_tags, smart_title
from .note_list import NoteListWidget
from .note_view import NoteView
from .store import Note, NoteStore
from .tag_bar import TagFilterBar
from .welcome import WELCOME_BODY


class ScratchpadPanel(QWidget):
    status_changed = Signal(str)

    AUTOSAVE_MS = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = NoteStore()
        if not self._store.notes:
            self._store.add(title="Welcome", body=WELCOME_BODY)

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
        self._note_list.note_selected.connect(self._on_note_selected)
        self._note_list.action_requested.connect(self._on_list_action)
        sb_layout.addWidget(self._note_list, 1)

        splitter.addWidget(sidebar)

        # --- Main area ---
        main = QWidget()
        m_layout = QVBoxLayout(main)
        m_layout.setContentsMargins(0, 0, 0, 0)
        m_layout.setSpacing(0)

        self._find_bar = FindBar()
        self._find_bar.find_requested.connect(self._on_find)
        self._find_bar.closed.connect(self._find_bar.hide)
        m_layout.addWidget(self._find_bar)

        self._view = NoteView()
        self._view.body_changed.connect(self._on_body_changed)
        m_layout.addWidget(self._view, 1)

        self._counts = QLabel("")
        self._counts.setStyleSheet("color: #888; padding: 4px 8px;")
        m_layout.addWidget(self._counts)

        splitter.addWidget(main)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 700])

        self._refresh_list(select_id=self._store.active_id)
        self._install_shortcuts()

    # ------------------------------------------------------------------
    # Shortcuts

    def _install_shortcuts(self) -> None:
        def sc(seq: str, fn) -> None:
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.WidgetWithChildrenShortcut)
            s.activated.connect(fn)

        sc("Ctrl+N", self.new_note)
        sc("Ctrl+W", self._delete_current)
        sc("Ctrl+S", self._flush)
        sc("Ctrl+E", self._view.toggle_mode)
        sc("Ctrl+F", self._open_find)
        sc("Ctrl+Tab", lambda: self._cycle(+1))
        sc("Ctrl+Shift+Tab", lambda: self._cycle(-1))
        sc("Ctrl+D", self._duplicate_line)

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

    def _on_note_selected(self, note_id: str) -> None:
        # Flush any pending edits to the previous note first.
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()
        note = self._store.get(note_id)
        if note is None:
            return
        self._store.active_id = note.id
        self._store.save()
        self._view.load_note(note)
        self._update_counts()
        self.status_changed.emit(note.title)

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
        elif action == "rename":
            self._rename_note(note_id)
        elif action == "delete":
            self._delete_note(note_id)

    # ------------------------------------------------------------------
    # Body change → autosave

    def _on_body_changed(self, body: str) -> None:
        if not self._store.active_id:
            return
        note = self._store.get(self._store.active_id)
        if note is None:
            return
        inferred = smart_title(body)
        if note.title in ("", "Untitled") or note.title == smart_title(note.body):
            note.title = inferred
        note.body = body
        self._save_timer.start()
        self._update_counts()

    def _flush(self) -> None:
        if not self._store.active_id:
            return
        note = self._store.get(self._store.active_id)
        if note is None:
            return
        note.modified = time.time()
        self._store.save()
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
            self._store.save()
            self._refresh_list(select_id=note.id)

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
        self._store.remove(note_id)
        self._refresh_list(select_id=self._store.active_id)

    def _delete_current(self) -> None:
        if self._store.active_id:
            self._delete_note(self._store.active_id)

    # ------------------------------------------------------------------
    # Cycling

    def _cycle(self, direction: int) -> None:
        count = self._note_list.count()
        if count == 0:
            return
        row = self._note_list.currentRow()
        self._note_list.setCurrentRow((row + direction) % count)

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
            target = next(
                (n for n in matching if n.id == self._store.active_id),
                matching[0],
            )
            self._note_list.select_id(target.id)
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
                    self._note_list.select_id(note.id)
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
    # Public API

    def new_note(self) -> None:
        note = self._store.add(title="Untitled", body="")
        self._tag_bar.blockSignals(True)
        self._tag_bar.clear_selection()
        self._tag_bar.blockSignals(False)
        self._refresh_list(select_id=note.id)
        self._view.enter_edit()
        self._view.editor.setFocus()

    def deactivate(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()
