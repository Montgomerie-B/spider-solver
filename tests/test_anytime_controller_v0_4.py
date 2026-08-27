from __future__ import annotations

import inspect
import random
import time
from dataclasses import fields, replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
import spider.planner.residual_campaign as residual_module
import spider.planner.diagnostics.anytime_whole_game_controller_v0_4_report as diagnostic
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.anytime_controller import (
    AnalysisStage,
    AnytimeControllerConfig,
    StrategicTranspositionTable,
    solve_anytime,
    verify_complete_candidate,
)
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    CampaignCorridorStatus,
    realize_campaign_corridor,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.economic_project_realizer import measure_structural_state
from spider.planner.economic_projects import analyze_economic_projects
from spider.planner.residual_campaign import (
    CheckpointDimension,
    DealPurpose,
    ResidualLaneKind,
    analyze_residual_campaign,
    assess_stock_opportunity,
    build_foundation_checkpoint_profile,
    residual_investment_accounting,
    retain_foundation_checkpoint_portfolio,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def gate_config(**changes) -> AnytimeControllerConfig:
    values = dict(
        wall_clock_limit_s=40.0,
        max_strategic_expansions=5,
        max_tactical_nodes=50_000,
        max_frontier_size=128,
        max_successors_per_expansion=8,
        enable_campaign_corridors=True,
        corridor_config=CampaignCorridorConfig(
            max_epoch_transitions=2,
            max_added_cost=24,
            max_nodes=30_000,
            time_limit_s=12.0,
            beam_width=256,
            max_lanes=2,
            max_source_combinations=64,
        ),
        stop_after_first_foundation=True,
    )
    values.update(changes)
    return AnytimeControllerConfig(**values)


@pytest.fixture(scope="module")
def opening():
    cards = tuple(load_deal(DEAL))
    return cards, SpiderState.from_cards(cards)


@pytest.fixture(scope="module")
def cost21(opening):
    cards, state = opening
    result = solve_anytime(state, cards, None, gate_config())
    node = result.best_progress_node
    assert node.g == 21 and len(node.state.foundations) == 1
    return cards, state, result, node


@pytest.fixture(scope="module")
def cost23():
    return reconstruct_cost23_checkpoint()


def _random_deal(seed: int):
    cards = [
        Card(suit, rank)
        for suit in "cdhs"
        for rank in range(1, 14)
        for _ in range(2)
    ]
    random.Random(seed).shuffle(cards)
    frozen = tuple(cards)
    return frozen, SpiderState.from_cards(frozen)


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_all_three_regression_anchors_are_exact(cost21, cost23):
    canonical = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves) == (172, 174, 169)
    assert (canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash) == (5, 8, "77d169da2538ba8c", "4e9861540eac570cb")
    _cards, opening, result, node = cost21
    assert controller._action_path_hash(node.actions) == "924bfd20deac96af"
    assert format(zobrist(node.state), "x") == "b7522950ea41ad9a"
    assert replay_actions(opening.clone(), list(node.actions)) == 21
    assert cost23.independently_verified and cost23.arm.total_cost == 23
    assert cost23.face_down_count == 32 and len(cost23.state.stock) == 30


def test_03_residual_conversion_accepts_arbitrary_post_foundation_state(cost21):
    cards, _opening, _result, node = cost21
    assessment = node.analysis.residual
    assert assessment.checkpoint.state_key == canonical_state_key(node.state)
    assert assessment.checkpoint.foundations == 1
    assert assessment.lanes


def test_04_residual_source_contains_no_benchmark_suit_or_column_constants():
    source = inspect.getsource(residual_module)
    for forbidden in ("492515", "Spades", "cost-21", "cost-23", "column 4"):
        assert forbidden not in source


def test_05_foundation_removal_triggers_complete_residual_reanalysis(cost21):
    _cards, _opening, result, node = cost21
    assert result.telemetry.full_reanalyses_after_foundation == 1
    resource_event = result.telemetry.foundation_resource_timeline[0]
    assert resource_event[0:2] == (21, 1)
    assert resource_event[2] >= 0.0 and resource_event[3] >= 1
    assert resource_event[4] >= 0 and resource_event[5]
    assert node.analysis.residual.checkpoint.g == node.g
    assert node.analysis.residual.checkpoint.foundation_suits == ("s",)


def test_06_next_foundation_corridor_target_is_generic(cost21):
    _cards, _opening, _result, node = cost21
    assert all(lane.target_foundations == 2 for lane in node.analysis.residual.lanes)


def test_07_next_foundation_terminal_milestone_requires_count_increase(cost21):
    _cards, _opening, _result, node = cost21
    lane = next(lane for lane in node.analysis.residual.lanes if lane.corridor_lane)
    milestone = lane.corridor_lane.corridor.final_milestone
    assert not milestone.is_satisfied(node.state, None)
    assert milestone.target_foundations == 2


def test_08_current_epoch_conversion_exists_while_deal_is_legal(cost21):
    _cards, _opening, _result, node = cost21
    kinds = {lane.kind for lane in node.analysis.residual.lanes}
    assert node.state.can_deal(MW_RULES)
    assert ResidualLaneKind.CURRENT_EPOCH_REMOVAL in kinds


def test_09_controller_does_not_require_move_exhaustion_before_deal(cost21):
    _cards, _opening, _result, node = cost21
    assert node.state.enumerate_moves()
    assert any(lane.kind == ResidualLaneKind.DEAL_NOW_UNLOCK for lane in node.analysis.residual.lanes)


def test_10_deal_remains_first_class_under_stock_preservation(cost21):
    _cards, _opening, _result, node = cost21
    lane = next(lane for lane in node.analysis.residual.lanes if lane.kind == ResidualLaneKind.DEAL_NOW_UNLOCK)
    assert lane.proof_pruning_allowed is False


def test_11_stock_epoch_has_no_intrinsic_positive_progress_value():
    names = {item.name for item in fields(controller.StrategicProgressComponents)}
    assert "stock_count" not in names and "stock_epoch" not in names


def test_12_deal_escape_only_classification_is_possible(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    before = replace(profile, current_epoch_actionable_high_value_projects=("live",))
    after = replace(before, stock_remaining=before.stock_remaining - 10)
    value = assess_stock_opportunity(before, after, impacts=())
    assert value.purpose == DealPurpose.ESCAPE_ONLY


def test_13_deal_strategic_unlock_classification_is_possible(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    after = replace(
        profile,
        stock_remaining=profile.stock_remaining - 10,
        current_epoch_actionable_high_value_projects=(
            *profile.current_epoch_actionable_high_value_projects,
            "new-project",
        ),
    )
    value = assess_stock_opportunity(profile, after, impacts=())
    assert value.purpose == DealPurpose.STRATEGIC_UNLOCK
    assert value.blocked_high_value_work_unlocked == ("new-project",)


def test_14_exact_next_row_components_are_transparent(cost21):
    previews = cost21[3].analysis.residual.checkpoint.exact_next_row_impact
    assert len(previews) == 10
    assert all(item.card and item.column in range(10) for item in previews)
    assert {item.same_suit_receiver for item in previews} <= {True, False}


def test_15_current_opportunities_blocked_by_deal_are_measured(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    before = replace(profile, current_epoch_actionable_high_value_projects=("a", "b"))
    after = replace(before, stock_remaining=20, current_epoch_actionable_high_value_projects=("b",))
    value = assess_stock_opportunity(before, after, impacts=())
    assert value.current_epoch_projects_blocked == ("a",)


def test_16_current_opportunities_enabled_by_deal_are_measured(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    before = replace(profile, current_epoch_actionable_high_value_projects=())
    after = replace(before, stock_remaining=20, current_epoch_actionable_high_value_projects=("a",))
    value = assess_stock_opportunity(before, after, impacts=())
    assert value.blocked_high_value_work_unlocked == ("a",)


def test_17_no_fixed_arbitrary_deal_penalty_controls_decision():
    source = inspect.getsource(residual_module.assess_stock_opportunity)
    assert "deal_penalty" not in source and "- 10" not in source


def test_18_distinct_equal_foundation_states_are_not_tt_conflated(cost21):
    node = cost21[3]
    moved = node.state.clone()
    action = moved.enumerate_moves()[0]
    moved.move(*action)
    tt = StrategicTranspositionTable()
    assert tt.admit(node.state, 21)
    assert tt.admit(moved, 22)
    assert len(tt) == 2


def test_19_higher_g_distinct_state_survives_checkpoint_diversity(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    moved = cost21[3].state.clone()
    moved.move(*moved.enumerate_moves()[0])
    dearer = replace(
        profile,
        state_key=canonical_state_key(moved),
        g=profile.g + 2,
        face_down_count=profile.face_down_count - 1,
    )
    portfolio = retain_foundation_checkpoint_portfolio((profile, dearer), maximum=6)
    assert {item.state_key for item in portfolio.profiles} == {profile.state_key, dearer.state_key}


def test_20_higher_g_identical_state_is_suppressed(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    portfolio = retain_foundation_checkpoint_portfolio((profile, replace(profile, g=23)), maximum=6)
    assert portfolio.profiles == (profile,)
    assert portfolio.exact_state_suppressions == 1


def test_21_foundation_checkpoint_profile_is_deterministic(cost21):
    cards, _opening, _result, node = cost21
    first = build_foundation_checkpoint_profile(node.state, g=node.g, analysis=node.analysis.economic, measurement=node.analysis.measurement)
    second = build_foundation_checkpoint_profile(node.state, g=node.g, analysis=node.analysis.economic, measurement=node.analysis.measurement)
    assert first == second


def test_22_pareto_dimension_retention_is_bounded_and_deterministic(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    variants = tuple(replace(profile, state_key=replace(profile.state_key, stock=profile.state_key.stock[: max(0, len(profile.state_key.stock) - i)]), g=profile.g + i) for i in range(5))
    first = retain_foundation_checkpoint_portfolio(variants, maximum=3)
    second = retain_foundation_checkpoint_portfolio(reversed(variants), maximum=3)
    assert len(first.profiles) == 3 and first.profiles == second.profiles


def test_23_cheapest_checkpoint_is_not_the_only_retained_state(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    alternate = replace(profile, state_key=replace(profile.state_key, stock=profile.state_key.stock[:-1]), g=profile.g + 2, total_campaign_must_burden=profile.total_campaign_must_burden - 1)
    portfolio = retain_foundation_checkpoint_portfolio((profile, alternate), maximum=6)
    assert len(portfolio.profiles) == 2


def test_24_near_removal_checkpoint_receives_protected_dimension(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    readiness = replace(profile.next_foundation_readiness[0], must_dependencies_remaining=1, bounded_removal_macro_available=True)
    near = replace(profile, state_key=replace(profile.state_key, stock=profile.state_key.stock[:-2]), g=profile.g + 3, next_foundation_readiness=(readiness,), near_removal_campaigns=(readiness.campaign_label,))
    portfolio = retain_foundation_checkpoint_portfolio((profile, near), maximum=2)
    represented = dict(portfolio.represented_dimensions)
    assert represented[CheckpointDimension.BEST_NEXT_FOUNDATION_READINESS] == near.state_key


def test_25_residual_investment_includes_paid_cost(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    after = replace(profile, g=profile.g + 7)
    assert residual_investment_accounting(profile, after).paid_cost == 7


def test_26_residual_investment_includes_stock_rows(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    after = replace(profile, stock_remaining=profile.stock_remaining - 20)
    assert residual_investment_accounting(profile, after).stock_rows_consumed == 2


def test_27_must_reduction_is_not_foundation_completion(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    after = replace(profile, total_campaign_must_burden=profile.total_campaign_must_burden - 5)
    accounting = residual_investment_accounting(profile, after)
    assert accounting.must_burden_removed == 5
    assert accounting.resulting_next_foundation_cost is None


def test_28_same_suit_mass_gain_is_not_foundation_completion(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    after = replace(profile, same_suit_run_mass=profile.same_suit_run_mass + 10)
    assert residual_investment_accounting(profile, after).resulting_next_foundation_cost is None


def test_29_corridor_replans_campaign_after_foundation(cost21):
    edge = cost21[3].incoming_edge
    assert edge is not None and edge.corridor_result is not None
    assert edge.corridor_result.assessment.alternatives_remaining


def test_30_corridor_can_switch_physical_source_copy(cost21):
    edge = cost21[3].incoming_edge
    assert edge.corridor_result.assessment.source_copy_switched
    assert any(step.revalidation == CampaignCorridorStatus.SWITCH_SOURCE_COPY for step in edge.corridor_result.steps)


def test_31_deal_opportunity_has_no_proof_authority(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    value = assess_stock_opportunity(profile, replace(profile, stock_remaining=20), impacts=())
    assert value.proof_pruning_allowed is False


def test_32_checkpoint_diversity_has_no_proof_authority(cost21):
    profile = cost21[3].analysis.residual.checkpoint
    assert retain_foundation_checkpoint_portfolio((profile,), maximum=2).proof_pruning_allowed is False


def test_33_stage_zero_one_two_semantics_remain_valid(cost21):
    result = cost21[2]
    assert result.best_progress_node.stage0.stage == AnalysisStage.EXACT_CHEAP_FACTS
    assert result.best_progress_node.analysis.stage in (AnalysisStage.STRATEGIC_CORE, AnalysisStage.EXPENSIVE_OPTIONAL)
    assert result.telemetry.stage0_analyses >= result.telemetry.stage1_analyses


def test_34_deadline_propagates_through_residual_corridor(opening):
    cards, state = opening
    economic = analyze_economic_projects(state, cards=cards)
    campaign = economic.campaign_portfolio.primary
    result = realize_campaign_corridor(state, campaign, cards, deadline=SearchDeadline.from_seconds(0.01))
    assert result.status == CampaignCorridorStatus.RESOURCE_LIMIT


def test_35_exact_analysis_reuse_remains_fingerprint_safe():
    source = inspect.getsource(controller.analyze_strategic_state)
    assert "cache_key = (state_key, fingerprint)" in source
    assert "precomputed_config_fingerprint == fingerprint" in source


def test_36_canonical_future_actions_are_unavailable_prospectively():
    source = inspect.getsource(controller) + inspect.getsource(residual_module)
    for forbidden in ("parse_moves_file", "canonical.moves", "solutions/"):
        assert forbidden not in source


def test_37_external_119_never_enters_pruning():
    source = inspect.getsource(controller) + inspect.getsource(residual_module)
    assert "119" not in source


def test_38_true_opening_controller_accepts_no_seeded_prefix_parameter():
    parameters = inspect.signature(solve_anytime).parameters
    assert tuple(parameters) == ("initial_state", "cards", "incumbent", "config")
    assert not any("seed" in name or "prefix" in name for name in parameters)
    gate_parameters = inspect.signature(diagnostic._gate_c_config).parameters
    assert tuple(gate_parameters) == ("seconds",)
    source = inspect.getsource(diagnostic._gate_c_config)
    assert "target_foundation_count=2" in source
    for forbidden_anchor in ("cost21", "cost23", "machine_node", "independent.state"):
        assert forbidden_anchor not in source


def test_39_unseen_deals_exercise_residual_apis_generically():
    labels = []
    for seed in (31, 47):
        cards, state = _random_deal(seed)
        economic = analyze_economic_projects(state, cards=cards, campaign_source_combination_limit=32)
        measurement = measure_structural_state(state, cards=cards, analysis=economic)
        assessment = analyze_residual_campaign(state, cards, g=0, analysis=economic, measurement=measurement, corridor_config=CampaignCorridorConfig(max_source_combinations=32), maximum_lanes=3)
        labels.append(tuple(lane.campaign_label for lane in assessment.lanes if lane.campaign_label))
        assert assessment.checkpoint.state_key == canonical_state_key(state)
    assert labels[0] != labels[1]


def test_40_solution_acceptance_remains_replay_gated(opening):
    _cards, state = opening
    assert verify_complete_candidate(state, state, (), expected_cost=0, expansions=0, elapsed_seconds=0.0) is None
