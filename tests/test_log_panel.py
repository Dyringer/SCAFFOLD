"""Qt-level tests for the Log tab (LogPanel).

Uses pytest-qt headless. The panel drives a real SessionLogger writing to a
tmp_path; the file dialog is bypassed by setting the chosen path directly (the
dialog itself is Qt-native and not unit-testable).
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.serial_terminal.log_panel import LogPanel, _human_size
from app.subapps.serial_terminal.session_logger import SessionLogger


@pytest.fixture
def panel(qtbot, tmp_path):
    logger = SessionLogger()
    p = LogPanel(logger, tmp_path, "COM_TEST")
    qtbot.addWidget(p)
    yield p, logger, tmp_path
    p.stop()
    logger.stop()


# ---------------------------------------------------------------------------
# _human_size formatter

def test_human_size_units() -> None:
    assert _human_size(0) == "0 B"
    assert _human_size(512) == "512 B"
    assert _human_size(1536) == "1.5 KB"
    assert _human_size(5 * 1024 * 1024) == "5.0 MB"


# ---------------------------------------------------------------------------
# start / stop

def test_cannot_start_without_path(panel) -> None:
    p, logger, _ = panel
    # No path chosen → Start disabled, start is a no-op.
    assert not p._start_btn.isEnabled()
    p._on_start_stop()
    assert not logger.is_logging


def test_start_writes_and_stop_closes(panel) -> None:
    p, logger, tmp_path = panel
    target = tmp_path / "cap.log"
    p._chosen_path = target
    p._mode_combo.setCurrentIndex(1)   # transcript
    p._update_controls()
    p._on_start_stop()                 # start
    assert logger.is_logging
    logger.write("rx", b"hello\n")
    p._on_start_stop()                 # stop
    assert not logger.is_logging
    assert target.read_text() == "RX hello\n"


def test_recording_changed_signal(panel, qtbot) -> None:
    p, _logger, tmp_path = panel
    p._chosen_path = tmp_path / "cap.log.bin"
    p._mode_combo.setCurrentIndex(0)   # raw
    p._update_controls()
    states: list[bool] = []
    p.recording_changed.connect(states.append)
    p._on_start_stop()   # → True
    p._on_start_stop()   # → False
    assert states == [True, False]


def test_controls_lock_while_recording(panel) -> None:
    p, _logger, tmp_path = panel
    p._chosen_path = tmp_path / "cap.log.bin"
    p._update_controls()
    p._on_start_stop()
    # Mode/browse locked during a capture; start button becomes Stop.
    assert not p._mode_combo.isEnabled()
    assert not p._browse_btn.isEnabled()
    assert p._start_btn.text() == "Stop logging"
    p._on_start_stop()
    assert p._mode_combo.isEnabled()
    assert p._start_btn.text() == "Start logging"


def test_stats_refresh_shows_size_and_lines(panel) -> None:
    p, logger, tmp_path = panel
    p._chosen_path = tmp_path / "cap.log"
    p._mode_combo.setCurrentIndex(1)   # transcript
    p._update_controls()
    p._on_start_stop()
    logger.write("rx", b"one\ntwo\n")
    p._refresh_stats()
    # "RX one\n" (7) + "RX two\n" (7) = 14 bytes, 2 lines.
    assert p._bytes_lbl.text() == "14"
    assert p._lines_lbl.text() == "2"
    p._on_start_stop()


def test_stop_if_logging_is_safe_when_idle(panel) -> None:
    p, logger, _tmp = panel
    # Never started — must not raise.
    p.stop_if_logging()
    assert not logger.is_logging
