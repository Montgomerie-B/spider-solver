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
from spider.move_lifecycle import (
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
)
from spider.planner.analysis_budget import (
    AnalysisResourceLimit,
    ComponentTiming,
    SearchDeadline,
)
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    CampaignCorridorResult,
    CampaignCorridorStatus,
    generate_campaign_corridor_lanes,
    realize_campaign_corridor,
)
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
    RevealValueClass,
    analyze_economic_projects,
)
from spider.planner.foundation_campaign import CampaignReadiness, FoundationCampaign
from spider.planner.foundation_campaign_realizer import (
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    realize_campaign_to_removal_epoch,
)
from spider.planner.incumbent_budget import IncumbentBudget, build_incumbent_budget
from spider.planner.residual_campaign import (
    DealPurpose,
    FoundationCheckpointPortfolio,
    FoundationCheckpointProfile,
    ResidualCampaignAssessment,
    StockOpportunityAssessment,
    analyze_residual_campaign,
    assess_stock_opportunity,
    build_foundation_checkpoint_profile,
    residual_investment_accounting,
    retain_foundation_checkpoint_portfolio,
)
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
    CAMPAIGN_CORRIDOR = "CAMPAIGN_CORRIDOR"
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


class ActionabilityTier(IntEnum):
    SHALLOW = 0
    MODEST = 1
    BROAD = 2


class AnalysisStage(IntEnum):
    EXACT_CHEAP_FACTS = 0
    STRATEGIC_CORE = 1
    EXPENSIVE_OPTIONAL = 2


@dataclass(frozen=True)
class ActionabilityTierSpec:
    tier: ActionabilityTier
    max_added_cost: int
    max_nodes: int
    time_limit_s: float

    def __post_init__(self) -> None:
        if self.max_added_cost < 0 or self.max_nodes <= 0 or self.time_limit_s <= 0:
            raise ValueError("actionability tier resources must be positive")


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
    max_actionability_probes_per_expansion: int = 6
    max_actionability_nodes_per_expansion: int = 3_000
    max_actionability_time_s_per_expansion: float = 1.0
    max_total_actionability_nodes: int = 100_000
    max_actionability_probes_per_tier: Tuple[int, ...] = (4, 4, 4)
    actionability_tiers: Tuple[ActionabilityTierSpec, ...] = field(
        default_factory=lambda: (
            ActionabilityTierSpec(ActionabilityTier.SHALLOW, 2, 256, 0.08),
            ActionabilityTierSpec(ActionabilityTier.MODEST, 4, 750, 0.20),
            ActionabilityTierSpec(ActionabilityTier.BROAD, 6, 1_500, 0.40),
        )
    )
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
    enable_campaign_corridors: bool = False
    corridor_config: CampaignCorridorConfig = field(
        default_factory=CampaignCorridorConfig
    )
    corridor_lanes_by_credit: Tuple[int, ...] = (1, 1, 2, 2, 3)
    enable_expensive_deal_timing: bool = True
    full_analysis_minimum_start_s: float = 0.10
    optional_analysis_minimum_start_s: float = 4.0
    stop_after_first_foundation: bool = False
    target_foundation_count: Optional[int] = None
    enable_residual_conversion: bool = True
    max_foundation_checkpoints: int = 6
    residual_lanes_by_credit: Tuple[int, ...] = (3, 3, 4, 4, 5)
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
        if (
            self.max_actionability_probes_per_expansion <= 0
            or self.max_actionability_nodes_per_expansion <= 0
            or self.max_actionability_time_s_per_expansion <= 0
            or self.max_total_actionability_nodes <= 0
        ):
            raise ValueError("actionability probe limits must be positive")
        if len(self.actionability_tiers) != 3:
            raise ValueError("three normalized actionability tiers are required")
        if tuple(spec.tier for spec in self.actionability_tiers) != tuple(ActionabilityTier):
            raise ValueError("actionability tiers must be ordered SHALLOW, MODEST, BROAD")
        if len(self.max_actionability_probes_per_tier) != len(self.actionability_tiers):
            raise ValueError("per-tier probe quotas must match normalized tiers")
        if min(self.max_actionability_probes_per_tier) <= 0:
            raise ValueError("per-tier probe quotas must be positive")
        if len(self.corridor_lanes_by_credit) != 5:
            raise ValueError("corridor lane schedule must contain five credit levels")
        if tuple(sorted(self.corridor_lanes_by_credit)) != self.corridor_lanes_by_credit:
            raise ValueError("corridor lane schedule must widen monotonically")
        if self.full_analysis_minimum_start_s <= 0 or self.optional_analysis_minimum_start_s <= 0:
            raise ValueError("analysis minimum start thresholds must be positive")
        if self.target_foundation_count is not None and not 1 <= self.target_foundation_count <= 8:
            raise ValueError("target foundation count must be in 1..8")
        if self.max_foundation_checkpoints <= 0:
            raise ValueError("foundation checkpoint limit must be positive")
        if len(self.residual_lanes_by_credit) != 5:
            raise ValueError("residual lane schedule must contain five credit levels")
        if tuple(sorted(self.residual_lanes_by_credit)) != self.residual_lanes_by_credit:
            raise ValueError("residual lane schedule must widen monotonically")


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
class StrategicProgressComponents:
    solved: bool
    foundation_count: int
    removal_ready_campaigns: int
    credible_current_campaigns: int
    near_removal_campaigns: int
    best_campaign_readiness_rank: int
    minimum_campaign_must_burden: int
    total_campaign_must_burden: int
    minimum_campaign_remaining_estimate: float
    critical_dependencies_pending: int
    critical_next_epoch_projects: int
    actionable_high_value_projects: int
    face_down_count: int
    longest_same_suit_run: int
    same_suit_run_mass: int
    stable_same_suit_joins: int
    empty_columns: int
    legal_mobility: int
    mixed_suit_boundaries: int
    rehandling_debt: float
    paid_cost: int

    @property
    def realized_or_ready_foundations(self) -> int:
        return self.foundation_count + self.removal_ready_campaigns

    def ordering_key(self) -> Tuple:
        """Transparent heuristic ordering; stock count is intentionally absent."""
        return (
            0 if self.solved else 1,
            -self.realized_or_ready_foundations,
            -self.removal_ready_campaigns,
            -self.foundation_count,
            -self.near_removal_campaigns,
            self.best_campaign_readiness_rank,
            self.minimum_campaign_must_burden,
            -self.credible_current_campaigns,
            self.total_campaign_must_burden,
            self.minimum_campaign_remaining_estimate,
            self.critical_dependencies_pending,
            -self.critical_next_epoch_projects,
            -self.actionable_high_value_projects,
            self.face_down_count,
            -self.longest_same_suit_run,
            -self.same_suit_run_mass,
            -self.stable_same_suit_joins,
            -self.empty_columns,
            -self.legal_mobility,
            self.mixed_suit_boundaries,
            self.rehandling_debt,
            self.paid_cost,
        )


@dataclass(frozen=True)
class StructuralProgressDelta:
    foundation_delta: int
    critical_dependencies_removed: int
    actionable_high_value_delta: int
    campaign_must_burden_reduction: int
    same_suit_mass_delta: int
    stable_join_delta: int
    mixed_boundary_reduction: int
    rehandling_debt_reduction: float
    workspace_delta: int
    mobility_delta: int
    exact_receiver_successes: int = 0

    def deal_ordering_key(self) -> Tuple:
        return (
            -self.foundation_delta,
            -self.critical_dependencies_removed,
            -self.actionable_high_value_delta,
            -self.campaign_must_burden_reduction,
            -self.exact_receiver_successes,
            -self.same_suit_mass_delta,
            -self.stable_join_delta,
            -self.mixed_boundary_reduction,
            -self.rehandling_debt_reduction,
            -self.workspace_delta,
            -self.mobility_delta,
        )


AnalysisConfigFingerprint = Tuple[int, ...]


@dataclass(frozen=True)
class Stage0AnalysisSnapshot:
    """Exact inexpensive facts attached to every generated child immediately."""

    state_key: CanonicalStateKey
    state_hash: str
    spent_cost: int
    stock_count: int
    foundation_count: int
    face_down_count: int
    empty_columns: Tuple[int, ...]
    fully_open_columns: Tuple[int, ...]
    legal_move_count: int
    stable_same_suit_joins: int
    same_suit_run_mass: int
    longest_same_suit_run: int
    mixed_suit_boundaries: int
    rehandling_debt: float
    budget: IncumbentBudget
    stage: AnalysisStage = AnalysisStage.EXACT_CHEAP_FACTS

    def ordering_key(self) -> Tuple:
        return (
            -self.foundation_count,
            self.face_down_count,
            -self.longest_same_suit_run,
            -self.same_suit_run_mass,
            -self.stable_same_suit_joins,
            -len(self.empty_columns),
            -self.legal_move_count,
            self.mixed_suit_boundaries,
            self.rehandling_debt,
            self.spent_cost,
        )


@dataclass(frozen=True)
class StrategicAnalysisFacts:
    state_key: CanonicalStateKey
    config_fingerprint: AnalysisConfigFingerprint
    economic: EconomicAnalysisResult
    measurement: StructuralMeasurement
    actionable_projects: Tuple[str, ...]
    blocked_high_value_projects: Tuple[str, ...]
    campaign_summary: Tuple[Tuple[str, str, float], ...]
    project_frontier_summary: Tuple[Tuple[str, int, float], ...]


@dataclass(frozen=True)
class ActionabilityCacheKey:
    state_key: CanonicalStateKey
    project_identity: Tuple
    tier: ActionabilityTier


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
    progress: StrategicProgressComponents
    residual: ResidualCampaignAssessment
    stage: AnalysisStage = AnalysisStage.STRATEGIC_CORE


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
    progress_delta: Optional[StructuralProgressDelta] = None
    precomputed_economic: Optional[EconomicAnalysisResult] = None
    precomputed_measurement: Optional[StructuralMeasurement] = None
    precomputed_state_key: Optional[CanonicalStateKey] = None
    precomputed_config_fingerprint: Optional[AnalysisConfigFingerprint] = None
    deal_timing_priority: int = 0
    deal_timing_decision: Optional[str] = None
    corridor_id: Optional[str] = None
    corridor_status: Optional[str] = None
    corridor_result: Optional[CampaignCorridorResult] = None
    stock_opportunity: Optional[StockOpportunityAssessment] = None


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
    analysis: Optional[StrategicAnalysisSnapshot]
    stage0: Optional[Stage0AnalysisSnapshot] = None
    foundation_checkpoint: Optional[FoundationCheckpointProfile] = None


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
    priority_components: Tuple
    incoming_progress_delta: Optional[StructuralProgressDelta]
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
    actionability_probes_attempted: int = 0
    actionability_probe_nodes: int = 0
    actionability_probe_seconds: float = 0.0
    actionability_probe_budget_exhausted: int = 0
    actionability_probes_skipped_due_quota: int = 0
    actionability_tier_escalations: int = 0
    actionability_retry_suppressions: int = 0
    direct_actionability_detections: int = 0
    cheap_actionability_rejections: int = 0
    project_realizations_attempted: int = 0
    project_realizations_succeeded: int = 0
    foundation_macro_attempts: int = 0
    foundation_macro_successes: int = 0
    corridors_generated: int = 0
    corridors_evaluated: int = 0
    corridor_lanes_retained: int = 0
    corridor_nodes: int = 0
    corridor_seconds: float = 0.0
    corridors_reaching_foundation: int = 0
    corridors_invalidated: int = 0
    corridors_suppressed_by_tt: int = 0
    corridor_campaigns: Dict[str, int] = field(default_factory=dict)
    corridor_target_epochs: Dict[int, int] = field(default_factory=dict)
    corridor_milestones: Dict[str, int] = field(default_factory=dict)
    corridor_failures: Dict[str, int] = field(default_factory=dict)
    corridor_results: List[Tuple[str, str, int, int, int]] = field(default_factory=list)
    stage0_analyses: int = 0
    stage1_analyses: int = 0
    stage2_analyses: int = 0
    lazy_children_admitted: int = 0
    optional_analyses_skipped: int = 0
    component_timings: Dict[str, ComponentTiming] = field(default_factory=dict)
    post_deal_analysis_reused: int = 0
    precomputed_analysis_mismatches: int = 0
    analysis_cache_hits: int = 0
    analysis_cache_misses: int = 0
    avoided_full_analyses: int = 0
    stock_successors_admitted: int = 0
    stock_successors_expanded: int = 0
    proof_pruned: int = 0
    heuristic_pruned: int = 0
    frontier_trimmed: int = 0
    solution_candidates: int = 0
    solution_replay_failures: int = 0
    deal_successors_generated: int = 0
    deal_preparations_retained: int = 0
    credit_expansions: Dict[int, int] = field(default_factory=dict)
    successor_kinds: Dict[str, int] = field(default_factory=dict)
    actionability_probes_by_tier: Dict[int, int] = field(default_factory=dict)
    realizations_by_tier: Dict[int, int] = field(default_factory=dict)
    expansions_by_foundation_count: Dict[int, int] = field(default_factory=dict)
    expansions_by_stock_epoch: Dict[int, int] = field(default_factory=dict)
    suppression_reasons: Dict[str, int] = field(default_factory=dict)
    decision_trace: List[DecisionTraceEntry] = field(default_factory=list)
    deal_timeline: List[Tuple[int, int, int, str]] = field(default_factory=list)
    foundation_timeline: List[Tuple[int, int, int, Tuple[str, ...]]] = field(default_factory=list)
    foundation_resource_timeline: List[
        Tuple[int, int, float, int, int, str]
    ] = field(default_factory=list)
    rework_timeline: List[Tuple[int, float, int, int, str]] = field(default_factory=list)
    deal_delta_timeline: List[Tuple[int, str, StructuralProgressDelta]] = field(default_factory=list)
    best_foundations: int = 0
    best_stock_epoch: int = 0
    lowest_face_down: int = 10**9
    foundation_checkpoints_generated: int = 0
    distinct_foundation_checkpoints_retained: int = 0
    checkpoint_diversity_suppressions: int = 0
    residual_lanes_generated: int = 0
    residual_lanes_realized: int = 0
    residual_conversion_failures: int = 0
    next_foundation_readiness_changes: int = 0
    deal_strategic_unlock_count: int = 0
    deal_escape_only_count: int = 0
    current_epoch_opportunities_lost_to_deal: int = 0
    stock_rows_consumed_between_foundations: int = 0
    paid_cost_between_foundations: int = 0
    must_burden_delta_between_foundations: int = 0
    face_down_delta_between_foundations: int = 0
    debt_delta_between_foundations: float = 0.0
    foundation_checkpoint_parents: List[Tuple[int, int, str]] = field(default_factory=list)

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
    best_progress_node: StrategicSearchNode
    lowest_g_node: StrategicSearchNode
    deepest_stock_node: StrategicSearchNode
    most_foundations_node: StrategicSearchNode
    lowest_dependency_node: StrategicSearchNode
    elapsed_seconds: float
    strategic_expansions: int
    tactical_nodes: int
    frontier_remaining: int
    maximum_credit_reached: int
    foundation_checkpoint_portfolio: FoundationCheckpointPortfolio
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


def analyze_stage0_state(
    state: SpiderState,
    *,
    spent_cost: int,
    incumbent_cost: Optional[int],
) -> Stage0AnalysisSnapshot:
    """Collect exact queue-admission facts without campaign/economic analysis."""
    stable = 0
    mass = 0
    longest = 0
    mixed = 0
    for column in state.columns:
        run = 1 if column.face_up else 0
        for lower, upper in zip(column.face_up, column.face_up[1:]):
            if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
                stable += 1
                run += 1
            else:
                longest = max(longest, run)
                if run >= 2:
                    mass += run
                run = 1
                if lower.suit != upper.suit:
                    mixed += 1
        longest = max(longest, run)
        if run >= 2:
            mass += run
    empties = tuple(i for i, column in enumerate(state.columns) if column.is_empty())
    fully_open = tuple(
        i
        for i, column in enumerate(state.columns)
        if column.face_up and not column.face_down
    )
    return Stage0AnalysisSnapshot(
        state_key=canonical_state_key(state),
        state_hash=_state_hash(state),
        spent_cost=spent_cost,
        stock_count=len(state.stock),
        foundation_count=len(state.foundations),
        face_down_count=sum(len(column.face_down) for column in state.columns),
        empty_columns=empties,
        fully_open_columns=fully_open,
        legal_move_count=len(state.enumerate_moves()),
        stable_same_suit_joins=stable,
        same_suit_run_mass=mass,
        longest_same_suit_run=longest,
        mixed_suit_boundaries=mixed,
        rehandling_debt=float(mixed),
        budget=build_incumbent_budget(
            state,
            spent_cost=spent_cost,
            incumbent_cost=incumbent_cost,
            heuristic_remaining_work=0.0,
        ),
    )


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


def analysis_config_fingerprint(
    config: AnytimeControllerConfig,
) -> AnalysisConfigFingerprint:
    """Fingerprint incumbent-independent analysis inputs and the rule profile."""
    return (
        config.campaign_source_combination_limit,
        config.corridor_config.max_source_combinations,
        config.corridor_config.max_epoch_transitions,
        int(config.enable_residual_conversion),
        config.max_foundation_checkpoints,
        *config.residual_lanes_by_credit,
        int(MW_RULES.can_deal_into_empty),
        int(MW_RULES.zero_cost_move_to_empty),
        int(MW_RULES.zero_cost_requires_emptying_column),
    )


def _campaign_must_total(measurement: StructuralMeasurement) -> int:
    return sum(value for _label, value in measurement.campaign_must_burden)


def _strategic_progress(
    state: SpiderState,
    economic: EconomicAnalysisResult,
    measurement: StructuralMeasurement,
    actionable: Sequence[str],
    *,
    spent_cost: int,
) -> StrategicProgressComponents:
    campaigns = economic.campaign_portfolio.campaigns
    removal_ready = sum(
        campaign.readiness == CampaignReadiness.READY_NOW for campaign in campaigns
    )
    credible_current = sum(
        campaign.target_removal_epoch == campaign.current_epoch
        and campaign.readiness
        in (
            CampaignReadiness.READY_NOW,
            CampaignReadiness.EXCAVATION_LED,
            CampaignReadiness.ASSEMBLY_LED,
        )
        and not campaign.blockers
        for campaign in campaigns
    )
    estimates = [campaign.estimated_campaign_cost for campaign in campaigns]
    must_by_campaign = [
        sum(need.must_excavate for need in campaign.rank_needs)
        for campaign in campaigns
    ]
    readiness_order = {
        CampaignReadiness.READY_NOW: 0,
        CampaignReadiness.ASSEMBLY_LED: 1,
        CampaignReadiness.EXCAVATION_LED: 2,
        CampaignReadiness.STOCK_GATED: 3,
        CampaignReadiness.DEFERRED: 4,
        CampaignReadiness.BLOCKED: 5,
    }
    near_removal = sum(
        campaign.target_removal_epoch is not None
        and campaign.target_removal_epoch <= campaign.current_epoch + 1
        and not campaign.blockers
        and (
            campaign.readiness == CampaignReadiness.READY_NOW
            or sum(need.must_excavate for need in campaign.rank_needs) <= 2
            or max(
                (fragment.length for fragment in campaign.current_same_suit_fragments),
                default=0,
            )
            >= 10
        )
        for campaign in campaigns
    )
    critical_classes = {
        RevealValueClass.CRITICAL_NOW,
        RevealValueClass.REQUIRED_BEFORE_NEXT_DEAL,
        RevealValueClass.HIGH_VALUE_CURRENT_EPOCH,
    }
    critical_projects = sum(
        any(value.classification in critical_classes for value in project.reveal_values)
        for project in economic.frontier.ordered_projects
    )
    return StrategicProgressComponents(
        solved=state.is_solved(),
        foundation_count=measurement.foundation_count,
        removal_ready_campaigns=removal_ready,
        credible_current_campaigns=credible_current,
        near_removal_campaigns=near_removal,
        best_campaign_readiness_rank=min(
            (readiness_order[campaign.readiness] for campaign in campaigns),
            default=99,
        ),
        minimum_campaign_must_burden=min(must_by_campaign, default=0),
        total_campaign_must_burden=_campaign_must_total(measurement),
        minimum_campaign_remaining_estimate=(min(estimates) if estimates else 0.0),
        critical_dependencies_pending=measurement.critical_dependencies_pending,
        critical_next_epoch_projects=critical_projects,
        actionable_high_value_projects=len(actionable),
        face_down_count=measurement.face_down_count,
        longest_same_suit_run=measurement.longest_same_suit_run,
        same_suit_run_mass=measurement.same_suit_run_mass,
        stable_same_suit_joins=measurement.stable_same_suit_joins,
        empty_columns=len(measurement.empty_columns),
        legal_mobility=measurement.legal_move_count,
        mixed_suit_boundaries=measurement.mixed_suit_boundaries,
        rehandling_debt=measurement.rehandling_debt,
        paid_cost=spent_cost,
    )


def _build_analysis_facts(
    state: SpiderState,
    economic: EconomicAnalysisResult,
    measurement: StructuralMeasurement,
    fingerprint: AnalysisConfigFingerprint,
) -> StrategicAnalysisFacts:
    actionable, blocked = _actionability_partition(state, economic)
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
    return StrategicAnalysisFacts(
        state_key=canonical_state_key(state),
        config_fingerprint=fingerprint,
        economic=economic,
        measurement=measurement,
        actionable_projects=actionable,
        blocked_high_value_projects=blocked,
        campaign_summary=campaigns,
        project_frontier_summary=frontier,
    )


def analyze_strategic_state(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    spent_cost: int,
    incumbent_cost: Optional[int],
    config: AnytimeControllerConfig,
    include_deal_timing: bool = True,
    analysis_cache: Optional[
        Dict[Tuple[CanonicalStateKey, AnalysisConfigFingerprint], StrategicAnalysisFacts]
    ] = None,
    telemetry: Optional[ControllerTelemetry] = None,
    precomputed_economic: Optional[EconomicAnalysisResult] = None,
    precomputed_measurement: Optional[StructuralMeasurement] = None,
    precomputed_state_key: Optional[CanonicalStateKey] = None,
    precomputed_config_fingerprint: Optional[AnalysisConfigFingerprint] = None,
    deadline: Optional[SearchDeadline] = None,
) -> StrategicAnalysisSnapshot:
    """Recompute all current-state strategic layers from the actual state."""
    state_key = canonical_state_key(state)
    fingerprint = analysis_config_fingerprint(config)
    cache_key = (state_key, fingerprint)
    facts = analysis_cache.get(cache_key) if analysis_cache is not None else None
    if facts is not None:
        if telemetry is not None:
            telemetry.analysis_cache_hits += 1
            telemetry.avoided_full_analyses += 1
    else:
        if telemetry is not None:
            telemetry.analysis_cache_misses += 1
        seed_matches = bool(
            precomputed_economic is not None
            and precomputed_measurement is not None
            and precomputed_state_key == state_key
            and precomputed_config_fingerprint == fingerprint
        )
        if seed_matches:
            economic = precomputed_economic
            measurement = precomputed_measurement
            assert economic is not None and measurement is not None
            if telemetry is not None:
                telemetry.post_deal_analysis_reused += 1
                telemetry.avoided_full_analyses += 1
        else:
            if (
                telemetry is not None
                and (precomputed_economic is not None or precomputed_measurement is not None)
            ):
                telemetry.precomputed_analysis_mismatches += 1
            if deadline is not None and not deadline.can_start(
                "economic_analysis",
                minimum_seconds=config.full_analysis_minimum_start_s,
            ):
                raise AnalysisResourceLimit(
                    "insufficient deadline remains for fresh strategic-core analysis"
                )
            if deadline is None:
                economic = analyze_economic_projects(
                    state,
                    cards=cards,
                    campaign_source_combination_limit=config.campaign_source_combination_limit,
                )
            else:
                with deadline.measure("economic_analysis"):
                    economic = analyze_economic_projects(
                        state,
                        cards=cards,
                        campaign_source_combination_limit=config.campaign_source_combination_limit,
                    )
            measurement = measure_structural_state(state, cards=cards, analysis=economic)
        facts = _build_analysis_facts(state, economic, measurement, fingerprint)
        if analysis_cache is not None:
            analysis_cache[cache_key] = facts
    economic = facts.economic
    measurement = facts.measurement
    budget = build_incumbent_budget(
        state,
        spent_cost=spent_cost,
        incumbent_cost=incumbent_cost,
        heuristic_remaining_work=economic.estimated_remaining_work,
    )
    timing: Optional[DealTimingAssessment] = None
    if include_deal_timing and state.can_deal(MW_RULES):
        may_start = deadline is None or deadline.can_start(
            "deal_timing",
            minimum_seconds=config.optional_analysis_minimum_start_s,
        )
        if may_start:
            preparations = _direct_preparation_candidates(state, economic, config)
            if deadline is None:
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
            else:
                with deadline.measure("deal_timing"):
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
    residual = analyze_residual_campaign(
        state,
        cards,
        g=spent_cost,
        analysis=economic,
        measurement=measurement,
        corridor_config=config.corridor_config,
        maximum_lanes=config.residual_lanes_by_credit[-1],
    )
    return StrategicAnalysisSnapshot(
        state_hash=_state_hash(state),
        economic=economic,
        measurement=measurement,
        budget=budget,
        actionable_projects=facts.actionable_projects,
        blocked_high_value_projects=facts.blocked_high_value_projects,
        deal_timing=timing,
        campaign_summary=facts.campaign_summary,
        project_frontier_summary=facts.project_frontier_summary,
        progress=_strategic_progress(
            state,
            economic,
            measurement,
            facts.actionable_projects,
            spent_cost=spent_cost,
        ),
        residual=residual,
        stage=(
            AnalysisStage.EXPENSIVE_OPTIONAL
            if timing is not None
            else AnalysisStage.STRATEGIC_CORE
        ),
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


def structural_progress_delta(
    before: StructuralMeasurement,
    after: StructuralMeasurement,
    *,
    actionable_before: int,
    actionable_after: int,
    exact_receiver_successes: int = 0,
) -> StructuralProgressDelta:
    """Describe consequences without treating stock consumption as progress."""
    return StructuralProgressDelta(
        foundation_delta=after.foundation_count - before.foundation_count,
        critical_dependencies_removed=(
            before.critical_dependencies_pending - after.critical_dependencies_pending
        ),
        actionable_high_value_delta=actionable_after - actionable_before,
        campaign_must_burden_reduction=(
            _campaign_must_total(before) - _campaign_must_total(after)
        ),
        same_suit_mass_delta=after.same_suit_run_mass - before.same_suit_run_mass,
        stable_join_delta=(
            after.stable_same_suit_joins - before.stable_same_suit_joins
        ),
        mixed_boundary_reduction=(
            before.mixed_suit_boundaries - after.mixed_suit_boundaries
        ),
        rehandling_debt_reduction=before.rehandling_debt - after.rehandling_debt,
        workspace_delta=len(after.empty_columns) - len(before.empty_columns),
        mobility_delta=after.legal_move_count - before.legal_move_count,
        exact_receiver_successes=exact_receiver_successes,
    )
def _successor_from_deal_arm(
    node: StrategicSearchNode,
    arm: DealCounterfactual,
    config: AnytimeControllerConfig,
) -> Optional[StrategicSuccessor]:
    if (
        arm.post_deal_state is None
        or arm.measurement is None
        or arm.economic_analysis is None
        or not arm.independent_replay_verified
    ):
        return None
    kind = (
        StrategicActionKind.DEAL_NOW
        if arm.preparation is None
        else StrategicActionKind.PREPARE_THEN_DEAL
    )
    actionability_after = (
        len(arm.actionability.high_value_actionable_after)
        if arm.actionability is not None
        else 0
    )
    delta = structural_progress_delta(
        node.analysis.measurement,
        arm.measurement,
        actionable_before=len(node.analysis.actionable_projects),
        actionable_after=actionability_after,
        exact_receiver_successes=sum(
            impact.exact_receiver_success for impact in arm.incoming_impacts
        ),
    )
    timing = node.analysis.deal_timing
    timing_priority = 0
    timing_decision: Optional[str] = None
    if timing is not None:
        decision = timing.decision
        timing_decision = decision.kind.value
        if decision.kind == DealTimingDecisionKind.DEAL_REQUIRED_FOR_ACTIONABILITY:
            timing_priority = -3 if arm.preparation is None else -2
        elif decision.kind == DealTimingDecisionKind.DEAL_NOW_PREFERRED:
            timing_priority = -2 if arm.preparation is None else 0
        elif decision.kind == DealTimingDecisionKind.PREPARATION_PREFERRED:
            timing_priority = -2 if arm.label == decision.selected_candidate_id else 0
        elif decision.kind == DealTimingDecisionKind.COMPARISON_INCONCLUSIVE:
            timing_priority = -1
    before_profile = node.analysis.residual.checkpoint
    after_profile = build_foundation_checkpoint_profile(
        arm.post_deal_state,
        g=node.g + arm.total_added_cost,
        analysis=arm.economic_analysis,
        measurement=arm.measurement,
    )
    opportunity = assess_stock_opportunity(
        before_profile,
        after_profile,
        impacts=arm.incoming_impacts,
        preparation_paid_cost=arm.preparation_cost,
        preparation_repaid=bool(
            arm.preparation is not None
            and timing is not None
            and timing.decision.kind == DealTimingDecisionKind.PREPARATION_PREFERRED
            and timing.decision.selected_candidate_id == arm.label
        ),
    )
    if opportunity.purpose == DealPurpose.STRATEGIC_UNLOCK:
        timing_priority = min(timing_priority, -2)
    elif opportunity.purpose == DealPurpose.ESCAPE_ONLY:
        timing_priority = max(timing_priority, 2)
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
            f"deal_structural_delta={delta}",
            "stock epoch is excluded from strategic progress priority",
            f"deal_purpose={opportunity.purpose.value}",
            f"deal_gain={opportunity.rationale}",
        ),
        source_project_id=(arm.preparation.candidate_id if arm.preparation else None),
        progress_delta=delta,
        precomputed_economic=arm.economic_analysis,
        precomputed_measurement=arm.measurement,
        precomputed_state_key=canonical_state_key(arm.post_deal_state),
        precomputed_config_fingerprint=analysis_config_fingerprint(config),
        deal_timing_priority=timing_priority,
        deal_timing_decision=timing_decision,
        stock_opportunity=opportunity,
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
        "residual_conversion",
        "campaign_corridor",
        "permanent_structure",
        "campaign",
        "workspace_excavation",
        "deal_timing",
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


def actionability_tier_for_credit(
    credit: StrategicCreditLevel,
) -> Optional[ActionabilityTier]:
    if credit == StrategicCreditLevel.CLEAN:
        return None
    if credit == StrategicCreditLevel.POSITIVE_INVESTMENT:
        return ActionabilityTier.SHALLOW
    if credit == StrategicCreditLevel.SPECULATIVE:
        return ActionabilityTier.MODEST
    return ActionabilityTier.BROAD


def normalized_actionability_resource(
    config: AnytimeControllerConfig,
    tier: ActionabilityTier,
) -> EconomicProjectResourceConfig:
    spec = config.actionability_tiers[int(tier)]
    return EconomicProjectResourceConfig(
        added_cost_bounds=(spec.max_added_cost,),
        max_nodes_per_bound=spec.max_nodes,
        time_limit_s_per_bound=spec.time_limit_s,
        allow_foundation_increase=True,
    )


def _project_probe_identity(project: EconomicProject, predicate) -> Tuple:
    return (
        project.project_id,
        predicate.kind.value,
        predicate.target_column,
        predicate.max_face_down,
        predicate.min_empty_count,
        predicate.suit,
        predicate.high_rank,
        predicate.low_rank,
        predicate.expected_placement.value if predicate.expected_placement else None,
        predicate.structural_return_required,
    )


def _project_probe_schedule_key(
    project: EconomicProject,
    *,
    current_epoch: int,
) -> Tuple:
    critical_classes = {
        RevealValueClass.CRITICAL_NOW,
        RevealValueClass.REQUIRED_BEFORE_NEXT_DEAL,
        RevealValueClass.HIGH_VALUE_CURRENT_EPOCH,
    }
    critical = sum(
        value.classification in critical_classes for value in project.reveal_values
    )
    shallowest = min(
        (value.reveal_depth for value in project.reveal_values),
        default=10**6,
    )
    substitutable = sum(
        value.substitute_available or bool(value.stock_copy_epochs)
        for value in project.reveal_values
    )
    campaign_relevant = project.kind in (
        EconomicProjectKind.FOUNDATION_CAMPAIGN_STEP,
        EconomicProjectKind.EXCAVATE_CARD,
        EconomicProjectKind.EXCAVATE_COLUMN_PREFIX,
        EconomicProjectKind.PREPARE_STOCK_RECEIVER,
        EconomicProjectKind.CREATE_WORKSPACE,
        EconomicProjectKind.RECOVER_WORKSPACE,
    )
    return (
        project.earliest_useful_epoch > current_epoch,
        -critical,
        shallowest,
        not project.debt.exit_route_bounded,
        not campaign_relevant,
        substitutable,
        int(project.assessment.frontier_tier),
        -project.assessment.net_economic_value,
        project.project_id,
    )


def _foundation_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    started: float,
) -> List[StrategicSuccessor]:
    if not config.enable_campaign_edges:
        return []
    configured_campaign_limit = _campaign_limit(node.credit_level, config)
    campaign_limit = configured_campaign_limit
    if node.credit_level >= StrategicCreditLevel.POSITIVE_INVESTMENT:
        campaign_limit = max(1, campaign_limit)
    protected_removals = tuple(
        campaign
        for campaign in node.analysis.economic.campaign_portfolio.campaigns
        if (
            config.enable_removal_edges
            and campaign.target_removal_epoch is not None
            and campaign.target_removal_epoch <= campaign.current_epoch + 1
            and campaign.readiness != CampaignReadiness.BLOCKED
            and not campaign.blockers
        )
    )
    if protected_removals:
        campaign_limit = max(1, campaign_limit)
    if campaign_limit <= 0:
        return []
    campaigns = (
        protected_removals[:1]
        if configured_campaign_limit == 0
        and node.credit_level == StrategicCreditLevel.CLEAN
        else node.analysis.economic.campaign_portfolio.campaigns[:campaign_limit]
    )
    successors: List[StrategicSuccessor] = []
    for campaign in campaigns:
        if (
            telemetry.tactical_nodes >= config.max_tactical_nodes
            or _remaining_controller_time(started, config) <= 0
        ):
            break
        remaining_nodes = max(1, config.max_tactical_nodes - telemetry.tactical_nodes)
        removal_eligible = bool(
            config.enable_removal_edges
            and campaign.target_removal_epoch is not None
            and campaign.target_removal_epoch <= campaign.current_epoch + 1
            and campaign.readiness != CampaignReadiness.BLOCKED
            and not campaign.blockers
        )
        added = False
        if removal_eligible:
            telemetry.foundation_macro_attempts += 1
            removal = realize_campaign_to_removal_epoch(
                node.state,
                campaign,
                cards,
                max_added_cost=config.campaign_max_added_cost,
                max_nodes=min(config.campaign_max_nodes, remaining_nodes),
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
                if removal.status == CampaignRemovalStatus.FOUNDATION_REMOVED:
                    telemetry.foundation_macro_successes += 1
                successors.append(
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
                        (
                            removal.stop_reason,
                            "protected generic foundation macro opportunity",
                            "bounded removal miss is not impossibility",
                        ),
                        campaign.label,
                    )
                )
                added = True
        if (
            added
            or telemetry.tactical_nodes >= config.max_tactical_nodes
            or (
                node.credit_level == StrategicCreditLevel.CLEAN
                and configured_campaign_limit == 0
            )
        ):
            continue
        telemetry.foundation_macro_attempts += 1
        result = realize_campaign_to_next_epoch(
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
        )
        telemetry.tactical_nodes += result.nodes_expanded
        if (
            result.status in (CampaignRealizationStatus.FOUND, CampaignRealizationStatus.PARTIAL)
            and result.independent_replay_verified
            and result.actions
            and result.corrected_added_cost is not None
        ):
            successors.append(
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
                    (
                        result.stop_reason,
                        "protected generic campaign opportunity",
                        "campaign is reanalysed after this bounded edge",
                    ),
                    campaign.label,
                )
            )
    return successors


def _campaign_corridor_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    deadline: SearchDeadline,
) -> List[StrategicSuccessor]:
    """Give credible multi-epoch campaigns a protected bounded opportunity."""
    if not config.enable_campaign_corridors:
        return []
    assert node.analysis is not None
    lane_limit = config.corridor_lanes_by_credit[int(node.credit_level)]
    is_residual = bool(
        config.enable_residual_conversion and len(node.state.foundations) > 0
    )
    if is_residual:
        lane_limit = max(
            lane_limit,
            config.residual_lanes_by_credit[int(node.credit_level)],
        )
    if lane_limit <= 0:
        return []
    remaining_nodes = config.max_tactical_nodes - telemetry.tactical_nodes
    if remaining_nodes <= 0:
        return []
    corridor_config = replace(
        config.corridor_config,
        max_lanes=min(lane_limit, config.corridor_config.max_lanes),
        max_nodes=min(config.corridor_config.max_nodes, remaining_nodes),
        time_limit_s=min(
            config.corridor_config.time_limit_s,
            max(0.01, deadline.remaining_wall_time),
        ),
    )
    lanes = generate_campaign_corridor_lanes(
        node.state,
        cards,
        config=corridor_config,
        portfolio=node.analysis.economic.campaign_portfolio,
    )
    telemetry.corridors_generated += len(lanes)
    if is_residual:
        telemetry.residual_lanes_generated += len(lanes)
    successors: List[StrategicSuccessor] = []
    for lane in lanes[:lane_limit]:
        if (
            telemetry.tactical_nodes >= config.max_tactical_nodes
            or not deadline.checkpoint()
        ):
            break
        identity = lane.corridor.identity
        label = identity.label
        telemetry.corridors_evaluated += 1
        telemetry.corridor_campaigns[label] = telemetry.corridor_campaigns.get(label, 0) + 1
        telemetry.corridor_target_epochs[identity.target_epoch] = (
            telemetry.corridor_target_epochs.get(identity.target_epoch, 0) + 1
        )
        campaign = node.analysis.economic.campaign_portfolio.campaign_for(
            identity.suit, identity.copy_index
        )
        result = realize_campaign_corridor(
            node.state,
            campaign,
            cards,
            config=replace(
                corridor_config,
                max_nodes=min(
                    corridor_config.max_nodes,
                    max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
                ),
            ),
            deadline=deadline,
        )
        telemetry.tactical_nodes += result.nodes_expanded
        telemetry.corridor_nodes += result.nodes_expanded
        telemetry.corridor_seconds += result.elapsed_seconds
        for step in result.steps:
            for milestone in step.milestones_reached:
                telemetry.corridor_milestones[milestone] = (
                    telemetry.corridor_milestones.get(milestone, 0) + 1
                )
        if result.status == CampaignCorridorStatus.COMPLETED:
            telemetry.corridors_reaching_foundation += 1
        elif result.status == CampaignCorridorStatus.INVALIDATED:
            telemetry.corridors_invalidated += 1
        if result.status not in (
            CampaignCorridorStatus.COMPLETED,
            CampaignCorridorStatus.CONTINUE,
            CampaignCorridorStatus.REPLAN_WITH_SAME_CAMPAIGN,
            CampaignCorridorStatus.WAIT_FOR_DEAL,
            CampaignCorridorStatus.SWITCH_SOURCE_COPY,
            CampaignCorridorStatus.BLOCKED_WITHIN_BOUND,
        ):
            if is_residual:
                telemetry.residual_conversion_failures += 1
            telemetry.corridor_failures[result.status.value] = (
                telemetry.corridor_failures.get(result.status.value, 0) + 1
            )
        telemetry.corridor_results.append(
            (
                label,
                result.status.value,
                result.corrected_added_cost or -1,
                result.deals_applied,
                result.foundation_count_after - result.foundation_count_before,
            )
        )
        if (
            not result.independent_replay_verified
            or not result.actions
            or result.corrected_added_cost is None
        ):
            continue
        lifecycle_rationale = tuple(
            f"{item.placement_class.value}: immediate={item.immediate_cost}; "
            f"joins+={item.same_suit_joins_created}; joins-={item.same_suit_joins_broken}; "
            f"mixed+={item.mixed_suit_boundaries_created}; mixed-={item.mixed_suit_boundaries_removed}; "
            f"exit={item.future_exit_route}; rehandling={item.estimated_rehandling_cost}; "
            f"override={item.compensating_benefit.override_reason if item.compensating_benefit else 'none'}"
            for step in result.steps
            for item in step.lifecycle
        )
        successors.append(
            StrategicSuccessor(
                StrategicActionKind.CAMPAIGN_CORRIDOR,
                "residual_conversion" if is_residual else "campaign_corridor",
                (
                    f"residual next-foundation corridor {label}"
                    if is_residual
                    else f"multi-epoch corridor {label}"
                ),
                result.actions,
                result.corrected_added_cost,
                result.end_state.clone(),
                node.credit_level,
                int(round(lane.corridor.estimated_paid_expenditure)),
                result.corrected_added_cost,
                result.nodes_expanded,
                True,
                False,
                (
                    result.stop_reason,
                    "campaign identity derived from the current portfolio",
                    "whole campaign portfolio revalidated after every corridor step",
                    "corridor failure has no proof authority",
                    f"target_foundations={len(node.state.foundations) + 1}",
                )
                + lifecycle_rationale,
                source_project_id=label,
                corridor_id=lane.lane_id,
                corridor_status=result.status.value,
                corridor_result=result,
            )
        )
        telemetry.corridor_lanes_retained += 1
        if is_residual:
            telemetry.residual_lanes_realized += 1
        # A completed protected lane already establishes the dominant bounded
        # milestone; retain other strategic families instead of spending the
        # entire expansion on additional campaign suits.
        if result.status == CampaignCorridorStatus.COMPLETED:
            break
    return successors


def generate_strategic_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    incumbent_cost: Optional[int],
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    actionability_cache: Dict[ActionabilityCacheKey, ProjectActionability],
    started: float,
    analysis_cache: Optional[
        Dict[Tuple[CanonicalStateKey, AnalysisConfigFingerprint], StrategicAnalysisFacts]
    ] = None,
    deadline: Optional[SearchDeadline] = None,
) -> Tuple[StrategicSuccessor, ...]:
    """Generate a replay-verified portfolio in an explicit resource order.

    Direct work, protected foundation work, and Deal admission happen before
    any uncertain-project probe.  Probe resources are fixed by normalized
    tier and are accounted separately from tactical realization resources.
    """
    raw: List[StrategicSuccessor] = []
    analysis = node.analysis
    if analysis is None:
        raise ValueError("a node must receive fresh Stage-1 analysis before expansion")
    shared_deadline = deadline or SearchDeadline.from_seconds(
        max(0.01, _remaining_controller_time(started, config))
    )
    allowed = set(allowed_frontier_tiers(node.credit_level))

    # 1. Obvious legal economic work never pays for an actionability search.
    direct_per_tier: Dict[EconomicFrontierTier, int] = {}
    uncertain: List[Tuple[Tuple, EconomicProject, object]] = []
    current_epoch = 5 - analysis.measurement.stock_count // 10
    for project in analysis.economic.frontier.ordered_projects:
        frontier_tier = project.assessment.frontier_tier
        if frontier_tier not in allowed:
            continue
        if project.action is not None and node.state.can_move(*project.action):
            telemetry.direct_actionability_detections += 1
            if direct_per_tier.get(frontier_tier, 0) >= config.max_direct_projects_per_tier:
                continue
            successor = _apply_direct_project(node, project)
            if successor is not None:
                raw.append(successor)
                direct_per_tier[frontier_tier] = direct_per_tier.get(frontier_tier, 0) + 1
            continue
        if node.credit_level < StrategicCreditLevel.POSITIVE_INVESTMENT:
            continue
        predicate, _reason = project_predicate(node.state, project)
        if predicate is None:
            telemetry.cheap_actionability_rejections += 1
            continue
        if predicate.is_satisfied(node.state):
            # The economic fact is already true; it informs analysis but does
            # not create a zero-action strategic edge.
            telemetry.direct_actionability_detections += 1
            continue
        uncertain.append(
            (
                _project_probe_schedule_key(project, current_epoch=current_epoch),
                project,
                predicate,
            )
        )

    # 2. Foundation-oriented work receives a protected bounded opportunity.
    raw.extend(
        _foundation_successors(
            node,
            cards,
            config=config,
            telemetry=telemetry,
            started=started,
        )
    )

    # 3. The multi-epoch hypothesis is protected before generic Deal/raw
    # families.  The campaign suit/copy comes only from the live portfolio.
    corridor_successors = _campaign_corridor_successors(
        node,
        cards,
        config=config,
        telemetry=telemetry,
        deadline=shared_deadline,
    )
    raw.extend(corridor_successors)

    # Full H1/H2 Deal timing is Stage 2.  It is skipped when a protected
    # corridor already reaches a foundation; the exact legal Deal arm remains
    # available below, so laziness never demotes Deal to an unavailable move.
    corridor_completed = any(
        successor.kind == StrategicActionKind.CAMPAIGN_CORRIDOR
        and len(successor.end_state.foundations) > len(node.state.foundations)
        for successor in corridor_successors
    )
    if (
        analysis.deal_timing is None
        and config.enable_expensive_deal_timing
        and node.state.can_deal(MW_RULES)
        and not corridor_completed
        and shared_deadline.remaining_wall_time
        >= config.optional_analysis_minimum_start_s
    ):
        try:
            optional = analyze_strategic_state(
                node.state,
                cards,
                spent_cost=node.g,
                incumbent_cost=incumbent_cost,
                config=config,
                include_deal_timing=True,
                analysis_cache=analysis_cache,
                telemetry=telemetry,
                deadline=shared_deadline,
            )
        except AnalysisResourceLimit:
            telemetry.optional_analyses_skipped += 1
        else:
            if optional.deal_timing is not None:
                analysis = optional
                telemetry.stage2_analyses += 1
    elif analysis.deal_timing is None and node.state.can_deal(MW_RULES):
        telemetry.optional_analyses_skipped += 1

    # 4. Deal is admitted as a first-class legal successor before probes.  Its
    # eventual queue position is based on exact post-deal consequences.
    deal_added = False
    if analysis.deal_timing is not None:
        for arm in order_deal_timing_arms(analysis.deal_timing):
            successor = _successor_from_deal_arm(node, arm, config)
            if successor is None:
                continue
            raw.append(successor)
            deal_added = True
            telemetry.deal_successors_generated += 1
            if successor.kind == StrategicActionKind.PREPARE_THEN_DEAL:
                telemetry.deal_preparations_retained += 1
    if node.state.can_deal(MW_RULES) and not deal_added:
        end = node.state.clone()
        cost = end.deal(MW_RULES)
        actions: Tuple[Action, ...] = (("deal",),)
        raw.append(
            StrategicSuccessor(
                StrategicActionKind.RAW_DEAL,
                "deal_timing",
                "exact legal Deal fallback",
                actions,
                cost,
                end,
                node.credit_level,
                cost,
                cost,
                0,
                _replay_edge(node.state, actions, end, cost),
                False,
                (
                    "unrestricted legal Deal remains first-class",
                    "child structural delta controls priority; epoch does not",
                ),
            )
        )
        telemetry.deal_successors_generated += 1

    # 5. Probe only the best scheduled uncertain work, with a separate fixed
    # normalized budget.  A miss is cached only for this exact tier.
    confirmed: List[Tuple[EconomicProject, ActionabilityTier]] = []
    probe_tier = actionability_tier_for_credit(node.credit_level)
    probe_count = 0
    probe_nodes = 0
    per_tier_count = 0
    probe_started = time.perf_counter()
    budget_exhaustion_recorded = False
    uncertain.sort(key=lambda item: item[0])
    for _schedule, project, predicate in uncertain:
        if probe_tier is None:
            break
        identity = _project_probe_identity(project, predicate)
        key = ActionabilityCacheKey(
            canonical_state_key(node.state), identity, probe_tier
        )
        cached = actionability_cache.get(key)
        if cached is not None:
            telemetry.actionability_cache_hits += 1
            if cached.actionable_current_epoch:
                confirmed.append((project, probe_tier))
            else:
                telemetry.inaccessible_retry_suppressed += 1
                telemetry.actionability_retry_suppressions += 1
            continue

        tier_limit = config.max_actionability_probes_per_tier[int(probe_tier)]
        tier_spec = config.actionability_tiers[int(probe_tier)]
        elapsed_probe = time.perf_counter() - probe_started
        exhausted = bool(
            probe_count >= config.max_actionability_probes_per_expansion
            or per_tier_count >= tier_limit
            or probe_nodes + tier_spec.max_nodes
            > config.max_actionability_nodes_per_expansion
            or elapsed_probe + tier_spec.time_limit_s
            > config.max_actionability_time_s_per_expansion
            or telemetry.actionability_probe_nodes + tier_spec.max_nodes
            > config.max_total_actionability_nodes
        )
        if exhausted:
            telemetry.actionability_probes_skipped_due_quota += 1
            if not budget_exhaustion_recorded:
                telemetry.actionability_probe_budget_exhausted += 1
                budget_exhaustion_recorded = True
            continue

        if not shared_deadline.can_start(
            "bounded_actionability",
            minimum_seconds=min(0.02, tier_spec.time_limit_s),
            minimum_nodes=1,
        ):
            telemetry.actionability_probes_skipped_due_quota += 1
            telemetry.optional_analyses_skipped += 1
            continue

        narrower_miss = False
        for narrower in ActionabilityTier:
            if int(narrower) >= int(probe_tier):
                break
            narrower_result = actionability_cache.get(
                ActionabilityCacheKey(
                    canonical_state_key(node.state), identity, narrower
                )
            )
            if narrower_result is not None and not narrower_result.actionable_current_epoch:
                narrower_miss = True
                break
        if narrower_miss:
            telemetry.actionability_tier_escalations += 1

        resource = normalized_actionability_resource(config, probe_tier)
        resource = replace(
            resource,
            time_limit_s_per_bound=max(
                0.01,
                min(
                    resource.time_limit_s_per_bound,
                    shared_deadline.time_slice(
                        "bounded_actionability",
                        resource.time_limit_s_per_bound,
                    ),
                ),
            ),
        )
        telemetry.actionability_cache_misses += 1
        telemetry.actionability_probes_attempted += 1
        telemetry.actionability_probes_by_tier[int(probe_tier)] = (
            telemetry.actionability_probes_by_tier.get(int(probe_tier), 0) + 1
        )
        call_started = time.perf_counter()
        with shared_deadline.measure("bounded_actionability"):
            actionability = probe_project_actionability(
                node.state,
                project,
                config=resource,
            )
        call_elapsed = time.perf_counter() - call_started
        actionability_cache[key] = actionability
        probe_count += 1
        per_tier_count += 1
        probe_nodes += actionability.nodes_expanded
        telemetry.actionability_probe_nodes += actionability.nodes_expanded
        telemetry.actionability_probe_seconds += call_elapsed
        if actionability.actionable_current_epoch:
            confirmed.append((project, probe_tier))

    # 6. Realization is separately bounded and attempted only for confirmed
    # actionable work.  An attempt consumes a realization slot even on miss.
    bounded_used = 0
    for project, confirmed_tier in confirmed:
        if bounded_used >= config.max_bounded_projects_per_expansion:
            break
        if (
            telemetry.tactical_nodes >= config.max_tactical_nodes
            or not shared_deadline.checkpoint()
        ):
            break
        bounded_used += 1
        telemetry.project_realizations_attempted += 1
        telemetry.realizations_by_tier[int(confirmed_tier)] = (
            telemetry.realizations_by_tier.get(int(confirmed_tier), 0) + 1
        )
        realization_seconds = shared_deadline.time_slice(
            "economic_project_realizer",
            config.tactical_time_limit_s_per_project,
        )
        if realization_seconds <= 0:
            telemetry.optional_analyses_skipped += 1
            break
        with shared_deadline.measure("economic_project_realizer"):
            result = realize_economic_project(
                node.state,
                project,
                cards,
                max_added_cost=config.tactical_max_cost_by_credit[int(node.credit_level)],
                max_nodes=min(
                    config.tactical_nodes_per_project,
                    max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
                ),
                time_limit_s=max(0.01, realization_seconds),
                allow_foundation_increase=True,
            )
        telemetry.tactical_nodes += result.nodes_expanded
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
        telemetry.project_realizations_succeeded += 1
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
                tuple(result.notes)
                + (
                    f"actionability_tier={confirmed_tier.name}",
                    "value, actionability, and realization were evaluated separately",
                ),
                project.project_id,
            )
        )

    # 7. Broader legal tableau fallback appears only at credit level four.
    if raw_fallback_enabled(node.credit_level):
        raw.extend(_raw_move_successors(node))

    deduplicated = deduplicate_strategic_successors(raw)
    return retain_diverse_portfolio(
        deduplicated,
        maximum=config.max_successors_per_expansion,
    )


def strategic_progress_order_key(node: StrategicSearchNode) -> Tuple:
    """Return the inspectable heuristic order; stock epoch is absent."""
    if node.analysis is None:
        if node.stage0 is None:
            raise ValueError("lazy node lacks required Stage-0 analysis")
        # Foundation count leads this exact/cheap admission order.  Stock
        # count/epoch is intentionally absent, matching the full order.
        return node.stage0.ordering_key()
    progress_key = node.analysis.progress.ordering_key()
    delta = node.incoming_edge.progress_delta if node.incoming_edge is not None else None
    deal_kinds = {
        StrategicActionKind.DEAL_NOW,
        StrategicActionKind.PREPARE_THEN_DEAL,
        StrategicActionKind.RAW_DEAL,
    }
    deal_delta_key = (
        delta.deal_ordering_key()
        if delta is not None
        and node.incoming_edge is not None
        and node.incoming_edge.kind in deal_kinds
        else (0,) * 11
    )
    timing_priority = (
        node.incoming_edge.deal_timing_priority
        if node.incoming_edge is not None
        else 0
    )
    deal_required_rank = (
        timing_priority
        if node.incoming_edge is not None
        and node.incoming_edge.deal_timing_decision
        == DealTimingDecisionKind.DEAL_REQUIRED_FOR_ACTIONABILITY.value
        else 0
    )
    # Only an explicit actionability requirement may interrupt the intrinsic
    # structural order. Other bounded timing preferences break structural
    # ties after exact consequence deltas; neither rank contains an epoch.
    return (
        progress_key[:5]
        + (deal_required_rank,)
        + progress_key[5:]
        + deal_delta_key
        + (timing_priority,)
    )


def _node_priority(node: StrategicSearchNode) -> Tuple:
    return strategic_progress_order_key(node) + (
        int(node.credit_level),
        node.depth,
        node.node_id,
    )


def _better_progress(candidate: StrategicSearchNode, incumbent: StrategicSearchNode) -> bool:
    if candidate.analysis is None or incumbent.analysis is None:
        return strategic_progress_order_key(candidate) < strategic_progress_order_key(incumbent)
    return candidate.analysis.progress.ordering_key() < incumbent.analysis.progress.ordering_key()


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


def _trim_frontier_with_checkpoint_diversity(
    frontier: Sequence[Tuple[Tuple, int, StrategicSearchNode]],
    *,
    maximum: int,
    portfolio: FoundationCheckpointPortfolio,
) -> List[Tuple[Tuple, int, StrategicSearchNode]]:
    """Protect one best descendant of each retained checkpoint lineage."""
    ordered = sorted(frontier)
    protected = {profile.state_key for profile in portfolio.profiles}
    kept = []
    kept_ids = set()
    represented = set()
    for item in ordered:
        node = item[2]
        checkpoint = node.foundation_checkpoint
        if checkpoint is None or checkpoint.state_key not in protected:
            continue
        if checkpoint.state_key in represented:
            continue
        kept.append(item)
        kept_ids.add(item[1])
        represented.add(checkpoint.state_key)
        if len(kept) >= maximum:
            return kept
    for item in ordered:
        if item[1] in kept_ids:
            continue
        kept.append(item)
        if len(kept) >= maximum:
            break
    return kept


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
            priority_components=strategic_progress_order_key(node),
            incoming_progress_delta=(
                node.incoming_edge.progress_delta
                if node.incoming_edge is not None
                else None
            ),
            reason=(
                "expanded with transparent structural progress order; "
                "stock epoch excluded"
            ),
        ),
        config.max_trace_entries,
    )


def _record_transition(
    parent: StrategicSearchNode,
    successor: StrategicSuccessor,
    child: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    *,
    elapsed_seconds: float,
) -> None:
    if parent.analysis is None:
        raise ValueError("expanded parent lacks Stage-1 analysis")
    pm = parent.analysis.measurement
    cm0 = child.stage0 or analyze_stage0_state(
        child.state, spent_cost=child.g, incumbent_cost=None
    )
    if cm0.stock_count < pm.stock_count:
        _append_bounded(
            telemetry.deal_timeline,
            (
                child.g,
                5 - cm0.stock_count // 10,
                cm0.foundation_count,
                successor.label,
            ),
            config.max_timeline_entries,
        )
        if successor.progress_delta is not None:
            _append_bounded(
                telemetry.deal_delta_timeline,
                (child.g, successor.label, successor.progress_delta),
                config.max_timeline_entries,
            )
        opportunity = successor.stock_opportunity
        if opportunity is not None:
            if opportunity.purpose == DealPurpose.STRATEGIC_UNLOCK:
                telemetry.deal_strategic_unlock_count += 1
            elif opportunity.purpose == DealPurpose.ESCAPE_ONLY:
                telemetry.deal_escape_only_count += 1
            telemetry.current_epoch_opportunities_lost_to_deal += len(
                opportunity.current_epoch_projects_blocked
            )
    if cm0.foundation_count > pm.foundation_count:
        _append_bounded(
            telemetry.foundation_timeline,
            (
                child.g,
                cm0.foundation_count,
                5 - cm0.stock_count // 10,
                _foundation_suits(child.state),
            ),
            config.max_timeline_entries,
        )
        _append_bounded(
            telemetry.foundation_resource_timeline,
            (
                child.g,
                cm0.foundation_count,
                elapsed_seconds,
                telemetry.expanded,
                telemetry.tactical_nodes,
                successor.label,
            ),
            config.max_timeline_entries,
        )
    if (
        cm0.rehandling_debt != pm.rehandling_debt
        or cm0.stable_same_suit_joins != pm.stable_same_suit_joins
    ):
        _append_bounded(
            telemetry.rework_timeline,
            (
                child.g,
                cm0.rehandling_debt - pm.rehandling_debt,
                cm0.stable_same_suit_joins - pm.stable_same_suit_joins,
                cm0.mixed_suit_boundaries - pm.mixed_suit_boundaries,
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
    deadline = SearchDeadline(
        absolute_deadline=started + config.wall_clock_limit_s,
        started_at=started,
        component_max_seconds={
            "campaign_epoch_realizer": config.corridor_config.time_limit_s,
            "campaign_removal_realizer": config.corridor_config.time_limit_s,
            "campaign_current_epoch_realizer": config.corridor_config.time_limit_s,
            "bounded_actionability": max(
                spec.time_limit_s for spec in config.actionability_tiers
            ),
            "economic_project_realizer": config.tactical_time_limit_s_per_project,
        },
    )
    preflight = freeze_active_rule_profile(initial_state, cards, rules=MW_RULES)
    initial_incumbent_cost = (
        incumbent.corrected_cost if isinstance(incumbent, IncumbentRecord) else incumbent
    )
    supplied_record = incumbent if isinstance(incumbent, IncumbentRecord) else None
    telemetry = ControllerTelemetry()
    checkpoint_profiles: List[FoundationCheckpointProfile] = []
    checkpoint_portfolio = retain_foundation_checkpoint_portfolio(
        (), maximum=config.max_foundation_checkpoints
    )

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
        residual = analyze_residual_campaign(
            initial_state,
            cards,
            g=0,
            analysis=economic,
            measurement=measurement,
            corridor_config=config.corridor_config,
            maximum_lanes=config.residual_lanes_by_credit[-1],
        )
        root_analysis = StrategicAnalysisSnapshot(
            _state_hash(initial_state),
            economic,
            measurement,
            budget,
            (),
            (),
            None,
            (),
            (),
            _strategic_progress(initial_state, economic, measurement, (), spent_cost=0),
            residual,
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
            analyze_stage0_state(
                initial_state,
                spent_cost=0,
                incumbent_cost=initial_incumbent_cost,
            ),
            residual.checkpoint if initial_state.foundations else None,
        )
        if initial_state.foundations:
            checkpoint_profiles.append(residual.checkpoint)
            checkpoint_portfolio = retain_foundation_checkpoint_portfolio(
                checkpoint_profiles, maximum=config.max_foundation_checkpoints
            )
        return AnytimeSearchResult(
            status=AnytimeControllerStatus.PREFLIGHT_FAILED,
            preflight=preflight,
            initial_incumbent_cost=initial_incumbent_cost,
            first_solution=None,
            incumbent=supplied_record,
            incumbent_cost=initial_incumbent_cost,
            incumbent_progression=(),
            best_node=root,
            best_progress_node=root,
            lowest_g_node=root,
            deepest_stock_node=root,
            most_foundations_node=root,
            lowest_dependency_node=root,
            elapsed_seconds=time.perf_counter() - started,
            strategic_expansions=0,
            tactical_nodes=0,
            frontier_remaining=0,
            maximum_credit_reached=0,
            foundation_checkpoint_portfolio=checkpoint_portfolio,
            telemetry=telemetry,
            stop_reason="; ".join(preflight.failures),
        )

    current_incumbent_cost = initial_incumbent_cost
    current_incumbent = supplied_record
    first_solution: Optional[IncumbentRecord] = None
    progression: List[int] = []
    analysis_cache: Dict[
        Tuple[CanonicalStateKey, AnalysisConfigFingerprint], StrategicAnalysisFacts
    ] = {}
    root_analysis = analyze_strategic_state(
        initial_state,
        cards,
        spent_cost=0,
        incumbent_cost=current_incumbent_cost,
        config=config,
        analysis_cache=analysis_cache,
        telemetry=telemetry,
        include_deal_timing=False,
        deadline=deadline,
    )
    telemetry.reanalyses += 1
    telemetry.stage0_analyses += 1
    telemetry.stage1_analyses += 1
    root_stage0 = analyze_stage0_state(
        initial_state,
        spent_cost=0,
        incumbent_cost=current_incumbent_cost,
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
        root_stage0,
        root_analysis.residual.checkpoint if initial_state.foundations else None,
    )
    if initial_state.foundations:
        checkpoint_profiles.append(root_analysis.residual.checkpoint)
        checkpoint_portfolio = retain_foundation_checkpoint_portfolio(
            checkpoint_profiles, maximum=config.max_foundation_checkpoints
        )
        telemetry.foundation_checkpoints_generated = 1
        telemetry.distinct_foundation_checkpoints_retained = len(
            checkpoint_portfolio.profiles
        )
    best_node = root
    best_progress_node = root
    lowest_g_node = root
    deepest_stock_node = root
    most_foundations_node = root
    lowest_dependency_node = root
    tt = StrategicTranspositionTable()
    tt.admit(root.state, 0)
    frontier: List[Tuple[Tuple, int, StrategicSearchNode]] = []
    uid = 0
    heapq.heappush(frontier, (_node_priority(root), uid, root))
    expansion_credits: set[Tuple[CanonicalStateKey, int]] = set()
    actionability_cache: Dict[ActionabilityCacheKey, ProjectActionability] = {}
    maximum_credit_reached = 0
    stop_reason = "frontier exhausted"

    while frontier:
        elapsed = time.perf_counter() - started
        if not deadline.checkpoint():
            stop_reason = "wall-clock limit"
            break
        if telemetry.expanded >= config.max_strategic_expansions:
            stop_reason = "strategic expansion limit"
            break
        if telemetry.tactical_nodes >= config.max_tactical_nodes:
            stop_reason = "tactical node limit"
            break

        _priority, _sequence, node = heapq.heappop(frontier)
        if node.stage0 is None:
            node = replace(
                node,
                stage0=analyze_stage0_state(
                    node.state,
                    spent_cost=node.g,
                    incumbent_cost=current_incumbent_cost,
                ),
            )
            telemetry.stage0_analyses += 1
        if node.analysis is None:
            try:
                fresh = analyze_strategic_state(
                    node.state,
                    cards,
                    spent_cost=node.g,
                    incumbent_cost=current_incumbent_cost,
                    config=config,
                    include_deal_timing=False,
                    analysis_cache=analysis_cache,
                    telemetry=telemetry,
                    precomputed_economic=(
                        node.incoming_edge.precomputed_economic
                        if node.incoming_edge is not None
                        else None
                    ),
                    precomputed_measurement=(
                        node.incoming_edge.precomputed_measurement
                        if node.incoming_edge is not None
                        else None
                    ),
                    precomputed_state_key=(
                        node.incoming_edge.precomputed_state_key
                        if node.incoming_edge is not None
                        else None
                    ),
                    precomputed_config_fingerprint=(
                        node.incoming_edge.precomputed_config_fingerprint
                        if node.incoming_edge is not None
                        else None
                    ),
                    deadline=deadline,
                )
            except AnalysisResourceLimit:
                telemetry.optional_analyses_skipped += 1
                stop_reason = "deadline before fresh Stage-1 expansion analysis"
                break
            node = replace(node, analysis=fresh)
            telemetry.reanalyses += 1
            telemetry.stage1_analyses += 1
        assert node.analysis is not None
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
            if _better_progress(node, best_progress_node):
                best_progress_node = node
                best_node = node
            most_foundations_node = node
            continue

        telemetry.expanded += 1
        maximum_credit_reached = max(maximum_credit_reached, int(node.credit_level))
        telemetry.credit_expansions[int(node.credit_level)] = (
            telemetry.credit_expansions.get(int(node.credit_level), 0) + 1
        )
        m = node.analysis.measurement
        current_profile = node.analysis.residual.checkpoint
        previous_checkpoint = node.foundation_checkpoint
        if (
            m.foundation_count > 0
            and (
                previous_checkpoint is None
                or m.foundation_count > previous_checkpoint.foundations
            )
        ):
            checkpoint_profiles.append(current_profile)
            telemetry.foundation_checkpoints_generated += 1
            checkpoint_portfolio = retain_foundation_checkpoint_portfolio(
                checkpoint_profiles,
                maximum=config.max_foundation_checkpoints,
            )
            telemetry.distinct_foundation_checkpoints_retained = len(
                checkpoint_portfolio.profiles
            )
            telemetry.checkpoint_diversity_suppressions = (
                checkpoint_portfolio.diversity_suppressions
            )
            if previous_checkpoint is not None:
                investment = residual_investment_accounting(
                    previous_checkpoint, current_profile
                )
                telemetry.stock_rows_consumed_between_foundations += (
                    investment.stock_rows_consumed
                )
                telemetry.paid_cost_between_foundations += investment.paid_cost
                telemetry.must_burden_delta_between_foundations += (
                    investment.must_burden_removed
                )
                telemetry.face_down_delta_between_foundations += investment.reveals
                telemetry.debt_delta_between_foundations += (
                    investment.rehandling_debt_delta
                )
                before_ready = previous_checkpoint.best_readiness
                after_ready = current_profile.best_readiness
                if (
                    after_ready is not None
                    and (
                        before_ready is None
                        or after_ready.ordering_key() < before_ready.ordering_key()
                    )
                ):
                    telemetry.next_foundation_readiness_changes += 1
            _append_bounded(
                telemetry.foundation_checkpoint_parents,
                (
                    current_profile.foundations,
                    current_profile.g,
                    (
                        node.incoming_edge.label
                        if node.incoming_edge is not None
                        else "initial checkpoint"
                    ),
                ),
                config.max_timeline_entries,
            )
            node = replace(node, foundation_checkpoint=current_profile)
        stock_epoch = 5 - m.stock_count // 10
        telemetry.expansions_by_foundation_count[m.foundation_count] = (
            telemetry.expansions_by_foundation_count.get(m.foundation_count, 0) + 1
        )
        telemetry.expansions_by_stock_epoch[stock_epoch] = (
            telemetry.expansions_by_stock_epoch.get(stock_epoch, 0) + 1
        )
        if (
            node.incoming_edge is not None
            and node.incoming_edge.kind
            in (
                StrategicActionKind.DEAL_NOW,
                StrategicActionKind.PREPARE_THEN_DEAL,
                StrategicActionKind.RAW_DEAL,
            )
        ):
            telemetry.stock_successors_expanded += 1
        telemetry.best_foundations = max(telemetry.best_foundations, m.foundation_count)
        telemetry.best_stock_epoch = max(telemetry.best_stock_epoch, stock_epoch)
        telemetry.lowest_face_down = min(telemetry.lowest_face_down, m.face_down_count)
        if _better_progress(node, best_progress_node):
            best_progress_node = node
            best_node = node
        if (node.g, strategic_progress_order_key(node)) < (
            lowest_g_node.g,
            strategic_progress_order_key(lowest_g_node),
        ):
            lowest_g_node = node
        if (
            len(node.state.stock),
            node.g,
            node.node_id,
        ) < (
            len(deepest_stock_node.state.stock),
            deepest_stock_node.g,
            deepest_stock_node.node_id,
        ):
            deepest_stock_node = node
        if (
            -m.foundation_count,
            strategic_progress_order_key(node),
        ) < (
            -most_foundations_node.analysis.measurement.foundation_count,
            strategic_progress_order_key(most_foundations_node),
        ):
            most_foundations_node = node
        if (
            m.critical_dependencies_pending,
            m.face_down_count,
            strategic_progress_order_key(node),
        ) < (
            lowest_dependency_node.analysis.measurement.critical_dependencies_pending,
            lowest_dependency_node.analysis.measurement.face_down_count,
            strategic_progress_order_key(lowest_dependency_node),
        ):
            lowest_dependency_node = node

        if (
            config.target_foundation_count is not None
            and m.foundation_count >= config.target_foundation_count
        ):
            stop_reason = "target-foundation milestone"
            break

        if (
            config.stop_after_first_foundation
            and m.foundation_count > len(initial_state.foundations)
        ):
            stop_reason = "first-foundation milestone"
            break

        successors = generate_strategic_successors(
            node,
            cards,
            incumbent_cost=current_incumbent_cost,
            config=config,
            telemetry=telemetry,
            actionability_cache=actionability_cache,
            started=started,
            analysis_cache=analysis_cache,
            deadline=deadline,
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
                if successor.kind == StrategicActionKind.CAMPAIGN_CORRIDOR:
                    telemetry.corridors_suppressed_by_tt += 1
                telemetry.count_suppression("exact state reached at no lower g")
                continue
            child_stage0 = analyze_stage0_state(
                successor.end_state,
                spent_cost=ng,
                incumbent_cost=current_incumbent_cost,
            )
            telemetry.stage0_analyses += 1
            if len(successor.end_state.foundations) > len(node.state.foundations):
                telemetry.full_reanalyses_after_foundation += 1
            if len(successor.end_state.stock) < len(node.state.stock):
                telemetry.full_reanalyses_after_deal += 1
            child_successor = replace(
                successor,
                analysis=None,
            )
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
                None,
                child_stage0,
                node.foundation_checkpoint,
            )
            if child.analysis is not None:
                if child.analysis.budget.proof_prunable:
                    telemetry.proof_pruned += 1
                    telemetry.count_suppression("admissible incumbent bound")
                    continue
            heapq.heappush(frontier, (_node_priority(child), uid, child))
            telemetry.retained += 1
            telemetry.lazy_children_admitted += 1
            telemetry.successor_kinds[child_successor.kind.value] = (
                telemetry.successor_kinds.get(child_successor.kind.value, 0) + 1
            )
            if child_successor.kind in (
                StrategicActionKind.DEAL_NOW,
                StrategicActionKind.PREPARE_THEN_DEAL,
                StrategicActionKind.RAW_DEAL,
            ):
                telemetry.stock_successors_admitted += 1
            _record_transition(
                node,
                child_successor,
                child,
                telemetry,
                config,
                elapsed_seconds=time.perf_counter() - started,
            )

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
            frontier = _trim_frontier_with_checkpoint_diversity(
                frontier,
                maximum=config.max_frontier_size,
                portfolio=checkpoint_portfolio,
            )
            heapq.heapify(frontier)
            telemetry.frontier_trimmed += 1
            telemetry.heuristic_pruned += 1
            telemetry.count_suppression("bounded frontier trim; not proof")

    telemetry.tt_new = tt.new_entries
    telemetry.tt_improved = tt.improvements
    telemetry.tt_suppressed = max(telemetry.tt_suppressed, tt.suppressions)
    telemetry.component_timings = deadline.timing_snapshot()
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
        best_progress_node=best_progress_node,
        lowest_g_node=lowest_g_node,
        deepest_stock_node=deepest_stock_node,
        most_foundations_node=most_foundations_node,
        lowest_dependency_node=lowest_dependency_node,
        elapsed_seconds=elapsed,
        strategic_expansions=telemetry.expanded,
        tactical_nodes=telemetry.tactical_nodes,
        frontier_remaining=len(frontier),
        maximum_credit_reached=maximum_credit_reached,
        foundation_checkpoint_portfolio=checkpoint_portfolio,
        telemetry=telemetry,
        stop_reason=stop_reason,
    )
