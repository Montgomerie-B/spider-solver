from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import deal_timing as timing
from spider.planner.deal_timing import (
    DealCounterfactual,
    DealTimingDecisionKind,
    DealTimingReason,
    DealTimingStatus,
    DownstreamCostComparison,
    MarginalPreparationValue,
    choose_deal_timing,
    deal_as_economic_project,
    simulate_deal_counterfactual,
)
from spider.planner.diagnostics import strategic_deal_timing_report as report
from spider.planner.space_lifecycle import empty_columns
from spider.rules import MW_RULES, MobilityWareRules
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="session")
def experiment():
    return report.run_prospective_deal_timing()


def _empty_deal_state(*, stock_count: int = 10) -> SpiderState:
    columns = [Column([], [])]
    columns.extend(Column([], [Card("c", 9)]) for _ in range(9))
    stock = [Card("s", (index % 13) + 1) for index in range(stock_count)]
    return SpiderState(columns, stock, [])


def _minimal_counterfactual(
    status: DealTimingStatus = DealTimingStatus.DEAL_NOW,
) -> DealCounterfactual:
    return DealCounterfactual(
        label="DEAL NOW",
        status=status,
        preparation=None,
        preparation_cost=0,
        deal_cost=1 if status == DealTimingStatus.DEAL_NOW else 0,
        total_added_cost=1 if status == DealTimingStatus.DEAL_NOW else 0,
        actions=(("deal",),) if status == DealTimingStatus.DEAL_NOW else (),
        post_deal_state=None,
        result_key_hex=None,
        independent_replay_verified=True,
        incoming_impacts=(),
        pre_deal_measurement=None,
        measurement=None,
        economic_analysis=None,
        economic_frontier=(),
        estimated_remaining_work=None,
        actionability=None,
        incumbent_budget=None,
        notes=(),
    )


def _marginal(*, net: int | None, comparable: bool = True) -> MarginalPreparationValue:
    downstream = DownstreamCostComparison(
        objective_id="test-objective",
        matched_max_cost=10,
        matched_max_nodes=50_000,
        matched_time_limit_s=15,
        deal_now_status="found",
        deal_now_cost=4,
        prepared_status="found" if comparable else "not_found_within_bound",
        prepared_cost=1 if comparable else None,
        preparation_plus_downstream_cost=2 if comparable else None,
        bounded_saving_before_preparation_cost=3 if comparable else None,
        bounded_net_gain=net,
        comparable=comparable,
        notes=("matched resources",),
    )
    return MarginalPreparationValue(
        candidate_id="candidate",
        preparation_paid_cost=1,
        preparation_rehandling_debt=0,
        stable_joins_broken_during_preparation=0,
        workspace_consumed_during_preparation=0,
        permanent_joins_retained_delta=1,
        same_suit_mass_delta=2,
        mixed_liabilities_avoided=1,
        exact_receiver_success_delta=1,
        campaign_must_burden_reduction=0,
        critical_dependencies_removed=0,
        newly_actionable_project_delta=0,
        workspace_delta=0,
        mobility_delta=1,
        estimated_future_work_avoided=2,
        downstream=downstream,
    )


def test_unrestricted_mobilityware_profile_is_explicit():
    assert MW_RULES.can_deal_into_empty


def test_engine_can_deal_with_empty_column_under_confirmed_profile():
    state = _empty_deal_state()
    assert state.can_deal()
    assert state.deal() == 1
    assert not state.columns[0].is_empty()


def test_engine_enforces_explicit_restricted_profile():
    state = _empty_deal_state()
    restricted = MobilityWareRules(can_deal_into_empty=False)
    assert not state.can_deal(restricted)
    with pytest.raises(ValueError, match="empty tableau"):
        state.deal(restricted)


def test_fully_open_nonempty_is_not_an_empty_column():
    state = _empty_deal_state()
    state.columns[0].face_up.append(Card("h", 4))
    restricted = MobilityWareRules(can_deal_into_empty=False)
    assert not state.columns[0].is_empty()
    assert not state.columns[0].face_down
    assert state.can_deal(restricted)


def test_insufficient_stock_remains_illegal_even_when_unrestricted():
    state = _empty_deal_state(stock_count=9)
    assert not state.can_deal()
    with pytest.raises(ValueError, match="fewer than 10"):
        state.deal()


def test_exact_incoming_row_is_derived_from_each_state(experiment):
    for checkpoint, assessment in (
        (experiment.checkpoint_a, experiment.assessment_a),
        (experiment.checkpoint_b, experiment.assessment_b),
        (experiment.checkpoint_c, experiment.assessment_c),
    ):
        assert assessment.incoming_row == tuple(checkpoint.state.stock[-10:])


def test_deal_now_uses_a_clone(experiment):
    state = experiment.checkpoint_b.state
    before_stock = tuple(state.stock)
    before_tops = tuple(state.top_row())
    assert experiment.assessment_b.deal_now.post_deal_state is not state
    assert tuple(state.stock) == before_stock
    assert tuple(state.top_row()) == before_tops


def test_counterfactual_deal_does_not_mutate_source(experiment):
    checkpoint = experiment.checkpoint_b
    before = checkpoint.state.clone()
    simulate_deal_counterfactual(
        checkpoint.state,
        experiment.cards,
        spent_cost=11,
        incumbent_cost=172,
    )
    assert states_structurally_equal(before, checkpoint.state)


def test_preparation_candidates_are_currently_actionable(experiment):
    start = experiment.checkpoint_b.state
    for candidate in experiment.assessment_b.preparations:
        replay = start.clone()
        replay_actions(replay, list(candidate.actions))
        assert states_structurally_equal(replay, candidate.resulting_state)


def test_inaccessible_projects_are_not_repeated_in_h2(experiment):
    for candidate in experiment.assessment_b.preparations:
        assert len(candidate.source_project_ids) == len(set(candidate.source_project_ids))


def test_preparation_states_are_structurally_deduplicated(experiment):
    keys = [candidate.state_key_hex for candidate in experiment.assessment_b.preparations]
    assert len(keys) == len(set(keys))


def test_every_preparation_route_independently_replays(experiment):
    for assessment, checkpoint in (
        (experiment.assessment_a, experiment.checkpoint_a),
        (experiment.assessment_b, experiment.checkpoint_b),
        (experiment.assessment_c, experiment.checkpoint_c),
    ):
        for candidate in assessment.preparations:
            assert candidate.independent_replay_verified
            replay = checkpoint.state.clone()
            assert replay_actions(replay, list(candidate.actions)) == candidate.corrected_cost


def test_every_post_preparation_deal_independently_replays(experiment):
    for assessment in (
        experiment.assessment_a,
        experiment.assessment_b,
        experiment.assessment_c,
    ):
        assert all(item.independent_replay_verified for item in assessment.prepared_deals)


def test_generic_timing_module_contains_no_benchmark_constants():
    source = inspect.getsource(timing)
    for token in ("4925153", "canonical.moves", "cost-23", "cost-47", "cost-49"):
        assert token.lower() not in source.lower()
    assert "119" not in source and "172" not in source


def test_legal_moves_remaining_do_not_block_deal_decision(experiment):
    decision = experiment.assessment_b.decision
    assert decision.legal_tableau_moves_remaining > 0
    assert decision.kind == DealTimingDecisionKind.DEAL_NOW_PREFERRED


def test_planner_selects_deal_now_before_tableau_exhaustion():
    decision = choose_deal_timing(
        _minimal_counterfactual(), (_marginal(net=-1),), legal_tableau_moves_remaining=4
    )
    assert decision.kind == DealTimingDecisionKind.DEAL_NOW_PREFERRED
    assert decision.legal_tableau_moves_remaining == 4


def test_planner_selects_preparation_when_bounded_return_exceeds_cost(experiment):
    demo = experiment.preparation_demonstration.assessment
    assert demo.decision.kind == DealTimingDecisionKind.PREPARATION_PREFERRED
    assert demo.marginal_values[0].downstream.bounded_net_gain == 2


def test_marginal_comparison_charges_preparation_cost(experiment):
    value = experiment.preparation_demonstration.assessment.marginal_values[0]
    assert value.downstream.deal_now_cost == 3
    assert value.downstream.prepared_cost == 0
    assert value.downstream.bounded_saving_before_preparation_cost == 3
    assert value.downstream.bounded_net_gain == 3 - value.preparation_paid_cost == 2


def test_prettier_tableau_alone_is_insufficient_evidence():
    value = _marginal(net=None, comparable=False)
    assert value.permanent_joins_retained_delta > 0
    decision = choose_deal_timing(
        _minimal_counterfactual(), (value,), legal_tableau_moves_remaining=1
    )
    assert decision.kind == DealTimingDecisionKind.COMPARISON_INCONCLUSIVE


def test_exact_receiver_preparation_is_recognized(experiment):
    demo = experiment.preparation_demonstration
    assert "exact-stock-receiver" in demo.candidate.source_kinds
    assert demo.assessment.marginal_values[0].exact_receiver_success_delta > 0


def test_stock_supplied_duplicates_are_transparently_recorded(experiment):
    impacts = experiment.assessment_c.deal_now.incoming_impacts
    assert all(isinstance(item.supplies_excavation_duplicate, bool) for item in impacts)
    assert any(item.supplies_excavation_duplicate for item in impacts)


def test_newly_actionable_post_deal_projects_are_measured(experiment):
    transition = experiment.assessment_c.deal_now.actionability
    assert transition is not None
    assert isinstance(transition.newly_actionable_after_deal, tuple)


def test_projects_blocked_by_deal_are_measured(experiment):
    transition = experiment.assessment_c.deal_now.actionability
    assert transition is not None
    assert isinstance(transition.blocked_by_deal, tuple)


def test_timing_economics_never_affect_proof_prunable(experiment):
    for assessment in (
        experiment.assessment_a,
        experiment.assessment_b,
        experiment.assessment_c,
    ):
        assert not assessment.decision.proof_pruning_allowed
        assert not deal_as_economic_project(assessment).proof_pruning_allowed


def test_no_incumbent_production_mode_has_no_cap(experiment):
    result = simulate_deal_counterfactual(
        experiment.checkpoint_c.state,
        experiment.cards,
        spent_cost=23,
        incumbent_cost=None,
    )
    budget = result.incumbent_budget
    assert budget is not None
    assert budget.incumbent_cost is None
    assert budget.improvement_target is None
    assert budget.hard_headroom is None
    assert not budget.proof_prunable


def test_later_incumbent_installation_changes_only_budget(experiment):
    result = simulate_deal_counterfactual(
        experiment.checkpoint_c.state,
        experiment.cards,
        spent_cost=23,
        incumbent_cost=None,
    )
    production = result.incumbent_budget
    installed = production.install_incumbent(172)
    assert installed.lower_bound == production.lower_bound
    assert installed.spent_cost == production.spent_cost
    assert installed.heuristic_remaining_work == production.heuristic_remaining_work
    assert isinstance(experiment.assessment_c.decision.kind, DealTimingDecisionKind)


def test_external_119_never_enters_timing_or_pruning():
    source = inspect.getsource(timing)
    assert "119" not in source


def test_invalid_historical_cost47_49_states_are_never_used():
    combined = inspect.getsource(timing) + inspect.getsource(report)
    assert "cost-47" not in combined.lower()
    assert "cost-49" not in combined.lower()


def test_canonical_future_route_is_guarded_by_full_prospective_freeze(experiment):
    assert experiment.prospective_decisions_frozen
    assert not experiment.canonical_loaded
    with pytest.raises(AssertionError, match="prospective freeze"):
        report.inspect_canonical_after_freeze(
            replace(experiment, prospective_decisions_frozen=False)
        )


def test_canonical_comparison_loads_only_after_freeze(experiment):
    observation = report.inspect_canonical_after_freeze(experiment)
    assert observation.loaded_after_prospective_freeze
    assert observation.corrected_cost == 172
    assert observation.solved


def test_checkpoint_a_reconstruction_is_legal_and_exact(experiment):
    checkpoint = experiment.checkpoint_a
    assert checkpoint.corrected_cost == 6
    assert len(checkpoint.actions) == 6
    assert checkpoint.stock_deals == 0
    assert checkpoint.independent_replay_verified
    assert empty_columns(checkpoint.state)
    assert checkpoint.state.can_deal()


def test_checkpoint_b_reconstruction_is_legal_and_exact(experiment):
    checkpoint = experiment.checkpoint_b
    assert checkpoint.corrected_cost == 11
    assert checkpoint.stock_deals == 1
    assert len(checkpoint.state.stock) == 40
    assert checkpoint.independent_replay_verified


def test_checkpoint_c_cost23_reconstruction_is_exact(experiment):
    checkpoint = experiment.checkpoint_c
    assert checkpoint.corrected_cost == 23
    assert checkpoint.stock_deals == 2
    assert len(checkpoint.state.stock) == 30
    assert len(checkpoint.state.foundations) == 1
    assert sum(len(column.face_down) for column in checkpoint.state.columns) == 32
    assert checkpoint.independent_replay_verified


def test_checkpoint_b_uses_the_exact_second_row(experiment):
    assert experiment.assessment_b.incoming_row == tuple(
        experiment.checkpoint_b.state.stock[-10:]
    )


def test_checkpoint_c_uses_the_exact_third_row(experiment):
    assert experiment.assessment_c.incoming_row == tuple(
        experiment.checkpoint_c.state.stock[-10:]
    )


def test_preparation_horizon_and_cost_are_bounded(experiment):
    for assessment in (
        experiment.assessment_a,
        experiment.assessment_b,
        experiment.assessment_c,
    ):
        assert all(candidate.horizon <= 2 for candidate in assessment.preparations)
        assert all(candidate.corrected_cost <= 8 for candidate in assessment.preparations)


def test_deal_is_exposed_as_first_class_economic_adapter(experiment):
    adapter = deal_as_economic_project(experiment.assessment_c)
    assert adapter.project_id == "deal-next-stock-row"
    assert adapter.immediate_paid_cost == 1
    assert adapter.incoming_row == experiment.assessment_c.incoming_row


def test_every_deal_counterfactual_applies_exactly_one_deal(experiment):
    for assessment in (
        experiment.assessment_a,
        experiment.assessment_b,
        experiment.assessment_c,
    ):
        assert assessment.deal_now.actions.count(("deal",)) == 1
        assert all(item.actions.count(("deal",)) == 1 for item in assessment.prepared_deals)


def test_assessments_freeze_before_any_canonical_observation(experiment):
    for assessment in (
        experiment.assessment_a,
        experiment.assessment_b,
        experiment.assessment_c,
    ):
        assert assessment.prospective_frozen
        assert not assessment.canonical_loaded
        assert len(assessment.prediction_fingerprint) == 64


def test_hard_gate_is_pass_not_strong_pass(experiment):
    assert experiment.verdict == "PASS"
