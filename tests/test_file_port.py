"""Tests for FileSerialPort — replaying a captured file as a serial source.

Pure-ish (QObject signals, no widgets); uses qtbot only to own the object.
The headline property: a RAW capture replayed through FileSerialPort reproduces
the exact same parsed points, closing the capture→replay loop.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.serial_terminal.file_port import (
    FILE_PORT_NAME,
    FileSerialPort,
)


@pytest.fixture
def port(qtbot):
    p = FileSerialPort()
    yield p
    if p.is_open:
        p.close("teardown")


def _collect(p: FileSerialPort) -> list[bytes]:
    chunks: list[bytes] = []
    p.data_received.connect(chunks.append)
    return chunks


def test_open_emits_file_bytes(port, tmp_path) -> None:
    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"hello\nworld\n")
    chunks = _collect(port)
    port.set_path(f)
    assert port.open(FILE_PORT_NAME, 115200) is True
    assert b"".join(chunks) == b"hello\nworld\n"


def test_stays_open_idle_at_eof(port, tmp_path) -> None:
    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"data\n")
    port.set_path(f)
    port.open(FILE_PORT_NAME, 115200)
    # All bytes emitted, but the port stays open (loaded + idle).
    assert port.is_open


def test_large_file_emitted_in_chunks(port, tmp_path) -> None:
    f = tmp_path / "big.log.bin"
    blob = bytes(200 * 1024)            # > _CHUNK (64 KB)
    f.write_bytes(blob)
    chunks = _collect(port)
    port.set_path(f)
    port.open(FILE_PORT_NAME, 115200)
    # Multiple bounded chunks, reassembling to the original bytes.
    assert len(chunks) >= 3
    assert b"".join(chunks) == blob


def test_open_without_path_fails(port) -> None:
    errors: list[str] = []
    port.error.connect(errors.append)
    assert port.open(FILE_PORT_NAME, 115200) is False
    assert not port.is_open
    assert errors and "no file" in errors[0].lower()


def test_open_missing_file_fails(port, tmp_path) -> None:
    errors: list[str] = []
    port.error.connect(errors.append)
    port.set_path(tmp_path / "does_not_exist.log.bin")
    assert port.open(FILE_PORT_NAME, 115200) is False
    assert not port.is_open
    assert errors


def test_write_is_noop(port, tmp_path) -> None:
    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"x\n")
    port.set_path(f)
    port.open(FILE_PORT_NAME, 115200)
    # A file can't receive — write returns 0 like a closed port.
    assert port.write(b"command\n") == 0


def test_close_emits_closed(port, tmp_path) -> None:
    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"x\n")
    closed: list[str] = []
    port.closed.connect(closed.append)
    port.set_path(f)
    port.open(FILE_PORT_NAME, 115200)
    port.close("done")
    assert not port.is_open
    assert closed == ["done"]


def test_reopen_replaces_previous(port, tmp_path) -> None:
    a = tmp_path / "a.log.bin"
    b = tmp_path / "b.log.bin"
    a.write_bytes(b"aaa\n")
    b.write_bytes(b"bbb\n")
    chunks = _collect(port)
    port.set_path(a)
    port.open(FILE_PORT_NAME, 115200)
    port.set_path(b)
    port.open(FILE_PORT_NAME, 115200)   # reopen → closes a, loads b
    assert b"bbb\n" in b"".join(chunks)


def test_raw_capture_replays_to_same_points(port, tmp_path) -> None:
    # The capture→replay loop: feed FileSerialPort's output through the plot
    # parser and confirm the points match the file's data.
    from app.subapps.serial_terminal.plot_parser import (
        LineAssembler,
        MultiSeriesExtractor,
        SeriesSpec,
    )

    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"v=10\nv=20\nv=30\n")
    chunks = _collect(port)
    port.set_path(f)
    port.open(FILE_PORT_NAME, 115200)

    asm = LineAssembler()
    ext = MultiSeriesExtractor("", [SeriesSpec("v", r"v=(\d+)")])
    ys: list[float] = []
    for i, line in enumerate(asm.feed(b"".join(chunks))):
        r = ext.feed_line(line, timestamp=float(i))
        if r.matched:
            ys.append(r.points["v"][1])
    assert ys == [10.0, 20.0, 30.0]
