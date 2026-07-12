"""Stock-round analysis for deal-aware search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .cards import Card
from .deal import cards_from_tokens, stock_deal_rounds


@dataclass(frozen=True)
class DealAnalysis:
    incoming_by_round: List[List[Card]]
    latest_round_by_suit: Dict[str, int]
    # New global pre-analysis for human-like high-level strategy (reverse-engineering
    # suit clearance eligibility and critical exposure priorities using full stock knowledge).
    initial_count_by_suit: Dict[str, int] = None  # type: ignore
    cumulative_by_suit: Dict[str, List[int]] = None  # type: ignore  # after r0 (initial) .. r5 ; len=6
    eligible_suits_by_round: List[set] = None  # type: ignore  # after each round r=0..5, set of suits with >=13 cards available
    priority_clearance_order: List[str] = None  # type: ignore  # suits sorted by earliest round they become eligible (early first)
    initial_buried_columns_by_suit: Dict[str, List[int]] = None  # type: ignore  # suit -> list of col indices (0-9) that bury some of its cards initially


def build_deal_analysis(tokens: List[str]) -> DealAnalysis:
    cards = cards_from_tokens(tokens)
    stock = cards[54:]
    incoming = stock_deal_rounds(stock)
    latest = {"s": 0, "h": 0, "d": 0, "c": 0}
    for r, ten in enumerate(incoming, start=1):
        for c in ten:
            latest[c.suit] = max(latest[c.suit], r)

    # --- New global clearance / exposure pre-analysis (for higher-level human strategy) ---
    # Compute initial per-suit counts and which columns bury cards of each suit.
    initial_54 = cards[:54]
    initial_count_by_suit = {"s": 0, "h": 0, "d": 0, "c": 0}
    for c in initial_54:
        initial_count_by_suit[c.suit] += 1

    # Simulate initial face-down layout to find buried columns per suit (same logic as SpiderState.from_cards / engine).
    cols_face_down_suits: List[List[str]] = [[] for _ in range(10)]
    idx = 0
    for _ in range(5):  # 5 rows
        for c in range(10):
            cols_face_down_suits[c].append(initial_54[idx].suit)
            idx += 1
    for c in range(4):  # extra 4 in first columns
        cols_face_down_suits[c].append(initial_54[idx].suit)
        idx += 1

    initial_buried_columns_by_suit: Dict[str, List[int]] = {s: [] for s in "shdc"}
    for col_idx, suits_in_col in enumerate(cols_face_down_suits):
        for s in set(suits_in_col):  # any buried of this suit in the column
            if s not in initial_buried_columns_by_suit:
                initial_buried_columns_by_suit[s] = []
            if col_idx not in initial_buried_columns_by_suit[s]:
                initial_buried_columns_by_suit[s].append(col_idx)

    # Cumulative availability per suit after each round (r0=initial, r1..r5 after each stock deal).
    cum_by_suit: Dict[str, List[int]] = {s: [0] * 6 for s in "shdc"}
    for s in "shdc":
        cum_by_suit[s][0] = initial_count_by_suit[s]
    for r, ten in enumerate(incoming, start=1):
        for ss in "shdc":
            cum_by_suit[ss][r] = cum_by_suit[ss][r-1]
        for c in ten:
            cum_by_suit[c.suit][r] += 1

    # Eligible suits after each round: those with cum >=13 (can have at least one full run in play).
    eligible_by_round: List[set] = []
    for r in range(6):
        elig = {s for s in "shdc" if cum_by_suit[s][r] >= 13}
        eligible_by_round.append(elig)

    # Priority order: suits sorted by the earliest round they become eligible (earliest first).
    first_eligible = {}
    for s in "shdc":
        for r in range(6):
            if cum_by_suit[s][r] >= 13:
                first_eligible[s] = r
                break
        else:
            first_eligible[s] = 6
    priority_order = sorted("shdc", key=lambda s: (first_eligible[s], s))

    return DealAnalysis(
        incoming_by_round=incoming,
        latest_round_by_suit=latest,
        initial_count_by_suit=initial_count_by_suit,
        cumulative_by_suit=cum_by_suit,
        eligible_suits_by_round=eligible_by_round,
        priority_clearance_order=priority_order,
        initial_buried_columns_by_suit=initial_buried_columns_by_suit,
    )


def build_deal_analysis_from_stock(stock: List[Card]) -> DealAnalysis:
    incoming = stock_deal_rounds(stock)
    latest = {"s": 0, "h": 0, "d": 0, "c": 0}
    for r, ten in enumerate(incoming, start=1):
        for c in ten:
            latest[c.suit] = max(latest[c.suit], r)
    return DealAnalysis(
        incoming_by_round=incoming,
        latest_round_by_suit=latest,
        initial_count_by_suit={"s": 0, "h": 0, "d": 0, "c": 0},
        cumulative_by_suit={s: [0]*6 for s in "shdc"},
        eligible_suits_by_round=[set() for _ in range(6)],
        priority_clearance_order=[],
        initial_buried_columns_by_suit={s: [] for s in "shdc"},
    )