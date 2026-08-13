"""Sprint 1F — objective realizer tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.lower_bounds import compute_objective_lower_bound
from spider.planner.objective_realizer import (
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
    evaluate_target,
    generate_objective_portfolio,
)
from spider.planner.space_lifecycle import empty_count


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    return SpiderState(cols, list(stock or []), [])


def _obj(**kwargs) -> StrategicObjective:
    defaults = dict(
        kind=ObjectiveKind.CREATE_WORKSPACE,
        objective_id="t",
        description="t",
        target_key="empty_count_ge",
        target_params={"min_empty": 1},
        hard_preconditions=(),
        hard_evidence=(),
        admissible_lb=0,
        admissible_breakdown=None,
        heuristic_est_cost=2.0,
        heuristic_est_benefit=1.0,
        priority=PriorityComponents(),
        foundation_relevance="",
        workspace_relevance="",
        stock_relevance="",
        explanation="",
    )
    defaults.update(kwargs)
    return StrategicObjective(**defaults)


def test_reveal_not_satisfied_by_duplicate_elsewhere():
    st = _pad(
        [
            Column([Card("s", 3)], [Card("h", 2)]),
            Column([], [Card("s", 3)]),
        ]
    )
    assert not evaluate_target(
        st, "column_face_down_le", {"column": 0, "max_face_down": 0}
    )


def test_deal_now_exact():
    stock = [Card("h", r) for r in range(1, 11)] * 2
    st = _pad([Column([], [Card("s", 5)])], stock)
    obj = _obj(
        kind=ObjectiveKind.DEAL_NOW,
        target_key="stock_epoch_advanced",
        target_params={"deals_before": 2},
        admissible_lb=1,
        heuristic_est_cost=1,
    )
    r = realize_objective(st, obj)
    assert r.status == RealizationStatus.FOUND
    assert r.actions == (("deal",),)
    assert r.corrected_mw_cost == 1
    assert r.target_verified
    assert r.exact_within_bound


def test_one_move_workspace_creation():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    assert empty_count(st) == 0
    obj = _obj(target_params={"min_empty": 1}, heuristic_est_cost=2)
    r = realize_objective(st, obj, max_cost=2, max_nodes=500)
    assert r.status == RealizationStatus.FOUND
    assert r.corrected_mw_cost == 1
    assert r.target_verified
    st2 = st.clone()
    from spider.metrics import replay_actions

    replay_actions(st2, list(r.actions))
    assert empty_count(st2) >= 1


def test_multi_move_workspace_and_zero_cost():
    # Fully open 9s-8s, empty dest: relocate free then we already have empty? 
    # Start with 0 empties: two open columns that can merge creating empty
    st = _pad(
        [
            Column([], [Card("c", 10), Card("c", 9)]),
            Column([], [Card("c", 8)]),
        ]
    )
    obj = _obj(target_params={"min_empty": 1})
    r = realize_objective(st, obj, max_cost=3)
    assert r.status == RealizationStatus.FOUND
    assert r.target_verified


def test_receiver_shaping():
    stock = [Card("c", 8)] + [Card("h", r) for r in range(2, 11)] + [Card("h", r) for r in range(1, 11)] * 4
    st = _pad(
        [
            Column([], [Card("c", 9), Card("d", 5)]),
            Column([], [Card("d", 6)]),
        ],
        stock,
    )
    obj = _obj(
        kind=ObjectiveKind.SHAPE_STOCK_RECEIVER,
        target_key="column_top_is",
        target_params={"column": 0, "suit": "c", "rank": 9},
        heuristic_est_cost=2,
    )
    r = realize_objective(st, obj, max_cost=2)
    assert r.status == RealizationStatus.FOUND
    assert r.target_verified
    assert r.corrected_mw_cost == 1


def test_reveal_prefix_realisation():
    st = _pad(
        [
            Column([Card("c", 3)], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    obj = _obj(
        kind=ObjectiveKind.EXPOSE_REVEAL_PREFIX,
        target_key="column_face_down_le",
        target_params={"column": 0, "max_face_down": 0, "required_reveals": 1},
        heuristic_est_cost=3,
        admissible_lb=1,
    )
    r = realize_objective(st, obj, max_cost=3)
    assert r.status == RealizationStatus.FOUND
    assert r.target_verified
    assert len(st.columns[0].face_down) == 1
    from spider.metrics import replay_actions

    st2 = st.clone()
    replay_actions(st2, list(r.actions))
    assert len(st2.columns[0].face_down) == 0


def test_zero_cost_relocate_in_path():
    st = _pad(
        [
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], []),
            Column([], [Card("s", 7)]),
        ]
    )
    # create second empty by relocating then merging 8s onto 9? 
    # already 1 empty. Target 2 empties: move 7s onto 8s (col2->col0) creates empty
    obj = _obj(target_params={"min_empty": 2})
    r = realize_objective(st, obj, max_cost=2)
    assert r.status == RealizationStatus.FOUND
    # Path may include free relocate
    assert r.corrected_mw_cost is not None
    assert r.corrected_mw_cost <= 1


def test_bounded_miss_not_impossible():
    st = _pad([Column([], [Card("s", 13)])] * 10)  # all kings, no empties, no creates
    obj = _obj(target_params={"min_empty": 1}, heuristic_est_cost=1)
    r = realize_objective(st, obj, max_cost=1, max_nodes=200)
    assert r.status in (
        RealizationStatus.NOT_FOUND_WITHIN_BOUND,
        RealizationStatus.RESOURCE_LIMIT,
    )
    assert r.status != RealizationStatus.UNSUPPORTED
    assert any("impossible" in n or "not_found" in n.lower() or "limit" in n.lower() for n in r.notes)


def test_deterministic_synthetic():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    obj = _obj(target_params={"min_empty": 1})
    r1 = realize_objective(st, obj, mode=RealizationMode.EXACT_BOUNDED, max_cost=2)
    r2 = realize_objective(st, obj, mode=RealizationMode.EXACT_BOUNDED, max_cost=2)
    assert r1.status == r2.status == RealizationStatus.FOUND
    assert r1.actions == r2.actions
    assert r1.corrected_mw_cost == r2.corrected_mw_cost


def test_replay_cost_matches():
    st = _pad(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
    )
    obj = _obj(target_params={"min_empty": 1})
    r = realize_objective(st, obj, max_cost=2)
    from spider.metrics import replay_actions

    st2 = st.clone()
    recost = replay_actions(st2, list(r.actions))
    assert recost == r.corrected_mw_cost


def test_portfolio_deal_now_on_benchmark():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    p = generate_objective_portfolio(st, cards=cards)
    deal_objs = [o for o in p.objectives if o.kind == ObjectiveKind.DEAL_NOW]
    assert deal_objs
    r = realize_objective(st, deal_objs[0])
    assert r.status == RealizationStatus.FOUND
    assert r.corrected_mw_cost == 1
