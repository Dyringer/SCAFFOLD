from __future__ import annotations

import heapq
from collections import deque
from typing import Callable

from app.subapps.games_hub.base_game import PlayerSlot
from app.subapps.games_hub.games.bomberman.game import (
    Bomb, BombermanState, Cell, Player,
    ROWS, COLS, FUSE_TICKS, MOVE_DELAY,
    _blast_cells,
)

_INF: int = 10_000
_STEP_COST = MOVE_DELAY + 1  # ticks between bot actions

# How many moves it costs to bomb through a crate: stand adjacent, place bomb,
# wait for fuse + blast, then step into the cleared cell.
CRATE_COST = FUSE_TICKS // _STEP_COST + 1   # ≈ 9


# ---------------------------------------------------------------------------
# Danger sets
# ---------------------------------------------------------------------------

def _danger_cells(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    explosions: list,
) -> tuple[set[tuple[int, int]], set[tuple[int, int]]]:
    """Return (blast_zone, explosion_zone).

    blast_zone     – cells that will be hit when any active bomb detonates.
    explosion_zone – cells currently on fire; impassable (instant death).
    """
    blast_zone: set[tuple[int, int]] = set()
    explosion_zone: set[tuple[int, int]] = set()
    for b in bombs:
        blast_zone.update(_blast_cells(grid, b.row, b.col))
    for exp in explosions:
        explosion_zone.update(exp.cells)
    return blast_zone, explosion_zone


def _passable(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    explosion_zone: set[tuple[int, int]],
    r: int, c: int,
) -> bool:
    """True if the cell can be entered on foot (empty, no bomb, not on fire)."""
    if not (0 <= r < ROWS and 0 <= c < COLS):
        return False
    if grid[r][c] != Cell.EMPTY:
        return False
    if (r, c) in explosion_zone:
        return False
    if any(b.row == r and b.col == c for b in bombs):
        return False
    return True


# ---------------------------------------------------------------------------
# Escape BFS — used when the bot is inside a blast zone
# ---------------------------------------------------------------------------

def _find_escape(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    blast_zone: set[tuple[int, int]],
    explosion_zone: set[tuple[int, int]],
    start_r: int, start_c: int,
) -> tuple[int, int] | None:
    """BFS to the nearest cell outside blast_zone.

    The bot may pass *through* blast-zone cells while fleeing (it keeps
    moving so it never lingers there).  Active explosion cells are walls.
    Returns the first hop toward safety, or None if no escape exists.
    """
    visited: dict[tuple[int, int], tuple[int, int] | None] = {
        (start_r, start_c): None
    }
    queue: deque[tuple[int, int]] = deque([(start_r, start_c)])
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if (nr, nc) in visited:
                continue
            if not _passable(grid, bombs, explosion_zone, nr, nc):
                continue
            visited[(nr, nc)] = (r, c)
            if (nr, nc) not in blast_zone:
                cur: tuple[int, int] = (nr, nc)
                while visited[cur] != (start_r, start_c):
                    cur = visited[cur]
                return cur
            queue.append((nr, nc))
    return None


# ---------------------------------------------------------------------------
# Dijkstra pathfinding — drives all bot movement
# ---------------------------------------------------------------------------

def _dijkstra_step(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    hot: set[tuple[int, int]],
    sr: int, sc: int,
    tr: int, tc: int,
) -> tuple[int, int] | None:
    """Shortest path from (sr, sc) to (tr, tc).

    Edge costs:
      empty cell  → 1  (just move)
      crate cell  → CRATE_COST  (bomb it, wait, then enter)
      hot / pillar / bomb → impassable

    Returns the first hop cell, or None if unreachable.
    """
    if (sr, sc) == (tr, tc):
        return None

    dist: dict[tuple[int, int], int] = {(sr, sc): 0}
    prev: dict[tuple[int, int], tuple[int, int] | None] = {(sr, sc): None}
    pq: list[tuple[int, int, int]] = [(0, sr, sc)]

    while pq:
        d, r, c = heapq.heappop(pq)
        if d > dist.get((r, c), _INF):
            continue
        if (r, c) == (tr, tc):
            cur: tuple[int, int] = (r, c)
            while prev[cur] != (sr, sc):
                cur = prev[cur]
            return cur

        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < ROWS and 0 <= nc < COLS):
                continue
            if grid[nr][nc] == Cell.PILLAR:
                continue
            if (nr, nc) in hot:
                continue
            if any(b.row == nr and b.col == nc for b in bombs):
                continue
            cost = CRATE_COST if grid[nr][nc] == Cell.CRATE else 1
            nd = d + cost
            if nd < dist.get((nr, nc), _INF):
                dist[(nr, nc)] = nd
                prev[(nr, nc)] = (r, c)
                heapq.heappush(pq, (nd, nr, nc))

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def bot_path(state: BombermanState) -> list[tuple[int, int]]:
    """Return the full Dijkstra path from the bot to P1 (debug use only).

    Runs a fresh Dijkstra and reconstructs the complete cell list from the
    bot's current position to P1, or an empty list if either player is dead
    or no path exists.
    """
    bot = state.players[PlayerSlot.P2]
    p1  = state.players[PlayerSlot.P1]
    if not bot.alive or not p1.alive:
        return []

    sr, sc = bot.row, bot.col
    tr, tc = p1.row, p1.col
    if (sr, sc) == (tr, tc):
        return []

    _, explosion_zone = _danger_cells(
        state.grid, state.bombs, state.explosions,
    )
    # Blast zones are temporary — the bot waits for them to clear and takes
    # the same route.  Only actively-burning cells are truly impassable.
    walls = explosion_zone

    dist: dict[tuple[int, int], int] = {(sr, sc): 0}
    prev: dict[tuple[int, int], tuple[int, int] | None] = {(sr, sc): None}
    pq: list[tuple[int, int, int]] = [(0, sr, sc)]
    found = False

    while pq:
        d, r, c = heapq.heappop(pq)
        if d > dist.get((r, c), _INF):
            continue
        if (r, c) == (tr, tc):
            found = True
            break
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < ROWS and 0 <= nc < COLS):
                continue
            if state.grid[nr][nc] == Cell.PILLAR:
                continue
            if (nr, nc) in walls:
                continue
            if any(b.row == nr and b.col == nc for b in state.bombs):
                continue
            cost = CRATE_COST if state.grid[nr][nc] == Cell.CRATE else 1
            nd = d + cost
            if nd < dist.get((nr, nc), _INF):
                dist[(nr, nc)] = nd
                prev[(nr, nc)] = (r, c)
                heapq.heappush(pq, (nd, nr, nc))

    if not found:
        return []

    path: list[tuple[int, int]] = []
    cur: tuple[int, int] | None = (tr, tc)
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path


def _free_path_exists(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    explosion_zone: set[tuple[int, int]],
    sr: int, sc: int,
    tr: int, tc: int,
) -> bool:
    """True if P1 is reachable through empty cells only (no crates needed).

    Uses BFS treating crates, pillars, bombs, and explosion cells as walls.
    """
    if (sr, sc) == (tr, tc):
        return True
    visited: set[tuple[int, int]] = {(sr, sc)}
    queue: deque[tuple[int, int]] = deque([(sr, sc)])
    while queue:
        r, c = queue.popleft()
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if (nr, nc) in visited:
                continue
            if not (0 <= nr < ROWS and 0 <= nc < COLS):
                continue
            if grid[nr][nc] != Cell.EMPTY:
                continue
            if (nr, nc) in explosion_zone:
                continue
            if any(b.row == nr and b.col == nc for b in bombs):
                continue
            if (nr, nc) == (tr, tc):
                return True
            visited.add((nr, nc))
            queue.append((nr, nc))
    return False


def _hunt_step(
    grid: list[list[Cell]],
    bombs: list[Bomb],
    hot: set[tuple[int, int]],
    bot_r: int, bot_c: int,
    p1_r: int, p1_c: int,
) -> tuple[int, int] | None:
    """Phase 2: find the nearest cell where the bot can place a bomb that
    hits P1.

    Dijkstra over empty cells only (crates = impassable in hunt mode).
    Returns the first hop toward the best firing position, or None.
    If the bot is already in a position where P1 is in blast range, returns
    None so the caller can bomb immediately.
    """
    if (p1_r, p1_c) in _blast_cells(grid, bot_r, bot_c):
        return None  # already in firing position

    dist: dict[tuple[int, int], int] = {(bot_r, bot_c): 0}
    prev: dict[tuple[int, int], tuple[int, int] | None] = {(bot_r, bot_c): None}
    pq: list[tuple[int, int, int]] = [(0, bot_r, bot_c)]

    best_dist = _INF
    best_cell: tuple[int, int] | None = None

    while pq:
        d, r, c = heapq.heappop(pq)
        if d > dist.get((r, c), _INF):
            continue
        if d >= best_dist:
            break

        if (p1_r, p1_c) in _blast_cells(grid, r, c):
            best_dist = d
            best_cell = (r, c)
            break

        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            nr, nc = r + dr, c + dc
            if not (0 <= nr < ROWS and 0 <= nc < COLS):
                continue
            if grid[nr][nc] != Cell.EMPTY:
                continue
            if (nr, nc) in hot:
                continue
            if any(b.row == nr and b.col == nc for b in bombs):
                continue
            nd = d + 1
            if nd < dist.get((nr, nc), _INF):
                dist[(nr, nc)] = nd
                prev[(nr, nc)] = (r, c)
                heapq.heappush(pq, (nd, nr, nc))

    if best_cell is None:
        return None

    cur: tuple[int, int] = best_cell
    while prev[cur] != (bot_r, bot_c):
        cur = prev[cur]
    return cur


def _try_bomb_and_flee(
    state: BombermanState,
    bot: Player,
    explosion_zone: set[tuple[int, int]],
    place_bomb: Callable[[], None],
) -> bool:
    """Attempt to place a bomb and immediately flee.

    Simulates the bomb to check if an escape route exists before committing.
    Returns True if a bomb was placed (caller should not move further).
    """
    if bot.bombs_placed >= bot.max_bombs:
        return False
    sim_bomb = Bomb(row=bot.row, col=bot.col, owner=PlayerSlot.P2, fuse=FUSE_TICKS)
    sim_blast, _ = _danger_cells(state.grid, state.bombs + [sim_bomb], state.explosions)
    escape = _find_escape(
        state.grid, state.bombs + [sim_bomb],
        sim_blast, explosion_zone,
        bot.row, bot.col,
    )
    if escape is None:
        return False
    place_bomb()
    blast2, exp2 = _danger_cells(state.grid, state.bombs, state.explosions)
    step = _find_escape(state.grid, state.bombs, blast2, exp2, bot.row, bot.col)
    if step:
        bot.row, bot.col = step
        bot.move_cd = MOVE_DELAY
    return True


def bot_act(
    state: BombermanState,
    place_bomb: Callable[[], None],
) -> None:
    """Execute one bot decision tick for PlayerSlot.P2."""
    bot = state.players[PlayerSlot.P2]
    p1  = state.players[PlayerSlot.P1]
    if not bot.alive:
        return

    blast_zone, explosion_zone = _danger_cells(
        state.grid, state.bombs, state.explosions,
    )
    hot = blast_zone | explosion_zone

    # 1. In danger — flee to the nearest cell outside all blast zones.
    if (bot.row, bot.col) in hot:
        step = _find_escape(
            state.grid, state.bombs, blast_zone, explosion_zone,
            bot.row, bot.col,
        )
        if step:
            bot.row, bot.col = step
            bot.move_cd = MOVE_DELAY
        return

    # Determine phase: if a crate-free path to P1 exists → Phase 2 (hunt).
    phase2 = p1.alive and _free_path_exists(
        state.grid, state.bombs, explosion_zone,
        bot.row, bot.col, p1.row, p1.col,
    )

    if phase2:
        # Phase 2: actively try to bomb P1.
        p1_in_blast = (p1.row, p1.col) in _blast_cells(state.grid, bot.row, bot.col)
        if p1_in_blast:
            # Already in firing position — bomb and flee.
            _try_bomb_and_flee(state, bot, explosion_zone, place_bomb)
            return

        # Navigate to the nearest firing position (empty cells only).
        next_hop = _hunt_step(
            state.grid, state.bombs, hot,
            bot.row, bot.col, p1.row, p1.col,
        )
        if next_hop is not None:
            bot.row, bot.col = next_hop
            bot.move_cd = MOVE_DELAY
        return

    # Phase 1: clear a path to P1 through crates via weighted Dijkstra.
    next_hop = _dijkstra_step(
        state.grid, state.bombs, hot,
        bot.row, bot.col, p1.row, p1.col,
    )
    if next_hop is None:
        return

    nr, nc = next_hop
    next_is_crate = state.grid[nr][nc] == Cell.CRATE

    if next_is_crate:
        # Bomb the crate blocking the optimal path, then flee.
        _try_bomb_and_flee(state, bot, explosion_zone, place_bomb)
        return

    # Move toward P1 along the cleared path.
    bot.row, bot.col = next_hop
    bot.move_cd = MOVE_DELAY
