"""Focused lifecycle and controller-migration gates for StateServiceRegistry v0.1."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicCreditPropagation,
    StrategicSearchNode,
    StrategicTranspositionTable,
    _apply_ordinary_child_credit_semantics,
    analyze_stage0_state,
    solve_anytime,
)
from spider.planner.state_service_registry import (
    ArrivalDisposition,
    ServiceCoverageMode,
    ServiceStatus,
    StateServiceRegistry,
)
from spider.state_identity import canonical_state_key


CONTEXT = ("BEST_ARRIVAL_STRATEGIC_NODE_V0_1",)


def _state(marker: int = 0) -> SpiderState:
    return SpiderState(
        [
            Column([], [Card("shcd"[(index + marker) % 4], 13 - index % 5)])
            for index in range(10)
        ],
        [],
    )


def _node(node_id: int, *, g: int, state: SpiderState, credit: int = 0):
    return StrategicSearchNode(
        node_id,
        state,
        g,
        (),
        None,
        None,
        0,
        StrategicCreditLevel(credit),
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
    )


def _registry() -> StateServiceRegistry:
    return StateServiceRegistry(max_states=32, max_requests=160)


def _request(registry, key, credit=0):
    return registry.request_service(
        key,
        credit,
        coverage_mode=ServiceCoverageMode.CURRENT_STRATEGIC_SUCCESSORS,
        adapter_context=CONTEXT,
    )


def test_new_state_installs_one_best_arrival_and_one_live_clean_request():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    witness = _node(1, g=7, state=state)
    assert registry.admit_arrival(key, 7, witness) is ArrivalDisposition.NEW
    request = _request(registry, key)
    assert request.status is ServiceStatus.PENDING
    assert registry.activate(request.key, 10)
    assert request.status is ServiceStatus.LIVE
    assert registry.state_count == 1 and registry.request_count == 1


def test_equal_or_worse_decorated_arrival_preserves_best_witness_and_cost():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    best = _node(1, g=5, state=state)
    decorated = replace(_node(2, g=8, state=state), actions=((0, 1, 1),))
    registry.admit_arrival(key, 5, best)
    assert registry.admit_arrival(key, 5, decorated) is ArrivalDisposition.SUPPRESSED
    assert registry.admit_arrival(key, 8, decorated) is ArrivalDisposition.SUPPRESSED
    arrival = registry.arrival(key)
    assert arrival is not None
    assert arrival.best_cost == 5 and arrival.witness is best and arrival.version == 1


def test_d1_cheaper_tt_arrival_reopens_attempted_coverage_at_new_version():
    registry = _registry()
    tt = StrategicTranspositionTable()
    state = _state()
    key = canonical_state_key(state)
    old = _node(1, g=9, state=state)
    cheap = _node(2, g=7, state=state)
    assert tt.admit(state, 9)
    registry.admit_arrival(key, 9, old)
    request = _request(registry, key)
    registry.activate(request.key, 10)
    start = registry.begin(10)
    assert start.accepted
    registry.complete(request.key)
    legacy_expansion_history = {(key, 0)}

    assert tt.admit(state, 7)
    assert (key, 0) in legacy_expansion_history  # the old bookkeeping defect
    assert registry.admit_arrival(key, 7, cheap) is ArrivalDisposition.IMPROVED
    assert request.status is ServiceStatus.PENDING
    assert registry.arrival(key).version == 2
    assert registry.activate(request.key, 11)
    reopened = registry.begin(11)
    assert reopened.accepted and reopened.witness is cheap
    registry.complete(request.key)
    assert request.executions == 2 and request.serviced_arrival_version == 2
    assert registry.metrics.reopening_events == 1


def test_d2_evicted_unserved_work_defers_reactivates_and_executes_once():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    witness = _node(1, g=4, state=state)
    registry.admit_arrival(key, 4, witness)
    request = _request(registry, key)
    registry.activate(request.key, 10)
    assert registry.defer_handle(10)
    assert request.status is ServiceStatus.DEFERRED
    assert request.executions == 0 and registry.arrival(key).witness is witness
    assert registry.activate(request.key, 11)
    assert registry.begin(11).accepted
    registry.complete(request.key)
    assert request.status is ServiceStatus.ATTEMPTED and request.executions == 1
    assert not registry.activate(request.key, 12)


def test_d3_duplicate_submissions_share_one_record_handle_and_execution():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 3, _node(1, g=3, state=state))
    first = _request(registry, key)
    second = _request(registry, key)
    assert first is second and registry.request_count == 1
    assert registry.activate(first.key, 10)
    assert not registry.activate(second.key, 11)
    assert registry.metrics.live_handle_invariant_violations == 1
    assert registry.begin(10).accepted
    registry.complete(first.key)
    third = _request(registry, key)
    assert third is first and not registry.activate(third.key, 12)
    assert first.executions == 1


def test_d4_credit_widening_is_distinct_once_and_children_remain_clean():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    broad_parent = _node(1, g=3, state=state, credit=3)
    registry.admit_arrival(key, 3, broad_parent)
    clean = _request(registry, key, 0)
    broad = _request(registry, key, 3)
    assert clean.key != broad.key and registry.request_count == 2
    for handle, request in ((10, clean), (11, broad)):
        assert registry.activate(request.key, handle)
        assert registry.begin(handle).accepted
        registry.complete(request.key)
        assert not registry.activate(request.key, handle + 10)
    ordinary_child = _node(20, g=4, state=_state(1), credit=3)
    reset = _apply_ordinary_child_credit_semantics(
        ordinary_child,
        parent_credit=StrategicCreditLevel.ESCAPE,
        propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    assert reset.credit_level is StrategicCreditLevel.CLEAN


def test_newer_arrival_makes_old_live_handle_stale_before_expensive_analysis():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 8, _node(1, g=8, state=state))
    request = _request(registry, key)
    registry.activate(request.key, 10)
    registry.admit_arrival(key, 6, _node(2, g=6, state=state))
    expensive_analysis_calls = 0
    start = registry.begin(10)
    if start.accepted:
        expensive_analysis_calls += 1
    assert not start.accepted and expensive_analysis_calls == 0
    assert registry.metrics.stale_handles_rejected_before_analysis == 1


def test_attempted_requires_running_and_eviction_never_marks_attempted():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 2, _node(1, g=2, state=state))
    request = _request(registry, key)
    try:
        registry.complete(request.key)
    except ValueError as error:
        assert "RUNNING" in str(error)
    else:
        raise AssertionError("PENDING work must not become ATTEMPTED")
    registry.activate(request.key, 10)
    registry.defer_handle(10)
    assert request.status is ServiceStatus.DEFERRED
    assert request.serviced_arrival_version is None


def test_proof_pruning_is_explicit_and_not_misreported_as_execution():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 2, _node(1, g=2, state=state))
    request = _request(registry, key)
    registry.activate(request.key, 10)
    registry.begin(10)
    registry.proof_prune(request.key)
    assert request.status is ServiceStatus.PROOF_PRUNED
    assert request.executions == 0 and registry.metrics.service_executions == 0


def test_status_snapshot_and_memory_telemetry_are_bounded_and_deterministic():
    registry = _registry()
    state = _state()
    key = canonical_state_key(state)
    registry.admit_arrival(key, 1, _node(1, g=1, state=state))
    request = _request(registry, key)
    snapshot = registry.snapshot()
    assert snapshot["states"] == 1 and snapshot["service_requests"] == 1
    assert snapshot["status_counts"]["PENDING"] == 1
    assert snapshot["approximate_bytes"] > 0
    assert request.submissions == 1


def test_registry_controller_switch_rejects_unsupported_legacy_modes():
    cards = tuple(load_deal(Path("deals/4925153.txt")))
    opening = SpiderState.from_cards(list(cards))
    try:
        solve_anytime(
            opening,
            cards,
            config=replace(
                AnytimeControllerConfig(),
                enable_state_service_registry=True,
                wall_clock_limit_s=1,
                max_strategic_expansions=1,
                max_tactical_nodes=1,
            ),
        )
    except ValueError as error:
        assert "COMMON_STAGE0 + STATE_LOCAL" in str(error)
    else:
        raise AssertionError("v0.1 registry must reject unsupported legacy semantics")


def test_registry_controller_smoke_runs_before_analysis_and_publishes_metrics():
    cards = tuple(load_deal(Path("deals/4925153.txt")))
    opening = SpiderState.from_cards(list(cards))
    config = replace(
        AnytimeControllerConfig(),
        enable_state_service_registry=True,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
        wall_clock_limit_s=30,
        max_strategic_expansions=1,
        max_tactical_nodes=30_000,
        enable_expensive_deal_timing=False,
    )
    result = solve_anytime(opening, cards, config=config)
    telemetry = result.telemetry
    assert result.strategic_expansions == 1
    assert telemetry.registry_enabled
    assert telemetry.registry_states >= 1
    assert telemetry.registry_service_requests >= 1
    assert telemetry.registry_service_executions == 1
    assert telemetry.registry_live_handle_invariant_violations == 0


def test_production_defaults_and_exact_state_identity_remain_unchanged():
    config = AnytimeControllerConfig()
    assert config.enable_state_service_registry is False
    assert config.frontier_priority_schema is FrontierPrioritySchema.LEGACY
    assert config.strategic_credit_propagation is StrategicCreditPropagation.INHERITED
    state = _state()
    decorated = replace(_node(1, g=9, state=state), actions=((0, 1, 1),))
    assert canonical_state_key(state) == canonical_state_key(decorated.state)
