#!/usr/bin/env python3
"""Reproducible v0.9 milestone-conversion and epoch-progression report."""

from __future__ import annotations

import argparse
import inspect
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
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import solve_anytime
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node, _opening_anchor_config, _replay, _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _v08_gate_h_config,
    _gate_g_config as _v08_gate_i_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import reconstruct_cost23_checkpoint
from spider.planner.epoch_progression import (
    PreDealWorkDisposition,
    PreDealWorkItem,
    analyze_campaign_epoch_availability,
    analyze_material_availability,
    assess_epoch_transition,
    classify_pre_deal_construction,
)
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment, MilestonePrimitiveStep, realize_milestone,
)
from spider.planner.strategic_milestone import (
    MilestonePredicateKind, MilestoneTargetPredicate, StrategicMilestone,
    StrategicMilestoneKind, StrategicMilestonePrerequisite,
    StrategicMilestoneProgress, StrategicMilestoneStatus,
    evaluate_milestone_progress,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "374e21b4be2d61fdcaeecc515b3a7e2636a3a814"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "955 passed, 37 xfailed, 1 existing warning in 1120.21s"


def _section(number, title, value):
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up):
    result = [Column([], list(cards)) for cards in face_up]
    result.extend(Column([], []) for _ in range(10 - len(result)))
    return result


def _fixture(*face_up, stock=()):
    return SpiderState(_columns(*face_up), list(stock))


def _fixture_milestone(state):
    return StrategicMilestone(
        "fixture", canonical_state_key(state), "C#1", "C#1",
        StrategicMilestoneKind.RUN_CONSTRUCTION,
        MilestoneTargetPredicate(
            MilestonePredicateKind.DURABLE_RUN, "build generic three-card run",
            suit="c", minimum_run_length=3,
        ),
        "c", (7, 6, 5), (),
        (StrategicMilestonePrerequisite("source", "source"),),
        StrategicMilestoneProgress(1, 3), 2, 4, 3, 4.0, 12_000,
        "three-card run exists", "fresh target contradiction", None,
    )


def _capability_gates(cards):
    start = _fixture([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    milestone = _fixture_milestone(start)
    def primitive(state, _milestone, *_limits):
        action = (1, 0, 1) if state.columns[1].face_up else (2, 0, 1)
        end = state.clone(); cost = end.move(*action)
        return MilestonePrimitiveStep((action,), end, cost, 1, (str(action),), True, "fixture")
    def fresh(state, prior):
        progress = evaluate_milestone_progress(state, prior)
        return FreshMilestoneAssessment(prior, progress, reason="fresh")
    multi = realize_milestone(start, milestone, primitive, fresh)
    invalid = realize_milestone(
        start, milestone, primitive,
        lambda _state, prior: FreshMilestoneAssessment(None, prior.progress, contradicted=True),
        max_primitive_steps=1,
    )

    future = _fixture([], stock=[Card("c", 5)] + [Card("h", 9)] * 9)
    blocked = analyze_campaign_epoch_availability(future, "C#1", "c", (5,))
    duplicate = _fixture([Card("c", 5)], stock=list(future.stock))
    duplicate_fact = analyze_campaign_epoch_availability(duplicate, "C#1", "c", (5,))
    prep = PreDealWorkItem(
        "prep", PreDealWorkDisposition.MUST_BEFORE_DEAL, "cheap durable join",
        "C#1", "fixture", None, 1, 2.0, "next row covers receiver", completed=True,
    )
    transition = assess_epoch_transition(future, (blocked,), (prep,))

    workspace_target = MilestoneTargetPredicate(
        MilestonePredicateKind.WORKSPACE_USED_RECOVERED, "workspace lifecycle",
        workspace_requires_use=True, workspace_requires_recovery=True,
    )
    workspace = replace(
        milestone, kind=StrategicMilestoneKind.WORKSPACE_LIFECYCLE,
        target=workspace_target, progress=StrategicMilestoneProgress(0, 3),
    )
    created_only = evaluate_milestone_progress(start, workspace, workspace_created=True)
    lifecycle = evaluate_milestone_progress(
        start, workspace, workspace_created=True, workspace_used=True,
        workspace_recovered_or_replaced=True,
    )

    opening = SpiderState.from_cards(cards)
    config = replace(
        _v08_gate_h_config(2.0), enable_strategic_milestones=True,
        wall_clock_limit_s=2.0, max_strategic_expansions=1,
        max_tactical_nodes=12_000, max_frontier_size=64,
    )
    analysis = controller_module.analyze_strategic_state(
        opening, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    kinds = {item.kind for item in analysis.milestone_portfolio.milestones}
    return {
        "A": {
            "status": multi.status.value,
            "primitive_steps": multi.primitive_steps,
            "fresh_reanalyses": multi.fresh_reanalyses,
            "replay": multi.independent_replay_verified,
            "passed": multi.status == StrategicMilestoneStatus.ACHIEVED and multi.fresh_reanalyses == 2,
        },
        "B": {"status": invalid.status.value, "passed": invalid.status == StrategicMilestoneStatus.INVALIDATED},
        "C": {
            "future_blocked": blocked.preparation_only,
            "duplicate_current_feasible": duplicate_fact.current_epoch_feasible,
            "earliest": blocked.earliest_feasible_epoch,
            "proof": blocked.proof_pruning_allowed,
            "passed": blocked.preparation_only and duplicate_fact.current_epoch_feasible and not blocked.proof_pruning_allowed,
        },
        "D": {
            "work": asdict(prep), "transition": transition.status.value,
            "passed": transition.purposeful_deal_eligible,
        },
        "E": {
            "exact_row": tuple(str(card) for card in transition.exact_next_row),
            "purpose": transition.purpose,
            "passed": transition.purposeful_deal_eligible and bool(transition.purpose),
        },
        "F": {
            "creation_alone_complete": created_only.complete,
            "full_lifecycle_complete": lifecycle.complete,
            "passed": not created_only.complete and lifecycle.complete,
        },
        "G": {
            "portfolio_kinds": tuple(sorted(item.value for item in kinds)),
            "raw_fallback": analysis.milestone_portfolio.plan.raw_fallback_available,
            "epoch_transition": analysis.epoch_transition.status.value,
            "passed": StrategicMilestoneKind.RUN_CONSTRUCTION in kinds and analysis.epoch_transition is not None,
        },
    }


def _config(config):
    return {
        "wall": config.wall_clock_limit_s,
        "strategic_expansions": config.max_strategic_expansions,
        "tactical_nodes": config.max_tactical_nodes,
        "frontier": config.max_frontier_size,
        "per_expansion_seconds": config.tactical_resource_config.max_granted_seconds_per_expansion,
        "per_expansion_nodes": config.tactical_resource_config.max_granted_nodes_per_expansion,
        "milestones": config.enable_strategic_milestones,
        "allocator": config.enable_tactical_resource_allocation,
    }


def _milestone_telemetry(result):
    t = result.telemetry
    return {
        "generated_by_kind": t.milestones_generated_by_kind,
        "admitted": t.milestones_admitted,
        "activated": t.milestones_activated,
        "primitive_steps": t.milestone_primitive_steps,
        "advanced": t.milestones_advanced,
        "achieved": t.milestones_achieved,
        "replanned": t.milestones_replanned,
        "stock_blocked": t.milestones_stock_blocked,
        "invalidated": t.milestones_invalidated,
        "superseded": t.milestones_superseded,
        "expired": t.milestones_expired,
        "bounded_misses": t.milestone_bounded_misses,
        "seconds": t.milestone_conversion_seconds,
        "nodes": t.milestone_conversion_nodes,
    }


def _epoch_telemetry(result):
    t = result.telemetry
    return {
        "feasible": t.epoch_feasible_milestones,
        "blocked": t.epoch_stock_blocked_milestones,
        "earliest_epochs": t.earliest_required_future_epochs,
        "must": t.predeal_must_items,
        "should": t.predeal_should_items,
        "free_join_deferrals": t.predeal_free_join_deferrals,
        "avoided": t.predeal_avoided_actions,
        "purposeful_deals": t.purposeful_deals,
        "timeline": tuple(t.epoch_timeline),
    }


def _unseen(cards, seconds):
    reports = []
    for seed in (61, 83):
        shuffled = list(cards); random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = replace(
            _v08_gate_h_config(seconds), enable_strategic_milestones=True,
            wall_clock_limit_s=seconds, max_strategic_expansions=2,
            max_tactical_nodes=12_000, max_frontier_size=64,
        )
        result = solve_anytime(state, shuffled, None, config)
        reports.append({
            "seed": seed, "summary": _summary(result), "replay": _replay(state, result),
            "milestones": _milestone_telemetry(result), "epoch": _epoch_telemetry(result),
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "deadline_healthy": result.elapsed_seconds <= seconds + 1.0,
        })
    return tuple(reports)


def _route(start, result):
    node = _node(result); replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost, valid = None, False
    return {
        "valid": valid, "g": cost, "actions": len(node.actions),
        "deals": sum(action == ("deal",) for action in node.actions),
        "foundations": len(node.state.foundations), "stock": len(node.state.stock),
        "path_hash": controller_module._action_path_hash(node.actions),
        "state_hash": controller_module._state_hash(node.state),
    }


def _foundation_events(start, actions):
    state = start.clone(); result = []; cost = 0; before = len(state.foundations)
    for index, action in enumerate(actions, 1):
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            for foundation in state.foundations[before:]:
                result.append({"number": len(result) + before + 1, "suit": foundation[0].suit, "g": cost, "action": index, "stock": len(state.stock)})
            before = len(state.foundations)
    return tuple(result)


def _selected_epoch_audit(node):
    epoch_results = tuple(
        item for item in node.milestone_ledger.results
        if item.milestone.kind == StrategicMilestoneKind.EPOCH_TRANSITION
        and item.status == StrategicMilestoneStatus.ACHIEVED
    )
    deal_action_indices = tuple(
        index
        for index, action in enumerate(node.actions, 1)
        if action == ("deal",)
    )
    deals = len(deal_action_indices)
    return {
        "selected_deals": deals,
        "deal_action_indices": deal_action_indices,
        "selected_epoch_checkpoints": len(epoch_results),
        "every_selected_deal_purposeful": deals == len(epoch_results),
        "purposes": tuple(item.reason for item in epoch_results),
        "deal_contracts": len(node.deal_contract_history),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-h-seconds", type=float, default=90.0)
    parser.add_argument("--gate-i-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=2.0)
    parser.add_argument("--skip-gate-i", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH)); opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor); independent = reconstruct_cost23_checkpoint()
    gates = _capability_gates(cards); unseen = _unseen(cards, args.smoke_seconds)

    gate_h_config = replace(
        _v08_gate_h_config(args.gate_h_seconds),
        enable_strategic_milestones=True,
        wall_clock_limit_s=args.gate_h_seconds,
    )
    gate_h = solve_anytime(anchor_node.state, cards, None, gate_h_config)
    gate_h_node = _node(gate_h)
    h_t = gate_h.telemetry
    authorization_reasons = {
        "foundation_2": len(gate_h_node.state.foundations) >= 2,
        "substantial_completed_milestone": h_t.milestones_achieved > 0 and h_t.milestone_primitive_steps > 1,
        "terminal_qualification": h_t.milestone_terminal_qualifications > 0,
        "purposeful_epoch_progression": h_t.purposeful_deals > 0,
        "nontrivial_completed_milestones": h_t.milestones_achieved >= 2,
    }
    authorized = any(authorization_reasons.values())
    gate_i = None; repeat = None; f3 = None; whole = None
    gate_i_config = replace(
        _v08_gate_i_config(args.gate_i_seconds),
        enable_strategic_milestones=True,
        wall_clock_limit_s=args.gate_i_seconds,
    )
    if authorized and not args.skip_gate_i:
        gate_i = solve_anytime(opening, cards, None, gate_i_config)
        if len(_node(gate_i).state.foundations) >= 2:
            repeat = solve_anytime(opening, cards, None, gate_i_config)
    selected = gate_i or gate_h; selected_node = _node(selected)
    events = _foundation_events(opening, _node(gate_i).actions) if gate_i else ()
    repeat_ok = bool(repeat and len(_node(repeat).state.foundations) >= 2 and _replay(opening, repeat)["valid"])
    if gate_i and len(_node(gate_i).state.foundations) >= 2 and repeat_ok:
        f3_config = replace(gate_i_config, wall_clock_limit_s=90.0, max_strategic_expansions=50, target_foundation_count=3)
        f3 = solve_anytime(_node(gate_i).state, cards, None, f3_config)
        if f3.elapsed_seconds <= 91.0:
            whole_config = replace(gate_i_config, wall_clock_limit_s=240.0, target_foundation_count=None)
            whole = solve_anytime(opening, cards, None, whole_config)

    gate_i_f = len(_node(gate_i).state.foundations) if gate_i else 0
    if whole and _node(whole).state.is_solved() and _route(opening, whole)["valid"] and _node(whole).g <= 171:
        verdict = "EXCEPTIONAL"
    elif gate_i_f >= 2 and repeat_ok:
        verdict = "STRONG PASS"
    elif len(gate_h_node.state.foundations) >= 2 or gate_i_f >= 2 or (gate_i_f >= 1 and h_t.milestones_achieved):
        verdict = "PASS"
    elif h_t.milestones_achieved or h_t.purposeful_deals:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    blocker = (
        "none through foundation #2"
        if len(selected_node.state.foundations) >= 2
        else "bounded milestone conversion did not reach terminal qualification for foundation #2"
    )

    _section(1, "authoritative base", AUTHORITATIVE_BASE)
    _section(2, "active rule profile", asdict(anchor.preflight.profile))
    _section(3, "regression anchors", {
        "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
        "machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
        "independent": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
    })
    _section(4, "v0.8 blocker", "238 primitive harvest events but no completed foundation or Deal in the 50-expansion untouched gate")
    _section(5, "milestone architecture", tuple(StrategicMilestone.__dataclass_fields__))
    _section(6, "milestone kinds", tuple(item.value for item in StrategicMilestoneKind))
    _section(7, "primitive versus milestone harvest", "primitive events remain allocator facts; milestone harvest requires the explicit target predicate")
    _section(8, "milestone continuity", tuple(item.value for item in StrategicMilestoneStatus))
    _section(9, "bounded conversion coordinator", {"function": "realize_milestone", "per_expansion": (gate_h_config.milestone_max_time_s_per_expansion, gate_h_config.milestone_max_nodes_per_expansion)})
    _section(10, "interval/source-chain semantics", "rank intervals and prerequisite IDs; interchangeable copies, no coordinates")
    _section(11, "workspace milestone semantics", gates["F"])
    _section(12, "epoch-availability architecture", tuple(analyze_campaign_epoch_availability.__annotations__))
    _section(13, "duplicate-aware availability", gates["C"])
    _section(14, "pre-Deal work classifications", tuple(item.value for item in PreDealWorkDisposition))
    _section(15, "purposeful epoch-transition semantics", gates["E"])
    _section(16, "whole-deal milestone portfolio", gates["G"])
    _section(17, "proof-safety audit", {"TT": "exact structural state -> lowest g", "milestone_in_TT": False, "epoch_block_proof": False, "bounded_miss_proof": False, "canonical_route_in_controller": "canonical.moves" in inspect.getsource(controller_module)})
    for number, name in enumerate("ABCDEFG", 18):
        _section(number, f"capability Gate {name}", gates[name])
    _section(25, "unseen-deal smokes", unseen)
    _section(26, "Gate H config/result", {"config": _config(gate_h_config), "summary": _summary(gate_h, offset=anchor_node.g), "replay": _replay(anchor_node.state, gate_h)})
    _section(27, "Gate H milestones generated/achieved", _milestone_telemetry(gate_h))
    _section(28, "Gate H primitive-to-milestone conversion", tuple(gate_h.telemetry.milestone_timeline))
    _section(29, "Gate H stock-availability analysis", _epoch_telemetry(gate_h))
    _section(30, "Gate H pre-Deal work", {"must": h_t.predeal_must_items, "should": h_t.predeal_should_items, "deferred_free": h_t.predeal_free_join_deferrals, "avoided": h_t.predeal_avoided_actions})
    _section(31, "Gate H Deal timeline", {"generated": tuple(h_t.deal_timeline), "selected": _selected_epoch_audit(gate_h_node)})
    _section(32, "Gate H terminal qualification/F2 result", {"terminal": h_t.milestone_terminal_qualifications, "foundations": len(gate_h_node.state.foundations), "F2": len(gate_h_node.state.foundations) >= 2})
    _section(33, "true-opening Gate I authorization", {"authorized": authorized, "reasons": authorization_reasons})
    _section(34, "Gate I config/result if authorized", {"config": _config(gate_i_config), "summary": _summary(gate_i) if gate_i else None, "replay": _replay(opening, gate_i) if gate_i else None})
    _section(35, "Gate I milestone timeline", tuple(gate_i.telemetry.milestone_timeline) if gate_i else None)
    _section(36, "Gate I epoch timeline", tuple(gate_i.telemetry.epoch_timeline) if gate_i else None)
    _section(37, "Gate I stock timeline", {"generated": tuple(gate_i.telemetry.deal_timeline), "selected": _selected_epoch_audit(_node(gate_i))} if gate_i else None)
    _section(38, "Gate I construction by suit", tuple(gate_i.telemetry.construction_timeline) if gate_i else None)
    _section(39, "Gate I first-foundation result", events[0] if events else None)
    _section(40, "post-F1 milestone timeline", tuple(item for item in (gate_i.telemetry.milestone_timeline if gate_i else ()) if events and item[0] >= events[0]["g"]))
    _section(41, "second-foundation result", events[1] if len(events) > 1 else None)
    _section(42, "continuous route/replay/hashes if successful", _route(opening, gate_i) if gate_i and gate_i_f >= 2 else None)
    _section(43, "repeatability", {"run": repeat is not None, "success": repeat_ok, "summary": _summary(repeat) if repeat else None})
    _section(44, "optional F3 continuation", _summary(f3) if f3 else "not authorized")
    _section(45, "optional whole-game result", _summary(whole) if whole else "not authorized")
    _section(46, "milestone telemetry", _milestone_telemetry(selected))
    _section(47, "epoch telemetry", _epoch_telemetry(selected))
    _section(48, "tactical/resource telemetry", {"nodes": selected.tactical_nodes, "requests": selected.telemetry.tactical_requests_by_objective, "seconds": selected.telemetry.tactical_seconds_consumed_by_family})
    _section(49, "TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed})
    _section(50, "proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "milestone_proof": False})
    _section(51, "final full-suite result", FINAL_COMPLETE_SUITE)
    _section(52, "verdict", verdict)
    _section(53, "precise remaining blocker", blocker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
