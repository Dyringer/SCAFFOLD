from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from app.core.resource_manager import resource_path
from app.core.settings_store import settings_store


class ThemeManager(QObject):
    theme_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._current: str = settings_store.get("app.theme", "light")

    @property
    def current(self) -> str:
        return self._current

    def apply(self, theme: str) -> None:
        qss_file = resource_path(f"themes/{theme}.qss")
        qss = qss_file.read_text(encoding="utf-8") if qss_file.exists() else ""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(qss)
        self._current = theme
        settings_store.set("app.theme", theme)
        self.theme_changed.emit(theme)

    def toggle(self) -> None:
        self.apply("dark" if self._current == "light" else "light")


theme_manager = ThemeManager()
