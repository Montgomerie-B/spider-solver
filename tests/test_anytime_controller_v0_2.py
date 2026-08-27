from __future__ import annotations

import inspect
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest

import spider.planner.anytime_controller as controller
from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.planner.anytime_controller import (
    ActionabilityCacheKey,
    ActionabilityTier,
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicProgressComponents,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    StructuralProgressDelta,
    _better_progress,
    _foundation_successors,
    _node_priority,
    _project_probe_schedule_key,
    actionability_tier_for_credit,
    analysis_config_fingerprint,
    analyze_strategic_state,
    freeze_active_rule_profile,
    generate_strategic_successors,
    normalized_actionability_resource,
    solve_anytime,
    strategic_progress_order_key,
    structural_progress_delta,
)
from spider.metrics import replay_actions
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.economic_project_realizer import (
    EconomicProjectRealizationStatus,
    ProjectActionability,
    project_predicate,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


def small_config(**changes) -> AnytimeControllerConfig:
    base = AnytimeControllerConfig(
        wall_clock_limit_s=8,
        max_strategic_expansions=1,
        max_tactical_nodes=2_000,
        max_frontier_size=50,
        max_credit_level=StrategicCreditLevel.CLEAN,
        campaign_source_combination_limit=4,
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_actionability_probes_per_expansion=1,
        max_actionability_nodes_per_expansion=512,
        max_actionability_time_s_per_expansion=1.0,
        max_total_actionability_nodes=10_000,
        max_bounded_projects_per_expansion=1,
        max_trace_entries=4,
        max_timeline_entries=4,
    )
    return replace(base, **changes)


def standard_cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def one_move_solution_state() -> SpiderState:
    foundations = [
        [Card(suit, rank) for rank in range(13, 0, -1)]
        for suit in "cdh"
        for _ in range(2)
    ]
    foundations.append([Card("s", rank) for rank in range(13, 0, -1)])
    columns = [
        Column([], [Card("s", rank) for rank in range(13, 1, -1)]),
        Column([], [Card("s", 1)]),
    ] + [Column([], []) for _ in range(8)]
    return SpiderState(columns, [], foundations)


@pytest.fixture(scope="module")
def benchmark():
    cards = load_deal(DEAL)
    state = SpiderState.from_cards(cards)
    config = small_config(wall_clock_limit_s=20)
    analysis = analyze_strategic_state(
        state,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
    )
    node = StrategicSearchNode(
        0,
        state,
        0,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        analysis,
    )
    return cards, state, config, analysis, node


def positive_node(benchmark) -> StrategicSearchNode:
    return replace(benchmark[4], credit_level=StrategicCreditLevel.POSITIVE_INVESTMENT)


def install_miss_probe(monkeypatch, calls: list[str], *, nodes: int = 1) -> None:
    def miss(state, project, *, config):
        predicate, _reason = project_predicate(state, project)
        calls.append(project.project_id)
        return ProjectActionability(
            project.project_id,
            False,
            predicate,
            EconomicProjectRealizationStatus.NOT_ACTIONABLE_CURRENT_EPOCH,
            None,
            (),
            nodes,
            config,
            "bounded tier miss",
        )

    monkeypatch.setattr(controller, "probe_project_actionability", miss)


def make_edge(kind: StrategicActionKind, state: SpiderState, delta=None) -> StrategicSuccessor:
    return StrategicSuccessor(
        kind,
        "deal_timing" if kind != StrategicActionKind.ECONOMIC_PROJECT else "other",
        kind.value,
        (),
        0,
        state.clone(),
        StrategicCreditLevel.CLEAN,
        0,
        0,
        0,
        True,
        False,
        (),
        progress_delta=delta,
    )


def make_priority_node(
    benchmark,
    *,
    node_id: int,
    progress: StrategicProgressComponents,
    state: SpiderState | None = None,
    edge: StrategicSuccessor | None = None,
) -> StrategicSearchNode:
    base = benchmark[4]
    return replace(
        base,
        node_id=node_id,
        state=(state or base.state).clone(),
        incoming_edge=edge,
        analysis=replace(base.analysis, progress=progress),
        g=progress.paid_cost,
    )


def test_01_active_profile_requires_unrestricted_deal(benchmark):
    cards, state, *_ = benchmark
    preflight = freeze_active_rule_profile(state, cards)
    assert preflight.passed and preflight.profile.can_deal_into_empty
    assert MW_RULES.can_deal_into_empty is True


def test_02_canonical_rule_anchor_is_exact():
    result = validate_solution("4925153", CANONICAL)
    assert result.valid and result.solved
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)
    assert (result.stock_deals, result.foundations) == (5, 8)
    assert (result.path_hash, result.state_hash) == ("77d169da2538ba8c", "4e9861540eac570cb")


def test_03_cost23_rule_anchor_is_exact():
    checkpoint = reconstruct_cost23_checkpoint()
    assert checkpoint.independently_verified
    assert (checkpoint.arm.total_cost, checkpoint.action_count, checkpoint.deal_count) == (23, 23, 2)
    assert (checkpoint.foundation_suits, len(checkpoint.state.stock), checkpoint.face_down_count) == (("s",), 30, 32)


def test_04_probe_quota_is_independent_per_expansion(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls)
    cards, _state, config, *_ = benchmark
    telemetry = ControllerTelemetry()
    generate_strategic_successors(
        positive_node(benchmark), cards, incumbent_cost=None, config=config,
        telemetry=telemetry, actionability_cache={}, started=time.perf_counter(),
    )
    assert len(calls) == telemetry.actionability_probes_attempted == 1
    assert telemetry.actionability_probe_budget_exhausted == 1


def test_05_probe_exhaustion_preserves_direct_and_deal_successors(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls)
    cards, _state, config, *_ = benchmark
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        positive_node(benchmark), cards, incumbent_cost=None, config=config,
        telemetry=telemetry, actionability_cache={}, started=time.perf_counter(),
    )
    assert any(item.kind == StrategicActionKind.ECONOMIC_PROJECT for item in successors)
    assert any(item.kind in (StrategicActionKind.DEAL_NOW, StrategicActionKind.PREPARE_THEN_DEAL) for item in successors)


def test_06_failed_probes_do_not_consume_tactical_budget(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls, nodes=256)
    cards, _state, config, *_ = benchmark
    telemetry = ControllerTelemetry()
    generate_strategic_successors(
        positive_node(benchmark), cards, incumbent_cost=None, config=config,
        telemetry=telemetry, actionability_cache={}, started=time.perf_counter(),
    )
    assert telemetry.actionability_probe_nodes == 256
    assert telemetry.tactical_nodes == 0


def test_07_normalized_tiers_are_deterministic():
    a = small_config(tactical_nodes_per_project=9_999)
    b = small_config(tactical_nodes_per_project=17)
    for tier in ActionabilityTier:
        assert normalized_actionability_resource(a, tier) == normalized_actionability_resource(b, tier)
    assert [actionability_tier_for_credit(StrategicCreditLevel(i)) for i in range(5)] == [
        None, ActionabilityTier.SHALLOW, ActionabilityTier.MODEST,
        ActionabilityTier.BROAD, ActionabilityTier.BROAD,
    ]


def test_08_exact_state_project_tier_cache_suppresses_duplicate_probe(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls, nodes=256)
    cards, _state, config, *_ = benchmark
    node = positive_node(benchmark)
    cache: dict[ActionabilityCacheKey, ProjectActionability] = {}
    telemetry = ControllerTelemetry()
    for _ in range(2):
        generate_strategic_successors(
            node, cards, incumbent_cost=None, config=config, telemetry=telemetry,
            actionability_cache=cache, started=time.perf_counter(),
        )
    assert calls.count(calls[0]) == 1
    assert telemetry.actionability_cache_hits >= 1


def test_09_broader_tier_retries_after_narrower_miss(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls)
    cards, _state, config, *_ = benchmark
    config = replace(config, max_actionability_nodes_per_expansion=1_000)
    cache: dict[ActionabilityCacheKey, ProjectActionability] = {}
    telemetry = ControllerTelemetry()
    generate_strategic_successors(
        positive_node(benchmark), cards, incumbent_cost=None, config=config,
        telemetry=telemetry, actionability_cache=cache, started=time.perf_counter(),
    )
    broad = replace(positive_node(benchmark), credit_level=StrategicCreditLevel.SPECULATIVE)
    generate_strategic_successors(
        broad, cards, incumbent_cost=None, config=config, telemetry=telemetry,
        actionability_cache=cache, started=time.perf_counter(),
    )
    assert calls.count(calls[0]) == 2
    assert telemetry.actionability_tier_escalations >= 1


def test_10_direct_actionability_bypasses_probe_search(benchmark, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("direct action launched bounded probe")

    monkeypatch.setattr(controller, "probe_project_actionability", forbidden)
    cards, _state, config, *_ = benchmark
    successors = generate_strategic_successors(
        benchmark[4], cards, incumbent_cost=None, config=config,
        telemetry=ControllerTelemetry(), actionability_cache={}, started=time.perf_counter(),
    )
    assert any(item.kind == StrategicActionKind.ECONOMIC_PROJECT for item in successors)


def test_11_value_actionability_and_realization_are_distinct(benchmark):
    project = next(
        item for item in benchmark[3].economic.frontier.ordered_projects
        if item.action is None and project_predicate(benchmark[1], item)[0] is not None
    )
    value_before = project.assessment
    result = controller.probe_project_actionability(
        benchmark[1], project,
        config=normalized_actionability_resource(benchmark[2], ActionabilityTier.SHALLOW),
    )
    assert project.assessment == value_before
    assert isinstance(result, ProjectActionability)
    assert "realize_economic_project" not in inspect.getsource(controller.probe_project_actionability)


def test_12_stock_epoch_is_absent_from_progress_key(benchmark):
    progress = benchmark[3].progress
    early = make_priority_node(benchmark, node_id=10, progress=progress)
    empty_stock = benchmark[1].clone()
    empty_stock.stock.clear()
    late = make_priority_node(benchmark, node_id=11, progress=progress, state=empty_stock)
    assert strategic_progress_order_key(early) == strategic_progress_order_key(late)


def test_13_stock_empty_zero_foundation_disaster_is_not_preferred(benchmark):
    cards, state, config, _analysis, root = benchmark
    empty_stock = state.clone()
    for _ in range(5):
        empty_stock.deal(MW_RULES)
    late_analysis = analyze_strategic_state(
        empty_stock,
        cards,
        spent_cost=5,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    late = replace(root, node_id=21, state=empty_stock, g=5, analysis=late_analysis)
    assert late.analysis.measurement.stock_count == 0
    assert late.analysis.measurement.foundation_count == 0
    assert not _better_progress(late, root)


def test_14_deal_can_outrank_tableau_when_exact_delta_justifies_it(benchmark):
    progress = benchmark[3].progress
    positive = StructuralProgressDelta(1, 1, 1, 1, 2, 1, 1, 1.0, 1, 1, 1)
    deal_state = benchmark[1].clone()
    deal_edge = make_edge(StrategicActionKind.DEAL_NOW, deal_state, positive)
    move_edge = make_edge(StrategicActionKind.ECONOMIC_PROJECT, deal_state)
    deal_node = make_priority_node(benchmark, node_id=30, progress=progress, edge=deal_edge)
    move_node = make_priority_node(benchmark, node_id=31, progress=progress, edge=move_edge)
    assert _node_priority(deal_node) < _node_priority(move_node)


def test_15_post_deal_delta_metrics_are_exact(benchmark):
    before = benchmark[3].measurement
    after = replace(
        before,
        foundation_count=before.foundation_count + 1,
        critical_dependencies_pending=before.critical_dependencies_pending - 2,
        same_suit_run_mass=before.same_suit_run_mass + 3,
        stable_same_suit_joins=before.stable_same_suit_joins + 1,
        mixed_suit_boundaries=before.mixed_suit_boundaries - 1,
        rehandling_debt=before.rehandling_debt - 2,
        legal_move_count=before.legal_move_count + 4,
    )
    delta = structural_progress_delta(
        before, after, actionable_before=2, actionable_after=5, exact_receiver_successes=2
    )
    assert (delta.foundation_delta, delta.critical_dependencies_removed) == (1, 2)
    assert (delta.actionable_high_value_delta, delta.same_suit_mass_delta) == (3, 3)
    assert (delta.stable_join_delta, delta.mixed_boundary_reduction) == (1, 1)
    assert (delta.rehandling_debt_reduction, delta.mobility_delta, delta.exact_receiver_successes) == (2, 4, 2)


def test_16_deal_priority_uses_delta_not_epoch(benchmark):
    source = inspect.getsource(controller.strategic_progress_order_key)
    assert "deal_ordering_key" in source
    assert "stock_count" not in source and "stock_epoch" not in source


def test_17_post_deal_reuse_requires_exact_identity(benchmark):
    cards, _state, config, analysis, _node = benchmark
    arm = analysis.deal_timing.deal_now
    telemetry = ControllerTelemetry()
    analyze_strategic_state(
        arm.post_deal_state, cards, spent_cost=1, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache={}, telemetry=telemetry,
        precomputed_economic=arm.economic_analysis, precomputed_measurement=arm.measurement,
        precomputed_state_key=canonical_state_key(arm.post_deal_state),
        precomputed_config_fingerprint=analysis_config_fingerprint(config),
    )
    assert telemetry.post_deal_analysis_reused == telemetry.avoided_full_analyses == 1


def test_18_mismatched_state_invalidates_reuse(benchmark):
    cards, state, config, analysis, _node = benchmark
    arm = analysis.deal_timing.deal_now
    telemetry = ControllerTelemetry()
    result = analyze_strategic_state(
        arm.post_deal_state, cards, spent_cost=1, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache={}, telemetry=telemetry,
        precomputed_economic=arm.economic_analysis, precomputed_measurement=arm.measurement,
        precomputed_state_key=canonical_state_key(state),
        precomputed_config_fingerprint=analysis_config_fingerprint(config),
    )
    assert telemetry.precomputed_analysis_mismatches == 1
    assert result.economic is not arm.economic_analysis


def test_19_analysis_cache_is_exact_state_and_config_safe(benchmark):
    cards, state, config, *_ = benchmark
    cache = {}
    telemetry = ControllerTelemetry()
    first = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache, telemetry=telemetry,
    )
    second = analyze_strategic_state(
        state.clone(), cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache, telemetry=telemetry,
    )
    changed = replace(config, campaign_source_combination_limit=5)
    third = analyze_strategic_state(
        state, cards, spent_cost=0, incumbent_cost=None, config=changed,
        include_deal_timing=False, analysis_cache=cache, telemetry=telemetry,
    )
    assert first.economic is second.economic
    assert third.economic is not first.economic
    assert telemetry.analysis_cache_hits == 1 and telemetry.analysis_cache_misses == 2


def test_20_incumbent_budget_is_not_stale_cached(benchmark):
    cards, state, config, *_ = benchmark
    cache = {}
    production = analyze_strategic_state(
        state, cards, spent_cost=7, incumbent_cost=None, config=config,
        include_deal_timing=False, analysis_cache=cache,
    )
    research = analyze_strategic_state(
        state, cards, spent_cost=7, incumbent_cost=172, config=config,
        include_deal_timing=False, analysis_cache=cache,
    )
    assert production.economic is research.economic
    assert production.budget.improvement_target is None
    assert research.budget.improvement_target == 171


def test_21_foundation_macro_has_protected_positive_credit_opportunity(benchmark):
    cards, _state, config, *_ = benchmark
    config = replace(
        config,
        enable_campaign_edges=True,
        enable_removal_edges=True,
        campaign_branches_positive=0,
        campaign_max_added_cost=1,
        campaign_max_nodes=1,
        campaign_time_limit_s=0.01,
        max_tactical_nodes=10,
    )
    telemetry = ControllerTelemetry()
    _foundation_successors(
        positive_node(benchmark), cards, config=config, telemetry=telemetry,
        started=time.perf_counter(),
    )
    assert telemetry.foundation_macro_attempts >= 1


def test_22_probe_scheduling_prefers_current_epoch_work(benchmark):
    project = next(item for item in benchmark[3].economic.frontier.ordered_projects if item.reveal_values)
    current_epoch = benchmark[3].economic.campaign_portfolio.current_epoch
    current = replace(project, earliest_useful_epoch=current_epoch)
    later = replace(project, earliest_useful_epoch=current_epoch + 1)
    assert _project_probe_schedule_key(current, current_epoch=current_epoch) < _project_probe_schedule_key(later, current_epoch=current_epoch)


def test_23_failed_same_tier_probe_is_not_immediately_repeated(benchmark, monkeypatch):
    calls: list[str] = []
    install_miss_probe(monkeypatch, calls, nodes=256)
    cards, _state, config, *_ = benchmark
    node = positive_node(benchmark)
    cache = {}
    telemetry = ControllerTelemetry()
    generate_strategic_successors(
        node, cards, incumbent_cost=None, config=config, telemetry=telemetry,
        actionability_cache=cache, started=time.perf_counter(),
    )
    generate_strategic_successors(
        node, cards, incumbent_cost=None, config=config, telemetry=telemetry,
        actionability_cache=cache, started=time.perf_counter(),
    )
    assert calls.count(calls[0]) == 1
    assert telemetry.actionability_retry_suppressions >= 1


def test_24_progressive_credit_semantics_remain_monotonic():
    assert [int(level) for level in StrategicCreditLevel] == [0, 1, 2, 3, 4]
    assert list(AnytimeControllerConfig().tactical_max_cost_by_credit) == sorted(
        AnytimeControllerConfig().tactical_max_cost_by_credit
    )


def test_25_exact_tt_semantics_are_unchanged():
    state = one_move_solution_state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 5)
    assert not tt.admit(state.clone(), 5, heuristic_score=-10**9)
    assert tt.admit(state.clone(), 4, heuristic_score=10**9)
    assert tt.best_g(state) == 4


def test_26_only_admissible_budget_proof_prunes():
    source = inspect.getsource(controller.solve_anytime)
    proof_lines = [line.strip() for line in source.splitlines() if "proof_prunable" in line]
    assert proof_lines == [
        "if node.analysis.budget.proof_prunable:",
        "if child.analysis.budget.proof_prunable:",
    ]
    assert "progress.proof" not in source and "actionability.proof" not in source


def test_27_strategic_progress_order_is_transparent_and_deterministic(benchmark):
    progress = benchmark[3].progress
    assert progress.ordering_key() == progress.ordering_key()
    fields = tuple(StrategicProgressComponents.__dataclass_fields__)
    assert "stock_count" not in fields and "stock_epoch" not in fields
    assert fields[:4] == (
        "solved", "foundation_count", "removal_ready_campaigns", "credible_current_campaigns"
    )


def test_28_best_progress_is_separate_from_lowest_g_when_appropriate():
    result = solve_anytime(
        one_move_solution_state(), standard_cards(), None,
        small_config(max_strategic_expansions=2),
    )
    assert result.best_progress_node.state.is_solved()
    assert result.lowest_g_node.node_id == 0
    assert result.best_progress_node.node_id != result.lowest_g_node.node_id
    assert result.best_progress_node.node_id != result.deepest_stock_node.node_id


def test_29_generic_priority_contains_no_benchmark_constants():
    source = inspect.getsource(controller)
    assert "492515" not in source
    assert "Hearts needs" not in source and "Spades needs" not in source


def test_30_canonical_future_route_is_unavailable_prospectively():
    source = inspect.getsource(controller)
    assert ".moves" not in source
    assert "parse_moves_file" not in source
    assert "77d169da2538ba8c" not in source


def test_31_external_119_never_enters_pruning():
    source = inspect.getsource(controller)
    assert "119" not in source
    assert "external" not in inspect.getsource(controller._node_priority).lower()


@pytest.mark.parametrize("seed", [20260827, 20260828])
def test_32_unseen_deal_smoke_honors_unrestricted_profile(seed):
    cards = standard_cards()
    random.Random(seed).shuffle(cards)
    result = solve_anytime(
        SpiderState.from_cards(cards),
        cards,
        None,
        small_config(wall_clock_limit_s=5, max_strategic_expansions=1),
    )
    assert result.preflight.passed
    assert result.preflight.profile.can_deal_into_empty is True
    assert result.telemetry.retained > 0
    replay = SpiderState.from_cards(cards)
    if result.best_progress_node.actions:
        replay_actions(replay, list(result.best_progress_node.actions))
