"""Unit tests for the incremental ANSI→HTML converter.

Pure logic — no QApplication needed (AnsiToHtml has no Qt dependency). The
focus here is the carry-buffer cap that protects the serial console from a
misbehaving device: a segfaulting CDC peer can dump binary that happens to
begin "\\x1b[" followed by a long unterminated run, which the partial-escape
carry would otherwise accumulate forever while rendering nothing (the freeze
this guards against).
"""
from __future__ import annotations

from app.subapps.serial_terminal.ansi import _MAX_CARRY, AnsiToHtml


def _strip_tags(html: str) -> str:
    """Crude tag stripper so tests can assert on rendered text content."""
    out, depth = [], 0
    for ch in html:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def test_plain_text_passes_through() -> None:
    a = AnsiToHtml()
    assert _strip_tags(a.feed("hello world")) == "hello world"


def test_sgr_color_applies_and_persists_across_chunks() -> None:
    a = AnsiToHtml()
    first = a.feed("\x1b[31mred")
    # Color set in one chunk must still apply to text in the next (firmware
    # logs routinely split a color escape from the text it colors).
    second = a.feed("still-red")
    assert "color:#c0392b" in first
    assert "color:#c0392b" in second
    assert _strip_tags(first) == "red"
    assert _strip_tags(second) == "still-red"


def test_legitimate_split_escape_is_carried_not_lost() -> None:
    a = AnsiToHtml()
    # A real SGR split mid-sequence across the read boundary: the first half
    # emits no text and is held; the second half completes it and colors "X".
    out1 = a.feed("before\x1b[3")
    out2 = a.feed("1mX")
    assert _strip_tags(out1) == "before"
    assert "color:#c0392b" in out2
    assert _strip_tags(out2) == "X"


def test_truecolor_sgr_within_cap() -> None:
    # The longest real-world sequence (24-bit color) must fit under the cap so
    # the guard never breaks a legitimate escape.
    seq = "\x1b[38;2;255;255;255m"
    assert len(seq) <= _MAX_CARRY
    a = AnsiToHtml()
    # Split it right before the terminating 'm' to exercise the carry path.
    a.feed(seq[:-1])
    out = a.feed("m" + "text")
    assert _strip_tags(out) == "text"


def test_unterminated_escape_does_not_accumulate_unbounded() -> None:
    """The poison pill: binary that begins '\\x1b[' then never terminates.

    Before the cap this grew the carry without bound and emitted nothing,
    freezing the console. Now an over-long carry is flushed as literal text and
    the converter resyncs, so subsequent normal text still renders.
    """
    a = AnsiToHtml()
    # A run far longer than any real escape: ESC '[' + many digits/semicolons,
    # no final byte in @-~. Feed it in pieces like a streaming device would.
    garbage = "\x1b[" + "1;" * 200
    for i in range(0, len(garbage), 17):
        a.feed(garbage[i : i + 17])
    # The held carry must never exceed the cap, no matter how much arrived.
    assert len(a._carry) <= _MAX_CARRY
    # And the converter must not be wedged: real text after the garbage renders.
    out = a.feed("\x1b[0mrecovered\n")
    assert "recovered" in _strip_tags(out)


def test_recovers_to_normal_after_garbage_then_valid_sequence() -> None:
    a = AnsiToHtml()
    a.feed("\x1b[" + "9" * (_MAX_CARRY * 3))  # well over the cap
    # A clean reset + colored text afterwards must behave normally.
    out = a.feed("\x1b[32mgreen")
    assert "color:#2e9e44" in out
    assert _strip_tags(out).endswith("green")


def test_reset_clears_carry() -> None:
    a = AnsiToHtml()
    a.feed("text\x1b[3")  # leaves a partial escape in carry
    assert a._carry != ""
    a.reset()
    assert a._carry == ""
