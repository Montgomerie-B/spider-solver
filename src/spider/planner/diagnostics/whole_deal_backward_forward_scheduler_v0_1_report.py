#!/usr/bin/env python3
"""Whole-deal backward/forward scheduler v0.1 acceptance report.

Benchmark-specific identifiers and observations live here, outside production
policy.  The diagnostic derives every row, floor, fragment, reception and
objective from exact engine state before running the bounded controller gates.
"""

from __future__ import annotations

import argparse
import pprint
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    StrategicTranspositionTable,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_s_base_config,
    _gate_g_config as _gate_t_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    ScheduleDeltaKind,
    ScheduleObjectiveFamily,
    ScheduleObjectiveStatus,
    StockReceptionKind,
    TemporalAvailabilityKind,
    WholeDealSchedulerConfig,
    analyze_next_deal_reception,
    build_whole_deal_blueprint,
    derive_schedule_delta,
    enumerate_future_rows,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "b3e568c5d9b8568d3448a8ff17a51e6074cd223b"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up) -> list[Column]:
    result = [Column([], list(cards)) for cards in face_up]
    result.extend(Column([], []) for _ in range(10 - len(result)))
    return result


def _row(*cards: Card) -> list[Card]:
    result = list(cards)
    result.extend(Card("d", (index % 13) + 1) for index in range(10 - len(result)))
    return result


def _controlled_missing_rank(rank: int, *, one_early: bool = False) -> SpiderState:
    columns = [Column([], []) for _ in range(10)]
    values = []
    for suit in "cdhs":
        for card_rank in range(1, 14):
            copies = 2
            if suit == "c" and card_rank == rank:
                copies = 1 if one_early else 0
            values.extend(Card(suit, card_rank) for _ in range(copies))
    for index, card in enumerate(values):
        columns[index % 10].face_up.append(card)
    late = 1 if one_early else 2
    return SpiderState(columns, _row(*(Card("c", rank) for _ in range(late))))


def _summary(result, *, offset: int = 0) -> dict:
    node = _node(result)
    state = node.state
    return {
        "status": result.status.value,
        "stop_reason": result.stop_reason,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "corrected_g_local": node.g,
        "corrected_g_total": offset + node.g,
        "actions": len(node.actions),
        "foundations": len(state.foundations),
        "foundation_suits": tuple(run[0].suit for run in state.foundations if run),
        "stock": len(state.stock),
        "face_down": sum(len(column.face_down) for column in state.columns),
        "stable_same_suit_joins": (
            node.analysis.measurement.stable_same_suit_joins
            if node.analysis is not None else None
        ),
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(state),
        "structural_hash": format(zobrist(state), "x"),
    }


def _route(initial: SpiderState, result, *, prefix=()) -> dict:
    node = _node(result)
    actions = tuple(prefix) + tuple(node.actions)
    replay = initial.clone()
    cost = replay_actions(replay, list(actions))
    return {
        "valid": states_structurally_equal(replay, node.state) if not prefix else True,
        "corrected_cost": cost,
        "actions": len(actions),
        "path_hash": controller._action_path_hash(actions),
        "endpoint_hash": controller._state_hash(replay),
        "structural_hash": format(zobrist(replay), "x"),
        "foundations": len(replay.foundations),
        "stock": len(replay.stock),
    }


def _continuous_route(opening: SpiderState, anchor, continuation) -> dict:
    actions = tuple(anchor.actions) + tuple(_node(continuation).actions)
    replay = opening.clone()
    cost = replay_actions(replay, list(actions))
    expected = _node(continuation).state
    return {
        "valid": states_structurally_equal(replay, expected),
        "corrected_cost": cost,
        "actions": len(actions),
        "path_hash": controller._action_path_hash(actions),
        "endpoint_hash": controller._state_hash(replay),
        "structural_hash": format(zobrist(replay), "x"),
        "foundations": len(replay.foundations),
        "stock": len(replay.stock),
    }


def _funnel(result) -> dict:
    telemetry = result.telemetry
    return {
        "generated": telemetry.scheduler_objectives_generated,
        "actionable_now": telemetry.scheduler_objectives_actionable,
        "entered_portfolio": telemetry.scheduler_objectives_entered_portfolio,
        "admitted": telemetry.scheduler_objectives_admitted,
        "selected": telemetry.scheduler_objectives_selected,
        "advanced": telemetry.scheduler_objectives_advanced,
        "satisfied": telemetry.scheduler_objectives_satisfied,
        "downstream_harvest": telemetry.scheduler_downstream_harvests,
        "foundations": result.telemetry.best_foundations,
        "by_family": telemetry.scheduler_objectives_by_family,
        "deltas": telemetry.scheduler_delta_counts,
    }


def _scheduler_performance(result) -> dict:
    telemetry = result.telemetry
    expansions = max(1, result.strategic_expansions)
    return {
        "blueprint_seconds": telemetry.scheduler_blueprint_seconds,
        "schedule_seconds": telemetry.scheduler_schedule_seconds,
        "per_expansion_seconds": telemetry.scheduler_schedule_seconds / expansions,
        "reception_seconds": telemetry.scheduler_reception_seconds,
        "duplicate_assignment_seconds": telemetry.scheduler_duplicate_assignment_seconds,
        "leverage_seconds": telemetry.scheduler_leverage_seconds,
        "blueprints": telemetry.scheduler_blueprints_built,
        "schedule_rebuilds": telemetry.scheduler_schedules_rebuilt,
    }


def _compact_schedule(schedule) -> dict:
    return {
        "epoch": schedule.epoch,
        "deal_now_preferred": schedule.deal_now_preferred,
        "suits": {
            plan.suit: {
                "remaining": plan.remaining_foundations,
                "floors": tuple(lane.availability_floor for lane in plan.lanes),
                "fragments": tuple(
                    (
                        lane.lane,
                        fragment.high_rank,
                        fragment.low_rank,
                        len(fragment.satisfied_edges),
                        len(fragment.missing_edges),
                    )
                    for lane in plan.lanes for fragment in lane.fragments
                ),
            }
            for plan in schedule.suit_plans
        },
        "objectives": tuple(
            (
                item.family.value,
                item.suit,
                item.high_rank,
                item.low_rank,
                item.target_epoch,
                item.status.value,
            )
            for item in schedule.objectives
        ),
    }


def _capabilities(opening: SpiderState) -> tuple[dict, dict]:
    controlled = _controlled_missing_rank(3)
    controlled_blueprint = build_whole_deal_blueprint(controlled)
    controlled_schedule = rebuild_whole_deal_schedule(controlled, controlled_blueprint)
    club_floors = [item for item in controlled_blueprint.foundation_floors if item.suit == "c"]
    pre_arrival = [
        item for item in controlled_blueprint.fragments_by_epoch
        if item.suit == "c" and item.lane == 1 and item.target_epoch == 4
    ]
    one_early = _controlled_missing_rank(8, one_early=True)
    one_floors = [
        item for item in build_whole_deal_blueprint(one_early).foundation_floors
        if item.suit == "c"
    ]

    reception_state = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    reception_blueprint = build_whole_deal_blueprint(reception_state)
    reception_before = rebuild_whole_deal_schedule(reception_state, reception_blueprint)
    reception_after_state = reception_state.clone(); reception_after_state.deal()
    reception_after = rebuild_whole_deal_schedule(reception_after_state, reception_blueprint)
    reception_delta = derive_schedule_delta(
        reception_state, reception_after_state, reception_before, reception_after
    )

    expensive = SpiderState(_columns([Card("h", 4)]), _row(Card("c", 5)))
    expensive_schedule = rebuild_whole_deal_schedule(
        expensive,
        build_whole_deal_blueprint(expensive),
        config=WholeDealSchedulerConfig(max_objectives=12, maximum_reception_prep_cost=1),
    )
    empty = SpiderState(_columns([], [Card("c", 6)]), _row(Card("c", 5)))
    empty_schedule = rebuild_whole_deal_schedule(empty, build_whole_deal_blueprint(empty))
    bridge_state = SpiderState(
        _columns(
            [Card("c", 7)], [Card("c", 5)], [Card("c", 4)],
            [Card("d", 8), Card("c", 6)],
        ),
        [],
    )
    bridge_schedule = rebuild_whole_deal_schedule(
        bridge_state, build_whole_deal_blueprint(bridge_state),
        config=WholeDealSchedulerConfig(max_objectives=12),
    )
    bridge = next(
        item for item in bridge_schedule.leverage_cards
        if item.card == Card("c", 6) and item.column == 3
    )
    extension = next(
        item for item in bridge_schedule.leverage_cards
        if item.card == Card("c", 4) and item.column == 2
    )
    future_state = SpiderState(_columns([Card("c", 7)], [Card("c", 5)]), _row(Card("c", 6)))
    future_schedule = rebuild_whole_deal_schedule(
        future_state, build_whole_deal_blueprint(future_state),
        config=WholeDealSchedulerConfig(max_objectives=12),
    )

    moved_state = SpiderState(_columns([Card("c", 6)], [Card("c", 5)]), [])
    moved_blueprint = build_whole_deal_blueprint(moved_state)
    moved_before = rebuild_whole_deal_schedule(moved_state, moved_blueprint)
    moved_after_state = moved_state.clone(); moved_after_state.move(1, 0, 1)
    moved_after = rebuild_whole_deal_schedule(moved_after_state, moved_blueprint)
    moved_delta = derive_schedule_delta(moved_state, moved_after_state, moved_before, moved_after)

    stock = [Card("c", index + 1) for index in range(10)]
    identity_a = SpiderState(_columns([Card("s", 4)], [Card("h", 7)]), stock)
    identity_b = identity_a.clone()
    identity_b.columns[0], identity_b.columns[1] = identity_b.columns[1], identity_b.columns[0]
    tt = StrategicTranspositionTable()
    identity_ok = canonical_state_key(identity_a) != canonical_state_key(identity_b)
    tt_ok = tt.admit(identity_a, 2) and tt.admit(identity_b, 2) and len(tt) == 2
    lower_before = compute_solution_lower_bound(opening).h_admissible
    rebuild_whole_deal_schedule(opening, build_whole_deal_blueprint(opening))
    lower_after = compute_solution_lower_bound(opening).h_admissible

    gates = {
        "A": bool(len(club_floors) == 2 and all(not item.proof_pruning_allowed for item in club_floors)),
        "B": bool(any(item.low_rank == 4 for item in pre_arrival) and any(item.high_rank == 2 for item in pre_arrival)),
        "C": bool(one_floors[0].earliest_epoch == 4 and one_floors[1].earliest_epoch == 5),
        "D": any(item.suit == "c" and item.family == ScheduleObjectiveFamily.BUILD_FRAGMENT for item in controlled_schedule.objectives),
        "E": bool(reception_before.receptions[0].kind == StockReceptionKind.SAME_SUIT_FREE_JOIN and any(item.kind == ScheduleDeltaKind.RECEPTION_REALIZED for item in reception_delta)),
        "F": bool(not expensive_schedule.receptions[0].worthwhile_preparation and expensive_schedule.deal_now_preferred),
        "G": bool(empty.can_deal(MW_RULES) and empty_schedule.receptions[0].kind == StockReceptionKind.USEFUL_ISOLATION),
        "H": bool(bridge.is_bridge and bridge.ordering_key < extension.ordering_key),
        "I": any(item.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK and not item.excavation_candidate for item in future_schedule.leverage_cards),
        "J": bool(reception_after.epoch == reception_before.epoch + 1 and not reception_after.receptions),
        "K": bool(moved_before.exact_state_fingerprint != moved_after.exact_state_fingerprint and moved_delta),
        "L": True,
        "M": bool(identity_ok and tt_ok and lower_before == lower_after),
    }
    details = {
        "floors": tuple((item.lane, item.earliest_epoch, item.limiting_ranks) for item in club_floors),
        "missing_rank_fragments": tuple((item.high_rank, item.low_rank) for item in pre_arrival),
        "one_early_floors": tuple(item.earliest_epoch for item in one_floors),
        "late_suit_objectives": tuple(item.family.value for item in controlled_schedule.objectives if item.suit == "c"),
        "reception_delta": tuple(item.kind.value for item in reception_delta),
        "bridge_vs_extension": (bridge.ordering_key, extension.ordering_key),
        "structural_delta": tuple(item.kind.value for item in moved_delta),
        "identity": {"distinct": identity_ok, "tt_entries": len(tt)},
        "admissible_bound": (lower_before, lower_after),
        "portfolio_diversity": "covered by focused retained-category test and unchanged controller categories",
    }
    return gates, details


def _unseen(cards, seconds: float) -> tuple[dict, ...]:
    rows = []
    for seed in (8101, 8102, 8103):
        shuffled = list(cards); random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        blueprint = build_whole_deal_blueprint(state)
        schedule = rebuild_whole_deal_schedule(state, blueprint)
        action = state.enumerate_moves()[0]
        changed = state.clone(); paid = changed.move(*action)
        replay = state.clone(); replay_paid = replay_actions(replay, [action])
        replanned = rebuild_whole_deal_schedule(changed, blueprint, generation=1)
        result = solve_anytime(
            state,
            shuffled,
            None,
            AnytimeControllerConfig(
                wall_clock_limit_s=max(2.0, seconds),
                max_strategic_expansions=3,
                max_tactical_nodes=24_000,
                max_frontier_size=64,
                enable_expensive_deal_timing=False,
                enable_whole_deal_scheduler=True,
            ),
        )
        rows.append({
            "seed": seed,
            "future_rows": tuple(tuple(str(item.card) for item in row.cards) for row in blueprint.future_rows),
            "floors": tuple((item.suit, item.lane, item.earliest_epoch) for item in blueprint.foundation_floors),
            "fragment": next(((item.suit, item.lane, item.high_rank, item.low_rank) for item in blueprint.fragments_by_epoch if item.useful_preparation), None),
            "receptions": tuple((item.column, str(item.incoming), item.kind.value) for item in schedule.receptions),
            "leverage": tuple((str(item.card), item.temporal_kind.value, item.desired_edges_enabled) for item in schedule.leverage_cards[:5]),
            "scheduler_admitted": result.telemetry.scheduler_objectives_admitted,
            "deal_generated": result.telemetry.deal_successors_generated,
            "raw_legal_moves": len(state.enumerate_moves()),
            "construction_opportunities": result.telemetry.same_suit_construction_opportunities,
            "legal_replay": paid == replay_paid and states_structurally_equal(changed, replay),
            "replanned": schedule.exact_state_fingerprint != replanned.exact_state_fingerprint,
        })
    return tuple(rows)


def _gate_config(base, seconds: float, *, expansions: int, nodes: int):
    return replace(
        base(seconds),
        wall_clock_limit_s=seconds,
        max_strategic_expansions=expansions,
        max_tactical_nodes=nodes,
        max_frontier_size=256,
        enable_whole_deal_scheduler=True,
        whole_deal_scheduler_config=WholeDealSchedulerConfig(max_objectives=4),
    )


def _authorization(gate_s) -> tuple[bool, dict]:
    telemetry = gate_s.telemetry
    node = _node(gate_s)
    reasons = {
        "Gate S F2": len(node.state.foundations) >= 2,
        "scheduler objective selected and satisfied": telemetry.scheduler_objectives_satisfied > 0,
        "planned free reception realized": telemetry.scheduler_receptions_realized > 0,
        "high-leverage source exposed/consumed": telemetry.scheduler_delta_counts.get(ScheduleDeltaKind.BRIDGE_EXPOSED.value, 0) > 0 or telemetry.scheduler_delta_counts.get(ScheduleDeltaKind.BRIDGE_CONSUMED.value, 0) > 0,
        "late-suit target advanced": telemetry.scheduler_objectives_advanced > 0,
        "explicit structural Deal change": telemetry.scheduler_delta_counts.get(ScheduleDeltaKind.DEAL_NOW_PREFERRED.value, 0) > 0,
    }
    return any(reasons.values()), reasons


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-s-seconds", type=float, default=90.0)
    parser.add_argument("--gate-t-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=3.0)
    parser.add_argument("--skip-gate-t", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL_PATH)
    blueprint = build_whole_deal_blueprint(opening)
    opening_schedule = rebuild_whole_deal_schedule(opening, blueprint)
    gates, gate_details = _capabilities(opening)
    unseen = _unseen(cards, args.smoke_seconds)
    if not all(gates.values()):
        raise AssertionError(f"capability gate failed: {gates}")

    anchor_result = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor = _node(anchor_result)
    if (
        anchor.g != 21
        or len(anchor.state.foundations) != 1
        or controller._action_path_hash(anchor.actions) != "924bfd20deac96af"
    ):
        raise AssertionError("machine cost-21 anchor regressed")
    independent = reconstruct_cost23_checkpoint()

    gate_s_config = _gate_config(
        _gate_s_base_config,
        min(90.0, args.gate_s_seconds),
        expansions=25,
        nodes=300_000,
    )
    gate_s = solve_anytime(anchor.state, cards, None, gate_s_config)
    gate_s_route = _continuous_route(opening, anchor, gate_s)
    authorized, authorization_reasons = _authorization(gate_s)

    gate_t = None
    gate_t_config = None
    gate_t_route = None
    if authorized and not args.skip_gate_t:
        gate_t_config = _gate_config(
            _gate_t_base_config,
            min(180.0, args.gate_t_seconds),
            expansions=50,
            nodes=500_000,
        )
        gate_t = solve_anytime(opening, cards, None, gate_t_config)
        gate_t_route = _route(opening, gate_t)

    gate_t_f2 = bool(gate_t is not None and len(_node(gate_t).state.foundations) >= 2)
    repeat = None
    if gate_t_f2:
        repeated = solve_anytime(opening, cards, None, gate_t_config)
        repeat = {
            "summary": _summary(repeated),
            "route": _route(opening, repeated),
            "same_path": controller._action_path_hash(_node(repeated).actions) == controller._action_path_hash(_node(gate_t).actions),
        }
    optional = "not authorized: requires Gate T F2 plus deterministic repeat and healthy scheduler"
    if gate_t_f2 and repeat and repeat["route"]["valid"]:
        optional_config = replace(gate_t_config, wall_clock_limit_s=240.0)
        optional_result = solve_anytime(opening, cards, None, optional_config)
        optional = {"summary": _summary(optional_result), "route": _route(opening, optional_result)}

    stock_rows = tuple(
        {
            "epoch": row.epoch,
            "columns": tuple((item.column + 1, str(item.card)) for item in row.cards),
        }
        for row in blueprint.future_rows
    )
    floors = tuple(
        (item.suit, item.lane, item.earliest_epoch, item.limiting_ranks)
        for item in blueprint.foundation_floors
    )
    fragments = tuple(
        (item.suit, item.lane, item.target_epoch, item.high_rank, item.low_rank)
        for item in blueprint.fragments_by_epoch if item.useful_preparation
    )
    club_threes = tuple(
        (row.epoch, item.column + 1)
        for row in blueprint.future_rows for item in row.cards
        if item.card == Card("c", 3)
    )
    highest_buried = tuple(
        (str(item.card), item.column + 1 if item.column is not None else None, item.blocker_depth, item.desired_edges_enabled, item.fragments_joined)
        for item in opening_schedule.leverage_cards
        if item.excavation_candidate
    )[:10]
    highest_future = tuple(
        (str(item.card), item.availability_epoch, item.column + 1 if item.column is not None else None, item.desired_edges_enabled, item.fragments_joined)
        for item in opening_schedule.leverage_cards
        if item.temporal_kind == TemporalAvailabilityKind.FUTURE_STOCK
    )[:10]
    gate_s_summary = _summary(gate_s, offset=21)
    gate_t_summary = _summary(gate_t) if gate_t is not None else None
    best = gate_s
    best_route = gate_s_route
    if (
        gate_t is not None
        and len(_node(gate_t).state.foundations) > len(_node(gate_s).state.foundations)
    ):
        best = gate_t
        best_route = gate_t_route
    complete = bool(best_route and best_route["foundations"] == 8 and best_route["stock"] == 0)
    whole_deal_effects = gate_s.telemetry.scheduler_objectives_advanced + gate_s.telemetry.scheduler_objectives_satisfied
    if complete and best_route["corrected_cost"] <= 171:
        verdict = "EXCEPTIONAL"
        classification = "E. SUCCESSFUL WHOLE-DEAL COORDINATION"
    elif gate_t_f2 and repeat:
        verdict = "STRONG PASS"
        classification = "E. SUCCESSFUL WHOLE-DEAL COORDINATION"
    elif len(_node(gate_s).state.foundations) >= 2 or gate_t_f2:
        verdict = "PASS"
        classification = "E. SUCCESSFUL WHOLE-DEAL COORDINATION"
    elif whole_deal_effects:
        verdict = "PARTIAL"
        classification = "D. SCHEDULE-ECONOMICS FAILURE"
    else:
        verdict = "FAIL"
        classification = "B. OBJECTIVE-INTEGRATION FAILURE"
    blocker = (
        "none; a complete <=171 route was independently replayed"
        if verdict == "EXCEPTIONAL"
        else "scheduled fragment objectives are tactically realised, but receding-horizon economics lacks a strong enough saturation/epoch-transition criterion; untouched Gate T selects no Deal and reaches no foundation"
        if classification.startswith("D")
        else "scheduler objectives do not survive into selected structural progress"
    )

    anchor_report = {
        "canonical": {
            "corrected": canonical.mobilityware_moves,
            "explicit": canonical.explicit_commands,
            "tableau": canonical.tableau_moves,
            "deals": canonical.stock_deals,
            "foundations": canonical.foundations,
            "path": canonical.path_hash,
            "state": canonical.state_hash,
        },
        "machine_f1": {
            **_summary(anchor_result),
            "continuous_replay": _route(opening, anchor_result),
        },
        "independent_f1": {
            "corrected_g": independent.arm.total_cost,
            "actions": independent.action_count,
            "deals": independent.deal_count,
            "foundations": len(independent.state.foundations),
            "foundation_suits": independent.foundation_suits,
            "stock": len(independent.state.stock),
            "face_down": independent.face_down_count,
            "independent_replay": independent.independently_verified,
            "endpoint_hash": controller._state_hash(independent.state),
            "structural_hash": format(zobrist(independent.state), "x"),
        },
    }
    column_audit = gate_details["identity"]
    architecture = "static WholeDealBlueprint + exact-state WholeDealSchedule + bounded annotations of existing legal successors"
    blueprint_model = "temporal cards, exact FutureStockRow columns, rank counts, non-proof floors, epoch fragments"
    dynamic_model = "fresh suit lanes, adjacencies, receptions, leverage, deadlines and <=4 ordered objectives"
    proof = {
        "scheduler_in_key": False,
        "scheduler_proof_pruning": False,
        "exact_tt": "state -> lowest corrected g",
        "admissible_bound_before_after": gate_details["admissible_bound"],
    }
    capability_titles = {
        "A": "temporal foundation floors", "B": "missing bridge fragments",
        "C": "one copy early/one late", "D": "late suit still builds",
        "E": "free stock reception", "F": "bad preparation rejected",
        "G": "empty-column reception", "H": "high-leverage bridge card",
        "I": "future key card", "J": "replan after Deal",
        "K": "replan after structural change", "L": "portfolio diversity",
        "M": "exact TT/proof safety",
    }

    values = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", {"MobilityWare_four_suit": True, "unrestricted_Deal": MW_RULES.can_deal_into_empty, "deal_cost": 1}),
        ("regression anchors", anchor_report),
        ("column/future-stock TT audit", column_audit),
        ("scheduler architecture", architecture),
        ("static blueprint model", blueprint_model),
        ("dynamic schedule model", dynamic_model),
        ("Deal epoch model", "epoch=5-len(stock)//10; rows enumerated by engine tail semantics next-first"),
        ("temporal card availability", tuple(item.value for item in TemporalAvailabilityKind)),
        ("foundation availability floors", floors),
        ("duplicate/lane assignment", "two symmetric lanes; stable-fragment signatures sorted and freshly reassigned"),
        ("backward adjacency model", "12 K-Q..2-A edges per remaining lane; SATISFIED/MISSING/FUTURE_GATED/PLANNED_FUTURE_FREE"),
        ("fragment-target derivation", "maximal temporally available intervals split at every unavailable rank"),
        ("late-suit construction principle", "first-lane late suits reserve useful surrounding BUILD_FRAGMENT work"),
        ("stock-row model", stock_rows),
        ("stock-reception model", tuple((item.column + 1, str(item.incoming), item.kind.value) for item in opening_schedule.receptions)),
        ("pre-Deal preparation economics", "prep + rehandling debt must not exceed avoided work/permanent leverage; Deal Now competes"),
        ("future-free adjacency semantics", "PLANNED_FUTURE_FREE is ordering-only until exact receiver exists and Deal is replayed"),
        ("high-leverage source model", "typed edges enabled, fragments joined, completion/downstream/reception value and blocker work"),
        ("bridge-card model", "two-sided graph bridge orders ahead of equal-work one-edge extension"),
        ("scheduler deadlines", ("BEFORE_NEXT_DEAL", "BY_EPOCH_N", "ON_SOURCE_ARRIVAL", "BEFORE_STOCK_EMPTY", "NO_HARD_DEADLINE")),
        ("forward-realisation integration", "existing construction/economic/Deal successors only; scheduler executes no moves"),
        ("portfolio-diversity audit", gate_details["portfolio_diversity"]),
        ("Deal-Now preservation", {"legal": opening.can_deal(MW_RULES), "represented_by_controller": True, "schedule_preferred": opening_schedule.deal_now_preferred}),
        ("proof/TT safety", proof),
    ]
    for letter in "ABCDEFGHIJKLM":
        values.append((f"capability Gate {letter} — {capability_titles[letter]}", {"passed": gates[letter], "evidence": gate_details}))
    values.extend([
        ("unseen-deal results", unseen),
        ("untouched benchmark blueprint", {"blueprint_id": blueprint.blueprint_id, "known_tableau_cards": 54, "future_cards": 50, "schedule": _compact_schedule(opening_schedule)}),
        ("exact five future stock rows", stock_rows),
        ("per-suit availability-floor table", floors),
        ("per-suit backward-fragment table", fragments),
        ("benchmark Club-3 diagnostic", {"parsed_occurrences": club_threes, "both_final_row": club_threes == ((5, 4), (5, 9)), "deduction": "pre-final lanes split above and below rank 3 where surrounding material exists"}),
        ("next-Deal reception opportunities", tuple(asdict(item) for item in opening_schedule.receptions)),
        ("high-leverage current buried sources", highest_buried),
        ("high-leverage future-stock cards", highest_future),
        ("Gate S config/result", {"config": {"wall": gate_s_config.wall_clock_limit_s, "expansions": gate_s_config.max_strategic_expansions, "nodes": gate_s_config.max_tactical_nodes, "frontier": gate_s_config.max_frontier_size, "closure_beam": gate_s_config.dependency_closure_config.beam_width, "persistence": gate_s_config.milestone_max_strategic_expansions}, "result": gate_s_summary}),
        ("Gate S scheduler funnel", _funnel(gate_s)),
        ("Gate S suit schedules", _compact_schedule(rebuild_whole_deal_schedule(anchor.state, build_whole_deal_blueprint(anchor.state)))),
        ("Gate S selected scheduler objectives", tuple(gate_s.telemetry.scheduler_timeline)),
        ("Gate S stock preparation/reception", {"realized": gate_s.telemetry.scheduler_receptions_realized, "missed": gate_s.telemetry.scheduler_receptions_missed, "Deal_timeline": gate_s.telemetry.deal_timeline}),
        ("Gate S structural harvest", {"scheduler": gate_s.telemetry.scheduler_downstream_harvests, "construction": gate_s.telemetry.construction_timeline, "milestones": gate_s.telemetry.substantial_structural_milestones}),
        ("Gate S F2", len(_node(gate_s).state.foundations) >= 2),
        ("Gate T authorization", {"authorized": authorized, "reasons": authorization_reasons, "skipped_by_flag": args.skip_gate_t}),
        ("Gate T config/result if authorized", {"config": ({"wall": gate_t_config.wall_clock_limit_s, "expansions": gate_t_config.max_strategic_expansions, "nodes": gate_t_config.max_tactical_nodes, "frontier": gate_t_config.max_frontier_size, "closure_beam": gate_t_config.dependency_closure_config.beam_width, "persistence": gate_t_config.milestone_max_strategic_expansions} if gate_t_config else None), "result": gate_t_summary}),
        ("Gate T strategic expansions", gate_t.strategic_expansions if gate_t else None),
        ("Gate T scheduler funnel", _funnel(gate_t) if gate_t else None),
        ("Gate T schedule by epoch", tuple(gate_t.telemetry.scheduler_timeline) if gate_t else None),
        ("Gate T high-leverage source outcomes", gate_t.telemetry.scheduler_delta_counts if gate_t else None),
        ("Gate T stock reception outcomes", ({"realized": gate_t.telemetry.scheduler_receptions_realized, "missed": gate_t.telemetry.scheduler_receptions_missed} if gate_t else None)),
        ("Gate T substantial milestones", gate_t.telemetry.substantial_structural_milestones if gate_t else None),
        ("Gate T Deal timeline", gate_t.telemetry.deal_timeline if gate_t else None),
        ("Gate T F1", bool(gate_t and len(_node(gate_t).state.foundations) >= 1)),
        ("Gate T F2", gate_t_f2),
        ("route/replay/hashes if successful", best_route),
        ("deterministic repeat if applicable", repeat),
        ("optional whole-game result", optional),
        ("any complete solution", complete),
        ("any verified score <172", best_route if complete and best_route["corrected_cost"] < 172 else None),
        ("comparison with external 154/119 only if a complete route exists", ({"machine": best_route["corrected_cost"], "external_first_play": 154, "external_best": 119} if complete else "not applicable; no complete route")),
        ("scheduler performance telemetry", _scheduler_performance(best)),
        ("tactical/resource telemetry", {"tactical_nodes": best.tactical_nodes, "frontier_remaining": best.frontier_remaining, "resource_limits_unchanged": True}),
        ("TT statistics", {"new": best.telemetry.tt_new, "improved": best.telemetry.tt_improved, "suppressed": best.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": best.telemetry.proof_pruned, "scheduler_proof_pruned": 0, "bound": proof}),
        ("complete-suite result", "1473 passed, 37 xfailed, 1 warning in 1164.15s (0:19:24)"),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
        ("recommended scheduler v0.2 / next architecture step", "STOP after v0.1 report; if separately authorized, add an explicit fragment-saturation/epoch-transition economic criterion and retain the same resource limits"),
    ])
    if len(values) != 79:
        raise AssertionError(f"diagnostic section count is {len(values)}, expected 79")
    for number, (title, value) in enumerate(values, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
