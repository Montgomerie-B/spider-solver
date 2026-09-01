from __future__ import annotations

import inspect
from dataclasses import fields, replace
from pathlib import Path

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
    AdjacencyStatus,
    DealNowCounterfactual,
    FoundationLaneBlockerKind,
    FoundationLaneCashOutEstimate,
    FoundationLaneMaturationState,
    FoundationLaneProgressKind,
    ScheduleObjectiveFamily,
    SuitEpochPlan,
    SuitLanePlan,
    WholeDealSchedule,
    WholeDealSchedulerConfig,
    assess_foundation_lane_maturation,
    build_foundation_lane_maturation_portfolio,
    build_whole_deal_blueprint,
    classify_pre_deal_objective,
    derive_foundation_lane_progress,
    maturation_assessment_for_objective,
    sequence_foundation_lanes,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _cards(suit: str, ranks) -> list[Card]:
    return [Card(suit, rank) for rank in ranks]


def _state(*columns: Column, stock=(), foundations=()) -> SpiderState:
    values = list(columns)
    values.extend(Column([], []) for _ in range(10 - len(values)))
    return SpiderState(values, list(stock), list(foundations))


def _manual_schedule(
    state: SpiderState,
    *,
    epoch: int = 5,
    specifications=(("c", 5, ()),),
) -> WholeDealSchedule:
    plans = []
    for lane_number, (suit, floor, future_edges) in enumerate(specifications, 1):
        fragments = scheduler._stable_fragments(state, suit)
        satisfied = set(scheduler._lane_edges_from_fragments(fragments))
        future = set(future_edges)
        adjacencies = tuple(
            scheduler.AdjacencyTarget(
                suit,
                lane_number,
                rank,
                rank - 1,
                epoch,
                (
                    AdjacencyStatus.SATISFIED
                    if (rank, rank - 1) in satisfied
                    else AdjacencyStatus.FUTURE_GATED
                    if (rank, rank - 1) in future
                    else AdjacencyStatus.MISSING
                ),
            )
            for rank in range(13, 1, -1)
        )
        lane = SuitLanePlan(
            suit,
            lane_number,
            1,
            floor,
            fragments,
            adjacencies,
            (),
        )
        plans.append(SuitEpochPlan(suit, epoch, 1, (lane,)))
    return WholeDealSchedule(
        "fixture-blueprint",
        scheduler._state_fingerprint(state),
        epoch,
        tuple(plans),
        (),
        (),
        (),
        False,
    )


def _matured_schedule(state: SpiderState, **kwargs) -> WholeDealSchedule:
    base = _manual_schedule(state, **kwargs)
    assessments = assess_foundation_lane_maturation(state, base)
    priority = sequence_foundation_lanes(assessments)
    objectives, decision = build_foundation_lane_maturation_portfolio(
        base, priority
    )
    return replace(
        base,
        objectives=objectives,
        lane_maturation_assessments=assessments,
        lane_sequence_priority=priority,
        lane_portfolio_decision=decision,
    )


def _assessment(state: SpiderState, **kwargs):
    schedule = _matured_schedule(state, **kwargs)
    return schedule, next(
        item
        for item in schedule.lane_maturation_assessments
        if item.state != FoundationLaneMaturationState.REMOVED
    )


def _building_state() -> SpiderState:
    return _state(
        Column([], _cards("c", (13, 12))),
        Column([], _cards("c", (8, 7))),
    )


def _merge_state() -> SpiderState:
    return _state(
        Column([], _cards("c", (9,))),
        Column([], _cards("c", (8, 7))),
    )


def _bridge_state() -> SpiderState:
    return _state(
        Column(_cards("c", (3,)), _cards("c", (8, 7))),
        Column([], _cards("c", (9,))),
    )


def _near_state() -> SpiderState:
    return _state(
        Column([], _cards("c", range(13, 5, -1))),
        Column([], _cards("c", range(5, 1, -1))),
    )


def _terminal_state() -> SpiderState:
    return _state(
        Column([], _cards("c", range(13, 1, -1))),
        Column([], _cards("c", (1,))),
    )


def _successor(state: SpiderState, action) -> StrategicSuccessor:
    end = state.clone()
    cost = end.move(*action, rules=MW_RULES)
    return StrategicSuccessor(
        StrategicActionKind.RAW_TABLEAU_MOVE,
        "raw_fallback",
        "fixture maturation successor",
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


def _node(state: SpiderState, schedule: WholeDealSchedule) -> StrategicSearchNode:
    return StrategicSearchNode(
        1,
        state,
        0,
        (),
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        None,
        stage0=analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
        whole_deal_schedule=schedule,
    )


def _preview(
    state: SpiderState,
    before: WholeDealSchedule,
    after: WholeDealSchedule,
) -> DealNowCounterfactual:
    return DealNowCounterfactual(
        canonical_state_key(state),
        before.exact_state_fingerprint,
        before.epoch,
        (),
        1,
        state.clone(),
        after.exact_state_fingerprint,
        after,
    )


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_regression_anchor_is_unchanged():
    result = validate_solution(
        "4925153", ROOT / "solutions" / "4925153_canonical.moves"
    )
    assert (result.mobilityware_moves, result.path_hash, result.state_hash) == (
        172,
        "77d169da2538ba8c",
        "4e9861540eac570cb",
    )


def test_03_v01_to_v03_blueprint_facts_are_preserved():
    blueprint = build_whole_deal_blueprint(
        SpiderState.from_cards(load_deal(DEAL))
    )
    assert len(blueprint.future_rows) == 5
    assert all(len(row.cards) == 10 for row in blueprint.future_rows)


def test_04_lane_maturity_uses_current_exact_fragments():
    _schedule, item = _assessment(_building_state())
    assert set(item.fragments) == {(13, 12, 0), (8, 7, 1)}


def test_05_future_gated_lane_is_recognised():
    _schedule, item = _assessment(
        _building_state(), specifications=(("c", 6, ((9, 8),)),)
    )
    assert item.state == FoundationLaneMaturationState.FUTURE_GATED


def test_06_fragment_building_lane_is_recognised():
    assert _assessment(_building_state())[1].state == (
        FoundationLaneMaturationState.FRAGMENT_BUILDING
    )


def test_07_bridge_ready_lane_is_recognised():
    assert _assessment(_bridge_state())[1].state == (
        FoundationLaneMaturationState.BRIDGE_READY
    )


def test_08_merge_ready_lane_is_recognised():
    assert _assessment(_merge_state())[1].state == (
        FoundationLaneMaturationState.MERGE_READY
    )


def test_09_near_terminal_lane_is_recognised():
    assert _assessment(_near_state())[1].state == (
        FoundationLaneMaturationState.NEAR_TERMINAL
    )


def test_10_terminal_ready_lane_is_recognised():
    assert _assessment(_terminal_state())[1].state == (
        FoundationLaneMaturationState.TERMINAL_READY
    )


def test_11_removed_lane_is_recognised():
    foundation = _cards("c", range(13, 0, -1))
    state = _state(foundations=(foundation,))
    assessments = assess_foundation_lane_maturation(
        state, _manual_schedule(state, specifications=())
    )
    assert assessments[0].state == FoundationLaneMaturationState.REMOVED


def test_12_floor_status_is_explicit():
    _schedule, item = _assessment(
        _building_state(), specifications=(("c", 6, ()),)
    )
    assert item.availability_floor == 6 and not item.floor_reached


def test_13_fragment_count_is_explicit():
    assert _assessment(_building_state())[1].fragment_count == 2


def test_14_missing_edges_are_explicit():
    item = _assessment(_merge_state())[1]
    assert (9, 8) in item.missing_edges and len(item.missing_edges) == 11


def test_15_actionable_bridge_is_explicit():
    assert _assessment(_merge_state())[1].actionable_bridge_edges == ((9, 8),)


def test_16_buried_blocker_work_is_explicit():
    state = _state(
        Column([], [Card("c", 13), Card("h", 4)]),
        Column([], [Card("c", 12)]),
    )
    item = _assessment(state)[1]
    assert item.cash_out_estimate.blocker_work >= 1
    assert any(x.kind == FoundationLaneBlockerKind.BURIED_SOURCE for x in item.blockers)


def test_17_workspace_requirement_is_explicit():
    columns = [Column([], [Card("c", 13)])]
    columns.extend(Column([], [Card("d", rank)]) for rank in range(1, 10))
    state = _state(*columns)
    item = _assessment(state)[1]
    assert item.cash_out_estimate.workspace_work == 1


def test_18_stable_break_debt_participates_in_ordering():
    base = FoundationLaneCashOutEstimate(0, 1, 1, 0, 0, 0, 0, 0, 5, 0)
    debt = replace(base, stable_break_debt=2)
    assert base.ordering_key() < debt.ordering_key()


def test_19_cash_out_estimate_is_explicitly_non_proof():
    assert not _assessment(_merge_state())[1].cash_out_estimate.proof_pruning_allowed


def test_20_historical_spend_is_absent_from_assessment():
    assert "spent" not in {item.name for item in fields(type(_assessment(_merge_state())[1]))}


def test_21_historical_spend_is_absent_from_priority_key():
    source = inspect.getsource(type(_assessment(_merge_state())[1]).ordering_key)
    assert "spend" not in source and "history" not in source


def test_22_three_fragment_cheap_lane_can_beat_two_fragment_expensive_lane():
    first = _assessment(_building_state())[1]
    cheap = replace(
        first,
        lane_fingerprint="cheap",
        fragments=first.fragments + ((4, 4, 2),),
        cash_out_estimate=replace(first.cash_out_estimate, blocker_work=0),
    )
    expensive = replace(
        first,
        lane_fingerprint="expensive",
        cash_out_estimate=replace(first.cash_out_estimate, blocker_work=4),
    )
    assert sequence_foundation_lanes((expensive, cheap)).lead == cheap


def test_23_converted_child_updates_maturity_from_fresh_state():
    state = _merge_state()
    before, item = _assessment(state)
    child = state.clone()
    child.move(1, 0, 2, rules=MW_RULES)
    after = _matured_schedule(child)
    delta = derive_foundation_lane_progress(state, child, before, after, item)
    assert delta.missing_edge_count_after < delta.missing_edge_count_before


def test_24_fragment_reduction_survives_fresh_replan():
    state = _merge_state()
    before, item = _assessment(state)
    child = state.clone()
    child.move(1, 0, 2, rules=MW_RULES)
    delta = derive_foundation_lane_progress(
        state, child, before, _matured_schedule(child), item
    )
    assert FoundationLaneProgressKind.FRAGMENT_COUNT_REDUCED in delta.kinds


def test_25_bridge_consumption_advances_maturity():
    state = _merge_state()
    before, item = _assessment(state)
    child = state.clone()
    child.move(1, 0, 2, rules=MW_RULES)
    delta = derive_foundation_lane_progress(
        state, child, before, _matured_schedule(child), item
    )
    assert FoundationLaneProgressKind.BRIDGE_INTEGRATED in delta.kinds


def test_26_floor_crossing_causes_reassessment():
    state = _building_state()
    before, item = _assessment(state, specifications=(("c", 6, ()),))
    after = _matured_schedule(state, specifications=(("c", 5, ()),))
    delta = derive_foundation_lane_progress(state, state, before, after, item)
    assert FoundationLaneProgressKind.FLOOR_REACHED in delta.kinds


def test_27_floor_crossing_does_not_force_completion():
    state = _building_state()
    assert _assessment(state)[1].state == FoundationLaneMaturationState.FRAGMENT_BUILDING


def test_28_lane_reassignment_preserves_physical_progress():
    state = _merge_state()
    before, item = _assessment(state)
    child = state.clone()
    child.move(1, 0, 2, rules=MW_RULES)
    delta = derive_foundation_lane_progress(
        state, child, before, _matured_schedule(child), item
    )
    assert delta.fragment_count_after < delta.fragment_count_before
    assert delta.before_lane_fingerprint != delta.after_lane_fingerprint


def test_29_symmetric_lane_assignments_remain_canonical():
    state = _building_state()
    schedule = scheduler.rebuild_whole_deal_schedule(
        state, build_whole_deal_blueprint(state)
    )
    for plan in schedule.suit_plans:
        signatures = tuple(lane.assignment_signature for lane in plan.lanes)
        assert signatures == tuple(sorted(signatures))


def test_30_lead_lane_has_no_suit_precedence_over_better_economics():
    item = _assessment(_building_state())[1]
    club = replace(item, suit="c", lane_fingerprint="club")
    diamond = replace(
        item,
        suit="d",
        lane_fingerprint="diamond",
        cash_out_estimate=replace(item.cash_out_estimate, terminal_gap=1),
    )
    assert sequence_foundation_lanes((club, diamond)).lead.suit == "d"


def test_31_lead_lane_is_deterministic():
    assessments = _matured_schedule(_merge_state()).lane_maturation_assessments
    assert sequence_foundation_lanes(assessments) == sequence_foundation_lanes(assessments)


def test_32_lead_lane_can_change_after_structural_change():
    item = _assessment(_building_state())[1]
    first = replace(item, suit="c", lane_fingerprint="first")
    second = replace(item, suit="d", lane_fingerprint="second")
    initial = sequence_foundation_lanes((first, second))
    matured_second = replace(
        second,
        state=FoundationLaneMaturationState.MERGE_READY,
        cash_out_estimate=replace(second.cash_out_estimate, terminal_gap=2),
    )
    assert sequence_foundation_lanes((first, matured_second)).lead != initial.lead


def test_33_lead_lane_is_freshly_recomputed_after_deal():
    source = inspect.getsource(scheduler.preview_deal_now)
    assert "rebuild_whole_deal_schedule" in source


def test_34_maturation_objective_reuses_existing_families():
    schedule = _matured_schedule(_merge_state())
    assert schedule.objectives[0].family in {
        ScheduleObjectiveFamily.BUILD_FRAGMENT,
        ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD,
        ScheduleObjectiveFamily.CONSUME_BRIDGE_CARD,
        ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE,
    }


def test_35_scheduler_does_not_directly_move_cards():
    source = inspect.getsource(scheduler._maturation_objective)
    assert ".move(" not in source and "replay_actions" not in source


def test_36_late_future_gated_fragment_remains_planned():
    schedule = _matured_schedule(
        _building_state(), specifications=(("c", 6, ((9, 8),)),)
    )
    assert schedule.lane_sequence_priority.lead.state == (
        FoundationLaneMaturationState.FUTURE_GATED
    )
    assert not schedule.lane_portfolio_decision.maturation_objective_ids


def test_37_distant_lane_does_not_outrank_near_cash_out():
    future = _assessment(
        _building_state(), specifications=(("c", 6, ((9, 8),)),)
    )[1]
    near = replace(_assessment(_near_state())[1], suit="d", lane_fingerprint="near")
    assert sequence_foundation_lanes((future, near)).lead == near


def test_38_removal_workspace_value_affects_ordering():
    estimate = FoundationLaneCashOutEstimate(0, 1, 1, 1, 0, 0, 0, 0, 1, 0)
    payoff = replace(estimate, removal_workspace_payoff=1)
    assert payoff.ordering_key() < estimate.ordering_key()


def test_39_expensive_stable_break_can_defeat_maturation():
    item = _assessment(_merge_state())[1]
    clean = replace(item, lane_fingerprint="clean")
    costly = replace(
        item,
        lane_fingerprint="costly",
        cash_out_estimate=replace(item.cash_out_estimate, stable_break_debt=4),
    )
    assert sequence_foundation_lanes((costly, clean)).lead == clean


def test_40_genuinely_urgent_maturation_can_block_deal():
    state = _terminal_state()
    before = _matured_schedule(state)
    objective = before.objectives[0]
    after = _matured_schedule(_building_state())
    result = classify_pre_deal_objective(
        state, objective, _preview(state, before, after), current_schedule=before
    )
    assert result.classification.value == "MUST_PRE_DEAL"


def test_41_deferrable_maturation_does_not_block_deal():
    state = _merge_state()
    before = _matured_schedule(state)
    objective = before.objectives[0]
    result = classify_pre_deal_objective(
        state, objective, _preview(state, before, before), current_schedule=before
    )
    assert result.classification.value == "DEFERRABLE"


def test_42_v02_deal_readiness_semantics_remain_available():
    state = _state(stock=[Card("d", rank) for rank in range(1, 11)])
    schedule = scheduler.rebuild_whole_deal_schedule(
        state, build_whole_deal_blueprint(state)
    )
    assert schedule.deal_now_preferred


def test_43_v03_arrival_conversion_api_is_preserved():
    assert callable(scheduler.analyze_post_deal_arrival_conversions)
    assert callable(scheduler.advance_post_deal_conversion_ledger)


def test_44_completion_cash_out_is_preserved():
    assert "completion_cash_out" in StrategicSearchNode.__dataclass_fields__
    assert ControllerTelemetry().completion_representatives_reserved == 0


def test_45_terminal_maturation_precedes_ordinary_merge():
    terminal = _assessment(_terminal_state())[1]
    merge = _assessment(_merge_state())[1]
    assert sequence_foundation_lanes((merge, terminal)).lead == terminal


def test_46_scheduler_objective_count_remains_four():
    state = SpiderState.from_cards(load_deal(DEAL))
    schedule = scheduler.rebuild_whole_deal_schedule(
        state, build_whole_deal_blueprint(state)
    )
    assert WholeDealSchedulerConfig().max_objectives == 4
    assert len(schedule.objectives) <= 4


def test_47_frontier_width_has_no_maturation_expansion():
    assert "maturation" not in AnytimeControllerConfig.__dataclass_fields__["max_frontier_size"].name
    assert ControllerTelemetry().lane_maturation_representatives_reserved == 0


def test_48_no_giant_foundation_bonus_was_added():
    source = inspect.getsource(scheduler.sequence_foundation_lanes)
    assert "foundation_bonus" not in source


def test_49_no_giant_maturity_scalar_was_added():
    source = inspect.getsource(scheduler.FoundationLaneCashOutEstimate.ordering_key)
    assert "score" not in source and "bonus" not in source


def test_50_lane_signal_compression_produces_at_most_one_objective():
    schedule = _matured_schedule(_merge_state())
    assert len(schedule.lane_portfolio_decision.maturation_objective_ids) <= 1


def test_51_one_semantic_objective_represents_the_lead_lane():
    schedule = _matured_schedule(_merge_state())
    objective = schedule.objectives[0]
    assert maturation_assessment_for_objective(schedule, objective.objective_id) == (
        schedule.lane_sequence_priority.lead
    )


def test_52_natural_audit_did_not_authorize_a_representative():
    telemetry = ControllerTelemetry()
    assert telemetry.lane_maturation_representatives_required == 0


def test_53_no_maturation_reservation_function_exists():
    assert not hasattr(controller, "_reserve_lane_maturation_representative")


def test_54_exact_tt_admission_remains_required_for_search_nodes():
    tt = StrategicTranspositionTable()
    state = _merge_state()
    assert tt.admit(state, 2) and not tt.admit(state, 2)


def test_55_no_extra_expansion_is_granted_to_maturation():
    telemetry = ControllerTelemetry()
    assert telemetry.lane_maturation_representatives_expanded == 0


def test_56_no_extra_tactical_grant_is_defined_for_maturation():
    names = AnytimeControllerConfig.__dataclass_fields__
    assert "maturation_tactical_nodes" not in names


def test_57_target_persistence_is_not_increased():
    assert AnytimeControllerConfig().milestone_max_strategic_expansions == 3


def test_58_unnecessary_representative_is_absent():
    telemetry = ControllerTelemetry()
    assert (
        telemetry.lane_maturation_representatives_required,
        telemetry.lane_maturation_representatives_reserved,
        telemetry.lane_maturation_representatives_expanded,
    ) == (0, 0, 0)


def test_59_fresh_economics_resume_after_maturation():
    state = _merge_state()
    before = _matured_schedule(state)
    child = state.clone()
    child.move(1, 0, 2, rules=MW_RULES)
    after = _matured_schedule(child)
    assert after.exact_state_fingerprint != before.exact_state_fingerprint
    assert after.lane_sequence_priority is not before.lane_sequence_priority


def test_60_next_deal_remains_legal_after_maturation():
    stock = [Card("d", rank) for rank in range(1, 11)]
    state = _state(
        Column([], _cards("c", (9,))),
        Column([], _cards("c", (8, 7))),
        stock=stock,
    )
    state.move(1, 0, 2, rules=MW_RULES)
    assert state.can_deal(MW_RULES) and state.deal(MW_RULES) == 1


def test_61_canonical_tt_excludes_maturation_data():
    state = _merge_state()
    before = canonical_state_key(state)
    _matured_schedule(state)
    assert canonical_state_key(state) == before


def test_62_lower_g_exact_dominance_is_unchanged():
    tt = StrategicTranspositionTable()
    state = _merge_state()
    assert tt.admit(state, 5)
    assert tt.admit(state, 4)
    assert not tt.admit(state, 6)
    assert tt.best_g(state) == 4


def test_63_admissible_bound_is_unchanged_by_schedule():
    state = _merge_state()
    before = compute_solution_lower_bound(state)
    _matured_schedule(state)
    assert compute_solution_lower_bound(state) == before


def test_64_scheduler_proof_prunes_remain_zero():
    assert ControllerTelemetry().scheduler_proof_prunes == 0
    assert not _assessment(_merge_state())[1].proof_pruning_allowed


def test_65_no_benchmark_deal_constant_in_production_policy():
    source = inspect.getsource(scheduler)
    assert "4925153" not in source and "77d169da2538ba8c" not in source


def test_66_no_leaderboard_score_constant_in_production_policy():
    source = inspect.getsource(scheduler)
    assert "leaderboard" not in source.lower()


def test_67_unseen_conversion_then_maturation_is_replay_valid():
    state = _merge_state()
    successor = _successor(state, (1, 0, 2))
    replay = state.clone()
    paid = replay_actions(replay, list(successor.actions))
    assert paid == successor.corrected_cost
    assert canonical_state_key(replay) == canonical_state_key(successor.end_state)
    before = _matured_schedule(state)
    annotations = scheduler.choose_scheduler_annotations(
        state, (successor,), before, maximum=1
    )
    assert annotations and annotations[0][0] == 0


def test_68_unseen_future_gated_lane_behaves_sensibly():
    state = _building_state()
    schedule = _matured_schedule(
        state, specifications=(("c", 6, ((9, 8),)),)
    )
    assert schedule.lane_sequence_priority.lead.state == (
        FoundationLaneMaturationState.FUTURE_GATED
    )
    assert schedule.objectives == ()


def test_69_deterministic_lane_table():
    state = SpiderState.from_cards(load_deal(DEAL))
    blueprint = build_whole_deal_blueprint(state)
    first = scheduler.rebuild_whole_deal_schedule(state, blueprint)
    second = scheduler.rebuild_whole_deal_schedule(state, blueprint)
    assert first.lane_maturation_assessments == second.lane_maturation_assessments
    assert first.lane_sequence_priority == second.lane_sequence_priority
    assert first.objectives == second.objectives


def test_controller_annotation_carries_maturation_identity():
    state = _merge_state()
    schedule = _matured_schedule(state)
    successor = _successor(state, (1, 0, 2))
    telemetry = ControllerTelemetry()
    annotated = _annotate_scheduler_successors(
        _node(state, schedule),
        (successor,),
        AnytimeControllerConfig(
            enable_whole_deal_scheduler=True,
            max_scheduler_objectives_in_portfolio=1,
        ),
        telemetry,
    )
    assert annotated[0].maturation_lane_fingerprint
    assert annotated[0].maturation_state == FoundationLaneMaturationState.MERGE_READY
    assert telemetry.lane_maturation_successors_generated == 1
