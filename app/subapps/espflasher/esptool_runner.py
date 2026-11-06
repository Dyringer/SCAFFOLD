"""Run esptool as a child process and stream its progress.

We drive the standalone `esptool.exe` (shipped beside this module, see
`find_esptool`) through QProcess rather than importing esptool as a library:
no extra Python deps, a crash or hang in esptool can't take the app down, and
cancelling is just killing the process — which also guarantees the COM port
handle is released.
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from app.subapps.espflasher.progress import FlashEvent, Stage, parse_line

log = logging.getLogger(__name__)

# (esptool --chip value, label). "auto" lets esptool detect the chip.
CHIPS: list[tuple[str, str]] = [
    ("auto", "Auto-detect"),
    ("esp32s3", "ESP32-S3"),
    ("esp32s2", "ESP32-S2"),
    ("esp32", "ESP32"),
    ("esp32c3", "ESP32-C3"),
    ("esp32c6", "ESP32-C6"),
    ("esp32c2", "ESP32-C2"),
    ("esp32h2", "ESP32-H2"),
    ("esp8266", "ESP8266"),
]

# Flashing baud. Ignored by native-USB chips (S2/S3/C3 USB-JTAG/CDC), which
# always run at USB speed; matters for USB-UART bridges (CP210x, CH34x, FTDI).
FLASH_BAUDS: list[int] = [115200, 230400, 460800, 921600, 1500000, 2000000]
DEFAULT_FLASH_BAUD = 921600
DEFAULT_CHIP = "esp32s3"

# SPI flash header options. "keep" = leave the image header as built;
# "detect" (size) = probe the flash chip and patch the header to match.
FLASH_MODES: list[str] = ["keep", "qio", "qout", "dio", "dout"]
FLASH_FREQS: list[str] = ["keep", "80m", "60m", "48m", "40m", "30m", "26m", "20m"]
FLASH_SIZES: list[str] = [
    "keep", "detect", "1MB", "2MB", "4MB", "8MB", "16MB", "32MB", "64MB", "128MB",
]
DEFAULT_FLASH_MODE = "dio"
DEFAULT_FLASH_FREQ = "40m"
DEFAULT_FLASH_SIZE = "detect"


def _find_tool(name: str, *path_names: str) -> str | None:
    exe = f"{name}.exe" if sys.platform == "win32" else name
    if getattr(sys, "frozen", False):
        bundled = Path(sys._MEIPASS) / "esptool" / exe  # type: ignore[attr-defined]
        if bundled.is_file():
            return str(bundled)
    # Newest release folder first (names embed the version).
    for candidate in sorted(Path(__file__).parent.glob(f"esptool*/**/{exe}"), reverse=True):
        if candidate.is_file():
            return str(candidate)
    for n in (name, *path_names):
        found = shutil.which(n)
        if found:
            return found
    return None


def find_esptool() -> str | None:
    """Locate an esptool executable.

    Order: the copy bundled into a frozen build (`<bundle>/esptool/`), any
    `esptool*/**/esptool.exe` unpacked next to this module (the release zip
    from github.com/espressif/esptool), then esptool on PATH.
    """
    return _find_tool("esptool", "esptool.py")


def find_espefuse() -> str | None:
    """Locate espefuse, which ships beside esptool in the same release."""
    return _find_tool("espefuse", "espefuse.py")


def _session_args(port: str, chip: str, baud: int | None, after: str | None) -> list[str]:
    args = ["--chip", chip, "--port", port]
    if baud is not None:
        args += ["--baud", str(baud)]
    args += ["--before", "default_reset"]
    if after is not None:
        args += ["--after", after]
    return args


def build_info_args(*, port: str, chip: str = DEFAULT_CHIP,
                    baud: int = DEFAULT_FLASH_BAUD) -> list[str]:
    """esptool argv for `flash_id`: connect, print chip + flash info, reset."""
    return [*_session_args(port, chip, baud, "hard_reset"), "flash_id"]


def build_efuse_args(*, port: str, chip: str = DEFAULT_CHIP) -> list[str]:
    """espefuse argv for the read-only `summary` command."""
    return [*_session_args(port, chip, None, "hard_reset"), "summary"]


def build_read_args(*, port: str, size: int, path: str, chip: str = DEFAULT_CHIP,
                    baud: int = DEFAULT_FLASH_BAUD, address: int = 0) -> list[str]:
    """esptool argv reading `size` bytes of flash from `address` into `path`."""
    return [*_session_args(port, chip, baud, "hard_reset"),
            "read_flash", f"0x{address:x}", f"0x{size:x}", path]


def build_erase_args(*, port: str, chip: str = DEFAULT_CHIP,
                     baud: int = DEFAULT_FLASH_BAUD) -> list[str]:
    """esptool argv wiping the whole flash (`erase_flash`)."""
    return [*_session_args(port, chip, baud, "hard_reset"), "erase_flash"]


def build_write_args(
    *,
    port: str,
    images: list[tuple[int, str]],
    chip: str = DEFAULT_CHIP,
    baud: int = DEFAULT_FLASH_BAUD,
    erase_all: bool = False,
    flash_mode: str = "keep",
    flash_freq: str = "keep",
    flash_size: str = "keep",
) -> list[str]:
    """esptool argv (without the program) writing `images` [(offset, path)]
    in one session.

    Resets into the ROM bootloader via DTR/RTS before, and hard-resets into
    the new firmware after, so no BOOT/EN button presses are needed on boards
    with the usual auto-reset circuit (or native USB).
    """
    args = [*_session_args(port, chip, baud, "hard_reset"), "write_flash"]
    if erase_all:
        args.append("--erase-all")
    for opt, value in (
        ("--flash_mode", flash_mode),
        ("--flash_freq", flash_freq),
        ("--flash_size", flash_size),
    ):
        if value != "keep":
            args += [opt, value]
    for offset, path in images:
        args += [f"0x{offset:x}", path]
    return args


# read_flash redraws its "<bytes> (<pct> %)" counter with backspaces.
_READ_FRAGMENT = re.compile(r"\d+ \(\d+ %\)\x08+")


class EsptoolRunner(QObject):
    """One esptool-family program (esptool, espefuse) at a time, via signals.

    `output` carries raw text chunks as they arrive (including the partial
    "Connecting....." dot line) for a live log; `progress` carries parsed
    events; `finished(ok, summary)` fires exactly once per start().
    """

    output = Signal(str)
    progress = Signal(object)       # FlashEvent
    finished = Signal(bool, str)    # success, human-readable summary

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: QProcess | None = None
        self._line_buf = ""
        self._last_error = ""
        self._cancelled = False
        self._reported = False
        self._success_text = "Flashed successfully"
        self._label = "esptool"

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.state() != QProcess.NotRunning

    def start(self, program: str, args: list[str], *,
              success_text: str = "Flashed successfully", label: str = "esptool") -> None:
        """Run `program args`. `success_text` is the summary reported on exit 0."""
        if self.is_running:
            raise RuntimeError(f"{label} is already running")
        self._success_text = success_text
        self._label = label
        self._line_buf = ""
        self._last_error = ""
        self._cancelled = False
        self._reported = False

        proc = QProcess(self)
        proc.setProgram(program)
        proc.setArguments(args)
        proc.setProcessChannelMode(QProcess.MergedChannels)
        # Piped Python stdio is block-buffered; without this read_flash's
        # progress would arrive in one lump at exit.
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        proc.setProcessEnvironment(env)
        proc.readyReadStandardOutput.connect(self._on_ready_read)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        log.info("%s: %s %s", label, program, " ".join(args))
        self.output.emit(f"$ {label} {' '.join(args)}\n")
        proc.start()

    def cancel(self) -> None:
        """Kill the running esptool (and its children) immediately."""
        proc = self._proc
        if proc is None or proc.state() == QProcess.NotRunning:
            return
        self._cancelled = True
        # The release esptool.exe is a PyInstaller one-file build: a bootloader
        # process that spawns the real Python process. Killing only the parent
        # can orphan the child — still holding the COM port open — so take
        # the whole tree down on Windows.
        pid = proc.processId()
        if sys.platform == "win32" and pid:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(pid)],
                    capture_output=True,
                    timeout=5,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            except (OSError, subprocess.SubprocessError):
                log.debug("taskkill failed", exc_info=True)
        proc.kill()

    # ------------------------------------------------------------------

    def _on_ready_read(self) -> None:
        if self._proc is None:
            return
        text = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        shown = _READ_FRAGMENT.sub("", text).replace("\x08", "")
        if shown:
            self.output.emit(shown)
        self._line_buf += text.replace("\x08", "\n")
        *lines, self._line_buf = self._line_buf.split("\n")
        for line in lines:
            self._handle_line(line)

    def _handle_line(self, line: str) -> None:
        event: FlashEvent | None = parse_line(line)
        if event is None:
            return
        if event.stage is Stage.ERROR:
            self._last_error = event.detail
        self.progress.emit(event)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        if self._line_buf:
            self._handle_line(self._line_buf)
            self._line_buf = ""
        if self._cancelled:
            self._report(False, "Cancelled")
        elif exit_status == QProcess.NormalExit and exit_code == 0:
            self._report(True, self._success_text)
        else:
            self._report(False, self._last_error or f"{self._label} exited with code {exit_code}")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        # FailedToStart never produces finished(); other errors (Crashed on
        # kill, read/write errors) are followed by finished(), which reports.
        if error == QProcess.FailedToStart:
            msg = self._proc.errorString() if self._proc is not None else "failed to start"
            self._report(False, f"Could not start {self._label}: {msg}")

    def _report(self, ok: bool, summary: str) -> None:
        if self._reported:
            return
        self._reported = True
        self.finished.emit(ok, summary)
