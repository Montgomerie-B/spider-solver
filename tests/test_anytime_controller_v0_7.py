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
import spider.planner.anytime_controller as controller_module
from spider.planner.analysis_budget import AnalysisResourceLimit, SearchDeadline
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    analyze_stage0_state,
    analyze_strategic_state,
    generate_strategic_successors,
    retain_obligation_successors,
)
from spider.planner.campaign_dependency_closure import (
    CampaignCriticalPathSummary,
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
    DependencyClosureStatus,
    build_campaign_critical_path,
)
from spider.planner.deal_purpose import DealPurposeKind
from spider.planner.incumbent_budget import build_incumbent_budget
from spider.planner.pre_foundation_diversity import build_pre_foundation_geometry
from spider.planner.protected_conversion import campaign_is_near_removal
from spider.planner.structural_construction import (
    ConstructionDisposition,
    analyze_same_suit_construction,
)
from spider.planner.structural_investment import (
    SameCampaignContinuationStatus,
    StructuralInvestmentEvidence,
    StructuralInvestmentKind,
    StructuralInvestmentLedger,
    StructuralInvestmentStatus,
    continuation_from_investment,
    investment_from_dependency_closure,
    refresh_continuation_credit,
)
from spider.planner.supply_consumption import (
    CampaignSupplyEvidence,
    CampaignSupplyObligation,
    SupplyConsumptionResult,
    SupplyConsumptionStage,
    SupplyObligationRole,
    advance_supply_consumption_results,
    scope_campaign_supply_obligations,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


@pytest.fixture(scope="module")
def analyzed_opening():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=5.0,
        max_strategic_expansions=1,
        max_tactical_nodes=100,
        max_frontier_size=24,
        max_successors_per_expansion=8,
        enable_campaign_edges=False,
        enable_campaign_corridors=False,
        enable_dependency_closure=False,
        enable_expensive_deal_timing=False,
    )
    analysis = analyze_strategic_state(
        state,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
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
        analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
    )
    return cards, state, config, analysis, node


def _closure_investment(*, evidence: bool = True, deals: int = 0):
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    lifecycle = SimpleNamespace(
        same_suit_joins_created=("6c-5c",) if evidence else (),
        estimated_rehandling_cost=0.0,
    )
    result = SimpleNamespace(
        campaign_id="C#1",
        dependencies_closed=("source:5:c",) if evidence else (),
        overlays_cleared=("overlay:c",) if evidence else (),
        supply_consumptions=(),
        steps=(SimpleNamespace(lifecycle=lifecycle),),
        corrected_added_cost=4,
        actions=(("deal",),) * deals + ((1, 0, 1),),
        status=DependencyClosureStatus.DEPENDENCY_CLOSED,
    )
    return investment_from_dependency_closure(
        canonical_state_key(state),
        result,
        created_depth=3,
        created_elapsed_seconds=1.0,
        maximum_further_cost=8,
        maximum_descendant_expansions=2,
        maximum_elapsed_seconds=5.0,
        baseline_total_g=14,
    )


def _credit():
    investment = _closure_investment()
    credit = continuation_from_investment(
        investment, outstanding_dependencies=("interval:4-1:c",)
    )
    assert credit is not None
    return credit


def _successor(state, *, label, category, source=None, kind=StrategicActionKind.ECONOMIC_PROJECT):
    return StrategicSuccessor(
        kind=kind,
        category=category,
        label=label,
        actions=(),
        corrected_cost=0,
        end_state=state.clone(),
        credit_level=StrategicCreditLevel.CLEAN,
        predicted_tactical_cost=0,
        realized_tactical_cost=0,
        tactical_nodes=0,
        independent_replay_verified=True,
        proof_pruning_allowed=False,
        rationale=(label,),
        source_project_id=source,
    )


def _obligation(identifier: str, rank: int, role: SupplyObligationRole):
    return CampaignSupplyObligation(
        identifier,
        "C#1",
        Card("c", rank),
        1,
        rank % 10,
        f"stock:1:{rank % 10}",
        f"rank:{rank}:c",
        (rank, rank),
        rank + 1,
        role=role,
    )


def _supply_result(obligations, stages, *, direct=()):
    state = SpiderState(_columns(), [])
    evidence = tuple(
        CampaignSupplyEvidence(
            item.obligation_id,
            stage,
            item.promised_source_key,
            item.promised_source_key,
            item.destination_column,
            0,
            None,
            None,
            None,
            index in set(direct),
            stage.value,
        )
        for index, (item, stage) in enumerate(zip(obligations, stages))
    )
    return SupplyConsumptionResult(
        "contract",
        "C#1",
        tuple(obligations),
        evidence,
        (),
        canonical_state_key(state),
        0,
        0,
        "fixture",
    )


def _graph(dependencies, edges):
    state = SpiderState(_columns(), [])
    terminal = "terminal:C#1"
    terminal_dependency = CampaignDependency(
        terminal,
        CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
        "C#1",
        "terminal",
        prerequisites=tuple(item.dependency_id for item in dependencies),
    )
    return CampaignDependencyGraph(
        canonical_state_key(state),
        "C#1",
        tuple(dependencies) + (terminal_dependency,),
        tuple(edges) + tuple((item.dependency_id, terminal) for item in dependencies),
        (),
        terminal,
        "fixture",
    )


def _construction_state(*, stock=()):
    return SpiderState(
        _columns([Card("d", 9), Card("c", 5)], [Card("c", 6)]),
        list(stock),
    )


def test_01_unrestricted_deal_still_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_regression_anchors_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)
    assert (result.stock_deals, result.foundations, result.path_hash, result.state_hash) == (
        5, 8, "77d169da2538ba8c", "4e9861540eac570cb"
    )


def test_03_structural_economics_docs_are_present():
    assert (ROOT / "docs" / "whole_deal_structural_economics.md").is_file()
    assert (ROOT / "docs" / "anytime_solver_development_plan_structural_update_2026-08-28.md").is_file()


def test_04_continuation_credit_created_after_named_closure_success():
    assert _credit().status == SameCampaignContinuationStatus.ACTIVE


def test_05_continuation_credit_carries_exact_campaign_objective():
    assert _credit().objective_id == "C#1"


def test_06_continuation_credit_carries_harvest_evidence():
    assert {item.kind.value for item in _credit().latest_harvest} >= {
        "DEPENDENCY_CLOSED", "OVERLAY_REMOVED", "PERMANENT_JOIN_CREATED"
    }


def test_07_successful_closure_child_gets_bounded_admission(analyzed_opening):
    _cards, state, _config, _analysis, node = analyzed_opening
    node = replace(node, continuation_credit=_credit())
    same = _successor(state, label="same", category="campaign", source="C#1")
    other = _successor(state, label="other", category="other", source="D#1")
    kept = retain_obligation_successors(node, (other, same), (other,), maximum=2)
    assert same in kept


def test_08_unrelated_alternatives_remain_available(analyzed_opening):
    _cards, state, _config, _analysis, node = analyzed_opening
    node = replace(node, continuation_credit=_credit())
    same = _successor(state, label="same", category="campaign", source="C#1")
    alternate = _successor(state, label="alternate", category="campaign", source="D#1")
    deal = _successor(state, label="deal", category="deal_timing", kind=StrategicActionKind.RAW_DEAL)
    kept = retain_obligation_successors(node, (same, alternate, deal), (deal,), maximum=3)
    assert {item.label for item in kept} == {"same", "alternate", "deal"}


def test_09_continuity_expires():
    credit = refresh_continuation_credit(
        _credit(), current_depth=6, current_elapsed_seconds=2.0,
        objective_still_credible=True,
    )
    assert credit.status == SameCampaignContinuationStatus.EXPIRED


def test_10_continuity_invalidates_on_fresh_contradiction():
    credit = refresh_continuation_credit(
        _credit(), current_depth=3, current_elapsed_seconds=2.0,
        objective_still_credible=False,
    )
    assert credit.status == SameCampaignContinuationStatus.INVALIDATED


def test_11_same_objective_concrete_dominance_supersedes_continuity():
    credit = refresh_continuation_credit(
        _credit(), current_depth=3, current_elapsed_seconds=2.0,
        objective_still_credible=True, dominating_same_objective=True,
    )
    assert credit.status == SameCampaignContinuationStatus.SUPERSEDED


def test_12_continuation_history_does_not_enter_exact_tt_identity():
    state = _construction_state()
    table = StrategicTranspositionTable()
    assert table.admit(state, 4)
    assert not table.admit(state.clone(), 4, heuristic_score=_credit())


def test_13_dependency_success_remains_fresh_state_reanalysed():
    source = inspect.getsource(controller_module.solve_anytime)
    assert "if node.analysis is None" in source
    assert "analyze_strategic_state(" in source
    assert "analysis=None" in source


def test_14_structural_investment_records_paid_cost():
    assert _closure_investment().paid_cost_invested == 4


def test_15_structural_investment_records_stock_spent():
    assert _closure_investment(deals=1).stock_rows_spent == 1


def test_16_structural_investment_records_permanent_joins():
    assert _closure_investment().evidence.permanent_same_suit_joins_created == 1


def test_17_structural_investment_records_expected_and_actual_harvest():
    investment = _closure_investment()
    assert investment.expected_harvest and investment.actual_harvest


def test_18_generic_activity_alone_is_not_campaign_harvest():
    investment = _closure_investment(evidence=False)
    assert continuation_from_investment(investment, outstanding_dependencies=()) is None


def test_19_one_critical_supply_asset_and_optional_assets_scope_correctly():
    obligations = (_obligation("a", 5, SupplyObligationRole.CRITICAL), _obligation("b", 7, SupplyObligationRole.CRITICAL))
    scoped = scope_campaign_supply_obligations(
        obligations, critical_dependency_keys=("rank:5:c",), coherent_milestone_id="m1"
    )
    assert [item.role for item in scoped] == [SupplyObligationRole.CRITICAL, SupplyObligationRole.OPTIONAL]


def test_20_genuinely_multi_asset_critical_objective_scopes_correctly():
    obligations = (_obligation("a", 5, SupplyObligationRole.OPTIONAL), _obligation("b", 6, SupplyObligationRole.OPTIONAL))
    scoped = scope_campaign_supply_obligations(
        obligations,
        critical_dependency_keys=("rank:5:c", "rank:6:c"),
        coherent_milestone_id="5-with-receiver-6",
    )
    assert all(item.role == SupplyObligationRole.CRITICAL for item in scoped)


def test_21_optional_unused_asset_does_not_block_full_fulfilment():
    critical = _obligation("a", 5, SupplyObligationRole.CRITICAL)
    optional = _obligation("b", 7, SupplyObligationRole.OPTIONAL)
    result = _supply_result(
        (critical, optional),
        (SupplyConsumptionStage.INTEGRATED, SupplyConsumptionStage.AVAILABLE),
        direct=(0,),
    )
    assert result.fully_consumed and result.critical_direct_campaign_advance


def test_22_unconsumed_critical_asset_blocks_fulfilment():
    critical = _obligation("a", 5, SupplyObligationRole.CRITICAL)
    optional = _obligation("b", 7, SupplyObligationRole.OPTIONAL)
    result = _supply_result(
        (critical, optional),
        (SupplyConsumptionStage.AVAILABLE, SupplyConsumptionStage.INTEGRATED),
        direct=(1,),
    )
    assert not result.fully_consumed


def test_23_copy_substitution_remains_valid():
    row = [Card("c", 5), Card("c", 5), Card("c", 6)] + [Card("h", 13)] * 7
    before = SpiderState(_columns(*([Card("d", 6)] for _ in range(10))), row)
    obligation = _obligation("copy", 5, SupplyObligationRole.CRITICAL)
    obligation = replace(obligation, destination_column=0, expected_receiver_rank=6)
    contract = SimpleNamespace(
        contract_id="copy-contract", campaign_id="C#1",
        supply_obligations=(obligation,), parent_state_key=canonical_state_key(before),
    )
    delivered = advance_supply_consumption_results(before, (("deal",),), new_contracts=(contract,))
    after = before.clone(); after.deal(MW_RULES)
    advanced = advance_supply_consumption_results(after, ((1, 2, 1),), existing=delivered)
    assert advanced[0].evidence[0].substituted_source_key is not None


def test_24_critical_path_ordering_favors_high_downstream_unlock():
    source = CampaignDependency("source", CampaignDependencyType.SOURCE_BURIED, "C#1", "source", depth=1)
    interval = CampaignDependency("interval", CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL, "C#1", "interval", prerequisites=("source",))
    overlay = CampaignDependency("overlay", CampaignDependencyType.MIXED_OVERLAY, "C#1", "overlay")
    summary = build_campaign_critical_path(_graph((source, interval, overlay), (("source", "interval"),)))
    by_id = {item.dependency_id: item for item in summary.entries}
    assert by_id["source"].downstream_dependencies_unlocked > by_id["overlay"].downstream_dependencies_unlocked


def test_25_receiver_creation_participates_in_dependency_ordering():
    receiver = CampaignDependency("receiver", CampaignDependencyType.RECEIVER_MISSING, "C#1", "receiver")
    source = CampaignDependency("source", CampaignDependencyType.SOURCE_BURIED, "C#1", "source")
    summary = build_campaign_critical_path(_graph((receiver, source), ()))
    assert summary.entries[0].dependency_id == "receiver"


def test_26_supplied_waiting_dependency_receives_relevance():
    supplied = CampaignDependency("supply", CampaignDependencyType.SUPPLIED_NOT_CONSUMED, "C#1", "supply")
    receiver = CampaignDependency("receiver", CampaignDependencyType.RECEIVER_MISSING, "C#1", "receiver")
    summary = build_campaign_critical_path(_graph((receiver, supplied), ()))
    assert summary.entries[0].supplied_asset_waiting


def test_27_permanent_same_suit_join_participates_in_ordering():
    opportunity = analyze_same_suit_construction(_construction_state()).opportunities[0]
    assert opportunity.stable_permanent and opportunity.ordering_key()[0] == 0


def test_28_two_card_same_suit_connection_is_construction_opportunity():
    opportunity = analyze_same_suit_construction(_construction_state()).opportunities[0]
    assert opportunity.run_length_after == 2 and opportunity.new_adjacencies == 1


def test_29_late_removal_campaign_has_positive_current_construction(analyzed_opening):
    _cards, _state, _config, analysis, _node = analyzed_opening
    campaign = replace(
        analysis.economic.campaign_portfolio.campaigns[0],
        suit="c", current_epoch=3, target_removal_epoch=5,
    )
    stock = [Card("h", 13)] * 20
    opportunity = analyze_same_suit_construction(
        _construction_state(stock=stock), campaigns=(campaign,)
    ).opportunities[0]
    assert opportunity.removal_horizon == 5 and opportunity.disposition == ConstructionDisposition.MAKE_NOW


def test_30_removal_horizon_is_distinct_from_construction_horizon(analyzed_opening):
    _cards, _state, _config, analysis, _node = analyzed_opening
    campaign = replace(analysis.economic.campaign_portfolio.campaigns[0], suit="c", target_removal_epoch=5)
    opportunity = analyze_same_suit_construction(
        _construction_state(stock=[Card("h", 13)] * 20), campaigns=(campaign,)
    ).opportunities[0]
    assert opportunity.construction_horizon == 3 < opportunity.removal_horizon


def test_31_exact_future_free_join_can_justify_deferral():
    row = [Card("h", 13)] * 10
    row[1] = Card("c", 5)
    opportunity = analyze_same_suit_construction(_construction_state(stock=row)).opportunities[0]
    assert opportunity.disposition == ConstructionDisposition.DEFER_FOR_FREE_FUTURE_JOIN
    assert opportunity.exact_future_free_join_epoch == 5


def test_32_workspace_or_receiver_damage_can_downorder_join():
    opportunity = analyze_same_suit_construction(
        _construction_state(), critical_receiver_columns=(1,)
    ).opportunities[0]
    assert opportunity.disposition == ConstructionDisposition.DOWNORDER_WORKSPACE_CONFLICT


def test_33_run_construction_is_not_proof_pruning():
    analysis = analyze_same_suit_construction(_construction_state())
    assert not analysis.proof_pruning_allowed
    assert all(not item.proof_pruning_allowed for item in analysis.opportunities)


def test_34_carrying_interference_evidence_is_ordering_only():
    opportunity = analyze_same_suit_construction(_construction_state()).opportunities[0]
    assert opportunity.carrying_interference_cost >= 0 and not opportunity.proof_pruning_allowed


def test_35_exact_tt_remains_lower_g_structural_dominance():
    state = _construction_state()
    table = StrategicTranspositionTable()
    assert table.admit(state, 5)
    assert not table.admit(state.clone(), 6)
    assert table.admit(state.clone(), 4)


def test_36_admissible_h_is_unchanged_by_investment_history():
    state = _construction_state(stock=[Card("h", 13)] * 10)
    a = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=9)
    ledger = StructuralInvestmentLedger((_closure_investment(),))
    b = build_incumbent_budget(state, spent_cost=2, incumbent_cost=100, heuristic_remaining_work=9)
    assert ledger.investments and a.admissible_remaining_lower_bound == b.admissible_remaining_lower_bound


def test_37_deal_remains_legal_despite_unresolved_campaign_investment():
    state = SpiderState(_columns(), [Card("h", 13)] * 10)
    assert _credit().outstanding_dependencies and state.can_deal(MW_RULES)


def test_38_broad_raw_credit_still_provides_alternate_legal_play(analyzed_opening):
    cards, state, config, analysis, node = analyzed_opening
    node = replace(node, credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK, continuation_credit=_credit())
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node, cards, incumbent_cost=None, config=config, telemetry=telemetry,
        actionability_cache={}, started=time.perf_counter(),
    )
    assert any(item.kind == StrategicActionKind.RAW_DEAL for item in successors)
    assert any(item.kind == StrategicActionKind.RAW_TABLEAU_MOVE for item in successors)


def test_39_pre_foundation_diversity_remains_intact(analyzed_opening):
    _cards, state, config, analysis, _node = analyzed_opening
    geometry = build_pre_foundation_geometry(state, g=0, analysis=analysis.economic, measurement=analysis.measurement)
    assert config.max_pre_foundation_geometries == 6 and geometry.proof_pruning_allowed is False


def test_40_terminal_assembly_predicate_is_not_weakened():
    source = inspect.getsource(campaign_is_near_removal)
    assert "continuation" not in source and "structural_investment" not in source


def test_41_external_119_is_absent_from_strategy_and_proof_constants():
    text = (ROOT / "src" / "spider" / "planner" / "anytime_controller.py").read_text()
    assert "119" not in text


def test_42_cost_21_is_absent_as_production_preference_constant():
    production = "\n".join(
        (ROOT / "src" / "spider" / "planner" / name).read_text()
        for name in ("anytime_controller.py", "structural_investment.py", "structural_construction.py")
    )
    assert "cost-21" not in production.lower() and "cost 21" not in production.lower()


def test_43_spades_is_absent_as_production_suit_target():
    production = "\n".join(
        (ROOT / "src" / "spider" / "planner" / name).read_text()
        for name in ("anytime_controller.py", "structural_investment.py", "structural_construction.py")
    )
    assert "spades" not in production.lower()


def test_44_canonical_future_actions_are_inaccessible_prospectively():
    source = inspect.getsource(controller_module)
    assert "canonical.moves" not in source and "solution_archive" not in source


def test_45_unseen_deals_generate_generic_structural_investments():
    base = load_deal(DEAL)
    for seed in (17, 23):
        cards = list(base); random.Random(seed).shuffle(cards)
        opportunities = analyze_same_suit_construction(SpiderState.from_cards(cards)).opportunities
        assert opportunities
        assert all(item.suit in {"c", "d", "h", "s"} for item in opportunities)


def test_46_shared_deadlines_propagate_through_new_analysis(analyzed_opening):
    cards, state, config, _analysis, _node = analyzed_opening
    deadline = SearchDeadline.from_seconds(0.001)
    time.sleep(0.005)
    with pytest.raises(AnalysisResourceLimit):
        analyze_strategic_state(
            state, cards, spent_cost=0, incumbent_cost=None, config=config,
            include_deal_timing=False, deadline=deadline,
        )
