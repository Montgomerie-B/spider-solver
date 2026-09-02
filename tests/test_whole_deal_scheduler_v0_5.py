"""Focused regressions for whole-deal scheduler v0.5 conversion handoff."""

from __future__ import annotations

import inspect
from dataclasses import replace

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
    analyze_stage0_state,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    FoundationLaneMaturationState,
    ScheduleObjectiveFamily,
    WholeDealSchedulerConfig,
    converted_lane_cash_out_shift,
    lead_maturation_legal_step,
    rebuild_whole_deal_schedule,
    build_whole_deal_blueprint,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key

from test_whole_deal_scheduler_v0_4 import (
    DEAL,
    ROOT,
    _assessment,
    _building_state,
    _cards,
    _matured_schedule,
    _merge_state,
    _node,
    _state,
    _successor,
    _terminal_state,
)


def _conversion_child(state, schedule, arrival_id="arrival-converted"):
    incoming = StrategicSuccessor(
        StrategicActionKind.RAW_TABLEAU_MOVE,
        "other",
        "integrated arrival",
        (),
        0,
        state,
        StrategicCreditLevel.CLEAN,
        0,
        0,
        0,
        True,
        False,
        ("fixture conversion",),
        arrival_conversion_opportunity_id=arrival_id,
        arrival_conversion_class=scheduler.ArrivalConversionClass.CONSUME_NOW,
    )
    return replace(
        _node(state, schedule),
        incoming_edge=incoming,
        parent_id=0,
    )


def _annotate(state, schedule, candidates=(), arrival_id="arrival-converted"):
    telemetry = ControllerTelemetry()
    annotated = _annotate_scheduler_successors(
        _conversion_child(state, schedule, arrival_id),
        tuple(candidates),
        AnytimeControllerConfig(
            enable_whole_deal_scheduler=True,
            max_scheduler_objectives_in_portfolio=1,
        ),
        telemetry,
    )
    return annotated, telemetry


def test_01_lead_converted_lane_emits_legal_bridge_successor():
    state = _merge_state()
    schedule = _matured_schedule(state)
    assert schedule.lane_sequence_priority.lead.state == (
        FoundationLaneMaturationState.MERGE_READY
    )
    step = lead_maturation_legal_step(schedule)
    assert step is not None
    annotated, telemetry = _annotate(state, schedule)
    maturation = [
        item
        for item in annotated
        if item.scheduled_objective is not None
        and item.maturation_lane_fingerprint
    ]
    assert maturation
    assert telemetry.lane_maturation_successors_generated >= 1
    replay = state.clone()
    assert replay_actions(replay, list(maturation[0].actions)) == maturation[0].corrected_cost


def test_02_terminal_ready_converted_lane_emits_existing_terminal_successor():
    state = _terminal_state()
    schedule = _matured_schedule(state)
    assert schedule.lane_sequence_priority.lead.state == (
        FoundationLaneMaturationState.TERMINAL_READY
    )
    objective = schedule.objectives[0]
    assert objective.family == ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE
    annotated, telemetry = _annotate(state, schedule)
    chosen = next(
        item
        for item in annotated
        if item.scheduled_objective is not None
        and item.scheduled_objective.family
        == ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE
    )
    end = state.clone()
    replay_actions(end, list(chosen.actions))
    assert len(end.foundations) == len(state.foundations) + 1
    assert telemetry.lane_maturation_successors_generated >= 1


def test_03_causal_arrival_id_survives_onto_maturation_successor():
    state = _merge_state()
    schedule = _matured_schedule(state)
    annotated, _telemetry = _annotate(state, schedule, arrival_id="arrival-js")
    tagged = [item for item in annotated if item.maturation_lane_fingerprint]
    assert tagged
    assert tagged[0].arrival_conversion_opportunity_id == "arrival-js"
    assert tagged[0].maturation_lane_fingerprint == (
        schedule.lane_sequence_priority.lead.lane_fingerprint
    )


def test_04_non_lead_converted_lane_is_not_forced():
    state = _state(
        Column([], _cards("c", (9,))),
        Column([], _cards("c", (8, 7))),
        Column([], _cards("d", (5,))),
        Column([], _cards("d", (4,))),
    )
    schedule = _matured_schedule(
        state, specifications=(("c", 5, ()), ("d", 5, ()))
    )
    lead = schedule.lane_sequence_priority.lead
    assert lead.suit == "c"
    diamond = next(
        item
        for item in schedule.lane_maturation_assessments
        if item.suit == "d"
    )
    assert diamond.lane_fingerprint != lead.lane_fingerprint
    incoming = replace(
        _successor(state, (3, 2, 1)),
        arrival_conversion_opportunity_id="arrival-d",
        arrival_conversion_class=scheduler.ArrivalConversionClass.CONSUME_NOW,
    )
    node = replace(_node(state, schedule), incoming_edge=incoming, parent_id=0)
    telemetry = ControllerTelemetry()
    annotated = _annotate_scheduler_successors(
        node,
        (),
        AnytimeControllerConfig(
            enable_whole_deal_scheduler=True,
            max_scheduler_objectives_in_portfolio=1,
        ),
        telemetry,
    )
    forced = [
        item
        for item in annotated
        if item.maturation_lane_fingerprint == diamond.lane_fingerprint
    ]
    assert forced == []
    assert not any(item.maturation_lane_fingerprint for item in annotated)
    assert schedule.lane_sequence_priority.lead.suit == "c"


def test_05_no_extra_portfolio_slot():
    state = _merge_state()
    schedule = _matured_schedule(state)
    assert len(schedule.objectives) <= 4
    assert len(schedule.lane_portfolio_decision.maturation_objective_ids) <= 1
    _annotate(state, schedule)
    assert len(schedule.objectives) <= 4
    assert len(schedule.lane_portfolio_decision.maturation_objective_ids) <= 1


def test_06_no_representative_is_introduced():
    source = inspect.getsource(controller)
    assert "lane_maturation_representatives_required" in source
    telemetry = ControllerTelemetry()
    assert telemetry.lane_maturation_representatives_required == 0
    assert telemetry.lane_maturation_representatives_reserved == 0
    assert telemetry.lane_maturation_representatives_expanded == 0
    emit = inspect.getsource(controller._emit_lead_maturation_legal_successor)
    assert "representative" not in emit.lower()


def test_07_exact_tt_identity_unchanged():
    state = _merge_state()
    schedule = _matured_schedule(state)
    tt = StrategicTranspositionTable()
    assert tt.best_g(state) is None
    assert tt.admit(state, 3)
    assert tt.best_g(state) == 3
    assert not tt.admit(state, 3)
    _annotate(state, schedule)
    assert canonical_state_key(state) == canonical_state_key(state.clone())
    assert tt.best_g(state) == 3


def test_08_proof_bounds_unchanged():
    state = _merge_state()
    before = compute_solution_lower_bound(state)
    _matured_schedule(state)
    assert compute_solution_lower_bound(state) == before
    assert ControllerTelemetry().scheduler_proof_prunes == 0
    assert not _assessment(state)[1].proof_pruning_allowed


def test_09_cash_out_shift_flags_join_with_worsened_rehandling():
    before_state = _building_state()
    after_state = _merge_state()
    before = _matured_schedule(before_state)
    after = _matured_schedule(after_state)
    shift = converted_lane_cash_out_shift(before, after, "c")
    assert shift is not None
    assert shift.suit == "c"
    assert shift.proof_pruning_allowed is False


def test_10_no_benchmark_constants_in_v05_policy():
    source = inspect.getsource(scheduler)
    assert "4925153" not in source
    assert "77d169da2538ba8c" not in source
    ctrl = inspect.getsource(controller._emit_lead_maturation_legal_successor)
    assert "4925153" not in ctrl


def test_11_existing_raw_fallback_is_reclassified_not_duplicated():
    state = _merge_state()
    schedule = _matured_schedule(state)
    step = lead_maturation_legal_step(schedule)
    assert step is not None
    raw = replace(
        _successor(state, step[2].actions[0]),
        kind=StrategicActionKind.RAW_TABLEAU_MOVE,
        category="raw_fallback",
    )
    annotated, _telemetry = _annotate(state, schedule, candidates=(raw,))
    matching = [
        item for item in annotated if tuple(item.actions) == tuple(step[2].actions)
    ]
    assert len(matching) == 1
    assert matching[0].kind == StrategicActionKind.SAME_SUIT_CONSTRUCTION
    assert matching[0].category == "run_construction"
    assert matching[0].maturation_lane_fingerprint == (
        schedule.lane_sequence_priority.lead.lane_fingerprint
    )
    assert matching[0].arrival_conversion_opportunity_id == "arrival-converted"


def test_12_emitted_maturation_successor_is_tt_admissible():
    state = _merge_state()
    schedule = _matured_schedule(state)
    annotated, _telemetry = _annotate(state, schedule)
    tagged = [item for item in annotated if item.maturation_lane_fingerprint]
    assert tagged
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 0)
    assert tt.admit(tagged[0].end_state, tagged[0].corrected_cost)
    assert tt.best_g(tagged[0].end_state) == tagged[0].corrected_cost
    assert not tt.admit(tagged[0].end_state, tagged[0].corrected_cost)
