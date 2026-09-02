#!/usr/bin/env python3
"""v0.5 Gate Z validation: conversion-child maturation handoff on search nodes.

Read-only. Inherited cost-21 envelope. No production changes, no unpacking.
"""

from __future__ import annotations

import pprint
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.planner.anytime_controller import solve_anytime
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_y_base_config,
)
from spider.planner.diagnostics.post_conversion_lane_handoff_audit import (
    _path_nodes,
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
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_5_report import (
    _independent_generation,
    _lineage_row,
    _shift_row,
)
from spider.planner.whole_deal_scheduler import ArrivalConversionHarvestKind


DEAL_PATH = ROOT / "deals" / "4925153.txt"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))
    sys.stdout.flush()


def _arrival_row(trace) -> dict:
    return {
        "id": trace.opportunity_id,
        "incoming": str(trace.incoming_card) if trace.incoming_card else None,
        "column": (
            trace.destination_column + 1
            if trace.destination_column is not None
            else None
        ),
        "class": trace.conversion_class.value,
        "status": trace.status.value,
        "generated/TT/selected": (
            trace.successor_generated,
            trace.exact_tt_admitted,
            trace.selected,
        ),
        "harvests": tuple(item.kind.value for item in trace.harvests),
        "suit": trace.incoming_card.suit if trace.incoming_card is not None else None,
    }


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("V0.5 GATE Z VALIDATION")
    print("No production changes. Inherited cost-21 envelope only.")
    sys.stdout.flush()

    print("\n== replayed machine F1 cost-21 ==")
    sys.stdout.flush()
    anchor_config = _opening_anchor_config()
    assert not anchor_config.enable_whole_deal_scheduler
    anchor_result = solve_anytime(opening, cards, None, anchor_config)
    anchor = _node(anchor_result)
    facts = (
        anchor.g,
        len(anchor.state.foundations),
        len(anchor.state.stock),
        sum(len(column.face_down) for column in anchor.state.columns),
    )
    _section(1, "cost-21 F1 checkpoint", {"facts": facts, "summary": _summary(anchor_result)})
    if facts != (21, 1, 30, 33):
        print("STOP: cost-21 F1 checkpoint regression")
        return 1

    gate_z_config = _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000)
    envelope = {
        "wall_clock_limit_s": gate_z_config.wall_clock_limit_s,
        "max_strategic_expansions": gate_z_config.max_strategic_expansions,
        "max_tactical_nodes": gate_z_config.max_tactical_nodes,
        "max_frontier_size": gate_z_config.max_frontier_size,
        "closure_beam": gate_z_config.dependency_closure_config.beam_width,
        "milestone_max_strategic_expansions": (
            gate_z_config.milestone_max_strategic_expansions
        ),
        "scheduler": gate_z_config.enable_whole_deal_scheduler,
        "scheduler_portfolio": gate_z_config.whole_deal_scheduler_config.max_objectives,
        "max_scheduler_objectives_in_portfolio": (
            gate_z_config.max_scheduler_objectives_in_portfolio
        ),
    }
    expected = {
        "wall_clock_limit_s": 90.0,
        "max_strategic_expansions": 25,
        "max_tactical_nodes": 300_000,
        "max_frontier_size": 256,
        "closure_beam": 192,
        "milestone_max_strategic_expansions": 3,
        "scheduler": True,
        "scheduler_portfolio": 4,
        "max_scheduler_objectives_in_portfolio": 1,
    }
    _section(2, "Gate Z envelope", envelope)
    if envelope != expected:
        print("STOP: Gate Z envelope drifted")
        print("expected", expected)
        return 1

    print("\n== Gate Z from cost-21 ==")
    sys.stdout.flush()
    gate_z = solve_anytime(anchor.state, cards, None, gate_z_config)
    t = gate_z.telemetry
    z_node = _node(gate_z)
    z_f2 = len(gate_z.most_foundations_node.state.foundations) >= 2
    arrivals = tuple(t.arrival_conversion_traces)
    integrated_arrivals = tuple(
        item
        for item in arrivals
        if any(
            harvest.kind == ArrivalConversionHarvestKind.ARRIVAL_SOURCE_INTEGRATED
            for harvest in item.harvests
        )
        or item.status.value in {"INTEGRATED", "CONSUMED", "SPENT"}
    )
    selected_arrivals = tuple(item for item in arrivals if item.selected)
    mat_traces = tuple(t.lane_maturation_traces)
    causal = tuple(
        item for item in mat_traces if item.arrival_conversion_opportunity_id is not None
    )
    causal_tt = tuple(item for item in causal if item.exact_tt_admitted)
    causal_selected = tuple(item for item in causal if item.selected)
    causal_expanded = tuple(item for item in causal if item.expanded)
    same_lane_repeat = any(
        sum(other.lane_fingerprint == item.lane_fingerprint for other in causal_tt) >= 2
        for item in causal_tt
    )
    substantial = tuple(item for item in causal_tt if item.delta.substantial)

    path_audits = []
    independent = []
    for node in _path_nodes(gate_z):
        path_audits.extend(
            _scan_path(
                "gate-z-path",
                anchor.state,
                node.actions,
                cards,
                mat_traces,
            )
        )
        independent.extend(_independent_generation(anchor.state, node.actions))
    unique = []
    seen = set()
    for row in path_audits:
        key = (row["opportunity_id"], row["incoming"], row["physical_fragments_after"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    former_e = [
        row
        for row in unique
        if row["converted_is_lead"]
        and row["entered_four_slot_portfolio"]
        and row["legal_maturation_successor"]
    ]
    class_b = [row for row in unique if row["failure_class"] == "B"]
    path_e_tt = [row for row in former_e if row["tt_admitted"]]

    primary = bool(causal)
    stronger = bool(primary and causal_tt and (causal_selected or causal_expanded))
    _section(
        3,
        "Gate Z result",
        {
            "summary": _summary(gate_z, offset=21),
            "foundations_best": len(gate_z.most_foundations_node.state.foundations),
            "F2": z_f2,
            "funnel": _maturation_funnel(gate_z),
            "arrival": {
                "traces": len(arrivals),
                "selected": t.arrival_conversions_selected,
                "tt_admitted": t.arrival_conversion_successors_admitted,
                "integrated": t.arrival_sources_integrated,
                "consumed": t.arrival_sources_consumed,
            },
            "selected_arrivals": tuple(_arrival_row(item) for item in selected_arrivals),
            "integrated_arrivals": tuple(_arrival_row(item) for item in integrated_arrivals),
            "causal_maturation": {
                "generated_traces": len(causal),
                "TT_admitted": len(causal_tt),
                "selected": len(causal_selected),
                "expanded": len(causal_expanded),
                "same_lane_repeat": same_lane_repeat,
                "substantial": len(substantial),
                "foundations_removed": t.lane_maturation_foundations_removed,
            },
            "causal_trace_rows": tuple(_trace_row(item) for item in causal),
            "all_maturation_trace_rows": tuple(_trace_row(item) for item in mat_traces),
            "cash_out_shifts": tuple(_shift_row(item) for item in t.conversion_cash_out_shifts),
            "join_worsened": {
                "rehandling": t.conversion_join_with_worsened_rehandling,
                "workspace": t.conversion_join_with_worsened_workspace,
                "blocker": t.conversion_join_with_worsened_blocker,
            },
            "path_class_counts": dict(Counter(row["failure_class"] for row in unique)),
            "path_lineages": tuple(_lineage_row(row) for row in unique),
            "path_former_E": len(former_e),
            "path_former_E_TT": len(path_e_tt),
            "path_class_B": len(class_b),
            "independent_generation": independent,
            "representatives": (
                t.lane_maturation_representatives_required,
                t.lane_maturation_representatives_reserved,
                t.lane_maturation_representatives_expanded,
            ),
            "primary_success": primary,
            "stronger": stronger,
            "best_F2": z_f2,
        },
    )

    auth = {
        "F2": z_f2,
        "second_same_lane_advance": any(
            sum(other.lane_fingerprint == trace.lane_fingerprint for other in mat_traces)
            >= 2
            for trace in mat_traces
        ),
        "merge_or_near_transition": bool(
            t.lane_maturation_merge_ready_transitions
            or t.lane_maturation_near_terminal_transitions
        ),
        "selected_substantial_maturation": any(
            trace.selected and trace.delta.substantial for trace in mat_traces
        ),
        "audited_selection_defect_corrected": any(
            trace.exact_tt_admitted and trace.selected for trace in mat_traces
        ),
    }
    _section(4, "Gate AA/Y inherited authorization", auth)

    if not primary:
        print("\nSTOP: no integrated-arrival child produced an exact-TT-admitted same-lane maturation successor.")
        return 1

    if not any(auth.values()):
        print("\nPrimary success, but inherited Gate AA/Y authorization is false. STOP.")
        return 0

    print("\n== Gate AA/Y from opening (unchanged 50 / 180s / 500k) ==")
    sys.stdout.flush()
    gate_y_config = _gate_envelope(_gate_y_base_config, 180.0, 50, 500_000)
    gate_y = solve_anytime(opening, cards, None, gate_y_config)
    yt = gate_y.telemetry
    y_causal = tuple(
        item
        for item in yt.lane_maturation_traces
        if item.arrival_conversion_opportunity_id is not None
    )
    _section(
        5,
        "Gate AA/Y",
        {
            "summary": _summary(gate_y),
            "stock": len(_node(gate_y).state.stock),
            "F1": len(gate_y.most_foundations_node.state.foundations) >= 1,
            "F2": len(gate_y.most_foundations_node.state.foundations) >= 2,
            "funnel": _maturation_funnel(gate_y),
            "causal": tuple(_trace_row(item) for item in y_causal),
            "shifts": tuple(_shift_row(item) for item in yt.conversion_cash_out_shifts),
        },
    )
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
