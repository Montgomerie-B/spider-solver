#!/usr/bin/env python3
"""Reproducible v0.6 supply-consumption and dependency-closure report.

The cost-21 state is reconstructed only for the explicitly diagnostic Gate C.
The saved v0.5 terminal prefix is unavailable as an action artifact and is
therefore never reconstructed or used as a production seed.  The untouched
Gate E is run only when the capability decision in section 21 authorizes it.
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
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
import spider.planner.campaign_dependency_closure as closure_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.campaign_corridor import CampaignCorridorConfig
from spider.planner.campaign_dependency_closure import (
    DependencyClosureConfig,
    DependencyClosureStatus,
    build_campaign_dependency_graph,
    realize_campaign_dependency_closure,
)
from spider.planner.deal_purpose import (
    DealPurposeKind,
    create_deal_purpose_contract,
    validate_deal_purpose_contract,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.foundation_campaign import CampaignReadiness, RankSource, RankSourceKind
from spider.planner.protected_conversion import diagnose_terminal_conversion
from spider.planner.supply_consumption import (
    CampaignSupplyObligation,
    advance_supply_consumption_results,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "c147a59a4151678fe7945db18f8eccc7949a99c0"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _opening_anchor_config() -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=40.0,
        max_strategic_expansions=5,
        max_tactical_nodes=50_000,
        max_frontier_size=128,
        max_successors_per_expansion=8,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        enable_campaign_corridors=True,
        corridor_config=CampaignCorridorConfig(
            max_epoch_transitions=2,
            max_added_cost=24,
            max_nodes=30_000,
            time_limit_s=12.0,
            beam_width=256,
            max_lanes=2,
            max_source_combinations=64,
        ),
        stop_after_first_foundation=True,
    )


def _gate_c_config(seconds: float) -> AnytimeControllerConfig:
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


def _gate_e_config(seconds: float) -> AnytimeControllerConfig:
    return replace(
        _gate_c_config(seconds),
        wall_clock_limit_s=min(180.0, seconds),
        max_strategic_expansions=50,
        max_tactical_nodes=500_000,
    )


def _node(result):
    return result.most_foundations_node


def _summary(result, *, offset: int = 0):
    node = _node(result)
    measurement = node.analysis.measurement
    return {
        "stop": result.stop_reason,
        "elapsed": round(result.elapsed_seconds, 3),
        "expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "added_g": node.g,
        "total_g": offset + node.g,
        "actions": len(node.actions),
        "foundations": len(node.state.foundations),
        "foundation_suits": tuple(seq[0].suit for seq in node.state.foundations if seq),
        "stock": len(node.state.stock),
        "face_down": measurement.face_down_count,
        "must": node.analysis.progress.total_campaign_must_burden,
        "stable_joins": measurement.stable_same_suit_joins,
        "same_suit_mass": measurement.same_suit_run_mass,
        "mixed_boundaries": measurement.mixed_suit_boundaries,
        "rehandling_debt": measurement.rehandling_debt,
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(node.state),
        "zobrist": format(zobrist(node.state), "x"),
    }


def _replay(start: SpiderState, result):
    node = _node(result)
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost, valid = None, False
    return {
        "valid": valid,
        "cost": cost,
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(node.state),
    }


def _source(suit: str, rank: int) -> RankSource:
    return RankSource(
        f"fixture:{suit}:{rank}", Card(suit, rank), RankSourceKind.SHALLOW_TABLEAU,
        0, "face_up", 1, None, None, True, False, 1, 0, (), False, False,
        "not_applicable", 1.0, "deterministic capability fixture",
    )


def _fixture_campaign(base, *, required_rank: int = 5):
    needs = tuple(
        replace(
            need,
            chosen=(_source("c", need.rank) if need.rank == required_rank else None),
            must_excavate=need.rank == required_rank,
        )
        for need in base.rank_needs
    )
    return replace(
        base,
        suit="c",
        current_epoch=5,
        target_removal_epoch=5,
        rank_needs=needs,
        tableau_critical_cards=tuple(n.chosen for n in needs if n.chosen),
        future_stock_supplied_cards=(),
        prerequisite_excavation_projects=(),
        shared_prerequisite_tasks=(),
        stock_plan=(),
        space_requirement=0,
        estimated_campaign_cost=4.0,
        blockers=(),
        readiness=CampaignReadiness.ASSEMBLY_LED,
    )


def _capability_gates(anchor_node):
    base = anchor_node.analysis.economic.campaign_portfolio.campaigns[0]
    campaign = _fixture_campaign(base)
    columns = [
        Column([], [Card("c", 5), Card("d", 4)]),
        Column([], [Card("d", 5)]),
    ] + [Column([], []) for _ in range(8)]
    closure_start = SpiderState(columns, [])
    closure = realize_campaign_dependency_closure(
        closure_start,
        campaign,
        config=DependencyClosureConfig(max_added_cost=3, max_nodes=100, time_limit_s=1.0),
    )

    row = tuple(
        [Card("c", 5), Card("c", 6)]
        + [Card("h", rank) for rank in range(1, 9)]
    )
    supply_start = SpiderState(
        [Column([], [Card("s", 13)]) for _ in range(10)], list(row)
    )
    profile = anchor_node.analysis.residual.checkpoint
    obligation = CampaignSupplyObligation(
        "fixture-supply", "C#1", Card("c", 5), 5, 0, "stock:5:0",
        "rank:5:c", (5, 5), 6,
    )
    contract = create_deal_purpose_contract(
        supply_start,
        profile,
        campaign_id="C#1",
        explicit_purpose=DealPurposeKind.CAMPAIGN_SUPPLY,
    )
    contract = replace(contract, supply_obligations=(obligation,))
    delivered = advance_supply_consumption_results(
        supply_start, (("deal",),), new_contracts=(contract,)
    )
    after_deal = supply_start.clone()
    after_deal.deal(MW_RULES)
    consumed = advance_supply_consumption_results(
        after_deal, ((0, 1, 1),), existing=delivered
    )
    return {
        "A1_delivered_stage": delivered[0].highest_stage.value,
        "A1_contract": validate_deal_purpose_contract(
            contract, profile, current_depth=1, supply_consumption=delivered[0]
        ).status.value,
        "A2_consumed_stage": consumed[0].highest_stage.value,
        "A2_contract": validate_deal_purpose_contract(
            contract, profile, current_depth=1, supply_consumption=consumed[0]
        ).status.value,
        "B_overlay_closure": closure.status.value,
        "B_actions": closure.actions,
        "B_closed": closure.dependencies_closed,
        "B_overlays": closure.overlays_cleared,
        "B_replay": closure.independent_replay_verified,
        "B_no_deal": ("deal",) not in closure.actions,
    }


def _unseen_smokes():
    values = {}
    for seed in (8301, 8302):
        cards = [
            Card(suit, rank)
            for suit in "cdhs"
            for rank in range(1, 14)
            for _ in range(2)
        ]
        random.Random(seed).shuffle(cards)
        frozen = tuple(cards)
        state = SpiderState.from_cards(frozen)
        result = solve_anytime(
            state,
            frozen,
            None,
            AnytimeControllerConfig(
                wall_clock_limit_s=3.0,
                max_strategic_expansions=1,
                max_tactical_nodes=50,
                max_frontier_size=16,
                max_successors_per_expansion=4,
                enable_campaign_edges=False,
                enable_campaign_corridors=False,
                enable_expensive_deal_timing=False,
            ),
        )
        values[seed] = {
            "preflight": result.preflight.passed,
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "elapsed": round(result.elapsed_seconds, 3),
            "replay_legal_successors": result.telemetry.retained,
            "contracts": result.telemetry.deal_contracts_created,
        }
    return values


def _diagnosis_payload(node):
    diagnosis = diagnose_terminal_conversion(
        node.state, node.analysis.economic.campaign_portfolio.campaigns
    )
    return tuple(
        {
            "campaign": item.campaign_id,
            "near": item.near_removal,
            "must": len(item.remaining_must_sources),
            "deepest": max((source.depth for source in item.remaining_must_sources), default=0),
            "missing": item.missing_rank_intervals,
            "overlays": item.mixed_suit_blockers,
            "macro": item.removal_macro_failure_reason,
        }
        for item in diagnosis.target_campaigns
    )


def _supply_timeline(node):
    outcomes = {item.contract_id: item for item in node.deal_outcome_history}
    supplies = {item.contract_id: item for item in node.supply_consumption_results}
    return tuple(
        {
            "contract": contract.contract_id,
            "row": tuple(str(card) for card in contract.exact_incoming_row),
            "purpose": contract.purpose.value,
            "campaign": contract.campaign_id,
            "promised": tuple(item.dependency_key for item in contract.supply_obligations),
            "stage": supplies[contract.contract_id].highest_stage.value
            if contract.contract_id in supplies
            else "NONE",
            "consumed": supplies[contract.contract_id].consumed_count
            if contract.contract_id in supplies
            else 0,
            "outcome": outcomes[contract.contract_id].status.value
            if contract.contract_id in outcomes
            else "PENDING",
        }
        for contract in node.deal_contract_history
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-c-seconds", type=float, default=90.0)
    parser.add_argument("--gate-e-seconds", type=float, default=180.0)
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    gates = _capability_gates(anchor_node)
    unseen = _unseen_smokes()

    gate_c_config = _gate_c_config(args.gate_c_seconds)
    gate_c = solve_anytime(anchor_node.state, cards, None, gate_c_config)
    gate_c_node = _node(gate_c)
    gate_c_diag = _diagnosis_payload(gate_c_node)
    leading = gate_c_diag[0] if gate_c_diag else None
    gate_c_second = len(gate_c_node.state.foundations) >= 2
    major = bool(
        gate_c_second
        or gate_c.telemetry.terminal_qualification_transitions
        or gate_c.telemetry.supplied_assets_consumed_by_closure
        or (leading is not None and leading["must"] <= 1)
    )
    # Gate D is unavailable because v0.5 committed no replayable 73-action
    # artifact.  Hashes alone are not enough to reconstruct a legal state.
    gate_d = None
    authorize_e = gate_c_second or major
    gate_e_config = _gate_e_config(args.gate_e_seconds) if authorize_e else None
    gate_e = (
        solve_anytime(SpiderState.from_cards(cards), cards, None, gate_e_config)
        if authorize_e and gate_e_config is not None
        else None
    )
    gate_e_node = _node(gate_e) if gate_e is not None else None
    second = bool(gate_e_node is not None and len(gate_e_node.state.foundations) >= 2)
    repeat = (
        solve_anytime(SpiderState.from_cards(cards), cards, None, gate_e_config)
        if second and gate_e_config is not None
        else None
    )

    _section(1, "authoritative base", AUTHORITATIVE_BASE)
    _section(2, "active rule profile", asdict(anchor.preflight.profile))
    _section(3, "regression anchors", {
        "canonical": (canonical.valid, canonical.solved, canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.stock_deals, canonical.foundations, canonical.path_hash, canonical.state_hash),
        "machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
        "independent": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        "v0.5_terminal": "unavailable: no committed replayable 73-action prefix",
    })
    _section(4, "v0.5 blocker summary", "g=73, one foundation, stock empty, face-down 25, MUST 28; Diamond #1 had two compulsory sources, missing rank 3, and mixed overlays")
    _section(5, "supply-consumption lifecycle", tuple(item.value for item in controller.SupplyConsumptionStage))
    _section(6, "dependency-closure architecture", tuple(closure_module.DependencyClosureResult.__dataclass_fields__))
    _section(7, "dependency types/graph", tuple(item.value for item in closure_module.CampaignDependencyType))
    _section(8, "overlay-clearing semantics", "every action cites a named dependency; temporary parks require a bounded exit; lifecycle debt only orders")
    _section(9, "bridge to terminal assembler", "closure successor is freshly reanalysed; unchanged near-removal predicate gates terminal assembly")
    _section(10, "proof-safety audit", {
        "exact_tt": "canonical structural state -> lowest corrected g",
        "closure_in_identity": False,
        "supply_in_identity": False,
        "admissible_h": "remaining Deals + unavoidable paid reveals",
        "proof_lines": tuple(line.strip() for line in inspect.getsource(controller.solve_anytime).splitlines() if "proof_prunable" in line),
    })
    _section(11, "capability Gate A results", {key: value for key, value in gates.items() if key.startswith("A")})
    _section(12, "capability Gate B results", {key: value for key, value in gates.items() if key.startswith("B")})
    _section(13, "unseen-deal capability smokes", unseen)
    _section(14, "Gate C cost-21 config/result", {"config": asdict(gate_c_config), "result": _summary(gate_c, offset=anchor_node.g), "replay": _replay(anchor_node.state, gate_c)})
    _section(15, "Gate C leading campaign dependency graph", gate_c_diag)
    _section(16, "supply assets consumed/unconsumed", _supply_timeline(gate_c_node))
    _section(17, "dependencies closed", gate_c.telemetry.dependency_closure_timeline)
    _section(18, "Gate C second-foundation result or blocker", {"found": gate_c_second, "leading": leading})
    _section(19, "Gate D terminal-state config/result", "not run: diagnostic action artifact unavailable; hashes were not treated as a seed")
    _section(20, "Gate D dependencies/overlays cleared", None)
    _section(21, "authorization decision for true-opening gate", {"authorized": authorize_e, "Gate_C_second": gate_c_second, "major_capability_threshold": major, "rule": "Section 28 hard capability decision"})
    _section(22, "Gate E config/result", {"config": asdict(gate_e_config), "result": _summary(gate_e)} if gate_e is not None else {"not_run": "capability threshold not met"})
    _section(23, "first-foundation timeline", gate_e.telemetry.foundation_timeline if gate_e is not None else None)
    _section(24, "post-foundation supply-contract timeline", _supply_timeline(gate_e_node) if gate_e_node is not None else None)
    _section(25, "closure attempts before each later Deal", tuple(asdict(item) for item in gate_e.successive_deal_audit) if gate_e is not None else None)
    _section(26, "second-foundation result", second)
    _section(27, "exact continuous route if found", gate_e_node.actions if second else None)
    _section(28, "replay/hash verification", _replay(opening, gate_e) if gate_e is not None else None)
    _section(29, "repeatability", _summary(repeat) if repeat is not None else {"not_run": "two-foundation Gate E did not succeed"})
    _section(30, "optional foundation-3 continuation", None)
    _section(31, "optional whole-game result", None)
    _section(32, "supply lifecycle statistics", {
        key: getattr(gate_c.telemetry, key)
        for key in (
            "supply_contracts_created", "supply_assets_promised", "supply_assets_delivered",
            "supply_assets_available", "supply_assets_consumed", "supply_assets_integrated",
            "supply_assets_invalidated", "delivered_but_unconsumed_contracts", "full_supply_fulfilments",
        )
    })
    _section(33, "dependency-closure statistics", {
        "graphs": gate_c.telemetry.dependency_graphs_built,
        "by_type": gate_c.telemetry.dependencies_by_type,
        "attempts": gate_c.telemetry.dependency_closure_attempts,
        "successes": gate_c.telemetry.dependency_closure_successes,
        "nodes": gate_c.telemetry.dependency_closure_nodes,
        "closed": gate_c.telemetry.dependencies_closed,
        "overlays": gate_c.telemetry.overlays_cleared,
        "failures": gate_c.telemetry.dependency_closure_failures,
        "seconds": gate_c.telemetry.dependency_closure_seconds,
        "max_seconds": gate_c.telemetry.dependency_closure_max_seconds,
    })
    _section(34, "protected-lane statistics", {
        "created": gate_c.telemetry.protected_lanes_created,
        "continued": gate_c.telemetry.protected_lanes_continued,
        "milestones": gate_c.telemetry.removal_relevant_milestones_reached,
        "closure_replans": gate_c.telemetry.protected_lane_replans_after_closure,
    })
    _section(35, "Deal lifecycle audit", tuple(asdict(item) for item in gate_c.successive_deal_audit))
    _section(36, "analysis/deadline statistics", {"elapsed": gate_c.elapsed_seconds, "overrun": max(0.0, gate_c.elapsed_seconds - gate_c_config.wall_clock_limit_s), "stages": (gate_c.telemetry.stage0_analyses, gate_c.telemetry.stage1_analyses, gate_c.telemetry.stage2_analyses), "component_timings": gate_c.telemetry.component_timings})
    _section(37, "TT statistics", {"new": gate_c.telemetry.tt_new, "improved": gate_c.telemetry.tt_improved, "suppressed": gate_c.telemetry.tt_suppressed})
    _section(38, "proof statistics", {"proof_pruned": gate_c.telemetry.proof_pruned, "heuristic_pruned": gate_c.telemetry.heuristic_pruned, "incumbent": gate_c.initial_incumbent_cost})
    verdict = "STRONG PASS" if second and repeat is not None and len(_node(repeat).state.foundations) >= 2 else ("PASS" if gate_c_second else "PARTIAL")
    _section(39, "verdict", verdict)
    _section(40, "precise remaining blocker", "none for foundation #2" if second or gate_c_second else leading)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
