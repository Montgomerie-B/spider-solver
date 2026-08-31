#!/usr/bin/env python3
"""v0.15 completion-harvest selection and bounded cash-out audit."""

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
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicCreditLevel,
    StrategicSearchNode,
    StrategicTranspositionTable,
    _node_priority,
    _reserve_completion_representative,
    analyze_stage0_state,
    solve_anytime,
)
from spider.planner.completion_cash_out import (
    CompletionCashOutDisposition,
    CompletionCashOutOpportunity,
    CompletionCashOutStatus,
    CompletionCashOutTrace,
    CompletionHarvestAssessment,
    CompletionHarvestKind,
    CompletionStructuralMetrics,
    assess_completion_harvest,
    make_completion_cash_out_opportunity,
    rank_completion_opportunities,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_14_report import (
    _completion_funnel,
    _resource_summary,
    _route,
    _source_summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_q_base_config,
    _gate_g_config as _gate_r_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.source_completion import (
    SourceCompletionPropagationTrace,
    SourceCompletionStage,
    physical_source_identity,
    semantic_source_requirement,
    source_completion_event,
)
from spider.planner.tactical_resource_allocator import TacticalResourceAllocatorConfig
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "c0a959fd60fba8dc4d307bdc6b38c675a8290905"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = (
    "1378 passed, 37 expected historical xfails, 1 inherited warning "
    "in 1099.00 seconds"
)


def _section(number, title, value):
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _fixture_state():
    return SpiderState(
        _columns(
            [Card("c", 5)], [Card("c", 6)], [Card("d", 6)],
            *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )


def _event(state, *, target=("generic", "cash-out"), dependency="source:5:c"):
    requirement = semantic_source_requirement(target, dependency, Card("c", 5))
    physical = physical_source_identity(
        Card("c", 5), dependency_id=dependency, copy_ordinal=1,
        zone="face_up", column=0, offset=0, face_up=True, blocker_depth=0,
    )
    return source_completion_event(
        semantic_target_fingerprint=target,
        dependency_id=dependency,
        original_dependency_type="SOURCE_BURIED",
        fresh_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED",
        physical_source=physical,
        requirement=requirement,
        state=state,
        actions=(),
        completion_class="SOURCE_EXPOSED",
        source_depth_before=1,
        source_depth_after=0,
        exposed=True,
        actionable=True,
        consumed=False,
        integrated=False,
        evidence_provenance=("generic v0.15 capability fixture",),
    )


def _trace(state, **kwargs):
    return SourceCompletionPropagationTrace(_event(state, **kwargs)).advance(
        SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION
    )


def _metrics(state, g=3):
    stage0 = analyze_stage0_state(state, spent_cost=g, incumbent_cost=None)
    return CompletionStructuralMetrics(
        g, stage0.foundation_count, stage0.stable_same_suit_joins,
        stage0.mixed_suit_boundaries, 1, 1, 0, 0, 0, 0,
        len(stage0.empty_columns), stage0.face_down_count, 0,
        stage0.stock_count, 0, stage0.rehandling_debt, 0, 0,
        stage0.legal_move_count,
    )


def _opportunity(state, *, g=3, traces=None):
    value = make_completion_cash_out_opportunity(
        state,
        corrected_g=g,
        traces=tuple(traces or (_trace(state),)),
        successor_family="dependency_closure",
        metrics=_metrics(state, g),
        exact_tt_admitted=True,
        independently_replay_verified=True,
    )
    if value is None:
        raise AssertionError("generic completion fixture did not qualify")
    return value


def _cash_out_node(state, node_id, g, opportunity=None):
    return StrategicSearchNode(
        node_id, state.clone(), g, (), None, None, 1,
        StrategicCreditLevel.CLEAN, None,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
        completion_cash_out=opportunity,
    )


def _capabilities():
    state = _fixture_state()
    opportunity = _opportunity(state)
    tt = StrategicTranspositionTable(); tt.admit(state, 3)
    completion_node = _cash_out_node(state, 2, 3, opportunity)
    conservative_node = _cash_out_node(state, 1, 1)
    telemetry = ControllerTelemetry()
    frontier = _reserve_completion_representative(
        (((9,), 2, completion_node), ((0,), 1, conservative_node)),
        tt=tt, spent_event_ids=(), telemetry=telemetry,
    )
    representative = next(
        item[2].completion_cash_out for item in frontier
        if item[2].completion_cash_out is not None
        and item[2].completion_cash_out.status == CompletionCashOutStatus.RESERVED
    )
    end = state.clone(); end.move(0, 1, 1, rules=MW_RULES)
    harvest = assess_completion_harvest(
        representative, state, end,
        downstream_successor_generated=True,
        downstream_successor_admitted=True,
        dependency_chain_advanced=True,
    )
    no_harvest = assess_completion_harvest(
        representative, state, state.clone(),
        downstream_successor_generated=True,
        downstream_successor_admitted=True,
    )
    second_trace = _trace(
        state, target=("generic", "cash-out-second"),
        dependency="source:5:c:second",
    )
    multi = _opportunity(state, traces=(_trace(state), second_trace))
    spent = replace(
        representative, status=CompletionCashOutStatus.SPENT,
        cash_out_spent=True,
    )
    duplicate_tt = StrategicTranspositionTable()
    duplicate_safe = bool(
        duplicate_tt.admit(state, 5)
        and duplicate_tt.admit(state.clone(), 4)
        and not duplicate_tt.admit(state.clone(), 5)
    )
    gates = {
        "A": representative.status == CompletionCashOutStatus.RESERVED and len(frontier) == 2,
        "B": not spent.eligible() and not rank_completion_opportunities((opportunity,), spent_event_ids=opportunity.event_ids),
        "C": duplicate_safe and canonical_state_key(state) == canonical_state_key(state.clone()),
        "D": CompletionHarvestKind.SOURCE_CONSUMED in harvest.harvest_kinds and CompletionHarvestKind.SOURCE_INTEGRATED in harvest.harvest_kinds,
        "E": _event(state).fresh_dependency_type == "SOURCE_EXPOSED_BUT_BLOCKED" and CompletionHarvestKind.DEPENDENCY_CHAIN_ADVANCE in harvest.harvest_kinds,
        "F": no_harvest.harvest_kinds == (CompletionHarvestKind.NO_DOWNSTREAM_HARVEST,) and not spent.eligible(),
        "G": {item[1] for item in frontier} == {1, 2} and not representative.proof_pruning_allowed,
        "H": len(multi.events) == 2 and len(rank_completion_opportunities((multi,))) == 1,
        "I": MW_RULES.can_deal_into_empty and CompletionHarvestKind.EPOCH_PREPARATION not in assess_completion_harvest(representative, state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, epoch_prepared=True, action_is_deal=True).harvest_kinds,
        "J": CompletionHarvestKind.TERMINAL_QUALIFICATION in assess_completion_harvest(representative, state, state.clone(), downstream_successor_generated=True, downstream_successor_admitted=True, terminal_qualified=True).harvest_kinds,
        "K": len(frontier) == 2 and sum(item[2].completion_cash_out is not None and item[2].completion_cash_out.status == CompletionCashOutStatus.RESERVED for item in frontier) == 1,
        "L": _node_priority(conservative_node) < _node_priority(replace(completion_node, completion_cash_out=spent)),
    }
    return gates, {
        "representative": representative,
        "harvest": harvest,
        "no_harvest": no_harvest,
        "multi_event": multi,
        "TT": (duplicate_tt.new_entries, duplicate_tt.improvements, duplicate_tt.suppressions),
    }


def _cash_out_funnel(result):
    t = result.telemetry
    return {
        "targeted": t.dependency_closure_attempts,
        "trace_completed": t.source_trace_completions,
        "controller_admitted": t.source_controller_admitted_completions,
        "admitted_completion_states": t.admitted_completion_states,
        "cash_out_qualified": t.completion_cash_out_qualified,
        "representatives_reserved": t.completion_representatives_reserved,
        "representatives_expanded": t.completion_representatives_expanded,
        "expired_before_expansion": t.completion_representatives_expired_before_expansion,
        "cash_out_spent": t.completion_cash_out_spent,
        "downstream_successors_admitted": t.completion_ordinary_continuations,
        "source_consumed": t.completion_source_consumed,
        "source_integrated": t.completion_source_integrated,
        "source_chain_milestones": t.substantial_source_chain_completions,
        "interval_milestones": t.substantial_interval_completions,
        "terminal_qualifications": t.milestone_terminal_qualifications,
        "foundations": len(_node(result).state.foundations),
    }


def _selection_rows(result):
    return tuple(
        {
            "opportunity": item.opportunity_id,
            "events": item.event_ids,
            "targets": tuple(map(repr, item.semantic_targets)),
            "state": item.exact_state_hash,
            "g": item.corrected_g,
            "family": item.successor_family,
            "metrics": item.structural_metrics,
            "status": item.qualifying_status.value,
            "rank": item.representative_rank,
            "competing_state": item.competing_normal_state_hash,
            "competing_g": item.competing_normal_g,
            "trimmed": item.frontier_trimmed,
            "expanded": item.selected_for_expansion,
            "spent": item.cash_out_spent,
            "disposition": item.disposition.value,
            "reason": item.reason,
            "harvest": tuple(value.value for value in item.downstream_result),
        }
        for item in result.telemetry.completion_selection_traces
    )


def _selection_summary(result):
    t = result.telemetry
    return {
        "admitted": t.admitted_completion_states,
        "admitted_but_freshly_nonqualifying": t.completion_nonqualifying_admitted,
        "qualified": t.completion_cash_out_qualified,
        "reserved": t.completion_representatives_reserved,
        "expanded": t.completion_representatives_expanded,
        "expired_before": t.completion_representatives_expired_before_expansion,
        "spent": t.completion_cash_out_spent,
        "admitted_not_selected": t.completion_admitted_not_selected,
        "exact_duplicate_suppressions": t.completion_exact_duplicate_suppressions,
        "invalidated": t.completion_invalidated_representatives,
        "ordinary_slots_displaced": t.completion_representative_displaced_ordinary_slots,
        "selection_seconds": t.completion_selection_seconds,
    }


def _harvest_summary(result):
    t = result.telemetry
    return {
        "assessments": t.completion_harvest_assessments,
        "by_kind": dict(t.completion_harvest_by_kind),
        "by_suit": dict(t.completion_harvest_by_suit),
        "source_consumed": t.completion_source_consumed,
        "source_integrated": t.completion_source_integrated,
        "no_downstream_harvest": t.completion_no_downstream_harvest,
        "ordinary_continuations": t.completion_ordinary_continuations,
        "branch_abandoned": t.completion_branches_abandoned,
        "deal_admitted_after_cash_out": t.completion_deals_admitted_after_cash_out,
        "deal_chosen_after_cash_out": t.completion_deals_chosen_after_cash_out,
        "terminal_paths": t.completion_terminal_paths,
    }


def _unseen(cards, seconds):
    rows = []
    for seed in (15015, 15051):
        shuffled = list(cards); random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = AnytimeControllerConfig(
            wall_clock_limit_s=max(2.0, seconds), max_strategic_expansions=3,
            max_tactical_nodes=36_000, max_frontier_size=64,
            enable_tactical_resource_allocation=True,
            enable_strategic_milestones=True,
            enable_target_grant_lineage=True,
            enable_closure_candidate_audit=True,
        )
        result = solve_anytime(state, shuffled, None, config)
        route = _route(state, result)
        rows.append({
            "seed": seed,
            "summary": _summary(result),
            "route": route,
            "cash_out": _cash_out_funnel(result),
            "selection": _selection_summary(result),
            "harvest": _harvest_summary(result),
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "deal_alternatives": result.telemetry.deal_successors_generated,
            "raw_alternative": "RAW_TABLEAU_MOVE" in result.telemetry.successor_kinds,
            "construction": result.telemetry.same_suit_construction_opportunities,
            "replay_valid": bool(route and route["valid"]),
        })
    return tuple(rows)


def _authorization(gate_q):
    t = gate_q.telemetry
    kinds = t.completion_harvest_by_kind
    reasons = {
        "Gate Q F2": len(_node(gate_q).state.foundations) >= 2,
        "natural cash-out consumed/integrated source": bool(t.completion_source_consumed or t.completion_source_integrated),
        "natural cash-out advanced source chain": bool(kinds.get(CompletionHarvestKind.DEPENDENCY_CHAIN_ADVANCE.value) or t.substantial_source_chain_completions),
        "terminal qualification followed cash-out": bool(kinds.get(CompletionHarvestKind.TERMINAL_QUALIFICATION.value) or kinds.get(CompletionHarvestKind.FOUNDATION_REMOVAL.value)),
        "v0.14 admitted-but-unselected class corrected": t.completion_representatives_expanded > 0,
    }
    return any(reasons.values()), reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-q-seconds", type=float, default=90.0)
    parser.add_argument("--gate-r-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=3.0)
    parser.add_argument("--skip-gate-r", action="store_true")
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    if (
        anchor_node.g != 21
        or len(anchor_node.state.foundations) != 1
        or controller_module._action_path_hash(anchor_node.actions) != "924bfd20deac96af"
    ):
        raise AssertionError("machine F1 anchor regressed")
    independent = reconstruct_cost23_checkpoint()
    gates, capability = _capabilities()
    if not all(gates.values()):
        raise AssertionError(f"v0.15 capability gate failed: {gates}")
    unseen = _unseen(cards, args.smoke_seconds)

    gate_q_config = replace(
        _gate_q_base_config(args.gate_q_seconds),
        enable_tactical_resource_allocation=True,
        enable_strategic_milestones=True,
        enable_target_grant_lineage=True,
        enable_closure_candidate_audit=True,
        wall_clock_limit_s=min(90.0, args.gate_q_seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
    )
    gate_q = solve_anytime(anchor_node.state, cards, None, gate_q_config)
    authorized, authorization_reasons = _authorization(gate_q)

    gate_r = None
    gate_r_config = None
    if authorized and not args.skip_gate_r:
        gate_r_config = replace(
            _gate_r_base_config(args.gate_r_seconds),
            enable_tactical_resource_allocation=True,
            enable_strategic_milestones=True,
            enable_target_grant_lineage=True,
            enable_closure_candidate_audit=True,
            wall_clock_limit_s=min(180.0, args.gate_r_seconds),
            max_strategic_expansions=50,
            max_tactical_nodes=500_000,
            max_frontier_size=256,
        )
        gate_r = solve_anytime(opening, cards, None, gate_r_config)

    repeat = None
    if gate_r is not None and len(_node(gate_r).state.foundations) >= 2:
        repeat = solve_anytime(opening, cards, None, gate_r_config)

    selected = gate_r or gate_q
    gate_q_f2 = len(_node(gate_q).state.foundations) >= 2
    gate_r_f1 = bool(gate_r and len(_node(gate_r).state.foundations) >= 1)
    gate_r_f2 = bool(gate_r and len(_node(gate_r).state.foundations) >= 2)
    natural_expansion = gate_q.telemetry.completion_representatives_expanded > 0
    natural_harvest = any(
        name != CompletionHarvestKind.NO_DOWNSTREAM_HARVEST.value and count
        for name, count in gate_q.telemetry.completion_harvest_by_kind.items()
    )
    verdict = (
        "STRONG PASS"
        if gate_r_f2 and repeat is not None and len(_node(repeat).state.foundations) >= 2
        else "PASS"
        if gate_q_f2 or gate_r_f2
        else "PARTIAL"
        if natural_expansion and natural_harvest
        else "FAIL"
    )
    if natural_expansion and natural_harvest and not (gate_q_f2 or gate_r_f2):
        architecture_decision = (
            "B. Local execution machinery demonstrated admitted completion -> one fresh expansion -> "
            "genuine harvest; stop local micro-sprints and move next to the whole-deal backward/forward scheduler."
        )
        blocker = "bounded local cash-out works, but the resulting ordinary continuation still does not schedule enough whole-deal structure to reach F2"
    elif not natural_expansion:
        architecture_decision = "A. One narrow correctness fix remains justified at completion representative selection/expansion."
        blocker = "a natural admitted completion still did not receive its bounded fresh expansion"
    else:
        architecture_decision = "A. The representative expands, but natural downstream harvest was not demonstrated; audit the narrow harvest/consumption correctness boundary before scheduling."
        blocker = "natural completion representatives expand, but their fresh descendants produce no verified structural harvest"

    gate_q_route = _route(anchor_node.state, gate_q, offset=21)
    gate_r_route = _route(opening, gate_r)
    tier_fingerprint = TacticalResourceAllocatorConfig().fingerprint
    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", anchor.preflight.profile),
        ("regression anchors", {
            "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
            "machine_F1": (_summary(anchor), _route(opening, anchor)),
            "independent_F1": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        }),
        ("v0.14 exact blocker", "typed completion reached exact-TT-admitted lazy nodes, but ordinary queue priority supplied no completion-specific next-expansion opportunity"),
        ("post-TT strategic selection map", "successor -> exact TT -> admitted lazy node -> completion qualification -> one in-capacity representative -> normal fresh Stage-1 expansion -> ordinary descendants"),
        ("completion cash-out model", tuple(CompletionCashOutOpportunity.__dataclass_fields__)),
        ("qualifying-completion semantics", "replay-valid exact-TT admission, strong source event, exact event/state match, newly admitted and not already spent"),
        ("one-representative invariant", "at most one strongest completion representative across the live strategic frontier; existing width only"),
        ("cash-out window", "one ordinary strategic expansion; no additional tactical grant, expansion, persistence or terminal resource"),
        ("no-sunk-cost guarantee", "cash_out_spent ends special treatment immediately; all descendants use ordinary economics"),
        ("downstream harvest classification", tuple(item.value for item in CompletionHarvestKind)),
        ("source consumption/integration path", capability["harvest"]),
        ("follow-on dependency handling", "SOURCE_BURIED remains satisfied while SOURCE_EXPOSED_BUT_BLOCKED is freshly evaluated as distinct follow-on debt"),
        ("structural economics comparison", tuple(CompletionStructuralMetrics.__dataclass_fields__)),
        ("exact-TT safety", {"identity_metadata": False, "lower_g_fixture": capability["TT"]}),
        ("representative deduplication", {"geometry_key": capability["multi_event"].geometry_key, "representatives": len(rank_completion_opportunities((capability["multi_event"],)))}),
        ("post-admission selection-loss diagnosis", CompletionCashOutDisposition.COMPLETION_ADMITTED_NOT_SELECTED.value),
        ("performance/resource audit", {"tier_fingerprint": tier_fingerprint, "frontier": 256, "persistence": 3, "selection_pass_is_shallow": True}),
        ("proof-safety audit", {"proof_authority": False, "TT_identity_changed": False, "admissible_bound_changed": False}),
        ("capability Gate A", gates["A"]),
        ("capability Gate B", gates["B"]),
        ("capability Gate C", gates["C"]),
        ("capability Gate D", gates["D"]),
        ("capability Gate E", gates["E"]),
        ("capability Gate F", gates["F"]),
        ("capability Gate G", gates["G"]),
        ("capability Gate H", gates["H"]),
        ("capability Gate I", gates["I"]),
        ("capability Gate J", gates["J"]),
        ("capability Gate K", gates["K"]),
        ("capability Gate L", gates["L"]),
        ("unseen-deal smokes", unseen),
        ("Gate Q config/result", {"config": (gate_q_config.wall_clock_limit_s, gate_q_config.max_strategic_expansions, gate_q_config.max_tactical_nodes, gate_q_config.max_frontier_size, gate_q_config.dependency_closure_config.beam_width, gate_q_config.milestone_max_strategic_expansions), "summary": _summary(gate_q), "route": gate_q_route}),
        ("Gate Q completion funnel", _cash_out_funnel(gate_q)),
        ("Gate Q completion-representative table", _selection_rows(gate_q)),
        ("Gate Q admitted completions", gate_q.telemetry.admitted_completion_states),
        ("Gate Q representatives reserved", gate_q.telemetry.completion_representatives_reserved),
        ("Gate Q representatives expanded", gate_q.telemetry.completion_representatives_expanded),
        ("Gate Q downstream harvest", _harvest_summary(gate_q)),
        ("Gate Q source consumptions/integrations", (gate_q.telemetry.completion_source_consumed, gate_q.telemetry.completion_source_integrated)),
        ("Gate Q source-chain substantial milestones", gate_q.telemetry.substantial_source_chain_completions),
        ("Gate Q terminal qualifications", gate_q.telemetry.milestone_terminal_qualifications),
        ("Gate Q expiry after cash-out", {"before_expansion": gate_q.telemetry.completion_representatives_expired_before_expansion, "no_harvest": gate_q.telemetry.completion_no_downstream_harvest, "ordinary_continuation": gate_q.telemetry.completion_ordinary_continuations}),
        ("Gate Q F2", gate_q_f2),
        ("Gate R authorization", {"authorized": authorized, "reasons": authorization_reasons}),
        ("Gate R config/result if authorized", {"config": (gate_r_config.wall_clock_limit_s, gate_r_config.max_strategic_expansions, gate_r_config.max_tactical_nodes, gate_r_config.max_frontier_size, gate_r_config.dependency_closure_config.beam_width, gate_r_config.milestone_max_strategic_expansions) if gate_r_config else None, "summary": _summary(gate_r) if gate_r else None, "route": gate_r_route}),
        ("Gate R completion/cash-out funnel", _cash_out_funnel(gate_r) if gate_r else None),
        ("Gate R by-suit completions/harvest", {"completion": dict(gate_r.telemetry.source_completion_by_suit), "harvest": dict(gate_r.telemetry.completion_harvest_by_suit)} if gate_r else None),
        ("Gate R substantial milestones", {"source_chains": gate_r.telemetry.substantial_source_chain_completions, "intervals": gate_r.telemetry.substantial_interval_completions, "total": gate_r.telemetry.substantial_structural_milestones} if gate_r else None),
        ("Gate R stock/Deal timeline", tuple(gate_r.telemetry.deal_timeline) if gate_r else None),
        ("Gate R F1", gate_r_f1),
        ("post-F1 completion cash-out", _cash_out_funnel(gate_r) if gate_r_f1 else None),
        ("Gate R F2", gate_r_f2),
        ("continuous route/replay/hashes if successful", gate_r_route if gate_r_f2 else None),
        ("repeatability", {"ran": repeat is not None, "F2": len(_node(repeat).state.foundations) >= 2 if repeat else None, "route": _route(opening, repeat) if repeat else None}),
        ("optional F3", "not run unless Gate R reaches F2 and repeat succeeds"),
        ("optional whole-game", "not run unless F2, repeat, healthy cash-out and deadlines all succeed"),
        ("selection telemetry", _selection_summary(selected)),
        ("harvest telemetry", _harvest_summary(selected)),
        ("tactical/resource telemetry", _resource_summary(selected)),
        ("TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed}),
        ("final complete-suite result", FINAL_COMPLETE_SUITE),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
        ("architecture decision / recommended next phase", architecture_decision),
    ]
    assert len(sections) == 66
    if args.compact:
        print(pprint.pformat({
            "capability_gates": gates,
            "unseen": unseen,
            "gate_q": {
                "config": (gate_q_config.wall_clock_limit_s, gate_q_config.max_strategic_expansions, gate_q_config.max_tactical_nodes, gate_q_config.max_frontier_size, gate_q_config.dependency_closure_config.beam_width, gate_q_config.milestone_max_strategic_expansions),
                "summary": _summary(gate_q),
                "route": gate_q_route,
                "funnel": _cash_out_funnel(gate_q),
                "selection": _selection_summary(gate_q),
                "selection_rows": _selection_rows(gate_q),
                "harvest": _harvest_summary(gate_q),
                "resource": _resource_summary(gate_q),
                "TT": (gate_q.telemetry.tt_new, gate_q.telemetry.tt_improved, gate_q.telemetry.tt_suppressed),
                "proof": (gate_q.telemetry.proof_pruned, gate_q.telemetry.heuristic_pruned, gate_q.telemetry.exact_loop_suppressed),
            },
            "authorization": {"authorized": authorized, "reasons": authorization_reasons},
            "gate_r": ({
                "config": (gate_r_config.wall_clock_limit_s, gate_r_config.max_strategic_expansions, gate_r_config.max_tactical_nodes, gate_r_config.max_frontier_size, gate_r_config.dependency_closure_config.beam_width, gate_r_config.milestone_max_strategic_expansions),
                "summary": _summary(gate_r),
                "route": gate_r_route,
                "funnel": _cash_out_funnel(gate_r),
                "selection": _selection_summary(gate_r),
                "selection_rows": _selection_rows(gate_r),
                "harvest": _harvest_summary(gate_r),
                "source_by_suit": dict(gate_r.telemetry.source_completion_by_suit),
                "substantial": (gate_r.telemetry.substantial_source_chain_completions, gate_r.telemetry.substantial_interval_completions, gate_r.telemetry.substantial_structural_milestones),
                "deal_timeline": tuple(gate_r.telemetry.deal_timeline),
                "resource": _resource_summary(gate_r),
                "TT": (gate_r.telemetry.tt_new, gate_r.telemetry.tt_improved, gate_r.telemetry.tt_suppressed),
                "proof": (gate_r.telemetry.proof_pruned, gate_r.telemetry.heuristic_pruned, gate_r.telemetry.exact_loop_suppressed),
            } if gate_r is not None else None),
            "repeat": ({"summary": _summary(repeat), "route": _route(opening, repeat)} if repeat is not None else None),
            "verdict": verdict,
            "blocker": blocker,
            "architecture_decision": architecture_decision,
        }, width=140, sort_dicts=True))
        return
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
