from __future__ import annotations

import re

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

# ---------------------------------------------------------------------------
# Evaluation helpers
# ---------------------------------------------------------------------------

_ALLOWED_NAMES = {"abs": abs, "min": min, "max": max}
_SAFE_NAMES_FULL = {"__builtins__": {}, **_ALLOWED_NAMES}
_BANNED = re.compile(r"\b(import|exec|eval|open|os|sys|__)\b")

UINT64_MASK = (1 << 64) - 1


def _evaluate(expr: str) -> int:
    expr = expr.strip()
    if not expr:
        raise ValueError("empty")
    if _BANNED.search(expr):
        raise ValueError("disallowed token")
    try:
        result = eval(expr, _SAFE_NAMES_FULL)  # noqa: S307
    except Exception as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(result, int):
        raise ValueError("result is not an integer")
    return result


def _fmt_bin(value: int) -> str:
    bits = format(value & UINT64_MASK if value < 0 else value, "b")
    pad = (4 - len(bits) % 4) % 4
    bits = "0" * pad + bits
    return "0b" + " ".join(bits[i : i + 4] for i in range(0, len(bits), 4))


def _fmt_hex(value: int) -> str:
    return f"0x{value & UINT64_MASK:X}" if value < 0 else f"0x{value:X}"


def _fmt_dec(value: int) -> str:
    return str(value)


# ---------------------------------------------------------------------------
# CalcButton
# ---------------------------------------------------------------------------

_CAT_DIGIT   = "digit"
_CAT_HEX     = "hex"
_CAT_OP      = "op"
_CAT_BITWISE = "bitwise"
_CAT_PREFIX  = "prefix"
_CAT_ACTION  = "action"
_CAT_PAREN   = "paren"

# Each entry: (light-bg, light-fg, dark-bg, dark-fg)
_CAT_COLORS: dict[str, tuple[str, str, str, str]] = {
    _CAT_DIGIT:   ("#e8e8e8", "#111111", "#2a2a2a", "#e0e0e0"),
    _CAT_HEX:     ("#cce0ff", "#004080", "#1a3a5c", "#4a9eff"),
    _CAT_OP:      ("#ffe8c0", "#7a4000", "#2d1a00", "#e8a020"),
    _CAT_BITWISE: ("#d4f0c0", "#2a5a00", "#1a2d00", "#78c832"),
    _CAT_PREFIX:  ("#f0d0f0", "#6a006a", "#2d002d", "#c864c8"),
    _CAT_ACTION:  ("#ffd0d0", "#800000", "#3a0000", "#e05050"),
    _CAT_PAREN:   ("#ddddf8", "#333388", "#1a1a2d", "#8888cc"),
}


class CalcButton(QPushButton):
    def __init__(
        self,
        label: str,
        insert: str,
        category: str = _CAT_DIGIT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(label.replace("&", "&&"), parent)
        self._insert = insert
        self.setFixedHeight(44)
        self.setMinimumWidth(44)
        self.setFont(QFont("Consolas", 13))
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        colors = _CAT_COLORS.get(category, ("#e0e0e0", "#111", "#2a2a2a", "#eee"))
        is_dark = QApplication.palette().color(QPalette.Window).lightness() < 128
        bg, fg = (colors[2], colors[3]) if is_dark else (colors[0], colors[1])
        self.setStyleSheet(
            f"QPushButton {{ border-radius: 6px; padding: 4px 2px;"
            f" background-color: {bg}; color: {fg}; }}"
            f"QPushButton:hover {{ background-color: {bg}dd; }}"
            f"QPushButton:pressed {{ background-color: {bg}99; }}"
        )

    @property
    def insert_text(self) -> str:
        return self._insert


# ---------------------------------------------------------------------------
# ResultRow
# ---------------------------------------------------------------------------


class ResultRow(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(10)

        lbl = QLabel(label)
        lbl.setFixedWidth(36)
        lbl.setFont(QFont("Consolas", 11))
        lbl.setStyleSheet("font-weight: 700; color: #888;")

        self._value = QLabel("—")
        self._value.setFont(QFont("Consolas", 14))
        self._value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._copy_btn = QPushButton("Copy")
        self._copy_btn.setFixedWidth(54)
        self._copy_btn.setEnabled(False)
        self._copy_btn.clicked.connect(self._copy)
        self._copy_btn.setCursor(Qt.PointingHandCursor)

        layout.addWidget(lbl)
        layout.addWidget(self._value)
        layout.addWidget(self._copy_btn)

        self._current: str = ""

    def set_value(self, text: str) -> None:
        self._current = text
        self._value.setText(text)
        self._copy_btn.setEnabled(True)

    def clear(self) -> None:
        self._current = ""
        self._value.setText("—")
        self._copy_btn.setEnabled(False)

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self._current)


# ---------------------------------------------------------------------------
# HistoryEntry
# ---------------------------------------------------------------------------


class HistoryEntry(QWidget):
    clicked = Signal(str)

    def __init__(self, expr: str, result: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)

        text = f"{expr}  =  {result}"
        lbl = QLabel(text)
        lbl.setFont(QFont("Consolas", 12))
        lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        layout.addWidget(lbl)

        self._expr = expr
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to restore expression")

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        self.clicked.emit(self._expr)


# ---------------------------------------------------------------------------
# Keypad
# ---------------------------------------------------------------------------
#
# 8 columns, 5 rows.
#
# Number block (cols 0–3): 4×4, ascending left-to-right bottom-to-top.
# Row 4 is the bottom — lowest values. Row 0 is the top — highest values.
#
#  col:  0    1    2    3  ‖   4    5    6    7
#  r0:   C    D    E    F  ‖   /   <<   0b   ←
#  r1:   8    9    A    B  ‖   ×   >>   0x  CLR
#  r2:   4    5    6    7  ‖   −    &    (    )
#  r3:   0    1    2    3  ‖   +    |    ~    ^
#  r4:   .   [.]   %   [%] ‖  [=   =    =    =]

_KEYPAD: list[tuple[int, int, int, int, str, str, str]] = [
    # (row, col, rowspan, colspan, label, insert, category)

    # -- number block: 0-9 ascending L-R bottom-to-top --
    (3, 0, 1, 1, "0",   "0",   _CAT_DIGIT),
    (3, 1, 1, 1, "1",   "1",   _CAT_DIGIT),
    (3, 2, 1, 1, "2",   "2",   _CAT_DIGIT),
    (3, 3, 1, 1, "3",   "3",   _CAT_DIGIT),
    (2, 0, 1, 1, "4",   "4",   _CAT_DIGIT),
    (2, 1, 1, 1, "5",   "5",   _CAT_DIGIT),
    (2, 2, 1, 1, "6",   "6",   _CAT_DIGIT),
    (2, 3, 1, 1, "7",   "7",   _CAT_DIGIT),
    (1, 0, 1, 1, "8",   "8",   _CAT_DIGIT),
    (1, 1, 1, 1, "9",   "9",   _CAT_DIGIT),

    # -- hex A-F continuing the same pattern --
    (1, 2, 1, 1, "A",   "0xA", _CAT_HEX),
    (1, 3, 1, 1, "B",   "0xB", _CAT_HEX),
    (0, 0, 1, 1, "C",   "0xC", _CAT_HEX),
    (0, 1, 1, 1, "D",   "0xD", _CAT_HEX),
    (0, 2, 1, 1, "E",   "0xE", _CAT_HEX),
    (0, 3, 1, 1, "F",   "0xF", _CAT_HEX),

    # -- bottom row extras --
    (4, 0, 1, 2, ".",   ".",   _CAT_DIGIT),  # wide dot
    (4, 2, 1, 2, "%",   " % ", _CAT_OP),     # wide %

    # -- arithmetic col 4 --
    (0, 4, 1, 1, "/",   " / ", _CAT_OP),
    (1, 4, 1, 1, "×",   " * ", _CAT_OP),
    (2, 4, 1, 1, "−",   " - ", _CAT_OP),
    (3, 4, 1, 1, "+",   " + ", _CAT_OP),

    # -- bitwise col 5 --
    (0, 5, 1, 1, "<<",  " << ", _CAT_BITWISE),
    (1, 5, 1, 1, ">>",  " >> ", _CAT_BITWISE),
    (2, 5, 1, 1, "&",   " & ",  _CAT_BITWISE),
    (3, 5, 1, 1, "|",   " | ",  _CAT_BITWISE),
    (2, 7, 1, 1, "^",   " ^ ",  _CAT_BITWISE),
    (1, 7, 1, 1, "~",   "~",    _CAT_BITWISE),

    # -- prefixes col 6 --
    (0, 6, 1, 1, "0b",  "0b",  _CAT_PREFIX),
    (1, 6, 1, 1, "0x",  "0x",  _CAT_PREFIX),

    # -- parens --
    (2, 6, 1, 1, "(",   "(",   _CAT_PAREN),
    (3, 6, 1, 1, ")",   ")",   _CAT_PAREN),

    # -- actions --
    (0, 7, 1, 1, "←",   "__BACKSPACE__", _CAT_ACTION),
    (3, 7, 1, 1, "CLR", "__CLR__",       _CAT_ACTION),
    (4, 4, 1, 4, "=",   "__EVAL__",      _CAT_ACTION),
]


class Keypad(QWidget):
    key_pressed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        grid = QGridLayout(self)
        grid.setSpacing(5)
        grid.setContentsMargins(0, 0, 0, 0)

        for row, col, rs, cs, label, insert, cat in _KEYPAD:
            btn = CalcButton(label, insert, cat)
            btn.clicked.connect(lambda _checked=False, ins=insert: self.key_pressed.emit(ins))
            grid.addWidget(btn, row, col, rs, cs)

        for c in range(8):
            grid.setColumnStretch(c, 1)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


# ---------------------------------------------------------------------------
# CalcPanel
# ---------------------------------------------------------------------------


class CalcPanel(QWidget):
    expression_evaluated = Signal(str, int)
    history_cleared = Signal()

    def __init__(self, history: list[dict], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # -- expression input --
        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g.  10 + 0x42 + 0b1101")
        self._input.setFont(QFont("Consolas", 16))
        self._input.setFixedHeight(44)
        self._input.setStyleSheet("padding: 6px 10px;")
        root.addWidget(self._input)

        # -- error label --
        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #c0392b; font-size: 12px; padding: 0 4px;")
        self._error_lbl.setVisible(False)
        root.addWidget(self._error_lbl)

        # -- result rows --
        result_frame = QFrame()
        result_frame.setFrameShape(QFrame.StyledPanel)
        rf = QVBoxLayout(result_frame)
        rf.setContentsMargins(10, 6, 10, 6)
        rf.setSpacing(2)
        self._dec_row = ResultRow("DEC")
        self._hex_row = ResultRow("HEX")
        self._bin_row = ResultRow("BIN")
        for row in (self._dec_row, self._hex_row, self._bin_row):
            rf.addWidget(row)
        root.addWidget(result_frame)

        # -- history (above keypad, grows with window height) --
        hist_header = QHBoxLayout()
        hist_lbl = QLabel("History")
        hist_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        clr_hist_btn = QPushButton("Clear")
        clr_hist_btn.setFixedWidth(54)
        clr_hist_btn.clicked.connect(self._on_clear_history)
        clr_hist_btn.setCursor(Qt.PointingHandCursor)
        hist_header.addWidget(hist_lbl)
        hist_header.addStretch()
        hist_header.addWidget(clr_hist_btn)
        root.addLayout(hist_header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._hist_container = QWidget()
        self._hist_layout = QVBoxLayout(self._hist_container)
        self._hist_layout.setAlignment(Qt.AlignTop)
        self._hist_layout.setContentsMargins(0, 0, 0, 0)
        self._hist_layout.setSpacing(1)
        scroll.setWidget(self._hist_container)
        scroll.setMinimumHeight(60)
        root.addWidget(scroll, stretch=1)  # takes all extra vertical space

        # -- keypad (fixed height, below history) --
        self._keypad = Keypad()
        self._keypad.key_pressed.connect(self._on_key)
        root.addWidget(self._keypad)

        # -- debounce --
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._evaluate_current)
        self._input.textChanged.connect(lambda _: self._timer.start())
        self._input.returnPressed.connect(self._commit_result)

        self._last_result: int | None = None

        for entry in history:
            self._prepend_history_entry(entry["expr"], entry["result"])

        self._input.setFocus()

    # ------------------------------------------------------------------
    # public API

    def clear_expression(self) -> None:
        self._input.clear()

    def clear_history(self) -> None:
        self._on_clear_history()

    # ------------------------------------------------------------------
    # keypad handler

    def _on_key(self, token: str) -> None:
        if token == "__CLR__":
            self._input.clear()
            return
        if token == "__BACKSPACE__":
            text = self._input.text()
            stripped = text.rstrip()
            self._input.setText(stripped if stripped != text else text[:-1])
            self._input.setFocus()
            return
        if token == "__EVAL__":
            self._commit_result()
            return
        pos = self._input.cursorPosition()
        text = self._input.text()
        self._input.setText(text[:pos] + token + text[pos:])
        self._input.setCursorPosition(pos + len(token))
        self._input.setFocus()

    # ------------------------------------------------------------------
    # evaluation

    def _evaluate_current(self) -> None:
        expr = self._input.text().strip()
        if not expr:
            self._clear_results()
            self._error_lbl.setVisible(False)
            self._last_result = None
            return
        try:
            result = _evaluate(expr)
        except ValueError as exc:
            self._clear_results()
            self._error_lbl.setText(str(exc))
            self._error_lbl.setVisible(True)
            self._input.setStyleSheet(
                "font-family: Consolas; font-size: 16px; padding: 6px 10px;"
                " border: 1px solid #c0392b;"
            )
            self._last_result = None
            return

        self._error_lbl.setVisible(False)
        self._input.setStyleSheet("font-family: Consolas; font-size: 16px; padding: 6px 10px;")
        self._last_result = result
        self._dec_row.set_value(_fmt_dec(result))
        self._hex_row.set_value(_fmt_hex(result))
        self._bin_row.set_value(_fmt_bin(result))

    def _commit_result(self) -> None:
        self._evaluate_current()
        expr = self._input.text().strip()
        if self._last_result is not None and expr:
            self.expression_evaluated.emit(expr, self._last_result)
            self._prepend_history_entry(expr, self._last_result)

    def _clear_results(self) -> None:
        for row in (self._dec_row, self._hex_row, self._bin_row):
            row.clear()

    def _prepend_history_entry(self, expr: str, result: int) -> None:
        entry = HistoryEntry(expr, result)
        entry.clicked.connect(self._on_history_clicked)
        self._hist_layout.insertWidget(0, entry)

    def _on_history_clicked(self, expr: str) -> None:
        self._input.setText(expr)
        self._input.setCursorPosition(len(expr))
        self._input.setFocus()

    def _on_clear_history(self) -> None:
        while self._hist_layout.count():
            item = self._hist_layout.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()
        self.history_cleared.emit()
