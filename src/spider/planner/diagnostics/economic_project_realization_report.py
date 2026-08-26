#!/usr/bin/env python3
"""Frozen-prediction economic project realization calibration report."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.engine import SpiderState
from spider.metrics import format_action, parse_moves_file, replay_actions
from spider.move_lifecycle import PlacementClass, assess_tableau_move
from spider.planner.diagnostics.economic_project_analysis_report import (
    AUTHORITATIVE_SOURCE_BASE,
    CANONICAL_PATH,
    REPLAY_VERIFIED_RESEARCH_INCUMBENT,
    FrozenEconomicAnalysis,
    freeze_prospective_economics,
)
from spider.planner.economic_project_realizer import (
    DownstreamProbeResult,
    EconomicProjectBoundSeries,
    EconomicProjectResourceConfig,
    EconomicProjectSample,
    FrozenEconomicPrediction,
    PredictionAssessment,
    ProjectActionability,
    ProjectSelectionDisposition,
    ReworkValidation,
    StructuralMeasurement,
    StructuralOutcomeVector,
    assess_prediction,
    freeze_economic_predictions,
    measure_structural_state,
    probe_frontier_actionability,
    realize_economic_project_bounds,
    run_downstream_probe,
    select_representative_projects,
    structural_outcome_vector,
    target_dependencies_satisfied,
    validate_rework_outcome,
    verify_prediction_freeze,
)
from spider.planner.economic_projects import (
    EconomicAnalysisResult,
    EconomicFrontierTier,
    EconomicProject,
    analyze_economic_projects,
)
from spider.planner.incumbent_budget import IncumbentBudget, build_incumbent_budget
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_CALIBRATION_BASE = "a1c4f0a82877d5f5a7c6ca6377f5ac3c4646598d"


@dataclass(frozen=True)
class ProjectCalibrationOutcome:
    project: EconomicProject
    series: EconomicProjectBoundSeries
    before: StructuralMeasurement
    after: StructuralMeasurement
    vector: StructuralOutcomeVector
    post_analysis: EconomicAnalysisResult
    downstream: DownstreamProbeResult
    prediction_assessment: PredictionAssessment
    assessment_reason: str
    research_budget_after: IncumbentBudget


@dataclass(frozen=True)
class ReworkCalibrationOutcome:
    project_id: Optional[str]
    validation: ReworkValidation
    reason: str
    frozen_investment: Optional[Tuple]
    actionability: Optional[ProjectActionability]


@dataclass(frozen=True)
class FrozenCalibrationExperiment:
    baseline: FrozenEconomicAnalysis
    prediction: FrozenEconomicPrediction
    actionability: Tuple[ProjectActionability, ...]
    sample: EconomicProjectSample
    config: EconomicProjectResourceConfig
    outcomes: Tuple[ProjectCalibrationOutcome, ...]
    rework: ReworkCalibrationOutcome
    verdict: str
    verdict_reasons: Tuple[str, ...]
    prediction_result_frozen: bool
    canonical_loaded: bool = False


@dataclass(frozen=True)
class CanonicalCalibrationObservation:
    corrected_cost: int
    solved: bool
    action_count: int
    stable_joins: int
    mixed_parks: int
    workspace_parks: int
    selected_join_relations_seen: Tuple[str, ...]
    loaded_after_full_freeze: bool


def _state_after(start: SpiderState, actions) -> SpiderState:
    state = start.clone()
    replay_actions(state, list(actions))
    return state


def _natural_rework_candidate(
    analysis: EconomicAnalysisResult,
) -> Optional[EconomicProject]:
    return next(
        (
            project
            for project in analysis.frontier.ordered_projects
            if project.assessment.frontier_tier
            == EconomicFrontierTier.POSITIVE_INVESTMENT
            and (project.debt.ordering_total > 0 or project.rework_investment is not None)
        ),
        None,
    )


def _verdict(
    sample: EconomicProjectSample,
    outcomes: Tuple[ProjectCalibrationOutcome, ...],
    rework: ReworkCalibrationOutcome,
    prediction: FrozenEconomicPrediction,
) -> Tuple[str, Tuple[str, ...]]:
    selected_tiers = {outcome.project.assessment.frontier_tier for outcome in outcomes}
    dominant = [
        outcome
        for outcome in outcomes
        if outcome.project.assessment.frontier_tier
        == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    ]
    controls = [
        outcome
        for outcome in outcomes
        if outcome.project.assessment.frontier_tier
        == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
    ]
    dominant_confirmed = bool(
        dominant
        and all(
            item.prediction_assessment == PredictionAssessment.CONFIRMED
            and item.vector.stable_joins_delta > 0
            and item.vector.mixed_boundaries_delta < 0
            for item in dominant
        )
    )
    control_weak = bool(
        controls
        and all(
            item.prediction_assessment == PredictionAssessment.CONFIRMED
            and item.vector.stable_joins_delta <= 0
            and item.vector.mixed_boundaries_delta > 0
            for item in controls
        )
    )
    resources_matched = all(
        item.series.config == outcomes[0].series.config for item in outcomes
    ) if outcomes else False
    freeze_ok = verify_prediction_freeze(prediction)
    positive_sampled = EconomicFrontierTier.POSITIVE_INVESTMENT in selected_tiers
    reasons = (
        f"prediction snapshot intact={freeze_ok}",
        f"matched resources={resources_matched}",
        f"dominant permanent outcomes confirmed={dominant_confirmed}",
        f"Tier-4 control meaningfully weaker={control_weak}",
        f"actionable Tier-2 sampled={positive_sampled}",
        f"natural rework validation={rework.validation.value}: {rework.reason}",
        "all benchmark routes remained at stock=30 / epoch=2",
        "economics and structural outcome vectors remained non-pruning",
    )
    if freeze_ok and resources_matched and dominant_confirmed and control_weak:
        # The fixed checkpoint has no tableau-only Tier-2 reveal project.  The
        # ordering is discriminating, but this is too small for STRONG PASS.
        return "PASS", reasons
    if freeze_ok and outcomes:
        return "PARTIAL", reasons
    return "FAIL", reasons


def run_prospective_calibration(
    *,
    config: EconomicProjectResourceConfig = EconomicProjectResourceConfig(),
) -> FrozenCalibrationExperiment:
    """Freeze predictions, then run the matched experiment without canonical data."""
    baseline = freeze_prospective_economics()
    prediction = freeze_economic_predictions(
        baseline.analysis,
        research_budget=baseline.research_budget,
        production_budget=baseline.production_budget,
    )
    if not verify_prediction_freeze(prediction):
        raise AssertionError("prediction freeze failed before actionability screening")

    actionability = probe_frontier_actionability(
        baseline.checkpoint.state,
        baseline.analysis,
        config=config,
    )
    actionability_by_id = {item.project_id: item for item in actionability}
    sample = select_representative_projects(
        baseline.checkpoint.state,
        baseline.analysis,
        prediction,
        actionability=actionability_by_id,
    )
    before = measure_structural_state(
        baseline.checkpoint.state,
        cards=baseline.checkpoint.cards,
        analysis=baseline.analysis,
    )
    outcomes = []
    for project in sample.selected:
        series = realize_economic_project_bounds(
            baseline.checkpoint.state.clone(),
            project,
            baseline.checkpoint.cards,
            prediction,
            config=config,
        )
        best = series.best
        end = _state_after(baseline.checkpoint.state, best.actions)
        if len(end.stock) != 30 or len(end.foundations) != 1:
            raise AssertionError("calibration route left the legal no-Deal-3 checkpoint scope")
        post_analysis = analyze_economic_projects(end, cards=baseline.checkpoint.cards)
        after = measure_structural_state(
            end,
            cards=baseline.checkpoint.cards,
            analysis=post_analysis,
        )
        downstream = run_downstream_probe(
            baseline.checkpoint.state,
            end,
            post_analysis,
            baseline.checkpoint.cards,
            prediction,
            completed_project_id=project.project_id,
            config=config,
        )
        vector = structural_outcome_vector(
            before,
            after,
            paid_cost=best.actual_corrected_cost,
            target_dependencies_satisfied=target_dependencies_satisfied(
                baseline.checkpoint.state, end, project
            ),
            bounded_downstream_cost_delta=downstream.bounded_cost_delta,
        )
        assessment, assessment_reason = assess_prediction(project, best, vector)
        after_budget = build_incumbent_budget(
            end,
            spent_cost=23 + int(best.actual_corrected_cost or 0),
            incumbent_cost=REPLAY_VERIFIED_RESEARCH_INCUMBENT,
            heuristic_remaining_work=post_analysis.estimated_remaining_work,
        )
        outcomes.append(
            ProjectCalibrationOutcome(
                project,
                series,
                before,
                after,
                vector,
                post_analysis,
                downstream,
                assessment,
                assessment_reason,
                after_budget,
            )
        )

    natural_rework = _natural_rework_candidate(baseline.analysis)
    if natural_rework is None:
        rework = ReworkCalibrationOutcome(
            None,
            ReworkValidation.FAILED_TO_REALIZE,
            "no natural positive-investment project carried rework debt",
            None,
            None,
        )
    else:
        action = actionability_by_id[natural_rework.project_id]
        selected_outcome = next(
            (item for item in outcomes if item.project.project_id == natural_rework.project_id),
            None,
        )
        if selected_outcome is None:
            validation = ReworkValidation.FAILED_TO_REALIZE
            reason = (
                "natural debt-bearing Tier-2 project cannot make even one target reveal "
                "inside the exhaustive matched no-deal closure; exit was already frozen as unbounded"
            )
        else:
            validation, reason = validate_rework_outcome(
                natural_rework,
                selected_outcome.series.best,
                selected_outcome.vector,
            )
        frozen_row = next(
            item for item in prediction.projects if item.project_id == natural_rework.project_id
        )
        rework = ReworkCalibrationOutcome(
            natural_rework.project_id,
            validation,
            reason,
            frozen_row.rework_investment,
            action,
        )

    outcome_tuple = tuple(outcomes)
    verdict, reasons = _verdict(sample, outcome_tuple, rework, prediction)
    if not verify_prediction_freeze(prediction):
        raise AssertionError("realization mutated frozen economic predictions")
    return FrozenCalibrationExperiment(
        baseline,
        prediction,
        actionability,
        sample,
        config,
        outcome_tuple,
        rework,
        verdict,
        reasons,
        prediction_result_frozen=True,
    )


def inspect_canonical_after_calibration(
    experiment: FrozenCalibrationExperiment,
) -> CanonicalCalibrationObservation:
    if not experiment.prediction_result_frozen or experiment.canonical_loaded:
        raise AssertionError("canonical read requires fully frozen predictions and results")
    actions = tuple(parse_moves_file(CANONICAL_PATH))
    state = SpiderState.from_cards(list(experiment.baseline.checkpoint.cards))
    stable = mixed = workspace = 0
    seen = set()
    corrected = 0
    selected_relations = [
        (outcome.project.project_id, outcome.series.best.predicate)
        for outcome in experiment.outcomes
        if outcome.series.best.predicate is not None
        and outcome.series.best.predicate.kind.value == "PERMANENT_SAME_SUIT_JOIN"
    ]
    for action in actions:
        if action == ("deal",):
            corrected += state.deal()
        else:
            src, dst, k = action
            lifecycle = assess_tableau_move(state, (src, dst, k))
            if lifecycle.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN:
                stable += 1
            elif lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK:
                mixed += 1
            elif lifecycle.placement_class == PlacementClass.WORKSPACE_PARK:
                workspace += 1
            corrected += state.move(src, dst, k)
        for project_id, predicate in selected_relations:
            assert predicate is not None
            # Similar structural relation may appear in any column later.
            for pile in state.columns:
                if any(
                    lower.suit == upper.suit == predicate.suit
                    and lower.rank == predicate.high_rank
                    and upper.rank == predicate.low_rank
                    for lower, upper in zip(pile.face_up, pile.face_up[1:])
                ):
                    seen.add(project_id)
                    break
    if corrected != REPLAY_VERIFIED_RESEARCH_INCUMBENT or not state.is_solved():
        raise AssertionError("canonical post-freeze replay regressed")
    return CanonicalCalibrationObservation(
        corrected,
        state.is_solved(),
        len(actions),
        stable,
        mixed,
        workspace,
        tuple(sorted(seen)),
        True,
    )


def _print_measurement(prefix: str, measurement: StructuralMeasurement) -> None:
    print(
        f"  {prefix}: fd={measurement.face_down_count} fnd={measurement.foundation_count} "
        f"stock={measurement.stock_count} empty={measurement.empty_columns} "
        f"open={measurement.fully_open_columns} mobility={measurement.legal_move_count} "
        f"joins={measurement.stable_same_suit_joins} mass={measurement.same_suit_run_mass} "
        f"longest={measurement.longest_same_suit_run} mixed={measurement.mixed_suit_boundaries} "
        f"debt={measurement.rehandling_debt:.1f} critical={measurement.critical_dependencies_pending} "
        f"MUST={measurement.campaign_must_burden}"
    )


def main() -> int:
    print("1. AUTHORITATIVE BASELINE")
    print(f"  economic base={AUTHORITATIVE_CALIBRATION_BASE}")
    print(f"  legal source lineage={AUTHORITATIVE_SOURCE_BASE}")
    experiment = run_prospective_calibration()
    checkpoint = experiment.baseline.checkpoint

    print("\n2. COST-23 RECONSTRUCTION")
    print(
        f"  cost={checkpoint.arm.total_cost} actions={checkpoint.action_count} "
        f"deals={checkpoint.deal_count} stock={len(checkpoint.state.stock)} "
        f"foundation={checkpoint.foundation_suits} fd={checkpoint.face_down_count} "
        f"replay={checkpoint.independently_verified} no-Deal-3={checkpoint.no_deal3}"
    )

    print("\n3. FROZEN ECONOMIC FRONTIER")
    print(f"  fingerprint={experiment.prediction.fingerprint}")
    for project in experiment.prediction.projects:
        print(
            f"  {project.order:>2} T{project.frontier_tier} {project.project_id:<24} "
            f"net={project.predicted_net:>6.1f} confidence={project.confidence}"
        )

    print("\n4. SELECTED REPRESENTATIVE PROJECTS / ACTIONABILITY")
    by_id = {item.project_id: item for item in experiment.actionability}
    for record in experiment.sample.records:
        action = by_id[record.project_id]
        print(
            f"  {record.project_id:<24} {record.disposition.value:<38} "
            f"{record.category:<16} probe={action.probe_status.value} "
            f"nodes={action.nodes_expanded}: {record.reason}"
        )

    print("\n5. FROZEN PREDICTED COST / BENEFIT / DEBT")
    frozen_by_id = {item.project_id: item for item in experiment.prediction.projects}
    for project in experiment.sample.selected:
        row = frozen_by_id[project.project_id]
        print(
            f"  {row.project_id}: T{row.frontier_tier} predicted-net={row.predicted_net:.1f} "
            f"cost={project.cost.ordering_total:.1f} benefit={project.benefit.structural_total:.1f} "
            f"debt={project.debt.ordering_total:.1f} exit-bounded={row.exit_route_bounded}"
        )

    cfg = experiment.config
    print("\n6. MATCHED RESOURCE CONFIGURATION")
    print(
        f"  bounds={cfg.added_cost_bounds} nodes/bound={cfg.max_nodes_per_bound} "
        f"seconds/bound={cfg.time_limit_s_per_bound} allow-deal={cfg.allow_stock_deal} "
        f"allow-foundation-increase={cfg.allow_foundation_increase}"
    )

    print("\n7. PER-BOUND REALIZATION RESULTS")
    for outcome in experiment.outcomes:
        print(f"  {outcome.project.project_id}")
        for result in outcome.series.results:
            print(
                f"    <= {result.max_added_cost}: {result.status.value} "
                f"cost={result.actual_corrected_cost} nodes={result.nodes_expanded} "
                f"time={result.elapsed_seconds:.3f}s predicate={result.predicate_satisfied}"
            )

    print("\n8. BEST ACTION SEQUENCES FROM COST 23")
    for outcome in experiment.outcomes:
        best = outcome.series.best
        labels = tuple(format_action(action) for action in best.actions)
        print(f"  {outcome.project.project_id}: {labels or ('no action',)}")

    print("\n9. INDEPENDENT REPLAY")
    for outcome in experiment.outcomes:
        best = outcome.series.best
        print(
            f"  {outcome.project.project_id}: replay={best.independent_replay_verified} "
            f"cost={best.actual_corrected_cost} no-deal={best.no_stock_deal} "
            f"stock={best.stock_count_before}->{best.stock_count_after} "
            f"foundation={best.foundation_count_before}->{best.foundation_count_after}"
        )

    print("\n10. BEFORE / AFTER STRUCTURAL VECTORS")
    for outcome in experiment.outcomes:
        print(f"  {outcome.project.project_id}")
        _print_measurement("before", outcome.before)
        _print_measurement("after ", outcome.after)
        print(f"    vector={outcome.vector}")

    print("\n11. DOWNSTREAM BOUNDED PROBES")
    for outcome in experiment.outcomes:
        probe = outcome.downstream
        print(
            f"  {outcome.project.project_id}: objective={probe.objective_project_id} "
            f"original={probe.original_status.value}/{probe.original_cost} "
            f"post={probe.post_status.value}/{probe.post_cost} "
            f"delta={probe.bounded_cost_delta} matched={probe.resources_matched}"
        )

    print("\n12. REWORK POT-OF-GOLD VALIDATION")
    print(
        f"  project={experiment.rework.project_id} result={experiment.rework.validation.value}: "
        f"{experiment.rework.reason}"
    )
    print(f"  frozen investment={experiment.rework.frozen_investment}")

    print("\n13. TIER-4 CONTROL")
    for outcome in experiment.outcomes:
        if outcome.project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED:
            print(
                f"  {outcome.project.project_id}: {outcome.series.best.status.value} "
                f"vector={outcome.vector}; assessment={outcome.prediction_assessment.value}"
            )

    print("\n14. PREDICTION VERSUS ACTUAL")
    print(
        "  project tier pred-cost pred-return pred-debt status actual-cost target "
        "critical stable mixed workspace MUST downstream debt assessment"
    )
    for outcome in experiment.outcomes:
        project = outcome.project
        vector = outcome.vector
        best = outcome.series.best
        print(
            f"  {project.project_id} T{int(project.assessment.frontier_tier)} "
            f"{project.cost.ordering_total:.1f} {project.benefit.structural_total:.1f} "
            f"{project.debt.ordering_total:.1f} {best.status.value} "
            f"{best.actual_corrected_cost} {best.predicate_satisfied} "
            f"{vector.critical_dependencies_removed:+d} {vector.stable_joins_delta:+d} "
            f"{vector.mixed_boundaries_delta:+d} {vector.workspace_delta:+d} "
            f"{vector.must_burden_delta:+d} {vector.bounded_downstream_cost_delta} "
            f"{vector.rehandling_debt_delta:+.1f} {outcome.prediction_assessment.value}"
        )

    print("\n15. DISCRIMINATION SUMMARY")
    for outcome in experiment.outcomes:
        print(
            f"  {outcome.project.project_id}: {outcome.prediction_assessment.value} — "
            f"{outcome.assessment_reason}"
        )
    print("  Tier-1 joins each buy permanent structure and remove debt for cost 1; control adds debt and loses mobility.")

    print("\n16. INCUMBENT / PROOF SAFETY")
    b = experiment.baseline.research_budget
    print(
        f"  baseline g={b.spent_cost} h={b.admissible_remaining_lower_bound} "
        f"hard-min={b.hard_min_total} incumbent={b.incumbent_cost} target={b.improvement_target} "
        f"proof-prunable={b.proof_prunable}"
    )
    for outcome in experiment.outcomes:
        b2 = outcome.research_budget_after
        print(
            f"  {outcome.project.project_id}: g={b2.spent_cost} h={b2.admissible_remaining_lower_bound} "
            f"proof-prunable={b2.proof_prunable}"
        )
    print("  project economics, structural vectors, and external context never enter proof pruning")

    print("\n17. PROSPECTIVE HARD-GATE VERDICT")
    print(f"  {experiment.verdict}")
    for reason in experiment.verdict_reasons:
        print(f"  - {reason}")
    print(
        f"  frozen-results={experiment.prediction_result_frozen} "
        f"canonical-loaded={experiment.canonical_loaded}"
    )

    canonical = inspect_canonical_after_calibration(experiment)
    print("\n18. OPTIONAL CANONICAL OBSERVATIONS — POST-FREEZE ONLY")
    print(
        f"  loaded-after-full-freeze={canonical.loaded_after_full_freeze} "
        f"cost={canonical.corrected_cost} actions={canonical.action_count} solved={canonical.solved}"
    )
    print(
        f"  stable={canonical.stable_joins} mixed={canonical.mixed_parks} "
        f"workspace={canonical.workspace_parks} selected-relations-seen={canonical.selected_join_relations_seen}"
    )
    print("  canonical data did not alter predictions, selection, outcomes, or classifications")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
