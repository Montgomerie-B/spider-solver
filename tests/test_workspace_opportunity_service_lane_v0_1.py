"""Focused gates for the bounded workspace-opportunity service lane."""

from __future__ import annotations

import dataclasses
import heapq
import inspect
from types import SimpleNamespace

from spider.cards import Card
from spider.engine import Column, SpiderState
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicSearchNode,
    analyze_stage0_state,
)

import workspace_opportunity_service_lane_v0_1 as harness


def _actual_empty_state():
    return SpiderState(
        [Column([], [])]
        + [Column([], [Card("d", 9 - index % 3)]) for index in range(9)],
        [],
    )


def _empty_creatable_state():
    return SpiderState(
        [Column([], [Card("s", 5)]), Column([], [Card("h", 6)])]
        + [Column([], [Card("d", 9 - index % 3)]) for index in range(8)],
        [],
    )


def _not_empty_creatable_state():
    return SpiderState(
        [
            Column([Card("c", 10)], [Card("s", 5)]),
            Column([Card("c", 12)], [Card("h", 6)]),
        ]
        + [
            Column([Card("c", 11)], [Card("d", 9 - index % 3)])
            for index in range(8)
        ],
        [],
    )


def _node(node_id, state, *, g=3):
    return StrategicSearchNode(
        node_id,
        state,
        g,
        (),
        None,
        None,
        1,
        StrategicCreditLevel.CLEAN,
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
    )


def test_actual_empty_qualification_is_structural():
    state = _actual_empty_state()
    assert harness.actual_empty_columns(state) == (0,)
    assert harness.workspace_class(state) == "ACTUAL_EMPTY"
    assert harness.legal_empty_creating_moves(state) == ()


def test_empty_creatable_uses_engine_legal_whole_column_relocation():
    state = _empty_creatable_state()
    moves = harness.legal_empty_creating_moves(state)
    assert (0, 1, 1) in moves
    assert (0, 1, 1) in state.enumerate_moves()
    assert state.can_move(0, 1, 1)
    replay = state.clone()
    replay.move(0, 1, 1)
    assert replay.columns[0].is_empty()
    assert harness.workspace_class(state) == "EMPTY_CREATABLE"
    assert harness.workspace_class(_not_empty_creatable_state()) is None


def test_qualification_has_no_digest_card_path_or_benchmark_special_case():
    source = inspect.getsource(harness.workspace_class) + inspect.getsource(
        harness.legal_empty_creating_moves
    )
    assert "digest" not in source
    assert "4925153" not in source
    assert "Card(" not in source
    assert "source ==" not in source and "destination ==" not in source


def test_only_one_workspace_representative_exists_at_once():
    first = _node(1, _actual_empty_state())
    second = _node(2, _empty_creatable_state())
    frontier = [(('b',), 1, first), (('a',), 2, second)]
    lane = harness.WorkspaceServiceLane(enabled=True)
    lane.select(frontier, expansion_count=0)
    lane.select(frontier, expansion_count=1)
    assert lane.current_node_id == 2
    assert len(lane.selections) == 1
    assert lane.max_outstanding == 1


def test_candidate_selection_uses_existing_priority_then_node_id():
    weaker = _node(1, _actual_empty_state(), g=1)
    stronger = _node(99, _empty_creatable_state(), g=20)
    frontier = [(('z',), 1, weaker), (('a',), 99, stronger)]
    selected, candidates = harness.choose_workspace_candidate(frontier)
    assert selected is frontier[1]
    assert [item[2].node_id for item in candidates] == [99, 1]


def test_periodic_forced_service_occurs_no_more_frequently_than_configured():
    reserved = _node(10, _actual_empty_state())
    ordinary = _node(11, _not_empty_creatable_state())
    frontier = [(('z',), 10, reserved), (('a',), 11, ordinary)]
    heapq.heapify(frontier)
    lane = harness.WorkspaceServiceLane(enabled=True, interval=8)
    lane.select(frontier, expansion_count=0)
    for _ in range(7):
        lane.on_expansion(ordinary)
    item, forced = lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=7,
    )
    assert not forced and item[2] is ordinary
    lane.on_expansion(ordinary)
    item, forced = lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=8,
    )
    assert forced and item[2] is reserved
    lane.on_expansion(reserved)
    assert lane.service_intervals == [8]


def test_natural_expansion_spends_and_allows_replacement():
    first = _node(1, _actual_empty_state())
    second = _node(2, _empty_creatable_state())
    frontier = [(('a',), 1, first), (('z',), 2, second)]
    heapq.heapify(frontier)
    lane = harness.WorkspaceServiceLane(enabled=True)
    lane.select(frontier, expansion_count=0)
    item, forced = lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=0,
    )
    assert not forced and item[2] is first
    assert lane.on_expansion(first) == "WORKSPACE_NATURAL"
    assert lane.current_node_id is None and lane.natural_services == 1
    lane.select(frontier, expansion_count=1)
    assert lane.current_node_id == 2 and len(lane.selections) == 2


def test_frontier_width_remains_unchanged_during_protection():
    opening = _not_empty_creatable_state()
    observer = harness.WorkspaceServiceObserver(opening, enable_service=True)
    observer._originals["heapify"] = heapq.heapify
    representative = _node(7, _actual_empty_state())
    ordinary_a = _node(8, opening)
    ordinary_b = _node(9, opening)
    original = [(('z',), 7, representative), (('a',), 8, ordinary_a), (('b',), 9, ordinary_b)]
    observer.lane.select(original, expansion_count=0)
    kept = [(('a',), 8, ordinary_a), (('b',), 9, ordinary_b)]
    result = observer._protect_workspace_representative(
        original,
        kept,
        {"portfolio": SimpleNamespace(profiles=()), "pre_foundation_portfolio": None},
    )
    assert len(result) == len(kept) == 2
    assert any(item[2] is representative for item in result)


def test_lane_reuses_exact_entry_and_never_clones_it():
    representative = _node(7, _actual_empty_state())
    item = (('z',), 7, representative)
    frontier = [item]
    lane = harness.WorkspaceServiceLane(enabled=True, interval=1)
    lane.select(frontier, expansion_count=0)
    lane.on_expansion(_node(8, _not_empty_creatable_state()))
    popped, forced = lane.pop(
        frontier,
        ordinary_pop=heapq.heappop,
        ordinary_heapify=heapq.heapify,
        expansion_count=1,
    )
    assert forced and popped is item and popped[2] is representative
    assert frontier == []


def test_overlap_with_existing_protection_does_not_add_duplicate():
    opening = _not_empty_creatable_state()
    observer = harness.WorkspaceServiceObserver(opening, enable_service=True)
    observer._originals["heapify"] = heapq.heapify
    representative = _node(7, _actual_empty_state())
    item = (('a',), 7, representative)
    original = [item, (('b',), 8, _node(8, opening))]
    observer.lane.select(original, expansion_count=0)
    kept = list(original)
    result = observer._protect_workspace_representative(
        original,
        kept,
        {"portfolio": SimpleNamespace(profiles=()), "pre_foundation_portfolio": None},
    )
    assert len(result) == 2
    assert sum(entry[2].node_id == 7 for entry in result) == 1
    assert observer.lane.lane_duplicate_entries_introduced == 0


def test_production_defaults_remain_unchanged():
    before = dataclasses.asdict(controller.AnytimeControllerConfig())
    config = harness.common.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    after = dataclasses.asdict(controller.AnytimeControllerConfig())
    assert before == after
    assert config.max_frontier_size == 256
    assert config.max_successors_per_expansion == 10


def test_resource_planner_is_not_integrated_or_called_by_lane():
    assert "resource_excavation" not in inspect.getsource(controller)
    assert "plan_resource_excavation" not in inspect.getsource(
        harness.WorkspaceServiceLane
    )
