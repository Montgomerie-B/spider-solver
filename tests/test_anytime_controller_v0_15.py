from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

import pytest

import spider.planner.anytime_controller as controller_module
from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import (
    PlacementClass,
    assess_tableau_move,
    stable_join_dominates,
)
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    _node_priority,
    _reserve_completion_representative,
    _trim_frontier_with_checkpoint_diversity,
    analyze_stage0_state,
    retain_diverse_portfolio,
)
from spider.planner.campaign_dependency_closure import DependencyClosureConfig
from spider.planner.completion_cash_out import (
    CompletionCashOutDisposition,
    CompletionCashOutStatus,
    CompletionHarvestKind,
    CompletionStructuralMetrics,
    assess_completion_harvest,
    combine_completion_harvest,
    make_completion_cash_out_opportunity,
    rank_completion_opportunities,
    reconstruct_completion_satisfactions,
)
from spider.planner.residual_campaign import FoundationCheckpointPortfolio
from spider.planner.source_completion import (
    SourceCompletionPropagationTrace,
    SourceCompletionStage,
    SourceRequirementSatisfactionState,
    physical_source_identity,
    semantic_source_requirement,
    source_completion_event,
)
from spider.planner.tactical_resource_allocator import (
    TacticalResourceAllocatorConfig,
    TacticalResourceTier,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source_state() -> SpiderState:
    return SpiderState(
        _columns(
            [Card("c", 5)],
            [Card("c", 6)],
            [Card("d", 6)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )


def _event(state: SpiderState, *, target=("generic", "source"), dependency="source:5:c"):
    requirement = semantic_source_requirement(target, dependency, Card("c", 5))
    physical = physical_source_identity(
        Card("c", 5),
        dependency_id=dependency,
        copy_ordinal=1,
        zone="face_up",
        column=0,
        offset=0,
        face_up=True,
        blocker_depth=0,
    )
    return source_completion_event(
        semantic_target_fingerprint=target,
        dependency_id=dependency,
        original_dependency_type="SOURCE_BURIED",
        fresh_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED",
        physical_source=physical,
        requirement=requirement,
        state=state,
        actions=(),
        completion_class="SOURCE_EXPOSED",
        source_depth_before=1,
        source_depth_after=0,
        exposed=True,
        actionable=True,
        consumed=False,
        integrated=False,
        evidence_provenance=("fresh exact fixture",),
    )


def _trace(state: SpiderState, **event_args):
    return SourceCompletionPropagationTrace(_event(state, **event_args)).advance(
        SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION
    )


def _metrics(state: SpiderState, *, g=3) -> CompletionStructuralMetrics:
    stage0 = analyze_stage0_state(state, spent_cost=g, incumbent_cost=None)
    return CompletionStructuralMetrics(
        g,
        stage0.foundation_count,
        stage0.stable_same_suit_joins,
        stage0.mixed_suit_boundaries,
        1,
        1,
        0,
        0,
        0,
        0,
        len(stage0.empty_columns),
        stage0.face_down_count,
        0,
        stage0.stock_count,
        0,
        stage0.rehandling_debt,
        0,
        0,
        stage0.legal_move_count,
    )


def _opportunity(state: SpiderState, *, g=3, traces=None):
    traces = tuple(traces or (_trace(state),))
    result = make_completion_cash_out_opportunity(
        state,
        corrected_g=g,
        traces=traces,
        successor_family="dependency_closure",
        metrics=_metrics(state, g=g),
        exact_tt_admitted=True,
        independently_replay_verified=True,
    )
    assert result is not None
    return result


def _node(state: SpiderState, node_id: int, g: int, opportunity=None):
    return StrategicSearchNode(
        node_id,
        state.clone(),
        g,
        (),
        None,
        None,
        1,
        StrategicCreditLevel.CLEAN,
        None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        completion_cash_out=opportunity,
    )


def _successor(state: SpiderState, category: str, kind=StrategicActionKind.RAW_TABLEAU_MOVE):
    return StrategicSuccessor(
        kind,
        category,
        category,
        ((0, 1, 1),),
        1,
        state.clone(),
        StrategicCreditLevel.CLEAN,
        1,
        1,
        1,
        True,
        False,
        (category,),
    )


def test_01_unrestricted_deal_on():
    assert MW_RULES.can_deal_into_empty


def test_02_canonical_regression_anchor():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (
        result.mobilityware_moves,
        result.explicit_commands,
        result.tableau_moves,
        result.stock_deals,
        result.foundations,
        result.path_hash,
        result.state_hash,
    ) == (172, 174, 169, 5, 8, "77d169da2538ba8c", "4e9861540eac570cb")


def test_03_source_completion_qualifies_after_tt_admission():
    assert _opportunity(_source_state()).status == CompletionCashOutStatus.QUALIFIED


def test_04_ordinary_join_does_not_qualify_without_completion_event():
    state = _source_state()
    assert make_completion_cash_out_opportunity(
        state,
        corrected_g=1,
        traces=(),
        successor_family="run_construction",
        metrics=_metrics(state),
        exact_tt_admitted=True,
        independently_replay_verified=True,
    ) is None


def test_05_exact_tt_admission_is_required():
    state = _source_state()
    assert make_completion_cash_out_opportunity(
        state,
        corrected_g=1,
        traces=(_trace(state),),
        successor_family="dependency_closure",
        metrics=_metrics(state),
        exact_tt_admitted=False,
        independently_replay_verified=True,
    ) is None


def test_06_replay_verification_is_required():
    state = _source_state()
    assert make_completion_cash_out_opportunity(
        state,
        corrected_g=1,
        traces=(_trace(state),),
        successor_family="dependency_closure",
        metrics=_metrics(state),
        exact_tt_admitted=True,
        independently_replay_verified=False,
    ) is None


def test_07_contradictory_fresh_state_cannot_qualify():
    state = _source_state()
    other = SpiderState(_columns(*([Card("h", 1)] for _ in range(10))), [])
    assert make_completion_cash_out_opportunity(
        other,
        corrected_g=2,
        traces=(_trace(state),),
        successor_family="dependency_closure",
        metrics=_metrics(other, g=2),
        exact_tt_admitted=True,
        independently_replay_verified=True,
    ) is None


def test_08_exact_state_representative_deduplicates():
    state = _source_state(); first = _opportunity(state)
    second = replace(first, opportunity_id="duplicate", corrected_g=4)
    assert len(rank_completion_opportunities((first, second))) == 1


def test_09_same_completion_event_cannot_duplicate_representative():
    state = _source_state(); opportunity = _opportunity(state)
    assert not rank_completion_opportunities(
        (opportunity,), spent_event_ids=opportunity.event_ids
    )


def test_10_gate_a_at_most_one_completion_representative():
    a = _source_state(); b = _source_state(); b.move(0, 2, 1)
    oa = _opportunity(a, g=4)
    ob = _opportunity(b, g=5, traces=(_trace(b),))
    na = _node(a, 1, 4, oa); nb = _node(b, 2, 5, ob)
    tt = StrategicTranspositionTable(); tt.admit(a, 4); tt.admit(b, 5)
    telemetry = ControllerTelemetry()
    frontier = _reserve_completion_representative(
        (((9,), 1, na), ((8,), 2, nb)), tt=tt, spent_event_ids=(), telemetry=telemetry
    )
    assert sum(item[2].completion_cash_out.status == CompletionCashOutStatus.RESERVED for item in frontier) == 1


def test_11_gate_k_reservation_does_not_increase_frontier_width():
    state = _source_state(); opportunity = _opportunity(state); node = _node(state, 1, 3, opportunity)
    tt = StrategicTranspositionTable(); tt.admit(state, 3)
    frontier = (((9,), 1, node),)
    assert len(_reserve_completion_representative(frontier, tt=tt, spent_event_ids=(), telemetry=ControllerTelemetry())) == len(frontier)


def test_12_gate_k_representative_displaces_capacity():
    state = _source_state(); opportunity = replace(_opportunity(state, g=30), status=CompletionCashOutStatus.RESERVED)
    completion = _node(state, 30, 30, opportunity)
    normal1 = _node(state, 1, 1); normal2 = _node(state, 2, 2)
    telemetry = ControllerTelemetry(); portfolio = FoundationCheckpointPortfolio((), (), 0, 0, 2)
    kept = _trim_frontier_with_checkpoint_diversity(
        (((9,), 30, completion), ((0,), 1, normal1), ((1,), 2, normal2)),
        maximum=2, portfolio=portfolio, telemetry=telemetry,
    )
    assert 30 in {item[1] for item in kept} and len(kept) == 2


def test_13_reserved_completion_receives_queue_priority_at_equal_structure():
    state = _source_state(); reserved = replace(_opportunity(state), status=CompletionCashOutStatus.RESERVED)
    assert _node_priority(_node(state, 2, 3, reserved)) < _node_priority(_node(state, 1, 3))


def test_14_gate_b_spent_cash_out_is_ineligible():
    state = _source_state(); spent = replace(_opportunity(state), status=CompletionCashOutStatus.SPENT, cash_out_spent=True)
    assert not spent.eligible()


def test_15_gate_b_same_event_gets_no_second_cash_out():
    state = _source_state(); opportunity = _opportunity(state)
    assert not rank_completion_opportunities((opportunity,), spent_event_ids=opportunity.event_ids)


def test_16_cash_out_spent_state_has_normal_queue_treatment():
    state = _source_state(); spent = replace(_opportunity(state), status=CompletionCashOutStatus.SPENT, cash_out_spent=True)
    assert _node_priority(_node(state, 2, 3, spent)) > _node_priority(_node(state, 1, 3))


def test_17_original_exposure_is_not_fresh_harvest():
    state = _source_state(); opportunity = _opportunity(state)
    result = assess_completion_harvest(opportunity, state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True)
    assert result.harvest_kinds == (CompletionHarvestKind.NO_DOWNSTREAM_HARVEST,)


def test_18_gate_d_source_consumption_is_harvest():
    state = _source_state(); end = state.clone(); end.move(0, 1, 1)
    result = assess_completion_harvest(_opportunity(state), state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.SOURCE_CONSUMED in result.harvest_kinds


def test_19_gate_d_source_integration_is_harvest():
    state = _source_state(); end = state.clone(); end.move(0, 1, 1)
    result = assess_completion_harvest(_opportunity(state), state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.SOURCE_INTEGRATED in result.harvest_kinds


def test_20_same_suit_construction_is_harvest():
    state = _source_state(); end = state.clone(); end.move(0, 1, 1)
    result = assess_completion_harvest(_opportunity(state), state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.SAME_SUIT_CONSTRUCTION in result.harvest_kinds


def test_21_dependency_chain_advance_is_harvest():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, dependency_chain_advanced=True)
    assert CompletionHarvestKind.DEPENDENCY_CHAIN_ADVANCE in result.harvest_kinds


def test_22_receiver_unlock_is_harvest():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, receiver_unlocked=True)
    assert CompletionHarvestKind.RECEIVER_UNLOCK in result.harvest_kinds


def test_23_workspace_unlock_is_harvest():
    state = _source_state(); end = state.clone(); end.move(0, 2, 1)
    result = assess_completion_harvest(_opportunity(state), state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.WORKSPACE_UNLOCK in result.harvest_kinds


def test_24_new_reveal_is_harvest():
    state = SpiderState(_columns([], [Card("c", 6)], *([Card("h", 1)] for _ in range(8))), [])
    state.columns[0] = Column([Card("s", 9)], [Card("c", 5)])
    opportunity = _opportunity(state); end = state.clone(); end.move(0, 1, 1)
    result = assess_completion_harvest(opportunity, state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.NEW_REVEAL in result.harvest_kinds


def test_25_terminal_qualification_is_harvest():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, terminal_qualified=True)
    assert CompletionHarvestKind.TERMINAL_QUALIFICATION in result.harvest_kinds


def test_26_gate_j_foundation_removal_is_harvest():
    state = _source_state(); end = state.clone(); end.foundations.append([Card("h", rank) for rank in range(13, 0, -1)])
    result = assess_completion_harvest(_opportunity(state), state, end, downstream_successor_generated=True, downstream_successor_admitted=True)
    assert CompletionHarvestKind.FOUNDATION_REMOVAL in result.harvest_kinds


def test_27_epoch_preparation_without_deal_is_harvest():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, epoch_prepared=True)
    assert CompletionHarvestKind.EPOCH_PREPARATION in result.harvest_kinds


def test_28_deal_itself_is_not_completion_harvest():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, epoch_prepared=True, action_is_deal=True)
    assert CompletionHarvestKind.EPOCH_PREPARATION not in result.harvest_kinds


def test_29_other_named_structural_harvest_is_explicit():
    state = _source_state(); result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, other_named_harvest=True)
    assert CompletionHarvestKind.OTHER_NAMED_STRUCTURAL_HARVEST in result.harvest_kinds


def test_30_gate_f_no_downstream_harvest_is_explicit():
    state = _source_state(); result = combine_completion_harvest(_opportunity(state), ())
    assert result.harvest_kinds == (CompletionHarvestKind.NO_DOWNSTREAM_HARVEST,)


def test_31_gate_f_no_harvest_does_not_renew_reservation():
    state = _source_state(); spent = replace(_opportunity(state), status=CompletionCashOutStatus.SPENT, cash_out_spent=True)
    assert not rank_completion_opportunities((spent,))


def test_32_gate_e_follow_on_blocker_can_advance():
    state = _source_state(); event = _event(state)
    assert event.fresh_dependency_type == "SOURCE_EXPOSED_BUT_BLOCKED"
    result = assess_completion_harvest(_opportunity(state), state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, dependency_chain_advanced=True)
    assert result.meaningful


def test_33_follow_on_does_not_reopen_buried_requirement():
    state = _source_state(); event = _event(state)
    assert event.satisfaction.state == SourceRequirementSatisfactionState.ACTIONABLE
    assert event.satisfaction.satisfied


def test_34_gate_h_multiple_events_use_one_opportunity():
    state = _source_state(); traces = (_trace(state), _trace(state, target=("generic", "second"), dependency="source:5:c:second"))
    opportunity = _opportunity(state, traces=traces)
    assert len(opportunity.events) == 2


def test_35_gate_h_multiple_events_still_rank_as_one_representative():
    state = _source_state(); traces = (_trace(state), _trace(state, target=("generic", "second"), dependency="source:5:c:second"))
    assert len(rank_completion_opportunities((_opportunity(state, traces=traces),))) == 1


def test_36_gate_g_lower_g_conservative_state_remains_represented():
    state = _source_state(); completion = _node(state, 2, 4, replace(_opportunity(state, g=4), status=CompletionCashOutStatus.RESERVED)); conservative = _node(state, 1, 1)
    portfolio = FoundationCheckpointPortfolio((), (), 0, 0, 2)
    kept = _trim_frontier_with_checkpoint_diversity((((9,), 2, completion), ((0,), 1, conservative)), maximum=2, portfolio=portfolio)
    assert {item[1] for item in kept} == {1, 2}


def test_37_gate_g_higher_g_completion_gets_bounded_opportunity():
    state = _source_state(); completion = _node(state, 2, 4, _opportunity(state, g=4)); conservative = _node(state, 1, 1)
    tt = StrategicTranspositionTable(); tt.admit(state, 4)
    frontier = _reserve_completion_representative((((0,), 1, conservative), ((9,), 2, completion)), tt=tt, spent_event_ids=(), telemetry=ControllerTelemetry())
    assert any(item[2].completion_cash_out and item[2].completion_cash_out.status == CompletionCashOutStatus.RESERVED for item in frontier)


def test_38_completion_model_has_no_proof_authority():
    state = _source_state(); opportunity = _opportunity(state)
    assert not opportunity.proof_pruning_allowed and not opportunity.metrics.ordering_key() == ()


def test_39_gate_c_exact_lower_g_tt_dominance_unchanged():
    state = _source_state(); table = StrategicTranspositionTable()
    assert table.admit(state, 5) and table.admit(state.clone(), 4) and not table.admit(state.clone(), 5)


def test_40_gate_c_source_satisfaction_reconstructed_on_cheaper_state():
    state = _source_state(); rows = reconstruct_completion_satisfactions(state.clone(), (_trace(state),))
    assert rows[0].satisfied and rows[0].current_state_hash


def test_41_gate_i_deal_family_remains_represented():
    state = _source_state(); successors = (_successor(state, "dependency_closure"), _successor(state, "deal_timing", StrategicActionKind.RAW_DEAL))
    assert any(item.kind == StrategicActionKind.RAW_DEAL for item in retain_diverse_portfolio(successors, maximum=2))


def test_42_late_removal_construction_family_remains_represented():
    state = _source_state(); successors = (_successor(state, "dependency_closure"), _successor(state, "run_construction", StrategicActionKind.SAME_SUIT_CONSTRUCTION))
    assert {item.category for item in retain_diverse_portfolio(successors, maximum=2)} == {"dependency_closure", "run_construction"}


def test_43_raw_fallback_family_remains_represented():
    state = _source_state(); successors = (_successor(state, "dependency_closure"), _successor(state, "raw_fallback"))
    assert any(item.category == "raw_fallback" for item in retain_diverse_portfolio(successors, maximum=2))


def test_44_alternate_campaign_family_remains_represented():
    state = _source_state(); successors = (_successor(state, "dependency_closure"), _successor(state, "campaign", StrategicActionKind.FOUNDATION_CAMPAIGN))
    assert any(item.category == "campaign" for item in retain_diverse_portfolio(successors, maximum=2))


def test_45_permanent_same_suit_dominance_remains():
    state = _source_state(); stable = assess_tableau_move(state, (0, 1, 1)); mixed = assess_tableau_move(state, (0, 2, 1))
    assert stable.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert stable_join_dominates(stable, mixed, comparable_effects=True)


def test_46_mixed_park_still_records_exit_and_debt():
    state = _source_state(); mixed = assess_tableau_move(state, (0, 2, 1))
    assert mixed.placement_class in {PlacementClass.MIXED_SUIT_PARK, PlacementClass.WORKSPACE_PARK}
    assert mixed.estimated_rehandling_cost >= 0 and mixed.future_exit_route


def test_47_target_persistence_remains_exactly_three():
    assert AnytimeControllerConfig().milestone_max_strategic_expansions == 3


def test_48_closure_beam_remains_192():
    assert DependencyClosureConfig().beam_width == 192


def test_49_allocator_tier_vocabulary_unchanged():
    assert tuple(item.name for item in TacticalResourceTier) == ("PROBE", "SHALLOW", "COMMITTED", "TERMINAL")


def test_50_per_expansion_allocator_ceilings_unchanged():
    config = AnytimeControllerConfig()
    assert (config.milestone_max_nodes_per_expansion, config.milestone_max_time_s_per_expansion) == (12_000, 4.0)


def test_51_cash_out_adds_no_resource_configuration():
    fields = AnytimeControllerConfig.__dataclass_fields__
    assert not any("cash_out" in name or "completion_representative" in name for name in fields)


def test_52_production_policy_has_no_benchmark_suit_rank_or_column():
    source = (ROOT / "src/spider/planner/completion_cash_out.py").read_text()
    assert all(item not in source for item in ("4925153", "Spades", "Hearts 6", "Diamonds 13"))


def test_53_canonical_future_actions_are_unavailable_prospectively():
    source = (ROOT / "src/spider/planner/completion_cash_out.py").read_text()
    assert "77d169da2538ba8c" not in source and "924bfd20deac96af" not in source


def test_54_external_119_absent_from_production_policy():
    assert "119" not in (ROOT / "src/spider/planner/completion_cash_out.py").read_text()


def test_55_selected_path_remains_distinct_from_admission():
    state = _source_state(); trace = _trace(state)
    assert trace.controller_admitted and not trace.selected_path


def test_56_admitted_not_selected_diagnosis_is_explicit():
    assert CompletionCashOutDisposition.COMPLETION_ADMITTED_NOT_SELECTED.value == "COMPLETION_ADMITTED_NOT_SELECTED"


def test_57_selection_trace_fields_are_visible():
    fields = controller_module.CompletionCashOutTrace.__dataclass_fields__
    assert {"event_ids", "structural_metrics", "representative_rank", "selected_for_expansion", "downstream_result"} <= set(fields)


def test_58_completion_telemetry_fields_exist():
    fields = ControllerTelemetry.__dataclass_fields__
    assert {"admitted_completion_states", "completion_cash_out_qualified", "completion_representatives_reserved", "completion_representatives_expanded", "completion_harvest_by_kind", "completion_deals_admitted_after_cash_out", "completion_deals_chosen_after_cash_out"} <= set(fields)


def test_59_completion_context_never_enters_state_identity():
    state = _source_state(); before = canonical_state_key(state); _opportunity(state)
    assert canonical_state_key(state) == before


def test_60_gate_l_sunk_cost_has_no_priority_after_cash_out():
    state = _source_state(); spent = replace(_opportunity(state, g=20), status=CompletionCashOutStatus.SPENT, cash_out_spent=True)
    costly = _node(state, 2, 20, spent); useful = _node(state, 1, 1)
    assert _node_priority(useful) < _node_priority(costly)


@pytest.mark.parametrize("seed", [15015, 15051])
def test_61_unseen_deal_cash_out_smoke_is_exact_and_replay_neutral(seed):
    cards = list(load_deal(DEAL)); random.Random(seed).shuffle(cards)
    state = SpiderState.from_cards(cards); card = state.columns[0].face_up[-1]
    requirement = semantic_source_requirement(("unseen", seed), f"source:{card.rank}:{card.suit}", card)
    physical = physical_source_identity(card, dependency_id=requirement.dependency_id, copy_ordinal=1, zone="face_up", column=0, offset=len(state.columns[0].face_up)-1, face_up=True, blocker_depth=0)
    event = source_completion_event(semantic_target_fingerprint=requirement.semantic_target_fingerprint, dependency_id=requirement.dependency_id, original_dependency_type="SOURCE_BURIED", fresh_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED", physical_source=physical, requirement=requirement, state=state, actions=(), completion_class="SOURCE_EXPOSED", source_depth_before=1, source_depth_after=0, exposed=True, actionable=True, consumed=False, integrated=False, evidence_provenance=("unseen exact smoke",))
    trace = SourceCompletionPropagationTrace(event).advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    opportunity = make_completion_cash_out_opportunity(state, corrected_g=0, traces=(trace,), successor_family="unseen", metrics=_metrics(state, g=0), exact_tt_admitted=True, independently_replay_verified=True)
    assert opportunity is not None and opportunity.exact_state_key == canonical_state_key(state)
    moves = tuple(state.enumerate_moves())
    if moves:
        end = state.clone(); cost = end.move(*moves[0]); replay = state.clone(); assert replay_actions(replay, [moves[0]]) == cost and states_structurally_equal(replay, end)
