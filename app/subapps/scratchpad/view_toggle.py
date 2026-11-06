from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget


class ViewToggleBar(QWidget):
    """Two-button Edit / Preview toolbar. Emits mode_changed('edit'|'preview')."""

    mode_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # Checkable ghost buttons: the kit's :checked style is the accent pill.
        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setObjectName("SpModeBtn")
        self._edit_btn.setCheckable(True)
        self._edit_btn.setCursor(Qt.PointingHandCursor)
        self._edit_btn.setToolTip("Edit (Ctrl+E)")
        self._edit_btn.clicked.connect(lambda: self._set_mode("edit"))
        layout.addWidget(self._edit_btn)

        self._preview_btn = QPushButton("Preview")
        self._preview_btn.setObjectName("SpModeBtn")
        self._preview_btn.setCheckable(True)
        self._preview_btn.setCursor(Qt.PointingHandCursor)
        self._preview_btn.setToolTip("Preview (Ctrl+E)")
        self._preview_btn.clicked.connect(lambda: self._set_mode("preview"))
        layout.addWidget(self._preview_btn)

        self._set_mode("preview", emit=False)

    def _set_mode(self, mode: str, *, emit: bool = True) -> None:
        self._edit_btn.setChecked(mode == "edit")
        self._preview_btn.setChecked(mode == "preview")
        if emit:
            self.mode_changed.emit(mode)

    def set_mode(self, mode: str) -> None:
        """Sync button state without emitting (call when code changes the view)."""
        self._set_mode(mode, emit=False)
