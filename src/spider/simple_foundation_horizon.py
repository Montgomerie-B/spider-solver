"""Research-only exact foundation material-horizon audit.

Material availability is a lower bound.  It is not operational reachability.
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState

SUITS = ("s", "h", "d", "c")
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}
EXPECTED_FIRST = {"s": 2, "h": 2, "d": 4, "c": 5}
EXPECTED_SECOND = {"s": 5, "h": 5, "d": 5, "c": 5}
EXPECTED_MAX_BY_HORIZON = [0, 0, 2, 2, 3, 8]
EXPECTED_SD5 = ["3H", "10H", "2D", "3C", "9H", "7C", "7H", "AS", "3C", "5D"]


def pretty_card(card: Card) -> str:
    return f"{rank_str(card.rank)}{card.suit.upper()}"


def pretty_rank(rank: int) -> str:
    return rank_str(rank)


def tableau_cards(state: SpiderState) -> List[Card]:
    cards: List[Card] = []
    for column in state.columns:
        cards.extend(column.face_down)
        cards.extend(column.face_up)
    return cards


def stock_deal_rows(stock: Sequence[Card]) -> List[List[Card]]:
    """Engine deal order: each Deal consumes stock[-10:] left-to-right."""

    remaining = list(stock)
    rows: List[List[Card]] = []
    while len(remaining) >= 10:
        rows.append(list(remaining[-10:]))
        remaining = remaining[:-10]
    return rows


def count_cards(cards: Iterable[Card]) -> Counter:
    return Counter((card.suit, card.rank) for card in cards)


def complete_sets(suit: str, counts: Counter) -> int:
    return min(counts.get((suit, rank), 0) for rank in range(1, 14))


def missing_ranks(suit: str, counts: Counter, needed: int) -> List[int]:
    return [rank for rank in range(1, 14) if counts.get((suit, rank), 0) < needed]


def earliest_horizon(suit: str, needed: int, counts_by_h: Sequence[Counter]) -> int:
    for horizon, counts in enumerate(counts_by_h):
        if complete_sets(suit, counts) >= needed:
            return horizon
    return -1


def bottleneck(suit: str, needed: int, horizon: int, counts_by_h: Sequence[Counter], rows: Sequence[Sequence[Card]]) -> dict:
    prev = counts_by_h[horizon - 1] if horizon > 0 else Counter()
    missing = missing_ranks(suit, prev, needed)
    supplied = []
    if horizon > 0:
        for index, card in enumerate(rows[horizon - 1]):
            if card.suit == suit and card.rank in missing:
                supplied.append(
                    {
                        "column_1": index + 1,
                        "card": pretty_card(card),
                        "suit": card.suit,
                        "rank": card.rank,
                    }
                )
    return {
        "missing_ranks_before": [pretty_rank(rank) for rank in missing],
        "missing_rank_ints": missing,
        "supplied_by_completing_row": supplied,
    }


def material_horizon_audit(state: SpiderState) -> dict:
    tableau = tableau_cards(state)
    rows = stock_deal_rows(state.stock)
    assert len(rows) == 5
    counts_by_h: List[Counter] = []
    running = count_cards(tableau)
    counts_by_h.append(Counter(running))
    for row in rows:
        running.update(count_cards(row))
        counts_by_h.append(Counter(running))

    suits = {}
    for suit in SUITS:
        first_h = earliest_horizon(suit, 1, counts_by_h)
        second_h = earliest_horizon(suit, 2, counts_by_h)
        suits[suit] = {
            "name": SUIT_NAMES[suit],
            "first_horizon": first_h,
            "second_horizon": second_h,
            "first_label": "initial" if first_h == 0 else f"SD{first_h}",
            "second_label": "initial" if second_h == 0 else f"SD{second_h}",
            "first_bottleneck": bottleneck(suit, 1, first_h, counts_by_h, rows),
            "second_bottleneck": bottleneck(suit, 2, second_h, counts_by_h, rows),
            "complete_sets_by_horizon": [complete_sets(suit, counts) for counts in counts_by_h],
        }

    max_by_h = [sum(complete_sets(suit, counts) for suit in SUITS) for counts in counts_by_h]
    sd5 = [pretty_card(card) for card in rows[4]]
    impossible_before_sd5 = []
    for suit in SUITS:
        if suits[suit]["first_horizon"] == 5:
            impossible_before_sd5.append(f"first {SUIT_NAMES[suit]}")
        if suits[suit]["second_horizon"] == 5:
            impossible_before_sd5.append(f"second {SUIT_NAMES[suit]}")

    expected_ok = (
        all(suits[suit]["first_horizon"] == EXPECTED_FIRST[suit] for suit in SUITS)
        and all(suits[suit]["second_horizon"] == EXPECTED_SECOND[suit] for suit in SUITS)
        and max_by_h == EXPECTED_MAX_BY_HORIZON
        and sd5 == EXPECTED_SD5
    )
    return {
        "tableau_cards": len(tableau),
        "stock_rows": [[pretty_card(card) for card in row] for row in rows],
        "sd5": sd5,
        "sd5_expected": EXPECTED_SD5,
        "sd5_matches_expected": sd5 == EXPECTED_SD5,
        "suits": suits,
        "max_foundations_by_horizon": max_by_h,
        "horizon_labels": ["initial / before SD1", "after SD1", "after SD2", "after SD3", "after SD4", "after SD5"],
        "impossible_before_sd5": impossible_before_sd5,
        "expected_ok": expected_ok,
        "material_not_operational": True,
    }
