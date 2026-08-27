"""Residual conversion evidence between consecutive foundation removals.

This module is deliberately an analysis/orchestration layer.  It describes
live campaigns, checkpoint diversity, and the exact opportunity represented
by the next stock row.  It does not own a whole-game search and none of its
heuristic records has proof-pruning authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    CampaignCorridorLane,
    generate_campaign_corridor_lanes,
)
from spider.planner.deal_timing import IncomingRowImpact
from spider.planner.economic_project_realizer import StructuralMeasurement
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProjectKind,
)
from spider.planner.foundation_campaign import (
    CampaignReadiness,
    FoundationCampaign,
)
from spider.planner.foundation_campaign_removal import (
    campaign_receiver_conditions,
    locate_campaign_bands,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.stock_reception import next_stock_row
from spider.rules import MW_RULES
from spider.state_identity import CanonicalStateKey, canonical_state_key


class ResidualConversionStatus(str, Enum):
    FOUNDATION_REMOVED = "FOUNDATION_REMOVED"
    NEAR_REMOVAL = "NEAR_REMOVAL"
    STRUCTURAL_ADVANCE = "STRUCTURAL_ADVANCE"
    DEAL_REQUIRED = "DEAL_REQUIRED"
    BLOCKED_WITHIN_BOUND = "BLOCKED_WITHIN_BOUND"
    INCONCLUSIVE = "INCONCLUSIVE"


class ResidualLaneKind(str, Enum):
    CURRENT_EPOCH_REMOVAL = "CURRENT_EPOCH_REMOVAL"
    ALTERNATE_CAMPAIGN = "ALTERNATE_CAMPAIGN"
    PERMANENT_STRUCTURE = "PERMANENT_STRUCTURE"
    DEAL_NOW_UNLOCK = "DEAL_NOW_UNLOCK"
    PREPARE_THEN_DEAL = "PREPARE_THEN_DEAL"


class DealPurpose(str, Enum):
    STRATEGIC_UNLOCK = "STRATEGIC_UNLOCK"
    PREPARATION_PAYOFF = "PREPARATION_PAYOFF"
    CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY = "CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY"
    ESCAPE_ONLY = "ESCAPE_ONLY"
    INCONCLUSIVE = "INCONCLUSIVE"


class CheckpointDimension(str, Enum):
    LOWEST_G = "LOWEST_G"
    LOWEST_MUST_BURDEN = "LOWEST_MUST_BURDEN"
    BEST_NEXT_FOUNDATION_READINESS = "BEST_NEXT_FOUNDATION_READINESS"
    LOWEST_FACE_DOWN = "LOWEST_FACE_DOWN"
    STRONGEST_PERMANENT_STRUCTURE = "STRONGEST_PERMANENT_STRUCTURE"
    BEST_WORKSPACE = "BEST_WORKSPACE"
    BEST_STOCK_OPTION = "BEST_STOCK_OPTION"


_READINESS_ORDER = {
    CampaignReadiness.READY_NOW: 0,
    CampaignReadiness.ASSEMBLY_LED: 1,
    CampaignReadiness.EXCAVATION_LED: 2,
    CampaignReadiness.STOCK_GATED: 3,
    CampaignReadiness.DEFERRED: 4,
    CampaignReadiness.BLOCKED: 5,
}


@dataclass(frozen=True)
class NextFoundationReadiness:
    campaign_label: str
    suit: str
    copy_index: int
    campaign_status: CampaignReadiness
    must_dependencies_remaining: int
    deepest_required_source: int
    exact_stock_dependencies: int
    assembled_same_suit_rank_coverage: int
    workspace_requirement: int
    receiver_conditions_total: int
    receiver_conditions_ready: int
    bounded_estimated_cost_to_removal: float
    bounded_removal_macro_available: bool
    target_epoch: Optional[int]
    proof_pruning_allowed: bool = False

    @property
    def near_removal(self) -> bool:
        return bool(
            self.bounded_removal_macro_available
            and (
                self.campaign_status == CampaignReadiness.READY_NOW
                or self.must_dependencies_remaining <= 2
                or self.assembled_same_suit_rank_coverage >= 10
            )
        )

    def ordering_key(self) -> Tuple:
        return (
            _READINESS_ORDER[self.campaign_status],
            not self.bounded_removal_macro_available,
            self.must_dependencies_remaining,
            -self.assembled_same_suit_rank_coverage,
            self.deepest_required_source,
            self.workspace_requirement,
            self.bounded_estimated_cost_to_removal,
            self.campaign_label,
        )


@dataclass(frozen=True)
class ExactNextRowPreview:
    column: int
    card: Card
    receiver: Optional[Card]
    same_suit_receiver: bool
    mixed_rank_receiver: bool
    buries_permanent_run: bool
    supplies_selected_campaign_rank: bool
    immediate_walkoff_count: int


@dataclass(frozen=True)
class StockOpportunityAssessment:
    purpose: DealPurpose
    dependencies_supplied: int
    blocked_high_value_work_unlocked: Tuple[str, ...]
    exact_receivers_satisfied: int
    readiness_improvements: Tuple[str, ...]
    stable_same_suit_joins_created: int
    useful_walkoffs_enabled: int
    workspace_delta: int
    permanent_joins_lost: int
    useful_exposed_tops_buried: int
    workspace_consumed: int
    current_epoch_projects_blocked: Tuple[str, ...]
    mixed_boundaries_created: int
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    @property
    def has_concrete_gain(self) -> bool:
        return bool(
            self.dependencies_supplied
            or self.blocked_high_value_work_unlocked
            or self.exact_receivers_satisfied
            or self.readiness_improvements
            or self.stable_same_suit_joins_created
            or self.useful_walkoffs_enabled
            or self.workspace_delta > 0
        )

    def ordering_key(self) -> Tuple:
        purpose_order = {
            DealPurpose.STRATEGIC_UNLOCK: 0,
            DealPurpose.PREPARATION_PAYOFF: 1,
            DealPurpose.CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY: 2,
            DealPurpose.INCONCLUSIVE: 3,
            DealPurpose.ESCAPE_ONLY: 4,
        }
        return (
            purpose_order[self.purpose],
            -len(self.readiness_improvements),
            -len(self.blocked_high_value_work_unlocked),
            -self.dependencies_supplied,
            -self.exact_receivers_satisfied,
            self.permanent_joins_lost,
            len(self.current_epoch_projects_blocked),
            self.mixed_boundaries_created,
        )


@dataclass(frozen=True)
class ResidualCampaignLane:
    lane_id: str
    kind: ResidualLaneKind
    campaign_label: Optional[str]
    target_foundations: int
    current_epoch: int
    target_epoch: Optional[int]
    near_removal: bool
    actions_required_are_structural: bool
    rationale: Tuple[str, ...]
    corridor_lane: Optional[CampaignCorridorLane] = None
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class FoundationCheckpointProfile:
    state_key: CanonicalStateKey
    g: int
    foundations: int
    foundation_suits: Tuple[str, ...]
    stock_remaining: int
    stock_epoch: int
    face_down_count: int
    empty_columns: Tuple[int, ...]
    fully_open_columns: Tuple[int, ...]
    legal_mobility: int
    stable_same_suit_joins: int
    same_suit_run_mass: int
    longest_same_suit_run: int
    mixed_boundaries: int
    rehandling_debt: float
    total_campaign_must_burden: int
    minimum_campaign_remaining_estimate: float
    ready_removal_campaigns: Tuple[str, ...]
    near_removal_campaigns: Tuple[str, ...]
    current_epoch_actionable_high_value_projects: Tuple[str, ...]
    next_epoch_blocked_high_value_projects: Tuple[str, ...]
    next_foundation_readiness: Tuple[NextFoundationReadiness, ...]
    exact_next_row_impact: Tuple[ExactNextRowPreview, ...]
    residual_corridor_candidates: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    @property
    def best_readiness(self) -> Optional[NextFoundationReadiness]:
        return self.next_foundation_readiness[0] if self.next_foundation_readiness else None


@dataclass(frozen=True)
class FoundationCheckpointPortfolio:
    profiles: Tuple[FoundationCheckpointProfile, ...]
    represented_dimensions: Tuple[Tuple[CheckpointDimension, CanonicalStateKey], ...]
    exact_state_suppressions: int
    diversity_suppressions: int
    maximum: int
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class ResidualInvestmentAccounting:
    checkpoint_foundations_before: int
    checkpoint_foundations_after: int
    paid_cost: int
    reveals: int
    must_burden_removed: int
    stable_structure_created: int
    mixed_debt_incurred: int
    workspace_delta: int
    stock_rows_consumed: int
    rehandling_debt_delta: float
    resulting_next_foundation_cost: Optional[int]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class ResidualCampaignAssessment:
    status: ResidualConversionStatus
    checkpoint: FoundationCheckpointProfile
    lanes: Tuple[ResidualCampaignLane, ...]
    selected_lane_id: Optional[str]
    reasons: Tuple[str, ...]
    proof_pruning_allowed: bool = False


def _must_total(measurement: StructuralMeasurement) -> int:
    return sum(value for _label, value in measurement.campaign_must_burden)


def _campaign_readiness(
    state: SpiderState, campaign: FoundationCampaign
) -> NextFoundationReadiness:
    chosen_remaining = [
        need.chosen
        for need in campaign.rank_needs
        if need.must_excavate and need.chosen is not None
    ]
    deepest = max(
        (
            source.depth + source.excavation_peels + source.closure_prefix_hops
            for source in chosen_remaining
        ),
        default=0,
    )
    stock_dependencies = sum(
        need.chosen is not None and need.chosen.stock_epoch is not None
        for need in campaign.rank_needs
    )
    coverage = max(
        (band.length for band in locate_campaign_bands(state, campaign)),
        default=0,
    )
    receivers = campaign_receiver_conditions(state, campaign)
    receiver_ready = sum(item.direct or item.bounded_walkoff for item in receivers)
    macro = bool(
        campaign.target_removal_epoch is not None
        and campaign.target_removal_epoch <= campaign.current_epoch + 1
        and campaign.readiness != CampaignReadiness.BLOCKED
        and not campaign.blockers
    )
    return NextFoundationReadiness(
        campaign_label=campaign.label,
        suit=campaign.suit,
        copy_index=campaign.copy_index,
        campaign_status=campaign.readiness,
        must_dependencies_remaining=sum(need.must_excavate for need in campaign.rank_needs),
        deepest_required_source=deepest,
        exact_stock_dependencies=stock_dependencies,
        assembled_same_suit_rank_coverage=coverage,
        workspace_requirement=campaign.space_requirement,
        receiver_conditions_total=len(receivers),
        receiver_conditions_ready=receiver_ready,
        bounded_estimated_cost_to_removal=campaign.estimated_campaign_cost,
        bounded_removal_macro_available=macro,
        target_epoch=campaign.target_removal_epoch,
    )


def analyze_next_foundation_readiness(
    state: SpiderState, analysis: EconomicAnalysisResult
) -> Tuple[NextFoundationReadiness, ...]:
    values = tuple(
        _campaign_readiness(state, campaign)
        for campaign in analysis.campaign_portfolio.campaigns
    )
    return tuple(sorted(values, key=NextFoundationReadiness.ordering_key))


def _high_value_project_sets(
    state: SpiderState, analysis: EconomicAnalysisResult
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    current_epoch = current_stock_epoch(state, 5)
    current = []
    blocked = []
    for project in analysis.frontier.ordered_projects:
        if project.assessment.frontier_tier > EconomicFrontierTier.POSITIVE_INVESTMENT:
            continue
        direct = project.action is not None and state.can_move(*project.action)
        if project.earliest_useful_epoch <= current_epoch and direct:
            current.append(project.project_id)
        elif project.earliest_useful_epoch > current_epoch or not direct:
            blocked.append(project.project_id)
    return tuple(current), tuple(blocked)


def _next_row_preview(
    state: SpiderState, analysis: EconomicAnalysisResult
) -> Tuple[ExactNextRowPreview, ...]:
    row = next_stock_row(state)
    if row is None:
        return ()
    selected = {
        (need.chosen.card.suit, need.chosen.card.rank)
        for campaign in analysis.campaign_portfolio.campaigns
        for need in campaign.rank_needs
        if need.chosen is not None and need.chosen.stock_epoch is not None
    }
    dealt = state.clone()
    dealt.deal(MW_RULES)
    immediate_out_counts = {
        column: sum(1 for move in dealt.enumerate_moves() if move[0] == column)
        for column in range(len(dealt.columns))
    }
    previews = []
    for column, card in enumerate(row):
        receiver = state.columns[column].top()
        same = bool(
            receiver is not None
            and receiver.suit == card.suit
            and receiver.rank - 1 == card.rank
        )
        mixed = bool(
            receiver is not None
            and receiver.suit != card.suit
            and receiver.rank - 1 == card.rank
        )
        trailing = 1
        up = state.columns[column].face_up
        while (
            trailing < len(up)
            and up[-trailing - 1].suit == up[-trailing].suit
            and up[-trailing - 1].rank - 1 == up[-trailing].rank
        ):
            trailing += 1
        previews.append(
            ExactNextRowPreview(
                column=column,
                card=card,
                receiver=receiver,
                same_suit_receiver=same,
                mixed_rank_receiver=mixed,
                buries_permanent_run=trailing >= 2 and not same,
                supplies_selected_campaign_rank=(card.suit, card.rank) in selected,
                immediate_walkoff_count=immediate_out_counts[column],
            )
        )
    return tuple(previews)


def build_foundation_checkpoint_profile(
    state: SpiderState,
    *,
    g: int,
    analysis: EconomicAnalysisResult,
    measurement: StructuralMeasurement,
    residual_corridor_candidates: Sequence[str] = (),
) -> FoundationCheckpointProfile:
    readiness = analyze_next_foundation_readiness(state, analysis)
    current_projects, blocked_projects = _high_value_project_sets(state, analysis)
    return FoundationCheckpointProfile(
        state_key=canonical_state_key(state),
        g=g,
        foundations=len(state.foundations),
        foundation_suits=tuple(seq[0].suit for seq in state.foundations if seq),
        stock_remaining=len(state.stock),
        stock_epoch=current_stock_epoch(state, 5),
        face_down_count=measurement.face_down_count,
        empty_columns=measurement.empty_columns,
        fully_open_columns=measurement.fully_open_columns,
        legal_mobility=measurement.legal_move_count,
        stable_same_suit_joins=measurement.stable_same_suit_joins,
        same_suit_run_mass=measurement.same_suit_run_mass,
        longest_same_suit_run=measurement.longest_same_suit_run,
        mixed_boundaries=measurement.mixed_suit_boundaries,
        rehandling_debt=measurement.rehandling_debt,
        total_campaign_must_burden=_must_total(measurement),
        minimum_campaign_remaining_estimate=min(
            (item.estimated_campaign_cost for item in analysis.campaign_portfolio.campaigns),
            default=0.0,
        ),
        ready_removal_campaigns=tuple(
            item.campaign_label
            for item in readiness
            if item.campaign_status == CampaignReadiness.READY_NOW
        ),
        near_removal_campaigns=tuple(
            item.campaign_label for item in readiness if item.near_removal
        ),
        current_epoch_actionable_high_value_projects=current_projects,
        next_epoch_blocked_high_value_projects=blocked_projects,
        next_foundation_readiness=readiness,
        exact_next_row_impact=_next_row_preview(state, analysis),
        residual_corridor_candidates=tuple(residual_corridor_candidates),
    )


def generate_residual_campaign_lanes(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    analysis: EconomicAnalysisResult,
    config: CampaignCorridorConfig,
    maximum: int = 5,
) -> Tuple[ResidualCampaignLane, ...]:
    corridors = generate_campaign_corridor_lanes(
        state,
        cards,
        config=config,
        portfolio=analysis.campaign_portfolio,
    )
    readiness = {
        item.campaign_label: item
        for item in analyze_next_foundation_readiness(state, analysis)
    }
    lanes = []
    for index, corridor in enumerate(corridors):
        identity = corridor.corridor.identity
        item = readiness.get(identity.label)
        current = identity.target_epoch <= current_stock_epoch(state, 5)
        lanes.append(
            ResidualCampaignLane(
                lane_id=f"residual:{corridor.lane_id}",
                kind=(
                    ResidualLaneKind.CURRENT_EPOCH_REMOVAL
                    if current
                    else ResidualLaneKind.ALTERNATE_CAMPAIGN
                ),
                campaign_label=identity.label,
                target_foundations=len(state.foundations) + 1,
                current_epoch=current_stock_epoch(state, 5),
                target_epoch=identity.target_epoch,
                near_removal=bool(item and item.near_removal),
                actions_required_are_structural=True,
                rationale=(
                    "campaign identity comes from the fresh complete portfolio",
                    "foundation count increase is the terminal milestone",
                    "bounded failure has no proof authority",
                ),
                corridor_lane=corridor,
            )
        )
    permanent = next(
        (
            project
            for project in analysis.frontier.ordered_projects
            if project.kind
            in (
                EconomicProjectKind.PERMANENT_JOIN,
                EconomicProjectKind.ASSEMBLE_BAND,
                EconomicProjectKind.REMOVE_MIXED_BOUNDARY,
            )
            and project.action is not None
            and state.can_move(*project.action)
        ),
        None,
    )
    if permanent is not None:
        lanes.append(
            ResidualCampaignLane(
                lane_id=f"residual:permanent:{permanent.project_id}",
                kind=ResidualLaneKind.PERMANENT_STRUCTURE,
                campaign_label=None,
                target_foundations=len(state.foundations) + 1,
                current_epoch=current_stock_epoch(state, 5),
                target_epoch=None,
                near_removal=False,
                actions_required_are_structural=True,
                rationale=(
                    "retain permanent current-epoch work beside campaign lanes",
                    permanent.description,
                ),
            )
        )
    if state.stock:
        lanes.append(
            ResidualCampaignLane(
                lane_id="residual:deal-now",
                kind=ResidualLaneKind.DEAL_NOW_UNLOCK,
                campaign_label=None,
                target_foundations=len(state.foundations) + 1,
                current_epoch=current_stock_epoch(state, 5),
                target_epoch=current_stock_epoch(state, 5) + 1,
                near_removal=False,
                actions_required_are_structural=False,
                rationale=(
                    "Deal remains legal and first-class",
                    "exact gain and current-epoch opportunity loss must be compared",
                ),
            )
        )
        if permanent is not None:
            lanes.append(
                ResidualCampaignLane(
                    lane_id=f"residual:prepare-deal:{permanent.project_id}",
                    kind=ResidualLaneKind.PREPARE_THEN_DEAL,
                    campaign_label=None,
                    target_foundations=len(state.foundations) + 1,
                    current_epoch=current_stock_epoch(state, 5),
                    target_epoch=current_stock_epoch(state, 5) + 1,
                    near_removal=False,
                    actions_required_are_structural=True,
                    rationale=(
                        "preparation cost must be included in matched total cost",
                        permanent.description,
                    ),
                )
            )
    # Preserve one lane per semantic family before filling corridor rank order.
    out = []
    for kind in ResidualLaneKind:
        match = next((lane for lane in lanes if lane.kind == kind), None)
        if match is not None and match not in out:
            out.append(match)
        if len(out) >= maximum:
            return tuple(out)
    for lane in lanes:
        if lane not in out:
            out.append(lane)
        if len(out) >= maximum:
            break
    return tuple(out)


def assess_stock_opportunity(
    before: FoundationCheckpointProfile,
    after: FoundationCheckpointProfile,
    *,
    impacts: Sequence[IncomingRowImpact],
    preparation_paid_cost: int = 0,
    preparation_repaid: bool = False,
) -> StockOpportunityAssessment:
    before_current = set(before.current_epoch_actionable_high_value_projects)
    after_current = set(after.current_epoch_actionable_high_value_projects)
    readiness_before = {item.campaign_label: item for item in before.next_foundation_readiness}
    readiness_after = {item.campaign_label: item for item in after.next_foundation_readiness}
    improvements = tuple(
        label
        for label, post in sorted(readiness_after.items())
        if label not in readiness_before
        or post.ordering_key() < readiness_before[label].ordering_key()
    )
    unlocked = tuple(sorted(after_current - before_current))
    blocked = tuple(sorted(before_current - after_current))
    dependencies = sum(item.campaign_dependency_removed for item in impacts)
    receivers = sum(item.exact_receiver_success for item in impacts)
    walkoffs = sum(bool(item.immediate_out_moves) for item in impacts)
    stable_gain = max(0, after.stable_same_suit_joins - before.stable_same_suit_joins)
    lost = max(0, before.stable_same_suit_joins - after.stable_same_suit_joins)
    mixed = max(0, after.mixed_boundaries - before.mixed_boundaries)
    workspace_delta = len(after.empty_columns) - len(before.empty_columns)
    consumed = max(0, -workspace_delta)
    buried = sum(item.buries_permanent_structure for item in impacts)
    concrete = bool(dependencies or receivers or unlocked or improvements or stable_gain or walkoffs)
    if preparation_paid_cost and preparation_repaid:
        purpose = DealPurpose.PREPARATION_PAYOFF
    elif concrete:
        purpose = DealPurpose.STRATEGIC_UNLOCK
    elif not before_current and before.near_removal_campaigns == ():
        purpose = DealPurpose.CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY
    elif not concrete and not receivers and not dependencies:
        purpose = DealPurpose.ESCAPE_ONLY
    else:
        purpose = DealPurpose.INCONCLUSIVE
    return StockOpportunityAssessment(
        purpose=purpose,
        dependencies_supplied=dependencies,
        blocked_high_value_work_unlocked=unlocked,
        exact_receivers_satisfied=receivers,
        readiness_improvements=improvements,
        stable_same_suit_joins_created=stable_gain,
        useful_walkoffs_enabled=walkoffs,
        workspace_delta=workspace_delta,
        permanent_joins_lost=lost,
        useful_exposed_tops_buried=buried,
        workspace_consumed=consumed,
        current_epoch_projects_blocked=blocked,
        mixed_boundaries_created=mixed,
        rationale=(
            f"exact next row supplied {dependencies} selected dependencies",
            f"unlocked={unlocked}; blocked={blocked}",
            f"readiness_improvements={improvements}",
            "classification orders search only and cannot proof-prune",
        ),
    )


def _profile_dimension_key(
    profile: FoundationCheckpointProfile, dimension: CheckpointDimension
) -> Tuple:
    readiness = profile.best_readiness
    if dimension == CheckpointDimension.LOWEST_G:
        return (profile.g, profile.face_down_count, repr(profile.state_key))
    if dimension == CheckpointDimension.LOWEST_MUST_BURDEN:
        return (profile.total_campaign_must_burden, profile.g, repr(profile.state_key))
    if dimension == CheckpointDimension.BEST_NEXT_FOUNDATION_READINESS:
        return (
            readiness.ordering_key() if readiness is not None else (99,),
            profile.g,
            repr(profile.state_key),
        )
    if dimension == CheckpointDimension.LOWEST_FACE_DOWN:
        return (profile.face_down_count, profile.g, repr(profile.state_key))
    if dimension == CheckpointDimension.STRONGEST_PERMANENT_STRUCTURE:
        return (
            -profile.stable_same_suit_joins,
            -profile.same_suit_run_mass,
            profile.mixed_boundaries,
            profile.rehandling_debt,
            profile.g,
            repr(profile.state_key),
        )
    if dimension == CheckpointDimension.BEST_WORKSPACE:
        return (
            -len(profile.empty_columns),
            -len(profile.fully_open_columns),
            -profile.legal_mobility,
            profile.g,
            repr(profile.state_key),
        )
    concrete_next_row_gains = sum(
        int(item.supplies_selected_campaign_rank)
        + int(item.same_suit_receiver)
        + item.immediate_walkoff_count
        for item in profile.exact_next_row_impact
    )
    concrete_next_row_liabilities = sum(
        int(item.buries_permanent_run) + int(item.mixed_rank_receiver)
        for item in profile.exact_next_row_impact
    )
    return (
        -concrete_next_row_gains,
        concrete_next_row_liabilities,
        -profile.stock_remaining,
        -(len(profile.ready_removal_campaigns) + len(profile.near_removal_campaigns)),
        profile.g,
        repr(profile.state_key),
    )


def retain_foundation_checkpoint_portfolio(
    profiles: Iterable[FoundationCheckpointProfile],
    *,
    maximum: int = 6,
) -> FoundationCheckpointPortfolio:
    if maximum <= 0:
        raise ValueError("checkpoint portfolio maximum must be positive")
    exact = {}
    exact_suppressions = 0
    for profile in profiles:
        previous = exact.get(profile.state_key)
        if previous is None or profile.g < previous.g:
            if previous is not None:
                exact_suppressions += 1
            exact[profile.state_key] = profile
        else:
            exact_suppressions += 1
    candidates = tuple(
        sorted(
            exact.values(),
            key=lambda item: (
                -item.foundations,
                _profile_dimension_key(item, CheckpointDimension.LOWEST_G),
            ),
        )
    )
    selected = []
    dimensions = []
    for dimension in CheckpointDimension:
        if not candidates:
            break
        winner = min(candidates, key=lambda item: _profile_dimension_key(item, dimension))
        dimensions.append((dimension, winner.state_key))
        if winner not in selected:
            selected.append(winner)
        if len(selected) >= maximum:
            break
    for candidate in candidates:
        if candidate not in selected:
            selected.append(candidate)
        if len(selected) >= maximum:
            break
    return FoundationCheckpointPortfolio(
        profiles=tuple(selected),
        represented_dimensions=tuple(dimensions),
        exact_state_suppressions=exact_suppressions,
        diversity_suppressions=max(0, len(candidates) - len(selected)),
        maximum=maximum,
    )


def residual_investment_accounting(
    before: FoundationCheckpointProfile,
    after: FoundationCheckpointProfile,
) -> ResidualInvestmentAccounting:
    foundation_delta = after.foundations - before.foundations
    return ResidualInvestmentAccounting(
        checkpoint_foundations_before=before.foundations,
        checkpoint_foundations_after=after.foundations,
        paid_cost=after.g - before.g,
        reveals=before.face_down_count - after.face_down_count,
        must_burden_removed=(
            before.total_campaign_must_burden - after.total_campaign_must_burden
        ),
        stable_structure_created=(
            after.stable_same_suit_joins - before.stable_same_suit_joins
        ),
        mixed_debt_incurred=after.mixed_boundaries - before.mixed_boundaries,
        workspace_delta=len(after.empty_columns) - len(before.empty_columns),
        stock_rows_consumed=max(0, (before.stock_remaining - after.stock_remaining) // 10),
        rehandling_debt_delta=after.rehandling_debt - before.rehandling_debt,
        resulting_next_foundation_cost=after.g - before.g if foundation_delta > 0 else None,
    )


def analyze_residual_campaign(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    g: int,
    analysis: EconomicAnalysisResult,
    measurement: StructuralMeasurement,
    corridor_config: CampaignCorridorConfig = CampaignCorridorConfig(),
    maximum_lanes: int = 5,
) -> ResidualCampaignAssessment:
    lanes = generate_residual_campaign_lanes(
        state,
        cards,
        analysis=analysis,
        config=corridor_config,
        maximum=maximum_lanes,
    )
    profile = build_foundation_checkpoint_profile(
        state,
        g=g,
        analysis=analysis,
        measurement=measurement,
        residual_corridor_candidates=tuple(lane.lane_id for lane in lanes),
    )
    if profile.ready_removal_campaigns:
        status = ResidualConversionStatus.NEAR_REMOVAL
    elif profile.near_removal_campaigns:
        status = ResidualConversionStatus.NEAR_REMOVAL
    elif any(lane.kind == ResidualLaneKind.CURRENT_EPOCH_REMOVAL for lane in lanes):
        status = ResidualConversionStatus.STRUCTURAL_ADVANCE
    elif state.stock:
        status = ResidualConversionStatus.DEAL_REQUIRED
    else:
        status = ResidualConversionStatus.INCONCLUSIVE
    selected = next((lane.lane_id for lane in lanes if lane.near_removal), None)
    if selected is None and lanes:
        selected = lanes[0].lane_id
    return ResidualCampaignAssessment(
        status=status,
        checkpoint=profile,
        lanes=lanes,
        selected_lane_id=selected,
        reasons=(
            "fresh post-transition portfolio and exact state profile generated",
            "current-epoch, alternate, permanent, Deal-now, and prepared-Deal lanes remain diverse",
            "only a foundation-count increase completes conversion",
        ),
    )
