"""Focused gates for one-shot natural empty-state service."""

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

import one_shot_natural_empty_service_v0_1 as harness
from one_shot_natural_empty_service_v0_1 import (
    OneShotEmptyService,
    actual_empty_columns,
    choose_empty_candidate,
)


def _empty_state(rank=7):
    return SpiderState(
        [Column([], [])]
        + [Column([], [Card("s", rank - index % 3)]) for index in range(9)],
        [],
    )


def _full_state():
    return SpiderState([Column([], [Card("d", 7)]) for _ in range(10)], [])


def _node(node_id, state=None, *, g=8, credit=StrategicCreditLevel.CLEAN):
    state = state or _empty_state()
    return StrategicSearchNode(
        node_id,
        state,
        g,
        ((2, 3, 1),),
        3,
        None,
        5,
        credit,
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
    )


def _fixture():
    ordinary = _node(1, _full_state())
    first = _node(2, credit=StrategicCreditLevel.SPECULATIVE)
    second = _node(3, _empty_state(10), g=12)
    frontier = [(('a',), 1, ordinary), (('c',), 3, second), (('b',), 2, first)]
    heapq.heapify(frontier)
    service = OneShotEmptyService(
        enabled=True,
        origin_by_id={1: "SUCCESSOR", 2: "SUCCESSOR", 3: "SUCCESSOR"},
    )
    size = len(frontier)
    popped, forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    return service, frontier, ordinary, first, popped, forced, size


def test_structural_empty_eligibility_accepts_actual_engine_empty_only():
    assert actual_empty_columns(_empty_state()) == (0,)
    assert actual_empty_columns(_full_state()) == ()
    empty = _node(2)
    rebuilt = _node(3, _empty_state(10))
    full = _node(4, _full_state())
    selected, candidates = choose_empty_candidate(
        [(('b',), 2, empty), (('a',), 3, rebuilt), (('0',), 4, full)],
        {2: "SUCCESSOR", 3: "WIDENING", 4: "SUCCESSOR"},
    )
    assert selected[2] is empty
    assert [item[2].node_id for item in candidates] == [2]


def test_empty_eligibility_has_no_digest_path_card_or_benchmark_special_case():
    source = inspect.getsource(harness.eligible_empty_frontier_items)
    assert "digest" not in source
    assert "4925153" not in source
    assert "Card" not in source and "actions" not in source


def test_strongest_empty_uses_existing_priority_then_node_id():
    weaker = _node(10, g=1)
    stronger = _node(99, state=_empty_state(10), g=20)
    frontier = [(('z',), 10, weaker), (('a',), 99, stronger)]
    selected, candidates = choose_empty_candidate(
        frontier, {10: "SUCCESSOR", 99: "SUCCESSOR"}
    )
    assert selected is frontier[1]
    assert [item[2].node_id for item in candidates] == [99, 10]


def test_only_one_empty_receives_special_service():
    service, frontier, ordinary, first, popped, forced, _size = _fixture()
    assert forced and popped[2] is first
    next_item, next_forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    assert not next_forced and next_item[2] is ordinary
    assert service.services == 1


def test_serviced_empty_preserves_exact_state_g_credit_and_context():
    _service, _frontier, _ordinary, first, popped, forced, _size = _fixture()
    assert forced and popped[2] is first
    assert popped[2].state is first.state
    assert popped[2].g == first.g
    assert popped[2].credit_level is first.credit_level
    assert popped[2].actions is first.actions
    assert popped[2].stage0 is first.stage0


def test_empty_service_flag_is_permanently_spent():
    service, frontier, _ordinary, _first, _popped, _forced, _size = _fixture()
    service.pop(frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify)
    assert service.spent and service.services == 1


def test_empty_service_does_not_increase_frontier_capacity_or_clone():
    _service, frontier, _ordinary, first, popped, forced, size = _fixture()
    assert forced and popped[2] is first
    assert len(frontier) == size - 1


def test_resource_planner_is_not_part_of_empty_service():
    source = inspect.getsource(OneShotEmptyService)
    assert "resource" not in source.lower()
    assert "max_frontier_size" not in source


def test_r3_prerequisite_is_identical_between_b_and_c_definitions():
    source = inspect.getsource(harness.main)
    assert '("R3_ONLY", True, False)' in source
    assert '("R3_THEN_EMPTY", True, True)' in source
    assert "r3.OneShotR3Service" in inspect.getsource(harness.run_arm)
