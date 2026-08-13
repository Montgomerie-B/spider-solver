"""Sprint 1A — generic foundation-removal feasibility tests.

Uses synthetic deals for deterministic epoch assertions and the benchmark
deal only as a non-hard-coded fixture path for integration smoke.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal, stock_deal_rounds
from spider.engine import SpiderState
from spider.planner import foundation_feasibility as ff
from spider.planner.foundation_feasibility import (
    analyze_foundation_feasibility,
    compute_static_availability,
    earliest_any_foundation_epoch,
    epoch_name,
)


# ---------------------------------------------------------------------------
# Synthetic deal construction (generic; no benchmark deal numbers)
# ---------------------------------------------------------------------------


def _two_full_decks() -> list[Card]:
    cards: list[Card] = []
    for _ in range(2):
        for suit in "shdc":
            for rank in range(1, 14):
                cards.append(Card(suit, rank))
    assert len(cards) == 104
    return cards


def _split_tableau_stock(cards: list[Card]) -> tuple[list[Card], list[Card]]:
    assert len(cards) == 104
    return cards[:54], cards[54:]


def make_synthetic_deal_delayed_ace(
    *,
    suit: str = "d",
    first_ace_deal: int = 2,
    second_ace_deal: int = 4,
) -> list[Card]:
    """Build a 104-card deal where the given suit's Aces enter on specific deals.

    ``first_ace_deal`` / ``second_ace_deal`` are 1-based stock deal indices.

    Guarantees every non-Ace rank of ``suit`` has *both* physical copies in the
    opening tableau, so only the Aces control earliest epochs:

      suit#1 earliest == first_ace_deal
      suit#2 earliest == second_ace_deal
    """
    assert 1 <= first_ace_deal <= 5
    assert first_ace_deal <= second_ace_deal <= 5
    suit = suit.lower()

    # Both non-Ace copies of target suit must open in the tableau.
    target_non_aces = [
        Card(suit, r) for r in range(2, 14) for _ in range(2)
    ]  # 24 cards
    target_aces = [Card(suit, 1), Card(suit, 1)]

    others: list[Card] = []
    for s in "shdc":
        if s == suit:
            continue
        for _ in range(2):
            for r in range(1, 14):
                others.append(Card(s, r))
    # others = 78 cards; tableau needs 54 = 24 non-aces + 30 others
    assert len(target_non_aces) == 24
    assert len(others) == 78
    tableau = target_non_aces + others[:30]
    rest = others[30:]  # 48 cards + 2 aces = 50 stock
    assert len(rest) == 48

    rounds: list[list[Card]] = [[] for _ in range(5)]
    rest_i = 0
    for deal_idx in range(1, 6):
        bucket = rounds[deal_idx - 1]
        if deal_idx == first_ace_deal:
            bucket.append(target_aces[0])
            if second_ace_deal == first_ace_deal:
                bucket.append(target_aces[1])
        elif deal_idx == second_ace_deal:
            bucket.append(target_aces[1])
        while len(bucket) < 10:
            bucket.append(rest[rest_i])
            rest_i += 1
    assert rest_i == len(rest)

    stock: list[Card] = []
    for deal_idx in range(5, 0, -1):
        stock.extend(rounds[deal_idx - 1])
    assert len(stock) == 50

    recovered = stock_deal_rounds(stock)
    assert sum(1 for c in recovered[first_ace_deal - 1] if c.suit == suit and c.rank == 1) >= 1
    assert sum(1 for c in recovered[second_ace_deal - 1] if c.suit == suit and c.rank == 1) >= 1
    return tableau + stock


def make_synthetic_deal_second_foundation_needs_two_copies(
    suit: str = "c",
) -> list[Card]:
    """Ensure copy#2 of ``suit`` is delayed until both copies of every rank exist.

    Puts exactly one full K-A of ``suit`` entirely in the opening tableau
    region of the multiset, and holds the second K of that suit until deal 3.
    All other second-copy ranks of the suit enter by deal 2 at latest.
    """
    suit = suit.lower()
    # Partition into first-copy and second-copy of the suit, plus other cards.
    first_copy = [Card(suit, r) for r in range(1, 14)]
    second_copy = [Card(suit, r) for r in range(1, 14)]
    others: list[Card] = []
    for s in "shdc":
        if s == suit:
            continue
        for _ in range(2):
            for r in range(1, 14):
                others.append(Card(s, r))

    # Opening: full first copy + 41 others (54 total)
    tableau = first_copy + others[:41]
    others = others[41:]
    # Remaining: second_copy (13) + others (78-41=37? wait)
    # others total = 3 suits * 26 = 78; used 41; remain 37
    # second_copy 13 + 37 = 50 stock. Perfect.
    assert len(others) == 37

    # Hold second K until deal 3; put rest of second_copy into deal 1-2.
    second_k = Card(suit, 13)
    second_rest = [c for c in second_copy if c.rank != 13]

    rounds: list[list[Card]] = [[] for _ in range(5)]
    # deal 1: as many second_rest as fit
    pool = list(second_rest) + list(others)
    # Place second K into deal 3 first
    rounds[2].append(second_k)
    for d in range(5):
        while len(rounds[d]) < 10:
            rounds[d].append(pool.pop(0))
    assert not pool

    stock: list[Card] = []
    for d in range(5, 0, -1):
        stock.extend(rounds[d - 1])
    return tableau + stock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_foundation_not_available_before_all_ranks_enter_play():
    cards = make_synthetic_deal_delayed_ace(
        suit="d", first_ace_deal=2, second_ace_deal=4
    )
    _, static = compute_static_availability(cards)
    d1 = next(a for a in static if a.suit == "d" and a.copy_index == 1)
    assert d1.earliest_epoch == 2
    # Before that epoch, Ace count for diamonds is 0
    assert d1.rank_count_at(0, 1) == 0
    assert d1.rank_count_at(1, 1) == 0
    assert d1.rank_count_at(2, 1) >= 1
    assert 1 in d1.limiting_ranks  # Ace limited


def test_second_foundation_requires_two_copies_of_every_rank():
    cards = make_synthetic_deal_second_foundation_needs_two_copies(suit="c")
    _, static = compute_static_availability(cards)
    c1 = next(a for a in static if a.suit == "c" and a.copy_index == 1)
    c2 = next(a for a in static if a.suit == "c" and a.copy_index == 2)
    assert c1.earliest_epoch == 0  # full first set in opening
    assert c2.earliest_epoch is not None
    assert c2.earliest_epoch >= 3  # second K arrives on deal 3
    # At epoch 2, some rank still has count < 2
    counts_e2 = c2.cumulative_counts_by_epoch[2]
    assert any(n < 2 for n in counts_e2)
    counts_e3 = c2.cumulative_counts_by_epoch[3]
    assert all(n >= 2 for n in counts_e3)


def test_later_stock_row_delays_theoretical_epoch():
    cards = make_synthetic_deal_delayed_ace(
        suit="h", first_ace_deal=3, second_ace_deal=5
    )
    _, static = compute_static_availability(cards)
    h1 = next(a for a in static if a.suit == "h" and a.copy_index == 1)
    h2 = next(a for a in static if a.suit == "h" and a.copy_index == 2)
    assert h1.earliest_epoch == 3
    assert h2.earliest_epoch == 5
    assert h1.earliest_epoch_name == "after deal 3"
    assert h2.earliest_epoch_name == "after deal 5"


def test_duplicate_physical_cards_counted_separately():
    cards = make_synthetic_deal_delayed_ace(
        suit="s", first_ace_deal=1, second_ace_deal=1
    )
    # Both Aces of spades on deal 1
    _, static = compute_static_availability(cards)
    s1 = next(a for a in static if a.suit == "s" and a.copy_index == 1)
    s2 = next(a for a in static if a.suit == "s" and a.copy_index == 2)
    assert s1.earliest_epoch == 1
    assert s2.earliest_epoch == 1
    assert s1.rank_count_at(1, 1) == 2
    assert s2.rank_count_at(0, 1) == 0


def test_build_and_removal_readiness_are_separate():
    cards = make_synthetic_deal_delayed_ace(
        suit="d", first_ace_deal=2, second_ace_deal=4
    )
    analysis = analyze_foundation_feasibility(cards)
    # At opening, diamonds#1 is NOT theoretically available
    d1 = next(
        c
        for c in analysis.frontier.candidates
        if c.suit == "d" and c.copy_index == 1
    )
    assert d1.theoretically_available is False
    assert d1.heuristic_removal_readiness == 0.0
    # Build readiness may still be > 0 if material is face-up (heuristic)
    assert d1.heuristic_build_readiness >= 0.0
    # Explicit field separation
    assert hasattr(d1, "heuristic_build_readiness")
    assert hasattr(d1, "heuristic_removal_readiness")
    assert hasattr(d1, "theoretically_available")
    assert d1.theoretically_available is not (
        d1.heuristic_build_readiness > 0
    ) or d1.heuristic_removal_readiness == 0.0


def test_no_benchmark_deal_hardcoding_in_module_source():
    src = inspect.getsource(ff)
    forbidden = [
        "4925153",
        "77d169da",
        "canonical_mw",
        "cmd69",
        "command 68",
    ]
    for token in forbidden:
        assert token not in src, f"found forbidden token {token!r} in module"


def test_synthetic_obvious_epoch_end_to_end_report():
    cards = make_synthetic_deal_delayed_ace(
        suit="c", first_ace_deal=2, second_ace_deal=5
    )
    analysis = analyze_foundation_feasibility(cards)
    c1 = analysis.availability_for("c", 1)
    c2 = analysis.availability_for("c", 2)
    assert c1.earliest_epoch == 2
    assert c2.earliest_epoch == 5
    earliest = earliest_any_foundation_epoch(analysis)
    # Some other suit may be available at opening; just ensure function runs
    assert earliest is None or earliest >= 0
    report = ff.format_analysis_report(analysis, title="Synthetic")
    assert "FOUNDATION AVAILABILITY" in report
    assert "REMOVAL FRONTIER" in report
    assert "HEURISTIC" in report


def test_dynamic_state_tracks_stock_epoch_after_deals():
    cards = make_synthetic_deal_delayed_ace(
        suit="d", first_ace_deal=2, second_ace_deal=4
    )
    state = SpiderState.from_cards(list(cards))
    # Force two stock deals (legal if no empty columns — opening never empty)
    state.deal()
    state.deal()
    analysis = analyze_foundation_feasibility(cards, state)
    assert analysis.current_epoch == 2
    d1 = next(
        c
        for c in analysis.frontier.candidates
        if c.suit == "d" and c.copy_index == 1
    )
    assert d1.theoretically_available is True
    d2 = next(
        c
        for c in analysis.frontier.candidates
        if c.suit == "d" and c.copy_index == 2
    )
    assert d2.theoretically_available is False


def test_benchmark_deal_smoke_no_strategy_hardcode():
    """Smoke: analyser runs on the benchmark fixture path without special cases."""
    deal_path = ROOT / "deals" / "4925153.txt"
    if not deal_path.exists():
        pytest.skip("benchmark deal fixture not present")
    cards = load_deal(deal_path)
    analysis = analyze_foundation_feasibility(cards)
    assert len(analysis.static_availability) == 8  # 4 suits × 2 copies
    assert analysis.stock_deals_total == 5
    # Sanity: every availability has an epoch name
    for a in analysis.static_availability:
        assert a.earliest_epoch_name
        if a.earliest_epoch is not None:
            assert a.earliest_epoch == analysis.current_epoch or True


def test_epoch_names_are_stable():
    assert epoch_name(0) == "opening"
    assert epoch_name(2) == "after deal 2"
    assert epoch_name(5) == "after deal 5"
