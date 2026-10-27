"""v0.129 goal-directed anchored scheduling.

Uniform-cost search stays available. The goal policy reorders expansion
and does not delete legal moves or change corrected costs.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import search_segment, target_displacement
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import all_legal_actions, apply_action, step_cost
from spider.rules import MW_RULES
from spider.search_kernel import SearchLimits, run_search


def _cards(text: str):
    return [Card.parse(tok) for tok in text.split() if tok]


def _state(columns, stock="") -> SpiderState:
    cols = []
    for index in range(10):
        spec = columns.get(index, "")
        cols.append(Column([], _cards(spec)))
    return SpiderState(cols, _cards(stock), [])


def _root(state: SpiderState) -> dict:
    return {"ordered_digest": pack_state(state).hex(), "g": 0}


def test_unique_cap_stores_and_checks_the_boundary_child():
    state = _state({0: "kh"})
    checked = run_search(
        [_root(state)],
        limits=SearchLimits(max_unique=2, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=lambda candidate: candidate.columns[0].is_empty(),
        actions_fn=all_legal_actions,
        stop_on_first_terminal=False,
    )
    assert checked.stop_reason == "unique limit"
    assert checked.unique == 2
    assert len(checked.nodes) == 2
    assert len(checked.terminals) == 1
    assert checked.terminals[0]["g"] == 0

    stored = run_search(
        [_root(state)],
        limits=SearchLimits(max_unique=2, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=lambda _candidate: False,
        actions_fn=all_legal_actions,
    )
    assert stored.stop_reason == "unique limit"
    assert stored.unique == 2
    assert len(stored.nodes) == 2
    assert stored.terminals == []


def test_displacement_is_ordering_and_zero_cost_moves_stay_legal():
    source = _state({0: "kh qh"})
    target = _state({0: "kh", 1: "qh"})
    assert target_displacement(target, target) == 0
    assert target_displacement(source, target) > 0
    worse = source.clone()
    assert step_cost(worse, (0, 2, 2)) == 0
    apply_action(worse, (0, 2, 2))
    paid = source.clone()
    assert step_cost(paid, (0, 1, 1)) == 1
    apply_action(paid, (0, 1, 1))
    assert target_displacement(paid, target) == 0
    assert target_displacement(paid, target) < target_displacement(worse, target)
    assert (target_displacement(paid, target), 1) < (target_displacement(worse, target), 0)

    found = search_segment(source, target, 2, time_limit_s=2, max_unique=200, policy="goal")
    assert found.status == "FOUND"
    assert found.cost == 1
    assert found.cost_optimal is False
    assert found.proof is False
    assert found.zero_cost_actions >= 1
    assert found.policy == "goal"

    control = search_segment(
        source, target, 2, time_limit_s=2, max_unique=200, exhaustive=True, policy="ucs"
    )
    assert control.status == "FOUND"
    assert control.cost == 1
    assert control.cost_optimal is True
    assert control.policy == "ucs"


def test_goal_and_ucs_finish_the_same_capped_graph():
    source = _state({0: "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah", 1: "kh"})
    target = source.clone()
    apply_action(target, (0, 1, 12))
    ucs = search_segment(source, target, 1, time_limit_s=2, max_unique=500, exhaustive=True, policy="ucs")
    goal = search_segment(source, target, 1, time_limit_s=2, max_unique=500, exhaustive=True, policy="goal")
    assert ucs.status == "EXHAUSTED"
    assert goal.status == "EXHAUSTED"
    assert ucs.proof is True and goal.proof is True
    assert ucs.cost_optimal is True and goal.cost_optimal is True
    assert ucs.unique == goal.unique
    assert ucs.expanded == goal.expanded
    assert ucs.generated == goal.generated
    assert ucs.zero_cost_actions == goal.zero_cost_actions
    assert ucs.lower_bound_prunes == goal.lower_bound_prunes
    assert goal.duplicate_skips >= 1


def test_unrestricted_deal_is_not_removed_by_goal_order():
    stock = "ah 2h 3h 4h 5h 6h 7h 8h 9h 10h"
    source = _state({0: "kh"}, stock=stock)
    assert source.columns[1].is_empty()
    assert MW_RULES.can_deal_into_empty is True
    legal = all_legal_actions(source)
    assert ("deal",) in legal
    seen = []

    def actions(state):
        found = all_legal_actions(state)
        seen.append(tuple(found))
        return found

    target = _state({0: "kh", 2: "qh"})
    import spider.human_strategy.anchored as anchored

    original = anchored.all_legal_actions
    anchored.all_legal_actions = actions
    try:
        search_segment(source, target, 2, time_limit_s=2, max_unique=8, policy="goal")
    finally:
        anchored.all_legal_actions = original
    assert seen
    assert ("deal",) in seen[0]
    assert list(seen[0]) == legal


def test_goal_can_expand_a_paid_state_before_the_graph_is_finished():
    source = _state({0: "kh qh jh"})
    target = _state({0: "kh", 1: "qh", 2: "jh"})
    found = search_segment(source, target, 3, time_limit_s=2, max_unique=80, policy="goal")
    assert found.status == "FOUND"
    assert found.cost == 2
    assert found.cost_optimal is False
    assert any(layer >= 1 for layer, _count in found.expanded_by_g)
    assert found.zero_cost_actions >= 1


def test_unknown_policy_is_rejected():
    source = _state({0: "kh"})
    try:
        search_segment(source, source, 1, policy="orbit")
    except ValueError as exc:
        assert "orbit" in str(exc)
    else:
        raise AssertionError("orbit policy was accepted")
