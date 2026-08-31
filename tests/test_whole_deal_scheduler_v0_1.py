from __future__ import annotations

import inspect
import random
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
    _annotate_scheduler_successors,
    analyze_stage0_state,
    retain_diverse_portfolio,
    solve_anytime,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    AdjacencyStatus,
    ScheduleDeadlineKind,
    ScheduleDeltaKind,
    ScheduleObjectiveFamily,
    ScheduleObjectiveStatus,
    StockReceptionKind,
    TemporalAvailabilityKind,
    WholeDealSchedulerConfig,
    analyze_next_deal_reception,
    build_whole_deal_blueprint,
    choose_scheduler_annotations,
    derive_schedule_delta,
    enumerate_future_rows,
    enumerate_temporal_cards,
    objective_progress,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


def _columns(*values):
    columns = [Column([], list(cards)) for cards in values]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _row(*cards: Card) -> list[Card]:
    result = list(cards)
    result.extend(Card("d", (index % 13) + 1) for index in range(10 - len(result)))
    return result


def _full_material_state(*, late_suit="c", late_rank=3, one_early=False):
    current = []
    stock = []
    for suit in "cdhs":
        for rank in range(1, 14):
            copies = 1 if suit == late_suit and rank == late_rank and one_early else 2
            if suit == late_suit and rank == late_rank and not one_early:
                copies = 0
            current.extend(Card(suit, rank) for _ in range(copies))
    while len(current) < 54:
        current.append(Card("s", (len(current) % 13) + 1))
    # The scheduler accepts exact mid-game material rather than requiring the
    # opening layout.  Put the controlled material face up across ten piles.
    columns = [Column([], []) for _ in range(10)]
    for index, card in enumerate(current):
        columns[index % 10].face_up.append(card)
    late_copies = 1 if one_early else 2
    future = [Card(late_suit, late_rank) for _ in range(late_copies)]
    future.extend(Card("h", (index % 13) + 1) for index in range(10 - len(future)))
    stock.extend(future)
    return SpiderState(columns, stock)


def _successor(before: SpiderState, action, *, category="run_construction"):
    end = before.clone()
    cost = end.move(*action)
    return StrategicSuccessor(
        StrategicActionKind.SAME_SUIT_CONSTRUCTION,
        category,
        "fixture successor",
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


def test_01_unrestricted_deal_is_on_and_empty_column_deal_is_legal():
    state = SpiderState(_columns([], *([[Card("c", 13)]] * 9)), _row(Card("s", 5)))
    assert MW_RULES.can_deal_into_empty and state.can_deal(MW_RULES)
    assert state.deal(MW_RULES) == 1


def test_02_canonical_regression_anchor_unchanged():
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


@pytest.mark.parametrize("column", range(10))
def test_03_future_row_preserves_exact_card_to_column_mapping(column):
    stock = [Card("c", index + 1) for index in range(10)]
    state = SpiderState(_columns(*([[]] * 10)), stock)
    row = enumerate_future_rows(state)[0]
    assert row.cards[column].column == column
    assert row.cards[column].card == stock[column]


def test_04_column_permutation_with_non_symmetric_stock_is_tt_distinct():
    stock = [Card("c", index + 1) for index in range(10)]
    first = SpiderState(_columns([Card("s", 4)], [Card("h", 7)]), stock)
    second = first.clone()
    second.columns[0], second.columns[1] = second.columns[1], second.columns[0]
    assert canonical_state_key(first) != canonical_state_key(second)
    tt = StrategicTranspositionTable()
    assert tt.admit(first, 0) and tt.admit(second, 0) and len(tt) == 2


@pytest.mark.parametrize("deals_done", range(6))
def test_05_epoch_is_derived_from_remaining_stock(deals_done):
    state = SpiderState(_columns(*([[]] * 10)), [Card("c", 1)] * (50 - 10 * deals_done))
    blueprint = build_whole_deal_blueprint(state)
    schedule = rebuild_whole_deal_schedule(state, blueprint)
    assert schedule.epoch == deals_done


@pytest.mark.parametrize(
    "kind",
    list(TemporalAvailabilityKind),
)
def test_06_all_temporal_availability_classes_are_explicit(kind):
    assert kind.value == kind.name


def test_07_tableau_temporal_floor_is_current_epoch_and_actionability_is_separate():
    state = SpiderState(
        [Column([Card("c", 4)], [Card("c", 6), Card("c", 5)])]
        + [Column([], []) for _ in range(9)],
        [Card("h", 1)] * 20,
    )
    refs = enumerate_temporal_cards(state)
    tableau = [item for item in refs if item.column == 0 and item.stock_epoch is None]
    assert {item.availability_epoch for item in tableau} == {3}
    assert {item.temporal_kind for item in tableau} >= {
        TemporalAvailabilityKind.CURRENT_EXPOSED,
        TemporalAvailabilityKind.CURRENT_FACEUP_BURIED,
        TemporalAvailabilityKind.CURRENT_FACEDOWN_KNOWN,
    }


def test_08_future_stock_temporal_floor_is_arrival_epoch():
    state = SpiderState(_columns(*([[]] * 10)), [Card("c", 1)] * 20)
    refs = [item for item in enumerate_temporal_cards(state) if item.stock_epoch]
    assert {item.availability_epoch for item in refs} == {4, 5}


def test_09_removed_foundation_is_accounted_for_and_only_one_lane_remains():
    foundation = [Card("c", rank) for rank in range(13, 0, -1)]
    remaining = [Card("c", rank) for rank in range(1, 14)]
    state = SpiderState(_columns(remaining), [], [foundation])
    blueprint = build_whole_deal_blueprint(state)
    floors = [item for item in blueprint.foundation_floors if item.suit == "c"]
    assert [(item.lane, item.copy_threshold) for item in floors] == [(1, 2)]
    assert floors[0].earliest_epoch == 5


@pytest.mark.parametrize("suit", tuple("cdhs"))
@pytest.mark.parametrize("lane", (1, 2))
def test_10_foundation_floors_are_per_suit_lane_and_non_proof(suit, lane):
    cards = list(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    blueprint = build_whole_deal_blueprint(state)
    floor = next(item for item in blueprint.foundation_floors if item.suit == suit and item.lane == lane)
    assert floor.copy_threshold == lane
    assert floor.proof_pruning_allowed is False
    assert len(floor.counts_by_epoch) == 6


def test_11_per_rank_counts_are_cumulative_by_epoch():
    state = SpiderState(_columns([Card("c", 4)]), _row(Card("c", 4)))
    blueprint = build_whole_deal_blueprint(state)
    assert blueprint.counts("c", 4)[3] == 1
    assert blueprint.counts("c", 5)[3] == 2


def test_12_symmetric_duplicate_assignments_are_canonical():
    state = SpiderState(
        _columns(
            [Card("c", 8), Card("c", 7)],
            [Card("c", 13), Card("c", 12), Card("c", 11)],
        ),
        [],
    )
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    signatures = tuple(lane.assignment_signature for lane in schedule.suit_plans[0].lanes)
    assert signatures == tuple(sorted(signatures))


def test_13_one_copy_early_one_copy_late_splits_only_second_lane():
    state = _full_material_state(late_rank=8, one_early=True)
    blueprint = build_whole_deal_blueprint(state)
    floors = [item for item in blueprint.foundation_floors if item.suit == "c"]
    assert floors[0].earliest_epoch == 4
    assert floors[1].earliest_epoch == 5


@pytest.mark.parametrize("missing_rank", (2, 3, 7, 12))
def test_14_missing_rank_splits_backward_fragments_generically(missing_rank):
    state = _full_material_state(late_rank=missing_rank)
    blueprint = build_whole_deal_blueprint(state)
    fragments = [
        item for item in blueprint.fragments_by_epoch
        if item.suit == "c" and item.lane == 1 and item.target_epoch == 4
    ]
    assert all(missing_rank not in item.required_ranks for item in fragments)
    if missing_rank not in (1, 13):
        assert any(item.low_rank == missing_rank + 1 for item in fragments)
        assert any(item.high_rank == missing_rank - 1 for item in fragments)


def test_15_multiple_missing_ranks_make_multiple_fragments():
    cards = [Card("c", rank) for rank in range(1, 14) if rank not in (5, 9)]
    state = SpiderState(_columns(cards), _row(Card("c", 5), Card("c", 9)))
    blueprint = build_whole_deal_blueprint(state)
    fragments = [
        item for item in blueprint.fragments_by_epoch
        if item.suit == "c" and item.lane == 1 and item.target_epoch == 4
    ]
    assert len(fragments) >= 3


def test_16_late_suit_still_gets_positive_construction_objective():
    state = _full_material_state(late_rank=7)
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    assert any(
        item.suit == "c" and item.family in {
            ScheduleObjectiveFamily.BUILD_FRAGMENT,
            ScheduleObjectiveFamily.PREPARE_TERMINAL_SEQUENCE,
        }
        for item in schedule.objectives
    )


def test_17_existing_stable_run_satisfies_target_edge():
    state = SpiderState(_columns([Card("c", 8), Card("c", 7)]), [])
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    edges = [edge for plan in schedule.suit_plans if plan.suit == "c" for lane in plan.lanes for edge in lane.adjacencies]
    assert any(edge.high_rank == 8 and edge.status == AdjacencyStatus.SATISFIED for edge in edges)


def test_18_free_reception_and_engine_realisation():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    receptions = analyze_next_deal_reception(state)
    assert receptions[0].kind == StockReceptionKind.SAME_SUIT_FREE_JOIN
    assert receptions[0].estimated_preparation_cost == 0
    state.deal()
    assert state.columns[0].face_up[-2:] == [Card("c", 6), Card("c", 5)]


def test_19_foundation_trigger_reception():
    run = [Card("c", rank) for rank in range(13, 1, -1)]
    state = SpiderState(_columns(run), _row(Card("c", 1)))
    assert analyze_next_deal_reception(state)[0].kind == StockReceptionKind.FOUNDATION_TRIGGER


def test_20_useful_empty_column_reception_under_unrestricted_rule():
    state = SpiderState(_columns([], [Card("c", 6)]), _row(Card("c", 5)))
    blueprint = build_whole_deal_blueprint(state)
    schedule = rebuild_whole_deal_schedule(state, blueprint)
    assert schedule.receptions[0].kind == StockReceptionKind.USEFUL_ISOLATION
    assert state.can_deal(MW_RULES)


def test_21_harmful_reception_is_detectable():
    state = SpiderState(
        _columns([Card("c", 8), Card("c", 7)]),
        _row(Card("h", 12)),
    )
    assert analyze_next_deal_reception(state)[0].kind == StockReceptionKind.HARMFUL_RECEPTION


def test_22_expensive_prep_does_not_force_itself_and_deal_now_survives():
    state = SpiderState(_columns([Card("h", 4)]), _row(Card("c", 5)))
    schedule = rebuild_whole_deal_schedule(
        state,
        build_whole_deal_blueprint(state),
        config=WholeDealSchedulerConfig(max_objectives=12, maximum_reception_prep_cost=1),
    )
    reception = schedule.receptions[0]
    assert not reception.worthwhile_preparation
    assert schedule.deal_now_preferred
    assert any(item.family == ScheduleObjectiveFamily.PREPARE_EPOCH_TRANSITION for item in schedule.objectives)


@pytest.mark.parametrize("deadline", list(ScheduleDeadlineKind))
def test_23_deadline_vocabulary_is_complete(deadline):
    assert deadline.value == deadline.name


@pytest.mark.parametrize("family", list(ScheduleObjectiveFamily))
def test_24_forward_objective_portfolio_vocabulary_is_complete(family):
    assert family.value == family.name


@pytest.mark.parametrize("delta_kind", list(ScheduleDeltaKind))
def test_25_schedule_delta_vocabulary_is_complete(delta_kind):
    assert delta_kind.value == delta_kind.name


def test_26_planned_future_free_is_heuristic_not_proof():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    assert schedule.proof_pruning_allowed is False
    assert schedule.receptions[0].proof_pruning_allowed is False
    edge = next(
        edge for plan in schedule.suit_plans if plan.suit == "c"
        for lane in plan.lanes for edge in lane.adjacencies
        if (edge.high_rank, edge.low_rank) == (6, 5)
    )
    assert edge.status == AdjacencyStatus.PLANNED_FUTURE_FREE


def test_27_planned_receiver_invalidates_when_condition_changes():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), _row(Card("c", 5)))
    before = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    objective = next(
        item for item in before.objectives
        if item.family == ScheduleObjectiveFamily.PREPARE_STOCK_RECEPTION
    )
    changed = state.clone()
    changed.move(0, 2, 1)
    assert objective_progress(state, changed, objective) == ScheduleObjectiveStatus.PLANNED


def test_28_bridge_card_ranks_above_one_edge_extension():
    state = SpiderState(
        _columns(
            [Card("c", 7)],
            [Card("c", 5)],
            [Card("c", 4)],
            [Card("d", 8), Card("c", 6)],
        ),
        [],
    )
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    bridge = next(item for item in schedule.leverage_cards if item.card == Card("c", 6) and item.column == 3)
    extension = next(item for item in schedule.leverage_cards if item.card == Card("c", 4) and item.column == 2)
    assert bridge.is_bridge and bridge.ordering_key < extension.ordering_key


def test_29_current_buried_key_card_gets_excavation_not_future_prep():
    state = SpiderState(
        _columns([Card("c", 6), Card("d", 9)], [Card("c", 7)], [Card("c", 5)]),
        [],
    )
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    source = next(item for item in schedule.leverage_cards if item.card == Card("c", 6) and item.column == 0)
    assert source.excavation_candidate
    assert any(item.family == ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD for item in schedule.objectives)


def test_30_future_key_card_gets_surrounding_prep_not_excavation():
    state = SpiderState(_columns([Card("c", 7)], [Card("c", 5)]), _row(Card("c", 6)))
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    future = next(item for item in schedule.leverage_cards if item.card == Card("c", 6) and item.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK)
    assert not future.excavation_candidate and future.is_bridge
    assert any(
        item.source_ref_id == future.source_id
        and item.family in {
            ScheduleObjectiveFamily.BUILD_FRAGMENT,
            ScheduleObjectiveFamily.PRESERVE_USEFUL_FRAGMENT,
        }
        for item in schedule.objectives
    )
    assert not any(
        item.source_ref_id == future.source_id
        and item.family == ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD
        for item in schedule.objectives
    )


def test_31_replan_after_structural_move_and_lane_reassignment():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint)
    after_state = state.clone(); after_state.move(1, 0, 1)
    after = rebuild_whole_deal_schedule(after_state, blueprint, generation=1)
    deltas = derive_schedule_delta(state, after_state, before, after)
    assert before.exact_state_fingerprint != after.exact_state_fingerprint
    assert any(item.kind == ScheduleDeltaKind.TARGET_REASSIGNED for item in deltas)


def test_32_replan_after_deal_records_realised_reception_and_expires_target():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint)
    after_state = state.clone(); after_state.deal()
    after = rebuild_whole_deal_schedule(after_state, blueprint, generation=1)
    deltas = derive_schedule_delta(state, after_state, before, after)
    assert after.epoch == before.epoch + 1
    assert any(item.kind == ScheduleDeltaKind.RECEPTION_REALIZED for item in deltas)
    assert not after.receptions


def test_33_missed_reception_is_recorded_without_impossibility_claim():
    state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint)
    after_state = state.clone(); after_state.move(0, 1, 1); after_state.deal()
    after = rebuild_whole_deal_schedule(after_state, blueprint)
    missed = [item for item in derive_schedule_delta(state, after_state, before, after) if item.kind == ScheduleDeltaKind.RECEPTION_MISSED]
    assert missed and "no impossibility" in missed[0].detail


def test_34_scheduler_converts_objective_to_existing_legal_successor_only():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state), config=WholeDealSchedulerConfig(max_objectives=12))
    successor = _successor(state, (1, 0, 1))
    annotations = choose_scheduler_annotations(state, (successor,), schedule)
    assert annotations and annotations[0][0] == 0 and annotations[0][2] < 2
    assert successor.actions == ((1, 0, 1),)


def test_35_controller_annotation_is_bounded_and_does_not_execute_moves():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state), config=WholeDealSchedulerConfig(max_objectives=12))
    node = StrategicSearchNode(
        0, state, 0, (), None, None, 0, StrategicCreditLevel.CLEAN, None,
        analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
        whole_deal_schedule=schedule,
    )
    candidate = _successor(state, (1, 0, 1))
    telemetry = ControllerTelemetry()
    annotated = _annotate_scheduler_successors(
        node,
        (candidate,),
        AnytimeControllerConfig(enable_whole_deal_scheduler=True, max_scheduler_objectives_in_portfolio=1),
        telemetry,
    )
    assert len(annotated) == 1 and annotated[0].scheduled_objective is not None
    assert state.columns[0].top() == Card("c", 6)


def test_36_portfolio_keeps_scheduler_raw_deal_construction_campaign_and_cashout_categories():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), _row(Card("h", 1)))
    base = _successor(state, (1, 0, 1))
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state), config=WholeDealSchedulerConfig(max_objectives=12))
    objective = choose_scheduler_annotations(state, (base,), schedule)[0][1]
    categories = (
        "run_construction", "raw_fallback", "deal_timing", "campaign", "milestone_conversion"
    )
    candidates = tuple(
        StrategicSuccessor(
            base.kind, category, category, base.actions, base.corrected_cost,
            base.end_state.clone(), base.credit_level, 1, 1, 0, True, False,
            (category,), scheduled_objective=(objective if category == "run_construction" else None),
        )
        for category in categories
    )
    retained = retain_diverse_portfolio(candidates, maximum=5)
    assert {item.category for item in retained} == set(categories)


def test_37_scheduler_is_absent_from_exact_key_and_lower_g_dominance_is_unchanged():
    state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    key_before = canonical_state_key(state)
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    assert canonical_state_key(state) == key_before
    assert "whole_deal_schedule" not in repr(key_before)
    tt = StrategicTranspositionTable()
    assert tt.admit(state, 3)
    assert tt.admit(state, 2)
    assert not tt.admit(state, 2)
    assert schedule.proof_pruning_allowed is False


def test_38_admissible_bound_is_unchanged_by_scheduler():
    state = SpiderState.from_cards(load_deal(DEAL))
    before = compute_solution_lower_bound(state).h_admissible
    rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    assert compute_solution_lower_bound(state).h_admissible == before


def test_39_schedule_ordering_is_deterministic_ignoring_performance_timers():
    state = SpiderState.from_cards(load_deal(DEAL))
    blueprint = build_whole_deal_blueprint(state)
    first = rebuild_whole_deal_schedule(state, blueprint)
    second = rebuild_whole_deal_schedule(state, blueprint)
    assert first == second
    assert tuple(item.objective_id for item in first.objectives) == tuple(item.objective_id for item in second.objectives)


def test_40_production_policy_has_no_benchmark_route_score_or_named_suit_constants():
    source = inspect.getsource(__import__("spider.planner.whole_deal_scheduler", fromlist=["x"]))
    for token in ("492515", "77d169", "924bfd20", "119", "154", "Spades", "Club 3"):
        assert token not in source


@pytest.mark.parametrize("seed", (8101, 8102, 8103))
def test_41_unseen_deal_blueprint_and_forward_replan_are_legal(seed):
    cards = list(load_deal(DEAL)); random.Random(seed).shuffle(cards)
    state = SpiderState.from_cards(cards)
    blueprint = build_whole_deal_blueprint(state)
    before = rebuild_whole_deal_schedule(state, blueprint)
    moves = state.enumerate_moves()
    if moves:
        action = moves[0]
        changed = state.clone()
        cost = changed.move(*action)
        assert replay_actions(state.clone(), [action]) == cost
    else:
        changed = state.clone(); changed.deal()
    after = rebuild_whole_deal_schedule(changed, blueprint, generation=1)
    assert len(blueprint.future_rows) == 5
    assert len(blueprint.foundation_floors) == 8
    assert before.exact_state_fingerprint != after.exact_state_fingerprint
    assert before.objectives and after.objectives


def test_42_benchmark_club_three_fact_is_parsed_not_assumed():
    state = SpiderState.from_cards(load_deal(DEAL))
    blueprint = build_whole_deal_blueprint(state)
    occurrences = [
        (row.epoch, item.column)
        for row in blueprint.future_rows for item in row.cards
        if item.card == Card("c", 3)
    ]
    assert occurrences == [(5, 3), (5, 8)]
    pre_final = [
        item for item in blueprint.fragments_by_epoch
        if item.suit == "c" and item.lane == 1 and item.target_epoch == 4
    ]
    assert any(item.low_rank == 4 for item in pre_final)
    assert any(item.high_rank == 2 for item in pre_final)


def test_43_blueprint_and_schedule_are_debuggable_and_proof_neutral():
    state = SpiderState.from_cards(load_deal(DEAL))
    blueprint = build_whole_deal_blueprint(state)
    schedule = rebuild_whole_deal_schedule(state, blueprint)
    assert blueprint.blueprint_id and schedule.exact_state_fingerprint
    assert not blueprint.proof_pruning_allowed and not schedule.proof_pruning_allowed
    assert blueprint.performance.blueprint_seconds >= 0
    assert schedule.performance.schedule_seconds >= 0


def test_44_scheduler_has_natural_controller_effect_inside_existing_caps():
    cards = load_deal(DEAL)
    result = solve_anytime(
        SpiderState.from_cards(cards),
        cards,
        None,
        AnytimeControllerConfig(
            wall_clock_limit_s=3,
            max_strategic_expansions=1,
            max_tactical_nodes=10_000,
            max_frontier_size=64,
            enable_expensive_deal_timing=False,
            enable_whole_deal_scheduler=True,
        ),
    )
    telemetry = result.telemetry
    assert telemetry.scheduler_blueprints_built == 1
    assert telemetry.scheduler_objectives_entered_portfolio >= 1
    assert telemetry.scheduler_objectives_admitted >= 1
    assert result.strategic_expansions == 1
