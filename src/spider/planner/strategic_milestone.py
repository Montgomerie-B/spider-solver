"""Bounded strategic milestones built from fresh Spider structure.

Milestones are continuation and ordering context.  They deliberately do not
participate in canonical state identity or admissible proof pruning.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Mapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathSummary,
    CampaignDependencyGraph,
    CampaignDependencyType,
)
from spider.planner.epoch_progression import (
    CampaignEpochAvailability,
    MilestoneEpochFeasibility,
    milestone_epoch_feasibility,
)
from spider.planner.foundation_campaign import FoundationCampaign
from spider.planner.structural_construction import (
    ConstructionDisposition,
    StructuralConstructionAnalysis,
)
from spider.state_identity import CanonicalStateKey, canonical_state_key


class StrategicMilestoneKind(str, Enum):
    INTERVAL_ASSEMBLY = "INTERVAL_ASSEMBLY"
    SOURCE_CHAIN = "SOURCE_CHAIN"
    RECEIVER_GEOMETRY = "RECEIVER_GEOMETRY"
    SUPPLY_INTEGRATION = "SUPPLY_INTEGRATION"
    OVERLAY_CLEARANCE = "OVERLAY_CLEARANCE"
    WORKSPACE_LIFECYCLE = "WORKSPACE_LIFECYCLE"
    RUN_CONSTRUCTION = "RUN_CONSTRUCTION"
    PRE_DEAL_PREPARATION = "PRE_DEAL_PREPARATION"
    EPOCH_TRANSITION = "EPOCH_TRANSITION"
    TERMINAL_QUALIFICATION = "TERMINAL_QUALIFICATION"
    FOUNDATION_REMOVAL = "FOUNDATION_REMOVAL"


class StrategicMilestoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ADVANCED = "ADVANCED"
    ACHIEVED = "ACHIEVED"
    REPLANNED = "REPLANNED"
    BLOCKED_CURRENT_EPOCH = "BLOCKED_CURRENT_EPOCH"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    BOUNDED_MISS = "BOUNDED_MISS"


class MilestoneOutcomeKind(str, Enum):
    """Economic meaning of a completed milestone attempt.

    A primitive result and a stock transition checkpoint are intentionally
    separate from a substantial structural milestone.  Search ordering may
    use all four classes, but only the latter two represent durable campaign
    harvest.
    """

    PRIMITIVE_RESULT = "PRIMITIVE_RESULT"
    TRANSITION_CHECKPOINT = "TRANSITION_CHECKPOINT"
    SUBSTANTIAL_STRUCTURAL_MILESTONE = "SUBSTANTIAL_STRUCTURAL_MILESTONE"
    FOUNDATION = "FOUNDATION"


class MilestonePredicateKind(str, Enum):
    SAME_SUIT_INTERVAL = "SAME_SUIT_INTERVAL"
    DEPENDENCIES_CLOSED = "DEPENDENCIES_CLOSED"
    RECEIVER_AVAILABLE = "RECEIVER_AVAILABLE"
    SUPPLY_INTEGRATED = "SUPPLY_INTEGRATED"
    OVERLAY_REMOVED = "OVERLAY_REMOVED"
    WORKSPACE_USED_RECOVERED = "WORKSPACE_USED_RECOVERED"
    DURABLE_RUN = "DURABLE_RUN"
    PRE_DEAL_WORK_COMPLETE = "PRE_DEAL_WORK_COMPLETE"
    STOCK_EPOCH_REACHED = "STOCK_EPOCH_REACHED"
    TERMINAL_QUALIFIED = "TERMINAL_QUALIFIED"
    FOUNDATION_COUNT = "FOUNDATION_COUNT"


@dataclass(frozen=True)
class StrategicMilestonePrerequisite:
    prerequisite_id: str
    description: str
    satisfied: bool = False


@dataclass(frozen=True)
class MilestoneTargetPredicate:
    kind: MilestonePredicateKind
    description: str
    suit: Optional[str] = None
    high_rank: Optional[int] = None
    low_rank: Optional[int] = None
    minimum_run_length: Optional[int] = None
    dependency_ids: Tuple[str, ...] = ()
    target_stock_epoch: Optional[int] = None
    target_foundation_count: Optional[int] = None
    workspace_requires_use: bool = False
    workspace_requires_recovery: bool = False


@dataclass(frozen=True)
class MilestoneTargetIdentity:
    """Coordinate-free identity for a strategic objective across fresh states."""

    objective_id: str
    campaign_id: Optional[str]
    kind: StrategicMilestoneKind
    predicate_kind: MilestonePredicateKind
    suit: Optional[str]
    required_ranks: Tuple[int, ...]
    dependency_outcomes: Tuple[str, ...]
    completion_condition: str
    proof_pruning_allowed: bool = False

    @property
    def fingerprint(self) -> Tuple:
        return (
            self.objective_id,
            self.campaign_id,
            self.kind,
            self.predicate_kind,
            self.suit,
            self.required_ranks,
            self.dependency_outcomes,
            self.completion_condition,
        )


@dataclass(frozen=True)
class StrategicMilestoneProgress:
    satisfied_units: int
    total_units: int
    remaining_dependencies: Tuple[str, ...] = ()
    assembled_ranks: Tuple[int, ...] = ()
    primitive_steps: int = 0
    corrected_paid_cost: int = 0
    tactical_nodes: int = 0
    workspace_created: bool = False
    workspace_used: bool = False
    workspace_recovered_or_replaced: bool = False
    terminal_qualified: bool = False
    foundation_delta: int = 0
    fresh_state_hash: str = ""

    @property
    def complete(self) -> bool:
        return self.total_units > 0 and self.satisfied_units >= self.total_units


@dataclass(frozen=True)
class StrategicMilestone:
    milestone_id: str
    starting_state: CanonicalStateKey
    objective_id: str
    campaign_id: Optional[str]
    kind: StrategicMilestoneKind
    target: MilestoneTargetPredicate
    suit: Optional[str]
    ranks: Tuple[int, ...]
    fragments: Tuple[str, ...]
    prerequisites: Tuple[StrategicMilestonePrerequisite, ...]
    progress: StrategicMilestoneProgress
    estimated_paid_cost: int
    max_primitive_steps: int
    max_strategic_expansions: int
    max_elapsed_seconds: float
    max_tactical_nodes: int
    completion_condition: str
    invalidation_condition: str
    epoch_feasibility: Optional[MilestoneEpochFeasibility]
    status: StrategicMilestoneStatus = StrategicMilestoneStatus.ACTIVE
    created_depth: int = 0
    created_elapsed_seconds: float = 0.0
    proof_pruning_allowed: bool = False
    target_identity: Optional[MilestoneTargetIdentity] = None

    @property
    def same_target_key(self) -> Tuple:
        return milestone_target_identity(self).fingerprint

    def ordering_key(self) -> Tuple:
        blocked = self.status == StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH
        return (
            blocked,
            0 if self.kind == StrategicMilestoneKind.FOUNDATION_REMOVAL else 1,
            (
                0
                if milestone_is_substantial(self)
                and self.kind != StrategicMilestoneKind.TERMINAL_QUALIFICATION
                else 3
                if self.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION
                else 2
            ),
            -self.progress.satisfied_units,
            self.progress.total_units,
            self.estimated_paid_cost,
            self.kind.value,
            self.milestone_id,
        )


@dataclass(frozen=True)
class StrategicMilestonePlan:
    primary: Optional[StrategicMilestone]
    alternates: Tuple[StrategicMilestone, ...]
    raw_fallback_available: bool = True
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class StrategicMilestonePortfolio:
    milestones: Tuple[StrategicMilestone, ...]
    plan: StrategicMilestonePlan
    generated_by_kind: Tuple[Tuple[str, int], ...]
    proof_pruning_allowed: bool = False

    def matching(self, milestone: StrategicMilestone) -> Optional[StrategicMilestone]:
        return next(
            (item for item in self.milestones if item.same_target_key == milestone.same_target_key),
            None,
        )


@dataclass(frozen=True)
class MilestoneRealizationResult:
    milestone: StrategicMilestone
    status: StrategicMilestoneStatus
    actions: Tuple[Tuple, ...]
    corrected_paid_cost: int
    end_state: SpiderState
    primitive_steps: int
    tactical_nodes: int
    elapsed_seconds: float
    independent_replay_verified: bool
    fresh_reanalyses: int
    harvest_events: Tuple[str, ...]
    reason: str
    proof_pruning_allowed: bool = False
    outcome_kind: MilestoneOutcomeKind = MilestoneOutcomeKind.PRIMITIVE_RESULT
    target_identity: Optional[MilestoneTargetIdentity] = None
    residual_timeline: Tuple[str, ...] = ()
    blocker_transitions: Tuple[str, ...] = ()
    closure_completion_timeline: Tuple[str, ...] = ()
    closure_target_timeline: Tuple[str, ...] = ()
    advanced_closure_steps: int = 0
    advanced_fallbacks: int = 0
    same_target_continuations: int = 0
    persisted_target_completed: bool = False
    restore_replace_obligations: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MilestoneConversionLedger:
    results: Tuple[MilestoneRealizationResult, ...] = ()
    proof_pruning_allowed: bool = False

    def add(self, result: MilestoneRealizationResult) -> "MilestoneConversionLedger":
        return MilestoneConversionLedger(self.results + (result,))

    @property
    def achieved(self) -> int:
        return sum(item.status == StrategicMilestoneStatus.ACHIEVED for item in self.results)


def _stable_id(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]


def semantic_dependency_outcome(dependency_id: str) -> str:
    """Remove volatile tableau coordinates while retaining logical purpose."""

    value = re.sub(r":c\d+(?::|$)", ":", dependency_id)
    value = re.sub(r"column[=:]?\d+", "column", value, flags=re.IGNORECASE)
    return value.rstrip(":")


def milestone_target_identity(milestone: StrategicMilestone) -> MilestoneTargetIdentity:
    if milestone.target_identity is not None:
        return milestone.target_identity
    ranks = milestone.ranks
    if milestone.target.high_rank is not None and milestone.target.low_rank is not None:
        ranks = tuple(range(milestone.target.high_rank, milestone.target.low_rank - 1, -1))
    outcomes = tuple(
        sorted({semantic_dependency_outcome(item) for item in milestone.target.dependency_ids})
    )
    return MilestoneTargetIdentity(
        objective_id=milestone.objective_id,
        campaign_id=milestone.campaign_id,
        kind=milestone.kind,
        predicate_kind=milestone.target.kind,
        suit=milestone.suit or milestone.target.suit,
        required_ranks=ranks,
        dependency_outcomes=outcomes,
        completion_condition=milestone.completion_condition,
    )


def milestone_is_substantial(milestone: StrategicMilestone) -> bool:
    """Return whether the target describes a coherent durable endpoint."""

    if milestone.kind == StrategicMilestoneKind.INTERVAL_ASSEMBLY:
        return len(milestone_target_identity(milestone).required_ranks) >= 2
    if milestone.kind == StrategicMilestoneKind.SOURCE_CHAIN:
        return max(
            milestone.progress.total_units,
            len(milestone_target_identity(milestone).dependency_outcomes),
        ) >= 2
    if milestone.kind == StrategicMilestoneKind.RECEIVER_GEOMETRY:
        return milestone.progress.total_units >= 2
    return milestone.kind in {
        StrategicMilestoneKind.SUPPLY_INTEGRATION,
        StrategicMilestoneKind.WORKSPACE_LIFECYCLE,
        StrategicMilestoneKind.TERMINAL_QUALIFICATION,
        StrategicMilestoneKind.FOUNDATION_REMOVAL,
    }


def classify_milestone_outcome(
    milestone: StrategicMilestone,
    status: StrategicMilestoneStatus,
) -> MilestoneOutcomeKind:
    if milestone.kind == StrategicMilestoneKind.EPOCH_TRANSITION:
        return MilestoneOutcomeKind.TRANSITION_CHECKPOINT
    if status != StrategicMilestoneStatus.ACHIEVED:
        return MilestoneOutcomeKind.PRIMITIVE_RESULT
    if milestone.kind == StrategicMilestoneKind.FOUNDATION_REMOVAL:
        return MilestoneOutcomeKind.FOUNDATION
    if milestone_is_substantial(milestone):
        return MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE
    return MilestoneOutcomeKind.PRIMITIVE_RESULT


def _same_suit_runs(state: SpiderState, suit: str) -> Tuple[Tuple[int, ...], ...]:
    runs = []
    for column in state.columns:
        current = []
        for card in column.face_up:
            if card.suit != suit:
                if current:
                    runs.append(tuple(current))
                    current = []
                continue
            if current and current[-1] - 1 != card.rank:
                runs.append(tuple(current))
                current = []
            current.append(card.rank)
        if current:
            runs.append(tuple(current))
    return tuple(runs)


def interval_is_assembled(state: SpiderState, suit: str, high: int, low: int) -> bool:
    required = tuple(range(high, low - 1, -1))
    if any(tuple(run[i : i + len(required)]) == required for run in _same_suit_runs(state, suit) for i in range(max(0, len(run) - len(required) + 1))):
        return True
    return any(foundation and foundation[0].suit == suit for foundation in state.foundations)


def _interval_progress(state: SpiderState, suit: str, high: int, low: int) -> Tuple[int, Tuple[int, ...]]:
    required = set(range(high, low - 1, -1))
    if any(foundation and foundation[0].suit == suit for foundation in state.foundations):
        assembled = tuple(range(high, low - 1, -1))
        return len(assembled), assembled
    best: set[int] = set()
    for run in _same_suit_runs(state, suit):
        covered = required.intersection(run)
        if len(covered) > len(best):
            best = covered
    return len(best), tuple(sorted(best, reverse=True))


def evaluate_milestone_progress(
    state: SpiderState,
    milestone: StrategicMilestone,
    *,
    remaining_dependencies: Sequence[str] = (),
    terminal_qualified: bool = False,
    workspace_created: Optional[bool] = None,
    workspace_used: Optional[bool] = None,
    workspace_recovered_or_replaced: Optional[bool] = None,
) -> StrategicMilestoneProgress:
    target = milestone.target
    old = milestone.progress
    satisfied = 0
    total = max(1, old.total_units)
    assembled = old.assembled_ranks
    remaining = tuple(remaining_dependencies)
    if target.kind == MilestonePredicateKind.SAME_SUIT_INTERVAL:
        assert target.suit and target.high_rank is not None and target.low_rank is not None
        satisfied, assembled = _interval_progress(state, target.suit, target.high_rank, target.low_rank)
        total = target.high_rank - target.low_rank + 1
    elif target.kind == MilestonePredicateKind.DURABLE_RUN:
        assert target.suit and target.minimum_run_length
        longest = max((len(run) for run in _same_suit_runs(state, target.suit)), default=0)
        satisfied, total = min(longest, target.minimum_run_length), target.minimum_run_length
    elif target.kind in (
        MilestonePredicateKind.DEPENDENCIES_CLOSED,
        MilestonePredicateKind.RECEIVER_AVAILABLE,
        MilestonePredicateKind.SUPPLY_INTEGRATED,
        MilestonePredicateKind.OVERLAY_REMOVED,
    ):
        expected = set(target.dependency_ids)
        remaining_set = expected.intersection(remaining)
        total = max(1, len(expected))
        satisfied = total - len(remaining_set)
        remaining = tuple(sorted(remaining_set))
    elif target.kind == MilestonePredicateKind.WORKSPACE_USED_RECOVERED:
        created = old.workspace_created if workspace_created is None else workspace_created
        used = old.workspace_used if workspace_used is None else workspace_used
        recovered = old.workspace_recovered_or_replaced if workspace_recovered_or_replaced is None else workspace_recovered_or_replaced
        required = (created, used) + ((recovered,) if target.workspace_requires_recovery else ())
        satisfied, total = sum(required), len(required)
    elif target.kind == MilestonePredicateKind.STOCK_EPOCH_REACHED:
        current = 5 - len(state.stock) // 10
        total = max(1, int(target.target_stock_epoch or current))
        satisfied = min(current, total)
    elif target.kind == MilestonePredicateKind.TERMINAL_QUALIFIED:
        satisfied, total = int(terminal_qualified), 1
    elif target.kind == MilestonePredicateKind.FOUNDATION_COUNT:
        total = int(target.target_foundation_count or 1)
        satisfied = min(len(state.foundations), total)
    elif target.kind == MilestonePredicateKind.PRE_DEAL_WORK_COMPLETE:
        satisfied, total = (old.satisfied_units, total)
    return replace(
        old,
        satisfied_units=satisfied,
        total_units=total,
        remaining_dependencies=remaining,
        assembled_ranks=assembled,
        workspace_created=(old.workspace_created if workspace_created is None else workspace_created),
        workspace_used=(old.workspace_used if workspace_used is None else workspace_used),
        workspace_recovered_or_replaced=(old.workspace_recovered_or_replaced if workspace_recovered_or_replaced is None else workspace_recovered_or_replaced),
        terminal_qualified=terminal_qualified,
        fresh_state_hash=_stable_id(canonical_state_key(state)),
    )


def refresh_milestone(
    state: SpiderState,
    milestone: StrategicMilestone,
    *,
    matching_fresh: Optional[StrategicMilestone],
    depth: int,
    elapsed_seconds: float,
    remaining_dependencies: Sequence[str] = (),
    terminal_qualified: bool = False,
) -> StrategicMilestone:
    if matching_fresh is None:
        return replace(milestone, status=StrategicMilestoneStatus.INVALIDATED)
    if depth - milestone.created_depth >= milestone.max_strategic_expansions:
        return replace(milestone, status=StrategicMilestoneStatus.EXPIRED)
    if elapsed_seconds - milestone.created_elapsed_seconds >= milestone.max_elapsed_seconds:
        return replace(milestone, status=StrategicMilestoneStatus.EXPIRED)
    progress = evaluate_milestone_progress(
        state,
        milestone,
        remaining_dependencies=remaining_dependencies,
        terminal_qualified=terminal_qualified,
    )
    if progress.complete:
        status = StrategicMilestoneStatus.ACHIEVED
    elif milestone.epoch_feasibility is not None and not milestone.epoch_feasibility.feasible_now:
        status = StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH
    elif progress.satisfied_units > milestone.progress.satisfied_units:
        status = StrategicMilestoneStatus.ADVANCED
    else:
        status = StrategicMilestoneStatus.ACTIVE
    return replace(milestone, progress=progress, status=status)


def derive_strategic_milestones(
    state: SpiderState,
    campaigns: Sequence[FoundationCampaign],
    graphs: Sequence[CampaignDependencyGraph],
    critical_paths: Sequence[CampaignCriticalPathSummary],
    construction: Optional[StructuralConstructionAnalysis],
    availability: Mapping[str, CampaignEpochAvailability],
    *,
    created_depth: int = 0,
    created_elapsed_seconds: float = 0.0,
    maximum: int = 8,
) -> StrategicMilestonePortfolio:
    state_key = canonical_state_key(state)
    campaigns_by_id = {item.label: item for item in campaigns}
    summaries = {item.campaign_id: item for item in critical_paths}
    milestones = []
    for graph in graphs:
        campaign = campaigns_by_id.get(graph.campaign_id)
        if campaign is None:
            continue
        summary = summaries.get(graph.campaign_id)
        intervals = [item for item in graph.dependencies if item.kind == CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL and item.rank_interval]
        for dependency in intervals[:1]:
            high, low = dependency.rank_interval or (13, 1)
            ranks = tuple(range(high, low - 1, -1))
            mid = _stable_id(state_key, graph.campaign_id, "interval", high, low)
            feasibility = milestone_epoch_feasibility(mid, availability[graph.campaign_id], ranks=ranks)
            progress_count, assembled = _interval_progress(state, campaign.suit, high, low)
            milestones.append(StrategicMilestone(
                mid, state_key, graph.campaign_id, graph.campaign_id,
                StrategicMilestoneKind.INTERVAL_ASSEMBLY,
                MilestoneTargetPredicate(MilestonePredicateKind.SAME_SUIT_INTERVAL, f"assemble same-suit {high}-{low}", campaign.suit, high, low),
                campaign.suit, ranks, tuple(fragment.column.__str__() for fragment in campaign.current_same_suit_fragments),
                tuple(StrategicMilestonePrerequisite(item, item) for item in dependency.prerequisites),
                StrategicMilestoneProgress(progress_count, len(ranks), dependency.prerequisites, assembled, fresh_state_hash=_stable_id(state_key)),
                min(8, max(1, len(ranks))), 4, 3, 4.0, 12_000,
                f"one contiguous {campaign.suit} run covers {high} through {low}",
                "fresh analysis removes or economically supersedes the required interval",
                feasibility,
                StrategicMilestoneStatus.ACTIVE if feasibility.feasible_now else StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH,
                created_depth, created_elapsed_seconds,
            ))
        all_chain_ids = tuple(
            item.dependency_id
            for item in graph.dependencies
            if item.kind not in (
                CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
                CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
            )
        )
        critical_ids = tuple(
            item.dependency_id
            for item in (summary.entries if summary is not None else ())
            if item.dependency_id in all_chain_ids
        )
        chain_ids = tuple(dict.fromkeys(critical_ids + all_chain_ids))[:4]
        if chain_ids:
            kind = StrategicMilestoneKind.SOURCE_CHAIN
            if summary and summary.workspace_required:
                kind = StrategicMilestoneKind.WORKSPACE_LIFECYCLE
            elif summary and summary.supplied_asset_waiting:
                kind = StrategicMilestoneKind.SUPPLY_INTEGRATION
            elif summary and summary.overlay_present:
                kind = StrategicMilestoneKind.OVERLAY_CLEARANCE
            mid = _stable_id(state_key, graph.campaign_id, kind.value, chain_ids)
            target_kind = {
                StrategicMilestoneKind.WORKSPACE_LIFECYCLE: MilestonePredicateKind.WORKSPACE_USED_RECOVERED,
                StrategicMilestoneKind.SUPPLY_INTEGRATION: MilestonePredicateKind.SUPPLY_INTEGRATED,
                StrategicMilestoneKind.OVERLAY_CLEARANCE: MilestonePredicateKind.OVERLAY_REMOVED,
            }.get(kind, MilestonePredicateKind.DEPENDENCIES_CLOSED)
            target_ids = chain_ids if target_kind != MilestonePredicateKind.WORKSPACE_USED_RECOVERED else ()
            target = MilestoneTargetPredicate(target_kind, f"close prerequisite chain for {graph.campaign_id}", campaign.suit, dependency_ids=target_ids, workspace_requires_use=True, workspace_requires_recovery=True)
            milestones.append(StrategicMilestone(
                mid, state_key, graph.campaign_id, graph.campaign_id, kind, target,
                campaign.suit, (), (), tuple(StrategicMilestonePrerequisite(item, item) for item in chain_ids),
                StrategicMilestoneProgress(0, 3 if kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE else len(chain_ids), chain_ids, fresh_state_hash=_stable_id(state_key)),
                min(8, max(1, len(chain_ids))), 4, 3, 4.0, 12_000,
                "fresh dependency graph no longer contains the selected chain",
                "fresh graph contradicts the target or a cheaper same-target assignment dominates",
                milestone_epoch_feasibility(mid, availability[graph.campaign_id]),
                StrategicMilestoneStatus.ACTIVE, created_depth, created_elapsed_seconds,
            ))
            family_specs = (
                (
                    StrategicMilestoneKind.RECEIVER_GEOMETRY,
                    MilestonePredicateKind.RECEIVER_AVAILABLE,
                    tuple(
                        dep.dependency_id for dep in graph.dependencies
                        if dep.kind in (
                            CampaignDependencyType.RECEIVER_MISSING,
                            CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
                        )
                    ),
                ),
                (
                    StrategicMilestoneKind.SUPPLY_INTEGRATION,
                    MilestonePredicateKind.SUPPLY_INTEGRATED,
                    tuple(dep.dependency_id for dep in graph.dependencies if dep.kind == CampaignDependencyType.SUPPLIED_NOT_CONSUMED),
                ),
                (
                    StrategicMilestoneKind.OVERLAY_CLEARANCE,
                    MilestonePredicateKind.OVERLAY_REMOVED,
                    tuple(dep.dependency_id for dep in graph.dependencies if dep.kind == CampaignDependencyType.MIXED_OVERLAY),
                ),
                (
                    StrategicMilestoneKind.WORKSPACE_LIFECYCLE,
                    MilestonePredicateKind.WORKSPACE_USED_RECOVERED,
                    tuple(dep.dependency_id for dep in graph.dependencies if dep.kind == CampaignDependencyType.WORKSPACE_REQUIRED),
                ),
            )
            for family_kind, predicate_kind, family_ids in family_specs:
                if not family_ids or family_kind == kind:
                    continue
                family_id = _stable_id(state_key, graph.campaign_id, family_kind.value, family_ids)
                workspace_family = family_kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE
                milestones.append(StrategicMilestone(
                    family_id, state_key, graph.campaign_id, graph.campaign_id,
                    family_kind,
                    MilestoneTargetPredicate(
                        predicate_kind,
                        f"complete {family_kind.value.lower()} for {graph.campaign_id}",
                        campaign.suit,
                        dependency_ids=(() if workspace_family else family_ids),
                        workspace_requires_use=workspace_family,
                        workspace_requires_recovery=workspace_family,
                    ),
                    campaign.suit, (), (),
                    tuple(StrategicMilestonePrerequisite(item, item) for item in family_ids),
                    StrategicMilestoneProgress(0, 3 if workspace_family else len(family_ids), family_ids, fresh_state_hash=_stable_id(state_key)),
                    min(6, max(1, len(family_ids))), 4, 3, 4.0, 12_000,
                    f"fresh analysis satisfies {family_kind.value.lower()}",
                    "fresh analysis removes or supersedes the named requirement",
                    milestone_epoch_feasibility(family_id, availability[graph.campaign_id]),
                    StrategicMilestoneStatus.ACTIVE,
                    created_depth, created_elapsed_seconds,
                ))
        if summary is not None and not summary.terminal_qualified:
            terminal_id = _stable_id(state_key, graph.campaign_id, "terminal-qualification")
            milestones.append(StrategicMilestone(
                terminal_id, state_key, graph.campaign_id, graph.campaign_id,
                StrategicMilestoneKind.TERMINAL_QUALIFICATION,
                MilestoneTargetPredicate(
                    MilestonePredicateKind.TERMINAL_QUALIFIED,
                    f"reach the existing terminal predicate for {graph.campaign_id}",
                    campaign.suit,
                    dependency_ids=chain_ids,
                ),
                campaign.suit, tuple(range(13, 0, -1)), (),
                tuple(StrategicMilestonePrerequisite(item, item) for item in chain_ids),
                StrategicMilestoneProgress(0, 1, chain_ids, fresh_state_hash=_stable_id(state_key)),
                8, 4, 3, 4.0, 12_000,
                "existing campaign_is_near_removal predicate is true",
                "fresh campaign analysis makes another assignment dominant",
                milestone_epoch_feasibility(terminal_id, availability[graph.campaign_id]),
                StrategicMilestoneStatus.ACTIVE,
                created_depth, created_elapsed_seconds,
            ))
        if summary and summary.terminal_qualified:
            target_count = len(state.foundations) + 1
            mid = _stable_id(state_key, graph.campaign_id, "foundation", target_count)
            milestones.append(StrategicMilestone(
                mid, state_key, graph.campaign_id, graph.campaign_id,
                StrategicMilestoneKind.FOUNDATION_REMOVAL,
                MilestoneTargetPredicate(MilestonePredicateKind.FOUNDATION_COUNT, f"reach {target_count} foundations", campaign.suit, target_foundation_count=target_count),
                campaign.suit, tuple(range(13, 0, -1)), (), (),
                StrategicMilestoneProgress(len(state.foundations), target_count, terminal_qualified=True, fresh_state_hash=_stable_id(state_key)),
                18, 4, 2, 4.0, 12_000, "automatic same-suit K-A removal occurs", "campaign loses terminal qualification", milestone_epoch_feasibility(mid, availability[graph.campaign_id]),
                StrategicMilestoneStatus.ACTIVE, created_depth, created_elapsed_seconds,
            ))
    if construction is not None:
        make = [item for item in construction.opportunities if item.disposition == ConstructionDisposition.MAKE_NOW]
        by_suit = {}
        for item in make:
            by_suit.setdefault(item.suit, item)
        for suit, opportunity in sorted(by_suit.items()):
            mid = _stable_id(state_key, "run", suit, opportunity.run_length_after)
            milestones.append(StrategicMilestone(
                mid, state_key, f"construction:{suit}", None, StrategicMilestoneKind.RUN_CONSTRUCTION,
                MilestoneTargetPredicate(MilestonePredicateKind.DURABLE_RUN, f"build durable {opportunity.run_length_after}-card run", suit, minimum_run_length=opportunity.run_length_after),
                suit, tuple(card.rank for card in opportunity.source_fragment) + (opportunity.receiver.rank,), (), (),
                StrategicMilestoneProgress(opportunity.run_length_before, opportunity.run_length_after, fresh_state_hash=_stable_id(state_key)),
                opportunity.current_paid_cost, 2, 2, 2.0, 2_000, "durable run length reached", "fresh construction analysis no longer supports the join", None,
                StrategicMilestoneStatus.ACTIVE, created_depth, created_elapsed_seconds,
            ))
    blocked = tuple(item for item in availability.values() if not item.current_epoch_feasible)
    if blocked and state.stock:
        epoch = 5 - len(state.stock) // 10
        for item in blocked[:1]:
            campaign = campaigns_by_id.get(item.campaign_id)
            suit = campaign.suit if campaign is not None else None
            prep_id = _stable_id(state_key, item.campaign_id, "predeal", epoch)
            milestones.append(StrategicMilestone(
                prep_id, state_key, item.campaign_id, item.campaign_id,
                StrategicMilestoneKind.PRE_DEAL_PREPARATION,
                MilestoneTargetPredicate(MilestonePredicateKind.PRE_DEAL_WORK_COMPLETE, f"complete worthwhile epoch-{epoch} work before the exact next row", suit),
                suit, item.stock_blocked_ranks, (), (),
                StrategicMilestoneProgress(0, 1, fresh_state_hash=_stable_id(state_key)),
                4, 3, 2, 4.0, 12_000,
                "all MUST/SHOULD exact-row preparation is achieved or boundedly exhausted",
                "fresh availability no longer requires later stock",
                milestone_epoch_feasibility(prep_id, item),
                StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH,
                created_depth, created_elapsed_seconds,
            ))
            target_epoch = item.earliest_feasible_epoch or epoch + 1
            transition_id = _stable_id(state_key, item.campaign_id, "epoch", target_epoch)
            milestones.append(StrategicMilestone(
                transition_id, state_key, item.campaign_id, item.campaign_id,
                StrategicMilestoneKind.EPOCH_TRANSITION,
                MilestoneTargetPredicate(MilestonePredicateKind.STOCK_EPOCH_REACHED, f"Deal deliberately toward epoch {target_epoch}", suit, target_stock_epoch=min(target_epoch, epoch + 1)),
                suit, item.stock_blocked_ranks, (), (),
                StrategicMilestoneProgress(epoch, min(target_epoch, epoch + 1), fresh_state_hash=_stable_id(state_key)),
                1, 1, 1, 1.0, 128,
                "one exact stock row is dealt for recorded future-material purpose",
                "stock is exhausted or fresh analysis removes the material requirement",
                milestone_epoch_feasibility(transition_id, item),
                StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH,
                created_depth, created_elapsed_seconds,
            ))
    # Diverse admission: one leading campaign, an alternate, construction,
    # workspace and stock-blocked preparation/transition when available.
    milestones.sort(key=lambda item: item.ordering_key())
    selected = []
    families = set()
    campaigns_seen = set()
    for item in milestones:
        family = item.kind
        if item.campaign_id and item.campaign_id in campaigns_seen and family in families:
            continue
        selected.append(item)
        families.add(family)
        if item.campaign_id:
            campaigns_seen.add(item.campaign_id)
        if len(selected) >= maximum:
            break
    counts = {}
    for item in milestones:
        counts[item.kind.value] = counts.get(item.kind.value, 0) + 1
    admitted = tuple(selected)
    return StrategicMilestonePortfolio(
        admitted,
        StrategicMilestonePlan(admitted[0] if admitted else None, admitted[1:]),
        tuple(sorted(counts.items())),
    )
