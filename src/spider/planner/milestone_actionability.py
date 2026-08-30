"""Fresh-state actionability for one persistent strategic milestone.

This is deliberately a thin adapter over the existing construction,
dependency-closure, terminal-assembly, and campaign realisers.  It names the
remaining logical requirement and selects an existing bounded realiser; it is
not a second search engine and none of its conclusions authorize proof
pruning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Mapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
)
from spider.planner.epoch_progression import CampaignEpochAvailability
from spider.planner.strategic_milestone import (
    MilestonePredicateKind,
    MilestoneTargetIdentity,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestoneProgress,
    evaluate_milestone_progress,
    milestone_target_identity,
    semantic_dependency_outcome,
)
from spider.planner.structural_construction import (
    ConstructionDisposition,
    SameSuitConstructionOpportunity,
    StructuralConstructionAnalysis,
)
from spider.planner.source_completion import (
    SourceCompletionScope,
    SourceRequirementReopeningReason,
    SourceRequirementSatisfaction,
    SourceRequirementSatisfactionState,
    reconcile_source_satisfaction,
    semantic_source_requirement,
)
from spider.planner.tactical_resource_allocator import (
    TacticalDemand,
    TacticalObjectiveKind,
    TacticalRealizerKind,
)
from spider.rules import MW_RULES


class MilestoneBlockerKind(str, Enum):
    SOURCE_BURIED = "SOURCE_BURIED"
    EXPOSED_BLOCKED = "EXPOSED_BLOCKED"
    MIXED_OVERLAY = "MIXED_OVERLAY"
    RECEIVER_MISSING = "RECEIVER_MISSING"
    SUPPLIED_NOT_CONSUMED = "SUPPLIED_NOT_CONSUMED"
    MISSING_INTERVAL = "MISSING_INTERVAL"
    FRAGMENT_ORDERING = "FRAGMENT_ORDERING"
    WORKSPACE = "WORKSPACE"
    TERMINAL_ASSEMBLY = "TERMINAL_ASSEMBLY"
    STOCK_EPOCH = "STOCK_EPOCH"


class ResidualTargetStatus(str, Enum):
    COMPLETE = "COMPLETE"
    ACTIONABLE = "ACTIONABLE"
    BLOCKED_CURRENT_EPOCH = "BLOCKED_CURRENT_EPOCH"
    INVALIDATED = "INVALIDATED"


class PostDealObligationStatus(str, Enum):
    MATERIAL_AVAILABLE = "MATERIAL_AVAILABLE"
    ACTIONABLE = "ACTIONABLE"
    BLOCKED = "BLOCKED"
    STRUCTURAL_PROGRESS = "STRUCTURAL_PROGRESS"
    SUBSTANTIAL_HARVEST = "SUBSTANTIAL_HARVEST"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class ResidualMilestoneRequirement:
    requirement_id: str
    description: str
    satisfied: bool
    blocker: Optional[MilestoneBlockerKind] = None
    source_satisfaction: Optional[SourceRequirementSatisfaction] = None


@dataclass(frozen=True)
class MilestoneActionCandidate:
    blocker: MilestoneBlockerKind
    demand: TacticalDemand
    construction_opportunity_id: Optional[str]
    rationale: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class ResidualMilestoneTarget:
    identity: MilestoneTargetIdentity
    milestone: StrategicMilestone
    progress: StrategicMilestoneProgress
    requirements: Tuple[ResidualMilestoneRequirement, ...]
    blockers: Tuple[MilestoneBlockerKind, ...]
    candidates: Tuple[MilestoneActionCandidate, ...]
    status: ResidualTargetStatus
    remaining_dependency_ids: Tuple[str, ...]
    fresh_state_fingerprint: str
    reason: str
    proof_pruning_allowed: bool = False
    source_satisfactions: Tuple[SourceRequirementSatisfaction, ...] = ()
    source_reopenings: Tuple[Tuple[str, SourceRequirementReopeningReason], ...] = ()

    @property
    def next_candidate(self) -> Optional[MilestoneActionCandidate]:
        return self.candidates[0] if self.candidates else None

    @property
    def summary(self) -> str:
        blockers = ",".join(item.value for item in self.blockers) or "none"
        return (
            f"{self.identity.kind.value}:{self.status.value}:"
            f"{self.progress.satisfied_units}/{self.progress.total_units}:{blockers}"
        )


@dataclass(frozen=True)
class PostDealMilestoneObligation:
    obligation_id: str
    transition_milestone_id: str
    target_identity: MilestoneTargetIdentity
    expected_material: Tuple[Tuple[str, int], ...]
    created_epoch: int
    opportunity_deadline_epoch: int
    status: PostDealObligationStatus
    material_available: bool
    structural_progress_events: int
    substantial_harvest_events: int
    last_reason: str
    proof_pruning_allowed: bool = False

    @property
    def unresolved_actionable(self) -> bool:
        return self.status in {
            PostDealObligationStatus.MATERIAL_AVAILABLE,
            PostDealObligationStatus.ACTIONABLE,
        }


_DEPENDENCY_BLOCKER = {
    CampaignDependencyType.SOURCE_BURIED: MilestoneBlockerKind.SOURCE_BURIED,
    CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED: MilestoneBlockerKind.EXPOSED_BLOCKED,
    CampaignDependencyType.MIXED_OVERLAY: MilestoneBlockerKind.MIXED_OVERLAY,
    CampaignDependencyType.RECEIVER_MISSING: MilestoneBlockerKind.RECEIVER_MISSING,
    CampaignDependencyType.SUPPLIED_NOT_CONSUMED: MilestoneBlockerKind.SUPPLIED_NOT_CONSUMED,
    CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL: MilestoneBlockerKind.MISSING_INTERVAL,
    CampaignDependencyType.FRAGMENT_ORDERING: MilestoneBlockerKind.FRAGMENT_ORDERING,
    CampaignDependencyType.WORKSPACE_REQUIRED: MilestoneBlockerKind.WORKSPACE,
    CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE: MilestoneBlockerKind.TERMINAL_ASSEMBLY,
}

_BLOCKER_ORDER = {
    MilestoneBlockerKind.SOURCE_BURIED: 0,
    MilestoneBlockerKind.EXPOSED_BLOCKED: 1,
    MilestoneBlockerKind.MIXED_OVERLAY: 2,
    MilestoneBlockerKind.RECEIVER_MISSING: 3,
    MilestoneBlockerKind.SUPPLIED_NOT_CONSUMED: 4,
    MilestoneBlockerKind.MISSING_INTERVAL: 5,
    MilestoneBlockerKind.FRAGMENT_ORDERING: 6,
    MilestoneBlockerKind.WORKSPACE: 7,
    MilestoneBlockerKind.TERMINAL_ASSEMBLY: 8,
    MilestoneBlockerKind.STOCK_EPOCH: 9,
}


def _state_fingerprint(state: SpiderState) -> str:
    from spider.state_identity import canonical_state_key

    return hashlib.sha256(repr(canonical_state_key(state)).encode("utf-8")).hexdigest()[:16]


def _dependencies_for_target(
    milestone: StrategicMilestone,
    graph: Optional[CampaignDependencyGraph],
) -> Tuple[CampaignDependency, ...]:
    if graph is None:
        return ()
    dependencies = graph.dependencies
    if milestone.kind == StrategicMilestoneKind.RECEIVER_GEOMETRY:
        allowed = {
            CampaignDependencyType.RECEIVER_MISSING,
            CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
        }
        return tuple(item for item in dependencies if item.kind in allowed)
    if milestone.kind == StrategicMilestoneKind.SUPPLY_INTEGRATION:
        return tuple(
            item for item in dependencies
            if item.kind == CampaignDependencyType.SUPPLIED_NOT_CONSUMED
        )
    if milestone.kind == StrategicMilestoneKind.OVERLAY_CLEARANCE:
        return tuple(
            item for item in dependencies if item.kind == CampaignDependencyType.MIXED_OVERLAY
        )
    if milestone.kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE:
        return tuple(
            item for item in dependencies if item.kind == CampaignDependencyType.WORKSPACE_REQUIRED
        )
    if milestone.kind == StrategicMilestoneKind.SOURCE_CHAIN:
        expected = set(milestone_target_identity(milestone).dependency_outcomes)
        return tuple(
            item for item in dependencies
            if item.kind not in {
                CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
                CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
            }
            and (
                not expected
                or semantic_dependency_outcome(item.dependency_id) in expected
            )
        )
    if milestone.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION:
        return dependencies
    return ()


def _target_construction_opportunities(
    state: SpiderState,
    milestone: StrategicMilestone,
    construction: Optional[StructuralConstructionAnalysis],
    progress: StrategicMilestoneProgress,
) -> Tuple[SameSuitConstructionOpportunity, ...]:
    if construction is None:
        return ()
    improving = []
    for opportunity in construction.opportunities:
        if opportunity.disposition != ConstructionDisposition.MAKE_NOW:
            continue
        if milestone.suit and opportunity.suit != milestone.suit:
            continue
        candidate = state.clone()
        try:
            candidate.move(*opportunity.action, rules=MW_RULES)
        except (ValueError, IndexError):
            continue
        after = evaluate_milestone_progress(candidate, milestone)
        if (
            milestone.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION
            or after.satisfied_units > progress.satisfied_units
            or after.complete
        ):
            improving.append(opportunity)
    return tuple(sorted(improving, key=lambda item: item.ordering_key()))


def _candidate_for_blocker(
    blocker: MilestoneBlockerKind,
    milestone: StrategicMilestone,
    dependency: Optional[CampaignDependency],
    opportunity: Optional[SameSuitConstructionOpportunity],
) -> MilestoneActionCandidate:
    objective, realizer = {
        MilestoneBlockerKind.SOURCE_BURIED: (
            TacticalObjectiveKind.EXCAVATION,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.EXPOSED_BLOCKED: (
            TacticalObjectiveKind.RECEIVER_CREATION,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.MIXED_OVERLAY: (
            TacticalObjectiveKind.OVERLAY_CLEARING,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.RECEIVER_MISSING: (
            TacticalObjectiveKind.RECEIVER_CREATION,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.SUPPLIED_NOT_CONSUMED: (
            TacticalObjectiveKind.SUPPLY_CONSUMPTION,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.MISSING_INTERVAL: (
            TacticalObjectiveKind.INTERVAL_ASSEMBLY,
            TacticalRealizerKind.RUN_CONSTRUCTION,
        ),
        MilestoneBlockerKind.FRAGMENT_ORDERING: (
            TacticalObjectiveKind.RUN_CONSTRUCTION,
            TacticalRealizerKind.RUN_CONSTRUCTION,
        ),
        MilestoneBlockerKind.WORKSPACE: (
            TacticalObjectiveKind.WORKSPACE,
            TacticalRealizerKind.DEPENDENCY_CLOSURE,
        ),
        MilestoneBlockerKind.TERMINAL_ASSEMBLY: (
            TacticalObjectiveKind.FOUNDATION_REMOVAL,
            TacticalRealizerKind.TERMINAL_ASSEMBLY,
        ),
        MilestoneBlockerKind.STOCK_EPOCH: (
            TacticalObjectiveKind.DEAL_EVALUATION,
            TacticalRealizerKind.DEAL_TIMING,
        ),
    }[blocker]
    demand = TacticalDemand(
        objective=objective,
        realizer=realizer,
        reason=f"persistent {milestone.kind.value} residual: {blocker.value}",
        campaign_id=milestone.campaign_id,
        campaign_suit=milestone.suit,
        target_dependency_id=dependency.dependency_id if dependency else None,
        prerequisites=dependency.prerequisites if dependency else (),
        source_depth=dependency.depth if dependency else 0,
        receiver_missing=blocker in {
            MilestoneBlockerKind.EXPOSED_BLOCKED,
            MilestoneBlockerKind.RECEIVER_MISSING,
        },
        workspace_required=blocker == MilestoneBlockerKind.WORKSPACE,
        supplied_asset_waiting=blocker == MilestoneBlockerKind.SUPPLIED_NOT_CONSUMED,
        interval_missing=blocker == MilestoneBlockerKind.MISSING_INTERVAL,
        overlay_present=blocker == MilestoneBlockerKind.MIXED_OVERLAY,
        terminal_qualified=blocker == MilestoneBlockerKind.TERMINAL_ASSEMBLY,
        continuation_attention=True,
        construction_opportunity_id=opportunity.opportunity_id if opportunity else None,
        construction_disposition=opportunity.disposition if opportunity else None,
    )
    return MilestoneActionCandidate(
        blocker=blocker,
        demand=demand,
        construction_opportunity_id=opportunity.opportunity_id if opportunity else None,
        rationale=demand.reason,
    )


def derive_residual_milestone_target(
    state: SpiderState,
    milestone: StrategicMilestone,
    *,
    graph: Optional[CampaignDependencyGraph] = None,
    construction: Optional[StructuralConstructionAnalysis] = None,
    availability: Optional[CampaignEpochAvailability] = None,
    terminal_qualified: bool = False,
    prior_source_satisfactions: Sequence[SourceRequirementSatisfaction] = (),
) -> ResidualMilestoneTarget:
    """Re-express the same logical target against the complete fresh state."""

    identity = milestone_target_identity(milestone)
    dependencies = _dependencies_for_target(milestone, graph)
    dependency_ids = tuple(item.dependency_id for item in dependencies)
    progress = evaluate_milestone_progress(
        state,
        milestone,
        remaining_dependencies=dependency_ids,
        terminal_qualified=terminal_qualified,
    )
    requirements = []
    source_satisfactions = []
    source_reopenings = []
    blockers_with_sources = []
    opportunities = _target_construction_opportunities(
        state, milestone, construction, progress
    )

    if milestone.target.kind == MilestonePredicateKind.SAME_SUIT_INTERVAL:
        assembled = set(progress.assembled_ranks)
        for rank in identity.required_ranks:
            satisfied = rank in assembled or progress.complete
            requirements.append(ResidualMilestoneRequirement(
                f"rank:{rank}:{identity.suit}",
                f"rank {rank} is integrated in the target interval",
                satisfied,
                None if satisfied else MilestoneBlockerKind.MISSING_INTERVAL,
            ))
        if not progress.complete:
            blockers_with_sources.append((MilestoneBlockerKind.MISSING_INTERVAL, None))
            if not opportunities and graph is not None:
                required_ranks = set(identity.required_ranks)
                for dependency in graph.dependencies:
                    if dependency.kind == CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE:
                        continue
                    if (
                        dependency.card is not None
                        and dependency.card.suit == identity.suit
                        and dependency.card.rank not in required_ranks
                    ):
                        continue
                    blockers_with_sources.append(
                        (_DEPENDENCY_BLOCKER[dependency.kind], dependency)
                    )
    elif milestone.target.kind == MilestonePredicateKind.DURABLE_RUN:
        requirements.append(ResidualMilestoneRequirement(
            f"run:{identity.suit}:{progress.total_units}",
            milestone.completion_condition,
            progress.complete,
            None if progress.complete else MilestoneBlockerKind.FRAGMENT_ORDERING,
        ))
        if not progress.complete:
            blockers_with_sources.append((MilestoneBlockerKind.FRAGMENT_ORDERING, None))
    elif milestone.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION:
        requirements.append(ResidualMilestoneRequirement(
            "terminal-qualification", milestone.completion_condition, terminal_qualified,
            None if terminal_qualified else MilestoneBlockerKind.TERMINAL_ASSEMBLY,
        ))
        for dependency in dependencies:
            blockers_with_sources.append((_DEPENDENCY_BLOCKER[dependency.kind], dependency))
        if not terminal_qualified and not dependencies:
            blockers_with_sources.append((MilestoneBlockerKind.TERMINAL_ASSEMBLY, None))
    elif dependencies or milestone.target.kind in {
        MilestonePredicateKind.DEPENDENCIES_CLOSED,
        MilestonePredicateKind.RECEIVER_AVAILABLE,
        MilestonePredicateKind.SUPPLY_INTEGRATED,
        MilestonePredicateKind.OVERLAY_REMOVED,
        MilestonePredicateKind.WORKSPACE_USED_RECOVERED,
    }:
        current_semantic = {
            semantic_dependency_outcome(item.dependency_id): item for item in dependencies
        }
        expected = identity.dependency_outcomes or tuple(current_semantic)
        for required in expected:
            dependency = current_semantic.get(required)
            satisfied = dependency is None
            blocker = None if satisfied else _DEPENDENCY_BLOCKER[dependency.kind]
            source_satisfaction = None
            source_dependency = dependency
            prior = next(
                (
                    item
                    for item in reversed(tuple(prior_source_satisfactions))
                    if semantic_dependency_outcome(item.requirement.dependency_id) == required
                    and item.requirement.semantic_target_fingerprint == identity.fingerprint
                ),
                None,
            )
            if source_dependency is not None and source_dependency.card is not None and source_dependency.kind in {
                CampaignDependencyType.SOURCE_BURIED,
                CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED,
            }:
                source_requirement = semantic_source_requirement(
                    identity.fingerprint,
                    source_dependency.dependency_id,
                    source_dependency.card,
                    scope=(
                        prior.requirement.scope
                        if prior is not None
                        else SourceCompletionScope.BURIED_PREDICATE
                        if source_dependency.kind == CampaignDependencyType.SOURCE_BURIED
                        else SourceCompletionScope.EXPOSED_BLOCKER_PREDICATE
                    ),
                    copies_required=(prior.requirement.copies_required if prior else 1),
                )
                source_satisfaction = reconcile_source_satisfaction(
                    state,
                    source_requirement,
                    prior,
                    current_dependency_type=source_dependency.kind.value,
                )
            elif dependency is None and prior is not None:
                source_satisfaction = reconcile_source_satisfaction(
                    state,
                    prior.requirement,
                    prior,
                    current_dependency_type=None,
                )
            if source_satisfaction is not None:
                source_satisfactions.append(source_satisfaction)
                if source_satisfaction.reopening_reason is not None:
                    source_reopenings.append((required, source_satisfaction.reopening_reason))
                # Completing SOURCE_BURIED is durable subrequirement harvest;
                # SOURCE_EXPOSED_BUT_BLOCKED remains an explicit follow-on.
                if (
                    dependency is not None
                    and dependency.kind == CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED
                    and source_satisfaction.state in {
                        SourceRequirementSatisfactionState.EXPOSED,
                        SourceRequirementSatisfactionState.ACTIONABLE,
                        SourceRequirementSatisfactionState.CONSUMED,
                        SourceRequirementSatisfactionState.INTEGRATED,
                    }
                ):
                    satisfied = False
                    blocker = MilestoneBlockerKind.EXPOSED_BLOCKED
            requirements.append(ResidualMilestoneRequirement(
                required,
                (
                    f"logical dependency outcome {required} retains a follow-on blocker; "
                    "its original buried-source predicate is satisfied"
                    if source_satisfaction is not None
                    and blocker == MilestoneBlockerKind.EXPOSED_BLOCKED
                    else f"logical dependency outcome {required} is closed"
                ),
                satisfied,
                blocker,
                source_satisfaction,
            ))
            if dependency is not None:
                blockers_with_sources.append((blocker, dependency))
        for required, dependency in current_semantic.items():
            if required not in expected:
                blocker = _DEPENDENCY_BLOCKER[dependency.kind]
                requirements.append(ResidualMilestoneRequirement(
                    required, f"replacement blocker {required} is closed", False, blocker
                ))
                blockers_with_sources.append((blocker, dependency))
        if milestone.kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE and not progress.complete:
            blockers_with_sources.append((MilestoneBlockerKind.WORKSPACE, None))
    else:
        requirements.append(ResidualMilestoneRequirement(
            "completion", milestone.completion_condition, progress.complete
        ))

    if milestone.kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE:
        workspace_complete = bool(
            progress.workspace_created
            and progress.workspace_used
            and progress.workspace_recovered_or_replaced
        )
        progress = replace(
            progress,
            satisfied_units=sum((
                progress.workspace_created,
                progress.workspace_used,
                progress.workspace_recovered_or_replaced,
            )),
            total_units=3,
        )
        requirements = [ResidualMilestoneRequirement(
            "workspace-lifecycle",
            "workspace is created, used for the named objective, and recovered or replaced",
            workspace_complete,
            None if workspace_complete else MilestoneBlockerKind.WORKSPACE,
        )]
    elif milestone.target.kind in {
        MilestonePredicateKind.DEPENDENCIES_CLOSED,
        MilestonePredicateKind.RECEIVER_AVAILABLE,
        MilestonePredicateKind.SUPPLY_INTEGRATED,
        MilestonePredicateKind.OVERLAY_REMOVED,
    } and requirements:
        progress = replace(
            progress,
            satisfied_units=sum(item.satisfied for item in requirements),
            total_units=len(requirements),
            remaining_dependencies=tuple(
                item.requirement_id for item in requirements if not item.satisfied
            ),
        )

    ordered = []
    seen = set()
    for blocker, dependency in sorted(
        blockers_with_sources, key=lambda item: _BLOCKER_ORDER[item[0]]
    ):
        if blocker not in seen:
            ordered.append((blocker, dependency))
            seen.add(blocker)
    candidates = []
    for blocker, dependency in ordered:
        opportunity = opportunities[0] if blocker in {
            MilestoneBlockerKind.MISSING_INTERVAL,
            MilestoneBlockerKind.FRAGMENT_ORDERING,
        } and opportunities else None
        if blocker in {
            MilestoneBlockerKind.MISSING_INTERVAL,
            MilestoneBlockerKind.FRAGMENT_ORDERING,
        } and opportunity is None:
            continue
        candidates.append(_candidate_for_blocker(blocker, milestone, dependency, opportunity))

    if progress.complete:
        status = ResidualTargetStatus.COMPLETE
        reason = "fresh completion predicate is satisfied"
    elif candidates:
        status = ResidualTargetStatus.ACTIONABLE
        reason = f"fresh state exposes {candidates[0].blocker.value} actionability"
    elif availability is not None and not availability.current_epoch_feasible:
        status = ResidualTargetStatus.BLOCKED_CURRENT_EPOCH
        reason = "same semantic target currently requires later stock material"
    elif (
        ordered
        and not (
            milestone.kind == StrategicMilestoneKind.RUN_CONSTRUCTION
            and not state.stock
        )
    ):
        status = ResidualTargetStatus.BLOCKED_CURRENT_EPOCH
        reason = "fresh blockers remain but no bounded target-specific action is exposed"
    else:
        status = ResidualTargetStatus.INVALIDATED
        reason = "fresh state neither satisfies nor supports the target"
    return ResidualMilestoneTarget(
        identity=identity,
        milestone=replace(milestone, target_identity=identity, progress=progress),
        progress=progress,
        requirements=tuple(requirements),
        blockers=tuple(item[0] for item in ordered),
        candidates=tuple(candidates),
        status=status,
        remaining_dependency_ids=dependency_ids,
        fresh_state_fingerprint=_state_fingerprint(state),
        reason=reason,
        source_satisfactions=tuple(source_satisfactions),
        source_reopenings=tuple(source_reopenings),
    )


def create_post_deal_obligation(
    transition_milestone: StrategicMilestone,
    target: StrategicMilestone,
    dealt_row: Sequence[Card],
    *,
    created_epoch: int,
) -> PostDealMilestoneObligation:
    identity = milestone_target_identity(target)
    rank_set = set(identity.required_ranks)
    expected = tuple(
        sorted({
            (card.suit, card.rank)
            for card in dealt_row
            if (identity.suit is None or card.suit == identity.suit)
            and (not rank_set or card.rank in rank_set)
        })
    )
    if not expected:
        expected = tuple(sorted({(card.suit, card.rank) for card in dealt_row}))
    obligation_id = hashlib.sha256(repr((
        transition_milestone.milestone_id,
        identity.fingerprint,
        expected,
        created_epoch,
    )).encode("utf-8")).hexdigest()[:16]
    return PostDealMilestoneObligation(
        obligation_id=obligation_id,
        transition_milestone_id=transition_milestone.milestone_id,
        target_identity=identity,
        expected_material=expected,
        created_epoch=created_epoch,
        opportunity_deadline_epoch=created_epoch + 1,
        status=PostDealObligationStatus.MATERIAL_AVAILABLE,
        material_available=True,
        structural_progress_events=0,
        substantial_harvest_events=0,
        last_reason="purposeful Deal created a bounded same-target conversion obligation",
    )


def refresh_post_deal_obligation(
    state: SpiderState,
    obligation: PostDealMilestoneObligation,
    residual: Optional[ResidualMilestoneTarget],
    *,
    structural_progress: bool = False,
    substantial_harvest: bool = False,
) -> PostDealMilestoneObligation:
    visible_or_buried = {
        (card.suit, card.rank)
        for column in state.columns
        for card in column.face_down + column.face_up
    }
    material_available = any(item in visible_or_buried for item in obligation.expected_material)
    progress_events = obligation.structural_progress_events + int(structural_progress)
    harvest_events = obligation.substantial_harvest_events + int(substantial_harvest)
    if substantial_harvest:
        status = PostDealObligationStatus.SUBSTANTIAL_HARVEST
        reason = "the promised target reached a substantial structural milestone"
    elif structural_progress:
        status = PostDealObligationStatus.STRUCTURAL_PROGRESS
        reason = "the promised target received fresh structural conversion"
    elif residual is not None and residual.status == ResidualTargetStatus.ACTIONABLE:
        status = PostDealObligationStatus.ACTIONABLE
        reason = residual.reason
    elif material_available:
        status = PostDealObligationStatus.MATERIAL_AVAILABLE
        reason = "promised row material remains available for bounded conversion"
    else:
        status = PostDealObligationStatus.BLOCKED
        reason = "promised material or target actionability is not currently available"
    return replace(
        obligation,
        status=status,
        material_available=material_available,
        structural_progress_events=progress_events,
        substantial_harvest_events=harvest_events,
        last_reason=reason,
    )


def obligation_matches_target(
    obligation: PostDealMilestoneObligation,
    target: StrategicMilestone | MilestoneTargetIdentity,
) -> bool:
    identity = (
        target if isinstance(target, MilestoneTargetIdentity)
        else milestone_target_identity(target)
    )
    return obligation.target_identity.fingerprint == identity.fingerprint
