"""Proof-neutral tactical commitment for one semantic target.

The v0.8 allocator intentionally remembers evidence for one exact structural
context.  A semantic milestone can, however, survive a structural transition.
This module records the bounded target-specific evidence needed to decide
whether the *next* fresh request may start at an already-earned existing tier.

Lineage is planning context only.  It never changes canonical Spider identity,
the exact transposition table, an admissible bound, or any resource ceiling.
Unused grants are not represented and therefore cannot cross a boundary.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.planner.tactical_resource_allocator import TacticalResourceTier
from spider.planner.source_completion import (
    SourceCompletionEvent,
    SourceRequirementSatisfaction,
)
from spider.state_identity import CanonicalStateKey


class TargetCommitmentStatus(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    PROMOTED = "PROMOTED"
    RETAINED = "RETAINED"
    DEMOTED = "DEMOTED"
    RESET = "RESET"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class TargetCommitmentTransition(str, Enum):
    START = "START"
    PROMOTE_AFTER_HARVEST = "PROMOTE_AFTER_HARVEST"
    RETAIN_AFTER_HARVEST = "RETAIN_AFTER_HARVEST"
    RETAIN_ACROSS_BLOCKER_CHANGE = "RETAIN_ACROSS_BLOCKER_CHANGE"
    DEMOTE_AFTER_MISS = "DEMOTE_AFTER_MISS"
    RESET_NO_PORTABLE_HARVEST = "RESET_NO_PORTABLE_HARVEST"
    RESET_CONTRADICTORY_ANALYSIS = "RESET_CONTRADICTORY_ANALYSIS"
    RESET_LIFECYCLE_DEBT = "RESET_LIFECYCLE_DEBT"
    EXPIRE_PERSISTENCE_ENVELOPE = "EXPIRE_PERSISTENCE_ENVELOPE"
    SUPERSEDE_TARGET = "SUPERSEDE_TARGET"
    INVALIDATE_TARGET = "INVALIDATE_TARGET"
    COMPLETE_TARGET = "COMPLETE_TARGET"


class PersistedTargetFailureDiagnosis(str, Enum):
    TACTICAL_TIER_RESET = "TACTICAL_TIER_RESET"
    FRESH_CANDIDATE_TURNOVER = "FRESH_CANDIDATE_TURNOVER"
    TARGET_ATTRIBUTION_LOSS = "TARGET_ATTRIBUTION_LOSS"
    LIFECYCLE_MISORDERING = "LIFECYCLE_MISORDERING"
    STRATEGIC_ADMISSION_LOSS = "STRATEGIC_ADMISSION_LOSS"
    RESOURCE_BOUND = "RESOURCE_BOUND"
    STRUCTURAL_BLOCKER = "STRUCTURAL_BLOCKER"
    TARGET_SUPERSEDED = "TARGET_SUPERSEDED"
    EXPIRED = "EXPIRED"
    OTHER_EXPLICIT = "OTHER_EXPLICIT"


@dataclass(frozen=True)
class TargetCommitmentEvidence:
    """Only named evidence attributable to the semantic target is portable."""

    named_harvest: Tuple[str, ...] = ()
    completion_class: Optional[str] = None
    source_depth_before: Optional[int] = None
    source_depth_after: Optional[int] = None
    blockers_before: Optional[int] = None
    blockers_after: Optional[int] = None
    dependency_completed: bool = False
    prerequisite_completed: bool = False
    source_exposed: bool = False
    source_consumed: bool = False
    substantial_progress: bool = False
    target_relevant: bool = False
    nodes_consumed: int = 0
    seconds_consumed: float = 0.0
    corrected_paid_cost: int = 0
    lifecycle_debt: float = 0.0
    restore_replace_obligation: Optional[str] = None
    compensation_credible: bool = True
    proof_pruning_allowed: bool = False

    @property
    def source_depth_reduced(self) -> bool:
        return bool(
            self.source_depth_before is not None
            and self.source_depth_after is not None
            and self.source_depth_after < self.source_depth_before
        )

    @property
    def blockers_reduced(self) -> bool:
        return bool(
            self.blockers_before is not None
            and self.blockers_after is not None
            and self.blockers_after < self.blockers_before
        )

    @property
    def has_portable_harvest(self) -> bool:
        return bool(
            self.target_relevant
            and (
                self.named_harvest
                or self.dependency_completed
                or self.prerequisite_completed
                or self.source_depth_reduced
                or self.blockers_reduced
                or self.source_exposed
                or self.source_consumed
                or self.substantial_progress
                or self.completion_class
                in {"DEPENDENCY_ADVANCED", "DEPENDENCY_COMPLETED", "SOURCE_EXPOSED"}
            )
        )


@dataclass(frozen=True)
class TargetGrantDecision:
    requested_tier: TacticalResourceTier
    inherited_commitment: bool
    status: TargetCommitmentStatus
    transition: TargetCommitmentTransition
    reason: str
    previous_tier: Optional[TacticalResourceTier] = None
    earned_tier: Optional[TacticalResourceTier] = None
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TargetGrantLineageEntry:
    lineage_id: str
    semantic_target_fingerprint: Tuple
    campaign_id: Optional[str]
    objective_id: Optional[str]
    dependency_id: Optional[str]
    previous_state_key: Optional[CanonicalStateKey]
    current_state_key: CanonicalStateKey
    previous_state_hash: Optional[str]
    current_state_hash: str
    previous_blocker_fingerprint: Optional[str]
    current_blocker_fingerprint: Optional[str]
    previous_blocker_kind: Optional[str]
    current_blocker_kind: Optional[str]
    previous_granted_tier: Optional[TacticalResourceTier]
    requested_tier: TacticalResourceTier
    granted_tier: Optional[TacticalResourceTier]
    earned_tier: TacticalResourceTier
    evidence: TargetCommitmentEvidence
    status: TargetCommitmentStatus
    transition: TargetCommitmentTransition
    reason: str
    lifecycle_debt: float = 0.0
    restore_replace_obligation: Optional[str] = None
    target_valid: bool = True
    generation: int = 0
    consecutive_misses: int = 0
    persistence_limit: int = 3
    realizer: Optional[str] = None
    proof_pruning_allowed: bool = False
    source_satisfactions: Tuple[SourceRequirementSatisfaction, ...] = ()
    source_completion_event_ids: Tuple[str, ...] = ()
    follow_on_source_requirement_ids: Tuple[str, ...] = ()

    @property
    def identity_key(self) -> Tuple:
        """Coordinate-free key; dependency/realiser/state are descriptive only."""
        return self.semantic_target_fingerprint

    @property
    def is_live(self) -> bool:
        return self.target_valid and self.status not in {
            TargetCommitmentStatus.INVALIDATED,
            TargetCommitmentStatus.SUPERSEDED,
            TargetCommitmentStatus.COMPLETED,
            TargetCommitmentStatus.EXPIRED,
        }


@dataclass(frozen=True)
class TargetBoundaryTrace:
    lineage_id: str
    semantic_target_fingerprint: Tuple
    state_before_hash: Optional[str]
    state_after_hash: str
    dependency_before: Optional[str]
    dependency_after: Optional[str]
    blocker_before: Optional[str]
    blocker_after: Optional[str]
    progress_before: str
    progress_after: str
    previous_tier: Optional[TacticalResourceTier]
    requested_next_tier: TacticalResourceTier
    granted_next_tier: Optional[TacticalResourceTier]
    promotion_retained: bool
    reason: str
    fresh_relevant_candidate_count: int
    candidate_classes: Tuple[str, ...]
    best_next_candidate: Optional[str]
    best_candidate_minimum_tier: Optional[TacticalResourceTier]
    candidate_inside_grant: Optional[bool]
    selected_action: Optional[str]
    admission_reason: Optional[str]
    lifecycle_obligation: Optional[str]
    next_closure_result: Optional[str]
    eventual_target_outcome: Optional[str]
    failure_diagnosis: Optional[PersistedTargetFailureDiagnosis]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TargetGrantLineage:
    entries: Tuple[TargetGrantLineageEntry, ...] = ()
    boundary_traces: Tuple[TargetBoundaryTrace, ...] = ()
    proof_pruning_allowed: bool = False

    def active_for(self, semantic_target_fingerprint: Tuple) -> Optional[TargetGrantLineageEntry]:
        return next(
            (
                item
                for item in reversed(self.entries)
                if item.identity_key == semantic_target_fingerprint and item.is_live
            ),
            None,
        )

    def with_entry(self, entry: TargetGrantLineageEntry) -> "TargetGrantLineage":
        return replace(self, entries=self.entries + (entry,))

    def with_trace(self, trace: TargetBoundaryTrace) -> "TargetGrantLineage":
        return replace(self, boundary_traces=self.boundary_traces + (trace,))


def _state_hash(state_key: CanonicalStateKey) -> str:
    return hashlib.sha256(repr(state_key).encode("utf-8")).hexdigest()[:16]


def _lineage_id(semantic_target_fingerprint: Tuple) -> str:
    return hashlib.sha256(repr(semantic_target_fingerprint).encode("utf-8")).hexdigest()[:16]


def _bounded_nonterminal_promotion(tier: TacticalResourceTier) -> TacticalResourceTier:
    return TacticalResourceTier(
        min(int(tier) + 1, int(TacticalResourceTier.COMMITTED))
    )


def new_target_lineage_entry(
    semantic_target_fingerprint: Tuple,
    state_key: CanonicalStateKey,
    *,
    campaign_id: Optional[str],
    objective_id: Optional[str],
    dependency_id: Optional[str],
    blocker_fingerprint: Optional[str],
    blocker_kind: Optional[str],
    initial_tier: TacticalResourceTier = TacticalResourceTier.PROBE,
    persistence_limit: int = 3,
    realizer: Optional[str] = None,
) -> TargetGrantLineageEntry:
    return TargetGrantLineageEntry(
        lineage_id=_lineage_id(semantic_target_fingerprint),
        semantic_target_fingerprint=semantic_target_fingerprint,
        campaign_id=campaign_id,
        objective_id=objective_id,
        dependency_id=dependency_id,
        previous_state_key=None,
        current_state_key=state_key,
        previous_state_hash=None,
        current_state_hash=_state_hash(state_key),
        previous_blocker_fingerprint=None,
        current_blocker_fingerprint=blocker_fingerprint,
        previous_blocker_kind=None,
        current_blocker_kind=blocker_kind,
        previous_granted_tier=None,
        requested_tier=initial_tier,
        granted_tier=None,
        earned_tier=initial_tier,
        evidence=TargetCommitmentEvidence(),
        status=TargetCommitmentStatus.NEW,
        transition=TargetCommitmentTransition.START,
        reason="fresh semantic target starts under the existing demand tier",
        persistence_limit=max(1, persistence_limit),
        realizer=realizer,
    )


def decide_target_grant(
    entry: Optional[TargetGrantLineageEntry],
    *,
    semantic_target_fingerprint: Tuple,
    requested_initial_tier: TacticalResourceTier,
    terminal_qualified: bool,
    target_valid: bool,
    current_state_key: CanonicalStateKey,
    current_blocker_fingerprint: Optional[str],
    current_blocker_kind: Optional[str],
    lifecycle_debt: float = 0.0,
    compensation_credible: bool = True,
) -> TargetGrantDecision:
    """Choose among existing tiers without changing any tier specification."""

    if entry is None or entry.identity_key != semantic_target_fingerprint:
        tier = (
            TacticalResourceTier.TERMINAL
            if terminal_qualified and requested_initial_tier == TacticalResourceTier.TERMINAL
            else min(requested_initial_tier, TacticalResourceTier.COMMITTED)
        )
        return TargetGrantDecision(
            tier,
            False,
            TargetCommitmentStatus.NEW,
            TargetCommitmentTransition.START,
            "no same-target portable commitment exists in this admitted path",
        )
    if not target_valid:
        return TargetGrantDecision(
            requested_initial_tier,
            False,
            TargetCommitmentStatus.INVALIDATED,
            TargetCommitmentTransition.INVALIDATE_TARGET,
            "fresh analysis invalidated the semantic target",
            entry.granted_tier,
            entry.earned_tier,
        )
    if entry.generation >= entry.persistence_limit:
        return TargetGrantDecision(
            requested_initial_tier,
            False,
            TargetCommitmentStatus.EXPIRED,
            TargetCommitmentTransition.EXPIRE_PERSISTENCE_ENVELOPE,
            "the configured target-persistence envelope expired",
            entry.granted_tier,
            entry.earned_tier,
        )
    if terminal_qualified and requested_initial_tier == TacticalResourceTier.TERMINAL:
        return TargetGrantDecision(
            TacticalResourceTier.TERMINAL,
            False,
            TargetCommitmentStatus.ACTIVE,
            TargetCommitmentTransition.RETAIN_AFTER_HARVEST,
            "the unchanged terminal predicate freshly qualifies TERMINAL",
            entry.granted_tier,
            entry.earned_tier,
        )
    if lifecycle_debt > entry.lifecycle_debt and not compensation_credible:
        tier = TacticalResourceTier(
            max(int(requested_initial_tier), int(entry.earned_tier) - 1)
        )
        tier = min(tier, TacticalResourceTier.COMMITTED)
        return TargetGrantDecision(
            tier,
            tier > requested_initial_tier,
            TargetCommitmentStatus.DEMOTED if tier > requested_initial_tier else TargetCommitmentStatus.RESET,
            TargetCommitmentTransition.RESET_LIFECYCLE_DEBT,
            "fresh lifecycle debt worsened and the prior compensation is no longer credible",
            entry.granted_tier,
            entry.earned_tier,
        )
    if not entry.evidence.has_portable_harvest:
        return TargetGrantDecision(
            requested_initial_tier,
            False,
            TargetCommitmentStatus.RESET,
            TargetCommitmentTransition.RESET_NO_PORTABLE_HARVEST,
            "the prior bounded call produced no named target-specific harvest",
            entry.granted_tier,
            entry.earned_tier,
        )
    if entry.consecutive_misses:
        tier = TacticalResourceTier(
            max(int(requested_initial_tier), int(entry.earned_tier) - entry.consecutive_misses)
        )
        tier = min(tier, TacticalResourceTier.COMMITTED)
        return TargetGrantDecision(
            tier,
            tier > requested_initial_tier,
            TargetCommitmentStatus.DEMOTED,
            TargetCommitmentTransition.DEMOTE_AFTER_MISS,
            "target-specific commitment decayed after a fresh no-harvest miss",
            entry.granted_tier,
            entry.earned_tier,
        )
    tier = min(entry.earned_tier, TacticalResourceTier.COMMITTED)
    transition = (
        TargetCommitmentTransition.RETAIN_ACROSS_BLOCKER_CHANGE
        if entry.current_blocker_kind != current_blocker_kind
        else TargetCommitmentTransition.RETAIN_AFTER_HARVEST
    )
    status = (
        TargetCommitmentStatus.PROMOTED
        if entry.granted_tier is not None and tier > entry.granted_tier
        else TargetCommitmentStatus.RETAINED
    )
    return TargetGrantDecision(
        tier,
        tier > requested_initial_tier,
        status,
        transition,
        (
            "same semantic target retains earned commitment across a fresh blocker type"
            if transition == TargetCommitmentTransition.RETAIN_ACROSS_BLOCKER_CHANGE
            else "same semantic target retains commitment earned by named structural harvest"
        ),
        entry.granted_tier,
        entry.earned_tier,
    )


def record_target_grant(
    entry: TargetGrantLineageEntry,
    *,
    state_key: CanonicalStateKey,
    dependency_id: Optional[str],
    blocker_fingerprint: Optional[str],
    blocker_kind: Optional[str],
    requested_tier: TacticalResourceTier,
    granted_tier: Optional[TacticalResourceTier],
    decision: TargetGrantDecision,
    realizer: Optional[str],
) -> TargetGrantLineageEntry:
    crossed_state = entry.current_state_key != state_key
    return replace(
        entry,
        previous_state_key=(
            entry.current_state_key if crossed_state else entry.previous_state_key
        ),
        current_state_key=state_key,
        previous_state_hash=(
            entry.current_state_hash if crossed_state else entry.previous_state_hash
        ),
        current_state_hash=_state_hash(state_key),
        dependency_id=dependency_id,
        previous_blocker_fingerprint=entry.current_blocker_fingerprint,
        current_blocker_fingerprint=blocker_fingerprint,
        previous_blocker_kind=entry.current_blocker_kind,
        current_blocker_kind=blocker_kind,
        previous_granted_tier=entry.granted_tier,
        requested_tier=requested_tier,
        granted_tier=granted_tier,
        status=decision.status,
        transition=decision.transition,
        reason=decision.reason,
        generation=entry.generation + int(crossed_state),
        realizer=realizer,
    )


def record_target_outcome(
    entry: TargetGrantLineageEntry,
    evidence: TargetCommitmentEvidence,
    *,
    end_state_key: CanonicalStateKey,
    target_valid: bool = True,
    completed: bool = False,
) -> TargetGrantLineageEntry:
    granted = entry.granted_tier or entry.requested_tier
    crossed_state = entry.current_state_key != end_state_key
    if completed:
        status = TargetCommitmentStatus.COMPLETED
        transition = TargetCommitmentTransition.COMPLETE_TARGET
        earned = granted
        misses = 0
        reason = "the scoped semantic target completed"
    elif evidence.has_portable_harvest:
        earned = _bounded_nonterminal_promotion(granted)
        status = (
            TargetCommitmentStatus.PROMOTED
            if earned > granted
            else TargetCommitmentStatus.RETAINED
        )
        transition = (
            TargetCommitmentTransition.PROMOTE_AFTER_HARVEST
            if earned > granted
            else TargetCommitmentTransition.RETAIN_AFTER_HARVEST
        )
        misses = 0
        reason = "named target-specific structural harvest earned the next existing tier"
    else:
        misses = entry.consecutive_misses + 1
        earned = TacticalResourceTier(
            max(int(TacticalResourceTier.PROBE), int(granted) - int(granted >= TacticalResourceTier.SHALLOW))
        )
        status = TargetCommitmentStatus.DEMOTED if granted > TacticalResourceTier.PROBE else TargetCommitmentStatus.RESET
        transition = TargetCommitmentTransition.DEMOTE_AFTER_MISS
        reason = "fresh bounded outcome produced no named target-specific harvest"
    return replace(
        entry,
        previous_state_key=entry.current_state_key,
        current_state_key=end_state_key,
        previous_state_hash=entry.current_state_hash,
        current_state_hash=_state_hash(end_state_key),
        earned_tier=earned,
        evidence=evidence,
        status=(TargetCommitmentStatus.INVALIDATED if not target_valid else status),
        transition=(TargetCommitmentTransition.INVALIDATE_TARGET if not target_valid else transition),
        reason=("fresh outcome invalidated the semantic target" if not target_valid else reason),
        lifecycle_debt=evidence.lifecycle_debt,
        restore_replace_obligation=evidence.restore_replace_obligation,
        target_valid=target_valid,
        consecutive_misses=misses,
        generation=entry.generation + int(crossed_state),
    )


def record_lineage_source_completion(
    entry: TargetGrantLineageEntry,
    events: Sequence[SourceCompletionEvent],
    satisfactions: Sequence[SourceRequirementSatisfaction] = (),
) -> TargetGrantLineageEntry:
    """Attach scoped source harvest without completing the whole target."""

    event_ids = tuple(dict.fromkeys(
        entry.source_completion_event_ids + tuple(item.event_id for item in events)
    ))
    merged = {
        item.requirement.identity_key: item for item in entry.source_satisfactions
    }
    for item in tuple(satisfactions) + tuple(item.satisfaction for item in events):
        merged[item.requirement.identity_key] = item
    follow_on = tuple(dict.fromkeys(
        entry.follow_on_source_requirement_ids
        + tuple(
            f"{item.dependency_id}:exposed-blocker"
            for item in events
            if item.fresh_dependency_type == "SOURCE_EXPOSED_BUT_BLOCKED"
        )
    ))
    evidence = entry.evidence
    if events:
        evidence = replace(
            evidence,
            named_harvest=tuple(dict.fromkeys(
                evidence.named_harvest
                + tuple(f"SOURCE_REQUIREMENT_SATISFIED:{item.event_id}" for item in events)
            )),
            source_exposed=(evidence.source_exposed or any(item.exposed for item in events)),
            source_consumed=(evidence.source_consumed or any(item.consumed for item in events)),
            target_relevant=True,
        )
    return replace(
        entry,
        evidence=evidence,
        source_satisfactions=tuple(merged.values()),
        source_completion_event_ids=event_ids,
        follow_on_source_requirement_ids=follow_on,
    )


def make_boundary_trace(
    entry: TargetGrantLineageEntry,
    decision: TargetGrantDecision,
    *,
    dependency_after: Optional[str],
    blocker_after: Optional[str],
    progress_before: str,
    progress_after: str,
    fresh_candidate_classes: Sequence[str] = (),
    best_next_candidate: Optional[str] = None,
    best_candidate_minimum_tier: Optional[TacticalResourceTier] = None,
    granted_tier: Optional[TacticalResourceTier] = None,
    selected_action: Optional[str] = None,
    admission_reason: Optional[str] = None,
    next_closure_result: Optional[str] = None,
    eventual_target_outcome: Optional[str] = None,
    failure_diagnosis: Optional[PersistedTargetFailureDiagnosis] = None,
) -> TargetBoundaryTrace:
    inside = None
    if best_candidate_minimum_tier is not None and granted_tier is not None:
        inside = best_candidate_minimum_tier <= granted_tier
    return TargetBoundaryTrace(
        entry.lineage_id,
        entry.semantic_target_fingerprint,
        entry.previous_state_hash,
        entry.current_state_hash,
        entry.dependency_id,
        dependency_after,
        entry.previous_blocker_kind,
        blocker_after,
        progress_before,
        progress_after,
        entry.previous_granted_tier,
        decision.requested_tier,
        granted_tier,
        decision.inherited_commitment,
        decision.reason,
        len(tuple(fresh_candidate_classes)),
        tuple(fresh_candidate_classes),
        best_next_candidate,
        best_candidate_minimum_tier,
        inside,
        selected_action,
        admission_reason,
        entry.restore_replace_obligation,
        next_closure_result,
        eventual_target_outcome,
        failure_diagnosis,
    )


def diagnose_persisted_target_failure(
    trace: TargetBoundaryTrace,
    *,
    same_target_attributed: bool = True,
    candidate_turnover: bool = False,
    lifecycle_context_lost: bool = False,
    strategically_admitted: bool = True,
    resource_bound: bool = False,
    structural_blocker: bool = False,
    superseded: bool = False,
    expired: bool = False,
) -> PersistedTargetFailureDiagnosis:
    """Return one primary evidence-backed diagnosis for a failed continuation."""

    if expired:
        return PersistedTargetFailureDiagnosis.EXPIRED
    if superseded:
        return PersistedTargetFailureDiagnosis.TARGET_SUPERSEDED
    if not same_target_attributed:
        return PersistedTargetFailureDiagnosis.TARGET_ATTRIBUTION_LOSS
    if lifecycle_context_lost:
        return PersistedTargetFailureDiagnosis.LIFECYCLE_MISORDERING
    if not strategically_admitted:
        return PersistedTargetFailureDiagnosis.STRATEGIC_ADMISSION_LOSS
    if candidate_turnover:
        return PersistedTargetFailureDiagnosis.FRESH_CANDIDATE_TURNOVER
    if (
        trace.previous_tier is not None
        and trace.requested_next_tier < trace.previous_tier
        and trace.best_candidate_minimum_tier is not None
        and trace.best_candidate_minimum_tier > trace.requested_next_tier
        and trace.best_candidate_minimum_tier <= trace.previous_tier
    ):
        return PersistedTargetFailureDiagnosis.TACTICAL_TIER_RESET
    if resource_bound:
        return PersistedTargetFailureDiagnosis.RESOURCE_BOUND
    if structural_blocker or trace.fresh_relevant_candidate_count == 0:
        return PersistedTargetFailureDiagnosis.STRUCTURAL_BLOCKER
    return PersistedTargetFailureDiagnosis.OTHER_EXPLICIT
