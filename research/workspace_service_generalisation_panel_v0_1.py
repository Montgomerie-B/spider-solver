#!/usr/bin/env python3
"""Resumable ten-deal A/B panel for the fixed workspace service lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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
import spider.planner.anytime_controller as controller
import state_local_credit_semantics_v0_1 as state_local
import workspace_opportunity_service_lane_v0_1 as service
import workspace_service_panel_v0_1 as panel
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)


BASE_SHA = "1af93024fd1add6ab18a36300d3fe819dbb69fe5"
EXPERIMENT_ID = "workspace_service_generalisation_panel_v0_1"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT_ID
ARMS = ("CONTROL", "WORKSPACE_SERVICE_1")
CONFIG = {
    "controller_seed": 0,
    "max_strategic_expansions": 400,
    "max_tactical_nodes": 300_000,
    "wall_clock_limit_s": 900.0,
    "max_frontier_size": 256,
    "max_successors_per_expansion": 10,
    "max_credit_level": 4,
    "scheduler": True,
    "tactical_allocation": True,
    "incumbent": None,
    "target_foundation_count": 2,
    "priority_schema": "COMMON_STAGE0",
    "credit_propagation": "STATE_LOCAL",
    "workspace_service_interval": 8,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def panel_definition() -> dict:
    frozen = json.loads(panel.PANEL_PATH.read_text(encoding="utf-8"))
    if frozen != panel.build_panel_definition():
        raise RuntimeError("frozen panel definition no longer matches fixtures/generator")
    return frozen


def load_entry_cards(entry: dict) -> tuple:
    cards = tuple(load_deal(ROOT / entry["fixture_path"]))
    opening = panel.validate_cards(cards)
    if common.digest(opening) != entry["opening_digest"]:
        raise RuntimeError(f"opening digest mismatch for {entry['panel_entry']}")
    return cards


class PanelWorkspaceServiceObserver(service.WorkspaceServiceObserver):
    """Add control-arm workspace lifecycle telemetry without changing policy."""

    def install(self) -> None:
        super().install()
        observed_generate = controller.generate_strategic_successors
        observer = self

        def wrapped_generate(node, cards, **kwargs):
            before_event = len(observer.events)
            successors = observed_generate(node, cards, **kwargs)
            mode = observer.expansion_modes[node.node_id]
            if service.workspace_class(node.state) is not None and mode == "ORDINARY":
                facts = service.workspace_facts(node.state)
                observer.workspace_expansions.append(
                    {
                        "node_id": node.node_id,
                        "digest": common.digest(node.state),
                        "g": int(node.g),
                        "credit": int(node.credit_level),
                        "mode": mode,
                        "workspace_class": facts["workspace_class"],
                        "parent_facts": facts,
                        "event_ids": [
                            event["event_id"] for event in observer.events[before_event:]
                        ],
                    }
                )
            return successors

        controller.generate_strategic_successors = wrapped_generate


def _solution_replay(opening: SpiderState, result) -> dict | None:
    incumbent = result.incumbent
    if incumbent is None or incumbent.foundations != 8:
        return None
    replay = opening.clone()
    replay_cost = replay_actions(replay, list(incumbent.actions))
    return {
        "corrected_cost": incumbent.corrected_cost,
        "replay_cost": replay_cost,
        "solved": replay.is_solved(),
        "foundations": len(replay.foundations),
        "path_hash": incumbent.path_hash,
        "verified": replay_cost == incumbent.corrected_cost and replay.is_solved(),
    }


def _productive_endpoints(full: dict, mode: str) -> tuple[int, int, list[str]]:
    rows = [
        successor
        for expansion in full["workspace_lifecycle"]["expansions"]
        for successor in expansion["successors"]
        if successor["retained_productive"]
        and successor["child_expansion_mode"] == mode
    ]
    digests = sorted({row["child_digest"] for row in rows})
    return len(rows), len(digests), digests


def _minimum_expanded_stock_rows(full: dict) -> int | None:
    values = [
        int(stock_rows)
        for stock_rows, count in full["stock_progression"]["expanded"].items()
        if count
    ]
    return min(values) if values else None


def compact_arm(
    full: dict,
    opening: SpiderState,
    result,
    *,
    final_duplicate_node_ids: list[int],
) -> dict:
    ordinary_total, ordinary_unique, ordinary_digests = _productive_endpoints(
        full, "ORDINARY"
    )
    workspace_rows = [
        successor
        for expansion in full["workspace_lifecycle"]["expansions"]
        for successor in expansion["successors"]
        if successor["retained_productive"]
        and successor["child_expansion_mode"]
        in {"WORKSPACE_FORCED", "WORKSPACE_NATURAL"}
    ]
    workspace_digests = sorted({row["child_digest"] for row in workspace_rows})
    lane = full["workspace_service"]
    natural_workspace_parent_expansions = sum(
        expansion["mode"] == "ORDINARY"
        for expansion in full["workspace_lifecycle"]["expansions"]
    )
    return {
        "stop_reason": full["stop_reason"],
        "elapsed_s": full["elapsed_s"],
        "strategic_expansions": full["strategic_expansions"],
        "tactical_nodes": full["tactical_nodes"],
        "successors_generated": full["successors_generated"],
        "successors_retained": full["successors_retained"],
        "tt": full["tt"],
        "proof_pruned": full["proof_pruned"],
        "replay_failures": full["replay_failures"],
        "corrected_cost_inconsistencies": full["corrected_cost_inconsistencies"],
        "independent_replay_false": full["independent_replay_false"],
        "proof_pruning_successor_flags": full["proof_pruning_successor_flags"],
        "credit_expansions": [
            full["credit"][str(value)]["expansions"] for value in range(5)
        ],
        "minimum_face_down": full["minimum_face_down"],
        "maximum_foundations": full["maximum_foundations"],
        "maximum_actual_empty_count": full["maximum_actual_empty_count"],
        "minimum_expanded_stock_rows": _minimum_expanded_stock_rows(full),
        "EMPTY_CREATABLE": full["EMPTY_CREATABLE"],
        "ACTUAL_EMPTY": full["ACTUAL_EMPTY"],
        "workspace": {
            "representatives_selected": lane["selections"],
            "forced_services": lane["forced_service_expansions"],
            "natural_services": lane["natural_expansions_before_forced_service"],
            "invalidations": lane["invalidations"],
            "max_outstanding": lane["max_outstanding"],
            "service_intervals": lane["service_interval_distribution"],
            "minimum_forced_interval_respected": lane[
                "minimum_forced_interval_respected"
            ],
            "lane_duplicate_entries_introduced": lane[
                "lane_duplicate_entries_introduced"
            ],
            "natural_workspace_parent_expansions": natural_workspace_parent_expansions,
            "productive_descendants_retained": full["workspace_lifecycle"][
                "retained_productive_workspace_descendants"
            ],
            "productive_descendants_ordinary_serviced": ordinary_total,
            "productive_descendants_ordinary_serviced_unique": ordinary_unique,
            "ordinary_serviced_endpoint_digests": ordinary_digests,
            "productive_descendants_workspace_serviced": len(workspace_rows),
            "productive_descendants_workspace_serviced_unique": len(
                workspace_digests
            ),
        },
        "frontier": {
            **full["frontier"],
            "duplicate_node_ids": final_duplicate_node_ids,
        },
        "existing_duplicate_occurrence_count": len(
            full["existing_duplicate_occurrences"]
        ),
        "resource_planner_calls": full["resource_planner_calls"],
        "priority_schema": full["priority_schema"],
        "credit_propagation": full["credit_propagation"],
        "complete_solution_replay": _solution_replay(opening, result),
    }


def run_arm(cards: tuple, *, enable_service: bool) -> dict:
    random.seed(CONFIG["controller_seed"])
    config = common.production_shadow._production_config(
        seconds=CONFIG["wall_clock_limit_s"],
        expansions=CONFIG["max_strategic_expansions"],
        nodes=CONFIG["max_tactical_nodes"],
    )
    config = replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    state_local.assert_config(config)
    opening = SpiderState.from_cards(list(cards))
    observer = PanelWorkspaceServiceObserver(
        opening, enable_service=enable_service
    )
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        full = observer.workspace_summary(result)
        final_duplicate_node_ids = sorted(
            observer._duplicate_ids(observer.frontier or []).keys()
        )
    finally:
        observer.restore()
    full["priority_schema"] = config.frontier_priority_schema.value
    full["credit_propagation"] = config.strategic_credit_propagation.value
    return compact_arm(
        full,
        opening,
        result,
        final_duplicate_node_ids=final_duplicate_node_ids,
    )


def _checkpoint_path(panel_entry: str, arm: str) -> Path:
    return CHECKPOINT_DIR / f"{panel_entry}_{arm.lower()}.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _config_fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(CONFIG, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _load_checkpoint(entry: dict, arm: str) -> dict | None:
    path = _checkpoint_path(entry["panel_entry"], arm)
    if not path.exists():
        return None
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "experiment": EXPERIMENT_ID,
        "panel_entry": entry["panel_entry"],
        "opening_digest": entry["opening_digest"],
        "arm": arm,
        "config_fingerprint": _config_fingerprint(),
    }
    actual = {key: checkpoint.get(key) for key in expected}
    if actual != expected:
        raise RuntimeError({"checkpoint": str(path), "actual": actual, "expected": expected})
    return checkpoint


def execute_missing_runs(definition: dict, *, stop_after_pairs: int | None = None) -> dict:
    all_runs: dict[str, dict] = {}
    completed_pairs = 0
    for entry in definition["entries"]:
        panel_entry = entry["panel_entry"]
        cards = load_entry_cards(entry)
        control_opening = SpiderState.from_cards(list(cards))
        treatment_opening = SpiderState.from_cards(list(cards))
        if common.digest(control_opening) != common.digest(treatment_opening):
            raise RuntimeError(f"arm initial states differ for {panel_entry}")
        all_runs[panel_entry] = {}
        for order_index, arm in enumerate(entry["run_order"], start=1):
            checkpoint = _load_checkpoint(entry, arm)
            if checkpoint is None:
                print(
                    f"START {panel_entry} {arm} order={order_index}/2 at {utc_now()}",
                    flush=True,
                )
                started = utc_now()
                summary = run_arm(cards, enable_service=arm == "WORKSPACE_SERVICE_1")
                checkpoint = {
                    "experiment": EXPERIMENT_ID,
                    "panel_entry": panel_entry,
                    "opening_digest": entry["opening_digest"],
                    "arm": arm,
                    "run_order_index": order_index,
                    "config_fingerprint": _config_fingerprint(),
                    "started_utc": started,
                    "completed_utc": utc_now(),
                    "summary": summary,
                }
                _write_json_atomic(_checkpoint_path(panel_entry, arm), checkpoint)
                print(
                    f"DONE {panel_entry} {arm}: exp={summary['strategic_expansions']} "
                    f"fd={summary['minimum_face_down']} "
                    f"EC={summary['EMPTY_CREATABLE']['expanded']} "
                    f"AE={summary['ACTUAL_EMPTY']['expanded']} "
                    f"ordinary={summary['workspace']['productive_descendants_ordinary_serviced']} "
                    f"tactical={summary['tactical_nodes']} elapsed={summary['elapsed_s']:.1f}s",
                    flush=True,
                )
            else:
                print(f"RESUME {panel_entry} {arm} from checkpoint", flush=True)
            all_runs[panel_entry][arm] = checkpoint["summary"]
        completed_pairs += 1
        if stop_after_pairs is not None and completed_pairs >= stop_after_pairs:
            break
    return all_runs


def _credit_balance(control: dict, treatment: dict) -> dict:
    control_total = max(1, sum(control["credit_expansions"]))
    treatment_total = max(1, sum(treatment["credit_expansions"]))
    control_shares = [value / control_total for value in control["credit_expansions"]]
    treatment_shares = [value / treatment_total for value in treatment["credit_expansions"]]
    deltas = [treatment_shares[i] - control_shares[i] for i in range(5)]
    reasons = []
    if max(treatment_shares) > 0.60:
        reasons.append("treatment credit level exceeds 60% of expansions")
    if max(abs(value) for value in deltas) > 0.25:
        reasons.append("paired credit share shifts by more than 25 percentage points")
    return {
        "flagged": bool(reasons),
        "reasons": reasons,
        "control_shares": control_shares,
        "treatment_shares": treatment_shares,
        "paired_share_deltas": deltas,
    }


def paired_rows(definition: dict, runs: dict) -> list[dict]:
    entries = {entry["panel_entry"]: entry for entry in definition["entries"]}
    rows = []
    for panel_entry in [f"P{index}" for index in range(10)]:
        if panel_entry not in runs or any(arm not in runs[panel_entry] for arm in ARMS):
            continue
        control = runs[panel_entry]["CONTROL"]
        treatment = runs[panel_entry]["WORKSPACE_SERVICE_1"]
        control_workspace = (
            control["EMPTY_CREATABLE"]["expanded"]
            + control["ACTUAL_EMPTY"]["expanded"]
        )
        treatment_workspace = (
            treatment["EMPTY_CREATABLE"]["expanded"]
            + treatment["ACTUAL_EMPTY"]["expanded"]
        )
        rows.append(
            {
                "panel_entry": panel_entry,
                "opening_digest": entries[panel_entry]["opening_digest"],
                "run_order": entries[panel_entry]["run_order"],
                "workspace_expansions": {
                    "control": control_workspace,
                    "treatment": treatment_workspace,
                    "delta": treatment_workspace - control_workspace,
                },
                "EMPTY_CREATABLE_expanded": {
                    "control": control["EMPTY_CREATABLE"]["expanded"],
                    "treatment": treatment["EMPTY_CREATABLE"]["expanded"],
                },
                "ACTUAL_EMPTY_expanded": {
                    "control": control["ACTUAL_EMPTY"]["expanded"],
                    "treatment": treatment["ACTUAL_EMPTY"]["expanded"],
                },
                "productive_descendants_retained": {
                    "control": control["workspace"]["productive_descendants_retained"],
                    "treatment": treatment["workspace"]["productive_descendants_retained"],
                },
                "ordinary_serviced_productive_descendants": {
                    "control": control["workspace"][
                        "productive_descendants_ordinary_serviced"
                    ],
                    "treatment": treatment["workspace"][
                        "productive_descendants_ordinary_serviced"
                    ],
                    "control_unique": control["workspace"][
                        "productive_descendants_ordinary_serviced_unique"
                    ],
                    "treatment_unique": treatment["workspace"][
                        "productive_descendants_ordinary_serviced_unique"
                    ],
                },
                "minimum_face_down": {
                    "control": control["minimum_face_down"],
                    "treatment": treatment["minimum_face_down"],
                    "delta": treatment["minimum_face_down"]
                    - control["minimum_face_down"],
                },
                "maximum_foundations": {
                    "control": control["maximum_foundations"],
                    "treatment": treatment["maximum_foundations"],
                },
                "minimum_expanded_stock_rows": {
                    "control": control["minimum_expanded_stock_rows"],
                    "treatment": treatment["minimum_expanded_stock_rows"],
                },
                "tactical_node_ratio": treatment["tactical_nodes"]
                / control["tactical_nodes"],
                "elapsed_time_ratio": treatment["elapsed_s"] / control["elapsed_s"],
                "credit_balance": _credit_balance(control, treatment),
            }
        )
    return rows


def _foundation_outcome(row: dict) -> str:
    control = row["maximum_foundations"]["control"] > 0
    treatment = row["maximum_foundations"]["treatment"] > 0
    if control and treatment:
        return "both"
    if treatment:
        return "treatment_only"
    if control:
        return "control_only"
    return "neither"


def aggregate(rows: list[dict], runs: dict) -> dict:
    deltas = [row["minimum_face_down"]["delta"] for row in rows]
    tactical_ratios = [row["tactical_node_ratio"] for row in rows]
    time_ratios = [row["elapsed_time_ratio"] for row in rows]
    foundation = {name: 0 for name in ("treatment_only", "control_only", "both", "neither")}
    for row in rows:
        foundation[_foundation_outcome(row)] += 1
    coverage = {
        "EMPTY_CREATABLE_expansion_increase": sum(
            row["EMPTY_CREATABLE_expanded"]["treatment"]
            > row["EMPTY_CREATABLE_expanded"]["control"]
            for row in rows
        ),
        "ACTUAL_EMPTY_expansion_increase": sum(
            row["ACTUAL_EMPTY_expanded"]["treatment"]
            > row["ACTUAL_EMPTY_expanded"]["control"]
            for row in rows
        ),
        "productive_descendants_retained_increase": sum(
            row["productive_descendants_retained"]["treatment"]
            > row["productive_descendants_retained"]["control"]
            for row in rows
        ),
        "ordinary_serviced_productive_descendants_increase": sum(
            row["ordinary_serviced_productive_descendants"]["treatment"]
            > row["ordinary_serviced_productive_descendants"]["control"]
            for row in rows
        ),
        "combined_workspace_expansion_increase": sum(
            row["workspace_expansions"]["delta"] > 0 for row in rows
        ),
    }
    ordinary = {
        arm: {
            "total": sum(
                runs[row["panel_entry"]][arm]["workspace"][
                    "productive_descendants_ordinary_serviced"
                ]
                for row in rows
            ),
            "unique_endpoints": len(
                {
                    digest
                    for row in rows
                    for digest in runs[row["panel_entry"]][arm]["workspace"][
                        "ordinary_serviced_endpoint_digests"
                    ]
                }
            ),
            "deals_with_at_least_one": sum(
                runs[row["panel_entry"]][arm]["workspace"][
                    "productive_descendants_ordinary_serviced"
                ]
                > 0
                for row in rows
            ),
        }
        for arm in ARMS
    }
    return {
        "completed_pairs": len(rows),
        "workspace_service_coverage": coverage,
        "ordinary_serviced_productive_descendants": ordinary,
        "non_calibration_treatment_deals_with_ordinary_serviced_productive_descendants": sum(
            row["panel_entry"] != "P0"
            and runs[row["panel_entry"]]["WORKSPACE_SERVICE_1"]["workspace"][
                "productive_descendants_ordinary_serviced"
            ]
            > 0
            for row in rows
        ),
        "face_down": {
            "improve": sum(delta < 0 for delta in deltas),
            "tie": sum(delta == 0 for delta in deltas),
            "worsen": sum(delta > 0 for delta in deltas),
            "median_paired_delta": statistics.median(deltas) if deltas else None,
        },
        "foundation": foundation,
        "cost": {
            "tactical_node_ratio": {
                "median": statistics.median(tactical_ratios) if tactical_ratios else None,
                "min": min(tactical_ratios) if tactical_ratios else None,
                "max": max(tactical_ratios) if tactical_ratios else None,
                "treatment_cheaper": sum(value < 1 for value in tactical_ratios),
                "treatment_more_expensive": sum(value > 1 for value in tactical_ratios),
                "ties": sum(value == 1 for value in tactical_ratios),
            },
            "elapsed_time_ratio": {
                "median": statistics.median(time_ratios) if time_ratios else None,
                "min": min(time_ratios) if time_ratios else None,
                "max": max(time_ratios) if time_ratios else None,
                "treatment_cheaper": sum(value < 1 for value in time_ratios),
                "treatment_more_expensive": sum(value > 1 for value in time_ratios),
                "ties": sum(math.isclose(value, 1.0) for value in time_ratios),
            },
        },
        "credit_balance_flagged_deals": [
            row["panel_entry"] for row in rows if row["credit_balance"]["flagged"]
        ],
    }


def calibration_status(runs: dict) -> dict:
    if "P0" not in runs or any(arm not in runs["P0"] for arm in ARMS):
        return {"complete": False, "broadly_reproduced": False}
    control = runs["P0"]["CONTROL"]
    treatment = runs["P0"]["WORKSPACE_SERVICE_1"]
    checks = {
        "control_workspace_expansions_at_most_one": (
            control["EMPTY_CREATABLE"]["expanded"]
            + control["ACTUAL_EMPTY"]["expanded"]
            <= 1
        ),
        "treatment_material_EMPTY_CREATABLE_service": treatment[
            "EMPTY_CREATABLE"
        ]["expanded"]
        >= 5,
        "treatment_expands_ACTUAL_EMPTY": treatment["ACTUAL_EMPTY"]["expanded"] >= 1,
        "bounded_credit_distribution": not _credit_balance(control, treatment)["flagged"],
        "integrity": all(
            not arm["replay_failures"]
            and not arm["corrected_cost_inconsistencies"]
            and arm["frontier"]["duplicate_entries"] == 0
            for arm in (control, treatment)
        ),
    }
    return {"complete": True, "checks": checks, "broadly_reproduced": all(checks.values())}


def classify(rows: list[dict], runs: dict, summary: dict, calibration: dict) -> str:
    if len(rows) != 10:
        return "WORKSPACE_SERVICE_PANEL_INCONCLUSIVE"
    integrity = all(
        not arm["replay_failures"]
        and not arm["corrected_cost_inconsistencies"]
        and arm["frontier"]["duplicate_entries"] == 0
        and arm["resource_planner_calls"] == 0
        for panel_runs in runs.values()
        for arm in panel_runs.values()
    )
    if not integrity or not calibration.get("broadly_reproduced"):
        return "WORKSPACE_SERVICE_PANEL_INCONCLUSIVE"
    service_deals = summary["workspace_service_coverage"][
        "combined_workspace_expansion_increase"
    ]
    non_calibration_ordinary = summary[
        "non_calibration_treatment_deals_with_ordinary_serviced_productive_descendants"
    ]
    systematic_tradeoff = (
        summary["face_down"]["worsen"] >= 6
        and summary["face_down"]["median_paired_delta"] > 0
    ) or len(summary["credit_balance_flagged_deals"]) >= 3
    if service_deals >= 6 and systematic_tradeoff:
        return "WORKSPACE_SERVICE_GENERALISES_WITH_PROGRESS_TRADEOFF"
    if service_deals >= 6 and non_calibration_ordinary >= 2:
        return "WORKSPACE_SERVICE_GENERALISES"
    non_calibration_service = sum(
        row["panel_entry"] != "P0" and row["workspace_expansions"]["delta"] > 0
        for row in rows
    )
    if rows[0]["workspace_expansions"]["delta"] > 0 and non_calibration_service <= 2:
        return "WORKSPACE_SERVICE_BENCHMARK_SPECIFIC"
    return "WORKSPACE_SERVICE_NOISY_OR_MIXED"


def build_result(definition: dict, runs: dict) -> dict:
    rows = paired_rows(definition, runs)
    summary = aggregate(rows, runs)
    calibration = calibration_status(runs)
    gates = {
        "all_twenty_runs_complete": len(rows) == 10,
        "identical_arm_initial_states": True,
        "alternating_run_order_observed": all(
            entry["run_order"] == list(panel.arm_order(index))
            for index, entry in enumerate(definition["entries"])
        ),
        "fixed_workspace_interval": CONFIG["workspace_service_interval"]
        == service.SERVICE_INTERVAL
        == 8,
        "all_forced_intervals_respected": all(
            arm["workspace"]["minimum_forced_interval_respected"]
            for panel_runs in runs.values()
            for arm in panel_runs.values()
        ),
        "frontier_capacity_preserved": all(
            arm["frontier"]["size"] <= CONFIG["max_frontier_size"]
            for panel_runs in runs.values()
            for arm in panel_runs.values()
        ),
        "no_lane_duplicates": all(
            arm["workspace"]["lane_duplicate_entries_introduced"] == 0
            for panel_runs in runs.values()
            for arm in panel_runs.values()
        ),
        "integrity": all(
            not arm["replay_failures"]
            and not arm["corrected_cost_inconsistencies"]
            and arm["independent_replay_false"] == 0
            for panel_runs in runs.values()
            for arm in panel_runs.values()
        ),
        "resource_planner_not_invoked": all(
            arm["resource_planner_calls"] == 0
            for panel_runs in runs.values()
            for arm in panel_runs.values()
        ),
    }
    return {
        "experiment": EXPERIMENT_ID,
        "base_sha": BASE_SHA,
        "panel_id": definition["panel_id"],
        "panel_definition_path": panel.PANEL_PATH.relative_to(ROOT).as_posix(),
        "config": CONFIG,
        "run_schedule": {
            entry["panel_entry"]: entry["run_order"] for entry in definition["entries"]
        },
        "runs": runs,
        "paired_results": rows,
        "aggregate": summary,
        "calibration": calibration,
        "gates": gates,
        "verdict": classify(rows, runs, summary, calibration),
        "completed_utc": utc_now(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stop-after-pairs",
        type=int,
        default=None,
        help="runtime-discipline checkpoint stop; final verdict still requires all ten pairs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    definition = panel_definition()
    runs = execute_missing_runs(definition, stop_after_pairs=args.stop_after_pairs)
    result = build_result(definition, runs)
    _write_json_atomic(RESULT_PATH, result)
    print(
        f"VERDICT {result['verdict']} pairs={result['aggregate']['completed_pairs']}",
        flush=True,
    )
    print(f"WROTE {RESULT_PATH}", flush=True)
    return 0 if all(result["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
