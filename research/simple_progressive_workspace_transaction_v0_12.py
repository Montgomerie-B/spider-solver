#!/usr/bin/env python3
"""v0.12: shallow layered workspace-transaction reachability from fd13/empty1."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import foundation_proximity
from spider.simple_workspace_reachability import (
    empty_column_indices,
    first_empty_use_on_path,
    layered_reachability,
)

EXPERIMENT = "simple_progressive_workspace_transaction_v0_12"
BASE_SHA = "d7be8cb2816bd91568980a90d67ee07e809367a6"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
V11 = {
    "unique": 233865,
    "min_fd": 13,
    "max_empties": 1,
    "longest_run": 9,
    "foundations": 0,
    "max_depth": 2000,
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def load_seed():
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    prefix = parse_moves_file(SEED_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    digest = pack_state(seed).hex()
    empties = empty_column_indices(seed)
    prox = foundation_proximity(seed)
    ok = (
        digest == EXPECTED_HEX
        and cost == 102
        and len(prefix) == 102
        and sum(len(col.face_down) for col in seed.columns) == 13
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
        and len(empties) == 1
        and prox["longest_exposed_same_suit_run"] == 6
    )
    return opening, prefix, seed, {
        "ok": ok,
        "digest": digest,
        "cost": cost,
        "path_length": len(prefix),
        "fd": 13 if ok else sum(len(col.face_down) for col in seed.columns),
        "stock_rows": 0,
        "foundations": 0,
        "empties": list(empties),
        "initial_empty_column": None if not empties else empties[0],
        "longest_run": prox["longest_exposed_same_suit_run"],
        "adjacencies": prox["exposed_same_suit_adjacencies"],
        "blocks": prox["movable_same_suit_blocks"],
    }


def replay_combined(opening: SpiderState, prefix: list, local: list) -> dict:
    combined = list(prefix) + [tuple(item) if not isinstance(item, tuple) else item for item in local]
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        prox = foundation_proximity(end)
        empties = empty_column_indices(end)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "fd": sum(len(col.face_down) for col in end.columns),
            "stock_rows": len(end.stock) // 10,
            "foundations": len(end.foundations),
            "empties": list(empties),
            "longest_run": prox["longest_exposed_same_suit_run"],
            "adjacencies": prox["exposed_same_suit_adjacencies"],
            "blocks": prox["movable_same_suit_blocks"],
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def enrich_witness(opening, prefix, seed, witness: dict | None) -> dict | None:
    if not witness:
        return None
    local = [tuple(action) for action in witness.get("actions") or []]
    replay = replay_combined(opening, prefix, local)
    first_use = witness.get("first_empty_use") or first_empty_use_on_path(seed, local)
    timing = "never"
    if first_use:
        if first_use.get("immediate"):
            timing = "USE NOW"
        elif first_use.get("after_ab_setup"):
            timing = "WAIT/SETUP"
        elif first_use.get("after_c_rework"):
            timing = "after C rework"
        else:
            timing = "WAIT/SETUP"
    return {
        **{k: v for k, v in witness.items() if k != "actions"},
        "local_path_length": len(local),
        "actions": [list(action) for action in local],
        "combined_replay": replay,
        "first_empty_use": first_use,
        "use_now_vs_wait": timing,
        "total_path_length": replay.get("path_length"),
        "total_cost": replay.get("cost"),
    }


def empty_quality(result, witnesses: dict) -> str:
    hard = witnesses.get("fd_le_12") or witnesses.get("foundation")
    if hard and (hard.get("combined_replay") or {}).get("ok"):
        use = hard.get("first_empty_use")
        if use:
            return "PRODUCTIVE_SHORT_TERM_WORKSPACE"
    if result.completed_generated_depth < 8 and result.stop_reason in ("unique limit", "time limit", "rss abort"):
        return "INCONCLUSIVE"
    transfer = witnesses.get("empty_transferred") or witnesses.get("empty_recreated")
    if transfer and (transfer.get("combined_replay") or {}).get("ok"):
        return "TRANSFERABLE_WORKSPACE"
    if result.completed_generated_depth >= 8:
        return "LOCALLY_STERILE_WORKSPACE"
    return "INCONCLUSIVE"


def choose_verdict(result, witnesses: dict, quality: str) -> tuple[str, str]:
    fnd = witnesses.get("foundation")
    if fnd and (fnd.get("combined_replay") or {}).get("ok") and (fnd.get("combined_replay") or {}).get("foundations", 0) >= 1:
        return "SHALLOW_WORKSPACE_REACHES_FOUNDATION", f"foundation at depth {fnd.get('depth')}"
    fd12 = witnesses.get("fd_le_12")
    if fd12 and (fd12.get("combined_replay") or {}).get("ok") and (fd12.get("combined_replay") or {}).get("fd", 99) <= 12:
        return "SHALLOW_WORKSPACE_REVEALS_FD12", f"fd {fd12.get('combined_replay', {}).get('fd')} at depth {fd12.get('depth')}"
    if result.stop_reason in ("unique limit", "time limit", "rss abort") and result.completed_generated_depth < 8:
        return "SHALLOW_WORKSPACE_STATE_EXPLOSION", f"stopped at generated depth {result.completed_generated_depth} ({result.stop_reason})"
    transfer = witnesses.get("empty_transferred")
    recreate = witnesses.get("empty_recreated")
    second = witnesses.get("second_empty")
    if any(
        item and (item.get("combined_replay") or {}).get("ok")
        for item in (transfer, recreate, second)
    ):
        return "SHALLOW_WORKSPACE_TRANSFER_FOUND", "short replay-valid empty transfer/recreate/second-empty"
    if quality == "LOCALLY_STERILE_WORKSPACE":
        return (
            "LOCALLY_STERILE_FIRST_EMPTY",
            "completed shallow envelope uses the empty but does not buy fd12, foundation, second empty, or transfer",
        )
    if result.max_run > 6 or any((layer.get("max_run") or 0) > 6 for layer in result.layers):
        return "SHALLOW_WORKSPACE_ONLY_SOFT_PROGRESS", "run/adjacency improved without reveal, foundation, or workspace lifecycle progress"
    if result.stop_reason in ("unique limit", "time limit", "rss abort"):
        return "SHALLOW_WORKSPACE_STATE_EXPLOSION", result.stop_reason
    return "INCONCLUSIVE", "methodological or incomplete comparison"


def next_recommendation(verdict: str) -> str:
    if verdict == "SHALLOW_WORKSPACE_REACHES_FOUNDATION":
        return (
            "Keep the short foundation transaction as a research fixture. Next: test "
            "whether that workspace sequence can be detected cheaply enough to influence "
            "ordering; do not add Pass 3."
        )
    if verdict == "SHALLOW_WORKSPACE_REVEALS_FD12":
        return (
            "Keep the shortest fd<=12 transaction as a research fixture. Next: test "
            "whether that eight-move consume/recreate/reveal sequence can be detected "
            "cheaply enough to influence ordering; do not add Pass 3 and do not return "
            "to deep DFS from this seed."
        )
    if verdict == "SHALLOW_WORKSPACE_TRANSFER_FOUND":
        return (
            "Short empty transfer/recreation exists but does not buy a reveal. Next: "
            "measure whether transferred empties at those short depths expose a legal "
            "uncover that the seed empty does not; do not add a workspace heuristic yet."
        )
    if verdict == "LOCALLY_STERILE_FIRST_EMPTY":
        return (
            "This particular first empty is not useful short-term working capital. Next: "
            "do not add empty-preservation or empty-fill heuristics; look for a different "
            "empty-creating branch rather than deepening DFS from this seed."
        )
    if verdict == "SHALLOW_WORKSPACE_ONLY_SOFT_PROGRESS":
        return (
            "Shallow A+B+C only rearranges structure. Next: do not raise the depth cap "
            "and do not add Pass 3; treat this empty as locally unproductive for reveals."
        )
    if verdict == "SHALLOW_WORKSPACE_STATE_EXPLOSION":
        return (
            "Shallow unique-set growth is the next measurement, not deeper DFS. Next: "
            "report layer sizes and stop; do not engineer a new search framework."
        )
    return "Reproduce the layered workspace search before changing empty policy."


def write_report(payload: dict) -> None:
    seed = payload.get("seed") or {}
    result = payload.get("search") or {}
    witnesses = payload.get("witnesses") or {}
    lines = [
        "# Simple Progressive Search v0.12: Workspace Transaction Reachability",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        f"Empty-quality class (research only): `{payload.get('empty_quality')}`.",
        "",
        "Layered first-visit BFS is a research harness. Production `solve_progressive` is unchanged.",
        "",
        "## 2. Seed",
        "",
        f"- ok={seed.get('ok')} digest `{seed.get('digest')}`",
        f"- path=102 cost=102 fd=13 stock=0 fnd=0 empties={seed.get('empties')} "
        f"initial_empty_column={seed.get('initial_empty_column')} run={seed.get('longest_run')}",
        "",
        "## 3. Layered search",
        "",
        f"- completed generated depth={result.get('completed_generated_depth')}",
        f"- completed expanded depth={result.get('completed_expanded_depth')}",
        f"- unique={result.get('unique')} generated={result.get('generated')} "
        f"duplicate_skips={result.get('duplicate_skips')}",
        f"- min_fd={result.get('min_fd')} max_fnd={result.get('max_foundations')} "
        f"max_run={result.get('max_run')} max_empties={result.get('max_empties')}",
        f"- elapsed_s={result.get('elapsed_s')} rss_mb={result.get('peak_rss_mb')} "
        f"stop={result.get('stop_reason')}",
        "",
        "| Depth | Frontier | Unique | Generated | Dup skips | A | B | C | empty0 | empty1 | empty>=2 | min fd | max run |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for layer in result.get("layers") or []:
        lines.append(
            f"| {layer.get('depth')} | {layer.get('frontier_size')} | {layer.get('cumulative_unique')} | "
            f"{layer.get('generated_successors')} | {layer.get('exact_duplicate_skips')} | "
            f"{layer.get('a_children')} | {layer.get('b_children')} | {layer.get('c_children')} | "
            f"{layer.get('states_empty_0')} | {layer.get('states_empty_1')} | {layer.get('states_empty_ge2')} | "
            f"{layer.get('min_fd')} | {layer.get('max_run')} |"
        )
    lines.extend(["", "## 4. Witnesses", ""])
    for name in (
        "fd_le_12",
        "foundation",
        "empty_transferred",
        "empty_recreated",
        "empty_consumed",
        "second_empty",
        "run_ge_10",
    ):
        item = witnesses.get(name)
        if not item:
            lines.append(f"- {name}: none")
            continue
        replay = item.get("combined_replay") or {}
        use = item.get("first_empty_use") or {}
        lines.append(
            f"- {name}: depth={item.get('depth')} local_cost={item.get('local_cost')} "
            f"total_path={replay.get('path_length')} cost={replay.get('cost')} "
            f"fd={replay.get('fd')} fnd={replay.get('foundations')} empties={replay.get('empties')} "
            f"run={replay.get('longest_run')} replay={replay.get('ok')} "
            f"first_empty_use_depth={use.get('depth')} tier={use.get('tier_name')} "
            f"timing={item.get('use_now_vs_wait')}"
        )
        if item.get("empty_sequence"):
            lines.append(f"  empty_sequence={item.get('empty_sequence')}")
    lines.extend(
        [
            "",
            "## 5. USE NOW vs WAIT/SETUP",
            "",
            payload.get("use_interpretation") or "",
            "",
            "## 6. Comparison with v0.11 DFS",
            "",
            f"- v0.11 DFS unique={V11['unique']} min_fd={V11['min_fd']} empties={V11['max_empties']} "
            f"run={V11['longest_run']} fnd={V11['foundations']} max_depth={V11['max_depth']}",
            f"- v0.12 BFS unique={result.get('unique')} min_fd={result.get('min_fd')} "
            f"empties={result.get('max_empties')} run={result.get('max_run')} "
            f"fnd={result.get('max_foundations')} completed_depth={result.get('completed_generated_depth')}",
            "",
            "## 7. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Production solve_progressive is unchanged. This harness is research-only.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def use_interpretation(witnesses: dict) -> str:
    hard = witnesses.get("foundation") or witnesses.get("fd_le_12")
    if hard and hard.get("first_empty_use"):
        return (
            f"Best hard witness timing={hard.get('use_now_vs_wait')} "
            f"first empty-use depth={hard['first_empty_use'].get('depth')} "
            f"tier={hard['first_empty_use'].get('tier_name')} "
            f"column={hard['first_empty_use'].get('empty_column')} "
            f"consumed={hard['first_empty_use'].get('consumed')} "
            f"transferred={hard['first_empty_use'].get('transferred')}."
        )
    transfer = witnesses.get("empty_transferred") or witnesses.get("empty_recreated") or witnesses.get("empty_consumed")
    if transfer and transfer.get("first_empty_use"):
        return (
            f"No hard progress. Shortest workspace event timing={transfer.get('use_now_vs_wait')} "
            f"first empty-use depth={transfer['first_empty_use'].get('depth')} "
            f"tier={transfer['first_empty_use'].get('tier_name')}."
        )
    return "No empty-use witness was retained."


def main() -> int:
    opening, prefix, seed, seed_info = load_seed()
    if not seed_info["ok"]:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "INCONCLUSIVE",
            "note": "seed failed",
            "seed": seed_info,
        }
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print(
        f"SEED_OK empty_col={seed_info['initial_empty_column']} digest={seed_info['digest'][:16]}...",
        flush=True,
    )
    started = time.perf_counter()
    result = layered_reachability(
        seed,
        max_depth=20,
        max_unique=1_000_000,
        time_limit_s=1800.0,
        rss_abort_mb=8 * 1024.0,
    )
    print(
        f"SEARCH stop={result.stop_reason} gen_depth={result.completed_generated_depth} "
        f"exp_depth={result.completed_expanded_depth} unique={result.unique} "
        f"min_fd={result.min_fd} run={result.max_run} fnd={result.max_foundations} "
        f"rss={result.peak_rss_mb} elapsed={result.elapsed_s:.1f}",
        flush=True,
    )
    witnesses = {}
    for kind, raw in result.witnesses.items():
        witnesses[kind] = enrich_witness(opening, prefix, seed, raw)
    if result.fd12_same_depth:
        witnesses["fd_le_12_same_depth"] = [
            enrich_witness(opening, prefix, seed, item) for item in result.fd12_same_depth
        ]
    quality = empty_quality(result, witnesses)
    verdict, note = choose_verdict(result, witnesses, quality)
    search = {
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "path_cycle_skips": result.path_cycle_skips,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_run": result.max_run,
        "max_empties": result.max_empties,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "layers": result.layers,
        "expansion_order": result.expansion_order,
        "first_depth": result.first_depth,
        "wall_s": time.perf_counter() - started,
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "search": search,
        "witnesses": witnesses,
        "empty_quality": quality,
        "use_interpretation": use_interpretation(witnesses),
        "v11_reference": V11,
        "verdict": verdict,
        "note": note,
        "next_recommendation": next_recommendation(verdict),
        "interpretation": (
            f"Verdict {verdict}. Generated depth {result.completed_generated_depth}, "
            f"unique={result.unique}, min_fd={result.min_fd}, max_empties={result.max_empties}, "
            f"max_run={result.max_run}, fnd={result.max_foundations}, quality={quality}."
        ),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
