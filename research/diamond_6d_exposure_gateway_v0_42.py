#!/usr/bin/env python3
"""v0.42: expose physical G6_8 / G6_9 as the 6D-5D receiving gateway."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, heart_telemetry, source_invariants
from spider.simple_diamond_edges import satisfied_core_edges
from spider.simple_diamond_g6_exposure import (
    COST_CEILING,
    HARVEST_SLACK,
    MAX_UNIQUE,
    RSS_PER_MB,
    TIME_LIMIT_S,
    blocker_audit,
    identify_source_g6,
    load_v041_sources,
    loc_is_top,
    opening_state,
    preview_c,
    search_exposure,
)
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "diamond_6d_exposure_gateway_v0_42"
BASE_SHA = "31e5f979712e41f85c7a2045b029b6b230922e3c"
BRANCH = "agent/diamond-6d-exposure-gateway-v0-42"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
G6_8_PORT = ROOT / "docs" / "research" / "diamond_g6_8_v0_42.json"
G6_9_PORT = ROOT / "docs" / "research" / "diamond_g6_9_v0_42.json"
COMBINED = ROOT / "docs" / "research" / "diamond_g6_combined_v0_42.json"
C_PORT = ROOT / "docs" / "research" / "diamond_c_from_g6_v0_42.json"
TAIL_PORT = ROOT / "docs" / "research" / "diamond_lower_tail_v0_42.json"
FOUND_FIX = ROOT / "solutions" / "4925153_v0_42_diamond_foundation.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def phase_a(states, locs8, locs9, cats) -> dict:
    a8, a9 = [], []
    for st, loc8, loc9, cat in zip(states, locs8, locs9, cats):
        b8 = blocker_audit(st, loc8, name="G6_8")
        b9 = blocker_audit(st, loc9, name="G6_9")
        b8["source_category"] = cat
        b9["source_category"] = cat
        a8.append(b8)
        a9.append(b9)

    def agg(rows, label):
        depths = Counter(r["cards_above"] for r in rows)
        movable = sum(1 for r in rows if r["covering_packet"]["movable"])
        has_7 = sum(1 for r in rows if r.get("has_7d_6d"))
        by_cat = {}
        for cat in ("B+D", "A+B", "A+B+D", "A+D"):
            sub = [r for r in rows if r.get("source_category") == cat]
            by_cat[cat] = {
                "n": len(sub),
                "depth": dict(Counter(r["cards_above"] for r in sub)),
                "movable_cover": sum(1 for r in sub if r["covering_packet"]["movable"]),
                "mean_depth": None if not sub else round(sum(r["cards_above"] for r in sub) / len(sub), 2),
            }
        return {
            "n": len(rows),
            "cover_depth": {str(k): int(v) for k, v in sorted(depths.items())},
            "movable_cover": movable,
            "has_7d_6d": has_7,
            "never_top": sum(1 for r in rows if not r["top"]),
            "all_face_up": all(r["face_up"] for r in rows),
            "by_category": by_cat,
            "sample": rows[0] if rows else None,
        }

    return {"G6_8": agg(a8, "G6_8"), "G6_9": agg(a9, "G6_9")}


def rebuild(opening, paths, gs, cats, search, target):
    rebuilt = []
    for rec in search.witnesses:
        origin = rec["origin"]
        full = list(paths[origin]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        loc = tuple(rec["loc"]) if rec.get("loc") else None
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "source_g": gs[origin],
                "continuation": cost - gs[origin],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "full_replay_ok": cost == rec["g"],
                "edges_now": sorted(satisfied_core_edges(end)),
                "heart": heart_telemetry(end),
                "invariants": source_invariants(end),
                "stock_rows": stock_rows(end),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "ordered_digest": pack_state(end).hex(),
                "exposed_top": bool(loc and loc_is_top(end, loc)),
                "target": target,
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"], w["ordered_digest"]))
    return rebuilt


def choose_verdict(payload: dict) -> tuple[str, str]:
    if not payload.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.41 sources failed replay or defensive dedup"
    if payload.get("foundation_reached"):
        return "DIAMOND_FOUNDATION_REACHED", "Diamond foundation auto-removed (Foundation 2)"
    s8 = payload.get("search8") or {}
    s9 = payload.get("search9") or {}
    r8, r9 = bool(s8.get("reached")), bool(s9.get("reached"))
    explosion = (s8.get("stop_reason") in ("unique limit", "rss abort") and not r8) or (
        s9.get("stop_reason") in ("unique limit", "rss abort") and not r9
    )
    preview = payload.get("c_preview") or {}
    c_hits = int(preview.get("C_IMMEDIATE") or 0) + int(preview.get("C_WITHIN_6") or 0) + int(
        preview.get("LOWER_TAIL_IMMEDIATE") or 0
    )
    if not r8 and not r9:
        if explosion:
            return "6D_EXPOSURE_SEARCH_STATE_EXPLOSION", "neither physical 6D exposed before unique/RSS limit"
        return "6D_EXPOSURE_NOT_FOUND_IN_ENVELOPE", "neither physical 6D became exposed/top under MW<=100"
    if r8 and r9 and c_hits == 0:
        return "6D_EXPOSURE_REACHED_NO_C_PREVIEW", "both exposures reached but C preview did not form 6D-5D"
    if (r8 or r9) and c_hits == 0:
        return "6D_EXPOSURE_REACHED_NO_C_PREVIEW", "exposure reached but C preview did not form 6D-5D"
    leader = payload.get("gateway_leader")
    if leader == "BOTH":
        return "BOTH_6D_EXPOSURES_PRODUCTIVE", "G6_8 and G6_9 both expose and produce C-preview evidence"
    if leader == "G6_8":
        return "G6_8_EXPOSURE_LEADS", "column-8 physical 6D is the more productive exposure gateway"
    if leader == "G6_9":
        return "G6_9_EXPOSURE_LEADS", "column-9 physical 6D is the more productive exposure gateway"
    if r8 and r9:
        return "BOTH_6D_EXPOSURES_PRODUCTIVE", "both physical 6Ds exposed"
    if r8:
        return "G6_8_EXPOSURE_LEADS", "only G6_8 reached exposure"
    if r9:
        return "G6_9_EXPOSURE_LEADS", "only G6_9 reached exposure"
    return "INCONCLUSIVE", "exposure comparison incomplete"


def select_leader(s8, s9, p8, p9) -> tuple[str, str]:
    r8, r9 = bool(s8.get("reached")), bool(s9.get("reached"))
    if not r8 and not r9:
        return "NONE", "neither exposure reached"
    c8 = (p8.get("C_IMMEDIATE") or 0) + (p8.get("C_WITHIN_6") or 0) + (p8.get("LOWER_TAIL_IMMEDIATE") or 0)
    c9 = (p9.get("C_IMMEDIATE") or 0) + (p9.get("C_WITHIN_6") or 0) + (p9.get("LOWER_TAIL_IMMEDIATE") or 0)
    t8 = p8.get("LOWER_TAIL_IMMEDIATE") or 0
    t9 = p9.get("LOWER_TAIL_IMMEDIATE") or 0
    n8 = s8.get("n") or 0
    n9 = s9.get("n") or 0
    rate8 = (c8 / n8) if n8 else 0
    rate9 = (c9 / n9) if n9 else 0
    if r8 and r9:
        if (c8 > 0) == (c9 > 0) and abs(rate8 - rate9) < 0.15 and t8 == t9:
            # both productive or both not; keep both if either has C or both exposed
            if c8 > 0 and c9 > 0:
                return "BOTH", f"C-preview rates {rate8:.2f} vs {rate9:.2f}; preserve both"
            if c8 == 0 and c9 == 0:
                return "BOTH", "both exposed, neither formed C in 6 ply"
        if t8 > t9:
            return "G6_8", "more LOWER_TAIL_IMMEDIATE"
        if t9 > t8:
            return "G6_9", "more LOWER_TAIL_IMMEDIATE"
        if rate8 > rate9 + 0.05:
            return "G6_8", f"higher C-preview rate {rate8:.2f} > {rate9:.2f} (not merely cheaper E)"
        if rate9 > rate8 + 0.05:
            return "G6_9", f"higher C-preview rate {rate9:.2f} > {rate8:.2f} (not merely cheaper E)"
        e8, e9 = s8.get("best_full_mw"), s9.get("best_full_mw")
        if c8 > 0 and c9 > 0:
            return "BOTH", "both produce C; cost is not the selector"
        if e8 is not None and e9 is not None and e8 < e9 and c8 >= c9:
            return "G6_8", "cheaper exposure with at least equal C evidence"
        if e9 is not None and e8 is not None and e9 < e8 and c9 >= c8:
            return "G6_9", "cheaper exposure with at least equal C evidence"
        return "BOTH", "no decisive C-preview gap"
    return ("G6_8", "only G6_8 reached") if r8 else ("G6_9", "only G6_9 reached")


def next_recommendation(verdict: str, leader: str) -> str:
    if verdict == "DIAMOND_FOUNDATION_REACHED":
        return "Persist the Foundation 2 witness and do not take SD5."
    if verdict in ("G6_8_EXPOSURE_LEADS", "G6_9_EXPOSURE_LEADS", "BOTH_6D_EXPOSURES_PRODUCTIVE"):
        who = "both physical 6Ds" if leader == "BOTH" else leader
        return (
            f"Take the {who} exposure portfolio as the Diamond C gateway. "
            "Search for current 6D-5D from those exposed-6D states. Do not raise MW above 100. "
            "Do not take SD5. Do not search Hearts."
        )
    if verdict == "6D_EXPOSURE_REACHED_NO_C_PREVIEW":
        return (
            "6D can be exposed but C does not collapse inside 6 ply. Keep the exposure "
            "portfolio and run a dedicated C search from it. Do not take SD5."
        )
    if verdict == "6D_EXPOSURE_NOT_FOUND_IN_ENVELOPE":
        return (
            "G6_9's covering packet is the unique 5D-4D and legally needs a rank-6 landing, "
            "so it cannot start until some 6D is already exposed. G6_8 has 7D-6D under a "
            "mixed 6-10 card cover whose top packet is movable on all 208 sources. Spend the "
            "next envelope on finishing G6_8 exposure (workspace/empty creation plus column-8 "
            "peeling) from this 208-state frontier. Do not split the budget with G6_9. "
            "Do not raise MW above 100. Do not take SD5."
        )
    if verdict == "6D_EXPOSURE_SEARCH_STATE_EXPLOSION":
        return "Exposure search hit unique/RSS before a 6D-top witness. Keep the 208-state frontier; do not take SD5."
    return "Keep the 6D exposure gateway. Do not take SD5. Do not search Hearts."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.42 — Diamond 6D Exposure Gateway",
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
        "## 2. Sources",
        "",
        "```json",
        json.dumps(payload.get("sources"), indent=2)[:2500],
        "```",
        "",
        "## 3. Blocker audit",
        "",
        "```json",
        json.dumps(payload.get("blocker_audit"), indent=2)[:5000],
        "```",
        "",
        "## 4. SEARCH 8 / SEARCH 9",
        "",
        "```json",
        json.dumps({"search8": payload.get("search8"), "search9": payload.get("search9")}, indent=2)[:4000],
        "```",
        "",
        "## 5. C preview / lower tail / edges",
        "",
        "```json",
        json.dumps(
            {
                "c_preview": payload.get("c_preview"),
                "lower_tail": payload.get("lower_tail"),
                "current_edges": payload.get("current_edges"),
                "gateway": payload.get("gateway"),
            },
            indent=2,
        )[:4000],
        "```",
        "",
        "## 6. Foundation / cross-target / files",
        "",
        "```json",
        json.dumps(
            {
                "foundation": payload.get("foundation"),
                "cross_target": payload.get("cross_target"),
                "files": payload.get("files"),
            },
            indent=2,
        )[:2500],
        "```",
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "SD5 never expanded. Physical 6D identity is search bookkeeping, not canonical state. Column 8 is not proof-preferred. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_search(search, rebuilt) -> dict:
    bands = Counter(w["full_cost"] for w in rebuilt)
    e0 = None if not rebuilt else min(w["full_cost"] for w in rebuilt)
    slack = {}
    if e0 is not None:
        for extra in range(0, HARVEST_SLACK + 1):
            slack[f"E+{extra}" if extra else "E"] = sum(1 for w in rebuilt if w["full_cost"] == e0 + extra)
    return {
        "reached": bool(rebuilt),
        "first_s": search.first_s,
        "first_unique": search.first_unique,
        "best_full_mw": e0,
        "source_category": search.first_category,
        "unique": search.unique,
        "expanded": search.expanded,
        "generated": search.generated,
        "duplicate_skips": search.duplicate_skips,
        "elapsed_s": search.elapsed_s,
        "peak_rss_mb": search.peak_rss_mb,
        "stop_reason": search.stop_reason,
        "levels": search.levels_reached,
        "sd5_expanded": search.sd5_expanded,
        "n": len(rebuilt),
        "bands": {str(k): int(v) for k, v in sorted(bands.items())},
        "slack": slack,
        "already_at_source": search.already_at_source,
        "foundation_surprise": search.foundation_surprise,
        "used_heuristic_prune": search.used_heuristic_prune,
    }


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 450.0
    print("LOAD v0.41 sources", flush=True)
    bundle = load_v041_sources(opening)
    print(
        f"SRC n={bundle['n']} cats={bundle['categories']} replay_fail={bundle['replay_failures']}",
        flush=True,
    )
    states, paths, gs, cats, locs8, locs9 = [], [], [], [], [], []
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        ids = identify_source_g6(end)
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(int(rec["full_cost"]))
        cats.append(rec["category"])
        locs8.append(ids["G6_8"])
        locs9.append(ids["G6_9"])
    audit = phase_a(states, locs8, locs9, cats)
    print(
        f"AUDIT8 depth={audit['G6_8']['cover_depth']} movable={audit['G6_8']['movable_cover']} 7d6d={audit['G6_8']['has_7d_6d']}",
        flush=True,
    )
    print(
        f"AUDIT9 depth={audit['G6_9']['cover_depth']} movable={audit['G6_9']['movable_cover']} 7d6d={audit['G6_9']['has_7d_6d']}",
        flush=True,
    )

    searches = {}
    rebuilt = {}
    remaining_searches = 2
    for target, locs in (("G6_8", locs8), ("G6_9", locs9)):
        remaining = global_deadline - time.perf_counter()
        budget = min(TIME_LIMIT_S, max(20.0, remaining / remaining_searches))
        print(f"SEARCH {target} budget={budget:.0f}s unique_cap={MAX_UNIQUE}", flush=True)
        res = search_exposure(
            states,
            paths,
            gs,
            cats,
            locs,
            target=target,
            max_unique=MAX_UNIQUE,
            time_limit_s=budget,
            rss_abort_mb=RSS_PER_MB,
            cost_ceiling=COST_CEILING,
        )
        rebuilt[target] = rebuild(opening, paths, gs, cats, res, target)
        searches[target] = res
        remaining_searches -= 1
        print(
            f"{target} reached={bool(rebuilt[target])} n={len(rebuilt[target])} "
            f"inc={res.incumbent} unique={res.unique} stop={res.stop_reason}",
            flush=True,
        )

    def persist_port(path, target, rows, search):
        bands = Counter(w["full_cost"] for w in rows)
        _write_json(
            path,
            {
                "experiment": EXPERIMENT,
                "target": target,
                "n": len(rows),
                "e0": None if not rows else min(w["full_cost"] for w in rows),
                "bands": {str(k): int(v) for k, v in sorted(bands.items())},
                "incumbent": search.incumbent,
                "states": rows,
            },
        )

    persist_port(G6_8_PORT, "G6_8", rebuilt["G6_8"], searches["G6_8"])
    persist_port(G6_9_PORT, "G6_9", rebuilt["G6_9"], searches["G6_9"])

    combined_map = {}
    for target, rows in rebuilt.items():
        for rec in rows:
            ident = rec["ordered_digest"]
            prev = combined_map.get(ident)
            if prev is None or rec["full_cost"] < prev["full_cost"]:
                combined_map[ident] = rec
            else:
                prev.setdefault("targets", [])
            rec.setdefault("targets", [target])
            if target not in rec["targets"]:
                rec["targets"].append(target)
    combined = sorted(combined_map.values(), key=lambda w: (w["full_cost"], w["ordered_digest"]))
    _write_json(
        COMBINED,
        {
            "experiment": EXPERIMENT,
            "n": len(combined),
            "from_g6_8": len(rebuilt["G6_8"]),
            "from_g6_9": len(rebuilt["G6_9"]),
            "states": combined,
        },
    )

    preview_counts = {"G6_8": Counter(), "G6_9": Counter()}
    c_states = []
    tail_states = []
    surprise_path = None
    foundation_reached = any(s.foundation_surprise for s in searches.values())
    for target, rows in rebuilt.items():
        for rec in rows:
            if time.perf_counter() >= global_deadline:
                preview_counts[target]["LIVE_BEYOND_6"] += 1
                rec["preview"] = "LIVE_BEYOND_6"
                continue
            end = opening.clone()
            replay_actions(end, as_actions(rec["full_actions"]))
            loc = tuple(rec["loc"]) if rec.get("loc") else None
            if loc is None:
                rec["preview"] = "FOUNDATION_2"
                preview_counts[target]["FOUNDATION_2"] += 1
                continue
            pr = preview_c(
                end,
                loc,
                rec["full_cost"],
                max_depth=6,
                deadline=min(global_deadline, time.perf_counter() + 1.5),
            )
            rec["preview"] = pr["status"]
            rec["preview_g"] = (pr.get("hit") or {}).get("g") if pr.get("hit") else rec["full_cost"] if pr["status"] in (
                "C_IMMEDIATE",
                "LOWER_TAIL_IMMEDIATE",
            ) else None
            preview_counts[target][pr["status"]] += 1
            if pr["status"] in ("C_IMMEDIATE", "C_WITHIN_6", "LOWER_TAIL_IMMEDIATE") or rec.get("c_immediate") or rec.get(
                "lower_tail_immediate"
            ):
                status = rec["preview"]
                if rec.get("lower_tail_immediate"):
                    status = "LOWER_TAIL_IMMEDIATE"
                    rec["preview"] = status
                    preview_counts[target][status] += 1
                elif rec.get("c_immediate") and status not in ("C_IMMEDIATE", "LOWER_TAIL_IMMEDIATE"):
                    status = "C_IMMEDIATE"
                    rec["preview"] = status
                    preview_counts[target][status] += 1
                c_states.append({**rec, "preview": status, "physical_6d": target})
            if rec.get("lower_tail_immediate") or pr.get("lower_tail"):
                tail_states.append({**rec, "physical_6d": target, "preview": rec["preview"]})
            if pr.get("foundation") and surprise_path is None:
                surprise_path = rec["full_actions"]
                foundation_reached = True

    if c_states:
        _write_json(
            C_PORT,
            {
                "experiment": EXPERIMENT,
                "n": len(c_states),
                "cheapest_full_mw": min(w["full_cost"] for w in c_states),
                "states": c_states,
            },
        )
    if tail_states:
        _write_json(
            TAIL_PORT,
            {
                "experiment": EXPERIMENT,
                "n": len(tail_states),
                "cheapest_full_mw": min(w["full_cost"] for w in tail_states),
                "states": tail_states,
            },
        )
    fixture = None
    if foundation_reached and surprise_path:
        FOUND_FIX.write_text(
            format_moves_text(as_actions(surprise_path), header="# v0.42 Diamond foundation surprise (Foundation 2)\n"),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()

    s8 = summarize_search(searches["G6_8"], rebuilt["G6_8"])
    s9 = summarize_search(searches["G6_9"], rebuilt["G6_9"])
    p8 = dict(preview_counts["G6_8"])
    p9 = dict(preview_counts["G6_9"])
    leader, leader_why = select_leader(s8, s9, p8, p9)

    def edge_hist(rows):
        return dict(Counter("+".join(w.get("edges_now") or w.get("edges") or []) for w in rows))

    all_preview = Counter()
    for c in preview_counts.values():
        all_preview.update(c)
    cheapest_c = None if not c_states else min(w.get("preview_g") or w["full_cost"] for w in c_states)
    cheapest_c_src = None if not c_states else min(c_states, key=lambda w: w.get("preview_g") or w["full_cost"]).get(
        "physical_6d"
    )

    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "foundation_reached": foundation_reached,
        "search8": s8,
        "search9": s9,
        "c_preview": dict(all_preview),
        "gateway_leader": leader,
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Sources {bundle['n']}/208. "
        f"G6_8 reached={s8['reached']} E={s8['best_full_mw']} "
        f"G6_9 reached={s9['reached']} E={s9['best_full_mw']}. "
        f"Leader={leader} ({leader_why}). C preview {dict(all_preview)}. "
        f"Lower-tail immediate {len(tail_states)}. SD5 never expanded."
    )
    heart = None
    sample = rebuilt["G6_8"][:1] or rebuilt["G6_9"][:1] or bundle["states"][:1]
    if sample:
        heart = sample[0].get("heart")
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, leader),
        "sources": {
            "n": bundle["n"],
            "categories": bundle["categories"],
            "all_replay_ok": bundle["all_replay_ok"],
            "replay_failures": bundle["replay_failures"],
            "cost_counts": dict(Counter(gs)),
        },
        "blocker_audit": audit,
        "search8": s8,
        "search9": s9,
        "c_preview": {
            "G6_8": p8,
            "G6_9": p9,
            "combined": dict(all_preview),
            "cheapest_c": cheapest_c,
            "cheapest_c_physical_6d": cheapest_c_src,
            "n_c_states": len(c_states),
        },
        "lower_tail": {
            "immediate": len(tail_states),
            "cheapest_full_mw": None if not tail_states else min(w["full_cost"] for w in tail_states),
        },
        "current_edges": {
            "exposure_g6_8": edge_hist(rebuilt["G6_8"]),
            "exposure_g6_9": edge_hist(rebuilt["G6_9"]),
            "post_c": edge_hist(c_states),
        },
        "gateway": {"leader": leader, "why": leader_why, "not_merely_cheapest_exposure": True},
        "foundation": {"reached": foundation_reached, "fixture": fixture},
        "cross_target": heart,
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "g6_8": G6_8_PORT.relative_to(ROOT).as_posix(),
            "g6_9": G6_9_PORT.relative_to(ROOT).as_posix(),
            "combined": COMBINED.relative_to(ROOT).as_posix(),
            "c_from_g6": C_PORT.relative_to(ROOT).as_posix() if C_PORT.exists() else None,
            "lower_tail": TAIL_PORT.relative_to(ROOT).as_posix() if TAIL_PORT.exists() else None,
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "sd5_expanded": bool(searches["G6_8"].sd5_expanded or searches["G6_9"].sd5_expanded),
        "all_replay_ok": bundle["all_replay_ok"],
        "gateway_leader": leader,
        "foundation_reached": foundation_reached,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"LEADER {leader} {leader_why}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
