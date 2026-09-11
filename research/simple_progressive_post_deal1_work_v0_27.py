#!/usr/bin/env python3
"""v0.27: tableau-only work after prepared Deal 1.  No Deal 2.  No heuristic."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, permute_tableau_columns
from spider.simple_deal1_preview import stock_rows, tableau_layer_bfs
from spider.simple_legacy_fd13_alternatives import checkpoint_record, reveal_target_from_transition
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import face_down_count

EXPERIMENT = "simple_progressive_post_deal1_work_v0_27"
BASE_SHA = "2d9fdbb9b337c59a15d9fc595b809d66d81e3ebc"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
V26 = ROOT / "docs" / "research" / "simple_progressive_deal1_preview_v0_26.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_27_fd12.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_27_first_foundation.moves.txt"
EXPECTED_REVEAL = "c10,d12,c6,s8"


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


def choose_verdict(audit_ok, search) -> tuple[str, str]:
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the v0.26 prepared portfolio could not be reconstructed"
    if search.max_foundations >= 1:
        return "POST_DEAL1_WORK_REACHES_FOUNDATION", "tableau-only play reached a foundation before Deal 2"
    if search.min_fd <= 12 and search.progress:
        return "POST_DEAL1_WORK_REACHES_FD12", "tableau-only play reached fd12 before Deal 2"
    if search.stop_reason == "frontier empty":
        return (
            "POST_DEAL1_FD13_REGION_EXHAUSTED",
            "the exact fd13 tableau-only graph from these sources exhausted without fd12",
        )
    if search.stop_reason in ("unique limit", "time limit", "rss abort"):
        return "POST_DEAL1_WORK_STATE_EXPLOSION", "resource limits bound before hard progress or exact closure"
    return "INCONCLUSIVE", f"unclassified stop={search.stop_reason}"


def next_recommendation(verdict: str) -> str:
    if verdict == "POST_DEAL1_WORK_REACHES_FD12":
        return (
            "Keep working the tableau: prepared Deal 1 still has hard progress before Deal 2. "
            "Do not preview Deal 2 until this fd12 line is used. Do not add a heuristic."
        )
    if verdict == "POST_DEAL1_WORK_REACHES_FOUNDATION":
        return "Capture the foundation route. Do not take Deal 2. Do not add a heuristic."
    if verdict == "POST_DEAL1_FD13_REGION_EXHAUSTED":
        return (
            "The no-Deal fd13 opportunity space from these sources is closed. Next: a "
            "perfect-information Deal-2 preview over that closed set. Do not add a heuristic."
        )
    if verdict == "POST_DEAL1_WORK_STATE_EXPLOSION":
        return (
            "The fd13 tableau graph is large. Keep the harness; do not raise limits here and "
            "do not preview Deal 2 until a completed layer or exact closure exists."
        )
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.26 prepared fd13 witnesses before any further work."
    return "Do not inspect Deal 2. Keep exact tableau-only search after prepared Deal 1."


def write_report(payload: dict) -> None:
    search = payload.get("search") or {}
    lines = [
        "# Simple Progressive Search v0.27 — Post-Deal-1 Work-Completion Boundary Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `DEAL1_PREPARATION_BEATS_DEAL_NOW`",
        "- No Deal 2. No heuristic. Ordered pack_state while stock remains.",
        "",
        "## 2. Source audit",
        "",
        f"- prepared sources={payload.get('n_prepared')} distinct ordered={payload.get('n_distinct_sources')} "
        f"path_range={payload.get('source_path_range')} MW_range={payload.get('source_mw_range')}",
        f"- stock_rows=4 fd=13 foundations=0 reveal=`{EXPECTED_REVEAL}`",
        "",
        "## 3. Search",
        "",
        f"- unique={search.get('unique')} expanded={search.get('expanded')} generated={search.get('generated')} "
        f"dups={search.get('duplicate_skips')} cross_origin={search.get('cross_origin_dups')}",
        f"- max_depth={search.get('completed_generated_depth')} expanded_depth={search.get('completed_expanded_depth')} "
        f"stop={search.get('stop_reason')} exhausted={search.get('exhausted')}",
        f"- min_fd={search.get('min_fd')} fnd={search.get('max_foundations')} "
        f"progress_classes={search.get('progress_classes')} progress_edges={search.get('progress_edges')}",
        f"- elapsed_s={search.get('elapsed_s')} rss_mb={search.get('peak_rss_mb')}",
        "",
        "## 4. fd12 / foundation",
        "",
        f"- fd12={payload.get('fd12')} min_local_depth={payload.get('min_fd12_local_depth')} "
        f"min_total_path={payload.get('min_fd12_total_path')} min_cost={payload.get('min_fd12_cost')}",
        f"- stock_at_fd12={payload.get('stock_at_fd12')} fd12_classes={payload.get('fd12_classes')}",
        f"- reveal_targets={payload.get('reveal_target_counts')} foundation={payload.get('foundation')}",
        "",
        "## 5. Closure telemetry",
        "",
        json.dumps(payload.get("closure") or {}, indent=2),
        "",
        "## 6. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. fd12={payload.get('fd12')} exhausted={search.get('exhausted')}.",
        "",
        f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
        "No Deal 2. No heuristic. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    seed_actions = parse_moves_file(SEED)
    d1 = opening.clone()
    replay_actions(d1, seed_actions[:38])
    v26 = json.loads(V26.read_text(encoding="utf-8"))
    records = v26.get("prepared_deal_progress") or []
    if len(records) != 8:
        raise SystemExit(f"expected 8 prepared_deal_progress records, got {len(records)}")
    audited = []
    distinct = {}
    origin_paths = []
    sources = []
    for index, rec in enumerate(records):
        full = as_actions(rec.get("full_actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        deals = sum(1 for a in full if a == ("deal",))
        reveal = reveal_target_from_transition(d1, end)
        cp = checkpoint_record(end, arm=f"v026_{index}", path_length=len(full), cost=cost, kind="PREPARED_FD13")
        ok = (
            cp["fd"] == 13
            and cp["foundations"] == 0
            and stock_rows(end) == 4
            and deals == 1
            and reveal.get("signature_key") == EXPECTED_REVEAL
            and pack_state(end).hex() == rec["ordered_digest"]
        )
        swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
        ordered_sensitive = pack_state(end) != pack_state(swapped)
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "total_primitive_path": len(full),
                "mw_cost": cost,
                "deals": deals,
                "fd": cp["fd"],
                "stock_rows": stock_rows(end),
                "foundations": cp["foundations"],
                "empties": cp["empties"],
                "legal_tableau": cp["legal_action_count"],
                "longest_run": cp["longest_run"],
                "adjacencies": cp["adjacencies"],
                "movable_blocks": cp["movable_blocks"],
                "ordered_digest": cp["ordered_digest"],
                "reveal_target": reveal.get("signature_key"),
                "ordered_identity_sensitive_to_column_perm": ordered_sensitive,
                "full_actions": rec.get("full_actions"),
            }
        )
        print(
            f"SOURCE {index} ok={ok} path={len(full)} MW={cost} legal={cp['legal_action_count']} "
            f"empty={cp['empties']} reveal={reveal.get('signature_key')}",
            flush=True,
        )
        digest = pack_state(end)
        if digest not in distinct:
            distinct[digest] = index
            sources.append(end)
            origin_paths.append(full)
    audit_ok = all(row["ok"] for row in audited) and bool(sources)
    if not audit_ok:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "SOURCE_REPLAY_FAILURE",
            "sources": audited,
            "n_prepared": len(records),
            "n_distinct_sources": len(sources),
        }
        _write_json(RESULT, payload)
        print("VERDICT SOURCE_REPLAY_FAILURE", flush=True)
        return payload

    paths = [row["total_primitive_path"] for row in audited]
    costs = [row["mw_cost"] for row in audited]
    print(
        f"SOURCES prepared={len(records)} distinct={len(sources)} path={min(paths)}-{max(paths)}",
        flush=True,
    )
    print("SEARCH START tableau-only fd13 plateau no Deal 2", flush=True)
    search = tableau_layer_bfs(
        sources,
        origin_paths=origin_paths,
        max_depth=10_000,
        max_unique=1_500_000,
        time_limit_s=1800.0,
        rss_abort_mb=3 * 1024.0,
        checkpoints=(8, 16, 24, 32, 48, 64),
        stop_after_progress_layer=True,
        require_stock_rows=4,
    )
    print(
        f"SEARCH unique={search.unique} exp={search.expanded} gen={search.generated} "
        f"dups={search.duplicate_skips} cross={search.cross_origin_dups} "
        f"progress={len(search.progress)} min_fd={search.min_fd} stop={search.stop_reason} "
        f"depth={search.completed_generated_depth} elapsed={search.elapsed_s:.1f} rss={search.peak_rss_mb}",
        flush=True,
    )

    fd12_rows = []
    reveal_counts = {}
    for rec in search.progress:
        origin = rec["origin"]
        full = list(origin_paths[origin]) + [tuple(a) for a in rec["actions"]]
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
            replay_ok = True
        except (ValueError, AssertionError) as exc:
            cost = None
            replay_ok = False
            rec["replay_error"] = str(exc)
        reveal = reveal_target_from_transition(sources[origin], end) if replay_ok else {}
        key = reveal.get("signature_key") or ""
        reveal_counts[key] = reveal_counts.get(key, 0) + 1
        item = dict(rec)
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = replay_ok
        item["reveal_target"] = key
        item["deals"] = sum(1 for a in full if a == ("deal",))
        fd12_rows.append(item)

    first = None
    if fd12_rows:
        first = min(fd12_rows, key=lambda r: (r["depth"], r.get("origin", 0)))
        origin = first["origin"]
        full = list(origin_paths[origin]) + [tuple(a) for a in first["actions"]]
        FD12_FIXTURE.write_text(
            format_moves_text(
                full,
                header="\n".join(
                    [
                        "# v0.27 tableau-only fd12 after prepared Deal 1",
                        f"# source_id: {origin}",
                        f"# local_depth: {first['depth']}",
                        f"# stock_rows: {first.get('stock_rows')}",
                    ]
                ),
            ),
            encoding="utf-8",
        )
        first["fixture"] = FD12_FIXTURE.relative_to(ROOT).as_posix()

    if search.max_foundations >= 1:
        fnd = min((r for r in fd12_rows if r.get("foundations", 0) >= 1), key=lambda r: r["depth"], default=None)
        if fnd:
            origin = fnd["origin"]
            full = list(origin_paths[origin]) + [tuple(a) for a in fnd["actions"]]
            FOUNDATION_FIXTURE.write_text(
                format_moves_text(full, header="# v0.27 foundation after prepared Deal 1"),
                encoding="utf-8",
            )

    exhausted = search.stop_reason == "frontier empty"
    closure = {
        "exhausted": exhausted,
        "unique": search.unique,
        "max_depth": search.completed_generated_depth,
        "empty0": search.empty0,
        "empty1": search.empty1,
        "empty_ge2": search.empty_ge2,
        "max_run": search.max_run,
        "max_adjacencies": search.max_adjacencies,
        "max_blocks": search.max_blocks,
        "zero_legal_tableau": search.zero_legal_tableau,
        "legal_count_hist": {str(k): v for k, v in sorted(search.legal_count_hist.items())},
    }
    verdict, reason = choose_verdict(True, search)
    if verdict == "POST_DEAL1_WORK_REACHES_FD12":
        interpretation = (
            "Prepared Deal 1 still has tableau-only hard progress before Deal 2. "
            "Keep working the resulting tableau."
        )
    elif verdict == "POST_DEAL1_FD13_REGION_EXHAUSTED":
        interpretation = (
            "These prepared Deal-1 fd13 states have no further tableau-only fd12. "
            "The closed set is the exact Deal-2 candidate space."
        )
    else:
        interpretation = reason

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-post-deal1-work-v0-27",
        "previous_verdict": "DEAL1_PREPARATION_BEATS_DEAL_NOW",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "n_prepared": len(records),
        "n_distinct_sources": len(sources),
        "source_path_range": f"{min(paths)}-{max(paths)}" if len(set(paths)) > 1 else str(paths[0]),
        "source_mw_range": f"{min(costs)}-{max(costs)}" if len(set(costs)) > 1 else str(costs[0]),
        "sources": audited,
        "search": {
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "cross_origin_dups": search.cross_origin_dups,
            "unique_sources": search.unique_sources,
            "completed_expanded_depth": search.completed_expanded_depth,
            "completed_generated_depth": search.completed_generated_depth,
            "stop_reason": search.stop_reason,
            "exhausted": exhausted,
            "min_fd": search.min_fd,
            "max_foundations": search.max_foundations,
            "progress_classes": len(search.progress),
            "progress_edges": search.progress_edges,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "deal_expanded": False,
            "identity": "pack_state",
        },
        "fd12": bool(fd12_rows) and search.min_fd <= 12,
        "min_fd12_local_depth": None if not fd12_rows else min(r["depth"] for r in fd12_rows),
        "min_fd12_total_path": None if not first else first.get("full_path_length"),
        "min_fd12_cost": None if not first else first.get("full_cost"),
        "stock_at_fd12": None if not first else first.get("stock_rows"),
        "fd12_classes": len(fd12_rows),
        "reveal_target_counts": reveal_counts,
        "foundation": search.max_foundations >= 1,
        "first_fd12": first,
        "fd12_exits": fd12_rows,
        "closure": closure,
        "no_deal_2": True,
        "no_post_stock_symmetry": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
