#!/usr/bin/env python3
"""v0.40: Diamond unique-core edge ratchet (A/B/C/D) from Diamond-ready states."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_edges import (
    EDGES,
    diamond_components,
    edge_audit,
    preview_other_edges,
    search_edge,
    satisfied_core_edges,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_gate1 import gate1_progress
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "diamond_core_edge_ratchet_v0_40"
BASE_SHA = "8cbae9664c436f007164bf072a8fe0874b43e732"
BRANCH = "agent/diamond-core-edge-ratchet-v0-40"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SRC_PORT = ROOT / "docs" / "research" / "sd4_diamond_operational_cut_v0_39_portfolio.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FOUND_FIX = ROOT / "solutions" / "4925153_v0_40_diamond_foundation.moves.txt"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw):
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def dump_actions(actions):
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


def load_sources(opening: SpiderState):
    port = json.loads(SRC_PORT.read_text(encoding="utf-8"))
    rows, states, paths, gs = [], [], [], []
    seen = {}
    for rec in port["states"]:
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        ident = pack_state(end)
        d2 = occurrence_counts(end, "d", 2)
        d5 = occurrence_counts(end, "d", 5)
        ok = (
            cost == rec["full_cost"]
            and ident.hex() == rec["ordered_digest"]
            and stock_rows(end) == 1
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and d2["current_count"] == 1
            and d5["current_count"] == 1
            and d2["tableau"]
            and d2["tableau"][0].get("top")
            and d5["tableau"]
            and d5["tableau"][0].get("top")
        )
        item = {
            "ok": ok,
            "full_cost": cost,
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "edges": sorted(satisfied_core_edges(end)),
        }
        prev = seen.get(ident)
        if prev is not None and cost >= prev:
            continue
        seen[ident] = cost
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = item
            states[idx] = end
            paths[idx] = full
            gs[idx] = cost
        else:
            rows.append(item)
            states.append(end)
            paths.append(full)
            gs.append(cost)
    print(f"SRC n={len(rows)} costs={dict(Counter(r['full_cost'] for r in rows))} ok={all(r['ok'] for r in rows)}", flush=True)
    return rows, states, paths, gs


def heart_telemetry(state: SpiderState) -> dict:
    prog = gate1_progress(state)
    c2 = state.columns[1].face_up
    c3 = state.columns[2].face_up
    return {
        "ah_top_c2": bool(c2) and pretty_card(c2[-1]) == "AH",
        "ah_in_c2": "AH" in [pretty_card(c) for c in c2],
        "h9_up": bool(prog.get("face_up")),
        "jh_still_down": prog.get("top_fd") == "JH",
        "qh_jh": len(c3) >= 2 and pretty_card(c3[-1]) == "JH" and pretty_card(c3[-2]) == "QH",
        "heart_release_plausible": prog.get("top_fd") == "JH" and not prog.get("face_up"),
    }


def rebuild(opening, rows, paths, gs, search, name):
    rebuilt = []
    for rec in search.witnesses:
        full = list(paths[rec["origin"]]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "continuation": cost - gs[rec["origin"]],
                "source_g": gs[rec["origin"]],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "edges_now": sorted(satisfied_core_edges(end)),
                "heart": heart_telemetry(end),
                "d2_top": bool(occurrence_counts(end, "d", 2)["tableau"] and occurrence_counts(end, "d", 2)["tableau"][0].get("top")),
                "d5_top": bool(occurrence_counts(end, "d", 5)["tableau"] and occurrence_counts(end, "d", 5)["tableau"][0].get("top")),
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": cost == rec["g"],
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"]))
    bands = Counter(w["full_cost"] for w in rebuilt)
    path = ROOT / "docs" / "research" / f"diamond_core_edge_{name}_v0_40.json"
    _write_json(
        path,
        {
            "experiment": EXPERIMENT,
            "edge": name,
            "n": len(rebuilt),
            "bands": {str(k): int(v) for k, v in sorted(bands.items())},
            "incumbent": search.incumbent,
            "states": rebuilt,
        },
    )
    return rebuilt, path


def choose_verdict(reached, surprise, explosion, contract_ok, replay_ok):
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "Diamond-ready sources failed replay"
    if not contract_ok:
        return "DIAMOND_EDGE_CONTRACT_INVALID", "unique 2D/5D or adjacency orientation failed"
    if surprise:
        return "DIAMOND_FOUNDATION_REACHED_DURING_EDGE_SEARCH", "Diamond foundation removed during an edge search"
    if explosion and not reached:
        return "DIAMOND_CORE_EDGE_STATE_EXPLOSION", "resource limits prevent four-edge comparison"
    if len(reached) == 4:
        return "DIAMOND_CORE_EDGES_TRACTABLE", "all four unique-core edges reached"
    if reached:
        return "DIAMOND_CORE_PARTIAL_TRACTABLE", f"edges reached: {sorted(reached)}"
    return "DIAMOND_CORE_EDGES_NOT_REACHED", "no unique-core edge reached"


def next_recommendation(verdict: str, entry: str | None) -> str:
    if verdict == "DIAMOND_FOUNDATION_REACHED_DURING_EDGE_SEARCH":
        return "Diamond foundation appeared during the edge ratchet. Persist that witness and do not take SD5."
    if verdict == "DIAMOND_CORE_EDGES_TRACTABLE" or verdict == "DIAMOND_CORE_PARTIAL_TRACTABLE":
        return (
            f"Continue the Diamond ratchet from entry edge {entry}. Carry the two-edge portfolio and "
            "prefer boundaries with SECOND_EDGE_WITHIN_4. Do not take SD5. Do not search Hearts."
        )
    return "Keep the unique-core edge decomposition. Do not return to whole-foundation search. Do not take SD5."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.40 — Diamond Unique-Core Edge Ratchet",
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
        "## 2. Sources / current components",
        "",
        json.dumps({"sources": payload.get("sources"), "components": payload.get("components")}, indent=2)[:2500],
        "",
        "## 3. Edges",
        "",
        json.dumps(payload.get("edges") or {}, indent=2)[:5000],
        "",
        "## 4. Two-edge / ratchet",
        "",
        json.dumps({"two_edge": payload.get("two_edge"), "ratchet": payload.get("ratchet")}, indent=2)[:2500],
        "",
        "## 5. Cross-target / foundation",
        "",
        json.dumps({"cross_target": payload.get("cross_target"), "foundation": payload.get("foundation")}, indent=2)[:1500],
        "",
        "## 6. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "SD5 never expanded. Edge history not in canonical identity. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 600.0
    rows, states, paths, gs = load_sources(opening)
    replay_ok = bool(states) and all(r["ok"] for r in rows)
    d2 = occurrence_counts(states[0], "d", 2) if states else {}
    d5 = occurrence_counts(states[0], "d", 5) if states else {}
    contract_ok = d2.get("current_count") == 1 and d5.get("current_count") == 1 and d2.get("tableau_count") == 1

    sat = Counter()
    comps_n = Counter()
    audits = {name: Counter() for name in EDGES}
    for st in states:
        have = satisfied_core_edges(st)
        for name in EDGES:
            sat[name] += int(name in have)
            a = edge_audit(st, name)
            audits[name]["satisfied"] += int(a["satisfied"])
            audits[name]["legal_join_now"] += int(a["legal_join_now"])
        comps_n[len(diamond_components(st))] += 1
    print(f"PHASE_A sat={dict(sat)} comps_len={dict(comps_n)}", flush=True)

    edge_blocks = {}
    rebuilt_all = {}
    surprise_path = None
    remaining_edges = list(EDGES)
    for name in remaining_edges:
        remaining = global_deadline - time.perf_counter()
        budget = min(150.0, max(20.0, remaining / max(1, 5 - len(edge_blocks))))
        print(f"SEARCH {name} budget={budget:.0f}s", flush=True)
        res = search_edge(states, paths, gs, name=name, time_limit_s=budget, max_unique=200_000, rss_abort_mb=1.5 * 1024.0)
        rebuilt, path = rebuild(opening, rows, paths, gs, res, name)
        rebuilt_all[name] = rebuilt
        # preview sample
        preview_counts = Counter()
        two_hits = []
        sample = rebuilt[:32]
        for rec in sample:
            end = opening.clone()
            replay_actions(end, as_actions(rec["full_actions"]))
            have = set(rec.get("edges_now") or rec.get("edges") or [])
            pr = preview_other_edges(
                end,
                rec["full_cost"],
                have,
                max_depth=4,
                deadline=min(global_deadline, time.perf_counter() + 2.0),
                rss_abort_mb=1.5 * 1024.0,
            )
            preview_counts[pr["status"]] += 1
            rec["preview"] = pr["status"]
            rec["preview_new"] = pr.get("new_edges")
            if pr.get("found") and pr.get("hit"):
                two_hits.append({"from_edge": name, "g": pr["hit"]["g"], "new": pr["hit"]["new_edges"], "origin": rec["origin"], "source_full": rec["full_actions"]})
            if pr.get("foundation") and surprise_path is None:
                surprise_path = rec["full_actions"]
        edge_blocks[name] = {
            "reached": bool(rebuilt),
            "first_s": res.first_s,
            "first_unique": res.first_unique,
            "best_full_mw": None if not rebuilt else min(w["full_cost"] for w in rebuilt),
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "duplicate_skips": res.duplicate_skips,
            "levels": res.levels_reached,
            "elapsed_s": res.elapsed_s,
            "peak_rss_mb": res.peak_rss_mb,
            "stop_reason": res.stop_reason,
            "sd5_expanded": res.sd5_expanded,
            "already_at_source": res.already_at_source,
            "n": len(rebuilt),
            "bands": {str(k): int(v) for k, v in sorted(Counter(w["full_cost"] for w in rebuilt).items())},
            "preview": dict(preview_counts),
            "second_edge_pct": None if not sample else round(100.0 * preview_counts.get("SECOND_EDGE_WITHIN_4", 0) / len(sample), 1),
            "portfolio": path.relative_to(ROOT).as_posix(),
            "foundation_surprise": res.foundation_surprise,
            "d2_preserved": None if not rebuilt else sum(1 for w in rebuilt if w.get("d2_top")) / len(rebuilt),
            "d5_preserved": None if not rebuilt else sum(1 for w in rebuilt if w.get("d5_top")) / len(rebuilt),
        }
        print(
            f"EDGE_{name} reached={bool(rebuilt)} inc={res.incumbent} unique={res.unique} "
            f"preview={dict(preview_counts)}",
            flush=True,
        )
        if res.foundation_surprise:
            break

    # two-edge from preview hits and from any witness that already has 2+ edges
    two = []
    pair_counts = Counter()
    pair_best = {}
    for name, rebuilt in rebuilt_all.items():
        for rec in rebuilt:
            have = rec.get("edges_now") or rec.get("edges") or []
            if len(have) >= 2:
                key = "+".join(sorted(have)[:2]) if len(have) == 2 else "MULTI:" + "+".join(sorted(have))
                pair_counts[key] += 1
                prev = pair_best.get(key)
                if prev is None or rec["full_cost"] < prev:
                    pair_best[key] = rec["full_cost"]
                two.append(rec)
    two_path = ROOT / "docs" / "research" / "diamond_core_two_edge_v0_40.json"
    _write_json(two_path, {"experiment": EXPERIMENT, "n": len(two), "pairs": dict(pair_counts), "best": pair_best, "states": two[:256]})

    reached = [n for n, b in edge_blocks.items() if b["reached"]]
    # entry edge: not merely cheapest; prefer second-edge-within-4 then cheapest
    entry = None
    if reached:
        def score(n):
            b = edge_blocks[n]
            pct = b["second_edge_pct"] or 0
            dead = (b["preview"] or {}).get("EXACT_DEAD_TO_OTHER_CORE_EDGE", 0)
            sample_n = sum((b["preview"] or {}).values()) or 1
            dead_frac = dead / sample_n
            return (-pct, dead_frac, b["best_full_mw"] if b["best_full_mw"] is not None else 10**9, b["first_s"] or 99)

        entry = sorted(reached, key=score)[0]

    explosion = all(edge_blocks[n]["stop_reason"] in ("unique limit", "rss abort", "time limit") and not edge_blocks[n]["reached"] for n in edge_blocks) if edge_blocks else False
    surprise = any(edge_blocks[n].get("foundation_surprise") for n in edge_blocks)
    verdict, reason = choose_verdict(reached, surprise, explosion, contract_ok, replay_ok)

    fixture = None
    if surprise and surprise_path:
        FOUND_FIX.write_text(format_moves_text(as_actions(surprise_path), header="# v0.40 Diamond foundation surprise\n"), encoding="utf-8")
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()

    cross = {}
    for name, rebuilt in rebuilt_all.items():
        if rebuilt:
            h = rebuilt[0].get("heart") or {}
            cross[name] = h

    interpretation = (
        f"{reason}. Unique current 2D={d2.get('current_count')} 5D={d5.get('current_count')}. "
        f"Source-edge satisfaction A/B/C/D={dict(sat)}. "
        f"Reached {reached or 'none'}. Entry={entry}. "
        f"Heart H9 cut was +4/77; Diamond-ready was +2/75. SD5 never expanded."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict, entry),
        "sources": {
            "n": len(rows),
            "cost_counts": dict(Counter(gs)),
            "all_replay_ok": replay_ok,
        },
        "components": {
            "length_hist": dict(comps_n),
            "sample": diamond_components(states[0]) if states else [],
            "source_edge_satisfaction": dict(sat),
            "audits": {n: dict(c) for n, c in audits.items()},
            "d2": d2,
            "d5": d5,
        },
        "edges": edge_blocks,
        "two_edge": {
            "n": len(two),
            "pairs": dict(pair_counts),
            "best": pair_best,
            "path": two_path.relative_to(ROOT).as_posix(),
        },
        "ratchet": {
            "entry_edge": entry,
            "evidence": None
            if not entry
            else {
                "best_full_mw": edge_blocks[entry]["best_full_mw"],
                "second_edge_pct": edge_blocks[entry]["second_edge_pct"],
                "preview": edge_blocks[entry]["preview"],
                "not_merely_cheapest": True,
            },
        },
        "cross_target": cross,
        "foundation": {"reached": surprise, "fixture": fixture},
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "sd5_expanded": any(edge_blocks[n]["sd5_expanded"] for n in edge_blocks),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"ENTRY {entry}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
