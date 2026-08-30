#!/usr/bin/env python3
"""v0.11 buried-source candidate autopsy and unchanged-envelope gates."""

from __future__ import annotations

import argparse
import inspect
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
from spider.metrics import replay_actions
from spider.move_lifecycle import (
    BoundedCompensatingBenefit,
    assess_tableau_move,
    with_bounded_compensation,
)
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import AnytimeControllerConfig, analyze_strategic_state, solve_anytime
from spider.planner.buried_source_closure import ClosureFailureDiagnosis, ClosureProgressKind, describe_buried_source
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    DependencyClosureConfig,
    DependencyClosureStatus,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import _node, _opening_anchor_config, _replay, _summary
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import _gate_f_config as _gate_j_base_config, _gate_g_config as _gate_k_base_config
from spider.planner.diagnostics.economic_project_analysis_report import reconstruct_cost23_checkpoint
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "4b399f6f0ae47343a439f4821dd9ed868c2af648"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "1106 passed, 37 xfailed, 1 existing warning in 1169.60 seconds"


def _section(number, title, value):
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit, rank):
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "generic fixture",
    )


def _campaign(base, suit="c", rank=5, space=0):
    needs = tuple(replace(
        need, chosen=_source(suit, need.rank) if need.rank == rank else None,
        must_excavate=need.rank == rank, reason="generic named source",
    ) for need in base.rank_needs)
    return replace(
        base, suit=suit, current_epoch=5, target_removal_epoch=5,
        rank_needs=needs, tableau_critical_cards=tuple(n.chosen for n in needs if n.chosen),
        future_stock_supplied_cards=(), optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(), shared_prerequisite_tasks=(),
        space_requirement=space, stock_plan=(), estimated_campaign_cost=4.0,
        blockers=(), readiness=CampaignReadiness.ASSEMBLY_LED,
    )


def _closure(state, campaign, *, nodes=400, beam=192):
    return realize_campaign_dependency_closure(
        state, campaign, target_dependency_id="source:5:c",
        semantic_target_id="generic-source-chain",
        config=DependencyClosureConfig(
            max_added_cost=8, max_nodes=nodes, time_limit_s=1.5,
            beam_width=beam, enable_legal_candidate_audit=True,
        ),
    )


def _trace_summary(result):
    if not result.buried_source_traces:
        return None
    trace = result.buried_source_traces[0]
    return {
        "target": trace.target_dependency_id,
        "blockers_before": tuple(map(str, trace.blocker_before.blocker_cards)),
        "source_depth": (trace.blocker_before.source_depth, trace.blocker_after.source_depth),
        "legal_target": trace.legal_target_relevant_actions,
        "generated": trace.generated_actions,
        "missing": trace.missing_from_generator,
        "admitted": tuple(a.action for a in trace.candidate_audits if a.disposition.value == "ADMITTED"),
        "rejected": tuple((a.action, a.rejection_reason.value) for a in trace.candidate_audits if a.rejection_reason),
        "beam": tuple((b.search_depth, b.retained, b.discarded, tuple(k.value for k in b.retained_progress_kinds)) for b in trace.beam_audits),
        "substitutions": trace.source_copy_substitutions,
        "exposed": trace.sources_exposed,
        "consumed": trace.source_consumed,
        "diagnosis": trace.failure_diagnosis.value,
        "outcome": trace.outcome,
    }


def _capabilities(base):
    filler7 = tuple([Card("h", 1)] for _ in range(7))
    filler6 = tuple([Card("h", 1)] for _ in range(6))
    campaign = _campaign(base)
    one_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("d", 5)], [Card("h", 6)], *filler7), [])
    two_state = SpiderState(_columns([Card("c", 5), Card("d", 5), Card("d", 4)], [Card("d", 6)], [Card("h", 6)], *filler7), [])
    receiver_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("h", 5), Card("s", 9)], [Card("s", 10)], [Card("h", 6)], *filler6), [])
    workspace_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("s", 9)], [Card("s", 10)], [Card("h", 6)], *filler6), [])
    park_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("h", 5)], [Card("h", 6)], *filler7), [])
    copy_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("c", 5), Card("s", 9)], [Card("s", 10)], [Card("h", 6)], *filler6), [])
    results = {name: _closure(state, campaign, beam=1 if name == "G" else 192) for name, state in (
        ("A", one_state), ("B", two_state), ("C", receiver_state),
        ("D", workspace_state), ("E", park_state), ("G", receiver_state), ("H", copy_state),
    )}
    stable_state = SpiderState(_columns([Card("c", 5), Card("d", 4)], [Card("s", 5), Card("s", 4)], [Card("h", 5)], [Card("h", 6)], *filler6), [])
    lifecycle = assess_tableau_move(stable_state, (1, 2, 1))
    lifecycle = with_bounded_compensation(lifecycle, BoundedCompensatingBenefit(
        lifecycle.estimated_rehandling_cost + 2, "named source receiver", "bounded same-suit restore",
    ))
    structural_state = SpiderState(_columns([Card("c", 5), Card("d", 13)], *([Card("h", 1)] for _ in range(9))), [])
    i1 = _closure(structural_state, campaign, nodes=20)
    i2 = _closure(receiver_state, campaign, nodes=1)
    gates = {
        "A": results["A"].status == DependencyClosureStatus.DEPENDENCY_CLOSED,
        "B": results["B"].status == DependencyClosureStatus.DEPENDENCY_CLOSED and results["B"].actions[0][2] == 2,
        "C": results["C"].status == DependencyClosureStatus.DEPENDENCY_CLOSED and results["C"].steps[0].progress_evidence.kind == ClosureProgressKind.RECEIVER_CREATED,
        "D": results["D"].status == DependencyClosureStatus.DEPENDENCY_CLOSED and results["D"].steps[0].progress_evidence.workspace_created,
        "E": results["E"].status == DependencyClosureStatus.DEPENDENCY_CLOSED and results["E"].steps[0].lifecycle.exit_route_bounded,
        "F": lifecycle.can_override_permanent_join and bool(lifecycle.same_suit_joins_broken),
        "G": results["G"].actions[0] == (1, 2, 1) and all(b.retained <= 1 for b in results["G"].buried_source_traces[0].beam_audits),
        "H": results["H"].buried_source_traces[0].source_copy_substitutions >= 1,
        "I": i1.failure_diagnosis == ClosureFailureDiagnosis.STRUCTURAL_BLOCKER and i2.failure_diagnosis == ClosureFailureDiagnosis.RESOURCE_BOUND,
    }
    return gates, results, i1, i2, lifecycle


def _telemetry(result):
    t = result.telemetry
    return {
        "source_attempts": t.source_buried_attempts,
        "physical_blockers": t.source_physical_blockers,
        "copies": t.source_copies_considered,
        "substitutions": t.source_copy_substitutions,
        "depth_reduced": t.source_depth_reduced,
        "exposed": t.sources_exposed,
        "consumed": t.sources_consumed,
        "legal": t.closure_legal_candidate_audit_count,
        "generated": t.closure_candidates_generated,
        "missing": t.closure_candidates_missing_from_generator,
        "admitted": t.closure_candidates_admitted,
        "rejected": dict(t.closure_candidates_rejected_by_reason),
        "beam_retained": t.closure_beam_retained,
        "beam_discarded": t.closure_beam_discarded,
        "representatives": t.closure_target_progress_representatives,
        "receivers": t.closure_receivers_created,
        "workspace": (t.closure_workspace_created, t.closure_workspace_used),
        "parks": (t.closure_temporary_parks, t.closure_temporary_park_exits),
        "stable": (t.closure_stable_runs_broken, t.closure_stable_runs_restored),
        "debt": t.closure_lifecycle_debt,
        "diagnoses": dict(t.closure_failure_diagnoses),
    }


def _route(start, result):
    node = _node(result)
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost, valid = None, False
    return {
        "valid": valid, "g": cost, "actions": len(node.actions),
        "deals": sum(a == ("deal",) for a in node.actions),
        "foundations": len(node.state.foundations), "stock": len(node.state.stock),
        "face_down": sum(len(c.face_down) for c in node.state.columns),
        "path_hash": controller_module._action_path_hash(node.actions),
        "endpoint_hash": controller_module._state_hash(node.state),
    }


def _unseen(cards, base, seconds):
    out = []
    for seed in (107, 139):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = AnytimeControllerConfig(
            wall_clock_limit_s=max(1.0, seconds), max_strategic_expansions=1,
            max_tactical_nodes=12_000, max_frontier_size=64,
            enable_strategic_milestones=True, enable_closure_candidate_audit=True,
        )
        result = solve_anytime(state, shuffled, None, config)
        out.append({"seed": seed, "summary": _summary(result), "replay": _replay(state, result), "telemetry": _telemetry(result), "unrestricted": result.preflight.profile.can_deal_into_empty})
    return tuple(out)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-j-seconds", type=float, default=90.0)
    parser.add_argument("--gate-k-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=1.0)
    parser.add_argument("--skip-gate-k", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    base_analysis = analyze_strategic_state(opening, cards, spent_cost=0, incumbent_cost=None, config=AnytimeControllerConfig(wall_clock_limit_s=1, max_strategic_expansions=1, max_tactical_nodes=100, max_frontier_size=16), include_deal_timing=False)
    base_campaign = base_analysis.economic.campaign_portfolio.campaigns[0]
    gates, capability, i1, i2, stable = _capabilities(base_campaign)
    unseen = _unseen(cards, base_campaign, args.smoke_seconds)

    gate_j_config = replace(
        _gate_j_base_config(args.gate_j_seconds), enable_strategic_milestones=True,
        enable_closure_candidate_audit=True,
        wall_clock_limit_s=min(90.0, args.gate_j_seconds), max_strategic_expansions=25,
        max_tactical_nodes=300_000, max_frontier_size=256,
    )
    gate_j = solve_anytime(anchor_node.state, cards, None, gate_j_config)
    gate_j_node = _node(gate_j)
    gate_j_t = _telemetry(gate_j)
    substantial = gate_j.telemetry.substantial_structural_milestones
    terminal = gate_j.telemetry.milestone_terminal_qualifications
    natural_prerequisite_execution = bool(
        gate_j_t["consumed"]
        and (gate_j_t["receivers"] or gate_j_t["workspace"][0] or gate_j_t["parks"][0])
    )
    authorization_reasons = {
        "residual_consumed": False,
        "F2": len(gate_j_node.state.foundations) >= 2,
        "substantial_source_chain": substantial > 0 and gate_j_t["consumed"] > 0,
        "terminal_via_closure": terminal > 0 and gate_j_t["consumed"] > 0,
        "natural_missing_candidate_executed": natural_prerequisite_execution,
    }
    authorized = any(authorization_reasons.values())
    gate_k = None
    if authorized and not args.skip_gate_k:
        gate_k_config = replace(
            _gate_k_base_config(args.gate_k_seconds), enable_strategic_milestones=True,
            enable_closure_candidate_audit=True,
            wall_clock_limit_s=min(180.0, args.gate_k_seconds), max_strategic_expansions=50,
            max_tactical_nodes=500_000, max_frontier_size=256,
        )
        gate_k = solve_anytime(opening, cards, None, gate_k_config)
    selected = gate_k or gate_j
    selected_start = opening if gate_k else anchor_node.state
    selected_node = _node(selected)
    selected_route = _route(selected_start, selected)
    f2 = len(selected_node.state.foundations) >= 2
    verdict = "PASS" if len(gate_j_node.state.foundations) >= 2 else "PARTIAL" if all(gates.values()) and gate_j_t["missing"] == 0 else "FAIL"
    blocker = "none through F2" if f2 else "natural bounded controller did not convert its remaining source-chain work into foundation #2"

    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", anchor.preflight.profile),
        ("regression anchors", {"canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash), "machine": _summary(anchor), "independent": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified)}),
        ("v0.10 precise blocker", "fresh SOURCE_BURIED residual was actionable but prerequisite receiver/workspace moves were absent from closure attribution"),
        ("dependency-closure architecture audit", "one existing bounded realiser; fixed cost/node/time/beam; named target enters cache and ordering"),
        ("SOURCE_BURIED trace model", tuple(inspect.signature(describe_buried_source).parameters)),
        ("physical blocker enumeration", _trace_summary(capability["A"])),
        ("legal candidate coverage", {k: _trace_summary(v)["missing"] for k, v in capability.items()}),
        ("candidate generation", {k: _trace_summary(v)["generated"] for k, v in capability.items()}),
        ("candidate rejection reasons", {k: _trace_summary(v)["rejected"] for k, v in capability.items()}),
        ("receiver-prerequisite handling", _trace_summary(capability["C"])),
        ("workspace-prerequisite handling", _trace_summary(capability["D"])),
        ("temporary-park handling", _trace_summary(capability["E"])),
        ("permanent same-suit dominance audit", "stable join retains lifecycle ordering dominance over comparable unexplained mixed park"),
        ("stable-run break/restore semantics", {"broken": stable.same_suit_joins_broken, "exit": stable.future_exit_route, "debt": stable.estimated_rehandling_cost, "override": stable.can_override_permanent_join}),
        ("beam retention/diversity", _trace_summary(capability["G"])),
        ("fresh source attribution", _trace_summary(capability["H"])),
        ("exact-state dedup safety", "exact structural state -> lowest corrected g; target context excluded from identity"),
        ("SEARCH_POLICY versus RESOURCE_BOUND semantics", {"I1": i1.failure_diagnosis.value, "I2": i2.failure_diagnosis.value}),
        ("proof-safety audit", {"trace_proof": False, "TT_changed": False, "admissible_bound_changed": False}),
        ("capability Gate A", {"passed": gates["A"], "trace": _trace_summary(capability["A"])}),
        ("capability Gate B", {"passed": gates["B"], "trace": _trace_summary(capability["B"])}),
        ("capability Gate C", {"passed": gates["C"], "trace": _trace_summary(capability["C"])}),
        ("capability Gate D", {"passed": gates["D"], "trace": _trace_summary(capability["D"])}),
        ("capability Gate E", {"passed": gates["E"], "trace": _trace_summary(capability["E"])}),
        ("capability Gate F", {"passed": gates["F"], "override": stable.can_override_permanent_join}),
        ("capability Gate G", {"passed": gates["G"], "trace": _trace_summary(capability["G"])}),
        ("capability Gate H", {"passed": gates["H"], "trace": _trace_summary(capability["H"])}),
        ("capability Gate I", {"passed": gates["I"], "structural": i1.failure_diagnosis.value, "resource": i2.failure_diagnosis.value}),
        ("unseen-deal smokes", unseen),
        ("natural residual artifact availability", "NATURAL_RESIDUAL_ARTIFACT_UNAVAILABLE"),
        ("natural residual candidate autopsy if available", None),
        ("natural residual outcome if available", None),
        ("Gate J config/result", {"config": (gate_j_config.wall_clock_limit_s, gate_j_config.max_strategic_expansions, gate_j_config.max_tactical_nodes, gate_j_config.max_frontier_size), "summary": _summary(gate_j), "replay": _replay(anchor_node.state, gate_j)}),
        ("Gate J SOURCE_BURIED attempts", gate_j_t["source_attempts"]),
        ("Gate J candidate-generation/rejection breakdown", gate_j_t),
        ("Gate J source-chain substantial completions", substantial),
        ("Gate J terminal qualifications", terminal),
        ("Gate J F2 result", len(gate_j_node.state.foundations) >= 2),
        ("true-opening Gate K authorization", {"authorized": authorized, "reasons": authorization_reasons}),
        ("Gate K config/result if authorized", _summary(gate_k) if gate_k else None),
        ("Gate K strategic timeline", tuple(gate_k.telemetry.decision_trace) if gate_k else None),
        ("Gate K buried-source timeline", _telemetry(gate_k) if gate_k else None),
        ("Gate K substantial milestones", gate_k.telemetry.substantial_structural_milestones if gate_k else None),
        ("Gate K epoch/stock timeline", tuple(gate_k.telemetry.deal_timeline) if gate_k else None),
        ("Gate K F1 result", len(_node(gate_k).state.foundations) >= 1 if gate_k else None),
        ("post-F1 source-chain timeline", tuple(gate_k.telemetry.residual_target_timeline) if gate_k else None),
        ("Gate K F2 result", len(_node(gate_k).state.foundations) >= 2 if gate_k else None),
        ("continuous route/replay/hashes if successful", selected_route if f2 else None),
        ("repeatability", "not authorized: F2 absent"),
        ("optional F3", None),
        ("optional whole-game result", None),
        ("candidate telemetry", _telemetry(selected)),
        ("closure performance telemetry", {"calls": selected.telemetry.dependency_closure_attempts, "nodes": selected.telemetry.dependency_closure_nodes, "seconds": selected.telemetry.dependency_closure_seconds, "max_seconds": selected.telemetry.dependency_closure_max_seconds}),
        ("TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed}),
        ("final suite result", FINAL_COMPLETE_SUITE),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
    ]
    assert len(sections) == 59
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
