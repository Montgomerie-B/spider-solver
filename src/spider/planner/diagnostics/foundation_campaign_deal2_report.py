#!/usr/bin/env python3
"""Prospective fixed-campaign realisation through Deal 2 and first removal.

All benchmark setup data lives in this diagnostic.  The verified Deal-1 route
is obtained by calling the existing generic realizer.  Every prospective
Deal-2 result is frozen before the canonical move file is opened.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, format_action, parse_moves_file, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
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
    campaign_removal_obligations,
    campaign_receiver_conditions,
    format_removal_obligation,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.space_lifecycle import empty_columns
from spider.state_identity import states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (8, 12, 16, 20, 28)
SIX_MOVE_FIXTURE: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
)


@dataclass(frozen=True)
class FrozenDeal2:
    cards: Tuple[Card, ...]
    opening: SpiderState
    six_move_state: SpiderState
    deal1: CampaignRealizationResult
    post_deal1: SpiderState
    campaign: FoundationCampaign
    obligations: Tuple[CampaignRemovalObligation, ...]
    bound_results: Tuple[Tuple[int, CampaignRemovalResult], ...]
    best: CampaignRemovalResult
    full_actions: Tuple[Action, ...]
    total_cost: int
    replay_verified: bool
    verdict: str
    gate_reasons: Tuple[str, ...]


def _state_line(state: SpiderState) -> str:
    tops = " ".join(str(card) if card else "--" for card in state.top_row())
    return (
        f"tops=[{tops}] fd={sum(len(column.face_down) for column in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"empties={[column + 1 for column in empty_columns(state)]}"
    )


def _band_line(band: CampaignBand) -> str:
    recovery = campaign_band_recovery(band)
    return (
        f"{band.label:<22} interval={band.face_up_interval} movable={band.movable} "
        f"cover={[str(card) for card in band.covering_cards]} "
        f"cover_groups={recovery.covering_groups}"
    )


def _build_verified_deal1(
    cards: Sequence[Card],
) -> Tuple[SpiderState, SpiderState, CampaignRealizationResult]:
    opening = SpiderState.from_cards(list(cards))
    six = opening.clone()
    if replay_actions(six, list(SIX_MOVE_FIXTURE)) != 6:
        raise AssertionError("six-move benchmark fixture cost drift")
    portfolio = analyze_foundation_campaigns(six, cards=cards)
    if portfolio.primary is None:
        raise AssertionError("campaign portfolio has no primary at fixture state")
    deal1 = realize_campaign_to_next_epoch(
        six,
        portfolio.primary,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    if (
        deal1.status != CampaignRealizationStatus.FOUND
        or not deal1.independent_replay_verified
        or deal1.actions.count(("deal",)) != 1
    ):
        raise AssertionError(
            f"Deal-1 prerequisite regression: {deal1.status.value} "
            f"replay={deal1.independent_replay_verified}"
        )
    return opening, six, deal1


def _hard_gate(
    frozen_campaign: FoundationCampaign,
    deal1: CampaignRealizationResult,
    best: CampaignRemovalResult,
    full_actions: Sequence[Action],
    replay_verified: bool,
) -> Tuple[str, Tuple[str, ...]]:
    deals = sum(1 for action in full_actions if action == ("deal",))
    identity_ok = bool(
        best.identity.suit == frozen_campaign.suit
        and best.identity.copy_index == frozen_campaign.copy_index
        and best.identity.target_epoch == frozen_campaign.target_removal_epoch
        and deal1.identity.suit == frozen_campaign.suit
    )
    foundation_ok = bool(
        best.foundation_count_after == best.foundation_count_before + 1
        and best.foundation_suits_added == (frozen_campaign.suit,)
    )
    costs_ok = bool(
        best.corrected_added_cost is not None
        and best.replayed_cost == best.corrected_added_cost
    )
    reasons = (
        f"status={best.status.value} fixed_identity={identity_ok}",
        f"true_opening_replay={replay_verified} added_replay={best.independent_replay_verified}",
        f"deals={deals} stock_after={len(best.end_state.stock)} no_Deal3={deals == 2}",
        f"foundation_count={best.foundation_count_before}->{best.foundation_count_after} "
        f"added_suits={best.foundation_suits_added}",
        f"costs: Deal1_added={deal1.corrected_added_cost} "
        f"Deal2_added={best.corrected_added_cost} recomputed={best.replayed_cost}",
    )
    if (
        best.status == CampaignRemovalStatus.FOUNDATION_REMOVED
        and identity_ok
        and foundation_ok
        and replay_verified
        and best.independent_replay_verified
        and costs_ok
        and deals == 2
        and len(best.end_state.stock) == 30
    ):
        return "STRONG PASS", reasons
    if best.status == CampaignRemovalStatus.BAND_COMPLETE and replay_verified:
        return "PASS", reasons
    if best.actions:
        return "PARTIAL", reasons
    return "FAIL", reasons


def _freeze_prospective(cards: Tuple[Card, ...]) -> FrozenDeal2:
    opening, six, deal1 = _build_verified_deal1(cards)
    post_deal1 = deal1.resulting_state.clone()
    portfolio = analyze_foundation_campaigns(post_deal1, cards=cards)
    campaign = portfolio.primary
    if campaign is None:
        raise AssertionError("post-Deal-1 campaign portfolio has no primary")
    if (
        campaign.suit != deal1.identity.suit
        or campaign.copy_index != deal1.identity.copy_index
        or campaign.target_removal_epoch != deal1.identity.target_epoch
    ):
        raise AssertionError(
            f"fixed campaign regression: Deal1={deal1.identity.label}, "
            f"post={campaign.label}@D{campaign.target_removal_epoch}"
        )

    obligations = campaign_removal_obligations(post_deal1, campaign, cards)
    results = tuple(
        (
            bound,
            realize_campaign_to_removal_epoch(
                post_deal1,
                campaign,
                cards,
                max_added_cost=bound,
                max_nodes=80_000,
                time_limit_s=30,
                beam_width=256,
            ),
        )
        for bound in BOUNDS
    )
    removed = [
        result
        for _bound, result in results
        if result.status == CampaignRemovalStatus.FOUNDATION_REMOVED
        and result.independent_replay_verified
    ]
    if removed:
        best = min(
            removed,
            key=lambda result: (
                result.corrected_added_cost
                if result.corrected_added_cost is not None
                else 999,
                result.nodes_expanded,
            ),
        )
    else:
        best = max(
            (result for _bound, result in results),
            key=lambda result: (
                result.status == CampaignRemovalStatus.BAND_COMPLETE,
                len(result.obligations_satisfied),
                len(result.actions),
            ),
        )

    full_actions = SIX_MOVE_FIXTURE + deal1.actions + best.actions
    replay = opening.clone()
    total_cost = replay_actions(replay, list(full_actions))
    replay_verified = bool(
        states_structurally_equal(replay, best.end_state)
        and total_cost
        == 6 + deal1.corrected_added_cost + best.corrected_added_cost
    )
    verdict, reasons = _hard_gate(
        campaign, deal1, best, full_actions, replay_verified
    )
    return FrozenDeal2(
        cards,
        opening.clone(),
        six.clone(),
        deal1,
        post_deal1,
        campaign,
        obligations,
        results,
        best,
        full_actions,
        total_cost,
        replay_verified,
        verdict,
        reasons,
    )


def _print_progress(result: CampaignRemovalResult) -> None:
    for item in result.progress:
        print(
            f"  {item.phase:<22} g+={item.corrected_added_cost:<2} "
            f"actions={item.action_count:<2} epoch={item.epoch} "
            f"empties={[column + 1 for column in item.empty_columns]} "
            f"foundations={item.foundation_count}"
        )
        for band in item.bands:
            if band.length >= 2:
                print("    band " + _band_line(band))
        print(
            f"    obligations={len(item.obligations_satisfied)} satisfied / "
            f"{len(item.obligations_remaining)} remaining; {item.note}"
        )


def _print_prospective(frozen: FrozenDeal2) -> None:
    best = frozen.best
    print("FOUNDATION CAMPAIGN REALIZER — DEAL 2 / FIRST FOUNDATION")
    print("No plan_search. No whole-game solver. Canonical trace not yet loaded.")
    print()
    print("VERIFIED POST-DEAL-1 START")
    print(_state_line(frozen.post_deal1))
    print(
        f"Deal1 result={frozen.deal1.status.value} "
        f"added_cost={frozen.deal1.corrected_added_cost} "
        f"opening_total=11 replay={frozen.deal1.independent_replay_verified}"
    )
    print()
    print("FROZEN CAMPAIGN IDENTITY")
    print(format_campaign(frozen.campaign))
    print()
    print("CURRENT CAMPAIGN BANDS AND OVERLAYS")
    for band in locate_campaign_bands(frozen.post_deal1, frozen.campaign):
        print("  " + _band_line(band))
    print()
    print("DEAL-1 JOIN / PRE-DEAL-2 OBLIGATIONS")
    for obligation in frozen.obligations:
        print("  " + format_removal_obligation(obligation))
    print()
    print("EXACT DEAL-2 ROW AND DERIVED RECEIVERS")
    print("  row=" + " ".join(str(card) for card in best.exact_row))
    for condition in campaign_receiver_conditions(
        frozen.post_deal1, frozen.campaign
    ):
        print(
            f"  incoming={condition.incoming_card}@c{condition.incoming_column + 1} "
            f"receiver={condition.receiver_rank} direct={condition.direct} "
            f"bounded_walkoff={condition.bounded_walkoff} {condition.note}"
        )
    print()
    print("ITERATIVE BOUNDS")
    for bound, result in frozen.bound_results:
        max_band = max((band.length for band in result.bands_after), default=0)
        print(
            f"  bound={bound:>2} status={result.status.value:<24} "
            f"cost={result.corrected_added_cost!s:<3} nodes={result.nodes_expanded:<5} "
            f"time={result.elapsed_seconds:.3f}s obligations="
            f"{len(result.obligations_satisfied)}/{len(result.obligations)} "
            f"max_band={max_band}"
        )
    print()
    print("BEST COMPLETE ACTION SEQUENCE FROM TRUE OPENING")
    fixture_n = len(SIX_MOVE_FIXTURE)
    deal1_n = len(frozen.deal1.actions)
    for index, action in enumerate(frozen.full_actions, 1):
        if index <= fixture_n:
            role = "fixture-prefix"
        elif index <= fixture_n + deal1_n:
            role = frozen.deal1.action_roles[index - fixture_n - 1]
        else:
            role = best.action_roles[index - fixture_n - deal1_n - 1]
        print(f"  {index:>2}. {format_action(action):<18} [{role}]")
    print(
        f"post_Deal1_added_cost={best.corrected_added_cost} "
        f"total_corrected_from_opening={frozen.total_cost}"
    )
    print()
    print("OBLIGATION AND BAND PROGRESSION")
    _print_progress(best)
    print()
    print("PRE-DEAL-2 TABLEAU")
    if best.pre_deal_state is not None:
        print(_state_line(best.pre_deal_state))
        print(best.pre_deal_state.render(reveal=True))
        print("  receivers after shaping:")
        for condition in best.receiver_conditions:
            print(
                f"    {condition.incoming_card}@c{condition.incoming_column + 1}: "
                f"direct={condition.direct} bounded_walkoff={condition.bounded_walkoff} "
                f"actions={condition.walkoff_actions}"
            )
    print()
    print("IMMEDIATE POST-DEAL-2 TABLEAU")
    if best.immediate_post_deal_state is not None:
        print(_state_line(best.immediate_post_deal_state))
        print(best.immediate_post_deal_state.render(reveal=True))
    print()
    print("FINAL FIRST-FOUNDATION STATE")
    print(_state_line(best.end_state))
    print(best.end_state.render(reveal=True))
    print(
        f"foundation_count={best.foundation_count_before}->{best.foundation_count_after} "
        f"added_suits={best.foundation_suits_added} deals_added={best.deals_applied}"
    )
    print(
        f"independent_replay={best.independent_replay_verified} "
        f"replayed_added_cost={best.replayed_cost} "
        f"true_opening_replay={frozen.replay_verified}"
    )
    print()
    print("WORKSPACE LIFECYCLE")
    for event in frozen.deal1.workspace_events:
        print("  Deal1 " + event)
    if not best.workspace_events:
        print("  Deal2 campaign proceeds with zero empty columns; none created or hoarded.")
    for event in best.workspace_events:
        print("  Deal2 " + event)
    print()
    print("HARD GATE")
    for reason in frozen.gate_reasons:
        print("  " + reason)
    print("VERDICT: " + frozen.verdict)


def _canonical_comparison(frozen: FrozenDeal2) -> None:
    """First canonical read; prospective result is already frozen."""
    print()
    print("PROSPECTIVE RESULT FROZEN — canonical trace may now be loaded.")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = frozen.opening.clone()
    cost = 0
    first_suit = None
    first_state = None
    first_command = None
    for command, action in enumerate(actions, 1):
        before = len(state.foundations)
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            sequence = state.foundations[before]
            first_suit = sequence[0].suit if sequence else None
            first_state = state.clone()
            first_command = command
            break
    print()
    print("CANONICAL FIRST-FOUNDATION COMPARISON (validation only)")
    print(
        f"cost_to_first_foundation: prospective={frozen.total_cost} canonical={cost} "
        f"canonical_command={first_command}"
    )
    print(
        f"foundation_suit: prospective={frozen.best.foundation_suits_added} "
        f"canonical={(first_suit,) if first_suit else ()}"
    )
    if first_state is not None:
        canonical_bands = locate_campaign_bands(first_state, first_suit or "s")
        print(
            f"canonical_at_removal: fd="
            f"{sum(len(column.face_down) for column in first_state.columns)} "
            f"empties={[column + 1 for column in empty_columns(first_state)]} "
            f"remaining_same_suit_bands="
            f"{[(band.high_rank, band.low_rank, band.column + 1) for band in canonical_bands]}"
        )
    print(
        f"prospective_at_removal: fd="
        f"{sum(len(column.face_down) for column in frozen.best.end_state.columns)} "
        f"empties={[column + 1 for column in empty_columns(frozen.best.end_state)]}"
    )
    print(
        "This is a partial-route structural comparison only; no canonical "
        "resemblance, reconnection, or complete-solution improvement is claimed."
    )


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL_PATH))
    frozen = _freeze_prospective(cards)
    _print_prospective(frozen)
    _canonical_comparison(frozen)
    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0 if frozen.verdict == "STRONG PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
