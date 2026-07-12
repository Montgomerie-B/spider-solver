"""Collision-safe exact state identity for exhaustive search.

A bare Zobrist integer is **not** an exact transposition identity: two
structurally different Spider positions could collide and incorrectly prune
each other. Exhaustive Opt011 mode must key transposition on a canonical
structural representation covering every field that affects legality or
continuation.

Zobrist may still be used as a preliminary filter or progress metric; Python
dict equality for search keys always compares the structural form.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .cards import Card
from .engine import SpiderState

CardT = Tuple[str, int]  # (suit, rank)
ColumnT = Tuple[Tuple[CardT, ...], Tuple[CardT, ...]]  # face_down, face_up


def card_tuple(c: Card) -> CardT:
    return (c.suit, int(c.rank))


def _column_tuple(col) -> ColumnT:
    fd = tuple(card_tuple(c) for c in col.face_down)
    fu = tuple(card_tuple(c) for c in col.face_up)
    return (fd, fu)


def _foundations_tuple(foundations: Sequence[Sequence[Card]]) -> Tuple[Tuple[CardT, ...], ...]:
    # Multiset of completed sequences — order of completion is not continuation-relevant
    seqs = [tuple(card_tuple(c) for c in seq) for seq in foundations]
    seqs.sort()
    return tuple(seqs)


@dataclass(frozen=True, slots=True)
class CanonicalStateKey:
    """Immutable structural identity for exact equality and TT keys."""

    columns: Tuple[ColumnT, ...]
    stock: Tuple[CardT, ...]
    foundations: Tuple[Tuple[CardT, ...], ...]

    def to_jsonable(self) -> Dict[str, Any]:
        return {
            "columns": [[[list(c) for c in fd], [list(c) for c in fu]] for fd, fu in self.columns],
            "stock": [list(c) for c in self.stock],
            "foundations": [[list(c) for c in seq] for seq in self.foundations],
        }

    @staticmethod
    def from_jsonable(d: Dict[str, Any]) -> "CanonicalStateKey":
        cols = []
        for fd, fu in d["columns"]:
            cols.append(
                (
                    tuple((s, int(r)) for s, r in fd),
                    tuple((s, int(r)) for s, r in fu),
                )
            )
        stock = tuple((s, int(r)) for s, r in d["stock"])
        found = tuple(tuple((s, int(r)) for s, r in seq) for seq in d["foundations"])
        return CanonicalStateKey(columns=tuple(cols), stock=stock, foundations=found)


def canonical_state_key(state: SpiderState) -> CanonicalStateKey:
    """Build the exact structural key for ``state``."""
    return CanonicalStateKey(
        columns=tuple(_column_tuple(col) for col in state.columns),
        stock=tuple(card_tuple(c) for c in state.stock),
        foundations=_foundations_tuple(state.foundations),
    )


def states_structurally_equal(a: SpiderState, b: SpiderState) -> bool:
    return canonical_state_key(a) == canonical_state_key(b)


class CollisionSafeTT:
    """Best corrected cost per exact structural state.

    Optional ``hash_fn`` forces hash collisions for tests while equality
    still uses the full ``CanonicalStateKey``.
    """

    def __init__(
        self,
        *,
        hash_fn: Optional[Callable[[CanonicalStateKey], int]] = None,
    ) -> None:
        self._hash_fn = hash_fn
        # When hash_fn is None, use dict[CanonicalStateKey, int] directly.
        self._direct: Dict[CanonicalStateKey, int] = {}
        # Bucket form for injectable hash: hash -> list[(key, cost)]
        self._buckets: Dict[int, List[Tuple[CanonicalStateKey, int]]] = {}
        self._n = 0

    def clear(self) -> None:
        self._direct.clear()
        self._buckets.clear()
        self._n = 0

    def __len__(self) -> int:
        return self._n

    def get(self, key: CanonicalStateKey) -> Optional[int]:
        if self._hash_fn is None:
            return self._direct.get(key)
        h = int(self._hash_fn(key))
        for k, c in self._buckets.get(h, []):
            if k == key:
                return c
        return None

    def store(self, key: CanonicalStateKey, cost: int) -> bool:
        """Store if improved. Return True if stored (new or improved)."""
        prev = self.get(key)
        if prev is not None and prev <= cost:
            return False
        if self._hash_fn is None:
            if prev is None:
                self._n += 1
            self._direct[key] = cost
            return True
        h = int(self._hash_fn(key))
        bucket = self._buckets.setdefault(h, [])
        for i, (k, c) in enumerate(bucket):
            if k == key:
                if c <= cost:
                    return False
                bucket[i] = (key, cost)
                return True
        bucket.append((key, cost))
        self._n += 1
        return True

    def items(self) -> Iterable[Tuple[CanonicalStateKey, int]]:
        if self._hash_fn is None:
            yield from self._direct.items()
            return
        for bucket in self._buckets.values():
            yield from bucket

    def to_serializable(self) -> List[Dict[str, Any]]:
        """Stream-friendly list of {key, cost} — no second full in-memory graph."""
        out: List[Dict[str, Any]] = []
        for k, c in self.items():
            out.append({"key": k.to_jsonable(), "cost": int(c)})
        return out

    @classmethod
    def from_serializable(
        cls,
        rows: Sequence[Dict[str, Any]],
        *,
        hash_fn: Optional[Callable[[CanonicalStateKey], int]] = None,
    ) -> "CollisionSafeTT":
        tt = cls(hash_fn=hash_fn)
        for row in rows:
            key = CanonicalStateKey.from_jsonable(row["key"])
            tt.store(key, int(row["cost"]))
        return tt
