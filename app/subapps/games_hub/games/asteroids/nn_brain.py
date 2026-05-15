from __future__ import annotations

import copy
import json
import math
import multiprocessing
import random
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np


def _save_dir() -> Path:
    from app.core.resource_manager import local_dir
    d = local_dir() / "games_hub" / "asteroids" / "neural_network"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _new_pool(pop_size: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=min(multiprocessing.cpu_count(), pop_size))


class NeuralNet:
    """Feedforward net: 25 → 32 → 16 → 4 (tanh hidden, tanh output thresholded at 0).

    Inputs are documented in nn_bot.compute_inputs; outputs are
    [rotate_left, rotate_right, thrust, fire], each thresholded at 0.
    """

    IN  = 25
    H1  = 32
    H2  = 16
    OUT = 4

    def __init__(self) -> None:
        self.w1 = np.random.normal(0, 1 / math.sqrt(self.IN),  (self.H1, self.IN)).astype(np.float32)
        self.b1 = np.zeros(self.H1, dtype=np.float32)
        self.w2 = np.random.normal(0, 1 / math.sqrt(self.H1), (self.H2, self.H1)).astype(np.float32)
        self.b2 = np.zeros(self.H2, dtype=np.float32)
        self.w3 = np.random.normal(0, 1 / math.sqrt(self.H2), (self.OUT, self.H2)).astype(np.float32)
        self.b3 = np.zeros(self.OUT, dtype=np.float32)

    def forward(self, x: list[float]) -> list[float]:
        xv  = np.asarray(x, dtype=np.float32)
        h1  = np.tanh(self.w1 @ xv + self.b1)
        h2  = np.tanh(self.w2 @ h1 + self.b2)
        out = np.tanh(self.w3 @ h2 + self.b3)
        return out.tolist()

    def forward_with_activations(self, x: list[float]) -> tuple[list[float], list[list[float]]]:
        """Returns (outputs, per-layer activations normalised to [0, 1] for display)."""
        xv  = np.asarray(x, dtype=np.float32)
        h1  = np.tanh(self.w1 @ xv + self.b1)
        h2  = np.tanh(self.w2 @ h1 + self.b2)
        out = np.tanh(self.w3 @ h2 + self.b3)
        # tanh outputs [-1,1] → remap to [0,1] for visualiser
        def _disp(v): return ((v + 1.0) / 2.0).tolist()
        return out.tolist(), [_disp(xv), _disp(h1), _disp(h2), _disp(out)]

    # ------------------------------------------------------------------
    # Serialisation

    def to_genes(self) -> list[float]:
        return np.concatenate([
            self.w1.ravel(), self.b1,
            self.w2.ravel(), self.b2,
            self.w3.ravel(), self.b3,
        ]).tolist()

    @classmethod
    def from_genes(cls, genes: list[float]) -> "NeuralNet":
        net = cls.__new__(cls)
        g   = np.asarray(genes, dtype=np.float32)
        idx = 0
        def take(shape):
            nonlocal idx
            n = int(np.prod(shape))
            arr = g[idx:idx + n].reshape(shape)
            idx += n
            return arr
        net.w1 = take((cls.H1, cls.IN))
        net.b1 = take((cls.H1,))
        net.w2 = take((cls.H2, cls.H1))
        net.b2 = take((cls.H2,))
        net.w3 = take((cls.OUT, cls.H2))
        net.b3 = take((cls.OUT,))
        return net


# ---------------------------------------------------------------------------
# Headless episode evaluator

BOT_MAX_TICKS     = 60 * 60 * 3   # 3-minute hard cap (at 60 fps equivalent)
EPISODES_PER_BOT  = 3             # Average fitness across N seeded episodes
                                  # to suppress per-run spawn-luck noise. The
                                  # same N seeds are shared across the whole
                                  # generation so every bot faces identical
                                  # challenges.


def _eval_genes(args: tuple[list[float], tuple[int, ...]]) -> float:
    """Top-level wrapper so ProcessPoolExecutor can pickle it on Windows."""
    genes, seeds = args
    return evaluate_bot(NeuralNet.from_genes(genes), seeds)


def evaluate_bot(net: NeuralNet, seeds: tuple[int, ...]) -> float:
    """Mean fitness across one episode per seed."""
    total = 0.0
    for seed in seeds:
        total += _run_episode(net, seed)
    return total / len(seeds)


def _run_episode(net: NeuralNet, seed: int) -> float:
    """Run one full episode with a seeded RNG and return fitness."""
    from app.subapps.games_hub.games.asteroids.game_core import (
        AsteroidsState, InputState, HitEvent, GameOverEvent, step, MAX_BULLETS,
    )
    from app.subapps.games_hub.games.asteroids.nn_bot import AsteroidsBot

    # game_core uses module-level random.* for spawn positions/velocities,
    # so seeding here gives every bot the same asteroid sequence.
    random.seed(seed)

    bot   = AsteroidsBot(net)
    state = AsteroidsState.new()
    fire_cooldown = 0

    ticks        = 0
    dist         = 0.0
    shots_fired  = 0
    shots_hit    = 0
    kills        = 0
    rot_sum      = 0.0
    prev_angle   = state.ship_angle

    while ticks < BOT_MAX_TICKS:
        rot_l, rot_r, thrust, fire = bot.decide(state, fire_cooldown)

        # step() decrements cooldown before checking it, so a shot fires when cooldown <= 1
        will_fire = fire and fire_cooldown <= 1 and len(state.bullets) < MAX_BULLETS
        if will_fire:
            shots_fired += 1

        inp = InputState(left=rot_l, right=rot_r, thrust=thrust, fire=fire)
        fire_cooldown, events = step(state, inp, fire_cooldown)

        ticks += 1
        dist  += math.hypot(state.ship_vx, state.ship_vy)

        for evt in events:
            if isinstance(evt, HitEvent):
                shots_hit += 1
                # A HitEvent fires on every bullet→asteroid contact, but large
                # and medium asteroids split rather than die. Only the smallest
                # size is actually killed; it awards 100 pts (ASTEROID_SCORE[-1]).
                if evt.points == 100:
                    kills += 1
            elif isinstance(evt, GameOverEvent):
                return _fitness(ticks, state.score, shots_fired, shots_hit,
                                kills, dist, rot_sum)

        delta = abs(state.ship_angle - prev_angle)
        if delta > 180:
            delta = 360 - delta
        rot_sum    += delta
        prev_angle  = state.ship_angle

    return _fitness(ticks, state.score, shots_fired, shots_hit, kills, dist, rot_sum)


def _fitness(ticks: int, score: int, shots_fired: int, shots_hit: int,
             kills: int, dist: float, rot_sum: float) -> float:
    return _fitness_breakdown(ticks, score, shots_fired, shots_hit, kills, dist, rot_sum)["total"]


def _fitness_breakdown(ticks: int, score: int, shots_fired: int, shots_hit: int,
                       kills: int, dist: float, rot_sum: float) -> dict:
    ticks        = max(ticks, 1)
    shots_missed = max(0, shots_fired - shots_hit)

    survival = ticks * 0.1
    hunting  = score * 3   # score already encodes hit quality via size (20/50/100)

    # Only penalise misses once the bot has demonstrated it can aim. Early bots
    # firing wildly is a necessary exploration phase — punishing it traps them
    # in a "never fire" local minimum.
    miss_penalty = shots_missed * 8 if kills >= 5 else 0.0

    cowardice = 0.0
    if ticks > 200 and kills == 0:
        cowardice = survival * 0.8

    avg_speed        = dist / ticks
    movement_penalty = max(0.0, 1.0 - avg_speed) * ticks * 0.5

    avg_rot      = rot_sum / ticks
    spin_penalty = max(0.0, avg_rot - 6.0) * max(0.0, 1.0 - avg_speed) * ticks * 0.4

    total = survival + hunting - miss_penalty - cowardice - movement_penalty - spin_penalty
    return {
        "survival":          round(survival, 1),
        "hunting":           round(hunting, 1),
        "miss_penalty":      round(-miss_penalty, 1),
        "cowardice_penalty": round(-cowardice, 1),
        "movement_penalty":  round(-movement_penalty, 1),
        "spin_penalty":      round(-spin_penalty, 1),
        "total":             round(total, 1),
    }


# ---------------------------------------------------------------------------
# Genetic trainer

class GeneticTrainer:
    """Population management: selection, crossover, mutation."""

    POP_SIZE       = 30
    ELITE_K        = 3
    TOURNAMENT_K   = 3
    MUTATION_RATE  = 0.15
    MUTATION_STD   = 0.3

    # Stagnation recovery thresholds
    SOFT_STAGNATION  = 10   # gens without improvement → boost mutation
    HARD_STAGNATION  = 25   # gens without improvement → full restart

    def __init__(self) -> None:
        self.generation  = 1
        self.population: list[NeuralNet] = [NeuralNet() for _ in range(self.POP_SIZE)]
        self.fitnesses:  list[float]     = [0.0] * self.POP_SIZE
        self._stagnant_gens = 0
        # All-time best genome, re-evaluated on each generation's seeds to
        # decide whether it has been dethroned. Persisted across hard restarts.
        self.champion_genes:    list[float] | None = None
        self.champion_fitness:  float              = 0.0

    def record_fitness(self, idx: int, fitness: float) -> None:
        self.fitnesses[idx] = fitness

    def evolve(self, improved: bool) -> None:
        """Breed the next generation.

        `improved` is supplied by the caller — it knows whether this
        generation's winner beat the champion on the shared seed set
        (only the caller has the seeds, so only the caller can compare
        like-for-like).
        """
        ranked = sorted(range(self.POP_SIZE), key=lambda i: self.fitnesses[i], reverse=True)

        if improved:
            self._stagnant_gens = 0
        else:
            self._stagnant_gens += 1

        # Hard restart: keep only the champion's genes, rebuild everything else randomly
        if self._stagnant_gens >= self.HARD_STAGNATION:
            self._stagnant_gens = 0
            seed_net = (NeuralNet.from_genes(self.champion_genes)
                        if self.champion_genes is not None else NeuralNet())
            self.population  = [seed_net] + [NeuralNet() for _ in range(self.POP_SIZE - 1)]
            self.fitnesses   = [0.0] * self.POP_SIZE
            self.generation += 1
            return

        # Soft boost: scale up both mutation rate and std the longer we stagnate
        stagnation_factor = min(self._stagnant_gens / self.SOFT_STAGNATION, 3.0)
        mut_rate = min(self.MUTATION_RATE * (1 + stagnation_factor), 0.6)
        mut_std  = self.MUTATION_STD  * (1 + stagnation_factor)

        elites = [self.population[i] for i in ranked[: self.ELITE_K]]
        next_pop: list[NeuralNet] = list(elites)

        # Tournament-of-K selection from the full population preserves diversity
        # vs. breeding only the elites (which collapses the gene pool fast).
        def pick() -> NeuralNet:
            contenders = random.sample(range(self.POP_SIZE), self.TOURNAMENT_K)
            winner = max(contenders, key=lambda i: self.fitnesses[i])
            return self.population[winner]

        while len(next_pop) < self.POP_SIZE:
            p1, p2 = pick(), pick()
            genes = _crossover_layerwise(p1.to_genes(), p2.to_genes())
            genes = _mutate(genes, mut_rate, mut_std)
            next_pop.append(NeuralNet.from_genes(genes))

        self.population  = next_pop
        self.fitnesses   = [0.0] * self.POP_SIZE
        self.generation += 1

    # ------------------------------------------------------------------
    # Persistence

    def save(self, path: Path) -> None:
        expected_genes = len(self.population[0].to_genes())
        data = {
            "generation":       self.generation,
            "gene_count":       expected_genes,
            "population":       [net.to_genes() for net in self.population],
            "fitnesses":        self.fitnesses,
            "champion_genes":   self.champion_genes,
            "champion_fitness": self.champion_fitness,
            "stagnant_gens":    self._stagnant_gens,
        }
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GeneticTrainer":
        data = json.loads(path.read_text(encoding="utf-8"))

        # Reject saves from a different network shape
        dummy     = NeuralNet()
        expected  = len(dummy.to_genes())
        saved_len = data.get("gene_count", len(data["population"][0]) if data["population"] else 0)
        if saved_len != expected:
            raise ValueError(
                f"Saved network has {saved_len} genes, current architecture expects {expected}. "
                "Delete the save file to start fresh."
            )
        if len(data["population"]) != cls.POP_SIZE:
            raise ValueError(
                f"Saved population size is {len(data['population'])}, current is {cls.POP_SIZE}. "
                "Delete the save file to start fresh."
            )

        trainer = cls.__new__(cls)
        trainer.generation       = data["generation"]
        trainer.population       = [NeuralNet.from_genes(g) for g in data["population"]]
        trainer.fitnesses        = data["fitnesses"]
        trainer.champion_genes   = data.get("champion_genes")
        trainer.champion_fitness = data.get("champion_fitness", 0.0)
        trainer._stagnant_gens   = data.get("stagnant_gens", 0)
        return trainer

    @staticmethod
    def default_save_path() -> Path:
        return _save_dir() / "trainer.json"


# ---------------------------------------------------------------------------
# Background evolver — runs the GA loop in a thread pool

class BackgroundEvolver:
    """Runs the GA loop forever in a background thread, evaluating each
    generation across a process pool. The display thread can read `best_net`
    at any time; it is replaced atomically at the end of each generation.
    """

    def __init__(self, trainer: GeneticTrainer | None = None) -> None:
        self.trainer      = trainer or GeneticTrainer()
        self._lock        = threading.Lock()
        # Display bot: refreshed each generation to the current gen's winner,
        # so the user can actually watch the GA learn instead of staring at
        # a frozen all-time-best.
        self._best_net:        NeuralNet | None = None
        self._best_idx:        int   = 0
        self._best_gen:        int   = self.trainer.generation
        self._best_fitness:    float = 0.0   # current gen winner's fitness
        self._champion_fitness: float = self.trainer.champion_fitness  # re-eval on latest seeds
        self._generation: int = self.trainer.generation
        self._stop_event  = threading.Event()
        self._thread:     threading.Thread | None = None
        self._pool = _new_pool(self.trainer.POP_SIZE)

    # ------------------------------------------------------------------
    # Public API

    @property
    def best_net(self) -> NeuralNet | None:
        with self._lock:
            return self._best_net

    @property
    def stats(self) -> dict:
        with self._lock:
            return {
                "generation":        self._generation,
                "best_fitness":      self._best_fitness,
                "champion_fitness":  self._champion_fitness,
                # Legacy key kept so any old display code keeps working;
                # now reflects the latest re-evaluation of the champion.
                "best_ever":         self._champion_fitness,
                "best_idx":          self._best_idx,
                "best_gen":          self._best_gen,
                "pop_size":          self.trainer.POP_SIZE,
                "stagnant":          self.trainer._stagnant_gens,
                "hard_thresh":       self.trainer.HARD_STAGNATION,
            }

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # stop() shuts down the pool; rebuild it before restarting the loop.
        if self._stop_event.is_set():
            self._pool = _new_pool(self.trainer.POP_SIZE)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="BgEvolver")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    def load(self, path: Path) -> None:
        """Hot-swap trainer from a saved file (call from main thread)."""
        trainer = GeneticTrainer.load(path)
        with self._lock:
            self.trainer           = trainer
            self._generation       = trainer.generation
            self._champion_fitness = trainer.champion_fitness
            self._best_fitness     = 0.0
            self._best_net         = None

    def save(self, path: Path) -> None:
        with self._lock:
            self.trainer.save(path)

    # ------------------------------------------------------------------
    # Background loop

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            self._run_generation()

    def _run_generation(self) -> None:
        if self._stop_event.is_set():
            return
        pop        = self.trainer.population   # snapshot — trainer mutates after evolve()
        genes_list = [net.to_genes() for net in pop]

        # Shared seeds for this generation: every bot — including the champion
        # — faces the same N episodes, so fitnesses are directly comparable.
        # Seeds change each generation to prevent overfitting to a fixed
        # challenge set.
        seeds = tuple(random.randrange(2**31) for _ in range(EPISODES_PER_BOT))

        # Submit the population, plus the champion (if any) re-evaluated on the
        # same seeds. Champion uses sentinel index -1 so we can pull its result
        # out separately.
        CHAMPION_IDX = -1
        champion_genes = self.trainer.champion_genes

        try:
            futures = {
                self._pool.submit(_eval_genes, (g, seeds)): i
                for i, g in enumerate(genes_list)
            }
            if champion_genes is not None:
                futures[self._pool.submit(_eval_genes, (champion_genes, seeds))] = CHAMPION_IDX
        except RuntimeError:
            return  # pool was shut down between the check and the submit

        champion_fitness_now: float | None = None
        for fut in as_completed(futures):
            if self._stop_event.is_set():
                return
            idx     = futures[fut]
            fitness = fut.result()
            if idx == CHAMPION_IDX:
                champion_fitness_now = fitness
            else:
                self.trainer.record_fitness(idx, fitness)

        # Current generation's best
        best_idx     = max(range(len(pop)), key=lambda i: self.trainer.fitnesses[i])
        best_fitness = self.trainer.fitnesses[best_idx]
        best_net     = pop[best_idx]

        # Improvement test on like-for-like seeds. If we have no champion yet
        # (first ever generation), this gen's winner becomes champion by default.
        if champion_genes is None:
            improved = True
            new_champion_fitness = best_fitness
            new_champion_genes   = best_net.to_genes()
        else:
            improved = best_fitness > champion_fitness_now
            if improved:
                new_champion_fitness = best_fitness
                new_champion_genes   = best_net.to_genes()
            else:
                new_champion_fitness = champion_fitness_now or 0.0
                new_champion_genes   = champion_genes

        self.trainer.champion_genes   = new_champion_genes
        self.trainer.champion_fitness = new_champion_fitness

        # Always publish the current-gen winner for display, so the user can
        # actually see the GA learn (no more "frozen on gen 4" effect).
        with self._lock:
            self._best_net         = copy.deepcopy(best_net)
            self._best_idx         = best_idx + 1   # 1-based for display
            self._best_gen         = self.trainer.generation
            self._best_fitness     = best_fitness
            self._champion_fitness = new_champion_fitness
            self._generation       = self.trainer.generation

        self.trainer.evolve(improved)


# ---------------------------------------------------------------------------
# Helpers

def _crossover_layerwise(a: list[float], b: list[float]) -> list[float]:
    """Each entire layer (weights + biases) inherited from parent A or B with 50/50 chance.

    Preserves co-adapted weight groups within a layer, which works better than
    uniform gene-level crossover for small feedforward nets.
    """
    n = NeuralNet
    s0 = n.H1 * n.IN
    s1 = s0 + n.H1
    s2 = s1 + n.H2 * n.H1
    s3 = s2 + n.H2
    s4 = s3 + n.OUT * n.H2
    slices = [(0, s0), (s0, s1), (s1, s2), (s2, s3), (s3, s4), (s4, len(a))]
    av, bv = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    result = av.copy()
    for lo, hi in slices:
        if random.random() < 0.5:
            result[lo:hi] = bv[lo:hi]
    return result.tolist()


def _mutate(genes: list[float], rate: float, std: float) -> list[float]:
    gv    = np.asarray(genes, dtype=np.float32)
    mask  = np.random.random(len(gv)) < rate
    gv[mask] += np.random.normal(0, std, mask.sum()).astype(np.float32)
    return gv.tolist()
