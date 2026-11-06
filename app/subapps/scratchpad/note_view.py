from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from app.core.theme_manager import theme_manager

from .editor import MarkdownEditor
from .highlighter import MarkdownHighlighter
from .preview import MarkdownPreview
from .store import Note
from .view_toggle import ViewToggleBar


class NoteView(QWidget):
    """Editor / preview stack.

    The Edit / Preview toggle (`toggle_bar`) is not part of this widget's
    layout: the host places it (the Scratchpad panel puts it in the tab row).
    """

    body_changed = Signal(str)

    PAGE_EDIT = 0
    PAGE_PREVIEW = 1

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.toggle_bar = ViewToggleBar()

        self._stack = QStackedWidget()
        self._stack.setObjectName("Plain")
        layout.addWidget(self._stack, 1)

        self.editor = MarkdownEditor()
        self.preview = MarkdownPreview()
        self._stack.addWidget(self.editor)   # PAGE_EDIT = 0
        self._stack.addWidget(self.preview)  # PAGE_PREVIEW = 1

        self._highlighter = MarkdownHighlighter(self.editor.document())
        self._current_note_id: str | None = None
        self._suppress_change = False

        self.editor.textChanged.connect(self._on_text_changed)
        self.toggle_bar.mode_changed.connect(self._on_toggle)
        theme_manager.theme_changed.connect(self._on_theme_changed)

        self._stack.setCurrentIndex(self.PAGE_PREVIEW)

    def load_note(self, note: Note | None) -> None:
        was_editing = self.is_editing()
        self._suppress_change = True
        if note is None:
            self._current_note_id = None
            self.editor.setPlainText("")
            self.preview.set_markdown("")
            self._suppress_change = False
            return
        self._current_note_id = note.id
        self.editor.setPlainText(note.body)
        self._suppress_change = False
        if was_editing:
            self.enter_edit()
        else:
            self.enter_preview()

    def clear(self) -> None:
        self._current_note_id = None
        self._suppress_change = True
        self.editor.setPlainText("")
        self.preview.set_markdown("")
        self._suppress_change = False

    def _on_text_changed(self) -> None:
        if self._suppress_change:
            return
        self.body_changed.emit(self.editor.toPlainText())

    def _on_toggle(self, mode: str) -> None:
        if mode == "edit":
            self._stack.setCurrentIndex(self.PAGE_EDIT)
            self.editor.setFocus()
        else:
            self.preview.set_markdown(self.editor.toPlainText())
            self._stack.setCurrentIndex(self.PAGE_PREVIEW)

    def _on_theme_changed(self, _name: str) -> None:
        if not self.is_editing():
            self.preview.set_markdown(self.editor.toPlainText())

    def enter_edit(self) -> None:
        self.toggle_bar.set_mode("edit")
        self._stack.setCurrentIndex(self.PAGE_EDIT)
        self.editor.setFocus()
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.editor.setTextCursor(cursor)

    def enter_preview(self) -> None:
        self.preview.set_markdown(self.editor.toPlainText())
        self.toggle_bar.set_mode("preview")
        self._stack.setCurrentIndex(self.PAGE_PREVIEW)

    def toggle_mode(self) -> None:
        if self.is_editing():
            self.enter_preview()
        else:
            self.enter_edit()

    def is_editing(self) -> bool:
        return self._stack.currentIndex() == self.PAGE_EDIT
