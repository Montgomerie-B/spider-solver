"""Focused gates for the harness-only natural-R3 service override."""

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

from one_shot_natural_r3_service_v0_1 import (
    OneShotR3Service,
    choose_r3_candidate,
    legal_full_column_empty_creating_moves,
)


def _r3_state(source_rank=5):
    columns = [
        Column([], [Card("s", source_rank), Card("s", source_rank - 1)]),
        Column([], [Card("h", source_rank + 1)]),
    ]
    columns.extend(Column([], [Card("c", 13 - index)]) for index in range(8))
    return SpiderState(columns, [])


def _node(node_id, state=None, *, g=7, credit=StrategicCreditLevel.CLEAN):
    state = state or _r3_state()
    return StrategicSearchNode(
        node_id,
        state,
        g,
        ((2, 3, 1),),
        3,
        None,
        4,
        credit,
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
    )


def test_engine_structural_r3_detection_has_no_digest_or_benchmark_special_case():
    assert (0, 1, 2) in legal_full_column_empty_creating_moves(_r3_state(5))
    assert (0, 1, 2) in legal_full_column_empty_creating_moves(_r3_state(8))
    source = inspect.getsource(legal_full_column_empty_creating_moves)
    assert "digest" not in source
    assert "4925153" not in source
    assert ".enumerate_moves()" in source and ".can_move(*action)" in source
    natural = _node(2)
    reconstructed = _node(3, state=_r3_state(8))
    selected, candidates = choose_r3_candidate(
        [(('b',), 2, natural), (('a',), 3, reconstructed)],
        {2: "SUCCESSOR", 3: "WIDENING"},
    )
    assert selected[2] is natural
    assert [item[2].node_id for item in candidates] == [2]


def test_selection_uses_existing_queue_ordering_not_node_arrival_or_digest():
    weaker = _node(10, g=1)
    stronger = _node(99, g=20)
    frontier = [(('z',), 10, weaker), (('a',), 99, stronger)]
    selected, candidates = choose_r3_candidate(
        frontier, {10: "SUCCESSOR", 99: "SUCCESSOR"}
    )
    assert selected is frontier[1]
    assert [item[2].node_id for item in candidates] == [99, 10]


def test_control_never_intervenes():
    node = _node(10)
    frontier = [(('z',), 10, node)]
    service = OneShotR3Service(enabled=False, origin_by_id={10: "SUCCESSOR"})
    popped, forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    assert popped[2] is node and not forced
    assert service.services == 0 and not service.spent


def _service_fixture():
    ordinary = _node(1, state=SpiderState(
        [Column([], [Card("d", 7)]) for _ in range(10)], []
    ))
    first = _node(2, credit=StrategicCreditLevel.SPECULATIVE)
    second = _node(3, state=_r3_state(8), g=11)
    frontier = [(('a',), 1, ordinary), (('c',), 3, second), (('b',), 2, first)]
    heapq.heapify(frontier)
    service = OneShotR3Service(
        enabled=True,
        origin_by_id={1: "SUCCESSOR", 2: "SUCCESSOR", 3: "SUCCESSOR"},
    )
    size = len(frontier)
    popped, forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    return service, frontier, ordinary, first, popped, forced, size


def test_exactly_one_existing_r3_receives_special_service():
    service, frontier, ordinary, first, popped, forced, _size = _service_fixture()
    assert forced and popped[2] is first

    second_pop, second_forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    assert not second_forced and second_pop[2] is ordinary
    assert service.services == 1


def test_service_does_not_increase_frontier_capacity_or_clone_arrival():
    _service, frontier, _ordinary, first, popped, forced, size = _service_fixture()
    assert forced and popped[2] is first
    assert len(frontier) == size - 1


def test_serviced_node_preserves_exact_state_g_credit_and_context():
    _service, _frontier, _ordinary, first, popped, forced, _size = _service_fixture()
    assert forced and popped[2] is first
    assert popped[2].state is first.state
    assert popped[2].g == first.g
    assert popped[2].credit_level is first.credit_level
    assert popped[2].actions is first.actions
    assert popped[2].stage0 is first.stage0


def test_intervention_is_permanently_spent_after_first_service():
    service, frontier, ordinary, _first, _popped, _forced, _size = _service_fixture()
    second_pop, second_forced = service.pop(
        frontier, ordinary_pop=heapq.heappop, ordinary_heapify=heapq.heapify
    )
    assert not second_forced and second_pop[2] is ordinary
    assert service.services == 1 and service.spent


def test_harness_does_not_import_or_call_resource_planner_for_service():
    import one_shot_natural_r3_service_v0_1 as harness

    source = inspect.getsource(harness.OneShotR3Service)
    assert "resource" not in source.lower()
    assert "max_frontier_size" not in source
