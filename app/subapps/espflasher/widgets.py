"""ESP Flasher specific widgets. Generic pieces live in app.ui.widgets."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QWidget

from app.subapps.espflasher.firmware import OFFSET_PRESETS, guess_offset, parse_offset
from app.ui.widgets import FileRow, ToggleSwitch, button, set_state


class ImageRow(FileRow):
    """One (offset, file) pair to write: [switch] [offset] [name / folder] [size] [📂] [✕]."""

    remove_requested = Signal(object)   # self

    def __init__(self, offset: int = 0x10000, path: str = "", enabled: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(last_dir_key="espflasher.last_dir", empty_title="No file selected",
                         empty_hint="Browse, or drop a .bin anywhere on this page",
                         parent=parent)
        self.outer.setContentsMargins(10, 8, 8, 8)

        self._enabled = ToggleSwitch()
        self._enabled.setChecked(enabled)
        self._enabled.setToolTip("Include this image when flashing")
        self._enabled.toggled.connect(self._on_enabled)
        self.row.insertWidget(0, self._enabled)

        self._offset = QComboBox()
        self._offset.setObjectName("EfOffset")
        self._offset.setEditable(True)
        for preset in OFFSET_PRESETS:
            self._offset.addItem(f"0x{preset:x}", preset)
        self._offset.setEditText(f"0x{offset:x}")
        self._offset.setFixedWidth(104)
        self._offset.setToolTip(
            "Flash address. Bootloader: 0x0 (S3/C3/C6/H2) or 0x1000 (ESP32/S2);\n"
            "partition table: 0x8000; app: usually 0x10000; merged image: 0x0.\n"
            "Suggested automatically when you pick a file."
        )
        self._offset.editTextChanged.connect(self._on_offset_text)
        self.row.insertWidget(1, self._offset)

        remove = button("✕", lambda: self.remove_requested.emit(self),
                        tip="Remove this image", name="IconBtn")
        remove.setProperty("kind", "danger")
        self.row.addWidget(remove)

        self.set_path(path, guess=False, notify=False)

    # -- state -----------------------------------------------------------

    def is_enabled(self) -> bool:
        return self._enabled.isChecked()

    def offset(self) -> int | None:
        return parse_offset(self._offset.currentText())

    def is_valid(self) -> bool:
        return self.offset() is not None and self.size() > 0

    def to_dict(self) -> dict:
        return {"offset": self._offset.currentText().strip(),
                "path": self._path, "enabled": self.is_enabled()}

    def set_path(self, path: str, *, guess: bool = True, notify: bool = True) -> None:
        self._path = path.strip().strip('"')
        p = Path(self._path)
        if guess and p.is_file():
            offset = guess_offset(p)
            if offset is not None:
                self._offset.setEditText(f"0x{offset:x}")
        self._refresh()
        if notify:
            self.changed.emit()

    # -- internals -------------------------------------------------------

    def _on_enabled(self, _on: bool) -> None:
        self._refresh()
        self.changed.emit()

    def _on_offset_text(self, _text: str) -> None:
        set_state(self._offset, "ok" if self.offset() is not None else "error")
        self.changed.emit()

    def _refresh(self) -> None:
        super()._refresh()
        if not self.is_enabled():
            for w in (self, self._size, self._name, self._dir):
                set_state(w, "disabled")
