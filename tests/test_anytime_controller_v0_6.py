from __future__ import annotations

import inspect
import random
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
import spider.planner.campaign_dependency_closure as closure_module
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicTranspositionTable,
    freeze_active_rule_profile,
    solve_anytime,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    DependencyClosureConfig,
    DependencyClosureStatus,
    assess_campaign_dependency_closure,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
)
from spider.planner.deal_purpose import (
    DealPurposeKind,
    DealPurposeStatus,
    audit_successive_deal,
    create_deal_purpose_contract,
    validate_deal_purpose_contract,
)
from spider.planner.foundation_campaign import (
    CampaignReadiness,
    RankSource,
    RankSourceKind,
)
from spider.planner.protected_conversion import (
    NearRemovalConfig,
    TerminalAssemblyConfig,
    TerminalAssemblyStatus,
    create_protected_conversion_lane,
    realize_terminal_campaign_assembly,
)
from spider.planner.supply_consumption import (
    CampaignSupplyObligation,
    SupplyConsumptionStage,
    advance_supply_consumption_results,
    invalidate_supply_result,
    supply_result_for_contract,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


@pytest.fixture(scope="module")
def analyzed_opening():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=5.0,
        max_strategic_expansions=1,
        max_tactical_nodes=100,
        max_frontier_size=16,
        max_successors_per_expansion=4,
        enable_campaign_edges=False,
        enable_campaign_corridors=False,
        enable_expensive_deal_timing=False,
    )
    analysis = controller_module.analyze_strategic_state(
        state,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    return cards, state, config, analysis


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit: str, rank: int, column: int = 0) -> RankSource:
    return RankSource(
        source_key=f"fixture:{suit}:{rank}",
        card=Card(suit, rank),
        kind=RankSourceKind.SHALLOW_TABLEAU,
        column=column,
        tableau_zone="face_up",
        depth=1,
        stock_epoch=None,
        stock_column=None,
        usable_by_target=True,
        reserved_by_completed_foundation=False,
        excavation_peels=1,
        closure_prefix_hops=0,
        helper_tasks=(),
        needs_temp_space=False,
        dependency_blocked=False,
        reception_status="not_applicable",
        estimated_cost=1.0,
        note="synthetic legal fixture",
    )


def _campaign(base, *, suit="c", required_rank=5, space_requirement=0, cost=4.0):
    needs = tuple(
        replace(
            need,
            chosen=(_source(suit, need.rank) if need.rank == required_rank else None),
            must_excavate=(need.rank == required_rank),
            reason="synthetic named dependency",
        )
        for need in base.rank_needs
    )
    return replace(
        base,
        suit=suit,
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(
            need.chosen for need in needs if need.chosen is not None
        ),
        future_stock_supplied_cards=(),
        optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(),
        shared_prerequisite_tasks=(),
        space_requirement=space_requirement,
        stock_plan=(),
        estimated_campaign_cost=cost,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )


@pytest.fixture(scope="module")
def base_campaign(analyzed_opening):
    return analyzed_opening[3].economic.campaign_portfolio.campaigns[0]


@pytest.fixture
def supply_case(analyzed_opening):
    _cards, _opening, _config, analysis = analyzed_opening
    profile = analysis.residual.checkpoint
    row = (
        Card("c", 5),
        Card("c", 6),
        Card("c", 5),
        Card("d", 7),
        Card("h", 8),
        Card("s", 9),
        Card("d", 10),
        Card("h", 11),
        Card("s", 12),
        Card("d", 13),
    )
    before = SpiderState(
        _columns(*([Card("h", 13)] for _ in range(10))),
        list(row),
    )
    obligation = CampaignSupplyObligation(
        "supply-five",
        "C#1",
        Card("c", 5),
        5,
        0,
        "stock:5:0",
        "rank:5:c",
        (5, 5),
        6,
    )
    contract = create_deal_purpose_contract(
        before,
        profile,
        campaign_id="C#1",
        explicit_purpose=DealPurposeKind.CAMPAIGN_SUPPLY,
        horizon_expansions=2,
    )
    contract = replace(
        contract,
        parent_state_key=canonical_state_key(before),
        exact_incoming_row=row,
        supply_obligations=(obligation,),
    )
    delivered = advance_supply_consumption_results(
        before,
        (("deal",),),
        new_contracts=(contract,),
    )
    after_deal = before.clone()
    after_deal.deal(MW_RULES)
    return profile, before, after_deal, contract, delivered


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_canonical_anchor_is_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)
    assert (result.stock_deals, result.foundations, result.path_hash, result.state_hash) == (
        5,
        8,
        "77d169da2538ba8c",
        "4e9861540eac570cb",
    )


def test_03_delivery_is_not_consumption(supply_case):
    profile, _before, _after, contract, results = supply_case
    result = results[0]
    assert result.highest_stage == SupplyConsumptionStage.AVAILABLE
    outcome = validate_deal_purpose_contract(
        contract, profile, current_depth=1, supply_consumption=result
    )
    assert outcome.status != DealPurposeStatus.FULFILLED


def test_04_delivered_only_contract_is_partial(supply_case):
    profile, _before, _after, contract, results = supply_case
    outcome = validate_deal_purpose_contract(
        contract, profile, current_depth=1, supply_consumption=results[0]
    )
    assert outcome.status == DealPurposeStatus.PARTIALLY_FULFILLED


def test_05_delivered_unconsumed_contract_reclassifies_at_horizon(supply_case):
    profile, _before, _after, contract, results = supply_case
    outcome = validate_deal_purpose_contract(
        contract, profile, current_depth=2, supply_consumption=results[0]
    )
    assert outcome.status == DealPurposeStatus.DELIVERED_BUT_UNCONSUMED


def test_06_supplied_source_integration_fulfils_contract(supply_case):
    profile, _before, after, contract, results = supply_case
    advanced = advance_supply_consumption_results(
        after, ((0, 1, 1),), existing=results
    )
    evidence = advanced[0].evidence[0]
    assert evidence.stage == SupplyConsumptionStage.INTEGRATED
    outcome = validate_deal_purpose_contract(
        contract, profile, current_depth=1, supply_consumption=advanced[0]
    )
    assert outcome.status == DealPurposeStatus.FULFILLED


def test_06b_supplied_receiver_requires_actual_use(supply_case):
    profile, before, after, contract, _results = supply_case
    receiver = CampaignSupplyObligation(
        "supply-six-receiver",
        "C#1",
        Card("c", 6),
        5,
        1,
        "stock:5:1",
        "receiver:6:c",
        (6, 5),
        6,
        receiver_supply=True,
    )
    receiver_contract = replace(
        contract,
        contract_id="receiver-contract",
        supply_obligations=(receiver,),
    )
    delivered = advance_supply_consumption_results(
        before, (("deal",),), new_contracts=(receiver_contract,)
    )
    assert validate_deal_purpose_contract(
        receiver_contract,
        profile,
        current_depth=1,
        supply_consumption=delivered[0],
    ).status != DealPurposeStatus.FULFILLED
    used = advance_supply_consumption_results(after, ((0, 1, 1),), existing=delivered)
    assert used[0].evidence[0].stage == SupplyConsumptionStage.INTEGRATED


def test_07_interchangeable_copy_can_satisfy_dependency(supply_case):
    _profile, _before, after, _contract, results = supply_case
    advanced = advance_supply_consumption_results(
        after, ((2, 1, 1),), existing=results
    )
    assert advanced[0].evidence[0].stage == SupplyConsumptionStage.INTEGRATED
    assert advanced[0].evidence[0].substituted_source_key is not None


def test_08_provenance_follows_substitution(supply_case):
    _profile, _before, after, _contract, results = supply_case
    advanced = advance_supply_consumption_results(after, ((2, 1, 1),), existing=results)
    evidence = advanced[0].evidence[0]
    assert evidence.active_source_key == evidence.substituted_source_key
    assert evidence.current_column == 1


def test_09_irrelevant_supply_can_invalidate_cleanly(supply_case):
    _profile, _before, after, _contract, results = supply_case
    invalid = invalidate_supply_result(results[0], after, reason="fresh campaign changed")
    assert invalid.evidence[0].stage == SupplyConsumptionStage.INVALIDATED


def test_10_supply_lifecycle_has_no_proof_authority(supply_case):
    _profile, _before, _after, contract, results = supply_case
    assert not contract.proof_pruning_allowed
    assert not results[0].proof_pruning_allowed
    assert not results[0].evidence[0].proof_pruning_allowed


def test_11_named_dependency_graph_is_deterministic(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), [])
    campaign = _campaign(base_campaign)
    assert build_campaign_dependency_graph(state, campaign) == build_campaign_dependency_graph(state, campaign)


def test_12_dependency_graph_contains_no_benchmark_constants():
    source = inspect.getsource(closure_module)
    assert "492515" not in source and "Diamond" not in source and "column 4" not in source


def test_13_buried_source_blocker_is_represented(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)]), [])
    graph = build_campaign_dependency_graph(state, _campaign(base_campaign))
    assert graph.count(CampaignDependencyType.SOURCE_BURIED) == 1


def test_14_mixed_overlay_blocker_is_represented(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)]), [])
    graph = build_campaign_dependency_graph(state, _campaign(base_campaign))
    assert graph.count(CampaignDependencyType.MIXED_OVERLAY) == 1


def test_15_missing_interval_blocker_is_represented(base_campaign):
    state = SpiderState(_columns([Card("c", 5)]), [])
    graph = build_campaign_dependency_graph(state, _campaign(base_campaign))
    assert graph.count(CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL) >= 1


def test_16_receiver_blocker_is_represented(base_campaign):
    state = SpiderState(_columns([Card("c", 5)], [Card("c", 8)]), [])
    graph = build_campaign_dependency_graph(state, _campaign(base_campaign))
    assert graph.count(CampaignDependencyType.RECEIVER_MISSING) >= 1


def test_17_workspace_blocker_is_represented(base_campaign):
    state = SpiderState(_columns(*([Card("h", 13)] for _ in range(10))), [])
    graph = build_campaign_dependency_graph(
        state, _campaign(base_campaign, space_requirement=1)
    )
    assert graph.count(CampaignDependencyType.WORKSPACE_REQUIRED) == 1


def test_18_supplied_not_consumed_blocker_is_represented(base_campaign, supply_case):
    _profile, _before, after, _contract, results = supply_case
    graph = build_campaign_dependency_graph(
        after, _campaign(base_campaign), supply_consumptions=results
    )
    assert graph.count(CampaignDependencyType.SUPPLIED_NOT_CONSUMED) == 1


def test_19_overlay_clearer_exposes_named_source(base_campaign):
    state = SpiderState(
        _columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), []
    )
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_added_cost=3, max_nodes=100, time_limit_s=1.0),
    )
    assert result.status in (
        DependencyClosureStatus.DEPENDENCY_CLOSED,
        DependencyClosureStatus.MILESTONE_REACHED,
    )
    assert result.overlays_cleared and result.independent_replay_verified


def test_20_overlay_clearer_ignores_unrelated_cleanup(base_campaign):
    state = SpiderState(
        _columns([Card("c", 5), Card("d", 4)], [Card("d", 5)], [Card("h", 9), Card("s", 8)], [Card("s", 9)]),
        [],
    )
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_added_cost=3, max_nodes=100, time_limit_s=1.0),
    )
    assert all(step.action[0] != 2 for step in result.steps)


def test_21_temporary_park_requires_bounded_exit(base_campaign):
    state = SpiderState(
        _columns([Card("c", 5), Card("d", 13)], *([Card("h", 1)] for _ in range(9))),
        [],
    )
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_added_cost=2, max_nodes=20, time_limit_s=0.5),
    )
    assert all(
        step.lifecycle is None
        or step.lifecycle.placement_class not in ("MIXED_SUIT_PARK", "WORKSPACE_PARK")
        or step.lifecycle.exit_route_bounded
        for step in result.steps
    )


def test_22_closure_can_create_receiver_path(base_campaign):
    state = SpiderState(
        _columns([Card("c", 5)], [Card("c", 6), Card("d", 5)], [Card("d", 6)]), []
    )
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_added_cost=3, max_nodes=100, time_limit_s=1.0),
    )
    assert result.actions and result.independent_replay_verified


def test_23_closure_can_consume_supplied_asset(base_campaign, supply_case):
    _profile, _before, after, _contract, supplies = supply_case
    # Remove the interchangeable fixture copy so this gate isolates actual
    # use of the delivered source rather than fragment ordering among copies.
    after.columns[2].face_up[-1] = Card("d", 5)
    result = realize_campaign_dependency_closure(
        after,
        _campaign(base_campaign),
        supply_consumptions=supplies,
        config=DependencyClosureConfig(max_added_cost=2, max_nodes=100, time_limit_s=1.0),
    )
    assert result.status == DependencyClosureStatus.SUPPLY_CONSUMED
    assert result.supply_consumptions[0].consumed_count == 1


def test_24_closure_can_join_missing_interval(base_campaign):
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    campaign = _campaign(base_campaign, required_rank=1)
    result = realize_campaign_dependency_closure(
        state,
        campaign,
        config=DependencyClosureConfig(max_added_cost=2, max_nodes=50, time_limit_s=0.5),
    )
    assert result.status == DependencyClosureStatus.MILESTONE_REACHED
    assert result.actions == ((1, 0, 1),)


def test_25_closure_reduces_named_dependency(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), [])
    campaign = _campaign(base_campaign)
    before = assess_campaign_dependency_closure(state, campaign)
    result = realize_campaign_dependency_closure(
        state, campaign, config=DependencyClosureConfig(max_nodes=100, time_limit_s=1.0)
    )
    after = assess_campaign_dependency_closure(result.end_state, campaign)
    assert len(after.graph.dependencies) < len(before.graph.dependencies)


def test_26_closure_defaults_to_no_deal(base_campaign):
    config = DependencyClosureConfig()
    assert config.permit_stock_transition is False


def test_27_closure_does_not_silently_deal(base_campaign):
    row = [Card("h", rank) for rank in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    state = SpiderState(_columns(*([Card("s", 13)] for _ in range(10))), row)
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_nodes=10, time_limit_s=0.2),
    )
    assert ("deal",) not in result.actions and len(result.end_state.stock) == 10


def test_28_bounded_failure_is_typed(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 13)], *([Card("h", 1)] for _ in range(9))), [])
    result = realize_campaign_dependency_closure(
        state,
        _campaign(base_campaign),
        config=DependencyClosureConfig(max_nodes=1, time_limit_s=0.2),
    )
    assert result.status in (
        DependencyClosureStatus.RESOURCE_LIMIT,
        DependencyClosureStatus.BLOCKED_BY_OVERLAY,
    )


def test_29_closure_failure_has_no_proof_authority(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 13)], *([Card("h", 1)] for _ in range(9))), [])
    result = realize_campaign_dependency_closure(
        state, _campaign(base_campaign), config=DependencyClosureConfig(max_nodes=1, time_limit_s=0.1)
    )
    assert result.proof_pruning_allowed is False


def test_30_successful_closure_independently_replays(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), [])
    result = realize_campaign_dependency_closure(
        state, _campaign(base_campaign), config=DependencyClosureConfig(max_nodes=100, time_limit_s=1.0)
    )
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost
    assert canonical_state_key(replay) == canonical_state_key(result.end_state)


def test_31_closure_can_make_terminal_predicate_true(base_campaign):
    state = SpiderState(
        _columns([Card("c", rank) for rank in range(13, 1, -1)], [Card("c", 1)]), []
    )
    campaign = _campaign(base_campaign, required_rank=1, cost=1.0)
    campaign = replace(
        campaign,
        rank_needs=tuple(replace(need, chosen=None, must_excavate=False) for need in campaign.rank_needs),
    )
    assert realize_terminal_campaign_assembly(
        state,
        campaign,
        config=TerminalAssemblyConfig(near_removal=NearRemovalConfig(minimum_same_suit_coverage=8)),
    ).status == TerminalAssemblyStatus.FOUNDATION_REMOVED


def test_32_terminal_assembler_removes_fixture_foundation(base_campaign):
    state = SpiderState(_columns([Card("c", rank) for rank in range(13, 1, -1)], [Card("c", 1)]), [])
    campaign = _campaign(base_campaign, required_rank=1, cost=1.0)
    campaign = replace(campaign, rank_needs=tuple(replace(n, chosen=None, must_excavate=False) for n in campaign.rank_needs))
    result = realize_terminal_campaign_assembly(state, campaign)
    assert result.status == TerminalAssemblyStatus.FOUNDATION_REMOVED


def test_33_protected_lane_carries_dependency_set(analyzed_opening):
    _cards, _state, _config, analysis = analyzed_opening
    profile = analysis.residual.checkpoint
    lane = create_protected_conversion_lane(
        profile,
        unresolved_dependencies=("source:5:c", "overlay:5-5:c0"),
    )
    assert lane and lane.unresolved_dependencies == ("source:5:c", "overlay:5-5:c0")


def test_34_alternate_lanes_remain_available(analyzed_opening):
    _cards, _state, _config, analysis = analyzed_opening
    assert len(analysis.economic.campaign_portfolio.campaigns) > 1


def test_35_unresolved_supply_is_a_graph_dependency(base_campaign, supply_case):
    _profile, _before, after, _contract, supplies = supply_case
    graph = build_campaign_dependency_graph(after, _campaign(base_campaign), supply_consumptions=supplies)
    assert any(item.kind == CampaignDependencyType.SUPPLIED_NOT_CONSUMED for item in graph.dependencies)


def test_36_another_deal_remains_legal_with_unresolved_supply(supply_case):
    _profile, _before, after, _contract, _supplies = supply_case
    after.stock = [Card("h", rank) for rank in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)]
    assert after.can_deal(MW_RULES)


def test_37_successive_deal_audit_records_consumption_and_closure(supply_case):
    profile, _before, _after, contract, supplies = supply_case
    outcome = validate_deal_purpose_contract(contract, profile, current_depth=1, supply_consumption=supplies[0])
    audit = audit_successive_deal(
        contract,
        outcome,
        deal_ordinal=2,
        dependency_closure_attempted=True,
        dependency_closure_result=DependencyClosureStatus.BLOCKED_BY_RECEIVER.value,
        reason_another_deal_considered="bounded closure miss",
    )
    assert audit.consumption_stage == SupplyConsumptionStage.AVAILABLE
    assert audit.dependency_closure_attempted


def test_38_exact_tt_ignores_contract_history():
    state = SpiderState(_columns([Card("c", 7)]), [])
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 3)
    assert not tt.admit(state.clone(), 3, heuristic_score={"contract": "different"})


def test_39_lower_g_exact_state_still_dominates():
    state = SpiderState(_columns([Card("c", 7)]), [])
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 5) and tt.admit(state.clone(), 4) and not tt.admit(state, 4)


def test_40_admissible_h_is_unchanged(analyzed_opening):
    _cards, _state, _config, analysis = analyzed_opening
    assert analysis.budget.admissible_remaining_lower_bound == (
        analysis.budget.h_deals + analysis.budget.h_reveal_paid
    )


def test_41_deadline_propagates_through_closure(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), [])
    now = time.perf_counter()
    deadline = SearchDeadline(absolute_deadline=now - 0.01, started_at=now - 1.0)
    result = realize_campaign_dependency_closure(
        state, _campaign(base_campaign), deadline=deadline
    )
    assert result.status == DependencyClosureStatus.RESOURCE_LIMIT


def test_42_closure_cache_keys_exact_state_campaign_and_config(base_campaign):
    state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)]), [])
    cache = {}
    campaign = _campaign(base_campaign)
    a = realize_campaign_dependency_closure(state, campaign, cache=cache, config=DependencyClosureConfig(max_nodes=20, time_limit_s=0.2))
    b = realize_campaign_dependency_closure(state, campaign, cache=cache, config=DependencyClosureConfig(max_nodes=20, time_limit_s=0.2))
    assert len(cache) == 1 and a.actions == b.actions
    realize_campaign_dependency_closure(state, campaign, cache=cache, config=DependencyClosureConfig(max_nodes=21, time_limit_s=0.2))
    assert len(cache) == 2


def test_43_pre_foundation_diversity_configuration_is_unchanged():
    config = AnytimeControllerConfig()
    assert config.enable_pre_foundation_diversity and config.max_pre_foundation_geometries == 6


def test_44_canonical_actions_are_unavailable_prospectively():
    signature = inspect.signature(solve_anytime)
    assert "route" not in signature.parameters and "future_actions" not in signature.parameters


def test_45_external_119_is_absent_from_production_controller():
    assert "119" not in inspect.getsource(controller_module.solve_anytime)


def test_46_dependency_closure_has_no_benchmark_suit_bonus():
    source = inspect.getsource(closure_module)
    assert "target_suit" not in source and "diamond" not in source.lower()


@pytest.mark.parametrize("seed", (8301, 8302))
def test_47_unseen_deals_exercise_generic_closure_safely(seed):
    cards = [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]
    random.Random(seed).shuffle(cards)
    frozen = tuple(cards)
    state = SpiderState.from_cards(frozen)
    assert freeze_active_rule_profile(state, frozen).passed
    result = solve_anytime(
        state,
        frozen,
        None,
        AnytimeControllerConfig(
            wall_clock_limit_s=3.0,
            max_strategic_expansions=1,
            max_tactical_nodes=50,
            max_frontier_size=16,
            max_successors_per_expansion=4,
            enable_campaign_edges=False,
            enable_campaign_corridors=False,
            enable_expensive_deal_timing=False,
        ),
    )
    assert result.preflight.profile.can_deal_into_empty
    assert result.elapsed_seconds <= 5.0
