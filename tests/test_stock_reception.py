"""Sprint 1D — known-stock reception / pre-deal shaping tests."""

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
from spider.planner import stock_reception as sr
from spider.planner.stock_reception import (
    LandingKind,
    analyze_stock_reception,
    next_stock_row,
    run_bounded_shaping_probe,
    PreDealShapingObjective,
)
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.foundation_feasibility import analyze_foundation_feasibility
from spider.planner.reveal_graph import analyze_reveal_graph
from spider.planner.space_lifecycle import analyze_space_lifecycle


def _pad(cols: list[Column], stock: list[Card]) -> SpiderState:
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    return SpiderState(cols, list(stock), [])


def _stock_with_row(row: list[Card], *, extra_rounds: int = 4) -> list[Card]:
    """Build stock so next deal is ``row`` (len 10)."""
    assert len(row) == 10
    filler = []
    for _ in range(extra_rounds):
        filler.extend([Card("h", r) for r in range(1, 11)])
    # next deal = stock[-10:] = row
    return filler + list(row)


def test_exact_mapping_next_ten_to_columns():
    row = [Card("s", r) for r in range(1, 11)]
    stock = _stock_with_row(row)
    st = _pad([Column([], [Card("c", 13)]) for _ in range(10)], stock)
    got = next_stock_row(st)
    assert got == tuple(row)
    analysis = analyze_stock_reception(st, run_shaping_probe=False)
    assert analysis.can_deal
    for i, f in enumerate(analysis.incoming_row):
        assert f.column == i
        assert f.card == row[i]


def test_same_suit_one_rank_receiver():
    # col0 top 9c, incoming 8c
    row = [Card("c", 8)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], [Card("c", 9)])]
    for _ in range(9):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].landing == LandingKind.SAME_SUIT_CONNECT
    assert a.columns[0].creates_or_extends_same_suit_run_on_landing
    assert a.row_summary.n_same_suit_landings >= 1


def test_mixed_suit_rank_receiver():
    row = [Card("s", 8)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], [Card("c", 9)])]  # 9c <- 8s mixed
    for _ in range(9):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].landing == LandingKind.MIXED_RANK_CONNECT


def test_non_connecting_receiver():
    row = [Card("s", 3)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], [Card("c", 9)])]
    for _ in range(9):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].landing == LandingKind.NON_CONNECTING


def test_empty_column_landing():
    row = [Card("s", 7)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], [])]  # empty
    for _ in range(9):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].landing == LandingKind.EMPTY_LANDING
    assert a.row_summary.n_empty_landings >= 1


def test_immediate_post_deal_destinations():
    # empty col0 gets 7s; col1 receives 8s as its incoming top -> 7s can move onto it
    row = [Card("s", 7), Card("s", 8)] + [Card("h", r) for r in range(3, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], []), Column([], [Card("d", 12)])]
    for _ in range(8):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].immediate_out_moves
    assert any(m.dst == 1 for m in a.columns[0].immediate_out_moves)


def test_one_move_empty_recovery_link():
    row = [Card("s", 7), Card("s", 8)] + [Card("h", r) for r in range(3, 11)]
    stock = _stock_with_row(row)
    cols = [Column([], []), Column([], [Card("d", 12)])]
    for _ in range(8):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    a = analyze_stock_reception(st, run_shaping_probe=False)
    assert a.columns[0].empty_recovery is not None
    assert a.columns[0].empty_recovery.value == "recovers_same_column"


def test_foundation_limiting_tag_via_1a():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    # Deal twice so we approach deal 2 epoch
    # Actually analyze at opening for deal 1 - limiting cards may appear later
    a = analyze_stock_reception(st, cards=cards, run_shaping_probe=False)
    assert a.can_deal
    # At least foundation notes present
    assert any(c.foundation_notes for c in a.columns)


def test_no_false_simultaneous_benefit_conflict():
    # Two empties both get cards that can only move to same dest 9s
    # col0 empty <- 8s, col1 empty <- 8h, only col2 has 9s
    row = (
        [Card("s", 8), Card("h", 8)]
        + [Card("d", r) for r in range(3, 11)]
    )
    stock = _stock_with_row(row)
    cols = [
        Column([], []),
        Column([], []),
        Column([], [Card("s", 9)]),  # only receives 8s same-suit; 8h needs 9h
    ]
    # Give 8h a dest: col3 top 9c for mixed or 9h
    cols.append(Column([], [Card("h", 9)]))
    for _ in range(6):
        cols.append(Column([], [Card("d", 5)]))
    st = _pad(cols, stock)
    # Force both 8s and something to compete: make both only go to col2
    # 8s -> 9s on col2; 8c -> also need 9 on col2 only
    row2 = [Card("s", 8), Card("c", 8)] + [Card("d", r) for r in range(3, 11)]
    stock2 = _stock_with_row(row2)
    cols2 = [
        Column([], []),
        Column([], []),
        Column([], [Card("s", 9)]),  # 8s ok; 8c also rank-ok mixed
    ]
    for _ in range(7):
        cols2.append(Column([], [Card("d", 5)]))
    st2 = _pad(cols2, stock2)
    a = analyze_stock_reception(st2, run_shaping_probe=False)
    # Both col0 and col1 may list dest 2
    assert a.row_summary.conflicts or a.row_summary.joint_out_move_status in (
        "unknown_joint",
        "exact_trivial",
    )
    # If both have out to col2, conflict must be flagged
    outs0 = {m.dst for m in a.columns[0].immediate_out_moves}
    outs1 = {m.dst for m in a.columns[1].immediate_out_moves}
    if outs0 & outs1:
        assert a.row_summary.conflicts
        assert a.row_summary.joint_out_move_status == "unknown_joint"


def test_bounded_shaping_finds_known_improvement():
    """Bad landing: top is 5c, incoming 8c; one move can put 9c on top.

    Layout: col0 has 9c under 5d (wrong top). Move 5d away onto 6d, expose 9c.
    """
    row = [Card("c", 8)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    cols = [
        Column([], [Card("c", 9), Card("d", 5)]),  # top 5d blocks 9c
        Column([], [Card("d", 6)]),  # can receive 5d
    ]
    for _ in range(8):
        cols.append(Column([], [Card("s", 5 if _ % 2 else 4)]))
    st = _pad(cols, stock)
    # Before: non-connecting
    a0 = analyze_stock_reception(st, run_shaping_probe=False)
    assert a0.columns[0].landing == LandingKind.NON_CONNECTING
    obj = PreDealShapingObjective(
        code="same_suit_receiver",
        description="expose 9c",
        target_column=0,
        incoming=Card("c", 8),
        predicate_key="same_suit_receiver",
        max_cost=2,
    )
    res = run_bounded_shaping_probe(st, obj, max_cost=2)
    assert res.found
    assert res.status in ("found", "already_satisfied")
    assert res.corrected_mw_cost <= 2
    # Apply path and verify landing becomes same-suit
    st2 = st.clone()
    for src, dst, k in res.path:
        st2.move(src, dst, k)
    a1 = analyze_stock_reception(st2, run_shaping_probe=False)
    assert a1.columns[0].landing == LandingKind.SAME_SUIT_CONNECT


def test_bounded_shaping_failure_is_not_impossible():
    row = [Card("c", 2)] + [Card("h", r) for r in range(2, 11)]
    stock = _stock_with_row(row)
    # No 3c anywhere accessible; probe for same-suit receiver should miss within bound
    cols = [Column([], [Card("s", 10)])]
    for _ in range(9):
        cols.append(Column([], [Card("d", 5 if _ % 2 else 4)]))
    st = _pad(cols, stock)
    obj = PreDealShapingObjective(
        code="same_suit_receiver",
        description="want 3c",
        target_column=0,
        incoming=Card("c", 2),
        predicate_key="same_suit_receiver",
        max_cost=1,
    )
    res = run_bounded_shaping_probe(st, obj, max_cost=1)
    assert not res.found
    assert res.status == "not_found_within_bound"
    assert any("NOT prove impossibility" in n for n in res.notes)


def test_strategic_analysis_includes_all_four():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    sa = analyze_strategic(st, cards=cards, run_shaping_probe=False)
    assert sa.foundation is not None
    assert sa.reveal is not None
    assert sa.space is not None
    assert sa.stock_reception is not None
    assert sa.stock_reception.can_deal


def test_deterministic():
    row = [Card("s", r) for r in range(1, 11)]
    stock = _stock_with_row(row)
    st = _pad([Column([], [Card("c", 13)]) for _ in range(10)], stock)
    a1 = analyze_stock_reception(st, run_shaping_probe=False)
    a2 = analyze_stock_reception(st, run_shaping_probe=False)
    assert [c.landing for c in a1.columns] == [c.landing for c in a2.columns]
    assert a1.row_summary.n_same_suit_landings == a2.row_summary.n_same_suit_landings


def test_no_benchmark_constants_in_module():
    src = inspect.getsource(sr)
    for tok in ("4925153", "77d169da", "cmd69", "leaderboard"):
        assert tok not in src


def test_good_and_bad_fixtures_bundle():
    # GOOD: several same-suit landings
    row = [
        Card("c", 8),
        Card("s", 6),
        Card("h", 4),
        Card("d", 10),
    ] + [Card("h", r) for r in range(5, 11)]
    stock = _stock_with_row(row)
    cols = [
        Column([], [Card("c", 9)]),
        Column([], [Card("s", 7)]),
        Column([], [Card("h", 5)]),
        Column([], [Card("d", 11)]),
    ]
    for _ in range(6):
        cols.append(Column([], [Card("d", 5 if _ % 2 else 4)]))
    st = _pad(cols, stock)
    good = analyze_stock_reception(st, run_shaping_probe=False)
    assert good.row_summary.n_same_suit_landings >= 3

    # BAD/SHAPABLE covered by test_bounded_shaping_finds_known_improvement


def test_sprint1a_1b_1c_still_green_smoke():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    fa = analyze_foundation_feasibility(cards, st)
    rg = analyze_reveal_graph(st, cards=cards, foundation_analysis=fa)
    sp = analyze_space_lifecycle(st, cards=cards, reveal_analysis=rg)
    assert len(fa.static_availability) == 8
    assert len(rg.chains) == 10
    assert sp.workspace.empty_count == 0
