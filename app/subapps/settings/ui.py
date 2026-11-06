from __future__ import annotations

import json
import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.notification_bus import notification_bus
from app.core.registry import registry
from app.core.settings_store import SettingDef, settings_store
from app.ui.widgets import Card, ElidedLabel, ToggleSwitch, mark_modern

# Controls sit right-aligned at a common width so the cards read as a column.
_CONTROL_WIDTH = 220


class _SettingWidget(QWidget):
    """One row: label on the left, the matching control on the right."""

    def __init__(self, defn: SettingDef) -> None:
        super().__init__()
        self.setObjectName("Plain")
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(12)
        lbl = QLabel(defn.label)
        lbl.setWordWrap(True)
        hl.addWidget(lbl, 1)

        current = settings_store.get(defn.key, defn.default)

        if defn.type == "bool":
            ctrl = ToggleSwitch()
            ctrl.setChecked(bool(current))
            ctrl.toggled.connect(lambda v: settings_store.set(defn.key, v))
        elif defn.type == "int":
            ctrl = QSpinBox()
            ctrl.setRange(-1_000_000, 1_000_000)
            ctrl.setValue(int(current))
            ctrl.setFixedWidth(_CONTROL_WIDTH)
            ctrl.valueChanged.connect(lambda v: settings_store.set(defn.key, v))
        elif defn.type == "choice" and defn.choices:
            ctrl = QComboBox()
            # choices may be [value, ...] OR [(value, display_label), ...]
            values: list = []
            labels: list[str] = []
            for c in defn.choices:
                if isinstance(c, tuple) and len(c) == 2:
                    values.append(c[0])
                    labels.append(str(c[1]))
                else:
                    values.append(c)
                    labels.append(str(c))
            ctrl.addItems(labels)
            if current in values:
                ctrl.setCurrentIndex(values.index(current))
            ctrl.setFixedWidth(_CONTROL_WIDTH)
            ctrl.currentIndexChanged.connect(
                lambda i, vs=values, d=defn: settings_store.set(d.key, vs[i])
            )
        else:
            ctrl = QLineEdit(str(current))
            ctrl.setFixedWidth(_CONTROL_WIDTH)
            ctrl.textChanged.connect(lambda v: settings_store.set(defn.key, v))
        hl.addWidget(ctrl, 0, Qt.AlignRight | Qt.AlignVCenter)


class SettingsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Settings")
        mark_modern(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setObjectName("Scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        content.setObjectName("Plain")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(0, 0, 4, 0)
        self._content_layout.setSpacing(12)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._populate()

    def _populate(self) -> None:
        self._add_section("Application", [
            SettingDef("app.theme", "Theme", "choice", "light", ["light", "dark"]),
            SettingDef("app.log_notify", "Forward log errors to notifications", "bool", False),
        ])

        # Sub-app sections (skip apps with no settings)
        for subapp in registry.all(include_hidden=True):
            defs = subapp.get_settings()
            if defs:
                self._add_section(subapp.name, defs)

        self._content_layout.addWidget(self._build_file_card())
        self._content_layout.addStretch()

    def _add_section(self, title: str, defs: list[SettingDef]) -> None:
        card = Card(title)
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        card.body.setSpacing(10)
        for defn in defs:
            card.body.addWidget(_SettingWidget(defn))
        self._content_layout.addWidget(card)

    # ------------------------------------------------------------------
    # settings file (export / import)

    def _build_file_card(self) -> QWidget:
        card = Card("Settings file")
        card.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row = QHBoxLayout()
        row.setSpacing(6)
        path = ElidedLabel(str(settings_store.path), Qt.ElideMiddle)
        path.setObjectName("Hint")
        row.addWidget(path, 1)
        exp_btn = QPushButton("Export…")
        exp_btn.setToolTip("Export settings to a JSON file")
        exp_btn.clicked.connect(self._export)
        imp_btn = QPushButton("Import…")
        imp_btn.setToolTip("Import settings from a JSON file")
        imp_btn.clicked.connect(self._import)
        for b in (exp_btn, imp_btn):
            b.setCursor(Qt.PointingHandCursor)
            row.addWidget(b)
        card.body.addLayout(row)
        return card

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "", "JSON (*.json)")
        if path:
            shutil.copy(settings_store.path, path)
            notification_bus.notify.emit("info", "Settings exported", path)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            settings_store.set_many(data)
        except Exception as exc:
            notification_bus.notify.emit("error", "Import failed", str(exc))
