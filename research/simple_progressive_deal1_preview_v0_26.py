#!/usr/bin/env python3
"""v0.26: perfect-information Deal-1 preview.  No Deal heuristic.  No Deal 2."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_deal1_preview import (
    DEAL_NOW,
    PREPARE_THEN_DEAL,
    classify_timing,
    next_stock_row,
    snapshot_metrics,
    stock_rows,
    tableau_layer_bfs,
    virtual_deal_candidates,
)
from spider.simple_legacy_fd13_alternatives import reveal_target_from_transition
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import face_down_count

EXPERIMENT = "simple_progressive_deal1_preview_v0_26"
BASE_SHA = "f66d3f861c3e27b368b26872bd504e057cbcf05a"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
BEFORE_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_26_before_deal1_fd13.moves.txt"
PREPARED_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_26_prepared_deal1_fd13.moves.txt"
DEAL_NOW_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_26_deal_now_fd13.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_26_first_foundation.moves.txt"


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


def choose_verdict(d1_ok, control_ok, pre, deal_now, prepared, explosion) -> tuple[str, str]:
    if not d1_ok or not control_ok:
        return "REPRODUCTION_FAILURE", "D1 root or immediate-Deal control could not be reproduced"
    if explosion:
        return "DEAL1_PREVIEW_STATE_EXPLOSION", "resource limits bound before a useful Deal-1 comparison"
    if pre:
        return (
            "HARD_PROGRESS_AVAILABLE_BEFORE_DEAL1",
            "tableau-only play reached fd13/foundation before Deal 1",
        )
    if prepared and deal_now:
        return (
            "DEAL1_PREPARATION_AND_DEAL_NOW_BOTH_PROGRESS",
            "both Deal-now and prepare-then-Deal reached hard progress in the envelope",
        )
    if prepared and not deal_now:
        return (
            "DEAL1_PREPARATION_BEATS_DEAL_NOW",
            "preparation before Deal 1 found hard progress that Deal-now did not",
        )
    if deal_now and not prepared:
        return (
            "DEAL_NOW_ONLY_SHORT_PROGRESS",
            "only immediate Deal 1 reached hard progress inside the envelope",
        )
    return (
        "NO_DEAL1_TIMING_SIGNAL_IN_ENVELOPE",
        "neither Deal-now nor bounded preparation reached fd13/foundation",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "HARD_PROGRESS_AVAILABLE_BEFORE_DEAL1":
        return (
            "The historical five-Deal burst discarded available tableau hard progress. "
            "Next: keep the pre-Deal fd13 witness and do not dump stock rows until that "
            "progress is used. Do not add a Deal heuristic."
        )
    if verdict == "DEAL1_PREPARATION_BEATS_DEAL_NOW":
        return (
            "DEAL TIMING MATTERS: perfect-information receiving-position search found a "
            "better Deal-1 moment than the historical immediate Deal. Next: treat Deal 1 "
            "as a previewed commitment from prepared candidates. Do not inspect Deal 2 yet."
        )
    if verdict == "DEAL1_PREPARATION_AND_DEAL_NOW_BOTH_PROGRESS":
        return (
            "Both timings reach hard progress. Compare the resulting fd13 classes before "
            "inspecting Deal 2. Do not add a Deal score."
        )
    if verdict == "DEAL_NOW_ONLY_SHORT_PROGRESS":
        return (
            "Immediate Deal 1 is the only short hard-progress timing in this envelope. "
            "That is bounded evidence, not a policy. Next: a deeper preparation envelope "
            "or Deal-2 isolation. Do not add a Deal heuristic."
        )
    if verdict == "NO_DEAL1_TIMING_SIGNAL_IN_ENVELOPE":
        return (
            "No better Deal-1 timing was demonstrated inside depth 8+8. Do not conclude "
            "Deal-now is optimal. Next: a larger pre-Deal envelope or isolate Deal 2. "
            "Do not add a Deal heuristic."
        )
    if verdict == "REPRODUCTION_FAILURE":
        return "Reconstruct the 38-move D1 root and historical Deal-1 child before any preview."
    return "Do not invent a Deal heuristic. Keep Deal-1 preview as exact virtual-Deal search."


def write_report(payload: dict) -> None:
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2") or {}
    p3 = payload.get("phase3") or {}
    d1 = payload.get("d1") or {}
    lines = [
        "# Simple Progressive Search v0.26 — Perfect-Information Deal-1 Preview",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- No Deal heuristic. No Deal 2. No fd13 descent.",
        "",
        "## 2. D1 root",
        "",
        f"- path={d1.get('path')} fd={d1.get('fd')} stock_rows={d1.get('stock_rows')} "
        f"foundations={d1.get('foundations')} empties={d1.get('empties')} "
        f"legal_tableau={d1.get('legal_tableau')} deal_legal={d1.get('deal_legal')}",
        f"- ordered=`{d1.get('ordered_digest')}`",
        f"- incoming row={d1.get('incoming_row')}",
        f"- control Deal-1 child match: {payload.get('control_ok')}",
        "",
        "## 3. Phase 1 — pre-Deal candidates",
        "",
        f"- unique={p1.get('unique')} expanded={p1.get('expanded')} generated={p1.get('generated')} "
        f"dups={p1.get('duplicate_skips')}",
        f"- completed_expanded={p1.get('completed_expanded_depth')} generated_depth={p1.get('completed_generated_depth')} "
        f"stop={p1.get('stop_reason')}",
        f"- pre-Deal progress classes={p1.get('progress_classes')} min_fd={p1.get('min_fd')}",
        f"- elapsed_s={p1.get('elapsed_s')} rss_mb={p1.get('peak_rss_mb')}",
        "",
        "## 4. Phase 2 — virtual Deal",
        "",
        f"- candidates_dealt={p2.get('n_candidates_dealt')} distinct_children={p2.get('n_distinct_children')}",
        f"- control_post_digest match={p2.get('control_match')} root_unmutated={p2.get('root_unmutated')}",
        f"- join totals={p2.get('join_totals')}",
        "",
        "## 5. Phase 3 — post-Deal preview (no Deal 2)",
        "",
        f"- unique={p3.get('unique')} expanded={p3.get('expanded')} generated={p3.get('generated')} "
        f"dups={p3.get('duplicate_skips')}",
        f"- completed_expanded={p3.get('completed_expanded_depth')} generated_depth={p3.get('completed_generated_depth')} "
        f"stop={p3.get('stop_reason')}",
        f"- Deal-now progress={payload.get('deal_now_progress_n')} "
        f"prepared progress={payload.get('prepared_progress_n')} "
        f"distinct hard-progress classes={payload.get('hard_progress_classes')}",
        f"- best preparation depth={payload.get('best_preparation_depth')} "
        f"best post-Deal depth={payload.get('best_post_deal_depth')}",
        f"- elapsed_s={p3.get('elapsed_s')} rss_mb={p3.get('peak_rss_mb')}",
        "",
        "| Timing | Hard progress | Min pre-Deal depth | Min post-Deal depth | Classes |",
        "|---|---|---:|---:|---:|",
        f"| No Deal | {payload.get('pre_deal_hard_progress')} | n/a | n/a | {p1.get('progress_classes')} |",
        f"| Deal now | {payload.get('deal_now_hard_progress')} | 0 | {payload.get('deal_now_min_post_depth')} | {payload.get('deal_now_progress_n')} |",
        f"| Prepare then Deal | {payload.get('prepared_hard_progress')} | {payload.get('best_preparation_depth')} | {payload.get('prepared_min_post_depth')} | {payload.get('prepared_progress_n')} |",
        "",
        "## 6. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. control_ok={payload.get('control_ok')}.",
        "",
        f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
        "No Deal heuristic. No Deal 2. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def save_witness(path: Path, actions, header: str) -> None:
    path.write_text(format_moves_text(actions, header=header), encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    seed_actions = parse_moves_file(SEED)
    prefix = seed_actions[:38]
    d1 = opening.clone()
    replay_actions(d1, prefix)
    d1_snap = snapshot_metrics(d1)
    row = next_stock_row(d1)
    hist_after = opening.clone()
    replay_actions(hist_after, seed_actions[:39])
    control_child = d1.clone()
    apply_action(control_child, ("deal",))
    control_ok = pack_state(control_child) == pack_state(hist_after)
    d1_ok = (
        len(prefix) == 38
        and d1_snap["fd"] == 14
        and d1_snap["foundations"] == 0
        and d1_snap["stock_rows"] == 5
        and d1_snap["deal_legal"]
        and len(row) == 10
        and control_ok
    )
    print(
        f"D1 path=38 fd={d1_snap['fd']} stock={d1_snap['stock_rows']} "
        f"legal={d1_snap['legal_tableau']} deal={d1_snap['deal_legal']} "
        f"row={row} control_ok={control_ok}",
        flush=True,
    )
    if not d1_ok:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "REPRODUCTION_FAILURE",
            "verdict_reason": "D1 root or Deal-1 control mismatch",
            "d1": d1_snap,
            "control_ok": control_ok,
            "incoming_row": row,
        }
        _write_json(RESULT, payload)
        print("VERDICT REPRODUCTION_FAILURE", flush=True)
        return payload

    print("PHASE1 START pre-Deal tableau BFS depth_cap=8", flush=True)
    phase1 = tableau_layer_bfs(
        [d1],
        max_depth=8,
        max_unique=500_000,
        time_limit_s=600.0,
        rss_abort_mb=2 * 1024.0,
        checkpoints=(4, 8),
    )
    print(
        f"PHASE1 unique={phase1.unique} exp={phase1.expanded} gen={phase1.generated} "
        f"dups={phase1.duplicate_skips} progress={len(phase1.progress)} "
        f"stop={phase1.stop_reason} depth={phase1.completed_generated_depth} "
        f"elapsed={phase1.elapsed_s:.1f} rss={phase1.peak_rss_mb}",
        flush=True,
    )

    print("PHASE2 START virtual Deal of every candidate", flush=True)
    phase2 = virtual_deal_candidates(d1, phase1, known_row=row)
    control_match = phase2["control_post_digest"] == pack_state(hist_after).hex()
    print(
        f"PHASE2 candidates={phase2['n_candidates_dealt']} children={phase2['n_distinct_children']} "
        f"control_match={control_match} unmutated={phase2['root_unmutated']}",
        flush=True,
    )

    children = phase2["children"]
    sources = []
    origin_paths = []
    origin_meta = []
    for rec in children:
        st = unpack_state(bytes.fromhex(rec["post_ordered_digest"]))
        sources.append(st)
        origin_paths.append(list(prefix) + as_actions(rec["pre_actions"]) + [("deal",)])
        origin_meta.append(rec)

    print(f"PHASE3 START post-Deal portfolio sources={len(sources)} no Deal 2", flush=True)
    phase3 = tableau_layer_bfs(
        sources,
        origin_paths=origin_paths,
        max_depth=8,
        max_unique=750_000,
        time_limit_s=900.0,
        rss_abort_mb=3 * 1024.0,
        checkpoints=(4, 8),
    )
    print(
        f"PHASE3 unique={phase3.unique} exp={phase3.expanded} gen={phase3.generated} "
        f"dups={phase3.duplicate_skips} progress={len(phase3.progress)} "
        f"stop={phase3.stop_reason} depth={phase3.completed_generated_depth} "
        f"elapsed={phase3.elapsed_s:.1f} rss={phase3.peak_rss_mb}",
        flush=True,
    )

    deal_now_prog = []
    prepared_prog = []
    reveal_counts = {}
    for rec in phase3.progress:
        origin = rec["origin"]
        meta = origin_meta[origin]
        timing = classify_timing(meta["pre_depth"])
        rec = dict(rec)
        rec["timing"] = timing
        rec["pre_depth"] = meta["pre_depth"]
        rec["is_deal_now"] = meta["is_deal_now"]
        rec["total_local_depth"] = meta["pre_depth"] + 1 + rec["depth"]
        full = list(origin_paths[origin]) + as_actions(rec["actions"])
        rec["full_path_length"] = len(full)
        rec["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        end = opening.clone()
        try:
            rec["full_cost"] = replay_actions(end, full)
            rec["full_replay_ok"] = True
            rec["reveal_target"] = reveal_target_from_transition(d1, end).get("signature_key")
        except (ValueError, AssertionError) as exc:
            rec["full_replay_ok"] = False
            rec["full_replay_error"] = str(exc)
            rec["reveal_target"] = None
        reveal_counts[rec["reveal_target"] or ""] = reveal_counts.get(rec["reveal_target"] or "", 0) + 1
        if timing == DEAL_NOW:
            deal_now_prog.append(rec)
        else:
            prepared_prog.append(rec)

    pre_deal_prog = []
    for rec in phase1.progress:
        rec = dict(rec)
        rec["timing"] = "BEFORE_DEAL"
        full = list(prefix) + as_actions(rec["actions"])
        rec["full_path_length"] = len(full)
        rec["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        end = opening.clone()
        try:
            rec["full_cost"] = replay_actions(end, full)
            rec["full_replay_ok"] = True
        except (ValueError, AssertionError) as exc:
            rec["full_replay_ok"] = False
            rec["full_replay_error"] = str(exc)
        pre_deal_prog.append(rec)

    if pre_deal_prog:
        best = min(pre_deal_prog, key=lambda r: r["depth"])
        save_witness(
            BEFORE_FIXTURE,
            as_actions(best["full_actions"]),
            "# v0.26 tableau-only fd13 before Deal 1",
        )
        best["fixture"] = BEFORE_FIXTURE.relative_to(ROOT).as_posix()
    if prepared_prog:
        best = min(prepared_prog, key=lambda r: (r["pre_depth"], r["depth"]))
        save_witness(
            PREPARED_FIXTURE,
            as_actions(best["full_actions"]),
            "# v0.26 prepare-then-Deal-1 fd13",
        )
        best["fixture"] = PREPARED_FIXTURE.relative_to(ROOT).as_posix()
    if deal_now_prog:
        best = min(deal_now_prog, key=lambda r: r["depth"])
        save_witness(
            DEAL_NOW_FIXTURE,
            as_actions(best["full_actions"]),
            "# v0.26 Deal-now fd13 after Deal 1",
        )
        best["fixture"] = DEAL_NOW_FIXTURE.relative_to(ROOT).as_posix()

    explosion = (
        phase1.stop_reason in ("unique limit", "time limit", "rss abort")
        and phase1.completed_expanded_depth < 4
    ) or (
        phase3.stop_reason in ("unique limit", "time limit", "rss abort")
        and phase3.completed_expanded_depth < 2
        and not (deal_now_prog or prepared_prog or pre_deal_prog)
    )
    verdict, reason = choose_verdict(
        True,
        control_match,
        bool(pre_deal_prog),
        bool(deal_now_prog),
        bool(prepared_prog),
        explosion,
    )
    if verdict == "HARD_PROGRESS_AVAILABLE_BEFORE_DEAL1":
        interpretation = "The historical Deal 1 was taken while tableau-only hard progress was already available."
    elif verdict == "DEAL1_PREPARATION_BEATS_DEAL_NOW":
        interpretation = "DEAL TIMING MATTERS. Perfect-information receiving-position search beat Deal-now."
    elif verdict == "NO_DEAL1_TIMING_SIGNAL_IN_ENVELOPE":
        interpretation = "No better Deal-1 timing was demonstrated inside this envelope. That is not proof Deal-now is optimal."
    else:
        interpretation = reason

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-deal1-preview-v0-26",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "d1": {**d1_snap, "path": 38, "incoming_row": [list(c) for c in row]},
        "control_ok": control_match,
        "incoming_row": [list(c) for c in row],
        "phase1": {
            "unique": phase1.unique,
            "expanded": phase1.expanded,
            "generated": phase1.generated,
            "duplicate_skips": phase1.duplicate_skips,
            "completed_expanded_depth": phase1.completed_expanded_depth,
            "completed_generated_depth": phase1.completed_generated_depth,
            "stop_reason": phase1.stop_reason,
            "min_fd": phase1.min_fd,
            "max_foundations": phase1.max_foundations,
            "progress_classes": len(phase1.progress),
            "elapsed_s": phase1.elapsed_s,
            "peak_rss_mb": phase1.peak_rss_mb,
            "deal_expanded": False,
        },
        "phase2": {
            "n_candidates_dealt": phase2["n_candidates_dealt"],
            "n_distinct_children": phase2["n_distinct_children"],
            "control_post_digest": phase2["control_post_digest"],
            "control_match": control_match,
            "root_unmutated": phase2["root_unmutated"],
            "join_totals": phase2["join_totals"],
        },
        "phase3": {
            "unique": phase3.unique,
            "expanded": phase3.expanded,
            "generated": phase3.generated,
            "duplicate_skips": phase3.duplicate_skips,
            "completed_expanded_depth": phase3.completed_expanded_depth,
            "completed_generated_depth": phase3.completed_generated_depth,
            "stop_reason": phase3.stop_reason,
            "min_fd": phase3.min_fd,
            "progress_classes": len(phase3.progress),
            "elapsed_s": phase3.elapsed_s,
            "peak_rss_mb": phase3.peak_rss_mb,
            "deal_expanded": False,
            "source_count": phase3.source_count,
        },
        "pre_deal_hard_progress": bool(pre_deal_prog),
        "deal_now_hard_progress": bool(deal_now_prog),
        "prepared_hard_progress": bool(prepared_prog),
        "pre_deal_progress_n": len(pre_deal_prog),
        "deal_now_progress_n": len(deal_now_prog),
        "prepared_progress_n": len(prepared_prog),
        "hard_progress_classes": len(pre_deal_prog) + len(deal_now_prog) + len(prepared_prog),
        "best_preparation_depth": None if not prepared_prog else min(r["pre_depth"] for r in prepared_prog),
        "best_post_deal_depth": None
        if not (deal_now_prog or prepared_prog)
        else min(r["depth"] for r in deal_now_prog + prepared_prog),
        "deal_now_min_post_depth": None if not deal_now_prog else min(r["depth"] for r in deal_now_prog),
        "prepared_min_post_depth": None if not prepared_prog else min(r["depth"] for r in prepared_prog),
        "reveal_target_counts": reveal_counts,
        "pre_deal_progress": pre_deal_prog[:8],
        "prepared_deal_progress": prepared_prog[:8],
        "deal_now_progress": deal_now_prog[:8],
        "no_deal_heuristic": True,
        "no_deal_2": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
