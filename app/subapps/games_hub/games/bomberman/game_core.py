from __future__ import annotations

import random
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable

COLS = 15
ROWS = 11

TICK_MS     = 50
MOVE_DELAY  = 4
FUSE_TICKS  = 40
BLAST_TICKS = 12
BLAST_RANGE = 2

PILLAR_DENSITY = 0.45

P1 = 0
P2 = 1


class Cell(Enum):
    EMPTY  = auto()
    PILLAR = auto()
    CRATE  = auto()


@dataclass
class Bomb:
    row:   int
    col:   int
    owner: int   # P1 or P2
    fuse:  int = FUSE_TICKS


@dataclass
class Explosion:
    cells: list[tuple[int, int]]
    life:  int = BLAST_TICKS


@dataclass
class Player:
    row:          int
    col:          int
    alive:        bool = True
    move_cd:      int  = 0
    bombs_placed: int  = 0
    max_bombs:    int  = 1


@dataclass
class InputState:
    up:   bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    bomb: bool = False


@dataclass
class BombermanState:
    grid:       list[list[Cell]]
    players:    dict[int, Player]   # keyed by P1/P2 (0/1)
    bombs:      list[Bomb]
    explosions: list[Explosion]

    @staticmethod
    def new() -> "BombermanState":
        grid = _build_grid()
        players: dict[int, Player] = {
            P1: Player(row=1,        col=1),
            P2: Player(row=ROWS - 2, col=COLS - 2),
        }
        return BombermanState(grid=grid, players=players, bombs=[], explosions=[])

    @property
    def alive_count(self) -> int:
        return sum(1 for p in self.players.values() if p.alive)

    def winner(self) -> int | None:
        alive = [idx for idx, p in self.players.items() if p.alive]
        return alive[0] if len(alive) == 1 else None


# ---------------------------------------------------------------------------
# Events

class PlayerDiedEvent:
    __slots__ = ("player",)
    def __init__(self, player: int) -> None:
        self.player = player


class GameOverEvent:
    __slots__ = ("winner",)
    def __init__(self, winner: int | None) -> None:
        self.winner = winner


# ---------------------------------------------------------------------------
# Grid helpers

def _build_grid() -> list[list[Cell]]:
    grid = [[Cell.EMPTY] * COLS for _ in range(ROWS)]

    for r in range(ROWS):
        for c in range(COLS):
            if r == 0 or r == ROWS - 1 or c == 0 or c == COLS - 1:
                grid[r][c] = Cell.PILLAR

    reserved = _spawn_reservation()
    candidates = [
        (r, c) for r in range(1, ROWS - 1) for c in range(1, COLS - 1)
        if (r, c) not in reserved
    ]
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
        for s in range(BLAST_RANGE + 1):
            cells.add((r + dr * s, c))
            cells.add((r, c + dc * s))
    return cells


def _has_pillar_neighbor8(grid: list[list[Cell]], r: int, c: int) -> bool:
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


def walkable(grid: list[list[Cell]], bombs: list[Bomb], r: int, c: int) -> bool:
    if not (0 <= r < ROWS and 0 <= c < COLS):
        return False
    if grid[r][c] != Cell.EMPTY:
        return False
    if any(b.row == r and b.col == c for b in bombs):
        return False
    return True


def blast_cells(grid: list[list[Cell]], row: int, col: int) -> list[tuple[int, int]]:
    cells = [(row, col)]
    for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
        for s in range(1, BLAST_RANGE + 1):
            r, c = row + dr * s, col + dc * s
            if not (0 <= r < ROWS and 0 <= c < COLS):
                break
            if grid[r][c] == Cell.PILLAR:
                break
            cells.append((r, c))
            if grid[r][c] == Cell.CRATE:
                break
    return cells


# ---------------------------------------------------------------------------
# Step

def place_bomb(s: BombermanState, player_idx: int) -> None:
    p = s.players[player_idx]
    if not p.alive:
        return
    if p.bombs_placed >= p.max_bombs:
        return
    if any(b.row == p.row and b.col == p.col for b in s.bombs):
        return
    s.bombs.append(Bomb(row=p.row, col=p.col, owner=player_idx))
    p.bombs_placed += 1


def move_player(s: BombermanState, player_idx: int, dr: int, dc: int) -> None:
    p = s.players[player_idx]
    if not p.alive or p.move_cd > 0:
        return
    nr, nc = p.row + dr, p.col + dc
    if walkable(s.grid, s.bombs, nr, nc):
        p.row, p.col = nr, nc
        p.move_cd = MOVE_DELAY


def apply_input(s: BombermanState, player_idx: int, inp: InputState,
                do_bomb: Callable[[], None], bomb_was_held: bool = False) -> bool:
    """Apply movement and bomb input for one player.

    Returns the new bomb_held state so the caller can track rising edge.
    bomb_was_held: whether the bomb key was already held last tick.
    """
    p = s.players[player_idx]
    if not p.alive:
        return inp.bomb
    # Bomb fires on rising edge only (key-down, not key-held)
    if inp.bomb and not bomb_was_held:
        do_bomb()
    if p.move_cd > 0:
        return inp.bomb
    if inp.up:
        move_player(s, player_idx, -1, 0)
    elif inp.down:
        move_player(s, player_idx, 1, 0)
    elif inp.left:
        move_player(s, player_idx, 0, -1)
    elif inp.right:
        move_player(s, player_idx, 0, 1)
    return inp.bomb


def step(s: BombermanState) -> list:
    """
    Advance bombs, explosions, and death checks by one tick.
    Movement is applied separately via apply_input() before calling step().
    Returns a list of PlayerDiedEvent / GameOverEvent.
    """
    events: list = []

    # Cooldowns
    for p in s.players.values():
        if p.move_cd > 0:
            p.move_cd -= 1

    # Bomb fuses
    detonated: list[Bomb] = []
    for bomb in s.bombs:
        bomb.fuse -= 1
        if bomb.fuse <= 0:
            detonated.append(bomb)

    for bomb in detonated:
        s.bombs.remove(bomb)
        s.players[bomb.owner].bombs_placed -= 1
        cells = blast_cells(s.grid, bomb.row, bomb.col)
        s.explosions.append(Explosion(cells=cells))
        for r, c in cells:
            if s.grid[r][c] == Cell.CRATE:
                s.grid[r][c] = Cell.EMPTY
        for other in list(s.bombs):
            if (other.row, other.col) in cells:
                other.fuse = 1

    # Explosion lifetimes
    for exp in s.explosions:
        exp.life -= 1
    s.explosions = [e for e in s.explosions if e.life > 0]

    # Death checks
    blast_set: set[tuple[int, int]] = set()
    for exp in s.explosions:
        blast_set.update(exp.cells)

    for idx, player in s.players.items():
        if player.alive and (player.row, player.col) in blast_set:
            player.alive = False
            events.append(PlayerDiedEvent(idx))

    # Game over check
    alive = [idx for idx, p in s.players.items() if p.alive]
    if len(alive) <= 1:
        winner = alive[0] if alive else None
        events.append(GameOverEvent(winner))

    return events
