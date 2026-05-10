from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.core.log_handler import log_handler
from app.core.settings_store import settings_store
from app.core.theme_manager import theme_manager
from app.core.registry import registry


def _log_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


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
    from app.subapps.counter.core import CounterSubApp
    from app.subapps.dummy.core import DummySubApp
    from app.subapps.programmer_calc.core import ProgrammerCalcSubApp
    from app.subapps.secret.core import SecretSubApp
    from app.subapps.settings.core import SettingsSubApp

    registry.register(CounterSubApp())
    registry.register(DummySubApp())
    registry.register(ProgrammerCalcSubApp())
    registry.register(SecretSubApp())
    registry.register(SettingsSubApp())


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

    # apply saved theme before building window
    theme_manager.apply(settings_store.get("app.theme", "light"))

    from app.window import MainWindow
    window = MainWindow()

    _register_subapps()

    # restore last active sub-app
    last = settings_store.get("app.last_subapp")
    if last and registry.get(last):
        registry.activate(last)

    window.show()
    log.info("Window shown")
    sys.exit(app.exec())
