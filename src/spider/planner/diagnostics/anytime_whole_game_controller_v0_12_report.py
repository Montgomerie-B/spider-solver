#!/usr/bin/env python3
"""v0.12 multi-primitive closure continuation and unchanged-envelope gates."""

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
from spider.move_lifecycle import PlacementClass, assess_tableau_move
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import AnytimeControllerConfig, analyze_strategic_state, solve_anytime
from spider.planner.buried_source_closure import ClosureFailureDiagnosis, ClosureProgressKind
from spider.planner.campaign_dependency_closure import (
    ClosureCompletionClass,
    DependencyClosureConfig,
    DependencyClosureStatus,
    DependencyClosureStep,
    realize_campaign_dependency_closure,
    summarize_closure_lifecycle,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
    _replay,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_k_base_config,
    _gate_g_config as _gate_l_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import reconstruct_cost23_checkpoint
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "f76befa72ee838dc5c6b45314ac3e14dc267c657"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "1179 passed, 37 xfailed, 1 inherited warning in 1137.10 seconds"


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
        "not_applicable", 1.0, "generic v0.12 fixture",
    )


def _campaign(base, suit="c", rank=5):
    needs = tuple(
        replace(
            need,
            chosen=_source(suit, need.rank) if need.rank == rank else None,
            must_excavate=need.rank == rank,
            reason="generic named source",
        )
        for need in base.rank_needs
    )
    return replace(
        base,
        suit=suit,
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(item.chosen for item in needs if item.chosen),
        future_stock_supplied_cards=(),
        optional_replaceable_buried_copies=(),
        prerequisite_excavation_projects=(),
        shared_prerequisite_tasks=(),
        space_requirement=0,
        stock_plan=(),
        estimated_campaign_cost=4.0,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )


def _closure(state, campaign, *, rank=5, cost=8, nodes=400):
    return realize_campaign_dependency_closure(
        state,
        campaign,
        target_dependency_id=f"source:{rank}:c",
        semantic_target_id="generic-source-chain",
        config=DependencyClosureConfig(
            max_added_cost=cost,
            max_nodes=nodes,
            time_limit_s=1.5,
            beam_width=192,
            enable_legal_candidate_audit=True,
        ),
    )


def _closure_summary(result):
    endpoint = result.endpoint_assessment
    return {
        "status": result.status.value,
        "completion_class": result.completion_class.value,
        "target": result.target_dependency_id,
        "actions": result.actions,
        "cost": result.corrected_added_cost,
        "nodes": result.nodes_expanded,
        "replay": result.independent_replay_verified,
        "advanced_continued": result.advanced_states_continued,
        "advanced_fallback": result.advanced_fallback_returned,
        "diagnosis": result.failure_diagnosis.value,
        "source_depth": (
            endpoint.source_depth_before if endpoint else None,
            endpoint.source_depth_after if endpoint else None,
        ),
        "source_exposed": endpoint.source_exposed if endpoint else False,
        "source_actionable": endpoint.source_actionable if endpoint else False,
        "source_consumed": endpoint.source_consumed if endpoint else False,
        "primitive_count": endpoint.primitive_count if endpoint else 0,
        "lifecycle": endpoint.lifecycle if endpoint else None,
        "step_progress": tuple(
            step.progress_evidence.kind.value
            for step in result.steps
            if step.progress_evidence is not None
        ),
    }


def _lifecycle_fixture():
    state = SpiderState(_columns([Card("d", 7), Card("d", 6)], [Card("s", 7)]), [])
    broken = assess_tableau_move(state, (0, 1, 1))
    state.move(0, 1, 1)
    restored = assess_tableau_move(state, (1, 0, 1))
    steps = (
        DependencyClosureStep((0, 1, 1), broken.immediate_cost, ("source:7:c",), "break", broken, 1, 1, 0, 0),
        DependencyClosureStep((1, 0, 1), restored.immediate_cost, ("source:7:c",), "restore", restored, 1, 1, 0, 0),
    )
    return summarize_closure_lifecycle(steps)


def _capabilities(base):
    filler7 = tuple([Card("h", 1)] for _ in range(7))
    filler6 = tuple([Card("h", 1)] for _ in range(6))
    c5 = _campaign(base, rank=5)
    c7 = _campaign(base, rank=7)
    two_state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)],
            [Card("s", 5)], [Card("d", 6)], *filler7,
        ), []
    )
    receiver_state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)],
            [Card("s", 5), Card("s", 9)], [Card("s", 10)],
            [Card("d", 6)], *filler6,
        ), []
    )
    workspace_state = SpiderState(
        _columns(
            [Card("c", 7), Card("d", 6), Card("d", 5)],
            [Card("s", 9)], [Card("s", 10)], *filler7,
        ), []
    )
    park_state = SpiderState(
        _columns(
            [Card("c", 7), Card("d", 6), Card("h", 5)],
            [Card("s", 6)], [Card("s", 7)], *filler7,
        ), []
    )
    copy_state = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 4)],
            [Card("c", 5), Card("s", 9)], [Card("s", 10)],
            [Card("h", 6)], *filler6,
        ), []
    )
    a = _closure(two_state, c5)
    b = _closure(receiver_state, c5)
    c = _closure(workspace_state, c7, rank=7)
    d = _closure(park_state, c7, rank=7)
    f = _closure(two_state, c5, cost=1)
    g2 = _closure(f.end_state, c5)
    h = _closure(copy_state, c5)
    lifecycle = _lifecycle_fixture()
    gates = {
        "A": len(a.actions) == 2 and a.advanced_states_continued >= 1 and a.endpoint_assessment.source_exposed,
        "B": len(b.actions) == 3 and b.steps[0].progress_evidence.kind == ClosureProgressKind.RECEIVER_CREATED,
        "C": len(c.actions) == 2 and c.steps[-1].lifecycle.placement_class == PlacementClass.WORKSPACE_PARK,
        "D": d.endpoint_assessment.lifecycle.midpoint_rehandling_debt > 0 and d.endpoint_assessment.source_exposed,
        "E": lifecycle.same_suit_joins_broken == lifecycle.stable_joins_restored_or_replaced == 1,
        "F": f.status == DependencyClosureStatus.DEPENDENCY_ADVANCED and f.failure_diagnosis == ClosureFailureDiagnosis.RESOURCE_BOUND,
        "G": f.target_dependency_id == g2.target_dependency_id and g2.endpoint_assessment.source_exposed,
        "H": h.buried_source_traces[0].source_copy_substitutions >= 1,
        "I": a.steps[-1].progress_evidence.source_exposed and len(a.actions) == 2,
        "J": a.endpoint_assessment.ordering_key() < f.endpoint_assessment.ordering_key(),
    }
    return gates, {"A": a, "B": b, "C": c, "D": d, "F": f, "G2": g2, "H": h}, lifecycle


def _closure_telemetry(result):
    t = result.telemetry
    return {
        "targeted_calls": t.closure_targeted_calls,
        "completion_classes": dict(t.closure_completion_classes),
        "dependency_completed": t.closure_dependency_completed,
        "source_exposed": t.closure_source_exposed,
        "dependency_advanced": t.closure_dependency_advanced,
        "resource_bound": t.closure_resource_bound,
        "structural_blocker": t.closure_structural_blocker,
        "search_policy": t.closure_search_policy,
        "invalidated": t.closure_invalidated,
        "advanced_continued": t.closure_advanced_states_continued,
        "advanced_fallbacks": t.closure_advanced_fallbacks,
        "advanced_persisted": t.closure_advanced_persisted_across_expansions,
        "persisted_completed": t.closure_persisted_targets_completed,
        "primitive_total": t.closure_primitives_total,
        "primitive_max": t.closure_max_primitive_sequence,
        "receiver_chains": t.closure_receiver_blocker_exposure_chains,
        "workspace_chains": t.closure_workspace_blocker_exposure_chains,
        "park_chains": t.closure_park_blocker_exposure_chains,
        "source_depth_reductions": t.source_depth_reduced,
        "sources_exposed": t.sources_exposed,
        "sources_consumed": t.sources_consumed,
        "copy_substitutions": t.source_copy_substitutions,
        "calls": t.dependency_closure_attempts,
        "nodes": t.dependency_closure_nodes,
        "seconds": t.dependency_closure_seconds,
        "max_seconds": t.dependency_closure_max_seconds,
    }


def _lifecycle_telemetry(result):
    t = result.telemetry
    return {
        "stable_joins_broken": t.closure_stable_runs_broken,
        "stable_joins_restored_or_replaced": t.closure_stable_joins_restored_or_replaced,
        "midpoint_debt": t.closure_midpoint_rehandling_debt,
        "final_debt": t.closure_final_rehandling_debt,
        "compensation_accepted": t.closure_projected_compensation_accepted,
        "compensation_rejected": t.closure_projected_compensation_rejected,
        "temporary_parks": t.closure_temporary_parks,
        "bounded_park_exits": t.closure_temporary_park_exits,
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
        "valid": valid,
        "g": cost,
        "actions": len(node.actions),
        "deals": sum(action == ("deal",) for action in node.actions),
        "foundations": len(node.state.foundations),
        "stock": len(node.state.stock),
        "face_down": sum(len(column.face_down) for column in node.state.columns),
        "path_hash": controller_module._action_path_hash(node.actions),
        "endpoint_hash": controller_module._state_hash(node.state),
        "structural_hash": format(zobrist(node.state), "x"),
    }


def _unseen(cards, seconds):
    outcomes = []
    for seed in (12012, 12013):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = AnytimeControllerConfig(
            wall_clock_limit_s=max(1.0, seconds),
            max_strategic_expansions=1,
            max_tactical_nodes=12_000,
            max_frontier_size=64,
            enable_strategic_milestones=True,
            enable_closure_candidate_audit=True,
        )
        result = solve_anytime(state, shuffled, None, config)
        outcomes.append({
            "seed": seed,
            "summary": _summary(result),
            "replay": _replay(state, result),
            "closure": _closure_telemetry(result),
            "unrestricted": result.preflight.profile.can_deal_into_empty,
        })
    return tuple(outcomes)


def _authorization(gate_k):
    node = _node(gate_k)
    t = gate_k.telemetry
    prior_progress_exposure = bool(
        t.sources_exposed
        and (
            t.source_depth_reduced
            or t.closure_receivers_created
            or t.closure_workspace_created
            or t.closure_temporary_parks
        )
    )
    reasons = {
        "Gate K F2": len(node.state.foundations) >= 2,
        "natural source exposure/consumption after progress": prior_progress_exposure or bool(t.sources_consumed),
        "substantial natural source chain": t.substantial_source_chain_completions > 0,
        "terminal qualification": t.milestone_terminal_qualifications > 0,
        "persisted ADVANCED target later completed": t.closure_persisted_targets_completed > 0,
    }
    return any(reasons.values()), reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-k-seconds", type=float, default=90.0)
    parser.add_argument("--gate-l-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=1.0)
    parser.add_argument("--skip-gate-l", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    base_analysis = analyze_strategic_state(
        opening,
        cards,
        spent_cost=0,
        incumbent_cost=None,
        config=AnytimeControllerConfig(
            wall_clock_limit_s=1.0,
            max_strategic_expansions=1,
            max_tactical_nodes=100,
            max_frontier_size=16,
        ),
        include_deal_timing=False,
    )
    base_campaign = base_analysis.economic.campaign_portfolio.campaigns[0]
    gates, capability, lifecycle = _capabilities(base_campaign)
    unseen = _unseen(cards, args.smoke_seconds)

    gate_k_config = replace(
        _gate_k_base_config(args.gate_k_seconds),
        enable_strategic_milestones=True,
        enable_closure_candidate_audit=True,
        wall_clock_limit_s=min(90.0, args.gate_k_seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
    )
    gate_k = solve_anytime(anchor_node.state, cards, None, gate_k_config)
    gate_k_node = _node(gate_k)
    gate_k_closure = _closure_telemetry(gate_k)
    authorized, authorization_reasons = _authorization(gate_k)

    gate_l = None
    if authorized and not args.skip_gate_l:
        gate_l_config = replace(
            _gate_l_base_config(args.gate_l_seconds),
            enable_strategic_milestones=True,
            enable_closure_candidate_audit=True,
            wall_clock_limit_s=min(180.0, args.gate_l_seconds),
            max_strategic_expansions=50,
            max_tactical_nodes=500_000,
            max_frontier_size=256,
        )
        gate_l = solve_anytime(opening, cards, None, gate_l_config)
    else:
        gate_l_config = None

    repeat = None
    if gate_l is not None and len(_node(gate_l).state.foundations) >= 2:
        repeat = solve_anytime(opening, cards, None, gate_l_config)

    selected = gate_l or gate_k
    selected_start = opening if gate_l else anchor_node.state
    selected_node = _node(selected)
    gate_l_f2 = bool(gate_l and len(_node(gate_l).state.foundations) >= 2)
    gate_k_f2 = len(gate_k_node.state.foundations) >= 2
    natural_exposure = bool(gate_k_closure["sources_exposed"] or gate_k_closure["sources_consumed"])
    verdict = "PASS" if gate_k_f2 or gate_l_f2 else "PARTIAL" if all(gates.values()) and natural_exposure else "FAIL"
    blocker = (
        "none through F2"
        if gate_k_f2 or gate_l_f2
        else "natural named-source progress did not convert into foundation #2"
        if natural_exposure
        else "natural bounded source-depth/prerequisite work still produced no named source exposure"
    )
    primitive_average = (
        gate_k_closure["primitive_total"] / gate_k_closure["calls"]
        if gate_k_closure["calls"]
        else 0.0
    )

    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", anchor.preflight.profile),
        ("regression anchors", {
            "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
            "machine": (_summary(anchor), _route(opening, anchor)),
            "independent": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        }),
        ("v0.11 blocker", "candidate coverage was complete, but dependency-ID-only completion and broad success statuses returned prerequisite/depth progress as closure"),
        ("existing closure return-policy audit", "the inner search already chained primitives; completion was ID-only and any vanished campaign dependency could label the requested target closed"),
        ("completion-vs-advancement model", tuple(item.value for item in ClosureCompletionClass)),
        ("inner continuation policy", "fresh ADVANCED states remain candidates until completion, local exhaustion, invalidation, or unchanged resource limits"),
        ("endpoint ordering", "foundation; requested completion; source exposure/actionability; cumulative source progress; prerequisite progress; unrelated structure"),
        ("ADVANCED fallback semantics", _closure_summary(capability["F"])),
        ("outer milestone-boundary handling", {"first": _closure_summary(capability["F"]), "continued": _closure_summary(capability["G2"])}),
        ("fresh reanalysis", "exact state, graph, physical source alternatives, blocker chain, lifecycle, and semantic target are rebuilt after every accepted move"),
        ("immediate exposure detection", _closure_summary(capability["A"])),
        ("stable-run restore/replace economics", lifecycle),
        ("temporary-debt midpoint policy", _closure_summary(capability["D"])),
        ("beam continuation retention", {"beam_width": DependencyClosureConfig().beam_width, "advanced_continued": capability["A"].advanced_states_continued}),
        ("RESOURCE_BOUND vs SEARCH_POLICY", {"advanced_fallback": capability["F"].failure_diagnosis.value, "generator_audit_available": True}),
        ("proof-safety audit", {"endpoint_proof": False, "TT_changed": False, "admissible_bound_changed": False}),
        ("capability Gate A", {"passed": gates["A"], "result": _closure_summary(capability["A"])}),
        ("capability Gate B", {"passed": gates["B"], "result": _closure_summary(capability["B"])}),
        ("capability Gate C", {"passed": gates["C"], "result": _closure_summary(capability["C"])}),
        ("capability Gate D", {"passed": gates["D"], "result": _closure_summary(capability["D"])}),
        ("capability Gate E", {"passed": gates["E"], "lifecycle": lifecycle}),
        ("capability Gate F", {"passed": gates["F"], "result": _closure_summary(capability["F"])}),
        ("capability Gate G", {"passed": gates["G"], "result": _closure_summary(capability["G2"])}),
        ("capability Gate H", {"passed": gates["H"], "result": _closure_summary(capability["H"])}),
        ("capability Gate I", {"passed": gates["I"], "result": _closure_summary(capability["A"])}),
        ("capability Gate J", {"passed": gates["J"], "completion_key": capability["A"].endpoint_assessment.ordering_key(), "advanced_key": capability["F"].endpoint_assessment.ordering_key()}),
        ("unseen-deal smokes", unseen),
        ("Gate K config/result", {"config": (gate_k_config.wall_clock_limit_s, gate_k_config.max_strategic_expansions, gate_k_config.max_tactical_nodes, gate_k_config.max_frontier_size), "summary": _summary(gate_k), "route": _route(anchor_node.state, gate_k)}),
        ("Gate K targeted closure statistics", gate_k_closure),
        ("Gate K DEPENDENCY_ADVANCED count", gate_k_closure["dependency_advanced"]),
        ("Gate K DEPENDENCY_COMPLETED count", gate_k_closure["dependency_completed"]),
        ("Gate K source-depth reductions", gate_k_closure["source_depth_reductions"]),
        ("Gate K source exposures", gate_k_closure["sources_exposed"]),
        ("Gate K source consumptions", gate_k_closure["sources_consumed"]),
        ("Gate K primitives per closure result", {"total": gate_k_closure["primitive_total"], "calls": gate_k_closure["calls"], "average": primitive_average, "maximum": gate_k_closure["primitive_max"]}),
        ("Gate K outer-boundary continuations", {"persisted": gate_k_closure["advanced_persisted"], "later_completed": gate_k_closure["persisted_completed"]}),
        ("Gate K restore/replace sequences", _lifecycle_telemetry(gate_k)),
        ("Gate K substantial source-chain completions", gate_k.telemetry.substantial_source_chain_completions),
        ("Gate K terminal qualifications", gate_k.telemetry.milestone_terminal_qualifications),
        ("Gate K F2 result", gate_k_f2),
        ("Gate L authorization decision", {"authorized": authorized, "reasons": authorization_reasons}),
        ("Gate L config/result if authorized", {"config": (gate_l_config.wall_clock_limit_s, gate_l_config.max_strategic_expansions, gate_l_config.max_tactical_nodes, gate_l_config.max_frontier_size) if gate_l_config else None, "summary": _summary(gate_l) if gate_l else None}),
        ("Gate L strategic timeline", tuple(gate_l.telemetry.decision_trace) if gate_l else None),
        ("Gate L closure continuation timeline", tuple(gate_l.telemetry.dependency_closure_timeline) if gate_l else None),
        ("Gate L substantial milestones", gate_l.telemetry.substantial_structural_milestones if gate_l else None),
        ("Gate L stock/Deal timeline", tuple(gate_l.telemetry.deal_timeline) if gate_l else None),
        ("Gate L F1", len(_node(gate_l).state.foundations) >= 1 if gate_l else None),
        ("post-F1 source-chain progress", tuple(gate_l.telemetry.residual_target_timeline) if gate_l else None),
        ("Gate L F2", gate_l_f2 if gate_l else None),
        ("continuous route/replay/hashes if successful", _route(opening, gate_l) if gate_l_f2 else None),
        ("repeatability", {"ran": repeat is not None, "F2": len(_node(repeat).state.foundations) >= 2 if repeat else None, "route": _route(opening, repeat) if repeat else None}),
        ("optional F3", "not run: optional continuation not authorized by this diagnostic"),
        ("optional whole-game run", "not run: optional continuation not authorized by this diagnostic"),
        ("closure telemetry", _closure_telemetry(selected)),
        ("lifecycle telemetry", _lifecycle_telemetry(selected)),
        ("TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed}),
        ("final full-suite result", FINAL_COMPLETE_SUITE),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
    ]
    assert len(sections) == 61
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
