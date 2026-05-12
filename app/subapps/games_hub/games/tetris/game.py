from __future__ import annotations

import random
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

COLS = 10
ROWS = 20

# Tetrominoes: each piece is a list of (row, col) offsets from the pivot
_PIECES: list[list[tuple[int, int]]] = [
    # I
    [(0, -1), (0, 0), (0, 1), (0, 2)],
    # O
    [(0, 0), (0, 1), (1, 0), (1, 1)],
    # T
    [(0, -1), (0, 0), (0, 1), (1, 0)],
    # S
    [(0, 0), (0, 1), (1, -1), (1, 0)],
    # Z
    [(0, -1), (0, 0), (1, 0), (1, 1)],
    # J
    [(0, -1), (0, 0), (0, 1), (1, 1)],
    # L
    [(0, -1), (0, 0), (0, 1), (1, -1)],
]

_COLORS = [
    (0, 240, 240),   # I — cyan
    (240, 240, 0),   # O — yellow
    (160, 0, 240),   # T — purple
    (0, 240, 0),     # S — green
    (240, 0, 0),     # Z — red
    (0, 0, 240),     # J — blue
    (240, 160, 0),   # L — orange
]

# Points awarded per lines cleared simultaneously
_LINE_POINTS = {1: 100, 2: 300, 3: 500, 4: 800}
# Speed: ms per drop tick per level
_LEVEL_SPEED = [800, 700, 600, 500, 400, 300, 250, 200, 150, 100]


@dataclass
class TetrisState:
    board: list[list[int]]            # 0 = empty, 1-7 = piece colour index+1
    piece: list[tuple[int, int]]      # current piece cells (absolute row, col)
    pivot: tuple[int, int]            # rotation centre (absolute row, col)
    piece_type: int                   # index into _PIECES / _COLORS
    next_type: int
    score: int = 0
    level: int = 1
    lines: int = 0

    @staticmethod
    def empty() -> "TetrisState":
        return TetrisState(
            board=[[0] * COLS for _ in range(ROWS)],
            piece=[],
            pivot=(0, COLS // 2),
            piece_type=0,
            next_type=random.randrange(len(_PIECES)),
        )


def _spawn(piece_type: int) -> tuple[list[tuple[int, int]], tuple[int, int]]:
    """Return (absolute cells, pivot) for a freshly spawned piece."""
    pivot = (0, COLS // 2)
    cells = [(r + pivot[0], c + pivot[1]) for r, c in _PIECES[piece_type]]
    return cells, pivot


def _rotate(cells: list[tuple[int, int]], pivot: tuple[int, int]) -> list[tuple[int, int]]:
    """Rotate cells 90° CW around pivot."""
    pr, pc = pivot
    return [(pr + (c - pc), pc - (r - pr)) for r, c in cells]


def _valid(board: list[list[int]], cells: list[tuple[int, int]]) -> bool:
    for r, c in cells:
        if r < 0 or r >= ROWS or c < 0 or c >= COLS:
            return False
        if board[r][c]:
            return False
    return True


def _lock(state: TetrisState) -> int:
    """Lock the current piece into the board, clear lines, return lines cleared."""
    color = state.piece_type + 1
    for r, c in state.piece:
        if 0 <= r < ROWS and 0 <= c < COLS:
            state.board[r][c] = color

    cleared = 0
    new_board = []
    for row in state.board:
        if all(row):
            cleared += 1
        else:
            new_board.append(row)
    for _ in range(cleared):
        new_board.insert(0, [0] * COLS)
    state.board = new_board
    return cleared


@register_game
class TetrisGame(BaseGame):
    game_id = "tetris"
    display_name = "Tetris"
    icon_char = "🟦"
    icon_path = ""
    max_players = 1
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = TetrisState.empty()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None
        self._das_timer = QTimer(self)   # delayed auto-shift
        self._das_timer.setSingleShot(True)
        self._das_timer.timeout.connect(self._start_arr)
        self._arr_timer = QTimer(self)   # auto-repeat rate
        self._arr_timer.setInterval(50)
        self._arr_timer.timeout.connect(self._arr_tick)
        self._held_action: Action | None = None

    # ------------------------------------------------------------------
    # BaseGame contract

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.tetris.renderer import TetrisRenderer
        self._widget = TetrisRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = TetrisState.empty()
        self._state.piece_type = self._state.next_type
        self._state.next_type = random.randrange(len(_PIECES))
        self._state.piece, self._state.pivot = _spawn(self._state.piece_type)
        if self._widget is not None:
            self._widget._state = self._state  # keep renderer in sync with new state
        self._sync_widget()
        super().start(mode, players)
        self._start_timer()

    def pause(self) -> None:
        self._timer.stop()
        self._das_timer.stop()
        self._arr_timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        self._start_timer()

    def stop(self) -> None:
        self._timer.stop()
        self._das_timer.stop()
        self._arr_timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        if action == Action.LEFT:
            self._move(0, -1)
            self._held_action = Action.LEFT
            self._das_timer.start(170)
        elif action == Action.RIGHT:
            self._move(0, 1)
            self._held_action = Action.RIGHT
            self._das_timer.start(170)
        elif action == Action.DOWN:
            self._move(1, 0)
        elif action == Action.UP:
            self._rotate_piece()
        elif action == Action.FIRE:
            self._hard_drop()

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action in (Action.LEFT, Action.RIGHT) and action == self._held_action:
            self._held_action = None
            self._das_timer.stop()
            self._arr_timer.stop()

    def get_state(self) -> dict:
        return {
            "board": [row[:] for row in self._state.board],
            "piece": list(self._state.piece),
            "piece_type": self._state.piece_type,
            "next_type": self._state.next_type,
            "score": self._state.score,
            "level": self._state.level,
            "lines": self._state.lines,
        }

    # ------------------------------------------------------------------
    # Internal

    def _start_timer(self) -> None:
        speed = _LEVEL_SPEED[min(self._state.level - 1, len(_LEVEL_SPEED) - 1)]
        self._timer.start(speed)

    def _tick(self) -> None:
        if not self._move(1, 0):
            self._lock_piece()

    def _move(self, dr: int, dc: int) -> bool:
        candidate = [(r + dr, c + dc) for r, c in self._state.piece]
        if _valid(self._state.board, candidate):
            self._state.piece = candidate
            pr, pc = self._state.pivot
            self._state.pivot = (pr + dr, pc + dc)
            self._sync_widget()
            return True
        return False

    def _rotate_piece(self) -> None:
        candidate = _rotate(self._state.piece, self._state.pivot)
        # Wall kicks: try shifting ±1 col if rotation hits a wall or stack
        for dc in (0, 1, -1, 2, -2):
            shifted = [(r, c + dc) for r, c in candidate]
            if _valid(self._state.board, shifted):
                self._state.piece = shifted
                pr, pc = self._state.pivot
                self._state.pivot = (pr, pc + dc)
                self._sync_widget()
                return

    def _hard_drop(self) -> None:
        while self._move(1, 0):
            pass
        self._lock_piece()

    def _lock_piece(self) -> None:
        cleared = _lock(self._state)
        if cleared:
            pts = _LINE_POINTS.get(cleared, 0) * self._state.level
            self._state.score += pts
            self._state.lines += cleared
            self._state.level = self._state.lines // 10 + 1
            self._start_timer()  # adjust speed

        # Spawn next
        self._state.piece_type = self._state.next_type
        self._state.next_type = random.randrange(len(_PIECES))
        self._state.piece, self._state.pivot = _spawn(self._state.piece_type)

        self.score_tick.emit({"p1": self._state.score})

        if not _valid(self._state.board, self._state.piece):
            self._timer.stop()
            self._set_state(GameState.OVER)
            self.game_over.emit({"p1": self._state.score})
        else:
            self._sync_widget()

    def _start_arr(self) -> None:
        self._arr_timer.start()

    def _arr_tick(self) -> None:
        if self._held_action == Action.LEFT:
            self._move(0, -1)
        elif self._held_action == Action.RIGHT:
            self._move(0, 1)

    def _sync_widget(self) -> None:
        if self._widget is not None:
            self._widget.update()  # type: ignore[attr-defined]
