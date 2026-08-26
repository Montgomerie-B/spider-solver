"""Frozen-prediction economic project realization calibration gates."""

from __future__ import annotations

import inspect
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import economic_project_realizer as realizer
from spider.planner.diagnostics import economic_project_realization_report as report
from spider.planner.economic_project_realizer import (
    EconomicProjectRealizationStatus,
    PredictionAssessment,
    ProjectSelectionDisposition,
    ReworkValidation,
    StructuralOutcomeVector,
    assess_prediction,
    measure_structural_state,
    select_representative_projects,
    validate_rework_outcome,
    verify_prediction_freeze,
)
from spider.planner.economic_projects import (
    EconomicFrontierTier,
    EconomicProjectKind,
    empty_project_benefit,
    hard,
    make_economic_project,
)
from spider.planner.incumbent_budget import update_heuristic_remaining_work
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="module")
def experiment():
    return report.run_prospective_calibration()


def test_cost23_checkpoint_reconstructs_exactly(experiment):
    checkpoint = experiment.baseline.checkpoint
    assert checkpoint.arm.total_cost == 23
    assert checkpoint.action_count == 23
    assert checkpoint.deal_count == 2
    assert len(checkpoint.state.stock) == 30
    assert checkpoint.foundation_suits == ("s",)
    assert checkpoint.face_down_count == 32
    assert checkpoint.independently_verified
    assert states_structurally_equal(checkpoint.state, checkpoint.replay_state)


def test_frozen_predictions_are_immutable_during_realization(experiment):
    assert verify_prediction_freeze(experiment.prediction)
    assert all(
        outcome.series.prediction_fingerprint == experiment.prediction.fingerprint
        for outcome in experiment.outcomes
    )
    with pytest.raises(FrozenInstanceError):
        experiment.prediction.estimated_remaining_work = 0  # type: ignore[misc]


def test_project_sample_selection_is_deterministic(experiment):
    mapping = {item.project_id: item for item in experiment.actionability}
    again = select_representative_projects(
        experiment.baseline.checkpoint.state,
        experiment.baseline.analysis,
        experiment.prediction,
        actionability=mapping,
    )
    assert tuple(project.project_id for project in again.selected) == tuple(
        project.project_id for project in experiment.sample.selected
    )
    assert again.records == experiment.sample.records


def test_selection_contains_high_tier_and_tier4_control(experiment):
    tiers = [project.assessment.frontier_tier for project in experiment.sample.selected]
    assert tiers.count(EconomicFrontierTier.STRUCTURALLY_DOMINANT) == 2
    assert tiers.count(EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED) == 1


def test_selection_logic_contains_no_benchmark_ids_or_coordinates():
    source = inspect.getsource(realizer.select_representative_projects).lower()
    for token in ("4925153", "move-c2", "excavate-c", "spades", "hearts", "(1, 9, 1)"):
        assert token not in source


def test_actionable_and_future_epoch_projects_are_distinguished(experiment):
    selected = {
        record.project_id
        for record in experiment.sample.records
        if record.disposition == ProjectSelectionDisposition.SELECTED
    }
    future = {
        record.project_id
        for record in experiment.sample.records
        if record.disposition
        == ProjectSelectionDisposition.INELIGIBLE_UNTIL_FUTURE_EPOCH
    }
    assert selected
    assert future
    assert selected.isdisjoint(future)
    assert any(
        not item.actionable_current_epoch and item.nodes_expanded == 112
        for item in experiment.actionability
    )


def test_every_selected_project_has_structural_predicate(experiment):
    records = {
        record.project_id: record for record in experiment.sample.records
    }
    assert all(records[project.project_id].predicate is not None for project in experiment.sample.selected)


def test_project_realized_requires_full_predicate(experiment):
    for outcome in experiment.outcomes:
        best = outcome.series.best
        if best.status == EconomicProjectRealizationStatus.PROJECT_REALIZED:
            assert best.predicate_satisfied
        if outcome.project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED:
            assert best.status == EconomicProjectRealizationStatus.PROJECT_ADVANCED


def test_project_realization_uses_legal_corrected_moves(experiment):
    for outcome in experiment.outcomes:
        state = experiment.baseline.checkpoint.state.clone()
        cost = replay_actions(state, list(outcome.series.best.actions))
        assert cost == outcome.series.best.actual_corrected_cost


def test_every_generated_multicard_action_is_same_suit(experiment):
    for outcome in experiment.outcomes:
        state = experiment.baseline.checkpoint.state.clone()
        for action in outcome.series.best.actions:
            assert action != ("deal",)
            src, dst, k = action
            run = state.columns[src].face_up[-k:]
            if k > 1:
                assert state.is_movable_run(run)
            state.move(src, dst, k)


def test_independent_replay_reproduces_result_and_cost(experiment):
    for outcome in experiment.outcomes:
        best = outcome.series.best
        replay = experiment.baseline.checkpoint.state.clone()
        assert replay_actions(replay, list(best.actions)) == best.actual_corrected_cost
        assert best.result_key == realizer.canonical_state_key(replay)
        assert best.independent_replay_verified


def test_matched_resource_configuration_is_enforced(experiment):
    configs = {outcome.series.config for outcome in experiment.outcomes}
    assert configs == {experiment.config}
    for outcome in experiment.outcomes:
        for result in outcome.series.results:
            assert result.max_nodes == experiment.config.max_nodes_per_bound
            assert result.time_limit_s == experiment.config.time_limit_s_per_bound
            assert result.max_added_cost in experiment.config.added_cost_bounds


def test_no_project_may_take_deal3(experiment):
    for outcome in experiment.outcomes:
        best = outcome.series.best
        assert best.no_stock_deal
        assert best.stock_count_before == best.stock_count_after == 30
        assert ("deal",) not in best.actions
        assert outcome.after.stock_count == 30


def test_no_project_removes_second_foundation(experiment):
    assert all(
        outcome.series.best.foundation_count_before
        == outcome.series.best.foundation_count_after
        == 1
        for outcome in experiment.outcomes
    )


def test_structural_before_after_measurements_are_deterministic(experiment):
    for outcome in experiment.outcomes:
        end = experiment.baseline.checkpoint.state.clone()
        replay_actions(end, list(outcome.series.best.actions))
        again = measure_structural_state(
            end,
            cards=experiment.baseline.checkpoint.cards,
            analysis=outcome.post_analysis,
        )
        assert again == outcome.after


def test_tier4_status_is_not_rewritten_after_observation(experiment):
    control = next(
        outcome
        for outcome in experiment.outcomes
        if outcome.project.assessment.frontier_tier
        == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
    )
    frozen = next(
        row for row in experiment.prediction.projects if row.project_id == control.project.project_id
    )
    assert frozen.frontier_tier == int(EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED)
    assert control.project.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
    assert control.prediction_assessment == PredictionAssessment.CONFIRMED


def test_rework_validation_requires_actual_promised_return(experiment):
    assert experiment.rework.validation == ReworkValidation.FAILED_TO_REALIZE
    assert "cannot make even one target reveal" in experiment.rework.reason


def test_unrelated_progress_cannot_satisfy_rework_target(experiment):
    natural = next(
        project
        for project in experiment.baseline.analysis.frontier.ordered_projects
        if project.project_id == experiment.rework.project_id
    )
    arbitrary_result = replace(
        experiment.outcomes[0].series.best,
        project_id=natural.project_id,
        status=EconomicProjectRealizationStatus.PROJECT_REALIZED,
    )
    unrelated = StructuralOutcomeVector(
        paid_cost=1,
        critical_dependencies_removed=0,
        stable_joins_delta=0,
        same_suit_mass_delta=0,
        mixed_boundaries_delta=0,
        workspace_delta=0,
        mobility_delta=5,
        must_burden_delta=0,
        bounded_downstream_cost_delta=None,
        rehandling_debt_delta=0,
        target_dependencies_satisfied=0,
    )
    validation, _reason = validate_rework_outcome(natural, arbitrary_result, unrelated)
    assert validation == ReworkValidation.NOT_VALIDATED


def test_synthetic_temporary_park_alone_cannot_realize_promised_return():
    columns = [
        Column([], [Card("d", 7)]),
        Column([], [Card("c", 8)]),
    ]
    columns.extend(Column([], [Card("s", 5)]) for _ in range(8))
    state = SpiderState(columns, [])
    benefit = replace(
        empty_project_benefit(),
        campaign_must_dependencies=hard(10, "promised downstream dependency"),
    )
    project = make_economic_project(
        project_id="synthetic-positive-rework",
        kind=EconomicProjectKind.TEMPORARY_REWORK,
        description="park whose promised return is not the park itself",
        earliest_useful_epoch=0,
        benefit=benefit,
        action=(0, 1, 1),
    )
    result = realizer.realize_economic_project(
        state,
        project,
        (),
        max_added_cost=4,
        max_nodes=100,
        time_limit_s=1,
    )
    assert result.status == EconomicProjectRealizationStatus.INVALID_PROJECT
    assert not result.predicate_satisfied
    assert not result.actions


def test_downstream_probes_use_identical_resources(experiment):
    for outcome in experiment.outcomes:
        probe = outcome.downstream
        assert probe.resources_matched
        assert probe.max_added_cost == experiment.config.downstream_max_cost
        assert probe.max_nodes == experiment.config.downstream_max_nodes
        assert probe.time_limit_s == experiment.config.downstream_time_limit_s


def test_project_economics_never_changes_proof_prunable(experiment):
    baseline = experiment.baseline.research_budget
    changed = update_heuristic_remaining_work(baseline, 1_000_000)
    assert changed.proof_prunable == baseline.proof_prunable
    assert changed.hard_min_total == baseline.hard_min_total
    assert all(not outcome.research_budget_after.proof_prunable for outcome in experiment.outcomes)


def test_external_score_never_enters_generic_pruning_or_realization():
    source = inspect.getsource(realizer).lower()
    assert "119" not in source
    assert "leaderboard" not in source


def test_invalid_historical_states_are_never_reconstructed():
    source = inspect.getsource(realizer).lower() + inspect.getsource(report).lower()
    assert "cost-47" not in source
    assert "cost-49" not in source
    assert "post-command-14" not in source


def test_production_module_has_no_benchmark_constants():
    source = inspect.getsource(realizer).lower()
    for token in (
        "4925153",
        "canonical.moves",
        "move-c2",
        "move-c9",
        "excavate-c4",
        "172",
        "spade",
    ):
        assert token not in source


def test_all_cloned_experiments_share_identical_start_state(experiment):
    expected = realizer.canonical_state_key(experiment.baseline.checkpoint.state)
    assert all(outcome.series.best.start_key == expected for outcome in experiment.outcomes)


def test_prediction_and_result_freeze_precedes_canonical_read(experiment):
    assert experiment.prediction.prediction_frozen
    assert experiment.prediction_result_frozen
    assert not experiment.prediction.canonical_loaded
    assert not experiment.canonical_loaded
    observation = report.inspect_canonical_after_calibration(experiment)
    assert observation.loaded_after_full_freeze
    assert observation.corrected_cost == 172
    assert observation.solved


def test_calibration_reports_pass_not_strong_pass(experiment):
    assert experiment.verdict == "PASS"
    assert any("actionable Tier-2 sampled=False" in reason for reason in experiment.verdict_reasons)
    assert all(
        outcome.prediction_assessment == PredictionAssessment.CONFIRMED
        for outcome in experiment.outcomes
    )
