#!/usr/bin/env python3
"""v0.15: one-move-slack fd11 checkpoints first seen at depth 10."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_post_deal_audit import census_legal_by_tier, describe_legal_actions, foundation_proximity
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    first_empty_use_on_path,
    layered_reachability,
)

EXPERIMENT = "simple_progressive_fd11_one_move_slack_v0_15"
BASE_SHA = "2141aaf3b134459634ac42e025d52fe9697f4e52"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
VIABLE = ROOT / "solutions" / "4925153_simple_v0_15_fd11_viable.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_15_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_15_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CANDIDATES = ROOT / "research" / "results" / EXPERIMENT / "depth10_fd11_candidates.jsonl"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
DEAD_FD11_HEX = (
    "53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
V14_UNIQUE_DEPTH9 = 1_144_490
V14_DEPTH9_FRONTIER = 759_780


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def load_seed():
    opening = opening_state()
    prefix = parse_moves_file(SEED_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    digest = pack_state(seed).hex()
    empties = empty_column_indices(seed)
    ok = (
        digest == EXPECTED_HEX
        and cost == 102
        and len(prefix) == 102
        and sum(len(col.face_down) for col in seed.columns) == 13
        and list(empties) == [2]
    )
    return opening, prefix, seed, {"ok": ok, "digest": digest, "cost": cost, "empties": list(empties)}


def replay_combined(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        combined.extend(tuple(a) if not isinstance(a, tuple) else a for a in part)
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        prox = foundation_proximity(end)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "fd": sum(len(col.face_down) for col in end.columns),
            "stock_rows": len(end.stock) // 10,
            "foundations": len(end.foundations),
            "empties": list(empty_column_indices(end)),
            "longest_run": prox["longest_exposed_same_suit_run"],
            "adjacencies": prox["exposed_same_suit_adjacencies"],
            "blocks": prox["movable_same_suit_blocks"],
            "digest": pack_state(end).hex(),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def inspect_candidate(item: dict) -> dict:
    state = unpack_state(bytes.fromhex(item["digest"]))
    census = census_legal_by_tier(state)
    rows = describe_legal_actions(state)
    prox = foundation_proximity(state)
    return {
        "digest": item["digest"],
        "depth": item["depth"],
        "fd": item["fd"],
        "foundations": item["foundations"],
        "actions": item["actions"],
        "hits": item.get("hits", 1),
        "empties": item["empties"],
        "empty_count": len(item["empties"]),
        "longest_run": prox["longest_exposed_same_suit_run"],
        "adjacencies": prox["exposed_same_suit_adjacencies"],
        "blocks": prox["movable_same_suit_blocks"],
        "legal": census["legal"],
        "a": census["a"],
        "b": census["b"],
        "c": census["c"],
        "d": census["d"],
        "immediate_uncover": any(row.get("uncovers_face_down") for row in rows),
        "immediate_empty_create": any(row.get("creates_empty") for row in rows),
        "immediate_foundation": census["has_immediate_foundation_move"],
        "is_dead_depth9": item["digest"] == DEAD_FD11_HEX,
    }


def workspace_on_path(root: SpiderState, actions: list) -> dict:
    first_use = first_empty_use_on_path(root, actions)
    seq = [list(empty_column_indices(root))]
    events = []
    state = root.clone()
    for action in actions:
        before = empty_column_indices(state)
        dest_was_empty = False
        source_became = False
        if action != ("deal",):
            src, dst, k = action
            dest_was_empty = state.columns[dst].is_empty()
            source_became = k == len(state.columns[src].face_up) and not state.columns[src].face_down
        apply_action(state, action)
        after = empty_column_indices(state)
        seq.append(list(after))
        events.extend(
            empty_transition_events(
                before, after, dest_was_empty=dest_was_empty, source_became_empty=source_became
            )
        )
    timing = "never"
    if first_use:
        timing = "immediate" if first_use.get("immediate") else "delayed"
    return {
        "start_empties": seq[0],
        "end_empties": seq[-1],
        "empty_sequence": seq,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "first_empty_use": first_use,
        "timing": timing,
    }


def compact_search(result) -> dict:
    return {
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_run": result.max_run,
        "max_empties": result.max_empties,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "layers": result.layers,
        "fresh_tt": result.fresh_tt,
        "imported_keys": result.imported_keys,
        "source_count": result.source_count,
        "collected_complete": result.collected_complete,
        "collect_partial": result.collect_partial,
        "collected_depth": result.collected_depth,
        "depth_expanded_frac": result.depth_expanded_frac,
        "first_depth": result.first_depth,
        "stream_discarded": result.stream_discarded,
        "keys_before_stream": result.keys_before_stream,
        "last_layer_generated": result.last_layer_generated,
        "last_layer_duplicates": result.last_layer_duplicates,
        "cross_origin_dups": result.cross_origin_dups,
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("direct_foundation"):
        return "DEPTH10_DIRECTLY_REACHES_FOUNDATION", "foundation at overall local depth 10"
    if payload.get("direct_fd10"):
        return "DEPTH10_DIRECTLY_REACHES_FD10", "fd10 at depth 10 from the fd13 seed"
    if payload.get("foundation"):
        return "ONE_MOVE_SLACK_FD11_REACHES_FOUNDATION", "a new depth-10 fd11 checkpoint reached a foundation"
    if payload.get("fd10"):
        return "ONE_MOVE_SLACK_FD11_REACHES_FD10", "a new depth-10 fd11 checkpoint reached fd10"
    phase1 = payload.get("phase1") or {}
    if not phase1.get("collected_complete"):
        return "DEPTH10_FD11_ENUMERATION_INCOMPLETE", "depth-9 frontier was not fully expanded"
    if payload.get("new_candidate_count") == 0:
        return "NO_NEW_DEPTH10_FD11_CHECKPOINTS", "complete harvest has no genuinely new depth-10 fd11 states"
    phase2 = payload.get("phase2") or {}
    stop = (phase2.get("search") or {}).get("stop_reason")
    if stop in ("unique limit", "time limit", "rss abort"):
        return "PORTFOLIO_CONTINUATION_STATE_EXPLOSION", f"continuation hit {stop}"
    if payload.get("new_candidate_count", 0) > 0 and not payload.get("fd10"):
        return "DEPTH10_FD11_VARIANTS_EXIST_BUT_STALL", "new depth-10 fd11 states exist but none reach fd10/foundation"
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict in (
        "DEPTH10_DIRECTLY_REACHES_FOUNDATION",
        "DEPTH10_DIRECTLY_REACHES_FD10",
        "ONE_MOVE_SLACK_FD11_REACHES_FOUNDATION",
        "ONE_MOVE_SLACK_FD11_REACHES_FD10",
        "ONE_MOVE_SLACK_CREATES_VIABLE_CHECKPOINT",
    ):
        return (
            "One move of slack produced a viable continuation. Next: restart the "
            "reveal ratchet from that depth-10 checkpoint; do not add a heuristic."
        )
    if verdict == "DEPTH10_FD11_VARIANTS_EXIST_BUT_STALL":
        return (
            "New depth-10 fd11 states exist but still stall. Next: do not add a "
            "heuristic; a separate v0.16 may test two-move slack (depth 11)."
        )
    if verdict == "NO_NEW_DEPTH10_FD11_CHECKPOINTS":
        return (
            "One extra primitive does not create a new fd11 state. Next: do not add "
            "a heuristic; a separate v0.16 may test two-move slack."
        )
    if verdict == "DEPTH10_FD11_ENUMERATION_INCOMPLETE":
        return "Do not raise limits here. Report the partial harvest and stop."
    if verdict == "PORTFOLIO_CONTINUATION_STATE_EXPLOSION":
        return "Do not deepen continuation. Report completed layers and stop."
    return "Reproduce the depth-10 harvest before changing checkpoint policy."


def write_report(payload: dict) -> None:
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2") or {}
    lines = [
        "# Simple Progressive Search v0.15: One-Move-Slack FD11 Checkpoints",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "One extra primitive before fd11 is the only slack tested. Production `solve_progressive` is unchanged.",
        "",
        "## 2. Depth-9 regression",
        "",
        f"- first_depth fd11={(p1.get('first_depth') or {}).get('fd_le_11')}",
        f"- keys before stream={p1.get('keys_before_stream')} (v0.14 unique through depth 9={V14_UNIQUE_DEPTH9})",
        f"- depth-9 expanded complete={p1.get('collected_complete')} frac={p1.get('depth_expanded_frac')}",
        "",
        "## 3. Depth-10 harvest",
        "",
        f"- successors generated={p1.get('last_layer_generated')} duplicates={p1.get('last_layer_duplicates')} discarded={p1.get('stream_discarded')}",
        f"- unique retained={p1.get('unique')} elapsed={p1.get('elapsed_s')} rss={p1.get('peak_rss_mb')} stop={p1.get('stop_reason')}",
        f"- new depth-10 fd11 candidates={payload.get('new_candidate_count')} (dead depth-9 re-hits excluded)",
        f"- empty0/1/ge2={payload.get('empty_distribution')}",
        f"- empty identities={payload.get('empty_identities')}",
        f"- run distribution={payload.get('run_distribution')}",
        f"- legal range={payload.get('legal_range')} adj range={payload.get('adj_range')} blocks range={payload.get('blocks_range')}",
        f"- direct fd10={payload.get('direct_fd10')} direct foundation={payload.get('direct_foundation')}",
        "",
        "## 4. Phase 2 continuation",
        "",
    ]
    if not p2:
        lines.append("- not run.")
    else:
        s = p2.get("search") or {}
        lines.append(
            f"- sources={s.get('source_count')} unique={s.get('unique')} gen_depth={s.get('completed_generated_depth')} "
            f"stop={s.get('stop_reason')} min_fd={s.get('min_fd')} fnd={s.get('max_foundations')} "
            f"elapsed={s.get('elapsed_s')} rss={s.get('peak_rss_mb')}"
        )
        lines.append("")
        lines.append("| Depth | Frontier | Unique | min fd | empty0 | empty1 | origins |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for layer in s.get("layers") or []:
            lines.append(
                f"| {layer.get('depth')} | {layer.get('frontier_size')} | {layer.get('cumulative_unique')} | "
                f"{layer.get('min_fd')} | {layer.get('states_empty_0')} | {layer.get('states_empty_1')} | "
                f"{layer.get('origins_represented')} |"
            )
    winner = payload.get("winner")
    lines.extend(["", "## 5. Winner", ""])
    if not winner:
        lines.append("- none.")
    else:
        lines.append(
            f"- digest `{winner.get('digest')}` empties={winner.get('empties')} run={winner.get('longest_run')} "
            f"legal={winner.get('legal')}"
        )
        cont = payload.get("continuation") or {}
        w = cont.get("workspace") or {}
        r = cont.get("combined_replay") or {}
        lines.append(
            f"- continuation depth={cont.get('local_depth')} replay={r.get('ok')} fd={r.get('fd')} "
            f"fnd={r.get('foundations')} empties={r.get('empties')} timing={w.get('timing')} "
            f"consumed={w.get('consumed')} transferred={w.get('transferred')} recreated={w.get('recreated')}"
        )
    cmp_ = payload.get("comparison") or {}
    lines.extend(
        [
            "",
            "## 6. Depth-9 dead vs depth-10 viable",
            "",
            "| Metric | Depth-9 dead | Depth-10 viable |",
            "| --- | ---: | ---: |",
            f"| FD | 11 | {cmp_.get('winner_fd')} |",
            f"| Depth from fd13 | 9 | {cmp_.get('winner_depth')} |",
            f"| Local MW cost | 9 | {cmp_.get('winner_cost')} |",
            f"| Empties | 0 | {cmp_.get('winner_empties')} |",
            f"| Run | 6 | {cmp_.get('winner_run')} |",
            f"| Adjacencies | 39 | {cmp_.get('winner_adj')} |",
            f"| Movable blocks | 4 | {cmp_.get('winner_blocks')} |",
            f"| Legal actions | 5 | {cmp_.get('winner_legal')} |",
            f"| Reaches fd10 | no | {cmp_.get('winner_reaches_fd10')} |",
            f"| Continuation depth to fd10 | — | {cmp_.get('winner_local_depth')} |",
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
            "Production solve_progressive is unchanged. Depth 11+ fd11 states were not searched.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    opening, prefix, seed, seed_info = load_seed()
    if not seed_info["ok"]:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "seed failed", "seed": seed_info}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print("SEED_OK", flush=True)
    print("PHASE1 harvest first-seen-at-depth-10 fd11", flush=True)
    phase1 = layered_reachability(
        seed,
        max_depth=10,
        max_unique=5_000_000,
        time_limit_s=1800.0,
        rss_abort_mb=4 * 1024.0,
        collect_fd=11,
        collect_exact_depth=10,
        stream_last=True,
        checkpoints=(4, 8),
    )
    print(
        f"PHASE1 stop={phase1.stop_reason} unique={phase1.unique} before_stream={phase1.keys_before_stream} "
        f"streamed={phase1.last_layer_generated} discarded={phase1.stream_discarded} "
        f"candidates={len(phase1.collected)} complete={phase1.collected_complete} "
        f"min_fd={phase1.min_fd} fnd={phase1.max_foundations} elapsed={phase1.elapsed_s:.1f} rss={phase1.peak_rss_mb}",
        flush=True,
    )
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    inspected = []
    with CANDIDATES.open("w", encoding="utf-8") as fh:
        for item in phase1.collected:
            rec = inspect_candidate(item)
            inspected.append(rec)
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    new_ones = [rec for rec in inspected if not rec["is_dead_depth9"]]
    dead_hits = sum(1 for rec in inspected if rec["is_dead_depth9"])
    empty_counts = Counter(rec["empty_count"] for rec in new_ones)
    empty_ids = Counter(tuple(rec["empties"]) for rec in new_ones)
    runs = Counter(rec["longest_run"] for rec in new_ones)
    legal_vals = [rec["legal"] for rec in new_ones]
    adj_vals = [rec["adjacencies"] for rec in new_ones]
    block_vals = [rec["blocks"] for rec in new_ones]
    dist = {
        "empty_0": empty_counts.get(0, 0),
        "empty_1": empty_counts.get(1, 0),
        "empty_ge2": sum(v for k, v in empty_counts.items() if k >= 2),
    }
    print(
        f"CENSUS new={len(new_ones)} dead_rehit={dead_hits} empty0={dist['empty_0']} "
        f"empty1={dist['empty_1']} empty_ge2={dist['empty_ge2']}",
        flush=True,
    )
    direct_fd10 = phase1.min_fd <= 10 and (phase1.first_depth.get("fd_le_10") == 10)
    direct_fnd = phase1.max_foundations >= 1 and phase1.first_depth.get("foundation") == 10
    winner = None
    continuation = None
    foundation = None
    fd10_payload = None
    phase2_wrap = None

    if direct_fnd and "foundation" in phase1.witnesses:
        wit = phase1.witnesses["foundation"]
        local = [tuple(a) for a in wit.get("actions") or []]
        foundation = {
            "kind": "foundation",
            "local_depth": wit.get("depth"),
            "combined_replay": replay_combined(opening, [prefix, local]),
            "workspace": workspace_on_path(seed, local),
        }
    elif direct_fd10 and "fd_le_10" in phase1.witnesses:
        wit = phase1.witnesses["fd_le_10"]
        local = [tuple(a) for a in wit.get("actions") or []]
        fd10_payload = {
            "kind": "direct_fd10",
            "local_depth": wit.get("depth"),
            "combined_replay": replay_combined(opening, [prefix, local]),
            "workspace": workspace_on_path(seed, local),
        }
        FD10_FIXTURE.write_text(
            format_moves_text(
                list(prefix) + local,
                header="# v0.15 direct depth-10 fd10 from fd13 seed 4925153\n",
            ),
            encoding="utf-8",
        )
    elif new_ones and phase1.collected_complete:
        sources = [unpack_state(bytes.fromhex(rec["digest"])) for rec in new_ones]
        origin_paths = [[tuple(a) for a in rec["actions"]] for rec in new_ones]
        print(f"PHASE2 multi-source n={len(sources)}", flush=True)
        phase2 = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=12,
            max_unique=2_000_000,
            time_limit_s=1800.0,
            rss_abort_mb=4 * 1024.0,
            stop_fd=10,
            checkpoints=(4, 8, 12),
        )
        phase2_wrap = {"search": compact_search(phase2)}
        print(
            f"PHASE2 stop={phase2.stop_reason} unique={phase2.unique} min_fd={phase2.min_fd} "
            f"fnd={phase2.max_foundations} elapsed={phase2.elapsed_s:.1f}",
            flush=True,
        )
        kind = "foundation" if "foundation" in phase2.witnesses else "fd_le_10" if "fd_le_10" in phase2.witnesses else None
        if kind:
            wit = phase2.witnesses[kind]
            origin = wit.get("origin", 0)
            winner = new_ones[origin]
            local = [tuple(a) for a in wit.get("actions") or []]
            replay = replay_combined(opening, [prefix, origin_paths[origin], local])
            continuation = {
                "kind": kind,
                "local_depth": wit.get("depth"),
                "local_cost": wit.get("local_cost"),
                "actions": [list(a) for a in local],
                "combined_replay": replay,
                "workspace": workspace_on_path(sources[origin], local),
            }
            if kind == "foundation":
                foundation = continuation
            else:
                fd10_payload = continuation
            VIABLE.write_text(
                format_moves_text(
                    list(prefix) + list(origin_paths[origin]),
                    header="\n".join(
                        [
                            "# v0.15 viable depth-10 fd11 checkpoint 4925153",
                            f"# digest: {winner['digest']}",
                            f"# empties: {winner['empties']}",
                            f"# legal: {winner['legal']}",
                        ]
                    ),
                ),
                encoding="utf-8",
            )
            dest = FOUNDATION_FIXTURE if kind == "foundation" else FD10_FIXTURE
            dest.write_text(
                format_moves_text(
                    list(prefix) + list(origin_paths[origin]) + local,
                    header=f"# v0.15 {kind} from one-move-slack fd11 4925153\n",
                ),
                encoding="utf-8",
            )
            print(f"WROTE {VIABLE}", flush=True)
            print(f"WROTE {dest}", flush=True)

    comparison = {
        "winner_fd": None if winner is None else 11,
        "winner_depth": None if winner is None else 10,
        "winner_cost": None if winner is None else 10,
        "winner_empties": None if winner is None else winner.get("empty_count"),
        "winner_run": None if winner is None else winner.get("longest_run"),
        "winner_adj": None if winner is None else winner.get("adjacencies"),
        "winner_blocks": None if winner is None else winner.get("blocks"),
        "winner_legal": None if winner is None else winner.get("legal"),
        "winner_reaches_fd10": bool(fd10_payload or foundation),
        "winner_local_depth": None if continuation is None else continuation.get("local_depth"),
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "phase1": compact_search(phase1),
        "phase2": phase2_wrap,
        "new_candidate_count": len(new_ones),
        "dead_depth9_rehit": dead_hits,
        "empty_distribution": dist,
        "empty_identities": {str(k): v for k, v in empty_ids.items()},
        "run_distribution": {str(k): v for k, v in runs.items()},
        "legal_range": None if not legal_vals else [min(legal_vals), max(legal_vals)],
        "adj_range": None if not adj_vals else [min(adj_vals), max(adj_vals)],
        "blocks_range": None if not block_vals else [min(block_vals), max(block_vals)],
        "direct_fd10": bool(direct_fd10),
        "direct_foundation": bool(direct_fnd),
        "winner": winner,
        "continuation": continuation,
        "fd10": fd10_payload,
        "foundation": foundation,
        "comparison": comparison,
        "depth9_regression": {
            "expected_unique": V14_UNIQUE_DEPTH9,
            "expected_frontier": V14_DEPTH9_FRONTIER,
            "keys_before_stream": phase1.keys_before_stream,
            "first_fd11_depth": (phase1.first_depth or {}).get("fd_le_11"),
        },
        "candidates_path": str(CANDIDATES.relative_to(ROOT)).replace("\\", "/"),
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. new_d10_fd11={len(new_ones)} complete={phase1.collected_complete} "
        f"fd10={'yes' if fd10_payload else 'no'} foundation={'yes' if foundation else 'no'}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
