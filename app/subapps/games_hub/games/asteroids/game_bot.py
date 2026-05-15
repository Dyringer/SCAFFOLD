from __future__ import annotations

import math

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QWidget

from app.subapps.games_hub.base_game import BaseGame, GameMode, GameResult, GameState
from app.subapps.games_hub.games.asteroids.game_core import (
    AsteroidsState, GameOverEvent, HitEvent, InputState, TICK_MS, MAX_BULLETS,
)
from app.subapps.games_hub.games.asteroids.nn_brain import BackgroundEvolver, GeneticTrainer
from app.subapps.games_hub.games.asteroids.nn_bot import AsteroidsBot


# ---------------------------------------------------------------------------
# Display runner — drives one live bot (always the current best genome)

class BotRunner:
    def __init__(self, evolver: BackgroundEvolver) -> None:
        self.evolver       = evolver
        self.viz_callback  = None
        self._ticks        = 0
        self._live_bot_idx = 0
        self._live_bot_gen = 0
        self._current_bot  = self._load_best()
        self._reset_counters()

    def _load_best(self) -> AsteroidsBot:
        s   = self.evolver.stats
        net = self.evolver.best_net
        if net is None:
            from app.subapps.games_hub.games.asteroids.nn_brain import NeuralNet
            net = NeuralNet()
        self._live_bot_idx = s["best_idx"]
        self._live_bot_gen = s["best_gen"]
        return AsteroidsBot(net)

    def _reset_counters(self) -> None:
        self._ticks        = 0
        self._shots_fired  = 0
        self._shots_hit    = 0
        self._kills        = 0
        self._dist         = 0.0
        self._rot_sum      = 0.0
        self._prev_angle   = 0.0

    def reset(self, state: AsteroidsState) -> None:
        self._current_bot = self._load_best()
        self._reset_counters()
        self._prev_angle = state.ship_angle

    def record_tick(self, state: AsteroidsState, fired: bool, events: list) -> None:
        self._ticks += 1
        self._dist  += math.hypot(state.ship_vx, state.ship_vy)
        if fired:
            self._shots_fired += 1
        for evt in events:
            if isinstance(evt, HitEvent):
                self._shots_hit += 1
                # HitEvent fires for every bullet→asteroid contact; only the
                # smallest size is actually destroyed (100 pts). Large/medium
                # asteroids split instead of dying.
                if evt.points == 100:
                    self._kills += 1
        delta = abs(state.ship_angle - self._prev_angle)
        if delta > 180:
            delta = 360 - delta
        self._rot_sum   += delta
        self._prev_angle = state.ship_angle

    def decide(self, state: AsteroidsState, fire_cooldown: int = 0) -> tuple[bool, bool, bool, bool]:
        if self.viz_callback is not None and self._ticks % 6 == 0:
            rot_l, rot_r, thrust, fire, acts = self._current_bot.decide_with_activations(state, fire_cooldown)
            self.viz_callback(self._current_bot.net, acts)
            return rot_l, rot_r, thrust, fire
        return self._current_bot.decide(state, fire_cooldown)

    def episode_breakdown(self, score: int) -> dict:
        from app.subapps.games_hub.games.asteroids.nn_brain import _fitness_breakdown
        shots_missed = max(0, self._shots_fired - self._shots_hit)
        return {
            "bot_idx":      self._live_bot_idx,
            "bot_gen":      self._live_bot_gen,
            "ticks":        self._ticks,
            "game_score":   score,
            "kills":        self._kills,
            "shots_fired":  self._shots_fired,
            "shots_hit":    self._shots_hit,
            "shots_missed": shots_missed,
            "accuracy_pct": round(self._shots_hit / self._shots_fired * 100, 1) if self._shots_fired else 0.0,
            "fitness":      _fitness_breakdown(self._ticks, score, self._shots_fired,
                                               self._shots_hit, self._kills,
                                               self._dist, self._rot_sum),
        }

    def get_stats(self) -> dict:
        s = self.evolver.stats
        return {
            "generation":    s["generation"],
            "bot":           self._live_bot_idx,
            "bot_gen":       self._live_bot_gen,
            "pop_size":      s["pop_size"],
            "best_fitness":  s["best_fitness"],       # current-gen winner
            "best_ever":     s["champion_fitness"],   # champion on latest seeds
            "best_ever_gen": s["best_gen"],
            "ticks":         self._ticks,
            "stagnant":      s["stagnant"],
            "hard_thresh":   s["hard_thresh"],
        }


# ---------------------------------------------------------------------------
# Bot game — drives the live display, background evolver runs independently

class AsteroidsBotGame(BaseGame):
    game_id      = "asteroids_bot"
    display_name = "Asteroids — Bot"
    icon_char    = "🤖"

    # Hard cap for the display bot (3 min); background bots have their own cap
    _DISPLAY_MAX_TICKS = 60 * 60 * 3

    def __init__(self) -> None:
        super().__init__()
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._evolver       = BackgroundEvolver()
        self._bot           = BotRunner(self._evolver)
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
        self._evolver = BackgroundEvolver()
        self._bot = BotRunner(self._evolver)
        self._bot.viz_callback = viz_cb
        self._evolver.start()
        self._reset_state()
        self._set_state(GameState.RUNNING)
        self._push_stats()
        self._timer.start()

    def stop(self) -> None:
        self._evolver.stop()
        super().stop()

    # Bot games don't pause — evolution runs continuously
    def pause(self) -> None:
        pass

    def resume(self) -> None:
        pass

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
        return [("Skip", self._skip), ("Save", self._save), ("Load", self._load)]

    # ------------------------------------------------------------------
    # Save / load

    def _skip(self) -> None:
        self._write_episode_stats(self._state.score)
        self._reset_state()
        self._push_stats()

    def _save(self) -> None:
        self._evolver.save(GeneticTrainer.default_save_path())

    def _load(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        path = GeneticTrainer.default_save_path()
        if not path.exists():
            return
        self._evolver.stop()
        try:
            self._evolver.load(path)
        except ValueError as exc:
            QMessageBox.warning(self._widget, "Load failed", str(exc))
            self._evolver.start()
            return
        self._evolver.start()
        self._reset_state()

    # ------------------------------------------------------------------
    # Internal

    def _reset_state(self) -> None:
        self._state         = AsteroidsState.new()
        self._fire_cooldown = 0
        self._bot.reset(self._state)
        if self._widget is not None:
            self._widget.state     = self._state
            self._widget.bot_stats = {}

    def _push_stats(self) -> None:
        if self._widget is not None:
            self._widget.bot_stats = self._bot.get_stats()

    def _tick(self) -> None:
        from app.subapps.games_hub.games.asteroids.game_core import step

        s   = self._state
        bot = self._bot

        rot_l, rot_r, thrust, fire = bot.decide(s, self._fire_cooldown)

        # step() decrements cooldown before checking it, so a shot fires when cooldown <= 1
        will_fire = fire and self._fire_cooldown <= 1 and len(s.bullets) < MAX_BULLETS
        inp = InputState(left=rot_l, right=rot_r, thrust=thrust, fire=fire)
        self._fire_cooldown, events = step(s, inp, self._fire_cooldown)

        bot.record_tick(s, will_fire, events)

        for evt in events:
            if isinstance(evt, HitEvent):
                self.score_tick.emit(f"Score: {s.score:,}")
            elif isinstance(evt, GameOverEvent):
                self._write_episode_stats(s.score)
                self._reset_state()
                self._push_stats()
                return

        if bot._ticks >= self._DISPLAY_MAX_TICKS:
            self._write_episode_stats(s.score)
            self._reset_state()
            self._push_stats()
            return

        if bot._ticks % 30 == 0:
            self._push_stats()

        if self._widget is not None:
            self._widget.update()

    def _write_episode_stats(self, score: int) -> None:
        import json
        breakdown = self._bot.episode_breakdown(score)
        path = GeneticTrainer.default_save_path().parent / "live_stats.json"
        path.write_text(json.dumps(breakdown, indent=2), encoding="utf-8")
