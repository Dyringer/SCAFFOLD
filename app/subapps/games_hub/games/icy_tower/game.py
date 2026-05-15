from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
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

# Segment lengths in floors (random range)
SEG_MIN        = 20
SEG_MAX        = 100

# Scroll speed brackets — (min_floor, scroll_px_per_frame)
_SPEED_BRACKETS = [
    (0,   0.0),
    (10,  0.4),
    (25,  0.8),
    (50,  1.3),
    (80,  1.9),
    (120, 2.6),
]


@dataclass
class _Input:
    left:  bool = False
    right: bool = False
    jump:  bool = False


# -----------------------------------------------------------------------

@dataclass
class Platform:
    x: float
    y: float
    w: float
    idx: int = 0
    h: float = PLAT_H
    crumble: bool = False   # disappears after player leaves it
    crumble_timer: int = 0  # counts down to removal; >0 means crumbling

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h


@dataclass
class Segment:
    """A vertical band of the tower with consistent wall behaviour."""
    floor_start: int
    floor_end: int      # exclusive
    walled: bool

    def contains(self, floor: int) -> bool:
        return self.floor_start <= floor < self.floor_end

    @property
    def y_top(self) -> float:
        """World Y of the TOP of this segment (smaller Y = higher up)."""
        return PLAT_START_Y - self.floor_end * PLAT_STEP_Y

    @property
    def y_bottom(self) -> float:
        """World Y of the BOTTOM of this segment."""
        return PLAT_START_Y - self.floor_start * PLAT_STEP_Y


def _next_segment(prev: Segment) -> Segment:
    length = random.randint(SEG_MIN, SEG_MAX)
    return Segment(
        floor_start=prev.floor_end,
        floor_end=prev.floor_end + length,
        walled=not prev.walled,   # alternate
    )


@dataclass
class IcyTowerState:
    px: float                       # player left edge (world coords)
    py: float                       # player top edge (world coords)
    vx: float
    vy: float
    on_ground: bool
    on_wall: int                    # -1 = left wall, 0 = none, 1 = right wall
    standing_on: Platform | None    # platform the player stood on last frame
    platforms: list[Platform]
    segments: list[Segment]
    camera_y: float                 # world y at top of screen
    floor: int                      # highest platform index ever landed
    score: int
    scroll_speed: float
    next_plat_y: float              # y of next platform to generate above
    next_plat_idx: int              # monotonic counter for generated platforms

    PLAYER_W: float = 28.0
    PLAYER_H: float = 36.0

    def walled_at(self, py: float) -> bool:
        """Return True if the world Y position is inside a walled segment."""
        for seg in self.segments:
            if seg.y_top <= py <= seg.y_bottom:
                return seg.walled
        return False

    @staticmethod
    def new() -> "IcyTowerState":
        ground = Platform(x=10, y=PLAT_START_Y, w=PLAT_START_W, idx=0)
        platforms = [ground]

        # Pre-generate platforms to fill two screens
        next_y = PLAT_START_Y - PLAT_STEP_Y
        for i in range(1, 30):
            platforms.append(_gen_platform(next_y, i))
            next_y -= PLAT_STEP_Y

        # First segment is open (no walls), alternates from there
        seg0 = Segment(floor_start=0, floor_end=random.randint(SEG_MIN, SEG_MAX), walled=False)
        seg1 = _next_segment(seg0)
        seg2 = _next_segment(seg1)

        px = WORLD_W / 2 - 14
        py = ground.y - 36

        return IcyTowerState(
            px=px, py=py, vx=0, vy=0,
            on_ground=True, on_wall=0, standing_on=None,
            platforms=platforms,
            segments=[seg0, seg1, seg2],
            camera_y=py - SCREEN_H * 0.35,
            floor=0, score=0,
            scroll_speed=0.0,
            next_plat_y=next_y,
            next_plat_idx=30,
        )


def _plat_width(floor_idx: int) -> float:
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
    crumble = idx > 5 and random.random() < 1 / 25
    return Platform(x=x, y=y, w=w, idx=idx, crumble=crumble)


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

    def __init__(self) -> None:
        super().__init__()
        self._state = IcyTowerState.new()
        self._input = _Input()
        self._jump_held = False
        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)
        self._widget: QWidget | None = None

    def create_widget(self) -> QWidget:
        from app.subapps.games_hub.games.icy_tower.renderer import IcyTowerRenderer
        self._widget = IcyTowerRenderer(self._state, self._input)
        return self._widget

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        self._state = IcyTowerState.new()
        self._input.left = self._input.right = self._input.jump = False
        self._jump_held = False
        if self._widget is not None:
            self._widget.state = self._state
            self._widget.clear_held()
        super().start(mode, players)
        self._timer.start()

    # ------------------------------------------------------------------

    def _tick(self) -> None:
        s = self._state
        inp = self._input
        walled = s.walled_at(s.py)

        # Rising-edge jump
        jump_pressed = inp.jump and not self._jump_held
        self._jump_held = inp.jump
        if jump_pressed:
            if s.on_ground:
                run_bonus = RUN_JUMP_BONUS if abs(s.vx) > RUN_THRESHOLD else 0.0
                s.vy = JUMP_VY + run_bonus
                s.on_ground = False
            elif s.on_wall != 0:
                s.vy = JUMP_VY * 0.9
                s.vx = -s.on_wall * WALK_VX * 1.2
                s.on_wall = 0

        # Horizontal movement
        if inp.left:
            s.vx -= 0.5
        elif inp.right:
            s.vx += 0.5
        else:
            s.vx *= FRICTION

        s.vx = max(-WALK_VX * 1.6, min(WALK_VX * 1.6, s.vx))

        # Gravity — reduced when sliding down a wall
        if s.on_wall != 0 and s.vy > 0:
            s.vy += GRAVITY * 0.35
            s.vy = min(s.vy, 3.0)
        else:
            s.vy += GRAVITY
        s.on_ground = False
        s.on_wall = 0

        # Move player
        s.px += s.vx
        s.py += s.vy

        # Horizontal boundary — walls or open depending on segment
        if walled:
            if s.px <= 0:
                s.px = 0
                if s.vy > 0 and inp.left:
                    s.on_wall = -1
                s.vx = 0.0
            elif s.px + s.PLAYER_W >= WORLD_W:
                s.px = WORLD_W - s.PLAYER_W
                if s.vy > 0 and inp.right:
                    s.on_wall = 1
                s.vx = 0.0
        else:
            # Open section — wrap around
            if s.px + s.PLAYER_W < 0:
                s.px = WORLD_W
            elif s.px > WORLD_W:
                s.px = -s.PLAYER_W

        # Platform collision (landing on top only, while falling)
        landed_plat: Platform | None = None
        if s.vy >= 0:
            player_bottom = s.py + s.PLAYER_H
            for plat in s.platforms:
                if plat.crumble_timer > 0:
                    continue
                if (s.px + s.PLAYER_W > plat.x and
                        s.px < plat.right and
                        player_bottom >= plat.y and
                        player_bottom <= plat.y + PLAT_H + abs(s.vy) + 2):
                    s.py = plat.y - s.PLAYER_H
                    s.vy = 0.0
                    s.on_ground = True
                    landed_plat = plat
                    if plat.idx > s.floor:
                        s.floor = plat.idx
                        s.score = plat.idx
                        s.scroll_speed = _scroll_speed_for_floor(s.floor)
                        self.score_tick.emit(f"Floor: {s.score}")
                    break

        prev = s.standing_on
        if prev is not None and prev.crumble and landed_plat is not prev:
            prev.crumble_timer = 12  # ~200 ms visible before removal

        s.standing_on = landed_plat

        next_platforms = []
        for p in s.platforms:
            if p.crumble_timer > 0:
                p.crumble_timer -= 1
                if p.crumble_timer > 0:
                    next_platforms.append(p)
            else:
                next_platforms.append(p)
        s.platforms = next_platforms

        # Scroll camera upward when player is in the top 40%
        if s.py < s.camera_y + SCREEN_H * 0.35:
            s.camera_y = s.py - SCREEN_H * 0.35

        if s.scroll_speed > 0:
            s.camera_y += s.scroll_speed

        # Death: player fell below screen
        if s.py > s.camera_y + SCREEN_H + 60:
            self._die()
            return

        # Generate platforms above as needed
        while s.next_plat_y > s.camera_y - SCREEN_H:
            s.platforms.append(_gen_platform(s.next_plat_y, s.next_plat_idx))
            s.next_plat_y -= PLAT_STEP_Y
            s.next_plat_idx += 1

        # Extend segments ahead of the highest generated floor
        while s.segments[-1].floor_end < s.next_plat_idx + SEG_MAX:
            s.segments.append(_next_segment(s.segments[-1]))

        # Cull platforms and segments well below the screen
        cutoff_y = s.camera_y + SCREEN_H + 200
        s.platforms = [p for p in s.platforms if p.y < cutoff_y]

        if self._widget is not None:
            self._widget.update()

    def _die(self) -> None:
        self._set_state(GameState.OVER)
        self.game_over.emit(GameResult(scores={0: self._state.score}, winner=None))
