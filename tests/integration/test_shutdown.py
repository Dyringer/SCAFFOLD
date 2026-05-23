"""Integration test: the real main.py must exit cleanly.

Spawns python main.py with SCAFFOLD_AUTO_QUIT_MS set so the app
self-terminates a few seconds after boot. Asserts the process actually
exits within a deadline. This catches Windows-tray-IPC class regressions
that unit tests can't see because they never spin up the real
MainWindow + tray + multi-subapp registration.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MAIN_PY = REPO_ROOT / "main.py"
BOOT_TIMEOUT = 15.0     # window-shown signal must arrive within this many seconds
EXIT_TIMEOUT = 8.0      # process must exit this many seconds after auto-quit fires
AUTO_QUIT_MS = 2000     # app self-quits N ms after Window shown


def _spawn(profile: str, auto_activate: str | None = None) -> subprocess.Popen:
    env = dict(os.environ)
    env["SCAFFOLD_PROFILE"] = profile
    env["SCAFFOLD_AUTO_QUIT_MS"] = str(AUTO_QUIT_MS)
    if auto_activate:
        env["SCAFFOLD_AUTO_ACTIVATE"] = auto_activate
    # Force unbuffered output so we can stream-detect "Window shown"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.Popen(
        [sys.executable, "-X", "utf8", "-u", str(MAIN_PY)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _wait_for_window_shown(proc: subprocess.Popen, deadline: float) -> list[str]:
    """Read stdout until 'Window shown' appears or deadline elapses.

    Returns the lines captured so far. Raises if the deadline is hit.
    """
    seen: list[str] = []
    while time.time() < deadline:
        line = proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            if proc.poll() is not None:
                raise AssertionError(
                    f"process exited (rc={proc.returncode}) before Window shown\n"
                    + "".join(seen)
                )
            continue
        seen.append(line)
        if "Window shown" in line:
            return seen
    raise AssertionError(
        f"timed out waiting for Window shown after {BOOT_TIMEOUT}s\n"
        + "".join(seen)
    )


def _wait_for_exit(proc: subprocess.Popen, timeout: float) -> int:
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(
            f"process did not exit within {timeout}s after self-quit fired"
        )


def _cleanup_profile(profile: str) -> None:
    d = REPO_ROOT / f".local-{profile}"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def fresh_profile():
    """Use a unique profile so the test never touches the user's settings."""
    name = "test-shutdown"
    _cleanup_profile(name)
    yield name
    _cleanup_profile(name)


def test_clean_shutdown_default(fresh_profile: str) -> None:
    """App boots, sits idle briefly, exits cleanly when QTimer fires app.quit."""
    proc = _spawn(fresh_profile)
    try:
        boot_deadline = time.time() + BOOT_TIMEOUT
        _wait_for_window_shown(proc, boot_deadline)
        rc = _wait_for_exit(proc, EXIT_TIMEOUT)
        assert rc == 0, f"expected exit code 0, got {rc}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_clean_shutdown_with_chat_active(fresh_profile: str) -> None:
    """App boots with chat activated (the path that previously hung)."""
    proc = _spawn(fresh_profile, auto_activate="chat")
    try:
        boot_deadline = time.time() + BOOT_TIMEOUT
        _wait_for_window_shown(proc, boot_deadline)
        rc = _wait_for_exit(proc, EXIT_TIMEOUT)
        assert rc == 0, f"expected exit code 0, got {rc}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_clean_shutdown_with_network_tools_active(fresh_profile: str) -> None:
    """App boots with network_tools activated (multiple QTimers in panels)."""
    proc = _spawn(fresh_profile, auto_activate="network_tools")
    try:
        boot_deadline = time.time() + BOOT_TIMEOUT
        _wait_for_window_shown(proc, boot_deadline)
        rc = _wait_for_exit(proc, EXIT_TIMEOUT)
        assert rc == 0, f"expected exit code 0, got {rc}"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
