from __future__ import annotations

import re

from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtWidgets import QTextBrowser, QWidget

from app.core.theme_manager import theme_manager
from app.ui.palette import palette as ui_palette

from .models import _TAG_RE

_MONO = 'Consolas, "Cascadia Mono", monospace'


def _preview_css(dark: bool) -> str:
    c = ui_palette("dark" if dark else "light")
    return f"""
        h1, h2, h3, h4, h5, h6 {{ color: {c['strong']}; }}
        h1 {{ font-size: 18pt; }}
        h2 {{ font-size: 15pt; }}
        h3 {{ font-size: 13pt; }}
        b {{ color: {c['strong']}; font-weight: 700; }}
        i {{ font-style: italic; }}
        a {{ color: {c['accent']}; }}
        code {{
            color: {c['console_fg']};
            background-color: {c['console_bg']};
            font-family: {_MONO};
        }}
        pre {{
            background-color: {c['console_bg']};
            color: {c['console_fg']};
            font-family: {_MONO};
            margin-top: 0px;
            margin-bottom: 0px;
        }}
        p.quote {{
            color: {c['muted']};
            font-style: italic;
            margin-left: 14px;
        }}
        span.tag {{
            color: {c['accent']};
            background-color: {c['accent_soft']};
            font-weight: 600;
        }}
        hr {{ border: 1px solid {c['border']}; }}
        li {{ margin: 2px 0; }}
        table {{ border-collapse: collapse; }}
        th, td {{ border: 1px solid {c['border2']}; padding: 4px 8px; }}
        th {{ background-color: {c['row']}; }}
    """


# Qt's markdown -> HTML bakes formatting into inline style="…" attributes,
# including hard-coded colours that would mask our stylesheet. Translate the
# formatting into semantic tags/classes first, then strip every style attr.
_SPAN_RE = re.compile(r'<span style="([^"]*)">(.*?)</span>', re.S)
_QUOTE_P_RE = re.compile(r'<p style="[^"]*margin-left:\s*[1-9]\d*px[^"]*">')
_STYLE_ATTR_RE = re.compile(r'\s+style="[^"]*"')
_HTML_TOKEN_RE = re.compile(r"(<[^>]+>)")
_NO_TAG_ELEMENTS = ("pre", "code", "a", "style", "head")


def _span_to_tags(m: re.Match) -> str:
    style = m.group(1).replace(" ", "").lower()
    tags = []
    weight = re.search(r"font-weight:(\d+)", style)
    if weight and int(weight.group(1)) >= 600:
        tags.append("b")
    if "font-style:italic" in style:
        tags.append("i")
    if "line-through" in style:
        tags.append("s")
    if re.search(r"font-family:[^;]*(courier|mono|consolas)", style):
        tags.append("code")
    inner = m.group(2)
    return "".join(f"<{t}>" for t in tags) + inner + "".join(f"</{t}>" for t in reversed(tags))


def _wrap_tags(html: str) -> str:
    """Wrap #tags in body text (not code, links or <head>) in span.tag."""
    out: list[str] = []
    depth = 0
    for part in _HTML_TOKEN_RE.split(html):
        if part.startswith("<"):
            name = re.match(r"</?\s*([a-zA-Z0-9]+)", part)
            if name and name.group(1).lower() in _NO_TAG_ELEMENTS and not part.endswith("/>"):
                depth += -1 if part.startswith("</") else 1
            out.append(part)
        elif depth <= 0 and "#" in part:
            out.append(_TAG_RE.sub(r'<span class="tag">#\1</span>', part))
        else:
            out.append(part)
    return "".join(out)


def markdown_to_html(text: str) -> str:
    scratch = QTextDocument()
    scratch.setMarkdown(text or "*(empty note)*")
    html = scratch.toHtml()
    html = _QUOTE_P_RE.sub('<p class="quote">', html)
    html = _SPAN_RE.sub(_span_to_tags, html)
    html = _STYLE_ATTR_RE.sub("", html)
    return _wrap_tags(html)


class MarkdownPreview(QTextBrowser):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SpPreview")
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
        dark = theme_manager.current == "dark"
        self.document().setDefaultStyleSheet(_preview_css(dark))
        self.document().setHtml(markdown_to_html(text))
