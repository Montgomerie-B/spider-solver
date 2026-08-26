#!/usr/bin/env python3
"""Prospective report for strategic stock-deal timing.

All three benchmark decisions are completed and frozen before this module's
separate canonical-inspection function is allowed to open future route data.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.planner.deal_timing import (
    DealPreparationCandidate,
    DealTimingAssessment,
    DealTimingConfig,
    DealTimingDecisionKind,
    assess_deal_timing,
    build_preparation_candidate,
    deal_as_economic_project,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    CANONICAL_PATH,
    REPLAY_VERIFIED_RESEARCH_INCUMBENT,
    reconstruct_cost23_checkpoint,
)
from spider.planner.diagnostics.foundation_campaign_deal2_report import (
    DEAL_PATH,
    SIX_MOVE_FIXTURE,
    _build_verified_deal1,
)
from spider.planner.space_lifecycle import empty_columns, fully_open_nonempty
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    PriorityComponents,
    StrategicObjective,
)
from spider.rules import MW_RULES, MobilityWareRules
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "b7f09d60ec1e972fa29dbb72846ac85a31e9dbe6"
MOBILITYWARE_RULE_EVIDENCE = (
    "MobilityWare documents the normal all-columns-populated restriction and "
    "a separate Unrestricted Deal setting; the user confirmed Unrestricted "
    "Deal is enabled for this benchmark."
)


@dataclass(frozen=True)
class LegalCheckpoint:
    label: str
    state: SpiderState
    actions: Tuple[Action, ...]
    corrected_cost: int
    stock_deals: int
    independent_replay_verified: bool


@dataclass(frozen=True)
class ValuablePreparationDemonstration:
    state: SpiderState
    cards: Tuple[Card, ...]
    candidate: DealPreparationCandidate
    assessment: DealTimingAssessment


@dataclass(frozen=True)
class FrozenDealTimingExperiment:
    cards: Tuple[Card, ...]
    checkpoint_a: LegalCheckpoint
    checkpoint_b: LegalCheckpoint
    checkpoint_c: LegalCheckpoint
    assessment_a: DealTimingAssessment
    assessment_b: DealTimingAssessment
    assessment_c: DealTimingAssessment
    preparation_demonstration: ValuablePreparationDemonstration
    verdict: str
    verdict_reasons: Tuple[str, ...]
    prospective_decisions_frozen: bool
    canonical_loaded: bool = False


@dataclass(frozen=True)
class CanonicalTimingObservation:
    corrected_cost: int
    solved: bool
    tableau_actions_before_deals: Tuple[int, ...]
    corrected_costs_at_deals: Tuple[int, ...]
    loaded_after_prospective_freeze: bool


def _face_down(state: SpiderState) -> int:
    return sum(len(column.face_down) for column in state.columns)


def _checkpoint(
    label: str,
    cards: Tuple[Card, ...],
    actions: Tuple[Action, ...],
    corrected_cost: int,
) -> LegalCheckpoint:
    state = SpiderState.from_cards(list(cards))
    replayed = replay_actions(state, list(actions))
    return LegalCheckpoint(
        label=label,
        state=state,
        actions=actions,
        corrected_cost=corrected_cost,
        stock_deals=sum(action == ("deal",) for action in actions),
        independent_replay_verified=replayed == corrected_cost,
    )


def _diagnostic_config() -> DealTimingConfig:
    return DealTimingConfig(
        max_preparation_projects=2,
        max_preparation_cost=8,
        hard_preparation_cost_cap=12,
        max_h1_candidates=3,
        max_h2_candidates=1,
        tactical_max_cost=4,
        tactical_max_nodes=5_000,
        tactical_time_limit_s=2.0,
        downstream_max_cost=10,
        downstream_max_nodes=10_000,
        downstream_time_limit_s=3.0,
    )


def _two_decks() -> list[Card]:
    return [Card(suit, rank) for _copy in range(2) for suit in "shdc" for rank in range(1, 14)]


def _take(pool: list[Card], card: Card) -> Card:
    index = pool.index(card)
    return pool.pop(index)


def valuable_preparation_fixture() -> Tuple[SpiderState, Tuple[Card, ...]]:
    """Legal scale fixture where one preparation saves three bounded moves.

    Without preparation, the incoming 5s lands on 7s and the exact 7s-6s-5s
    objective needs a three-move repair.  Moving 6s onto 7s before the deal
    costs one and lets the exact incoming 5s complete the band immediately.
    """
    full = _two_decks()
    pool = list(full)
    tops_requested = (
        Card("s", 7),
        Card("s", 6),
        Card("c", 13),
        Card("d", 12),
        Card("h", 11),
        Card("c", 10),
        Card("d", 9),
        Card("h", 8),
        Card("c", 4),
        Card("d", 3),
    )
    incoming_requested = (
        Card("s", 5),
        Card("h", 5),
        Card("h", 6),
        Card("c", 2),
        Card("d", 2),
        Card("h", 2),
        Card("s", 2),
        Card("c", 1),
        Card("d", 1),
        Card("h", 1),
    )
    tops = [_take(pool, card) for card in tops_requested]
    incoming = [_take(pool, card) for card in incoming_requested]
    earlier_stock = [pool.pop() for _ in range(40)]
    face_down = list(pool)
    assert len(face_down) == 44
    columns = [Column([], [card]) for card in tops]
    for index, card in enumerate(face_down):
        columns[index % 10].face_down.append(card)
    # Engine flips from the end of face_down; exact identities do not affect
    # the receiver proof because the incoming row covers the reveal.
    return SpiderState(columns, earlier_stock + incoming, []), tuple(full)


def _band_objective() -> StrategicObjective:
    return StrategicObjective(
        kind=ObjectiveKind.CONSOLIDATE_SAME_SUIT,
        objective_id="synthetic-exact-three-card-band",
        description="form any 7s-6s-5s same-suit band",
        target_key="same_suit_run_at_least",
        target_params={"suit": "s", "min_len": 3},
        hard_preconditions=("exact incoming row known",),
        hard_evidence=("one legal preparation move exists",),
        admissible_lb=0,
        admissible_breakdown=None,
        heuristic_est_cost=0,
        heuristic_est_benefit=0,
        priority=PriorityComponents(),
        foundation_relevance="demonstration only",
        workspace_relevance="none",
        stock_relevance="incoming 5s completes prepared 7s-6s",
        explanation="bounded total-cost demonstration, not weight calibration",
    )


def run_valuable_preparation_demonstration() -> ValuablePreparationDemonstration:
    state, cards = valuable_preparation_fixture()
    candidate = build_preparation_candidate(
        state,
        ((1, 0, 1),),
        candidate_id="receiver-band-preparation",
        horizon=1,
        source_kinds=("exact-stock-receiver",),
        rationale=("place 6s on 7s for the known incoming 5s",),
        max_cost=8,
    )
    if candidate is None:
        raise AssertionError("valuable preparation fixture regressed")
    config = DealTimingConfig(
        max_preparation_projects=1,
        max_preparation_cost=8,
        max_h1_candidates=1,
        max_h2_candidates=0,
        tactical_max_cost=4,
        tactical_max_nodes=5_000,
        tactical_time_limit_s=2,
        downstream_max_cost=6,
        downstream_max_nodes=20_000,
        downstream_time_limit_s=5,
    )
    assessment = assess_deal_timing(
        state,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
        preparations=(candidate,),
        downstream_objective=_band_objective(),
    )
    if assessment.decision.kind != DealTimingDecisionKind.PREPARATION_PREFERRED:
        raise AssertionError("bounded valuable-preparation demonstration did not discriminate")
    return ValuablePreparationDemonstration(state, cards, candidate, assessment)


def run_prospective_deal_timing() -> FrozenDealTimingExperiment:
    """Complete all prospective work without reading canonical future actions."""
    cards = tuple(load_deal(DEAL_PATH))
    opening, six_state, deal1 = _build_verified_deal1(cards)
    checkpoint_a = _checkpoint("A — preferred opening", cards, SIX_MOVE_FIXTURE, 6)
    b_actions = SIX_MOVE_FIXTURE + deal1.actions
    checkpoint_b = _checkpoint("B — legal post-Deal-1", cards, b_actions, 11)
    if not states_structurally_equal(checkpoint_a.state, six_state):
        raise AssertionError("Checkpoint A state drift")
    if not states_structurally_equal(checkpoint_b.state, deal1.resulting_state):
        raise AssertionError("Checkpoint B state drift")

    cost23 = reconstruct_cost23_checkpoint()
    checkpoint_c = LegalCheckpoint(
        label="C — first foundation",
        state=cost23.state.clone(),
        actions=cost23.arm.full_actions,
        corrected_cost=cost23.arm.total_cost,
        stock_deals=cost23.deal_count,
        independent_replay_verified=cost23.independently_verified,
    )
    config = _diagnostic_config()
    assessment_a = assess_deal_timing(
        checkpoint_a.state,
        cards,
        spent_cost=6,
        incumbent_cost=REPLAY_VERIFIED_RESEARCH_INCUMBENT,
        config=config,
    )
    assessment_b = assess_deal_timing(
        checkpoint_b.state,
        cards,
        spent_cost=11,
        incumbent_cost=REPLAY_VERIFIED_RESEARCH_INCUMBENT,
        config=config,
    )
    assessment_c = assess_deal_timing(
        checkpoint_c.state,
        cards,
        spent_cost=23,
        incumbent_cost=REPLAY_VERIFIED_RESEARCH_INCUMBENT,
        config=config,
    )
    demonstration = run_valuable_preparation_demonstration()
    decisions = (assessment_a, assessment_b, assessment_c)
    frozen = all(item.prospective_frozen and not item.canonical_loaded for item in decisions)
    deal_now_behavior = any(
        item.decision.kind
        in (
            DealTimingDecisionKind.DEAL_NOW_PREFERRED,
            DealTimingDecisionKind.DEAL_REQUIRED_FOR_ACTIONABILITY,
        )
        and item.decision.legal_tableau_moves_remaining > 0
        for item in decisions
    )
    prep_behavior = demonstration.assessment.decision.kind == DealTimingDecisionKind.PREPARATION_PREFERRED
    verdict = "PASS" if frozen and deal_now_behavior and prep_behavior else "PARTIAL"
    reasons = (
        "Unrestricted Deal setting is explicit and engine-enforced",
        "exact incoming rows drive every counterfactual",
        "DEAL NOW competes at H0 rather than after tableau exhaustion",
        f"natural legal-moves-remain behavior demonstrated={deal_now_behavior}",
        f"bounded valuable-preparation behavior demonstrated={prep_behavior}",
        "preparation paid cost is charged against matched downstream saving",
        "economic timing never alters admissible incumbent pruning",
        "benchmark comparisons are bounded and do not continue a committed route",
    )
    return FrozenDealTimingExperiment(
        cards,
        checkpoint_a,
        checkpoint_b,
        checkpoint_c,
        assessment_a,
        assessment_b,
        assessment_c,
        demonstration,
        verdict,
        reasons,
        prospective_decisions_frozen=frozen,
    )


def inspect_canonical_after_freeze(
    experiment: FrozenDealTimingExperiment,
) -> CanonicalTimingObservation:
    """First and only canonical future-action read, after all decisions freeze."""
    if not experiment.prospective_decisions_frozen or experiment.canonical_loaded:
        raise AssertionError("canonical comparison requires a clean prospective freeze")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = SpiderState.from_cards(list(experiment.cards))
    corrected = 0
    since_deal = 0
    counts = []
    costs = []
    for action in actions:
        corrected += replay_actions(state, [action])
        if action == ("deal",):
            counts.append(since_deal)
            costs.append(corrected)
            since_deal = 0
        else:
            since_deal += 1
    return CanonicalTimingObservation(
        corrected_cost=corrected,
        solved=state.is_solved(),
        tableau_actions_before_deals=tuple(counts),
        corrected_costs_at_deals=tuple(costs),
        loaded_after_prospective_freeze=True,
    )


def _state_line(checkpoint: LegalCheckpoint) -> str:
    state = checkpoint.state
    return (
        f"cost={checkpoint.corrected_cost} actions={len(checkpoint.actions)} "
        f"deals={checkpoint.stock_deals} stock={len(state.stock)} fd={_face_down(state)} "
        f"foundations={len(state.foundations)} empties={[i + 1 for i in empty_columns(state)]} "
        f"fully-open={[i + 1 for i in fully_open_nonempty(state)]} "
        f"legal-moves={len(state.enumerate_moves())} replay={checkpoint.independent_replay_verified}"
    )


def _print_assessment(assessment: DealTimingAssessment) -> None:
    print(
        f"  decision={assessment.decision.kind.value} selected="
        f"{assessment.decision.selected_candidate_id} legal-moves="
        f"{assessment.decision.legal_tableau_moves_remaining}"
    )
    for reason in assessment.decision.reasons:
        print(f"  reason: {reason}")


def main() -> int:
    print("1. AUTHORITATIVE BASELINE")
    print(f"  branch base={AUTHORITATIVE_BASE}; incumbent context=172")
    print("  no canonical future actions loaded")
    experiment = run_prospective_deal_timing()

    print("\n2. EXACT DEAL-LEGALITY AUDIT AND EVIDENCE")
    print(f"  {MOBILITYWARE_RULE_EVIDENCE}")
    print(f"  active can_deal_into_empty={MW_RULES.can_deal_into_empty}")

    print("\n3. ENGINE / RULE RESULT")
    print("  can_deal() added; active unrestricted profile permits empty-column deals")
    print("  optional restricted profile is still enforced when explicitly supplied")

    print("\n4. EXACT INCOMING-ROW IMPACT API")
    for impact in experiment.assessment_b.deal_now.incoming_impacts:
        print(
            f"  c{impact.target_column + 1} {impact.card} on "
            f"{impact.current_receiver or '--'} landing={impact.landing.value} "
            f"same={impact.same_suit_adjacency} mixed={impact.lands_on_mixed_boundary} "
            f"buries={impact.buries_permanent_structure} outs={len(impact.immediate_out_moves)}"
        )

    print("\n5. CHECKPOINT A RECONSTRUCTION")
    print(f"  {_state_line(experiment.checkpoint_a)}")

    print("\n6. CHECKPOINT A DEAL LEGALITY / DECISION")
    print(f"  empty columns do not block this unrestricted profile: {experiment.checkpoint_a.state.can_deal()}")
    _print_assessment(experiment.assessment_a)

    print("\n7. CHECKPOINT B RECONSTRUCTION")
    print(f"  {_state_line(experiment.checkpoint_b)}")

    print("\n8. CHECKPOINT B EXACT NEXT ROW")
    print("  " + " ".join(str(card) for card in experiment.assessment_b.incoming_row))

    print("\n9. CHECKPOINT B DEAL-NOW COUNTERFACTUAL")
    b0 = experiment.assessment_b.deal_now
    print(f"  status={b0.status.value} added={b0.total_added_cost} replay={b0.independent_replay_verified}")
    print(f"  measurement={b0.measurement}")

    print("\n10. CHECKPOINT B PREPARATION CANDIDATES")
    for candidate in experiment.assessment_b.preparations:
        print(f"  {candidate.candidate_id}: cost={candidate.corrected_cost} actions={candidate.action_labels}")

    print("\n11. CHECKPOINT B PREPARE-THEN-DEAL COUNTERFACTUALS")
    for counterfactual in experiment.assessment_b.prepared_deals:
        print(f"  {counterfactual.label}: total-added={counterfactual.total_added_cost} replay={counterfactual.independent_replay_verified}")

    print("\n12. BOUNDED DOWNSTREAM COMPARISONS")
    for value in experiment.assessment_b.marginal_values:
        d = value.downstream
        print(f"  {value.candidate_id}: objective={d.objective_id} now={d.deal_now_cost} prep+later={d.preparation_plus_downstream_cost} net={d.bounded_net_gain}")

    print("\n13. FROZEN CHECKPOINT B TIMING DECISION")
    _print_assessment(experiment.assessment_b)

    print("\n14. CHECKPOINT C COST-23 RECONSTRUCTION")
    print(f"  {_state_line(experiment.checkpoint_c)}")

    print("\n15. CHECKPOINT C EXACT DEAL-3 ROW")
    print("  " + " ".join(str(card) for card in experiment.assessment_c.incoming_row))

    print("\n16. DEAL-NOW POST-DEAL-3 ANALYSIS")
    c0 = experiment.assessment_c.deal_now
    print(f"  added={c0.total_added_cost} replay={c0.independent_replay_verified} measurement={c0.measurement}")

    print("\n17. BOUNDED PRE-DEAL-3 CANDIDATES")
    for candidate in experiment.assessment_c.preparations:
        print(f"  {candidate.candidate_id}: cost={candidate.corrected_cost} actions={candidate.action_labels}")

    print("\n18. POST-PREPARATION DEAL-3 ANALYSES")
    for counterfactual in experiment.assessment_c.prepared_deals:
        print(f"  {counterfactual.label}: total-added={counterfactual.total_added_cost} measurement={counterfactual.measurement}")

    print("\n19. ACTIONABILITY TRANSITIONS")
    for label, assessment in (("B", experiment.assessment_b), ("C", experiment.assessment_c)):
        transition = assessment.deal_now.actionability
        print(f"  {label}: newly={transition.newly_actionable_after_deal} blocked={transition.blocked_by_deal}")

    print("\n20. MARGINAL PREPARATION ECONOMICS")
    for value in experiment.assessment_c.marginal_values:
        print(f"  {value.candidate_id}: prep={value.preparation_paid_cost} receivers={value.exact_receiver_success_delta:+d} mixed-avoided={value.mixed_liabilities_avoided:+d} net={value.downstream.bounded_net_gain}")

    print("\n21. FROZEN DEAL-3 TIMING RECOMMENDATION")
    _print_assessment(experiment.assessment_c)

    print("\n22. PROOF-SAFETY AUDIT")
    for label, assessment in (("A", experiment.assessment_a), ("B", experiment.assessment_b), ("C", experiment.assessment_c)):
        budget = assessment.deal_now.incumbent_budget
        print(f"  {label}: g={budget.spent_cost} deals={budget.h_deals} reveal-paid={budget.h_reveal_paid} h={budget.admissible_remaining_lower_bound} min={budget.hard_min_total} headroom={budget.hard_headroom} prune={budget.proof_prunable}")
    print("  timing adapter proof-pruning allowed=" + str(deal_as_economic_project(experiment.assessment_c).proof_pruning_allowed))

    print("\n23. PRODUCTION NO-INCUMBENT BEHAVIOUR")
    production = assess_deal_timing(
        experiment.checkpoint_c.state,
        experiment.cards,
        spent_cost=23,
        incumbent_cost=None,
        config=experiment.assessment_c.config,
        preparations=experiment.assessment_c.preparations,
    )
    print(f"  decision={production.decision.kind.value} incumbent={production.deal_now.incumbent_budget.incumbent_cost} headroom={production.deal_now.incumbent_budget.hard_headroom} prune={production.deal_now.incumbent_budget.proof_prunable}")

    print("\n24. LEGAL MOVES REMAIN — DEAL NOW DEMONSTRATION")
    _print_assessment(experiment.assessment_b)

    print("\n25. VALUABLE PREPARATION — DELAY DEAL DEMONSTRATION")
    demo = experiment.preparation_demonstration.assessment
    _print_assessment(demo)
    for value in demo.marginal_values:
        print(f"  downstream now={value.downstream.deal_now_cost}; prep={value.preparation_paid_cost}; after-prep={value.downstream.prepared_cost}; net={value.downstream.bounded_net_gain}")

    print("\nPROSPECTIVE DECISIONS FROZEN — canonical data may now be opened")
    print("\n26. OPTIONAL CANONICAL COMPARISON")
    canonical = inspect_canonical_after_freeze(experiment)
    print(f"  cost={canonical.corrected_cost} solved={canonical.solved} actions-before-deals={canonical.tableau_actions_before_deals} deal-cost-points={canonical.corrected_costs_at_deals}")
    print("  canonical observations did not alter any timing decision")
    print(f"\nHARD-GATE VERDICT: {experiment.verdict}")
    for reason in experiment.verdict_reasons:
        print(f"  - {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
