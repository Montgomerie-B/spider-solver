#!/usr/bin/env python3
"""Reproducible v0.4 residual-conversion and checkpoint-diversity report.

The cost-21 and cost-23 states are capability anchors for Gates A and B only.
Gate C always constructs the untouched deal and receives no action, checkpoint,
suit, campaign, or canonical-route seed.
"""

from __future__ import annotations

import argparse
import inspect
import pprint
import random
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import Action, replay_actions
import spider.planner.anytime_controller as controller
import spider.planner.residual_campaign as residual_module
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    AnytimeSearchResult,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.campaign_corridor import CampaignCorridorConfig
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.economic_project_realizer import measure_structural_state
from spider.planner.economic_projects import analyze_economic_projects
from spider.planner.residual_campaign import (
    analyze_residual_campaign,
    residual_investment_accounting,
)
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import states_structurally_equal


AUTHORITATIVE_BASE = "cef33e88b39008fba6d9e6aa9ed26f7861b45730"
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


def _residual_gate_config(seconds: float) -> AnytimeControllerConfig:
    """One frozen generic configuration shared unchanged by Gates A and B."""
    return AnytimeControllerConfig(
        wall_clock_limit_s=min(90.0, seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
        max_successors_per_expansion=10,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        enable_campaign_corridors=True,
        enable_residual_conversion=True,
        max_foundation_checkpoints=6,
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


def _gate_c_config(seconds: float) -> AnytimeControllerConfig:
    """True-opening Gate C config; there is intentionally no seed argument."""
    return AnytimeControllerConfig(
        wall_clock_limit_s=min(180.0, seconds),
        max_strategic_expansions=50,
        max_tactical_nodes=500_000,
        max_frontier_size=256,
        max_successors_per_expansion=10,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        enable_campaign_corridors=True,
        enable_residual_conversion=True,
        max_foundation_checkpoints=6,
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


def _node_with_most_foundations(result: AnytimeSearchResult):
    return result.most_foundations_node


def _summary(result: AnytimeSearchResult, *, offset_g: int = 0) -> Dict:
    node = _node_with_most_foundations(result)
    analysis = node.analysis
    assert analysis is not None
    replay = result.best_node.state.clone()  # overwritten below; avoids aliasing endpoint
    del replay
    return {
        "status": result.status.value,
        "stop": result.stop_reason,
        "elapsed": round(result.elapsed_seconds, 3),
        "expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "probe_nodes": result.telemetry.actionability_probe_nodes,
        "added_g": node.g,
        "total_g": offset_g + node.g,
        "actions": len(node.actions),
        "actions_exact": node.actions,
        "foundations": len(node.state.foundations),
        "foundation_suits": tuple(seq[0].suit for seq in node.state.foundations if seq),
        "stock": len(node.state.stock),
        "face_down": analysis.measurement.face_down_count,
        "must_burden": analysis.progress.total_campaign_must_burden,
        "stable_joins": analysis.measurement.stable_same_suit_joins,
        "same_suit_mass": analysis.measurement.same_suit_run_mass,
        "mixed_boundaries": analysis.measurement.mixed_suit_boundaries,
        "rehandling_debt": analysis.measurement.rehandling_debt,
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(node.state),
        "zobrist": format(zobrist(node.state), "x"),
        "independent_replay_required": True,
    }


def _verify_from(start: SpiderState, result: AnytimeSearchResult) -> Dict:
    node = _node_with_most_foundations(result)
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost = None
        valid = False
    return {
        "valid": valid,
        "cost": cost,
        "endpoint_equal": valid,
        "path_hash": controller._action_path_hash(node.actions),
        "endpoint_hash": controller._state_hash(node.state),
        "zobrist": format(zobrist(node.state), "x"),
    }


def _checkpoint_payload(result: AnytimeSearchResult) -> Tuple[Dict, ...]:
    out = []
    for profile in result.foundation_checkpoint_portfolio.profiles:
        best = profile.best_readiness
        out.append(
            {
                "foundations": profile.foundations,
                "suits": profile.foundation_suits,
                "g": profile.g,
                "stock": profile.stock_remaining,
                "face_down": profile.face_down_count,
                "must": profile.total_campaign_must_burden,
                "readiness": asdict(best) if best is not None else None,
                "debt": profile.rehandling_debt,
                "stable_joins": profile.stable_same_suit_joins,
                "workspace": (profile.empty_columns, profile.fully_open_columns),
                "residual_corridors": profile.residual_corridor_candidates,
            }
        )
    return tuple(out)


def _timings(result: AnytimeSearchResult) -> Dict:
    return {
        name: {
            "calls": value.calls,
            "seconds": round(value.cumulative_seconds, 3),
            "maximum": round(value.maximum_seconds, 3),
            "skipped": value.skipped_due_deadline,
            "incomplete": value.aborted_or_incomplete,
        }
        for name, value in sorted(result.telemetry.component_timings.items())
    }


def _unseen_results() -> Dict:
    out = {}
    for seed in (31, 47):
        cards = [
            Card(suit, rank)
            for suit in "cdhs"
            for rank in range(1, 14)
            for _ in range(2)
        ]
        random.Random(seed).shuffle(cards)
        frozen = tuple(cards)
        state = SpiderState.from_cards(frozen)
        economic = analyze_economic_projects(
            state, cards=frozen, campaign_source_combination_limit=32
        )
        measurement = measure_structural_state(state, cards=frozen, analysis=economic)
        assessment = analyze_residual_campaign(
            state,
            frozen,
            g=0,
            analysis=economic,
            measurement=measurement,
            corridor_config=CampaignCorridorConfig(max_source_combinations=32),
            maximum_lanes=3,
        )
        smoke = solve_anytime(
            state,
            frozen,
            None,
            AnytimeControllerConfig(
                wall_clock_limit_s=2.0,
                max_strategic_expansions=1,
                max_tactical_nodes=500,
                max_frontier_size=32,
                max_successors_per_expansion=4,
                enable_campaign_edges=False,
                enable_campaign_corridors=False,
                enable_expensive_deal_timing=False,
            ),
        )
        out[seed] = {
            "preflight": smoke.preflight.passed,
            "elapsed": round(smoke.elapsed_seconds, 3),
            "overrun": round(max(0.0, smoke.elapsed_seconds - 2.0), 3),
            "retained": smoke.telemetry.retained,
            "residual_status": assessment.status.value,
            "lanes": tuple(lane.lane_id for lane in assessment.lanes),
        }
    return out


def _foundation_investment(result: AnytimeSearchResult) -> Optional[Dict]:
    profiles = sorted(
        result.foundation_checkpoint_portfolio.profiles,
        key=lambda item: (item.foundations, item.g),
    )
    for before in profiles:
        after = next(
            (item for item in profiles if item.foundations == before.foundations + 1),
            None,
        )
        if after is not None:
            return asdict(residual_investment_accounting(before, after))
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-a-seconds", type=float, default=90.0)
    parser.add_argument("--gate-b-seconds", type=float, default=90.0)
    parser.add_argument("--gate-c-seconds", type=float, default=180.0)
    parser.add_argument("--third-seconds", type=float, default=90.0)
    parser.add_argument("--whole-seconds", type=float, default=240.0)
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    machine_anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    machine_node = _node_with_most_foundations(machine_anchor)
    machine_replay = _verify_from(opening, machine_anchor)
    if not (
        machine_node.g == 21
        and len(machine_node.actions) == 21
        and len(machine_node.state.foundations) == 1
        and len(machine_node.state.stock) == 30
        and sum(len(column.face_down) for column in machine_node.state.columns) == 33
        and controller._action_path_hash(machine_node.actions) == "924bfd20deac96af"
        and format(zobrist(machine_node.state), "x") == "b7522950ea41ad9a"
        and machine_replay["valid"]
    ):
        raise AssertionError("cost-21 machine anchor regressed")
    independent = reconstruct_cost23_checkpoint()

    _section(1, "authoritative base", AUTHORITATIVE_BASE)
    _section(2, "active rule profile", asdict(machine_anchor.preflight.profile))
    _section(3, "canonical 172 anchor", {
        "valid": canonical.valid, "solved": canonical.solved,
        "cost": canonical.mobilityware_moves, "explicit": canonical.explicit_commands,
        "tableau": canonical.tableau_moves, "deals": canonical.stock_deals,
        "foundations": canonical.foundations, "path_hash": canonical.path_hash,
        "final_state_hash": canonical.state_hash,
    })
    _section(4, "cost-21 machine anchor", {**_summary(machine_anchor), "replay": machine_replay})
    _section(5, "cost-23 independent anchor", {
        "verified": independent.independently_verified,
        "cost": independent.arm.total_cost,
        "actions": independent.action_count,
        "deals": independent.deal_count,
        "stock": len(independent.state.stock),
        "face_down": independent.face_down_count,
        "foundations": independent.foundation_suits,
    })
    _section(6, "v0.3 blocker summary", {
        "continuation": "face-down 33->27; MUST 26->21; stock 30; no second foundation",
        "whole_game": "g=79; one foundation; face-down 24; stock empty; no solution",
    })
    _section(7, "residual-conversion architecture", tuple(
        item for item in residual_module.__all__
    ) if hasattr(residual_module, "__all__") else (
        "ResidualCampaignAssessment", "ResidualCampaignLane",
        "NextFoundationReadiness", "ResidualInvestmentAccounting",
    ))
    _section(8, "foundation checkpoint profile/diversity semantics", {
        "profile_fields": tuple(residual_module.FoundationCheckpointProfile.__dataclass_fields__),
        "portfolio_fields": tuple(residual_module.FoundationCheckpointPortfolio.__dataclass_fields__),
        "proof_authority": False,
    })
    _section(9, "stock opportunity-cost semantics", tuple(residual_module.StockOpportunityAssessment.__dataclass_fields__))
    _section(10, "Deal escape-vs-unlock classification", tuple(item.value for item in residual_module.DealPurpose))
    proof_lines = [line.strip() for line in inspect.getsource(controller.solve_anytime).splitlines() if "proof_prunable" in line]
    _section(11, "proof-safety audit", {"proof_lines": proof_lines, "residual_proof_authority": False, "incumbent": None})

    frozen_residual_config = _residual_gate_config(args.gate_a_seconds)
    gate_a = solve_anytime(machine_node.state, cards, None, frozen_residual_config)
    gate_a_summary = _summary(gate_a, offset_g=21)
    gate_a_replay = _verify_from(machine_node.state, gate_a)
    _section(12, "Gate A config/result", {"config": asdict(frozen_residual_config), "result": gate_a_summary, "replay": gate_a_replay})

    # Gate B receives the same strategy and resource values; only its wall cap
    # may be lower if the caller explicitly requests a shorter diagnostic.
    gate_b_config = _residual_gate_config(args.gate_b_seconds)
    gate_b = solve_anytime(independent.state, cards, None, gate_b_config)
    gate_b_summary = _summary(gate_b, offset_g=23)
    gate_b_replay = _verify_from(independent.state, gate_b)
    _section(13, "Gate B config/result", {"config": asdict(gate_b_config), "result": gate_b_summary, "replay": gate_b_replay})
    frozen_comparison = {
        "A_total_cost": gate_a_summary["total_g"],
        "B_total_cost": gate_b_summary["total_g"],
        "A_foundations": gate_a_summary["foundations"],
        "B_foundations": gate_b_summary["foundations"],
        "A_stock": gate_a_summary["stock"],
        "B_stock": gate_b_summary["stock"],
        "A_face_down": gate_a_summary["face_down"],
        "B_face_down": gate_b_summary["face_down"],
        "A_must": gate_a_summary["must_burden"],
        "B_must": gate_b_summary["must_burden"],
        "strategy_changed_between_gates": False,
    }
    _section(14, "frozen A/B comparison", frozen_comparison)

    gate_c_config = _gate_c_config(args.gate_c_seconds)
    _section(15, "Gate C true-opening config", {"config": asdict(gate_c_config), "incumbent": None, "seeded_prefix": None})
    gate_c = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_c_config)
    gate_c_summary = _summary(gate_c)
    gate_c_node = _node_with_most_foundations(gate_c)
    gate_c_replay = _verify_from(opening, gate_c)
    checkpoints = _checkpoint_payload(gate_c)
    _section(16, "first foundation(s) discovered during Gate C", tuple(item for item in gate_c.telemetry.foundation_timeline if item[1] == 1))
    _section(17, "retained first-foundation checkpoint portfolio", tuple(item for item in checkpoints if item["foundations"] == 1))
    second_found = len(gate_c_node.state.foundations) >= 2
    _section(18, "exact route to second foundation if found", gate_c_node.actions if second_found else None)
    _section(19, "second-foundation suit", gate_c_summary["foundation_suits"][1] if second_found else None)
    _section(20, "corrected g at second foundation", gate_c_node.g if second_found else None)
    investment = _foundation_investment(gate_c)
    _section(21, "stock rows consumed between foundations", investment["stock_rows_consumed"] if investment else None)
    _section(22, "residual economics between foundations", investment)
    _section(23, "independent replay/hash verification", gate_c_replay)

    repeat = None
    repeat_summary = None
    if second_found:
        repeat = solve_anytime(SpiderState.from_cards(cards), cards, None, gate_c_config)
        repeat_summary = _summary(repeat)
    repeat_ok = bool(
        repeat is not None
        and repeat_summary is not None
        and repeat_summary["foundations"] >= 2
        and _verify_from(opening, repeat)["valid"]
    )
    _section(24, "repeatability result", {"run": repeat_summary, "passed": repeat_ok})

    third = None
    if second_found and repeat_ok:
        third_config = _residual_gate_config(min(90.0, args.third_seconds))
        third_config = controller.replace(third_config, target_foundation_count=3)
        third = solve_anytime(gate_c_node.state, cards, None, third_config)
    _section(25, "optional third-foundation continuation", _summary(third, offset_g=gate_c_node.g) if third else None)

    whole = None
    if second_found and repeat_ok and gate_c.elapsed_seconds <= gate_c_config.wall_clock_limit_s + 2.0:
        whole_config = controller.replace(
            _gate_c_config(min(240.0, args.whole_seconds)),
            target_foundation_count=None,
            max_strategic_expansions=80,
            max_tactical_nodes=750_000,
        )
        whole = solve_anytime(SpiderState.from_cards(cards), cards, None, whole_config)
    _section(26, "optional whole-game result", _summary(whole) if whole else None)
    _section(27, "foundation timeline", {
        "structural": gate_c.telemetry.foundation_timeline,
        "resources": gate_c.telemetry.foundation_resource_timeline,
    })
    _section(28, "stock timeline", gate_c.telemetry.deal_timeline)
    _section(29, "Deal unlock/escape statistics", {
        "strategic_unlock": gate_c.telemetry.deal_strategic_unlock_count,
        "escape_only": gate_c.telemetry.deal_escape_only_count,
        "current_opportunities_lost": gate_c.telemetry.current_epoch_opportunities_lost_to_deal,
    })
    _section(30, "residual corridor statistics", {
        "generated": gate_c.telemetry.residual_lanes_generated,
        "realised": gate_c.telemetry.residual_lanes_realized,
        "failures": gate_c.telemetry.residual_conversion_failures,
        "results": gate_c.telemetry.corridor_results,
    })
    _section(31, "analysis/deadline statistics", {
        "elapsed": gate_c.elapsed_seconds,
        "overrun": max(0.0, gate_c.elapsed_seconds - gate_c_config.wall_clock_limit_s),
        "stages": (gate_c.telemetry.stage0_analyses, gate_c.telemetry.stage1_analyses, gate_c.telemetry.stage2_analyses),
        "cache": (gate_c.telemetry.analysis_cache_hits, gate_c.telemetry.analysis_cache_misses, gate_c.telemetry.avoided_full_analyses),
        "timings": _timings(gate_c),
    })
    _section(32, "TT statistics", {
        "new": gate_c.telemetry.tt_new,
        "improved": gate_c.telemetry.tt_improved,
        "suppressed": gate_c.telemetry.tt_suppressed,
        "corridors_suppressed": gate_c.telemetry.corridors_suppressed_by_tt,
        "checkpoint_generated": gate_c.telemetry.foundation_checkpoints_generated,
        "checkpoint_retained": gate_c.telemetry.distinct_foundation_checkpoints_retained,
        "diversity_suppressions": gate_c.telemetry.checkpoint_diversity_suppressions,
    })
    _section(33, "proof-bound statistics", {
        "proof_pruned": gate_c.telemetry.proof_pruned,
        "heuristic_pruned": gate_c.telemetry.heuristic_pruned,
        "incumbent": gate_c.initial_incumbent_cost,
    })
    unseen = _unseen_results()
    _section(34, "unseen-deal results", unseen)

    complete = bool(whole and whole.incumbent and whole.incumbent.corrected_cost <= 171)
    deadline_ok = gate_c.elapsed_seconds <= gate_c_config.wall_clock_limit_s + 2.0
    ab_both = gate_a_summary["foundations"] >= 2 and gate_b_summary["foundations"] >= 2
    if complete:
        verdict = "EXCEPTIONAL"
    elif second_found and repeat_ok and deadline_ok:
        verdict = "STRONG PASS"
    elif second_found or (ab_both and gate_c_summary["foundations"] >= 1):
        verdict = "PASS"
    elif (
        gate_c_summary["face_down"] < 33
        or gate_c_summary["must_burden"] < 26
        or gate_a_summary["face_down"] < 33
        or gate_b_summary["face_down"] < 32
    ):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    blocker = (
        "none; complete <=171 solution verified"
        if complete
        else "none for the two-foundation gate"
        if second_found
        else (
            "bounded residual lanes improve structure but do not expose and assemble "
            "the remaining campaign sources into foundation #2 before stock escape branches advance"
        )
    )
    _section(35, "prospective verdict", verdict)
    _section(36, "precise remaining blocker", blocker)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
