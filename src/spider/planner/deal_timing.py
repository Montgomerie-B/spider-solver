"""Strategic timing for one irreversible Spider stock-epoch transition.

The deal is a first-class strategic alternative.  This module compares an
exact DEAL-NOW clone with a deliberately small set of replay-verified
PREPARE-THEN-DEAL clones.  It never searches a complete game and every
heuristic/economic field remains outside proof pruning.

No benchmark deal, move, suit, column, incumbent, or external score is a
production constant in this module.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.economic_project_realizer import (
    EconomicProjectRealizationStatus,
    EconomicProjectResourceConfig,
    StructuralMeasurement,
    freeze_economic_predictions,
    measure_structural_state,
    probe_project_actionability,
    project_predicate,
    realize_economic_project,
    run_downstream_probe,
)
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProject,
    analyze_economic_projects,
)
from spider.planner.incumbent_budget import IncumbentBudget, build_incumbent_budget
from spider.planner.objective_realizer import (
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.stock_reception import (
    LandingKind,
    analyze_stock_reception,
    next_stock_row,
)
from spider.planner.strategic_objectives import StrategicObjective
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal


class DealTimingStatus(str, Enum):
    DEAL_NOW = "DEAL_NOW"
    PREPARE_THEN_DEAL = "PREPARE_THEN_DEAL"
    DEAL_CURRENTLY_ILLEGAL = "DEAL_CURRENTLY_ILLEGAL"
    NO_STOCK_REMAINING = "NO_STOCK_REMAINING"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    NO_USEFUL_COMPARISON = "NO_USEFUL_COMPARISON"


class DealTimingDecisionKind(str, Enum):
    DEAL_NOW_PREFERRED = "DEAL_NOW_PREFERRED"
    PREPARATION_PREFERRED = "PREPARATION_PREFERRED"
    DEAL_REQUIRED_FOR_ACTIONABILITY = "DEAL_REQUIRED_FOR_ACTIONABILITY"
    DEAL_ILLEGAL_UNTIL_EMPTY_FILLED = "DEAL_ILLEGAL_UNTIL_EMPTY_FILLED"
    COMPARISON_INCONCLUSIVE = "COMPARISON_INCONCLUSIVE"
    NO_STOCK_REMAINING = "NO_STOCK_REMAINING"


class DealTimingReason(str, Enum):
    LOWER_TOTAL_BOUNDED_COST = "LOWER_TOTAL_BOUNDED_COST"
    NO_PREPARATION_REPAYS_COST = "NO_PREPARATION_REPAYS_COST"
    STOCK_UNLOCKS_HIGH_VALUE_WORK = "STOCK_UNLOCKS_HIGH_VALUE_WORK"
    EMPTY_COLUMN_BLOCKS_RESTRICTED_PROFILE = "EMPTY_COLUMN_BLOCKS_RESTRICTED_PROFILE"
    NO_COMPARABLE_DOWNSTREAM_TARGET = "NO_COMPARABLE_DOWNSTREAM_TARGET"
    STOCK_EXHAUSTED = "STOCK_EXHAUSTED"


@dataclass(frozen=True)
class DealTimingConfig:
    max_preparation_projects: int = 2
    max_preparation_cost: int = 8
    hard_preparation_cost_cap: int = 12
    max_h1_candidates: int = 6
    max_h2_candidates: int = 4
    tactical_max_cost: int = 4
    tactical_max_nodes: int = 20_000
    tactical_time_limit_s: float = 6.0
    downstream_max_cost: int = 10
    downstream_max_nodes: int = 50_000
    downstream_time_limit_s: float = 15.0

    def __post_init__(self) -> None:
        if self.max_preparation_projects not in (1, 2, 3):
            raise ValueError("preparation horizon must be H1, H2, or H3")
        if not 0 <= self.max_preparation_cost <= self.hard_preparation_cost_cap <= 12:
            raise ValueError("preparation ceiling must be non-negative and no greater than 12")


@dataclass(frozen=True)
class IncomingRowImpact:
    target_column: int
    card: Card
    current_receiver: Optional[Card]
    landing: LandingKind
    same_suit_adjacency: bool
    mixed_suit_descending_adjacency: bool
    buries_permanent_structure: bool
    lands_on_mixed_boundary: bool
    campaign_dependency_removed: bool
    supplies_excavation_duplicate: bool
    automatic_foundation_removal: bool
    immediate_out_moves: Tuple[Tuple[int, int, int], ...]
    same_suit_out_moves: Tuple[Tuple[int, int, int], ...]
    workspace_consequence: str
    exact_receiver_success: bool


@dataclass(frozen=True)
class ActionabilityTransition:
    high_value_actionable_before: Tuple[str, ...]
    high_value_blocked_before: Tuple[str, ...]
    high_value_actionable_after: Tuple[str, ...]
    newly_actionable_after_deal: Tuple[str, ...]
    blocked_by_deal: Tuple[str, ...]
    campaign_readiness_before: Tuple[Tuple[str, str], ...]
    campaign_readiness_after: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class DealPreparationCandidate:
    candidate_id: str
    horizon: int
    source_kinds: Tuple[str, ...]
    source_project_ids: Tuple[str, ...]
    actions: Tuple[Action, ...]
    action_labels: Tuple[str, ...]
    corrected_cost: int
    resulting_state: SpiderState
    state_key_hex: str
    independent_replay_verified: bool
    rationale: Tuple[str, ...]


@dataclass(frozen=True)
class DealCounterfactual:
    label: str
    status: DealTimingStatus
    preparation: Optional[DealPreparationCandidate]
    preparation_cost: int
    deal_cost: int
    total_added_cost: int
    actions: Tuple[Action, ...]
    post_deal_state: Optional[SpiderState]
    result_key_hex: Optional[str]
    independent_replay_verified: bool
    incoming_impacts: Tuple[IncomingRowImpact, ...]
    pre_deal_measurement: Optional[StructuralMeasurement]
    measurement: Optional[StructuralMeasurement]
    economic_analysis: Optional[EconomicAnalysisResult]
    economic_frontier: Tuple[Tuple[str, int], ...]
    estimated_remaining_work: Optional[float]
    actionability: Optional[ActionabilityTransition]
    incumbent_budget: Optional[IncumbentBudget]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class DownstreamCostComparison:
    objective_id: Optional[str]
    matched_max_cost: int
    matched_max_nodes: int
    matched_time_limit_s: float
    deal_now_status: str
    deal_now_cost: Optional[int]
    prepared_status: str
    prepared_cost: Optional[int]
    preparation_plus_downstream_cost: Optional[int]
    bounded_saving_before_preparation_cost: Optional[int]
    bounded_net_gain: Optional[int]
    comparable: bool
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class MarginalPreparationValue:
    candidate_id: str
    preparation_paid_cost: int
    preparation_rehandling_debt: float
    stable_joins_broken_during_preparation: int
    workspace_consumed_during_preparation: int
    permanent_joins_retained_delta: int
    same_suit_mass_delta: int
    mixed_liabilities_avoided: int
    exact_receiver_success_delta: int
    campaign_must_burden_reduction: int
    critical_dependencies_removed: int
    newly_actionable_project_delta: int
    workspace_delta: int
    mobility_delta: int
    estimated_future_work_avoided: float
    downstream: DownstreamCostComparison


@dataclass(frozen=True)
class DealTimingDecision:
    kind: DealTimingDecisionKind
    selected_candidate_id: Optional[str]
    reason_codes: Tuple[DealTimingReason, ...]
    reasons: Tuple[str, ...]
    legal_tableau_moves_remaining: int
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DealTimingAssessment:
    config: DealTimingConfig
    incoming_row: Tuple[Card, ...]
    deal_now: DealCounterfactual
    preparations: Tuple[DealPreparationCandidate, ...]
    prepared_deals: Tuple[DealCounterfactual, ...]
    marginal_values: Tuple[MarginalPreparationValue, ...]
    decision: DealTimingDecision
    prediction_fingerprint: str
    prospective_frozen: bool = True
    canonical_loaded: bool = False


@dataclass(frozen=True)
class DealEconomicProjectAdapter:
    project_id: str
    description: str
    immediate_paid_cost: int
    incoming_row: Tuple[Card, ...]
    decision_kind: DealTimingDecisionKind
    preparation_candidate_id: Optional[str]
    proof_pruning_allowed: bool = False


def _action_label(action: Action) -> str:
    if action == ("deal",):
        return "deal"
    src, dst, k = action
    return f"move {src + 1} {dst + 1} {k}"


def _state_key_hex(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode("utf-8")).hexdigest()


def _must_total(measurement: StructuralMeasurement) -> int:
    return sum(value for _label, value in measurement.campaign_must_burden)


def _trailing_same_suit_run_length(state: SpiderState, column: int) -> int:
    cards = state.columns[column].face_up
    if not cards:
        return 0
    length = 1
    for index in range(len(cards) - 1, 0, -1):
        lower, upper = cards[index - 1], cards[index]
        if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
            length += 1
        else:
            break
    return length


def _campaign_must_keys(analysis: EconomicAnalysisResult) -> set[Tuple[str, int]]:
    return {
        (campaign.suit, need.rank)
        for campaign in analysis.campaign_portfolio.campaigns
        for need in campaign.rank_needs
        if need.must_excavate
    }


def _replaceable_stock_keys(analysis: EconomicAnalysisResult) -> set[Tuple[str, int]]:
    return {
        (value.card.suit, value.card.rank)
        for value in analysis.reveal_values
        if value.stock_copy_epochs
    }


def analyze_exact_incoming_row(
    pre_deal_state: SpiderState,
    post_deal_state: SpiderState,
    before: EconomicAnalysisResult,
    after: EconomicAnalysisResult,
) -> Tuple[IncomingRowImpact, ...]:
    """Return a transparent per-card impact for the exact next stock row."""
    row = next_stock_row(pre_deal_state)
    if row is None:
        return ()
    must_before = _campaign_must_keys(before)
    must_after = _campaign_must_keys(after)
    replaceable = _replaceable_stock_keys(before)
    impacts: List[IncomingRowImpact] = []
    for column, incoming in enumerate(row):
        top = pre_deal_state.columns[column].top()
        same = bool(
            top is not None
            and top.suit == incoming.suit
            and top.rank - 1 == incoming.rank
        )
        mixed_desc = bool(
            top is not None
            and top.suit != incoming.suit
            and top.rank - 1 == incoming.rank
        )
        pre_empty = pre_deal_state.columns[column].is_empty()
        landing = (
            LandingKind.EMPTY_LANDING
            if pre_empty
            else (
                LandingKind.SAME_SUIT_CONNECT
                if same
                else LandingKind.MIXED_RANK_CONNECT
                if mixed_desc
                else LandingKind.NON_CONNECTING
            )
        )
        outs = tuple(
            action
            for action in post_deal_state.enumerate_moves()
            if action[0] == column and action[2] == 1
        )
        same_outs = tuple(
            action
            for action in outs
            if (
                post_deal_state.columns[action[1]].top() is not None
                and post_deal_state.columns[action[1]].top().suit == incoming.suit
            )
        )
        run_before = _trailing_same_suit_run_length(pre_deal_state, column)
        candidate_tail = list(pre_deal_state.columns[column].face_up[-12:]) + [incoming]
        auto = bool(
            len(candidate_tail) >= 13
            and SpiderState.is_movable_run(candidate_tail[-13:])
            and candidate_tail[-13].rank == 13
        )
        workspace = (
            "empty workspace receives a known card; immediate walk-off exists"
            if pre_empty and outs
            else "empty workspace is occupied by the incoming card"
            if pre_empty
            else "non-empty column remains occupied"
        )
        key = (incoming.suit, incoming.rank)
        impacts.append(
            IncomingRowImpact(
                target_column=column,
                card=incoming,
                current_receiver=top,
                landing=landing,
                same_suit_adjacency=same,
                mixed_suit_descending_adjacency=mixed_desc,
                buries_permanent_structure=run_before >= 2 and not same,
                lands_on_mixed_boundary=top is not None and top.suit != incoming.suit,
                campaign_dependency_removed=key in must_before and key not in must_after,
                supplies_excavation_duplicate=key in replaceable,
                automatic_foundation_removal=auto,
                immediate_out_moves=outs,
                same_suit_out_moves=same_outs,
                workspace_consequence=workspace,
                exact_receiver_success=same,
            )
        )
    return tuple(impacts)


def _immediately_actionable(
    state: SpiderState, analysis: EconomicAnalysisResult
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Cheap hard/depth-one actionability, separate from economic value."""
    actionable: List[str] = []
    blocked: List[str] = []
    for project in analysis.frontier.ordered_projects:
        if project.assessment.frontier_tier > EconomicFrontierTier.POSITIVE_INVESTMENT:
            continue
        predicate, _reason = project_predicate(state, project)
        found = False
        if project.action is not None:
            found = state.can_move(*project.action)
        elif predicate is not None:
            if predicate.is_satisfied(state):
                found = True
            else:
                for action in state.enumerate_moves():
                    clone = state.clone()
                    clone.move(*action)
                    if predicate.is_satisfied(clone):
                        found = True
                        break
        (actionable if found else blocked).append(project.project_id)
    return tuple(actionable), tuple(blocked)


def actionability_transition(
    before_state: SpiderState,
    after_state: SpiderState,
    before: EconomicAnalysisResult,
    after: EconomicAnalysisResult,
) -> ActionabilityTransition:
    actionable_before, blocked_before = _immediately_actionable(before_state, before)
    actionable_after, _blocked_after = _immediately_actionable(after_state, after)
    before_set, after_set = set(actionable_before), set(actionable_after)
    return ActionabilityTransition(
        high_value_actionable_before=actionable_before,
        high_value_blocked_before=blocked_before,
        high_value_actionable_after=actionable_after,
        newly_actionable_after_deal=tuple(sorted(after_set - before_set)),
        blocked_by_deal=tuple(sorted(before_set - after_set)),
        campaign_readiness_before=tuple(
            (campaign.label, campaign.readiness.value)
            for campaign in before.campaign_portfolio.campaigns
        ),
        campaign_readiness_after=tuple(
            (campaign.label, campaign.readiness.value)
            for campaign in after.campaign_portfolio.campaigns
        ),
    )


def build_preparation_candidate(
    start_state: SpiderState,
    actions: Sequence[Action],
    *,
    candidate_id: str,
    horizon: int,
    source_kinds: Sequence[str],
    source_project_ids: Sequence[str] = (),
    rationale: Sequence[str] = (),
    max_cost: int = 12,
) -> Optional[DealPreparationCandidate]:
    """Build and independently replay one bounded tableau-only preparation."""
    if not actions or any(action == ("deal",) for action in actions):
        return None
    state = start_state.clone()
    try:
        cost = replay_actions(state, list(actions))
    except (AssertionError, ValueError):
        return None
    if cost > max_cost:
        return None
    replay = start_state.clone()
    replay_cost = replay_actions(replay, list(actions))
    verified = replay_cost == cost and states_structurally_equal(state, replay)
    if not verified:
        return None
    key = _state_key_hex(state)
    return DealPreparationCandidate(
        candidate_id=candidate_id,
        horizon=horizon,
        source_kinds=tuple(source_kinds),
        source_project_ids=tuple(source_project_ids),
        actions=tuple(actions),
        action_labels=tuple(_action_label(action) for action in actions),
        corrected_cost=cost,
        resulting_state=state,
        state_key_hex=key,
        independent_replay_verified=True,
        rationale=tuple(rationale),
    )


def _candidate_key(candidate: DealPreparationCandidate) -> Tuple[str, int]:
    return candidate.state_key_hex, candidate.corrected_cost


def _deduplicate_candidates(
    candidates: Iterable[DealPreparationCandidate], limit: int
) -> Tuple[DealPreparationCandidate, ...]:
    best: Dict[str, DealPreparationCandidate] = {}
    for candidate in candidates:
        incumbent = best.get(candidate.state_key_hex)
        if incumbent is None or (
            candidate.corrected_cost,
            len(candidate.actions),
            candidate.candidate_id,
        ) < (
            incumbent.corrected_cost,
            len(incumbent.actions),
            incumbent.candidate_id,
        ):
            best[candidate.state_key_hex] = candidate
    ordered = sorted(
        best.values(),
        key=lambda item: (
            item.corrected_cost,
            item.horizon,
            item.source_kinds,
            item.candidate_id,
        ),
    )
    return tuple(ordered[:limit])


def _h1_preparation_candidates(
    state: SpiderState,
    cards: Sequence[Card],
    config: DealTimingConfig,
    *,
    prefix: str = "h1",
) -> Tuple[DealPreparationCandidate, ...]:
    economic = analyze_economic_projects(state, cards=cards)
    resource = EconomicProjectResourceConfig(
        added_cost_bounds=(config.tactical_max_cost,),
        max_nodes_per_bound=config.tactical_max_nodes,
        time_limit_s_per_bound=config.tactical_time_limit_s,
        allow_foundation_increase=True,
        downstream_max_cost=config.downstream_max_cost,
        downstream_max_nodes=config.downstream_max_nodes,
        downstream_time_limit_s=config.downstream_time_limit_s,
    )
    found: List[DealPreparationCandidate] = []
    checked = 0
    for project in economic.frontier.ordered_projects:
        if project.assessment.frontier_tier > EconomicFrontierTier.POSITIVE_INVESTMENT:
            continue
        if checked >= config.max_h1_candidates:
            break
        actionability = probe_project_actionability(state, project, config=resource)
        checked += 1
        if not actionability.actionable_current_epoch or not actionability.probe_actions:
            continue
        candidate = build_preparation_candidate(
            state,
            actionability.probe_actions,
            candidate_id=f"{prefix}-project-{project.project_id}",
            horizon=1,
            source_kinds=(f"economic-tier-{int(project.assessment.frontier_tier)}",),
            source_project_ids=(project.project_id,),
            rationale=(
                "currently actionable economic project",
                actionability.reason,
            ),
            max_cost=config.max_preparation_cost,
        )
        if candidate is not None:
            found.append(candidate)

    reception = analyze_stock_reception(
        state,
        cards=cards,
        shaping_max_cost=min(3, config.max_preparation_cost),
        run_shaping_probe=True,
    )
    for index, result in enumerate(reception.shaping_results):
        if not result.found or not result.path:
            continue
        candidate = build_preparation_candidate(
            state,
            result.path,
            candidate_id=f"{prefix}-receiver-{index}-{result.objective.code}",
            horizon=1,
            source_kinds=("exact-stock-receiver",),
            rationale=(result.objective.description,) + result.notes,
            max_cost=config.max_preparation_cost,
        )
        if candidate is not None:
            found.append(candidate)

    # Broadest-level raw fallback is deliberately structural and small.  It is
    # never "play until stuck" and it does not enumerate long arbitrary paths.
    for index, action in enumerate(state.enumerate_moves()):
        assessment = assess_tableau_move(state, action, discover_exit=False)
        if assessment.placement_class not in (
            PlacementClass.STABLE_SAME_SUIT_JOIN,
            PlacementClass.WORKSPACE_PARK,
        ):
            continue
        candidate = build_preparation_candidate(
            state,
            (action,),
            candidate_id=f"{prefix}-raw-{index}",
            horizon=1,
            source_kinds=("broad-structural-fallback",),
            rationale=(
                f"{assessment.placement_class.value}: {assessment.future_exit_route}",
            ),
            max_cost=config.max_preparation_cost,
        )
        if candidate is not None:
            found.append(candidate)
        if len(found) >= config.max_h1_candidates * 2:
            break
    return _deduplicate_candidates(found, config.max_h1_candidates)


def generate_preparation_candidates(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    config: DealTimingConfig = DealTimingConfig(),
) -> Tuple[DealPreparationCandidate, ...]:
    """Generate H1 and small H2 non-redundant preparation alternatives."""
    h1 = _h1_preparation_candidates(state, cards, config)
    if config.max_preparation_projects < 2:
        return h1
    combined: List[DealPreparationCandidate] = list(h1)
    h2_count = 0
    for first in h1:
        if h2_count >= config.max_h2_candidates:
            break
        remaining = config.max_preparation_cost - first.corrected_cost
        if remaining < 0:
            continue
        follow_config = DealTimingConfig(
            max_preparation_projects=1,
            max_preparation_cost=remaining,
            hard_preparation_cost_cap=config.hard_preparation_cost_cap,
            max_h1_candidates=min(3, config.max_h1_candidates),
            max_h2_candidates=0,
            tactical_max_cost=min(config.tactical_max_cost, remaining),
            tactical_max_nodes=config.tactical_max_nodes,
            tactical_time_limit_s=config.tactical_time_limit_s,
            downstream_max_cost=config.downstream_max_cost,
            downstream_max_nodes=config.downstream_max_nodes,
            downstream_time_limit_s=config.downstream_time_limit_s,
        )
        for second in _h1_preparation_candidates(
            first.resulting_state, cards, follow_config, prefix=f"h2-{h2_count}"
        ):
            ids = first.source_project_ids + second.source_project_ids
            if len(ids) != len(set(ids)):
                continue
            candidate = build_preparation_candidate(
                state,
                first.actions + second.actions,
                candidate_id=f"h2-{first.candidate_id}+{second.candidate_id}",
                horizon=2,
                source_kinds=first.source_kinds + second.source_kinds,
                source_project_ids=ids,
                rationale=first.rationale + second.rationale,
                max_cost=config.max_preparation_cost,
            )
            if candidate is None or candidate.state_key_hex == first.state_key_hex:
                continue
            combined.append(candidate)
            h2_count += 1
            if h2_count >= config.max_h2_candidates:
                break
    return _deduplicate_candidates(
        combined, config.max_h1_candidates + config.max_h2_candidates
    )


def simulate_deal_counterfactual(
    original_state: SpiderState,
    cards: Sequence[Card],
    *,
    spent_cost: int,
    incumbent_cost: Optional[int],
    preparation: Optional[DealPreparationCandidate] = None,
) -> DealCounterfactual:
    """Clone, optionally prepare, apply exactly one deal, and reanalyse."""
    if len(original_state.stock) < 10:
        return DealCounterfactual(
            "DEAL NOW" if preparation is None else preparation.candidate_id,
            DealTimingStatus.NO_STOCK_REMAINING,
            preparation,
            preparation.corrected_cost if preparation else 0,
            0,
            preparation.corrected_cost if preparation else 0,
            preparation.actions if preparation else (),
            None,
            None,
            False,
            (),
            None,
            None,
            None,
            (),
            None,
            None,
            None,
            ("stock has fewer than ten cards",),
        )
    prepared = original_state.clone()
    prep_actions: Tuple[Action, ...] = ()
    prep_cost = 0
    if preparation is not None:
        prep_actions = preparation.actions
        prep_cost = replay_actions(prepared, list(prep_actions))
        if prep_cost != preparation.corrected_cost or not states_structurally_equal(
            prepared, preparation.resulting_state
        ):
            raise AssertionError("preparation replay drift before deal")
    if not prepared.can_deal(MW_RULES):
        return DealCounterfactual(
            "DEAL NOW" if preparation is None else preparation.candidate_id,
            DealTimingStatus.DEAL_CURRENTLY_ILLEGAL,
            preparation,
            prep_cost,
            0,
            prep_cost,
            prep_actions,
            None,
            None,
            False,
            (),
            None,
            None,
            None,
            (),
            None,
            None,
            None,
            ("active rules profile rejects this deal state",),
        )
    before = analyze_economic_projects(prepared, cards=cards)
    pre_deal_measurement = measure_structural_state(
        prepared, cards=cards, analysis=before
    )
    post = prepared.clone()
    deal_paid = post.deal(MW_RULES)
    after = analyze_economic_projects(post, cards=cards)
    measurement = measure_structural_state(post, cards=cards, analysis=after)
    transition = actionability_transition(prepared, post, before, after)
    impacts = analyze_exact_incoming_row(prepared, post, before, after)
    actions = prep_actions + (("deal",),)
    replay = original_state.clone()
    replay_cost = replay_actions(replay, list(actions))
    verified = bool(
        replay_cost == prep_cost + deal_paid
        and states_structurally_equal(replay, post)
    )
    budget = build_incumbent_budget(
        post,
        spent_cost=spent_cost + prep_cost + deal_paid,
        incumbent_cost=incumbent_cost,
        heuristic_remaining_work=after.estimated_remaining_work,
    )
    return DealCounterfactual(
        label="DEAL NOW" if preparation is None else preparation.candidate_id,
        status=(
            DealTimingStatus.DEAL_NOW
            if preparation is None
            else DealTimingStatus.PREPARE_THEN_DEAL
        ),
        preparation=preparation,
        preparation_cost=prep_cost,
        deal_cost=deal_paid,
        total_added_cost=prep_cost + deal_paid,
        actions=actions,
        post_deal_state=post,
        result_key_hex=_state_key_hex(post),
        independent_replay_verified=verified,
        incoming_impacts=impacts,
        pre_deal_measurement=pre_deal_measurement,
        measurement=measurement,
        economic_analysis=after,
        economic_frontier=tuple(
            (project.project_id, int(project.assessment.frontier_tier))
            for project in after.frontier.ordered_projects
        ),
        estimated_remaining_work=after.estimated_remaining_work,
        actionability=transition,
        incumbent_budget=budget,
        notes=(
            "exact incoming row applied to a clone",
            "independent corrected-cost replay verified" if verified else "replay failed",
            "deal timing economics excluded from proof pruning",
        ),
    )


def _explicit_downstream_comparison(
    deal_now: DealCounterfactual,
    prepared: DealCounterfactual,
    objective: StrategicObjective,
    config: DealTimingConfig,
) -> DownstreamCostComparison:
    assert deal_now.post_deal_state is not None and prepared.post_deal_state is not None

    def probe(state: SpiderState):
        return realize_objective(
            state.clone(),
            objective,
            mode=RealizationMode.EXACT_BOUNDED,
            max_cost=config.downstream_max_cost,
            max_nodes=config.downstream_max_nodes,
            time_limit_s=config.downstream_time_limit_s,
        )

    base, candidate = probe(deal_now.post_deal_state), probe(prepared.post_deal_state)
    good = {RealizationStatus.FOUND, RealizationStatus.ALREADY_SATISFIED}
    comparable = base.status in good and candidate.status in good
    base_cost = base.corrected_mw_cost if base.status in good else None
    candidate_cost = candidate.corrected_mw_cost if candidate.status in good else None
    saving = (
        base_cost - candidate_cost
        if base_cost is not None and candidate_cost is not None
        else None
    )
    total = (
        prepared.preparation_cost + candidate_cost
        if candidate_cost is not None
        else None
    )
    net = saving - prepared.preparation_cost if saving is not None else None
    return DownstreamCostComparison(
        objective.objective_id,
        config.downstream_max_cost,
        config.downstream_max_nodes,
        config.downstream_time_limit_s,
        base.status.value,
        base_cost,
        candidate.status.value,
        candidate_cost,
        total,
        saving,
        net,
        comparable,
        ("identical exact bounded objective and resources",),
    )


def _generic_downstream_comparison(
    deal_now: DealCounterfactual,
    prepared: DealCounterfactual,
    cards: Sequence[Card],
    spent_cost: int,
    incumbent_cost: Optional[int],
    config: DealTimingConfig,
) -> DownstreamCostComparison:
    assert deal_now.post_deal_state is not None and prepared.post_deal_state is not None
    post_analysis = prepared.economic_analysis
    assert post_analysis is not None
    research = build_incumbent_budget(
        prepared.post_deal_state,
        spent_cost=spent_cost + prepared.total_added_cost,
        incumbent_cost=incumbent_cost,
        heuristic_remaining_work=post_analysis.estimated_remaining_work,
    )
    production = build_incumbent_budget(
        prepared.post_deal_state,
        spent_cost=spent_cost + prepared.total_added_cost,
        incumbent_cost=None,
        heuristic_remaining_work=post_analysis.estimated_remaining_work,
    )
    snapshot = freeze_economic_predictions(
        post_analysis,
        research_budget=research,
        production_budget=production,
    )
    resource = EconomicProjectResourceConfig(
        added_cost_bounds=(config.tactical_max_cost,),
        max_nodes_per_bound=config.tactical_max_nodes,
        time_limit_s_per_bound=config.tactical_time_limit_s,
        allow_foundation_increase=True,
        downstream_max_cost=config.downstream_max_cost,
        downstream_max_nodes=config.downstream_max_nodes,
        downstream_time_limit_s=config.downstream_time_limit_s,
    )
    result = run_downstream_probe(
        deal_now.post_deal_state,
        prepared.post_deal_state,
        post_analysis,
        cards,
        snapshot,
        completed_project_id="deal-timing-preparation",
        config=resource,
    )
    comparable = bool(
        result.resources_matched
        and result.original_cost is not None
        and result.post_cost is not None
    )
    saving = result.bounded_cost_delta if comparable else None
    total = (
        prepared.preparation_cost + result.post_cost
        if result.post_cost is not None
        else None
    )
    net = saving - prepared.preparation_cost if saving is not None else None
    return DownstreamCostComparison(
        result.objective_project_id,
        result.max_added_cost,
        result.max_nodes,
        result.time_limit_s,
        result.original_status.value,
        result.original_cost,
        result.post_status.value,
        result.post_cost,
        total,
        saving,
        net,
        comparable,
        (result.note,),
    )


def marginal_preparation_value(
    original_state: SpiderState,
    cards: Sequence[Card],
    deal_now: DealCounterfactual,
    prepared: DealCounterfactual,
    downstream: DownstreamCostComparison,
) -> MarginalPreparationValue:
    assert prepared.preparation is not None
    assert deal_now.measurement is not None and prepared.measurement is not None
    pre_measure = deal_now.pre_deal_measurement
    prepared_measure = prepared.pre_deal_measurement
    assert pre_measure is not None and prepared_measure is not None
    base, after = deal_now.measurement, prepared.measurement
    base_receivers = sum(item.exact_receiver_success for item in deal_now.incoming_impacts)
    after_receivers = sum(item.exact_receiver_success for item in prepared.incoming_impacts)
    base_new = len(deal_now.actionability.newly_actionable_after_deal) if deal_now.actionability else 0
    after_new = len(prepared.actionability.newly_actionable_after_deal) if prepared.actionability else 0
    return MarginalPreparationValue(
        candidate_id=prepared.preparation.candidate_id,
        preparation_paid_cost=prepared.preparation_cost,
        preparation_rehandling_debt=max(
            0.0, prepared_measure.rehandling_debt - pre_measure.rehandling_debt
        ),
        stable_joins_broken_during_preparation=max(
            0, pre_measure.stable_same_suit_joins - prepared_measure.stable_same_suit_joins
        ),
        workspace_consumed_during_preparation=max(
            0, len(pre_measure.empty_columns) - len(prepared_measure.empty_columns)
        ),
        permanent_joins_retained_delta=(
            after.stable_same_suit_joins - base.stable_same_suit_joins
        ),
        same_suit_mass_delta=after.same_suit_run_mass - base.same_suit_run_mass,
        mixed_liabilities_avoided=(
            base.mixed_suit_boundaries - after.mixed_suit_boundaries
        ),
        exact_receiver_success_delta=after_receivers - base_receivers,
        campaign_must_burden_reduction=_must_total(base) - _must_total(after),
        critical_dependencies_removed=(
            base.critical_dependencies_pending - after.critical_dependencies_pending
        ),
        newly_actionable_project_delta=after_new - base_new,
        workspace_delta=len(after.empty_columns) - len(base.empty_columns),
        mobility_delta=after.legal_move_count - base.legal_move_count,
        estimated_future_work_avoided=(
            float(deal_now.estimated_remaining_work or 0.0)
            - float(prepared.estimated_remaining_work or 0.0)
        ),
        downstream=downstream,
    )


def choose_deal_timing(
    deal_now: DealCounterfactual,
    marginals: Sequence[MarginalPreparationValue],
    *,
    legal_tableau_moves_remaining: int,
) -> DealTimingDecision:
    """Choose only from explicit total-cost evidence; never from move exhaustion."""
    if deal_now.status == DealTimingStatus.NO_STOCK_REMAINING:
        return DealTimingDecision(
            DealTimingDecisionKind.NO_STOCK_REMAINING,
            None,
            (DealTimingReason.STOCK_EXHAUSTED,),
            ("fewer than ten stock cards remain",),
            legal_tableau_moves_remaining,
        )
    if deal_now.status == DealTimingStatus.DEAL_CURRENTLY_ILLEGAL:
        return DealTimingDecision(
            DealTimingDecisionKind.DEAL_ILLEGAL_UNTIL_EMPTY_FILLED,
            None,
            (DealTimingReason.EMPTY_COLUMN_BLOCKS_RESTRICTED_PROFILE,),
            ("the active restricted rules profile rejects the current tableau",),
            legal_tableau_moves_remaining,
        )
    winners = [
        value
        for value in marginals
        if value.downstream.comparable
        and value.downstream.bounded_net_gain is not None
        and value.downstream.bounded_net_gain > 0
    ]
    if winners:
        best = max(
            winners,
            key=lambda value: (
                value.downstream.bounded_net_gain or 0,
                value.mixed_liabilities_avoided,
                value.permanent_joins_retained_delta,
                -value.preparation_paid_cost,
                value.candidate_id,
            ),
        )
        return DealTimingDecision(
            DealTimingDecisionKind.PREPARATION_PREFERRED,
            best.candidate_id,
            (DealTimingReason.LOWER_TOTAL_BOUNDED_COST,),
            (
                f"preparation spends {best.preparation_paid_cost} and produces "
                f"bounded net gain {best.downstream.bounded_net_gain}",
            ),
            legal_tableau_moves_remaining,
        )
    comparable = [value for value in marginals if value.downstream.comparable]
    newly_actionable = (
        deal_now.actionability.newly_actionable_after_deal
        if deal_now.actionability is not None
        else ()
    )
    if newly_actionable and not comparable:
        return DealTimingDecision(
            DealTimingDecisionKind.DEAL_REQUIRED_FOR_ACTIONABILITY,
            None,
            (DealTimingReason.STOCK_UNLOCKS_HIGH_VALUE_WORK,),
            (f"deal makes high-value work actionable: {', '.join(newly_actionable)}",),
            legal_tableau_moves_remaining,
        )
    if comparable and all(
        value.downstream.bounded_net_gain is not None
        and value.downstream.bounded_net_gain <= 0
        for value in comparable
    ):
        return DealTimingDecision(
            DealTimingDecisionKind.DEAL_NOW_PREFERRED,
            None,
            (DealTimingReason.NO_PREPARATION_REPAYS_COST,),
            (
                "every comparable preparation has total bounded expenditure "
                "at least as high as dealing now",
                "legal tableau moves remaining are not a reason to delay",
            ),
            legal_tableau_moves_remaining,
        )
    return DealTimingDecision(
        DealTimingDecisionKind.COMPARISON_INCONCLUSIVE,
        None,
        (DealTimingReason.NO_COMPARABLE_DOWNSTREAM_TARGET,),
        ("no matched bounded objective establishes a net saving",),
        legal_tableau_moves_remaining,
    )


def _assessment_fingerprint(
    incoming: Sequence[Card],
    deal_now: DealCounterfactual,
    preparations: Sequence[DealPreparationCandidate],
    marginals: Sequence[MarginalPreparationValue],
    decision: DealTimingDecision,
) -> str:
    payload = (
        tuple((card.suit, card.rank) for card in incoming),
        deal_now.status.value,
        deal_now.result_key_hex,
        tuple(
            (item.candidate_id, item.corrected_cost, item.state_key_hex, item.actions)
            for item in preparations
        ),
        tuple(
            (
                item.candidate_id,
                item.preparation_paid_cost,
                item.downstream.objective_id,
                item.downstream.deal_now_cost,
                item.downstream.prepared_cost,
                item.downstream.bounded_net_gain,
            )
            for item in marginals
        ),
        decision.kind.value,
        decision.selected_candidate_id,
    )
    return hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def assess_deal_timing(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    spent_cost: int,
    incumbent_cost: Optional[int] = None,
    config: DealTimingConfig = DealTimingConfig(),
    preparations: Optional[Sequence[DealPreparationCandidate]] = None,
    downstream_objective: Optional[StrategicObjective] = None,
) -> DealTimingAssessment:
    """Freeze one H0/H1/H2 deal-timing assessment from independent clones."""
    incoming = tuple(next_stock_row(state) or ())
    deal_now = simulate_deal_counterfactual(
        state,
        cards,
        spent_cost=spent_cost,
        incumbent_cost=incumbent_cost,
    )
    if deal_now.post_deal_state is None:
        decision = choose_deal_timing(
            deal_now, (), legal_tableau_moves_remaining=len(state.enumerate_moves())
        )
        fingerprint = _assessment_fingerprint(incoming, deal_now, (), (), decision)
        return DealTimingAssessment(
            config, incoming, deal_now, (), (), (), decision, fingerprint
        )
    candidates = tuple(preparations) if preparations is not None else generate_preparation_candidates(
        state, cards, config=config
    )
    prepared_deals: List[DealCounterfactual] = []
    marginals: List[MarginalPreparationValue] = []
    for candidate in candidates:
        if candidate.corrected_cost > config.max_preparation_cost:
            continue
        prepared = simulate_deal_counterfactual(
            state,
            cards,
            spent_cost=spent_cost,
            incumbent_cost=incumbent_cost,
            preparation=candidate,
        )
        if prepared.post_deal_state is None:
            continue
        downstream = (
            _explicit_downstream_comparison(
                deal_now, prepared, downstream_objective, config
            )
            if downstream_objective is not None
            else _generic_downstream_comparison(
                deal_now,
                prepared,
                cards,
                spent_cost,
                incumbent_cost,
                config,
            )
        )
        prepared_deals.append(prepared)
        marginals.append(
            marginal_preparation_value(state, cards, deal_now, prepared, downstream)
        )
    decision = choose_deal_timing(
        deal_now,
        marginals,
        legal_tableau_moves_remaining=len(state.enumerate_moves()),
    )
    fingerprint = _assessment_fingerprint(
        incoming, deal_now, candidates, marginals, decision
    )
    return DealTimingAssessment(
        config=config,
        incoming_row=incoming,
        deal_now=deal_now,
        preparations=candidates,
        prepared_deals=tuple(prepared_deals),
        marginal_values=tuple(marginals),
        decision=decision,
        prediction_fingerprint=fingerprint,
    )


def deal_as_economic_project(
    assessment: DealTimingAssessment,
) -> DealEconomicProjectAdapter:
    """Controller-facing adapter without integrating a whole-game controller."""
    return DealEconomicProjectAdapter(
        project_id="deal-next-stock-row",
        description="advance one exact known stock epoch",
        immediate_paid_cost=assessment.deal_now.deal_cost,
        incoming_row=assessment.incoming_row,
        decision_kind=assessment.decision.kind,
        preparation_candidate_id=assessment.decision.selected_candidate_id,
    )
