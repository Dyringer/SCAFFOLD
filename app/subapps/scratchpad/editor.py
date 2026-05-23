from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QKeyEvent, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from .models import _LIST_RE


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

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and not event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)
            and self._handle_list_continuation()
        ):
            return
        super().keyPressEvent(event)

    def _handle_list_continuation(self) -> bool:
        cursor = self.textCursor()
        if cursor.hasSelection():
            return False
        block_text = cursor.block().text()
        pos_in_block = cursor.positionInBlock()
        # Only continue when Enter is pressed at end of line — matches typical
        # editors and avoids surprising mid-line splits.
        if pos_in_block != len(block_text):
            return False
        match = _LIST_RE.match(block_text)
        if not match:
            return False

        indent = match.group("indent")
        rest = match.group("rest")
        bullet = match.group("bullet")
        check = match.group("check")
        num = match.group("num")

        # Empty marker → strip it (exit list).
        if not rest.strip():
            cursor.beginEditBlock()
            cursor.movePosition(QTextCursor.StartOfBlock)
            cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            cursor.insertText(indent)
            cursor.insertText("\n")
            cursor.endEditBlock()
            self.setTextCursor(cursor)
            return True

        if bullet is not None:
            # Reset checkbox state to unchecked on continuation.
            new_check = "[ ] " if check else ""
            prefix = f"{indent}{bullet} {new_check}"
        else:
            try:
                next_num = int(num) + 1
            except (TypeError, ValueError):
                return False
            prefix = f"{indent}{next_num}. "

        cursor.beginEditBlock()
        cursor.insertText("\n" + prefix)
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return True
