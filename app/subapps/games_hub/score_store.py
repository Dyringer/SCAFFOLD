from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from app.core.resource_manager import local_dir


def _scores_path() -> Path:
    return local_dir() / "scores.json"


@dataclass
class ScoreEntry:
    player: str
    score: int
    timestamp: str  # ISO-8601

    @staticmethod
    def now(player: str, score: int) -> "ScoreEntry":
        return ScoreEntry(player=player, score=score, timestamp=datetime.now().isoformat())


class ScoreStore:
    TOP_N = 10

    def __init__(self) -> None:
        self._path = _scores_path()
        self._data: dict[str, list[dict]] = {}
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

    def submit(self, game_id: str, player: str, score: int) -> None:
        entries = self._data.setdefault(game_id, [])
        entries.append(asdict(ScoreEntry.now(player, score)))
        entries.sort(key=lambda e: e["score"], reverse=True)
        self._data[game_id] = entries[: self.TOP_N]
        self._save()

    def top(self, game_id: str, n: int = 5) -> list[ScoreEntry]:
        raw = self._data.get(game_id, [])
        return [ScoreEntry(**e) for e in raw[:n]]

    def best(self, game_id: str) -> ScoreEntry | None:
        entries = self.top(game_id, 1)
        return entries[0] if entries else None

    def reset_game(self, game_id: str) -> None:
        self._data.pop(game_id, None)
        self._save()

    def reset_all(self) -> None:
        self._data.clear()
        self._save()


score_store = ScoreStore()
