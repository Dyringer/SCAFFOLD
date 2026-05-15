from __future__ import annotations

import math

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.asteroids.game_core import (
    AsteroidsState, GameOverEvent, HitEvent, InputState, TICK_MS, MAX_BULLETS,
)
from app.subapps.games_hub.games.asteroids.nn_brain import GeneticTrainer
from app.subapps.games_hub.games.asteroids.nn_bot import AsteroidsBot

BOT_MAX_TICKS = 60 * 60 * 3   # 3-minute hard cap per bot run


# ---------------------------------------------------------------------------
# Bot runner — owns evolution loop and per-bot fitness counters

class BotRunner:
    def __init__(self) -> None:
        self.trainer:     GeneticTrainer = GeneticTrainer()
        self.bot_index:   int            = 0
        self.current_bot: AsteroidsBot   = AsteroidsBot(self.trainer.population[0])
        self.viz_callback = None          # callable(net, activations) | None
        self._reset_counters(0.0)

    def _reset_counters(self, initial_angle: float) -> None:
        self._ticks       = 0
        self._dist        = 0.0
        self._shots_fired = 0
        self._shots_hit   = 0
        self._facing_sum  = 0.0
        self._rot_sum     = 0.0
        self._prev_angle  = initial_angle

    def reset(self, state: AsteroidsState) -> None:
        self._reset_counters(state.ship_angle)

    # ------------------------------------------------------------------
    # Per-tick API

    def decide(self, state: AsteroidsState) -> tuple[bool, bool, bool, bool]:
        want_viz = self.viz_callback is not None and self._ticks % 6 == 0
        if want_viz:
            rot_l, rot_r, thrust, fire, acts = self.current_bot.decide(state, with_activations=True)
            self.viz_callback(self.current_bot.net, acts)
        else:
            rot_l, rot_r, thrust, fire = self.current_bot.decide(state)
        return rot_l, rot_r, thrust, fire

    def record_shot_fired(self) -> None:
        self._shots_fired += 1

    def record_tick(self, state: AsteroidsState, events: list) -> None:
        self._ticks += 1
        self._dist  += math.hypot(state.ship_vx, state.ship_vy)
        self._shots_hit += sum(1 for e in events if isinstance(e, HitEvent))

        if state.asteroids:
            rad = math.radians(state.ship_angle)
            sdx, sdy = math.sin(rad), -math.cos(rad)
            nearest = min(state.asteroids,
                          key=lambda a: math.hypot(a.x - state.ship_x, a.y - state.ship_y))
            d = math.hypot(nearest.x - state.ship_x, nearest.y - state.ship_y)
            if d > 0:
                self._facing_sum += max(0.0,
                    sdx * (nearest.x - state.ship_x) / d +
                    sdy * (nearest.y - state.ship_y) / d)

        delta = abs(state.ship_angle - self._prev_angle)
        if delta > 180:
            delta = 360 - delta
        self._rot_sum    += delta
        self._prev_angle  = state.ship_angle

    @property
    def ticks(self) -> int:
        return self._ticks

    @property
    def at_tick_cap(self) -> bool:
        return self._ticks >= BOT_MAX_TICKS

    # ------------------------------------------------------------------
    # Evolution

    def advance(self, score: int) -> None:
        """Score current bot, evolve if generation complete, load next bot."""
        self.trainer.record_fitness(self.bot_index, self._compute_fitness(score))

        self.bot_index += 1
        if self.bot_index >= self.trainer.POP_SIZE:
            self.trainer.evolve()
            self.bot_index = 0

        self.current_bot = AsteroidsBot(self.trainer.population[self.bot_index])

    def get_stats(self) -> dict:
        t = self.trainer
        return {
            "generation":   t.generation,
            "bot":          self.bot_index + 1,
            "pop_size":     t.POP_SIZE,
            "best_fitness": t.best_fitness,
            "best_ever":    t.best_ever,
            "ticks":        self._ticks,
        }

    # ------------------------------------------------------------------
    # Fitness

    def _compute_fitness(self, score: int) -> float:
        ticks = max(self._ticks, 1)
        base  = self._ticks + score * 2

        if self._shots_fired > 0:
            accuracy       = self._shots_hit / self._shots_fired
            accuracy_bonus = accuracy * self._shots_hit * 30
        else:
            accuracy_bonus = 0.0

        facing_bonus     = (self._facing_sum / ticks) * ticks * 0.3
        avg_speed        = self._dist / ticks
        movement_penalty = max(0.0, 1.0 - avg_speed) * ticks * 0.5
        avg_rot          = self._rot_sum / ticks
        spin_penalty     = max(0.0, avg_rot - 6.0) * max(0.0, 1.0 - avg_speed) * ticks * 0.4

        return base + accuracy_bonus + facing_bonus - movement_penalty - spin_penalty


# ---------------------------------------------------------------------------
# Bot game — separate BaseGame subclass, no user input

class AsteroidsBotGame(BaseGame):
    game_id      = "asteroids_bot"
    display_name = "Asteroids — Bot"
    icon_char    = "🤖"

    def __init__(self) -> None:
        super().__init__()
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._bot           = BotRunner()
        self._widget: QWidget | None = None

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timers.append(self._timer)

    # ------------------------------------------------------------------
    # BaseGame interface

    def create_widget(self) -> QWidget:
        from PySide6.QtWidgets import QVBoxLayout
        from app.subapps.games_hub.games.asteroids.renderer import AsteroidsRenderer
        from app.core.settings_store import settings_store

        self._widget = AsteroidsRenderer(self._state)

        if not settings_store.get("asteroids.show_nn_visualizer", False):
            return self._widget

        from app.subapps.games_hub.games.asteroids.nn_visualizer import NNVisualizerWidget
        self._viz = NNVisualizerWidget()
        self._bot.viz_callback = self._viz.update_net

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._widget, stretch=1)
        layout.addWidget(self._viz)
        return container

    def start(self, mode: GameMode, players: dict[int, str]) -> None:
        viz_cb = self._bot.viz_callback
        self._bot = BotRunner()
        self._bot.viz_callback = viz_cb
        self._reset_state()
        self._set_state(GameState.RUNNING)
        self._push_stats()
        self._timer.start()

    # Bot games don't pause — evolution runs continuously
    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

    # No keyboard input — ship is driven entirely by the neural net

    def get_state(self) -> dict:
        s = self._state
        return {"ship_x": s.ship_x, "ship_y": s.ship_y, "score": s.score}

    # ------------------------------------------------------------------
    # BaseGame extension points

    @classmethod
    def get_settings(cls) -> list:
        from app.core.settings_store import SettingDef
        return [
            SettingDef("asteroids.show_nn_visualizer", "Show NN visualizer", "bool", False),
        ]

    def can_pause(self) -> bool:
        return False

    def toolbar_actions(self) -> list[tuple[str, object]]:
        return [("Save", self._save), ("Load", self._load)]

    # ------------------------------------------------------------------
    # Save / load

    def _save(self) -> None:
        from app.subapps.games_hub.games.asteroids.nn_brain import GeneticTrainer
        self._bot.trainer.save(GeneticTrainer.default_save_path())

    def _load(self) -> None:
        from app.subapps.games_hub.games.asteroids.nn_brain import GeneticTrainer
        from app.subapps.games_hub.games.asteroids.nn_bot import AsteroidsBot
        path = GeneticTrainer.default_save_path()
        if not path.exists():
            return
        trainer = GeneticTrainer.load(path)
        self._bot.trainer     = trainer
        self._bot.bot_index   = 0
        self._bot.current_bot = AsteroidsBot(trainer.population[0])
        self._reset_state()

    # ------------------------------------------------------------------
    # Internal

    def _reset_state(self) -> None:
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._bot.reset(self._state)
        if self._widget is not None:
            self._widget.state      = self._state
            self._widget.bot_stats  = {}

    def _push_stats(self) -> None:
        if self._widget is not None:
            self._widget.bot_stats = self._bot.get_stats()

    def _tick(self) -> None:
        from app.subapps.games_hub.games.asteroids.game_core import step

        s   = self._state
        bot = self._bot

        rot_l, rot_r, thrust, fire = bot.decide(s)

        will_fire = fire and self._fire_cooldown == 0 and len(s.bullets) < MAX_BULLETS
        if will_fire:
            bot.record_shot_fired()

        inp = InputState(left=rot_l, right=rot_r, thrust=thrust, fire=fire)
        self._fire_cooldown, events = step(s, inp, self._fire_cooldown)

        for evt in events:
            if isinstance(evt, HitEvent):
                self.score_tick.emit(f"Score: {s.score:,}")
            elif isinstance(evt, GameOverEvent):
                bot.advance(s.score)
                self._reset_state()
                self._push_stats()
                return

        bot.record_tick(s, events)

        if bot.at_tick_cap:
            bot.advance(s.score)
            self._reset_state()
            self._push_stats()
            return

        if bot.ticks % 30 == 0:
            self._push_stats()

        if self._widget is not None:
            self._widget.update()
