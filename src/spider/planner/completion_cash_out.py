"""Bounded, proof-neutral cash-out continuity for structural completions.

An exact-TT-admitted state that contains a newly durable source completion is
allowed one ordinary strategic expansion in which the controller performs its
normal fresh analysis.  The opportunity is planning coverage only: it is not
a Spider state, never changes exact identity or proof pruning, carries no
unused tactical resource, and expires after the single expansion.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.planner.source_completion import (
    SourceCompletionEvent,
    SourceCompletionPropagationTrace,
    SourceCompletionStage,
    SourceRequirementSatisfactionState,
    reconcile_source_satisfaction,
    source_state_hash,
)
from spider.state_identity import CanonicalStateKey, canonical_state_key


class CompletionCashOutStatus(str, Enum):
    ADMITTED = "ADMITTED"
    QUALIFIED = "QUALIFIED"
    RESERVED = "RESERVED"
    EXPANDED = "EXPANDED"
    SPENT = "SPENT"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class CompletionCashOutDisposition(str, Enum):
    QUALIFIED = "QUALIFIED"
    REPRESENTATIVE_RESERVED = "REPRESENTATIVE_RESERVED"
    REPRESENTATIVE_EXPANDED = "REPRESENTATIVE_EXPANDED"
    CASH_OUT_SPENT = "CASH_OUT_SPENT"
    COMPLETION_ADMITTED_NOT_SELECTED = "COMPLETION_ADMITTED_NOT_SELECTED"
    EXACT_DUPLICATE_SUPPRESSED = "EXACT_DUPLICATE_SUPPRESSED"
    SUPERSEDED_BY_LOWER_G = "SUPERSEDED_BY_LOWER_G"
    INVALIDATED_BY_FRESH_FACT = "INVALIDATED_BY_FRESH_FACT"
    EXPIRED_BEFORE_EXPANSION = "EXPIRED_BEFORE_EXPANSION"
    ORDINARY_CONTINUATION = "ORDINARY_CONTINUATION"
    BRANCH_ABANDONED = "BRANCH_ABANDONED"


class CompletionHarvestKind(str, Enum):
    SOURCE_CONSUMED = "SOURCE_CONSUMED"
    SOURCE_INTEGRATED = "SOURCE_INTEGRATED"
    SAME_SUIT_CONSTRUCTION = "SAME_SUIT_CONSTRUCTION"
    DEPENDENCY_CHAIN_ADVANCE = "DEPENDENCY_CHAIN_ADVANCE"
    RECEIVER_UNLOCK = "RECEIVER_UNLOCK"
    WORKSPACE_UNLOCK = "WORKSPACE_UNLOCK"
    NEW_REVEAL = "NEW_REVEAL"
    TERMINAL_QUALIFICATION = "TERMINAL_QUALIFICATION"
    FOUNDATION_REMOVAL = "FOUNDATION_REMOVAL"
    EPOCH_PREPARATION = "EPOCH_PREPARATION"
    OTHER_NAMED_STRUCTURAL_HARVEST = "OTHER_NAMED_STRUCTURAL_HARVEST"
    NO_DOWNSTREAM_HARVEST = "NO_DOWNSTREAM_HARVEST"


@dataclass(frozen=True)
class CompletionStructuralMetrics:
    """Transparent ordering facts for qualifying completion states only."""

    corrected_g: int
    foundation_count: int
    permanent_same_suit_joins: int
    mixed_suit_boundaries: int
    source_completion_count: int
    source_actionable_count: int
    source_consumed_count: int
    source_integrated_count: int
    downstream_dependency_reduction: int
    receiver_unlocks: int
    workspace_columns: int
    face_down_count: int
    reveal_delta: int
    stock_count: int
    stock_timing_rank: int
    rehandling_debt: float
    terminal_readiness: int
    substantial_milestone_progress: int
    legal_mobility: int

    def ordering_key(self) -> Tuple:
        """Heuristic order with no magic completion bonus or proof authority."""

        return (
            -self.foundation_count,
            -self.terminal_readiness,
            -self.source_integrated_count,
            -self.source_consumed_count,
            -self.source_actionable_count,
            -self.downstream_dependency_reduction,
            -self.substantial_milestone_progress,
            -self.permanent_same_suit_joins,
            self.mixed_suit_boundaries,
            -self.receiver_unlocks,
            -self.workspace_columns,
            self.face_down_count,
            -self.reveal_delta,
            self.stock_timing_rank,
            self.rehandling_debt,
            -self.legal_mobility,
            self.corrected_g,
        )


@dataclass(frozen=True)
class CompletionCashOutOpportunity:
    opportunity_id: str
    exact_state_key: CanonicalStateKey
    exact_state_hash: str
    corrected_g: int
    events: Tuple[SourceCompletionEvent, ...]
    semantic_targets: Tuple[Tuple, ...]
    successor_family: str
    metrics: CompletionStructuralMetrics
    status: CompletionCashOutStatus = CompletionCashOutStatus.QUALIFIED
    representative_rank: Optional[int] = None
    competing_normal_state_hash: Optional[str] = None
    competing_normal_g: Optional[int] = None
    cash_out_spent: bool = False
    reason: str = "newly durable completion awaits one fresh strategic expansion"
    proof_pruning_allowed: bool = False

    @property
    def event_ids(self) -> Tuple[str, ...]:
        return tuple(item.event_id for item in self.events)

    @property
    def geometry_key(self) -> Tuple:
        return (
            self.exact_state_key,
            self.semantic_targets,
            tuple(
                sorted(
                    (
                        item.requirement.scope.value,
                        item.requirement.suit,
                        item.requirement.rank,
                    )
                    for item in self.events
                )
            ),
        )

    def eligible(self, spent_event_ids: Iterable[str] = ()) -> bool:
        spent = set(spent_event_ids)
        return bool(
            not self.cash_out_spent
            and self.status
            in {
                CompletionCashOutStatus.QUALIFIED,
                CompletionCashOutStatus.RESERVED,
            }
            and any(event_id not in spent for event_id in self.event_ids)
        )


@dataclass(frozen=True)
class CompletionHarvestAssessment:
    opportunity_id: str
    start_state_hash: str
    end_state_hash: str
    harvest_kinds: Tuple[CompletionHarvestKind, ...]
    source_consumed_event_ids: Tuple[str, ...]
    source_integrated_event_ids: Tuple[str, ...]
    permanent_join_delta: int
    mixed_boundary_reduction: int
    dependency_reduction: int
    receiver_unlocks: int
    workspace_delta: int
    reveal_delta: int
    foundation_delta: int
    downstream_successor_generated: bool
    downstream_successor_admitted: bool
    fresh_comparison: bool
    evidence: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    @property
    def meaningful(self) -> bool:
        return any(
            item != CompletionHarvestKind.NO_DOWNSTREAM_HARVEST
            for item in self.harvest_kinds
        )


@dataclass(frozen=True)
class CompletionCashOutTrace:
    opportunity_id: str
    event_ids: Tuple[str, ...]
    semantic_targets: Tuple[Tuple, ...]
    exact_state_key: CanonicalStateKey
    exact_state_hash: str
    corrected_g: int
    successor_family: str
    structural_metrics: CompletionStructuralMetrics
    qualifying_status: CompletionCashOutStatus
    representative_rank: Optional[int]
    competing_normal_state_hash: Optional[str]
    competing_normal_g: Optional[int]
    frontier_admitted: bool
    frontier_trimmed: bool
    selected_for_expansion: bool
    cash_out_spent: bool
    disposition: CompletionCashOutDisposition
    reason: str
    downstream_result: Tuple[CompletionHarvestKind, ...] = ()
    proof_pruning_allowed: bool = False

    def update(
        self,
        *,
        opportunity: Optional[CompletionCashOutOpportunity] = None,
        disposition: Optional[CompletionCashOutDisposition] = None,
        reason: Optional[str] = None,
        frontier_trimmed: Optional[bool] = None,
        selected_for_expansion: Optional[bool] = None,
        cash_out_spent: Optional[bool] = None,
        downstream_result: Optional[Sequence[CompletionHarvestKind]] = None,
    ) -> "CompletionCashOutTrace":
        current = opportunity
        return replace(
            self,
            qualifying_status=(current.status if current is not None else self.qualifying_status),
            representative_rank=(current.representative_rank if current is not None else self.representative_rank),
            competing_normal_state_hash=(
                current.competing_normal_state_hash
                if current is not None
                else self.competing_normal_state_hash
            ),
            competing_normal_g=(
                current.competing_normal_g
                if current is not None
                else self.competing_normal_g
            ),
            frontier_trimmed=(
                frontier_trimmed if frontier_trimmed is not None else self.frontier_trimmed
            ),
            selected_for_expansion=(
                selected_for_expansion
                if selected_for_expansion is not None
                else self.selected_for_expansion
            ),
            cash_out_spent=(
                cash_out_spent if cash_out_spent is not None else self.cash_out_spent
            ),
            disposition=disposition or self.disposition,
            reason=reason or self.reason,
            downstream_result=(
                tuple(downstream_result)
                if downstream_result is not None
                else self.downstream_result
            ),
        )


def qualifying_completion_events(
    state: SpiderState,
    traces: Sequence[SourceCompletionPropagationTrace],
    *,
    spent_event_ids: Iterable[str] = (),
) -> Tuple[SourceCompletionEvent, ...]:
    """Return strong, exact-state, newly admitted and unspent completions."""

    state_key = canonical_state_key(state)
    spent = set(spent_event_ids)
    result = []
    seen = set()
    for trace in traces:
        event = trace.event
        if event.exact_state_key != state_key:
            fresh = reconcile_source_satisfaction(
                state,
                event.requirement,
                event.satisfaction,
                current_dependency_type=event.fresh_dependency_type,
            )
            if not fresh.satisfied:
                continue
            physical = (
                fresh.satisfying_sources[0]
                if fresh.satisfying_sources
                else event.physical_source
            )
            event = replace(
                event,
                physical_source=physical,
                satisfaction=fresh,
                exact_state_key=state_key,
                exact_state_hash=source_state_hash(state_key),
                exposed=fresh.state
                in {
                    SourceRequirementSatisfactionState.EXPOSED,
                    SourceRequirementSatisfactionState.ACTIONABLE,
                    SourceRequirementSatisfactionState.CONSUMED,
                    SourceRequirementSatisfactionState.INTEGRATED,
                },
                actionable=fresh.state
                in {
                    SourceRequirementSatisfactionState.ACTIONABLE,
                    SourceRequirementSatisfactionState.CONSUMED,
                    SourceRequirementSatisfactionState.INTEGRATED,
                },
                consumed=fresh.state
                in {
                    SourceRequirementSatisfactionState.CONSUMED,
                    SourceRequirementSatisfactionState.INTEGRATED,
                },
                integrated=(
                    fresh.state == SourceRequirementSatisfactionState.INTEGRATED
                ),
                evidence_provenance=event.evidence_provenance
                + (
                    "fresh exact admitted state preserves the durable completion",
                ),
            )
        admitted = bool(
            trace.controller_admitted
            or SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION in trace.stages
        )
        strong = bool(
            event.exposed
            or event.actionable
            or event.consumed
            or event.integrated
            or event.requirement.scope.value == "SOURCE_CHAIN"
        )
        valid = event.satisfaction.state not in {
            SourceRequirementSatisfactionState.INVALIDATED,
            SourceRequirementSatisfactionState.SUPERSEDED,
            SourceRequirementSatisfactionState.UNSATISFIED,
        }
        if (
            not admitted
            or not strong
            or not valid
            or event.event_id in spent
            or event.event_id in seen
        ):
            continue
        seen.add(event.event_id)
        result.append(event)
    return tuple(result)


def make_completion_cash_out_opportunity(
    state: SpiderState,
    *,
    corrected_g: int,
    traces: Sequence[SourceCompletionPropagationTrace],
    successor_family: str,
    metrics: CompletionStructuralMetrics,
    exact_tt_admitted: bool,
    independently_replay_verified: bool,
    spent_event_ids: Iterable[str] = (),
) -> Optional[CompletionCashOutOpportunity]:
    """Qualify only after replay and exact TT admission."""

    if not exact_tt_admitted or not independently_replay_verified:
        return None
    events = qualifying_completion_events(
        state, traces, spent_event_ids=spent_event_ids
    )
    if not events:
        return None
    key = canonical_state_key(state)
    event_ids = tuple(sorted(item.event_id for item in events))
    opportunity_id = hashlib.sha256(
        repr((key, event_ids)).encode("utf-8")
    ).hexdigest()[:16]
    targets = tuple(dict.fromkeys(item.semantic_target_fingerprint for item in events))
    return CompletionCashOutOpportunity(
        opportunity_id,
        key,
        source_state_hash(key),
        corrected_g,
        events,
        targets,
        successor_family,
        metrics,
    )


def rank_completion_opportunities(
    opportunities: Sequence[CompletionCashOutOpportunity],
    *,
    spent_event_ids: Iterable[str] = (),
) -> Tuple[CompletionCashOutOpportunity, ...]:
    """Deduplicate and rank qualifying representatives by transparent facts."""

    spent = set(spent_event_ids)
    best_by_geometry = {}
    for opportunity in opportunities:
        if not opportunity.eligible(spent):
            continue
        previous = best_by_geometry.get(opportunity.geometry_key)
        if previous is None or (
            opportunity.metrics.ordering_key(),
            opportunity.corrected_g,
            opportunity.opportunity_id,
        ) < (
            previous.metrics.ordering_key(),
            previous.corrected_g,
            previous.opportunity_id,
        ):
            best_by_geometry[opportunity.geometry_key] = opportunity
    ranked = sorted(
        best_by_geometry.values(),
        key=lambda item: (
            item.metrics.ordering_key(),
            item.corrected_g,
            item.exact_state_hash,
            item.opportunity_id,
        ),
    )
    return tuple(
        replace(item, representative_rank=index + 1)
        for index, item in enumerate(ranked)
    )


def _same_suit_joins(state: SpiderState) -> int:
    return sum(
        lower.suit == upper.suit and lower.rank == upper.rank + 1
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )


def _mixed_boundaries(state: SpiderState) -> int:
    return sum(
        lower.rank == upper.rank + 1 and lower.suit != upper.suit
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )


def assess_completion_harvest(
    opportunity: CompletionCashOutOpportunity,
    start_state: SpiderState,
    end_state: SpiderState,
    *,
    downstream_successor_generated: bool,
    downstream_successor_admitted: bool,
    dependency_chain_advanced: bool = False,
    receiver_unlocked: bool = False,
    terminal_qualified: bool = False,
    epoch_prepared: bool = False,
    other_named_harvest: bool = False,
    action_is_deal: bool = False,
) -> CompletionHarvestAssessment:
    """Compare the completion state with a fresh descendant consequence."""

    kinds = []
    consumed = []
    integrated = []
    for event in opportunity.events:
        start = reconcile_source_satisfaction(
            start_state,
            event.requirement,
            event.satisfaction,
            current_dependency_type=event.fresh_dependency_type,
        )
        end = reconcile_source_satisfaction(
            end_state,
            event.requirement,
            start,
            current_dependency_type=None,
        )
        newly_integrated = bool(
            end.state == SourceRequirementSatisfactionState.INTEGRATED
            and start.state != SourceRequirementSatisfactionState.INTEGRATED
        )
        newly_consumed = bool(
            newly_integrated
            or (
                end.state == SourceRequirementSatisfactionState.CONSUMED
                and start.state
                not in {
                    SourceRequirementSatisfactionState.CONSUMED,
                    SourceRequirementSatisfactionState.INTEGRATED,
                }
            )
        )
        if newly_consumed:
            consumed.append(event.event_id)
        if newly_integrated:
            integrated.append(event.event_id)

    start_joins = _same_suit_joins(start_state)
    end_joins = _same_suit_joins(end_state)
    start_mixed = _mixed_boundaries(start_state)
    end_mixed = _mixed_boundaries(end_state)
    join_delta = end_joins - start_joins
    mixed_reduction = start_mixed - end_mixed
    workspace_delta = sum(column.is_empty() for column in end_state.columns) - sum(
        column.is_empty() for column in start_state.columns
    )
    reveal_delta = sum(len(column.face_down) for column in start_state.columns) - sum(
        len(column.face_down) for column in end_state.columns
    )
    foundation_delta = len(end_state.foundations) - len(start_state.foundations)

    if consumed:
        kinds.append(CompletionHarvestKind.SOURCE_CONSUMED)
    if integrated:
        kinds.append(CompletionHarvestKind.SOURCE_INTEGRATED)
    if join_delta > 0:
        kinds.append(CompletionHarvestKind.SAME_SUIT_CONSTRUCTION)
    if dependency_chain_advanced:
        kinds.append(CompletionHarvestKind.DEPENDENCY_CHAIN_ADVANCE)
    if receiver_unlocked:
        kinds.append(CompletionHarvestKind.RECEIVER_UNLOCK)
    if workspace_delta > 0:
        kinds.append(CompletionHarvestKind.WORKSPACE_UNLOCK)
    if reveal_delta > 0:
        kinds.append(CompletionHarvestKind.NEW_REVEAL)
    if terminal_qualified:
        kinds.append(CompletionHarvestKind.TERMINAL_QUALIFICATION)
    if foundation_delta > 0:
        kinds.append(CompletionHarvestKind.FOUNDATION_REMOVAL)
    if epoch_prepared and not action_is_deal:
        kinds.append(CompletionHarvestKind.EPOCH_PREPARATION)
    if other_named_harvest:
        kinds.append(CompletionHarvestKind.OTHER_NAMED_STRUCTURAL_HARVEST)
    if not kinds:
        kinds.append(CompletionHarvestKind.NO_DOWNSTREAM_HARVEST)
    kinds = list(dict.fromkeys(kinds))
    evidence = (
        "fresh descendant is compared against the post-completion starting state",
        f"source_consumed={len(consumed)} source_integrated={len(integrated)}",
        f"stable_join_delta={join_delta} mixed_boundary_reduction={mixed_reduction}",
        f"workspace_delta={workspace_delta} reveal_delta={reveal_delta}",
        f"foundation_delta={foundation_delta}",
        "the original exposure is not counted as downstream harvest",
        "Deal itself is never completion harvest",
    )
    return CompletionHarvestAssessment(
        opportunity.opportunity_id,
        source_state_hash(start_state),
        source_state_hash(end_state),
        tuple(kinds),
        tuple(consumed),
        tuple(integrated),
        join_delta,
        mixed_reduction,
        int(dependency_chain_advanced),
        int(receiver_unlocked),
        workspace_delta,
        reveal_delta,
        foundation_delta,
        downstream_successor_generated,
        downstream_successor_admitted,
        True,
        evidence,
    )


def combine_completion_harvest(
    opportunity: CompletionCashOutOpportunity,
    assessments: Sequence[CompletionHarvestAssessment],
) -> CompletionHarvestAssessment:
    """Collapse one cash-out expansion's descendants into one bounded result."""

    if not assessments:
        return CompletionHarvestAssessment(
            opportunity.opportunity_id,
            opportunity.exact_state_hash,
            opportunity.exact_state_hash,
            (CompletionHarvestKind.NO_DOWNSTREAM_HARVEST,),
            (),
            (),
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            False,
            False,
            True,
            (
                "fresh cash-out analysis generated no replay-valid downstream successor",
            ),
        )
    preferred = tuple(item for item in assessments if item.downstream_successor_admitted)
    rows = preferred or tuple(assessments)
    kinds = tuple(
        dict.fromkeys(
            kind
            for item in rows
            for kind in item.harvest_kinds
            if kind != CompletionHarvestKind.NO_DOWNSTREAM_HARVEST
        )
    )
    if not kinds:
        kinds = (CompletionHarvestKind.NO_DOWNSTREAM_HARVEST,)
    return CompletionHarvestAssessment(
        opportunity.opportunity_id,
        opportunity.exact_state_hash,
        rows[0].end_state_hash,
        kinds,
        tuple(dict.fromkeys(e for item in rows for e in item.source_consumed_event_ids)),
        tuple(dict.fromkeys(e for item in rows for e in item.source_integrated_event_ids)),
        max(item.permanent_join_delta for item in rows),
        max(item.mixed_boundary_reduction for item in rows),
        max(item.dependency_reduction for item in rows),
        max(item.receiver_unlocks for item in rows),
        max(item.workspace_delta for item in rows),
        max(item.reveal_delta for item in rows),
        max(item.foundation_delta for item in rows),
        any(item.downstream_successor_generated for item in rows),
        any(item.downstream_successor_admitted for item in rows),
        True,
        tuple(dict.fromkeys(e for item in rows for e in item.evidence)),
    )


def reconstruct_completion_satisfactions(
    state: SpiderState,
    traces: Sequence[SourceCompletionPropagationTrace],
):
    """Rebuild proof-neutral source facts on a cheaper identical exact state."""

    return tuple(
        reconcile_source_satisfaction(
            state,
            trace.event.requirement,
            trace.event.satisfaction,
            current_dependency_type=trace.event.fresh_dependency_type,
        )
        for trace in traces
    )
