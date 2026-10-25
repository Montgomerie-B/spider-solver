"""Foundation-directed adapter for the human-strategy controller.

This module does not plan foundations by itself. It asks the existing
feasibility and campaign analysers for a ranked next foundation, turns the
campaign's obligations into a short prerequisite list, and asks the existing
objective realiser for a legal path. When that path misses, a bounded search
looks for a legal way to uncover the named card. A known incoming card can
be given its receiver only when the replayed deal is better than dealing
immediately. Estimates order work. They do not prune. A tactical timeout
does not retire the campaign, and it does not move the operational epoch.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.metrics import Action, format_action, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    RankSourceKind,
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
from spider.planner.stock_reception import PreDealShapingObjective, next_stock_row, run_bounded_shaping_probe
from spider.research_actions import all_legal_actions, apply_action, face_down_count, step_cost
from spider.state_identity import canonical_state_key

from .evaluation import admissible_remaining, estimate_remaining, same_suit_bonds
from .portfolio import Candidate
from .preparation import classify_incoming_receiver, compare_exact_reception
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
    _proposal.active_lock = lock
    started = time.perf_counter()
    try:
        feasibility, portfolio = load_portfolio(state, cards, cache)
        _add_time(lock, "foundation_analysis", time.perf_counter() - started)
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
    lock["yield_to_alternative"] = False
    campaign = _locked_campaign(portfolio, lock, events, state)
    if campaign is None:
        return FoundationProposal(None, "", tuple(events), False, False, None)
    view = _view_for(views_from_portfolio(feasibility, portfolio), campaign.label)
    if view is None:
        view = views_from_portfolio(feasibility, portfolio)[0]
    previous_stock = lock.get("stock_len")
    fd_before = lock.get("fd")
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
    lock["stock_just_changed"] = previous_stock is not None and len(state.stock) != previous_stock
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
    _sync_operational_epoch(lock, campaign, state, events)
    if (
        fd_before is not None
        and fd_now < fd_before
        and lock.get("operational_epoch") is not None
        and campaign.current_epoch >= lock["operational_epoch"]
        and (lock.get("failures") or lock.get("suspended_notes") or lock.get("buried_tried"))
    ):
        # An elapsed campaign can look again after a reveal. An earlier
        # campaign keeps its miss counts so the opening line does not restart.
        events.append("foundation: a reveal reopens suspended prerequisites")
        lock["failures"] = {}
        lock["suspended_notes"] = set()
        lock.pop("buried_tried", None)
    _record_agenda(lock, agenda, campaign)
    if not lock.get("portfolio_noted"):
        band = [
            item.label
            for item in agenda.alternatives
            if abs(float(item.estimated_cost) - float(agenda.view.estimated_cost)) <= 6.0
        ]
        if band:
            events.append(
                "foundation: alternative portfolio "
                + ", ".join(band)
                + "; similar costs are not proof and do not prune"
            )
        lock["portfolio_noted"] = True

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

    bottleneck = _bottleneck_proposal(state, g, campaign, agenda, lock, events, time_left, refused)
    if bottleneck is not None:
        return bottleneck

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
        realise_started = time.perf_counter()
        realized, status = _realize(state, item, profile, time_left)
        _add_time(lock, "tactical_realisation", time.perf_counter() - realise_started)
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

    # A missed reveal is evidence about that attempt. It is not evidence that
    # the suit can only be finished after another stock row.
    open_mandatory = [
        item
        for item in agenda.prerequisites
        if item.kind == "excavate" and item.mandatory_before_deal and not item.achieved
    ]
    operational = lock.get("operational_epoch")
    completing = operational is not None and campaign.current_epoch + 1 == operational
    policy = campaign.space_plan.next_deal_policy
    if open_mandatory or missed_open:
        waiting = open_mandatory[0].prerequisite_id if open_mandatory else "an open prerequisite"
        accessed = _access_proposal(
            state, g, campaign, agenda, lock, events, refused, time_left, waiting
        )
        if accessed is not None:
            return accessed
        suspended_all = bool(open_mandatory) and all(
            failures.get(item.prerequisite_id, 0) >= 3
            or item.prerequisite_id in lock.get("suspended_notes", ())
            for item in open_mandatory
        )
        if suspended_all:
            # Every mandatory reveal has already missed. Waiting here replays
            # the same refusal. The suit stays suspended and another campaign
            # may move. This is not a proof that the suit is impossible.
            events.append(
                f"foundation: suspended prerequisites do not freeze {campaign.label}"
            )
            events.append(
                "foundation: a failed direct reveal does not move the operational epoch"
            )
            lock["feasibility_status"] = "SUSPENDED"
            lock["yield_to_alternative"] = True
            return _proposal(None, "", events, False, agenda, block_deal=True)
        events.append(f"foundation: deal waits on {waiting}")
        events.append(
            "foundation: a failed direct reveal does not move the operational epoch"
        )
        return _proposal(None, "", events, False, agenda, block_deal=True)
    if _preserve_broken(state, agenda):
        events.append(f"foundation: protected {campaign.suit} run is broken; not dealing yet")
        return _proposal(None, "", events, False, agenda, block_deal=True)
    if (
        state.can_deal()
        and f"DEAL:{campaign.label}" not in refused
        and completing
        and lock.get("barren_deals", 0) < 1
        and _deal_recommended(policy)
    ):
        # The next row is the locked operational epoch. Receiver alignment
        # runs only when this deal is not already justified.
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
    if operational is not None and campaign.current_epoch + 1 < operational:
        events.append(
            f"foundation: target epoch {operational} "
            f"is not the next row; {policy} delays the deal"
        )
    elif operational is not None and campaign.current_epoch >= operational and state.can_deal():
        events.append(
            f"foundation: target epoch {operational} is in hand "
            f"and {campaign.label} is still on the tableau; the deal waits"
        )
    analysed = lock.get("analysed_epoch")
    if analysed != operational:
        events.append(
            f"foundation: analysed epoch {analysed} does not authorise a deal "
            f"while the operational epoch stays {operational}"
        )
    accessed = _access_proposal(
        state, g, campaign, agenda, lock, events, refused, time_left, "the locked suit"
    )
    if accessed is not None:
        return accessed
    elapsed = operational is not None and campaign.current_epoch >= operational
    if elapsed:
        # The target row has already been dealt. Aligning a parent under that
        # historical landing is not a current obligation, and the next row is
        # a later stock event. Work that remains is on the tableau now.
        events.append(
            f"foundation: epoch {operational} is already dealt; "
            "receiver alignment is not generated for that historical row"
        )
        events.append(
            "foundation: remaining work is current accessibility, not a past landing column"
        )
        buried = _elapsed_access_proposal(
            state, g, campaign, agenda, lock, events, refused, time_left
        )
        if buried is not None:
            return buried
        for item in agenda.alternatives:
            events.append(
                f"foundation: {item.label} stays eligible; "
                f"readiness {item.readiness}, epoch {item.target_epoch}"
            )
        if any(card.suit == campaign.suit for card in state.stock):
            events.append(
                f"foundation: {campaign.label} still depends on a future stock row; "
                "the elapsed epoch does not deal it"
            )
            lock["feasibility_status"] = "DEFERRED_BY_STOCK"
        else:
            lock["feasibility_status"] = lock.get("feasibility_status") or "PROBE_LIMIT"
        lock["yield_to_alternative"] = True
        miss = lock.get("feasibility_status") or "PROBE_LIMIT"
        events.append(f"foundation: {campaign.label} yields; {miss} is not infeasibility")
        return _proposal(None, "", events, False, agenda, block_deal=True)
    aligned = _alignment_proposal(state, g, campaign, agenda, lock, events, time_left)
    if aligned is not None:
        return aligned
    # Alignment has already run when time remains. A measured connection on
    # the next row can then justify the deal. A raised analysed epoch cannot.
    if time_left >= 0.2:
        evidenced = _evidenced_deal(
            state, g, campaign, agenda, lock, events, refused, operational
        )
        if evidenced is not None:
            return evidenced
        necessary = _necessary_deal(
            state, g, campaign, agenda, lock, events, refused, operational
        )
        if necessary is not None:
            return necessary
    horizon = _horizon_deal(state, g, campaign, agenda, lock, events, refused, operational, policy)
    if horizon is not None:
        return horizon
    if (
        time_left >= 0.2
        and state.can_deal()
        and operational is not None
        and campaign.current_epoch + 1 <= operational
    ):
        events.append(
            "foundation: the next row has no measured same-suit gain inside the locked horizon, "
            "so the deal stays deferred"
        )
    return _proposal(None, "", events, False, agenda, block_deal=state.can_deal())


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
    public = agenda_public(agenda)
    holder = getattr(_proposal, "active_lock", None)
    if holder is not None:
        public = dict(public)
        public["campaign_record"] = campaign_record_public(holder)
        timing = holder.get("timing") or {}
        public["timing"] = {key: round(float(value), 4) for key, value in timing.items()}
    return FoundationProposal(
        candidate,
        reason,
        tuple(events),
        timeout,
        block_deal,
        agenda,
        public,
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


def _locked_campaign(portfolio, lock, events: List[str], state: Optional[SpiderState] = None) -> Optional[FoundationCampaign]:
    forced = lock.get("hold_label")
    if forced:
        lock["hold_label"] = None
        for campaign in portfolio.campaigns:
            if campaign.label == forced:
                lock["label"] = forced
                events.append(f"foundation: {forced} is the alternative under test")
                return campaign
    label = lock.get("label")
    if not label:
        return portfolio.primary
    for campaign in portfolio.campaigns:
        if campaign.label == label:
            primary = portfolio.primary
            if primary is not None and primary.label != label and _clearly_better(primary, campaign):
                if state is not None and not campaign_may_displace(state, primary, campaign):
                    token = (label, primary.label, len(state.stock))
                    if lock.get("refused_switch") != token:
                        lock["refused_switch"] = token
                        events.append(
                            f"foundation: keep {label}; {primary.label} looks earlier "
                            "on the heuristic schedule but has no demonstrated next step"
                        )
                        lock.setdefault("campaign_changes", []).append(
                            f"refused switch {label} to {primary.label}; "
                            "feasibility outweighs the epoch"
                        )
                    return campaign
                reason = (
                    f"switch {label} to {primary.label} "
                    f"because its schedule is materially better"
                )
                events.append(f"foundation: {reason}")
                lock.setdefault("campaign_changes", []).append(reason)
                lock["label"] = primary.label
                lock["announced"] = None
                lock["failures"] = {}
                return primary
            return campaign
    events.append(f"foundation: {label} is no longer the next ordinal")
    lock["label"] = None
    lock["announced"] = None
    return portfolio.primary


_HORIZON_KEYS = (
    "label",
    "announced",
    "epoch_label",
    "original_epoch",
    "operational_epoch",
    "analysed_epoch",
    "theoretical_epoch",
    "original_rationale",
    "failures",
    "timeouts",
    "suspended_notes",
    "epoch_changes",
    "rejected_revisions",
    "tableau_counts",
    "chosen_sources",
    "required_cards",
    "outstanding",
    "achieved_prerequisites",
    "campaign_blockers",
    "receiving",
    "last_rejection",
    "rationale_frozen",
    "unresolved_access",
    "cost_invested",
    "portfolio_noted",
    "hold_label",
)


def _drop_horizon(lock: dict) -> None:
    """Forget one campaign's epoch and obligations. Physical stock counters stay."""

    for key in _HORIZON_KEYS:
        lock.pop(key, None)


def close_foundation_campaign(
    lock: dict,
    *,
    reason: str,
    exact_cost: int,
    cumulative_g: int,
    label: Optional[str],
) -> dict:
    """Close a finished foundation campaign so the next one starts clean.

    The old operational epoch and its completed obligations are not inherited.
    """

    record = {
        "label": label,
        "reason": reason,
        "exact_cost": int(exact_cost),
        "cumulative_g": int(cumulative_g),
        "operational_epoch": lock.get("operational_epoch"),
        "outstanding_at_close": list(lock.get("outstanding") or []),
    }
    lock.setdefault("completed", []).append(record)
    lock.setdefault("campaign_changes", []).append(reason)
    _drop_horizon(lock)
    lock.pop("alternatives", None)
    lock.pop("tried_labels", None)
    lock.pop("resume_counts", None)
    lock.pop("yield_to_alternative", None)
    lock.pop("recovery_key", None)
    lock.pop("buried_tried", None)
    lock.pop("excavation_cache", None)
    lock.pop("access_cache", None)
    lock.pop("feasibility_status", None)
    # Deal forks, refused switches, and a finished probe belong to the suit
    # that just left the tableau. The next campaign ranks its own copies.
    lock.pop("fork_block", None)
    lock.pop("refused_switch", None)
    lock.pop("bottleneck_cache", None)
    lock.pop("pinned_actions", None)
    lock.pop("pending_alternate_bottleneck", None)
    lock["alternative_switches"] = 0
    lock["barren_deals"] = 0
    lock["moves_since_deal"] = 0
    return record


def adopt_alternative_foundation(lock: dict) -> Optional[str]:
    """Point the lock at one dormant foundation target.

    The previous horizon is dropped. At most two such switches are kept, so a
    stall cannot walk the whole suit list.
    """

    if int(lock.get("alternative_switches", 0)) >= 2:
        return None
    tried = lock.setdefault("tried_labels", [])
    current = lock.get("label")
    if current and current not in tried:
        tried.append(current)
    chosen = None
    for label in list(lock.get("alternatives") or []):
        if label not in tried:
            chosen = label
            break
    if chosen is None:
        return None
    tried.append(chosen)
    alternatives = list(lock.get("alternatives") or [])
    reason = f"campaign {current} stalled; trying {chosen}"
    _drop_horizon(lock)
    lock["alternatives"] = alternatives
    lock["tried_labels"] = tried
    lock["label"] = chosen
    lock["hold_label"] = chosen
    lock["alternative_switches"] = int(lock.get("alternative_switches", 0)) + 1
    lock["barren_deals"] = 0
    lock.setdefault("campaign_changes", []).append(reason)
    return reason


def structural_assessment(state: SpiderState) -> dict:
    """Structure at a checkpoint. The remaining-cost figure is heuristic.

    ``admissible_remaining`` is the only number that may prune. The heuristic
    figure must not be read as a proof bound, and an early foundation is not
    by itself a claim that the full game got cheaper.
    """

    fragments = []
    mixed = 0
    for index, column in enumerate(state.columns):
        length = _exposed_run_length(column)
        top = column.top()
        if length >= 2 and top is not None:
            fragments.append(
                {
                    "column": index + 1,
                    "suit": top.suit,
                    "length": length,
                    "top": str(top),
                }
            )
        up = column.face_up
        for cursor in range(len(up) - 1):
            if up[cursor].suit != up[cursor + 1].suit:
                mixed += 1
    empties = sum(1 for column in state.columns if column.is_empty())
    return {
        "face_down": face_down_count(state),
        "bonds": same_suit_bonds(state),
        "foundations": len(state.foundations),
        "stock_cards": len(state.stock),
        "empty_columns": empties,
        "fragments": fragments,
        "mixed_suit_boundaries": mixed,
        "admissible_remaining": admissible_remaining(state),
        "heuristic_remaining": estimate_remaining(state),
        "heuristic_remaining_is_not_a_bound": True,
    }


def campaign_near_term_status(state: SpiderState, campaign: FoundationCampaign) -> str:
    """What the controller can do next. A heuristic epoch is not a status.

    READY means a legal same-suit join exists. REQUIRES_PREPARATION means a
    buried or obstructed card is a concrete tableau task. DEFERRED_BY_STOCK
    means the next need is still in a future row. PROBE_LIMIT and
    PROVEN_INFEASIBLE are not assigned here: a bounded search has to say so.
    """

    if _target_join(state, campaign.suit, ()) is not None:
        return "READY"
    buried = any(
        card.suit == campaign.suit
        for column in state.columns
        for card in column.face_down
    )
    obstructed = bool(obstructed_tableau_sources(state, campaign))
    readiness = campaign.readiness.value
    elapsed = (
        campaign.target_removal_epoch is not None
        and campaign.current_epoch >= campaign.target_removal_epoch
    )
    if readiness == "blocked" and not buried and not obstructed:
        return "SUSPENDED"
    if readiness in {"ready_now", "assembly_led", "excavation_led"} or obstructed or buried:
        return "REQUIRES_PREPARATION"
    if elapsed or readiness in {"deferred", "stock_gated"}:
        return "DEFERRED_BY_STOCK"
    return "REQUIRES_PREPARATION"


def campaign_may_displace(
    state: SpiderState,
    challenger: FoundationCampaign,
    incumbent: FoundationCampaign,
) -> bool:
    """An earlier heuristic schedule must not evict a campaign that can move.

    A challenger whose target epoch has already been dealt, and which has no
    legal join, does not displace an incumbent that still has tableau work.
    """

    new_status = campaign_near_term_status(state, challenger)
    old_status = campaign_near_term_status(state, incumbent)
    if new_status in {"DEFERRED_BY_STOCK", "PROBE_LIMIT", "SUSPENDED"} and old_status in {
        "READY",
        "REQUIRES_PREPARATION",
    }:
        return False
    elapsed = (
        challenger.target_removal_epoch is not None
        and challenger.current_epoch >= challenger.target_removal_epoch
    )
    if elapsed and new_status != "READY" and old_status in {"READY", "REQUIRES_PREPARATION"}:
        return False
    return True


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
        if obligation.kind == CampaignObligationKind.SHAPE_RECEIVER:
            prerequisites.append(
                Prerequisite(
                    obligation.obligation_id,
                    "receiver",
                    obligation.description,
                    obligation.rank,
                    obligation.receiver_column,
                    (),
                    1.0,
                    False,
                    achieved,
                )
            )
            continue
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


@dataclass(frozen=True)
class AccessPlan:
    """A short legal sequence that reduces the cover on one named card."""

    actions: Tuple[Action, ...]
    cost: int
    status: str
    nodes: int
    source_key: str
    column: int
    depth_before: int
    depth_after: int
    obstruction: Tuple[str, ...]
    exhaustive: bool = False
    strategy: str = "receiver-then-peel"
    allow_deals: bool = False
    max_cost_limit: int = 0
    max_nodes_limit: int = 0
    movable: bool = False
    stop: str = ""
    zero_cost_expansions: int = 0


def _add_time(lock: dict, name: str, seconds: float) -> None:
    bucket = lock.setdefault("timing", {})
    bucket[name] = float(bucket.get(name, 0.0)) + float(seconds)


def _rank_tableau_counts(state: SpiderState, suit: str) -> Dict[int, int]:
    counts = {rank: 0 for rank in range(1, 14)}
    for column in state.columns:
        for card in list(column.face_down) + list(column.face_up):
            if card.suit == suit:
                counts[card.rank] += 1
    return counts


def revise_operational_epoch(
    lock: dict,
    *,
    analysed: Optional[int],
    theoretical: Optional[int],
    stock_changed: bool,
    foundation_removed: bool,
    lost: Sequence[Tuple] = (),
    arrived: Sequence[Tuple] = (),
    note: str = "",
) -> str:
    """Keep the operational epoch stable unless the evidence is specific.

    A higher analysed epoch is a forecast. It is recorded and rejected unless
    stock actually changed and a named copy left the tableau, or the analysed
    horizon moved earlier after new stock information. Returns ``revised``,
    ``rejected``, or ``unchanged``.
    """

    lock["theoretical_epoch"] = theoretical
    lock["analysed_epoch"] = analysed
    if lock.get("original_epoch") is None:
        lock["original_epoch"] = analysed
        lock["operational_epoch"] = analysed
        lock["original_rationale"] = note
        lock.setdefault("epoch_changes", [])
        lock.setdefault("rejected_revisions", [])
        return "unchanged"
    operational = lock.get("operational_epoch")
    if analysed == operational:
        return "unchanged"
    lost = tuple(lost)
    arrived = tuple(arrived)
    earlier = (
        stock_changed
        and analysed is not None
        and operational is not None
        and analysed < operational
    )
    named_loss = bool(lost) and stock_changed and analysed is not None and operational is not None and analysed > operational
    if foundation_removed or earlier or named_loss:
        if foundation_removed:
            why = "a foundation was removed"
            affected = "the locked suit"
        elif earlier:
            why = "stock changed and the analysed horizon moved earlier"
            affected = arrived[0][0] if arrived else "the locked suit"
        else:
            why = "a named tableau copy left the tableau after the stock changed"
            affected = lost[0][0]
        lock["operational_epoch"] = analysed
        lock.setdefault("epoch_changes", []).append(
            {
                "old": operational,
                "new": analysed,
                "state_change": note or why,
                "prerequisite": affected,
                "evidence": why,
                "stock_timing": "later deals are judged against the revised operational epoch",
            }
        )
        return "revised"
    lock.setdefault("rejected_revisions", []).append(
        {
            "old": operational,
            "new": analysed,
            "state_change": note or "reanalysis without a stock change or a named lost card",
            "prerequisite": lost[0][0] if lost else None,
            "evidence": "a changed target epoch is a forecast, not proof that another row is required",
            "stock_timing": "the operational epoch stays, so the forecast does not authorise a deal",
        }
    )
    return "rejected"


def _sync_operational_epoch(lock: dict, campaign: FoundationCampaign, state: SpiderState, events: List[str]) -> None:
    if lock.get("epoch_label") not in (None, campaign.label):
        events.append(
            f"foundation: epoch record resets because the locked suit is now {campaign.label}"
        )
        lock["original_epoch"] = None
        lock["epoch_changes"] = []
        lock["rejected_revisions"] = []
        lock["tableau_counts"] = {}
        lock["chosen_sources"] = {}
    lock["epoch_label"] = campaign.label
    counts = _rank_tableau_counts(state, campaign.suit)
    previous_counts = lock.get("tableau_counts") or {}
    lost = []
    for rank, count in counts.items():
        old = previous_counts.get(rank)
        if old is not None and count < old:
            lost.append((rank, f"tableau-count:{old}", f"tableau-count:{count}"))
    current_sources = {}
    arrived = []
    previous_sources = lock.get("chosen_sources") or {}
    for need in campaign.rank_needs:
        if need.chosen is None:
            continue
        current_sources[str(need.rank)] = need.chosen.source_key
        previous = previous_sources.get(str(need.rank))
        if (
            previous
            and str(previous).startswith("stock:")
            and str(need.chosen.source_key).startswith("tableau:")
        ):
            arrived.append((need.rank, previous, need.chosen.source_key))
    status = revise_operational_epoch(
        lock,
        analysed=campaign.target_removal_epoch,
        theoretical=campaign.earliest_theoretical_epoch,
        stock_changed=bool(lock.get("stock_just_changed")),
        foundation_removed=False,
        lost=tuple(lost),
        arrived=tuple(arrived),
        note=f"suit {campaign.label} at epoch {campaign.current_epoch}",
    )
    lock["tableau_counts"] = counts
    lock["chosen_sources"] = current_sources
    if status == "revised" and lock.get("epoch_changes"):
        last = lock["epoch_changes"][-1]
        events.append(
            f"foundation: operational epoch {last['old']} -> {last['new']}; {last['evidence']}"
        )
    elif status == "rejected" and lock.get("rejected_revisions"):
        last = lock["rejected_revisions"][-1]
        token = (last["old"], last["new"], len(state.stock))
        if lock.get("last_rejection") != token:
            lock["last_rejection"] = token
            events.append(
                f"foundation: rejected epoch revision {last['old']} -> {last['new']}; "
                "a forecast does not authorise another stock row"
            )


def _record_agenda(lock: dict, agenda: FoundationAgenda, campaign: FoundationCampaign) -> None:
    lock["required_cards"] = [
        {
            "id": item.prerequisite_id,
            "kind": item.kind,
            "rank": item.rank,
            "achieved": bool(item.achieved),
            "column": None if item.column is None else item.column + 1,
        }
        for item in agenda.prerequisites
    ]
    lock["achieved_prerequisites"] = [
        item.prerequisite_id for item in agenda.prerequisites if item.achieved
    ]
    lock["outstanding"] = [
        item.prerequisite_id for item in agenda.prerequisites if not item.achieved
    ]
    lock["campaign_blockers"] = list(campaign.blockers)
    lock["alternatives"] = [item.label for item in agenda.alternatives]
    lock["suspensions"] = sorted(str(item) for item in lock.get("suspended_notes", ()))
    lock["receiving"] = list(campaign.pre_deal_receiver_requirements[:6])
    if not lock.get("rationale_frozen"):
        lock["original_rationale"] = list(campaign.rationale[:3])
        lock["rationale_frozen"] = True


def campaign_record_public(lock: dict) -> dict:
    """JSON-safe view of the persistent foundation campaign record."""

    def _plain(value):
        if isinstance(value, tuple):
            return [_plain(item) for item in value]
        if isinstance(value, list):
            return [_plain(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _plain(item) for key, item in value.items()}
        return value

    return {
        "label": lock.get("epoch_label") or lock.get("label"),
        "original_epoch": lock.get("original_epoch"),
        "original_rationale": _plain(lock.get("original_rationale") or []),
        "theoretical_epoch": lock.get("theoretical_epoch"),
        "operational_epoch": lock.get("operational_epoch"),
        "analysed_epoch": lock.get("analysed_epoch"),
        "required_cards": _plain(lock.get("required_cards") or []),
        "outstanding": list(lock.get("outstanding") or []),
        "achieved_prerequisites": list(lock.get("achieved_prerequisites") or []),
        "blockers": list(lock.get("campaign_blockers") or []),
        "unresolved_access": list(lock.get("unresolved_access") or []),
        "receiving": list(lock.get("receiving") or []),
        "cost_invested": lock.get("cost_invested", 0),
        "alternatives": list(lock.get("alternatives") or []),
        "suspensions": list(lock.get("suspensions") or []),
        "epoch_changes": _plain(lock.get("epoch_changes") or []),
        "rejected_revisions": _plain(lock.get("rejected_revisions") or []),
        "completed": _plain(lock.get("completed") or []),
        "campaign_changes": list(lock.get("campaign_changes") or []),
        "feasibility_status": lock.get("feasibility_status"),
    }


def locate_source(state: SpiderState, source_key: str):
    """Return the physical card named by a tableau source key, if it is still there."""

    parts = str(source_key).split(":")
    if len(parts) != 4 or parts[0] != "tableau":
        return None
    column = int(parts[1])
    zone = parts[2]
    index = int(parts[3])
    if not 0 <= column < len(state.columns):
        return None
    sequence = state.columns[column].face_up if zone == "up" else state.columns[column].face_down
    if not 0 <= index < len(sequence):
        return None
    return sequence[index], column, zone, index


def _cover_depth(state: SpiderState, card: Card) -> Optional[int]:
    for column in state.columns:
        for index, item in enumerate(column.face_down):
            if item is card:
                return len(column.face_up) + (len(column.face_down) - 1 - index)
        for index, item in enumerate(column.face_up):
            if item is card:
                return len(column.face_up) - 1 - index
    return None


def _legally_movable_head(state: SpiderState, card: Card) -> bool:
    """True when a legal move starts at this card. Face-up alone is not enough."""

    for src, column in enumerate(state.columns):
        for index, item in enumerate(column.face_up):
            if item is not card:
                continue
            run_length = len(column.face_up) - index
            return any(
                state.can_move(src, dst, run_length) for dst in range(len(state.columns)) if dst != src
            )
    return False


def _obstruction_labels(state: SpiderState, card: Card) -> Tuple[str, ...]:
    for column in state.columns:
        for index, item in enumerate(column.face_up):
            if item is card:
                return tuple(str(other) for other in column.face_up[index + 1 :])
        for index, item in enumerate(column.face_down):
            if item is card:
                covered = [str(other) for other in column.face_up]
                covered.extend(str(other) for other in column.face_down[index + 1 :])
                return tuple(covered)
    return ()


def _fingerprint(state: SpiderState) -> tuple:
    parts = []
    for column in state.columns:
        parts.append(
            (
                tuple((card.suit, card.rank) for card in column.face_down),
                tuple((card.suit, card.rank) for card in column.face_up),
            )
        )
    return (tuple(parts), len(state.stock), len(state.foundations))


def _exposed_descending_run(column) -> Tuple[Card, ...]:
    """Same-suit descending run sitting on the top of one column."""

    up = column.face_up
    if not up:
        return ()
    start = len(up) - 1
    suit = up[start].suit
    while start > 0 and up[start - 1].suit == suit and up[start - 1].rank == up[start].rank + 1:
        start -= 1
    return tuple(up[start:])


def covers_productive_run(state: SpiderState, action: Action) -> bool:
    """True when a move hides or splits an exposed same-suit run of length at least 7.

    A same-suit join, and a move of the whole run onto an empty column, keep
    the run available. Those are not covers.
    """

    if not action or action == ("deal",):
        return False
    src, dst, k = action
    if k <= 0 or src == dst:
        return False
    source = state.columns[src]
    if k > len(source.face_up):
        return False
    moving = source.face_up[-k:]
    if not moving:
        return False
    dest_run = _exposed_descending_run(state.columns[dst])
    if len(dest_run) >= 7 and moving[0].suit != dest_run[0].suit:
        return True
    src_run = _exposed_descending_run(source)
    if len(src_run) < 7 or k > len(src_run):
        return False
    if moving[0].suit != src_run[0].suit:
        return False
    dest_top = state.columns[dst].top()
    if k == len(src_run) and dest_top is None:
        return False
    if dest_top is not None and dest_top.suit == moving[0].suit and dest_top.rank == moving[0].rank + 1:
        return False
    return True


def choose_without_unjustified_cover(state: SpiderState, choice: Candidate, considered: Sequence[Candidate]):
    """Prefer a considered move that leaves a productive run exposed.

    A plan that names a recoverable temporary park is left alone. Returns
    the choice and a log line. An empty log line means the choice did not change.
    """

    if choice is None or not choice.actions:
        return choice, ""
    action = choice.actions[0]
    if not covers_productive_run(state, action):
        return choice, ""
    if any("fact: temporary park is recoverable" in item for item in choice.evidence):
        return choice, ""
    if choice.kind in {"FOUNDATION", "BOTTLENECK"}:
        return choice, ""
    for item in considered:
        if item.candidate_id == choice.candidate_id or not item.actions:
            continue
        if item.actions[0] == ("deal",):
            continue
        if covers_productive_run(state, item.actions[0]):
            continue
        return item, (
            f"run guard: {format_action(action)} would cover a productive run; "
            f"play {format_action(item.actions[0])}"
        )
    return choice, ""


@dataclass(frozen=True)
class KingAccess:
    """One physical copy of the rank a nearly complete run still needs."""

    suit: str
    rank: int
    column: int
    zone: str
    depth: int
    face_up: bool
    accessible: bool
    blockers: Tuple[str, ...]
    movable_runs: Tuple[int, ...]
    investment: int
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class BottleneckPlan:
    """Bounded search for one missing connection on a nearly complete foundation."""

    status: str
    suit: str
    run_column: int
    run_length: int
    actions: Tuple[Action, ...]
    alternate_actions: Tuple[Action, ...]
    cost: int
    nodes: int
    kings: Tuple[KingAccess, ...]
    foundations_after: int
    zero_cost_expansions: int
    cheapest_zero_edge: Optional[int]
    covers_run: bool
    note: str
    events: Tuple[str, ...]


def _nearly_complete_runs(state: SpiderState) -> List[Tuple[int, Tuple[Card, ...]]]:
    """Exposed same-suit runs that are one rank short of a foundation, ace on top."""

    found = []
    for index, column in enumerate(state.columns):
        run = _exposed_descending_run(column)
        if len(run) < 12 or run[-1].rank != 1 or run[0].rank != len(run):
            continue
        found.append((index, run))
    found.sort(key=lambda item: -len(item[1]))
    return found


def _locate_rank(state: SpiderState, suit: str, rank: int) -> List[tuple]:
    found = []
    for column_index, column in enumerate(state.columns):
        for index, card in enumerate(column.face_up):
            if card.suit == suit and card.rank == rank:
                depth = len(column.face_up) - 1 - index
                found.append((depth, column_index, "up", index, card))
        for index, card in enumerate(column.face_down):
            if card.suit == suit and card.rank == rank:
                depth = len(column.face_up) + (len(column.face_down) - 1 - index)
                found.append((depth, column_index, "down", index, card))
    found.sort(key=lambda item: (item[0], item[1]))
    return found


def _movable_cover(state: SpiderState, column: int, zone: str, index: int) -> Tuple[Tuple[str, ...], Tuple[int, ...], int]:
    """Cards above one card, which suffixes can move, and a move-count estimate."""

    col = state.columns[column]
    if zone == "down":
        labels = [str(card) for card in col.face_down[index + 1 :]]
        labels.extend(str(card) for card in col.face_up)
        return tuple(labels), (), len(labels)
    cover = col.face_up[index + 1 :]
    labels = tuple(str(card) for card in cover)
    movable: List[int] = []
    remaining = len(cover)
    guard = 0
    while remaining > 0 and guard < 13:
        guard += 1
        found_k = 0
        for k in range(remaining, 0, -1):
            if any(state.can_move(column, dst, k) for dst in range(len(state.columns)) if dst != column):
                found_k = k
                break
        if found_k == 0:
            break
        movable.append(found_k)
        remaining -= found_k
    investment = len(movable) + remaining
    return labels, tuple(movable), investment


def _analyse_kings(state: SpiderState, suit: str, rank: int, run_column: int) -> Tuple[KingAccess, ...]:
    analyses = []
    for depth, column, zone, index, _card in _locate_rank(state, suit, rank):
        labels, movable, investment = _movable_cover(state, column, zone, index)
        face_up = zone == "up"
        accessible = bool(face_up and depth == 0)
        notes = []
        if not face_up:
            notes.append("this copy is face-down, so it is not an exposed receiver")
        elif depth > 0:
            notes.append("face-up is not a legal receiver while cards cover this king")
        else:
            notes.append("this king is the head of its column")
        if accessible and state.can_move(run_column, column, 12):
            notes.append("the 12-card run can move onto this king now")
        elif column == run_column:
            notes.append("this king shares the run's column")
        analyses.append(
            KingAccess(
                suit=suit,
                rank=rank,
                column=column,
                zone=zone,
                depth=int(depth),
                face_up=face_up,
                accessible=accessible,
                blockers=labels,
                movable_runs=movable,
                investment=int(investment),
                notes=tuple(notes),
            )
        )
    return tuple(analyses)


def _disruption(state: SpiderState, action: Action, suit: str) -> int:
    """Ordering penalty only. It is not added to the corrected MobilityWare cost."""

    penalty = 8 if covers_productive_run(state, action) else 0
    src, _dst, k = action
    column = state.columns[src]
    if k < len(column.face_up):
        for index, card in enumerate(column.face_up):
            if card.suit == suit and card.rank == 13 and index < len(column.face_up) - k:
                penalty -= 1
                break
    return penalty


def _search_completion(
    state: SpiderState,
    *,
    max_cost: int,
    max_nodes: int,
    deadline: float,
    avoid_dst: Optional[int] = None,
) -> dict:
    """Dijkstra on corrected cost. Zero-cost edges pop before one-cost edges."""

    start_foundations = len(state.foundations)
    seen = {_fingerprint(state): 0}
    heap = [(0, 0, 0, state, ())]
    sequence = 0
    nodes = 0
    beyond = False
    zero_cost_expansions = 0
    cheapest_zero_edge: Optional[int] = None
    while heap and nodes < max_nodes:
        if time.perf_counter() >= deadline:
            return {
                "status": "RESOURCE_LIMIT",
                "actions": (),
                "cost": 0,
                "nodes": nodes,
                "beyond": True,
                "zero_cost_expansions": zero_cost_expansions,
                "cheapest_zero_edge": cheapest_zero_edge,
            }
        cost, _penalty, _order, current, path = heapq.heappop(heap)
        nodes += 1
        if len(current.foundations) > start_foundations:
            return {
                "status": "FOUND",
                "actions": tuple(path),
                "cost": int(cost),
                "nodes": nodes,
                "beyond": beyond,
                "zero_cost_expansions": zero_cost_expansions,
                "cheapest_zero_edge": cheapest_zero_edge,
            }
        if cost >= max_cost:
            for action in current.enumerate_moves():
                trial = current.clone()
                try:
                    step = apply_action(trial, action)
                except ValueError:
                    continue
                if cost + step > max_cost and _fingerprint(trial) not in seen:
                    beyond = True
                    break
            continue
        for action in current.enumerate_moves():
            if avoid_dst is not None and action[1] == avoid_dst and action[2] >= 12:
                continue
            trial = current.clone()
            try:
                step = apply_action(trial, action)
            except ValueError:
                continue
            next_cost = cost + int(step)
            if int(step) == 0:
                zero_cost_expansions += 1
                if cheapest_zero_edge is None or next_cost < cheapest_zero_edge:
                    cheapest_zero_edge = next_cost
            if next_cost > max_cost:
                if _fingerprint(trial) not in seen:
                    beyond = True
                continue
            key = _fingerprint(trial)
            previous = seen.get(key)
            if previous is not None and previous <= next_cost:
                continue
            seen[key] = next_cost
            sequence += 1
            suit = ""
            run = _exposed_descending_run(current.columns[action[0]]) if action != ("deal",) else ()
            if run:
                suit = run[0].suit
            penalty = _disruption(current, action, suit) if suit else (8 if covers_productive_run(current, action) else 0)
            heapq.heappush(heap, (next_cost, penalty, sequence, trial, path + (action,)))
    if nodes >= max_nodes or time.perf_counter() >= deadline:
        return {
            "status": "RESOURCE_LIMIT",
            "actions": (),
            "cost": 0,
            "nodes": nodes,
            "beyond": True,
            "zero_cost_expansions": zero_cost_expansions,
            "cheapest_zero_edge": cheapest_zero_edge,
        }
    status = "NOT_FOUND_WITHIN_BOUND" if beyond else "GRAPH_EXHAUSTED"
    return {
        "status": status,
        "actions": (),
        "cost": 0,
        "nodes": nodes,
        "beyond": beyond,
        "zero_cost_expansions": zero_cost_expansions,
        "cheapest_zero_edge": cheapest_zero_edge,
    }


def _verified_cost(state: SpiderState, actions: Sequence[Action]) -> Optional[int]:
    trial = state.clone()
    spent = 0
    try:
        for action in actions:
            spent += step_cost(trial, action)
            apply_action(trial, action)
    except ValueError:
        return None
    if len(trial.foundations) <= len(state.foundations):
        return None
    return spent


def plan_foundation_bottleneck(
    state: SpiderState,
    *,
    max_cost: int = 8,
    max_nodes: int = 2500,
    time_left: float = 1.0,
) -> BottleneckPlan:
    """Search for a legal way to finish an exposed run that is one rank short.

    Both physical copies of the missing rank are analysed. Face-up and covered
    is not accessible. Corrected MobilityWare cost orders the search, so a
    zero-cost transfer is cheaper than a one-cost move. A node cap or a
    timeout is inconclusive. Exhausting the tableau component is a fact about
    this position with the stock left untouched, not a retired suit.
    """

    runs = _nearly_complete_runs(state)
    if not runs:
        return BottleneckPlan(
            "NO_BOTTLENECK",
            "",
            -1,
            0,
            (),
            (),
            0,
            0,
            (),
            len(state.foundations),
            0,
            None,
            False,
            "no exposed same-suit run of length 12 or more is waiting on one rank",
            (),
        )
    run_column, run = runs[0]
    suit = run[0].suit
    needed = run[0].rank + 1
    kings = _analyse_kings(state, suit, needed, run_column)
    king_text = ", ".join(
        f"column {item.column + 1} depth {item.depth} zone {item.zone} blockers {' '.join(item.blockers) or 'none'}"
        for item in kings
    ) or "no copy of the required rank is on the tableau"
    common = (
        f"foundation bottleneck: {suit} run length {len(run)} on column {run_column + 1} "
        f"needs rank {needed}; copies: {king_text}"
    )
    if time_left <= 0:
        note = "the time guard stopped the bottleneck probe before it expanded; this is not infeasibility"
        return BottleneckPlan(
            "RESOURCE_LIMIT",
            suit,
            run_column,
            len(run),
            (),
            (),
            0,
            0,
            kings,
            len(state.foundations),
            0,
            None,
            False,
            note,
            (common, f"foundation bottleneck: {note}"),
        )
    deadline = time.perf_counter() + float(time_left)
    primary = _search_completion(
        state,
        max_cost=max_cost,
        max_nodes=max_nodes,
        deadline=deadline,
    )
    actions = tuple(primary["actions"])
    cost = int(primary["cost"])
    covers = False
    if primary["status"] == "FOUND":
        verified = _verified_cost(state, actions)
        if verified is None:
            primary = {**primary, "status": "RESOURCE_LIMIT", "actions": (), "cost": 0}
            actions = ()
            cost = 0
        else:
            cost = verified
            probe = state.clone()
            for action in actions:
                if covers_productive_run(probe, action):
                    covers = True
                apply_action(probe, action)
    alternate: Tuple[Action, ...] = ()
    avoid = actions[-1][1] if actions and actions[-1] != ("deal",) else None
    remaining = deadline - time.perf_counter()
    if primary["status"] == "FOUND" and avoid is not None and remaining > 0.05 and len(kings) > 1:
        second = _search_completion(
            state,
            max_cost=max_cost,
            max_nodes=min(800, max_nodes),
            deadline=time.perf_counter() + min(0.35, remaining),
            avoid_dst=avoid,
        )
        if second["status"] == "FOUND" and tuple(second["actions"]) != actions:
            if _verified_cost(state, second["actions"]) is not None:
                alternate = tuple(second["actions"])
    status = primary["status"]
    if status == "FOUND":
        note = f"replayed sequence removes a foundation at corrected cost {cost}"
    elif status == "GRAPH_EXHAUSTED":
        note = (
            "every legal tableau successor inside the cost bound was expanded; "
            "the stock was not dealt; this is stronger than a node cap and is not a proof "
            "the suit can never finish after a later deal"
        )
    elif status == "NOT_FOUND_WITHIN_BOUND":
        note = (
            f"no completion was found at corrected cost {max_cost} or less; "
            "states past that bound were not expanded; this is not infeasibility"
        )
    else:
        note = (
            f"bottleneck search stopped at {primary['nodes']} nodes or the time guard; "
            "a timeout or a node cap is not infeasibility"
        )
    events = [common, "fact: face-up does not make a covered card a legal receiver", f"foundation bottleneck: {note}"]
    if kings:
        events.append(f"foundation bottleneck: examined {len(kings)} physical copies")
    return BottleneckPlan(
        status,
        suit,
        run_column,
        len(run),
        actions,
        alternate,
        cost,
        int(primary["nodes"]),
        kings,
        len(state.foundations) + (1 if status == "FOUND" else 0),
        int(primary["zero_cost_expansions"]),
        primary["cheapest_zero_edge"],
        covers,
        note,
        tuple(events),
    )


def _bottleneck_cache_hit(cache: dict, probe_key: tuple):
    """Reuse a bottleneck result only when that probe's assumptions cover this one.

    A resource limit is not stored. An exhaustion inside a lower cost ceiling
    does not answer a higher ceiling, and a tableau-only result does not answer
    a probe that is allowed to deal.
    """

    if probe_key in cache:
        return cache[probe_key]
    fingerprint, allow_deals, max_cost, _max_nodes, strategy = probe_key
    for key, status in cache.items():
        if not isinstance(key, tuple) or len(key) != 5:
            continue
        stored_fp, stored_deals, stored_cost, _stored_nodes, stored_strategy = key
        if stored_fp != fingerprint or stored_deals != allow_deals or stored_strategy != strategy:
            continue
        if status == "FOUND" and stored_cost <= max_cost:
            return status
        if status in {"GRAPH_EXHAUSTED", "NOT_FOUND_WITHIN_BOUND"} and stored_cost >= max_cost:
            return status
    return None


def _bottleneck_proposal(state, g, campaign, agenda, lock, events, time_left, refused):
    """One live objective when a 12-card run is blocked on its last connection."""

    runs = _nearly_complete_runs(state)
    if not runs:
        return None
    fingerprint = _fingerprint(state)
    cache = lock.setdefault("bottleneck_cache", {})
    probe_key = (fingerprint, False, 8, 2500, "tableau-completion")
    cached = _bottleneck_cache_hit(cache, probe_key)
    if cached is not None:
        if cached in {"GRAPH_EXHAUSTED", "NOT_FOUND_WITHIN_BOUND", "FOUND"}:
            events.append(
                f"foundation bottleneck: cached {cached}; the same probe is not repeated; "
                "this is not infeasibility"
            )
        return None
    if time_left < 0.05:
        events.append("foundation bottleneck: time guard skipped the probe; this is not infeasibility")
        return None
    started = time.perf_counter()
    plan = plan_foundation_bottleneck(
        state,
        max_cost=8,
        max_nodes=2500,
        time_left=min(1.2, float(time_left)),
    )
    _add_time(lock, "bottleneck", time.perf_counter() - started)
    if plan.status != "RESOURCE_LIMIT":
        cache[probe_key] = plan.status
    events.extend(plan.events)
    if plan.status != "FOUND" or not plan.actions:
        return None
    ident = f"bottleneck:{plan.suit}:{plan.run_column}"
    if ident in refused:
        return None
    if plan.alternate_actions:
        lock["pending_alternate_bottleneck"] = list(plan.alternate_actions)
    rendered = " ".join(format_action(action) for action in plan.actions)
    blockers = "; ".join(
        f"column {item.column + 1}: {' '.join(item.blockers) or 'none'}" for item in plan.kings
    )
    evidence = [
        "fact: face-up does not make a covered king a legal receiver",
        f"fact: examined {len(plan.kings)} physical copies",
        f"fact: blockers {blockers or 'none'}",
        f"fact: legal sequence {rendered}",
        f"fact: corrected cost of the sequence is {plan.cost}",
        "fact: a bounded miss would be inconclusive, not infeasibility",
    ]
    if plan.covers_run:
        evidence.append("fact: temporary park is recoverable")
    else:
        evidence.append("fact: the required run stays available until it is moved onto the king")
    candidate = _make_candidate(
        g,
        ident,
        "BOTTLENECK",
        plan.actions,
        hold=True,
        benefit=12.0,
        evidence=_evidence(campaign, agenda, *evidence),
        purpose="expose the receiver and complete the nearly finished foundation",
    )
    return _proposal(
        candidate,
        "selected: foundation bottleneck has a replayed completion",
        events,
        False,
        agenda,
    )


def obstructed_tableau_sources(state: SpiderState, campaign: FoundationCampaign) -> Tuple[tuple, ...]:
    """Chosen tableau cards that are not the head of a legal move."""

    found = []
    for need in campaign.rank_needs:
        chosen = need.chosen
        if chosen is None or not str(chosen.source_key).startswith("tableau:"):
            continue
        if chosen.kind == RankSourceKind.ALREADY_USABLE:
            continue
        located = locate_source(state, chosen.source_key)
        if located is None:
            continue
        card, column, zone, _index = located
        if _legally_movable_head(state, card):
            continue
        depth = _cover_depth(state, card)
        if depth is None:
            continue
        found.append((depth, -need.rank, chosen.source_key, card, column, zone))
    found.sort(key=lambda item: (item[0], item[1], item[2]))
    return tuple(found)


_EXECUTABLE_ACCESS = frozenset({"unlocked", "exposed", "progress"})
_EXHAUSTIVE_MISS = frozenset(
    {"GRAPH_EXHAUSTED_WITHIN_BOUND", "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"}
)


def excavation_cache_key(fingerprint, source_key, allow_deals, max_cost, max_nodes, strategy):
    """Identity of one excavation probe, including the limits that bound it."""

    return (
        fingerprint,
        str(source_key),
        bool(allow_deals),
        int(max_cost),
        int(max_nodes),
        str(strategy),
    )


def excavation_probe_category(plan: AccessPlan) -> str:
    """Classify a finished probe without treating a node cap as infeasibility."""

    if plan.status == "progress":
        return "PARTIAL_PROGRESS"
    if plan.status in {"unlocked", "exposed"}:
        return "SUCCESS"
    if plan.status in {"NODE_LIMIT", "TIME_LIMIT", "PROBE_LIMIT"}:
        return plan.status
    if plan.status in _EXHAUSTIVE_MISS:
        return plan.status
    return "PROBE_LIMIT"


def excavation_cache_lookup(cache: dict, key: tuple) -> Optional[AccessPlan]:
    """Return a probe that is safe to reuse for ``key``.

    An exact key is never repeated. A success whose corrected cost fits the
    requested ceiling is reused. An exhaustive negative covers the same
    strategy only up to the cost it actually exhausted. A node cap, a time
    cap, or a partial result does not answer a larger or different probe.
    """

    if key in cache:
        return cache[key]
    fingerprint, source_key, allow_deals, max_cost, _max_nodes, strategy = key
    for stored_key, plan in cache.items():
        if not isinstance(stored_key, tuple) or len(stored_key) != 6:
            continue
        stored_fp, stored_src, stored_deals, stored_cost, _stored_nodes, stored_strategy = stored_key
        if (
            stored_fp != fingerprint
            or stored_src != source_key
            or stored_deals != allow_deals
            or stored_strategy != strategy
        ):
            continue
        category = excavation_probe_category(plan)
        if category == "SUCCESS" and plan.cost <= max_cost and stored_cost <= max_cost:
            return plan
        if category in _EXHAUSTIVE_MISS and not plan.actions and stored_cost >= max_cost:
            return plan
    return None


def _column_of_card(state: SpiderState, card: Card) -> Optional[int]:
    for index, column in enumerate(state.columns):
        if any(item is card for item in column.face_down) or any(item is card for item in column.face_up):
            return index
    return None


def _cards_above(state: SpiderState, card: Card) -> List[Card]:
    """Physical cards above ``card``, top first. Identity is not a move."""

    for column in state.columns:
        for index, item in enumerate(column.face_up):
            if item is card:
                return list(reversed(column.face_up[index + 1 :]))
        for index, item in enumerate(column.face_down):
            if item is card:
                above = list(column.face_down[index + 1 :])
                above.extend(column.face_up)
                return list(reversed(above))
    return []


def _missing_receiver_count(state: SpiderState, card: Card) -> int:
    """How many cards above the target still lack a distinct legal home.

    An exposed rank can receive one blocker. An empty column can receive one
    blocker. This number orders the search. It does not prune.
    """

    supply: Dict[int, int] = {}
    empties = 0
    for column in state.columns:
        if column.is_empty():
            empties += 1
            continue
        top = column.top()
        if top is not None:
            supply[top.rank] = supply.get(top.rank, 0) + 1
    missing = 0
    for blocker in _cards_above(state, card):
        needed = blocker.rank - 1
        if needed >= 1 and supply.get(needed, 0) > 0:
            supply[needed] -= 1
        elif empties > 0:
            empties -= 1
        else:
            missing += 1
    return missing


def _peel_widths(state: SpiderState, column_index: int, card: Card) -> List[int]:
    """Legal suffix lengths that sit strictly above ``card``, or 1 when it is the top."""

    column = state.columns[column_index]
    up = column.face_up
    if not up:
        return []
    if any(item is card for item in column.face_down):
        above = len(up)
    else:
        index = next((cursor for cursor, item in enumerate(up) if item is card), None)
        if index is None:
            return []
        above = len(up) - 1 - index
    if above == 0:
        return [1]
    return [k for k in range(1, above + 1) if state.is_movable_run(up[-k:])]


def _dead_after_peel(state: SpiderState, src: int, card: Card) -> bool:
    """True when the peel spent the last empty column and the next card cannot move."""

    if _legally_movable_head(state, card):
        return False
    depth = _cover_depth(state, card)
    if depth is None or depth == 0:
        return depth is None
    if any(column.is_empty() for column in state.columns):
        return False
    column = state.columns[src]
    if not column.face_up:
        return False
    return not any(state.can_move(src, dst, 1) for dst in range(len(state.columns)) if dst != src)


def _safe_peel(state: SpiderState, card: Card, protected, max_cost: int):
    """Greedy legal peels that keep a home for the next card.

    A step that raises cover is kept when it also creates a receiver. A step
    that fills the last empty column and leaves the next card with nowhere to
    go is not taken. That rejection is one path, not a proof.
    """

    actions: List[Action] = []
    cost = 0
    current = state
    start = _cover_depth(state, card)
    if start is None:
        return (), 0, "missing", None
    seen = {_fingerprint(current)}
    for _guard in range(16):
        if cost >= max_cost and max_cost >= 0:
            break
        if _legally_movable_head(current, card):
            return tuple(actions), cost, "unlocked", 0
        depth = _cover_depth(current, card)
        if depth is None:
            return tuple(actions), cost, "missing", None
        if depth == 0:
            return tuple(actions), cost, "exposed", 0
        src = _column_of_card(current, card)
        if src is None:
            return tuple(actions), cost, "missing", None
        before_missing = _missing_receiver_count(current, card)
        best = None
        for k in _peel_widths(current, src, card):
            for dst in range(len(current.columns)):
                if dst == src or not current.can_move(src, dst, k):
                    continue
                action = (src, dst, k)
                if _splits_protected(current, action, protected):
                    continue
                trial = current.clone()
                try:
                    step = apply_action(trial, action)
                except ValueError:
                    continue
                if max_cost >= 0 and cost + step > max_cost:
                    continue
                if _fingerprint(trial) in seen or _dead_after_peel(trial, src, card):
                    continue
                new_depth = _cover_depth(trial, card)
                if new_depth is None:
                    continue
                new_missing = _missing_receiver_count(trial, card)
                if new_depth > depth and new_missing >= before_missing and not _legally_movable_head(trial, card):
                    continue
                rank = (
                    0 if new_depth == 0 or _legally_movable_head(trial, card) else 1,
                    new_missing,
                    new_depth,
                    0 if current.columns[dst].top() is not None else 1,
                    -k,
                    dst,
                )
                if best is None or rank < best[0]:
                    best = (rank, action, trial, step, new_depth)
        if best is None:
            break
        _rank, action, current, step, _depth = best
        actions.append(action)
        cost += step
        seen.add(_fingerprint(current))
    depth = _cover_depth(current, card)
    if not actions or depth is None or start is None or depth >= start:
        if actions and _legally_movable_head(current, card):
            return tuple(actions), cost, "unlocked", 0
        return tuple(actions), cost, "none", depth
    if _legally_movable_head(current, card):
        status = "unlocked"
    elif depth == 0:
        status = "exposed"
    else:
        status = "progress"
    return tuple(actions), cost, status, depth


def _outcome_rank(status: str, depth: int, cost: int, length: int) -> tuple:
    order = {"unlocked": 0, "exposed": 1, "progress": 2}.get(status, 3)
    return (order, int(depth), int(cost), int(length))


def _commit_peel(state, card, protected, setup, setup_cost, max_cost: int):
    """Attach the longest legal peel that fits, if it advances the target."""

    room = max(0, int(max_cost) - int(setup_cost))
    fitted, fitted_cost, fitted_status, fitted_depth = _safe_peel(state, card, protected, room)
    full, full_cost, full_status, full_depth = _safe_peel(state, card, protected, 13)
    if full_status in {"unlocked", "exposed"} and setup_cost + full_cost <= max_cost:
        return tuple(setup) + tuple(full), setup_cost + full_cost, full_status, full_depth, True
    if fitted_status in _EXECUTABLE_ACCESS and fitted:
        return tuple(setup) + tuple(fitted), setup_cost + fitted_cost, fitted_status, fitted_depth, False
    if full_status in {"unlocked", "exposed"}:
        return tuple(setup), setup_cost, "PROBE_LIMIT", _cover_depth(state, card), True
    return None


def _make_access_plan(
    actions,
    cost,
    status,
    nodes,
    source_key,
    column,
    start,
    depth,
    obstruction,
    *,
    exhaustive=False,
    strategy="receiver-then-peel",
    allow_deals=False,
    max_cost_limit=0,
    max_nodes_limit=0,
    stop="",
    zero_cost_expansions=0,
) -> AccessPlan:
    return AccessPlan(
        tuple(actions),
        int(cost),
        status,
        int(nodes),
        source_key,
        int(column),
        int(start),
        int(start if depth is None else depth),
        tuple(obstruction),
        exhaustive=bool(exhaustive),
        strategy=strategy,
        allow_deals=bool(allow_deals),
        max_cost_limit=int(max_cost_limit),
        max_nodes_limit=int(max_nodes_limit),
        movable=status == "unlocked",
        stop=stop,
        zero_cost_expansions=int(zero_cost_expansions),
    )


def _search_excavation(
    state: SpiderState,
    card: Card,
    protected,
    *,
    max_cost: int,
    max_nodes: int,
    deadline,
    restrict_target: bool,
    allow_deals: bool,
):
    """Corrected-cost search. A receiver for the next blocker is the goal test.

    Primary key is corrected MobilityWare cost, so a zero-cost whole-column
    transfer is expanded before a cost-1 move. Cover may rise along the way.
    The target column stays still until a peel has a home, when
    ``restrict_target`` is set. That restriction is part of the strategy name.
    """

    start = _cover_depth(state, card)
    seen = {_fingerprint(state): 0}
    sequence = 0
    heap = [(0, _missing_receiver_count(state, card), 0, state, ())]
    nodes = 0
    zeros = 0
    best = None
    stop = ""
    while heap and nodes < max_nodes:
        if deadline is not None and nodes % 24 == 0 and time.perf_counter() >= deadline:
            stop = "TIME_LIMIT"
            break
        cost, _missing, _order, current, path = heapq.heappop(heap)
        nodes += 1
        if _cover_depth(current, card) is None:
            continue
        committed = _commit_peel(current, card, protected, path, cost, max_cost)
        if committed is not None:
            actions, total, status, depth, finished = committed
            if status in _EXECUTABLE_ACCESS and actions:
                rank = _outcome_rank(status, 0 if depth is None else depth, total, len(actions))
                if best is None or rank < best[0]:
                    best = (rank, actions, total, status, depth)
                if status in {"unlocked", "exposed"} or finished:
                    chosen = best
                    return (
                        chosen[1],
                        chosen[2],
                        chosen[3],
                        chosen[4],
                        nodes,
                        zeros,
                        False,
                        "",
                    )
            elif status == "PROBE_LIMIT" and finished:
                return (), cost, "PROBE_LIMIT", _cover_depth(current, card), nodes, zeros, False, "COST_CEILING"
        if cost >= max_cost:
            continue
        blocked = _column_of_card(current, card) if restrict_target else None
        moves = list(current.enumerate_moves())
        if allow_deals and current.can_deal():
            moves.append(("deal",))
        for action in moves:
            if blocked is not None and action != ("deal",) and action[0] == blocked:
                continue
            if _splits_protected(current, action, protected):
                continue
            trial = current.clone()
            try:
                step = apply_action(trial, action)
            except ValueError:
                continue
            next_cost = cost + step
            if next_cost > max_cost:
                continue
            key = _fingerprint(trial)
            if key in seen and seen[key] <= next_cost:
                continue
            seen[key] = next_cost
            if step == 0:
                zeros += 1
            sequence += 1
            heapq.heappush(
                heap,
                (
                    next_cost,
                    _missing_receiver_count(trial, card),
                    sequence,
                    trial,
                    path + (action,),
                ),
            )
    if not stop:
        stop = "GRAPH_EXHAUSTED_WITHIN_BOUND" if nodes < max_nodes or not heap else "NODE_LIMIT"
        if nodes >= max_nodes and heap:
            stop = "NODE_LIMIT"
    exhaustive = stop == "GRAPH_EXHAUSTED_WITHIN_BOUND"
    if best is None:
        status = "TIME_LIMIT" if stop == "TIME_LIMIT" else stop
        return (), 0, status, start, nodes, zeros, exhaustive, stop
    _rank, actions, total, status, depth = best
    return actions, total, status, depth, nodes, zeros, exhaustive, stop


def plan_obstructed_access(
    state: SpiderState,
    card: Card,
    protected,
    *,
    source_key: str = "",
    column: int = -1,
    max_cost: int = 4,
    max_nodes: int = 2500,
    allow_deals: bool = False,
    strategy: str = "receiver-then-peel",
    deadline=None,
) -> Optional[AccessPlan]:
    """Bounded legal sequence that uncovers one physical card.

    Outcomes stay distinct. ``progress`` reduces cover. ``exposed`` turns the
    card face-up. ``unlocked`` makes it the head of a legal move. A node cap,
    a time cap, or a cost ceiling is not proof the card can never move.
    ``GRAPH_EXHAUSTED_WITHIN_BOUND`` exhausts only this cost, this action
    policy, and this deal policy. The engine generates every move.
    """

    start = _cover_depth(state, card)
    obstruction = _obstruction_labels(state, card)
    common = dict(
        source_key=source_key,
        column=column,
        strategy=strategy,
        allow_deals=allow_deals,
        max_cost_limit=max_cost,
        max_nodes_limit=max_nodes,
    )
    if start is None:
        return _make_access_plan(
            (),
            0,
            "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS",
            0,
            obstruction=obstruction,
            start=0,
            depth=0,
            exhaustive=True,
            stop="card is not on the tableau",
            **common,
        )
    if _legally_movable_head(state, card):
        return None
    root = _commit_peel(state, card, protected, (), 0, max_cost)
    if root is not None:
        actions, total, status, depth, finished = root
        if status in {"unlocked", "exposed"} or (status == "progress" and finished):
            return _make_access_plan(
                actions,
                total,
                status,
                1,
                obstruction=obstruction,
                start=start,
                depth=depth,
                stop="",
                **common,
            )
    restrict = strategy != "unrestricted"
    actions, total, status, depth, nodes, zeros, exhaustive, stop = _search_excavation(
        state,
        card,
        protected,
        max_cost=max_cost,
        max_nodes=max_nodes,
        deadline=deadline,
        restrict_target=restrict,
        allow_deals=allow_deals,
    )
    used_strategy = strategy
    target_src = _column_of_card(state, card)
    target_can_move = bool(
        target_src is not None
        and any(move[0] == target_src for move in state.enumerate_moves())
    )
    if (
        restrict
        and status not in _EXECUTABLE_ACCESS
        and exhaustive
        and target_can_move
        and nodes < max_nodes
        and (deadline is None or time.perf_counter() < deadline)
    ):
        extra_actions, extra_total, extra_status, extra_depth, extra_nodes, extra_zeros, extra_ex, extra_stop = (
            _search_excavation(
                state,
                card,
                protected,
                max_cost=max_cost,
                max_nodes=max(0, max_nodes - nodes),
                deadline=deadline,
                restrict_target=False,
                allow_deals=allow_deals,
            )
        )
        nodes += extra_nodes
        zeros += extra_zeros
        used_strategy = strategy + "+unrestricted"
        if extra_status in _EXECUTABLE_ACCESS or (
            extra_status in _EXECUTABLE_ACCESS
            or _outcome_rank(extra_status, extra_depth or start, extra_total, len(extra_actions))
            < _outcome_rank(status, depth or start, total, len(actions))
        ):
            if extra_actions or extra_status in _EXECUTABLE_ACCESS:
                actions, total, status, depth = extra_actions, extra_total, extra_status, extra_depth
                exhaustive, stop = extra_ex, extra_stop
    if root is not None and root[2] in _EXECUTABLE_ACCESS:
        root_rank = _outcome_rank(root[2], root[3] if root[3] is not None else start, root[1], len(root[0]))
        found_rank = _outcome_rank(status, depth if depth is not None else start, total, len(actions))
        if root_rank < found_rank:
            actions, total, status, depth = root[0], root[1], root[2], root[3]
            stop = ""
    return _make_access_plan(
        actions,
        total,
        status if actions or status not in _EXECUTABLE_ACCESS else "PROBE_LIMIT",
        nodes,
        source_key,
        column,
        start,
        depth,
        obstruction,
        exhaustive=exhaustive and not actions,
        strategy=used_strategy,
        allow_deals=allow_deals,
        max_cost_limit=max_cost,
        max_nodes_limit=max_nodes,
        stop=stop,
        zero_cost_expansions=zeros,
    )


def _probe_stats(lock: dict) -> dict:
    return lock.setdefault(
        "probe_stats",
        {"hits": 0, "misses": 0, "expanded": 0, "inconclusive": 0, "nodes": 0, "revisits": 0},
    )


def _cached_excavation(
    state,
    card,
    protected,
    lock,
    *,
    source_key,
    column,
    max_cost,
    max_nodes,
    time_left,
    strategy="receiver-then-peel",
    deadline_s=2.0,
):
    """Run one excavation probe, or reuse one whose assumptions cover this call."""

    cache = lock.setdefault("excavation_cache", {})
    stats = _probe_stats(lock)
    # A global slack ceiling is additional corrected cost still allowed.
    # It narrows this probe. It does not turn a miss into infeasibility.
    capped = lock.get("cost_ceiling") if isinstance(lock, dict) else None
    if capped is not None:
        max_cost = min(int(max_cost), max(0, int(capped)))
    key = excavation_cache_key(_fingerprint(state), source_key, False, max_cost, max_nodes, strategy)
    cached = excavation_cache_lookup(cache, key)
    if cached is not None:
        stats["hits"] += 1
        if key not in cache:
            stats["revisits"] += 1
        if excavation_probe_category(cached) != "SUCCESS":
            stats["inconclusive"] += 1
        return cached
    if time_left < 0.05:
        depth = _cover_depth(state, card) or 0
        return _make_access_plan(
            (),
            0,
            "TIME_LIMIT",
            0,
            source_key,
            column,
            depth,
            depth,
            _obstruction_labels(state, card),
            strategy=strategy,
            max_cost_limit=max_cost,
            max_nodes_limit=max_nodes,
            stop="TIME_LIMIT",
        )
    deadline = time.perf_counter() + max(0.05, min(float(deadline_s), float(time_left)))
    plan = plan_obstructed_access(
        state,
        card,
        protected,
        source_key=source_key,
        column=column,
        max_cost=max_cost,
        max_nodes=max_nodes,
        strategy=strategy,
        deadline=deadline,
    )
    stats["misses"] += 1
    if plan is None:
        depth = _cover_depth(state, card) or 0
        plan = _make_access_plan(
            (),
            0,
            "unlocked",
            0,
            source_key,
            column,
            depth,
            depth,
            (),
            strategy=strategy,
            max_cost_limit=max_cost,
            max_nodes_limit=max_nodes,
        )
    else:
        stats["nodes"] += int(plan.nodes)
        if excavation_probe_category(plan) != "SUCCESS":
            stats["inconclusive"] += 1
    cache[key] = plan
    return plan


def _excavation_is_executable(plan: Optional[AccessPlan]) -> bool:
    """A partial result counts only when the target's cover actually falls.

    Visibility and mobility are separate. A sequence whose net cover does not
    fall is not partial excavation, even if an intermediate move was legal.
    """

    if plan is None or not plan.actions or plan.status not in _EXECUTABLE_ACCESS:
        return False
    if plan.status == "progress" and plan.depth_after >= plan.depth_before:
        return False
    if plan.status in {"exposed", "unlocked"} and plan.depth_after != 0:
        return False
    return True


def _justified_expansion(plan: Optional[AccessPlan]) -> bool:
    """One larger probe is allowed when the last one was inconclusive for its own ceiling."""

    if plan is None or plan.status in {"unlocked", "exposed"}:
        return False
    if plan.movable and not plan.actions:
        return False
    category = excavation_probe_category(plan)
    if category == "SUCCESS":
        return False
    if category in _EXHAUSTIVE_MISS and int(plan.max_cost_limit) >= 8:
        return False
    return True


def _excavation_targets(state: SpiderState, campaign: FoundationCampaign) -> List[tuple]:
    """Connectors first, then chosen obstructed copies, then other buried cards."""

    wanted = set()
    for column in state.columns:
        run = _exposed_descending_run(column)
        if not run or run[0].suit != campaign.suit or len(run) < 2:
            continue
        if run[0].rank < 13:
            wanted.add(run[0].rank + 1)
        if run[-1].rank > 1:
            wanted.add(run[-1].rank - 1)
    targets = []
    seen = set()
    for depth, _neg_rank, source_key, card, column, _zone in obstructed_tableau_sources(state, campaign):
        role = "connector" if card.rank in wanted else "chosen"
        targets.append((0 if role == "connector" else 1, depth, source_key, card, column, role))
        seen.add(source_key)
    for depth, column, index, card in _buried_cards(state, campaign.suit):
        source_key = f"tableau:{column}:down:{index}"
        if source_key in seen or card.rank not in wanted:
            continue
        targets.append((0, depth, source_key, card, column, "connector"))
        seen.add(source_key)
    for depth, column, index, card in _buried_cards(state, campaign.suit):
        source_key = f"tableau:{column}:down:{index}"
        if source_key in seen:
            continue
        targets.append((2, depth, source_key, card, column, "buried"))
        seen.add(source_key)
        if len([item for item in targets if item[5] == "buried"]) >= 2:
            break
    targets.sort(key=lambda item: (item[0], item[1], item[2]))
    return targets


def _fragment_lengths(state: SpiderState, suit: str) -> int:
    best = 0
    for column in state.columns:
        run = _exposed_descending_run(column)
        if run and run[0].suit == suit:
            best = max(best, len(run))
    return best


def _shortens_long_fragment(state: SpiderState, actions, suit: str) -> bool:
    before = _fragment_lengths(state, suit)
    if before < 5:
        return False
    trial = state.clone()
    for action in actions:
        try:
            apply_action(trial, action)
        except ValueError:
            return False
    return _fragment_lengths(trial, suit) < before


def _access_candidate(g, campaign, agenda, plan: AccessPlan, *, purpose: str, shortens: bool = False):
    blockers = " ".join(plan.obstruction) if plan.obstruction else "none"
    rendered = " ".join(format_action(action) for action in plan.actions)
    benefit = {"unlocked": 4.0, "exposed": 3.0, "progress": 2.5}.get(plan.status, 2.0)
    evidence = [
        f"fact: obstruction above the card is {blockers}",
        f"fact: legal sequence {rendered}",
        f"fact: corrected cost of the sequence is {plan.cost}",
        f"fact: outcome {plan.status} cover {plan.depth_before} -> {plan.depth_after}",
        "fact: face-up does not mean the card is legally movable",
        "fact: visibility, mobility, and operational access are different outcomes",
        "fact: a probe limit is not infeasibility",
    ]
    if plan.status == "unlocked":
        evidence.append("fact: the card is the head of a legal move")
    elif plan.status == "exposed":
        evidence.append("fact: the card is face-up and is not yet a legal move")
    else:
        evidence.append("fact: partial excavation reduced cover and did not reveal the card")
    if shortens:
        benefit -= 1.5
        evidence.append("fact: the sequence covers a same-suit run of length at least 5")
    return _make_candidate(
        g,
        f"access:{plan.source_key}",
        "ACCESS",
        tuple(plan.actions),
        hold=True,
        benefit=benefit,
        evidence=_evidence(campaign, agenda, *evidence),
        purpose=purpose,
    )


def _empty_spent_without_receiver(state: SpiderState, card: Card, plan: AccessPlan, suit: str) -> bool:
    """True when the plan fills the last empty column and creates no receiver.

    A face-up card that a same-suit run can land on is a receiver. A card that
    becomes a legal head is mobile. Parking a blocker on the only empty column
    and leaving neither is not excavation progress.
    """

    if not plan.actions or plan.status == "unlocked":
        return False
    if not any(column.is_empty() for column in state.columns):
        return False
    trial = state.clone()
    try:
        for action in plan.actions:
            apply_action(trial, action)
    except ValueError:
        return True
    if any(column.is_empty() for column in trial.columns):
        return False
    column = _column_of_card(trial, card)
    if column is None or _legally_movable_head(trial, card):
        return False
    for src in range(len(trial.columns)):
        if src == column:
            continue
        face_up = trial.columns[src].face_up
        for width in range(1, len(face_up) + 1):
            run = face_up[-width:]
            if not run or run[0].suit != suit or not trial.is_movable_run(run):
                continue
            if trial.can_move(src, column, width):
                return False
    return True


def _access_proposal(state, g, campaign, agenda, lock, events, refused, time_left, waiting):
    if time_left < 0.15:
        return None
    started = time.perf_counter()
    targets = obstructed_tableau_sources(state, campaign)
    plan = None
    for depth, _rank, source_key, card, column, _zone in targets[:2]:
        ident = f"access:{source_key}"
        if ident in refused:
            continue
        found = _cached_excavation(
            state,
            card,
            agenda.protected_fragments,
            lock,
            source_key=source_key,
            column=column,
            max_cost=4,
            max_nodes=800,
            time_left=time_left,
        )
        if not _excavation_is_executable(found):
            note = f"{source_key} depth {depth} {excavation_probe_category(found) if found else 'missing'}"
            unresolved = lock.setdefault("unresolved_access", [])
            if note not in unresolved:
                unresolved.append(note)
            continue
        if _empty_spent_without_receiver(state, card, found, campaign.suit):
            events.append(
                f"foundation: {source_key} spends the only empty column and {card} "
                "is not a receiver for its suit; not played"
            )
            continue
        plan = found
        break
    _add_time(lock, "dependency_planning", time.perf_counter() - started)
    if plan is None:
        return None
    blockers = " ".join(plan.obstruction) if plan.obstruction else "none"
    events.append(
        f"foundation: {plan.source_key} is blocked by {blockers}; "
        f"a {len(plan.actions)}-move sequence {plan.status} cover {plan.depth_before} -> {plan.depth_after}"
    )
    events.append(
        "foundation: that sequence is one realisation; it does not move the operational epoch"
    )
    lock["active_access"] = {
        "source": plan.source_key,
        "status": plan.status,
        "actions": [format_action(action) for action in plan.actions],
        "waiting": waiting,
    }
    return _proposal(
        _access_candidate(
            g,
            campaign,
            agenda,
            plan,
            purpose="unblock a foundation prerequisite without dealing",
        ),
        "selected: foundation prerequisite can be unblocked",
        events,
        False,
        agenda,
    )


def _buried_cards(state: SpiderState, suit: str) -> List[tuple]:
    """Face-down cards of ``suit``, shallowest cover first."""

    found = []
    for column_index, column in enumerate(state.columns):
        for index, card in enumerate(column.face_down):
            if card.suit != suit:
                continue
            depth = len(column.face_up) + (len(column.face_down) - 1 - index)
            found.append((depth, column_index, index, card))
    found.sort(key=lambda item: (item[0], item[1], item[2]))
    return found


def _elapsed_access_proposal(state, g, campaign, agenda, lock, events, refused, time_left):
    """Excavate a foundation dependency after its target epoch has passed.

    A miss inside one budget is recorded and does not retire the suit. A later
    call with a larger ceiling, a different strategy, or a new state can run.
    """

    if time_left < 0.15:
        events.append("foundation: elapsed-epoch access probe hit the time guard; inconclusive")
        lock["feasibility_status"] = "PROBE_LIMIT"
        return None
    started = time.perf_counter()
    found_plans = []
    examined = 0
    for _role_rank, depth, source_key, card, column, role in _excavation_targets(state, campaign):
        if examined >= 2:
            break
        ident = f"access:{source_key}"
        if ident in refused:
            continue
        examined += 1
        relevant = role in {"connector", "chosen"}
        plan = _cached_excavation(
            state,
            card,
            agenda.protected_fragments,
            lock,
            source_key=source_key,
            column=column,
            max_cost=6,
            max_nodes=2000,
            time_left=time_left,
            deadline_s=3.0,
        )
        events.append(
            f"foundation: excavation {card} column {column + 1} role {role} "
            f"cover {depth} budget cost 6 nodes 2000 -> {excavation_probe_category(plan)} "
            f"status {plan.status} nodes {plan.nodes}"
        )
        if (
            relevant
            and not _excavation_is_executable(plan)
            and _justified_expansion(plan)
            and time_left > 1.0
        ):
            _probe_stats(lock)["expanded"] += 1
            plan = _cached_excavation(
                state,
                card,
                agenda.protected_fragments,
                lock,
                source_key=source_key,
                column=column,
                max_cost=8,
                max_nodes=4500,
                time_left=time_left - (time.perf_counter() - started),
                deadline_s=12.0,
            )
            events.append(
                f"foundation: expanded excavation {card} budget cost 8 nodes 4500 -> "
                f"{excavation_probe_category(plan)} status {plan.status} nodes {plan.nodes}"
            )
        if not _excavation_is_executable(plan):
            events.append(
                f"foundation: {excavation_probe_category(plan)} buried {card} on column {column + 1} "
                f"cover {depth}; this bound is not infeasibility"
            )
            lock["feasibility_status"] = excavation_probe_category(plan)
            continue
        found_plans.append(plan)
        # A partial peel is not operational access. Keep the second target
        # eligible. Stop early only for a reveal or an unlocked card that
        # leaves a long same-suit run intact.
        if plan.status in {"unlocked", "exposed"} and not _shortens_long_fragment(
            state, plan.actions, campaign.suit
        ):
            break
    _add_time(lock, "dependency_planning", time.perf_counter() - started)
    if not found_plans:
        return None
    def _rank(item: AccessPlan):
        shortens = _shortens_long_fragment(state, item.actions, campaign.suit)
        return (
            1 if shortens else 0,
            _outcome_rank(item.status, item.depth_after, item.cost, len(item.actions)),
        )
    plan = min(found_plans, key=_rank)
    shortens = _shortens_long_fragment(state, plan.actions, campaign.suit)
    events.append(
        f"foundation: excavation plays {len(plan.actions)} legal moves; "
        f"cover {plan.depth_before} -> {plan.depth_after}; outcome {plan.status}"
    )
    lock["feasibility_status"] = "REQUIRES_PREPARATION"
    lock["active_access"] = {
        "source": plan.source_key,
        "status": plan.status,
        "category": excavation_probe_category(plan),
        "actions": [format_action(action) for action in plan.actions],
        "cost": plan.cost,
    }
    return _proposal(
        _access_candidate(
            g,
            campaign,
            agenda,
            plan,
            purpose="excavate a buried foundation card after its stock epoch",
            shortens=shortens,
        ),
        "selected: buried card is an accessibility prerequisite",
        events,
        False,
        agenda,
    )


def recover_foundation_step(state, cards, g, cache, lock, blocked, time_left):
    """One bounded access step when no campaign proposal is executable.

    The search reuses ``plan_obstructed_access``. It does not start another
    kernel and it does not order moves by best-g. A miss is a probe limit.
    """

    events: List[str] = []
    if time_left < 0.15:
        events.append("foundation: recovery search stopped at the time guard")
        return None, tuple(events)
    state_key = canonical_state_key(state)
    if lock.get("recovery_key") == state_key:
        events.append("foundation: recovery already attempted on this state")
        return None, tuple(events)
    lock["recovery_key"] = state_key
    try:
        _feasibility, portfolio = load_portfolio(state, cards, cache)
    except (ValueError, KeyError) as exc:
        events.append(f"foundation: recovery analysis unavailable ({exc})")
        return None, tuple(events)
    refused = set(blocked)
    active = lock.get("label")
    order = [item for item in portfolio.campaigns if item.label != active]
    order.extend(item for item in portfolio.campaigns if item.label == active)
    started = time.perf_counter()
    examined = 0
    for campaign in order:
        if examined >= 3:
            break
        examined += 1
        status = campaign_near_term_status(state, campaign)
        events.append(
            f"foundation: recovery considers {campaign.label} status {status} "
            f"epoch {campaign.target_removal_epoch}"
        )
        buried = _buried_cards(state, campaign.suit)
        if not buried:
            continue
        depth, column, index, card = buried[0]
        source_key = f"tableau:{column}:down:{index}"
        ident = f"recover:{source_key}"
        if ident in refused:
            continue
        plan = _cached_excavation(
            state,
            card,
            (),
            lock,
            source_key=source_key,
            column=column,
            max_cost=4,
            max_nodes=600,
            time_left=time_left,
        )
        if not _excavation_is_executable(plan):
            events.append(
                f"foundation: {excavation_probe_category(plan)} recovery did not uncover {card} "
                f"at cover {depth}; this is not infeasibility"
            )
            continue
        _add_time(lock, "dependency_planning", time.perf_counter() - started)
        events.append(
            f"foundation: recovery plays {len(plan.actions)} moves to reach buried {card}"
        )
        lock["feasibility_status"] = "REQUIRES_PREPARATION"
        candidate = _make_candidate(
            g,
            ident,
            "ACCESS",
            tuple(plan.actions),
            hold=True,
            benefit=2.0,
            evidence=(
                f"fact: recovery uncovers {card} for {campaign.label}",
                f"fact: cover {plan.depth_before} -> {plan.depth_after}",
                f"fact: outcome {plan.status}",
                "fact: the sequence is a bounded access search, not a proof bound",
            ),
            purpose="recover access toward a foundation card",
        )
        return candidate, tuple(events)
    _add_time(lock, "dependency_planning", time.perf_counter() - started)
    legal = [action for action in all_legal_actions(state) if action != ("deal",)]
    events.append(
        "foundation: remaining legal tableau moves "
        + ", ".join(format_action(action) for action in legal)
    )
    events.append("foundation: recovery found no bounded access step")
    return None, tuple(events)


def planning_stall_detail(state: SpiderState, lock: dict) -> str:
    """Name the moves and campaigns a stall did not pretend to exhaust."""

    legal = [action for action in all_legal_actions(state) if action != ("deal",)]
    rendered = ", ".join(format_action(action) for action in legal) or "none"
    entered = ", ".join(lock.get("tried_labels") or []) or (lock.get("label") or "none")
    pending = [
        label
        for label in (lock.get("alternatives") or [])
        if label not in (lock.get("tried_labels") or [])
    ]
    return (
        f"legal actions: {rendered}. "
        f"campaigns entered: {entered}. "
        f"not entered: {', '.join(pending) or 'none'}. "
        f"feasibility: {lock.get('feasibility_status') or 'unclassified'}. "
        "a probe limit is not infeasibility"
    )


def _parent_sites_for_alignment(state: SpiderState, suit: str, rank: int):
    found = []
    for index, column in enumerate(state.columns):
        if any(card.suit == suit and card.rank == rank for card in column.face_up):
            found.append((index, "face-up"))
        elif any(card.suit == suit and card.rank == rank for card in column.face_down):
            found.append((index, "face-down"))
    return found


def plan_receiver_alignment(
    state: SpiderState,
    campaign: FoundationCampaign,
    *,
    max_cost: int = 3,
    max_expand: int = 500,
) -> Optional[object]:
    """Place a same-suit receiver for a chosen incoming card, when the replay wins."""

    row = next_stock_row(state)
    if row is None:
        return None
    chosen_columns = set()
    chosen_ranks = set()
    for need in campaign.rank_needs:
        chosen = need.chosen
        if chosen is None:
            continue
        chosen_ranks.add(need.rank)
        if chosen.stock_epoch == campaign.current_epoch + 1 and chosen.stock_column is not None:
            chosen_columns.add(chosen.stock_column)
    best = None
    notes: List[str] = []
    examined = 0
    for column, card in enumerate(row):
        if card.suit != campaign.suit or card.rank not in chosen_ranks:
            continue
        if chosen_columns and column not in chosen_columns:
            continue
        examined += 1
        if examined > 3:
            break
        if card.rank >= 13:
            compared = compare_exact_reception(state, (), column, campaign.suit)
            notes.append(
                f"incoming king on column {column + 1} is not a completed foundation; "
                f"queen-led follow-up is {compared.post_deal_queen_onto_king}"
            )
            continue
        places = _parent_sites_for_alignment(state, card.suit, card.rank + 1)
        elsewhere = [
            f"column {index + 1} ({zone})"
            for index, zone in places
            if index != column
        ]
        if elsewhere:
            notes.append(
                f"receiver for {card} is on {', '.join(elsewhere)}, "
                f"not on landing column {column + 1}"
            )
        objective = PreDealShapingObjective(
            code="same_suit_receiver",
            description=f"top of column {column + 1} receives {card}",
            target_column=column,
            incoming=card,
            predicate_key="same_suit_receiver",
            max_cost=max_cost,
        )
        found = run_bounded_shaping_probe(
            state, objective, max_cost=max_cost, max_expand=max_expand
        )
        if found.status == "already_satisfied":
            notes.append(
                f"receiver for {card} is already the top of column {column + 1}; "
                "no relocation is required"
            )
            continue
        if not found.found or not found.path:
            notes.append(
                f"receiver for {card} cannot legally reach column {column + 1} "
                f"within corrected cost {max_cost} ({found.status})"
            )
            continue
        compared = compare_exact_reception(state, found.path, column, campaign.suit)
        if compared.choice == "prepare" and (
            best is None or compared.preparation_cost < best.preparation_cost
        ):
            best = compared
        elif compared.choice == "deal_now":
            notes.append(
                f"moving a receiver for {card} onto column {column + 1} loses to dealing now"
            )
        elif compared.choice == "reject":
            notes.append(f"receiver plan for {card} on column {column + 1} was rejected")
    return best, tuple(notes)


def _alignment_proposal(state, g, campaign, agenda, lock, events, time_left):
    if time_left < 0.2 or not state.can_deal():
        return None
    started = time.perf_counter()
    found = plan_receiver_alignment(state, campaign)
    _add_time(lock, "receiver_alignment", time.perf_counter() - started)
    if found is None:
        return None
    comparison, notes = found
    compare_started = time.perf_counter()
    _add_time(lock, "consequence_comparison", time.perf_counter() - compare_started)
    for note in notes:
        if note not in events:
            events.append(f"foundation: {note}")
    if comparison is None or comparison.choice != "prepare" or not comparison.actions:
        return None
    rendered = " ".join(format_action(action) for action in comparison.actions)
    events.append(
        f"foundation: prepare column {comparison.column + 1} before the deal; "
        f"corrected preparation-plus-deal cost {comparison.preparation_cost}"
    )
    return _proposal(
        _make_candidate(
            g,
            f"ALIGN:{campaign.label}:{comparison.column + 1}",
            "ALIGN",
            (comparison.actions[0],),
            hold=False,
            benefit=1.5,
            evidence=_evidence(
                campaign,
                agenda,
                *comparison.evidence,
                f"fact: legal preparation {rendered}",
            ),
            purpose="place the receiver for a known incoming card",
        ),
        "selected: stock reception is worth preparing",
        events,
        False,
        agenda,
    )


def _named_stock_still_ahead(campaign: FoundationCampaign) -> Tuple[str, ...]:
    missing = []
    for need in campaign.rank_needs:
        chosen = need.chosen
        if chosen is None or not str(chosen.source_key).startswith("stock:"):
            continue
        if chosen.stock_epoch is not None and chosen.stock_epoch > campaign.current_epoch:
            missing.append(f"{chosen.card} at epoch {chosen.stock_epoch}")
    return tuple(missing)


def _exposed_run_length(column) -> int:
    up = column.face_up
    if not up:
        return 0
    length = 1
    while length < len(up):
        parent = up[-1 - length]
        child = up[-length]
        if parent.suit != child.suit or parent.rank != child.rank + 1:
            break
        length += 1
    return length


def _cover_is_movable(state: SpiderState, column: int, protected) -> bool:
    """True when the single covering card has a legal move that is not a protected split."""

    for action in all_legal_actions(state):
        if action == ("deal",) or action[0] != column or action[2] != 1:
            continue
        if _splits_protected(state, action, protected):
            continue
        return True
    return False


@dataclass(frozen=True)
class CoverRecovery:
    """A bounded legal sequence that uncovers one card after a deal."""

    actions: Tuple[Action, ...]
    cost: int
    evidence: Tuple[str, ...]


def _depth_of(state: SpiderState, card: Card) -> Optional[int]:
    for column in state.columns:
        for index, item in enumerate(column.face_up):
            if item is card:
                return len(column.face_up) - 1 - index
    for sequence in state.foundations:
        if any(item is card for item in sequence):
            return 0
    return None


def search_post_deal_recovery(
    dealt: SpiderState,
    card: Card,
    protected,
    *,
    max_moves: int = 3,
    max_nodes: int = 80,
) -> Optional[CoverRecovery]:
    """Search a short legal sequence that uncovers ``card``.

    One move is not assumed to be enough, and finding a sequence does not by
    itself approve the deal. The caller still has to have a useful consequence.
    Deals are not part of the recovery.
    """

    if _depth_of(dealt, card) == 0:
        return CoverRecovery((), 0, ("fact: the card is already exposed",))
    queue = [(dealt, (), 0, 0)]
    seen = {canonical_state_key(dealt)}
    nodes = 0
    while queue and nodes < max_nodes:
        cursor, actions, moves, cost = queue.pop(0)
        nodes += 1
        if moves >= max_moves:
            continue
        legal = []
        for action in all_legal_actions(cursor):
            if action == ("deal",) or _splits_protected(cursor, action, protected):
                continue
            legal.append(action)
        holding = None
        for index, column in enumerate(cursor.columns):
            if any(item is card for item in column.face_up):
                holding = index
                break
        legal.sort(key=lambda action: 0 if action[0] == holding else 1)
        for action in legal:
            trial = cursor.clone()
            try:
                paid = apply_action(trial, action)
            except ValueError:
                continue
            depth = _depth_of(trial, card)
            new_actions = actions + (action,)
            new_cost = cost + int(paid)
            if depth == 0:
                rendered = " ".join(format_action(item) for item in new_actions)
                return CoverRecovery(
                    new_actions,
                    new_cost,
                    (
                        f"fact: recovery {rendered} costs {new_cost}",
                        "fact: the sequence was replayed on the dealt state",
                        "fact: a multi-move recovery is not automatic approval",
                    ),
                )
            if depth is None or moves + 1 >= max_moves:
                continue
            key = canonical_state_key(trial)
            if key in seen:
                continue
            seen.add(key)
            queue.append((trial, new_actions, moves + 1, new_cost))
    return None


def _burial_facts(state, dealt, suit: str, protected, lock=None) -> Optional[List[str]]:
    """Facts about same-suit runs the next row covers.

    None means a run of three or more cannot be recovered inside the bound.
    A one-move lift and a longer recovery are both reported. Neither is an
    approval by itself.
    """

    covered = []
    for index, column in enumerate(state.columns):
        old_top = column.top()
        if old_top is None or old_top.suit != suit:
            continue
        new_top = dealt.columns[index].top()
        if new_top is old_top:
            continue
        if new_top.suit == old_top.suit and old_top.rank == new_top.rank + 1:
            # The incoming card extended the run. It is the connection, not a burial.
            continue
        length = _exposed_run_length(column)
        if length < 3:
            covered.append(f"column {index + 1} {old_top} is covered by {new_top}")
            continue
        if _cover_is_movable(dealt, index, protected):
            covered.append(
                f"column {index + 1} run of {length} is covered by {new_top} "
                "and one legal move lifts that cover"
            )
            continue
        started = time.perf_counter()
        recovery = search_post_deal_recovery(dealt, old_top, protected)
        if lock is not None:
            _add_time(lock, "consequence_probing", time.perf_counter() - started)
        if recovery is None:
            return None
        covered.append(
            f"column {index + 1} run of {length} is covered by {new_top} "
            f"and a {len(recovery.actions)}-move recovery costs {recovery.cost}"
        )
    return covered


def measured_stock_connection(state, suit: str, protected, *, operational, current, lock=None):
    """Exact facts that can justify dealing the next row for one locked suit.

    The analysed target epoch is intentionally not an argument. Returning None
    means this row is not justified by a measured connection. A covered run of
    three or more cards blocks the deal unless one legal move lifts that cover.
    """

    if operational is None or current + 1 > operational or not state.can_deal():
        return None
    row = next_stock_row(state)
    if row is None:
        return None
    before_longest = _longest(state, suit)
    dealt = state.clone()
    try:
        deal_cost = apply_action(dealt, ("deal",))
    except ValueError:
        return None
    landings = []
    arrived = []
    for index, card in enumerate(row):
        if card.suit != suit:
            continue
        arrived.append(f"column {index + 1} {card}")
        parent = state.columns[index].top()
        if parent is not None and parent.suit == suit and parent.rank == card.rank + 1:
            landings.append(f"{card} onto {parent} in column {index + 1}")
    follow = None
    follow_gain = None
    follow_removes = False
    follow_key = None
    for action in all_legal_actions(dealt):
        if action == ("deal",):
            continue
        src, dst, k = action
        run = dealt.columns[src].face_up[-k:]
        if not run or run[0].suit != suit:
            continue
        if _splits_protected(dealt, action, protected):
            continue
        top = dealt.columns[dst].top()
        if top is None or top.suit != suit or top.rank != run[0].rank + 1:
            continue
        uses_new_card = any(run[0] is card or top is card for card in row)
        if not uses_new_card:
            continue
        trial = dealt.clone()
        apply_action(trial, action)
        gain = _longest(trial, suit) - before_longest
        removes = len(trial.foundations) > len(dealt.foundations)
        # Removing the suit shortens the longest remaining run. That is the
        # completion, so it outranks a cosmetic extension.
        key = (1 if removes else 0, gain, k)
        if follow_key is None or key > follow_key:
            follow_key = key
            follow_gain = gain
            follow_removes = removes
            follow = action
    if not landings and follow is None:
        return None
    covered = _burial_facts(state, dealt, suit, protected, lock)
    if covered is None:
        return None
    lines = [
        "fact: preparation inside the cost bound did not relocate a better receiver",
        f"fact: corrected deal cost is {deal_cost}",
        "fact: the operational epoch was not revised to authorise this row",
    ]
    if arrived:
        lines.append("fact: incoming " + ", ".join(arrived))
    if landings:
        lines.append("fact: same-suit landing " + "; ".join(landings))
    if follow is not None and follow_removes:
        lines.append(
            f"fact: after the deal {format_action(follow)} removes the suit; "
            "the landing itself is not the foundation"
        )
    elif follow is not None:
        lines.append(
            f"fact: after the deal {format_action(follow)} extends the suit "
            f"by {follow_gain}"
        )
    lines.extend(f"fact: {item}" for item in covered[:4])
    return tuple(lines)


def _evidenced_deal(state, g, campaign, agenda, lock, events, refused, operational):
    """Deal when the next row itself creates a measured same-suit gain.

    This is not the old unlocking deal. The row must still be inside the
    locked operational horizon, and a failed reveal must already have been
    refused further up the caller.
    """

    if operational is None or not state.can_deal():
        return None
    if f"DEAL:{campaign.label}" in refused or lock.get("barren_deals", 0) >= 1:
        return None
    evidence = measured_stock_connection(
        state,
        campaign.suit,
        agenda.protected_fragments,
        operational=operational,
        current=campaign.current_epoch,
        lock=lock,
    )
    if evidence is None:
        return None
    evidence = tuple(evidence) + (
        "fact: the next row is a future stock event, not a row already dealt",
    )
    events.append(
        f"foundation: deal one row for a measured {campaign.suit} connection; "
        f"operational epoch stays {operational}"
    )
    return _proposal(
        _make_candidate(
            g,
            f"DEAL:{campaign.label}",
            "DEAL_NOW",
            (("deal",),),
            hold=False,
            benefit=1.4,
            evidence=_evidence(campaign, agenda, *evidence),
            purpose="deal because a known incoming card creates a same-suit connection",
        ),
        "selected: a known incoming card enables a same-suit connection after preparation was tried",
        events,
        False,
        agenda,
    )


def _necessary_deal(state, g, campaign, agenda, lock, events, refused, operational):
    """Deal one row because a required card arrives, even with a neutral landing.

    A higher analysed epoch is not evidence. The card has to be a chosen
    stock source of this exact next row, and that row has to sit inside the
    locked operational horizon. The same burial bound used by a measured
    connection still applies.
    """

    if operational is None or not state.can_deal():
        return None
    if campaign.current_epoch + 1 > operational:
        return None
    if f"DEAL:{campaign.label}" in refused or lock.get("barren_deals", 0) >= 1:
        return None
    row = next_stock_row(state)
    if not row:
        return None
    required = []
    for need in campaign.rank_needs:
        chosen = need.chosen
        if chosen is None or not str(chosen.source_key).startswith("stock:"):
            continue
        if chosen.stock_epoch != campaign.current_epoch + 1 or chosen.stock_column is None:
            continue
        column = chosen.stock_column
        if not 0 <= column < len(row):
            continue
        card = row[column]
        if card.suit != campaign.suit or card.rank != need.rank:
            continue
        parent = state.columns[column].top()
        direct = (
            parent is not None
            and card.rank < 13
            and parent.suit == card.suit
            and parent.rank == card.rank + 1
        )
        required.append((card, column, direct))
    neutral = [item for item in required if not item[2]]
    if not neutral:
        return None
    dealt = state.clone()
    try:
        apply_action(dealt, ("deal",))
    except ValueError:
        return None
    started = time.perf_counter()
    covered = _burial_facts(state, dealt, campaign.suit, agenda.protected_fragments, lock)
    _add_time(lock, "dependency_planning", time.perf_counter() - started)
    if covered is None:
        return None
    descriptions = []
    for card, column, _direct in neutral[:3]:
        landing = classify_incoming_receiver(state, card, column, max_cost=2, max_expand=120)
        descriptions.append(f"{card} on column {column + 1} is {landing.status}")
    names = ", ".join(descriptions)
    events.append(
        f"foundation: deal one row because a required {campaign.suit} card has not arrived; "
        f"operational epoch stays {operational}"
    )
    evidence = _evidence(
        campaign,
        agenda,
        f"fact: required card has not arrived: {names}",
        "fact: the landing need not be same-suit for a card the campaign still needs",
        "fact: the operational epoch was not revised to authorise this row",
        "fact: an analysed-epoch increase is not the reason for this deal",
        "fact: the next row is a future stock event, not a row already dealt",
    )
    if covered:
        evidence = evidence + tuple(f"fact: {item}" for item in covered[:3])
    return _proposal(
        _make_candidate(
            g,
            f"DEAL:{campaign.label}",
            "DEAL_NOW",
            (("deal",),),
            hold=False,
            benefit=1.1,
            evidence=evidence,
            purpose="deal because a required card arrives in this row",
        ),
        "selected: a required card arrives in this row even though its landing is neutral",
        events,
        False,
        agenda,
    )


def _horizon_deal(state, g, campaign, agenda, lock, events, refused, operational, policy):
    """One intermediate row when the locked horizon is still ahead.

    The analysed epoch is not consulted. A row beyond the locked operational
    epoch is not dealt here.
    """

    if operational is None or not state.can_deal():
        return None
    if f"DEAL:{campaign.label}" in refused or lock.get("barren_deals", 0) >= 1:
        return None
    if not _deal_recommended(policy):
        return None
    if not (campaign.current_epoch + 1 < operational):
        return None
    if _any_reveal(state):
        return None
    missing = _named_stock_still_ahead(campaign)
    if not missing:
        return None
    events.append(
        "foundation: bounded preparation did not open the tableau prerequisite; "
        "the locked horizon still needs stock"
    )
    evidence = _deal_evidence(state, campaign, agenda) + (
        f"fact: operational epoch {operational} stays locked",
        f"fact: named stock still ahead: {', '.join(missing[:4])}",
        "fact: this deal is not authorised by a raised analysed epoch",
    )
    return _proposal(
        _make_candidate(
            g,
            f"DEAL:{campaign.label}",
            "DEAL_NOW",
            (("deal",),),
            hold=False,
            benefit=1.0,
            evidence=evidence,
            purpose="deal one row because the locked horizon still needs stock",
        ),
        "selected: locked stock horizon still needs a row after preparation was tried",
        events,
        False,
        agenda,
    )
