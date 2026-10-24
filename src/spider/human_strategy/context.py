"""Whole-deal strategic context.

Known cards and legally accessible cards are different facts. Face-down
cards and stock cards are known from the deal and are not movable yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from spider.cards import rank_str
from spider.engine import SpiderState
from spider.planner.stock_reception import next_stock_row
from spider.research_actions import face_down_count

from .evaluation import (
    admissible_remaining,
    bury_risk,
    estimate_remaining,
    longest_same_suit_run,
    mixed_boundaries,
    same_suit_bonds,
    same_suit_landings,
    stock_rows,
)


@dataclass(frozen=True)
class CardFact:
    column: Optional[int]
    zone: str
    index: int
    suit: str
    rank: int
    accessible: bool

    @property
    def label(self) -> str:
        return f"{rank_str(self.rank)}{self.suit.upper()}"


@dataclass
class StrategicContext:
    state: SpiderState
    cumulative_g: int
    stock_rows: int
    face_down: int
    foundations: int
    bonds: int
    mixed_boundaries: int
    longest_run: int
    empty_columns: int
    bury_risk: int
    same_suit_landings: int
    admissible_remaining: int
    estimate_remaining: float
    cards: Tuple[CardFact, ...]
    incoming_labels: Tuple[str, ...]
    notes: Tuple[str, ...]

    def known_hidden(self) -> Tuple[CardFact, ...]:
        return tuple(card for card in self.cards if card.zone == "face_down")

    def accessible_cards(self) -> Tuple[CardFact, ...]:
        return tuple(card for card in self.cards if card.accessible)


def _movable_suffix_length(column) -> int:
    up = column.face_up
    if not up:
        return 0
    length = 1
    for index in range(len(up) - 2, -1, -1):
        upper, lower = up[index], up[index + 1]
        if upper.suit == lower.suit and upper.rank == lower.rank + 1:
            length += 1
        else:
            break
    return length


def _card_facts(state: SpiderState) -> List[CardFact]:
    facts: List[CardFact] = []
    for column_index, column in enumerate(state.columns):
        for index, card in enumerate(column.face_down):
            facts.append(
                CardFact(column_index, "face_down", index, card.suit, card.rank, False)
            )
        suffix = _movable_suffix_length(column)
        start = len(column.face_up) - suffix
        for index, card in enumerate(column.face_up):
            facts.append(
                CardFact(
                    column_index,
                    "face_up",
                    index,
                    card.suit,
                    card.rank,
                    index >= start,
                )
            )
    row = next_stock_row(state)
    if row is not None:
        for index, card in enumerate(row):
            facts.append(CardFact(index, "stock", index, card.suit, card.rank, False))
    return facts


def _prereq_notes(state: SpiderState) -> Tuple[str, ...]:
    """Face-down cards that are the next rank of an accessible same-suit card."""

    accessible = []
    for column in state.columns:
        if column.face_up:
            top = column.face_up[-1]
            accessible.append(top)
    notes = []
    for column_index, column in enumerate(state.columns):
        if not column.face_down or not column.face_up:
            continue
        hidden = column.face_down[-1]
        for card in accessible:
            if card.suit == hidden.suit and card.rank == hidden.rank - 1:
                notes.append(
                    f"prerequisite: {rank_str(hidden.rank)}{hidden.suit.upper()} is face-down "
                    f"in column {column_index + 1} and is the next card for "
                    f"{rank_str(card.rank)}{card.suit.upper()}"
                )
                break
    return tuple(notes[:6])


def build_context(state: SpiderState, cumulative_g: int) -> StrategicContext:
    row = next_stock_row(state)
    incoming = tuple(f"{rank_str(card.rank)}{card.suit.upper()}" for card in row) if row else ()
    return StrategicContext(
        state=state,
        cumulative_g=int(cumulative_g),
        stock_rows=stock_rows(state),
        face_down=face_down_count(state),
        foundations=len(state.foundations),
        bonds=same_suit_bonds(state),
        mixed_boundaries=mixed_boundaries(state),
        longest_run=longest_same_suit_run(state),
        empty_columns=sum(1 for column in state.columns if column.is_empty()),
        bury_risk=bury_risk(state),
        same_suit_landings=same_suit_landings(state),
        admissible_remaining=admissible_remaining(state),
        estimate_remaining=estimate_remaining(state),
        cards=tuple(_card_facts(state)),
        incoming_labels=incoming,
        notes=_prereq_notes(state),
    )
