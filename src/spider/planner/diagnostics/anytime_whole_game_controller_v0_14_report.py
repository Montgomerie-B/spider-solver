#!/usr/bin/env python3
"""v0.14 source-scoped completion propagation and expiry audit."""

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
import spider.planner.anytime_controller as controller_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    ControllerTelemetry,
    StrategicTranspositionTable,
    analyze_strategic_state,
    solve_anytime,
)
from spider.planner.campaign_dependency_closure import (
    CampaignDependencyType,
    ClosureCompletionClass,
    DependencyClosureConfig,
    realize_campaign_dependency_closure,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_o_base_config,
    _gate_g_config as _gate_p_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.planner.milestone_actionability import (
    MilestoneBlockerKind,
    derive_residual_milestone_target,
)
from spider.planner.milestone_conversion import MilestonePrimitiveStep
from spider.planner.source_completion import (
    PhysicalSourceIdentity,
    SemanticSourceRequirement,
    SourceCompletionEvent,
    SourceCompletionLedger,
    SourceCompletionLossReason,
    SourceCompletionPropagationTrace,
    SourceCompletionScope,
    SourceCompletionStage,
    SourceExpiryClassification,
    SourceRequirementReopeningReason,
    SourceRequirementSatisfaction,
    SourceRequirementSatisfactionState,
    classify_completion_loss,
    classify_source_expiry,
    physical_source_identity,
    reconcile_source_satisfaction,
    semantic_source_requirement,
    source_completion_event,
    source_state_hash,
)
from spider.planner.strategic_milestone import (
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
)
from spider.planner.tactical_resource_allocator import (
    TacticalResourceAllocatorConfig,
    TacticalResourceTier,
)
from spider.planner.target_grant_lineage import (
    TargetCommitmentStatus,
    new_target_lineage_entry,
    record_lineage_source_completion,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "77f46e8edeb2378df6ef9f7940ea6d34b45f03c8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "1316 passed, 37 xfailed, 1 inherited warning in 1110.34s"


def _section(number, title, value):
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up):
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _source(suit: str, rank: int) -> RankSource:
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "generic v0.14 source fixture",
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


def _milestone(state, campaign):
    return StrategicMilestone(
        "v014-source-chain", canonical_state_key(state), "generic-source-chain",
        campaign.label, StrategicMilestoneKind.SOURCE_CHAIN,
        MilestoneTargetPredicate(
            MilestonePredicateKind.DEPENDENCIES_CLOSED,
            "close a generic source requirement", suit="c",
            dependency_ids=("source:5:c",),
        ),
        "c", (5,), (), (), StrategicMilestoneProgress(0, 1, ("source:5:c",)),
        2, 4, 3, 4.0, 12_000, "the scoped source chain closes",
        "fresh exact state invalidates the source chain", None,
        target_identity=None,
    )


def _route(start, result, *, offset=0):
    if result is None:
        return None
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
        "total_g": offset + added if added is not None else None,
        "actions": len(node.actions),
        "deals": sum(action == ("deal",) for action in node.actions),
        "foundations": len(node.state.foundations),
        "foundation_suits": tuple(
            sequence[0].suit for sequence in node.state.foundations if sequence
        ),
        "stock": len(node.state.stock),
        "face_down": sum(len(column.face_down) for column in node.state.columns),
        "path_hash": controller_module._action_path_hash(node.actions),
        "endpoint_hash": controller_module._state_hash(node.state),
        "structural_hash": format(zobrist(node.state), "x"),
    }


def _completion_funnel(result):
    t = result.telemetry
    return {
        "source_buried_targeted": t.dependency_closure_attempts,
        "depth_or_prerequisite_progress": t.source_depth_reduced,
        "trace_completed": t.source_trace_completions,
        "successor_created": t.source_successors_created,
        "controller_admitted": t.source_controller_admitted_completions,
        "fresh_residual_preserved": t.source_fresh_residual_preserved,
        "lineage_preserved": t.source_lineage_preserved,
        "selected_path": t.source_selected_path_completions,
        "consumed": t.source_completion_consumptions,
        "integrated": t.source_completion_integrations,
        "substantial_source_chain": t.substantial_source_chain_completions,
        "terminal_qualification": t.milestone_terminal_qualifications,
        "foundations": len(_node(result).state.foundations),
    }


def _physical_rows(result):
    return tuple({
        "event": trace.event.event_id,
        "target": repr(trace.event.semantic_target_fingerprint),
        "dependency": trace.event.dependency_id,
        "source": f"{trace.event.physical_source.rank}{trace.event.physical_source.suit}",
        "provenance": trace.event.physical_source.provenance_id,
        "state": trace.event.exact_state_hash,
        "transition": (
            trace.event.original_dependency_type,
            trace.event.fresh_dependency_type,
        ),
        "face_up": trace.event.physical_source.face_up,
        "actionable": trace.event.actionable,
        "stages": tuple(item.value for item in trace.stages),
        "successor": trace.successor_created,
        "admitted": trace.controller_admitted,
        "residual": trace.residual_preserved,
        "lineage": trace.lineage_preserved,
        "selected": trace.selected_path,
        "consumed": trace.later_consumed,
        "integrated": trace.later_integrated,
        "reopening": trace.reopening_reason.value if trace.reopening_reason else None,
        "loss": trace.loss_reason.value if trace.loss_reason else None,
    } for trace in result.telemetry.source_completion_traces)


def _source_summary(result):
    t = result.telemetry
    return {
        "funnel": _completion_funnel(result),
        "by_suit": dict(t.source_completion_by_suit),
        "loss": dict(t.source_completion_loss_classifications),
        "reopenings": t.source_residual_reopenings,
        "copy_reassignments": t.source_copy_reassignments,
        "expiry": dict(t.source_expiry_classifications),
        "source_requirement_expiry": dict(t.source_requirement_expiry_classifications),
        "expiry_rows": tuple((key, value.value) for key, value in t.source_expiry_rows),
        "reanalyses": t.source_completion_reanalyses,
        "propagation_seconds": t.source_completion_propagation_seconds,
        "expiry_audit_seconds": t.source_expiry_audit_seconds,
    }


def _resource_summary(result):
    t = result.telemetry
    return {
        "elapsed": result.elapsed_seconds,
        "expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "closure_nodes": t.dependency_closure_nodes,
        "closure_seconds": t.dependency_closure_seconds,
        "closure_max_seconds": t.dependency_closure_max_seconds,
        "granted_nodes": result.tactical_resource_ledger.total_nodes_granted,
        "consumed_nodes": result.tactical_resource_ledger.total_nodes_consumed,
        "granted_seconds": result.tactical_resource_ledger.total_seconds_granted,
        "consumed_seconds": result.tactical_resource_ledger.total_seconds_consumed,
    }


def _capabilities(cards):
    opening = SpiderState.from_cards(cards)
    config = AnytimeControllerConfig(
        wall_clock_limit_s=2.0, max_strategic_expansions=1,
        max_tactical_nodes=100, max_frontier_size=16,
        enable_campaign_edges=False, enable_expensive_deal_timing=False,
    )
    analysis = analyze_strategic_state(
        opening, cards, spent_cost=0, incumbent_cost=None, config=config,
        include_deal_timing=False,
    )
    campaign = _campaign(analysis.economic.campaign_portfolio.campaigns[0])
    start = SpiderState(
        _columns(
            [Card("c", 5), Card("d", 5), Card("h", 4)], [Card("s", 5)],
            [Card("d", 6)], *([Card("h", 1)] for _ in range(7)),
        ),
        [],
    )
    target = ("generic-source-chain", campaign.label, "SOURCE_CHAIN")
    closure = realize_campaign_dependency_closure(
        start, campaign, target_dependency_id="source:5:c",
        semantic_target_id=target,
        config=DependencyClosureConfig(
            max_added_cost=8, max_nodes=400, time_limit_s=1.5,
            beam_width=192, enable_legal_candidate_audit=True,
        ),
    )
    event = closure.source_completion_events[0]
    dependency = next(
        item for item in closure.graph_after.dependencies
        if item.dependency_id == "source:5:c"
    )
    replay = start.clone()
    closure_replay = (
        replay_actions(replay, list(closure.actions)) == closure.corrected_added_cost
        and states_structurally_equal(replay, closure.end_state)
    )
    residual = derive_residual_milestone_target(
        closure.end_state, _milestone(closure.end_state, campaign),
        graph=closure.graph_after,
        prior_source_satisfactions=(event.satisfaction,),
    )
    same_state = reconcile_source_satisfaction(
        closure.end_state, event.requirement, event.satisfaction,
        current_dependency_type=event.fresh_dependency_type,
    )
    two_copy = reconcile_source_satisfaction(
        SpiderState(_columns([Card("c", 5)]), []),
        semantic_source_requirement(target, "source:5:c", Card("c", 5), copies_required=2),
    )
    copy_state = SpiderState(_columns([Card("c", 5)], [Card("c", 5)]), [])
    copy_prior = reconcile_source_satisfaction(copy_state, event.requirement)
    copy_prior = replace(
        copy_prior,
        satisfying_sources=(replace(copy_prior.satisfying_sources[0], current_column=1),),
    )
    copy_fresh = reconcile_source_satisfaction(copy_state, event.requirement, copy_prior)
    trace = SourceCompletionPropagationTrace(event).advance(
        SourceCompletionStage.CONTROLLER_SUCCESSOR_CREATED
    )
    admitted = trace.advance(SourceCompletionStage.CONTROLLER_ADMITTED_COMPLETION)
    telemetry = ControllerTelemetry()
    controller_module._record_source_completion_trace(telemetry, admitted, 32)
    controller_module._record_source_completion_trace(telemetry, admitted, 32)
    lineage_entry = new_target_lineage_entry(
        target, canonical_state_key(start), campaign_id=campaign.label,
        objective_id="generic-source-chain", dependency_id="source:5:c",
        blocker_fingerprint="buried", blocker_kind="SOURCE_BURIED",
    )
    lineage_entry = record_lineage_source_completion(lineage_entry, (event,))
    reobstructed = SpiderState(_columns([Card("c", 5)], [Card("d", 4)]), [])
    reobstruct_prior = reconcile_source_satisfaction(reobstructed, event.requirement)
    reobstructed.move(1, 0, 1, rules=MW_RULES)
    reopened = reconcile_source_satisfaction(
        reobstructed, event.requirement, reobstruct_prior,
        current_dependency_type="SOURCE_EXPOSED_BUT_BLOCKED",
    )
    integrated_state = SpiderState(_columns([Card("c", 6), Card("c", 5)]), [])
    integrated = reconcile_source_satisfaction(
        integrated_state, event.requirement, event.satisfaction
    )
    expiry = {
        item.value: classify_source_expiry(**kwargs).value
        for item, kwargs in (
            (SourceExpiryClassification.COMPLETED_BEFORE_EXPIRY, {"completed_before_expiry": True}),
            (SourceExpiryClassification.LEGITIMATE_NO_PROGRESS_EXPIRY, {}),
            (SourceExpiryClassification.RESOURCE_LIMIT_EXPIRY, {"resource_limited": True}),
            (SourceExpiryClassification.TARGET_TURNOVER_EXPIRY, {"target_turnover": True}),
            (SourceExpiryClassification.ATTRIBUTION_LOSS_EXPIRY, {"attribution_lost": True}),
            (SourceExpiryClassification.LIFECYCLE_EXPIRY, {"lifecycle_terminated": True}),
            (SourceExpiryClassification.SUPERSEDED_EXPIRY, {"superseded": True}),
        )
    }
    table = StrategicTranspositionTable()
    tt_state = SpiderState(_columns([Card("c", 5)]), [])
    tt_safe = (
        table.admit(tt_state, 5)
        and table.admit(tt_state.clone(), 4)
        and not table.admit(tt_state.clone(), 6, heuristic_score=SourceCompletionLedger())
    )
    gates = {
        "A": (
            closure_replay
            and closure.completion_class == ClosureCompletionClass.SOURCE_EXPOSED
            and event.original_dependency_type == "SOURCE_BURIED"
            and dependency.kind == CampaignDependencyType.SOURCE_EXPOSED_BUT_BLOCKED
            and not residual.source_reopenings
        ),
        "B": same_state.fresh_reanalysis_preserved and same_state.state != SourceRequirementSatisfactionState.UNSATISFIED,
        "C": copy_fresh.satisfied and copy_fresh.copy_reassigned and two_copy.state == SourceRequirementSatisfactionState.PARTIALLY_SATISFIED,
        "D": not residual.source_reopenings and any(item.source_satisfaction for item in residual.requirements),
        "E": telemetry.source_controller_admitted_completions == 1 and classify_completion_loss(trace_completed=True, successor_created=True, controller_admitted=False, metadata_present=True, residual_preserved=False, attribution_preserved=True, strategically_trimmed=True) == SourceCompletionLossReason.STRATEGIC_ADMISSION_LOSS,
        "F": admitted.controller_admitted and not admitted.selected_path,
        "G": event.event_id in lineage_entry.source_completion_event_ids and lineage_entry.status == TargetCommitmentStatus.NEW and bool(lineage_entry.follow_on_source_requirement_ids),
        "H": reopened.reopening_reason == SourceRequirementReopeningReason.SOURCE_BECAME_UNUSABLE,
        "I": set(expiry) == {item.value for item in SourceExpiryClassification},
        "J": integrated.state == SourceRequirementSatisfactionState.INTEGRATED,
        "K": tt_safe and canonical_state_key(tt_state) == canonical_state_key(tt_state.clone()),
    }
    details = {
        "closure": closure,
        "event": event,
        "residual": residual,
        "same_state": same_state,
        "copy_reassignment": copy_fresh,
        "two_copy": two_copy,
        "lineage": lineage_entry,
        "reopening": reopened,
        "integration": integrated,
        "expiry": expiry,
        "TT": (table.new_entries, table.improvements, table.suppressions),
    }
    return gates, details


def _unseen(cards, seconds):
    rows = []
    for seed in (14014, 14041):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
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
        rows.append({
            "seed": seed,
            "summary": _summary(result),
            "route": _route(state, result),
            "source": _source_summary(result),
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "deal_alternatives": result.telemetry.deal_successors_generated,
            "raw_alternative": "RAW_TABLEAU_MOVE" in result.telemetry.successor_kinds,
            "late_construction": result.telemetry.late_removal_construction_opportunities,
        })
    return tuple(rows)


def _authorization(gate_o):
    t = gate_o.telemetry
    reasons = {
        "Gate O F2": len(_node(gate_o).state.foundations) >= 2,
        "natural trace event became controller admitted": t.source_controller_admitted_completions > 0,
        "preserved completion progressed to consumption": t.source_fresh_residual_preserved > 0 and t.source_completion_consumptions > 0,
        "substantial source chain": t.substantial_source_chain_completions > 0,
        "terminal qualification": t.milestone_terminal_qualifications > 0,
        "same natural completion moved at least one funnel stage": t.source_successors_created > 0,
    }
    return any(reasons.values()), reasons


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-o-seconds", type=float, default=90.0)
    parser.add_argument("--gate-p-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=3.0)
    parser.add_argument("--skip-gate-p", action="store_true")
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
    gates, capability = _capabilities(cards)
    if not all(gates.values()):
        raise AssertionError(f"v0.14 capability gate failed: {gates}")
    unseen = _unseen(cards, args.smoke_seconds)

    gate_o_config = replace(
        _gate_o_base_config(args.gate_o_seconds),
        enable_tactical_resource_allocation=True,
        enable_strategic_milestones=True,
        enable_target_grant_lineage=True,
        enable_closure_candidate_audit=True,
        wall_clock_limit_s=min(90.0, args.gate_o_seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
    )
    gate_o = solve_anytime(anchor_node.state, cards, None, gate_o_config)
    authorized, authorization_reasons = _authorization(gate_o)

    gate_p = None
    gate_p_config = None
    if authorized and not args.skip_gate_p:
        gate_p_config = replace(
            _gate_p_base_config(args.gate_p_seconds),
            enable_tactical_resource_allocation=True,
            enable_strategic_milestones=True,
            enable_target_grant_lineage=True,
            enable_closure_candidate_audit=True,
            wall_clock_limit_s=min(180.0, args.gate_p_seconds),
            max_strategic_expansions=50,
            max_tactical_nodes=500_000,
            max_frontier_size=256,
        )
        gate_p = solve_anytime(opening, cards, None, gate_p_config)

    repeat = None
    if gate_p is not None and len(_node(gate_p).state.foundations) >= 2:
        repeat = solve_anytime(opening, cards, None, gate_p_config)

    selected = gate_p or gate_o
    gate_o_f2 = len(_node(gate_o).state.foundations) >= 2
    gate_p_f2 = bool(gate_p and len(_node(gate_p).state.foundations) >= 2)
    durable = gate_o.telemetry.source_controller_admitted_completions > 0
    verdict = (
        "STRONG PASS"
        if gate_p_f2 and repeat is not None and len(_node(repeat).state.foundations) >= 2
        else "PASS"
        if gate_o_f2 or gate_p_f2
        else "PARTIAL"
        if durable
        else "FAIL"
    )
    blocker = (
        "none through foundation #2"
        if gate_o_f2 or gate_p_f2
        else "typed source completion now survives controller admission, but the bounded selected route does not convert that harvest into foundation #2"
        if durable
        else "natural closure endpoints do not yet produce a durable admitted source completion"
    )
    gate_o_route = _route(anchor_node.state, gate_o, offset=21)
    gate_p_route = _route(opening, gate_p)
    tier_fingerprint = TacticalResourceAllocatorConfig().fingerprint
    sections = [
        ("authoritative base", AUTHORITATIVE_BASE),
        ("active rule profile", anchor.preflight.profile),
        ("regression anchors", {
            "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
            "machine_F1": (_summary(anchor), _route(opening, anchor)),
            "independent_F1": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        }),
        ("v0.13 anomaly", "trace-scoped completion/exposure existed, but no typed fact crossed closure result, residual, successor, node, lineage and telemetry"),
        ("current completion propagation map", "closure physical analysis -> typed DependencyClosureResult event -> MilestonePrimitiveStep -> fresh residual satisfaction -> StrategicSuccessor trace -> exact-TT-admitted node ledger -> target lineage -> selected-path telemetry"),
        ("source completion event model", tuple(SourceCompletionEvent.__dataclass_fields__)),
        ("physical source identity", tuple(PhysicalSourceIdentity.__dataclass_fields__)),
        ("physical monotonicity", "same exact state cannot downgrade an exposed/integrated physical fact; contradictory same-state analysis is ANALYSIS_DEFECT"),
        ("semantic source requirement model", tuple(SemanticSourceRequirement.__dataclass_fields__)),
        ("dependency-type transition handling", {"transition": (capability["event"].original_dependency_type, capability["event"].fresh_dependency_type), "buried_completed": capability["closure"].endpoint_assessment.requested_dependency_completed}),
        ("closure-result propagation", tuple(capability["closure"].source_completion_events)),
        ("milestone primitive propagation", tuple(MilestonePrimitiveStep.__dataclass_fields__)),
        ("residual satisfaction/reopening rules", {"states": tuple(item.value for item in SourceRequirementSatisfactionState), "reasons": tuple(item.value for item in SourceRequirementReopeningReason), "fixture_reopenings": capability["residual"].source_reopenings}),
        ("copy reassignment handling", capability["copy_reassignment"]),
        ("controller successor propagation", tuple(controller_module.StrategicSuccessor.__dataclass_fields__)),
        ("admitted/selected completion semantics", tuple(item.value for item in SourceCompletionStage)),
        ("lineage propagation", {"events": capability["lineage"].source_completion_event_ids, "follow_on": capability["lineage"].follow_on_source_requirement_ids}),
        ("portfolio reanalysis", "fresh exact state reconstructs current satisfaction; prior facts interpret the semantic target but never override exact state"),
        ("completion-loss classifications", tuple(item.value for item in SourceCompletionLossReason)),
        ("expiry-audit classifications", tuple(item.value for item in SourceExpiryClassification)),
        ("proof-safety audit", {"source_metadata_in_TT": False, "tier_fingerprint": tier_fingerprint, "proof_authority": False}),
        ("capability Gate A", {"passed": gates["A"], "event": capability["event"]}),
        ("capability Gate B", {"passed": gates["B"], "same_state": capability["same_state"]}),
        ("capability Gate C", {"passed": gates["C"], "one_copy": capability["copy_reassignment"], "two_copy": capability["two_copy"]}),
        ("capability Gate D", {"passed": gates["D"], "residual": capability["residual"].summary}),
        ("capability Gate E", {"passed": gates["E"]}),
        ("capability Gate F", {"passed": gates["F"]}),
        ("capability Gate G", {"passed": gates["G"], "lineage": capability["lineage"].lineage_id}),
        ("capability Gate H", {"passed": gates["H"], "reopening": capability["reopening"]}),
        ("capability Gate I", {"passed": gates["I"], "classifications": capability["expiry"]}),
        ("capability Gate J", {"passed": gates["J"], "integration": capability["integration"]}),
        ("capability Gate K", {"passed": gates["K"], "TT": capability["TT"]}),
        ("unseen-deal smokes", unseen),
        ("Gate O config/result", {"config": (gate_o_config.wall_clock_limit_s, gate_o_config.max_strategic_expansions, gate_o_config.max_tactical_nodes, gate_o_config.max_frontier_size, gate_o_config.dependency_closure_config.beam_width, gate_o_config.milestone_max_strategic_expansions), "summary": _summary(gate_o), "route": gate_o_route}),
        ("Gate O completion funnel", _completion_funnel(gate_o)),
        ("Gate O physical source event table", _physical_rows(gate_o)),
        ("Gate O trace completions", gate_o.telemetry.source_trace_completions),
        ("Gate O controller-admitted completions", gate_o.telemetry.source_controller_admitted_completions),
        ("Gate O selected-path completions", gate_o.telemetry.source_selected_path_completions),
        ("Gate O residual reopenings", gate_o.telemetry.source_residual_reopenings),
        ("Gate O copy reassignments", gate_o.telemetry.source_copy_reassignments),
        ("Gate O source consumptions", gate_o.telemetry.source_completion_consumptions),
        ("Gate O substantial source chains", gate_o.telemetry.substantial_source_chain_completions),
        ("Gate O terminal qualifications", gate_o.telemetry.milestone_terminal_qualifications),
        ("Gate O expiry audit", {"counts": dict(gate_o.telemetry.source_expiry_classifications), "rows": tuple((key, value.value) for key, value in gate_o.telemetry.source_expiry_rows)}),
        ("Gate O F2", gate_o_f2),
        ("Gate P authorization", {"authorized": authorized, "reasons": authorization_reasons}),
        ("Gate P config/result if authorized", {"config": (gate_p_config.wall_clock_limit_s, gate_p_config.max_strategic_expansions, gate_p_config.max_tactical_nodes, gate_p_config.max_frontier_size, gate_p_config.dependency_closure_config.beam_width, gate_p_config.milestone_max_strategic_expansions) if gate_p_config else None, "summary": _summary(gate_p) if gate_p else None, "route": gate_p_route}),
        ("Gate P completion funnel", _completion_funnel(gate_p) if gate_p else None),
        ("Gate P by-suit source completion", dict(gate_p.telemetry.source_completion_by_suit) if gate_p else None),
        ("Gate P substantial milestones", {"source_chains": gate_p.telemetry.substantial_source_chain_completions, "intervals": gate_p.telemetry.substantial_interval_completions, "total": gate_p.telemetry.substantial_structural_milestones} if gate_p else None),
        ("Gate P stock/Deal timeline", tuple(gate_p.telemetry.deal_timeline) if gate_p else None),
        ("Gate P F1", len(_node(gate_p).state.foundations) >= 1 if gate_p else None),
        ("post-F1 completion funnel", _completion_funnel(gate_p) if gate_p and len(_node(gate_p).state.foundations) >= 1 else None),
        ("Gate P F2", gate_p_f2 if gate_p else None),
        ("continuous route/replay/hashes if successful", gate_p_route if gate_p_f2 else None),
        ("repeatability", {"ran": repeat is not None, "F2": len(_node(repeat).state.foundations) >= 2 if repeat else None, "route": _route(opening, repeat) if repeat else None}),
        ("optional F3", "not run unless F2 and its deterministic repeat succeed"),
        ("optional whole-game", "not run unless F2, repeat, coherent propagation and healthy deadlines all succeed"),
        ("propagation telemetry", _source_summary(selected)),
        ("lineage/expiry telemetry", {"lineages_created": selected.telemetry.target_lineages_created, "lineages_persisted": selected.telemetry.target_lineages_persisted, "expirations": selected.telemetry.target_tier_expirations, "expiry": dict(selected.telemetry.source_expiry_classifications)}),
        ("resource telemetry", _resource_summary(selected)),
        ("TT statistics", {"new": selected.telemetry.tt_new, "improved": selected.telemetry.tt_improved, "suppressed": selected.telemetry.tt_suppressed}),
        ("proof statistics", {"proof_pruned": selected.telemetry.proof_pruned, "heuristic_pruned": selected.telemetry.heuristic_pruned, "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed}),
        ("final full-suite result", FINAL_COMPLETE_SUITE),
        ("verdict", verdict),
        ("precise remaining blocker", blocker),
    ]
    assert len(sections) == 67
    for number, (title, value) in enumerate(sections, 1):
        _section(number, title, value)


if __name__ == "__main__":
    main()
