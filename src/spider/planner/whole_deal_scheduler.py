"""Proof-neutral whole-deal backward/forward structural scheduling.

The blueprint reads the complete known deal from an exact :class:`SpiderState`.
It records when material exists and which exact stock card will reach which
column.  The dynamic schedule is rebuilt from the current state and emits a
small set of semantic objectives.  It never emits moves, rejects states, or
participates in canonical state identity.
"""

from __future__ import annotations

import hashlib
import time
from collections import Counter
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.epoch_progression import current_stock_epoch, future_stock_rows
from spider.rules import MW_RULES
from spider.state_identity import CanonicalStateKey, canonical_state_key


SUITS: Tuple[str, ...] = ("c", "d", "h", "s")
RANKS_DESCENDING: Tuple[int, ...] = tuple(range(13, 0, -1))


class TemporalAvailabilityKind(str, Enum):
    CURRENT_EXPOSED = "CURRENT_EXPOSED"
    CURRENT_FACEUP_BURIED = "CURRENT_FACEUP_BURIED"
    CURRENT_FACEDOWN_KNOWN = "CURRENT_FACEDOWN_KNOWN"
    FUTURE_STOCK = "FUTURE_STOCK"
    REMOVED_TO_FOUNDATION = "REMOVED_TO_FOUNDATION"


class AdjacencyStatus(str, Enum):
    SATISFIED = "SATISFIED"
    MISSING = "MISSING"
    FUTURE_GATED = "FUTURE_GATED"
    PLANNED_FUTURE_FREE = "PLANNED_FUTURE_FREE"


class StockReceptionKind(str, Enum):
    SAME_SUIT_FREE_JOIN = "SAME_SUIT_FREE_JOIN"
    FOUNDATION_TRIGGER = "FOUNDATION_TRIGGER"
    BRIDGE_RECEPTION = "BRIDGE_RECEPTION"
    USEFUL_ISOLATION = "USEFUL_ISOLATION"
    NEUTRAL_RECEPTION = "NEUTRAL_RECEPTION"
    HARMFUL_RECEPTION = "HARMFUL_RECEPTION"


class ScheduleObjectiveFamily(str, Enum):
    BUILD_FRAGMENT = "BUILD_FRAGMENT"
    EXPOSE_UNLOCK_CARD = "EXPOSE_UNLOCK_CARD"
    PREPARE_STOCK_RECEPTION = "PREPARE_STOCK_RECEPTION"
    CONSUME_BRIDGE_CARD = "CONSUME_BRIDGE_CARD"
    PRESERVE_USEFUL_FRAGMENT = "PRESERVE_USEFUL_FRAGMENT"
    PREPARE_TERMINAL_SEQUENCE = "PREPARE_TERMINAL_SEQUENCE"
    PREPARE_EPOCH_TRANSITION = "PREPARE_EPOCH_TRANSITION"


class ScheduleObjectiveStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIONABLE = "ACTIONABLE"
    ADVANCED = "ADVANCED"
    SATISFIED = "SATISFIED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class ScheduleDeadlineKind(str, Enum):
    BEFORE_NEXT_DEAL = "BEFORE_NEXT_DEAL"
    BY_EPOCH_N = "BY_EPOCH_N"
    ON_SOURCE_ARRIVAL = "ON_SOURCE_ARRIVAL"
    BEFORE_STOCK_EMPTY = "BEFORE_STOCK_EMPTY"
    NO_HARD_DEADLINE = "NO_HARD_DEADLINE"


class ScheduleDeltaKind(str, Enum):
    TARGET_SATISFIED = "TARGET_SATISFIED"
    TARGET_ADVANCED = "TARGET_ADVANCED"
    TARGET_INVALIDATED = "TARGET_INVALIDATED"
    TARGET_REASSIGNED = "TARGET_REASSIGNED"
    DEADLINE_ADVANCED = "DEADLINE_ADVANCED"
    RECEPTION_REALIZED = "RECEPTION_REALIZED"
    RECEPTION_MISSED = "RECEPTION_MISSED"
    BRIDGE_EXPOSED = "BRIDGE_EXPOSED"
    BRIDGE_CONSUMED = "BRIDGE_CONSUMED"
    FOUNDATION_FLOOR_REACHED = "FOUNDATION_FLOOR_REACHED"
    DEAL_NOW_PREFERRED = "DEAL_NOW_PREFERRED"
    NEW_HIGH_LEVERAGE_SOURCE = "NEW_HIGH_LEVERAGE_SOURCE"


class PreDealOpportunityClass(str, Enum):
    """Marginal value of completing an objective before the exact next Deal."""

    MUST_PRE_DEAL = "MUST_PRE_DEAL"
    ADVANTAGE_PRE_DEAL = "ADVANTAGE_PRE_DEAL"
    DEFERRABLE = "DEFERRABLE"
    FUTURE_SUPPLIED = "FUTURE_SUPPLIED"
    NON_ECONOMIC = "NON_ECONOMIC"
    INVALID = "INVALID"


class EpochSaturationStatus(str, Enum):
    PREPARATION_REQUIRED = "PREPARATION_REQUIRED"
    PREPARATION_ADVANTAGE = "PREPARATION_ADVANTAGE"
    DEAL_READY = "DEAL_READY"
    STOCK_EMPTY = "STOCK_EMPTY"


class EpochTransitionRepresentativeStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    RESERVED = "RESERVED"
    EXPANDED = "EXPANDED"
    SPENT = "SPENT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SchedulerDealKind(str, Enum):
    DEAL_NOW = "DEAL_NOW"
    PREPARED_DEAL = "PREPARED_DEAL"
    FALLBACK_DEAL = "FALLBACK_DEAL"


class EpochTransitionHarvestKind(str, Enum):
    REALIZED_FREE_JOIN = "REALIZED_FREE_JOIN"
    REALIZED_FOUNDATION_TRIGGER = "REALIZED_FOUNDATION_TRIGGER"
    REALIZED_BRIDGE_ARRIVAL = "REALIZED_BRIDGE_ARRIVAL"
    HIGH_LEVERAGE_SOURCE_ARRIVED = "HIGH_LEVERAGE_SOURCE_ARRIVED"
    USEFUL_ISOLATION = "USEFUL_ISOLATION"
    NEW_WORKSPACE_EFFECT = "NEW_WORKSPACE_EFFECT"
    NEW_FRAGMENT_OPPORTUNITY = "NEW_FRAGMENT_OPPORTUNITY"
    EXPECTED_NEUTRAL_TRANSITION = "EXPECTED_NEUTRAL_TRANSITION"
    HARMFUL_RECEPTION = "HARMFUL_RECEPTION"
    OTHER_NAMED_EPOCH_HARVEST = "OTHER_NAMED_EPOCH_HARVEST"


@dataclass(frozen=True)
class SchedulerPerformance:
    blueprint_seconds: float = field(default=0.0, compare=False)
    schedule_seconds: float = field(default=0.0, compare=False)
    reception_seconds: float = field(default=0.0, compare=False)
    duplicate_assignment_seconds: float = field(default=0.0, compare=False)
    leverage_seconds: float = field(default=0.0, compare=False)
    deal_now_preview_seconds: float = field(default=0.0, compare=False)
    prepare_then_deal_seconds: float = field(default=0.0, compare=False)
    saturation_seconds: float = field(default=0.0, compare=False)


@dataclass(frozen=True)
class DealCardRef:
    ref_id: str
    card: Card
    temporal_kind: TemporalAvailabilityKind
    availability_epoch: int
    column: Optional[int]
    depth: int
    stock_epoch: Optional[int] = None


@dataclass(frozen=True)
class FutureStockRow:
    epoch: int
    cards: Tuple[DealCardRef, ...]

    @property
    def card_values(self) -> Tuple[Card, ...]:
        return tuple(item.card for item in self.cards)


@dataclass(frozen=True)
class FoundationAvailabilityFloor:
    suit: str
    lane: int
    copy_threshold: int
    earliest_epoch: Optional[int]
    limiting_ranks: Tuple[int, ...]
    counts_by_epoch: Tuple[Tuple[int, Tuple[int, ...]], ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class AdjacencyTarget:
    suit: str
    lane: int
    high_rank: int
    low_rank: int
    epoch: int
    status: AdjacencyStatus

    @property
    def identity(self) -> Tuple[str, int, int]:
        return self.suit, self.high_rank, self.low_rank


@dataclass(frozen=True)
class FragmentTarget:
    suit: str
    lane: int
    high_rank: int
    low_rank: int
    target_epoch: int
    required_ranks: Tuple[int, ...]
    satisfied_edges: Tuple[Tuple[int, int], ...]
    missing_edges: Tuple[Tuple[int, int], ...]
    future_gated_edges: Tuple[Tuple[int, int], ...]
    contributing_fragments: Tuple[Tuple[int, int, int], ...]
    actionable_now: bool
    terminal_at_epoch: bool
    useful_preparation: bool

    @property
    def edge_count(self) -> int:
        return max(0, self.high_rank - self.low_rank)


@dataclass(frozen=True)
class SuitLanePlan:
    suit: str
    lane: int
    copy_threshold: int
    availability_floor: Optional[int]
    assignment_signature: Tuple[Tuple[int, int, int], ...]
    adjacencies: Tuple[AdjacencyTarget, ...]
    fragments: Tuple[FragmentTarget, ...]


@dataclass(frozen=True)
class SuitEpochPlan:
    suit: str
    epoch: int
    remaining_foundations: int
    lanes: Tuple[SuitLanePlan, ...]


@dataclass(frozen=True)
class StockReceptionOpportunity:
    opportunity_id: str
    epoch: int
    column: int
    incoming: Card
    kind: StockReceptionKind
    current_top: Optional[Card]
    desired_receiver: Optional[Card]
    receiver_satisfied: bool
    estimated_preparation_cost: int
    estimated_rehandling_cost: int
    expected_saved_actions: int
    permanent_edges_created: int
    feasible: bool
    worthwhile_preparation: bool
    deadline: ScheduleDeadlineKind = ScheduleDeadlineKind.BEFORE_NEXT_DEAL
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class UnlockCardAssessment:
    source_id: str
    card: Card
    temporal_kind: TemporalAvailabilityKind
    availability_epoch: int
    column: Optional[int]
    blocker_depth: int
    desired_edges_enabled: int
    fragments_joined: int
    completion_potential: bool
    downstream_requirements_unlocked: int
    receiver_or_workspace_value: int
    estimated_structural_work: int
    is_bridge: bool
    excavation_candidate: bool
    ordering_key: Tuple


@dataclass(frozen=True)
class ScheduledStructuralObjective:
    objective_id: str
    family: ScheduleObjectiveFamily
    status: ScheduleObjectiveStatus
    suit: Optional[str]
    high_rank: Optional[int]
    low_rank: Optional[int]
    source_card: Optional[Card]
    source_ref_id: Optional[str]
    target_column: Optional[int]
    target_epoch: Optional[int]
    deadline: ScheduleDeadlineKind
    estimated_paid_cost: int
    estimated_rehandling_cost: int
    permanent_edges: int
    leverage_edges: int
    fragments_joined: int
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    def ordering_key(self) -> Tuple:
        family_order = {
            ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE: 0,
            ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD: 1,
            ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD: 2,
            ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION: 3,
            ScheduleObjectiveFamily.BUILD_FRAGMENT: 4,
            ScheduleObjectiveFamily.PRESERVE_USEFUL_FRAGMENT: 5,
            ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION: 6,
        }
        return (
            family_order[self.family],
            -self.permanent_edges,
            -self.leverage_edges,
            -self.fragments_joined,
            self.estimated_paid_cost,
            self.estimated_rehandling_cost,
            self.target_epoch if self.target_epoch is not None else 99,
            self.suit or "",
            -(self.high_rank or 0),
            -(self.low_rank or 0),
            self.target_column if self.target_column is not None else 99,
            self.objective_id,
        )


@dataclass(frozen=True)
class PreDealOpportunity:
    objective: ScheduledStructuralObjective
    classification: PreDealOpportunityClass
    deadline_distance: Optional[int]
    survives_after_deal: bool
    source_actionable_before: bool
    source_actionable_after: bool
    blocker_work_before: int
    blocker_work_after: int
    estimated_marginal_benefit: int
    estimated_preparation_cost: int
    automatically_supplied: bool
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    def ordering_key(self) -> Tuple:
        class_order = {
            PreDealOpportunityClass.MUST_PRE_DEAL: 0,
            PreDealOpportunityClass.ADVANTAGE_PRE_DEAL: 1,
            PreDealOpportunityClass.DEFERRABLE: 2,
            PreDealOpportunityClass.FUTURE_SUPPLIED: 3,
            PreDealOpportunityClass.NON_ECONOMIC: 4,
            PreDealOpportunityClass.INVALID: 5,
        }
        return (
            class_order[self.classification],
            self.deadline_distance if self.deadline_distance is not None else 99,
            -self.estimated_marginal_benefit,
            self.estimated_preparation_cost,
            self.blocker_work_after - self.blocker_work_before,
            self.objective.ordering_key(),
        )


@dataclass(frozen=True)
class EpochSaturationAssessment:
    status: EpochSaturationStatus
    epoch: int
    opportunities: Tuple[PreDealOpportunity, ...]
    selected_preparation: Optional[PreDealOpportunity]
    must_count: int
    advantage_count: int
    deferrable_count: int
    future_supplied_count: int
    non_economic_count: int
    invalid_count: int
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DealNowCounterfactual:
    source_exact_state_key: CanonicalStateKey
    source_state_fingerprint: str
    source_epoch: int
    incoming_row: Tuple[Card, ...]
    deal_cost: int
    post_deal_state: SpiderState = field(compare=False, repr=False)
    post_deal_state_fingerprint: str = ""
    post_deal_schedule: Optional["WholeDealSchedule"] = field(
        default=None, compare=False, repr=False
    )
    objective_ids_before: Tuple[str, ...] = ()
    objective_ids_after: Tuple[str, ...] = ()
    preview_seconds: float = field(default=0.0, compare=False)
    entered_tt: bool = False
    strategic_expansions: int = 0
    tactical_nodes: int = 0
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class PrepareThenDealComparison:
    objective_id: str
    candidate_actions: Tuple[Tuple, ...]
    preparation_cost: int
    deal_now_state_fingerprint: str
    prepared_deal_state: SpiderState = field(compare=False, repr=False)
    prepared_deal_state_fingerprint: str = ""
    objective_progress_after_deal: ScheduleObjectiveStatus = (
        ScheduleObjectiveStatus.PLANNED
    )
    same_suit_edge_delta: int = 0
    foundation_delta: int = 0
    face_down_delta: int = 0
    harmful_boundary_delta: int = 0
    demonstrably_better: bool = False
    rationale: Tuple[str, ...] = ()
    comparison_seconds: float = field(default=0.0, compare=False)
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class EpochTransitionHarvest:
    kind: EpochTransitionHarvestKind
    detail: str
    column: Optional[int] = None
    card: Optional[Card] = None
    predicted: bool = False
    realized: bool = True
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class EpochTransitionOpportunity:
    opportunity_id: str
    source_exact_state_key: CanonicalStateKey
    source_state_fingerprint: str
    source_epoch: int
    incoming_row: Tuple[Card, ...]
    corrected_g_after_deal: int
    saturation: EpochSaturationAssessment
    deal_kind: SchedulerDealKind
    stable_structure_after: int
    rehandling_debt_after: float
    next_epoch_opportunity_count: int
    harvests: Tuple[EpochTransitionHarvest, ...]
    status: EpochTransitionRepresentativeStatus = (
        EpochTransitionRepresentativeStatus.QUALIFIED
    )
    exact_tt_admitted: bool = True
    independently_replay_verified: bool = True
    proof_pruning_allowed: bool = False

    def ordering_key(self) -> Tuple:
        return (
            self.corrected_g_after_deal,
            self.saturation.must_count,
            self.saturation.advantage_count,
            self.rehandling_debt_after,
            -self.stable_structure_after,
            -self.next_epoch_opportunity_count,
            self.source_epoch,
            self.source_state_fingerprint,
            self.opportunity_id,
        )

    def eligible(self, spent_ids: Iterable[str] = ()) -> bool:
        return bool(
            self.status
            in {
                EpochTransitionRepresentativeStatus.QUALIFIED,
                EpochTransitionRepresentativeStatus.RESERVED,
            }
            and self.opportunity_id not in set(spent_ids)
            and self.exact_tt_admitted
            and self.independently_replay_verified
        )


@dataclass(frozen=True)
class EpochTransitionTrace:
    opportunity_id: str
    source_state_fingerprint: str
    corrected_g_before: int
    corrected_g_after: int
    epoch_before: int
    epoch_after: int
    saturation_status: EpochSaturationStatus
    must_objective_ids: Tuple[str, ...]
    advantage_objective_ids: Tuple[str, ...]
    deferrable_objective_ids: Tuple[str, ...]
    future_supplied_objective_ids: Tuple[str, ...]
    selected_preparation_id: Optional[str]
    deal_kind: SchedulerDealKind
    incoming_row: Tuple[Card, ...]
    admitted: bool
    reserved: bool
    expanded: bool
    harvests: Tuple[EpochTransitionHarvest, ...]
    next_objective_ids: Tuple[str, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class WholeDealBlueprint:
    blueprint_id: str
    origin_epoch: int
    temporal_cards: Tuple[DealCardRef, ...]
    future_rows: Tuple[FutureStockRow, ...]
    rank_counts_by_epoch: Tuple[Tuple[int, str, Tuple[int, ...]], ...]
    foundation_floors: Tuple[FoundationAvailabilityFloor, ...]
    fragments_by_epoch: Tuple[FragmentTarget, ...]
    proof_pruning_allowed: bool = False
    performance: SchedulerPerformance = field(default_factory=SchedulerPerformance)

    def counts(self, suit: str, epoch: int) -> Tuple[int, ...]:
        eligible = [
            counts
            for item_epoch, item_suit, counts in self.rank_counts_by_epoch
            if item_suit == suit and item_epoch <= epoch
        ]
        return eligible[-1] if eligible else (0,) * 13


@dataclass(frozen=True)
class WholeDealSchedule:
    blueprint_id: str
    exact_state_fingerprint: str
    epoch: int
    suit_plans: Tuple[SuitEpochPlan, ...]
    receptions: Tuple[StockReceptionOpportunity, ...]
    leverage_cards: Tuple[UnlockCardAssessment, ...]
    objectives: Tuple[ScheduledStructuralObjective, ...]
    deal_now_preferred: bool
    pre_deal_opportunities: Tuple[PreDealOpportunity, ...] = ()
    saturation: Optional[EpochSaturationAssessment] = None
    deal_now_counterfactual: Optional[DealNowCounterfactual] = field(
        default=None, compare=False, repr=False
    )
    generation: int = 0
    proof_pruning_allowed: bool = False
    performance: SchedulerPerformance = field(default_factory=SchedulerPerformance)


WholeDealScheduleSnapshot = WholeDealSchedule


@dataclass(frozen=True)
class ScheduleDelta:
    kind: ScheduleDeltaKind
    objective_id: Optional[str]
    detail: str
    epoch_before: int
    epoch_after: int
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class WholeDealSchedulerConfig:
    max_objectives: int = 4
    maximum_reception_prep_cost: int = 3
    minimum_bridge_edges: int = 2

    def __post_init__(self) -> None:
        if self.max_objectives <= 0:
            raise ValueError("max_objectives must be positive")
        if self.maximum_reception_prep_cost < 0:
            raise ValueError("maximum reception cost cannot be negative")


def _state_fingerprint(state: SpiderState) -> str:
    structural = (
        tuple(
            (
                tuple((card.suit, card.rank) for card in column.face_down),
                tuple((card.suit, card.rank) for card in column.face_up),
            )
            for column in state.columns
        ),
        tuple((card.suit, card.rank) for card in state.stock),
        tuple(tuple((card.suit, card.rank) for card in run) for run in state.foundations),
    )
    return hashlib.sha256(repr(structural).encode("utf-8")).hexdigest()[:16]


def _removed_by_suit(state: SpiderState) -> Counter:
    result: Counter = Counter()
    for foundation in state.foundations:
        if foundation and len(foundation) == 13:
            result[foundation[0].suit] += 1
    return result


def enumerate_temporal_cards(state: SpiderState) -> Tuple[DealCardRef, ...]:
    epoch = current_stock_epoch(state)
    result = []
    for column_index, column in enumerate(state.columns):
        for index, card in enumerate(column.face_down):
            depth = len(column.face_down) - index - 1 + len(column.face_up)
            result.append(
                DealCardRef(
                    f"fd:{column_index}:{index}:{card.suit}{card.rank}",
                    card,
                    TemporalAvailabilityKind.CURRENT_FACEDOWN_KNOWN,
                    epoch,
                    column_index,
                    depth,
                )
            )
        for index, card in enumerate(column.face_up):
            depth = len(column.face_up) - index - 1
            kind = (
                TemporalAvailabilityKind.CURRENT_EXPOSED
                if depth == 0
                else TemporalAvailabilityKind.CURRENT_FACEUP_BURIED
            )
            result.append(
                DealCardRef(
                    f"fu:{column_index}:{index}:{card.suit}{card.rank}",
                    card,
                    kind,
                    epoch,
                    column_index,
                    depth,
                )
            )
    for offset, row in enumerate(future_stock_rows(state), 1):
        arrival = epoch + offset
        for column_index, card in enumerate(row):
            result.append(
                DealCardRef(
                    f"stock:{arrival}:{column_index}:{card.suit}{card.rank}",
                    card,
                    TemporalAvailabilityKind.FUTURE_STOCK,
                    arrival,
                    column_index,
                    0,
                    arrival,
                )
            )
    for foundation_index, foundation in enumerate(state.foundations):
        for index, card in enumerate(foundation):
            result.append(
                DealCardRef(
                    f"foundation:{foundation_index}:{index}:{card.suit}{card.rank}",
                    card,
                    TemporalAvailabilityKind.REMOVED_TO_FOUNDATION,
                    epoch,
                    None,
                    0,
                )
            )
    return tuple(result)


def enumerate_future_rows(state: SpiderState) -> Tuple[FutureStockRow, ...]:
    epoch = current_stock_epoch(state)
    rows = []
    for offset, row in enumerate(future_stock_rows(state), 1):
        arrival = epoch + offset
        rows.append(
            FutureStockRow(
                arrival,
                tuple(
                    DealCardRef(
                        f"stock:{arrival}:{column}:{card.suit}{card.rank}",
                        card,
                        TemporalAvailabilityKind.FUTURE_STOCK,
                        arrival,
                        column,
                        0,
                        arrival,
                    )
                    for column, card in enumerate(row)
                ),
            )
        )
    return tuple(rows)


def _counts_by_epoch(
    temporal_cards: Sequence[DealCardRef], origin_epoch: int
) -> Tuple[Tuple[int, str, Tuple[int, ...]], ...]:
    last_epoch = max((item.availability_epoch for item in temporal_cards), default=origin_epoch)
    result = []
    for epoch in range(origin_epoch, last_epoch + 1):
        for suit in SUITS:
            counts = [0] * 13
            for item in temporal_cards:
                if item.card.suit == suit and item.availability_epoch <= epoch:
                    counts[item.card.rank - 1] += 1
            result.append((epoch, suit, tuple(counts)))
    return tuple(result)


def _availability_floors(
    state: SpiderState,
    counts: Sequence[Tuple[int, str, Tuple[int, ...]]],
) -> Tuple[FoundationAvailabilityFloor, ...]:
    origin = current_stock_epoch(state)
    removed = _removed_by_suit(state)
    epochs = sorted({epoch for epoch, _suit, _counts in counts})
    floors = []
    for suit in SUITS:
        for lane in range(1, max(0, 2 - removed[suit]) + 1):
            threshold = removed[suit] + lane
            earliest = None
            limiting: Tuple[int, ...] = tuple(RANKS_DESCENDING)
            per_epoch = tuple(
                (epoch, next(row for e, s, row in counts if e == epoch and s == suit))
                for epoch in epochs
            )
            for index, (epoch, rank_counts) in enumerate(per_epoch):
                if min(rank_counts, default=0) >= threshold:
                    earliest = epoch
                    if index == 0:
                        limiting = ()
                    else:
                        previous = per_epoch[index - 1][1]
                        limiting = tuple(
                            rank for rank in RANKS_DESCENDING
                            if previous[rank - 1] < threshold
                        )
                    break
            floors.append(
                FoundationAvailabilityFloor(
                    suit,
                    lane,
                    threshold,
                    earliest,
                    limiting,
                    per_epoch,
                )
            )
    return tuple(floors)


def _maximal_available_intervals(
    suit: str,
    lane: int,
    threshold: int,
    epoch: int,
    counts: Sequence[int],
) -> Tuple[FragmentTarget, ...]:
    intervals = []
    current = []
    for rank in RANKS_DESCENDING:
        if counts[rank - 1] >= threshold:
            current.append(rank)
        elif current:
            intervals.append(tuple(current))
            current = []
    if current:
        intervals.append(tuple(current))
    return tuple(
        FragmentTarget(
            suit=suit,
            lane=lane,
            high_rank=ranks[0],
            low_rank=ranks[-1],
            target_epoch=epoch,
            required_ranks=ranks,
            satisfied_edges=(),
            missing_edges=tuple(zip(ranks, ranks[1:])),
            future_gated_edges=(),
            contributing_fragments=(),
            actionable_now=True,
            terminal_at_epoch=len(ranks) == 13,
            useful_preparation=len(ranks) >= 2,
        )
        for ranks in intervals
        if len(ranks) >= 1
    )


def build_whole_deal_blueprint(state: SpiderState) -> WholeDealBlueprint:
    """Build deterministic whole-deal supply and backward-fragment facts."""
    started = time.perf_counter()
    temporal = enumerate_temporal_cards(state)
    rows = enumerate_future_rows(state)
    origin = current_stock_epoch(state)
    counts = _counts_by_epoch(temporal, origin)
    floors = _availability_floors(state, counts)
    fragments = []
    for floor in floors:
        for epoch, rank_counts in floor.counts_by_epoch:
            fragments.extend(
                _maximal_available_intervals(
                    floor.suit,
                    floor.lane,
                    floor.copy_threshold,
                    epoch,
                    rank_counts,
                )
            )
    identity = (
        origin,
        tuple(
            (
                row.epoch,
                tuple((item.column, item.card.suit, item.card.rank) for item in row.cards),
            )
            for row in rows
        ),
        tuple((item.ref_id, item.availability_epoch) for item in temporal),
    )
    return WholeDealBlueprint(
        hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:16],
        origin,
        temporal,
        rows,
        counts,
        floors,
        tuple(fragments),
        performance=SchedulerPerformance(
            blueprint_seconds=time.perf_counter() - started
        ),
    )


def _stable_fragments(state: SpiderState, suit: str) -> Tuple[Tuple[int, int, int], ...]:
    fragments = []
    for column_index, column in enumerate(state.columns):
        up = column.face_up
        index = 0
        while index < len(up):
            if up[index].suit != suit:
                index += 1
                continue
            end = index
            while (
                end + 1 < len(up)
                and up[end + 1].suit == suit
                and up[end].rank - 1 == up[end + 1].rank
            ):
                end += 1
            fragments.append((up[index].rank, up[end].rank, column_index))
            index = end + 1
    return tuple(
        sorted(fragments, key=lambda item: (-(item[0] - item[1] + 1), -item[0], item[2]))
    )


def _stable_edges(state: SpiderState, suit: str) -> set[Tuple[int, int]]:
    edges: set[Tuple[int, int]] = set()
    for column in state.columns:
        for high, low in zip(column.face_up, column.face_up[1:]):
            if high.suit == suit == low.suit and high.rank - 1 == low.rank:
                edges.add((high.rank, low.rank))
    return edges


def _assignment_signatures(
    state: SpiderState, suit: str, lane_count: int
) -> Tuple[Tuple[Tuple[int, int, int], ...], ...]:
    """Canonicalise symmetric lanes using current stable fragments."""
    fragments = _stable_fragments(state, suit)
    buckets = [[] for _ in range(lane_count)]
    for index, fragment in enumerate(fragments):
        if buckets:
            buckets[index % lane_count].append(fragment)
    signatures = [tuple(sorted(bucket)) for bucket in buckets]
    return tuple(sorted(signatures))


def _card_refs_for_state(state: SpiderState) -> Tuple[DealCardRef, ...]:
    return tuple(
        item
        for item in enumerate_temporal_cards(state)
        if item.temporal_kind != TemporalAvailabilityKind.REMOVED_TO_FOUNDATION
    )


def _leverage_assessments(
    state: SpiderState,
    blueprint: WholeDealBlueprint,
) -> Tuple[UnlockCardAssessment, ...]:
    exposed_by_suit_rank = Counter()
    for column in state.columns:
        for card in column.face_up:
            exposed_by_suit_rank[(card.suit, card.rank)] += 1
    assessments = []
    for item in _card_refs_for_state(state):
        card = item.card
        upper_present = card.rank < 13 and exposed_by_suit_rank[(card.suit, card.rank + 1)] > 0
        lower_present = card.rank > 1 and exposed_by_suit_rank[(card.suit, card.rank - 1)] > 0
        edges = int(upper_present) + int(lower_present)
        fragments_joined = int(upper_present and lower_present)
        completion = edges == 2 and card.rank not in (1, 13)
        future_receiver = int(
            item.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK and upper_present
        )
        downstream = edges + fragments_joined + int(completion)
        work = item.depth if item.temporal_kind != TemporalAvailabilityKind.FUTURE_STOCK else 0
        excavation = item.temporal_kind in {
            TemporalAvailabilityKind.CURRENT_FACEUP_BURIED,
            TemporalAvailabilityKind.CURRENT_FACEDOWN_KNOWN,
        }
        ordering = (
            -int(completion),
            -fragments_joined,
            -edges,
            -downstream,
            -future_receiver,
            work,
            item.availability_epoch,
            card.suit,
            -card.rank,
            item.column if item.column is not None else 99,
            item.ref_id,
        )
        assessments.append(
            UnlockCardAssessment(
                item.ref_id,
                card,
                item.temporal_kind,
                item.availability_epoch,
                item.column,
                item.depth,
                edges,
                fragments_joined,
                completion,
                downstream,
                future_receiver,
                work,
                bool(fragments_joined),
                excavation,
                ordering,
            )
        )
    return tuple(sorted(assessments, key=lambda item: item.ordering_key))


def _would_trigger_foundation(state: SpiderState, column: int, incoming: Card) -> bool:
    values = list(state.columns[column].face_up) + [incoming]
    if len(values) < 13:
        return False
    tail = values[-13:]
    return bool(
        tail[0].rank == 13
        and all(card.suit == incoming.suit for card in tail)
        and all(high.rank - 1 == low.rank for high, low in zip(tail, tail[1:]))
    )


def _receiver_rehandling_cost(state: SpiderState, column: int, receiver: Card) -> int:
    for source, pile in enumerate(state.columns):
        if source == column or pile.top() != receiver:
            continue
        if len(pile.face_up) >= 2:
            below = pile.face_up[-2]
            if below.suit == receiver.suit and below.rank - 1 == receiver.rank:
                return 1
        return 0
    return 0


def analyze_next_deal_reception(
    state: SpiderState,
    leverage_cards: Sequence[UnlockCardAssessment] = (),
    *,
    maximum_preparation_cost: int = 3,
) -> Tuple[StockReceptionOpportunity, ...]:
    rows = future_stock_rows(state)
    if not rows:
        return ()
    epoch = current_stock_epoch(state) + 1
    leverage = {}
    for item in leverage_cards:
        # ``leverage_cards`` is already in strongest-first deterministic order.
        leverage.setdefault((item.card.suit, item.card.rank), item)
    result = []
    for column, incoming in enumerate(rows[0]):
        top = state.columns[column].top()
        desired = Card(incoming.suit, incoming.rank + 1) if incoming.rank < 13 else None
        satisfied = desired is not None and top == desired
        item_leverage = leverage.get((incoming.suit, incoming.rank))
        permanent_edges = int(satisfied)
        if satisfied and _would_trigger_foundation(state, column, incoming):
            kind = StockReceptionKind.FOUNDATION_TRIGGER
        elif satisfied:
            kind = StockReceptionKind.SAME_SUIT_FREE_JOIN
        elif state.columns[column].is_empty():
            kind = (
                StockReceptionKind.USEFUL_ISOLATION
                if item_leverage is not None and item_leverage.desired_edges_enabled > 0
                else StockReceptionKind.NEUTRAL_RECEPTION
            )
        elif item_leverage is not None and item_leverage.is_bridge:
            kind = StockReceptionKind.BRIDGE_RECEPTION
        elif top is not None and any(
            high.suit == top.suit == low.suit and high.rank - 1 == low.rank
            for high, low in zip(state.columns[column].face_up, state.columns[column].face_up[1:])
        ):
            kind = StockReceptionKind.HARMFUL_RECEPTION
        else:
            kind = StockReceptionKind.NEUTRAL_RECEPTION

        if satisfied:
            prep_cost = 0
        elif desired is None:
            prep_cost = maximum_preparation_cost + 1
        else:
            receiver_sources = [
                source
                for source, pile in enumerate(state.columns)
                if source != column and pile.top() == desired
            ]
            if state.columns[column].is_empty() and receiver_sources:
                prep_cost = 1
            elif receiver_sources:
                prep_cost = 2
            else:
                prep_cost = maximum_preparation_cost + 1
        debt = _receiver_rehandling_cost(state, column, desired) if desired else 0
        saved = permanent_edges + (
            item_leverage.desired_edges_enabled if item_leverage is not None else 0
        )
        feasible = prep_cost <= maximum_preparation_cost
        worthwhile = bool(
            desired is not None
            and feasible
            and (satisfied or prep_cost + debt <= max(1, saved))
        )
        opportunity_id = hashlib.sha256(
            repr((epoch, column, incoming.suit, incoming.rank, desired)).encode("utf-8")
        ).hexdigest()[:16]
        result.append(
            StockReceptionOpportunity(
                opportunity_id,
                epoch,
                column,
                incoming,
                kind,
                top,
                desired,
                satisfied,
                prep_cost,
                debt,
                saved,
                permanent_edges,
                feasible,
                worthwhile,
            )
        )
    return tuple(result)


def _dynamic_fragment(
    state: SpiderState,
    fragment: FragmentTarget,
    gated_edges: Iterable[Tuple[int, int]],
) -> FragmentTarget:
    stable = _stable_edges(state, fragment.suit)
    desired = tuple(zip(fragment.required_ranks, fragment.required_ranks[1:]))
    gated = set(gated_edges)
    satisfied = tuple(edge for edge in desired if edge in stable)
    future = tuple(edge for edge in desired if edge in gated and edge not in stable)
    missing = tuple(edge for edge in desired if edge not in stable and edge not in gated)
    contributors = tuple(
        item
        for item in _stable_fragments(state, fragment.suit)
        if not (item[1] > fragment.high_rank or item[0] < fragment.low_rank)
    )
    return FragmentTarget(
        fragment.suit,
        fragment.lane,
        fragment.high_rank,
        fragment.low_rank,
        fragment.target_epoch,
        fragment.required_ranks,
        satisfied,
        missing,
        future,
        contributors,
        bool(missing),
        fragment.terminal_at_epoch,
        fragment.useful_preparation,
    )


def _objective_id(parts: Tuple) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]


def _build_objectives(
    state: SpiderState,
    epoch: int,
    suit_plans: Sequence[SuitEpochPlan],
    receptions: Sequence[StockReceptionOpportunity],
    leverage: Sequence[UnlockCardAssessment],
) -> Tuple[ScheduledStructuralObjective, ...]:
    candidates = []
    for source in leverage:
        if source.desired_edges_enabled <= 0:
            continue
        if source.excavation_candidate:
            family = ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD
            status = ScheduleObjectiveStatus.ACTIONABLE
            rationale = (
                "known current tableau source enables target adjacency",
                f"blocker_depth={source.blocker_depth}",
                "existing dependency machinery chooses the legal excavation route",
            )
        elif source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK:
            surrounding = [
                fragment
                for plan in suit_plans if plan.suit == source.card.suit
                for lane in plan.lanes for fragment in lane.fragments
                if (
                    fragment.low_rank == source.card.rank + 1
                    or fragment.high_rank == source.card.rank - 1
                )
            ]
            surrounding.sort(
                key=lambda item: (
                    -item.edge_count,
                    -len(item.satisfied_edges),
                    item.lane,
                    -item.high_rank,
                )
            )
            target_fragment = surrounding[0] if surrounding else None
            family = (
                ScheduleObjectiveFamily.BUILD_FRAGMENT
                if target_fragment is not None and target_fragment.missing_edges
                else ScheduleObjectiveFamily.PRESERVE_USEFUL_FRAGMENT
            )
            status = (
                ScheduleObjectiveStatus.ACTIONABLE
                if family == ScheduleObjectiveFamily.BUILD_FRAGMENT
                else ScheduleObjectiveStatus.PLANNED
            )
            rationale = (
                "future key card cannot be excavated before its stock epoch",
                "prepare or preserve a useful adjacent fragment before arrival",
            )
        elif source.is_bridge:
            family = ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD
            status = ScheduleObjectiveStatus.ACTIONABLE
            rationale = ("card can join two current/target fragments",)
        else:
            continue
        candidates.append(
            ScheduledStructuralObjective(
                _objective_id((family.value, source.source_id, source.availability_epoch)),
                family,
                status,
                source.card.suit,
                (
                    target_fragment.high_rank
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    and target_fragment is not None
                    else min(13, source.card.rank + 1)
                ),
                (
                    target_fragment.low_rank
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    and target_fragment is not None
                    else max(1, source.card.rank - 1)
                ),
                source.card,
                source.source_id,
                (
                    source.column
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    and source.availability_epoch == epoch + 1
                    else None
                ),
                source.availability_epoch,
                (
                    ScheduleDeadlineKind.ON_SOURCE_ARRIVAL
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    else ScheduleDeadlineKind.BEFORE_NEXT_DEAL
                    if any(
                        item.column == source.column
                        and item.kind == StockReceptionKind.HARMFUL_RECEPTION
                        for item in receptions
                    )
                    else ScheduleDeadlineKind.BY_EPOCH_N
                ),
                (
                    max(1, len(target_fragment.missing_edges))
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    and target_fragment is not None
                    else source.estimated_structural_work
                ),
                0,
                (
                    target_fragment.edge_count
                    if source.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
                    and target_fragment is not None
                    else source.desired_edges_enabled
                ),
                source.desired_edges_enabled,
                source.fragments_joined,
                rationale,
            )
        )

    for reception in receptions:
        if not reception.worthwhile_preparation:
            continue
        candidates.append(
            ScheduledStructuralObjective(
                _objective_id((ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION.value, reception.opportunity_id)),
                ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION,
                (
                    ScheduleObjectiveStatus.SATISFIED
                    if reception.receiver_satisfied
                    else ScheduleObjectiveStatus.ACTIONABLE
                ),
                reception.incoming.suit,
                reception.desired_receiver.rank if reception.desired_receiver else None,
                reception.incoming.rank,
                reception.incoming,
                None,
                reception.column,
                reception.epoch,
                ScheduleDeadlineKind.BEFORE_NEXT_DEAL,
                reception.estimated_preparation_cost,
                reception.estimated_rehandling_cost,
                max(1, reception.permanent_edges_created),
                reception.expected_saved_actions,
                int(reception.kind == StockReceptionKind.BRIDGE_RECEPTION),
                (
                    "prepare the fixed next-Deal destination for a useful reception",
                    "preparation competes directly with Deal Now on lifecycle economics",
                ),
            )
        )

    # Every still-incomplete suit receives at least one future-directed
    # construction candidate, including suits whose floor is a later epoch.
    for suit_plan in suit_plans:
        lane_fragments = [
            fragment
            for lane in suit_plan.lanes
            for fragment in lane.fragments
            if fragment.useful_preparation and fragment.missing_edges
        ]
        if not lane_fragments:
            continue
        fragment = sorted(
            lane_fragments,
            key=lambda item: (
                -len(item.satisfied_edges),
                -item.edge_count,
                item.target_epoch,
                item.lane,
                -item.high_rank,
            ),
        )[0]
        floor = next(
            (lane.availability_floor for lane in suit_plan.lanes if lane.lane == fragment.lane),
            None,
        )
        candidates.append(
            ScheduledStructuralObjective(
                _objective_id((ScheduleObjectiveFamily.BUILD_FRAGMENT.value, fragment.suit, fragment.lane, fragment.high_rank, fragment.low_rank, fragment.target_epoch)),
                (
                    ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE
                    if fragment.terminal_at_epoch
                    else ScheduleObjectiveFamily.BUILD_FRAGMENT
                ),
                ScheduleObjectiveStatus.ACTIONABLE,
                fragment.suit,
                fragment.high_rank,
                fragment.low_rank,
                None,
                None,
                None,
                floor if floor is not None else fragment.target_epoch,
                (
                    ScheduleDeadlineKind.BY_EPOCH_N
                    if floor is not None and floor > epoch
                    else ScheduleDeadlineKind.BEFORE_STOCK_EMPTY
                ),
                max(1, len(fragment.missing_edges)),
                0,
                fragment.edge_count,
                0,
                max(0, len(fragment.contributing_fragments) - 1),
                (
                    "same-suit fragment is useful preparation for a remaining lane",
                    f"temporal_foundation_floor={floor}",
                    "late completion does not suppress cheap permanent construction",
                ),
            )
        )

    if state.can_deal() and state.stock:
        candidates.append(
            ScheduledStructuralObjective(
                _objective_id((ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION.value, epoch, tuple((c.suit, c.rank) for c in future_stock_rows(state)[0]))),
                ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION,
                ScheduleObjectiveStatus.ACTIONABLE,
                None,
                None,
                None,
                None,
                None,
                None,
                epoch + 1,
                ScheduleDeadlineKind.NO_HARD_DEADLINE,
                1,
                0,
                0,
                0,
                0,
                (
                    "Deal Now remains a first-class epoch transition",
                    "no scheduler target can make a legal unrestricted Deal unavailable",
                ),
            )
        )
    unique = {candidate.objective_id: candidate for candidate in candidates}
    return tuple(sorted(unique.values(), key=lambda item: item.ordering_key()))


def _deadline_distance(
    objective: ScheduledStructuralObjective,
    *,
    epoch: int,
    remaining_deals: int,
) -> Optional[int]:
    if objective.deadline == ScheduleDeadlineKind.BEFORE_NEXT_DEAL:
        return 0
    if objective.deadline in {
        ScheduleDeadlineKind.BY_EPOCH_N,
        ScheduleDeadlineKind.ON_SOURCE_ARRIVAL,
    }:
        return max(0, (objective.target_epoch or epoch) - epoch)
    if objective.deadline == ScheduleDeadlineKind.BEFORE_STOCK_EMPTY:
        return remaining_deals
    return None


def _objective_edges(
    objective: ScheduledStructuralObjective,
) -> set[Tuple[int, int]]:
    if (
        objective.high_rank is None
        or objective.low_rank is None
        or objective.high_rank <= objective.low_rank
    ):
        return set()
    return {
        (rank, rank - 1)
        for rank in range(objective.high_rank, objective.low_rank, -1)
    }


def _source_facts(
    state: SpiderState,
    objective: ScheduledStructuralObjective,
) -> Tuple[bool, bool, int]:
    refs = enumerate_temporal_cards(state)
    exact = next(
        (
            item
            for item in refs
            if objective.source_ref_id is not None
            and item.ref_id == objective.source_ref_id
        ),
        None,
    )
    if exact is None and objective.source_card is not None:
        exact = min(
            (
                item
                for item in refs
                if item.card == objective.source_card
                and item.temporal_kind
                != TemporalAvailabilityKind.REMOVED_TO_FOUNDATION
            ),
            key=lambda item: (
                item.availability_epoch,
                item.depth,
                item.column if item.column is not None else 99,
            ),
            default=None,
        )
    if exact is None:
        return False, False, 99
    actionable = exact.temporal_kind == TemporalAvailabilityKind.CURRENT_EXPOSED
    return True, actionable, exact.depth


def _matching_reception(
    schedule: Optional[WholeDealSchedule],
    objective: ScheduledStructuralObjective,
) -> Optional[StockReceptionOpportunity]:
    if schedule is None:
        return None
    return next(
        (
            item
            for item in schedule.receptions
            if item.column == objective.target_column
            and item.incoming == objective.source_card
        ),
        None,
    )


def _objective_is_valid(
    state: SpiderState,
    objective: ScheduledStructuralObjective,
    schedule: Optional[WholeDealSchedule],
) -> bool:
    if objective.status in {
        ScheduleObjectiveStatus.INVALIDATED,
        ScheduleObjectiveStatus.EXPIRED,
    }:
        return False
    if objective.family == ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION:
        return bool(state.stock and state.can_deal(MW_RULES))
    if objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION:
        rows = future_stock_rows(state)
        return bool(
            rows
            and objective.target_column is not None
            and 0 <= objective.target_column < len(rows[0])
            and rows[0][objective.target_column] == objective.source_card
            and _matching_reception(schedule, objective) is not None
        )
    if objective.source_ref_id is not None:
        return any(
            item.ref_id == objective.source_ref_id
            for item in enumerate_temporal_cards(state)
        )
    return bool(objective.suit is not None or objective.source_card is not None)


def classify_pre_deal_objective(
    state: SpiderState,
    objective: ScheduledStructuralObjective,
    deal_now: Optional[DealNowCounterfactual],
    *,
    current_schedule: Optional[WholeDealSchedule] = None,
) -> PreDealOpportunity:
    """Classify marginal pre-Deal value from exact current/post-Deal facts.

    The result is planning evidence only.  In particular, merely adding one
    stock card above a current top is not treated as material loss.
    """

    epoch = current_stock_epoch(state)
    remaining_deals = len(state.stock) // 10
    distance = _deadline_distance(
        objective, epoch=epoch, remaining_deals=remaining_deals
    )
    valid = _objective_is_valid(state, objective, current_schedule)
    before_exists, before_actionable, before_depth = _source_facts(state, objective)
    after_state = deal_now.post_deal_state if deal_now is not None else state
    after_exists, after_actionable, after_depth = _source_facts(after_state, objective)
    target_edges = _objective_edges(objective)
    before_edges = _stable_edges(state, objective.suit) if objective.suit else set()
    after_edges = (
        _stable_edges(after_state, objective.suit) if objective.suit else set()
    )
    missing_before = target_edges - before_edges
    missing_after = target_edges - after_edges
    reception_realized = False
    if (
        deal_now is not None
        and objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
        and objective.target_column is not None
        and objective.source_card is not None
    ):
        column = after_state.columns[objective.target_column]
        desired = (
            Card(objective.source_card.suit, objective.source_card.rank + 1)
            if objective.source_card.rank < 13
            else None
        )
        reception_realized = bool(
            desired is not None
            and len(column.face_up) >= 2
            and column.face_up[-1] == objective.source_card
            and column.face_up[-2] == desired
        )
    automatically_supplied = bool(
        deal_now is not None
        and (
            reception_realized
            or (
                objective.family
                != ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
                and (
                    (
                        bool(missing_before)
                        and len(missing_after) < len(missing_before)
                    )
                    or objective_progress(state, after_state, objective)
                    == ScheduleObjectiveStatus.SATISFIED
                )
            )
        )
    )
    survives = bool(
        deal_now is not None
        and objective.family != ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
        and (
            bool(missing_after)
            or (
                objective.source_card is not None
                and after_exists
                and objective_progress(state, after_state, objective)
                != ScheduleObjectiveStatus.SATISFIED
            )
        )
    )
    benefit = max(
        objective.permanent_edges,
        objective.leverage_edges + objective.fragments_joined,
    )
    cost = objective.estimated_paid_cost + objective.estimated_rehandling_cost
    rationale = []

    if not valid:
        classification = PreDealOpportunityClass.INVALID
        rationale.append("fresh exact state no longer supports the objective")
    elif automatically_supplied:
        classification = PreDealOpportunityClass.FUTURE_SUPPLIED
        rationale.append("the exact next Deal supplies or completes the target")
    elif objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION:
        reception = _matching_reception(current_schedule, objective)
        if reception is None or not reception.feasible:
            classification = PreDealOpportunityClass.INVALID
            rationale.append("the fixed-column receiver is no longer feasible")
        elif reception.receiver_satisfied:
            classification = PreDealOpportunityClass.FUTURE_SUPPLIED
            automatically_supplied = True
            rationale.append("the receiver is already prepared; Deal realizes the join")
        elif not reception.worthwhile_preparation or cost > benefit:
            classification = PreDealOpportunityClass.NON_ECONOMIC
            rationale.append("receiver preparation costs more than its typed structural return")
        elif reception.estimated_preparation_cost <= 1 and cost < benefit:
            classification = PreDealOpportunityClass.MUST_PRE_DEAL
            rationale.append("the fixed next-row reception is lost if Deal occurs first")
        else:
            classification = PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
            rationale.append("cheap receiver preparation improves the exact post-Deal structure")
    elif objective.family == ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE:
        if distance is not None and distance <= 1 and cost <= max(1, benefit):
            classification = PreDealOpportunityClass.MUST_PRE_DEAL
            rationale.append("near-terminal work should be cashed out before stock coverage")
        elif distance is not None and distance > 1:
            classification = PreDealOpportunityClass.DEFERRABLE
            rationale.append("terminal material has a later typed epoch deadline")
        elif cost <= max(1, benefit) and after_depth > before_depth:
            classification = PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
            rationale.append("bounded terminal preparation is cheaper before the next row")
        else:
            classification = PreDealOpportunityClass.DEFERRABLE
            rationale.append("no current terminal loss relative to Deal Now is demonstrated")
    elif objective.family in {
        ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD,
        ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD,
    }:
        materially_harder = bool(
            before_exists
            and after_exists
            and after_depth > before_depth
            and objective.deadline == ScheduleDeadlineKind.BEFORE_NEXT_DEAL
            and (objective.fragments_joined > 0 or objective.leverage_edges >= 2)
        )
        lost = bool(before_exists and not after_exists)
        if (lost or materially_harder) and cost < max(1, benefit):
            classification = PreDealOpportunityClass.MUST_PRE_DEAL
            rationale.append("a high-leverage current source becomes materially harder after Deal")
        elif (lost or materially_harder) and cost <= max(1, benefit):
            classification = PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
            rationale.append("the source remains possible but is cheaper to exploit now")
        elif survives or after_exists:
            classification = PreDealOpportunityClass.DEFERRABLE
            rationale.append("the source remains comparably available after Deal")
        else:
            classification = PreDealOpportunityClass.NON_ECONOMIC
            rationale.append("no credible pre-Deal leverage return exceeds current work")
    elif distance is not None and distance > 1:
        classification = PreDealOpportunityClass.DEFERRABLE
        rationale.append("the objective remains useful but its typed deadline is not this Deal")
    elif survives:
        classification = PreDealOpportunityClass.DEFERRABLE
        rationale.append("equivalent structural work remains available after Deal")
    elif distance == 0 and benefit > cost:
        classification = PreDealOpportunityClass.MUST_PRE_DEAL
        rationale.append("a positive deadline-bound opportunity is absent after Deal")
    elif distance is not None and distance <= 1 and benefit >= cost and benefit > 0:
        classification = PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
        rationale.append("near-deadline construction produces a better exact next epoch")
    elif benefit <= 0 or cost > max(1, benefit * 2):
        classification = PreDealOpportunityClass.NON_ECONOMIC
        rationale.append("credible structural benefit does not cover preparation and rehandling")
    else:
        classification = PreDealOpportunityClass.DEFERRABLE
        rationale.append("useful construction alone does not justify delaying this Deal")

    if after_depth == before_depth + 1 and classification == PreDealOpportunityClass.DEFERRABLE:
        rationale.append("ordinary stock coverage alone is not material opportunity loss")
    return PreDealOpportunity(
        objective,
        classification,
        distance,
        survives,
        before_actionable,
        after_actionable,
        before_depth,
        after_depth,
        benefit,
        cost,
        automatically_supplied,
        tuple(rationale),
    )


def assess_epoch_saturation(
    state: SpiderState,
    opportunities: Sequence[PreDealOpportunity],
) -> EpochSaturationAssessment:
    started = time.perf_counter()
    del started  # timing is collected by the caller without entering identity
    epoch = current_stock_epoch(state)
    ordered = tuple(sorted(opportunities, key=lambda item: item.ordering_key()))
    counts = Counter(item.classification for item in ordered)
    must = tuple(
        item
        for item in ordered
        if item.classification == PreDealOpportunityClass.MUST_PRE_DEAL
    )
    advantage = tuple(
        item
        for item in ordered
        if item.classification == PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
    )
    if not state.stock:
        status = EpochSaturationStatus.STOCK_EMPTY
        selected = None
        reason = "stock is empty; normal construction and foundation play continue"
    elif must:
        status = EpochSaturationStatus.PREPARATION_REQUIRED
        selected = must[0]
        reason = "at least one actionable opportunity is materially lost by the next Deal"
    elif advantage:
        status = EpochSaturationStatus.PREPARATION_ADVANTAGE
        selected = advantage[0]
        reason = "one strongest bounded preparation may compete before fresh reassessment"
    else:
        status = EpochSaturationStatus.DEAL_READY
        selected = None
        reason = "no bounded current preparation has greater marginal value than Deal Now"
    return EpochSaturationAssessment(
        status,
        epoch,
        ordered,
        selected,
        counts[PreDealOpportunityClass.MUST_PRE_DEAL],
        counts[PreDealOpportunityClass.ADVANTAGE_PRE_DEAL],
        counts[PreDealOpportunityClass.DEFERRABLE],
        counts[PreDealOpportunityClass.FUTURE_SUPPLIED],
        counts[PreDealOpportunityClass.NON_ECONOMIC],
        counts[PreDealOpportunityClass.INVALID],
        reason,
    )


def preview_deal_now(
    state: SpiderState,
    blueprint: WholeDealBlueprint,
    *,
    config: WholeDealSchedulerConfig = WholeDealSchedulerConfig(),
    generation: int = 0,
) -> Optional[DealNowCounterfactual]:
    """Apply one real engine Deal and build one non-recursive fresh schedule."""

    if not state.stock or not state.can_deal(MW_RULES):
        return None
    started = time.perf_counter()
    row = tuple(future_stock_rows(state)[0])
    post = state.clone()
    cost = post.deal(MW_RULES)
    post_schedule = rebuild_whole_deal_schedule(
        post,
        blueprint,
        config=config,
        generation=generation + 1,
        _include_deal_preview=False,
    )
    elapsed = time.perf_counter() - started
    return DealNowCounterfactual(
        canonical_state_key(state),
        _state_fingerprint(state),
        current_stock_epoch(state),
        row,
        cost,
        post,
        _state_fingerprint(post),
        post_schedule,
        (),
        tuple(item.objective_id for item in post_schedule.objectives),
        elapsed,
    )


def _same_suit_edge_count(state: SpiderState) -> int:
    return sum(len(_stable_edges(state, suit)) for suit in SUITS)


def _harmful_boundary_count(state: SpiderState) -> int:
    return sum(
        lower.rank - 1 == upper.rank and lower.suit != upper.suit
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )


def compare_prepare_then_deal(
    before: SpiderState,
    candidate_end_state: SpiderState,
    objective: ScheduledStructuralObjective,
    deal_now: DealNowCounterfactual,
    *,
    candidate_actions: Sequence[Tuple] = (),
    preparation_cost: int = 0,
) -> Optional[PrepareThenDealComparison]:
    """Compare an already-generated legal candidate followed by one exact Deal."""

    if not candidate_end_state.stock or not candidate_end_state.can_deal(MW_RULES):
        return None
    started = time.perf_counter()
    prepared = candidate_end_state.clone()
    prepared.deal(MW_RULES)
    direct = deal_now.post_deal_state
    edge_delta = _same_suit_edge_count(prepared) - _same_suit_edge_count(direct)
    foundation_delta = len(prepared.foundations) - len(direct.foundations)
    face_down_delta = sum(len(c.face_down) for c in direct.columns) - sum(
        len(c.face_down) for c in prepared.columns
    )
    harmful_delta = _harmful_boundary_count(direct) - _harmful_boundary_count(prepared)
    progress = objective_progress(direct, prepared, objective)
    structural_return = (
        max(0, edge_delta)
        + max(0, foundation_delta) * 12
        + max(0, face_down_delta)
        + max(0, harmful_delta)
    )
    demonstrably_better = bool(
        foundation_delta > 0
        or progress in {
            ScheduleObjectiveStatus.SATISFIED,
            ScheduleObjectiveStatus.ADVANCED,
        }
        or (structural_return > 0 and structural_return >= preparation_cost)
    )
    rationale = (
        "comparison uses only an existing replay-valid successor and one engine Deal",
        f"same_suit_edge_delta={edge_delta}",
        f"foundation_delta={foundation_delta}",
        f"face_down_improvement={face_down_delta}",
        f"harmful_boundary_reduction={harmful_delta}",
        f"preparation_cost={preparation_cost}",
    )
    return PrepareThenDealComparison(
        objective.objective_id,
        tuple(candidate_actions),
        preparation_cost,
        deal_now.post_deal_state_fingerprint,
        prepared,
        _state_fingerprint(prepared),
        progress,
        edge_delta,
        foundation_delta,
        face_down_delta,
        harmful_delta,
        demonstrably_better,
        rationale,
        time.perf_counter() - started,
    )


def rebuild_whole_deal_schedule(
    state: SpiderState,
    blueprint: WholeDealBlueprint,
    *,
    config: WholeDealSchedulerConfig = WholeDealSchedulerConfig(),
    generation: int = 0,
    _include_deal_preview: bool = True,
) -> WholeDealSchedule:
    """Rebuild a receding-horizon schedule from the current exact state."""
    started = time.perf_counter()
    epoch = current_stock_epoch(state)
    assignment_started = time.perf_counter()
    removed = _removed_by_suit(state)
    planned_free_counts: Counter = Counter()
    exact_rows = future_stock_rows(state)
    if exact_rows:
        for column, incoming in enumerate(exact_rows[0]):
            top = state.columns[column].top()
            if (
                top is not None
                and top.suit == incoming.suit
                and top.rank - 1 == incoming.rank
            ):
                planned_free_counts[(incoming.suit, top.rank, incoming.rank)] += 1
    suit_plans = []
    for suit in SUITS:
        floors = tuple(
            item for item in blueprint.foundation_floors
            if item.suit == suit and item.copy_threshold > removed[suit]
        )
        assignments = _assignment_signatures(state, suit, len(floors))
        lanes = []
        stable = _stable_edges(state, suit)
        for lane_index, floor in enumerate(floors):
            threshold = floor.copy_threshold
            counts = blueprint.counts(suit, epoch)
            gated = set()
            adjacencies = []
            for high in range(13, 1, -1):
                edge = (high, high - 1)
                if edge in stable:
                    status = AdjacencyStatus.SATISFIED
                elif planned_free_counts[(suit, high, high - 1)] >= lane_index + 1:
                    status = AdjacencyStatus.PLANNED_FUTURE_FREE
                elif counts[high - 1] < threshold or counts[high - 2] < threshold:
                    status = AdjacencyStatus.FUTURE_GATED
                    gated.add(edge)
                else:
                    status = AdjacencyStatus.MISSING
                adjacencies.append(
                    AdjacencyTarget(suit, lane_index + 1, high, high - 1, epoch, status)
                )
            blueprint_fragments = tuple(
                fragment for fragment in blueprint.fragments_by_epoch
                if fragment.suit == suit
                and fragment.lane == floor.lane
                and fragment.target_epoch == epoch
            )
            dynamic_fragments = tuple(
                _dynamic_fragment(state, fragment, gated)
                for fragment in blueprint_fragments
            )
            lanes.append(
                SuitLanePlan(
                    suit,
                    lane_index + 1,
                    threshold,
                    floor.earliest_epoch,
                    assignments[lane_index] if lane_index < len(assignments) else (),
                    tuple(adjacencies),
                    dynamic_fragments,
                )
            )
        suit_plans.append(
            SuitEpochPlan(suit, epoch, max(0, 2 - removed[suit]), tuple(lanes))
        )
    assignment_seconds = time.perf_counter() - assignment_started

    leverage_started = time.perf_counter()
    leverage = _leverage_assessments(state, blueprint)
    leverage_seconds = time.perf_counter() - leverage_started
    reception_started = time.perf_counter()
    receptions = analyze_next_deal_reception(
        state,
        leverage,
        maximum_preparation_cost=config.maximum_reception_prep_cost,
    )
    reception_seconds = time.perf_counter() - reception_started
    all_objectives = _build_objectives(state, epoch, suit_plans, receptions, leverage)
    selected_objectives = []
    selected_ids = set()
    # Four-suit planning needs campaign diversity: when the configured bound
    # permits it, reserve the best target for every remaining suit before
    # filling with the globally strongest additional targets.
    if config.max_objectives >= len(SUITS):
        late_suits = {
            plan.suit
            for plan in suit_plans
            if plan.lanes
            and plan.lanes[0].availability_floor is not None
            and plan.lanes[0].availability_floor > epoch
        }
        for suit in SUITS:
            candidate = None
            if suit in late_suits:
                candidate = next(
                    (
                        item for item in all_objectives
                        if item.suit == suit
                        and item.family in {
                            ScheduleObjectiveFamily.BUILD_FRAGMENT,
                            ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE,
                        }
                    ),
                    None,
                )
            if candidate is None:
                candidate = next(
                    (item for item in all_objectives if item.suit == suit), None
                )
            if candidate is not None:
                selected_objectives.append(candidate)
                selected_ids.add(candidate.objective_id)
    for candidate in all_objectives:
        if candidate.objective_id in selected_ids:
            continue
        selected_objectives.append(candidate)
        selected_ids.add(candidate.objective_id)
        if len(selected_objectives) >= config.max_objectives:
            break
    fallback_objectives = tuple(
        sorted(
            selected_objectives[: config.max_objectives],
            key=lambda item: item.ordering_key(),
        )
    )
    base = WholeDealSchedule(
        blueprint.blueprint_id,
        _state_fingerprint(state),
        epoch,
        tuple(suit_plans),
        receptions,
        leverage,
        all_objectives,
        False,
        generation=generation,
        performance=SchedulerPerformance(
            reception_seconds=reception_seconds,
            duplicate_assignment_seconds=assignment_seconds,
            leverage_seconds=leverage_seconds,
        ),
    )
    preview = (
        preview_deal_now(
            state,
            blueprint,
            config=config,
            generation=generation,
        )
        if _include_deal_preview
        else None
    )
    saturation_started = time.perf_counter()
    all_opportunities = tuple(
        classify_pre_deal_objective(
            state,
            objective,
            preview,
            current_schedule=base,
        )
        for objective in all_objectives
        if objective.family != ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION
    )
    typed_by_id = {
        item.objective.objective_id: item for item in all_opportunities
    }
    typed_priority = tuple(
        sorted(all_opportunities, key=lambda item: item.ordering_key())
    )
    final_objectives = []
    final_ids = set()

    def retain(objective: ScheduledStructuralObjective) -> None:
        if (
            len(final_objectives) < config.max_objectives
            and objective.objective_id not in final_ids
        ):
            final_objectives.append(objective)
            final_ids.add(objective.objective_id)

    for item in typed_priority:
        if item.classification == PreDealOpportunityClass.MUST_PRE_DEAL:
            retain(item.objective)
    best_advantage = next(
        (
            item
            for item in typed_priority
            if item.classification
            == PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
        ),
        None,
    )
    if best_advantage is not None:
        retain(best_advantage.objective)
    for objective in fallback_objectives:
        typed = typed_by_id.get(objective.objective_id)
        if (
            typed is not None
            and typed.classification
            == PreDealOpportunityClass.ADVANTAGE_PRE_DEAL
            and objective.objective_id
            != (
                best_advantage.objective.objective_id
                if best_advantage is not None
                else None
            )
        ):
            continue
        retain(objective)
    for objective in all_objectives:
        retain(objective)
    objectives = tuple(sorted(final_objectives, key=lambda item: item.ordering_key()))
    if preview is not None:
        preview = replace(
            preview,
            objective_ids_before=tuple(item.objective_id for item in objectives),
        )
    opportunities = tuple(
        item for item in all_opportunities
        if item.objective.objective_id in final_ids
    )
    saturation = assess_epoch_saturation(state, opportunities)
    saturation_seconds = time.perf_counter() - saturation_started
    schedule_seconds = time.perf_counter() - started
    return replace(
        base,
        objectives=objectives,
        deal_now_preferred=(
            saturation.status == EpochSaturationStatus.DEAL_READY
            and state.can_deal(MW_RULES)
        ),
        pre_deal_opportunities=opportunities,
        saturation=saturation,
        deal_now_counterfactual=preview,
        performance=SchedulerPerformance(
            schedule_seconds=schedule_seconds,
            reception_seconds=reception_seconds,
            duplicate_assignment_seconds=assignment_seconds,
            leverage_seconds=leverage_seconds,
            deal_now_preview_seconds=(preview.preview_seconds if preview else 0.0),
            saturation_seconds=saturation_seconds,
        ),
    )


def objective_progress(
    before: SpiderState,
    after: SpiderState,
    objective: ScheduledStructuralObjective,
) -> ScheduleObjectiveStatus:
    """Evaluate one advisory objective without making a proof claim."""
    if objective.family == ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION:
        return (
            ScheduleObjectiveStatus.SATISFIED
            if current_stock_epoch(after) > current_stock_epoch(before)
            else ScheduleObjectiveStatus.PLANNED
        )
    if objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION:
        if current_stock_epoch(after) > current_stock_epoch(before):
            return ScheduleObjectiveStatus.SATISFIED
        if objective.target_column is None or objective.source_card is None:
            return ScheduleObjectiveStatus.INVALIDATED
        desired = (
            Card(objective.source_card.suit, objective.source_card.rank + 1)
            if objective.source_card.rank < 13 else None
        )
        return (
            ScheduleObjectiveStatus.SATISFIED
            if desired is not None and after.columns[objective.target_column].top() == desired
            else ScheduleObjectiveStatus.PLANNED
        )
    if (
        objective.source_card is not None
        and objective.family in {
            ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD,
            ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD,
        }
    ):
        card = objective.source_card
        before_refs = enumerate_temporal_cards(before)
        after_refs = enumerate_temporal_cards(after)
        exact_before = next(
            (
                item for item in before_refs
                if objective.source_ref_id is not None
                and item.ref_id == objective.source_ref_id
            ),
            None,
        )
        before_depth = min(
            (item.depth for item in before_refs if item.card == card and item.temporal_kind != TemporalAvailabilityKind.FUTURE_STOCK),
            default=99,
        )
        if exact_before is not None:
            before_depth = exact_before.depth
        after_depth = min(
            (item.depth for item in after_refs if item.card == card and item.temporal_kind != TemporalAvailabilityKind.FUTURE_STOCK),
            default=99,
        )
        before_exposed = sum(
            item.card == card
            and item.temporal_kind == TemporalAvailabilityKind.CURRENT_EXPOSED
            for item in before_refs
        )
        after_exposed = sum(
            item.card == card
            and item.temporal_kind == TemporalAvailabilityKind.CURRENT_EXPOSED
            for item in after_refs
        )
        if after_exposed > before_exposed:
            return ScheduleObjectiveStatus.SATISFIED
        if after_depth == 0 and before_depth > 0:
            return ScheduleObjectiveStatus.SATISFIED
        if after_depth < before_depth:
            return ScheduleObjectiveStatus.ADVANCED
    if objective.suit is not None:
        before_edges = _stable_edges(before, objective.suit)
        after_edges = _stable_edges(after, objective.suit)
        target_edges = {
            (rank, rank - 1)
            for rank in range(objective.high_rank or 1, objective.low_rank or 1, -1)
        }
        old_count = len(before_edges & target_edges)
        new_count = len(after_edges & target_edges)
        if target_edges and new_count == len(target_edges):
            return ScheduleObjectiveStatus.SATISFIED
        if new_count > old_count:
            return ScheduleObjectiveStatus.ADVANCED
    return ScheduleObjectiveStatus.PLANNED


def derive_schedule_delta(
    before_state: SpiderState,
    after_state: SpiderState,
    before: WholeDealSchedule,
    after: WholeDealSchedule,
    *,
    selected_objective: Optional[ScheduledStructuralObjective] = None,
) -> Tuple[ScheduleDelta, ...]:
    result = []
    if selected_objective is not None:
        progress = objective_progress(before_state, after_state, selected_objective)
        if progress == ScheduleObjectiveStatus.SATISFIED:
            result.append(
                ScheduleDelta(
                    ScheduleDeltaKind.TARGET_SATISFIED,
                    selected_objective.objective_id,
                    f"{selected_objective.family.value} predicate satisfied",
                    before.epoch,
                    after.epoch,
                )
            )
        elif progress == ScheduleObjectiveStatus.ADVANCED:
            result.append(
                ScheduleDelta(
                    ScheduleDeltaKind.TARGET_ADVANCED,
                    selected_objective.objective_id,
                    f"{selected_objective.family.value} made structural progress",
                    before.epoch,
                    after.epoch,
                )
            )
    if after.epoch > before.epoch:
        result.append(
            ScheduleDelta(
                ScheduleDeltaKind.DEADLINE_ADVANCED,
                None,
                "stock epoch advanced; all pre-Deal targets were freshly rebuilt",
                before.epoch,
                after.epoch,
            )
        )
        for reception in before.receptions:
            column = after_state.columns[reception.column]
            realized = bool(
                len(column.face_up) >= 2
                and column.face_up[-1] == reception.incoming
                and reception.desired_receiver is not None
                and column.face_up[-2] == reception.desired_receiver
            )
            tracked_reception = bool(
                reception.receiver_satisfied or reception.worthwhile_preparation
            )
            if realized or tracked_reception:
                result.append(
                    ScheduleDelta(
                        (
                            ScheduleDeltaKind.RECEPTION_REALIZED
                            if realized else ScheduleDeltaKind.RECEPTION_MISSED
                        ),
                        reception.opportunity_id,
                        (
                            "planned receiver condition produced the incoming adjacency"
                            if realized
                            else "receiver condition was not realized; no impossibility is inferred"
                        ),
                        before.epoch,
                        after.epoch,
                    )
                )
            if tracked_reception and not realized:
                matching_objective = next(
                    (
                        item for item in before.objectives
                        if item.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
                        and item.target_column == reception.column
                        and item.source_card == reception.incoming
                    ),
                    None,
                )
                if matching_objective is not None:
                    result.append(
                        ScheduleDelta(
                            ScheduleDeltaKind.TARGET_INVALIDATED,
                            matching_objective.objective_id,
                            "pre-Deal receiver target expired at its deadline and was removed",
                            before.epoch,
                            after.epoch,
                        )
                    )
        for plan in before.suit_plans:
            for lane in plan.lanes:
                if lane.availability_floor == after.epoch:
                    result.append(
                        ScheduleDelta(
                            ScheduleDeltaKind.FOUNDATION_FLOOR_REACHED,
                            None,
                            f"{plan.suit} lane {lane.lane} reached its temporal material floor",
                            before.epoch,
                            after.epoch,
                        )
                    )
    before_assignments = tuple(
        (plan.suit, lane.lane, lane.assignment_signature)
        for plan in before.suit_plans for lane in plan.lanes
    )
    after_assignments = tuple(
        (plan.suit, lane.lane, lane.assignment_signature)
        for plan in after.suit_plans for lane in plan.lanes
    )
    if before_assignments != after_assignments:
        result.append(
            ScheduleDelta(
                ScheduleDeltaKind.TARGET_REASSIGNED,
                None,
                "symmetric lane contributions were canonicalised from fresh structure",
                before.epoch,
                after.epoch,
            )
        )
    before_bridge = {
        (item.card.suit, item.card.rank): item
        for item in before.leverage_cards if item.is_bridge
    }
    after_bridge = {
        (item.card.suit, item.card.rank): item
        for item in after.leverage_cards if item.is_bridge
    }
    for key, source in before_bridge.items():
        previous_edges = sum(
            edge in _stable_edges(before_state, key[0])
            for edge in ((min(13, key[1] + 1), key[1]), (key[1], max(1, key[1] - 1)))
            if edge[0] != edge[1]
        )
        current_edges = sum(
            edge in _stable_edges(after_state, key[0])
            for edge in ((min(13, key[1] + 1), key[1]), (key[1], max(1, key[1] - 1)))
            if edge[0] != edge[1]
        )
        before_exposed = sum(
            item.card == source.card
            and item.temporal_kind == TemporalAvailabilityKind.CURRENT_EXPOSED
            for item in enumerate_temporal_cards(before_state)
        )
        after_exposed = sum(
            item.card == source.card
            and item.temporal_kind == TemporalAvailabilityKind.CURRENT_EXPOSED
            for item in enumerate_temporal_cards(after_state)
        )
        if source.excavation_candidate and after_exposed > before_exposed:
            result.append(
                ScheduleDelta(
                    ScheduleDeltaKind.BRIDGE_EXPOSED,
                    selected_objective.objective_id if selected_objective else None,
                    f"high-leverage {source.card} became exposed",
                    before.epoch,
                    after.epoch,
                )
            )
        if current_edges > previous_edges:
            result.append(
                ScheduleDelta(
                    ScheduleDeltaKind.BRIDGE_CONSUMED,
                    selected_objective.objective_id if selected_objective else None,
                    f"high-leverage {source.card} entered additional same-suit adjacency",
                    before.epoch,
                    after.epoch,
                )
            )
    new_sources = set(after_bridge) - set(before_bridge)
    if new_sources:
        result.append(
            ScheduleDelta(
                ScheduleDeltaKind.NEW_HIGH_LEVERAGE_SOURCE,
                None,
                "fresh exact structure created a new two-sided leverage candidate",
                before.epoch,
                after.epoch,
            )
        )
    if after.deal_now_preferred and not before.deal_now_preferred:
        result.append(
            ScheduleDelta(
                ScheduleDeltaKind.DEAL_NOW_PREFERRED,
                None,
                "no remaining bounded next-Deal preparation outranks Deal Now",
                before.epoch,
                after.epoch,
            )
        )
    return tuple(result)


def scheduler_objective_effect(
    before: SpiderState,
    after: SpiderState,
    objective: ScheduledStructuralObjective,
) -> Tuple[int, Tuple[str, ...]]:
    """Return an inspectable ordering rank for an existing legal successor.

    ``0`` means satisfied, ``1`` advanced, and ``2`` no demonstrated effect.
    The result is heuristic annotation only.
    """
    progress = objective_progress(before, after, objective)
    if progress == ScheduleObjectiveStatus.SATISFIED:
        return 0, (f"scheduler objective satisfied: {objective.objective_id}",)
    if progress == ScheduleObjectiveStatus.ADVANCED:
        return 1, (f"scheduler objective advanced: {objective.objective_id}",)
    return 2, ()


def pre_deal_opportunity_for_objective(
    schedule: WholeDealSchedule,
    objective: ScheduledStructuralObjective,
) -> Optional[PreDealOpportunity]:
    return next(
        (
            item
            for item in schedule.pre_deal_opportunities
            if item.objective.objective_id == objective.objective_id
        ),
        None,
    )


def epoch_transition_objective(
    state: SpiderState,
    schedule: WholeDealSchedule,
) -> Optional[ScheduledStructuralObjective]:
    saturation = schedule.saturation
    rows = future_stock_rows(state)
    if (
        saturation is None
        or saturation.status != EpochSaturationStatus.DEAL_READY
        or not rows
        or not state.can_deal(MW_RULES)
    ):
        return None
    row = tuple((card.suit, card.rank) for card in rows[0])
    return ScheduledStructuralObjective(
        _objective_id(
            (
                ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION.value,
                schedule.exact_state_fingerprint,
                schedule.epoch,
                row,
            )
        ),
        ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION,
        ScheduleObjectiveStatus.ACTIONABLE,
        None,
        None,
        None,
        None,
        None,
        None,
        schedule.epoch + 1,
        ScheduleDeadlineKind.NO_HARD_DEADLINE,
        1,
        0,
        0,
        0,
        0,
        (
            "fresh marginal analysis classifies the current epoch Deal-ready",
            "the existing legal Deal may receive one post-TT representative",
            "this is bounded coverage, not a Deal score bonus",
        ),
    )


def classify_epoch_transition_harvest(
    before_state: SpiderState,
    after_state: SpiderState,
    before: WholeDealSchedule,
    after: WholeDealSchedule,
) -> Tuple[EpochTransitionHarvest, ...]:
    """Describe actual structural consequences; the Deal itself is not harvest."""

    result = []
    for reception in before.receptions:
        column = after_state.columns[reception.column]
        incoming_present = bool(column.face_up and column.face_up[-1] == reception.incoming)
        realized_join = bool(
            len(column.face_up) >= 2
            and column.face_up[-1] == reception.incoming
            and reception.desired_receiver is not None
            and column.face_up[-2] == reception.desired_receiver
        )
        if realized_join:
            kind = (
                EpochTransitionHarvestKind.REALIZED_FOUNDATION_TRIGGER
                if reception.kind == StockReceptionKind.FOUNDATION_TRIGGER
                else EpochTransitionHarvestKind.REALIZED_FREE_JOIN
            )
            result.append(
                EpochTransitionHarvest(
                    kind,
                    "the exact incoming card realized its predicted same-suit reception",
                    reception.column,
                    reception.incoming,
                    predicted=True,
                )
            )
        elif reception.kind == StockReceptionKind.USEFUL_ISOLATION and incoming_present:
            result.append(
                EpochTransitionHarvest(
                    EpochTransitionHarvestKind.USEFUL_ISOLATION,
                    "the incoming source landed in the predicted isolated column",
                    reception.column,
                    reception.incoming,
                    predicted=True,
                )
            )
        elif reception.kind == StockReceptionKind.HARMFUL_RECEPTION and incoming_present:
            result.append(
                EpochTransitionHarvest(
                    EpochTransitionHarvestKind.HARMFUL_RECEPTION,
                    "the exact incoming row covered a stable current fragment",
                    reception.column,
                    reception.incoming,
                    predicted=True,
                )
            )
    if len(after_state.foundations) > len(before_state.foundations) and not any(
        item.kind == EpochTransitionHarvestKind.REALIZED_FOUNDATION_TRIGGER
        for item in result
    ):
        result.append(
            EpochTransitionHarvest(
                EpochTransitionHarvestKind.REALIZED_FOUNDATION_TRIGGER,
                "automatic removal occurred during the exact Deal transition",
                predicted=False,
            )
        )
    next_epoch = before.epoch + 1
    next_cards = {
        (item.column, item.card)
        for item in before.leverage_cards
        if item.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
        and item.availability_epoch == next_epoch
        and item.is_bridge
    }
    for column, card in sorted(
        next_cards,
        key=lambda item: (item[0] if item[0] is not None else 99, item[1].suit, item[1].rank),
    ):
        if column is not None and card in after_state.columns[column].face_up:
            result.append(
                EpochTransitionHarvest(
                    EpochTransitionHarvestKind.REALIZED_BRIDGE_ARRIVAL,
                    "a known two-sided bridge entered the tableau on schedule",
                    column,
                    card,
                    predicted=True,
                )
            )
            result.append(
                EpochTransitionHarvest(
                    EpochTransitionHarvestKind.HIGH_LEVERAGE_SOURCE_ARRIVED,
                    "fresh next-epoch analysis can now act on the arrived source",
                    column,
                    card,
                    predicted=True,
                )
            )
    before_ids = {item.objective_id for item in before.objectives}
    new_objectives = tuple(
        item for item in after.objectives if item.objective_id not in before_ids
    )
    if new_objectives:
        result.append(
            EpochTransitionHarvest(
                EpochTransitionHarvestKind.NEW_FRAGMENT_OPPORTUNITY,
                f"fresh epoch schedule produced {len(new_objectives)} new bounded objectives",
                predicted=False,
            )
        )
    if not result:
        result.append(
            EpochTransitionHarvest(
                EpochTransitionHarvestKind.EXPECTED_NEUTRAL_TRANSITION,
                "the mandatory epoch transition produced no named immediate harvest",
                predicted=True,
            )
        )
    unique = {}
    for item in result:
        unique[(item.kind, item.column, item.card)] = item
    return tuple(unique.values())


def make_epoch_transition_opportunity(
    source_state: SpiderState,
    child_state: SpiderState,
    source_schedule: WholeDealSchedule,
    child_schedule: WholeDealSchedule,
    *,
    corrected_g_after_deal: int,
    stable_structure_after: int,
    rehandling_debt_after: float,
    deal_kind: SchedulerDealKind = SchedulerDealKind.DEAL_NOW,
    exact_tt_admitted: bool,
    independently_replay_verified: bool,
) -> Optional[EpochTransitionOpportunity]:
    saturation = source_schedule.saturation
    rows = future_stock_rows(source_state)
    if (
        saturation is None
        or saturation.status != EpochSaturationStatus.DEAL_READY
        or not rows
        or current_stock_epoch(child_state) != source_schedule.epoch + 1
        or not exact_tt_admitted
        or not independently_replay_verified
    ):
        return None
    source_key = canonical_state_key(source_state)
    row = tuple(rows[0])
    identity = (
        source_key,
        source_schedule.epoch,
        tuple((card.suit, card.rank) for card in row),
    )
    opportunity_id = hashlib.sha256(repr(identity).encode("utf-8")).hexdigest()[:16]
    return EpochTransitionOpportunity(
        opportunity_id,
        source_key,
        source_schedule.exact_state_fingerprint,
        source_schedule.epoch,
        row,
        corrected_g_after_deal,
        saturation,
        deal_kind,
        stable_structure_after,
        rehandling_debt_after,
        len(child_schedule.objectives),
        classify_epoch_transition_harvest(
            source_state,
            child_state,
            source_schedule,
            child_schedule,
        ),
        exact_tt_admitted=exact_tt_admitted,
        independently_replay_verified=independently_replay_verified,
    )


def build_epoch_transition_trace(
    opportunity: EpochTransitionOpportunity,
    *,
    corrected_g_before: int,
    epoch_after: int,
    next_schedule: WholeDealSchedule,
    expanded: bool,
) -> EpochTransitionTrace:
    saturation = opportunity.saturation
    selected = saturation.selected_preparation
    by_class = {
        classification: tuple(
            item.objective.objective_id
            for item in saturation.opportunities
            if item.classification == classification
        )
        for classification in PreDealOpportunityClass
    }
    return EpochTransitionTrace(
        opportunity.opportunity_id,
        opportunity.source_state_fingerprint,
        corrected_g_before,
        opportunity.corrected_g_after_deal,
        opportunity.source_epoch,
        epoch_after,
        saturation.status,
        by_class[PreDealOpportunityClass.MUST_PRE_DEAL],
        by_class[PreDealOpportunityClass.ADVANTAGE_PRE_DEAL],
        by_class[PreDealOpportunityClass.DEFERRABLE],
        by_class[PreDealOpportunityClass.FUTURE_SUPPLIED],
        selected.objective.objective_id if selected is not None else None,
        opportunity.deal_kind,
        opportunity.incoming_row,
        opportunity.exact_tt_admitted,
        opportunity.status == EpochTransitionRepresentativeStatus.RESERVED,
        expanded,
        opportunity.harvests,
        tuple(item.objective_id for item in next_schedule.objectives),
    )


def choose_scheduler_annotations(
    before: SpiderState,
    successors: Sequence[object],
    schedule: WholeDealSchedule,
    *,
    maximum: int = 1,
) -> Tuple[Tuple[int, ScheduledStructuralObjective, int], ...]:
    """Match bounded scheduler targets to existing successor end states.

    The return values are ``(successor_index, objective, effect_rank)``.  This
    module intentionally knows nothing about controller action classes and
    never creates or executes an action.
    """
    saturation = schedule.saturation
    if saturation is None:
        eligible_objectives = schedule.objectives
    elif saturation.status in {
        EpochSaturationStatus.PREPARATION_REQUIRED,
        EpochSaturationStatus.PREPARATION_ADVANTAGE,
    }:
        selected = saturation.selected_preparation
        eligible_objectives = (
            (selected.objective,) if selected is not None else ()
        )
    elif saturation.status == EpochSaturationStatus.DEAL_READY:
        transition = epoch_transition_objective(before, schedule)
        has_direct_deal = any(
            tuple(getattr(successor, "actions", ())) == (("deal",),)
            for successor in successors
        )
        eligible_objectives = (
            (transition,)
            if transition is not None and has_direct_deal
            else schedule.objectives
        )
    else:
        eligible_objectives = schedule.objectives
    matches = []
    for objective in eligible_objectives:
        for index, successor in enumerate(successors):
            end_state = getattr(successor, "end_state", None)
            if end_state is None:
                continue
            effect_rank, _notes = scheduler_objective_effect(before, end_state, objective)
            kind_value = getattr(getattr(successor, "kind", None), "value", "")
            if objective.family == ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION:
                compatible = bool(
                    "DEAL" in kind_value
                    and tuple(getattr(successor, "actions", ())) == (("deal",),)
                )
            else:
                compatible = bool(
                    effect_rank < 2
                    and not any(
                        action == ("deal",)
                        for action in tuple(getattr(successor, "actions", ()))
                    )
                )
            if compatible:
                matches.append((objective.ordering_key(), effect_rank, index, objective))
    matches.sort(key=lambda item: (item[1], item[0], item[2]))
    selected = []
    used_indices = set()
    for _order, effect, index, objective in matches:
        if index in used_indices:
            continue
        selected.append((index, objective, effect))
        used_indices.add(index)
        if len(selected) >= maximum:
            break
    return tuple(selected)
