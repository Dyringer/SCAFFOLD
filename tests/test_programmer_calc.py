from __future__ import annotations

import pytest

from app.subapps.programmer_calc.ui import CalcPanel, _evaluate, _fmt_bin, _fmt_hex


def test_evaluate_and_format():
    assert _evaluate("0x10 + 0b11 + 1") == 20
    assert _fmt_hex(255) == "0xFF"
    assert _fmt_bin(5) == "0b0101"
    with pytest.raises(ValueError):
        _evaluate("__import__('os')")
    with pytest.raises(ValueError):
        _evaluate("1 +")


def test_panel_results_error_and_history(qtbot):
    panel = CalcPanel(history=[{"expr": "1 + 1", "result": 2}])
    qtbot.addWidget(panel)
    assert panel._hist_list.count() == 1
    assert panel._hist_hint.isHidden()

    panel._input.setText("0x10 + 2")
    panel._evaluate_current()
    assert panel._dec_row._value.text() == "18"
    assert panel._hex_row._value.text() == "0x12"
    assert panel._input.property("state") in (None, "")

    panel._input.setText("1 +")
    panel._evaluate_current()
    assert panel._input.property("state") == "error"
    assert not panel._error_lbl.isHidden()

    panel._input.setText("6 * 7")
    with qtbot.waitSignal(panel.expression_evaluated) as blocker:
        panel._commit_result()
    assert blocker.args == ["6 * 7", 42]
    assert panel._hist_list.count() == 2

    # Newest first; clicking a history row restores its expression.
    newest = panel._hist_list.itemWidget(panel._hist_list.item(0))
    assert newest.expr == "6 * 7"
    panel._input.clear()
    newest.clicked.emit(newest.expr)
    assert panel._input.text() == "6 * 7"

    with qtbot.waitSignal(panel.history_cleared):
        panel.clear_history()
    assert panel._hist_list.count() == 0
    assert not panel._hist_hint.isHidden()


def test_keypad_eval_key_is_primary(qtbot):
    panel = CalcPanel(history=[])
    qtbot.addWidget(panel)
    from app.subapps.programmer_calc.ui import CalcButton
    keys = panel.findChildren(CalcButton)
    eq = [k for k in keys if k.insert_text == "__EVAL__"]
    assert len(eq) == 1 and eq[0].objectName() == "PrimaryBtn"
    ops = {k.text(): k.property("kind") for k in keys if k.objectName() == "CalcKey"}
    assert ops["+"] == "op" and ops["CLR"] == "danger" and ops["7"] == ""
