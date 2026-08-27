from __future__ import annotations

import inspect
import random
import time
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
import spider.planner.campaign_corridor as corridor_module
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.anytime_controller import (
    AnalysisStage,
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    analyze_stage0_state,
    analyze_strategic_state,
    generate_strategic_successors,
    solve_anytime,
)
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    CampaignCorridorStatus,
    realize_campaign_corridor,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def gate_config(**changes) -> AnytimeControllerConfig:
    values = dict(
        wall_clock_limit_s=120.0,
        max_strategic_expansions=30,
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
def gate_result(opening):
    cards, state = opening
    return solve_anytime(state, cards, incumbent=None, config=gate_config())


def _random_state(seed: int = 101):
    cards = [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]
    random.Random(seed).shuffle(cards)
    frozen = tuple(cards)
    return frozen, SpiderState.from_cards(frozen)


def test_01_canonical_172_anchor_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (
        result.valid,
        result.solved,
        result.mobilityware_moves,
        result.explicit_commands,
        result.tableau_moves,
        result.stock_deals,
        result.foundations,
        result.path_hash,
        result.state_hash,
    ) == (
        True,
        True,
        172,
        174,
        169,
        5,
        8,
        "77d169da2538ba8c",
        "4e9861540eac570cb",
    )


def test_02_legal_cost23_anchor_unchanged():
    checkpoint = reconstruct_cost23_checkpoint()
    assert checkpoint.independently_verified
    assert checkpoint.arm.total_cost == checkpoint.action_count == 23
    assert checkpoint.deal_count == 2
    assert checkpoint.foundation_suits == ("s",)
    assert len(checkpoint.state.stock) == 30
    assert checkpoint.face_down_count == 32


def test_03_stage0_analysis_is_cheap_exact_and_proof_safe(opening):
    _cards, state = opening
    snapshot = analyze_stage0_state(state, spent_cost=7, incumbent_cost=None)
    assert snapshot.stage == AnalysisStage.EXACT_CHEAP_FACTS
    assert snapshot.state_key == canonical_state_key(state)
    assert snapshot.face_down_count == 44
    assert snapshot.stock_count == 50
    assert snapshot.foundation_count == 0
    assert snapshot.budget.proof_prunable is False


def test_04_generated_children_enter_frontier_without_stage2(gate_result):
    assert gate_result.telemetry.lazy_children_admitted > 0
    assert gate_result.telemetry.stage2_analyses == 0
    assert gate_result.telemetry.stage0_analyses > gate_result.telemetry.stage1_analyses


def test_05_child_receives_fresh_stage1_before_expansion(gate_result):
    node = gate_result.best_progress_node
    assert node.analysis is not None
    assert node.analysis.stage == AnalysisStage.STRATEGIC_CORE
    assert node.analysis.state_hash == controller._state_hash(node.state)
    assert gate_result.telemetry.stage1_analyses >= 2


def test_06_true_opening_generic_gate_removes_foundation(gate_result):
    node = gate_result.best_progress_node
    assert len(node.state.foundations) == 1
    assert node.g == 21
    assert len(node.actions) == 21
    assert gate_result.strategic_expansions <= 30
    assert gate_result.stop_reason == "first-foundation milestone"


def test_07_foundation_prefix_independently_replays(opening, gate_result):
    _cards, state = opening
    replay = state.clone()
    assert replay_actions(replay, list(gate_result.best_progress_node.actions)) == 21
    assert states_structurally_equal(replay, gate_result.best_progress_node.state)


def test_08_stale_parent_facts_are_not_used_after_deals_or_foundation(gate_result):
    node = gate_result.best_progress_node
    assert node.analysis is not None
    assert node.analysis.measurement.stock_count == 30
    assert node.analysis.measurement.foundation_count == 1
    assert gate_result.telemetry.full_reanalyses_after_deal >= 1
    assert gate_result.telemetry.full_reanalyses_after_foundation == 1


def test_09_analysis_deadline_exposes_monotonic_remaining_budget():
    deadline = SearchDeadline.from_seconds(0.2, analysis_node_limit=10)
    before = deadline.remaining_wall_time
    deadline.consume_nodes(4)
    after = deadline.remaining_wall_time
    assert after <= before
    assert deadline.remaining_analysis_nodes == 6
    assert 0 < deadline.time_slice("x", 1.0) <= before


def test_10_corridor_honors_insufficient_shared_deadline(opening):
    cards, state = opening
    campaign = analyze_foundation_campaigns(state, cards=cards).primary
    deadline = SearchDeadline.from_seconds(0.01)
    result = realize_campaign_corridor(
        state,
        campaign,
        cards,
        config=CampaignCorridorConfig(time_limit_s=1.0),
        deadline=deadline,
    )
    assert result.status == CampaignCorridorStatus.RESOURCE_LIMIT
    assert not result.actions


def test_11_controller_wall_deadline_has_two_second_tolerance():
    cards, state = _random_state()
    config = AnytimeControllerConfig(
        wall_clock_limit_s=0.2,
        max_strategic_expansions=2,
        max_tactical_nodes=100,
        enable_campaign_edges=False,
        enable_campaign_corridors=False,
        enable_expensive_deal_timing=False,
    )
    result = solve_anytime(state, cards, None, config)
    assert result.elapsed_seconds <= 2.2


def test_12_exact_state_analysis_cache_reuses_only_matching_facts(opening):
    cards, state = opening
    config = AnytimeControllerConfig(enable_campaign_corridors=False)
    cache = {}
    telemetry = ControllerTelemetry()
    first = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache, telemetry=telemetry,
    )
    second = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache, telemetry=telemetry,
    )
    assert first.economic is second.economic
    assert telemetry.analysis_cache_hits == 1


def test_13_incumbent_budget_is_refreshed_not_stale_cached(opening):
    cards, state = opening
    config = AnytimeControllerConfig(enable_campaign_corridors=False)
    cache = {}
    first = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache,
    )
    second = analyze_strategic_state(
        state, cards, spent_cost=7, incumbent_cost=172, config=config,
        include_deal_timing=False, analysis_cache=cache,
    )
    assert first.economic is second.economic
    assert first.budget.incumbent_cost is None
    assert second.budget.incumbent_cost == 172 and second.budget.spent_cost == 7


def test_14_precomputed_deal_facts_require_exact_state_identity(opening):
    cards, state = opening
    config = AnytimeControllerConfig(enable_campaign_corridors=False)
    telemetry = ControllerTelemetry()
    initial = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    dealt = state.clone()
    dealt.deal(MW_RULES)
    analyze_strategic_state(
        dealt, cards, spent_cost=1, incumbent_cost=None, config=config,
        include_deal_timing=False, telemetry=telemetry,
        precomputed_economic=initial.economic,
        precomputed_measurement=initial.measurement,
        precomputed_state_key=canonical_state_key(state),
        precomputed_config_fingerprint=controller.analysis_config_fingerprint(config),
    )
    assert telemetry.precomputed_analysis_mismatches == 1


def test_15_lazy_deal_timing_still_retains_first_class_deal(opening):
    cards, state = opening
    config = AnytimeControllerConfig(
        enable_campaign_edges=False,
        enable_campaign_corridors=False,
        enable_expensive_deal_timing=True,
        optional_analysis_minimum_start_s=1.0,
    )
    analysis = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    node = StrategicSearchNode(
        0, state, 0, (), None, None, 0, StrategicCreditLevel.CLEAN,
        analysis, analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
    )
    successors = generate_strategic_successors(
        node, cards, incumbent_cost=None, config=config,
        telemetry=ControllerTelemetry(), actionability_cache={},
        started=time.perf_counter(), deadline=SearchDeadline.from_seconds(0.05),
    )
    assert any(item.kind == controller.StrategicActionKind.RAW_DEAL for item in successors)


def test_16_lazy_economics_never_becomes_proof_pruning():
    source = inspect.getsource(controller.solve_anytime)
    proof_lines = [line.strip() for line in source.splitlines() if "proof_prunable" in line]
    assert proof_lines == [
        "if node.analysis.budget.proof_prunable:",
        "if child.analysis.budget.proof_prunable:",
    ]
    assert "economic" not in " ".join(proof_lines).lower()


def test_17_true_opening_search_has_no_route_or_suit_seed():
    source = inspect.getsource(controller) + inspect.getsource(corridor_module)
    for forbidden in ("preferred six", "cost-11", "cost-23", "Spades", "492515"):
        assert forbidden not in source


def test_18_external_119_is_never_a_production_pruning_constant():
    source = inspect.getsource(controller) + inspect.getsource(corridor_module)
    assert "119" not in source


def test_19_canonical_future_actions_are_unavailable_to_prospective_code():
    source = inspect.getsource(controller) + inspect.getsource(corridor_module)
    assert "parse_moves_file" not in source
    assert "canonical.moves" not in source
    assert "solutions/" not in source


def test_20_exact_tt_lower_g_dominates_regardless_of_corridor_history(opening):
    _cards, state = opening
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 9, heuristic_score="corridor-a")
    assert tt.admit(state, 8, heuristic_score="corridor-b")
    assert not tt.admit(state, 8, heuristic_score="different-history")
    assert tt.best_g(state) == 8
