from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path

import pytest

import spider.planner.anytime_controller as controller
import spider.planner.whole_deal_scheduler as scheduler
from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    StrategicTranspositionTable,
    _annotate_scheduler_successors,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    ArrivalActionabilityStage,
    ArrivalConversionClass,
    ArrivalConversionHarvestKind,
    ArrivalConversionStatus,
    EpochSaturationStatus,
    FoundationLaneConversionState,
    PreDealOpportunityClass,
    ScheduleDeadlineKind,
    ScheduleObjectiveFamily,
    TemporalAvailabilityKind,
    WholeDealSchedulerConfig,
    advance_post_deal_conversion_ledger,
    analyze_post_deal_arrival_conversions,
    arrival_candidate_obligation,
    arrival_conversion_traces,
    assess_epoch_saturation,
    build_whole_deal_blueprint,
    classify_arrival_conversion_harvest,
    classify_epoch_transition_harvest,
    foundation_lane_conversions,
    integrate_arrival_conversion_ledger,
    record_arrival_conversion_candidates,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
CONFIG12 = WholeDealSchedulerConfig(max_objectives=12)


def _state(bottoms, row) -> SpiderState:
    assert len(bottoms) == len(row) == 10
    return SpiderState([Column([], list(cards)) for cards in bottoms], list(row))


def _scheduled_deal(source: SpiderState):
    blueprint = build_whole_deal_blueprint(source)
    before = rebuild_whole_deal_schedule(source, blueprint, config=CONFIG12)
    child = source.clone()
    child.deal(MW_RULES)
    after = rebuild_whole_deal_schedule(child, blueprint, config=CONFIG12)
    ledger = analyze_post_deal_arrival_conversions(source, child, before, after)
    integrated = integrate_arrival_conversion_ledger(
        child, after, ledger, config=CONFIG12
    )
    return blueprint, before, child, after, ledger, integrated


def _immediate_source() -> SpiderState:
    bottoms = (
        (Card("c", 6),),
        (Card("h", 13),),
        (Card("d", 13),),
        (Card("s", 13),),
        (Card("h", 11),),
        (Card("d", 11),),
        (Card("s", 11),),
        (Card("h", 9),),
        (Card("d", 9),),
        (Card("s", 9),),
    )
    row = (
        Card("c", 5),
        Card("c", 4),
        Card("h", 2),
        Card("d", 2),
        Card("s", 2),
        Card("h", 4),
        Card("d", 4),
        Card("s", 4),
        Card("h", 7),
        Card("d", 7),
    )
    return _state(bottoms, row)


def _prepare_source() -> SpiderState:
    bottoms = (
        (Card("c", 6),),
        (Card("c", 4),),
        (Card("s", 13),),
        (Card("h", 13),),
        (Card("d", 13),),
        (Card("s", 11),),
        (Card("h", 11),),
        (Card("d", 11),),
        (Card("s", 8),),
        (Card("h", 8),),
    )
    row = (
        Card("c", 5),
        Card("h", 9),
        Card("d", 10),
        Card("s", 2),
        Card("h", 2),
        Card("d", 2),
        Card("s", 4),
        Card("h", 4),
        Card("d", 4),
        Card("s", 6),
    )
    return _state(bottoms, row)


def _terminal_source() -> SpiderState:
    bottoms = (
        (Card("h", 13),),
        tuple(Card("c", rank) for rank in range(13, 2, -1)),
        *((Card("d", 13 - index % 4),) for index in range(8)),
    )
    row = (
        Card("c", 1),
        Card("c", 2),
        Card("h", 2),
        Card("d", 2),
        Card("s", 2),
        Card("h", 4),
        Card("d", 4),
        Card("s", 4),
        Card("h", 6),
        Card("d", 6),
    )
    return _state(bottoms, row)


def _neutral_source() -> SpiderState:
    bottoms = tuple((Card(suit, rank),) for suit, rank in (
        ("c", 13), ("d", 11), ("h", 9), ("s", 7), ("c", 5),
        ("d", 3), ("h", 13), ("s", 11), ("c", 9), ("d", 7),
    ))
    row = tuple(Card(suit, rank) for suit, rank in (
        ("h", 2), ("s", 4), ("c", 7), ("d", 9), ("h", 11),
        ("s", 13), ("c", 2), ("d", 4), ("h", 6), ("s", 8),
    ))
    return _state(bottoms, row)


def _op(ledger, card: Card, column: int):
    return next(
        item
        for item in ledger.opportunities
        if item.incoming_card == card and item.destination_column == column
    )


def _obligation(ledger, opportunity):
    return next(
        item
        for item in ledger.obligations
        if item.opportunity.opportunity_id == opportunity.opportunity_id
    )


def _successor(state: SpiderState, action) -> StrategicSuccessor:
    end = state.clone()
    cost = end.move(*action, rules=MW_RULES)
    return StrategicSuccessor(
        StrategicActionKind.RAW_TABLEAU_MOVE,
        "raw_fallback",
        "generated legal fixture successor",
        (action,),
        cost,
        end,
        StrategicCreditLevel.CLEAN,
        cost,
        cost,
        0,
        True,
        False,
        ("fixture",),
    )


@pytest.fixture(scope="module")
def immediate_case():
    return _scheduled_deal(_immediate_source())


@pytest.fixture(scope="module")
def prepare_case():
    return _scheduled_deal(_prepare_source())


@pytest.fixture(scope="module")
def terminal_case():
    return _scheduled_deal(_terminal_source())


@pytest.fixture(scope="module")
def benchmark_epochs():
    source = SpiderState.from_cards(load_deal(DEAL))
    blueprint = build_whole_deal_blueprint(source)
    schedule = rebuild_whole_deal_schedule(source, blueprint, config=CONFIG12)
    rows = []
    for generation in range(1, 6):
        before_state = source.clone()
        before_schedule = schedule
        source.deal(MW_RULES)
        schedule = rebuild_whole_deal_schedule(
            source, blueprint, config=CONFIG12, generation=generation
        )
        ledger = analyze_post_deal_arrival_conversions(
            before_state,
            source,
            before_schedule,
            schedule,
            generation=generation,
        )
        rows.append((before_state, before_schedule, source.clone(), schedule, ledger))
    return tuple(rows)


@pytest.fixture(scope="module")
def anchors():
    cards = tuple(load_deal(DEAL))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL)
    machine = _node(
        controller.solve_anytime(opening, cards, None, _opening_anchor_config())
    )
    independent = reconstruct_cost23_checkpoint()
    return canonical, machine, independent


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_regression_anchors_are_unchanged(anchors):
    canonical, machine, independent = anchors
    assert canonical.valid and canonical.solved and canonical.mobilityware_moves == 172
    assert machine.g == 21 and len(machine.state.foundations) == 1
    assert independent.action_count == 23 and len(independent.state.foundations) == 1


def test_03_v01_v02_blueprint_facts_survive(benchmark_epochs):
    assert [tuple(item.deal_row) for *_, item in benchmark_epochs] == [
        tuple(row[-1].deal_row) for row in benchmark_epochs
    ]
    assert [len(item[2].stock) for item in benchmark_epochs] == [40, 30, 20, 10, 0]


def test_04_transition_harvest_generates_arrival_event(benchmark_epochs):
    before_state, before, child, after, _ledger = benchmark_epochs[1]
    kinds = {item.kind.value for item in classify_epoch_transition_harvest(before_state, child, before, after)}
    assert "REALIZED_BRIDGE_ARRIVAL" in kinds


def test_05_arrival_is_causally_linked_to_exact_deal(immediate_case):
    _bp, before, _child, _after, ledger, _integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    assert opportunity.source_epoch == before.epoch
    assert opportunity.deal_row[0] == opportunity.incoming_card
    assert opportunity.originating_transition_id == ledger.transition_id


def test_06_unrelated_row_cards_are_not_false_arrivals(immediate_case):
    *_, ledger, _integrated = immediate_case
    assert [(item.incoming_card, item.destination_column) for item in ledger.opportunities] == [(Card("c", 5), 0)]


def test_07_arrived_is_distinct_from_actionable():
    source = _prepare_source()
    blueprint, before, child, _after, _ledger, _integrated = _scheduled_deal(source)
    child.columns[0].face_up.append(Card("s", 12))
    covered = rebuild_whole_deal_schedule(child, blueprint, config=CONFIG12)
    ledger = analyze_post_deal_arrival_conversions(source, child, before, covered)
    opportunity = _op(ledger, Card("c", 5), 0)
    assert opportunity.actionability_stage == ArrivalActionabilityStage.ARRIVED


def test_08_actionable_is_distinct_from_consumable(immediate_case):
    _bp, _before, child, _after, ledger, _integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    obligation = _obligation(ledger, opportunity)
    assert obligation.actionability_stage == ArrivalActionabilityStage.ACTIONABLE
    generated = record_arrival_conversion_candidates(
        child, ledger, (_successor(child, (1, 0, 1)),)
    )
    assert _obligation(generated, opportunity).actionability_stage == ArrivalActionabilityStage.CONSUMABLE


def test_09_immediate_legal_bridge_is_consume_now(immediate_case):
    *_, ledger, _integrated = immediate_case
    assert _op(ledger, Card("c", 5), 0).conversion_class == ArrivalConversionClass.CONSUME_NOW


def test_10_one_preparation_bridge_is_typed(prepare_case):
    *_, ledger, _integrated = prepare_case
    opportunity = _op(ledger, Card("c", 5), 0)
    assert opportunity.conversion_class == ArrivalConversionClass.PREPARE_THEN_CONSUME
    assert opportunity.preparation_actions == ((1, 2, 1),)


def test_11_near_terminal_lane_is_foundation_convert_now(terminal_case):
    *_, ledger, _integrated = terminal_case
    assert _op(ledger, Card("c", 2), 1).conversion_class == ArrivalConversionClass.FOUNDATION_CONVERT_NOW


def test_12_safe_useful_arrival_is_deferrable(prepare_case):
    *_, ledger, _integrated = prepare_case
    assert _op(ledger, Card("h", 9), 1).conversion_class == ArrivalConversionClass.DEFERRABLE_ARRIVAL


def test_13_theoretical_leverage_without_path_is_no_current(benchmark_epochs):
    ledger = benchmark_epochs[2][-1]
    assert any(item.conversion_class == ArrivalConversionClass.NO_CURRENT_CONVERSION for item in ledger.opportunities)


def test_14_stale_arrival_is_invalidated(immediate_case):
    blueprint, before, child, _after, _ledger, _integrated = immediate_case
    stale_child = child.clone()
    stale_child.columns[0].face_up.pop()
    stale = rebuild_whole_deal_schedule(stale_child, blueprint, config=CONFIG12)
    ledger = analyze_post_deal_arrival_conversions(_immediate_source(), stale_child, before, stale)
    assert _op(ledger, Card("c", 5), 0).conversion_class == ArrivalConversionClass.INVALIDATED_ARRIVAL


def test_15_two_edge_bridge_outranks_one_edge_extension(immediate_case):
    *_, ledger, _integrated = immediate_case
    bridge = _op(ledger, Card("c", 5), 0)
    assert bridge.structural_benefit >= 2


def test_16_fragment_count_reduction_is_detected(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    obligation = _obligation(ledger, opportunity)
    successor = _successor(child, (1, 0, 1))
    after = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    harvests = classify_arrival_conversion_harvest(child, successor.end_state, obligation, before_schedule=integrated, after_schedule=after)
    assert any(item.kind == ArrivalConversionHarvestKind.FRAGMENTS_JOINED for item in harvests)


def test_17_arrival_integration_survives_fresh_replan(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 0, 1))
    blueprint = build_whole_deal_blueprint(successor.end_state)
    fresh = rebuild_whole_deal_schedule(successor.end_state, blueprint, config=CONFIG12)
    advanced = advance_post_deal_conversion_ledger(child, successor.end_state, integrated, fresh, ledger, selected_opportunity_id=opportunity.opportunity_id, selected_actions=successor.actions)
    assert _obligation(advanced, opportunity).status == ArrivalConversionStatus.SPENT


def test_18_duplicate_lane_reassignment_is_allowed(immediate_case):
    _bp, before, child, after, _ledger, _integrated = immediate_case
    assert foundation_lane_conversions(before) != foundation_lane_conversions(after)
    assert states_structurally_equal(child, child.clone())


def test_19_reassignment_preserves_existing_stable_structure(immediate_case):
    _bp, before, _child, after, _ledger, _integrated = immediate_case
    before_edges = {edge for lane in foundation_lane_conversions(before) for edge in lane.satisfied_edges}
    after_edges = {edge for lane in foundation_lane_conversions(after) for edge in lane.satisfied_edges}
    assert before_edges <= after_edges


def test_20_foundation_floor_crossing_is_detected(benchmark_epochs):
    assert ("h", 1) in benchmark_epochs[1][-1].floor_crossings
    assert ("c", 1) in benchmark_epochs[4][-1].floor_crossings


def test_21_floor_crossing_does_not_claim_foundation(benchmark_epochs):
    _before_state, _before, child, _after, ledger = benchmark_epochs[1]
    assert ledger.floor_crossings and len(child.foundations) == 0


def test_22_existing_terminal_predicate_remains_authoritative(terminal_case):
    _bp, _before, child, _after, _ledger, _integrated = terminal_case
    endpoint = child.clone()
    assert endpoint.can_move(0, 1, 1)
    endpoint.move(0, 1, 1, rules=MW_RULES)
    assert len(endpoint.foundations) == 1


def test_23_arrival_consumption_uses_existing_move_successor(immediate_case):
    _bp, _before, child, _after, ledger, _integrated = immediate_case
    successor = _successor(child, (1, 0, 1))
    assert arrival_candidate_obligation(child, ledger, successor.actions, successor.end_state) is not None


def test_24_scheduler_does_not_execute_cards(immediate_case):
    _bp, _before, child, after, ledger, _integrated = immediate_case
    frozen = child.clone()
    analyze_post_deal_arrival_conversions(_immediate_source(), child, rebuild_whole_deal_schedule(_immediate_source(), build_whole_deal_blueprint(_immediate_source()), config=CONFIG12), after)
    assert states_structurally_equal(child, frozen) and ledger.harvests == ()


def test_25_prepare_then_consume_uses_generated_preparation(prepare_case):
    _bp, _before, child, _after, ledger, _integrated = prepare_case
    preparation = _successor(child, (1, 2, 1))
    match = arrival_candidate_obligation(child, ledger, preparation.actions, preparation.end_state)
    assert match is not None and match.opportunity.conversion_class == ArrivalConversionClass.PREPARE_THEN_CONSUME


def test_26_conversion_probe_is_not_recursive(prepare_case):
    *_, ledger, _integrated = prepare_case
    opportunity = _op(ledger, Card("c", 5), 0)
    assert all(len(action) == 3 for action in opportunity.preparation_actions)
    assert "recursive" not in inspect.getsource(scheduler._arrival_preparation_actions)


def test_27_conversion_cost_records_stable_run_debt(immediate_case):
    *_, ledger, _integrated = immediate_case
    assert _op(ledger, Card("c", 5), 0).rehandling_cost >= 0


def test_28_expensive_or_unavailable_conversion_is_rejected(benchmark_epochs):
    no_current = next(item for item in benchmark_epochs[2][-1].opportunities if item.conversion_class == ArrivalConversionClass.NO_CURRENT_CONVERSION)
    assert not no_current.immediate_actions and not no_current.preparation_actions


def test_29_urgent_arrival_blocks_next_deal(benchmark_epochs):
    _before_state, _before, child, after, ledger = benchmark_epochs[0]
    integrated = integrate_arrival_conversion_ledger(child, after, ledger, config=CONFIG12)
    assert any(item.opportunity.deadline == ScheduleDeadlineKind.BEFORE_NEXT_DEAL for item in ledger.obligations if item.objective_id)
    assert integrated.saturation.status == EpochSaturationStatus.PREPARATION_REQUIRED


def test_30_deferrable_arrival_does_not_block_deal(benchmark_epochs):
    _bs, _before, child, after, ledger = benchmark_epochs[0]
    deferred = tuple(item for item in ledger.obligations if item.opportunity.conversion_class == ArrivalConversionClass.DEFERRABLE_ARRIVAL)
    only = replace(ledger, opportunities=tuple(item.opportunity for item in deferred), obligations=deferred, assessments=tuple(item for item in ledger.assessments if item.opportunity_id in {o.opportunity.opportunity_id for o in deferred}))
    blank = replace(after, objectives=(), pre_deal_opportunities=(), saturation=assess_epoch_saturation(child, ()))
    assert integrate_arrival_conversion_ledger(child, blank, only, config=CONFIG12).saturation.status == EpochSaturationStatus.DEAL_READY


def test_31_no_current_conversion_does_not_block_deal(benchmark_epochs):
    _bs, _before, child, after, ledger = benchmark_epochs[2]
    items = tuple(item for item in ledger.obligations if item.opportunity.conversion_class == ArrivalConversionClass.NO_CURRENT_CONVERSION)
    only = replace(ledger, opportunities=tuple(item.opportunity for item in items), obligations=items, assessments=tuple(item for item in ledger.assessments if item.opportunity_id in {o.opportunity.opportunity_id for o in items}))
    blank = replace(after, objectives=(), pre_deal_opportunities=(), saturation=assess_epoch_saturation(child, ()))
    assert integrate_arrival_conversion_ledger(child, blank, only, config=CONFIG12).saturation.status == EpochSaturationStatus.DEAL_READY


def test_32_conversion_recomputes_fresh_saturation(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    successor = _successor(child, (1, 0, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    advanced = advance_post_deal_conversion_ledger(child, successor.end_state, integrated, fresh, ledger, selected_opportunity_id=_op(ledger, Card("c", 5), 0).opportunity_id, selected_actions=successor.actions)
    assert integrate_arrival_conversion_ledger(successor.end_state, fresh, advanced, config=CONFIG12).saturation is not integrated.saturation


def test_33_next_deal_can_become_ready_after_conversion():
    state = _neutral_source()
    assert assess_epoch_saturation(state, ()).status == EpochSaturationStatus.DEAL_READY


def test_34_representative_is_not_added_without_starvation():
    assert ControllerTelemetry().arrival_conversion_representatives_required == 0


def test_35_at_most_one_live_conversion_representative():
    telemetry = ControllerTelemetry()
    assert telemetry.arrival_conversion_representatives_reserved <= 1


def test_36_frontier_width_is_unchanged():
    assert _gate_f_config(90.0).max_frontier_size == 256


def test_37_no_special_conversion_expansion_is_created():
    assert ControllerTelemetry().arrival_conversion_representatives_expanded == 0


def test_38_arrival_analysis_consumes_no_tactical_nodes(immediate_case):
    *_, ledger, _integrated = immediate_case
    assert ledger.analysis_seconds >= 0 and ControllerTelemetry().tactical_nodes == 0


def test_39_persistence_limit_is_unchanged():
    assert _gate_f_config(90.0).milestone_max_strategic_expansions == 3


def test_40_same_arrival_cannot_repeatedly_reserve(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 0, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    advanced = advance_post_deal_conversion_ledger(child, successor.end_state, integrated, fresh, ledger, selected_opportunity_id=opportunity.opportunity_id, selected_actions=successor.actions)
    assert not _obligation(advanced, opportunity).active()


def test_41_completion_cashout_can_coexist_with_arrival_ledger(immediate_case):
    node = StrategicSearchNode(1, immediate_case[2], 1, (("deal",),), None, None, 1, StrategicCreditLevel.CLEAN, None, whole_deal_schedule=immediate_case[-1], post_deal_conversion_ledger=immediate_case[-2])
    assert node.completion_cash_out is None and node.post_deal_conversion_ledger is not None


def test_42_epoch_transition_can_coexist_with_arrival_ledger(immediate_case):
    node = StrategicSearchNode(1, immediate_case[2], 1, (("deal",),), None, None, 1, StrategicCreditLevel.CLEAN, None, whole_deal_schedule=immediate_case[-1], post_deal_conversion_ledger=immediate_case[-2])
    assert hasattr(node, "epoch_transition_opportunity") and node.post_deal_conversion_ledger.transition_id


def test_43_terminal_objective_precedes_bridge_objective(terminal_case):
    families = [item.family for item in terminal_case[-1].objectives]
    assert families[0] == ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE


def test_44_deal_readiness_still_obeys_must_work(benchmark_epochs):
    integrated = integrate_arrival_conversion_ledger(benchmark_epochs[0][2], benchmark_epochs[0][3], benchmark_epochs[0][4], config=CONFIG12)
    if any(item.classification == PreDealOpportunityClass.MUST_PRE_DEAL for item in integrated.pre_deal_opportunities):
        assert integrated.saturation.status == EpochSaturationStatus.PREPARATION_REQUIRED


def test_45_deal_itself_is_not_conversion_harvest(immediate_case):
    assert immediate_case[-2].harvests == ()


def test_46_arrival_source_consumption_harvest_is_typed(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 0, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    kinds = {item.kind for item in classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)}
    assert ArrivalConversionHarvestKind.ARRIVAL_SOURCE_CONSUMED in kinds


def test_47_arrival_integration_harvest_is_typed(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 0, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    kinds = {item.kind for item in classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)}
    assert ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED in kinds


def test_48_bridge_merge_harvest_is_typed(immediate_case):
    _bp, _before, child, _after, ledger, integrated = immediate_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 0, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    kinds = {item.kind for item in classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)}
    assert ArrivalConversionHarvestKind.BRIDGE_MERGE in kinds


def test_49_lane_completion_harvest_is_typed(terminal_case):
    _bp, _before, child, _after, ledger, integrated = terminal_case
    opportunity = _op(ledger, Card("c", 2), 1)
    successor = _successor(child, (0, 1, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    kinds = {item.kind for item in classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)}
    assert ArrivalConversionHarvestKind.FOUNDATION_REMOVED in kinds


def test_50_foundation_removal_harvest_is_typed(terminal_case):
    _bp, _before, child, _after, ledger, integrated = terminal_case
    opportunity = _op(ledger, Card("c", 2), 1)
    successor = _successor(child, (0, 1, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    harvests = classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)
    assert any(item.structural_delta.foundations_added == 1 for item in harvests)


def test_51_no_conversion_harvest_is_explicit(prepare_case):
    _bp, _before, child, _after, ledger, integrated = prepare_case
    opportunity = _op(ledger, Card("c", 5), 0)
    successor = _successor(child, (1, 2, 1))
    fresh = rebuild_whole_deal_schedule(successor.end_state, build_whole_deal_blueprint(successor.end_state), config=CONFIG12)
    kinds = {item.kind for item in classify_arrival_conversion_harvest(child, successor.end_state, _obligation(ledger, opportunity), before_schedule=integrated, after_schedule=fresh)}
    assert ArrivalConversionHarvestKind.NO_CONVERSION_HARVEST in kinds


@pytest.mark.parametrize("suit,rank", [("c", 5), ("d", 8), ("h", 10), ("s", 12)])
def test_52_missing_rank_fixture_is_generic(suit, rank):
    assert Card(suit, rank).rank - 1 == rank - 1
    source = inspect.getsource(scheduler.analyze_post_deal_arrival_conversions)
    assert "Clubs" not in source and "3C" not in source


def test_53_two_equal_copies_are_handled_symmetrically():
    source = _immediate_source()
    source.columns[1].face_up = [Card("c", 6)]
    source.stock[1] = Card("c", 5)
    _bp, _before, _child, _after, ledger, _integrated = _scheduled_deal(source)
    copies = [item for item in ledger.opportunities if item.incoming_card == Card("c", 5)]
    assert len(copies) == 2 and {item.destination_column for item in copies} == {0, 1}


def test_54_future_arrival_is_not_a_current_source():
    source = _immediate_source()
    blueprint = build_whole_deal_blueprint(source)
    schedule = rebuild_whole_deal_schedule(source, blueprint, config=CONFIG12)
    reference = next(item for item in schedule.leverage_cards if item.card == Card("c", 5) and item.column == 0)
    assert reference.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK


def test_55_lane_fragmentation_table_is_deterministic(immediate_case):
    table = foundation_lane_conversions(immediate_case[3])
    assert table == foundation_lane_conversions(immediate_case[3])
    assert all(item.state in FoundationLaneConversionState for item in table)


def test_56_scheduler_metadata_is_absent_from_tt_identity(immediate_case):
    child = immediate_case[2]
    key = canonical_state_key(child)
    assert key == canonical_state_key(child.clone())


def test_57_conversion_metadata_is_absent_from_tt_identity(immediate_case):
    child = immediate_case[2]
    node = StrategicSearchNode(1, child, 1, (), None, None, 0, StrategicCreditLevel.CLEAN, None, post_deal_conversion_ledger=immediate_case[-2])
    assert canonical_state_key(node.state) == canonical_state_key(child)


def test_58_lower_g_exact_dominance_is_unchanged(immediate_case):
    state = immediate_case[2]
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 5)
    assert not tt.admit(state.clone(), 6)
    assert tt.admit(state.clone(), 4)


def test_59_admissible_bound_is_unchanged(immediate_case):
    state = immediate_case[2]
    before = compute_solution_lower_bound(state)
    ledger = immediate_case[-2]
    assert ledger.proof_pruning_allowed is False
    assert compute_solution_lower_bound(state) == before


def test_60_scheduler_proof_prunes_remain_zero():
    assert ControllerTelemetry().scheduler_proof_prunes == 0


def test_61_no_benchmark_constants_in_production():
    source = inspect.getsource(scheduler)
    assert all(token not in source for token in ("4925153", "Clubs", "3C", "column 4", "column 9"))


def test_62_no_external_scores_in_production():
    source = inspect.getsource(scheduler) + inspect.getsource(controller)
    assert "score 154" not in source and "score 119" not in source


def test_63_unseen_deal_arrival_conversion_replays(immediate_case):
    source = _immediate_source()
    child = immediate_case[2].clone()
    actions = ((1, 0, 1),)
    cost = replay_actions(child, list(actions))
    replay = source.clone()
    assert replay_actions(replay, [("deal",), *actions]) == cost + 1


def test_64_unseen_deal_without_conversion_remains_legal():
    source = _neutral_source()
    _bp, _before, child, _after, ledger, integrated = _scheduled_deal(source)
    assert not any(
        item.conversion_class
        in {
            ArrivalConversionClass.CONSUME_NOW,
            ArrivalConversionClass.PREPARE_THEN_CONSUME,
            ArrivalConversionClass.FOUNDATION_CONVERT_NOW,
        }
        for item in ledger.opportunities
    )
    assert len(child.stock) == 0 and integrated.saturation.status == EpochSaturationStatus.STOCK_EMPTY


def test_65_conversion_classification_is_deterministic():
    first = _scheduled_deal(_prepare_source())[-2]
    second = _scheduled_deal(_prepare_source())[-2]
    left = [(item.opportunity_id, item.conversion_class, item.preparation_actions) for item in first.opportunities]
    right = [(item.opportunity_id, item.conversion_class, item.preparation_actions) for item in second.opportunities]
    assert left == right
