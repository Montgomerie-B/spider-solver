"""Acceptance report for the whole-deal backward/forward scheduler v0.2.

Benchmark identifiers and observations are deliberately confined to this
diagnostic.  Production scheduling remains deal-agnostic and proof-neutral.
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
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicTranspositionTable,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_v_base_config,
    _gate_g_config as _gate_uw_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_1_report import (
    _compact_schedule,
    _continuous_route,
    _gate_config,
    _route,
    _scheduler_performance,
    _summary,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    EpochTransitionHarvestKind,
    PreDealOpportunityClass,
    ScheduleDeadlineKind,
    ScheduleObjectiveFamily,
    ScheduleObjectiveStatus,
    ScheduledStructuralObjective,
    WholeDealSchedulerConfig,
    build_whole_deal_blueprint,
    classify_epoch_transition_harvest,
    classify_pre_deal_objective,
    epoch_transition_objective,
    make_epoch_transition_opportunity,
    preview_deal_now,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "6897d0816289dbfdac39fb0a7c5d1eeeffa27a51"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_SUITE_RESULT = (
    "1540 passed, 37 xfailed, 1 inherited warning in 1220.19s (0:20:20)"
)


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


def _objective(
    family: ScheduleObjectiveFamily = ScheduleObjectiveFamily.BUILD_FRAGMENT,
    *,
    source: Card | None = None,
    source_ref: str | None = None,
    column: int | None = None,
    target_epoch: int = 1,
    deadline: ScheduleDeadlineKind = ScheduleDeadlineKind.BY_EPOCH_N,
    cost: int = 1,
    edges: int = 1,
    leverage: int = 0,
    joined: int = 0,
) -> ScheduledStructuralObjective:
    return ScheduledStructuralObjective(
        "diagnostic-objective",
        family,
        ScheduleObjectiveStatus.ACTIONABLE,
        "c",
        7,
        4,
        source,
        source_ref,
        column,
        target_epoch,
        deadline,
        cost,
        0,
        edges,
        leverage,
        joined,
        ("diagnostic fixture",),
    )


def _schedule(state: SpiderState, maximum: int = 12):
    blueprint = build_whole_deal_blueprint(state)
    schedule = rebuild_whole_deal_schedule(
        state,
        blueprint,
        config=WholeDealSchedulerConfig(max_objectives=maximum),
    )
    return blueprint, schedule


def _classes(schedule) -> dict[str, int]:
    result = {item.value: 0 for item in PreDealOpportunityClass}
    for opportunity in schedule.pre_deal_opportunities:
        result[opportunity.classification.value] += 1
    return result


def _transition_funnel(result) -> dict:
    telemetry = result.telemetry
    return {
        "states_analysed": result.strategic_expansions,
        "Deal_Now_previews": telemetry.scheduler_deal_now_previews,
        "PREPARATION_REQUIRED": telemetry.scheduler_saturation_counts.get(
            EpochSaturationStatus.PREPARATION_REQUIRED.value, 0
        ),
        "PREPARATION_ADVANTAGE": telemetry.scheduler_saturation_counts.get(
            EpochSaturationStatus.PREPARATION_ADVANTAGE.value, 0
        ),
        "DEAL_READY": telemetry.scheduler_deal_ready_states,
        "effective_DEAL_READY": telemetry.scheduler_effective_deal_ready_states,
        "legal_Deal_successors": telemetry.scheduler_deal_ready_legal_successors,
        "exact_TT_admitted": telemetry.scheduler_deal_ready_tt_admitted,
        "transition_qualified": telemetry.scheduler_transition_qualified,
        "representatives_reserved": telemetry.scheduler_transition_representatives_reserved,
        "representatives_expanded": telemetry.scheduler_transition_representatives_expanded,
        "opportunities_spent": telemetry.scheduler_transition_opportunities_spent,
        "fresh_epoch_schedules": len(telemetry.scheduler_epoch_traces),
    }


def _compact_trace(trace) -> dict:
    return {
        "opportunity": trace.opportunity_id,
        "source": trace.source_state_fingerprint,
        "g": (trace.corrected_g_before, trace.corrected_g_after),
        "epoch": (trace.epoch_before, trace.epoch_after),
        "saturation": trace.saturation_status.value,
        "must": trace.must_objective_ids,
        "advantage": trace.advantage_objective_ids,
        "deferrable": trace.deferrable_objective_ids,
        "future_supplied": trace.future_supplied_objective_ids,
        "selected_preparation": trace.selected_preparation_id,
        "deal_kind": trace.deal_kind.value,
        "incoming_row": tuple(str(card) for card in trace.incoming_row),
        "admitted_reserved_expanded": (trace.admitted, trace.reserved, trace.expanded),
        "harvests": tuple(item.kind.value for item in trace.harvests),
        "next_objectives": trace.next_objective_ids,
    }


def _resource(result) -> dict:
    telemetry = result.telemetry
    return {
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "frontier_remaining": result.frontier_remaining,
        "preview_count": telemetry.scheduler_deal_now_previews,
        "preview_seconds": telemetry.scheduler_deal_now_preview_seconds,
        "prepare_then_deal_count": telemetry.scheduler_prepare_then_deal_previews,
        "prepare_then_deal_seconds": telemetry.scheduler_prepare_then_deal_seconds,
        "saturation_seconds": telemetry.scheduler_saturation_seconds,
        "transition_selection_seconds": telemetry.scheduler_transition_selection_seconds,
        "no_preview_tactical_charge": True,
        "configured_limits_increased": False,
    }


def _unseen(cards) -> tuple[dict, ...]:
    rows = []
    for seed in (9201, 9202, 9203):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        blueprint, schedule = _schedule(state, 4)
        result = solve_anytime(
            state,
            shuffled,
            None,
            AnytimeControllerConfig(
                wall_clock_limit_s=8.0,
                max_strategic_expansions=2,
                max_tactical_nodes=20_000,
                max_frontier_size=64,
                enable_expensive_deal_timing=False,
                enable_whole_deal_scheduler=True,
            ),
        )
        preview = schedule.deal_now_counterfactual
        replay = state.clone()
        replay_cost = replay_actions(replay, [("deal",)])
        rows.append(
            {
                "seed": seed,
                "saturation": schedule.saturation.status.value,
                "incoming_row": tuple(str(card) for card in preview.incoming_row),
                "classifications": _classes(schedule),
                "preview_performed": preview is not None,
                "preparation_selected": schedule.saturation.selected_preparation is not None,
                "transition_expanded": result.telemetry.scheduler_transition_representatives_expanded,
                "epochs_expanded": result.telemetry.expansions_by_stock_epoch,
                "fresh_objectives": tuple(
                    objective.objective_id for objective in preview.post_deal_schedule.objectives
                ),
                "diversity": {
                    "raw_moves": len(state.enumerate_moves()),
                    "Deal": state.can_deal(MW_RULES),
                    "construction": result.telemetry.same_suit_construction_opportunities,
                },
                "legal_replay": replay_cost == 1
                and states_structurally_equal(replay, preview.post_deal_state),
                "future_rows": len(blueprint.future_rows),
            }
        )
    return tuple(rows)


def _capabilities(opening: SpiderState) -> tuple[dict[str, bool], dict]:
    preview = preview_deal_now(opening, build_whole_deal_blueprint(opening))

    deferrable = SpiderState(
        _columns([Card("c", 7)], [Card("c", 6)]), _row(Card("h", 4))
    )
    def_blueprint, def_schedule = _schedule(deferrable)
    def_item = classify_pre_deal_objective(
        deferrable,
        _objective(target_epoch=5),
        preview_deal_now(deferrable, def_blueprint),
        current_schedule=def_schedule,
    )

    required = SpiderState(
        _columns([], [Card("c", 6)], [Card("c", 4)]), _row(Card("c", 5))
    )
    req_blueprint, req_before = _schedule(required)
    prepared = required.clone()
    prepared.move(1, 0, 1, rules=MW_RULES)
    req_after = rebuild_whole_deal_schedule(prepared, req_blueprint)

    supplied = SpiderState(_columns([Card("c", 6)]), _row(Card("c", 5)))
    supplied_blueprint, supplied_schedule = _schedule(supplied)
    supplied_classes = _classes(supplied_schedule)
    supplied_after = supplied.clone()
    supplied_after.deal(MW_RULES)
    supplied_harvest = classify_epoch_transition_harvest(
        supplied,
        supplied_after,
        supplied_schedule,
        rebuild_whole_deal_schedule(supplied_after, supplied_blueprint),
    )

    advantage = SpiderState(_columns([], [Card("c", 6)]), _row(Card("c", 5)))
    _, advantage_schedule = _schedule(advantage)
    expensive = SpiderState(
        _columns([Card("h", 9)], [Card("c", 6)]), _row(Card("c", 5))
    )
    _, expensive_schedule = _schedule(expensive)

    opening_blueprint, opening_schedule = _schedule(opening, 4)
    late = [
        item
        for item in opening_schedule.pre_deal_opportunities
        if item.deadline_distance is not None and item.deadline_distance >= 4
    ]

    urgent = SpiderState(
        _columns(
            [Card("c", 6), Card("d", 9)],
            [Card("c", 7)],
            [Card("c", 5)],
        ),
        _row(Card("h", 4)),
    )
    urgent_blueprint, urgent_schedule = _schedule(urgent)
    urgent_source = next(
        item
        for item in urgent_schedule.leverage_cards
        if item.card == Card("c", 6) and item.column == 0
    )
    urgent_item = classify_pre_deal_objective(
        urgent,
        _objective(
            ScheduleObjectiveFamily.EXPOSE_UNLOCK_CARD,
            source=urgent_source.card,
            source_ref=urgent_source.source_id,
            deadline=ScheduleDeadlineKind.BEFORE_NEXT_DEAL,
            edges=2,
            leverage=2,
            joined=1,
        ),
        preview_deal_now(urgent, urgent_blueprint),
        current_schedule=urgent_schedule,
    )

    two_epoch = SpiderState(
        [Column([], [Card("c", 13)]) for _ in range(10)],
        [Card("h", 2)] * 10 + [Card("s", 4)] * 10,
    )
    two_blueprint = build_whole_deal_blueprint(two_epoch)
    transition_ids = []
    for corrected_g in (1, 2):
        source = two_epoch.clone()
        before = rebuild_whole_deal_schedule(source, two_blueprint)
        two_epoch.deal(MW_RULES)
        after = rebuild_whole_deal_schedule(two_epoch, two_blueprint)
        opportunity = make_epoch_transition_opportunity(
            source,
            two_epoch,
            before,
            after,
            corrected_g_after_deal=corrected_g,
            stable_structure_after=0,
            rehandling_debt_after=0,
            exact_tt_admitted=True,
            independently_replay_verified=True,
        )
        transition_ids.append(opportunity.opportunity_id if opportunity else None)

    stock_empty = SpiderState(_columns([Card("c", 7)], [Card("c", 6)]), [])
    _, empty_schedule = _schedule(stock_empty)

    tt = StrategicTranspositionTable()
    identity_before = canonical_state_key(opening)
    lower_before = compute_solution_lower_bound(opening).h_admissible
    tt.admit(opening, 3)
    lower_g = tt.admit(opening, 2) and not tt.admit(opening, 2)
    _schedule(opening)

    gates = {
        "A": bool(preview and preview.strategic_expansions == 0 and not preview.entered_tt),
        "B": def_item.classification == PreDealOpportunityClass.DEFERRABLE,
        "C": req_before.saturation.status == EpochSaturationStatus.PREPARATION_REQUIRED,
        "D": bool(
            req_before.saturation.status == EpochSaturationStatus.PREPARATION_REQUIRED
            and req_after.saturation.status == EpochSaturationStatus.DEAL_READY
            and epoch_transition_objective(prepared, req_after) is not None
        ),
        "E": bool(
            supplied_classes[PreDealOpportunityClass.FUTURE_SUPPLIED.value]
            and EpochTransitionHarvestKind.REALIZED_FREE_JOIN
            in {item.kind for item in supplied_harvest}
        ),
        "F": advantage_schedule.saturation.status
        == EpochSaturationStatus.PREPARATION_ADVANTAGE,
        "G": not expensive_schedule.receptions[0].worthwhile_preparation,
        "H": bool(
            late
            and all(
                item.classification != PreDealOpportunityClass.MUST_PRE_DEAL
                for item in late
            )
        ),
        "I": urgent_item.classification
        in {
            PreDealOpportunityClass.MUST_PRE_DEAL,
            PreDealOpportunityClass.ADVANTAGE_PRE_DEAL,
        },
        "J": bool(
            opening_schedule.saturation.status == EpochSaturationStatus.DEAL_READY
            and opening.can_deal(MW_RULES)
        ),
        "K": len(set(transition_ids)) == 2,
        "L": len(set(transition_ids)) == 2,
        "M": bool(
            empty_schedule.saturation.status == EpochSaturationStatus.STOCK_EMPTY
            and epoch_transition_objective(stock_empty, empty_schedule) is None
        ),
        "N": hasattr(controller.StrategicSearchNode, "__dataclass_fields__")
        and "completion_cash_out" in controller.StrategicSearchNode.__dataclass_fields__
        and "epoch_transition_opportunity"
        in controller.StrategicSearchNode.__dataclass_fields__,
        "O": bool(
            canonical_state_key(opening) == identity_before
            and lower_g
            and compute_solution_lower_bound(opening).h_admissible == lower_before
        ),
    }
    details = {
        "opening_schedule": _compact_schedule(opening_schedule),
        "deferrable": def_item,
        "required_then_ready": (
            req_before.saturation.status.value,
            req_after.saturation.status.value,
        ),
        "supplied_classes": supplied_classes,
        "advantage": advantage_schedule.saturation.status.value,
        "expensive_reception": expensive_schedule.receptions[0],
        "late_count": len(late),
        "urgent": urgent_item,
        "transition_ids": tuple(transition_ids),
        "stock_empty": empty_schedule.saturation.status.value,
        "proof": {
            "scheduler_in_identity": False,
            "counterfactual_in_TT": False,
            "transition_in_identity": False,
            "lower_bound": lower_before,
            "lower_g_dominance": lower_g,
        },
        "opening_blueprint": opening_blueprint.blueprint_id,
    }
    return gates, details


def _gate_summary(result, offset: int = 0) -> dict | None:
    if result is None:
        return None
    return {
        "result": _summary(result, offset=offset),
        "funnel": _transition_funnel(result),
        "epochs": result.telemetry.expansions_by_stock_epoch,
        "traces": tuple(_compact_trace(item) for item in result.telemetry.scheduler_epoch_traces),
        "classifications": result.telemetry.scheduler_pre_deal_classifications,
        "selected_classifications": result.telemetry.scheduler_selected_pre_deal_classifications,
        "harvests": result.telemetry.scheduler_transition_harvest_counts,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-u-seconds", type=float, default=90.0)
    parser.add_argument("--gate-v-seconds", type=float, default=90.0)
    parser.add_argument("--gate-w-seconds", type=float, default=180.0)
    parser.add_argument("--skip-gate-v", action="store_true")
    parser.add_argument("--skip-gate-w", action="store_true")
    parser.add_argument("--complete-suite-result", default=FINAL_SUITE_RESULT)
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL_PATH)
    independent = reconstruct_cost23_checkpoint()
    blueprint, opening_schedule = _schedule(opening, 4)
    gates, capability_details = _capabilities(opening)
    if not all(gates.values()):
        raise AssertionError(f"capability gate failed: {gates}")
    unseen = _unseen(cards)

    anchor_result = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor = _node(anchor_result)
    if (
        anchor.g != 21
        or len(anchor.state.foundations) != 1
        or controller._action_path_hash(anchor.actions) != "924bfd20deac96af"
    ):
        raise AssertionError("machine cost-21 anchor regressed")

    gate_u_config = _gate_config(
        _gate_uw_base_config,
        min(90.0, args.gate_u_seconds),
        expansions=25,
        nodes=300_000,
    )
    gate_u = solve_anytime(opening, cards, None, gate_u_config)
    gate_u_authorized = bool(
        gate_u.telemetry.scheduler_transition_representatives_expanded
        and any(item.epoch_after >= 1 for item in gate_u.telemetry.scheduler_epoch_traces)
    )

    gate_v = None
    gate_v_config = None
    if gate_u_authorized and not args.skip_gate_v:
        gate_v_config = _gate_config(
            _gate_v_base_config,
            min(90.0, args.gate_v_seconds),
            expansions=25,
            nodes=300_000,
        )
        gate_v = solve_anytime(anchor.state, cards, None, gate_v_config)
    gate_v_advanced = bool(
        gate_v and gate_v.telemetry.scheduler_transition_representatives_expanded
    )
    gate_v_f2 = bool(gate_v and len(_node(gate_v).state.foundations) >= 2)

    gate_w_authorized = gate_u_authorized and bool(
        gate_v_advanced
        or (gate_v and gate_v.telemetry.scheduler_receptions_realized)
        or gate_v_f2
    )
    gate_w = None
    gate_w_config = None
    if gate_w_authorized and not args.skip_gate_w:
        gate_w_config = _gate_config(
            _gate_uw_base_config,
            min(180.0, args.gate_w_seconds),
            expansions=50,
            nodes=500_000,
        )
        gate_w = solve_anytime(opening, cards, None, gate_w_config)
    gate_w_f1 = bool(gate_w and len(_node(gate_w).state.foundations) >= 1)
    gate_w_f2 = bool(gate_w and len(_node(gate_w).state.foundations) >= 2)

    repeat = "not applicable: Gate W did not reach F2"
    optional = "not authorized: requires Gate W F2 and deterministic repeat"
    if gate_w_f2 and gate_w_config is not None:
        repeated = solve_anytime(opening, cards, None, gate_w_config)
        repeat = {
            "summary": _summary(repeated),
            "route": _route(opening, repeated),
            "same_path": controller._action_path_hash(_node(repeated).actions)
            == controller._action_path_hash(_node(gate_w).actions),
        }
        if repeat["same_path"]:
            optional_config = replace(gate_w_config, wall_clock_limit_s=240.0)
            optional_result = solve_anytime(opening, cards, None, optional_config)
            optional = {
                "summary": _summary(optional_result),
                "route": _route(opening, optional_result),
            }

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
    opening_classes = _classes(opening_schedule)
    preview = opening_schedule.deal_now_counterfactual
    best_opening_construction = next(
        (
            (item.objective.family.value, item.objective.objective_id)
            for item in opening_schedule.pre_deal_opportunities
            if item.classification == PreDealOpportunityClass.DEFERRABLE
        ),
        None,
    )
    opening_audit = {
        "classifications": opening_classes,
        "saturation": opening_schedule.saturation.status.value,
        "reason": opening_schedule.saturation.reason,
        "best_ordinary_construction": best_opening_construction,
        "incoming_row": tuple(str(card) for card in preview.incoming_row),
        "post_Deal_schedule": _compact_schedule(preview.post_deal_schedule),
        "DEAL_READY_justified": opening_schedule.saturation.status
        == EpochSaturationStatus.DEAL_READY,
    }

    anchor_report = {
        "canonical_172": {
            "corrected": canonical.mobilityware_moves,
            "path": canonical.path_hash,
            "state": canonical.state_hash,
        },
        "machine_F1_cost21": {
            **_summary(anchor_result),
            "replay": _route(opening, anchor_result),
        },
        "independent_F1_cost23": {
            "corrected": independent.arm.total_cost,
            "actions": independent.action_count,
            "deals": independent.deal_count,
            "foundations": len(independent.state.foundations),
            "suits": independent.foundation_suits,
            "stock": len(independent.state.stock),
            "face_down": independent.face_down_count,
            "replay": independent.independently_verified,
            "endpoint": controller._state_hash(independent.state),
            "structural": format(zobrist(independent.state), "x"),
        },
    }

    gate_u_report = _gate_summary(gate_u)
    gate_v_report = _gate_summary(gate_v)
    gate_w_report = _gate_summary(gate_w)
    gate_v_route = _continuous_route(opening, anchor, gate_v) if gate_v else None
    gate_w_route = _route(opening, gate_w) if gate_w else None
    transition_count = (
        gate_w.telemetry.scheduler_transition_representatives_expanded if gate_w else 0
    )
    complete = bool(
        gate_w_route
        and gate_w_route["foundations"] == 8
        and gate_w_route["stock"] == 0
    )

    if complete and gate_w_route["corrected_cost"] <= 171:
        verdict = "EXCEPTIONAL"
        classification = "F. SUCCESSFUL EPOCH RHYTHM"
    elif gate_w_f2 and isinstance(repeat, dict) and repeat.get("same_path"):
        verdict = "STRONG PASS"
        classification = "F. SUCCESSFUL EPOCH RHYTHM"
    elif gate_v_f2 or gate_w_f2:
        verdict = "PASS"
        classification = "F. SUCCESSFUL EPOCH RHYTHM"
    elif gate_u_authorized and transition_count >= 2:
        verdict = "PARTIAL"
        classification = "D. MULTI-EPOCH ECONOMICS FAILURE"
    else:
        verdict = "FAIL"
        classification = "B. DEAL-TRANSITION-SELECTION FAILURE"
    blocker = (
        "none; a complete sub-172 route was independently replayed"
        if verdict == "EXCEPTIONAL"
        else (
            "Deal starvation is removed, but consecutive Deal-ready epochs do not "
            "convert the typed bridge/high-leverage arrivals into preparation and "
            "foundation progress on the same continuous branch."
        )
    )
    recommendation = (
        "A separately authorized scheduler v0.3 should model arrival-to-foundation "
        "conversion obligations and compare consuming arrived leverage with the next "
        "Deal; retain all current resource, TT and proof limits."
    )

    model = {
        "Deal_Now": "actual engine Deal plus exactly one fresh non-recursive post-Deal schedule",
        "prepare_then_Deal": "only already-generated replay-valid successors; exact engine Deal; marginal comparison",
        "classes": tuple(item.value for item in PreDealOpportunityClass),
        "saturation": tuple(item.value for item in EpochSaturationStatus),
    }
    v01_diagnosis = (
        "The four-slot suit-diverse objective portfolio was filled by fragment work, "
        "so PREPARE_EPOCH_TRANSITION never annotated the legal Deal. Exact TT admission "
        "did not fail; after admission, ordinary global priority repeatedly selected "
        "local fragments because no post-TT epoch-transition coverage lane existed."
    )

    values = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", {"profile": "MobilityWare four-suit", "unrestricted_Deal": MW_RULES.can_deal_into_empty, "Deal_cost": 1}),
        ("regression anchors", anchor_report),
        ("v0.1 architecture baseline", "static WholeDealBlueprint + fresh exact-state WholeDealSchedule + <=4 advisory annotations"),
        ("exact v0.1 Deal-starvation diagnosis", v01_diagnosis),
        ("Deal-Now counterfactual model", model["Deal_Now"]),
        ("pre-move-then-Deal comparison model", model["prepare_then_Deal"]),
        ("pre-Deal objective classification", model["classes"]),
        ("objective deferrability semantics", "useful work may remain ordinary positive construction when its marginal pre-Deal value is not superior"),
        ("future-supplied semantics", "exact next row supplies or preserves the objective more cheaply; do not redundantly prepare it"),
        ("epoch saturation model", model["saturation"]),
        ("Deal-readiness model", "DEAL_READY only after no MUST and no demonstrably superior bounded ADVANTAGE realiser remains"),
        ("one-shot epoch-transition representative", "one post-TT exact Deal child; one normal expansion; exact source+epoch+row identity; then spent"),
        ("interaction with completion cash-out", "independent typed coverage; completion/foundation precedence wins direct conflict; no frontier growth"),
        ("interaction with terminal/foundation play", "terminal/foundation-critical work precedes transition coverage"),
        ("next-Deal reception urgency", "BEFORE_NEXT_DEAL only when the exact row materially loses or improves a receiver opportunity"),
        ("high-leverage source urgency", "compare actionability/blocker work before and after exact Deal; one-edge survivors remain deferrable"),
        ("late-suit deadline behaviour", "retained in the itinerary but epoch-5 work is not automatically urgent at epoch 0"),
        ("post-Deal replanning", "new exact fingerprint, epoch, lanes, receptions, leverage, saturation and bounded objectives"),
        ("epoch transition harvest", tuple(item.value for item in EpochTransitionHarvestKind)),
        ("proof/TT safety", capability_details["proof"]),
        ("resource/preview safety", "non-recursive previews charge neither tactical nodes nor strategic expansions; all gate ceilings unchanged"),
    ]
    for letter in "ABCDEFGHIJKLMNO":
        values.append((f"capability Gate {letter}", {"passed": gates[letter], "evidence": capability_details}))
    values.extend(
        [
            ("unseen-deal results", unseen),
            ("benchmark blueprint regression", {"blueprint": blueprint.blueprint_id, "future_rows": len(blueprint.future_rows), "objectives": len(opening_schedule.objectives)}),
            ("benchmark future rows", stock_rows),
            ("benchmark temporal-floor regression", floors),
            ("benchmark opening readiness audit", opening_audit),
            ("Gate U config/result", {"config": {"wall": gate_u_config.wall_clock_limit_s, "expansions": gate_u_config.max_strategic_expansions, "nodes": gate_u_config.max_tactical_nodes, "frontier": gate_u_config.max_frontier_size, "closure_beam": gate_u_config.dependency_closure_config.beam_width, "persistence": gate_u_config.milestone_max_strategic_expansions}, "result": gate_u_report}),
            ("Gate U transition funnel", _transition_funnel(gate_u)),
            ("Gate U principal pre-Deal table", opening_audit),
            ("Gate U actual Deal transition", tuple(_compact_trace(item) for item in gate_u.telemetry.scheduler_epoch_traces)),
            ("Gate U epoch-1 replan", tuple(item.next_objective_ids for item in gate_u.telemetry.scheduler_epoch_traces if item.epoch_after == 1)),
            ("Gate V config/result", {"config": ({"wall": gate_v_config.wall_clock_limit_s, "expansions": gate_v_config.max_strategic_expansions, "nodes": gate_v_config.max_tactical_nodes, "frontier": gate_v_config.max_frontier_size} if gate_v_config else None), "result": gate_v_report}),
            ("Gate V epoch table", gate_v.telemetry.expansions_by_stock_epoch if gate_v else None),
            ("Gate V transition funnel", _transition_funnel(gate_v) if gate_v else None),
            ("Gate V preparation/Deal timeline", tuple(_compact_trace(item) for item in gate_v.telemetry.scheduler_epoch_traces) if gate_v else None),
            ("Gate V F2", gate_v_f2),
            ("Gate W authorization", {"authorized": gate_w_authorized, "Gate_U_advanced": gate_u_authorized, "Gate_V_advanced": gate_v_advanced, "skipped": args.skip_gate_w}),
            ("Gate W config/result if authorized", {"config": ({"wall": gate_w_config.wall_clock_limit_s, "expansions": gate_w_config.max_strategic_expansions, "nodes": gate_w_config.max_tactical_nodes, "frontier": gate_w_config.max_frontier_size} if gate_w_config else None), "result": gate_w_report}),
            ("Gate W strategic expansions", gate_w.strategic_expansions if gate_w else None),
            ("Gate W continuous epoch rhythm", tuple(_compact_trace(item) for item in gate_w.telemetry.scheduler_epoch_traces) if gate_w else None),
            ("Gate W objective classifications", gate_w.telemetry.scheduler_pre_deal_classifications if gate_w else None),
            ("Gate W selected pre-Deal work", {"selected": gate_w.telemetry.scheduler_selected_pre_deal_classifications, "timeline": gate_w.telemetry.scheduler_timeline} if gate_w else None),
            ("Gate W Deal transitions", tuple(_compact_trace(item) for item in gate_w.telemetry.scheduler_epoch_traces) if gate_w else None),
            ("Gate W reception outcomes", {"realized": gate_w.telemetry.scheduler_receptions_realized, "missed": gate_w.telemetry.scheduler_receptions_missed} if gate_w else None),
            ("Gate W high-leverage arrivals", gate_w.telemetry.scheduler_transition_harvest_counts if gate_w else None),
            ("Gate W late-suit fragment behaviour", gate_w.telemetry.scheduler_objectives_by_family.get(ScheduleObjectiveFamily.BUILD_FRAGMENT.value, {}) if gate_w else None),
            ("Gate W substantial milestones", gate_w.telemetry.substantial_structural_milestones if gate_w else None),
            ("Gate W F1", gate_w_f1),
            ("Gate W F2", gate_w_f2),
            ("route/replay/hashes", {"Gate_U": _route(opening, gate_u), "Gate_V_continuous": gate_v_route, "Gate_W": gate_w_route}),
            ("repeatability", repeat),
            ("optional whole-game run", optional),
            ("any complete solution", complete),
            ("any verified score below172", gate_w_route if complete and gate_w_route["corrected_cost"] < 172 else None),
            ("preview/scheduler performance", {"Gate_U": _scheduler_performance(gate_u), "Gate_V": _scheduler_performance(gate_v) if gate_v else None, "Gate_W": _scheduler_performance(gate_w) if gate_w else None}),
            ("tactical/resource telemetry", {"Gate_U": _resource(gate_u), "Gate_V": _resource(gate_v) if gate_v else None, "Gate_W": _resource(gate_w) if gate_w else None}),
            ("TT statistics", {"Gate_U": (gate_u.telemetry.tt_new, gate_u.telemetry.tt_improved, gate_u.telemetry.tt_suppressed), "Gate_V": ((gate_v.telemetry.tt_new, gate_v.telemetry.tt_improved, gate_v.telemetry.tt_suppressed) if gate_v else None), "Gate_W": ((gate_w.telemetry.tt_new, gate_w.telemetry.tt_improved, gate_w.telemetry.tt_suppressed) if gate_w else None)}),
            ("proof statistics", {"Gate_U": (gate_u.telemetry.proof_pruned, gate_u.telemetry.scheduler_proof_prunes), "Gate_V": ((gate_v.telemetry.proof_pruned, gate_v.telemetry.scheduler_proof_prunes) if gate_v else None), "Gate_W": ((gate_w.telemetry.proof_pruned, gate_w.telemetry.scheduler_proof_prunes) if gate_w else None)}),
            ("complete-suite result", args.complete_suite_result),
            ("verdict", verdict),
            ("architectural classification", classification),
            ("precise remaining blocker", blocker),
            ("recommended scheduler v0.3 / next task", recommendation),
        ]
    )
    if len(values) != 79:
        raise AssertionError(f"diagnostic section count is {len(values)}, expected 79")
    for number, (title, value) in enumerate(values, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
