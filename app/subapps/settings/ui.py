from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QScrollArea, QSpinBox,
    QVBoxLayout, QWidget,
)

from app.core.registry import registry
from app.core.settings_store import SettingDef, settings_store


class _SettingWidget(QWidget):
    def __init__(self, defn: SettingDef) -> None:
        super().__init__()
        hl = QHBoxLayout(self)
        hl.setContentsMargins(0, 2, 0, 2)
        lbl = QLabel(defn.label)
        lbl.setFixedWidth(200)
        hl.addWidget(lbl)
        hl.addStretch()

        current = settings_store.get(defn.key, defn.default)

        if defn.type == "bool":
            ctrl = QCheckBox()
            ctrl.setChecked(bool(current))
            ctrl.toggled.connect(lambda v: settings_store.set(defn.key, v))
            hl.addWidget(ctrl)
        elif defn.type == "int":
            ctrl = QSpinBox()
            ctrl.setValue(int(current))
            ctrl.valueChanged.connect(lambda v: settings_store.set(defn.key, v))
            hl.addWidget(ctrl)
        elif defn.type == "choice" and defn.choices:
            ctrl = QComboBox()
            ctrl.addItems([str(c) for c in defn.choices])
            if current in defn.choices:
                ctrl.setCurrentIndex(defn.choices.index(current))
            ctrl.currentIndexChanged.connect(
                lambda i, d=defn: settings_store.set(d.key, d.choices[i])  # type: ignore[index]
            )
            hl.addWidget(ctrl)
        else:
            ctrl = QLineEdit(str(current))
            ctrl.textChanged.connect(lambda v: settings_store.set(defn.key, v))
            hl.addWidget(ctrl)


class SettingsHeaderWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(4)

        exp_btn = QPushButton("Export")
        exp_btn.setObjectName("HeaderCompactBtn")
        exp_btn.setFixedHeight(26)
        exp_btn.setToolTip("Export settings to a JSON file")
        exp_btn.clicked.connect(self._export)

        imp_btn = QPushButton("Import")
        imp_btn.setObjectName("HeaderCompactBtn")
        imp_btn.setFixedHeight(26)
        imp_btn.setToolTip("Import settings from a JSON file")
        imp_btn.clicked.connect(self._import)

        layout.addWidget(exp_btn)
        layout.addWidget(imp_btn)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export settings", "", "JSON (*.json)")
        if path:
            import shutil
            shutil.copy(settings_store.path, path)

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import settings", "", "JSON (*.json)")
        if not path:
            return
        try:
            import json
            from pathlib import Path
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            settings_store.set_many(data)
        except Exception as exc:
            from app.core.notification_bus import notification_bus
            notification_bus.notify.emit("error", "Import failed", str(exc))


class SettingsPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # scrollable settings area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(16, 8, 16, 16)
        self._content_layout.setSpacing(8)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._populate()

    def _populate(self) -> None:
        # App section
        self._add_section("Application", [
            SettingDef("app.theme", "Theme", "choice", "light", ["light", "dark"]),
            SettingDef("app.log_notify", "Forward log errors to notifications", "bool", False),
        ])

        # Sub-app sections
        for subapp in registry.all(include_hidden=True):
            defs = subapp.get_settings()
            self._add_section(subapp.name, defs)

        self._content_layout.addStretch()

    def _add_section(self, title: str, defs: list[SettingDef]) -> None:
        section = QWidget()
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(12, 8, 12, 10)
        section_layout.setSpacing(6)

        lbl = QLabel(title)
        lbl.setObjectName("SectionTitle")
        lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        section_layout.addWidget(lbl)

        if not defs:
            placeholder = QLabel("(no settings)")
            placeholder.setStyleSheet("color: palette(mid); padding: 2px 0;")
            section_layout.addWidget(placeholder)
        else:
            for defn in defs:
                section_layout.addWidget(_SettingWidget(defn))

        self._content_layout.addWidget(section)
