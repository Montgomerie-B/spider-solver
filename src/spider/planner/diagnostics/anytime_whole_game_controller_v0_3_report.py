#!/usr/bin/env python3
"""Reproducible v0.3 campaign-continuity and deadline report.

Anchor summaries are verified before search but no anchor action, state, suit,
or campaign is passed to the prospective controller.  The optional whole-game
attempt is opt-in because this sprint authorizes only one; the checked-in
frozen observation records the single attempt performed for v0.3.
"""

from __future__ import annotations

import argparse
import inspect
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.move_lifecycle import assess_tableau_move
import spider.planner.anytime_controller as controller
import spider.planner.campaign_corridor as corridor_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    AnytimeSearchResult,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    generate_campaign_corridor_lanes,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "c7672bf370442650f3bdc440febef8351d6134a4"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
V02_BASELINE = {
    "gate_c": {
        "expansions": 12,
        "tactical_nodes": 1_431,
        "probe_nodes": 2_924,
        "best_g": 10,
        "stock": 30,
        "face_down": 40,
        "foundations": 0,
    },
    "gate_d": {
        "expansions": 18,
        "tactical_nodes": 1_820,
        "probe_nodes": 7_151,
        "analysis_misses": 60,
        "post_deal_reuses": 23,
        "foundations": 0,
        "overrun_seconds": 9.05,
    },
    "research_overrun_seconds": 19.42,
}

# Frozen after the gate, repeat, and continuation passed.  Do not replay this
# automatically: the task authorized one production-like attempt only.
FROZEN_WHOLE_GAME_OBSERVATION = {
    "wall_limit_seconds": 120,
    "elapsed_seconds": 120.124,
    "overrun_seconds": 0.124,
    "expansions": 15,
    "tactical_nodes": 34_266,
    "probe_nodes": 0,
    "best_g": 79,
    "best_foundations": 1,
    "best_stock": 0,
    "best_face_down": 24,
    "first_solution": None,
    "maximum_component_call_seconds": 8.967,
    "verdict": "bounded miss; no complete solution",
}


def _print_section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(value)


def _gate_config(*, stop_after_first: bool, wall: float = 120.0) -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=wall,
        max_strategic_expansions=30,
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
        stop_after_first_foundation=stop_after_first,
    )


def _continuation_config(seconds: float) -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=seconds,
        max_strategic_expansions=6,
        max_tactical_nodes=90_000,
        max_frontier_size=128,
        max_successors_per_expansion=8,
        enable_campaign_corridors=True,
        corridor_config=CampaignCorridorConfig(
            max_epoch_transitions=2,
            max_added_cost=24,
            max_nodes=30_000,
            time_limit_s=min(6.0, seconds),
            beam_width=256,
            max_lanes=2,
            max_source_combinations=64,
        ),
    )


def _node_summary(result: AnytimeSearchResult) -> Dict:
    node = result.best_progress_node
    analysis = node.analysis
    assert analysis is not None
    return {
        "g": node.g,
        "actions": len(node.actions),
        "foundations": len(node.state.foundations),
        "foundation_suits": tuple(
            sequence[0].suit for sequence in node.state.foundations if sequence
        ),
        "stock": len(node.state.stock),
        "face_down": sum(len(column.face_down) for column in node.state.columns),
        "must_burden": analysis.progress.total_campaign_must_burden,
        "stable_joins": analysis.measurement.stable_same_suit_joins,
        "mixed_boundaries": analysis.measurement.mixed_suit_boundaries,
        "rehandling_debt": analysis.measurement.rehandling_debt,
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(node.state),
        "actions_exact": node.actions,
    }


def _timings(result: AnytimeSearchResult) -> Dict:
    return {
        name: {
            "calls": item.calls,
            "cumulative_seconds": round(item.cumulative_seconds, 3),
            "maximum_seconds": round(item.maximum_seconds, 3),
            "skipped_due_deadline": item.skipped_due_deadline,
            "incomplete": item.aborted_or_incomplete,
        }
        for name, item in sorted(result.telemetry.component_timings.items())
    }


def _lifecycle_summary(state: SpiderState, actions: Sequence[Action]) -> Dict:
    cursor = state.clone()
    placements = []
    for action in actions:
        if action == ("deal",):
            replay_actions(cursor, [action])
            continue
        item = assess_tableau_move(cursor, action)
        placements.append(
            {
                "action": action,
                "class": item.placement_class.value,
                "immediate_cost": item.immediate_cost,
                "joins_created": item.same_suit_joins_created,
                "joins_broken": item.same_suit_joins_broken,
                "mixed_created": item.mixed_suit_boundaries_created,
                "mixed_removed": item.mixed_suit_boundaries_removed,
                "exit": item.future_exit_route,
                "estimated_rehandling": item.estimated_rehandling_cost,
                "permanent_join_override": (
                    item.compensating_benefit.override_reason
                    if item.compensating_benefit is not None
                    else None
                ),
            }
        )
        replay_actions(cursor, [action])
    return {
        "placements": placements,
        "park_count": sum(item["class"].endswith("PARK") for item in placements),
        "estimated_rehandling": sum(item["estimated_rehandling"] for item in placements),
    }


def _unseen_deal(seed: int):
    cards = [
        Card(suit, rank)
        for suit in "cdhs"
        for rank in range(1, 14)
        for _ in range(2)
    ]
    random.Random(seed).shuffle(cards)
    frozen = tuple(cards)
    return frozen, SpiderState.from_cards(frozen)


def _unseen_results() -> Dict:
    out = {}
    for seed in (1, 2):
        cards, state = _unseen_deal(seed)
        config = AnytimeControllerConfig(
            wall_clock_limit_s=3.0,
            max_strategic_expansions=1,
            max_tactical_nodes=1_000,
            max_frontier_size=32,
            max_successors_per_expansion=4,
            enable_campaign_edges=False,
            enable_campaign_corridors=True,
            enable_expensive_deal_timing=False,
            corridor_config=CampaignCorridorConfig(
                max_epoch_transitions=2,
                max_added_cost=4,
                max_nodes=500,
                time_limit_s=0.5,
                beam_width=32,
                max_lanes=1,
                max_source_combinations=32,
            ),
        )
        portfolio = analyze_foundation_campaigns(
            state, cards=cards, max_source_combinations=32
        )
        lanes = generate_campaign_corridor_lanes(
            state, cards, config=config.corridor_config, portfolio=portfolio
        )
        result = solve_anytime(state, cards, None, config)
        out[seed] = {
            "primary": lanes[0].corridor.identity.label if lanes else None,
            "lanes": tuple(lane.lane_id for lane in lanes),
            "elapsed": round(result.elapsed_seconds, 3),
            "overrun": round(max(0.0, result.elapsed_seconds - 3.0), 3),
            "replay_verified_retained": result.telemetry.retained,
            "preflight": result.preflight.passed,
        }
    return out


def _whole_game_attempt(state: SpiderState, cards: Sequence[Card], seconds: float):
    config = _gate_config(stop_after_first=False, wall=min(240.0, seconds))
    return solve_anytime(state, cards, None, config)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--continuation-seconds", type=float, default=15.0)
    parser.add_argument("--run-whole-game", action="store_true")
    parser.add_argument("--whole-game-seconds", type=float, default=120.0)
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    preflight = controller.freeze_active_rule_profile(opening, cards, rules=MW_RULES)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    cost23 = reconstruct_cost23_checkpoint()

    _print_section(1, "authoritative base", AUTHORITATIVE_BASE)
    _print_section(2, "active rule preflight", {
        "passed": preflight.passed,
        "unrestricted_deal": preflight.profile.can_deal_into_empty,
        "failures": preflight.failures,
    })
    _print_section(3, "canonical anchor summary", {
        "valid": canonical.valid, "solved": canonical.solved,
        "cost": canonical.mobilityware_moves, "explicit": canonical.explicit_commands,
        "tableau": canonical.tableau_moves, "deals": canonical.stock_deals,
        "foundations": canonical.foundations, "path": canonical.path_hash,
        "state": canonical.state_hash,
    })
    _print_section(4, "legal cost-23 anchor summary", {
        "verified": cost23.independently_verified,
        "cost": cost23.arm.total_cost,
        "actions": cost23.action_count,
        "deals": cost23.deal_count,
        "suits": cost23.foundation_suits,
        "stock": len(cost23.state.stock),
        "face_down": cost23.face_down_count,
    })
    _print_section(5, "v0.2 measured baseline", V02_BASELINE)

    gate_config = _gate_config(stop_after_first=True)
    portfolio = analyze_foundation_campaigns(
        opening, cards=cards, max_source_combinations=64
    )
    lanes = generate_campaign_corridor_lanes(
        opening,
        cards,
        config=gate_config.corridor_config,
        portfolio=portfolio,
    )
    _print_section(6, "corridor architecture/config", asdict(gate_config.corridor_config))
    _print_section(7, "true-opening corridor campaigns/lanes", [
        {
            "lane": lane.lane_id,
            "identity": lane.corridor.identity.label,
            "must": lane.corridor.must_source_keys,
            "alternatives": lane.corridor.interchangeable_source_keys,
            "future_stock": tuple(
                (epoch, column + 1, str(card))
                for epoch, column, card in lane.corridor.relevant_future_stock_cards
            ),
        }
        for lane in lanes
    ])
    _print_section(8, "corridor milestones/target epochs", [
        {
            "lane": lane.lane_id,
            "next": lane.corridor.next_milestone.description,
            "final": lane.corridor.final_milestone.description,
            "target_epoch": lane.corridor.plausible_target_removal_epoch,
        }
        for lane in lanes
    ])
    _print_section(9, "staged-analysis architecture", {
        "stage0": "exact cheap facts on every generated child",
        "stage1": "fresh strategic core before expansion",
        "stage2": "optional Deal timing, probes, and deep corridor work only when needed",
    })
    _print_section(10, "deadline/resource configuration", {
        "wall": gate_config.wall_clock_limit_s,
        "expansions": gate_config.max_strategic_expansions,
        "tactical": gate_config.max_tactical_nodes,
        "corridor": asdict(gate_config.corridor_config),
    })

    # No route, checkpoint, suit, or anchor object enters either call.
    gate = solve_anytime(opening, cards, incumbent=None, config=gate_config)
    repeat = solve_anytime(
        SpiderState.from_cards(cards), cards, incumbent=None, config=gate_config
    )
    gate_summary = _node_summary(gate)
    repeat_summary = _node_summary(repeat)
    gate_success = gate_summary["foundations"] >= 1
    repeat_success = repeat_summary["foundations"] >= 1

    _print_section(11, "per-component analysis timing", _timings(gate))
    _print_section(12, "cache/reuse statistics", {
        "hits": gate.telemetry.analysis_cache_hits,
        "misses": gate.telemetry.analysis_cache_misses,
        "post_deal_reuse": gate.telemetry.post_deal_analysis_reused,
        "avoided": gate.telemetry.avoided_full_analyses,
        "stages": (gate.telemetry.stage0_analyses, gate.telemetry.stage1_analyses, gate.telemetry.stage2_analyses),
    })
    _print_section(13, "true-opening prospective foundation gate", {
        "success": gate_success,
        "status": gate.status.value,
        "stop": gate.stop_reason,
        "elapsed": round(gate.elapsed_seconds, 3),
        "expansions": gate.strategic_expansions,
        "tactical": gate.tactical_nodes,
        "probe": gate.telemetry.actionability_probe_nodes,
        "best": {k: v for k, v in gate_summary.items() if k != "actions_exact"},
    })
    _print_section(14, "complete first-foundation machine prefix", gate_summary["actions_exact"] if gate_success else None)

    replay = opening.clone()
    replay_cost = replay_actions(replay, list(gate.best_progress_node.actions))
    _print_section(15, "independent replay/hash verification", {
        "cost": replay_cost,
        "endpoint_equal": states_structurally_equal(replay, gate.best_progress_node.state),
        "path_hash": gate_summary["path_hash"],
        "endpoint_hash": gate_summary["endpoint_hash"],
    })
    _print_section(16, "repeatability run", {
        "success": repeat_success,
        "same_result": (
            gate_summary["g"], gate_summary["foundation_suits"], gate_summary["actions_exact"]
        ) == (
            repeat_summary["g"], repeat_summary["foundation_suits"], repeat_summary["actions_exact"]
        ),
        "summary": repeat_summary,
    })

    # Comparison is deliberately below the prospective freeze and repeat.
    _print_section(17, "post-freeze cost-23 comparison", {
        "machine_cost": gate_summary["g"],
        "anchor_cost": cost23.arm.total_cost,
        "same_suit": gate_summary["foundation_suits"] == cost23.foundation_suits,
        "machine_deal_action_indexes": tuple(
            i + 1 for i, action in enumerate(gate_summary["actions_exact"]) if action == ("deal",)
        ),
        "anchor_deal_action_indexes": (11, 19),
        "machine_face_down": gate_summary["face_down"],
        "anchor_face_down": cost23.face_down_count,
        "lifecycle": _lifecycle_summary(opening, gate_summary["actions_exact"]),
    })

    continuation = None
    if gate_success and repeat_success:
        continuation = solve_anytime(
            gate.best_progress_node.state,
            cards,
            incumbent=None,
            config=_continuation_config(args.continuation_seconds),
        )
    continuation_summary = _node_summary(continuation) if continuation else None
    _print_section(18, "optional continuation result", {
        "summary": continuation_summary,
        "elapsed": round(continuation.elapsed_seconds, 3) if continuation else None,
        "overrun": round(max(0.0, continuation.elapsed_seconds - args.continuation_seconds), 3) if continuation else None,
        "corridors": continuation.telemetry.corridor_results if continuation else (),
    })

    if args.run_whole_game:
        whole = _whole_game_attempt(
            SpiderState.from_cards(cards), cards, args.whole_game_seconds
        )
        whole_summary = {
            "fresh_run": True,
            "result": _node_summary(whole),
            "elapsed": whole.elapsed_seconds,
            "first_solution": whole.first_solution.corrected_cost if whole.first_solution else None,
        }
    else:
        whole_summary = {
            "fresh_run": False,
            "frozen_single_authorized_attempt": FROZEN_WHOLE_GAME_OBSERVATION,
        }
    _print_section(19, "optional whole-game result", whole_summary)
    _print_section(20, "corridor successes/failures", {
        "results": gate.telemetry.corridor_results,
        "successes": gate.telemetry.corridors_reaching_foundation,
        "failures": gate.telemetry.corridor_failures,
    })
    _print_section(21, "Deal timing inside corridors", {
        "successful_corridor_deals": gate.telemetry.corridor_results,
        "note": "exact Deals are corridor steps; shallow Deal timing cannot kill the lane",
    })
    _print_section(22, "stock timeline", gate.telemetry.deal_timeline)
    _print_section(23, "foundation timeline", gate.telemetry.foundation_timeline)
    _print_section(24, "strategic progress timeline", gate.telemetry.decision_trace)
    _print_section(25, "analysis calls per expansion", {
        "stage1_per_expansion": round(gate.telemetry.stage1_analyses / max(1, gate.strategic_expansions), 3),
        "stage2_per_expansion": round(gate.telemetry.stage2_analyses / max(1, gate.strategic_expansions), 3),
    })
    _print_section(26, "maximum single analysis-call duration", max(
        (item.maximum_seconds for item in gate.telemetry.component_timings.values()),
        default=0.0,
    ))
    _print_section(27, "wall-clock overrun", {
        "gate": max(0.0, gate.elapsed_seconds - gate_config.wall_clock_limit_s),
        "repeat": max(0.0, repeat.elapsed_seconds - gate_config.wall_clock_limit_s),
        "continuation": (
            max(0.0, continuation.elapsed_seconds - args.continuation_seconds)
            if continuation else None
        ),
    })
    _print_section(28, "TT statistics", {
        "new": gate.telemetry.tt_new,
        "improved": gate.telemetry.tt_improved,
        "suppressed": gate.telemetry.tt_suppressed,
        "corridors_suppressed": gate.telemetry.corridors_suppressed_by_tt,
    })
    _print_section(29, "proof-bound statistics", {
        "proof_pruned": gate.telemetry.proof_pruned,
        "heuristic_pruned": gate.telemetry.heuristic_pruned,
        "proof_source": "existing admissible incumbent budget only",
        "incumbent": None,
    })
    unseen = _unseen_results()
    _print_section(30, "unseen-deal results", unseen)

    deadline_ok = all(
        overrun <= 2.0
        for overrun in (
            max(0.0, gate.elapsed_seconds - gate_config.wall_clock_limit_s),
            max(0.0, repeat.elapsed_seconds - gate_config.wall_clock_limit_s),
            max(0.0, continuation.elapsed_seconds - args.continuation_seconds) if continuation else 0.0,
        )
    )
    continuation_progress = bool(
        continuation_summary
        and (
            continuation_summary["foundations"] > gate_summary["foundations"]
            or continuation_summary["face_down"] < gate_summary["face_down"]
            or continuation_summary["must_burden"] < gate_summary["must_burden"]
        )
    )
    verdict = (
        "STRONG PASS"
        if gate_success and repeat_success and deadline_ok and continuation_progress
        else ("PASS" if gate_success and deadline_ok else "PARTIAL")
    )
    _print_section(31, "prospective verdict", verdict)
    _print_section(32, "precise remaining blocker", (
        "Current-epoch residual corridors improve reveals and MUST burden but do not yet "
        "convert that progress into a second foundation before other lanes consume stock; "
        "the single production attempt ended with one foundation and no solution."
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
