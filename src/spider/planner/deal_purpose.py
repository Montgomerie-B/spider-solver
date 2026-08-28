"""Auditable, ordering-only contracts for irreversible stock Deals.

A contract records why a known row was consumed and how that claim can later
be checked.  Contracts never participate in canonical state identity, exact
transposition dominance, or admissible proof pruning.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.foundation_campaign import FoundationCampaign
from spider.planner.residual_campaign import (
    FoundationCheckpointProfile,
    NextFoundationReadiness,
    StockOpportunityAssessment,
)
from spider.planner.supply_consumption import (
    CampaignSupplyObligation,
    SupplyConsumptionResult,
    SupplyConsumptionStage,
    derive_campaign_supply_obligations,
)
from spider.planner.stock_reception import next_stock_row
from spider.state_identity import CanonicalStateKey, canonical_state_key


class DealPurposeKind(str, Enum):
    STRATEGIC_UNLOCK = "STRATEGIC_UNLOCK"
    CAMPAIGN_SUPPLY = "CAMPAIGN_SUPPLY"
    RECEIVER_GEOMETRY = "RECEIVER_GEOMETRY"
    WORKSPACE_TRANSITION = "WORKSPACE_TRANSITION"
    PREPARATION_PAYOFF = "PREPARATION_PAYOFF"
    CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY = "CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY"
    ESCAPE_ONLY = "ESCAPE_ONLY"
    INCONCLUSIVE = "INCONCLUSIVE"


class DealObjectiveType(str, Enum):
    CAMPAIGN = "CAMPAIGN"
    ECONOMIC_PROJECT = "ECONOMIC_PROJECT"
    RECEIVER_CHAIN = "RECEIVER_CHAIN"
    WORKSPACE_EXCAVATION = "WORKSPACE_EXCAVATION"
    STOCK_TRANSITION = "STOCK_TRANSITION"
    UNRESOLVED = "UNRESOLVED"


class DealPurposeStatus(str, Enum):
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    PENDING = "PENDING"
    INVALIDATED = "INVALIDATED"
    FAILED = "FAILED"
    ESCAPE_RECLASSIFIED = "ESCAPE_RECLASSIFIED"
    DELIVERED_BUT_UNCONSUMED = "DELIVERED_BUT_UNCONSUMED"


@dataclass(frozen=True)
class DealPurposeEvidence:
    foundations: int
    total_must_burden: int
    target_must_burden: Optional[int]
    target_readiness_key: Optional[Tuple]
    target_same_suit_coverage: int
    target_receiver_ready: int
    target_removal_macro_available: bool
    target_estimated_cost: Optional[float]
    exact_dependencies_supplied: int = 0
    exact_receivers_satisfied: int = 0
    required_sources_actionable: Tuple[str, ...] = ()
    removal_relevant_corridors: Tuple[str, ...] = ()
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DealPurposeContract:
    contract_id: str
    parent_state_key: CanonicalStateKey
    exact_incoming_row: Tuple[Card, ...]
    purpose: DealPurposeKind
    objective_type: DealObjectiveType
    target_objective: str
    campaign_id: Optional[str]
    project_id: Optional[str]
    evidence_before: DealPurposeEvidence
    expected_structural_consequence: Tuple[str, ...]
    surrendered_current_opportunities: Tuple[str, ...]
    predicted_milestone: str
    bounded_expected_cost: Optional[float]
    bounded_expected_benefit: Optional[float]
    validation_conditions: Tuple[str, ...]
    expiry_conditions: Tuple[str, ...]
    created_depth: int
    horizon_expansions: int
    supply_obligations: Tuple[CampaignSupplyObligation, ...] = ()
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DealPurposeOutcome:
    contract_id: str
    status: DealPurposeStatus
    evaluated_state_key: CanonicalStateKey
    expansions_elapsed: int
    observed_consequences: Tuple[str, ...]
    reason: str
    objective_still_credible: bool
    supply_stage: Optional[SupplyConsumptionStage] = None
    supplied_assets_delivered: int = 0
    supplied_assets_consumed: int = 0
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class DealPurposeAssessment:
    contract: DealPurposeContract
    outcome: DealPurposeOutcome
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class SuccessiveDealAuditEntry:
    deal_ordinal: int
    contract_id: str
    exact_incoming_row: Tuple[Card, ...]
    purpose: DealPurposeKind
    target_objective: str
    surrendered_opportunities: Tuple[str, ...]
    status_before_next_deal: DealPurposeStatus
    previous_contract_resolution: Optional[str]
    promised_dependencies: Tuple[str, ...] = ()
    consumption_stage: Optional[SupplyConsumptionStage] = None
    dependency_closure_attempted: bool = False
    dependency_closure_result: Optional[str] = None
    reason_another_deal_considered: Optional[str] = None
    proof_pruning_allowed: bool = False


def _readiness(profile: FoundationCheckpointProfile, label: Optional[str]) -> Optional[NextFoundationReadiness]:
    if label is None:
        return profile.best_readiness
    return next(
        (item for item in profile.next_foundation_readiness if item.campaign_label == label),
        None,
    )


def evidence_from_profile(
    profile: FoundationCheckpointProfile,
    *,
    campaign_id: Optional[str] = None,
    dependencies_supplied: int = 0,
    receivers_satisfied: int = 0,
    required_sources_actionable: Sequence[str] = (),
    removal_relevant_corridors: Sequence[str] = (),
) -> DealPurposeEvidence:
    readiness = _readiness(profile, campaign_id)
    return DealPurposeEvidence(
        foundations=profile.foundations,
        total_must_burden=profile.total_campaign_must_burden,
        target_must_burden=(
            readiness.must_dependencies_remaining if readiness is not None else None
        ),
        target_readiness_key=(readiness.ordering_key() if readiness is not None else None),
        target_same_suit_coverage=(
            readiness.assembled_same_suit_rank_coverage if readiness is not None else 0
        ),
        target_receiver_ready=(
            readiness.receiver_conditions_ready if readiness is not None else 0
        ),
        target_removal_macro_available=bool(
            readiness is not None and readiness.bounded_removal_macro_available
        ),
        target_estimated_cost=(
            readiness.bounded_estimated_cost_to_removal if readiness is not None else None
        ),
        exact_dependencies_supplied=dependencies_supplied,
        exact_receivers_satisfied=receivers_satisfied,
        required_sources_actionable=tuple(required_sources_actionable),
        removal_relevant_corridors=tuple(removal_relevant_corridors),
    )


def removal_relevant_changes(
    before: DealPurposeEvidence,
    after: DealPurposeEvidence,
) -> Tuple[str, ...]:
    """Return concrete campaign/removal changes; generic activity is absent."""
    changes = []
    if after.foundations > before.foundations:
        changes.append("target foundation count increased")
    if after.total_must_burden < before.total_must_burden:
        changes.append("portfolio MUST burden decreased")
    if (
        before.target_must_burden is not None
        and after.target_must_burden is not None
        and after.target_must_burden < before.target_must_burden
    ):
        changes.append("target campaign MUST dependency removed")
    if after.target_same_suit_coverage > before.target_same_suit_coverage:
        changes.append("target same-suit interval coverage increased")
    if after.target_receiver_ready > before.target_receiver_ready:
        changes.append("target receiver obligation became ready")
    if after.target_removal_macro_available and not before.target_removal_macro_available:
        changes.append("bounded target removal macro became available")
    if (
        before.target_estimated_cost is not None
        and after.target_estimated_cost is not None
        and after.target_estimated_cost < before.target_estimated_cost
    ):
        changes.append("bounded target removal estimate decreased")
    if set(after.required_sources_actionable) - set(before.required_sources_actionable):
        changes.append("previously blocked required source became actionable")
    if set(after.removal_relevant_corridors) - set(before.removal_relevant_corridors):
        changes.append("removal-relevant corridor became credible")
    return tuple(changes)


def _contract_id(parent: CanonicalStateKey, row: Sequence[Card], objective: str, depth: int) -> str:
    payload = repr((parent, tuple(row), objective, depth)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _select_purpose(
    before: DealPurposeEvidence,
    after: Optional[DealPurposeEvidence],
    *,
    preparation_repaid: bool,
    current_epoch_exhausted: bool,
    explicit_purpose: Optional[DealPurposeKind],
) -> DealPurposeKind:
    if explicit_purpose is not None:
        return explicit_purpose
    if preparation_repaid:
        return DealPurposeKind.PREPARATION_PAYOFF
    if after is not None:
        if after.exact_dependencies_supplied > 0:
            return DealPurposeKind.CAMPAIGN_SUPPLY
        if after.exact_receivers_satisfied > 0:
            return DealPurposeKind.RECEIVER_GEOMETRY
        if removal_relevant_changes(before, after):
            return DealPurposeKind.STRATEGIC_UNLOCK
    if current_epoch_exhausted:
        return DealPurposeKind.CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY
    if after is None:
        return DealPurposeKind.INCONCLUSIVE
    if not removal_relevant_changes(before, after):
        return DealPurposeKind.ESCAPE_ONLY
    return DealPurposeKind.INCONCLUSIVE


def create_deal_purpose_contract(
    state_before: SpiderState,
    before_profile: FoundationCheckpointProfile,
    *,
    after_profile: Optional[FoundationCheckpointProfile] = None,
    stock_opportunity: Optional[StockOpportunityAssessment] = None,
    campaign_id: Optional[str] = None,
    campaign: Optional[FoundationCampaign] = None,
    project_id: Optional[str] = None,
    objective_type: Optional[DealObjectiveType] = None,
    target_objective: Optional[str] = None,
    explicit_purpose: Optional[DealPurposeKind] = None,
    preparation_repaid: bool = False,
    current_epoch_exhausted: bool = False,
    predicted_milestone: Optional[str] = None,
    bounded_expected_cost: Optional[float] = None,
    bounded_expected_benefit: Optional[float] = None,
    created_depth: int = 0,
    horizon_expansions: int = 2,
) -> DealPurposeContract:
    """Create a deterministic contract for the exact next row.

    ``STRATEGIC_UNLOCK`` can only be inferred from removal-relevant evidence.
    Mobility, exposed tops, stock epoch, and generic project actionability are
    deliberately not accepted here.
    """
    if horizon_expansions <= 0:
        raise ValueError("Deal contract horizon must be positive")
    row = tuple(next_stock_row(state_before) or ())
    before = evidence_from_profile(before_profile, campaign_id=campaign_id)
    after = None
    if after_profile is not None:
        after = evidence_from_profile(
            after_profile,
            campaign_id=campaign_id,
            dependencies_supplied=(
                stock_opportunity.dependencies_supplied if stock_opportunity else 0
            ),
            receivers_satisfied=(
                stock_opportunity.exact_receivers_satisfied if stock_opportunity else 0
            ),
        )
    purpose = _select_purpose(
        before,
        after,
        preparation_repaid=preparation_repaid,
        current_epoch_exhausted=current_epoch_exhausted,
        explicit_purpose=explicit_purpose,
    )
    if objective_type is None:
        if campaign_id is not None:
            objective_type = DealObjectiveType.CAMPAIGN
        elif project_id is not None:
            objective_type = DealObjectiveType.ECONOMIC_PROJECT
        elif purpose == DealPurposeKind.RECEIVER_GEOMETRY:
            objective_type = DealObjectiveType.RECEIVER_CHAIN
        elif purpose == DealPurposeKind.WORKSPACE_TRANSITION:
            objective_type = DealObjectiveType.WORKSPACE_EXCAVATION
        elif purpose in (
            DealPurposeKind.CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY,
            DealPurposeKind.ESCAPE_ONLY,
        ):
            objective_type = DealObjectiveType.STOCK_TRANSITION
        else:
            objective_type = DealObjectiveType.UNRESOLVED
    objective = target_objective or campaign_id or project_id or "unresolved next-removal objective"
    observed = removal_relevant_changes(before, after) if after is not None else ()
    expected = observed or (
        "fresh campaign analysis must demonstrate a removal-relevant consequence",
    )
    surrendered = (
        stock_opportunity.current_epoch_projects_blocked if stock_opportunity else ()
    )
    milestone = predicted_milestone or (
        observed[0] if observed else "named objective advances within the bounded horizon"
    )
    parent = canonical_state_key(state_before)
    supply_obligations = (
        derive_campaign_supply_obligations(
            state_before,
            row,
            campaign,
            campaign_id=campaign_id,
        )
        if purpose == DealPurposeKind.CAMPAIGN_SUPPLY
        else ()
    )
    return DealPurposeContract(
        contract_id=_contract_id(parent, row, objective, created_depth),
        parent_state_key=parent,
        exact_incoming_row=row,
        purpose=purpose,
        objective_type=objective_type,
        target_objective=objective,
        campaign_id=campaign_id,
        project_id=project_id,
        evidence_before=before,
        expected_structural_consequence=tuple(expected),
        surrendered_current_opportunities=tuple(surrendered),
        predicted_milestone=milestone,
        bounded_expected_cost=bounded_expected_cost,
        bounded_expected_benefit=bounded_expected_benefit,
        validation_conditions=(
            "foundation increase or named campaign dependency/readiness consequence",
            "generic mobility, reveal, or epoch progress alone is insufficient",
        ),
        expiry_conditions=(
            f"no promised consequence after {horizon_expansions} descendant expansions",
            "fresh analysis explicitly invalidates the named objective",
        ),
        created_depth=created_depth,
        horizon_expansions=horizon_expansions,
        supply_obligations=supply_obligations,
    )


def validate_deal_purpose_contract(
    contract: DealPurposeContract,
    current_profile: FoundationCheckpointProfile,
    *,
    current_depth: int,
    objective_still_credible: bool = True,
    supply_consumption: Optional[SupplyConsumptionResult] = None,
) -> DealPurposeOutcome:
    elapsed = max(0, current_depth - contract.created_depth)
    current = evidence_from_profile(current_profile, campaign_id=contract.campaign_id)
    changes = removal_relevant_changes(contract.evidence_before, current)
    supply_stage = (
        supply_consumption.highest_stage if supply_consumption is not None else None
    )
    supplied = supply_consumption.delivered_count if supply_consumption is not None else 0
    consumed = supply_consumption.consumed_count if supply_consumption is not None else 0
    is_supply = contract.purpose == DealPurposeKind.CAMPAIGN_SUPPLY
    supply_fulfilled = bool(
        is_supply
        and supply_consumption is not None
        and supply_consumption.fully_consumed
        and supply_consumption.critical_direct_campaign_advance
    )
    if is_supply and supply_fulfilled:
        status = DealPurposeStatus.FULFILLED
        reason = "the supplied campaign dependency was actually consumed and integrated"
    elif is_supply and not objective_still_credible:
        status = DealPurposeStatus.INVALIDATED
        reason = "fresh structural analysis invalidated the named supply objective"
    elif is_supply and supplied and elapsed < contract.horizon_expansions:
        status = DealPurposeStatus.PARTIALLY_FULFILLED
        reason = "the promised asset arrived but has not yet been consumed by the campaign"
    elif is_supply and supplied:
        status = DealPurposeStatus.DELIVERED_BUT_UNCONSUMED
        reason = "the contract horizon ended after delivery without campaign consumption"
    elif is_supply and elapsed < contract.horizon_expansions:
        status = DealPurposeStatus.PENDING
        reason = "campaign supply remains promised inside its bounded validation horizon"
    elif is_supply:
        status = DealPurposeStatus.FAILED
        reason = "campaign supply was not consumed within the contract envelope"
    elif current.foundations > contract.evidence_before.foundations:
        status = DealPurposeStatus.FULFILLED
        reason = "foundation milestone fulfilled the Deal purpose"
    elif not objective_still_credible:
        status = DealPurposeStatus.INVALIDATED
        reason = "fresh structural analysis invalidated the named objective"
    elif changes and (
        current.target_removal_macro_available
        or "target campaign MUST dependency removed" in changes
        or "previously blocked required source became actionable" in changes
    ):
        status = DealPurposeStatus.FULFILLED
        reason = "the promised removal-relevant consequence materialised"
    elif changes:
        status = DealPurposeStatus.PARTIALLY_FULFILLED
        reason = "the named objective advanced without reaching the promised milestone"
    elif elapsed < contract.horizon_expansions:
        status = DealPurposeStatus.PENDING
        reason = "the contract remains inside its bounded validation horizon"
    elif contract.purpose in (
        DealPurposeKind.ESCAPE_ONLY,
        DealPurposeKind.INCONCLUSIVE,
        DealPurposeKind.CURRENT_EPOCH_EXHAUSTED_ECONOMICALLY,
    ):
        status = DealPurposeStatus.ESCAPE_RECLASSIFIED
        reason = "stock advanced without a demonstrated removal-relevant payoff"
    else:
        status = DealPurposeStatus.FAILED
        reason = "the promised consequence did not materialise within the contract envelope"
    return DealPurposeOutcome(
        contract_id=contract.contract_id,
        status=status,
        evaluated_state_key=current_profile.state_key,
        expansions_elapsed=elapsed,
        observed_consequences=changes,
        reason=reason,
        objective_still_credible=objective_still_credible,
        supply_stage=supply_stage,
        supplied_assets_delivered=supplied,
        supplied_assets_consumed=consumed,
    )


def contract_requires_descendant(outcome: DealPurposeOutcome) -> bool:
    return outcome.status in (
        DealPurposeStatus.PENDING,
        DealPurposeStatus.PARTIALLY_FULFILLED,
    )


def audit_successive_deal(
    contract: DealPurposeContract,
    outcome: DealPurposeOutcome,
    *,
    deal_ordinal: int,
    previous_contract_resolution: Optional[str] = None,
    dependency_closure_attempted: bool = False,
    dependency_closure_result: Optional[str] = None,
    reason_another_deal_considered: Optional[str] = None,
) -> SuccessiveDealAuditEntry:
    return SuccessiveDealAuditEntry(
        deal_ordinal=deal_ordinal,
        contract_id=contract.contract_id,
        exact_incoming_row=contract.exact_incoming_row,
        purpose=contract.purpose,
        target_objective=contract.target_objective,
        surrendered_opportunities=contract.surrendered_current_opportunities,
        status_before_next_deal=outcome.status,
        previous_contract_resolution=previous_contract_resolution,
        promised_dependencies=tuple(
            item.dependency_key for item in contract.supply_obligations
        ),
        consumption_stage=outcome.supply_stage,
        dependency_closure_attempted=dependency_closure_attempted,
        dependency_closure_result=dependency_closure_result,
        reason_another_deal_considered=reason_another_deal_considered,
    )
