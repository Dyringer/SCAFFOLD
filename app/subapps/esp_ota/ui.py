from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.core.async_runner import async_runner
from app.core.notification_bus import notification_bus
from app.core.settings_store import settings_store
from app.subapps.esp_ota.client import parse_target, probe, send_reboot
from app.subapps.esp_ota.runner import DeviceProber, OtaRunner
from app.subapps.espflasher.firmware import APP_OFFSET, ESP_IMAGE_MAGIC, guess_offset
from app.ui.widgets import (
    Card,
    FileRow,
    HeroCard,
    OutputCard,
    PortItem,
    ToggleSwitch,
    badge,
    button,
    human_size,
    mark_modern,
    repolish,
    set_state,
)

_LOG_MAX_LINES = 5000


def firmware_warning(path: str | Path) -> str:
    """Why `path` probably isn't an OTA-able app image ("" if it looks fine).

    The http_panel streams the body into an OTA partition and validates it as
    an ESP *app* image, so a merged/factory image or a partition table will be
    rejected after the whole upload. Warn up front instead.
    """
    try:
        with open(path, "rb") as f:
            first = f.read(1)
    except OSError:
        return ""
    offset = guess_offset(path)
    if offset == 0x0:
        return ("Looks like a merged image (bootloader + partitions + app). "
                "OTA needs the app-only .bin.")
    if offset == 0x8000:
        return "This is a partition table, not an app image."
    if offset != APP_OFFSET and (not first or first[0] != ESP_IMAGE_MAGIC):
        return "No ESP app-image header (0xE9) — the device will likely reject it."
    return ""


class _FirmwareRow(FileRow):
    """[name / folder · date] [size] [📂] + warning — the single image to push."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(last_dir_key="esp_ota.last_dir", empty_title="No firmware selected",
                         empty_hint="Browse, or drop the app .bin anywhere on this page",
                         browse_tip="Choose firmware…", parent=parent)
        self._warning = QLabel("")
        self._warning.setObjectName("FileWarning")
        self._warning.setWordWrap(True)
        self.outer.addWidget(self._warning)
        self.set_path("")

    def is_valid(self) -> bool:
        return self.size() > 0

    def _refresh(self) -> None:
        self._warning.hide()
        super()._refresh()

    def _file_state(self, path: Path) -> str:
        warning = firmware_warning(path)
        self._warning.setText(f"⚠ {warning}")
        self._warning.setVisible(bool(warning))
        return "warn" if warning else "ok"


class EspOtaPanel(QWidget):
    """Push firmware to a running ESP32 over Wi-Fi (http_panel OTA endpoint).

    Left: saved devices with live online/offline status. Right, as cards: the
    update action with progress, the firmware file, quick device actions
    (web panel, reboot, check) and the raw log.
    """

    status_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("EspOta")
        mark_modern(self)
        self.setAcceptDrops(True)

        self._devices: list[dict] = [
            d for d in (settings_store.get("esp_ota.devices") or [])
            if isinstance(d, dict) and d.get("host")
        ]
        self._online: dict[str, bool] = {}
        self._job_key: str | None = None

        self._runner = OtaRunner(self)
        self._runner.stage.connect(self._on_stage)
        self._runner.progress.connect(self._on_progress)
        self._runner.log_line.connect(lambda t: self._output.append(t + "\n"))
        self._runner.finished.connect(self._on_finished)

        self._prober = DeviceProber(parent=self)
        self._prober.results.connect(self._on_probe_results)

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

        self._fw_row.set_path(str(settings_store.get("esp_ota.firmware", "")))
        self._rebuild_devices()
        self._hero.set("Ready", "", "idle")
        self._update_controls()

    # ------------------------------------------------------------------
    # construction

    def _build_left(self) -> QWidget:
        card = Card("Devices")
        card.header.addWidget(button("⟳", self._prober.check_now,
                                     tip="Check which devices are online", name="IconBtn"))
        self._remove_btn = button("✕", self._remove_selected,
                                  tip="Remove the selected device", name="IconBtn")
        self._remove_btn.setProperty("kind", "danger")
        card.header.addWidget(self._remove_btn)

        self._dev_list = QListWidget()
        self._dev_list.setObjectName("PortList")
        self._dev_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self._dev_list.currentItemChanged.connect(self._on_device_changed)
        card.body.addWidget(self._dev_list, 1)

        self._no_devices = QLabel("No devices yet.\nAdd your board's IP address below.")
        self._no_devices.setObjectName("Hint")
        self._no_devices.setAlignment(Qt.AlignCenter)
        card.body.addWidget(self._no_devices, 1)

        self._addr_edit = QLineEdit()
        self._addr_edit.setPlaceholderText("192.168.1.42  or  cam.local:8080")
        self._addr_edit.textChanged.connect(lambda _t: self._update_add_btn())
        self._addr_edit.returnPressed.connect(self._add_device)
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Name (optional)")
        self._name_edit.returnPressed.connect(self._add_device)
        self._add_btn = button("+  Add device", self._add_device)
        card.body.addWidget(self._addr_edit)
        card.body.addWidget(self._name_edit)
        card.body.addWidget(self._add_btn)
        self._update_add_btn()
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
        col.addWidget(self._build_update_card())
        col.addWidget(self._build_firmware_card())
        col.addWidget(self._build_device_card())
        self._output = OutputCard("esp_ota.show_output", max_lines=_LOG_MAX_LINES)
        col.addWidget(self._output, 1)
        scroll.setWidget(content)
        return scroll

    def _build_update_card(self) -> QWidget:
        card = self._hero = HeroCard("Update over Wi-Fi", "⇪  Start OTA", self.start_ota,
                                     self.cancel_ota)
        opts = QHBoxLayout()
        opts.setSpacing(20)
        self._reboot_chk = ToggleSwitch("Reboot after upload")
        self._reboot_chk.setChecked(bool(settings_store.get("esp_ota.reboot", True)))
        self._reboot_chk.setToolTip(
            "Off: leave the update staged; it takes effect on the next reboot.")
        self._reboot_chk.toggled.connect(self._on_reboot_toggled)
        opts.addWidget(self._reboot_chk)
        self._wait_chk = ToggleSwitch("Wait until back online")
        self._wait_chk.setChecked(bool(settings_store.get("esp_ota.wait", True)))
        self._wait_chk.setToolTip("Poll the device after the reboot to confirm it came back up.")
        self._wait_chk.toggled.connect(lambda on: settings_store.set("esp_ota.wait", on))
        opts.addWidget(self._wait_chk)
        opts.addStretch(1)
        card.body.addLayout(opts)
        self._wait_chk.setEnabled(self._reboot_chk.isChecked())
        return card

    def _build_firmware_card(self) -> QWidget:
        card = Card("Firmware")
        self._fw_card = card
        self._fw_row = _FirmwareRow()
        self._fw_row.changed.connect(self._on_firmware_changed)
        card.body.addWidget(self._fw_row)
        return card

    def _build_device_card(self) -> QWidget:
        card = Card("Device")
        row = QHBoxLayout()
        row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(0)
        self._dev_title = QLabel("")
        self._dev_title.setObjectName("FileName")
        self._dev_url = QLabel("")
        self._dev_url.setObjectName("FileDir")
        text.addWidget(self._dev_title)
        text.addWidget(self._dev_url)
        row.addLayout(text, 1)
        self._dev_badge = badge("", "")
        row.addWidget(self._dev_badge)
        self._web_btn = button("Open web panel", self._open_web)
        row.addWidget(self._web_btn)
        self._reboot_btn = button("Reboot now", self._reboot_now)
        row.addWidget(self._reboot_btn)
        self._check_btn = button("Check", self._check_selected)
        row.addWidget(self._check_btn)
        card.body.addLayout(row)
        return card

    # ------------------------------------------------------------------
    # devices

    @staticmethod
    def _key(dev: dict) -> str:
        return f"{dev['host']}:{dev['port']}"

    def _selected(self) -> dict | None:
        item = self._dev_list.currentItem()
        if item is None:
            return None
        key = item.data(Qt.UserRole)
        return next((d for d in self._devices if self._key(d) == key), None)

    def _rebuild_devices(self, select: str | None = None) -> None:
        current = select or (self._key(s) if (s := self._selected()) else None) \
            or settings_store.get("esp_ota.selected")
        self._dev_list.blockSignals(True)
        self._dev_list.clear()
        for dev in self._devices:
            key = self._key(dev)
            online = self._online.get(key)
            if online is None:
                status, badges = "", []
            elif online:
                status, badges = "live", [("ONLINE", "live")]
            else:
                status, badges = "offline", [("OFFLINE", "")]
            widget = PortItem(dev.get("name") or dev["host"], key, badges, status)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, key)
            item.setSizeHint(widget.sizeHint())
            self._dev_list.addItem(item)
            self._dev_list.setItemWidget(item, widget)
            if key == current:
                self._dev_list.setCurrentItem(item)
        if self._dev_list.currentItem() is None and self._dev_list.count():
            self._dev_list.setCurrentRow(0)
        self._dev_list.blockSignals(False)
        self._dev_list.setVisible(bool(self._devices))
        self._no_devices.setVisible(not self._devices)
        self._prober.set_targets([(d["host"], int(d["port"])) for d in self._devices])
        self._on_device_changed()

    def _update_add_btn(self) -> None:
        self._add_btn.setEnabled(parse_target(self._addr_edit.text()) is not None)

    def _add_device(self) -> None:
        target = parse_target(self._addr_edit.text())
        if target is None:
            return
        host, port = target
        key = f"{host}:{port}"
        name = self._name_edit.text().strip()
        existing = next((d for d in self._devices if self._key(d) == key), None)
        if existing is not None:
            if name:
                existing["name"] = name
        else:
            self._devices.append({"name": name, "host": host, "port": port})
        self._save_devices()
        self._addr_edit.clear()
        self._name_edit.clear()
        self._rebuild_devices(select=key)
        self._check_selected()      # immediate status for the new device

    def _remove_selected(self) -> None:
        dev = self._selected()
        if dev is None or self._runner.is_running:
            return
        self._devices.remove(dev)
        self._online.pop(self._key(dev), None)
        self._save_devices()
        self._rebuild_devices()

    def _save_devices(self) -> None:
        settings_store.set("esp_ota.devices", [dict(d) for d in self._devices])

    def _on_device_changed(self, *_args) -> None:
        dev = self._selected()
        if dev is not None:
            key = self._key(dev)
            if settings_store.get("esp_ota.selected") != key:
                settings_store.set("esp_ota.selected", key)
            self._dev_title.setText(dev.get("name") or dev["host"])
            self._dev_url.setText(f"http://{key}/")
            online = self._online.get(key)
            self._dev_badge.setText({True: "ONLINE", False: "OFFLINE"}.get(online, "CHECKING"))
            self._dev_badge.setProperty("kind", "live" if online else "")
            repolish(self._dev_badge)
            self._dev_badge.show()
        else:
            self._dev_title.setText("No device selected")
            self._dev_url.setText("Add a device on the left")
            self._dev_badge.hide()
        self._update_controls()

    def _on_probe_results(self, results: dict) -> None:
        if results == {k: v for k, v in self._online.items() if k in results}:
            return   # nothing changed — don't rebuild the list
        self._online.update(results)
        self._rebuild_devices()

    # ------------------------------------------------------------------
    # device actions

    def _open_web(self) -> None:
        dev = self._selected()
        if dev is not None:
            QDesktopServices.openUrl(QUrl(f"http://{self._key(dev)}/"))

    def _reboot_now(self) -> None:
        dev = self._selected()
        if dev is None:
            return
        host, port = dev["host"], int(dev["port"])
        self._output.append(f"Requesting reboot of {host}:{port} …\n")

        def done(_r) -> None:
            self._output.append("Reboot requested\n")
            self._online[f"{host}:{port}"] = False
            self._rebuild_devices()

        def failed(exc) -> None:
            # A reboot often drops the socket mid-handshake — still a success.
            self._output.append(f"(connection dropped during reboot trigger: {exc})\n")

        async_runner.run(lambda: send_reboot(host, port), done, failed)

    def _check_selected(self) -> None:
        dev = self._selected()
        if dev is None:
            return
        host, port = dev["host"], int(dev["port"])
        key = f"{host}:{port}"

        def done(ok: bool) -> None:
            self._output.append(f"{key} is {'online' if ok else 'not responding'}\n")
            self._on_probe_results({key: ok})

        async_runner.run(lambda: probe(host, port), done)

    # ------------------------------------------------------------------
    # firmware

    def _on_firmware_changed(self) -> None:
        settings_store.set("esp_ota.firmware", self._fw_row.path())
        self._update_controls()

    def _on_reboot_toggled(self, on: bool) -> None:
        settings_store.set("esp_ota.reboot", on)
        self._wait_chk.setEnabled(on)

    # Online checks run only while the panel is shown.
    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._prober.start()

    def hideEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().hideEvent(event)
        self._prober.stop()

    def dragEnterEvent(self, event) -> None:  # noqa: N802 (Qt override)
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile() and not self._runner.is_running:
            event.acceptProposedAction()
            set_state(self._fw_card, "drop")

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        set_state(self._fw_card, "")

    def dropEvent(self, event) -> None:  # noqa: N802 (Qt override)
        set_state(self._fw_card, "")
        urls = event.mimeData().urls()
        if urls and urls[0].isLocalFile():
            self._fw_row.set_path(urls[0].toLocalFile())
            event.acceptProposedAction()

    # ------------------------------------------------------------------
    # OTA

    def _blocker(self) -> str | None:
        if self._selected() is None:
            return "Add or select a device"
        if not self._fw_row.path():
            return "Choose a firmware file"
        if not self._fw_row.is_valid():
            return "The firmware file is missing"
        return None

    def _update_controls(self) -> None:
        if not hasattr(self, "_hero"):
            return   # still constructing
        running = self._runner.is_running
        blocker = self._blocker()
        self._hero.start_btn.setEnabled(blocker is None and not running)
        self._hero.start_btn.setToolTip(blocker or "Upload the firmware to the selected device")
        self._hero.cancel_btn.setVisible(running)
        has_dev = self._selected() is not None
        for w in (self._web_btn, self._check_btn):
            w.setEnabled(has_dev)
        self._reboot_btn.setEnabled(has_dev and not running)
        for w in (self._dev_list, self._fw_row, self._add_btn, self._remove_btn,
                  self._addr_edit, self._name_edit, self._reboot_chk, self._wait_chk):
            w.setEnabled(not running)
        if not running:
            self._wait_chk.setEnabled(self._reboot_chk.isChecked())
            if self._hero.is_idle():
                self._hero.detail.setText(blocker or self._ready_detail())

    def _ready_detail(self) -> str:
        dev = self._selected()
        size = human_size(self._fw_row.size())
        return f"{Path(self._fw_row.path()).name}  ({size})  →  {self._key(dev)}"

    def start_ota(self) -> None:
        dev = self._selected()
        if self._blocker() is not None or dev is None or self._runner.is_running:
            return
        self._job_key = self._key(dev)
        self._output.clear()
        self._hero.begin("Connecting…", self._job_key)
        self._hero.set_percent(0)
        self.status_changed.emit(f"OTA → {self._job_key}")
        self._prober.set_paused(True)
        self._runner.start(dev["host"], int(dev["port"]), self._fw_row.path(),
                           reboot=self._reboot_chk.isChecked(),
                           wait_online=self._wait_chk.isChecked())
        self._update_controls()

    def cancel_ota(self) -> None:
        self._runner.cancel()

    def _on_stage(self, key: str, text: str) -> None:
        if key in ("validate", "reboot", "wait"):
            # Upload is done; what's left has no byte count.
            self._hero.set_busy()
        self._hero.set(text, self._job_key or "", "busy")

    def _on_progress(self, sent: int, total: int, rate: float) -> None:
        self._hero.set_percent(int(sent * 100 / total) if total else 100)
        if rate > 0:
            speed = f"{rate / 1024:.1f} KB/s  ·  ~{(total - sent) / rate:.0f} s left"
        else:
            speed = "measuring speed…"
        self._hero.detail.setText(
            f"{human_size(sent)} of {human_size(total)}  ·  {speed}  ·  {self._job_key}"
        )

    def _on_finished(self, ok: bool, summary: str) -> None:
        cancelled = summary == "Cancelled"
        state = "ok" if ok else ("idle" if cancelled else "error")
        self._hero.finish(state)
        title = "Done" if ok else ("Cancelled" if cancelled else "Failed")
        self._hero.set(title, summary if not ok else f"{summary}  ·  {self._job_key}", state)
        self.status_changed.emit(f"{self._job_key}: {summary}")
        self._prober.set_paused(False)
        self._prober.check_now()
        self._update_controls()
        if not cancelled:
            if ok:
                notification_bus.notify.emit("info", "OTA complete", f"{self._job_key}: {summary}")
            else:
                notification_bus.notify.emit("error", f"OTA failed ({self._job_key})", summary)

    # ------------------------------------------------------------------
    # lifecycle

    def shutdown(self) -> None:
        self._prober.stop()
        self._runner.shutdown()
