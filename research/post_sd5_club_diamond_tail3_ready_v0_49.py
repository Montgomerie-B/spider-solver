#!/usr/bin/env python3
"""v0.49: Club vs Diamond TAIL3_READY race from all DEAL_NOW 2-A roots.

Do not search Spades, Hearts, Foundation 2/3, or rank 5+.
Do not restrict sources to the old 128-state harvests.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_club_diamond_tail3_ready import (
    COST_CEILING,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    execute_tail3_joins,
    filter_2a_sources,
    load_v044_deal_now_roots,
    one_move_scan,
    optional_tail4_join,
    preview_tail4_ready,
    search_tail3_ready,
    structural_audit,
    tail3_already,
    tail4_ready,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "post_sd5_club_diamond_reassessment_v0_49"
BASE_SHA = "45c8aa9feffb7fd559eba7286667834c9f656a66"
BRANCH = "agent/post-sd5-club-diamond-tail3-ready-v0-49"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CLUB_SRC = ROOT / "docs" / "research" / "post_sd5_club_2a_sources_v0_49.json"
DIA_SRC = ROOT / "docs" / "research" / "post_sd5_diamond_2a_sources_v0_49.json"
CLUB_READY = ROOT / "docs" / "research" / "post_sd5_club_tail3_ready_v0_49.json"
DIA_READY = ROOT / "docs" / "research" / "post_sd5_diamond_tail3_ready_v0_49.json"
CLUB_T3 = ROOT / "docs" / "research" / "post_sd5_club_tail3_v0_49.json"
DIA_T3 = ROOT / "docs" / "research" / "post_sd5_diamond_tail3_v0_49.json"
CLUB_T4 = ROOT / "docs" / "research" / "post_sd5_club_tail4_v0_49.json"
DIA_T4 = ROOT / "docs" / "research" / "post_sd5_diamond_tail4_v0_49.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim(states, extra=()):
    keys = ("g", "source_g", "full_actions", "ordered_digest", "symmetry_digest", "lineages", "obstacle", "already_ready", "already_tail3", "ready", "tail3", "join", "preview", "preview_g") + extra
    out = []
    for s in states:
        row = {k: s[k] for k in keys if k in s}
        out.append(row)
    return out


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "720 DEAL_NOW roots failed replay"
    if p.get("contract_fail"):
        return "TAIL3_READY_CONTRACT_FAILURE", "3-2-A appeared without a TAIL3_READY parent"
    if p.get("foundation2"):
        return "FOUNDATION2_SURPRISE", "a second foundation auto-removed"
    club_r = p.get("club_ready")
    dia_r = p.get("diamond_ready")
    club_exp = p.get("club_explosion")
    dia_exp = p.get("diamond_explosion")
    if (club_exp or dia_exp) and not club_r and not dia_r:
        return "CLUB_DIAMOND_REASSESSMENT_STATE_EXPLOSION", "equal envelopes exploded before TAIL3_READY"
    if not club_r and not dia_r:
        return "CLUB_DIAMOND_TAIL3_READY_NOT_FOUND", "neither suit crossed TAIL3_READY"
    club_t4 = p.get("club_t4_live")
    dia_t4 = p.get("diamond_t4_live")
    club_g = p.get("club_ready_g")
    dia_g = p.get("diamond_ready_g")
    if club_r and dia_r:
        # Do not pick on cheapest TAIL3 alone; continuation matters.
        if club_t4 and not dia_t4:
            return "CLUB_POST_SD5_TARGET_LEADS", "Club TAIL3_READY and TAIL4-ready preview stays live; Diamond does not"
        if dia_t4 and not club_t4:
            return "DIAMOND_POST_SD5_TARGET_LEADS", "Diamond TAIL3_READY and TAIL4-ready preview stays live; Club does not"
        if club_t4 and dia_t4:
            if club_g is not None and dia_g is not None and club_g + 4 < dia_g:
                return "CLUB_POST_SD5_TARGET_LEADS", "both live; Club READY is substantially cheaper"
            if dia_g is not None and club_g is not None and dia_g + 4 < club_g:
                return "DIAMOND_POST_SD5_TARGET_LEADS", "both live; Diamond READY is substantially cheaper"
            return "CLUB_AND_DIAMOND_BOTH_VIABLE", "both suits reach TAIL3_READY with live TAIL4-ready continuation"
        return "CLUB_AND_DIAMOND_BOTH_VIABLE", "both suits reach TAIL3_READY; TAIL4-ready continuation is mixed"
    if club_r and not dia_r:
        return "CLUB_POST_SD5_TARGET_LEADS", "only Club crossed TAIL3_READY in the equal envelope"
    if dia_r and not club_r:
        return "DIAMOND_POST_SD5_TARGET_LEADS", "only Diamond crossed TAIL3_READY in the equal envelope"
    return "INCONCLUSIVE", "reassessment finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "CLUB_POST_SD5_TARGET_LEADS":
        return (
            "Adopt Club as the revised post-SD5 operational target. Continue from Club TAIL3 / "
            "TAIL3_READY portfolios toward TAIL4_READY. Do not resume the Spade 4S/LAND5 tunnel."
        )
    if verdict == "DIAMOND_POST_SD5_TARGET_LEADS":
        return (
            "Adopt Diamond as the revised post-SD5 operational target. Continue from Diamond TAIL3 / "
            "TAIL3_READY portfolios toward TAIL4_READY. Do not resume the Spade 4S/LAND5 tunnel."
        )
    if verdict == "CLUB_AND_DIAMOND_BOTH_VIABLE":
        return (
            "Keep both Club and Diamond TAIL3_READY portfolios. Next: equal TAIL4_READY searches "
            "from those boundaries. Do not resume the Spade 4S/LAND5 tunnel."
        )
    if verdict == "CLUB_DIAMOND_TAIL3_READY_NOT_FOUND":
        return (
            "Neither Club nor Diamond crossed TAIL3_READY. Inspect buried 2-A vs buried 3 with a "
            "directed resource cut. Do not immediately return to Spades."
        )
    if verdict == "CLUB_DIAMOND_REASSESSMENT_STATE_EXPLOSION":
        return (
            "Equal Club/Diamond READY searches exploded. Continue from cheapest near-miss "
            "packet-mobilise / 3-expose states. Do not immediately return to Spades."
        )
    return "Keep the Club vs Diamond TAIL3_READY reassessment. Do not resume the Spade tunnel."


def _rebuild(opening, sources, recs):
    rebuilt = []
    for rec in recs:
        src = sources[rec["origin"]]
        full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "full_actions": dump_actions(full),
                "full_replay_ok": cost == rec["g"] and stock_rows(end) == 0,
                "ordered_digest": pack_state(end).hex(),
                "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                "source_g": src.get("g"),
                "lineages": src.get("lineages"),
            }
        )
    rebuilt.sort(key=lambda w: (w["g"], w.get("origin", 0)))
    return rebuilt


def run_preview(opening, tail3_rows, suit: str, deadline: float) -> dict:
    counts = Counter()
    t4_hits = []
    t4_joins = []
    for rec in tail3_rows:
        if time.perf_counter() >= deadline:
            counts["LIVE_BEYOND_5"] += 1
            continue
        st = opening.clone()
        replay_actions(st, as_actions(rec["full_actions"]))
        pr = preview_tail4_ready(st, int(rec["g"]), suit, deadline=min(deadline, time.perf_counter() + 0.25))
        rec["preview"] = pr["status"]
        rec["preview_g"] = (pr.get("hit") or {}).get("g")
        counts[pr["status"]] += 1
        if pr.get("hit"):
            t4_hits.append({**rec, "tail4_ready_g": pr["hit"]["g"], "tail4_ready_depth": pr["hit"]["depth"]})
            # optional join from the TAIL4_READY child if immediate
            if pr["status"] == "TAIL4_READY_IMMEDIATE":
                joined = optional_tail4_join(st, int(rec["g"]), suit)
                if joined:
                    t4_joins.append({**rec, **joined})
    live = counts["TAIL4_READY_IMMEDIATE"] + counts["TAIL4_READY_WITHIN_5"] + counts["LIVE_BEYOND_5"]
    return {
        "counts": dict(counts),
        "live": live > 0,
        "immediate": counts["TAIL4_READY_IMMEDIATE"],
        "within5": counts["TAIL4_READY_WITHIN_5"],
        "t4_ready_n": len(t4_hits),
        "t4_n": len(t4_joins),
        "cheapest_t4": None if not t4_joins else min(w["g"] for w in t4_joins),
        "hits": t4_hits[:64],
        "joins": t4_joins[:64],
    }


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.49 — Post-SD5 Club vs Diamond TAIL3_READY Race",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        f"- Revised target: **{payload.get('revised_target')}**",
        "",
        "## 2. Roots / sources",
        "",
        "```json",
        json.dumps(payload.get("roots"), indent=2)[:2500],
        "```",
        "",
        "## 3. Club audit / search / TAIL3 / TAIL4",
        "",
        "```json",
        json.dumps(payload.get("club"), indent=2)[:4000],
        "```",
        "",
        "## 4. Diamond audit / search / TAIL3 / TAIL4",
        "",
        "```json",
        json.dumps(payload.get("diamond"), indent=2)[:4000],
        "```",
        "",
        "## 5. Comparison",
        "",
        "```json",
        json.dumps(payload.get("comparison"), indent=2)[:2500],
        "```",
        "",
        "## 6. Spade / Heart reference (telemetry only)",
        "",
        "Spade TAIL3 best = MW85, but v0.45–v0.48 failed to create LAND5_READY after a dedicated 160k search.",
        "Heart 2-A was not reached in v0.44 (~104k unique / 150s). Deferred, not impossible.",
        "",
        "## 7. Files",
        "",
        json.dumps(payload.get("files"), indent=2),
        "",
        "No Spade search. No Heart search. No Foundation-3. No rank-5+. Production unchanged.",
        "",
        "## 8. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 360.0

    print("LOAD 720 DEAL_NOW", flush=True)
    roots = load_v044_deal_now_roots(opening)
    print(
        f"ROOTS raw={roots['raw']} unique={roots['symmetry_unique']} replay_ok={roots['all_replay_ok']} "
        f"costs={roots['cost_counts']}",
        flush=True,
    )
    print("FILTER 2-A", flush=True)
    club_src = filter_2a_sources(roots["states"], "c")
    dia_src = filter_2a_sources(roots["states"], "d")
    print(
        f"CLUB 2A raw={club_src['raw']} unique={club_src['symmetry_unique']} obst={club_src['obstacles']}",
        flush=True,
    )
    print(
        f"DIA 2A raw={dia_src['raw']} unique={dia_src['symmetry_unique']} obst={dia_src['obstacles']}",
        flush=True,
    )
    _write_json(CLUB_SRC, {"experiment": EXPERIMENT, "suit": "c", "n": club_src["symmetry_unique"], "raw": club_src["raw"], "cost_counts": club_src["cost_counts"], "obstacles": club_src["obstacles"], "states": _slim(club_src["states"])})
    _write_json(DIA_SRC, {"experiment": EXPERIMENT, "suit": "d", "n": dia_src["symmetry_unique"], "raw": dia_src["raw"], "cost_counts": dia_src["cost_counts"], "obstacles": dia_src["obstacles"], "states": _slim(dia_src["states"])})

    club_audit = structural_audit(club_src["states"], "c")
    dia_audit = structural_audit(dia_src["states"], "d")
    print(f"AUDIT C {club_audit}", flush=True)
    print(f"AUDIT D {dia_audit}", flush=True)

    print("ONE-MOVE SCAN", flush=True)
    club_fast = one_move_scan(club_src["states"], "c")
    dia_fast = one_move_scan(dia_src["states"], "d")
    print(f"FAST C actions={club_fast['n_actions']} ready={club_fast['ready_n']} t3={club_fast['tail3_n']} cheap={club_fast['ready_cheapest']}", flush=True)
    print(f"FAST D actions={dia_fast['n_actions']} ready={dia_fast['ready_n']} t3={dia_fast['tail3_n']} cheap={dia_fast['ready_cheapest']}", flush=True)

    def run_suit(name, src, fast, out_ready, out_t3, out_t4):
        remaining = global_deadline - time.perf_counter()
        budget = min(SEARCH_TIME_S, max(20.0, remaining - 20.0))
        print(f"SEARCH {name} budget={budget:.0f}s n={len(src['states'])}", flush=True)
        res = search_tail3_ready(
            src["states"],
            suit=name,
            max_unique=SEARCH_UNIQUE,
            time_limit_s=budget,
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=COST_CEILING,
        )
        rebuilt = _rebuild(opening, src["states"], res.witnesses)
        if rebuilt:
            _write_json(out_ready, {"experiment": EXPERIMENT, "suit": name, "n": len(rebuilt), "states": _slim(rebuilt)})
        joins = execute_tail3_joins(src["states"], rebuilt, name, opening)
        if joins:
            _write_json(out_t3, {"experiment": EXPERIMENT, "suit": name, "n": len(joins), "states": _slim(joins)})
        preview = {"counts": {}, "live": False, "immediate": 0, "within5": 0, "t4_n": 0, "cheapest_t4": None, "hits": [], "joins": []}
        if joins and time.perf_counter() < global_deadline:
            print(f"PREVIEW {name} n={len(joins)}", flush=True)
            preview = run_preview(opening, joins, name, global_deadline)
            if preview.get("joins"):
                _write_json(out_t4, {"experiment": EXPERIMENT, "suit": name, "n": len(preview["joins"]), "states": _slim(preview["joins"])})
        meta = {
            "sources": src["symmetry_unique"],
            "raw": src["raw"],
            "obstacles": src["obstacles"],
            "audit": {k: v for k, v in (club_audit if name == "c" else dia_audit).items() if k != "suit"},
            "fast": {"n_actions": fast["n_actions"], "ready_n": fast["ready_n"], "tail3_n": fast["tail3_n"], "ready_cheapest": fast["ready_cheapest"]},
            "search": {
                "unique": res.unique,
                "expanded": res.expanded,
                "generated": res.generated,
                "duplicate_skips": res.duplicate_skips,
                "elapsed_s": res.elapsed_s,
                "peak_rss_mb": res.peak_rss_mb,
                "stop_reason": res.stop_reason,
                "first_s": res.first_s,
                "first_g": res.first_g,
                "already": res.already,
                "n": len(rebuilt),
                "cheapest": None if not rebuilt else min(w["g"] for w in rebuilt),
                "bands": dict(Counter(w["g"] for w in rebuilt)),
                "contract_fail": res.contract_fail,
                "foundation": res.foundation_surprise,
            },
            "tail3": {
                "n": len(joins),
                "cheapest": None if not joins else min(w["g"] for w in joins),
            },
            "preview": {k: preview.get(k) for k in ("counts", "live", "immediate", "within5", "t4_n", "cheapest_t4")},
        }
        print(
            f"{name} READY n={len(rebuilt)} cheap={meta['search']['cheapest']} stop={res.stop_reason} "
            f"T3 n={len(joins)} cheap={meta['tail3']['cheapest']} preview={preview.get('counts')}",
            flush=True,
        )
        return meta, res, rebuilt, joins, preview

    club_meta, club_res, club_ready, club_t3, club_prev = run_suit("c", club_src, club_fast, CLUB_READY, CLUB_T3, CLUB_T4)
    dia_meta, dia_res, dia_ready, dia_t3, dia_prev = run_suit("d", dia_src, dia_fast, DIA_READY, DIA_T3, DIA_T4)

    payload_pre = {
        "all_replay_ok": roots["all_replay_ok"],
        "contract_fail": (club_res.contract_fail + dia_res.contract_fail) > 0,
        "foundation2": club_res.foundation_surprise or dia_res.foundation_surprise,
        "club_ready": bool(club_ready),
        "diamond_ready": bool(dia_ready),
        "club_explosion": club_res.stop_reason in ("unique limit", "rss abort") and not club_ready,
        "diamond_explosion": dia_res.stop_reason in ("unique limit", "rss abort") and not dia_ready,
        "club_t4_live": bool(club_prev.get("live")),
        "diamond_t4_live": bool(dia_prev.get("live")),
        "club_ready_g": club_meta["search"]["cheapest"],
        "diamond_ready_g": dia_meta["search"]["cheapest"],
    }
    verdict, reason = choose_verdict(payload_pre)
    if verdict == "CLUB_POST_SD5_TARGET_LEADS":
        target = "CLUB"
    elif verdict == "DIAMOND_POST_SD5_TARGET_LEADS":
        target = "DIAMOND"
    elif verdict == "CLUB_AND_DIAMOND_BOTH_VIABLE":
        target = "BOTH"
    else:
        target = "UNRESOLVED"
    interpretation = (
        f"{reason}. Roots 720 replay_ok={roots['all_replay_ok']}. "
        f"Club 2-A {club_src['raw']}/{club_src['symmetry_unique']}. "
        f"Diamond 2-A {dia_src['raw']}/{dia_src['symmetry_unique']}. "
        f"Club READY cheap={club_meta['search']['cheapest']} T3={club_meta['tail3']['cheapest']}. "
        f"Diamond READY cheap={dia_meta['search']['cheapest']} T3={dia_meta['tail3']['cheapest']}. "
        f"No Spade/Heart/F3/rank5 search."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "revised_target": target,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "roots": {
            "raw": roots["raw"],
            "symmetry_unique": roots["symmetry_unique"],
            "all_replay_ok": roots["all_replay_ok"],
            "cost_counts": roots["cost_counts"],
            "club_2a_raw": club_src["raw"],
            "club_2a_unique": club_src["symmetry_unique"],
            "diamond_2a_raw": dia_src["raw"],
            "diamond_2a_unique": dia_src["symmetry_unique"],
        },
        "club": club_meta,
        "diamond": dia_meta,
        "comparison": {
            "club_ready_g": club_meta["search"]["cheapest"],
            "diamond_ready_g": dia_meta["search"]["cheapest"],
            "club_tail3_g": club_meta["tail3"]["cheapest"],
            "diamond_tail3_g": dia_meta["tail3"]["cheapest"],
            "club_t4": club_prev.get("counts"),
            "diamond_t4": dia_prev.get("counts"),
            "club_t4_live": club_prev.get("live"),
            "diamond_t4_live": dia_prev.get("live"),
        },
        "reference": {
            "spade": "TAIL3 best MW85; v0.45-v0.48 failed LAND5_READY after 160k unique",
            "heart": "v0.44 2-A no hit ~104k unique / 150s; deferred not impossible",
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "club_sources": CLUB_SRC.relative_to(ROOT).as_posix(),
            "diamond_sources": DIA_SRC.relative_to(ROOT).as_posix(),
            "club_ready": CLUB_READY.relative_to(ROOT).as_posix() if CLUB_READY.exists() else None,
            "diamond_ready": DIA_READY.relative_to(ROOT).as_posix() if DIA_READY.exists() else None,
            "club_tail3": CLUB_T3.relative_to(ROOT).as_posix() if CLUB_T3.exists() else None,
            "diamond_tail3": DIA_T3.relative_to(ROOT).as_posix() if DIA_T3.exists() else None,
            "club_tail4": CLUB_T4.relative_to(ROOT).as_posix() if CLUB_T4.exists() else None,
            "diamond_tail4": DIA_T4.relative_to(ROOT).as_posix() if DIA_T4.exists() else None,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": roots["all_replay_ok"],
        "contract_fail": payload_pre["contract_fail"],
        "foundation2": payload_pre["foundation2"],
        "club_ready": bool(club_ready),
        "diamond_ready": bool(dia_ready),
        "club_explosion": payload_pre["club_explosion"],
        "diamond_explosion": payload_pre["diamond_explosion"],
        "club_t4_live": payload_pre["club_t4_live"],
        "diamond_t4_live": payload_pre["diamond_t4_live"],
        "club_ready_g": payload_pre["club_ready_g"],
        "diamond_ready_g": payload_pre["diamond_ready_g"],
    }
    for key, path in (
        ("club_ready", CLUB_READY),
        ("diamond_ready", DIA_READY),
        ("club_tail3", CLUB_T3),
        ("diamond_tail3", DIA_T3),
        ("club_tail4", CLUB_T4),
        ("diamond_tail4", DIA_T4),
    ):
        payload["files"][key] = path.relative_to(ROOT).as_posix() if path.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"TARGET {target}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
