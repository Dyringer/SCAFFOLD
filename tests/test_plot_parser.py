"""Unit tests for the serial-plotter parsing layer (pure, no Qt).

Covers LineAssembler (chunk reassembly) and the series-builder extractor
(MultiSeriesExtractor): one regex per series, per-line X, and the time-based X
that kicks in when no X regex is configured.
"""
from __future__ import annotations

import re

import pytest

from app.subapps.serial_terminal.plot_parser import (
    LineAssembler,
    MultiSeriesExtractor,
    SeriesSpec,
)

# ---------------------------------------------------------------------------
# LineAssembler

def test_assembler_splits_on_newline() -> None:
    a = LineAssembler()
    assert a.feed(b"a\nb\nc\n") == ["a", "b", "c"]


def test_assembler_holds_partial_line_across_chunks() -> None:
    a = LineAssembler()
    assert a.feed(b"temp=25.") == []
    assert a.feed(b"3\n") == ["temp=25.3"]


def test_assembler_strips_crlf() -> None:
    a = LineAssembler()
    assert a.feed(b"a\r\nb\r\n") == ["a", "b"]


def test_assembler_lenient_on_bad_bytes() -> None:
    a = LineAssembler()
    out = a.feed(b"\xff\xfe\n")
    assert len(out) == 1


def test_assembler_caps_runaway_line_without_newline() -> None:
    a = LineAssembler()
    out = a.feed(b"x" * (70 * 1024))
    assert out and len(out) == 1
    assert a.feed(b"next\n") == ["next"]


# ---------------------------------------------------------------------------
# MultiSeriesExtractor — construction / discovery

def _spec(name: str, pat: str) -> SeriesSpec:
    return SeriesSpec(name=name, pattern=pat)


def test_series_names_in_order() -> None:
    e = MultiSeriesExtractor(
        "", [_spec("volt", r"volt=([\d.]+)"), _spec("temp", r"temp=([\d.]+)")]
    )
    assert e.series_names == ["volt", "temp"]


def test_empty_x_pattern_uses_time() -> None:
    e = MultiSeriesExtractor("", [_spec("v", r"v=([\d.]+)")])
    assert e.uses_time_x is True


def test_x_pattern_means_not_time() -> None:
    e = MultiSeriesExtractor(r"t=(\d+)", [_spec("v", r"v=([\d.]+)")])
    assert e.uses_time_x is False


def test_bad_series_regex_raises() -> None:
    with pytest.raises(re.error):
        MultiSeriesExtractor("", [_spec("bad", r"([")])


def test_bad_x_regex_raises() -> None:
    with pytest.raises(re.error):
        MultiSeriesExtractor(r"t=([", [_spec("v", r"v=([\d.]+)")])


# ---------------------------------------------------------------------------
# MultiSeriesExtractor — time-based X (no X regex)

def test_time_x_uses_supplied_timestamp() -> None:
    e = MultiSeriesExtractor("", [_spec("v", r"v=([\d.]+)")])
    r = e.feed_line("v=12.5", timestamp=3.5)
    assert r.matched
    assert r.points["v"] == (3.5, 12.5)
    assert r.x_from_line is False


def test_time_x_multiline_series_share_the_timestamp() -> None:
    # volt on one line, temp on another, same timestamp → aligned on X.
    e = MultiSeriesExtractor(
        "", [_spec("volt", r"volt=([\d.]+)"), _spec("temp", r"temp=([\d.]+)")]
    )
    r1 = e.feed_line("volt=3.20", timestamp=1.0)
    r2 = e.feed_line("temp=25.3", timestamp=1.0)
    assert r1.points == {"volt": (1.0, 3.20)}
    assert r2.points == {"temp": (1.0, 25.3)}


# ---------------------------------------------------------------------------
# MultiSeriesExtractor — regex-based X

def test_regex_x_taken_from_same_line() -> None:
    e = MultiSeriesExtractor(r"t=(\d+)", [_spec("v", r"v=([\d.]+)")])
    r = e.feed_line("t=100 v=7.5")
    assert r.matched
    assert r.points["v"] == (100.0, 7.5)
    assert r.x_from_line is True


def test_regex_x_missing_drops_line() -> None:
    # Series value present but no X on the line → can't place it.
    e = MultiSeriesExtractor(r"t=(\d+)", [_spec("v", r"v=([\d.]+)")])
    r = e.feed_line("v=7.5")     # no t=
    assert not r.matched
    assert r.points == {}


# ---------------------------------------------------------------------------
# MultiSeriesExtractor — value extraction

def test_two_series_one_line() -> None:
    e = MultiSeriesExtractor(
        "", [_spec("temp", r"temp=([\d.]+)"), _spec("hum", r"hum=([\d.]+)")]
    )
    r = e.feed_line("temp=25.3 hum=40", timestamp=2.0)
    assert r.points == {"temp": (2.0, 25.3), "hum": (2.0, 40.0)}


def test_partial_line_plots_only_present_series() -> None:
    e = MultiSeriesExtractor(
        "", [_spec("temp", r"temp=([\d.]+)"), _spec("hum", r"hum=([\d.]+)")]
    )
    r = e.feed_line("temp=22.1", timestamp=0.0)
    assert r.points == {"temp": (0.0, 22.1)}


def test_non_matching_line_is_unmatched() -> None:
    e = MultiSeriesExtractor("", [_spec("v", r"v=([\d.]+)")])
    r = e.feed_line("[INFO] some log line", timestamp=0.0)
    assert not r.matched
    assert r.points == {}


def test_regex_without_group_uses_whole_match() -> None:
    # A pattern with no capture group falls back to the whole match as value.
    e = MultiSeriesExtractor("", [_spec("n", r"-?\d+\.\d+")])
    r = e.feed_line("reading 3.14 done", timestamp=0.0)
    assert r.points["n"] == (0.0, 3.14)


def test_non_numeric_capture_is_skipped() -> None:
    e = MultiSeriesExtractor("", [_spec("x", r"x=(\w+)")])
    r = e.feed_line("x=hello", timestamp=0.0)
    assert not r.matched   # 'hello' isn't a float


def test_negative_and_float_values() -> None:
    e = MultiSeriesExtractor(r"t=(-?\d+)", [_spec("v", r"v=(-?[\d.]+)")])
    r = e.feed_line("t=-5 v=-12.75")
    assert r.points["v"] == (-5.0, -12.75)
