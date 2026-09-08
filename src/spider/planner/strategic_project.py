"""Persistent strategic-purpose lifecycle over registry-owned service requests.

Projects have no proof authority and contain no game states or search nodes.
The v0.1 registry intentionally supports only the historic bounded
same-campaign continuation contract.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Hashable, Iterable, Optional, Sequence, Tuple

from spider.planner.state_service_registry import (
    ServiceExecutionResult,
    ServiceRequestKey,
    ServiceStatus,
    ServiceSubscriberKind,
    StateServiceRegistry,
)
from spider.planner.structural_investment import (
    SameCampaignContinuationCredit,
    SameCampaignContinuationStatus,
    refresh_continuation_credit,
)


class StrategicProjectKind(str, Enum):
    SAME_CAMPAIGN_CONTINUATION = "SAME_CAMPAIGN_CONTINUATION"


class StrategicProjectStatus(str, Enum):
    RUNNABLE = "RUNNABLE"
    BLOCKED = "BLOCKED"
    ACHIEVED = "ACHIEVED"
    EXHAUSTED = "EXHAUSTED"
    INVALIDATED = "INVALIDATED"


@dataclass(frozen=True)
class StrategicTargetIdentity:
    """Semantic target; deliberately excludes state, node and path identity."""

    campaign_id: str

    def __post_init__(self) -> None:
        if not self.campaign_id:
            raise ValueError("same-campaign project requires a campaign identity")


@dataclass(frozen=True)
class ProjectBaseline:
    outstanding_dependencies: Tuple[str, ...]
    total_g: int
    depth: int
    elapsed_seconds: float


@dataclass(frozen=True)
class ProjectProgressEvidence:
    execution_ordinal: int
    request_key: ServiceRequestKey
    dependencies_closed: Tuple[str, ...]
    target_achieved: bool


@dataclass
class StrategicProjectCandidate:
    request_key: ServiceRequestKey
    continuation: SameCampaignContinuationCredit
    priority_information: Tuple[Hashable, ...]
    attached_expansion: int
    arrival_version: int
    service_executions: int = 0
    last_observed_dependencies: Tuple[str, ...] = ()
    last_execution_result: Optional[ServiceExecutionResult] = None


@dataclass
class StrategicProject:
    project_id: str
    kind: StrategicProjectKind
    target: StrategicTargetIdentity
    baseline: ProjectBaseline
    status: StrategicProjectStatus = StrategicProjectStatus.RUNNABLE
    candidates: Dict[ServiceRequestKey, StrategicProjectCandidate] = field(
        default_factory=dict
    )
    selected_candidate: Optional[ServiceRequestKey] = None
    progress_evidence: list[ProjectProgressEvidence] = field(default_factory=list)
    activity_events: int = 0
    created_expansion: int = 0
    last_expansion: int = 0
    terminal_reason: Optional[str] = None
    proof_pruning_allowed: bool = False


@dataclass
class StrategicProjectMetrics:
    projects_created: int = 0
    projects_reused: int = 0
    projects_achieved: int = 0
    projects_expired: int = 0
    projects_invalidated: int = 0
    projects_blocked: int = 0
    projects_exhausted: int = 0
    candidates_attached: int = 0
    candidate_replacements: int = 0
    service_requests_subscribed: int = 0
    project_service_executions: int = 0
    project_activity_events: int = 0
    project_progress_events: int = 0
    service_executions_without_progress: int = 0
    cheaper_arrival_revalidations: int = 0
    candidate_defer_events: int = 0
    candidate_reactivate_events: int = 0
    maximum_simultaneous_projects: int = 0
    maximum_candidates_per_project: int = 0
    maximum_project_lifetime_expansions: int = 0
    project_identity_collisions: int = 0


def _project_id(kind: StrategicProjectKind, target: StrategicTargetIdentity) -> str:
    return hashlib.sha256(
        repr((kind.value, target.campaign_id)).encode()
    ).hexdigest()[:16]


class StrategicProjectRegistry:
    """Own project purpose while delegating every execution fact to the registry."""

    def __init__(self) -> None:
        self._projects: Dict[str, StrategicProject] = {}
        self._by_target: Dict[
            Tuple[StrategicProjectKind, StrategicTargetIdentity], str
        ] = {}
        self._candidate_projects: Dict[ServiceRequestKey, set[str]] = {}
        self.metrics = StrategicProjectMetrics()

    @property
    def projects(self) -> Tuple[StrategicProject, ...]:
        return tuple(self._projects[key] for key in sorted(self._projects))

    def project(self, project_id: str) -> Optional[StrategicProject]:
        return self._projects.get(project_id)

    def projects_for_request(
        self, key: ServiceRequestKey
    ) -> Tuple[StrategicProject, ...]:
        return tuple(
            self._projects[project_id]
            for project_id in sorted(self._candidate_projects.get(key, ()))
        )

    def attach_continuation(
        self,
        credit: SameCampaignContinuationCredit,
        request_key: ServiceRequestKey,
        *,
        priority_information: Tuple[Hashable, ...],
        arrival_version: int,
        expansion: int,
    ) -> StrategicProject:
        target = StrategicTargetIdentity(credit.objective_id)
        index = (StrategicProjectKind.SAME_CAMPAIGN_CONTINUATION, target)
        project_id = _project_id(*index)
        existing_id = self._by_target.get(index)
        if existing_id is not None and existing_id != project_id:
            self.metrics.project_identity_collisions += 1
            raise ValueError("strategic project identity collision")
        project = self._projects.get(project_id)
        if project is None:
            project = StrategicProject(
                project_id,
                index[0],
                target,
                ProjectBaseline(
                    tuple(credit.outstanding_dependencies),
                    credit.baseline_total_g,
                    credit.created_depth,
                    credit.created_elapsed_seconds,
                ),
                created_expansion=expansion,
                last_expansion=expansion,
            )
            self._projects[project_id] = project
            self._by_target[index] = project_id
            self.metrics.projects_created += 1
        else:
            self.metrics.projects_reused += 1
            if project.target != target or project.kind is not index[0]:
                self.metrics.project_identity_collisions += 1
                raise ValueError("incompatible candidate attempted to enter project")
            if project.status is StrategicProjectStatus.BLOCKED:
                project.status = StrategicProjectStatus.RUNNABLE
        candidate = project.candidates.get(request_key)
        if candidate is None:
            candidate = StrategicProjectCandidate(
                request_key,
                credit,
                tuple(priority_information),
                expansion,
                arrival_version,
                last_observed_dependencies=tuple(credit.outstanding_dependencies),
            )
            project.candidates[request_key] = candidate
            self._candidate_projects.setdefault(request_key, set()).add(project_id)
            self.metrics.candidates_attached += 1
        else:
            candidate.continuation = credit
            candidate.priority_information = tuple(priority_information)
            candidate.arrival_version = arrival_version
        project.last_expansion = expansion
        self._update_peaks(expansion)
        return project

    def revalidate_cheaper_arrival(
        self, key: ServiceRequestKey, *, arrival_version: int
    ) -> None:
        for project in self.projects_for_request(key):
            candidate = project.candidates[key]
            if arrival_version > candidate.arrival_version:
                candidate.arrival_version = arrival_version
                self.metrics.cheaper_arrival_revalidations += 1

    def select_global_candidate(
        self,
        registry: StateServiceRegistry,
        eligible_requests: Iterable[ServiceRequestKey],
        *,
        expansion: int,
    ) -> Optional[StrategicProjectCandidate]:
        eligible = set(eligible_requests)
        choices = []
        for project in self.projects:
            if project.status not in {
                StrategicProjectStatus.RUNNABLE,
                StrategicProjectStatus.BLOCKED,
            }:
                continue
            candidates = [
                item
                for key, item in project.candidates.items()
                if key in eligible
                and item.continuation.is_live
                and registry.request(key) is not None
                and registry.request(key).status is ServiceStatus.LIVE
            ]
            if not candidates:
                if project.status is not StrategicProjectStatus.BLOCKED:
                    project.status = StrategicProjectStatus.BLOCKED
                    self.metrics.projects_blocked += 1
                project.selected_candidate = None
                continue
            project.status = StrategicProjectStatus.RUNNABLE
            choices.extend(
                (
                    item.priority_information,
                    project.project_id,
                    repr(item.request_key),
                    item,
                )
                for item in candidates
            )
        chosen_row = min(choices, default=None)
        chosen = chosen_row[3] if chosen_row is not None else None
        chosen_project_id = chosen_row[1] if chosen_row is not None else None
        for project in self.projects:
            old = project.selected_candidate
            new = chosen.request_key if project.project_id == chosen_project_id else None
            if old is not None and old != new:
                registry.unsubscribe(
                    old,
                    ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION,
                    reason="project candidate replaced or no longer runnable",
                )
            if new is not None:
                if old is not None and old != new:
                    self.metrics.candidate_replacements += 1
                if not registry.has_active_subscriber(
                    new, ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION
                ):
                    registry.subscribe(
                        new,
                        ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION,
                        priority_information=chosen.priority_information,
                        quota_identity=project.project_id,
                        reason="strongest live same-campaign project candidate",
                    )
                    self.metrics.service_requests_subscribed += 1
                project.selected_candidate = new
                project.last_expansion = expansion
            else:
                project.selected_candidate = None
        self._update_peaks(expansion)
        return chosen

    def selected_credit_for_request(
        self, key: ServiceRequestKey
    ) -> Optional[SameCampaignContinuationCredit]:
        for project in self.projects_for_request(key):
            if (
                project.selected_candidate == key
                and project.status is StrategicProjectStatus.RUNNABLE
            ):
                return project.candidates[key].continuation
        return None

    def revalidate_selected(
        self,
        key: ServiceRequestKey,
        *,
        current_depth: int,
        current_elapsed_seconds: float,
        objective_still_credible: bool,
        fully_harvested: bool,
        outstanding_dependencies: Optional[Sequence[str]],
        current_g: int,
        registry: StateServiceRegistry,
        expansion: int,
    ) -> Optional[SameCampaignContinuationCredit]:
        for project in self.projects_for_request(key):
            if project.selected_candidate != key:
                continue
            candidate = project.candidates[key]
            refreshed = refresh_continuation_credit(
                candidate.continuation,
                current_depth=current_depth,
                current_elapsed_seconds=current_elapsed_seconds,
                objective_still_credible=objective_still_credible,
                fully_harvested=fully_harvested,
                outstanding_dependencies=outstanding_dependencies,
                current_g=current_g,
            )
            candidate.continuation = refreshed
            project.last_expansion = expansion
            if refreshed.status is SameCampaignContinuationStatus.HARVESTED:
                project.status = StrategicProjectStatus.ACHIEVED
                project.terminal_reason = refreshed.expiry_reason
                self.metrics.projects_achieved += 1
            elif refreshed.status in {
                SameCampaignContinuationStatus.INVALIDATED,
                SameCampaignContinuationStatus.SUPERSEDED,
            }:
                project.status = StrategicProjectStatus.INVALIDATED
                project.terminal_reason = refreshed.expiry_reason
                self.metrics.projects_invalidated += 1
            elif refreshed.status is SameCampaignContinuationStatus.EXPIRED:
                project.status = StrategicProjectStatus.EXHAUSTED
                project.terminal_reason = refreshed.expiry_reason
                self.metrics.projects_expired += 1
                self.metrics.projects_exhausted += 1
            if not refreshed.is_live:
                registry.unsubscribe(
                    key,
                    ServiceSubscriberKind.STRATEGIC_PROJECT_CONTINUATION,
                    reason=refreshed.expiry_reason or refreshed.status.value,
                )
                project.selected_candidate = None
            self._update_peaks(expansion)
            return refreshed
        return None

    def observe_execution(
        self,
        key: ServiceRequestKey,
        *,
        execution_ordinal: int,
        expansion: int,
        result: Optional[ServiceExecutionResult] = None,
    ) -> None:
        for project in self.projects_for_request(key):
            candidate = project.candidates[key]
            project.activity_events += 1
            candidate.service_executions += 1
            candidate.last_execution_result = result
            self.metrics.project_service_executions += 1
            self.metrics.project_activity_events += 1
            before = set(candidate.last_observed_dependencies)
            after = set(candidate.continuation.outstanding_dependencies)
            closed = tuple(sorted(before - after)) if after.issubset(before) else ()
            achieved = candidate.continuation.status is SameCampaignContinuationStatus.HARVESTED
            if closed or achieved:
                project.progress_evidence.append(
                    ProjectProgressEvidence(execution_ordinal, key, closed, achieved)
                )
                self.metrics.project_progress_events += 1
            else:
                self.metrics.service_executions_without_progress += 1
            candidate.last_observed_dependencies = tuple(
                candidate.continuation.outstanding_dependencies
            )
            project.last_expansion = expansion
        self._update_peaks(expansion)

    def note_deferred(self, key: ServiceRequestKey) -> None:
        if self.projects_for_request(key):
            self.metrics.candidate_defer_events += 1

    def note_reactivated(self, key: ServiceRequestKey) -> None:
        if self.projects_for_request(key):
            self.metrics.candidate_reactivate_events += 1

    def _update_peaks(self, expansion: int) -> None:
        active = [
            item
            for item in self.projects
            if item.status
            in {StrategicProjectStatus.RUNNABLE, StrategicProjectStatus.BLOCKED}
        ]
        self.metrics.maximum_simultaneous_projects = max(
            self.metrics.maximum_simultaneous_projects, len(active)
        )
        self.metrics.maximum_candidates_per_project = max(
            self.metrics.maximum_candidates_per_project,
            max((len(item.candidates) for item in self.projects), default=0),
        )
        self.metrics.maximum_project_lifetime_expansions = max(
            self.metrics.maximum_project_lifetime_expansions,
            max(
                (expansion - item.created_expansion for item in self.projects),
                default=0,
            ),
        )

    def approximate_bytes(self) -> int:
        total = sys.getsizeof(self) + sys.getsizeof(self._projects)
        total += sys.getsizeof(self._by_target) + sys.getsizeof(self._candidate_projects)
        for project in self.projects:
            total += sys.getsizeof(project) + sys.getsizeof(project.candidates)
            total += sys.getsizeof(project.progress_evidence)
            total += sum(sys.getsizeof(item) for item in project.candidates.values())
        return total

    def snapshot(self) -> dict:
        return {
            **vars(self.metrics),
            "projects": len(self._projects),
            "status_counts": {
                status.value: sum(item.status is status for item in self.projects)
                for status in StrategicProjectStatus
            },
            "approximate_bytes": self.approximate_bytes(),
            "per_project": [
                {
                    "project_id": item.project_id,
                    "kind": item.kind.value,
                    "campaign_id": item.target.campaign_id,
                    "status": item.status.value,
                    "candidates": len(item.candidates),
                    "service_executions": item.activity_events,
                    "semantic_progress_events": len(item.progress_evidence),
                    "lifetime_expansions": item.last_expansion - item.created_expansion,
                }
                for item in self.projects
            ],
        }
