"""Bounded realization and calibration support for frozen economic projects.

This module is deliberately narrower than a controller.  It translates one
already-frozen :class:`~spider.planner.economic_projects.EconomicProject` into
a machine-testable structural predicate, delegates supported searches to the
existing tactical objective realizer, and measures replay-verified outcomes.

It never deals stock.  Economic scores, frontier tiers, lifecycle estimates,
and prediction records are inputs only and never change during realization.
None of the measurements or calibration classifications may proof-prune.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.committed_excavation import longest_same_suit
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProject,
    EconomicProjectKind,
    EvidenceAmount,
    analyze_economic_projects,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.incumbent_budget import IncumbentBudget
from spider.planner.objective_realizer import (
    RealizationMode,
    RealizationStatus,
    realize_objective,
)
from spider.planner.space_lifecycle import fully_open_nonempty
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.state_identity import (
    CanonicalStateKey,
    canonical_state_key,
    states_structurally_equal,
)


class EconomicProjectRealizationStatus(str, Enum):
    PROJECT_REALIZED = "PROJECT_REALIZED"
    PROJECT_ADVANCED = "PROJECT_ADVANCED"
    NOT_FOUND_WITHIN_BOUND = "NOT_FOUND_WITHIN_BOUND"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    INVALID_PROJECT = "INVALID_PROJECT"
    NOT_ACTIONABLE_CURRENT_EPOCH = "NOT_ACTIONABLE_CURRENT_EPOCH"


class EconomicProjectPredicateKind(str, Enum):
    COLUMN_FACE_DOWN_AT_MOST = "COLUMN_FACE_DOWN_AT_MOST"
    PERMANENT_SAME_SUIT_JOIN = "PERMANENT_SAME_SUIT_JOIN"
    EMPTY_COUNT_AT_LEAST = "EMPTY_COUNT_AT_LEAST"
    STOCK_RECEIVER_TOP = "STOCK_RECEIVER_TOP"
    LIFECYCLE_CONTROL_EFFECT = "LIFECYCLE_CONTROL_EFFECT"


class ProjectSelectionDisposition(str, Enum):
    SELECTED = "SELECTED"
    INELIGIBLE_UNTIL_FUTURE_EPOCH = "INELIGIBLE_UNTIL_FUTURE_EPOCH"
    OVERLAPS_SELECTED_PROJECT = "OVERLAPS_SELECTED_PROJECT"
    NO_GENERIC_TACTICAL_PREDICATE = "NO_GENERIC_TACTICAL_PREDICATE"
    ACTIONABLE_NOT_SAMPLED = "ACTIONABLE_NOT_SAMPLED"


class PredictionAssessment(str, Enum):
    CONFIRMED = "CONFIRMED"
    DIRECTIONALLY_CONFIRMED = "DIRECTIONALLY_CONFIRMED"
    INCONCLUSIVE = "INCONCLUSIVE"
    CONTRADICTED = "CONTRADICTED"


class ReworkValidation(str, Enum):
    VALIDATED = "VALIDATED"
    PLAUSIBLE = "PLAUSIBLE"
    NOT_VALIDATED = "NOT_VALIDATED"
    FAILED_TO_REALIZE = "FAILED_TO_REALIZE"


@dataclass(frozen=True)
class EconomicProjectResourceConfig:
    added_cost_bounds: Tuple[int, ...] = (4, 8, 12)
    max_nodes_per_bound: int = 50_000
    time_limit_s_per_bound: float = 18.0
    downstream_max_cost: int = 8
    downstream_max_nodes: int = 20_000
    downstream_time_limit_s: float = 8.0
    allow_stock_deal: bool = False
    allow_foundation_increase: bool = False

    def __post_init__(self) -> None:
        if not self.added_cost_bounds or tuple(sorted(set(self.added_cost_bounds))) != self.added_cost_bounds:
            raise ValueError("added_cost_bounds must be strictly increasing")
        if min(self.added_cost_bounds) < 0:
            raise ValueError("cost bounds must be non-negative")
        if self.max_nodes_per_bound <= 0 or self.time_limit_s_per_bound <= 0:
            raise ValueError("resource limits must be positive")
        if self.allow_stock_deal:
            raise ValueError("economic calibration realization must prohibit stock deals")


@dataclass(frozen=True)
class EconomicProjectPredicate:
    kind: EconomicProjectPredicateKind
    project_id: str
    description: str
    target_column: Optional[int] = None
    max_face_down: Optional[int] = None
    min_empty_count: Optional[int] = None
    suit: Optional[str] = None
    high_rank: Optional[int] = None
    low_rank: Optional[int] = None
    expected_placement: Optional[PlacementClass] = None
    structural_return_required: bool = True

    def is_satisfied(self, state: SpiderState) -> bool:
        if self.kind == EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST:
            return bool(
                self.target_column is not None
                and self.max_face_down is not None
                and len(state.columns[self.target_column].face_down) <= self.max_face_down
            )
        if self.kind == EconomicProjectPredicateKind.PERMANENT_SAME_SUIT_JOIN:
            return _has_adjacency(
                state,
                suit=self.suit,
                high_rank=self.high_rank,
                low_rank=self.low_rank,
                column=self.target_column,
            )
        if self.kind == EconomicProjectPredicateKind.EMPTY_COUNT_AT_LEAST:
            return bool(
                self.min_empty_count is not None
                and _empty_count(state) >= self.min_empty_count
            )
        if self.kind == EconomicProjectPredicateKind.STOCK_RECEIVER_TOP:
            if self.target_column is None or self.suit is None or self.high_rank is None:
                return False
            top = state.columns[self.target_column].top()
            return bool(top is not None and top.suit == self.suit and top.rank == self.high_rank)
        if self.kind == EconomicProjectPredicateKind.LIFECYCLE_CONTROL_EFFECT:
            # This verifies the frozen local structural effect.  A control with
            # no promised return is still only PROJECT_ADVANCED, never REALIZED.
            if self.expected_placement == PlacementClass.MIXED_SUIT_PARK:
                return _has_adjacency(
                    state,
                    suit=None,
                    high_rank=self.high_rank,
                    low_rank=self.low_rank,
                    column=self.target_column,
                    require_mixed=True,
                )
            if self.expected_placement == PlacementClass.WORKSPACE_PARK:
                return self.target_column is not None and bool(state.columns[self.target_column].face_up)
        return False


@dataclass(frozen=True)
class EconomicProjectProgress:
    predicate_satisfied: bool
    target_face_down_before: Optional[int]
    target_face_down_after: Optional[int]
    empty_count_before: int
    empty_count_after: int
    stable_join_present_before: bool
    stable_join_present_after: bool
    note: str


@dataclass(frozen=True)
class FrozenAmount:
    name: str
    value: Optional[float]
    evidence: str
    rationale: str


@dataclass(frozen=True)
class FrozenRevealPrediction:
    card: Tuple[str, int]
    column: int
    depth: int
    classification: str
    information_gain: float
    structural_value: float
    campaign_dependencies: Tuple[str, ...]


@dataclass(frozen=True)
class FrozenProjectPrediction:
    order: int
    project_id: str
    kind: str
    frontier_tier: int
    predicted_net: float
    confidence: str
    costs: Tuple[FrozenAmount, ...]
    benefits: Tuple[FrozenAmount, ...]
    debt: Tuple[FrozenAmount, ...]
    future_exit_route: str
    exit_route_bounded: bool
    reveal_values: Tuple[FrozenRevealPrediction, ...]
    rework_investment: Optional[Tuple]
    action: Optional[Tuple[int, int, int]]


@dataclass(frozen=True)
class FrozenBudgetPrediction:
    incumbent_cost: Optional[int]
    improvement_target: Optional[int]
    spent_cost: int
    admissible_remaining_lower_bound: int
    hard_min_total: int
    hard_headroom: Optional[int]
    heuristic_remaining_work: float
    heuristic_economic_slack: Optional[float]
    proof_prunable: bool


@dataclass(frozen=True)
class FrozenEconomicPrediction:
    projects: Tuple[FrozenProjectPrediction, ...]
    dominance: Tuple[Tuple[str, str, Tuple[str, ...]], ...]
    estimated_remaining_work: float
    research_budget: FrozenBudgetPrediction
    production_budget: FrozenBudgetPrediction
    fingerprint: str
    canonical_loaded: bool = False
    prediction_frozen: bool = True


@dataclass(frozen=True)
class ProjectSelectionRecord:
    project_id: str
    disposition: ProjectSelectionDisposition
    category: str
    reason: str
    predicate: Optional[EconomicProjectPredicate]


@dataclass(frozen=True)
class EconomicProjectSample:
    selected: Tuple[EconomicProject, ...]
    records: Tuple[ProjectSelectionRecord, ...]
    prediction_fingerprint: str


@dataclass(frozen=True)
class ProjectActionability:
    project_id: str
    actionable_current_epoch: bool
    predicate: Optional[EconomicProjectPredicate]
    probe_status: EconomicProjectRealizationStatus
    probe_cost: Optional[int]
    probe_actions: Tuple[Action, ...]
    nodes_expanded: int
    resources: EconomicProjectResourceConfig
    reason: str


@dataclass(frozen=True)
class EconomicProjectRealizationResult:
    project_id: str
    project_kind: EconomicProjectKind
    predicted_tier: EconomicFrontierTier
    predicate: Optional[EconomicProjectPredicate]
    status: EconomicProjectRealizationStatus
    max_added_cost: int
    max_nodes: int
    time_limit_s: float
    actual_corrected_cost: Optional[int]
    actions: Tuple[Action, ...]
    nodes_expanded: int
    elapsed_seconds: float
    predicate_satisfied: bool
    independent_replay_verified: bool
    no_stock_deal: bool
    stock_count_before: int
    stock_count_after: int
    foundation_count_before: int
    foundation_count_after: int
    start_key: CanonicalStateKey
    result_key: Optional[CanonicalStateKey]
    progress: EconomicProjectProgress
    notes: Tuple[str, ...]
    prediction_fingerprint: str


@dataclass(frozen=True)
class EconomicProjectBoundSeries:
    project_id: str
    config: EconomicProjectResourceConfig
    results: Tuple[EconomicProjectRealizationResult, ...]
    best: EconomicProjectRealizationResult
    prediction_fingerprint: str


@dataclass(frozen=True)
class StructuralMeasurement:
    face_down_count: int
    foundation_count: int
    stock_count: int
    empty_columns: Tuple[int, ...]
    fully_open_columns: Tuple[int, ...]
    legal_move_count: int
    stable_same_suit_joins: int
    same_suit_run_mass: int
    longest_same_suit_run: int
    mixed_suit_boundaries: int
    rehandling_debt: float
    critical_dependencies_pending: int
    campaign_must_burden: Tuple[Tuple[str, int], ...]
    frontier_order: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class StructuralOutcomeVector:
    paid_cost: Optional[int]
    critical_dependencies_removed: int
    stable_joins_delta: int
    same_suit_mass_delta: int
    mixed_boundaries_delta: int
    workspace_delta: int
    mobility_delta: int
    must_burden_delta: int
    bounded_downstream_cost_delta: Optional[int]
    rehandling_debt_delta: float
    target_dependencies_satisfied: int


@dataclass(frozen=True)
class DownstreamProbeResult:
    objective_project_id: Optional[str]
    predicate: Optional[EconomicProjectPredicate]
    max_added_cost: int
    max_nodes: int
    time_limit_s: float
    original_status: EconomicProjectRealizationStatus
    original_cost: Optional[int]
    post_status: EconomicProjectRealizationStatus
    post_cost: Optional[int]
    bounded_cost_delta: Optional[int]
    resources_matched: bool
    note: str


def _empty_count(state: SpiderState) -> int:
    return sum(column.is_empty() for column in state.columns)


def _has_adjacency(
    state: SpiderState,
    *,
    suit: Optional[str],
    high_rank: Optional[int],
    low_rank: Optional[int],
    column: Optional[int] = None,
    require_mixed: bool = False,
) -> bool:
    if high_rank is None or low_rank is None:
        return False
    columns = range(len(state.columns)) if column is None else (column,)
    for index in columns:
        up = state.columns[index].face_up
        for lower, upper in zip(up, up[1:]):
            if lower.rank != high_rank or upper.rank != low_rank:
                continue
            if require_mixed:
                if lower.suit != upper.suit:
                    return True
            elif suit is not None and lower.suit == upper.suit == suit:
                return True
    return False


def _freeze_amounts(items: Iterable[Tuple[str, EvidenceAmount]]) -> Tuple[FrozenAmount, ...]:
    return tuple(
        FrozenAmount(name, amount.value, amount.evidence.value, amount.rationale)
        for name, amount in items
    )


def _freeze_budget(budget: IncumbentBudget) -> FrozenBudgetPrediction:
    return FrozenBudgetPrediction(
        incumbent_cost=budget.incumbent_cost,
        improvement_target=budget.improvement_target,
        spent_cost=budget.spent_cost,
        admissible_remaining_lower_bound=budget.admissible_remaining_lower_bound,
        hard_min_total=budget.hard_min_total,
        hard_headroom=budget.hard_headroom,
        heuristic_remaining_work=budget.heuristic_remaining_work,
        heuristic_economic_slack=budget.heuristic_economic_slack,
        proof_prunable=budget.proof_prunable,
    )


def _prediction_payload(
    projects: Tuple[FrozenProjectPrediction, ...],
    dominance: Tuple[Tuple[str, str, Tuple[str, ...]], ...],
    estimated_remaining_work: float,
    research: FrozenBudgetPrediction,
    production: FrozenBudgetPrediction,
) -> Tuple:
    return (projects, dominance, estimated_remaining_work, research, production)


def freeze_economic_predictions(
    analysis: EconomicAnalysisResult,
    *,
    research_budget: IncumbentBudget,
    production_budget: IncumbentBudget,
) -> FrozenEconomicPrediction:
    """Deep-freeze every prediction before any tactical realization begins."""
    project_rows: List[FrozenProjectPrediction] = []
    for order, project in enumerate(analysis.frontier.ordered_projects):
        debt_items = (
            ("rework_actions_introduced", project.debt.rework_actions_introduced),
            ("mixed_boundaries_created", project.debt.mixed_boundaries_created),
            ("stable_joins_broken", project.debt.stable_joins_broken),
            ("provisional_joins_created", project.debt.provisional_joins_created),
            ("workspace_consumed", project.debt.workspace_consumed),
            ("projected_rehandling_cost", project.debt.projected_rehandling_cost),
        )
        rework = project.rework_investment
        rework_tuple = None
        if rework is not None:
            rework_tuple = (
                rework.investment_cost.value,
                rework.investment_cost.evidence.value,
                rework.expected_structural_return.value,
                rework.expected_structural_return.evidence.value,
                rework.expected_move_saving.value,
                rework.expected_move_saving.evidence.value,
                rework.evidence,
                rework.net_economic_value,
                rework.confidence,
                rework.exit_route_bounded,
                rework.worthwhile,
            )
        project_rows.append(
            FrozenProjectPrediction(
                order=order,
                project_id=project.project_id,
                kind=project.kind.value,
                frontier_tier=int(project.assessment.frontier_tier),
                predicted_net=project.assessment.net_economic_value,
                confidence=project.assessment.confidence,
                costs=_freeze_amounts(project.cost.components),
                benefits=_freeze_amounts(project.benefit.components),
                debt=_freeze_amounts(debt_items),
                future_exit_route=project.debt.future_exit_route,
                exit_route_bounded=project.debt.exit_route_bounded,
                reveal_values=tuple(
                    FrozenRevealPrediction(
                        (value.card.suit, value.card.rank),
                        value.column,
                        value.reveal_depth,
                        value.classification.value,
                        value.information_gain,
                        value.structural_value,
                        value.campaign_dependencies,
                    )
                    for value in project.reveal_values
                ),
                rework_investment=rework_tuple,
                action=project.action,
            )
        )
    projects = tuple(project_rows)
    dominance = tuple(
        (item.dominant_project_id, item.dominated_project_id, item.reasons)
        for item in analysis.frontier.dominance
    )
    research = _freeze_budget(research_budget)
    production = _freeze_budget(production_budget)
    payload = _prediction_payload(
        projects, dominance, analysis.estimated_remaining_work, research, production
    )
    fingerprint = hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()
    return FrozenEconomicPrediction(
        projects=projects,
        dominance=dominance,
        estimated_remaining_work=analysis.estimated_remaining_work,
        research_budget=research,
        production_budget=production,
        fingerprint=fingerprint,
    )


def verify_prediction_freeze(snapshot: FrozenEconomicPrediction) -> bool:
    payload = _prediction_payload(
        snapshot.projects,
        snapshot.dominance,
        snapshot.estimated_remaining_work,
        snapshot.research_budget,
        snapshot.production_budget,
    )
    return snapshot.fingerprint == hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()


def project_predicate(
    start_state: SpiderState, project: EconomicProject
) -> Tuple[Optional[EconomicProjectPredicate], str]:
    """Translate one generic frozen project into a structural predicate."""
    epoch = current_stock_epoch(start_state, 5)
    if project.earliest_useful_epoch > epoch:
        return None, "project belongs to a future stock epoch"

    if project.kind in (
        EconomicProjectKind.EXCAVATE_CARD,
        EconomicProjectKind.EXCAVATE_COLUMN_PREFIX,
    ):
        columns = {value.column for value in project.reveal_values}
        if len(columns) != 1:
            return None, "excavation project lacks one unambiguous target column"
        column = next(iter(columns))
        if not start_state.columns[column].face_down:
            return None, "target column has no current face-down prefix"
        # Economic excavation benefit aggregates the complete known hidden
        # prefix; realization must therefore expose the full prefix, not take
        # credit for one unrelated reveal.
        return EconomicProjectPredicate(
            EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST,
            project.project_id,
            f"column {column + 1} face-down prefix fully exposed",
            target_column=column,
            max_face_down=0,
        ), "current-epoch full-prefix reveal predicate"

    if project.kind == EconomicProjectKind.PERMANENT_JOIN and project.action is not None:
        src, dst, k = project.action
        if not start_state.can_move(src, dst, k):
            return None, "frozen permanent-join action is no longer legal"
        lower = start_state.columns[dst].top()
        upper = start_state.columns[src].face_up[-k]
        if lower is None or lower.suit != upper.suit or lower.rank - 1 != upper.rank:
            return None, "frozen action does not encode a same-suit adjacency"
        return EconomicProjectPredicate(
            EconomicProjectPredicateKind.PERMANENT_SAME_SUIT_JOIN,
            project.project_id,
            f"{lower}-{upper} stable adjacency exists in destination column",
            target_column=dst,
            suit=lower.suit,
            high_rank=lower.rank,
            low_rank=upper.rank,
        ), "legal frozen permanent-join action and exact adjacency predicate"

    if project.kind in (
        EconomicProjectKind.CREATE_WORKSPACE,
        EconomicProjectKind.RECOVER_WORKSPACE,
    ):
        return EconomicProjectPredicate(
            EconomicProjectPredicateKind.EMPTY_COUNT_AT_LEAST,
            project.project_id,
            "increase available empty-column workspace by one",
            min_empty_count=_empty_count(start_state) + 1,
        ), "current-epoch workspace predicate"

    if project.kind == EconomicProjectKind.TEMPORARY_REWORK and project.action is not None:
        if project.benefit.structural_total > 0:
            return (
                None,
                "temporary action does not encode the promised downstream structural return; "
                "executing the park alone cannot realize this project",
            )
        src, dst, k = project.action
        if not start_state.can_move(src, dst, k):
            return None, "frozen lifecycle-control action is no longer legal"
        assessment = assess_tableau_move(start_state, project.action, discover_exit=False)
        lower = start_state.columns[dst].top()
        upper = start_state.columns[src].face_up[-k]
        return EconomicProjectPredicate(
            EconomicProjectPredicateKind.LIFECYCLE_CONTROL_EFFECT,
            project.project_id,
            "replay the frozen local lifecycle effect without claiming structural return",
            target_column=dst,
            suit=upper.suit,
            high_rank=lower.rank if lower is not None else None,
            low_rank=upper.rank,
            expected_placement=assessment.placement_class,
            structural_return_required=project.benefit.structural_total > 0,
        ), "local lifecycle effect is measurable; return remains separately required"

    if project.kind == EconomicProjectKind.FOUNDATION_CAMPAIGN_STEP:
        deals = int(project.cost.necessary_stock_deals.ordering_value)
        if deals > 0:
            return None, f"campaign requires {deals} future stock deal(s)"
        return None, "campaign project has no narrow current-epoch structural predicate"

    if project.kind == EconomicProjectKind.PREPARE_STOCK_RECEIVER:
        return None, "receiver target is described economically but lacks frozen structural coordinates"

    return None, f"no generic tactical predicate for kind {project.kind.value}"


def select_representative_projects(
    start_state: SpiderState,
    analysis: EconomicAnalysisResult,
    snapshot: FrozenEconomicPrediction,
    *,
    max_dominant: int = 2,
    max_positive: int = 2,
    actionability: Optional[Mapping[str, ProjectActionability]] = None,
) -> EconomicProjectSample:
    """Select a deterministic tier/control sample without project-ID constants."""
    if not verify_prediction_freeze(snapshot):
        raise ValueError("economic prediction snapshot is not intact")
    ordered = analysis.frontier.ordered_projects
    predicates: Dict[str, Optional[EconomicProjectPredicate]] = {}
    reasons: Dict[str, str] = {}
    for project in ordered:
        predicate, reason = project_predicate(start_state, project)
        checked = actionability.get(project.project_id) if actionability is not None else None
        if checked is not None:
            predicate = checked.predicate if checked.actionable_current_epoch else None
            reason = checked.reason
        predicates[project.project_id] = predicate
        reasons[project.project_id] = reason

    selected: List[EconomicProject] = []
    categories: Dict[str, str] = {}
    target_keys: set[Tuple] = set()

    def key_for(predicate: EconomicProjectPredicate) -> Tuple:
        return (
            predicate.kind.value,
            predicate.target_column,
            predicate.max_face_down,
            predicate.min_empty_count,
            predicate.suit,
            predicate.high_rank,
            predicate.low_rank,
        )

    def add(project: EconomicProject, category: str) -> bool:
        predicate = predicates[project.project_id]
        if predicate is None:
            return False
        key = key_for(predicate)
        if key in target_keys:
            return False
        selected.append(project)
        categories[project.project_id] = category
        target_keys.add(key)
        return True

    for project in ordered:
        if len([p for p in selected if categories[p.project_id] == "A_DOMINANT"]) >= max_dominant:
            break
        if project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT:
            add(project, "A_DOMINANT")

    for project in ordered:
        if len([p for p in selected if categories[p.project_id] == "B_POSITIVE"]) >= max_positive:
            break
        if project.assessment.frontier_tier == EconomicFrontierTier.POSITIVE_INVESTMENT:
            add(project, "B_POSITIVE")

    debt_candidates = [
        project
        for project in ordered
        if project.assessment.frontier_tier == EconomicFrontierTier.POSITIVE_INVESTMENT
        and predicates[project.project_id] is not None
        and (
            project.debt.ordering_total > 0
            or project.rework_investment is not None
        )
        and project not in selected
    ]
    if debt_candidates:
        add(debt_candidates[0], "C_REWORK")

    controls = [
        project
        for project in ordered
        if project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
        and predicates[project.project_id] is not None
        and project not in selected
    ]
    if controls:
        add(controls[0], "D_TIER4_CONTROL")

    records: List[ProjectSelectionRecord] = []
    selected_ids = {project.project_id for project in selected}
    selected_keys = {
        key_for(predicates[project.project_id])
        for project in selected
        if predicates[project.project_id] is not None
    }
    for project in ordered:
        predicate = predicates[project.project_id]
        if project.project_id in selected_ids:
            disposition = ProjectSelectionDisposition.SELECTED
            category = categories[project.project_id]
            reason = reasons[project.project_id]
        elif predicate is None:
            disposition = (
                ProjectSelectionDisposition.INELIGIBLE_UNTIL_FUTURE_EPOCH
                if (
                    project.earliest_useful_epoch > current_stock_epoch(start_state, 5)
                    or project.cost.necessary_stock_deals.ordering_value > 0
                    or (
                        actionability is not None
                        and project.project_id in actionability
                        and not actionability[project.project_id].actionable_current_epoch
                        and actionability[project.project_id].predicate is not None
                    )
                )
                else ProjectSelectionDisposition.NO_GENERIC_TACTICAL_PREDICATE
            )
            category = "NOT_SELECTED"
            reason = reasons[project.project_id]
        elif key_for(predicate) in selected_keys:
            disposition = ProjectSelectionDisposition.OVERLAPS_SELECTED_PROJECT
            category = "NOT_SELECTED"
            reason = "same structural target as an already selected project"
        else:
            disposition = ProjectSelectionDisposition.ACTIONABLE_NOT_SAMPLED
            category = "NOT_SELECTED"
            reason = "actionable but outside the fixed representative quotas"
        records.append(
            ProjectSelectionRecord(
                project.project_id,
                disposition,
                category,
                reason,
                predicate,
            )
        )
    return EconomicProjectSample(tuple(selected), tuple(records), snapshot.fingerprint)


def probe_project_actionability(
    start_state: SpiderState,
    project: EconomicProject,
    *,
    config: EconomicProjectResourceConfig,
) -> ProjectActionability:
    """Bound whether a project can make any target progress without stock.

    This screening happens only after economic predictions freeze.  A bounded
    miss remains a current-experiment ineligibility result, not a global proof
    that the project can never be useful.
    """
    predicate, reason = project_predicate(start_state, project)
    if predicate is None:
        return ProjectActionability(
            project.project_id,
            False,
            None,
            (
                EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH
                if (
                    project.earliest_useful_epoch > current_stock_epoch(start_state, 5)
                    or project.cost.necessary_stock_deals.ordering_value > 0
                )
                else EconomicProjectRealizationStatus.INVALID_PROJECT
            ),
            None,
            (),
            0,
            config,
            reason,
        )
    if project.action is not None:
        legal = start_state.can_move(*project.action)
        return ProjectActionability(
            project.project_id,
            legal,
            predicate,
            (
                EconomicProjectRealizationStatus.PROJECT_ADVANCED
                if legal else EconomicProjectRealizationStatus.INVALID_PROJECT
            ),
            (
                assess_tableau_move(start_state, project.action, discover_exit=False).immediate_cost
                if legal else None
            ),
            (project.action,) if legal else (),
            1 if legal else 0,
            config,
            reason if legal else "frozen action is not legal from current state",
        )
    screen_predicate = predicate
    if (
        predicate.kind == EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST
        and predicate.target_column is not None
    ):
        before_fd = len(start_state.columns[predicate.target_column].face_down)
        screen_predicate = EconomicProjectPredicate(
            EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST,
            project.project_id,
            "at least one real reveal toward the frozen full-prefix target",
            target_column=predicate.target_column,
            max_face_down=max(0, before_fd - 1),
        )
    objective = _predicate_to_objective(screen_predicate, project)
    if objective is None:
        return ProjectActionability(
            project.project_id,
            False,
            predicate,
            EconomicProjectRealizationStatus.INVALID_PROJECT,
            None,
            (),
            0,
            config,
            "predicate has no bounded tactical adapter",
        )
    tactical = realize_objective(
        start_state.clone(),
        objective,
        mode=RealizationMode.EXACT_BOUNDED,
        max_cost=config.added_cost_bounds[-1],
        max_nodes=config.max_nodes_per_bound,
        time_limit_s=config.time_limit_s_per_bound,
    )
    found = tactical.status in (RealizationStatus.FOUND, RealizationStatus.ALREADY_SATISFIED)
    status = (
        EconomicProjectRealizationStatus.PROJECT_ADVANCED
        if found
        else (
            EconomicProjectRealizationStatus.RESOURCE_LIMIT
            if tactical.status == RealizationStatus.RESOURCE_LIMIT
            else EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH
        )
    )
    return ProjectActionability(
        project.project_id,
        found,
        predicate,
        status,
        tactical.corrected_mw_cost,
        tactical.actions,
        tactical.nodes_expanded,
        config,
        (
            "tableau-only bounded probe found structural progress"
            if found
            else (
                "tableau-only probe hit a resource limit; excluded from the matched sample"
                if tactical.status == RealizationStatus.RESOURCE_LIMIT
                else "no target progress in the matched no-deal bounded closure"
            )
        ),
    )


def probe_frontier_actionability(
    start_state: SpiderState,
    analysis: EconomicAnalysisResult,
    *,
    config: EconomicProjectResourceConfig,
) -> Tuple[ProjectActionability, ...]:
    return tuple(
        probe_project_actionability(start_state, project, config=config)
        for project in analysis.frontier.ordered_projects
    )


def _predicate_to_objective(
    predicate: EconomicProjectPredicate,
    project: EconomicProject,
) -> Optional[StrategicObjective]:
    if predicate.kind == EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST:
        kind = ObjectiveKind.EXPOSE_REVEAL_PREFIX
        target_key = "column_face_down_le"
        params = {
            "column": predicate.target_column,
            "max_face_down": predicate.max_face_down,
        }
    elif predicate.kind == EconomicProjectPredicateKind.EMPTY_COUNT_AT_LEAST:
        kind = ObjectiveKind.CREATE_WORKSPACE
        target_key = "empty_count_ge"
        params = {"min_empty": predicate.min_empty_count}
    elif predicate.kind == EconomicProjectPredicateKind.PERMANENT_SAME_SUIT_JOIN:
        kind = ObjectiveKind.CONSOLIDATE_SAME_SUIT
        target_key = "same_suit_adjacency"
        params = {
            "suit": predicate.suit,
            "high_rank": predicate.high_rank,
            "low_rank": predicate.low_rank,
        }
    else:
        return None
    return StrategicObjective(
        kind=kind,
        objective_id=f"economic::{project.project_id}",
        description=predicate.description,
        target_key=target_key,
        target_params=params,
        hard_preconditions=("tableau-only economic realization",),
        hard_evidence=("predicate derived before tactical search",),
        admissible_lb=0,
        admissible_breakdown=None,
        heuristic_est_cost=project.cost.ordering_total,
        heuristic_est_benefit=project.benefit.structural_total,
        priority=PriorityComponents(),
        foundation_relevance="frozen economic project",
        workspace_relevance=project.workspace_effect,
        stock_relevance="no stock deal permitted",
        explanation="generic project-to-existing-objective adapter",
    )


def _progress(
    start: SpiderState,
    end: SpiderState,
    predicate: Optional[EconomicProjectPredicate],
) -> EconomicProjectProgress:
    target = predicate.target_column if predicate is not None else None
    before_fd = len(start.columns[target].face_down) if target is not None else None
    after_fd = len(end.columns[target].face_down) if target is not None else None
    before_sat = predicate.is_satisfied(start) if predicate is not None else False
    after_sat = predicate.is_satisfied(end) if predicate is not None else False
    return EconomicProjectProgress(
        predicate_satisfied=after_sat,
        target_face_down_before=before_fd,
        target_face_down_after=after_fd,
        empty_count_before=_empty_count(start),
        empty_count_after=_empty_count(end),
        stable_join_present_before=before_sat,
        stable_join_present_after=after_sat,
        note=("target predicate satisfied" if after_sat else "target predicate not satisfied"),
    )


def _result(
    *,
    start_state: SpiderState,
    end_state: Optional[SpiderState],
    project: EconomicProject,
    predicate: Optional[EconomicProjectPredicate],
    status: EconomicProjectRealizationStatus,
    max_added_cost: int,
    max_nodes: int,
    time_limit_s: float,
    cost: Optional[int],
    actions: Sequence[Action],
    nodes: int,
    elapsed: float,
    notes: Sequence[str],
    prediction_fingerprint: str,
) -> EconomicProjectRealizationResult:
    end = end_state or start_state
    no_deal = all(action != ("deal",) for action in actions)
    predicate_satisfied = predicate.is_satisfied(end) if predicate is not None else False
    return EconomicProjectRealizationResult(
        project_id=project.project_id,
        project_kind=project.kind,
        predicted_tier=project.assessment.frontier_tier,
        predicate=predicate,
        status=status,
        max_added_cost=max_added_cost,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        actual_corrected_cost=cost,
        actions=tuple(actions),
        nodes_expanded=nodes,
        elapsed_seconds=elapsed,
        predicate_satisfied=predicate_satisfied,
        independent_replay_verified=False,
        no_stock_deal=no_deal,
        stock_count_before=len(start_state.stock),
        stock_count_after=len(end.stock),
        foundation_count_before=len(start_state.foundations),
        foundation_count_after=len(end.foundations),
        start_key=canonical_state_key(start_state),
        result_key=canonical_state_key(end) if end_state is not None else None,
        progress=_progress(start_state, end, predicate),
        notes=tuple(notes),
        prediction_fingerprint=prediction_fingerprint,
    )


def realize_economic_project(
    start_state: SpiderState,
    project: EconomicProject,
    cards: Sequence[Card],
    *,
    max_added_cost: int = 8,
    max_nodes: int = 50_000,
    time_limit_s: float = 18.0,
    prediction_fingerprint: str = "",
    allow_foundation_increase: bool = False,
) -> EconomicProjectRealizationResult:
    """Realize one frozen project under a tableau-only bounded experiment."""
    del cards  # Card data is required by the public calibration API, not the local predicate search.
    predicate, predicate_reason = project_predicate(start_state, project)
    if predicate is None:
        future = (
            project.earliest_useful_epoch > current_stock_epoch(start_state, 5)
            or project.cost.necessary_stock_deals.ordering_value > 0
        )
        return _result(
            start_state=start_state,
            end_state=None,
            project=project,
            predicate=None,
            status=(
                EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH
                if future
                else EconomicProjectRealizationStatus.INVALID_PROJECT
            ),
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            cost=None,
            actions=(),
            nodes=0,
            elapsed=0.0,
            notes=(predicate_reason,),
            prediction_fingerprint=prediction_fingerprint,
        )

    actions: Tuple[Action, ...] = ()
    cost: Optional[int] = None
    nodes = 0
    elapsed = 0.0
    notes: Tuple[str, ...]
    status: EconomicProjectRealizationStatus

    # Frozen one-move projects should be tested as frozen, not replaced by a
    # tactically prettier route discovered after prediction.
    if project.action is not None and project.kind in (
        EconomicProjectKind.PERMANENT_JOIN,
        EconomicProjectKind.TEMPORARY_REWORK,
        EconomicProjectKind.ASSEMBLE_BAND,
        EconomicProjectKind.REMOVE_MIXED_BOUNDARY,
    ):
        if not start_state.can_move(*project.action):
            return _result(
                start_state=start_state,
                end_state=None,
                project=project,
                predicate=predicate,
                status=EconomicProjectRealizationStatus.INVALID_PROJECT,
                max_added_cost=max_added_cost,
                max_nodes=max_nodes,
                time_limit_s=time_limit_s,
                cost=None,
                actions=(),
                nodes=0,
                elapsed=0.0,
                notes=("frozen action is illegal from experiment start",),
                prediction_fingerprint=prediction_fingerprint,
            )
        trial = start_state.clone()
        trial_cost = trial.move(*project.action)
        if trial_cost > max_added_cost:
            return _result(
                start_state=start_state,
                end_state=None,
                project=project,
                predicate=predicate,
                status=EconomicProjectRealizationStatus.NOT_FOUND_WITHIN_BOUND,
                max_added_cost=max_added_cost,
                max_nodes=max_nodes,
                time_limit_s=time_limit_s,
                cost=None,
                actions=(),
                nodes=1,
                elapsed=0.0,
                notes=("frozen action exceeds matched paid-cost bound",),
                prediction_fingerprint=prediction_fingerprint,
            )
        actions = (project.action,)
        cost = trial_cost
        nodes = 1
        notes = (predicate_reason, "frozen legal action replayed")
        status = (
            EconomicProjectRealizationStatus.PROJECT_ADVANCED
            if (
                project.kind == EconomicProjectKind.TEMPORARY_REWORK
                and not predicate.structural_return_required
            )
            else EconomicProjectRealizationStatus.PROJECT_REALIZED
        )
    else:
        objective = _predicate_to_objective(predicate, project)
        if objective is None:
            return _result(
                start_state=start_state,
                end_state=None,
                project=project,
                predicate=predicate,
                status=EconomicProjectRealizationStatus.INVALID_PROJECT,
                max_added_cost=max_added_cost,
                max_nodes=max_nodes,
                time_limit_s=time_limit_s,
                cost=None,
                actions=(),
                nodes=0,
                elapsed=0.0,
                notes=("predicate has no existing tactical-objective adapter",),
                prediction_fingerprint=prediction_fingerprint,
            )
        tactical = realize_objective(
            start_state,
            objective,
            mode=RealizationMode.EXACT_BOUNDED,
            max_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
        )
        actions = tactical.actions
        cost = tactical.corrected_mw_cost
        nodes = tactical.nodes_expanded
        elapsed = tactical.elapsed_seconds
        notes = (predicate_reason,) + tactical.notes
        if tactical.status == RealizationStatus.RESOURCE_LIMIT:
            status = EconomicProjectRealizationStatus.RESOURCE_LIMIT
        elif tactical.status in (
            RealizationStatus.NOT_FOUND_WITHIN_BOUND,
            RealizationStatus.UNSUPPORTED,
        ):
            status = EconomicProjectRealizationStatus.NOT_FOUND_WITHIN_BOUND
        elif tactical.status in (RealizationStatus.FOUND, RealizationStatus.ALREADY_SATISFIED):
            status = EconomicProjectRealizationStatus.PROJECT_REALIZED
        else:
            status = EconomicProjectRealizationStatus.NOT_FOUND_WITHIN_BOUND

        # A complete-prefix prediction may be unreachable in the bounded
        # current tableau even though the project can make a real first reveal.
        # Search that strictly weaker structural predicate with only the
        # *remaining* matched resources and report ADVANCED, never REALIZED.
        if (
            status == EconomicProjectRealizationStatus.NOT_FOUND_WITHIN_BOUND
            and project.kind
            in (
                EconomicProjectKind.EXCAVATE_CARD,
                EconomicProjectKind.EXCAVATE_COLUMN_PREFIX,
            )
            and predicate.target_column is not None
            and len(start_state.columns[predicate.target_column].face_down) > 0
            and nodes < max_nodes
            and elapsed < time_limit_s
        ):
            advance_predicate = EconomicProjectPredicate(
                EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST,
                project.project_id,
                "advance the frozen prefix by at least one real reveal",
                target_column=predicate.target_column,
                max_face_down=(
                    len(start_state.columns[predicate.target_column].face_down) - 1
                ),
            )
            advance_objective = _predicate_to_objective(advance_predicate, project)
            assert advance_objective is not None
            advance = realize_objective(
                start_state,
                advance_objective,
                mode=RealizationMode.EXACT_BOUNDED,
                max_cost=max_added_cost,
                max_nodes=max(1, max_nodes - nodes),
                time_limit_s=max(0.01, time_limit_s - elapsed),
            )
            nodes += advance.nodes_expanded
            elapsed += advance.elapsed_seconds
            notes = notes + (
                "complete prefix not realized; matched-resource partial predicate attempted",
            ) + advance.notes
            if advance.status in (RealizationStatus.FOUND, RealizationStatus.ALREADY_SATISFIED):
                actions = advance.actions
                cost = advance.corrected_mw_cost
                status = EconomicProjectRealizationStatus.PROJECT_ADVANCED
            elif advance.status == RealizationStatus.RESOURCE_LIMIT:
                status = EconomicProjectRealizationStatus.RESOURCE_LIMIT
        if status not in (
            EconomicProjectRealizationStatus.PROJECT_REALIZED,
            EconomicProjectRealizationStatus.PROJECT_ADVANCED,
        ):
            return _result(
                start_state=start_state,
                end_state=None,
                project=project,
                predicate=predicate,
                status=status,
                max_added_cost=max_added_cost,
                max_nodes=max_nodes,
                time_limit_s=time_limit_s,
                cost=None,
                actions=(),
                nodes=nodes,
                elapsed=elapsed,
                notes=notes,
                prediction_fingerprint=prediction_fingerprint,
            )

    if any(action == ("deal",) for action in actions):
        return _result(
            start_state=start_state,
            end_state=None,
            project=project,
            predicate=predicate,
            status=EconomicProjectRealizationStatus.INVALID_PROJECT,
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            cost=None,
            actions=(),
            nodes=nodes,
            elapsed=elapsed,
            notes=notes + ("rejected: tactical route attempted a stock deal",),
            prediction_fingerprint=prediction_fingerprint,
        )

    replay = start_state.clone()
    try:
        replay_cost = replay_actions(replay, list(actions))
    except (AssertionError, ValueError) as exc:
        return _result(
            start_state=start_state,
            end_state=None,
            project=project,
            predicate=predicate,
            status=EconomicProjectRealizationStatus.INVALID_PROJECT,
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            cost=None,
            actions=(),
            nodes=nodes,
            elapsed=elapsed,
            notes=notes + (f"independent replay failed: {exc}",),
            prediction_fingerprint=prediction_fingerprint,
        )
    foundation_ok = allow_foundation_increase or len(replay.foundations) == len(start_state.foundations)
    structural_target_ok = predicate.is_satisfied(replay)
    if (
        status == EconomicProjectRealizationStatus.PROJECT_ADVANCED
        and predicate.kind == EconomicProjectPredicateKind.COLUMN_FACE_DOWN_AT_MOST
        and predicate.target_column is not None
    ):
        structural_target_ok = (
            len(replay.columns[predicate.target_column].face_down)
            < len(start_state.columns[predicate.target_column].face_down)
        )
    replay_verified = bool(
        replay_cost == cost
        and structural_target_ok
        and len(replay.stock) == len(start_state.stock)
        and foundation_ok
    )
    if not replay_verified:
        return _result(
            start_state=start_state,
            end_state=replay,
            project=project,
            predicate=predicate,
            status=EconomicProjectRealizationStatus.INVALID_PROJECT,
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            cost=replay_cost,
            actions=actions,
            nodes=nodes,
            elapsed=elapsed,
            notes=notes + ("rejected: replay/predicate/stock/foundation invariant failed",),
            prediction_fingerprint=prediction_fingerprint,
        )

    if status == EconomicProjectRealizationStatus.PROJECT_ADVANCED:
        pass
    elif project.kind == EconomicProjectKind.TEMPORARY_REWORK and not predicate.structural_return_required:
        status = EconomicProjectRealizationStatus.PROJECT_ADVANCED
    else:
        status = EconomicProjectRealizationStatus.PROJECT_REALIZED
    result = _result(
        start_state=start_state,
        end_state=replay,
        project=project,
        predicate=predicate,
        status=status,
        max_added_cost=max_added_cost,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        cost=replay_cost,
        actions=actions,
        nodes=nodes,
        elapsed=elapsed,
        notes=notes + ("independent corrected replay verified",),
        prediction_fingerprint=prediction_fingerprint,
    )
    return EconomicProjectRealizationResult(
        **{
            **result.__dict__,
            "independent_replay_verified": True,
        }
    )


def realize_economic_project_bounds(
    start_state: SpiderState,
    project: EconomicProject,
    cards: Sequence[Card],
    snapshot: FrozenEconomicPrediction,
    *,
    config: EconomicProjectResourceConfig = EconomicProjectResourceConfig(),
) -> EconomicProjectBoundSeries:
    """Run the same increasing bound series and stop at first realization."""
    if not verify_prediction_freeze(snapshot):
        raise ValueError("economic prediction mutated before realization")
    results: List[EconomicProjectRealizationResult] = []
    for bound in config.added_cost_bounds:
        result = realize_economic_project(
            start_state.clone(),
            project,
            cards,
            max_added_cost=bound,
            max_nodes=config.max_nodes_per_bound,
            time_limit_s=config.time_limit_s_per_bound,
            prediction_fingerprint=snapshot.fingerprint,
            allow_foundation_increase=config.allow_foundation_increase,
        )
        results.append(result)
        if result.status == EconomicProjectRealizationStatus.PROJECT_REALIZED:
            break
        if (
            result.status == EconomicProjectRealizationStatus.PROJECT_ADVANCED
            and project.assessment.frontier_tier
            == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
        ):
            break
        if result.status in (
            EconomicProjectRealizationStatus.INVALID_PROJECT,
            EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH,
        ):
            break
    if not verify_prediction_freeze(snapshot):
        raise AssertionError("realization mutated frozen predictions")
    best = next(
        (
            result
            for result in results
            if result.status == EconomicProjectRealizationStatus.PROJECT_REALIZED
        ),
        next(
            (
                result
                for result in results
                if result.status == EconomicProjectRealizationStatus.PROJECT_ADVANCED
            ),
            results[-1],
        ),
    )
    return EconomicProjectBoundSeries(
        project.project_id,
        config,
        tuple(results),
        best,
        snapshot.fingerprint,
    )


def measure_structural_state(
    state: SpiderState,
    *,
    cards: Sequence[Card],
    analysis: Optional[EconomicAnalysisResult] = None,
) -> StructuralMeasurement:
    """Measure hard structural facts plus explicitly heuristic debt/burden."""
    economic = analysis or analyze_economic_projects(state, cards=cards)
    stable = 0
    mass = 0
    mixed = 0
    for pile in state.columns:
        up = pile.face_up
        run_len = 1
        for lower, upper in zip(up, up[1:]):
            if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
                stable += 1
                run_len += 1
            else:
                if run_len >= 2:
                    mass += run_len
                run_len = 1
                if lower.suit != upper.suit:
                    mixed += 1
        if run_len >= 2:
            mass += run_len
    longest, _legacy_mass = longest_same_suit(state)
    must = tuple(
        sorted(
            (
                campaign.label,
                sum(1 for need in campaign.rank_needs if need.must_excavate),
            )
            for campaign in economic.campaign_portfolio.campaigns
        )
    )
    critical = sum(
        1
        for value in economic.reveal_values
        if value.mandatory_for_nearest_campaign
        and value.classification.value
        in ("CRITICAL_NOW", "REQUIRED_BEFORE_NEXT_DEAL")
    )
    empties = tuple(i for i, pile in enumerate(state.columns) if pile.is_empty())
    return StructuralMeasurement(
        face_down_count=sum(len(pile.face_down) for pile in state.columns),
        foundation_count=len(state.foundations),
        stock_count=len(state.stock),
        empty_columns=empties,
        fully_open_columns=tuple(fully_open_nonempty(state)),
        legal_move_count=len(state.enumerate_moves()),
        stable_same_suit_joins=stable,
        same_suit_run_mass=mass,
        longest_same_suit_run=longest,
        mixed_suit_boundaries=mixed,
        rehandling_debt=float(mixed),
        critical_dependencies_pending=critical,
        campaign_must_burden=must,
        frontier_order=tuple(
            (project.project_id, int(project.assessment.frontier_tier))
            for project in economic.frontier.ordered_projects
        ),
    )


def structural_outcome_vector(
    before: StructuralMeasurement,
    after: StructuralMeasurement,
    *,
    paid_cost: Optional[int],
    target_dependencies_satisfied: int,
    bounded_downstream_cost_delta: Optional[int] = None,
) -> StructuralOutcomeVector:
    before_must = sum(value for _label, value in before.campaign_must_burden)
    after_must = sum(value for _label, value in after.campaign_must_burden)
    return StructuralOutcomeVector(
        paid_cost=paid_cost,
        critical_dependencies_removed=(
            before.critical_dependencies_pending - after.critical_dependencies_pending
        ),
        stable_joins_delta=after.stable_same_suit_joins - before.stable_same_suit_joins,
        same_suit_mass_delta=after.same_suit_run_mass - before.same_suit_run_mass,
        mixed_boundaries_delta=after.mixed_suit_boundaries - before.mixed_suit_boundaries,
        workspace_delta=len(after.empty_columns) - len(before.empty_columns),
        mobility_delta=after.legal_move_count - before.legal_move_count,
        must_burden_delta=before_must - after_must,
        bounded_downstream_cost_delta=bounded_downstream_cost_delta,
        rehandling_debt_delta=after.rehandling_debt - before.rehandling_debt,
        target_dependencies_satisfied=target_dependencies_satisfied,
    )


def target_dependencies_satisfied(
    start: SpiderState,
    end: SpiderState,
    project: EconomicProject,
) -> int:
    """Count frozen reveal sources that left the face-down zone."""
    satisfied = 0
    for value in project.reveal_values:
        column = value.column
        before_fd = len(start.columns[column].face_down)
        after_fd = len(end.columns[column].face_down)
        if after_fd < before_fd and after_fd <= max(0, before_fd - value.reveal_depth):
            satisfied += 1
    if not project.reveal_values and project.action is not None:
        predicate, _reason = project_predicate(start, project)
        if predicate is not None and predicate.is_satisfied(end):
            satisfied = 1
    return satisfied


def select_downstream_project(
    state: SpiderState,
    analysis: EconomicAnalysisResult,
    *,
    exclude_project_id: str,
) -> Tuple[Optional[EconomicProject], Optional[EconomicProjectPredicate]]:
    """Choose the nearest current-epoch machine-testable follow-on project."""
    for project in analysis.frontier.ordered_projects:
        if project.project_id == exclude_project_id:
            continue
        predicate, _reason = project_predicate(state, project)
        if predicate is None or predicate.is_satisfied(state):
            continue
        if _predicate_to_objective(predicate, project) is None:
            continue
        return project, predicate
    return None, None


def run_downstream_probe(
    original_state: SpiderState,
    post_state: SpiderState,
    post_analysis: EconomicAnalysisResult,
    cards: Sequence[Card],
    snapshot: FrozenEconomicPrediction,
    *,
    completed_project_id: str,
    config: EconomicProjectResourceConfig,
) -> DownstreamProbeResult:
    """Run one identical small objective probe from original and post states."""
    project, predicate = select_downstream_project(
        post_state, post_analysis, exclude_project_id=completed_project_id
    )
    if project is None or predicate is None:
        return DownstreamProbeResult(
            None,
            None,
            config.downstream_max_cost,
            config.downstream_max_nodes,
            config.downstream_time_limit_s,
            EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH,
            None,
            EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH,
            None,
            None,
            True,
            "no clean comparable downstream project",
        )

    def probe(state: SpiderState) -> EconomicProjectRealizationResult:
        # The downstream project was selected post-realization.  Its frozen
        # structural predicate is searched identically from both states.
        objective = _predicate_to_objective(predicate, project)
        assert objective is not None
        tactical = realize_objective(
            state,
            objective,
            mode=RealizationMode.EXACT_BOUNDED,
            max_cost=config.downstream_max_cost,
            max_nodes=config.downstream_max_nodes,
            time_limit_s=config.downstream_time_limit_s,
        )
        status = (
            EconomicProjectRealizationStatus.PROJECT_REALIZED
            if tactical.status in (RealizationStatus.FOUND, RealizationStatus.ALREADY_SATISFIED)
            else (
                EconomicProjectRealizationStatus.RESOURCE_LIMIT
                if tactical.status == RealizationStatus.RESOURCE_LIMIT
                else EconomicProjectRealizationStatus.NOT_FOUND_WITHIN_BOUND
            )
        )
        return _result(
            start_state=state,
            end_state=None,
            project=project,
            predicate=predicate,
            status=status,
            max_added_cost=config.downstream_max_cost,
            max_nodes=config.downstream_max_nodes,
            time_limit_s=config.downstream_time_limit_s,
            cost=tactical.corrected_mw_cost,
            actions=tactical.actions,
            nodes=tactical.nodes_expanded,
            elapsed=tactical.elapsed_seconds,
            notes=tactical.notes,
            prediction_fingerprint=snapshot.fingerprint,
        )

    original = probe(original_state.clone())
    post = probe(post_state.clone())
    delta = None
    if original.actual_corrected_cost is not None and post.actual_corrected_cost is not None:
        delta = original.actual_corrected_cost - post.actual_corrected_cost
    return DownstreamProbeResult(
        project.project_id,
        predicate,
        config.downstream_max_cost,
        config.downstream_max_nodes,
        config.downstream_time_limit_s,
        original.status,
        original.actual_corrected_cost,
        post.status,
        post.actual_corrected_cost,
        delta,
        True,
        "identical cost/node/time resources; no stock deal",
    )


def validate_rework_outcome(
    project: EconomicProject,
    result: EconomicProjectRealizationResult,
    vector: StructuralOutcomeVector,
) -> Tuple[ReworkValidation, str]:
    """Require the promised return, never merely a temporary park."""
    if result.status != EconomicProjectRealizationStatus.PROJECT_REALIZED:
        return ReworkValidation.FAILED_TO_REALIZE, "frozen structural predicate was not realized"
    material_return = bool(
        vector.critical_dependencies_removed > 0
        or vector.stable_joins_delta > 0
        or vector.workspace_delta > 0
        or vector.must_burden_delta > 0
        or vector.target_dependencies_satisfied > 0
    )
    debt = max(0.0, vector.rehandling_debt_delta)
    saving = vector.bounded_downstream_cost_delta
    if material_return and saving is not None and saving > debt:
        return ReworkValidation.VALIDATED, "bounded downstream saving exceeds realized debt"
    if material_return:
        return (
            ReworkValidation.PLAUSIBLE,
            "promised structural return occurred, but matched probe does not prove saving exceeds debt",
        )
    return ReworkValidation.NOT_VALIDATED, "temporary work occurred without the promised structural return"


def assess_prediction(
    project: EconomicProject,
    result: EconomicProjectRealizationResult,
    vector: StructuralOutcomeVector,
) -> Tuple[PredictionAssessment, str]:
    if result.status not in (
        EconomicProjectRealizationStatus.PROJECT_REALIZED,
        EconomicProjectRealizationStatus.PROJECT_ADVANCED,
    ):
        return PredictionAssessment.INCONCLUSIVE, "project was not realized within matched resources"
    material = bool(
        vector.critical_dependencies_removed > 0
        or vector.stable_joins_delta > 0
        or vector.same_suit_mass_delta > 0
        or vector.workspace_delta > 0
        or vector.must_burden_delta > 0
        or vector.target_dependencies_satisfied > 0
        or (
            vector.bounded_downstream_cost_delta is not None
            and vector.bounded_downstream_cost_delta > 0
        )
    )
    harmful = bool(
        vector.mixed_boundaries_delta > 0
        or vector.rehandling_debt_delta > 0
    )
    if project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED:
        if material and not harmful:
            return PredictionAssessment.CONTRADICTED, "Tier-4 control produced clean material value"
        return PredictionAssessment.CONFIRMED, "control produced no clean return beyond its liability"
    if project.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT:
        if result.status == EconomicProjectRealizationStatus.PROJECT_REALIZED and vector.stable_joins_delta > 0:
            return PredictionAssessment.CONFIRMED, "permanent same-suit structure materialized at frozen cost"
        return PredictionAssessment.CONTRADICTED, "dominant prediction failed to create its permanent structure"
    if material:
        return (
            PredictionAssessment.CONFIRMED
            if not harmful
            else PredictionAssessment.DIRECTIONALLY_CONFIRMED,
            "predicted structural progress materialized" + (" with additional liability" if harmful else ""),
        )
    return PredictionAssessment.CONTRADICTED, "realized project did not exhibit predicted structural return"
