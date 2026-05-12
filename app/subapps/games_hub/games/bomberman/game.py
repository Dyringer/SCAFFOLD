from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

# Grid dimensions (must be odd for the classic pillar layout)
COLS = 15
ROWS = 11

TICK_MS      = 50    # ~20 fps physics ticks
MOVE_DELAY   = 4     # ticks between player moves (200 ms)
FUSE_TICKS   = 40    # ticks until bomb detonates (2 s)
BLAST_TICKS  = 12    # ticks the explosion lingers
BLAST_RANGE  = 2     # cells in each direction

PILLAR_CHAR  = "#"   # indestructible
CRATE_CHAR   = "C"   # destructible
EMPTY_CHAR   = " "


class Cell(Enum):
    EMPTY   = auto()
    PILLAR  = auto()   # indestructible wall
    CRATE   = auto()   # destructible block


@dataclass
class Bomb:
    row: int
    col: int
    owner: PlayerSlot
    fuse: int = FUSE_TICKS       # ticks until explosion


@dataclass
class Explosion:
    cells: list[tuple[int, int]]  # all cells hit
    life: int = BLAST_TICKS


@dataclass
class Player:
    row: int
    col: int
    alive: bool = True
    move_cd: int = 0              # move cooldown in ticks
    bombs_placed: int = 0
    max_bombs: int = 1


@dataclass
class BombermanState:
    grid: list[list[Cell]]
    players: dict[PlayerSlot, Player]
    bombs: list[Bomb]
    explosions: list[Explosion]
    mode: GameMode = GameMode.LOCAL_PVP

    @staticmethod
    def new(mode: GameMode) -> "BombermanState":
        grid = _build_grid()
        players: dict[PlayerSlot, Player] = {
            PlayerSlot.P1: Player(row=1, col=1),
            PlayerSlot.P2: Player(row=ROWS - 2, col=COLS - 2),
        }
        return BombermanState(grid=grid, players=players, bombs=[], explosions=[], mode=mode)

    @property
    def alive_count(self) -> int:
        return sum(1 for p in self.players.values() if p.alive)

    def winner(self) -> PlayerSlot | None:
        alive = [slot for slot, p in self.players.items() if p.alive]
        return alive[0] if len(alive) == 1 else None


PILLAR_DENSITY = 0.45  # fraction of eligible interior cells that become pillars


def _build_grid() -> list[list[Cell]]:
    grid = [[Cell.EMPTY] * COLS for _ in range(ROWS)]

    # Border walls
    for r in range(ROWS):
        for c in range(COLS):
            if r == 0 or r == ROWS - 1 or c == 0 or c == COLS - 1:
                grid[r][c] = Cell.PILLAR

    # Spawn-safety reservation: each corner needs an L-corridor of length
    # BLAST_RANGE+1 along both inward axes kept free of pillars so a player
    # who bombs from (1,2) or (2,1) can flee perpendicular to the blast.
    # The spawn cell itself counts; dropping a bomb at spawn is fatal by
    # design (no diagonal escape) — players are expected to step out first.
    reserved = _spawn_reservation()

    # Randomized pillar placement with 8-neighbor non-adjacency. Shuffling
    # candidate cells gives layout variety while the adjacency check keeps
    # every pillar reachable from at least one cardinal neighbor.
    candidates = [(r, c) for r in range(1, ROWS - 1) for c in range(1, COLS - 1)
                  if (r, c) not in reserved]
    random.shuffle(candidates)
    target = int(len(candidates) * PILLAR_DENSITY)
    placed = 0
    for r, c in candidates:
        if placed >= target:
            break
        if _has_pillar_neighbor8(grid, r, c):
            continue
        grid[r][c] = Cell.PILLAR
        placed += 1

    # Fill remaining empty cells with crates (~65%), skipping the reserved
    # spawn corridors so they stay walkable.
    for r in range(ROWS):
        for c in range(COLS):
            if grid[r][c] == Cell.EMPTY and (r, c) not in reserved \
                    and random.random() < 0.65:
                grid[r][c] = Cell.CRATE

    return grid


def _spawn_reservation() -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    corners = [
        (1,        1,         1,  1),
        (1,        COLS - 2,  1, -1),
        (ROWS - 2, 1,        -1,  1),
        (ROWS - 2, COLS - 2, -1, -1),
    ]
    for r, c, dr, dc in corners:
        for step in range(BLAST_RANGE + 1):
            cells.add((r + dr * step, c))
            cells.add((r, c + dc * step))
    return cells


def _has_pillar_neighbor8(grid: list[list[Cell]], r: int, c: int) -> bool:
    # Only checks interior pillars; the surrounding border wall is excluded
    # so candidate cells adjacent to the border are still eligible.
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if not (1 <= nr < ROWS - 1 and 1 <= nc < COLS - 1):
                continue
            if grid[nr][nc] == Cell.PILLAR:
                return True
    return False


def _walkable(grid: list[list[Cell]], bombs: list[Bomb], r: int, c: int) -> bool:
    if not (0 <= r < ROWS and 0 <= c < COLS):
        return False
    if grid[r][c] != Cell.EMPTY:
        return False
    if any(b.row == r and b.col == c for b in bombs):
        return False
    return True


def _blast_cells(grid: list[list[Cell]], row: int, col: int) -> list[tuple[int, int]]:
    """Return all cells hit by explosion from (row, col)."""
    cells = [(row, col)]
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        for step in range(1, BLAST_RANGE + 1):
            r, c = row + dr * step, col + dc * step
            if not (0 <= r < ROWS and 0 <= c < COLS):
                break
            if grid[r][c] == Cell.PILLAR:
                break
            cells.append((r, c))
            if grid[r][c] == Cell.CRATE:
                break  # blast destroys crate but doesn't pass through
    return cells



@register_game
class BombermanGame(BaseGame):
    game_id = "bomberman"
    display_name = "Bomberman"
    icon_char = "💣"
    max_players = 2
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = BombermanState.new(GameMode.LOCAL_PVP)
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None

        # Held movement directions per player
        self._held: dict[PlayerSlot, tuple[int, int] | None] = {
            PlayerSlot.P1: None,
            PlayerSlot.P2: None,
        }

        self._bot_debug_path: list[tuple[int, int]] = []

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.bomberman.renderer import BombermanRenderer
        self._widget = BombermanRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = BombermanState.new(mode)
        self._held = {PlayerSlot.P1: None, PlayerSlot.P2: None}
        self._bot_debug_path = []
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
            self._widget.bot_path = []  # type: ignore[attr-defined]
        super().start(mode, players)
        self._timer.start()

    def pause(self) -> None:
        self._timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        if action == Action.UP:    self._held[slot] = (-1, 0)
        elif action == Action.DOWN:  self._held[slot] = (1, 0)
        elif action == Action.LEFT:  self._held[slot] = (0, -1)
        elif action == Action.RIGHT: self._held[slot] = (0, 1)
        elif action == Action.FIRE:  self._place_bomb(slot)

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        if action in (Action.UP, Action.DOWN, Action.LEFT, Action.RIGHT):
            dr_dc = {Action.UP: (-1,0), Action.DOWN: (1,0),
                     Action.LEFT: (0,-1), Action.RIGHT: (0,1)}[action]
            if self._held[slot] == dr_dc:
                self._held[slot] = None

    def get_state(self) -> dict:
        s = self._state
        return {
            "p1": (s.players[PlayerSlot.P1].row, s.players[PlayerSlot.P1].col),
            "p2": (s.players[PlayerSlot.P2].row, s.players[PlayerSlot.P2].col),
        }

    # ------------------------------------------------------------------

    def _place_bomb(self, slot: PlayerSlot) -> None:
        s = self._state
        p = s.players[slot]
        if not p.alive:
            return
        if p.bombs_placed >= p.max_bombs:
            return
        if any(b.row == p.row and b.col == p.col for b in s.bombs):
            return
        s.bombs.append(Bomb(row=p.row, col=p.col, owner=slot))
        p.bombs_placed += 1

    def _tick(self) -> None:
        s = self._state

        # Move players
        for slot, player in s.players.items():
            if not player.alive:
                continue
            if player.move_cd > 0:
                player.move_cd -= 1
                continue
            # Bot control in SINGLE mode
            if slot == PlayerSlot.P2 and s.mode == GameMode.SINGLE:
                self._bot_act()
                continue
            direction = self._held[slot]
            if direction is not None:
                nr, nc = player.row + direction[0], player.col + direction[1]
                if _walkable(s.grid, s.bombs, nr, nc):
                    player.row, player.col = nr, nc
                    player.move_cd = MOVE_DELAY

        # Tick bombs
        detonated: list[Bomb] = []
        for bomb in s.bombs:
            bomb.fuse -= 1
            if bomb.fuse <= 0:
                detonated.append(bomb)

        # Detonate
        for bomb in detonated:
            s.bombs.remove(bomb)
            s.players[bomb.owner].bombs_placed -= 1
            cells = _blast_cells(s.grid, bomb.row, bomb.col)
            s.explosions.append(Explosion(cells=cells))
            # Destroy crates
            for r, c in cells:
                if s.grid[r][c] == Cell.CRATE:
                    s.grid[r][c] = Cell.EMPTY
            # Chain-detonate other bombs in blast
            for other in list(s.bombs):
                if (other.row, other.col) in cells:
                    other.fuse = 1   # detonate next tick

        # Tick explosions
        for exp in s.explosions:
            exp.life -= 1
        s.explosions = [e for e in s.explosions if e.life > 0]

        # Kill players caught in explosion
        blast_set: set[tuple[int, int]] = set()
        for exp in s.explosions:
            blast_set.update(exp.cells)

        for player in s.players.values():
            if player.alive and (player.row, player.col) in blast_set:
                player.alive = False

        # Check end condition
        alive = [slot for slot, p in s.players.items() if p.alive]
        if len(alive) <= 1:
            self._timer.stop()
            winner = alive[0] if alive else None
            scores: dict = {}
            for slot, p in s.players.items():
                scores[slot.value] = 1 if slot == winner else 0
            self._set_state(GameState.OVER)
            self.game_over.emit(scores)
            if self._widget is not None:
                self._widget.update()
            return

        if self._widget is not None:
            self._widget.update()

    def _bot_act(self) -> None:
        from app.subapps.games_hub.games.bomberman.bot import bot_act, bot_path
        from app.core.settings_store import settings_store
        bot_act(self._state, lambda: self._place_bomb(PlayerSlot.P2))
        if settings_store.get("bomberman.debug_bot_path", False):
            # Only recalculate when the bot has no active bombs — during the
            # fuse/blast window the path would route around the bot's own blast
            # zone, which is misleading.  Keep showing the pre-bomb plan until
            # the area is clear, then update from the new position.
            bot = self._state.players[PlayerSlot.P2]
            if bot.bombs_placed == 0:
                self._bot_debug_path = bot_path(self._state)
        else:
            self._bot_debug_path = []
        if self._widget is not None:
            self._widget.bot_path = self._bot_debug_path  # type: ignore[attr-defined]
