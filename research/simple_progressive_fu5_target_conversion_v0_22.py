#!/usr/bin/env python3
"""v0.22: FU5 target-conversion audit.  No new heuristic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_target_clearance import (
    census_buried_targets,
    face_down_signature,
    signature_key,
    target_block_count,
    target_conversion_bfs,
    target_face_up_count,
    target_stack_audit,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    face_down_count,
    first_empty_use_on_path,
    layered_reachability,
    post_stock_identity,
    stock0_tableau_classifier_complete,
)

EXPERIMENT = "simple_progressive_fu5_target_conversion_v0_22"
BASE_SHA = "830b4d01a66c07974a6fe7c4941e86941d1c52e8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD13_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
V21 = ROOT / "docs" / "research" / "simple_progressive_landing_aware_target_v0_21.json"
DEAD_CACHE = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
)
FU5_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_22_col1_fu5_seed.moves.txt"
REVEAL_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_22_col1_target_reveal.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_22_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_22_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
COL1_KEY = "c10,d12,c6,s8"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def inspect(state: SpiderState) -> dict:
    return {
        "fd": face_down_count(state),
        "stock": len(state.stock),
        "foundations": len(state.foundations),
        "empties": list(empty_column_indices(state)),
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": post_stock_identity(state).hex(),
    }


def replay_full(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        for action in part:
            combined.append(("deal",) if action in (("deal",), ["deal"]) else tuple(action))
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in combined],
            **inspect(end),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined), "full_actions": []}


def load_dead_fd12() -> set[str]:
    if not DEAD_CACHE.exists():
        return set()
    out = set()
    for line in DEAD_CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("fd") == 12:
            out.add(rec["symmetry_digest"])
    return out


def earliest_fu5(payload: dict) -> dict:
    records = [r for r in (payload.get("records") or []) if r.get("target_fu") == 5]
    if not records:
        raise ValueError("no FU5 record in v0.21 report")
    return min(records, key=lambda r: (int(r.get("depth", 10**9)), int(r.get("unique", 10**9))))


def workspace(root: SpiderState, actions: list) -> dict:
    first = first_empty_use_on_path(root, actions)
    seq = [list(empty_column_indices(root))]
    events: list[str] = []
    state = root.clone()
    for action in actions:
        before = empty_column_indices(state)
        dest_was_empty = source_became = False
        if action != ("deal",):
            src, dst, k = action
            dest_was_empty = state.columns[dst].is_empty()
            source_became = k == len(state.columns[src].face_up) and not state.columns[src].face_down
        apply_action(state, action)
        after = empty_column_indices(state)
        seq.append(list(after))
        events.extend(
            empty_transition_events(before, after, dest_was_empty=dest_was_empty, source_became_empty=source_became)
        )
    return {
        "start_empties": seq[0],
        "end_empties": seq[-1],
        "empty_sequence": seq,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "second_empty": events.count("SECOND_EMPTY"),
        "first_empty_use": first,
        "empties_before_reveal": seq[-2] if len(seq) >= 2 else seq[0],
        "empties_after_reveal": seq[-1],
        "max_simultaneous": max(len(row) for row in seq),
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("reproduction_failed"):
        return "FU5_REPRODUCTION_FAILED", "the v0.21 FU5 checkpoint cannot be reconstructed exactly"
    if payload.get("foundation"):
        return "FU5_LOCAL_REACHES_FOUNDATION", "a foundation is reached from the FU5 checkpoint"
    if payload.get("fd10"):
        return "FU5_LOCAL_REVEAL_REACHES_FD10", "target reveal occurs and downstream reaches fd10"
    outside = payload.get("outside_known_dead") or 0
    known = payload.get("known_dead_exits") or 0
    if outside > 0:
        return (
            "FU5_LOCAL_REVEALS_TARGET_NEW_REGION",
            "target is revealed into at least one fd12 class outside the known-dead cache",
        )
    if known > 0:
        return (
            "FU5_LOCAL_REVEALS_TARGET_KNOWN_DEAD_ONLY",
            "target is revealed, but all minimum-depth target exits are already certified dead",
        )
    search = payload.get("search") or {}
    if search.get("stop_reason") in ("unique limit", "time limit", "rss abort") and search.get("completed_expanded_depth", -1) < 4:
        return "FU5_LOCAL_STATE_EXPLOSION", "resource limits prevent a useful shallow conclusion"
    min_fu = search.get("min_target_fu")
    if min_fu is not None and min_fu < 5:
        return "FU5_LOCAL_BREAKS_TO_FU4_OR_LOWER", "fair search improves below FU5 but does not complete the target reveal"
    return "FU5_LOCAL_NO_CLEARANCE_PROGRESS", "no target FU below 5 and no reveal inside the completed shallow envelope"


def next_recommendation(verdict: str) -> str:
    if verdict in ("FU5_LOCAL_REACHES_FOUNDATION", "FU5_LOCAL_REVEAL_REACHES_FD10", "FU5_LOCAL_REVEALS_TARGET_NEW_REGION"):
        return (
            "The FU5 checkpoint converts. Next: restart the reveal ratchet from that fd12; "
            "do not add another heuristic."
        )
    if verdict == "FU5_LOCAL_REVEALS_TARGET_KNOWN_DEAD_ONLY":
        return (
            "FU5 converts only into already-dead fd12 classes. Next: stop this target-clearance "
            "line and backtrack to an earlier hard-progress state; do not add another heuristic."
        )
    if verdict in ("FU5_LOCAL_BREAKS_TO_FU4_OR_LOWER", "FU5_LOCAL_NO_CLEARANCE_PROGRESS"):
        return (
            "FU5 does not convert under fair shallow search. Next: stop this target-clearance "
            "line and recommend backtracking to an earlier hard-progress state. Do not add another heuristic."
        )
    if verdict == "FU5_LOCAL_STATE_EXPLOSION":
        return "Do not raise limits. Report the bounded FU5 envelope and stop this line."
    if verdict == "FU5_REPRODUCTION_FAILED":
        return "Reproduce the v0.21 FU5 checkpoint before any further target-clearance work."
    return "Reproduce the FU5 conversion audit before changing target policy."


def write_report(payload: dict) -> None:
    s = payload.get("search") or {}
    fu5 = payload.get("fu5") or {}
    lines = [
        "# Simple Progressive Search v0.22: FU5 Target-Conversion Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "No new heuristic. Landing-aware search is used only to harvest the FU5 checkpoint.",
        "Phase 1 is fair primitive-depth BFS. Production identity is unchanged. Column 7 was not tested.",
        "",
        "## 2. FU5 checkpoint",
        "",
        f"- replay_ok={fu5.get('replay_ok')} local_depth={fu5.get('local_depth')} "
        f"total_path={fu5.get('path_length')} cost={fu5.get('cost')} "
        f"fd={fu5.get('fd')} empties={fu5.get('empties')} target_fu={fu5.get('target_fu')} "
        f"blocks={fu5.get('block_count')} top={fu5.get('top_block_head')} "
        f"face_up={fu5.get('face_up')}",
        f"- ordered=`{fu5.get('ordered_digest')}`",
        f"- symmetry=`{fu5.get('symmetry_digest')}`",
        "",
        "## 3. Fair BFS from FU5",
        "",
        f"- stop={s.get('stop_reason')} unique={s.get('unique')} generated={s.get('generated')} "
        f"dups={s.get('duplicate_skips')} expanded={s.get('completed_expanded_depth')} "
        f"generated_depth={s.get('completed_generated_depth')} elapsed={s.get('elapsed_s')} "
        f"rss={s.get('peak_rss_mb')}",
        f"- min_fu={s.get('min_target_fu')} min_blocks={s.get('min_block_count')} min_fd={s.get('min_fd')}",
        f"- reveal={payload.get('target_reveal')} reveal_depth={s.get('reveal_depth')} "
        f"target_exits={payload.get('target_exit_classes')} known_dead={payload.get('known_dead_exits')} "
        f"outside={payload.get('outside_known_dead')} off_target={payload.get('off_target_exits')}",
        "",
        "| Depth | Frontier | Unique | min FU | FU5 | FU4 | FU3 | empty0 | empty1 | target exits |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in s.get("layers") or []:
        lines.append(
            f"| {row.get('depth')} | {row.get('frontier_size')} | {row.get('cumulative_unique')} | "
            f"{row.get('min_target_fu')} | {row.get('states_fu5')} | {row.get('states_fu4')} | "
            f"{row.get('states_fu3')} | {row.get('states_empty_0')} | {row.get('states_empty_1')} | "
            f"{row.get('target_exits')} |"
        )
    lines.extend(["", "## 4. Downstream", ""])
    d = payload.get("downstream")
    if not d:
        lines.append(f"- skipped: {payload.get('downstream_skip')}")
    else:
        lines.append(
            f"- sources={d.get('source_count')} unique={d.get('unique')} stop={d.get('stop_reason')} "
            f"min_fd={d.get('min_fd')} fnd={d.get('max_foundations')}"
        )
    lines.extend(
        [
            "",
            "## 5. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "No new heuristic. No column-7 arm. No production change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    prefix = parse_moves_file(FD13_FIXTURE)
    fd13 = opening.clone()
    cost13 = replay_actions(fd13, prefix)
    if pack_state(fd13).hex() != FD13_HEX or len(prefix) != 102 or cost13 != 102:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "fd13 fixture failed"}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print("FD13_OK True", flush=True)
    sig = face_down_signature(fd13.columns[0])
    assert signature_key(sig) == COL1_KEY

    v21 = json.loads(V21.read_text(encoding="utf-8"))
    rec = earliest_fu5(v21)
    local = [tuple(a) for a in rec["actions"]]
    fu5 = opening.clone()
    reproduction_failed = False
    try:
        cost = replay_actions(fu5, prefix + local)
    except (ValueError, AssertionError):
        reproduction_failed = True
        cost = None
    audit = None
    if not reproduction_failed:
        audit = target_stack_audit(fu5, sig)
        reproduction_failed = not (
            face_down_count(fu5) == 13
            and len(fu5.stock) == 0
            and len(fu5.foundations) == 0
            and target_face_up_count(fu5, sig) == 5
            and target_block_count(fu5, sig) == 5
            and audit.get("top_block_head") == 1
        )
    print(f"FU5_REPLAY failed={reproduction_failed} depth={len(local)} fu={None if reproduction_failed else target_face_up_count(fu5, sig)}", flush=True)
    if reproduction_failed:
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "reproduction_failed": True,
            "verdict": "FU5_REPRODUCTION_FAILED",
            "note": "the v0.21 FU5 checkpoint cannot be reconstructed exactly",
        }
        payload["next_recommendation"] = next_recommendation("FU5_REPRODUCTION_FAILED")
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT FU5_REPRODUCTION_FAILED", flush=True)
        return 1

    FU5_FIXTURE.write_text(
        format_moves_text(prefix + local, header="# v0.22 column-1 FU5 seed from v0.21 record\n"),
        encoding="utf-8",
    )
    fu5_info = {
        "replay_ok": True,
        "local_depth": len(local),
        "path_length": len(prefix) + len(local),
        "cost": cost,
        "target_fu": 5,
        "block_count": audit["block_count"],
        "top_block_head": audit["top_block_head"],
        "face_up": audit["face_up"],
        "blocks": audit["blocks"],
        "legal_destinations": audit["legal_destinations"],
        "landing_obstruction": audit["landing_obstruction"],
        **inspect(fu5),
    }
    print(f"FU5_OK empties={fu5_info['empties']} face_up={fu5_info['face_up']}", flush=True)
    print(f"CLASSIFIER {stock0_tableau_classifier_complete(fu5)['complete']}", flush=True)

    print("PHASE1 fair BFS from FU5", flush=True)
    result = target_conversion_bfs(
        fu5,
        sig,
        plateau_fd=13,
        max_depth=16,
        max_unique=1_000_000,
        time_limit_s=1200.0,
        rss_abort_mb=3 * 1024.0,
        checkpoints=(4, 8, 12, 16),
    )
    print(
        f"PHASE1 unique={result.unique} stop={result.stop_reason} min_fu={result.min_target_fu} "
        f"exits={len(result.target_exits)} expanded={result.completed_expanded_depth} elapsed={result.elapsed_s:.1f}",
        flush=True,
    )

    dead = load_dead_fd12()
    known = [e for e in result.target_exits if e["symmetry_digest"] in dead]
    outside = [e for e in result.target_exits if e["symmetry_digest"] not in dead]
    for e in result.target_exits:
        e["class"] = "KNOWN_DEAD_EXIT" if e["symmetry_digest"] in dead else "OUTSIDE_KNOWN_DEAD"
    for e in result.off_target_exits:
        e["class"] = "KNOWN_DEAD_EXIT" if e["symmetry_digest"] in dead else "OUTSIDE_KNOWN_DEAD"

    first_exit = None
    if result.target_exits:
        best = min(result.target_exits, key=lambda e: e["depth"])
        first_exit = {**best, **replay_full(opening, [prefix, local, [tuple(a) for a in best["actions"]]])}
        if first_exit.get("ok"):
            REVEAL_FIXTURE.write_text(
                format_moves_text(
                    prefix + local + [tuple(a) for a in best["actions"]],
                    header="# v0.22 column-1 target reveal from FU5\n",
                ),
                encoding="utf-8",
            )

    ws = None
    if first_exit and first_exit.get("ok"):
        ws = workspace(fu5, [tuple(a) for a in best["actions"]])

    fd10_payload = foundation = downstream = None
    downstream_skip = "no OUTSIDE_KNOWN_DEAD target exit"
    if outside:
        sources, origin_paths = [], []
        for e in outside:
            st = fu5.clone()
            path = [tuple(a) for a in e["actions"]]
            replay_actions(st, path)
            sources.append(st)
            origin_paths.append(path)
        print(f"PHASE2 sources={len(sources)}", flush=True)
        cont = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=10_000,
            max_unique=500_000,
            time_limit_s=600.0,
            rss_abort_mb=2 * 1024.0,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            stop_fd=10,
            checkpoints=(8, 12, 16),
        )
        downstream = {
            "source_count": cont.source_count,
            "unique": cont.unique,
            "stop_reason": cont.stop_reason,
            "min_fd": cont.min_fd,
            "max_foundations": cont.max_foundations,
            "elapsed_s": cont.elapsed_s,
            "peak_rss_mb": cont.peak_rss_mb,
        }
        downstream_skip = None
        if "foundation" in cont.witnesses:
            w = cont.witnesses["foundation"]
            origin = w.get("origin") or 0
            foundation = {**w, **replay_full(opening, [prefix, local, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
        if "fd_le_10" in cont.witnesses:
            w = cont.witnesses["fd_le_10"]
            origin = w.get("origin") or 0
            fd10_payload = {**w, **replay_full(opening, [prefix, local, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
        print(f"PHASE2 unique={cont.unique} stop={cont.stop_reason} min_fd={cont.min_fd}", flush=True)

    if fd10_payload and fd10_payload.get("ok"):
        FD10_FIXTURE.write_text(
            format_moves_text([tuple(a) if a != ["deal"] else ("deal",) for a in fd10_payload["full_actions"]], header="# v0.22 fd10\n"),
            encoding="utf-8",
        )
    if foundation and foundation.get("ok"):
        FOUNDATION_FIXTURE.write_text(
            format_moves_text([tuple(a) if a != ["deal"] else ("deal",) for a in foundation["full_actions"]], header="# v0.22 foundation\n"),
            encoding="utf-8",
        )

    fu_depths = {str(k): v.get("depth") for k, v in result.fu_records.items()}
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "reproduction_failed": False,
        "fu5": fu5_info,
        "search": {
            "unique": result.unique,
            "generated": result.generated,
            "duplicate_skips": result.duplicate_skips,
            "completed_expanded_depth": result.completed_expanded_depth,
            "completed_generated_depth": result.completed_generated_depth,
            "stop_reason": result.stop_reason,
            "min_target_fu": result.min_target_fu,
            "min_block_count": result.min_block_count,
            "min_fd": result.min_fd,
            "reveal_depth": result.reveal_depth,
            "elapsed_s": result.elapsed_s,
            "peak_rss_mb": result.peak_rss_mb,
            "layers": result.layers,
            "expansion_order": result.expansion_order,
            "fu_record_depths": fu_depths,
        },
        "fu_records": result.fu_records,
        "target_reveal": bool(result.target_exits),
        "target_exit_classes": len(result.target_exits),
        "known_dead_exits": len(known),
        "outside_known_dead": len(outside),
        "off_target_exits": len(result.off_target_exits),
        "first_target_exit": first_exit,
        "workspace": ws,
        "downstream": downstream,
        "downstream_skip": downstream_skip,
        "fd10": bool(fd10_payload and fd10_payload.get("ok")),
        "foundation": bool(foundation and foundation.get("ok")),
        "fd10_witness": fd10_payload,
        "foundation_witness": foundation,
        "production_unchanged": True,
        "column7_tested": False,
        "new_heuristic": False,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. FU5 depth={len(local)} min_fu={result.min_target_fu} "
        f"reveal={bool(result.target_exits)} known={len(known)} outside={len(outside)}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
