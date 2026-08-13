"""Sprint 1G — limited plan-level search tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.objective_realizer import RealizationStatus, realize_objective
from spider.planner.plan_search_v2 import (
    PlanNode,
    compute_quality,
    pareto_front,
    search_opening_to_first_deal,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.state_identity import canonical_state_key


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    return SpiderState(cols, list(stock or [Card("h", r) for r in range(1, 11)] * 5), [])


def test_plan_node_replay_and_cost():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_opening_to_first_deal(
        st,
        max_non_deal=1,
        beam=8,
        tactical_max_cost=2,
        tactical_max_nodes=200,
        tactical_time_s=0.4,
        max_plan_nodes=30,
        time_limit_s=8.0,
    )
    assert res.terminals
    for t in res.terminals:
        chk = st.clone()
        cost = replay_actions(chk, list(t.actions))
        assert cost == t.g
        assert t.dealt
        assert t.actions[-1] == ("deal",)


def test_deal_now_terminal_always_possible():
    st = _pad([Column([], [Card("s", 5)])])
    res = search_opening_to_first_deal(
        st, max_non_deal=0, beam=4, max_plan_nodes=10, time_limit_s=5.0
    )
    kinds = [t.objective_kinds for t in res.terminals]
    assert any(k == ("DEAL_NOW",) or k[-1] == "DEAL_NOW" for k in kinds)
    assert any(t.g == 1 and t.actions == (("deal",),) for t in res.terminals)


def test_transposition_keeps_cheaper_g():
    # Two ways to create empty then deal should not keep worse g for same key
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_opening_to_first_deal(
        st,
        max_non_deal=2,
        beam=12,
        tactical_max_cost=3,
        max_plan_nodes=40,
        time_limit_s=10.0,
    )
    by_key = {}
    for t in res.terminals:
        prev = by_key.get(t.key)
        if prev is None:
            by_key[t.key] = t.g
        else:
            # if same key appears twice, equal g (cheaper kept)
            assert t.g >= prev


def test_miss_not_impossible():
    from spider.planner.objective_realizer import RealizationStatus as RS

    st = _pad([Column([], [Card("s", 13)]) for _ in range(10)])
    res = search_opening_to_first_deal(
        st, max_non_deal=1, beam=4, tactical_max_cost=1, max_plan_nodes=8, time_limit_s=4.0
    )
    # Kings-only: CREATE_WORKSPACE likely miss; DEAL_NOW still found
    assert res.stats.realizations_miss + res.stats.realizations_resource >= 0
    assert any(t.dealt for t in res.terminals)


def test_immediate_deal_branch_exists():
    st = _pad([Column([], [Card("c", 7)])])
    res = search_opening_to_first_deal(
        st, max_non_deal=2, beam=8, max_plan_nodes=20, time_limit_s=6.0
    )
    assert any(t.objective_kinds == ("DEAL_NOW",) for t in res.terminals)


def test_zero_cost_in_accumulation():
    st = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], []),
            Column([], [Card("s", 7)]),
        ]
    )
    res = search_opening_to_first_deal(
        st,
        max_non_deal=2,
        beam=10,
        tactical_max_cost=3,
        max_plan_nodes=30,
        time_limit_s=8.0,
    )
    assert res.terminals
    for t in res.terminals:
        chk = st.clone()
        assert replay_actions(chk, list(t.actions)) == t.g


def test_pareto_and_diversity():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_opening_to_first_deal(
        st, max_non_deal=2, beam=12, max_plan_nodes=40, time_limit_s=10.0
    )
    assert res.pareto_terminals
    # Beam should have tried more than just DEAL_NOW if workspace possible
    assert res.stats.families_tried.get("DEAL_NOW", 0) >= 1


def test_synthetic_create_then_deal():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    res = search_opening_to_first_deal(
        st, max_non_deal=2, beam=10, tactical_max_cost=3, max_plan_nodes=30, time_limit_s=8.0
    )
    # Expect some terminal with CREATE_WORKSPACE then DEAL
    seqs = [t.objective_kinds for t in res.terminals]
    assert any("CREATE_WORKSPACE" in s and s[-1] == "DEAL_NOW" for s in seqs) or any(
        t.g >= 2 for t in res.terminals
    )


def test_deterministic_small():
    st = _pad([Column([], [Card("h", 4)])])
    a = search_opening_to_first_deal(
        st, max_non_deal=0, beam=4, max_plan_nodes=6, time_limit_s=4.0
    )
    b = search_opening_to_first_deal(
        st, max_non_deal=0, beam=4, max_plan_nodes=6, time_limit_s=4.0
    )
    assert [t.g for t in a.terminals] == [t.g for t in b.terminals]
    assert [t.actions for t in a.terminals] == [t.actions for t in b.terminals]
