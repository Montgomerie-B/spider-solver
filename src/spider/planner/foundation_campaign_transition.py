"""Bounded transition for the next outstanding foundation campaign.

This module is a small orchestration layer over the existing one-epoch and
target-row realizers.  It fixes one campaign identity, derives exactly one of
three epoch-relative modes, and stops after a foundation removal or one stock
row.  Campaign estimates order work only; success is always an engine-checked
structural predicate followed by independent replay.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    analyze_foundation_campaign,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignIdentity,
    CampaignObligation,
    CampaignObligationKind,
    CampaignRealizationStatus,
    campaign_obligations_for_next_epoch,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignBand,
    CampaignRemovalObligation,
    CampaignRemovalObligationKind,
    CampaignRemovalStatus,
    CampaignTableauTarget,
    campaign_interval_exists,
    campaign_removal_obligations,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
    search_campaign_tableau,
)
from spider.planner.backward_strategy import (
    analyze_buried_cards,
    analyze_space_liquidity,
)
from spider.planner.foundation_feasibility import analyze_foundation_feasibility
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.space_lifecycle import empty_columns
from spider.planner.stock_reception import next_stock_row
from spider.planner.workspace_obstruction import open_column_facts
from spider.state_identity import states_structurally_equal


class CampaignTransitionMode(str, Enum):
    REMOVE_BEFORE_NEXT_DEAL = "remove_before_next_deal"
    REMOVE_AT_NEXT_DEAL = "remove_at_next_deal"
    ADVANCE_ONE_EPOCH = "advance_one_epoch"


class CampaignTransitionStatus(str, Enum):
    FOUNDATION_REMOVED = "foundation_removed"
    NEXT_EPOCH_REACHED = "next_epoch_reached"
    CAMPAIGN_ADVANCED = "campaign_advanced"
    PARTIAL = "partial"
    NOT_FOUND_WITHIN_BOUND = "not_found_within_bound"
    RESOURCE_LIMIT = "resource_limit"
    INVALID_CAMPAIGN = "invalid_campaign"


class CampaignTransitionPhase(str, Enum):
    FROZEN = "frozen"
    TABLEAU_ONLY = "tableau_only"
    PRE_DEAL = "pre_deal"
    DEAL = "deal"
    POST_DEAL = "post_deal"
    REANALYZE = "reanalyze"
    COMPLETE = "complete"


class CampaignTransitionObligationKind(str, Enum):
    EXPOSE_SELECTED_SOURCE = "expose_selected_source"
    RECOVER_CAMPAIGN_BAND = "recover_campaign_band"
    JOIN_CAMPAIGN_BANDS = "join_campaign_bands"
    PRESERVE_CAMPAIGN_FRAGMENT = "preserve_campaign_fragment"
    SHAPE_RECEIVER = "shape_receiver"
    PREPARE_WORKSPACE = "prepare_workspace"
    APPLY_EXACT_ROW = "apply_exact_row"
    VERIFY_FIXED_CAMPAIGN = "verify_fixed_campaign"
    CONNECT_Q_TO_A = "connect_q_to_a"
    REMOVE_FOUNDATION = "remove_foundation"
    VERIFY_FOUNDATION_REMOVAL = "verify_foundation_removal"


@dataclass(frozen=True)
class CampaignTransitionObligation:
    obligation_id: str
    kind: CampaignTransitionObligationKind
    phase: CampaignTransitionPhase
    description: str
    mandatory: bool
    deadline_epoch: int
    rank: Optional[int] = None
    source_keys: Tuple[str, ...] = ()
    high_rank: Optional[int] = None
    low_rank: Optional[int] = None
    column: Optional[int] = None
    incoming_card: Optional[Card] = None
    receiver_rank: Optional[int] = None
    notes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignTransitionProgress:
    phase: CampaignTransitionPhase
    action_count: int
    corrected_added_cost: int
    epoch: int
    must_source_keys: Tuple[str, ...]
    longest_campaign_band: int
    obligations_satisfied: Tuple[str, ...]
    obligations_remaining: Tuple[str, ...]
    empty_columns: Tuple[int, ...]
    foundation_count: int
    note: str


@dataclass(frozen=True)
class CampaignTransitionResult:
    status: CampaignTransitionStatus
    identity: CampaignIdentity
    mode: CampaignTransitionMode
    start_epoch: int
    target_epoch: int
    actions: Tuple[Action, ...]
    action_roles: Tuple[str, ...]
    corrected_added_cost: Optional[int]
    resulting_state: SpiderState
    obligations: Tuple[CampaignTransitionObligation, ...]
    obligations_satisfied: Tuple[CampaignTransitionObligation, ...]
    obligations_remaining: Tuple[CampaignTransitionObligation, ...]
    bands_before: Tuple[CampaignBand, ...]
    bands_after: Tuple[CampaignBand, ...]
    must_sources_before: Tuple[str, ...]
    must_sources_after: Tuple[str, ...]
    workspace_events: Tuple[str, ...]
    exact_row: Tuple[Card, ...]
    deals_applied: int
    foundation_count_before: int
    foundation_count_after: int
    foundation_suits_before: Tuple[str, ...]
    foundation_suits_after: Tuple[str, ...]
    foundation_suits_added: Tuple[str, ...]
    portfolio_before: FoundationCampaignPortfolio
    portfolio_after: FoundationCampaignPortfolio
    campaign_before: FoundationCampaign
    campaign_after: Optional[FoundationCampaign]
    progress: Tuple[CampaignTransitionProgress, ...]
    nodes_expanded: int
    elapsed_seconds: float
    independent_replay_verified: bool
    replayed_cost: Optional[int]
    pre_deal_state: Optional[SpiderState]
    immediate_post_deal_state: Optional[SpiderState]
    stop_reason: str


@dataclass(frozen=True)
class SuitBandAudit:
    suit: str
    bands: Tuple[CampaignBand, ...]
    longest_run: int
    total_run_mass: int


@dataclass(frozen=True)
class ResidualStateAudit:
    face_down_cards: int
    stock_size: int
    foundation_count: int
    foundation_suits: Tuple[str, ...]
    empty_columns: Tuple[int, ...]
    fully_open_columns: int
    fully_open_nonking_columns: int
    cheapest_workspace_cost: Optional[int]
    workspace_status: str
    suit_bands: Tuple[SuitBandAudit, ...]
    longest_same_suit_run: int
    total_same_suit_run_mass: int
    mixed_suit_boundaries: Tuple[Tuple[int, Card, Card], ...]
    legal_move_count: int
    campaign_usable_source_keys: Tuple[str, ...]
    campaign_buried_source_keys: Tuple[str, ...]


def audit_residual_state(
    state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
) -> ResidualStateAudit:
    """Return cheap structural facts for a post-foundation state."""
    foundation = analyze_foundation_feasibility(cards, state)
    buried = analyze_buried_cards(state, cards=cards, foundation=foundation)
    liquidity = analyze_space_liquidity(state, buried)
    fully_open, fully_open_nonking, _min_fd = open_column_facts(state)
    suit_bands = tuple(
        SuitBandAudit(
            suit,
            locate_campaign_bands(state, suit),
            max(
                (band.length for band in locate_campaign_bands(state, suit)),
                default=0,
            ),
            sum(band.length for band in locate_campaign_bands(state, suit)),
        )
        for suit in "cdhs"
    )
    mixed: List[Tuple[int, Card, Card]] = []
    for column_index, column in enumerate(state.columns):
        for upper, lower in zip(column.face_up, column.face_up[1:]):
            if upper.rank - 1 == lower.rank and upper.suit != lower.suit:
                mixed.append((column_index, upper, lower))
    usable = tuple(
        need.chosen.source_key
        for need in campaign.rank_needs
        if need.chosen is not None
        and _rank_usable(state, campaign.suit, need.rank)
    )
    buried_keys = tuple(
        need.chosen.source_key
        for need in campaign.rank_needs
        if need.chosen is not None
        and need.chosen.is_tableau_work
        and not _rank_usable(state, campaign.suit, need.rank)
    )
    return ResidualStateAudit(
        face_down_cards=sum(len(column.face_down) for column in state.columns),
        stock_size=len(state.stock),
        foundation_count=len(state.foundations),
        foundation_suits=_foundation_suits(state),
        empty_columns=tuple(empty_columns(state)),
        fully_open_columns=fully_open,
        fully_open_nonking_columns=fully_open_nonking,
        cheapest_workspace_cost=liquidity.cheapest_create,
        workspace_status=liquidity.create_status,
        suit_bands=suit_bands,
        longest_same_suit_run=max(
            (item.longest_run for item in suit_bands), default=0
        ),
        total_same_suit_run_mass=sum(item.total_run_mass for item in suit_bands),
        mixed_suit_boundaries=tuple(mixed),
        legal_move_count=len(state.enumerate_moves()),
        campaign_usable_source_keys=usable,
        campaign_buried_source_keys=buried_keys,
    )


def derive_transition_mode(
    current_epoch: int, target_epoch: int
) -> CampaignTransitionMode:
    """Return the only permitted bounded transition for these epochs."""
    if target_epoch <= current_epoch:
        return CampaignTransitionMode.REMOVE_BEFORE_NEXT_DEAL
    if target_epoch == current_epoch + 1:
        return CampaignTransitionMode.REMOVE_AT_NEXT_DEAL
    return CampaignTransitionMode.ADVANCE_ONE_EPOCH


def _foundation_suits(state: SpiderState) -> Tuple[str, ...]:
    return tuple(sequence[0].suit for sequence in state.foundations if sequence)


def _foundation_count_for_suit(state: SpiderState, suit: str) -> int:
    return sum(
        1
        for sequence in state.foundations
        if len(sequence) == 13
        and sequence
        and all(card.suit == suit for card in sequence)
    )


def _must_keys(campaign: Optional[FoundationCampaign]) -> Tuple[str, ...]:
    if campaign is None:
        return ()
    return tuple(source.source_key for source in campaign.tableau_critical_cards)


def _rank_usable(state: SpiderState, suit: str, rank: int) -> bool:
    return any(
        band.movable and band.high_rank >= rank >= band.low_rank
        for band in locate_campaign_bands(state, suit)
    )


def _longest_band(state: SpiderState, suit: str) -> int:
    return max((band.length for band in locate_campaign_bands(state, suit)), default=0)


def _fixed_reanalysis(
    state: SpiderState,
    identity: CampaignIdentity,
    cards: Sequence[Card],
    *,
    max_source_combinations: Optional[int] = None,
) -> Optional[FoundationCampaign]:
    if _foundation_count_for_suit(state, identity.suit) >= identity.copy_index:
        return None
    try:
        return analyze_foundation_campaign(
            state,
            cards=cards,
            suit=identity.suit,
            copy_index=identity.copy_index,
            target_epoch=identity.target_epoch,
            max_source_combinations=max_source_combinations,
        )
    except ValueError:
        return None


def _convert_epoch_obligation(
    obligation: CampaignObligation,
) -> CampaignTransitionObligation:
    kinds = {
        CampaignObligationKind.EXCAVATE_PREFIX:
            CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE,
        CampaignObligationKind.MAKE_RANK_USABLE:
            CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE,
        CampaignObligationKind.PRESERVE_FRAGMENT:
            CampaignTransitionObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
        CampaignObligationKind.SHAPE_RECEIVER:
            CampaignTransitionObligationKind.SHAPE_RECEIVER,
        CampaignObligationKind.PREPARE_WORKSPACE:
            CampaignTransitionObligationKind.PREPARE_WORKSPACE,
        CampaignObligationKind.APPLY_DEAL:
            CampaignTransitionObligationKind.APPLY_EXACT_ROW,
        CampaignObligationKind.VERIFY_POST_DEAL:
            CampaignTransitionObligationKind.VERIFY_FIXED_CAMPAIGN,
    }
    if obligation.kind in (
        CampaignObligationKind.APPLY_DEAL,
        CampaignObligationKind.VERIFY_POST_DEAL,
    ):
        phase = CampaignTransitionPhase.DEAL
    elif obligation.mandatory_before_deal:
        phase = CampaignTransitionPhase.PRE_DEAL
    else:
        phase = CampaignTransitionPhase.REANALYZE
    fragment = obligation.fragment
    return CampaignTransitionObligation(
        obligation_id=obligation.obligation_id,
        kind=kinds[obligation.kind],
        phase=phase,
        description=obligation.description,
        mandatory=obligation.mandatory_before_deal
        or obligation.kind
        in (CampaignObligationKind.APPLY_DEAL, CampaignObligationKind.VERIFY_POST_DEAL),
        deadline_epoch=obligation.deadline_epoch,
        rank=obligation.rank,
        source_keys=obligation.source_keys,
        high_rank=fragment[0].rank if fragment else None,
        low_rank=fragment[-1].rank if fragment else None,
        column=obligation.receiver_column,
        incoming_card=obligation.incoming_card,
        receiver_rank=obligation.receiver_rank,
        notes=obligation.notes,
    )


def _convert_removal_obligation(
    obligation: CampaignRemovalObligation,
    deadline_epoch: int,
) -> CampaignTransitionObligation:
    kinds = {
        CampaignRemovalObligationKind.JOIN_RECEIVED_STOCK:
            CampaignTransitionObligationKind.JOIN_CAMPAIGN_BANDS,
        CampaignRemovalObligationKind.ASSEMBLE_SAME_SUIT_BAND:
            CampaignTransitionObligationKind.RECOVER_CAMPAIGN_BAND,
        CampaignRemovalObligationKind.POSITION_BAND_FOR_INCOMING:
            CampaignTransitionObligationKind.SHAPE_RECEIVER,
        CampaignRemovalObligationKind.PRESERVE_CAMPAIGN_FRAGMENT:
            CampaignTransitionObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
        CampaignRemovalObligationKind.PREPARE_WORKSPACE:
            CampaignTransitionObligationKind.PREPARE_WORKSPACE,
        CampaignRemovalObligationKind.APPLY_DEAL:
            CampaignTransitionObligationKind.APPLY_EXACT_ROW,
        CampaignRemovalObligationKind.CONNECT_CAMPAIGN_BANDS:
            CampaignTransitionObligationKind.CONNECT_Q_TO_A,
        CampaignRemovalObligationKind.REMOVE_FOUNDATION:
            CampaignTransitionObligationKind.REMOVE_FOUNDATION,
        CampaignRemovalObligationKind.VERIFY_FOUNDATION_REMOVAL:
            CampaignTransitionObligationKind.VERIFY_FOUNDATION_REMOVAL,
    }
    phases = {
        "pre_deal": CampaignTransitionPhase.PRE_DEAL,
        "deal": CampaignTransitionPhase.DEAL,
        "post_deal": CampaignTransitionPhase.POST_DEAL,
        "verify": CampaignTransitionPhase.COMPLETE,
    }
    return CampaignTransitionObligation(
        obligation_id=obligation.obligation_id,
        kind=kinds[obligation.kind],
        phase=phases.get(obligation.phase, CampaignTransitionPhase.PRE_DEAL),
        description=obligation.description,
        mandatory=obligation.mandatory,
        deadline_epoch=deadline_epoch,
        high_rank=obligation.high_rank,
        low_rank=obligation.low_rank,
        column=obligation.column,
        incoming_card=obligation.incoming_card,
        receiver_rank=obligation.receiver_rank,
        notes=obligation.notes,
    )


def campaign_transition_obligations(
    state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
) -> Tuple[CampaignTransitionObligation, ...]:
    """Generate structural work for exactly the derived transition mode."""
    target = campaign.target_removal_epoch
    if target is None:
        return ()
    mode = derive_transition_mode(current_stock_epoch(state, 5), target)
    if mode == CampaignTransitionMode.ADVANCE_ONE_EPOCH:
        return tuple(
            _convert_epoch_obligation(obligation)
            for obligation in campaign_obligations_for_next_epoch(state, campaign, cards)
        )
    if mode == CampaignTransitionMode.REMOVE_AT_NEXT_DEAL:
        return tuple(
            _convert_removal_obligation(obligation, target)
            for obligation in campaign_removal_obligations(state, campaign, cards)
        )

    out: List[CampaignTransitionObligation] = []
    for need in campaign.rank_needs:
        chosen = need.chosen
        if not need.must_excavate or chosen is None:
            continue
        out.append(
            CampaignTransitionObligation(
                obligation_id=f"expose:r{need.rank}:{campaign.suit}",
                kind=CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE,
                phase=CampaignTransitionPhase.TABLEAU_ONLY,
                description=(
                    f"make an interchangeable rank {need.rank} source usable "
                    "without dealing"
                ),
                mandatory=True,
                deadline_epoch=target,
                rank=need.rank,
                source_keys=tuple(source.source_key for source in need.sources),
            )
        )
    for band in locate_campaign_bands(state, campaign):
        if band.length < 2:
            continue
        out.append(
            CampaignTransitionObligation(
                obligation_id=(
                    f"preserve:{band.high_rank}-{band.low_rank}:c{band.column}"
                ),
                kind=CampaignTransitionObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
                phase=CampaignTransitionPhase.TABLEAU_ONLY,
                description=f"preserve or join the existing {band.label} fragment",
                mandatory=True,
                deadline_epoch=target,
                high_rank=band.high_rank,
                low_rank=band.low_rank,
                column=band.column,
            )
        )
    if campaign.space_plan.policy.value != "none":
        out.append(
            CampaignTransitionObligation(
                obligation_id=f"workspace:d{target}",
                kind=CampaignTransitionObligationKind.PREPARE_WORKSPACE,
                phase=CampaignTransitionPhase.TABLEAU_ONLY,
                description=campaign.space_plan.enabled_action,
                mandatory=False,
                deadline_epoch=target,
                notes=campaign.space_plan.reasons,
            )
        )
    out.extend(
        (
            CampaignTransitionObligation(
                obligation_id=f"connect:{campaign.suit}:12-1",
                kind=CampaignTransitionObligationKind.CONNECT_Q_TO_A,
                phase=CampaignTransitionPhase.TABLEAU_ONLY,
                description="connect campaign material into one movable Q-A band",
                mandatory=True,
                deadline_epoch=target,
                high_rank=12,
                low_rank=1,
            ),
            CampaignTransitionObligation(
                obligation_id=f"remove:{campaign.suit}:{campaign.copy_index}",
                kind=CampaignTransitionObligationKind.REMOVE_FOUNDATION,
                phase=CampaignTransitionPhase.TABLEAU_ONLY,
                description="assemble K-A and trigger the selected foundation removal",
                mandatory=True,
                deadline_epoch=target,
                high_rank=13,
                low_rank=1,
            ),
            CampaignTransitionObligation(
                obligation_id=f"verify:{campaign.suit}:{campaign.copy_index}",
                kind=CampaignTransitionObligationKind.VERIFY_FOUNDATION_REMOVAL,
                phase=CampaignTransitionPhase.COMPLETE,
                description="verify exactly one automatic foundation of the fixed suit",
                mandatory=True,
                deadline_epoch=target,
            ),
        )
    )
    return tuple(out)


def transition_obligation_is_satisfied(
    state: SpiderState,
    campaign: FoundationCampaign,
    obligation: CampaignTransitionObligation,
    *,
    start_epoch: int,
    foundation_suit_before: int,
    accomplished: Sequence[str] = (),
) -> bool:
    """Evaluate one transition obligation using only structural facts."""
    if obligation.obligation_id in accomplished:
        return True
    removed = _foundation_count_for_suit(state, campaign.suit) > foundation_suit_before
    if removed:
        return True
    kind = obligation.kind
    if kind == CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE:
        return obligation.rank is not None and _rank_usable(
            state, campaign.suit, obligation.rank
        )
    if kind in (
        CampaignTransitionObligationKind.RECOVER_CAMPAIGN_BAND,
        CampaignTransitionObligationKind.JOIN_CAMPAIGN_BANDS,
        CampaignTransitionObligationKind.PRESERVE_CAMPAIGN_FRAGMENT,
        CampaignTransitionObligationKind.CONNECT_Q_TO_A,
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
    if kind == CampaignTransitionObligationKind.SHAPE_RECEIVER:
        if obligation.incoming_card is None or obligation.receiver_rank is None:
            return True
        if obligation.column is not None:
            top = state.columns[obligation.column].top()
            if (
                top is not None
                and top.suit == obligation.incoming_card.suit
                and top.rank == obligation.receiver_rank
            ):
                return True
        return _rank_usable(state, campaign.suit, obligation.receiver_rank)
    if kind == CampaignTransitionObligationKind.PREPARE_WORKSPACE:
        return bool(empty_columns(state)) or campaign.space_plan.estimated_regain_cost is not None
    if kind in (
        CampaignTransitionObligationKind.APPLY_EXACT_ROW,
        CampaignTransitionObligationKind.VERIFY_FIXED_CAMPAIGN,
    ):
        return current_stock_epoch(state, 5) >= obligation.deadline_epoch
    if kind in (
        CampaignTransitionObligationKind.REMOVE_FOUNDATION,
        CampaignTransitionObligationKind.VERIFY_FOUNDATION_REMOVAL,
    ):
        return removed
    return False


def _workspace_and_roles(
    start: SpiderState, actions: Sequence[Action], suit: str
) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    state = start.clone()
    events: List[str] = []
    roles: List[str] = []
    for index, action in enumerate(actions, 1):
        before_empty = tuple(empty_columns(state))
        before_foundations = len(state.foundations)
        if action == ("deal",):
            role = "deal"
        else:
            src, _dst, count = action
            moved = tuple(state.columns[src].face_up[-count:])
            role = "campaign" if moved and all(card.suit == suit for card in moved) else "auxiliary"
        replay_actions(state, [action])
        after_empty = tuple(empty_columns(state))
        if len(state.foundations) > before_foundations:
            role = "removal-trigger"
        elif before_empty != after_empty and action != ("deal",):
            role = "workspace"
        roles.append(role)
        if before_empty != after_empty:
            if len(after_empty) > len(before_empty):
                effect = "create"
            elif len(after_empty) < len(before_empty):
                effect = "consume"
            else:
                effect = "relocate"
            events.append(f"action {index}: {effect} {before_empty} -> {after_empty}")
    return tuple(events), tuple(roles)


def _invalid_result(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    mode: CampaignTransitionMode,
    start_epoch: int,
    target_epoch: int,
    started: float,
    reason: str,
) -> CampaignTransitionResult:
    portfolio = analyze_foundation_campaigns(start_state, cards=cards)
    identity = CampaignIdentity(campaign.suit, campaign.copy_index, target_epoch)
    bands = locate_campaign_bands(start_state, campaign)
    suits = _foundation_suits(start_state)
    return CampaignTransitionResult(
        CampaignTransitionStatus.INVALID_CAMPAIGN,
        identity,
        mode,
        start_epoch,
        target_epoch,
        (),
        (),
        None,
        start_state.clone(),
        (),
        (),
        (),
        bands,
        bands,
        _must_keys(campaign),
        _must_keys(campaign),
        (),
        (),
        0,
        len(start_state.foundations),
        len(start_state.foundations),
        suits,
        suits,
        (),
        portfolio,
        portfolio,
        campaign,
        campaign,
        (),
        0,
        time.perf_counter() - started,
        False,
        None,
        None,
        None,
        reason,
    )


def realize_residual_campaign_transition(
    start_state: SpiderState,
    campaign: FoundationCampaign,
    cards: Sequence[Card],
    *,
    max_added_cost: int = 24,
    max_nodes: int = 120_000,
    time_limit_s: float = 60.0,
    beam_width: int = 512,
    max_source_combinations: Optional[int] = None,
) -> CampaignTransitionResult:
    """Realize one fixed campaign transition, with at most one stock deal."""
    started = time.perf_counter()
    start_epoch = current_stock_epoch(start_state, 5)
    target_epoch = (
        campaign.target_removal_epoch
        if campaign.target_removal_epoch is not None
        else -1
    )
    mode = derive_transition_mode(start_epoch, target_epoch)
    if (
        target_epoch < 0
        or campaign.current_epoch != start_epoch
        or max_added_cost < 0
        or max_nodes <= 0
        or time_limit_s <= 0
    ):
        return _invalid_result(
            start_state,
            campaign,
            cards,
            mode,
            start_epoch,
            target_epoch,
            started,
            "campaign identity/epoch or resource bounds are invalid",
        )

    portfolio_before = analyze_foundation_campaigns(
        start_state,
        cards=cards,
        max_source_combinations=max_source_combinations,
    )
    matching = next(
        (
            item
            for item in portfolio_before.campaigns
            if item.suit == campaign.suit
            and item.copy_index == campaign.copy_index
            and item.target_removal_epoch == target_epoch
        ),
        None,
    )
    if matching is None:
        return _invalid_result(
            start_state,
            campaign,
            cards,
            mode,
            start_epoch,
            target_epoch,
            started,
            "campaign is not the state's next outstanding fixed ordinal/schedule",
        )

    identity = CampaignIdentity(campaign.suit, campaign.copy_index, target_epoch)
    obligations = campaign_transition_obligations(start_state, campaign, cards)
    bands_before = locate_campaign_bands(start_state, campaign)
    must_before = _must_keys(campaign)
    foundation_before = len(start_state.foundations)
    suit_foundations_before = _foundation_count_for_suit(start_state, campaign.suit)
    suits_before = _foundation_suits(start_state)
    exact_row = tuple(next_stock_row(start_state) or ()) if mode != CampaignTransitionMode.REMOVE_BEFORE_NEXT_DEAL else ()
    actions: Tuple[Action, ...] = ()
    roles: Tuple[str, ...] = ()
    workspace_events: Tuple[str, ...] = ()
    nodes = 0
    state = start_state.clone()
    backend_satisfied: Tuple[str, ...] = ()
    resource_limited = False
    stop_reason = ""
    pre_deal_state: Optional[SpiderState] = None
    immediate_post_deal_state: Optional[SpiderState] = None

    if mode == CampaignTransitionMode.REMOVE_BEFORE_NEXT_DEAL:
        outcome = search_campaign_tableau(
            start_state,
            campaign,
            target=CampaignTableauTarget.REMOVE_FOUNDATION,
            max_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            beam_width=beam_width,
            foundation_suit_before=suit_foundations_before,
        )
        actions = outcome.actions
        state = outcome.state.clone()
        nodes = outcome.nodes
        resource_limited = outcome.resource_limited
        stop_reason = outcome.stop_reason
        workspace_events, roles = _workspace_and_roles(start_state, actions, campaign.suit)
    elif mode == CampaignTransitionMode.REMOVE_AT_NEXT_DEAL:
        removal = realize_campaign_to_removal_epoch(
            start_state,
            campaign,
            cards,
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
            beam_width=beam_width,
        )
        actions = removal.actions
        roles = removal.action_roles
        state = removal.end_state.clone()
        nodes = removal.nodes_expanded
        resource_limited = removal.status == CampaignRemovalStatus.RESOURCE_LIMIT
        stop_reason = removal.stop_reason
        workspace_events = removal.workspace_events
        backend_satisfied = tuple(
            obligation.obligation_id for obligation in removal.obligations_satisfied
        )
        pre_deal_state = removal.pre_deal_state
        immediate_post_deal_state = removal.immediate_post_deal_state
    else:
        epoch = realize_campaign_to_next_epoch(
            start_state,
            campaign,
            cards,
            max_added_cost=max_added_cost,
            max_nodes=max_nodes,
            time_limit_s=time_limit_s,
        )
        actions = epoch.actions
        roles = epoch.action_roles
        state = epoch.resulting_state.clone()
        nodes = epoch.nodes_expanded
        resource_limited = epoch.status == CampaignRealizationStatus.RESOURCE_LIMIT
        stop_reason = epoch.stop_reason
        workspace_events = epoch.workspace_events
        backend_satisfied = tuple(
            obligation.obligation_id for obligation in epoch.obligations_satisfied
        )
        if ("deal",) in actions:
            deal_index = actions.index(("deal",))
            pre_deal_state = start_state.clone()
            replay_actions(pre_deal_state, list(actions[:deal_index]))
            immediate_post_deal_state = pre_deal_state.clone()
            replay_actions(immediate_post_deal_state, [("deal",)])

    replayed = start_state.clone()
    replayed_cost: Optional[int] = None
    replay_ok = False
    try:
        replayed_cost = replay_actions(replayed, list(actions))
        replay_ok = bool(
            states_structurally_equal(replayed, state)
            and sum(1 for action in actions if action == ("deal",)) <= 1
        )
    except ValueError:
        replayed_cost = None

    # A bounded miss is not a state the caller may continue from.  Avoid
    # launching two complete source-enumeration analyses after the tactical
    # slice has already expired; doing so was the principal controller
    # deadline overrun.  Successful/non-expired transitions still receive the
    # full fresh reanalysis invariant below.
    analysis_time_exhausted = time.perf_counter() - started >= time_limit_s
    if resource_limited and analysis_time_exhausted:
        campaign_after = None
        portfolio_after = portfolio_before
        must_after = must_before
        stop_reason = (
            f"{stop_reason}; post-bound campaign reanalysis skipped at deadline"
        )
    else:
        campaign_after = _fixed_reanalysis(
            state,
            identity,
            cards,
            max_source_combinations=max_source_combinations,
        )
        portfolio_after = analyze_foundation_campaigns(
            state,
            cards=cards,
            max_source_combinations=max_source_combinations,
        )
        must_after = _must_keys(campaign_after)
    deals_applied = sum(1 for action in actions if action == ("deal",))
    suits_after = _foundation_suits(state)
    foundation_added = suits_after[len(suits_before):]
    exact_removed = bool(
        len(state.foundations) == foundation_before + 1
        and foundation_added == (campaign.suit,)
        and _foundation_count_for_suit(state, campaign.suit)
        == suit_foundations_before + 1
    )
    reached_next = current_stock_epoch(state, 5) == start_epoch + 1
    burden_fell = bool(
        campaign_after is not None
        and (
            campaign_after.estimated_campaign_cost
            < campaign.estimated_campaign_cost - 0.5
            or len(must_after) < len(must_before)
            or _longest_band(state, campaign.suit)
            > _longest_band(start_state, campaign.suit)
        )
    )
    if exact_removed and replay_ok:
        status = CampaignTransitionStatus.FOUNDATION_REMOVED
        stop_reason = "fixed campaign foundation removed and independently replayed"
    elif resource_limited:
        status = CampaignTransitionStatus.RESOURCE_LIMIT
    elif reached_next and replay_ok:
        status = (
            CampaignTransitionStatus.CAMPAIGN_ADVANCED
            if burden_fell
            else CampaignTransitionStatus.NEXT_EPOCH_REACHED
        )
    elif actions and replay_ok and burden_fell:
        status = CampaignTransitionStatus.CAMPAIGN_ADVANCED
    elif actions and replay_ok:
        status = CampaignTransitionStatus.PARTIAL
    else:
        status = CampaignTransitionStatus.NOT_FOUND_WITHIN_BOUND

    satisfied = tuple(
        obligation
        for obligation in obligations
        if transition_obligation_is_satisfied(
            state,
            campaign,
            obligation,
            start_epoch=start_epoch,
            foundation_suit_before=suit_foundations_before,
            accomplished=backend_satisfied,
        )
    )
    remaining = tuple(obligation for obligation in obligations if obligation not in satisfied)
    longest_before = _longest_band(start_state, campaign.suit)
    longest_after = _longest_band(state, campaign.suit)
    progress = (
        CampaignTransitionProgress(
            CampaignTransitionPhase.FROZEN,
            0,
            0,
            start_epoch,
            must_before,
            longest_before,
            (),
            tuple(obligation.obligation_id for obligation in obligations),
            tuple(empty_columns(start_state)),
            foundation_before,
            "campaign identity, mode, obligations, and next row frozen",
        ),
        CampaignTransitionProgress(
            CampaignTransitionPhase.COMPLETE
            if exact_removed
            else CampaignTransitionPhase.REANALYZE,
            len(actions),
            replayed_cost or 0,
            current_stock_epoch(state, 5),
            must_after,
            longest_after,
            tuple(obligation.obligation_id for obligation in satisfied),
            tuple(obligation.obligation_id for obligation in remaining),
            tuple(empty_columns(state)),
            len(state.foundations),
            stop_reason,
        ),
    )
    return CampaignTransitionResult(
        status=status,
        identity=identity,
        mode=mode,
        start_epoch=start_epoch,
        target_epoch=target_epoch,
        actions=actions,
        action_roles=roles,
        corrected_added_cost=replayed_cost if replay_ok else None,
        resulting_state=state.clone(),
        obligations=obligations,
        obligations_satisfied=satisfied,
        obligations_remaining=remaining,
        bands_before=bands_before,
        bands_after=locate_campaign_bands(state, campaign.suit),
        must_sources_before=must_before,
        must_sources_after=must_after,
        workspace_events=workspace_events,
        exact_row=exact_row,
        deals_applied=deals_applied,
        foundation_count_before=foundation_before,
        foundation_count_after=len(state.foundations),
        foundation_suits_before=suits_before,
        foundation_suits_after=suits_after,
        foundation_suits_added=foundation_added,
        portfolio_before=portfolio_before,
        portfolio_after=portfolio_after,
        campaign_before=campaign,
        campaign_after=campaign_after,
        progress=progress,
        nodes_expanded=nodes,
        elapsed_seconds=time.perf_counter() - started,
        independent_replay_verified=replay_ok,
        replayed_cost=replayed_cost,
        pre_deal_state=pre_deal_state,
        immediate_post_deal_state=immediate_post_deal_state,
        stop_reason=stop_reason,
    )
