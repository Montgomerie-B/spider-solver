"""Generic anytime strategic controller for corrected-rule Spider.

The primary frontier contains strategic edges, not an unstructured global
raw-move tree.  Economic projects, foundation campaigns, exact deal timing,
and progressively widened fallback moves all produce independently replayed
successors.  The complete resulting state is reanalysed after every retained
edge.

Only exact structural-state dominance and the existing admissible
deal/reveal lower bound may suppress a branch for shortest-score search.
Economic value, campaign estimates, lifecycle debt, deal-timing preferences,
and frontier credit are ordering and coverage devices only.

This module contains no benchmark deal, route, column, suit-order, incumbent,
or leaderboard constants.
"""

from __future__ import annotations

import hashlib
import heapq
import time
from dataclasses import dataclass, field, replace
from enum import Enum, IntEnum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.hash import zobrist
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import MoveLifecycleAssessment, PlacementClass, assess_tableau_move
from spider.planner.deal_timing import (
    DealCounterfactual,
    DealPreparationCandidate,
    DealTimingAssessment,
    DealTimingConfig,
    DealTimingDecisionKind,
    assess_deal_timing,
    build_preparation_candidate,
)
from spider.planner.economic_project_realizer import (
    EconomicProjectRealizationStatus,
    EconomicProjectResourceConfig,
    ProjectActionability,
    StructuralMeasurement,
    measure_structural_state,
    probe_project_actionability,
    project_predicate,
    realize_economic_project,
)
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProject,
    EconomicProjectKind,
    analyze_economic_projects,
)
from spider.planner.foundation_campaign import FoundationCampaign
from spider.planner.foundation_campaign_realizer import (
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    realize_campaign_to_removal_epoch,
)
from spider.planner.incumbent_budget import IncumbentBudget, build_incumbent_budget
from spider.rules import MW_RULES, MobilityWareRules, deal_cost, mw_move_cost
from spider.state_identity import (
    CanonicalStateKey,
    canonical_state_key,
    states_structurally_equal,
)


class AnytimeControllerStatus(str, Enum):
    SOLVED = "SOLVED"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"
    FRONTIER_EXHAUSTED = "FRONTIER_EXHAUSTED"
    PREFLIGHT_FAILED = "PREFLIGHT_FAILED"


class StrategicActionKind(str, Enum):
    ECONOMIC_PROJECT = "ECONOMIC_PROJECT"
    FOUNDATION_CAMPAIGN = "FOUNDATION_CAMPAIGN"
    FOUNDATION_REMOVAL = "FOUNDATION_REMOVAL"
    DEAL_NOW = "DEAL_NOW"
    PREPARE_THEN_DEAL = "PREPARE_THEN_DEAL"
    RAW_TABLEAU_MOVE = "RAW_TABLEAU_MOVE"
    RAW_DEAL = "RAW_DEAL"


class StrategicCreditLevel(IntEnum):
    CLEAN = 0
    POSITIVE_INVESTMENT = 1
    SPECULATIVE = 2
    ESCAPE = 3
    RAW_LEGAL_FALLBACK = 4


@dataclass(frozen=True)
class AnytimeControllerConfig:
    wall_clock_limit_s: float = 60.0
    max_strategic_expansions: int = 400
    max_tactical_nodes: int = 100_000
    max_frontier_size: int = 2_000
    max_credit_level: StrategicCreditLevel = StrategicCreditLevel.RAW_LEGAL_FALLBACK
    max_successors_per_expansion: int = 12
    max_trace_entries: int = 256
    max_timeline_entries: int = 256
    campaign_source_combination_limit: int = 64
    max_direct_projects_per_tier: int = 2
    max_bounded_projects_per_expansion: int = 1
    tactical_max_cost_by_credit: Tuple[int, ...] = (1, 4, 6, 8, 10)
    tactical_nodes_per_project: int = 2_000
    tactical_time_limit_s_per_project: float = 0.5
    enable_campaign_edges: bool = True
    campaign_branches_clean: int = 0
    campaign_branches_positive: int = 1
    campaign_branches_speculative: int = 2
    campaign_max_added_cost: int = 18
    campaign_max_nodes: int = 8_000
    campaign_time_limit_s: float = 2.0
    campaign_beam_width: int = 128
    enable_removal_edges: bool = True
    deal_preparation_arms: int = 1
    deal_pair_arms: int = 0
    deal_timing_config: DealTimingConfig = field(
        default_factory=lambda: DealTimingConfig(
            max_preparation_projects=2,
            max_preparation_cost=4,
            hard_preparation_cost_cap=8,
            max_h1_candidates=2,
            max_h2_candidates=1,
            tactical_max_cost=3,
            tactical_max_nodes=1_000,
            tactical_time_limit_s=0.25,
            downstream_max_cost=5,
            downstream_max_nodes=1_000,
            downstream_time_limit_s=0.25,
        )
    )

    def __post_init__(self) -> None:
        if self.wall_clock_limit_s <= 0:
            raise ValueError("wall-clock limit must be positive")
        if self.max_strategic_expansions <= 0 or self.max_tactical_nodes <= 0:
            raise ValueError("expansion and tactical-node limits must be positive")
        if self.max_frontier_size <= 0 or self.max_successors_per_expansion <= 0:
            raise ValueError("frontier and successor limits must be positive")
        if not 0 <= int(self.max_credit_level) <= 4:
            raise ValueError("maximum credit level must be in 0..4")
        if len(self.tactical_max_cost_by_credit) != 5:
            raise ValueError("tactical cost schedule must contain five credit levels")
        if tuple(sorted(self.tactical_max_cost_by_credit)) != self.tactical_max_cost_by_credit:
            raise ValueError("tactical cost schedule must widen monotonically")
        if self.max_trace_entries < 0 or self.max_timeline_entries < 0:
            raise ValueError("telemetry bounds must be non-negative")


@dataclass(frozen=True)
class ActiveRuleProfile:
    suits: int
    cards: int
    tableau_columns: int
    stock_rows: int
    single_card_mixed_destination_legal: bool
    multi_card_same_suit_required: bool
    empty_column_move_legal: bool
    can_deal_into_empty: bool
    next_row_is_stock_tail: bool
    deal_left_to_right: bool
    complete_same_suit_king_ace_removal: bool
    tableau_move_cost: int
    whole_open_column_to_empty_cost: int
    deal_cost: int
    foundation_removal_cost: int
    solved_requires_eight_foundations_empty_stock_tableau: bool


@dataclass(frozen=True)
class ControllerPreflight:
    passed: bool
    profile: ActiveRuleProfile
    failures: Tuple[str, ...]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class StrategicAnalysisSnapshot:
    state_hash: str
    economic: EconomicAnalysisResult
    measurement: StructuralMeasurement
    budget: IncumbentBudget
    actionable_projects: Tuple[str, ...]
    blocked_high_value_projects: Tuple[str, ...]
    deal_timing: Optional[DealTimingAssessment]
    campaign_summary: Tuple[Tuple[str, str, float], ...]
    project_frontier_summary: Tuple[Tuple[str, int, float], ...]


@dataclass(frozen=True)
class StrategicSuccessor:
    kind: StrategicActionKind
    category: str
    label: str
    actions: Tuple[Action, ...]
    corrected_cost: int
    end_state: SpiderState
    credit_level: StrategicCreditLevel
    predicted_tactical_cost: Optional[int]
    realized_tactical_cost: int
    tactical_nodes: int
    independent_replay_verified: bool
    proof_pruning_allowed: bool
    rationale: Tuple[str, ...]
    source_project_id: Optional[str] = None
    analysis: Optional[StrategicAnalysisSnapshot] = None


@dataclass(frozen=True)
class StrategicSearchNode:
    node_id: int
    state: SpiderState
    g: int
    actions: Tuple[Action, ...]
    parent_id: Optional[int]
    incoming_edge: Optional[StrategicSuccessor]
    depth: int
    credit_level: StrategicCreditLevel
    analysis: StrategicAnalysisSnapshot


@dataclass(frozen=True)
class IncumbentRecord:
    corrected_cost: int
    actions: Tuple[Action, ...]
    explicit_commands: int
    tableau_commands: int
    stock_deals: int
    foundations: int
    stock_remaining: int
    path_hash: str
    final_state_hash: str
    independently_replay_verified: bool
    search_endpoint_matches_replay: bool
    installed_after_expansions: int
    installed_after_seconds: float
    source: str = "machine"


@dataclass(frozen=True)
class DecisionTraceEntry:
    state_hash: str
    g: int
    stock_epoch: int
    foundations: int
    face_down: int
    empty_columns: Tuple[int, ...]
    legal_mobility: int
    same_suit_mass: int
    stable_joins: int
    mixed_boundaries: int
    rehandling_debt: float
    campaign_summary: Tuple[Tuple[str, str, float], ...]
    project_frontier_summary: Tuple[Tuple[str, int, float], ...]
    actionable_projects: Tuple[str, ...]
    blocked_high_value_projects: Tuple[str, ...]
    deal_timing_decision: Optional[str]
    deal_alternatives_retained: int
    strategic_credit_level: int
    chosen_successors: Tuple[str, ...]
    h_admissible: int
    incumbent: Optional[int]
    hard_headroom: Optional[int]
    reason: str


@dataclass
class ControllerTelemetry:
    expanded: int = 0
    generated: int = 0
    retained: int = 0
    tactical_nodes: int = 0
    reanalyses: int = 0
    full_reanalyses_after_foundation: int = 0
    full_reanalyses_after_deal: int = 0
    tt_new: int = 0
    tt_improved: int = 0
    tt_suppressed: int = 0
    exact_loop_suppressed: int = 0
    actionability_cache_hits: int = 0
    actionability_cache_misses: int = 0
    inaccessible_retry_suppressed: int = 0
    proof_pruned: int = 0
    heuristic_pruned: int = 0
    frontier_trimmed: int = 0
    solution_candidates: int = 0
    solution_replay_failures: int = 0
    deal_successors_generated: int = 0
    deal_preparations_retained: int = 0
    credit_expansions: Dict[int, int] = field(default_factory=dict)
    successor_kinds: Dict[str, int] = field(default_factory=dict)
    suppression_reasons: Dict[str, int] = field(default_factory=dict)
    decision_trace: List[DecisionTraceEntry] = field(default_factory=list)
    deal_timeline: List[Tuple[int, int, int, str]] = field(default_factory=list)
    foundation_timeline: List[Tuple[int, int, int, Tuple[str, ...]]] = field(default_factory=list)
    rework_timeline: List[Tuple[int, float, int, int, str]] = field(default_factory=list)
    best_foundations: int = 0
    best_stock_epoch: int = 0
    lowest_face_down: int = 10**9

    def count_suppression(self, reason: str) -> None:
        self.suppression_reasons[reason] = self.suppression_reasons.get(reason, 0) + 1


@dataclass(frozen=True)
class AnytimeSearchResult:
    status: AnytimeControllerStatus
    preflight: ControllerPreflight
    initial_incumbent_cost: Optional[int]
    first_solution: Optional[IncumbentRecord]
    incumbent: Optional[IncumbentRecord]
    incumbent_cost: Optional[int]
    incumbent_progression: Tuple[int, ...]
    best_node: StrategicSearchNode
    elapsed_seconds: float
    strategic_expansions: int
    tactical_nodes: int
    frontier_remaining: int
    maximum_credit_reached: int
    telemetry: ControllerTelemetry
    stop_reason: str


class StrategicTranspositionTable:
    """Exact structural-state dominance by corrected paid cost only."""

    def __init__(self) -> None:
        self._best: Dict[CanonicalStateKey, int] = {}
        self.new_entries = 0
        self.improvements = 0
        self.suppressions = 0

    def __len__(self) -> int:
        return len(self._best)

    def best_g(self, state_or_key: SpiderState | CanonicalStateKey) -> Optional[int]:
        key = (
            state_or_key
            if isinstance(state_or_key, CanonicalStateKey)
            else canonical_state_key(state_or_key)
        )
        return self._best.get(key)

    def admit(
        self,
        state: SpiderState,
        g: int,
        *,
        heuristic_score: object = None,
    ) -> bool:
        """Admit new/lower-g exact states; ignore every heuristic argument."""
        del heuristic_score
        key = canonical_state_key(state)
        previous = self._best.get(key)
        if previous is not None and g >= previous:
            self.suppressions += 1
            return False
        if previous is None:
            self.new_entries += 1
        else:
            self.improvements += 1
        self._best[key] = g
        return True


def _state_hash(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode("utf-8")).hexdigest()[:16]


def _action_path_hash(actions: Sequence[Action]) -> str:
    payload = repr([(action if action != ("deal",) else ("deal",)) for action in actions])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _foundation_suits(state: SpiderState) -> Tuple[str, ...]:
    return tuple(sequence[0].suit for sequence in state.foundations if sequence)


def freeze_active_rule_profile(
    initial_state: SpiderState,
    cards: Sequence[Card],
    *,
    rules: MobilityWareRules = MW_RULES,
    require_unrestricted: bool = True,
) -> ControllerPreflight:
    """Fail-fast state-space/scoring consistency audit without route guidance."""
    failures: List[str] = []
    notes: List[str] = []

    if len(cards) != 104:
        failures.append(f"deal contains {len(cards)} cards, expected 104")
    if len(initial_state.columns) != 10:
        failures.append(f"tableau contains {len(initial_state.columns)} columns, expected 10")
    if len(initial_state.stock) > 50 or len(initial_state.stock) % 10:
        failures.append("remaining stock must contain zero to five complete ten-card rows")
    suits = len({card.suit for card in cards})
    if suits != 4:
        failures.append(f"active deal contains {suits} suits, expected 4")
    if require_unrestricted and not rules.can_deal_into_empty:
        failures.append("active profile must confirm can_deal_into_empty=True")

    mixed_single = SpiderState(
        [Column([], [Card("d", 7)]), Column([], [Card("c", 8)])]
        + [Column([], []) for _ in range(8)],
        [],
    )
    single_mixed_legal = mixed_single.can_move(0, 1, 1)
    if not single_mixed_legal:
        failures.append("single-card cross-suit rank placement regressed")

    mixed_block = SpiderState(
        [Column([], [Card("d", 7), Card("c", 6)]), Column([], [Card("h", 8)])]
        + [Column([], []) for _ in range(8)],
        [],
    )
    same_block = SpiderState(
        [Column([], [Card("d", 7), Card("d", 6)]), Column([], [Card("h", 8)])]
        + [Column([], []) for _ in range(8)],
        [],
    )
    multi_same_required = not mixed_block.can_move(0, 1, 2) and same_block.can_move(0, 1, 2)
    if not multi_same_required:
        failures.append("multi-card same-suit requirement regressed")
    empty_move_legal = same_block.can_move(0, 2, 2)
    if not empty_move_legal:
        failures.append("legal same-suit block cannot move to empty column")

    stock = [Card("c", rank) for rank in range(1, 11)]
    empty_deal_state = SpiderState(
        [Column([], [])] + [Column([], [Card("d", (i % 13) + 1)]) for i in range(1, 10)],
        stock,
    )
    unrestricted_legal = empty_deal_state.can_deal(rules)
    restricted = MobilityWareRules(can_deal_into_empty=False)
    restricted_rejects = not empty_deal_state.can_deal(restricted)
    if rules.can_deal_into_empty and not unrestricted_legal:
        failures.append("empty-column deal rejected under unrestricted profile")
    if not restricted_rejects:
        failures.append("explicit restricted profile accepted an empty-column deal")

    next_row_is_tail = True
    deal_left_to_right = True
    if len(initial_state.stock) >= 10:
        row = tuple(initial_state.stock[-10:])
        dealt = initial_state.clone()
        before_stock = tuple(dealt.stock)
        before_lengths = tuple(len(column.face_up) for column in dealt.columns)
        paid = dealt.deal(rules)
        next_row_is_tail = tuple(before_stock[-10:]) == row and tuple(dealt.stock) == before_stock[:-10]
        # A foundation cascade can remove the appended row; otherwise verify
        # the exact insertion position in every column.
        deal_left_to_right = all(
            len(dealt.columns[index].face_up) == before_lengths[index] + 1
            and dealt.columns[index].face_up[before_lengths[index]] == row[index]
            for index in range(10)
        ) or len(dealt.foundations) > len(initial_state.foundations)
        if paid != 1:
            failures.append("stock deal no longer costs one")
        if not next_row_is_tail or not deal_left_to_right:
            failures.append("stock tail/left-to-right deal ordering regressed")

    foundation_state = SpiderState(
        [Column([], [Card("s", rank) for rank in range(13, 0, -1)])]
        + [Column([], []) for _ in range(9)],
        [],
    )
    foundation_removed = foundation_state.check_seq(0)
    complete_foundation = bool(
        foundation_removed
        and len(foundation_state.foundations) == 1
        and len(foundation_state.foundations[0]) == 13
        and foundation_state.columns[0].is_empty()
    )
    if not complete_foundation:
        failures.append("automatic same-suit K-A removal regressed")

    ordinary_cost = mw_move_cost(
        cards_moved=1,
        source_face_up_count=1,
        dest_was_empty=False,
        source_face_down_count=0,
        rules=rules,
    )
    free_cost = mw_move_cost(
        cards_moved=2,
        source_face_up_count=2,
        dest_was_empty=True,
        source_face_down_count=0,
        rules=rules,
    )
    covered_cost = mw_move_cost(
        cards_moved=2,
        source_face_up_count=2,
        dest_was_empty=True,
        source_face_down_count=1,
        rules=rules,
    )
    if (ordinary_cost, free_cost, covered_cost, deal_cost()) != (1, 0, 1, 1):
        failures.append("corrected move/deal scoring regressed")

    solved_probe = SpiderState(
        [Column([], []) for _ in range(10)],
        [],
        [[Card(suit, rank) for rank in range(13, 0, -1)] for suit in "cdhs" for _ in range(2)],
    )
    solved_semantics = solved_probe.is_solved()
    if not solved_semantics:
        failures.append("solved-state semantics regressed")

    notes.extend(
        (
            "single-card destination rank is exact and suit-independent",
            "multi-card blocks are descending and same-suit",
            "foundation removal is automatic and zero-cost",
            "only exact state and admissible incumbent budget may proof-prune",
        )
    )
    profile = ActiveRuleProfile(
        suits=suits,
        cards=len(cards),
        tableau_columns=len(initial_state.columns),
        stock_rows=5,
        single_card_mixed_destination_legal=single_mixed_legal,
        multi_card_same_suit_required=multi_same_required,
        empty_column_move_legal=empty_move_legal,
        can_deal_into_empty=rules.can_deal_into_empty,
        next_row_is_stock_tail=next_row_is_tail,
        deal_left_to_right=deal_left_to_right,
        complete_same_suit_king_ace_removal=complete_foundation,
        tableau_move_cost=ordinary_cost,
        whole_open_column_to_empty_cost=free_cost,
        deal_cost=deal_cost(),
        foundation_removal_cost=0,
        solved_requires_eight_foundations_empty_stock_tableau=solved_semantics,
    )
    return ControllerPreflight(not failures, profile, tuple(failures), tuple(notes))


def allowed_frontier_tiers(
    credit: StrategicCreditLevel,
) -> Tuple[EconomicFrontierTier, ...]:
    if credit == StrategicCreditLevel.CLEAN:
        return (EconomicFrontierTier.STRUCTURALLY_DOMINANT,)
    if credit == StrategicCreditLevel.POSITIVE_INVESTMENT:
        return (
            EconomicFrontierTier.STRUCTURALLY_DOMINANT,
            EconomicFrontierTier.POSITIVE_INVESTMENT,
        )
    if credit == StrategicCreditLevel.SPECULATIVE:
        return (
            EconomicFrontierTier.STRUCTURALLY_DOMINANT,
            EconomicFrontierTier.POSITIVE_INVESTMENT,
            EconomicFrontierTier.SPECULATIVE_DEFERRABLE,
        )
    return tuple(EconomicFrontierTier)


def raw_fallback_enabled(credit: StrategicCreditLevel) -> bool:
    return credit == StrategicCreditLevel.RAW_LEGAL_FALLBACK


def _direct_preparation_candidates(
    state: SpiderState,
    analysis: EconomicAnalysisResult,
    config: AnytimeControllerConfig,
) -> Tuple[DealPreparationCandidate, ...]:
    direct: List[DealPreparationCandidate] = []
    actions: List[Tuple[int, int, int]] = []
    for project in analysis.frontier.ordered_projects:
        if project.action is None or not state.can_move(*project.action):
            continue
        if project.action in actions:
            continue
        actions.append(project.action)
        candidate = build_preparation_candidate(
            state,
            (project.action,),
            candidate_id=f"controller-h1-{len(actions)}",
            horizon=1,
            source_kinds=(project.kind.value,),
            source_project_ids=(project.project_id,),
            rationale=(
                "currently actionable direct economic project",
                "retained as bounded deal-timing preparation",
            ),
            max_cost=config.deal_timing_config.max_preparation_cost,
        )
        if candidate is not None:
            direct.append(candidate)
        if len(direct) >= config.deal_preparation_arms:
            break
    if config.deal_pair_arms and len(direct) >= 2:
        pair = build_preparation_candidate(
            state,
            direct[0].actions + direct[1].actions,
            candidate_id="controller-h2-1",
            horizon=2,
            source_kinds=direct[0].source_kinds + direct[1].source_kinds,
            source_project_ids=direct[0].source_project_ids + direct[1].source_project_ids,
            rationale=("non-redundant pair of strongest direct preparations",),
            max_cost=config.deal_timing_config.max_preparation_cost,
        )
        if pair is not None:
            direct.append(pair)
    return tuple(direct)


def _actionability_partition(
    state: SpiderState,
    analysis: EconomicAnalysisResult,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    actionable: List[str] = []
    blocked: List[str] = []
    for project in analysis.frontier.ordered_projects:
        if project.assessment.frontier_tier.value > 2:
            continue
        predicate, _reason = project_predicate(state, project)
        direct = project.action is not None and state.can_move(*project.action)
        if direct or (predicate is not None and predicate.is_satisfied(state)):
            actionable.append(project.project_id)
        else:
            blocked.append(project.project_id)
    return tuple(actionable), tuple(blocked)


def analyze_strategic_state(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    spent_cost: int,
    incumbent_cost: Optional[int],
    config: AnytimeControllerConfig,
    include_deal_timing: bool = True,
) -> StrategicAnalysisSnapshot:
    """Recompute all current-state strategic layers from the actual state."""
    economic = analyze_economic_projects(
        state,
        cards=cards,
        campaign_source_combination_limit=config.campaign_source_combination_limit,
    )
    measurement = measure_structural_state(state, cards=cards, analysis=economic)
    budget = build_incumbent_budget(
        state,
        spent_cost=spent_cost,
        incumbent_cost=incumbent_cost,
        heuristic_remaining_work=economic.estimated_remaining_work,
    )
    actionable, blocked = _actionability_partition(state, economic)
    timing: Optional[DealTimingAssessment] = None
    if include_deal_timing and state.can_deal(MW_RULES):
        preparations = _direct_preparation_candidates(state, economic, config)
        timing = assess_deal_timing(
            state,
            cards,
            spent_cost=spent_cost,
            incumbent_cost=incumbent_cost,
            config=config.deal_timing_config,
            preparations=preparations,
            pre_deal_analysis=economic,
            pre_deal_measurement=measurement,
            campaign_source_combination_limit=config.campaign_source_combination_limit,
        )
    campaigns = tuple(
        (
            campaign.label,
            campaign.readiness.value,
            float(campaign.campaign_score),
        )
        for campaign in economic.campaign_portfolio.campaigns[:4]
    )
    frontier = tuple(
        (
            project.project_id,
            int(project.assessment.frontier_tier),
            float(project.assessment.net_economic_value),
        )
        for project in economic.frontier.ordered_projects[:8]
    )
    return StrategicAnalysisSnapshot(
        state_hash=_state_hash(state),
        economic=economic,
        measurement=measurement,
        budget=budget,
        actionable_projects=actionable,
        blocked_high_value_projects=blocked,
        deal_timing=timing,
        campaign_summary=campaigns,
        project_frontier_summary=frontier,
    )


def order_deal_timing_arms(
    assessment: DealTimingAssessment,
) -> Tuple[DealCounterfactual, ...]:
    """Portfolio semantics: timing recommendations order but never oracle-prune."""
    deal = assessment.deal_now
    prepared = list(assessment.prepared_deals)
    marginal_by_id = {value.candidate_id: value for value in assessment.marginal_values}
    prepared.sort(
        key=lambda arm: (
            -(
                marginal_by_id.get(arm.label).downstream.bounded_net_gain
                if marginal_by_id.get(arm.label) is not None
                and marginal_by_id[arm.label].downstream.bounded_net_gain is not None
                else -10**6
            ),
            arm.preparation_cost,
            arm.label,
        )
    )
    selected = assessment.decision.selected_candidate_id
    if selected is not None:
        prepared.sort(key=lambda arm: (arm.label != selected, arm.preparation_cost, arm.label))
    kind = assessment.decision.kind
    if kind == DealTimingDecisionKind.PREPARATION_PREFERRED:
        return tuple(prepared + [deal])
    if kind in (
        DealTimingDecisionKind.DEAL_NOW_PREFERRED,
        DealTimingDecisionKind.DEAL_REQUIRED_FOR_ACTIONABILITY,
    ):
        return tuple([deal] + prepared)
    if kind == DealTimingDecisionKind.COMPARISON_INCONCLUSIVE:
        return tuple([deal] + prepared)
    return (deal,) if deal.post_deal_state is not None else ()


def _project_category(project: EconomicProject) -> str:
    if project.kind in (
        EconomicProjectKind.PERMANENT_JOIN,
        EconomicProjectKind.ASSEMBLE_BAND,
        EconomicProjectKind.REMOVE_MIXED_BOUNDARY,
    ):
        return "permanent_structure"
    if project.kind in (
        EconomicProjectKind.CREATE_WORKSPACE,
        EconomicProjectKind.RECOVER_WORKSPACE,
        EconomicProjectKind.EXCAVATE_CARD,
        EconomicProjectKind.EXCAVATE_COLUMN_PREFIX,
    ):
        return "workspace_excavation"
    if project.kind == EconomicProjectKind.FOUNDATION_CAMPAIGN_STEP:
        return "campaign"
    if project.kind in (
        EconomicProjectKind.TEMPORARY_REWORK,
        EconomicProjectKind.DEFERRED_PROJECT,
    ):
        return "rework"
    return "other"


def _replay_edge(
    start: SpiderState,
    actions: Sequence[Action],
    expected: SpiderState,
    expected_cost: int,
) -> bool:
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(actions))
    except (ValueError, AssertionError, IndexError):
        return False
    return cost == expected_cost and states_structurally_equal(replay, expected)


def _lifecycle_rationale(lifecycle: MoveLifecycleAssessment) -> Tuple[str, ...]:
    benefit = lifecycle.compensating_benefit
    override = (
        benefit.override_reason
        if lifecycle.can_override_permanent_join and benefit is not None
        else "none; no bounded compensating saving exceeds rehandling debt"
    )
    return (
        f"placement={lifecycle.placement_class.value}",
        f"same_suit_joins_created={lifecycle.same_suit_joins_created}",
        f"same_suit_joins_broken={lifecycle.same_suit_joins_broken}",
        f"mixed_suit_boundaries_created={lifecycle.mixed_suit_boundaries_created}",
        f"mixed_suit_boundaries_removed={lifecycle.mixed_suit_boundaries_removed}",
        f"future_exit_route={lifecycle.future_exit_route}",
        f"exit_route_bounded={lifecycle.exit_route_bounded}",
        f"estimated_rehandling_cost={lifecycle.estimated_rehandling_cost}",
        f"permanent_join_override_reason={override}",
    )


def _successor_from_deal_arm(
    node: StrategicSearchNode,
    arm: DealCounterfactual,
) -> Optional[StrategicSuccessor]:
    if arm.post_deal_state is None or not arm.independent_replay_verified:
        return None
    kind = (
        StrategicActionKind.DEAL_NOW
        if arm.preparation is None
        else StrategicActionKind.PREPARE_THEN_DEAL
    )
    return StrategicSuccessor(
        kind=kind,
        category="deal_timing",
        label=arm.label,
        actions=arm.actions,
        corrected_cost=arm.total_added_cost,
        end_state=arm.post_deal_state.clone(),
        credit_level=node.credit_level,
        predicted_tactical_cost=arm.total_added_cost,
        realized_tactical_cost=arm.total_added_cost,
        tactical_nodes=0,
        independent_replay_verified=True,
        proof_pruning_allowed=False,
        rationale=(
            "exact next stock row is a first-class successor",
            "deal-timing recommendation controls ordering, not branch deletion",
        ),
        source_project_id=(arm.preparation.candidate_id if arm.preparation else None),
    )


def _campaign_limit(credit: StrategicCreditLevel, config: AnytimeControllerConfig) -> int:
    if credit == StrategicCreditLevel.CLEAN:
        return config.campaign_branches_clean
    if credit == StrategicCreditLevel.POSITIVE_INVESTMENT:
        return config.campaign_branches_positive
    return config.campaign_branches_speculative


def _apply_direct_project(
    node: StrategicSearchNode,
    project: EconomicProject,
) -> Optional[StrategicSuccessor]:
    action = project.action
    if action is None or not node.state.can_move(*action):
        return None
    lifecycle = assess_tableau_move(node.state, action)
    end = node.state.clone()
    before_foundations = len(end.foundations)
    cost = end.move(*action, rules=MW_RULES)
    verified = _replay_edge(node.state, (action,), end, cost)
    if not verified:
        return None
    category = _project_category(project)
    return StrategicSuccessor(
        StrategicActionKind.ECONOMIC_PROJECT,
        category,
        project.description,
        (action,),
        cost,
        end,
        node.credit_level,
        int(round(project.cost.ordering_total)),
        cost,
        1,
        True,
        False,
        _lifecycle_rationale(lifecycle)
        + (
            f"frontier tier={int(project.assessment.frontier_tier)}",
            "direct frozen project action independently replayed",
            (
                "automatic foundation removal occurred; child requires full reanalysis"
                if len(end.foundations) > before_foundations
                else "no automatic foundation removal on this edge"
            ),
        ),
        project.project_id,
    )


def _raw_move_successors(
    node: StrategicSearchNode,
) -> List[StrategicSuccessor]:
    ranked: List[Tuple[Tuple, StrategicSuccessor]] = []
    for action in node.state.enumerate_moves():
        lifecycle = assess_tableau_move(node.state, action)
        end = node.state.clone()
        cost = end.move(*action, rules=MW_RULES)
        verified = _replay_edge(node.state, (action,), end, cost)
        if not verified:
            continue
        successor = StrategicSuccessor(
            StrategicActionKind.RAW_TABLEAU_MOVE,
            "raw_fallback",
            f"raw move {action[0] + 1}->{action[1] + 1} k={action[2]}",
            (action,),
            cost,
            end,
            node.credit_level,
            None,
            cost,
            1,
            True,
            False,
            _lifecycle_rationale(lifecycle),
        )
        rank = (
            lifecycle.ordering_key(),
            -len(end.foundations),
            sum(len(column.face_down) for column in end.columns),
            action,
        )
        ranked.append((rank, successor))
    ranked.sort(key=lambda item: item[0])
    return [successor for _rank, successor in ranked]


def deduplicate_strategic_successors(
    successors: Iterable[StrategicSuccessor],
) -> Tuple[StrategicSuccessor, ...]:
    """Keep the cheapest representative for each exact resulting state."""
    by_key: Dict[CanonicalStateKey, StrategicSuccessor] = {}
    order: List[CanonicalStateKey] = []
    for successor in successors:
        key = canonical_state_key(successor.end_state)
        previous = by_key.get(key)
        if previous is None:
            by_key[key] = successor
            order.append(key)
        elif (successor.corrected_cost, len(successor.actions), successor.label) < (
            previous.corrected_cost,
            len(previous.actions),
            previous.label,
        ):
            by_key[key] = successor
    return tuple(by_key[key] for key in order)


def retain_diverse_portfolio(
    successors: Sequence[StrategicSuccessor],
    *,
    maximum: int,
) -> Tuple[StrategicSuccessor, ...]:
    """Round-robin categories before filling remaining priority slots."""
    if len(successors) <= maximum:
        return tuple(successors)
    categories = (
        "deal_timing",
        "permanent_structure",
        "campaign",
        "workspace_excavation",
        "rework",
        "other",
        "raw_fallback",
    )
    retained: List[StrategicSuccessor] = []
    seen: set[int] = set()
    for category in categories:
        for index, successor in enumerate(successors):
            if successor.category == category:
                retained.append(successor)
                seen.add(index)
                break
        if len(retained) >= maximum:
            return tuple(retained)
    for index, successor in enumerate(successors):
        if index in seen:
            continue
        retained.append(successor)
        if len(retained) >= maximum:
            break
    return tuple(retained)


def _remaining_controller_time(started: float, config: AnytimeControllerConfig) -> float:
    return max(0.0, config.wall_clock_limit_s - (time.perf_counter() - started))


def generate_strategic_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    incumbent_cost: Optional[int],
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    actionability_cache: Dict[Tuple, ProjectActionability],
    started: float,
) -> Tuple[StrategicSuccessor, ...]:
    """Generate a small diverse, replay-verified strategic portfolio."""
    raw: List[StrategicSuccessor] = []
    analysis = node.analysis

    if analysis.deal_timing is not None:
        for arm in order_deal_timing_arms(analysis.deal_timing):
            successor = _successor_from_deal_arm(node, arm)
            if successor is not None:
                raw.append(successor)
                telemetry.deal_successors_generated += 1
                if successor.kind == StrategicActionKind.PREPARE_THEN_DEAL:
                    telemetry.deal_preparations_retained += 1

    allowed = set(allowed_frontier_tiers(node.credit_level))
    direct_per_tier: Dict[EconomicFrontierTier, int] = {}
    bounded_used = 0
    for project in analysis.economic.frontier.ordered_projects:
        tier = project.assessment.frontier_tier
        if tier not in allowed:
            continue
        if project.action is not None:
            if direct_per_tier.get(tier, 0) >= config.max_direct_projects_per_tier:
                continue
            successor = _apply_direct_project(node, project)
            if successor is not None:
                raw.append(successor)
                direct_per_tier[tier] = direct_per_tier.get(tier, 0) + 1
            continue
        if node.credit_level < StrategicCreditLevel.POSITIVE_INVESTMENT:
            continue
        if bounded_used >= config.max_bounded_projects_per_expansion:
            continue
        if _remaining_controller_time(started, config) <= 0:
            break
        resource = EconomicProjectResourceConfig(
            added_cost_bounds=(
                config.tactical_max_cost_by_credit[int(node.credit_level)],
            ),
            max_nodes_per_bound=min(
                config.tactical_nodes_per_project,
                max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
            ),
            time_limit_s_per_bound=min(
                config.tactical_time_limit_s_per_project,
                max(0.01, _remaining_controller_time(started, config)),
            ),
            allow_foundation_increase=True,
        )
        cache_key = (
            canonical_state_key(node.state),
            project.project_id,
            int(node.credit_level),
            resource.added_cost_bounds,
            resource.max_nodes_per_bound,
        )
        actionability = actionability_cache.get(cache_key)
        if actionability is None:
            telemetry.actionability_cache_misses += 1
            actionability = probe_project_actionability(
                node.state,
                project,
                config=resource,
            )
            actionability_cache[cache_key] = actionability
            telemetry.tactical_nodes += actionability.nodes_expanded
        else:
            telemetry.actionability_cache_hits += 1
        if not actionability.actionable_current_epoch:
            telemetry.inaccessible_retry_suppressed += 1
            continue
        result = realize_economic_project(
            node.state,
            project,
            cards,
            max_added_cost=resource.added_cost_bounds[-1],
            max_nodes=resource.max_nodes_per_bound,
            time_limit_s=resource.time_limit_s_per_bound,
            allow_foundation_increase=True,
        )
        telemetry.tactical_nodes += result.nodes_expanded
        bounded_used += 1
        if (
            result.status
            not in (
                EconomicProjectRealizationStatus.PROJECT_REALIZED,
                EconomicProjectRealizationStatus.PROJECT_ADVANCED,
            )
            or not result.independent_replay_verified
            or not result.actions
            or result.actual_corrected_cost is None
        ):
            continue
        end = node.state.clone()
        replay_cost = replay_actions(end, list(result.actions))
        if replay_cost != result.actual_corrected_cost:
            continue
        raw.append(
            StrategicSuccessor(
                StrategicActionKind.ECONOMIC_PROJECT,
                _project_category(project),
                project.description,
                result.actions,
                replay_cost,
                end,
                node.credit_level,
                int(round(project.cost.ordering_total)),
                replay_cost,
                result.nodes_expanded,
                True,
                False,
                tuple(result.notes),
                project.project_id,
            )
        )

    campaign_limit = _campaign_limit(node.credit_level, config)
    if (
        config.enable_campaign_edges
        and campaign_limit > 0
        and telemetry.tactical_nodes < config.max_tactical_nodes
        and _remaining_controller_time(started, config) > 0
    ):
        campaigns = analysis.economic.campaign_portfolio.campaigns[:campaign_limit]
        for campaign in campaigns:
            if _remaining_controller_time(started, config) <= 0:
                break
            remaining_nodes = max(1, config.max_tactical_nodes - telemetry.tactical_nodes)
            result = realize_campaign_to_next_epoch(
                node.state,
                campaign,
                cards,
                max_added_cost=config.campaign_max_added_cost,
                max_nodes=min(config.campaign_max_nodes, remaining_nodes),
                time_limit_s=min(
                    config.campaign_time_limit_s,
                    max(0.01, _remaining_controller_time(started, config)),
                ),
            )
            telemetry.tactical_nodes += result.nodes_expanded
            if (
                result.status
                in (CampaignRealizationStatus.FOUND, CampaignRealizationStatus.PARTIAL)
                and result.independent_replay_verified
                and result.actions
                and result.corrected_added_cost is not None
            ):
                raw.append(
                    StrategicSuccessor(
                        StrategicActionKind.FOUNDATION_CAMPAIGN,
                        "campaign",
                        f"campaign {campaign.label} through next epoch",
                        result.actions,
                        result.corrected_added_cost,
                        result.resulting_state.clone(),
                        node.credit_level,
                        int(round(campaign.estimated_campaign_cost)),
                        result.corrected_added_cost,
                        result.nodes_expanded,
                        True,
                        False,
                        (result.stop_reason, "campaign is reanalysed after this bounded edge"),
                        campaign.label,
                    )
                )

            if (
                config.enable_removal_edges
                and node.credit_level >= StrategicCreditLevel.SPECULATIVE
                and campaign.target_removal_epoch == campaign.current_epoch + 1
                and _remaining_controller_time(started, config) > 0
                and telemetry.tactical_nodes < config.max_tactical_nodes
            ):
                removal = realize_campaign_to_removal_epoch(
                    node.state,
                    campaign,
                    cards,
                    max_added_cost=config.campaign_max_added_cost,
                    max_nodes=min(
                        config.campaign_max_nodes,
                        max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
                    ),
                    time_limit_s=min(
                        config.campaign_time_limit_s,
                        max(0.01, _remaining_controller_time(started, config)),
                    ),
                    beam_width=config.campaign_beam_width,
                )
                telemetry.tactical_nodes += removal.nodes_expanded
                if (
                    removal.status
                    in (
                        CampaignRemovalStatus.FOUNDATION_REMOVED,
                        CampaignRemovalStatus.BAND_COMPLETE,
                        CampaignRemovalStatus.PARTIAL,
                    )
                    and removal.independent_replay_verified
                    and removal.actions
                    and removal.corrected_added_cost is not None
                ):
                    raw.append(
                        StrategicSuccessor(
                            StrategicActionKind.FOUNDATION_REMOVAL,
                            "campaign",
                            f"removal campaign {campaign.label}",
                            removal.actions,
                            removal.corrected_added_cost,
                            removal.end_state.clone(),
                            node.credit_level,
                            int(round(campaign.estimated_campaign_cost)),
                            removal.corrected_added_cost,
                            removal.nodes_expanded,
                            True,
                            False,
                            (removal.stop_reason, "bounded removal miss is not impossibility"),
                            campaign.label,
                        )
                    )

    if raw_fallback_enabled(node.credit_level):
        raw.extend(_raw_move_successors(node))
        if node.state.can_deal(MW_RULES) and analysis.deal_timing is None:
            end = node.state.clone()
            cost = end.deal(MW_RULES)
            raw.append(
                StrategicSuccessor(
                    StrategicActionKind.RAW_DEAL,
                    "deal_timing",
                    "raw legal deal fallback",
                    (("deal",),),
                    cost,
                    end,
                    node.credit_level,
                    1,
                    cost,
                    1,
                    _replay_edge(node.state, (("deal",),), end, cost),
                    False,
                    ("engine-legal deal remains present at raw fallback",),
                )
            )

    deduplicated = deduplicate_strategic_successors(raw)
    return retain_diverse_portfolio(
        deduplicated,
        maximum=config.max_successors_per_expansion,
    )


def _node_priority(node: StrategicSearchNode) -> Tuple:
    measurement = node.analysis.measurement
    return (
        0 if node.state.is_solved() else 1,
        -measurement.foundation_count,
        measurement.face_down_count,
        measurement.stock_count // 10,
        node.analysis.budget.hard_min_total,
        node.g,
        measurement.rehandling_debt,
        -measurement.same_suit_run_mass,
        -len(measurement.empty_columns),
        int(node.credit_level),
        node.depth,
        node.node_id,
    )


def _better_progress(candidate: StrategicSearchNode, incumbent: StrategicSearchNode) -> bool:
    cm = candidate.analysis.measurement
    im = incumbent.analysis.measurement
    return (
        cm.foundation_count,
        -cm.face_down_count,
        -(cm.stock_count // 10),
        -candidate.g,
        cm.same_suit_run_mass,
        -cm.rehandling_debt,
    ) > (
        im.foundation_count,
        -im.face_down_count,
        -(im.stock_count // 10),
        -incumbent.g,
        im.same_suit_run_mass,
        -im.rehandling_debt,
    )


def verify_complete_candidate(
    initial_state: SpiderState,
    endpoint: SpiderState,
    actions: Sequence[Action],
    *,
    expected_cost: int,
    expansions: int,
    elapsed_seconds: float,
) -> Optional[IncumbentRecord]:
    """Independently replay a complete candidate before incumbent admission."""
    replay = initial_state.clone()
    try:
        cost = replay_actions(replay, list(actions))
    except (ValueError, AssertionError, IndexError):
        return None
    endpoint_equal = states_structurally_equal(replay, endpoint)
    solved = bool(
        replay.is_solved()
        and not replay.stock
        and len(replay.foundations) == 8
        and endpoint_equal
        and cost == expected_cost
    )
    if not solved:
        return None
    frozen_actions = tuple(actions)
    return IncumbentRecord(
        corrected_cost=cost,
        actions=frozen_actions,
        explicit_commands=len(frozen_actions),
        tableau_commands=sum(action != ("deal",) for action in frozen_actions),
        stock_deals=sum(action == ("deal",) for action in frozen_actions),
        foundations=len(replay.foundations),
        stock_remaining=len(replay.stock),
        path_hash=_action_path_hash(frozen_actions),
        final_state_hash=format(zobrist(replay), "x"),
        independently_replay_verified=True,
        search_endpoint_matches_replay=endpoint_equal,
        installed_after_expansions=expansions,
        installed_after_seconds=elapsed_seconds,
    )


def _append_bounded(items: List, value, maximum: int) -> None:
    if maximum <= 0:
        return
    if len(items) < maximum:
        items.append(value)


def _trace_expansion(
    node: StrategicSearchNode,
    successors: Sequence[StrategicSuccessor],
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    incumbent_cost: Optional[int],
) -> None:
    m = node.analysis.measurement
    timing = node.analysis.deal_timing
    deal_count = sum(
        successor.kind
        in (
            StrategicActionKind.DEAL_NOW,
            StrategicActionKind.PREPARE_THEN_DEAL,
            StrategicActionKind.RAW_DEAL,
        )
        for successor in successors
    )
    _append_bounded(
        telemetry.decision_trace,
        DecisionTraceEntry(
            state_hash=node.analysis.state_hash,
            g=node.g,
            stock_epoch=5 - m.stock_count // 10,
            foundations=m.foundation_count,
            face_down=m.face_down_count,
            empty_columns=m.empty_columns,
            legal_mobility=m.legal_move_count,
            same_suit_mass=m.same_suit_run_mass,
            stable_joins=m.stable_same_suit_joins,
            mixed_boundaries=m.mixed_suit_boundaries,
            rehandling_debt=m.rehandling_debt,
            campaign_summary=node.analysis.campaign_summary,
            project_frontier_summary=node.analysis.project_frontier_summary,
            actionable_projects=node.analysis.actionable_projects,
            blocked_high_value_projects=node.analysis.blocked_high_value_projects,
            deal_timing_decision=(
                timing.decision.kind.value if timing is not None else None
            ),
            deal_alternatives_retained=deal_count,
            strategic_credit_level=int(node.credit_level),
            chosen_successors=tuple(successor.label for successor in successors),
            h_admissible=node.analysis.budget.admissible_remaining_lower_bound,
            incumbent=incumbent_cost,
            hard_headroom=node.analysis.budget.hard_headroom,
            reason="expanded with diverse strategic portfolio",
        ),
        config.max_trace_entries,
    )


def _record_transition(
    parent: StrategicSearchNode,
    successor: StrategicSuccessor,
    child: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
) -> None:
    pm = parent.analysis.measurement
    cm = child.analysis.measurement
    if cm.stock_count < pm.stock_count:
        _append_bounded(
            telemetry.deal_timeline,
            (child.g, 5 - cm.stock_count // 10, cm.foundation_count, successor.label),
            config.max_timeline_entries,
        )
    if cm.foundation_count > pm.foundation_count:
        _append_bounded(
            telemetry.foundation_timeline,
            (
                child.g,
                cm.foundation_count,
                5 - cm.stock_count // 10,
                _foundation_suits(child.state),
            ),
            config.max_timeline_entries,
        )
    if cm.rehandling_debt != pm.rehandling_debt or cm.stable_same_suit_joins != pm.stable_same_suit_joins:
        _append_bounded(
            telemetry.rework_timeline,
            (
                child.g,
                cm.rehandling_debt - pm.rehandling_debt,
                cm.stable_same_suit_joins - pm.stable_same_suit_joins,
                cm.mixed_suit_boundaries - pm.mixed_suit_boundaries,
                successor.label,
            ),
            config.max_timeline_entries,
        )


def solve_anytime(
    initial_state: SpiderState,
    cards: Sequence[Card],
    incumbent: Optional[int | IncumbentRecord] = None,
    config: AnytimeControllerConfig = AnytimeControllerConfig(),
) -> AnytimeSearchResult:
    """Run one bounded generic anytime strategic search.

    ``incumbent=None`` has no artificial cap.  An integer incumbent supplies
    only a replay-verified external ceiling; it supplies no route or state.
    Every machine solution is installed only after independent replay.
    """
    started = time.perf_counter()
    preflight = freeze_active_rule_profile(initial_state, cards, rules=MW_RULES)
    initial_incumbent_cost = (
        incumbent.corrected_cost if isinstance(incumbent, IncumbentRecord) else incumbent
    )
    supplied_record = incumbent if isinstance(incumbent, IncumbentRecord) else None
    telemetry = ControllerTelemetry()

    # Build one minimal snapshot for a failed preflight result without starting
    # strategic expansion.  The caller receives the exact failure record.
    if not preflight.passed:
        economic = analyze_economic_projects(initial_state, cards=cards)
        measurement = measure_structural_state(initial_state, cards=cards, analysis=economic)
        budget = build_incumbent_budget(
            initial_state,
            spent_cost=0,
            incumbent_cost=initial_incumbent_cost,
            heuristic_remaining_work=economic.estimated_remaining_work,
        )
        root_analysis = StrategicAnalysisSnapshot(
            _state_hash(initial_state), economic, measurement, budget, (), (), None, (), ()
        )
        root = StrategicSearchNode(
            0,
            initial_state.clone(),
            0,
            (),
            None,
            None,
            0,
            StrategicCreditLevel.CLEAN,
            root_analysis,
        )
        return AnytimeSearchResult(
            AnytimeControllerStatus.PREFLIGHT_FAILED,
            preflight,
            initial_incumbent_cost,
            None,
            supplied_record,
            initial_incumbent_cost,
            (),
            root,
            time.perf_counter() - started,
            0,
            0,
            0,
            0,
            telemetry,
            "; ".join(preflight.failures),
        )

    current_incumbent_cost = initial_incumbent_cost
    current_incumbent = supplied_record
    first_solution: Optional[IncumbentRecord] = None
    progression: List[int] = []
    root_analysis = analyze_strategic_state(
        initial_state,
        cards,
        spent_cost=0,
        incumbent_cost=current_incumbent_cost,
        config=config,
    )
    telemetry.reanalyses += 1
    root = StrategicSearchNode(
        0,
        initial_state.clone(),
        0,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        root_analysis,
    )
    best_node = root
    tt = StrategicTranspositionTable()
    tt.admit(root.state, 0)
    frontier: List[Tuple[Tuple, int, StrategicSearchNode]] = []
    uid = 0
    heapq.heappush(frontier, (_node_priority(root), uid, root))
    expansion_credits: set[Tuple[CanonicalStateKey, int]] = set()
    actionability_cache: Dict[Tuple, ProjectActionability] = {}
    maximum_credit_reached = 0
    stop_reason = "frontier exhausted"

    while frontier:
        elapsed = time.perf_counter() - started
        if elapsed >= config.wall_clock_limit_s:
            stop_reason = "wall-clock limit"
            break
        if telemetry.expanded >= config.max_strategic_expansions:
            stop_reason = "strategic expansion limit"
            break
        if telemetry.tactical_nodes >= config.max_tactical_nodes:
            stop_reason = "tactical node limit"
            break

        _priority, _sequence, node = heapq.heappop(frontier)
        expansion_key = (canonical_state_key(node.state), int(node.credit_level))
        if expansion_key in expansion_credits:
            telemetry.exact_loop_suppressed += 1
            continue
        expansion_credits.add(expansion_key)

        # Rebuild the proof budget under a newly installed incumbent without
        # changing heuristic analysis or deal-timing semantics.
        if node.analysis.budget.incumbent_cost != current_incumbent_cost:
            node = replace(
                node,
                analysis=replace(
                    node.analysis,
                    budget=build_incumbent_budget(
                        node.state,
                        spent_cost=node.g,
                        incumbent_cost=current_incumbent_cost,
                        heuristic_remaining_work=node.analysis.economic.estimated_remaining_work,
                    ),
                ),
            )
        if node.analysis.budget.proof_prunable:
            telemetry.proof_pruned += 1
            telemetry.count_suppression("admissible incumbent bound")
            continue

        if node.state.is_solved():
            telemetry.solution_candidates += 1
            verified = verify_complete_candidate(
                initial_state,
                node.state,
                node.actions,
                expected_cost=node.g,
                expansions=telemetry.expanded,
                elapsed_seconds=elapsed,
            )
            if verified is None:
                telemetry.solution_replay_failures += 1
                continue
            if first_solution is None:
                first_solution = verified
            if current_incumbent_cost is None or verified.corrected_cost < current_incumbent_cost:
                current_incumbent = verified
                current_incumbent_cost = verified.corrected_cost
                progression.append(verified.corrected_cost)
            continue

        telemetry.expanded += 1
        maximum_credit_reached = max(maximum_credit_reached, int(node.credit_level))
        telemetry.credit_expansions[int(node.credit_level)] = (
            telemetry.credit_expansions.get(int(node.credit_level), 0) + 1
        )
        m = node.analysis.measurement
        telemetry.best_foundations = max(telemetry.best_foundations, m.foundation_count)
        telemetry.best_stock_epoch = max(telemetry.best_stock_epoch, 5 - m.stock_count // 10)
        telemetry.lowest_face_down = min(telemetry.lowest_face_down, m.face_down_count)
        if _better_progress(node, best_node):
            best_node = node

        successors = generate_strategic_successors(
            node,
            cards,
            incumbent_cost=current_incumbent_cost,
            config=config,
            telemetry=telemetry,
            actionability_cache=actionability_cache,
            started=started,
        )
        telemetry.generated += len(successors)
        _trace_expansion(node, successors, telemetry, config, current_incumbent_cost)

        for successor in successors:
            if not successor.independent_replay_verified:
                telemetry.count_suppression("edge replay failed")
                continue
            ng = node.g + successor.corrected_cost
            if not tt.admit(successor.end_state, ng):
                telemetry.tt_suppressed += 1
                telemetry.count_suppression("exact state reached at no lower g")
                continue
            try:
                child_analysis = analyze_strategic_state(
                    successor.end_state,
                    cards,
                    spent_cost=ng,
                    incumbent_cost=current_incumbent_cost,
                    config=config,
                )
            except (ValueError, AssertionError):
                telemetry.count_suppression("full reanalysis rejected successor")
                continue
            telemetry.reanalyses += 1
            if len(successor.end_state.foundations) > len(node.state.foundations):
                telemetry.full_reanalyses_after_foundation += 1
            if len(successor.end_state.stock) < len(node.state.stock):
                telemetry.full_reanalyses_after_deal += 1
            child_successor = replace(successor, analysis=child_analysis)
            uid += 1
            child = StrategicSearchNode(
                uid,
                successor.end_state.clone(),
                ng,
                node.actions + successor.actions,
                node.node_id,
                child_successor,
                node.depth + 1,
                node.credit_level,
                child_analysis,
            )
            if child.analysis.budget.proof_prunable:
                telemetry.proof_pruned += 1
                telemetry.count_suppression("admissible incumbent bound")
                continue
            heapq.heappush(frontier, (_node_priority(child), uid, child))
            telemetry.retained += 1
            telemetry.successor_kinds[successor.kind.value] = (
                telemetry.successor_kinds.get(successor.kind.value, 0) + 1
            )
            _record_transition(node, successor, child, telemetry, config)

        # Revisit the same exact state at a broader credit.  This bypasses TT
        # admission deliberately: TT dominates state arrival, not expansion
        # coverage.  Each (state, credit) expands at most once.
        if int(node.credit_level) < int(config.max_credit_level):
            next_credit = StrategicCreditLevel(int(node.credit_level) + 1)
            widened_key = (canonical_state_key(node.state), int(next_credit))
            if widened_key not in expansion_credits:
                uid += 1
                widened = replace(node, node_id=uid, credit_level=next_credit)
                heapq.heappush(frontier, (_node_priority(widened), uid, widened))

        if len(frontier) > config.max_frontier_size:
            frontier = heapq.nsmallest(config.max_frontier_size, frontier)
            heapq.heapify(frontier)
            telemetry.frontier_trimmed += 1
            telemetry.heuristic_pruned += 1
            telemetry.count_suppression("bounded frontier trim; not proof")

    telemetry.tt_new = tt.new_entries
    telemetry.tt_improved = tt.improvements
    telemetry.tt_suppressed = max(telemetry.tt_suppressed, tt.suppressions)
    elapsed = time.perf_counter() - started
    if current_incumbent is not None and (
        first_solution is not None or initial_incumbent_cost is None
    ):
        status = AnytimeControllerStatus.SOLVED
    elif frontier:
        status = AnytimeControllerStatus.RESOURCE_LIMIT
    else:
        status = AnytimeControllerStatus.FRONTIER_EXHAUSTED
    return AnytimeSearchResult(
        status=status,
        preflight=preflight,
        initial_incumbent_cost=initial_incumbent_cost,
        first_solution=first_solution,
        incumbent=current_incumbent,
        incumbent_cost=current_incumbent_cost,
        incumbent_progression=tuple(progression),
        best_node=best_node,
        elapsed_seconds=elapsed,
        strategic_expansions=telemetry.expanded,
        tactical_nodes=telemetry.tactical_nodes,
        frontier_remaining=len(frontier),
        maximum_credit_reached=maximum_credit_reached,
        telemetry=telemetry,
        stop_reason=stop_reason,
    )
