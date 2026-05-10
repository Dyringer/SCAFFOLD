import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


def _settings_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "settings.json"
    return Path.cwd() / "settings.json"


@dataclass
class SettingDef:
    key: str
    label: str
    type: Literal["int", "str", "bool", "choice"]
    default: Any
    choices: list | None = field(default=None)


class SettingsStore:
    def __init__(self) -> None:
        self._path = _settings_path()
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @property
    def path(self) -> Path:
        return self._path

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        if self._data.get(key) == value:
            return
        self._data[key] = value
        self._save()

    def set_many(self, pairs: dict[str, Any]) -> None:
        self._data.update(pairs)
        self._save()

    def all_for_prefix(self, prefix: str) -> dict[str, Any]:
        return {k: v for k, v in self._data.items() if k.startswith(prefix)}


settings_store = SettingsStore()
