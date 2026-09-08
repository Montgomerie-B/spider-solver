#!/usr/bin/env python3
"""Frozen three-deal migration comparison for StateServiceRegistry v0.1."""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import random
import statistics
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import workspace_service_generalisation_panel_v0_1 as panel
from spider.engine import SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller
from spider.planner.anytime_controller import (
    AnytimeControllerConfig,
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)
from spider.state_identity import canonical_state_key


BASE_SHA = "57d301efc0324353d27be70eef20062d8a14e4ec"
EXPERIMENT = "state_service_registry_v0_1"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
PLAN_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT}_plan.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT
DEALS = ("P0", "P2", "P7")
LEGACY = "LEGACY_BOOKKEEPING"
REGISTRY = "STATE_SERVICE_REGISTRY"
ARMS = (LEGACY, REGISTRY)
RUN_ORDER = {
    "P0": (LEGACY, REGISTRY),
    "P2": (REGISTRY, LEGACY),
    "P7": (LEGACY, REGISTRY),
}
CONFIG = {
    "controller_seed": 0,
    "max_strategic_expansions": 80,
    "max_tactical_nodes": 120_000,
    "wall_clock_limit_s": 240.0,
    "max_frontier_size": 256,
    "max_successors_per_expansion": 10,
    "max_credit_level": 4,
    "scheduler": True,
    "tactical_allocation": True,
    "incumbent": None,
    "target_foundation_count": 2,
    "priority_schema": "COMMON_STAGE0",
    "credit_propagation": "STATE_LOCAL",
    "workspace_service": False,
    "resource_planner": False,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def frozen_plan() -> dict:
    definition = panel.panel_definition()
    entries = {
        item["panel_entry"]: {
            "fixture_path": item["fixture_path"],
            "opening_digest": item["opening_digest"],
            "fixture_sha256": item["fixture_sha256"],
        }
        for item in definition["entries"]
        if item["panel_entry"] in DEALS
    }
    return {
        "experiment": EXPERIMENT,
        "status": "FROZEN_PRE_RUN",
        "base_sha": BASE_SHA,
        "deals": list(DEALS),
        "arms": list(ARMS),
        "run_order": {deal: list(RUN_ORDER[deal]) for deal in DEALS},
        "config": CONFIG,
        "config_fingerprint": _fingerprint(),
        "fixtures": entries,
        "registry_contract": {
            "canonical_state_identity": "UNCHANGED",
            "coverage_request": (
                "canonical state + credit + CURRENT_STRATEGIC_SUCCESSORS + "
                "BEST_ARRIVAL_STRATEGIC_NODE_V0_1 adapter"
            ),
            "reopening": (
                "every existing current-generator credit request is reopened once "
                "when the exact state's best corrected arrival cost decreases"
            ),
            "production_default": False,
        },
    }


def _config(registry_enabled: bool):
    config = common.production_shadow._production_config(
        seconds=CONFIG["wall_clock_limit_s"],
        expansions=CONFIG["max_strategic_expansions"],
        nodes=CONFIG["max_tactical_nodes"],
    )
    return replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
        enable_state_service_registry=registry_enabled,
    )


def _trajectory_digest(result) -> str:
    rows = tuple(
        (
            entry.state_hash,
            entry.g,
            entry.strategic_credit_level,
            entry.stock_epoch,
            entry.foundations,
            entry.face_down,
            entry.chosen_successors,
        )
        for entry in result.telemetry.decision_trace
    )
    return hashlib.sha256(repr(rows).encode("utf-8")).hexdigest()[:16]


def _replay_check(opening: SpiderState, node) -> dict:
    replay = opening.clone()
    corrected_cost = replay_actions(replay, list(node.actions))
    return {
        "corrected_cost": corrected_cost,
        "expected_g": node.g,
        "cost_matches": corrected_cost == node.g,
        "state_matches": canonical_state_key(replay) == canonical_state_key(node.state),
    }


def compact_result(opening: SpiderState, result, *, arm: str) -> dict:
    telemetry = result.telemetry
    return {
        "arm": arm,
        "stop_reason": result.stop_reason,
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "elapsed_s": result.elapsed_seconds,
        "successors_generated": telemetry.generated,
        "successors_retained": telemetry.retained,
        "tt": {
            "new": telemetry.tt_new,
            "improved": telemetry.tt_improved,
            "suppressed": telemetry.tt_suppressed,
        },
        "minimum_face_down": telemetry.lowest_face_down,
        "minimum_expanded_stock_rows": len(result.deepest_stock_node.state.stock) // 10,
        "maximum_foundations": telemetry.best_foundations,
        "proof_pruned": telemetry.proof_pruned,
        "frontier_remaining": result.frontier_remaining,
        "maximum_credit_reached": result.maximum_credit_reached,
        "credit_expansions": [
            telemetry.credit_expansions.get(level, 0) for level in range(5)
        ],
        "trajectory_digest": _trajectory_digest(result),
        "best_progress_digest": common.digest(result.best_progress_node.state),
        "best_progress_replay": _replay_check(opening, result.best_progress_node),
        "solution_replay_failures": telemetry.solution_replay_failures,
        "registry": {
            "enabled": telemetry.registry_enabled,
            "states": telemetry.registry_states,
            "service_requests": telemetry.registry_service_requests,
            "status_counts": telemetry.registry_status_counts,
            "cheaper_arrival_updates": telemetry.registry_cheaper_arrival_updates,
            "reopening_events": telemetry.registry_reopening_events,
            "eviction_deferrals": telemetry.registry_eviction_deferrals,
            "reactivations": telemetry.registry_reactivations,
            "duplicate_request_coalesces": (
                telemetry.registry_duplicate_request_coalesces
            ),
            "stale_handles_rejected_before_analysis": (
                telemetry.registry_stale_handles_rejected_before_analysis
            ),
            "live_handle_invariant_violations": (
                telemetry.registry_live_handle_invariant_violations
            ),
            "service_executions": telemetry.registry_service_executions,
            "approximate_bytes": telemetry.registry_approximate_bytes,
        },
    }


def run_arm(entry: dict, arm: str) -> dict:
    cards = panel.load_entry_cards(entry)
    opening = SpiderState.from_cards(list(cards))
    random.seed(CONFIG["controller_seed"])
    result = controller.solve_anytime(
        opening.clone(),
        cards,
        None,
        _config(arm == REGISTRY),
    )
    return compact_result(opening, result, arm=arm)


def checkpoint_path(deal: str, arm: str) -> Path:
    return CHECKPOINT_DIR / f"{deal}_{arm.lower()}.json"


def execute() -> dict:
    definition = panel.panel_definition()
    entries = {
        item["panel_entry"]: item
        for item in definition["entries"]
        if item["panel_entry"] in DEALS
    }
    runs = {}
    for deal in DEALS:
        runs[deal] = {}
        for arm in RUN_ORDER[deal]:
            path = checkpoint_path(deal, arm)
            if path.exists():
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                if checkpoint.get("config_fingerprint") == _fingerprint():
                    print(f"RESUME {deal} {arm}", flush=True)
                    runs[deal][arm] = checkpoint["result"]
                    continue
            print(f"START {deal} {arm}", flush=True)
            result = run_arm(entries[deal], arm)
            _write_json(
                path,
                {
                    "experiment": EXPERIMENT,
                    "deal": deal,
                    "arm": arm,
                    "config_fingerprint": _fingerprint(),
                    "completed_utc": utc_now(),
                    "result": result,
                },
            )
            runs[deal][arm] = result
            print(
                f"DONE {deal} {arm} expansions={result['strategic_expansions']} "
                f"elapsed={result['elapsed_s']:.1f}s fd={result['minimum_face_down']} "
                f"stock={result['minimum_expanded_stock_rows']}",
                flush=True,
            )
    return runs


def build_result(runs: dict) -> dict:
    comparisons = []
    for deal in DEALS:
        legacy = runs[deal][LEGACY]
        registry = runs[deal][REGISTRY]
        comparisons.append(
            {
                "deal": deal,
                "trajectory_changed": (
                    legacy["trajectory_digest"] != registry["trajectory_digest"]
                ),
                "strategic_expansion_delta": (
                    registry["strategic_expansions"] - legacy["strategic_expansions"]
                ),
                "tactical_node_delta": (
                    registry["tactical_nodes"] - legacy["tactical_nodes"]
                ),
                "elapsed_ratio": (
                    registry["elapsed_s"] / legacy["elapsed_s"]
                    if legacy["elapsed_s"]
                    else None
                ),
                "face_down_delta": (
                    registry["minimum_face_down"] - legacy["minimum_face_down"]
                ),
                "stock_rows_delta": (
                    registry["minimum_expanded_stock_rows"]
                    - legacy["minimum_expanded_stock_rows"]
                ),
                "foundation_delta": (
                    registry["maximum_foundations"] - legacy["maximum_foundations"]
                ),
            }
        )
    registry_runs = [runs[deal][REGISTRY] for deal in DEALS]
    all_runs = [runs[deal][arm] for deal in DEALS for arm in ARMS]
    gates = {
        "all_six_runs_complete": all(
            run["strategic_expansions"] == CONFIG["max_strategic_expansions"]
            for run in all_runs
        ),
        "best_progress_replay_and_cost_integrity": all(
            run["best_progress_replay"]["state_matches"]
            and run["best_progress_replay"]["cost_matches"]
            and not run["solution_replay_failures"]
            for run in all_runs
        ),
        "registry_executed": all(
            run["registry"]["service_executions"] > 0 for run in registry_runs
        ),
        "one_live_handle_invariant": all(
            run["registry"]["live_handle_invariant_violations"] == 0
            for run in registry_runs
        ),
        "exact_identity_source_unchanged": (
            "scheduler" not in inspect.getsource(canonical_state_key)
            and "service" not in inspect.getsource(canonical_state_key)
        ),
        "production_defaults_unchanged": (
            not AnytimeControllerConfig().enable_state_service_registry
            and AnytimeControllerConfig().frontier_priority_schema
            == FrontierPrioritySchema.LEGACY
            and AnytimeControllerConfig().strategic_credit_propagation
            == StrategicCreditPropagation.INHERITED
        ),
        "resource_planner_not_integrated": (
            "resource_excavation" not in inspect.getsource(controller)
        ),
    }
    elapsed_ratios = [row["elapsed_ratio"] for row in comparisons]
    return {
        **frozen_plan(),
        "status": "COMPLETE",
        "runs": runs,
        "comparisons": comparisons,
        "aggregate": {
            "registry_states": sum(run["registry"]["states"] for run in registry_runs),
            "registry_service_requests": sum(
                run["registry"]["service_requests"] for run in registry_runs
            ),
            "cheaper_arrival_updates": sum(
                run["registry"]["cheaper_arrival_updates"] for run in registry_runs
            ),
            "reopening_events": sum(
                run["registry"]["reopening_events"] for run in registry_runs
            ),
            "eviction_deferrals": sum(
                run["registry"]["eviction_deferrals"] for run in registry_runs
            ),
            "reactivations": sum(
                run["registry"]["reactivations"] for run in registry_runs
            ),
            "stale_handles_rejected_before_analysis": sum(
                run["registry"]["stale_handles_rejected_before_analysis"]
                for run in registry_runs
            ),
            "service_executions": sum(
                run["registry"]["service_executions"] for run in registry_runs
            ),
            "approximate_bytes": sum(
                run["registry"]["approximate_bytes"] for run in registry_runs
            ),
            "elapsed_ratio_median": statistics.median(elapsed_ratios),
            "elapsed_ratio_min": min(elapsed_ratios),
            "elapsed_ratio_max": max(elapsed_ratios),
        },
        "gates": gates,
        "verdict": (
            "STATE_SERVICE_REGISTRY_READY"
            if all(gates.values())
            else "STATE_SERVICE_REGISTRY_REGRESSION"
        ),
        "completed_utc": utc_now(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-plan-only", action="store_true")
    args = parser.parse_args()
    plan = frozen_plan()
    _write_json(PLAN_PATH, plan)
    if args.freeze_plan_only:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    result = build_result(execute())
    _write_json(RESULT_PATH, result)
    print(f"VERDICT {result['verdict']}", flush=True)
    print(f"WROTE {RESULT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
