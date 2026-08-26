"""Ordering-only economics for bounded Spider planning projects.

Spider is a perfect-information game: exposing a face-down card provides no
information.  A reveal is valuable only through known structural consequences
such as a campaign dependency, receiver, same-suit join, workspace change, or
downstream excavation chain.

This module does not search a whole game, advance stock, select a production
controller action, or provide a proof bound.  Its costs, scores, tiers, and
dominance relations are transparent search-ordering metadata.  Exact/proof
search must retain economically unattractive alternatives unless an
independent mathematical dominance proof exists.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.move_lifecycle import (
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
)
from spider.planner.backward_strategy import (
    BuriedCardFact,
    CardLocation,
    ExcavationProject,
    LocationKind,
    analyze_buried_cards,
    analyze_excavation_projects,
    locate_all_cards,
)
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    RankSourceKind,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.stock_reception import LandingKind, next_stock_row


class EvidenceLevel(str, Enum):
    HARD_FACT = "HARD_FACT"
    BOUNDED_FACT = "BOUNDED_FACT"
    HEURISTIC_ESTIMATE = "HEURISTIC_ESTIMATE"


class EconomicProjectKind(str, Enum):
    EXCAVATE_CARD = "EXCAVATE_CARD"
    EXCAVATE_COLUMN_PREFIX = "EXCAVATE_COLUMN_PREFIX"
    CREATE_WORKSPACE = "CREATE_WORKSPACE"
    RECOVER_WORKSPACE = "RECOVER_WORKSPACE"
    PERMANENT_JOIN = "PERMANENT_JOIN"
    ASSEMBLE_BAND = "ASSEMBLE_BAND"
    REMOVE_MIXED_BOUNDARY = "REMOVE_MIXED_BOUNDARY"
    PREPARE_STOCK_RECEIVER = "PREPARE_STOCK_RECEIVER"
    FOUNDATION_CAMPAIGN_STEP = "FOUNDATION_CAMPAIGN_STEP"
    TEMPORARY_REWORK = "TEMPORARY_REWORK"
    DEFERRED_PROJECT = "DEFERRED_PROJECT"


class RevealValueClass(str, Enum):
    CRITICAL_NOW = "CRITICAL_NOW"
    REQUIRED_BEFORE_NEXT_DEAL = "REQUIRED_BEFORE_NEXT_DEAL"
    HIGH_VALUE_CURRENT_EPOCH = "HIGH_VALUE_CURRENT_EPOCH"
    USEFUL_BUT_DEFERRABLE = "USEFUL_BUT_DEFERRABLE"
    REPLACEABLE_BY_DUPLICATE = "REPLACEABLE_BY_DUPLICATE"
    REPLACEABLE_BY_STOCK = "REPLACEABLE_BY_STOCK"
    LATER_EPOCH = "LATER_EPOCH"
    LOW_CURRENT_VALUE = "LOW_CURRENT_VALUE"


class EconomicFrontierTier(int, Enum):
    STRUCTURALLY_DOMINANT = 1
    POSITIVE_INVESTMENT = 2
    SPECULATIVE_DEFERRABLE = 3
    ECONOMICALLY_UNEXPLAINED = 4


@dataclass(frozen=True)
class EvidenceAmount:
    """A numeric economic component with an explicit epistemic label."""

    value: Optional[float]
    evidence: EvidenceLevel
    rationale: str

    @property
    def ordering_value(self) -> float:
        return float(self.value or 0.0)


def hard(value: Optional[float], rationale: str) -> EvidenceAmount:
    return EvidenceAmount(value, EvidenceLevel.HARD_FACT, rationale)


def bounded(value: Optional[float], rationale: str) -> EvidenceAmount:
    return EvidenceAmount(value, EvidenceLevel.BOUNDED_FACT, rationale)


def heuristic(value: Optional[float], rationale: str) -> EvidenceAmount:
    return EvidenceAmount(value, EvidenceLevel.HEURISTIC_ESTIMATE, rationale)


@dataclass(frozen=True)
class EconomicProjectCost:
    immediate_paid_cost: EvidenceAmount
    bounded_tactical_cost: EvidenceAmount
    necessary_stock_deals: EvidenceAmount
    existing_rehandling_obligation: EvidenceAmount
    expected_additional_paid_moves: EvidenceAmount
    mixed_suit_park_debt: EvidenceAmount
    stable_joins_to_break: EvidenceAmount
    workspace_creation_cost: EvidenceAmount
    workspace_recovery_cost: EvidenceAmount
    destination_preparation_cost: EvidenceAmount
    expected_future_rehandling: EvidenceAmount
    timing_delay: EvidenceAmount

    @property
    def components(self) -> Tuple[Tuple[str, EvidenceAmount], ...]:
        return tuple(
            (name, getattr(self, name))
            for name in self.__dataclass_fields__
        )

    @property
    def ordering_total(self) -> float:
        """Heuristic total for ordering; never an admissible lower bound."""
        return sum(amount.ordering_value for _name, amount in self.components)

    @property
    def hard_observed_total(self) -> float:
        return sum(
            amount.ordering_value
            for _name, amount in self.components
            if amount.evidence == EvidenceLevel.HARD_FACT
        )


def empty_project_cost() -> EconomicProjectCost:
    return EconomicProjectCost(
        immediate_paid_cost=hard(0, "no project action has yet been taken"),
        bounded_tactical_cost=bounded(None, "no bounded tactical route established"),
        necessary_stock_deals=hard(0, "project itself does not require a stock deal"),
        existing_rehandling_obligation=hard(0, "no observed obligation assigned"),
        expected_additional_paid_moves=heuristic(0, "no additional move estimate"),
        mixed_suit_park_debt=heuristic(0, "no mixed park estimated"),
        stable_joins_to_break=heuristic(0, "no stable join break estimated"),
        workspace_creation_cost=heuristic(0, "no workspace creation estimate"),
        workspace_recovery_cost=heuristic(0, "no workspace recovery estimate"),
        destination_preparation_cost=heuristic(0, "no destination preparation estimate"),
        expected_future_rehandling=heuristic(0, "no future rehandling estimate"),
        timing_delay=heuristic(0, "no timing-delay estimate"),
    )


@dataclass(frozen=True)
class EconomicProjectBenefit:
    stable_same_suit_joins: EvidenceAmount
    same_suit_run_mass: EvidenceAmount
    campaign_must_dependencies: EvidenceAmount
    alternatives_retired: EvidenceAmount
    stock_receivers_prepared: EvidenceAmount
    mixed_boundaries_removed: EvidenceAmount
    workspace_created: EvidenceAmount
    workspace_recoverability: EvidenceAmount
    critical_reveal_advancement: EvidenceAmount
    foundation_readiness: EvidenceAmount
    future_paid_actions_avoided: EvidenceAmount

    @property
    def components(self) -> Tuple[Tuple[str, EvidenceAmount], ...]:
        return tuple(
            (name, getattr(self, name))
            for name in self.__dataclass_fields__
        )

    @property
    def structural_total(self) -> float:
        return sum(amount.ordering_value for _name, amount in self.components)


def empty_project_benefit() -> EconomicProjectBenefit:
    zero = lambda reason: heuristic(0, reason)
    return EconomicProjectBenefit(
        stable_same_suit_joins=zero("no stable join identified"),
        same_suit_run_mass=zero("no run-mass gain identified"),
        campaign_must_dependencies=zero("no mandatory dependency advanced"),
        alternatives_retired=zero("no alternative retired"),
        stock_receivers_prepared=zero("no receiver prepared"),
        mixed_boundaries_removed=zero("no mixed boundary removed"),
        workspace_created=zero("no workspace created"),
        workspace_recoverability=zero("no recoverability gain"),
        critical_reveal_advancement=zero("no critical reveal advanced"),
        foundation_readiness=zero("no foundation-readiness gain"),
        future_paid_actions_avoided=zero("no avoided action estimated"),
    )


@dataclass(frozen=True)
class EconomicProjectDebt:
    rework_actions_introduced: EvidenceAmount
    mixed_boundaries_created: EvidenceAmount
    stable_joins_broken: EvidenceAmount
    provisional_joins_created: EvidenceAmount
    workspace_consumed: EvidenceAmount
    projected_rehandling_cost: EvidenceAmount
    future_exit_route: str
    exit_route_bounded: bool
    proof_pruning_allowed: bool = False

    @property
    def ordering_total(self) -> float:
        return sum(
            amount.ordering_value
            for amount in (
                self.rework_actions_introduced,
                self.mixed_boundaries_created,
                self.stable_joins_broken,
                self.provisional_joins_created,
                self.workspace_consumed,
                self.projected_rehandling_cost,
            )
        )


def empty_project_debt() -> EconomicProjectDebt:
    return EconomicProjectDebt(
        rework_actions_introduced=heuristic(0, "no rework identified"),
        mixed_boundaries_created=hard(0, "no selected action creates a boundary"),
        stable_joins_broken=hard(0, "no selected action breaks a join"),
        provisional_joins_created=hard(0, "no provisional join selected"),
        workspace_consumed=hard(0, "no workspace action selected"),
        projected_rehandling_cost=heuristic(0, "no rehandling estimated"),
        future_exit_route="no temporary placement selected",
        exit_route_bounded=True,
    )


@dataclass(frozen=True)
class RevealValue:
    card: Card
    column: int
    reveal_depth: int
    classification: RevealValueClass
    information_gain: float
    interchangeable_copies: Tuple[str, ...]
    stock_copy_epochs: Tuple[int, ...]
    earliest_useful_epoch: int
    campaign_dependencies: Tuple[str, ...]
    mandatory_for_nearest_campaign: bool
    substitute_available: bool
    receiver_enabled: Tuple[str, ...]
    same_suit_join_enabled: Tuple[str, ...]
    workspace_consequence: str
    downstream_hidden_cards: int
    exposure_rehandling_estimate: float
    structural_value: float
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class ReworkInvestment:
    investment_cost: EvidenceAmount
    expected_structural_return: EvidenceAmount
    expected_move_saving: EvidenceAmount
    evidence: str
    net_economic_value: float
    confidence: str
    exit_route_bounded: bool
    worthwhile: bool
    proof_pruning_allowed: bool = False


def assess_rework_investment(
    *,
    investment_cost: EvidenceAmount,
    expected_structural_return: EvidenceAmount,
    expected_move_saving: EvidenceAmount,
    evidence: str,
    confidence: str,
    exit_route_bounded: bool,
) -> ReworkInvestment:
    """Assess temporary work as an investment, never as proof evidence."""
    net = (
        expected_structural_return.ordering_value
        + expected_move_saving.ordering_value
        - investment_cost.ordering_value
    )
    worthwhile = bool(exit_route_bounded and evidence.strip() and net > 0)
    return ReworkInvestment(
        investment_cost=investment_cost,
        expected_structural_return=expected_structural_return,
        expected_move_saving=expected_move_saving,
        evidence=evidence,
        net_economic_value=net,
        confidence=confidence,
        exit_route_bounded=exit_route_bounded,
        worthwhile=worthwhile,
    )


@dataclass(frozen=True)
class EconomicProjectAssessment:
    net_economic_value: float
    frontier_tier: EconomicFrontierTier
    confidence: str
    rationale: Tuple[str, ...]
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class EconomicProject:
    project_id: str
    kind: EconomicProjectKind
    description: str
    earliest_useful_epoch: int
    cost: EconomicProjectCost
    benefit: EconomicProjectBenefit
    debt: EconomicProjectDebt
    reveal_values: Tuple[RevealValue, ...]
    workspace_effect: str
    stock_interaction: str
    campaign_dependencies: Tuple[str, ...]
    rework_investment: Optional[ReworkInvestment]
    assessment: EconomicProjectAssessment
    action: Optional[Tuple[int, int, int]] = None


@dataclass(frozen=True)
class EconomicDominance:
    dominant_project_id: str
    dominated_project_id: str
    reasons: Tuple[str, ...]
    suppression_metadata_only: bool = True
    proof_pruning_allowed: bool = False


@dataclass(frozen=True)
class EconomicFrontier:
    ordered_projects: Tuple[EconomicProject, ...]
    tiers: Tuple[Tuple[EconomicFrontierTier, Tuple[EconomicProject, ...]], ...]
    dominance: Tuple[EconomicDominance, ...]
    retained_unexplained: Tuple[str, ...]
    proof_pruning_allowed: bool = False

    def projects_in(self, tier: EconomicFrontierTier) -> Tuple[EconomicProject, ...]:
        for item_tier, projects in self.tiers:
            if item_tier == tier:
                return projects
        return ()


@dataclass(frozen=True)
class EconomicStateFacts:
    current_epoch: int
    stock_remaining: int
    remaining_deals: int
    exact_next_stock_row: Tuple[Card, ...]
    face_down_cards: int
    foundations: int
    empty_columns: Tuple[int, ...]
    fully_open_columns: Tuple[int, ...]
    same_suit_joins: Tuple[str, ...]
    mixed_suit_boundaries: Tuple[str, ...]


@dataclass(frozen=True)
class EconomicAnalysisResult:
    facts: EconomicStateFacts
    campaign_portfolio: FoundationCampaignPortfolio
    buried_cards: Tuple[BuriedCardFact, ...]
    reveal_values: Tuple[RevealValue, ...]
    excavation_projects: Tuple[ExcavationProject, ...]
    lifecycle_liabilities: Tuple[str, ...]
    projects: Tuple[EconomicProject, ...]
    frontier: EconomicFrontier
    estimated_remaining_work: float
    proof_pruning_allowed: bool = False


def _replace_cost(cost: EconomicProjectCost, **changes: EvidenceAmount) -> EconomicProjectCost:
    return replace(cost, **changes)


def _replace_benefit(
    benefit: EconomicProjectBenefit, **changes: EvidenceAmount
) -> EconomicProjectBenefit:
    return replace(benefit, **changes)


def _replace_debt(debt: EconomicProjectDebt, **changes) -> EconomicProjectDebt:
    return replace(debt, **changes)


def _classify_tier(
    cost: EconomicProjectCost,
    benefit: EconomicProjectBenefit,
    debt: EconomicProjectDebt,
    net: float,
    rework: Optional[ReworkInvestment],
) -> EconomicFrontierTier:
    permanent = benefit.stable_same_suit_joins.ordering_value
    critical = (
        benefit.campaign_must_dependencies.ordering_value
        + benefit.critical_reveal_advancement.ordering_value
    )
    if (
        net > 0
        and debt.ordering_total <= 0
        and (
            permanent > 0
            or (critical >= 8 and cost.ordering_total <= 2)
        )
    ):
        return EconomicFrontierTier.STRUCTURALLY_DOMINANT
    if rework is not None and rework.worthwhile and net > 0:
        return EconomicFrontierTier.POSITIVE_INVESTMENT
    if net > 0 and benefit.structural_total > 0:
        return EconomicFrontierTier.POSITIVE_INVESTMENT
    if benefit.structural_total > 0:
        return EconomicFrontierTier.SPECULATIVE_DEFERRABLE
    return EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED


def make_economic_project(
    *,
    project_id: str,
    kind: EconomicProjectKind,
    description: str,
    earliest_useful_epoch: int,
    cost: Optional[EconomicProjectCost] = None,
    benefit: Optional[EconomicProjectBenefit] = None,
    debt: Optional[EconomicProjectDebt] = None,
    reveal_values: Sequence[RevealValue] = (),
    workspace_effect: str = "none identified",
    stock_interaction: str = "none identified",
    campaign_dependencies: Sequence[str] = (),
    rework_investment: Optional[ReworkInvestment] = None,
    confidence: str = "MEDIUM",
    rationale: Sequence[str] = (),
    action: Optional[Tuple[int, int, int]] = None,
) -> EconomicProject:
    """Public deterministic constructor used by diagnostics and fixtures."""
    cost = cost or empty_project_cost()
    benefit = benefit or empty_project_benefit()
    debt = debt or empty_project_debt()
    # Lifecycle debt is already represented by the labelled project-cost
    # fields.  ``debt`` preserves boundary/exit semantics and must not be
    # subtracted a second time.
    net = benefit.structural_total - cost.ordering_total
    if rework_investment is not None:
        # Rework return is already represented in the component breakdown; it
        # controls tier eligibility but is not added again.
        rationale = tuple(rationale) + (
            f"rework investment net={rework_investment.net_economic_value:.1f}",
        )
    tier = _classify_tier(cost, benefit, debt, net, rework_investment)
    return EconomicProject(
        project_id=project_id,
        kind=kind,
        description=description,
        earliest_useful_epoch=earliest_useful_epoch,
        cost=cost,
        benefit=benefit,
        debt=debt,
        reveal_values=tuple(reveal_values),
        workspace_effect=workspace_effect,
        stock_interaction=stock_interaction,
        campaign_dependencies=tuple(sorted(set(campaign_dependencies))),
        rework_investment=rework_investment,
        assessment=EconomicProjectAssessment(
            net_economic_value=net,
            frontier_tier=tier,
            confidence=confidence,
            rationale=tuple(rationale),
        ),
        action=action,
    )


def _campaign_source_matches(
    campaign: FoundationCampaign, fact: BuriedCardFact
) -> Tuple[bool, bool]:
    """Return (selected mandatory source, campaign rank dependency)."""
    if campaign.suit != fact.card.suit:
        return False, False
    try:
        need = campaign.rank_need(fact.card.rank)
    except KeyError:
        return False, False
    if need.chosen is None:
        return False, True
    chosen_here = bool(
        need.chosen.kind in (RankSourceKind.SHALLOW_TABLEAU, RankSourceKind.DEEP_TABLEAU)
        and need.chosen.column == fact.column
        and need.chosen.card == fact.card
    )
    return bool(need.must_excavate and chosen_here), True


def _copy_label(location: CardLocation) -> str:
    if location.kind == LocationKind.STOCK:
        return f"stock@epoch{location.stock_epoch}/c{(location.column or 0) + 1}"
    if location.column is not None:
        return f"{location.kind.value}@c{location.column + 1}/d{location.depth}"
    return location.kind.value


def analyze_reveal_values(
    state: SpiderState,
    buried: Sequence[BuriedCardFact],
    portfolio: FoundationCampaignPortfolio,
    *,
    locations: Optional[Sequence[CardLocation]] = None,
) -> Tuple[RevealValue, ...]:
    """Value every known buried card by consequences, with information=0."""
    locs = tuple(locations) if locations is not None else locate_all_cards(state)
    epoch = current_stock_epoch(state, 5)
    campaign_order = {campaign.label: i for i, campaign in enumerate(portfolio.campaigns)}
    values: List[RevealValue] = []
    for fact in buried:
        copies = tuple(
            loc
            for loc in locs
            if loc.card == fact.card
            and not (
                loc.kind == LocationKind.FACE_DOWN
                and loc.column == fact.column
                and loc.depth == fact.reveal_order
            )
            and loc.kind != LocationKind.FOUNDATION
        )
        stock_epochs = tuple(
            sorted(
                {
                    int(loc.stock_epoch)
                    for loc in copies
                    if loc.kind == LocationKind.STOCK and loc.stock_epoch is not None
                }
            )
        )
        tableau_substitutes = tuple(
            loc for loc in copies if loc.kind != LocationKind.STOCK
        )
        dependencies: List[str] = []
        mandatory_labels: List[str] = []
        for campaign in portfolio.campaigns:
            mandatory, relevant = _campaign_source_matches(campaign, fact)
            if relevant:
                dependencies.append(campaign.label)
            if mandatory:
                mandatory_labels.append(campaign.label)

        nearest_mandatory = bool(
            mandatory_labels
            and min(campaign_order[label] for label in mandatory_labels) <= 1
        )
        stock_substitute = bool(stock_epochs)
        tableau_substitute = bool(tableau_substitutes)
        relevant_targets = tuple(
            campaign.target_removal_epoch
            for campaign in portfolio.campaigns
            if campaign.label in dependencies
            and campaign.target_removal_epoch is not None
        )
        stock_substitute_in_time = bool(
            stock_epochs
            and (
                not relevant_targets
                or min(stock_epochs) <= min(relevant_targets)
            )
        )
        earliest = max(epoch, fact.earliest_useful_epoch)
        receiver = tuple(
            sorted(
                {
                    f"{loc.card}@c{(loc.column or 0) + 1}"
                    for loc in fact.dest_prereqs
                    if loc.kind == LocationKind.FACE_UP_TOP
                }
            )
        )
        downstream = max(0, len(state.columns[fact.column].face_down) - fact.reveal_order - 1)
        deepest = fact.reveal_order == len(state.columns[fact.column].face_down) - 1

        structural = 0.0
        reasons: List[str] = ["perfect information: revealing the card adds no knowledge"]
        if mandatory_labels:
            structural += 14.0 if nearest_mandatory else 8.0
            reasons.append("selected mandatory source for " + ", ".join(mandatory_labels))
        if fact.ss_join:
            structural += 6.0 + 2.0 * len(fact.ss_join)
            reasons.append("enables known same-suit geometry")
        if receiver:
            structural += 4.0
            reasons.append("has a currently exposed receiver")
        if downstream:
            structural += min(6.0, 1.5 * downstream)
            reasons.append(f"unlocks a chain with {downstream} deeper hidden card(s)")
        if deepest:
            structural += 3.0
            reasons.append("advances the column toward fully-open workspace")
        if stock_substitute:
            structural -= 5.0
            reasons.append("an interchangeable stock copy reduces current urgency")
        elif tableau_substitute:
            structural -= 3.0
            reasons.append("an interchangeable tableau copy reduces current urgency")
        if earliest > epoch + 1:
            structural -= 3.0
            reasons.append("known use belongs to a later stock epoch")
        structural = max(0.0, structural)

        if stock_substitute_in_time:
            classification = RevealValueClass.REPLACEABLE_BY_STOCK
        elif nearest_mandatory and earliest <= epoch:
            classification = RevealValueClass.CRITICAL_NOW
        elif nearest_mandatory and earliest == epoch + 1:
            classification = RevealValueClass.REQUIRED_BEFORE_NEXT_DEAL
        elif tableau_substitute and not nearest_mandatory:
            classification = RevealValueClass.REPLACEABLE_BY_DUPLICATE
        elif earliest > epoch + 1:
            classification = RevealValueClass.LATER_EPOCH
        elif structural >= 12:
            classification = RevealValueClass.HIGH_VALUE_CURRENT_EPOCH
        elif structural >= 5:
            classification = RevealValueClass.USEFUL_BUT_DEFERRABLE
        else:
            classification = RevealValueClass.LOW_CURRENT_VALUE

        values.append(
            RevealValue(
                card=fact.card,
                column=fact.column,
                reveal_depth=fact.min_reveals,
                classification=classification,
                information_gain=0.0,
                interchangeable_copies=tuple(_copy_label(loc) for loc in copies),
                stock_copy_epochs=stock_epochs,
                earliest_useful_epoch=earliest,
                campaign_dependencies=tuple(dependencies),
                mandatory_for_nearest_campaign=nearest_mandatory,
                substitute_available=stock_substitute or tableau_substitute,
                receiver_enabled=receiver,
                same_suit_join_enabled=fact.ss_join,
                workspace_consequence=(
                    "exposing this deepest known card advances a fully-open column"
                    if deepest
                    else "no immediate workspace creation"
                ),
                downstream_hidden_cards=downstream,
                exposure_rehandling_estimate=float(max(0, fact.min_reveals - 1)),
                structural_value=structural,
                reasons=tuple(reasons),
            )
        )
    return tuple(
        sorted(
            values,
            key=lambda value: (
                -value.structural_value,
                value.earliest_useful_epoch,
                value.reveal_depth,
                value.column,
                value.card.suit,
                value.card.rank,
            ),
        )
    )


def _structure_facts(state: SpiderState) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    joins: List[str] = []
    mixed: List[str] = []
    for column, pile in enumerate(state.columns):
        for lower, upper in zip(pile.face_up, pile.face_up[1:]):
            label = f"{lower}-{upper}@c{column + 1}"
            if lower.suit == upper.suit and lower.rank - 1 == upper.rank:
                joins.append(label)
            elif lower.suit != upper.suit:
                mixed.append(label)
    return tuple(joins), tuple(mixed)


def _landing_kind(top: Optional[Card], incoming: Card) -> LandingKind:
    if top is None:
        return LandingKind.EMPTY_LANDING
    if top.rank - 1 == incoming.rank:
        return (
            LandingKind.SAME_SUIT_CONNECT
            if top.suit == incoming.suit
            else LandingKind.MIXED_RANK_CONNECT
        )
    return LandingKind.NON_CONNECTING


def _project_from_excavation(
    state: SpiderState,
    excavation: ExcavationProject,
    reveals: Sequence[RevealValue],
    epoch: int,
) -> EconomicProject:
    relevant = tuple(value for value in reveals if value.column == excavation.column)
    reveal_total = sum(value.structural_value for value in relevant)
    critical = sum(
        1
        for value in relevant
        if value.classification
        in (RevealValueClass.CRITICAL_NOW, RevealValueClass.REQUIRED_BEFORE_NEXT_DEAL)
    )
    cost = _replace_cost(
        empty_project_cost(),
        expected_additional_paid_moves=heuristic(
            float(excavation.approx_open_cost),
            "bounded dependency analysis has not independently proved this excavation estimate",
        ),
        mixed_suit_park_debt=heuristic(
            1.0 if excavation.shortage != "none" else 0.0,
            f"receiver shortage={excavation.shortage}",
        ),
        expected_future_rehandling=heuristic(
            max(0.0, float(excavation.approx_advance_cost - 1)),
            "estimated blocker separation/rejoin work",
        ),
    )
    benefit = _replace_benefit(
        empty_project_benefit(),
        campaign_must_dependencies=heuristic(
            10.0 * critical, f"{critical} current/next-deal critical reveal(s)"
        ),
        critical_reveal_advancement=heuristic(
            reveal_total,
            "sum of consequence-only reveal values in the known prefix",
        ),
        workspace_created=heuristic(
            5.0 if excavation.latent_workspace else 0.0,
            "fully excavating the column may create reusable open structure",
        ),
        foundation_readiness=heuristic(
            3.0 * len({d for value in relevant for d in value.campaign_dependencies}),
            "campaign dependencies touched by the prefix",
        ),
    )
    debt_value = cost.mixed_suit_park_debt.ordering_value + cost.expected_future_rehandling.ordering_value
    debt = _replace_debt(
        empty_project_debt(),
        rework_actions_introduced=heuristic(debt_value, "estimated prefix handling"),
        projected_rehandling_cost=heuristic(debt_value, "estimated future separation/rejoin"),
        future_exit_route=(
            "bounded only after a concrete tactical realizer establishes receivers"
        ),
        exit_route_bounded=False,
    )
    rework = None
    if debt_value > 0:
        rework = assess_rework_investment(
            investment_cost=heuristic(
                cost.expected_additional_paid_moves.ordering_value + debt_value,
                "estimated excavation and rehandling investment",
            ),
            expected_structural_return=heuristic(
                benefit.structural_total,
                "known dependency/structure consequences, valued heuristically",
            ),
            expected_move_saving=heuristic(
                1.0 if excavation.latent_workspace else 0.0,
                "possible later workspace saving",
            ),
            evidence="bounded dependency chain; tactical exit remains prospective",
            confidence="MEDIUM" if critical else "LOW",
            exit_route_bounded=False,
        )
    earliest = min((value.earliest_useful_epoch for value in relevant), default=epoch)
    return make_economic_project(
        project_id=f"excavate-c{excavation.column + 1}",
        kind=EconomicProjectKind.EXCAVATE_COLUMN_PREFIX,
        description=f"excavate known prefix of column {excavation.column + 1}",
        earliest_useful_epoch=earliest,
        cost=cost,
        benefit=benefit,
        debt=debt,
        reveal_values=relevant,
        workspace_effect=(
            "latent fully-open workspace if the column project completes"
            if excavation.latent_workspace
            else "no reliable workspace gain"
        ),
        stock_interaction=(
            "some sources have known stock substitutes"
            if any(value.stock_copy_epochs for value in relevant)
            else "no stock substitution identified"
        ),
        campaign_dependencies=tuple(
            dependency for value in relevant for dependency in value.campaign_dependencies
        ),
        rework_investment=rework,
        confidence="MEDIUM" if critical else "LOW",
        rationale=excavation.reasons,
    )


def _project_from_lifecycle(
    assessment: MoveLifecycleAssessment, epoch: int
) -> EconomicProject:
    stable = len(assessment.same_suit_joins_created)
    mixed_removed = len(assessment.mixed_suit_boundaries_removed)
    workspace = assessment.placement_class == PlacementClass.WORKSPACE_PARK
    benefit = _replace_benefit(
        empty_project_benefit(),
        stable_same_suit_joins=hard(5.0 * stable, "legal action creates stable same-suit boundary"),
        same_suit_run_mass=hard(
            float(assessment.action[2]) if stable else 0.0,
            "cards carried by the legal same-suit block",
        ),
        mixed_boundaries_removed=hard(
            3.0 * mixed_removed, "legal action removes an observed mixed boundary"
        ),
        workspace_recoverability=heuristic(
            1.0 if workspace and assessment.exit_route_bounded else 0.0,
            "whole-column workspace relocation has a known reversal",
        ),
    )
    cost = _replace_cost(
        empty_project_cost(),
        immediate_paid_cost=hard(
            float(assessment.immediate_cost), "corrected cost of the legal tableau move"
        ),
        existing_rehandling_obligation=hard(
            float(len(assessment.mixed_suit_boundaries_created)),
            "mixed boundaries created by the selected legal action",
        ),
        expected_future_rehandling=heuristic(
            assessment.estimated_rehandling_cost,
            "ordering-only move lifecycle estimate",
        ),
    )
    debt = EconomicProjectDebt(
        rework_actions_introduced=heuristic(
            assessment.estimated_rehandling_cost,
            "ordering-only lifecycle debt",
        ),
        mixed_boundaries_created=hard(
            float(len(assessment.mixed_suit_boundaries_created)),
            "observed boundary change for legal action",
        ),
        stable_joins_broken=hard(
            float(len(assessment.same_suit_joins_broken)),
            "observed boundary change for legal action",
        ),
        provisional_joins_created=hard(
            1.0 if assessment.placement_class == PlacementClass.PROVISIONAL_SAME_SUIT_JOIN else 0.0,
            "move lifecycle classification",
        ),
        workspace_consumed=hard(
            1.0 if workspace else 0.0, "destination is currently empty"
        ),
        projected_rehandling_cost=heuristic(
            assessment.estimated_rehandling_cost,
            "ordering-only lifecycle estimate",
        ),
        future_exit_route=assessment.future_exit_route,
        exit_route_bounded=assessment.exit_route_bounded,
    )
    kind = {
        PlacementClass.STABLE_SAME_SUIT_JOIN: EconomicProjectKind.PERMANENT_JOIN,
        PlacementClass.PROVISIONAL_SAME_SUIT_JOIN: EconomicProjectKind.ASSEMBLE_BAND,
        PlacementClass.MIXED_SUIT_PARK: EconomicProjectKind.TEMPORARY_REWORK,
        PlacementClass.WORKSPACE_PARK: EconomicProjectKind.RECOVER_WORKSPACE,
    }[assessment.placement_class]
    src, dst, k = assessment.action
    rework = None
    if assessment.estimated_rehandling_cost > 0:
        rework = assess_rework_investment(
            investment_cost=heuristic(
                assessment.immediate_cost + assessment.estimated_rehandling_cost,
                "immediate action plus lifecycle rehandling estimate",
            ),
            expected_structural_return=heuristic(
                benefit.structural_total, "local boundary improvement"
            ),
            expected_move_saving=heuristic(0, "no bounded downstream saving identified"),
            evidence="local lifecycle only",
            confidence="LOW",
            exit_route_bounded=assessment.exit_route_bounded,
        )
    return make_economic_project(
        project_id=f"move-c{src + 1}-c{dst + 1}-k{k}",
        kind=kind,
        description=(
            f"{assessment.placement_class.value}: c{src + 1}->c{dst + 1} k={k}"
        ),
        earliest_useful_epoch=epoch,
        cost=cost,
        benefit=benefit,
        debt=debt,
        workspace_effect=(
            "uses an empty column with the recorded exit route" if workspace else "none"
        ),
        stock_interaction="not established by this local move",
        rework_investment=rework,
        confidence="HIGH" if kind == EconomicProjectKind.PERMANENT_JOIN else "LOW",
        rationale=(
            f"same-suit joins created={assessment.same_suit_joins_created}",
            f"mixed boundaries created={assessment.mixed_suit_boundaries_created}",
            f"future exit={assessment.future_exit_route}",
        ),
        action=assessment.action,
    )


def _campaign_project(campaign: FoundationCampaign) -> EconomicProject:
    must_count = sum(1 for need in campaign.rank_needs if need.must_excavate)
    benefit = _replace_benefit(
        empty_project_benefit(),
        campaign_must_dependencies=heuristic(
            5.0 * must_count, f"campaign schedule contains {must_count} MUST source(s)"
        ),
        same_suit_run_mass=hard(
            float(sum(fragment.length for fragment in campaign.current_same_suit_fragments)),
            "observed current same-suit fragment mass",
        ),
        foundation_readiness=heuristic(
            max(0.0, campaign.expected_structural_payoff),
            "campaign structural payoff estimate",
        ),
    )
    cost = _replace_cost(
        empty_project_cost(),
        expected_additional_paid_moves=heuristic(
            campaign.estimated_campaign_cost, "campaign schedule estimate"
        ),
        necessary_stock_deals=hard(
            float(max(0, (campaign.target_removal_epoch or campaign.current_epoch) - campaign.current_epoch)),
            "known stock epochs before the scheduled target",
        ),
        workspace_creation_cost=heuristic(
            float(campaign.space_requirement), "campaign workspace requirement proxy"
        ),
        destination_preparation_cost=heuristic(
            float(len(campaign.pre_deal_receiver_requirements)),
            "exact-row receiver requirements in the campaign schedule",
        ),
    )
    return make_economic_project(
        project_id=f"campaign-{campaign.label.lower()}",
        kind=EconomicProjectKind.FOUNDATION_CAMPAIGN_STEP,
        description=f"advance bounded {campaign.label} foundation campaign",
        earliest_useful_epoch=campaign.current_epoch,
        cost=cost,
        benefit=benefit,
        debt=empty_project_debt(),
        workspace_effect=campaign.space_plan.enabled_action,
        stock_interaction=(
            f"target epoch={campaign.target_removal_epoch}; "
            f"receiver requirements={len(campaign.pre_deal_receiver_requirements)}"
        ),
        campaign_dependencies=(campaign.label,),
        confidence=campaign.confidence,
        rationale=campaign.rationale,
    )


def _stock_receiver_projects(
    state: SpiderState, epoch: int
) -> Tuple[EconomicProject, ...]:
    row = tuple(next_stock_row(state) or ())
    projects: List[EconomicProject] = []
    for column, incoming in enumerate(row):
        top = state.columns[column].top()
        landing = _landing_kind(top, incoming)
        if landing == LandingKind.SAME_SUIT_CONNECT:
            continue
        same_suit_receivers = [
            (i, pile.top())
            for i, pile in enumerate(state.columns)
            if i != column
            and pile.top() is not None
            and pile.top().suit == incoming.suit
            and pile.top().rank - 1 == incoming.rank
        ]
        if not same_suit_receivers:
            continue
        receiver_column, receiver = same_suit_receivers[0]
        benefit = _replace_benefit(
            empty_project_benefit(),
            stock_receivers_prepared=hard(
                6.0, "exact next stock card has a visible same-suit receiver"
            ),
        )
        cost = _replace_cost(
            empty_project_cost(),
            destination_preparation_cost=heuristic(
                1.0,
                "receiver preparation action has not been bounded by a tactical realizer",
            ),
            timing_delay=hard(0, "receiver is useful before the exact next deal"),
        )
        projects.append(
            make_economic_project(
                project_id=f"receiver-c{column + 1}-{incoming}",
                kind=EconomicProjectKind.PREPARE_STOCK_RECEIVER,
                description=(
                    f"prepare exact next-row receiver for {incoming} landing in c{column + 1}"
                ),
                earliest_useful_epoch=epoch,
                cost=cost,
                benefit=benefit,
                workspace_effect="must preserve sufficient tableau mobility before dealing",
                stock_interaction=(
                    f"exact {incoming} can join {receiver} at c{receiver_column + 1}"
                ),
                confidence="MEDIUM",
                rationale=(f"current landing={landing.value}",),
            )
        )
    return tuple(projects)


def economic_project_dominates(
    candidate: EconomicProject, alternative: EconomicProject
) -> Optional[EconomicDominance]:
    """Conservative heuristic dominance; never proof pruning or deletion."""
    if candidate.project_id == alternative.project_id:
        return None
    no_worse = bool(
        candidate.cost.immediate_paid_cost.ordering_value
        <= alternative.cost.immediate_paid_cost.ordering_value
        and sum(value.structural_value for value in candidate.reveal_values)
        >= sum(value.structural_value for value in alternative.reveal_values)
        and candidate.benefit.workspace_created.ordering_value
        >= alternative.benefit.workspace_created.ordering_value
        and candidate.benefit.stock_receivers_prepared.ordering_value
        >= alternative.benefit.stock_receivers_prepared.ordering_value
    )
    improvements: List[str] = []
    candidate_permanent = (
        candidate.benefit.stable_same_suit_joins.ordering_value
        if candidate.benefit.stable_same_suit_joins.evidence
        != EvidenceLevel.HEURISTIC_ESTIMATE
        else 0.0
    )
    alternative_permanent = (
        alternative.benefit.stable_same_suit_joins.ordering_value
        if alternative.benefit.stable_same_suit_joins.evidence
        != EvidenceLevel.HEURISTIC_ESTIMATE
        else 0.0
    )
    if candidate_permanent > alternative_permanent:
        improvements.append("more stable permanent structure")
    if candidate.debt.mixed_boundaries_created.ordering_value < alternative.debt.mixed_boundaries_created.ordering_value:
        improvements.append("less mixed-suit debt")
    if candidate.debt.projected_rehandling_cost.ordering_value < alternative.debt.projected_rehandling_cost.ordering_value:
        improvements.append("lower projected rehandling")
    if candidate.benefit.critical_reveal_advancement.ordering_value > alternative.benefit.critical_reveal_advancement.ordering_value:
        improvements.append("more critical-path advancement")
    if not no_worse or not improvements:
        return None
    return EconomicDominance(
        dominant_project_id=candidate.project_id,
        dominated_project_id=alternative.project_id,
        reasons=tuple(improvements),
    )


def build_economic_frontier(projects: Sequence[EconomicProject]) -> EconomicFrontier:
    """Order every project and attach non-pruning dominance metadata."""
    ordered = tuple(
        sorted(
            projects,
            key=lambda project: (
                int(project.assessment.frontier_tier),
                -project.assessment.net_economic_value,
                project.cost.ordering_total,
                project.earliest_useful_epoch,
                project.project_id,
            ),
        )
    )
    dominance: List[EconomicDominance] = []
    for i, candidate in enumerate(ordered):
        for alternative in ordered[i + 1 :]:
            relation = economic_project_dominates(candidate, alternative)
            if relation is not None:
                dominance.append(relation)
    tiers = tuple(
        (tier, tuple(project for project in ordered if project.assessment.frontier_tier == tier))
        for tier in EconomicFrontierTier
    )
    unexplained = tuple(
        project.project_id
        for project in ordered
        if project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
    )
    return EconomicFrontier(
        ordered_projects=ordered,
        tiers=tiers,
        dominance=tuple(dominance),
        retained_unexplained=unexplained,
    )


def estimate_remaining_economic_work(
    projects: Sequence[EconomicProject], remaining_deals: int
) -> float:
    """Ordering-only estimate, intentionally unrelated to proof pruning."""
    campaign_costs = [
        project.cost.expected_additional_paid_moves.ordering_value
        for project in projects
        if project.kind == EconomicProjectKind.FOUNDATION_CAMPAIGN_STEP
    ]
    campaign_floor = min(campaign_costs) if campaign_costs else 0.0
    liability = sum(
        project.debt.projected_rehandling_cost.ordering_value
        for project in projects
        if project.kind in (EconomicProjectKind.TEMPORARY_REWORK, EconomicProjectKind.RECOVER_WORKSPACE)
    )
    critical = max(
        (
            project.cost.expected_additional_paid_moves.ordering_value
            for project in projects
            if project.reveal_values
            and any(value.mandatory_for_nearest_campaign for value in project.reveal_values)
        ),
        default=0.0,
    )
    return float(remaining_deals + campaign_floor + critical + min(8.0, liability))


def analyze_economic_projects(
    state: SpiderState,
    *,
    cards: Sequence[Card],
    campaign_portfolio: Optional[FoundationCampaignPortfolio] = None,
    campaign_source_combination_limit: Optional[int] = None,
) -> EconomicAnalysisResult:
    """Build a static/bounded whole-tableau economic portfolio.

    The supplied state is never mutated and no returned project is selected or
    executed.  Existing campaign helpers may simulate bounded alternatives on
    clones, but the machine checkpoint itself remains at its current epoch.
    """
    before_stock = tuple(state.stock)
    before_foundations = tuple(tuple(sequence) for sequence in state.foundations)
    epoch = current_stock_epoch(state, 5)
    portfolio = campaign_portfolio or analyze_foundation_campaigns(
        state,
        cards=cards,
        max_source_combinations=campaign_source_combination_limit,
    )
    locations = locate_all_cards(state)
    buried = analyze_buried_cards(state, cards=cards, locs=locations)
    reveal_values = analyze_reveal_values(
        state, buried, portfolio, locations=locations
    )
    excavation = analyze_excavation_projects(state, buried)
    joins, mixed = _structure_facts(state)
    empties = tuple(i for i, pile in enumerate(state.columns) if pile.is_empty())
    fully_open = tuple(
        i for i, pile in enumerate(state.columns) if pile.face_up and not pile.face_down
    )
    facts = EconomicStateFacts(
        current_epoch=epoch,
        stock_remaining=len(state.stock),
        remaining_deals=len(state.stock) // 10,
        exact_next_stock_row=tuple(next_stock_row(state) or ()),
        face_down_cards=sum(len(pile.face_down) for pile in state.columns),
        foundations=len(state.foundations),
        empty_columns=empties,
        fully_open_columns=fully_open,
        same_suit_joins=joins,
        mixed_suit_boundaries=mixed,
    )

    projects: List[EconomicProject] = [
        _project_from_excavation(state, item, reveal_values, epoch)
        for item in excavation
        if item.face_down > 0
    ]
    projects.extend(_campaign_project(campaign) for campaign in portfolio.campaigns)
    projects.extend(_stock_receiver_projects(state, epoch))

    # Whole legal move set is inspected, but keep only distinct representative
    # structure classes so diagnostics remain readable.
    lifecycle_seen: Dict[PlacementClass, int] = {}
    for action in sorted(state.enumerate_moves()):
        assessment = assess_tableau_move(state, action, discover_exit=False)
        count = lifecycle_seen.get(assessment.placement_class, 0)
        limit = 8 if assessment.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN else 3
        if count >= limit:
            continue
        lifecycle_seen[assessment.placement_class] = count + 1
        projects.append(_project_from_lifecycle(assessment, epoch))

    frontier = build_economic_frontier(projects)
    estimated = estimate_remaining_economic_work(projects, facts.remaining_deals)
    liabilities = tuple(
        f"mixed boundary {label}: future same-suit separation/rejoin may be required"
        for label in mixed
    )
    # The analysis itself must not advance the supplied state.
    if tuple(state.stock) != before_stock or tuple(tuple(s) for s in state.foundations) != before_foundations:
        raise AssertionError("economic analysis mutated the supplied state")
    return EconomicAnalysisResult(
        facts=facts,
        campaign_portfolio=portfolio,
        buried_cards=buried,
        reveal_values=reveal_values,
        excavation_projects=excavation,
        lifecycle_liabilities=liabilities,
        projects=tuple(projects),
        frontier=frontier,
        estimated_remaining_work=estimated,
    )
