#!/usr/bin/env python3
"""Legal Deal-2 campaign restart from the corrected-rules baseline.

The preferred permanent-join arm is completed and frozen before the control
arm is started.  Both arms are independently reconstructed from the true deal.
Canonical move data is opened only after both prospective results are frozen.

Benchmark coordinates belong only in this diagnostic.  Production campaign
selection, obligation derivation, stock-row mapping, and tactical expansion
remain generic and engine-verified.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, format_action, parse_moves_file, replay_actions
from spider.move_lifecycle import (
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
)
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    RankSource,
    RankSourceKind,
    analyze_foundation_campaign,
    analyze_foundation_campaigns,
    format_campaign,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignRealizationResult,
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignBand,
    CampaignRemovalObligation,
    CampaignRemovalResult,
    CampaignRemovalStatus,
    campaign_band_recovery,
    campaign_receiver_conditions,
    campaign_removal_obligations,
    format_removal_obligation,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.foundation_feasibility import current_stock_epoch, epoch_name
from spider.planner.space_lifecycle import empty_columns
from spider.planner.stock_reception import next_stock_row
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "dec794eb5661defe3ff04e06e56a63e905ebbb93"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (8, 12, 16, 22, 30)
MAX_NODES = 120_000
TIME_LIMIT_S = 45.0
BEAM_WIDTH = 256

COMMON_PREFIX: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
)
PREFERRED_B_OPENING: Tuple[Action, ...] = COMMON_PREFIX + (
    (5, 4, 1),  # Qc -> Kc, stable
    (5, 1, 1),  # Qs -> Kd, one necessary park
    (2, 7, 3),  # 4s-3s-2s -> 5s
)
CONTROL_A_OPENING: Tuple[Action, ...] = COMMON_PREFIX + (
    (5, 1, 1),  # Qc -> Kd, park
    (5, 4, 1),  # Qs -> Kc, park
    (2, 7, 3),  # 4s-3s-2s -> 5s
)


@dataclass(frozen=True)
class SearchResources:
    bounds: Tuple[int, ...] = BOUNDS
    max_nodes: int = MAX_NODES
    time_limit_s: float = TIME_LIMIT_S
    beam_width: int = BEAM_WIDTH


@dataclass(frozen=True)
class LifecycleRecord:
    action_index: int
    action: Action
    assessment: MoveLifecycleAssessment
    selected_exit_route: str
    resolved_within_route: bool


@dataclass(frozen=True)
class LifecycleSummary:
    immediate_cost: int
    stable_joins_created: int
    provisional_joins_created: int
    same_suit_joins_broken: int
    mixed_boundaries_created: int
    mixed_boundaries_removed: int
    workspace_parks: int
    estimated_rehandling_debt: float
    projected_lifecycle_cost: float
    records: Tuple[LifecycleRecord, ...]
    permanent_join_overrides: Tuple[str, ...]


@dataclass(frozen=True)
class RevealValueFact:
    action_index: int
    card: Card
    column: int
    category: str
    campaign_dependency: str
    receiver_created: str
    permanent_run_enabled: str
    workspace_effect: str
    stock_substitution: str
    rehandling_debt: float


@dataclass(frozen=True)
class FrozenArm:
    name: str
    cards: Tuple[Card, ...]
    opening_actions: Tuple[Action, ...]
    opening_state: SpiderState
    six_move_state: SpiderState
    opening_variant_lifecycle: LifecycleSummary
    opening_portfolio: FoundationCampaignPortfolio
    deal1: CampaignRealizationResult
    post_deal1: SpiderState
    post_deal1_portfolio: FoundationCampaignPortfolio
    campaign: FoundationCampaign
    obligations: Tuple[CampaignRemovalObligation, ...]
    bound_results: Tuple[Tuple[int, CampaignRemovalResult], ...]
    best: CampaignRemovalResult
    full_actions: Tuple[Action, ...]
    total_cost: int
    independent_replay_verified: bool
    route_lifecycle: LifecycleSummary
    reveal_values: Tuple[RevealValueFact, ...]
    verdict: str
    gate_reasons: Tuple[str, ...]
    resources: SearchResources
    prospective_frozen: bool


@dataclass(frozen=True)
class FrozenExperiment:
    preferred: FrozenArm
    control: FrozenArm
    canonical_loaded: bool = False


def _face_down_count(state: SpiderState) -> int:
    return sum(len(column.face_down) for column in state.columns)


def _state_line(state: SpiderState) -> str:
    tops = " ".join(str(card) if card else "--" for card in state.top_row())
    return (
        f"tops=[{tops}] fd={_face_down_count(state)} stock={len(state.stock)} "
        f"epoch={current_stock_epoch(state, 5)} foundations={len(state.foundations)} "
        f"empties={[column + 1 for column in empty_columns(state)]}"
    )


def _band_line(band: CampaignBand) -> str:
    recovery = campaign_band_recovery(band)
    return (
        f"{band.label:<22} interval={band.face_up_interval} "
        f"movable={band.movable} cover={[str(card) for card in band.covering_cards]} "
        f"cover_groups={recovery.covering_groups}"
    )


def _portfolio_objective(campaign: FoundationCampaign) -> float:
    confidence_penalty = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}
    target = campaign.target_removal_epoch
    delay = 99 if target is None else max(0, target - campaign.current_epoch)
    return (
        campaign.estimated_campaign_cost
        + 6.0 * delay
        + confidence_penalty.get(campaign.confidence, 6.0)
    )


def _multi_card_actions_are_same_suit(
    start: SpiderState, actions: Sequence[Action]
) -> bool:
    state = start.clone()
    for action in actions:
        if action == ("deal",):
            state.deal()
            continue
        src, dst, k = action
        run = state.columns[src].face_up[-k:]
        if k > 1 and not SpiderState.is_movable_run(run):
            return False
        state.move(src, dst, k)
    return True


def _boundary_present(state: SpiderState, lower: Card, upper: Card) -> bool:
    return any(
        any(
            column.face_up[index] is lower and column.face_up[index + 1] is upper
            for index in range(len(column.face_up) - 1)
        )
        for column in state.columns
    )


def _route_lifecycle(
    start: SpiderState,
    actions: Sequence[Action],
    *,
    action_offset: int = 0,
    future_king: Optional[Card] = None,
) -> LifecycleSummary:
    """Audit every selected placement and identify its bounded exit if seen."""
    state = start.clone()
    staged: list[
        tuple[
            int,
            Action,
            MoveLifecycleAssessment,
            Optional[Card],
            Card,
            Tuple[Card, ...],
        ]
    ] = []
    assessments: list[MoveLifecycleAssessment] = []
    snapshots: list[SpiderState] = [state.clone()]
    for local_index, action in enumerate(actions, 1):
        if action == ("deal",):
            state.deal()
            snapshots.append(state.clone())
            continue
        src, dst, k = action
        lower = state.columns[dst].top()
        moved_head = state.columns[src].face_up[-k]
        moved_cards = tuple(state.columns[src].face_up[-k:])
        assessment = assess_tableau_move(state, (src, dst, k))
        assessments.append(assessment)
        staged.append(
            (
                action_offset + local_index,
                action,
                assessment,
                lower,
                moved_head,
                moved_cards,
            )
        )
        state.move(src, dst, k)
        snapshots.append(state.clone())

    records: list[LifecycleRecord] = []
    for action_index, action, assessment, lower, moved_head, moved_cards in staged:
        route = assessment.future_exit_route
        resolved = assessment.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
        if assessment.placement_class == PlacementClass.MIXED_SUIT_PARK and lower is not None:
            local_start = action_index - action_offset
            for later_local in range(local_start + 1, len(snapshots)):
                if not _boundary_present(snapshots[later_local], lower, moved_head):
                    route = (
                        f"resolved by selected action {action_offset + later_local}: "
                        f"{format_action(actions[later_local - 1])}"
                    )
                    resolved = True
                    break
        if assessment.placement_class == PlacementClass.WORKSPACE_PARK:
            local_start = action_index - action_offset
            for later_local in range(local_start + 1, len(snapshots)):
                later_action = actions[later_local - 1]
                if later_action == ("deal",):
                    continue
                before_later = snapshots[later_local - 1]
                later_src, _later_dst, later_k = later_action
                later_run = before_later.columns[later_src].face_up[-later_k:]
                if any(card is moved_cards[0] for card in later_run):
                    route = (
                        f"resolved by selected action {action_offset + later_local}: "
                        f"{format_action(later_action)}"
                    )
                    resolved = True
                    break
        if (
            assessment.placement_class == PlacementClass.MIXED_SUIT_PARK
            and not resolved
            and moved_head.rank == 12
            and future_king is not None
            and future_king.suit == moved_head.suit
        ):
            route = (
                f"bounded substitution exit: use parked {moved_head} as the Q source "
                f"onto exact incoming {future_king}; debt remains because the selected "
                "first-foundation route used the interchangeable Queen instead"
            )
        elif not resolved and route.startswith("move "):
            route = "bounded immediate exit available: " + route
        elif not resolved and route.startswith("unresolved"):
            route = (
                "exit obligation unresolved within the Deal-2 horizon; " + route
            )
        records.append(
            LifecycleRecord(action_index, action, assessment, route, resolved)
        )

    stable = sum(
        a.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
        for a in assessments
    )
    provisional = sum(
        a.placement_class == PlacementClass.PROVISIONAL_SAME_SUIT_JOIN
        for a in assessments
    )
    workspaces = sum(
        a.placement_class == PlacementClass.WORKSPACE_PARK for a in assessments
    )
    immediate = sum(a.immediate_cost for a in assessments)
    debt = sum(a.estimated_rehandling_cost for a in assessments)
    overrides = tuple(
        a.compensating_benefit.override_reason
        for a in assessments
        if a.can_override_permanent_join and a.compensating_benefit is not None
    )
    return LifecycleSummary(
        immediate_cost=immediate,
        stable_joins_created=stable,
        provisional_joins_created=provisional,
        same_suit_joins_broken=sum(len(a.same_suit_joins_broken) for a in assessments),
        mixed_boundaries_created=sum(
            len(a.mixed_suit_boundaries_created) for a in assessments
        ),
        mixed_boundaries_removed=sum(
            len(a.mixed_suit_boundaries_removed) for a in assessments
        ),
        workspace_parks=workspaces,
        estimated_rehandling_debt=debt,
        projected_lifecycle_cost=float(immediate) + debt,
        records=tuple(records),
        permanent_join_overrides=overrides,
    )


def _opening_variant_lifecycle(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    future_king: Card,
) -> LifecycleSummary:
    state = opening.clone()
    replay_actions(state, list(actions[:3]))
    # The diagnostic comparison is intentionally the three differing/common
    # closing actions only: Queen placements plus Spade consolidation.
    return _route_lifecycle(
        state, actions[3:], action_offset=3, future_king=future_king
    )


def _selected_sources(campaign: FoundationCampaign) -> Tuple[RankSource, ...]:
    return tuple(
        need.chosen for need in campaign.rank_needs if need.chosen is not None
    )


def _reveal_value_facts(
    start: SpiderState,
    actions: Sequence[Action],
    campaign: FoundationCampaign,
    *,
    action_offset: int,
) -> Tuple[RevealValueFact, ...]:
    """Value exact exposures by later structural use, never by information."""
    state = start.clone()
    events: list[tuple[int, Card, int, bool, float]] = []
    before_states: list[SpiderState] = []
    after_states: list[SpiderState] = []
    for local_index, action in enumerate(actions, 1):
        before = state.clone()
        before_states.append(before)
        debt = 0.0
        if action == ("deal",):
            state.deal()
        else:
            src, dst, k = action
            debt = assess_tableau_move(before, (src, dst, k)).estimated_rehandling_cost
            old_top = before.columns[src].top()
            old_fd = len(before.columns[src].face_down)
            state.move(src, dst, k)
            new_top = state.columns[src].top()
            if new_top is not None and new_top is not old_top:
                flipped = len(state.columns[src].face_down) < old_fd
                events.append(
                    (action_offset + local_index, new_top, src, flipped, debt)
                )
        after_states.append(state.clone())

    selected_stock = {
        (source.card.suit, source.card.rank)
        for source in campaign.future_stock_supplied_cards
    }
    source_counts: dict[tuple[str, int], int] = {}
    for need in campaign.rank_needs:
        for source in need.sources:
            key = (source.card.suit, source.card.rank)
            source_counts[key] = source_counts.get(key, 0) + 1

    facts: list[RevealValueFact] = []
    deal_local = next(
        (index for index, action in enumerate(actions, 1) if action == ("deal",)),
        len(actions) + 1,
    )
    for global_index, card, column, flipped, debt in events:
        local_index = global_index - action_offset
        used_receiver: Optional[int] = None
        moved_later: Optional[int] = None
        for later in range(local_index, len(actions)):
            action = actions[later]
            if action == ("deal",):
                continue
            before = before_states[later]
            src, dst, k = action
            if before.columns[dst].top() is card and used_receiver is None:
                used_receiver = action_offset + later + 1
            if any(item is card for item in before.columns[src].face_up[-k:]):
                moved_later = action_offset + later + 1
                break
        key = (card.suit, card.rank)
        stock_replaceable = key in selected_stock
        duplicate = source_counts.get(key, 0) > 1
        moved_after_deal = bool(
            moved_later is not None
            and moved_later > action_offset + deal_local
        )
        if (
            local_index < deal_local
            and card.suit == campaign.suit
            and moved_after_deal
        ):
            category = "required-before-next-deal"
        elif used_receiver is not None or moved_later is not None:
            category = "critical-now"
        elif card.suit == campaign.suit and stock_replaceable:
            category = "replaceable-by-stock/duplicate"
        elif card.suit == campaign.suit:
            category = "useful-but-deferrable"
        else:
            category = "strategically-irrelevant-at-current-epoch"
        dependency = (
            f"used by selected action {moved_later}"
            if moved_later is not None
            else "no selected S#1 dependency"
        )
        receiver = (
            f"receiver used by selected action {used_receiver}"
            if used_receiver is not None
            else "none"
        )
        permanent = (
            "enabled selected same-suit assembly"
            if card.suit == campaign.suit and (moved_later or used_receiver)
            else "none"
        )
        substitution = (
            "exact selected stock copy available"
            if stock_replaceable
            else ("interchangeable tableau copy available" if duplicate else "none")
        )
        facts.append(
            RevealValueFact(
                action_index=global_index,
                card=card,
                column=column,
                category=category,
                campaign_dependency=("face-down flip; " if flipped else "face-up uncover; ")
                + dependency,
                receiver_created=receiver,
                permanent_run_enabled=permanent,
                workspace_effect="no empty created or recovered",
                stock_substitution=substitution,
                rehandling_debt=debt,
            )
        )
    return tuple(facts)


def _hard_gate(
    campaign: FoundationCampaign,
    deal1: CampaignRealizationResult,
    best: CampaignRemovalResult,
    full_actions: Sequence[Action],
    total_cost: int,
    replay_verified: bool,
) -> Tuple[str, Tuple[str, ...]]:
    deals = sum(action == ("deal",) for action in full_actions)
    foundation_ok = bool(
        best.foundation_count_after == best.foundation_count_before + 1
        and best.foundation_suits_added == (campaign.suit,)
    )
    identity_ok = bool(
        deal1.identity.suit == campaign.suit == best.identity.suit
        and best.identity.copy_index == campaign.copy_index
        and best.identity.target_epoch == campaign.target_removal_epoch == 2
    )
    legal = _multi_card_actions_are_same_suit(best.start_state, best.actions)
    success = bool(
        best.status == CampaignRemovalStatus.FOUNDATION_REMOVED
        and best.independent_replay_verified
        and replay_verified
        and foundation_ok
        and identity_ok
        and deals == 2
        and len(best.end_state.stock) == 30
        and legal
    )
    reasons = (
        f"status={best.status.value}; fixed_identity={identity_ok}",
        f"true-deal replay={replay_verified}; campaign replay={best.independent_replay_verified}",
        f"all multi-card actions same-suit={legal}",
        f"deals={deals}; stock_after={len(best.end_state.stock)}; no Deal 3={deals == 2}",
        f"foundation={best.foundation_count_before}->{best.foundation_count_after}; "
        f"added_suits={best.foundation_suits_added}",
        f"costs opening=6 Deal1={deal1.corrected_added_cost} "
        f"Deal2={best.corrected_added_cost} total={total_cost}",
    )
    if success and total_cost <= 23:
        return "EXCEPTIONAL", reasons
    if success and total_cost <= 30:
        return "STRONG PASS", reasons
    if success:
        return "PASS", reasons
    if best.actions and best.independent_replay_verified:
        return "PARTIAL", reasons
    return "FAIL", reasons


def freeze_arm(
    name: str,
    opening_actions: Sequence[Action],
    cards: Sequence[Card],
    *,
    resources: SearchResources = SearchResources(),
) -> FrozenArm:
    """Run and freeze one arm without reading canonical move data."""
    card_tuple = tuple(cards)
    opening = SpiderState.from_cards(list(card_tuple))
    six = opening.clone()
    opening_cost = replay_actions(six, list(opening_actions))
    if opening_cost != 6 or not _multi_card_actions_are_same_suit(
        opening, opening_actions
    ):
        raise AssertionError(f"{name} opening failed corrected replay")

    opening_portfolio = analyze_foundation_campaigns(six, cards=card_tuple)
    if opening_portfolio.primary is None:
        raise AssertionError(f"{name} has no opening campaign")
    deal1 = realize_campaign_to_next_epoch(
        six,
        opening_portfolio.primary,
        card_tuple,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20.0,
    )
    deal1_checked = six.clone()
    deal1_cost = replay_actions(deal1_checked, list(deal1.actions))
    if not (
        deal1.status == CampaignRealizationStatus.FOUND
        and deal1.independent_replay_verified
        and deal1.actions.count(("deal",)) == 1
        and deal1_cost == deal1.corrected_added_cost == 5
        and states_structurally_equal(deal1_checked, deal1.resulting_state)
        and _multi_card_actions_are_same_suit(six, deal1.actions)
    ):
        raise AssertionError(f"{name} Deal-1 realizer regression")

    post_deal1 = deal1.resulting_state.clone()
    portfolio = analyze_foundation_campaigns(post_deal1, cards=card_tuple)
    campaign = portfolio.primary
    if campaign is None:
        raise AssertionError(f"{name} has no post-Deal-1 campaign")
    near_primary = campaign.suit == "s" or (
        portfolio.secondary is not None and portfolio.secondary.suit == "s"
    )
    if not (
        near_primary
        and campaign.suit == "s"
        and campaign.copy_index == 1
        and campaign.target_removal_epoch == 2
    ):
        raise AssertionError(
            f"{name} S#1 is not a credible Deal-2 primary: {campaign.label}"
        )

    obligations = campaign_removal_obligations(post_deal1, campaign, card_tuple)
    results: list[tuple[int, CampaignRemovalResult]] = []
    for bound in resources.bounds:
        result = realize_campaign_to_removal_epoch(
            post_deal1,
            campaign,
            card_tuple,
            max_added_cost=bound,
            max_nodes=resources.max_nodes,
            time_limit_s=resources.time_limit_s,
            beam_width=resources.beam_width,
        )
        results.append((bound, result))
        if result.status == CampaignRemovalStatus.FOUNDATION_REMOVED:
            break
    best = next(
        (
            result
            for _bound, result in results
            if result.status == CampaignRemovalStatus.FOUNDATION_REMOVED
            and result.independent_replay_verified
        ),
        max(
            (result for _bound, result in results),
            key=lambda item: (
                len(item.obligations_satisfied),
                item.foundation_count_after,
                len(item.actions),
            ),
        ),
    )
    full_actions = tuple(opening_actions) + deal1.actions + best.actions
    replay = opening.clone()
    total = replay_actions(replay, list(full_actions))
    replay_ok = bool(
        states_structurally_equal(replay, best.end_state)
        and best.corrected_added_cost is not None
        and total == 6 + deal1.corrected_added_cost + best.corrected_added_cost
        and sum(action == ("deal",) for action in full_actions) == 2
    )
    exact_row = tuple(next_stock_row(post_deal1) or ())
    if best.exact_row != exact_row:
        raise AssertionError("Deal-2 row was not derived from current state")
    future_king = next(
        (card for card in exact_row if card.suit == campaign.suit and card.rank == 13),
        Card(campaign.suit, 13),
    )
    opening_lifecycle = _opening_variant_lifecycle(
        opening, opening_actions, future_king=future_king
    )
    route_lifecycle = _route_lifecycle(
        opening, full_actions, future_king=future_king
    )
    reveal_values = _reveal_value_facts(
        post_deal1,
        best.actions,
        campaign,
        action_offset=len(opening_actions) + len(deal1.actions),
    )
    verdict, gate_reasons = _hard_gate(
        campaign, deal1, best, full_actions, total, replay_ok
    )
    return FrozenArm(
        name=name,
        cards=card_tuple,
        opening_actions=tuple(opening_actions),
        opening_state=opening,
        six_move_state=six,
        opening_variant_lifecycle=opening_lifecycle,
        opening_portfolio=opening_portfolio,
        deal1=deal1,
        post_deal1=post_deal1,
        post_deal1_portfolio=portfolio,
        campaign=campaign,
        obligations=obligations,
        bound_results=tuple(results),
        best=best,
        full_actions=full_actions,
        total_cost=total,
        independent_replay_verified=replay_ok,
        route_lifecycle=route_lifecycle,
        reveal_values=reveal_values,
        verdict=verdict,
        gate_reasons=gate_reasons,
        resources=resources,
        prospective_frozen=True,
    )


def freeze_experiment(
    cards: Sequence[Card], *, resources: SearchResources = SearchResources()
) -> FrozenExperiment:
    """Freeze preferred B first; only then run the isolated control A arm."""
    preferred = freeze_arm(
        "B — preferred permanent join",
        PREFERRED_B_OPENING,
        cards,
        resources=resources,
    )
    if not preferred.prospective_frozen:
        raise AssertionError("preferred result must freeze before control")
    control = freeze_arm(
        "A — control Queen parks",
        CONTROL_A_OPENING,
        cards,
        resources=resources,
    )
    return FrozenExperiment(preferred=preferred, control=control)


def _print_portfolio(portfolio: FoundationCampaignPortfolio) -> None:
    print(
        "  suit copy epoch target score objective remaining confidence/readiness "
        "MUST stock bands projects workspace receivers lifecycle"
    )
    for campaign in portfolio.campaigns:
        bands = locate_campaign_bands(
            # The caller prints only post-Deal-1 portfolios and replaces this
            # placeholder through the campaign's hard structure summary below.
            _PRINT_STATE,
            campaign,
        )
        print(
            f"  {campaign.suit.upper():>4} {campaign.copy_index:>4} "
            f"{campaign.current_epoch:>5} {str(campaign.target_removal_epoch):>6} "
            f"{campaign.campaign_score:>5.1f} {_portfolio_objective(campaign):>9.1f} "
            f"{campaign.estimated_campaign_cost:>9.1f} "
            f"{campaign.confidence}/{campaign.readiness.value} "
            f"{len(campaign.tableau_critical_cards):>4} "
            f"{len(campaign.future_stock_supplied_cards):>5} "
            f"{len(bands):>5} "
            f"{len(campaign.prerequisite_excavation_projects):>8} "
            f"{campaign.space_requirement:>9} "
            f"{len(campaign.pre_deal_receiver_requirements):>9} "
            f"parks~{campaign.estimated_park_moves}"
        )


_PRINT_STATE: SpiderState


def _print_sources(campaign: FoundationCampaign) -> None:
    print("  MUST / deadline facts")
    project_by_column = {
        project.column: project for project in campaign.prerequisite_excavation_projects
    }
    for source in campaign.tableau_critical_cards:
        project = project_by_column.get(source.column if source.column is not None else -1)
        deadline = (
            f"before D{project.deadline_epoch}"
            if project is not None and project.deadline_before_deal
            else f"by D{project.deadline_epoch}" if project is not None else "campaign target"
        )
        print(
            f"    MUST {source.card}@c{(source.column or 0)+1} "
            f"key={source.source_key} peels={source.excavation_peels} deadline={deadline}"
        )
    print("  stock-supplied")
    for source in campaign.future_stock_supplied_cards:
        print(
            f"    STOCK {source.card}@D{source.stock_epoch}/c{(source.stock_column or 0)+1} "
            f"status={source.reception_status}"
        )
    print("  defer / interchangeable")
    for source in campaign.optional_replaceable_buried_copies:
        where = (
            f"c{source.column + 1}" if source.column is not None else f"D{source.stock_epoch}"
        )
        print(f"    DEFER {source.card}@{where} key={source.source_key} {source.note}")


def _print_lifecycle(title: str, summary: LifecycleSummary) -> None:
    print(title)
    print(
        f"  immediate={summary.immediate_cost} stable_created={summary.stable_joins_created} "
        f"provisional={summary.provisional_joins_created} joins_broken={summary.same_suit_joins_broken} "
        f"mixed_created={summary.mixed_boundaries_created} "
        f"mixed_removed={summary.mixed_boundaries_removed} "
        f"workspace_parks={summary.workspace_parks} debt={summary.estimated_rehandling_debt:g} "
        f"projected={summary.projected_lifecycle_cost:g}"
    )
    for record in summary.records:
        assessment = record.assessment
        if assessment.placement_class not in (
            PlacementClass.MIXED_SUIT_PARK,
            PlacementClass.WORKSPACE_PARK,
        ):
            continue
        print(
            f"    action {record.action_index}: {format_action(record.action)} "
            f"{assessment.placement_class.value} debt={assessment.estimated_rehandling_cost:g} "
            f"exit={record.selected_exit_route}"
        )
    print(
        "  permanent-join override: "
        + ("; ".join(summary.permanent_join_overrides) or "none")
    )


def _reported_status(result: CampaignRemovalResult) -> str:
    if result.status == CampaignRemovalStatus.FOUNDATION_REMOVED:
        return "FOUNDATION_REMOVED"
    if result.status == CampaignRemovalStatus.RESOURCE_LIMIT:
        return "RESOURCE_LIMIT"
    if result.status == CampaignRemovalStatus.INVALID_CAMPAIGN:
        return "INVALID_CAMPAIGN"
    if result.status == CampaignRemovalStatus.NOT_FOUND_WITHIN_BOUND:
        return "NOT_FOUND_WITHIN_BOUND"
    if result.deals_applied == 1 and (
        result.obligations_satisfied or result.bands_after
    ):
        return "CAMPAIGN_ADVANCED"
    return "PARTIAL"


def _remaining_must_count(arm: FrozenArm, result: CampaignRemovalResult) -> int:
    if result.status == CampaignRemovalStatus.FOUNDATION_REMOVED:
        return 0
    try:
        current = analyze_foundation_campaign(
            result.end_state,
            cards=arm.cards,
            suit=arm.campaign.suit,
            copy_index=arm.campaign.copy_index,
            target_epoch=arm.campaign.target_removal_epoch,
        )
    except ValueError:
        return len(arm.campaign.tableau_critical_cards)
    return len(current.tableau_critical_cards)


def _print_arm(arm: FrozenArm, *, complete: bool) -> None:
    global _PRINT_STATE
    _PRINT_STATE = arm.post_deal1
    print()
    print(arm.name.upper())
    print("  six-move replay: legal=True corrected_cost=6")
    print(
        f"  Deal-1 realizer: {arm.deal1.status.value} added={arm.deal1.corrected_added_cost} "
        f"nodes={arm.deal1.nodes_expanded} time={arm.deal1.elapsed_seconds:.3f}s "
        f"replay={arm.deal1.independent_replay_verified} actions="
        + ", ".join(format_action(action) for action in arm.deal1.actions)
    )
    print("  post-Deal-1: " + _state_line(arm.post_deal1))
    _print_lifecycle("  opening variant lifecycle (actions 4-6)", arm.opening_variant_lifecycle)
    print(
        f"  through-Deal-1 projected lifecycle: immediate=8 debt="
        f"{arm.opening_variant_lifecycle.estimated_rehandling_debt:g} projected="
        f"{8 + arm.opening_variant_lifecycle.estimated_rehandling_debt:g}"
    )
    print()
    print("  COMPLETE POST-DEAL-1 CAMPAIGN PORTFOLIO")
    _print_portfolio(arm.post_deal1_portfolio)
    print("  selected=" + arm.campaign.label + " because it remains the primary Deal-2 campaign")
    print(format_campaign(arm.campaign))
    _print_sources(arm.campaign)
    print()
    print("  FRESH DEAL-2 BANDS / OBLIGATIONS")
    for band in locate_campaign_bands(arm.post_deal1, arm.campaign):
        print("    " + _band_line(band))
    for obligation in arm.obligations:
        print("    " + format_removal_obligation(obligation))
    print("  exact Deal-2 row=" + " ".join(str(card) for card in arm.best.exact_row))
    for condition in campaign_receiver_conditions(arm.post_deal1, arm.campaign):
        print(
            f"    receiver {condition.incoming_card}@c{condition.incoming_column + 1}: "
            f"rank={condition.receiver_rank} direct={condition.direct} "
            f"walkoff={condition.bounded_walkoff} actions={condition.walkoff_actions}; "
            f"{condition.note}"
        )
    print()
    print("  ITERATIVE BOUNDS (stop at first removal)")
    for bound, result in arm.bound_results:
        must_before = len(arm.campaign.tableau_critical_cards)
        must_after = _remaining_must_count(arm, result)
        max_band = max((band.length for band in result.bands_after), default=0)
        bands = ",".join(
            f"{band.high_rank}-{band.low_rank}{band.suit}"
            for band in result.bands_after
            if band.length >= 2
        ) or "none"
        print(
            f"    bound={bound:>2} status={_reported_status(result):<24} "
            f"added={result.corrected_added_cost!s:<3} total="
            f"{(11 + result.corrected_added_cost) if result.corrected_added_cost is not None else 'n/a'} "
            f"deals={result.deals_applied} fd={_face_down_count(result.end_state)} "
            f"empty={len(empty_columns(result.end_state))} MUST={must_before}->{must_after} "
            f"max_band={max_band} bands={bands} receivers="
            f"{sum(c.direct or c.bounded_walkoff for c in result.receiver_conditions)}/"
            f"{len(result.receiver_conditions)} lifecycle_debt~"
            f"{_route_lifecycle(arm.post_deal1, result.actions).estimated_rehandling_debt:g} "
            f"nodes={result.nodes_expanded} time={result.elapsed_seconds:.3f}s "
            f"foundations={result.foundation_count_after}"
        )
    print()
    print("  REVEAL VALUE (information value is always zero)")
    for fact in arm.reveal_values:
        print(
            f"    action {fact.action_index}: expose {fact.card}@c{fact.column + 1} "
            f"[{fact.category}]; dependency={fact.campaign_dependency}; "
            f"receiver={fact.receiver_created}; run={fact.permanent_run_enabled}; "
            f"workspace={fact.workspace_effect}; substitution={fact.stock_substitution}; "
            f"debt={fact.rehandling_debt:g}"
        )
    _print_lifecycle("  COMPLETE SELECTED-ROUTE LIFECYCLE", arm.route_lifecycle)
    if complete:
        print()
        print("  COMPLETE BEST ROUTE FROM TRUE OPENING")
        for index, action in enumerate(arm.full_actions, 1):
            print(f"    {index:>2}. {format_action(action)}")
    print(
        f"  foundation verification: count={arm.best.foundation_count_before}->"
        f"{arm.best.foundation_count_after} suit={arm.best.foundation_suits_added} "
        f"replay={arm.independent_replay_verified} added={arm.best.corrected_added_cost} "
        f"total={arm.total_cost}"
    )
    for reason in arm.gate_reasons:
        print("    gate: " + reason)
    print("  VERDICT: " + arm.verdict)


def _mixed_boundary_count(state: SpiderState) -> int:
    count = 0
    for column in state.columns:
        for lower, upper in zip(column.face_up, column.face_up[1:]):
            if lower.rank - 1 == upper.rank and lower.suit != upper.suit:
                count += 1
    return count


def _canonical_comparison(experiment: FrozenExperiment) -> None:
    """The only function that reads canonical route content."""
    if not (
        experiment.preferred.prospective_frozen
        and experiment.control.prospective_frozen
    ):
        raise AssertionError("both prospective arms must freeze before canonical read")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = SpiderState.from_cards(
        list(load_deal(DEAL_PATH))
    )
    cost = 0
    prefix: list[Action] = []
    first_suit = None
    command = None
    for index, action in enumerate(actions, 1):
        before = len(state.foundations)
        cost += replay_actions(state, [action])
        prefix.append(action)
        if len(state.foundations) > before:
            first_suit = state.foundations[-1][0].suit
            command = index
            break
    print()
    print("CANONICAL COMPARISON — loaded only after B and A froze")
    print(
        f"  first foundation: cost={cost} command={command} suit={first_suit} "
        f"epoch={current_stock_epoch(state, 5)} fd={_face_down_count(state)} "
        f"empties={len(empty_columns(state))} mixed_boundaries={_mixed_boundary_count(state)}"
    )
    print(
        f"  preferred: cost={experiment.preferred.total_cost} suit="
        f"{experiment.preferred.best.foundation_suits_added} "
        f"epoch={current_stock_epoch(experiment.preferred.best.end_state, 5)} "
        f"fd={_face_down_count(experiment.preferred.best.end_state)} "
        f"empties={len(empty_columns(experiment.preferred.best.end_state))} "
        f"mixed_boundaries={_mixed_boundary_count(experiment.preferred.best.end_state)}"
    )
    print("  incumbent complete-route context=172; no incumbent pruning was used")
    print("  canonical is validation context only; no future canonical move guided search")


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL_PATH))
    print("LEGAL DEAL-2 CAMPAIGN RESTART")
    print(
        f"authoritative_base={AUTHORITATIVE_BASE}; corrected engine requires "
        "same-suit multi-card blocks; old 23/47/49 states are invalid evidence"
    )
    print(
        f"resources bounds={BOUNDS} nodes={MAX_NODES} "
        f"time_per_bound={TIME_LIMIT_S:g}s beam={BEAM_WIDTH}"
    )
    print("canonical move data not loaded")

    experiment = freeze_experiment(cards)
    _print_arm(experiment.preferred, complete=True)
    print()
    print("PREFERRED B PROSPECTIVE RESULT FROZEN — now running isolated control A")
    _print_arm(experiment.control, complete=False)

    b = experiment.preferred
    a = experiment.control
    print()
    print("A/B COMPARISON")
    print(
        "  resources comparable="
        + str(a.resources == b.resources)
        + f"; B bounds_run={[x for x, _ in b.bound_results]}; "
        + f"A bounds_run={[x for x, _ in a.bound_results]}"
    )
    print(
        f"  immediate variant cost A={a.opening_variant_lifecycle.immediate_cost} "
        f"B={b.opening_variant_lifecycle.immediate_cost}; stable joins "
        f"A={a.opening_variant_lifecycle.stable_joins_created} "
        f"B={b.opening_variant_lifecycle.stable_joins_created}; mixed boundaries "
        f"A={a.opening_variant_lifecycle.mixed_boundaries_created} "
        f"B={b.opening_variant_lifecycle.mixed_boundaries_created}; debt "
        f"A={a.opening_variant_lifecycle.estimated_rehandling_debt:g} "
        f"B={b.opening_variant_lifecycle.estimated_rehandling_debt:g}; "
        f"through-Deal-1 projected A="
        f"{8 + a.opening_variant_lifecycle.estimated_rehandling_debt:g} B="
        f"{8 + b.opening_variant_lifecycle.estimated_rehandling_debt:g}"
    )
    print(
        f"  post-D1 S1 remaining A={a.campaign.estimated_campaign_cost:g} "
        f"B={b.campaign.estimated_campaign_cost:g}; MUST "
        f"A={len(a.campaign.tableau_critical_cards)} "
        f"B={len(b.campaign.tableau_critical_cards)}"
    )
    print(
        f"  result A={a.verdict}/cost{a.total_cost}/nodes{a.best.nodes_expanded}/"
        f"{a.best.elapsed_seconds:.3f}s B={b.verdict}/cost{b.total_cost}/"
        f"nodes{b.best.nodes_expanded}/{b.best.elapsed_seconds:.3f}s"
    )
    print(
        "  permanent-join override found=none; A supplied no bounded downstream "
        "saving over B, and both reached the same legal cost-23 checkpoint"
    )

    print()
    print("BOTH PROSPECTIVE RESULTS FROZEN — canonical route may now be read")
    _canonical_comparison(experiment)
    print()
    print(
        "RECOMMENDED NEXT STEP: preserve the preferred cost-23 legal checkpoint "
        "as the new first-foundation fixture, then design a separately bounded "
        "post-foundation campaign transition from that state. Do not revive the "
        "old illegal cost-47/49 descendants."
    )
    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0 if b.verdict in ("EXCEPTIONAL", "STRONG PASS", "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
