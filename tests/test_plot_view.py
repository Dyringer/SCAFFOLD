"""Qt-level tests for the serial PlotView and its session integration.

Needs a real event loop / QApplication (pyqtgraph widgets), so uses pytest-qt
headless via the offscreen platform. The parsing logic is covered in
test_plot_parser.py; here we verify the widget wiring: the series-builder
config → series → coalesced flush → curve data, the bad-regex path, time-based
X, pause, clear, add/remove rows, and that a session routes RX to both views.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.serial_terminal.plot_view import PlotView
from app.subapps.serial_terminal.session import TerminalSession

_VOLT_TEMP_CFG = {
    "x": "",
    "x_label": "time",
    "series": [r"volt=([\d.]+)", r"temp=([\d.]+)"],
}


@pytest.fixture
def view(qtbot):
    v = PlotView()
    qtbot.addWidget(v)
    yield v
    v.stop()


def test_config_creates_series(view) -> None:
    view.set_config(_VOLT_TEMP_CFG)
    assert sorted(view._series) == ["temp", "volt"]


def test_feed_fills_series_from_separate_lines(view) -> None:
    view.set_config(_VOLT_TEMP_CFG)
    # volt and temp arrive on different lines — both must plot.
    view.feed(b"volt=3.20\ntemp=25.3\nvolt=3.22\ntemp=25.4\n")
    view._flush()
    assert list(view._series["volt"].ys) == [3.20, 3.22]
    assert list(view._series["temp"].ys) == [25.3, 25.4]


def test_time_x_is_monotonic_from_zero(view) -> None:
    view.set_config(_VOLT_TEMP_CFG)
    view.feed(b"volt=1\n")
    view.feed(b"volt=2\n")
    view._flush()
    xs = list(view._series["volt"].xs)
    assert xs[0] >= 0.0
    assert xs[0] <= xs[-1]   # time only moves forward


def test_partial_chunk_reassembled(view) -> None:
    view.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    view.feed(b"v=4")
    view._flush()
    assert list(view._series["v"].ys) == []
    view.feed(b"2\n")
    view._flush()
    assert list(view._series["v"].ys) == [42.0]


def test_log_lines_counted_unmatched(view) -> None:
    view.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    view.feed(b"v=1\n[INFO] hello\n[WARN] world\nv=2\n")
    view._flush()
    assert view._unmatched == 2
    assert list(view._series["v"].ys) == [1.0, 2.0]


def test_bad_regex_reported_inline(view) -> None:
    view.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    view.set_config({"x": "", "x_label": "t", "series": [r"(["]})  # invalid
    assert "bad regex" in view._status.text()


def test_pause_stops_buffering(view) -> None:
    view.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    view._on_pause(True)
    view.feed(b"v=9\n")
    view._flush()
    assert list(view._series["v"].ys) == []


def test_clear_drops_points(view) -> None:
    view.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    view.feed(b"v=1\nv=2\n")
    view._flush()
    view.clear()
    assert list(view._series["v"].ys) == []
    assert view._unmatched == 0


def test_add_and_remove_series_rows(view) -> None:
    start = len(view._rows)
    view._add_row(r"x=([\d.]+)")
    assert len(view._rows) == start + 1
    view._remove_row(view._rows[-1])
    assert len(view._rows) == start
    # Removing the last remaining row keeps one (never bare).
    while len(view._rows) > 1:
        view._remove_row(view._rows[-1])
    view._remove_row(view._rows[0])
    assert len(view._rows) == 1


def test_config_roundtrips(view) -> None:
    view.set_config(_VOLT_TEMP_CFG)
    cfg = view.config
    assert cfg["x"] == ""
    assert [s["pattern"] for s in cfg["series"]] == [
        r"volt=([\d.]+)",
        r"temp=([\d.]+)",
    ]


def test_series_label_used_as_legend_name(view) -> None:
    view.set_config(
        {"x": "", "x_label": "t", "series": [{"pattern": r"v=(\d+)", "label": "Battery"}]}
    )
    assert "Battery" in view._series


def test_blank_label_falls_back_to_auto_name(view) -> None:
    view.set_config(
        {"x": "", "x_label": "t", "series": [{"pattern": r"volt=([\d.]+)", "label": ""}]}
    )
    assert "volt" in view._series   # auto-named from the leading key


def test_old_string_series_config_still_loads(view) -> None:
    # Back-compat: a config saved before per-series labels used bare strings.
    view.set_config({"x": "", "x_label": "t", "series": [r"temp=([\d.]+)"]})
    assert "temp" in view._series


def test_samples_window_keeps_last_n(view) -> None:
    view.set_config(
        {
            "x": "",
            "x_label": "t",
            "window": "3",
            "window_unit": "samples",
            "series": [{"pattern": r"v=(\d+)", "label": ""}],
        }
    )
    view.feed(b"v=1\nv=2\nv=3\nv=4\nv=5\n")
    view._flush()
    assert list(view._series["v"].ys) == [3.0, 4.0, 5.0]


def test_seconds_window_drops_old_points(view) -> None:
    # Explicit numeric X so the test is deterministic (no wall-clock).
    view.set_config(
        {
            "x": r"t=(\d+)",
            "x_label": "t",
            "window": "5",
            "window_unit": "seconds",
            "series": [{"pattern": r"v=(\d+)", "label": ""}],
        }
    )
    for i in range(0, 12, 2):
        view.feed(f"t={i} v={i}\n".encode())
    view._flush()
    xs = list(view._series["v"].xs)
    # Newest X is 10; window 5 → nothing older than 5 survives.
    assert xs[0] >= xs[-1] - 5
    assert xs[-1] == 10.0


def test_empty_window_grows_forever(view) -> None:
    view.set_config(
        {
            "x": "",
            "x_label": "t",
            "window": "",
            "series": [{"pattern": r"v=(\d+)", "label": ""}],
        }
    )
    view.feed(b"".join(f"v={i}\n".encode() for i in range(20)))
    view._flush()
    assert len(view._series["v"].ys) == 20


def test_window_persists_in_config(view) -> None:
    view.set_config(
        {
            "x": "",
            "x_label": "t",
            "window": "30",
            "window_unit": "samples",
            "series": [{"pattern": r"v=(\d+)", "label": "V"}],
        }
    )
    cfg = view.config
    assert cfg["window"] == "30"
    assert cfg["window_unit"] == "samples"
    assert cfg["series"] == [{"pattern": r"v=(\d+)", "label": "V"}]


def test_ring_buffer_caps_points(qtbot) -> None:
    v = PlotView(cap=10)
    qtbot.addWidget(v)
    v.set_config({"x": "", "x_label": "t", "series": [r"v=(\d+)"]})
    v.feed(b"".join(f"v={i}\n".encode() for i in range(50)))
    v._flush()
    assert len(v._series["v"].ys) == 10
    assert list(v._series["v"].ys)[-1] == 49.0
    v.stop()


def test_config_changed_signal_emits_json(view, qtbot) -> None:
    import json

    seen: list[str] = []
    view.config_changed.connect(seen.append)
    view.set_config(_VOLT_TEMP_CFG)
    assert seen
    parsed = json.loads(seen[-1])
    assert [s["pattern"] for s in parsed["series"]] == [
        r"volt=([\d.]+)",
        r"temp=([\d.]+)",
    ]


# ---------------------------------------------------------------------------
# Session integration

def test_session_feeds_both_console_and_plot(qtbot) -> None:
    s = TerminalSession("COM_TEST")
    qtbot.addWidget(s)
    s._plot.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    s._on_data_received(b"v=11\nv=22\n")
    s._plot._flush()
    s._flush_pending()
    assert list(s._plot._series["v"].ys) == [11.0, 22.0]
    assert "v=22" in s._console.toPlainText()
    s.close_port()


def test_session_has_console_plot_log_tabs(qtbot) -> None:
    s = TerminalSession("COM_TEST")
    qtbot.addWidget(s)
    tabs = [s._tabs.tabText(i) for i in range(s._tabs.count())]
    assert tabs == ["Console", "Plot", "Log"]
    s.close_port()


def test_file_session_loads_into_console_and_plot(qtbot, tmp_path) -> None:
    from app.subapps.serial_terminal.file_port import FileSerialPort

    f = tmp_path / "cap.log.bin"
    f.write_bytes(b"v=5\nv=6\n")
    s = TerminalSession("FILE")
    qtbot.addWidget(s)
    assert isinstance(s._serial, FileSerialPort)   # factory routed FILE
    s._plot.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    s.set_source_path(str(f))   # also clears prior data
    s.connect()
    s._plot._flush()
    s._flush_pending()
    assert list(s._plot._series["v"].ys) == [5.0, 6.0]
    assert "v=6" in s._console.toPlainText()
    assert s.is_open   # stays idle-open at EOF
    s.close_port()


def test_set_source_path_clears_previous(qtbot, tmp_path) -> None:
    from app.subapps.serial_terminal.file_port import FileSerialPort

    f1 = tmp_path / "a.log.bin"
    f1.write_bytes(b"v=1\n")
    f2 = tmp_path / "b.log.bin"
    f2.write_bytes(b"v=9\n")
    s = TerminalSession("FILE")
    qtbot.addWidget(s)
    assert isinstance(s._serial, FileSerialPort)
    s._plot.set_config({"x": "", "x_label": "t", "series": [r"v=([\d.]+)"]})
    s.set_source_path(str(f1))
    s.connect()
    s._plot._flush()
    # Load a different file — prior console/plot data must be cleared first.
    s.set_source_path(str(f2))
    s.connect()
    s._plot._flush()
    s._flush_pending()
    assert list(s._plot._series["v"].ys) == [9.0]   # not [1.0, 9.0]
    s.close_port()
