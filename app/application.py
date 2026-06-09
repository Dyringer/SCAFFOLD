from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtWidgets import QApplication

from app.core.log_handler import log_handler
from app.core.settings_store import settings_store
from app.core.theme_manager import theme_manager
from app.core.registry import registry


def _log_dir() -> Path:
    from app.core.resource_manager import local_dir
    return local_dir()


def _configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    log_path = _log_dir() / "app.log"
    file_handler = RotatingFileHandler(
        log_path, maxBytes=1 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-7s  %(name)s  %(message)s")
    )
    root.addHandler(file_handler)

    if not getattr(sys, "frozen", False):
        stream = logging.StreamHandler(sys.stdout)
        stream.setFormatter(
            logging.Formatter("%(levelname)-7s  %(name)s  %(message)s")
        )
        root.addHandler(stream)

    root.addHandler(log_handler)


def _register_subapps() -> None:
    from app.subapps.chat.core import ChatSubApp
    from app.subapps.counter.core import CounterSubApp
    from app.subapps.dummy.core import DummySubApp
    from app.subapps.games_hub.core import GamesHubSubApp
    from app.subapps.network_tools.core import NetworkToolsSubApp
    from app.subapps.programmer_calc.core import ProgrammerCalcSubApp
    from app.subapps.scratchpad.core import ScratchpadSubApp
    from app.subapps.secret.core import SecretSubApp
    from app.subapps.serial_terminal.core import SerialTerminalSubApp
    from app.subapps.settings.core import SettingsSubApp

    # Import game packages — each __init__.py registers games/composites
    import app.subapps.games_hub.games.tetris.game         # noqa: F401
    import app.subapps.games_hub.games.snake.game          # noqa: F401
    import app.subapps.games_hub.games.breakout.game       # noqa: F401
    import app.subapps.games_hub.games.space_invaders.game # noqa: F401
    import app.subapps.games_hub.games.icy_tower.game      # noqa: F401
    import app.subapps.games_hub.games.asteroids           # noqa: F401
    import app.subapps.games_hub.games.pong                # noqa: F401
    import app.subapps.games_hub.games.bomberman           # noqa: F401
    import app.subapps.games_hub.games.asteroidsbomber     # noqa: F401
    import app.subapps.games_hub.games.stacker             # noqa: F401

    registry.register(GamesHubSubApp())
    registry.register(ProgrammerCalcSubApp())
    registry.register(ScratchpadSubApp())
    registry.register(ChatSubApp())
    registry.register(NetworkToolsSubApp())
    registry.register(SerialTerminalSubApp())
    registry.register(SettingsSubApp())

    registry.register(CounterSubApp())
    registry.register(DummySubApp())
    registry.register(SecretSubApp())


def run() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)
    log.info("Starting S.C.A.F.F.O.L.D.")

    app = QApplication(sys.argv)
    app.setApplicationName("SCAFFOLD")
    app.setQuitOnLastWindowClosed(False)

    # import singletons early so they're initialised in order
    from app.core import (  # noqa: F401
        async_runner, message_bus, notification_bus,
    )

    # register app-level services. ServiceRegistry handles start order =
    # registration order, stop order = reverse.
    from app.core.services import service_registry
    from app.services.network import network_service
    service_registry.register("network", network_service)

    # apply saved theme before building window
    theme_manager.apply(settings_store.get("app.theme", "light"))

    from app.window import MainWindow
    window = MainWindow()

    _register_subapps()

    # Consolidated shutdown: tear everything down in the right order so
    # nothing lingers in the background after the main window closes.
    def _shutdown() -> None:
        """Tear down in strict order: subapps -> services -> window -> threadpool.

        Why this order matters:
          1. Subapps may hold references to services (e.g. chat registers
             a namespace on network_service). Tear them down first so
             those refs are released before services start closing.
          2. Services own sockets/threads/timers. Stop them before the
             window is destroyed so callbacks that touch UI don't run
             against half-deleted widgets.
          3. Window owns the tray icon, which on Windows holds shell IPC.
             Explicitly hide() before Qt's destructor cleanup — otherwise
             the release can stall and pin the process.

        Each step is best-effort (try/except). The 3-second os._exit
        safety net in run() catches anything that still pins the
        process after this returns.

        See `shitdown_rework.md` for the full rationale and the
        Windows-tray-IPC root cause that motivated this design.
        """
        log.info("Shutting down")
        try:
            registry.shutdown_all()
        except Exception:
            log.exception("registry.shutdown_all failed")
        try:
            service_registry.stop_all()
        except Exception:
            log.exception("service_registry.stop_all failed")
        try:
            window.shutdown()
        except Exception:
            log.exception("window.shutdown failed")
        try:
            from PySide6.QtCore import QThreadPool
            QThreadPool.globalInstance().clear()
            QThreadPool.globalInstance().waitForDone(2000)
        except Exception:
            pass
        log.info("Shutdown complete")

    app.aboutToQuit.connect(_shutdown)

    # restore last active sub-app (or test override)
    auto_activate = os.environ.get("SCAFFOLD_AUTO_ACTIVATE", "").strip()
    if auto_activate and registry.get(auto_activate):
        registry.activate(auto_activate)
    else:
        last = settings_store.get("app.last_subapp")
        if last and registry.get(last):
            registry.activate(last)

    window.show()
    log.info("Window shown")

    from PySide6.QtCore import QTimer
    QTimer.singleShot(0, service_registry.start_all)

    # Test hook: auto-quit after N ms. Used by the integration test to
    # exercise the real shutdown path without manual UI interaction.
    auto_quit_ms = os.environ.get("SCAFFOLD_AUTO_QUIT_MS", "").strip()
    if auto_quit_ms.isdigit():
        QTimer.singleShot(int(auto_quit_ms), app.quit)
    rc = app.exec()
    log.info("Event loop exited with rc=%d", rc)

    # Safety net: if anything still holds the process (rogue thread,
    # un-released native handle, etc.) hard-exit after a grace period.
    # This is a last resort — _shutdown above is the real cleanup.
    import threading
    def _force_exit() -> None:
        log.warning("Process still alive 3s after event loop exit — forcing")
        os._exit(rc)
    t = threading.Timer(3.0, _force_exit)
    t.daemon = True
    t.start()

    sys.exit(rc)
