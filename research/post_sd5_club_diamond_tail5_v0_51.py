#!/usr/bin/env python3
"""v0.51: Club vs Diamond TAIL5_READY race from v0.50 visible TAIL4 states.

Do not search Spades, Hearts, Foundation 3, or rank 7+.
Do not rerun TAIL4_READY search.
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
from spider.simple_club_diamond_tail5 import (
    CLUB_T4,
    COST_CEILING,
    DIA_T4,
    EXPECTED_CLUB,
    EXPECTED_DIA,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    execute_tail5_joins,
    load_tail4_persists,
    one_move_scan,
    reconstruct_tail6_preview,
    search_tail5_ready,
    structural_audit,
    tail5_ready,
    tail6_ready,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_low_tail import (
    FOUNDATION_AUTO_REMOVED,
    LOW_TAIL_PERSISTS,
    classify_low_tail_transition,
    legal_tail_joins,
)
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "post_sd5_club_diamond_tail5_v0_51"
BASE_SHA = "a8a8719b58cd8f9fa9b1bbe036a6bfc17d2a00b1"
BRANCH = "agent/post-sd5-club-diamond-tail5-ready-v0-51"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CLUB_SRC = ROOT / "docs" / "research" / "club_tail4_sources_v0_51.json"
DIA_SRC = ROOT / "docs" / "research" / "diamond_tail4_sources_v0_51.json"
CLUB_READY = ROOT / "docs" / "research" / "club_tail5_ready_v0_51.json"
DIA_READY = ROOT / "docs" / "research" / "diamond_tail5_ready_v0_51.json"
CLUB_T5 = ROOT / "docs" / "research" / "club_tail5_v0_51.json"
DIA_T5 = ROOT / "docs" / "research" / "diamond_tail5_v0_51.json"
CLUB_T6R = ROOT / "docs" / "research" / "club_tail6_ready_v0_51.json"
DIA_T6R = ROOT / "docs" / "research" / "diamond_tail6_ready_v0_51.json"
CLUB_T6 = ROOT / "docs" / "research" / "club_tail6_v0_51.json"
DIA_T6 = ROOT / "docs" / "research" / "diamond_tail6_v0_51.json"
F2_OUT = ROOT / "docs" / "research" / "foundation2_portfolio_v0_51.json"
CLUB_FIX = ROOT / "solutions" / "4925153_v0_51_club_foundation2.moves.txt"
DIA_FIX = ROOT / "solutions" / "4925153_v0_51_diamond_foundation2.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _slim(states):
    keys = (
        "g", "source_g", "full_actions", "ordered_digest", "symmetry_digest",
        "category", "already_ready", "ready", "join", "report_class", "class",
        "upper_run", "status", "depth", "actions", "foundation_count", "foundation_suits",
        "persist_name", "ka_ok", "fd", "empties", "suit",
    )
    out = []
    for s in states:
        out.append({k: s[k] for k in keys if k in s})
    return out


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.50 TAIL4_PERSISTS sources failed replay"
    if p.get("contract_fail"):
        return "LOW_TAIL_TRANSITION_CONTRACT_FAILURE", "TAIL5 appeared without TAIL5_READY parent or join failed"
    club_f2 = p.get("club_f2")
    dia_f2 = p.get("dia_f2")
    if club_f2 and dia_f2:
        return "BOTH_CLUB_AND_DIAMOND_REACH_FOUNDATION2", "both suits auto-removed Foundation 2 via 4-3-2-A onto K-through-5"
    if club_f2:
        return "CLUB_FOUNDATION2_REACHED", "Club 4-3-2-A onto 5 auto-removed Foundation 2"
    if dia_f2:
        return "DIAMOND_FOUNDATION2_REACHED", "Diamond 4-3-2-A onto 5 auto-removed Foundation 2"
    club_r = p.get("club_ready")
    dia_r = p.get("dia_ready")
    if p.get("explosion") and not club_r and not dia_r:
        return "TAIL5_RACE_STATE_EXPLOSION", "equal envelopes exploded before TAIL5_READY"
    if not club_r and not dia_r:
        return "TAIL5_READY_NOT_FOUND_FOR_EITHER", "neither suit crossed TAIL5_READY"
    club_t6 = p.get("club_t6_live")
    dia_t6 = p.get("dia_t6_live")
    club_g = p.get("club_ready_g")
    dia_g = p.get("dia_ready_g")
    if club_r and dia_r:
        if club_t6 and not dia_t6:
            return "CLUB_TAIL5_CONTINUATION_LEADS", "both READY; Club TAIL6_READY stays live, Diamond does not"
        if dia_t6 and not club_t6:
            return "DIAMOND_TAIL5_CONTINUATION_LEADS", "both READY; Diamond TAIL6_READY stays live, Club does not"
        if club_g is not None and dia_g is not None and club_g + 4 < dia_g and club_t6:
            return "CLUB_TAIL5_CONTINUATION_LEADS", "both live; Club READY substantially cheaper"
        if dia_g is not None and club_g is not None and dia_g + 4 < club_g and dia_t6:
            return "DIAMOND_TAIL5_CONTINUATION_LEADS", "both live; Diamond READY substantially cheaper"
        return "CLUB_AND_DIAMOND_TAIL5_BOTH_VIABLE", "both suits reach TAIL5_READY with comparable continuation"
    if club_r:
        return "CLUB_TAIL5_CONTINUATION_LEADS", "only Club crossed TAIL5_READY"
    return "DIAMOND_TAIL5_CONTINUATION_LEADS", "only Diamond crossed TAIL5_READY"


def next_recommendation(verdict: str) -> str:
    if "FOUNDATION2" in verdict:
        return (
            "Foundation 2 is in hand. Replan from the exact Foundation-2 frontier. "
            "Do not search Foundation 3, Spades, or Hearts."
        )
    if verdict in ("CLUB_TAIL5_CONTINUATION_LEADS", "DIAMOND_TAIL5_CONTINUATION_LEADS"):
        who = "Club" if verdict.startswith("CLUB") else "Diamond"
        return (
            f"Adopt {who} as the revised post-SD5 target from its TAIL5 / TAIL5_READY portfolio. "
            "Continue toward TAIL6_READY with the corrected join classifier. Do not resume Spades."
        )
    if verdict == "CLUB_AND_DIAMOND_TAIL5_BOTH_VIABLE":
        return (
            "Keep both Club and Diamond TAIL5 portfolios. Next: equal TAIL6_READY searches "
            "from those boundaries. Do not resume Spades."
        )
    if verdict == "TAIL5_READY_NOT_FOUND_FOR_EITHER":
        return (
            "Neither suit crossed TAIL5_READY. Inspect buried 5s with a directed resource cut. "
            "Do not immediately return to Spades."
        )
    if verdict == "TAIL5_RACE_STATE_EXPLOSION":
        return (
            "Equal TAIL5 searches exploded. Continue from cheapest near-miss 5-expose states. "
            "Do not immediately return to Spades."
        )
    return "Keep the Club vs Diamond TAIL5_READY race. Do not resume the Spade tunnel."


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
                "ready": tail5_ready(end, rec.get("suit") or src.get("suit") or "c"),
            }
        )
    rebuilt.sort(key=lambda w: (w["g"], w.get("origin", 0)))
    return rebuilt


def preview_t6(persists, suit, deadline):
    counts = Counter()
    ready_children = []
    joins = []
    for rec in persists:
        if time.perf_counter() >= deadline:
            counts["LIVE_BEYOND_5"] += 1
            continue
        hit = reconstruct_tail6_preview(rec, suit)
        counts[hit["status"]] += 1
        if hit["status"] in ("READY_AT_SOURCE", "READY_WITHIN_5"):
            ready_children.append(hit)
            st = unpack_state(bytes.fromhex(hit["ordered_digest"]))
            for action in legal_tail_joins(st, suit, 6):
                cls = classify_low_tail_transition(st, int(hit["g"]), suit, action, packet_head_rank=5)
                cls["full_actions"] = dump_actions(as_actions(hit["full_actions"]) + [action])
                cls["suit"] = suit
                cls["report_class"] = "TAIL6_PERSISTS" if cls["class"] == LOW_TAIL_PERSISTS else cls["class"]
                joins.append(cls)
    live = counts["READY_AT_SOURCE"] + counts["READY_WITHIN_5"] + counts["LIVE_BEYOND_5"]
    return {
        "counts": dict(counts),
        "live": live > 0,
        "at_source": counts["READY_AT_SOURCE"],
        "within5": counts["READY_WITHIN_5"],
        "dead": counts["EXACT_DEAD_TO_TAIL6_READY"],
        "ready_n": len(ready_children),
        "join_n": len(joins),
        "join_classes": dict(Counter(j["report_class"] for j in joins)),
        "cheapest_t6": None if not joins else min(j["g"] for j in joins),
        "ready": ready_children,
        "joins": joins,
    }


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.51 — Club vs Diamond TAIL5_READY Race",
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
        "## 2. Sources",
        "",
        "```json",
        json.dumps(payload.get("sources"), indent=2)[:2500],
        "```",
        "",
        "## 3. Club",
        "",
        "```json",
        json.dumps(payload.get("club"), indent=2)[:4000],
        "```",
        "",
        "## 4. Diamond",
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
        "Spade TAIL3 MW85 then LAND5_READY failed. Heart 2-A not reached in v0.44. Both deferred.",
        "",
        "## 6. Files",
        "",
        json.dumps(payload.get("files"), indent=2),
        "",
        "No Spade/Heart/Foundation-3/rank-7 search. Production unchanged.",
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_suit(name, src_path, expected, opening, global_deadline, out_src, out_ready, out_t5, out_t6r, out_t6):
    print(f"LOAD {name} TAIL4_PERSISTS", flush=True)
    bundle = load_tail4_persists(src_path, opening, name, expected)
    print(
        f"{name} raw={bundle['raw']} unique={bundle['symmetry_unique']} replay_ok={bundle['all_replay_ok']} "
        f"cats={bundle['categories']} costs={bundle['cost_counts']}",
        flush=True,
    )
    _write_json(out_src, {"experiment": EXPERIMENT, "suit": name, "n": bundle["symmetry_unique"], "raw": bundle["raw"], "cost_counts": bundle["cost_counts"], "categories": bundle["categories"], "states": _slim(bundle["states"])})
    audit = structural_audit(bundle["states"], name)
    print(f"AUDIT {name} { {k:v for k,v in audit.items() if k not in ('suit',)} }", flush=True)
    fast = one_move_scan(bundle["states"], name)
    print(f"FAST {name} actions={fast['n_actions']} ready={fast['ready_n']} cheap={fast['ready_cheapest']} f2={fast['f2_n']}", flush=True)
    remaining = global_deadline - time.perf_counter()
    budget = min(SEARCH_TIME_S, max(20.0, remaining - 40.0))
    print(f"SEARCH {name} budget={budget:.0f}s n={len(bundle['states'])}", flush=True)
    res = search_tail5_ready(bundle["states"], suit=name, max_unique=SEARCH_UNIQUE, time_limit_s=budget, rss_abort_mb=SEARCH_RSS_MB, cost_ceiling=COST_CEILING)
    rebuilt = _rebuild(opening, bundle["states"], res.witnesses)
    if rebuilt:
        _write_json(out_ready, {"experiment": EXPERIMENT, "suit": name, "n": len(rebuilt), "states": _slim(rebuilt)})
    joins = execute_tail5_joins(bundle["states"], rebuilt, name)
    persists = [j for j in joins if j["class"] == LOW_TAIL_PERSISTS]
    f2 = [j for j in joins if j["class"] == FOUNDATION_AUTO_REMOVED]
    fail = [j for j in joins if j["class"] not in (LOW_TAIL_PERSISTS, FOUNDATION_AUTO_REMOVED)]
    if persists:
        _write_json(out_t5, {"experiment": EXPERIMENT, "suit": name, "n": len(persists), "states": _slim(persists)})
    print(
        f"{name} READY n={len(rebuilt)} cheap={None if not rebuilt else min(w['g'] for w in rebuilt)} "
        f"stop={res.stop_reason} joins persist={len(persists)} f2={len(f2)} fail={len(fail)}",
        flush=True,
    )
    preview = {"counts": {}, "live": False, "at_source": 0, "within5": 0, "dead": 0, "ready_n": 0, "join_n": 0, "join_classes": {}, "cheapest_t6": None, "ready": [], "joins": []}
    if persists and time.perf_counter() < global_deadline:
        print(f"PREVIEW T6 {name} n={len(persists)}", flush=True)
        preview = preview_t6(persists, name, global_deadline)
        if preview["ready"]:
            _write_json(out_t6r, {"experiment": EXPERIMENT, "suit": name, "n": len(preview["ready"]), "states": _slim(preview["ready"])})
        if preview["joins"]:
            _write_json(out_t6, {"experiment": EXPERIMENT, "suit": name, "n": len(preview["joins"]), "states": _slim(preview["joins"])})
        print(f"T6 {name} {preview['counts']} joins={preview['join_classes']}", flush=True)
    meta = {
        "sources": bundle["symmetry_unique"],
        "raw": bundle["raw"],
        "all_replay_ok": bundle["all_replay_ok"],
        "cost_counts": bundle["cost_counts"],
        "categories": bundle["categories"],
        "audit": audit,
        "fast": {k: fast[k] for k in ("n_actions", "ready_n", "ready_cheapest", "f2_n")},
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
            "foundation_surprise": res.foundation_surprise,
        },
        "transitions": {
            "n": len(joins),
            "persists_n": len(persists),
            "f2_n": len(f2),
            "contract_n": len(fail),
            "cheapest_t5": None if not persists else min(j["g"] for j in persists),
            "cheapest_f2": None if not f2 else min(j["g"] for j in f2),
            "upper": dict(Counter((j.get("upper_run") or {}).get("label") for j in joins)),
        },
        "preview": {k: preview.get(k) for k in ("counts", "live", "at_source", "within5", "dead", "ready_n", "join_n", "join_classes", "cheapest_t6")},
    }
    return meta, bundle, res, rebuilt, persists, f2, preview


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 480.0
    search_deadline = started + 360.0

    club_meta, club_b, club_res, club_ready, club_p, club_f2, club_prev = run_suit(
        "c", CLUB_T4, EXPECTED_CLUB, opening, min(global_deadline, search_deadline + 60),
        CLUB_SRC, CLUB_READY, CLUB_T5, CLUB_T6R, CLUB_T6,
    )
    dia_meta, dia_b, dia_res, dia_ready, dia_p, dia_f2, dia_prev = run_suit(
        "d", DIA_T4, EXPECTED_DIA, opening, global_deadline,
        DIA_SRC, DIA_READY, DIA_T5, DIA_T6R, DIA_T6,
    )

    all_f2 = list(club_f2) + list(dia_f2)
    fixtures = {}
    if all_f2:
        by = {}
        for w in all_f2:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        port = sorted(by.values(), key=lambda w: w["g"])[:128]
        _write_json(F2_OUT, {"experiment": EXPERIMENT, "n": len(port), "cheapest": port[0]["g"], "states": _slim(port)})
        best = {}
        for w in port:
            s = w.get("suit")
            if s not in best or w["g"] < best[s]["g"]:
                best[s] = w
        if "c" in best:
            CLUB_FIX.parent.mkdir(parents=True, exist_ok=True)
            CLUB_FIX.write_text(format_moves_text(as_actions(best["c"]["full_actions"]), header="# v0.51 Club Foundation 2\n"), encoding="utf-8")
            fixtures["c"] = CLUB_FIX.relative_to(ROOT).as_posix()
        if "d" in best:
            DIA_FIX.parent.mkdir(parents=True, exist_ok=True)
            DIA_FIX.write_text(format_moves_text(as_actions(best["d"]["full_actions"]), header="# v0.51 Diamond Foundation 2\n"), encoding="utf-8")
            fixtures["d"] = DIA_FIX.relative_to(ROOT).as_posix()
        for s, p in (("c", CLUB_FIX), ("d", DIA_FIX)):
            if p.exists():
                end = opening.clone()
                cost = replay_actions(end, parse_moves_file(p))
                print(f"FIXTURE {s} mw={cost} fdn={len(end.foundations)}", flush=True)

    payload_pre = {
        "all_replay_ok": club_b["all_replay_ok"] and dia_b["all_replay_ok"],
        "contract_fail": (club_res.contract_fail + dia_res.contract_fail + club_meta["transitions"]["contract_n"] + dia_meta["transitions"]["contract_n"]) > 0 and not (club_ready or dia_ready),
        "club_f2": club_meta["transitions"]["f2_n"] > 0,
        "dia_f2": dia_meta["transitions"]["f2_n"] > 0,
        "club_ready": bool(club_ready),
        "dia_ready": bool(dia_ready),
        "explosion": (club_res.stop_reason in ("unique limit", "rss abort") and not club_ready) or (dia_res.stop_reason in ("unique limit", "rss abort") and not dia_ready),
        "club_t6_live": bool(club_prev.get("live")),
        "dia_t6_live": bool(dia_prev.get("live")),
        "club_ready_g": club_meta["search"]["cheapest"],
        "dia_ready_g": dia_meta["search"]["cheapest"],
    }
    verdict, reason = choose_verdict(payload_pre)
    if "FOUNDATION2" in verdict:
        target = "FOUNDATION2"
    elif verdict.startswith("CLUB_TAIL5") and "BOTH" not in verdict:
        target = "CLUB"
    elif verdict.startswith("DIAMOND"):
        target = "DIAMOND"
    elif "BOTH" in verdict:
        target = "BOTH"
    else:
        target = "UNRESOLVED"
    interpretation = (
        f"{reason}. Club unique={club_b['symmetry_unique']} READY cheap={club_meta['search']['cheapest']} "
        f"T5={club_meta['transitions']['cheapest_t5']} F2={club_meta['transitions']['cheapest_f2']}. "
        f"Diamond unique={dia_b['symmetry_unique']} READY cheap={dia_meta['search']['cheapest']} "
        f"T5={dia_meta['transitions']['cheapest_t5']} F2={dia_meta['transitions']['cheapest_f2']}. "
        f"No Spade/Heart/F3/rank7."
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
        "sources": {
            "club_raw": club_b["raw"],
            "club_unique": club_b["symmetry_unique"],
            "club_costs": club_b["cost_counts"],
            "diamond_raw": dia_b["raw"],
            "diamond_unique": dia_b["symmetry_unique"],
            "diamond_costs": dia_b["cost_counts"],
        },
        "club": club_meta,
        "diamond": dia_meta,
        "comparison": {
            "club_ready_g": club_meta["search"]["cheapest"],
            "diamond_ready_g": dia_meta["search"]["cheapest"],
            "club_t5": club_meta["transitions"]["cheapest_t5"],
            "diamond_t5": dia_meta["transitions"]["cheapest_t5"],
            "club_f2": club_meta["transitions"]["cheapest_f2"],
            "diamond_f2": dia_meta["transitions"]["cheapest_f2"],
            "club_t6": club_prev.get("counts"),
            "diamond_t6": dia_prev.get("counts"),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "club_sources": CLUB_SRC.relative_to(ROOT).as_posix(),
            "diamond_sources": DIA_SRC.relative_to(ROOT).as_posix(),
            "club_ready": CLUB_READY.relative_to(ROOT).as_posix() if CLUB_READY.exists() else None,
            "diamond_ready": DIA_READY.relative_to(ROOT).as_posix() if DIA_READY.exists() else None,
            "club_tail5": CLUB_T5.relative_to(ROOT).as_posix() if CLUB_T5.exists() else None,
            "diamond_tail5": DIA_T5.relative_to(ROOT).as_posix() if DIA_T5.exists() else None,
            "club_tail6_ready": CLUB_T6R.relative_to(ROOT).as_posix() if CLUB_T6R.exists() else None,
            "diamond_tail6_ready": DIA_T6R.relative_to(ROOT).as_posix() if DIA_T6R.exists() else None,
            "foundation2": F2_OUT.relative_to(ROOT).as_posix() if F2_OUT.exists() else None,
            "club_fixture": fixtures.get("c"),
            "diamond_fixture": fixtures.get("d"),
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": payload_pre["all_replay_ok"],
        "club_ready": bool(club_ready),
        "dia_ready": bool(dia_ready),
        "club_f2": payload_pre["club_f2"],
        "dia_f2": payload_pre["dia_f2"],
        "explosion": payload_pre["explosion"],
        "club_t6_live": payload_pre["club_t6_live"],
        "dia_t6_live": payload_pre["dia_t6_live"],
        "club_ready_g": payload_pre["club_ready_g"],
        "dia_ready_g": payload_pre["dia_ready_g"],
        "contract_fail": payload_pre["contract_fail"],
    }
    for key, path in (
        ("club_ready", CLUB_READY), ("diamond_ready", DIA_READY),
        ("club_tail5", CLUB_T5), ("diamond_tail5", DIA_T5),
        ("club_tail6_ready", CLUB_T6R), ("diamond_tail6_ready", DIA_T6R),
        ("foundation2", F2_OUT),
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
