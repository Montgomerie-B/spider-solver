#!/usr/bin/env python3
"""Economic-project report from the legal cost-23 machine checkpoint.

Benchmark coordinates and the verified incumbent belong only in this
diagnostic.  Prospective economics are frozen before the canonical solution is
opened.  The checkpoint is never advanced to Deal 3.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.diagnostics.legal_deal2_campaign_restart_report import (
    CANONICAL_PATH,
    DEAL_PATH,
    PREFERRED_B_OPENING,
    FrozenArm,
    SearchResources,
    freeze_arm,
)
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProject,
    EconomicProjectKind,
    EvidenceLevel,
    analyze_economic_projects,
    assess_rework_investment,
    bounded,
    build_economic_frontier,
    economic_project_dominates,
    empty_project_benefit,
    empty_project_cost,
    empty_project_debt,
    hard,
    heuristic,
    make_economic_project,
)
from spider.planner.foundation_campaign import format_campaign_portfolio
from spider.planner.incumbent_budget import IncumbentBudget, build_incumbent_budget
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_SOURCE_BASE = "0d1af35f08029b6ebdb1820ccb68ffae6c0811ab"
REPLAY_VERIFIED_RESEARCH_INCUMBENT = 172
EXTERNAL_CONTEXT_ONLY_SCORE = 119


@dataclass(frozen=True)
class Cost23Checkpoint:
    arm: FrozenArm
    state: SpiderState
    cards: Tuple[Card, ...]
    replay_state: SpiderState
    action_count: int
    deal_count: int
    face_down_count: int
    foundation_suits: Tuple[str, ...]
    no_deal3: bool
    independently_verified: bool


@dataclass(frozen=True)
class FrozenEconomicAnalysis:
    checkpoint: Cost23Checkpoint
    analysis: EconomicAnalysisResult
    research_budget: IncumbentBudget
    production_budget: IncumbentBudget
    production_after_incumbent: IncumbentBudget
    prospective_project_order: Tuple[str, ...]
    canonical_loaded: bool = False
    prospective_frozen: bool = True


@dataclass(frozen=True)
class CanonicalPostFreezeObservation:
    corrected_cost: int
    action_count: int
    solved: bool
    stable_joins: int
    provisional_joins: int
    mixed_parks: int
    workspace_parks: int
    projected_lifecycle_debt: float
    loaded_after_freeze: bool


def _foundation_suits(state: SpiderState) -> Tuple[str, ...]:
    return tuple(sequence[0].suit for sequence in state.foundations if sequence)


def reconstruct_cost23_checkpoint(
    *, resources: SearchResources = SearchResources()
) -> Cost23Checkpoint:
    """Reconstruct the legal machine checkpoint through public realizer APIs."""
    cards = tuple(load_deal(DEAL_PATH))
    arm = freeze_arm(
        "economic cost-23 checkpoint",
        PREFERRED_B_OPENING,
        cards,
        resources=resources,
    )
    state = arm.best.end_state.clone()
    replay = SpiderState.from_cards(list(cards))
    replay_cost = replay_actions(replay, list(arm.full_actions))
    action_count = len(arm.full_actions)
    deals = sum(action == ("deal",) for action in arm.full_actions)
    face_down = sum(len(column.face_down) for column in state.columns)
    suits = _foundation_suits(state)
    independently_verified = bool(
        replay_cost == arm.total_cost == 23
        and action_count == 23
        and deals == 2
        and len(state.stock) == 30
        and len(state.foundations) == 1
        and suits == ("s",)
        and face_down == 32
        and arm.independent_replay_verified
        and states_structurally_equal(state, replay)
    )
    if not independently_verified:
        raise AssertionError("legal cost-23 checkpoint reconstruction regressed")
    return Cost23Checkpoint(
        arm=arm,
        state=state,
        cards=cards,
        replay_state=replay,
        action_count=action_count,
        deal_count=deals,
        face_down_count=face_down,
        foundation_suits=suits,
        no_deal3=deals == 2 and len(state.stock) == 30,
        independently_verified=independently_verified,
    )


def freeze_prospective_economics(
    *, resources: SearchResources = SearchResources()
) -> FrozenEconomicAnalysis:
    """Freeze the entire economic portfolio without opening canonical moves."""
    checkpoint = reconstruct_cost23_checkpoint(resources=resources)
    before = checkpoint.state.clone()
    analysis = analyze_economic_projects(
        checkpoint.state,
        cards=checkpoint.cards,
    )
    if not states_structurally_equal(before, checkpoint.state):
        raise AssertionError("prospective economic analysis advanced the checkpoint")
    research = build_incumbent_budget(
        checkpoint.state,
        spent_cost=23,
        incumbent_cost=REPLAY_VERIFIED_RESEARCH_INCUMBENT,
        heuristic_remaining_work=analysis.estimated_remaining_work,
    )
    production = build_incumbent_budget(
        checkpoint.state,
        spent_cost=23,
        incumbent_cost=None,
        heuristic_remaining_work=analysis.estimated_remaining_work,
    )
    installed = production.install_incumbent(REPLAY_VERIFIED_RESEARCH_INCUMBENT)
    return FrozenEconomicAnalysis(
        checkpoint=checkpoint,
        analysis=analysis,
        research_budget=research,
        production_budget=production,
        production_after_incumbent=installed,
        prospective_project_order=tuple(
            project.project_id for project in analysis.frontier.ordered_projects
        ),
    )


def inspect_canonical_after_freeze(
    frozen: FrozenEconomicAnalysis,
) -> CanonicalPostFreezeObservation:
    """Open and replay canonical actions only after prospective conclusions freeze."""
    if not frozen.prospective_frozen or frozen.canonical_loaded:
        raise AssertionError("canonical inspection requires a clean prospective freeze")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = SpiderState.from_cards(list(frozen.checkpoint.cards))
    stable = provisional = mixed = workspace = 0
    debt = 0.0
    corrected = 0
    for action in actions:
        if action == ("deal",):
            corrected += state.deal()
            continue
        src, dst, k = action
        assessment = assess_tableau_move(state, (src, dst, k))
        if assessment.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN:
            stable += 1
        elif assessment.placement_class == PlacementClass.PROVISIONAL_SAME_SUIT_JOIN:
            provisional += 1
        elif assessment.placement_class == PlacementClass.MIXED_SUIT_PARK:
            mixed += 1
        else:
            workspace += 1
        debt += assessment.estimated_rehandling_cost
        corrected += state.move(src, dst, k)
    if corrected != REPLAY_VERIFIED_RESEARCH_INCUMBENT or not state.is_solved():
        raise AssertionError("canonical incumbent failed independent replay")
    return CanonicalPostFreezeObservation(
        corrected_cost=corrected,
        action_count=len(actions),
        solved=state.is_solved(),
        stable_joins=stable,
        provisional_joins=provisional,
        mixed_parks=mixed,
        workspace_parks=workspace,
        projected_lifecycle_debt=debt,
        loaded_after_freeze=True,
    )


def synthetic_rework_pot_of_gold_example() -> Tuple[EconomicProject, EconomicProject]:
    """Small generic fixture where bounded ugly work buys a larger return."""
    clean_benefit = empty_project_benefit()
    clean_benefit = type(clean_benefit)(
        **{
            **clean_benefit.__dict__,
            "same_suit_run_mass": hard(2, "small clean local band improvement"),
        }
    )
    clean_cost = empty_project_cost()
    clean_cost = type(clean_cost)(
        **{
            **clean_cost.__dict__,
            "immediate_paid_cost": hard(1, "one legal paid move"),
        }
    )
    clean = make_economic_project(
        project_id="synthetic-clean-local-work",
        kind=EconomicProjectKind.DEFERRED_PROJECT,
        description="clean but low-return local work",
        earliest_useful_epoch=0,
        cost=clean_cost,
        benefit=clean_benefit,
        confidence="HIGH",
    )

    investment = assess_rework_investment(
        investment_cost=bounded(4, "bounded four-action park/exit route"),
        expected_structural_return=bounded(
            16, "bounded route clears a mandatory chain and creates workspace"
        ),
        expected_move_saving=bounded(3, "three later separation actions avoided"),
        evidence="fixture replay bounds the exit and exposes the campaign-critical source",
        confidence="HIGH",
        exit_route_bounded=True,
    )
    rework_benefit = empty_project_benefit()
    rework_benefit = type(rework_benefit)(
        **{
            **rework_benefit.__dict__,
            "campaign_must_dependencies": bounded(10, "mandatory dependency removed"),
            "critical_reveal_advancement": bounded(6, "critical source exposed"),
            "workspace_created": bounded(3, "column becomes reusable workspace"),
        }
    )
    rework_cost = empty_project_cost()
    rework_cost = type(rework_cost)(
        **{
            **rework_cost.__dict__,
            "immediate_paid_cost": hard(1, "first legal park"),
            "bounded_tactical_cost": bounded(3, "remaining bounded route cost"),
            "expected_future_rehandling": heuristic(1, "conservative lifecycle estimate"),
        }
    )
    rework_debt = empty_project_debt()
    rework_debt = type(rework_debt)(
        **{
            **rework_debt.__dict__,
            "rework_actions_introduced": bounded(4, "four-action temporary route"),
            "mixed_boundaries_created": hard(1, "one temporary mixed boundary"),
            "projected_rehandling_cost": bounded(3, "bounded park exit"),
            "future_exit_route": "rejoin the parked band after the mandatory source clears",
            "exit_route_bounded": True,
        }
    )
    rework = make_economic_project(
        project_id="synthetic-bounded-pot-of-gold",
        kind=EconomicProjectKind.TEMPORARY_REWORK,
        description="bounded rework that unlocks a mandatory source and workspace",
        earliest_useful_epoch=0,
        cost=rework_cost,
        benefit=rework_benefit,
        debt=rework_debt,
        rework_investment=investment,
        confidence="HIGH",
        rationale=("temporary ugliness is paid back by a larger bounded return",),
    )
    return clean, rework


def _print_project(project: EconomicProject, *, details: bool = False) -> None:
    assessment = project.assessment
    print(
        f"  {assessment.frontier_tier.value} {project.project_id:<24} "
        f"net={assessment.net_economic_value:>6.1f} epoch={project.earliest_useful_epoch} "
        f"kind={project.kind.value} confidence={assessment.confidence}"
    )
    if not details:
        return
    print(f"    {project.description}")
    print(
        f"    cost hard={project.cost.hard_observed_total:.1f} "
        f"ordering={project.cost.ordering_total:.1f}; "
        f"benefit={project.benefit.structural_total:.1f}; debt={project.debt.ordering_total:.1f}"
    )
    for name, amount in project.cost.components:
        if amount.value:
            print(f"      cost.{name}={amount.value:g} [{amount.evidence.value}] {amount.rationale}")
    for name, amount in project.benefit.components:
        if amount.value:
            print(f"      benefit.{name}={amount.value:g} [{amount.evidence.value}] {amount.rationale}")
    print(f"    workspace={project.workspace_effect}")
    print(f"    stock={project.stock_interaction}")
    print(f"    campaigns={project.campaign_dependencies or ('none',)}")
    print(
        f"    exit={project.debt.future_exit_route}; bounded={project.debt.exit_route_bounded}; "
        f"proof-prune={project.assessment.proof_pruning_allowed}"
    )


def main() -> int:
    print("1. LEGAL BASELINE CONFIRMATION")
    print(f"  requested source base={AUTHORITATIVE_SOURCE_BASE}")
    print("  corrected same-suit move legality and lifecycle debt remain authoritative")

    frozen = freeze_prospective_economics()
    checkpoint = frozen.checkpoint
    analysis = frozen.analysis
    facts = analysis.facts

    print("\n2. RECONSTRUCTED COST-23 CHECKPOINT")
    print(
        f"  cost={checkpoint.arm.total_cost} actions={checkpoint.action_count} "
        f"deals={checkpoint.deal_count} stock={len(checkpoint.state.stock)} "
        f"foundations={checkpoint.foundation_suits} fd={checkpoint.face_down_count}"
    )
    print(
        f"  independent replay={checkpoint.independently_verified}; "
        f"structural equality={states_structurally_equal(checkpoint.state, checkpoint.replay_state)}; "
        f"no Deal 3={checkpoint.no_deal3}"
    )

    print("\n3. HARD STATE FACTS")
    print(
        f"  epoch={facts.current_epoch} stock={facts.stock_remaining} deals-left={facts.remaining_deals} "
        f"fd={facts.face_down_cards} foundations={facts.foundations}"
    )
    print(f"  exact next row={' '.join(map(str, facts.exact_next_stock_row))}")
    print(f"  empty={facts.empty_columns}; fully-open={facts.fully_open_columns}")
    print(f"  same-suit joins={len(facts.same_suit_joins)}; mixed boundaries={len(facts.mixed_suit_boundaries)}")

    print("\n4. ADMISSIBLE INCUMBENT BUDGET")
    b = frozen.research_budget
    print(
        f"  g={b.spent_cost} h_deals={b.h_deals} h_reveal_paid={b.h_reveal_paid} "
        f"h={b.admissible_remaining_lower_bound} hard-min={b.hard_min_total}"
    )
    print(
        f"  incumbent={b.incumbent_cost} max-improving={b.maximum_improving_total} "
        f"hard-headroom={b.hard_headroom} proof-prunable={b.proof_prunable}"
    )
    print(
        f"  withdrawn fd+deals={b.lower_bound.h_naive_face_down_plus_deals} "
        "is diagnostic-only and absent from pruning"
    )

    print("\n5. HEURISTIC ECONOMIC BUDGET")
    print(
        f"  estimated remaining work={b.heuristic_remaining_work:.1f}; "
        f"estimated economic slack={b.heuristic_economic_slack:.1f}"
    )
    print("  HEURISTIC_ESTIMATE: neither figure can change proof_prunable")

    print("\n6. CURRENT CAMPAIGN PORTFOLIO")
    print(format_campaign_portfolio(analysis.campaign_portfolio))

    print("\n7. WHOLE-TABLEAU REVEAL VALUE")
    for value in analysis.reveal_values:
        print(
            f"  {value.card}@c{value.column + 1}/d{value.reveal_depth} "
            f"{value.classification.value:<28} info={value.information_gain:.0f} "
            f"structural={value.structural_value:>5.1f} stock={value.stock_copy_epochs} "
            f"campaigns={value.campaign_dependencies}"
        )

    print("\n8. CURRENT REHANDLING/LIFECYCLE LIABILITIES")
    for liability in analysis.lifecycle_liabilities:
        print(f"  {liability}")

    print("\n9. GENERATED ECONOMIC PROJECTS")
    for project in analysis.projects:
        _print_project(project)

    print("\n10. ECONOMIC FRONTIER")
    for tier, projects in analysis.frontier.tiers:
        print(f"  TIER {tier.value} {tier.name}: {len(projects)}")
        for project in projects:
            _print_project(project)

    print("\n11. TOP PROJECT BREAKDOWNS")
    for project in analysis.frontier.ordered_projects[:8]:
        _print_project(project, details=True)

    print("\n12. DOMINATED / ECONOMICALLY UNEXPLAINED")
    for relation in analysis.frontier.dominance[:12]:
        print(
            f"  {relation.dominant_project_id} > {relation.dominated_project_id}: "
            f"{'; '.join(relation.reasons)}; proof-prune={relation.proof_pruning_allowed}"
        )
    print(f"  retained Tier-4 projects={analysis.frontier.retained_unexplained}")

    print("\n13. RESEARCH MODE")
    print(f"  {b.proof_reason}; target={b.improvement_target}; external {EXTERNAL_CONTEXT_ONLY_SCORE}=context only")

    print("\n14. PRODUCTION MODE")
    p = frozen.production_budget
    installed = frozen.production_after_incumbent
    print(
        f"  no incumbent: target={p.improvement_target} headroom={p.hard_headroom} "
        f"can-improve={p.can_improve_incumbent} proof-prunable={p.proof_prunable}"
    )
    print(
        f"  after verified incumbent: target={installed.improvement_target} "
        f"headroom={installed.hard_headroom} proof-prunable={installed.proof_prunable}"
    )

    print("\n15. BOUNDED REWORK WITH A POT OF GOLD")
    clean, rework = synthetic_rework_pot_of_gold_example()
    for project in build_economic_frontier((clean, rework)).ordered_projects:
        _print_project(project, details=True)

    print("\n16. FROZEN PROSPECTIVE CONCLUSION")
    print(
        f"  frozen={frozen.prospective_frozen}; canonical-loaded={frozen.canonical_loaded}; "
        f"projects={len(frozen.prospective_project_order)}; checkpoint stock={len(checkpoint.state.stock)}"
    )
    print("  no Deal 3, second foundation, controller integration, whole-game search, or archive write")

    canonical = inspect_canonical_after_freeze(frozen)
    print("\n17. CANONICAL POST-FREEZE VALIDATION")
    print(
        f"  loaded-after-freeze={canonical.loaded_after_freeze}; replay cost={canonical.corrected_cost}; "
        f"actions={canonical.action_count}; solved={canonical.solved}"
    )
    print(
        f"  lifecycle observations stable={canonical.stable_joins} provisional={canonical.provisional_joins} "
        f"mixed-parks={canonical.mixed_parks} workspace-parks={canonical.workspace_parks} "
        f"heuristic debt={canonical.projected_lifecycle_debt:.1f}"
    )
    print("  canonical actions were validation evidence only and never strategy input")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
