"""Exact target-monotonic pruning for Opt012 corridor (commands 43–51).

Not heuristic: only rejects states that cannot reconnect to the exact target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from spider.engine import SpiderState
from spider.state_identity import card_tuple


@dataclass
class PruneStats:
    face_down_prefix: int = 0
    foundation: int = 0
    stock: int = 0
    reveal_bound: int = 0
    accepted: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "face_down_prefix": self.face_down_prefix,
            "foundation": self.foundation,
            "stock": self.stock,
            "reveal_bound": self.reveal_bound,
            "accepted": self.accepted,
        }


@dataclass
class TargetMonotonicFilter:
    """Corridor filter relative to fixed start/target snapshots."""

    target: SpiderState
    start: SpiderState
    cost_ceiling: int = 7
    stats: PruneStats = field(default_factory=PruneStats)

    # Precomputed target face-down prefixes (bottom-to-top as stored in engine)
    target_fd: Tuple[Tuple[Tuple[str, int], ...], ...] = field(init=False)
    target_found_multiset: Tuple[Tuple[Tuple[str, int], ...], ...] = field(init=False)
    start_found_multiset: Tuple[Tuple[Tuple[str, int], ...], ...] = field(init=False)
    target_stock: Tuple[Tuple[str, int], ...] = field(init=False)
    # Cards that remain face-down in target, per column (must still be hidden or deeper)
    target_fd_sets: Tuple[frozenset, ...] = field(init=False)

    def __post_init__(self) -> None:
        self.target_fd = tuple(
            tuple(card_tuple(c) for c in col.face_down) for col in self.target.columns
        )
        self.target_found_multiset = tuple(
            sorted(tuple(card_tuple(c) for c in seq) for seq in self.target.foundations)
        )
        self.start_found_multiset = tuple(
            sorted(tuple(card_tuple(c) for c in seq) for seq in self.start.foundations)
        )
        self.target_stock = tuple(card_tuple(c) for c in self.target.stock)
        self.target_fd_sets = tuple(frozenset(seq) for seq in self.target_fd)

    def remaining_required_reveals(self, st: SpiderState) -> int:
        """Minimum paid moves still needed solely for required exposures.

        Each column may need to expose cards until its face-down prefix equals
        the target's. One tableau move exposes at most one face-down card
        (maybe_flip after removing face-up), and that move costs 1 under
        corrected MW when face-down remain (cannot be free entire-column reloc).
        """
        need = 0
        for i, col in enumerate(st.columns):
            cur_fd = len(col.face_down)
            tgt_fd = len(self.target_fd[i])
            if cur_fd > tgt_fd:
                need += cur_fd - tgt_fd
            # if cur_fd == tgt_fd, prefix must match (checked elsewhere)
            # if cur_fd < tgt_fd, impossible (checked elsewhere)
        return need

    def reject_reason(self, st: SpiderState, *, current_cost: int) -> Optional[str]:
        # Stock: no deals — must match target stock exactly for this corridor
        if tuple(card_tuple(c) for c in st.stock) != self.target_stock:
            return "stock"
        # Foundations monotonic: for this corridor start==target foundations (0).
        # Any extra foundation is incompatible with exact target equality.
        cur_found = tuple(
            sorted(tuple(card_tuple(c) for c in seq) for seq in st.foundations)
        )
        if len(cur_found) > len(self.target_found_multiset):
            return "foundation"
        # target foundations must be a multiset extension of current — if target
        # has fewer than current, impossible; if equal, must match; if more, current
        # must be subset (prefix of completion). For exact final foundations equal
        # to start here:
        if cur_found != self.target_found_multiset and len(self.target_found_multiset) == len(
            self.start_found_multiset
        ):
            # no foundations may be completed beyond start when start==target
            if cur_found != self.start_found_multiset:
                return "foundation"

        # Face-down prefix invariant (engine stores face_down as bottom-to-top,
        # index 0 = deepest). Target prefix of length T must equal candidate's
        # deepest T cards when candidate has F >= T face-down.
        for i, col in enumerate(st.columns):
            cur = tuple(card_tuple(c) for c in col.face_down)
            tgt = self.target_fd[i]
            if len(cur) < len(tgt):
                return "face_down_prefix"
            # deepest len(tgt) cards of current must equal target face-down sequence
            if cur[: len(tgt)] != tgt:
                return "face_down_prefix"
            # any card still face-down in target must not appear face-up if that
            # would require it having been removed from deeper than target prefix
            # — covered by prefix equality + length.

        # Reveal lower bound
        rem = self.remaining_required_reveals(st)
        if current_cost + rem > self.cost_ceiling:
            return "reveal_bound"
        return None

    def accept(self, st: SpiderState, *, current_cost: int) -> bool:
        reason = self.reject_reason(st, current_cost=current_cost)
        if reason is None:
            self.stats.accepted += 1
            return True
        if reason == "face_down_prefix":
            self.stats.face_down_prefix += 1
        elif reason == "foundation":
            self.stats.foundation += 1
        elif reason == "stock":
            self.stats.stock += 1
        elif reason == "reveal_bound":
            self.stats.reveal_bound += 1
        return False
