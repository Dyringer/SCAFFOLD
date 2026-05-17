from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from app.core.resource_manager import local_dir


def _store_path() -> Path:
    return local_dir() / "scratchpad.json"


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Untitled"
    body: str = ""
    pinned: bool = False
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)


class NoteStore:
    def __init__(self) -> None:
        self._path = _store_path()
        self.notes: list[Note] = []
        self.active_id: str | None = None
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data: dict[str, Any] = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            return
        for raw in data.get("notes", []):
            try:
                self.notes.append(Note(**{k: raw[k] for k in raw if k in Note.__annotations__}))
            except Exception:
                continue
        self.active_id = data.get("active_id")

    def save(self) -> None:
        data = {
            "notes": [asdict(n) for n in self.notes],
            "active_id": self.active_id,
        }
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get(self, note_id: str) -> Note | None:
        for n in self.notes:
            if n.id == note_id:
                return n
        return None

    def add(self, title: str = "Untitled", body: str = "") -> Note:
        note = Note(title=title, body=body)
        self.notes.append(note)
        self.active_id = note.id
        self.save()
        return note

    def remove(self, note_id: str) -> None:
        self.notes = [n for n in self.notes if n.id != note_id]
        if self.active_id == note_id:
            self.active_id = self.notes[0].id if self.notes else None
        self.save()

    def duplicate(self, note_id: str) -> Note | None:
        src = self.get(note_id)
        if not src:
            return None
        copy = Note(title=f"{src.title} (copy)", body=src.body, pinned=src.pinned)
        idx = self.notes.index(src)
        self.notes.insert(idx + 1, copy)
        self.active_id = copy.id
        self.save()
        return copy

    def touch(self, note_id: str, *, title: str | None = None, body: str | None = None) -> None:
        note = self.get(note_id)
        if not note:
            return
        if title is not None:
            note.title = title
        if body is not None:
            note.body = body
        note.modified = time.time()
        self.save()

    def set_pinned(self, note_id: str, pinned: bool) -> None:
        note = self.get(note_id)
        if not note:
            return
        note.pinned = pinned
        self.save()

    def sorted_notes(self) -> list[Note]:
        return sorted(self.notes, key=lambda n: (not n.pinned, -n.modified))
