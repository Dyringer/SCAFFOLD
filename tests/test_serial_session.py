"""Qt-level tests for TerminalSession's anti-freeze RX handling.

These need a real event loop (the protections are timer-driven), so they use
pytest-qt's qtbot. Run headless via the offscreen platform — set by the
module-level fixture so the suite needs no display.

What's under test is the coalescing contract from the freeze fix: a burst of
RX chunks arriving within one event-loop turn (what a flooding/garbage device
produces) must NOT render per-chunk on the GUI thread — it must render once,
on the next flush tick. That bound on per-frame work is what keeps the window
responsive under a flood.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.serial_terminal.session import _FLUSH_INTERVAL, TerminalSession


@pytest.fixture
def session(qtbot):
    s = TerminalSession("COM_TEST")
    qtbot.addWidget(s)
    return s


def test_burst_is_coalesced_into_one_flush(session, qtbot, monkeypatch) -> None:
    flushes = {"n": 0}
    real_flush = session._flush_pending

    def counting_flush() -> None:
        flushes["n"] += 1
        real_flush()

    monkeypatch.setattr(session, "_flush_pending", counting_flush)
    # The timer was connected to the original bound method in __init__; re-point
    # it at our counter so the scheduled flush goes through the spy.
    session._flush_timer.timeout.disconnect()
    session._flush_timer.timeout.connect(counting_flush)

    # Simulate a flood: 500 chunks delivered synchronously (one event-loop turn).
    for i in range(500):
        session._on_data_received(f"line{i}\n".encode())

    # Nothing should have rendered yet — the whole burst is queued, GUI free.
    assert flushes["n"] == 0
    assert session._console.toPlainText() == ""
    assert len(session._pending) == 500

    # One flush tick drains the entire burst in a single render.
    qtbot.wait(_FLUSH_INTERVAL * 3)
    assert flushes["n"] == 1
    assert session._pending == []
    text = session._console.toPlainText()
    assert "line0" in text
    assert "line499" in text


def test_clear_console_drops_queued_flush(session, qtbot) -> None:
    session._on_data_received(b"queued-but-not-flushed")
    assert len(session._pending) == 1
    # Clearing must cancel the pending flush so it can't repopulate the console.
    session.clear_console()
    assert session._pending == []
    assert not session._flush_timer.isActive()
    qtbot.wait(_FLUSH_INTERVAL * 3)
    assert session._console.toPlainText() == ""


def test_paused_does_not_queue_flush(session) -> None:
    session._on_pause_toggled(True)
    session._on_data_received(b"while paused")
    # Paused: bytes go to the ring buffer (source of truth) but never queue a
    # render, so no flush is scheduled.
    assert session._pending == []
    assert not session._flush_timer.isActive()
    # The buffer still has it, so resume re-renders it.
    assert any(data == b"while paused" for _d, data in session._buffer)
