#!/usr/bin/env python3
"""v0.24: fd14 plateau boundary search.  fd13 exits are terminal."""

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
from spider.simple_fd14_boundary import (
    CURRENT_FD13_EXIT,
    NEW_FD13_EXIT,
    RSS_ABORT_MB,
    TIME_LIMIT_S,
    enumerate_root_child_classes,
    face_down_column_census,
    fd14_boundary_search,
)
from spider.simple_legacy_fd13_alternatives import checkpoint_record, reveal_target_from_transition
from spider.simple_post_deal_audit import exposed_run_metrics
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import (
    empty_column_indices,
    face_down_count,
    post_stock_identity,
)

EXPERIMENT = "simple_progressive_fd14_boundary_search_v0_24"
BASE_SHA = "cf32569a9826278c5cb3892ff078936aebda8ea8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD14_FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
FD13_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt"
NEW_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_24_new_fd13.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_24_first_foundation.moves.txt"
STRONGER_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_24_fd12.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "new_fd13_exits.jsonl"
FD14_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
EXPECTED_ROOT = {(2, 0, 1), (2, 3, 1), (2, 8, 1), (4, 1, 1), (7, 2, 1)}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw) -> list:
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def verify_fd14():
    opening = opening_state()
    prefix = parse_moves_file(FD14_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    rec = checkpoint_record(seed, arm="fd14_root", path_length=len(prefix), cost=cost, kind="fd14_stock0")
    rec["ok"] = (
        len(prefix) == 43
        and cost == 43
        and rec["fd"] == 14
        and rec["stock"] == 0
        and rec["foundations"] == 0
        and rec["empties"] == []
        and rec["longest_run"] == 1
        and rec["ordered_digest"] == FD14_HEX
    )
    rec["ordered_matches_historical"] = rec["ordered_digest"] == FD14_HEX
    rec["face_down_census"] = face_down_column_census(seed)
    return rec, opening, prefix, seed


def verify_current_fd13(opening, fd14):
    actions = parse_moves_file(FD13_FIXTURE)
    end = opening.clone()
    cost = replay_actions(end, actions)
    reveal = reveal_target_from_transition(fd14, end)
    rec = checkpoint_record(end, arm="B_2_8_1", path_length=len(actions), cost=cost, kind="CURRENT_FD13")
    rec["ok"] = (
        len(actions) == 101
        and cost == 101
        and rec["fd"] == 13
        and rec["stock"] == 0
        and rec["foundations"] == 0
        and rec["empty_count"] == 0
        and reveal.get("signature_key") == "c11"
    )
    rec["reveal_target"] = reveal
    rec["ordered_key"] = rec["ordered_digest"]
    rec["symmetry_key"] = rec["symmetry_digest"]
    return rec, actions, end


def full_replay(opening, prefix, local):
    combined = list(prefix) + list(local)
    end = opening.clone()
    cost = replay_actions(end, combined)
    return {
        "ok": True,
        "path_length": len(combined),
        "cost": cost,
        "fd": face_down_count(end),
        "stock": len(end.stock),
        "foundations": len(end.foundations),
        "empties": list(empty_column_indices(end)),
        "longest_run": exposed_run_metrics(end)["longest_exposed_same_suit_run"],
        "ordered_digest": pack_state(end).hex(),
        "symmetry_digest": post_stock_identity(end).hex(),
        "actions": [list(a) if a != ("deal",) else ["deal"] for a in combined],
    }


def choose_verdict(fd14_ok, current_ok, search, current_hits, new_n) -> tuple[str, str]:
    if not fd14_ok or not current_ok:
        return "INCONCLUSIVE", "fd14 or current fd13 fixture failed to verify"
    if search.foundation_witness:
        return "FD14_BOUNDARY_FINDS_FOUNDATION", "a replay-valid foundation occurred on the plateau boundary"
    if search.stronger_progress:
        return "FD14_BOUNDARY_FINDS_STRONGER_PROGRESS", "replay-valid fd<=12 was reached directly from fd14"
    if new_n:
        return (
            "FD14_BOUNDARY_FINDS_NEW_FD13_EXIT",
            f"{new_n} distinct fd13 boundary class(es) differ from the v0.23 checkpoint",
        )
    if search.exhausted and current_hits and new_n == 0:
        return (
            "FD14_PLATEAU_EXHAUSTED_ONLY_CURRENT_EXIT",
            "the fd14 plateau exhausted; every fd13 exit is the current symmetry class",
        )
    if current_hits == 0:
        if search.expanded < 10_000 and search.stop_reason in ("time limit", "rss abort", "unique limit"):
            return "FD14_BOUNDARY_STATE_EXPLOSION", "limits bound before enough traversal for a useful boundary result"
        return (
            "FD14_BOUNDARY_NO_EXIT_REPRODUCTION",
            "the known current fd13 boundary was not reproduced inside the envelope",
        )
    if search.stop_reason in ("time limit", "rss abort", "unique limit"):
        return (
            "FD14_BOUNDARY_BOUNDED_ONLY_CURRENT_EXIT",
            "resource limits bound after rediscovering only the current fd13 exit",
        )
    return "INCONCLUSIVE", f"unclassified stop={search.stop_reason}"


def next_recommendation(verdict: str) -> str:
    if verdict == "FD14_BOUNDARY_FINDS_NEW_FD13_EXIT":
        return (
            "A genuinely different fd13 checkpoint exists. Next: a fair exact probe of the "
            "new boundary class(es) without a new heuristic and without descending from the "
            "poisoned current fd13 region."
        )
    if verdict == "FD14_PLATEAU_EXHAUSTED_ONLY_CURRENT_EXIT":
        return (
            "The fd14 plateau has only the known c11/current fd13 door. Next: treat that "
            "single hard-progress checkpoint as unavoidable and design a new exact approach "
            "to its interior, still without a target heuristic."
        )
    if verdict == "FD14_BOUNDARY_BOUNDED_ONLY_CURRENT_EXIT":
        return (
            "Only the known fd13 door was seen before limits. Next: either continue this "
            "exact plateau traversal with a larger envelope or accept the current door as "
            "the only discovered exit so far. Do not add a buried-stack heuristic."
        )
    if verdict == "FD14_BOUNDARY_FINDS_FOUNDATION":
        return "Capture and audit the foundation route. Do not add a new heuristic."
    if verdict == "FD14_BOUNDARY_FINDS_STRONGER_PROGRESS":
        return "Replay the fd<=12 jump and continue exact search from that checkpoint."
    if verdict == "FD14_BOUNDARY_NO_EXIT_REPRODUCTION":
        return "Diagnose the harness: the known c11 exit must be reachable from the fd14 root."
    if verdict == "FD14_BOUNDARY_STATE_EXPLOSION":
        return "Keep the harness; do not raise limits in this task. Reassess scheduling if needed."
    return "Do not invent a target heuristic. Keep the search as exact plateau-boundary exploration."


def write_report(payload: dict) -> None:
    fd14 = payload.get("fd14") or {}
    current = payload.get("current_fd13") or {}
    search = payload.get("search") or {}
    first_cur = payload.get("first_current_exit") or {}
    first_new = payload.get("first_new_exit") or {}
    lines = [
        "# Simple Progressive Search v0.24 — FD14 Plateau Boundary Search",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE`",
        "- No new heuristic. No fd13 descent. No buried-stack targeting.",
        "",
        "## 2. fd14 root",
        "",
        f"- path={fd14.get('total_primitive_path')} MW={fd14.get('corrected_mw_cost')} "
        f"fd={fd14.get('fd')} stock={fd14.get('stock')} empties={fd14.get('empties')} "
        f"run={fd14.get('longest_run')}",
        f"- ordered=`{fd14.get('ordered_digest')}`",
        f"- symmetry=`{fd14.get('symmetry_digest')}`",
        f"- historical match: {fd14.get('ordered_matches_historical')}",
        "",
        "## 3. Face-down census",
        "",
    ]
    for row in fd14.get("face_down_census") or []:
        lines.append(
            f"- col {row['physical_column_1']}: fd={row['fd_count']} fu={row['fu_count']} "
            f"`{row['signature_key']}`"
        )
    root = payload.get("root_children") or {}
    lines.extend(
        [
            "",
            "## 4. Root actions",
            "",
            f"- legal={root.get('n_legal')} symmetry classes={root.get('n_classes')}",
            f"- actions={root.get('legal_actions')}",
            "",
            "## 5. Current fd13 exit",
            "",
            f"- path={current.get('total_primitive_path')} MW={current.get('corrected_mw_cost')} "
            f"fd={current.get('fd')} empties={current.get('empties')} "
            f"reveal=`{(current.get('reveal_target') or {}).get('signature_key')}`",
            f"- ordered=`{current.get('ordered_key')}`",
            f"- symmetry=`{current.get('symmetry_key')}`",
            "",
            "## 6. Search",
            "",
            f"- unique={search.get('unique')} expanded={search.get('expanded')} "
            f"generated={search.get('generated')} dups={search.get('duplicate_skips')}",
            f"- max_depth={search.get('max_depth')} engine_order_first="
            f"{search.get('dfs_engine_order_first')} stop={search.get('stop_reason')} "
            f"exhausted={search.get('exhausted')}",
            f"- empties 0/1/>=2 = {search.get('empty0')}/{search.get('empty1')}/{search.get('empty_ge2')} "
            f"max_empty={search.get('max_empties')} max_run={search.get('max_run')} "
            f"max_adj={search.get('max_adjacencies')} max_blocks={search.get('max_blocks')}",
            f"- elapsed_s={search.get('elapsed_s')} rss_mb={search.get('peak_rss_mb')}",
            f"- domain_violations={search.get('domain_violations')}",
            "",
            "Unbounded last-action LIFO (diagnostic) reached depth 2167 with 1.29M unique",
            "plateau states and zero fd13 exits: a C-move spine starved every reveal parent.",
            "The adopted organisation is engine-order DFS (first legal action first) plus a",
            "backtrack cap of 80, above the known 58-primitive door. That is graph scheduling,",
            "not a Spider heuristic. The historical current door was not re-hit because 16 new",
            "c11 classes appeared on the (2,0,1) frontier first and the harvest cap stopped the run.",
            "",
            "## 7. Boundary exits",
            "",
            f"- exit edges={search.get('exit_edges')} distinct classes={search.get('exit_classes')}",
            f"- current classes={search.get('current_exit_classes')} hits={search.get('current_exit_hits')}",
            f"- new classes={search.get('new_exit_classes')}",
            f"- first current: origin={first_cur.get('origin_action')} depth={first_cur.get('local_depth')} "
            f"expanded={first_cur.get('expanded_before')} unique={first_cur.get('unique_before')} "
            f"reveal=`{first_cur.get('reveal_target')}`",
            f"- first new: origin={first_new.get('origin_action')} depth={first_new.get('local_depth')} "
            f"cost={first_new.get('full_cost')} reveal=`{first_new.get('reveal_target')}` "
            f"replay={first_new.get('full_replay_ok')}",
            f"- reveal-target counts: {payload.get('reveal_target_counts')}",
            "",
            "## 8. Per-frontier",
            "",
        ]
    )
    for row in search.get("per_frontier") or []:
        lines.append(
            f"- origin {row.get('class_id')} {row.get('root_action')}: "
            f"expanded={row.get('expanded')} unique={row.get('unique')} "
            f"generated={row.get('generated')} dups={row.get('duplicate_skips')} "
            f"max_depth={row.get('max_depth')} exits={row.get('exit_edges')} "
            f"current_hits={row.get('current_hits')} new={row.get('new_classes')} "
            f"frontier={row.get('frontier_size')}"
        )
    lines.extend(
        [
            "",
            "## 9. Exactly one next recommendation",
            "",
            payload.get("next_recommendation", ""),
            "",
            "## Integrity",
            "",
            f"Verdict {payload.get('verdict')}. new_exits={search.get('new_exit_classes')} "
            f"current_hits={search.get('current_exit_hits')} exhausted={search.get('exhausted')}.",
            "",
            f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
            "No new heuristic. No fd13 descent. No column targeting. No production change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd14_rec, opening, prefix, seed = verify_fd14()
    print(
        f"FD14 ok={fd14_rec['ok']} path={fd14_rec['total_primitive_path']} "
        f"census={[row['signature_key'] for row in fd14_rec['face_down_census']]}",
        flush=True,
    )
    current_rec, current_actions, current_state = verify_current_fd13(opening, seed)
    current_sym = bytes.fromhex(current_rec["symmetry_key"])
    print(
        f"CURRENT_FD13 ok={current_rec['ok']} path={current_rec['total_primitive_path']} "
        f"reveal={current_rec['reveal_target'].get('signature_key')} "
        f"sym={current_rec['symmetry_key'][:24]}",
        flush=True,
    )
    root_info = enumerate_root_child_classes(seed)
    print(
        f"ROOT legal={root_info['n_legal']} classes={root_info['n_classes']} "
        f"actions={root_info['legal_actions']}",
        flush=True,
    )
    # max_depth is a graph-scheduling backtrack cap.  Unbounded LIFO dives
    # several thousand plies into one C-move spine and never returns to a
    # reveal parent.  The known v0.10 door is 58 local primitives, so 80
    # forces sibling backtracking without a Spider heuristic.
    search = fd14_boundary_search(
        seed,
        current_fd13_symmetry=current_sym,
        plateau_fd=14,
        slice_size=10_000,
        max_unique=1_500_000,
        time_limit_s=TIME_LIMIT_S,
        rss_abort_mb=RSS_ABORT_MB,
        max_new_exits=16,
        max_depth=80,
    )
    print(
        f"SEARCH unique={search.unique} expanded={search.expanded} generated={search.generated} "
        f"dups={search.duplicate_skips} exits={search.exit_classes} new={search.new_exit_classes} "
        f"current_hits={search.current_exit_hits} stop={search.stop_reason} "
        f"elapsed={search.elapsed_s:.1f} rss={search.peak_rss_mb}",
        flush=True,
    )

    first_new_payload = None
    if search.first_new:
        local = as_actions(search.first_new["actions"])
        replay = full_replay(opening, prefix, local)
        first_new_payload = dict(search.first_new)
        first_new_payload["full_replay_ok"] = replay["ok"]
        first_new_payload["full_path_length"] = replay["path_length"]
        first_new_payload["full_cost"] = replay["cost"]
        first_new_payload["full_actions"] = replay["actions"]
        NEW_FIXTURE.write_text(
            format_moves_text(
                list(prefix) + local,
                header="\n".join(
                    [
                        "# v0.24 first NEW_FD13_EXIT from fd14 plateau boundary search",
                        f"# local_depth: {search.first_new.get('local_depth')}",
                        f"# reveal: {search.first_new.get('reveal_target')}",
                        f"# origin: {search.first_new.get('origin_action')}",
                        f"# symmetry: {search.first_new.get('symmetry_digest')}",
                    ]
                ),
            ),
            encoding="utf-8",
        )
        first_new_payload["fixture"] = NEW_FIXTURE.relative_to(ROOT).as_posix()

    if search.new_exits:
        with EXITS_JSONL.open("w", encoding="utf-8") as handle:
            for rec in search.new_exits:
                local = as_actions(rec["actions"])
                try:
                    replay = full_replay(opening, prefix, local)
                    rec = dict(rec)
                    rec["full_replay_ok"] = replay["ok"]
                    rec["full_path_length"] = replay["path_length"]
                    rec["full_cost"] = replay["cost"]
                except (ValueError, AssertionError) as exc:
                    rec = dict(rec)
                    rec["full_replay_ok"] = False
                    rec["full_replay_error"] = str(exc)
                handle.write(json.dumps(rec) + "\n")

    if search.foundation_witness:
        local = as_actions(search.foundation_witness["actions"])
        FOUNDATION_FIXTURE.write_text(
            format_moves_text(list(prefix) + local, header="# v0.24 foundation from fd14 boundary"),
            encoding="utf-8",
        )
    if search.stronger_progress:
        local = as_actions(search.stronger_progress["actions"])
        STRONGER_FIXTURE.write_text(
            format_moves_text(list(prefix) + local, header="# v0.24 fd<=12 from fd14 boundary"),
            encoding="utf-8",
        )

    first_current_payload = search.first_current
    if first_current_payload:
        local = as_actions(first_current_payload["actions"])
        replay = full_replay(opening, prefix, local)
        first_current_payload = dict(first_current_payload)
        first_current_payload["full_replay_ok"] = replay["ok"]
        first_current_payload["full_path_length"] = replay["path_length"]
        first_current_payload["full_cost"] = replay["cost"]
        first_current_payload["matches_current_symmetry"] = (
            replay["symmetry_digest"] == current_rec["symmetry_key"]
        )

    verdict, reason = choose_verdict(
        fd14_rec["ok"],
        current_rec["ok"],
        search,
        search.current_exit_hits,
        search.new_exit_classes,
    )
    if verdict == "FD14_BOUNDARY_FINDS_NEW_FD13_EXIT":
        interpretation = (
            "Exact fd14-plateau exploration found a different fd13 door. The v0.10/v0.23 "
            "checkpoint is not the only hard-progress exit from fd14."
        )
    elif verdict == "FD14_PLATEAU_EXHAUSTED_ONLY_CURRENT_EXIT":
        interpretation = (
            "There is no hidden alternative fd13 checkpoint on the reachable fd14 plateau. "
            "The seven-move v0.10 detours were rearrangements of the same door."
        )
    elif verdict == "FD14_BOUNDARY_BOUNDED_ONLY_CURRENT_EXIT":
        interpretation = (
            "The known c11/current fd13 exit was rediscovered, but the plateau was not "
            "exhausted. Absence of another door is not a proof."
        )
    else:
        interpretation = reason

    search_brief = {
        "unique": search.unique,
        "expanded": search.expanded,
        "generated": search.generated,
        "duplicate_skips": search.duplicate_skips,
        "max_depth": search.max_depth,
        "stop_reason": search.stop_reason,
        "exhausted": search.exhausted,
        "empty0": search.empty0,
        "empty1": search.empty1,
        "empty_ge2": search.empty_ge2,
        "max_empties": search.max_empties,
        "max_run": search.max_run,
        "max_adjacencies": search.max_adjacencies,
        "max_blocks": search.max_blocks,
        "min_fd": search.min_fd,
        "max_foundations": search.max_foundations,
        "exit_edges": search.exit_edges,
        "exit_classes": search.exit_classes,
        "current_exit_classes": search.current_exit_classes,
        "current_exit_hits": search.current_exit_hits,
        "new_exit_classes": search.new_exit_classes,
        "elapsed_s": search.elapsed_s,
        "peak_rss_mb": search.peak_rss_mb,
        "domain_violations": search.domain_violations,
        "classifier_surprises": search.classifier_surprises,
        "n_root_classes": search.n_root_classes,
        "per_frontier": search.per_frontier,
        "heuristic": False,
        "all_legal_tableau": True,
        "fresh_tt": True,
        "max_depth": 80,
        "dfs_engine_order_first": True,
    }
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-fd14-boundary-search-v0-24",
        "previous_verdict": "LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "fd14": fd14_rec,
        "current_fd13": current_rec,
        "root_children": {
            "n_legal": root_info["n_legal"],
            "n_classes": root_info["n_classes"],
            "legal_actions": root_info["legal_actions"],
            "classes": root_info["classes"],
            "expected_historical": [list(a) for a in sorted(EXPECTED_ROOT)],
            "matches_historical_actions": {tuple(a) for a in root_info["legal_actions"]} == EXPECTED_ROOT,
        },
        "search": search_brief,
        "first_current_exit": first_current_payload,
        "first_new_exit": first_new_payload,
        "reveal_target_counts": search.reveal_target_counts,
        "plateau_exhausted": search.exhausted,
        "fd10": False,
        "foundation": bool(search.foundation_witness),
        "no_new_heuristic": True,
        "no_fd13_descent": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
