from __future__ import annotations

import random
from dataclasses import dataclass, field

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import Action, BaseGame, GameMode, GameState, PlayerSlot
from app.subapps.games_hub.ui import register_game

# -----------------------------------------------------------------------
# World constants (pixel units in world space)

WORLD_W        = 320      # logical world width
SCREEN_H       = 480      # logical viewport height

GRAVITY        = 0.55
JUMP_VY        = -13.5    # initial vertical velocity when jumping
WALK_VX        = 3.8      # horizontal speed while key held
FRICTION       = 0.96     # icy — very little deceleration when not pressing

RUN_THRESHOLD  = 2.5      # |vel_x| above which a jump gets a run bonus
RUN_JUMP_BONUS = -2.0     # extra vel_y added when running before jump

TICK_MS        = 16       # ~60 fps

# Platform generation
PLAT_START_Y   = SCREEN_H - 60        # y of the very first (ground) platform
PLAT_START_W   = WORLD_W - 20         # ground platform is almost full width
PLAT_H         = 12
PLAT_MIN_W     = 40
PLAT_STEP_Y    = 56       # vertical gap between successive platforms (world units)

# Scroll speed brackets — (min_floor, scroll_px_per_frame)
_SPEED_BRACKETS = [
    (0,   0.0),
    (10,  0.4),
    (25,  0.8),
    (50,  1.3),
    (80,  1.9),
    (120, 2.6),
]


# -----------------------------------------------------------------------

@dataclass
class Platform:
    x: float
    y: float
    w: float
    idx: int = 0
    h: float = PLAT_H

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class IcyTowerState:
    px: float                       # player left edge (world coords)
    py: float                       # player top edge (world coords)
    vx: float
    vy: float
    on_ground: bool
    holding_left: bool
    holding_right: bool
    platforms: list[Platform]
    camera_y: float                 # world y at top of screen
    floor: int                      # highest platform index ever landed
    score: int
    scroll_speed: float
    next_plat_y: float              # y of next platform to generate above
    next_plat_idx: int              # monotonic counter for generated platforms

    PLAYER_W: float = 28.0
    PLAYER_H: float = 36.0

    @staticmethod
    def new() -> "IcyTowerState":
        ground = Platform(x=10, y=PLAT_START_Y, w=PLAT_START_W, idx=0)
        platforms = [ground]

        # Pre-generate enough platforms to fill two screens worth
        next_y = PLAT_START_Y - PLAT_STEP_Y
        for i in range(1, 30):
            platforms.append(_gen_platform(next_y, i))
            next_y -= PLAT_STEP_Y

        px = WORLD_W / 2 - 14
        py = ground.y - 36  # standing on ground

        return IcyTowerState(
            px=px, py=py, vx=0, vy=0,
            on_ground=True,
            holding_left=False, holding_right=False,
            platforms=platforms,
            camera_y=py - SCREEN_H * 0.35,
            floor=0, score=0,
            scroll_speed=0.0,
            next_plat_y=next_y,
            next_plat_idx=30,
        )


def _plat_width(floor_idx: int) -> float:
    """Platform width narrows as floor index grows."""
    if floor_idx < 10:
        return random.uniform(160, WORLD_W - 40)
    if floor_idx < 25:
        return random.uniform(100, 180)
    if floor_idx < 50:
        return random.uniform(70, 130)
    if floor_idx < 80:
        return random.uniform(55, 100)
    return random.uniform(PLAT_MIN_W, 80)


def _gen_platform(y: float, idx: int) -> Platform:
    w = _plat_width(idx)
    x = random.uniform(0, max(0, WORLD_W - w))
    return Platform(x=x, y=y, w=w, idx=idx)


def _scroll_speed_for_floor(floor: int) -> float:
    speed = 0.0
    for min_f, spd in _SPEED_BRACKETS:
        if floor >= min_f:
            speed = spd
    return speed


# -----------------------------------------------------------------------

@register_game
class IcyTowerGame(BaseGame):
    game_id      = "icy_tower"
    display_name = "Icy Tower"
    icon_char    = "🏔️"
    max_players  = 1
    supports_lan = False

    def __init__(self) -> None:
        super().__init__()
        self._state = IcyTowerState.new()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._widget: QWidget | None = None

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.icy_tower.renderer import IcyTowerRenderer
        self._widget = IcyTowerRenderer(self._state)
        return self._widget

    def start(self, mode: GameMode, players: dict[PlayerSlot, str]) -> None:
        self._state = IcyTowerState.new()
        if self._widget is not None:
            self._widget._state = self._state  # type: ignore[attr-defined]
        super().start(mode, players)
        self._timer.start(TICK_MS)

    def pause(self) -> None:
        self._timer.stop()
        super().pause()

    def resume(self) -> None:
        super().resume()
        self._timer.start(TICK_MS)

    def stop(self) -> None:
        self._timer.stop()
        super().stop()

    def key_press(self, action: Action, slot: PlayerSlot) -> None:
        if self._game_state != GameState.RUNNING:
            return
        s = self._state
        if action == Action.LEFT:
            s.holding_left = True
        elif action == Action.RIGHT:
            s.holding_right = True
        elif action == Action.FIRE and s.on_ground:
            running = abs(s.vx) >= RUN_THRESHOLD
            s.vy = JUMP_VY + (RUN_JUMP_BONUS if running else 0.0)
            s.on_ground = False

    def key_release(self, action: Action, slot: PlayerSlot) -> None:
        s = self._state
        if action == Action.LEFT:
            s.holding_left = False
        elif action == Action.RIGHT:
            s.holding_right = False

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        s = self._state

        # Horizontal movement
        if s.holding_left:
            s.vx -= 0.5
        elif s.holding_right:
            s.vx += 0.5
        else:
            s.vx *= FRICTION

        s.vx = max(-WALK_VX * 1.6, min(WALK_VX * 1.6, s.vx))

        # Gravity
        s.vy += GRAVITY
        s.on_ground = False

        # Move player
        s.px += s.vx
        s.py += s.vy

        # Wrap horizontally
        if s.px + s.PLAYER_W < 0:
            s.px = WORLD_W
        elif s.px > WORLD_W:
            s.px = -s.PLAYER_W

        # Platform collision (landing on top only, while falling)
        if s.vy >= 0:
            player_bottom = s.py + s.PLAYER_H
            for plat in s.platforms:
                if (s.px + s.PLAYER_W > plat.x and
                        s.px < plat.right and
                        player_bottom >= plat.y and
                        player_bottom <= plat.y + PLAT_H + abs(s.vy) + 2):
                    s.py = plat.y - s.PLAYER_H
                    s.vy = 0.0
                    s.on_ground = True
                    if plat.idx > s.floor:
                        s.floor = plat.idx
                        s.score = plat.idx
                        s.scroll_speed = _scroll_speed_for_floor(s.floor)
                        self.score_tick.emit({"p1": s.score})
                    break

        # Scroll camera upward when player is in the top 40%
        top_threshold = s.camera_y + SCREEN_H * 0.35
        if s.py < top_threshold:
            s.camera_y = s.py - SCREEN_H * 0.35

        # Enforce minimum scroll speed (platforms drift down even if player is stationary)
        if s.scroll_speed > 0:
            s.camera_y += s.scroll_speed
            # Also push platforms down visually (move world coords down = camera up is equivalent,
            # but we nudge camera so player falls toward death zone if not climbing)

        # Death: player bottom went below bottom of screen
        if s.py > s.camera_y + SCREEN_H + 60:
            self._die()
            return

        # Generate more platforms above as needed
        while s.next_plat_y > s.camera_y - SCREEN_H:
            s.platforms.append(_gen_platform(s.next_plat_y, s.next_plat_idx))
            s.next_plat_y -= PLAT_STEP_Y
            s.next_plat_idx += 1

        # Cull platforms well below the screen
        cutoff = s.camera_y + SCREEN_H + 200
        s.platforms = [p for p in s.platforms if p.y < cutoff]

        if self._widget is not None:
            self._widget.update()

    def _die(self) -> None:
        self._timer.stop()
        self._set_state(GameState.OVER)
        self.game_over.emit({"p1": self._state.score})
