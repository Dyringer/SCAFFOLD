# ruff: noqa: RUF001, RUF003 -- keypad labels use real math glyphs (−, ×) on purpose
from __future__ import annotations

import re

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets import Card, ElidedLabel, field_label, mark_modern, set_state

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
        result = eval(expr, _SAFE_NAMES_FULL)  # restricted globals; see _BANNED
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
#
# Keys are neutral surfaces; only the category's *text* colour differs, and
# only within the minimal palette (see the "Programmer Calculator" QSS
# section): operators accent, prefixes/parens muted, CLR/← error, and "=" is
# the filled primary button.

_CAT_DIGIT   = "digit"
_CAT_HEX     = "hex"
_CAT_OP      = "op"
_CAT_BITWISE = "bitwise"
_CAT_PREFIX  = "prefix"
_CAT_ACTION  = "action"
_CAT_PAREN   = "paren"

# category -> QSS `kind` of #CalcKey
_CAT_KIND: dict[str, str] = {
    _CAT_DIGIT:   "",
    _CAT_HEX:     "",
    _CAT_OP:      "op",
    _CAT_BITWISE: "op",
    _CAT_PREFIX:  "muted",
    _CAT_PAREN:   "muted",
    _CAT_ACTION:  "danger",
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
        self.setFixedHeight(46)
        self.setMinimumWidth(44)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if insert == "__EVAL__":
            self.setObjectName("PrimaryBtn")
        else:
            self.setObjectName("CalcKey")
            self.setProperty("kind", _CAT_KIND.get(category, ""))

    @property
    def insert_text(self) -> str:
        return self._insert


# ---------------------------------------------------------------------------
# ResultRow
# ---------------------------------------------------------------------------


class ResultRow(QWidget):
    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Plain")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(12)

        lbl = field_label(label)
        lbl.setFixedWidth(34)

        self._value = QLabel("—")
        self._value.setObjectName("CalcValue")
        self._value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self._copy_btn = QPushButton("Copy")
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
    """Two-line history row (expression / = result) for the history list."""

    clicked = Signal(str)

    def __init__(self, expr: str, result: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PortItem")      # kit list-row: transparent, padded
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(1)

        expr_lbl = ElidedLabel(expr, Qt.ElideRight)
        expr_lbl.setObjectName("CalcHistExpr")
        result_lbl = ElidedLabel(f"= {result}   ·   {_fmt_hex(result)}", Qt.ElideRight)
        result_lbl.setObjectName("CalcHistResult")
        layout.addWidget(expr_lbl)
        layout.addWidget(result_lbl)

        self._expr = expr
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Click to restore expression")

    @property
    def expr(self) -> str:
        return self._expr

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.clicked.emit(self._expr)
        super().mousePressEvent(event)


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
        self.setObjectName("Plain")
        grid = QGridLayout(self)
        grid.setSpacing(6)
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
        self.setObjectName("ProgrammerCalc")
        mark_modern(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(12)
        splitter.addWidget(self._build_main())
        splitter.addWidget(self._build_history())
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 300])
        outer.addWidget(splitter, 1)

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

        self._update_history_hint()
        self._input.setFocus()

    # ------------------------------------------------------------------
    # construction

    def _build_main(self) -> QWidget:
        col = QWidget()
        col.setObjectName("Plain")
        lay = QVBoxLayout(col)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        expr_card = Card("Expression")
        self._input = QLineEdit()
        self._input.setObjectName("CalcInput")
        self._input.setPlaceholderText("e.g.  10 + 0x42 + 0b1101")
        expr_card.body.addWidget(self._input)

        self._error_lbl = QLabel("")
        self._error_lbl.setObjectName("StatusText")
        set_state(self._error_lbl, "error")
        self._error_lbl.setVisible(False)
        expr_card.body.addWidget(self._error_lbl)

        self._dec_row = ResultRow("DEC")
        self._hex_row = ResultRow("HEX")
        self._bin_row = ResultRow("BIN")
        for row in (self._dec_row, self._hex_row, self._bin_row):
            expr_card.body.addWidget(row)
        lay.addWidget(expr_card)

        keypad_card = Card("Keypad")
        self._keypad = Keypad()
        self._keypad.key_pressed.connect(self._on_key)
        keypad_card.body.addWidget(self._keypad)
        lay.addWidget(keypad_card)
        lay.addStretch(1)
        return col

    def _build_history(self) -> QWidget:
        card = Card("History")
        clr_hist_btn = QPushButton("Clear")
        clr_hist_btn.clicked.connect(self._on_clear_history)
        clr_hist_btn.setCursor(Qt.PointingHandCursor)
        card.header.addWidget(clr_hist_btn)

        self._hist_list = QListWidget()
        self._hist_list.setObjectName("PortList")
        self._hist_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        card.body.addWidget(self._hist_list, 1)

        self._hist_hint = QLabel("No calculations yet.\nPress Enter or = to keep a result.")
        self._hist_hint.setObjectName("Hint")
        self._hist_hint.setAlignment(Qt.AlignCenter)
        card.body.addWidget(self._hist_hint, 1)
        return card

    def _update_history_hint(self) -> None:
        has = self._hist_list.count() > 0
        self._hist_list.setVisible(has)
        self._hist_hint.setVisible(not has)

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
            self._error_lbl.setText(f"⚠ {exc}")
            self._error_lbl.setVisible(True)
            set_state(self._input, "error")
            self._last_result = None
            return

        self._error_lbl.setVisible(False)
        set_state(self._input, "")
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
        item = QListWidgetItem()
        item.setSizeHint(entry.sizeHint())
        self._hist_list.insertItem(0, item)
        self._hist_list.setItemWidget(item, entry)
        self._update_history_hint()

    def _on_history_clicked(self, expr: str) -> None:
        self._input.setText(expr)
        self._input.setCursorPosition(len(expr))
        self._input.setFocus()

    def _on_clear_history(self) -> None:
        self._hist_list.clear()
        self._update_history_hint()
        self.history_cleared.emit()
