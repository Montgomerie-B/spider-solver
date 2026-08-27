"""Generic bounded multi-epoch continuity for foundation campaigns.

A corridor is a revalidated hypothesis, never a script or proof claim.  It
composes the existing next-epoch and removal realizers, refreshes the whole
campaign portfolio after every accepted step, and independently replays the
composite edge from its parent state.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import MoveLifecycleAssessment, assess_tableau_move
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.foundation_campaign import (
    CampaignReadiness,
    FoundationCampaign,
    FoundationCampaignPortfolio,
    RankSource,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignIdentity,
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    campaign_receiver_conditions,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionStatus,
    realize_residual_campaign_transition,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.state_identity import canonical_state_key, states_structurally_equal


class CampaignCorridorStatus(str, Enum):
    CONTINUE = "CONTINUE"
    REPLAN_WITH_SAME_CAMPAIGN = "REPLAN_WITH_SAME_CAMPAIGN"
    WAIT_FOR_DEAL = "WAIT_FOR_DEAL"
    SWITCH_SOURCE_COPY = "SWITCH_SOURCE_COPY"
    COMPLETED = "COMPLETED"
    DOMINATED_LOW_VALUE = "DOMINATED_LOW_VALUE"
    BLOCKED_WITHIN_BOUND = "BLOCKED_WITHIN_BOUND"
    INVALIDATED = "INVALIDATED"
    NOT_FOUND_WITHIN_BOUND = "NOT_FOUND_WITHIN_BOUND"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


class CampaignCorridorMilestoneKind(str, Enum):
    EXPOSE_REQUIRED_SOURCE = "EXPOSE_REQUIRED_SOURCE"
    ASSEMBLE_SAME_SUIT_INTERVAL = "ASSEMBLE_SAME_SUIT_INTERVAL"
    WORKSPACE_AVAILABLE = "WORKSPACE_AVAILABLE"
    RECEIVER_GEOMETRY_READY = "RECEIVER_GEOMETRY_READY"
    MUST_DEPENDENCIES_SATISFIED = "MUST_DEPENDENCIES_SATISFIED"
    CAMPAIGN_READINESS = "CAMPAIGN_READINESS"
    STOCK_EPOCH_AT_LEAST = "STOCK_EPOCH_AT_LEAST"
    FOUNDATION_COUNT_AT_LEAST = "FOUNDATION_COUNT_AT_LEAST"


@dataclass(frozen=True)
class CampaignCorridorConfig:
    max_epoch_transitions: int = 2
    max_added_cost: int = 24
    max_nodes: int = 30_000
    time_limit_s: float = 12.0
    beam_width: int = 256
    max_lanes: int = 3
    max_source_combinations: int = 64
    minimum_component_start_s: float = 0.05

    def __post_init__(self) -> None:
        if not 1 <= self.max_epoch_transitions <= 2:
            raise ValueError("corridor epoch horizon must be one or two")
        if self.max_added_cost <= 0 or self.max_nodes <= 0 or self.time_limit_s <= 0:
            raise ValueError("corridor cost, node, and time limits must be positive")
        if self.beam_width <= 0 or self.max_lanes <= 0:
            raise ValueError("corridor beam and lane limits must be positive")


@dataclass(frozen=True)
class CampaignCorridorMilestone:
    kind: CampaignCorridorMilestoneKind
    description: str
    suit: Optional[str] = None
    source_keys: Tuple[str, ...] = ()
    high_rank: Optional[int] = None
    low_rank: Optional[int] = None
    minimum_empty_columns: Optional[int] = None
    target_epoch: Optional[int] = None
    target_foundations: Optional[int] = None
    readiness: Optional[CampaignReadiness] = None

    def is_satisfied(
        self,
        state: SpiderState,
        campaign: Optional[FoundationCampaign],
    ) -> bool:
        if self.kind == CampaignCorridorMilestoneKind.STOCK_EPOCH_AT_LEAST:
            return bool(
                self.target_epoch is not None
                and current_stock_epoch(state, 5) >= self.target_epoch
            )
        if self.kind == CampaignCorridorMilestoneKind.FOUNDATION_COUNT_AT_LEAST:
            return bool(
                self.target_foundations is not None
                and len(state.foundations) >= self.target_foundations
            )
        if self.kind == CampaignCorridorMilestoneKind.WORKSPACE_AVAILABLE:
            target = self.minimum_empty_columns or 1
            return sum(column.is_empty() for column in state.columns) >= target
        if campaign is None:
            return False
        if self.kind == CampaignCorridorMilestoneKind.MUST_DEPENDENCIES_SATISFIED:
            return not any(need.must_excavate for need in campaign.rank_needs)
        if self.kind == CampaignCorridorMilestoneKind.CAMPAIGN_READINESS:
            if self.readiness is None:
                return False
            acceptable = {
                CampaignReadiness.READY_NOW: {CampaignReadiness.READY_NOW},
                CampaignReadiness.ASSEMBLY_LED: {
                    CampaignReadiness.READY_NOW,
                    CampaignReadiness.ASSEMBLY_LED,
                },
                CampaignReadiness.EXCAVATION_LED: {
                    CampaignReadiness.READY_NOW,
                    CampaignReadiness.ASSEMBLY_LED,
                    CampaignReadiness.EXCAVATION_LED,
                },
                CampaignReadiness.STOCK_GATED: set(CampaignReadiness),
                CampaignReadiness.DEFERRED: set(CampaignReadiness),
                CampaignReadiness.BLOCKED: {CampaignReadiness.BLOCKED},
            }[self.readiness]
            return campaign.readiness in acceptable
        if self.kind == CampaignCorridorMilestoneKind.ASSEMBLE_SAME_SUIT_INTERVAL:
            if self.high_rank is None or self.low_rank is None:
                return False
            return any(
                band.movable
                and band.high_rank >= self.high_rank
                and band.low_rank <= self.low_rank
                for band in locate_campaign_bands(state, self.suit or campaign.suit)
            )
        if self.kind == CampaignCorridorMilestoneKind.RECEIVER_GEOMETRY_READY:
            conditions = campaign_receiver_conditions(state, campaign)
            return bool(conditions) and all(
                condition.direct or condition.bounded_walkoff for condition in conditions
            )
        if self.kind == CampaignCorridorMilestoneKind.EXPOSE_REQUIRED_SOURCE:
            visible = {
                source.source_key
                for need in campaign.rank_needs
                for source in need.sources
                if source.usable_by_target and not source.dependency_blocked
            }
            return bool(self.source_keys and set(self.source_keys).issubset(visible))
        return False


@dataclass(frozen=True)
class CampaignCorridor:
    identity: CampaignIdentity
    start_epoch: int
    plausible_target_removal_epoch: int
    maximum_epoch_horizon: int
    current_status: CampaignReadiness
    must_source_keys: Tuple[str, ...]
    interchangeable_source_keys: Tuple[str, ...]
    relevant_future_stock_cards: Tuple[Tuple[int, int, Card], ...]
    actionable_dependencies: Tuple[str, ...]
    blocked_dependencies: Tuple[str, ...]
    pre_deal_obligations: Tuple[str, ...]
    receiver_obligations: Tuple[str, ...]
    workspace_requirements: Tuple[str, ...]
    permanent_same_suit_structure: Tuple[str, ...]
    excavation_chains: Tuple[str, ...]
    mixed_rehandling_liabilities: Tuple[str, ...]
    bounded_exit_obligations: Tuple[str, ...]
    next_milestone: CampaignCorridorMilestone
    final_milestone: CampaignCorridorMilestone
    estimated_paid_expenditure: float
    confidence: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignCorridorLane:
    lane_id: str
    corridor: CampaignCorridor
    portfolio_rank: int
    rationale: Tuple[str, ...]


@dataclass(frozen=True)
class CampaignCorridorStep:
    phase: str
    epoch_before: int
    epoch_after: int
    campaign_label_before: str
    campaign_label_after: Optional[str]
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_cost: int
    nodes_expanded: int
    elapsed_seconds: float
    milestones_reached: Tuple[str, ...]
    lifecycle: Tuple[MoveLifecycleAssessment, ...]
    revalidation: CampaignCorridorStatus
    reason: str


@dataclass(frozen=True)
class CampaignCorridorAssessment:
    status: CampaignCorridorStatus
    reasons: Tuple[str, ...]
    alternatives_remaining: Tuple[str, ...]
    original_must_sources: Tuple[str, ...]
    current_must_sources: Tuple[str, ...]
    source_copy_switched: bool
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignCorridorMarginalValue:
    deal_now_total_cost: Optional[int]
    prepared_post_deal_cost: Optional[int]
    preparation_cost: int
    prepared_total_cost: Optional[int]
    bounded_saving: Optional[int]
    comparable: bool
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class CampaignCorridorResult:
    corridor: CampaignCorridor
    status: CampaignCorridorStatus
    start_state: SpiderState
    end_state: SpiderState
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_added_cost: Optional[int]
    nodes_expanded: int
    elapsed_seconds: float
    deals_applied: int
    foundation_count_before: int
    foundation_count_after: int
    foundation_suits_added: Tuple[str, ...]
    steps: Tuple[CampaignCorridorStep, ...]
    assessment: CampaignCorridorAssessment
    independent_replay_verified: bool
    replayed_cost: Optional[int]
    path_hash: str
    endpoint_hash: str
    stop_reason: str
    marginal_values: Tuple[CampaignCorridorMarginalValue, ...] = ()
    proof_pruning_allowed: bool = False


def _chosen_sources(campaign: FoundationCampaign) -> Tuple[RankSource, ...]:
    return tuple(need.chosen for need in campaign.rank_needs if need.chosen is not None)


def _must_keys(campaign: FoundationCampaign) -> Tuple[str, ...]:
    return tuple(
        need.chosen.source_key
        for need in campaign.rank_needs
        if need.must_excavate and need.chosen is not None
    )


def _alternative_keys(campaign: FoundationCampaign) -> Tuple[str, ...]:
    selected = set(_must_keys(campaign))
    return tuple(
        dict.fromkeys(
            source.source_key
            for need in campaign.rank_needs
            for source in need.sources
            if source.source_key not in selected
        )
    )


def _path_hash(actions: Sequence[Action]) -> str:
    return hashlib.blake2b(repr(tuple(actions)).encode("utf-8"), digest_size=8).hexdigest()


def build_campaign_corridor(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    config: CampaignCorridorConfig,
) -> CampaignCorridor:
    target = campaign.target_removal_epoch
    if target is None:
        raise ValueError("campaign has no target removal epoch")
    start_epoch = current_stock_epoch(state, 5)
    if campaign.current_epoch != start_epoch:
        raise ValueError("campaign snapshot does not match the corridor state")
    must = _must_keys(campaign)
    stock_cards = tuple(
        (plan.epoch, incoming.column, incoming.card)
        for plan in campaign.stock_plan
        for incoming in plan.incoming
        if incoming.selected_source
        and incoming.card.suit == campaign.suit
        and plan.epoch <= start_epoch + config.max_epoch_transitions
    )
    actionable = tuple(
        source.source_key
        for source in _chosen_sources(campaign)
        if source.usable_by_target and not source.dependency_blocked
    )
    blocked = tuple(
        source.source_key
        for source in _chosen_sources(campaign)
        if source.dependency_blocked
    )
    excavations = tuple(
        f"c{project.column + 1}:peels={project.required_peels}:"
        f"sources={','.join(project.source_keys)}"
        for project in campaign.prerequisite_excavation_projects
    )
    structure = tuple(
        f"{fragment.top_rank}-{fragment.bottom_rank}{campaign.suit}@c{fragment.column + 1}"
        for fragment in campaign.current_same_suit_fragments
    )
    liabilities = tuple(
        f"c{project.column + 1}:estimated temporary placements="
        f"{project.estimated_prep_cost}"
        for project in campaign.prerequisite_excavation_projects
        if project.estimated_prep_cost
    )
    exits = tuple(
        campaign.space_plan.reasons
        + ((campaign.space_plan.next_deal_policy,) if campaign.space_plan.next_deal_policy else ())
    )
    next_epoch = min(target, start_epoch + 1)
    next_milestone = CampaignCorridorMilestone(
        CampaignCorridorMilestoneKind.STOCK_EPOCH_AT_LEAST,
        f"reach stock epoch {next_epoch} with campaign identity revalidated",
        suit=campaign.suit,
        target_epoch=next_epoch,
    )
    final_milestone = CampaignCorridorMilestone(
        CampaignCorridorMilestoneKind.FOUNDATION_COUNT_AT_LEAST,
        f"remove the next {campaign.suit.upper()} foundation",
        suit=campaign.suit,
        target_foundations=len(state.foundations) + 1,
    )
    return CampaignCorridor(
        identity=CampaignIdentity(campaign.suit, campaign.copy_index, target),
        start_epoch=start_epoch,
        plausible_target_removal_epoch=target,
        maximum_epoch_horizon=config.max_epoch_transitions,
        current_status=campaign.readiness,
        must_source_keys=must,
        interchangeable_source_keys=_alternative_keys(campaign),
        relevant_future_stock_cards=stock_cards,
        actionable_dependencies=actionable,
        blocked_dependencies=blocked,
        pre_deal_obligations=tuple(
            step.description
            for step in campaign.critical_path
            if step.phase in ("excavate", "pre_deal", "workspace")
        ),
        receiver_obligations=campaign.pre_deal_receiver_requirements,
        workspace_requirements=(
            campaign.space_plan.enabled_action,
            campaign.space_plan.next_deal_policy,
        ),
        permanent_same_suit_structure=structure,
        excavation_chains=excavations,
        mixed_rehandling_liabilities=liabilities,
        bounded_exit_obligations=tuple(item for item in exits if item),
        next_milestone=next_milestone,
        final_milestone=final_milestone,
        estimated_paid_expenditure=campaign.estimated_campaign_cost,
        confidence=campaign.confidence,
    )


def generate_campaign_corridor_lanes(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    config: CampaignCorridorConfig = CampaignCorridorConfig(),
    portfolio: Optional[FoundationCampaignPortfolio] = None,
) -> Tuple[CampaignCorridorLane, ...]:
    """Return a deterministic bounded portfolio derived only from live facts."""
    current = portfolio or analyze_foundation_campaigns(
        state,
        cards=cards,
        max_source_combinations=config.max_source_combinations,
    )
    candidates = [
        campaign
        for campaign in current.campaigns
        if campaign.target_removal_epoch is not None
        and campaign.target_removal_epoch - current.current_epoch
        <= config.max_epoch_transitions
        and campaign.readiness != CampaignReadiness.BLOCKED
        and not campaign.blockers
    ]
    lanes: List[CampaignCorridorLane] = []
    for rank, campaign in enumerate(candidates[: config.max_lanes]):
        corridor = build_campaign_corridor(state, campaign, config=config)
        lanes.append(
            CampaignCorridorLane(
                lane_id=f"corridor:{campaign.label}:d{corridor.plausible_target_removal_epoch}",
                corridor=corridor,
                portfolio_rank=rank,
                rationale=(
                    "derived from the current whole-campaign portfolio",
                    "alternative campaign lanes remain available",
                    "bounded miss has no proof authority",
                ),
            )
        )
    return tuple(lanes)


def compare_campaign_corridor_marginal_value(
    *,
    deal_now_total_cost: Optional[int],
    prepared_post_deal_cost: Optional[int],
    preparation_cost: int,
) -> CampaignCorridorMarginalValue:
    """Compare two routes to the same structural milestone, including prep."""
    if preparation_cost < 0:
        raise ValueError("preparation cost cannot be negative")
    comparable = deal_now_total_cost is not None and prepared_post_deal_cost is not None
    prepared_total = (
        preparation_cost + prepared_post_deal_cost
        if prepared_post_deal_cost is not None
        else None
    )
    saving = (
        deal_now_total_cost - prepared_total
        if comparable and prepared_total is not None and deal_now_total_cost is not None
        else None
    )
    return CampaignCorridorMarginalValue(
        deal_now_total_cost,
        prepared_post_deal_cost,
        preparation_cost,
        prepared_total,
        saving,
        comparable,
        (
            "matched bounded campaign milestone comparison"
            if comparable
            else "bounded arms did not both reach the same milestone"
        ),
    )


def _lifecycle_for_actions(
    state: SpiderState, actions: Sequence[Action]
) -> Tuple[MoveLifecycleAssessment, ...]:
    cursor = state.clone()
    out: List[MoveLifecycleAssessment] = []
    for action in actions:
        if action == ("deal",):
            replay_actions(cursor, [action])
            continue
        assessment = assess_tableau_move(cursor, action)
        out.append(assessment)
        replay_actions(cursor, [action])
    return tuple(out)


def _revalidate(
    state: SpiderState,
    cards: Sequence[Card],
    identity: CampaignIdentity,
    previous: FoundationCampaign,
    *,
    config: CampaignCorridorConfig,
) -> Tuple[
    CampaignCorridorStatus,
    Optional[FoundationCampaign],
    FoundationCampaignPortfolio,
    Tuple[str, ...],
]:
    portfolio = analyze_foundation_campaigns(
        state,
        cards=cards,
        max_source_combinations=config.max_source_combinations,
    )
    try:
        current = portfolio.campaign_for(identity.suit, identity.copy_index)
    except KeyError:
        return CampaignCorridorStatus.COMPLETED, None, portfolio, (
            "target ordinal is no longer outstanding",
        )
    if current.blockers or current.readiness == CampaignReadiness.BLOCKED:
        return CampaignCorridorStatus.INVALIDATED, current, portfolio, tuple(
            current.blockers or ("campaign became structurally blocked",)
        )
    previous_keys = set(_must_keys(previous))
    current_keys = set(_must_keys(current))
    if previous_keys != current_keys:
        return CampaignCorridorStatus.SWITCH_SOURCE_COPY, current, portfolio, (
            "fresh portfolio selected interchangeable physical sources",
        )
    if current.target_removal_epoch != previous.target_removal_epoch:
        return CampaignCorridorStatus.REPLAN_WITH_SAME_CAMPAIGN, current, portfolio, (
            "same campaign identity received a new live target epoch",
        )
    if current.target_removal_epoch is not None and current.target_removal_epoch > current.current_epoch:
        return CampaignCorridorStatus.WAIT_FOR_DEAL, current, portfolio, (
            "campaign remains credible and its exact required row is still ahead",
        )
    return CampaignCorridorStatus.CONTINUE, current, portfolio, (
        "fresh whole-state campaign facts still support the corridor",
    )


def realize_campaign_corridor(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    *,
    config: CampaignCorridorConfig = CampaignCorridorConfig(),
    deadline: Optional[SearchDeadline] = None,
) -> CampaignCorridorResult:
    """Compose at most two revalidated epoch steps toward one foundation."""
    started = time.perf_counter()
    owned_deadline = deadline is None
    resource = deadline or SearchDeadline.from_seconds(
        config.time_limit_s, analysis_node_limit=config.max_nodes
    )
    corridor = build_campaign_corridor(start_state, campaign, config=config)
    state = start_state.clone()
    current = campaign
    actions: List[Action] = []
    roles: List[str] = []
    steps: List[CampaignCorridorStep] = []
    nodes = 0
    cost = 0
    start_foundations = len(start_state.foundations)
    alternatives: Tuple[str, ...] = ()
    current_must = corridor.must_source_keys
    source_switched = False
    status = CampaignCorridorStatus.CONTINUE
    reasons: Tuple[str, ...] = ("corridor initialized from live campaign facts",)

    if corridor.plausible_target_removal_epoch - corridor.start_epoch > config.max_epoch_transitions:
        status = CampaignCorridorStatus.INVALIDATED
        reasons = ("target epoch lies outside the configured corridor horizon",)

    for _transition in range(config.max_epoch_transitions):
        if status in (
            CampaignCorridorStatus.INVALIDATED,
            CampaignCorridorStatus.COMPLETED,
            CampaignCorridorStatus.RESOURCE_LIMIT,
        ):
            break
        if len(state.foundations) > start_foundations:
            status = CampaignCorridorStatus.COMPLETED
            reasons = ("one foundation was removed",)
            break
        remaining_cost = config.max_added_cost - cost
        remaining_nodes = min(config.max_nodes - nodes, resource.node_slice(config.max_nodes - nodes))
        component = (
            "campaign_current_epoch_realizer"
            if current.target_removal_epoch is not None
            and current.target_removal_epoch <= current.current_epoch
            else (
                "campaign_removal_realizer"
                if current.target_removal_epoch == current.current_epoch + 1
                else "campaign_epoch_realizer"
            )
        )
        seconds = resource.time_slice(
            component,
            min(config.time_limit_s, max(0.0, config.time_limit_s - (time.perf_counter() - started))),
        )
        if (
            remaining_cost <= 0
            or remaining_nodes <= 0
            or seconds < config.minimum_component_start_s
            or not resource.can_start(
                component,
                minimum_seconds=config.minimum_component_start_s,
                minimum_nodes=1,
            )
        ):
            status = CampaignCorridorStatus.RESOURCE_LIMIT
            reasons = ("insufficient shared resource to start the next bounded corridor step",)
            break

        before = state.clone()
        epoch_before = current_stock_epoch(state, 5)
        campaign_before = current
        transition_status = None
        if (
            current.target_removal_epoch is not None
            and current.target_removal_epoch <= epoch_before
        ):
            with resource.measure(component):
                result = realize_residual_campaign_transition(
                    state,
                    current,
                    cards,
                    max_added_cost=remaining_cost,
                    max_nodes=remaining_nodes,
                    time_limit_s=seconds,
                    beam_width=config.beam_width,
                    max_source_combinations=config.max_source_combinations,
                )
            step_actions = result.actions
            step_roles = result.action_roles
            step_cost = result.corrected_added_cost
            step_nodes = result.nodes_expanded
            step_elapsed = result.elapsed_seconds
            step_reason = result.stop_reason
            step_ok = result.independent_replay_verified and step_cost is not None
            state = result.resulting_state.clone() if step_ok else state
            transition_status = result.status
            removal_status = None
        elif current.target_removal_epoch == epoch_before + 1:
            with resource.measure(component):
                result = realize_campaign_to_removal_epoch(
                    state,
                    current,
                    cards,
                    max_added_cost=remaining_cost,
                    max_nodes=remaining_nodes,
                    time_limit_s=seconds,
                    beam_width=config.beam_width,
                )
            step_actions = result.actions
            step_roles = result.action_roles
            step_cost = result.corrected_added_cost
            step_nodes = result.nodes_expanded
            step_elapsed = result.elapsed_seconds
            step_reason = result.stop_reason
            step_ok = result.independent_replay_verified and step_cost is not None
            state = result.end_state.clone() if step_ok else state
            removal_status = result.status
        else:
            with resource.measure(component):
                result = realize_campaign_to_next_epoch(
                    state,
                    current,
                    cards,
                    max_added_cost=remaining_cost,
                    max_nodes=remaining_nodes,
                    time_limit_s=seconds,
                )
            step_actions = result.actions
            step_roles = result.action_roles
            step_cost = result.corrected_added_cost
            step_nodes = result.nodes_expanded
            step_elapsed = result.elapsed_seconds
            step_reason = result.stop_reason
            step_ok = result.independent_replay_verified and step_cost is not None
            state = result.resulting_state.clone() if step_ok else state
            removal_status = None
        nodes += step_nodes
        resource.consume_nodes(step_nodes)
        if not step_ok or not step_actions:
            status = (
                CampaignCorridorStatus.RESOURCE_LIMIT
                if (
                    removal_status == CampaignRemovalStatus.RESOURCE_LIMIT
                    or transition_status == CampaignTransitionStatus.RESOURCE_LIMIT
                    or getattr(result, "status", None) == CampaignRealizationStatus.RESOURCE_LIMIT
                )
                else CampaignCorridorStatus.NOT_FOUND_WITHIN_BOUND
            )
            reasons = (step_reason, "bounded miss has no proof authority")
            break

        assert step_cost is not None
        actions.extend(step_actions)
        roles.extend(step_roles)
        cost += step_cost
        lifecycle = _lifecycle_for_actions(before, step_actions)
        backend_resource_limited = bool(
            removal_status == CampaignRemovalStatus.RESOURCE_LIMIT
            or transition_status == CampaignTransitionStatus.RESOURCE_LIMIT
            or getattr(result, "status", None) == CampaignRealizationStatus.RESOURCE_LIMIT
        )
        if backend_resource_limited and len(state.foundations) == start_foundations:
            status = CampaignCorridorStatus.RESOURCE_LIMIT
            reasons = (step_reason, "bounded miss has no proof authority")
            steps.append(
                CampaignCorridorStep(
                    phase=(
                        "current_epoch_removal"
                        if transition_status is not None
                        else ("removal_epoch" if removal_status is not None else "advance_epoch")
                    ),
                    epoch_before=epoch_before,
                    epoch_after=current_stock_epoch(state, 5),
                    campaign_label_before=campaign_before.label,
                    campaign_label_after=None,
                    actions=tuple(step_actions),
                    action_roles=tuple(step_roles),
                    corrected_cost=step_cost,
                    nodes_expanded=step_nodes,
                    elapsed_seconds=step_elapsed,
                    milestones_reached=(),
                    lifecycle=lifecycle,
                    revalidation=CampaignCorridorStatus.RESOURCE_LIMIT,
                    reason="; ".join(reasons),
                )
            )
            break
        with resource.measure("corridor_revalidation"):
            validation, refreshed, portfolio, validation_reasons = _revalidate(
                state, cards, corridor.identity, campaign_before, config=config
            )
        alternatives = tuple(
            item.label
            for item in portfolio.campaigns
            if (item.suit, item.copy_index)
            != (corridor.identity.suit, corridor.identity.copy_index)
        )
        source_switched = source_switched or validation == CampaignCorridorStatus.SWITCH_SOURCE_COPY
        if refreshed is not None:
            current = refreshed
            current_must = _must_keys(refreshed)
        milestone_names = tuple(
            milestone.kind.value
            for milestone in (corridor.next_milestone, corridor.final_milestone)
            if milestone.is_satisfied(state, refreshed)
        )
        steps.append(
            CampaignCorridorStep(
                phase=(
                    "current_epoch_removal"
                    if transition_status is not None
                    else ("removal_epoch" if removal_status is not None else "advance_epoch")
                ),
                epoch_before=epoch_before,
                epoch_after=current_stock_epoch(state, 5),
                campaign_label_before=campaign_before.label,
                campaign_label_after=refreshed.label if refreshed is not None else None,
                actions=tuple(step_actions),
                action_roles=tuple(step_roles),
                corrected_cost=step_cost,
                nodes_expanded=step_nodes,
                elapsed_seconds=step_elapsed,
                milestones_reached=milestone_names,
                lifecycle=lifecycle,
                revalidation=validation,
                reason="; ".join(validation_reasons),
            )
        )
        if len(state.foundations) > start_foundations:
            status = CampaignCorridorStatus.COMPLETED
            reasons = ("foundation milestone satisfied and whole portfolio refreshed",)
            break
        if validation == CampaignCorridorStatus.INVALIDATED:
            status = validation
            reasons = validation_reasons
            break
        if current_stock_epoch(state, 5) - corridor.start_epoch >= config.max_epoch_transitions:
            status = CampaignCorridorStatus.BLOCKED_WITHIN_BOUND
            reasons = ("epoch horizon exhausted before foundation removal",)
            break
        status = validation
        reasons = validation_reasons

    replay = start_state.clone()
    replayed_cost: Optional[int] = None
    replay_ok = False
    try:
        replayed_cost = replay_actions(replay, list(actions))
        replay_ok = bool(
            replayed_cost == cost and states_structurally_equal(replay, state)
        )
    except (ValueError, AssertionError, IndexError):
        replay_ok = False
    if not replay_ok and actions:
        status = CampaignCorridorStatus.INVALIDATED
        reasons = ("composite corridor failed independent replay",)

    added = tuple(
        sequence[0].suit
        for sequence in state.foundations[start_foundations:]
        if sequence
    )
    assessment = CampaignCorridorAssessment(
        status=status,
        reasons=reasons,
        alternatives_remaining=alternatives,
        original_must_sources=corridor.must_source_keys,
        current_must_sources=current_must,
        source_copy_switched=source_switched,
    )
    elapsed = time.perf_counter() - started
    if owned_deadline and elapsed > config.time_limit_s + 2.0:
        status = CampaignCorridorStatus.RESOURCE_LIMIT
        assessment = CampaignCorridorAssessment(
            status,
            ("corridor exceeded its cooperative deadline tolerance",),
            alternatives,
            corridor.must_source_keys,
            current_must,
            source_switched,
        )
    return CampaignCorridorResult(
        corridor=corridor,
        status=status,
        start_state=start_state.clone(),
        end_state=state.clone(),
        actions=tuple(actions),
        action_roles=tuple(roles),
        corrected_added_cost=cost if replay_ok else None,
        nodes_expanded=nodes,
        elapsed_seconds=elapsed,
        deals_applied=sum(action == ("deal",) for action in actions),
        foundation_count_before=start_foundations,
        foundation_count_after=len(state.foundations),
        foundation_suits_added=added,
        steps=tuple(steps),
        assessment=assessment,
        independent_replay_verified=replay_ok,
        replayed_cost=replayed_cost,
        path_hash=_path_hash(actions),
        endpoint_hash=format(zobrist(state), "x"),
        stop_reason="; ".join(assessment.reasons),
    )


def deduplicate_corridor_results(
    results: Iterable[CampaignCorridorResult],
) -> Tuple[CampaignCorridorResult, ...]:
    """Keep the lowest-cost independently replayed result per exact endpoint."""
    best = {}
    for result in results:
        key = canonical_state_key(result.end_state)
        previous = best.get(key)
        cost = result.corrected_added_cost
        previous_cost = previous.corrected_added_cost if previous is not None else None
        if previous is None or (
            cost is not None and (previous_cost is None or cost < previous_cost)
        ):
            best[key] = result
    return tuple(best[key] for key in sorted(best, key=repr))
