#!/usr/bin/env python3
"""v0.52: expose either physical 6D from Diamond TAIL5, then micro-preview TAIL6.

Do not search TAIL6 until 6D is exposed. Do not search Spades/Clubs/Hearts,
Foundation 3, or rank 8+. Do not enlarge the envelope if D6 is missed.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_6d_access import (
    COST_CEILING,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    d6_exposed,
    harvest_d6_portfolio,
    load_tail5_sources,
    one_move_scan,
    reconstruct_ready_preview,
    search_d6_exposed,
    six_d_copies,
    structural_audit,
)
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_low_tail import (
    FOUNDATION_AUTO_REMOVED,
    LOW_TAIL_PERSISTS,
    classify_low_tail_transition,
    legal_tail_joins,
    tail_packets,
    tail_ready,
)
from spider.simple_progressive_solver import format_moves_text

EXPERIMENT = "diamond_6d_access_cut_v0_52"
BASE_SHA = "b34b6edfc7e2e322f56a8b0a90bb33d54895afa9"
BRANCH = "agent/diamond-6d-access-cut-v0-52"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOURCES = ROOT / "docs" / "research" / "diamond_tail5_sources_v0_52.json"
EXPOSED = ROOT / "docs" / "research" / "diamond_6d_exposed_v0_52.json"
T6_READY = ROOT / "docs" / "research" / "diamond_tail6_ready_v0_52.json"
T6_OUT = ROOT / "docs" / "research" / "diamond_tail6_v0_52.json"
F2_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_52.json"
F2_FIX = ROOT / "solutions" / "4925153_v0_52_diamond_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim(states):
    keys = (
        "g", "source_g", "full_actions", "ordered_digest", "symmetry_digest",
        "category", "min_depth", "already_exposed", "tail5_movable", "exposed",
        "used_cols_1", "tail5", "actions", "depth", "status", "class", "report_class",
        "join", "upper_run", "foundation_count", "foundation_suits", "ka_ok",
        "persist_name", "fd", "empties", "suits",
    )
    return [{k: s[k] for k in keys if k in s} for s in states]


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.51 Diamond TAIL5 sources failed replay"
    if p.get("contract_fail"):
        return "LOW_TAIL_TRANSITION_CONTRACT_FAILURE", "TAIL6 join produced neither persist nor auto-removal"
    if p.get("f2"):
        return "DIAMOND_FOUNDATION2_REACHED", "Diamond K-A auto-removed after 6D access / join"
    if p.get("tail6"):
        return "DIAMOND_TAIL6_REACHED", "visible 6D-5D-4D-3D-2D-AD formed after exposing 6D"
    if p.get("exposed") and not p.get("tail6_ready"):
        return "DIAMOND_6D_EXPOSED_TAIL6_NOT_READY", "6D exposed but TAIL5 could not join within 4 ply"
    if p.get("exposed"):
        return "DIAMOND_6D_ACCESS_LIVE", "6D exposed and TAIL6_READY live but join not completed"
    if p.get("explosion"):
        return "DIAMOND_6D_ACCESS_STATE_EXPLOSION", "dedicated 6D search hit unique/RSS/time without exposure"
    if p.get("search_attempted"):
        return "DIAMOND_6D_ACCESS_NOT_FOUND", "no D6_EXPOSED inside the dedicated envelope"
    return "INCONCLUSIVE", "6D access experiment finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "DIAMOND_FOUNDATION2_REACHED":
        return "Diamond Foundation 2 is in hand. Replan from that frontier. Do not search Foundation 3 or Spades."
    if verdict == "DIAMOND_TAIL6_REACHED":
        return "Continue Diamond from visible TAIL6 toward TAIL7_READY with the corrected classifier. Do not resume Spades."
    if verdict == "DIAMOND_6D_EXPOSED_TAIL6_NOT_READY":
        return "6D is exposed. Next: a short exact TAIL6_READY search from the exposure portfolio only. Do not flood UCS."
    if verdict == "DIAMOND_6D_ACCESS_LIVE":
        return "Keep the D6_EXPOSED portfolio and complete the 5-tail onto 6D. Do not resume Spades."
    if verdict in ("DIAMOND_6D_ACCESS_STATE_EXPLOSION", "DIAMOND_6D_ACCESS_NOT_FOUND"):
        return (
            "Diamond 6D access failed inside a dedicated envelope — same warning signature as Spade LAND5 / Club 5C. "
            "Stop Diamond excavation. Do not start another 6D blocker ratchet."
        )
    return "Keep the Diamond 6D access cut. Do not search TAIL6 while 6D is buried."


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
                "exposed": d6_exposed(end),
                "tail5": any(p["movable"] for p in tail_packets(end, "d", 5)),
            }
        )
    rebuilt.sort(key=lambda w: (w["g"], w.get("origin", 0)))
    return rebuilt


def write_report(payload: dict) -> None:
    src = payload.get("sources") or {}
    audit = payload.get("audit") or {}
    fast = payload.get("fast") or {}
    search = payload.get("search") or {}
    t6 = payload.get("tail6") or {}
    t7 = payload.get("tail7") or {}
    f2 = payload.get("foundation2") or {}
    lines = [
        "# Spider Solver v0.52 — Diamond 6D Access Cut",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        f"- Elapsed: {payload.get('elapsed_s')}s",
        "",
        "## 2. Sources",
        "",
        f"- Raw v0.51 TAIL5_PERSISTS: **{src.get('raw')}**",
        f"- Replay: **{src.get('replay_count', src.get('raw'))}** (ok={src.get('all_replay_ok')})",
        f"- Symmetry-unique: **{src.get('symmetry_unique')}**",
        f"- MW distribution: `{src.get('cost_counts')}`",
        f"- Categories: `{src.get('categories')}`",
        "",
        "TAIL5 packet audit (after v0.51 join, expected exposed and movable):",
        "",
        f"- exposed sources: {audit.get('tail5_exposed_sources')}",
        f"- movable sources: {audit.get('tail5_movable_sources')}",
        "",
        "## 3. 6D audit",
        "",
        f"- Physical copies counted: {audit.get('six_n')} (expect 2 per source)",
        f"- Sources with an exposed 6D: {audit.get('six_top_sources')}",
        f"- One-move-exposable sources: {audit.get('six_one_move_sources')}",
        f"- Both face-down sources: {audit.get('six_face_down_sources')}",
        f"- Blocker-depth distribution: `{audit.get('six_depth')}`",
        f"- Upper-run classes: `{audit.get('upper_runs')}`",
        f"- K_THROUGH_6: {audit.get('k_through_6')}",
        f"- Principal blocker signatures: `{audit.get('signatures')}`",
        "",
        "## 4. One-move scan",
        "",
        f"- Legal actions scanned: **{fast.get('n_actions')}**",
        f"- D6_EXPOSED children: **{fast.get('hit_n')}** (cheapest {fast.get('cheapest')})",
        f"- Foundation-2 surprises: **{fast.get('f2_n')}**",
        "",
        "## 5. D6_EXPOSED search",
        "",
        f"- Reached: **{search.get('reached')}**",
        f"- Attempted: {search.get('attempted')}",
        f"- First hit: t={search.get('first_s') if search.get('first_s') is not None else 'none'}s, g={search.get('first_g')}",
        f"- Cheapest g: **{search.get('cheapest')}**",
        f"- Unique / expanded / generated / dups: {search.get('unique')} / {search.get('expanded')} / {search.get('generated')} / {search.get('duplicate_skips')}",
        f"- Runtime / RSS: {search.get('elapsed_s')}s / {search.get('peak_rss_mb')} MB",
        f"- Stop: {search.get('stop_reason')}",
        f"- Boundary n / bands: {search.get('n')} / `{search.get('bands')}`",
        "",
        "## 6. TAIL6",
        "",
        f"- READY counts: `{t6.get('counts')}`",
        f"- Ready n: {t6.get('ready_n')}",
        f"- Transitions: join={t6.get('join_n')} persist={t6.get('persists_n')} auto-remove={t6.get('f2_n')} contract={t6.get('contract_n')}",
        f"- Visible TAIL6 cheapest: {t6.get('cheapest')}",
        "",
        "## 7. TAIL7 preview",
        "",
        f"- Counts: `{t7.get('counts')}`",
        f"- Optional join classes: `{t7.get('join_classes')}`",
        "",
        "## 8. Foundation 2",
        "",
        f"- Reached: **{f2.get('reached')}**",
        f"- n / cheapest: {f2.get('n')} / {f2.get('cheapest')}",
        f"- Fixture: {f2.get('fixture')}",
        "",
        "## 9. Strategic interpretation",
        "",
        payload.get("strategic", ""),
        "",
        f"- Diamond still operational leader: **{payload.get('diamond_still_leader')}**",
        "",
        "No TAIL6 search until 6D exposed. No Spade/Club/Heart/F3/rank-8. Production unchanged.",
        "",
        "## 10. Files",
        "",
        "```json",
        json.dumps(payload.get("files"), indent=2),
        "```",
        "",
        "## 11. Exactly one next recommendation",
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

    print("LOAD TAIL5", flush=True)
    bundle = load_tail5_sources(opening)
    print(
        f"T5 raw={bundle['raw']} unique={bundle['symmetry_unique']} replay_ok={bundle['all_replay_ok']} "
        f"cats={bundle['categories']} costs={bundle['cost_counts']}",
        flush=True,
    )
    _write_json(
        SOURCES,
        {
            "experiment": EXPERIMENT,
            "n": bundle["symmetry_unique"],
            "raw": bundle["raw"],
            "replay_count": bundle.get("replay_count"),
            "symmetry_unique": bundle["symmetry_unique"],
            "cost_counts": bundle["cost_counts"],
            "categories": bundle["categories"],
            "states": _slim(bundle["states"]),
        },
    )
    audit = structural_audit(bundle["states"])
    print(f"AUDIT {audit}", flush=True)
    print("ONE-MOVE", flush=True)
    fast = one_move_scan(bundle["states"])
    print(f"FAST actions={fast['n_actions']} hits={fast['hit_n']} cheap={fast['cheapest']} f2={fast['f2_n']}", flush=True)

    exposed_rows = []
    f2_rows = list(fast.get("f2") or [])
    search_meta = {
        "attempted": False,
        "reached": False,
        "n": 0,
        "unique": 0,
        "expanded": 0,
        "generated": 0,
        "duplicate_skips": 0,
        "elapsed_s": 0.0,
        "peak_rss_mb": None,
        "stop_reason": "skipped",
        "first_s": None,
        "first_g": None,
        "cheapest": None,
        "bands": {},
    }
    explosion = False
    for origin, rec in enumerate(bundle["states"]):
        if not rec.get("already_exposed"):
            continue
        exposed_rows.append(
            {
                "origin": origin,
                "g": rec["g"],
                "source_g": rec["g"],
                "depth": 0,
                "actions": [],
                "full_actions": rec["full_actions"],
                "ordered_digest": rec["ordered_digest"],
                "symmetry_digest": rec["symmetry_digest"],
                "already": True,
                "exposed": True,
                "used_cols_1": rec.get("used_cols_1") or [],
                "tail5": rec.get("tail5_movable"),
                "min_depth_src": rec.get("min_depth"),
            }
        )
    if fast["hits"]:
        exposed_rows.extend(fast["hits"])
    remaining = global_deadline - time.perf_counter()
    if remaining > 80.0:
        budget = min(SEARCH_TIME_S, remaining - 80.0)
        print(f"SEARCH D6 budget={budget:.0f}s n={len(bundle['states'])}", flush=True)
        res = search_d6_exposed(
            bundle["states"],
            max_unique=SEARCH_UNIQUE,
            time_limit_s=budget,
            rss_abort_mb=SEARCH_RSS_MB,
            cost_ceiling=COST_CEILING,
        )
        search_meta["attempted"] = True
        search_meta.update(
            {
                "unique": res.unique,
                "expanded": res.expanded,
                "generated": res.generated,
                "duplicate_skips": res.duplicate_skips,
                "elapsed_s": res.elapsed_s,
                "peak_rss_mb": res.peak_rss_mb,
                "stop_reason": res.stop_reason,
                "first_s": res.first_s,
                "first_g": res.first_g,
            }
        )
        if res.stop_reason in ("unique limit", "rss abort"):
            explosion = True
        rebuilt = _rebuild(opening, bundle["states"], res.witnesses)
        if rebuilt:
            exposed_rows.extend(rebuilt)
        f2_rows.extend(res.f2_hits)

    if exposed_rows:
        by = {}
        for w in exposed_rows:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        merged = sorted(by.values(), key=lambda w: w["g"])
        e6 = merged[0]["g"]
        banded = [w for w in merged if w["g"] <= e6 + 3]
        exposed_rows = harvest_d6_portfolio(banded, limit=192)
        search_meta["reached"] = True
        search_meta["n"] = len(exposed_rows)
        search_meta["cheapest"] = e6
        search_meta["bands"] = dict(Counter(w["g"] for w in exposed_rows))
        _write_json(EXPOSED, {"experiment": EXPERIMENT, "n": len(exposed_rows), "states": _slim(exposed_rows)})
        print(f"D6 n={len(exposed_rows)} cheap={search_meta['cheapest']} bands={search_meta['bands']}", flush=True)

    t6_counts = Counter()
    t6_ready = []
    t6_joins = []
    if exposed_rows and time.perf_counter() < global_deadline:
        print(f"PREVIEW TAIL6 n={len(exposed_rows)}", flush=True)
        for rec in exposed_rows:
            if time.perf_counter() >= global_deadline:
                t6_counts["LIVE_BEYOND_4"] += 1
                continue
            hit = reconstruct_ready_preview(rec, target_k=6, max_depth=4, max_unique=800)
            t6_counts[hit["status"]] += 1
            if hit["status"] in ("TAIL6_READY_AT_EXPOSURE", "TAIL6_READY_WITHIN_4"):
                t6_ready.append(hit)
                st = unpack_state(bytes.fromhex(hit["ordered_digest"]))
                for action in legal_tail_joins(st, "d", 6):
                    cls = classify_low_tail_transition(st, int(hit["g"]), "d", action, packet_head_rank=5)
                    cls["full_actions"] = dump_actions(as_actions(hit["full_actions"]) + [action])
                    cls["suit"] = "d"
                    cls["report_class"] = "TAIL6_PERSISTS" if cls["class"] == LOW_TAIL_PERSISTS else cls["class"]
                    t6_joins.append(cls)
                    if cls["class"] == FOUNDATION_AUTO_REMOVED:
                        f2_rows.append(cls)
        print(f"T6 {dict(t6_counts)} joins={Counter(j['report_class'] for j in t6_joins)}", flush=True)
        if t6_ready:
            _write_json(T6_READY, {"experiment": EXPERIMENT, "n": len(t6_ready), "states": _slim(t6_ready)})
        persists = [j for j in t6_joins if j["class"] == LOW_TAIL_PERSISTS]
        if persists:
            _write_json(T6_OUT, {"experiment": EXPERIMENT, "n": len(persists), "states": _slim(persists)})
    else:
        persists = []

    t7_counts = Counter()
    t7_joins = []
    if persists and time.perf_counter() < global_deadline:
        print(f"PREVIEW TAIL7 n={len(persists)}", flush=True)
        for rec in persists[:192]:
            if time.perf_counter() >= global_deadline:
                t7_counts["LIVE_BEYOND_5"] += 1
                continue
            hit = reconstruct_ready_preview(rec, target_k=7, max_depth=5, max_unique=800)
            t7_counts[hit["status"]] += 1
            if hit["status"] in ("READY_AT_SOURCE", "READY_WITHIN_5"):
                st = unpack_state(bytes.fromhex(hit["ordered_digest"]))
                for action in legal_tail_joins(st, "d", 7):
                    cls = classify_low_tail_transition(st, int(hit["g"]), "d", action, packet_head_rank=6)
                    cls["report_class"] = "TAIL7_PERSISTS" if cls["class"] == LOW_TAIL_PERSISTS else cls["class"]
                    t7_joins.append(cls)
                    if cls["class"] == FOUNDATION_AUTO_REMOVED:
                        f2_rows.append({**cls, "full_actions": dump_actions(as_actions(hit["full_actions"]) + [action])})
        print(f"T7 {dict(t7_counts)} joins={Counter(j['report_class'] for j in t7_joins)}", flush=True)

    fixtures = {}
    if f2_rows:
        by = {}
        for w in f2_rows:
            ident = w.get("symmetry_digest") or str(w.get("g"))
            prev = by.get(ident)
            if prev is None or w["g"] < prev["g"]:
                by[ident] = w
        port = sorted(by.values(), key=lambda w: w["g"])[:128]
        _write_json(F2_OUT, {"experiment": EXPERIMENT, "n": len(port), "cheapest": port[0]["g"], "states": _slim(port)})
        best = port[0]
        if best.get("full_actions"):
            F2_FIX.parent.mkdir(parents=True, exist_ok=True)
            F2_FIX.write_text(format_moves_text(as_actions(best["full_actions"]), header="# v0.52 Diamond Foundation 2\n"), encoding="utf-8")
            fixtures["d"] = F2_FIX.relative_to(ROOT).as_posix()
            end = opening.clone()
            cost = replay_actions(end, parse_moves_file(F2_FIX))
            print(f"FIXTURE d mw={cost} fdn={len(end.foundations)}", flush=True)

    persists_n = len([j for j in t6_joins if j["class"] == LOW_TAIL_PERSISTS])
    f2_join_n = len([j for j in t6_joins if j["class"] == FOUNDATION_AUTO_REMOVED])
    fail_n = len([j for j in t6_joins if j["class"] not in (LOW_TAIL_PERSISTS, FOUNDATION_AUTO_REMOVED)])
    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "contract_fail": fail_n > 0 and persists_n == 0 and f2_join_n == 0,
        "f2": bool(f2_rows),
        "tail6": persists_n > 0,
        "tail6_ready": bool(t6_ready),
        "exposed": bool(exposed_rows),
        "explosion": explosion and not exposed_rows,
        "search_attempted": search_meta["attempted"] or bool(fast["hits"]),
    }
    verdict, reason = choose_verdict(payload_pre)
    still_leader = verdict in (
        "DIAMOND_FOUNDATION2_REACHED",
        "DIAMOND_TAIL6_REACHED",
        "DIAMOND_6D_EXPOSED_TAIL6_NOT_READY",
        "DIAMOND_6D_ACCESS_LIVE",
    )
    strategic = (
        "Diamond remains the operational post-SD5 leader."
        if still_leader
        else "Diamond 6D access failed inside a dedicated envelope — same warning as Spade LAND5 / Club 5C. Stop Diamond excavation."
    )
    interpretation = (
        f"{reason}. T5 unique={bundle['symmetry_unique']} D6 cheap={search_meta.get('cheapest')} "
        f"T6 ready={len(t6_ready)} persist={persists_n} F2={len(f2_rows)}. {strategic}"
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "strategic": strategic,
        "next_recommendation": next_recommendation(verdict),
        "sources": {
            "raw": bundle["raw"],
            "replay_count": bundle.get("replay_count"),
            "symmetry_unique": bundle["symmetry_unique"],
            "all_replay_ok": bundle["all_replay_ok"],
            "cost_counts": bundle["cost_counts"],
            "categories": bundle["categories"],
        },
        "audit": audit,
        "fast": {k: fast[k] for k in ("n_actions", "hit_n", "cheapest", "f2_n")},
        "search": search_meta,
        "tail6": {
            "counts": dict(t6_counts),
            "ready_n": len(t6_ready),
            "join_n": len(t6_joins),
            "persists_n": persists_n,
            "f2_n": f2_join_n,
            "contract_n": fail_n,
            "cheapest": None if not persists else min(j["g"] for j in persists),
        },
        "tail7": {
            "counts": dict(t7_counts),
            "join_classes": dict(Counter(j["report_class"] for j in t7_joins)),
        },
        "foundation2": {
            "reached": bool(f2_rows),
            "n": len(f2_rows),
            "cheapest": None if not f2_rows else min(w["g"] for w in f2_rows),
            "fixture": fixtures.get("d"),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "sources": SOURCES.relative_to(ROOT).as_posix(),
            "exposed": EXPOSED.relative_to(ROOT).as_posix() if EXPOSED.exists() else None,
            "tail6_ready": T6_READY.relative_to(ROOT).as_posix() if T6_READY.exists() else None,
            "tail6": T6_OUT.relative_to(ROOT).as_posix() if T6_OUT.exists() else None,
            "foundation2": F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None,
            "fixture": fixtures.get("d"),
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": bundle["all_replay_ok"],
        "f2": bool(f2_rows),
        "tail6": persists_n > 0,
        "tail6_ready": bool(t6_ready),
        "exposed": bool(exposed_rows),
        "explosion": explosion and not exposed_rows,
        "search_attempted": search_meta["attempted"] or bool(fast["hits"]),
        "contract_fail": payload_pre["contract_fail"],
        "diamond_still_leader": still_leader,
    }
    # fix duplicate tail6 key - keep structured tail6 and boolean separately
    payload["tail6_reached"] = persists_n > 0
    payload["tail6"] = {
        "counts": dict(t6_counts),
        "ready_n": len(t6_ready),
        "join_n": len(t6_joins),
        "persists_n": persists_n,
        "f2_n": f2_join_n,
        "contract_n": fail_n,
        "cheapest": None if not persists else min(j["g"] for j in persists),
    }
    for key, path in (("exposed", EXPOSED), ("tail6_ready", T6_READY), ("tail6_file", T6_OUT), ("foundation2", F2_OUT)):
        payload["files"][key if key != "tail6_file" else "tail6"] = path.relative_to(ROOT).as_posix() if path.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
