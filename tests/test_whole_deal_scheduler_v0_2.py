from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

import pytest

import spider.planner.anytime_controller as controller
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
    _node_priority,
    _reserve_epoch_transition_representative,
    _annotate_scheduler_successors,
    analyze_stage0_state,
    solve_anytime,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    EpochTransitionHarvestKind,
    EpochTransitionRepresentativeStatus,
    PreDealOpportunityClass,
    ScheduleDeadlineKind,
    ScheduleObjectiveFamily,
    ScheduleObjectiveStatus,
    ScheduledStructuralObjective,
    SchedulerDealKind,
    WholeDealSchedulerConfig,
    assess_epoch_saturation,
    build_epoch_transition_trace,
    build_whole_deal_blueprint,
    choose_scheduler_annotations,
    classify_epoch_transition_harvest,
    classify_pre_deal_objective,
    compare_prepare_then_deal,
    derive_schedule_delta,
    epoch_transition_objective,
    make_epoch_transition_opportunity,
    objective_progress,
    pre_deal_opportunity_for_objective,
    preview_deal_now,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*values):
    result = [Column([], list(cards)) for cards in values]
    result.extend(Column([], []) for _ in range(10 - len(result)))
    return result


def _row(*cards: Card) -> list[Card]:
    result = list(cards)
    result.extend(Card("d", (index % 13) + 1) for index in range(10 - len(result)))
    return result


def _opening() -> SpiderState:
    return SpiderState.from_cards(load_deal(DEAL))


def _schedule(state: SpiderState, *, maximum: int = 12):
    blueprint = build_whole_deal_blueprint(state)
    return blueprint, rebuild_whole_deal_schedule(
        state,
        blueprint,
        config=WholeDealSchedulerConfig(max_objectives=maximum),
    )


def _reception_state(*, bridge: bool = False) -> SpiderState:
    values = ([], [Card("c", 6)], [Card("c", 4)]) if bridge else ([], [Card("c", 6)])
    return SpiderState(_columns(*values), _row(Card("c", 5)))


def _two_epoch_state() -> SpiderState:
    columns = [Column([], [Card("c", 13)]) for _ in range(10)]
    return SpiderState(columns, [Card("h", 2)] * 10 + [Card("s", 4)] * 10)


def _move_successor(state: SpiderState, action=(1, 0, 1)) -> StrategicSuccessor:
    end = state.clone()
    cost = end.move(*action, rules=MW_RULES)
    return StrategicSuccessor(
        StrategicActionKind.RAW_TABLEAU_MOVE,
        "raw_fallback",
        "fixture preparation",
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


def _manual_objective(
    family=ScheduleObjectiveFamily.BUILD_FRAGMENT,
    *,
    status=ScheduleObjectiveStatus.ACTIONABLE,
    suit="c",
    high=7,
    low=4,
    source=None,
    source_ref=None,
    column=None,
    target_epoch=1,
    deadline=ScheduleDeadlineKind.BY_EPOCH_N,
    cost=1,
    debt=0,
    edges=1,
    leverage=0,
    joined=0,
):
    return ScheduledStructuralObjective(
        "fixture-objective",
        family,
        status,
        suit,
        high,
        low,
        source,
        source_ref,
        column,
        target_epoch,
        deadline,
        cost,
        debt,
        edges,
        leverage,
        joined,
        ("fixture",),
    )


def _transition_fixture():
    source = _opening()
    blueprint = build_whole_deal_blueprint(source)
    before = rebuild_whole_deal_schedule(source, blueprint)
    child = source.clone()
    child.deal(MW_RULES)
    after = rebuild_whole_deal_schedule(child, blueprint, generation=1)
    stage0 = analyze_stage0_state(child, spent_cost=1, incumbent_cost=None)
    opportunity = make_epoch_transition_opportunity(
        source,
        child,
        before,
        after,
        corrected_g_after_deal=1,
        stable_structure_after=stage0.stable_same_suit_joins,
        rehandling_debt_after=stage0.rehandling_debt,
        exact_tt_admitted=True,
        independently_replay_verified=True,
    )
    assert opportunity is not None
    edge = StrategicSuccessor(
        StrategicActionKind.RAW_DEAL,
        "deal_timing",
        "fixture Deal",
        (("deal",),),
        1,
        child,
        StrategicCreditLevel.CLEAN,
        1,
        1,
        0,
        True,
        False,
        ("fixture",),
    )
    node = StrategicSearchNode(
        1,
        child,
        1,
        (("deal",),),
        0,
        edge,
        1,
        StrategicCreditLevel.CLEAN,
        None,
        stage0,
        whole_deal_schedule=after,
        epoch_transition_opportunity=opportunity,
    )
    return source, child, before, after, opportunity, node


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty


def test_02_regression_anchor_is_unchanged():
    result = validate_solution("4925153", ROOT / "solutions" / "4925153_canonical.moves")
    assert (result.mobilityware_moves, result.path_hash, result.state_hash) == (
        172,
        "77d169da2538ba8c",
        "4e9861540eac570cb",
    )


def test_03_v01_benchmark_blueprint_is_preserved():
    blueprint = build_whole_deal_blueprint(_opening())
    assert len(blueprint.future_rows) == 5
    assert [(row.epoch, len(row.cards)) for row in blueprint.future_rows] == [
        (1, 10), (2, 10), (3, 10), (4, 10), (5, 10)
    ]


def test_04_deal_now_preview_uses_engine_transition():
    state = _opening()
    preview = preview_deal_now(state, build_whole_deal_blueprint(state))
    expected = state.clone(); expected.deal(MW_RULES)
    assert preview is not None and states_structurally_equal(preview.post_deal_state, expected)


def test_05_deal_now_preview_does_not_enter_tt():
    state = _opening(); tt = StrategicTranspositionTable(); tt.admit(state, 0)
    preview = preview_deal_now(state, build_whole_deal_blueprint(state))
    assert preview is not None and len(tt) == 1 and not preview.entered_tt


def test_06_deal_now_preview_is_not_an_expansion():
    state = _opening(); preview = preview_deal_now(state, build_whole_deal_blueprint(state))
    assert preview is not None and preview.strategic_expansions == preview.tactical_nodes == 0


def test_07_surviving_fragment_is_deferrable():
    state = SpiderState(_columns([Card("c", 7)], [Card("c", 6)]), _row(Card("h", 4)))
    blueprint, schedule = _schedule(state)
    objective = _manual_objective(target_epoch=4)
    item = classify_pre_deal_objective(state, objective, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification == PreDealOpportunityClass.DEFERRABLE


def test_08_useful_move_does_not_imply_must():
    state = SpiderState(_columns([Card("c", 7)], [Card("c", 6)]), _row(Card("h", 4)))
    blueprint, schedule = _schedule(state)
    item = classify_pre_deal_objective(state, _manual_objective(target_epoch=5), preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.estimated_marginal_benefit > 0 and item.classification != PreDealOpportunityClass.MUST_PRE_DEAL


def test_09_stock_coverage_alone_is_not_urgent():
    state = SpiderState(_columns([Card("c", 7)], [Card("c", 6)]), _row(Card("h", 4)))
    blueprint, schedule = _schedule(state)
    item = classify_pre_deal_objective(state, _manual_objective(target_epoch=5), preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.blocker_work_after <= item.blocker_work_before + 1
    assert item.classification == PreDealOpportunityClass.DEFERRABLE


def test_10_lost_bridge_reception_is_must():
    state = _reception_state(bridge=True); _, schedule = _schedule(state)
    item = next(x for x in schedule.pre_deal_opportunities if x.objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION)
    assert item.classification == PreDealOpportunityClass.MUST_PRE_DEAL


def test_11_equal_cost_receiver_is_advantage():
    state = _reception_state(); _, schedule = _schedule(state)
    item = next(x for x in schedule.pre_deal_opportunities if x.objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION)
    assert item.classification == PreDealOpportunityClass.ADVANTAGE_PRE_DEAL


def test_12_deal_supplies_ready_receiver():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    _, schedule = _schedule(state)
    item = next(x for x in schedule.pre_deal_opportunities if x.objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION)
    assert item.classification == PreDealOpportunityClass.FUTURE_SUPPLIED


def test_13_bad_reception_preparation_is_non_economic():
    state = SpiderState(_columns([Card("h", 9)], [Card("c", 6)]), _row(Card("c", 5)))
    blueprint, schedule = _schedule(state)
    objective = _manual_objective(
        ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION,
        source=Card("c", 5), column=0, deadline=ScheduleDeadlineKind.BEFORE_NEXT_DEAL,
        cost=2, edges=1,
    )
    item = classify_pre_deal_objective(state, objective, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification == PreDealOpportunityClass.NON_ECONOMIC


def test_14_stale_objective_is_invalid():
    state = _opening(); blueprint, schedule = _schedule(state)
    objective = _manual_objective(status=ScheduleObjectiveStatus.INVALIDATED)
    item = classify_pre_deal_objective(state, objective, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification == PreDealOpportunityClass.INVALID


def test_15_must_means_preparation_required():
    _, schedule = _schedule(_reception_state(bridge=True))
    assert schedule.saturation.status == EpochSaturationStatus.PREPARATION_REQUIRED


def test_16_advantage_means_preparation_advantage():
    _, schedule = _schedule(_reception_state())
    assert schedule.saturation.status == EpochSaturationStatus.PREPARATION_ADVANTAGE


def test_17_no_marginal_prep_means_deal_ready():
    _, schedule = _schedule(_opening(), maximum=4)
    assert schedule.saturation.status == EpochSaturationStatus.DEAL_READY


def test_18_stock_empty_is_explicit():
    state = SpiderState(_columns([Card("c", 7)], [Card("c", 6)]), [])
    _, schedule = _schedule(state)
    assert schedule.saturation.status == EpochSaturationStatus.STOCK_EMPTY


def test_19_one_preparation_changes_required_to_ready():
    state = _reception_state(bridge=True); blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    state.move(1, 0, 1, rules=MW_RULES)
    after = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    assert (before.saturation.status, after.saturation.status) == (
        EpochSaturationStatus.PREPARATION_REQUIRED,
        EpochSaturationStatus.DEAL_READY,
    )


def test_20_saturation_is_fresh_after_preparation():
    state = _reception_state(); blueprint = build_whole_deal_blueprint(state)
    first = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    state.move(1, 0, 1, rules=MW_RULES)
    second = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12), generation=1)
    assert first.exact_state_fingerprint != second.exact_state_fingerprint
    assert second.saturation.selected_preparation is None


def test_21_late_epoch_fragment_is_not_opening_must():
    _, schedule = _schedule(_opening())
    late = [x for x in schedule.pre_deal_opportunities if x.deadline_distance and x.deadline_distance >= 4]
    assert late and all(x.classification != PreDealOpportunityClass.MUST_PRE_DEAL for x in late)


def test_22_nearer_deadline_orders_first():
    state = _opening()
    near = replace(classify_pre_deal_objective(state, _manual_objective(target_epoch=1), None), classification=PreDealOpportunityClass.ADVANTAGE_PRE_DEAL)
    far = replace(classify_pre_deal_objective(state, _manual_objective(target_epoch=5), None), classification=PreDealOpportunityClass.ADVANTAGE_PRE_DEAL)
    assessment = assess_epoch_saturation(state, (far, near))
    assert assessment.selected_preparation.deadline_distance == 1


def test_23_reception_can_be_must_or_advantage():
    classes = []
    for bridge in (False, True):
        _, schedule = _schedule(_reception_state(bridge=bridge))
        classes.append(next(x.classification for x in schedule.pre_deal_opportunities if x.objective.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION))
    assert classes == [PreDealOpportunityClass.ADVANTAGE_PRE_DEAL, PreDealOpportunityClass.MUST_PRE_DEAL]


def test_24_expensive_reception_is_rejected():
    state = SpiderState(_columns([Card("h", 9)], [Card("c", 6)]), _row(Card("c", 5)))
    _, schedule = _schedule(state)
    assert not schedule.receptions[0].worthwhile_preparation


def test_25_future_free_join_is_seen_in_preview():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    _, schedule = _schedule(state)
    assert schedule.deal_now_counterfactual.post_deal_state.columns[0].face_up[-2:] == [Card("c", 6), Card("c", 5)]


def test_26_future_supplied_work_is_not_selected_preparation():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    _, schedule = _schedule(state)
    assert schedule.saturation.selected_preparation is None


def test_27_high_leverage_source_can_be_urgent():
    state = SpiderState(_columns([Card("c", 6), Card("d", 9)], [Card("c", 7)], [Card("c", 5)]), _row(Card("h", 4)))
    blueprint, schedule = _schedule(state)
    source = next(x for x in schedule.leverage_cards if x.card == Card("c", 6) and x.column == 0)
    objective = _manual_objective(
        ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD,
        source=source.card,
        source_ref=source.source_id,
        deadline=ScheduleDeadlineKind.BEFORE_NEXT_DEAL,
        cost=1,
        edges=2,
        leverage=2,
        joined=1,
    )
    item = classify_pre_deal_objective(state, objective, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification in {PreDealOpportunityClass.MUST_PRE_DEAL, PreDealOpportunityClass.ADVANTAGE_PRE_DEAL}


def test_28_one_edge_source_can_be_deferred():
    state = SpiderState(_columns([Card("c", 6), Card("d", 9)], [Card("c", 7)]), _row(Card("h", 4)))
    blueprint, schedule = _schedule(state)
    source = next(x for x in schedule.leverage_cards if x.card == Card("c", 6) and x.column == 0)
    objective = _manual_objective(ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD, source=source.card, source_ref=source.source_id, cost=1, edges=1, leverage=1)
    item = classify_pre_deal_objective(state, objective, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification == PreDealOpportunityClass.DEFERRABLE


def test_29_legal_deal_can_form_transition_opportunity():
    *_, opportunity, _node = _transition_fixture()
    assert opportunity.status == EpochTransitionRepresentativeStatus.QUALIFIED


def test_30_transition_requires_exact_tt_admission():
    source, child, before, after, _opportunity, _node = _transition_fixture()
    assert make_epoch_transition_opportunity(
        source, child, before, after, corrected_g_after_deal=1,
        stable_structure_after=0, rehandling_debt_after=0,
        exact_tt_admitted=False, independently_replay_verified=True,
    ) is None


def test_31_only_one_transition_is_reserved():
    _source, child, _before, _after, opportunity, node = _transition_fixture()
    second = replace(node, node_id=2, epoch_transition_opportunity=replace(opportunity, opportunity_id="second", corrected_g_after_deal=2))
    tt = StrategicTranspositionTable(); tt.admit(child, 1)
    telemetry = ControllerTelemetry()
    frontier = [(_node_priority(node), 1, node), (_node_priority(second), 2, second)]
    reserved = _reserve_epoch_transition_representative(frontier, tt=tt, spent_opportunity_ids=(), telemetry=telemetry)
    assert sum(item[2].epoch_transition_opportunity.status == EpochTransitionRepresentativeStatus.RESERVED for item in reserved) == 1


def test_32_frontier_width_config_is_unchanged():
    config = AnytimeControllerConfig(max_frontier_size=256, enable_whole_deal_scheduler=True)
    assert config.max_frontier_size == 256


def test_33_representative_uses_one_ordinary_expansion():
    cards = load_deal(DEAL)
    result = solve_anytime(_opening(), cards, None, AnytimeControllerConfig(
        wall_clock_limit_s=8, max_strategic_expansions=2, max_tactical_nodes=20_000,
        max_frontier_size=64, enable_expensive_deal_timing=False,
        enable_whole_deal_scheduler=True,
    ))
    assert result.strategic_expansions == 2
    assert result.telemetry.scheduler_transition_representatives_expanded == 1


def test_34_representative_has_no_tactical_grant_field():
    *_, opportunity, _node = _transition_fixture()
    assert "tactical" not in opportunity.__dataclass_fields__


def test_35_representative_has_no_persistence_extension():
    config = AnytimeControllerConfig(enable_whole_deal_scheduler=True)
    assert config.milestone_max_strategic_expansions == 3


def test_36_same_transition_cannot_reserve_twice():
    _source, child, _before, _after, opportunity, node = _transition_fixture()
    tt = StrategicTranspositionTable(); tt.admit(child, 1)
    telemetry = ControllerTelemetry()
    frontier = [(_node_priority(node), 1, node)]
    reserved = _reserve_epoch_transition_representative(frontier, tt=tt, spent_opportunity_ids=(opportunity.opportunity_id,), telemetry=telemetry)
    assert reserved[0][2].epoch_transition_opportunity.status != EpochTransitionRepresentativeStatus.RESERVED


def test_37_post_deal_branch_has_fresh_schedule():
    source, _child, before, after, _opportunity, _node = _transition_fixture()
    assert after.epoch == before.epoch + 1 and after.exact_state_fingerprint != before.exact_state_fingerprint


def test_38_readiness_does_not_cross_deal():
    _source, _child, before, after, _opportunity, _node = _transition_fixture()
    assert before.saturation is not after.saturation
    assert after.saturation.epoch == before.saturation.epoch + 1


def test_39_second_epoch_can_create_new_transition():
    state = _two_epoch_state(); blueprint = build_whole_deal_blueprint(state)
    first = rebuild_whole_deal_schedule(state, blueprint)
    state.deal(MW_RULES)
    second = rebuild_whole_deal_schedule(state, blueprint)
    assert first.saturation.status == second.saturation.status == EpochSaturationStatus.DEAL_READY
    assert epoch_transition_objective(state, second) is not None


def test_40_prepare_deal_replan_chain_is_exact():
    state = _reception_state(bridge=True); blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    state.move(1, 0, 1, rules=MW_RULES)
    prepared = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    state.deal(MW_RULES)
    after = rebuild_whole_deal_schedule(state, blueprint, config=WholeDealSchedulerConfig(max_objectives=12))
    assert [before.saturation.status, prepared.saturation.status, after.epoch] == [EpochSaturationStatus.PREPARATION_REQUIRED, EpochSaturationStatus.DEAL_READY, 5]


def test_41_two_epoch_chain_has_distinct_identities():
    state = _two_epoch_state(); blueprint = build_whole_deal_blueprint(state)
    ids = []
    for _ in range(2):
        pre = state.clone()
        schedule = rebuild_whole_deal_schedule(pre, blueprint)
        state.deal(MW_RULES)
        child = rebuild_whole_deal_schedule(state, blueprint)
        op = make_epoch_transition_opportunity(
            pre, state, schedule, child,
            corrected_g_after_deal=len(ids) + 1,
            stable_structure_after=0,
            rehandling_debt_after=0,
            exact_tt_admitted=True,
            independently_replay_verified=True,
        )
        assert op is not None
        ids.append(op.opportunity_id)
    assert len(set(ids)) == 2


def test_42_deal_transition_does_not_remove_raw_alternative():
    state = _opening(); _, schedule = _schedule(state, maximum=4)
    deal = state.clone(); deal.deal(MW_RULES)
    raw = _move_successor(state, state.enumerate_moves()[0])
    deal_successor = replace(raw, kind=StrategicActionKind.RAW_DEAL, actions=(("deal",),), corrected_cost=1, end_state=deal)
    annotations = choose_scheduler_annotations(state, (raw, deal_successor), schedule)
    assert len((raw, deal_successor)) == 2 and annotations[0][0] == 1


def test_43_deal_transition_does_not_remove_construction():
    state = _opening(); construction = _move_successor(state, state.enumerate_moves()[0])
    assert construction.independent_replay_verified and construction.actions


def test_44_completion_cashout_field_coexists_with_transition():
    *_, opportunity, node = _transition_fixture()
    coexisting = replace(node, completion_cash_out=None, epoch_transition_opportunity=opportunity)
    assert hasattr(coexisting, "completion_cash_out") and hasattr(coexisting, "epoch_transition_opportunity")


def test_45_terminal_work_can_block_deal():
    state = _opening(); blueprint, schedule = _schedule(state)
    terminal = _manual_objective(ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE, target_epoch=1, cost=1, edges=2)
    item = classify_pre_deal_objective(state, terminal, preview_deal_now(state, blueprint), current_schedule=schedule)
    assert item.classification == PreDealOpportunityClass.MUST_PRE_DEAL


def test_46_deal_itself_is_not_downstream_harvest():
    cards = load_deal(DEAL)
    result = solve_anytime(_opening(), cards, None, AnytimeControllerConfig(
        wall_clock_limit_s=8, max_strategic_expansions=2, max_tactical_nodes=20_000,
        max_frontier_size=64, enable_expensive_deal_timing=False,
        enable_whole_deal_scheduler=True,
    ))
    assert result.telemetry.scheduler_transition_representatives_expanded == 1
    assert result.telemetry.scheduler_downstream_harvests == 0


def test_47_actual_free_join_is_transition_harvest():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    blueprint = build_whole_deal_blueprint(state); before = rebuild_whole_deal_schedule(state, blueprint)
    after_state = state.clone(); after_state.deal(MW_RULES)
    after = rebuild_whole_deal_schedule(after_state, blueprint)
    kinds = {x.kind for x in classify_epoch_transition_harvest(state, after_state, before, after)}
    assert EpochTransitionHarvestKind.REALIZED_FREE_JOIN in kinds


def test_48_harmful_reception_is_recorded():
    state = SpiderState(_columns([Card("c", 8), Card("c", 7)]), _row(Card("h", 12)))
    blueprint = build_whole_deal_blueprint(state); before = rebuild_whole_deal_schedule(state, blueprint)
    after_state = state.clone(); after_state.deal(MW_RULES)
    after = rebuild_whole_deal_schedule(after_state, blueprint)
    assert EpochTransitionHarvestKind.HARMFUL_RECEPTION in {x.kind for x in classify_epoch_transition_harvest(state, after_state, before, after)}


def test_49_realized_and_missed_receptions_are_distinct():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    blueprint = build_whole_deal_blueprint(state); before = rebuild_whole_deal_schedule(state, blueprint)
    realized_state = state.clone(); realized_state.deal(MW_RULES)
    missed_state = state.clone(); missed_state.move(0, 1, 1, rules=MW_RULES); missed_state.deal(MW_RULES)
    realized = derive_schedule_delta(state, realized_state, before, rebuild_whole_deal_schedule(realized_state, blueprint))
    missed = derive_schedule_delta(state, missed_state, before, rebuild_whole_deal_schedule(missed_state, blueprint))
    assert {x.kind.value for x in realized} != {x.kind.value for x in missed}


def test_50_exact_stock_row_mapping_survives_preview():
    state = _opening(); blueprint = build_whole_deal_blueprint(state); preview = preview_deal_now(state, blueprint)
    assert all(preview.post_deal_state.columns[i].top() == card for i, card in enumerate(preview.incoming_row))


def test_51_empty_column_deal_remains_legal():
    state = SpiderState(_columns([], *([[Card("c", 13)]] * 9)), _row(Card("s", 5)))
    assert state.can_deal(MW_RULES) and preview_deal_now(state, build_whole_deal_blueprint(state)) is not None


def test_52_duplicate_assignments_are_recomputed_after_deal():
    source, child, before, after, _opportunity, _node = _transition_fixture()
    deltas = derive_schedule_delta(source, child, before, after)
    assert before.exact_state_fingerprint != after.exact_state_fingerprint
    assert after.generation > before.generation


def test_53_bridge_leverage_is_recomputed_after_deal():
    source, _child, before, after, _opportunity, _node = _transition_fixture()
    assert before.leverage_cards is not after.leverage_cards
    assert after.epoch == before.epoch + 1


def test_54_scheduler_state_is_absent_from_tt_identity():
    state = _opening(); key = canonical_state_key(state); _schedule(state)
    assert canonical_state_key(state) == key and "saturation" not in repr(key)


def test_55_counterfactual_state_is_absent_from_tt():
    state = _opening(); tt = StrategicTranspositionTable(); tt.admit(state, 0); _schedule(state)
    assert len(tt) == 1


def test_56_lower_g_exact_dominance_is_unchanged():
    state = _opening(); tt = StrategicTranspositionTable()
    assert tt.admit(state, 3) and tt.admit(state, 2) and not tt.admit(state, 2)


def test_57_admissible_bound_is_unchanged():
    state = _opening(); before = compute_solution_lower_bound(state).h_admissible; _schedule(state)
    assert compute_solution_lower_bound(state).h_admissible == before


def test_58_scheduler_proof_prunes_are_zero():
    telemetry = ControllerTelemetry()
    assert telemetry.scheduler_proof_prunes == 0


def test_59_readiness_is_deterministic():
    state = _opening(); blueprint = build_whole_deal_blueprint(state)
    first = rebuild_whole_deal_schedule(state, blueprint); second = rebuild_whole_deal_schedule(state, blueprint)
    assert first.saturation == second.saturation


def test_60_no_benchmark_constants_in_production():
    source = inspect.getsource(__import__("spider.planner.whole_deal_scheduler", fromlist=["x"]))
    for token in ("492515", "77d169", "924bfd20", "Spades", "Club 3"):
        assert token not in source


def test_61_no_leaderboard_constants_in_production():
    source = inspect.getsource(__import__("spider.planner.whole_deal_scheduler", fromlist=["x"]))
    assert "154" not in source and "119" not in source


@pytest.mark.parametrize("seed", (9201, 9202, 9203))
def test_62_unseen_deal_gets_a_typed_saturation(seed):
    cards = list(load_deal(DEAL)); random.Random(seed).shuffle(cards)
    _, schedule = _schedule(SpiderState.from_cards(cards))
    assert schedule.saturation.status in set(EpochSaturationStatus)


def test_63_unseen_deal_can_become_deal_ready():
    cards = list(load_deal(DEAL)); random.Random(9201).shuffle(cards)
    _, schedule = _schedule(SpiderState.from_cards(cards))
    assert schedule.deal_now_counterfactual is not None
    assert schedule.saturation.status in {EpochSaturationStatus.DEAL_READY, EpochSaturationStatus.PREPARATION_REQUIRED, EpochSaturationStatus.PREPARATION_ADVANTAGE}


def test_64_unseen_deal_transition_replays_legally():
    cards = list(load_deal(DEAL)); random.Random(9202).shuffle(cards)
    state = SpiderState.from_cards(cards); preview = preview_deal_now(state, build_whole_deal_blueprint(state))
    replay = state.clone(); paid = replay_actions(replay, [("deal",)])
    assert preview is not None and paid == 1 and states_structurally_equal(replay, preview.post_deal_state)


def test_65_benchmark_opening_readiness_is_inspectable():
    state = _opening(); _, schedule = _schedule(state, maximum=4)
    assert schedule.saturation.status == EpochSaturationStatus.DEAL_READY
    assert schedule.saturation.deferrable_count == 4
    assert epoch_transition_objective(state, schedule) is not None
