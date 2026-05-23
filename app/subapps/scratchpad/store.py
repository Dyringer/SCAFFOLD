from __future__ import annotations

import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.resource_manager import local_dir

TRASH_RETENTION_DAYS = 30


def _scratchpad_dir() -> Path:
    return local_dir() / "scratchpad"


def _legacy_path() -> Path:
    return local_dir() / "scratchpad.json"


def _slug(title: str) -> str:
    """Convert a title to a safe filename fragment (max 40 chars)."""
    s = title.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:40] or "note"


def _make_filename(title: str, created: float) -> str:
    date = datetime.fromtimestamp(created).strftime("%Y-%m-%d")
    return f"{date}_{_slug(title)}"


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


@dataclass
class Note:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    title: str = "Untitled"
    body: str = ""
    pinned: bool = False
    created: float = field(default_factory=time.time)
    modified: float = field(default_factory=time.time)
    filename: str = ""  # stem only, no extension; set once at creation


class NoteStore:
    def __init__(self) -> None:
        self._dir = _scratchpad_dir()
        self._notes_dir = self._dir / "notes"
        self._trash_dir = self._dir / "trash"
        self._index_path = self._dir / "index.json"

        self.notes: list[Note] = []
        self.active_id: str | None = None
        self.open_tabs: list[str] = []
        self.warnings: list[str] = []

        self._ensure_dirs()
        self._load()

    def _ensure_dirs(self) -> None:
        self._notes_dir.mkdir(parents=True, exist_ok=True)
        self._trash_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Filename helpers

    def _note_path(self, note: Note) -> Path:
        return self._notes_dir / f"{note.filename}.md"

    def _assign_filename(self, note: Note, exclude: set[str] | None = None) -> None:
        """Set note.filename to a unique stem based on creation date + title."""
        base = _make_filename(note.title, note.created)
        stem = base
        n = 1
        existing = {f.stem for f in self._notes_dir.glob("*.md")}
        existing |= {n2.filename for n2 in self.notes if n2.filename}
        if exclude:
            existing -= exclude
        while stem in existing:
            stem = f"{base}-{n}"
            n += 1
        note.filename = stem

    # ------------------------------------------------------------------
    # Load

    def _load(self) -> None:
        if not self._index_path.exists() and not any(self._notes_dir.glob("*.md")):
            self._migrate_legacy()
            return

        index = self._load_index()
        meta: dict[str, Any] = index.get("notes", {})
        self.active_id = index.get("active_id")
        self.open_tabs = index.get("open_tabs", [])

        # Build id→filename map from index for fast lookup.
        id_to_file: dict[str, str] = {
            nid: m.get("filename", "") for nid, m in meta.items()
        }

        seen_files: set[str] = set()
        for md_file in sorted(self._notes_dir.glob("*.md")):
            stem = md_file.stem

            if stem in seen_files:
                n = 1
                while True:
                    new_stem = f"{stem}-dup-{n}"
                    if not (self._notes_dir / f"{new_stem}.md").exists():
                        break
                    n += 1
                os.replace(md_file, self._notes_dir / f"{new_stem}.md")
                self.warnings.append(f"Duplicate file '{stem}.md' renamed to '{new_stem}.md'")
                stem = new_stem
                md_file = self._notes_dir / f"{stem}.md"

            seen_files.add(stem)

            # Find the note id whose filename matches this stem.
            note_id = next((nid for nid, fn in id_to_file.items() if fn == stem), None)
            # Fallback: old-style files where stem == id.
            if note_id is None and stem in meta:
                note_id = stem

            if note_id is None:
                # Unknown file not in index — import it with a new id.
                note_id = uuid.uuid4().hex[:12]

            try:
                body = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            m = meta.get(note_id, {})
            note = Note(
                id=note_id,
                title=m.get("title", "Untitled"),
                body=body,
                pinned=m.get("pinned", False),
                created=m.get("created", time.time()),
                modified=m.get("modified", time.time()),
                filename=stem,
            )
            self.notes.append(note)

        self._rename_legacy_id_files()
        self._purge_trash()

    def _load_index(self) -> dict[str, Any]:
        if not self._index_path.exists():
            return {}
        try:
            return json.loads(self._index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _migrate_legacy(self) -> None:
        legacy = _legacy_path()
        if not legacy.exists():
            return
        try:
            data: dict[str, Any] = json.loads(legacy.read_text(encoding="utf-8"))
        except Exception:
            return

        self.active_id = data.get("active_id")
        for raw in data.get("notes", []):
            try:
                note = Note(**{k: raw[k] for k in raw if k in Note.__dataclass_fields__})
                self._assign_filename(note)
                self.notes.append(note)
                _atomic_write(self._note_path(note), note.body)
            except Exception:
                continue

        self._save_index()
        os.replace(legacy, legacy.with_suffix(".json.migrated"))

    def _rename_legacy_id_files(self) -> None:
        """Rename any note file whose stem looks like a raw id (no date prefix)."""
        changed = False
        existing_stems = {f.stem for f in self._notes_dir.glob("*.md")}
        for note in self.notes:
            # Already has a pretty name if it contains a '-' after a date prefix.
            if re.match(r"^\d{4}-\d{2}-\d{2}_", note.filename):
                continue
            # Assign a proper filename and rename the file on disk.
            old_path = self._notes_dir / f"{note.filename}.md"
            old_stem = note.filename
            self._assign_filename(note, exclude={old_stem})  # updates note.filename in place
            existing_stems.add(note.filename)
            new_path = self._note_path(note)
            if old_path.exists():
                os.replace(old_path, new_path)
            changed = True
        if changed:
            self._save_index()

    def _purge_trash(self) -> None:
        cutoff = time.time() - TRASH_RETENTION_DAYS * 86400
        for f in list(self._trash_dir.glob("*.md")):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Index persistence

    def _save_index(self) -> None:
        meta = {
            n.id: {
                "filename": n.filename,
                "title": n.title,
                "pinned": n.pinned,
                "created": n.created,
                "modified": n.modified,
            }
            for n in self.notes
        }
        data = {"active_id": self.active_id, "open_tabs": self.open_tabs, "notes": meta}
        _atomic_write(self._index_path, json.dumps(data, indent=2, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Body persistence

    def _save_body(self, note: Note) -> None:
        _atomic_write(self._note_path(note), note.body)

    def save(self) -> None:
        """Write the index. Body writes happen via save_note()."""
        self._save_index()

    def save_note(self, note: Note) -> None:
        """Write body, rename file if title-derived filename changed, update index."""
        desired_base = _make_filename(note.title, note.created)
        # Current filename is stale if it doesn't equal the desired base and
        # doesn't look like "<desired_base>-<n>" (a collision suffix variant).
        current_base = re.sub(r"-\d+$", "", note.filename)
        if current_base != desired_base:
            old_path = self._note_path(note)
            self._assign_filename(note, exclude={note.filename})
            new_path = self._note_path(note)
            if old_path.exists() and old_path != new_path:
                os.replace(old_path, new_path)
        self._save_body(note)
        self._save_index()

    # ------------------------------------------------------------------
    # CRUD

    def get(self, note_id: str) -> Note | None:
        for n in self.notes:
            if n.id == note_id:
                return n
        return None

    def add(self, title: str = "Untitled", body: str = "") -> Note:
        note = Note(title=title, body=body)
        self._assign_filename(note)
        self.notes.append(note)
        self.active_id = note.id
        self._save_body(note)
        self._save_index()
        return note

    def remove(self, note_id: str) -> None:
        note = self.get(note_id)
        if note is None:
            return
        src = self._note_path(note)
        dst = self._trash_dir / f"{note.filename}.md"
        if src.exists():
            os.replace(src, dst)
        self.notes = [n for n in self.notes if n.id != note_id]
        if self.active_id == note_id:
            self.active_id = self.notes[0].id if self.notes else None
        self._save_index()

    def duplicate(self, note_id: str) -> Note | None:
        src = self.get(note_id)
        if not src:
            return None
        copy = Note(title=f"{src.title} (copy)", body=src.body, pinned=src.pinned)
        self._assign_filename(copy)
        idx = self.notes.index(src)
        self.notes.insert(idx + 1, copy)
        self.active_id = copy.id
        self._save_body(copy)
        self._save_index()
        return copy

    def set_pinned(self, note_id: str, pinned: bool) -> None:
        note = self.get(note_id)
        if not note:
            return
        note.pinned = pinned
        self._save_index()

    def sorted_notes(self) -> list[Note]:
        return sorted(self.notes, key=lambda n: (not n.pinned, -n.modified))

    # ------------------------------------------------------------------
    # Paths (for UI)

    def notes_folder(self) -> Path:
        return self._notes_dir
