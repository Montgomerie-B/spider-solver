"""Proof-neutral source completion facts across strategic boundaries.

Closure can finish one scoped source predicate while a broader campaign target
remains active.  The records here keep that distinction inspectable without
changing Spider identity, exact TT dominance, admissible bounds, or any search
resource.  Fresh physical state remains authoritative.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action
from spider.state_identity import CanonicalStateKey, canonical_state_key


class SourceCompletionScope(str, Enum):
    BURIED_PREDICATE = "BURIED_PREDICATE"
    EXPOSED_BLOCKER_PREDICATE = "EXPOSED_BLOCKER_PREDICATE"
    SEMANTIC_SOURCE_REQUIREMENT = "SEMANTIC_SOURCE_REQUIREMENT"
    SOURCE_CHAIN = "SOURCE_CHAIN"


class SourceCompletionStage(str, Enum):
    TRACE_COMPLETED = "TRACE_COMPLETED"
    CONTROLLER_SUCCESSOR_CREATED = "CONTROLLER_SUCCESSOR_CREATED"
    CONTROLLER_ADMITTED_COMPLETION = "CONTROLLER_ADMITTED_COMPLETION"
    FRESH_RESIDUAL_PRESERVED = "FRESH_RESIDUAL_PRESERVED"
    LINEAGE_PRESERVED = "LINEAGE_PRESERVED"
    SELECTED_PATH_COMPLETION = "SELECTED_PATH_COMPLETION"
    SOURCE_CONSUMED = "SOURCE_CONSUMED"
    SOURCE_INTEGRATED = "SOURCE_INTEGRATED"


class SourceCompletionDisposition(str, Enum):
    OBSERVED = "OBSERVED"
    PROPAGATED = "PROPAGATED"
    PRESERVED = "PRESERVED"
    REASSIGNED = "REASSIGNED"
    REOPENED = "REOPENED"
    REVERSED = "REVERSED"
    ADMISSION_LOSS = "ADMISSION_LOSS"
    SELECTED_ELSEWHERE = "SELECTED_ELSEWHERE"
    EXPIRED = "EXPIRED"


class SourceCompletionLossReason(str, Enum):
    TELEMETRY_ONLY_LOSS = "TELEMETRY_ONLY_LOSS"
    DEPENDENCY_TYPE_TRANSITION_LOSS = "DEPENDENCY_TYPE_TRANSITION_LOSS"
    PHYSICAL_SOURCE_ATTRIBUTION_LOSS = "PHYSICAL_SOURCE_ATTRIBUTION_LOSS"
    RESIDUAL_REOPENING = "RESIDUAL_REOPENING"
    CONTROLLER_PROPAGATION_LOSS = "CONTROLLER_PROPAGATION_LOSS"
    STRATEGIC_ADMISSION_LOSS = "STRATEGIC_ADMISSION_LOSS"
    PORTFOLIO_REANALYSIS_RESCOPING = "PORTFOLIO_REANALYSIS_RESCOPING"
    LEGITIMATE_EXPIRY = "LEGITIMATE_EXPIRY"
    OTHER_EXPLICIT = "OTHER_EXPLICIT"


class SourceRequirementSatisfactionState(str, Enum):
    UNSATISFIED = "UNSATISFIED"
    PARTIALLY_SATISFIED = "PARTIALLY_SATISFIED"
    EXPOSED = "EXPOSED"
    ACTIONABLE = "ACTIONABLE"
    CONSUMED = "CONSUMED"
    INTEGRATED = "INTEGRATED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"


class SourceRequirementReopeningReason(str, Enum):
    PHYSICAL_COPY_NO_LONGER_SATISFIES = "PHYSICAL_COPY_NO_LONGER_SATISFIES"
    REQUIREMENT_SCOPE_CHANGED = "REQUIREMENT_SCOPE_CHANGED"
    ADDITIONAL_COPY_REQUIRED = "ADDITIONAL_COPY_REQUIRED"
    SOURCE_BECAME_UNUSABLE = "SOURCE_BECAME_UNUSABLE"
    SEMANTIC_REASSIGNMENT = "SEMANTIC_REASSIGNMENT"
    ANALYSIS_DEFECT = "ANALYSIS_DEFECT"


class SourceExpiryClassification(str, Enum):
    COMPLETED_BEFORE_EXPIRY = "COMPLETED_BEFORE_EXPIRY"
    LEGITIMATE_NO_PROGRESS_EXPIRY = "LEGITIMATE_NO_PROGRESS_EXPIRY"
    RESOURCE_LIMIT_EXPIRY = "RESOURCE_LIMIT_EXPIRY"
    TARGET_TURNOVER_EXPIRY = "TARGET_TURNOVER_EXPIRY"
    ATTRIBUTION_LOSS_EXPIRY = "ATTRIBUTION_LOSS_EXPIRY"
    LIFECYCLE_EXPIRY = "LIFECYCLE_EXPIRY"
    SUPERSEDED_EXPIRY = "SUPERSEDED_EXPIRY"


_SATISFACTION_ORDER = {
    SourceRequirementSatisfactionState.UNSATISFIED: 0,
    SourceRequirementSatisfactionState.PARTIALLY_SATISFIED: 1,
    SourceRequirementSatisfactionState.EXPOSED: 2,
    SourceRequirementSatisfactionState.ACTIONABLE: 3,
    SourceRequirementSatisfactionState.CONSUMED: 4,
    SourceRequirementSatisfactionState.INTEGRATED: 5,
    SourceRequirementSatisfactionState.SUPERSEDED: 0,
    SourceRequirementSatisfactionState.INVALIDATED: 0,
}


@dataclass(frozen=True)
class PhysicalSourceIdentity:
    """Event-local physical copy identity with location kept separate."""

    suit: str
    rank: int
    provenance_id: str
    current_zone: str
    current_column: Optional[int]
    current_offset: Optional[int]
    face_up: bool
    blocker_depth: int
    consumed: bool = False
    integrated: bool = False
    foundation_removed: bool = False
    proof_pruning_allowed: bool = False

    @property
    def identity_key(self) -> Tuple[str, int, str]:
        return (self.suit, self.rank, self.provenance_id)

    @property
    def location(self) -> Tuple[str, Optional[int], Optional[int]]:
        return (self.current_zone, self.current_column, self.current_offset)


@dataclass(frozen=True)
class SemanticSourceRequirement:
    requirement_id: str
    semantic_target_fingerprint: Tuple
    dependency_id: str
    scope: SourceCompletionScope
    suit: str
    rank: int
    copies_required: int = 1
    proof_pruning_allowed: bool = False

    @property
    def identity_key(self) -> Tuple:
        return (
            self.semantic_target_fingerprint,
            self.requirement_id,
            self.scope,
            self.suit,
            self.rank,
            self.copies_required,
        )


@dataclass(frozen=True)
class SourceRequirementSatisfaction:
    requirement: SemanticSourceRequirement
    state: SourceRequirementSatisfactionState
    satisfying_sources: Tuple[PhysicalSourceIdentity, ...]
    first_satisfied_state_hash: Optional[str]
    current_state_hash: str
    evidence: Tuple[str, ...]
    fresh_reanalysis_preserved: bool
    reopening_reason: Optional[SourceRequirementReopeningReason] = None
    copy_reassigned: bool = False
    superseding_requirement_id: Optional[str] = None
    proof_pruning_allowed: bool = False

    @property
    def satisfied(self) -> bool:
        return self.state not in {
            SourceRequirementSatisfactionState.UNSATISFIED,
            SourceRequirementSatisfactionState.PARTIALLY_SATISFIED,
            SourceRequirementSatisfactionState.INVALIDATED,
        }


@dataclass(frozen=True)
class SourceCompletionEvent:
    event_id: str
    semantic_target_fingerprint: Tuple
    dependency_id: str
    original_dependency_type: str
    fresh_dependency_type: Optional[str]
    scope: SourceCompletionScope
    physical_source: PhysicalSourceIdentity
    requirement: SemanticSourceRequirement
    satisfaction: SourceRequirementSatisfaction
    exact_state_key: CanonicalStateKey
    exact_state_hash: str
    actions: Tuple[Action, ...]
    completion_class: str
    source_depth_before: int
    source_depth_after: int
    exposed: bool
    actionable: bool
    consumed: bool
    integrated: bool
    evidence_provenance: Tuple[str, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class SourceCompletionPropagationTrace:
    event: SourceCompletionEvent
    stages: Tuple[SourceCompletionStage, ...] = (
        SourceCompletionStage.TRACE_COMPLETED,
    )
    disposition: SourceCompletionDisposition = SourceCompletionDisposition.OBSERVED
    successor_created: bool = False
    controller_admitted: bool = False
    residual_preserved: bool = False
    lineage_preserved: bool = False
    selected_path: bool = False
    copy_reassigned: bool = False
    later_consumed: bool = False
    later_integrated: bool = False
    loss_reason: Optional[SourceCompletionLossReason] = None
    reopening_reason: Optional[SourceRequirementReopeningReason] = None
    detail: str = "closure fresh state completed a scoped source predicate"
    proof_pruning_allowed: bool = False

    def advance(
        self,
        stage: SourceCompletionStage,
        *,
        disposition: SourceCompletionDisposition = SourceCompletionDisposition.PROPAGATED,
        detail: Optional[str] = None,
        loss_reason: Optional[SourceCompletionLossReason] = None,
        reopening_reason: Optional[SourceRequirementReopeningReason] = None,
    ) -> "SourceCompletionPropagationTrace":
        stages = self.stages if stage in self.stages else self.stages + (stage,)
        return replace(
            self,
            stages=stages,
            disposition=disposition,
            successor_created=(self.successor_created or stage == SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED),
            controller_admitted=(self.controller_admitted or stage == SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION),
            residual_preserved=(self.residual_preserved or stage == SourceCompletionStage.FRESH_RESIDUAL_PRESERVED),
            lineage_preserved=(self.lineage_preserved or stage == SourceCompletionStage.LINEAGE_PRESERVED),
            selected_path=(self.selected_path or stage == SourceCompletionStage.SELECTED_PATH_COMPLETION),
            later_consumed=(self.later_consumed or stage == SourceCompletionStage.SOURCE_CONSUMED),
            later_integrated=(self.later_integrated or stage == SourceCompletionStage.SOURCE_INTEGRATED),
            loss_reason=loss_reason if loss_reason is not None else self.loss_reason,
            reopening_reason=(
                reopening_reason if reopening_reason is not None else self.reopening_reason
            ),
            detail=detail or self.detail,
        )

    def merge(self, newer: "SourceCompletionPropagationTrace") -> "SourceCompletionPropagationTrace":
        """Merge repeated analysis without allowing an earlier stage to vanish."""

        if self.event.event_id != newer.event.event_id:
            raise ValueError("only traces for the same source-completion event can merge")
        stages = self.stages + tuple(item for item in newer.stages if item not in self.stages)
        return replace(
            newer,
            stages=stages,
            successor_created=(self.successor_created or newer.successor_created),
            controller_admitted=(self.controller_admitted or newer.controller_admitted),
            residual_preserved=(self.residual_preserved or newer.residual_preserved),
            lineage_preserved=(self.lineage_preserved or newer.lineage_preserved),
            selected_path=(self.selected_path or newer.selected_path),
            copy_reassigned=(self.copy_reassigned or newer.copy_reassigned),
            later_consumed=(self.later_consumed or newer.later_consumed),
            later_integrated=(self.later_integrated or newer.later_integrated),
            loss_reason=(newer.loss_reason or self.loss_reason),
            reopening_reason=(newer.reopening_reason or self.reopening_reason),
        )


@dataclass(frozen=True)
class SourceCompletionLedger:
    traces: Tuple[SourceCompletionPropagationTrace, ...] = ()
    satisfactions: Tuple[SourceRequirementSatisfaction, ...] = ()
    expiry_classifications: Tuple[Tuple[str, SourceExpiryClassification], ...] = ()
    proof_pruning_allowed: bool = False

    def with_trace(self, trace: SourceCompletionPropagationTrace) -> "SourceCompletionLedger":
        existing = next(
            (item for item in self.traces if item.event.event_id == trace.event.event_id),
            None,
        )
        traces = (
            tuple(
                item.merge(trace) if item.event.event_id == trace.event.event_id else item
                for item in self.traces
            )
            if existing is not None
            else self.traces + (trace,)
        )
        satisfaction = trace.event.satisfaction
        satisfactions = self.satisfactions
        if existing is None:
            satisfactions = tuple(
                item
                for item in self.satisfactions
                if item.requirement.identity_key != satisfaction.requirement.identity_key
            ) + (satisfaction,)
        return replace(self, traces=traces, satisfactions=satisfactions)

    def satisfaction_for(
        self, requirement: SemanticSourceRequirement
    ) -> Optional[SourceRequirementSatisfaction]:
        return next(
            (
                item
                for item in reversed(self.satisfactions)
                if item.requirement.identity_key == requirement.identity_key
            ),
            None,
        )


def source_state_hash(state_or_key: SpiderState | CanonicalStateKey) -> str:
    key = (
        state_or_key
        if isinstance(state_or_key, CanonicalStateKey)
        else canonical_state_key(state_or_key)
    )
    return hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]


def physical_source_identity(
    card: Card,
    *,
    dependency_id: str,
    copy_ordinal: int,
    zone: str,
    column: Optional[int],
    offset: Optional[int],
    face_up: bool,
    blocker_depth: int,
    consumed: bool = False,
    integrated: bool = False,
    foundation_removed: bool = False,
    provenance_id: Optional[str] = None,
) -> PhysicalSourceIdentity:
    provenance = provenance_id or f"{dependency_id}:copy:{max(1, copy_ordinal)}"
    return PhysicalSourceIdentity(
        card.suit,
        card.rank,
        provenance,
        zone,
        column,
        offset,
        face_up,
        blocker_depth,
        consumed,
        integrated,
        foundation_removed,
    )


def semantic_source_requirement(
    semantic_target_fingerprint: Tuple,
    dependency_id: str,
    card: Card,
    *,
    scope: SourceCompletionScope = SourceCompletionScope.BURIED_PREDICATE,
    copies_required: int = 1,
) -> SemanticSourceRequirement:
    suffix = {
        SourceCompletionScope.BURIED_PREDICATE: "buried",
        SourceCompletionScope.EXPOSED_BLOCKER_PREDICATE: "exposed-blocker",
        SourceCompletionScope.SEMANTIC_SOURCE_REQUIREMENT: "source",
        SourceCompletionScope.SOURCE_CHAIN: "chain",
    }[scope]
    return SemanticSourceRequirement(
        f"{dependency_id}:{suffix}",
        semantic_target_fingerprint,
        dependency_id,
        scope,
        card.suit,
        card.rank,
        max(1, copies_required),
    )


def source_completion_event(
    *,
    semantic_target_fingerprint: Tuple,
    dependency_id: str,
    original_dependency_type: str,
    fresh_dependency_type: Optional[str],
    physical_source: PhysicalSourceIdentity,
    requirement: SemanticSourceRequirement,
    state: SpiderState,
    actions: Sequence[Action],
    completion_class: str,
    source_depth_before: int,
    source_depth_after: int,
    exposed: bool,
    actionable: bool,
    consumed: bool,
    integrated: bool,
    evidence_provenance: Sequence[str],
) -> SourceCompletionEvent:
    key = canonical_state_key(state)
    state_hash = source_state_hash(key)
    satisfaction_state = (
        SourceRequirementSatisfactionState.INTEGRATED
        if integrated
        else SourceRequirementSatisfactionState.CONSUMED
        if consumed
        else SourceRequirementSatisfactionState.ACTIONABLE
        if actionable
        else SourceRequirementSatisfactionState.EXPOSED
        if exposed
        else SourceRequirementSatisfactionState.PARTIALLY_SATISFIED
    )
    satisfaction = SourceRequirementSatisfaction(
        requirement,
        satisfaction_state,
        (physical_source,),
        state_hash if satisfaction_state != SourceRequirementSatisfactionState.PARTIALLY_SATISFIED else None,
        state_hash,
        tuple(evidence_provenance),
        True,
    )
    event_id = hashlib.sha256(
        repr(
            (
                semantic_target_fingerprint,
                dependency_id,
                original_dependency_type,
                physical_source.identity_key,
                state_hash,
                satisfaction_state,
            )
        ).encode("utf-8")
    ).hexdigest()[:16]
    return SourceCompletionEvent(
        event_id,
        semantic_target_fingerprint,
        dependency_id,
        original_dependency_type,
        fresh_dependency_type,
        requirement.scope,
        physical_source,
        requirement,
        satisfaction,
        key,
        state_hash,
        tuple(actions),
        completion_class,
        source_depth_before,
        source_depth_after,
        exposed,
        actionable,
        consumed,
        integrated,
        tuple(evidence_provenance),
    )


def _matching_occurrences(state: SpiderState, requirement: SemanticSourceRequirement):
    result = []
    for column_index, column in enumerate(state.columns):
        for offset, card in enumerate(column.face_up):
            if (card.suit, card.rank) == (requirement.suit, requirement.rank):
                integrated = bool(
                    (offset > 0 and column.face_up[offset - 1].suit == card.suit
                     and column.face_up[offset - 1].rank - 1 == card.rank)
                    or (offset + 1 < len(column.face_up)
                        and column.face_up[offset + 1].suit == card.suit
                        and card.rank - 1 == column.face_up[offset + 1].rank)
                )
                result.append(("face_up", column_index, offset, True, 0, integrated))
        for offset, card in enumerate(column.face_down):
            if (card.suit, card.rank) == (requirement.suit, requirement.rank):
                depth = len(column.face_up) + len(column.face_down) - offset - 1
                result.append(("face_down", column_index, offset, False, depth, False))
    for foundation_index, sequence in enumerate(state.foundations):
        for offset, card in enumerate(sequence):
            if (card.suit, card.rank) == (requirement.suit, requirement.rank):
                result.append(("foundation", foundation_index, offset, True, 0, True))
    return tuple(result)


def reconcile_source_satisfaction(
    state: SpiderState,
    requirement: SemanticSourceRequirement,
    prior: Optional[SourceRequirementSatisfaction] = None,
    *,
    current_dependency_type: Optional[str] = None,
) -> SourceRequirementSatisfaction:
    """Reconstruct current satisfaction from exact state and semantic scope."""

    state_hash = source_state_hash(state)
    occurrences = _matching_occurrences(state, requirement)
    visible = tuple(item for item in occurrences if item[3])
    integrated = tuple(item for item in visible if item[5])
    required = requirement.copies_required
    if len(integrated) >= required:
        state_value = SourceRequirementSatisfactionState.INTEGRATED
        chosen = integrated[:required]
    elif len(visible) >= required:
        state_value = (
            SourceRequirementSatisfactionState.ACTIONABLE
            if current_dependency_type is None
            else SourceRequirementSatisfactionState.EXPOSED
            if current_dependency_type == "SOURCE_EXPOSED_BUT_BLOCKED"
            else SourceRequirementSatisfactionState.ACTIONABLE
        )
        chosen = visible[:required]
    elif visible:
        state_value = SourceRequirementSatisfactionState.PARTIALLY_SATISFIED
        chosen = visible
    else:
        state_value = SourceRequirementSatisfactionState.UNSATISFIED
        chosen = ()

    sources = tuple(
        physical_source_identity(
            Card(requirement.suit, requirement.rank),
            dependency_id=requirement.dependency_id,
            copy_ordinal=index + 1,
            zone=item[0],
            column=item[1],
            offset=item[2],
            face_up=item[3],
            blocker_depth=item[4],
            integrated=item[5],
            provenance_id=(
                prior.satisfying_sources[index].provenance_id
                if prior is not None and index < len(prior.satisfying_sources)
                else None
            ),
        )
        for index, item in enumerate(chosen)
    )
    preserved = bool(
        prior is None
        or _SATISFACTION_ORDER[state_value] >= _SATISFACTION_ORDER[prior.state]
        or prior.current_state_hash != state_hash
    )
    reopening = None
    if prior is not None and _SATISFACTION_ORDER[state_value] < _SATISFACTION_ORDER[prior.state]:
        reopening = (
            SourceRequirementReopeningReason.ANALYSIS_DEFECT
            if prior.current_state_hash == state_hash
            else SourceRequirementReopeningReason.SOURCE_BECAME_UNUSABLE
        )
    reassigned = bool(
        prior is not None
        and prior.satisfying_sources
        and sources
        and prior.satisfying_sources[0].location != sources[0].location
    )
    evidence = (
        f"fresh exact state contains {len(visible)} exposed and {len(integrated)} integrated matching copy/copies",
        f"copies_required={required}",
        "fresh exact state is authoritative; history has no proof authority",
    )
    return SourceRequirementSatisfaction(
        requirement,
        state_value,
        sources,
        (
            prior.first_satisfied_state_hash
            if prior is not None and prior.first_satisfied_state_hash is not None
            else state_hash
            if _SATISFACTION_ORDER[state_value] >= _SATISFACTION_ORDER[SourceRequirementSatisfactionState.EXPOSED]
            else None
        ),
        state_hash,
        evidence,
        preserved,
        reopening,
        reassigned,
    )


def classify_completion_loss(
    *,
    trace_completed: bool,
    successor_created: bool,
    controller_admitted: bool,
    metadata_present: bool,
    residual_preserved: bool,
    attribution_preserved: bool,
    strategically_trimmed: bool = False,
    legitimate_rescope: bool = False,
) -> Optional[SourceCompletionLossReason]:
    if not trace_completed:
        return None
    if strategically_trimmed or successor_created and not controller_admitted:
        return SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS
    if controller_admitted and not metadata_present:
        return SourceCompletionLossReason.CONTROLLER_PROPAGATION_LOSS
    if metadata_present and not attribution_preserved:
        return SourceCompletionLossReason.PHYSICAL_SOURCE_ATTRIBUTION_LOSS
    if metadata_present and not residual_preserved:
        return (
            SourceCompletionLossReason.PORTFOLIO_REANALYSIS_RESCOPING
            if legitimate_rescope
            else SourceCompletionLossReason.RESIDUAL_REOPENING
        )
    return None


def classify_source_expiry(
    *,
    completed_before_expiry: bool = False,
    made_progress: bool = False,
    resource_limited: bool = False,
    target_turnover: bool = False,
    attribution_lost: bool = False,
    lifecycle_terminated: bool = False,
    superseded: bool = False,
) -> SourceExpiryClassification:
    if completed_before_expiry:
        return SourceExpiryClassification.COMPLETED_BEFORE_EXPIRY
    if superseded:
        return SourceExpiryClassification.SUPERSEDED_EXPIRY
    if lifecycle_terminated:
        return SourceExpiryClassification.LIFECYCLE_EXPIRY
    if attribution_lost:
        return SourceExpiryClassification.ATTRIBUTION_LOSS_EXPIRY
    if target_turnover:
        return SourceExpiryClassification.TARGET_TURNOVER_EXPIRY
    if resource_limited or made_progress:
        return SourceExpiryClassification.RESOURCE_LIMIT_EXPIRY
    return SourceExpiryClassification.LEGITIMATE_NO_PROGRESS_EXPIRY
