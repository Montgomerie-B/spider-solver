#!/usr/bin/env python3
"""Whole-deal scheduler v0.5 post-conversion maturation handoff gate.

Focused natural evidence first: opening-anchor conversions with the
scheduler enabled at unchanged limits.  Bounded cost-21 / untouched gates
run only when a former class-E lineage reaches exact TT admission.
"""

from __future__ import annotations

import argparse
import pprint
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicSuccessor,
    _annotate_scheduler_successors,
    analyze_stage0_state,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_y_base_config,
)
from spider.planner.diagnostics.post_conversion_lane_handoff_audit import (
    _scan_path,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_1_report import (
    _summary,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
    _maturation_funnel,
    _trace_row,
)
from spider.planner.whole_deal_scheduler import (
    ArrivalConversionClass,
    ArrivalConversionHarvestKind,
    ArrivalConversionStatus,
    WholeDealSchedulerConfig,
    analyze_post_deal_arrival_conversions,
    build_whole_deal_blueprint,
    classify_arrival_conversion_harvest,
    lead_maturation_legal_step,
    rebuild_whole_deal_schedule,
)
from spider.solution_archive import validate_solution


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))
    sys.stdout.flush()


def _scheduler_opening_anchor_config() -> AnytimeControllerConfig:
    return replace(
        _opening_anchor_config(),
        enable_whole_deal_scheduler=True,
        whole_deal_scheduler_config=WholeDealSchedulerConfig(max_objectives=4),
    )


def _conversion_node(state, schedule, opportunity_id: str, ledger=None):
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
        ("natural conversion child",),
        arrival_conversion_opportunity_id=opportunity_id,
        arrival_conversion_class=ArrivalConversionClass.CONSUME_NOW,
    )
    return StrategicSearchNode(
        1,
        state,
        0,
        (),
        0,
        incoming,
        0,
        StrategicCreditLevel.CLEAN,
        None,
        stage0=analyze_stage0_state(state, spent_cost=0, incumbent_cost=None),
        whole_deal_schedule=schedule,
        post_deal_conversion_ledger=ledger,
    )


def _annotate_child(child, schedule, opportunity_id: str, ledger=None) -> dict:
    telemetry = ControllerTelemetry()
    annotated = _annotate_scheduler_successors(
        _conversion_node(child, schedule, opportunity_id, ledger),
        (),
        AnytimeControllerConfig(
            enable_whole_deal_scheduler=True,
            max_scheduler_objectives_in_portfolio=1,
        ),
        telemetry,
    )
    tagged = [
        item
        for item in annotated
        if item.maturation_lane_fingerprint and item.scheduled_objective is not None
    ]
    return {
        "generated": len(tagged),
        "arrival_id": tagged[0].arrival_conversion_opportunity_id if tagged else None,
        "fingerprint": tagged[0].maturation_lane_fingerprint if tagged else None,
        "family": (
            tagged[0].scheduled_objective.family.value if tagged else None
        ),
        "actions": tagged[0].actions if tagged else (),
        "telemetry_generated": telemetry.lane_maturation_successors_generated,
        "legal_step": lead_maturation_legal_step(schedule) is not None,
        "lead": (
            schedule.lane_sequence_priority.lead.suit
            if schedule.lane_sequence_priority is not None
            and schedule.lane_sequence_priority.lead is not None
            else None
        ),
        "lead_state": (
            schedule.lane_sequence_priority.lead.state.value
            if schedule.lane_sequence_priority is not None
            and schedule.lane_sequence_priority.lead is not None
            else None
        ),
    }


def _independent_generation(start: SpiderState, actions) -> tuple:
    """Replay the selected path and annotate each integrated conversion child."""

    blueprint = build_whole_deal_blueprint(start)
    st = start.clone()
    pending_ledger = None
    rows = []
    for index, action in enumerate(actions):
        parent = st.clone()
        if action == ("deal",):
            before_sched = rebuild_whole_deal_schedule(parent, blueprint)
            replay_actions(st, [action])
            after_sched = rebuild_whole_deal_schedule(st, blueprint)
            pending_ledger = analyze_post_deal_arrival_conversions(
                parent, st, before_sched, after_sched, generation=index + 1
            )
            continue
        if pending_ledger is None:
            replay_actions(st, [action])
            continue
        before_sched = rebuild_whole_deal_schedule(parent, blueprint)
        replay_actions(st, [action])
        after_sched = rebuild_whole_deal_schedule(st, blueprint)
        for obligation in pending_ledger.obligations:
            if not obligation.active():
                continue
            opp = obligation.opportunity
            if opp.conversion_class in {
                ArrivalConversionClass.NO_CURRENT_CONVERSION,
                ArrivalConversionClass.INVALIDATED_ARRIVAL,
                ArrivalConversionClass.DEFERRABLE_ARRIVAL,
            }:
                continue
            harvests = classify_arrival_conversion_harvest(
                parent,
                st,
                obligation,
                before_schedule=before_sched,
                after_schedule=after_sched,
            )
            if not any(
                item.kind == ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED
                for item in harvests
            ):
                continue
            integrated = replace(
                pending_ledger,
                obligations=tuple(
                    replace(item, status=ArrivalConversionStatus.INTEGRATED)
                    if item.obligation_id == obligation.obligation_id
                    else item
                    for item in pending_ledger.obligations
                ),
            )
            rows.append(
                {
                    "incoming": str(opp.incoming_card) if opp.incoming_card else None,
                    "opportunity_id": opp.opportunity_id,
                    "suit": opp.suit,
                    "handoff": _annotate_child(
                        st.clone(),
                        after_sched,
                        opp.opportunity_id,
                        integrated,
                    ),
                }
            )
    return tuple(rows)


def _shift_row(shift) -> dict:
    return {
        "suit": shift.suit,
        "state": (shift.state_before, shift.state_after),
        "fragments": (shift.fragment_count_before, shift.fragment_count_after),
        "rehandling": (shift.rehandling_before, shift.rehandling_after),
        "workspace": (shift.workspace_before, shift.workspace_after),
        "blocker": (shift.blocker_before, shift.blocker_after),
        "fragment_merges": (shift.fragment_merges_before, shift.fragment_merges_after),
        "partition_improved": shift.partition_improved,
        "estimate_worsened": shift.estimate_worsened,
        "proof_pruning_allowed": shift.proof_pruning_allowed,
    }


def _lineage_row(row) -> dict:
    return {
        "class": row["failure_class"],
        "incoming": row["incoming"],
        "column": row["column"],
        "suit": row["suit"],
        "converted_is_lead": row["converted_is_lead"],
        "maturation_after": row["maturation_after"],
        "objective": row["converted_maturation_objective"],
        "in_portfolio": row["entered_four_slot_portfolio"],
        "legal_successor": row["legal_maturation_successor"],
        "linked_traces": row["linked_maturation_traces"],
        "generated_tt_selected_expanded": (
            row["linked_maturation_traces"] > 0,
            row["tt_admitted"],
            row["selected"],
            row["expanded"],
        ),
        "cash_out": (row["cash_out_before"], row["cash_out_after"]),
        "lead": row["lead"],
        "next": row["next_action_on_this_branch"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-z-seconds", type=float, default=90.0)
    parser.add_argument("--gate-y-seconds", type=float, default=180.0)
    parser.add_argument("--skip-bounded-gates", action="store_true")
    parser.add_argument("--complete-suite-result", default="pending")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL_PATH)
    print("SCHEDULER V0.5 POST-CONVERSION MATURATION HANDOFF")
    sys.stdout.flush()

    config = _scheduler_opening_anchor_config()
    assert config.max_strategic_expansions == 5
    assert config.wall_clock_limit_s == 40.0
    assert config.max_tactical_nodes == 50_000
    assert config.max_frontier_size == 128
    assert config.enable_whole_deal_scheduler
    _section(
        1,
        "opening-anchor envelope (unchanged limits, scheduler on)",
        {
            "expansions": config.max_strategic_expansions,
            "seconds": config.wall_clock_limit_s,
            "tactical_nodes": config.max_tactical_nodes,
            "frontier": config.max_frontier_size,
            "scheduler": config.enable_whole_deal_scheduler,
            "portfolio": config.max_scheduler_objectives_in_portfolio,
            "canonical_172": canonical.mobilityware_moves,
        },
    )

    print("\n== focused natural opening-anchor ==")
    sys.stdout.flush()
    anchor_result = solve_anytime(opening, cards, None, config)
    anchor = _node(anchor_result)
    t = anchor_result.telemetry
    funnel = _maturation_funnel(anchor_result)
    shifts = tuple(_shift_row(item) for item in t.conversion_cash_out_shifts)
    causal = tuple(
        _trace_row(item)
        for item in t.lane_maturation_traces
        if item.arrival_conversion_opportunity_id is not None
    )
    audits = _scan_path(
        "opening-anchor",
        opening,
        anchor.actions,
        cards,
        tuple(t.lane_maturation_traces),
    )
    unique = []
    seen = set()
    for row in audits:
        key = (row["opportunity_id"], row["incoming"], row["physical_fragments_after"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    independent = _independent_generation(opening, anchor.actions)

    former_e = [
        row
        for row in unique
        if row["converted_is_lead"]
        and row["entered_four_slot_portfolio"]
        and row["legal_maturation_successor"]
    ]
    e_tt = [row for row in former_e if row["tt_admitted"]]
    as_rows = [
        row
        for row in unique
        if row["incoming"] and str(row["incoming"]).startswith("As")
    ]
    js_rows = [
        row
        for row in unique
        if row["incoming"] and str(row["incoming"]).startswith("Js")
    ]
    counts = Counter(row["failure_class"] for row in unique)
    same_lane_repeat = any(
        sum(
            other["duplicate_lane_after"]
            and row["duplicate_lane_after"]
            and other["duplicate_lane_after"]["fingerprint"]
            == row["duplicate_lane_after"]["fingerprint"]
            and other["tt_admitted"]
            for other in unique
        )
        >= 2
        and row["tt_admitted"]
        for row in former_e
    )
    focused_success = bool(e_tt)
    strong_success = bool(
        focused_success
        and (
            same_lane_repeat
            or t.lane_maturation_foundations_removed > 0
            or any(
                row["maturation_after"]
                in {"TERMINAL_READY", "NEAR_TERMINAL", "REMOVED"}
                and row["tt_admitted"]
                for row in former_e
            )
        )
    )
    as_handoff = any(
        row["converted_is_lead"]
        and row["maturation_after"] == "TERMINAL_READY"
        and row["legal_maturation_successor"]
        and row["tt_admitted"]
        for row in as_rows
    )

    _section(
        2,
        "focused natural result",
        {
            "summary": _summary(anchor_result),
            "funnel": funnel,
            "arrival_integrated": t.arrival_sources_integrated,
            "arrival_selected": t.arrival_conversions_selected,
            "conversion_children": len(unique),
            "class_counts": dict(counts),
            "former_E_like": len(former_e),
            "former_E_TT_admitted": len(e_tt),
            "Js": tuple(_lineage_row(row) for row in js_rows),
            "As": tuple(_lineage_row(row) for row in as_rows),
            "all_lineages": tuple(_lineage_row(row) for row in unique),
            "causal_traces": causal,
            "independent_generation": independent,
            "cash_out_shifts": shifts,
            "join_worsened_rehandling": t.conversion_join_with_worsened_rehandling,
            "join_worsened_workspace": t.conversion_join_with_worsened_workspace,
            "join_worsened_blocker": t.conversion_join_with_worsened_blocker,
            "As_TERMINAL_READY_handoff": as_handoff,
            "focused_success": focused_success,
            "strong_success": strong_success,
            "representatives": (
                t.lane_maturation_representatives_required,
                t.lane_maturation_representatives_reserved,
                t.lane_maturation_representatives_expanded,
            ),
        },
    )

    if not focused_success:
        print("\nSTOP: no former class-E successor reached exact TT admission.")
        print("Bounded cost-21 / untouched gates were not run.")
        return 1

    if args.skip_bounded_gates:
        print("\nFocused natural evidence succeeded; bounded gates skipped by flag.")
        return 0

    print("\n== Gate Z from cost-21 (unchanged 25 / 90s / 300k) ==")
    sys.stdout.flush()
    # Cost-21 continuation uses the scheduler-off opening-anchor F1 checkpoint
    # only when this run itself reached it; otherwise continue from this
    # selected endpoint without increasing the envelope.
    z_start = anchor.state
    if (
        anchor.g,
        len(anchor.state.foundations),
        len(anchor.state.stock),
    ) != (21, 1, 30):
        print(
            f"  note: selected endpoint is g={anchor.g} "
            f"F={len(anchor.state.foundations)} stock={len(anchor.state.stock)}; "
            "continuing from this node at the inherited Gate Z envelope"
        )
    gate_z_config = _gate_envelope(
        _gate_z_base_config,
        min(90.0, args.gate_z_seconds),
        25,
        300_000,
    )
    gate_z = solve_anytime(z_start, cards, None, gate_z_config)
    z_f2 = len(gate_z.most_foundations_node.state.foundations) >= 2
    _section(
        3,
        "Gate Z",
        {
            "summary": _summary(gate_z, offset=anchor.g),
            "funnel": _maturation_funnel(gate_z),
            "F2": z_f2,
            "shifts": tuple(
                _shift_row(item) for item in gate_z.telemetry.conversion_cash_out_shifts
            ),
            "join_worsened_rehandling": (
                gate_z.telemetry.conversion_join_with_worsened_rehandling
            ),
            "join_worsened_workspace": (
                gate_z.telemetry.conversion_join_with_worsened_workspace
            ),
        },
    )

    print("\n== Gate Y / AA from opening (unchanged 50 / 180s / 500k) ==")
    sys.stdout.flush()
    gate_y_config = _gate_envelope(
        _gate_y_base_config,
        min(180.0, args.gate_y_seconds),
        50,
        500_000,
    )
    gate_y = solve_anytime(opening, cards, None, gate_y_config)
    y_node = _node(gate_y)
    y_f1 = len(gate_y.most_foundations_node.state.foundations) >= 1
    y_f2 = len(gate_y.most_foundations_node.state.foundations) >= 2
    _section(
        4,
        "Gate Y / AA",
        {
            "summary": _summary(gate_y),
            "funnel": _maturation_funnel(gate_y),
            "stock": len(y_node.state.stock),
            "F1": y_f1,
            "F2": y_f2,
            "shifts": tuple(
                _shift_row(item) for item in gate_y.telemetry.conversion_cash_out_shifts
            ),
        },
    )
    _section(
        5,
        "complete suite",
        args.complete_suite_result,
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
