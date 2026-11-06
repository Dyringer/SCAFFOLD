from __future__ import annotations

import sys
import textwrap

import pytest

from app.subapps.espflasher.device import ChipInfo, parse_chip_info
from app.subapps.espflasher.esptool_runner import (
    EsptoolRunner,
    build_efuse_args,
    build_erase_args,
    build_info_args,
    build_read_args,
    build_write_args,
    find_espefuse,
)
from app.subapps.espflasher.firmware import APP_OFFSET, guess_offset, parse_offset
from app.subapps.espflasher.progress import FlashEvent, Stage, parse_line

# ---------------------------------------------------------------------------
# progress parsing


@pytest.mark.parametrize(
    "line, expected",
    [
        ("Connecting....", FlashEvent(Stage.CONNECTING)),
        (
            "Chip is ESP32-S3 (QFN56) (revision v0.2)",
            FlashEvent(Stage.CHIP, detail="ESP32-S3 (QFN56) (revision v0.2)"),
        ),
        ("Erasing flash (this may take a while)...", FlashEvent(Stage.ERASING)),
        ("Erasing flash...", FlashEvent(Stage.ERASING)),
        ("Writing at 0x00010000... (3 %)", FlashEvent(Stage.WRITING, percent=3)),
        ("Writing at 0x0012c000... (100 %)", FlashEvent(Stage.WRITING, percent=100)),
        (
            "Wrote 1048576 bytes (612345 compressed) at 0x00010000 in 9.1 seconds...",
            FlashEvent(Stage.WROTE, percent=100),
        ),
        ("Hash of data verified.", FlashEvent(Stage.VERIFIED)),
        ("Hard resetting via RTS pin...", FlashEvent(Stage.RESETTING)),
        (
            "A fatal error occurred: Failed to connect to ESP32-S3: No serial data received.",
            FlashEvent(
                Stage.ERROR, detail="Failed to connect to ESP32-S3: No serial data received."
            ),
        ),
        ("esptool.py v4.7.0", None),
        ("Compressed 1048576 bytes to 612345...", None),
        ("   ", None),
    ],
)
def test_parse_line(line, expected):
    assert parse_line(line) == expected


# ---------------------------------------------------------------------------
# firmware helpers


def test_guess_offset_merged_image(tmp_path):
    data = bytearray(b"\xff" * 0x20000)
    data[0] = 0xE9
    data[0x8000:0x8002] = b"\xaa\x50"
    f = tmp_path / "merged.bin"
    f.write_bytes(bytes(data))
    assert guess_offset(f) == 0x0


def test_guess_offset_app_image(tmp_path):
    f = tmp_path / "app.bin"
    f.write_bytes(b"\xe9" + b"\x00" * 0x20000)
    assert guess_offset(f) == APP_OFFSET


def test_guess_offset_partition_table(tmp_path):
    f = tmp_path / "partition-table.bin"
    f.write_bytes(b"\xaa\x50" + b"\xff" * 0xBFE)
    assert guess_offset(f) == 0x8000


def test_guess_offset_unknown(tmp_path):
    small_bootloader = tmp_path / "bootloader.bin"
    small_bootloader.write_bytes(b"\xe9" + b"\x00" * 0x4000)
    junk = tmp_path / "junk.bin"
    junk.write_bytes(b"hello")
    assert guess_offset(small_bootloader) is None
    assert guess_offset(junk) is None
    assert guess_offset(tmp_path / "missing.bin") is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("0x10000", 0x10000),
        ("0x10000  application", 0x10000),
        ("0x0", 0),
        ("10000h", 0x10000),
        ("65536", 65536),
        ("", None),
        ("zzz", None),
    ],
)
def test_parse_offset(text, expected):
    assert parse_offset(text) == expected


def test_build_write_args_matches_bootloader_plus_app_script():
    # Equivalent of the hand-written flash .bat used for the S3 boards.
    args = build_write_args(
        port="COM5",
        images=[(0x0, "EVLY_bootloader.bin"), (0x10000, "BSC_ESP32S3_Zephyr_signed.bin")],
        chip="esp32s3", baud=921600,
        flash_mode="dio", flash_freq="40m", flash_size="detect",
    )
    assert args == [
        "--chip", "esp32s3", "--port", "COM5", "--baud", "921600",
        "--before", "default_reset", "--after", "hard_reset",
        "write_flash", "--flash_mode", "dio", "--flash_freq", "40m",
        "--flash_size", "detect",
        "0x0", "EVLY_bootloader.bin", "0x10000", "BSC_ESP32S3_Zephyr_signed.bin",
    ]


def test_build_write_args_keep_and_erase():
    args = build_write_args(
        port="COM7", images=[(0x10000, "app.bin")], chip="auto", baud=460800,
        erase_all=True,
    )
    assert args[-4:] == ["write_flash", "--erase-all", "0x10000", "app.bin"]
    assert "--flash_mode" not in args   # "keep" is esptool's default -> omitted


# ---------------------------------------------------------------------------
# runner against a fake esptool (a Python script emitting esptool-style output)


def _fake_esptool(tmp_path, body: str) -> list[str]:
    script = tmp_path / "fake_esptool.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return [str(script)]


def _run(qtbot, tmp_path, body: str):
    runner = EsptoolRunner()
    events: list[FlashEvent] = []
    chunks: list[str] = []
    runner.progress.connect(events.append)
    runner.output.connect(chunks.append)
    with qtbot.waitSignal(runner.finished, timeout=10000) as blocker:
        runner.start(sys.executable, _fake_esptool(tmp_path, body))
    return blocker.args, events, "".join(chunks)


def test_runner_success(qtbot, tmp_path):
    (ok, summary), events, out = _run(qtbot, tmp_path, """
        import sys
        print("Connecting....")
        print("Chip is ESP32-S3 (QFN56) (revision v0.2)")
        for pct in (10, 55, 100):
            print(f"Writing at 0x00010000... ({pct} %)"); sys.stdout.flush()
        print("Hash of data verified.")
        print("Hard resetting via RTS pin...")
    """)
    assert ok is True
    assert summary == "Flashed successfully"
    writes = [e.percent for e in events if e.stage is Stage.WRITING]
    assert writes == [10, 55, 100]
    assert any(e.stage is Stage.CHIP for e in events)
    assert "Hash of data verified." in out


def test_runner_failure_reports_fatal_error(qtbot, tmp_path):
    (ok, summary), _events, _out = _run(qtbot, tmp_path, """
        import sys
        print("Connecting......")
        print()
        print("A fatal error occurred: Failed to connect to ESP32-S3: No serial data received.")
        sys.exit(2)
    """)
    assert ok is False
    assert summary == "Failed to connect to ESP32-S3: No serial data received."


def test_runner_failed_to_start(qtbot, tmp_path):
    runner = EsptoolRunner()
    with qtbot.waitSignal(runner.finished, timeout=5000) as blocker:
        runner.start(str(tmp_path / "does-not-exist.exe"), [])
    ok, summary = blocker.args
    assert ok is False
    assert summary.startswith("Could not start esptool")


def test_panel_multi_image_progress(qtbot, tmp_path):
    """Overall progress is weighted by image size across esptool's per-image 0-100 %."""
    from app.subapps.espflasher.ui import EspFlasherPanel

    panel = EspFlasherPanel()
    qtbot.addWidget(panel)
    panel._job_sizes = [1000, 3000]          # bootloader, app
    panel._job_done = 0
    assert panel._overall_percent(100) == 25
    panel._on_progress(FlashEvent(Stage.WROTE, percent=100))
    assert panel._overall_percent(0) == 25
    assert panel._overall_percent(50) == 62
    panel._on_progress(FlashEvent(Stage.WROTE, percent=100))
    assert panel._overall_percent(0) == 100


def test_panel_drop_fills_empty_rows_and_guesses_offset(qtbot, tmp_path):
    from app.subapps.espflasher.ui import EspFlasherPanel

    app_bin = tmp_path / "app.bin"
    app_bin.write_bytes(b"\xe9" + b"\x00" * 0x20000)
    panel = EspFlasherPanel()
    qtbot.addWidget(panel)
    assert [r.offset() for r in panel._rows] == [0x0, 0x10000]   # default layout
    panel._rows[1].set_path(str(app_bin))
    assert panel._rows[1].offset() == 0x10000
    assert panel._rows[1].is_valid()
    assert panel._job_images() is None        # row 0 enabled but empty
    panel._rows[0]._enabled.setChecked(False)
    assert panel._job_images() == [(0x10000, str(app_bin), 1 + 0x20000)]


def test_runner_cancel(qtbot, tmp_path):
    runner = EsptoolRunner()
    chunks: list[str] = []
    runner.output.connect(chunks.append)
    runner.start(sys.executable, _fake_esptool(tmp_path, """
        import sys, time
        print("Connecting", end=""); sys.stdout.flush()
        time.sleep(30)
    """))
    # Partial (newline-less) output must stream through for the live log.
    qtbot.waitUntil(lambda: "Connecting" in "".join(chunks), timeout=10000)
    with qtbot.waitSignal(runner.finished, timeout=10000) as blocker:
        runner.cancel()
    assert blocker.args == [False, "Cancelled"]
    assert not runner.is_running



# ---------------------------------------------------------------------------
# device tools: parsers, arg builders, runner with a non-write command

FLASH_ID_OUTPUT = """\
esptool.py v4.7.0
Serial port COM5
Connecting....
Chip is ESP32-S3 (QFN56) (revision v0.2)
Features: WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)
Crystal is 40MHz
MAC: 34:85:18:aa:bb:cc
Uploading stub...
Running stub...
Stub running...
Manufacturer: c8
Device: 4018
Detected flash size: 16MB
Flash type set in eFuse: quad (4 data lines)
Hard resetting via RTS pin...
"""


def test_parse_chip_info_flash_id_output():
    info = parse_chip_info(FLASH_ID_OUTPUT)
    assert info.chip == "ESP32-S3 (QFN56)"
    assert info.revision == "v0.2"
    assert info.features == "WiFi, BLE, Embedded PSRAM 8MB (AP_3v3)"
    assert info.crystal == "40 MHz"
    assert info.mac == "34:85:18:aa:bb:cc"
    assert (info.flash_mfr, info.flash_device) == ("c8", "4018")
    assert info.flash_id == "GigaDevice  (c8/4018)"
    assert info.flash_size == "16MB"
    assert info.flash_size_bytes == 16 * 1024 * 1024


def test_parse_chip_info_variants():
    esp32 = parse_chip_info(
        "Chip is ESP32-D0WDQ6 (revision v1.0)\r\nMAC: 24:0a:c4:00:00:01\r\n"
        "BASE MAC: 24:0a:c4:00:00:02\r\nDetected flash size: 512KB\r\n"
    )
    assert esp32.revision == "v1.0"
    assert esp32.mac == "24:0a:c4:00:00:01"
    assert esp32.flash_size_bytes == 512 * 1024
    esp8266 = parse_chip_info("Chip is ESP8266EX\nDetected flash size: Unknown\n")
    assert (esp8266.chip, esp8266.revision, esp8266.flash_size) == ("ESP8266EX", "", "")
    assert esp8266.flash_size_bytes is None
    assert parse_chip_info("A fatal error occurred: nope").is_empty
    assert parse_chip_info("") == ChipInfo()


def test_read_flash_progress_lines():
    assert parse_line("0 (0 %)") == FlashEvent(Stage.READING, percent=0)
    assert parse_line("4194304 (25 %)") == FlashEvent(Stage.READING, percent=25)
    assert parse_line("16777216 (100 %)") == FlashEvent(Stage.READING, percent=100)
    done = "Read 16777216 bytes at 0x00000000 in 140.2 seconds (957.2 kbit/s)..."
    assert parse_line(done) == FlashEvent(Stage.READ, percent=100)
    # not mistaken for write progress
    assert parse_line("Writing at 0x00010000... (3 %)").stage is Stage.WRITING


def test_device_arg_builders():
    base = ["--chip", "esp32s3", "--port", "COM5"]
    assert build_info_args(port="COM5", chip="esp32s3", baud=460800) == [
        *base, "--baud", "460800", "--before", "default_reset", "--after", "hard_reset",
        "flash_id"]
    assert build_erase_args(port="COM5", chip="esp32s3", baud=460800)[-1] == "erase_flash"
    assert build_read_args(port="COM5", size=0x1000000, path="b.bin", chip="esp32s3",
                           baud=921600)[-4:] == ["read_flash", "0x0", "0x1000000", "b.bin"]
    efuse = build_efuse_args(port="COM5", chip="esp32s3")
    assert efuse == [*base, "--before", "default_reset", "--after", "hard_reset", "summary"]
    assert "--baud" not in efuse


def test_find_espefuse_returns_existing_file_or_none():
    path = find_espefuse()
    assert path is None or "espefuse" in path


def test_runner_non_write_command_and_read_progress(qtbot, tmp_path):
    runner = EsptoolRunner()
    events: list[FlashEvent] = []
    chunks: list[str] = []
    runner.progress.connect(events.append)
    runner.output.connect(chunks.append)
    script = _fake_esptool(tmp_path, r"""
        import sys
        print("Connecting....")
        print("Chip is ESP32-S3 (QFN56) (revision v0.2)")
        total = 4096
        for done in (0, 1024, 2048, 4096):
            msg = "%d (%d %%)" % (done, done * 100 / total)
            sys.stdout.write(msg + ("\n" if done == total else "\b" * len(msg)))
            sys.stdout.flush()
        print("Read 4096 bytes at 0x00000000 in 0.1 seconds...")
    """)
    with qtbot.waitSignal(runner.finished, timeout=10000) as blocker:
        runner.start(sys.executable, script, success_text="Backup saved", label="fake")
    assert blocker.args == [True, "Backup saved"]
    reads = [e.percent for e in events if e.stage is Stage.READING]
    assert reads == [0, 25, 50, 100]
    assert any(e.stage is Stage.READ for e in events)
    out = "".join(chunks)
    assert out.startswith("$ fake ")
    assert "\x08" not in out and "(25 %)" not in out   # counter noise kept out of the log
    assert "Read 4096 bytes" in out


def test_runner_failure_uses_label(qtbot, tmp_path):
    runner = EsptoolRunner()
    with qtbot.waitSignal(runner.finished, timeout=10000) as blocker:
        runner.start(sys.executable, _fake_esptool(tmp_path, "import sys; sys.exit(3)"),
                     label="espefuse")
    assert blocker.args == [False, "espefuse exited with code 3"]


def test_panel_device_card_and_single_job(qtbot, tmp_path, monkeypatch):
    from app.subapps.espflasher import ui as ui_mod
    from app.subapps.espflasher.ui import EspFlasherPanel

    panel = EspFlasherPanel()
    qtbot.addWidget(panel)
    panel._set_info(parse_chip_info(FLASH_ID_OUTPUT))
    assert panel._info_values["chip"].full_text() == "ESP32-S3 (QFN56)"
    assert panel._info_values["flash_size"].full_text() == "16MB"
    panel._set_info(ChipInfo())
    assert panel._info_values["mac"].full_text() == "—"

    # Never touch hardware: pretend a port is selected and run a fake program.
    script = _fake_esptool(tmp_path, """
        import time
        print("Chip is ESP32-S3 (QFN56) (revision v0.2)", flush=True)
        print("Detected flash size: 4MB", flush=True)
        time.sleep(30)
    """)
    monkeypatch.setattr(panel, "_selected_port", lambda: "COMX")
    monkeypatch.setattr(panel, "_esptool", sys.executable)
    monkeypatch.setattr(ui_mod, "build_info_args", lambda **_k: script)
    panel._update_controls()
    assert panel._info_btn.isEnabled() and panel._wipe_btn.isEnabled()
    panel.read_info()
    assert panel._runner.is_running
    for btn in (panel._info_btn, panel._efuse_btn, panel._backup_btn, panel._wipe_btn,
                panel._hero.start_btn):
        assert not btn.isEnabled()
    qtbot.waitUntil(lambda: "Detected flash size" in "".join(panel._job_output), timeout=10000)
    with qtbot.waitSignal(panel._runner.finished, timeout=10000):
        panel.cancel_flash()
    assert panel._hero.stage.text() == "Cancelled"
    assert panel._info_btn.isEnabled()
