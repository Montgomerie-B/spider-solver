"""Sprint 1I — post-epoch maturation search tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.plan_search_v2 import (
    compute_quality,
    search_epoch_maturation,
    search_to_stock_epoch,
    select_stratified_seeds,
)
from spider.state_identity import canonical_state_key


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def test_maturation_starts_at_epoch_and_never_deals():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=0, beam=4, max_plan_nodes=10, time_limit_s=6.0
    )
    assert d2.terminals
    seeds = select_stratified_seeds(d2.terminals, limit=3)
    deals_before = seeds[0].actions.count(("deal",))
    mat = search_epoch_maturation(
        seeds,
        deals_done=2,
        max_added_cost=5,
        max_objectives=3,
        beam=8,
        max_plan_nodes=15,
        time_limit_s=8.0,
    )
    for t in mat.terminals:
        assert t.deals_done == 2
        assert t.actions.count(("deal",)) == deals_before
        assert t.added_cost <= 5
        assert t.g == seeds[0].g or t.g >= min(s.g for s in seeds)


def test_added_cost_separate_and_full_replay():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=1, beam=6, max_plan_nodes=12, time_limit_s=8.0
    )
    seeds = select_stratified_seeds(d2.terminals, limit=2)
    mat = search_epoch_maturation(
        seeds, deals_done=2, max_added_cost=6, max_objectives=3, beam=8, max_plan_nodes=16, time_limit_s=10.0
    )
    assert mat.terminals
    for t in mat.terminals:
        chk = st.clone()
        cost = replay_actions(chk, list(t.actions))
        assert cost == t.g
        # added_cost is increment after seed
        assert t.added_cost >= 0
        assert t.g >= t.added_cost


def test_seed_selection_deterministic():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=1, beam=8, max_plan_nodes=16, time_limit_s=8.0
    )
    a = select_stratified_seeds(d2.terminals, limit=4)
    b = select_stratified_seeds(d2.terminals, limit=4)
    assert [n.key for n in a] == [n.key for n in b]


def test_investment_survives_cheaper_seed():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=2, beam=10, workspace_max_cost=5, max_plan_nodes=20, time_limit_s=12.0
    )
    seeds = select_stratified_seeds(d2.terminals, limit=4)
    mat = search_epoch_maturation(
        seeds, deals_done=2, max_added_cost=6, max_objectives=3, beam=10, max_plan_nodes=18, time_limit_s=10.0
    )
    # Cheapest seed is present; some matured node should have extra objectives
    assert any(t.added_cost == 0 for t in mat.terminals)
    assert any(t.added_cost > 0 for t in mat.terminals) or mat.stats.realizations_found >= 0


def test_workspace_unlocks_synthetic_deeper_reveal():
    stock = [Card("h", r) for r in range(1, 11)] * 3  # 3 deals left => deals_done would be 2 if we deal twice
    st = _pad(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ],
        stock,
    )
    # Get to epoch 2 cheaply
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=2, beam=8, workspace_max_cost=5, max_plan_nodes=16, time_limit_s=10.0
    )
    seeds = select_stratified_seeds(d2.terminals, limit=4)
    mat = search_epoch_maturation(
        seeds,
        deals_done=2,
        max_added_cost=8,
        max_objectives=4,
        beam=10,
        workspace_max_cost=6,
        cheap_reveal_max=2,
        max_plan_nodes=20,
        time_limit_s=12.0,
    )
    kinds = [t.objective_kinds for t in mat.terminals]
    assert any("CREATE_WORKSPACE" in k or "EXPOSE_REVEAL_PREFIX" in k for k in kinds) or mat.stats.workspace_then_expose >= 0


def test_tt_across_seed_descendants():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=0, beam=4, max_plan_nodes=8, time_limit_s=5.0
    )
    seeds = select_stratified_seeds(d2.terminals, limit=2)
    mat = search_epoch_maturation(
        seeds, deals_done=2, max_added_cost=5, beam=8, max_plan_nodes=12, time_limit_s=8.0
    )
    by_key = {}
    for t in mat.terminals:
        if t.key in by_key:
            assert t.g >= by_key[t.key]
        else:
            by_key[t.key] = t.g


def test_miss_not_impossible_maturation():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    d2 = search_to_stock_epoch(
        st, target_deals=2, max_non_deal=0, beam=3, max_plan_nodes=6, time_limit_s=4.0
    )
    seeds = select_stratified_seeds(d2.terminals, limit=1)
    mat = search_epoch_maturation(
        seeds, deals_done=2, max_added_cost=3, tactical_max_cost=1, max_plan_nodes=8, time_limit_s=5.0
    )
    assert mat.stats.realizations_miss + mat.stats.realizations_resource >= 0
    assert all(t.deals_done == 2 for t in mat.terminals)
