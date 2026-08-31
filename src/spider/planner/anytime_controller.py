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
from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathSummary,
    CampaignDependencyGraph,
    CampaignDependencyType,
    ClosureCompletionClass,
    DependencyClosureCache,
    DependencyClosureConfig,
    DependencyClosureResult,
    DependencyClosureStatus,
    build_campaign_dependency_graph,
    build_campaign_critical_path,
    realize_campaign_dependency_closure,
)
from spider.planner.completion_cash_out import (
    CompletionCashOutDisposition,
    CompletionCashOutOpportunity,
    CompletionCashOutStatus,
    CompletionCashOutTrace,
    CompletionHarvestAssessment,
    CompletionHarvestKind,
    CompletionStructuralMetrics,
    assess_completion_harvest,
    combine_completion_harvest,
    make_completion_cash_out_opportunity,
    rank_completion_opportunities,
    reconstruct_completion_satisfactions,
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
from spider.planner.deal_purpose import (
    DealObjectiveType,
    DealPurposeContract,
    DealPurposeKind,
    DealPurposeOutcome,
    DealPurposeStatus,
    SuccessiveDealAuditEntry,
    audit_successive_deal,
    contract_requires_descendant,
    create_deal_purpose_contract,
    validate_deal_purpose_contract,
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
from spider.planner.epoch_progression import (
    CampaignEpochAvailability,
    EpochTransitionAssessment,
    EpochTransitionStatus,
    PreDealWorkDisposition,
    analyze_campaign_epoch_availability,
    assess_epoch_transition,
    classify_pre_deal_construction,
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
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment,
    MilestonePrimitiveStep,
    realize_milestone,
)
from spider.planner.milestone_actionability import (
    PostDealMilestoneObligation,
    PostDealObligationStatus,
    ResidualMilestoneTarget,
    ResidualTargetStatus,
    create_post_deal_obligation,
    derive_residual_milestone_target,
    obligation_matches_target,
    refresh_post_deal_obligation,
)
from spider.planner.pre_foundation_diversity import (
    PreFoundationGeometry,
    PreFoundationPortfolio,
    build_pre_foundation_geometry,
    retain_pre_foundation_portfolio,
)
from spider.planner.protected_conversion import (
    ProtectedConversionBudget,
    ProtectedConversionLane,
    ProtectedConversionStatus,
    TerminalAssemblyConfig,
    TerminalAssemblyStatus,
    create_protected_conversion_lane,
    evaluate_protected_conversion_lane,
    campaign_is_near_removal,
    realize_terminal_campaign_assembly,
)
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
from spider.planner.supply_consumption import (
    SupplyObligationRole,
    SupplyConsumptionResult,
    SupplyConsumptionStage,
    advance_supply_consumption_results,
    invalidate_supply_result,
    supply_result_for_contract,
)
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    EpochTransitionOpportunity,
    EpochTransitionRepresentativeStatus,
    EpochTransitionTrace,
    PreDealOpportunityClass,
    PrepareThenDealComparison,
    SchedulerDealKind,
    ScheduleDelta,
    ScheduleDeltaKind,
    ScheduleObjectiveFamily,
    ScheduleObjectiveStatus,
    ScheduledStructuralObjective,
    WholeDealBlueprint,
    WholeDealSchedule,
    WholeDealSchedulerConfig,
    build_whole_deal_blueprint,
    build_epoch_transition_trace,
    choose_scheduler_annotations,
    compare_prepare_then_deal,
    derive_schedule_delta,
    epoch_transition_objective,
    make_epoch_transition_opportunity,
    pre_deal_opportunity_for_objective,
    rebuild_whole_deal_schedule,
    scheduler_objective_effect,
)
from spider.planner.structural_construction import (
    ConstructionDisposition,
    SameSuitConstructionOpportunity,
    StructuralConstructionAnalysis,
    analyze_same_suit_construction,
)
from spider.planner.structural_investment import (
    SameCampaignContinuationCredit,
    SameCampaignContinuationStatus,
    StructuralInvestment,
    StructuralInvestmentLedger,
    StructuralInvestmentStatus,
    continuation_from_investment,
    investment_from_construction,
    investment_from_dependency_closure,
    refresh_continuation_credit,
    successor_matches_continuation,
)
from spider.planner.strategic_milestone import (
    MilestoneOutcomeKind,
    MilestonePredicateKind,
    MilestoneConversionLedger,
    MilestoneRealizationResult,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestonePortfolio,
    StrategicMilestoneStatus,
    derive_strategic_milestones,
    evaluate_milestone_progress,
    classify_milestone_outcome,
    milestone_is_substantial,
    milestone_target_identity,
)
from spider.planner.tactical_resource_allocator import (
    RemovalAllocationPolicy,
    TacticalDemand,
    TacticalDemandPortfolio,
    TacticalObjectiveKind,
    TacticalRealizerKind,
    TacticalResourceAllocator,
    TacticalResourceAllocatorConfig,
    TacticalResourceDecision,
    TacticalResourceLedger,
    TacticalResourceOutcome,
    TacticalResourceTier,
    TacticalResourceTierSpec,
    derive_tactical_demands,
)
from spider.planner.target_grant_lineage import (
    PersistedTargetFailureDiagnosis,
    TargetBoundaryTrace,
    TargetCommitmentEvidence,
    TargetGrantDecision,
    TargetGrantLineage,
    TargetGrantLineageEntry,
    decide_target_grant,
    diagnose_persisted_target_failure,
    make_boundary_trace,
    new_target_lineage_entry,
    record_target_grant,
    record_target_outcome,
    record_lineage_source_completion,
)
from spider.planner.source_completion import (
    SourceCompletionDisposition,
    SourceCompletionLedger,
    SourceCompletionLossReason,
    SourceCompletionPropagationTrace,
    SourceCompletionStage,
    SourceExpiryClassification,
    SourceRequirementSatisfactionState,
    classify_completion_loss,
    classify_source_expiry,
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
    CAMPAIGN_DEPENDENCY_CLOSURE = "CAMPAIGN_DEPENDENCY_CLOSURE"
    SAME_SUIT_CONSTRUCTION = "SAME_SUIT_CONSTRUCTION"
    MILESTONE_CONVERSION = "MILESTONE_CONVERSION"
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
    enable_deal_purpose_contracts: bool = True
    deal_contract_horizon_expansions: int = 2
    enable_protected_conversion_lanes: bool = True
    protected_conversion_budget: ProtectedConversionBudget = field(
        default_factory=ProtectedConversionBudget
    )
    enable_terminal_assembly: bool = True
    terminal_assembly_config: TerminalAssemblyConfig = field(
        default_factory=TerminalAssemblyConfig
    )
    enable_dependency_closure: bool = True
    dependency_closure_config: DependencyClosureConfig = field(
        default_factory=DependencyClosureConfig
    )
    enable_closure_candidate_audit: bool = False
    enable_pre_foundation_diversity: bool = True
    max_pre_foundation_geometries: int = 6
    enable_structural_investment: bool = True
    enable_same_campaign_continuity: bool = True
    continuation_max_further_cost: int = 14
    continuation_max_descendant_expansions: int = 2
    continuation_max_elapsed_seconds: float = 30.0
    enable_same_suit_construction: bool = True
    max_construction_successors_per_expansion: int = 2
    enable_tactical_resource_allocation: bool = False
    tactical_resource_config: TacticalResourceAllocatorConfig = field(
        default_factory=TacticalResourceAllocatorConfig
    )
    enable_strategic_milestones: bool = False
    enable_target_grant_lineage: bool = True
    max_milestones_per_state: int = 8
    milestone_max_primitive_steps: int = 4
    milestone_max_strategic_expansions: int = 3
    milestone_max_time_s_per_expansion: float = 4.0
    milestone_max_nodes_per_expansion: int = 12_000
    enable_whole_deal_scheduler: bool = False
    whole_deal_scheduler_config: WholeDealSchedulerConfig = field(
        default_factory=WholeDealSchedulerConfig
    )
    max_scheduler_objectives_in_portfolio: int = 1
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
        if not 0 <= self.max_scheduler_objectives_in_portfolio <= self.max_successors_per_expansion:
            raise ValueError("scheduler objectives must fit inside the existing successor portfolio")
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
        if self.deal_contract_horizon_expansions <= 0:
            raise ValueError("Deal contract horizon must be positive")
        if not 3 <= self.max_pre_foundation_geometries <= 6:
            raise ValueError("pre-foundation geometry limit must be in 3..6")
        if (
            self.continuation_max_further_cost <= 0
            or self.continuation_max_descendant_expansions <= 0
            or self.continuation_max_elapsed_seconds <= 0
        ):
            raise ValueError("same-campaign continuation limits must be positive")
        if self.max_construction_successors_per_expansion <= 0:
            raise ValueError("construction successor limit must be positive")
        if self.max_milestones_per_state <= 0 or self.milestone_max_primitive_steps <= 0:
            raise ValueError("milestone portfolio and step limits must be positive")
        if self.milestone_max_strategic_expansions <= 0:
            raise ValueError("milestone continuation limit must be positive")
        if not 0 < self.milestone_max_time_s_per_expansion <= self.tactical_resource_config.max_granted_seconds_per_expansion:
            raise ValueError("milestone time must fit the existing per-expansion allocator ceiling")
        if not 0 < self.milestone_max_nodes_per_expansion <= self.tactical_resource_config.max_granted_nodes_per_expansion:
            raise ValueError("milestone nodes must fit the existing per-expansion allocator ceiling")


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
    construction: Optional[StructuralConstructionAnalysis] = None
    tactical_demands: Optional[TacticalDemandPortfolio] = None
    milestone_portfolio: Optional[StrategicMilestonePortfolio] = None
    campaign_epoch_availability: Tuple[CampaignEpochAvailability, ...] = ()
    epoch_transition: Optional[EpochTransitionAssessment] = None
    dependency_graphs: Tuple[CampaignDependencyGraph, ...] = ()
    critical_paths: Tuple[CampaignCriticalPathSummary, ...] = ()


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
    deal_contracts: Tuple[DealPurposeContract, ...] = ()
    purpose_debt_penalty: int = 0
    dependency_closure_result: Optional[DependencyClosureResult] = None
    closure_attempted_before_deal: bool = False
    closure_result_before_deal: Optional[str] = None
    successive_deal_reason: Optional[str] = None
    structural_investment: Optional[StructuralInvestment] = None
    continuation_credit: Optional[SameCampaignContinuationCredit] = None
    construction_opportunity: Optional[SameSuitConstructionOpportunity] = None
    milestone_result: Optional[MilestoneRealizationResult] = None
    epoch_transition: Optional[EpochTransitionAssessment] = None
    residual_target: Optional[ResidualMilestoneTarget] = None
    post_deal_obligation: Optional[PostDealMilestoneObligation] = None
    persistent_target: Optional[StrategicMilestone] = None
    target_grant_entry: Optional[TargetGrantLineageEntry] = None
    target_boundary_trace: Optional[TargetBoundaryTrace] = None
    source_completion_traces: Tuple[SourceCompletionPropagationTrace, ...] = ()
    scheduled_objective: Optional[ScheduledStructuralObjective] = None
    scheduler_effect_rank: int = 2
    schedule_deltas: Tuple[ScheduleDelta, ...] = ()
    scheduler_pre_deal_comparison: Optional[PrepareThenDealComparison] = None
    scheduler_pre_deal_classification: Optional[PreDealOpportunityClass] = None
    scheduler_effective_deal_ready: bool = False


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
    active_deal_contracts: Tuple[DealPurposeContract, ...] = ()
    deal_contract_outcomes: Tuple[DealPurposeOutcome, ...] = ()
    protected_conversion_lane: Optional[ProtectedConversionLane] = None
    pre_foundation_geometry: Optional[PreFoundationGeometry] = None
    deal_contract_history: Tuple[DealPurposeContract, ...] = ()
    deal_outcome_history: Tuple[DealPurposeOutcome, ...] = ()
    supply_consumption_results: Tuple[SupplyConsumptionResult, ...] = ()
    dependency_closure_history: Tuple[DependencyClosureResult, ...] = ()
    successive_deal_audit_history: Tuple[SuccessiveDealAuditEntry, ...] = ()
    structural_investment_ledger: StructuralInvestmentLedger = field(
        default_factory=StructuralInvestmentLedger
    )
    continuation_credit: Optional[SameCampaignContinuationCredit] = None
    active_milestone: Optional[StrategicMilestone] = None
    milestone_ledger: MilestoneConversionLedger = field(
        default_factory=MilestoneConversionLedger
    )
    active_residual_target: Optional[ResidualMilestoneTarget] = None
    post_deal_obligations: Tuple[PostDealMilestoneObligation, ...] = ()
    target_grant_lineage: TargetGrantLineage = field(default_factory=TargetGrantLineage)
    source_completion_ledger: SourceCompletionLedger = field(
        default_factory=SourceCompletionLedger
    )
    completion_cash_out: Optional[CompletionCashOutOpportunity] = None
    completion_harvest_history: Tuple[CompletionHarvestAssessment, ...] = ()
    completion_cash_out_parent_was_deal: bool = False
    whole_deal_schedule: Optional[WholeDealSchedule] = None
    epoch_transition_opportunity: Optional[EpochTransitionOpportunity] = None


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
    deal_contracts_created: int = 0
    contracts_by_purpose: Dict[str, int] = field(default_factory=dict)
    fulfilled_contracts: int = 0
    partially_fulfilled_contracts: int = 0
    failed_contracts: int = 0
    invalidated_contracts: int = 0
    escape_reclassifications: int = 0
    pending_contract_deals: int = 0
    consecutive_deals_with_unresolved_contracts: int = 0
    protected_lanes_created: int = 0
    protected_lanes_continued: int = 0
    protected_lanes_completed: int = 0
    protected_lanes_invalidated: int = 0
    protected_lanes_expired: int = 0
    removal_relevant_milestones_reached: int = 0
    near_removal_campaigns_detected: int = 0
    terminal_realizer_attempts: int = 0
    terminal_realizer_successes: int = 0
    distinct_pre_foundation_geometries: int = 0
    first_foundation_checkpoints_discovered: int = 0
    foundation_two_checkpoint_parent: Optional[Tuple[int, int, str]] = None
    contract_timeline: List[Tuple[int, str, str, str]] = field(default_factory=list)
    protected_lane_timeline: List[Tuple[int, str, str, str]] = field(default_factory=list)
    successive_deal_audit: List[SuccessiveDealAuditEntry] = field(default_factory=list)
    supply_contracts_created: int = 0
    supply_assets_promised: int = 0
    supply_assets_delivered: int = 0
    supply_assets_available: int = 0
    supply_assets_consumed: int = 0
    supply_assets_integrated: int = 0
    supply_assets_invalidated: int = 0
    delivered_but_unconsumed_contracts: int = 0
    full_supply_fulfilments: int = 0
    dependency_graphs_built: int = 0
    dependencies_by_type: Dict[str, int] = field(default_factory=dict)
    dependency_closure_attempts: int = 0
    dependency_closure_successes: int = 0
    dependency_closure_nodes: int = 0
    dependency_closure_seconds: float = 0.0
    dependency_closure_max_seconds: float = 0.0
    dependencies_closed: int = 0
    overlays_cleared: int = 0
    supplied_assets_consumed_by_closure: int = 0
    dependency_closure_failures: Dict[str, int] = field(default_factory=dict)
    closure_attempted_before_successive_deal: int = 0
    deals_with_unresolved_supply_obligation: int = 0
    protected_lane_replans_after_closure: int = 0
    terminal_qualification_transitions: int = 0
    dependency_closure_timeline: List[
        Tuple[int, str, str, int, int, Tuple[str, ...], Tuple[str, ...]]
    ] = field(default_factory=list)
    investments_created_by_kind: Dict[str, int] = field(default_factory=dict)
    structural_investment_paid_cost: int = 0
    structural_expected_harvest: int = 0
    structural_actual_harvest: int = 0
    unharvested_investments: int = 0
    abandoned_or_superseded_investments: int = 0
    continuation_credits_created: int = 0
    continuation_descendants_admitted: int = 0
    continuation_descendants_retained: int = 0
    continuation_credits_replanned: int = 0
    continuation_credits_harvested: int = 0
    continuation_credits_invalidated: int = 0
    continuation_credits_expired: int = 0
    continuation_credits_superseded: int = 0
    critical_supply_obligations: int = 0
    supporting_supply_obligations: int = 0
    optional_supply_assets: int = 0
    critical_supply_consumed: int = 0
    critical_supply_integrated: int = 0
    coherent_full_supply_fulfilments: int = 0
    critical_paths_built: int = 0
    high_unlock_dependencies_chosen: int = 0
    receivers_created_by_closure: int = 0
    closure_successors_admitted: int = 0
    source_buried_attempts: int = 0
    source_physical_blockers: int = 0
    source_copies_considered: int = 0
    source_copy_substitutions: int = 0
    source_depth_reduced: int = 0
    sources_exposed: int = 0
    sources_consumed: int = 0
    closure_legal_candidate_audit_count: int = 0
    closure_candidates_generated: int = 0
    closure_candidates_missing_from_generator: int = 0
    closure_candidates_admitted: int = 0
    closure_candidates_rejected_by_reason: Dict[str, int] = field(default_factory=dict)
    closure_beam_retained: int = 0
    closure_beam_discarded: int = 0
    closure_target_progress_representatives: int = 0
    closure_receivers_created: int = 0
    closure_workspace_created: int = 0
    closure_workspace_used: int = 0
    closure_temporary_parks: int = 0
    closure_temporary_park_exits: int = 0
    closure_stable_runs_broken: int = 0
    closure_stable_runs_restored: int = 0
    closure_lifecycle_debt: float = 0.0
    closure_failure_diagnoses: Dict[str, int] = field(default_factory=dict)
    closure_targeted_calls: int = 0
    closure_completion_classes: Dict[str, int] = field(default_factory=dict)
    closure_dependency_completed: int = 0
    closure_source_exposed: int = 0
    closure_dependency_advanced: int = 0
    closure_resource_bound: int = 0
    closure_structural_blocker: int = 0
    closure_search_policy: int = 0
    closure_invalidated: int = 0
    closure_advanced_states_continued: int = 0
    closure_advanced_fallbacks: int = 0
    closure_advanced_persisted_across_expansions: int = 0
    closure_persisted_targets_completed: int = 0
    closure_primitives_total: int = 0
    closure_max_primitive_sequence: int = 0
    closure_receiver_blocker_exposure_chains: int = 0
    closure_workspace_blocker_exposure_chains: int = 0
    closure_park_blocker_exposure_chains: int = 0
    closure_stable_joins_restored_or_replaced: int = 0
    closure_midpoint_rehandling_debt: float = 0.0
    closure_final_rehandling_debt: float = 0.0
    closure_projected_compensation_accepted: int = 0
    closure_projected_compensation_rejected: int = 0
    same_suit_construction_opportunities: int = 0
    two_card_construction_joins: int = 0
    larger_construction_merges: int = 0
    late_removal_construction_opportunities: int = 0
    free_future_join_deferrals: int = 0
    workspace_conflict_deferrals: int = 0
    structural_investment_timeline: List[Tuple[int, str, str, int, int]] = field(
        default_factory=list
    )
    continuation_timeline: List[Tuple[int, str, str, str]] = field(
        default_factory=list
    )
    supply_scope_timeline: List[Tuple[int, str, int, int, int]] = field(
        default_factory=list
    )
    construction_timeline: List[Tuple[int, str, str, int, Optional[int]]] = field(
        default_factory=list
    )
    tactical_requests_by_objective: Dict[str, int] = field(default_factory=dict)
    tactical_grants_by_tier: Dict[str, int] = field(default_factory=dict)
    tactical_nodes_granted_by_family: Dict[str, int] = field(default_factory=dict)
    tactical_nodes_consumed_by_family: Dict[str, int] = field(default_factory=dict)
    tactical_seconds_granted_by_family: Dict[str, float] = field(default_factory=dict)
    tactical_seconds_consumed_by_family: Dict[str, float] = field(default_factory=dict)
    tactical_promotions: int = 0
    tactical_demotions: int = 0
    tactical_suspensions: int = 0
    tactical_terminal_escalations: int = 0
    tactical_zero_harvest_invocations: int = 0
    tactical_repeated_equivalent_misses: int = 0
    tactical_harvest_events_by_realizer: Dict[str, int] = field(default_factory=dict)
    tactical_dependencies_closed: int = 0
    tactical_overlays_cleared: int = 0
    tactical_receivers_created: int = 0
    tactical_intervals_assembled: int = 0
    tactical_supply_integrated: int = 0
    tactical_joins_created: int = 0
    tactical_workspace_objectives_achieved: int = 0
    tactical_concrete_deal_unlocks: int = 0
    tactical_foundations_removed: int = 0
    tactical_allocation_timeline: List[
        Tuple[int, str, str, str, int, float, str]
    ] = field(default_factory=list)
    milestones_generated_by_kind: Dict[str, int] = field(default_factory=dict)
    milestones_admitted: int = 0
    milestones_activated: int = 0
    milestone_primitive_steps: int = 0
    milestones_advanced: int = 0
    milestones_achieved: int = 0
    milestones_replanned: int = 0
    milestones_stock_blocked: int = 0
    milestones_invalidated: int = 0
    milestones_superseded: int = 0
    milestones_expired: int = 0
    milestone_bounded_misses: int = 0
    milestone_intervals_completed: int = 0
    milestone_source_chains_completed: int = 0
    milestone_supply_completed: int = 0
    milestone_workspace_lifecycles_completed: int = 0
    milestone_predeal_completed: int = 0
    milestone_terminal_qualifications: int = 0
    milestone_foundations: int = 0
    milestone_conversion_seconds: float = 0.0
    milestone_conversion_nodes: int = 0
    milestone_timeline: List[Tuple[int, str, str, str, int, int]] = field(default_factory=list)
    epoch_feasible_milestones: int = 0
    epoch_stock_blocked_milestones: int = 0
    earliest_required_future_epochs: Dict[int, int] = field(default_factory=dict)
    predeal_must_items: int = 0
    predeal_should_items: int = 0
    predeal_free_join_deferrals: int = 0
    predeal_avoided_actions: int = 0
    purposeful_deals: int = 0
    epoch_timeline: List[Tuple[int, int, str, str]] = field(default_factory=list)
    primitive_results: int = 0
    transition_checkpoints: int = 0
    substantial_structural_milestones: int = 0
    semantic_targets_created: int = 0
    semantic_targets_persisted: int = 0
    semantic_target_copy_substitutions: int = 0
    residual_targets_rebuilt: int = 0
    residual_target_completions: int = 0
    residual_target_invalidations: int = 0
    blocker_type_transitions: int = 0
    post_deal_obligations_created: int = 0
    post_deal_material_available: int = 0
    post_deal_actionable: int = 0
    post_deal_blocked: int = 0
    post_deal_structural_progress: int = 0
    post_deal_substantial_harvest: int = 0
    successive_deals_before_obligation_conversion: int = 0
    substantial_interval_completions: int = 0
    substantial_source_chain_completions: int = 0
    substantial_receiver_lifecycles: int = 0
    substantial_supply_integrations: int = 0
    substantial_workspace_lifecycles: int = 0
    substantial_terminal_qualifications: int = 0
    semantic_target_timeline: List[Tuple[int, str, str, str]] = field(default_factory=list)
    residual_target_timeline: List[Tuple[int, str, str, str]] = field(default_factory=list)
    post_deal_obligation_timeline: List[Tuple[int, str, str, str]] = field(default_factory=list)
    target_lineages_created: int = 0
    target_lineages_persisted: int = 0
    target_tier_promotions_retained: int = 0
    target_tier_resets: int = 0
    target_tier_demotions: int = 0
    target_tier_expirations: int = 0
    target_grants_before_by_tier: Dict[str, int] = field(default_factory=dict)
    target_grants_after_by_tier: Dict[str, int] = field(default_factory=dict)
    target_next_candidates_inside_grant: int = 0
    target_next_candidates_outside_grant: int = 0
    target_failure_classifications: Dict[str, int] = field(default_factory=dict)
    target_boundary_traces: List[TargetBoundaryTrace] = field(default_factory=list)
    advanced_descendants_admitted: int = 0
    advanced_descendants_trimmed: int = 0
    same_target_reserved_representatives: int = 0
    mature_targets_lost_to_lower_g: int = 0
    source_trace_completions: int = 0
    source_successors_created: int = 0
    source_controller_admitted_completions: int = 0
    source_fresh_residual_preserved: int = 0
    source_lineage_preserved: int = 0
    source_selected_path_completions: int = 0
    source_completion_consumptions: int = 0
    source_completion_integrations: int = 0
    source_residual_reopenings: int = 0
    source_copy_reassignments: int = 0
    source_completion_loss_classifications: Dict[str, int] = field(default_factory=dict)
    source_expiry_classifications: Dict[str, int] = field(default_factory=dict)
    source_requirement_expiry_classifications: Dict[str, int] = field(default_factory=dict)
    source_expiry_rows: List[Tuple[str, SourceExpiryClassification]] = field(default_factory=list)
    source_completion_by_suit: Dict[str, Dict[str, int]] = field(default_factory=dict)
    source_completion_traces: List[SourceCompletionPropagationTrace] = field(default_factory=list)
    source_completion_reanalyses: int = 0
    source_completion_propagation_seconds: float = 0.0
    source_expiry_audit_seconds: float = 0.0
    admitted_completion_states: int = 0
    completion_nonqualifying_admitted: int = 0
    completion_cash_out_qualified: int = 0
    completion_representatives_reserved: int = 0
    completion_representatives_expanded: int = 0
    completion_representatives_expired_before_expansion: int = 0
    completion_cash_out_spent: int = 0
    completion_admitted_not_selected: int = 0
    completion_exact_duplicate_suppressions: int = 0
    completion_invalidated_representatives: int = 0
    completion_representative_displaced_ordinary_slots: int = 0
    completion_selection_seconds: float = 0.0
    completion_harvest_assessments: int = 0
    completion_source_consumed: int = 0
    completion_source_integrated: int = 0
    completion_no_downstream_harvest: int = 0
    completion_ordinary_continuations: int = 0
    completion_branches_abandoned: int = 0
    completion_targets_expired: int = 0
    completion_deals_admitted_after_cash_out: int = 0
    completion_deals_chosen_after_cash_out: int = 0
    completion_terminal_paths: int = 0
    completion_harvest_by_kind: Dict[str, int] = field(default_factory=dict)
    completion_harvest_by_suit: Dict[str, Dict[str, int]] = field(default_factory=dict)
    completion_selection_traces: List[CompletionCashOutTrace] = field(default_factory=list)
    completion_harvest_rows: List[CompletionHarvestAssessment] = field(default_factory=list)
    scheduler_blueprints_built: int = 0
    scheduler_schedules_rebuilt: int = 0
    scheduler_objectives_generated: int = 0
    scheduler_objectives_actionable: int = 0
    scheduler_objectives_entered_portfolio: int = 0
    scheduler_objectives_admitted: int = 0
    scheduler_objectives_selected: int = 0
    scheduler_objectives_advanced: int = 0
    scheduler_objectives_satisfied: int = 0
    scheduler_downstream_harvests: int = 0
    scheduler_receptions_realized: int = 0
    scheduler_receptions_missed: int = 0
    scheduler_objectives_by_family: Dict[str, Dict[str, int]] = field(default_factory=dict)
    scheduler_delta_counts: Dict[str, int] = field(default_factory=dict)
    scheduler_timeline: List[Tuple[int, int, str, str]] = field(default_factory=list)
    scheduler_deal_timeline: List[Tuple[int, int, str, Tuple[str, ...]]] = field(default_factory=list)
    scheduler_blueprint_seconds: float = 0.0
    scheduler_schedule_seconds: float = 0.0
    scheduler_reception_seconds: float = 0.0
    scheduler_duplicate_assignment_seconds: float = 0.0
    scheduler_leverage_seconds: float = 0.0
    scheduler_deal_now_previews: int = 0
    scheduler_deal_now_preview_seconds: float = 0.0
    scheduler_prepare_then_deal_previews: int = 0
    scheduler_prepare_then_deal_seconds: float = 0.0
    scheduler_saturation_seconds: float = 0.0
    scheduler_saturation_counts: Dict[str, int] = field(default_factory=dict)
    scheduler_pre_deal_classifications: Dict[str, int] = field(default_factory=dict)
    scheduler_selected_pre_deal_classifications: Dict[str, int] = field(
        default_factory=dict
    )
    scheduler_deal_ready_states: int = 0
    scheduler_effective_deal_ready_states: int = 0
    scheduler_deal_ready_legal_successors: int = 0
    scheduler_deal_ready_tt_admitted: int = 0
    scheduler_transition_qualified: int = 0
    scheduler_transition_representatives_reserved: int = 0
    scheduler_transition_representatives_expanded: int = 0
    scheduler_transition_opportunities_spent: int = 0
    scheduler_transition_duplicate_reservations_suppressed: int = 0
    scheduler_transition_superseded: int = 0
    scheduler_transition_displaced_ordinary_slots: int = 0
    scheduler_transition_completion_conflicts: int = 0
    scheduler_transition_selection_seconds: float = 0.0
    scheduler_transition_harvest_counts: Dict[str, int] = field(default_factory=dict)
    scheduler_epoch_traces: List[EpochTransitionTrace] = field(default_factory=list)
    scheduler_proof_prunes: int = 0

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
    pre_foundation_portfolio: Optional[PreFoundationPortfolio] = None
    successive_deal_audit: Tuple[SuccessiveDealAuditEntry, ...] = ()
    tactical_resource_ledger: TacticalResourceLedger = field(
        default_factory=TacticalResourceLedger
    )
    milestone_conversion_ledger: MilestoneConversionLedger = field(
        default_factory=MilestoneConversionLedger
    )
    target_grant_lineage: TargetGrantLineage = field(default_factory=TargetGrantLineage)
    source_completion_ledger: SourceCompletionLedger = field(
        default_factory=SourceCompletionLedger
    )


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
        int(config.enable_strategic_milestones),
        config.max_milestones_per_state,
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
    supply_consumptions: Sequence[SupplyConsumptionResult] = (),
    continuation_objective_id: Optional[str] = None,
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
    campaigns = economic.campaign_portfolio.campaigns
    # Campaign critical-path columns identify sources as well as receivers;
    # they must not all be treated as uniquely reserved receiver geometry.
    # Explicit receiver reservations can be supplied by focused callers.
    receiver_columns: Tuple[int, ...] = ()
    construction = (
        analyze_same_suit_construction(
            state,
            campaigns=campaigns,
            critical_receiver_columns=receiver_columns,
        )
        if config.enable_same_suit_construction
        else None
    )
    critical_paths = []
    dependency_graphs = []
    campaign_suits = {}
    if config.enable_tactical_resource_allocation or config.enable_strategic_milestones:
        for campaign in campaigns[: config.tactical_resource_config.max_campaign_demands]:
            terminal_qualified = campaign_is_near_removal(
                state,
                campaign,
                config=config.terminal_assembly_config.near_removal,
            )
            graph = build_campaign_dependency_graph(
                state,
                campaign,
                supply_consumptions=supply_consumptions,
            )
            dependency_graphs.append(graph)
            critical_paths.append(
                build_campaign_critical_path(
                    graph,
                    terminal_qualified=terminal_qualified,
                )
            )
            campaign_suits[campaign.label] = campaign.suit
    tactical_demands = (
        derive_tactical_demands(
            critical_paths,
            campaign_suits=campaign_suits,
            construction=construction,
            continuation_objective_id=continuation_objective_id,
            deal_available=state.can_deal(MW_RULES),
        )
        if config.enable_tactical_resource_allocation
        else None
    )
    epoch_availability = tuple(
        analyze_campaign_epoch_availability(
            state,
            campaign.label,
            campaign.suit,
            campaign.required_ranks,
        )
        for campaign in campaigns
    ) if config.enable_strategic_milestones else ()
    availability_by_campaign = {
        item.campaign_id: item for item in epoch_availability
    }
    milestone_portfolio = (
        derive_strategic_milestones(
            state,
            campaigns,
            dependency_graphs,
            critical_paths,
            construction,
            availability_by_campaign,
            maximum=config.max_milestones_per_state,
        )
        if config.enable_strategic_milestones
        else None
    )
    predeal_items = (
        classify_pre_deal_construction(
            state,
            construction.opportunities if construction is not None else (),
            campaign_id=(
                economic.campaign_portfolio.primary.label
                if economic.campaign_portfolio.primary is not None
                else None
            ),
            milestone_id=(
                milestone_portfolio.plan.primary.milestone_id
                if milestone_portfolio is not None
                and milestone_portfolio.plan.primary is not None
                else None
            ),
        )
        if config.enable_strategic_milestones
        else ()
    )
    epoch_transition = (
        assess_epoch_transition(
            state,
            epoch_availability,
            predeal_items,
            milestone_ids=(
                tuple(item.milestone_id for item in milestone_portfolio.milestones)
                if milestone_portfolio is not None
                else ()
            ),
        )
        if config.enable_strategic_milestones
        else None
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
        construction=construction,
        tactical_demands=tactical_demands,
        milestone_portfolio=milestone_portfolio,
        campaign_epoch_availability=epoch_availability,
        epoch_transition=epoch_transition,
        dependency_graphs=tuple(dependency_graphs),
        critical_paths=tuple(critical_paths),
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


_DEAL_ACTION_KINDS = {
    StrategicActionKind.DEAL_NOW,
    StrategicActionKind.PREPARE_THEN_DEAL,
    StrategicActionKind.RAW_DEAL,
}


def _strong_deal_purpose(purpose: DealPurposeKind) -> bool:
    return purpose in (
        DealPurposeKind.STRATEGIC_UNLOCK,
        DealPurposeKind.CAMPAIGN_SUPPLY,
        DealPurposeKind.RECEIVER_GEOMETRY,
        DealPurposeKind.PREPARATION_PAYOFF,
    )


def _purpose_debt_penalty(
    node: StrategicSearchNode,
    contracts: Sequence[DealPurposeContract],
) -> int:
    if not node.active_deal_contracts:
        return 0
    return 0 if any(_strong_deal_purpose(item.purpose) for item in contracts) else 2


def _deal_target_campaign(
    before: FoundationCheckpointProfile,
    opportunity: StockOpportunityAssessment,
) -> Optional[str]:
    if opportunity.readiness_improvements:
        return opportunity.readiness_improvements[0]
    if opportunity.dependencies_supplied or opportunity.exact_receivers_satisfied:
        readiness = before.best_readiness
        return readiness.campaign_label if readiness is not None else None
    return None


def _ensure_deal_contracts(
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
    config: AnytimeControllerConfig,
) -> StrategicSuccessor:
    """Attach a contract to every Deal, including composite bounded edges."""
    deal_count = sum(action == ("deal",) for action in successor.actions)
    if not config.enable_deal_purpose_contracts or deal_count == 0:
        return successor
    if len(successor.deal_contracts) == deal_count:
        return successor
    campaign_id = None
    if successor.category in ("campaign", "campaign_corridor", "residual_conversion"):
        campaign_id = (
            successor.source_project_id.split("@", 1)[0]
            if successor.source_project_id is not None
            else None
        )
    campaign = None
    if campaign_id is not None and node.analysis is not None:
        campaign = next(
            (
                item
                for item in node.analysis.economic.campaign_portfolio.campaigns
                if item.label == campaign_id
            ),
            None,
        )
    replay = node.state.clone()
    contracts = list(successor.deal_contracts)
    for action in successor.actions:
        if action == ("deal",):
            if len(contracts) < deal_count:
                explicit = (
                    DealPurposeKind.CAMPAIGN_SUPPLY
                    if campaign_id is not None
                    else DealPurposeKind.INCONCLUSIVE
                )
                contracts.append(
                    create_deal_purpose_contract(
                        replay,
                        node.analysis.residual.checkpoint,
                        campaign_id=campaign_id,
                        campaign=campaign,
                        objective_type=(
                            DealObjectiveType.CAMPAIGN
                            if campaign_id is not None
                            else DealObjectiveType.UNRESOLVED
                        ),
                        target_objective=(
                            f"campaign {campaign_id} corridor milestone"
                            if campaign_id is not None
                            else "fresh post-Deal next-removal analysis"
                        ),
                        explicit_purpose=explicit,
                        predicted_milestone=(
                            "named campaign dependency or corridor milestone"
                            if campaign_id is not None
                            else "fresh analysis identifies a removal-relevant consequence"
                        ),
                        bounded_expected_cost=float(successor.corrected_cost),
                        created_depth=node.depth + 1,
                        horizon_expansions=config.deal_contract_horizon_expansions,
                    )
                )
            replay.deal(MW_RULES)
        else:
            replay.move(*action, rules=MW_RULES)
    return replace(
        successor,
        deal_contracts=tuple(contracts[:deal_count]),
        purpose_debt_penalty=_purpose_debt_penalty(node, contracts),
    )


def successor_pursues_protected_conversion(
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
) -> bool:
    lane = node.protected_conversion_lane
    if lane is None:
        return False
    target = lane.target_campaign
    if successor.source_project_id == target:
        return True
    if successor.corridor_id is not None and target in successor.corridor_id:
        return True
    delta = successor.progress_delta
    if delta is not None and (
        delta.foundation_delta > 0
        or delta.campaign_must_burden_reduction > 0
        or delta.exact_receiver_successes > 0
    ):
        return True
    if successor.source_project_id is not None and node.analysis is not None:
        project = next(
            (
                item
                for item in node.analysis.economic.projects
                if item.project_id == successor.source_project_id
            ),
            None,
        )
        if project is not None and target in project.campaign_dependencies:
            return True
    return False


def successor_pursues_pending_contract(
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
) -> bool:
    objectives = {
        value
        for contract in node.active_deal_contracts
        for value in (contract.campaign_id, contract.project_id, contract.target_objective)
        if value
    }
    if not objectives:
        return False
    labels = " ".join(
        value
        for value in (
            successor.label,
            successor.source_project_id,
            successor.corridor_id,
        )
        if value
    )
    if any(value in labels for value in objectives):
        return True
    delta = successor.progress_delta
    return bool(
        delta is not None
        and (
            delta.foundation_delta > 0
            or delta.campaign_must_burden_reduction > 0
            or delta.exact_receiver_successes > 0
        )
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
        strict_removal_relevance=True,
    )
    if opportunity.purpose == DealPurpose.STRATEGIC_UNLOCK:
        timing_priority = min(timing_priority, -2)
    elif opportunity.purpose == DealPurpose.ESCAPE_ONLY:
        timing_priority = max(timing_priority, 2)
    campaign_id = _deal_target_campaign(before_profile, opportunity)
    campaign = next(
        (
            item
            for item in node.analysis.economic.campaign_portfolio.campaigns
            if item.label == campaign_id
        ),
        None,
    )
    contract = create_deal_purpose_contract(
        node.state,
        before_profile,
        after_profile=after_profile,
        stock_opportunity=opportunity,
        campaign_id=campaign_id,
        campaign=campaign,
        project_id=(arm.preparation.candidate_id if arm.preparation else None),
        target_objective=(
            campaign_id
            or (arm.preparation.candidate_id if arm.preparation else None)
            or "fresh post-Deal next-removal analysis"
        ),
        preparation_repaid=bool(
            arm.preparation is not None
            and timing is not None
            and timing.decision.kind == DealTimingDecisionKind.PREPARATION_PREFERRED
            and timing.decision.selected_candidate_id == arm.label
        ),
        current_epoch_exhausted=bool(
            not before_profile.current_epoch_actionable_high_value_projects
            and not before_profile.near_removal_campaigns
        ),
        bounded_expected_cost=float(arm.total_added_cost),
        created_depth=node.depth + 1,
        horizon_expansions=config.deal_contract_horizon_expansions,
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
        deal_contracts=(contract,),
        purpose_debt_penalty=_purpose_debt_penalty(node, (contract,)),
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
        elif (
            previous.kind == StrategicActionKind.SAME_SUIT_CONSTRUCTION
            and successor.kind == StrategicActionKind.ECONOMIC_PROJECT
            and successor.corrected_cost == previous.corrected_cost
        ):
            # The mature economic-project edge remains the public action kind
            # for backwards compatibility, while the exact construction view
            # enriches it with objective identity, harvest, and its dedicated
            # portfolio category.  Only one exact-state edge is retained.
            by_key[key] = replace(
                successor,
                category="run_construction",
                source_project_id=previous.source_project_id,
                rationale=previous.rationale + successor.rationale,
                structural_investment=previous.structural_investment,
                construction_opportunity=previous.construction_opportunity,
                scheduled_objective=(
                    previous.scheduled_objective or successor.scheduled_objective
                ),
                scheduler_effect_rank=min(
                    previous.scheduler_effect_rank,
                    successor.scheduler_effect_rank,
                ),
                scheduler_pre_deal_comparison=(
                    previous.scheduler_pre_deal_comparison
                    or successor.scheduler_pre_deal_comparison
                ),
                scheduler_pre_deal_classification=(
                    previous.scheduler_pre_deal_classification
                    or successor.scheduler_pre_deal_classification
                ),
                scheduler_effective_deal_ready=(
                    previous.scheduler_effective_deal_ready
                    or successor.scheduler_effective_deal_ready
                ),
            )
        elif (
            successor.corrected_cost,
            len(successor.actions),
            0 if successor.scheduled_objective is not None else 1,
            0 if successor.milestone_result is not None else 1,
            0 if successor.structural_investment is not None else 1,
            successor.label,
        ) < (
            previous.corrected_cost,
            len(previous.actions),
            0 if previous.scheduled_objective is not None else 1,
            0 if previous.milestone_result is not None else 1,
            0 if previous.structural_investment is not None else 1,
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
        "milestone_conversion",
        "dependency_closure",
        "residual_conversion",
        "campaign_corridor",
        "permanent_structure",
        "run_construction",
        "campaign",
        "workspace_excavation",
        "milestone_epoch",
        "deal_timing",
        "rework",
        "other",
        "raw_fallback",
    )
    retained: List[StrategicSuccessor] = []
    seen: set[int] = set()
    for category in categories:
        choices = [
            (index, successor)
            for index, successor in enumerate(successors)
            if successor.category == category
        ]
        if choices:
            index, successor = min(
                choices,
                key=lambda item: (
                    0 if item[1].scheduled_objective is not None else 1,
                    item[1].scheduler_effect_rank,
                    item[0],
                ),
            )
            retained.append(successor)
            seen.add(index)
        if len(retained) >= maximum:
            return tuple(retained)
    for index, successor in enumerate(successors):
        if index in seen:
            continue
        retained.append(successor)
        if len(retained) >= maximum:
            break
    return tuple(retained)


def _scheduler_stage(
    telemetry: ControllerTelemetry,
    objective: ScheduledStructuralObjective,
    stage: str,
) -> None:
    family = telemetry.scheduler_objectives_by_family.setdefault(
        objective.family.value, {}
    )
    family[stage] = family.get(stage, 0) + 1


def _record_scheduler_rebuild(
    telemetry: ControllerTelemetry,
    schedule: WholeDealSchedule,
) -> None:
    telemetry.scheduler_schedules_rebuilt += 1
    telemetry.scheduler_schedule_seconds += schedule.performance.schedule_seconds
    telemetry.scheduler_reception_seconds += schedule.performance.reception_seconds
    telemetry.scheduler_duplicate_assignment_seconds += (
        schedule.performance.duplicate_assignment_seconds
    )
    telemetry.scheduler_leverage_seconds += schedule.performance.leverage_seconds
    telemetry.scheduler_deal_now_preview_seconds += (
        schedule.performance.deal_now_preview_seconds
    )
    telemetry.scheduler_saturation_seconds += schedule.performance.saturation_seconds
    telemetry.scheduler_deal_now_previews += int(
        schedule.deal_now_counterfactual is not None
    )


def _annotate_scheduler_successors(
    node: StrategicSearchNode,
    candidates: Sequence[StrategicSuccessor],
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
) -> Tuple[StrategicSuccessor, ...]:
    """Attach bounded schedule intent to already legal/replayed successors."""
    if (
        not config.enable_whole_deal_scheduler
        or node.whole_deal_schedule is None
        or not candidates
        or config.max_scheduler_objectives_in_portfolio == 0
    ):
        return tuple(candidates)
    if (
        node.whole_deal_schedule.saturation is not None
        and node.whole_deal_schedule.saturation.status
        == EpochSaturationStatus.DEAL_READY
    ):
        telemetry.scheduler_deal_ready_legal_successors += sum(
            any(action == ("deal",) for action in item.actions)
            for item in candidates
        )
    annotations = choose_scheduler_annotations(
        node.state,
        candidates,
        node.whole_deal_schedule,
        maximum=config.max_scheduler_objectives_in_portfolio,
    )
    annotated = list(candidates)
    accepted = 0
    for index, objective, effect_rank in annotations:
        comparison = None
        opportunity = pre_deal_opportunity_for_objective(
            node.whole_deal_schedule, objective
        )
        if (
            opportunity is not None
            and opportunity.classification
            in {
                PreDealOpportunityClass.MUST_PRE_DEAL,
                PreDealOpportunityClass.ADVANTAGE_PRE_DEAL,
            }
            and node.whole_deal_schedule.deal_now_counterfactual is not None
            and not any(action == ("deal",) for action in annotated[index].actions)
        ):
            comparison = compare_prepare_then_deal(
                node.state,
                annotated[index].end_state,
                objective,
                node.whole_deal_schedule.deal_now_counterfactual,
                candidate_actions=annotated[index].actions,
                preparation_cost=annotated[index].corrected_cost,
            )
            if comparison is not None:
                telemetry.scheduler_prepare_then_deal_previews += 1
                telemetry.scheduler_prepare_then_deal_seconds += (
                    comparison.comparison_seconds
                )
            if (
                opportunity.classification
                == PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
                and (comparison is None or not comparison.demonstrably_better)
            ):
                continue
        _rank, notes = scheduler_objective_effect(
            node.state, annotated[index].end_state, objective
        )
        annotated[index] = replace(
            annotated[index],
            scheduled_objective=objective,
            scheduler_effect_rank=effect_rank,
            rationale=annotated[index].rationale
            + objective.rationale
            + notes
            + (
                "whole-deal schedule is advisory and absent from exact identity/proof pruning",
            ),
            scheduler_pre_deal_comparison=comparison,
            scheduler_pre_deal_classification=(
                opportunity.classification if opportunity is not None else None
            ),
        )
        telemetry.scheduler_objectives_entered_portfolio += 1
        _scheduler_stage(telemetry, objective, "entered")
        accepted += 1
    saturation = node.whole_deal_schedule.saturation
    if (
        accepted == 0
        and saturation is not None
        and saturation.status == EpochSaturationStatus.PREPARATION_ADVANTAGE
    ):
        effective_saturation = replace(
            saturation,
            status=EpochSaturationStatus.DEAL_READY,
            selected_preparation=None,
            reason=(
                "no already-generated legal successor demonstrated the bounded "
                "advantage over Deal Now"
            ),
        )
        effective_schedule = replace(
            node.whole_deal_schedule,
            saturation=effective_saturation,
            deal_now_preferred=True,
        )
        transition = epoch_transition_objective(node.state, effective_schedule)
        if transition is not None:
            direct = next(
                (
                    (index, item)
                    for index, item in enumerate(annotated)
                    if item.actions == (("deal",),)
                ),
                None,
            )
            if direct is not None:
                index, successor = direct
                _rank, notes = scheduler_objective_effect(
                    node.state, successor.end_state, transition
                )
                annotated[index] = replace(
                    successor,
                    scheduled_objective=transition,
                    scheduler_effect_rank=0,
                    scheduler_effective_deal_ready=True,
                    rationale=successor.rationale
                    + transition.rationale
                    + notes
                    + (
                        "bounded advantage had no demonstrated generated realiser; "
                        "fresh Deal readiness is effective for this successor only",
                    ),
                )
                telemetry.scheduler_deal_ready_legal_successors += 1
                telemetry.scheduler_effective_deal_ready_states += 1
                telemetry.scheduler_objectives_entered_portfolio += 1
                _scheduler_stage(telemetry, transition, "entered")
    return tuple(annotated)


def retain_obligation_successors(
    node: StrategicSearchNode,
    candidates: Sequence[StrategicSuccessor],
    retained: Sequence[StrategicSuccessor],
    *,
    maximum: int,
) -> Tuple[StrategicSuccessor, ...]:
    """Reserve at most one lane per ordering-only obligation."""
    result = list(retained)
    protected_candidates = []
    if node.protected_conversion_lane is not None:
        protected_candidates.append(
            next(
                (item for item in candidates if successor_pursues_protected_conversion(node, item)),
                None,
            )
        )
    if node.active_deal_contracts:
        protected_candidates.append(
            next(
                (item for item in candidates if successor_pursues_pending_contract(node, item)),
                None,
            )
        )
    credit = node.continuation_credit
    if credit is not None and credit.is_live:
        protected_candidates.append(
            next(
                (item for item in candidates if successor_matches_continuation(item, credit)),
                None,
            )
        )
        protected_candidates.append(
            next(
                (
                    item
                    for item in candidates
                    if item.category
                    in (
                        "dependency_closure",
                        "residual_conversion",
                        "campaign_corridor",
                        "campaign",
                    )
                    and item.source_project_id is not None
                    and item.source_project_id != credit.objective_id
                ),
                None,
            )
        )
    for candidate in protected_candidates:
        if candidate is None or candidate in result:
            continue
        if len(result) < maximum:
            result.append(candidate)
        elif result:
            replace_index = next(
                (
                    index
                    for index in range(len(result) - 1, -1, -1)
                    if result[index].category in ("raw_fallback", "other", "rework")
                ),
                len(result) - 1,
            )
            result[replace_index] = candidate
    return tuple(result[:maximum])


def _remaining_controller_time(started: float, config: AnytimeControllerConfig) -> float:
    return max(0.0, config.wall_clock_limit_s - (time.perf_counter() - started))


def _resource_allocator_for_config(
    config: AnytimeControllerConfig,
) -> TacticalResourceAllocator:
    if config.enable_tactical_resource_allocation:
        return TacticalResourceAllocator(config.tactical_resource_config)
    # Compatibility mode preserves the inherited scheduler exactly.  The
    # synthetic grants are deliberately wider than every existing component;
    # each legacy component's own established cap therefore remains binding.
    legacy_cost = max(
        config.campaign_max_added_cost,
        config.corridor_config.max_added_cost,
        config.dependency_closure_config.max_added_cost,
        config.terminal_assembly_config.max_added_cost,
        max(config.tactical_max_cost_by_credit),
    )
    legacy_nodes = max(config.max_tactical_nodes, 1)
    legacy_seconds = max(config.wall_clock_limit_s, 0.01)
    legacy = TacticalResourceAllocatorConfig(
        tiers=tuple(
            TacticalResourceTierSpec(tier, legacy_cost, legacy_nodes, legacy_seconds)
            for tier in TacticalResourceTier
        ),
        repeated_misses_before_suspend=10**9,
        max_campaign_demands=4,
        max_granted_nodes_per_expansion=legacy_nodes * 64,
        max_granted_seconds_per_expansion=legacy_seconds * 64,
        reserve_nodes_for_alternate=0,
    )
    return TacticalResourceAllocator(legacy)


def _resource_demand(
    node: StrategicSearchNode,
    realizer: TacticalRealizerKind,
    *,
    campaign_id: Optional[str] = None,
    construction_opportunity_id: Optional[str] = None,
) -> TacticalDemand:
    portfolio = node.analysis.tactical_demands if node.analysis is not None else None
    if portfolio is not None:
        matches = tuple(
            item
            for item in portfolio.demands
            if item.realizer == realizer
            and (campaign_id is None or item.campaign_id == campaign_id)
            and (
                construction_opportunity_id is None
                or item.construction_opportunity_id == construction_opportunity_id
            )
        )
        if matches:
            return min(matches, key=lambda item: item.ordering_key())
    objective = {
        TacticalRealizerKind.DEPENDENCY_CLOSURE: TacticalObjectiveKind.DEPENDENCY_CLOSURE,
        TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH: TacticalObjectiveKind.DEPENDENCY_CLOSURE,
        TacticalRealizerKind.CAMPAIGN_REMOVAL: TacticalObjectiveKind.FOUNDATION_REMOVAL,
        TacticalRealizerKind.TERMINAL_ASSEMBLY: TacticalObjectiveKind.FOUNDATION_REMOVAL,
        TacticalRealizerKind.CAMPAIGN_CORRIDOR: TacticalObjectiveKind.DEPENDENCY_CLOSURE,
        TacticalRealizerKind.RUN_CONSTRUCTION: TacticalObjectiveKind.RUN_CONSTRUCTION,
        TacticalRealizerKind.DEAL_TIMING: TacticalObjectiveKind.DEAL_EVALUATION,
        TacticalRealizerKind.ECONOMIC_PROJECT: TacticalObjectiveKind.EXCAVATION,
        TacticalRealizerKind.RAW_FALLBACK: TacticalObjectiveKind.RAW_FALLBACK,
    }[realizer]
    return TacticalDemand(
        objective,
        realizer,
        "generic bounded fallback demand; no benchmark or proof authority",
        campaign_id=campaign_id,
        construction_opportunity_id=construction_opportunity_id,
        removal_policy=(
            RemovalAllocationPolicy.REMOVAL_DIAGNOSTIC_ONLY
            if realizer == TacticalRealizerKind.CAMPAIGN_REMOVAL
            else RemovalAllocationPolicy.REMOVAL_NOT_QUALIFIED
        ),
    )


def _explicit_resource_demand(
    node: StrategicSearchNode,
    realizer: TacticalRealizerKind,
    *,
    campaign_id: Optional[str] = None,
) -> Optional[TacticalDemand]:
    portfolio = node.analysis.tactical_demands if node.analysis is not None else None
    if portfolio is None:
        return None
    return portfolio.best_for(realizer, campaign_id=campaign_id)


def _target_lineage_request_context(
    node: StrategicSearchNode,
    demand: TacticalDemand,
    config: AnytimeControllerConfig,
) -> Tuple[TacticalDemand, Optional[TargetGrantLineageEntry], Optional[TargetGrantDecision]]:
    """Apply portable same-target evidence to one existing allocator request."""

    residual = node.active_residual_target
    if (
        not config.enable_target_grant_lineage
        or not config.enable_tactical_resource_allocation
        or residual is None
        or (
            demand.campaign_id is not None
            and residual.identity.campaign_id is not None
            and demand.campaign_id != residual.identity.campaign_id
        )
    ):
        return demand, None, None
    fingerprint = residual.identity.fingerprint
    entry = node.target_grant_lineage.active_for(fingerprint)
    existing_entry = entry
    blocker_kind = residual.blockers[0].value if residual.blockers else None
    if entry is None:
        entry = new_target_lineage_entry(
            fingerprint,
            canonical_state_key(node.state),
            campaign_id=residual.identity.campaign_id,
            objective_id=residual.identity.objective_id,
            dependency_id=demand.target_dependency_id,
            blocker_fingerprint=demand.critical_path_fingerprint,
            blocker_kind=blocker_kind,
            initial_tier=demand.initial_tier,
            persistence_limit=(
                node.active_milestone.max_strategic_expansions
                if node.active_milestone is not None
                else config.milestone_max_strategic_expansions
            ),
            realizer=demand.realizer.value,
        )
    decision = decide_target_grant(
        existing_entry,
        semantic_target_fingerprint=fingerprint,
        requested_initial_tier=demand.initial_tier,
        terminal_qualified=demand.terminal_qualified,
        target_valid=residual.status != ResidualTargetStatus.INVALIDATED,
        current_state_key=canonical_state_key(node.state),
        current_blocker_fingerprint=demand.critical_path_fingerprint,
        current_blocker_kind=blocker_kind,
        lifecycle_debt=entry.lifecycle_debt,
        compensation_credible=entry.evidence.compensation_credible,
    )
    return replace(demand, initial_tier=decision.requested_tier), entry, decision


def _target_lineage_after_closure(
    node: StrategicSearchNode,
    demand: TacticalDemand,
    grant,
    entry: Optional[TargetGrantLineageEntry],
    decision: Optional[TargetGrantDecision],
    result: DependencyClosureResult,
) -> Tuple[Optional[TargetGrantLineageEntry], Optional[TargetBoundaryTrace]]:
    if entry is None or decision is None:
        return None, None
    residual = node.active_residual_target
    blocker_kind = residual.blockers[0].value if residual and residual.blockers else None
    granted_entry = record_target_grant(
        entry,
        state_key=canonical_state_key(node.state),
        dependency_id=demand.target_dependency_id,
        blocker_fingerprint=demand.critical_path_fingerprint,
        blocker_kind=blocker_kind,
        requested_tier=decision.requested_tier,
        granted_tier=(grant.tier if grant is not None else None),
        decision=decision,
        realizer=demand.realizer.value,
    )
    endpoint = result.endpoint_assessment
    progress = tuple(
        dict.fromkeys(
            step.progress_evidence.kind.value
            for step in result.steps
            if step.progress_evidence is not None
            and step.progress_evidence.target_relevant
        )
    )
    lifecycle = endpoint.lifecycle if endpoint is not None else None
    evidence = TargetCommitmentEvidence(
        named_harvest=tuple(result.dependencies_closed) + progress,
        completion_class=result.completion_class.value,
        source_depth_before=(endpoint.source_depth_before if endpoint is not None else None),
        source_depth_after=(endpoint.source_depth_after if endpoint is not None else None),
        blockers_before=(endpoint.blockers_before if endpoint is not None else None),
        blockers_after=(endpoint.blockers_after if endpoint is not None else None),
        dependency_completed=bool(endpoint and endpoint.requested_dependency_completed),
        prerequisite_completed=bool(endpoint and endpoint.prerequisite_progress),
        source_exposed=bool(endpoint and endpoint.source_exposed),
        source_consumed=bool(endpoint and endpoint.source_consumed),
        substantial_progress=bool(
            endpoint
            and (
                endpoint.requested_dependency_completed
                or endpoint.source_exposed
                or endpoint.source_consumed
            )
        ),
        target_relevant=bool(
            result.actions
            and result.completion_class
            in {
                ClosureCompletionClass.DEPENDENCY_ADVANCED,
                ClosureCompletionClass.DEPENDENCY_COMPLETED,
                ClosureCompletionClass.SOURCE_EXPOSED,
            }
        ),
        nodes_consumed=result.nodes_expanded,
        seconds_consumed=result.elapsed_seconds,
        corrected_paid_cost=int(result.corrected_added_cost or 0),
        lifecycle_debt=(lifecycle.final_rehandling_debt if lifecycle is not None else 0.0),
        restore_replace_obligation=(
            lifecycle.restore_replace_obligation if lifecycle is not None else None
        ),
        compensation_credible=bool(
            lifecycle is None
            or lifecycle.restore_replace_obligation is None
            or lifecycle.projected_compensation_accepted > 0
        ),
    )
    updated = record_target_outcome(
        granted_entry,
        evidence,
        end_state_key=canonical_state_key(result.end_state),
        target_valid=bool(endpoint is None or endpoint.same_semantic_target_valid),
        completed=bool(
            len(result.end_state.foundations) > len(node.state.foundations)
            or residual is not None and residual.status == ResidualTargetStatus.COMPLETE
        ),
    )
    if result.source_completion_events:
        updated = record_lineage_source_completion(
            updated,
            result.source_completion_events,
            tuple(item.satisfaction for item in result.source_completion_events),
        )
    candidate_classes = tuple(
        item.blocker.value for item in residual.candidates
    ) if residual is not None else ()
    best_candidate = (
        residual.next_candidate.rationale
        if residual is not None and residual.next_candidate is not None
        else None
    )
    minimum_tier = None
    if (
        result.completion_class == ClosureCompletionClass.RESOURCE_BOUND
        or result.failure_diagnosis.value == "RESOURCE_BOUND"
    ) and grant is not None and grant.tier < TacticalResourceTier.COMMITTED:
        minimum_tier = TacticalResourceTier(int(grant.tier) + 1)
    preliminary = make_boundary_trace(
        updated,
        decision,
        dependency_after=result.target_dependency_id,
        blocker_after=(
            endpoint.target_kind_after.value
            if endpoint is not None and endpoint.target_kind_after is not None
            else None
        ),
        progress_before=(
            f"{entry.evidence.completion_class or 'NEW'}:"
            f"{entry.evidence.source_depth_before}->{entry.evidence.source_depth_after}"
        ),
        progress_after=(
            f"{result.completion_class.value}:"
            f"{endpoint.source_depth_before if endpoint else None}->"
            f"{endpoint.source_depth_after if endpoint else None}"
        ),
        fresh_candidate_classes=candidate_classes,
        best_next_candidate=best_candidate,
        best_candidate_minimum_tier=minimum_tier,
        granted_tier=(grant.tier if grant is not None else None),
        selected_action=(repr(result.actions[0]) if result.actions else None),
        admission_reason=result.reason,
        next_closure_result=result.completion_class.value,
        eventual_target_outcome=(
            "COMPLETED"
            if endpoint is not None and endpoint.requested_dependency_completed
            else "EXPOSED"
            if endpoint is not None and endpoint.source_exposed
            else "ADVANCED"
            if result.completion_class == ClosureCompletionClass.DEPENDENCY_ADVANCED
            else result.completion_class.value
        ),
    )
    diagnosis = None
    if not (
        endpoint is not None
        and (endpoint.requested_dependency_completed or endpoint.source_exposed)
    ):
        diagnosis = diagnose_persisted_target_failure(
            preliminary,
            same_target_attributed=bool(endpoint is None or endpoint.same_semantic_target_valid),
            candidate_turnover=bool(
                entry.current_blocker_kind
                and blocker_kind
                and entry.current_blocker_kind != blocker_kind
            ),
            lifecycle_context_lost=bool(
                entry.restore_replace_obligation
                and lifecycle is not None
                and lifecycle.restore_replace_obligation is None
                and not evidence.compensation_credible
            ),
            resource_bound=bool(
                result.completion_class == ClosureCompletionClass.RESOURCE_BOUND
                or result.failure_diagnosis.value == "RESOURCE_BOUND"
            ),
            structural_blocker=bool(
                result.completion_class == ClosureCompletionClass.STRUCTURAL_BLOCKER
                or result.failure_diagnosis.value == "STRUCTURAL_BLOCKER"
            ),
            superseded=decision.status.value == "SUPERSEDED",
            expired=decision.status.value == "EXPIRED",
        )
    return updated, replace(preliminary, failure_diagnosis=diagnosis)


def _publish_target_boundary_telemetry(
    telemetry: ControllerTelemetry,
    entry: Optional[TargetGrantLineageEntry],
    decision: Optional[TargetGrantDecision],
    trace: Optional[TargetBoundaryTrace],
    *,
    maximum: int,
) -> None:
    if entry is None or decision is None or trace is None:
        return
    telemetry.target_lineages_created += int(entry.previous_granted_tier is None)
    persisted = bool(
        trace.previous_tier is not None
        and trace.state_before_hash
        and trace.state_before_hash != trace.state_after_hash
    )
    telemetry.target_lineages_persisted += int(persisted)
    telemetry.target_tier_promotions_retained += int(decision.inherited_commitment)
    telemetry.target_tier_resets += int(decision.status.value in {"RESET", "INVALIDATED"})
    telemetry.target_tier_demotions += int(decision.status.value == "DEMOTED")
    telemetry.target_tier_expirations += int(decision.status.value == "EXPIRED")
    if decision.status.value == "EXPIRED":
        audit_started = time.perf_counter()
        expiry_id = (
            f"{entry.lineage_id}:{entry.generation}:{trace.state_after_hash}:"
            f"{len(telemetry.source_expiry_rows) + 1}"
        )
        attribution_lost = any(
            item.reopening_reason is not None
            for item in entry.source_satisfactions
        )
        classification = classify_source_expiry(
            completed_before_expiry=any(
                item.satisfied for item in entry.source_satisfactions
            ),
            made_progress=entry.evidence.has_portable_harvest,
            resource_limited=entry.evidence.has_portable_harvest,
            target_turnover=bool(
                entry.previous_blocker_kind
                and entry.current_blocker_kind
                and entry.previous_blocker_kind != entry.current_blocker_kind
                and not entry.evidence.has_portable_harvest
            ),
            attribution_lost=attribution_lost,
            lifecycle_terminated=bool(
                entry.restore_replace_obligation
                and not entry.evidence.compensation_credible
            ),
            superseded=entry.status.value == "SUPERSEDED",
        )
        telemetry.source_expiry_rows.append((expiry_id, classification))
        name = classification.value
        telemetry.source_expiry_classifications[name] = (
            telemetry.source_expiry_classifications.get(name, 0) + 1
        )
        telemetry.source_expiry_audit_seconds += time.perf_counter() - audit_started
    if trace.previous_tier is not None:
        name = trace.previous_tier.name
        telemetry.target_grants_before_by_tier[name] = (
            telemetry.target_grants_before_by_tier.get(name, 0) + 1
        )
    if trace.granted_next_tier is not None:
        name = trace.granted_next_tier.name
        telemetry.target_grants_after_by_tier[name] = (
            telemetry.target_grants_after_by_tier.get(name, 0) + 1
        )
    telemetry.target_next_candidates_inside_grant += int(trace.candidate_inside_grant is True)
    telemetry.target_next_candidates_outside_grant += int(trace.candidate_inside_grant is False)
    if trace.failure_diagnosis is not None:
        name = trace.failure_diagnosis.value
        telemetry.target_failure_classifications[name] = (
            telemetry.target_failure_classifications.get(name, 0) + 1
        )
    _append_bounded(telemetry.target_boundary_traces, trace, maximum)


def _record_tactical_transition(
    allocator: TacticalResourceAllocator,
    grant,
    node: StrategicSearchNode,
    end_state: SpiderState,
    *,
    nodes_consumed: int,
    seconds_consumed: float,
    corrected_paid_cost: int,
    legal_successor_count: int,
    campaign: Optional[FoundationCampaign] = None,
    supply_after: Optional[Sequence[SupplyConsumptionResult]] = None,
    dependencies_closed: Optional[int] = None,
    overlays_cleared: Optional[int] = None,
    receivers_created: Optional[int] = None,
    supply_consumed_or_integrated: Optional[int] = None,
    permanent_adjacencies_created: Optional[int] = None,
    intervals_assembled: Optional[int] = None,
    concrete_deal_unlocks: int = 0,
    reason: str = "",
) -> TacticalResourceOutcome:
    before = node.stage0 or analyze_stage0_state(
        node.state, spent_cost=node.g, incumbent_cost=None
    )
    after = analyze_stage0_state(
        end_state,
        spent_cost=node.g + corrected_paid_cost,
        incumbent_cost=None,
    )
    blocker_before = grant.key.critical_path_fingerprint
    blocker_after = blocker_before
    terminal_before = False
    terminal_after = False
    derived_dependencies = 0
    derived_overlays = 0
    derived_receivers = 0
    derived_intervals = 0
    if campaign is not None:
        before_graph = build_campaign_dependency_graph(
            node.state,
            campaign,
            supply_consumptions=node.supply_consumption_results,
        )
        after_graph = build_campaign_dependency_graph(
            end_state,
            campaign,
            supply_consumptions=(
                tuple(supply_after)
                if supply_after is not None
                else node.supply_consumption_results
            ),
        )
        before_ids = {
            item.dependency_id
            for item in before_graph.dependencies
            if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
        }
        after_ids = {
            item.dependency_id
            for item in after_graph.dependencies
            if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
        }
        closed_ids = before_ids - after_ids
        derived_dependencies = len(closed_ids)
        derived_overlays = sum(item.startswith("overlay:") for item in closed_ids)
        derived_receivers = sum(item.startswith("receiver:") for item in closed_ids)
        derived_intervals = sum(item.startswith("interval:") for item in closed_ids)
        terminal_before = campaign_is_near_removal(
            node.state,
            campaign,
        )
        terminal_after = campaign_is_near_removal(
            end_state,
            campaign,
        )
        after_path = build_campaign_critical_path(
            after_graph,
            terminal_qualified=terminal_after,
        )
        blocker_after = after_path.bottleneck_dependency_id
    supply_before_count = sum(
        item.consumed_count for item in node.supply_consumption_results
    )
    supply_after_count = sum(
        item.consumed_count for item in (supply_after or node.supply_consumption_results)
    )
    outcome = TacticalResourceOutcome(
        grant.request_id,
        grant.key,
        grant.tier,
        nodes_consumed,
        seconds_consumed,
        corrected_paid_cost,
        legal_successor_count,
        dependencies_closed=(
            derived_dependencies if dependencies_closed is None else dependencies_closed
        ),
        overlays_cleared=(derived_overlays if overlays_cleared is None else overlays_cleared),
        receivers_created=(
            derived_receivers if receivers_created is None else receivers_created
        ),
        supply_consumed_or_integrated=(
            max(0, supply_after_count - supply_before_count)
            if supply_consumed_or_integrated is None
            else supply_consumed_or_integrated
        ),
        permanent_adjacencies_created=(
            max(0, after.stable_same_suit_joins - before.stable_same_suit_joins)
            if permanent_adjacencies_created is None
            else permanent_adjacencies_created
        ),
        strategically_relevant_sources_exposed=(
            max(0, before.face_down_count - after.face_down_count)
            if grant.key.objective == TacticalObjectiveKind.EXCAVATION
            else 0
        ),
        workspace_created_or_recovered=max(
            0, len(after.empty_columns) - len(before.empty_columns)
        ),
        intervals_assembled=(
            derived_intervals if intervals_assembled is None else intervals_assembled
        ),
        concrete_deal_unlocks=concrete_deal_unlocks,
        terminal_qualification_before=terminal_before,
        terminal_qualification_after=terminal_after,
        foundation_removals=max(
            0, after.foundation_count - before.foundation_count
        ),
        blocker_before=blocker_before,
        blocker_after=blocker_after,
        reason=reason,
    )
    return allocator.record_outcome(outcome)


def _probe_exact_deal_unlocks(node: StrategicSearchNode) -> int:
    """Return named, exact next-row reasons for widening Deal analysis.

    The probe deliberately avoids economic reanalysis.  It reads only the
    known next row, current receivers, and already-selected campaign stock
    sources.  The raw legal Deal successor is generated independently, so a
    zero result can suspend this evaluator without suppressing Deal itself.
    """
    if len(node.state.stock) < 10:
        return 0
    row = tuple(node.state.stock[-10:])
    unlocks: set[Tuple] = set()
    for column_index, incoming in enumerate(row):
        receiver = node.state.columns[column_index].top()
        if (
            receiver is not None
            and receiver.suit == incoming.suit
            and receiver.rank == incoming.rank + 1
        ):
            unlocks.add(("stable_join", column_index, incoming.suit, incoming.rank))

    campaigns = (
        node.analysis.economic.campaign_portfolio.campaigns
        if node.analysis is not None
        else ()
    )
    for campaign in campaigns[:2]:
        next_epoch = campaign.current_epoch + 1
        for need in campaign.rank_needs:
            source = need.chosen
            if source is None or source.stock_epoch != next_epoch:
                continue
            for column_index, incoming in enumerate(row):
                if incoming != source.card:
                    continue
                if source.stock_column not in (None, column_index, column_index + 1):
                    continue
                unlocks.add(
                    ("campaign_supply", campaign.label, source.source_key, column_index)
                )

    dealt = node.state.clone()
    foundations_before = len(dealt.foundations)
    dealt.deal(MW_RULES)
    for offset in range(len(dealt.foundations) - foundations_before):
        unlocks.add(("foundation_on_deal", offset))
    return len(unlocks)


def _publish_tactical_resource_telemetry(
    telemetry: ControllerTelemetry,
    ledger: TacticalResourceLedger,
    *,
    maximum_timeline_entries: int,
) -> None:
    for request in ledger.requests:
        key = request.demand.objective.value
        telemetry.tactical_requests_by_objective[key] = (
            telemetry.tactical_requests_by_objective.get(key, 0) + 1
        )
    for index, grant in enumerate(ledger.grants):
        tier = grant.tier.name
        family = grant.key.realizer.value
        telemetry.tactical_grants_by_tier[tier] = (
            telemetry.tactical_grants_by_tier.get(tier, 0) + 1
        )
        telemetry.tactical_nodes_granted_by_family[family] = (
            telemetry.tactical_nodes_granted_by_family.get(family, 0)
            + grant.nodes_granted
        )
        telemetry.tactical_seconds_granted_by_family[family] = (
            telemetry.tactical_seconds_granted_by_family.get(family, 0.0)
            + grant.seconds_granted
        )
        _append_bounded(
            telemetry.tactical_allocation_timeline,
            (
                index,
                grant.key.objective.value,
                family,
                tier,
                grant.nodes_granted,
                grant.seconds_granted,
                grant.removal_policy.value,
            ),
            maximum_timeline_entries,
        )
    for outcome in ledger.outcomes:
        family = outcome.key.realizer.value
        telemetry.tactical_nodes_consumed_by_family[family] = (
            telemetry.tactical_nodes_consumed_by_family.get(family, 0)
            + outcome.nodes_consumed
        )
        telemetry.tactical_seconds_consumed_by_family[family] = (
            telemetry.tactical_seconds_consumed_by_family.get(family, 0.0)
            + outcome.seconds_consumed
        )
        telemetry.tactical_harvest_events_by_realizer[family] = (
            telemetry.tactical_harvest_events_by_realizer.get(family, 0)
            + outcome.named_harvest_events
        )
        telemetry.tactical_zero_harvest_invocations += int(not outcome.has_named_harvest)
        telemetry.tactical_repeated_equivalent_misses += int(
            outcome.repeated_equivalent_miss
        )
        telemetry.tactical_dependencies_closed += outcome.dependencies_closed
        telemetry.tactical_overlays_cleared += outcome.overlays_cleared
        telemetry.tactical_receivers_created += outcome.receivers_created
        telemetry.tactical_intervals_assembled += outcome.intervals_assembled
        telemetry.tactical_supply_integrated += outcome.supply_consumed_or_integrated
        telemetry.tactical_joins_created += outcome.permanent_adjacencies_created
        telemetry.tactical_workspace_objectives_achieved += (
            outcome.workspace_created_or_recovered
        )
        telemetry.tactical_concrete_deal_unlocks += outcome.concrete_deal_unlocks
        telemetry.tactical_foundations_removed += outcome.foundation_removals
        telemetry.tactical_promotions += int(
            outcome.decision == TacticalResourceDecision.PROMOTE
        )
        telemetry.tactical_demotions += int(
            outcome.decision == TacticalResourceDecision.DEMOTE
        )
        telemetry.tactical_suspensions += int(
            outcome.decision == TacticalResourceDecision.SUSPEND_FOR_STATE
        )
        telemetry.tactical_terminal_escalations += int(
            outcome.decision == TacticalResourceDecision.TERMINAL_ESCALATION
        )


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


def _named_dependency_closure_campaign(
    node: StrategicSearchNode,
) -> Optional[FoundationCampaign]:
    """Select one already-named protected/supply objective, never a suit constant."""
    assert node.analysis is not None
    labels = []
    if node.active_milestone is not None and node.active_milestone.campaign_id is not None:
        labels.append(node.active_milestone.campaign_id)
    if node.continuation_credit is not None and node.continuation_credit.is_live:
        labels.append(node.continuation_credit.objective_id)
    if node.protected_conversion_lane is not None:
        labels.append(node.protected_conversion_lane.target_campaign)
    for contract in node.active_deal_contracts:
        result = supply_result_for_contract(
            node.supply_consumption_results, contract.contract_id
        )
        if (
            contract.purpose == DealPurposeKind.CAMPAIGN_SUPPLY
            and contract.campaign_id is not None
            and (
                result is None
                or not result.fully_consumed
            )
        ):
            labels.append(contract.campaign_id)
    if node.analysis.tactical_demands is not None:
        labels.extend(
            item.campaign_id
            for item in node.analysis.tactical_demands.for_realizer(
                TacticalRealizerKind.DEPENDENCY_CLOSURE
            )
            if item.campaign_id is not None
        )
    for label in dict.fromkeys(labels):
        campaign = next(
            (
                item
                for item in node.analysis.economic.campaign_portfolio.campaigns
                if item.label == label
            ),
            None,
        )
        if campaign is not None:
            return campaign
    return None


def _dependency_closure_successors(
    node: StrategicSearchNode,
    *,
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    deadline: SearchDeadline,
    started: float,
    cache: Optional[DependencyClosureCache] = None,
    resource_allocator: Optional[TacticalResourceAllocator] = None,
    target_demand: Optional[TacticalDemand] = None,
) -> Tuple[List[StrategicSuccessor], Optional[DependencyClosureResult]]:
    """Offer one bounded same-epoch closure before considering another Deal."""
    if (
        not config.enable_dependency_closure
        or (
            target_demand is None
            and
            not config.enable_tactical_resource_allocation
            and not node.state.foundations
        )
        or node.analysis is None
    ):
        return [], None
    campaign = (
        next(
            (
                item
                for item in node.analysis.economic.campaign_portfolio.campaigns
                if target_demand is not None
                and item.label == target_demand.campaign_id
            ),
            None,
        )
        if target_demand is not None
        else _named_dependency_closure_campaign(node)
    )
    if campaign is None:
        return [], None
    allocator = resource_allocator or _resource_allocator_for_config(config)
    demand = target_demand or _resource_demand(
        node,
        TacticalRealizerKind.DEPENDENCY_CLOSURE,
        campaign_id=campaign.label,
    )
    demand, lineage_entry, lineage_decision = _target_lineage_request_context(
        node, demand, config
    )
    _request, grant = allocator.request(canonical_state_key(node.state), demand)
    if grant is None:
        if lineage_entry is not None and lineage_decision is not None:
            residual = node.active_residual_target
            blocker_kind = residual.blockers[0].value if residual and residual.blockers else None
            refused = record_target_grant(
                lineage_entry,
                state_key=canonical_state_key(node.state),
                dependency_id=demand.target_dependency_id,
                blocker_fingerprint=demand.critical_path_fingerprint,
                blocker_kind=blocker_kind,
                requested_tier=lineage_decision.requested_tier,
                granted_tier=None,
                decision=lineage_decision,
                realizer=demand.realizer.value,
            )
            trace = make_boundary_trace(
                refused,
                lineage_decision,
                dependency_after=demand.target_dependency_id,
                blocker_after=blocker_kind,
                progress_before=lineage_entry.evidence.completion_class or "NEW",
                progress_after="NO_GRANT_WITHIN_PER_EXPANSION_CEILING",
                fresh_candidate_classes=(
                    tuple(item.blocker.value for item in residual.candidates)
                    if residual is not None else ()
                ),
                best_next_candidate=(
                    residual.next_candidate.rationale
                    if residual is not None and residual.next_candidate is not None
                    else None
                ),
                admission_reason="existing per-expansion allocator ceiling refused the request",
                eventual_target_outcome="NOT_EXECUTED",
                failure_diagnosis=PersistedTargetFailureDiagnosis.RESOURCE_BOUND,
            )
            _publish_target_boundary_telemetry(
                telemetry,
                refused,
                lineage_decision,
                trace,
                maximum=config.max_timeline_entries,
            )
        return [], None
    remaining_nodes = max(0, config.max_tactical_nodes - telemetry.tactical_nodes)
    if remaining_nodes <= 0 or not deadline.can_start(
        "campaign_dependency_closure", minimum_seconds=0.01, minimum_nodes=1
    ):
        return [], None
    closure_config = replace(
        config.dependency_closure_config,
        enable_legal_candidate_audit=config.enable_closure_candidate_audit,
        max_added_cost=min(
            config.dependency_closure_config.max_added_cost,
            grant.max_added_cost,
        ),
        max_nodes=min(
            config.dependency_closure_config.max_nodes,
            grant.nodes_granted,
            remaining_nodes,
        ),
        time_limit_s=max(
            0.01,
            min(
                config.dependency_closure_config.time_limit_s,
                grant.seconds_granted,
                deadline.time_slice(
                    "campaign_dependency_closure",
                    config.dependency_closure_config.time_limit_s,
                ),
            ),
        ),
    )
    telemetry.dependency_closure_attempts += 1
    call_started = time.perf_counter()
    with deadline.measure("campaign_dependency_closure"):
        result = realize_campaign_dependency_closure(
            node.state,
            campaign,
            config=closure_config,
            supply_consumptions=node.supply_consumption_results,
            deadline=deadline,
            cache=cache,
            target_dependency_id=demand.target_dependency_id,
            semantic_target_id=(
                node.active_residual_target.identity.fingerprint
                if node.active_residual_target is not None
                else None
            ),
        )
    elapsed = time.perf_counter() - call_started
    telemetry.dependency_closure_seconds += elapsed
    telemetry.dependency_closure_max_seconds = max(
        telemetry.dependency_closure_max_seconds, elapsed
    )
    telemetry.dependency_closure_nodes += result.nodes_expanded
    telemetry.tactical_nodes += result.nodes_expanded
    telemetry.dependency_graphs_built += 2
    telemetry.closure_targeted_calls += int(result.target_dependency_id is not None)
    completion_name = result.completion_class.value
    telemetry.closure_completion_classes[completion_name] = (
        telemetry.closure_completion_classes.get(completion_name, 0) + 1
    )
    telemetry.closure_dependency_completed += int(
        result.completion_class == ClosureCompletionClass.DEPENDENCY_COMPLETED
    )
    telemetry.closure_source_exposed += int(
        result.completion_class == ClosureCompletionClass.SOURCE_EXPOSED
    )
    telemetry.closure_dependency_advanced += int(
        result.completion_class == ClosureCompletionClass.DEPENDENCY_ADVANCED
    )
    telemetry.closure_resource_bound += int(
        result.completion_class == ClosureCompletionClass.RESOURCE_BOUND
        or result.failure_diagnosis.value == "RESOURCE_BOUND"
    )
    telemetry.closure_structural_blocker += int(
        result.completion_class == ClosureCompletionClass.STRUCTURAL_BLOCKER
        or result.failure_diagnosis.value == "STRUCTURAL_BLOCKER"
    )
    telemetry.closure_search_policy += int(result.failure_diagnosis.value == "SEARCH_POLICY")
    telemetry.closure_invalidated += int(
        result.completion_class == ClosureCompletionClass.TARGET_INVALIDATED
    )
    telemetry.closure_advanced_states_continued += result.advanced_states_continued
    telemetry.closure_advanced_fallbacks += int(result.advanced_fallback_returned)
    primitive_count = len(result.steps)
    telemetry.closure_primitives_total += primitive_count
    telemetry.closure_max_primitive_sequence = max(
        telemetry.closure_max_primitive_sequence, primitive_count
    )
    prior_advanced = next(
        (
            prior
            for prior in reversed(node.dependency_closure_history)
            if prior.target_dependency_id == result.target_dependency_id
            and prior.completion_class == ClosureCompletionClass.DEPENDENCY_ADVANCED
        ),
        None,
    )
    if prior_advanced is not None:
        telemetry.closure_advanced_persisted_across_expansions += 1
        telemetry.closure_persisted_targets_completed += int(
            result.completion_class
            in (
                ClosureCompletionClass.DEPENDENCY_COMPLETED,
                ClosureCompletionClass.SOURCE_EXPOSED,
            )
        )
    endpoint = result.endpoint_assessment
    if endpoint is not None:
        lifecycle_summary = endpoint.lifecycle
        telemetry.closure_stable_joins_restored_or_replaced += (
            lifecycle_summary.stable_joins_restored_or_replaced
        )
        telemetry.closure_midpoint_rehandling_debt += (
            lifecycle_summary.midpoint_rehandling_debt
        )
        telemetry.closure_final_rehandling_debt += lifecycle_summary.final_rehandling_debt
        telemetry.closure_projected_compensation_accepted += (
            lifecycle_summary.projected_compensation_accepted
        )
        telemetry.closure_projected_compensation_rejected += (
            lifecycle_summary.projected_compensation_rejected
        )
        exposed = endpoint.source_exposed
        blocker_progress = any(
            step.progress_evidence is not None
            and step.progress_evidence.source_depth_after
            < step.progress_evidence.source_depth_before
            for step in result.steps
        )
        telemetry.closure_receiver_blocker_exposure_chains += int(
            exposed
            and blocker_progress
            and any(
                step.progress_evidence is not None
                and step.progress_evidence.receiver_created
                for step in result.steps
            )
        )
        telemetry.closure_workspace_blocker_exposure_chains += int(
            exposed
            and blocker_progress
            and any(
                step.progress_evidence is not None
                and step.progress_evidence.workspace_created
                for step in result.steps
            )
        )
        telemetry.closure_park_blocker_exposure_chains += int(
            exposed
            and blocker_progress
            and any(
                step.lifecycle is not None
                and step.lifecycle.placement_class
                in (PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK)
                for step in result.steps
            )
        )
    critical_path = build_campaign_critical_path(result.graph_before)
    telemetry.critical_paths_built += 1
    for dependency in result.graph_before.dependencies:
        telemetry.dependencies_by_type[dependency.kind.value] = (
            telemetry.dependencies_by_type.get(dependency.kind.value, 0) + 1
        )
    telemetry.dependencies_closed += len(result.dependencies_closed)
    telemetry.overlays_cleared += len(result.overlays_cleared)
    telemetry.receivers_created_by_closure += sum(
        dependency_id.startswith("receiver:")
        for dependency_id in result.dependencies_closed
    )
    for trace in result.buried_source_traces:
        telemetry.source_buried_attempts += 1
        telemetry.source_physical_blockers += len(trace.blocker_before.blocker_cards)
        telemetry.source_copies_considered += len(trace.blocker_before.physical_sources)
        telemetry.source_copy_substitutions += trace.source_copy_substitutions
        telemetry.sources_exposed += trace.sources_exposed
        telemetry.sources_consumed += int(trace.source_consumed)
        telemetry.closure_legal_candidate_audit_count += len(
            trace.legal_target_relevant_actions
        )
        telemetry.closure_candidates_generated += len(trace.generated_actions)
        telemetry.closure_candidates_missing_from_generator += len(
            trace.missing_from_generator
        )
        telemetry.closure_beam_retained += sum(item.retained for item in trace.beam_audits)
        telemetry.closure_beam_discarded += sum(item.discarded for item in trace.beam_audits)
        telemetry.closure_target_progress_representatives += sum(
            len(item.retained_progress_kinds) for item in trace.beam_audits
        )
        telemetry.closure_failure_diagnoses[trace.failure_diagnosis.value] = (
            telemetry.closure_failure_diagnoses.get(trace.failure_diagnosis.value, 0) + 1
        )
        for audit in trace.candidate_audits:
            if audit.disposition.value == "ADMITTED":
                telemetry.closure_candidates_admitted += 1
            if audit.rejection_reason is not None:
                reason_key = audit.rejection_reason.value
                telemetry.closure_candidates_rejected_by_reason[reason_key] = (
                    telemetry.closure_candidates_rejected_by_reason.get(reason_key, 0) + 1
                )
    for step in result.steps:
        progress = step.progress_evidence
        lifecycle = step.lifecycle
        if progress is not None:
            telemetry.source_depth_reduced += int(
                progress.source_depth_after < progress.source_depth_before
            )
            telemetry.closure_receivers_created += int(progress.receiver_created)
            telemetry.closure_workspace_created += int(progress.workspace_created)
            telemetry.closure_workspace_used += int(
                progress.workspace_created and progress.source_depth_after < progress.source_depth_before
            )
        if lifecycle is not None:
            is_park = lifecycle.placement_class in (
                PlacementClass.MIXED_SUIT_PARK,
                PlacementClass.WORKSPACE_PARK,
            )
            telemetry.closure_temporary_parks += int(is_park)
            telemetry.closure_temporary_park_exits += int(
                is_park and lifecycle.exit_route_bounded
            )
            telemetry.closure_stable_runs_broken += len(lifecycle.same_suit_joins_broken)
            telemetry.closure_lifecycle_debt += lifecycle.estimated_rehandling_cost
    if endpoint is not None:
        telemetry.closure_stable_runs_restored += (
            endpoint.lifecycle.stable_joins_restored_or_replaced
        )
    if critical_path.entries:
        maximum_unlock = max(
            item.downstream_dependencies_unlocked for item in critical_path.entries
        )
        high_unlock = {
            item.dependency_id
            for item in critical_path.entries
            if item.downstream_dependencies_unlocked == maximum_unlock
        }
        telemetry.high_unlock_dependencies_chosen += sum(
            bool(set(step.targeted_dependencies) & high_unlock)
            for step in result.steps
        )
    if (
        not campaign_is_near_removal(
            node.state,
            campaign,
            config=config.terminal_assembly_config.near_removal,
        )
        and campaign_is_near_removal(
            result.end_state,
            campaign,
            config=config.terminal_assembly_config.near_removal,
        )
    ):
        telemetry.terminal_qualification_transitions += 1
    consumed_before = sum(
        item.consumed_count for item in node.supply_consumption_results
    )
    consumed_after = sum(item.consumed_count for item in result.supply_consumptions)
    telemetry.supplied_assets_consumed_by_closure += max(
        0, consumed_after - consumed_before
    )
    _append_bounded(
        telemetry.dependency_closure_timeline,
        (
            node.g,
            campaign.label,
            result.status.value,
            len(result.graph_before.dependencies) - 1,
            len(result.graph_after.dependencies) - 1,
            result.dependencies_closed,
            result.overlays_cleared,
        ),
        config.max_timeline_entries,
    )
    successful = result.status in (
        DependencyClosureStatus.FOUNDATION_REMOVED,
        DependencyClosureStatus.DEPENDENCY_CLOSED,
        DependencyClosureStatus.DEPENDENCY_ADVANCED,
        DependencyClosureStatus.SUPPLY_CONSUMED,
        DependencyClosureStatus.MILESTONE_REACHED,
    )
    target_grant_entry, target_boundary_trace = _target_lineage_after_closure(
        node,
        demand,
        grant,
        lineage_entry,
        lineage_decision,
        result,
    )
    source_completion_traces = []
    for event in result.source_completion_events:
        trace = SourceCompletionPropagationTrace(event).advance(
            SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED,
            detail="replay-valid strategic successor carries the typed source event",
        )
        if (
            target_grant_entry is not None
            and event.event_id in target_grant_entry.source_completion_event_ids
        ):
            trace = trace.advance(
                SourceCompletionStage.LINEAGE_PRESERVED,
                disposition=SourceCompletionDisposition.PRESERVED,
                detail="target lineage preserves the completed scoped source requirement",
            )
        source_completion_traces.append(trace)
        _record_source_completion_trace(
            telemetry, trace, config.max_timeline_entries
        )
    _publish_target_boundary_telemetry(
        telemetry,
        target_grant_entry,
        lineage_decision,
        target_boundary_trace,
        maximum=config.max_timeline_entries,
    )
    if not successful:
        telemetry.dependency_closure_failures[result.status.value] = (
            telemetry.dependency_closure_failures.get(result.status.value, 0) + 1
        )
        _record_tactical_transition(
            allocator,
            grant,
            node,
            result.end_state,
            nodes_consumed=result.nodes_expanded,
            seconds_consumed=elapsed,
            corrected_paid_cost=int(result.corrected_added_cost or 0),
            legal_successor_count=0,
            campaign=campaign,
            supply_after=result.supply_consumptions,
            dependencies_closed=len(result.dependencies_closed),
            overlays_cleared=len(result.overlays_cleared),
            receivers_created=sum(
                item.startswith("receiver:") for item in result.dependencies_closed
            ),
            reason=result.reason,
        )
        return [], result
    if (
        not result.actions
        or result.corrected_added_cost is None
        or not result.independent_replay_verified
    ):
        telemetry.dependency_closure_failures["INVALID_SUCCESS"] = (
            telemetry.dependency_closure_failures.get("INVALID_SUCCESS", 0) + 1
        )
        return [], result
    telemetry.dependency_closure_successes += 1
    _record_tactical_transition(
        allocator,
        grant,
        node,
        result.end_state,
        nodes_consumed=result.nodes_expanded,
        seconds_consumed=elapsed,
        corrected_paid_cost=int(result.corrected_added_cost or 0),
        legal_successor_count=1,
        campaign=campaign,
        supply_after=result.supply_consumptions,
        dependencies_closed=len(result.dependencies_closed),
        overlays_cleared=len(result.overlays_cleared),
        receivers_created=sum(
            item.startswith("receiver:") for item in result.dependencies_closed
        ),
        reason=result.reason,
    )
    investment = None
    continuation = None
    if config.enable_structural_investment:
        prior_supply_stage = {
            evidence.obligation_id: evidence.stage
            for supply in node.supply_consumption_results
            for evidence in supply.evidence
        }
        newly_consumed_supply = tuple(
            evidence.obligation_id
            for supply in result.supply_consumptions
            for evidence in supply.evidence
            if evidence.direct_campaign_advance
            and evidence.stage
            in (SupplyConsumptionStage.CONSUMED, SupplyConsumptionStage.INTEGRATED)
            and prior_supply_stage.get(evidence.obligation_id)
            not in (SupplyConsumptionStage.CONSUMED, SupplyConsumptionStage.INTEGRATED)
        )
        investment = investment_from_dependency_closure(
            canonical_state_key(node.state),
            result,
            created_depth=node.depth,
            created_elapsed_seconds=time.perf_counter() - started,
            maximum_further_cost=config.continuation_max_further_cost,
            maximum_descendant_expansions=config.continuation_max_descendant_expansions,
            maximum_elapsed_seconds=config.continuation_max_elapsed_seconds,
            baseline_total_g=node.g + int(result.corrected_added_cost or 0),
            supply_consumed_obligation_ids=newly_consumed_supply,
        )
        outstanding = tuple(
            item.dependency_id
            for item in result.graph_after.dependencies
            if item.dependency_id != result.graph_after.terminal_dependency_id
        )
        if config.enable_same_campaign_continuity:
            continuation = continuation_from_investment(
                investment,
                outstanding_dependencies=outstanding,
            )
    rationale = (
        result.reason,
        f"named_campaign={campaign.label}",
        f"dependencies_closed={result.dependencies_closed}",
        f"overlays_cleared={result.overlays_cleared}",
        "same-epoch closure does not Deal unless explicitly configured",
        "bounded miss has no proof authority",
    ) + tuple(
        (
            f"target={step.targeted_dependencies}; placement="
            f"{step.lifecycle.placement_class.value if step.lifecycle else 'DEAL'}; "
            f"joins+={step.lifecycle.same_suit_joins_created if step.lifecycle else ()}; "
            f"joins-={step.lifecycle.same_suit_joins_broken if step.lifecycle else ()}; "
            f"mixed+={step.lifecycle.mixed_suit_boundaries_created if step.lifecycle else ()}; "
            f"mixed-={step.lifecycle.mixed_suit_boundaries_removed if step.lifecycle else ()}; "
            f"exit={step.lifecycle.future_exit_route if step.lifecycle else 'configured stock transition'}; "
            f"rehandling={step.lifecycle.estimated_rehandling_cost if step.lifecycle else 0}"
        )
        for step in result.steps
    )
    return [
        StrategicSuccessor(
            StrategicActionKind.CAMPAIGN_DEPENDENCY_CLOSURE,
            "dependency_closure",
            f"close named dependencies for {campaign.label}",
            result.actions,
            result.corrected_added_cost,
            result.end_state.clone(),
            node.credit_level,
            result.corrected_added_cost,
            result.corrected_added_cost,
            result.nodes_expanded,
            True,
            False,
            rationale,
            source_project_id=campaign.label,
            dependency_closure_result=result,
            structural_investment=investment,
            continuation_credit=continuation,
            target_grant_entry=target_grant_entry,
            target_boundary_trace=target_boundary_trace,
            source_completion_traces=tuple(source_completion_traces),
        )
    ], result


def _construction_successors(
    node: StrategicSearchNode,
    *,
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    started: float,
    resource_allocator: Optional[TacticalResourceAllocator] = None,
    preferred_opportunity_id: Optional[str] = None,
    target_demand: Optional[TacticalDemand] = None,
) -> List[StrategicSuccessor]:
    """Retain durable construction independently of removal proximity."""
    if (
        not config.enable_same_suit_construction
        or node.analysis is None
        or node.analysis.construction is None
    ):
        return []
    construction = node.analysis.construction
    opportunities = construction.opportunities
    telemetry.same_suit_construction_opportunities += len(opportunities)
    telemetry.two_card_construction_joins += sum(
        item.run_length_after == 2 for item in opportunities
    )
    telemetry.larger_construction_merges += sum(
        item.run_length_after > 2 for item in opportunities
    )
    telemetry.late_removal_construction_opportunities += sum(
        item.removal_horizon is not None
        and item.removal_horizon > item.construction_horizon
        for item in opportunities
    )
    telemetry.free_future_join_deferrals += sum(
        item.disposition == ConstructionDisposition.DEFER_FOR_FREE_FUTURE_JOIN
        for item in opportunities
    )
    telemetry.workspace_conflict_deferrals += sum(
        item.disposition == ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT
        for item in opportunities
    )
    make_now = [
        item for item in opportunities if item.disposition == ConstructionDisposition.MAKE_NOW
    ]
    preferred = next(
        (
            item for item in make_now
            if item.opportunity_id == preferred_opportunity_id
        ),
        None,
    )
    selected = [preferred] if preferred is not None else make_now[:1]
    late = next(
        (
            item
            for item in make_now
            if item.removal_horizon is not None
            and item.removal_horizon > item.construction_horizon
            and item not in selected
        ),
        None,
    )
    if late is not None:
        selected.append(late)
    selected = selected[: config.max_construction_successors_per_expansion]
    campaigns = node.analysis.economic.campaign_portfolio.campaigns
    allocator = resource_allocator or _resource_allocator_for_config(config)
    successors = []
    for opportunity in selected:
        demand = target_demand or _resource_demand(
            node,
            TacticalRealizerKind.RUN_CONSTRUCTION,
            construction_opportunity_id=opportunity.opportunity_id,
        )
        demand, lineage_entry, lineage_decision = _target_lineage_request_context(
            node, demand, config
        )
        _request, grant = allocator.request(canonical_state_key(node.state), demand)
        if grant is None:
            continue
        action = opportunity.action
        if not node.state.can_move(*action):
            continue
        call_started = time.perf_counter()
        end = node.state.clone()
        cost = end.move(*action, rules=MW_RULES)
        campaign = next(
            (item for item in campaigns if item.suit == opportunity.suit),
            None,
        )
        objective_id = (
            campaign.label if campaign is not None else f"construction:{opportunity.suit}"
        )
        investment = investment_from_construction(
            canonical_state_key(node.state),
            opportunity,
            objective_id=objective_id,
            created_depth=node.depth,
            created_elapsed_seconds=time.perf_counter() - started,
            baseline_total_g=node.g + cost,
        )
        _record_tactical_transition(
            allocator,
            grant,
            node,
            end,
            nodes_consumed=1,
            seconds_consumed=time.perf_counter() - call_started,
            corrected_paid_cost=cost,
            legal_successor_count=1,
            permanent_adjacencies_created=opportunity.new_adjacencies,
            reason="durable same-suit construction edge",
        )
        target_grant_entry = None
        target_boundary_trace = None
        if lineage_entry is not None and lineage_decision is not None:
            residual = node.active_residual_target
            blocker_kind = residual.blockers[0].value if residual and residual.blockers else None
            target_grant_entry = record_target_grant(
                lineage_entry,
                state_key=canonical_state_key(node.state),
                dependency_id=demand.target_dependency_id,
                blocker_fingerprint=demand.critical_path_fingerprint,
                blocker_kind=blocker_kind,
                requested_tier=lineage_decision.requested_tier,
                granted_tier=grant.tier,
                decision=lineage_decision,
                realizer=demand.realizer.value,
            )
            evidence = TargetCommitmentEvidence(
                named_harvest=("PERMANENT_SAME_SUIT_PREREQUISITE",),
                prerequisite_completed=True,
                substantial_progress=opportunity.run_length_after > 2,
                target_relevant=target_demand is not None,
                nodes_consumed=1,
                seconds_consumed=time.perf_counter() - call_started,
                corrected_paid_cost=cost,
            )
            target_grant_entry = record_target_outcome(
                target_grant_entry,
                evidence,
                end_state_key=canonical_state_key(end),
            )
            candidate_classes = tuple(
                item.blocker.value for item in residual.candidates
            ) if residual is not None else ()
            target_boundary_trace = make_boundary_trace(
                target_grant_entry,
                lineage_decision,
                dependency_after=demand.target_dependency_id,
                blocker_after=blocker_kind,
                progress_before=lineage_entry.evidence.completion_class or "NEW",
                progress_after="PERMANENT_SAME_SUIT_PREREQUISITE",
                fresh_candidate_classes=candidate_classes,
                best_next_candidate=(
                    residual.next_candidate.rationale
                    if residual is not None and residual.next_candidate is not None
                    else None
                ),
                granted_tier=grant.tier,
                selected_action=repr(action),
                admission_reason="target-attributed durable construction executed",
                eventual_target_outcome="ADVANCED",
            )
            _publish_target_boundary_telemetry(
                telemetry,
                target_grant_entry,
                lineage_decision,
                target_boundary_trace,
                maximum=config.max_timeline_entries,
            )
        _append_bounded(
            telemetry.construction_timeline,
            (
                node.g,
                objective_id,
                opportunity.disposition.value,
                opportunity.run_length_after,
                opportunity.removal_horizon,
            ),
            config.max_timeline_entries,
        )
        successors.append(
            StrategicSuccessor(
                StrategicActionKind.SAME_SUIT_CONSTRUCTION,
                "run_construction",
                (
                    f"construct {opportunity.run_length_after}-card "
                    f"{opportunity.suit.upper()} same-suit run"
                ),
                (action,),
                cost,
                end,
                node.credit_level,
                cost,
                cost,
                1,
                _replay_edge(node.state, (action,), end, cost),
                False,
                opportunity.rationale,
                source_project_id=objective_id,
                structural_investment=investment,
                construction_opportunity=opportunity,
                target_grant_entry=target_grant_entry,
                target_boundary_trace=target_boundary_trace,
            )
        )
    return successors


def _foundation_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    started: float,
    deadline: Optional[SearchDeadline] = None,
    resource_allocator: Optional[TacticalResourceAllocator] = None,
    closure_offer: Optional[DependencyClosureResult] = None,
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
    if node.active_milestone is not None and node.active_milestone.campaign_id is not None:
        named = next(
            (
                item
                for item in node.analysis.economic.campaign_portfolio.campaigns
                if item.label == node.active_milestone.campaign_id
            ),
            None,
        )
        if named is not None:
            campaigns = (named,) + tuple(item for item in campaigns if item.label != named.label)
            campaigns = campaigns[:campaign_limit]
    successors: List[StrategicSuccessor] = []
    allocator = resource_allocator or _resource_allocator_for_config(config)
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
        terminal_attempted = False
        removal_attempted = False
        closure_harvested_same_campaign = bool(
            config.enable_tactical_resource_allocation
            and closure_offer is not None
            and closure_offer.campaign_id == campaign.label
            and closure_offer.status
            in (
                DependencyClosureStatus.FOUNDATION_REMOVED,
                DependencyClosureStatus.DEPENDENCY_CLOSED,
                DependencyClosureStatus.DEPENDENCY_ADVANCED,
                DependencyClosureStatus.SUPPLY_CONSUMED,
                DependencyClosureStatus.MILESTONE_REACHED,
            )
        )
        if (
            config.enable_terminal_assembly
            and campaign_is_near_removal(
                node.state,
                campaign,
                config=config.terminal_assembly_config.near_removal,
            )
        ):
            demand = _resource_demand(
                node,
                TacticalRealizerKind.TERMINAL_ASSEMBLY,
                campaign_id=campaign.label,
            )
            _request, grant = allocator.request(canonical_state_key(node.state), demand)
            terminal = None
            if grant is not None:
                terminal_attempted = True
                telemetry.near_removal_campaigns_detected += 1
                telemetry.terminal_realizer_attempts += 1
                terminal_config = replace(
                    config.terminal_assembly_config,
                    max_added_cost=min(
                        config.terminal_assembly_config.max_added_cost,
                        grant.max_added_cost,
                    ),
                    max_nodes=min(
                        config.terminal_assembly_config.max_nodes,
                        grant.nodes_granted,
                        remaining_nodes,
                    ),
                    time_limit_s=min(
                        config.terminal_assembly_config.time_limit_s,
                        grant.seconds_granted,
                        max(0.01, _remaining_controller_time(started, config)),
                    ),
                )
                call_started = time.perf_counter()
                terminal = realize_terminal_campaign_assembly(
                    node.state,
                    campaign,
                    config=terminal_config,
                    deadline=deadline,
                )
                terminal_elapsed = time.perf_counter() - call_started
                telemetry.tactical_nodes += terminal.nodes_expanded
                remaining_nodes = max(1, config.max_tactical_nodes - telemetry.tactical_nodes)
                _record_tactical_transition(
                    allocator,
                    grant,
                    node,
                    terminal.end_state,
                    nodes_consumed=terminal.nodes_expanded,
                    seconds_consumed=terminal_elapsed,
                    corrected_paid_cost=int(terminal.corrected_added_cost or 0),
                    legal_successor_count=int(
                        terminal.status == TerminalAssemblyStatus.FOUNDATION_REMOVED
                        and terminal.independent_replay_verified
                    ),
                    campaign=campaign,
                    reason=terminal.reason,
                )
            if (
                terminal is not None
                and
                terminal.status == TerminalAssemblyStatus.FOUNDATION_REMOVED
                and terminal.independent_replay_verified
                and terminal.actions
                and terminal.corrected_added_cost is not None
            ):
                telemetry.terminal_realizer_successes += 1
                successors.append(
                    StrategicSuccessor(
                        StrategicActionKind.FOUNDATION_REMOVAL,
                        "campaign",
                        f"terminal assembly {campaign.label}",
                        terminal.actions,
                        terminal.corrected_added_cost,
                        terminal.end_state.clone(),
                        node.credit_level,
                        int(round(campaign.estimated_campaign_cost)),
                        terminal.corrected_added_cost,
                        terminal.nodes_expanded,
                        True,
                        False,
                        (
                            terminal.reason,
                            "strict structural near-removal predicate qualified",
                            "terminal result was independently replayed",
                        ),
                        campaign.label,
                    )
                )
                added = True
        if (
            removal_eligible
            and not added
            and (
                not terminal_attempted
                or not config.enable_tactical_resource_allocation
            )
            and not closure_harvested_same_campaign
            and (
                not config.enable_tactical_resource_allocation
                or node.credit_level >= StrategicCreditLevel.ESCAPE
            )
        ):
            demand = _resource_demand(
                node,
                TacticalRealizerKind.CAMPAIGN_REMOVAL,
                campaign_id=campaign.label,
            )
            _request, grant = allocator.request(canonical_state_key(node.state), demand)
            if grant is None:
                continue
            removal_attempted = True
            if (
                config.enable_tactical_resource_allocation
                and grant.removal_policy
                == RemovalAllocationPolicy.REMOVAL_DIAGNOSTIC_ONLY
            ):
                _record_tactical_transition(
                    allocator,
                    grant,
                    node,
                    node.state,
                    nodes_consumed=0,
                    seconds_consumed=0.0,
                    corrected_paid_cost=0,
                    legal_successor_count=0,
                    campaign=campaign,
                    reason=(
                        "removal diagnostic retained without invoking the expensive "
                        "realiser while an explicit prerequisite remains"
                    ),
                )
                continue
            telemetry.foundation_macro_attempts += 1
            call_started = time.perf_counter()
            removal = realize_campaign_to_removal_epoch(
                node.state,
                campaign,
                cards,
                max_added_cost=min(config.campaign_max_added_cost, grant.max_added_cost),
                max_nodes=min(config.campaign_max_nodes, grant.nodes_granted, remaining_nodes),
                time_limit_s=min(
                    config.campaign_time_limit_s,
                    grant.seconds_granted,
                    max(0.01, _remaining_controller_time(started, config)),
                ),
                beam_width=config.campaign_beam_width,
            )
            removal_elapsed = time.perf_counter() - call_started
            telemetry.tactical_nodes += removal.nodes_expanded
            _record_tactical_transition(
                allocator,
                grant,
                node,
                removal.end_state,
                nodes_consumed=removal.nodes_expanded,
                seconds_consumed=removal_elapsed,
                corrected_paid_cost=int(removal.corrected_added_cost or 0),
                legal_successor_count=int(
                    removal.independent_replay_verified and bool(removal.actions)
                ),
                campaign=campaign,
                reason=removal.stop_reason,
            )
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
            or (
                removal_attempted
                and config.enable_tactical_resource_allocation
            )
            or closure_harvested_same_campaign
            or telemetry.tactical_nodes >= config.max_tactical_nodes
            or (
                node.credit_level == StrategicCreditLevel.CLEAN
                and configured_campaign_limit == 0
            )
        ):
            continue
        demand = (
            _explicit_resource_demand(
                node,
                TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH,
                campaign_id=campaign.label,
            )
            if config.enable_tactical_resource_allocation
            else _resource_demand(
                node,
                TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH,
                campaign_id=campaign.label,
            )
        )
        if demand is None:
            continue
        _request, grant = allocator.request(canonical_state_key(node.state), demand)
        if grant is None:
            continue
        telemetry.foundation_macro_attempts += 1
        call_started = time.perf_counter()
        result = realize_campaign_to_next_epoch(
            node.state,
            campaign,
            cards,
            max_added_cost=min(config.campaign_max_added_cost, grant.max_added_cost),
            max_nodes=min(
                config.campaign_max_nodes,
                grant.nodes_granted,
                max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
            ),
            time_limit_s=min(
                config.campaign_time_limit_s,
                grant.seconds_granted,
                max(0.01, _remaining_controller_time(started, config)),
            ),
        )
        current_elapsed = time.perf_counter() - call_started
        telemetry.tactical_nodes += result.nodes_expanded
        _record_tactical_transition(
            allocator,
            grant,
            node,
            result.resulting_state,
            nodes_consumed=result.nodes_expanded,
            seconds_consumed=current_elapsed,
            corrected_paid_cost=int(result.corrected_added_cost or 0),
            legal_successor_count=int(
                result.independent_replay_verified and bool(result.actions)
            ),
            campaign=campaign,
            reason=result.stop_reason,
        )
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
    resource_allocator: Optional[TacticalResourceAllocator] = None,
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
    allocator = resource_allocator or _resource_allocator_for_config(config)
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
        demand = (
            _explicit_resource_demand(
                node,
                TacticalRealizerKind.CAMPAIGN_CORRIDOR,
                campaign_id=campaign.label,
            )
            if config.enable_tactical_resource_allocation
            else _resource_demand(
                node,
                TacticalRealizerKind.CAMPAIGN_CORRIDOR,
                campaign_id=campaign.label,
            )
        )
        if demand is None:
            continue
        _request, grant = allocator.request(canonical_state_key(node.state), demand)
        if grant is None:
            continue
        lane_config = replace(
            corridor_config,
            max_added_cost=min(corridor_config.max_added_cost, grant.max_added_cost),
            max_nodes=min(
                corridor_config.max_nodes,
                grant.nodes_granted,
                max(1, config.max_tactical_nodes - telemetry.tactical_nodes),
            ),
            time_limit_s=min(
                corridor_config.time_limit_s,
                grant.seconds_granted,
                max(0.01, deadline.remaining_wall_time),
            ),
        )
        call_started = time.perf_counter()
        result = realize_campaign_corridor(
            node.state,
            campaign,
            cards,
            config=lane_config,
            deadline=deadline,
        )
        call_elapsed = time.perf_counter() - call_started
        telemetry.tactical_nodes += result.nodes_expanded
        telemetry.corridor_nodes += result.nodes_expanded
        telemetry.corridor_seconds += result.elapsed_seconds
        _record_tactical_transition(
            allocator,
            grant,
            node,
            result.end_state,
            nodes_consumed=result.nodes_expanded,
            seconds_consumed=call_elapsed,
            corrected_paid_cost=int(result.corrected_added_cost or 0),
            legal_successor_count=int(
                result.independent_replay_verified and bool(result.actions)
            ),
            campaign=campaign,
            reason=result.stop_reason,
        )
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


def _fresh_milestone_facts(
    state: SpiderState,
    analysis: StrategicAnalysisSnapshot,
    milestone: StrategicMilestone,
    supply_consumptions: Sequence[SupplyConsumptionResult],
    config: AnytimeControllerConfig,
) -> Tuple[Tuple[str, ...], bool]:
    campaign = next(
        (
            item
            for item in analysis.economic.campaign_portfolio.campaigns
            if item.label == milestone.campaign_id
        ),
        None,
    )
    if campaign is None:
        return (), False
    graph = build_campaign_dependency_graph(
        state, campaign, supply_consumptions=supply_consumptions
    )
    remaining = tuple(
        item.dependency_id
        for item in graph.dependencies
        if item.kind != CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE
    )
    terminal = campaign_is_near_removal(
        state, campaign, config=config.terminal_assembly_config.near_removal
    )
    return remaining, terminal


def _residual_target_for_milestone(
    state: SpiderState,
    analysis: StrategicAnalysisSnapshot,
    milestone: StrategicMilestone,
    config: AnytimeControllerConfig,
    source_satisfactions=(),
) -> ResidualMilestoneTarget:
    graph = next(
        (
            item for item in analysis.dependency_graphs
            if item.campaign_id == milestone.campaign_id
        ),
        None,
    )
    path = next(
        (
            item for item in analysis.critical_paths
            if item.campaign_id == milestone.campaign_id
        ),
        None,
    )
    availability = next(
        (
            item for item in analysis.campaign_epoch_availability
            if item.campaign_id == milestone.campaign_id
        ),
        None,
    )
    return derive_residual_milestone_target(
        state,
        milestone,
        graph=graph,
        construction=analysis.construction,
        availability=availability,
        terminal_qualified=bool(path and path.terminal_qualified),
        prior_source_satisfactions=source_satisfactions,
    )


def _matching_fresh_milestone(
    portfolio: Optional[StrategicMilestonePortfolio],
    milestone: StrategicMilestone,
) -> Optional[StrategicMilestone]:
    if portfolio is None:
        return None
    exact = portfolio.matching(milestone)
    if exact is not None:
        return exact
    return next(
        (
            item
            for item in portfolio.milestones
            if item.kind == milestone.kind
            and item.campaign_id == milestone.campaign_id
            and item.suit == milestone.suit
            and item.target.kind == milestone.target.kind
        ),
        None,
    )


def _milestone_conversion_successors(
    node: StrategicSearchNode,
    cards: Sequence[Card],
    *,
    incumbent_cost: Optional[int],
    config: AnytimeControllerConfig,
    telemetry: ControllerTelemetry,
    started: float,
    analysis_cache: Optional[
        Dict[Tuple[CanonicalStateKey, AnalysisConfigFingerprint], StrategicAnalysisFacts]
    ],
    deadline: SearchDeadline,
    dependency_closure_cache: Optional[DependencyClosureCache],
    resource_allocator: TacticalResourceAllocator,
) -> List[StrategicSuccessor]:
    """Compose existing v0.8 primitives inside one allocator expansion."""
    if not config.enable_strategic_milestones or node.analysis is None:
        return []
    portfolio = node.analysis.milestone_portfolio
    active = node.active_milestone or (
        portfolio.plan.primary if portfolio is not None else None
    )
    if active is None or active.status in (
        StrategicMilestoneStatus.ACHIEVED,
        StrategicMilestoneStatus.INVALIDATED,
        StrategicMilestoneStatus.SUPERSEDED,
        StrategicMilestoneStatus.EXPIRED,
    ):
        return []
    initial_residual = node.active_residual_target or _residual_target_for_milestone(
        node.state,
        node.analysis,
        active,
        config,
        node.source_completion_ledger.satisfactions,
    )
    if (
        active.status == StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH
        and initial_residual.status != ResidualTargetStatus.ACTIONABLE
    ):
        return []
    active = replace(
        active,
        created_depth=(node.depth if node.active_milestone is None else active.created_depth),
        created_elapsed_seconds=(
            time.perf_counter() - started
            if node.active_milestone is None
            else active.created_elapsed_seconds
        ),
        max_primitive_steps=min(active.max_primitive_steps, config.milestone_max_primitive_steps),
        max_strategic_expansions=min(active.max_strategic_expansions, config.milestone_max_strategic_expansions),
        max_elapsed_seconds=min(active.max_elapsed_seconds, config.milestone_max_time_s_per_expansion),
        max_tactical_nodes=min(active.max_tactical_nodes, config.milestone_max_nodes_per_expansion),
    )
    latest_analysis = node.analysis
    latest_residual = replace(initial_residual, milestone=active)
    latest_target_grant_entry: Optional[TargetGrantLineageEntry] = None
    latest_target_boundary_trace: Optional[TargetBoundaryTrace] = None
    latest_source_satisfactions = list(node.source_completion_ledger.satisfactions)

    def analyze_fresh(state: SpiderState, prior: StrategicMilestone) -> FreshMilestoneAssessment:
        nonlocal latest_analysis, latest_residual, latest_source_satisfactions
        try:
            latest_analysis = analyze_strategic_state(
                state,
                cards,
                spent_cost=node.g,
                incumbent_cost=incumbent_cost,
                config=config,
                include_deal_timing=False,
                analysis_cache=analysis_cache,
                telemetry=telemetry,
                deadline=deadline,
                supply_consumptions=node.supply_consumption_results,
                continuation_objective_id=prior.campaign_id,
            )
        except AnalysisResourceLimit:
            return FreshMilestoneAssessment(
                None,
                prior.progress,
                contradicted=True,
                reason="deadline prevented mandatory fresh milestone analysis",
            )
        telemetry.reanalyses += 1
        telemetry.stage1_analyses += 1
        prior_residual = latest_residual
        latest_residual = _residual_target_for_milestone(
            state,
            latest_analysis,
            prior,
            config,
            latest_source_satisfactions,
        )
        latest_source_satisfactions = list(latest_residual.source_satisfactions)
        telemetry.source_completion_reanalyses += int(
            bool(latest_source_satisfactions)
        )
        telemetry.residual_targets_rebuilt += 1
        progress = latest_residual.progress
        matching = replace(
            prior,
            target_identity=latest_residual.identity,
            progress=progress,
            status=(
                StrategicMilestoneStatus.ACHIEVED
                if latest_residual.status == ResidualTargetStatus.COMPLETE
                else StrategicMilestoneStatus.ACTIVE
            ),
        )
        contradicted = latest_residual.status == ResidualTargetStatus.INVALIDATED
        structural_progress = bool(
            latest_residual.progress.satisfied_units
            > prior_residual.progress.satisfied_units
            or len(latest_residual.remaining_dependency_ids)
            < len(prior_residual.remaining_dependency_ids)
            or latest_residual.blockers != prior_residual.blockers
        )
        if contradicted:
            matching = None
        return FreshMilestoneAssessment(
            matching,
            progress,
            contradicted=contradicted,
            reason=(
                "fresh structural analysis satisfies the milestone predicate"
                if progress.complete
                else latest_residual.reason
            ),
            residual_target=latest_residual,
            structural_progress=structural_progress,
        )

    def primitive(
        state: SpiderState,
        current: StrategicMilestone,
        nodes_left: int,
        _steps_left: int,
        seconds_left: float,
    ) -> Optional[MilestonePrimitiveStep]:
        nonlocal latest_target_grant_entry, latest_target_boundary_trace
        nonlocal latest_source_satisfactions
        temporary = replace(
            node,
            state=state.clone(),
            analysis=latest_analysis,
            stage0=analyze_stage0_state(
                state, spent_cost=node.g, incumbent_cost=incumbent_cost
            ),
            active_milestone=current,
            active_residual_target=latest_residual,
        )
        candidates: List[StrategicSuccessor] = []
        residual = _residual_target_for_milestone(
            state,
            latest_analysis,
            current,
            config,
            latest_source_satisfactions,
        )
        candidate = residual.next_candidate
        if candidate is not None and candidate.demand.realizer == TacticalRealizerKind.RUN_CONSTRUCTION:
            candidates.extend(
                _construction_successors(
                    temporary,
                    config=config,
                    telemetry=telemetry,
                    started=started,
                    resource_allocator=resource_allocator,
                    preferred_opportunity_id=candidate.construction_opportunity_id,
                    target_demand=candidate.demand,
                )
            )
        elif candidate is not None and candidate.demand.realizer == TacticalRealizerKind.DEPENDENCY_CLOSURE:
            closure, _result = _dependency_closure_successors(
                temporary,
                config=config,
                telemetry=telemetry,
                deadline=deadline,
                started=started,
                cache=dependency_closure_cache,
                resource_allocator=resource_allocator,
                target_demand=candidate.demand,
            )
            candidates.extend(closure)
        elif (
            current.kind == StrategicMilestoneKind.FOUNDATION_REMOVAL
            or candidate is not None
            and candidate.demand.realizer == TacticalRealizerKind.TERMINAL_ASSEMBLY
        ):
            candidates.extend(
                _foundation_successors(
                    temporary,
                    cards,
                    config=config,
                    telemetry=telemetry,
                    started=started,
                    deadline=deadline,
                    resource_allocator=resource_allocator,
                )
            )
        candidates = [
            item
            for item in candidates
            if item.actions
            and item.independent_replay_verified
            and item.tactical_nodes <= nodes_left
        ]
        if not candidates:
            return None
        chosen = min(
            candidates,
            key=lambda item: (
                0 if item.source_project_id == current.campaign_id else 1,
                item.corrected_cost,
                -len(item.actions),
                item.label,
            ),
        )
        if chosen.target_grant_entry is not None:
            latest_target_grant_entry = chosen.target_grant_entry
            latest_target_boundary_trace = chosen.target_boundary_trace
        if chosen.source_completion_traces:
            merged = {
                item.requirement.identity_key: item
                for item in latest_source_satisfactions
            }
            for trace in chosen.source_completion_traces:
                merged[trace.event.satisfaction.requirement.identity_key] = (
                    trace.event.satisfaction
                )
            latest_source_satisfactions = list(merged.values())
        workspace_created = False
        workspace_used = False
        workspace_recovered = False
        closure_result = chosen.dependency_closure_result
        if current.kind == StrategicMilestoneKind.WORKSPACE_LIFECYCLE:
            before_empty = sum(column.is_empty() for column in state.columns)
            after_empty = sum(column.is_empty() for column in chosen.end_state.columns)
            closed_workspace = bool(
                closure_result is not None
                and any(
                    item.kind == CampaignDependencyType.WORKSPACE_REQUIRED
                    for item in closure_result.graph_before.dependencies
                )
                and not any(
                    item.kind == CampaignDependencyType.WORKSPACE_REQUIRED
                    for item in closure_result.graph_after.dependencies
                )
            )
            workspace_created = after_empty > before_empty
            workspace_used = bool(
                (current.progress.workspace_created and chosen.actions)
                or (workspace_created and len(chosen.actions) >= 2)
            )
            workspace_recovered = bool(
                (
                    current.progress.workspace_used
                    or (workspace_created and len(chosen.actions) >= 2)
                )
                and (after_empty >= before_empty or closed_workspace)
            )
        return MilestonePrimitiveStep(
            chosen.actions,
            chosen.end_state.clone(),
            chosen.corrected_cost,
            chosen.tactical_nodes,
            (chosen.label,),
            chosen.independent_replay_verified,
            chosen.label,
            workspace_created=workspace_created,
            workspace_used=workspace_used,
            workspace_recovered_or_replaced=workspace_recovered,
            target_dependency_id=(
                closure_result.target_dependency_id if closure_result is not None else None
            ),
            semantic_target_id=(
                closure_result.buried_source_traces[0].semantic_target_id
                if closure_result is not None and closure_result.buried_source_traces
                else current.target_identity.fingerprint
                if current.target_identity is not None
                else None
            ),
            closure_completion_class=(
                closure_result.completion_class.value
                if closure_result is not None
                else None
            ),
            closure_requested_dependency_completed=bool(
                closure_result is not None
                and closure_result.endpoint_assessment is not None
                and closure_result.endpoint_assessment.requested_dependency_completed
            ),
            closure_advanced_fallback=bool(
                closure_result is not None and closure_result.advanced_fallback_returned
            ),
            closure_source_depth_before=(
                closure_result.endpoint_assessment.source_depth_before
                if closure_result is not None and closure_result.endpoint_assessment is not None
                else None
            ),
            closure_source_depth_after=(
                closure_result.endpoint_assessment.source_depth_after
                if closure_result is not None and closure_result.endpoint_assessment is not None
                else None
            ),
            closure_primitive_count=(
                len(closure_result.steps) if closure_result is not None else 0
            ),
            restore_replace_obligation=(
                closure_result.endpoint_assessment.lifecycle.restore_replace_obligation
                if closure_result is not None and closure_result.endpoint_assessment is not None
                else None
            ),
            source_completion_events=tuple(
                trace.event for trace in chosen.source_completion_traces
            ),
            source_completion_traces=chosen.source_completion_traces,
        )

    result = realize_milestone(
        node.state,
        active,
        primitive,
        analyze_fresh,
        max_primitive_steps=config.milestone_max_primitive_steps,
        max_tactical_nodes=min(
            config.milestone_max_nodes_per_expansion,
            max(0, config.max_tactical_nodes - telemetry.tactical_nodes),
        ),
        time_limit_s=min(
            config.milestone_max_time_s_per_expansion,
            max(0.01, deadline.remaining_wall_time),
        ),
    )
    telemetry.milestone_conversion_seconds += result.elapsed_seconds
    telemetry.milestone_conversion_nodes += result.tactical_nodes
    telemetry.milestone_primitive_steps += result.primitive_steps
    telemetry.closure_advanced_persisted_across_expansions += (
        result.same_target_continuations
    )
    telemetry.closure_persisted_targets_completed += int(
        result.persisted_target_completed
    )
    if result.outcome_kind == MilestoneOutcomeKind.PRIMITIVE_RESULT:
        telemetry.primitive_results += 1
    elif result.outcome_kind == MilestoneOutcomeKind.TRANSITION_CHECKPOINT:
        telemetry.transition_checkpoints += 1
    elif result.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE:
        telemetry.substantial_structural_milestones += 1
    elif result.outcome_kind == MilestoneOutcomeKind.FOUNDATION:
        telemetry.substantial_structural_milestones += 1
    status_counts = {
        StrategicMilestoneStatus.ADVANCED: "milestones_advanced",
        StrategicMilestoneStatus.ACHIEVED: "milestones_achieved",
        StrategicMilestoneStatus.REPLANNED: "milestones_replanned",
        StrategicMilestoneStatus.INVALIDATED: "milestones_invalidated",
        StrategicMilestoneStatus.SUPERSEDED: "milestones_superseded",
        StrategicMilestoneStatus.EXPIRED: "milestones_expired",
        StrategicMilestoneStatus.BOUNDED_MISS: "milestone_bounded_misses",
    }
    field_name = status_counts.get(result.status)
    if field_name is not None:
        setattr(telemetry, field_name, getattr(telemetry, field_name) + 1)
    if result.status == StrategicMilestoneStatus.ACHIEVED:
        harvest_field = {
            StrategicMilestoneKind.INTERVAL_ASSEMBLY: "milestone_intervals_completed",
            StrategicMilestoneKind.SOURCE_CHAIN: "milestone_source_chains_completed",
            StrategicMilestoneKind.SUPPLY_INTEGRATION: "milestone_supply_completed",
            StrategicMilestoneKind.WORKSPACE_LIFECYCLE: "milestone_workspace_lifecycles_completed",
            StrategicMilestoneKind.PRE_DEAL_PREPARATION: "milestone_predeal_completed",
            StrategicMilestoneKind.TERMINAL_QUALIFICATION: "milestone_terminal_qualifications",
            StrategicMilestoneKind.FOUNDATION_REMOVAL: "milestone_foundations",
        }.get(result.milestone.kind)
        if harvest_field is not None:
            setattr(telemetry, harvest_field, getattr(telemetry, harvest_field) + 1)
        if result.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE:
            substantial_field = {
                StrategicMilestoneKind.INTERVAL_ASSEMBLY: "substantial_interval_completions",
                StrategicMilestoneKind.SOURCE_CHAIN: "substantial_source_chain_completions",
                StrategicMilestoneKind.RECEIVER_GEOMETRY: "substantial_receiver_lifecycles",
                StrategicMilestoneKind.SUPPLY_INTEGRATION: "substantial_supply_integrations",
                StrategicMilestoneKind.WORKSPACE_LIFECYCLE: "substantial_workspace_lifecycles",
                StrategicMilestoneKind.TERMINAL_QUALIFICATION: "substantial_terminal_qualifications",
            }.get(result.milestone.kind)
            if substantial_field is not None:
                setattr(telemetry, substantial_field, getattr(telemetry, substantial_field) + 1)
    telemetry.blocker_type_transitions += len(result.blocker_transitions)
    for trace in result.source_completion_traces:
        _record_source_completion_trace(
            telemetry, trace, config.max_timeline_entries
        )
    _append_bounded(
        telemetry.milestone_timeline,
        (
            node.g,
            result.milestone.milestone_id,
            result.milestone.kind.value,
            result.status.value,
            result.primitive_steps,
            result.corrected_paid_cost,
        ),
        config.max_timeline_entries,
    )
    if not result.actions or not result.independent_replay_verified:
        return []
    return [
        StrategicSuccessor(
            StrategicActionKind.MILESTONE_CONVERSION,
            "milestone_conversion",
            f"{result.milestone.kind.value.lower()} {result.status.value.lower()}",
            result.actions,
            result.corrected_paid_cost,
            result.end_state.clone(),
            node.credit_level,
            result.milestone.estimated_paid_cost,
            result.corrected_paid_cost,
            result.tactical_nodes,
            True,
            False,
            (
                result.reason,
                f"fresh_reanalyses={result.fresh_reanalyses}",
                "milestone context is ordering-only and absent from exact TT identity",
            ),
            source_project_id=result.milestone.objective_id,
            milestone_result=result,
            residual_target=latest_residual,
            target_grant_entry=latest_target_grant_entry,
            target_boundary_trace=latest_target_boundary_trace,
            source_completion_traces=result.source_completion_traces,
        )
    ]


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
    dependency_closure_cache: Optional[DependencyClosureCache] = None,
    resource_allocator: Optional[TacticalResourceAllocator] = None,
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
    allocator = resource_allocator or _resource_allocator_for_config(config)
    if resource_allocator is None:
        allocator.begin_expansion()
    allowed = set(allowed_frontier_tiers(node.credit_level))

    if analysis.milestone_portfolio is not None:
        telemetry.milestones_admitted += len(analysis.milestone_portfolio.milestones)
        for kind, count in analysis.milestone_portfolio.generated_by_kind:
            telemetry.milestones_generated_by_kind[kind] = (
                telemetry.milestones_generated_by_kind.get(kind, 0) + count
            )
        blocked_milestones = tuple(
            item for item in analysis.milestone_portfolio.milestones
            if item.status == StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH
        )
        telemetry.epoch_feasible_milestones += (
            len(analysis.milestone_portfolio.milestones) - len(blocked_milestones)
        )
        telemetry.epoch_stock_blocked_milestones += len(blocked_milestones)
        telemetry.milestones_stock_blocked += len(blocked_milestones)
        for item in blocked_milestones:
            epoch = (
                item.epoch_feasibility.earliest_feasible_epoch
                if item.epoch_feasibility is not None else None
            )
            if epoch is not None:
                telemetry.earliest_required_future_epochs[epoch] = (
                    telemetry.earliest_required_future_epochs.get(epoch, 0) + 1
                )
        if node.active_milestone is None and analysis.milestone_portfolio.plan.primary is not None:
            telemetry.milestones_activated += 1
    if analysis.epoch_transition is not None:
        telemetry.predeal_must_items += sum(
            item.disposition == PreDealWorkDisposition.MUST_BEFORE_DEAL
            for item in analysis.epoch_transition.work_items
        )
        telemetry.predeal_should_items += sum(
            item.disposition == PreDealWorkDisposition.SHOULD_BEFORE_DEAL
            for item in analysis.epoch_transition.work_items
        )
        telemetry.predeal_free_join_deferrals += len(analysis.epoch_transition.free_future_joins)
        telemetry.predeal_avoided_actions += len(analysis.epoch_transition.surrendered_opportunities)

    raw.extend(
        _milestone_conversion_successors(
            node,
            cards,
            incumbent_cost=incumbent_cost,
            config=config,
            telemetry=telemetry,
            started=started,
            analysis_cache=analysis_cache,
            deadline=shared_deadline,
            dependency_closure_cache=dependency_closure_cache,
            resource_allocator=allocator,
        )
    )

    # Whole-deal construction is a first-class strategic family.  Its best
    # late-removal opportunity is retained alongside nearer removal work.
    raw.extend(
        _construction_successors(
            node,
            config=config,
            telemetry=telemetry,
            started=started,
            resource_allocator=allocator,
        )
    )

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

    # 2. A previously supplied/protected named objective receives one bounded
    # same-epoch closure opportunity before any new stock row is considered.
    closure_successors, closure_offer = _dependency_closure_successors(
        node,
        config=config,
        telemetry=telemetry,
        deadline=shared_deadline,
        started=started,
        cache=dependency_closure_cache,
        resource_allocator=allocator,
    )
    raw.extend(closure_successors)

    # 3. Foundation-oriented work receives a protected bounded opportunity.
    raw.extend(
        _foundation_successors(
            node,
            cards,
            config=config,
            telemetry=telemetry,
            started=started,
            deadline=shared_deadline,
            resource_allocator=allocator,
            closure_offer=closure_offer,
        )
    )

    # 4. The multi-epoch hypothesis is protected before generic Deal/raw
    # families.  The campaign suit/copy comes only from the live portfolio.
    corridor_successors = _campaign_corridor_successors(
        node,
        cards,
        config=config,
        telemetry=telemetry,
        deadline=shared_deadline,
        resource_allocator=allocator,
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
        deal_demand = _resource_demand(
            node,
            TacticalRealizerKind.DEAL_TIMING,
        )
        _deal_request, deal_grant = allocator.request(
            canonical_state_key(node.state), deal_demand
        )
        if deal_grant is None:
            telemetry.optional_analyses_skipped += 1
        elif deal_grant.tier < TacticalResourceTier.COMMITTED:
            deal_probe_started = time.perf_counter()
            concrete_unlocks = _probe_exact_deal_unlocks(node)
            _record_tactical_transition(
                allocator,
                deal_grant,
                node,
                node.state,
                nodes_consumed=0,
                seconds_consumed=time.perf_counter() - deal_probe_started,
                corrected_paid_cost=0,
                legal_successor_count=1,
                concrete_deal_unlocks=concrete_unlocks,
                reason=(
                    "exact incoming-row Deal probe; deeper counterfactual analysis "
                    "requires COMMITTED promotion"
                ),
            )
        else:
            limited_deal_config = replace(
                config.deal_timing_config,
                tactical_max_cost=min(
                    config.deal_timing_config.tactical_max_cost,
                    deal_grant.max_added_cost,
                ),
                tactical_max_nodes=min(
                    config.deal_timing_config.tactical_max_nodes,
                    deal_grant.nodes_granted,
                ),
                tactical_time_limit_s=min(
                    config.deal_timing_config.tactical_time_limit_s,
                    deal_grant.seconds_granted,
                ),
                downstream_max_cost=min(
                    config.deal_timing_config.downstream_max_cost,
                    deal_grant.max_added_cost,
                ),
                downstream_max_nodes=min(
                    config.deal_timing_config.downstream_max_nodes,
                    deal_grant.nodes_granted,
                ),
                downstream_time_limit_s=min(
                    config.deal_timing_config.downstream_time_limit_s,
                    deal_grant.seconds_granted,
                ),
            )
            allocation_config = replace(
                config,
                deal_timing_config=limited_deal_config,
            )
            deal_call_started = time.perf_counter()
            try:
                optional = analyze_strategic_state(
                    node.state,
                    cards,
                    spent_cost=node.g,
                    incumbent_cost=incumbent_cost,
                    config=allocation_config,
                    include_deal_timing=True,
                    analysis_cache=analysis_cache,
                    telemetry=telemetry,
                    deadline=shared_deadline,
                    supply_consumptions=node.supply_consumption_results,
                    continuation_objective_id=(
                        node.continuation_credit.objective_id
                        if node.continuation_credit is not None
                        and node.continuation_credit.is_live
                        else None
                    ),
                )
            except AnalysisResourceLimit:
                telemetry.optional_analyses_skipped += 1
                optional = None
            deal_elapsed = time.perf_counter() - deal_call_started
            _record_tactical_transition(
                allocator,
                deal_grant,
                node,
                node.state,
                nodes_consumed=0,
                seconds_consumed=deal_elapsed,
                corrected_paid_cost=0,
                legal_successor_count=(
                    len(order_deal_timing_arms(optional.deal_timing))
                    if optional is not None and optional.deal_timing is not None
                    else 0
                ),
                reason="bounded exact Deal timing analysis",
            )
            if optional is not None and optional.deal_timing is not None:
                analysis = optional
                telemetry.stage2_analyses += 1
    elif analysis.deal_timing is None and node.state.can_deal(MW_RULES):
        telemetry.optional_analyses_skipped += 1

    # 5. Deal is admitted as a first-class legal successor before probes.  Its
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
    purposeful = analysis.epoch_transition
    if (
        purposeful is not None
        and purposeful.status == EpochTransitionStatus.PREPARATION_REQUIRED
    ):
        actions_since_deal = 0
        for prior_action in reversed(node.actions):
            if prior_action == ("deal",):
                break
            actions_since_deal += 1
        if actions_since_deal >= config.milestone_max_primitive_steps:
            purposeful = assess_epoch_transition(
                node.state,
                analysis.campaign_epoch_availability,
                purposeful.work_items,
                milestone_ids=purposeful.milestone_ids,
                boundedly_exhausted=True,
            )
    if (
        node.state.can_deal(MW_RULES)
        and purposeful is not None
        and purposeful.purposeful_deal_eligible
    ):
        end = node.state.clone()
        cost = end.deal(MW_RULES)
        actions: Tuple[Action, ...] = (("deal",),)
        epoch_milestone = (
            next(
                (
                    item
                    for item in analysis.milestone_portfolio.milestones
                    if item.kind == StrategicMilestoneKind.EPOCH_TRANSITION
                    and (
                        not purposeful.campaign_ids
                        or item.campaign_id in purposeful.campaign_ids
                    )
                ),
                None,
            )
            if analysis.milestone_portfolio is not None
            else None
        )
        epoch_result = None
        persistent_target = None
        if (
            node.active_milestone is not None
            and milestone_is_substantial(node.active_milestone)
            and (
                not purposeful.campaign_ids
                or node.active_milestone.campaign_id in purposeful.campaign_ids
            )
        ):
            persistent_target = node.active_milestone
        if persistent_target is None and analysis.milestone_portfolio is not None:
            persistent_target = next(
                (
                    item
                    for item in analysis.milestone_portfolio.milestones
                    if milestone_is_substantial(item)
                    and item.kind != StrategicMilestoneKind.FOUNDATION_REMOVAL
                    and (
                        not purposeful.campaign_ids
                        or item.campaign_id in purposeful.campaign_ids
                    )
                ),
                None,
            )
        parent_residual = (
            _residual_target_for_milestone(
                node.state,
                analysis,
                persistent_target,
                config,
                node.source_completion_ledger.satisfactions,
            )
            if persistent_target is not None
            else None
        )
        post_deal_obligation = (
            create_post_deal_obligation(
                epoch_milestone,
                persistent_target,
                purposeful.exact_next_row,
                created_epoch=5 - len(end.stock) // 10,
            )
            if epoch_milestone is not None and persistent_target is not None
            else None
        )
        if epoch_milestone is not None:
            epoch_progress = evaluate_milestone_progress(end, epoch_milestone)
            achieved_epoch = replace(
                epoch_milestone,
                progress=epoch_progress,
                status=StrategicMilestoneStatus.ACHIEVED,
            )
            epoch_result = MilestoneRealizationResult(
                achieved_epoch,
                StrategicMilestoneStatus.ACHIEVED,
                actions,
                cost,
                end.clone(),
                1,
                0,
                0.0,
                _replay_edge(node.state, actions, end, cost),
                1,
                ("purposeful stock epoch advanced",),
                purposeful.purpose,
                outcome_kind=MilestoneOutcomeKind.TRANSITION_CHECKPOINT,
                target_identity=milestone_target_identity(achieved_epoch),
            )
        raw.append(
            StrategicSuccessor(
                StrategicActionKind.DEAL_NOW,
                "milestone_epoch",
                f"purposeful Deal: {purposeful.purpose}",
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
                    purposeful.purpose,
                    f"exact_next_row={' '.join(str(card) for card in purposeful.exact_next_row)}",
                    f"completed_predeal={purposeful.completed_work}",
                    f"deliberately_deferred={purposeful.deliberately_deferred_work}",
                    (
                        f"post_deal_obligation={post_deal_obligation.obligation_id}"
                        if post_deal_obligation is not None
                        else "post_deal_obligation=none"
                    ),
                    "post-Deal residual target must be rebuilt from the exact child",
                ),
                milestone_result=epoch_result,
                epoch_transition=purposeful,
                residual_target=parent_residual,
                post_deal_obligation=post_deal_obligation,
                persistent_target=persistent_target,
            )
        )
        deal_added = True
        telemetry.deal_successors_generated += 1
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

    # Record that the closure capability was offered before every Deal.  This
    # is path audit metadata and does not make the Deal illegal.
    if closure_offer is not None:
        closure_reason = closure_offer.reason
        raw = [
            replace(
                item,
                closure_attempted_before_deal=True,
                closure_result_before_deal=closure_offer.status.value,
                successive_deal_reason=(
                    "bounded same-epoch closure did not remove the need for a stock transition; "
                    + closure_reason
                ),
            )
            if item.kind in _DEAL_ACTION_KINDS
            else item
            for item in raw
        ]

    # 6. Probe only the best scheduled uncertain work, with a separate fixed
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

    # 7. Realization is separately bounded and attempted only for confirmed
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

    # 8. Broader legal tableau fallback appears only at credit level four.
    if raw_fallback_enabled(node.credit_level):
        raw.extend(_raw_move_successors(node))

    scheduler_annotated = _annotate_scheduler_successors(
        node, raw, config, telemetry
    )
    contracted = tuple(
        _ensure_deal_contracts(node, item, config)
        for item in scheduler_annotated
    )
    deduplicated = deduplicate_strategic_successors(contracted)
    retained = retain_diverse_portfolio(
        deduplicated,
        maximum=config.max_successors_per_expansion,
    )
    final = retain_obligation_successors(
        node,
        deduplicated,
        retained,
        maximum=config.max_successors_per_expansion,
    )
    telemetry.closure_successors_admitted += sum(
        item.kind == StrategicActionKind.CAMPAIGN_DEPENDENCY_CLOSURE
        for item in final
    )
    if node.continuation_credit is not None and node.continuation_credit.is_live:
        telemetry.continuation_descendants_retained += sum(
            successor_matches_continuation(item, node.continuation_credit)
            for item in final
        )
    return final


def _milestone_checkpoint_order(node: StrategicSearchNode) -> Tuple[int, int, int, int]:
    epoch_checkpoints = sum(
        item.outcome_kind == MilestoneOutcomeKind.TRANSITION_CHECKPOINT
        or (
            item.status == StrategicMilestoneStatus.ACHIEVED
            and item.milestone.kind == StrategicMilestoneKind.EPOCH_TRANSITION
        )
        for item in node.milestone_ledger.results
    )
    deals = sum(action == ("deal",) for action in node.actions)
    anonymous_deal_debt = max(0, deals - epoch_checkpoints)
    structural_achievements = sum(
        item.outcome_kind in {
            MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
            MilestoneOutcomeKind.FOUNDATION,
        }
        for item in node.milestone_ledger.results
    )
    obligation_debt = sum(
        item.unresolved_actionable for item in node.post_deal_obligations
    )
    # Anonymous Deal debt precedes checkpoint count: more construction harvest
    # cannot launder a Deal taken before its exact preparation/purpose gate.
    # The binary epoch rank prevents both epoch-0 stagnation and stock racing:
    # one deliberate transition is recognized, additional rows are not a score.
    return (
        anonymous_deal_debt,
        0 if epoch_checkpoints else 1,
        obligation_debt,
        -structural_achievements,
    )


def _contextual_milestone_completion(
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
) -> StrategicSuccessor:
    """Recognize a scoped parent target on its cheaper exact-state route.

    This annotation is added before exact TT admission and never changes the
    structural key or g dominance.  It prevents a more expensive conversion
    wrapper from being the only route that can describe an already explicit
    coherent interval/foundation target.
    """

    if (
        successor.milestone_result is not None
        or successor.kind in _DEAL_ACTION_KINDS
        or node.analysis is None
        or node.analysis.milestone_portfolio is None
    ):
        return successor
    for milestone in node.analysis.milestone_portfolio.milestones:
        if not milestone_is_substantial(milestone) or milestone.progress.complete:
            continue
        if milestone.target.kind not in {
            MilestonePredicateKind.SAME_SUIT_INTERVAL,
            MilestonePredicateKind.DURABLE_RUN,
            MilestonePredicateKind.FOUNDATION_COUNT,
        }:
            continue
        progress = evaluate_milestone_progress(successor.end_state, milestone)
        if not progress.complete:
            continue
        completed = replace(
            milestone,
            target_identity=milestone_target_identity(milestone),
            progress=progress,
            status=StrategicMilestoneStatus.ACHIEVED,
        )
        result = MilestoneRealizationResult(
            completed,
            StrategicMilestoneStatus.ACHIEVED,
            successor.actions,
            successor.corrected_cost,
            successor.end_state.clone(),
            1,
            successor.tactical_nodes,
            0.0,
            successor.independent_replay_verified,
            1,
            (successor.label,),
            "cheaper exact-state route completed an explicit parent semantic target",
            outcome_kind=classify_milestone_outcome(
                completed, StrategicMilestoneStatus.ACHIEVED
            ),
            target_identity=milestone_target_identity(completed),
        )
        return replace(successor, milestone_result=result)
    return successor


def strategic_progress_order_key(node: StrategicSearchNode) -> Tuple:
    """Return the inspectable heuristic order; stock epoch is absent."""
    if node.analysis is None:
        if node.stage0 is None:
            raise ValueError("lazy node lacks required Stage-0 analysis")
        # Foundation count leads this exact/cheap admission order.  Stock
        # count/epoch is intentionally absent, matching the full order.
        base = node.stage0.ordering_key()
        return base[:1] + _milestone_checkpoint_order(node) + base[1:]
    progress_key = node.analysis.progress.ordering_key()
    delta = node.incoming_edge.progress_delta if node.incoming_edge is not None else None
    deal_delta_key = (
        delta.deal_ordering_key()
        if delta is not None
        and node.incoming_edge is not None
        and node.incoming_edge.kind in _DEAL_ACTION_KINDS
        else (0,) * 11
    )
    timing_priority = (
        node.incoming_edge.deal_timing_priority
        if node.incoming_edge is not None
        else 0
    )
    purpose_debt_penalty = (
        node.incoming_edge.purpose_debt_penalty
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
    combined = (
        progress_key[:5]
        + (deal_required_rank,)
        + progress_key[5:]
        + deal_delta_key
        + (timing_priority, purpose_debt_penalty)
    )
    return combined[:4] + _milestone_checkpoint_order(node) + combined[4:]


def _node_priority(node: StrategicSearchNode) -> Tuple:
    base = strategic_progress_order_key(node)
    cash_out = node.completion_cash_out
    completion_reservation = (
        0
        if cash_out is not None
        and cash_out.status == CompletionCashOutStatus.RESERVED
        and not cash_out.cash_out_spent
        else 1,
    )
    epoch_transition = node.epoch_transition_opportunity
    epoch_transition_reservation = (
        0
        if epoch_transition is not None
        and epoch_transition.status == EpochTransitionRepresentativeStatus.RESERVED
        else 1,
    )
    bounded_representative = (
        0
        if completion_reservation == (0,)
        else 1
        if epoch_transition_reservation == (0,)
        else 2,
    )
    scheduled = (
        node.incoming_edge.scheduled_objective
        if node.incoming_edge is not None else None
    )
    scheduler_continuity = (
        node.incoming_edge.scheduler_effect_rank
        if scheduled is not None and node.incoming_edge is not None
        else 3,
        scheduled.ordering_key() if scheduled is not None else (9,),
    )
    credit = node.continuation_credit
    continuity = (
        0 if credit is not None and credit.is_live else 1,
        credit.ordering_key() if credit is not None else (1, 0, 0, 0, ""),
    )
    milestone = node.active_milestone
    residual_target = node.active_residual_target
    milestone_continuity = (
        0
        if residual_target is not None
        and residual_target.status == ResidualTargetStatus.ACTIONABLE
        else 1
        if milestone is not None
        and milestone.status in (
            StrategicMilestoneStatus.ACTIVE,
            StrategicMilestoneStatus.ADVANCED,
        )
        else 2,
        0 if milestone is not None and milestone_is_substantial(milestone) else 1,
        milestone.ordering_key() if milestone is not None else (1, 1, 1, 0, 0, 0, "", ""),
    )
    # Preserve solved/foundation precedence, then give at most one typed
    # completion or epoch-transition representative its promised ordinary
    # expansion. Completion wins a direct representative conflict. Lazy
    # Stage-0 nodes expose foundation count first; full analyses expose
    # solved/realized/removal/foundation first.
    # Foundation precedence and milestone checkpoint audit come first. A live
    # same-target continuation may not outrank a completed purposeful Deal or
    # launder anonymous Deal debt.
    continuity_index = 4 if node.analysis is None else 7
    representative_index = 1 if node.analysis is None else 4
    # Scheduler intent ranks otherwise comparable exact states.  It follows
    # the established structural, milestone and bounded-continuation order so
    # that a fresh receding-horizon target cannot become a compulsory script.
    return base[:representative_index] + bounded_representative + base[representative_index:continuity_index] + milestone_continuity + continuity + base[continuity_index:] + scheduler_continuity + (
        int(node.credit_level),
        node.depth,
        node.node_id,
    )


def _better_progress(candidate: StrategicSearchNode, incumbent: StrategicSearchNode) -> bool:
    return strategic_progress_order_key(candidate) < strategic_progress_order_key(incumbent)


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


def _record_source_completion_trace(
    telemetry: ControllerTelemetry,
    trace: SourceCompletionPropagationTrace,
    maximum: int,
) -> None:
    """Record each event/stage once even when the exact state is reanalysed."""

    propagation_started = time.perf_counter()
    existing_index = next(
        (
            index
            for index, item in enumerate(telemetry.source_completion_traces)
            if item.event.event_id == trace.event.event_id
        ),
        None,
    )
    previous = (
        telemetry.source_completion_traces[existing_index]
        if existing_index is not None
        else None
    )
    effective_loss = trace.loss_reason
    if (
        effective_loss == SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS
        and previous is not None
        and previous.controller_admitted
    ):
        effective_loss = None
    admission_recovered = bool(
        previous is not None
        and previous.loss_reason == SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS
        and trace.controller_admitted
    )
    if admission_recovered:
        name = SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS.value
        remaining = telemetry.source_completion_loss_classifications.get(name, 0) - 1
        if remaining > 0:
            telemetry.source_completion_loss_classifications[name] = remaining
        else:
            telemetry.source_completion_loss_classifications.pop(name, None)
    old_stages = set(previous.stages if previous is not None else ())
    new_stages = set(trace.stages) - old_stages
    counters = {
        SourceCompletionStage.TRACE_COMPLETED: "source_trace_completions",
        SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED: "source_successors_created",
        SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION: "source_controller_admitted_completions",
        SourceCompletionStage.FRESH_RESIDUAL_PRESERVED: "source_fresh_residual_preserved",
        SourceCompletionStage.LINEAGE_PRESERVED: "source_lineage_preserved",
        SourceCompletionStage.SELECTED_PATH_COMPLETION: "source_selected_path_completions",
        SourceCompletionStage.SOURCE_CONSUMED: "source_completion_consumptions",
        SourceCompletionStage.SOURCE_INTEGRATED: "source_completion_integrations",
    }
    suit_row = telemetry.source_completion_by_suit.setdefault(
        trace.event.physical_source.suit, {}
    )
    for stage in new_stages:
        field_name = counters[stage]
        setattr(telemetry, field_name, getattr(telemetry, field_name) + 1)
        suit_row[stage.value] = suit_row.get(stage.value, 0) + 1
    if trace.copy_reassigned and not bool(previous and previous.copy_reassigned):
        telemetry.source_copy_reassignments += 1
    if trace.reopening_reason is not None and not bool(
        previous and previous.reopening_reason is not None
    ):
        telemetry.source_residual_reopenings += 1
    if effective_loss is not None and not bool(
        previous and previous.loss_reason == effective_loss
    ):
        name = effective_loss.value
        telemetry.source_completion_loss_classifications[name] = (
            telemetry.source_completion_loss_classifications.get(name, 0) + 1
        )
    if previous is not None:
        merged_stages = previous.stages + tuple(
            item for item in trace.stages if item not in old_stages
        )
        merged = replace(
            trace,
            stages=merged_stages,
            disposition=(
                previous.disposition
                if not new_stages
                and effective_loss is None
                and trace.reopening_reason is None
                else trace.disposition
            ),
            successor_created=(previous.successor_created or trace.successor_created),
            controller_admitted=(previous.controller_admitted or trace.controller_admitted),
            residual_preserved=(previous.residual_preserved or trace.residual_preserved),
            lineage_preserved=(previous.lineage_preserved or trace.lineage_preserved),
            selected_path=(previous.selected_path or trace.selected_path),
            copy_reassigned=(previous.copy_reassigned or trace.copy_reassigned),
            later_consumed=(previous.later_consumed or trace.later_consumed),
            later_integrated=(previous.later_integrated or trace.later_integrated),
            loss_reason=(
                None
                if admission_recovered
                else effective_loss or previous.loss_reason
            ),
            reopening_reason=(trace.reopening_reason or previous.reopening_reason),
            detail=(
                trace.detail
                if new_stages
                or effective_loss is not None
                or trace.reopening_reason is not None
                else previous.detail
            ),
        )
        telemetry.source_completion_traces[existing_index] = merged
    else:
        _append_bounded(telemetry.source_completion_traces, trace, maximum)
    telemetry.source_completion_propagation_seconds += (
        time.perf_counter() - propagation_started
    )


def _completion_structural_metrics(
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
    child_stage0: Stage0AnalysisSnapshot,
    admitted_traces: Sequence[SourceCompletionPropagationTrace],
    *,
    corrected_g: int,
) -> CompletionStructuralMetrics:
    """Expose completion economics without introducing a completion bonus."""

    events = tuple({item.event.event_id: item.event for item in admitted_traces}.values())
    delta = successor.progress_delta
    closure = successor.dependency_closure_result
    milestone = successor.milestone_result
    dependency_reduction = max(
        0,
        delta.critical_dependencies_removed if delta is not None else 0,
        len(closure.dependencies_closed) if closure is not None else 0,
    )
    receiver_unlocks = max(
        0,
        delta.exact_receiver_successes if delta is not None else 0,
        int(
            milestone is not None
            and milestone.milestone.kind == StrategicMilestoneKind.RECEIVER_GEOMETRY
            and milestone.status == StrategicMilestoneStatus.ACHIEVED
        ),
    )
    terminal_readiness = int(
        len(successor.end_state.foundations) > len(node.state.foundations)
        or (
            milestone is not None
            and milestone.milestone.kind
            in {
                StrategicMilestoneKind.TERMINAL_QUALIFICATION,
                StrategicMilestoneKind.FOUNDATION_REMOVAL,
            }
            and milestone.status == StrategicMilestoneStatus.ACHIEVED
        )
    )
    substantial = int(
        milestone is not None
        and milestone.outcome_kind
        in {
            MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
            MilestoneOutcomeKind.FOUNDATION,
        }
    )
    return CompletionStructuralMetrics(
        corrected_g,
        child_stage0.foundation_count,
        child_stage0.stable_same_suit_joins,
        child_stage0.mixed_suit_boundaries,
        len(events),
        sum(item.actionable or item.exposed for item in events),
        sum(item.consumed for item in events),
        sum(item.integrated for item in events),
        dependency_reduction,
        receiver_unlocks,
        len(child_stage0.empty_columns),
        child_stage0.face_down_count,
        max(0, node.stage0.face_down_count - child_stage0.face_down_count)
        if node.stage0 is not None
        else 0,
        child_stage0.stock_count,
        successor.deal_timing_priority,
        child_stage0.rehandling_debt,
        terminal_readiness,
        substantial,
        child_stage0.legal_move_count,
    )


def _completion_trace_index(
    telemetry: ControllerTelemetry, opportunity_id: str
) -> Optional[int]:
    return next(
        (
            index
            for index, item in enumerate(telemetry.completion_selection_traces)
            if item.opportunity_id == opportunity_id
        ),
        None,
    )


def _record_completion_opportunity(
    telemetry: ControllerTelemetry,
    opportunity: CompletionCashOutOpportunity,
    maximum: int,
) -> None:
    if _completion_trace_index(telemetry, opportunity.opportunity_id) is not None:
        return
    trace = CompletionCashOutTrace(
        opportunity.opportunity_id,
        opportunity.event_ids,
        opportunity.semantic_targets,
        opportunity.exact_state_key,
        opportunity.exact_state_hash,
        opportunity.corrected_g,
        opportunity.successor_family,
        opportunity.metrics,
        opportunity.status,
        opportunity.representative_rank,
        opportunity.competing_normal_state_hash,
        opportunity.competing_normal_g,
        True,
        False,
        False,
        False,
        CompletionCashOutDisposition.QUALIFIED,
        opportunity.reason,
    )
    _append_bounded(telemetry.completion_selection_traces, trace, maximum)


def _update_completion_trace(
    telemetry: ControllerTelemetry,
    opportunity: CompletionCashOutOpportunity,
    **changes,
) -> None:
    index = _completion_trace_index(telemetry, opportunity.opportunity_id)
    if index is None:
        return
    telemetry.completion_selection_traces[index] = (
        telemetry.completion_selection_traces[index].update(
            opportunity=opportunity,
            **changes,
        )
    )


def _reserve_completion_representative(
    frontier: Sequence[Tuple[Tuple, int, StrategicSearchNode]],
    *,
    tt: StrategicTranspositionTable,
    spent_event_ids: Sequence[str],
    telemetry: ControllerTelemetry,
) -> List[Tuple[Tuple, int, StrategicSearchNode]]:
    """Reserve at most one already-admitted completion inside current width."""

    selection_started = time.perf_counter()
    eligible_nodes = []
    superseded_by_id = {}
    for _priority, _uid, node in frontier:
        opportunity = node.completion_cash_out
        if opportunity is None or not opportunity.eligible(spent_event_ids):
            continue
        best_g = tt.best_g(opportunity.exact_state_key)
        if best_g is not None and node.g > best_g:
            if opportunity.status != CompletionCashOutStatus.SUPERSEDED:
                superseded = replace(
                    opportunity,
                    status=CompletionCashOutStatus.SUPERSEDED,
                    reason="a lower-g identical exact state superseded this completion arrival",
                )
                _update_completion_trace(
                    telemetry,
                    superseded,
                    disposition=CompletionCashOutDisposition.SUPERSEDED_BY_LOWER_G,
                    reason=superseded.reason,
                )
                telemetry.completion_invalidated_representatives += 1
                superseded_by_id[opportunity.opportunity_id] = superseded
            continue
        eligible_nodes.append((node, opportunity))
    ranked = rank_completion_opportunities(
        tuple(item[1] for item in eligible_nodes),
        spent_event_ids=spent_event_ids,
    )
    ranked_by_id = {item.opportunity_id: item for item in ranked}
    chosen = ranked[0] if ranked else None
    normal = next(
        (
            item[2]
            for item in sorted(frontier)
            if item[2].completion_cash_out is None
            or not item[2].completion_cash_out.eligible(spent_event_ids)
        ),
        None,
    )
    rebuilt = []
    for _priority, uid, node in frontier:
        opportunity = node.completion_cash_out
        if (
            opportunity is not None
            and opportunity.opportunity_id in superseded_by_id
        ):
            updated_node = replace(
                node,
                completion_cash_out=superseded_by_id[opportunity.opportunity_id],
            )
            rebuilt.append((_node_priority(updated_node), uid, updated_node))
            continue
        if opportunity is None or opportunity.opportunity_id not in ranked_by_id:
            rebuilt.append((_node_priority(node), uid, node))
            continue
        ranked_opportunity = ranked_by_id[opportunity.opportunity_id]
        is_chosen = bool(
            chosen is not None
            and ranked_opportunity.opportunity_id == chosen.opportunity_id
        )
        status = (
            CompletionCashOutStatus.RESERVED
            if is_chosen
            else CompletionCashOutStatus.QUALIFIED
        )
        updated = replace(
            ranked_opportunity,
            status=status,
            competing_normal_state_hash=(
                _state_hash(normal.state) if normal is not None else None
            ),
            competing_normal_g=(normal.g if normal is not None else None),
            reason=(
                "strongest qualifying completion reserved for one ordinary fresh expansion"
                if is_chosen
                else "another qualifying completion has the stronger bounded representative rank"
            ),
        )
        if is_chosen and opportunity.status != CompletionCashOutStatus.RESERVED:
            telemetry.completion_representatives_reserved += 1
        _update_completion_trace(
            telemetry,
            updated,
            disposition=(
                CompletionCashOutDisposition.REPRESENTATIVE_RESERVED
                if is_chosen
                else CompletionCashOutDisposition.QUALIFIED
            ),
            reason=updated.reason,
        )
        updated_node = replace(node, completion_cash_out=updated)
        rebuilt.append((_node_priority(updated_node), uid, updated_node))
    heapq.heapify(rebuilt)
    telemetry.completion_selection_seconds += time.perf_counter() - selection_started
    return rebuilt


def _reserve_epoch_transition_representative(
    frontier: Sequence[Tuple[Tuple, int, StrategicSearchNode]],
    *,
    tt: StrategicTranspositionTable,
    spent_opportunity_ids: Sequence[str],
    telemetry: ControllerTelemetry,
) -> List[Tuple[Tuple, int, StrategicSearchNode]]:
    """Reserve one exact-TT-admitted Deal child inside existing capacity."""

    started = time.perf_counter()
    spent = set(spent_opportunity_ids)
    eligible = []
    superseded = {}
    for _priority, _uid, node in frontier:
        opportunity = node.epoch_transition_opportunity
        if opportunity is None or not opportunity.eligible(spent):
            continue
        best_g = tt.best_g(node.state)
        if best_g is not None and node.g > best_g:
            superseded[opportunity.opportunity_id] = replace(
                opportunity,
                status=EpochTransitionRepresentativeStatus.SUPERSEDED,
            )
            telemetry.scheduler_transition_superseded += 1
            continue
        eligible.append((node, opportunity))
    eligible.sort(key=lambda item: item[1].ordering_key())
    chosen = eligible[0][1] if eligible else None
    eligible_ids = {item[1].opportunity_id for item in eligible}
    previously_reserved = {
        item[2].epoch_transition_opportunity.opportunity_id
        for item in frontier
        if item[2].epoch_transition_opportunity is not None
        and item[2].epoch_transition_opportunity.status
        == EpochTransitionRepresentativeStatus.RESERVED
    }
    rebuilt = []
    for _priority, uid, node in frontier:
        opportunity = node.epoch_transition_opportunity
        if opportunity is None:
            rebuilt.append((_node_priority(node), uid, node))
            continue
        if opportunity.opportunity_id in superseded:
            updated_node = replace(
                node,
                epoch_transition_opportunity=superseded[opportunity.opportunity_id],
            )
            rebuilt.append((_node_priority(updated_node), uid, updated_node))
            continue
        if opportunity.opportunity_id not in eligible_ids:
            rebuilt.append((_node_priority(node), uid, node))
            continue
        is_chosen = bool(
            chosen is not None and opportunity.opportunity_id == chosen.opportunity_id
        )
        updated = replace(
            opportunity,
            status=(
                EpochTransitionRepresentativeStatus.RESERVED
                if is_chosen
                else EpochTransitionRepresentativeStatus.QUALIFIED
            ),
        )
        if is_chosen and opportunity.opportunity_id not in previously_reserved:
            telemetry.scheduler_transition_representatives_reserved += 1
        updated_node = replace(node, epoch_transition_opportunity=updated)
        rebuilt.append((_node_priority(updated_node), uid, updated_node))
    heapq.heapify(rebuilt)
    telemetry.scheduler_transition_selection_seconds += time.perf_counter() - started
    return rebuilt


def _completion_harvest_assessment(
    opportunity: CompletionCashOutOpportunity,
    node: StrategicSearchNode,
    successor: StrategicSuccessor,
    *,
    admitted: bool,
) -> CompletionHarvestAssessment:
    milestone = successor.milestone_result
    closure = successor.dependency_closure_result
    completed_dependency_ids = {
        event.dependency_id for event in opportunity.events
    }
    matching_source_milestone = bool(
        milestone is not None
        and milestone.milestone.kind == StrategicMilestoneKind.SOURCE_CHAIN
        and milestone.milestone.target_identity is not None
        and milestone.milestone.target_identity.fingerprint
        in opportunity.semantic_targets
    )
    dependency_advance = bool(
        (
            closure is not None
            and closure.target_dependency_id in completed_dependency_ids
            and (closure.dependencies_closed or closure.advanced_states_continued)
        )
        or (
            matching_source_milestone
            and milestone.status
            in {StrategicMilestoneStatus.ADVANCED, StrategicMilestoneStatus.ACHIEVED}
        )
    )
    receiver_unlock = bool(
        (successor.progress_delta is not None and successor.progress_delta.exact_receiver_successes)
        or (
            milestone is not None
            and milestone.milestone.kind == StrategicMilestoneKind.RECEIVER_GEOMETRY
            and milestone.status == StrategicMilestoneStatus.ACHIEVED
        )
    )
    terminal = bool(
        len(successor.end_state.foundations) > len(node.state.foundations)
        or (
            milestone is not None
            and milestone.milestone.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION
            and milestone.status == StrategicMilestoneStatus.ACHIEVED
        )
    )
    epoch_prepared = bool(
        milestone is not None
        and milestone.milestone.kind == StrategicMilestoneKind.PRE_DEAL_PREPARATION
        and milestone.status == StrategicMilestoneStatus.ACHIEVED
    )
    captured_kinds = {
        StrategicMilestoneKind.SOURCE_CHAIN,
        StrategicMilestoneKind.RECEIVER_GEOMETRY,
        StrategicMilestoneKind.PRE_DEAL_PREPARATION,
        StrategicMilestoneKind.TERMINAL_QUALIFICATION,
        StrategicMilestoneKind.FOUNDATION_REMOVAL,
    }
    other_named = bool(
        milestone is not None
        and milestone.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE
        and milestone.milestone.kind not in captured_kinds
    )
    return assess_completion_harvest(
        opportunity,
        node.state,
        successor.end_state,
        downstream_successor_generated=True,
        downstream_successor_admitted=admitted,
        dependency_chain_advanced=dependency_advance,
        receiver_unlocked=receiver_unlock,
        terminal_qualified=terminal,
        epoch_prepared=epoch_prepared,
        other_named_harvest=other_named,
        action_is_deal=any(action == ("deal",) for action in successor.actions),
    )


def _record_completion_harvest(
    telemetry: ControllerTelemetry,
    opportunity: CompletionCashOutOpportunity,
    assessment: CompletionHarvestAssessment,
    maximum: int,
) -> None:
    telemetry.completion_harvest_assessments += 1
    telemetry.completion_source_consumed += len(assessment.source_consumed_event_ids)
    telemetry.completion_source_integrated += len(assessment.source_integrated_event_ids)
    telemetry.completion_no_downstream_harvest += int(not assessment.meaningful)
    for kind in assessment.harvest_kinds:
        telemetry.completion_harvest_by_kind[kind.value] = (
            telemetry.completion_harvest_by_kind.get(kind.value, 0) + 1
        )
    for suit in {item.physical_source.suit for item in opportunity.events}:
        row = telemetry.completion_harvest_by_suit.setdefault(suit, {})
        for kind in assessment.harvest_kinds:
            row[kind.value] = row.get(kind.value, 0) + 1
    telemetry.completion_ordinary_continuations += int(
        assessment.downstream_successor_admitted
    )
    telemetry.completion_branches_abandoned += int(
        not assessment.downstream_successor_admitted
    )
    telemetry.completion_terminal_paths += int(
        CompletionHarvestKind.TERMINAL_QUALIFICATION in assessment.harvest_kinds
        or CompletionHarvestKind.FOUNDATION_REMOVAL in assessment.harvest_kinds
    )
    _append_bounded(telemetry.completion_harvest_rows, assessment, maximum)
    spent = replace(
        opportunity,
        status=CompletionCashOutStatus.SPENT,
        cash_out_spent=True,
        reason=(
            "one bounded cash-out expansion completed; ordinary economics resume"
        ),
    )
    _update_completion_trace(
        telemetry,
        spent,
        disposition=CompletionCashOutDisposition.CASH_OUT_SPENT,
        reason=spent.reason,
        selected_for_expansion=True,
        cash_out_spent=True,
        downstream_result=assessment.harvest_kinds,
    )


def _trim_frontier_with_checkpoint_diversity(
    frontier: Sequence[Tuple[Tuple, int, StrategicSearchNode]],
    *,
    maximum: int,
    portfolio: FoundationCheckpointPortfolio,
    pre_foundation_portfolio: Optional[PreFoundationPortfolio] = None,
    telemetry: Optional[ControllerTelemetry] = None,
) -> List[Tuple[Tuple, int, StrategicSearchNode]]:
    """Protect checkpoint and material pre-foundation geometries."""
    ordered = sorted(frontier)
    protected = {profile.state_key for profile in portfolio.profiles}
    kept = []
    kept_ids = set()
    represented = set()
    # One already-admitted completion representative occupies an existing
    # frontier slot.  It receives no width, resource, or expansion increase.
    completion_item = next(
        (
            item
            for item in ordered
            if item[2].completion_cash_out is not None
            and item[2].completion_cash_out.status
            == CompletionCashOutStatus.RESERVED
            and not item[2].completion_cash_out.cash_out_spent
        ),
        None,
    )
    if completion_item is not None:
        if telemetry is not None:
            ordinary_order = sorted(
                frontier,
                key=lambda item: _node_priority(
                    replace(
                        item[2],
                        completion_cash_out=replace(
                            item[2].completion_cash_out,
                            status=CompletionCashOutStatus.QUALIFIED,
                        )
                        if item[2].completion_cash_out is not None
                        else None,
                    )
                ),
            )
            if completion_item[1] not in {
                item[1] for item in ordinary_order[:maximum]
            }:
                telemetry.completion_representative_displaced_ordinary_slots += 1
        kept.append(completion_item)
        kept_ids.add(completion_item[1])
        if telemetry is not None and any(
            item[2].epoch_transition_opportunity is not None
            and item[2].epoch_transition_opportunity.status
            == EpochTransitionRepresentativeStatus.RESERVED
            and item[1] != completion_item[1]
            for item in ordered
        ):
            telemetry.scheduler_transition_completion_conflicts += 1
        if len(kept) >= maximum:
            return kept
    transition_item = next(
        (
            item
            for item in ordered
            if item[1] not in kept_ids
            and item[2].epoch_transition_opportunity is not None
            and item[2].epoch_transition_opportunity.status
            == EpochTransitionRepresentativeStatus.RESERVED
        ),
        None,
    )
    if transition_item is not None:
        if telemetry is not None:
            ordinary = sorted(
                frontier,
                key=lambda item: _node_priority(
                    replace(item[2], epoch_transition_opportunity=None)
                ),
            )
            if transition_item[1] not in {item[1] for item in ordinary[:maximum]}:
                telemetry.scheduler_transition_displaced_ordinary_slots += 1
        kept.append(transition_item)
        kept_ids.add(transition_item[1])
        if len(kept) >= maximum:
            return kept
    # Protect only the strongest live same-campaign continuation globally;
    # continuity is bounded and cannot monopolise the frontier.
    continuity_item = next(
        (
            item
            for item in ordered
            if item[2].continuation_credit is not None
            and item[2].continuation_credit.is_live
        ),
        None,
    )
    if continuity_item is not None:
        kept.append(continuity_item)
        kept_ids.add(continuity_item[1])
        if len(kept) >= maximum:
            return kept
    # Keep at most one strongest currently actionable target whose own named
    # harvest earned portable commitment.  This is a bounded follow-up
    # opportunity, not sunk-cost protection or proof dominance.
    target_item = next(
        (
            item
            for item in ordered
            if item[1] not in kept_ids
            and item[2].active_residual_target is not None
            and item[2].active_residual_target.status == ResidualTargetStatus.ACTIONABLE
            and (
                (
                    entry := item[2].target_grant_lineage.active_for(
                        item[2].active_residual_target.identity.fingerprint
                    )
                )
                is not None
                and entry.evidence.has_portable_harvest
            )
        ),
        None,
    )
    if target_item is not None:
        kept.append(target_item)
        kept_ids.add(target_item[1])
        if telemetry is not None:
            telemetry.same_target_reserved_representatives += 1
        if len(kept) >= maximum:
            return kept
    if pre_foundation_portfolio is not None:
        pre_keys = {
            profile.geometry_key() for profile in pre_foundation_portfolio.geometries
        }
        represented_pre = set()
        for item in ordered:
            node = item[2]
            geometry = node.pre_foundation_geometry
            if geometry is None or geometry.geometry_key() not in pre_keys:
                continue
            key = geometry.geometry_key()
            if key in represented_pre:
                continue
            kept.append(item)
            kept_ids.add(item[1])
            represented_pre.add(key)
            if len(kept) >= maximum:
                return kept
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


def _record_contract_outcome(
    outcome: DealPurposeOutcome,
    contract: DealPurposeContract,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    seen: set[Tuple[str, str, CanonicalStateKey]],
    *,
    g: int,
) -> None:
    key = (outcome.contract_id, outcome.status.value, outcome.evaluated_state_key)
    if key in seen:
        return
    seen.add(key)
    if outcome.status == DealPurposeStatus.FULFILLED:
        telemetry.fulfilled_contracts += 1
        if contract.purpose == DealPurposeKind.CAMPAIGN_SUPPLY:
            telemetry.full_supply_fulfilments += 1
            telemetry.coherent_full_supply_fulfilments += 1
    elif outcome.status == DealPurposeStatus.PARTIALLY_FULFILLED:
        telemetry.partially_fulfilled_contracts += 1
    elif outcome.status == DealPurposeStatus.FAILED:
        telemetry.failed_contracts += 1
    elif outcome.status == DealPurposeStatus.INVALIDATED:
        telemetry.invalidated_contracts += 1
    elif outcome.status == DealPurposeStatus.ESCAPE_RECLASSIFIED:
        telemetry.escape_reclassifications += 1
    elif outcome.status == DealPurposeStatus.DELIVERED_BUT_UNCONSUMED:
        telemetry.delivered_but_unconsumed_contracts += 1
    _append_bounded(
        telemetry.contract_timeline,
        (g, contract.contract_id, contract.purpose.value, outcome.status.value),
        config.max_timeline_entries,
    )


def _refresh_node_contracts(
    node: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    seen: set[Tuple[str, str, CanonicalStateKey]],
) -> StrategicSearchNode:
    if node.analysis is None or not node.active_deal_contracts:
        return node
    labels = {
        item.campaign_label
        for item in node.analysis.residual.checkpoint.next_foundation_readiness
    }
    active = []
    outcomes = []
    supply_results = list(node.supply_consumption_results)
    for contract in node.active_deal_contracts:
        credible = contract.campaign_id is None or contract.campaign_id in labels
        supply = supply_result_for_contract(supply_results, contract.contract_id)
        if supply is not None and not credible:
            supply = invalidate_supply_result(
                supply,
                node.state,
                reason="fresh campaign reanalysis invalidated the named supply obligation",
            )
            supply_results = [
                supply if item.contract_id == contract.contract_id else item
                for item in supply_results
            ]
        outcome = validate_deal_purpose_contract(
            contract,
            node.analysis.residual.checkpoint,
            current_depth=node.depth,
            objective_still_credible=credible,
            supply_consumption=supply,
        )
        outcomes.append(outcome)
        _record_contract_outcome(
            outcome,
            contract,
            telemetry,
            config,
            seen,
            g=node.g,
        )
        if contract_requires_descendant(outcome):
            active.append(contract)
    history_by_id = {
        outcome.contract_id: outcome for outcome in node.deal_outcome_history
    }
    for outcome in outcomes:
        history_by_id[outcome.contract_id] = outcome
    return replace(
        node,
        active_deal_contracts=tuple(active),
        deal_contract_outcomes=tuple(outcomes),
        deal_outcome_history=tuple(history_by_id.values()),
        supply_consumption_results=tuple(supply_results),
    )


def _refresh_protected_conversion_lane(
    node: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    seen: set[Tuple[str, str, CanonicalStateKey]],
    *,
    elapsed_seconds: float,
) -> StrategicSearchNode:
    if (
        not config.enable_protected_conversion_lanes
        or node.analysis is None
        or not node.state.foundations
    ):
        return node
    profile = node.analysis.residual.checkpoint

    def dependency_ids(campaign_id: str) -> Tuple[str, ...]:
        campaign = next(
            (
                item
                for item in node.analysis.economic.campaign_portfolio.campaigns
                if item.label == campaign_id
            ),
            None,
        )
        if campaign is None:
            return ()
        graph = build_campaign_dependency_graph(
            node.state,
            campaign,
            supply_consumptions=node.supply_consumption_results,
        )
        telemetry.dependency_graphs_built += 1
        return tuple(
            item.dependency_id
            for item in graph.dependencies
            if item.dependency_id != graph.terminal_dependency_id
        )

    lane = node.protected_conversion_lane
    if lane is not None:
        assessment = evaluate_protected_conversion_lane(
            lane,
            profile,
            current_expansion=telemetry.expanded,
            current_elapsed_seconds=elapsed_seconds,
        )
        event = (lane.lane_id, assessment.status.value, profile.state_key)
        if event not in seen:
            seen.add(event)
            if assessment.status == ProtectedConversionStatus.CONTINUE:
                telemetry.protected_lanes_continued += 1
            elif assessment.status == ProtectedConversionStatus.SUCCESS:
                telemetry.protected_lanes_completed += 1
            elif assessment.status in (
                ProtectedConversionStatus.INVALIDATED,
                ProtectedConversionStatus.DOMINATED_SAME_OBJECTIVE,
            ):
                telemetry.protected_lanes_invalidated += 1
            elif assessment.status == ProtectedConversionStatus.EXPIRED:
                telemetry.protected_lanes_expired += 1
            elif assessment.status == ProtectedConversionStatus.MILESTONE_REACHED:
                telemetry.removal_relevant_milestones_reached += len(
                    assessment.milestones
                )
            _append_bounded(
                telemetry.protected_lane_timeline,
                (node.g, lane.lane_id, lane.target_campaign, assessment.status.value),
                config.max_timeline_entries,
            )
        if assessment.status == ProtectedConversionStatus.CONTINUE:
            return node
        if assessment.status == ProtectedConversionStatus.MILESTONE_REACHED:
            if (
                node.incoming_edge is not None
                and node.incoming_edge.kind
                == StrategicActionKind.CAMPAIGN_DEPENDENCY_CLOSURE
            ):
                telemetry.protected_lane_replans_after_closure += 1
            lane = create_protected_conversion_lane(
                profile,
                campaign_id=lane.target_campaign,
                current_expansion=telemetry.expanded,
                current_elapsed_seconds=elapsed_seconds,
                budget=config.protected_conversion_budget,
                unresolved_dependencies=dependency_ids(lane.target_campaign),
            )
            if lane is not None:
                telemetry.protected_lanes_created += 1
                return replace(node, protected_conversion_lane=lane)
        lane = None
    if lane is None:
        lane = create_protected_conversion_lane(
            profile,
            current_expansion=telemetry.expanded,
            current_elapsed_seconds=elapsed_seconds,
            budget=config.protected_conversion_budget,
        )
        if lane is not None:
            lane = replace(
                lane,
                unresolved_dependencies=dependency_ids(lane.target_campaign),
            )
            telemetry.protected_lanes_created += 1
            _append_bounded(
                telemetry.protected_lane_timeline,
                (node.g, lane.lane_id, lane.target_campaign, "CREATED"),
                config.max_timeline_entries,
            )
    return replace(node, protected_conversion_lane=lane)


def _refresh_same_campaign_continuation(
    node: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    seen: set[Tuple[str, str, CanonicalStateKey]],
    *,
    elapsed_seconds: float,
) -> StrategicSearchNode:
    """Replan continuity from fresh campaign facts without changing identity."""
    credit = node.continuation_credit
    if (
        not config.enable_same_campaign_continuity
        or credit is None
        or node.analysis is None
        or not credit.is_live
    ):
        return node
    campaign = next(
        (
            item
            for item in node.analysis.economic.campaign_portfolio.campaigns
            if item.label == credit.objective_id
        ),
        None,
    )
    outstanding: Optional[Tuple[str, ...]] = None
    if campaign is not None:
        graph = build_campaign_dependency_graph(
            node.state,
            campaign,
            supply_consumptions=node.supply_consumption_results,
        )
        telemetry.dependency_graphs_built += 1
        telemetry.critical_paths_built += 1
        outstanding = tuple(
            item.dependency_id
            for item in graph.dependencies
            if item.dependency_id != graph.terminal_dependency_id
        )
    refreshed = refresh_continuation_credit(
        credit,
        current_depth=node.depth,
        current_elapsed_seconds=elapsed_seconds,
        objective_still_credible=campaign is not None,
        fully_harvested=bool(campaign is not None and not outstanding),
        outstanding_dependencies=outstanding,
        current_g=node.g,
    )
    event = (
        refreshed.credit_id,
        refreshed.status.value,
        canonical_state_key(node.state),
    )
    if event not in seen and refreshed.status != credit.status:
        seen.add(event)
        if refreshed.status == SameCampaignContinuationStatus.REPLANNED:
            telemetry.continuation_credits_replanned += 1
        elif refreshed.status == SameCampaignContinuationStatus.HARVESTED:
            telemetry.continuation_credits_harvested += 1
        elif refreshed.status == SameCampaignContinuationStatus.INVALIDATED:
            telemetry.continuation_credits_invalidated += 1
        elif refreshed.status == SameCampaignContinuationStatus.EXPIRED:
            telemetry.continuation_credits_expired += 1
        elif refreshed.status == SameCampaignContinuationStatus.SUPERSEDED:
            telemetry.continuation_credits_superseded += 1
        _append_bounded(
            telemetry.continuation_timeline,
            (node.g, refreshed.objective_id, refreshed.credit_id, refreshed.status.value),
            config.max_timeline_entries,
        )
    ledger = node.structural_investment_ledger
    if refreshed.status in (
        SameCampaignContinuationStatus.HARVESTED,
        SameCampaignContinuationStatus.INVALIDATED,
        SameCampaignContinuationStatus.EXPIRED,
        SameCampaignContinuationStatus.SUPERSEDED,
    ):
        active = next(
            (
                item
                for item in ledger.investments
                if item.investment_id == refreshed.investment_id
            ),
            None,
        )
        if active is not None:
            status = {
                SameCampaignContinuationStatus.HARVESTED: StructuralInvestmentStatus.HARVESTED,
                SameCampaignContinuationStatus.INVALIDATED: StructuralInvestmentStatus.INVALIDATED,
                SameCampaignContinuationStatus.EXPIRED: StructuralInvestmentStatus.EXPIRED,
                SameCampaignContinuationStatus.SUPERSEDED: StructuralInvestmentStatus.SUPERSEDED,
            }[refreshed.status]
            ledger = ledger.replace(
                replace(active, status=status, expiry_reason=refreshed.expiry_reason)
            )
            if active.status in (
                StructuralInvestmentStatus.ACTIVE,
                StructuralInvestmentStatus.PARTIALLY_HARVESTED,
            ):
                telemetry.unharvested_investments = max(
                    0, telemetry.unharvested_investments - 1
                )
                if status != StructuralInvestmentStatus.HARVESTED:
                    telemetry.abandoned_or_superseded_investments += 1
    return replace(
        node,
        continuation_credit=refreshed,
        structural_investment_ledger=ledger,
    )


def _refresh_active_milestone(
    node: StrategicSearchNode,
    telemetry: ControllerTelemetry,
    config: AnytimeControllerConfig,
    *,
    elapsed_seconds: float,
) -> StrategicSearchNode:
    active = node.active_milestone
    if active is None or node.analysis is None or not config.enable_strategic_milestones:
        return node
    residual = _residual_target_for_milestone(
        node.state,
        node.analysis,
        active,
        config,
        node.source_completion_ledger.satisfactions,
    )
    telemetry.residual_targets_rebuilt += 1
    if node.active_residual_target is not None:
        telemetry.semantic_targets_persisted += int(
            node.active_residual_target.identity.fingerprint
            == residual.identity.fingerprint
        )
        telemetry.blocker_type_transitions += int(
            node.active_residual_target.blockers != residual.blockers
        )
    status = {
        ResidualTargetStatus.COMPLETE: StrategicMilestoneStatus.ACHIEVED,
        ResidualTargetStatus.ACTIONABLE: (
            StrategicMilestoneStatus.ADVANCED
            if residual.progress.satisfied_units > active.progress.satisfied_units
            else StrategicMilestoneStatus.ACTIVE
        ),
        ResidualTargetStatus.BLOCKED_CURRENT_EPOCH: StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH,
        ResidualTargetStatus.INVALIDATED: StrategicMilestoneStatus.INVALIDATED,
    }[residual.status]
    if (
        status != StrategicMilestoneStatus.ACHIEVED
        and node.depth - active.created_depth >= active.max_strategic_expansions
    ):
        status = StrategicMilestoneStatus.EXPIRED
    if (
        status != StrategicMilestoneStatus.ACHIEVED
        and elapsed_seconds - active.created_elapsed_seconds >= active.max_elapsed_seconds
    ):
        status = StrategicMilestoneStatus.EXPIRED
    refreshed = replace(
        active,
        target_identity=residual.identity,
        progress=residual.progress,
        status=status,
    )
    satisfaction_by_id = {
        item.requirement.requirement_id: item
        for item in residual.source_satisfactions
    }
    source_ledger = node.source_completion_ledger
    refreshed_traces = []
    for trace in source_ledger.traces:
        satisfaction = satisfaction_by_id.get(
            trace.event.requirement.requirement_id
        )
        updated_trace = trace
        if satisfaction is not None and satisfaction.fresh_reanalysis_preserved:
            updated_trace = updated_trace.advance(
                SourceCompletionStage.FRESH_RESIDUAL_PRESERVED,
                disposition=SourceCompletionDisposition.PRESERVED,
                detail="controller fresh residual preserves source satisfaction",
            )
            if satisfaction.copy_reassigned:
                updated_trace = replace(
                    updated_trace,
                    disposition=SourceCompletionDisposition.REASSIGNED,
                    copy_reassigned=True,
                    detail=(
                        "fresh exact analysis selected an interchangeable physical "
                        "copy without erasing semantic satisfaction"
                    ),
                )
            if satisfaction.state == SourceRequirementSatisfactionState.CONSUMED:
                updated_trace = updated_trace.advance(
                    SourceCompletionStage.SOURCE_CONSUMED,
                    detail="fresh exact state consumes the satisfying source",
                )
            elif satisfaction.state == SourceRequirementSatisfactionState.INTEGRATED:
                updated_trace = updated_trace.advance(
                    SourceCompletionStage.SOURCE_CONSUMED,
                    detail="fresh exact state consumes the satisfying source",
                ).advance(
                    SourceCompletionStage.SOURCE_INTEGRATED,
                    detail="fresh exact state integrates the source into same-suit structure",
                )
        elif satisfaction is not None and satisfaction.reopening_reason is not None:
            updated_trace = replace(
                updated_trace,
                disposition=SourceCompletionDisposition.REOPENED,
                loss_reason=SourceCompletionLossReason.RESIDUAL_REOPENING,
                reopening_reason=satisfaction.reopening_reason,
                detail="fresh residual explicitly reopened a prior source requirement",
            )
        refreshed_traces.append(updated_trace)
        _record_source_completion_trace(
            telemetry, updated_trace, config.max_timeline_entries
        )
    source_ledger = replace(
        source_ledger,
        traces=tuple(refreshed_traces),
        satisfactions=residual.source_satisfactions or source_ledger.satisfactions,
    )
    if status == StrategicMilestoneStatus.EXPIRED:
        audit_started = time.perf_counter()
        expiry_rows = list(source_ledger.expiry_classifications)
        existing_expired = {item[0] for item in expiry_rows}
        for trace in refreshed_traces:
            if trace.event.event_id in existing_expired:
                continue
            satisfaction = satisfaction_by_id.get(
                trace.event.requirement.requirement_id
            )
            classification = classify_source_expiry(
                completed_before_expiry=bool(
                    satisfaction is not None and satisfaction.satisfied
                ),
                made_progress=trace.residual_preserved,
                resource_limited=True,
                attribution_lost=(
                    trace.loss_reason
                    == SourceCompletionLossReason.PHYSICAL_SOURCE_ATTRIBUTION_LOSS
                ),
                lifecycle_terminated=bool(
                    node.target_grant_lineage.active_for(
                        trace.event.semantic_target_fingerprint
                    )
                    and node.target_grant_lineage.active_for(
                        trace.event.semantic_target_fingerprint
                    ).restore_replace_obligation
                ),
            )
            expiry_rows.append((trace.event.event_id, classification))
            name = classification.value
            telemetry.source_requirement_expiry_classifications[name] = (
                telemetry.source_requirement_expiry_classifications.get(name, 0) + 1
            )
        source_ledger = replace(
            source_ledger, expiry_classifications=tuple(expiry_rows)
        )
        telemetry.source_expiry_audit_seconds += time.perf_counter() - audit_started
    completion_result = None
    incoming = node.incoming_edge
    if (
        status == StrategicMilestoneStatus.ACHIEVED
        and active.status != StrategicMilestoneStatus.ACHIEVED
        and incoming is not None
        and incoming.kind not in _DEAL_ACTION_KINDS
        and incoming.actions
        and incoming.independent_replay_verified
    ):
        outcome_kind = classify_milestone_outcome(refreshed, status)
        completion_result = MilestoneRealizationResult(
            refreshed,
            status,
            incoming.actions,
            incoming.corrected_cost,
            node.state.clone(),
            1,
            incoming.tactical_nodes,
            0.0,
            True,
            1,
            (incoming.label,),
            "fresh descendant completed the persistent semantic target",
            outcome_kind=outcome_kind,
            target_identity=residual.identity,
            residual_timeline=(residual.summary,),
        )
        if outcome_kind == MilestoneOutcomeKind.PRIMITIVE_RESULT:
            telemetry.primitive_results += 1
        elif outcome_kind in {
            MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
            MilestoneOutcomeKind.FOUNDATION,
        }:
            telemetry.substantial_structural_milestones += 1
        _append_bounded(
            telemetry.milestone_timeline,
            (
                node.g,
                refreshed.milestone_id,
                refreshed.kind.value,
                status.value,
                1,
                incoming.corrected_cost,
            ),
            config.max_timeline_entries,
        )
    if refreshed.status != active.status:
        field_name = {
            StrategicMilestoneStatus.ADVANCED: "milestones_advanced",
            StrategicMilestoneStatus.ACHIEVED: "milestones_achieved",
            StrategicMilestoneStatus.REPLANNED: "milestones_replanned",
            StrategicMilestoneStatus.BLOCKED_CURRENT_EPOCH: "milestones_stock_blocked",
            StrategicMilestoneStatus.INVALIDATED: "milestones_invalidated",
            StrategicMilestoneStatus.SUPERSEDED: "milestones_superseded",
            StrategicMilestoneStatus.EXPIRED: "milestones_expired",
            StrategicMilestoneStatus.BOUNDED_MISS: "milestone_bounded_misses",
        }.get(refreshed.status)
        if (
            field_name is not None
            and not (
                refreshed.status == StrategicMilestoneStatus.ACHIEVED
                and incoming is not None
                and incoming.kind in _DEAL_ACTION_KINDS
            )
        ):
            setattr(telemetry, field_name, getattr(telemetry, field_name) + 1)
    if residual.status == ResidualTargetStatus.COMPLETE:
        telemetry.residual_target_completions += 1
    elif residual.status == ResidualTargetStatus.INVALIDATED:
        telemetry.residual_target_invalidations += 1
    _append_bounded(
        telemetry.residual_target_timeline,
        (
            node.g,
            active.milestone_id,
            residual.status.value,
            residual.summary,
        ),
        config.max_timeline_entries,
    )
    milestone_result = completion_result or (
        node.incoming_edge.milestone_result
        if node.incoming_edge is not None
        else None
    )
    refreshed_obligations = []
    for obligation in node.post_deal_obligations:
        matching_residual = (
            residual if obligation_matches_target(obligation, residual.identity) else None
        )
        structural_progress = bool(
            milestone_result is not None
            and milestone_result.status in {
                StrategicMilestoneStatus.ADVANCED,
                StrategicMilestoneStatus.ACHIEVED,
            }
            and obligation_matches_target(obligation, milestone_result.milestone)
        )
        substantial_harvest = bool(
            structural_progress
            and milestone_result is not None
            and milestone_result.outcome_kind in {
                MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
                MilestoneOutcomeKind.FOUNDATION,
            }
        )
        updated = refresh_post_deal_obligation(
            node.state,
            obligation,
            matching_residual,
            structural_progress=structural_progress,
            substantial_harvest=substantial_harvest,
        )
        refreshed_obligations.append(updated)
        field = {
            PostDealObligationStatus.MATERIAL_AVAILABLE: "post_deal_material_available",
            PostDealObligationStatus.ACTIONABLE: "post_deal_actionable",
            PostDealObligationStatus.BLOCKED: "post_deal_blocked",
            PostDealObligationStatus.STRUCTURAL_PROGRESS: "post_deal_structural_progress",
            PostDealObligationStatus.SUBSTANTIAL_HARVEST: "post_deal_substantial_harvest",
        }.get(updated.status)
        if field is not None:
            setattr(telemetry, field, getattr(telemetry, field) + 1)
        _append_bounded(
            telemetry.post_deal_obligation_timeline,
            (node.g, updated.obligation_id, updated.status.value, updated.last_reason),
            config.max_timeline_entries,
        )
    return replace(
        node,
        active_milestone=refreshed,
        active_residual_target=replace(residual, milestone=refreshed),
        post_deal_obligations=tuple(refreshed_obligations),
        milestone_ledger=(
            node.milestone_ledger.add(completion_result)
            if completion_result is not None
            else node.milestone_ledger
        ),
        source_completion_ledger=source_ledger,
    )


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
        if successor.epoch_transition is not None:
            telemetry.purposeful_deals += 1
            if successor.milestone_result is not None:
                telemetry.transition_checkpoints += 1
                _append_bounded(
                    telemetry.milestone_timeline,
                    (
                        parent.g,
                        successor.milestone_result.milestone.milestone_id,
                        StrategicMilestoneKind.EPOCH_TRANSITION.value,
                        StrategicMilestoneStatus.ACHIEVED.value,
                        1,
                        successor.corrected_cost,
                    ),
                    config.max_timeline_entries,
                )
            _append_bounded(
                telemetry.epoch_timeline,
                (
                    child.g,
                    successor.epoch_transition.next_epoch or 5,
                    successor.epoch_transition.status.value,
                    successor.epoch_transition.purpose,
                ),
                config.max_timeline_entries,
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
            "campaign_dependency_closure": config.dependency_closure_config.time_limit_s,
        },
    )
    preflight = freeze_active_rule_profile(initial_state, cards, rules=MW_RULES)
    initial_incumbent_cost = (
        incumbent.corrected_cost if isinstance(incumbent, IncumbentRecord) else incumbent
    )
    supplied_record = incumbent if isinstance(incumbent, IncumbentRecord) else None
    telemetry = ControllerTelemetry()
    resource_allocator = _resource_allocator_for_config(config)
    checkpoint_profiles: List[FoundationCheckpointProfile] = []
    pre_foundation_profiles: List[PreFoundationGeometry] = []
    checkpoint_portfolio = retain_foundation_checkpoint_portfolio(
        (), maximum=config.max_foundation_checkpoints
    )
    pre_foundation_portfolio = retain_pre_foundation_portfolio(
        (), maximum=config.max_pre_foundation_geometries
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
        if not initial_state.foundations:
            geometry = build_pre_foundation_geometry(
                initial_state,
                g=0,
                analysis=economic,
                measurement=measurement,
            )
            root = replace(root, pre_foundation_geometry=geometry)
            pre_foundation_profiles.append(geometry)
            pre_foundation_portfolio = retain_pre_foundation_portfolio(
                pre_foundation_profiles,
                maximum=config.max_pre_foundation_geometries,
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
            pre_foundation_portfolio=pre_foundation_portfolio,
            successive_deal_audit=tuple(telemetry.successive_deal_audit),
        )

    current_incumbent_cost = initial_incumbent_cost
    current_incumbent = supplied_record
    first_solution: Optional[IncumbentRecord] = None
    whole_deal_blueprint: Optional[WholeDealBlueprint] = None
    if config.enable_whole_deal_scheduler:
        whole_deal_blueprint = build_whole_deal_blueprint(initial_state)
        telemetry.scheduler_blueprints_built += 1
        telemetry.scheduler_blueprint_seconds += (
            whole_deal_blueprint.performance.blueprint_seconds
        )
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
        supply_consumptions=(),
        continuation_objective_id=None,
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
    if whole_deal_blueprint is not None:
        root_schedule = rebuild_whole_deal_schedule(
            initial_state,
            whole_deal_blueprint,
            config=config.whole_deal_scheduler_config,
            generation=0,
        )
        root = replace(root, whole_deal_schedule=root_schedule)
        _record_scheduler_rebuild(telemetry, root_schedule)
    if not initial_state.foundations:
        root_geometry = build_pre_foundation_geometry(
            initial_state,
            g=0,
            analysis=root_analysis.economic,
            measurement=root_analysis.measurement,
        )
        root = replace(root, pre_foundation_geometry=root_geometry)
        pre_foundation_profiles.append(root_geometry)
        pre_foundation_portfolio = retain_pre_foundation_portfolio(
            pre_foundation_profiles,
            maximum=config.max_pre_foundation_geometries,
        )
        telemetry.distinct_pre_foundation_geometries = len(
            pre_foundation_portfolio.geometries
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
    completion_context_by_state: Dict[CanonicalStateKey, SourceCompletionLedger] = {
        canonical_state_key(root.state): root.source_completion_ledger
    }
    cash_out_spent_event_ids: set[str] = set()
    epoch_transition_spent_ids: set[str] = set()
    frontier: List[Tuple[Tuple, int, StrategicSearchNode]] = []
    uid = 0
    heapq.heappush(frontier, (_node_priority(root), uid, root))
    expansion_credits: set[Tuple[CanonicalStateKey, int]] = set()
    actionability_cache: Dict[ActionabilityCacheKey, ProjectActionability] = {}
    dependency_closure_cache: Dict = {}
    contract_events_seen: set[Tuple[str, str, CanonicalStateKey]] = set()
    contract_creations_seen: set[str] = set()
    lane_events_seen: set[Tuple[str, str, CanonicalStateKey]] = set()
    continuation_events_seen: set[Tuple[str, str, CanonicalStateKey]] = set()
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

        frontier = _reserve_completion_representative(
            frontier,
            tt=tt,
            spent_event_ids=tuple(cash_out_spent_event_ids),
            telemetry=telemetry,
        )
        frontier = _reserve_epoch_transition_representative(
            frontier,
            tt=tt,
            spent_opportunity_ids=tuple(epoch_transition_spent_ids),
            telemetry=telemetry,
        )
        _priority, _sequence, node = heapq.heappop(frontier)
        if node.completion_cash_out_parent_was_deal:
            telemetry.completion_deals_chosen_after_cash_out += 1
            node = replace(node, completion_cash_out_parent_was_deal=False)
        reconstructed = completion_context_by_state.get(canonical_state_key(node.state))
        if reconstructed is not None and reconstructed.satisfactions:
            merged_satisfactions = {
                item.requirement.identity_key: item
                for item in node.source_completion_ledger.satisfactions
            }
            for item in reconstructed.satisfactions:
                merged_satisfactions[item.requirement.identity_key] = item
            node = replace(
                node,
                source_completion_ledger=replace(
                    node.source_completion_ledger,
                    satisfactions=tuple(merged_satisfactions.values()),
                ),
            )
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
                    supply_consumptions=node.supply_consumption_results,
                    continuation_objective_id=(
                        node.continuation_credit.objective_id
                        if node.continuation_credit is not None
                        and node.continuation_credit.is_live
                        else None
                    ),
                )
            except AnalysisResourceLimit:
                telemetry.optional_analyses_skipped += 1
                stop_reason = "deadline before fresh Stage-1 expansion analysis"
                break
            node = replace(node, analysis=fresh)
            telemetry.reanalyses += 1
            telemetry.stage1_analyses += 1
        assert node.analysis is not None
        if not node.state.foundations and config.enable_pre_foundation_diversity:
            refined_geometry = build_pre_foundation_geometry(
                node.state,
                g=node.g,
                analysis=node.analysis.economic,
                measurement=node.analysis.measurement,
                campaign_hint=(
                    node.pre_foundation_geometry.campaign_identity
                    if node.pre_foundation_geometry is not None
                    else None
                ),
            )
            node = replace(node, pre_foundation_geometry=refined_geometry)
            pre_foundation_profiles.append(refined_geometry)
            pre_foundation_portfolio = retain_pre_foundation_portfolio(
                pre_foundation_profiles,
                maximum=config.max_pre_foundation_geometries,
            )
            telemetry.distinct_pre_foundation_geometries = len(
                pre_foundation_portfolio.geometries
            )
        node = _refresh_node_contracts(
            node,
            telemetry,
            config,
            contract_events_seen,
        )
        node = _refresh_protected_conversion_lane(
            node,
            telemetry,
            config,
            lane_events_seen,
            elapsed_seconds=elapsed,
        )
        node = _refresh_same_campaign_continuation(
            node,
            telemetry,
            config,
            continuation_events_seen,
            elapsed_seconds=elapsed,
        )
        node = _refresh_active_milestone(
            node,
            telemetry,
            config,
            elapsed_seconds=elapsed,
        )
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

        active_cash_out = None
        if (
            node.completion_cash_out is not None
            and node.completion_cash_out.status == CompletionCashOutStatus.RESERVED
            and node.completion_cash_out.eligible(cash_out_spent_event_ids)
        ):
            active_cash_out = replace(
                node.completion_cash_out,
                status=CompletionCashOutStatus.EXPANDED,
                cash_out_spent=True,
                reason=(
                    "reserved admitted completion is receiving its one normal fresh expansion"
                ),
            )
            cash_out_spent_event_ids.update(active_cash_out.event_ids)
            node = replace(node, completion_cash_out=active_cash_out)
            telemetry.completion_representatives_expanded += 1
            telemetry.completion_cash_out_spent += 1
            _update_completion_trace(
                telemetry,
                active_cash_out,
                disposition=CompletionCashOutDisposition.REPRESENTATIVE_EXPANDED,
                reason=active_cash_out.reason,
                selected_for_expansion=True,
                cash_out_spent=True,
            )

        active_epoch_transition = None
        if (
            node.epoch_transition_opportunity is not None
            and node.epoch_transition_opportunity.status
            == EpochTransitionRepresentativeStatus.RESERVED
            and node.epoch_transition_opportunity.eligible(epoch_transition_spent_ids)
            and node.whole_deal_schedule is not None
        ):
            active_epoch_transition = node.epoch_transition_opportunity
            epoch_transition_spent_ids.add(active_epoch_transition.opportunity_id)
            trace = build_epoch_transition_trace(
                active_epoch_transition,
                corrected_g_before=max(
                    0,
                    active_epoch_transition.corrected_g_after_deal - 1,
                ),
                epoch_after=node.whole_deal_schedule.epoch,
                next_schedule=node.whole_deal_schedule,
                expanded=True,
            )
            _append_bounded(
                telemetry.scheduler_epoch_traces,
                trace,
                config.max_timeline_entries,
            )
            for harvest in active_epoch_transition.harvests:
                telemetry.scheduler_transition_harvest_counts[harvest.kind.value] = (
                    telemetry.scheduler_transition_harvest_counts.get(
                        harvest.kind.value, 0
                    )
                    + 1
                )
            node = replace(
                node,
                epoch_transition_opportunity=replace(
                    active_epoch_transition,
                    status=EpochTransitionRepresentativeStatus.SPENT,
                ),
            )
            telemetry.scheduler_transition_representatives_expanded += 1
            telemetry.scheduler_transition_opportunities_spent += 1

        telemetry.expanded += 1
        if node.whole_deal_schedule is not None:
            schedule = node.whole_deal_schedule
            if schedule.saturation is not None:
                saturation_name = schedule.saturation.status.value
                telemetry.scheduler_saturation_counts[saturation_name] = (
                    telemetry.scheduler_saturation_counts.get(saturation_name, 0) + 1
                )
                telemetry.scheduler_deal_ready_states += int(
                    schedule.saturation.status == EpochSaturationStatus.DEAL_READY
                )
                for opportunity in schedule.pre_deal_opportunities:
                    name = opportunity.classification.value
                    telemetry.scheduler_pre_deal_classifications[name] = (
                        telemetry.scheduler_pre_deal_classifications.get(name, 0) + 1
                    )
            telemetry.scheduler_objectives_generated += len(schedule.objectives)
            telemetry.scheduler_objectives_actionable += sum(
                item.status in (
                    ScheduleObjectiveStatus.ACTIONABLE,
                    ScheduleObjectiveStatus.SATISFIED,
                )
                for item in schedule.objectives
            )
            for objective in schedule.objectives:
                _scheduler_stage(telemetry, objective, "generated")
                if objective.status in (
                    ScheduleObjectiveStatus.ACTIONABLE,
                    ScheduleObjectiveStatus.SATISFIED,
                ):
                    _scheduler_stage(telemetry, objective, "actionable")
        if (
            node.incoming_edge is not None
            and node.incoming_edge.scheduled_objective is not None
        ):
            selected = node.incoming_edge.scheduled_objective
            telemetry.scheduler_objectives_selected += 1
            _scheduler_stage(telemetry, selected, "selected")
            selected_class = node.incoming_edge.scheduler_pre_deal_classification
            if selected_class is not None:
                telemetry.scheduler_selected_pre_deal_classifications[
                    selected_class.value
                ] = (
                    telemetry.scheduler_selected_pre_deal_classifications.get(
                        selected_class.value, 0
                    )
                    + 1
                )
            for delta in node.incoming_edge.schedule_deltas:
                telemetry.scheduler_delta_counts[delta.kind.value] = (
                    telemetry.scheduler_delta_counts.get(delta.kind.value, 0) + 1
                )
                if delta.kind == ScheduleDeltaKind.TARGET_ADVANCED:
                    telemetry.scheduler_objectives_advanced += 1
                    _scheduler_stage(telemetry, selected, "advanced")
                elif delta.kind == ScheduleDeltaKind.TARGET_SATISFIED:
                    telemetry.scheduler_objectives_satisfied += 1
                    _scheduler_stage(telemetry, selected, "satisfied")
                elif delta.kind == ScheduleDeltaKind.RECEPTION_REALIZED:
                    telemetry.scheduler_receptions_realized += 1
                elif delta.kind == ScheduleDeltaKind.RECEPTION_MISSED:
                    telemetry.scheduler_receptions_missed += 1
            schedule_progress_harvest = any(
                delta.kind in {
                    ScheduleDeltaKind.TARGET_ADVANCED,
                    ScheduleDeltaKind.TARGET_SATISFIED,
                    ScheduleDeltaKind.BRIDGE_CONSUMED,
                }
                for delta in node.incoming_edge.schedule_deltas
            ) and selected.family in {
                ScheduleObjectiveFamily.BUILD_FRAGMENT,
                ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD,
                ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE,
            }
            if (
                selected.family != ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION
                and (
                    schedule_progress_harvest
                    or (
                        node.incoming_edge.progress_delta is not None
                        and (
                            node.incoming_edge.progress_delta.stable_join_delta > 0
                            or node.incoming_edge.progress_delta.foundation_delta > 0
                            or node.incoming_edge.progress_delta.same_suit_mass_delta > 0
                        )
                    )
                )
            ):
                telemetry.scheduler_downstream_harvests += 1
                _scheduler_stage(telemetry, selected, "downstream_harvest")
            _append_bounded(
                telemetry.scheduler_timeline,
                (
                    node.g,
                    node.whole_deal_schedule.epoch if node.whole_deal_schedule else 0,
                    selected.family.value,
                    ",".join(item.kind.value for item in node.incoming_edge.schedule_deltas)
                    or "SELECTED",
                ),
                config.max_timeline_entries,
            )
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
            if m.foundation_count == 1:
                telemetry.first_foundation_checkpoints_discovered += 1
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
            if m.foundation_count >= 2 and telemetry.foundation_two_checkpoint_parent is None:
                telemetry.foundation_two_checkpoint_parent = (
                    current_profile.foundations,
                    current_profile.g,
                    (
                        node.incoming_edge.label
                        if node.incoming_edge is not None
                        else "initial checkpoint"
                    ),
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

        resource_allocator.begin_expansion()
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
            dependency_closure_cache=dependency_closure_cache,
            resource_allocator=resource_allocator,
        )
        telemetry.generated += len(successors)
        _trace_expansion(node, successors, telemetry, config, current_incumbent_cost)
        cash_out_assessments: List[CompletionHarvestAssessment] = []
        cash_out_deal_admitted = False

        protected_successor = next(
            (
                item
                for item in successors
                if successor_pursues_protected_conversion(node, item)
            ),
            None,
        )
        if node.protected_conversion_lane is not None and protected_successor is None:
            protected_successor = next(
                (
                    item
                    for item in successors
                    if item.category
                    in (
                        "dependency_closure",
                        "residual_conversion",
                        "campaign_corridor",
                        "campaign",
                        "permanent_structure",
                        "workspace_excavation",
                    )
                ),
                None,
            )
        for successor in successors:
            if not successor.independent_replay_verified:
                telemetry.count_suppression("edge replay failed")
                continue
            had_milestone_result = successor.milestone_result is not None
            successor = _contextual_milestone_completion(node, successor)
            contextual_completion = bool(
                not had_milestone_result and successor.milestone_result is not None
            )
            ng = node.g + successor.corrected_cost
            if not tt.admit(successor.end_state, ng):
                telemetry.tt_suppressed += 1
                if (
                    successor.actions == (("deal",),)
                    and node.whole_deal_schedule is not None
                    and node.whole_deal_schedule.saturation is not None
                    and node.whole_deal_schedule.saturation.status
                    == EpochSaturationStatus.DEAL_READY
                ):
                    telemetry.scheduler_transition_duplicate_reservations_suppressed += 1
                if active_cash_out is not None:
                    cash_out_assessments.append(
                        _completion_harvest_assessment(
                            active_cash_out, node, successor, admitted=False
                        )
                    )
                for source_trace in successor.source_completion_traces:
                    lost = replace(
                        source_trace,
                        disposition=SourceCompletionDisposition.ADMISSION_LOSS,
                        loss_reason=SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS,
                        detail="exact TT retained an equal/lower-g structural duplicate",
                    )
                    _record_source_completion_trace(
                        telemetry, lost, config.max_timeline_entries
                    )
                if successor.source_completion_traces:
                    telemetry.completion_exact_duplicate_suppressions += 1
                    key = canonical_state_key(successor.end_state)
                    context = completion_context_by_state.get(
                        key, SourceCompletionLedger()
                    )
                    satisfactions = {
                        item.requirement.identity_key: item
                        for item in context.satisfactions
                    }
                    for item in reconstruct_completion_satisfactions(
                        successor.end_state, successor.source_completion_traces
                    ):
                        satisfactions[item.requirement.identity_key] = item
                    completion_context_by_state[key] = replace(
                        context, satisfactions=tuple(satisfactions.values())
                    )
                if successor.kind == StrategicActionKind.CAMPAIGN_CORRIDOR:
                    telemetry.corridors_suppressed_by_tt += 1
                telemetry.count_suppression("exact state reached at no lower g")
                continue
            cash_out_assessment = None
            if active_cash_out is not None:
                cash_out_assessment = _completion_harvest_assessment(
                    active_cash_out, node, successor, admitted=True
                )
                cash_out_assessments.append(cash_out_assessment)
                cash_out_deal_admitted = bool(
                    cash_out_deal_admitted
                    or successor.kind in _DEAL_ACTION_KINDS
                )
            if contextual_completion:
                result = successor.milestone_result
                assert result is not None
                telemetry.milestones_achieved += 1
                if result.outcome_kind in {
                    MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
                    MilestoneOutcomeKind.FOUNDATION,
                }:
                    telemetry.substantial_structural_milestones += 1
                if result.milestone.kind == StrategicMilestoneKind.INTERVAL_ASSEMBLY:
                    telemetry.milestone_intervals_completed += 1
                    telemetry.substantial_interval_completions += 1
                _append_bounded(
                    telemetry.milestone_timeline,
                    (
                        node.g,
                        result.milestone.milestone_id,
                        result.milestone.kind.value,
                        result.status.value,
                        result.primitive_steps,
                        result.corrected_paid_cost,
                    ),
                    config.max_timeline_entries,
                )
            child_stage0 = analyze_stage0_state(
                successor.end_state,
                spent_cost=ng,
                incumbent_cost=current_incumbent_cost,
            )
            telemetry.stage0_analyses += 1
            child_schedule = None
            child_schedule_deltas: Tuple[ScheduleDelta, ...] = ()
            child_epoch_transition = None
            if whole_deal_blueprint is not None:
                child_schedule = rebuild_whole_deal_schedule(
                    successor.end_state,
                    whole_deal_blueprint,
                    config=config.whole_deal_scheduler_config,
                    generation=node.depth + 1,
                )
                _record_scheduler_rebuild(telemetry, child_schedule)
                if node.whole_deal_schedule is not None:
                    child_schedule_deltas = derive_schedule_delta(
                        node.state,
                        successor.end_state,
                        node.whole_deal_schedule,
                        child_schedule,
                        selected_objective=successor.scheduled_objective,
                    )
                if (
                    node.whole_deal_schedule is not None
                    and child_schedule is not None
                    and successor.actions == (("deal",),)
                ):
                    prepared = bool(
                        node.incoming_edge is not None
                        and node.incoming_edge.scheduler_pre_deal_classification
                        in {
                            PreDealOpportunityClass.MUST_PRE_DEAL,
                            PreDealOpportunityClass.ADVANTAGE_PRE_DEAL,
                        }
                    )
                    source_schedule = node.whole_deal_schedule
                    if (
                        successor.scheduler_effective_deal_ready
                        and source_schedule.saturation is not None
                    ):
                        source_schedule = replace(
                            source_schedule,
                            deal_now_preferred=True,
                            saturation=replace(
                                source_schedule.saturation,
                                status=EpochSaturationStatus.DEAL_READY,
                                selected_preparation=None,
                                reason=(
                                    "bounded advantage had no demonstrated "
                                    "already-generated realiser"
                                ),
                            ),
                        )
                    child_epoch_transition = make_epoch_transition_opportunity(
                        node.state,
                        successor.end_state,
                        source_schedule,
                        child_schedule,
                        corrected_g_after_deal=ng,
                        stable_structure_after=child_stage0.stable_same_suit_joins,
                        rehandling_debt_after=child_stage0.rehandling_debt,
                        deal_kind=(
                            SchedulerDealKind.PREPARED_DEAL
                            if prepared
                            else SchedulerDealKind.DEAL_NOW
                        ),
                        exact_tt_admitted=True,
                        independently_replay_verified=successor.independent_replay_verified,
                    )
                    if child_epoch_transition is not None:
                        telemetry.scheduler_deal_ready_tt_admitted += 1
                        telemetry.scheduler_transition_qualified += 1
            if successor.scheduled_objective is not None:
                telemetry.scheduler_objectives_admitted += 1
                _scheduler_stage(
                    telemetry, successor.scheduled_objective, "admitted"
                )
            if len(successor.end_state.foundations) > len(node.state.foundations):
                telemetry.full_reanalyses_after_foundation += 1
            if len(successor.end_state.stock) < len(node.state.stock):
                telemetry.full_reanalyses_after_deal += 1
            child_successor = replace(
                successor,
                analysis=None,
                schedule_deltas=child_schedule_deltas,
            )
            child_audit_history = node.successive_deal_audit_history
            if successor.deal_contracts:
                unresolved_before = tuple(node.active_deal_contracts)
                if unresolved_before:
                    telemetry.pending_contract_deals += 1
                previous = (
                    node.deal_contract_history[-1]
                    if node.deal_contract_history
                    else (unresolved_before[-1] if unresolved_before else None)
                )
                if previous is not None:
                    outcome = next(
                        (
                            item
                            for item in reversed(node.deal_outcome_history)
                            if item.contract_id == previous.contract_id
                        ),
                        validate_deal_purpose_contract(
                            previous,
                            node.analysis.residual.checkpoint,
                            current_depth=node.depth,
                            supply_consumption=supply_result_for_contract(
                                node.supply_consumption_results,
                                previous.contract_id,
                            ),
                        ),
                    )
                    if (
                        contract_requires_descendant(outcome)
                        and previous.evidence_before.foundations
                        == len(node.state.foundations)
                    ):
                        telemetry.consecutive_deals_with_unresolved_contracts += 1
                    audit = audit_successive_deal(
                        previous,
                        outcome,
                        deal_ordinal=sum(
                            action == ("deal",)
                            for action in node.actions + successor.actions
                        ),
                        previous_contract_resolution=outcome.reason,
                        dependency_closure_attempted=(
                            successor.closure_attempted_before_deal
                        ),
                        dependency_closure_result=(
                            successor.closure_result_before_deal
                        ),
                        reason_another_deal_considered=(
                            successor.successive_deal_reason
                        ),
                    )
                    if successor.closure_attempted_before_deal:
                        telemetry.closure_attempted_before_successive_deal += 1
                    if previous.purpose == DealPurposeKind.CAMPAIGN_SUPPLY and (
                        outcome.supply_stage
                        not in (
                            SupplyConsumptionStage.CONSUMED,
                            SupplyConsumptionStage.INTEGRATED,
                        )
                    ):
                        telemetry.deals_with_unresolved_supply_obligation += 1
                    _append_bounded(
                        telemetry.successive_deal_audit,
                        audit,
                        config.max_timeline_entries,
                    )
                    child_audit_history = child_audit_history + (audit,)
                for contract in successor.deal_contracts:
                    if contract.contract_id in contract_creations_seen:
                        continue
                    contract_creations_seen.add(contract.contract_id)
                    telemetry.deal_contracts_created += 1
                    telemetry.contracts_by_purpose[contract.purpose.value] = (
                        telemetry.contracts_by_purpose.get(contract.purpose.value, 0) + 1
                    )
                    if contract.purpose == DealPurposeKind.CAMPAIGN_SUPPLY:
                        telemetry.supply_contracts_created += 1
                        telemetry.supply_assets_promised += len(
                            contract.supply_obligations
                        )
                        critical = sum(
                            item.role == SupplyObligationRole.CRITICAL
                            for item in contract.supply_obligations
                        )
                        supporting = sum(
                            item.role == SupplyObligationRole.SUPPORTING
                            for item in contract.supply_obligations
                        )
                        optional = sum(
                            item.role == SupplyObligationRole.OPTIONAL
                            for item in contract.supply_obligations
                        )
                        telemetry.critical_supply_obligations += critical
                        telemetry.supporting_supply_obligations += supporting
                        telemetry.optional_supply_assets += optional
                        _append_bounded(
                            telemetry.supply_scope_timeline,
                            (node.g, contract.contract_id, critical, supporting, optional),
                            config.max_timeline_entries,
                        )
            uid += 1
            active_contracts = tuple(
                dict.fromkeys(
                    node.active_deal_contracts + successor.deal_contracts
                )
            )
            pre_geometry = None
            if not successor.end_state.foundations and config.enable_pre_foundation_diversity:
                live_campaigns = {
                    campaign.label
                    for campaign in node.analysis.economic.campaign_portfolio.campaigns
                }
                hint = (
                    successor.source_project_id
                    if successor.source_project_id in live_campaigns
                    else (
                        node.analysis.economic.campaign_portfolio.primary.label
                        if node.analysis.economic.campaign_portfolio.primary is not None
                        else None
                    )
                )
                pre_geometry = build_pre_foundation_geometry(
                    successor.end_state,
                    g=ng,
                    campaign_hint=hint,
                )
                pre_foundation_profiles.append(pre_geometry)
                pre_foundation_portfolio = retain_pre_foundation_portfolio(
                    pre_foundation_profiles,
                    maximum=config.max_pre_foundation_geometries,
                )
                telemetry.distinct_pre_foundation_geometries = len(
                    pre_foundation_portfolio.geometries
                )
            child_supply_results = advance_supply_consumption_results(
                node.state,
                successor.actions,
                existing=node.supply_consumption_results,
                new_contracts=successor.deal_contracts,
            )
            prior_supply = {
                (item.contract_id, evidence.obligation_id): evidence.stage
                for item in node.supply_consumption_results
                for evidence in item.evidence
            }
            for result in child_supply_results:
                for obligation, evidence in zip(result.obligations, result.evidence):
                    old = prior_supply.get((result.contract_id, evidence.obligation_id))
                    if old == evidence.stage:
                        continue
                    if old is None and evidence.stage in (
                        SupplyConsumptionStage.DELIVERED,
                        SupplyConsumptionStage.AVAILABLE,
                        SupplyConsumptionStage.CONSUMED,
                        SupplyConsumptionStage.INTEGRATED,
                    ):
                        telemetry.supply_assets_delivered += 1
                    if evidence.stage == SupplyConsumptionStage.DELIVERED:
                        pass
                    elif evidence.stage == SupplyConsumptionStage.AVAILABLE:
                        telemetry.supply_assets_available += 1
                    elif evidence.stage == SupplyConsumptionStage.CONSUMED:
                        telemetry.supply_assets_consumed += 1
                        if obligation.role == SupplyObligationRole.CRITICAL:
                            telemetry.critical_supply_consumed += 1
                    elif evidence.stage == SupplyConsumptionStage.INTEGRATED:
                        telemetry.supply_assets_consumed += int(
                            old not in (
                                SupplyConsumptionStage.CONSUMED,
                                SupplyConsumptionStage.INTEGRATED,
                            )
                        )
                        telemetry.supply_assets_integrated += 1
                        if obligation.role == SupplyObligationRole.CRITICAL:
                            telemetry.critical_supply_consumed += int(
                                old not in (
                                    SupplyConsumptionStage.CONSUMED,
                                    SupplyConsumptionStage.INTEGRATED,
                                )
                            )
                            telemetry.critical_supply_integrated += 1
                    elif evidence.stage == SupplyConsumptionStage.INVALIDATED:
                        telemetry.supply_assets_invalidated += 1
            closure_history = node.dependency_closure_history
            if successor.dependency_closure_result is not None:
                closure_history = closure_history + (
                    successor.dependency_closure_result,
                )
            ledger = node.structural_investment_ledger
            if successor.structural_investment is not None:
                investment = successor.structural_investment
                ledger = ledger.add(investment)
                kind = investment.kind.value
                telemetry.investments_created_by_kind[kind] = (
                    telemetry.investments_created_by_kind.get(kind, 0) + 1
                )
                telemetry.structural_investment_paid_cost += investment.paid_cost_invested
                telemetry.structural_expected_harvest += len(investment.expected_harvest)
                telemetry.structural_actual_harvest += len(investment.actual_harvest)
                telemetry.unharvested_investments += int(
                    investment.status
                    in (
                        StructuralInvestmentStatus.ACTIVE,
                        StructuralInvestmentStatus.PARTIALLY_HARVESTED,
                    )
                )
                _append_bounded(
                    telemetry.structural_investment_timeline,
                    (
                        ng,
                        investment.objective_id,
                        investment.kind.value,
                        investment.paid_cost_invested,
                        len(investment.actual_harvest),
                    ),
                    config.max_timeline_entries,
                )
            child_continuation = successor.continuation_credit
            if child_continuation is not None:
                telemetry.continuation_credits_created += 1
                _append_bounded(
                    telemetry.continuation_timeline,
                    (
                        ng,
                        child_continuation.objective_id,
                        child_continuation.credit_id,
                        "CREATED",
                    ),
                    config.max_timeline_entries,
                )
            elif successor_matches_continuation(successor, node.continuation_credit):
                child_continuation = node.continuation_credit
            if child_continuation is not None and child_continuation.is_live:
                telemetry.continuation_descendants_admitted += 1
            child_milestone_ledger = node.milestone_ledger
            child_active_milestone: Optional[StrategicMilestone] = None
            child_residual_target: Optional[ResidualMilestoneTarget] = None
            milestone_result = successor.milestone_result
            if milestone_result is not None:
                child_milestone_ledger = child_milestone_ledger.add(milestone_result)
                if milestone_result.status in (
                    StrategicMilestoneStatus.ACTIVE,
                    StrategicMilestoneStatus.ADVANCED,
                    StrategicMilestoneStatus.BOUNDED_MISS,
                ):
                    child_active_milestone = milestone_result.milestone
                    child_residual_target = successor.residual_target
            if successor.persistent_target is not None:
                child_active_milestone = replace(
                    successor.persistent_target,
                    target_identity=milestone_target_identity(successor.persistent_target),
                    created_depth=node.depth + 1,
                    created_elapsed_seconds=time.perf_counter() - started,
                    status=StrategicMilestoneStatus.ACTIVE,
                )
                child_residual_target = successor.residual_target
                telemetry.semantic_targets_created += 1
                _append_bounded(
                    telemetry.semantic_target_timeline,
                    (
                        ng,
                        child_active_milestone.milestone_id,
                        child_active_milestone.kind.value,
                        "created by purposeful Deal obligation",
                    ),
                    config.max_timeline_entries,
                )
            elif milestone_result is None and successor.kind not in _DEAL_ACTION_KINDS:
                if (
                    node.active_milestone is not None
                    and successor.source_project_id
                    in (
                        node.active_milestone.objective_id,
                        node.active_milestone.campaign_id,
                    )
                ):
                    child_active_milestone = node.active_milestone
                    child_residual_target = node.active_residual_target
                elif node.analysis.milestone_portfolio is not None:
                    selected_milestone = next(
                        (
                            item
                            for item in node.analysis.milestone_portfolio.milestones
                            if successor.source_project_id
                            in (item.objective_id, item.campaign_id)
                        ),
                        None,
                    )
                    if selected_milestone is not None:
                        child_active_milestone = replace(
                            selected_milestone,
                            created_depth=node.depth + 1,
                            created_elapsed_seconds=time.perf_counter() - started,
                        )
                        telemetry.milestones_activated += 1
            if (
                child_active_milestone is not None
                and node.active_milestone is None
                and successor.persistent_target is None
            ):
                telemetry.semantic_targets_created += 1
                _append_bounded(
                    telemetry.semantic_target_timeline,
                    (
                        ng,
                        child_active_milestone.milestone_id,
                        child_active_milestone.kind.value,
                        "activated by a target-compatible strategic successor",
                    ),
                    config.max_timeline_entries,
                )
            child_obligations = node.post_deal_obligations
            if successor.post_deal_obligation is not None:
                child_obligations = child_obligations + (
                    successor.post_deal_obligation,
                )
                telemetry.post_deal_obligations_created += 1
                _append_bounded(
                    telemetry.post_deal_obligation_timeline,
                    (
                        ng,
                        successor.post_deal_obligation.obligation_id,
                        successor.post_deal_obligation.status.value,
                        successor.post_deal_obligation.last_reason,
                    ),
                    config.max_timeline_entries,
                )
            if successor.kind in _DEAL_ACTION_KINDS:
                telemetry.successive_deals_before_obligation_conversion += sum(
                    item.unresolved_actionable for item in node.post_deal_obligations
                )
            child_target_lineage = node.target_grant_lineage
            if successor.target_grant_entry is not None:
                child_target_lineage = child_target_lineage.with_entry(
                    successor.target_grant_entry
                )
                if successor.target_boundary_trace is not None:
                    child_target_lineage = child_target_lineage.with_trace(
                        successor.target_boundary_trace
                    )
            child_source_ledger = node.source_completion_ledger
            admitted_source_traces = []
            for source_trace in successor.source_completion_traces:
                admitted_trace = source_trace.advance(
                    SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION,
                    detail="exact TT admitted the replay-valid source-completion state",
                )
                if source_trace.event.event_id in (
                    successor.target_grant_entry.source_completion_event_ids
                    if successor.target_grant_entry is not None
                    else ()
                ):
                    admitted_trace = admitted_trace.advance(
                        SourceCompletionStage.LINEAGE_PRESERVED,
                        disposition=SourceCompletionDisposition.PRESERVED,
                        detail="admitted node retains source harvest in target lineage",
                    )
                admitted_source_traces.append(admitted_trace)
                child_source_ledger = child_source_ledger.with_trace(admitted_trace)
                _record_source_completion_trace(
                    telemetry, admitted_trace, config.max_timeline_entries
                )
            if cash_out_assessment is not None:
                updated_traces = []
                consumed_ids = set(cash_out_assessment.source_consumed_event_ids)
                integrated_ids = set(cash_out_assessment.source_integrated_event_ids)
                for source_trace in child_source_ledger.traces:
                    updated_trace = source_trace
                    if source_trace.event.event_id in consumed_ids:
                        updated_trace = updated_trace.advance(
                            SourceCompletionStage.SOURCE_CONSUMED,
                            detail="cash-out descendant consumes the completed source",
                        )
                    if source_trace.event.event_id in integrated_ids:
                        updated_trace = updated_trace.advance(
                            SourceCompletionStage.SOURCE_INTEGRATED,
                            detail="cash-out descendant integrates the source into same-suit structure",
                        )
                    updated_traces.append(updated_trace)
                    if updated_trace.stages != source_trace.stages:
                        _record_source_completion_trace(
                            telemetry, updated_trace, config.max_timeline_entries
                        )
                child_source_ledger = replace(
                    child_source_ledger, traces=tuple(updated_traces)
                )
            child_completion_cash_out = None
            if admitted_source_traces:
                telemetry.admitted_completion_states += 1
                metrics = _completion_structural_metrics(
                    node,
                    successor,
                    child_stage0,
                    admitted_source_traces,
                    corrected_g=ng,
                )
                child_completion_cash_out = make_completion_cash_out_opportunity(
                    successor.end_state,
                    corrected_g=ng,
                    traces=admitted_source_traces,
                    successor_family=successor.category,
                    metrics=metrics,
                    exact_tt_admitted=True,
                    independently_replay_verified=successor.independent_replay_verified,
                    spent_event_ids=cash_out_spent_event_ids,
                )
                if child_completion_cash_out is not None:
                    telemetry.completion_cash_out_qualified += 1
                    _record_completion_opportunity(
                        telemetry,
                        child_completion_cash_out,
                        config.max_timeline_entries,
                    )
                else:
                    telemetry.completion_nonqualifying_admitted += 1
                    event_ids = tuple(
                        dict.fromkeys(
                            item.event.event_id for item in admitted_source_traces
                        )
                    )
                    target_ids = tuple(
                        dict.fromkeys(
                            item.event.semantic_target_fingerprint
                            for item in admitted_source_traces
                        )
                    )
                    trace_id = hashlib.sha256(
                        repr(
                            (
                                canonical_state_key(successor.end_state),
                                event_ids,
                                "nonqualifying-admitted-completion",
                            )
                        ).encode("utf-8")
                    ).hexdigest()[:16]
                    _append_bounded(
                        telemetry.completion_selection_traces,
                        CompletionCashOutTrace(
                            trace_id,
                            event_ids,
                            target_ids,
                            canonical_state_key(successor.end_state),
                            _state_hash(successor.end_state),
                            ng,
                            successor.category,
                            metrics,
                            CompletionCashOutStatus.INVALIDATED,
                            None,
                            None,
                            None,
                            True,
                            False,
                            False,
                            False,
                            CompletionCashOutDisposition.INVALIDATED_BY_FRESH_FACT,
                            (
                                "fresh exact admitted state did not preserve a new, "
                                "strong, unspent completion context"
                            ),
                        ),
                        config.max_timeline_entries,
                    )
            completion_context_by_state[
                canonical_state_key(successor.end_state)
            ] = child_source_ledger
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
                active_contracts,
                node.deal_contract_outcomes,
                (
                    node.protected_conversion_lane
                    if successor is protected_successor
                    else None
                ),
                pre_geometry,
                node.deal_contract_history + successor.deal_contracts,
                node.deal_outcome_history,
                child_supply_results,
                closure_history,
                child_audit_history,
                ledger,
                child_continuation,
                child_active_milestone,
                child_milestone_ledger,
                child_residual_target,
                child_obligations,
                child_target_lineage,
                child_source_ledger,
                child_completion_cash_out,
                node.completion_harvest_history
                + ((cash_out_assessment,) if cash_out_assessment is not None else ()),
                bool(
                    active_cash_out is not None
                    and successor.kind in _DEAL_ACTION_KINDS
                ),
                child_schedule,
                child_epoch_transition,
            )
            if child.analysis is not None:
                if child.analysis.budget.proof_prunable:
                    telemetry.proof_pruned += 1
                    telemetry.count_suppression("admissible incumbent bound")
                    continue
            heapq.heappush(frontier, (_node_priority(child), uid, child))
            telemetry.retained += 1
            telemetry.lazy_children_admitted += 1
            telemetry.advanced_descendants_admitted += int(
                successor.target_grant_entry is not None
                and successor.target_grant_entry.evidence.has_portable_harvest
            )
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

        if active_cash_out is not None:
            harvest = combine_completion_harvest(
                active_cash_out, cash_out_assessments
            )
            _record_completion_harvest(
                telemetry,
                active_cash_out,
                harvest,
                config.max_timeline_entries,
            )
            telemetry.completion_deals_admitted_after_cash_out += int(
                cash_out_deal_admitted
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

        frontier = _reserve_completion_representative(
            frontier,
            tt=tt,
            spent_event_ids=tuple(cash_out_spent_event_ids),
            telemetry=telemetry,
        )
        frontier = _reserve_epoch_transition_representative(
            frontier,
            tt=tt,
            spent_opportunity_ids=tuple(epoch_transition_spent_ids),
            telemetry=telemetry,
        )
        if len(frontier) > config.max_frontier_size:
            mature_before = {
                item[1]: item[2]
                for item in frontier
                if item[2].active_residual_target is not None
                and item[2].target_grant_lineage.active_for(
                    item[2].active_residual_target.identity.fingerprint
                ) is not None
            }
            frontier = _trim_frontier_with_checkpoint_diversity(
                frontier,
                maximum=config.max_frontier_size,
                portfolio=checkpoint_portfolio,
                pre_foundation_portfolio=pre_foundation_portfolio,
                telemetry=telemetry,
            )
            retained_ids = {item[1] for item in frontier}
            trimmed_mature = [
                node for key, node in mature_before.items() if key not in retained_ids
            ]
            telemetry.advanced_descendants_trimmed += len(trimmed_mature)
            minimum_retained_g = min((item[2].g for item in frontier), default=10**9)
            telemetry.mature_targets_lost_to_lower_g += sum(
                minimum_retained_g < node.g for node in trimmed_mature
            )
            heapq.heapify(frontier)
            telemetry.frontier_trimmed += 1
            telemetry.heuristic_pruned += 1
            telemetry.count_suppression("bounded frontier trim; not proof")

    telemetry.tt_new = tt.new_entries
    telemetry.tt_improved = tt.improvements
    telemetry.tt_suppressed = max(telemetry.tt_suppressed, tt.suppressions)
    telemetry.component_timings = deadline.timing_snapshot()
    _publish_tactical_resource_telemetry(
        telemetry,
        resource_allocator.ledger,
        maximum_timeline_entries=config.max_timeline_entries,
    )
    elapsed = time.perf_counter() - started
    if current_incumbent is not None and (
        first_solution is not None or initial_incumbent_cost is None
    ):
        status = AnytimeControllerStatus.SOLVED
    elif frontier:
        status = AnytimeControllerStatus.RESOURCE_LIMIT
    else:
        status = AnytimeControllerStatus.FRONTIER_EXHAUSTED
    # Reconcile generated source-completion successors which were removed by
    # bounded strategic-family selection before reaching the exact-TT loop.
    # Exact-TT rejections are labelled at their rejection site above; this
    # final pass covers every other pre-admission loss without changing search.
    for source_trace in tuple(telemetry.source_completion_traces):
        if source_trace.successor_created and not source_trace.controller_admitted:
            lost = replace(
                source_trace,
                disposition=SourceCompletionDisposition.ADMISSION_LOSS,
                loss_reason=SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS,
                detail=(
                    "replay-valid source-completion successor did not survive "
                    "bounded strategic admission"
                ),
            )
            _record_source_completion_trace(
                telemetry, lost, config.max_timeline_entries
            )
    resource_ended = stop_reason in {
        "wall-clock limit",
        "strategic expansion limit",
        "tactical node limit",
        "deadline before fresh Stage-1 expansion analysis",
    }
    for index, trace in enumerate(tuple(telemetry.completion_selection_traces)):
        if trace.cash_out_spent or trace.disposition in {
            CompletionCashOutDisposition.CASH_OUT_SPENT,
            CompletionCashOutDisposition.SUPERSEDED_BY_LOWER_G,
            CompletionCashOutDisposition.INVALIDATED_BY_FRESH_FACT,
            CompletionCashOutDisposition.EXACT_DUPLICATE_SUPPRESSED,
        }:
            continue
        if resource_ended:
            telemetry.completion_representatives_expired_before_expansion += 1
            telemetry.completion_selection_traces[index] = replace(
                trace,
                qualifying_status=CompletionCashOutStatus.EXPIRED,
                disposition=CompletionCashOutDisposition.EXPIRED_BEFORE_EXPANSION,
                reason=(
                    "global deadline/expansion ceiling ended before the admitted "
                    "completion could receive its reserved expansion"
                ),
            )
        else:
            telemetry.completion_admitted_not_selected += 1
            telemetry.completion_selection_traces[index] = replace(
                trace,
                disposition=(
                    CompletionCashOutDisposition.COMPLETION_ADMITTED_NOT_SELECTED
                ),
                reason=(
                    "admitted qualifying completion left the frontier without its "
                    "bounded representative expansion"
                ),
            )
    selected_source_ledger = best_progress_node.source_completion_ledger
    selected_traces = []
    for source_trace in selected_source_ledger.traces:
        selected_trace = source_trace.advance(
            SourceCompletionStage.SELECTED_PATH_COMPLETION,
            disposition=SourceCompletionDisposition.PRESERVED,
            detail="the final best-progress route includes this source completion",
        )
        if source_trace.event.consumed:
            selected_trace = selected_trace.advance(
                SourceCompletionStage.SOURCE_CONSUMED,
                detail="selected route consumes the completed source requirement",
            )
        if source_trace.event.integrated:
            selected_trace = selected_trace.advance(
                SourceCompletionStage.SOURCE_INTEGRATED,
                detail="selected route integrates the completed source into same-suit structure",
            )
        selected_traces.append(selected_trace)
        _record_source_completion_trace(
            telemetry, selected_trace, config.max_timeline_entries
        )
    selected_source_ledger = replace(
        selected_source_ledger, traces=tuple(selected_traces)
    )
    best_progress_node = replace(
        best_progress_node, source_completion_ledger=selected_source_ledger
    )
    if best_node.node_id == best_progress_node.node_id:
        best_node = best_progress_node
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
        pre_foundation_portfolio=pre_foundation_portfolio,
        successive_deal_audit=tuple(
            most_foundations_node.successive_deal_audit_history
        ),
        tactical_resource_ledger=resource_allocator.ledger,
        milestone_conversion_ledger=most_foundations_node.milestone_ledger,
        target_grant_lineage=best_progress_node.target_grant_lineage,
        source_completion_ledger=selected_source_ledger,
    )
