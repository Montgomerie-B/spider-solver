"""Critical-path tactical resource allocation for the anytime controller.

The allocator schedules existing bounded tactical realisers.  It does not
generate legal moves, alter structural state identity, or prove a branch dead.
Every request, grant, outcome, promotion, and miss is descriptive ordering
evidence local to one exact strategic context.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathSummary,
    CampaignDependencyType,
)
from spider.planner.structural_construction import (
    ConstructionDisposition,
    StructuralConstructionAnalysis,
)
from spider.state_identity import CanonicalStateKey


class TacticalObjectiveKind(str, Enum):
    DEPENDENCY_CLOSURE = "DEPENDENCY_CLOSURE"
    RECEIVER_CREATION = "RECEIVER_CREATION"
    INTERVAL_ASSEMBLY = "INTERVAL_ASSEMBLY"
    OVERLAY_CLEARING = "OVERLAY_CLEARING"
    SUPPLY_CONSUMPTION = "SUPPLY_CONSUMPTION"
    RUN_CONSTRUCTION = "RUN_CONSTRUCTION"
    EXCAVATION = "EXCAVATION"
    WORKSPACE = "WORKSPACE"
    FOUNDATION_REMOVAL = "FOUNDATION_REMOVAL"
    DEAL_PREPARATION = "DEAL_PREPARATION"
    DEAL_EVALUATION = "DEAL_EVALUATION"
    RAW_FALLBACK = "RAW_FALLBACK"


class TacticalRealizerKind(str, Enum):
    DEPENDENCY_CLOSURE = "DEPENDENCY_CLOSURE"
    ECONOMIC_PROJECT = "ECONOMIC_PROJECT"
    CAMPAIGN_CURRENT_EPOCH = "CAMPAIGN_CURRENT_EPOCH"
    CAMPAIGN_REMOVAL = "CAMPAIGN_REMOVAL"
    TERMINAL_ASSEMBLY = "TERMINAL_ASSEMBLY"
    CAMPAIGN_CORRIDOR = "CAMPAIGN_CORRIDOR"
    RUN_CONSTRUCTION = "RUN_CONSTRUCTION"
    DEAL_TIMING = "DEAL_TIMING"
    RAW_FALLBACK = "RAW_FALLBACK"


class TacticalResourceTier(IntEnum):
    PROBE = 0
    SHALLOW = 1
    COMMITTED = 2
    TERMINAL = 3


class TacticalResourceDecision(str, Enum):
    PROMOTE = "PROMOTE"
    CONTINUE_SAME_TIER = "CONTINUE_SAME_TIER"
    DEMOTE = "DEMOTE"
    SUSPEND_FOR_STATE = "SUSPEND_FOR_STATE"
    SWITCH_OBJECTIVE = "SWITCH_OBJECTIVE"
    TERMINAL_ESCALATION = "TERMINAL_ESCALATION"


class RemovalAllocationPolicy(str, Enum):
    REMOVAL_DIAGNOSTIC_ONLY = "REMOVAL_DIAGNOSTIC_ONLY"
    REMOVAL_NOT_QUALIFIED = "REMOVAL_NOT_QUALIFIED"
    REMOVAL_PROMOTED = "REMOVAL_PROMOTED"
    REMOVAL_FULL_BUDGET = "REMOVAL_FULL_BUDGET"


@dataclass(frozen=True)
class TacticalResourceTierSpec:
    tier: TacticalResourceTier
    max_added_cost: int
    max_nodes: int
    max_seconds: float

    def __post_init__(self) -> None:
        if self.max_added_cost <= 0 or self.max_nodes <= 0 or self.max_seconds <= 0:
            raise ValueError("tactical tier limits must be positive")

    @property
    def fingerprint(self) -> Tuple[int, int, int, int]:
        return (
            int(self.tier),
            self.max_added_cost,
            self.max_nodes,
            int(round(self.max_seconds * 1_000)),
        )


@dataclass(frozen=True)
class TacticalResourceAllocatorConfig:
    """Generic tranches carved from the existing controller limits."""

    tiers: Tuple[TacticalResourceTierSpec, ...] = field(
        default_factory=lambda: (
            TacticalResourceTierSpec(TacticalResourceTier.PROBE, 2, 128, 0.10),
            TacticalResourceTierSpec(TacticalResourceTier.SHALLOW, 4, 512, 0.35),
            TacticalResourceTierSpec(TacticalResourceTier.COMMITTED, 8, 2_000, 1.25),
            TacticalResourceTierSpec(TacticalResourceTier.TERMINAL, 18, 8_000, 2.00),
        )
    )
    repeated_misses_before_suspend: int = 2
    max_campaign_demands: int = 4
    max_granted_nodes_per_expansion: int = 12_000
    max_granted_seconds_per_expansion: float = 4.0
    reserve_nodes_for_alternate: int = 128

    def __post_init__(self) -> None:
        if tuple(item.tier for item in self.tiers) != tuple(TacticalResourceTier):
            raise ValueError("resource tiers must be ordered PROBE through TERMINAL")
        if self.repeated_misses_before_suspend <= 0 or self.max_campaign_demands <= 0:
            raise ValueError("allocator limits must be positive")
        if self.max_granted_nodes_per_expansion <= 0 or self.max_granted_seconds_per_expansion <= 0:
            raise ValueError("per-expansion allocation limits must be positive")
        if self.reserve_nodes_for_alternate < 0:
            raise ValueError("alternate reservation cannot be negative")

    def spec(self, tier: TacticalResourceTier) -> TacticalResourceTierSpec:
        return self.tiers[int(tier)]

    @property
    def fingerprint(self) -> Tuple:
        return (
            tuple(item.fingerprint for item in self.tiers),
            self.repeated_misses_before_suspend,
            self.max_campaign_demands,
            self.max_granted_nodes_per_expansion,
            int(round(self.max_granted_seconds_per_expansion * 1_000)),
            self.reserve_nodes_for_alternate,
        )


@dataclass(frozen=True)
class TacticalDemand:
    objective: TacticalObjectiveKind
    realizer: TacticalRealizerKind
    reason: str
    campaign_id: Optional[str] = None
    campaign_suit: Optional[str] = None
    target_dependency_id: Optional[str] = None
    prerequisites: Tuple[str, ...] = ()
    initial_tier: TacticalResourceTier = TacticalResourceTier.PROBE
    promotion_condition: str = "named campaign-specific structural harvest"
    downstream_unlock_count: int = 0
    source_depth: int = 0
    receiver_missing: bool = False
    workspace_required: bool = False
    supplied_asset_waiting: bool = False
    interval_missing: bool = False
    overlay_present: bool = False
    terminal_qualified: bool = False
    continuation_attention: bool = False
    construction_opportunity_id: Optional[str] = None
    construction_disposition: Optional[ConstructionDisposition] = None
    removal_policy: RemovalAllocationPolicy = RemovalAllocationPolicy.REMOVAL_NOT_QUALIFIED
    proof_pruning_allowed: bool = False

    def ordering_key(self) -> Tuple:
        return (
            0 if self.terminal_qualified else 1,
            0 if self.continuation_attention else 1,
            0 if self.objective != TacticalObjectiveKind.FOUNDATION_REMOVAL else 1,
            -self.downstream_unlock_count,
            -int(self.supplied_asset_waiting),
            -int(self.receiver_missing or self.workspace_required),
            self.source_depth,
            int(self.initial_tier),
            self.campaign_id or "",
            self.objective.value,
            self.realizer.value,
        )

    @property
    def critical_path_fingerprint(self) -> str:
        payload = repr(
            (
                self.campaign_id,
                self.target_dependency_id,
                self.prerequisites,
                self.downstream_unlock_count,
                self.source_depth,
                self.receiver_missing,
                self.workspace_required,
                self.supplied_asset_waiting,
                self.interval_missing,
                self.overlay_present,
                self.terminal_qualified,
            )
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:16]


@dataclass(frozen=True)
class TacticalDemandPortfolio:
    demands: Tuple[TacticalDemand, ...]
    proof_pruning_allowed: bool = False

    def for_realizer(
        self,
        realizer: TacticalRealizerKind,
        *,
        campaign_id: Optional[str] = None,
    ) -> Tuple[TacticalDemand, ...]:
        return tuple(
            item
            for item in self.demands
            if item.realizer == realizer
            and (campaign_id is None or item.campaign_id == campaign_id)
        )

    def best_for(
        self,
        realizer: TacticalRealizerKind,
        *,
        campaign_id: Optional[str] = None,
    ) -> Optional[TacticalDemand]:
        items = self.for_realizer(realizer, campaign_id=campaign_id)
        return min(items, key=lambda item: item.ordering_key()) if items else None

    @property
    def campaign_ids(self) -> Tuple[str, ...]:
        return tuple(dict.fromkeys(item.campaign_id for item in self.demands if item.campaign_id))


@dataclass(frozen=True)
class TacticalResourceKey:
    state_key: CanonicalStateKey
    objective: TacticalObjectiveKind
    campaign_id: Optional[str]
    realizer: TacticalRealizerKind
    allocator_config_fingerprint: Tuple
    critical_path_fingerprint: str
    terminal_qualified: bool


@dataclass(frozen=True)
class TacticalResourceRequest:
    request_id: str
    key: TacticalResourceKey
    demand: TacticalDemand
    requested_tier: TacticalResourceTier
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TacticalResourceGrant:
    request_id: str
    key: TacticalResourceKey
    tier: TacticalResourceTier
    nodes_granted: int
    seconds_granted: float
    max_added_cost: int
    tier_fingerprint: Tuple[int, int, int, int]
    removal_policy: RemovalAllocationPolicy
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TacticalHarvestRate:
    harvest_events_per_second: float
    harvest_events_per_thousand_nodes: float
    dependencies_closed_per_second: float
    permanent_adjacencies_per_second: float


@dataclass(frozen=True)
class TacticalResourceOutcome:
    request_id: str
    key: TacticalResourceKey
    tier: TacticalResourceTier
    nodes_consumed: int
    seconds_consumed: float
    corrected_paid_cost: int
    legal_successor_count: int
    dependencies_closed: int = 0
    overlays_cleared: int = 0
    receivers_created: int = 0
    supply_consumed_or_integrated: int = 0
    permanent_adjacencies_created: int = 0
    strategically_relevant_sources_exposed: int = 0
    workspace_created_or_recovered: int = 0
    intervals_assembled: int = 0
    concrete_deal_unlocks: int = 0
    terminal_qualification_before: bool = False
    terminal_qualification_after: bool = False
    foundation_removals: int = 0
    blocker_before: Optional[str] = None
    blocker_after: Optional[str] = None
    repeated_equivalent_miss: bool = False
    decision: TacticalResourceDecision = TacticalResourceDecision.CONTINUE_SAME_TIER
    reason: str = ""
    proof_pruning_allowed: bool = False

    @property
    def named_harvest_events(self) -> int:
        return sum(
            (
                self.dependencies_closed,
                self.overlays_cleared,
                self.receivers_created,
                self.supply_consumed_or_integrated,
                self.permanent_adjacencies_created,
                self.strategically_relevant_sources_exposed,
                self.workspace_created_or_recovered,
                self.intervals_assembled,
                self.concrete_deal_unlocks,
                int(self.terminal_qualification_after and not self.terminal_qualification_before),
                self.foundation_removals,
            )
        )

    @property
    def has_named_harvest(self) -> bool:
        return self.named_harvest_events > 0

    @property
    def harvest_rate(self) -> TacticalHarvestRate:
        seconds = max(self.seconds_consumed, 1e-9)
        nodes = max(self.nodes_consumed, 1)
        return TacticalHarvestRate(
            self.named_harvest_events / seconds,
            self.named_harvest_events * 1_000.0 / nodes,
            self.dependencies_closed / seconds,
            self.permanent_adjacencies_created / seconds,
        )


@dataclass(frozen=True)
class TacticalResourceEvidence:
    key: TacticalResourceKey
    latest_tier: TacticalResourceTier
    consecutive_zero_harvest_misses: int
    successful_harvests: int
    suspended_for_state: bool
    latest_decision: TacticalResourceDecision
    latest_blocker: Optional[str]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class TacticalResourceLedger:
    requests: Tuple[TacticalResourceRequest, ...] = ()
    grants: Tuple[TacticalResourceGrant, ...] = ()
    outcomes: Tuple[TacticalResourceOutcome, ...] = ()
    proof_pruning_allowed: bool = False

    @property
    def total_nodes_granted(self) -> int:
        return sum(item.nodes_granted for item in self.grants)

    @property
    def total_nodes_consumed(self) -> int:
        return sum(item.nodes_consumed for item in self.outcomes)

    @property
    def total_seconds_granted(self) -> float:
        return sum(item.seconds_granted for item in self.grants)

    @property
    def total_seconds_consumed(self) -> float:
        return sum(item.seconds_consumed for item in self.outcomes)

    @property
    def total_harvest_events(self) -> int:
        return sum(item.named_harvest_events for item in self.outcomes)


@dataclass
class _MutableEvidence:
    latest_tier: TacticalResourceTier
    consecutive_zero_harvest_misses: int = 0
    successful_harvests: int = 0
    suspended_for_state: bool = False
    latest_decision: TacticalResourceDecision = TacticalResourceDecision.CONTINUE_SAME_TIER
    latest_blocker: Optional[str] = None


def _objective_for_dependency(kind: CampaignDependencyType) -> TacticalObjectiveKind:
    return {
        CampaignDependencyType.RECEIVER_MISSING: TacticalObjectiveKind.RECEIVER_CREATION,
        CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED: TacticalObjectiveKind.RECEIVER_CREATION,
        CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL: TacticalObjectiveKind.INTERVAL_ASSEMBLY,
        CampaignDependencyType.FRAGMENT_ORDERING: TacticalObjectiveKind.INTERVAL_ASSEMBLY,
        CampaignDependencyType.MIXED_OVERLAY: TacticalObjectiveKind.OVERLAY_CLEARING,
        CampaignDependencyType.SUPPLIED_NOT_CONSUMED: TacticalObjectiveKind.SUPPLY_CONSUMPTION,
        CampaignDependencyType.SOURCE_BURIED: TacticalObjectiveKind.EXCAVATION,
        CampaignDependencyType.WORKSPACE_REQUIRED: TacticalObjectiveKind.WORKSPACE,
        CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE: TacticalObjectiveKind.DEPENDENCY_CLOSURE,
    }[kind]


def derive_tactical_demands(
    critical_paths: Sequence[CampaignCriticalPathSummary],
    *,
    campaign_suits: Optional[Mapping[str, str]] = None,
    construction: Optional[StructuralConstructionAnalysis] = None,
    continuation_objective_id: Optional[str] = None,
    deal_available: bool = False,
) -> TacticalDemandPortfolio:
    """Translate fresh structural facts into an inspectable tactical portfolio."""

    demands = []
    campaign_suits = campaign_suits or {}
    for summary in critical_paths:
        leading = summary.entries[0] if summary.entries else None
        continuation = summary.campaign_id == continuation_objective_id
        if leading is not None:
            objective = _objective_for_dependency(leading.kind)
            base = TacticalDemand(
                objective=objective,
                realizer=TacticalRealizerKind.DEPENDENCY_CLOSURE,
                reason=(
                    f"critical-path bottleneck {leading.dependency_id}: {leading.rationale}"
                ),
                campaign_id=summary.campaign_id,
                campaign_suit=campaign_suits.get(summary.campaign_id),
                target_dependency_id=leading.dependency_id,
                prerequisites=leading.prerequisites,
                initial_tier=TacticalResourceTier.PROBE,
                downstream_unlock_count=leading.downstream_dependencies_unlocked,
                source_depth=leading.source_depth,
                receiver_missing=summary.receiver_missing,
                workspace_required=summary.workspace_required,
                supplied_asset_waiting=summary.supplied_asset_waiting,
                interval_missing=summary.interval_missing,
                overlay_present=summary.overlay_present,
                terminal_qualified=summary.terminal_qualified,
                continuation_attention=continuation,
            )
            demands.append(base)

        qualified = summary.terminal_qualified
        removal_reason = (
            "terminal predicate is satisfied; removal may receive the strongest bounded tier"
            if qualified
            else (
                f"removal not terminal-qualified; prerequisite {summary.bottleneck_dependency_id} "
                "receives serious compute first"
            )
        )
        demands.append(
            TacticalDemand(
                TacticalObjectiveKind.FOUNDATION_REMOVAL,
                (
                    TacticalRealizerKind.TERMINAL_ASSEMBLY
                    if qualified
                    else TacticalRealizerKind.CAMPAIGN_REMOVAL
                ),
                removal_reason,
                campaign_id=summary.campaign_id,
                campaign_suit=campaign_suits.get(summary.campaign_id),
                target_dependency_id=summary.bottleneck_dependency_id,
                prerequisites=summary.prerequisite_dependency_ids,
                initial_tier=(
                    TacticalResourceTier.TERMINAL
                    if qualified
                    else TacticalResourceTier.PROBE
                ),
                promotion_condition="terminal qualification or foundation removal",
                source_depth=summary.deepest_source_depth,
                receiver_missing=summary.receiver_missing,
                workspace_required=summary.workspace_required,
                supplied_asset_waiting=summary.supplied_asset_waiting,
                interval_missing=summary.interval_missing,
                overlay_present=summary.overlay_present,
                terminal_qualified=qualified,
                continuation_attention=continuation,
                removal_policy=(
                    RemovalAllocationPolicy.REMOVAL_FULL_BUDGET
                    if qualified
                    else RemovalAllocationPolicy.REMOVAL_DIAGNOSTIC_ONLY
                ),
            )
        )
        if qualified:
            demands.append(
                TacticalDemand(
                    TacticalObjectiveKind.FOUNDATION_REMOVAL,
                    TacticalRealizerKind.CAMPAIGN_CORRIDOR,
                    "terminal-qualified campaign may receive a bounded corridor alternative",
                    campaign_id=summary.campaign_id,
                    campaign_suit=campaign_suits.get(summary.campaign_id),
                    target_dependency_id=summary.bottleneck_dependency_id,
                    initial_tier=TacticalResourceTier.TERMINAL,
                    promotion_condition="foundation removal",
                    terminal_qualified=True,
                    continuation_attention=continuation,
                    removal_policy=RemovalAllocationPolicy.REMOVAL_PROMOTED,
                )
            )

    if construction is not None:
        for opportunity in construction.opportunities:
            if opportunity.disposition != ConstructionDisposition.MAKE_NOW:
                continue
            demands.append(
                TacticalDemand(
                    TacticalObjectiveKind.RUN_CONSTRUCTION,
                    TacticalRealizerKind.RUN_CONSTRUCTION,
                    "; ".join(opportunity.rationale),
                    campaign_suit=opportunity.suit,
                    initial_tier=(
                        TacticalResourceTier.SHALLOW
                        if opportunity.run_length_after > 2
                        else TacticalResourceTier.PROBE
                    ),
                    promotion_condition="permanent same-suit adjacency created",
                    construction_opportunity_id=opportunity.opportunity_id,
                    construction_disposition=opportunity.disposition,
                )
            )

    if deal_available:
        demands.append(
            TacticalDemand(
                TacticalObjectiveKind.DEAL_EVALUATION,
                TacticalRealizerKind.DEAL_TIMING,
                "Deal is legal and retained as a first-class exact-stock alternative",
                initial_tier=TacticalResourceTier.PROBE,
                promotion_condition="concrete stock unlock or preparation advantage",
            )
        )
    demands.append(
        TacticalDemand(
            TacticalObjectiveKind.RAW_FALLBACK,
            TacticalRealizerKind.RAW_FALLBACK,
            "raw legal play remains available at broad credit",
            initial_tier=TacticalResourceTier.PROBE,
        )
    )
    demands.sort(key=lambda item: item.ordering_key())
    return TacticalDemandPortfolio(tuple(demands))


class TacticalResourceAllocator:
    """State-local progressive scheduler with no proof authority."""

    def __init__(self, config: TacticalResourceAllocatorConfig = TacticalResourceAllocatorConfig()):
        self.config = config
        self._memory: Dict[TacticalResourceKey, _MutableEvidence] = {}
        self._requests = []
        self._grants = []
        self._outcomes = []
        self._expansion_nodes_granted = 0
        self._expansion_seconds_granted = 0.0

    def begin_expansion(self) -> None:
        self._expansion_nodes_granted = 0
        self._expansion_seconds_granted = 0.0

    def _key(self, state_key: CanonicalStateKey, demand: TacticalDemand) -> TacticalResourceKey:
        return TacticalResourceKey(
            state_key,
            demand.objective,
            demand.campaign_id,
            demand.realizer,
            self.config.fingerprint,
            demand.critical_path_fingerprint,
            demand.terminal_qualified,
        )

    def request(
        self,
        state_key: CanonicalStateKey,
        demand: TacticalDemand,
    ) -> Tuple[TacticalResourceRequest, Optional[TacticalResourceGrant]]:
        key = self._key(state_key, demand)
        memory = self._memory.get(key)
        tier = demand.initial_tier
        reason = demand.reason
        if memory is not None:
            if memory.suspended_for_state:
                tier = memory.latest_tier
            elif memory.latest_decision in (
                TacticalResourceDecision.PROMOTE,
                TacticalResourceDecision.TERMINAL_ESCALATION,
            ):
                tier = TacticalResourceTier(min(int(memory.latest_tier) + 1, int(TacticalResourceTier.TERMINAL)))
            elif memory.latest_decision == TacticalResourceDecision.DEMOTE:
                tier = TacticalResourceTier(max(int(memory.latest_tier) - 1, int(TacticalResourceTier.PROBE)))
            else:
                tier = memory.latest_tier

        if tier == TacticalResourceTier.TERMINAL and not demand.terminal_qualified:
            tier = TacticalResourceTier.COMMITTED
        if tier >= TacticalResourceTier.COMMITTED and not demand.terminal_qualified:
            if memory is None or memory.successful_harvests == 0:
                tier = TacticalResourceTier.SHALLOW

        request_id = hashlib.sha256(
            repr((key, len(self._requests), int(tier))).encode("utf-8")
        ).hexdigest()[:16]
        request = TacticalResourceRequest(request_id, key, demand, tier, reason)
        self._requests.append(request)
        if memory is not None and memory.suspended_for_state:
            return request, None

        spec = self.config.spec(tier)
        if (
            self._expansion_nodes_granted + spec.max_nodes
            > self.config.max_granted_nodes_per_expansion
            or self._expansion_seconds_granted + spec.max_seconds
            > self.config.max_granted_seconds_per_expansion
        ):
            return request, None
        grant = TacticalResourceGrant(
            request_id,
            key,
            tier,
            spec.max_nodes,
            spec.max_seconds,
            spec.max_added_cost,
            spec.fingerprint,
            demand.removal_policy,
            reason,
        )
        self._grants.append(grant)
        self._expansion_nodes_granted += spec.max_nodes
        self._expansion_seconds_granted += spec.max_seconds
        return request, grant

    def record_outcome(self, outcome: TacticalResourceOutcome) -> TacticalResourceOutcome:
        memory = self._memory.get(outcome.key)
        if memory is None:
            memory = _MutableEvidence(outcome.tier)
            self._memory[outcome.key] = memory
        repeated = bool(
            not outcome.has_named_harvest
            and memory.consecutive_zero_harvest_misses > 0
            and memory.latest_blocker == outcome.blocker_after
        )
        if outcome.has_named_harvest:
            memory.consecutive_zero_harvest_misses = 0
            memory.successful_harvests += 1
            if outcome.terminal_qualification_after and not outcome.terminal_qualification_before:
                decision = TacticalResourceDecision.TERMINAL_ESCALATION
            elif outcome.tier < TacticalResourceTier.TERMINAL:
                decision = TacticalResourceDecision.PROMOTE
            else:
                decision = TacticalResourceDecision.CONTINUE_SAME_TIER
        else:
            memory.consecutive_zero_harvest_misses += 1
            if memory.consecutive_zero_harvest_misses >= self.config.repeated_misses_before_suspend:
                memory.suspended_for_state = True
                decision = TacticalResourceDecision.SUSPEND_FOR_STATE
            elif outcome.tier >= TacticalResourceTier.COMMITTED:
                decision = TacticalResourceDecision.DEMOTE
            else:
                decision = TacticalResourceDecision.CONTINUE_SAME_TIER
        memory.latest_tier = outcome.tier
        memory.latest_decision = decision
        memory.latest_blocker = outcome.blocker_after
        recorded = TacticalResourceOutcome(
            **{
                **outcome.__dict__,
                "repeated_equivalent_miss": repeated,
                "decision": decision,
            }
        )
        self._outcomes.append(recorded)
        return recorded

    def evidence_for(
        self, state_key: CanonicalStateKey, demand: TacticalDemand
    ) -> Optional[TacticalResourceEvidence]:
        key = self._key(state_key, demand)
        item = self._memory.get(key)
        if item is None:
            return None
        return TacticalResourceEvidence(
            key,
            item.latest_tier,
            item.consecutive_zero_harvest_misses,
            item.successful_harvests,
            item.suspended_for_state,
            item.latest_decision,
            item.latest_blocker,
        )

    @property
    def ledger(self) -> TacticalResourceLedger:
        return TacticalResourceLedger(
            tuple(self._requests), tuple(self._grants), tuple(self._outcomes)
        )
