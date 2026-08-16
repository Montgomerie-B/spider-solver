"""Bounded realisation of a fixed foundation campaign to actual removal.

The search composes one remaining stock epoch from a verified campaign state.
It derives target bands and receiver geometry from ``FoundationCampaign`` and
its exact ``CampaignEpochPlan``.  Campaign estimates order search only; every
successful route is independently replayed with the engine and corrected
MobilityWare accounting.

This module never searches beyond the frozen campaign removal epoch and never
calls the whole-game planner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.planner.foundation_campaign import (
    CampaignEpochPlan,
    FoundationCampaign,
    analyze_foundation_campaign,
)
from spider.planner.foundation_campaign_realizer import CampaignIdentity
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.space_lifecycle import empty_columns
from spider.planner.stock_reception import next_stock_row
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal


class CampaignRemovalStatus(str, Enum):
    FOUNDATION_REMOVED = "foundation_removed"
    BAND_COMPLETE = "band_complete"
    PARTIAL = "partial"
    NOT_FOUND_WITHIN_BOUND = "not_found_within_bound"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_CAMPAIGN = "invalid_campaign"


class CampaignRemovalObligationKind(str, Enum):
    JOIN_RECEIVED_STOCK = "join_received_stock"
    ASSEMBLE_SAME_SUIT_BAND = "assemble_same_suit_band"
    POSITION_BAND_FOR_INCOMING = "position_band_for_incoming"
    PRESERVE_CAMPAIGN_FRAGMENT = "preserve_campaign_fragment"
    PREPARE_WORKSPACE = "prepare_workspace"
    APPLY_DEAL = "apply_deal"
    CONNECT_CAMPAIGN_BANDS = "connect_campaign_bands"
    REMOVE_FOUNDATION = "remove_foundation"
    VERIFY_FOUNDATION_REMOVAL = "verify_foundation_removal"


@dataclass(frozen=True)
class CampaignBand:
    suit: str
    high_rank: int
    low_rank: int
    column: int
    start_index: int
    end_index: int
    movable: bool
    covered: bool
    covering_cards: Tuple[Card, ...]
    selected_source_keys: Tuple[str, ...]
    cards: Tuple[Card, ...]

    @property
    def length(self) -> int:
        return self.high_rank - self.low_rank + 1

    @property
    def face_up_interval(self) -> Tuple[int, int]:
        return (self.start_index, self.end_index)

    @property
    def label(self) -> str:
        return (
            f"{self.high_rank}-{self.low_rank}{self.suit}@c{self.column + 1}"
            f"{'/covered' if self.covered else '/top'}"
        )


@dataclass(frozen=True)
class CampaignBandRecovery:
    band: CampaignBand
    covering_groups: int
    covering_cards: Tuple[Card, ...]
    destination_ranks: Tuple[Optional[int], ...]
    already_recovered: bool


@dataclass(frozen=True)
class CampaignReceiverCondition:
    incoming_card: Card
    incoming_column: int
    receiver_rank: Optional[int]
    target_interval: Optional[Tuple[int, int]]
    direct: bool
    bounded_walkoff: bool
    walkoff_actions: Tuple[Action, ...]
    note: str


@dataclass(frozen=True)
class CampaignRemovalObligation:
    obligation_id: str
    kind: CampaignRemovalObligationKind
    phase: str
    description: str
    mandatory: bool
    high_rank: Optional[int] = None
    low_rank: Optional[int] = None
    column: Optional[int] = None
    incoming_card: Optional[Card] = None
    receiver_rank: Optional[int] = None
    source_columns: Tuple[int, ...] = ()
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignRemovalProgress:
    phase: str
    action_count: int
    corrected_added_cost: int
    epoch: int
    bands: Tuple[CampaignBand, ...]
    obligations_satisfied: Tuple[str, ...]
    obligations_remaining: Tuple[str, ...]
    empty_columns: Tuple[int, ...]
    foundation_count: int
    note: str


@dataclass(frozen=True)
class CampaignEpochResult:
    phase: str
    status: CampaignRemovalStatus
    actions: Tuple[Action, ...]
    corrected_cost: int
    nodes_expanded: int
    elapsed_seconds: float
    state: SpiderState
    obligations_satisfied: Tuple[str, ...]
    obligations_remaining: Tuple[str, ...]
    stop_reason: str


@dataclass(frozen=True)
class CampaignRemovalResult:
    status: CampaignRemovalStatus
    identity: CampaignIdentity
    start_state: SpiderState
    end_state: SpiderState
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_added_cost: Optional[int]
    obligations: Tuple[CampaignRemovalObligation, ...]
    obligations_satisfied: Tuple[CampaignRemovalObligation, ...]
    obligations_remaining: Tuple[CampaignRemovalObligation, ...]
    bands_before: Tuple[CampaignBand, ...]
    bands_after: Tuple[CampaignBand, ...]
    receiver_conditions: Tuple[CampaignReceiverCondition, ...]
    workspace_events: Tuple[str, ...]
    deals_applied: int
    foundation_count_before: int
    foundation_count_after: int
    foundation_suits_added: Tuple[str, ...]
    epoch_results: Tuple[CampaignEpochResult, ...]
    progress: Tuple[CampaignRemovalProgress, ...]
    nodes_expanded: int
    elapsed_seconds: float
    independent_replay_verified: bool
    replayed_cost: Optional[int]
    stop_reason: str
    immediate_post_deal_state: Optional[SpiderState]
    pre_deal_state: Optional[SpiderState]
    exact_row: Tuple[Card, ...]


@dataclass
class _SearchOutcome:
    found: bool
    actions: Tuple[Action, ...]
    cost: int
    state: SpiderState
    nodes: int
    elapsed: float
    resource_limited: bool
    stop_reason: str


def locate_campaign_bands(
    state: SpiderState,
    campaign_or_suit: FoundationCampaign | str,
) -> Tuple[CampaignBand, ...]:
    """Locate maximal same-suit descending face-up intervals."""
    suit = (
        campaign_or_suit.suit
        if isinstance(campaign_or_suit, FoundationCampaign)
        else campaign_or_suit.lower()
    )
    source_by_card: Dict[Tuple[int, int], List[str]] = {}
    if isinstance(campaign_or_suit, FoundationCampaign):
        for need in campaign_or_suit.rank_needs:
            for source in need.sources:
                if source.column is not None:
                    source_by_card.setdefault((source.column, need.rank), []).append(
                        source.source_key
                    )
    out: List[CampaignBand] = []
    for column_index, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            if up[i].suit != suit:
                i += 1
                continue
            j = i
            while (
                j + 1 < len(up)
                and up[j + 1].suit == suit
                and up[j].rank - 1 == up[j + 1].rank
            ):
                j += 1
            cards = tuple(up[i : j + 1])
            covering = tuple(up[j + 1 :])
            keys: List[str] = []
            for card in cards:
                keys.extend(source_by_card.get((column_index, card.rank), ()))
            out.append(
                CampaignBand(
                    suit=suit,
                    high_rank=cards[0].rank,
                    low_rank=cards[-1].rank,
                    column=column_index,
                    start_index=i,
                    end_index=j,
                    movable=not covering,
                    covered=bool(covering),
                    covering_cards=covering,
                    selected_source_keys=tuple(dict.fromkeys(keys)),
                    cards=cards,
                )
            )
            i = j + 1
    return tuple(
        sorted(
            out,
            key=lambda band: (
                -band.length,
                band.covered,
                -band.high_rank,
                band.column,
                band.start_index,
            ),
        )
    )


def campaign_band_recovery(band: CampaignBand) -> CampaignBandRecovery:
    groups = 0
    previous: Optional[Card] = None
    for card in band.covering_cards:
        if (
            previous is None
            or previous.rank - 1 != card.rank
            or previous.suit != card.suit
        ):
            groups += 1
        previous = card
    return CampaignBandRecovery(
        band=band,
        covering_groups=groups,
        covering_cards=band.covering_cards,
        destination_ranks=tuple(
            card.rank + 1 if card.rank < 13 else None
            for card in reversed(band.covering_cards)
        ),
        already_recovered=not band.covered,
    )


def bands_can_join(upper: CampaignBand, lower: CampaignBand) -> bool:
    """Whether moving ``lower`` onto ``upper`` makes one same-suit band."""
    return bool(
        upper.suit == lower.suit
        and upper.column != lower.column
        and upper.movable
        and lower.movable
        and upper.low_rank - 1 == lower.high_rank
    )


def campaign_interval_exists(
    state: SpiderState,
    suit: str,
    high_rank: int,
    low_rank: int,
    *,
    movable: bool = True,
    column: Optional[int] = None,
) -> bool:
    for band in locate_campaign_bands(state, suit):
        if column is not None and band.column != column:
            continue
        if movable and not band.movable:
            continue
        if band.high_rank >= high_rank and band.low_rank <= low_rank:
            return True
    return False


def _rank_intervals(ranks: Iterable[int]) -> Tuple[Tuple[int, int], ...]:
    ordered = sorted(set(ranks), reverse=True)
    if not ordered:
        return ()
    out: List[Tuple[int, int]] = []
    high = low = ordered[0]
    for rank in ordered[1:]:
        if low - 1 == rank:
            low = rank
        else:
            out.append((high, low))
            high = low = rank
    out.append((high, low))
    return tuple(out)


def _target_epoch_plan(campaign: FoundationCampaign) -> Optional[CampaignEpochPlan]:
    if campaign.target_removal_epoch is None:
        return None
    return next(
        (
            plan
            for plan in campaign.stock_plan
            if plan.epoch == campaign.target_removal_epoch
        ),
        None,
    )


def _predeal_intervals(campaign: FoundationCampaign) -> Tuple[Tuple[int, int], ...]:
    plan = _target_epoch_plan(campaign)
    arriving = {
        incoming.card.rank
        for incoming in (plan.incoming if plan else ())
        if incoming.selected_source and incoming.card.suit == campaign.suit
    }
    return tuple(
        interval
        for interval in _rank_intervals(
            rank for rank in campaign.required_ranks if rank not in arriving
        )
        if interval[0] - interval[1] + 1 >= 2
    )


def _foundations_of_suit(state: SpiderState, suit: str) -> int:
    return sum(
        1
        for sequence in state.foundations
        if len(sequence) == 13
        and sequence
        and all(card.suit == suit for card in sequence)
    )


def _foundation_removed(
    state: SpiderState, suit: str, before_suit_count: int
) -> bool:
    return _foundations_of_suit(state, suit) == before_suit_count + 1


def _simulate_deal(state: SpiderState) -> Optional[SpiderState]:
    if len(state.stock) < 10:
        return None
    dealt = state.clone()
    try:
        dealt.deal()
    except ValueError:
        return None
    return dealt


def _receiver_condition(
    state: SpiderState,
    campaign: FoundationCampaign,
    incoming_card: Card,
    incoming_column: int,
    target_intervals: Sequence[Tuple[int, int]],
) -> CampaignReceiverCondition:
    receiver_rank = incoming_card.rank + 1 if incoming_card.rank < 13 else None
    interval = next(
        (
            item
            for item in target_intervals
            if receiver_rank is not None and item[0] >= receiver_rank >= item[1]
        ),
        None,
    )
    if receiver_rank is None:
        return CampaignReceiverCondition(
            incoming_card,
            incoming_column,
            None,
            interval,
            True,
            False,
            (),
            "incoming King is the final campaign base",
        )
    direct = campaign_interval_exists(
        state,
        campaign.suit,
        receiver_rank,
        receiver_rank,
        movable=True,
        column=incoming_column,
    ) and state.columns[incoming_column].top() == Card(campaign.suit, receiver_rank)
    if direct:
        return CampaignReceiverCondition(
            incoming_card,
            incoming_column,
            receiver_rank,
            interval,
            True,
            False,
            (),
            "exact incoming column directly extends the selected band",
        )

    # Accept a concrete bounded equivalent: after the exact deal, clear at
    # most one overlay from a movable receiver band, then walk the incoming
    # campaign card onto that receiver.  Every proposed action is engine-legal.
    dealt = _simulate_deal(state)
    if dealt is not None:
        for band in locate_campaign_bands(state, campaign):
            if not (band.high_rank >= receiver_rank >= band.low_rank):
                continue
            band_column = band.column
            candidates: List[Tuple[Action, ...]] = [()]
            for src, dst, k in dealt.enumerate_moves():
                if src == band_column and k == 1:
                    candidates.append(((src, dst, k),))
            for prefix in candidates:
                probe = dealt.clone()
                try:
                    replay_actions(probe, list(prefix))
                except ValueError:
                    continue
                if (
                    probe.columns[incoming_column].top() == incoming_card
                    and probe.columns[band_column].top()
                    == Card(campaign.suit, receiver_rank)
                    and probe.can_move(incoming_column, band_column, 1)
                ):
                    return CampaignReceiverCondition(
                        incoming_card,
                        incoming_column,
                        receiver_rank,
                        interval,
                        False,
                        True,
                        prefix + ((incoming_column, band_column, 1),),
                        "exact deal admits a bounded overlay clear and walk-off",
                    )
    return CampaignReceiverCondition(
        incoming_card,
        incoming_column,
        receiver_rank,
        interval,
        False,
        False,
        (),
        "receiver not yet direct or bounded-walkoff ready",
    )


def campaign_receiver_conditions(
    state: SpiderState, campaign: FoundationCampaign
) -> Tuple[CampaignReceiverCondition, ...]:
    plan = _target_epoch_plan(campaign)
    if plan is None:
        return ()
    intervals = _predeal_intervals(campaign)
    return tuple(
        _receiver_condition(
            state, campaign, incoming.card, incoming.column, intervals
        )
        for incoming in plan.incoming
        if incoming.selected_source and incoming.card.suit == campaign.suit
    )


def campaign_removal_obligations(
    state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
) -> Tuple[CampaignRemovalObligation, ...]:
    """Derive structural work from current bands and the exact target row."""
    del cards
    plan = _target_epoch_plan(campaign)
    if plan is None:
        return ()
    out: List[CampaignRemovalObligation] = []
    bands = locate_campaign_bands(state, campaign)

    # Explicitly expose compatible current joins, including received stock
    # cards that now appear as tableau material.
    seen_join = set()
    for upper in bands:
        for lower in bands:
            if not bands_can_join(upper, lower):
                continue
            key = (upper.high_rank, lower.low_rank, upper.column, lower.column)
            if key in seen_join:
                continue
            seen_join.add(key)
            out.append(
                CampaignRemovalObligation(
                    obligation_id=(
                        f"join:{upper.high_rank}-{upper.low_rank}:"
                        f"{lower.high_rank}-{lower.low_rank}"
                    ),
                    kind=CampaignRemovalObligationKind.JOIN_RECEIVED_STOCK,
                    phase="post_previous_deal",
                    description=(
                        f"join movable {lower.label} onto {upper.label}"
                    ),
                    mandatory=False,
                    high_rank=upper.high_rank,
                    low_rank=lower.low_rank,
                    source_columns=(upper.column, lower.column),
                )
            )

    intervals = _predeal_intervals(campaign)
    for high, low in intervals:
        out.append(
            CampaignRemovalObligation(
                obligation_id=f"assemble:{high}-{low}:{campaign.suit}",
                kind=CampaignRemovalObligationKind.ASSEMBLE_SAME_SUIT_BAND,
                phase="pre_deal",
                description=f"assemble a movable {high}-{low}{campaign.suit} band",
                mandatory=True,
                high_rank=high,
                low_rank=low,
            )
        )

    for band in bands:
        if band.length < 2:
            continue
        out.append(
            CampaignRemovalObligation(
                obligation_id=(
                    f"preserve:{band.high_rank}-{band.low_rank}:c{band.column}"
                ),
                kind=CampaignRemovalObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
                phase="pre_deal",
                description=(
                    f"preserve or recover intact band {band.label}; "
                    f"overlay={tuple(str(card) for card in band.covering_cards)}"
                ),
                mandatory=True,
                high_rank=band.high_rank,
                low_rank=band.low_rank,
                column=band.column,
                notes=(
                    f"covering_groups={campaign_band_recovery(band).covering_groups}",
                ),
            )
        )

    for condition in campaign_receiver_conditions(state, campaign):
        out.append(
            CampaignRemovalObligation(
                obligation_id=(
                    f"position:{condition.incoming_card.suit}"
                    f"{condition.incoming_card.rank}:c{condition.incoming_column}"
                ),
                kind=CampaignRemovalObligationKind.POSITION_BAND_FOR_INCOMING,
                phase="pre_deal",
                description=condition.note,
                mandatory=condition.receiver_rank is not None,
                high_rank=condition.target_interval[0]
                if condition.target_interval
                else None,
                low_rank=condition.target_interval[1]
                if condition.target_interval
                else None,
                column=condition.incoming_column,
                incoming_card=condition.incoming_card,
                receiver_rank=condition.receiver_rank,
            )
        )

    out.extend(
        (
            CampaignRemovalObligation(
                obligation_id=f"workspace:d{plan.epoch}",
                kind=CampaignRemovalObligationKind.PREPARE_WORKSPACE,
                phase="pre_deal",
                description="spend, migrate, or recover space only for campaign work",
                mandatory=False,
            ),
            CampaignRemovalObligation(
                obligation_id=f"deal:d{plan.epoch}",
                kind=CampaignRemovalObligationKind.APPLY_DEAL,
                phase="deal",
                description=f"apply exact campaign target row at epoch {plan.epoch}",
                mandatory=True,
            ),
            CampaignRemovalObligation(
                obligation_id=f"connect:{campaign.suit}:12-1",
                kind=CampaignRemovalObligationKind.CONNECT_CAMPAIGN_BANDS,
                phase="post_deal",
                description="connect campaign material into one movable Q-A band",
                mandatory=True,
                high_rank=12,
                low_rank=1,
            ),
            CampaignRemovalObligation(
                obligation_id=f"remove:{campaign.suit}:{campaign.copy_index}",
                kind=CampaignRemovalObligationKind.REMOVE_FOUNDATION,
                phase="post_deal",
                description="place Q-A on the selected incoming King base",
                mandatory=True,
                high_rank=13,
                low_rank=1,
            ),
            CampaignRemovalObligation(
                obligation_id=f"verify:{campaign.suit}:{campaign.copy_index}",
                kind=CampaignRemovalObligationKind.VERIFY_FOUNDATION_REMOVAL,
                phase="verify",
                description="verify one automatic foundation of the fixed suit",
                mandatory=True,
            ),
        )
    )
    return tuple(out)


def removal_obligation_is_satisfied(
    state: SpiderState,
    campaign: FoundationCampaign,
    obligation: CampaignRemovalObligation,
    *,
    start_epoch: Optional[int] = None,
    foundation_suit_before: Optional[int] = None,
) -> bool:
    kind = obligation.kind
    if kind in (
        CampaignRemovalObligationKind.JOIN_RECEIVED_STOCK,
        CampaignRemovalObligationKind.ASSEMBLE_SAME_SUIT_BAND,
        CampaignRemovalObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
    ):
        return bool(
            obligation.high_rank is not None
            and obligation.low_rank is not None
            and campaign_interval_exists(
                state,
                campaign.suit,
                obligation.high_rank,
                obligation.low_rank,
                movable=True,
            )
        )
    if kind == CampaignRemovalObligationKind.POSITION_BAND_FOR_INCOMING:
        if obligation.incoming_card is None or obligation.column is None:
            return False
        condition = _receiver_condition(
            state,
            campaign,
            obligation.incoming_card,
            obligation.column,
            _predeal_intervals(campaign),
        )
        return condition.direct or condition.bounded_walkoff
    if kind == CampaignRemovalObligationKind.PREPARE_WORKSPACE:
        return bool(empty_columns(state)) or any(
            band.covered for band in locate_campaign_bands(state, campaign)
        )
    if kind == CampaignRemovalObligationKind.APPLY_DEAL:
        epoch0 = campaign.current_epoch if start_epoch is None else start_epoch
        return current_stock_epoch(state, 5) == epoch0 + 1
    if kind == CampaignRemovalObligationKind.CONNECT_CAMPAIGN_BANDS:
        return campaign_interval_exists(state, campaign.suit, 12, 1, movable=True)
    if kind in (
        CampaignRemovalObligationKind.REMOVE_FOUNDATION,
        CampaignRemovalObligationKind.VERIFY_FOUNDATION_REMOVAL,
    ):
        before = (
            _foundations_of_suit(state, campaign.suit)
            if foundation_suit_before is None
            else foundation_suit_before
        )
        return _foundation_removed(state, campaign.suit, before)
    return False


def _predeal_ready(state: SpiderState, campaign: FoundationCampaign) -> bool:
    intervals = _predeal_intervals(campaign)
    if not intervals or not all(
        campaign_interval_exists(
            state, campaign.suit, high, low, movable=True
        )
        for high, low in intervals
    ):
        return False
    return all(
        condition.direct or condition.bounded_walkoff
        for condition in campaign_receiver_conditions(state, campaign)
    )


def _band_complete(state: SpiderState, suit: str) -> bool:
    return campaign_interval_exists(state, suit, 12, 1, movable=True)


def _state_score(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    phase: str,
    foundation_suit_before: int,
) -> float:
    if _foundation_removed(state, campaign.suit, foundation_suit_before):
        return 1_000_000.0
    bands = locate_campaign_bands(state, campaign)
    score = 0.0
    for band in bands:
        score += band.length * band.length * (9.0 if band.movable else 3.0)
        score += band.length * 2.0
        if band.covered:
            recovery = campaign_band_recovery(band)
            score -= 8.0 * band.length
            score -= 2.0 * len(recovery.covering_cards)
            score -= 3.0 * recovery.covering_groups
    intervals = _predeal_intervals(campaign)
    assembled = []
    for high, low in intervals:
        ready = campaign_interval_exists(
            state, campaign.suit, high, low, movable=True
        )
        assembled.append(ready)
        if ready:
            score += 500.0 + 25.0 * (high - low + 1)
    if phase == "pre":
        # Full bounded-walkoff validation simulates the exact deal.  It is
        # only relevant after all structural bands exist; doing it for every
        # early beam state would add cost without changing their ordering.
        if assembled and all(assembled):
            conditions = campaign_receiver_conditions(state, campaign)
            score += 120.0 * sum(
                condition.direct or condition.bounded_walkoff
                for condition in conditions
            )
            score += 350.0 * sum(condition.direct for condition in conditions)
            if all(
                condition.direct or condition.bounded_walkoff
                for condition in conditions
            ):
                score += 5_000.0
    if _band_complete(state, campaign.suit):
        score += 50_000.0
    score += 3.0 * len(empty_columns(state))
    score -= 0.2 * sum(len(column.face_down) for column in state.columns)
    return score


def _search_moves(
    start: SpiderState,
    campaign: FoundationCampaign,
    *,
    phase: str,
    max_cost: int,
    max_nodes: int,
    time_limit_s: float,
    beam_width: int,
    foundation_suit_before: int,
) -> _SearchOutcome:
    started = time.perf_counter()
    target = (
        (lambda state: _predeal_ready(state, campaign))
        if phase == "pre"
        else (
            lambda state: _foundation_removed(
                state, campaign.suit, foundation_suit_before
            )
        )
    )
    if target(start):
        return _SearchOutcome(
            True, (), 0, start.clone(), 0, 0.0, False, "target already satisfied"
        )

    start_score = _state_score(
        start,
        campaign,
        phase=phase,
        foundation_suit_before=foundation_suit_before,
    )
    frontier: List[Tuple[SpiderState, Tuple[Action, ...], int, float]] = [
        (start.clone(), (), 0, start_score)
    ]
    best_cost_by_key = {canonical_state_key(start): 0}
    best_state = start.clone()
    best_path: Tuple[Action, ...] = ()
    best_cost = 0
    best_score = start_score
    nodes = 0
    max_depth = max_cost + 6

    for _depth in range(max_depth + 1):
        next_frontier: List[Tuple[SpiderState, Tuple[Action, ...], int, float]] = []
        for state, path, cost, _score in frontier:
            if time.perf_counter() - started >= time_limit_s:
                return _SearchOutcome(
                    False,
                    best_path,
                    best_cost,
                    best_state,
                    nodes,
                    time.perf_counter() - started,
                    True,
                    "time limit; bounded miss is not impossibility",
                )
            if nodes >= max_nodes:
                return _SearchOutcome(
                    False,
                    best_path,
                    best_cost,
                    best_state,
                    nodes,
                    time.perf_counter() - started,
                    True,
                    "node limit; bounded miss is not impossibility",
                )
            nodes += 1
            moves = state.enumerate_moves()
            for src, dst, k in moves:
                child = state.clone()
                try:
                    paid = child.move(src, dst, k, rules=MW_RULES)
                except ValueError:
                    continue
                new_cost = cost + paid
                if new_cost > max_cost:
                    continue
                key = canonical_state_key(child)
                previous = best_cost_by_key.get(key)
                if previous is not None and previous <= new_cost:
                    continue
                best_cost_by_key[key] = new_cost
                action: Action = (src, dst, k)
                new_path = path + (action,)
                score = _state_score(
                    child,
                    campaign,
                    phase=phase,
                    foundation_suit_before=foundation_suit_before,
                )
                if target(child):
                    return _SearchOutcome(
                        True,
                        new_path,
                        new_cost,
                        child,
                        nodes,
                        time.perf_counter() - started,
                        False,
                        f"bounded {phase} target found",
                    )
                if (score, -new_cost, -len(new_path)) > (
                    best_score,
                    -best_cost,
                    -len(best_path),
                ):
                    best_score = score
                    best_state = child.clone()
                    best_path = new_path
                    best_cost = new_cost
                next_frontier.append((child, new_path, new_cost, score))
        if not next_frontier:
            break
        next_frontier.sort(
            key=lambda item: (-item[3], item[2], len(item[1]), item[1])
        )
        frontier = next_frontier[:beam_width]
    return _SearchOutcome(
        False,
        best_path,
        best_cost,
        best_state,
        nodes,
        time.perf_counter() - started,
        False,
        "heuristic beam exhausted/truncated; miss is not impossibility",
    )


def _obligation_partition(
    state: SpiderState,
    campaign: FoundationCampaign,
    obligations: Sequence[CampaignRemovalObligation],
    *,
    start_epoch: int,
    foundation_suit_before: int,
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    if _foundation_removed(state, campaign.suit, foundation_suit_before):
        # Once the fixed campaign has been cashed out, its removed bands no
        # longer exist in tableau; removal is the terminal satisfaction of all
        # preparatory obligations.
        return tuple(obligation.obligation_id for obligation in obligations), ()
    satisfied: List[str] = []
    remaining: List[str] = []
    for obligation in obligations:
        ok = removal_obligation_is_satisfied(
            state,
            campaign,
            obligation,
            start_epoch=start_epoch,
            foundation_suit_before=foundation_suit_before,
        )
        (satisfied if ok else remaining).append(obligation.obligation_id)
    return tuple(satisfied), tuple(remaining)


def _workspace_events(start: SpiderState, actions: Sequence[Action]) -> Tuple[str, ...]:
    state = start.clone()
    out: List[str] = []
    for index, action in enumerate(actions, 1):
        before = tuple(empty_columns(state))
        replay_actions(state, [action])
        after = tuple(empty_columns(state))
        if before != after:
            if len(after) > len(before):
                kind = "create"
            elif len(after) < len(before):
                kind = "consume"
            else:
                kind = "relocate"
            out.append(f"action {index}: {kind} {before} -> {after}")
    return tuple(out)


def _action_roles(
    start: SpiderState,
    actions: Sequence[Action],
    suit: str,
) -> Tuple[str, ...]:
    state = start.clone()
    roles: List[str] = []
    for action in actions:
        if action == ("deal",):
            roles.append("deal")
            replay_actions(state, [action])
            continue
        before_foundations = len(state.foundations)
        before_bands = locate_campaign_bands(state, suit)
        before_empty = tuple(empty_columns(state))
        src, dst, _k = action
        moved = state.columns[src].face_up[-action[2] :]
        replay_actions(state, [action])
        after_bands = locate_campaign_bands(state, suit)
        if len(state.foundations) > before_foundations:
            role = "removal-trigger"
        elif moved and all(card.suit == suit for card in moved):
            role = "join"
        elif tuple(empty_columns(state)) != before_empty:
            role = "workspace"
        elif max((band.length for band in after_bands), default=0) > max(
            (band.length for band in before_bands), default=0
        ):
            role = "receiver-shape"
        elif src == dst:
            role = "auxiliary"
        else:
            role = "excavation" if state.columns[src].top() else "auxiliary"
        roles.append(role)
    return tuple(roles)


def realize_campaign_to_removal_epoch(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    *,
    max_added_cost: int = 20,
    max_nodes: int = 120_000,
    time_limit_s: float = 60.0,
    beam_width: int = 256,
) -> CampaignRemovalResult:
    """Attempt the fixed campaign's target-row foundation removal."""
    started = time.perf_counter()
    target_epoch = campaign.target_removal_epoch
    identity = CampaignIdentity(
        campaign.suit,
        campaign.copy_index,
        target_epoch if target_epoch is not None else -1,
    )
    start_epoch = current_stock_epoch(start_state, 5)
    invalid = bool(
        target_epoch is None
        or campaign.current_epoch != start_epoch
        or target_epoch != start_epoch + 1
        or len(start_state.stock) < 10
    )
    obligations = campaign_removal_obligations(start_state, campaign, cards)
    bands_before = locate_campaign_bands(start_state, campaign)
    foundation_before = len(start_state.foundations)
    foundation_suit_before = _foundations_of_suit(start_state, campaign.suit)
    exact_row = tuple(next_stock_row(start_state) or ())

    if invalid:
        return CampaignRemovalResult(
            CampaignRemovalStatus.INVALID_CAMPAIGN,
            identity,
            start_state.clone(),
            start_state.clone(),
            (),
            (),
            None,
            obligations,
            (),
            obligations,
            bands_before,
            bands_before,
            (),
            (),
            0,
            foundation_before,
            foundation_before,
            (),
            (),
            (),
            0,
            time.perf_counter() - started,
            False,
            None,
            "campaign must target exactly the next remaining stock epoch",
            None,
            None,
            exact_row,
        )

    progress: List[CampaignRemovalProgress] = []

    def add_progress(phase: str, state: SpiderState, actions_n: int, cost: int, note: str) -> None:
        satisfied, remaining = _obligation_partition(
            state,
            campaign,
            obligations,
            start_epoch=start_epoch,
            foundation_suit_before=foundation_suit_before,
        )
        progress.append(
            CampaignRemovalProgress(
                phase,
                actions_n,
                cost,
                current_stock_epoch(state, 5),
                locate_campaign_bands(state, campaign),
                satisfied,
                remaining,
                tuple(empty_columns(state)),
                len(state.foundations),
                note,
            )
        )

    add_progress("initial", start_state, 0, 0, "fixed identity and obligations frozen")
    reserve_deal = 1
    pre_budget = max(0, max_added_cost - reserve_deal)
    pre = _search_moves(
        start_state,
        campaign,
        phase="pre",
        max_cost=pre_budget,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        beam_width=beam_width,
        foundation_suit_before=foundation_suit_before,
    )
    nodes = pre.nodes
    actions: List[Action] = list(pre.actions)
    cost = pre.cost
    state = pre.state.clone()
    epoch_results: List[CampaignEpochResult] = []
    sat, rem = _obligation_partition(
        state,
        campaign,
        obligations,
        start_epoch=start_epoch,
        foundation_suit_before=foundation_suit_before,
    )
    epoch_results.append(
        CampaignEpochResult(
            "pre_deal",
            CampaignRemovalStatus.PARTIAL
            if not pre.found
            else CampaignRemovalStatus.BAND_COMPLETE,
            pre.actions,
            pre.cost,
            pre.nodes,
            pre.elapsed,
            state.clone(),
            sat,
            rem,
            pre.stop_reason,
        )
    )
    add_progress("pre_deal", state, len(actions), cost, pre.stop_reason)
    pre_deal_state = state.clone() if pre.found else None
    immediate_post_deal: Optional[SpiderState] = None
    resource_limited = pre.resource_limited
    stop_reason = pre.stop_reason

    if pre.found and cost + 1 <= max_added_cost:
        try:
            pre_campaign = analyze_foundation_campaign(
                state,
                cards=cards,
                suit=identity.suit,
                copy_index=identity.copy_index,
                target_epoch=identity.target_epoch,
            )
        except ValueError as exc:
            pre_campaign = None
            stop_reason = f"fixed campaign failed pre-deal reanalysis: {exc}"
        if pre_campaign is None:
            pre = _SearchOutcome(
                False,
                pre.actions,
                pre.cost,
                pre.state,
                pre.nodes,
                pre.elapsed,
                pre.resource_limited,
                stop_reason,
            )
    if pre.found and cost + 1 <= max_added_cost:
        before_deal = state.clone()
        dealt = state.clone()
        try:
            paid = dealt.deal()
        except ValueError as exc:
            stop_reason = f"engine rejected target deal: {exc}"
        else:
            row_verified = bool(
                paid == 1
                and len(exact_row) == 10
                and tuple(before_deal.stock[-10:]) == exact_row
                and len(dealt.stock) == len(before_deal.stock) - 10
            )
            if not row_verified:
                stop_reason = "exact target-row mapping verification failed"
            else:
                state = dealt
                immediate_post_deal = dealt.clone()
                actions.append(("deal",))
                cost += 1
                try:
                    post_campaign = analyze_foundation_campaign(
                        state,
                        cards=cards,
                        suit=identity.suit,
                        copy_index=identity.copy_index,
                        target_epoch=identity.target_epoch,
                    )
                except ValueError as exc:
                    post_campaign = None
                    stop_reason = f"fixed campaign failed post-deal reanalysis: {exc}"
                add_progress(
                    "immediate_post_deal",
                    state,
                    len(actions),
                    cost,
                    "exact target row applied by engine",
                )
                remaining_cost = max_added_cost - cost
                remaining_nodes = max(1, max_nodes - nodes)
                remaining_time = max(
                    0.01, time_limit_s - (time.perf_counter() - started)
                )
                if post_campaign is None:
                    post = _SearchOutcome(
                        False,
                        (),
                        0,
                        state.clone(),
                        0,
                        0.0,
                        False,
                        stop_reason,
                    )
                else:
                    post = _search_moves(
                        state,
                        campaign,
                        phase="post",
                        max_cost=remaining_cost,
                        max_nodes=remaining_nodes,
                        time_limit_s=remaining_time,
                        beam_width=beam_width,
                        foundation_suit_before=foundation_suit_before,
                    )
                nodes += post.nodes
                actions.extend(post.actions)
                cost += post.cost
                state = post.state.clone()
                resource_limited = resource_limited or post.resource_limited
                stop_reason = post.stop_reason
                sat, rem = _obligation_partition(
                    state,
                    campaign,
                    obligations,
                    start_epoch=start_epoch,
                    foundation_suit_before=foundation_suit_before,
                )
                if _foundation_removed(
                    state, campaign.suit, foundation_suit_before
                ):
                    post_status = CampaignRemovalStatus.FOUNDATION_REMOVED
                elif _band_complete(state, campaign.suit):
                    post_status = CampaignRemovalStatus.BAND_COMPLETE
                else:
                    post_status = CampaignRemovalStatus.PARTIAL
                epoch_results.append(
                    CampaignEpochResult(
                        "post_deal",
                        post_status,
                        post.actions,
                        post.cost,
                        post.nodes,
                        post.elapsed,
                        state.clone(),
                        sat,
                        rem,
                        post.stop_reason,
                    )
                )
                add_progress(
                    "post_deal",
                    state,
                    len(actions),
                    cost,
                    post.stop_reason,
                )

    replay_state = start_state.clone()
    replay_cost: Optional[int]
    replay_ok = False
    try:
        replay_cost = replay_actions(replay_state, list(actions))
        replay_ok = bool(
            replay_cost == cost
            and states_structurally_equal(replay_state, state)
            and sum(1 for action in actions if action == ("deal",)) <= 1
        )
    except ValueError:
        replay_cost = None

    removed = _foundation_removed(state, campaign.suit, foundation_suit_before)
    exact_removed = bool(
        removed
        and len(state.foundations) == foundation_before + 1
        and len(state.stock) == len(start_state.stock) - 10
        and sum(1 for action in actions if action == ("deal",)) == 1
    )
    if exact_removed and replay_ok:
        status = CampaignRemovalStatus.FOUNDATION_REMOVED
        stop_reason = "fixed campaign foundation removed and independently replayed"
    elif _band_complete(state, campaign.suit) and replay_ok:
        status = CampaignRemovalStatus.BAND_COMPLETE
    elif resource_limited:
        status = CampaignRemovalStatus.RESOURCE_LIMIT
    elif actions:
        status = CampaignRemovalStatus.PARTIAL
    else:
        status = CampaignRemovalStatus.NOT_FOUND_WITHIN_BOUND

    satisfied_ids, remaining_ids = _obligation_partition(
        state,
        campaign,
        obligations,
        start_epoch=start_epoch,
        foundation_suit_before=foundation_suit_before,
    )
    satisfied_set = set(satisfied_ids)
    foundation_added = tuple(
        sequence[0].suit
        for sequence in state.foundations[foundation_before:]
        if sequence
    )
    if exact_removed and foundation_added == (campaign.suit,):
        # Removal is the terminal satisfaction of every preparatory campaign
        # obligation, even though its bands are no longer present in tableau.
        satisfied_set = {obligation.obligation_id for obligation in obligations}
    return CampaignRemovalResult(
        status=status,
        identity=identity,
        start_state=start_state.clone(),
        end_state=state.clone(),
        actions=tuple(actions),
        action_roles=_action_roles(start_state, actions, campaign.suit),
        corrected_added_cost=cost if replay_ok else None,
        obligations=obligations,
        obligations_satisfied=tuple(
            obligation
            for obligation in obligations
            if obligation.obligation_id in satisfied_set
        ),
        obligations_remaining=tuple(
            obligation
            for obligation in obligations
            if obligation.obligation_id not in satisfied_set
        ),
        bands_before=bands_before,
        bands_after=locate_campaign_bands(state, campaign),
        receiver_conditions=campaign_receiver_conditions(
            pre_deal_state if pre_deal_state is not None else state, campaign
        ),
        workspace_events=_workspace_events(start_state, actions),
        deals_applied=sum(1 for action in actions if action == ("deal",)),
        foundation_count_before=foundation_before,
        foundation_count_after=len(state.foundations),
        foundation_suits_added=foundation_added,
        epoch_results=tuple(epoch_results),
        progress=tuple(progress),
        nodes_expanded=nodes,
        elapsed_seconds=time.perf_counter() - started,
        independent_replay_verified=replay_ok,
        replayed_cost=replay_cost,
        stop_reason=stop_reason,
        immediate_post_deal_state=immediate_post_deal,
        pre_deal_state=pre_deal_state,
        exact_row=exact_row,
    )


def format_removal_obligation(obligation: CampaignRemovalObligation) -> str:
    gate = "MUST" if obligation.mandatory else "DESIRED"
    return (
        f"{gate:<7} {obligation.phase:<18} {obligation.kind.value:<28} "
        f"{obligation.description}"
    )
