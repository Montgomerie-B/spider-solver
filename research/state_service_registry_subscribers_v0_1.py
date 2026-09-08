#!/usr/bin/env python3
"""Frozen ownership A/B for StateServiceRegistry subscriber consolidation."""

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


BASE_SHA = "b79419bda094941869925b35ec5730c6aa1e45ed"
EXPERIMENT = "state_service_registry_subscribers_v0_1"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
PLAN_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT}_plan.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT
DEALS = ("P0", "P2", "P7")
OWNERSHIP = "REGISTRY_V0_1_OWNERSHIP"
SUBSCRIBERS = "REGISTRY_SUBSCRIBERS"
ARMS = (OWNERSHIP, SUBSCRIBERS)
RUN_ORDER = {
    "P0": (OWNERSHIP, SUBSCRIBERS),
    "P2": (SUBSCRIBERS, OWNERSHIP),
    "P7": (OWNERSHIP, SUBSCRIBERS),
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
    "state_service_registry": True,
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
    payload = {"config": CONFIG, "arms": ARMS, "run_order": RUN_ORDER}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
        "selection_rationale": (
            "P0/P2/P7 are the mandatory existing frozen fixtures; the prior 80-expansion "
            "registry panel advances 3/4/1 stock rows respectively, so the unchanged "
            "envelope naturally reaches epoch-transition eligibility without outcome-based "
            "fixture selection. Focused deterministic tests cover all completion/epoch "
            "overlaps even if a panel mechanism is sparse."
        ),
        "ownership_contract": {
            "arm_a": "registry lifecycle plus legacy node-owned completion/epoch reservations",
            "arm_b": "same registry request/handle with ordinary, completion and epoch subscribers",
            "priority": "unchanged RESERVED marker projected from subscriber entitlement",
            "quota": "one completion and one epoch entitlement; shared execution capacity once",
            "production_default": False,
        },
    }


def _config(subscribers: bool):
    config = common.production_shadow._production_config(
        seconds=CONFIG["wall_clock_limit_s"],
        expansions=CONFIG["max_strategic_expansions"],
        nodes=CONFIG["max_tactical_nodes"],
    )
    return replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
        enable_state_service_registry=True,
        enable_state_service_subscribers=subscribers,
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
    subscriber = {
        "enabled": telemetry.registry_subscribers_enabled,
        "records": telemetry.registry_subscriber_records,
        "records_by_kind": telemetry.registry_subscriber_records_by_kind,
        "active": telemetry.registry_active_subscribers,
        "active_by_kind": telemetry.registry_active_subscribers_by_kind,
        "attachments": telemetry.registry_subscriber_attachments,
        "attachments_by_kind": telemetry.registry_subscriber_attachments_by_kind,
        "request_combinations_observed": telemetry.registry_request_combinations_observed,
        "duplicate_subscriber_coalesces": telemetry.registry_duplicate_subscriber_coalesces,
        "duplicate_live_representations_prevented": (
            telemetry.registry_duplicate_live_representations_prevented
        ),
        "live_representations_used": telemetry.registry_subscriber_live_representations_used,
        "add_events": telemetry.registry_subscriber_add_events,
        "remove_events": telemetry.registry_subscriber_remove_events,
        "quota_usage": telemetry.registry_subscriber_quota_usage,
        "peak_quota_usage": telemetry.registry_peak_subscriber_quota_usage,
        "shared_executions": telemetry.registry_shared_executions,
        "executions_satisfying_multiple_subscribers": (
            telemetry.registry_executions_satisfying_multiple_subscribers
        ),
        "subscriber_satisfactions": telemetry.registry_subscriber_satisfactions,
        "stale_shared_handles_rejected": telemetry.registry_stale_shared_handles_rejected,
        "shared_request_deferrals": telemetry.registry_shared_request_deferrals,
        "shared_request_reactivations": telemetry.registry_shared_request_reactivations,
        "orphan_deferrals": telemetry.registry_subscriber_orphan_deferrals,
    }
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
        "reservation_ownership": {
            "completion_reserved": telemetry.completion_representatives_reserved,
            "completion_expanded": telemetry.completion_representatives_expanded,
            "epoch_reserved": telemetry.scheduler_transition_representatives_reserved,
            "epoch_expanded": telemetry.scheduler_transition_representatives_expanded,
            "old_independent_claims": (
                telemetry.completion_representatives_reserved
                + telemetry.scheduler_transition_representatives_reserved
            ),
        },
        "registry": {
            "states": telemetry.registry_states,
            "service_requests": telemetry.registry_service_requests,
            "status_counts": telemetry.registry_status_counts,
            "cheaper_arrival_updates": telemetry.registry_cheaper_arrival_updates,
            "reopening_events": telemetry.registry_reopening_events,
            "eviction_deferrals": telemetry.registry_eviction_deferrals,
            "reactivations": telemetry.registry_reactivations,
            "duplicate_request_coalesces": telemetry.registry_duplicate_request_coalesces,
            "stale_handles_rejected_before_analysis": (
                telemetry.registry_stale_handles_rejected_before_analysis
            ),
            "live_handle_invariant_violations": (
                telemetry.registry_live_handle_invariant_violations
            ),
            "service_executions": telemetry.registry_service_executions,
            "approximate_bytes": telemetry.registry_approximate_bytes,
            "subscribers": subscriber,
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
        _config(arm == SUBSCRIBERS),
    )
    return compact_result(opening, result, arm=arm)


def checkpoint_path(deal: str, arm: str) -> Path:
    return CHECKPOINT_DIR / f"{deal}_{arm.lower()}.json"


def execute() -> dict:
    entries = {
        item["panel_entry"]: item
        for item in panel.panel_definition()["entries"]
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
                f"stock={result['minimum_expanded_stock_rows']} "
                f"special={sum(result['registry']['subscribers']['attachments_by_kind'].get(k, 0) for k in ('COMPLETION_CASH_OUT', 'EPOCH_TRANSITION'))}",
                flush=True,
            )
    return runs


def _sum_kind(runs: list[dict], field: str, kind: str) -> int:
    return sum(
        run["registry"]["subscribers"][field].get(kind, 0) for run in runs
    )


def build_result(runs: dict) -> dict:
    comparisons = []
    for deal in DEALS:
        ownership = runs[deal][OWNERSHIP]
        subscribers = runs[deal][SUBSCRIBERS]
        comparisons.append(
            {
                "deal": deal,
                "trajectory_changed": ownership["trajectory_digest"] != subscribers["trajectory_digest"],
                "strategic_expansion_delta": subscribers["strategic_expansions"] - ownership["strategic_expansions"],
                "service_execution_delta": subscribers["registry"]["service_executions"] - ownership["registry"]["service_executions"],
                "tactical_node_delta": subscribers["tactical_nodes"] - ownership["tactical_nodes"],
                "elapsed_ratio": subscribers["elapsed_s"] / ownership["elapsed_s"],
                "face_down_delta": subscribers["minimum_face_down"] - ownership["minimum_face_down"],
                "stock_rows_delta": subscribers["minimum_expanded_stock_rows"] - ownership["minimum_expanded_stock_rows"],
                "foundation_delta": subscribers["maximum_foundations"] - ownership["maximum_foundations"],
            }
        )
    subscriber_runs = [runs[deal][SUBSCRIBERS] for deal in DEALS]
    all_runs = [runs[deal][arm] for deal in DEALS for arm in ARMS]
    special_attachments = sum(
        _sum_kind(subscriber_runs, "attachments_by_kind", kind)
        for kind in ("COMPLETION_CASH_OUT", "EPOCH_TRANSITION")
    )
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
        "subscriber_path_exercised": special_attachments > 0,
        "one_live_handle_invariant": all(
            run["registry"]["live_handle_invariant_violations"] == 0
            for run in subscriber_runs
        ),
        "subscriber_quotas_preserved": all(
            run["registry"]["subscribers"]["peak_quota_usage"].get(kind, 0) <= 1
            for run in subscriber_runs
            for kind in ("COMPLETION_CASH_OUT", "EPOCH_TRANSITION")
        ),
        "production_defaults_unchanged": (
            not AnytimeControllerConfig().enable_state_service_registry
            and not AnytimeControllerConfig().enable_state_service_subscribers
            and AnytimeControllerConfig().frontier_priority_schema == FrontierPrioritySchema.LEGACY
            and AnytimeControllerConfig().strategic_credit_propagation == StrategicCreditPropagation.INHERITED
        ),
        "exact_identity_source_unchanged": (
            "scheduler" not in inspect.getsource(canonical_state_key)
            and "subscriber" not in inspect.getsource(canonical_state_key)
        ),
        "resource_planner_not_integrated": "resource_excavation" not in inspect.getsource(controller),
    }
    elapsed_ratios = [item["elapsed_ratio"] for item in comparisons]
    combinations = {}
    for run in subscriber_runs:
        for name, count in run["registry"]["subscribers"]["request_combinations_observed"].items():
            combinations[name] = combinations.get(name, 0) + count
    aggregate = {
        "registry_states": sum(run["registry"]["states"] for run in subscriber_runs),
        "registry_service_requests": sum(run["registry"]["service_requests"] for run in subscriber_runs),
        "duplicate_service_submissions_coalesced": sum(run["registry"]["duplicate_request_coalesces"] for run in subscriber_runs),
        "subscriber_attachments_by_kind": {
            kind: _sum_kind(subscriber_runs, "attachments_by_kind", kind)
            for kind in ("ORDINARY", "COMPLETION_CASH_OUT", "EPOCH_TRANSITION")
        },
        "request_combinations_observed": combinations,
        "old_independent_ownership_claims": sum(run["reservation_ownership"]["old_independent_claims"] for run in subscriber_runs),
        "duplicate_live_representations_prevented": sum(run["registry"]["subscribers"]["duplicate_live_representations_prevented"] for run in subscriber_runs),
        "subscriber_live_representations_used": sum(run["registry"]["subscribers"]["live_representations_used"] for run in subscriber_runs),
        "shared_executions": sum(run["registry"]["subscribers"]["shared_executions"] for run in subscriber_runs),
        "executions_satisfying_multiple_subscribers": sum(run["registry"]["subscribers"]["executions_satisfying_multiple_subscribers"] for run in subscriber_runs),
        "cheaper_arrival_updates": sum(run["registry"]["cheaper_arrival_updates"] for run in subscriber_runs),
        "reopening_events": sum(run["registry"]["reopening_events"] for run in subscriber_runs),
        "stale_shared_handles_rejected": sum(run["registry"]["subscribers"]["stale_shared_handles_rejected"] for run in subscriber_runs),
        "shared_request_deferrals": sum(run["registry"]["subscribers"]["shared_request_deferrals"] for run in subscriber_runs),
        "shared_request_reactivations": sum(run["registry"]["subscribers"]["shared_request_reactivations"] for run in subscriber_runs),
        "service_executions": sum(run["registry"]["service_executions"] for run in subscriber_runs),
        "approximate_bytes": sum(run["registry"]["approximate_bytes"] for run in subscriber_runs),
        "elapsed_ratio_median": statistics.median(elapsed_ratios),
        "elapsed_ratio_min": min(elapsed_ratios),
        "elapsed_ratio_max": max(elapsed_ratios),
    }
    return {
        **frozen_plan(),
        "status": "COMPLETE",
        "runs": runs,
        "comparisons": comparisons,
        "aggregate": aggregate,
        "gates": gates,
        "verdict": "REGISTRY_SUBSCRIBERS_READY" if all(gates.values()) else "REGISTRY_SUBSCRIBERS_REGRESSION",
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
