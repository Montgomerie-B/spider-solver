"""Foundation-directed adapter for the human-strategy controller.

This module does not plan foundations by itself. It asks the existing
feasibility and campaign analysers for a ranked next foundation, turns the
campaign's obligations into a short prerequisite list, and asks the existing
objective realiser for a legal path. Estimates order work. They do not prune.
A tactical timeout does not retire the campaign.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, format_action, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignObligationKind,
    _objective_for_prefix,
    campaign_obligations_for_next_epoch,
    obligation_is_satisfied,
)
from spider.planner.foundation_feasibility import (
    FoundationFeasibilityAnalysis,
    analyze_foundation_feasibility,
)
from spider.planner.objective_realizer import RealizationMode, RealizationStatus, realize_objective
from spider.planner.stock_reception import next_stock_row
from spider.research_actions import all_legal_actions, apply_action, face_down_count
from spider.state_identity import canonical_state_key

from .portfolio import Candidate
from .profiles import Profile

_OPERATIONAL = {"ready_now", "excavation_led", "assembly_led", "stock_gated"}
_CONFIDENCE_PENALTY = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}


@dataclass(frozen=True)
class FoundationView:
    """One suit's next foundation, with the three availability tiers separated."""

    suit: str
    copy_index: int
    label: str
    target_epoch: Optional[int]
    current_epoch: int
    earliest_epoch: Optional[int]
    other_copy_earliest: Optional[int]
    estimated_cost: float
    readiness: str
    confidence: str
    theoretically_available: bool
    operationally_attainable: bool
    economically_attractive: bool
    face_up: int
    face_down: int
    stock_count: int
    burial: int
    longest_fragment: int
    reasons: Tuple[str, ...]


@dataclass
class Prerequisite:
    prerequisite_id: str
    kind: str
    description: str
    rank: Optional[int]
    column: Optional[int]
    source_keys: Tuple[str, ...]
    estimated_cost: float
    mandatory_before_deal: bool
    achieved: bool
    objective: object = None


@dataclass
class FoundationAgenda:
    view: FoundationView
    alternatives: Tuple[FoundationView, ...]
    prerequisites: Tuple[Prerequisite, ...]
    protected_fragments: Tuple[Tuple[Card, ...], ...]
    campaign_cost: float
    target_epoch: Optional[int]
    current_epoch: int
    stock_len: int
    reasons: Tuple[str, ...]


@dataclass
class FoundationProposal:
    candidate: Optional[Candidate]
    reason: str
    events: Tuple[str, ...]
    timeout: bool
    block_deal: bool
    agenda: Optional[FoundationAgenda]
    public: dict = field(default_factory=dict)


def schedule_objective(campaign: FoundationCampaign) -> float:
    """The campaign module's own risk-adjusted schedule. Heuristic only."""

    target = campaign.target_removal_epoch if campaign.target_removal_epoch is not None else 99
    penalty = _CONFIDENCE_PENALTY.get(campaign.confidence, 6.0)
    return float(
        campaign.estimated_campaign_cost
        + 6.0 * max(0, target - campaign.current_epoch)
        + penalty
    )


def rank_foundations(
    state: SpiderState,
    cards: Sequence[Card],
    *,
    cache: Optional[dict] = None,
    max_source_combinations: int = 4,
) -> Tuple[FoundationView, ...]:
    """Rank the next foundation of every suit.

    Both physical copies are visible: the next ordinal is the candidate, and
    the other ordinal's earliest stock epoch is reported beside it. Copies are
    source alternatives inside that next foundation. A later ordinal is not a
    second rival that can be built from the same cards.
    """

    feasibility, portfolio = load_portfolio(
        state, cards, cache if cache is not None else {}, max_source_combinations
    )
    return views_from_portfolio(feasibility, portfolio)


def load_portfolio(
    state: SpiderState,
    cards: Sequence[Card],
    cache: dict,
    max_source_combinations: int = 4,
) -> Tuple[FoundationFeasibilityAnalysis, FoundationCampaignPortfolio]:
    key = canonical_state_key(state)
    cached = cache.get(key)
    if cached is not None:
        return cached
    feasibility = analyze_foundation_feasibility(tuple(cards), state)
    portfolio = analyze_foundation_campaigns(
        state,
        cards=tuple(cards),
        foundation_analysis=feasibility,
        max_source_combinations=max_source_combinations,
    )
    cache[key] = (feasibility, portfolio)
    return feasibility, portfolio


def views_from_portfolio(
    feasibility: FoundationFeasibilityAnalysis,
    portfolio: FoundationCampaignPortfolio,
) -> Tuple[FoundationView, ...]:
    primary = portfolio.primary.label if portfolio.primary is not None else ""
    views: List[FoundationView] = []
    for campaign in portfolio.campaigns:
        candidate = _candidate(feasibility, campaign.suit, campaign.copy_index)
        other_copy = 1 if campaign.copy_index == 2 else 2
        try:
            other = feasibility.availability_for(campaign.suit, other_copy)
            other_epoch = other.earliest_epoch
        except KeyError:
            other_epoch = None
        theoretical = bool(candidate is not None and candidate.theoretically_available)
        readiness = campaign.readiness.value
        operational = readiness in _OPERATIONAL and not campaign.blockers
        reasons = _view_reasons(campaign, candidate, other_copy, other_epoch, theoretical, operational)
        views.append(
            FoundationView(
                suit=campaign.suit,
                copy_index=campaign.copy_index,
                label=campaign.label,
                target_epoch=campaign.target_removal_epoch,
                current_epoch=campaign.current_epoch,
                earliest_epoch=None if candidate is None else candidate.earliest_epoch,
                other_copy_earliest=other_epoch,
                estimated_cost=float(campaign.estimated_campaign_cost),
                readiness=readiness,
                confidence=campaign.confidence,
                theoretically_available=theoretical,
                operationally_attainable=operational,
                economically_attractive=campaign.label == primary,
                face_up=0 if candidate is None else candidate.face_up_count,
                face_down=0 if candidate is None else candidate.face_down_count,
                stock_count=0 if candidate is None else candidate.stock_remaining_count,
                burial=0 if candidate is None else candidate.total_burial_depth,
                longest_fragment=campaign.current_same_suit_fragments
                and max(item.length for item in campaign.current_same_suit_fragments)
                or 0,
                reasons=reasons,
            )
        )
    return tuple(views)


def chosen_source_keys(campaign: FoundationCampaign) -> Tuple[str, ...]:
    return tuple(need.chosen.source_key for need in campaign.rank_needs if need.chosen is not None)


def propose_foundation_step(
    state: SpiderState,
    cards: Sequence[Card],
    profile: Profile,
    time_left: float,
    g: int,
    *,
    cache: dict,
    lock: dict,
    blocked: Sequence[str] = (),
) -> FoundationProposal:
    """Choose the next legal step of the locked foundation campaign.

    ``lock`` remembers the suit across moves so a slightly cheaper one-ply
    action cannot throw the campaign away. It is cleared by the caller when
    a foundation is removed.
    """

    refused = set(blocked)
    try:
        feasibility, portfolio = load_portfolio(state, cards, cache)
    except (ValueError, KeyError) as exc:
        return FoundationProposal(
            None,
            "",
            (f"foundation: analysis unavailable ({exc})",),
            False,
            False,
            None,
        )
    if portfolio.primary is None:
        return FoundationProposal(None, "", ("foundation: no remaining suit",), False, False, None)

    events: List[str] = []
    campaign = _locked_campaign(portfolio, lock, events)
    if campaign is None:
        return FoundationProposal(None, "", tuple(events), False, False, None)
    view = _view_for(views_from_portfolio(feasibility, portfolio), campaign.label)
    if view is None:
        view = views_from_portfolio(feasibility, portfolio)[0]
    previous_stock = lock.get("stock_len")
    fd_now = face_down_count(state)
    state_key = canonical_state_key(state)
    if previous_stock is not None and len(state.stock) < previous_stock:
        events.append("replan: foundation campaign after stock")
        # A deal that buries cards without a reveal does not earn an immediate
        # second row. Tableau work between rows clears that mark.
        if fd_now >= lock.get("fd", fd_now) and lock.get("moves_since_deal", 0) == 0:
            lock["barren_deals"] = lock.get("barren_deals", 0) + 1
        else:
            lock["barren_deals"] = 0
        lock["moves_since_deal"] = 0
    elif lock.get("fd") is not None and fd_now < lock["fd"]:
        lock["barren_deals"] = 0
        if lock.get("seen_key") != state_key:
            lock["moves_since_deal"] = lock.get("moves_since_deal", 0) + 1
    elif previous_stock is not None and lock.get("seen_key") != state_key:
        lock["moves_since_deal"] = lock.get("moves_since_deal", 0) + 1
    lock["seen_key"] = state_key
    lock["fd"] = fd_now
    lock["stock_len"] = len(state.stock)
    lock["label"] = campaign.label
    agenda = _agenda(state, cards, campaign, view, portfolio)
    if not lock.get("announced"):
        rival = agenda.alternatives[0].label if agenda.alternatives else "none"
        events.append(
            f"foundation: selected {campaign.label} over {rival}; "
            f"target epoch {campaign.target_removal_epoch}; "
            f"estimated cost {campaign.estimated_campaign_cost:.1f}"
        )
        lock["announced"] = campaign.label
    elif lock.get("announced") == campaign.label:
        events.append(f"foundation: continue {campaign.label}")
    else:
        events.append(f"foundation: selected {campaign.label}")
        lock["announced"] = campaign.label

    finishing = _completion_move(state)
    if finishing is not None and f"FOUNDATION:{campaign.label}" not in refused:
        candidate = _make_candidate(
            g,
            f"FOUNDATION:{campaign.label}",
            "FOUNDATION",
            (finishing,),
            hold=False,
            benefit=13.0,
            evidence=_evidence(campaign, agenda, "fact: a legal move completes the selected foundation"),
            purpose="remove the selected foundation",
        )
        return _proposal(candidate, "selected: legal foundation removal", events, False, agenda)

    failures: Dict[str, int] = lock.setdefault("failures", {})
    timeouts: Dict[str, int] = lock.setdefault("timeouts", {})
    missed_open = False
    for item in agenda.prerequisites:
        if item.achieved or item.kind != "excavate" or not item.mandatory_before_deal:
            continue
        if item.prerequisite_id in refused or failures.get(item.prerequisite_id, 0) >= 3:
            # A bounded miss is not permission to deal. Keep peeling this
            # column when a legal reveal remains; otherwise the deal waits.
            noted = lock.setdefault("suspended_notes", set())
            if item.prerequisite_id not in noted:
                events.append(
                    f"foundation: suspend {item.prerequisite_id}; campaign {campaign.label} stays open"
                )
                noted.add(item.prerequisite_id)
            if item.prerequisite_id not in refused:
                peel = _column_reveal(state, item.column, agenda.protected_fragments)
                if peel is not None:
                    return _proposal(
                        _make_candidate(
                            g,
                            item.prerequisite_id,
                            "REVEAL",
                            (peel,),
                            hold=False,
                            benefit=2.0,
                            evidence=_evidence(
                                campaign,
                                agenda,
                                "fact: search missed; one legal reveal of the required column remains",
                            ),
                            purpose="expose a card required by the foundation",
                        ),
                        "selected: foundation prerequisite reveal",
                        events,
                        False,
                        agenda,
                    )
            continue
        if time_left < 0.05:
            timeouts[item.prerequisite_id] = timeouts.get(item.prerequisite_id, 0) + 1
            events.append(
                f"foundation: tactical timeout does not retire {campaign.label}"
            )
            peel = _column_reveal(state, item.column, agenda.protected_fragments)
            if peel is not None:
                return _proposal(
                    _make_candidate(
                        g,
                        item.prerequisite_id,
                        "REVEAL",
                        (peel,),
                        hold=False,
                        benefit=2.0,
                        evidence=_evidence(campaign, agenda, "fact: one legal reveal toward the buried source"),
                        purpose="expose a card required by the foundation",
                    ),
                    "selected: foundation prerequisite reveal",
                    events,
                    True,
                    agenda,
                )
            continue
        realized, status = _realize(state, item, profile, time_left)
        if status == RealizationStatus.RESOURCE_LIMIT:
            timeouts[item.prerequisite_id] = timeouts.get(item.prerequisite_id, 0) + 1
            events.append(f"foundation: tactical timeout does not retire {campaign.label}")
            peel = _column_reveal(state, item.column, agenda.protected_fragments)
            if peel is not None:
                return _proposal(
                    _make_candidate(
                        g,
                        item.prerequisite_id,
                        "REVEAL",
                        (peel,),
                        hold=False,
                        benefit=2.0,
                        evidence=_evidence(campaign, agenda, "fact: search timed out; one legal reveal remains"),
                        purpose="expose a card required by the foundation",
                    ),
                    "selected: foundation prerequisite reveal",
                    events,
                    True,
                    agenda,
                    block_deal=True,
                )
            continue
        if realized:
            hold = len(realized) > 1
            return _proposal(
                _make_candidate(
                    g,
                    item.prerequisite_id,
                    "REVEAL",
                    realized,
                    hold=hold,
                    benefit=3.0,
                    evidence=_evidence(
                        campaign,
                        agenda,
                        f"fact: realized {' '.join(format_action(action) for action in realized)}",
                    ),
                    purpose="expose a card required by the foundation",
                ),
                "selected: foundation prerequisite",
                events,
                False,
                agenda,
            )
        failures[item.prerequisite_id] = failures.get(item.prerequisite_id, 0) + 1
        missed_open = True
        events.append(
            f"foundation: tactical miss on {item.prerequisite_id} does not make {campaign.label} impossible"
        )
        peel = _column_reveal(state, item.column, agenda.protected_fragments)
        if peel is not None:
            return _proposal(
                _make_candidate(
                    g,
                    item.prerequisite_id,
                    "REVEAL",
                    (peel,),
                    hold=False,
                    benefit=2.0,
                    evidence=_evidence(campaign, agenda, "fact: bounded search missed; one legal reveal remains"),
                    purpose="expose a card required by the foundation",
                ),
                "selected: foundation prerequisite reveal",
                events,
                False,
                agenda,
            )

    build = _target_join(state, campaign.suit, agenda.protected_fragments)
    if build is not None and f"JOIN:{campaign.label}" not in refused:
        return _proposal(
            _make_candidate(
                g,
                f"JOIN:{campaign.label}",
                "SAME_SUIT",
                (build,),
                hold=False,
                benefit=2.0,
                evidence=_evidence(campaign, agenda, "fact: same-suit join extends the selected foundation"),
                purpose="extend the selected suit without splitting its run",
            ),
            "selected: foundation assembly",
            events,
            False,
            agenda,
        )

    # Suspension does not satisfy a mandatory excavate. Dealing while the
    # card is still buried is the v0.108 stock-exhaustion failure.
    open_mandatory = [
        item
        for item in agenda.prerequisites
        if item.kind == "excavate" and item.mandatory_before_deal and not item.achieved
    ]
    if open_mandatory or missed_open:
        waiting = open_mandatory[0].prerequisite_id if open_mandatory else "an open prerequisite"
        unlocked = _unlocking_deal(state, campaign, refused, lock)
        if unlocked is not None:
            events.append(
                f"foundation: no tableau move reveals; one stock row is tried while {waiting} stays open"
            )
            return _unlocked_proposal(state, g, campaign, agenda, events)
        events.append(f"foundation: deal waits on {waiting}")
        return _proposal(None, "", events, False, agenda, block_deal=True)
    if _preserve_broken(state, agenda):
        events.append(f"foundation: protected {campaign.suit} run is broken; not dealing yet")
        return _proposal(None, "", events, False, agenda, block_deal=True)
    completing = (
        campaign.target_removal_epoch is not None
        and campaign.current_epoch + 1 == campaign.target_removal_epoch
    )
    if (
        state.can_deal()
        and f"DEAL:{campaign.label}" not in refused
        and completing
        and lock.get("barren_deals", 0) < 1
        and _deal_recommended(campaign.space_plan.next_deal_policy)
    ):
        # The next row is the campaign's removal epoch. Earlier rows stay
        # in stock while tableau work can still expose the suit.
        return _proposal(
            _make_candidate(
                g,
                f"DEAL:{campaign.label}",
                "DEAL_NOW",
                (("deal",),),
                hold=False,
                benefit=1.0,
                evidence=_deal_evidence(state, campaign, agenda),
                purpose="deal because the foundation plan is waiting on the next row",
            ),
            "selected: foundation plan deals after its prerequisites",
            events,
            False,
            agenda,
        )
    if (
        state.can_deal()
        and campaign.target_removal_epoch is not None
        and campaign.target_removal_epoch > campaign.current_epoch
    ):
        policy = campaign.space_plan.next_deal_policy
        if not completing:
            events.append(
                f"foundation: target epoch {campaign.target_removal_epoch} "
                f"is not the next row; {policy} delays the deal"
            )
        elif lock.get("barren_deals", 0) >= 1:
            events.append(
                "foundation: a stock row that revealed nothing does not earn another deal yet"
            )
        else:
            events.append(f"foundation: {policy} delays the deal")
        unlocked = _unlocking_deal(state, campaign, refused, lock)
        if unlocked is not None:
            events.append(
                "foundation: no tableau move reveals; one stock row is tried after shaping stalled"
            )
            return _unlocked_proposal(state, g, campaign, agenda, events)
        return _proposal(None, "", events, False, agenda, block_deal=True)
    if state.can_deal():
        # The removal epoch is already in hand. Deal again only when the
        # tableau itself cannot expose another card and a move was tried
        # since the previous row. Two barren deals in a row are refused.
        frozen = _frozen_row(state, campaign, refused, lock)
        if frozen:
            events.append(
                f"foundation: target epoch {campaign.target_removal_epoch} is in hand, "
                "the tableau cannot reveal, and one more stock row is tried"
            )
            return _unlocked_proposal(state, g, campaign, agenda, events)
        events.append(
            f"foundation: target epoch {campaign.target_removal_epoch} is in hand "
            f"and {campaign.label} is still on the tableau; the deal waits"
        )
        return _proposal(None, "", events, False, agenda, block_deal=True)
    return _proposal(None, "", events, False, agenda)


def agenda_public(agenda: Optional[FoundationAgenda]) -> dict:
    if agenda is None:
        return {}
    view = agenda.view
    return {
        "label": view.label,
        "suit": view.suit,
        "copy_index": view.copy_index,
        "target_epoch": view.target_epoch,
        "current_epoch": view.current_epoch,
        "earliest_epoch": view.earliest_epoch,
        "other_copy_earliest": view.other_copy_earliest,
        "estimated_cost": view.estimated_cost,
        "readiness": view.readiness,
        "confidence": view.confidence,
        "theoretically_available": view.theoretically_available,
        "operationally_attainable": view.operationally_attainable,
        "economically_attractive": view.economically_attractive,
        "reasons": list(view.reasons),
        "alternatives": [
            {
                "label": item.label,
                "estimated_cost": item.estimated_cost,
                "target_epoch": item.target_epoch,
                "readiness": item.readiness,
                "theoretically_available": item.theoretically_available,
                "operationally_attainable": item.operationally_attainable,
            }
            for item in agenda.alternatives
        ],
        "prerequisites": [
            {
                "id": item.prerequisite_id,
                "kind": item.kind,
                "achieved": item.achieved,
                "rank": item.rank,
                "column": None if item.column is None else item.column + 1,
                "estimated_cost": item.estimated_cost,
                "mandatory_before_deal": item.mandatory_before_deal,
                "source_keys": list(item.source_keys),
                "description": item.description,
            }
            for item in agenda.prerequisites
        ],
    }


def _proposal(candidate, reason, events, timeout, agenda, block_deal: bool = False) -> FoundationProposal:
    return FoundationProposal(
        candidate,
        reason,
        tuple(events),
        timeout,
        block_deal,
        agenda,
        agenda_public(agenda),
    )


def _candidate(feasibility, suit: str, copy_index: int):
    for item in feasibility.frontier.candidates:
        if item.suit == suit and item.copy_index == copy_index:
            return item
    return None


def _view_reasons(campaign, candidate, other_copy, other_epoch, theoretical, operational) -> Tuple[str, ...]:
    reasons = [
        f"fact: schedule objective {schedule_objective(campaign):.1f} is heuristic and does not prune",
        f"fact: target epoch {campaign.target_removal_epoch}, now epoch {campaign.current_epoch}",
        f"fact: readiness {campaign.readiness.value}, confidence {campaign.confidence}",
        (
            "fact: theoretically available now"
            if theoretical
            else f"fact: not theoretically available until epoch {None if candidate is None else candidate.earliest_epoch}"
        ),
        (
            "fact: operationally attainable from the current tableau or the named stock horizon"
            if operational
            else "fact: not operationally attainable on the present schedule"
        ),
        (
            f"fact: the other physical copy, ordinal {other_copy}, "
            f"is earliest at epoch {other_epoch}; it is a later foundation, not a second use of the chosen cards"
        ),
    ]
    reasons.extend(campaign.rationale[:3])
    if candidate is not None and candidate.buried_cards:
        buried = candidate.buried_cards[0]
        reasons.append(
            f"fact: a buried {campaign.suit} card is in column {buried.column + 1} at depth {buried.depth}"
        )
    reasons.append("fact: empty columns are shared by every suit and do not choose the target")
    return tuple(reasons)


def _locked_campaign(portfolio, lock, events: List[str]) -> Optional[FoundationCampaign]:
    label = lock.get("label")
    if not label:
        return portfolio.primary
    for campaign in portfolio.campaigns:
        if campaign.label == label:
            primary = portfolio.primary
            if primary is not None and primary.label != label and _clearly_better(primary, campaign):
                events.append(
                    f"foundation: switch {label} to {primary.label} "
                    f"because its schedule is materially better"
                )
                lock["label"] = primary.label
                lock["announced"] = None
                lock["failures"] = {}
                return primary
            return campaign
    events.append(f"foundation: {label} is no longer the next ordinal")
    lock["label"] = None
    lock["announced"] = None
    return portfolio.primary


def _clearly_better(new: FoundationCampaign, old: FoundationCampaign) -> bool:
    if schedule_objective(new) + 8.0 <= schedule_objective(old):
        return True
    if (
        new.target_removal_epoch is not None
        and old.target_removal_epoch is not None
        and new.target_removal_epoch + 1 < old.target_removal_epoch
        and schedule_objective(new) <= schedule_objective(old) + 2.0
    ):
        return True
    return False


def _view_for(views: Sequence[FoundationView], label: str) -> Optional[FoundationView]:
    for view in views:
        if view.label == label:
            return view
    return None


def _agenda(state, cards, campaign, view, portfolio) -> FoundationAgenda:
    obligations = campaign_obligations_for_next_epoch(state, campaign, cards)
    prerequisites: List[Prerequisite] = []
    protected: List[Tuple[Card, ...]] = []
    seen_ranks = set()
    for obligation in obligations:
        achieved = obligation_is_satisfied(state, campaign, obligation)
        if obligation.kind == CampaignObligationKind.PRESERVE_FRAGMENT and obligation.fragment:
            protected.append(tuple(obligation.fragment))
            prerequisites.append(
                Prerequisite(
                    obligation.obligation_id,
                    "preserve",
                    obligation.description,
                    obligation.rank,
                    obligation.source_column,
                    obligation.source_keys,
                    0.0,
                    True,
                    achieved,
                )
            )
            continue
        if obligation.kind != CampaignObligationKind.EXCAVATE_PREFIX:
            continue
        if obligation.rank in seen_ranks:
            continue
        seen_ranks.add(obligation.rank)
        objective = _objective_for_prefix(obligation)
        cost = float(obligation.required_reveals or 1)
        prerequisites.append(
            Prerequisite(
                obligation.obligation_id,
                "excavate",
                obligation.description,
                obligation.rank,
                obligation.source_column,
                obligation.source_keys,
                cost,
                bool(obligation.mandatory_before_deal),
                achieved,
                objective,
            )
        )
    return FoundationAgenda(
        view=view,
        alternatives=_sibling_views(view, portfolio),
        prerequisites=tuple(prerequisites),
        protected_fragments=tuple(protected),
        campaign_cost=float(campaign.estimated_campaign_cost),
        target_epoch=campaign.target_removal_epoch,
        current_epoch=campaign.current_epoch,
        stock_len=len(state.stock),
        reasons=view.reasons,
    )


def _sibling_views(selected: FoundationView, portfolio: FoundationCampaignPortfolio) -> Tuple[FoundationView, ...]:
    """Alternatives already ranked on the portfolio, without a second feasibility pass.

    The selected view carries the feasibility facts. Rivals are described from
    the campaign schedule so a caller can see why they lost.
    """

    rivals: List[FoundationView] = []
    for campaign in portfolio.campaigns:
        if campaign.label == selected.label:
            continue
        operational = campaign.readiness.value in _OPERATIONAL and not campaign.blockers
        rivals.append(
            FoundationView(
                suit=campaign.suit,
                copy_index=campaign.copy_index,
                label=campaign.label,
                target_epoch=campaign.target_removal_epoch,
                current_epoch=campaign.current_epoch,
                earliest_epoch=campaign.earliest_theoretical_epoch,
                other_copy_earliest=None,
                estimated_cost=float(campaign.estimated_campaign_cost),
                readiness=campaign.readiness.value,
                confidence=campaign.confidence,
                theoretically_available=bool(
                    campaign.earliest_theoretical_epoch is not None
                    and campaign.current_epoch >= campaign.earliest_theoretical_epoch
                ),
                operationally_attainable=operational,
                economically_attractive=False,
                face_up=0,
                face_down=0,
                stock_count=0,
                burial=0,
                longest_fragment=max((item.length for item in campaign.current_same_suit_fragments), default=0),
                reasons=(
                    f"fact: schedule objective {schedule_objective(campaign):.1f}",
                    f"fact: target epoch {campaign.target_removal_epoch}",
                    f"fact: readiness {campaign.readiness.value}",
                ),
            )
        )
    return tuple(rivals)


def _realize(state, item: Prerequisite, profile: Profile, time_left: float):
    if item.objective is None:
        return (), RealizationStatus.UNSUPPORTED
    limit = min(1.2, max(0.15, time_left / 4.0), float(profile.tactical_time_s) or 1.2)
    nodes = min(1500, max(int(profile.tactical_nodes), 200))
    cost_cap = min(8, max(int(profile.tactical_max_cost), int(item.estimated_cost) + 1, 2))
    try:
        found = realize_objective(
            state,
            item.objective,
            mode=RealizationMode.FAST_BOUNDED,
            max_cost=cost_cap,
            max_nodes=nodes,
            time_limit_s=limit,
            beam=32,
        )
    except Exception:
        return (), RealizationStatus.NOT_FOUND_WITHIN_BOUND
    if found.status != RealizationStatus.FOUND or not found.actions:
        return (), found.status
    actions = _without_deal(found.actions)
    if not actions:
        return (), RealizationStatus.NOT_FOUND_WITHIN_BOUND
    trial = state.clone()
    try:
        replay_actions(trial, list(actions))
    except ValueError:
        return (), RealizationStatus.NOT_FOUND_WITHIN_BOUND
    if item.column is not None and len(trial.columns[item.column].face_down) > (
        item.objective.target_params.get("max_face_down", 0)
    ):
        return (), RealizationStatus.NOT_FOUND_WITHIN_BOUND
    return actions, found.status


def _without_deal(actions: Sequence[Action]) -> Tuple[Action, ...]:
    if any(action == ("deal",) for action in actions[:-1]):
        return ()
    if actions and actions[-1] == ("deal",):
        return tuple(actions[:-1])
    return tuple(actions)


def _column_reveal(state: SpiderState, column: Optional[int], protected) -> Optional[Action]:
    if column is None:
        return None
    before = len(state.columns[column].face_down)
    if before <= 0:
        return None
    for action in all_legal_actions(state):
        if action == ("deal",) or action[0] != column:
            continue
        if _splits_protected(state, action, protected):
            continue
        trial = state.clone()
        apply_action(trial, action)
        if len(trial.columns[column].face_down) < before:
            return action
    return None


def _completion_move(state: SpiderState) -> Optional[Action]:
    best = None
    best_key = None
    for action in all_legal_actions(state):
        if action == ("deal",):
            continue
        trial = state.clone()
        try:
            cost = apply_action(trial, action)
        except ValueError:
            continue
        if len(trial.foundations) <= len(state.foundations):
            continue
        key = (cost, -action[2], action)
        if best_key is None or key < best_key:
            best_key = key
            best = action
    return best


def _target_join(state: SpiderState, suit: str, protected) -> Optional[Action]:
    best = None
    best_gain = 0
    before = _longest(state, suit)
    for action in all_legal_actions(state):
        if action == ("deal",):
            continue
        src, dst, k = action
        run = state.columns[src].face_up[-k:]
        if not run or run[0].suit != suit:
            continue
        if _splits_protected(state, action, protected):
            continue
        top = state.columns[dst].top()
        if top is None or top.suit != suit or top.rank != run[0].rank + 1:
            continue
        trial = state.clone()
        apply_action(trial, action)
        gain = _longest(trial, suit) - before
        if gain > best_gain:
            best_gain = gain
            best = action
    return best


def _splits_protected(state: SpiderState, action: Action, protected) -> bool:
    """True when the move takes a proper suffix out of a protected same-suit run."""

    if action == ("deal",) or not protected:
        return False
    src, _dst, k = action
    up = state.columns[src].face_up
    if k <= 0 or k > len(up):
        return False
    move_start = len(up) - k
    for fragment in protected:
        if len(fragment) < 2:
            continue
        width = len(fragment)
        for start in range(len(up) - width + 1):
            if tuple(up[start : start + width]) != tuple(fragment):
                continue
            end = start + width
            if start < move_start < end:
                return True
    return False


def _preserve_broken(state: SpiderState, agenda: FoundationAgenda) -> bool:
    for item in agenda.prerequisites:
        if item.kind == "preserve" and item.mandatory_before_deal and not item.achieved:
            return True
    return False


def _longest(state: SpiderState, suit: str) -> int:
    best = 0
    for column in state.columns:
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
            best = max(best, end - index + 1)
            index = end + 1
    return best


def _deal_recommended(policy: str) -> bool:
    """The campaign's own stock policy, not a suit preference.

    ``shape_receivers_then_deal`` means exposed parents still have to be
    placed. Dealing then is what buried the queen on deal 4925153.
    """

    text = policy or ""
    return text.startswith("deal_now") or text.startswith("fill_then_deal") or text.startswith(
        "carry_empty"
    )


def _any_reveal(state: SpiderState) -> bool:
    before = face_down_count(state)
    for action in all_legal_actions(state):
        if action == ("deal",):
            continue
        trial = state.clone()
        apply_action(trial, action)
        if face_down_count(trial) < before:
            return True
    return False


def _frozen_row(state, campaign, refused, lock) -> bool:
    """True when another stock row is the only way to expose a card."""

    if _any_reveal(state) or lock.get("moves_since_deal", 0) < 1:
        return False
    if f"DEAL:{campaign.label}" in refused or not state.can_deal():
        return False
    return True


def _unlocking_deal(state, campaign, refused, lock):
    """One row when the tableau cannot reveal and the plan still needs stock.

    A second consecutive barren deal is refused. Search timeouts are not
    treated as proof that the row is useless.
    """

    if _any_reveal(state):
        return None
    # A second row is allowed after the tableau has been tried. It is not
    # allowed on the same state as the deal that just failed to reveal.
    if lock.get("barren_deals", 0) >= 1 and lock.get("moves_since_deal", 0) < 1:
        return None
    if f"DEAL:{campaign.label}" in refused or not state.can_deal():
        return None
    if campaign.target_removal_epoch is None or campaign.target_removal_epoch <= campaign.current_epoch:
        return None
    return ("deal",)


def _unlocked_proposal(state, g, campaign, agenda, events):
    return _proposal(
        _make_candidate(
            g,
            f"DEAL:{campaign.label}",
            "DEAL_NOW",
            (("deal",),),
            hold=False,
            benefit=1.0,
            evidence=_deal_evidence(state, campaign, agenda),
            purpose="deal one row because no tableau move reveals a buried card",
        ),
        "selected: foundation plan deals one row because the tableau cannot reveal",
        events,
        False,
        agenda,
    )


def _deal_evidence(state, campaign, agenda) -> Tuple[str, ...]:
    row = next_stock_row(state) or ()
    incoming = [
        f"column {index + 1} {card}"
        for index, card in enumerate(row)
        if card.suit == campaign.suit
    ]
    note = ", ".join(incoming) if incoming else "no card of the selected suit"
    return _evidence(
        campaign,
        agenda,
        f"fact: next row brings {note}",
        "fact: mandatory excavation for this horizon is done or was not required",
        "fact: dealing can cover exposed cards; the campaign still wants this row",
    )


def _evidence(campaign, agenda, *extra: str) -> Tuple[str, ...]:
    return tuple(agenda.reasons[:4]) + tuple(extra) + (
        f"estimate: campaign cost {campaign.estimated_campaign_cost:.1f} is not an admissible bound",
    )


def _make_candidate(g, identifier, kind, actions, *, hold, benefit, evidence, purpose) -> Candidate:
    cost = len(tuple(action for action in actions if action == ("deal",))) + len(
        tuple(action for action in actions if action != ("deal",))
    )
    # Exact corrected cost is applied by the engine. This count is only a
    # projection so the decision log has a number. Zero-cost relocations can
    # make it high; the engine result replaces it.
    return Candidate(
        candidate_id=identifier,
        kind=kind,
        purpose=purpose,
        principles=(11, 12, 13, 2, 8),
        actions=tuple(actions),
        objective=None,
        immediate_cost=cost,
        cost_is_exact=False,
        expected_benefit=benefit,
        structural_risk=0.2,
        horizon="foundation",
        feasibility="bounded realisation",
        evidence=tuple(evidence),
        admissible_lb=0,
        projected=float(g) + float(len(actions)),
        solves=False,
        attractiveness=benefit,
        hold=hold,
    )
