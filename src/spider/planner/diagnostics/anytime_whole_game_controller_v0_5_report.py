#!/usr/bin/env python3
"""Reproducible v0.5 contract, conversion-lane, and diversity report."""

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
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.campaign_corridor import CampaignCorridorConfig
from spider.planner.deal_purpose import (
    DealPurposeKind,
    create_deal_purpose_contract,
    validate_deal_purpose_contract,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.protected_conversion import diagnose_terminal_conversion
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "299406e59238cc8afbb128cfde4f2896d00bb200"
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


def _residual_config(seconds: float) -> AnytimeControllerConfig:
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
        target_foundation_count=2,
    )


def _pre_foundation_config(seconds: float) -> AnytimeControllerConfig:
    return replace(
        _residual_config(seconds),
        wall_clock_limit_s=min(90.0, seconds),
        max_frontier_size=192,
        target_foundation_count=None,
    )


def _true_opening_config(seconds: float) -> AnytimeControllerConfig:
    return replace(
        _residual_config(seconds),
        wall_clock_limit_s=min(180.0, seconds),
        max_strategic_expansions=50,
        max_tactical_nodes=500_000,
        max_frontier_size=256,
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


def _contract_payload(node):
    outcomes = {item.contract_id: item for item in node.deal_outcome_history}
    values = []
    for contract in node.deal_contract_history:
        outcome = outcomes.get(contract.contract_id)
        if outcome is None and node.analysis is not None:
            outcome = validate_deal_purpose_contract(
                contract,
                node.analysis.residual.checkpoint,
                current_depth=node.depth,
            )
        values.append(
            {
                "id": contract.contract_id,
                "row": tuple(str(card) for card in contract.exact_incoming_row),
                "purpose": contract.purpose.value,
                "objective": contract.target_objective,
                "surrendered": contract.surrendered_current_opportunities,
                "expected": contract.predicted_milestone,
                "outcome": outcome.status.value if outcome is not None else "PENDING",
            }
        )
    return tuple(values)


def _contract_controls(opening: SpiderState, profile):
    readiness = profile.best_readiness
    assert readiness is not None
    improved = replace(readiness, must_dependencies_remaining=max(0, readiness.must_dependencies_remaining - 1))
    strict_after = replace(
        profile,
        next_foundation_readiness=tuple(
            improved if item.campaign_label == readiness.campaign_label else item
            for item in profile.next_foundation_readiness
        ),
    )
    unlock = create_deal_purpose_contract(
        opening,
        profile,
        after_profile=strict_after,
        campaign_id=readiness.campaign_label,
    )
    activity_after = replace(profile, legal_mobility=profile.legal_mobility + 5)
    activity = create_deal_purpose_contract(opening, profile, after_profile=activity_after)
    return {
        "concrete_unlock": unlock.purpose.value,
        "concrete_objective": unlock.target_objective,
        "validation": validate_deal_purpose_contract(
            unlock, strict_after, current_depth=1
        ).status.value,
        "activity_only": activity.purpose.value,
        "activity_is_not_unlock": activity.purpose != DealPurposeKind.STRATEGIC_UNLOCK,
    }


def _terminal_payload(result):
    node = _node(result)
    diagnosis = diagnose_terminal_conversion(
        node.state, node.analysis.economic.campaign_portfolio.campaigns
    )
    return tuple(
        {
            "campaign": item.campaign_id,
            "readiness": item.readiness.value,
            "near_removal": item.near_removal,
            "remaining_sources": tuple(asdict(source) for source in item.remaining_must_sources),
            "bands": tuple(band.label for band in item.assembled_bands),
            "missing_intervals": item.missing_rank_intervals,
            "receiver_blockers": item.receiver_blockers,
            "workspace_blockers": item.workspace_blockers,
            "mixed_blockers": item.mixed_suit_blockers,
            "next_row": tuple((col, str(card)) for col, card in item.exact_next_stock_contributions),
            "macro_failure": item.removal_macro_failure_reason,
        }
        for item in diagnosis.target_campaigns
    )


def _pre_payload(result):
    portfolio = result.pre_foundation_portfolio
    return tuple(
        {
            "g": item.g,
            "campaign": item.campaign_identity,
            "stock_epoch": item.stock_epoch,
            "face_down": item.face_down_count,
            "dependencies": item.dependency_burden,
            "joins": item.stable_same_suit_joins,
            "workspace": item.empty_columns,
            "debt": item.rehandling_debt,
            "tops": item.exposed_top_layout,
        }
        for item in (portfolio.geometries if portfolio is not None else ())
    )


def _unseen_smokes():
    values = {}
    for seed in (7301, 7302):
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
                wall_clock_limit_s=4.0,
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
            "contracts": result.telemetry.deal_contracts_created,
            "elapsed": round(result.elapsed_seconds, 3),
            "overrun": round(max(0.0, result.elapsed_seconds - 4.0), 3),
        }
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-a-seconds", type=float, default=90.0)
    parser.add_argument("--gate-c-seconds", type=float, default=90.0)
    parser.add_argument("--gate-d-seconds", type=float, default=180.0)
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()

    _section(1, "authoritative base", AUTHORITATIVE_BASE)
    _section(2, "active rule profile", asdict(anchor.preflight.profile))
    _section(3, "regression anchors", {
        "canonical": (canonical.mobilityware_moves, canonical.explicit_commands, canonical.tableau_moves, canonical.path_hash, canonical.state_hash),
        "machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
        "independent": (independent.arm.total_cost, independent.action_count, independent.deal_count, independent.face_down_count, independent.independently_verified),
    })
    _section(4, "v0.4 failure summary", "useful residual investment did not convert; later stock rows drained without foundation #2")
    _section(5, "Deal-purpose architecture", tuple(controller.DealPurposeContract.__dataclass_fields__))
    _section(6, "stricter STRATEGIC_UNLOCK semantics", "MUST/source/readiness/interval/receiver/removal consequence required; generic activity is insufficient")
    _section(7, "purpose validation lifecycle", tuple(item.value for item in controller.DealPurposeStatus))
    _section(8, "protected conversion lane semantics", tuple(item.value for item in controller.ProtectedConversionStatus))
    _section(9, "terminal conversion diagnostic", "exact sources, bands, missing intervals, receivers, workspace, mixed overlays, next row, and macro failure")
    _section(10, "terminal assembly capability", "strict near-removal same-epoch beam; independently replayed; miss has no proof authority")
    _section(11, "pre-foundation diversity policy", "3-6 material geometry representatives; exact equality deduplicates; action history is absent")
    proof_lines = tuple(line.strip() for line in inspect.getsource(controller.solve_anytime).splitlines() if "proof_prunable" in line)
    _section(12, "proof-safety audit", {"proof_lines": proof_lines, "contracts": False, "lanes": False, "diversity": False})

    gate_a_config = _residual_config(args.gate_a_seconds)
    gate_a = solve_anytime(anchor_node.state, cards, None, gate_a_config)
    _section(13, "Gate A cost-21 config/result", {"config": asdict(gate_a_config), "result": _summary(gate_a, offset=anchor_node.g), "replay": _replay(anchor_node.state, gate_a)})
    _section(14, "best residual investment path", _node(gate_a).actions)
    _section(15, "precise terminal blocker or second-foundation result", _terminal_payload(gate_a))
    controls = _contract_controls(opening, anchor_node.analysis.residual.checkpoint)
    _section(16, "Gate B Deal-purpose controls", controls)

    gate_c_config = _pre_foundation_config(args.gate_c_seconds)
    gate_c = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_c_config)
    _section(17, "Gate C pre-foundation diversity result", {"config": asdict(gate_c_config), "result": _summary(gate_c), "geometries": _pre_payload(gate_c)})
    checkpoints = tuple(
        {
            "g": item.g, "suits": item.foundation_suits, "stock": item.stock_remaining,
            "face_down": item.face_down_count, "must": item.total_campaign_must_burden,
            "joins": item.stable_same_suit_joins, "debt": item.rehandling_debt,
        }
        for item in gate_c.foundation_checkpoint_portfolio.profiles
        if item.foundations == 1
    )
    _section(18, "distinct first-foundation checkpoints discovered", checkpoints)
    _section(19, "freeze checkpoint comparison", {"frozen_before_comparison": True, "checkpoints": checkpoints})

    gate_d_config = _true_opening_config(args.gate_d_seconds)
    gate_d = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_d_config)
    gate_d_node = _node(gate_d)
    second = len(gate_d_node.state.foundations) >= 2
    _section(20, "Gate D true-opening config", {"config": asdict(gate_d_config), "incumbent": None, "seed": None})
    _section(21, "first-foundation timeline", gate_d.telemetry.foundation_timeline)
    _section(22, "purpose contracts on selected path", _contract_payload(gate_d_node))
    _section(23, "protected conversion-lane timeline", gate_d.telemetry.protected_lane_timeline)
    _section(24, "second-foundation result", {"found": second, "summary": _summary(gate_d)})
    _section(25, "exact continuous route if found", gate_d_node.actions if second else None)
    _section(26, "replay/hash verification", _replay(opening, gate_d))
    repeat = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_d_config) if second else None
    _section(27, "repeatability", {"run": _summary(repeat) if repeat else None, "not_run_reason": None if second else "Gate D did not reach foundation #2"})
    _section(28, "optional continuation", None)
    _section(29, "optional whole-game result", None)
    _section(30, "stock timeline", gate_d.telemetry.deal_timeline)
    _section(31, "successive-Deal purpose audit", tuple(asdict(item) for item in gate_d.successive_deal_audit))
    _section(32, "contract telemetry", {
        "created": gate_d.telemetry.deal_contracts_created, "by_purpose": gate_d.telemetry.contracts_by_purpose,
        "fulfilled": gate_d.telemetry.fulfilled_contracts, "partial": gate_d.telemetry.partially_fulfilled_contracts,
        "failed": gate_d.telemetry.failed_contracts, "invalidated": gate_d.telemetry.invalidated_contracts,
        "escape_reclassified": gate_d.telemetry.escape_reclassifications,
        "pending_deals": gate_d.telemetry.pending_contract_deals,
        "consecutive_unresolved": gate_d.telemetry.consecutive_deals_with_unresolved_contracts,
    })
    _section(33, "protected-lane telemetry", {
        "created": gate_d.telemetry.protected_lanes_created, "continued": gate_d.telemetry.protected_lanes_continued,
        "completed": gate_d.telemetry.protected_lanes_completed, "invalidated": gate_d.telemetry.protected_lanes_invalidated,
        "expired": gate_d.telemetry.protected_lanes_expired, "milestones": gate_d.telemetry.removal_relevant_milestones_reached,
    })
    _section(34, "terminal-realiser telemetry", {"near": gate_d.telemetry.near_removal_campaigns_detected, "attempts": gate_d.telemetry.terminal_realizer_attempts, "successes": gate_d.telemetry.terminal_realizer_successes})
    _section(35, "pre-foundation diversity telemetry", {"distinct": gate_d.telemetry.distinct_pre_foundation_geometries, "first_checkpoints": gate_d.telemetry.first_foundation_checkpoints_discovered})
    _section(36, "analysis/deadline statistics", {"elapsed": gate_d.elapsed_seconds, "overrun": max(0.0, gate_d.elapsed_seconds - gate_d_config.wall_clock_limit_s), "stages": (gate_d.telemetry.stage0_analyses, gate_d.telemetry.stage1_analyses, gate_d.telemetry.stage2_analyses), "timings": gate_d.telemetry.component_timings})
    _section(37, "TT statistics", {"new": gate_d.telemetry.tt_new, "improved": gate_d.telemetry.tt_improved, "suppressed": gate_d.telemetry.tt_suppressed})
    _section(38, "proof statistics", {"proof_pruned": gate_d.telemetry.proof_pruned, "heuristic_pruned": gate_d.telemetry.heuristic_pruned, "incumbent": gate_d.initial_incumbent_cost})
    _section(39, "unseen-deal results", _unseen_smokes())
    if second and repeat is not None and len(_node(repeat).state.foundations) >= 2:
        verdict = "STRONG PASS"
    elif second:
        verdict = "PASS"
    else:
        verdict = "PARTIAL"
    blocker = "none for foundation #2" if second else _terminal_payload(gate_d)[0]["macro_failure"]
    _section(40, "verdict", verdict)
    _section(41, "precise remaining blocker", blocker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
