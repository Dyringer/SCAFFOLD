"""Live serial plotter view — pyqtgraph fronted by the pure parsing layer.

Taps the same RX byte stream the console consumes (via `feed`) and plots it in
real time. The series are built in a small panel: an X-axis regex (left empty
to use elapsed time) and one regex per Y series, addable/removable on the fly.
Each series regex's first capture group is its value; series whose data arrives
on different lines are stitched onto the shared X.

Performance contract (the lesson from the console hardening, applied again):
incoming data NEVER triggers a redraw directly. `feed` only appends to bounded
ring buffers; a timer repaints at a fixed frame rate. So a device flooding at
full line-rate can't starve the GUI thread — render cost is bounded by frame
rate, not by how fast the device talks.
"""
from __future__ import annotations

import json
import re
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.subapps.serial_terminal.plot_parser import (
    LineAssembler,
    MultiSeriesExtractor,
    SeriesSpec,
)

# Redraw cadence — same ~30 fps target as the console flush. Visually live,
# but decouples paint rate from the device's output rate.
_REDRAW_MS = 33

# Points retained per series (ring buffer). Bounds memory and keeps setData
# fast no matter how long a capture runs; old points scroll off the left.
_DEFAULT_CAP = 50_000

# Flat pastel series colors, consistent with the app's overall look. Local to
# this subapp so the serial terminal stays independent of the games palette.
_SERIES_COLORS = [
    (74, 144, 217),    # blue
    (46, 158, 68),     # green
    (224, 176, 32),    # amber
    (200, 70, 80),     # red
    (155, 89, 182),    # purple
    (31, 158, 196),    # teal
    (210, 110, 150),   # rose
]


class _Series:
    """One plotted curve plus its bounded backing data."""

    def __init__(self, name: str, curve: pg.PlotDataItem, cap: int) -> None:
        self.name = name
        self.curve = curve
        self.xs: deque[float] = deque(maxlen=cap)
        self.ys: deque[float] = deque(maxlen=cap)

    def append(self, x: float, y: float) -> None:
        self.xs.append(x)
        self.ys.append(y)

    def clear(self) -> None:
        self.xs.clear()
        self.ys.clear()


class _SeriesRow(QWidget):
    """One editable Y series: its regex, an optional display label, and a
    remove button. The label (if given) is what shows in the legend; blank
    falls back to an auto-derived name."""

    def __init__(self, pattern: str, label: str, on_remove, on_apply) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self.edit = QLineEdit(pattern)
        self.edit.setPlaceholderText(r"regex, e.g.  temp=([\d.]+)")
        self.edit.returnPressed.connect(on_apply)
        row.addWidget(self.edit, 1)
        self.label_edit = QLineEdit(label)
        self.label_edit.setPlaceholderText("label (optional)")
        self.label_edit.setMaximumWidth(120)
        self.label_edit.setToolTip(
            "Legend name for this series. Leave blank to auto-name it from the "
            "regex (e.g. a leading 'temp=' → 'temp')."
        )
        self.label_edit.returnPressed.connect(on_apply)
        row.addWidget(self.label_edit)
        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(28)
        remove_btn.setToolTip("Remove this series")
        remove_btn.clicked.connect(lambda: on_remove(self))
        row.addWidget(remove_btn)

    def pattern(self) -> str:
        return self.edit.text().strip()

    def label(self) -> str:
        return self.label_edit.text().strip()


class PlotView(QWidget):
    """Series-builder live plot of the serial RX stream.

    Public surface:
      * feed(bytes)        — push RX data (called from the session)
      * clear()            — drop all points
      * config / set_config(dict) — the X + Y regex set (for persistence)
      * config_changed     — Signal(str) emitting the JSON config on apply
    """

    config_changed = Signal(str)

    def __init__(
        self,
        config: dict | None = None,
        cap: int = _DEFAULT_CAP,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cap = cap
        self._assembler = LineAssembler()
        self._extractor: MultiSeriesExtractor | None = None
        self._series: dict[str, _Series] = {}
        self._unmatched = 0
        self._paused = False
        self._dirty = False
        self._t0: float | None = None   # plot-start time for elapsed-time X
        # Display window: keep only the tail. None = grow forever. When
        # _window_seconds is True the value is X-units to retain; otherwise it's
        # a max sample count per series.
        self._window: float | None = None
        self._window_seconds = True

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        root.addLayout(self._build_panel())

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.15)
        self._plot.addLegend()
        self._plot.setLabel("bottom", "x")
        self._plot.setLabel("left", "y")
        root.addWidget(self._plot, 1)

        # Coalesced repaint timer — the only thing that calls setData.
        self._redraw = QTimer(self)
        self._redraw.setInterval(_REDRAW_MS)
        self._redraw.timeout.connect(self._flush)
        self._redraw.start()

        if config:
            self.set_config(config)

    # ------------------------------------------------------------------
    # construction

    def _build_panel(self) -> QVBoxLayout:
        panel = QVBoxLayout()
        panel.setSpacing(4)

        # X-axis row.
        xrow = QHBoxLayout()
        xrow.setSpacing(6)
        xrow.addWidget(QLabel("X axis:"))
        self._x_edit = QLineEdit()
        self._x_edit.setPlaceholderText(r"regex for X  (empty = elapsed time)")
        self._x_edit.setToolTip(
            "Regex whose first capture group is the X value. Leave empty to use "
            "elapsed seconds since plotting started — the right choice when the "
            "data carries no timestamp."
        )
        self._x_edit.returnPressed.connect(self._apply)
        xrow.addWidget(self._x_edit, 1)
        self._x_label_edit = QLineEdit("x")
        self._x_label_edit.setMaximumWidth(80)
        self._x_label_edit.setToolTip("X axis label")
        self._x_label_edit.textChanged.connect(
            lambda t: self._plot.setLabel("bottom", t or "x")
        )
        xrow.addWidget(self._x_label_edit)

        # Window: how much of the tail to keep on screen. Empty value = grow
        # forever. Units are seconds (drop points older than W on the X axis,
        # meaningful when X is time-like) or samples (keep the last N points).
        xrow.addSpacing(12)
        xrow.addWidget(QLabel("Window:"))
        self._window_edit = QLineEdit()
        self._window_edit.setMaximumWidth(70)
        self._window_edit.setPlaceholderText("all")
        self._window_edit.setToolTip(
            "Show only the most recent data. Empty = keep everything (the plot "
            "grows over time). Set a value and pick units: 'sec' drops points "
            "older than that many X-units; 'samples' keeps the last N points."
        )
        self._window_edit.returnPressed.connect(self._apply)
        xrow.addWidget(self._window_edit)
        self._window_unit = QComboBox()
        self._window_unit.addItem("sec", "seconds")
        self._window_unit.addItem("samples", "samples")
        self._window_unit.currentIndexChanged.connect(self._apply)
        xrow.addWidget(self._window_unit)
        panel.addLayout(xrow)

        # Y-series rows live in their own vertical box so we can add/remove.
        panel.addWidget(QLabel("Y series:"))
        self._rows_box = QVBoxLayout()
        self._rows_box.setSpacing(4)
        self._rows: list[_SeriesRow] = []
        panel.addLayout(self._rows_box)

        # Buttons row: add series, apply, pause, clear, status.
        btns = QHBoxLayout()
        btns.setSpacing(6)
        add_btn = QPushButton("+ Series")
        add_btn.clicked.connect(lambda: self._add_row(""))
        btns.addWidget(add_btn)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self._apply)
        btns.addWidget(apply_btn)
        btns.addStretch(1)
        self._status = QLabel("")
        self._status.setStyleSheet("color: #888;")
        btns.addWidget(self._status)
        self._pause_btn = QPushButton("Pause")
        self._pause_btn.setCheckable(True)
        self._pause_btn.toggled.connect(self._on_pause)
        btns.addWidget(self._pause_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear)
        btns.addWidget(clear_btn)
        panel.addLayout(btns)

        # Start with one empty Y row so the panel isn't bare.
        self._add_row("")
        return panel

    # ------------------------------------------------------------------
    # series rows

    def _add_row(self, pattern: str, label: str = "") -> None:
        row = _SeriesRow(pattern, label, self._remove_row, self._apply)
        self._rows.append(row)
        self._rows_box.addWidget(row)

    def _remove_row(self, row: _SeriesRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        # Keep at least one row present.
        if not self._rows:
            self._add_row("")

    # ------------------------------------------------------------------
    # public API

    @property
    def config(self) -> dict:
        return {
            "x": self._x_edit.text().strip(),
            "x_label": self._x_label_edit.text().strip() or "x",
            "window": self._window_edit.text().strip(),
            "window_unit": self._window_unit.currentData(),
            "series": [
                {"pattern": r.pattern(), "label": r.label()}
                for r in self._rows
                if r.pattern()
            ],
        }

    def set_config(self, config: dict) -> None:
        self._x_edit.setText(str(config.get("x", "")))
        self._x_label_edit.setText(str(config.get("x_label", "x")) or "x")
        self._window_edit.setText(str(config.get("window", "")))
        unit = str(config.get("window_unit", "seconds"))
        idx = self._window_unit.findData(unit)
        self._window_unit.setCurrentIndex(idx if idx >= 0 else 0)
        # Rebuild the rows from the saved series. Each entry is either the new
        # {pattern, label} object or, for back-compat, a bare pattern string.
        for row in list(self._rows):
            self._rows.remove(row)
            row.setParent(None)
            row.deleteLater()
        series = config.get("series") or [""]
        for entry in series:
            if isinstance(entry, dict):
                self._add_row(str(entry.get("pattern", "")), str(entry.get("label", "")))
            else:
                self._add_row(str(entry))
        self._apply()

    def feed(self, data: bytes) -> None:
        """Push RX bytes. Cheap: assemble lines, extract points, buffer them.
        No drawing happens here — the redraw timer owns setData."""
        if self._extractor is None or self._paused:
            return
        touched: set[_Series] = set()
        for line in self._assembler.feed(data):
            ts = self._elapsed()
            result = self._extractor.feed_line(line, timestamp=ts)
            if not result.matched:
                self._unmatched += 1
                continue
            for name, (x, y) in result.points.items():
                series = self._series.get(name)
                if series is not None:
                    series.append(x, y)
                    touched.add(series)
            self._dirty = True
        if self._window is not None:
            for series in touched:
                self._trim_series(series)

    def _trim_series(self, series: _Series) -> None:
        """Drop points that fall outside the display window, oldest first."""
        if self._window is None:
            return
        if self._window_seconds:
            # Keep points whose X is within `window` of the newest X. Works for
            # any time-like X (elapsed time or a numeric timestamp regex).
            if not series.xs:
                return
            cutoff = series.xs[-1] - self._window
            while len(series.xs) > 1 and series.xs[0] < cutoff:
                series.xs.popleft()
                series.ys.popleft()
        else:
            # Keep the last N samples.
            limit = int(self._window)
            while len(series.xs) > limit:
                series.xs.popleft()
                series.ys.popleft()

    def clear(self) -> None:
        for series in self._series.values():
            series.clear()
        self._assembler.reset()
        self._unmatched = 0
        self._t0 = None
        self._dirty = True
        self._update_status()

    # ------------------------------------------------------------------
    # internals

    def _elapsed(self) -> float:
        """Seconds since the first point after a (re)start — the time-based X.
        Only meaningful when the extractor uses time X, but cheap to keep."""
        now = time.monotonic()
        if self._t0 is None:
            self._t0 = now
        return now - self._t0

    def _apply(self) -> None:
        cfg = self.config
        # Each series' display name is its label if set, else auto-derived from
        # the regex. Names are de-duplicated so two unlabeled series can't
        # collide on one curve.
        seen: set[str] = set()
        specs: list[SeriesSpec] = []
        for i, entry in enumerate(cfg["series"]):
            pat = entry["pattern"]
            name = entry["label"] or self._auto_name(i, pat)
            name = self._unique(name, seen)
            seen.add(name)
            specs.append(SeriesSpec(name=name, pattern=pat))
        if not specs:
            self._status.setText("⚠ add at least one Y series")
            self._status.setStyleSheet("color: #c0392b;")
            return
        try:
            extractor = MultiSeriesExtractor(cfg["x"], specs)
        except re.error as exc:
            self._status.setText(f"⚠ bad regex: {exc}")
            self._status.setStyleSheet("color: #c0392b;")
            return

        self._window, self._window_seconds = self._parse_window(cfg)

        self._status.setStyleSheet("color: #888;")
        self._extractor = extractor
        self._rebuild_series([s.name for s in specs])
        self._assembler.reset()
        self._unmatched = 0
        self._t0 = None
        self._dirty = True
        self._update_status()
        self.config_changed.emit(json.dumps(cfg))

    @staticmethod
    def _unique(name: str, seen: set[str]) -> str:
        if name not in seen:
            return name
        i = 2
        while f"{name}_{i}" in seen:
            i += 1
        return f"{name}_{i}"

    @staticmethod
    def _parse_window(cfg: dict) -> tuple[float | None, bool]:
        """Return (window_value, is_seconds). window_value is None when no
        window is set (grow forever) or the field isn't a positive number."""
        raw = str(cfg.get("window", "")).strip()
        if not raw:
            return None, True
        try:
            val = float(raw)
        except ValueError:
            return None, True
        if val <= 0:
            return None, True
        return val, cfg.get("window_unit", "seconds") == "seconds"

    @staticmethod
    def _auto_name(index: int, pattern: str) -> str:
        # Name a series after a leading `key=` in its pattern if present, else
        # data1/data2/… — purely for the legend.
        m = re.match(r"\s*([A-Za-z_][\w]*)\s*=", pattern)
        return m.group(1) if m else f"data{index + 1}"

    def _rebuild_series(self, names: list[str]) -> None:
        # Fresh curves for the new config; drop any from the previous one.
        self._plot.clear()
        self._plot.addLegend()
        self._series.clear()
        for i, name in enumerate(names):
            color = _SERIES_COLORS[i % len(_SERIES_COLORS)]
            curve = self._plot.plot([], [], pen=pg.mkPen(color=color, width=2), name=name)
            self._series[name] = _Series(name, curve, self._cap)

    def _on_pause(self, paused: bool) -> None:
        self._paused = paused
        self._pause_btn.setText("Resume" if paused else "Pause")

    def _flush(self) -> None:
        """Redraw timer: push buffered points to the curves, once per frame."""
        if not self._dirty:
            return
        self._dirty = False
        for series in self._series.values():
            # deque → list is O(n) but bounded by the ring cap and runs at most
            # once per frame, so it never tracks the device's output rate.
            series.curve.setData(list(series.xs), list(series.ys))
        self._update_status()

    def _update_status(self) -> None:
        parts = [f"{len(self._series)} series"]
        if self._unmatched:
            parts.append(f"unmatched: {self._unmatched}")
        self._status.setText("   ".join(parts))

    def stop(self) -> None:
        """Stop the redraw timer (called on teardown)."""
        self._redraw.stop()
