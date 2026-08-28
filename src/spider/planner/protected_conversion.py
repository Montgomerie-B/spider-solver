"""Bounded protection and terminal diagnosis for next-foundation investment."""

from __future__ import annotations

import hashlib
import heapq
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.foundation_campaign import CampaignReadiness, FoundationCampaign
from spider.planner.foundation_campaign_removal import (
    CampaignBand,
    CampaignReceiverCondition,
    campaign_receiver_conditions,
    locate_campaign_bands,
)
from spider.planner.residual_campaign import (
    FoundationCheckpointProfile,
    NextFoundationReadiness,
)
from spider.planner.stock_reception import next_stock_row
from spider.rules import MW_RULES
from spider.state_identity import CanonicalStateKey, canonical_state_key, states_structurally_equal


_READINESS_RANK = {
    CampaignReadiness.READY_NOW: 0,
    CampaignReadiness.ASSEMBLY_LED: 1,
    CampaignReadiness.EXCAVATION_LED: 2,
    CampaignReadiness.STOCK_GATED: 3,
    CampaignReadiness.DEFERRED: 4,
    CampaignReadiness.BLOCKED: 5,
}


class RemovalRelevantMilestoneKind(str, Enum):
    FOUNDATION_REMOVED = "FOUNDATION_REMOVED"
    REQUIRED_SOURCE_EXPOSED = "REQUIRED_SOURCE_EXPOSED"
    MUST_DEPENDENCY_REMOVED = "MUST_DEPENDENCY_REMOVED"
    CAMPAIGN_INTERVAL_ASSEMBLED = "CAMPAIGN_INTERVAL_ASSEMBLED"
    RECEIVER_OBLIGATION_SATISFIED = "RECEIVER_OBLIGATION_SATISFIED"
    CAMPAIGN_STATUS_IMPROVED = "CAMPAIGN_STATUS_IMPROVED"
    REMOVAL_COST_DECREASED = "REMOVAL_COST_DECREASED"
    REMOVAL_MACRO_AVAILABLE = "REMOVAL_MACRO_AVAILABLE"


class ProtectedConversionStatus(str, Enum):
    CONTINUE = "CONTINUE"
    MILESTONE_REACHED = "MILESTONE_REACHED"
    SUCCESS = "SUCCESS"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    DOMINATED_SAME_OBJECTIVE = "DOMINATED_SAME_OBJECTIVE"


@dataclass(frozen=True)
class ProtectedConversionBudget:
    max_added_cost: int = 18
    max_descendant_expansions: int = 5
    max_elapsed_seconds: float = 30.0

    def __post_init__(self) -> None:
        if self.max_added_cost <= 0 or self.max_descendant_expansions <= 0:
            raise ValueError("protected conversion cost and expansion limits must be positive")
        if self.max_elapsed_seconds <= 0:
            raise ValueError("protected conversion time limit must be positive")


@dataclass(frozen=True)
class ProtectedConversionLane:
    lane_id: str
    target_campaign: str
    target_foundation_count: int
    start_state_key: CanonicalStateKey
    start_g: int
    start_expansion: int
    start_elapsed_seconds: float
    baseline: NextFoundationReadiness
    budget: ProtectedConversionBudget
    objective_description: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class ProtectedLaneAssessment:
    lane: ProtectedConversionLane
    status: ProtectedConversionStatus
    milestones: Tuple[RemovalRelevantMilestoneKind, ...]
    added_cost: int
    descendant_expansions: int
    elapsed_seconds: float
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class RequiredSourceDiagnosis:
    source_key: str
    card: Card
    rank: int
    location_kind: str
    column: Optional[int]
    stock_epoch: Optional[int]
    depth: int
    exposed: bool
    dependency_blocked: bool
    helper_tasks: Tuple[Tuple[int, int], ...]
    status: str


@dataclass(frozen=True)
class CampaignTerminalDiagnosis:
    campaign_id: str
    readiness: CampaignReadiness
    target_epoch: Optional[int]
    remaining_must_sources: Tuple[RequiredSourceDiagnosis, ...]
    assembled_bands: Tuple[CampaignBand, ...]
    missing_rank_intervals: Tuple[Tuple[int, int], ...]
    receiver_conditions: Tuple[CampaignReceiverCondition, ...]
    receiver_blockers: Tuple[str, ...]
    workspace_blockers: Tuple[str, ...]
    mixed_suit_blockers: Tuple[str, ...]
    exact_next_stock_contributions: Tuple[Tuple[int, Card], ...]
    minimal_bounded_tactical_blockers: Tuple[str, ...]
    removal_macro_available: bool
    removal_macro_failure_reason: str
    near_removal: bool
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TerminalConversionDiagnosis:
    state_key: CanonicalStateKey
    foundations: int
    stock_remaining: int
    target_campaigns: Tuple[CampaignTerminalDiagnosis, ...]
    summary: Tuple[str, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class NearRemovalConfig:
    maximum_must_sources: int = 2
    maximum_source_depth: int = 3
    minimum_same_suit_coverage: int = 8
    maximum_receiver_blockers: int = 1
    maximum_estimated_cost: float = 12.0


class TerminalAssemblyStatus(str, Enum):
    FOUNDATION_REMOVED = "FOUNDATION_REMOVED"
    NOT_NEAR_REMOVAL = "NOT_NEAR_REMOVAL"
    NOT_FOUND_WITHIN_BOUND = "NOT_FOUND_WITHIN_BOUND"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INVALID_CAMPAIGN = "INVALID_CAMPAIGN"


@dataclass(frozen=True)
class TerminalAssemblyConfig:
    max_added_cost: int = 8
    max_nodes: int = 2_000
    time_limit_s: float = 2.0
    beam_width: int = 128
    permit_stock_transition: bool = False
    near_removal: NearRemovalConfig = NearRemovalConfig()

    def __post_init__(self) -> None:
        if self.max_added_cost <= 0 or self.max_nodes <= 0 or self.time_limit_s <= 0:
            raise ValueError("terminal assembly resources must be positive")
        if self.beam_width <= 0:
            raise ValueError("terminal assembly beam width must be positive")


@dataclass(frozen=True)
class TerminalAssemblyResult:
    status: TerminalAssemblyStatus
    campaign_id: str
    actions: Tuple[Action, ...]
    corrected_added_cost: Optional[int]
    end_state: SpiderState
    nodes_expanded: int
    elapsed_seconds: float
    independent_replay_verified: bool
    near_removal_qualified: bool
    reason: str
    proof_pruning_allowed: bool = False


def _readiness(profile: FoundationCheckpointProfile, label: str) -> Optional[NextFoundationReadiness]:
    return next(
        (item for item in profile.next_foundation_readiness if item.campaign_label == label),
        None,
    )


def _lane_id(profile: FoundationCheckpointProfile, readiness: NextFoundationReadiness) -> str:
    payload = repr((profile.state_key, readiness.campaign_label, profile.g)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def create_protected_conversion_lane(
    profile: FoundationCheckpointProfile,
    *,
    campaign_id: Optional[str] = None,
    current_expansion: int = 0,
    current_elapsed_seconds: float = 0.0,
    budget: ProtectedConversionBudget = ProtectedConversionBudget(),
) -> Optional[ProtectedConversionLane]:
    candidates = profile.next_foundation_readiness
    readiness = (
        _readiness(profile, campaign_id)
        if campaign_id is not None
        else (candidates[0] if candidates else None)
    )
    if readiness is None:
        return None
    return ProtectedConversionLane(
        lane_id=_lane_id(profile, readiness),
        target_campaign=readiness.campaign_label,
        target_foundation_count=profile.foundations + 1,
        start_state_key=profile.state_key,
        start_g=profile.g,
        start_expansion=current_expansion,
        start_elapsed_seconds=current_elapsed_seconds,
        baseline=readiness,
        budget=budget,
        objective_description=f"convert {readiness.campaign_label} into the next foundation",
    )


def removal_relevant_milestones(
    baseline: NextFoundationReadiness,
    current: NextFoundationReadiness,
    *,
    foundation_count: int,
    target_foundation_count: int,
) -> Tuple[RemovalRelevantMilestoneKind, ...]:
    milestones = []
    if foundation_count >= target_foundation_count:
        milestones.append(RemovalRelevantMilestoneKind.FOUNDATION_REMOVED)
    if current.must_dependencies_remaining < baseline.must_dependencies_remaining:
        milestones.append(RemovalRelevantMilestoneKind.MUST_DEPENDENCY_REMOVED)
    if current.deepest_required_source < baseline.deepest_required_source:
        milestones.append(RemovalRelevantMilestoneKind.REQUIRED_SOURCE_EXPOSED)
    if current.assembled_same_suit_rank_coverage > baseline.assembled_same_suit_rank_coverage:
        milestones.append(RemovalRelevantMilestoneKind.CAMPAIGN_INTERVAL_ASSEMBLED)
    if current.receiver_conditions_ready > baseline.receiver_conditions_ready:
        milestones.append(RemovalRelevantMilestoneKind.RECEIVER_OBLIGATION_SATISFIED)
    if _READINESS_RANK[current.campaign_status] < _READINESS_RANK[baseline.campaign_status]:
        milestones.append(RemovalRelevantMilestoneKind.CAMPAIGN_STATUS_IMPROVED)
    if current.bounded_estimated_cost_to_removal < baseline.bounded_estimated_cost_to_removal:
        milestones.append(RemovalRelevantMilestoneKind.REMOVAL_COST_DECREASED)
    if current.bounded_removal_macro_available and not baseline.bounded_removal_macro_available:
        milestones.append(RemovalRelevantMilestoneKind.REMOVAL_MACRO_AVAILABLE)
    return tuple(milestones)


def evaluate_protected_conversion_lane(
    lane: ProtectedConversionLane,
    profile: FoundationCheckpointProfile,
    *,
    current_expansion: int,
    current_elapsed_seconds: float,
    objective_still_credible: bool = True,
    dominated_same_objective: bool = False,
) -> ProtectedLaneAssessment:
    added_cost = profile.g - lane.start_g
    expansions = max(0, current_expansion - lane.start_expansion)
    elapsed = max(0.0, current_elapsed_seconds - lane.start_elapsed_seconds)
    current = _readiness(profile, lane.target_campaign)
    if profile.foundations >= lane.target_foundation_count:
        milestones = (RemovalRelevantMilestoneKind.FOUNDATION_REMOVED,)
        status = ProtectedConversionStatus.SUCCESS
        reason = "target foundation count increased"
    elif not objective_still_credible or current is None:
        milestones = ()
        status = ProtectedConversionStatus.INVALIDATED
        reason = "fresh analysis no longer supports the named campaign objective"
    elif dominated_same_objective:
        milestones = ()
        status = ProtectedConversionStatus.DOMINATED_SAME_OBJECTIVE
        reason = "a concretely better bounded lane reaches the same objective"
    else:
        milestones = removal_relevant_milestones(
            lane.baseline,
            current,
            foundation_count=profile.foundations,
            target_foundation_count=lane.target_foundation_count,
        )
        if milestones:
            status = ProtectedConversionStatus.MILESTONE_REACHED
            reason = "named campaign reached a removal-relevant structural milestone"
        elif (
            added_cost >= lane.budget.max_added_cost
            or expansions >= lane.budget.max_descendant_expansions
            or elapsed >= lane.budget.max_elapsed_seconds
        ):
            status = ProtectedConversionStatus.EXPIRED
            reason = "bounded protected investment envelope was exhausted"
        else:
            status = ProtectedConversionStatus.CONTINUE
            reason = "credible named campaign remains inside its bounded envelope"
    return ProtectedLaneAssessment(
        lane=lane,
        status=status,
        milestones=milestones,
        added_cost=added_cost,
        descendant_expansions=expansions,
        elapsed_seconds=elapsed,
        reason=reason,
    )


def _missing_intervals(bands: Sequence[CampaignBand]) -> Tuple[Tuple[int, int], ...]:
    present = set()
    for band in bands:
        present.update(range(band.low_rank, band.high_rank + 1))
    missing = [rank for rank in range(1, 14) if rank not in present]
    if not missing:
        return ()
    intervals = []
    low = high = missing[0]
    for rank in missing[1:]:
        if rank == high + 1:
            high = rank
        else:
            intervals.append((high, low))
            low = high = rank
    intervals.append((high, low))
    return tuple(reversed(intervals))


def campaign_is_near_removal(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    config: NearRemovalConfig = NearRemovalConfig(),
) -> bool:
    bands = locate_campaign_bands(state, campaign)
    coverage = max((band.length for band in bands), default=0)
    must = [need.chosen for need in campaign.rank_needs if need.must_excavate and need.chosen]
    deepest = max(
        (source.depth + source.excavation_peels + source.closure_prefix_hops for source in must),
        default=0,
    )
    receiver_blockers = sum(
        not (item.direct or item.bounded_walkoff)
        for item in campaign_receiver_conditions(state, campaign)
    )
    no_deep_unknown = all(
        source.stock_epoch is not None or not source.dependency_blocked
        for source in must
    )
    return bool(
        len(must) <= config.maximum_must_sources
        and deepest <= config.maximum_source_depth
        and coverage >= config.minimum_same_suit_coverage
        and receiver_blockers <= config.maximum_receiver_blockers
        and campaign.estimated_campaign_cost <= config.maximum_estimated_cost
        and no_deep_unknown
        and campaign.readiness in (CampaignReadiness.READY_NOW, CampaignReadiness.ASSEMBLY_LED)
    )


def diagnose_terminal_conversion(
    state: SpiderState,
    campaigns: Sequence[FoundationCampaign],
    *,
    near_config: NearRemovalConfig = NearRemovalConfig(),
) -> TerminalConversionDiagnosis:
    rows = tuple(next_stock_row(state) or ())
    diagnoses = []
    for campaign in campaigns:
        bands = locate_campaign_bands(state, campaign)
        required = []
        for need in campaign.rank_needs:
            source = need.chosen
            if not need.must_excavate or source is None:
                continue
            if source.stock_epoch is not None:
                kind = "stock"
                exposed = False
            else:
                kind = "tableau"
                exposed = bool(source.depth == 0 and not source.dependency_blocked)
            required.append(
                RequiredSourceDiagnosis(
                    source_key=source.source_key,
                    card=source.card,
                    rank=need.rank,
                    location_kind=kind,
                    column=source.column,
                    stock_epoch=source.stock_epoch,
                    depth=source.depth,
                    exposed=exposed,
                    dependency_blocked=source.dependency_blocked,
                    helper_tasks=source.helper_tasks,
                    status=(
                        "stock-supplied"
                        if kind == "stock"
                        else ("exposed" if exposed else "buried/dependency-blocked")
                    ),
                )
            )
        receivers = campaign_receiver_conditions(state, campaign)
        receiver_blockers = tuple(
            item.note for item in receivers if not (item.direct or item.bounded_walkoff)
        )
        empty_count = sum(column.is_empty() for column in state.columns)
        workspace_blockers = (
            (
                f"campaign needs {campaign.space_requirement} workspace columns; {empty_count} empty",
            )
            if campaign.space_requirement > empty_count
            else ()
        )
        mixed_blockers = tuple(
            f"{band.label} covered by {tuple(str(card) for card in band.covering_cards)}"
            for band in bands
            if band.covered and any(card.suit != campaign.suit for card in band.covering_cards)
        )
        contributions = tuple(
            (column, card)
            for column, card in enumerate(rows)
            if card.suit == campaign.suit
        )
        tactical = []
        tactical.extend(item.status for item in required if not item.exposed)
        tactical.extend(receiver_blockers)
        tactical.extend(workspace_blockers)
        near = campaign_is_near_removal(state, campaign, config=near_config)
        macro = bool(
            near
            and campaign.target_removal_epoch is not None
            and campaign.target_removal_epoch <= campaign.current_epoch + 1
        )
        if macro:
            failure = "bounded terminal assembly is structurally qualified"
        elif required:
            failure = f"{len(required)} compulsory sources remain; deepest={max(item.depth for item in required)}"
        elif max((band.length for band in bands), default=0) < near_config.minimum_same_suit_coverage:
            failure = "same-suit fragments do not yet provide terminal coverage"
        elif receiver_blockers:
            failure = "receiver geometry is not bounded-ready"
        elif workspace_blockers:
            failure = "workspace obligation is unsatisfied"
        else:
            failure = "campaign readiness/cost envelope does not qualify as terminal"
        diagnoses.append(
            CampaignTerminalDiagnosis(
                campaign_id=campaign.label,
                readiness=campaign.readiness,
                target_epoch=campaign.target_removal_epoch,
                remaining_must_sources=tuple(required),
                assembled_bands=bands,
                missing_rank_intervals=_missing_intervals(bands),
                receiver_conditions=receivers,
                receiver_blockers=receiver_blockers,
                workspace_blockers=workspace_blockers,
                mixed_suit_blockers=mixed_blockers,
                exact_next_stock_contributions=contributions,
                minimal_bounded_tactical_blockers=tuple(dict.fromkeys(tactical)),
                removal_macro_available=macro,
                removal_macro_failure_reason=failure,
                near_removal=near,
            )
        )
    return TerminalConversionDiagnosis(
        state_key=canonical_state_key(state),
        foundations=len(state.foundations),
        stock_remaining=len(state.stock),
        target_campaigns=tuple(diagnoses),
        summary=(
            "remaining sources, bands, receivers, workspace, mixed blockers, and exact row are structural facts",
            "terminal estimates and misses have no proof-pruning authority",
        ),
    )


def _terminal_priority(state: SpiderState, suit: str, g: int, action_count: int) -> Tuple:
    bands = locate_campaign_bands(state, suit)
    return (
        -len(state.foundations),
        -max((band.length for band in bands), default=0),
        sum(band.covered for band in bands),
        g,
        action_count,
    )


def realize_terminal_campaign_assembly(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    config: TerminalAssemblyConfig = TerminalAssemblyConfig(),
    deadline: Optional[SearchDeadline] = None,
) -> TerminalAssemblyResult:
    """Run a narrow same-epoch tableau beam only for qualified campaigns."""
    started = time.perf_counter()
    if not campaign_is_near_removal(state, campaign, config=config.near_removal):
        return TerminalAssemblyResult(
            TerminalAssemblyStatus.NOT_NEAR_REMOVAL,
            campaign.label,
            (),
            None,
            state.clone(),
            0,
            time.perf_counter() - started,
            False,
            False,
            "transparent near-removal predicate rejected the campaign",
        )
    local_end = started + config.time_limit_s
    start_foundations = len(state.foundations)
    uid = 0
    frontier = [(_terminal_priority(state, campaign.suit, 0, 0), uid, state.clone(), 0, ())]
    best: Dict[CanonicalStateKey, int] = {canonical_state_key(state): 0}
    nodes = 0
    resource_limited = False
    while frontier and nodes < config.max_nodes:
        if time.perf_counter() >= local_end or (deadline is not None and not deadline.checkpoint()):
            resource_limited = True
            break
        _priority, _seq, current, g, actions = heapq.heappop(frontier)
        nodes += 1
        if len(current.foundations) > start_foundations:
            replay = state.clone()
            try:
                replay_cost = replay_actions(replay, list(actions))
                verified = bool(replay_cost == g and states_structurally_equal(replay, current))
            except (ValueError, AssertionError, IndexError):
                verified = False
            return TerminalAssemblyResult(
                TerminalAssemblyStatus.FOUNDATION_REMOVED,
                campaign.label,
                actions,
                g if verified else None,
                current.clone(),
                nodes,
                time.perf_counter() - started,
                verified,
                True,
                "qualified same-epoch terminal assembly removed a foundation",
            )
        children = []
        for action in current.enumerate_moves():
            lifecycle = assess_tableau_move(current, action)
            child = current.clone()
            try:
                paid = child.move(*action, rules=MW_RULES)
            except (ValueError, AssertionError, IndexError):
                continue
            ng = g + paid
            if ng > config.max_added_cost:
                continue
            key = canonical_state_key(child)
            if best.get(key, config.max_added_cost + 1) <= ng:
                continue
            best[key] = ng
            child_actions = actions + (action,)
            children.append(
                (
                    lifecycle.ordering_key(),
                    _terminal_priority(child, campaign.suit, ng, len(child_actions)),
                    action,
                    child,
                    ng,
                    child_actions,
                )
            )
        if config.permit_stock_transition and current.can_deal(MW_RULES):
            child = current.clone()
            paid = child.deal(MW_RULES)
            ng = g + paid
            if ng <= config.max_added_cost:
                key = canonical_state_key(child)
                if best.get(key, config.max_added_cost + 1) > ng:
                    best[key] = ng
                    child_actions = actions + (("deal",),)
                    children.append(
                        ((99,), _terminal_priority(child, campaign.suit, ng, len(child_actions)), ("deal",), child, ng, child_actions)
                    )
        children.sort(key=lambda item: (item[0], item[1], item[2]))
        for _life, priority, _action, child, ng, child_actions in children[: config.beam_width]:
            uid += 1
            heapq.heappush(frontier, (priority, uid, child, ng, child_actions))
        if len(frontier) > config.beam_width:
            frontier = heapq.nsmallest(config.beam_width, frontier)
            heapq.heapify(frontier)
    if nodes >= config.max_nodes:
        resource_limited = True
    return TerminalAssemblyResult(
        (
            TerminalAssemblyStatus.RESOURCE_LIMIT
            if resource_limited
            else TerminalAssemblyStatus.NOT_FOUND_WITHIN_BOUND
        ),
        campaign.label,
        (),
        None,
        state.clone(),
        nodes,
        time.perf_counter() - started,
        False,
        True,
        "bounded terminal assembly miss has no proof authority",
    )
