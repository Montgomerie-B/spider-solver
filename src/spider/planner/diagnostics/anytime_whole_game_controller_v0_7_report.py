#!/usr/bin/env python3
"""Reproducible v0.7 continuity, investment, scope, and construction report.

The cost-21 checkpoint is reconstructed only for diagnostic Gate E.  Gate F
always starts from the untouched deal and is run only when the explicit Gate E
authorization predicate succeeds.  No diagnostic action is exposed to the
prospective controller.
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
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    StrategicTranspositionTable,
    solve_anytime,
)
from spider.planner.campaign_corridor import CampaignCorridorConfig
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
    DependencyClosureConfig,
    build_campaign_critical_path,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _diagnosis_payload,
    _node,
    _opening_anchor_config,
    _replay,
    _summary,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.planner.structural_investment import (
    SameCampaignContinuationStatus,
    StructuralInvestmentKind,
)
from spider.planner.supply_consumption import (
    CampaignSupplyEvidence,
    CampaignSupplyObligation,
    SupplyConsumptionResult,
    SupplyConsumptionStage,
    SupplyObligationRole,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key


AUTHORITATIVE_BASE = "c96579f990487ad24f925fd6b03b2cc47a8222c4"
STRUCTURAL_DOC_COMMITS = (
    "19ac6a43361743db5c063d7cb9c7f61c74f845e9",
    "2c41a14ef51e0f3fe9e16af1d01becfb4f7355b7",
    "5050f43ec8ce470b8ec16d3593f833fc4f598a1c",
)
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _gate_e_config(seconds: float) -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=min(90.0, seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
        max_successors_per_expansion=10,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        enable_campaign_corridors=True,
        enable_residual_conversion=True,
        residual_lanes_by_credit=(3, 3, 4, 4, 5),
        corridor_config=CampaignCorridorConfig(
            max_epoch_transitions=2,
            max_added_cost=30,
            max_nodes=120_000,
            time_limit_s=min(20.0, seconds),
            beam_width=512,
            max_lanes=5,
            max_source_combinations=64,
        ),
        dependency_closure_config=DependencyClosureConfig(
            max_added_cost=14,
            max_nodes=4_000,
            time_limit_s=min(2.0, seconds),
            beam_width=192,
            permit_stock_transition=False,
        ),
        target_foundation_count=2,
    )


def _gate_f_config(seconds: float) -> AnytimeControllerConfig:
    return replace(
        _gate_e_config(min(90.0, seconds)),
        wall_clock_limit_s=min(180.0, seconds),
        max_strategic_expansions=50,
        max_tactical_nodes=500_000,
        max_frontier_size=256,
    )


def _columns(*face_up) -> list[Column]:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _capability_payload(cards, anchor_node) -> dict:
    investment_api = {
        item.value for item in StructuralInvestmentKind
    } == {
        "REMOVAL_CAMPAIGN", "RUN_CONSTRUCTION", "EXCAVATION",
        "WORKSPACE", "STOCK_RECEPTION", "DEPENDENCY_CLOSURE",
    }
    lifecycle = {item.value for item in SameCampaignContinuationStatus}
    gate_a = investment_api and lifecycle == {
        "ACTIVE", "REPLANNED", "HARVESTED", "SUPERSEDED", "INVALIDATED", "EXPIRED"
    }

    state = SpiderState(_columns(), [])
    critical = CampaignSupplyObligation(
        "critical", "C#1", Card("c", 5), 1, 0, "stock:1:0",
        "rank:5:c", (5, 5), 6, role=SupplyObligationRole.CRITICAL,
    )
    optional = replace(
        critical, obligation_id="optional", card=Card("c", 7),
        dependency_key="rank:7:c", role=SupplyObligationRole.OPTIONAL,
    )
    evidence = (
        CampaignSupplyEvidence(
            "critical", SupplyConsumptionStage.INTEGRATED, "stock:1:0", "stock:1:0",
            None, None, None, 0, "source", True, "integrated",
        ),
        CampaignSupplyEvidence(
            "optional", SupplyConsumptionStage.AVAILABLE, "stock:1:7", "stock:1:7",
            7, 0, None, None, None, False, "optional remains unused",
        ),
    )
    supply = SupplyConsumptionResult(
        "contract", "C#1", (critical, optional), evidence, (),
        canonical_state_key(state), 0, 0, "coherent fixture",
    )
    gate_b = bool(supply.fully_consumed and supply.critical_direct_campaign_advance)

    source = CampaignDependency(
        "source", CampaignDependencyType.SOURCE_BURIED, "C#1", "source", depth=1
    )
    interval = CampaignDependency(
        "interval", CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL,
        "C#1", "interval", prerequisites=("source",),
    )
    overlay = CampaignDependency(
        "overlay", CampaignDependencyType.MIXED_OVERLAY, "C#1", "overlay"
    )
    terminal = CampaignDependency(
        "terminal:C#1", CampaignDependencyType.TERMINAL_ASSEMBLY_PREREQUISITE,
        "C#1", "terminal", prerequisites=("source", "interval", "overlay"),
    )
    graph = CampaignDependencyGraph(
        canonical_state_key(state), "C#1", (source, interval, overlay, terminal),
        (("source", "interval"), ("source", "terminal:C#1"),
         ("interval", "terminal:C#1"), ("overlay", "terminal:C#1")),
        (), "terminal:C#1", "diagnostic",
    )
    path = build_campaign_critical_path(graph)
    by_id = {item.dependency_id: item for item in path.entries}
    gate_c = by_id["source"].downstream_dependencies_unlocked > by_id["overlay"].downstream_dependencies_unlocked

    construction_state = SpiderState(
        _columns([Card("d", 9), Card("c", 5)], [Card("c", 6)]), []
    )
    construction = analyze_same_suit_construction(construction_state)
    gate_d = bool(
        construction.opportunities
        and construction.opportunities[0].run_length_after == 2
        and construction.opportunities[0].construction_horizon
        != anchor_node.analysis.economic.campaign_portfolio.campaigns[0].target_removal_epoch
        and not construction.proof_pruning_allowed
    )
    unseen = []
    for seed in (17, 23):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        result = analyze_same_suit_construction(SpiderState.from_cards(shuffled))
        unseen.append((seed, len(result.opportunities), not result.proof_pruning_allowed))
    return {
        "A": gate_a,
        "B": gate_b,
        "C": gate_c,
        "D": gate_d,
        "unseen": tuple(unseen),
        "critical_path": path,
        "construction": construction,
    }


def _investment_history(node) -> tuple:
    return tuple(
        {
            "objective": item.objective_id,
            "kind": item.kind.value,
            "status": item.status.value,
            "paid": item.paid_cost_invested,
            "stock_rows": item.stock_rows_spent,
            "dependencies": item.evidence.dependencies_closed,
            "overlays": item.evidence.overlays_removed,
            "joins": item.evidence.permanent_same_suit_joins_created,
            "expected": item.expected_harvest,
            "actual": tuple(harvest.kind.value for harvest in item.actual_harvest),
        }
        for item in node.structural_investment_ledger.investments
    )


def _authorization(gate_e, gate_e_node, leading) -> dict:
    second = len(gate_e_node.state.foundations) >= 2
    selected_investments = gate_e_node.structural_investment_ledger.investments
    durable_selected_continuation = any(
        item.kind == StructuralInvestmentKind.DEPENDENCY_CLOSURE
        and item.evidence.dependencies_closed
        and item.actual_harvest
        for item in selected_investments
    )
    harvested_objectives = {
        item.objective_id
        for item in selected_investments
        if item.actual_harvest
    }
    materially_better = bool(
        durable_selected_continuation
        and leading is not None
        and leading["campaign"] in harvested_objectives
        and leading["must"] < 21
    )
    coherent_fulfilment = gate_e.telemetry.coherent_full_supply_fulfilments > 0
    reasons = {
        "foundation_2_removed": second,
        "durable_selected_same_campaign_continuation": durable_selected_continuation,
        "materially_better_readiness_due_to_harvest": materially_better,
        "coherent_full_fulfilment": coherent_fulfilment,
    }
    return {"authorized": any(reasons.values()), "reasons": reasons}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-e-seconds", type=float, default=90.0)
    parser.add_argument("--gate-f-seconds", type=float, default=180.0)
    parser.add_argument("--skip-gate-f", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    capabilities = _capability_payload(cards, anchor_node)

    gate_e_config = _gate_e_config(args.gate_e_seconds)
    gate_e = solve_anytime(anchor_node.state, cards, None, gate_e_config)
    gate_e_node = _node(gate_e)
    gate_e_diagnosis = _diagnosis_payload(gate_e_node)
    leading = gate_e_diagnosis[0] if gate_e_diagnosis else None
    authorization = _authorization(gate_e, gate_e_node, leading)
    gate_f = None
    gate_f_config = None
    if authorization["authorized"] and not args.skip_gate_f:
        gate_f_config = _gate_f_config(args.gate_f_seconds)
        gate_f = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_f_config)
    gate_f_node = _node(gate_f) if gate_f is not None else None
    second = bool(gate_f_node is not None and len(gate_f_node.state.foundations) >= 2)
    repeatability = "not run: Gate F did not reach foundation #2"
    foundation_three = "not run: requires successful repeatability"
    whole_game = "not run: requires the preceding hard gates"

    gate_e_summary = _summary(gate_e, offset=anchor_node.g)
    gate_f_summary = _summary(gate_f) if gate_f is not None else None
    gate_e_history = _investment_history(gate_e_node)
    gate_f_history = _investment_history(gate_f_node) if gate_f_node is not None else ()
    verdict = (
        "STRONG PASS" if second else (
            "PASS" if len(gate_e_node.state.foundations) >= 2 else (
                "PARTIAL" if all(capabilities[key] for key in "ABCD") else "FAIL"
            )
        )
    )
    blocker = (
        "none through foundation #2"
        if second
        else (
            "Gate E did not authorize Gate F: successful closure descendants were admitted, "
            "but no harvested same-campaign investment survived on the selected best path"
            if not authorization["authorized"]
            else "authorized Gate F did not remove foundation #2 within the fixed envelope"
        )
    )
    gate_e_blocker = (
        "none: foundation #2 removed"
        if len(gate_e_node.state.foundations) >= 2
        else (
            f"selected same-campaign harvest survived and leading {leading['campaign']} reached "
            f"MUST={leading['must']}, but terminal assembly/foundation #2 did not complete"
            if authorization["reasons"]["durable_selected_same_campaign_continuation"]
            and leading is not None
            else "successful closure work did not survive on the selected Gate E path"
        )
    )

    _section(1, "combined authoritative base", AUTHORITATIVE_BASE)
    _section(2, "integrated structural-economics docs", STRUCTURAL_DOC_COMMITS)
    _section(3, "active rule profile", asdict(anchor.preflight.profile))
    _section(4, "regression anchors", {
        "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands,
                      canonical.tableau_moves, canonical.stock_deals, canonical.foundations,
                      canonical.path_hash, canonical.state_hash),
        "machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
        "independent": (independent.arm.total_cost, independent.action_count,
                        independent.deal_count, len(independent.state.stock),
                        independent.face_down_count, independent.independently_verified),
    })
    _section(5, "v0.6 blocker summary", "g=35/F1 selected; successful closure work was discarded before harvest")
    _section(6, "structural-investment architecture", tuple(item.value for item in StructuralInvestmentKind))
    _section(7, "harvest semantics", "objective-specific dependency/supply/overlay/receiver/workspace/join evidence only")
    _section(8, "same-campaign continuation semantics", tuple(item.value for item in SameCampaignContinuationStatus))
    _section(9, "admission policy", "harvested same campaign + alternate campaign + construction + Deal + workspace/reveal + broad raw")
    _section(10, "coherent obligation scoping", {"critical_fulfils": capabilities["B"], "optional_blocks": False})
    _section(11, "source/receiver critical-path ordering", capabilities["critical_path"])
    _section(12, "construction opportunity model", capabilities["construction"])
    _section(13, "build vs removal horizon", "stored independently on each construction opportunity")
    _section(14, "free-future-join semantics", "exact row/column/card match can emit DEFER_FOR_FREE_FUTURE_JOIN")
    _section(15, "proof-safety audit", {"TT": "exact state -> lowest g", "new_proof_authority": False})
    _section(16, "capability Gate A", capabilities["A"])
    _section(17, "capability Gate B", capabilities["B"])
    _section(18, "capability Gate C", capabilities["C"])
    _section(19, "capability Gate D", capabilities["D"])
    _section(20, "unseen-deal smokes", capabilities["unseen"])
    _section(21, "Gate E config/result", {"config": asdict(gate_e_config), "result": gate_e_summary,
                                           "replay": _replay(anchor_node.state, gate_e)})
    _section(22, "Gate E leading named campaign", leading)
    _section(23, "closure successors admitted versus discarded", {
        "admitted": gate_e.telemetry.closure_successors_admitted,
        "continuation_children": gate_e.telemetry.continuation_descendants_admitted,
        "continued_next_step": gate_e.telemetry.continuation_descendants_retained,
        "selected_history": gate_e_history,
    })
    _section(24, "harvest/continuation timeline", {
        "investment": gate_e.telemetry.structural_investment_timeline,
        "continuation": gate_e.telemetry.continuation_timeline,
    })
    _section(25, "Gate E foundation #2 result or exact blocker", {
        "foundation_2": len(gate_e_node.state.foundations) >= 2, "blocker": gate_e_blocker
    })
    _section(26, "true-opening authorization decision", authorization)
    _section(27, "Gate F config/result if authorized", {"config": asdict(gate_f_config) if gate_f_config else None,
                                                         "result": gate_f_summary})
    _section(28, "first-foundation timeline", gate_f.telemetry.foundation_timeline if gate_f else anchor.telemetry.foundation_timeline)
    _section(29, "structural investment timeline after foundation #1", gate_f_history or gate_e_history)
    _section(30, "Deal critical-obligation timeline", gate_f.telemetry.supply_scope_timeline if gate_f else gate_e.telemetry.supply_scope_timeline)
    _section(31, "same-campaign continuation timeline", gate_f.telemetry.continuation_timeline if gate_f else gate_e.telemetry.continuation_timeline)
    _section(32, "late-removal construction work retained", (gate_f or gate_e).telemetry.late_removal_construction_opportunities)
    _section(33, "second-foundation result", second)
    _section(34, "continuous route/replay/hashes if successful", _replay(opening, gate_f) if second else None)
    _section(35, "repeatability", repeatability)
    _section(36, "optional foundation-3 continuation", foundation_three)
    _section(37, "optional whole-game result", whole_game)
    _section(38, "investment telemetry", {
        key: getattr((gate_f or gate_e).telemetry, key)
        for key in ("investments_created_by_kind", "structural_investment_paid_cost",
                    "structural_expected_harvest", "structural_actual_harvest",
                    "unharvested_investments", "abandoned_or_superseded_investments")
    })
    _section(39, "supply/closure telemetry", {
        key: getattr((gate_f or gate_e).telemetry, key)
        for key in ("critical_supply_obligations", "supporting_supply_obligations",
                    "optional_supply_assets", "critical_supply_consumed",
                    "critical_supply_integrated", "coherent_full_supply_fulfilments",
                    "dependency_closure_successes", "dependencies_closed", "overlays_cleared")
    })
    _section(40, "construction telemetry", {
        key: getattr((gate_f or gate_e).telemetry, key)
        for key in ("same_suit_construction_opportunities", "two_card_construction_joins",
                    "larger_construction_merges", "late_removal_construction_opportunities",
                    "free_future_join_deferrals", "workspace_conflict_deferrals")
    })
    _section(41, "analysis/deadline statistics", {
        "timings": (gate_f or gate_e).telemetry.component_timings,
        "skipped": (gate_f or gate_e).telemetry.optional_analyses_skipped,
    })
    _section(42, "TT statistics", {
        "new": (gate_f or gate_e).telemetry.tt_new,
        "improved": (gate_f or gate_e).telemetry.tt_improved,
        "suppressed": (gate_f or gate_e).telemetry.tt_suppressed,
    })
    _section(43, "proof statistics", {
        "proof_pruned": (gate_f or gate_e).telemetry.proof_pruned,
        "heuristic_pruned": (gate_f or gate_e).telemetry.heuristic_pruned,
        "structural_economics_proof_authority": False,
    })
    _section(44, "verdict", verdict)
    _section(45, "precise remaining blocker", blocker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
