#!/usr/bin/env python3
"""Prospective post-primary campaign transition benchmark.

The first-foundation residual state, residual portfolio, bounds, best route,
and verdict are frozen before the canonical move file is opened.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card, rank_str
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
    CampaignRealizationResult,
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalResult,
    CampaignRemovalStatus,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionResult,
    CampaignTransitionStatus,
    ResidualStateAudit,
    audit_residual_state,
    realize_residual_campaign_transition,
)
from spider.planner.stock_reception import next_stock_row
from spider.state_identity import states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (8, 12, 18, 24, 32)
SIX_MOVE_FIXTURE: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
)


@dataclass(frozen=True)
class FrozenResidualTransition:
    cards: Tuple[Card, ...]
    opening: SpiderState
    six_move_state: SpiderState
    deal1: CampaignRealizationResult
    first_removal: CampaignRemovalResult
    residual_state: SpiderState
    residual_actions: Tuple[Action, ...]
    residual_total_cost: int
    portfolio: FoundationCampaignPortfolio
    campaign: FoundationCampaign
    audit: ResidualStateAudit
    ordering_gap: float
    bound_results: Tuple[Tuple[int, CampaignTransitionResult], ...]
    best: CampaignTransitionResult
    full_actions: Tuple[Action, ...]
    total_cost: int
    full_replay_verified: bool
    verdict: str
    gate_reasons: Tuple[str, ...]


def _schedule_objective(campaign: FoundationCampaign) -> float:
    target = campaign.target_removal_epoch or campaign.current_epoch
    confidence_penalty = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}
    return (
        campaign.estimated_campaign_cost
        + 6.0 * max(0, target - campaign.current_epoch)
        + confidence_penalty.get(campaign.confidence, 6.0)
    )


def _reconstruct_first_foundation(
    cards: Sequence[Card],
) -> Tuple[
    SpiderState,
    SpiderState,
    CampaignRealizationResult,
    CampaignRemovalResult,
    Tuple[Action, ...],
    int,
]:
    opening = SpiderState.from_cards(list(cards))
    six = opening.clone()
    if replay_actions(six, list(SIX_MOVE_FIXTURE)) != 6:
        raise AssertionError("six-move supplied state has drifted")
    first_portfolio = analyze_foundation_campaigns(six, cards=cards)
    if first_portfolio.primary is None:
        raise AssertionError("supplied state has no campaign primary")
    deal1 = realize_campaign_to_next_epoch(
        six,
        first_portfolio.primary,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    if (
        deal1.status != CampaignRealizationStatus.FOUND
        or deal1.corrected_added_cost != 5
        or not deal1.independent_replay_verified
    ):
        raise AssertionError("verified Deal-1 public realizer regression")
    post1_portfolio = analyze_foundation_campaigns(deal1.resulting_state, cards=cards)
    if post1_portfolio.primary is None:
        raise AssertionError("post-Deal-1 state has no fixed primary")
    removal = realize_campaign_to_removal_epoch(
        deal1.resulting_state,
        post1_portfolio.primary,
        cards,
        max_added_cost=12,
        max_nodes=80_000,
        time_limit_s=30,
        beam_width=256,
    )
    if (
        removal.status != CampaignRemovalStatus.FOUNDATION_REMOVED
        or removal.corrected_added_cost != 12
        or not removal.independent_replay_verified
    ):
        raise AssertionError("verified first-foundation public realizer regression")
    residual_actions = SIX_MOVE_FIXTURE + deal1.actions + removal.actions
    checked = opening.clone()
    total = replay_actions(checked, list(residual_actions))
    residual = removal.end_state
    suits = tuple(sequence[0].suit for sequence in residual.foundations if sequence)
    facts_ok = bool(
        total == 23
        and residual_actions.count(("deal",)) == 2
        and len(residual.stock) == 30
        and len(residual.foundations) == 1
        and suits == ("s",)
        and states_structurally_equal(checked, residual)
    )
    if not facts_ok:
        raise AssertionError("cost-23 residual invariants have drifted")
    return opening, six, deal1, removal, residual_actions, total


def _best_result(
    results: Sequence[Tuple[int, CampaignTransitionResult]],
) -> CampaignTransitionResult:
    def key(item: Tuple[int, CampaignTransitionResult]) -> Tuple:
        _bound, result = item
        after = result.campaign_after
        remaining_cost = after.estimated_campaign_cost if after is not None else 0.0
        longest = max((band.length for band in result.bands_after), default=0)
        return (
            result.status == CampaignTransitionStatus.FOUNDATION_REMOVED,
            result.deals_applied == 1,
            -remaining_cost,
            -len(result.must_sources_after),
            longest,
            len(result.obligations_satisfied),
            -(result.corrected_added_cost or 999),
        )

    return max(results, key=key)[1]


def _verdict(
    campaign: FoundationCampaign,
    ordering_gap: float,
    best: CampaignTransitionResult,
    full_replay_verified: bool,
) -> Tuple[str, Tuple[str, ...]]:
    after = best.campaign_after
    cost_before = campaign.estimated_campaign_cost
    cost_after = after.estimated_campaign_cost if after is not None else 0.0
    burden_fell = bool(
        best.status == CampaignTransitionStatus.FOUNDATION_REMOVED
        or cost_after < cost_before - 0.5
        or len(best.must_sources_after) < len(best.must_sources_before)
    )
    obligations_due = tuple(
        obligation
        for obligation in best.obligations
        if obligation.mandatory
        and obligation.deadline_epoch <= best.start_epoch + best.deals_applied
    )
    due_satisfied = all(
        obligation in best.obligations_satisfied for obligation in obligations_due
    )
    reasons = (
        f"ordering_gap={ordering_gap:.1f} primary={campaign.label}",
        f"status={best.status.value} mode={best.mode.value} deals_added={best.deals_applied}",
        f"burden cost~{cost_before:.1f}->{cost_after:.1f} "
        f"MUST={len(best.must_sources_before)}->{len(best.must_sources_after)}",
        f"mandatory_due={len(obligations_due)} all_satisfied={due_satisfied}",
        f"added_replay={best.independent_replay_verified} full_replay={full_replay_verified}",
        f"foundations={best.foundation_count_before}->{best.foundation_count_after} "
        f"added_suits={best.foundation_suits_added}",
    )
    if (
        best.status == CampaignTransitionStatus.FOUNDATION_REMOVED
        and best.foundation_count_after == best.foundation_count_before + 1
        and best.foundation_suits_added == (campaign.suit,)
        and full_replay_verified
        and best.deals_applied <= 1
    ):
        return "EXCEPTIONAL", reasons
    if (
        best.deals_applied == 1
        and full_replay_verified
        and due_satisfied
        and burden_fell
        and ordering_gap >= 3.0
    ):
        return "STRONG PASS", reasons
    if best.deals_applied == 1 and full_replay_verified and burden_fell:
        return "PASS", reasons
    if best.actions and full_replay_verified and burden_fell:
        return "PARTIAL", reasons
    return "FAIL", reasons


def freeze_prospective(cards: Tuple[Card, ...]) -> FrozenResidualTransition:
    opening, six, deal1, first_removal, residual_actions, residual_cost = (
        _reconstruct_first_foundation(cards)
    )
    residual = first_removal.end_state.clone()
    portfolio = analyze_foundation_campaigns(residual, cards=cards)
    campaign = portfolio.primary
    if campaign is None or portfolio.secondary is None:
        raise AssertionError("residual campaign ordering is not rankable")
    ordering_gap = _schedule_objective(portfolio.secondary) - _schedule_objective(campaign)
    audit = audit_residual_state(residual, campaign, cards)
    results = tuple(
        (
            bound,
            realize_residual_campaign_transition(
                residual,
                campaign,
                cards,
                max_added_cost=bound,
                max_nodes=180_000,
                time_limit_s=45,
                beam_width=512,
            ),
        )
        for bound in BOUNDS
    )
    best = _best_result(results)
    full_actions = residual_actions + best.actions
    replayed = opening.clone()
    total = replay_actions(replayed, list(full_actions))
    full_replay = bool(
        best.corrected_added_cost is not None
        and total == residual_cost + best.corrected_added_cost
        and states_structurally_equal(replayed, best.resulting_state)
        and full_actions.count(("deal",)) <= 3
    )
    verdict, reasons = _verdict(campaign, ordering_gap, best, full_replay)
    return FrozenResidualTransition(
        cards,
        opening,
        six,
        deal1,
        first_removal,
        residual,
        residual_actions,
        residual_cost,
        portfolio,
        campaign,
        audit,
        ordering_gap,
        results,
        best,
        full_actions,
        total,
        full_replay,
        verdict,
        reasons,
    )


def _state_line(state: SpiderState) -> str:
    return (
        f"fd={sum(len(column.face_down) for column in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"empties={[i + 1 for i, column in enumerate(state.columns) if column.is_empty()]}"
    )


def _print_audit(audit: ResidualStateAudit) -> None:
    print(
        f"face_down={audit.face_down_cards} stock={audit.stock_size} "
        f"foundations={audit.foundation_count} suits={audit.foundation_suits}"
    )
    print(
        f"empties={[column + 1 for column in audit.empty_columns]} "
        f"fully_open={audit.fully_open_columns} "
        f"fully_open_nonking={audit.fully_open_nonking_columns}"
    )
    print(
        f"workspace_create_cost={audit.cheapest_workspace_cost} "
        f"({audit.workspace_status}) legal_moves={audit.legal_move_count}"
    )
    print(
        f"longest_same_suit_run={audit.longest_same_suit_run} "
        f"total_run_mass={audit.total_same_suit_run_mass} "
        f"mixed_desc_boundaries={len(audit.mixed_suit_boundaries)}"
    )
    for item in audit.suit_bands:
        print(
            f"  {item.suit.upper()}: longest={item.longest_run} mass={item.total_run_mass} "
            f"bands={[band.label for band in item.bands]}"
        )
    print(f"campaign_usable={audit.campaign_usable_source_keys}")
    print(f"campaign_buried={audit.campaign_buried_source_keys}")


def print_prospective(frozen: FrozenResidualTransition) -> None:
    print("POST-PRIMARY RESIDUAL CAMPAIGN TRANSITION")
    print("No plan_search. At most one new deal. Canonical trace not yet loaded.")
    print()
    print("PUBLIC-API RECONSTRUCTION OF COST-23 RESIDUAL")
    print(
        f"Deal1={frozen.deal1.status.value}/cost{frozen.deal1.corrected_added_cost} "
        f"first_removal={frozen.first_removal.status.value}/"
        f"cost{frozen.first_removal.corrected_added_cost}"
    )
    print(
        f"total={frozen.residual_total_cost} deals={frozen.residual_actions.count(('deal',))} "
        f"{_state_line(frozen.residual_state)} replay=verified"
    )
    print(frozen.residual_state.render(reveal=True))
    print()
    print("RESIDUAL QUALITY AUDIT")
    _print_audit(frozen.audit)
    print()
    print("FROZEN RESIDUAL CAMPAIGN PORTFOLIO")
    for index, campaign in enumerate(frozen.portfolio.campaigns, 1):
        role = "PRIMARY" if index == 1 else "SECONDARY" if index == 2 else "DEFERRED"
        print(
            f"{role:<9} {campaign.label} target=D{campaign.target_removal_epoch} "
            f"objective={_schedule_objective(campaign):.1f} "
            f"score={campaign.campaign_score:.1f} cost~{campaign.estimated_campaign_cost:.1f} "
            f"MUST={len(campaign.tableau_critical_cards)} "
            f"stock={len(campaign.future_stock_supplied_cards)}"
        )
    print(f"primary_to_runner_up_objective_gap={frozen.ordering_gap:.1f}")
    print()
    print("SELECTED PRIMARY")
    print(format_campaign(frozen.campaign))
    print(
        "MUST="
        + str(
            tuple(
                (str(source.card), source.source_key)
                for source in frozen.campaign.tableau_critical_cards
            )
        )
    )
    print(
        "SAFE_TO_WAIT="
        + str(
            tuple(
                (str(source.card), source.source_key)
                for source in frozen.campaign.optional_replaceable_buried_copies
            )
        )
    )
    print(
        f"mode={frozen.best.mode.value} target_epoch={frozen.best.target_epoch} "
        f"workspace={frozen.campaign.space_plan.policy.value}: "
        f"{frozen.campaign.space_plan.enabled_action}"
    )
    print()
    print("GENERATED STRUCTURAL OBLIGATIONS")
    for obligation in frozen.best.obligations:
        print(
            f"  {obligation.obligation_id:<28} {obligation.kind.value:<28} "
            f"mandatory={obligation.mandatory} {obligation.description}"
        )
    if frozen.best.exact_row:
        print("exact_next_row=" + " ".join(str(card) for card in frozen.best.exact_row))
    else:
        print(
            "exact_Deal3_row=not applied: current-epoch tableau-only removal mode; "
            "Deal3 is outside this transition"
        )
        print(
            "known_next_row_if_a_later campaign were selected="
            + " ".join(str(card) for card in (next_stock_row(frozen.residual_state) or ()))
        )
    print()
    print("ITERATIVE BOUNDS")
    for bound, result in frozen.bound_results:
        after = result.campaign_after
        after_cost = after.estimated_campaign_cost if after is not None else 0.0
        longest = max((band.length for band in result.bands_after), default=0)
        print(
            f"  bound={bound:>2} status={result.status.value:<24} "
            f"added={result.corrected_added_cost!s:<3} total="
            f"{(23 + result.corrected_added_cost) if result.corrected_added_cost is not None else '-':<3} "
            f"nodes={result.nodes_expanded:<6} time={result.elapsed_seconds:.3f}s "
            f"obligations={len(result.obligations_satisfied)}/{len(result.obligations)} "
            f"foundations={result.foundation_count_before}->{result.foundation_count_after} "
            f"MUST={len(result.must_sources_before)}->{len(result.must_sources_after)} "
            f"cost~={frozen.campaign.estimated_campaign_cost:.1f}->{after_cost:.1f} "
            f"longest={longest}"
        )
    print()
    print("BEST COMPLETE ACTION SEQUENCE FROM TRUE OPENING")
    fixture_end = len(SIX_MOVE_FIXTURE)
    deal1_end = fixture_end + len(frozen.deal1.actions)
    removal_end = deal1_end + len(frozen.first_removal.actions)
    for index, action in enumerate(frozen.full_actions, 1):
        if index <= fixture_end:
            role = "fixture-prefix"
        elif index <= deal1_end:
            role = frozen.deal1.action_roles[index - fixture_end - 1]
        elif index <= removal_end:
            role = frozen.first_removal.action_roles[index - deal1_end - 1]
        else:
            role = frozen.best.action_roles[index - removal_end - 1]
        print(f"  {index:>2}. {format_action(action):<18} [{role}]")
    print(
        f"residual_total=23 transition_added={frozen.best.corrected_added_cost} "
        f"total_from_opening={frozen.total_cost} full_replay={frozen.full_replay_verified}"
    )
    print()
    print("RESULTING CAMPAIGN STATE")
    print(_state_line(frozen.best.resulting_state))
    print(frozen.best.resulting_state.render(reveal=True))
    after = frozen.best.campaign_after
    print(
        f"campaign={frozen.best.identity.label} status={frozen.best.status.value} "
        f"score={frozen.campaign.campaign_score:.1f}->"
        f"{after.campaign_score if after is not None else 0.0:.1f} "
        f"cost~={frozen.campaign.estimated_campaign_cost:.1f}->"
        f"{after.estimated_campaign_cost if after is not None else 0.0:.1f} "
        f"MUST={len(frozen.best.must_sources_before)}->{len(frozen.best.must_sources_after)}"
    )
    print(
        f"bands_before={[band.label for band in frozen.best.bands_before]}\n"
        f"bands_after={[band.label for band in frozen.best.bands_after]}"
    )
    print("workspace_events=" + str(frozen.best.workspace_events))
    print(
        f"foundations={frozen.best.foundation_count_before}->"
        f"{frozen.best.foundation_count_after} added={frozen.best.foundation_suits_added} "
        f"deals_added={frozen.best.deals_applied}"
    )
    print()
    print("HARD GATE")
    for reason in frozen.gate_reasons:
        print("  " + reason)
    print("VERDICT: " + frozen.verdict)


def canonical_comparison(frozen: FrozenResidualTransition) -> None:
    """First canonical read; all prospective fields are already frozen."""
    print()
    print("PROSPECTIVE RESULT FROZEN — canonical trace may now be loaded.")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = frozen.opening.clone()
    cost = 0
    order = []
    first_state = None
    first_cost = None
    first_command = None
    for command, action in enumerate(actions, 1):
        before = len(state.foundations)
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            for sequence in state.foundations[before:]:
                if sequence:
                    order.append(sequence[0].suit)
            if first_state is None:
                first_state = state.clone()
                first_cost = cost
                first_command = command
    print("CANONICAL COMPARISON (validation only)")
    print(f"canonical_foundation_order={tuple(order)}")
    if first_state is not None:
        print(
            f"comparable_first_foundation: cost={first_cost} command={first_command} "
            f"{_state_line(first_state)} legal_moves={len(first_state.enumerate_moves())}"
        )
        print(
            f"canonical_remaining_run_mass="
            f"{sum(band.length for suit in 'cdhs' for band in locate_campaign_bands(first_state, suit))}"
        )
    print(
        f"prospective_after_transition: cost={frozen.total_cost} "
        f"{_state_line(frozen.best.resulting_state)} "
        f"legal_moves={len(frozen.best.resulting_state.enumerate_moves())}"
    )
    print(
        "The ordering was not trained against canonical history, and this "
        "partial route is not a complete-solution improvement claim."
    )


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL_PATH))
    frozen = freeze_prospective(cards)
    print_prospective(frozen)
    canonical_comparison(frozen)
    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0 if frozen.verdict in ("EXCEPTIONAL", "STRONG PASS", "PASS", "PARTIAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
