from __future__ import annotations

import inspect
import time
from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    AnytimeControllerStatus,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    allowed_frontier_tiers,
    analyze_strategic_state,
    deduplicate_strategic_successors,
    freeze_active_rule_profile,
    generate_strategic_successors,
    order_deal_timing_arms,
    raw_fallback_enabled,
    retain_diverse_portfolio,
    solve_anytime,
    verify_complete_candidate,
    _raw_move_successors,
)
from spider.planner.deal_timing import (
    DealCounterfactual,
    DealPreparationCandidate,
    DealTimingAssessment,
    DealTimingConfig,
    DealTimingDecision,
    DealTimingDecisionKind,
    DealTimingReason,
    DealTimingStatus,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.economic_projects import EconomicFrontierTier
from spider.rules import MW_RULES, MobilityWareRules
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


def standard_cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def one_move_solution_state() -> SpiderState:
    foundations = []
    for suit in "cdh":
        for _ in range(2):
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    foundations.append([Card("s", rank) for rank in range(13, 0, -1)])
    columns = [
        Column([], [Card("s", rank) for rank in range(13, 1, -1)]),
        Column([], [Card("s", 1)]),
    ] + [Column([], []) for _ in range(8)]
    return SpiderState(columns, [], foundations)


def controller_config(**changes) -> AnytimeControllerConfig:
    base = AnytimeControllerConfig(
        wall_clock_limit_s=8,
        max_strategic_expansions=2,
        max_tactical_nodes=1_000,
        max_frontier_size=50,
        max_credit_level=StrategicCreditLevel.CLEAN,
        campaign_source_combination_limit=4,
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_trace_entries=2,
        max_timeline_entries=2,
    )
    return replace(base, **changes)


@pytest.fixture(scope="module")
def benchmark_cards() -> list[Card]:
    return load_deal(DEAL)


@pytest.fixture(scope="module")
def benchmark_root(benchmark_cards):
    state = SpiderState.from_cards(benchmark_cards)
    config = controller_config(
        wall_clock_limit_s=20,
        max_strategic_expansions=1,
        campaign_source_combination_limit=8,
    )
    analysis = analyze_strategic_state(
        state,
        benchmark_cards,
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
    return state, config, analysis, node


@pytest.fixture(scope="module")
def benchmark_post_deal(benchmark_root, benchmark_cards):
    state, config, analysis, _node = benchmark_root
    assert analysis.deal_timing is not None
    post = analysis.deal_timing.deal_now.post_deal_state
    assert post is not None
    post_analysis = analyze_strategic_state(
        post,
        benchmark_cards,
        spent_cost=1,
        incumbent_cost=None,
        config=config,
    )
    return post, post_analysis


def minimal_counterfactual(
    state: SpiderState,
    label: str,
    *,
    preparation: DealPreparationCandidate | None = None,
) -> DealCounterfactual:
    actions = (("deal",),) if preparation is None else preparation.actions + (("deal",),)
    return DealCounterfactual(
        label=label,
        status=(DealTimingStatus.DEAL_NOW if preparation is None else DealTimingStatus.PREPARE_THEN_DEAL),
        preparation=preparation,
        preparation_cost=preparation.corrected_cost if preparation else 0,
        deal_cost=1,
        total_added_cost=(preparation.corrected_cost if preparation else 0) + 1,
        actions=actions,
        post_deal_state=state.clone(),
        result_key_hex="state",
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


def timing_assessment(kind: DealTimingDecisionKind) -> DealTimingAssessment:
    state = one_move_solution_state()
    prep = DealPreparationCandidate(
        "prep",
        1,
        ("PERMANENT_JOIN",),
        ("project",),
        ((1, 0, 1),),
        ("move 2 1 1",),
        1,
        state.clone(),
        "prep-state",
        True,
        ("credible",),
    )
    deal = minimal_counterfactual(state, "DEAL NOW")
    prepared = minimal_counterfactual(state, "prep", preparation=prep)
    decision = DealTimingDecision(
        kind,
        "prep" if kind == DealTimingDecisionKind.PREPARATION_PREFERRED else None,
        (DealTimingReason.LOWER_TOTAL_BOUNDED_COST,),
        ("test",),
        3,
    )
    return DealTimingAssessment(
        DealTimingConfig(),
        (),
        deal,
        (prep,),
        (prepared,),
        (),
        decision,
        "fingerprint",
    )


def successor(category: str, label: str, state: SpiderState, cost: int = 1) -> StrategicSuccessor:
    return StrategicSuccessor(
        StrategicActionKind.ECONOMIC_PROJECT,
        category,
        label,
        ((1, 0, 1),),
        cost,
        state.clone(),
        StrategicCreditLevel.CLEAN,
        cost,
        cost,
        1,
        True,
        False,
        (),
    )


def test_preflight_asserts_unrestricted_deal_on(benchmark_cards):
    result = freeze_active_rule_profile(SpiderState.from_cards(benchmark_cards), benchmark_cards)
    assert result.passed
    assert result.profile.can_deal_into_empty is True


def test_controller_never_substitutes_restricted_rules(benchmark_cards):
    restricted = MobilityWareRules(can_deal_into_empty=False)
    result = freeze_active_rule_profile(
        SpiderState.from_cards(benchmark_cards),
        benchmark_cards,
        rules=restricted,
    )
    assert not result.passed
    assert "can_deal_into_empty=True" in result.failures[0]


def test_empty_column_deal_legal_under_active_profile():
    state = SpiderState(
        [Column([], [])] + [Column([], [Card("c", rank)]) for rank in range(1, 10)],
        [Card("s", rank) for rank in range(1, 11)],
    )
    assert state.can_deal(MW_RULES)
    assert state.deal(MW_RULES) == 1


def test_restricted_profile_remains_restricted():
    state = SpiderState(
        [Column([], [])] + [Column([], [Card("c", rank)]) for rank in range(1, 10)],
        [Card("s", rank) for rank in range(1, 11)],
    )
    restricted = MobilityWareRules(can_deal_into_empty=False)
    assert not state.can_deal(restricted)
    with pytest.raises(ValueError):
        state.deal(restricted)


def test_preflight_freezes_complete_scoring_semantics(benchmark_cards):
    profile = freeze_active_rule_profile(
        SpiderState.from_cards(benchmark_cards), benchmark_cards
    ).profile
    assert (profile.cards, profile.suits, profile.tableau_columns, profile.stock_rows) == (104, 4, 10, 5)
    assert (profile.tableau_move_cost, profile.whole_open_column_to_empty_cost, profile.deal_cost) == (1, 0, 1)
    assert profile.foundation_removal_cost == 0


def test_canonical_172_regression_remains_exact():
    result = validate_solution("4925153", CANONICAL)
    assert result.valid and result.solved
    assert (result.mobilityware_moves, result.explicit_commands) == (172, 174)
    assert (result.tableau_moves, result.stock_deals, result.foundations) == (169, 5, 8)
    assert result.path_hash == "77d169da2538ba8c"
    assert result.state_hash == "4e9861540eac570cb"


def test_legal_cost23_regression_remains_exact():
    checkpoint = reconstruct_cost23_checkpoint()
    assert checkpoint.independently_verified
    assert checkpoint.arm.total_cost == checkpoint.action_count == 23
    assert checkpoint.deal_count == 2
    assert checkpoint.foundation_suits == ("s",)
    assert len(checkpoint.state.stock) == 30
    assert checkpoint.face_down_count == 32


def test_config_rejects_nonpositive_wall_time():
    with pytest.raises(ValueError):
        AnytimeControllerConfig(wall_clock_limit_s=0)


def test_config_rejects_nonmonotone_credit_costs():
    with pytest.raises(ValueError):
        AnytimeControllerConfig(tactical_max_cost_by_credit=(1, 4, 3, 8, 10))


def test_credit_zero_contains_only_tier1():
    assert allowed_frontier_tiers(StrategicCreditLevel.CLEAN) == (
        EconomicFrontierTier.STRUCTURALLY_DOMINANT,
    )


def test_credit_one_adds_tier2():
    assert EconomicFrontierTier.POSITIVE_INVESTMENT in allowed_frontier_tiers(
        StrategicCreditLevel.POSITIVE_INVESTMENT
    )


def test_credit_two_adds_tier3():
    assert EconomicFrontierTier.SPECULATIVE_DEFERRABLE in allowed_frontier_tiers(
        StrategicCreditLevel.SPECULATIVE
    )


def test_credit_three_adds_tier4():
    assert EconomicFrontierTier.ECONOMICALLY_UNEXPLAINED in allowed_frontier_tiers(
        StrategicCreditLevel.ESCAPE
    )


def test_raw_moves_absent_at_clean_credit():
    assert not raw_fallback_enabled(StrategicCreditLevel.CLEAN)


def test_raw_moves_available_at_broad_credit():
    assert raw_fallback_enabled(StrategicCreditLevel.RAW_LEGAL_FALLBACK)


def test_selected_raw_parks_record_complete_lifecycle(benchmark_root):
    _state, _config, _analysis, clean_node = benchmark_root
    node = replace(clean_node, credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK)
    successors = _raw_move_successors(node)
    assert successors
    for item in successors:
        joined = "\n".join(item.rationale)
        assert "same_suit_joins_created=" in joined
        assert "same_suit_joins_broken=" in joined
        assert "mixed_suit_boundaries_created=" in joined
        assert "mixed_suit_boundaries_removed=" in joined
        assert "future_exit_route=" in joined
        assert "estimated_rehandling_cost=" in joined
        assert "permanent_join_override_reason=" in joined
        assert "not evaluated" not in joined


def test_progressive_credit_cost_schedule_widens_monotonically():
    config = AnytimeControllerConfig()
    assert list(config.tactical_max_cost_by_credit) == sorted(config.tactical_max_cost_by_credit)


def test_tt_accepts_new_exact_state():
    tt = StrategicTranspositionTable()
    assert tt.admit(one_move_solution_state(), 4)


def test_tt_suppresses_equal_g_identical_state():
    state = one_move_solution_state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4)
    assert not tt.admit(state.clone(), 4)


def test_tt_suppresses_higher_g_identical_state():
    state = one_move_solution_state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4)
    assert not tt.admit(state.clone(), 5)


def test_tt_replaces_higher_g_with_lower_g():
    state = one_move_solution_state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 5)
    assert tt.admit(state.clone(), 4)
    assert tt.best_g(state) == 4


def test_heuristic_score_cannot_change_tt_dominance():
    state = one_move_solution_state()
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 4, heuristic_score=-10**9)
    assert not tt.admit(state.clone(), 5, heuristic_score=10**9)


def test_tt_identity_includes_stock():
    a = one_move_solution_state()
    b = one_move_solution_state()
    b.stock.append(Card("c", 1))
    tt = StrategicTranspositionTable()
    assert tt.admit(a, 4)
    assert tt.admit(b, 4)
    assert len(tt) == 2


def test_successor_dedup_keeps_lower_cost_exact_state():
    state = one_move_solution_state()
    items = (successor("other", "expensive", state, 2), successor("other", "cheap", state, 1))
    result = deduplicate_strategic_successors(items)
    assert len(result) == 1
    assert result[0].label == "cheap"


def test_portfolio_diversity_retains_deal_and_structure():
    state = one_move_solution_state()
    items = (
        successor("permanent_structure", "join", state),
        successor("deal_timing", "deal", state),
        successor("raw_fallback", "raw", state),
    )
    kept = retain_diverse_portfolio(items, maximum=2)
    assert {item.category for item in kept} == {"deal_timing", "permanent_structure"}


def test_deal_now_preferred_orders_deal_first_and_retains_preparation():
    arms = order_deal_timing_arms(timing_assessment(DealTimingDecisionKind.DEAL_NOW_PREFERRED))
    assert arms[0].preparation is None
    assert any(arm.preparation is not None for arm in arms)


def test_preparation_preferred_orders_preparation_first_and_retains_deal():
    arms = order_deal_timing_arms(timing_assessment(DealTimingDecisionKind.PREPARATION_PREFERRED))
    assert arms[0].preparation is not None
    assert any(arm.preparation is None for arm in arms)


def test_inconclusive_timing_retains_both_arms():
    arms = order_deal_timing_arms(timing_assessment(DealTimingDecisionKind.COMPARISON_INCONCLUSIVE))
    assert len(arms) == 2
    assert {arm.preparation is None for arm in arms} == {True, False}


def test_timing_decision_never_has_proof_authority():
    assessment = timing_assessment(DealTimingDecisionKind.DEAL_NOW_PREFERRED)
    assert assessment.decision.proof_pruning_allowed is False


def test_deal_timing_available_while_legal_moves_remain(benchmark_root):
    state, _config, analysis, _node = benchmark_root
    assert state.enumerate_moves()
    assert analysis.deal_timing is not None
    assert analysis.deal_timing.deal_now.post_deal_state is not None


def test_controller_retains_deal_successor_with_legal_moves(benchmark_root, benchmark_cards):
    _state, config, _analysis, node = benchmark_root
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node,
        benchmark_cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    assert any(item.kind == StrategicActionKind.DEAL_NOW for item in successors)


def test_deal_strategic_edge_independently_replays(benchmark_root, benchmark_cards):
    state, config, _analysis, node = benchmark_root
    successors = generate_strategic_successors(
        node,
        benchmark_cards,
        incumbent_cost=None,
        config=config,
        telemetry=ControllerTelemetry(),
        actionability_cache={},
        started=time.perf_counter(),
    )
    edge = next(item for item in successors if item.kind == StrategicActionKind.DEAL_NOW)
    replay = state.clone()
    assert replay_actions(replay, list(edge.actions)) == edge.corrected_cost
    assert states_structurally_equal(replay, edge.end_state)


def test_stock_deal_recomputes_campaign_portfolio(benchmark_root, benchmark_post_deal):
    _state, _config, before, _node = benchmark_root
    _post, after = benchmark_post_deal
    assert before.economic.campaign_portfolio.current_epoch == 0
    assert after.economic.campaign_portfolio.current_epoch == 1
    assert after.economic.campaign_portfolio is not before.economic.campaign_portfolio


def test_stock_deal_recomputes_actionability(benchmark_root, benchmark_post_deal):
    _state, _config, before, _node = benchmark_root
    _post, after = benchmark_post_deal
    assert (
        after.actionable_projects != before.actionable_projects
        or after.blocked_high_value_projects != before.blocked_high_value_projects
    )


def test_stock_deal_recomputes_deal_timing(benchmark_post_deal):
    _post, after = benchmark_post_deal
    assert after.deal_timing is not None
    assert after.deal_timing.incoming_row


def test_inaccessible_project_probe_is_cached_at_same_state_and_credit(
    benchmark_root, benchmark_cards
):
    _state, config, _analysis, clean_node = benchmark_root
    node = replace(clean_node, credit_level=StrategicCreditLevel.POSITIVE_INVESTMENT)
    cache = {}
    telemetry = ControllerTelemetry()
    generate_strategic_successors(
        node,
        benchmark_cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache=cache,
        started=time.perf_counter(),
    )
    misses = telemetry.actionability_cache_misses
    repeated_telemetry = ControllerTelemetry()
    generate_strategic_successors(
        node,
        benchmark_cards,
        incumbent_cost=None,
        config=config,
        telemetry=repeated_telemetry,
        actionability_cache=cache,
        started=time.perf_counter(),
    )
    assert misses >= 1
    assert repeated_telemetry.actionability_cache_hits >= 1


def test_controller_starts_from_arbitrary_legal_state():
    state = one_move_solution_state()
    result = solve_anytime(state, standard_cards(), None, controller_config())
    assert result.preflight.passed
    assert result.best_node is not None


def test_no_incumbent_mode_has_no_artificial_cap():
    result = solve_anytime(
        one_move_solution_state(), standard_cards(), None, controller_config(max_strategic_expansions=1)
    )
    assert result.initial_incumbent_cost is None
    assert result.best_node.analysis.budget.improvement_target is None


def test_first_verified_solution_installs_incumbent():
    result = solve_anytime(one_move_solution_state(), standard_cards(), None, controller_config())
    assert result.status == AnytimeControllerStatus.SOLVED
    assert result.first_solution is not None
    assert result.incumbent_cost == 1
    assert result.incumbent_progression == (1,)


def test_existing_incumbent_yields_target_one_less():
    state = one_move_solution_state()
    analysis = analyze_strategic_state(
        state,
        standard_cards(),
        spent_cost=0,
        incumbent_cost=172,
        config=controller_config(),
    )
    assert analysis.budget.improvement_target == 171


def test_complete_candidate_independently_replays():
    start = one_move_solution_state()
    end = start.clone()
    cost = end.move(1, 0, 1)
    record = verify_complete_candidate(
        start,
        end,
        ((1, 0, 1),),
        expected_cost=cost,
        expansions=1,
        elapsed_seconds=0.1,
    )
    assert record is not None
    assert record.independently_replay_verified
    assert record.search_endpoint_matches_replay
    assert record.foundations == 8 and record.stock_remaining == 0


def test_incomplete_candidate_is_rejected():
    state = one_move_solution_state()
    assert verify_complete_candidate(
        state,
        state,
        (),
        expected_cost=0,
        expansions=0,
        elapsed_seconds=0,
    ) is None


def test_successful_project_route_replays():
    start = one_move_solution_state()
    result = solve_anytime(start, standard_cards(), None, controller_config())
    assert result.first_solution is not None
    replay = start.clone()
    assert replay_actions(replay, list(result.first_solution.actions)) == 1
    assert replay.is_solved()


def test_foundation_removal_triggers_full_reanalysis():
    result = solve_anytime(
        one_move_solution_state(), standard_cards(), None, controller_config(max_strategic_expansions=1)
    )
    assert result.telemetry.full_reanalyses_after_foundation >= 1


def test_controller_reconstructs_path_across_strategic_edges():
    result = solve_anytime(one_move_solution_state(), standard_cards(), None, controller_config())
    assert result.first_solution.actions == ((1, 0, 1),)


def test_telemetry_is_bounded():
    result = solve_anytime(
        one_move_solution_state(),
        standard_cards(),
        None,
        controller_config(max_trace_entries=1, max_timeline_entries=1),
    )
    assert len(result.telemetry.decision_trace) <= 1
    assert len(result.telemetry.foundation_timeline) <= 1
    assert len(result.telemetry.rework_timeline) <= 1


def test_reveal_information_gain_remains_zero(benchmark_root):
    _state, _config, analysis, _node = benchmark_root
    assert all(value.information_gain == 0 for value in analysis.economic.reveal_values)


def test_heuristic_economic_slack_does_not_enter_proof_total(benchmark_root):
    _state, _config, analysis, _node = benchmark_root
    budget = analysis.budget
    changed = replace(budget, heuristic_economic_slack=-10**9)
    assert changed.hard_min_total == budget.hard_min_total
    assert changed.proof_prunable == budget.proof_prunable


def test_controller_source_contains_no_benchmark_strategy_constants():
    source = inspect.getsource(__import__("spider.planner.anytime_controller", fromlist=["*"]))
    for token in ("492515", "canonical.moves", "cost-47", "cost-49"):
        assert token not in source


def test_external_score_never_enters_generic_controller():
    source = inspect.getsource(__import__("spider.planner.anytime_controller", fromlist=["*"]))
    assert "119" not in source


def test_canonical_actions_are_not_imported_by_controller():
    source = inspect.getsource(__import__("spider.planner.anytime_controller", fromlist=["*"]))
    assert "parse_moves_file" not in source
    assert "CANONICAL" not in source


def test_controller_campaign_source_beam_is_deterministic(benchmark_cards):
    state = SpiderState.from_cards(benchmark_cards)
    config = controller_config(campaign_source_combination_limit=8)
    a = analyze_strategic_state(state, benchmark_cards, spent_cost=0, incumbent_cost=None, config=config)
    b = analyze_strategic_state(state, benchmark_cards, spent_cost=0, incumbent_cost=None, config=config)
    assert a.campaign_summary == b.campaign_summary
    assert a.project_frontier_summary == b.project_frontier_summary


def test_unseen_deterministic_deal_has_no_benchmark_dependency():
    cards = standard_cards()
    cards = cards[17:] + cards[:17]
    state = SpiderState.from_cards(cards)
    result = solve_anytime(
        state,
        cards,
        None,
        controller_config(
            wall_clock_limit_s=8,
            max_strategic_expansions=1,
            campaign_source_combination_limit=2,
        ),
    )
    assert result.preflight.passed
    assert result.strategic_expansions >= 1
    assert canonical_state_key(result.best_node.state)
