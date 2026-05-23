from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Command:
    id: str
    label: str
    callback: Callable[[], None]
    shortcut: str | None = None
    when: Callable[[], bool] | None = None


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        self._commands[cmd.id] = cmd

    def all(self) -> list[Command]:
        return list(self._commands.values())

    def get(self, cmd_id: str) -> Command | None:
        return self._commands.get(cmd_id)

    def execute(self, cmd_id: str) -> None:
        cmd = self._commands.get(cmd_id)
        if cmd is None:
            return
        if cmd.when is not None and not cmd.when():
            return
        cmd.callback()
