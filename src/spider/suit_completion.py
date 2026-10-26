"""Suit-completion proximity. An ordering estimate, never a bound.

One left-to-right scan of the ten columns and the stock. It asks how close
the physical tableau is to a removable same-suit king-to-ace sequence.
It does not plan an excavation, does not invent a multi-step line, and
does not drop a legal successor.

Two copies of each rank exist. A suit contributes its single best run.
Missing ranks pay the best remaining copy once, so two buried copies of
the same rank are not stacked into an impossible double foundation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Sequence, Tuple

from spider.cards import Card
from spider.deal import validate_four_suit_two_deck
from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state

SUITS = ("s", "h", "d", "c")
LENGTH_WEIGHT = 100
KING_BONUS = 250
ACE_BONUS = 80
JOIN_BONUS = 40
COVER_BASE = 80
COVER_PER_CARD = 20
PENALTY_EXPOSED = 2
PENALTY_FACE_UP = 8
PENALTY_FACE_DOWN = 20
PENALTY_STOCK = 28
PENALTY_ABSENT = 40


@dataclass(frozen=True)
class ProximityDetail:
    """One state's ordering features. ``score`` is higher when closer."""

    score: int
    by_suit: Dict[str, int]
    best_length: Dict[str, int]
    longest_exposed: int
    complete_exposed: int
    near_blocked: int
    near_accessible: int
    runs: Tuple[Tuple[str, int, bool], ...]


def opening_from_seed(seed: int) -> SpiderState:
    """A reproducible two-deck four-suit opening. Not deal 4925153."""

    cards = [
        Card(suit, rank)
        for _copy in range(2)
        for suit in SUITS
        for rank in range(1, 14)
    ]
    random.Random(int(seed)).shuffle(cards)
    validate_four_suit_two_deck(cards)
    return SpiderState.from_cards(cards)


def suit_completion_detail(state: SpiderState) -> ProximityDetail:
    """Score every suit from the cards that are physically present."""

    best_penalty = {suit: [PENALTY_ABSENT] * 14 for suit in SUITS}
    for column in state.columns:
        up = column.face_up
        for card in column.face_down:
            _keep(best_penalty, card, PENALTY_FACE_DOWN)
        start = _exposed_start(up)
        for index, card in enumerate(up):
            penalty = PENALTY_EXPOSED if start is not None and index >= start else PENALTY_FACE_UP
            _keep(best_penalty, card, penalty)
    for card in state.stock:
        _keep(best_penalty, card, PENALTY_STOCK)

    by_suit = {suit: 0 for suit in SUITS}
    best_length = {suit: 0 for suit in SUITS}
    runs: List[Tuple[str, int, bool]] = []
    longest_exposed = 0
    complete_exposed = 0
    near_blocked = 0
    near_accessible = 0

    for col_index, column in enumerate(state.columns):
        up = column.face_up
        if not up:
            continue
        segment = 0
        while segment < len(up):
            end = segment + 1
            while (
                end < len(up)
                and up[end].suit == up[segment].suit
                and up[end - 1].rank == up[end].rank + 1
            ):
                end += 1
            length = end - segment
            suit = up[segment].suit
            is_exposed = end == len(up)
            runs.append((suit, length, is_exposed))
            if is_exposed:
                longest_exposed = max(longest_exposed, length)
            if length == 1 and not is_exposed:
                segment = end
                continue
            high = int(up[segment].rank)
            low = int(up[end - 1].rank)
            present = set(range(low, high + 1))
            missing_penalty = 0
            blocked_missing = 0
            for rank in range(1, 14):
                if rank in present:
                    continue
                penalty = best_penalty[suit][rank]
                missing_penalty += penalty
                if penalty >= PENALTY_FACE_DOWN:
                    blocked_missing += 1
            cover = 0 if is_exposed else COVER_BASE + COVER_PER_CARD * (len(up) - end)
            join = _join_bonus(state, col_index, suit, high, low, length) if is_exposed else 0
            raw = length * LENGTH_WEIGHT
            if high == 13:
                raw += KING_BONUS
            if low == 1:
                raw += ACE_BONUS
            raw += join - missing_penalty - cover
            if raw < 0:
                raw = 0
            if raw > by_suit[suit]:
                by_suit[suit] = raw
                best_length[suit] = length
            if is_exposed and length == 13 and high == 13 and low == 1:
                complete_exposed += 1
            if is_exposed and length >= 11 and length < 13:
                if blocked_missing:
                    near_blocked += 1
                else:
                    near_accessible += 1
            segment = end

    return ProximityDetail(
        score=sum(by_suit.values()),
        by_suit=by_suit,
        best_length=best_length,
        longest_exposed=longest_exposed,
        complete_exposed=complete_exposed,
        near_blocked=near_blocked,
        near_accessible=near_accessible,
        runs=tuple(runs),
    )


def suit_completion_score(state: SpiderState) -> int:
    """Higher is closer to a removable sequence. Not a remaining-move bound."""

    return suit_completion_detail(state).score


def order_with_advice(actions: Sequence[Action], suggestion: Optional[Action]) -> List[Action]:
    """Move one legal suggestion to the front. Never drop the others.

    ``None`` and any action the engine did not generate leave the list as it
    arrived. A failed campaign therefore changes nothing.
    """

    ordered = list(actions)
    if suggestion is None or suggestion not in ordered:
        return ordered
    ordered.remove(suggestion)
    ordered.insert(0, suggestion)
    return ordered


class AdviceCache:
    """Remember one proposal per packed state and stop after ``budget`` calls."""

    def __init__(self, budget: int) -> None:
        self.budget = int(budget)
        self.calls = 0
        self.hits = 0
        self._cache: Dict[bytes, Optional[Action]] = {}

    def suggest(
        self,
        state: SpiderState,
        propose: Callable[[SpiderState], Optional[Action]],
    ) -> Optional[Action]:
        key = pack_state(state)
        if key in self._cache:
            self.hits += 1
            return self._cache[key]
        if self.calls >= self.budget:
            return None
        self.calls += 1
        suggestion = propose(state)
        self._cache[key] = suggestion
        return suggestion


def _keep(best_penalty: Dict[str, List[int]], card: Card, penalty: int) -> None:
    row = best_penalty[card.suit]
    if penalty < row[card.rank]:
        row[card.rank] = penalty


def _exposed_start(up: Sequence[Card]) -> Optional[int]:
    if not up:
        return None
    start = len(up) - 1
    while (
        start > 0
        and up[start - 1].suit == up[start].suit
        and up[start - 1].rank == up[start].rank + 1
    ):
        start -= 1
    return start


def _join_bonus(
    state: SpiderState,
    col_index: int,
    suit: str,
    high: int,
    low: int,
    length: int,
) -> int:
    """One-step same-suit join. Off-suit stacks and empty columns do not count."""

    bonus = 0
    if low > 1:
        want = low - 1
        for src, column in enumerate(state.columns):
            if src == col_index or not column.face_up:
                continue
            start = _exposed_start(column.face_up)
            if start is None:
                continue
            head = column.face_up[start]
            if head.suit != suit or int(head.rank) != want:
                continue
            if state.can_move(src, col_index, len(column.face_up) - start):
                bonus += JOIN_BONUS
                break
    if high < 13:
        want = high + 1
        for dst, column in enumerate(state.columns):
            if dst == col_index:
                continue
            top = column.top()
            if top is None or top.suit != suit or int(top.rank) != want:
                continue
            if state.can_move(col_index, dst, length):
                bonus += JOIN_BONUS
                break
    return bonus
