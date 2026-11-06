from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtSerialPort import QSerialPortInfo
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.notification_bus import notification_bus
from app.core.settings_store import settings_store
from app.subapps.espflasher.device import ChipInfo, parse_chip_info
from app.subapps.espflasher.esptool_runner import (
    CHIPS,
    DEFAULT_CHIP,
    DEFAULT_FLASH_BAUD,
    DEFAULT_FLASH_FREQ,
    DEFAULT_FLASH_MODE,
    DEFAULT_FLASH_SIZE,
    FLASH_BAUDS,
    FLASH_FREQS,
    FLASH_MODES,
    FLASH_SIZES,
    EsptoolRunner,
    build_efuse_args,
    build_erase_args,
    build_info_args,
    build_read_args,
    build_write_args,
    find_espefuse,
    find_esptool,
)
from app.subapps.espflasher.firmware import parse_offset
from app.subapps.espflasher.progress import FlashEvent, Stage
from app.subapps.espflasher.widgets import ImageRow
from app.subapps.serial_terminal.demo_port import DEMO_PORT_NAME
from app.subapps.serial_terminal.file_port import FILE_PORT_NAME
from app.subapps.serial_terminal.port_io import SerialPort, usb_badges
from app.ui.widgets import (
    Card,
    ElidedLabel,
    HeroCard,
    OutputCard,
    PortItem,
    ToggleSwitch,
    button,
    field_label,
    human_size,
    mark_modern,
    set_state,
)

_TERMINAL_ID = "serial_terminal"

# After a hard reset, native-USB chips (S2/S3/C3) drop off the bus and
# re-enumerate. Wait this long before looking for the port again, so we don't
# open the old handle in the instant before it disappears...
_CONSOLE_SETTLE_S = 1.0
# ...then require it to be present on this many consecutive polls...
_CONSOLE_STABLE_POLLS = 2
# ...and give up after this long.
_CONSOLE_TIMEOUT_S = 10.0
_CONSOLE_POLL_MS = 250

_LOG_MAX_LINES = 5000

# Job kinds (EspFlasherPanel._job_kind).
_FLASH, _INFO, _EFUSE, _BACKUP, _ERASE = "flash", "info", "efuse", "backup", "erase"
_EM_DASH = "—"


class EspFlasherPanel(QWidget):
    """Flash firmware to Espressif chips with esptool.

    Left: the serial ports (same names as the Serial Terminal). Right, as
    cards: the images to write (offset + file, several per session — e.g.
    bootloader at 0x0 and the app at 0x10000), target/flash options, the
    Start DFU action with an overall progress bar, and esptool's raw output.
    Optionally opens the port in the Serial Terminal once the device reboots.
    """

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EspFlasher")
        mark_modern(self)
        self.setAcceptDrops(True)

        self._esptool = find_esptool()
        self._espefuse = find_espefuse()
        self._runner = EsptoolRunner(self)
        self._runner.output.connect(self._on_output)
        self._runner.progress.connect(self._on_progress)
        self._runner.finished.connect(self._on_finished)
        self._rows: list[ImageRow] = []
        self._port_snapshot: list[tuple[str, str]] = []

        # Current job: port, per-image byte sizes (in write order) and how many
        # images esptool has finished, for an overall size-weighted progress.
        self._flash_port: str | None = None
        self._job_sizes: list[int] = []
        self._job_done = 0
        self._chip_desc = ""
        self._job_kind = _FLASH
        self._job_output: list[str] = []  # raw output of a running Read info job
        self._job_file = ""             # backup target
        self._info = ChipInfo()         # last Read info for the selected port
        self._pending_backup = ""       # backup file waiting on a flash-size probe

        # Post-flash "open console" wait (see _CONSOLE_* above).
        self._console_port: str | None = None
        self._console_not_before = 0.0
        self._console_deadline = 0.0
        self._console_hits = 0
        self._console_timer = QTimer(self)
        self._console_timer.setInterval(_CONSOLE_POLL_MS)
        self._console_timer.timeout.connect(self._poll_console_port)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([270, 730])
        outer.addWidget(splitter, 1)

        # Port rescans run only while the panel is shown (see showEvent).
        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(1000)
        self._scan_timer.timeout.connect(self._refresh_ports)

        self._load_images()
        self._refresh_ports()
        if self._esptool is None:
            self._output.append(
                "esptool executable not found.\n"
                "Unpack the esptool release (github.com/espressif/esptool/releases)\n"
                f"into {Path(__file__).parent}\n"
                "or put esptool on PATH, then restart.\n"
            )
            self._hero.set("esptool not found", "See the output below.", "error")
        else:
            self._hero.set("Ready", "Pick a port and firmware, then Start DFU.", "idle")
        self._update_controls()

    # ------------------------------------------------------------------
    # construction

    def _build_left(self) -> QWidget:
        card = Card("Device")
        card.header.addWidget(button("⟳", lambda: self._refresh_ports(force=True),
                                     tip="Rescan ports", name="IconBtn"))

        self._port_list = QListWidget()
        self._port_list.setObjectName("PortList")
        self._port_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._port_list.currentItemChanged.connect(self._on_port_changed)
        card.body.addWidget(self._port_list, 1)

        self._no_ports = QLabel(
            "No serial ports found.\nPlug in a board — the list\nrefreshes automatically."
        )
        self._no_ports.setObjectName("Hint")
        self._no_ports.setAlignment(Qt.AlignCenter)
        card.body.addWidget(self._no_ports, 1)
        return card

    def _build_right(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setObjectName("Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("Plain")
        col = QVBoxLayout(content)
        col.setContentsMargins(0, 0, 4, 0)
        col.setSpacing(12)
        col.addWidget(self._build_flash_card())
        col.addWidget(self._build_device_card())
        col.addWidget(self._build_firmware_card())
        col.addWidget(self._build_target_card())
        self._output = OutputCard("espflasher.show_output", max_lines=_LOG_MAX_LINES,
                                  min_height=160)
        col.addWidget(self._output, 1)
        scroll.setWidget(content)
        return scroll

    def _build_flash_card(self) -> QWidget:
        card = self._hero = HeroCard("Flash", "⚡  Start DFU", self.start_flash,
                                     self.cancel_flash)
        opts = QHBoxLayout()
        opts.setSpacing(20)
        self._console_chk = ToggleSwitch("Open console after flashing")
        self._console_chk.setChecked(bool(settings_store.get("espflasher.open_console", True)))
        self._console_chk.toggled.connect(
            lambda on: settings_store.set("espflasher.open_console", on)
        )
        if self._terminal() is None:
            self._console_chk.setChecked(False)
            self._console_chk.setEnabled(False)
            self._console_chk.setToolTip("Serial Terminal is not available.")
        opts.addWidget(self._console_chk)
        self._erase_chk = ToggleSwitch("Erase entire flash first")
        self._erase_chk.setChecked(bool(settings_store.get("espflasher.erase_all", False)))
        self._erase_chk.setToolTip("Also wipes NVS / stored settings on the device.")
        opts.addWidget(self._erase_chk)
        opts.addStretch(1)
        card.body.addLayout(opts)
        return card

    def _build_device_card(self) -> QWidget:
        card = Card("Device")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self._info_values: dict[str, ElidedLabel] = {}
        # (key, caption, row, column, column span)
        tiles = [
            ("chip", "Chip", 0, 0, 2), ("revision", "Revision", 0, 2, 1),
            ("crystal", "Crystal", 0, 3, 1),
            ("mac", "MAC", 3, 0, 2), ("flash_id", "Flash ID", 3, 2, 1),
            ("flash_size", "Flash size", 3, 3, 1),
            ("features", "Features", 6, 0, 4),
        ]
        for key, caption, row, col, span in tiles:
            grid.addWidget(field_label(caption), row, col, 1, span)
            value = ElidedLabel(_EM_DASH)
            value.setObjectName("StatValue")
            grid.addWidget(value, row + 1, col, 1, span)
            self._info_values[key] = value
        for c in range(4):
            grid.setColumnStretch(c, 1)
        for spacer in (2, 5):
            grid.setRowMinimumHeight(spacer, 6)
        card.body.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._info_btn = button("Read info", self.read_info,
                                tip="Connect and read chip, MAC and flash details (flash_id)")
        self._efuse_btn = button("eFuse summary", self.read_efuses,
                                 tip="Print the chip's eFuse values (read-only)")
        self._backup_btn = button("Back up flash…", self.backup_flash,
                                  tip="Save the whole flash contents to a file")
        self._wipe_btn = button("Erase flash…", self.erase_flash,
                                tip="Permanently wipe the entire flash")
        for b in (self._info_btn, self._efuse_btn, self._backup_btn):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self._wipe_btn)
        card.body.addLayout(row)
        return card

    def _set_info(self, info: ChipInfo) -> None:
        """Show `info` in the Device card tiles (empty fields show a dash)."""
        self._info = info
        for key, label in self._info_values.items():
            label.set_full_text(getattr(info, key) or _EM_DASH)

    def _build_firmware_card(self) -> QWidget:
        card = Card("Firmware")
        self._fw_card = card
        self._add_btn = button("+  Add image", lambda: self._add_row())
        card.header.addWidget(self._add_btn)

        self._rows_box = QWidget()
        self._rows_box.setObjectName("Plain")
        self._rows_layout = QVBoxLayout(self._rows_box)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(6)
        card.body.addWidget(self._rows_box)
        return card

    def _build_target_card(self) -> QWidget:
        card = Card("Target")
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)

        self._chip_combo = QComboBox()
        for value, label in CHIPS:
            self._chip_combo.addItem(label, value)
        self._select_data(self._chip_combo, settings_store.get("espflasher.chip", DEFAULT_CHIP))

        self._baud_combo = QComboBox()
        for b in FLASH_BAUDS:
            self._baud_combo.addItem(f"{b:,}".replace(",", " "), b)
        self._select_data(
            self._baud_combo, int(settings_store.get("espflasher.baud", DEFAULT_FLASH_BAUD))
        )
        self._baud_combo.setToolTip(
            "Transfer speed for USB-UART bridges. Native USB (S2/S3/C3) ignores it."
        )
        self._mode_combo = self._text_combo(
            FLASH_MODES, settings_store.get("espflasher.flash_mode", DEFAULT_FLASH_MODE))
        self._freq_combo = self._text_combo(
            FLASH_FREQS, settings_store.get("espflasher.flash_freq", DEFAULT_FLASH_FREQ))
        self._size_combo = self._text_combo(
            FLASH_SIZES, settings_store.get("espflasher.flash_size", DEFAULT_FLASH_SIZE))
        for combo in (self._mode_combo, self._freq_combo, self._size_combo):
            combo.setToolTip(
                "Patched into the bootloader image header.\n"
                "keep = as built; detect (size) = probe the flash chip."
            )

        fields = [
            ("Chip", self._chip_combo), ("Baud", self._baud_combo),
            ("Flash mode", self._mode_combo), ("Flash freq", self._freq_combo),
            ("Flash size", self._size_combo),
        ]
        for col, (label, widget) in enumerate(fields):
            grid.addWidget(field_label(label), 0, col)
            grid.addWidget(widget, 1, col)
            grid.setColumnStretch(col, 1)
        card.body.addLayout(grid)
        return card

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    @staticmethod
    def _text_combo(values: list[str], current) -> QComboBox:
        combo = QComboBox()
        combo.addItems(values)
        idx = combo.findText(str(current))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        return combo

    # ------------------------------------------------------------------
    # image rows

    def _add_row(self, offset: int = 0x10000, path: str = "", enabled: bool = True,
                 *, guess: bool = True) -> ImageRow:
        row = ImageRow(offset, "", enabled)
        row.changed.connect(self._update_controls)
        row.remove_requested.connect(self._remove_row)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        if path:
            row.set_path(path, guess=guess)
        self._update_controls()
        return row

    def _remove_row(self, row: ImageRow) -> None:
        if row in self._rows:
            self._rows.remove(row)
            row.deleteLater()
        if not self._rows:
            self._add_row()
        self._save_images()
        self._update_controls()

    def _load_images(self) -> None:
        saved = settings_store.get("espflasher.images") or []
        for entry in saved:
            offset = parse_offset(str(entry.get("offset", ""))) or 0
            self._add_row(offset, str(entry.get("path", "")),
                          bool(entry.get("enabled", True)), guess=False)
        if not self._rows:
            # Start with the usual split layout: bootloader + application.
            self._add_row(0x0)
            self._add_row(0x10000)

    def _save_images(self) -> None:
        settings_store.set("espflasher.images", [r.to_dict() for r in self._rows])

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._refresh_ports()
        self._scan_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._scan_timer.stop()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        urls = event.mimeData().urls()
        if urls and all(u.isLocalFile() for u in urls) and not self._runner.is_running:
            event.acceptProposedAction()
            set_state(self._fw_card, "drop")

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        set_state(self._fw_card, "")

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        set_state(self._fw_card, "")
        # Each dropped file fills the first empty row, else gets a new row.
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            empty = next((r for r in self._rows if not r.path()), None)
            if empty is not None:
                empty.set_path(url.toLocalFile())
            else:
                self._add_row(path=url.toLocalFile())
        self._save_images()
        event.acceptProposedAction()

    # ------------------------------------------------------------------
    # ports

    def _refresh_ports(self, force: bool = False) -> None:
        # Don't repopulate mid-flash: the port vanishes during the reset and
        # the selection must stay put.
        if self._runner.is_running:
            return
        ports = [(n, d) for n, d in SerialPort.available_ports()
                 if n not in (DEMO_PORT_NAME, FILE_PORT_NAME)]
        if ports == self._port_snapshot and not force:
            return   # unchanged — don't rebuild (avoids flicker every second)
        self._port_snapshot = ports
        chips = usb_badges()

        current = self._selected_port() or settings_store.get("espflasher.port")
        self._port_list.blockSignals(True)
        self._port_list.clear()
        for name, desc in ports:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, name)
            widget = PortItem(name, desc, [chips[name]] if name in chips else [])
            item.setSizeHint(widget.sizeHint())
            self._port_list.addItem(item)
            self._port_list.setItemWidget(item, widget)
            if name == current:
                self._port_list.setCurrentItem(item)
        if self._port_list.currentItem() is None and self._port_list.count():
            # Nothing remembered/still present: preselect so one board = zero clicks.
            self._port_list.setCurrentRow(0)
        self._port_list.blockSignals(False)
        self._port_list.setVisible(bool(ports))
        self._no_ports.setVisible(not ports)
        self._update_controls()

    def _selected_port(self) -> str | None:
        item = self._port_list.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _on_port_changed(self, *_args) -> None:
        port = self._selected_port()
        if port:
            settings_store.set("espflasher.port", port)
        if not self._info.is_empty and not self._runner.is_running:
            self._set_info(ChipInfo())   # info belongs to the previous board
        self._update_controls()

    # ------------------------------------------------------------------
    # flashing

    def _job_images(self) -> list[tuple[int, str, int]] | None:
        """Enabled (offset, path, size) sorted by offset, or None if any enabled
        row is invalid."""
        images = []
        for r in self._rows:
            if r.is_enabled():
                offset, size = r.offset(), r.size()
                if offset is None or size <= 0:
                    return None
                images.append((offset, r.path(), size))
        return sorted(images) or None

    def _blocker(self) -> str | None:
        """Why Start DFU is unavailable (None = ready)."""
        if self._esptool is None:
            return "esptool not found"
        if self._selected_port() is None:
            return "Select a port"
        enabled = [r for r in self._rows if r.is_enabled()]
        if not enabled:
            return "Enable at least one image"
        for r in enabled:
            if r.offset() is None:
                return "Fix the invalid offset"
            if r.size() <= 0:
                return "Choose a firmware file" if not r.path() else "A firmware file is missing"
        return None

    def _update_controls(self) -> None:
        if not hasattr(self, "_hero"):
            return   # still constructing
        running = self._runner.is_running
        blocker = self._blocker()
        self._hero.start_btn.setEnabled(blocker is None and not running)
        self._hero.start_btn.setToolTip(
            blocker or "Write the enabled images to the selected port")
        self._hero.cancel_btn.setVisible(running)
        port = self._selected_port()
        for btn, tool in ((self._info_btn, self._esptool), (self._efuse_btn, self._espefuse),
                          (self._backup_btn, self._esptool), (self._wipe_btn, self._esptool)):
            btn.setEnabled(tool is not None and port is not None and not running)
        for w in (
            self._port_list, self._rows_box, self._add_btn,
            self._chip_combo, self._baud_combo, self._mode_combo, self._freq_combo,
            self._size_combo, self._erase_chk,
        ):
            w.setEnabled(not running)
        if not running and self._hero.is_idle():
            self._hero.detail.setText(blocker or self._ready_detail())

    def _ready_detail(self) -> str:
        images = self._job_images() or []
        total = sum(size for _, _, size in images)
        return (f"{len(images)} image(s), {human_size(total)} → {self._selected_port()}"
                f"  ·  {self._chip_combo.currentText()}")

    @staticmethod
    def _target_settings(port: str, chip: str, baud: int) -> dict:
        return {"espflasher.port": port, "espflasher.chip": chip, "espflasher.baud": baud}

    def _start_job(self, kind: str, program: str, args: list[str], port: str, *,
                   success_text: str, detail: str,
                   job_sizes: list[int] | None = None, clear_log: bool = True) -> None:
        """Common launch path: free the port, reset the hero card, run `program`."""
        self._console_timer.stop()
        if clear_log:
            self._output.clear()
        # The OS port can only have one owner — free it if the terminal has it.
        terminal = self._terminal()
        if terminal is not None and terminal.release_port(port):
            self._output.append(f"— closed {port} in Serial Terminal —\n")

        self._job_kind = kind
        self._job_output = []
        self._flash_port = port
        self._job_sizes = job_sizes or []
        self._job_done = 0
        self._chip_desc = ""
        self._hero.begin("Connecting…", detail)
        self._runner.start(program, args, success_text=success_text, label=Path(program).stem)
        self._update_controls()

    def start_flash(self) -> None:
        port = self._selected_port()
        images = self._job_images()
        if self._esptool is None or not port or images is None or self._runner.is_running:
            return
        chip = str(self._chip_combo.currentData())
        baud = int(self._baud_combo.currentData())
        erase_all = self._erase_chk.isChecked()
        flash_mode = self._mode_combo.currentText()
        flash_freq = self._freq_combo.currentText()
        flash_size = self._size_combo.currentText()
        settings_store.set_many({
            "espflasher.images": [r.to_dict() for r in self._rows],
            **self._target_settings(port, chip, baud),
            "espflasher.flash_mode": flash_mode,
            "espflasher.flash_freq": flash_freq,
            "espflasher.flash_size": flash_size,
            "espflasher.erase_all": erase_all,
        })
        self.status_changed.emit(f"Flashing {len(images)} image(s) → {port}")
        self._start_job(
            _FLASH, self._esptool,
            build_write_args(
                port=port, images=[(o, p) for o, p, _ in images], chip=chip, baud=baud,
                erase_all=erase_all, flash_mode=flash_mode, flash_freq=flash_freq,
                flash_size=flash_size,
            ),
            port, success_text="Flashed successfully",
            detail=f"{port}  ·  resetting into the ROM bootloader",
            job_sizes=[size for _, _, size in images],
        )

    # ------------------------------------------------------------------
    # device tools

    def _device_job(self, tool: str | None) -> tuple[str, str, int] | None:
        """(port, chip, baud) if a device job can start now, else None."""
        port = self._selected_port()
        if tool is None or not port or self._runner.is_running:
            return None
        chip = str(self._chip_combo.currentData())
        baud = int(self._baud_combo.currentData())
        settings_store.set_many(self._target_settings(port, chip, baud))
        return port, chip, baud

    def read_info(self) -> None:
        job = self._device_job(self._esptool)
        if job is None:
            return
        port, chip, baud = job
        self.status_changed.emit(f"Reading device info ← {port}")
        self._start_job(
            _INFO, self._esptool, build_info_args(port=port, chip=chip, baud=baud), port,
            success_text="Device info read", detail=f"{port}  ·  reading chip and flash info",
            clear_log=not self._pending_backup,
        )

    def read_efuses(self) -> None:
        job = self._device_job(self._espefuse)
        if job is None:
            return
        port, chip, _baud = job
        self.status_changed.emit(f"Reading eFuses ← {port}")
        self._start_job(
            _EFUSE, self._espefuse, build_efuse_args(port=port, chip=chip), port,
            success_text="eFuse summary read", detail=f"{port}  ·  reading eFuses",
        )

    def _ask_backup_path(self) -> str:
        chip = self._info.chip.split(" ")[0].lower() or "esp"
        folder = str(settings_store.get("espflasher.backup_dir", "") or "")
        path, _ = QFileDialog.getSaveFileName(
            self, "Back up flash", str(Path(folder) / f"{chip}-flash-backup.bin"),
            "Flash image (*.bin);;All files (*)")
        return path

    def backup_flash(self) -> None:
        if self._device_job(self._esptool) is None:
            return
        path = self._ask_backup_path()
        if not path:
            return
        settings_store.set("espflasher.backup_dir", str(Path(path).parent))
        if self._info.flash_size_bytes is None:
            # Flash size unknown: probe with flash_id first, then back up.
            self._pending_backup = path
            self.read_info()
            return
        self._start_backup(path)

    def _start_backup(self, path: str) -> None:
        job = self._device_job(self._esptool)
        size = self._info.flash_size_bytes
        keep_log = bool(self._pending_backup)
        self._pending_backup = ""
        if job is None or not size:
            return
        port, chip, baud = job
        self._job_file = path
        self.status_changed.emit(f"Backing up {port} → {Path(path).name}")
        self._start_job(
            _BACKUP, self._esptool,
            build_read_args(port=port, size=size, path=path, chip=chip, baud=baud),
            port, success_text="Backup saved",
            detail=f"{port}  ·  {self._info.flash_size} → {Path(path).name}",
            clear_log=not keep_log,
        )

    def _confirm_erase(self, port: str) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Erase entire flash?")
        box.setText(f"Erase the entire flash of the device on {port}?")
        box.setInformativeText(
            "This permanently deletes the bootloader, firmware, stored settings (NVS) "
            "and every other partition. It cannot be undone, and the device will not "
            "boot until you flash it again.\n\nBack up the flash first if you may "
            "need anything on it."
        )
        erase = box.addButton("Erase flash", QMessageBox.DestructiveRole)
        cancel = box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(cancel)
        box.setEscapeButton(cancel)
        box.exec()
        return box.clickedButton() is erase

    def erase_flash(self) -> None:
        job = self._device_job(self._esptool)
        if job is None:
            return
        port, chip, baud = job
        if not self._confirm_erase(port):
            return
        self.status_changed.emit(f"Erasing flash on {port}")
        self._start_job(
            _ERASE, self._esptool, build_erase_args(port=port, chip=chip, baud=baud), port,
            success_text="Flash erased", detail=f"{port}  ·  erasing the entire flash",
        )

    def cancel_flash(self) -> None:
        self._console_timer.stop()
        self._runner.cancel()

    def _overall_percent(self, current_pct: int) -> int:
        """Size-weighted progress across all images of the job."""
        total = sum(self._job_sizes) or 1
        done = sum(self._job_sizes[: self._job_done])
        cur = self._job_sizes[self._job_done] if self._job_done < len(self._job_sizes) else 0
        return min(100, int((done + cur * current_pct / 100) * 100 / total))

    def _job_detail(self) -> str:
        parts = [self._flash_port or ""]
        if self._chip_desc:
            parts.append(self._chip_desc)
        n = len(self._job_sizes)
        if n > 1:
            parts.append(f"image {min(self._job_done + 1, n)} of {n}")
        return "  ·  ".join(p for p in parts if p)

    def _on_progress(self, event: FlashEvent) -> None:
        hero = self._hero
        if event.stage is Stage.CONNECTING:
            hero.set("Connecting…", self._job_detail(), "busy")
        elif event.stage is Stage.CHIP:
            self._chip_desc = event.detail
            hero.set("Connected", self._job_detail(), "busy")
            self.status_changed.emit(f"{self._flash_port}: {event.detail}")
        elif event.stage is Stage.ERASING:
            hero.set_busy()
            hero.set("Erasing flash…", self._job_detail(), "busy")
        elif event.stage is Stage.WRITING:
            hero.set_percent(self._overall_percent(event.percent or 0))
            hero.set("Writing…", self._job_detail(), "busy")
        elif event.stage is Stage.READING:
            hero.set_percent(event.percent or 0)
            hero.set("Reading flash…", self._job_detail(), "busy")
        elif event.stage is Stage.WROTE:
            self._job_done += 1
            hero.set_percent(self._overall_percent(0))
        elif event.stage is Stage.VERIFIED:
            hero.set("Verified", self._job_detail(), "busy")
        elif event.stage is Stage.RESETTING:
            hero.set("Resetting device…", self._job_detail(), "busy")

    def _on_finished(self, ok: bool, summary: str) -> None:
        port = self._flash_port
        kind = self._job_kind
        cancelled = summary == "Cancelled"
        state = "ok" if ok else ("idle" if cancelled else "error")
        self._hero.finish(state)

        if kind == _INFO and ok:
            self._set_info(parse_chip_info("".join(self._job_output)))
        if ok:
            title, detail = summary, self._job_detail()
            if kind == _FLASH:
                title = "Done"
            elif kind == _INFO:
                detail = "  ·  ".join(
                    s for s in (port, self._info.chip, self._info.flash_size) if s)
            elif kind == _EFUSE:
                detail = f"{port}  ·  see the output below"
            elif kind == _BACKUP:
                f = Path(self._job_file)
                detail = f"{human_size(f.stat().st_size)}  ·  {f}" if f.is_file() else str(f)
        else:
            title = "Cancelled" if cancelled else "Failed"
            detail = summary
            if "Failed to connect" in summary:
                detail += "  —  hold BOOT while pressing RESET, then retry."
        self._hero.set(title, detail, state)
        self.status_changed.emit(f"{port}: {summary}")
        self._output.append(f"\n— {summary} —\n")
        self._update_controls()
        self._refresh_ports(force=True)

        if not cancelled:
            what = {
                _FLASH: "Flash", _INFO: "Device info", _EFUSE: "eFuse summary",
                _BACKUP: "Backup", _ERASE: "Erase",
            }[kind]
            if ok and kind in (_FLASH, _BACKUP, _ERASE):
                extra = f"{len(self._job_sizes)} image(s) → {port}" if kind == _FLASH else detail
                notification_bus.notify.emit("info", f"{what} complete", extra)
            elif not ok:
                notification_bus.notify.emit("error", f"{what} failed ({port})", summary)

        # A backup that had to probe the flash size first continues now.
        pending = self._pending_backup
        if kind == _INFO and pending:
            if ok and self._info.flash_size_bytes:
                self._start_backup(pending)   # keeps the probe output in the log
            else:
                self._pending_backup = ""
                if ok:
                    notification_bus.notify.emit(
                        "warning", "Can't back up",
                        "The flash size could not be detected on this device.")

        if kind == _FLASH and ok and port and self._console_chk.isChecked() \
                and self._console_chk.isEnabled():
            self._wait_then_open_console(port)

    # ------------------------------------------------------------------
    # post-flash console

    def _terminal(self):
        """The Serial Terminal subapp, if registered and exposing our API."""
        from app.core.registry import registry
        term = registry.get(_TERMINAL_ID)
        if term is None or not hasattr(term, "open_console"):
            return None
        return term

    def _wait_then_open_console(self, port: str) -> None:
        now = time.monotonic()
        self._console_port = port
        self._console_not_before = now + _CONSOLE_SETTLE_S
        self._console_deadline = now + _CONSOLE_TIMEOUT_S
        self._console_hits = 0
        self._output.append(f"— waiting for {port} to come back —\n")
        self._console_timer.start()

    def _poll_console_port(self) -> None:
        now = time.monotonic()
        port = self._console_port
        if port is None or now < self._console_not_before:
            return
        # Names only — skip the description enrichment available_ports() does.
        present = any(i.portName() == port for i in QSerialPortInfo.availablePorts())
        self._console_hits = self._console_hits + 1 if present else 0
        if self._console_hits >= _CONSOLE_STABLE_POLLS:
            self._console_timer.stop()
            terminal = self._terminal()
            if terminal is not None:
                terminal.open_console(port)
        elif now > self._console_deadline:
            self._console_timer.stop()
            self._output.append(f"— {port} did not reappear; console not opened —\n")
            notification_bus.notify.emit(
                "warning", "Console not opened", f"{port} did not reappear after reset."
            )

    # ------------------------------------------------------------------
    # helpers

    def _on_output(self, text: str) -> None:
        if self._job_kind == _INFO:
            self._job_output.append(text)
        self._output.append(text)

    # ------------------------------------------------------------------
    # public API

    def shutdown(self) -> None:
        self._scan_timer.stop()
        self._console_timer.stop()
        self._runner.cancel()
        self._save_images()
