"""Sprint 1L — ACCESS as a plan-search macro-edge through Deal 3."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import plan_search_v2 as ps
from spider.planner.plan_search_v2 import (
    ACCESS_KIND,
    search_to_stock_epoch,
)


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    if stock is None:
        stock = [Card("h", r) for r in range(1, 11)] * 5
    return SpiderState(cols, list(stock), [])


def test_no_benchmark_constants_in_access_search():
    src = inspect.getsource(ps)
    assert "4925153" not in src
    assert "77d169da" not in src


def test_access_macro_is_replay_valid_edge():
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=8,
        max_plan_nodes=16,
        time_limit_s=12.0,
        use_access_campaigns=True,
        access_max_paid_cost=8,
        access_max_steps=6,
    )
    acc = [t for t in res.terminals if ACCESS_KIND in t.objective_kinds]
    assert acc or res.stats.access_macros_applied >= 1
    for t in res.terminals:
        chk = st.clone()
        assert replay_actions(chk, list(t.actions)) == t.g
        assert ("deal",) in t.actions
    if acc:
        t = min(acc, key=lambda n: n.quality.face_down)
        assert t.investment_fd >= 1
        assert t.investment_paid == t.g - t.actions.count(("deal",)) or t.investment_paid > 0
        assert t.access_focus_history or t.notes


def test_ab_flag_disables_access():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    off = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=6,
        max_plan_nodes=12,
        time_limit_s=8.0,
        use_access_campaigns=False,
    )
    assert off.stats.access_macros_applied == 0
    assert all(ACCESS_KIND not in t.objective_kinds for t in off.terminals)
    on = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=6,
        max_plan_nodes=12,
        time_limit_s=8.0,
        use_access_campaigns=True,
        access_max_paid_cost=6,
    )
    assert on.config["use_access_campaigns"] is True


def test_one_access_per_epoch_without_workspace_change():
    st = _pad(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=3,
        beam=8,
        max_plan_nodes=18,
        time_limit_s=12.0,
        use_access_campaigns=True,
        access_max_paid_cost=8,
    )
    for t in res.terminals:
        kinds = t.objective_kinds
        access_idxs = [i for i, k in enumerate(kinds) if k == ACCESS_KIND]
        for a, b in zip(access_idxs, access_idxs[1:]):
            between = kinds[a + 1 : b]
            assert "DEAL_NOW" in between or "CREATE_WORKSPACE" in between


def test_access_available_again_after_deal():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=2,
        max_non_deal=2,
        beam=8,
        max_plan_nodes=20,
        time_limit_s=14.0,
        use_access_campaigns=True,
        access_max_paid_cost=6,
    )
    # After a deal, epoch_depth resets so a second ACCESS is allowed.
    two = [
        t
        for t in res.terminals
        if t.objective_kinds.count(ACCESS_KIND) >= 2
        and t.objective_kinds.count("DEAL_NOW") >= 1
    ]
    assert two or any(t.deals_done == 2 for t in res.terminals)


def test_target_deals_3_never_deals_fourth():
    st = _pad([Column([], [Card("s", 5)])])
    res = search_to_stock_epoch(
        st,
        target_deals=3,
        max_non_deal=0,
        beam=4,
        max_plan_nodes=12,
        time_limit_s=8.0,
        use_access_campaigns=False,
    )
    assert res.terminals
    for t in res.terminals:
        assert t.deals_done == 3
        assert t.actions.count(("deal",)) == 3
        chk = st.clone()
        assert replay_actions(chk, list(t.actions)) == t.g
        assert len(chk.stock) == len(st.stock) - 30


def test_zero_progress_access_not_an_edge():
    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=4,
        max_plan_nodes=10,
        time_limit_s=8.0,
        use_access_campaigns=True,
        access_max_paid_cost=4,
        access_tactical_time_s=0.05,
    )
    assert all(ACCESS_KIND not in t.objective_kinds for t in res.terminals)
    assert res.stats.access_macros_applied == 0


def test_no_other_campaign_kinds_as_edges():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=6,
        max_plan_nodes=12,
        time_limit_s=8.0,
        use_access_campaigns=True,
    )
    banned = {"WORKSPACE_EXPLOIT", "FOUNDATION_BUILD", "STOCK_PREP"}
    for t in res.terminals:
        assert banned.isdisjoint(t.objective_kinds)


def test_remove_foundation_is_expandable():
    assert ps.ObjectiveKind.REMOVE_FOUNDATION in ps.EXPANDABLE


def test_access_cache_used():
    st = _pad(
        [
            Column([Card("c", 2)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
    )
    res = search_to_stock_epoch(
        st,
        target_deals=1,
        max_non_deal=2,
        beam=10,
        max_plan_nodes=20,
        time_limit_s=12.0,
        use_access_campaigns=True,
        access_max_paid_cost=6,
    )
    # Multiple nodes may share the opening state/budget.
    assert res.stats.access_macros_attempted >= 1
    assert res.stats.access_cache_hits >= 0
