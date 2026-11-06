from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import (
    QColor,
    QFont,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextDocument,
)

from app.core.theme_manager import theme_manager
from app.ui.palette import palette as ui_palette

_MONO = ["Consolas", "Cascadia Mono", "monospace"]

# Markdown role -> modern palette token (see app/ui/palette.py).
_ROLES = {
    "heading": "accent",
    "bold":    "strong",
    "italic":  "console_fg",
    "code":    "console_fg",
    "fence":   "muted",
    "link":    "accent",
    "quote":   "muted",
    "list":    "accent",
    "hr":      "muted",
    "tag":     "accent",
    "tag_bg":  "accent_soft",
}


def palette(dark: bool) -> dict[str, QColor]:
    """Markdown role colours for the dark or light theme, from the modern palette."""
    tokens = ui_palette("dark" if dark else "light")
    return {role: QColor(tokens[token]) for role, token in _ROLES.items()}


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []
        self._fence_format = QTextCharFormat()
        self._fence_marker_format = QTextCharFormat()
        self._build_rules()
        theme_manager.theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, _name: str) -> None:
        self._build_rules()
        self.rehighlight()

    def _build_rules(self) -> None:
        dark = theme_manager.current == "dark"
        c = palette(dark)
        rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

        # Headings (#, ##, ###...)
        for level in range(1, 7):
            fmt = QTextCharFormat()
            fmt.setForeground(c["heading"])
            fmt.setFontWeight(QFont.Bold)
            size_bump = max(0, 6 - level)
            if size_bump:
                fmt.setFontPointSize(10 + size_bump)
            rules.append((QRegularExpression(rf"^{'#' * level} .*$"), fmt))

        bold = QTextCharFormat()
        bold.setForeground(c["bold"])
        bold.setFontWeight(QFont.Bold)
        rules.append((QRegularExpression(r"\*\*[^*\n]+\*\*"), bold))
        rules.append((QRegularExpression(r"__[^_\n]+__"), bold))

        italic = QTextCharFormat()
        italic.setForeground(c["italic"])
        italic.setFontItalic(True)
        rules.append((QRegularExpression(r"(?<![*\w])\*[^*\n]+\*(?![*\w])"), italic))
        rules.append((QRegularExpression(r"(?<![_\w])_[^_\n]+_(?![_\w])"), italic))

        code = QTextCharFormat()
        code.setForeground(c["code"])
        code.setFontFamilies(_MONO)
        rules.append((QRegularExpression(r"`[^`\n]+`"), code))

        link = QTextCharFormat()
        link.setForeground(c["link"])
        link.setFontUnderline(True)
        rules.append((QRegularExpression(r"\[[^\]\n]+\]\([^)\n]+\)"), link))
        rules.append((QRegularExpression(r"https?://\S+"), link))

        quote = QTextCharFormat()
        quote.setForeground(c["quote"])
        quote.setFontItalic(True)
        rules.append((QRegularExpression(r"^> .*$"), quote))

        lst = QTextCharFormat()
        lst.setForeground(c["list"])
        lst.setFontWeight(QFont.Bold)
        rules.append((QRegularExpression(r"^\s*[-*+] "), lst))
        rules.append((QRegularExpression(r"^\s*\d+\. "), lst))

        hr = QTextCharFormat()
        hr.setForeground(c["hr"])
        rules.append((QRegularExpression(r"^(\s*([-*_])\s*){3,}$"), hr))

        tag = QTextCharFormat()
        tag.setForeground(c["tag"])
        tag.setBackground(c["tag_bg"])
        tag.setFontWeight(QFont.DemiBold)
        rules.append((QRegularExpression(r"(?<![\w/&])#[A-Za-z][\w\-]*"), tag))

        self._rules = rules

        self._fence_format = QTextCharFormat()
        self._fence_format.setForeground(c["code"])
        self._fence_format.setFontFamilies(_MONO)
        self._fence_marker_format = QTextCharFormat(self._fence_format)
        self._fence_marker_format.setForeground(c["fence"])

    def highlightBlock(self, text: str) -> None:  # noqa: N802 (Qt override)
        # Fenced code blocks tracked via block state (0 = normal, 1 = in fence)
        prev_state = self.previousBlockState()
        in_fence = prev_state == 1
        if re.match(r"^```", text):
            self.setFormat(0, len(text), self._fence_marker_format)
            self.setCurrentBlockState(0 if in_fence else 1)
            return
        if in_fence:
            self.setFormat(0, len(text), self._fence_format)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)

        for pattern, fmt in self._rules:
            it = pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(m.capturedStart(), m.capturedLength(), fmt)
