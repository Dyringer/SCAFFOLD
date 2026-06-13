"""Tests for the synthetic DemoSerialPort.

The line generators are pure (index → string), so they're asserted exactly.
The port itself is timer-driven, so its emit/echo/fault behaviour is exercised
with pytest-qt headless, pumping the event loop where a timer needs to fire.
"""
from __future__ import annotations

import os
import re

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.serial_terminal.demo_port import (
    DEMO_PORT_NAME,
    DemoSerialPort,
    env_line,
    log_line,
    volt_line,
)

# ---------------------------------------------------------------------------
# line generators — pure, deterministic, no timestamp

def test_volt_line_format() -> None:
    assert re.fullmatch(r"volt=[\d.]+", volt_line(0)), volt_line(0)


def test_env_line_format() -> None:
    assert re.fullmatch(r"temp=[\d.]+ hum=[\d.]+", env_line(0)), env_line(0)


def test_lines_are_deterministic() -> None:
    assert volt_line(123) == volt_line(123)
    assert env_line(123) == env_line(123)


def test_volt_is_sawtooth() -> None:
    # volt ramps 3.00→3.98 over 50 samples then wraps.
    v0 = float(volt_line(0).split("=")[1])
    v49 = float(volt_line(49).split("=")[1])
    v50 = float(volt_line(50).split("=")[1])
    assert v0 == pytest.approx(3.0)
    assert v49 > v0
    assert v50 == pytest.approx(3.0)  # wrapped back


def test_default_config_matches_demo_output() -> None:
    # The shipped default plot config MUST match the demo lines — guards against
    # the generators and DEMO_PLOT_CONFIG drifting apart.
    from app.subapps.serial_terminal.demo_port import DEMO_PLOT_CONFIG
    from app.subapps.serial_terminal.plot_parser import (
        MultiSeriesExtractor,
        SeriesSpec,
    )

    specs = [SeriesSpec(f"s{i}", p) for i, p in enumerate(DEMO_PLOT_CONFIG["series"])]
    e = MultiSeriesExtractor(DEMO_PLOT_CONFIG["x"], specs)
    # volt is on its own line; temp+hum on another. Each must yield a point.
    assert len(e.feed_line(volt_line(3), timestamp=1.0).points) == 1
    assert len(e.feed_line(env_line(3), timestamp=1.0).points) == 2


def test_log_line_is_deterministic_and_cycles() -> None:
    assert log_line(0) == log_line(0)
    from app.subapps.serial_terminal.demo_port import _LOG_LINES

    assert log_line(len(_LOG_LINES)) == log_line(0)


def test_log_lines_do_not_match_demo_series() -> None:
    # The whole point of interleaving them: logs are noise the plotter skips.
    from app.subapps.serial_terminal.demo_port import _LOG_LINES, DEMO_PLOT_CONFIG
    from app.subapps.serial_terminal.plot_parser import (
        MultiSeriesExtractor,
        SeriesSpec,
    )

    specs = [SeriesSpec(f"s{i}", p) for i, p in enumerate(DEMO_PLOT_CONFIG["series"])]
    e = MultiSeriesExtractor(DEMO_PLOT_CONFIG["x"], specs)
    for raw in _LOG_LINES:
        assert not e.feed_line(raw, timestamp=0.0).matched


# ---------------------------------------------------------------------------
# DemoSerialPort — lifecycle

@pytest.fixture
def port(qtbot):
    p = DemoSerialPort()
    yield p
    if p.is_open:
        p.close("test teardown")


def test_open_emits_opened_and_sets_state(port, qtbot) -> None:
    opened: list[str] = []
    port.opened.connect(opened.append)
    assert port.open(DEMO_PORT_NAME, 115200) is True
    assert port.is_open
    assert opened == [DEMO_PORT_NAME]


def test_open_ignores_baud(port) -> None:
    # baud is accepted but meaningless; opening must succeed regardless.
    assert port.open(DEMO_PORT_NAME, 9600) is True


def test_emits_telemetry_while_open(port, qtbot) -> None:
    chunks: list[bytes] = []
    port.data_received.connect(chunks.append)
    port.open(DEMO_PORT_NAME, 115200)
    qtbot.wait(200)  # let the emit timer fire several times
    assert len(chunks) >= 2
    blob = b"".join(chunks)
    assert b"volt=" in blob and b"temp=" in blob


def test_stream_interleaves_log_lines(port, qtbot) -> None:
    chunks: list[bytes] = []
    port.data_received.connect(chunks.append)
    port.open(DEMO_PORT_NAME, 115200)
    # Run long enough that several telemetry samples (and thus >= one log every
    # _LOG_EVERY) are emitted.
    qtbot.wait(600)
    blob = b"".join(chunks)
    assert b"volt=" in blob          # telemetry present
    assert b"[INFO]" in blob or b"[WARN]" in blob or b"[ERR]" in blob


def test_plotter_skips_demo_logs_but_plots_telemetry(qtbot) -> None:
    # End-to-end: feed a DemoSerialPort's mixed stream into the real PlotView
    # and confirm logs become "unmatched" while telemetry still plots.
    from app.subapps.serial_terminal.demo_port import DEMO_PLOT_CONFIG
    from app.subapps.serial_terminal.plot_view import PlotView

    view = PlotView(config=DEMO_PLOT_CONFIG)
    qtbot.addWidget(view)
    p = DemoSerialPort()
    p.data_received.connect(view.feed)
    p.open(DEMO_PORT_NAME, 115200)
    qtbot.wait(600)
    view._flush()
    assert len(view._series["temp"].ys) > 3   # telemetry plotted
    assert view._unmatched >= 1                # logs skipped, not plotted
    p.close("done")
    view.stop()


def test_close_stops_emission(port, qtbot) -> None:
    chunks: list[bytes] = []
    port.open(DEMO_PORT_NAME, 115200)
    qtbot.wait(120)
    port.data_received.connect(chunks.append)
    port.close("done")
    qtbot.wait(150)
    assert chunks == []  # nothing emitted after close


def test_write_echoes_back(port, qtbot) -> None:
    echoes: list[bytes] = []
    port.open(DEMO_PORT_NAME, 115200)
    # Silence telemetry so we only capture the echo.
    port.write(b":silent")
    qtbot.wait(50)
    port.data_received.connect(echoes.append)
    n = port.write(b"hello")
    assert n == len(b"hello")
    qtbot.wait(80)  # echo is deferred ~20 ms
    assert b"hello" in b"".join(echoes)


def test_write_returns_zero_when_closed(port) -> None:
    assert port.write(b"x") == 0


# ---------------------------------------------------------------------------
# DemoSerialPort — fault injection

def test_silent_command_stops_telemetry(port, qtbot) -> None:
    port.open(DEMO_PORT_NAME, 115200)
    port.write(b":silent")
    qtbot.wait(50)
    chunks: list[bytes] = []
    port.data_received.connect(chunks.append)
    qtbot.wait(150)
    assert chunks == []  # silent → no telemetry


def test_resume_command_restarts_telemetry(port, qtbot) -> None:
    port.open(DEMO_PORT_NAME, 115200)
    port.write(b":silent")
    qtbot.wait(50)
    port.write(b":resume")
    chunks: list[bytes] = []
    port.data_received.connect(chunks.append)
    qtbot.wait(200)
    assert any(b"volt=" in c for c in chunks)


def test_disconnect_command_emits_error_and_closes(port, qtbot) -> None:
    errors: list[str] = []
    closed: list[str] = []
    port.error.connect(errors.append)
    port.closed.connect(closed.append)
    port.open(DEMO_PORT_NAME, 115200)
    port.write(b":disconnect")
    qtbot.wait(50)  # close is deferred to the next event-loop turn
    assert errors and "disconnect" in errors[0].lower()
    assert not port.is_open
    assert closed
