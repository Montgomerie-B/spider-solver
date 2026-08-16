#!/usr/bin/env python3
"""Prospective A/B report for shared-helper campaign source guidance."""

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
from spider.planner.campaign_source_projects import (
    CampaignSourceProjectPlan,
    CampaignSourceRealizationResult,
    CampaignSourceRealizationStatus,
    build_campaign_source_project_plan,
    realize_campaign_source_projects,
)
from spider.planner.diagnostics.residual_campaign_continuation_report import (
    ReconstructedCost47,
    reconstruct_cost47,
    same_campaign_remains_primary,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionResult,
    CampaignTransitionStatus,
    ResidualStateAudit,
    audit_residual_state,
    realize_residual_campaign_transition,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.state_identity import states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
BOUNDS = (6, 10, 15, 20, 28)
MAX_NODES = 50_000
TIME_LIMIT_S = 12.0


@dataclass(frozen=True)
class ABBoundResult:
    bound: int
    baseline: CampaignTransitionResult
    guided: CampaignSourceRealizationResult


@dataclass(frozen=True)
class FrozenSourceGuidance:
    reconstructed: ReconstructedCost47
    plan: CampaignSourceProjectPlan
    same_primary: bool
    bounds: Tuple[ABBoundResult, ...]
    best: CampaignSourceRealizationResult | None
    total_cost: int
    full_actions: Tuple[Action, ...]
    full_replay_verified: bool
    audit_before: ResidualStateAudit
    audit_after: ResidualStateAudit
    verdict: str
    blocker_class: str
    prospective_runtime: float


def _source_reduction(result: CampaignSourceRealizationResult) -> int:
    if not result.progress:
        return 0
    return sum(reduction for _column, reduction in result.progress[-1].source_face_down_reductions)


def _band_joins(before: Sequence[object], after: Sequence[object]) -> int:
    """Report the conservative net reduction in campaign-band count."""
    return max(0, len(before) - len(after))


def _best_guided(
    bounds: Sequence[ABBoundResult],
) -> CampaignSourceRealizationResult | None:
    if not bounds:
        return None
    removed = [
        item.guided
        for item in bounds
        if item.guided.status == CampaignSourceRealizationStatus.FOUNDATION_REMOVED
        and item.guided.independent_replay_verified
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
    return max(
        (item.guided for item in bounds),
        key=lambda result: (
            len(result.helper_tasks_after),
            _source_reduction(result),
            -len(result.must_sources_after),
            -(result.corrected_added_cost or 0),
            -result.nodes_expanded,
        ),
    )


def _classify_blocker(result: CampaignSourceRealizationResult | None) -> str:
    if result is None:
        return "same_primary_gate"
    if result.status == CampaignSourceRealizationStatus.FOUNDATION_REMOVED:
        return "none"
    if not result.helper_tasks_after:
        return "helper_completion"
    if result.must_sources_after:
        return "source_exposure"
    if result.removal_result is None:
        return "band_joining"
    return "final_removal_execution"


def freeze_prospective(cards: Tuple[Card, ...]) -> FrozenSourceGuidance:
    """Run the prospective experiment before any canonical trace is loaded."""
    started = time.perf_counter()
    reconstructed = reconstruct_cost47(cards)
    same_primary = same_campaign_remains_primary(
        reconstructed.advanced_identity, reconstructed.portfolio
    )
    plan = build_campaign_source_project_plan(
        reconstructed.state, reconstructed.campaign
    )
    audit_before = audit_residual_state(
        reconstructed.state, reconstructed.campaign, cards
    )
    if not same_primary:
        return FrozenSourceGuidance(
            reconstructed,
            plan,
            False,
            (),
            None,
            reconstructed.total_cost,
            reconstructed.actions,
            reconstructed.replay_verified,
            audit_before,
            audit_before,
            "PARTIAL",
            "same_primary_gate",
            time.perf_counter() - started,
        )

    results = []
    for bound in BOUNDS:
        baseline = realize_residual_campaign_transition(
            reconstructed.state,
            reconstructed.campaign,
            cards,
            max_added_cost=bound,
            max_nodes=MAX_NODES,
            time_limit_s=TIME_LIMIT_S,
            beam_width=512,
        )
        guided = realize_campaign_source_projects(
            reconstructed.state,
            reconstructed.campaign,
            cards,
            max_added_cost=bound,
            max_nodes=MAX_NODES,
            time_limit_s=TIME_LIMIT_S,
            branch_cap=24,
            removal_beam_width=512,
        )
        results.append(ABBoundResult(bound, baseline, guided))

    frozen_bounds = tuple(results)
    best = _best_guided(frozen_bounds)
    assert best is not None
    full_actions = reconstructed.actions + best.actions
    replayed = reconstructed.opening.clone()
    total_cost = replay_actions(replayed, list(full_actions))
    replay_ok = bool(
        best.corrected_added_cost is not None
        and total_cost == reconstructed.total_cost + best.corrected_added_cost
        and states_structurally_equal(replayed, best.resulting_state)
        and full_actions.count(("deal",)) == 2
        and len(best.resulting_state.stock) == 30
    )
    if best.status == CampaignSourceRealizationStatus.FOUNDATION_REMOVED and replay_ok:
        if total_cost <= 62:
            verdict = "EXCEPTIONAL"
        elif total_cost <= 72:
            verdict = "STRONG PASS"
        else:
            verdict = "PASS"
    else:
        verdict = "FAIL"
    campaign_after = best.campaign_after or reconstructed.campaign
    audit_after = audit_residual_state(best.resulting_state, campaign_after, cards)
    return FrozenSourceGuidance(
        reconstructed,
        plan,
        True,
        frozen_bounds,
        best,
        total_cost,
        full_actions,
        replay_ok,
        audit_before,
        audit_after,
        verdict,
        _classify_blocker(best),
        time.perf_counter() - started,
    )


def _state_line(state: SpiderState) -> str:
    return (
        f"fd={sum(len(column.face_down) for column in state.columns)} "
        f"stock={len(state.stock)} foundations={len(state.foundations)} "
        f"epoch={current_stock_epoch(state, 5)} "
        f"empties={tuple(i + 1 for i, column in enumerate(state.columns) if column.is_empty())}"
    )


def _transition_line(result: CampaignTransitionResult) -> str:
    return (
        f"{result.status.value} added={result.corrected_added_cost} "
        f"MUST={len(result.must_sources_before)}->{len(result.must_sources_after)} "
        f"band_joins={_band_joins(result.bands_before, result.bands_after)} "
        f"obligations={len(result.obligations_satisfied)}/{len(result.obligations)} "
        f"foundations={result.foundation_count_before}->{result.foundation_count_after} "
        f"nodes={result.nodes_expanded} time={result.elapsed_seconds:.3f}s"
    )


def _guided_line(result: CampaignSourceRealizationResult) -> str:
    removal_satisfied = (
        len(result.removal_result.obligations_satisfied)
        if result.removal_result is not None
        else 0
    )
    removal_total = (
        len(result.removal_result.obligations)
        if result.removal_result is not None
        else 0
    )
    return (
        f"{result.status.value} added={result.corrected_added_cost} "
        f"helpers={len(result.helper_tasks_before)}->{len(result.helper_tasks_after)} "
        f"source_reveals={_source_reduction(result)} "
        f"MUST={len(result.must_sources_before)}->{len(result.must_sources_after)} "
        f"band_joins={_band_joins(result.bands_before, result.bands_after)} "
        f"removal_obligations={removal_satisfied}/{removal_total} "
        f"foundations={result.foundation_count_before}->{result.foundation_count_after} "
        f"nodes={result.nodes_expanded} time={result.elapsed_seconds:.3f}s"
    )


def print_prospective(frozen: FrozenSourceGuidance) -> None:
    reconstructed = frozen.reconstructed
    campaign = reconstructed.campaign
    print("SHARED-HELPER SOURCE-PROJECT REALISATION")
    print("Prospective result only. No Deal 3. Canonical trace not yet loaded.")
    print()
    print("PUBLIC-API COST-47 RECONSTRUCTION")
    print(
        f"cost={reconstructed.total_cost} actions={len(reconstructed.actions)} "
        f"deals={reconstructed.actions.count(('deal',))} "
        f"replay={reconstructed.replay_verified} {_state_line(reconstructed.state)}"
    )
    print(
        f"fixed_campaign={campaign.label} target=D{campaign.target_removal_epoch} "
        f"same_primary={frozen.same_primary} "
        f"MUST={tuple(str(source.card) for source in campaign.tableau_critical_cards)}"
    )
    print()
    print("SOURCE-PROJECT MODEL")
    for helper in frozen.plan.helper_tasks:
        print(
            f"  {helper.task_id}: column={helper.column + 1} hops={helper.required_hops} "
            f"card_reduction={helper.required_card_reduction} "
            f"face_down_reduction={helper.required_face_down_reduction} "
            f"shared={helper.shared} dependents={helper.dependent_project_ids}"
        )
    for project in frozen.plan.projects:
        print(
            f"  {project.project_id}: column={project.source_column + 1} "
            f"ranks={project.required_ranks} reveals={project.required_reveals} "
            f"target_fd<={project.target_max_face_down} helpers={project.helper_task_ids} "
            f"join_distance={project.join_distance}"
        )
        print(f"    interchangeable={project.interchangeable_sources}")
    print(f"  edges={frozen.plan.shared_helper_edges}")
    print(f"  priority={frozen.plan.priority_order}")
    print(f"  protected_bands={frozen.plan.protected_bands}")
    if not frozen.same_primary:
        print()
        print("HARD GATE")
        print("VERDICT: PARTIAL — reanalysis changed the fixed primary.")
        return

    print()
    print(
        f"A/B ITERATIVE BOUNDS (equal ceilings: nodes={MAX_NODES}, "
        f"time={TIME_LIMIT_S:.0f}s per arm)"
    )
    print("  existing: transition beam=512")
    print("  guided: committed branch cap=24, then existing removal beam=512")
    for item in frozen.bounds:
        print(f"  bound={item.bound:>2} existing  {_transition_line(item.baseline)}")
        print(f"           guided    {_guided_line(item.guided)}")
        print(f"           existing_stop={item.baseline.stop_reason}")
        print(f"           guided_stop={item.guided.stop_reason}")

    best = frozen.best
    assert best is not None
    print()
    print("BEST GUIDED PROJECT PROGRESSION")
    for snapshot in best.progress:
        print(
            f"  {snapshot.phase:<16} committed={snapshot.committed_target} "
            f"actions={snapshot.action_count} cost={snapshot.corrected_added_cost} "
            f"helpers={snapshot.helper_tasks_satisfied} "
            f"usable_ranks={snapshot.source_ranks_usable} "
            f"source_fd_reductions={snapshot.source_face_down_reductions} "
            f"MUST={len(snapshot.must_source_keys)} bands="
            f"{tuple(band.label for band in snapshot.bands)}"
        )
        print(f"    {snapshot.note}")
    print("  best_partial_actions:")
    for index, (action, role) in enumerate(zip(best.actions, best.action_roles), 1):
        print(f"    {index}. {format_action(action):<18} [{role}]")
    print(
        f"  partial_added={best.corrected_added_cost} total={frozen.total_cost} "
        f"full_prefix_replay={frozen.full_replay_verified} "
        f"deals_added={best.deals_applied}"
    )

    print()
    if best.status == CampaignSourceRealizationStatus.FOUNDATION_REMOVED:
        print("COMPLETE BEST ROUTE FROM TRUE OPENING")
        continuation_start = len(reconstructed.actions)
        for index, action in enumerate(frozen.full_actions, 1):
            role = (
                "reconstructed-prefix"
                if index <= continuation_start
                else best.action_roles[index - continuation_start - 1]
            )
            print(f"  {index:>2}. {format_action(action):<18} [{role}]")
    else:
        print("COMPLETE BEST ROUTE FROM TRUE OPENING: none; no actual second removal.")

    print()
    print("FOUNDATION / TABLEAU VERIFICATION")
    print(
        f"status={best.status.value} foundations={best.foundation_count_before}->"
        f"{best.foundation_count_after} added_suits={best.foundation_suits_added} "
        f"replay={best.independent_replay_verified} {_state_line(best.resulting_state)}"
    )
    print(
        f"bands_before={tuple(band.label for band in best.bands_before)} "
        f"bands_after={tuple(band.label for band in best.bands_after)} "
        f"net_joins={_band_joins(best.bands_before, best.bands_after)}"
    )
    print(best.resulting_state.render(reveal=True))
    print(
        f"audit_before: legal={frozen.audit_before.legal_move_count} "
        f"fully_open={frozen.audit_before.fully_open_columns} "
        f"longest_run={frozen.audit_before.longest_same_suit_run} "
        f"run_mass={frozen.audit_before.total_same_suit_run_mass}"
    )
    print(
        f"audit_after: legal={frozen.audit_after.legal_move_count} "
        f"fully_open={frozen.audit_after.fully_open_columns} "
        f"longest_run={frozen.audit_after.longest_same_suit_run} "
        f"run_mass={frozen.audit_after.total_same_suit_run_mass}"
    )
    print()
    print("HARD GATE")
    print(f"VERDICT: {frozen.verdict}")
    print(f"blocker_class={frozen.blocker_class}")
    if frozen.verdict == "FAIL":
        print(
            "The shared helper is realized once and the first committed source "
            "prefix advances by one reveal, but the remaining source cards are "
            "not exposed at any tested bound. A resource-limited miss is not an "
            "impossibility proof."
        )
        diamonds = reconstructed.cost23_portfolio.campaign_for("d", 1)
        print(
            "recommended_next_action=run an equal-resource H#1-vs-D#1 "
            "campaign comparison from the verified cost-23 state; "
            f"D#1 target=D{diamonds.target_removal_epoch} "
            f"MUST={len(diamonds.tableau_critical_cards)}"
        )
    print(f"prospective_runtime={frozen.prospective_runtime:.3f}s")


def canonical_comparison(frozen: FrozenSourceGuidance) -> None:
    """First canonical access, after the prospective outcome is frozen."""
    print()
    print("PROSPECTIVE RESULT FROZEN — canonical trace may now be loaded.")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = frozen.reconstructed.opening.clone()
    cost = 0
    order = []
    second = None
    for command, action in enumerate(actions, 1):
        before = len(state.foundations)
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            order.extend(sequence[0].suit for sequence in state.foundations[before:])
            if len(state.foundations) >= 2 and second is None:
                second = (command, cost, state.clone())
    print(f"canonical_foundation_order={tuple(order)}")
    if second is not None:
        command, second_cost, second_state = second
        audit = audit_residual_state(
            second_state,
            frozen.reconstructed.cost23_portfolio.primary,
            frozen.reconstructed.cards,
        )
        print(
            f"canonical_two-foundation milestone: command={command} cost={second_cost} "
            f"order={tuple(order[:2])} {_state_line(second_state)} "
            f"longest_run={audit.longest_same_suit_run} "
            f"run_mass={audit.total_same_suit_run_mass}"
        )
    best_state = (
        frozen.best.resulting_state
        if frozen.best is not None
        else frozen.reconstructed.state
    )
    print(
        f"prospective_final: cost={frozen.total_cost} {_state_line(best_state)} "
        f"longest_run={frozen.audit_after.longest_same_suit_run} "
        f"run_mass={frozen.audit_after.total_same_suit_run_mass}"
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
