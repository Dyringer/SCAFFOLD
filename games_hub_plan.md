# Games Hub — Design Plan

## Overview

Games Hub is a sub-app within S.C.A.F.F.O.L.D. that aggregates a collection of classic arcade games.
It exposes a launcher panel (the hub) and hosts each game as a fullscreen-ish widget within the
app body. All games share a common abstraction for input, scoring, and lifecycle.

---

## Directory Structure

```
app/subapps/games_hub/
    __init__.py
    core.py              ← GamesHubSubApp (registers as sub-app)
    ui.py                ← HubPanel (game picker grid)

    base_game.py         ← BaseGame abstract class + shared types
    score_store.py       ← Persistent high-score storage
    input_router.py      ← Keyboard routing to active game / player slots

    games/
        tetris/
            __init__.py
            game.py      ← TetrisGame(BaseGame)
            renderer.py  ← QWidget that paints the board
        space_invaders/
            ...
        pong/
            ...
        asteroids/
            ...
        snake/
            ...
```

---

## BaseGame Contract

Every game inherits `BaseGame` (itself a `QObject`) and implements a fixed lifecycle and
capability interface. The hub calls this contract — games never talk to each other or to
the hub directly beyond signals.

```python
class PlayerSlot(Enum):
    P1 = "p1"
    P2 = "p2"

class GameMode(Enum):
    SINGLE    = "single"     # one player vs. CPU (or endless arcade)
    LOCAL_PVP = "local_pvp"  # two players, same keyboard
    LAN_PVP   = "lan_pvp"    # two players, network  (future)

@dataclass
class ScoreEntry:
    player_name: str
    score: int
    timestamp: datetime

class BaseGame(QObject, metaclass=_Meta):
    # --- signals ---
    game_over   = Signal(dict)   # {"p1": score, "p2": score | None}
    score_tick  = Signal(dict)   # live score update, same shape
    state_changed = Signal(str)  # "idle" | "running" | "paused" | "over"

    # --- class-level metadata (override in each game) ---
    game_id:     str   = ""
    display_name: str  = ""
    icon_path:   str   = ""      # relative to app/resources/
    max_players: int   = 1       # 1 = single only; 2 = supports local PvP
    supports_lan: bool = False   # set True when LAN is wired up

    # --- lifecycle (called by hub) ---
    @abstractmethod
    def create_widget(self) -> QWidget: ...  # the game canvas

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None: ...
    def pause(self)  -> None: ...
    def resume(self) -> None: ...
    def reset(self)  -> None: ...
    def stop(self)   -> None: ...

    # --- input (called by InputRouter) ---
    def key_press(self,   key: Qt.Key, slot: PlayerSlot) -> None: ...
    def key_release(self, key: Qt.Key, slot: PlayerSlot) -> None: ...
```

The hub owns the game widget lifecycle: it creates the game, inserts its widget into the body,
and destroys it when the player exits.

---

## Score Store

`ScoreStore` is a lightweight singleton (similar to `SettingsStore`) backed by a JSON file
(`scores.json` alongside `settings.json`).

```
scores.json:
{
  "tetris":         [{"player": "Daniel", "score": 12400, "ts": "..."},  ...],
  "space_invaders": [...],
  ...
}
```

- Top-N (configurable, default 10) entries kept per game.
- `ScoreStore.submit(game_id, player_name, score)` — inserts and trims.
- `ScoreStore.top(game_id, n=5)` — returns sorted list for hub display.
- Hub shows the #1 score beside each game icon; full leaderboard opens on click.

---

## Hub Panel (Game Picker)

`HubPanel` is a `QWidget` grid of game cards. Each card shows:
- Game icon (pixel-art style, ~96×96)
- Game name
- Top score + holder name
- A "2P" badge if the game supports local PvP

Selecting a card opens a **mode selector dialog** (if the game supports multiple modes),
then launches the game. A persistent top-bar inside the game view shows current score and
an ESC/pause button, so the user can return to the hub without losing the session.

---

## Input Router

`InputRouter` sits between Qt's key events and the active game. It:

1. Intercepts `keyPressEvent` / `keyReleaseEvent` on the game widget container.
2. Looks up which `PlayerSlot` owns that key according to the **active key map**.
3. Calls `game.key_press(key, slot)` on the running game.

### Default Key Maps

| Slot | Action   | Keys              |
|------|----------|-------------------|
| P1   | Move     | Arrow keys / WASD |
| P1   | Fire/Act | Space / Z         |
| P2   | Move     | IJKL              |
| P2   | Fire/Act | Enter / M         |
| Both | Pause    | Escape / P        |

Key maps are stored in `settings.json` under `games.keymap.p1` / `games.keymap.p2` and are
editable via the Settings sub-app. Each game can declare which actions it uses; unused slots
are ignored.

---

## LAN Multiplayer — Future Preparation

No implementation now, but the architecture must not block it. Key decisions:

### Separation of game logic from rendering

Each game must maintain a **pure game-state object** (a plain dataclass or dict) that is
fully serializable. The renderer reads this state; it does not own it. This is the same
pattern as model/view and makes network sync straightforward later:

```
GameState (dataclass, JSON-serializable)
    ↑ mutated by: game logic tick (local) OR network patch (remote)
    ↓ read by:    renderer (paint from state)
```

### InputRouter abstraction layer

`InputRouter` already dispatches `(key, slot)` tuples. For LAN mode, a `NetworkInputRouter`
replaces it — it sends the local player's key events over the socket and injects the remote
player's events as if they came from the keyboard. The game itself is unaware of the
difference.

### Client–server model (peer-to-peer deferred)

- One player hosts (`GameServer`), one connects (`GameClient`).
- Host runs authoritative game logic and broadcasts state snapshots at ~20 Hz (UDP preferred
  for low latency).
- Client renders received state and sends only its key events upstream.
- `supports_lan = True` on a game means it has a serializable `GameState` and its `tick()`
  is deterministic given the same inputs — prerequisites for network play.

### Discovery

For LAN discovery, simple UDP broadcast on a well-known port is sufficient for a home/office
scenario. No internet relay needed. The hub shows a "Host" / "Join" flow when LAN mode is
selected.

### What each game must do today to be LAN-ready tomorrow

1. Keep all mutable state in a single `GameState` dataclass (no hidden state in the renderer).
2. Implement `get_state() -> GameState` and `apply_state(state: GameState) -> None`.
3. Make `tick(dt_ms: int, inputs: dict[PlayerSlot, set[Action]])` a pure function of state +
   inputs (no side effects other than mutating `self.state`).
4. Set `supports_lan = False` for now — the flag gates the UI option, not the architecture.

---

## Integration with SCAFFOLD

- `GamesHubSubApp` inherits `BaseSubApp`, registers via `registry.register()` in `application.py`.
- `create_body()` returns the `HubPanel`; when a game launches, the body widget is swapped for
  the game canvas (same pattern the hub uses to switch between sub-apps, just internal).
- `get_settings()` exposes key-map settings and top-score reset.
- `get_commands()` exposes commands like "Open Games Hub", "Reset All Scores".
- `on_deactivated()` pauses any running game automatically.
- Score data lives in `score_store.py` (a new singleton), not in `SettingsStore`, to keep
  concerns separate and avoid polluting `settings.json` with game data.

---

## Planned Games

| Game           | Players | CPU opponent | Notes                              | LAN-ready target |
|----------------|---------|--------------|-------------------------------------|------------------|
| Tetris         | 1       | —            | Endless, level-speed scaling        | No               |
| Snake          | 1       | —            | Endless, grid-based                 | No               |
| Space Invaders | 1       | Yes (waves)  | Wave progression                    | No               |
| Asteroids      | 1       | —            | Vector-style, wrap-around arena     | No               |
| Pong           | 1–2     | Yes          | Local PvP or vs CPU                 | Phase 4          |
| Breakout       | 1       | —            | Brick grid, power-ups optional      | No               |
| Bomberman      | 1–2     | Yes (basic)  | Local PvP; grid bombs, destructible walls | Phase 4     |

Pong is the natural first LAN candidate: minimal state (two paddles + ball), deterministic,
and the two-player local mode already validates the input-router split. Bomberman is the
flagship LAN title — richer state but still fully serializable (grid + player positions +
active bombs + timers).

---

## Implementation Phases

### Phase 1 — Foundation
- `base_game.py` — `BaseGame`, `GameMode`, `PlayerSlot`, `Action` enum
- `score_store.py` — persistence, top-N logic
- `input_router.py` — keyboard dispatch, configurable key maps
- `core.py` + `ui.py` — hub launcher panel, game card grid, mode selector dialog

### Phase 2 — First Games
- Tetris (validates single-player loop, score submission)
- Pong (validates two-player local, CPU mode, game-over handoff)

### Phase 3 — More Single-Player Games
- Snake
- Breakout
- Space Invaders
- Asteroids

### Phase 4 — Local Multiplayer Flagship
- Bomberman local PvP (2 players, same keyboard)
  - Grid with destructible walls, bomb placement, power-ups (blast radius, speed, bomb count)
  - CPU opponent for solo play (basic pathfinding, avoids own bombs)
  - `GameState` includes: grid cells, player positions/stats, active bombs + timers, power-up positions
  - Validates the most complex local multiplayer state — good LAN dry run

### Phase 5 — LAN Multiplayer
- `GameState` audit across all Phase 2–4 games
- `NetworkInputRouter`, `GameServer`, `GameClient`
- Hub LAN discovery and Host/Join flow
- Start with Pong, then Bomberman
