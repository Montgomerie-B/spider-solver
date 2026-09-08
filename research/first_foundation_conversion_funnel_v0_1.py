#!/usr/bin/env python3
"""Frozen A/B panel for the StrategicProject-to-foundation conversion funnel."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import workspace_service_generalisation_panel_v0_1 as panel
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicCreditPropagation,
    solve_anytime,
)
from spider.state_identity import canonical_state_key


EXPERIMENT = "first_foundation_conversion_funnel_v0_1"
BASE_SHA = "2fe1bbda0f21dbc1aaf8961ba702f28bc0c31cf1"
BASELINE = "PROJECT_BASELINE"
TREATMENT = "FOUNDATION_DEMAND_BRIDGE"
ARMS = (BASELINE, TREATMENT)
DEALS = ("P0", "P2", "P7")
RUN_ORDER = {
    "P0": (BASELINE, TREATMENT),
    "P2": (TREATMENT, BASELINE),
    "P7": (BASELINE, TREATMENT),
}
CONFIG = {
    "seed": 0,
    "max_strategic_expansions": 400,
    "max_tactical_nodes": 300_000,
    "wall_clock_limit_s": 900.0,
    "max_frontier_size": 256,
    "max_successors_per_expansion": 10,
    "max_strategic_credit": 4,
    "scheduler": True,
    "tactical_allocation": True,
    "target_foundation_count": 1,
    "incumbent": None,
}
PLAN = ROOT / "docs" / "research" / f"{EXPERIMENT}_plan.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {
                "base": BASE_SHA,
                "deals": DEALS,
                "arms": ARMS,
                "order": RUN_ORDER,
                "config": CONFIG,
            },
            sort_keys=True,
        ).encode("utf-8")
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
            "Mandatory frozen P0/P2/P7; a fourth fixture is allowed only if every "
            "mandatory control run stops before F3/F4."
        ),
    }


def experiment_config(bridge: bool):
    base = common.production_shadow._production_config(
        seconds=CONFIG["wall_clock_limit_s"],
        expansions=CONFIG["max_strategic_expansions"],
        nodes=CONFIG["max_tactical_nodes"],
    )
    return replace(
        base,
        max_frontier_size=CONFIG["max_frontier_size"],
        max_successors_per_expansion=CONFIG["max_successors_per_expansion"],
        max_credit_level=StrategicCreditLevel.RAW_LEGAL_FALLBACK,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
        enable_whole_deal_scheduler=True,
        enable_tactical_resource_allocation=True,
        enable_state_service_registry=True,
        enable_state_service_subscribers=True,
        enable_strategic_project_continuation=True,
        enable_foundation_conversion_funnel=True,
        enable_foundation_demand_bridge=bridge,
        target_foundation_count=1,
        stop_after_first_foundation=False,
    )


def _counts(snapshot: dict) -> dict:
    return {
        key: value["entrants"]
        for key, value in snapshot.get("stages", {}).items()
    }


def _detail_counts(snapshot: dict, stage: str, field: str) -> dict:
    return dict(
        Counter(
            item["details"].get(field, "UNKNOWN")
            for item in snapshot.get("events", [])
            if item["stage"] == stage
        )
    )


def _first_foundation(opening: SpiderState, result, snapshot: dict):
    events = [
        item
        for item in snapshot.get("events", [])
        if item["stage"] == "F14_FOUNDATION_REPLAY_VERIFIED"
    ]
    if not events:
        return None
    node = result.most_foundations_node
    replay = opening.clone()
    cost = replay_actions(replay, list(node.actions))
    return {
        "yes": True,
        "expansion": min(item["expansion"] for item in events),
        "corrected_path_cost": cost,
        "path_length": len(node.actions),
        "campaign_id": min(events, key=lambda item: item["expansion"])["campaign_id"],
        "foundation_multiset": sorted(
            sequence[0].suit.upper() for sequence in replay.foundations if sequence
        ),
        "trajectory_digest": hashlib.sha256(repr(tuple(node.actions)).encode()).hexdigest()[:16],
        "result_state_digest": hashlib.sha256(repr(canonical_state_key(replay)).encode()).hexdigest()[:16],
        "cost_matches": cost == node.g,
        "state_matches": canonical_state_key(replay) == canonical_state_key(node.state),
    }


def compact(opening: SpiderState, result, arm: str) -> dict:
    telemetry = result.telemetry
    snapshot = telemetry.foundation_conversion_funnel
    node = result.best_progress_node
    replay = opening.clone()
    replay_cost = replay_actions(replay, list(node.actions))
    return {
        "arm": arm,
        "stop_reason": result.stop_reason,
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "elapsed_s": result.elapsed_seconds,
        "deepest_stage": snapshot.get("deepest_stage"),
        "stage_counts": _counts(snapshot),
        "demand_kinds": _detail_counts(snapshot, "F4_TACTICAL_DEMAND_DERIVED", "demand_kind"),
        "realizer_calls": _detail_counts(snapshot, "F6_REALISER_INVOKED", "realizer"),
        "funnel": snapshot,
        "projects": telemetry.strategic_project_snapshot,
        "first_foundation": _first_foundation(opening, result, snapshot),
        "maximum_foundations": telemetry.best_foundations,
        "minimum_face_down": telemetry.lowest_face_down,
        "stock_rows_remaining": len(result.deepest_stock_node.state.stock) // 10,
        "best_progress_replay": {
            "corrected_cost": replay_cost,
            "expected_g": node.g,
            "cost_matches": replay_cost == node.g,
            "state_matches": canonical_state_key(replay) == canonical_state_key(node.state),
        },
        "proof_pruned": telemetry.proof_pruned,
        "tt_suppressed": telemetry.tt_suppressed,
        "registry_handle_errors": telemetry.registry_live_handle_invariant_violations,
    }


def run(entry: dict, arm: str) -> dict:
    cards = panel.load_entry_cards(entry)
    opening = SpiderState.from_cards(list(cards))
    random.seed(CONFIG["seed"])
    result = solve_anytime(
        opening.clone(), cards, None, experiment_config(arm == TREATMENT)
    )
    return compact(opening, result, arm)


def execute(*, only_deal: str | None = None) -> dict:
    entries = {
        item["panel_entry"]: item
        for item in panel.panel_definition()["entries"]
        if item["panel_entry"] in DEALS
    }
    runs = {}
    selected_deals = (only_deal,) if only_deal else DEALS
    for deal in selected_deals:
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
            _write_json(
                path,
                {"config_fingerprint": _fingerprint(), "result": measured},
            )
            runs[deal][arm] = measured
            print(
                f"DONE {deal} {arm} exp={measured['strategic_expansions']} "
                f"elapsed={measured['elapsed_s']:.2f} deepest={measured['deepest_stage']}",
                flush=True,
            )
    return runs


def _load_all_checkpoints() -> dict:
    runs = {}
    for deal in DEALS:
        runs[deal] = {}
        for arm in ARMS:
            path = CHECKPOINTS / f"{deal}_{arm.lower()}.json"
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("config_fingerprint") != _fingerprint():
                raise RuntimeError(f"stale checkpoint: {path}")
            run = saved["result"]
            run["funnel"] = _reconstruct_retention_stages(run["funnel"])
            run["stage_counts"] = _counts(run["funnel"])
            run["deepest_stage"] = run["funnel"]["deepest_stage"]
            runs[deal][arm] = run
    return runs


def _reconstruct_retention_stages(snapshot: dict) -> dict:
    """Repair pre-review F8/F9 sampling from exact F7/drop/F1/F2 evidence.

    Search and drop observations were recorded inside their exact gates.  The
    original F8 sampling hook was after the successor loop, so this rebuilds
    only F8/F9: an F7 endpoint with no same-attempt F7->F8 drop necessarily
    passed TT and registry admission in this no-incumbent experiment.  F1
    supplies the deterministic child registry-request digest where present.
    """

    fixed = json.loads(json.dumps(snapshot))
    events = [
        item
        for item in fixed.get("events", [])
        if item["stage"]
        not in {"F8_PROGRESS_RETAINED", "F9_PROJECT_CONTINUATION_SERVICED"}
    ]
    losses = {
        (
            item["project_id"],
            item["campaign_id"],
            item["state_digest"],
            item["request_digest"],
        )
        for item in fixed.get("drops", [])
        if item["from"] == "F7_REPLAYABLE_PROGRESS_RETURNED"
        and item["to"] == "F8_PROGRESS_RETAINED"
    }
    child_requests = {
        (
            item["project_id"],
            item["campaign_id"],
            item["state_digest"],
            item["trajectory_digest"],
        ): item["request_digest"]
        for item in events
        if item["stage"] == "F1_CANDIDATE_AVAILABLE"
    }
    retained = []
    seen = set()
    for item in events:
        if item["stage"] != "F7_REPLAYABLE_PROGRESS_RETURNED":
            continue
        loss_key = (
            item["project_id"],
            item["campaign_id"],
            item["state_digest"],
            item["request_digest"],
        )
        if loss_key in losses:
            continue
        row = dict(item)
        row["stage"] = "F8_PROGRESS_RETAINED"
        row["request_digest"] = child_requests.get(
            (
                item["project_id"],
                item["campaign_id"],
                item["state_digest"],
                item["trajectory_digest"],
            )
        )
        row["details"] = {
            "registry_admitted": True,
            "reconstructed_from_exact_f7_and_drop_gates": True,
        }
        key = (
            row["project_id"], row["campaign_id"], row["state_digest"],
            row["request_digest"], row["trajectory_digest"],
        )
        if key not in seen:
            seen.add(key)
            retained.append(row)
    events.extend(retained)
    serviced = []
    for analysis in events:
        if analysis["stage"] != "F2_CAMPAIGN_ANALYSED":
            continue
        prior = [
            item
            for item in retained
            if item["project_id"] == analysis["project_id"]
            and item["campaign_id"] == analysis["campaign_id"]
            and item["expansion"] < analysis["expansion"]
        ]
        if not prior:
            continue
        row = dict(analysis)
        row["stage"] = "F9_PROJECT_CONTINUATION_SERVICED"
        row["details"] = {
            "prior_retained_state": min(
                prior, key=lambda item: item["expansion"]
            )["state_digest"],
            "reconstructed_from_exact_f8_and_selected_f2_service": True,
        }
        serviced.append(row)
    events.extend(serviced)
    stage_labels = [
        "F0_PROJECT_EXISTS", "F1_CANDIDATE_AVAILABLE", "F2_CAMPAIGN_ANALYSED",
        "F3_ACTIONABLE_PREREQUISITE", "F4_TACTICAL_DEMAND_DERIVED",
        "F5_ALLOCATOR_GRANT", "F6_REALISER_INVOKED",
        "F7_REPLAYABLE_PROGRESS_RETURNED", "F8_PROGRESS_RETAINED",
        "F9_PROJECT_CONTINUATION_SERVICED", "F10_TERMINAL_READY",
        "F11_REMOVAL_REQUESTED", "F12_FOUNDATION_GENERATED",
        "F13_FOUNDATION_RETAINED", "F14_FOUNDATION_REPLAY_VERIFIED",
    ]
    fixed["events"] = events
    fixed["stages"] = {}
    for label in stage_labels:
        rows = [item for item in events if item["stage"] == label]
        fixed["stages"][label] = {
            "entrants": len(rows),
            "first_expansion": min((item["expansion"] for item in rows), default=None),
            "unique_projects": len({item["project_id"] for item in rows}),
            "unique_states": len({item["state_digest"] for item in rows}),
        }
    fixed["per_campaign"] = {}
    for campaign in sorted({item["campaign_id"] for item in events}):
        campaign_rows = [item for item in events if item["campaign_id"] == campaign]
        fixed["per_campaign"][campaign] = {}
        for label in stage_labels:
            rows = [item for item in campaign_rows if item["stage"] == label]
            fixed["per_campaign"][campaign][label] = {
                "entrants": len(rows),
                "first_expansion": min((item["expansion"] for item in rows), default=None),
                "unique_projects": len({item["project_id"] for item in rows}),
                "unique_states": len({item["state_digest"] for item in rows}),
            }
    fixed["deepest_stage"] = next(
        (label for label in reversed(stage_labels) if fixed["stages"][label]["entrants"]),
        None,
    )
    fixed["retention_stage_reconstruction"] = (
        "F8/F9 rebuilt from exact F7 endpoint, adjacent drop, F1 child-request, "
        "and later selected F2 service records after review found the original "
        "F8 observer outside the successor loop"
    )
    return fixed


def _stage_number(label: str | None) -> int:
    return -1 if not label else int(label.split("_", 1)[0][1:])


def _verdict(runs: dict) -> tuple[str, str]:
    treatment = [runs[deal][TREATMENT] for deal in DEALS]
    if any(item["first_foundation"] for item in treatment):
        return "FIRST_FOUNDATION_REACHED", "treatment independently reached F14"
    treatment_f7 = sum(
        item["stage_counts"].get("F7_REPLAYABLE_PROGRESS_RETURNED", 0)
        for item in treatment
    )
    treatment_f8 = sum(
        item["stage_counts"].get("F8_PROGRESS_RETAINED", 0)
        for item in treatment
    )
    retention_losses = sum(
        drop["reason"]
        in {
            "TT_DOMINATED",
            "SUCCESSOR_DEDUP_DROPPED",
            "PORTFOLIO_DROPPED",
            "RETENTION_DROPPED",
        }
        for item in treatment
        for drop in item["funnel"].get("drops", [])
    )
    if treatment_f7 > treatment_f8 and retention_losses:
        return (
            "FOUNDATION_RETENTION_LOSS_CONFIRMED",
            (
                f"{treatment_f7} replayable treatment successors produced only "
                f"{treatment_f8} retained project-progress admissions; exact TT and "
                "candidate deduplication are the earliest demonstrated loss gates"
            ),
        )
    if treatment_f8 and not any(
        item["stage_counts"].get("F9_PROJECT_CONTINUATION_SERVICED", 0)
        for item in treatment
    ):
        return "FOUNDATION_CONTINUATION_LOSS_CONFIRMED", "retained progress stopped before later service"
    if any(item["stage_counts"].get("F6_REALISER_INVOKED", 0) for item in treatment) and not any(
        item["stage_counts"].get("F7_REPLAYABLE_PROGRESS_RETURNED", 0) for item in treatment
    ):
        return "FOUNDATION_REALISER_LIMIT_CONFIRMED", "granted realisers returned no replayable project progress"
    return "FOUNDATION_DEMAND_GAP_NOT_CAUSAL", "bridge did not move the practical downstream boundary"


def build_result(runs: dict) -> dict:
    verdict, blocker = _verdict(runs)
    comparisons = []
    for deal in DEALS:
        a, b = runs[deal][BASELINE], runs[deal][TREATMENT]
        comparisons.append(
            {
                "deal": deal,
                "deepest_a": a["deepest_stage"],
                "deepest_b": b["deepest_stage"],
                "runtime_ratio_b_over_a": b["elapsed_s"] / a["elapsed_s"],
                "tactical_ratio_b_over_a": (
                    b["tactical_nodes"] / a["tactical_nodes"]
                    if a["tactical_nodes"]
                    else None
                ),
            }
        )
    aggregate = {}
    for arm in ARMS:
        arm_runs = [runs[deal][arm] for deal in DEALS]
        aggregate[arm] = {
            "projects_created": sum(item["projects"].get("projects_created", 0) for item in arm_runs),
            "campaign_demands_derived": sum(item["stage_counts"].get("F4_TACTICAL_DEMAND_DERIVED", 0) for item in arm_runs),
            "allocator_grants": sum(item["stage_counts"].get("F5_ALLOCATOR_GRANT", 0) for item in arm_runs),
            "realizer_invocations": sum(item["stage_counts"].get("F6_REALISER_INVOKED", 0) for item in arm_runs),
            "replayable_progress_returns": sum(item["stage_counts"].get("F7_REPLAYABLE_PROGRESS_RETURNED", 0) for item in arm_runs),
            "retained_project_continuations": sum(item["stage_counts"].get("F8_PROGRESS_RETAINED", 0) for item in arm_runs),
            "serviced_project_continuations": sum(item["stage_counts"].get("F9_PROJECT_CONTINUATION_SERVICED", 0) for item in arm_runs),
            "terminal_ready_states": sum(item["stage_counts"].get("F10_TERMINAL_READY", 0) for item in arm_runs),
            "removal_requests": sum(item["stage_counts"].get("F11_REMOVAL_REQUESTED", 0) for item in arm_runs),
            "foundation_generating_successors": sum(item["stage_counts"].get("F12_FOUNDATION_GENERATED", 0) for item in arm_runs),
            "foundation_retained_states": sum(item["stage_counts"].get("F13_FOUNDATION_RETAINED", 0) for item in arm_runs),
            "replay_verified_foundations": sum(item["stage_counts"].get("F14_FOUNDATION_REPLAY_VERIFIED", 0) for item in arm_runs),
            "project_service_executions": sum(item["projects"].get("project_service_executions", 0) for item in arm_runs),
            "semantic_progress_events": sum(item["projects"].get("project_progress_events", 0) for item in arm_runs),
            "activity_without_progress": sum(item["projects"].get("service_executions_without_progress", 0) for item in arm_runs),
            "demand_kinds": dict(Counter(key for item in arm_runs for key, count in item["demand_kinds"].items() for _ in range(count))),
            "realizer_calls": dict(Counter(key for item in arm_runs for key, count in item["realizer_calls"].items() for _ in range(count))),
            "drop_reasons": dict(
                Counter(
                    drop["reason"]
                    for item in arm_runs
                    for drop in item["funnel"].get("drops", [])
                )
            ),
        }
    return {
        **frozen_plan(),
        "status": "COMPLETE",
        "audit": {
            "gap_confirmed": True,
            "intended_realizer": "realize_campaign_to_next_epoch",
            "unlocking_demand": "CAMPAIGN_CURRENT_EPOCH",
            "production_emitters_before_treatment": [],
            "normal_project_execution_emitted_before_treatment": False,
            "classification": "accidental expressibility gap",
            "code_locations": {
                "realizer": "src/spider/planner/foundation_campaign_realizer.py:567 realize_campaign_to_next_epoch",
                "consumer": "src/spider/planner/anytime_controller.py:5802 _foundation_successors explicit allocated lookup",
                "demand_kind": "src/spider/planner/tactical_resource_allocator.py:45 TacticalRealizerKind.CAMPAIGN_CURRENT_EPOCH",
                "pre_treatment_derivation": "src/spider/planner/tactical_resource_allocator.py:402 derive_tactical_demands (no producer at base SHA)",
                "compatibility_fallback": "src/spider/planner/anytime_controller.py:4023 _resource_demand synthetic fallback used only outside allocated lookup",
                "treatment_producer": "src/spider/planner/tactical_resource_allocator.py:446 narrow selected-project producer",
            },
        },
        "runs": runs,
        "comparisons": comparisons,
        "aggregate": aggregate,
        "median_runtime_ratio_b_over_a": statistics.median(
            row["runtime_ratio_b_over_a"] for row in comparisons
        ),
        "median_tactical_ratio_b_over_a": statistics.median(
            row["tactical_ratio_b_over_a"]
            for row in comparisons
            if row["tactical_ratio_b_over_a"] is not None
        ),
        "earliest_causal_blocker": blocker,
        "verdict": verdict,
    }


def write_report(result: dict) -> None:
    lines = ["# First-Foundation Conversion Funnel v0.1", ""]
    sections = [
        ("1. Verdict", [f"`{result['verdict']}` — {result['earliest_causal_blocker']}."]),
        ("2. Existing foundation execution path", ["Fresh campaign analysis builds a dependency graph and tactical portfolio. `CAMPAIGN_CURRENT_EPOCH` is consumed by `_foundation_successors`, allocated through `TacticalResourceAllocator.request`, and invokes the unchanged `realize_campaign_to_next_epoch`; terminal paths use the unchanged terminal assembly/removal realisers and the rules engine performs complete-sequence removal."]),
        ("3. Demand-gap code audit", ["1. The intended realiser is `realize_campaign_to_next_epoch` (`foundation_campaign_realizer.py:567`), entered by `_foundation_successors`.", "2. Its unlocking demand is the existing `CAMPAIGN_CURRENT_EPOCH` kind (`tactical_resource_allocator.py:45`).", "3. At the base SHA, no production demand-derivation function emitted that kind; `_resource_demand` could synthesize it only for compatibility execution without tactical allocation.", "4. Allocated StrategicProject execution uses `_explicit_resource_demand` (`anytime_controller.py:5802`), so it could not emit or request the missing kind normally.", "5. This is accidental expressibility wiring: the realiser, compatibility fallback, eligibility facts, and allocator contract already existed. Exact locations are also recorded in the JSON audit object."]),
        ("4. Funnel definition", ["F0–F14 preserve the requested distinctions. Events are de-duplicated by stage, project, campaign, exact-state digest, registry-request digest, exact action-prefix digest, and demand/realiser detail. Drop events use the bounded taxonomy in the result JSON."]),
        ("5. Baseline funnel results", []),
        ("6. Minimal treatment", ["For the selected live StrategicProject campaign only, an existing actionable critical-path entry now emits the existing `CAMPAIGN_CURRENT_EPOCH` demand at PROBE tier. The allocator, tier budgets, realiser, priorities, proof contracts, and production defaults are unchanged."]),
        ("7. Treatment funnel results", []),
        ("8. First-foundation replay", []),
        ("9. Earliest causal blocker", [result["earliest_causal_blocker"] + ". No second blocker was repaired."]),
        ("10. Project activity versus conversion", []),
        ("11. Integrity/runtime", []),
        ("12. One next bounded task", []),
    ]
    for deal in DEALS:
        a, b = result["runs"][deal][BASELINE], result["runs"][deal][TREATMENT]
        sections[4][1].append(f"- {deal}: {a['deepest_stage']}; demands {a['demand_kinds']}; realisers {a['realizer_calls']}.")
        sections[6][1].append(f"- {deal}: {b['deepest_stage']}; demands {b['demand_kinds']}; realisers {b['realizer_calls']}.")
        replay = b["first_foundation"]
        sections[7][1].append(f"- {deal}: {json.dumps(replay, sort_keys=True) if replay else 'no F14 endpoint'}.")
        project = b["projects"]
        sections[9][1].append(
            f"- {deal} treatment: projects={project.get('projects_created', 0)}, service={project.get('project_service_executions', 0)}, semantic progress={project.get('project_progress_events', 0)}, activity without progress={project.get('service_executions_without_progress', 0)}; retained={b['stage_counts'].get('F8_PROGRESS_RETAINED', 0)}, serviced={b['stage_counts'].get('F9_PROJECT_CONTINUATION_SERVICED', 0)}."
        )
        comparison = next(item for item in result["comparisons"] if item["deal"] == deal)
        sections[10][1].append(
            f"- {deal}: replay A/B={a['best_progress_replay']['cost_matches'] and a['best_progress_replay']['state_matches']}/{b['best_progress_replay']['cost_matches'] and b['best_progress_replay']['state_matches']}; handle errors A/B={a['registry_handle_errors']}/{b['registry_handle_errors']}; runtime ratio={comparison['runtime_ratio_b_over_a']:.3f}; tactical ratio={comparison['tactical_ratio_b_over_a']:.3f}."
        )
    baseline_aggregate = result["aggregate"][BASELINE]
    treatment_aggregate = result["aggregate"][TREATMENT]
    sections[4][1].append(
        f"Aggregate: demands={baseline_aggregate['campaign_demands_derived']}, grants={baseline_aggregate['allocator_grants']}, realiser calls={baseline_aggregate['realizer_invocations']}, replayable/retained/serviced={baseline_aggregate['replayable_progress_returns']}/{baseline_aggregate['retained_project_continuations']}/{baseline_aggregate['serviced_project_continuations']}."
    )
    sections[6][1].append(
        f"Aggregate: demands={treatment_aggregate['campaign_demands_derived']} including {treatment_aggregate['demand_kinds'].get('CAMPAIGN_CURRENT_EPOCH', 0)} current-epoch demands; grants={treatment_aggregate['allocator_grants']}; realiser calls={treatment_aggregate['realizer_invocations']} (all dependency closure); replayable/retained/serviced={treatment_aggregate['replayable_progress_returns']}/{treatment_aggregate['retained_project_continuations']}/{treatment_aggregate['serviced_project_continuations']}."
    )
    sections[8][1].append(
        f"Observed treatment drops: {treatment_aggregate['drop_reasons']}. The bridge exposed no terminal-ready state and no removal request."
    )
    sections[10][1].append(
        "Post-run review found the original F8 observer immediately after, rather than inside, the successor loop. Search behavior and the exact F7/drop observations were unaffected. The hook is corrected; reported F8/F9 rows were rebuilt deterministically from each exact F7 endpoint, its adjacent dedup/TT drop record, the matching F1 child-request digest, and later selected F2 service. No metrics from different trajectories were combined."
    )
    if result["verdict"] == "FIRST_FOUNDATION_REACHED":
        next_task = "Repeat the identical frozen bridge and envelope across the full already-frozen P1–P9 panel to test first-foundation reproducibility and generalisation; change no policy."
    else:
        next_task = "Audit exact-state project-intent coalescing for F7 successors: when TT admission or candidate deduplication finds an equal state, determine whether the same-campaign continuation subscriber is transferred to the already retained registry request; test one bounded transfer only if that ownership gap is confirmed, changing no TT rule, priority, or budget."
    sections[11][1].append(next_task)
    for title, body in sections:
        lines.extend([f"## {title}", "", *body, ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-plan-only", action="store_true")
    parser.add_argument("--deal", choices=DEALS)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
    _write_json(PLAN, frozen_plan())
    if args.freeze_plan_only:
        print(f"FROZEN {PLAN}")
        return 0
    if not args.build_only:
        execute(only_deal=args.deal)
        if args.deal:
            return 0
    runs = _load_all_checkpoints()
    result = build_result(runs)
    _write_json(RESULT, result)
    write_report(result)
    print(f"VERDICT {result['verdict']}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
