#!/usr/bin/env python3
"""Prospective continuation of the reanalysed cost-47 campaign."""

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
    FoundationCampaignPortfolio,
    analyze_foundation_campaigns,
    format_campaign,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignIdentity,
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    bands_can_join,
    campaign_band_recovery,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionResult,
    CampaignTransitionStatus,
    ResidualStateAudit,
    audit_residual_state,
    campaign_transition_obligations,
    derive_transition_mode,
    realize_residual_campaign_transition,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.state_identity import states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (6, 10, 15, 20, 28)
SIX_MOVE_FIXTURE: Tuple[Action, ...] = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
)


@dataclass(frozen=True)
class ReconstructedCost47:
    cards: Tuple[Card, ...]
    opening: SpiderState
    cost23_state: SpiderState
    cost23_portfolio: FoundationCampaignPortfolio
    state: SpiderState
    actions: Tuple[Action, ...]
    total_cost: int
    advanced_identity: CampaignIdentity
    portfolio: FoundationCampaignPortfolio
    campaign: FoundationCampaign
    replay_verified: bool


@dataclass(frozen=True)
class FrozenContinuation:
    reconstructed: ReconstructedCost47
    audit_before: ResidualStateAudit
    bounds: Tuple[Tuple[int, CampaignTransitionResult], ...]
    best: CampaignTransitionResult | None
    full_actions: Tuple[Action, ...]
    total_cost: int
    full_replay_verified: bool
    verdict: str
    audit_after: ResidualStateAudit


def schedule_objective(campaign: FoundationCampaign) -> float:
    target = campaign.target_removal_epoch or campaign.current_epoch
    penalty = {"HIGH": 0.0, "MEDIUM": 2.0, "LOW": 6.0}
    return (
        campaign.estimated_campaign_cost
        + 6.0 * max(0, target - campaign.current_epoch)
        + penalty.get(campaign.confidence, 6.0)
    )


def same_campaign_remains_primary(
    identity: CampaignIdentity, portfolio: FoundationCampaignPortfolio
) -> bool:
    primary = portfolio.primary
    return bool(
        primary is not None
        and primary.suit == identity.suit
        and primary.copy_index == identity.copy_index
        and primary.target_removal_epoch == identity.target_epoch
    )


def reconstruct_cost47(cards: Sequence[Card]) -> ReconstructedCost47:
    frozen_cards = tuple(cards)
    opening = SpiderState.from_cards(list(frozen_cards))
    six = opening.clone()
    if replay_actions(six, list(SIX_MOVE_FIXTURE)) != 6:
        raise AssertionError("six-move fixture cost drift")
    opening_portfolio = analyze_foundation_campaigns(six, cards=frozen_cards)
    if opening_portfolio.primary is None:
        raise AssertionError("six-move state has no primary")
    deal1 = realize_campaign_to_next_epoch(
        six,
        opening_portfolio.primary,
        frozen_cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    if (
        deal1.status != CampaignRealizationStatus.FOUND
        or deal1.corrected_added_cost != 5
        or not deal1.independent_replay_verified
    ):
        raise AssertionError("Deal-1 public realizer regression")
    post1 = analyze_foundation_campaigns(deal1.resulting_state, cards=frozen_cards)
    if post1.primary is None:
        raise AssertionError("post-Deal-1 state has no primary")
    first = realize_campaign_to_removal_epoch(
        deal1.resulting_state,
        post1.primary,
        frozen_cards,
        max_added_cost=12,
        max_nodes=80_000,
        time_limit_s=30,
        beam_width=256,
    )
    if (
        first.status != CampaignRemovalStatus.FOUNDATION_REMOVED
        or first.corrected_added_cost != 12
        or not first.independent_replay_verified
    ):
        raise AssertionError("first-foundation public realizer regression")
    residual = analyze_foundation_campaigns(first.end_state, cards=frozen_cards)
    if residual.primary is None:
        raise AssertionError("cost-23 residual has no primary")
    advanced = realize_residual_campaign_transition(
        first.end_state,
        residual.primary,
        frozen_cards,
        max_added_cost=24,
        max_nodes=180_000,
        time_limit_s=45,
        beam_width=512,
    )
    if (
        advanced.status != CampaignTransitionStatus.CAMPAIGN_ADVANCED
        or advanced.corrected_added_cost != 24
        or not advanced.independent_replay_verified
        or advanced.deals_applied != 0
    ):
        raise AssertionError("verified 24-cost residual transition regression")
    actions = SIX_MOVE_FIXTURE + deal1.actions + first.actions + advanced.actions
    replayed = opening.clone()
    total = replay_actions(replayed, list(actions))
    state = advanced.resulting_state
    suits = tuple(sequence[0].suit for sequence in state.foundations if sequence)
    replay_ok = states_structurally_equal(replayed, state)
    facts_ok = bool(
        total == 47
        and actions.count(("deal",)) == 2
        and len(state.stock) == 30
        and len(state.foundations) == 1
        and suits == ("s",)
        and current_stock_epoch(state, 5) == 2
        and sum(len(column.face_down) for column in state.columns) == 21
        and replay_ok
    )
    if not facts_ok:
        raise AssertionError("cost-47 invariants have drifted")
    portfolio = analyze_foundation_campaigns(state, cards=frozen_cards)
    if portfolio.primary is None:
        raise AssertionError("cost-47 state has no primary")
    return ReconstructedCost47(
        cards=frozen_cards,
        opening=opening,
        cost23_state=first.end_state.clone(),
        cost23_portfolio=residual,
        state=state.clone(),
        actions=actions,
        total_cost=total,
        advanced_identity=advanced.identity,
        portfolio=portfolio,
        campaign=portfolio.primary,
        replay_verified=replay_ok,
    )


def _best_result(
    results: Sequence[Tuple[int, CampaignTransitionResult]],
) -> CampaignTransitionResult:
    removed = [
        result
        for _bound, result in results
        if result.status == CampaignTransitionStatus.FOUNDATION_REMOVED
        and result.independent_replay_verified
    ]
    if removed:
        return min(
            removed,
            key=lambda result: (
                result.corrected_added_cost
                if result.corrected_added_cost is not None
                else 999,
                result.nodes_expanded,
            ),
        )
    return min(
        (result for _bound, result in results),
        key=lambda result: (
            len(result.must_sources_after),
            result.campaign_after.estimated_campaign_cost
            if result.campaign_after is not None
            else 999,
            -(len(result.obligations_satisfied)),
            result.corrected_added_cost
            if result.corrected_added_cost is not None
            else 999,
            result.nodes_expanded,
        ),
    )


def freeze_prospective(cards: Tuple[Card, ...]) -> FrozenContinuation:
    reconstructed = reconstruct_cost47(cards)
    if not same_campaign_remains_primary(
        reconstructed.advanced_identity, reconstructed.portfolio
    ):
        audit = audit_residual_state(
            reconstructed.state, reconstructed.campaign, cards
        )
        return FrozenContinuation(
            reconstructed=reconstructed,
            audit_before=audit,
            bounds=(),
            best=None,
            full_actions=reconstructed.actions,
            total_cost=reconstructed.total_cost,
            full_replay_verified=reconstructed.replay_verified,
            verdict="PARTIAL",
            audit_after=audit,
        )
    audit_before = audit_residual_state(
        reconstructed.state, reconstructed.campaign, cards
    )
    results = tuple(
        (
            bound,
            realize_residual_campaign_transition(
                reconstructed.state,
                reconstructed.campaign,
                cards,
                max_added_cost=bound,
                max_nodes=240_000,
                time_limit_s=60,
                beam_width=1_024,
            ),
        )
        for bound in BOUNDS
    )
    best = _best_result(results)
    full_actions = reconstructed.actions + best.actions
    replayed = reconstructed.opening.clone()
    total = replay_actions(replayed, list(full_actions))
    replay_ok = bool(
        best.corrected_added_cost is not None
        and total == 47 + best.corrected_added_cost
        and states_structurally_equal(replayed, best.resulting_state)
        and full_actions.count(("deal",)) == 2
    )
    if best.status == CampaignTransitionStatus.FOUNDATION_REMOVED and replay_ok:
        if total <= 62:
            verdict = "EXCEPTIONAL"
        elif total <= 72:
            verdict = "STRONG PASS"
        else:
            verdict = "PASS"
    else:
        verdict = "FAIL"
    campaign_after = best.campaign_after or reconstructed.campaign
    audit_after = audit_residual_state(best.resulting_state, campaign_after, cards)
    return FrozenContinuation(
        reconstructed,
        audit_before,
        results,
        best,
        full_actions,
        total,
        replay_ok,
        verdict,
        audit_after,
    )


def _state_line(state: SpiderState) -> str:
    return (
        f"fd={sum(len(column.face_down) for column in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"epoch={current_stock_epoch(state, 5)} "
        f"empties={[i + 1 for i, column in enumerate(state.columns) if column.is_empty()]}"
    )


def _print_portfolio(portfolio: FoundationCampaignPortfolio) -> None:
    for index, campaign in enumerate(portfolio.campaigns, 1):
        role = "PRIMARY" if index == 1 else "RUNNER-UP" if index == 2 else "DEFERRED"
        print(
            f"  {role:<9} {campaign.label} target=D{campaign.target_removal_epoch} "
            f"objective={schedule_objective(campaign):.1f} "
            f"score={campaign.campaign_score:.1f} cost~{campaign.estimated_campaign_cost:.1f} "
            f"{campaign.readiness.value}/{campaign.confidence} "
            f"MUST={len(campaign.tableau_critical_cards)} "
            f"stock={len(campaign.future_stock_supplied_cards)}"
        )


def print_prospective(frozen: FrozenContinuation) -> None:
    reconstructed = frozen.reconstructed
    campaign = reconstructed.campaign
    best = frozen.best
    print("RESIDUAL CAMPAIGN CONTINUATION TO ACTUAL REMOVAL")
    print("No Deal 3. No whole-game search. Canonical trace not yet loaded.")
    print()
    print("PUBLIC-API COST-47 RECONSTRUCTION")
    print(
        f"total={reconstructed.total_cost} actions={len(reconstructed.actions)} "
        f"deals={reconstructed.actions.count(('deal',))} "
        f"replay={reconstructed.replay_verified} {_state_line(reconstructed.state)}"
    )
    print(reconstructed.state.render(reveal=True))
    print()
    print("REANALYSED PORTFOLIO (PROSPECTIVE)")
    _print_portfolio(reconstructed.portfolio)
    print(
        f"same_primary_persisted="
        f"{same_campaign_remains_primary(reconstructed.advanced_identity, reconstructed.portfolio)}"
    )
    if best is None:
        print()
        print("HARD GATE")
        print("VERDICT: PARTIAL")
        print(
            "The generic primary changed after reanalysis; the previously "
            "advanced campaign was not forced and no continuation search ran."
        )
        return
    print()
    print("FIXED CAMPAIGN")
    print(format_campaign(campaign))
    print("BANDS AND DIRECT JOINS")
    bands = locate_campaign_bands(reconstructed.state, campaign)
    for band in bands:
        recovery = campaign_band_recovery(band)
        print(
            f"  {band.label:<20} movable={band.movable} covered={band.covered} "
            f"cover={tuple(str(card) for card in band.covering_cards)} "
            f"cover_groups={recovery.covering_groups}"
        )
    joins = tuple(
        (upper.label, lower.label)
        for upper in bands
        for lower in bands
        if bands_can_join(upper, lower)
    )
    print(f"direct_band_joins={joins}")
    print(
        "remaining_MUST="
        + str(
            tuple(
                (str(source.card), source.source_key, source.column + 1)
                for source in campaign.tableau_critical_cards
                if source.column is not None
            )
        )
    )
    print(
        "projects="
        + str(
            tuple(
                (
                    project.column + 1,
                    project.required_ranks,
                    project.required_peels,
                    tuple((column + 1, depth) for column, depth in project.helper_tasks),
                    project.needs_temp_space,
                )
                for project in campaign.prerequisite_excavation_projects
            )
        )
    )
    print(
        f"workspace={campaign.space_plan.policy.value} "
        f"create_cost={campaign.space_plan.cheapest_recoverable_workspace} "
        f"{campaign.space_plan.enabled_action}"
    )
    print()
    print("FRESH CONTINUATION OBLIGATIONS")
    for obligation in campaign_transition_obligations(
        reconstructed.state, campaign, reconstructed.cards
    ):
        print(
            f"  {obligation.obligation_id:<28} {obligation.kind.value:<28} "
            f"mandatory={obligation.mandatory} {obligation.description}"
        )
    print()
    print("ITERATIVE BOUNDS")
    for bound, result in frozen.bounds:
        print(
            f"  bound={bound:>2} status={result.status.value:<24} "
            f"added={result.corrected_added_cost!s:<3} total="
            f"{47 + result.corrected_added_cost if result.corrected_added_cost is not None else '-':<3} "
            f"nodes={result.nodes_expanded:<6} time={result.elapsed_seconds:.3f}s "
            f"MUST={len(result.must_sources_before)}->{len(result.must_sources_after)} "
            f"obligations={len(result.obligations_satisfied)}/{len(result.obligations)} "
            f"foundations={result.foundation_count_before}->{result.foundation_count_after} "
            f"bands_after={[band.label for band in result.bands_after]}"
        )
        print(f"    stop={result.stop_reason}")
    print()
    print("BEST COMPLETE ROUTE FROM TRUE OPENING")
    continuation_start = len(reconstructed.actions)
    for index, action in enumerate(frozen.full_actions, 1):
        role = (
            "reconstructed-prefix"
            if index <= continuation_start
            else best.action_roles[index - continuation_start - 1]
        )
        print(f"  {index:>2}. {format_action(action):<18} [{role}]")
    print(
        f"continuation_added={best.corrected_added_cost} "
        f"total={frozen.total_cost} replay={frozen.full_replay_verified}"
    )
    print()
    print("FOUNDATION AND FINAL TABLEAU VERIFICATION")
    print(
        f"status={best.status.value} foundations={best.foundation_count_before}->"
        f"{best.foundation_count_after} added_suits={best.foundation_suits_added} "
        f"deals_added={best.deals_applied} {_state_line(best.resulting_state)}"
    )
    print(best.resulting_state.render(reveal=True))
    print(
        f"audit: legal_moves={frozen.audit_after.legal_move_count} "
        f"fully_open={frozen.audit_after.fully_open_columns} "
        f"workspace_create={frozen.audit_after.cheapest_workspace_cost} "
        f"longest_run={frozen.audit_after.longest_same_suit_run} "
        f"run_mass={frozen.audit_after.total_same_suit_run_mass}"
    )
    print()
    print("HARD GATE")
    print(f"VERDICT: {frozen.verdict}")
    if frozen.verdict == "FAIL":
        print(
            "blockers: J and 9 remain buried in one source project; 3 remains "
            "buried in a second project; both require the same one-reveal "
            "helper column, no current bands join directly, and the bounded "
            "beam did not expose any blocker."
        )
        diamonds = reconstructed.cost23_portfolio.campaign_for("d", 1)
        print("OPTIONAL FAILURE-ONLY D#1 CONTEXT (no search)")
        print(
            f"  mode={derive_transition_mode(reconstructed.cost23_state, diamonds).value} "
            f"target=D{diamonds.target_removal_epoch} "
            f"MUST={len(diamonds.tableau_critical_cards)} "
            f"stock={len(diamonds.future_stock_supplied_cards)}; Deal3 supplies "
            f"{tuple(str(source.card) for source in diamonds.future_stock_supplied_cards if source.stock_epoch == 3)}"
        )


def canonical_comparison(frozen: FrozenContinuation) -> None:
    """First canonical access, after the prospective result is frozen."""
    print()
    print("PROSPECTIVE RESULT FROZEN — canonical trace may now be loaded.")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = frozen.reconstructed.opening.clone()
    cost = 0
    events = []
    comparable = None
    second = None
    for command, action in enumerate(actions, 1):
        before = len(state.foundations)
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            for sequence in state.foundations[before:]:
                events.append(sequence[0].suit)
            if comparable is None:
                comparable = (command, cost, state.clone())
            if len(state.foundations) >= 2 and second is None:
                second = (command, cost, state.clone())
    print(f"canonical_foundation_order={tuple(events)}")
    if comparable is not None:
        command, milestone_cost, milestone = comparable
        print(
            f"same-foundation-count milestone: command={command} cost={milestone_cost} "
            f"{_state_line(milestone)} run_mass="
            f"{sum(band.length for suit in 'cdhs' for band in locate_campaign_bands(milestone, suit))}"
        )
    if second is not None:
        command, milestone_cost, milestone = second
        print(
            f"canonical_second_foundation: command={command} cost={milestone_cost} "
            f"order={tuple(events[:2])} {_state_line(milestone)}"
        )
    prospective_state = (
        frozen.best.resulting_state
        if frozen.best is not None
        else frozen.reconstructed.state
    )
    print(
        f"prospective_final: cost={frozen.total_cost} "
        f"{_state_line(prospective_state)} run_mass="
        f"{frozen.audit_after.total_same_suit_run_mass}"
    )
    print("No canonical agreement or complete-solution improvement is claimed.")


def main() -> int:
    started = time.perf_counter()
    cards = tuple(load_deal(DEAL_PATH))
    frozen = freeze_prospective(cards)
    print_prospective(frozen)
    canonical_comparison(frozen)
    print(f"total_runtime={time.perf_counter() - started:.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
