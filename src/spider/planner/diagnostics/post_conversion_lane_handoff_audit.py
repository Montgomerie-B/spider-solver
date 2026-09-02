#!/usr/bin/env python3
"""Forensic audit of the immediate post-conversion lane handoff.

Rebuilds the exact fresh schedule after every NATURAL integrated arrival
conversion found on continuous search paths. Production sequencing policy
is not changed. No representative, resource increase, or v0.5 correction.
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
from spider.planner.anytime_controller import solve_anytime
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_y_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_1_report import (
    _gate_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
from spider.planner.whole_deal_scheduler import (
    ArrivalConversionClass,
    ArrivalConversionHarvestKind,
    FoundationLaneMaturationState,
    WholeDealSchedulerConfig,
    _maturation_objective,
    _matching_maturation_lane,
    _stable_fragments,
    analyze_post_deal_arrival_conversions,
    build_whole_deal_blueprint,
    classify_arrival_conversion_harvest,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES


DEAL_PATH = ROOT / "deals" / "4925153.txt"
CLASSES = tuple("ABCDEFGH")


def _fp(fragments) -> tuple:
    return tuple(sorted((high, low, column) for high, low, column in fragments))


def _lane_row(item, *, lead_fp=None, runner_fp=None):
    cash = item.cash_out_estimate
    role = "lead" if item.lane_fingerprint == lead_fp else (
        "runner-up" if item.lane_fingerprint == runner_fp else ""
    )
    return {
        "suit": item.suit,
        "lane_ordinal": item.lane,
        "fingerprint": item.lane_fingerprint,
        "state": item.state.value,
        "floor": item.availability_floor,
        "floor_reached": item.floor_reached,
        "fragments": item.fragments,
        "fragment_count": item.fragment_count,
        "satisfied": item.satisfied_edges,
        "missing": item.missing_edges,
        "blockers": tuple(b.kind.value for b in item.blockers),
        "cash_out": cash.ordering_key(),
        "ordering": item.ordering_key()[:4],
        "role": role,
        "strong": item.strong_current_maturation,
        "actionable_merges": len(item.actionable_merges),
        "actionable_bridges": len(item.actionable_bridge_edges),
    }


def _match_suit_lane(assessments, suit, fragments):
    candidates = [item for item in assessments if item.suit == suit]
    if not candidates:
        return None
    want = set(fragments)
    return min(
        candidates,
        key=lambda item: (
            -len(want & set(item.fragments)),
            -len(set(item.satisfied_edges)),
            item.ordering_key(),
        ),
    )


def _why_lead(converted, lead, runner) -> str:
    if converted is None:
        return "converted semantic lane has no matching current-state assessment"
    if lead is None:
        return "no lead lane remains"
    if converted.lane_fingerprint == lead.lane_fingerprint:
        why = (
            f"converted {converted.suit} wins: state={converted.state.value} "
            f"cash_out={converted.cash_out_estimate.ordering_key()}"
        )
        if runner is not None:
            why += (
                f" vs runner {runner.suit} state={runner.state.value} "
                f"cash_out={runner.cash_out_estimate.ordering_key()}"
            )
        return why
    return (
        f"converted {converted.suit} loses lead to {lead.suit}: "
        f"converted state={converted.state.value} "
        f"cash_out={converted.cash_out_estimate.ordering_key()} "
        f"ordering={converted.ordering_key()[:3]} vs lead "
        f"state={lead.state.value} cash_out={lead.cash_out_estimate.ordering_key()} "
        f"ordering={lead.ordering_key()[:3]}"
    )


def _audit_child(
    *,
    lineage: str,
    parent: SpiderState,
    child: SpiderState,
    opportunity,
    harvests,
    next_action,
    blueprint,
    maturation_traces,
) -> dict:
    parent_sched = rebuild_whole_deal_schedule(parent, blueprint)
    fresh = rebuild_whole_deal_schedule(child, blueprint)
    lead = (
        fresh.lane_sequence_priority.lead
        if fresh.lane_sequence_priority is not None
        else None
    )
    runner = (
        fresh.lane_sequence_priority.runner_up
        if fresh.lane_sequence_priority is not None
        else None
    )
    lead_fp = lead.lane_fingerprint if lead is not None else None
    runner_fp = runner.lane_fingerprint if runner is not None else None
    parent_assess = parent_sched.lane_maturation_assessments
    child_assess = fresh.lane_maturation_assessments
    suit = opportunity.suit
    parent_lane = _match_suit_lane(
        parent_assess, suit, _stable_fragments(parent, suit) if suit else ()
    )
    child_lane = _match_suit_lane(
        child_assess, suit, _stable_fragments(child, suit) if suit else ()
    )
    if parent_lane is not None:
        matched_child = _matching_maturation_lane(parent_lane, fresh)
        if matched_child is not None:
            child_lane = matched_child
    converted_obj = (
        _maturation_objective(fresh, child_lane) if child_lane is not None else None
    )
    lead_obj = _maturation_objective(fresh, lead) if lead is not None else None
    portfolio_ids = tuple(item.objective_id for item in fresh.objectives)
    maturation_ids = (
        fresh.lane_portfolio_decision.maturation_objective_ids
        if fresh.lane_portfolio_decision is not None
        else ()
    )
    converted_obj_id = converted_obj.objective_id if converted_obj is not None else None
    in_portfolio = converted_obj_id in portfolio_ids if converted_obj_id else False
    in_maturation_slot = converted_obj_id in maturation_ids if converted_obj_id else False
    displaced_by = None
    if converted_obj is not None and not in_portfolio:
        displaced_by = tuple(
            (item.family.value, item.suit, item.objective_id)
            for item in fresh.objectives
        )
    legal_successor = False
    successor_actions = ()
    if child_lane is not None and child_lane.actionable_merges:
        legal_successor = True
        successor_actions = tuple(
            item.actions for item in child_lane.actionable_merges[:3]
        )
    elif child_lane is not None and child_lane.actionable_bridge_edges:
        legal_successor = True
        successor_actions = (("bridge-edge", child_lane.actionable_bridge_edges[0]),)
    linked_traces = tuple(
        trace
        for trace in maturation_traces
        if trace.arrival_conversion_opportunity_id == opportunity.opportunity_id
    )
    tt_admitted = any(trace.exact_tt_admitted for trace in linked_traces)
    selected = any(trace.selected for trace in linked_traces)
    expanded = any(trace.expanded for trace in linked_traces)
    converted_is_lead = (
        child_lane is not None
        and lead is not None
        and child_lane.lane_fingerprint == lead.lane_fingerprint
    )
    # Classification: first matching class, no sunk-cost assumption.
    if child_lane is None and suit is not None:
        klass = "A"
    elif not converted_is_lead:
        klass = "B"
    elif converted_obj is None:
        klass = "C"
    elif not in_portfolio:
        klass = "D"
    elif not legal_successor:
        klass = "E"
    elif linked_traces and not tt_admitted:
        klass = "F"
    elif linked_traces and tt_admitted and not expanded:
        klass = "G"
    elif converted_is_lead and legal_successor and in_portfolio and not linked_traces:
        # A legal one-step exists and the objective is in the portfolio, but
        # the controller never tagged a maturation successor to this
        # conversion. That is generation/handoff, not post-TT starvation.
        klass = "E"
    else:
        klass = "H"
    return {
        "lineage": lineage,
        "opportunity_id": opportunity.opportunity_id,
        "incoming": str(opportunity.incoming_card) if opportunity.incoming_card else None,
        "column": (
            opportunity.destination_column + 1
            if opportunity.destination_column is not None
            else None
        ),
        "conversion_class": opportunity.conversion_class.value,
        "harvests": tuple(item.kind.value for item in harvests),
        "suit": suit,
        "semantic_lane_before": (
            {
                "ordinal": parent_lane.lane,
                "fingerprint": parent_lane.lane_fingerprint,
                "state": parent_lane.state.value,
                "fragments": parent_lane.fragments,
                "cash_out": parent_lane.cash_out_estimate.ordering_key(),
            }
            if parent_lane is not None
            else None
        ),
        "physical_fragments_before": _stable_fragments(parent, suit) if suit else (),
        "physical_fragments_after": _stable_fragments(child, suit) if suit else (),
        "duplicate_lane_after": (
            {
                "ordinal": child_lane.lane,
                "fingerprint": child_lane.lane_fingerprint,
                "state": child_lane.state.value,
                "fragments": child_lane.fragments,
                "cash_out": child_lane.cash_out_estimate.ordering_key(),
            }
            if child_lane is not None
            else None
        ),
        "maturation_before": parent_lane.state.value if parent_lane else None,
        "maturation_after": child_lane.state.value if child_lane else None,
        "cash_out_before": (
            parent_lane.cash_out_estimate.ordering_key() if parent_lane else None
        ),
        "cash_out_after": (
            child_lane.cash_out_estimate.ordering_key() if child_lane else None
        ),
        "fresh_lane_table": tuple(
            _lane_row(item, lead_fp=lead_fp, runner_fp=runner_fp)
            for item in child_assess
        ),
        "lead": (
            (lead.suit, lead.lane_fingerprint, lead.state.value)
            if lead is not None
            else None
        ),
        "runner_up": (
            (runner.suit, runner.lane_fingerprint, runner.state.value)
            if runner is not None
            else None
        ),
        "lead_rationale": _why_lead(child_lane, lead, runner),
        "converted_is_lead": converted_is_lead,
        "scheduler_objectives": tuple(
            (item.family.value, item.suit, item.objective_id)
            for item in fresh.objectives
        ),
        "converted_maturation_objective": (
            (converted_obj.family.value, converted_obj.objective_id)
            if converted_obj is not None
            else None
        ),
        "lead_maturation_objective": (
            (lead_obj.family.value, lead_obj.suit, lead_obj.objective_id)
            if lead_obj is not None
            else None
        ),
        "entered_four_slot_portfolio": in_portfolio,
        "in_maturation_slot": in_maturation_slot,
        "displaced_by": displaced_by,
        "legal_maturation_successor": legal_successor,
        "successor_evidence": successor_actions,
        "linked_maturation_traces": len(linked_traces),
        "tt_admitted": tt_admitted,
        "selected": selected,
        "expanded": expanded,
        "next_action_on_this_branch": next_action,
        "failure_class": klass,
    }


def _scan_path(name, start: SpiderState, actions, cards, maturation_traces) -> list:
    blueprint = build_whole_deal_blueprint(start)
    st = start.clone()
    events = []
    pending_ledger = None
    pending_post_deal = None
    for index, action in enumerate(actions):
        parent = st.clone()
        if action == ("deal",):
            before_sched = rebuild_whole_deal_schedule(parent, blueprint)
            replay_actions(st, [action])
            after_sched = rebuild_whole_deal_schedule(st, blueprint)
            pending_ledger = analyze_post_deal_arrival_conversions(
                parent, st, before_sched, after_sched, generation=index + 1
            )
            pending_post_deal = st.clone()
            continue
        if pending_ledger is None:
            replay_actions(st, [action])
            continue
        before_sched = rebuild_whole_deal_schedule(parent, blueprint)
        replay_actions(st, [action])
        after_sched = rebuild_whole_deal_schedule(st, blueprint)
        nxt = actions[index + 1] if index + 1 < len(actions) else None
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
            events.append(
                _audit_child(
                    lineage=name,
                    parent=parent,
                    child=st.clone(),
                    opportunity=opp,
                    harvests=harvests,
                    next_action=nxt,
                    blueprint=blueprint,
                    maturation_traces=maturation_traces,
                )
            )
        # Keep the ledger for later consumes on this epoch; do not require
        # selected_opportunity_id when scanning an already-chosen path.
    return events


def _path_nodes(result):
    seen = []
    for node in (
        result.most_foundations_node,
        result.best_progress_node,
        result.best_node,
        result.lowest_g_node,
        result.deepest_stock_node,
    ):
        key = tuple(node.actions)
        if key in seen:
            continue
        seen.append(key)
        yield node


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-z-seconds", type=float, default=90.0)
    parser.add_argument("--gate-y-seconds", type=float, default=180.0)
    parser.add_argument("--skip-gate-y", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("POST-CONVERSION LANE HANDOFF AUDIT")
    print("Fresh schedule rebuild after each NATURAL integrated conversion.")
    print("No production policy change. No v0.5 implementation.")
    sys.stdout.flush()

    print("\n== cost-21 opening anchor ==")
    sys.stdout.flush()
    anchor_result = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor = _node(anchor_result)
    print(
        f"  g={anchor.g} F={len(anchor.state.foundations)} "
        f"stock={len(anchor.state.stock)} expansions={anchor_result.strategic_expansions}"
    )
    sys.stdout.flush()

    audits = []
    audits.extend(
        _scan_path(
            "opening-anchor",
            opening,
            anchor.actions,
            cards,
            tuple(anchor_result.telemetry.lane_maturation_traces),
        )
    )

    print("\n== Gate Z / Gate X continuation from cost-21 ==")
    sys.stdout.flush()
    gate_z_config = _gate_envelope(
        _gate_z_base_config,
        min(90.0, args.gate_z_seconds),
        25,
        300_000,
    )
    gate_z = solve_anytime(anchor.state, cards, None, gate_z_config)
    print(
        f"  expansions={gate_z.strategic_expansions} "
        f"integrated={gate_z.telemetry.arrival_sources_integrated} "
        f"selected_conv={gate_z.telemetry.arrival_conversions_selected} "
        f"maturation_tt={gate_z.telemetry.lane_maturation_successors_admitted} "
        f"maturation_exp={gate_z.telemetry.lane_maturation_successors_expanded}"
    )
    sys.stdout.flush()
    z_traces = tuple(gate_z.telemetry.lane_maturation_traces)
    for node in _path_nodes(gate_z):
        audits.extend(
            _scan_path(
                "gate-z-path",
                anchor.state,
                node.actions,
                cards,
                z_traces,
            )
        )

    y_result = None
    if not args.skip_gate_y:
        print("\n== untouched Gate Y / E0->E1 lineage ==")
        sys.stdout.flush()
        gate_y_config = _gate_envelope(
            _gate_y_base_config,
            min(180.0, args.gate_y_seconds),
            50,
            500_000,
        )
        y_result = solve_anytime(opening, cards, None, gate_y_config)
        print(
            f"  expansions={y_result.strategic_expansions} "
            f"integrated={y_result.telemetry.arrival_sources_integrated} "
            f"selected_conv={y_result.telemetry.arrival_conversions_selected} "
            f"stock={len(_node(y_result).state.stock)}"
        )
        sys.stdout.flush()
        y_traces = tuple(y_result.telemetry.lane_maturation_traces)
        for node in _path_nodes(y_result):
            audits.extend(
                _scan_path(
                    "gate-y-path",
                    opening,
                    node.actions,
                    cards,
                    y_traces,
                )
            )

    # Deduplicate by (lineage, opportunity, incoming, fragments_after)
    unique = []
    seen = set()
    for row in audits:
        key = (
            row["lineage"],
            row["opportunity_id"],
            row["incoming"],
            row["physical_fragments_after"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    print("\n== CONVERSION CHILDREN AUDITED ==")
    print(f"  count={len(unique)}")
    for row in unique:
        print()
        print(
            f"  [{row['failure_class']}] {row['lineage']} "
            f"{row['incoming']} col={row['column']} class={row['conversion_class']}"
        )
        print(f"    lead_rationale: {row['lead_rationale']}")
        print(
            f"    converted_is_lead={row['converted_is_lead']} "
            f"maturation_obj={row['converted_maturation_objective']} "
            f"in_portfolio={row['entered_four_slot_portfolio']} "
            f"legal_succ={row['legal_maturation_successor']} "
            f"tt={row['tt_admitted']} selected={row['selected']} "
            f"expanded={row['expanded']}"
        )
        print(f"    next_on_branch={row['next_action_on_this_branch']}")
        print(f"    fragments {row['physical_fragments_before']} -> {row['physical_fragments_after']}")
        print(f"    cash_out {row['cash_out_before']} -> {row['cash_out_after']}")
        print(f"    lead={row['lead']} runner={row['runner_up']}")
        print(f"    objectives={row['scheduler_objectives']}")

    counts = Counter(row["failure_class"] for row in unique)
    print("\n== CLASS COUNTS ==")
    for letter in CLASSES:
        print(f"  {letter}: {counts.get(letter, 0)}")

    primary = counts.most_common(1)[0][0] if counts else None
    starvation = any(row["failure_class"] == "G" for row in unique)
    print(f"\n  primary_boundary={primary}")
    print(f"  post_TT_starvation_evidence={starvation}")
    print("  representative_justified=NO")
    if primary == "B":
        rec = (
            "v0.5 should inspect whether the converted suit's *fresh* cash-out "
            "is mis-estimated immediately after integration (fragment/blocker "
            "accounting), not add a representative. If economics are correct, "
            "the missing chain is not a bug: the converted lane should lose."
        )
    elif primary == "C":
        rec = (
            "v0.5 should emit a maturation objective for a just-integrated "
            "lead/near-lead lane even when strong_current_maturation is false, "
            "still compressed to one slot and without sunk cost."
        )
    elif primary == "D":
        rec = (
            "v0.5 should keep the converted-lane maturation objective inside "
            "the inherited four-slot portfolio when it is generated."
        )
    elif primary == "E":
        rec = (
            "v0.5 should map the converted-lane objective onto an already-legal "
            "one-step realiser (bridge/merge/expose) rather than a new search."
        )
    else:
        rec = (
            "Do not add a representative. Trace the primary class above; "
            "smallest v0.5 fix is the corresponding objective/realiser handoff, "
            "not frontier coverage."
        )
    print(f"  recommended_v0.5={rec}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
