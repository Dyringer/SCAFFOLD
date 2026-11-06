"""Shared "modern" widget kit (cards, job/output cards, file rows, toggle
switches, port entries).

Used by subapps that opt into the modern look by calling `mark_modern(root)`
on their top-level panel. All colours come from the theme QSS — see the
"Modern widget kit" section of app/resources/themes/*.qss, whose rules are
scoped to `*[modern="true"]`. Widgets here only set object names and dynamic
`state` / `kind` properties; ToggleSwitch paints itself, so its colours are
exposed as Qt properties the QSS sets via `qproperty-*`.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.core.settings_store import settings_store


def mark_modern(widget: QWidget) -> None:
    """Opt `widget` and its descendants into the modern QSS rules."""
    widget.setProperty("modern", True)


def repolish(widget: QWidget) -> None:
    """Re-apply QSS after a dynamic property change."""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


def set_state(widget: QWidget, state: str) -> None:
    """Set the `state` property QSS keys off, repolishing only on change."""
    if widget.property("state") != state:
        widget.setProperty("state", state)
        repolish(widget)


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    return f"{n / (1024 * 1024):.2f} MiB"


def field_label(text: str) -> QLabel:
    """Small muted caption placed above/next to an input."""
    lbl = QLabel(text)
    lbl.setObjectName("FieldLabel")
    return lbl


def badge(text: str, kind: str = "") -> QLabel:
    """Small rounded pill label. `kind` selects its colour in QSS."""
    lbl = QLabel(text)
    lbl.setObjectName("Badge")
    lbl.setProperty("kind", kind)
    return lbl


def button(text: str, slot: Callable | None = None, *, tip: str = "",
           name: str = "") -> QPushButton:
    """Push button with a pointing-hand cursor; `name` sets the QSS object name."""
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    btn.setCursor(Qt.PointingHandCursor)
    if tip:
        btn.setToolTip(tip)
    if slot is not None:
        btn.clicked.connect(slot)
    return btn


# ---------------------------------------------------------------------------


class Card(QFrame):
    """Rounded section with an uppercase title row (`header`) and a body (`body`).

    Pass title="" for a bare card with no header row.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None,
                 *, margins: tuple[int, int, int, int] = (14, 12, 14, 14)) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(*margins)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        if title:
            title_lbl = QLabel(title.upper())
            title_lbl.setObjectName("CardTitle")
            self.header.addWidget(title_lbl)
            self.header.addStretch(1)
            outer.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(8)
        outer.addLayout(self.body, 1)


class HeroCard(Card):
    """Job status card: big stage title, detail line, percent, Cancel/start
    buttons and a slim progress bar. Callers add option rows to `body`."""

    def __init__(self, title: str, start_text: str, on_start: Callable,
                 on_cancel: Callable, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        top = QHBoxLayout()
        top.setSpacing(12)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.stage = QLabel("Ready")
        self.stage.setObjectName("HeroStage")
        self.detail = QLabel("")
        self.detail.setObjectName("HeroDetail")
        text.addWidget(self.stage)
        text.addWidget(self.detail)
        top.addLayout(text, 1)
        self.percent = QLabel("")
        self.percent.setObjectName("HeroPercent")
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.percent)
        self.cancel_btn = button("Cancel", on_cancel)
        top.addWidget(self.cancel_btn)
        self.start_btn = button(start_text, on_start, name="PrimaryBtn")
        top.addWidget(self.start_btn)
        self.body.addLayout(top)

        self.progress = QProgressBar()
        self.progress.setObjectName("HeroProgress")
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.body.addWidget(self.progress)

    def is_idle(self) -> bool:
        return self.stage.property("state") in (None, "idle")

    def set(self, title: str, detail: str, state: str) -> None:
        """Stage title + detail; `state` (idle/busy/ok/error) colours the title."""
        self.stage.setText(title)
        self.detail.setText(detail)
        set_state(self.stage, state)
        if state == "idle":
            self.percent.setText("")

    def begin(self, title: str, detail: str) -> None:
        """Enter the running state with a busy bar until the first set_percent()."""
        self.set_busy()
        set_state(self.progress, "busy")
        self.set(title, detail, "busy")

    def set_busy(self) -> None:
        """Indeterminate bar (no byte count for the current step)."""
        self.progress.setRange(0, 0)
        self.percent.setText("")

    def set_percent(self, percent: int) -> None:
        if self.progress.maximum() == 0:
            self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        self.percent.setText(f"{percent}%")

    def finish(self, state: str) -> None:
        """Settle the bar: full on "ok"; otherwise keep how far the job got
        (a busy bar resets to empty)."""
        busy = self.progress.maximum() == 0
        self.progress.setRange(0, 100)
        if state == "ok":
            self.set_percent(100)
        elif busy:
            self.progress.setValue(0)
            self.percent.setText("")
        set_state(self.progress, state)


class OutputCard(Card):
    """Read-only console with Copy and Show/Hide (visibility kept in settings)."""

    def __init__(self, visible_key: str, *, max_lines: int = 5000, min_height: int = 140,
                 parent: QWidget | None = None) -> None:
        super().__init__("Output", parent)
        self._visible_key = visible_key
        self.header.addWidget(button(
            "Copy", lambda: QGuiApplication.clipboard().setText(self.console.toPlainText())))
        self._toggle = button("", lambda: self._set_shown(not self.console.isVisibleTo(self)))
        self.header.addWidget(self._toggle)

        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 9))
        self.console.setMaximumBlockCount(max_lines)
        self.console.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.console.setMinimumHeight(min_height)
        self.body.addWidget(self.console, 1)
        self._set_shown(bool(settings_store.get(visible_key, True)))

    def append(self, text: str) -> None:
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.console.setTextCursor(cursor)
        self.console.ensureCursorVisible()

    def clear(self) -> None:
        self.console.clear()

    def _set_shown(self, shown: bool) -> None:
        self.console.setVisible(shown)
        self._toggle.setText("Hide" if shown else "Show")
        settings_store.set(self._visible_key, shown)


_FIRMWARE_FILTER = "Firmware images (*.bin);;All files (*)"


class FileRow(QFrame):
    """[name / folder · date] [size] [📂] — one chosen file.

    `row` is the horizontal layout (inside the vertical `outer`), so
    subclasses can add controls around the file text. They override
    `_file_state()` to refine the "ok" state.
    """

    changed = Signal()

    def __init__(self, *, last_dir_key: str, empty_title: str, empty_hint: str,
                 browse_tip: str = "Choose file…",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FileRow")
        self._path = ""
        self._last_dir_key = last_dir_key
        self._empty = (empty_title, empty_hint)

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(12, 8, 8, 8)
        self.outer.setSpacing(4)
        self.row = QHBoxLayout()
        self.row.setSpacing(10)
        text = QVBoxLayout()
        text.setSpacing(0)
        self._name = ElidedLabel("", Qt.ElideMiddle)
        self._name.setObjectName("FileName")
        self._dir = ElidedLabel("", Qt.ElideMiddle)
        self._dir.setObjectName("FileDir")
        text.addWidget(self._name)
        text.addWidget(self._dir)
        self.row.addLayout(text, 1)
        self._size = badge("", "size")
        self.row.addWidget(self._size)
        self.row.addWidget(button("📂", self._browse, tip=browse_tip, name="IconBtn"))
        self.outer.addLayout(self.row)

    def path(self) -> str:
        return self._path

    def size(self) -> int:
        """Current size in bytes (0 if empty or missing)."""
        try:
            return Path(self._path).stat().st_size if self._path else 0
        except OSError:
            return 0

    def set_path(self, path: str) -> None:
        self._path = path.strip().strip('"')
        self._refresh()
        self.changed.emit()

    def _file_state(self, _path: Path) -> str:
        return "ok"

    def _refresh(self) -> None:
        p = Path(self._path)
        if not self._path:
            self._name.set_full_text(self._empty[0])
            self._dir.set_full_text(self._empty[1])
            self._size.hide()
            state = "empty"
        elif not p.is_file():
            self._name.set_full_text(p.name)
            self._dir.set_full_text(f"Not found: {p.parent}")
            self._size.setText("missing")
            self._size.show()
            state = "missing"
        else:
            st = p.stat()
            modified = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            self._name.set_full_text(p.name)
            self._dir.set_full_text(f"{p.parent}  ·  {modified}")
            self._size.setText(human_size(st.st_size))
            self._size.show()
            state = self._file_state(p)
        for w in (self, self._size, self._name, self._dir):
            set_state(w, state)

    def _browse(self) -> None:
        current = Path(self._path)
        start = current.parent if self._path and current.parent.is_dir() else Path(
            str(settings_store.get(self._last_dir_key, Path.home())))
        path, _ = QFileDialog.getOpenFileName(self, "Select firmware", str(start),
                                              _FIRMWARE_FILTER)
        if path:
            settings_store.set(self._last_dir_key, str(Path(path).parent))
            self.set_path(path)


class ElidedLabel(QLabel):
    """QLabel that elides its text to the available width (full text in tooltip)."""

    def __init__(self, text: str = "", mode: Qt.TextElideMode = Qt.ElideMiddle,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self._mode = mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(20)
        self._elide()

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, self._mode, self.width()))
        self.setToolTip(self._full if self.text() != self._full else "")


class ToggleSwitch(QCheckBox):
    """iOS-style switch. Drop-in QCheckBox; colours via qproperty-* in QSS."""

    _TRACK_W, _TRACK_H, _GAP = 34, 18, 8

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._track_on = QColor("#4ea1f3")
        self._track_off = QColor("#5a5a5a")
        self._knob = QColor("#ffffff")
        self._pos = 0.0
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self.toggled.connect(self._animate)

    # -- QSS-settable colours -------------------------------------------
    def _get_on(self) -> QColor:
        return self._track_on

    def _set_on(self, c: QColor) -> None:
        self._track_on = QColor(c)
        self.update()

    def _get_off(self) -> QColor:
        return self._track_off

    def _set_off(self, c: QColor) -> None:
        self._track_off = QColor(c)
        self.update()

    def _get_knob(self) -> QColor:
        return self._knob

    def _set_knob(self, c: QColor) -> None:
        self._knob = QColor(c)
        self.update()

    def _get_pos(self) -> float:
        return self._pos

    def _set_pos(self, v: float) -> None:
        self._pos = v
        self.update()

    trackOn = Property(QColor, _get_on, _set_on)       # noqa: N815 (Qt property name)
    trackOff = Property(QColor, _get_off, _set_off)    # noqa: N815
    knob = Property(QColor, _get_knob, _set_knob)
    knobPos = Property(float, _get_pos, _set_pos)      # noqa: N815

    def setChecked(self, on: bool) -> None:  # noqa: N802 (Qt override)
        # Programmatic changes jump straight to the end state (no animation).
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _animate(self, on: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    # -- geometry / painting --------------------------------------------
    def sizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        text_w = self.fontMetrics().horizontalAdvance(self.text()) if self.text() else 0
        gap = self._GAP if self.text() else 0
        h = max(self._TRACK_H, self.fontMetrics().height()) + 4
        return QSize(self._TRACK_W + gap + text_w + 2, h)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 (Qt override)
        return self.sizeHint()

    def hitButton(self, pos) -> bool:  # noqa: N802 (Qt override)
        return self.rect().contains(pos)

    def paintEvent(self, _event) -> None:  # noqa: N802 (Qt override)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            p.setOpacity(0.45)
        y = (self.height() - self._TRACK_H) / 2
        track = QRectF(1, y, self._TRACK_W, self._TRACK_H)
        off, on = self._track_off, self._track_on
        t = self._pos
        color = QColor(
            int(off.red() + (on.red() - off.red()) * t),
            int(off.green() + (on.green() - off.green()) * t),
            int(off.blue() + (on.blue() - off.blue()) * t),
        )
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(track, self._TRACK_H / 2, self._TRACK_H / 2)
        d = self._TRACK_H - 4
        x = track.left() + 2 + (self._TRACK_W - d - 4) * t
        p.setBrush(self._knob)
        p.drawEllipse(QRectF(x, y + 2, d, d))
        if self.text():
            p.setPen(self.palette().color(self.foregroundRole()))
            text_rect = self.rect().adjusted(self._TRACK_W + self._GAP + 1, 0, 0, 0)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, self.text())


class PortItem(QWidget):
    """Two-line serial-port entry for a QListWidget (via setItemWidget).

    [● ] NAME            [badge] [badge]
         description

    `status` colours the leading dot via QSS: "live" (connected, shown),
    "open" (connected in background) or "" (no dot).
    """

    def __init__(self, name: str, desc: str, badges: list[tuple[str, str]] | None = None,
                 status: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PortItem")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        if status:
            dot = QLabel("●")
            dot.setObjectName("PortDot")
            dot.setProperty("state", status)
            top.addWidget(dot)
        name_lbl = QLabel(name)
        name_lbl.setObjectName("PortName")
        top.addWidget(name_lbl)
        top.addStretch(1)
        for text, kind in badges or []:
            top.addWidget(badge(text, kind))
        lay.addLayout(top)
        desc_lbl = ElidedLabel(desc or "Serial port", Qt.ElideRight)
        desc_lbl.setObjectName("PortDesc")
        lay.addWidget(desc_lbl)
