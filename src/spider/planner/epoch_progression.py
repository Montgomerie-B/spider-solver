"""Perfect-information stock-epoch planning for the anytime controller.

The facts in this module guide milestone ordering and Deal timing only.  A
current-epoch material block is never a dead-state or proof-pruning result.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action
from spider.planner.structural_construction import (
    ConstructionDisposition,
    SameSuitConstructionOpportunity,
)


class PreDealWorkDisposition(str, Enum):
    MUST_BEFORE_DEAL = "MUST_BEFORE_DEAL"
    SHOULD_BEFORE_DEAL = "SHOULD_BEFORE_DEAL"
    CAN_DEFER = "CAN_DEFER"
    DEFER_FOR_FREE_FUTURE_JOIN = "DEFER_FOR_FREE_FUTURE_JOIN"
    AVOID_BEFORE_DEAL = "AVOID_BEFORE_DEAL"


class EpochTransitionStatus(str, Enum):
    NO_STOCK = "NO_STOCK"
    CURRENT_EPOCH_FEASIBLE = "CURRENT_EPOCH_FEASIBLE"
    PREPARATION_REQUIRED = "PREPARATION_REQUIRED"
    PREPARATION_READY = "PREPARATION_READY"
    PURPOSEFUL_DEAL = "PURPOSEFUL_DEAL"
    DEFERRED_FOR_HIGHER_VALUE_WORK = "DEFERRED_FOR_HIGHER_VALUE_WORK"
    BOUNDEDLY_EXHAUSTED = "BOUNDEDLY_EXHAUSTED"


@dataclass(frozen=True)
class MaterialAvailability:
    suit: str
    rank: int
    copies_required: int
    face_up_copies: int
    hidden_tableau_copies: int
    future_stock_epochs: Tuple[int, ...]
    earliest_feasible_epoch: Optional[int]
    current_epoch_sufficient: bool
    proof_pruning_allowed: bool = False

    @property
    def current_tableau_copies(self) -> int:
        return self.face_up_copies + self.hidden_tableau_copies


@dataclass(frozen=True)
class CampaignEpochAvailability:
    campaign_id: str
    current_epoch: int
    material: Tuple[MaterialAvailability, ...]
    current_epoch_feasible: bool
    preparation_only: bool
    earliest_feasible_epoch: Optional[int]
    stock_blocked_ranks: Tuple[int, ...]
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class MilestoneEpochFeasibility:
    milestone_id: str
    current_epoch: int
    feasible_now: bool
    preparation_only: bool
    earliest_feasible_epoch: Optional[int]
    material: Tuple[MaterialAvailability, ...]
    reason: str
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class PreDealWorkItem:
    item_id: str
    disposition: PreDealWorkDisposition
    description: str
    campaign_id: Optional[str]
    milestone_id: Optional[str]
    action: Optional[Action]
    estimated_paid_cost: int
    expected_structural_saving: float
    exact_next_row_effect: str
    receiver_damage: bool = False
    completed: bool = False
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class EpochTransitionAssessment:
    current_epoch: int
    next_epoch: Optional[int]
    exact_next_row: Tuple[Card, ...]
    status: EpochTransitionStatus
    campaign_ids: Tuple[str, ...]
    milestone_ids: Tuple[str, ...]
    work_items: Tuple[PreDealWorkItem, ...]
    completed_work: Tuple[str, ...]
    deliberately_deferred_work: Tuple[str, ...]
    free_future_joins: Tuple[str, ...]
    surrendered_opportunities: Tuple[str, ...]
    purposeful_deal_eligible: bool
    purpose: str
    post_deal_reanalysis_required: bool = True
    proof_pruning_allowed: bool = False


def current_stock_epoch(state: SpiderState) -> int:
    """Return the number of stock rows already consumed."""
    return 5 - len(state.stock) // 10


def future_stock_rows(state: SpiderState) -> Tuple[Tuple[Card, ...], ...]:
    """Return remaining rows in actual deal order (next row first)."""
    return tuple(
        tuple(state.stock[end - 10 : end])
        for end in range(len(state.stock), 9, -10)
    )


def _tableau_counts(state: SpiderState) -> Tuple[Counter, Counter]:
    face_up: Counter = Counter()
    hidden: Counter = Counter()
    for column in state.columns:
        face_up.update((card.suit, card.rank) for card in column.face_up)
        hidden.update((card.suit, card.rank) for card in column.face_down)
    return face_up, hidden


def analyze_material_availability(
    state: SpiderState,
    requirements: Iterable[Tuple[str, int, int]],
) -> Tuple[MaterialAvailability, ...]:
    """Resolve duplicate physical cards without committing to coordinates."""
    face_up, hidden = _tableau_counts(state)
    epoch = current_stock_epoch(state)
    rows = future_stock_rows(state)
    result = []
    for suit, rank, copies_required in requirements:
        key = (suit.lower(), int(rank))
        current = face_up[key] + hidden[key]
        arrivals = []
        cumulative = current
        earliest = epoch if cumulative >= copies_required else None
        for offset, row in enumerate(rows, 1):
            row_count = sum((card.suit, card.rank) == key for card in row)
            arrivals.extend([epoch + offset] * row_count)
            cumulative += row_count
            if earliest is None and cumulative >= copies_required:
                earliest = epoch + offset
        result.append(
            MaterialAvailability(
                key[0],
                key[1],
                copies_required,
                face_up[key],
                hidden[key],
                tuple(arrivals),
                earliest,
                current >= copies_required,
            )
        )
    return tuple(result)


def analyze_campaign_epoch_availability(
    state: SpiderState,
    campaign_id: str,
    suit: str,
    required_ranks: Sequence[int],
    *,
    copies_per_rank: int = 1,
) -> CampaignEpochAvailability:
    material = analyze_material_availability(
        state,
        ((suit, rank, copies_per_rank) for rank in required_ranks),
    )
    blocked = tuple(item.rank for item in material if not item.current_epoch_sufficient)
    feasible = not blocked
    epochs = [item.earliest_feasible_epoch for item in material]
    earliest = max(epochs) if epochs and all(item is not None for item in epochs) else None
    rationale = (
        ("all interchangeable required material is already in the tableau",)
        if feasible
        else (
            "current-epoch completion lacks interchangeable tableau material for ranks "
            + ",".join(str(rank) for rank in blocked),
            f"earliest material-feasible epoch={earliest}",
            "this is planning evidence only; alternative work and Deal remain legal",
        )
    )
    return CampaignEpochAvailability(
        campaign_id,
        current_stock_epoch(state),
        material,
        feasible,
        not feasible,
        earliest,
        blocked,
        rationale,
    )


def milestone_epoch_feasibility(
    milestone_id: str,
    availability: CampaignEpochAvailability,
    *,
    ranks: Sequence[int] = (),
) -> MilestoneEpochFeasibility:
    selected = tuple(
        item for item in availability.material if not ranks or item.rank in set(ranks)
    )
    feasible = all(item.current_epoch_sufficient for item in selected)
    epochs = [item.earliest_feasible_epoch for item in selected]
    earliest = (
        max(epochs)
        if epochs and all(item is not None for item in epochs)
        else (availability.current_epoch if not selected else None)
    )
    return MilestoneEpochFeasibility(
        milestone_id,
        availability.current_epoch,
        feasible,
        not feasible,
        earliest,
        selected,
        (
            "required interchangeable material is available now"
            if feasible
            else f"material first becomes sufficient in epoch {earliest}"
        ),
    )


def classify_pre_deal_construction(
    state: SpiderState,
    opportunities: Sequence[SameSuitConstructionOpportunity],
    *,
    campaign_id: Optional[str] = None,
    milestone_id: Optional[str] = None,
) -> Tuple[PreDealWorkItem, ...]:
    """Classify current construction against the exact next stock row."""
    rows = future_stock_rows(state)
    next_row = rows[0] if rows else ()
    next_epoch = current_stock_epoch(state) + 1
    items = []
    for opportunity in opportunities:
        src, dst, _count = opportunity.action
        incoming = next_row[dst] if next_row else None
        receiver_damage = bool(opportunity.consumes_important_receiver)
        if (
            opportunity.exact_future_free_join_epoch is not None
            and opportunity.exact_future_free_join_epoch <= next_epoch
        ):
            disposition = PreDealWorkDisposition.DEFER_FOR_FREE_FUTURE_JOIN
            effect = "exact next row creates an equivalent same-suit join without paid handling"
        elif receiver_damage or opportunity.disposition == ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT:
            disposition = PreDealWorkDisposition.AVOID_BEFORE_DEAL
            effect = "current action consumes receiver/workspace needed for exact row reception"
        elif opportunity.disposition == ConstructionDisposition.MAKE_NOW and opportunity.current_paid_cost <= 1:
            covered = incoming is not None
            disposition = (
                PreDealWorkDisposition.MUST_BEFORE_DEAL
                if covered
                else PreDealWorkDisposition.SHOULD_BEFORE_DEAL
            )
            effect = (
                f"next-row {incoming} covers destination column {dst + 1}"
                if covered
                else "cheap durable join remains positive preparation"
            )
        else:
            disposition = PreDealWorkDisposition.CAN_DEFER
            effect = "no exact evidence that waiting materially increases cost"
        payload = repr((opportunity.opportunity_id, disposition.value, campaign_id, milestone_id))
        item_id = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        items.append(
            PreDealWorkItem(
                item_id,
                disposition,
                f"construct {opportunity.run_length_after}-card {opportunity.suit.upper()} run",
                campaign_id,
                milestone_id,
                opportunity.action,
                opportunity.current_paid_cost,
                float(opportunity.new_adjacencies),
                effect,
                receiver_damage,
            )
        )
    return tuple(items)


def assess_epoch_transition(
    state: SpiderState,
    availabilities: Sequence[CampaignEpochAvailability],
    work_items: Sequence[PreDealWorkItem] = (),
    *,
    milestone_ids: Sequence[str] = (),
    boundedly_exhausted: bool = False,
) -> EpochTransitionAssessment:
    epoch = current_stock_epoch(state)
    row = future_stock_rows(state)
    blocked = tuple(item for item in availabilities if not item.current_epoch_feasible)
    must_pending = tuple(
        item
        for item in work_items
        if item.disposition in (
            PreDealWorkDisposition.MUST_BEFORE_DEAL,
            PreDealWorkDisposition.SHOULD_BEFORE_DEAL,
        )
        and not item.completed
    )
    if not row:
        status = EpochTransitionStatus.NO_STOCK
        eligible = False
        purpose = "stock exhausted; no epoch transition exists"
    elif not blocked:
        status = EpochTransitionStatus.CURRENT_EPOCH_FEASIBLE
        eligible = False
        purpose = "selected campaign material is available in the current epoch"
    elif must_pending and not boundedly_exhausted:
        status = EpochTransitionStatus.PREPARATION_REQUIRED
        eligible = False
        purpose = "finish worthwhile exact-row preparation before Deal"
    else:
        status = (
            EpochTransitionStatus.BOUNDEDLY_EXHAUSTED
            if boundedly_exhausted and must_pending
            else EpochTransitionStatus.PURPOSEFUL_DEAL
        )
        eligible = True
        earliest = min(
            item.earliest_feasible_epoch
            for item in blocked
            if item.earliest_feasible_epoch is not None
        ) if any(item.earliest_feasible_epoch is not None for item in blocked) else epoch + 1
        purpose = (
            f"advance toward epoch {earliest} for "
            + ", ".join(item.campaign_id for item in blocked)
        )
    completed = tuple(item.item_id for item in work_items if item.completed)
    deferred = tuple(
        item.item_id
        for item in work_items
        if item.disposition in (
            PreDealWorkDisposition.CAN_DEFER,
            PreDealWorkDisposition.DEFER_FOR_FREE_FUTURE_JOIN,
            PreDealWorkDisposition.AVOID_BEFORE_DEAL,
        )
    )
    return EpochTransitionAssessment(
        epoch,
        epoch + 1 if row else None,
        row[0] if row else (),
        status,
        tuple(item.campaign_id for item in blocked),
        tuple(milestone_ids),
        tuple(work_items),
        completed,
        deferred,
        tuple(
            item.item_id
            for item in work_items
            if item.disposition == PreDealWorkDisposition.DEFER_FOR_FREE_FUTURE_JOIN
        ),
        tuple(
            item.item_id
            for item in work_items
            if item.disposition == PreDealWorkDisposition.AVOID_BEFORE_DEAL
        ),
        eligible,
        purpose,
    )
