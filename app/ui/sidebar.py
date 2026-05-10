from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QSize, Qt, Signal,
)
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.core.base_subapp import BaseSubApp

_COLLAPSED_W = 44
_EXPANDED_W = 160
_EASTER_EGG_TOGGLES = 5
_EASTER_EGG_WINDOW = 2.0  # seconds


class SidePanel(QWidget):
    subapp_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setFixedWidth(_COLLAPSED_W)

        self._expanded = False
        self._toggle_times: list[float] = []
        self._easter_egg_active = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(2, 4, 2, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch()

        self._buttons: dict[str, QPushButton] = {}

        self._anim = QPropertyAnimation(self, b"minimumWidth")
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim2 = QPropertyAnimation(self, b"maximumWidth")
        self._anim2.setDuration(180)
        self._anim2.setEasingCurve(QEasingCurve.OutCubic)

    # ------------------------------------------------------------------
    # registration

    def add_subapp(self, subapp: BaseSubApp) -> None:
        if subapp.id in self._buttons:
            return
        btn = QPushButton()
        btn.setCheckable(True)
        btn.setObjectName(f"sidebar_{subapp.id}")
        self._update_button_appearance(btn, subapp)
        btn.clicked.connect(lambda _, sid=subapp.id: self._on_click(sid))
        # insert before the stretch
        pos = self._layout.count() - 1
        self._layout.insertWidget(pos, btn)
        self._buttons[subapp.id] = btn

    def _update_button_appearance(self, btn: QPushButton, subapp: BaseSubApp) -> None:
        icon_char = getattr(subapp, "_icon_char", "⊞")
        if self._expanded:
            btn.setText(f"{icon_char}   {subapp.name}")
            btn.setStyleSheet("text-align: left; padding-left: 8px; font-size: 13px;")
            btn.setFixedWidth(_EXPANDED_W - 8)
        else:
            btn.setText(icon_char)
            btn.setStyleSheet("text-align: center; padding: 0; font-size: 16px;")
            btn.setFixedWidth(_COLLAPSED_W - 8)
        btn.setFixedHeight(36)
        btn.setIconSize(QSize(0, 0))  # suppress any QIcon so only text is shown

    def remove_subapp(self, subapp_id: str) -> None:
        btn = self._buttons.pop(subapp_id, None)
        if btn:
            self._layout.removeWidget(btn)
            btn.deleteLater()

    def set_active(self, subapp_id: str) -> None:
        for sid, btn in self._buttons.items():
            btn.setChecked(sid == subapp_id)

    # ------------------------------------------------------------------
    # toggle

    def toggle(self) -> None:
        now = time.monotonic()
        self._toggle_times.append(now)
        self._toggle_times = [t for t in self._toggle_times if now - t <= _EASTER_EGG_WINDOW]
        if len(self._toggle_times) >= _EASTER_EGG_TOGGLES and not self._easter_egg_active:
            self._activate_easter_egg()

        self._expanded = not self._expanded
        target = _EXPANDED_W if self._expanded else _COLLAPSED_W

        self._anim.stop(); self._anim2.stop()
        self._anim.setStartValue(self.width())
        self._anim.setEndValue(target)
        self._anim2.setStartValue(self.width())
        self._anim2.setEndValue(target)
        self._anim.start(); self._anim2.start()
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        from app.core.registry import registry
        for sid, btn in self._buttons.items():
            subapp = registry.get(sid)
            if subapp:
                self._update_button_appearance(btn, subapp)

    def _activate_easter_egg(self) -> None:
        self._easter_egg_active = True
        from app.core.registry import registry
        for subapp in registry.all(include_hidden=True):
            if subapp.hidden and subapp.id not in self._buttons:
                self.add_subapp(subapp)

    def _on_click(self, subapp_id: str) -> None:
        self.subapp_selected.emit(subapp_id)
