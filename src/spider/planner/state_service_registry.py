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


class StateServiceRegistry:
    """Bounded registry separating exact-state dominance from work coverage."""

    def __init__(self, *, max_states: int, max_requests: int) -> None:
        if max_states <= 0 or max_requests <= 0:
            raise ValueError("registry capacities must be positive")
        self.max_states = max_states
        self.max_requests = max_requests
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
            return existing
        if len(self._requests) >= self.max_requests:
            raise RegistryCapacityError("state-service registry request capacity exhausted")
        request = ServiceRequestRecord(key)
        self._requests[key] = request
        self._arrivals[state_key].request_keys.add(key)
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
        self.metrics.service_executions += 1

    def proof_prune(self, key: ServiceRequestKey) -> None:
        request = self._requests[key]
        if request.status != ServiceStatus.RUNNING:
            raise ValueError("only RUNNING service can be proof-pruned")
        request.status = ServiceStatus.PROOF_PRUNED
        request.last_outcome = "ADMISSIBLE_PROOF_PRUNE"

    def defer_handle(self, handle_id: int, *, reason: str = "FRONTIER_EVICTION") -> bool:
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
        self.metrics.eviction_deferrals += 1
        return True

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

    def approximate_bytes(self) -> int:
        """Return a deterministic shallow footprint suitable for A/B telemetry."""

        total = sys.getsizeof(self)
        for mapping in (self._arrivals, self._requests, self._handles):
            total += sys.getsizeof(mapping)
            total += sum(sys.getsizeof(key) + sys.getsizeof(value) for key, value in mapping.items())
        total += sum(sys.getsizeof(record.request_keys) for record in self._arrivals.values())
        return total

    def snapshot(self) -> dict:
        return {
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
