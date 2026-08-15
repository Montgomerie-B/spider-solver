#!/usr/bin/env python3
"""Prospective Deal-1 campaign-realizer diagnostic for the benchmark deal.

Benchmark identifiers and setup actions are fixture data in this diagnostic
only.  The prospective campaign, obligations, bounded results, best route and
post-deal analysis are all frozen before the canonical move file is opened.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, format_action, parse_moves_file, replay_actions
from spider.planner.foundation_campaign import (
    FoundationCampaign,
    FoundationCampaignPortfolio,
    analyze_foundation_campaigns,
    format_campaign,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignObligationKind,
    CampaignRealizationResult,
    CampaignRealizationStatus,
    campaign_obligations_for_next_epoch,
    format_obligation,
    obligation_is_satisfied,
    realize_campaign_to_next_epoch,
)
from spider.planner.space_lifecycle import empty_columns


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (6, 10, 14, 18, 24)

BENCHMARK_PREFIX: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
)


@dataclass(frozen=True)
class FrozenProspective:
    opening: SpiderState
    start: SpiderState
    portfolio_before: FoundationCampaignPortfolio
    campaign_before: FoundationCampaign
    bound_results: Tuple[Tuple[int, CampaignRealizationResult], ...]
    best: CampaignRealizationResult
    predeal: SpiderState
    portfolio_after: FoundationCampaignPortfolio
    full_actions: Tuple[Action, ...]
    total_cost: int
    gate: str
    gate_reasons: Tuple[str, ...]


def _state_line(state: SpiderState) -> str:
    tops = " ".join(str(card) if card else "--" for card in state.top_row())
    return (
        f"tops=[{tops}] fd={sum(len(c.face_down) for c in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"empties={[column + 1 for column in empty_columns(state)]}"
    )


def _build_start(cards: Sequence[Card]) -> Tuple[SpiderState, SpiderState]:
    opening = SpiderState.from_cards(list(cards))
    start = opening.clone()
    cost = replay_actions(start, list(BENCHMARK_PREFIX))
    if cost != 6 or empty_columns(start) != (5,):
        raise AssertionError(
            f"six-move fixture drift: cost={cost}, empties={empty_columns(start)}"
        )
    run = tuple(str(card) for card in start.columns[7].face_up[-5:])
    if run != ("6s", "5s", "4s", "3s", "2s"):
        raise AssertionError(f"campaign fragment drift: {run}")
    return opening, start


def _predeal_state(start: SpiderState, result: CampaignRealizationResult) -> SpiderState:
    state = start.clone()
    actions = result.actions[:-1] if result.actions and result.actions[-1] == ("deal",) else result.actions
    replay_actions(state, list(actions))
    return state


def _gate(
    start: SpiderState,
    before: FoundationCampaign,
    result: CampaignRealizationResult,
    predeal: SpiderState,
    after_portfolio: FoundationCampaignPortfolio,
) -> Tuple[str, Tuple[str, ...]]:
    after = result.campaign_after
    mandatory = [
        obligation
        for obligation in result.obligations_initial
        if obligation.mandatory_before_deal
    ]
    mandatory_ok = all(
        obligation_is_satisfied(
            predeal,
            before,
            obligation,
            accomplished=tuple(
                item.obligation_id for item in result.obligations_satisfied
            ),
        )
        for obligation in mandatory
    )
    critical = [
        obligation
        for obligation in result.obligations_initial
        if obligation.kind == CampaignObligationKind.EXCAVATE_PREFIX
    ]
    critical_ok = bool(critical) and all(
        obligation_is_satisfied(predeal, before, obligation)
        for obligation in critical
    )
    primary_ok = bool(
        after_portfolio.primary
        and after_portfolio.primary.suit == before.suit
        and after_portfolio.primary.copy_index == before.copy_index
        and after_portfolio.primary.target_removal_epoch == before.target_removal_epoch
    )
    burden_improved = bool(
        after
        and after.estimated_campaign_cost <= before.estimated_campaign_cost - 3
        and after.campaign_score > before.campaign_score
    )
    useful_receiver = bool(result.receiver_conditions_satisfied)
    reasons = (
        f"route_status={result.status.value} replay={result.independent_replay_verified}",
        f"mandatory_predeal={mandatory_ok} critical_prefix={critical_ok}",
        f"receiver_conditions={len(result.receiver_conditions_satisfied)}/"
        f"{len(result.receiver_conditions_satisfied) + len(result.receiver_conditions_remaining)}",
        f"postdeal_primary={after_portfolio.primary.label if after_portfolio.primary else '--'} "
        f"target=D{after_portfolio.primary.target_removal_epoch if after_portfolio.primary else '--'}",
        f"estimated_burden={before.estimated_campaign_cost} -> "
        f"{after.estimated_campaign_cost if after else '--'}; score="
        f"{before.campaign_score} -> {after.campaign_score if after else '--'}",
        f"workspace_events={len(result.workspace_events)} start_empties="
        f"{[c + 1 for c in empty_columns(start)]} predeal_empties="
        f"{[c + 1 for c in empty_columns(predeal)]}",
    )
    if (
        result.status == CampaignRealizationStatus.FOUND
        and result.independent_replay_verified
        and mandatory_ok
        and critical_ok
        and useful_receiver
        and primary_ok
        and burden_improved
    ):
        return "STRONG PASS", reasons
    if (
        result.status == CampaignRealizationStatus.FOUND
        and result.independent_replay_verified
        and critical_ok
        and primary_ok
        and burden_improved
    ):
        return "PASS", reasons
    if critical_ok:
        return "PARTIAL", reasons
    return "FAIL", reasons


def _freeze_prospective(cards: Sequence[Card]) -> FrozenProspective:
    opening, start = _build_start(cards)
    portfolio = analyze_foundation_campaigns(start, cards=cards)
    campaign = portfolio.primary
    if campaign is None:
        raise AssertionError("generic campaign portfolio has no primary")
    if campaign.suit != "s" or campaign.copy_index != 1 or campaign.target_removal_epoch != 2:
        raise AssertionError(
            f"benchmark campaign regression: {campaign.label} "
            f"target={campaign.target_removal_epoch}"
        )

    obligations = campaign_obligations_for_next_epoch(start, campaign, cards)
    critical_cards = {
        obligation.rank
        for obligation in obligations
        if obligation.kind == CampaignObligationKind.EXCAVATE_PREFIX
    }
    if 10 not in critical_cards:
        raise AssertionError("campaign-critical 10s obligation missing; stop before search")

    results = []
    for bound in BOUNDS:
        results.append(
            (
                bound,
                realize_campaign_to_next_epoch(
                    start,
                    campaign,
                    cards,
                    max_added_cost=bound,
                    max_nodes=60_000,
                    time_limit_s=30.0,
                ),
            )
        )
    found = [
        result
        for _bound, result in results
        if result.status == CampaignRealizationStatus.FOUND
        and result.independent_replay_verified
    ]
    if not found:
        best = max(
            (result for _bound, result in results),
            key=lambda result: (
                len(result.obligations_satisfied),
                len(result.actions),
                -result.nodes_expanded,
            ),
        )
    else:
        best = min(
            found,
            key=lambda result: (
                result.corrected_added_cost
                if result.corrected_added_cost is not None
                else 999,
                len(result.actions),
                result.nodes_expanded,
            ),
        )
    predeal = _predeal_state(start, best)
    after_portfolio = analyze_foundation_campaigns(best.resulting_state, cards=cards)
    full_actions = BENCHMARK_PREFIX + best.actions
    replay = opening.clone()
    total_cost = replay_actions(replay, list(full_actions))
    if not states_equal(replay, best.resulting_state):
        raise AssertionError("true-opening replay does not reproduce frozen result")
    gate, reasons = _gate(start, campaign, best, predeal, after_portfolio)
    return FrozenProspective(
        opening=opening.clone(),
        start=start.clone(),
        portfolio_before=portfolio,
        campaign_before=campaign,
        bound_results=tuple(results),
        best=best,
        predeal=predeal,
        portfolio_after=after_portfolio,
        full_actions=full_actions,
        total_cost=total_cost,
        gate=gate,
        gate_reasons=reasons,
    )


def states_equal(left: SpiderState, right: SpiderState) -> bool:
    # Local wrapper keeps this diagnostic independent of object identity.
    from spider.state_identity import states_structurally_equal

    return states_structurally_equal(left, right)


def _print_prospective(frozen: FrozenProspective) -> None:
    before = frozen.campaign_before
    best = frozen.best
    after = best.campaign_after
    print("FOUNDATION CAMPAIGN REALIZER — THROUGH DEAL 1")
    print("No plan_search. No whole-game solver. Canonical trace not yet loaded.")
    print()
    print("BENCHMARK START (six verified paid moves from opening)")
    print(_state_line(frozen.start))
    print("corrected_cost_from_opening=6")
    print()
    print("FROZEN PROSPECTIVE CAMPAIGN")
    print(format_campaign(before))
    print()
    print("NEXT-EPOCH OBLIGATIONS")
    for obligation in best.obligations_initial:
        print("  " + format_obligation(obligation))
    print()
    print("ITERATIVE BOUNDS")
    for bound, result in frozen.bound_results:
        print(
            f"  bound={bound:>2} status={result.status.value:<25} "
            f"cost={result.corrected_added_cost!s:<3} nodes={result.nodes_expanded:<6} "
            f"time={result.elapsed_seconds:.3f}s replay={result.independent_replay_verified}"
        )
    print()
    print("BEST ROUTE FROM TRUE OPENING")
    for index, action in enumerate(frozen.full_actions, 1):
        role = "fixture-prefix" if index <= len(BENCHMARK_PREFIX) else best.action_roles[index - len(BENCHMARK_PREFIX) - 1]
        print(f"  {index:>2}. {format_action(action):<18} [{role}]")
    print(
        f"added_cost_from_six_move_state={best.corrected_added_cost} "
        f"total_cost_from_opening={frozen.total_cost}"
    )
    print()
    print("OBLIGATION PROGRESSION")
    for item in best.progress:
        print(
            f"  {item.phase:<12} g+={item.corrected_added_cost:<2} "
            f"actions={item.action_count:<2} empties={[c + 1 for c in item.empty_columns]} "
            f"satisfied={len(item.satisfied)} remaining={len(item.remaining)}"
        )
        print(f"    {item.note}")
    print()
    print("WORKSPACE EVENTS")
    for event in best.workspace_events:
        print("  " + event)
    print()
    print("PRE-DEAL-1 TABLEAU")
    print(_state_line(frozen.predeal))
    print(frozen.predeal.render(reveal=True))
    print("exact_next_row=" + " ".join(str(card) for card in best.exact_row))
    print()
    print("POST-DEAL-1 TABLEAU")
    print(_state_line(best.resulting_state))
    print(best.resulting_state.render(reveal=True))
    print()
    print("POST-DEAL CAMPAIGN")
    if after is not None:
        print(format_campaign(after))
    print(
        f"primary_after={frozen.portfolio_after.primary.label if frozen.portfolio_after.primary else '--'} "
        f"target=D{frozen.portfolio_after.primary.target_removal_epoch if frozen.portfolio_after.primary else '--'}"
    )
    print(
        f"MUST source keys before={best.must_sources_before}\n"
        f"MUST source keys after ={best.must_sources_after}"
    )
    print(
        f"receivers_satisfied={best.receiver_conditions_satisfied}\n"
        f"receivers_missed={best.receiver_conditions_remaining}"
    )
    if after is not None:
        print(
            f"metrics: cost~ {before.estimated_campaign_cost} -> {after.estimated_campaign_cost}; "
            f"score {before.campaign_score} -> {after.campaign_score}; "
            f"readiness {before.readiness.value} -> {after.readiness.value}; "
            f"confidence {before.confidence} -> {after.confidence}"
        )
        print(
            f"workspace: start={[c + 1 for c in empty_columns(frozen.start)]} "
            f"predeal={[c + 1 for c in empty_columns(frozen.predeal)]} "
            f"postdeal={[c + 1 for c in empty_columns(best.resulting_state)]}; "
            f"modeled_regain={before.space_plan.estimated_regain_cost} -> "
            f"{after.space_plan.estimated_regain_cost}"
        )
    print(
        f"independent_replay={best.independent_replay_verified} "
        f"replayed_added_cost={best.replayed_cost} nodes={best.nodes_expanded} "
        f"runtime={best.elapsed_seconds:.3f}s"
    )
    print()
    print("HARD GATE")
    for reason in frozen.gate_reasons:
        print("  " + reason)
    print("VERDICT: " + frozen.gate)


def _canonical_comparison(frozen: FrozenProspective) -> None:
    """Load canonical data only after the prospective result is frozen."""
    print()
    print("PROSPECTIVE RESULT FROZEN — canonical trace may now be loaded.")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = frozen.opening.clone()
    cost = 0
    first_deal_cost = None
    first_foundation = None
    predeal = None
    for action in actions:
        if action == ("deal",) and predeal is None:
            predeal = state.clone()
        before_foundations = len(state.foundations)
        cost += replay_actions(state, [action])
        if action == ("deal",) and first_deal_cost is None:
            first_deal_cost = cost
        if len(state.foundations) > before_foundations and first_foundation is None:
            sequence = state.foundations[before_foundations]
            first_foundation = sequence[0].suit.upper() if sequence else "?"
            break
    print()
    print("CANONICAL COMPARISON (validation only)")
    print(
        f"cost_through_Deal1: prospective={frozen.total_cost} "
        f"canonical={first_deal_cost}"
    )
    print(
        f"first_foundation_campaign: prospective="
        f"{frozen.campaign_before.suit.upper()} canonical={first_foundation}"
    )
    if predeal is not None:
        print("canonical_preDeal1=" + _state_line(predeal))
    print(
        "Comparison is intentionally broad: no hash match, route resemblance, "
        "or canonical reconnection is required."
    )


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL_PATH))
    frozen = _freeze_prospective(cards)
    _print_prospective(frozen)
    # The first canonical file read occurs inside this call, after freeze/print.
    _canonical_comparison(frozen)
    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0 if frozen.gate in ("STRONG PASS", "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
