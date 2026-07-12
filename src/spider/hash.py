"""Zobrist hashing for Spider transposition tables."""

from __future__ import annotations

import random
from typing import Dict, Optional, Tuple

from .cards import card_id
from .engine import SpiderState

# Fixed seed for reproducible hashes across runs.
random.seed(1337)
Z_COL_FD = [[random.getrandbits(64) for _ in range(52)] for _ in range(10)]
Z_COL_FU = [[random.getrandbits(64) for _ in range(52)] for _ in range(10)]
Z_STOCK = [random.getrandbits(64) for _ in range(52)]
Z_FOUNDATIONS = random.getrandbits(64)


def zobrist(state: SpiderState) -> int:
    h = Z_FOUNDATIONS ^ (len(state.foundations) * 0x9E3779B97F4A7C15)
    for ci, col in enumerate(state.columns):
        for c in col.face_down:
            h ^= Z_COL_FD[ci][card_id(c)]
        for c in col.face_up:
            h ^= Z_COL_FU[ci][card_id(c)]
    for c in state.stock:
        h ^= Z_STOCK[card_id(c)]
    return h


class TranspositionTable:
    """Best g-cost seen per position (MW moves spent to reach state)."""

    def __init__(self) -> None:
        self._best: Dict[int, int] = {}

    def clear(self) -> None:
        self._best.clear()

    def seen_worse_or_equal(self, state: SpiderState, g: int) -> bool:
        key = zobrist(state)
        prev = self._best.get(key)
        return prev is not None and prev <= g

    def store(self, state: SpiderState, g: int) -> None:
        key = zobrist(state)
        prev = self._best.get(key)
        if prev is None or g < prev:
            self._best[key] = g

    def get(self, state: SpiderState) -> Optional[int]:
        return self._best.get(zobrist(state))

    def __len__(self) -> int:
        return len(self._best)