"""Generic same-suit construction opportunities and structural balance sheet.

All values here are transparent ordering evidence.  They never authorize
proof pruning or alter legal move generation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.foundation_campaign import FoundationCampaign
from spider.rules import MW_RULES


class ConstructionDisposition(str, Enum):
    MAKE_NOW = "MAKE_NOW"
    DEFER_FOR_FREE_FUTURE_JOIN = "DEFER_FOR_FREE_FUTURE_JOIN"
    DOWNORDER_WORKSPACE_CONFLICT = "DOWNORDER_WORKSPACE_CONFLICT"


@dataclass(frozen=True)
class SameSuitConstructionOpportunity:
    action: Action
    suit: str
    source_fragment: Tuple[Card, ...]
    receiver: Card
    new_adjacencies: int
    run_length_before: int
    run_length_after: int
    stable_permanent: bool
    current_paid_cost: int
    reveals_card: bool
    workspace_delta: int
    consumes_important_receiver: bool
    exact_future_free_join_epoch: Optional[int]
    carrying_interference_cost: float
    removal_horizon: Optional[int]
    construction_horizon: int
    disposition: ConstructionDisposition
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    @property
    def opportunity_id(self) -> str:
        src, dst, count = self.action
        return f"join:{self.suit}:{src}:{dst}:{count}:{self.run_length_after}"

    def ordering_key(self) -> Tuple:
        disposition = {
            ConstructionDisposition.MAKE_NOW: 0,
            ConstructionDisposition.DEFER_FOR_FREE_FUTURE_JOIN: 1,
            ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT: 2,
        }[self.disposition]
        return (
            disposition,
            -self.new_adjacencies,
            -self.run_length_after,
            self.current_paid_cost,
            self.carrying_interference_cost,
            self.action,
        )


@dataclass(frozen=True)
class StructuralBalanceSheet:
    foundation_count: int
    permanent_same_suit_adjacencies: int
    durable_runs: int
    effective_workspace: int
    exposed_campaign_sources: int
    consumed_integrated_stock_assets: int
    prepared_receivers: int
    buried_compulsory_sources: int
    mixed_overlays: int
    fragment_count: int
    rehandling_debt: float
    unresolved_critical_path_dependencies: int
    prepared_run_carrying_interference_cost: float
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class StructuralConstructionAnalysis:
    opportunities: Tuple[SameSuitConstructionOpportunity, ...]
    balance_sheet: StructuralBalanceSheet
    proof_pruning_allowed: bool = False


def _run_length_ending_at_top(state: SpiderState, column: int) -> int:
    up = state.columns[column].face_up
    if not up:
        return 0
    length = 1
    for lower, upper in zip(reversed(up[:-1]), reversed(up[1:])):
        if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
            length += 1
        else:
            break
    return length


def _future_rows(state: SpiderState) -> Tuple[Tuple[Card, ...], ...]:
    return tuple(
        tuple(state.stock[len(state.stock) - 10 * (offset + 1): len(state.stock) - 10 * offset])
        for offset in range(len(state.stock) // 10)
    )


def _campaign_for_suit(
    campaigns: Sequence[FoundationCampaign], suit: str
) -> Optional[FoundationCampaign]:
    matching = tuple(item for item in campaigns if item.suit == suit)
    return min(matching, key=lambda item: item.campaign_score) if matching else None


def analyze_same_suit_construction(
    state: SpiderState,
    *,
    campaigns: Sequence[FoundationCampaign] = (),
    critical_receiver_columns: Sequence[int] = (),
) -> StructuralConstructionAnalysis:
    """Enumerate legal durable joins, including useful two-card runs."""
    current_epoch = 5 - len(state.stock) // 10
    future_rows = _future_rows(state)
    opportunities = []
    for action in state.enumerate_moves():
        src, dst, count = action
        moved = tuple(state.columns[src].face_up[-count:])
        receiver = state.columns[dst].top()
        if receiver is None or not moved:
            continue
        if receiver.suit != moved[0].suit or receiver.rank - 1 != moved[0].rank:
            continue
        lifecycle = assess_tableau_move(state, action)
        if lifecycle.placement_class != PlacementClass.STABLE_SAME_SUIT_JOIN:
            continue
        before_src = _run_length_ending_at_top(state, src)
        before_dst = _run_length_ending_at_top(state, dst)
        end = state.clone()
        paid = end.move(*action, rules=MW_RULES)
        after = _run_length_ending_at_top(end, dst)
        workspace_delta = sum(column.is_empty() for column in end.columns) - sum(
            column.is_empty() for column in state.columns
        )
        reveals_card = bool(
            count == len(state.columns[src].face_up)
            and state.columns[src].face_down
        )
        free_epoch = next(
            (
                current_epoch + offset
                for offset, row in enumerate(future_rows[:1], start=1)
                if row[dst] == moved[0]
            ),
            None,
        )
        campaign = _campaign_for_suit(campaigns, receiver.suit)
        removal_horizon = campaign.target_removal_epoch if campaign else None
        construction_horizon = current_epoch
        receiver_critical = dst in set(critical_receiver_columns)
        loses_only_workspace = bool(
            state.columns[dst].is_empty() and workspace_delta < 0
        )
        # Waiting is justified only by an exact row/column/card match and no
        # immediate reveal, workspace gain, or receiver urgency.
        if (
            free_epoch is not None
            and not reveals_card
            and workspace_delta <= 0
            and not receiver_critical
        ):
            disposition = ConstructionDisposition.DEFER_FOR_FREE_FUTURE_JOIN
        elif loses_only_workspace or receiver_critical:
            disposition = ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT
        else:
            disposition = ConstructionDisposition.MAKE_NOW
        carrying_horizon = free_epoch or removal_horizon or current_epoch
        carrying = float(max(0, carrying_horizon - current_epoch)) * 0.25
        if disposition == ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT:
            carrying += 1.0
        rationale = (
            f"creates {max(1, after - max(before_src, before_dst))} permanent same-suit adjacency",
            f"removal_horizon={removal_horizon}; construction_horizon={construction_horizon}",
            (
                f"exact future row {free_epoch} can create the same join in column {dst + 1}"
                if free_epoch is not None
                else "no exact known free future join in this receiver column"
            ),
            "construction value is ordering evidence only",
        )
        opportunities.append(
            SameSuitConstructionOpportunity(
                action,
                receiver.suit,
                moved,
                receiver,
                max(1, after - max(before_src, before_dst)),
                max(before_src, before_dst),
                after,
                True,
                paid,
                reveals_card,
                workspace_delta,
                receiver_critical,
                free_epoch,
                carrying,
                removal_horizon,
                construction_horizon,
                disposition,
                rationale,
            )
        )
    opportunities.sort(key=lambda item: item.ordering_key())
    permanent = sum(
        lower.suit == upper.suit and lower.rank - 1 == upper.rank
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )
    durable_runs = sum(
        _run_length_ending_at_top(state, index) >= 2
        for index, _column in enumerate(state.columns)
    )
    mixed = sum(
        lower.suit != upper.suit
        for column in state.columns
        for lower, upper in zip(column.face_up, column.face_up[1:])
    )
    fragments = sum(
        1
        for column in state.columns
        for index, card in enumerate(column.face_up)
        if index == 0
        or column.face_up[index - 1].suit != card.suit
        or column.face_up[index - 1].rank - 1 != card.rank
    )
    critical_cards = {
        (campaign.suit, need.rank)
        for campaign in campaigns
        for need in campaign.rank_needs
        if need.must_excavate
    }
    exposed_sources = sum(
        (card.suit, card.rank) in critical_cards
        for column in state.columns
        for card in column.face_up
    )
    buried_sources = sum(
        (card.suit, card.rank) in critical_cards
        for column in state.columns
        for card in column.face_down
    )
    unresolved = sum(
        need.must_excavate
        for campaign in campaigns
        for need in campaign.rank_needs
    )
    balance = StructuralBalanceSheet(
        len(state.foundations),
        permanent,
        durable_runs,
        sum(column.is_empty() for column in state.columns),
        exposed_sources,
        0,
        len({item.action[1] for item in opportunities}),
        buried_sources,
        mixed,
        fragments,
        float(mixed),
        unresolved,
        sum(item.carrying_interference_cost for item in opportunities),
    )
    return StructuralConstructionAnalysis(tuple(opportunities), balance)
