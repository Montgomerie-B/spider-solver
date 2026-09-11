#!/usr/bin/env python3
"""v0.28: tableau-only fd12->fd11 after prepared Deal 1.  No Deal 2."""

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
from spider.simple_legacy_fd13_alternatives import (
    buried_stack_records,
    checkpoint_record,
    reveal_target_from_transition,
)
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import face_down_count

EXPERIMENT = "simple_progressive_post_deal1_fd12_v0_28"
BASE_SHA = "d1875b70cb775760c0addf41284ac5eb62ced13d"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V27 = ROOT / "docs" / "research" / "simple_progressive_post_deal1_work_v0_27.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FD11_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_fd11.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_28_first_foundation.moves.txt"


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
        return "SOURCE_REPLAY_FAILURE", "the v0.27 fd12 portfolio could not be reconstructed"
    if search.max_foundations >= 1:
        return "POST_DEAL1_FD12_REACHES_FOUNDATION", "tableau-only play reached a foundation before Deal 2"
    if search.min_fd <= 10 and search.progress:
        return "POST_DEAL1_FD12_REACHES_FD10", "tableau-only play crossed to fd10 or lower before Deal 2"
    if search.min_fd <= 11 and search.progress:
        return "POST_DEAL1_FD12_REACHES_FD11", "replay-valid fd11 is reached before Deal 2"
    if search.stop_reason == "frontier empty":
        return (
            "POST_DEAL1_FD12_REGION_EXHAUSTED",
            "the exact fd12 tableau graph exhausted without fd11/foundation",
        )
    if search.stop_reason in ("unique limit", "time limit", "rss abort"):
        return "POST_DEAL1_FD12_STATE_EXPLOSION", "resource limits bound before hard progress or exact closure"
    return "INCONCLUSIVE", f"unclassified stop={search.stop_reason}"


def next_recommendation(verdict: str) -> str:
    if verdict == "POST_DEAL1_FD12_REACHES_FD11":
        return (
            "The productive Deal-1 cascade still has another tableau reveal before Deal 2. "
            "Continue exact no-Deal search from the fd11 boundary. Do not preview Deal 2."
        )
    if verdict == "POST_DEAL1_FD12_REACHES_FD10":
        return "Unexpected fd<=10 before Deal 2. Capture it and keep working the tableau."
    if verdict == "POST_DEAL1_FD12_REACHES_FOUNDATION":
        return "Capture the foundation route. Do not take Deal 2."
    if verdict == "POST_DEAL1_FD12_REGION_EXHAUSTED":
        return (
            "The no-Deal fd12 opportunity space is closed. Next: a perfect-information "
            "Deal-2 preview over that closed set. Do not add a heuristic."
        )
    if verdict == "POST_DEAL1_FD12_STATE_EXPLOSION":
        return "Keep the harness; do not raise limits here and do not preview Deal 2 yet."
    if verdict == "SOURCE_REPLAY_FAILURE":
        return "Reconstruct the v0.27 fd12 witnesses before any further work."
    return "Do not inspect Deal 2. Keep exact tableau-only search after prepared Deal 1."


def write_report(payload: dict) -> None:
    search = payload.get("search") or {}
    lines = [
        "# Simple Progressive Search v0.28 — Post-Deal-1 FD12-to-FD11 Boundary Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `POST_DEAL1_WORK_REACHES_FD12`",
        "- No Deal 2. No heuristic. Ordered pack_state while stock remains.",
        "",
        "## 2. Source audit",
        "",
        f"- fd12 sources listed={payload.get('n_listed')} distinct ordered={payload.get('n_distinct_sources')} "
        f"replay_ok={payload.get('source_replay_ok')}",
        f"- path_range={payload.get('source_path_range')} MW_range={payload.get('source_mw_range')}",
        "- stock_rows=4 fd=12 foundations=0 exactly_one_Deal=True",
        "- identity=`pack_state` (no post-stock column symmetry)",
        "",
        "## 3. Search",
        "",
        f"- unique={search.get('unique')} expanded={search.get('expanded')} generated={search.get('generated')} "
        f"dups={search.get('duplicate_skips')} cross_origin={search.get('cross_origin_dups')}",
        f"- unique_sources={search.get('unique_sources')} max_depth={search.get('completed_generated_depth')} "
        f"expanded_depth={search.get('completed_expanded_depth')}",
        f"- stop={search.get('stop_reason')} exhausted={search.get('exhausted')}",
        f"- min_fd={search.get('min_fd')} fnd={search.get('max_foundations')} "
        f"progress_classes={search.get('progress_classes')} progress_edges={search.get('progress_edges')}",
        f"- elapsed_s={search.get('elapsed_s')} rss_mb={search.get('peak_rss_mb')}",
        "- Deal 2 engine-legal, not expanded.",
        "",
        "## 4. fd11 / stronger",
        "",
        f"- fd11={payload.get('fd11')} min_local_depth={payload.get('min_fd11_local_depth')} "
        f"min_total_path={payload.get('min_fd11_total_path')} min_cost={payload.get('min_fd11_cost')}",
        f"- stock_at_fd11={payload.get('stock_at_fd11')} fd11_classes={payload.get('fd11_classes')} "
        f"contributing_sources={payload.get('fd11_source_ids')}",
        f"- reveal_targets={payload.get('reveal_target_counts')}",
        f"- column1_chain={payload.get('column1_chain')}",
        f"- foundation={payload.get('foundation')} fd10_or_lower={payload.get('fd10_or_lower')}",
        f"- full_replay_ok={payload.get('full_replay_ok')} fixture={payload.get('fixture')}",
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
        f"Verdict {payload.get('verdict')}. fd11={payload.get('fd11')} exhausted={search.get('exhausted')}.",
        "",
        f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
        "No Deal 2. No heuristic. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    v27 = json.loads(V27.read_text(encoding="utf-8"))
    fd13_sources = v27.get("sources") or []
    exits = v27.get("fd12_exits") or []
    if len(exits) != 16:
        raise SystemExit(f"expected 16 v0.27 fd12 exits, got {len(exits)}")
    audited = []
    distinct = {}
    sources = []
    origin_paths = []
    for index, rec in enumerate(exits):
        origin = rec["origin"]
        parent_full = as_actions(fd13_sources[origin]["full_actions"])
        local = as_actions(rec["actions"])
        full = parent_full + local
        end = opening.clone()
        cost = replay_actions(end, full)
        deals = sum(1 for a in full if a == ("deal",))
        cp = checkpoint_record(end, arm=f"v027_{index}", path_length=len(full), cost=cost, kind="FD12_SOURCE")
        ok = (
            cp["fd"] == 12
            and cp["foundations"] == 0
            and stock_rows(end) == 4
            and deals == 1
            and pack_state(end).hex() == rec["ordered_digest"]
        )
        swapped = permute_tableau_columns(end, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "v27_origin": origin,
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
                "ordered_identity_sensitive_to_column_perm": pack_state(end) != pack_state(swapped),
                "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in full],
            }
        )
        print(
            f"SOURCE {index} ok={ok} path={len(full)} MW={cost} legal={cp['legal_action_count']} "
            f"empty={cp['empties']}",
            flush=True,
        )
        digest = pack_state(end)
        if digest not in distinct:
            distinct[digest] = index
            sources.append(end)
            origin_paths.append(full)
    audit_ok = all(row["ok"] for row in audited) and len(distinct) == 16
    if not audit_ok:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "SOURCE_REPLAY_FAILURE",
            "source_replay_ok": False,
            "n_listed": len(exits),
            "n_distinct_sources": len(distinct),
            "sources": audited,
        }
        _write_json(RESULT, payload)
        print("VERDICT SOURCE_REPLAY_FAILURE", flush=True)
        return payload

    paths = [row["total_primitive_path"] for row in audited]
    costs = [row["mw_cost"] for row in audited]
    print(f"SOURCES listed=16 distinct={len(sources)} path={min(paths)}-{max(paths)}", flush=True)
    print("SEARCH START tableau-only fd12 plateau no Deal 2", flush=True)
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

    fd11_rows = []
    reveal_counts = {}
    contributing = set()
    physical_counts = {}
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
        physical = reveal.get("physical_column_1_at_before")
        physical_counts[str(physical)] = physical_counts.get(str(physical), 0) + 1
        contributing.add(origin)
        item = dict(rec)
        item["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = replay_ok
        item["reveal_target"] = key
        item["reveal_physical_column_1"] = physical
        item["remaining_face_down_stacks"] = (
            [row["signature_key"] for row in buried_stack_records(end)] if replay_ok else []
        )
        item["deals"] = sum(1 for a in full if a == ("deal",))
        fd11_rows.append(item)

    first = None
    fixture = None
    if fd11_rows:
        first = min(fd11_rows, key=lambda r: (r["depth"], r.get("origin", 0)))
        origin = first["origin"]
        full = list(origin_paths[origin]) + [tuple(a) for a in first["actions"]]
        header_lines = [
            "# v0.28 tableau-only fd11 after prepared Deal 1 / fd12",
            f"# source_id: {origin}",
            f"# local_depth: {first['depth']}",
            f"# stock_rows: {first.get('stock_rows')}",
            f"# reveal_target: {first.get('reveal_target')}",
        ]
        path = FD11_FIXTURE
        if first["fd"] <= 10:
            path = FD10_FIXTURE
        if first.get("foundations", 0) >= 1:
            path = FOUNDATION_FIXTURE
        path.write_text(format_moves_text(full, header="\n".join(header_lines)), encoding="utf-8")
        fixture = path.relative_to(ROOT).as_posix()
        first["fixture"] = fixture

    continues_column1 = bool(reveal_counts) and all(
        key.startswith("c10,d12") or key == "c10" for key in reveal_counts
    )
    exhausted = search.stop_reason == "frontier empty"
    verdict, reason = choose_verdict(True, search)
    if verdict == "POST_DEAL1_FD12_REACHES_FD11":
        interpretation = (
            "The productive Deal-1 cascade still has another tableau reveal before Deal 2. "
            "This is evidence of a genuine hard-progress cascade after the timed Deal 1. "
            "It does not imply Deal 2 must wait for every remaining reveal."
        )
    elif verdict == "POST_DEAL1_FD12_REGION_EXHAUSTED":
        interpretation = (
            "These fd12 states have no further tableau-only fd11. "
            "The closed set is the first natural point at which this lineage has "
            "run out of hard-progress routes before Deal 2."
        )
    elif verdict == "POST_DEAL1_FD12_STATE_EXPLOSION":
        interpretation = (
            "Resource limits bound the exact fd12 plateau before fd11 or exhaustion. "
            "The result is bounded only."
        )
    else:
        interpretation = reason

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-post-deal1-fd12-v0-28",
        "previous_verdict": "POST_DEAL1_WORK_REACHES_FD12",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "n_listed": len(exits),
        "n_distinct_sources": len(sources),
        "source_replay_ok": True,
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
        "closure": {
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
        },
        "fd11": bool(fd11_rows) and search.min_fd <= 11,
        "min_fd11_local_depth": None if not fd11_rows else min(r["depth"] for r in fd11_rows),
        "min_fd11_total_path": None if not first else first.get("full_path_length"),
        "min_fd11_cost": None if not first else first.get("full_cost"),
        "stock_at_fd11": None if not first else first.get("stock_rows"),
        "fd11_classes": len(fd11_rows),
        "fd11_source_ids": sorted(contributing),
        "reveal_target_counts": reveal_counts,
        "reveal_physical_column_1_counts": physical_counts,
        "column1_chain": {
            "v026_reveal": "c10,d12,c6,s8",
            "v027_reveal": "c10,d12,c6",
            "continues_same_buried_stack": continues_column1,
            "multiple_reveal_target_classes": len(reveal_counts) > 1,
            "physical_column_1_counts": physical_counts,
        },
        "foundation": search.max_foundations >= 1,
        "fd10_or_lower": bool(fd11_rows) and search.min_fd <= 10,
        "full_replay_ok": bool(fd11_rows) and all(r.get("full_replay_ok") for r in fd11_rows),
        "fixture": fixture,
        "first_fd11": first,
        "fd11_exits": fd11_rows,
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
