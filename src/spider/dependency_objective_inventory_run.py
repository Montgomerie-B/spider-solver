"""One-shot inventory validation driver.

Run this only after the inventory sources are committed. It calls
``compare_local_objective`` once per source at the frozen panel limits.
It does not change those limits, the sources, or the evaluator.

Usage from the repository root:

    py -3 -m spider.dependency_objective_inventory_run
"""

from __future__ import annotations

import json
import time

from spider.dependency_objective_inventory import (
    DECK_LABEL,
    OPENING_REACHABILITY,
    build_state,
    inventory_shape_failures,
    inventory_sources,
)
from spider.dependency_objective_lookahead import compare_local_objective
from spider.dependency_objective_panel import reveal_predicate
from spider.packed_state import pack_state
from spider.research_actions import apply_action, step_cost, tableau_actions

_REQUIRED_WIN = frozenset({"distractor-reveal", "three-deep-uncover"})
_UNRESOLVED = frozenset({"unknown", "upper-unfinished"})


def _replay(state, candidate, predicate) -> dict:
    actions = tuple(candidate.actions) + tuple(candidate.continuation)
    if candidate.total_cost is None:
        return {
            "replayed": False,
            "cost": None,
            "cost_matches": False,
            "predicate": False,
            "target_pack": None,
        }
    current = state.clone()
    cost = 0
    for action in actions:
        normalized = tuple(int(part) for part in action)
        if normalized not in tableau_actions(current):
            return {
                "replayed": False,
                "cost": None,
                "cost_matches": False,
                "predicate": False,
                "target_pack": None,
                "illegal": str(normalized),
            }
        cost += int(step_cost(current, normalized))
        apply_action(current, normalized)
    return {
        "replayed": True,
        "cost": cost,
        "cost_matches": cost == candidate.total_cost,
        "predicate": bool(predicate(current)),
        "target_pack": pack_state(current).hex(),
    }


def _candidate_row(state, candidate, predicate) -> dict:
    return {
        "option_id": candidate.option_id,
        "actions": [list(action) for action in candidate.actions],
        "prefix_cost": candidate.prefix_cost,
        "continuation": [list(action) for action in candidate.continuation],
        "continuation_cost": candidate.continuation_cost,
        "total_cost": candidate.total_cost,
        "status": candidate.status,
        "stop_reason": candidate.stop_reason,
        "kernel_called": candidate.kernel_called,
        "unique": candidate.unique,
        "expanded": candidate.expanded,
        "generated": candidate.generated,
        "elapsed_s": candidate.elapsed_s,
        "zero_cost_actions": candidate.zero_cost_actions,
        "baseline_index": candidate.baseline_index,
        "replay": _replay(state, candidate, predicate),
    }


def _by_id(row: dict) -> dict:
    return {candidate["option_id"]: candidate for candidate in row["candidates"]}


def _correctness(row: dict) -> list:
    failures = []
    if row["shape_failures"] or row["skipped"]:
        failures.append("shape")
        return failures
    if row["legal_actions"] != [list(action) for action in row["frozen_legal"]]:
        failures.append("legal-drift")
    if row["pruned"]:
        failures.append("pruned")
    if row["absolute_g_used_for_proof"]:
        failures.append("absolute-g")
    if row["obligations_status"] != "matched":
        failures.append("obligations")
    if len(row["candidates"]) != len(row["legal_actions"]) or len(row["legal_actions"]) > 8:
        failures.append("candidate-count")
    found = _by_id(row)
    unresolved = [item for item in row["candidates"] if item["status"] in _UNRESOLVED]
    exact = [item for item in row["candidates"] if item["status"] == "exact"]
    if unresolved:
        if row["status"] != "inconclusive" or row["choice_id"] != row["baseline_id"]:
            failures.append("unknown-fallback")
    elif exact:
        if row["status"] != "ranked":
            failures.append("ranked-status")
    elif row["status"] != "no-exact-in-scope" or row["choice_id"] != row["baseline_id"]:
        failures.append("exhausted-fallback")
    for item in row["candidates"]:
        replay = item["replay"]
        if item["status"] in ("exact", "upper-unfinished") and item["total_cost"] is not None:
            if not replay["replayed"] or not replay["cost_matches"] or not replay["predicate"]:
                failures.append(f"witness:{item['option_id']}")
            continuation = item["continuation_cost"]
            if item["total_cost"] != item["prefix_cost"] + int(continuation or 0):
                failures.append(f"cost-sum:{item['option_id']}")
        elif item["total_cost"] is not None:
            failures.append(f"cost-on-miss:{item['option_id']}")
    if row["source_id"] == "symmetric-tie" and row["status"] == "ranked":
        costs = [item["total_cost"] for item in exact]
        if costs and len(set(costs)) == 1 and row["choice_id"] != row["baseline_id"]:
            failures.append("tie-order")
    if row["source_id"] == "immediate-join":
        join = found.get("(5, 6, 1)")
        if join is None or join["status"] != "exact" or join["stop_reason"] != "prefix-terminal":
            failures.append("immediate-prefix")
        elif join["total_cost"] != 1 or join["kernel_called"] or not join["replay"]["predicate"]:
            failures.append("immediate-prefix")
    if row["status"] == "ranked" and row["baseline_id"] in found and row["choice_id"] in found:
        base = found[row["baseline_id"]]
        choice = found[row["choice_id"]]
        if (
            base["status"] == "exact"
            and choice["status"] == "exact"
            and choice["total_cost"] > base["total_cost"]
        ):
            failures.append("regression")
    return failures


def _strict_win(row: dict) -> bool:
    if row["status"] != "ranked":
        return False
    found = _by_id(row)
    base = found.get(row["baseline_id"])
    choice = found.get(row["choice_id"])
    if base is None or choice is None:
        return False
    if base["status"] != "exact" or choice["status"] != "exact":
        return False
    if choice["option_id"] == base["option_id"]:
        return False
    return int(choice["total_cost"]) < int(base["total_cost"])


def _verdict(rows: list) -> dict:
    failures = {row["source_id"]: _correctness(row) for row in rows}
    broken = {key: value for key, value in failures.items() if value}
    wins = [row["source_id"] for row in rows if not broken and _strict_win(row)]
    if broken:
        verdict = "VALIDATION_FAILED"
        recommendation = (
            "Stop. Preserve this evidence. Do not patch the evaluator or "
            "replace the sources in this task."
        )
    elif len(set(wins)) >= 2 and set(wins) & _REQUIRED_WIN:
        verdict = "INVENTORY_VALIDATED_LOCAL_BENEFIT"
        recommendation = (
            "Keep the frozen lookahead unchanged. The local benefit replicated "
            "on these constructed inventory-valid positions only. Do not treat "
            "this as opening reachability, deal distribution, whole-game "
            "performance, or a better optimum than 172."
        )
    else:
        verdict = "INCONCLUSIVE"
        recommendation = (
            "Do not retune, raise caps, or continue the search. The inventory "
            "sources do not establish a local benefit under the frozen PR4 "
            "limits. Leave the abstract PR4 result unqualified."
        )
    return {
        "verdict": verdict,
        "wins": wins,
        "correctness": failures,
        "recommendation": recommendation,
    }


def run_once() -> dict:
    rows = []
    for source in inventory_sources():
        state = build_state(source)
        shape = inventory_shape_failures(state)
        frozen_legal = source.legal_actions
        if shape:
            rows.append(
                {
                    "source_id": source.source_id,
                    "target_column": source.target_column,
                    "skipped": True,
                    "shape_failures": list(shape),
                    "frozen_legal": [list(action) for action in frozen_legal],
                    "legal_actions": [],
                    "baseline_id": source.baseline_id,
                    "choice_id": None,
                    "status": "not-run",
                    "reason": "shape check failed before lookahead",
                    "pruned": [],
                    "obligations_status": "not_applied",
                    "absolute_g_used_for_proof": False,
                    "source_pack": pack_state(state).hex(),
                    "candidates": [],
                    "baseline_seconds": 0.0,
                    "kernel_seconds": 0.0,
                    "overhead_seconds": 0.0,
                    "wall_seconds": 0.0,
                    "process_cpu_seconds": 0.0,
                }
            )
            continue
        predicate = reveal_predicate(state, source.target_column)
        cpu_started = time.process_time()
        wall_started = time.perf_counter()
        result = compare_local_objective(state, predicate)
        wall_seconds = time.perf_counter() - wall_started
        cpu_seconds = time.process_time() - cpu_started
        rows.append(
            {
                "source_id": source.source_id,
                "target_column": source.target_column,
                "skipped": False,
                "shape_failures": [],
                "frozen_legal": [list(action) for action in frozen_legal],
                "legal_actions": [list(action) for action in result.legal_actions],
                "baseline_id": result.baseline_id,
                "choice_id": result.choice_id,
                "status": result.status,
                "reason": result.reason,
                "pruned": list(result.pruned),
                "obligations_status": result.obligations_status,
                "absolute_g_used_for_proof": result.absolute_g_used_for_proof,
                "source_pack": result.source_pack,
                "candidates": [
                    _candidate_row(state, candidate, predicate) for candidate in result.candidates
                ],
                "baseline_seconds": result.baseline_seconds,
                "kernel_seconds": result.kernel_seconds,
                "overhead_seconds": result.overhead_seconds,
                "wall_seconds": wall_seconds,
                "process_cpu_seconds": cpu_seconds,
            }
        )
    summary = _verdict(rows)
    return {
        "deck_label": DECK_LABEL,
        "opening_reachability": OPENING_REACHABILITY,
        "independent_cold_complete": False,
        "rows": rows,
        **summary,
    }


def main() -> None:
    print(json.dumps(run_once(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
