#!/usr/bin/env python3
"""v0.14: minimum-depth fd11 checkpoint portfolio."""

from __future__ import annotations

import json
import sys
import time
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

EXPERIMENT = "simple_progressive_fd11_checkpoint_portfolio_v0_14"
BASE_SHA = "dd16c4389c5f05cf157764c44a8c9dc3136dd924"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
OLD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
VIABLE_FD11 = ROOT / "solutions" / "4925153_simple_v0_14_fd11_viable.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_14_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_14_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CANDIDATES = ROOT / "research" / "results" / EXPERIMENT / "fd11_candidates.jsonl"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
OLD_FD11_HEX = (
    "53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


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
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
        and list(empties) == [2]
    )
    return opening, prefix, seed, {
        "ok": ok,
        "digest": digest,
        "cost": cost,
        "path_length": len(prefix),
        "empties": list(empties),
    }


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
        "local_path_length": len(item["actions"]),
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
        "cross_origin_dups": result.cross_origin_dups,
        "collected_complete": result.collected_complete,
        "collect_partial": result.collect_partial,
        "collected_depth": result.collected_depth,
        "depth_expanded_frac": result.depth_expanded_frac,
        "first_depth": result.first_depth,
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
        "events": events,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "first_empty_use": first_use,
        "timing": timing,
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("foundation"):
        return "MIN_DEPTH_FD11_PORTFOLIO_REACHES_FOUNDATION", "a min-depth fd11 origin reached a foundation"
    if payload.get("fd10"):
        first_ok = payload.get("first_fd11_reaches_fd10")
        if first_ok is False:
            return "FIRST_FD11_WAS_BAD_CHECKPOINT", "v0.13 first fd11 stalls but another min-depth fd11 reaches fd10"
        return "MIN_DEPTH_FD11_PORTFOLIO_REACHES_FD10", "at least one min-depth fd11 checkpoint reaches fd10"
    phase1 = payload.get("phase1") or {}
    if phase1.get("collect_partial") or not phase1.get("collected_complete"):
        return "FD11_FRONTIER_ENUMERATION_INCOMPLETE", "depth-9 fd11 set is partial"
    phase2 = payload.get("phase2") or {}
    stop = (phase2.get("search") or {}).get("stop_reason")
    if stop in ("unique limit", "time limit", "rss abort"):
        return "PORTFOLIO_SEARCH_STATE_EXPLOSION", f"portfolio continuation hit {stop}"
    dist = payload.get("empty_distribution") or {}
    variants = (dist.get("empty_1") or 0) + (dist.get("empty_ge2") or 0)
    if variants and not payload.get("fd10"):
        return (
            "MIN_DEPTH_FD11_FRONTIER_HAS_WORKSPACE_VARIANTS",
            "complete census has distinct workspace forms but no fd10 in the continuation envelope",
        )
    if phase1.get("collected_complete") and not payload.get("fd10"):
        return "ALL_MIN_DEPTH_FD11_CHECKPOINTS_STALL", "complete min-depth fd11 set has no fd10/foundation continuation"
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict == "MIN_DEPTH_FD11_PORTFOLIO_REACHES_FOUNDATION":
        return (
            "Keep the winning min-depth fd11 origin as a research fixture. Next: "
            "continue the reveal ratchet from that origin; do not add a heuristic yet."
        )
    if verdict in ("MIN_DEPTH_FD11_PORTFOLIO_REACHES_FD10", "FIRST_FD11_WAS_BAD_CHECKPOINT"):
        return (
            "Greedy first-fd11 commitment was the stall. Next: restart the reveal "
            "ratchet from the viable min-depth fd11 origin; do not add empty scoring."
        )
    if verdict == "ALL_MIN_DEPTH_FD11_CHECKPOINTS_STALL":
        return (
            "The min-depth fd11 set is a singleton and it stalls. Next: do not add a "
            "heuristic; the remaining question is whether a slightly longer route to "
            "fd11 (depth 10+) yields a viable checkpoint — not this task."
        )
    if verdict == "MIN_DEPTH_FD11_FRONTIER_HAS_WORKSPACE_VARIANTS":
        return (
            "Min-depth fd11 is not a single workspace form. Next: do not score empties "
            "yet; if continuation failed, stop rather than deepening fd11 depth."
        )
    if verdict == "FD11_FRONTIER_ENUMERATION_INCOMPLETE":
        return "Do not raise limits here. Report the partial census and stop."
    if verdict == "PORTFOLIO_SEARCH_STATE_EXPLOSION":
        return "Do not deepen. Report completed layers and stop; no heuristic."
    return "Reproduce the min-depth fd11 census before changing checkpoint policy."


def write_report(payload: dict) -> None:
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2") or {}
    pre = payload.get("preflight") or {}
    lines = [
        "# Simple Progressive Search v0.14: Minimum-Depth FD11 Checkpoint Portfolio",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "Workspace is telemetry, not an objective. Production `solve_progressive` is unchanged.",
        "",
        "## 2. Preflight — v0.13 first fd11 bubble",
        "",
        f"- true_exhaustion={pre.get('true_exhaustion')} unique={pre.get('unique')} "
        f"max_depth={pre.get('max_depth')} fd10={pre.get('fd10')} empty_created={pre.get('empty_created')} "
        f"foundation={pre.get('foundation')} stop={pre.get('stop_reason')} elapsed={pre.get('elapsed_s')}",
        "",
        "## 3. Phase 1 — min-depth fd11 census",
        "",
        f"- complete={p1.get('collected_complete')} partial={p1.get('collect_partial')} "
        f"unique={p1.get('unique')} gen_depth={p1.get('completed_generated_depth')} "
        f"stop={p1.get('stop_reason')} elapsed={p1.get('elapsed_s')} rss={p1.get('peak_rss_mb')}",
        f"- candidates={payload.get('candidate_count')} empty0={ (payload.get('empty_distribution') or {}).get('empty_0') } "
        f"empty1={(payload.get('empty_distribution') or {}).get('empty_1')} "
        f"empty_ge2={(payload.get('empty_distribution') or {}).get('empty_ge2')}",
        f"- empty identities={payload.get('empty_identities')}",
        f"- run distribution={payload.get('run_distribution')}",
        f"- legal-action range={payload.get('legal_range')}",
        f"- fd10 at depth 9={payload.get('fd10_at_depth9')} foundation at depth 9={payload.get('foundation_at_depth9')}",
        f"- v0.13 first fd11 in set={payload.get('first_fd11_in_set')}",
        "",
        "## 4. Phase 2 — multi-source continuation",
        "",
    ]
    if not p2:
        lines.append("- not run.")
    else:
        s = p2.get("search") or {}
        lines.append(
            f"- sources={s.get('source_count')} unique={s.get('unique')} "
            f"gen_depth={s.get('completed_generated_depth')} stop={s.get('stop_reason')} "
            f"cross_origin_dups={s.get('cross_origin_dups')} "
            f"min_fd={s.get('min_fd')} fnd={s.get('max_foundations')} "
            f"elapsed={s.get('elapsed_s')} rss={s.get('peak_rss_mb')}"
        )
        lines.append("")
        lines.append("| Depth | Frontier | Unique | Generated | Dup | A | B | C | empty0 | empty1 | empty>=2 | min fd | origins |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for layer in s.get("layers") or []:
            lines.append(
                f"| {layer.get('depth')} | {layer.get('frontier_size')} | {layer.get('cumulative_unique')} | "
                f"{layer.get('generated_successors')} | {layer.get('exact_duplicate_skips')} | "
                f"{layer.get('a_children')} | {layer.get('b_children')} | {layer.get('c_children')} | "
                f"{layer.get('states_empty_0')} | {layer.get('states_empty_1')} | {layer.get('states_empty_ge2')} | "
                f"{layer.get('min_fd')} | {layer.get('origins_represented')} |"
            )
    winner = payload.get("winner")
    lines.extend(["", "## 5. Winning origin", ""])
    if not winner:
        lines.append("- none.")
    else:
        lines.append(
            f"- digest `{winner.get('digest')}` empties={winner.get('empties')} run={winner.get('longest_run')} "
            f"legal={winner.get('legal')} A/B/C/D={winner.get('a')}/{winner.get('b')}/{winner.get('c')}/{winner.get('d')}"
        )
        lines.append(f"- local 9-move path={winner.get('actions')}")
        cont = payload.get("continuation") or {}
        lines.append(
            f"- continuation depth={cont.get('local_depth')} cost={cont.get('local_cost')} "
            f"fd={ (cont.get('combined_replay') or {}).get('fd') } "
            f"empties={(cont.get('combined_replay') or {}).get('empties')} "
            f"fnd={(cont.get('combined_replay') or {}).get('foundations')} "
            f"replay={(cont.get('combined_replay') or {}).get('ok')}"
        )
        w = cont.get("workspace") or {}
        lines.append(
            f"- workspace timing={w.get('timing')} consumed={w.get('consumed')} "
            f"transferred={w.get('transferred')} recreated={w.get('recreated')} "
            f"sequence={w.get('empty_sequence')}"
        )
    cmp_ = payload.get("comparison") or {}
    lines.extend(
        [
            "",
            "## 6. First fd11 vs portfolio winner",
            "",
            "| Metric | First fd11 | Portfolio winner |",
            "| --- | ---: | ---: |",
            f"| FD | 11 | {cmp_.get('winner_fd', 11)} |",
            f"| Local depth from fd13 | 9 | {cmp_.get('winner_depth', 9)} |",
            f"| Empties | {cmp_.get('first_empties')} | {cmp_.get('winner_empties')} |",
            f"| Longest run | {cmp_.get('first_run')} | {cmp_.get('winner_run')} |",
            f"| Adjacencies | {cmp_.get('first_adj')} | {cmp_.get('winner_adj')} |",
            f"| Movable blocks | {cmp_.get('first_blocks')} | {cmp_.get('winner_blocks')} |",
            f"| Legal actions | {cmp_.get('first_legal')} | {cmp_.get('winner_legal')} |",
            f"| Can reach fd10 within 12 | no | {cmp_.get('winner_reaches_fd10')} |",
            f"| Local depth to fd10 | — | {cmp_.get('winner_local_depth')} |",
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
            "Multi-source search uses a fresh TT seeded only with min-depth fd11 states.",
            "Production solve_progressive is unchanged.",
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

    old_actions = parse_moves_file(OLD_FD11)
    old_state = opening.clone()
    old_cost = replay_actions(old_state, old_actions)
    old_ok = (
        pack_state(old_state).hex() == OLD_FD11_HEX
        and len(old_actions) == 111
        and old_cost == 111
        and sum(len(col.face_down) for col in old_state.columns) == 11
        and len(old_state.stock) == 0
        and len(old_state.foundations) == 0
        and empty_column_indices(old_state) == ()
    )
    print(f"OLD_FD11_OK={old_ok}", flush=True)
    print("PREFLIGHT continuation from v0.13 fd11, no depth-12 cut", flush=True)
    pre = layered_reachability(
        old_state,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=60.0,
        rss_abort_mb=4 * 1024.0,
        stop_fd=10,
        checkpoints=(),
    )
    preflight = {
        "old_ok": old_ok,
        "true_exhaustion": pre.stop_reason == "frontier empty",
        "unique": pre.unique,
        "max_depth": pre.completed_generated_depth,
        "fd10": pre.min_fd <= 10,
        "empty_created": pre.max_empties >= 1,
        "foundation": pre.max_foundations >= 1,
        "stop_reason": pre.stop_reason,
        "elapsed_s": pre.elapsed_s,
        "peak_rss_mb": pre.peak_rss_mb,
    }
    print(
        f"PREFLIGHT stop={pre.stop_reason} unique={pre.unique} depth={pre.completed_generated_depth} "
        f"fd10={pre.min_fd <= 10} empty={pre.max_empties} fnd={pre.max_foundations}",
        flush=True,
    )
    if pre.min_fd <= 10 or pre.max_foundations >= 1:
        print("PREFLIGHT unexpected hard progress from old fd11", flush=True)

    print("PHASE1 collect all min-depth fd11", flush=True)
    phase1 = layered_reachability(
        seed,
        max_depth=9,
        max_unique=3_000_000,
        time_limit_s=1800.0,
        rss_abort_mb=4 * 1024.0,
        collect_fd=11,
        checkpoints=(4, 8),
    )
    print(
        f"PHASE1 stop={phase1.stop_reason} unique={phase1.unique} complete={phase1.collected_complete} "
        f"n={len(phase1.collected)} depth={phase1.collected_depth} min_fd={phase1.min_fd} "
        f"rss={phase1.peak_rss_mb} elapsed={phase1.elapsed_s:.1f}",
        flush=True,
    )
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    inspected = []
    with CANDIDATES.open("w", encoding="utf-8") as fh:
        for item in phase1.collected:
            rec = inspect_candidate(item)
            inspected.append(rec)
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    empty_counts = Counter(rec["empty_count"] for rec in inspected)
    empty_ids = Counter(tuple(rec["empties"]) for rec in inspected)
    runs = Counter(rec["longest_run"] for rec in inspected)
    legal_vals = [rec["legal"] for rec in inspected]
    first_digest = pack_state(old_state).hex()
    fd10_at_9 = any(rec["fd"] <= 10 for rec in inspected)
    fnd_at_9 = any(rec["foundations"] >= 1 for rec in inspected)
    dist = {
        "empty_0": empty_counts.get(0, 0),
        "empty_1": empty_counts.get(1, 0),
        "empty_ge2": sum(v for k, v in empty_counts.items() if k >= 2),
    }
    print(
        f"CENSUS n={len(inspected)} empty0={dist['empty_0']} empty1={dist['empty_1']} "
        f"empty_ge2={dist['empty_ge2']} first_in_set={first_digest in {r['digest'] for r in inspected}}",
        flush=True,
    )

    winner = None
    continuation = None
    foundation = None
    fd10_payload = None
    phase2_compact = None
    if pre.min_fd <= 10 or pre.max_foundations >= 1:
        # unexpected: old bubble already continues; still run portfolio unless foundation
        pass

    sources = [unpack_state(bytes.fromhex(rec["digest"])) for rec in inspected]
    origin_paths = [[tuple(a) for a in rec["actions"]] for rec in inspected]
    print(f"PHASE2 multi-source n={len(sources)}", flush=True)
    if sources:
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
        phase2_compact = compact_search(phase2)
        print(
            f"PHASE2 stop={phase2.stop_reason} unique={phase2.unique} min_fd={phase2.min_fd} "
            f"fnd={phase2.max_foundations} sources={phase2.source_count} "
            f"cross_origin={phase2.cross_origin_dups} elapsed={phase2.elapsed_s:.1f}",
            flush=True,
        )
        if "foundation" in phase2.witnesses:
            wit = phase2.witnesses["foundation"]
            origin = wit.get("origin", 0)
            winner = inspected[origin]
            local = [tuple(a) for a in wit.get("actions") or []]
            combined_replay = replay_combined(opening, [prefix, origin_paths[origin], local])
            continuation = {
                "kind": "foundation",
                "local_depth": wit.get("depth"),
                "local_cost": wit.get("local_cost"),
                "actions": [list(a) for a in local],
                "combined_replay": combined_replay,
                "workspace": workspace_on_path(sources[origin], local),
            }
            foundation = continuation
            save_parts = list(prefix) + list(origin_paths[origin]) + local
            VIABLE_FD11.write_text(
                format_moves_text(
                    list(prefix) + list(origin_paths[origin]),
                    header="\n".join(
                        [
                            "# v0.14 viable min-depth fd11 origin 4925153",
                            f"# digest: {winner['digest']}",
                            f"# empties: {winner['empties']}",
                        ]
                    ),
                ),
                encoding="utf-8",
            )
            FOUNDATION_FIXTURE.write_text(
                format_moves_text(
                    save_parts,
                    header="\n".join(
                        [
                            "# v0.14 foundation from min-depth fd11 portfolio 4925153",
                            f"# path_length: {combined_replay.get('path_length')}",
                            f"# fd: {combined_replay.get('fd')}",
                            f"# foundations: {combined_replay.get('foundations')}",
                        ]
                    ),
                ),
                encoding="utf-8",
            )
        elif "fd_le_10" in phase2.witnesses:
            wit = phase2.witnesses["fd_le_10"]
            origin = wit.get("origin", 0)
            winner = inspected[origin]
            local = [tuple(a) for a in wit.get("actions") or []]
            combined_replay = replay_combined(opening, [prefix, origin_paths[origin], local])
            continuation = {
                "kind": "fd_le_10",
                "local_depth": wit.get("depth"),
                "local_cost": wit.get("local_cost"),
                "actions": [list(a) for a in local],
                "combined_replay": combined_replay,
                "workspace": workspace_on_path(sources[origin], local),
            }
            fd10_payload = continuation
            VIABLE_FD11.write_text(
                format_moves_text(
                    list(prefix) + list(origin_paths[origin]),
                    header="\n".join(
                        [
                            "# v0.14 viable min-depth fd11 origin 4925153",
                            f"# digest: {winner['digest']}",
                            f"# empties: {winner['empties']}",
                            f"# run: {winner['longest_run']}",
                            f"# legal: {winner['legal']}",
                        ]
                    ),
                ),
                encoding="utf-8",
            )
            FD10_FIXTURE.write_text(
                format_moves_text(
                    list(prefix) + list(origin_paths[origin]) + local,
                    header="\n".join(
                        [
                            "# v0.14 fd10 from min-depth fd11 portfolio 4925153",
                            f"# local_depth: {continuation['local_depth']}",
                            f"# path_length: {combined_replay.get('path_length')}",
                            f"# cost: {combined_replay.get('cost')}",
                            f"# fd: {combined_replay.get('fd')}",
                            f"# empties: {combined_replay.get('empties')}",
                        ]
                    ),
                ),
                encoding="utf-8",
            )
            print(f"WROTE {VIABLE_FD11}", flush=True)
            print(f"WROTE {FD10_FIXTURE}", flush=True)

    first_rec = next((rec for rec in inspected if rec["digest"] == first_digest), None)
    first_reaches = False
    if winner is not None:
        first_reaches = winner["digest"] == first_digest
    comparison = {
        "first_empties": [] if first_rec is None else first_rec["empties"],
        "first_run": None if first_rec is None else first_rec["longest_run"],
        "first_adj": None if first_rec is None else first_rec["adjacencies"],
        "first_blocks": None if first_rec is None else first_rec["blocks"],
        "first_legal": None if first_rec is None else first_rec["legal"],
        "winner_fd": 11 if winner else None,
        "winner_depth": 9 if winner else None,
        "winner_empties": None if winner is None else winner["empties"],
        "winner_run": None if winner is None else winner["longest_run"],
        "winner_adj": None if winner is None else winner["adjacencies"],
        "winner_blocks": None if winner is None else winner["blocks"],
        "winner_legal": None if winner is None else winner["legal"],
        "winner_reaches_fd10": bool(fd10_payload or foundation),
        "winner_local_depth": None if continuation is None else continuation.get("local_depth"),
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "preflight": preflight,
        "phase1": compact_search(phase1),
        "phase2": None if phase2_compact is None else {"search": phase2_compact},
        "candidate_count": len(inspected),
        "empty_distribution": dist,
        "empty_identities": {str(k): v for k, v in empty_ids.items()},
        "run_distribution": {str(k): v for k, v in runs.items()},
        "legal_range": None if not legal_vals else [min(legal_vals), max(legal_vals)],
        "fd10_at_depth9": fd10_at_9,
        "foundation_at_depth9": fnd_at_9,
        "first_fd11_in_set": first_digest in {r["digest"] for r in inspected},
        "first_fd11_reaches_fd10": first_reaches if (fd10_payload or foundation) else False,
        "winner": winner,
        "continuation": continuation,
        "fd10": fd10_payload,
        "foundation": foundation,
        "comparison": comparison,
        "candidates_path": str(CANDIDATES.relative_to(ROOT)).replace("\\", "/"),
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. candidates={len(inspected)} complete={phase1.collected_complete} "
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
