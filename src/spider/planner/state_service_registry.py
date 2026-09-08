"""Bounded exact-state arrival and strategic-service lifecycle registry.

The transposition table answers whether an exact Spider state has a better
legal arrival.  This registry answers a different question: whether one
explicit bounded coverage request has a live handle or has actually run from
the best known arrival version.

The registry deliberately accepts opaque state keys and witnesses.  Canonical
Spider identity and controller node construction remain owned by the caller.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Hashable, Mapping, Optional, Tuple


class RegistryCapacityError(RuntimeError):
    """Raised rather than silently losing authoritative lifecycle state."""


class ArrivalDisposition(str, Enum):
    NEW = "NEW"
    IMPROVED = "IMPROVED"
    SUPPRESSED = "SUPPRESSED"


class ServiceStatus(str, Enum):
    PENDING = "PENDING"
    LIVE = "LIVE"
    RUNNING = "RUNNING"
    ATTEMPTED = "ATTEMPTED"
    DEFERRED = "DEFERRED"
    PROOF_PRUNED = "PROOF_PRUNED"


class ServiceCoverageMode(str, Enum):
    CURRENT_STRATEGIC_SUCCESSORS = "CURRENT_STRATEGIC_SUCCESSORS"


class ServiceSubscriberKind(str, Enum):
    ORDINARY = "ORDINARY"
    COMPLETION_CASH_OUT = "COMPLETION_CASH_OUT"
    EPOCH_TRANSITION = "EPOCH_TRANSITION"


@dataclass(frozen=True)
class ServiceRequestKey:
    state_key: Hashable
    strategic_credit: int
    coverage_mode: ServiceCoverageMode
    adapter_context: Tuple[Hashable, ...] = ()


@dataclass
class ArrivalRecord:
    state_key: Hashable
    best_cost: int
    witness: object
    version: int = 1
    request_keys: set[ServiceRequestKey] = field(default_factory=set)


@dataclass(frozen=True)
class ServiceExecutionResult:
    request_key: ServiceRequestKey
    arrival_version: int
    execution_ordinal: int
    outcome: str


@dataclass
class ServiceSubscriberRecord:
    kind: ServiceSubscriberKind
    active: bool = True
    priority_information: Tuple[Hashable, ...] = ()
    quota_identity: Optional[str] = None
    creation_reason: str = ""
    removal_reason: Optional[str] = None
    attachment_count: int = 1
    satisfaction_count: int = 0
    last_execution_result: Optional[ServiceExecutionResult] = None


@dataclass
class ServiceRequestRecord:
    key: ServiceRequestKey
    status: ServiceStatus = ServiceStatus.PENDING
    live_handle_id: Optional[int] = None
    live_arrival_version: Optional[int] = None
    serviced_arrival_version: Optional[int] = None
    submissions: int = 1
    executions: int = 0
    last_outcome: Optional[str] = None
    last_defer_reason: Optional[str] = None
    subscribers: Dict[ServiceSubscriberKind, ServiceSubscriberRecord] = field(
        default_factory=dict
    )
    observed_subscriber_combinations: set[str] = field(default_factory=set)
    last_execution_result: Optional[ServiceExecutionResult] = None


@dataclass(frozen=True)
class ServiceHandle:
    handle_id: int
    request_key: ServiceRequestKey
    arrival_version: int


@dataclass(frozen=True)
class ServiceStart:
    accepted: bool
    request_key: Optional[ServiceRequestKey]
    witness: Optional[object]
    reason: str


@dataclass
class RegistryMetrics:
    cheaper_arrival_updates: int = 0
    reopening_events: int = 0
    eviction_deferrals: int = 0
    reactivations: int = 0
    duplicate_request_coalesces: int = 0
    stale_handles_rejected_before_analysis: int = 0
    live_handle_invariant_violations: int = 0
    service_executions: int = 0
    subscriber_add_events: int = 0
    subscriber_remove_events: int = 0
    duplicate_subscriber_coalesces: int = 0
    duplicate_live_representations_prevented: int = 0
    special_interests_shared_with_existing_handle: int = 0
    subscriber_live_representations_used: int = 0
    shared_executions: int = 0
    executions_satisfying_multiple_subscribers: int = 0
    subscriber_satisfactions: int = 0
    stale_shared_handles_rejected: int = 0
    shared_request_deferrals: int = 0
    shared_request_reactivations: int = 0
    subscriber_orphan_deferrals: int = 0
    subscriber_attachments_by_kind: Dict[str, int] = field(default_factory=dict)
    peak_subscriber_quota_usage: Dict[str, int] = field(default_factory=dict)


class StateServiceRegistry:
    """Bounded registry separating exact-state dominance from work coverage."""

    def __init__(
        self,
        *,
        max_states: int,
        max_requests: int,
        enable_subscribers: bool = False,
    ) -> None:
        if max_states <= 0 or max_requests <= 0:
            raise ValueError("registry capacities must be positive")
        self.max_states = max_states
        self.max_requests = max_requests
        self.enable_subscribers = enable_subscribers
        self._arrivals: Dict[Hashable, ArrivalRecord] = {}
        self._requests: Dict[ServiceRequestKey, ServiceRequestRecord] = {}
        self._handles: Dict[int, ServiceHandle] = {}
        self.metrics = RegistryMetrics()

    def __len__(self) -> int:
        return len(self._arrivals)

    @property
    def state_count(self) -> int:
        return len(self._arrivals)

    @property
    def request_count(self) -> int:
        return len(self._requests)

    def arrival(self, state_key: Hashable) -> Optional[ArrivalRecord]:
        return self._arrivals.get(state_key)

    def request(self, key: ServiceRequestKey) -> Optional[ServiceRequestRecord]:
        return self._requests.get(key)

    def request_key_for_handle(self, handle_id: int) -> Optional[ServiceRequestKey]:
        handle = self._handles.get(handle_id)
        return handle.request_key if handle is not None else None

    @staticmethod
    def _active_subscribers(
        request: ServiceRequestRecord,
    ) -> Tuple[ServiceSubscriberRecord, ...]:
        return tuple(item for item in request.subscribers.values() if item.active)

    @staticmethod
    def _combination_name(request: ServiceRequestRecord) -> str:
        active = {item.kind for item in request.subscribers.values() if item.active}
        ordered = (
            ServiceSubscriberKind.ORDINARY,
            ServiceSubscriberKind.COMPLETION_CASH_OUT,
            ServiceSubscriberKind.EPOCH_TRANSITION,
        )
        return "+".join(item.value for item in ordered if item in active) or "NONE"

    def _record_combination(self, request: ServiceRequestRecord) -> None:
        request.observed_subscriber_combinations.add(self._combination_name(request))

    def _current_quota_usage(self, kind: ServiceSubscriberKind) -> int:
        return sum(
            subscriber.active
            for request in self._requests.values()
            for subscriber_kind, subscriber in request.subscribers.items()
            if subscriber_kind is kind
        )

    def subscribe(
        self,
        key: ServiceRequestKey,
        kind: ServiceSubscriberKind,
        *,
        priority_information: Tuple[Hashable, ...] = (),
        quota_identity: Optional[str] = None,
        reason: str = "",
    ) -> ServiceSubscriberRecord:
        """Attach one named policy interest without creating execution work."""

        request = self._requests[key]
        existing = request.subscribers.get(kind)
        was_active = existing is not None and existing.active
        active_before = self._active_subscribers(request)
        special_before = any(
            item.kind is not ServiceSubscriberKind.ORDINARY for item in active_before
        )
        if existing is None:
            existing = ServiceSubscriberRecord(
                kind=kind,
                priority_information=tuple(priority_information),
                quota_identity=quota_identity,
                creation_reason=reason,
            )
            request.subscribers[kind] = existing
        elif existing.active:
            existing.attachment_count += 1
            existing.priority_information = tuple(priority_information)
            existing.quota_identity = quota_identity
            existing.creation_reason = reason or existing.creation_reason
            self.metrics.duplicate_subscriber_coalesces += 1
        else:
            existing.active = True
            existing.attachment_count += 1
            existing.priority_information = tuple(priority_information)
            existing.quota_identity = quota_identity
            existing.creation_reason = reason or existing.creation_reason
            existing.removal_reason = None

        if not was_active:
            self.metrics.subscriber_add_events += 1
            name = kind.value
            self.metrics.subscriber_attachments_by_kind[name] = (
                self.metrics.subscriber_attachments_by_kind.get(name, 0) + 1
            )
            if (
                request.status is ServiceStatus.LIVE
                and active_before
                and kind is not ServiceSubscriberKind.ORDINARY
            ):
                self.metrics.special_interests_shared_with_existing_handle += 1
            if (
                request.status is ServiceStatus.LIVE
                and kind is not ServiceSubscriberKind.ORDINARY
                and not special_before
            ):
                self.metrics.subscriber_live_representations_used += 1
        self._record_combination(request)
        usage = self._current_quota_usage(kind)
        self.metrics.peak_subscriber_quota_usage[kind.value] = max(
            usage,
            self.metrics.peak_subscriber_quota_usage.get(kind.value, 0),
        )
        return existing

    def unsubscribe(
        self,
        key: ServiceRequestKey,
        kind: ServiceSubscriberKind,
        *,
        reason: str,
    ) -> bool:
        """Remove one entitlement without removing other interests or coverage."""

        request = self._requests[key]
        subscriber = request.subscribers.get(kind)
        if subscriber is None or not subscriber.active:
            return False
        subscriber.active = False
        subscriber.removal_reason = reason
        self.metrics.subscriber_remove_events += 1
        self._record_combination(request)
        if not self._active_subscribers(request) and request.status is ServiceStatus.LIVE:
            handle_id = request.live_handle_id
            if handle_id is not None:
                self._defer_handle(
                    handle_id,
                    reason="LAST_SUBSCRIBER_REMOVED",
                    count_eviction=False,
                )
                self.metrics.subscriber_orphan_deferrals += 1
        return True

    def subscriber(
        self,
        key: ServiceRequestKey,
        kind: ServiceSubscriberKind,
    ) -> Optional[ServiceSubscriberRecord]:
        return self._requests[key].subscribers.get(kind)

    def has_active_subscriber(
        self,
        key: ServiceRequestKey,
        kind: ServiceSubscriberKind,
    ) -> bool:
        subscriber = self.subscriber(key, kind)
        return subscriber is not None and subscriber.active

    def admit_arrival(
        self,
        state_key: Hashable,
        corrected_cost: int,
        witness: object,
    ) -> ArrivalDisposition:
        current = self._arrivals.get(state_key)
        if current is None:
            if len(self._arrivals) >= self.max_states:
                raise RegistryCapacityError("state-service registry state capacity exhausted")
            self._arrivals[state_key] = ArrivalRecord(
                state_key=state_key,
                best_cost=corrected_cost,
                witness=witness,
            )
            return ArrivalDisposition.NEW
        if corrected_cost >= current.best_cost:
            return ArrivalDisposition.SUPPRESSED

        current.best_cost = corrected_cost
        current.witness = witness
        current.version += 1
        self.metrics.cheaper_arrival_updates += 1
        for request_key in tuple(current.request_keys):
            request = self._requests[request_key]
            if request.status == ServiceStatus.LIVE:
                # Retain the old handle record so a queued obsolete node is
                # observably rejected if it is later popped.
                request.live_handle_id = None
                request.live_arrival_version = None
            request.status = ServiceStatus.PENDING
            request.last_defer_reason = "CHEAPER_ARRIVAL_REOPEN"
            self.metrics.reopening_events += 1
        return ArrivalDisposition.IMPROVED

    def request_service(
        self,
        state_key: Hashable,
        strategic_credit: int,
        *,
        coverage_mode: ServiceCoverageMode = (
            ServiceCoverageMode.CURRENT_STRATEGIC_SUCCESSORS
        ),
        adapter_context: Tuple[Hashable, ...] = (),
    ) -> ServiceRequestRecord:
        if state_key not in self._arrivals:
            raise KeyError("service requires an admitted exact-state arrival")
        key = ServiceRequestKey(
            state_key,
            int(strategic_credit),
            coverage_mode,
            tuple(adapter_context),
        )
        existing = self._requests.get(key)
        if existing is not None:
            existing.submissions += 1
            self.metrics.duplicate_request_coalesces += 1
            if self.enable_subscribers:
                self.subscribe(
                    key,
                    ServiceSubscriberKind.ORDINARY,
                    reason="current controller requested bounded coverage",
                )
            return existing
        if len(self._requests) >= self.max_requests:
            raise RegistryCapacityError("state-service registry request capacity exhausted")
        request = ServiceRequestRecord(key)
        self._requests[key] = request
        self._arrivals[state_key].request_keys.add(key)
        if self.enable_subscribers:
            self.subscribe(
                key,
                ServiceSubscriberKind.ORDINARY,
                reason="current controller requested bounded coverage",
            )
        return request

    def pending_requests(self, state_key: Hashable) -> Tuple[ServiceRequestRecord, ...]:
        arrival = self._arrivals[state_key]
        pending = (
            self._requests[key]
            for key in arrival.request_keys
            if self._requests[key].status in {
                ServiceStatus.PENDING,
                ServiceStatus.DEFERRED,
            }
        )
        return tuple(
            sorted(
                pending,
                key=lambda item: (
                    item.key.strategic_credit,
                    item.key.coverage_mode.value,
                    repr(item.key.adapter_context),
                ),
            )
        )

    def activate(self, key: ServiceRequestKey, handle_id: int) -> bool:
        request = self._requests[key]
        if request.status == ServiceStatus.LIVE:
            if request.live_handle_id != handle_id:
                self.metrics.live_handle_invariant_violations += 1
            return False
        if request.status not in {ServiceStatus.PENDING, ServiceStatus.DEFERRED}:
            return False
        if handle_id in self._handles:
            self.metrics.live_handle_invariant_violations += 1
            raise ValueError(f"service handle id {handle_id} is already registered")
        arrival = self._arrivals[key.state_key]
        if request.status == ServiceStatus.DEFERRED:
            self.metrics.reactivations += 1
            if len(self._active_subscribers(request)) > 1:
                self.metrics.shared_request_reactivations += 1
        request.status = ServiceStatus.LIVE
        request.live_handle_id = handle_id
        request.live_arrival_version = arrival.version
        self._handles[handle_id] = ServiceHandle(handle_id, key, arrival.version)
        return True

    def begin(self, handle_id: int) -> ServiceStart:
        handle = self._handles.get(handle_id)
        if handle is None:
            self.metrics.stale_handles_rejected_before_analysis += 1
            return ServiceStart(False, None, None, "UNKNOWN_HANDLE")
        request = self._requests[handle.request_key]
        arrival = self._arrivals[handle.request_key.state_key]
        valid = (
            request.status == ServiceStatus.LIVE
            and request.live_handle_id == handle_id
            and request.live_arrival_version == handle.arrival_version
            and handle.arrival_version == arrival.version
        )
        if not valid:
            self.metrics.stale_handles_rejected_before_analysis += 1
            if len(self._active_subscribers(request)) > 1:
                self.metrics.stale_shared_handles_rejected += 1
            self._handles.pop(handle_id, None)
            return ServiceStart(False, handle.request_key, None, "STALE_HANDLE")
        request.status = ServiceStatus.RUNNING
        request.live_handle_id = None
        request.live_arrival_version = None
        self._handles.pop(handle_id, None)
        return ServiceStart(True, handle.request_key, arrival.witness, "RUNNING")

    def complete(self, key: ServiceRequestKey, *, outcome: str = "EXECUTED") -> None:
        request = self._requests[key]
        if request.status != ServiceStatus.RUNNING:
            raise ValueError("only RUNNING service can be marked ATTEMPTED")
        arrival = self._arrivals[key.state_key]
        request.status = ServiceStatus.ATTEMPTED
        request.serviced_arrival_version = arrival.version
        request.executions += 1
        request.last_outcome = outcome
        request.last_defer_reason = None
        result = ServiceExecutionResult(
            key,
            arrival.version,
            request.executions,
            outcome,
        )
        request.last_execution_result = result
        active_subscribers = self._active_subscribers(request)
        for subscriber in active_subscribers:
            subscriber.satisfaction_count += 1
            subscriber.last_execution_result = result
            if subscriber.kind is not ServiceSubscriberKind.ORDINARY:
                subscriber.active = False
                subscriber.removal_reason = "SERVICE_SATISFIED"
                self.metrics.subscriber_remove_events += 1
        self.metrics.subscriber_satisfactions += len(active_subscribers)
        if len(active_subscribers) > 1:
            self.metrics.shared_executions += 1
            self.metrics.executions_satisfying_multiple_subscribers += 1
        self._record_combination(request)
        self.metrics.service_executions += 1

    def proof_prune(self, key: ServiceRequestKey) -> None:
        request = self._requests[key]
        if request.status != ServiceStatus.RUNNING:
            raise ValueError("only RUNNING service can be proof-pruned")
        request.status = ServiceStatus.PROOF_PRUNED
        request.last_outcome = "ADMISSIBLE_PROOF_PRUNE"

    def _defer_handle(
        self,
        handle_id: int,
        *,
        reason: str,
        count_eviction: bool,
    ) -> bool:
        handle = self._handles.get(handle_id)
        if handle is None:
            return False
        request = self._requests[handle.request_key]
        if request.status != ServiceStatus.LIVE or request.live_handle_id != handle_id:
            return False
        request.status = ServiceStatus.DEFERRED
        request.live_handle_id = None
        request.live_arrival_version = None
        request.last_defer_reason = reason
        self._handles.pop(handle_id, None)
        if count_eviction:
            self.metrics.eviction_deferrals += 1
        if len(self._active_subscribers(request)) > 1:
            self.metrics.shared_request_deferrals += 1
        return True

    def defer_handle(self, handle_id: int, *, reason: str = "FRONTIER_EVICTION") -> bool:
        return self._defer_handle(handle_id, reason=reason, count_eviction=True)

    def defer_running(self, key: ServiceRequestKey, *, reason: str) -> None:
        request = self._requests[key]
        if request.status != ServiceStatus.RUNNING:
            raise ValueError("only RUNNING service can be deferred")
        request.status = ServiceStatus.DEFERRED
        request.last_defer_reason = reason

    def status_counts(self) -> Mapping[str, int]:
        counts = {status.value: 0 for status in ServiceStatus}
        for request in self._requests.values():
            counts[request.status.value] += 1
        return counts

    def subscriber_snapshot(self) -> dict:
        active_by_kind = {kind.value: 0 for kind in ServiceSubscriberKind}
        records_by_kind = {kind.value: 0 for kind in ServiceSubscriberKind}
        combination_counts = {
            "ORDINARY": 0,
            "COMPLETION_CASH_OUT": 0,
            "EPOCH_TRANSITION": 0,
            "ORDINARY+COMPLETION_CASH_OUT": 0,
            "ORDINARY+EPOCH_TRANSITION": 0,
            "COMPLETION_CASH_OUT+EPOCH_TRANSITION": 0,
            "ORDINARY+COMPLETION_CASH_OUT+EPOCH_TRANSITION": 0,
        }
        for request in self._requests.values():
            for kind, subscriber in request.subscribers.items():
                records_by_kind[kind.value] += 1
                active_by_kind[kind.value] += int(subscriber.active)
            for combination in request.observed_subscriber_combinations:
                if combination in combination_counts:
                    combination_counts[combination] += 1
        return {
            "subscriber_records": sum(records_by_kind.values()),
            "subscriber_records_by_kind": records_by_kind,
            "active_subscribers": sum(active_by_kind.values()),
            "active_subscribers_by_kind": active_by_kind,
            "subscriber_attachments": self.metrics.subscriber_add_events,
            "subscriber_attachments_by_kind": dict(
                self.metrics.subscriber_attachments_by_kind
            ),
            "request_combinations_observed": combination_counts,
            "duplicate_subscriber_coalesces": (
                self.metrics.duplicate_subscriber_coalesces
            ),
            "duplicate_live_representations_prevented": (
                self.metrics.duplicate_live_representations_prevented
            ),
            "special_interests_shared_with_existing_handle": (
                self.metrics.special_interests_shared_with_existing_handle
            ),
            "subscriber_live_representations_used": (
                self.metrics.subscriber_live_representations_used
            ),
            "subscriber_add_events": self.metrics.subscriber_add_events,
            "subscriber_remove_events": self.metrics.subscriber_remove_events,
            "subscriber_quota_usage": {
                kind.value: self._current_quota_usage(kind)
                for kind in ServiceSubscriberKind
                if kind is not ServiceSubscriberKind.ORDINARY
            },
            "peak_subscriber_quota_usage": dict(
                self.metrics.peak_subscriber_quota_usage
            ),
            "shared_executions": self.metrics.shared_executions,
            "executions_satisfying_multiple_subscribers": (
                self.metrics.executions_satisfying_multiple_subscribers
            ),
            "subscriber_satisfactions": self.metrics.subscriber_satisfactions,
            "stale_shared_handles_rejected": (
                self.metrics.stale_shared_handles_rejected
            ),
            "shared_request_deferrals": self.metrics.shared_request_deferrals,
            "shared_request_reactivations": self.metrics.shared_request_reactivations,
            "subscriber_orphan_deferrals": self.metrics.subscriber_orphan_deferrals,
        }

    def approximate_bytes(self) -> int:
        """Return a deterministic shallow footprint suitable for A/B telemetry."""

        total = sys.getsizeof(self)
        for mapping in (self._arrivals, self._requests, self._handles):
            total += sys.getsizeof(mapping)
            total += sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in mapping.items())
        total += sum(sys.getsizeof(record.request_keys) for record in self._arrivals.values())
        for request in self._requests.values():
            total += sys.getsizeof(request.subscribers)
            total += sum(
                sys.getsizeof(key) + sys.getsizeof(value)
                for key, value in request.subscribers.items()
            )
            total += sys.getsizeof(request.observed_subscriber_combinations)
        return total

    def snapshot(self) -> dict:
        snapshot = {
            "states": self.state_count,
            "service_requests": self.request_count,
            "status_counts": dict(self.status_counts()),
            "cheaper_arrival_updates": self.metrics.cheaper_arrival_updates,
            "reopening_events": self.metrics.reopening_events,
            "eviction_deferrals": self.metrics.eviction_deferrals,
            "reactivations": self.metrics.reactivations,
            "duplicate_request_coalesces": self.metrics.duplicate_request_coalesces,
            "stale_handles_rejected_before_analysis": (
                self.metrics.stale_handles_rejected_before_analysis
            ),
            "live_handle_invariant_violations": (
                self.metrics.live_handle_invariant_violations
            ),
            "service_executions": self.metrics.service_executions,
            "approximate_bytes": self.approximate_bytes(),
        }
        snapshot.update(self.subscriber_snapshot())
        return snapshot
