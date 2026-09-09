#!/usr/bin/env python3
"""Bounded natural panel for the simple progressive competing solver."""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import RelaxationStage, solve_progressive
from spider.state_identity import canonical_state_key


EXPERIMENT = "simple_progressive_solver_v0_1"
BASE_SHA = "a10578240dd10d2c3c8a4b385ed2534ec341967f"
FUNNEL_PLAN = ROOT / "docs" / "research" / "first_foundation_conversion_funnel_v0_1_plan.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
DEALS = ("P0", "P2", "P7")
CONFIG = {
    "max_nodes": 200_000,
    "time_limit_s": 180.0,
    "target_foundations": 1,
    "max_stage": int(RelaxationStage.ANY),
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def load_entry(entry: dict) -> tuple:
    cards = tuple(load_deal(ROOT / entry["fixture_path"]))
    opening = SpiderState.from_cards(list(cards))
    digest = _digest(opening)
    if digest != entry["opening_digest"]:
        raise RuntimeError(f"opening digest mismatch {digest} != {entry['opening_digest']}")
    return cards, opening


def compact(opening: SpiderState, result) -> dict:
    replay = None
    if result.actions:
        end = opening.clone()
        paid = replay_actions(end, list(result.actions))
        replay = {
            "cost_matches": paid == result.cost,
            "foundations": len(end.foundations),
            "face_down": sum(len(col.face_down) for col in end.columns),
            "stock_rows": len(end.stock) // 10,
            "solved": end.is_solved(),
        }
    return {
        "solved": result.solved,
        "max_foundations": result.max_foundations,
        "min_face_down": result.min_face_down,
        "min_stock_rows": result.min_stock_rows,
        "stage_reached": result.stage_reached,
        "nodes": result.nodes,
        "elapsed_s": result.elapsed_s,
        "cost": result.cost,
        "path_length": len(result.actions),
        "stop_reason": result.stop_reason,
        "replay_ok": result.replay_ok,
        "replay": replay,
        "opening_face_down": sum(len(col.face_down) for col in opening.columns),
        "opening_stock_rows": len(opening.stock) // 10,
    }


def run_deal(deal: str, entry: dict) -> dict:
    _cards, opening = load_entry(entry)
    print(f"START {deal}", flush=True)
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=CONFIG["max_nodes"],
        time_limit_s=CONFIG["time_limit_s"],
        target_foundations=CONFIG["target_foundations"],
    )
    payload = compact(opening, result)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {deal} fnd={payload['max_foundations']} fd={payload['min_face_down']} "
        f"nodes={payload['nodes']} stage={payload['stage_reached']} "
        f"stop={payload['stop_reason']} replay={payload['replay_ok']}",
        flush=True,
    )
    return payload


def verdict(runs: dict) -> tuple[str, str]:
    foundations = sum(item["max_foundations"] for item in runs.values())
    solved = any(item["solved"] for item in runs.values())
    if solved:
        return "SIMPLE_SOLVER_SOLVED", "the progressive baseline solved at least one panel deal"
    if foundations:
        return (
            "SIMPLE_SOLVER_REACHED_FOUNDATION",
            f"reached {foundations} foundation(s) under the bounded envelope",
        )
    best_fd = min(item["min_face_down"] for item in runs.values())
    if best_fd <= 20:
        return (
            "SIMPLE_SOLVER_NO_FOUNDATION_BUT_DEEPER",
            f"no foundation, but uncovered to {best_fd} face-down vs strategic-controller 0-foundation ceiling",
        )
    return (
        "SIMPLE_SOLVER_NO_BETTER_THAN_STRATEGIC",
        "no foundation and no clear uncovering advantage in this envelope",
    )


def write_report(result: dict) -> None:
    lines = [
        "# Simple Progressive Search Baseline v0.1",
        "",
        "## 1. Verdict",
        "",
        f"`{result['verdict']}` — {result['note']}.",
        "",
        "This is a competing solver, not a patch to the strategic controller.",
        "",
        "## 2. Solver contract",
        "",
        "Reuses engine, MobilityWare rules, legal moves, automatic flip/removal,",
        "Deal legality, canonical exact identity, and replay.  Does not import the",
        "anytime controller, scheduler, campaigns, registry, or StrategicProject.",
        "",
        "Relaxation stages: STRICT (same-suit / uncover) → BUILD (mixed / king-empty)",
        "→ SPACE (create empty / park) → DEAL → ANY (join-breaks).",
        "Each stage receives an equal node/time slice. Exact TT keys",
        "`canonical_state_key` and re-expands a state only when g improves or",
        "the stage is strictly looser.",
        "",
        "## 3. Envelope",
        "",
        json.dumps(result["config"], indent=2),
        "",
        "## 4. Natural results",
        "",
    ]
    for deal, row in result["runs"].items():
        replay = row.get("replay") or {}
        lines.append(
            f"- {deal}: foundations={row['max_foundations']} joint path fd="
            f"{replay.get('face_down')} stock_rows={replay.get('stock_rows')} "
            f"cost={row['cost']} length={row['path_length']} "
            f"(search-wide min_fd={row['min_face_down']}, min_stock_rows={row['min_stock_rows']}; "
            f"opening fd={row['opening_face_down']}) "
            f"stage={row['stage_reached']} nodes={row['nodes']} "
            f"time={row['elapsed_s']:.1f}s stop={row['stop_reason']} replay={row['replay_ok']}."
        )
    lines.extend(
        [
            "",
            "## 5. Comparison to strategic controller",
            "",
            "Recent 400-expansion 4-suit strategic runs on these deals still report",
            "0 foundations.  This baseline asks whether cheap ordering + exact memory",
            "+ backtracking + relaxation can reach a foundation inside a similar wall.",
            "",
            "## 6. Integrity",
            "",
            "Returned paths are replayed through `replay_actions`. Source states are",
            "cloned; the solver module does not import planner policy.",
            "",
            "## 7. Exactly one next recommendation",
            "",
        ]
    )
    if result["verdict"] == "SIMPLE_SOLVER_REACHED_FOUNDATION":
        nxt = "Scale the same simple solver (nodes/time) and test full solve; do not fold it into the strategic controller yet."
    elif result["verdict"] == "SIMPLE_SOLVER_SOLVED":
        nxt = "Measure solution length against the 172-move human route; keep the solver separate."
    elif result["verdict"] == "SIMPLE_SOLVER_NO_FOUNDATION_BUT_DEEPER":
        nxt = "Give the same solver a larger node envelope before judging the hypothesis; still do not merge with the strategic controller."
    else:
        nxt = "Hypothesis not supported in this envelope. Keep the solver as a baseline and do not grow the strategic controller in response."
    lines.extend([nxt, ""])
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    fixtures = json.loads(FUNNEL_PLAN.read_text(encoding="utf-8"))["fixtures"]
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    runs = {}
    for deal in DEALS:
        path = CHECKPOINTS / f"{deal}.json"
        if path.exists():
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("config") == CONFIG:
                runs[deal] = saved["result"]
                print(f"RESUME {deal}", flush=True)
                continue
        measured = run_deal(deal, fixtures[deal])
        _write_json(path, {"config": CONFIG, "result": measured})
        runs[deal] = measured
        if measured["max_foundations"] >= 1:
            print("STOP first foundation reached; remaining deals still run", flush=True)
    label, note = verdict(runs)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "config": CONFIG,
        "deals": list(DEALS),
        "runs": runs,
        "verdict": label,
        "note": note,
        "total_foundations": sum(item["max_foundations"] for item in runs.values()),
        "any_solved": any(item["solved"] for item in runs.values()),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {label}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
