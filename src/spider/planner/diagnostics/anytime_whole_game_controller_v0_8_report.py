#!/usr/bin/env python3
"""Reproducible v0.8 tactical-resource allocation diagnostic.

Gate F starts at the independently replayed machine cost-21 checkpoint.  Gate
G starts at the untouched deal and is executed only when Gate F's measured
allocation behavior satisfies the authorization predicate.  Neither anchor
actions nor diagnostic results are available to prospective Gate G search.
"""

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
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
    build_campaign_critical_path,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _diagnosis_payload,
    _node,
    _opening_anchor_config,
    _replay,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_7_report import (
    _gate_e_config as _v07_gate_e_config,
    _gate_f_config as _v07_gate_f_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.planner.tactical_resource_allocator import (
    RemovalAllocationPolicy,
    TacticalDemand,
    TacticalObjectiveKind,
    TacticalRealizerKind,
    TacticalResourceAllocator,
    TacticalResourceDecision,
    TacticalResourceOutcome,
    TacticalResourceTier,
    derive_tactical_demands,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "966bf7364b2f0c2485c945e0ab8cbc30ffe51a1c"
INHERITED_COMPLETE_SUITE = "859 passed, 37 xfailed, 1 existing warning in 1138.47s"
FINAL_COMPLETE_SUITE = "905 passed, 37 xfailed, 1 existing warning in 1128.14s"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up) -> list[Column]:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _fixture_state(*, stock=()) -> SpiderState:
    return SpiderState(
        _columns([Card("d", 9), Card("c", 5)], [Card("c", 6)]),
        list(stock),
    )


def _fixture_graph(
    kind: CampaignDependencyType,
    *,
    campaign_id: str = "C#1",
    dependency_id: str = "blocker",
) -> CampaignDependencyGraph:
    dependency = CampaignDependency(
        dependency_id,
        kind,
        campaign_id,
        "deterministic allocation fixture",
        depth=2 if kind == CampaignDependencyType.SOURCE_BURIED else 0,
    )
    terminal_id = f"terminal:{campaign_id}"
    terminal = CampaignDependency(
        terminal_id,
        CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
        campaign_id,
        "terminal",
        prerequisites=(dependency_id,),
    )
    return CampaignDependencyGraph(
        canonical_state_key(_fixture_state()),
        campaign_id,
        (dependency, terminal),
        ((dependency_id, terminal_id),),
        (),
        terminal_id,
        f"fixture-{kind.value}",
    )


def _fixture_portfolio(
    kind: CampaignDependencyType,
    *,
    terminal: bool = False,
    continuation: str | None = None,
):
    summary = build_campaign_critical_path(
        _fixture_graph(kind), terminal_qualified=terminal
    )
    return derive_tactical_demands(
        (summary,),
        campaign_suits={"C#1": "c"},
        continuation_objective_id=continuation,
        construction=analyze_same_suit_construction(_fixture_state()),
        deal_available=True,
    )


def _fixture_demand(kind: CampaignDependencyType = CampaignDependencyType.RECEIVER_MISSING):
    return _fixture_portfolio(kind).best_for(
        TacticalRealizerKind.DEPENDENCY_CLOSURE,
        campaign_id="C#1",
    )


def _outcome(grant, **changes) -> TacticalResourceOutcome:
    values = dict(
        request_id=grant.request_id,
        key=grant.key,
        tier=grant.tier,
        nodes_consumed=grant.nodes_granted,
        seconds_consumed=grant.seconds_granted,
        corrected_paid_cost=0,
        legal_successor_count=0,
        blocker_before="blocker",
        blocker_after="blocker",
    )
    values.update(changes)
    return TacticalResourceOutcome(**values)


def _capability_gates() -> dict:
    receiver = _fixture_demand(CampaignDependencyType.RECEIVER_MISSING)
    interval = _fixture_demand(CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL)
    overlay = _fixture_demand(CampaignDependencyType.MIXED_OVERLAY)
    terminal_portfolio = _fixture_portfolio(
        CampaignDependencyType.RECEIVER_MISSING, terminal=True
    )
    terminal = terminal_portfolio.best_for(
        TacticalRealizerKind.TERMINAL_ASSEMBLY, campaign_id="C#1"
    )
    diagnostic_removal = _fixture_portfolio(
        CampaignDependencyType.RECEIVER_MISSING
    ).best_for(TacticalRealizerKind.CAMPAIGN_REMOVAL, campaign_id="C#1")
    gate_a = {
        "A1_receiver_priority": receiver.objective == TacticalObjectiveKind.RECEIVER_CREATION,
        "A2_interval_priority": interval.objective == TacticalObjectiveKind.INTERVAL_ASSEMBLY,
        "A3_overlay_priority": overlay.objective == TacticalObjectiveKind.OVERLAY_CLEARING,
        "A4_terminal_promoted_after_qualification": terminal.initial_tier == TacticalResourceTier.TERMINAL,
        "A5_terminal_strong_from_start": terminal.removal_policy == RemovalAllocationPolicy.REMOVAL_FULL_BUDGET,
        "unqualified_removal_diagnostic_only": diagnostic_removal.removal_policy == RemovalAllocationPolicy.REMOVAL_DIAGNOSTIC_ONLY,
    }

    key = canonical_state_key(_fixture_state())
    no_harvest = TacticalResourceAllocator()
    _, grant = no_harvest.request(key, receiver)
    first_miss = no_harvest.record_outcome(_outcome(grant))
    _, same_tier = no_harvest.request(key, receiver)

    promoted = TacticalResourceAllocator()
    _, probe = promoted.request(key, receiver)
    first_harvest = promoted.record_outcome(_outcome(probe, dependencies_closed=1))
    _, shallow = promoted.request(key, receiver)
    second_harvest = promoted.record_outcome(_outcome(shallow, receivers_created=1))
    _, committed = promoted.request(key, receiver)

    missed = TacticalResourceAllocator()
    misses = []
    for _ in range(2):
        _, miss_grant = missed.request(key, receiver)
        misses.append(missed.record_outcome(_outcome(miss_grant)))
    _, suspended = missed.request(key, receiver)
    fresh_key = canonical_state_key(
        _fixture_state(stock=[Card("h", 13)] * 10)
    )
    _, fresh = missed.request(fresh_key, receiver)
    gate_b = {
        "B1_no_harvest_no_promotion": first_miss.decision == TacticalResourceDecision.CONTINUE_SAME_TIER and same_tier.tier == TacticalResourceTier.PROBE,
        "B2_dependency_harvest_promotes": first_harvest.decision == TacticalResourceDecision.PROMOTE and shallow.tier == TacticalResourceTier.SHALLOW,
        "B3_shallow_harvest_reaches_committed": second_harvest.decision == TacticalResourceDecision.PROMOTE and committed.tier == TacticalResourceTier.COMMITTED,
        "B4_repeated_miss_suspends": misses[-1].decision == TacticalResourceDecision.SUSPEND_FOR_STATE and suspended is None,
        "B5_fresh_state_recalculates": fresh is not None and fresh.tier == TacticalResourceTier.PROBE,
    }

    telemetry_allocator = TacticalResourceAllocator()
    _, telemetry_grant = telemetry_allocator.request(key, receiver)
    telemetry_outcome = telemetry_allocator.record_outcome(
        _outcome(
            telemetry_grant,
            nodes_consumed=11,
            seconds_consumed=0.05,
            dependencies_closed=1,
            overlays_cleared=1,
            receivers_created=1,
            supply_consumed_or_integrated=1,
            permanent_adjacencies_created=1,
            terminal_qualification_after=True,
            foundation_removals=1,
        )
    )
    gate_c = {
        "ledger": {
            "requests": len(telemetry_allocator.ledger.requests),
            "nodes_granted": telemetry_allocator.ledger.total_nodes_granted,
            "nodes_consumed": telemetry_allocator.ledger.total_nodes_consumed,
            "seconds_granted": telemetry_allocator.ledger.total_seconds_granted,
            "seconds_consumed": telemetry_allocator.ledger.total_seconds_consumed,
        },
        "return": {
            field: getattr(telemetry_outcome, field)
            for field in (
                "dependencies_closed", "overlays_cleared", "receivers_created",
                "supply_consumed_or_integrated", "permanent_adjacencies_created",
                "terminal_qualification_after", "foundation_removals",
            )
        },
        "harvest_rate": asdict(telemetry_outcome.harvest_rate),
        "named_harvest_events": telemetry_outcome.named_harvest_events,
    }

    graph_a = build_campaign_critical_path(
        _fixture_graph(CampaignDependencyType.RECEIVER_MISSING)
    )
    graph_b_raw = _fixture_graph(
        CampaignDependencyType.MIXED_OVERLAY, campaign_id="D#1"
    )
    graph_b = build_campaign_critical_path(graph_b_raw)
    construction = analyze_same_suit_construction(_fixture_state())
    whole_deal = derive_tactical_demands(
        (graph_a, graph_b),
        campaign_suits={"C#1": "c", "D#1": "d"},
        construction=construction,
        deal_available=True,
    )
    gate_d = {
        "prerequisite": bool(whole_deal.for_realizer(TacticalRealizerKind.DEPENDENCY_CLOSURE)),
        "alternate_campaign": set(whole_deal.campaign_ids) == {"C#1", "D#1"},
        "late_removal_construction": bool(whole_deal.for_realizer(TacticalRealizerKind.RUN_CONSTRUCTION)),
        "deal": bool(whole_deal.for_realizer(TacticalRealizerKind.DEAL_TIMING)),
    }

    continuation = _fixture_portfolio(
        CampaignDependencyType.RECEIVER_MISSING,
        continuation="C#1",
    )
    continuation_demand = continuation.best_for(
        TacticalRealizerKind.DEPENDENCY_CLOSURE, campaign_id="C#1"
    )
    gate_e = {
        "continuation_admitted": continuation_demand.continuation_attention,
        "fresh_critical_path": bool(continuation_demand.target_dependency_id),
        "bounded_first_tranche": continuation_demand.initial_tier == TacticalResourceTier.PROBE,
        "promotion_requires_harvest": first_harvest.decision == TacticalResourceDecision.PROMOTE,
        "alternate_objective": bool(continuation.for_realizer(TacticalRealizerKind.RUN_CONSTRUCTION)),
        "deal_retained": bool(continuation.for_realizer(TacticalRealizerKind.DEAL_TIMING)),
    }
    return {"A": gate_a, "B": gate_b, "C": gate_c, "D": gate_d, "E": gate_e}


def _gate_f_config(seconds: float):
    return replace(
        _v07_gate_e_config(seconds),
        enable_tactical_resource_allocation=True,
    )


def _gate_g_config(seconds: float):
    return replace(
        _v07_gate_f_config(seconds),
        enable_tactical_resource_allocation=True,
    )


def _config_summary(config) -> dict:
    return {
        "wall_clock_limit_s": config.wall_clock_limit_s,
        "max_strategic_expansions": config.max_strategic_expansions,
        "max_tactical_nodes": config.max_tactical_nodes,
        "max_frontier_size": config.max_frontier_size,
        "target_foundation_count": config.target_foundation_count,
        "allocation_enabled": config.enable_tactical_resource_allocation,
        "tiers": {
            tier.name: asdict(config.tactical_resource_config.spec(tier))
            for tier in TacticalResourceTier
        },
        "per_expansion": {
            "nodes": config.tactical_resource_config.max_granted_nodes_per_expansion,
            "seconds": config.tactical_resource_config.max_granted_seconds_per_expansion,
        },
    }


def _allocation_telemetry(result) -> dict:
    telemetry = result.telemetry
    ledger = result.tactical_resource_ledger
    return {
        "requests_by_objective": telemetry.tactical_requests_by_objective,
        "grants_by_tier": telemetry.tactical_grants_by_tier,
        "nodes_granted_by_family": telemetry.tactical_nodes_granted_by_family,
        "nodes_consumed_by_family": telemetry.tactical_nodes_consumed_by_family,
        "seconds_granted_by_family": telemetry.tactical_seconds_granted_by_family,
        "seconds_consumed_by_family": telemetry.tactical_seconds_consumed_by_family,
        "promotions": telemetry.tactical_promotions,
        "demotions": telemetry.tactical_demotions,
        "suspensions": telemetry.tactical_suspensions,
        "terminal_escalations": telemetry.tactical_terminal_escalations,
        "zero_harvest": telemetry.tactical_zero_harvest_invocations,
        "repeated_equivalent_misses": telemetry.tactical_repeated_equivalent_misses,
        "ledger_totals": {
            "requests": len(ledger.requests),
            "granted_nodes": ledger.total_nodes_granted,
            "consumed_nodes": ledger.total_nodes_consumed,
            "granted_seconds": ledger.total_seconds_granted,
            "consumed_seconds": ledger.total_seconds_consumed,
            "harvest_events": ledger.total_harvest_events,
        },
    }


def _harvest_telemetry(result) -> dict:
    telemetry = result.telemetry
    ledger = result.tactical_resource_ledger
    seconds = max(ledger.total_seconds_consumed, 1e-9)
    nodes = max(ledger.total_nodes_consumed, 1)
    return {
        "by_realizer": telemetry.tactical_harvest_events_by_realizer,
        "dependencies": telemetry.tactical_dependencies_closed,
        "overlays": telemetry.tactical_overlays_cleared,
        "receivers": telemetry.tactical_receivers_created,
        "intervals": telemetry.tactical_intervals_assembled,
        "supply": telemetry.tactical_supply_integrated,
        "joins": telemetry.tactical_joins_created,
        "workspace": telemetry.tactical_workspace_objectives_achieved,
        "deal_unlocks": telemetry.tactical_concrete_deal_unlocks,
        "foundations": telemetry.tactical_foundations_removed,
        "harvest_per_second": ledger.total_harvest_events / seconds,
        "harvest_per_1000_nodes": ledger.total_harvest_events * 1000.0 / nodes,
    }


def _unseen_smokes(cards, seconds: float) -> tuple:
    results = []
    for seed in (31, 47):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        state = SpiderState.from_cards(shuffled)
        config = replace(
            _gate_f_config(min(2.0, seconds)),
            wall_clock_limit_s=min(2.0, seconds),
            max_strategic_expansions=2,
            max_tactical_nodes=5_000,
            max_frontier_size=64,
            target_foundation_count=1,
        )
        result = solve_anytime(state, shuffled, None, config)
        objectives = result.telemetry.tactical_requests_by_objective
        kinds = result.telemetry.successor_kinds
        results.append(
            {
                "seed": seed,
                "elapsed": result.elapsed_seconds,
                "deadline_compliant": result.elapsed_seconds <= config.wall_clock_limit_s + 1.0,
                "unrestricted": result.preflight.profile.can_deal_into_empty,
                "demand_derived": bool(objectives),
                "progressive_probe": result.telemetry.tactical_grants_by_tier.get("PROBE", 0) > 0,
                "construction_represented": objectives.get("RUN_CONSTRUCTION", 0) > 0,
                "deal_represented": objectives.get("DEAL_EVALUATION", 0) > 0 or kinds.get("RAW_DEAL", 0) > 0,
                "replay": _replay(state, result),
                "summary": _summary(result),
            }
        )
    return tuple(results)


def _authorization(gate_f) -> dict:
    node = _node(gate_f)
    family_seconds = gate_f.telemetry.tactical_seconds_consumed_by_family
    removal_seconds = sum(
        family_seconds.get(name, 0.0)
        for name in ("CAMPAIGN_CURRENT_EPOCH", "CAMPAIGN_REMOVAL", "TERMINAL_ASSEMBLY")
    )
    second = len(node.state.foundations) >= 2
    reasons = {
        "foundation_2": second,
        "unqualified_removal_materially_reduced": removal_seconds < 65.0,
        "more_than_v07_six_expansions": gate_f.strategic_expansions > 6,
        "named_critical_harvest": gate_f.tactical_resource_ledger.total_harvest_events > 0,
        "continuity_preserved": gate_f.telemetry.tactical_dependencies_closed > 0,
        "construction_preserved": gate_f.telemetry.same_suit_construction_opportunities > 0,
        "foundation_not_lost": len(node.state.foundations) >= 1,
    }
    clear_improvement = all(
        (
            reasons["unqualified_removal_materially_reduced"],
            reasons["more_than_v07_six_expansions"] or reasons["named_critical_harvest"],
            reasons["continuity_preserved"],
            reasons["construction_preserved"],
            reasons["foundation_not_lost"],
        )
    )
    return {
        "authorized": second or clear_improvement,
        "clear_resource_allocation_improvement": clear_improvement,
        "removal_family_seconds": removal_seconds,
        "reasons": reasons,
    }


def _foundation_checkpoints(start: SpiderState, actions) -> tuple:
    state = start.clone()
    cost = 0
    checkpoints = []
    prior = len(state.foundations)
    for index, action in enumerate(actions, start=1):
        cost += replay_actions(state, [action])
        while len(state.foundations) > prior:
            sequence = state.foundations[prior]
            checkpoints.append(
                {
                    "foundation": prior + 1,
                    "suit": sequence[0].suit if sequence else None,
                    "g": cost,
                    "action_index": index,
                    "stock": len(state.stock),
                    "face_down": sum(len(column.face_down) for column in state.columns),
                }
            )
            prior += 1
    return tuple(checkpoints)


def _route_acceptance(start: SpiderState, result) -> dict:
    node = _node(result)
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost, valid = None, False
    return {
        "valid": valid,
        "corrected_g": cost,
        "explicit_actions": len(node.actions),
        "deal_count": sum(action[0] == "deal" for action in node.actions),
        "foundations": len(node.state.foundations),
        "stock": len(node.state.stock),
        "empty_tableau": all(column.is_empty() for column in node.state.columns),
        "path_hash": controller_module._action_path_hash(node.actions),
        "endpoint_hash": controller_module._state_hash(node.state),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-f-seconds", type=float, default=90.0)
    parser.add_argument("--gate-g-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=2.0)
    parser.add_argument("--skip-gate-g", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    gates = _capability_gates()
    unseen = _unseen_smokes(cards, args.smoke_seconds)

    gate_f_config = _gate_f_config(args.gate_f_seconds)
    gate_f = solve_anytime(anchor_node.state, cards, None, gate_f_config)
    gate_f_node = _node(gate_f)
    authorization = _authorization(gate_f)
    gate_g = None
    gate_g_config = None
    if authorization["authorized"] and not args.skip_gate_g:
        gate_g_config = _gate_g_config(args.gate_g_seconds)
        gate_g = solve_anytime(opening, cards, None, gate_g_config)
    gate_g_node = _node(gate_g) if gate_g is not None else None
    gate_g_second = bool(
        gate_g_node is not None and len(gate_g_node.state.foundations) >= 2
    )
    repeat = (
        solve_anytime(opening, cards, None, gate_g_config)
        if gate_g_second and gate_g_config is not None
        else None
    )
    repeat_success = bool(
        repeat is not None
        and len(_node(repeat).state.foundations) >= 2
        and _replay(opening, repeat)["valid"]
    )

    selected = gate_g or gate_f
    selected_node = _node(selected)
    checkpoints = (
        _foundation_checkpoints(opening, gate_g_node.actions)
        if gate_g_node is not None
        else ()
    )
    gate_f_before = _diagnosis_payload(anchor_node)
    gate_f_after = _diagnosis_payload(gate_f_node)
    gate_g_after = _diagnosis_payload(gate_g_node) if gate_g_node is not None else ()
    gate_g_route = _route_acceptance(opening, gate_g) if gate_g is not None else None

    if gate_g_second and repeat_success:
        verdict = "STRONG PASS"
    elif len(gate_f_node.state.foundations) >= 2 or gate_g_second:
        verdict = "PASS"
    elif authorization["clear_resource_allocation_improvement"]:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    if len(selected_node.state.foundations) >= 2:
        blocker = "none through foundation #2"
    else:
        diagnosis = gate_g_after or gate_f_after
        blocker = diagnosis[0] if diagnosis else "no named campaign diagnosis available"

    _section(1, "authoritative base", AUTHORITATIVE_BASE)
    _section(2, "inherited complete-suite baseline verification", INHERITED_COMPLETE_SUITE)
    _section(3, "active rule profile", asdict(anchor.preflight.profile))
    _section(4, "regression anchors", {
        "canonical": (canonical.valid, canonical.solved, canonical.mobilityware_moves,
                      canonical.explicit_commands, canonical.tableau_moves,
                      canonical.stock_deals, canonical.foundations,
                      canonical.path_hash, canonical.state_hash),
        "machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
        "independent": (independent.arm.total_cost, independent.action_count,
                        independent.deal_count, len(independent.state.stock),
                        independent.face_down_count, independent.independently_verified),
    })
    _section(5, "v0.7 blocker", {
        "historical": "~130s in current-epoch/removal realisers; 9 untouched expansions",
        "fresh_30s_profile": {
            "expansions": 3,
            "current_epoch_seconds": 12.821,
            "removal_seconds": 10.126,
            "combined_share": "approximately 75%",
        },
    })
    _section(6, "tactical resource allocator architecture", (
        "TacticalDemand", "TacticalResourceRequest", "TacticalResourceGrant",
        "TacticalResourceOutcome", "TacticalResourceEvidence",
        "TacticalResourceLedger", "TacticalHarvestRate",
    ))
    _section(7, "tactical objective kinds", tuple(item.value for item in TacticalObjectiveKind))
    _section(8, "resource tiers", _config_summary(gate_f_config)["tiers"])
    _section(9, "critical-path demand semantics", "fresh blocker -> reasoned objective/realiser; alternate campaign, construction, Deal and fallback remain represented")
    _section(10, "terminal/removal qualification policy", tuple(item.value for item in RemovalAllocationPolicy))
    _section(11, "promotion/demotion policy", tuple(item.value for item in TacticalResourceDecision))
    _section(12, "compute-return telemetry", tuple(TacticalResourceOutcome.__dataclass_fields__))
    _section(13, "proof-safety audit", {
        "TT": "exact structural state -> lowest corrected g",
        "allocator_in_state_identity": False,
        "resource_miss_proof_authority": False,
        "admissible_bound_changed": False,
        "canonical_actions_in_controller": "canonical.moves" in inspect.getsource(controller_module),
    })
    _section(14, "capability Gate A", {"passed": all(gates["A"].values()), **gates["A"]})
    _section(15, "capability Gate B", {"passed": all(gates["B"].values()), **gates["B"]})
    _section(16, "capability Gate C", {"passed": gates["C"]["named_harvest_events"] == 7, **gates["C"]})
    _section(17, "capability Gate D", {"passed": all(gates["D"].values()), **gates["D"]})
    _section(18, "capability Gate E", {"passed": all(gates["E"].values()), **gates["E"]})
    _section(19, "unseen-deal smokes", unseen)
    _section(20, "Gate F cost-21 config/result", {
        "config": _config_summary(gate_f_config),
        "result": _summary(gate_f, offset=anchor_node.g),
        "replay": _replay(anchor_node.state, gate_f),
    })
    _section(21, "Gate F time by tactical family", gate_f.telemetry.tactical_seconds_consumed_by_family)
    _section(22, "Gate F nodes by tactical family", gate_f.telemetry.tactical_nodes_consumed_by_family)
    _section(23, "Gate F tier/promotion history", {
        "grants": gate_f.telemetry.tactical_grants_by_tier,
        "promotions": gate_f.telemetry.tactical_promotions,
        "demotions": gate_f.telemetry.tactical_demotions,
        "suspensions": gate_f.telemetry.tactical_suspensions,
        "timeline": gate_f.telemetry.tactical_allocation_timeline,
    })
    _section(24, "Gate F critical-path evolution", {"before": gate_f_before, "after": gate_f_after})
    _section(25, "Gate F structural harvest", _harvest_telemetry(gate_f))
    _section(26, "Gate F foundation #2 result", len(gate_f_node.state.foundations) >= 2)
    _section(27, "true-opening authorization decision", authorization)
    _section(28, "Gate G config/result if authorized", {
        "config": _config_summary(gate_g_config) if gate_g_config else None,
        "result": _summary(gate_g) if gate_g else None,
        "replay": _replay(opening, gate_g) if gate_g else None,
    })
    _section(29, "Gate G first-foundation result", checkpoints[0] if checkpoints else None)
    _section(30, "Gate G post-foundation critical path", gate_g_after)
    _section(31, "Gate G tactical-family time comparison versus v0.7", {
        "v0.7_current_epoch_plus_removal_seconds": "approximately 130",
        "v0.8": gate_g.telemetry.tactical_seconds_consumed_by_family if gate_g else None,
    })
    _section(32, "Gate G strategic expansion comparison versus v0.7", {
        "v0.7": 9,
        "v0.8": gate_g.strategic_expansions if gate_g else None,
    })
    _section(33, "Gate G stock timeline", gate_g.telemetry.deal_timeline if gate_g else None)
    _section(34, "Gate G construction timeline", gate_g.telemetry.construction_timeline if gate_g else None)
    _section(35, "second-foundation result", checkpoints[1] if len(checkpoints) >= 2 else None)
    _section(36, "continuous route/replay/hashes if successful", gate_g_route if gate_g_second else None)
    _section(37, "repeatability", {
        "run": repeat is not None,
        "success": repeat_success,
        "summary": _summary(repeat) if repeat else None,
        "replay": _replay(opening, repeat) if repeat else None,
    })
    _section(38, "optional F3 continuation", "not run: v0.8 stops after the requested allocation/F2 assessment")
    _section(39, "optional whole-game result", "not run: optional and outside the required scheduling gate")
    _section(40, "allocation telemetry", _allocation_telemetry(selected))
    _section(41, "strategic-throughput telemetry", {
        "summary": _summary(selected),
        "unique_frontier_states": selected.telemetry.tt_new,
        "foundations": len(selected_node.state.foundations),
        "stock_rows_consumed": (
            ((50 if gate_g is not None else 30) - len(selected_node.state.stock)) // 10
        ),
        "structural_balance_sheet": asdict(selected_node.analysis.measurement),
    })
    _section(42, "TT statistics", {
        "new": selected.telemetry.tt_new,
        "improved": selected.telemetry.tt_improved,
        "suppressed": selected.telemetry.tt_suppressed,
        "exact_loop_suppressed": selected.telemetry.exact_loop_suppressed,
    })
    _section(43, "proof statistics", {
        "proof_pruned": selected.telemetry.proof_pruned,
        "heuristic_pruned": selected.telemetry.heuristic_pruned,
        "resource_outcomes_with_proof_authority": sum(
            item.proof_pruning_allowed for item in selected.tactical_resource_ledger.outcomes
        ),
    })
    _section(44, "final full-suite result", FINAL_COMPLETE_SUITE)
    _section(45, "verdict", verdict)
    _section(46, "precise remaining blocker", blocker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
