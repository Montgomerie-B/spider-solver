#!/usr/bin/env python3
"""Reproducible v0.2 capability-gate report.

The cost-11 and cost-23 constructors are diagnostic-only setup.  Each
prospective controller receives an exact state and the deal only: no setup
actions, canonical suffix, target suit, or future route is passed to search.
Canonical comparison is isolated until all prospective outcomes are frozen.
"""

from __future__ import annotations

import argparse
import inspect
import json
import random
import subprocess
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    AnytimeSearchResult,
    StrategicCreditLevel,
    solve_anytime,
)
from spider.planner.deal_timing import DealTimingConfig
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.diagnostics.foundation_campaign_deal2_report import (
    DEAL_PATH,
    _build_verified_deal1,
)
from spider.solution_archive import validate_solution


AUTHORITATIVE_BASE = "93c408e43972798f494073624c5dbe597db3a25e"
V01_BASELINE = {
    "production_like_expansions": 55,
    "production_like_tactical_nodes": 80_000,
    "bounded_inaccessible_probes": 616,
    "foundations": 0,
    "reported_best": {
        "g": 6,
        "stock": 0,
        "foundations": 0,
        "face_down": 43,
    },
}


@dataclass(frozen=True)
class GateSummary:
    name: str
    config: Dict[str, Any]
    status: str
    stop_reason: str
    elapsed_seconds: float
    expansions: int
    tactical_nodes: int
    probe_nodes: int
    probe_seconds: float
    probes_attempted: int
    probe_budget_exhausted: int
    probe_cache_hits: int
    probe_cache_misses: int
    tier_escalations: int
    retry_suppressions: int
    direct_actionability: int
    realizations_attempted: int
    realizations_succeeded: int
    foundation_macro_attempts: int
    foundation_macro_successes: int
    best: Dict[str, Any]
    lowest_g: Dict[str, Any]
    deepest_stock: Dict[str, Any]
    most_foundations: Dict[str, Any]
    foundation_timeline: Tuple
    stock_timeline: Tuple
    deal_delta_timeline: Tuple
    analyses: Dict[str, int]
    tt: Dict[str, int]
    proof: Dict[str, int]
    throughput: Dict[str, float]
    first_solution: Optional[int]
    incumbent_cost: Optional[int]


def _isolated_json(code: str) -> Dict[str, Any]:
    env = dict(__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads([line for line in completed.stdout.splitlines() if line][-1])


def regression_anchors() -> Dict[str, Any]:
    canonical_path = ROOT / "solutions" / "4925153_canonical.moves"
    canonical = _isolated_json(
        "import json; from pathlib import Path; "
        "from spider.solution_archive import validate_solution; "
        f"v=validate_solution('4925153',Path(r'{canonical_path}')); "
        "print(json.dumps({'valid':v.valid,'solved':v.solved,'cost':v.mobilityware_moves,"
        "'explicit':v.explicit_commands,'tableau':v.tableau_moves,'deals':v.stock_deals,"
        "'foundations':v.foundations,'stock':v.stock_remaining,'path':v.path_hash,"
        "'state':v.state_hash}))"
    )
    cost23 = _isolated_json(
        "import json; from spider.planner.diagnostics.economic_project_analysis_report "
        "import reconstruct_cost23_checkpoint; c=reconstruct_cost23_checkpoint(); "
        "print(json.dumps({'valid':c.independently_verified,'cost':c.arm.total_cost,"
        "'actions':c.action_count,'deals':c.deal_count,'foundations':len(c.state.foundations),"
        "'suits':c.foundation_suits,'stock':len(c.state.stock),'face_down':c.face_down_count}))"
    )
    expected_canonical = {
        "valid": True,
        "solved": True,
        "cost": 172,
        "explicit": 174,
        "tableau": 169,
        "deals": 5,
        "foundations": 8,
        "stock": 0,
        "path": "77d169da2538ba8c",
        "state": "4e9861540eac570cb",
    }
    expected_cost23 = {
        "valid": True,
        "cost": 23,
        "actions": 23,
        "deals": 2,
        "foundations": 1,
        "suits": ["s"],
        "stock": 30,
        "face_down": 32,
    }
    if canonical != expected_canonical or cost23 != expected_cost23:
        raise AssertionError(f"anchor drift: canonical={canonical}; cost23={cost23}")
    return {"canonical": canonical, "cost23": cost23, "passed": True}


def timing_config() -> DealTimingConfig:
    return DealTimingConfig(
        max_preparation_projects=1,
        max_preparation_cost=4,
        hard_preparation_cost_cap=8,
        max_h1_candidates=1,
        max_h2_candidates=0,
        tactical_max_cost=2,
        tactical_max_nodes=400,
        tactical_time_limit_s=0.15,
        downstream_max_cost=3,
        downstream_max_nodes=400,
        downstream_time_limit_s=0.15,
    )


def gate_config(
    seconds: float,
    expansions: int,
    tactical_nodes: int,
    *,
    campaign_cost: int,
) -> AnytimeControllerConfig:
    return AnytimeControllerConfig(
        wall_clock_limit_s=seconds,
        max_strategic_expansions=expansions,
        max_tactical_nodes=tactical_nodes,
        max_frontier_size=800,
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        max_successors_per_expansion=6,
        max_trace_entries=160,
        max_timeline_entries=160,
        campaign_source_combination_limit=4,
        max_direct_projects_per_tier=1,
        max_bounded_projects_per_expansion=1,
        max_actionability_probes_per_expansion=4,
        max_actionability_nodes_per_expansion=3_000,
        max_actionability_time_s_per_expansion=1.0,
        max_total_actionability_nodes=100_000,
        tactical_nodes_per_project=600,
        tactical_time_limit_s_per_project=0.2,
        campaign_branches_clean=0,
        campaign_branches_positive=1,
        campaign_branches_speculative=1,
        campaign_max_added_cost=campaign_cost,
        campaign_max_nodes=3_000 if campaign_cost > 12 else 2_000,
        campaign_time_limit_s=5.0,
        campaign_beam_width=64,
        deal_preparation_arms=1,
        deal_pair_arms=0,
        deal_timing_config=timing_config(),
    )


def _node_summary(node) -> Dict[str, Any]:
    measurement = node.analysis.measurement
    return {
        "g": node.g,
        "state_hash": node.analysis.state_hash,
        "foundations": measurement.foundation_count,
        "face_down": measurement.face_down_count,
        "stock": measurement.stock_count,
        "campaign_must": measurement.campaign_must_burden,
        "critical_dependencies": measurement.critical_dependencies_pending,
        "same_suit_mass": measurement.same_suit_run_mass,
        "stable_joins": measurement.stable_same_suit_joins,
        "mixed_boundaries": measurement.mixed_suit_boundaries,
        "rehandling_debt": measurement.rehandling_debt,
        "priority_components": node.analysis.progress.ordering_key(),
    }


def summarize(name: str, result: AnytimeSearchResult, config: AnytimeControllerConfig) -> GateSummary:
    telemetry = result.telemetry
    expansions = max(1, result.strategic_expansions)
    attempts = telemetry.project_realizations_attempted
    foundation_gain = max(
        0,
        result.best_progress_node.analysis.measurement.foundation_count
        - result.lowest_g_node.analysis.measurement.foundation_count,
    )
    return GateSummary(
        name=name,
        config={
            "seconds": config.wall_clock_limit_s,
            "expansions": config.max_strategic_expansions,
            "tactical_nodes": config.max_tactical_nodes,
            "probe_per_expansion": config.max_actionability_probes_per_expansion,
            "probe_nodes_per_expansion": config.max_actionability_nodes_per_expansion,
        },
        status=result.status.value,
        stop_reason=result.stop_reason,
        elapsed_seconds=result.elapsed_seconds,
        expansions=result.strategic_expansions,
        tactical_nodes=result.tactical_nodes,
        probe_nodes=telemetry.actionability_probe_nodes,
        probe_seconds=telemetry.actionability_probe_seconds,
        probes_attempted=telemetry.actionability_probes_attempted,
        probe_budget_exhausted=telemetry.actionability_probe_budget_exhausted,
        probe_cache_hits=telemetry.actionability_cache_hits,
        probe_cache_misses=telemetry.actionability_cache_misses,
        tier_escalations=telemetry.actionability_tier_escalations,
        retry_suppressions=telemetry.actionability_retry_suppressions,
        direct_actionability=telemetry.direct_actionability_detections,
        realizations_attempted=attempts,
        realizations_succeeded=telemetry.project_realizations_succeeded,
        foundation_macro_attempts=telemetry.foundation_macro_attempts,
        foundation_macro_successes=telemetry.foundation_macro_successes,
        best=_node_summary(result.best_progress_node),
        lowest_g=_node_summary(result.lowest_g_node),
        deepest_stock=_node_summary(result.deepest_stock_node),
        most_foundations=_node_summary(result.most_foundations_node),
        foundation_timeline=tuple(telemetry.foundation_timeline),
        stock_timeline=tuple(telemetry.deal_timeline),
        deal_delta_timeline=tuple(telemetry.deal_delta_timeline),
        analyses={
            "cache_hits": telemetry.analysis_cache_hits,
            "cache_misses": telemetry.analysis_cache_misses,
            "avoided": telemetry.avoided_full_analyses,
            "post_deal_reused": telemetry.post_deal_analysis_reused,
        },
        tt={
            "new": telemetry.tt_new,
            "improved": telemetry.tt_improved,
            "suppressed": telemetry.tt_suppressed,
        },
        proof={
            "admissible_pruned": telemetry.proof_pruned,
            "heuristic_pruned": telemetry.heuristic_pruned,
            "frontier_trimmed": telemetry.frontier_trimmed,
        },
        throughput={
            "tactical_nodes_per_expansion": result.tactical_nodes / expansions,
            "probe_nodes_per_expansion": telemetry.actionability_probe_nodes / expansions,
            "realizations_per_expansion": attempts / expansions,
            "realization_success_rate": (
                telemetry.project_realizations_succeeded / attempts if attempts else 0.0
            ),
            "foundations_per_10k_tactical_nodes": (
                foundation_gain * 10_000 / max(1, result.tactical_nodes)
            ),
            "useful_structural_successors_per_expansion": telemetry.retained / expansions,
            "analyses_per_expansion": telemetry.analysis_cache_misses / expansions,
        },
        first_solution=(
            result.first_solution.corrected_cost if result.first_solution is not None else None
        ),
        incumbent_cost=result.incumbent_cost,
    )


def _standard_cards() -> list[Card]:
    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


def unseen_smoke(seed: int) -> Dict[str, Any]:
    cards = _standard_cards()
    random.Random(seed).shuffle(cards)
    config = replace(
        gate_config(5, 1, 2_000, campaign_cost=12),
        enable_campaign_edges=False,
        enable_removal_edges=False,
        max_successors_per_expansion=2,
    )
    result = solve_anytime(SpiderState.from_cards(cards), cards, None, config)
    return {
        "seed": seed,
        "preflight": result.preflight.passed,
        "unrestricted": result.preflight.profile.can_deal_into_empty,
        "legal_progression": result.telemetry.retained > 0,
        "status": result.status.value,
        "expansions": result.strategic_expansions,
        "best": _node_summary(result.best_progress_node),
    }


def proof_audit() -> Dict[str, Any]:
    source = inspect.getsource(controller.solve_anytime)
    proof_lines = [line.strip() for line in source.splitlines() if "proof_prunable" in line]
    generic_source = inspect.getsource(controller)
    return {
        "proof_checks": proof_lines,
        "only_budget_proof_checks": proof_lines
        == [
            "if node.analysis.budget.proof_prunable:",
            "if child.analysis.budget.proof_prunable:",
        ],
        "benchmark_id_absent": "492515" not in generic_source,
        "external_119_absent": "119" not in generic_source,
        "canonical_route_absent": ".moves" not in generic_source,
    }


def verdict_for(a: GateSummary, b: GateSummary, c: GateSummary) -> Tuple[str, str]:
    a_foundation = bool(a.foundation_timeline or a.best["foundations"] >= 1)
    b_material = bool(
        b.best["foundations"] > 1
        or (
            b.best["stock"] == 30
            and (
                sum(value for _label, value in b.best["campaign_must"]) < 25
                or b.best["face_down"] < 32
            )
        )
    )
    probe_fixed = c.probe_nodes < V01_BASELINE["production_like_tactical_nodes"]
    stock_not_best = not (
        c.best["stock"] == 0
        and c.best["foundations"] == 0
        and c.best["face_down"] >= 43
    )
    c_progress = c.best["face_down"] < 44 or c.best["foundations"] > 0
    if a_foundation and b_material and c_progress and probe_fixed and stock_not_best:
        if c.best["foundations"] > 0:
            return "STRONG PASS", "all strong gates including a true-opening foundation passed"
        return (
            "PASS",
            "probe pathology and stock bias are fixed; checkpoint gates pass, but the true opening has no foundation",
        )
    if probe_fixed and stock_not_best:
        return "PARTIAL", "resource mechanics improved but one or more structural gates did not pass"
    return "FAIL", "probe or stock-priority pathology remains"


def print_section(number: int, title: str, value: Any) -> None:
    print(f"\n{number}. {title}")
    print(json.dumps(value, indent=2, default=str))


def run(*, quick: bool = False) -> int:
    anchors = regression_anchors()
    cards = tuple(load_deal(DEAL_PATH))

    _opening, _six, deal1 = _build_verified_deal1(cards)
    gate_a_config = gate_config(60, 5, 20_000, campaign_cost=12)
    gate_a = summarize(
        "A-cost11",
        solve_anytime(deal1.resulting_state.clone(), cards, None, gate_a_config),
        gate_a_config,
    )

    checkpoint = reconstruct_cost23_checkpoint()
    gate_b_config = gate_config(60, 10, 25_000, campaign_cost=18)
    gate_b = summarize(
        "B-cost23",
        solve_anytime(checkpoint.state.clone(), checkpoint.cards, None, gate_b_config),
        gate_b_config,
    )

    gate_c_config = gate_config(20 if quick else 80, 3 if quick else 14, 30_000, campaign_cost=12)
    gate_c = summarize(
        "C-opening",
        solve_anytime(SpiderState.from_cards(list(cards)), cards, None, gate_c_config),
        gate_c_config,
    )
    verdict, reason = verdict_for(gate_a, gate_b, gate_c)

    gate_d_production = None
    gate_d_research = None
    if not quick and verdict in ("PASS", "STRONG PASS"):
        production_config = gate_config(180, 40, 60_000, campaign_cost=12)
        research_config = gate_config(120, 30, 60_000, campaign_cost=12)
        gate_d_production = summarize(
            "D-production",
            solve_anytime(SpiderState.from_cards(list(cards)), cards, None, production_config),
            production_config,
        )
        gate_d_research = summarize(
            "D-research",
            solve_anytime(SpiderState.from_cards(list(cards)), cards, 172, research_config),
            research_config,
        )

    unseen = (unseen_smoke(104729), unseen_smoke(130363))
    prospective_frozen = True
    canonical = validate_solution(
        "4925153", ROOT / "solutions" / "4925153_canonical.moves"
    )

    print_section(1, "authoritative base", AUTHORITATIVE_BASE)
    print_section(2, "active unrestricted preflight and anchors", anchors)
    print_section(3, "v0.1 measured failure baseline", V01_BASELINE)
    print_section(4, "v0.2 actionability quota/tier design", {
        "tiers": [asdict(spec) for spec in AnytimeControllerConfig().actionability_tiers],
        "cache_key": "exact state + project predicate identity + normalized tier",
        "probe_budget_is_separate": True,
    })
    print_section(5, "strategic progress ordering", {
        "components": list(controller.StrategicProgressComponents.__dataclass_fields__),
        "stock_epoch_intrinsic_reward": False,
        "deal_priority": "exact structural delta plus bounded timing evidence",
    })
    print_section(6, "analysis/deal-counterfactual cache", {
        "A": gate_a.analyses, "B": gate_b.analyses, "C": gate_c.analyses
    })
    print_section(7, "proof-safety audit", proof_audit())
    print_section(8, "Gate A", asdict(gate_a))
    print_section(9, "Gate B", asdict(gate_b))
    print_section(10, "Gate C", asdict(gate_c))
    print_section(11, "Gate D production", None if gate_d_production is None else asdict(gate_d_production))
    print_section(12, "Gate D research", None if gate_d_research is None else asdict(gate_d_research))
    print_section(13, "unseen deterministic deals", unseen)
    print_section(14, "prospective verdict", {"verdict": verdict, "reason": reason})
    print_section(15, "canonical comparison after prospective freeze", {
        "prospective_frozen": prospective_frozen,
        "valid": canonical.valid,
        "solved": canonical.solved,
        "cost": canonical.mobilityware_moves,
        "path_hash": canonical.path_hash,
        "state_hash": canonical.state_hash,
        "machine_solution": None,
        "machine_le_171": None,
        "archive_written": False,
    })
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="validate report wiring with short Gate C and no Gate D",
    )
    args = parser.parse_args(argv)
    return run(quick=args.quick)


if __name__ == "__main__":
    raise SystemExit(main())
