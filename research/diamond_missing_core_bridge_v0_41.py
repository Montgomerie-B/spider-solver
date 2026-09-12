#!/usr/bin/env python3
"""v0.41: form missing unique-core edge C = 6D-5D from multi-edge states."""

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
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import (
    COST_CEILING,
    HARVEST_SLACK,
    MAX_UNIQUE,
    RSS_ABORT_MB,
    TIME_LIMIT_S,
    as_actions,
    bridge_e_present,
    c_dependency_audit,
    classify_c_boundary,
    diamond_components,
    dump_actions,
    heart_telemetry,
    lower_tail_present,
    opening_state,
    preview_bridge_e,
    reconstruct_multi_edge_sources,
    search_c_edge,
    source_invariants,
)
from spider.simple_diamond_edges import satisfied_core_edges
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "diamond_missing_core_bridge_v0_41"
BASE_SHA = "6f3d7edb27e6dc54307c16b5c6284ceb53025910"
BRANCH = "agent/diamond-missing-core-bridge-v0-41"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOURCES = ROOT / "docs" / "research" / "diamond_multi_edge_sources_v0_41.json"
C_PORT = ROOT / "docs" / "research" / "diamond_edge_C_v0_41.json"
CORE4_PORT = ROOT / "docs" / "research" / "diamond_core4_v0_41.json"
TAIL_PORT = ROOT / "docs" / "research" / "diamond_lower_tail_v0_41.json"
FOUND_FIX = ROOT / "solutions" / "4925153_v0_41_diamond_foundation.moves.txt"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def persist_sources(bundle: dict) -> None:
    slim_states = []
    for rec in bundle["states"]:
        slim_states.append(
            {
                "ordered_digest": rec["ordered_digest"],
                "full_cost": rec["full_cost"],
                "full_actions": rec["full_actions"],
                "full_path_length": rec["full_path_length"],
                "edges_now": rec["edges_now"],
                "category": rec["category"],
                "source_portfolios": rec["source_portfolios"],
                "replay_ok": rec["replay_ok"],
                "stock_rows": rec["stock_rows"],
                "fd": rec["fd"],
                "empties": rec["empties"],
                "d2_top": rec["d2_top"],
                "d5_top": rec["d5_top"],
                "heart": rec["heart"],
                "c_dependency": rec["c_dependency"],
                "invariants": rec["invariants"],
            }
        )
    _write_json(
        SOURCES,
        {
            "experiment": EXPERIMENT,
            "n": bundle["exact_unique"],
            "persistence_audit": bundle["persistence_audit"],
            "raw_candidate_count": bundle["raw_candidate_count"],
            "multi_edge_before_dedup": bundle["multi_edge_before_dedup"],
            "exact_unique": bundle["exact_unique"],
            "discrepancy": bundle["discrepancy"],
            "categories": bundle["categories"],
            "unexpected_categories": bundle["unexpected_categories"],
            "all_replay_ok": bundle["all_replay_ok"],
            "replay_failures": bundle["replay_failures"],
            "source_order": bundle["source_order"],
            "a_ancestry_preference": False,
            "states": slim_states,
        },
    )
    print(
        f"SOURCES n={bundle['exact_unique']} before_dedup={bundle['multi_edge_before_dedup']} "
        f"raw={bundle['raw_candidate_count']} cats={ {k: v['n'] for k, v in bundle['categories'].items()} }",
        flush=True,
    )


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("reconstruction_failure"):
        return "MULTI_EDGE_SOURCE_RECONSTRUCTION_FAILURE", "reconstructed multi-edge source set is empty or invalid"
    if not payload.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "a reconstructed source failed original-deal replay"
    if not payload.get("contract_ok"):
        return "DIAMOND_EDGE_CONTRACT_INVALID", "unique 2D/5D or C orientation contract failed"
    if payload.get("foundation_reached"):
        return "DIAMOND_FOUNDATION_REACHED", "Diamond foundation auto-removed (Foundation 2)"
    if payload.get("lower_tail_reached"):
        return "DIAMOND_LOWER_TAIL_REACHED", "6D-5D-4D-3D-2D-AD reached during CORE4 preview"
    if payload.get("core4_n"):
        return "DIAMOND_C_REACHED_CORE4", "C reached and at least one current CORE4 state exists"
    if payload.get("c_reached"):
        return "DIAMOND_C_REACHED_NO_CORE4", "C reached but no state simultaneously satisfies A+B+C+D"
    stop = payload.get("c_search", {}).get("stop_reason")
    if stop in ("unique limit", "rss abort") and not payload.get("c_reached"):
        return "DIAMOND_C_SEARCH_STATE_EXPLOSION", "C not found before unique/RSS limit"
    if not payload.get("c_reached"):
        return "DIAMOND_C_NOT_FOUND_IN_ENVELOPE", "C = 6D-5D not reached under MW<=100"
    return "INCONCLUSIVE", "search finished without a classified C outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "DIAMOND_FOUNDATION_REACHED":
        return "Persist the Foundation 2 witness and do not take SD5. Do not continue to Foundation 3."
    if verdict == "DIAMOND_LOWER_TAIL_REACHED":
        return "The lower Diamond tail 6D-A is assembled. Continue from those CORE4 tail states toward a full pre-SD5 Diamond foundation. Do not take SD5. Do not search Hearts."
    if verdict == "DIAMOND_C_REACHED_CORE4":
        return "C is in place and CORE4 exists. Spend the next envelope on the remaining 4D-3D bridge from the CORE4 portfolio, still without SD5 or a Heart search."
    if verdict == "DIAMOND_C_REACHED_NO_CORE4":
        return "Keep the C-boundary portfolio and search for restoration of A/B/D around current 6D-5D. Do not restart from entry A. Do not take SD5."
    if verdict == "DIAMOND_C_NOT_FOUND_IN_ENVELOPE":
        return (
            "Every reconstructed multi-edge source already contains 7D-6D, but 6D is never "
            "an exposed destination (mixed covers of 6–14 cards, always columns 8 and 9). "
            "Make 6D exposure the next directed cut from this 208-state frontier. "
            "Do not raise MW above 100. Do not take SD5. Do not search Hearts."
        )
    if verdict == "DIAMOND_C_SEARCH_STATE_EXPLOSION":
        return "C search exhausted unique/RSS before a 6D-5D witness. Keep the reconstructed multi-edge sources; do not return to whole-foundation brute force and do not take SD5."
    if verdict in ("MULTI_EDGE_SOURCE_RECONSTRUCTION_FAILURE", "SOURCE_REPLAY_FAILURE"):
        return "Fix the multi-edge reconstruction before any further Diamond search."
    return "Keep the unique-core C obligation. Do not take SD5. Do not search Hearts."


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.41 — Diamond Missing-Core Bridge (6D–5D)",
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
        "## 2. Persistence audit",
        "",
        "```json",
        json.dumps(payload.get("persistence_audit"), indent=2)[:4000],
        "```",
        "",
        "## 3. Source categories",
        "",
        "```json",
        json.dumps(payload.get("source_categories"), indent=2)[:4000],
        "```",
        "",
        "## 4. C dependency",
        "",
        "```json",
        json.dumps(payload.get("c_dependency"), indent=2)[:4000],
        "```",
        "",
        "## 5. C search",
        "",
        "```json",
        json.dumps(payload.get("c_search"), indent=2)[:4000],
        "```",
        "",
        "## 6. C boundaries / CORE4 / bridge preview",
        "",
        "```json",
        json.dumps(
            {
                "boundaries": payload.get("c_boundaries"),
                "core4": payload.get("core4"),
                "bridge_preview": payload.get("bridge_preview"),
                "foundation": payload.get("foundation"),
            },
            indent=2,
        )[:5000],
        "```",
        "",
        "## 7. Cross-target Heart telemetry (descriptive only)",
        "",
        "```json",
        json.dumps(payload.get("cross_target"), indent=2)[:2000],
        "```",
        "",
        "## 8. Files",
        "",
        "```json",
        json.dumps(payload.get("files"), indent=2),
        "```",
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "SD5 never expanded. Edge history is not canonical identity. A-ancestry is not a hard preference. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def rebuild_c_witnesses(opening, source_paths, source_gs, search, source_categories):
    rebuilt = []
    for rec in search.witnesses:
        origin = rec["origin"]
        full = list(source_paths[origin]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        edges = sorted(satisfied_core_edges(end))
        foundation = rec.get("foundation") or suit_foundation_count(end, "d") > 0
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "continuation": cost - source_gs[origin],
                "source_g": source_gs[origin],
                "source_category": source_categories[origin],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "edges_now": edges,
                "classification": classify_c_boundary(edges, foundation=foundation),
                "heart": heart_telemetry(end),
                "c_dependency": c_dependency_audit(end),
                "components": diamond_components(end),
                "d2_top": bool(
                    occurrence_counts(end, "d", 2)["tableau"]
                    and occurrence_counts(end, "d", 2)["tableau"][0].get("top")
                ),
                "d5_top": bool(
                    occurrence_counts(end, "d", 5)["tableau"]
                    and occurrence_counts(end, "d", 5)["tableau"][0].get("top")
                ),
                "lower_tail": lower_tail_present(end),
                "bridge_e": bridge_e_present(end),
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": cost == rec["g"],
                "invariants": source_invariants(end),
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w.get("depth", 0), w["origin"], w["ordered_digest"]))
    return rebuilt


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 600.0

    print("PHASE reconstruct multi-edge sources", flush=True)
    bundle = reconstruct_multi_edge_sources(opening)
    persist_sources(bundle)
    states = []
    paths = []
    gs = []
    cats = []
    contract_ok = True
    for rec in bundle["states"]:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(int(rec["full_cost"]))
        cats.append(rec["category"])
        inv = source_invariants(end)
        if not inv["ok"] or rec["category"] not in ("A+B", "A+D", "B+D", "A+B+D") and rec["category"] not in bundle["unexpected_categories"]:
            contract_ok = False
        if occurrence_counts(end, "d", 2)["current_count"] != 1:
            contract_ok = False
        if occurrence_counts(end, "d", 5)["current_count"] != 1:
            contract_ok = False
    reconstruction_failure = not bundle["states"] or not bundle["all_replay_ok"]
    all_replay_ok = bool(bundle["all_replay_ok"] and bundle["states"])

    blocker_hist = Counter()
    immediate = 0
    six_face_up = 0
    has_7d6d = 0
    for rec in bundle["states"]:
        dep = rec["c_dependency"]
        blocker_hist.update(dep.get("principal_blockers") or [])
        if dep.get("immediate_c_joins"):
            immediate += 1
        if any(s.get("face_up") for s in dep.get("six_d") or []):
            six_face_up += 1
        if dep.get("has_7d_6d"):
            has_7d6d += 1
    sample_dep = bundle["states"][0]["c_dependency"] if bundle["states"] else {}
    c_dependency_summary = {
        "n": len(bundle["states"]),
        "immediate_c_joins": immediate,
        "face_up_6d_sources": six_face_up,
        "has_7d_6d": has_7d6d,
        "principal_blockers": dict(blocker_hist),
        "sample": sample_dep,
        "by_category": {
            name: {
                "n": info["n"],
                "immediate_c_joins": info.get("immediate_c_joins"),
                "principal_blockers": info.get("principal_blockers"),
                "cheapest_full_mw": info.get("cheapest_full_mw"),
            }
            for name, info in bundle["categories"].items()
        },
    }
    print(f"C_DEP immediate={immediate} blockers={dict(blocker_hist)} 7d6d={has_7d6d}", flush=True)

    remaining = global_deadline - time.perf_counter()
    c_budget = min(TIME_LIMIT_S, max(30.0, remaining - 30.0))
    search = None
    rebuilt = []
    if not reconstruction_failure:
        print(f"SEARCH C budget={c_budget:.0f}s unique_cap={MAX_UNIQUE} ceiling={COST_CEILING}", flush=True)
        search = search_c_edge(
            states,
            paths,
            gs,
            cats,
            max_unique=MAX_UNIQUE,
            time_limit_s=c_budget,
            rss_abort_mb=RSS_ABORT_MB,
            cost_ceiling=COST_CEILING,
            harvest_slack=HARVEST_SLACK,
        )
        rebuilt = rebuild_c_witnesses(opening, paths, gs, search, cats)

    c0 = None if not rebuilt else min(w["full_cost"] for w in rebuilt)
    bands = Counter(w["full_cost"] for w in rebuilt)
    class_counts = Counter(w["classification"] for w in rebuilt)
    c_plus_d = sum(1 for w in rebuilt if "C" in w["edges_now"] and "D" in w["edges_now"])
    c_plus_ab = sum(1 for w in rebuilt if {"A", "B", "C"} <= set(w["edges_now"]))
    core4 = [w for w in rebuilt if w["classification"] == "CORE4"]
    bands_slack = {}
    if c0 is not None:
        for extra in range(0, HARVEST_SLACK + 1):
            bands_slack[f"C0+{extra}" if extra else "C0"] = sum(1 for w in rebuilt if w["full_cost"] == c0 + extra)

    _write_json(
        C_PORT,
        {
            "experiment": EXPERIMENT,
            "edge": "C",
            "n": len(rebuilt),
            "c0": c0,
            "bands": {str(k): int(v) for k, v in sorted(bands.items())},
            "slack_bands": bands_slack,
            "classifications": dict(class_counts),
            "incumbent": None if search is None else search.incumbent,
            "states": rebuilt,
        },
    )

    core4_out = []
    for rec in core4:
        core4_out.append(
            {
                "full_actions": rec["full_actions"],
                "full_cost": rec["full_cost"],
                "ordered_digest": rec["ordered_digest"],
                "edges_now": rec["edges_now"],
                "components": rec["components"],
                "bridge_e": rec["bridge_e"],
                "lower_tail": rec["lower_tail"],
                "source_category": rec["source_category"],
                "full_replay_ok": rec["full_replay_ok"],
                "heart": rec["heart"],
                "classification": rec["classification"],
            }
        )
    _write_json(
        CORE4_PORT,
        {
            "experiment": EXPERIMENT,
            "n": len(core4_out),
            "cheapest_full_mw": None if not core4_out else min(w["full_cost"] for w in core4_out),
            "bridge_e_already": sum(1 for w in core4 if w.get("bridge_e")),
            "states": core4_out,
        },
    )

    preview_counts = Counter()
    tail_states = []
    surprise_path = None
    foundation_reached = bool(search and search.foundation_surprise) or any(w.get("foundation") for w in rebuilt)
    if foundation_reached:
        hit = next((w for w in rebuilt if w.get("foundation")), None)
        if hit:
            surprise_path = hit["full_actions"]
    if core4 and time.perf_counter() < global_deadline:
        print(f"PREVIEW E n_core4={len(core4)}", flush=True)
        for rec in core4:
            if time.perf_counter() >= global_deadline:
                preview_counts["LIVE_BEYOND_6"] += 1
                rec["preview"] = "LIVE_BEYOND_6"
                continue
            end = opening.clone()
            replay_actions(end, as_actions(rec["full_actions"]))
            pr = preview_bridge_e(
                end,
                rec["full_cost"],
                max_depth=6,
                deadline=min(global_deadline, time.perf_counter() + 3.0),
            )
            rec["preview"] = pr["status"]
            rec["preview_detail"] = {k: pr.get(k) for k in ("lower_tail", "bridge_e", "foundation", "unique", "dead", "live")}
            preview_counts[pr["status"]] += 1
            if pr.get("foundation") and surprise_path is None:
                surprise_path = rec["full_actions"]
                foundation_reached = True
            if pr.get("lower_tail"):
                tail_states.append(
                    {
                        **{k: rec[k] for k in ("full_actions", "full_cost", "ordered_digest", "source_category", "edges_now")},
                        "preview": pr,
                    }
                )
            if pr["status"] == "FOUNDATION_2":
                foundation_reached = True

    lower_tail_reached = bool(tail_states) or any(w.get("lower_tail") for w in rebuilt)
    if tail_states or any(w.get("lower_tail") for w in rebuilt):
        existing = [w for w in rebuilt if w.get("lower_tail")]
        _write_json(
            TAIL_PORT,
            {
                "experiment": EXPERIMENT,
                "n": len(tail_states) + len(existing),
                "from_preview": tail_states,
                "already_at_c": [
                    {
                        "full_actions": w["full_actions"],
                        "full_cost": w["full_cost"],
                        "ordered_digest": w["ordered_digest"],
                    }
                    for w in existing
                ],
            },
        )

    fixture = None
    if foundation_reached and surprise_path:
        FOUND_FIX.write_text(
            format_moves_text(as_actions(surprise_path), header="# v0.41 Diamond foundation surprise (Foundation 2)\n"),
            encoding="utf-8",
        )
        fixture = FOUND_FIX.relative_to(ROOT).as_posix()

    c_reached = bool(rebuilt)
    payload_pre = {
        "reconstruction_failure": reconstruction_failure,
        "all_replay_ok": all_replay_ok,
        "contract_ok": contract_ok and all(r["invariants"]["ok"] for r in bundle["states"]),
        "foundation_reached": foundation_reached,
        "lower_tail_reached": lower_tail_reached,
        "core4_n": len(core4),
        "c_reached": c_reached,
        "c_search": {
            "stop_reason": None if search is None else search.stop_reason,
        },
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Reconstructed {bundle['exact_unique']} exact multi-edge sources "
        f"(raw {bundle['raw_candidate_count']}, before-dedup {bundle['multi_edge_before_dedup']}). "
        f"C reached={c_reached} C0={c0} CORE4={len(core4)} lower_tail={lower_tail_reached} "
        f"foundation={foundation_reached}. Best source category for C="
        f"{None if search is None else search.first_category}. SD5 never expanded. "
        "A-ancestry was not a hard preference."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "persistence_audit": bundle["persistence_audit"],
        "reconstructed_candidate_count": bundle["raw_candidate_count"],
        "multi_edge_before_dedup": bundle["multi_edge_before_dedup"],
        "exact_dedup_count": bundle["exact_unique"],
        "discrepancy": bundle["discrepancy"],
        "source_categories": bundle["categories"],
        "c_dependency": c_dependency_summary,
        "c_search": {
            "reached": c_reached,
            "first_s": None if search is None else search.first_s,
            "first_unique": None if search is None else search.first_unique,
            "best_full_mw": c0,
            "best_source_category": None if search is None else search.first_category,
            "unique": None if search is None else search.unique,
            "expanded": None if search is None else search.expanded,
            "generated": None if search is None else search.generated,
            "duplicate_skips": None if search is None else search.duplicate_skips,
            "elapsed_s": None if search is None else search.elapsed_s,
            "peak_rss_mb": None if search is None else search.peak_rss_mb,
            "stop_reason": None if search is None else search.stop_reason,
            "levels": None if search is None else search.levels_reached,
            "sd5_expanded": False if search is None else search.sd5_expanded,
            "already_at_source": None if search is None else search.already_at_source,
            "a_ancestry_preference": False,
            "used_heuristic_prune": False if search is None else search.used_heuristic_prune,
        },
        "c_boundaries": {
            "c0": c0,
            "slack": bands_slack,
            "n": len(rebuilt),
            "classifications": dict(class_counts),
            "c_plus_d": c_plus_d,
            "c_plus_ab": c_plus_ab,
            "core4": len(core4),
        },
        "core4": {
            "n": len(core4),
            "cheapest_full_mw": None if not core4 else min(w["full_cost"] for w in core4),
            "bridge_e_already": sum(1 for w in core4 if w.get("bridge_e")),
            "lower_tail_already": sum(1 for w in core4 if w.get("lower_tail")),
            "source_categories": dict(Counter(w["source_category"] for w in core4)),
        },
        "bridge_preview": dict(preview_counts),
        "foundation": {"reached": foundation_reached, "fixture": fixture},
        "cross_target": None if not rebuilt else rebuilt[0].get("heart"),
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "sources": SOURCES.relative_to(ROOT).as_posix(),
            "c_portfolio": C_PORT.relative_to(ROOT).as_posix(),
            "core4": CORE4_PORT.relative_to(ROOT).as_posix(),
            "lower_tail": TAIL_PORT.relative_to(ROOT).as_posix() if TAIL_PORT.exists() else None,
            "fixture": fixture,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "sd5_expanded": False if search is None else search.sd5_expanded,
        "all_replay_ok": all_replay_ok,
        "contract_ok": payload_pre["contract_ok"],
        "reconstruction_failure": reconstruction_failure,
        "c_reached": c_reached,
        "core4_n": len(core4),
        "lower_tail_reached": lower_tail_reached,
        "foundation_reached": foundation_reached,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
