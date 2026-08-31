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
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.epoch_progression import current_stock_epoch, future_stock_rows


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


@dataclass(frozen=True)
class SchedulerPerformance:
    blueprint_seconds: float = field(default=0.0, compare=False)
    schedule_seconds: float = field(default=0.0, compare=False)
    reception_seconds: float = field(default=0.0, compare=False)
    duplicate_assignment_seconds: float = field(default=0.0, compare=False)
    leverage_seconds: float = field(default=0.0, compare=False)


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
                    else ScheduleDeadlineKind.BY_EPOCH_N
                ),
                source.estimated_structural_work,
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
                fragment.target_epoch,
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


def rebuild_whole_deal_schedule(
    state: SpiderState,
    blueprint: WholeDealBlueprint,
    *,
    config: WholeDealSchedulerConfig = WholeDealSchedulerConfig(),
    generation: int = 0,
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
    objectives = tuple(
        sorted(
            selected_objectives[: config.max_objectives],
            key=lambda item: item.ordering_key(),
        )
    )
    worthwhile_prep = any(
        item.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
        and item.status != ScheduleObjectiveStatus.SATISFIED
        for item in objectives
    )
    schedule_seconds = time.perf_counter() - started
    return WholeDealSchedule(
        blueprint.blueprint_id,
        _state_fingerprint(state),
        epoch,
        tuple(suit_plans),
        receptions,
        leverage,
        objectives,
        bool(state.can_deal() and not worthwhile_prep),
        generation,
        performance=SchedulerPerformance(
            schedule_seconds=schedule_seconds,
            reception_seconds=reception_seconds,
            duplicate_assignment_seconds=assignment_seconds,
            leverage_seconds=leverage_seconds,
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
    matches = []
    for objective in schedule.objectives:
        for index, successor in enumerate(successors):
            end_state = getattr(successor, "end_state", None)
            if end_state is None:
                continue
            effect_rank, _notes = scheduler_objective_effect(before, end_state, objective)
            kind_value = getattr(getattr(successor, "kind", None), "value", "")
            if objective.family == ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION:
                compatible = "DEAL" in kind_value
            else:
                compatible = effect_rank < 2
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
