from __future__ import annotations

import re
from datetime import datetime

from PySide6.QtCore import (
    QEvent, QObject, QPoint, QSize, QTimer, Qt, Signal,
)
from PySide6.QtGui import (
    QAction, QFont, QGuiApplication, QKeySequence, QMouseEvent, QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSplitter, QStackedWidget, QTextBrowser, QVBoxLayout,
    QWidget,
)

from app.core.registry import registry
from app.core.theme_manager import theme_manager

from .highlighter import MarkdownHighlighter
from .store import Note, NoteStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NUMERIC_RE = re.compile(
    r"^\s*(?:0x[0-9a-fA-F_]+|0b[01_]+|0o[0-7_]+|-?\d[\d_]*)\s*$"
)


def _format_modified(ts: float) -> str:
    try:
        dt = datetime.fromtimestamp(ts)
    except Exception:
        return ""
    now = datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%H:%M")
    if (now - dt).days < 7:
        return dt.strftime("%a %H:%M")
    return dt.strftime("%Y-%m-%d")


def _smart_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:60]
    return "Untitled"


# ---------------------------------------------------------------------------
# Editor — plain text edit with the standard modern-editor behavior
# ---------------------------------------------------------------------------

class MarkdownEditor(QPlainTextEdit):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabChangesFocus(False)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setUndoRedoEnabled(True)
        self.setAcceptDrops(True)


# ---------------------------------------------------------------------------
# Preview — QTextBrowser with click-to-edit
# ---------------------------------------------------------------------------

class MarkdownPreview(QTextBrowser):
    edit_requested = Signal()  # emitted on plain click (not on link click)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setOpenLinks(True)
        self.setReadOnly(True)
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)

    def set_markdown(self, text: str) -> None:
        # Promote bare URLs so QTextDocument auto-renders them as links.
        # QTextDocument.setMarkdown already handles [text](url) syntax.
        self.document().setMarkdown(text or "*(empty note — click to edit)*")

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # If the click is on a link, let the base class handle it (open URL).
        anchor = self.anchorAt(event.pos())
        if anchor:
            super().mousePressEvent(event)
            return
        # Otherwise: enter edit mode.
        self.edit_requested.emit()
        # Don't call super — we don't want a selection rectangle starting in
        # the preview that the user will never see.


# ---------------------------------------------------------------------------
# Sidebar item
# ---------------------------------------------------------------------------

class _NoteItemWidget(QWidget):
    def __init__(self, note: Note, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(4)

        pin = QLabel("📌" if note.pinned else "")
        pin.setFixedWidth(14)
        title_row.addWidget(pin)

        self._title = QLabel(note.title or "Untitled")
        f = self._title.font()
        f.setBold(True)
        self._title.setFont(f)
        self._title.setTextInteractionFlags(Qt.NoTextInteraction)
        title_row.addWidget(self._title, 1)

        layout.addLayout(title_row)

        self._meta = QLabel(_format_modified(note.modified))
        mf = self._meta.font()
        mf.setPointSize(max(8, mf.pointSize() - 1))
        self._meta.setFont(mf)
        self._meta.setStyleSheet("color: #888;")
        layout.addWidget(self._meta)


# ---------------------------------------------------------------------------
# Note view — editor/preview stack
# ---------------------------------------------------------------------------

class NoteView(QStackedWidget):
    body_changed = Signal(str)        # body
    title_inferred = Signal(str)      # new title (after inference)

    PAGE_EDIT = 0
    PAGE_PREVIEW = 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = MarkdownEditor(self)
        self.preview = MarkdownPreview(self)
        self.addWidget(self.editor)   # 0
        self.addWidget(self.preview)  # 1

        self._highlighter = MarkdownHighlighter(self.editor.document())
        self._current_note_id: str | None = None
        self._suppress_change = False

        self.editor.textChanged.connect(self._on_text_changed)
        self.preview.edit_requested.connect(self._enter_edit)

    def load_note(self, note: Note | None) -> None:
        self._suppress_change = True
        if note is None:
            self._current_note_id = None
            self.editor.setPlainText("")
            self.preview.set_markdown("")
            self._suppress_change = False
            return
        self._current_note_id = note.id
        self.editor.setPlainText(note.body)
        self.preview.set_markdown(note.body)
        # Default to preview when loading a different note.
        self.setCurrentIndex(self.PAGE_PREVIEW)
        self._suppress_change = False

    def clear(self) -> None:
        self._current_note_id = None
        self._suppress_change = True
        self.editor.setPlainText("")
        self.preview.set_markdown("")
        self._suppress_change = False

    def _on_text_changed(self) -> None:
        if self._suppress_change:
            return
        text = self.editor.toPlainText()
        self.body_changed.emit(text)

    def _enter_edit(self) -> None:
        self.setCurrentIndex(self.PAGE_EDIT)
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)

    def enter_preview(self) -> None:
        # Re-render in case body changed since last view
        self.preview.set_markdown(self.editor.toPlainText())
        self.setCurrentIndex(self.PAGE_PREVIEW)

    def enter_edit(self) -> None:
        self._enter_edit()

    def is_editing(self) -> bool:
        return self.currentIndex() == self.PAGE_EDIT


# ---------------------------------------------------------------------------
# Find bar
# ---------------------------------------------------------------------------

class FindBar(QFrame):
    find_requested = Signal(str)
    closed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        self._input = QLineEdit()
        self._input.setPlaceholderText("Find in all notes…")
        self._input.returnPressed.connect(self._fire)
        layout.addWidget(self._input, 1)

        btn = QPushButton("Find")
        btn.clicked.connect(self._fire)
        layout.addWidget(btn)

        close = QPushButton("✕")
        close.setFixedWidth(28)
        close.clicked.connect(self.closed)
        layout.addWidget(close)

        self.hide()

    def _fire(self) -> None:
        self.find_requested.emit(self._input.text())

    def focus_input(self) -> None:
        self._input.setFocus()
        self._input.selectAll()


# ---------------------------------------------------------------------------
# Main panel
# ---------------------------------------------------------------------------

class ScratchpadPanel(QWidget):
    status_changed = Signal(str)

    AUTOSAVE_MS = 500

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._store = NoteStore()
        if not self._store.notes:
            self._store.add(title="Welcome", body=_WELCOME_BODY)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(self.AUTOSAVE_MS)
        self._save_timer.timeout.connect(self._flush)

        # Layout: [sidebar | main]
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Sidebar
        sidebar = QWidget()
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        new_btn = QPushButton("+ New note")
        new_btn.clicked.connect(self.new_note)
        sb_layout.addWidget(new_btn)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_context_menu)
        self._list.currentItemChanged.connect(self._on_current_item_changed)
        sb_layout.addWidget(self._list, 1)

        splitter.addWidget(sidebar)

        # Main area
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
        self._view.editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self._view.editor.customContextMenuRequested.connect(self._on_editor_context_menu)
        m_layout.addWidget(self._view, 1)

        # Footer (counts)
        self._counts = QLabel("")
        self._counts.setStyleSheet("color: #888; padding: 4px 8px;")
        m_layout.addWidget(self._counts)

        splitter.addWidget(main)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([220, 700])

        # Refresh sidebar entries
        self._refresh_list(select_id=self._store.active_id)

        # Shortcuts
        self._install_shortcuts()

        # Focus-driven preview render
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_app_focus_changed)

        # Re-render preview on theme change
        theme_manager.theme_changed.connect(self._on_theme_changed)

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
        sc("Ctrl+E", self._toggle_preview)
        sc("Ctrl+F", self._open_find)
        sc("Ctrl+Tab", lambda: self._cycle(+1))
        sc("Ctrl+Shift+Tab", lambda: self._cycle(-1))
        sc("Ctrl+D", self._duplicate_line)

    # ------------------------------------------------------------------
    # Note list

    def _refresh_list(self, *, select_id: str | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for note in self._store.sorted_notes():
            item = QListWidgetItem()
            widget = _NoteItemWidget(note)
            item.setSizeHint(QSize(0, max(40, widget.sizeHint().height())))
            item.setData(Qt.UserRole, note.id)
            self._list.addItem(item)
            self._list.setItemWidget(item, widget)
        self._list.blockSignals(False)

        # Select the active note
        target = select_id or self._store.active_id
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(Qt.UserRole) == target:
                self._list.setCurrentItem(it)
                return
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            self._view.clear()

    def _on_current_item_changed(self, current: QListWidgetItem | None, _prev) -> None:
        # Flush any pending edits to the previous note first
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()
        if current is None:
            self._view.clear()
            self._update_counts()
            return
        note_id = current.data(Qt.UserRole)
        note = self._store.get(note_id)
        if note is None:
            return
        self._store.active_id = note.id
        self._store.save()
        self._view.load_note(note)
        self._update_counts()
        self.status_changed.emit(note.title)

    # ------------------------------------------------------------------
    # Body change → autosave

    def _on_body_changed(self, body: str) -> None:
        if not self._store.active_id:
            return
        # If the current title looks like an auto-title, refresh it.
        note = self._store.get(self._store.active_id)
        if note is None:
            return
        inferred = _smart_title(body)
        if note.title in ("", "Untitled") or note.title == _smart_title(note.body):
            note.title = inferred
        note.body = body
        # Defer save
        self._save_timer.start()
        self._update_counts()

    def _flush(self) -> None:
        if not self._store.active_id:
            return
        note = self._store.get(self._store.active_id)
        if note is None:
            return
        import time
        note.modified = time.time()
        self._store.save()
        # Update the current sidebar item in place (no rebuild → no focus steal).
        self._update_current_item(note)
        self.status_changed.emit(f"Saved · {note.title}")

    def _update_current_item(self, note: Note) -> None:
        """Refresh the widget for the currently selected list item only."""
        item = self._list.currentItem()
        if item is None or item.data(Qt.UserRole) != note.id:
            return
        widget = _NoteItemWidget(note)
        item.setSizeHint(QSize(0, max(40, widget.sizeHint().height())))
        self._list.setItemWidget(item, widget)

    # ------------------------------------------------------------------
    # Focus-driven render

    def _on_app_focus_changed(self, old: QWidget | None, new: QWidget | None) -> None:
        # Flip to preview whenever the editor loses focus to anything that
        # isn't a descendant of the editor itself (sidebar click, header,
        # other app, taskbar, etc).
        if not self._view.is_editing():
            return
        editor = self._view.editor
        # Only act when the *editor* is the one losing focus.
        if old is not editor:
            return
        # If focus moved to a child of the editor (e.g. its own context menu
        # popup) keep editing.
        if new is not None and (new is editor or editor.isAncestorOf(new)):
            return
        self._render_to_preview()

    def _render_to_preview(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()
        self._view.enter_preview()

    def _toggle_preview(self) -> None:
        if self._view.is_editing():
            self._render_to_preview()
        else:
            self._view.enter_edit()

    # ------------------------------------------------------------------
    # Counts

    def _update_counts(self) -> None:
        text = self._view.editor.toPlainText()
        words = len(re.findall(r"\S+", text))
        chars = len(text)
        lines = text.count("\n") + (1 if text else 0)
        self._counts.setText(f"{words} words · {chars} chars · {lines} lines")

    # ------------------------------------------------------------------
    # Context menu — sidebar

    def _on_list_context_menu(self, pos: QPoint) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            menu = QMenu(self)
            menu.addAction("New note", self.new_note)
            menu.exec(self._list.viewport().mapToGlobal(pos))
            return
        note_id = item.data(Qt.UserRole)
        note = self._store.get(note_id)
        if note is None:
            return
        menu = QMenu(self)
        menu.addAction(
            "Unpin" if note.pinned else "Pin to top",
            lambda nid=note.id, p=not note.pinned: self._toggle_pin(nid, p),
        )
        menu.addAction("Duplicate", lambda nid=note.id: self._duplicate_note(nid))
        menu.addAction("Rename…", lambda nid=note.id: self._rename_note(nid))
        menu.addSeparator()
        menu.addAction("Delete", lambda nid=note.id: self._delete_note(nid))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _toggle_pin(self, note_id: str, pinned: bool) -> None:
        self._store.set_pinned(note_id, pinned)
        self._refresh_list(select_id=note_id)

    def _duplicate_note(self, note_id: str) -> None:
        copy = self._store.duplicate(note_id)
        if copy:
            self._refresh_list(select_id=copy.id)

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
    # Context menu — editor (Send to Programmer Calc)

    def _on_editor_context_menu(self, pos: QPoint) -> None:
        menu = self._view.editor.createStandardContextMenu()
        sel = self._view.editor.textCursor().selectedText().strip()
        if sel and _NUMERIC_RE.match(sel):
            menu.addSeparator()
            act = QAction(f"Send '{sel}' to Programmer Calc", menu)
            act.triggered.connect(lambda _=False, s=sel: self._send_to_calc(s))
            menu.addAction(act)
        menu.exec(self._view.editor.mapToGlobal(pos))

    def _send_to_calc(self, value: str) -> None:
        QGuiApplication.clipboard().setText(value)
        registry.activate("programmer_calc")
        self.status_changed.emit(f"Sent {value} to Programmer Calc (clipboard)")

    # ------------------------------------------------------------------
    # Cycling

    def _cycle(self, direction: int) -> None:
        count = self._list.count()
        if count == 0:
            return
        row = self._list.currentRow()
        new_row = (row + direction) % count
        self._list.setCurrentRow(new_row)

    # ------------------------------------------------------------------
    # Find

    def _open_find(self) -> None:
        self._find_bar.show()
        self._find_bar.focus_input()

    def _on_find(self, query: str) -> None:
        if not query:
            return
        q = query.lower()
        # Look in order: current note first, then others
        notes = self._store.sorted_notes()
        active = self._store.active_id
        if active:
            # Move active to front of search list
            notes = sorted(notes, key=lambda n: 0 if n.id == active else 1)
        for note in notes:
            idx = note.body.lower().find(q)
            if idx >= 0 or q in note.title.lower():
                # Switch to that note
                if note.id != active:
                    self._select_id(note.id)
                # Highlight match in editor
                if idx >= 0:
                    self._view.enter_edit()
                    cursor = self._view.editor.textCursor()
                    cursor.setPosition(idx)
                    cursor.setPosition(idx + len(query), QTextCursor.KeepAnchor)
                    self._view.editor.setTextCursor(cursor)
                    self._view.editor.ensureCursorVisible()
                self.status_changed.emit(f"Found in '{note.title}'")
                return
        self.status_changed.emit("No match")

    def _select_id(self, note_id: str) -> None:
        for i in range(self._list.count()):
            it = self._list.item(i)
            if it.data(Qt.UserRole) == note_id:
                self._list.setCurrentItem(it)
                return

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
        self._refresh_list(select_id=note.id)
        self._view.enter_edit()
        self._view.editor.setFocus()

    def deactivate(self) -> None:
        """Called when sub-app loses activation — flush + render."""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._flush()

    # ------------------------------------------------------------------
    # Theme

    def _on_theme_changed(self, _name: str) -> None:
        # Re-render preview so any CSS inherited from QPalette refreshes.
        if not self._view.is_editing():
            self._view.preview.set_markdown(self._view.editor.toPlainText())


# ---------------------------------------------------------------------------
# Welcome content
# ---------------------------------------------------------------------------

_WELCOME_BODY = """# Welcome to Scratchpad

A quick place to **paste**, jot, and search.

## Editing

- Type to edit — focus loss renders the preview.
- Click the preview to return to raw mode.
- `Ctrl+E` flips manually.

## Shortcuts

- `Ctrl+N` — new note
- `Ctrl+W` — delete current note
- `Ctrl+Tab` / `Ctrl+Shift+Tab` — cycle notes
- `Ctrl+F` — search across all notes
- `Ctrl+S` — flush save (autosaves anyway)
- `Ctrl+D` — duplicate current line

## Embedded-dev bonus

Select a number like `0xDEADBEEF` and right-click → *Send to Programmer Calc*.

> Notes autosave to `.local/scratchpad.json`.
"""
