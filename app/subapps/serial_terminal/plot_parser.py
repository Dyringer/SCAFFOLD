"""Pure parsing layer for the serial plotter — no Qt, no pyqtgraph.

Two stages sit between the raw RX byte stream and the plot:

  bytes ──▶ LineAssembler ──▶ complete text lines ──▶ MultiSeriesExtractor ──▶ points

Kept Qt-free so the whole extraction path is unit-testable without an event
loop or a real port, matching how the rest of this codebase separates logic
from widgets.

The series model is a *builder*, not one mega-regex: each Y series is its own
small regex whose first capture group is the value, and X is its own regex too
(or, when X is left empty, a timestamp the caller supplies). Each series regex
is matched against every line independently, so data split across multiple
lines — `volt=3.2` on one line, `temp=25 hum=40` on the next — just works:
each series picks up its own lines.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.subapps.serial_terminal.ansi import decode_serial

# A line with no newline in sight can't grow our hold-back buffer forever: a
# device dumping binary or a runaway log with no '\n' would otherwise pin
# unbounded memory (the same failure class as the ANSI carry poison-pill in
# ansi.py). Past this, we force-flush what we have as one "line" and move on.
_MAX_LINE = 64 * 1024


class LineAssembler:
    """Reassembles complete text lines from arbitrary RX byte chunks.

    UART hands us bytes with no respect for line boundaries — `temp=25.` in one
    chunk, `3\\n` in the next. The regex must see whole lines, so we split on
    '\\n' and hold any trailing partial until the next chunk completes it.
    """

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, data: bytes) -> list[str]:
        """Consume a chunk; return the complete lines it completed (no newline).

        Decoding is lenient (replace) so a corrupt byte never raises — the
        plotter must survive the same garbage the console does.
        """
        self._buf += decode_serial(data)

        # Runaway with no newline: emit what we have so memory stays bounded.
        if len(self._buf) >= _MAX_LINE:
            line, self._buf = self._buf, ""
            return [line]

        if "\n" not in self._buf:
            return []

        *complete, tail = self._buf.split("\n")
        self._buf = tail
        # Strip a trailing '\r' so CRLF streams don't leave it on every line.
        return [ln[:-1] if ln.endswith("\r") else ln for ln in complete]

    def reset(self) -> None:
        self._buf = ""


@dataclass(frozen=True)
class SeriesSpec:
    """One Y series: a display name and a regex whose first capture group
    (or whole match, if the regex has no group) is the numeric value."""

    name: str
    pattern: str


@dataclass
class ParseResult:
    """One line's worth of extracted data.

    `points` maps series name → (x, y). Empty when no series matched the line
    (the caller treats an empty result as "unmatched" for its counter).
    `x_from_line` is True when X came from the X-regex on this line rather than
    the caller's timestamp — purely informational.
    """

    points: dict[str, tuple[float, float]] = field(default_factory=dict)
    matched: bool = False
    x_from_line: bool = False


def _first_value(m: re.Match) -> float | None:
    """The numeric value of a match: group 1 if the regex has a group, else the
    whole match. None if it isn't a parseable float."""
    raw = m.group(1) if m.re.groups >= 1 else m.group(0)
    try:
        return float(raw)
    except (ValueError, TypeError):
        return None


class MultiSeriesExtractor:
    """Extracts points from lines using one regex per series plus an X regex.

    * `x_pattern`: regex whose first group is the X value. If it matches a
      line, that X applies to every series value found on the SAME line. If
      empty (""), X is the timestamp the caller passes to `feed_line` — this is
      how time-based X works for data with no in-band timestamp.
    * `specs`: the Y series. Each spec's regex is searched on every line; a
      match contributes one point to that series.

    A single line can satisfy several series (e.g. "temp=25 hum=40") or just
    one; series on different lines are stitched together on the shared X.
    """

    def __init__(self, x_pattern: str, specs: list[SeriesSpec]) -> None:
        # Compile eagerly so a bad pattern raises at config time (the view
        # catches re.error and shows which field is wrong) rather than silently
        # dropping every line at runtime.
        self._x_re = re.compile(x_pattern) if x_pattern else None
        self._specs = list(specs)
        self._compiled = [(s.name, re.compile(s.pattern)) for s in specs]

    @property
    def series_names(self) -> list[str]:
        return [s.name for s in self._specs]

    @property
    def uses_time_x(self) -> bool:
        return self._x_re is None

    def feed_line(self, line: str, timestamp: float = 0.0) -> ParseResult:
        """Extract points from one line.

        `timestamp` is used as X only when no X regex is configured (time-based
        X); otherwise X comes from the X regex matched on this line. A line that
        has series values but no resolvable X is dropped (can't place points).
        """
        # Resolve X for this line.
        x_from_line = False
        if self._x_re is not None:
            xm = self._x_re.search(line)
            if xm is None:
                x = None
            else:
                x = _first_value(xm)
                x_from_line = True
        else:
            x = timestamp

        points: dict[str, tuple[float, float]] = {}
        for name, rx in self._compiled:
            m = rx.search(line)
            if m is None:
                continue
            y = _first_value(m)
            if y is not None and x is not None:
                points[name] = (x, y)

        if points:
            return ParseResult(points=points, matched=True, x_from_line=x_from_line)
        return ParseResult()

    def reset(self) -> None:
        # Stateless across lines (X is per-line or caller-supplied), so nothing
        # to reset — kept for interface parity with the view's expectations.
        pass
