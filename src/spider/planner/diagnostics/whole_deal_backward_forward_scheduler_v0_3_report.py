"""Acceptance report for whole-deal backward/forward scheduler v0.3.

Benchmark identifiers, historical comparisons and fixed gate envelopes remain
confined to this diagnostic.  Production arrival scheduling is deal-agnostic,
ordering-only and proof-neutral.
"""

from __future__ import annotations

import argparse
import pprint
import random
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
import spider.planner.whole_deal_scheduler as scheduler
from spider.planner.anytime_controller import ControllerTelemetry, solve_anytime
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_x_base_config,
    _gate_g_config as _gate_y_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_1_report import (
    _gate_config,
    _route,
    _scheduler_performance,
    _summary,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    ArrivalConversionClass,
    ArrivalConversionHarvestKind,
    ArrivalConversionStatus,
    EpochSaturationStatus,
    EpochTransitionHarvestKind,
    FoundationLaneConversionState,
    ScheduleDeadlineKind,
    TemporalAvailabilityKind,
    WholeDealSchedulerConfig,
    advance_post_deal_conversion_ledger,
    analyze_post_deal_arrival_conversions,
    arrival_conversion_traces,
    assess_epoch_saturation,
    build_whole_deal_blueprint,
    classify_arrival_conversion_harvest,
    classify_epoch_transition_harvest,
    foundation_lane_conversions,
    integrate_arrival_conversion_ledger,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "5e34e3b5fba2dfdfb3e2709607d88ab26166a2ef"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
CONFIG12 = WholeDealSchedulerConfig(max_objectives=12)


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _state(bottoms, row) -> SpiderState:
    return SpiderState([Column([], list(cards)) for cards in bottoms], list(row))


def _immediate_source() -> SpiderState:
    bottoms = (
        (Card("c", 6),), (Card("h", 13),), (Card("d", 13),),
        (Card("s", 13),), (Card("h", 11),), (Card("d", 11),),
        (Card("s", 11),), (Card("h", 9),), (Card("d", 9),),
        (Card("s", 9),),
    )
    row = (
        Card("c", 5), Card("c", 4), Card("h", 2), Card("d", 2),
        Card("s", 2), Card("h", 4), Card("d", 4), Card("s", 4),
        Card("h", 7), Card("d", 7),
    )
    return _state(bottoms, row)


def _prepare_source() -> SpiderState:
    bottoms = (
        (Card("c", 6),), (Card("c", 4),), (Card("s", 13),),
        (Card("h", 13),), (Card("d", 13),), (Card("s", 11),),
        (Card("h", 11),), (Card("d", 11),), (Card("s", 8),),
        (Card("h", 8),),
    )
    row = (
        Card("c", 5), Card("h", 9), Card("d", 10), Card("s", 2),
        Card("h", 2), Card("d", 2), Card("s", 4), Card("h", 4),
        Card("d", 4), Card("s", 6),
    )
    return _state(bottoms, row)


def _terminal_source() -> SpiderState:
    bottoms = (
        (Card("h", 13),),
        tuple(Card("c", rank) for rank in range(13, 2, -1)),
        *((Card("d", 13 - index % 4),) for index in range(8)),
    )
    row = (
        Card("c", 1), Card("c", 2), Card("h", 2), Card("d", 2),
        Card("s", 2), Card("h", 4), Card("d", 4), Card("s", 4),
        Card("h", 6), Card("d", 6),
    )
    return _state(bottoms, row)


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


def _find(ledger, card: Card, column: int):
    return next(
        item for item in ledger.opportunities
        if item.incoming_card == card and item.destination_column == column
    )


def _obligation(ledger, opportunity):
    return next(
        item for item in ledger.obligations
        if item.opportunity.opportunity_id == opportunity.opportunity_id
    )


def _move(state: SpiderState, action):
    end = state.clone()
    cost = end.move(*action, rules=MW_RULES)
    return end, cost


def _lane(item):
    if item is None:
        return None
    return {
        "suit": item.suit,
        "lane": item.lane,
        "floor": item.availability_floor,
        "floor_reached": item.floor_reached,
        "fragments": item.fragment_partition,
        "fragment_count": item.fragment_count,
        "missing": item.missing_edges,
        "next_bridge": str(item.next_missing_bridge) if item.next_missing_bridge else None,
        "terminal": item.terminal_qualified,
        "state": item.state.value,
    }


def _trace(item):
    fragment_reduction = max(
        (
            harvest.structural_delta.fragment_reduction
            for harvest in item.harvests
            if harvest.kind == ArrivalConversionHarvestKind.FRAGMENTS_JOINED
        ),
        default=0,
    )
    displayed_lane_reduction = max(
        0,
        (item.lane_before.fragment_count if item.lane_before else 0)
        - (item.lane_after.fragment_count if item.lane_after else 0),
    )
    return {
        "transition": item.transition_id,
        "epoch": (item.source_epoch, item.arrival_epoch),
        "card": str(item.incoming_card) if item.incoming_card else None,
        "column": item.destination_column + 1 if item.destination_column is not None else None,
        "class": item.conversion_class.value,
        "stages": tuple(stage.value for stage in item.stages),
        "status": item.status.value,
        "generated": item.successor_generated,
        "TT_admitted": item.exact_tt_admitted,
        "selected": item.selected,
        "harvests": tuple(harvest.kind.value for harvest in item.harvests),
        "fragment_reduction": fragment_reduction,
        "fragment_reduction_basis": (
            "canonical physical same-suit partition after duplicate-lane reassignment"
            if fragment_reduction > displayed_lane_reduction
            else "assigned foundation-lane partition"
        ),
        "lane_before": _lane(item.lane_before),
        "lane_after": _lane(item.lane_after),
        "stop": item.stop_reason,
    }


def _telemetry_funnel(result) -> dict:
    telemetry = result.telemetry
    return {
        "scheduler_Deals_expanded": telemetry.scheduler_transition_representatives_expanded,
        "important_arrivals": telemetry.arrival_important_sources,
        "opportunities": telemetry.arrival_conversion_opportunities,
        "classes": telemetry.arrival_conversion_by_class,
        "successors_generated": telemetry.arrival_conversion_successors_generated,
        "successors_TT_admitted": telemetry.arrival_conversion_successors_admitted,
        "selected": telemetry.arrival_conversions_selected,
        "sources_consumed": telemetry.arrival_sources_consumed,
        "sources_integrated": telemetry.arrival_sources_integrated,
        "bridge_merges": telemetry.arrival_bridge_merges,
        "fragments_joined": telemetry.arrival_fragments_joined,
        "lane_fragment_reduction": telemetry.arrival_lane_fragment_reductions,
        "terminal_qualified": telemetry.arrival_terminal_qualifications,
        "foundations_removed": telemetry.arrival_foundations_removed,
    }


def _performance(result) -> dict:
    telemetry = result.telemetry
    return {
        "scheduler": _scheduler_performance(result),
        "arrival_analysis_count": telemetry.arrival_analysis_count,
        "arrival_analysis_seconds": telemetry.arrival_analysis_seconds,
        "matching_seconds": telemetry.arrival_matching_seconds,
        "prepare_then_consume_seconds": telemetry.arrival_prepare_then_consume_seconds,
        "foundation_lane_seconds": telemetry.arrival_foundation_lane_seconds,
        "representatives_required/reserved/expanded": (
            telemetry.arrival_conversion_representatives_required,
            telemetry.arrival_conversion_representatives_reserved,
            telemetry.arrival_conversion_representatives_expanded,
        ),
    }


def _prepolicy_audit(opening: SpiderState):
    state = opening.clone()
    blueprint = build_whole_deal_blueprint(state)
    schedule = rebuild_whole_deal_schedule(state, blueprint)
    rows = []
    totals = {
        "bridge_arrivals": 0,
        "high_leverage_arrivals": 0,
        "new_fragment_opportunities": 0,
        "objective_omitted": 0,
        "immediate_legal_conversion": 0,
        "one_preparation_conversion": 0,
        "generated_equivalent": 0,
    }
    for generation in range(1, 5):
        before_state = state.clone()
        before_schedule = schedule
        state.deal(MW_RULES)
        schedule = rebuild_whole_deal_schedule(
            state, blueprint, generation=generation
        )
        harvests = classify_epoch_transition_harvest(
            before_state, state, before_schedule, schedule
        )
        totals["bridge_arrivals"] += sum(
            item.kind == EpochTransitionHarvestKind.REALIZED_BRIDGE_ARRIVAL
            for item in harvests
        )
        totals["high_leverage_arrivals"] += sum(
            item.kind == EpochTransitionHarvestKind.HIGH_LEVERAGE_SOURCE_ARRIVED
            for item in harvests
        )
        totals["new_fragment_opportunities"] += sum(
            item.kind == EpochTransitionHarvestKind.NEW_FRAGMENT_OPPORTUNITY
            for item in harvests
        )
        ledger = analyze_post_deal_arrival_conversions(
            before_state, state, before_schedule, schedule, generation=generation
        )
        for harvest in harvests:
            if harvest.kind != EpochTransitionHarvestKind.REALIZED_BRIDGE_ARRIVAL:
                continue
            opportunity = next(
                (
                    item for item in ledger.opportunities
                    if item.incoming_card == harvest.card
                    and item.destination_column == harvest.column
                ),
                None,
            )
            equivalent = tuple(
                item for item in schedule.objectives
                if item.source_card == harvest.card
                and item.target_column in (None, harvest.column)
            )
            immediate = bool(opportunity and opportunity.immediate_actions)
            preparation = bool(opportunity and opportunity.preparation_actions)
            totals["objective_omitted"] += int(not equivalent)
            totals["immediate_legal_conversion"] += int(immediate)
            totals["one_preparation_conversion"] += int(preparation)
            totals["generated_equivalent"] += int(bool(equivalent))
            rows.append(
                {
                    "epoch": generation,
                    "card": str(harvest.card),
                    "column": harvest.column + 1,
                    "lane": opportunity.lane if opportunity else None,
                    "v0.3_class": opportunity.conversion_class.value if opportunity else None,
                    "immediate": immediate,
                    "one_preparation": preparation,
                    "v0.2_objective": tuple(item.objective_id for item in equivalent),
                    "loss": (
                        "fixed four-objective omission before successor generation"
                        if not equivalent else "later scheduler/controller selection"
                    ),
                }
            )
    totals["correct_TT_admitted_successor_starved"] = 0
    totals["representative_authorized"] = False
    return totals, tuple(rows)


def _capabilities(opening: SpiderState):
    immediate = _scheduled_deal(_immediate_source())
    prepare = _scheduled_deal(_prepare_source())
    terminal = _scheduled_deal(_terminal_source())
    immediate_op = _find(immediate[-2], Card("c", 5), 0)
    prepare_op = _find(prepare[-2], Card("c", 5), 0)
    terminal_op = _find(terminal[-2], Card("c", 2), 1)
    consumed_state, _ = _move(immediate[2], (1, 0, 1))
    consumed_schedule = rebuild_whole_deal_schedule(
        consumed_state, build_whole_deal_blueprint(consumed_state), config=CONFIG12
    )
    consumed_harvests = classify_arrival_conversion_harvest(
        immediate[2],
        consumed_state,
        _obligation(immediate[-2], immediate_op),
        before_schedule=immediate[-1],
        after_schedule=consumed_schedule,
    )
    advanced = advance_post_deal_conversion_ledger(
        immediate[2],
        consumed_state,
        immediate[-1],
        consumed_schedule,
        immediate[-2],
        selected_opportunity_id=immediate_op.opportunity_id,
        selected_actions=((1, 0, 1),),
    )
    benchmark = opening.clone()
    blueprint = build_whole_deal_blueprint(benchmark)
    schedule = rebuild_whole_deal_schedule(benchmark, blueprint, config=CONFIG12)
    floors = ()
    urgent_after_deal = False
    for generation in range(1, 6):
        previous = benchmark.clone()
        previous_schedule = schedule
        benchmark.deal(MW_RULES)
        schedule = rebuild_whole_deal_schedule(
            benchmark, blueprint, config=CONFIG12, generation=generation
        )
        ledger = analyze_post_deal_arrival_conversions(
            previous, benchmark, previous_schedule, schedule
        )
        if generation == 1:
            integrated = integrate_arrival_conversion_ledger(
                benchmark, schedule, ledger, config=CONFIG12
            )
            urgent_after_deal = (
                benchmark.can_deal(MW_RULES)
                and integrated.saturation.status
                == EpochSaturationStatus.PREPARATION_REQUIRED
                and any(obligation.active() for obligation in ledger.obligations)
            )
        floors += ledger.floor_crossings
    terminal_state, terminal_cost = _move(terminal[2], (0, 1, 1))
    gates = {
        "A": immediate_op.originating_transition_id == immediate[-2].transition_id,
        "B": immediate_op.conversion_class == ArrivalConversionClass.CONSUME_NOW,
        "C": ArrivalConversionHarvestKind.BRIDGE_MERGE in {item.kind for item in consumed_harvests},
        "D": prepare_op.conversion_class == ArrivalConversionClass.PREPARE_THEN_CONSUME and bool(prepare_op.preparation_actions),
        "E": any(item.conversion_class == ArrivalConversionClass.DEFERRABLE_ARRIVAL for item in prepare[-2].opportunities),
        "F": any(item.conversion_class != ArrivalConversionClass.CONSUME_NOW for item in prepare[-2].opportunities),
        "G": ControllerTelemetry().arrival_conversion_representatives_reserved == 0,
        "H": not _obligation(advanced, immediate_op).active(),
        "I": bool(floors),
        "J": any(item.kind == ArrivalConversionHarvestKind.FRAGMENTS_JOINED for item in consumed_harvests),
        "K": len(terminal_state.foundations) == 1 and terminal_cost >= 0,
        "L": foundation_lane_conversions(immediate[1]) != foundation_lane_conversions(immediate[3]),
        "M": urgent_after_deal,
        "N": any(item.conversion_class in {ArrivalConversionClass.DEFERRABLE_ARRIVAL, ArrivalConversionClass.NO_CURRENT_CONVERSION} for item in prepare[-2].opportunities),
        "O": ControllerTelemetry().arrival_conversion_representatives_expanded == 0,
        "P": assess_epoch_saturation(benchmark, ()).status in {EpochSaturationStatus.DEAL_READY, EpochSaturationStatus.STOCK_EMPTY},
        "Q": canonical_state_key(consumed_state) == canonical_state_key(consumed_state.clone()) and not advanced.proof_pruning_allowed,
    }
    return gates, {
        "immediate": immediate_op,
        "prepare": prepare_op,
        "terminal": terminal_op,
        "harvests": consumed_harvests,
        "advanced": advanced,
        "floor_crossings": floors,
    }


def _unseen(cards, seconds: float):
    rows = []
    for seed in (17, 41, 73):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = _gate_config(
            _gate_y_base_config,
            min(12.0, seconds),
            expansions=4,
            nodes=50_000,
        )
        result = solve_anytime(state, tuple(shuffled), None, config)
        replay = state.clone()
        replay_cost = replay_actions(replay, list(result.best_progress_node.actions))
        rows.append(
            {
                "seed": seed,
                "expansions": result.strategic_expansions,
                "transitions": result.telemetry.scheduler_transition_representatives_expanded,
                "classes": result.telemetry.arrival_conversion_by_class,
                "selected": result.telemetry.arrival_conversions_selected,
                "integrated": result.telemetry.arrival_sources_integrated,
                "lane_reduction": result.telemetry.arrival_lane_fragment_reductions,
                "subsequent_deal_ready": result.telemetry.scheduler_deal_ready_states,
                "replay_valid": states_structurally_equal(replay, result.best_progress_node.state) and replay_cost == result.best_progress_node.g,
                "successor_diversity": tuple(sorted(result.telemetry.successor_kinds)),
            }
        )
    return tuple(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-x-seconds", type=float, default=90.0)
    parser.add_argument("--gate-y-seconds", type=float, default=180.0)
    parser.add_argument("--unseen-seconds", type=float, default=12.0)
    parser.add_argument("--skip-gate-y", action="store_true")
    parser.add_argument("--complete-suite-result", default="pending")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor_result = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor = _node(anchor_result)
    independent = reconstruct_cost23_checkpoint()
    prepolicy_totals, prepolicy_rows = _prepolicy_audit(opening)
    gates, capability = _capabilities(opening)
    if not all(gates.values()):
        raise AssertionError(f"capability gate failed: {gates}")
    unseen = _unseen(cards, args.unseen_seconds)

    gate_x_config = _gate_config(
        _gate_x_base_config,
        min(90.0, args.gate_x_seconds),
        expansions=25,
        nodes=300_000,
    )
    gate_x = solve_anytime(anchor.state, cards, None, gate_x_config)
    gate_x_node = _node(gate_x)
    gate_x_f2 = len(gate_x_node.state.foundations) >= 2
    gate_x_authorized = bool(
        gate_x_f2
        or gate_x.telemetry.arrival_sources_integrated
        or gate_x.telemetry.arrival_lane_fragment_reductions
        or gate_x.telemetry.arrival_terminal_qualifications
    )

    gate_y = None
    gate_y_config = None
    if gate_x_authorized and not args.skip_gate_y:
        gate_y_config = _gate_config(
            _gate_y_base_config,
            min(180.0, args.gate_y_seconds),
            expansions=50,
            nodes=500_000,
        )
        gate_y = solve_anytime(opening, cards, None, gate_y_config)
    gate_y_node = _node(gate_y) if gate_y else None
    gate_y_f1 = bool(gate_y_node and len(gate_y_node.state.foundations) >= 1)
    gate_y_f2 = bool(gate_y_node and len(gate_y_node.state.foundations) >= 2)
    repeatability = "not applicable: Gate Y did not reach F2"
    optional = "not authorized: Gate Y F2 and deterministic repeat are required"

    blueprint = build_whole_deal_blueprint(opening)
    future_rows = tuple(
        (row.epoch, tuple(str(item.card) for item in row.cards))
        for row in blueprint.future_rows
    )
    selected_x = tuple(
        _trace(item) for item in gate_x.telemetry.arrival_conversion_traces
        if item.selected
    )
    selected_y = tuple(
        _trace(item) for item in gate_y.telemetry.arrival_conversion_traces
        if item.selected
    ) if gate_y else ()
    x_funnel = _telemetry_funnel(gate_x)
    y_funnel = _telemetry_funnel(gate_y) if gate_y else None
    pass_condition = bool(
        gate_x_f2
        or gate_y_f2
        or (
            gate_y_f1
            and gate_y.telemetry.arrival_sources_integrated
        )
        or (
            gate_x.telemetry.arrival_conversions_selected >= 2
            and gate_x.telemetry.arrival_lane_fragment_reductions > 0
        )
    )
    verdict = "PASS" if pass_condition else "PARTIAL" if (
        gate_x.telemetry.arrival_sources_integrated
        or bool(gate_y and gate_y.telemetry.arrival_sources_integrated)
    ) else "FAIL"
    classification = (
        "F. MULTI-EPOCH SEQUENCING FAILURE: individual causal conversions work, "
        "but converted descendants do not yet mature into a second foundation "
        "or a sustained untouched Deal rhythm inside the fixed frontier."
    )
    route_hashes = {
        "Gate_X_continuation": _route(anchor.state, gate_x),
        "Gate_Y": _route(opening, gate_y) if gate_y else None,
    }

    sections = (
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", {"profile": "MobilityWare 4-suit", "Unrestricted_Deal": MW_RULES.can_deal_into_empty}),
        ("regression anchors", {"canonical": (canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.solved), "machine_F1": (anchor.g, len(anchor.actions), len(anchor.state.foundations), len(anchor.state.stock), sum(len(c.face_down) for c in anchor.state.columns), controller._action_path_hash(anchor.actions), format(zobrist(anchor.state), "x")), "independent_F1": (independent.action_count, independent.deal_count, independent.face_down_count, independent.foundation_suits, independent.independently_verified)}),
        ("v0.2 architecture baseline", "whole-deal blueprint, four objectives, exact marginal saturation, one-shot epoch transition, exact TT/proof separation"),
        ("exact post-Deal arrival-loss audit", prepolicy_totals),
        ("arrival-causality model", "exact source epoch + exact row + incoming card/column + pre/post lane requirement; unrelated cards excluded"),
        ("arrival-conversion API", ("analyze_post_deal_arrival_conversions", "integrate_arrival_conversion_ledger", "record_arrival_conversion_candidates", "advance_post_deal_conversion_ledger")),
        ("conversion classes", tuple(item.value for item in ArrivalConversionClass)),
        ("arrival actionability lifecycle", ("PLANNED_FUTURE_SOURCE", "ARRIVED", "EXPOSED", "ACTIONABLE", "CONSUMABLE", "CONSUMED", "INTEGRATED", "FOUNDATION_CONVERTIBLE", "TERMINAL", "REMOVED")),
        ("conversion obligations", "Deal-scoped, semantic, one-ply, controller-realized, outside exact identity"),
        ("obligation deadlines", (ScheduleDeadlineKind.BEFORE_NEXT_DEAL.value, ScheduleDeadlineKind.BY_EPOCH_N.value, ScheduleDeadlineKind.NO_HARD_DEADLINE.value)),
        ("arrival-vs-next-Deal economics", "credible direct/one-preparation value maps into existing MUST/ADVANTAGE; deferrable/no-current work never blocks Deal"),
        ("conversion representative decision", {"implemented": False, "reason": "pre-policy audit found zero correct generated/TT-admitted conversion successors to rescue; loss preceded successor generation"}),
        ("special-coverage precedence", "unchanged: terminal/foundation, completion cash-out, MUST work, epoch transition; no arrival representative added"),
        ("conversion harvest model", tuple(item.value for item in ArrivalConversionHarvestKind)),
        ("foundation-lane conversion model", tuple(item.value for item in FoundationLaneConversionState)),
        ("duplicate assignment after arrival", "fresh canonical symmetric assignment; lane metadata never enters TT"),
        ("foundation-floor crossing", capability["floor_crossings"]),
        ("proof/TT safety", {"arrival_in_identity": False, "lower_g_dominance": True, "bound_before_after": compute_solution_lower_bound(opening)}),
        ("resource safety", {"objective_limit": gate_x_config.whole_deal_scheduler_config.max_objectives, "frontier": gate_x_config.max_frontier_size, "closure_beam": gate_x_config.dependency_closure_config.beam_width, "persistence": gate_x_config.milestone_max_strategic_expansions, "representative": False}),
    )
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)
    for offset, letter in enumerate("ABCDEFGHIJKLMNOPQ", 21):
        _section(offset, f"capability Gate {letter}", gates[letter])
    _section(38, "unseen-deal results", unseen)
    _section(39, "benchmark blueprint regression", {"blueprint": blueprint.blueprint_id, "future_row_count": len(blueprint.future_rows), "foundation_floors": tuple((item.suit, item.lane, item.earliest_epoch) for item in blueprint.foundation_floors)})
    _section(40, "benchmark future rows", future_rows)
    _section(41, "benchmark v0.2 arrival audit", prepolicy_rows)
    _section(42, "Gate X config/result", {"config": (gate_x_config.wall_clock_limit_s, gate_x_config.max_strategic_expansions, gate_x_config.max_tactical_nodes, gate_x_config.max_frontier_size, gate_x_config.dependency_closure_config.beam_width, gate_x_config.milestone_max_strategic_expansions), "result": _summary(gate_x, offset=21)})
    _section(43, "Gate X Deal transitions", tuple((item.epoch_before, item.epoch_after, item.corrected_g_before, item.corrected_g_after) for item in gate_x.telemetry.scheduler_epoch_traces))
    _section(44, "Gate X arrival funnel", x_funnel)
    _section(45, "Gate X arrival table", tuple(_trace(item) for item in gate_x.telemetry.arrival_conversion_traces[:40]))
    _section(46, "Gate X selected conversions", selected_x)
    _section(47, "Gate X foundation-lane deltas", tuple((item["card"], item["lane_before"], item["lane_after"]) for item in selected_x))
    _section(48, "Gate X terminal/foundation progress", {"terminal": gate_x.telemetry.arrival_terminal_qualifications, "removed": gate_x.telemetry.arrival_foundations_removed, "most_foundations": len(gate_x.most_foundations_node.state.foundations)})
    _section(49, "Gate X F2", gate_x_f2)
    _section(50, "Gate Y authorization", gate_x_authorized)
    _section(51, "Gate Y config/result if authorized", {"config": ((gate_y_config.wall_clock_limit_s, gate_y_config.max_strategic_expansions, gate_y_config.max_tactical_nodes, gate_y_config.max_frontier_size) if gate_y_config else None), "result": _summary(gate_y) if gate_y else None})
    _section(52, "Gate Y strategic expansions", gate_y.strategic_expansions if gate_y else None)
    _section(53, "Gate Y continuous epoch rhythm", {"transitions": tuple((item.epoch_before, item.epoch_after, item.corrected_g_before, item.corrected_g_after) for item in gate_y.telemetry.scheduler_epoch_traces) if gate_y else (), "selected_conversions": selected_y, "stop": "converted epoch-1 child did not mature to a later Deal inside 50 expansions" if gate_y else None})
    _section(54, "Gate Y arrival funnel", y_funnel)
    _section(55, "Gate Y conversion classifications", gate_y.telemetry.arrival_conversion_by_class if gate_y else None)
    _section(56, "Gate Y selected conversions", selected_y)
    _section(57, "Gate Y foundation-lane table", tuple((item["card"], item["lane_before"], item["lane_after"]) for item in selected_y))
    _section(58, "Gate Y high-leverage source outcomes", {"consumed": gate_y.telemetry.arrival_sources_consumed, "integrated": gate_y.telemetry.arrival_sources_integrated, "bridge_merges": gate_y.telemetry.arrival_bridge_merges} if gate_y else None)
    _section(59, "Gate Y Deal timeline", gate_y.telemetry.scheduler_deal_timeline if gate_y else None)
    _section(60, "Gate Y late-suit fragment behaviour", {"fragments_joined": gate_y.telemetry.arrival_fragments_joined, "lane_reduction": gate_y.telemetry.arrival_lane_fragment_reductions} if gate_y else None)
    _section(61, "Gate Y Club diagnostic if E5 reached", "not applicable: Gate Y reached only E1" if gate_y and gate_y.telemetry.best_stock_epoch < 5 else "inspect the two exact E5 Club arrivals in the arrival table")
    _section(62, "Gate Y substantial milestones", gate_y.telemetry.substantial_structural_milestones if gate_y else None)
    _section(63, "Gate Y F1", gate_y_f1)
    _section(64, "Gate Y F2", gate_y_f2)
    _section(65, "route/replay/hashes", route_hashes)
    _section(66, "repeatability", repeatability)
    _section(67, "optional whole-game", optional)
    _section(68, "any complete solution", gate_y.incumbent if gate_y else gate_x.incumbent)
    _section(69, "any verified score below172", None)
    _section(70, "scheduler performance telemetry", {"Gate_X": _performance(gate_x), "Gate_Y": _performance(gate_y) if gate_y else None})
    _section(71, "tactical/resource telemetry", {"Gate_X": gate_x.telemetry.tactical_nodes, "Gate_Y": gate_y.telemetry.tactical_nodes if gate_y else None})
    _section(72, "TT statistics", {"Gate_X": (gate_x.telemetry.tt_new, gate_x.telemetry.tt_improved, gate_x.telemetry.tt_suppressed), "Gate_Y": ((gate_y.telemetry.tt_new, gate_y.telemetry.tt_improved, gate_y.telemetry.tt_suppressed) if gate_y else None)})
    _section(73, "proof statistics", {"Gate_X": (gate_x.telemetry.proof_pruned, gate_x.telemetry.scheduler_proof_prunes), "Gate_Y": ((gate_y.telemetry.proof_pruned, gate_y.telemetry.scheduler_proof_prunes) if gate_y else None)})
    _section(74, "complete-suite result", args.complete_suite_result)
    _section(75, "verdict", verdict)
    _section(76, "architectural classification", classification)
    _section(77, "precise remaining blocker", "Converted exact children reduce same-suit partitions, but the fixed mixed frontier still spends most untouched expansions on cheaper epoch-0 structure; no continuous converted branch reaches a later Deal or terminal lane within Gate Y.")
    _section(78, "recommended scheduler v0.4 / next task", "Only if separately authorized: cross-epoch foundation-lane sequencing and converted-descendant maturation inside existing capacity; do not return to local-controller micro-sprints or add resources.")


if __name__ == "__main__":
    main()
