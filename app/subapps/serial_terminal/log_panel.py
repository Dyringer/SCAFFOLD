"""The 'Log' tab — drives session capture to a file and shows live stats.

Logging lives here (not on the console toolbar) so the console stays focused on
the terminal. The panel owns the UI and a poll timer; the SessionLogger that
actually writes bytes is owned by the session and passed in, so the RX/TX tap
in the session keeps feeding it regardless of which tab is shown.
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.subapps.serial_terminal.session_logger import LogMode, SessionLogger

# How often (ms) the live stats (file size, bytes, lines, elapsed) refresh.
_STATS_MS = 1000


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class LogPanel(QWidget):
    """File-capture controls + live status for one session.

    Emits `recording_changed(bool)` so the host can show a REC indicator
    elsewhere (e.g. the console toolbar).
    """

    recording_changed = Signal(bool)

    def __init__(
        self,
        logger: SessionLogger,
        default_dir: Path,
        port_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._logger = logger
        self._default_dir = default_dir
        self._port = port_name
        self._start_monotonic: float | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Mode + file selection ---------------------------------------
        controls = QFormLayout()
        controls.setSpacing(6)

        self._mode_combo = QComboBox()
        self._mode_combo.addItem("Raw RX (replayable, *.log.bin)", LogMode.RAW)
        self._mode_combo.addItem("RX + TX transcript (*.log)", LogMode.TRANSCRIPT)
        self._mode_combo.setToolTip(
            "Raw: verbatim received bytes — byte-faithful, can be re-loaded into "
            "the plotter. Transcript: human-readable RX+TX text record."
        )
        controls.addRow("Mode:", self._mode_combo)

        file_row = QHBoxLayout()
        file_row.setSpacing(6)
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        self._path_edit.setPlaceholderText("no file chosen — Browse to pick a path")
        file_row.addWidget(self._path_edit, 1)
        self._browse_btn = QPushButton("Browse…")
        self._browse_btn.clicked.connect(self._on_browse)
        file_row.addWidget(self._browse_btn)
        controls.addRow("File:", file_row)
        root.addLayout(controls)

        # --- Start / Stop / Open folder ----------------------------------
        btns = QHBoxLayout()
        btns.setSpacing(6)
        self._start_btn = QPushButton("Start logging")
        self._start_btn.clicked.connect(self._on_start_stop)
        btns.addWidget(self._start_btn)
        self._open_btn = QPushButton("Open folder")
        self._open_btn.clicked.connect(self._on_open_folder)
        btns.addWidget(self._open_btn)
        btns.addStretch(1)
        root.addLayout(btns)

        # --- Live info ----------------------------------------------------
        info = QFormLayout()
        info.setSpacing(4)
        self._status_lbl = QLabel("Idle")
        self._mode_lbl = QLabel("—")
        self._started_lbl = QLabel("—")
        self._size_lbl = QLabel("—")
        self._bytes_lbl = QLabel("—")
        self._lines_lbl = QLabel("—")
        self._elapsed_lbl = QLabel("—")
        info.addRow("Status:", self._status_lbl)
        info.addRow("Mode:", self._mode_lbl)
        info.addRow("Started:", self._started_lbl)
        info.addRow("File size:", self._size_lbl)
        info.addRow("Bytes written:", self._bytes_lbl)
        info.addRow("Lines (transcript):", self._lines_lbl)
        info.addRow("Elapsed:", self._elapsed_lbl)
        root.addLayout(info)
        root.addStretch(1)

        # Live-stats poll: only does work while recording.
        self._timer = QTimer(self)
        self._timer.setInterval(_STATS_MS)
        self._timer.timeout.connect(self._refresh_stats)

        self._chosen_path: Path | None = None
        self._update_controls()

    # ------------------------------------------------------------------
    # file selection

    def _suggested_path(self) -> Path:
        mode: LogMode = self._mode_combo.currentData()
        self._default_dir.mkdir(parents=True, exist_ok=True)
        return self._default_dir / f"{self._port}{mode.default_suffix}"

    def _on_browse(self) -> None:
        mode: LogMode = self._mode_combo.currentData()
        filt = (
            "Raw RX capture (*.log.bin)"
            if mode is LogMode.RAW
            else "RX+TX transcript (*.log)"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "Choose log file", str(self._suggested_path()), filt
        )
        if path:
            self._chosen_path = Path(path)
            self._path_edit.setText(path)
            self._update_controls()

    # ------------------------------------------------------------------
    # start / stop

    def _on_start_stop(self) -> None:
        if self._logger.is_logging:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        if self._chosen_path is None:
            return
        mode: LogMode = self._mode_combo.currentData()
        try:
            self._logger.start(self._chosen_path, mode)
        except OSError as exc:
            self._status_lbl.setText(f"⚠ cannot open file: {exc}")
            return
        self._start_monotonic = time.monotonic()
        self._started_lbl.setText(time.strftime("%H:%M:%S"))
        self._mode_lbl.setText(mode.value)
        self._timer.start()
        self._refresh_stats()
        self._update_controls()
        self.recording_changed.emit(True)

    def _stop(self) -> None:
        self._logger.stop()
        self._timer.stop()
        self._start_monotonic = None
        self._refresh_stats()
        self._update_controls()
        self.recording_changed.emit(False)

    def stop_if_logging(self) -> None:
        """Called by the host on teardown / disconnect-close paths."""
        if self._logger.is_logging:
            self._stop()

    # ------------------------------------------------------------------
    # display

    def _update_controls(self) -> None:
        recording = self._logger.is_logging
        self._status_lbl.setText("● Recording" if recording else "Idle")
        self._start_btn.setText("Stop logging" if recording else "Start logging")
        # Can only start once a path is chosen; mode/file locked while recording.
        self._start_btn.setEnabled(recording or self._chosen_path is not None)
        self._mode_combo.setEnabled(not recording)
        self._browse_btn.setEnabled(not recording)

    def _refresh_stats(self) -> None:
        path = self._logger.path or self._chosen_path
        # File size from disk (the headline "is it growing?" number).
        size = 0
        if path is not None and path.exists():
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
        self._size_lbl.setText(_human_size(size))
        self._bytes_lbl.setText(f"{self._logger.bytes_written:,}")
        lines = self._logger.lines_written
        self._lines_lbl.setText(f"{lines:,}" if lines else "—")
        if self._start_monotonic is not None:
            secs = int(time.monotonic() - self._start_monotonic)
            self._elapsed_lbl.setText(f"{secs // 60:02d}:{secs % 60:02d}")

    def _on_open_folder(self) -> None:
        target = (self._chosen_path or self._suggested_path()).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def stop(self) -> None:
        """Stop the poll timer on teardown."""
        self._timer.stop()
