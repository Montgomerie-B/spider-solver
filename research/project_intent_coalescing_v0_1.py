#!/usr/bin/env python3
"""Frozen A/B panel for exact-state project-intent coalescing."""

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
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditLevel,
    StrategicCreditPropagation,
    solve_anytime,
)
from spider.state_identity import canonical_state_key


EXPERIMENT = "project_intent_coalescing_v0_1"
BASE_SHA = "d4868ce06ad131623dc8853967ffd1e74234bfa8"
BASELINE = "CURRENT_FUNNEL"
TREATMENT = "PROJECT_INTENT_COALESCING"
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
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
FUNNEL_PLAN = ROOT / "docs" / "research" / "first_foundation_conversion_funnel_v0_1_plan.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _fingerprint() -> str:
    return hashlib.sha256(
        json.dumps(
            {"base": BASE_SHA, "deals": DEALS, "arms": ARMS, "order": RUN_ORDER, "config": CONFIG},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def experiment_config(coalesce: bool):
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
        enable_foundation_demand_bridge=True,
        enable_project_intent_coalescing=coalesce,
        target_foundation_count=1,
        stop_after_first_foundation=True,
    )


def _counts(snapshot: dict) -> dict:
    return {key: value["entrants"] for key, value in snapshot.get("stages", {}).items()}


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
        "trajectory_digest": hashlib.sha256(repr(tuple(node.actions)).encode()).hexdigest()[:16],
        "cost_matches": cost == node.g,
        "state_matches": canonical_state_key(replay) == canonical_state_key(node.state),
    }


def _later_serviced(snapshot: dict, intent: dict) -> int:
    coalesced = [
        item
        for item in snapshot.get("events", [])
        if item["stage"] == "F1_CANDIDATE_AVAILABLE"
        and item.get("details", {}).get("coalesced_onto_canonical")
    ]
    serviced = 0
    for row in coalesced:
        later = [
            item
            for item in snapshot.get("events", [])
            if item["stage"] in {
                "F2_CAMPAIGN_ANALYSED",
                "F9_PROJECT_CONTINUATION_SERVICED",
            }
            and item["project_id"] == row["project_id"]
            and item["campaign_id"] == row["campaign_id"]
            and item.get("request_digest") == row.get("request_digest")
            and item["expansion"] > row["expansion"]
        ]
        if later:
            serviced += 1
    return serviced


def compact(opening: SpiderState, result, arm: str) -> dict:
    telemetry = result.telemetry
    snapshot = telemetry.foundation_conversion_funnel
    node = result.best_progress_node
    replay = opening.clone()
    replay_cost = replay_actions(replay, list(node.actions))
    intent = telemetry.project_intent_coalescing or {}
    return {
        "arm": arm,
        "stop_reason": result.stop_reason,
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "elapsed_s": result.elapsed_seconds,
        "deepest_stage": snapshot.get("deepest_stage"),
        "stage_counts": _counts(snapshot),
        "funnel": snapshot,
        "projects": telemetry.strategic_project_snapshot,
        "intent": intent,
        "recovered_later_serviced": _later_serviced(snapshot, intent),
        "first_foundation": _first_foundation(opening, result, snapshot),
        "maximum_foundations": telemetry.best_foundations,
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


def load_entry(entry: dict) -> tuple:
    cards = tuple(load_deal(ROOT / entry["fixture_path"]))
    opening = SpiderState.from_cards(list(cards))
    digest = hashlib.sha256(repr(canonical_state_key(opening)).encode()).hexdigest()[:16]
    if digest != entry["opening_digest"]:
        raise RuntimeError(f"opening digest mismatch: {digest} != {entry['opening_digest']}")
    return cards, opening


def run(entry: dict, arm: str) -> dict:
    cards, opening = load_entry(entry)
    random.seed(CONFIG["seed"])
    result = solve_anytime(
        opening.clone(), cards, None, experiment_config(arm == TREATMENT)
    )
    return compact(opening, result, arm)


def execute(*, only_deal: str | None = None) -> dict:
    fixtures = json.loads(FUNNEL_PLAN.read_text(encoding="utf-8"))["fixtures"]
    entries = {deal: fixtures[deal] for deal in DEALS}
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
            _write_json(path, {"config_fingerprint": _fingerprint(), "result": measured})
            runs[deal][arm] = measured
            print(
                f"DONE {deal} {arm} exp={measured['strategic_expansions']} "
                f"elapsed={measured['elapsed_s']:.2f} deepest={measured['deepest_stage']}",
                flush=True,
            )
            if measured.get("first_foundation"):
                print("STOP first foundation reached", flush=True)
                return runs
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
            runs[deal][arm] = saved["result"]
    return runs


def _class_sum(runs: dict, arm: str, name: str) -> int:
    return sum(
        runs[deal][arm].get("intent", {}).get("class_counts", {}).get(name, 0)
        for deal in DEALS
        if arm in runs[deal]
    )


def _verdict(runs: dict) -> tuple[str, str]:
    treatment = [runs[deal][TREATMENT] for deal in DEALS if TREATMENT in runs[deal]]
    baseline = [runs[deal][BASELINE] for deal in DEALS if BASELINE in runs[deal]]
    if any(item.get("first_foundation") for item in treatment + baseline):
        headline = "FIRST_FOUNDATION_REACHED"
    else:
        headline = None
    transferable = _class_sum(runs, BASELINE, "TRANSFERABLE_PROJECT_INTENT_LOST")
    already = _class_sum(runs, BASELINE, "STATE_ALREADY_HAS_PROJECT_INTENT")
    context = _class_sum(runs, BASELINE, "NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS")
    true_loss = _class_sum(runs, BASELINE, "TRUE_RETENTION_LOSS")
    recovered = sum(item.get("intent", {}).get("recovered_candidates", 0) for item in treatment)
    later = sum(_later_serviced(item.get("funnel") or {}, item.get("intent") or {}) for item in treatment)
    deepest_gain = any(
        (runs[deal][TREATMENT]["deepest_stage"] or "")
        > (runs[deal][BASELINE]["deepest_stage"] or "")
        for deal in DEALS
        if BASELINE in runs[deal] and TREATMENT in runs[deal]
    )
    if transferable == 0 and already and not true_loss:
        verdict = "PROJECT_INTENT_ALREADY_PRESERVED"
        note = "F7 suppressions already had the same StrategicProject on the surviving request"
    elif transferable and recovered == 0:
        verdict = "PROJECT_INTENT_LOSS_CONFIRMED_NOT_SUFFICIENT"
        note = "transferable losses were classified but production transfer attached no candidates"
    elif transferable and recovered:
        foundation_moved = any(
            item["stage_counts"].get("F10_TERMINAL_READY", 0)
            or item["stage_counts"].get("F14_FOUNDATION_REPLAY_VERIFIED", 0)
            for item in treatment
        )
        if foundation_moved and (later or deepest_gain):
            verdict = "PROJECT_INTENT_LOSS_CONFIRMED_AND_REPAIRED"
            note = f"{recovered} project candidates recovered onto surviving canonical requests"
        else:
            verdict = "PROJECT_INTENT_LOSS_CONFIRMED_NOT_SUFFICIENT"
            note = (
                f"{transferable} transferable F7 losses; {recovered} recovered candidates "
                f"({later} later serviced on the same request). Funnel depth did not advance "
                "and no foundation was generated. Do not fix the next blocker in this task."
            )
    elif context and not transferable:
        verdict = "PROGRESS_IS_CONTEXT_NONTRANSFERABLE"
        note = "suppressed F7 progress was provenance-only and failed fresh campaign checks"
    elif true_loss and not transferable:
        verdict = "TRUE_FOUNDATION_RETENTION_LOSS"
        note = "canonical children disappeared rather than being coalesced"
    else:
        verdict = "INCONCLUSIVE"
        note = "F7 anatomy did not isolate a single primary cause"
    if headline:
        return f"{headline}; {verdict}", note
    return verdict, note


def build_result(runs: dict) -> dict:
    verdict, note = _verdict(runs)
    comparisons = []
    for deal in DEALS:
        if BASELINE not in runs[deal] or TREATMENT not in runs[deal]:
            continue
        a, b = runs[deal][BASELINE], runs[deal][TREATMENT]
        comparisons.append(
            {
                "deal": deal,
                "deepest_a": a["deepest_stage"],
                "deepest_b": b["deepest_stage"],
                "runtime_ratio_b_over_a": b["elapsed_s"] / a["elapsed_s"] if a["elapsed_s"] else None,
                "tactical_ratio_b_over_a": (
                    b["tactical_nodes"] / a["tactical_nodes"] if a["tactical_nodes"] else None
                ),
            }
        )
    return {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "status": "COMPLETE",
        "deals": list(DEALS),
        "arms": list(ARMS),
        "run_order": {key: list(value) for key, value in RUN_ORDER.items()},
        "config": CONFIG,
        "config_fingerprint": _fingerprint(),
        "runs": runs,
        "comparisons": comparisons,
        "audit": {
            "baseline_transferable": _class_sum(runs, BASELINE, "TRANSFERABLE_PROJECT_INTENT_LOST"),
            "baseline_already": _class_sum(runs, BASELINE, "STATE_ALREADY_HAS_PROJECT_INTENT"),
            "baseline_nontransferable": _class_sum(
                runs, BASELINE, "NONTRANSFERABLE_CONTEXT_ONLY_PROGRESS"
            ),
            "baseline_true_retention": _class_sum(runs, BASELINE, "TRUE_RETENTION_LOSS"),
            "treatment_recovered": sum(
                runs[deal][TREATMENT].get("intent", {}).get("recovered_candidates", 0)
                for deal in DEALS
                if TREATMENT in runs[deal]
            ),
            "treatment_later_serviced": sum(
                _later_serviced(
                    runs[deal][TREATMENT].get("funnel") or {},
                    runs[deal][TREATMENT].get("intent") or {},
                )
                for deal in DEALS
                if TREATMENT in runs[deal]
            ),
        },
        "median_runtime_ratio_b_over_a": (
            statistics.median(row["runtime_ratio_b_over_a"] for row in comparisons)
            if comparisons
            else None
        ),
        "median_tactical_ratio_b_over_a": (
            statistics.median(
                row["tactical_ratio_b_over_a"]
                for row in comparisons
                if row["tactical_ratio_b_over_a"] is not None
            )
            if comparisons
            else None
        ),
        "verdict": verdict,
        "earliest_causal_blocker": note,
    }


def write_report(result: dict) -> None:
    lines = [
        "# Exact-State Project Intent Coalescing v0.1",
        "",
        "## 1. Verdict",
        "",
        f"`{result['verdict']}` — {result['earliest_causal_blocker']}.",
        "",
        "## 2. Existing F7 loss anatomy",
        "",
        "Natural F7 replayable campaign-progress successors from the previous funnel and this panel are classified at the exact TT and same-expansion child-dedup gates. Exact TT dominance is unchanged.",
        "",
        "## 3. TT loss classification",
        "",
        f"Baseline transferable={result['audit']['baseline_transferable']}; already represented={result['audit']['baseline_already']}; nontransferable={result['audit']['baseline_nontransferable']}; true retention={result['audit']['baseline_true_retention']}.",
        "",
        "## 4. Child-dedup loss classification",
        "",
        "Same-expansion exact-child duplicates are classified independently of the retained representative. Physical F8 retention remains a separate concept from purpose retained through coalescing.",
        "",
        "## 5. Project-intent coalescing contract",
        "",
        "Transfer purpose onto the surviving canonical registry request if fresh campaign-next-outstanding analysis supports the same StrategicProject. One request, one handle, no new canonical state, no proof authority, no priority change.",
        "",
        "## 6. Deterministic C1–C8 tests",
        "",
        "C1 TT transfer, C2 non-transferable context, C3 idempotent already-represented, C4 two projects one child, C5 same project one candidate, C6 cheaper arrival version, C7 subscriber sharing, C8 no proof authority.",
        "",
        "## 7. Natural A/B funnel",
        "",
    ]
    for deal in DEALS:
        if deal not in result["runs"]:
            continue
        a = result["runs"][deal].get(BASELINE, {})
        b = result["runs"][deal].get(TREATMENT, {})
        lines.append(
            f"- {deal}: A {a.get('deepest_stage')} / B {b.get('deepest_stage')}; "
            f"F7 {a.get('stage_counts', {}).get('F7_REPLAYABLE_PROGRESS_RETURNED')}/"
            f"{b.get('stage_counts', {}).get('F7_REPLAYABLE_PROGRESS_RETURNED')}; "
            f"F8 {a.get('stage_counts', {}).get('F8_PROGRESS_RETAINED')}/"
            f"{b.get('stage_counts', {}).get('F8_PROGRESS_RETAINED')}."
        )
    lines.extend(
        [
            "",
            "## 8. Recovered project continuations",
            "",
            f"Treatment recovered_candidates={result['audit']['treatment_recovered']}.",
            "",
            "## 9. Subsequent service/progress",
            "",
            f"Recovered candidates later serviced={result['audit']['treatment_later_serviced']}.",
            "",
            "## 10. Foundation result",
            "",
        ]
    )
    for deal in DEALS:
        if TREATMENT not in result["runs"].get(deal, {}):
            continue
        replay = result["runs"][deal][TREATMENT]["first_foundation"]
        lines.append(f"- {deal}: {json.dumps(replay, sort_keys=True) if replay else 'no F14 endpoint'}.")
    lines.extend(["", "## 11. Integrity/runtime", ""])
    for row in result["comparisons"]:
        deal = row["deal"]
        a, b = result["runs"][deal][BASELINE], result["runs"][deal][TREATMENT]
        lines.append(
            f"- {deal}: replay A/B={a['best_progress_replay']['cost_matches']}/{b['best_progress_replay']['cost_matches']}; "
            f"handle errors {a['registry_handle_errors']}/{b['registry_handle_errors']}; "
            f"runtime ratio={row['runtime_ratio_b_over_a']:.3f}; tactical ratio={row['tactical_ratio_b_over_a']:.3f}."
        )
    if result["verdict"].startswith("FIRST_FOUNDATION_REACHED"):
        nxt = "Reproduce first-foundation on the frozen panel without changing priority, width, or budgets."
    elif "REPAIRED" in result["verdict"] and "NOT_SUFFICIENT" not in result["verdict"]:
        nxt = "Bounded R2/R3 frontier-retention remains closed; next is a strategic review against a stripped human-style search alternative. Do not add a project allocator."
    elif result["verdict"] == "PROJECT_INTENT_LOSS_CONFIRMED_NOT_SUFFICIENT":
        nxt = "Do not add a project allocator. Document the next blocker after coalescing and compare this architecture against a stripped alternative in the next strategic review."
    elif result["verdict"] == "TRUE_FOUNDATION_RETENTION_LOSS":
        nxt = "Do not repair portfolio/retention in this architecture sequence; take the planned stripped-search comparison."
    else:
        nxt = "Do not widen this architecture. Next strategic review: human-style move ordering + exact state memory + progressive relaxation + brute-force/backtracking."
    lines.extend(["", "## 12. Exactly one next recommendation", "", nxt, ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--deal", choices=DEALS)
    parser.add_argument("--build-only", action="store_true")
    args = parser.parse_args()
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
