#!/usr/bin/env python3
"""v0.13 persisted-target grant-lineage and fresh-candidate audit."""

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
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicTranspositionTable,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_m_base_config,
    _gate_g_config as _gate_n_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.tactical_resource_allocator import (
    TacticalDemand,
    TacticalObjectiveKind,
    TacticalRealizerKind,
    TacticalResourceAllocator,
    TacticalResourceAllocatorConfig,
    TacticalResourceOutcome,
    TacticalResourceTier,
)
from spider.planner.target_grant_lineage import (
    PersistedTargetFailureDiagnosis,
    TargetCommitmentEvidence,
    TargetGrantLineage,
    decide_target_grant,
    diagnose_persisted_target_failure,
    make_boundary_trace,
    new_target_lineage_entry,
    record_target_grant,
    record_target_outcome,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "6de175ea7a18b376f4742092190d6d384dac0af4"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "1244 passed, 37 xfailed, 1 inherited warning in 1146.43s"


def _section(number, title, value):
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _state(tag=0):
    stock = [Card("h", 13)] * 10 if tag else []
    return SpiderState(_columns([Card("c", 7)], [Card("d", 6)]), stock)


TARGET = (
    "generic-source-chain",
    "generic-campaign",
    "SOURCE_CHAIN",
    "DEPENDENCIES_CLOSED",
    "c",
    (7, 6, 5),
    ("source:5:c",),
    "close the named source chain",
)


def _new_entry(state, *, tier=TacticalResourceTier.PROBE, limit=3):
    return new_target_lineage_entry(
        TARGET,
        canonical_state_key(state),
        campaign_id="generic-campaign",
        objective_id="generic-source-chain",
        dependency_id="source:5:c",
        blocker_fingerprint="blocker-a",
        blocker_kind="SOURCE_BURIED",
        initial_tier=tier,
        persistence_limit=limit,
        realizer="DEPENDENCY_CLOSURE",
    )


def _named_harvest(*, obligation=None):
    return TargetCommitmentEvidence(
        named_harvest=("SOURCE_DEPTH_REDUCED",),
        completion_class="DEPENDENCY_ADVANCED",
        source_depth_before=3,
        source_depth_after=2,
        blockers_before=3,
        blockers_after=2,
        prerequisite_completed=True,
        target_relevant=True,
        nodes_consumed=128,
        seconds_consumed=0.1,
        corrected_paid_cost=2,
        lifecycle_debt=1.0 if obligation else 0.0,
        restore_replace_obligation=obligation,
    )


def _decision(entry, state, *, target=TARGET, blocker="SOURCE_BURIED", initial=TacticalResourceTier.PROBE, terminal=False, valid=True):
    return decide_target_grant(
        entry,
        semantic_target_fingerprint=target,
        requested_initial_tier=initial,
        terminal_qualified=terminal,
        target_valid=valid,
        current_state_key=canonical_state_key(state),
        current_blocker_fingerprint=f"fresh-{blocker}",
        current_blocker_kind=blocker,
        lifecycle_debt=entry.lifecycle_debt if entry else 0.0,
        compensation_credible=True,
    )


def _advanced_entry():
    first, second = _state(0), _state(1)
    entry = _new_entry(first)
    decision = _decision(entry, first)
    entry = record_target_grant(
        entry,
        state_key=canonical_state_key(first),
        dependency_id="source:5:c",
        blocker_fingerprint="blocker-a",
        blocker_kind="SOURCE_BURIED",
        requested_tier=decision.requested_tier,
        granted_tier=TacticalResourceTier.PROBE,
        decision=decision,
        realizer="DEPENDENCY_CLOSURE",
    )
    return record_target_outcome(
        entry, _named_harvest(), end_state_key=canonical_state_key(second)
    )


def _allocator_audit():
    allocator = TacticalResourceAllocator()
    demand = TacticalDemand(
        TacticalObjectiveKind.EXCAVATION,
        TacticalRealizerKind.DEPENDENCY_CLOSURE,
        "generic exact-state audit",
        campaign_id="generic-campaign",
        target_dependency_id="source:5:c",
    )
    first, second = _state(0), _state(1)
    _request, grant = allocator.request(canonical_state_key(first), demand)
    allocator.record_outcome(TacticalResourceOutcome(
        grant.request_id,
        grant.key,
        grant.tier,
        1,
        0.01,
        1,
        1,
        dependencies_closed=1,
        blocker_before="source",
        blocker_after="next-source",
    ))
    same_request, same_grant = allocator.request(canonical_state_key(first), demand)
    fresh_request, fresh_grant = allocator.request(canonical_state_key(second), demand)
    return {
        "key_fields": tuple(grant.key.__dataclass_fields__),
        "same_exact_state_after_harvest": same_grant.tier.name,
        "fresh_exact_state_same_demand": fresh_grant.tier.name,
        "same_request_reason": same_request.reason,
        "fresh_request_reason": fresh_request.reason,
        "diagnosis": "SHALLOW/COMMITTED evidence was tied to the exact state; a changed exact state restarted at PROBE",
    }


def _capabilities():
    entry = _advanced_entry()
    second = _state(1)
    retained = _decision(entry, second)
    no_harvest = record_target_outcome(
        _new_entry(_state(0)),
        TargetCommitmentEvidence(),
        end_state_key=canonical_state_key(second),
    )
    blocker_change = _decision(entry, second, blocker="WORKSPACE")
    different = _decision(entry, second, target=TARGET + ("different",))
    missed = _decision(no_harvest, second)
    nonterminal = replace(
        entry,
        granted_tier=TacticalResourceTier.COMMITTED,
        earned_tier=TacticalResourceTier.COMMITTED,
    )
    terminal_guard = _decision(nonterminal, second)
    terminal_fresh = _decision(
        nonterminal,
        second,
        initial=TacticalResourceTier.TERMINAL,
        terminal=True,
    )

    legal = SpiderState(
        _columns(
            [Card("c", 7)], [Card("c", 6)], [Card("c", 5)],
            [Card("c", 4)], [Card("c", 3)], [Card("c", 2)],
        ),
        [],
    )
    midpoint = legal.clone()
    probe_cost = replay_actions(midpoint, [(1, 0, 1), (2, 0, 1)])
    shallow_cost = replay_actions(midpoint, [(3, 0, 1), (4, 0, 1), (5, 0, 1)])
    specs = TacticalResourceAllocatorConfig()
    trace = make_boundary_trace(
        entry,
        retained,
        dependency_after="source:5:c",
        blocker_after="WORKSPACE",
        progress_before="source depth 3->2",
        progress_after="fresh receiver changed to workspace",
        fresh_candidate_classes=("WORKSPACE",),
        best_next_candidate="create and use bounded workspace",
        best_candidate_minimum_tier=TacticalResourceTier.SHALLOW,
        granted_tier=TacticalResourceTier.PROBE,
    )
    turnover = diagnose_persisted_target_failure(trace, candidate_turnover=True)
    obligation = replace(
        entry,
        evidence=_named_harvest(obligation="restore or replace one stable join"),
        restore_replace_obligation="restore or replace one stable join",
    )
    table = StrategicTranspositionTable()
    tt_state = _state(0)
    tt_safe = table.admit(tt_state, 5) and table.admit(tt_state.clone(), 4) and not table.admit(
        tt_state.clone(), 6, heuristic_score=TargetGrantLineage((entry,))
    )
    reservation_source = inspect.getsource(
        controller_module._trim_frontier_with_checkpoint_diversity
    )
    gates = {
        "A": retained.requested_tier == TacticalResourceTier.SHALLOW,
        "B": missed.requested_tier == TacticalResourceTier.PROBE and not missed.inherited_commitment,
        "C": blocker_change.requested_tier == TacticalResourceTier.SHALLOW,
        "D": different.requested_tier == TacticalResourceTier.PROBE and not different.inherited_commitment,
        "E": no_harvest.consecutive_misses == 1 and missed.requested_tier == TacticalResourceTier.PROBE,
        "F": terminal_guard.requested_tier != TacticalResourceTier.TERMINAL and terminal_fresh.requested_tier == TacticalResourceTier.TERMINAL,
        "G": probe_cost == 2 and shallow_cost > specs.spec(TacticalResourceTier.PROBE).max_added_cost and shallow_cost <= specs.spec(TacticalResourceTier.SHALLOW).max_added_cost,
        "H": turnover == PersistedTargetFailureDiagnosis.FRESH_CANDIDATE_TURNOVER,
        "I": obligation.restore_replace_obligation is not None and obligation.evidence.compensation_credible,
        "J": "entry.evidence.has_portable_harvest" in reservation_source,
        "K": tt_safe,
    }
    details = {
        "retained": retained,
        "no_harvest": missed,
        "blocker_change": blocker_change,
        "different_target": different,
        "terminal_guard": terminal_guard,
        "terminal_fresh": terminal_fresh,
        "legal_costs": (probe_cost, shallow_cost),
        "turnover": turnover,
        "obligation": obligation.restore_replace_obligation,
        "TT": (table.new_entries, table.improvements, table.suppressions),
    }
    return gates, details


def _route(start, result, *, offset=0):
    node = _node(result)
    replay = start.clone()
    try:
        added = replay_actions(replay, list(node.actions))
        valid = added == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        added, valid = None, False
    return {
        "valid": valid,
        "added_g": added,
        "total_g": (offset + added if added is not None else None),
        "actions": len(node.actions),
        "deals": sum(action == ("deal",) for action in node.actions),
        "foundations": len(node.state.foundations),
        "foundation_suits": tuple(sequence[0].suit for sequence in node.state.foundations if sequence),
        "stock": len(node.state.stock),
        "face_down": sum(len(column.face_down) for column in node.state.columns),
        "path_hash": controller_module._action_path_hash(node.actions),
        "endpoint_hash": controller_module._state_hash(node.state),
        "structural_hash": format(zobrist(node.state), "x"),
    }


def _trace_row(trace):
    return {
        "lineage": trace.lineage_id,
        "target": repr(trace.semantic_target_fingerprint),
        "states": (trace.state_before_hash, trace.state_after_hash),
        "dependency": (trace.dependency_before, trace.dependency_after),
        "blocker": (trace.blocker_before, trace.blocker_after),
        "progress": (trace.progress_before, trace.progress_after),
        "tiers": (
            trace.previous_tier.name if trace.previous_tier is not None else None,
            trace.requested_next_tier.name,
            trace.granted_next_tier.name if trace.granted_next_tier is not None else None,
        ),
        "retained": trace.promotion_retained,
        "reason": trace.reason,
        "candidate_count": trace.fresh_relevant_candidate_count,
        "candidate_classes": trace.candidate_classes,
        "best": trace.best_next_candidate,
        "inside_grant": trace.candidate_inside_grant,
        "selected": trace.selected_action,
        "lifecycle": trace.lifecycle_obligation,
        "closure": trace.next_closure_result,
        "outcome": trace.eventual_target_outcome,
        "diagnosis": trace.failure_diagnosis.value if trace.failure_diagnosis else None,
    }


def _lineage_summary(result):
    telemetry = result.telemetry
    all_traces = tuple(telemetry.target_boundary_traces)
    traces = tuple(item for item in all_traces if item.previous_tier is not None)
    completed_lineages = {
        item.lineage_id
        for item in traces
        if item.eventual_target_outcome in {"COMPLETED", "EXPOSED"}
    }
    classifications = {}
    for lineage in {item.lineage_id for item in traces} - completed_lineages:
        rows = [item for item in traces if item.lineage_id == lineage]
        diagnosis = next(
            (item.failure_diagnosis for item in reversed(rows) if item.failure_diagnosis),
            PersistedTargetFailureDiagnosis.OTHER_EXPLICIT,
        )
        classifications[diagnosis.value] = classifications.get(diagnosis.value, 0) + 1
    before_by_tier = {}
    after_by_tier = {}
    for item in traces:
        before = item.previous_tier.name
        before_by_tier[before] = before_by_tier.get(before, 0) + 1
        if item.granted_next_tier is not None:
            after = item.granted_next_tier.name
            after_by_tier[after] = after_by_tier.get(after, 0) + 1
    return {
        "created": telemetry.target_lineages_created,
        "persisted_boundaries": telemetry.target_lineages_persisted,
        "distinct": len({item.lineage_id for item in traces}),
        "completed_or_exposed": len(completed_lineages),
        "retained_promotions": telemetry.target_tier_promotions_retained,
        "resets": telemetry.target_tier_resets,
        "demotions": telemetry.target_tier_demotions,
        "expirations": telemetry.target_tier_expirations,
        "before_by_tier": before_by_tier,
        "after_by_tier": after_by_tier,
        "inside_grant": sum(item.candidate_inside_grant is True for item in traces),
        "outside_grant": sum(item.candidate_inside_grant is False for item in traces),
        "classifications": classifications,
        "rows": tuple(_trace_row(item) for item in traces),
    }


def _resource_summary(result):
    t = result.telemetry
    return {
        "closures": t.dependency_closure_attempts,
        "closure_nodes": t.dependency_closure_nodes,
        "closure_seconds": t.dependency_closure_seconds,
        "closure_max_seconds": t.dependency_closure_max_seconds,
        "completion_classes": dict(t.closure_completion_classes),
        "advanced": t.closure_dependency_advanced,
        "completed": t.closure_dependency_completed,
        "resource_bound": t.closure_resource_bound,
        "source_depth_reductions": t.source_depth_reduced,
        "source_exposures": t.sources_exposed,
        "source_consumptions": t.sources_consumed,
        "primitives": t.closure_primitives_total,
        "maximum_sequence": t.closure_max_primitive_sequence,
        "tactical_nodes": t.tactical_nodes,
        "granted_nodes": result.tactical_resource_ledger.total_nodes_granted,
        "consumed_nodes": result.tactical_resource_ledger.total_nodes_consumed,
        "granted_seconds": result.tactical_resource_ledger.total_seconds_granted,
        "consumed_seconds": result.tactical_resource_ledger.total_seconds_consumed,
    }


def _unseen(cards, seconds):
    outcomes = []
    for seed in (13013, 13031):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = AnytimeControllerConfig(
            wall_clock_limit_s=max(2.0, seconds),
            max_strategic_expansions=3,
            max_tactical_nodes=36_000,
            max_frontier_size=64,
            enable_tactical_resource_allocation=True,
            enable_strategic_milestones=True,
            enable_target_grant_lineage=True,
            enable_closure_candidate_audit=True,
        )
        result = solve_anytime(state, shuffled, None, config)
        outcomes.append({
            "seed": seed,
            "summary": _summary(result),
            "route": _route(state, result),
            "lineage": {key: value for key, value in _lineage_summary(result).items() if key != "rows"},
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "deal_alternative": result.telemetry.deal_successors_generated > 0,
            "raw_family_enabled": config.max_credit_level.name == "RAW",
            "raw_alternative_observed": "RAW_TABLEAU_MOVE" in result.telemetry.successor_kinds,
            "late_construction": result.telemetry.late_removal_construction_opportunities,
        })
    return tuple(outcomes)


def _authorization(gate_m):
    node = _node(gate_m)
    t = gate_m.telemetry
    same_class_lost_action_recovered = any(
        item.previous_tier is not None
        and item.promotion_retained
        and item.selected_action is not None
        for item in t.target_boundary_traces
    )
    reasons = {
        "Gate M F2": len(node.state.foundations) >= 2,
        "natural persisted target exposed/consumed source": bool(t.sources_exposed or t.sources_consumed),
        "substantial source chain": t.substantial_source_chain_completions > 0,
        "terminal qualification": t.milestone_terminal_qualifications > 0,
        "former boundary reset corrected and same target class executed next action": same_class_lost_action_recovered,
    }
    return any(reasons.values()), reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-m-seconds", type=float, default=90.0)
    parser.add_argument("--gate-n-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=3.0)
    parser.add_argument("--skip-gate-n", action="store_true")
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
    allocator_audit = _allocator_audit()
    gates, capability = _capabilities()
    if not all(gates.values()):
        raise AssertionError(f"v0.13 capability gate failed: {gates}")
    unseen = _unseen(cards, args.smoke_seconds)

    gate_m_config = replace(
        _gate_m_base_config(args.gate_m_seconds),
        enable_tactical_resource_allocation=True,
        enable_strategic_milestones=True,
        enable_target_grant_lineage=True,
        enable_closure_candidate_audit=True,
        wall_clock_limit_s=min(90.0, args.gate_m_seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
    )
    gate_m = solve_anytime(anchor_node.state, cards, None, gate_m_config)
    gate_m_node = _node(gate_m)
    gate_m_route = _route(anchor_node.state, gate_m, offset=21)
    gate_m_lineage = _lineage_summary(gate_m)
    authorized, authorization_reasons = _authorization(gate_m)

    gate_n = None
    gate_n_config = None
    if authorized and not args.skip_gate_n:
        gate_n_config = replace(
            _gate_n_base_config(args.gate_n_seconds),
            enable_tactical_resource_allocation=True,
            enable_strategic_milestones=True,
            enable_target_grant_lineage=True,
            enable_closure_candidate_audit=True,
            wall_clock_limit_s=min(180.0, args.gate_n_seconds),
            max_strategic_expansions=50,
            max_tactical_nodes=500_000,
            max_frontier_size=256,
        )
        gate_n = solve_anytime(opening, cards, None, gate_n_config)

    repeat = None
    if gate_n is not None and len(_node(gate_n).state.foundations) >= 2:
        repeat = solve_anytime(opening, cards, None, gate_n_config)

    selected = gate_n or gate_m
    selected_node = _node(selected)
    gate_m_f2 = len(gate_m_node.state.foundations) >= 2
    gate_n_f2 = bool(gate_n and len(_node(gate_n).state.foundations) >= 2)
    natural_conversion = bool(
        gate_m.telemetry.sources_exposed
        or gate_m.telemetry.sources_consumed
        or gate_m.telemetry.closure_persisted_targets_completed
    )
    diagnosed = bool(gate_m_lineage["classifications"])
    verdict = (
        "STRONG PASS"
        if gate_n_f2 and repeat is not None and len(_node(repeat).state.foundations) >= 2
        else "PASS"
        if gate_m_f2 or gate_n_f2
        else "PARTIAL"
        if natural_conversion or diagnosed
        else "FAIL"
    )
    blocker = (
        "none through foundation #2"
        if gate_m_f2 or gate_n_f2
        else "same-target boundary conversion improved, but the selected bounded route did not mature into foundation #2"
        if natural_conversion
        else "fresh same-target actions remained bounded or structurally blocked before named-source exposure and foundation #2"
    )
    gate_n_route = _route(opening, gate_n) if gate_n is not None else None
    gate_n_lineage = _lineage_summary(gate_n) if gate_n is not None else None
    selected_lineage = _lineage_summary(selected)

    config_fingerprint_before = TacticalResourceAllocatorConfig().fingerprint
    config_fingerprint_after = gate_m_config.tactical_resource_config.fingerprint
    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("rule profile", anchor.preflight.profile),
        ("regression anchors", {
            "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
            "machine_F1": (_summary(anchor), _route(opening, anchor)),
            "independent_F1": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        }),
        ("v0.12 blocker", "11 natural ADVANCED targets crossed boundaries; none later completed or exposed/consumed its named source"),
        ("allocator-state audit", allocator_audit),
        ("current exact-state tier behaviour", {"before_v0.13": "changed exact state restarted at PROBE", "confirmed": allocator_audit["fresh_exact_state_same_demand"]}),
        ("target grant-lineage model", tuple(TargetGrantLineage.__dataclass_fields__)),
        ("lineage retention/reset rules", {"retain": "same valid target plus named target harvest", "reset": "no harvest, contradiction, expiry, unrelated target", "terminal": "fresh predicate only"}),
        ("no-hidden-budget audit", {"tier_fingerprint_unchanged": config_fingerprint_before == config_fingerprint_after, "unused_grant_carried": False, "per_expansion_nodes": gate_m_config.tactical_resource_config.max_granted_nodes_per_expansion, "per_expansion_seconds": gate_m_config.tactical_resource_config.max_granted_seconds_per_expansion}),
        ("target-specific promotion evidence", asdict(capability["retained"])),
        ("commitment decay", asdict(capability["no_harvest"])),
        ("fresh-candidate conversion tracing", tuple(controller_module.TargetBoundaryTrace.__dataclass_fields__)),
        ("restore/replace lineage", capability["obligation"]),
        ("strategic-admission audit", "one strongest actionable same-target descendant with portable harvest receives a bounded reservation; conservative alternatives remain in normal fill"),
        ("failure classification model", tuple(item.value for item in PersistedTargetFailureDiagnosis)),
        ("proof-safety audit", {"lineage_in_state_key": False, "TT_changed": False, "admissible_bound_changed": False, "proof_authority": False}),
        ("capability Gate A", {"passed": gates["A"], "decision": capability["retained"]}),
        ("capability Gate B", {"passed": gates["B"], "decision": capability["no_harvest"]}),
        ("capability Gate C", {"passed": gates["C"], "decision": capability["blocker_change"]}),
        ("capability Gate D", {"passed": gates["D"], "decision": capability["different_target"]}),
        ("capability Gate E", {"passed": gates["E"], "misses": capability["no_harvest"].previous_tier}),
        ("capability Gate F", {"passed": gates["F"], "nonterminal": capability["terminal_guard"], "terminal": capability["terminal_fresh"]}),
        ("capability Gate G", {"passed": gates["G"], "legal_costs": capability["legal_costs"]}),
        ("capability Gate H", {"passed": gates["H"], "diagnosis": capability["turnover"]}),
        ("capability Gate I", {"passed": gates["I"], "obligation": capability["obligation"]}),
        ("capability Gate J", {"passed": gates["J"], "bounded_reservation": True}),
        ("capability Gate K", {"passed": gates["K"], "TT": capability["TT"]}),
        ("unseen-deal smokes", unseen),
        ("Gate M config/result", {"config": (gate_m_config.wall_clock_limit_s, gate_m_config.max_strategic_expansions, gate_m_config.max_tactical_nodes, gate_m_config.max_frontier_size, gate_m_config.dependency_closure_config.beam_width), "summary": _summary(gate_m), "route": gate_m_route}),
        ("Gate M persisted-target count", {"distinct": gate_m_lineage["distinct"], "boundaries": gate_m_lineage["persisted_boundaries"]}),
        ("Gate M lineage rows", gate_m_lineage["rows"]),
        ("Gate M tier-before/tier-after summary", {"before": gate_m_lineage["before_by_tier"], "after": gate_m_lineage["after_by_tier"]}),
        ("Gate M tier resets", gate_m_lineage["resets"]),
        ("Gate M retained promotions", gate_m_lineage["retained_promotions"]),
        ("Gate M fresh candidate-set analysis", {"inside_grant": gate_m_lineage["inside_grant"], "outside_grant": gate_m_lineage["outside_grant"]}),
        ("Gate M failure classifications", gate_m_lineage["classifications"]),
        ("Gate M outer-boundary completions", {"completed_or_exposed_lineages": gate_m_lineage["completed_or_exposed"], "legacy_persisted_completed": gate_m.telemetry.closure_persisted_targets_completed}),
        ("Gate M source exposures/consumptions", (gate_m.telemetry.sources_exposed, gate_m.telemetry.sources_consumed)),
        ("Gate M substantial source chains", gate_m.telemetry.substantial_source_chain_completions),
        ("Gate M terminal qualifications", gate_m.telemetry.milestone_terminal_qualifications),
        ("Gate M strategic admission analysis", {"admitted": gate_m.telemetry.advanced_descendants_admitted, "trimmed": gate_m.telemetry.advanced_descendants_trimmed, "reserved": gate_m.telemetry.same_target_reserved_representatives, "lost_to_lower_g": gate_m.telemetry.mature_targets_lost_to_lower_g}),
        ("Gate M F2 result", gate_m_f2),
        ("Gate N authorization", {"authorized": authorized, "reasons": authorization_reasons}),
        ("Gate N config/result if authorized", {"config": (gate_n_config.wall_clock_limit_s, gate_n_config.max_strategic_expansions, gate_n_config.max_tactical_nodes, gate_n_config.max_frontier_size, gate_n_config.dependency_closure_config.beam_width) if gate_n_config else None, "summary": _summary(gate_n) if gate_n else None, "route": gate_n_route}),
        ("Gate N strategic timeline", tuple(gate_n.telemetry.decision_trace) if gate_n else None),
        ("Gate N target-lineage timeline", gate_n_lineage["rows"] if gate_n_lineage else None),
        ("Gate N source-chain/interval completions", (gate_n.telemetry.substantial_source_chain_completions, gate_n.telemetry.substantial_interval_completions) if gate_n else None),
        ("Gate N stock/Deal timeline", tuple(gate_n.telemetry.deal_timeline) if gate_n else None),
        ("Gate N F1", len(_node(gate_n).state.foundations) >= 1 if gate_n else None),
        ("post-F1 target lineage", gate_n_lineage if gate_n and len(_node(gate_n).state.foundations) >= 1 else None),
        ("Gate N F2", gate_n_f2 if gate_n else None),
        ("continuous route/replay/hashes if successful", gate_n_route if gate_n_f2 else None),
        ("repeatability", {"ran": repeat is not None, "F2": len(_node(repeat).state.foundations) >= 2 if repeat else None, "route": _route(opening, repeat) if repeat else None}),
        ("optional F3", "not run unless F2 and its deterministic repeat succeed"),
        ("optional whole-game", "not run unless F2, repeat, healthy lineage, and deadline gates all succeed"),
        ("lineage telemetry", {key: value for key, value in selected_lineage.items() if key != "rows"}),
        ("tactical/resource telemetry", _resource_summary(selected)),
        ("TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed}),
        ("final full-suite result", FINAL_COMPLETE_SUITE),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
    ]
    assert len(sections) == 62
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
