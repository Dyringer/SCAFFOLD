from __future__ import annotations

import json
import math
import random
from pathlib import Path


def _save_dir() -> Path:
    from app.core.resource_manager import local_dir
    d = local_dir() / "games_hub" / "asteroids" / "neural_network"
    d.mkdir(parents=True, exist_ok=True)
    return d


class NeuralNet:
    """Feedforward net: 12 → 16 → 16 → 4 (ReLU hidden, sigmoid output)."""

    IN  = 12
    H1  = 16
    H2  = 16
    OUT = 4

    def __init__(self) -> None:
        self.w1 = [[random.gauss(0, 1 / math.sqrt(self.IN))  for _ in range(self.IN)]  for _ in range(self.H1)]
        self.b1 = [0.0] * self.H1
        self.w2 = [[random.gauss(0, 1 / math.sqrt(self.H1)) for _ in range(self.H1)] for _ in range(self.H2)]
        self.b2 = [0.0] * self.H2
        self.w3 = [[random.gauss(0, 1 / math.sqrt(self.H2)) for _ in range(self.H2)] for _ in range(self.OUT)]
        self.b3 = [0.0] * self.OUT

    def forward(self, x: list[float]) -> list[float]:
        h1  = [_relu(sum(self.w1[i][j] * x[j]   for j in range(self.IN))  + self.b1[i]) for i in range(self.H1)]
        h2  = [_relu(sum(self.w2[i][j] * h1[j]  for j in range(self.H1)) + self.b2[i]) for i in range(self.H2)]
        out = [_sigmoid(sum(self.w3[i][j] * h2[j] for j in range(self.H2)) + self.b3[i]) for i in range(self.OUT)]
        return out

    def forward_with_activations(self, x: list[float]) -> tuple[list[float], list[list[float]]]:
        """Returns (outputs, per-layer activations normalised to [0, 1] for display)."""
        h1  = [_relu(sum(self.w1[i][j] * x[j]   for j in range(self.IN))  + self.b1[i]) for i in range(self.H1)]
        h2  = [_relu(sum(self.w2[i][j] * h1[j]  for j in range(self.H1)) + self.b2[i]) for i in range(self.H2)]
        out = [_sigmoid(sum(self.w3[i][j] * h2[j] for j in range(self.H2)) + self.b3[i]) for i in range(self.OUT)]
        h1_max = max(max(h1), 1e-6)
        h2_max = max(max(h2), 1e-6)
        x_disp = [(v + 1.0) / 2.0 for v in x]
        return out, [x_disp, [v / h1_max for v in h1], [v / h2_max for v in h2], out]

    # ------------------------------------------------------------------
    # Serialisation

    def to_genes(self) -> list[float]:
        genes: list[float] = []
        for row in self.w1: genes.extend(row)
        genes.extend(self.b1)
        for row in self.w2: genes.extend(row)
        genes.extend(self.b2)
        for row in self.w3: genes.extend(row)
        genes.extend(self.b3)
        return genes

    @classmethod
    def from_genes(cls, genes: list[float]) -> "NeuralNet":
        net = cls.__new__(cls)
        it = iter(genes)

        def take(n: int) -> list[float]:
            return [next(it) for _ in range(n)]

        net.w1 = [take(cls.IN)  for _ in range(cls.H1)]
        net.b1 = take(cls.H1)
        net.w2 = [take(cls.H1) for _ in range(cls.H2)]
        net.b2 = take(cls.H2)
        net.w3 = [take(cls.H2) for _ in range(cls.OUT)]
        net.b3 = take(cls.OUT)
        return net


# ---------------------------------------------------------------------------
# Genetic trainer

class GeneticTrainer:
    """Population management: selection, crossover, mutation."""

    POP_SIZE       = 20
    ELITE_K        = 4
    MUTATION_RATE  = 0.15
    MUTATION_STD   = 0.3

    def __init__(self) -> None:
        self.generation  = 1
        self.population: list[NeuralNet] = [NeuralNet() for _ in range(self.POP_SIZE)]
        self.fitnesses:  list[float]     = [0.0] * self.POP_SIZE
        self.best_fitness = 0.0
        self.best_ever    = 0.0

    def record_fitness(self, idx: int, fitness: float) -> None:
        self.fitnesses[idx] = fitness
        if fitness > self.best_fitness:
            self.best_fitness = fitness

    def evolve(self) -> None:
        self.best_ever = max(self.best_ever, self.best_fitness)
        ranked = sorted(range(self.POP_SIZE), key=lambda i: self.fitnesses[i], reverse=True)
        elites = [self.population[i] for i in ranked[: self.ELITE_K]]

        next_pop: list[NeuralNet] = list(elites)
        while len(next_pop) < self.POP_SIZE:
            p1, p2 = random.sample(elites, 2)
            genes = _crossover(p1.to_genes(), p2.to_genes())
            genes = _mutate(genes, self.MUTATION_RATE, self.MUTATION_STD)
            next_pop.append(NeuralNet.from_genes(genes))

        self.population   = next_pop
        self.fitnesses    = [0.0] * self.POP_SIZE
        self.best_fitness = 0.0
        self.generation  += 1

    # ------------------------------------------------------------------
    # Persistence

    def save(self, path: Path) -> None:
        data = {
            "generation":  self.generation,
            "best_ever":   self.best_ever,
            "population":  [net.to_genes() for net in self.population],
            "fitnesses":   self.fitnesses,
        }
        path.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "GeneticTrainer":
        data = json.loads(path.read_text(encoding="utf-8"))
        trainer = cls.__new__(cls)
        trainer.generation   = data["generation"]
        trainer.best_ever    = data["best_ever"]
        trainer.best_fitness = 0.0
        trainer.population   = [NeuralNet.from_genes(g) for g in data["population"]]
        trainer.fitnesses    = data["fitnesses"]
        return trainer

    @staticmethod
    def default_save_path() -> Path:
        return _save_dir() / "trainer.json"


# ---------------------------------------------------------------------------
# Helpers

def _relu(x: float) -> float:
    return x if x > 0 else 0.0


def _sigmoid(x: float) -> float:
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def _crossover(a: list[float], b: list[float]) -> list[float]:
    point = random.randint(1, len(a) - 1)
    return a[:point] + b[point:]


def _mutate(genes: list[float], rate: float, std: float) -> list[float]:
    return [g + random.gauss(0, std) if random.random() < rate else g for g in genes]
