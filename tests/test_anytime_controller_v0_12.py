"""v0.12 multi-primitive closure continuation and endpoint gates."""

from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import (
    MoveLifecycleAssessment,
    PlacementClass,
    assess_tableau_move,
    stable_join_dominates,
)
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicTranspositionTable,
    analyze_strategic_state,
    freeze_active_rule_profile,
)
from spider.planner.buried_source_closure import (
    ClosureCandidateRejectionReason,
    ClosureFailureDiagnosis,
    ClosureProgressKind,
    compare_legal_candidate_coverage,
    describe_buried_source,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    ClosureCompletionClass,
    ClosureEndpointAssessment,
    DependencyClosureConfig,
    DependencyClosureStatus,
    DependencyClosureStep,
    assess_closure_endpoint,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
    summarize_closure_lifecycle,
)
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment,
    MilestonePrimitiveStep,
    realize_milestone,
)
from spider.planner.strategic_milestone import (
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestonePrerequisite,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    evaluate_milestone_progress,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.planner.tactical_resource_allocator import TacticalResourceAllocatorConfig
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit: str, rank: int) -> RankSource:
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "generic v0.12 fixture",
    )


@pytest.fixture(scope="module")
def base_campaign():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=2.0,
        max_strategic_expansions=1,
        max_tactical_nodes=100,
        max_frontier_size=16,
        enable_campaign_edges=False,
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
    return analysis.economic.campaign_portfolio.campaigns[0]


def _campaign(base, suit: str = "c", rank: int = 5, space: int = 0):
    needs = tuple(
        replace(
            need,
            chosen=_source(suit, need.rank) if need.rank == rank else None,
            must_excavate=need.rank == rank,
            reason="generic named source",
        )
        for need in base.rank_needs
    )
    return replace(
        base,
        suit=suit,
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(item.chosen for item in needs if item.chosen),
        future_stock_supplied_cards=(),
        optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(),
        shared_prerequisite_tasks=(),
        space_requirement=space,
        stock_plan=(),
        estimated_campaign_cost=4.0,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )


def _run(state, campaign, *, rank=5, cost=8, nodes=400, beam=192, audit=True):
    return realize_campaign_dependency_closure(
        state,
        campaign,
        target_dependency_id=f"source:{rank}:c",
        semantic_target_id="generic-source-chain",
        config=DependencyClosureConfig(
            max_added_cost=cost,
            max_nodes=nodes,
            time_limit_s=1.5,
            beam_width=beam,
            enable_legal_candidate_audit=audit,
        ),
    )


@pytest.fixture
def two_blocker_case(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)],
            [Card("s", 5)],
            [Card("d", 6)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    return state, _campaign(base_campaign)


@pytest.fixture
def receiver_two_blocker_case(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)],
            [Card("s", 5), Card("s", 9)],
            [Card("s", 10)],
            [Card("d", 6)],
            *([Card("h", 1)] for _ in range(6)),
        ),
        [],
    )
    return state, _campaign(base_campaign)


@pytest.fixture
def workspace_case(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 7), Card("d", 6), Card("d", 5)],
            [Card("s", 9)],
            [Card("s", 10)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    return state, _campaign(base_campaign, rank=7)


@pytest.fixture
def park_case(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 7), Card("d", 6), Card("h", 5)],
            [Card("s", 6)],
            [Card("s", 7)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    return state, _campaign(base_campaign, rank=7)


def _step(action, lifecycle):
    return DependencyClosureStep(
        action,
        lifecycle.immediate_cost,
        ("source:7:c",),
        "lifecycle fixture",
        lifecycle,
        1,
        1,
        0,
        0,
    )


def _milestone(state):
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.DURABLE_RUN,
        "build a three-card club run",
        suit="c",
        minimum_run_length=3,
    )
    return StrategicMilestone(
        "v012-fixture",
        canonical_state_key(state),
        "C#1",
        "C#1",
        StrategicMilestoneKind.SOURCE_CHAIN,
        target,
        "c",
        (7, 6, 5),
        ("fixture",),
        (StrategicMilestonePrerequisite("source", "expose source"),),
        StrategicMilestoneProgress(1, 3),
        2,
        4,
        3,
        4.0,
        12_000,
        "three-card run exists",
        "fresh analysis contradicts target",
        None,
    )


def _outer_conversion(max_steps=4):
    start = SpiderState(
        _columns([Card("c", 7)], [Card("c", 6)], [Card("c", 5)]), []
    )
    milestone = _milestone(start)

    def primitive(state, _active, *_limits):
        first = bool(state.columns[1].face_up)
        action = (1, 0, 1) if first else (2, 0, 1)
        end = state.clone()
        cost = end.move(*action)
        return MilestonePrimitiveStep(
            (action,),
            end,
            cost,
            1,
            ("source chain",),
            True,
            "fresh source-chain step",
            target_dependency_id="source:5:c",
            semantic_target_id="semantic-source-chain",
            closure_completion_class=(
                ClosureCompletionClass.DEPENDENCY_ADVANCED.value
                if first
                else ClosureCompletionClass.SOURCE_EXPOSED.value
            ),
            closure_requested_dependency_completed=not first,
            closure_advanced_fallback=first,
            closure_source_depth_before=2 if first else 1,
            closure_source_depth_after=1 if first else 0,
            closure_primitive_count=1,
        )

    def fresh(state, prior):
        return FreshMilestoneAssessment(
            prior, evaluate_milestone_progress(state, prior), reason="fresh exact analysis"
        )

    return realize_milestone(
        start,
        milestone,
        primitive,
        fresh,
        max_primitive_steps=max_steps,
    )


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_rule_profile_remains_unrestricted():
    cards = tuple(load_deal(DEAL))
    profile = freeze_active_rule_profile(SpiderState.from_cards(cards), cards)
    assert profile.profile.can_deal_into_empty


def test_03_closure_resources_are_unchanged():
    config = DependencyClosureConfig()
    assert (config.max_added_cost, config.max_nodes, config.time_limit_s, config.beam_width) == (
        14, 4_000, 2.0, 192
    )


def test_04_milestone_resources_are_unchanged():
    config = AnytimeControllerConfig()
    assert (
        config.milestone_max_primitive_steps,
        config.milestone_max_strategic_expansions,
        config.milestone_max_time_s_per_expansion,
        config.milestone_max_nodes_per_expansion,
    ) == (4, 3, 4.0, 12_000)


def test_05_allocator_tranches_are_unchanged():
    config = TacticalResourceAllocatorConfig()
    assert tuple((item.max_added_cost, item.max_nodes, item.max_seconds) for item in config.tiers) == (
        (2, 128, 0.10), (4, 512, 0.35), (8, 2_000, 1.25), (18, 8_000, 2.00)
    )


def test_06_canonical_anchor_is_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.explicit_commands, result.tableau_moves) == (
        172, 174, 169
    )


def test_07_canonical_anchor_hashes_are_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.stock_deals, result.foundations, result.path_hash, result.state_hash) == (
        5, 8, "77d169da2538ba8c", "4e9861540eac570cb"
    )


def test_08_completion_and_advancement_are_distinct():
    assert ClosureCompletionClass.DEPENDENCY_COMPLETED != ClosureCompletionClass.DEPENDENCY_ADVANCED


def test_09_typed_outcomes_are_inspectable():
    assert {item.value for item in ClosureCompletionClass} == {
        "DEPENDENCY_COMPLETED", "SOURCE_EXPOSED", "DEPENDENCY_ADVANCED",
        "NO_TARGET_PROGRESS", "STRUCTURAL_BLOCKER", "RESOURCE_BOUND",
        "TARGET_INVALIDATED",
    }


def test_10_first_depth_reduction_is_advanced(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    first = result.steps[0].progress_evidence
    assert first.kind == ClosureProgressKind.SOURCE_DEPTH_REDUCED
    assert not first.source_exposed


def test_11_gate_a_continues_after_first_depth_reduction(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert len(result.actions) == 2 and result.advanced_states_continued >= 1


def test_12_gate_a_completes_in_one_call(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert result.status == DependencyClosureStatus.DEPENDENCY_CLOSED
    assert result.completion_class == ClosureCompletionClass.SOURCE_EXPOSED


def test_13_gate_a_replays(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost
    assert states_structurally_equal(replay, result.end_state)


def test_14_gate_a_source_id_can_survive_as_exposed(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    fresh = next(item for item in result.graph_after.dependencies if item.dependency_id == "source:5:c")
    assert fresh.kind == CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED


def test_15_gate_a_requested_dependency_is_complete(two_blocker_case):
    state, campaign = two_blocker_case
    endpoint = _run(state, campaign).endpoint_assessment
    assert endpoint.requested_dependency_completed and endpoint.source_exposed
    assert not endpoint.source_consumed


def test_16_gate_b_receiver_is_first_prerequisite(receiver_two_blocker_case):
    state, campaign = receiver_two_blocker_case
    result = _run(state, campaign)
    assert result.steps[0].progress_evidence.kind == ClosureProgressKind.RECEIVER_CREATED


def test_17_gate_b_receiver_does_not_end_call(receiver_two_blocker_case):
    state, campaign = receiver_two_blocker_case
    result = _run(state, campaign)
    assert len(result.actions) == 3 and result.actions[0] == (1, 2, 1)


def test_18_gate_b_completion_outranks_receiver_endpoint(receiver_two_blocker_case):
    state, campaign = receiver_two_blocker_case
    result = _run(state, campaign)
    assert result.completion_class == ClosureCompletionClass.SOURCE_EXPOSED
    assert result.endpoint_assessment.primitive_count == 3


def test_19_gate_b_replays(receiver_two_blocker_case):
    state, campaign = receiver_two_blocker_case
    result = _run(state, campaign)
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost


def test_20_gate_c_workspace_creation_does_not_end_call(workspace_case):
    state, campaign = workspace_case
    result = _run(state, campaign, rank=7)
    assert len(result.actions) == 2 and result.steps[0].progress_evidence.workspace_created


def test_21_gate_c_blocker_run_moves_together(workspace_case):
    state, campaign = workspace_case
    result = _run(state, campaign, rank=7)
    assert result.actions[1][2] == 2


def test_22_gate_c_workspace_is_used_for_exposure(workspace_case):
    state, campaign = workspace_case
    result = _run(state, campaign, rank=7)
    assert result.steps[1].lifecycle.placement_class == PlacementClass.WORKSPACE_PARK
    assert result.endpoint_assessment.source_exposed


def test_23_gate_c_workspace_exit_is_bounded(workspace_case):
    state, campaign = workspace_case
    result = _run(state, campaign, rank=7)
    assert result.steps[1].lifecycle.exit_route_bounded


def test_24_gate_c_replays(workspace_case):
    state, campaign = workspace_case
    result = _run(state, campaign, rank=7)
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost


def test_25_gate_d_temporary_midpoint_debt_is_explicit(park_case):
    state, campaign = park_case
    result = _run(state, campaign, rank=7)
    assert result.endpoint_assessment.lifecycle.midpoint_rehandling_debt > 0


def test_26_gate_d_midpoint_does_not_beat_completion(park_case):
    state, campaign = park_case
    result = _run(state, campaign, rank=7)
    assert len(result.actions) == 2
    assert result.completion_class == ClosureCompletionClass.SOURCE_EXPOSED


def test_27_gate_d_every_selected_park_has_exit(park_case):
    state, campaign = park_case
    result = _run(state, campaign, rank=7)
    parks = [step.lifecycle for step in result.steps if step.lifecycle.placement_class == PlacementClass.MIXED_SUIT_PARK]
    assert parks and all(item.exit_route_bounded and item.future_exit_route for item in parks)


def test_28_unexplained_park_remains_rejected(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 7)], [Card("h", 8)],
            *([Card("h", 1)] for _ in range(8)),
        ),
        [],
    )
    result = _run(state, _campaign(base_campaign))
    audits = result.buried_source_traces[0].candidate_audits
    assert any(
        item.rejection_reason == ClosureCandidateRejectionReason.TEMPORARY_PARK_NO_EXIT
        for item in audits
    )


def test_29_stable_same_suit_dominance_remains():
    state = SpiderState(
        _columns([Card("c", 6)], [Card("c", 5)], [Card("h", 6)]), []
    )
    stable = assess_tableau_move(state, (1, 0, 1))
    park = assess_tableau_move(state, (1, 2, 1))
    assert stable_join_dominates(stable, park, comparable_effects=True)


def test_30_stable_break_requires_bounded_target_compensation():
    state = SpiderState(_columns([Card("d", 7), Card("d", 6)], [Card("s", 7)]), [])
    lifecycle = assess_tableau_move(state, (0, 1, 1))
    assert lifecycle.same_suit_joins_broken and lifecycle.exit_route_bounded


def test_31_restore_sequence_is_detected():
    state = SpiderState(_columns([Card("d", 7), Card("d", 6)], [Card("s", 7)]), [])
    broken = assess_tableau_move(state, (0, 1, 1))
    state.move(0, 1, 1)
    restored = assess_tableau_move(state, (1, 0, 1))
    summary = summarize_closure_lifecycle((_step((0, 1, 1), broken), _step((1, 0, 1), restored)))
    assert summary.same_suit_joins_broken == 1
    assert summary.stable_joins_restored_or_replaced == 1


def test_32_restore_sequence_records_midpoint_and_final_debt():
    state = SpiderState(_columns([Card("d", 7), Card("d", 6)], [Card("s", 7)]), [])
    broken = assess_tableau_move(state, (0, 1, 1))
    state.move(0, 1, 1)
    restored = assess_tableau_move(state, (1, 0, 1))
    summary = summarize_closure_lifecycle((_step((0, 1, 1), broken), _step((1, 0, 1), restored)))
    assert summary.midpoint_rehandling_debt >= summary.final_rehandling_debt


def test_33_replacement_need_not_use_the_original_boundary_label():
    broken = MoveLifecycleAssessment(
        (0, 1, 1), PlacementClass.MIXED_SUIT_PARK, 1, (), ("d7-d6@c1",),
        ("s7-d6@c2",), (), "bounded replacement", True, 2.0,
    )
    replacement = MoveLifecycleAssessment(
        (1, 2, 1), PlacementClass.STABLE_SAME_SUIT_JOIN, 1,
        ("d7-d6@c3",), (), (), ("s7-d6@c2",), "permanent band", True, 0.0,
    )
    summary = summarize_closure_lifecycle((_step((0, 1, 1), broken), _step((1, 2, 1), replacement)))
    assert summary.stable_joins_restored_or_replaced == 1


def test_34_restoration_is_not_required_before_exposure(park_case):
    state, campaign = park_case
    endpoint = _run(state, campaign, rank=7).endpoint_assessment
    assert endpoint.source_exposed and endpoint.lifecycle.final_rehandling_debt > 0


def test_35_gate_f_best_advanced_fallback_survives(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign, cost=1)
    assert result.status == DependencyClosureStatus.DEPENDENCY_ADVANCED
    assert result.completion_class == ClosureCompletionClass.DEPENDENCY_ADVANCED
    assert result.actions == ((0, 1, 1),)


def test_36_gate_f_advanced_fallback_is_resource_bound(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign, cost=1)
    assert result.failure_diagnosis == ClosureFailureDiagnosis.RESOURCE_BOUND
    assert result.advanced_fallback_returned


def test_37_gate_f_advanced_fallback_keeps_fresh_target(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign, cost=1)
    endpoint = result.endpoint_assessment
    assert endpoint.target_dependency_id == "source:5:c"
    assert endpoint.same_semantic_target_valid and endpoint.continuation_available


def test_38_gate_f_advanced_fallback_replays(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign, cost=1)
    replay = state.clone()
    assert replay_actions(replay, list(result.actions)) == result.corrected_added_cost
    assert states_structurally_equal(replay, result.end_state)


def test_39_gate_g_outer_boundary_continues_same_target():
    result = _outer_conversion()
    assert result.same_target_continuations == 1
    assert result.closure_target_timeline == (
        "semantic-source-chain", "semantic-source-chain"
    )


def test_40_gate_g_outer_boundary_completes_persisted_target():
    result = _outer_conversion()
    assert result.persisted_target_completed
    assert result.status == StrategicMilestoneStatus.ACHIEVED


def test_41_gate_g_outer_boundary_replays():
    result = _outer_conversion()
    assert result.independent_replay_verified and result.primitive_steps == 2


def test_42_gate_g_partial_outer_result_keeps_advanced_metadata():
    result = _outer_conversion(max_steps=1)
    assert result.status == StrategicMilestoneStatus.ADVANCED
    assert result.advanced_closure_steps == 1 and result.advanced_fallbacks == 1


def test_43_gate_h_copy_substitution_is_fresh(base_campaign):
    state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 4)],
            [Card("c", 5), Card("s", 9)],
            [Card("s", 10)],
            [Card("h", 6)],
            *([Card("h", 1)] for _ in range(6)),
        ),
        [],
    )
    result = _run(state, _campaign(base_campaign))
    assert result.buried_source_traces[0].source_copy_substitutions >= 1
    assert result.endpoint_assessment.same_semantic_target_valid


def test_44_gate_i_completion_is_immediate(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert result.steps[-1].progress_evidence.source_exposed
    assert result.endpoint_assessment.source_depth_after == 0


def test_45_gate_i_no_registration_move_is_added(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert result.actions == ((0, 1, 1), (0, 2, 1))


def test_46_source_consumption_can_be_classified_when_integrated(base_campaign):
    campaign = _campaign(base_campaign)
    start = SpiderState(
        _columns(
            [Card("c", 5)], [Card("c", 6), Card("s", 9)], [Card("s", 10)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    before = build_campaign_dependency_graph(start, campaign)
    end = start.clone()
    end.move(1, 2, 1)
    end.move(0, 1, 1)
    after = build_campaign_dependency_graph(end, campaign)
    endpoint = assess_closure_endpoint(
        start, end, campaign, before, after, "source:5:c"
    )
    assert endpoint.requested_dependency_completed and endpoint.source_consumed


def test_47_gate_j_completed_endpoint_outranks_advanced(two_blocker_case):
    state, campaign = two_blocker_case
    advanced = _run(state, campaign, cost=1).endpoint_assessment
    completed = _run(state, campaign, cost=8).endpoint_assessment
    assert completed.ordering_key() < advanced.ordering_key()


def test_48_gate_j_source_exposure_outranks_depth_only(two_blocker_case):
    state, campaign = two_blocker_case
    advanced = _run(state, campaign, cost=1).endpoint_assessment
    exposed = _run(state, campaign, cost=8).endpoint_assessment
    assert exposed.completion_class == ClosureCompletionClass.SOURCE_EXPOSED
    assert exposed.ordering_key() < advanced.ordering_key()


def test_49_gate_j_lifecycle_debt_orders_same_completion_class(two_blocker_case):
    state, campaign = two_blocker_case
    endpoint = _run(state, campaign).endpoint_assessment
    low = replace(endpoint, lifecycle=replace(endpoint.lifecycle, final_rehandling_debt=0.0))
    high = replace(endpoint, lifecycle=replace(endpoint.lifecycle, final_rehandling_debt=9.0))
    assert low.ordering_key() < high.ordering_key()


def test_50_resource_bound_is_not_search_policy(two_blocker_case):
    state, campaign = two_blocker_case
    assert _run(state, campaign, cost=1).failure_diagnosis == ClosureFailureDiagnosis.RESOURCE_BOUND


def test_51_search_policy_detection_remains_available():
    audit = compare_legal_candidate_coverage(
        "source:5:c", ((0, 1, 1), (0, 2, 1)), ((0, 1, 1),)
    )
    assert audit.failure_diagnosis == ClosureFailureDiagnosis.SEARCH_POLICY


def test_52_completion_policy_has_no_proof_authority(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert not result.proof_pruning_allowed
    assert not result.endpoint_assessment.proof_pruning_allowed
    assert not result.endpoint_assessment.lifecycle.proof_pruning_allowed


def test_53_completion_metadata_does_not_enter_state_identity(two_blocker_case):
    state, campaign = two_blocker_case
    before = canonical_state_key(state)
    _run(state, campaign)
    assert canonical_state_key(state) == before


def test_54_lower_g_exact_state_dominance_is_unchanged():
    state = SpiderState(_columns([Card("c", 7)]), [])
    table = StrategicTranspositionTable()
    assert table.admit(state, 5)
    assert table.admit(state.clone(), 4)
    assert not table.admit(state.clone(), 6)


def test_55_contextual_duplicate_cannot_override_exact_tt():
    state = SpiderState(_columns([Card("c", 7)]), [])
    table = StrategicTranspositionTable()
    assert table.admit(state, 2, heuristic_score=ClosureCompletionClass.DEPENDENCY_ADVANCED)
    assert not table.admit(state.clone(), 2, heuristic_score=ClosureCompletionClass.DEPENDENCY_COMPLETED)


def test_56_raw_fallback_remains_represented():
    source = inspect.getsource(controller_module.generate_strategic_successors)
    assert "raw_fallback" in source


def test_57_deal_remains_represented():
    source = inspect.getsource(controller_module.generate_strategic_successors)
    assert "exact legal Deal fallback" in source and "purposeful Deal" in source


def test_58_late_suit_construction_remains_represented():
    state = SpiderState(
        _columns([Card("c", 6)], [Card("c", 5)]), [Card("h", 9)] * 20
    )
    assert analyze_same_suit_construction(state).opportunities


def test_59_expensive_unqualified_removal_remains_gated():
    source = inspect.getsource(controller_module._foundation_successors)
    assert "campaign_is_near_removal" in source


def test_60_no_benchmark_route_or_hash_is_in_production_policy():
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src" / "spider" / "planner").glob("*.py")
    )
    assert "924bfd20deac96af" not in source
    assert "77d169da2538ba8c" not in source


def test_61_external_119_is_absent_from_production_policy():
    source = inspect.getsource(controller_module)
    assert "119-move" not in source and "external 119" not in source


def test_62_canonical_future_solution_is_not_loaded_prospectively():
    source = inspect.getsource(controller_module.solve_anytime)
    assert "solutions/" not in source and "canonical.moves" not in source


@pytest.mark.parametrize("seed", (12012, 12013))
def test_63_unseen_deal_smoke_has_fresh_generic_semantics(seed):
    cards = [
        Card(suit, rank)
        for suit in "cdhs"
        for rank in range(1, 14)
        for _ in range(2)
    ]
    random.Random(seed).shuffle(cards)
    frozen = tuple(cards)
    state = SpiderState.from_cards(frozen)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=1.0,
        max_strategic_expansions=1,
        max_tactical_nodes=64,
        max_frontier_size=16,
    )
    analysis = analyze_strategic_state(
        state,
        frozen,
        spent_cost=0,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    assert analysis.economic.campaign_portfolio.campaigns
    assert state.can_deal(MW_RULES)


def test_64_telemetry_exposes_completion_counts():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {
        "closure_targeted_calls", "closure_dependency_completed",
        "closure_source_exposed", "closure_dependency_advanced",
        "closure_resource_bound", "closure_structural_blocker",
    } <= set(fields)


def test_65_telemetry_exposes_continuation_counts():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {
        "closure_advanced_states_continued", "closure_advanced_fallbacks",
        "closure_advanced_persisted_across_expansions",
        "closure_persisted_targets_completed",
    } <= set(fields)


def test_66_telemetry_exposes_primitive_sequence_counts():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {
        "closure_primitives_total", "closure_max_primitive_sequence",
        "closure_receiver_blocker_exposure_chains",
        "closure_workspace_blocker_exposure_chains",
        "closure_park_blocker_exposure_chains",
    } <= set(fields)


def test_67_telemetry_exposes_lifecycle_counts():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {
        "closure_stable_joins_restored_or_replaced",
        "closure_midpoint_rehandling_debt", "closure_final_rehandling_debt",
        "closure_projected_compensation_accepted",
        "closure_projected_compensation_rejected",
    } <= set(fields)


def test_68_result_reports_primitives_per_closure(receiver_two_blocker_case):
    state, campaign = receiver_two_blocker_case
    result = _run(state, campaign)
    assert result.endpoint_assessment.primitive_count == len(result.steps) == 3


def test_69_result_reports_natural_exposure_rate_input(two_blocker_case):
    state, campaign = two_blocker_case
    trace = _run(state, campaign).buried_source_traces[0]
    assert trace.sources_exposed == 1 and not trace.source_consumed


def test_70_stale_target_is_typed_invalidated(two_blocker_case):
    state, campaign = two_blocker_case
    result = realize_campaign_dependency_closure(
        state, campaign, target_dependency_id="source:13:s"
    )
    assert result.status == DependencyClosureStatus.INVALIDATED
    assert result.completion_class == ClosureCompletionClass.TARGET_INVALIDATED


def test_71_fresh_coordinates_are_recorded_after_each_primitive(two_blocker_case):
    state, campaign = two_blocker_case
    result = _run(state, campaign)
    assert result.endpoint_assessment.source_key_before
    assert result.endpoint_assessment.source_key_after


def test_72_endpoint_assessment_is_directly_inspectable(two_blocker_case):
    state, campaign = two_blocker_case
    endpoint = _run(state, campaign).endpoint_assessment
    assert isinstance(endpoint, ClosureEndpointAssessment)
    assert endpoint.primitive_count == 2
