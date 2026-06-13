"""Tests for SessionLogger — file capture of a serial session.

Pure file I/O (no Qt), so everything runs against a tmp_path with exact byte
assertions. The critical property for RAW mode is byte-fidelity: the file must
equal the concatenated RX bytes so it can be re-fed to the plotter later.
"""
from __future__ import annotations

from pathlib import Path

from app.subapps.serial_terminal.session_logger import LogMode, SessionLogger

# ---------------------------------------------------------------------------
# RAW mode — verbatim RX bytes, replayable

def test_raw_captures_rx_bytes_verbatim(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"temp=25.")
    lg.write("rx", b"3\nhum=40\n")
    lg.stop()
    # Byte-identical to what arrived — exactly re-feedable to the plotter.
    assert p.read_bytes() == b"temp=25.3\nhum=40\n"


def test_raw_ignores_tx(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"abc")
    lg.write("tx", b"SENT")   # must not appear — would corrupt the byte stream
    lg.write("rx", b"def")
    lg.stop()
    assert p.read_bytes() == b"abcdef"


def test_raw_preserves_binary(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    blob = bytes(range(256))
    lg.write("rx", blob)
    lg.stop()
    assert p.read_bytes() == blob   # no newline translation / mangling


# ---------------------------------------------------------------------------
# TRANSCRIPT mode — RX+TX, line-assembled, tagged

def test_transcript_tags_both_directions(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"hello\n")
    lg.write("tx", b"reset\n")
    lg.write("rx", b"world\n")
    lg.stop()
    assert p.read_text() == "RX hello\nTX reset\nRX world\n"


def test_transcript_assembles_partial_lines(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    # A line split across chunks must not get a tag mid-line.
    lg.write("rx", b"temp=")
    lg.write("rx", b"25.3\n")
    lg.stop()
    assert p.read_text() == "RX temp=25.3\n"


def test_transcript_flushes_trailing_partial_on_stop(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"no newline yet")   # never terminated
    lg.stop()
    # stop() must not lose the trailing partial line.
    assert p.read_text() == "RX no newline yet\n"


def test_transcript_strips_cr(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"crlf line\r\n")
    lg.stop()
    assert p.read_text() == "RX crlf line\n"


def test_transcript_directions_do_not_cross_contaminate(tmp_path: Path) -> None:
    # Interleaved partial lines on each direction stay separate.
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"ab")
    lg.write("tx", b"XY")
    lg.write("rx", b"c\n")     # completes "abc"
    lg.write("tx", b"Z\n")     # completes "XYZ"
    lg.stop()
    assert p.read_text() == "RX abc\nTX XYZ\n"


# ---------------------------------------------------------------------------
# lifecycle

def test_write_is_noop_before_start() -> None:
    lg = SessionLogger()
    assert lg.is_logging is False
    lg.write("rx", b"ignored")   # must not raise
    assert lg.bytes_written == 0


def test_stop_is_idempotent(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"x")
    lg.stop()
    lg.stop()   # second stop must be harmless
    assert p.read_bytes() == b"x"


def test_start_replaces_previous_session(tmp_path: Path) -> None:
    a = tmp_path / "a.log.bin"
    b = tmp_path / "b.log.bin"
    lg = SessionLogger()
    lg.start(a, LogMode.RAW)
    lg.write("rx", b"first")
    lg.start(b, LogMode.RAW)   # implicitly stops 'a'
    lg.write("rx", b"second")
    lg.stop()
    assert a.read_bytes() == b"first"
    assert b.read_bytes() == b"second"


def test_bytes_written_tracks_output(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"12345")
    assert lg.bytes_written == 5
    lg.stop()


def test_lines_written_counts_transcript_lines(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"a\nb\n")
    lg.write("tx", b"c\n")
    assert lg.lines_written == 3
    lg.stop()


def test_lines_written_includes_trailing_partial_on_stop(tmp_path: Path) -> None:
    p = tmp_path / "cap.log"
    lg = SessionLogger()
    lg.start(p, LogMode.TRANSCRIPT)
    lg.write("rx", b"a\nb")   # 'b' has no newline yet → 1 line so far
    assert lg.lines_written == 1
    lg.stop()                  # flushes 'b' → 2
    assert lg.lines_written == 2


def test_lines_written_zero_in_raw_mode(tmp_path: Path) -> None:
    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"a\nb\nc\n")
    assert lg.lines_written == 0   # raw has no line concept
    lg.stop()


def test_mode_property_reflects_start(tmp_path: Path) -> None:
    lg = SessionLogger()
    lg.start(tmp_path / "c.log", LogMode.TRANSCRIPT)
    assert lg.mode is LogMode.TRANSCRIPT
    lg.stop()


def test_default_suffix_per_mode() -> None:
    assert LogMode.RAW.default_suffix == ".log.bin"
    assert LogMode.TRANSCRIPT.default_suffix == ".log"


def test_raw_capture_roundtrips_through_plotter(tmp_path: Path) -> None:
    # The whole point of RAW mode: replay the file into the plotter's parser
    # and get the same points back.
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from app.subapps.serial_terminal.plot_parser import (
        LineAssembler,
        MultiSeriesExtractor,
        SeriesSpec,
    )

    p = tmp_path / "cap.log.bin"
    lg = SessionLogger()
    lg.start(p, LogMode.RAW)
    lg.write("rx", b"v=10\nv=20\nv=30\n")
    lg.stop()

    asm = LineAssembler()
    ext = MultiSeriesExtractor("", [SeriesSpec("v", r"v=(\d+)")])
    ys = []
    for i, line in enumerate(asm.feed(p.read_bytes())):
        r = ext.feed_line(line, timestamp=float(i))
        if r.matched:
            ys.append(r.points["v"][1])
    assert ys == [10.0, 20.0, 30.0]
