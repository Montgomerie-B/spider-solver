"""Focused gates for the one-shot lag-1 workspace grace lease."""

from __future__ import annotations

import heapq
import inspect

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicSearchNode,
    analyze_stage0_state,
)

import common_priority_schema_ab_v0_1 as common
import workspace_opportunity_service_lane_v0_1 as service
import workspace_service_generalisation_panel_v0_1 as general
import workspace_service_lag1_grace_v0_1 as grace


def _workspace_state(rows: int, *, marker: int = 0) -> SpiderState:
    return SpiderState(
        [Column([], [])]
        + [
            Column([], [Card("d", 9 - (index + marker) % 3)])
            for index in range(9)
        ],
        [Card("s", 1)] * (rows * 10),
    )


def _ordinary_state(rows: int, *, marker: int = 0) -> SpiderState:
    return SpiderState(
        [
            Column([Card("c", 10)], [Card("s", 5)]),
            Column([Card("c", 12)], [Card("h", 6)]),
        ]
        + [
            Column([Card("c", 11)], [Card("d", 9 - (index + marker) % 3)])
            for index in range(8)
        ],
        [Card("h", 1)] * (rows * 10),
    )


def _node(node_id: int, state: SpiderState) -> StrategicSearchNode:
    return StrategicSearchNode(
        node_id,
        state,
        3,
        (),
        None,
        None,
        1,
        StrategicCreditLevel.CLEAN,
        None,
        analyze_stage0_state(state, spent_cost=3, incumbent_cost=None),
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
    )


def _frontier(*items):
    result = list(items)
    heapq.heapify(result)
    return result


def _pop(lane, frontier, *, due: bool = True, expansion_count: int = 8):
    lane.ordinary_expansions_since_service = 8 if due else 0
    return lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=expansion_count,
    )


def test_lag0_remains_normally_serviceable():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(2))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("z",), 10, workspace), (("a",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert forced and item[2] is workspace
    assert lane.scheduled_opportunities[-1]["decision"] == "FORCE_LAG0"


def test_lag1_is_serviceable_when_epoch_grace_is_unused():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("z",), 10, workspace), (("a",), 11, ordinary))
    selected = lane.select(frontier, expansion_count=0)
    assert selected[2] is workspace
    assert lane.current_selection["stock_lag_at_selection"] == 1


def test_first_forced_lag1_service_consumes_exactly_its_epoch_lease():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("z",), 10, workspace), (("a",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert forced
    assert lane.lag1_grace_spent_epochs == set()
    lane.on_expansion(item[2])
    assert lane.lag1_grace_spent_epochs == {2}
    assert lane.service_events[-1]["lease_consumed"] is True


def test_second_lag1_force_in_same_epoch_is_prohibited():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    lane.lag1_grace_spent_epochs.add(2)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert not forced
    assert item[2] is workspace
    assert lane.scheduled_opportunities[-1]["decision"] == "NO_ELIGIBLE_REPRESENTATIVE"


def test_new_lower_stock_epoch_receives_fresh_lease():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    lane.lag1_grace_spent_epochs.add(2)
    workspace = _node(10, _workspace_state(2))
    ordinary = _node(11, _ordinary_state(1))
    frontier = _frontier((("z",), 10, workspace), (("a",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert forced and item[2] is workspace
    lane.on_expansion(item[2])
    assert lane.lag1_grace_spent_epochs == {1, 2}


def test_returning_to_used_stock_depth_does_not_refresh_lease():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    lane.lag1_grace_spent_epochs.update({1, 2})
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    assert lane.select(frontier, expansion_count=0) is None
    assert 2 in lane.lag1_grace_spent_epochs


def test_lag2_plus_receives_no_forced_service():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(4))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert not forced and item[2] is workspace
    assert lane.policy_summary()["forced_lag2_plus_services"] == 0


def test_natural_lagging_workspace_expansion_remains_allowed_and_free():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    item, forced = _pop(lane, frontier, due=False, expansion_count=0)
    assert not forced and item[2] is workspace
    assert lane.on_expansion(item[2]) == "WORKSPACE_NATURAL"
    assert lane.lag1_grace_spent_epochs == set()


def test_ineligible_reservation_release_leaves_frontier_unchanged():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    lane.select(frontier, expansion_count=0)
    deeper = _node(12, _ordinary_state(1, marker=1))
    frontier.append((("b",), 12, deeper))
    heapq.heapify(frontier)
    before = sorted(item[2].node_id for item in frontier)
    lane.select(frontier, expansion_count=1)
    assert lane.current_node_id is None
    assert sorted(item[2].node_id for item in frontier) == before
    assert any(item[2] is workspace for item in frontier)


def test_no_hold_style_stale_ownership_after_epoch_is_spent():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(3))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("a",), 10, workspace), (("z",), 11, ordinary))
    lane.select(frontier, expansion_count=0)
    lane.lag1_grace_spent_epochs.add(2)
    lane.select(frontier, expansion_count=1)
    assert lane.current_node_id is None
    assert lane.reservations_released == 1
    assert lane.release_events[-1]["reason"] == "LAG1_EPOCH_LEASE_SPENT"


def test_missed_service_window_has_no_catchup_entitlement():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    workspace = _node(10, _workspace_state(4))
    ordinary = _node(11, _ordinary_state(2))
    frontier = _frontier((("z",), 10, workspace), (("a",), 11, ordinary))
    item, forced = _pop(lane, frontier)
    assert not forced and item[2] is ordinary
    assert lane.ordinary_expansions_since_service == 0
    lane.on_expansion(item[2])
    assert lane.ordinary_expansions_since_service == 1


def test_n8_service_interval_remains_unchanged():
    assert service.SERVICE_INTERVAL == 8
    assert grace.CONFIG["workspace_service_interval"] == 8
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    assert lane.interval == 8


def test_candidate_selection_uses_ordinary_priority_then_node_id():
    lane = grace.Lag1GraceWorkspaceServiceLane(mode=grace.GRACE)
    later = _node(20, _workspace_state(3, marker=1))
    earlier = _node(30, _workspace_state(3, marker=2))
    tied_lower_id = _node(10, _workspace_state(3, marker=0))
    ordinary = _node(40, _ordinary_state(2))
    frontier = _frontier(
        (("b",), 20, later),
        (("a",), 30, earlier),
        (("a",), 10, tied_lower_id),
        (("z",), 40, ordinary),
    )
    assert lane.select(frontier, expansion_count=0)[2] is tied_lower_id


def test_production_defaults_remain_unchanged():
    config = common.production_shadow._production_config(seconds=1, expansions=2, nodes=3)
    assert config.frontier_priority_schema == FrontierPrioritySchema.LEGACY
    assert config.max_frontier_size == 256
    assert config.max_successors_per_expansion == 10
    assert general.CONFIG["max_credit_level"] == 4


def test_resource_planner_is_never_invoked_by_the_lane():
    assert "plan_resource_excavation" not in inspect.getsource(
        grace.Lag1GraceWorkspaceServiceLane
    )
