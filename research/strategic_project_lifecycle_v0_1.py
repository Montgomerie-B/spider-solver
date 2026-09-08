#!/usr/bin/env python3
"""Frozen lifecycle-equivalence panel for same-campaign StrategicProject v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import state_service_registry_subscribers_v0_1 as prior
import workspace_service_generalisation_panel_v0_1 as panel
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import solve_anytime
from spider.state_identity import canonical_state_key


EXPERIMENT = "strategic_project_lifecycle_v0_1"
BASE_SHA = "dc778dc7b33239b6cfaec77e7181b129cdd60830"
CURRENT = "CURRENT_CONTINUATION_OWNERSHIP"
PROJECT = "STRATEGIC_PROJECT_CONTINUATION"
ARMS = (CURRENT, PROJECT)
DEALS = ("P0", "P2", "P7")
RUN_ORDER = {
    "P0": (CURRENT, PROJECT),
    "P2": (PROJECT, CURRENT),
    "P7": (CURRENT, PROJECT),
}
CONFIG = {
    "implementation_revision": 2,
    "seed": 0,
    "max_strategic_expansions": 80,
    "max_tactical_nodes": 120_000,
    "wall_clock_limit_s": 240.0,
    "target_foundation_count": 2,
    "frontier_priority_schema": "COMMON_STAGE0",
    "strategic_credit_propagation": "STATE_LOCAL",
    "state_service_registry": True,
    "state_service_subscribers": True,
}
PLAN = ROOT / "docs" / "research" / f"{EXPERIMENT}_plan.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {"base": BASE_SHA, "deals": DEALS, "arms": ARMS, "order": RUN_ORDER, "config": CONFIG},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def frozen_plan() -> dict:
    entries = {
        item["panel_entry"]: {
            "fixture_path": item["fixture_path"],
            "opening_digest": item["opening_digest"],
            "fixture_sha256": item["fixture_sha256"],
        }
        for item in panel.panel_definition()["entries"]
        if item["panel_entry"] in DEALS
    }
    return {
        "experiment": EXPERIMENT,
        "status": "FROZEN_PRE_RUN",
        "base_sha": BASE_SHA,
        "deals": list(DEALS),
        "arms": list(ARMS),
        "run_order": {key: list(value) for key, value in RUN_ORDER.items()},
        "config": CONFIG,
        "config_fingerprint": _fingerprint(),
        "fixtures": entries,
        "selection_rationale": (
            "Mandatory frozen P0/P2/P7. P0 produced a continuation during the pre-panel "
            "implementation smoke, so no fourth fixture was selected; no project outcome was "
            "used to choose among fixtures."
        ),
    }


def _config(project: bool):
    return replace(
        prior._config(True),
        enable_strategic_project_continuation=project,
    )


def _trajectory(result) -> str:
    rows = tuple(
        (
            row.state_hash,
            row.g,
            row.strategic_credit_level,
            row.stock_epoch,
            row.foundations,
            row.face_down,
            row.chosen_successors,
        )
        for row in result.telemetry.decision_trace
    )
    return hashlib.sha256(repr(rows).encode()).hexdigest()[:16]


def compact(opening, result, arm: str) -> dict:
    node = result.best_progress_node
    replay = opening.clone()
    replay_cost = replay_actions(replay, list(node.actions))
    t = result.telemetry
    return {
        "arm": arm,
        "stop_reason": result.stop_reason,
        "strategic_expansions": result.strategic_expansions,
        "service_executions": t.registry_service_executions,
        "tactical_nodes": result.tactical_nodes,
        "elapsed_s": result.elapsed_seconds,
        "tt": {"new": t.tt_new, "improved": t.tt_improved, "suppressed": t.tt_suppressed},
        "credit_expansions": [t.credit_expansions.get(level, 0) for level in range(5)],
        "minimum_face_down": t.lowest_face_down,
        "stock_rows_remaining": len(result.deepest_stock_node.state.stock) // 10,
        "maximum_foundations": t.best_foundations,
        "trajectory_digest": _trajectory(result),
        "best_progress_digest": common.digest(node.state),
        "best_progress_replay": {
            "cost_matches": replay_cost == node.g,
            "state_matches": canonical_state_key(replay) == canonical_state_key(node.state),
        },
        "continuation": {
            "created": t.continuation_credits_created,
            "admitted": t.continuation_descendants_admitted,
            "retained": t.continuation_descendants_retained,
            "replanned": t.continuation_credits_replanned,
            "harvested": t.continuation_credits_harvested,
            "invalidated": t.continuation_credits_invalidated,
            "expired": t.continuation_credits_expired,
            "superseded": t.continuation_credits_superseded,
        },
        "registry": {
            "states": t.registry_states,
            "requests": t.registry_service_requests,
            "bytes": t.registry_approximate_bytes,
            "reopenings": t.registry_reopening_events,
            "reactivations": t.registry_reactivations,
            "handle_errors": t.registry_live_handle_invariant_violations,
        },
        "projects": t.strategic_project_snapshot,
    }


def run(entry: dict, arm: str) -> dict:
    cards = panel.load_entry_cards(entry)
    opening = SpiderState.from_cards(list(cards))
    random.seed(CONFIG["seed"])
    result = solve_anytime(opening.clone(), cards, None, _config(arm == PROJECT))
    return compact(opening, result, arm)


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
            path = CHECKPOINTS / f"{deal}_{arm.lower()}.json"
            if path.exists():
                saved = json.loads(path.read_text(encoding="utf-8"))
                if saved.get("config_fingerprint") == _fingerprint():
                    runs[deal][arm] = saved["result"]
                    print(f"RESUME {deal} {arm}", flush=True)
                    continue
            print(f"START {deal} {arm}", flush=True)
            measured = run(entries[deal], arm)
            _write(path, {"config_fingerprint": _fingerprint(), "result": measured})
            runs[deal][arm] = measured
            print(
                f"DONE {deal} {arm} exp={measured['strategic_expansions']} "
                f"elapsed={measured['elapsed_s']:.2f} projects={measured['projects'].get('projects', 0)}",
                flush=True,
            )
    return runs


def build_result(runs: dict) -> dict:
    comparisons = []
    for deal in DEALS:
        a, b = runs[deal][CURRENT], runs[deal][PROJECT]
        comparisons.append(
            {
                "deal": deal,
                "trajectory_changed": a["trajectory_digest"] != b["trajectory_digest"],
                "strategic_expansion_delta": b["strategic_expansions"] - a["strategic_expansions"],
                "service_execution_delta": b["service_executions"] - a["service_executions"],
                "tactical_node_delta": b["tactical_nodes"] - a["tactical_nodes"],
                "elapsed_ratio": b["elapsed_s"] / a["elapsed_s"],
                "face_down_delta": b["minimum_face_down"] - a["minimum_face_down"],
                "stock_rows_delta": b["stock_rows_remaining"] - a["stock_rows_remaining"],
                "foundation_delta": b["maximum_foundations"] - a["maximum_foundations"],
            }
        )
    project_runs = [runs[deal][PROJECT] for deal in DEALS]
    def total(field):
        return sum(item["projects"].get(field, 0) for item in project_runs)
    aggregate = {
        "projects_created": total("projects_created"),
        "maximum_concurrent_projects": max(item["projects"].get("maximum_simultaneous_projects", 0) for item in project_runs),
        "candidate_replacements": total("candidate_replacements"),
        "service_executions_observed": total("project_service_executions"),
        "semantic_progress_events": total("project_progress_events"),
        "activity_without_progress": total("service_executions_without_progress"),
        "projects_expired": total("projects_expired"),
        "cheaper_arrival_revalidations": total("cheaper_arrival_revalidations"),
        "candidate_defer_events": total("candidate_defer_events"),
        "candidate_reactivate_events": total("candidate_reactivate_events"),
        "incremental_project_bytes": sum(item["projects"].get("approximate_bytes", 0) for item in project_runs),
        "median_elapsed_ratio": statistics.median(row["elapsed_ratio"] for row in comparisons),
    }
    gates = {
        "all_runs_complete": all(runs[d][a]["strategic_expansions"] == 80 for d in DEALS for a in ARMS),
        "replay_integrity": all(all(runs[d][a]["best_progress_replay"].values()) for d in DEALS for a in ARMS),
        "project_path_exercised": aggregate["projects_created"] > 0,
        "one_handle_invariant": all(runs[d][a]["registry"]["handle_errors"] == 0 for d in DEALS for a in ARMS),
        "outcome_equivalence": all(
            not row["face_down_delta"] and not row["stock_rows_delta"] and not row["foundation_delta"]
            for row in comparisons
        ),
    }
    return {
        **frozen_plan(),
        "status": "COMPLETE",
        "runs": runs,
        "comparisons": comparisons,
        "aggregate": aggregate,
        "gates": gates,
        "verdict": "STRATEGIC_PROJECT_LIFECYCLE_READY" if all(gates.values()) else "STRATEGIC_PROJECT_LIFECYCLE_PARTIAL",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-plan-only", action="store_true")
    args = parser.parse_args()
    _write(PLAN, frozen_plan())
    if args.freeze_plan_only:
        print(f"FROZEN {PLAN}")
        return 0
    result = build_result(execute())
    _write(RESULT, result)
    print(f"VERDICT {result['verdict']}")
    print(f"WROTE {RESULT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
