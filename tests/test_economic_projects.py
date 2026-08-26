"""Economic-project, reveal-value, and incumbent-budget gates."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.planner import economic_projects as economics
from spider.planner import incumbent_budget as budgets
from spider.planner.diagnostics import economic_project_analysis_report as report
from spider.planner.economic_projects import (
    EconomicFrontierTier,
    EconomicProjectKind,
    EvidenceLevel,
    RevealValueClass,
    build_economic_frontier,
    economic_project_dominates,
    empty_project_benefit,
    empty_project_cost,
    empty_project_debt,
    hard,
    heuristic,
    make_economic_project,
)
from spider.planner.incumbent_budget import update_heuristic_remaining_work
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="module")
def frozen():
    return report.freeze_prospective_economics()


def _unexplained_park():
    cost = replace(
        empty_project_cost(),
        immediate_paid_cost=hard(1, "one legal paid park"),
        mixed_suit_park_debt=heuristic(1, "one mixed boundary"),
        expected_future_rehandling=heuristic(1, "park must later exit"),
    )
    debt = replace(
        empty_project_debt(),
        rework_actions_introduced=heuristic(1, "one rehandling action"),
        mixed_boundaries_created=hard(1, "one mixed boundary created"),
        projected_rehandling_cost=heuristic(1, "ordering-only debt"),
        future_exit_route="unresolved receiver or workspace required",
        exit_route_bounded=False,
    )
    return make_economic_project(
        project_id="synthetic-unexplained-park",
        kind=EconomicProjectKind.TEMPORARY_REWORK,
        description="unnecessary mixed-suit park",
        earliest_useful_epoch=0,
        cost=cost,
        debt=debt,
        confidence="LOW",
    )


def _permanent_project():
    benefit = replace(
        empty_project_benefit(),
        stable_same_suit_joins=hard(5, "one permanent same-suit boundary"),
        same_suit_run_mass=hard(2, "two-card permanent band"),
    )
    cost = replace(
        empty_project_cost(),
        immediate_paid_cost=hard(1, "one legal paid move"),
    )
    return make_economic_project(
        project_id="synthetic-permanent-join",
        kind=EconomicProjectKind.PERMANENT_JOIN,
        description="permanent same-suit join",
        earliest_useful_epoch=0,
        cost=cost,
        benefit=benefit,
        confidence="HIGH",
    )


def test_cost23_legal_checkpoint_reconstructs_exactly(frozen):
    checkpoint = frozen.checkpoint
    assert checkpoint.arm.total_cost == 23
    assert checkpoint.action_count == 23
    assert checkpoint.deal_count == 2
    assert len(checkpoint.state.stock) == 30
    assert checkpoint.foundation_suits == ("s",)
    assert checkpoint.face_down_count == 32
    assert checkpoint.independently_verified
    assert states_structurally_equal(checkpoint.state, checkpoint.replay_state)


def test_information_value_of_every_reveal_is_zero(frozen):
    assert frozen.analysis.reveal_values
    assert {value.information_gain for value in frozen.analysis.reveal_values} == {0.0}


def test_critical_reveal_outranks_cheap_replaceable_reveal(frozen):
    values = frozen.analysis.reveal_values
    cheap = min(
        (
            value
            for value in values
            if value.reveal_depth == 1
            and value.classification
            in (
                RevealValueClass.REPLACEABLE_BY_STOCK,
                RevealValueClass.REPLACEABLE_BY_DUPLICATE,
                RevealValueClass.LOW_CURRENT_VALUE,
            )
        ),
        key=lambda value: value.structural_value,
    )
    critical = max(
        (value for value in values if value.classification == RevealValueClass.CRITICAL_NOW),
        key=lambda value: value.structural_value,
    )
    assert critical.reveal_depth >= cheap.reveal_depth
    assert critical.structural_value > cheap.structural_value


def test_stock_supplied_duplicate_reduces_reveal_urgency(frozen):
    supplied = [
        value
        for value in frozen.analysis.reveal_values
        if value.stock_copy_epochs
        and value.classification == RevealValueClass.REPLACEABLE_BY_STOCK
    ]
    assert supplied
    assert all(value.substitute_available for value in supplied)
    assert all(
        any("reduces current urgency" in reason for reason in value.reasons)
        for value in supplied
    )


def test_permanent_join_outranks_comparable_unnecessary_mixed_park():
    permanent = _permanent_project()
    park = _unexplained_park()
    frontier = build_economic_frontier((park, permanent))
    assert frontier.ordered_projects[0] == permanent
    relation = economic_project_dominates(permanent, park)
    assert relation is not None
    assert relation.proof_pruning_allowed is False


def test_rework_can_outrank_clean_move_when_bounded_return_exceeds_debt():
    clean, rework = report.synthetic_rework_pot_of_gold_example()
    assert rework.rework_investment is not None
    assert rework.rework_investment.worthwhile
    assert rework.rework_investment.net_economic_value > 0
    assert build_economic_frontier((clean, rework)).ordered_projects[0] == rework


def test_unexplained_park_does_not_outrank_permanent_move():
    permanent = _permanent_project()
    park = _unexplained_park()
    assert park.assessment.frontier_tier == EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED
    assert permanent.assessment.frontier_tier == EconomicFrontierTier.STRUCTURALLY_DOMINANT
    assert build_economic_frontier((park, permanent)).ordered_projects[0] == permanent


def test_project_costs_distinguish_hard_bounded_and_heuristic_evidence():
    _clean, rework = report.synthetic_rework_pot_of_gold_example()
    levels = {amount.evidence for _name, amount in rework.cost.components}
    assert levels == {
        EvidenceLevel.HARD_FACT,
        EvidenceLevel.BOUNDED_FACT,
        EvidenceLevel.HEURISTIC_ESTIMATE,
    }


def test_economic_frontier_is_deterministic(frozen):
    first = tuple(project.project_id for project in build_economic_frontier(frozen.analysis.projects).ordered_projects)
    second = tuple(project.project_id for project in build_economic_frontier(tuple(reversed(frozen.analysis.projects))).ordered_projects)
    assert first == second == frozen.prospective_project_order


def test_dominance_is_metadata_not_proof_pruning(frozen):
    assert frozen.analysis.frontier.dominance
    assert not frozen.analysis.frontier.proof_pruning_allowed
    assert all(
        relation.suppression_metadata_only and not relation.proof_pruning_allowed
        for relation in frozen.analysis.frontier.dominance
    )
    assert len(frozen.analysis.frontier.ordered_projects) == len(frozen.analysis.projects)


def test_verified_incumbent_yields_one_lower_target(frozen):
    budget = frozen.research_budget
    assert budget.incumbent_cost == 172
    assert budget.improvement_target == 171


def test_no_incumbent_disables_incumbent_proof_pruning(frozen):
    budget = frozen.production_budget
    assert budget.incumbent_cost is None
    assert budget.improvement_target is None
    assert budget.hard_headroom is None
    assert budget.heuristic_economic_slack is None
    assert budget.can_improve_incumbent
    assert not budget.proof_prunable


def test_incumbent_can_be_installed_later_and_tightens_budget(frozen):
    before = frozen.production_budget
    after = before.install_incumbent(60)
    assert before.hard_headroom is None
    assert after.improvement_target == 59
    assert after.hard_headroom == 59 - after.hard_min_total
    assert after.lower_bound is before.lower_bound


def test_admissible_lower_bound_uses_correct_safe_formula(frozen):
    budget = frozen.research_budget
    assert budget.h_deals == 3
    assert budget.h_reveal_paid == 1
    assert budget.admissible_remaining_lower_bound == 4
    assert budget.hard_min_total == 27
    assert budget.hard_headroom == 144


def test_withdrawn_face_down_plus_deals_is_absent_from_proof_total(frozen):
    lower = frozen.research_budget.lower_bound
    admissible = [component for component in lower.components if component.admissible]
    assert lower.h_naive_face_down_plus_deals == 35
    assert all(component.name != "h_naive_face_down_plus_deals" for component in admissible)
    assert lower.h_admissible != lower.h_naive_face_down_plus_deals


def test_heuristic_remaining_work_never_enters_proof_prunable(frozen):
    original = frozen.research_budget
    huge = update_heuristic_remaining_work(original, 1_000_000)
    assert huge.hard_min_total == original.hard_min_total
    assert huge.proof_prunable == original.proof_prunable
    assert huge.heuristic_economic_slack != original.heuristic_economic_slack


def test_external_leaderboard_context_never_enters_generic_pruning():
    generic_source = inspect.getsource(economics) + inspect.getsource(budgets)
    assert "119" not in generic_source
    assert "leaderboard" not in generic_source.lower()


def test_lifecycle_and_project_debt_remain_ordering_only(frozen):
    assert all(not project.debt.proof_pruning_allowed for project in frozen.analysis.projects)
    assert all(not project.assessment.proof_pruning_allowed for project in frozen.analysis.projects)
    clean, rework = report.synthetic_rework_pot_of_gold_example()
    assert rework.rework_investment is not None
    assert not rework.rework_investment.proof_pruning_allowed


def test_generic_production_code_contains_no_benchmark_constants():
    source = inspect.getsource(economics) + inspect.getsource(budgets)
    for token in (
        "4925153",
        "cost-23",
        "canonical.moves",
        "qc -> kc",
        "(5, 4, 1)",
        "172",
    ):
        assert token not in source.lower()


def test_cost23_analysis_takes_no_deal3_and_mutates_no_checkpoint(frozen):
    checkpoint = frozen.checkpoint
    assert checkpoint.no_deal3
    assert frozen.analysis.facts.current_epoch == 2
    assert frozen.analysis.facts.stock_remaining == 30
    assert len(checkpoint.state.stock) == 30
    assert len(checkpoint.state.foundations) == 1
    assert states_structurally_equal(checkpoint.state, checkpoint.replay_state)


def test_invalid_historical_cost47_and_cost49_fixtures_are_never_used():
    source = inspect.getsource(economics) + inspect.getsource(budgets) + inspect.getsource(report)
    assert "cost-47" not in source.lower()
    assert "cost-49" not in source.lower()
    assert "post-command-14" not in source.lower()


def test_portfolio_is_meaningfully_nonflat_and_retains_tier4(frozen):
    frontier = frozen.analysis.frontier
    scores = {round(project.assessment.net_economic_value, 6) for project in frontier.ordered_projects}
    tiers = {project.assessment.frontier_tier for project in frontier.ordered_projects}
    assert len(scores) > 4
    assert len(tiers) >= 3
    assert frontier.retained_unexplained
    assert set(frontier.retained_unexplained) <= {
        project.project_id for project in frontier.ordered_projects
    }


def test_campaign_primary_is_not_forced_to_top_economic_project(frozen):
    primary = frozen.analysis.campaign_portfolio.primary
    assert primary is not None
    top = frozen.analysis.frontier.ordered_projects[0]
    assert top.project_id != f"campaign-{primary.label.lower()}"


def test_prospective_analysis_freezes_before_canonical_is_loaded(frozen):
    assert frozen.prospective_frozen
    assert not frozen.canonical_loaded
    assert frozen.prospective_project_order


def test_canonical_is_replayed_only_through_post_freeze_api(frozen):
    observation = report.inspect_canonical_after_freeze(frozen)
    assert observation.loaded_after_freeze
    assert observation.corrected_cost == 172
    assert observation.solved
    assert observation.stable_joins > 0
    assert observation.projected_lifecycle_debt > 0
