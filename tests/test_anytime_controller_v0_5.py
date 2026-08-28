from __future__ import annotations

import inspect
import random
import time
from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.analysis_budget import SearchDeadline
import spider.planner.anytime_controller as controller_module
import spider.planner.protected_conversion as conversion_module
from spider.planner.anytime_controller import (
    AnalysisStage,
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    analyze_stage0_state,
    analyze_strategic_state,
    freeze_active_rule_profile,
    generate_strategic_successors,
    retain_obligation_successors,
    solve_anytime,
    successor_pursues_pending_contract,
)
from spider.planner.deal_purpose import (
    DealPurposeKind,
    DealPurposeStatus,
    audit_successive_deal,
    contract_requires_descendant,
    create_deal_purpose_contract,
    validate_deal_purpose_contract,
)
from spider.planner.economic_project_realizer import measure_structural_state
from spider.planner.economic_projects import analyze_economic_projects
from spider.planner.foundation_campaign import CampaignReadiness
from spider.planner.pre_foundation_diversity import (
    build_pre_foundation_geometry,
    retain_pre_foundation_portfolio,
)
from spider.planner.protected_conversion import (
    NearRemovalConfig,
    ProtectedConversionBudget,
    ProtectedConversionStatus,
    RemovalRelevantMilestoneKind,
    TerminalAssemblyConfig,
    TerminalAssemblyStatus,
    campaign_is_near_removal,
    create_protected_conversion_lane,
    diagnose_terminal_conversion,
    evaluate_protected_conversion_lane,
    realize_terminal_campaign_assembly,
    removal_relevant_milestones,
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
        wall_clock_limit_s=10.0,
        max_strategic_expansions=1,
        max_tactical_nodes=100,
        max_frontier_size=32,
        max_successors_per_expansion=6,
        enable_campaign_edges=False,
        enable_campaign_corridors=False,
        enable_expensive_deal_timing=False,
    )
    snapshot = analyze_strategic_state(
        state,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    stage0 = analyze_stage0_state(state, spent_cost=0, incumbent_cost=None)
    node = StrategicSearchNode(
        node_id=0,
        state=state,
        g=0,
        actions=(),
        parent_id=None,
        incoming_edge=None,
        depth=0,
        credit_level=StrategicCreditLevel.CLEAN,
        analysis=snapshot,
        stage0=stage0,
    )
    return cards, state, config, snapshot, node


@pytest.fixture(scope="module")
def raw_successors(analyzed_opening):
    cards, _state, config, _snapshot, node = analyzed_opening
    telemetry = ControllerTelemetry()
    values = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    return values


@pytest.fixture(scope="module")
def contract_context(analyzed_opening):
    _cards, state, _config, snapshot, _node = analyzed_opening
    profile = snapshot.residual.checkpoint
    campaign = profile.best_readiness.campaign_label
    return state, profile, campaign


@pytest.fixture(scope="module")
def terminal_fixture(analyzed_opening):
    cards, _opening, _config, snapshot, _node = analyzed_opening
    original = snapshot.economic.campaign_portfolio.campaigns[0]
    suit = "c"
    band = [Card(suit, rank) for rank in range(13, 1, -1)]
    state = SpiderState(
        [Column([], band), Column([], [Card(suit, 1)])]
        + [Column([], []) for _ in range(8)],
        [],
    )
    needs = tuple(
        replace(need, chosen=None, must_excavate=False, reason="already exposed")
        for need in original.rank_needs
    )
    campaign = replace(
        original,
        suit=suit,
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        stock_plan=(),
        space_requirement=0,
        estimated_campaign_cost=1.0,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )
    return cards, state, campaign


def _changed_readiness(profile, campaign, **changes):
    values = tuple(
        replace(item, **changes) if item.campaign_label == campaign else item
        for item in profile.next_foundation_readiness
    )
    return replace(profile, next_foundation_readiness=values)


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_regression_archive_anchor_is_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (172, 174, 169)
    assert result.path_hash == "77d169da2538ba8c"


def test_03_every_generated_deal_successor_has_contract(raw_successors):
    deals = [item for item in raw_successors if ("deal",) in item.actions]
    assert deals and all(len(item.deal_contracts) == item.actions.count(("deal",)) for item in deals)


def test_04_raw_deal_has_purpose_metadata(raw_successors):
    deal = next(item for item in raw_successors if item.kind == StrategicActionKind.RAW_DEAL)
    assert deal.deal_contracts[0].purpose in (DealPurposeKind.INCONCLUSIVE, DealPurposeKind.ESCAPE_ONLY)


def test_05_strategic_unlock_requires_removal_evidence(contract_context):
    state, profile, campaign = contract_context
    current = next(item for item in profile.next_foundation_readiness if item.campaign_label == campaign)
    after = _changed_readiness(
        profile,
        campaign,
        must_dependencies_remaining=max(0, current.must_dependencies_remaining - 1),
    )
    contract = create_deal_purpose_contract(state, profile, after_profile=after, campaign_id=campaign)
    assert contract.purpose == DealPurposeKind.STRATEGIC_UNLOCK


def test_06_generic_activity_is_not_strategic_unlock(contract_context):
    state, profile, _campaign = contract_context
    after = replace(
        profile,
        legal_mobility=profile.legal_mobility + 5,
        current_epoch_actionable_high_value_projects=("generic-activity",),
    )
    contract = create_deal_purpose_contract(state, profile, after_profile=after)
    assert contract.purpose != DealPurposeKind.STRATEGIC_UNLOCK


def test_07_escape_only_can_be_produced(contract_context):
    state, profile, _campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, after_profile=profile)
    assert contract.purpose == DealPurposeKind.ESCAPE_ONLY


def test_08_inconclusive_can_be_produced(contract_context):
    state, profile, _campaign = contract_context
    assert create_deal_purpose_contract(state, profile).purpose == DealPurposeKind.INCONCLUSIVE


def test_09_applicable_contract_names_objective(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(
        state, profile, campaign_id=campaign, explicit_purpose=DealPurposeKind.CAMPAIGN_SUPPLY
    )
    assert contract.target_objective == campaign and contract.campaign_id == campaign


def test_10_contract_stores_surrendered_opportunities(raw_successors):
    contract = next(item for item in raw_successors if ("deal",) in item.actions).deal_contracts[0]
    assert isinstance(contract.surrendered_current_opportunities, tuple)


def test_11_contract_validation_can_fulfil(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(
        state, profile, campaign_id=campaign, explicit_purpose=DealPurposeKind.STRATEGIC_UNLOCK
    )
    current = next(item for item in profile.next_foundation_readiness if item.campaign_label == campaign)
    after = _changed_readiness(
        profile, campaign, must_dependencies_remaining=max(0, current.must_dependencies_remaining - 1)
    )
    assert validate_deal_purpose_contract(contract, after, current_depth=1).status == DealPurposeStatus.FULFILLED


def test_12_contract_validation_can_partially_fulfil(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(
        state, profile, campaign_id=campaign, explicit_purpose=DealPurposeKind.STRATEGIC_UNLOCK
    )
    after = replace(profile, total_campaign_must_burden=profile.total_campaign_must_burden - 1)
    assert validate_deal_purpose_contract(contract, after, current_depth=1).status == DealPurposeStatus.PARTIALLY_FULFILLED


def test_13_contract_validation_can_fail(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(
        state,
        profile,
        campaign_id=campaign,
        explicit_purpose=DealPurposeKind.STRATEGIC_UNLOCK,
        horizon_expansions=1,
    )
    assert validate_deal_purpose_contract(contract, profile, current_depth=1).status == DealPurposeStatus.FAILED


def test_14_contract_validation_can_invalidate(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    outcome = validate_deal_purpose_contract(
        contract, profile, current_depth=0, objective_still_credible=False
    )
    assert outcome.status == DealPurposeStatus.INVALIDATED


def test_15_failed_purpose_has_no_proof_authority(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign, horizon_expansions=1)
    outcome = validate_deal_purpose_contract(contract, profile, current_depth=1)
    assert not contract.proof_pruning_allowed and not outcome.proof_pruning_allowed


def test_16_pending_purpose_can_protect_one_descendant(analyzed_opening, contract_context, raw_successors):
    _cards, _state, _config, _snapshot, node = analyzed_opening
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    obligated = replace(node, active_deal_contracts=(contract,))
    candidate = replace(raw_successors[0], label=f"advance {campaign}", source_project_id=campaign)
    retained = retain_obligation_successors(obligated, (candidate,), (), maximum=1)
    assert retained == (candidate,)


def test_17_pending_purpose_does_not_force_all_descendants(analyzed_opening, contract_context, raw_successors):
    _cards, _state, _config, _snapshot, node = analyzed_opening
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    obligated = replace(node, active_deal_contracts=(contract,))
    unrelated = replace(raw_successors[0], label="unrelated", source_project_id=None)
    assert not successor_pursues_pending_contract(obligated, unrelated)


def test_18_successive_deal_audit_records_outcome(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    outcome = validate_deal_purpose_contract(contract, profile, current_depth=0)
    audit = audit_successive_deal(contract, outcome, deal_ordinal=2)
    assert audit.status_before_next_deal == DealPurposeStatus.PENDING


def test_19_new_deal_remains_legal_with_pending_purpose(analyzed_opening, contract_context, raw_successors):
    _cards, _state, _config, _snapshot, node = analyzed_opening
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    obligated = replace(node, active_deal_contracts=(contract,), credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK)
    assert obligated.state.can_deal(MW_RULES)
    assert any(item.kind == StrategicActionKind.RAW_DEAL for item in raw_successors)


def test_20_protected_lane_survives_ordinary_competition(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(profile, campaign_id=campaign)
    assert lane is not None
    result = evaluate_protected_conversion_lane(
        lane, profile, current_expansion=1, current_elapsed_seconds=1.0
    )
    assert result.status == ProtectedConversionStatus.CONTINUE


def test_21_protected_lane_expires_at_bound(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(
        profile, campaign_id=campaign, budget=ProtectedConversionBudget(max_descendant_expansions=1)
    )
    result = evaluate_protected_conversion_lane(
        lane, profile, current_expansion=1, current_elapsed_seconds=0.0
    )
    assert result.status == ProtectedConversionStatus.EXPIRED


def test_22_protected_lane_stops_on_invalidation(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(profile, campaign_id=campaign)
    result = evaluate_protected_conversion_lane(
        lane,
        profile,
        current_expansion=0,
        current_elapsed_seconds=0.0,
        objective_still_credible=False,
    )
    assert result.status == ProtectedConversionStatus.INVALIDATED


def test_23_protected_lane_succeeds_on_foundation_increase(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(profile, campaign_id=campaign)
    result = evaluate_protected_conversion_lane(
        lane,
        replace(profile, foundations=lane.target_foundation_count),
        current_expansion=1,
        current_elapsed_seconds=1.0,
    )
    assert result.status == ProtectedConversionStatus.SUCCESS


def test_24_removal_relevant_milestones_are_structural(contract_context):
    _state, profile, campaign = contract_context
    before = next(item for item in profile.next_foundation_readiness if item.campaign_label == campaign)
    after = replace(before, receiver_conditions_ready=before.receiver_conditions_ready + 1)
    values = removal_relevant_milestones(
        before, after, foundation_count=profile.foundations, target_foundation_count=profile.foundations + 1
    )
    assert RemovalRelevantMilestoneKind.RECEIVER_OBLIGATION_SATISFIED in values


def test_25_same_suit_mass_alone_is_not_milestone(contract_context):
    _state, profile, campaign = contract_context
    readiness = next(item for item in profile.next_foundation_readiness if item.campaign_label == campaign)
    assert removal_relevant_milestones(
        readiness, readiness, foundation_count=profile.foundations, target_foundation_count=profile.foundations + 1
    ) == ()


def test_26_face_down_reduction_alone_is_not_milestone(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(profile, campaign_id=campaign)
    changed = replace(profile, face_down_count=profile.face_down_count - 1)
    assert evaluate_protected_conversion_lane(
        lane, changed, current_expansion=1, current_elapsed_seconds=1.0
    ).status == ProtectedConversionStatus.CONTINUE


def test_27_terminal_diagnosis_lists_required_sources(analyzed_opening):
    _cards, state, _config, snapshot, _node = analyzed_opening
    result = diagnose_terminal_conversion(state, snapshot.economic.campaign_portfolio.campaigns)
    assert any(item.remaining_must_sources for item in result.target_campaigns)


def test_28_terminal_diagnosis_lists_receiver_or_workspace_blocker(analyzed_opening):
    _cards, state, _config, snapshot, _node = analyzed_opening
    result = diagnose_terminal_conversion(state, snapshot.economic.campaign_portfolio.campaigns)
    assert any(
        item.receiver_blockers or item.workspace_blockers or item.minimal_bounded_tactical_blockers
        for item in result.target_campaigns
    )


def test_29_terminal_assembly_only_activates_near_removal(analyzed_opening):
    _cards, state, _config, snapshot, _node = analyzed_opening
    campaign = snapshot.economic.campaign_portfolio.campaigns[0]
    result = realize_terminal_campaign_assembly(state, campaign)
    assert result.status == TerminalAssemblyStatus.NOT_NEAR_REMOVAL


def test_30_terminal_assembly_contains_no_benchmark_constants():
    source = inspect.getsource(conversion_module)
    assert "4925153" not in source and "924bfd20" not in source


def test_31_terminal_assembly_success_replays(terminal_fixture):
    _cards, state, campaign = terminal_fixture
    result = realize_terminal_campaign_assembly(state, campaign)
    assert result.status == TerminalAssemblyStatus.FOUNDATION_REMOVED
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost
    assert canonical_state_key(replay) == canonical_state_key(result.end_state)


def test_32_terminal_miss_has_no_proof_authority(terminal_fixture):
    _cards, state, campaign = terminal_fixture
    result = realize_terminal_campaign_assembly(
        state, campaign, config=TerminalAssemblyConfig(max_added_cost=1, max_nodes=1, time_limit_s=0.1)
    )
    assert result.proof_pruning_allowed is False


def test_33_pre_foundation_diversity_preserves_distinct_geometry():
    a = SpiderState([Column([], [Card("c", 7)])] + [Column([], []) for _ in range(9)], [])
    b = SpiderState([Column([], [Card("d", 7)])] + [Column([], []) for _ in range(9)], [])
    portfolio = retain_pre_foundation_portfolio(
        (build_pre_foundation_geometry(a, g=0), build_pre_foundation_geometry(b, g=1)), maximum=3
    )
    assert len(portfolio.geometries) == 2


def test_34_identical_structural_states_deduplicate():
    state = SpiderState([Column([], [Card("c", 7)])] + [Column([], []) for _ in range(9)], [])
    a = build_pre_foundation_geometry(state, g=2)
    b = build_pre_foundation_geometry(state.clone(), g=1)
    portfolio = retain_pre_foundation_portfolio((a, b), maximum=3)
    assert len(portfolio.geometries) == 1 and portfolio.geometries[0].g == 1


def test_35_action_history_is_absent_from_geometry_key():
    state = SpiderState([Column([], [Card("c", 7)])] + [Column([], []) for _ in range(9)], [])
    a = build_pre_foundation_geometry(state, g=1)
    b = build_pre_foundation_geometry(state, g=4)
    assert a.geometry_key() == b.geometry_key()


def test_36_distinct_higher_g_geometry_survives():
    a = SpiderState([Column([], [Card("c", 7)])] + [Column([], []) for _ in range(9)], [])
    b = SpiderState([Column([], [Card("c", 7)]), Column([], [Card("d", 6)])] + [Column([], []) for _ in range(8)], [])
    portfolio = retain_pre_foundation_portfolio(
        (build_pre_foundation_geometry(a, g=0), build_pre_foundation_geometry(b, g=7)), maximum=3
    )
    assert any(item.g == 7 for item in portfolio.geometries)


def test_37_cheaper_identical_state_tt_dominates():
    state = SpiderState([Column([], [Card("c", 7)])] + [Column([], []) for _ in range(9)], [])
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 3) and tt.admit(state, 2) and not tt.admit(state, 2)


def test_38_historical_checkpoint_cost_is_not_controller_constant():
    source = inspect.getsource(controller_module)
    assert "cost_21" not in source and "cost21" not in source


def test_39_no_production_suit_target_constant():
    source = inspect.getsource(controller_module)
    assert "target_suit" not in source and "Spades" not in source


def test_40_canonical_future_actions_are_not_solver_input():
    signature = inspect.signature(solve_anytime)
    assert "route" not in signature.parameters and "checkpoint" not in signature.parameters


def test_41_external_record_never_enters_pruning(analyzed_opening):
    _cards, _state, _config, snapshot, _node = analyzed_opening
    assert snapshot.budget.incumbent_cost is None


def test_42_staged_analysis_remains_correct(analyzed_opening):
    _cards, _state, _config, snapshot, node = analyzed_opening
    assert node.stage0.stage == AnalysisStage.EXACT_CHEAP_FACTS
    assert snapshot.stage >= AnalysisStage.STRATEGIC_CORE


def test_43_deadline_propagates_to_terminal_search(terminal_fixture):
    _cards, state, campaign = terminal_fixture
    now = time.perf_counter()
    deadline = SearchDeadline(absolute_deadline=now - 0.01, started_at=now - 1.0)
    result = realize_terminal_campaign_assembly(state, campaign, deadline=deadline)
    assert result.status == TerminalAssemblyStatus.RESOURCE_LIMIT


def test_44_contracts_do_not_enter_admissible_h(contract_context):
    state, profile, campaign = contract_context
    contract = create_deal_purpose_contract(state, profile, campaign_id=campaign)
    assert contract.proof_pruning_allowed is False


def test_45_protected_lanes_do_not_enter_admissible_h(contract_context):
    _state, profile, campaign = contract_context
    lane = create_protected_conversion_lane(profile, campaign_id=campaign)
    assert lane is not None and lane.proof_pruning_allowed is False


@pytest.mark.parametrize("seed", (7301, 7302))
def test_46_unseen_deals_exercise_generic_contract_lane_logic(seed):
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
            wall_clock_limit_s=4.0,
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
    assert result.telemetry.deal_contracts_created >= 1
    assert result.elapsed_seconds <= 6.0
