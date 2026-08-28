"""Ordering-only records for strategic investment and bounded continuity.

The objects in this module deliberately do not participate in canonical state
identity, transposition dominance, or admissible pruning.  They preserve why
paid structural work was undertaken so a freshly successful descendant can be
given one bounded opportunity to harvest that work.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.state_identity import CanonicalStateKey


class StructuralInvestmentKind(str, Enum):
    REMOVAL_CAMPAIGN = "REMOVAL_CAMPAIGN"
    RUN_CONSTRUCTION = "RUN_CONSTRUCTION"
    EXCAVATION = "EXCAVATION"
    WORKSPACE = "WORKSPACE"
    STOCK_RECEPTION = "STOCK_RECEPTION"
    DEPENDENCY_CLOSURE = "DEPENDENCY_CLOSURE"


class StructuralInvestmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_HARVESTED = "PARTIALLY_HARVESTED"
    HARVESTED = "HARVESTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class StructuralHarvestKind(str, Enum):
    FOUNDATION_REMOVED = "FOUNDATION_REMOVED"
    DEPENDENCY_CLOSED = "DEPENDENCY_CLOSED"
    SUPPLY_CONSUMED = "SUPPLY_CONSUMED"
    OVERLAY_REMOVED = "OVERLAY_REMOVED"
    SOURCE_EXPOSED = "SOURCE_EXPOSED"
    RECEIVER_CREATED = "RECEIVER_CREATED"
    WORKSPACE_USED = "WORKSPACE_USED"
    WORKSPACE_RECOVERED = "WORKSPACE_RECOVERED"
    PERMANENT_JOIN_CREATED = "PERMANENT_JOIN_CREATED"
    FRAGMENTS_MERGED = "FRAGMENTS_MERGED"
    TERMINAL_QUALIFIED = "TERMINAL_QUALIFIED"


class SameCampaignContinuationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPLANNED = "REPLANNED"
    HARVESTED = "HARVESTED"
    SUPERSEDED = "SUPERSEDED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class StructuralHarvest:
    kind: StructuralHarvestKind
    objective_id: str
    description: str
    dependency_ids: Tuple[str, ...] = ()
    source_keys: Tuple[str, ...] = ()
    permanent_joins: int = 0
    fragments_merged: int = 0
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class StructuralInvestmentEvidence:
    dependencies_closed: Tuple[str, ...] = ()
    supplied_assets_consumed: Tuple[str, ...] = ()
    overlays_removed: Tuple[str, ...] = ()
    sources_exposed: Tuple[str, ...] = ()
    receivers_created: Tuple[str, ...] = ()
    workspace_created: int = 0
    workspace_consumed: int = 0
    workspace_recovered: int = 0
    permanent_same_suit_joins_created: int = 0
    same_suit_fragments_merged: int = 0
    temporary_mixed_debt_incurred: float = 0.0
    proof_pruning_allowed: bool = False

    @property
    def campaign_specific_value(self) -> bool:
        return bool(
            self.dependencies_closed
            or self.supplied_assets_consumed
            or self.overlays_removed
            or self.sources_exposed
            or self.receivers_created
            or self.permanent_same_suit_joins_created
            or self.same_suit_fragments_merged
        )


@dataclass(frozen=True)
class StructuralInvestment:
    investment_id: str
    start_state_key: CanonicalStateKey
    objective_id: str
    kind: StructuralInvestmentKind
    paid_cost_invested: int
    stock_rows_spent: int
    evidence: StructuralInvestmentEvidence
    expected_harvest: Tuple[str, ...]
    actual_harvest: Tuple[StructuralHarvest, ...]
    created_depth: int
    created_elapsed_seconds: float
    maximum_further_cost: int
    maximum_descendant_expansions: int
    maximum_elapsed_seconds: float
    status: StructuralInvestmentStatus = StructuralInvestmentStatus.ACTIVE
    expiry_reason: Optional[str] = None
    proof_pruning_allowed: bool = False
    baseline_total_g: int = 0


@dataclass(frozen=True)
class StructuralInvestmentLedger:
    investments: Tuple[StructuralInvestment, ...] = ()
    proof_pruning_allowed: bool = False

    def add(self, investment: StructuralInvestment) -> "StructuralInvestmentLedger":
        return StructuralInvestmentLedger(self.investments + (investment,))

    def replace(self, investment: StructuralInvestment) -> "StructuralInvestmentLedger":
        return StructuralInvestmentLedger(
            tuple(
                investment if item.investment_id == investment.investment_id else item
                for item in self.investments
            )
        )

    def active_for(self, objective_id: str) -> Tuple[StructuralInvestment, ...]:
        return tuple(
            item
            for item in self.investments
            if item.objective_id == objective_id
            and item.status
            in (
                StructuralInvestmentStatus.ACTIVE,
                StructuralInvestmentStatus.PARTIALLY_HARVESTED,
            )
        )


@dataclass(frozen=True)
class SameCampaignContinuationCredit:
    credit_id: str
    objective_id: str
    investment_id: str
    latest_harvest: Tuple[StructuralHarvest, ...]
    outstanding_dependencies: Tuple[str, ...]
    paid_investment_to_date: int
    maximum_further_cost: int
    maximum_descendant_expansions: int
    maximum_elapsed_seconds: float
    created_depth: int
    created_elapsed_seconds: float
    status: SameCampaignContinuationStatus = SameCampaignContinuationStatus.ACTIVE
    expiry_reason: Optional[str] = None
    proof_pruning_allowed: bool = False
    baseline_total_g: int = 0

    @property
    def is_live(self) -> bool:
        return self.status in (
            SameCampaignContinuationStatus.ACTIVE,
            SameCampaignContinuationStatus.REPLANNED,
        )

    def ordering_key(self) -> Tuple:
        return (
            0 if self.is_live else 1,
            -len(self.latest_harvest),
            len(self.outstanding_dependencies),
            self.paid_investment_to_date,
            self.credit_id,
        )


def _stable_id(*parts: object) -> str:
    return hashlib.sha256(repr(parts).encode("utf-8")).hexdigest()[:16]


def investment_from_dependency_closure(
    start_state_key: CanonicalStateKey,
    result: object,
    *,
    created_depth: int,
    created_elapsed_seconds: float,
    maximum_further_cost: int,
    maximum_descendant_expansions: int,
    maximum_elapsed_seconds: float,
    baseline_total_g: int = 0,
    supply_consumed_obligation_ids: Optional[Sequence[str]] = None,
) -> StructuralInvestment:
    """Create an investment only from inspectable closure consequences."""
    objective_id = str(getattr(result, "campaign_id"))
    dependencies = tuple(getattr(result, "dependencies_closed", ()))
    overlays = tuple(getattr(result, "overlays_cleared", ()))
    supplies = (
        tuple(supply_consumed_obligation_ids)
        if supply_consumed_obligation_ids is not None
        else tuple(
            evidence.obligation_id
            for supply in getattr(result, "supply_consumptions", ())
            for evidence in getattr(supply, "evidence", ())
            if getattr(getattr(evidence, "stage", None), "value", None)
            in ("CONSUMED", "INTEGRATED")
            and getattr(evidence, "direct_campaign_advance", False)
        )
    )
    joins = sum(
        len(getattr(getattr(step, "lifecycle", None), "same_suit_joins_created", ()))
        for step in getattr(result, "steps", ())
    )
    mixed_debt = sum(
        float(getattr(getattr(step, "lifecycle", None), "estimated_rehandling_cost", 0.0))
        for step in getattr(result, "steps", ())
    )
    evidence = StructuralInvestmentEvidence(
        dependencies_closed=dependencies,
        supplied_assets_consumed=supplies,
        overlays_removed=overlays,
        permanent_same_suit_joins_created=joins,
        same_suit_fragments_merged=joins,
        temporary_mixed_debt_incurred=mixed_debt,
    )
    harvest = []
    if dependencies:
        harvest.append(
            StructuralHarvest(
                StructuralHarvestKind.DEPENDENCY_CLOSED,
                objective_id,
                "named campaign dependencies were removed",
                dependency_ids=dependencies,
            )
        )
    if supplies:
        harvest.append(
            StructuralHarvest(
                StructuralHarvestKind.SUPPLY_CONSUMED,
                objective_id,
                "promised supply was consumed by the named campaign",
                source_keys=supplies,
            )
        )
    if overlays:
        harvest.append(
            StructuralHarvest(
                StructuralHarvestKind.OVERLAY_REMOVED,
                objective_id,
                "named mixed overlays were removed",
                dependency_ids=overlays,
            )
        )
    if joins:
        harvest.append(
            StructuralHarvest(
                StructuralHarvestKind.PERMANENT_JOIN_CREATED,
                objective_id,
                "durable same-suit structure was created during closure",
                permanent_joins=joins,
                fragments_merged=joins,
            )
        )
    closure_status = getattr(getattr(result, "status", None), "value", "")
    if closure_status == "FOUNDATION_REMOVED":
        harvest.append(
            StructuralHarvest(
                StructuralHarvestKind.FOUNDATION_REMOVED,
                objective_id,
                "the named campaign produced a foundation",
            )
        )
        status = StructuralInvestmentStatus.HARVESTED
    else:
        status = (
            StructuralInvestmentStatus.PARTIALLY_HARVESTED
            if harvest
            else StructuralInvestmentStatus.ACTIVE
        )
    paid = int(getattr(result, "corrected_added_cost", 0) or 0)
    actions = tuple(getattr(result, "actions", ()))
    investment_id = _stable_id(
        start_state_key, objective_id, created_depth, actions, dependencies, overlays
    )
    return StructuralInvestment(
        investment_id,
        start_state_key,
        objective_id,
        StructuralInvestmentKind.DEPENDENCY_CLOSURE,
        paid,
        sum(action == ("deal",) for action in actions),
        evidence,
        (
            "advance the named campaign critical path",
            "integrate the prepared structure or remove the target foundation",
        ),
        tuple(harvest),
        created_depth,
        created_elapsed_seconds,
        maximum_further_cost,
        maximum_descendant_expansions,
        maximum_elapsed_seconds,
        status,
        None,
        False,
        baseline_total_g,
    )


def investment_from_construction(
    start_state_key: CanonicalStateKey,
    opportunity: object,
    *,
    objective_id: str,
    created_depth: int,
    created_elapsed_seconds: float,
    baseline_total_g: int,
) -> StructuralInvestment:
    """Record a durable same-suit join as an immediately harvested asset."""
    joins = int(getattr(opportunity, "new_adjacencies", 0))
    evidence = StructuralInvestmentEvidence(
        permanent_same_suit_joins_created=joins,
        same_suit_fragments_merged=max(1, joins),
    )
    harvest = StructuralHarvest(
        StructuralHarvestKind.PERMANENT_JOIN_CREATED,
        objective_id,
        "legal durable same-suit construction completed",
        permanent_joins=joins,
        fragments_merged=max(1, joins),
    )
    action = getattr(opportunity, "action", None)
    return StructuralInvestment(
        _stable_id(start_state_key, objective_id, action, created_depth),
        start_state_key,
        objective_id,
        StructuralInvestmentKind.RUN_CONSTRUCTION,
        int(getattr(opportunity, "current_paid_cost", 0)),
        0,
        evidence,
        (
            "reduce independent fragment handling",
            "extend or receive later same-suit structure",
        ),
        (harvest,),
        created_depth,
        created_elapsed_seconds,
        0,
        0,
        0.0,
        StructuralInvestmentStatus.HARVESTED,
        "durable construction asset created on this edge",
        False,
        baseline_total_g,
    )


def continuation_from_investment(
    investment: StructuralInvestment,
    *,
    outstanding_dependencies: Sequence[str],
) -> Optional[SameCampaignContinuationCredit]:
    """Issue credit only after a concrete, objective-specific harvest."""
    if (
        investment.status == StructuralInvestmentStatus.HARVESTED
        or not investment.actual_harvest
        or not investment.evidence.campaign_specific_value
    ):
        return None
    return SameCampaignContinuationCredit(
        _stable_id(investment.investment_id, investment.actual_harvest),
        investment.objective_id,
        investment.investment_id,
        investment.actual_harvest,
        tuple(outstanding_dependencies),
        investment.paid_cost_invested,
        investment.maximum_further_cost,
        investment.maximum_descendant_expansions,
        investment.maximum_elapsed_seconds,
        investment.created_depth,
        investment.created_elapsed_seconds,
        SameCampaignContinuationStatus.ACTIVE,
        None,
        False,
        investment.baseline_total_g,
    )


def refresh_continuation_credit(
    credit: SameCampaignContinuationCredit,
    *,
    current_depth: int,
    current_elapsed_seconds: float,
    objective_still_credible: bool,
    foundation_removed: bool = False,
    fully_harvested: bool = False,
    dominating_same_objective: bool = False,
    outstanding_dependencies: Optional[Sequence[str]] = None,
    current_g: Optional[int] = None,
) -> SameCampaignContinuationCredit:
    """Revalidate bounded continuity from fresh analysis, never from identity."""
    if foundation_removed or fully_harvested:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.HARVESTED,
            expiry_reason="named objective was harvested",
            outstanding_dependencies=tuple(outstanding_dependencies or ()),
        )
    if not objective_still_credible:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.INVALIDATED,
            expiry_reason="fresh campaign analysis invalidated the named objective",
        )
    if dominating_same_objective:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.SUPERSEDED,
            expiry_reason="a concrete same-objective lane dominates this continuation",
        )
    if current_depth - credit.created_depth > credit.maximum_descendant_expansions:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.EXPIRED,
            expiry_reason="descendant-expansion envelope expired",
        )
    if current_elapsed_seconds - credit.created_elapsed_seconds >= credit.maximum_elapsed_seconds:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.EXPIRED,
            expiry_reason="elapsed-time envelope expired",
        )
    if current_g is not None and current_g - credit.baseline_total_g > credit.maximum_further_cost:
        return replace(
            credit,
            status=SameCampaignContinuationStatus.EXPIRED,
            expiry_reason="maximum further paid-cost envelope expired",
        )
    updated = tuple(
        credit.outstanding_dependencies
        if outstanding_dependencies is None
        else outstanding_dependencies
    )
    return replace(
        credit,
        status=(
            SameCampaignContinuationStatus.REPLANNED
            if updated != credit.outstanding_dependencies
            else SameCampaignContinuationStatus.ACTIVE
        ),
        outstanding_dependencies=updated,
    )


def successor_matches_continuation(
    successor: object,
    credit: Optional[SameCampaignContinuationCredit],
) -> bool:
    return bool(
        credit is not None
        and credit.is_live
        and getattr(successor, "source_project_id", None) == credit.objective_id
    )
