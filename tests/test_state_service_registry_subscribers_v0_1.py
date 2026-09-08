"""Focused ownership-consolidation gates for registry subscribers v0.1."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

import spider.planner.anytime_controller as controller
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicCreditPropagation,
    StrategicSearchNode,
    _node_priority,
    _node_with_registry_subscriber_entitlements,
    _reserve_completion_subscriber,
    _reserve_epoch_transition_subscriber,
    _subscriber_node_priority,
    _trim_frontier_with_checkpoint_diversity,
    analyze_stage0_state,
)
from spider.planner.completion_cash_out import CompletionCashOutStatus
from spider.planner.residual_campaign import FoundationCheckpointPortfolio
from spider.planner.state_service_registry import (
    ServiceStatus,
    ServiceSubscriberKind,
    StateServiceRegistry,
)
from spider.planner.whole_deal_scheduler import EpochTransitionRepresentativeStatus
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


def _node(node_id: int, state: SpiderState, *, g: int = 3, credit: int = 0, **changes):
    node = StrategicSearchNode(
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
    return replace(node, **changes)


def _registry(*, ordinary: bool = True) -> StateServiceRegistry:
    return StateServiceRegistry(
        max_states=32,
        max_requests=160,
        enable_subscribers=ordinary,
    )


def _request(registry: StateServiceRegistry, node: StrategicSearchNode):
    key = canonical_state_key(node.state)
    registry.admit_arrival(key, node.g, node)
    return registry.request_service(
        key,
        int(node.credit_level),
        adapter_context=CONTEXT,
    )


def _subscribe(registry, request, *kinds):
    for kind in kinds:
        registry.subscribe(
            request.key,
            kind,
            priority_information=(kind.value,),
            quota_identity=f"quota:{kind.value}",
            reason="deterministic overlap fixture",
        )


def _execute(registry, request, handle=10):
    assert registry.activate(request.key, handle)
    assert registry.begin(handle).accepted
    registry.complete(request.key, outcome="SHARED_FIXTURE_EXECUTION")


def test_s1_ordinary_and_completion_share_one_request_handle_and_execution():
    registry = _registry()
    request = _request(registry, _node(1, _state()))
    assert registry.activate(request.key, 10)
    _subscribe(registry, request, ServiceSubscriberKind.COMPLETION_CASH_OUT)
    assert registry.request_count == 1 and request.live_handle_id == 10
    assert not registry.activate(request.key, 11)
    assert registry.begin(10).accepted
    registry.complete(request.key)
    assert request.executions == 1
    assert registry.metrics.shared_executions == 1


def test_s2_ordinary_and_epoch_share_one_request_handle_and_execution():
    registry = _registry()
    request = _request(registry, _node(1, _state()))
    assert registry.activate(request.key, 10)
    _subscribe(registry, request, ServiceSubscriberKind.EPOCH_TRANSITION)
    assert registry.request_count == 1 and request.live_handle_id == 10
    assert registry.begin(10).accepted
    registry.complete(request.key)
    assert request.executions == 1
    assert registry.metrics.shared_executions == 1


def test_s3_completion_and_epoch_observe_the_same_execution_result_reference():
    registry = _registry(ordinary=False)
    request = _request(registry, _node(1, _state()))
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    _execute(registry, request)
    completion = registry.subscriber(
        request.key, ServiceSubscriberKind.COMPLETION_CASH_OUT
    )
    epoch = registry.subscriber(request.key, ServiceSubscriberKind.EPOCH_TRANSITION)
    assert completion is not None and epoch is not None
    assert completion.last_execution_result is epoch.last_execution_result
    assert completion.last_execution_result is request.last_execution_result
    assert request.executions == 1


def test_s4_three_interests_still_use_one_live_handle_and_one_execution():
    registry = _registry()
    request = _request(registry, _node(1, _state()))
    assert registry.activate(request.key, 10)
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    assert len([item for item in request.subscribers.values() if item.active]) == 3
    assert registry.metrics.duplicate_live_representations_prevented == 0
    assert registry.metrics.special_interests_shared_with_existing_handle == 2
    assert registry.metrics.subscriber_live_representations_used == 1
    assert registry.begin(10).accepted
    registry.complete(request.key)
    assert request.executions == 1
    assert registry.metrics.subscriber_satisfactions == 3


@pytest.mark.parametrize(
    ("first", "remaining"),
    (
        (
            ServiceSubscriberKind.COMPLETION_CASH_OUT,
            ServiceSubscriberKind.EPOCH_TRANSITION,
        ),
        (
            ServiceSubscriberKind.EPOCH_TRANSITION,
            ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ),
    ),
)
def test_s5_one_special_subscriber_can_expire_without_destroying_the_other(
    first, remaining
):
    registry = _registry(ordinary=False)
    request = _request(registry, _node(1, _state()))
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    assert registry.activate(request.key, 10)
    assert registry.unsubscribe(request.key, first, reason="fixture expiry")
    assert request.status is ServiceStatus.LIVE
    assert registry.has_active_subscriber(request.key, remaining)
    assert registry.begin(10).accepted
    registry.complete(request.key)


def test_s6_cheaper_arrival_reopens_once_without_cloning_subscribers_or_handles():
    registry = _registry()
    old = _node(1, _state(), g=8)
    request = _request(registry, old)
    assert registry.activate(request.key, 10)
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    cheap = _node(2, old.state, g=6)
    registry.admit_arrival(request.key.state_key, 6, cheap)
    assert request.status is ServiceStatus.PENDING
    assert registry.metrics.reopening_events == 1
    assert len(request.subscribers) == 3
    assert registry.activate(request.key, 11)
    stale = registry.begin(10)
    assert not stale.accepted
    assert registry.metrics.stale_shared_handles_rejected == 1
    assert registry.begin(11).witness is cheap
    registry.complete(request.key)
    assert request.executions == 1


def test_s7_shared_eviction_preserves_subscribers_and_reactivates_once():
    registry = _registry()
    request = _request(registry, _node(1, _state()))
    assert registry.activate(request.key, 10)
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    assert registry.defer_handle(10)
    assert request.status is ServiceStatus.DEFERRED
    assert sum(item.active for item in request.subscribers.values()) == 3
    assert registry.activate(request.key, 11)
    assert not registry.activate(request.key, 12)
    assert registry.begin(11).accepted
    registry.complete(request.key)
    assert request.executions == 1
    assert registry.metrics.shared_request_deferrals == 1
    assert registry.metrics.shared_request_reactivations == 1


def test_duplicate_subscriber_attachment_coalesces_without_new_entitlement():
    registry = _registry()
    request = _request(registry, _node(1, _state()))
    first = registry.subscribe(
        request.key,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        quota_identity="completion:1",
    )
    second = registry.subscribe(
        request.key,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        quota_identity="completion:1",
    )
    assert first is second and len(request.subscribers) == 2
    assert registry.metrics.duplicate_subscriber_coalesces == 1


def test_last_subscriber_removal_defers_live_work_without_attempting_it():
    registry = _registry(ordinary=False)
    request = _request(registry, _node(1, _state()))
    _subscribe(registry, request, ServiceSubscriberKind.COMPLETION_CASH_OUT)
    assert registry.activate(request.key, 10)
    registry.unsubscribe(
        request.key,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        reason="last reason expired",
    )
    assert request.status is ServiceStatus.DEFERRED
    assert request.executions == 0
    assert registry.metrics.subscriber_orphan_deferrals == 1


@dataclass(frozen=True)
class _MetricsStub:
    def ordering_key(self):
        return (0,)


@dataclass(frozen=True)
class _CompletionStub:
    status: CompletionCashOutStatus = CompletionCashOutStatus.QUALIFIED
    cash_out_spent: bool = False
    metrics: _MetricsStub = _MetricsStub()
    corrected_g: int = 3
    exact_state_hash: str = "completion-state"
    opportunity_id: str = "completion-opportunity"
    reason: str = "fixture completion reservation"


@dataclass(frozen=True)
class _EpochStub:
    status: EpochTransitionRepresentativeStatus = (
        EpochTransitionRepresentativeStatus.QUALIFIED
    )
    opportunity_id: str = "epoch-opportunity"

    def ordering_key(self):
        return (0, self.opportunity_id)


def test_subscriber_projection_preserves_existing_combined_priority_exactly():
    registry = _registry()
    neutral = _node(
        10,
        _state(),
        completion_cash_out=_CompletionStub(),
        epoch_transition_opportunity=_EpochStub(),
    )
    request = _request(registry, neutral)
    assert registry.activate(request.key, neutral.node_id)
    _subscribe(
        registry,
        request,
        ServiceSubscriberKind.COMPLETION_CASH_OUT,
        ServiceSubscriberKind.EPOCH_TRANSITION,
    )
    legacy_reserved = replace(
        neutral,
        completion_cash_out=replace(
            neutral.completion_cash_out, status=CompletionCashOutStatus.RESERVED
        ),
        epoch_transition_opportunity=replace(
            neutral.epoch_transition_opportunity,
            status=EpochTransitionRepresentativeStatus.RESERVED,
        ),
    )
    projected = _node_with_registry_subscriber_entitlements(neutral, registry)
    assert projected == legacy_reserved
    assert _subscriber_node_priority(neutral, registry) == _node_priority(legacy_reserved)


def test_subscriber_entitlement_preserves_trim_protection_without_node_ownership():
    registry = _registry()
    ordinary = _node(1, _state(1), g=1)
    protected = _node(
        2,
        _state(2),
        g=30,
        completion_cash_out=_CompletionStub(),
    )
    ordinary_request = _request(registry, ordinary)
    protected_request = _request(registry, protected)
    assert registry.activate(ordinary_request.key, 1)
    assert registry.activate(protected_request.key, 2)
    _subscribe(registry, protected_request, ServiceSubscriberKind.COMPLETION_CASH_OUT)
    frontier = (
        (_subscriber_node_priority(ordinary, registry), 1, ordinary),
        (_subscriber_node_priority(protected, registry), 2, protected),
    )
    kept = _trim_frontier_with_checkpoint_diversity(
        frontier,
        maximum=1,
        portfolio=FoundationCheckpointPortfolio((), (), 0, 0, 1),
        telemetry=ControllerTelemetry(),
        registry=registry,
    )
    assert [item[1] for item in kept] == [2]
    assert kept[0][2].completion_cash_out.status is CompletionCashOutStatus.QUALIFIED


def test_completion_and_epoch_selection_each_keep_the_existing_quota_of_one(monkeypatch):
    registry = _registry()
    a = _node(1, _state(1), completion_cash_out=_CompletionStub())
    b = _node(2, _state(2), completion_cash_out=_CompletionStub())
    ra, rb = _request(registry, a), _request(registry, b)
    assert registry.activate(ra.key, 1) and registry.activate(rb.key, 2)

    def choose_completion(frontier, **_kwargs):
        return [
            (
                item[0],
                item[1],
                replace(
                    item[2],
                    completion_cash_out=replace(
                        item[2].completion_cash_out,
                        status=(
                            CompletionCashOutStatus.RESERVED
                            if item[1] == 1
                            else CompletionCashOutStatus.QUALIFIED
                        ),
                    ),
                ),
            )
            for item in frontier
        ]

    monkeypatch.setattr(controller, "_reserve_completion_representative", choose_completion)
    frontier = ((_node_priority(a), 1, a), (_node_priority(b), 2, b))
    _reserve_completion_subscriber(
        frontier,
        tt=object(),
        spent_event_ids=(),
        telemetry=ControllerTelemetry(),
        registry=registry,
    )
    assert registry.subscriber_snapshot()["subscriber_quota_usage"]["COMPLETION_CASH_OUT"] == 1

    ea = replace(a, completion_cash_out=None, epoch_transition_opportunity=_EpochStub())
    eb = replace(b, completion_cash_out=None, epoch_transition_opportunity=_EpochStub())

    def choose_epoch(frontier, **_kwargs):
        return [
            (
                item[0],
                item[1],
                replace(
                    item[2],
                    epoch_transition_opportunity=replace(
                        item[2].epoch_transition_opportunity,
                        status=(
                            EpochTransitionRepresentativeStatus.RESERVED
                            if item[1] == 2
                            else EpochTransitionRepresentativeStatus.QUALIFIED
                        ),
                    ),
                ),
            )
            for item in frontier
        ]

    monkeypatch.setattr(controller, "_reserve_epoch_transition_representative", choose_epoch)
    frontier = ((_node_priority(ea), 1, ea), (_node_priority(eb), 2, eb))
    _reserve_epoch_transition_subscriber(
        frontier,
        tt=object(),
        spent_opportunity_ids=(),
        telemetry=ControllerTelemetry(),
        registry=registry,
    )
    assert registry.subscriber_snapshot()["subscriber_quota_usage"]["EPOCH_TRANSITION"] == 1


def test_migration_switch_and_production_defaults_remain_explicit():
    defaults = AnytimeControllerConfig()
    assert not defaults.enable_state_service_registry
    assert not defaults.enable_state_service_subscribers
    assert defaults.frontier_priority_schema is FrontierPrioritySchema.LEGACY
    assert defaults.strategic_credit_propagation is StrategicCreditPropagation.INHERITED
    with pytest.raises(ValueError, match="require StateServiceRegistry"):
        replace(defaults, enable_state_service_subscribers=True)
