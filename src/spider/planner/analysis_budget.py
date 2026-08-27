"""Cooperative wall-clock and component accounting for strategic analysis.

The object in this module does not terminate work unsafely.  Callers check it
before expensive operations and pass its remaining time into bounded helpers.
Component timings are diagnostic only and never participate in proof pruning.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterator, Mapping, Optional


class ComputationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    CANCELLED = "CANCELLED"


class AnalysisResourceLimit(RuntimeError):
    """Typed signal that optional analysis could not start within its budget."""


@dataclass
class ComponentTiming:
    calls: int = 0
    cumulative_seconds: float = 0.0
    maximum_seconds: float = 0.0
    skipped_due_deadline: int = 0
    aborted_or_incomplete: int = 0

    def record(self, elapsed: float, *, incomplete: bool = False) -> None:
        self.calls += 1
        self.cumulative_seconds += elapsed
        self.maximum_seconds = max(self.maximum_seconds, elapsed)
        if incomplete:
            self.aborted_or_incomplete += 1


@dataclass
class SearchDeadline:
    """One monotonic deadline shared by controller and bounded sub-analyses."""

    absolute_deadline: float
    started_at: float = field(default_factory=time.perf_counter)
    analysis_node_limit: Optional[int] = None
    component_max_seconds: Mapping[str, float] = field(default_factory=dict)
    cancellation_requested: bool = False
    analysis_nodes_used: int = 0
    timings: Dict[str, ComponentTiming] = field(default_factory=dict)

    @classmethod
    def from_seconds(
        cls,
        seconds: float,
        *,
        analysis_node_limit: Optional[int] = None,
        component_max_seconds: Optional[Mapping[str, float]] = None,
    ) -> "SearchDeadline":
        if seconds <= 0:
            raise ValueError("deadline duration must be positive")
        now = time.perf_counter()
        return cls(
            absolute_deadline=now + seconds,
            started_at=now,
            analysis_node_limit=analysis_node_limit,
            component_max_seconds=dict(component_max_seconds or {}),
        )

    @property
    def remaining_wall_time(self) -> float:
        return max(0.0, self.absolute_deadline - time.perf_counter())

    @property
    def remaining_analysis_nodes(self) -> Optional[int]:
        if self.analysis_node_limit is None:
            return None
        return max(0, self.analysis_node_limit - self.analysis_nodes_used)

    @property
    def status(self) -> ComputationStatus:
        if self.cancellation_requested:
            return ComputationStatus.CANCELLED
        if self.remaining_wall_time <= 0:
            return ComputationStatus.RESOURCE_LIMIT
        if self.remaining_analysis_nodes == 0:
            return ComputationStatus.RESOURCE_LIMIT
        return ComputationStatus.ACTIVE

    def request_cancel(self) -> None:
        self.cancellation_requested = True

    def checkpoint(self) -> bool:
        return self.status == ComputationStatus.ACTIVE

    def can_start(
        self,
        component: str,
        *,
        minimum_seconds: float = 0.0,
        minimum_nodes: int = 0,
    ) -> bool:
        nodes = self.remaining_analysis_nodes
        allowed = bool(
            self.status == ComputationStatus.ACTIVE
            and self.remaining_wall_time >= minimum_seconds
            and (nodes is None or nodes >= minimum_nodes)
        )
        if not allowed:
            self.timings.setdefault(component, ComponentTiming()).skipped_due_deadline += 1
        return allowed

    def time_slice(
        self,
        component: str,
        requested_seconds: float,
        *,
        reserve_seconds: float = 0.02,
    ) -> float:
        cap = self.component_max_seconds.get(component, requested_seconds)
        return max(
            0.0,
            min(requested_seconds, cap, self.remaining_wall_time - reserve_seconds),
        )

    def node_slice(self, requested_nodes: int) -> int:
        remaining = self.remaining_analysis_nodes
        return requested_nodes if remaining is None else min(requested_nodes, remaining)

    def consume_nodes(self, nodes: int) -> None:
        if nodes < 0:
            raise ValueError("consumed node count cannot be negative")
        self.analysis_nodes_used += nodes

    @contextmanager
    def measure(self, component: str) -> Iterator[None]:
        started = time.perf_counter()
        incomplete = False
        try:
            yield
        except AnalysisResourceLimit:
            incomplete = True
            raise
        finally:
            elapsed = time.perf_counter() - started
            self.timings.setdefault(component, ComponentTiming()).record(
                elapsed, incomplete=incomplete
            )

    def timing_snapshot(self) -> Dict[str, ComponentTiming]:
        return {
            name: ComponentTiming(
                calls=value.calls,
                cumulative_seconds=value.cumulative_seconds,
                maximum_seconds=value.maximum_seconds,
                skipped_due_deadline=value.skipped_due_deadline,
                aborted_or_incomplete=value.aborted_or_incomplete,
            )
            for name, value in self.timings.items()
        }
