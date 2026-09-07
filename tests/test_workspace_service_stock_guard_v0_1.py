"""Focused mechanical gates for the stock-aware N8 service guard."""

from __future__ import annotations

import dataclasses
import heapq
import inspect

from spider.cards import Card
from spider.engine import Column, SpiderState
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicSearchNode,
    analyze_stage0_state,
)

import workspace_opportunity_service_lane_v0_1 as service
import workspace_service_generalisation_panel_v0_1 as general
import workspace_service_stock_guard_v0_1 as guard


def _actual_empty_state(rows: int):
    return SpiderState(
        [Column([], [])]
        + [Column([], [Card("d", 9 - index % 3)]) for index in range(9)],
        [Card("s", 1)] * (rows * 10),
    )


def _ordinary_state(rows: int):
    return SpiderState(
        [
            Column([Card("c", 10)], [Card("s", 5)]),
            Column([Card("c", 12)], [Card("h", 6)]),
        ]
        + [
            Column([Card("c", 11)], [Card("d", 9 - index % 3)])
            for index in range(8)
        ],
        [Card("h", 1)] * (rows * 10),
    )


def _node(node_id: int, state: SpiderState):
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


def _due_lane(workspace_rows: int, ordinary_rows: int, *, guard_enabled=True):
    workspace = _node(10, _actual_empty_state(workspace_rows))
    ordinary = _node(11, _ordinary_state(ordinary_rows))
    frontier = [(('z',), 10, workspace), (('a',), 11, ordinary)]
    heapq.heapify(frontier)
    lane = guard.StockGuardWorkspaceServiceLane(
        stock_guard_enabled=guard_enabled
    )
    lane.select(frontier, expansion_count=0)
    lane.ordinary_expansions_since_service = 8
    return lane, frontier, workspace, ordinary


def _pop(lane, frontier):
    return lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=8,
    )


def test_stock_lag_uses_only_live_unique_nonstale_ordinary_entries():
    lane, frontier, workspace, ordinary = _due_lane(4, 2)
    stale = _node(12, _ordinary_state(0))
    lane.expanded_state_credits.add(service.expansion_identity(stale))
    frontier.extend([(('0',), 12, stale), (('b',), 11, ordinary)])
    items = guard.ordinary_live_frontier_items(frontier, lane)
    assert {item[2].node_id for item in items} == {workspace.node_id, ordinary.node_id}
    assert guard.stock_lag(lane.current_item, items) == (4, 2, 2)


def test_lower_undealt_row_count_means_further_progression():
    lane, frontier, _workspace, _ordinary = _due_lane(5, 1)
    items = guard.ordinary_live_frontier_items(frontier, lane)
    workspace_rows, best_rows, lag = guard.stock_lag(lane.current_item, items)
    assert (workspace_rows, best_rows, lag) == (5, 1, 4)
    assert best_rows < workspace_rows


def test_lag_zero_allows_forced_service():
    lane, frontier, workspace, _ordinary = _due_lane(2, 2)
    item, forced = _pop(lane, frontier)
    assert forced and item[2] is workspace
    assert lane.guard_events[-1]["decision"] == "SERVICE"
    assert lane.guard_events[-1]["stock_lag"] == 0


def test_lag_one_allows_forced_service():
    lane, frontier, workspace, _ordinary = _due_lane(3, 2)
    item, forced = _pop(lane, frontier)
    assert forced and item[2] is workspace
    assert lane.guard_events[-1]["decision"] == "SERVICE"
    assert lane.guard_events[-1]["stock_lag"] == 1


def test_lag_two_or_more_withholds_forced_service():
    lane, frontier, _workspace, ordinary = _due_lane(4, 2)
    item, forced = _pop(lane, frontier)
    assert not forced and item[2] is ordinary
    assert lane.guard_events[-1]["decision"] == "WITHHOLD_STOCK_LAG"
    assert lane.guard_events[-1]["stock_lag"] == 2


def test_natural_workspace_pop_is_never_blocked():
    lane, frontier, workspace, _ordinary = _due_lane(4, 1)
    frontier[:] = [(('a',), 10, workspace), (('z',), 11, frontier[0][2])]
    heapq.heapify(frontier)
    lane.current_item = frontier[0]
    item, forced = _pop(lane, frontier)
    assert not forced and item[2] is workspace
    assert lane.on_expansion(workspace) == "WORKSPACE_NATURAL"


def test_withheld_entitlement_does_not_accumulate():
    lane, frontier, _workspace, ordinary = _due_lane(4, 2)
    _pop(lane, frontier)
    assert lane.ordinary_expansions_since_service == 0
    lane.on_expansion(ordinary)
    assert lane.ordinary_expansions_since_service == 1


def test_representative_remains_valid_after_withholding():
    lane, frontier, workspace, _ordinary = _due_lane(4, 2)
    _pop(lane, frontier)
    assert lane.current_node_id == workspace.node_id
    assert any(item[2] is workspace for item in frontier)
    assert lane.current_selection["outcome"] == "RESERVED"


def test_guard_never_clones_or_reinserts_nodes():
    lane, frontier, workspace, ordinary = _due_lane(4, 2)
    original_ids = [item[2].node_id for item in frontier]
    _pop(lane, frontier)
    remaining_ids = [item[2].node_id for item in frontier]
    assert sorted(original_ids) == sorted([ordinary.node_id, workspace.node_id])
    assert remaining_ids == [workspace.node_id]
    assert len(remaining_ids) == len(set(remaining_ids))


def test_guard_does_not_change_fixed_frontier_capacity():
    lane, frontier, _workspace, _ordinary = _due_lane(4, 2)
    before = len(frontier)
    _pop(lane, frontier)
    assert len(frontier) == before - 1
    assert general.CONFIG["max_frontier_size"] == 256


def test_threshold_is_exactly_one():
    assert guard.STOCK_LAG_THRESHOLD == 1
    assert guard.CONFIG["stock_lag_threshold"] == 1
    assert "lag > STOCK_LAG_THRESHOLD" in inspect.getsource(
        guard.StockGuardWorkspaceServiceLane.pop
    )


def test_frozen_panel_and_n8_mechanism_are_unchanged():
    assert guard.service.SERVICE_INTERVAL == general.CONFIG["workspace_service_interval"] == 8
    assert guard.StockGuardWorkspaceServiceLane.__mro__[1] is service.WorkspaceServiceLane
    assert general.panel_definition()["panel_id"] == "workspace-service-panel-v0-1"
    assert [guard.arm_order(index) for index in range(2)] == [
        ("WORKSPACE_N8_STOCK_GUARD", "WORKSPACE_N8"),
        ("WORKSPACE_N8", "WORKSPACE_N8_STOCK_GUARD"),
    ]


def test_production_defaults_and_resource_planner_remain_unchanged():
    before = dataclasses.asdict(controller.AnytimeControllerConfig())
    config = guard.common.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    after = dataclasses.asdict(controller.AnytimeControllerConfig())
    assert before == after
    assert config.max_frontier_size == 256
    assert config.max_successors_per_expansion == 10
    assert "plan_resource_excavation" not in inspect.getsource(
        guard.StockGuardWorkspaceServiceLane
    )
