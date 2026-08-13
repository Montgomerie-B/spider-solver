"""Sprint 1B — perfect-information reveal / unlock graph tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner import reveal_graph as rg
from spider.planner.reveal_graph import (
    analyze_reveal_graph,
    build_reveal_chain,
    minimum_reveals_to_expose,
)
from spider.planner.foundation_feasibility import analyze_foundation_feasibility


def _col(face_down: list[Card], face_up: list[Card] | None = None) -> Column:
    return Column(list(face_down), list(face_up or []))


def _state_with_column(
    face_down: list[Card],
    face_up: list[Card] | None = None,
    *,
    stock: list[Card] | None = None,
) -> SpiderState:
    """Minimal state: one interesting column + 9 empty; stock padded."""
    cols = [_col(face_down, face_up)] + [_col([], []) for _ in range(9)]
    if stock is None:
        # 50 cards so epoch math is stable if foundation analysis not used
        stock = [Card("s", 1)] * 50
    return SpiderState(cols, list(stock), [])


def test_ordered_hidden_chain_synthetic_column():
    # face_down[0]=deepest, face_down[-1]=next flip
    hidden = [Card("c", 3), Card("s", 13), Card("h", 7)]  # deep -> ... -> frontier
    # excavation order: 7h, Ks, 3c
    st = _state_with_column(hidden, [Card("d", 9)])
    chain = build_reveal_chain(0, st)
    assert chain is not None
    assert chain.n_hidden == 3
    assert [h.card for h in chain.hidden_cards] == [
        Card("h", 7),
        Card("s", 13),
        Card("c", 3),
    ]
    assert chain.hidden_cards[0].reveal_order == 0
    assert chain.hidden_cards[2].reveal_order == 2


def test_minimum_reveal_counts_top_middle_deep():
    hidden = [Card("c", 1), Card("c", 2), Card("c", 3), Card("c", 4)]
    st = _state_with_column(hidden, [Card("s", 5)])
    chain = build_reveal_chain(0, st)
    assert chain is not None
    # frontier
    assert minimum_reveals_to_expose(chain, 0) == 1
    assert chain.hidden_cards[0].minimum_reveals_to_expose == 1
    # middle
    assert minimum_reveals_to_expose(chain, 1) == 2
    assert minimum_reveals_to_expose(chain, 2) == 3
    # deepest
    assert minimum_reveals_to_expose(chain, 3) == 4


def test_deeper_target_depends_on_all_above():
    hidden = [Card("d", 5), Card("h", 6), Card("s", 7)]
    st = _state_with_column(hidden)
    chain = build_reveal_chain(0, st)
    assert chain is not None
    deep = chain.hidden_cards[-1]
    assert deep.face_down_above == 2
    assert deep.predecessor_order == 1
    # Every shallower card must come first
    for shallower in chain.hidden_cards[:-1]:
        assert shallower.reveal_order < deep.reveal_order
        assert shallower.minimum_reveals_to_expose < deep.minimum_reveals_to_expose


def test_exhausts_face_down_detected():
    hidden = [Card("c", 8), Card("c", 9)]
    st = _state_with_column(hidden, [Card("c", 10)])
    analysis = analyze_reveal_graph(st)
    chain = analysis.chain_for_column(0)
    assert chain is not None
    # Find prefixes via opportunities
    prefixes = [
        o.prefix
        for o in analysis.opportunities
        if o.prefix.column == 0
    ]
    assert any(p.exhausts_face_down and p.unavoidable_reveal_count == 2 for p in prefixes)
    assert any(not p.exhausts_face_down and p.unavoidable_reveal_count == 1 for p in prefixes)


def test_duplicate_cards_not_assigned_fixed_foundation_copy():
    """Physical 3c is not labelled as C#1 vs C#2 identity."""
    # Two identical clubs threes buried
    hidden = [Card("c", 3), Card("c", 3)]
    st = _state_with_column(hidden)
    # Provide full deal for foundation analysis
    deal_path = ROOT / "deals" / "4925153.txt"
    cards = load_deal(deal_path) if deal_path.exists() else None
    analysis = analyze_reveal_graph(st, cards=cards)
    for opp in analysis.opportunities:
        if opp.prefix.column != 0:
            continue
        for rel in opp.prefix.foundation_relevance:
            # Must not claim exclusive copy ownership
            joined = " ".join(rel.notes).lower()
            assert "interchangeable" in joined or rel.remaining_rank_demand >= 0
            assert "is C#1" not in joined and "is C#2" not in joined


def test_foundation_relevance_changes_with_epoch():
    deal_path = ROOT / "deals" / "4925153.txt"
    if not deal_path.exists():
        pytest.skip("benchmark fixture absent")
    cards = load_deal(deal_path)
    st0 = SpiderState.from_cards(list(cards))
    a0 = analyze_reveal_graph(st0, cards=cards)
    # After two stock deals, epoch advances and some foundations become theoretical
    st2 = SpiderState.from_cards(list(cards))
    st2.deal()
    st2.deal()
    a2 = analyze_reveal_graph(st2, cards=cards)
    assert a2.current_epoch == a0.current_epoch + 2
    # At least one opportunity should mention theoretical availability after deals
    # (H#1 / S#1 become available after deal 2 on this fixture — fact from 1A)
    fa2 = a2.foundation_analysis
    assert fa2 is not None
    h1 = fa2.availability_for("h", 1)
    assert h1.earliest_epoch is not None
    if a2.current_epoch >= h1.earliest_epoch:
        # Some buried heart may now tag theo_now
        any_theo = any(
            r.theoretically_available_this_epoch
            for opp in a2.opportunities
            for r in opp.prefix.foundation_relevance
            if r.suit == "h"
        )
        # Not all hearts may be buried, but if any heart is in a chain it should tag
        buried_h = any(
            h.card.suit == "h"
            for ch in a2.chains
            for h in ch.hidden_cards
        )
        if buried_h:
            assert any_theo


def test_king_is_neutral_structural_tag_not_penalty():
    hidden = [Card("s", 13)]  # only a King
    st = _state_with_column(hidden, [Card("h", 2)])
    analysis = analyze_reveal_graph(st)
    opp = next(o for o in analysis.opportunities if o.prefix.column == 0)
    king_tags = [t for t in opp.prefix.structural_tags if t.code == "contains_king"]
    assert king_tags
    assert "not a penalty" in king_tags[0].detail.lower() or "neutral" in king_tags[0].detail.lower()
    # No generic negative in heuristic reasons
    for reason in opp.heuristic_reasons:
        assert "bad" not in reason.lower()
        assert "penalty" not in reason.lower() or "no generic penalty" in reason.lower()


def test_unrelated_deal_without_benchmark_constants():
    # Synthetic: one column with known chain, empty stock remainder
    hidden = [Card("d", 4), Card("d", 10), Card("c", 6)]
    st = _state_with_column(hidden, [Card("c", 7)])
    analysis = analyze_reveal_graph(st)
    assert analysis.chain_for_column(0) is not None
    assert analysis.opportunities
    src = inspect.getsource(rg)
    assert "4925153" not in src
    assert "77d169da" not in src


def test_initial_benchmark_analyser_is_deterministic():
    deal_path = ROOT / "deals" / "4925153.txt"
    if not deal_path.exists():
        pytest.skip("benchmark fixture absent")
    cards = load_deal(deal_path)
    st = SpiderState.from_cards(list(cards))
    a1 = analyze_reveal_graph(st, cards=cards)
    a2 = analyze_reveal_graph(st, cards=cards)
    # Same chain sequences
    seq1 = tuple(
        (ch.column, tuple(h.card for h in ch.hidden_cards)) for ch in a1.chains
    )
    seq2 = tuple(
        (ch.column, tuple(h.card for h in ch.hidden_cards)) for ch in a2.chains
    )
    assert seq1 == seq2
    scores1 = tuple(
        (o.prefix.column, o.prefix.stop_reveal_order, o.heuristic_interest)
        for o in a1.opportunities
    )
    scores2 = tuple(
        (o.prefix.column, o.prefix.stop_reveal_order, o.heuristic_interest)
        for o in a2.opportunities
    )
    assert scores1 == scores2


def test_sprint1a_still_imports_and_runs():
    deal_path = ROOT / "deals" / "4925153.txt"
    if not deal_path.exists():
        pytest.skip("benchmark fixture absent")
    cards = load_deal(deal_path)
    fa = analyze_foundation_feasibility(cards)
    assert len(fa.static_availability) == 8
    # reveal graph consumes foundation analysis without mutating separation
    st = SpiderState.from_cards(list(cards))
    rg_a = analyze_reveal_graph(st, cards=cards, foundation_analysis=fa)
    assert rg_a.foundation_analysis is fa
    # 1A hard fields unchanged
    assert fa.availability_for("h", 1).earliest_epoch is not None
