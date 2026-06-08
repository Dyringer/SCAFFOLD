from __future__ import annotations

import re

# Standard 16 ANSI colors → hex. Index 0-7 normal, 8-15 bright.
# Tuned to read well on both the light and dark app themes.
_FG = {
    30: "#1c1c1c", 31: "#c0392b", 32: "#2e9e44", 33: "#b8860b",
    34: "#2f6fd0", 35: "#9b59b6", 36: "#1f9ec4", 37: "#c8c8c8",
    90: "#7f7f7f", 91: "#e74c3c", 92: "#3ecc5f", 93: "#e0b020",
    94: "#5b9bf0", 95: "#c77dde", 96: "#48c7e8", 97: "#ffffff",
}
_BG = {
    40: "#1c1c1c", 41: "#c0392b", 42: "#2e9e44", 43: "#b8860b",
    44: "#2f6fd0", 45: "#9b59b6", 46: "#1f9ec4", 47: "#c8c8c8",
    100: "#7f7f7f", 101: "#e74c3c", 102: "#3ecc5f", 103: "#e0b020",
    104: "#5b9bf0", 105: "#c77dde", 106: "#48c7e8", 107: "#ffffff",
}

# Matches a complete CSI ... m (SGR) sequence, or any other complete
# CSI/escape sequence (which we strip). Does NOT match a trailing partial
# escape — that is detected separately so it can be carried to the next chunk.
_SGR_RE = re.compile(r"\x1b\[([0-9;]*)m")
_ANY_ESC_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
# A partial escape at the very end of the buffer (incomplete, keep for later).
_PARTIAL_ESC_RE = re.compile(r"\x1b(?:\[[0-9;?]*[ -/]*)?$")

# A real CSI escape's parameter/intermediate run is short (the longest in
# practice is a truecolor SGR, "\x1b[38;2;255;255;255m" ≈ 19 chars). A device
# that segfaults often dumps binary that happens to begin "\x1b[" followed by a
# long unterminated run of digits/semicolons — which _PARTIAL_ESC_RE would
# otherwise carry forward forever, growing without bound and emitting nothing.
# Past this cap we treat the carry as garbage, not a split escape: flush it as
# literal text and resync. Generous so no legitimate sequence is ever broken.
_MAX_CARRY = 64


def _esc_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


class AnsiToHtml:
    """Incremental ANSI-SGR → HTML converter.

    State (current fg/bg/bold) carries across calls because firmware logs
    set a color with one escape and emit text in later writes. A trailing
    partial escape sequence (split across a read boundary) is buffered and
    prepended to the next chunk so colors are never corrupted.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._fg: str | None = None
        self._bg: str | None = None
        self._bold = False
        self._carry = ""  # partial escape held from the previous chunk

    def _style(self) -> str:
        parts: list[str] = []
        if self._fg:
            parts.append(f"color:{self._fg}")
        if self._bg:
            parts.append(f"background-color:{self._bg}")
        if self._bold:
            parts.append("font-weight:bold")
        return ";".join(parts)

    def _wrap(self, text: str) -> str:
        if not text:
            return ""
        html = _esc_html(text).replace("\n", "<br>")
        style = self._style()
        if style:
            return f'<span style="{style}">{html}</span>'
        return html

    def _apply_sgr(self, codes: str) -> None:
        nums = [int(p) if p else 0 for p in codes.split(";")] if codes else [0]
        for n in nums:
            if n == 0:
                self._fg = self._bg = None
                self._bold = False
            elif n == 1:
                self._bold = True
            elif n == 22:
                self._bold = False
            elif n == 39:
                self._fg = None
            elif n == 49:
                self._bg = None
            elif n in _FG:
                self._fg = _FG[n]
            elif n in _BG:
                self._bg = _BG[n]

    def feed(self, text: str) -> str:
        """Consume a chunk of (decoded) text, return an HTML fragment."""
        text = self._carry + text
        self._carry = ""

        # Hold back a trailing partial escape for the next call — but only if
        # it's short enough to plausibly be a real split sequence. A carry that
        # has already grown past _MAX_CARRY is garbage from a misbehaving device
        # (binary that began "\x1b["), not an escape waiting to complete; let it
        # fall through and render as literal text so the console never wedges.
        m = _PARTIAL_ESC_RE.search(text)
        if m and (len(text) - m.start()) <= _MAX_CARRY:
            self._carry = text[m.start():]
            text = text[: m.start()]

        out: list[str] = []
        pos = 0
        for sgr in _SGR_RE.finditer(text):
            out.append(self._wrap(text[pos:sgr.start()]))
            self._apply_sgr(sgr.group(1))
            pos = sgr.end()
        tail = text[pos:]
        # Strip any other (non-SGR) complete escape sequences from the tail.
        tail = _ANY_ESC_RE.sub("", tail)
        out.append(self._wrap(tail))
        return "".join(out)
