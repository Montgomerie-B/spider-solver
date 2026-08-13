"""Sprint 1C — empty-column lifecycle / recoverability tests."""

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
from spider.planner import space_lifecycle as sl
from spider.planner.space_lifecycle import (
    ImmediateRecoveryKind,
    WorkspaceEffectKind,
    analyze_all_move_effects,
    analyze_next_stock_recovery,
    analyze_space_lifecycle,
    empty_columns,
    empty_count,
    simulate_move_effect,
)
from spider.planner.reveal_graph import analyze_reveal_graph
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.foundation_feasibility import analyze_foundation_feasibility


def _state(cols: list[Column], stock: list[Card] | None = None) -> SpiderState:
    # Pad with occupied non-empty columns (not empties) so empty counts are intentional.
    pad_rank = 5
    while len(cols) < 10:
        cols.append(Column([], [Card("d", pad_rank)]))
        pad_rank = 4 if pad_rank == 5 else 5
    if stock is None:
        stock = []
    return SpiderState(cols, list(stock), [])


def test_current_empty_column_detection():
    st = _state(
        [
            Column([], []),  # empty
            Column([], [Card("s", 5)]),
            Column([Card("h", 2)], [Card("h", 3)]),
            Column([], []),  # empty
        ]
    )
    assert empty_columns(st) == (0, 3)
    assert empty_count(st) == 2


def test_full_open_column_to_empty_relocates_and_may_be_free():
    # Fully open 9s-8s onto empty
    st = _state(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], []),  # empty
        ]
    )
    eff = simulate_move_effect(st, 0, 1, 2)
    assert eff.effect == WorkspaceEffectKind.RELOCATES
    assert eff.empty_before == 1
    assert eff.empty_after == 1
    assert eff.corrected_mw_cost == 0  # free full-column relocate
    assert 0 in eff.empties_after
    assert 1 not in eff.empties_after


def test_entire_faceup_to_empty_with_facedown_is_paid():
    st = _state(
        [
            Column([Card("c", 3)], [Card("s", 9), Card("s", 8)]),
            Column([], []),
        ]
    )
    before = empty_count(st)
    eff = simulate_move_effect(st, 0, 1, 2)
    assert eff.dest_was_empty
    assert eff.source_face_down_before == 1
    assert eff.corrected_mw_cost == 1  # NOT free
    assert eff.flipped is True  # 3c exposed
    # Source not empty (has face-up 3c after flip), dest no longer empty
    assert eff.effect == WorkspaceEffectKind.CONSUMES
    assert eff.empty_after == before - 1


def test_partial_move_into_empty_consumes():
    st = _state(
        [
            Column([], [Card("s", 10), Card("s", 9), Card("s", 8)]),
            Column([], []),
        ]
    )
    # Move only 9-8 (k=2), leave 10s
    eff = simulate_move_effect(st, 0, 1, 2)
    assert eff.effect == WorkspaceEffectKind.CONSUMES
    assert eff.empty_before == 1
    assert eff.empty_after == 0
    assert not eff.source_became_empty
    assert eff.corrected_mw_cost == 1


def test_move_to_nonempty_creating_workspace():
    st = _state(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    assert empty_count(st) == 0
    eff = simulate_move_effect(st, 0, 1, 1)
    assert eff.effect == WorkspaceEffectKind.CREATES
    assert eff.empty_after == 1
    assert 0 in eff.empties_after
    assert eff.corrected_mw_cost == 1


def test_foundation_removal_zero_extra_cost_and_workspace():
    ka = [Card("c", r) for r in range(13, 0, -1)]
    st = _state(
        [
            Column([], list(ka)),  # full foundation ready on source
            Column([], []),
        ]
    )
    before = empty_count(st)
    assert before == 1
    eff = simulate_move_effect(st, 0, 1, 13)
    assert eff.foundation_removal is True
    assert eff.corrected_mw_cost == 0  # full open column to empty
    st2 = st.clone()
    cost = st2.move(0, 1, 13)
    assert cost == 0
    assert len(st2.foundations) == 1
    # Source emptied; dest emptied by free foundation removal -> net +1 empty
    assert empty_count(st2) == before + 1
    assert eff.effect == WorkspaceEffectKind.CREATES


def test_next_stock_maps_incoming_card_onto_empty():
    # Stock top 10 dealt left-to-right onto cols 0..9; engine uses stock[-10:]
    incoming = [Card("h", r) for r in range(1, 11)]  # col0 gets h1 ... col9 gets h10
    # stock file order: bottom ... top; deal takes last 10
    stock = [Card("s", 1)] * 40 + incoming
    st = _state(
        [Column([], [Card("d", 5)]) for _ in range(10)],
        stock=stock,
    )
    # Make col 2 empty
    st.columns[2] = Column([], [])
    rec = analyze_next_stock_recovery(st)
    assert rec.can_deal
    assert 2 in rec.pre_deal_empties
    by_col = {p.column: p for p in rec.per_column}
    assert by_col[2].incoming_card == Card("h", 3)  # cols 0..9 -> ranks 1..10


def test_one_move_post_stock_recovery_when_legal():
    # Empty col 0; deal places 7s; col 1 top is 8s so 7s can move onto it
    stock = [Card("s", 1)] * 40 + [
        Card("s", 7),  # col 0
        Card("h", 2),
        Card("h", 3),
        Card("h", 4),
        Card("h", 5),
        Card("h", 6),
        Card("h", 7),
        Card("h", 8),
        Card("h", 9),
        Card("h", 10),
    ]
    cols = [Column([], [])]  # empty col 0
    cols.append(Column([], [Card("s", 8)]))
    for _ in range(8):
        cols.append(Column([], [Card("d", 5)]))
    st = _state(cols, stock=stock)
    rec = analyze_next_stock_recovery(st)
    p0 = next(p for p in rec.per_column if p.column == 0)
    assert p0.incoming_card == Card("s", 7)
    assert p0.immediate_recovery == ImmediateRecoveryKind.RECOVERS_SAME_COLUMN
    assert p0.recovery_move is not None
    assert p0.recovery_move.corrected_mw_cost == 1


def test_no_false_immediate_recovery_without_destination():
    # Empty col 0; dealt king with no empty and no matching rank below
    stock = [Card("c", 1)] * 40 + [Card("s", 13)] + [Card("h", r) for r in range(2, 11)]
    cols = [Column([], [])]
    for r in range(2, 11):
        # tops that cannot receive K (need empty for K)
        cols.append(Column([], [Card("d", 5)]))
    st = _state(cols, stock=stock)
    # Only one empty; after deal it has Ks, and no other empties, K only goes to empty
    rec = analyze_next_stock_recovery(st)
    p0 = next(p for p in rec.per_column if p.column == 0)
    assert p0.incoming_card == Card("s", 13)
    assert p0.immediate_recovery == ImmediateRecoveryKind.NO_LEGAL_ONE_MOVE
    assert p0.legal_destinations == ()


def test_multi_empty_simultaneous_not_hard_fact():
    stock = [Card("s", 1)] * 50
    cols = [Column([], []), Column([], [])] + [
        Column([], [Card("d", 5)]) for _ in range(8)
    ]
    st = _state(cols, stock=stock)
    rec = analyze_next_stock_recovery(st)
    assert len(rec.pre_deal_empties) == 2
    assert rec.simultaneous_recovery_status == "unknown_without_joint_search"
    assert "NOT claimed" in rec.simultaneous_recovery_note or "not" in rec.simultaneous_recovery_note.lower()


def test_reveal_link_deterministic():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    # Create an empty somehow if possible - initial has no empties
    a1 = analyze_space_lifecycle(st, cards=cards)
    a2 = analyze_space_lifecycle(st, cards=cards)
    assert a1.workspace.empty_count == a2.workspace.empty_count
    assert len(a1.reveal_contexts) == len(a2.reveal_contexts)
    assert a1.workspace.empty_columns == a2.workspace.empty_columns


def test_unrelated_synthetic_no_benchmark_constants():
    st = _state(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], []),
            Column([Card("c", 2)], [Card("h", 4)]),
        ],
        stock=[Card("d", r) for r in range(1, 11)] * 5,
    )
    analysis = analyze_space_lifecycle(st, include_reveal_link=True)
    assert analysis.workspace.empty_count == 1
    assert analysis.relocation_moves or analysis.consumption_moves
    src = inspect.getsource(sl)
    assert "4925153" not in src
    assert "77d169da" not in src


def test_strategic_analysis_aggregate():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    sa = analyze_strategic(st, cards=cards)
    assert sa.foundation is not None
    assert sa.reveal is not None
    assert sa.space.workspace.empty_count == 0
    # 1A still works
    assert len(sa.foundation.static_availability) == 8


def test_sprint1a_1b_smoke():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    fa = analyze_foundation_feasibility(cards, st)
    rg = analyze_reveal_graph(st, cards=cards, foundation_analysis=fa)
    assert len(rg.chains) == 10
    assert fa.current_epoch == 0
