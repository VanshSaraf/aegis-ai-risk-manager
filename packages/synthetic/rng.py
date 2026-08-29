import hashlib
from collections.abc import Sequence
from typing import TypeVar

import numpy as np

ChoiceT = TypeVar("ChoiceT")


class RandomStream:
    """The only source of randomness used by the synthetic world."""

    def __init__(self, seed: int, name: str = "root") -> None:
        digest = hashlib.sha256(f"{seed}:{name}".encode()).digest()
        entropy = [seed, *np.frombuffer(digest[:16], dtype=np.uint32).tolist()]
        self._generator = np.random.Generator(np.random.PCG64(np.random.SeedSequence(entropy)))
        self.seed = seed
        self.name = name

    def child(self, name: str) -> "RandomStream":
        return RandomStream(self.seed, f"{self.name}/{name}")

    def probability(self, probability: float) -> bool:
        return bool(self._generator.random() < probability)

    def integer(self, low: int, high: int) -> int:
        return int(self._generator.integers(low, high))

    def uniform(self, low: float = 0.0, high: float = 1.0) -> float:
        return float(self._generator.uniform(low, high))

    def lognormal(self, mean: float, sigma: float) -> float:
        return float(self._generator.lognormal(mean, sigma))

    def choice(
        self, values: Sequence[ChoiceT], probabilities: Sequence[float] | None = None
    ) -> ChoiceT:
        index = int(self._generator.choice(len(values), p=probabilities))
        return values[index]

    def weighted_counts(self, total: int, weights: dict[ChoiceT, float]) -> dict[ChoiceT, int]:
        keys = list(weights)
        if total == 0:
            return dict.fromkeys(keys, 0)
        raw = np.array([weights[key] for key in keys], dtype=float) * total
        counts = np.floor(raw).astype(int)
        remainder = total - int(counts.sum())
        fractions = raw - counts
        for index in np.argsort(-fractions, kind="stable")[:remainder]:
            counts[index] += 1
        return {key: int(count) for key, count in zip(keys, counts, strict=True)}
