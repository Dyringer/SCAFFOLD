from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.ui import register_game

# Board geometry. Narrow + tall is what makes the greed loop bite: the tower
# climbs quickly so the speed ramp is felt, and it's wide enough that an early
# sloppy drop still leaves room to recover.
COLS = 14
ROWS = 18

START_WIDTH = 6        # blocks in the very first moving row
TICK_MS = 220          # base slide interval (ms per one-column step)
SPEED_STEP = 9         # ms shaved per level climbed
MIN_TICK = 70          # fastest the row ever slides

# Scoring. A clean (no-overlap-lost) drop is worth far more than a sloppy one,
# so playing for perfects — the risky line — pays better than playing safe.
SCORE_PER_BLOCK = 10
PERFECT_BONUS = 50
# A perfect drop regrows a sliced block (up to the row's own width) every Nth
# perfect in a row, so a hot streak can *widen* the tower — the carrot that
# makes you keep chasing perfects instead of banking a safe narrow stack.
PERFECT_REGROW_EVERY = 3


@dataclass
class StackerState:
    """Pure grid model — no Qt. All rules operate on integer columns.

    A placed level is (left, width). `placed` is bottom-to-top. The moving row
    rides on top of the last placed level: `pos` is its left column, advancing
    `direction` (+1/-1) one column per tick and bouncing off the walls.
    """

    placed: list[tuple[int, int]]   # [(left, width)] bottom → top
    pos: int                        # moving row's left column
    width: int                      # moving row's width (blocks)
    direction: int                  # +1 / -1
    score: int = 0
    perfect_streak: int = 0
    landed: list[tuple[int, int, int]] = field(default_factory=list)
    # ^ sliced-off fragments still falling, as (left, width, row) — cosmetic.

    @staticmethod
    def new() -> StackerState:
        left = (COLS - START_WIDTH) // 2
        return StackerState(
            placed=[(left, START_WIDTH)],
            pos=left,
            width=START_WIDTH,
            direction=1,
        )

    @property
    def height(self) -> int:
        """Number of levels locked in (the bottom seed row counts as 1)."""
        return len(self.placed)


def advance(pos: int, width: int, direction: int) -> tuple[int, int]:
    """One slide step for the moving row. Bounces off either wall.

    Returns the new (pos, direction). Pure — the renderer never needs to know
    the bounce rule and tests can step it without a timer.
    """
    nxt = pos + direction
    if nxt < 0:
        return 0, 1
    if nxt + width > COLS:
        return COLS - width, -1
    return nxt, direction


def resolve_drop(
    drop_left: int, drop_width: int, base_left: int, base_width: int
) -> tuple[int, int]:
    """Intersect the dropped row with the level below.

    Returns the surviving (left, width) — the overlap. width == 0 means nothing
    landed on solid ground, i.e. game over. This is the whole Stacker rule, in
    one line of interval math, so it's trivially testable.
    """
    left = max(drop_left, base_left)
    right = min(drop_left + drop_width, base_left + base_width)
    return left, max(0, right - left)


@register_game
class StackerGame(BaseGame):
    game_id = "stacker"
    display_name = "Stacker"
    icon_char = "🧱"

    def __init__(self) -> None:
        super().__init__()
        self._state = StackerState.new()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)
        self._widget: QWidget | None = None

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.stacker.renderer import StackerRenderer
        self._widget = StackerRenderer(self._state, self._drop)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = StackerState.new()
        if self._widget is not None:
            self._widget.state = self._state
        super().start(mode, players)
        self.score_tick.emit(self._score_text())
        self._timer.start(self._current_speed())

    def resume(self) -> None:
        super().resume()
        self._timer.start(self._current_speed())

    def get_state(self) -> dict:
        s = self._state
        return {"placed": list(s.placed), "pos": s.pos, "score": s.score}

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        s = self._state
        s.pos, s.direction = advance(s.pos, s.width, s.direction)
        if self._widget is not None:
            self._widget.update()

    def _drop(self) -> None:
        """The one input: lock the moving row onto the stack."""
        if self._game_state != GameState.RUNNING:
            return
        s = self._state
        base_left, base_width = s.placed[-1]
        left, width = resolve_drop(s.pos, s.width, base_left, base_width)

        if width == 0:
            self._die()
            return

        sliced = s.width - width  # blocks that hung off and fell away
        if sliced == 0:
            # Perfect drop: full bonus, and a hot streak can regrow a block.
            s.perfect_streak += 1
            s.score += PERFECT_BONUS
            if (
                s.perfect_streak % PERFECT_REGROW_EVERY == 0
                and width < START_WIDTH
                and self._can_regrow(left, width)
            ):
                left, width = self._regrow(left, width)
        else:
            s.perfect_streak = 0

        s.score += width * SCORE_PER_BLOCK
        s.placed.append((left, width))
        s.pos = left
        s.width = width
        self.score_tick.emit(self._score_text())

        # Reached the top → cleared the tower.
        if s.height >= ROWS:
            self._win()
            return

        self._timer.start(self._current_speed())
        if self._widget is not None:
            self._widget.update()

    def _can_regrow(self, left: int, width: int) -> bool:
        return left > 0 or (left + width) < COLS

    def _regrow(self, left: int, width: int) -> tuple[int, int]:
        # Prefer growing toward the side with more room so we stay on-board.
        room_left = left
        room_right = COLS - (left + width)
        if room_left >= room_right and room_left > 0:
            return left - 1, width + 1
        if room_right > 0:
            return left, width + 1
        return left, width

    def _current_speed(self) -> int:
        return max(MIN_TICK, TICK_MS - (self._state.height - 1) * SPEED_STEP)

    def _score_text(self) -> str:
        s = self._state
        streak = f"   🔥{s.perfect_streak}" if s.perfect_streak >= 2 else ""
        return f"Score: {s.score:,}   H{s.height}{streak}"

    def _die(self) -> None:
        self._timer.stop()
        self._set_state(GameState.OVER)
        self.game_over.emit(
            GameResult(
                scores={0: self._state.score},
                winner=None,
                message=f"Height {self._state.height}",
            )
        )

    def _win(self) -> None:
        self._timer.stop()
        # Topping out is the rare triumphant end — reward it heavily.
        self._state.score += 500
        self.score_tick.emit(self._score_text())
        self._set_state(GameState.OVER)
        self.game_over.emit(
            GameResult(
                scores={0: self._state.score},
                winner=0,
                message="Topped out! 🏆",
            )
        )
