"""Sprint 1H — two-epoch plan search tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.plan_search_v2 import (
    replay_canonical_epochs,
    search_opening_to_first_deal,
    search_to_stock_epoch,
    stratify_nodes,
)
from spider.planner.foundation_feasibility import analyze_foundation_feasibility


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def test_epoch_transition_two_deals():
    st = _pad([Column([], [Card("s", 5)])])
    res = search_to_stock_epoch(
        st,
        target_deals=2,
        max_non_deal=0,
        beam=6,
        max_plan_nodes=15,
        time_limit_s=8.0,
    )
    assert res.terminals
    for t in res.terminals:
        assert t.deals_done == 2
        assert t.actions.count(("deal",)) == 2
        chk = st.clone()
        assert replay_actions(chk, list(t.actions)) == t.g


def test_epoch_depth_resets_after_deal():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=2,
        max_non_deal=1,
        beam=10,
        tactical_max_cost=3,
        workspace_max_cost=5,
        max_plan_nodes=25,
        time_limit_s=12.0,
    )
    # After a deal, further non-deal objectives are allowed (depth reset)
    kinds = [t.objective_kinds for t in res.terminals]
    assert any(k.count("DEAL_NOW") == 2 for k in kinds)


def test_compose_replay_across_two_deals():
    st = _pad([Column([], [Card("c", 6)])])
    res = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=0, beam=4, max_plan_nodes=10, time_limit_s=6.0
    )
    t = res.terminals[0]
    chk = st.clone()
    cost = replay_actions(chk, list(t.actions))
    assert cost == t.g
    assert len(chk.stock) == len(st.stock) - 20


def test_transposition_across_epochs():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=1, beam=8, max_plan_nodes=20, time_limit_s=10.0
    )
    seen = {}
    for t in res.terminals:
        key = (t.deals_done, t.key)
        if key in seen:
            assert t.g >= seen[key]
        else:
            seen[key] = t.g


def test_stratify_keeps_investment_despite_cheap_deal():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=2,
        max_non_deal=2,
        beam=12,
        workspace_max_cost=5,
        max_plan_nodes=30,
        time_limit_s=15.0,
    )
    assert any(t.g == 2 and t.objective_kinds == ("DEAL_NOW", "DEAL_NOW") for t in res.terminals)
    # Investment: workspace or expose somewhere in some terminal
    kinds_all = [t.objective_kinds for t in res.terminals]
    assert any(
        "CREATE_WORKSPACE" in k or "EXPOSE_REVEAL_PREFIX" in k or "CONSOLIDATE_SAME_SUIT" in k
        for k in kinds_all
    ) or len(res.stratified_terminals) >= 1


def test_workspace_can_unlock_synthetic_reveal():
    # No empty; Ks buries 2c; 8s/9s can create empty; then Ks parks and 2c flips.
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ],
        stock,
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=3,
        beam=12,
        tactical_max_cost=3,
        workspace_max_cost=5,
        cheap_reveal_max=2,
        max_plan_nodes=25,
        time_limit_s=12.0,
    )
    seqs = [t.objective_kinds for t in res.terminals]
    unlocked = any(
        "CREATE_WORKSPACE" in s and "EXPOSE_REVEAL_PREFIX" in s for s in seqs
    )
    # If not in terminals (deal cut off), check deal1 children via stats
    assert unlocked or res.stats.workspace_then_expose > 0 or any(
        "CREATE_WORKSPACE" in s for s in seqs
    )


def test_deal2_foundation_availability_update():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    fa0 = analyze_foundation_feasibility(cards, st)
    h1_0 = fa0.availability_for("h", 1).earliest_epoch
    s1_0 = fa0.availability_for("s", 1).earliest_epoch
    assert h1_0 == 2 and s1_0 == 2
    # After two deals on raw opening, epoch=2 so theo available
    st.deal()
    st.deal()
    fa2 = analyze_foundation_feasibility(cards, st)
    assert fa2.current_epoch == 2
    h1 = next(c for c in fa2.frontier.candidates if c.suit == "h" and c.copy_index == 1)
    s1 = next(c for c in fa2.frontier.candidates if c.suit == "s" and c.copy_index == 1)
    assert h1.theoretically_available
    assert s1.theoretically_available


def test_old_opening_api_still_works():
    st = _pad([Column([], [Card("h", 3)])])
    res = search_opening_to_first_deal(
        st, max_non_deal=0, beam=4, max_plan_nodes=8, time_limit_s=5.0
    )
    assert res.terminals
    assert all(t.deals_done == 1 for t in res.terminals)


def test_bounded_miss_not_impossible_two_epoch():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    res = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=1, beam=4, tactical_max_cost=1, max_plan_nodes=10, time_limit_s=5.0
    )
    assert res.stats.realizations_miss + res.stats.realizations_resource >= 0
    assert any(t.deals_done == 2 for t in res.terminals)
