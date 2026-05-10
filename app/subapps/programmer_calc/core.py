from __future__ import annotations

import json

from PySide6.QtWidgets import QApplication, QStyle, QWidget

from app.core.base_subapp import BaseSubApp, CommandDef, SubAppState
from app.core.settings_store import settings_store

_HISTORY_KEY = "programmer_calc.history"
_MAX_HISTORY = 50


class ProgrammerCalcSubApp(BaseSubApp):
    id = "programmer_calc"
    name = "Calc"
    hidden = False
    _icon_char = "⌗"

    def __init__(self) -> None:
        super().__init__()
        self.icon = QApplication.style().standardIcon(QStyle.SP_ComputerIcon)
        self._panel: QWidget | None = None

    # ------------------------------------------------------------------
    # BaseSubApp contract

    def create_body(self) -> QWidget:
        from app.subapps.programmer_calc.ui import CalcPanel

        self._panel = CalcPanel(self._load_history())
        self._panel.expression_evaluated.connect(self._on_result)
        self._panel.history_cleared.connect(self._on_history_cleared)
        return self._panel

    def get_commands(self) -> list[CommandDef]:
        return [
            CommandDef("calc.clear", "Clear expression", self._clear),
            CommandDef("calc.clear_history", "Clear calculator history", self._clear_history),
        ]

    def on_activated(self) -> None:
        self.state_changed.emit(SubAppState.READY)
        self.status_changed.emit("Programmer Calculator")

    # ------------------------------------------------------------------
    # internal

    def _on_result(self, expr: str, result: int) -> None:
        history = self._load_history()
        history.insert(0, {"expr": expr, "result": result})
        history = history[:_MAX_HISTORY]
        settings_store.set(_HISTORY_KEY, json.dumps(history))

    def _on_history_cleared(self) -> None:
        settings_store.set(_HISTORY_KEY, "[]")

    def _load_history(self) -> list[dict]:
        raw = settings_store.get(_HISTORY_KEY, "[]")
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    def _clear(self) -> None:
        if self._panel:
            self._panel.clear_expression()  # type: ignore[attr-defined]

    def _clear_history(self) -> None:
        if self._panel:
            self._panel.clear_history()  # type: ignore[attr-defined]
