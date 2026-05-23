from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont, QMouseEvent, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QWidget

from app.core.theme_manager import theme_manager
from .highlighter import palette as md_palette


def _preview_css(dark: bool) -> str:
    c = md_palette(dark)
    if dark:
        code_bg = "#2a2f36"
        quote_bg = "#23262b"
        table_border = "#444"
    else:
        code_bg = "#f3efe6"
        quote_bg = "#f6f3ec"
        table_border = "#bbb"

    return f"""
        h1, h2, h3, h4, h5, h6 {{ color: {c['heading'].name()}; }}
        h1 {{ font-size: 18pt; }}
        h2 {{ font-size: 15pt; }}
        h3 {{ font-size: 13pt; }}
        strong, b {{ color: {c['bold'].name()}; }}
        em, i {{ color: {c['italic'].name()}; }}
        a {{ color: {c['link'].name()}; }}
        code {{
            color: {c['code'].name()};
            background-color: {code_bg};
            font-family: Consolas, "Cascadia Mono", monospace;
        }}
        pre {{
            background-color: {code_bg};
            color: {c['code'].name()};
            font-family: Consolas, "Cascadia Mono", monospace;
        }}
        blockquote {{
            color: {c['quote'].name()};
            background-color: {quote_bg};
            border-left: 3px solid {c['quote'].name()};
            margin-left: 0;
            padding: 4px 10px;
        }}
        hr {{ border: 1px solid {c['hr'].name()}; }}
        li {{ margin: 2px 0; }}
        table {{ border-collapse: collapse; }}
        th, td {{ border: 1px solid {table_border}; padding: 4px 8px; }}
        th {{ background-color: {code_bg}; }}
    """


class MarkdownPreview(QTextBrowser):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setOpenLinks(True)
        self.setReadOnly(True)
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)

    def set_markdown(self, text: str) -> None:
        # QTextDocument.setMarkdown() ignores defaultStyleSheet, so we have to
        # round-trip through HTML: render markdown in a scratch document,
        # extract its HTML, then setHtml() on our document with the stylesheet
        # in place — that path *does* honor CSS.
        scratch = QTextDocument()
        scratch.setMarkdown(text or "*(empty note)*")
        html = scratch.toHtml()
        # Strip Qt's inline style="…" attributes so our defaultStyleSheet
        # actually wins. Qt bakes hard-coded colors/fonts into every tag,
        # which would otherwise mask the CSS.
        html = re.sub(r'\s+style="[^"]*"', "", html)

        dark = theme_manager.current == "dark"
        self.document().setDefaultStyleSheet(_preview_css(dark))
        self.document().setHtml(html)
