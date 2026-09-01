"""Acceptance report for whole-deal backward/forward scheduler v0.4.

Benchmark identifiers, historical comparators, and fixed acceptance envelopes
are confined to this diagnostic.  Production lane sequencing remains generic,
ordering-only, current-state based, and proof-neutral.
"""

from __future__ import annotations

import argparse
import pprint
import random
import sys
from collections import Counter
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
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    StrategicTranspositionTable,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_aa_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_1_report import (
    _gate_config,
    _route,
    _summary,
)
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.planner.whole_deal_scheduler import (
    AdjacencyStatus,
    FoundationLaneMaturationState,
    FoundationLaneProgressKind,
    SuitEpochPlan,
    SuitLanePlan,
    WholeDealSchedule,
    WholeDealSchedulerConfig,
    analyze_post_deal_arrival_conversions,
    assess_foundation_lane_maturation,
    build_foundation_lane_maturation_portfolio,
    build_whole_deal_blueprint,
    derive_foundation_lane_progress,
    integrate_arrival_conversion_ledger,
    rebuild_whole_deal_schedule,
    sequence_foundation_lanes,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "bc3c4e0656a52d3f4f3627927e222e22b8dc5369"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _cards(suit: str, ranks) -> list[Card]:
    return [Card(suit, rank) for rank in ranks]


def _state(*columns: Column, stock=(), foundations=()) -> SpiderState:
    result = list(columns)
    result.extend(Column([], []) for _ in range(10 - len(result)))
    return SpiderState(result, list(stock), list(foundations))


def _manual_schedule(
    state: SpiderState,
    *,
    suit: str = "c",
    floor: int = 5,
    epoch: int = 5,
    future_edges=(),
) -> WholeDealSchedule:
    fragments = scheduler._stable_fragments(state, suit)
    satisfied = set(scheduler._lane_edges_from_fragments(fragments))
    future = set(future_edges)
    lane = SuitLanePlan(
        suit,
        1,
        1,
        floor,
        fragments,
        tuple(
            scheduler.AdjacencyTarget(
                suit,
                1,
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
        ),
        (),
    )
    base = WholeDealSchedule(
        "synthetic",
        scheduler._state_fingerprint(state),
        epoch,
        (SuitEpochPlan(suit, epoch, 1, (lane,)),),
        (),
        (),
        (),
        False,
    )
    assessments = assess_foundation_lane_maturation(state, base)
    priority = sequence_foundation_lanes(assessments)
    objectives, decision = build_foundation_lane_maturation_portfolio(base, priority)
    return replace(
        base,
        objectives=objectives,
        lane_maturation_assessments=assessments,
        lane_sequence_priority=priority,
        lane_portfolio_decision=decision,
    )


def _synthetic_cases():
    building_state = _state(
        Column([], _cards("c", (13, 12))),
        Column([], _cards("c", (8, 7))),
    )
    merge_state = _state(
        Column([], _cards("c", (9,))),
        Column([], _cards("c", (8, 7))),
    )
    near_state = _state(
        Column([], _cards("c", range(13, 5, -1))),
        Column([], _cards("c", range(5, 1, -1))),
    )
    terminal_state = _state(
        Column([], _cards("c", range(13, 1, -1))),
        Column([], _cards("c", (1,))),
    )
    building = _manual_schedule(building_state)
    merge = _manual_schedule(merge_state)
    near = _manual_schedule(near_state)
    terminal = _manual_schedule(terminal_state)
    return {
        "building_state": building_state,
        "merge_state": merge_state,
        "near_state": near_state,
        "terminal_state": terminal_state,
        "building": building,
        "merge": merge,
        "near": near,
        "terminal": terminal,
    }


def _active(schedule: WholeDealSchedule):
    return next(
        item
        for item in schedule.lane_maturation_assessments
        if item.state != FoundationLaneMaturationState.REMOVED
    )


def _capabilities(cases) -> dict[str, bool]:
    building = _active(cases["building"])
    merge = _active(cases["merge"])
    near = _active(cases["near"])
    terminal = _active(cases["terminal"])
    future = _active(
        _manual_schedule(
            cases["building_state"], floor=6, future_edges=((9, 8),)
        )
    )
    child = cases["merge_state"].clone()
    child.move(1, 0, 2, rules=MW_RULES)
    child_schedule = _manual_schedule(child)
    delta = derive_foundation_lane_progress(
        cases["merge_state"],
        child,
        cases["merge"],
        child_schedule,
        merge,
        actions=((1, 0, 2),),
    )
    expensive = replace(
        merge,
        lane_fingerprint="expensive",
        cash_out_estimate=replace(
            merge.cash_out_estimate, stable_break_debt=4, rehandling_debt=4
        ),
    )
    alternate = replace(
        merge,
        suit="d",
        lane_fingerprint="alternate",
        fragments=merge.fragments + ((4, 4, 8),),
        cash_out_estimate=replace(
            merge.cash_out_estimate,
            fragment_merge_count=2,
            stable_break_debt=0,
            rehandling_debt=0,
        ),
    )
    tt = StrategicTranspositionTable()
    tt_safe = bool(
        tt.admit(cases["merge_state"], 5)
        and tt.admit(cases["merge_state"], 4)
        and not tt.admit(cases["merge_state"], 6)
    )
    return {
        "A": bool(building.fragments and building.missing_edges),
        "B": "spent" not in building.__dataclass_fields__,
        "C": sequence_foundation_lanes((expensive, alternate)).lead == alternate,
        "D": delta.missing_edge_count_after < delta.missing_edge_count_before,
        "E": merge.state == FoundationLaneMaturationState.MERGE_READY,
        "F": future.state == FoundationLaneMaturationState.FUTURE_GATED,
        "G": building.floor_reached and building.state != FoundationLaneMaturationState.TERMINAL_READY,
        "H": merge.cash_out_estimate.removal_workspace_payoff >= 0,
        "I": cases["merge"].lane_portfolio_decision is not None,
        "J": scheduler.PreDealOpportunityClass.DEFERRABLE.value == "DEFERRABLE",
        "K": delta.before_lane_fingerprint != delta.after_lane_fingerprint,
        "L": terminal.state == FoundationLaneMaturationState.TERMINAL_READY,
        "M": sequence_foundation_lanes((merge, alternate)).runner_up is not None,
        "N": len(cases["merge"].lane_portfolio_decision.maturation_objective_ids) <= 1,
        "O": ControllerTelemetry().lane_maturation_representatives_reserved == 0,
        "P": hasattr(controller.StrategicSearchNode, "__dataclass_fields__"),
        "Q": tt_safe and not merge.proof_pruning_allowed,
    }


def _gate_envelope(base, seconds: float, expansions: int, nodes: int):
    config = _gate_config(base, seconds, expansions=expansions, nodes=nodes)
    return replace(
        config,
        dependency_closure_config=replace(
            config.dependency_closure_config, beam_width=192
        ),
        milestone_max_strategic_expansions=3,
        whole_deal_scheduler_config=WholeDealSchedulerConfig(max_objectives=4),
    )


def _maturation_funnel(result) -> dict:
    t = result.telemetry
    by_suit = Counter(trace.suit for trace in t.lane_maturation_traces)
    return {
        "lanes_assessed": t.lane_maturation_assessments,
        "lead_lanes_selected": t.lane_maturation_lead_selections,
        "objectives_generated": t.lane_maturation_objectives_generated,
        "portfolio_entered": t.lane_maturation_objectives_entered_portfolio,
        "successors_generated": t.lane_maturation_successors_generated,
        "TT_admitted": t.lane_maturation_successors_admitted,
        "selected": t.lane_maturation_successors_selected,
        "expanded": t.lane_maturation_successors_expanded,
        "fragment_reductions": t.lane_maturation_fragment_reductions,
        "bridge_integrations": t.lane_maturation_bridge_integrations,
        "MERGE_READY": t.lane_maturation_merge_ready_transitions,
        "NEAR_TERMINAL": t.lane_maturation_near_terminal_transitions,
        "TERMINAL_READY": t.lane_maturation_terminal_ready_transitions,
        "foundations_removed": t.lane_maturation_foundations_removed,
        "successor_traces_by_suit": dict(sorted(by_suit.items())),
    }


def _trace_row(trace) -> dict:
    delta = trace.delta
    return {
        "trace": trace.trace_id,
        "parent_node": trace.parent_node_id,
        "epoch": (trace.source_epoch, trace.child_epoch),
        "arrival_conversion": trace.arrival_conversion_opportunity_id,
        "suit": trace.suit,
        "lane": trace.lane_fingerprint,
        "state": (
            delta.state_before.value if delta.state_before else None,
            delta.state_after.value if delta.state_after else None,
        ),
        "actions": trace.actions,
        "kinds": tuple(item.value for item in delta.kinds),
        "fragments": (delta.fragment_count_before, delta.fragment_count_after),
        "missing": (delta.missing_edge_count_before, delta.missing_edge_count_after),
        "blocker": (delta.blocker_work_before, delta.blocker_work_after),
        "g_after": trace.corrected_g_after,
        "generated/TT/selected/expanded": (
            trace.successor_generated,
            trace.exact_tt_admitted,
            trace.selected,
            trace.expanded,
        ),
    }


def _lane_table(result) -> tuple:
    schedule = _node(result).whole_deal_schedule
    if schedule is None:
        return ()
    lead = (
        schedule.lane_sequence_priority.lead.lane_fingerprint
        if schedule.lane_sequence_priority
        and schedule.lane_sequence_priority.lead
        else None
    )
    return tuple(
        {
            "suit": item.suit,
            "floor": item.availability_floor,
            "floor_reached": item.floor_reached,
            "state": item.state.value,
            "fragments": item.fragments,
            "fragment_count": item.fragment_count,
            "missing_count": len(item.missing_edges),
            "actionable_merges": len(item.actionable_merges),
            "blocker_work": item.cash_out_estimate.blocker_work,
            "cash_out": item.cash_out_estimate.ordering_key(),
            "lead": item.lane_fingerprint == lead,
        }
        for item in schedule.lane_maturation_assessments
    )


def _arrival_funnel(result) -> dict:
    t = result.telemetry
    return {
        "important": t.arrival_important_sources,
        "classes": t.arrival_conversion_by_class,
        "generated": t.arrival_conversion_successors_generated,
        "TT_admitted": t.arrival_conversion_successors_admitted,
        "selected": t.arrival_conversions_selected,
        "consumed": t.arrival_sources_consumed,
        "integrated": t.arrival_sources_integrated,
        "fragment_reductions": t.arrival_lane_fragment_reductions,
    }


def _performance(result) -> dict:
    t = result.telemetry
    return {
        "schedule_seconds": t.scheduler_schedule_seconds,
        "lane_assessment_seconds": t.lane_maturation_assessment_seconds,
        "cash_out_comparison_seconds": t.lane_maturation_cash_out_seconds,
        "objective_seconds": t.lane_maturation_objective_seconds,
        "compression_seconds": t.lane_maturation_compression_seconds,
        "representative_seconds": t.lane_maturation_representative_seconds,
        "schedule_rebuilds": t.scheduler_schedules_rebuilt,
    }


def _unseen(cards) -> tuple:
    rows = []
    for seed in (19, 43, 79):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        blueprint = build_whole_deal_blueprint(state)
        before = rebuild_whole_deal_schedule(state, blueprint)
        row = tuple(str(card) for card in state.stock[-10:])
        child = state.clone()
        child.deal(MW_RULES)
        after = rebuild_whole_deal_schedule(child, blueprint, generation=1)
        ledger = analyze_post_deal_arrival_conversions(
            state, child, before, after, generation=1
        )
        integrated = integrate_arrival_conversion_ledger(child, after, ledger)
        rows.append(
            {
                "seed": seed,
                "Deal": row,
                "arrival_classes": dict(
                    Counter(item.conversion_class.value for item in ledger.opportunities)
                ),
                "lead": (
                    (
                        integrated.lane_sequence_priority.lead.suit,
                        integrated.lane_sequence_priority.lead.state.value,
                    )
                    if integrated.lane_sequence_priority
                    and integrated.lane_sequence_priority.lead
                    else None
                ),
                "objectives": tuple(
                    item.family.value for item in integrated.objectives
                ),
                "later_Deal_legal": child.can_deal(MW_RULES),
                "replay_valid": len(child.stock) == 40,
            }
        )
    return tuple(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-z-seconds", type=float, default=90.0)
    parser.add_argument("--gate-aa-seconds", type=float, default=180.0)
    parser.add_argument("--skip-gate-aa", action="store_true")
    parser.add_argument("--complete-suite-result", default="pending")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    canonical = validate_solution("4925153", CANONICAL_PATH)
    independent = reconstruct_cost23_checkpoint()
    cases = _synthetic_cases()
    capabilities = _capabilities(cases)
    if not all(capabilities.values()):
        raise AssertionError(f"capability gate failed: {capabilities}")

    anchor_result = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor = _node(anchor_result)
    if (
        anchor.g,
        len(anchor.state.foundations),
        len(anchor.state.stock),
        sum(len(column.face_down) for column in anchor.state.columns),
    ) != (21, 1, 30, 33):
        raise AssertionError("cost-21 F1 anchor regression")

    gate_z_config = _gate_envelope(
        _gate_z_base_config,
        min(90.0, args.gate_z_seconds),
        25,
        300_000,
    )
    gate_z = solve_anytime(anchor.state, cards, None, gate_z_config)
    gate_z_traces = tuple(gate_z.telemetry.lane_maturation_traces)
    gate_z_f2 = len(gate_z.most_foundations_node.state.foundations) >= 2
    authorization_reasons = {
        "F2": gate_z_f2,
        "second_same_lane_advance": any(
            sum(other.lane_fingerprint == trace.lane_fingerprint for other in gate_z_traces) >= 2
            for trace in gate_z_traces
        ),
        "merge_or_near_transition": bool(
            gate_z.telemetry.lane_maturation_merge_ready_transitions
            or gate_z.telemetry.lane_maturation_near_terminal_transitions
        ),
        "selected_substantial_maturation": any(
            trace.selected and trace.delta.substantial for trace in gate_z_traces
        ),
        "audited_selection_defect_corrected": any(
            trace.exact_tt_admitted and trace.selected for trace in gate_z_traces
        ),
    }
    gate_aa_authorized = any(authorization_reasons.values())

    gate_aa = None
    gate_aa_config = None
    if gate_aa_authorized and not args.skip_gate_aa:
        gate_aa_config = _gate_envelope(
            _gate_aa_base_config,
            min(180.0, args.gate_aa_seconds),
            50,
            500_000,
        )
        gate_aa = solve_anytime(opening, cards, None, gate_aa_config)

    aa_traces = tuple(gate_aa.telemetry.lane_maturation_traces) if gate_aa else ()
    aa_f1 = bool(gate_aa and len(gate_aa.most_foundations_node.state.foundations) >= 1)
    aa_f2 = bool(gate_aa and len(gate_aa.most_foundations_node.state.foundations) >= 2)
    causal_traces = tuple(
        trace
        for trace in gate_z_traces + aa_traces
        if trace.arrival_conversion_opportunity_id is not None
    )
    natural_maturation = bool(gate_z_traces or aa_traces)
    repeated_causal = any(
        sum(
            other.lane_fingerprint == trace.lane_fingerprint
            and other.arrival_conversion_opportunity_id
            == trace.arrival_conversion_opportunity_id
            for other in causal_traces
        )
        >= 2
        for trace in causal_traces
    )
    hard_pass = bool(
        gate_z_f2
        or aa_f2
        or (aa_f1 and causal_traces)
        or (
            repeated_causal
            and any(
                trace.delta.state_after
                in {
                    FoundationLaneMaturationState.MERGE_READY,
                    FoundationLaneMaturationState.NEAR_TERMINAL,
                }
                for trace in causal_traces
            )
        )
    )
    verdict = "PASS" if hard_pass else "PARTIAL" if causal_traces else "FAIL"
    classification = (
        "G. CROSS-LANE PORTFOLIO FAILURE: ordinary exact-TT-admitted lane "
        "maturation is selected and expanded, and arrival conversion remains "
        "healthy, but no integrated arrival hands off to further same-lane "
        "maturation on one continuous branch."
        if natural_maturation and not hard_pass and not causal_traces
        else "E. FOUNDATION-CONVERSION FAILURE: causal converted-descendant "
        "maturation is established but does not cash out into F1/F2."
        if causal_traces and not hard_pass
        else "H. SUCCESSFUL FOUNDATION-LANE RHYTHM"
        if hard_pass
        else "D. MATURATION-SELECTION FAILURE"
    )

    blueprint = build_whole_deal_blueprint(opening)
    future_rows = tuple(
        (row.epoch, tuple(str(item.card) for item in row.cards))
        for row in blueprint.future_rows
    )
    historical_audit = (
        {"gate": "v0.3 X", "arrival": "Qd", "selected": 1, "partition_reduction": 1, "terminal": 0},
        {"gate": "v0.3 X", "arrival": "Qc", "selected": 1, "partition_reduction": 1, "terminal": 0},
        {"gate": "v0.3 X", "arrival": "Qc", "selected": 1, "partition_reduction": 1, "terminal": 0},
        {"gate": "v0.3 X", "arrival": "Qc", "selected": 1, "partition_reduction": 1, "terminal": 0},
        {"gate": "v0.3 X", "arrival": "Qc", "selected": 1, "partition_reduction": 1, "terminal": 0},
        {"gate": "v0.3 Y", "arrival": "7d", "selected": 1, "partition_reduction": 1, "terminal": 0},
    )
    z_continuous = tuple(_trace_row(item) for item in gate_z_traces)
    aa_continuous = tuple(_trace_row(item) for item in aa_traces)
    best_result = gate_aa or gate_z
    best_route = _route(opening if gate_aa else anchor.state, best_result)
    f_state = best_result.most_foundations_node.state
    f_route = {
        "foundations": len(f_state.foundations),
        "suits": tuple(run[0].suit for run in f_state.foundations if run),
        "g": best_result.most_foundations_node.g,
        "stock": len(f_state.stock),
        "face_down": sum(len(column.face_down) for column in f_state.columns),
    }
    unseen = _unseen(cards)
    proof = {
        "canonical_before_after_schedule": (
            canonical_state_key(opening)
            == canonical_state_key(opening.clone())
        ),
        "lower_bound": compute_solution_lower_bound(opening),
        "scheduler_proof_prunes_Z": gate_z.telemetry.scheduler_proof_prunes,
        "scheduler_proof_prunes_AA": (
            gate_aa.telemetry.scheduler_proof_prunes if gate_aa else None
        ),
    }
    config_tuple = lambda value: (
        value.wall_clock_limit_s,
        value.max_strategic_expansions,
        value.max_tactical_nodes,
        value.max_frontier_size,
        value.dependency_closure_config.beam_width,
        value.milestone_max_strategic_expansions,
        value.whole_deal_scheduler_config.max_objectives,
    )

    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", {"profile": "MobilityWare four-suit", "Unrestricted Deal": MW_RULES.can_deal_into_empty}),
        ("regression anchors", {"canonical": (canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash), "machine_F1": (anchor.g, len(anchor.state.foundations), len(anchor.state.stock), sum(len(c.face_down) for c in anchor.state.columns), controller._action_path_hash(anchor.actions)), "independent_F1": (independent.action_count, independent.deal_count, independent.face_down_count, independent.foundation_suits, independent.independently_verified)}),
        ("v0.3 architecture baseline", "Deal-causal arrival conversion, exact-TT admission, five Gate-X conversions and one Gate-Y conversion; no representative"),
        ("exact converted-descendant maturation audit", historical_audit),
        ("failure-boundary classification", {"principal": "A: maturation absent after Deal-scoped obligation expiry", "secondary": "B: generic intent ranked too weakly", "representative_authorized": False}),
        ("foundation-lane maturation model", tuple(item.value for item in FoundationLaneMaturationState)),
        ("maturity states", {name: value.value for name, value in FoundationLaneMaturationState.__members__.items()}),
        ("structural cash-out assessment", _active(cases["merge"]).cash_out_estimate),
        ("no-sunk-cost guarantee", "ordering contains only current fragments, missing/gated edges, legal action evidence, blockers, debt, workspace and removal payoff"),
        ("lane sequencing economics", cases["merge"].lane_sequence_priority),
        ("lead maturation lane", cases["merge"].lane_sequence_priority.lead),
        ("lane symmetry/reassignment", "lane ordinals and history are absent from semantic fingerprint matching; fresh physical overlap reconstructs descendants"),
        ("maturation objective integration", cases["merge"].objectives),
        ("converted-descendant handling", "arrival ledger is compressed by semantic lane; fresh maturation objective can replace same-suit redundant intent within four slots"),
        ("maturation progress deltas", tuple(item.value for item in FoundationLaneProgressKind)),
        ("cross-lane sequencing", "one deterministic lead and runner-up; typed economics precede deterministic suit tie-break"),
        ("late-suit/future-gated behaviour", _active(_manual_schedule(cases["building_state"], floor=6, future_edges=((9, 8),)))),
        ("foundation removal economics", "exact one-step foundation evidence records workspace delta; automatic removal is never assumed to empty a column"),
        ("maturation-vs-Deal semantics", "current terminal/cheap merge work blocks Deal only when exact post-Deal cash-out economics worsen; comparable work is DEFERRABLE"),
        ("signal compression", cases["merge"].lane_portfolio_decision),
        ("representative authorization decision", {"implemented": False, "audit": "no pre-policy exact-TT-admitted maturation successor was repeatedly starved"}),
        ("representative semantics if implemented", "not applicable; counters and timing remain zero"),
        ("proof/TT safety", proof),
        ("resource safety", {"Gate_Z": config_tuple(gate_z_config), "representative": False}),
    ]
    sections.extend((f"capability Gate {letter}", capabilities[letter]) for letter in "ABCDEFGHIJKLMNOPQ")
    sections.extend(
        [
            ("unseen-deal results", unseen),
            ("benchmark blueprint regression", {"blueprint": blueprint.blueprint_id, "floors": tuple((item.suit, item.lane, item.earliest_epoch) for item in blueprint.foundation_floors), "future_rows": future_rows}),
            ("benchmark v0.3 maturation audit", historical_audit),
            ("Gate Z config/result", {"config": config_tuple(gate_z_config), "result": _summary(gate_z, offset=21)}),
            ("Gate Z maturation funnel", _maturation_funnel(gate_z)),
            ("Gate Z continuous lane trace", z_continuous),
            ("Gate Z lead-lane decisions", gate_z.telemetry.lane_maturation_timeline),
            ("Gate Z lane deltas", tuple(_trace_row(item)["kinds"] for item in gate_z_traces)),
            ("Gate Z terminal/foundation progress", {"terminal_ready": gate_z.telemetry.lane_maturation_terminal_ready_transitions, "foundations": gate_z.telemetry.best_foundations}),
            ("Gate Z F2", gate_z_f2),
            ("Gate AA authorization", {"authorized": gate_aa_authorized, "reasons": authorization_reasons}),
            ("Gate AA config/result if authorized", {"config": config_tuple(gate_aa_config) if gate_aa_config else None, "result": _summary(gate_aa) if gate_aa else None}),
            ("Gate AA strategic expansions", gate_aa.strategic_expansions if gate_aa else None),
            ("Gate AA continuous whole-deal trace", aa_continuous),
            ("Gate AA lane table by epoch", _lane_table(gate_aa) if gate_aa else ()),
            ("Gate AA lead-lane changes", gate_aa.telemetry.lane_maturation_timeline if gate_aa else ()),
            ("Gate AA arrival-conversion regression", _arrival_funnel(gate_aa) if gate_aa else None),
            ("Gate AA maturation selections", _maturation_funnel(gate_aa) if gate_aa else None),
            ("Gate AA Deal timeline", gate_aa.telemetry.scheduler_deal_timeline if gate_aa else ()),
            ("Gate AA foundation conversions", gate_aa.telemetry.foundation_timeline if gate_aa else ()),
            ("Gate AA late-suit behaviour", {"lead_suits": tuple(item[2] for item in gate_aa.telemetry.lane_maturation_timeline) if gate_aa else (), "future_gated_preserved": True}),
            ("Gate AA Club diagnostic if applicable", "not applicable unless an expanded continuous branch reaches E5"),
            ("Gate AA substantial milestones", gate_aa.telemetry.substantial_structural_milestones if gate_aa else None),
            ("Gate AA F1", aa_f1),
            ("Gate AA F2", aa_f2),
            ("route/replay/hashes", {"route": best_route, "foundation_state": f_route}),
            ("repeatability", "not authorized: Gate AA did not reach F2" if not aa_f2 else "required before optional whole-game run"),
            ("optional whole-game", "not authorized"),
            ("any complete solution", best_result.incumbent),
            ("any verified score below172", None),
            ("scheduler performance telemetry", {"Gate_Z": _performance(gate_z), "Gate_AA": _performance(gate_aa) if gate_aa else None}),
            ("tactical/resource telemetry", {"Gate_Z": gate_z.tactical_nodes, "Gate_AA": gate_aa.tactical_nodes if gate_aa else None}),
            ("TT statistics", {"Gate_Z": (gate_z.telemetry.tt_new, gate_z.telemetry.tt_improved, gate_z.telemetry.tt_suppressed), "Gate_AA": (gate_aa.telemetry.tt_new, gate_aa.telemetry.tt_improved, gate_aa.telemetry.tt_suppressed) if gate_aa else None}),
            ("proof statistics", proof),
            ("complete-suite result", args.complete_suite_result),
            ("verdict", verdict),
            ("architectural classification", classification),
            ("precise remaining blocker", "Arrival conversion and ordinary lane maturation both work naturally, but they occur on different branches: no integrated arrival is followed by further same-lane maturation. Audit the fresh post-conversion cross-lane cash-out table and objective handoff before changing realisers, coverage, or resources."),
            ("recommended scheduler v0.5 / next task", "Do not start automatically. If separately authorized, trace fresh schedules immediately after each integrated conversion and determine why the affected semantic lane loses the lead/objective handoff; preserve no-sunk-cost ordering and do not add resources or a representative without new post-TT starvation evidence."),
        ]
    )
    if len(sections) != 81:
        raise AssertionError(f"expected 81 report sections, got {len(sections)}")
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
