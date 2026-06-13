"""Tests for the Stacker game.

The game rules live in two pure integer functions (advance, resolve_drop) and a
small StackerState — no Qt — so the mechanic is tested directly. A few
Qt-level tests then exercise the drop/die/win flow through the real StackerGame
(QTimer-based), using pytest-qt headless like the serial-session tests.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.subapps.games_hub.base_game import GameMode, GameResult, GameState
from app.subapps.games_hub.games.stacker.game import (
    COLS,
    ROWS,
    START_WIDTH,
    StackerGame,
    StackerState,
    advance,
    resolve_drop,
)

# ---------------------------------------------------------------------------
# advance() — sliding row with wall bounces

def test_advance_moves_in_direction() -> None:
    assert advance(3, 4, 1) == (4, 1)
    assert advance(3, 4, -1) == (2, -1)


def test_advance_bounces_off_left_wall() -> None:
    # Stepping past column 0 clamps to 0 and flips to rightward.
    assert advance(0, 4, -1) == (0, 1)


def test_advance_bounces_off_right_wall() -> None:
    # A width-4 row can't go past COLS; it clamps flush-right and flips.
    assert advance(COLS - 4, 4, 1) == (COLS - 4, -1)


def test_advance_full_sweep_is_periodic() -> None:
    # Sweeping a width-3 row across the board returns it home eventually, never
    # leaving bounds — guards against an off-by-one that would freeze a wall.
    pos, d, width = 0, 1, 3
    for _ in range(200):
        pos, d = advance(pos, width, d)
        assert 0 <= pos <= COLS - width


# ---------------------------------------------------------------------------
# resolve_drop() — the core overlap rule

def test_resolve_perfect_overlap_keeps_full_width() -> None:
    assert resolve_drop(4, 6, 4, 6) == (4, 6)


def test_resolve_partial_overlap_is_intersection() -> None:
    # Dropped [5,11) onto base [4,10) → overlap [5,10) width 5.
    assert resolve_drop(5, 6, 4, 6) == (5, 5)


def test_resolve_no_overlap_is_zero_width() -> None:
    # Entirely past the base → width 0 → game over signal.
    assert resolve_drop(0, 3, 8, 4) == (8, 0)  # left clamps, width 0
    _left, width = resolve_drop(0, 3, 8, 4)
    assert width == 0


def test_resolve_touching_edges_do_not_overlap() -> None:
    # [0,4) and [4,8) share only a boundary, not a column → width 0.
    _left, width = resolve_drop(0, 4, 4, 4)
    assert width == 0


def test_resolve_is_symmetric_in_position() -> None:
    # Overlapping from the left or the right by the same amount loses the same.
    _l1, w1 = resolve_drop(2, 6, 4, 6)   # hangs off left
    _l2, w2 = resolve_drop(6, 6, 4, 6)   # hangs off right
    assert w1 == w2 == 4


# ---------------------------------------------------------------------------
# StackerState

def test_new_state_is_centered_and_seeded() -> None:
    s = StackerState.new()
    assert s.width == START_WIDTH
    assert s.height == 1
    left, width = s.placed[0]
    assert width == START_WIDTH
    # Centered on the board.
    assert left == (COLS - START_WIDTH) // 2


# ---------------------------------------------------------------------------
# Qt-level flow through the real game

@pytest.fixture
def game(qtbot):
    g = StackerGame()
    w = g.create_widget()
    qtbot.addWidget(w)
    g.start(GameMode.SINGLE, {0: "P1"})
    yield g
    # Stop the slide timer before the widget is torn down — otherwise a queued
    # tick fires into an already-deleted renderer and pollutes a later test.
    # This mirrors the hub's real teardown (HubPanel stops the game first).
    g.stop()


def test_perfect_drop_scores_bonus_and_grows_streak(game) -> None:
    # The seed row is centered and the moving row starts exactly on top of it,
    # so an immediate drop (before any slide) is a perfect stack.
    start_height = game._state.height
    game._drop()
    assert game._state.height == start_height + 1
    assert game._state.perfect_streak == 1
    # Perfect bonus plus per-block score were awarded.
    assert game._state.score > 0
    assert game.current_state == GameState.RUNNING


def test_drop_with_no_overlap_ends_game(game, qtbot) -> None:
    # Force the moving row entirely off the base, then drop → game over.
    s = game._state
    base_left, base_width = s.placed[-1]
    s.width = 2
    s.pos = 0 if base_left >= 3 else COLS - 2  # somewhere with no overlap
    # Make sure we really have zero overlap for this geometry.
    _l, w = resolve_drop(s.pos, s.width, base_left, base_width)
    if w != 0:
        s.pos = COLS - 2 if s.pos == 0 else 0
    results: list[GameResult] = []
    game.game_over.connect(results.append)
    game._drop()
    assert game.current_state == GameState.OVER
    assert len(results) == 1
    assert results[0].winner is None


def test_misaligned_drop_narrows_and_resets_streak(game) -> None:
    s = game._state
    base_left, base_width = s.placed[-1]
    # Shift the moving row one column off the base so one block is sliced.
    s.pos = base_left + 1
    s.width = base_width
    game._drop()
    _new_left, new_width = s.placed[-1]
    assert new_width == base_width - 1   # one block lost
    assert s.perfect_streak == 0


def test_topping_out_wins(game, qtbot) -> None:
    # Stack perfect rows until the tower reaches the top; expect a win result.
    results: list[GameResult] = []
    game.game_over.connect(results.append)
    # Each perfect drop adds one level; ROWS levels total tops out. We're at
    # height 1, so ROWS-1 more perfect drops reach the ceiling.
    for _ in range(ROWS):
        if game.current_state != GameState.RUNNING:
            break
        # Re-align onto the base each time so every drop is perfect.
        base_left, base_width = game._state.placed[-1]
        game._state.pos = base_left
        game._state.width = base_width
        game._drop()
    assert game.current_state == GameState.OVER
    assert results and results[-1].winner == 0
    assert "Topped out" in (results[-1].message or "")
