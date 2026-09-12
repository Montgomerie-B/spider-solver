#!/usr/bin/env python3
"""v0.46: ratchet blockers off the unique 4S from post-SD5 3S-2S-AS states."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_sd5_spade_receiver import spade_tail_present
from spider.simple_spade_4s_ratchet import (
    COST_CEILING,
    RSS_ABORT_MB,
    STAGE_UNIQUE,
    b4_count,
    four_s_can_move,
    locate_unique_spade,
    preview_tail4,
    reconstruct_tail3_sources,
    search_b4_decrease,
    tail3_packet,
    unique_4s_exposed,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "spade_4s_access_ratchet_v0_46"
BASE_SHA = "c1776413e2082bebab01925b6626dcb8cfaeb6fe"
BRANCH = "agent/spade-4s-access-ratchet-v0-46"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOURCES = ROOT / "docs" / "research" / "spade_tail3_sources_v0_46.json"
EXPOSED = ROOT / "docs" / "research" / "spade_4s_exposed_v0_46.json"
TAIL4 = ROOT / "docs" / "research" / "spade_tail4_v0_46.json"
FOUND_FIX = ROOT / "solutions" / "4925153_v0_46_spade_foundation.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def choose_verdict(p: dict) -> tuple[str, str]:
    if p.get("uniqueness_fail"):
        return "SPADE_UNIQUENESS_CONTRACT_FAILURE", "unique remaining 4S/3S/2S/AS contract failed"
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "TAIL3 sources failed reconstruction/replay"
    if p.get("foundation_reached"):
        return "FOUNDATION2_SPADE_REACHED", "second Spade foundation auto-removed"
    if p.get("tail4_reached"):
        return "SPADE_TAIL4_REACHED", "4S-3S-2S-AS formed after 4S exposure"
    if p.get("exposed"):
        return "SPADE_4S_EXPOSED", "unique 4S became top"
    stages = p.get("ratchet") or []
    if stages and any(s.get("n") for s in stages):
        if any(s.get("stop_reason") in ("unique limit", "rss abort") for s in stages) and not p.get("exposed"):
            return "SPADE_BLOCKER_RATCHET_STATE_EXPLOSION", "B4 ratchet hit unique/RSS before exposing 4S"
        return "SPADE_BLOCKER_RATCHET_PROGRESS", "B4 decreased and boundaries persisted, 4S not yet exposed"
    if stages and all(s.get("n") == 0 for s in stages):
        return "SPADE_BLOCKER_RATCHET_STALLED", "no strict B4 reduction from the TAIL3 frontier"
    return "INCONCLUSIVE", "4S ratchet finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "FOUNDATION2_SPADE_REACHED":
        return "Persist the second Spade foundation and do not search Foundation 3."
    if verdict == "SPADE_TAIL4_REACHED":
        return "Continue the unique Spade chain from TAIL4 toward TAIL5. Do not reopen pre-Deal receiver search."
    if verdict == "SPADE_4S_EXPOSED":
        return "Unique 4S is exposed. Spend the next envelope joining 3S-2S-AS (or fragments) onto it. Do not reopen pre-Deal prep."
    if verdict == "SPADE_BLOCKER_RATCHET_PROGRESS":
        return "Keep the lower-B4 boundary portfolio and continue the 4S access ratchet. Do not search TAIL4 directly."
    if verdict == "SPADE_BLOCKER_RATCHET_STALLED":
        return "No B4 reduction from 3S-2S-AS. Inspect top-blocker landings (4H/5S/10D/TAIL3). Do not reopen pre-Deal prep."
    if verdict == "SPADE_BLOCKER_RATCHET_STATE_EXPLOSION":
        return "Ratchet exploded before exposing 4S. Continue from the cheapest lower-B4 boundaries only. Do not flood UCS."
    return "Keep the unique-4S blocker ratchet. Do not search TAIL4 directly from buried 4S."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.46 — Spade 4S Access Ratchet",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "",
        "## 2. Source audit",
        "",
        "```json",
        json.dumps(payload.get("sources"), indent=2)[:3500],
        "```",
        "",
        "## 3. Ratchet",
        "",
        "```json",
        json.dumps(payload.get("ratchet"), indent=2)[:4000],
        "```",
        "",
        "## 4. Exposure / TAIL4 / foundation / bottleneck",
        "",
        "```json",
        json.dumps(
            {
                "exposure": payload.get("exposure"),
                "tail4": payload.get("tail4"),
                "foundation": payload.get("foundation"),
                "bottleneck": payload.get("bottleneck"),
            },
            indent=2,
        )[:3500],
        "```",
        "",
        "## 5. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "TAIL3 sources only. No pre-Deal prep enlargement. B4 is not canonical identity. L3 admits all tableau moves. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    from spider.simple_diamond_c_bridge import opening_state as _open

    opening = _open()
    started = time.perf_counter()
    global_deadline = started + 450.0
    print("RECONSTRUCT TAIL3", flush=True)
    bundle = reconstruct_tail3_sources(opening)
    print(
        f"TAIL3 raw={bundle['raw_tail3']} unique={bundle['symmetry_unique']} timing={bundle['timing']} "
        f"b4={bundle['b4_dist']} uniq_fail={bundle['uniqueness_fail']}",
        flush=True,
    )
    slim_states = [
        {
            "g": r["g"],
            "timing": r["timing"],
            "prep_depth": r["prep_depth"],
            "lineages": r["lineages"],
            "ordered_digest": r["ordered_digest"],
            "symmetry_digest": r["symmetry_digest"],
            "full_actions": r["full_actions"],
            "b4": r["b4"],
            "signature": r["signature"],
            "column_1": r["column_1"],
            "tail3_above_4s": r["tail3_above_4s"],
        }
        for r in bundle["states"]
    ]
    _write_json(
        SOURCES,
        {
            "experiment": EXPERIMENT,
            "raw_tail3": bundle["raw_tail3"],
            "n": bundle["symmetry_unique"],
            "timing": bundle["timing"],
            "cost_counts": bundle["cost_counts"],
            "b4_dist": bundle["b4_dist"],
            "signatures": bundle["signatures"],
            "states": slim_states,
        },
    )
    sources = slim_states
    stages = []
    exposed_rows = []
    foundation_reached = False
    surprise_path = None
    stage_i = 0
    while sources and time.perf_counter() < global_deadline:
        if all(r["b4"] <= 0 for r in sources):
            break
        remaining = global_deadline - time.perf_counter()
        if remaining < 15:
            break
        live = [r for r in sources if r["b4"] > 0]
        if not live:
            break
        budget = min(120.0, remaining - 10.0)
        print(f"STAGE {stage_i} n={len(live)} b4={dict(Counter(r['b4'] for r in live))} budget={budget:.0f}s", flush=True)
        res = search_b4_decrease(
            live,
            opening,
            max_unique=STAGE_UNIQUE,
            time_limit_s=budget,
            rss_abort_mb=RSS_ABORT_MB,
            cost_ceiling=COST_CEILING,
        )
        rebuilt = []
        for rec in res.witnesses:
            src = live[rec["origin"]]
            full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
            end = opening.clone()
            cost = replay_actions(end, full)
            b_after = 0 if rec.get("foundation") else b4_count(end)
            rebuilt.append(
                {
                    **rec,
                    "full_cost": cost,
                    "full_actions": dump_actions(full),
                    "full_replay_ok": cost == rec["g"] and stock_rows(end) == 0,
                    "ordered_digest": pack_state(end).hex(),
                    "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                    "b4": b_after,
                    "exposed": unique_4s_exposed(end),
                    "tail3": bool(tail3_packet(end)),
                    "four_can_move": four_s_can_move(end),
                    "fd": face_down_count(end),
                    "empties": list(empty_column_indices(end)),
                    "timing": src.get("timing"),
                    "lineages": src.get("lineages"),
                    "b4_before": src.get("b4"),
                    "signature": list(locate_unique_spade(end, 4)["above"]) if locate_unique_spade(end, 4) else [],
                }
            )
        rebuilt.sort(key=lambda w: (w["b4"], w["full_cost"], w.get("origin", 0)))
        by_b = Counter(w["b4"] for w in rebuilt)
        labels = Counter(w.get("label") for w in rebuilt)
        stage_rec = {
            "stage": stage_i,
            "n": len(rebuilt),
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "duplicate_skips": res.duplicate_skips,
            "elapsed_s": res.elapsed_s,
            "peak_rss_mb": res.peak_rss_mb,
            "stop_reason": res.stop_reason,
            "first_s": res.first_s,
            "first_g": res.first_g,
            "first_b4": res.first_b4,
            "achieved_b4": dict(by_b),
            "labels": dict(labels),
            "tail3_preserved": sum(1 for w in rebuilt if w.get("tail3")),
            "tail3_split": sum(1 for w in rebuilt if not w.get("tail3")),
        }
        stages.append(stage_rec)
        print(f"STAGE {stage_i} n={len(rebuilt)} b4={dict(by_b)} labels={dict(labels)} stop={res.stop_reason}", flush=True)
        for b, rows in _group(rebuilt):
            path = ROOT / "docs" / "research" / f"spade_4s_blockers_{b}_v0_46.json"
            _write_json(
                path,
                {"experiment": EXPERIMENT, "b4": b, "n": len(rows), "states": rows},
            )
        if res.foundation_surprise:
            foundation_reached = True
            hit = next((w for w in rebuilt if w.get("foundation")), None)
            if hit:
                surprise_path = hit["full_actions"]
            break
        exp = [w for w in rebuilt if w.get("exposed") or w["b4"] == 0]
        if exp:
            exposed_rows.extend(exp)
        nxt = [w for w in rebuilt if w["b4"] > 0]
        if not nxt and not exp:
            break
        sources = nxt
        stage_i += 1
        if not nxt:
            break
        if res.stop_reason in ("unique limit", "rss abort") and not exp:
            break

    if exposed_rows:
        _write_json(
            EXPOSED,
            {
                "experiment": EXPERIMENT,
                "n": len(exposed_rows),
                "cheapest": min(w["full_cost"] for w in exposed_rows),
                "states": exposed_rows,
            },
        )
    preview_counts = Counter()
    tail4_rows = []
    if exposed_rows and time.perf_counter() < global_deadline:
        print(f"PREVIEW TAIL4 n={len(exposed_rows)}", flush=True)
        for rec in exposed_rows:
            end = opening.clone()
            replay_actions(end, as_actions(rec["full_actions"]))
            pr = preview_tail4(end, rec["full_cost"], max_depth=6, deadline=min(global_deadline, time.perf_counter() + 1.5))
            rec["preview"] = pr["status"]
            preview_counts[pr["status"]] += 1
            if pr.get("foundation"):
                foundation_reached = True
                if surprise_path is None:
                    surprise_path = rec["full_actions"]
            if pr["status"] in ("TAIL4_IMMEDIATE", "TAIL4_WITHIN_6") or rec.get("preview") == "TAIL4_IMMEDIATE":
                tail4_rows.append({**rec, "preview": pr["status"], "preview_g": (pr.get("hit") or {}).get("g")})
    if tail4_rows:
        _write_json(TAIL4, {"experiment": EXPERIMENT, "n": len(tail4_rows), "states": tail4_rows})
    fixture = None
    if foundation_reached and surprise_path:
        FOUND_FIX.write_text(
            format_moves_text(as_actions(surprise_path), header="# v0.46 second Spade foundation surprise\n"),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()
    bottleneck = None
    if bundle["signatures"]:
        bottleneck = {"dominant_source_signature": list(bundle["signatures"].items())[0] if bundle["signatures"] else None}
    if stages:
        bottleneck = {
            "source_signatures": bundle["signatures"],
            "stage0_labels": stages[0].get("labels"),
            "achieved": [s.get("achieved_b4") for s in stages],
        }
    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "uniqueness_fail": bundle["uniqueness_fail"] > 0,
        "foundation_reached": foundation_reached,
        "tail4_reached": bool(tail4_rows),
        "exposed": bool(exposed_rows),
        "ratchet": stages,
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. TAIL3 raw={bundle['raw_tail3']} unique={bundle['symmetry_unique']} "
        f"timing={bundle['timing']} initial B4={bundle['b4_dist']}. Stages={len(stages)}. "
        f"Exposed={len(exposed_rows)} TAIL4={len(tail4_rows)}. No pre-Deal prep enlargement."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "sources": {
            "raw_tail3": bundle["raw_tail3"],
            "symmetry_unique": bundle["symmetry_unique"],
            "timing": bundle["timing"],
            "cost_counts": bundle["cost_counts"],
            "b4_dist": bundle["b4_dist"],
            "signatures": bundle["signatures"],
            "all_replay_ok": bundle["all_replay_ok"],
            "uniqueness_fail": bundle["uniqueness_fail"],
        },
        "ratchet": stages,
        "exposure": {
            "reached": bool(exposed_rows),
            "n": len(exposed_rows),
            "cheapest": None if not exposed_rows else min(w["full_cost"] for w in exposed_rows),
        },
        "tail4": {
            "preview": dict(preview_counts),
            "n": len(tail4_rows),
            "cheapest": None if not tail4_rows else min(w.get("preview_g") or w["full_cost"] for w in tail4_rows),
        },
        "foundation": {"reached": foundation_reached, "fixture": fixture},
        "bottleneck": bottleneck,
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "sources": SOURCES.relative_to(ROOT).as_posix(),
            "exposed": EXPOSED.relative_to(ROOT).as_posix() if EXPOSED.exists() else None,
            "tail4": TAIL4.relative_to(ROOT).as_posix() if TAIL4.exists() else None,
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": bundle["all_replay_ok"],
        "uniqueness_fail": bundle["uniqueness_fail"] > 0,
        "foundation_reached": foundation_reached,
        "tail4_reached": bool(tail4_rows),
        "exposed": bool(exposed_rows),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


def _group(rows):
    by = {}
    for r in rows:
        by.setdefault(r["b4"], []).append(r)
    return sorted(by.items())


if __name__ == "__main__":
    main()
