"""Focused gates for zero-tolerance HOLD and stock-synchronous RESELECT."""

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
import workspace_service_stock_synchronous_v0_1 as synchronous


def _workspace_state(rows: int):
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


def _selected_lane(
    mode: str, *, workspace_rows: int = 4, ordinary_rows: int = 2
):
    workspace = _node(10, _workspace_state(workspace_rows))
    ordinary = _node(11, _ordinary_state(ordinary_rows))
    frontier = [(('z',), 10, workspace), (('a',), 11, ordinary)]
    heapq.heapify(frontier)
    lane = synchronous.StockSynchronousWorkspaceServiceLane(mode=mode)
    if mode == synchronous.RESELECT and workspace_rows != ordinary_rows:
        raise ValueError("RESELECT helper needs an initially synchronous workspace")
    lane.select(frontier, expansion_count=0)
    return lane, frontier, workspace, ordinary


def _pop(lane, frontier, expansion_count=8):
    lane.ordinary_expansions_since_service = 8
    return lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=expansion_count,
    )


def test_zero_tolerance_allows_only_lag_zero_forced_service():
    zero, frontier, workspace, _ordinary = _selected_lane(
        synchronous.HOLD, workspace_rows=2, ordinary_rows=2
    )
    item, forced = _pop(zero, frontier)
    assert forced and item[2] is workspace

    lagging, frontier, _workspace, ordinary = _selected_lane(
        synchronous.HOLD, workspace_rows=3, ordinary_rows=2
    )
    item, forced = _pop(lagging, frontier)
    assert not forced and item[2] is ordinary
    assert lagging.lagging_events[-1]["stock_lag"] == 1


def test_hold_retains_lagging_reservation_after_withholding():
    lane, frontier, workspace, _ordinary = _selected_lane(synchronous.HOLD)
    _pop(lane, frontier)
    assert lane.current_node_id == workspace.node_id
    assert lane.current_selection["outcome"] == "RESERVED"
    assert any(item[2] is workspace for item in frontier)


def test_reselect_releases_only_reservation_not_frontier_node():
    lane, frontier, workspace, _ordinary = _selected_lane(
        synchronous.RESELECT, workspace_rows=4, ordinary_rows=4
    )
    frontier.append((('0',), 12, _node(12, _ordinary_state(2))))
    heapq.heapify(frontier)
    lane.select(frontier, expansion_count=1)
    assert lane.current_node_id is None
    assert lane.reservations_released == 1
    assert any(item[2] is workspace for item in frontier)


def test_released_node_remains_ordinary_expansion_eligible():
    lane, frontier, workspace, _ordinary = _selected_lane(
        synchronous.RESELECT, workspace_rows=4, ordinary_rows=4
    )
    deeper = _node(12, _ordinary_state(2))
    frontier.append((('0',), 12, deeper))
    heapq.heapify(frontier)
    lane.select(frontier, expansion_count=1)
    frontier.remove(next(item for item in frontier if item[2] is deeper))
    heapq.heapify(frontier)
    assert service.expansion_identity(workspace) not in lane.expanded_state_credits
    ordinary_item = min(frontier, key=lambda item: (item[0], item[2].node_id))
    assert ordinary_item[2] is workspace or any(
        item[2] is workspace for item in frontier
    )


def test_reselect_selects_only_same_stock_depth_workspace_candidates():
    lane = synchronous.StockSynchronousWorkspaceServiceLane(
        mode=synchronous.RESELECT
    )
    lagging = _node(10, _workspace_state(4))
    synchronous_workspace = _node(11, _workspace_state(2))
    ordinary = _node(12, _ordinary_state(2))
    frontier = [
        (('a',), 10, lagging),
        (('z',), 11, synchronous_workspace),
        (('b',), 12, ordinary),
    ]
    heapq.heapify(frontier)
    selected = lane.select(frontier, expansion_count=0)
    assert selected[2] is synchronous_workspace
    assert synchronous.stock_rows(selected[2].state) == 2


def test_same_epoch_candidate_selection_uses_ordinary_priority_then_node_id():
    lane = synchronous.StockSynchronousWorkspaceServiceLane(
        mode=synchronous.RESELECT
    )
    later = _node(20, _workspace_state(2))
    earlier = _node(30, _workspace_state(2))
    tied_lower_id = _node(10, _workspace_state(2))
    frontier = [
        (('b',), 20, later),
        (('a',), 30, earlier),
        (('a',), 10, tied_lower_id),
    ]
    heapq.heapify(frontier)
    selected = lane.select(frontier, expansion_count=0)
    assert selected[2] is tied_lower_id


def test_release_and_reselection_do_not_clone_frontier_entries():
    lane, frontier, workspace, _ordinary = _selected_lane(
        synchronous.RESELECT, workspace_rows=4, ordinary_rows=4
    )
    candidate = _node(12, _workspace_state(2))
    frontier.append((('b',), 12, candidate))
    heapq.heapify(frontier)
    before = [item[2].node_id for item in frontier]
    lane.select(frontier, expansion_count=1)
    after = [item[2].node_id for item in frontier]
    assert sorted(after) == sorted(before)
    assert len(after) == len(set(after))
    assert any(item[2] is workspace for item in frontier)


def test_lane_has_at_most_one_current_representative():
    lane, frontier, _workspace, _ordinary = _selected_lane(
        synchronous.RESELECT, workspace_rows=2, ordinary_rows=2
    )
    lane.select(frontier, expansion_count=1)
    assert lane.max_outstanding == 1
    assert sum(
        selection["outcome"] == "RESERVED" for selection in lane.selections
    ) == 1


def test_withheld_hold_entitlement_does_not_accumulate():
    lane, frontier, _workspace, ordinary = _selected_lane(synchronous.HOLD)
    _pop(lane, frontier)
    assert lane.ordinary_expansions_since_service == 0
    lane.on_expansion(ordinary)
    assert lane.ordinary_expansions_since_service == 1


def test_stale_reservation_block_span_telemetry_is_exact():
    lane, frontier, _workspace, _ordinary = _selected_lane(synchronous.HOLD)
    _pop(lane, frontier, expansion_count=8)
    lane._completed_expansions = 50
    lane.finalize(frontier)
    summary = lane.policy_summary()["reservation_block_span"]
    assert summary["maximum"] == 42
    assert summary["median"] == 42
    assert summary["count_exceeding_32"] == 1
    assert summary["count_surviving_to_end"] == 1


def test_hold_observes_blocked_current_epoch_workspace_opportunities():
    lane, frontier, _workspace, _ordinary = _selected_lane(synchronous.HOLD)
    candidate = _node(12, _workspace_state(2))
    frontier.append((('b',), 12, candidate))
    heapq.heapify(frontier)
    _pop(lane, frontier)
    loss = lane.policy_summary()["current_epoch_opportunity_loss"]
    assert loss["occurrences"] == 1
    assert loss["unique_candidate_states"] == 1
    assert loss["events"][0]["candidate_node_id"] == candidate.node_id


def test_n8_and_frozen_rotation_are_unchanged():
    assert service.SERVICE_INTERVAL == general.CONFIG["workspace_service_interval"] == 8
    assert synchronous.ZERO_TOLERANCE == 0
    assert synchronous.RUN_SCHEDULE == {
        "P0": (synchronous.UNGUARDED, synchronous.HOLD, synchronous.RESELECT),
        "P2": (synchronous.HOLD, synchronous.RESELECT, synchronous.UNGUARDED),
        "P4": (synchronous.RESELECT, synchronous.UNGUARDED, synchronous.HOLD),
        "P7": (synchronous.UNGUARDED, synchronous.RESELECT, synchronous.HOLD),
    }


def test_production_defaults_remain_unchanged():
    before = dataclasses.asdict(controller.AnytimeControllerConfig())
    config = synchronous.common.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    after = dataclasses.asdict(controller.AnytimeControllerConfig())
    assert before == after
    assert config.max_frontier_size == 256
    assert config.max_successors_per_expansion == 10


def test_resource_planner_is_not_invoked_by_the_lane():
    assert "plan_resource_excavation" not in inspect.getsource(
        synchronous.StockSynchronousWorkspaceServiceLane
    )
