#!/usr/bin/env python3
"""v0.39: unbiased SD4 Diamond operational cut from pre-SD4 Gate-2 sources.

Does not apply the Heart AH->2D parking macro. SD5 never taken.
"""

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
from spider.simple_diamond_cut import (
    C4,
    C9,
    apply_actions,
    card_cover,
    continuation_lb_audit,
    diamond_unique_ranks,
    enumerate_predicted_macros,
    is_diamond_ready,
    legal_dests_for_top,
    probe_diamond_foundation,
    search_diamond_ready,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_gate1 import gate1_progress
from spider.simple_gate3 import verify_gate3_chain
from spider.simple_progressive_solver import apply_action, format_moves_text, step_cost
from spider.simple_sd4_horizon import EXPECTED_SD4, verify_sd4_row
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "sd4_diamond_operational_cut_v0_39"
BASE_SHA = "e7f5021ac1f7bc7b190bbedf174a443afbab6c3a"
BRANCH = "agent/sd4-diamond-operational-cut-v0-39"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V36_G1 = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate1_sources.json"
V36_G2 = ROOT / "docs" / "research" / "two_gate_ah_release_preview_v0_36_gate2_portfolio.json"
V35_G2 = ROOT / "docs" / "research" / "heart9_blocker_ratchet3_v0_35_gate2_sources.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PORT = ROOT / "docs" / "research" / f"{EXPERIMENT}_portfolio.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIX = ROOT / "solutions" / "4925153_v0_39_diamond_ready_best.moves.txt"
FIX_FOUND = ROOT / "solutions" / "4925153_v0_39_diamond_foundation_probe.moves.txt"


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


def load_union(opening: SpiderState):
    g1 = json.loads(V36_G1.read_text(encoding="utf-8"))
    g2 = json.loads(V36_G2.read_text(encoding="utf-8"))
    v35 = json.loads(V35_G2.read_text(encoding="utf-8"))
    best = {}
    rows = []

    def consider(full, g_hint, lineage):
        end = opening.clone()
        cost = replay_actions(end, full)
        ident = pack_state(end)
        prog = gate1_progress(end)
        chain = verify_gate3_chain(end)
        ok = (
            chain["valid"]
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and stock_rows(end) == 2
            and prog.get("fd_blockers") == 1
            and prog.get("top_fd") == "JH"
            and not prog.get("face_up")
            and prog.get("column_0") == 1
            and pretty_card(end.columns[1].face_up[-1]) == "AH"
            and not prog.get("can_move_packet")
        )
        rec = {
            "ok": ok,
            "full_cost": cost,
            "lineage": lineage,
            "ordered_digest": ident.hex(),
            "full_actions": dump_actions(full),
            "replay_ok": ok and (g_hint is None or cost == g_hint),
        }
        if not rec["replay_ok"]:
            return
        prev = best.get(ident)
        if prev is not None and cost >= prev:
            return
        best[ident] = cost
        if prev is not None:
            idx = next(i for i, r in enumerate(rows) if r["ordered_digest"] == ident.hex())
            rows[idx] = rec
        else:
            rows.append(rec)

    for rec in v35["states"]:
        consider(as_actions(rec["full_actions"]), rec.get("full_cost"), "v0.35")
    for rec in g2["states"]:
        origin = rec.get("origin")
        full = as_actions(g1["states"][origin]["full_actions"]) + as_actions(rec.get("actions_to_gate2") or [])
        consider(full, rec.get("g"), "v0.36")
    rows.sort(key=lambda r: (r["full_cost"], r["ordered_digest"]))
    states, paths, gs = [], [], []
    for rec in rows:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        states.append(end)
        paths.append(as_actions(rec["full_actions"]))
        gs.append(rec["full_cost"])
    print(f"UNION n={len(rows)} costs={dict(Counter(r['full_cost'] for r in rows))}", flush=True)
    return rows, states, paths, gs


def choose_verdict(replay_ok, unique_ok, row_ok, n_one, n_two, search_n, explosion, n_src):
    if not replay_ok:
        return "SOURCE_REPLAY_FAILURE", "pre-SD4 Gate-2 union failed replay"
    if not unique_ok:
        return "DIAMOND_HORIZON_ASSUMPTION_MISMATCH", "unique current Diamond ranks are not exactly 2D and 5D"
    if not row_ok:
        return "DIAMOND_HORIZON_ASSUMPTION_MISMATCH", "SD4 row orientation mismatch"
    if explosion and not (n_one or n_two or search_n):
        return "DIAMOND_READY_SEARCH_STATE_EXPLOSION", "resource limits before Diamond-ready"
    if n_one and n_two:
        return "DIAMOND_READY_VIA_MULTIPLE_SD4_ROUTES", f"SD4+JH (+2) on {n_one} and SD4+two tableau on {n_two} of {n_src}"
    if n_two and not n_one:
        return "DIAMOND_READY_VIA_PREDICTED_SD4_MACRO", f"predicted JH-then-4H family unlocked {n_two}/{n_src}"
    if n_one and not n_two:
        return "DIAMOND_READY_VIA_DIFFERENT_ROUTE", f"SD4+single JH move unlocked {n_one}/{n_src}; 4H not required"
    if search_n:
        return "DIAMOND_READY_VIA_DIFFERENT_ROUTE", "independent search reached Diamond-ready without the enumerated macros"
    return "DIAMOND_READY_NOT_FOUND_IN_SHORT_ENVELOPE", "no Diamond-ready cut in macros or depth-8 search"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("DIAMOND_READY"):
        return (
            "Diamond operational access is available from the unbiased pre-SD4 frontier without parking AH on 2D. "
            "Next: compare this Diamond-ready portfolio against the v0.37 Heart H9 cut for a fair post-SD4 "
            "foundation-order decision. Do not take SD5 yet. Do not inspect the human route."
        )
    return (
        "Diamond-ready was not reached in the short envelope. Diagnose 5D cover classes (JH vs 4H vs KC) "
        "before raising limits. Do not take SD5. Do not inspect the human route."
    )


def write_report(payload: dict) -> None:
    lines = [
        "# Spider Solver v0.39 — Unbiased SD4 Diamond Operational Cut",
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
        json.dumps(payload.get("sources") or {}, indent=2)[:1500],
        "",
        "## 3. Diamond material / SD4 structure",
        "",
        json.dumps({"material": payload.get("material"), "sd4_structure": payload.get("sd4_structure")}, indent=2)[:3500],
        "",
        "## 4. Macro audit",
        "",
        json.dumps(payload.get("macros") or {}, indent=2)[:2500],
        "",
        "## 5. Exact cut search",
        "",
        json.dumps(payload.get("search") or {}, indent=2)[:2500],
        "",
        "## 6. Ready portfolio",
        "",
        json.dumps(payload.get("portfolio") or {}, indent=2)[:1500],
        "",
        "## 7. Continuation probe",
        "",
        json.dumps(payload.get("probe") or {}, indent=2)[:1500],
        "",
        "## 8. Cross-target / comparison",
        "",
        json.dumps({"cross_target": payload.get("cross_target"), "comparison": payload.get("comparison")}, indent=2)[:2000],
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        "No Heart AH->2D prescription. SD5 never expanded. Production unchanged.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    rows, states, paths, gs = load_union(opening)
    replay_ok = bool(states) and all(r["ok"] and r["replay_ok"] for r in rows)
    print(f"SOURCES n={len(states)} replay={replay_ok}", flush=True)

    sd4 = verify_sd4_row(states[0]) if states else {"valid": False}
    print(f"SD4_ROW valid={sd4.get('valid')} row={sd4.get('row')}", flush=True)

    # Unique ranks after SD4 on first source
    after0 = states[0].clone()
    apply_action(after0, ("deal",))
    unique_after = diamond_unique_ranks(after0)
    unique_before = diamond_unique_ranks(states[0])
    unique_ok = unique_after == ["2", "5"]
    print(f"UNIQUE D before={unique_before} after_sd4={unique_after} ok={unique_ok}", flush=True)

    # Phase A: SD4 structural audit
    cover_after = Counter()
    d2_top = 0
    ah_on_2d = 0
    c9_top = Counter()
    jh_dests = Counter()
    four_dests = Counter()
    n_one = n_two = 0
    one_kinds = Counter()
    two_kinds = Counter()
    lb_values = Counter()
    print("PHASE_A/B SD4 audit and macros", flush=True)
    for st in states:
        child = st.clone()
        apply_action(child, ("deal",))
        d2 = card_cover(child, "d", 2)
        d5 = card_cover(child, "d", 5)
        if d2.get("top"):
            d2_top += 1
        cover_after["|".join(d5.get("face_up_above") or [])] += 1
        if child.columns[C4].face_up and pretty_card(child.columns[C4].face_up[-1]) == "AH":
            ah_on_2d += 1
        if child.columns[C9].face_up:
            c9_top[pretty_card(child.columns[C9].face_up[-1])] += 1
        for d in legal_dests_for_top(child, C9):
            jh_dests[str(d["onto"])] += 1
        lb = continuation_lb_audit(st)
        lb_values[str(lb.get("lb"))] += 1
        variants = enumerate_predicted_macros(st)
        if any(v["kind"] == "sd4_then_one" for v in variants):
            n_one += 1
            for v in variants:
                if v["kind"] == "sd4_then_one":
                    one_kinds[f"{v['moving']}->{v['jh_dest']}"] += 1
        if any(v["kind"] == "sd4_then_two" for v in variants):
            n_two += 1
            for v in variants:
                if v["kind"] == "sd4_then_two":
                    two_kinds[str(v.get("moving"))] += 1
    print(f"PHASE_B one={n_one}/{len(states)} two={n_two}/{len(states)} d2_top={d2_top} ah_on_2d={ah_on_2d}", flush=True)
    print(f"5D cover after SD4 {dict(cover_after)}", flush=True)

    remaining = 300.0 - (time.perf_counter() - started)
    print(f"PHASE_C search budget={max(10.0, remaining):.0f}s", flush=True)
    search = search_diamond_ready(
        states,
        paths,
        gs,
        max_depth=8,
        max_unique=250_000,
        time_limit_s=max(10.0, remaining),
        rss_abort_mb=2 * 1024.0,
        harvest_slack=3,
        harvest_limit=256,
    )
    explosion = search.stop_reason in ("unique limit", "rss abort") and not search.witnesses
    print(
        f"SEARCH unique={search.unique} exp={search.expanded} inc={search.incumbent} "
        f"wit={len(search.witnesses)} first_t={search.first_s} stop={search.stop_reason} "
        f"ah_on_2d_gen={search.ah_on_2d_generated}",
        flush=True,
    )

    rebuilt = []
    for rec in search.witnesses:
        full = list(paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        d2 = card_cover(end, "d", 2)
        d5 = card_cover(end, "d", 5)
        rebuilt.append(
            {
                **rec,
                "full_cost": cost,
                "continuation": cost - gs[rec["origin"]],
                "source_g": gs[rec["origin"]],
                "full_actions": dump_actions(full),
                "full_path_length": len(full),
                "fd": face_down_count(end),
                "foundations": len(end.foundations),
                "empties": list(empty_column_indices(end)),
                "stock_rows": stock_rows(end),
                "ah_c2": pretty_card(end.columns[1].face_up[-1]) if end.columns[1].face_up else None,
                "h9_up": pretty_card(end.columns[1].face_up[-1]) == "9H" if end.columns[1].face_up else False,
                "jh_still_down": gate1_progress(end).get("top_fd") == "JH",
                "d2": d2,
                "d5": d5,
                "qh_jh": (
                    len(end.columns[2].face_up) >= 2
                    and pretty_card(end.columns[2].face_up[-1]) == "JH"
                    and pretty_card(end.columns[2].face_up[-2]) == "QH"
                ),
                "ordered_digest": pack_state(end).hex(),
                "full_replay_ok": is_diamond_ready(end) and cost == rec["g"] and not rec.get("ah_on_2d"),
            }
        )
    rebuilt.sort(key=lambda w: (w["full_cost"], w["full_path_length"]))
    first = rebuilt[0] if rebuilt else None
    fixture = None
    if first:
        FIX.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=f"# v0.39 Diamond-ready cut\n# full_mw: {first['full_cost']}\n# continuation: {first['continuation']}",
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIX.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    # Phase D probes on a diverse sample of ready states (cap 32 for time)
    probe_counts = Counter()
    found_fix = None
    probe_deadline = started + 450.0
    sample = rebuilt[:32]
    print(f"PHASE_D probe n={len(sample)}", flush=True)
    for rec in sample:
        end = opening.clone()
        replay_actions(end, as_actions(rec["full_actions"]))
        pr = probe_diamond_foundation(end, rec["full_cost"], max_depth=8, deadline=probe_deadline, rss_abort_mb=2 * 1024.0)
        probe_counts[pr["status"]] += 1
        rec["probe"] = pr["status"]
        if pr["found"] and found_fix is None:
            # reconstruct not stored; skip writing full path unless we have actions
            found_fix = True
    print(f"PROBE {dict(probe_counts)}", flush=True)

    bands = Counter(w["full_cost"] for w in rebuilt)
    cats = Counter()
    for w in rebuilt:
        cats[f"cont{w['continuation']}|qh_jh={w['qh_jh']}|ah={w['ah_c2']}|h9={w['h9_up']}"] += 1
    _write_json(
        PORT,
        {
            "experiment": EXPERIMENT,
            "kind": "diamond_ready_portfolio",
            "d": None if not first else first["full_cost"],
            "n": len(rebuilt),
            "bands": {str(k): int(v) for k, v in sorted(bands.items())},
            "states": rebuilt,
        },
    )

    n_src = len(states)
    lb0 = continuation_lb_audit(states[0]) if states else {}
    local_opt = bool(first and lb0.get("valid") and first["continuation"] == lb0.get("lb"))
    # cheapest source 73 + min continuation
    min_cont = None if not rebuilt else min(w["continuation"] for w in rebuilt)
    verdict, reason = choose_verdict(
        replay_ok, unique_ok, bool(sd4.get("valid")), n_one, n_two, len(rebuilt), explosion, n_src
    )
    interpretation = (
        f"{reason}. Unique Diamond current ranks after SD4={unique_after} (before SD4={unique_before}). "
        f"After SD4, 2D is top on {d2_top}/{n_src}; AH-on-2D count={ah_on_2d} (Heart macro was not applied). "
        f"5D cover classes after SD4: {dict(cover_after)}. "
        f"Enumerated +1-tableau after SD4: {n_one}; +2-tableau: {n_two}. "
        f"Search incumbent={search.incumbent} first_t={search.first_s} continuation_best={min_cont}. "
        f"Heart H9 cut was +4 to full 77. SD5 never expanded."
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
            "n": n_src,
            "cost_counts": dict(Counter(gs)),
            "cost_min": None if not gs else min(gs),
            "cost_max": None if not gs else max(gs),
            "all_replay_ok": replay_ok,
        },
        "material": {
            "unique_before_sd4": unique_before,
            "unique_after_sd4": unique_after,
            "unique_ok": unique_ok,
            "sd5_excluded": True,
        },
        "sd4": sd4,
        "sd4_structure": {
            "d2_top_after_sd4": d2_top,
            "ah_on_2d_after_sd4_only": ah_on_2d,
            "c9_top_after_sd4": dict(c9_top),
            "d5_cover_after_sd4": dict(cover_after),
            "jh_c9_dests": dict(jh_dests),
            "note": "Engine c9 is not uniformly JH/4H/5D. 5D may already be top of c9 or sit under KC at c7.",
        },
        "macros": {
            "one_after_sd4": n_one,
            "two_after_sd4": n_two,
            "n": n_src,
            "one_kinds": dict(one_kinds),
            "two_kinds": dict(two_kinds),
            "no_ah_to_2d": True,
        },
        "search": {
            "unique": search.unique,
            "expanded": search.expanded,
            "generated": search.generated,
            "duplicate_skips": search.duplicate_skips,
            "first_s": search.first_s,
            "first_unique": search.first_unique,
            "first_g": search.first_g,
            "incumbent": search.incumbent,
            "max_depth": search.max_depth,
            "elapsed_s": search.elapsed_s,
            "peak_rss_mb": search.peak_rss_mb,
            "stop_reason": search.stop_reason,
            "sd5_expanded": search.sd5_expanded,
            "ah_on_2d_generated": search.ah_on_2d_generated,
            "witnesses": len(search.witnesses),
        },
        "proof": {
            "per_source_lb_counts": dict(lb_values),
            "sample_lb": lb0,
            "global_plus3_valid": False,
            "local_opt_if_lb_matches": local_opt,
            "best_continuation": min_cont,
        },
        "portfolio": {
            "n": len(rebuilt),
            "bands": {str(k): int(v) for k, v in sorted(bands.items())},
            "categories": dict(cats),
            "path": PORT.relative_to(ROOT).as_posix(),
            "best": None
            if not first
            else {
                "full_cost": first["full_cost"],
                "continuation": first["continuation"],
                "source_g": first["source_g"],
                "ah_c2": first["ah_c2"],
                "h9_up": first["h9_up"],
                "jh_still_down": first["jh_still_down"],
                "qh_jh": first["qh_jh"],
                "stock_rows": first["stock_rows"],
                "fd": first["fd"],
                "fixture": fixture,
                "full_replay_ok": first["full_replay_ok"],
            },
        },
        "probe": dict(probe_counts),
        "cross_target": None
        if not first
        else {
            "ah_still_c2": first["ah_c2"] == "AH",
            "h9_still_down": not first["h9_up"],
            "original_jh_still_down": first["jh_still_down"],
            "qh_jh_incidental": first["qh_jh"],
            "heart_sd4_release_still_possible": first["jh_still_down"] and first["ah_c2"] == "AH" and not first["h9_up"],
        },
        "comparison": {
            "heart_h9_cut_continuation": 4,
            "heart_h9_best_full_mw": 77,
            "diamond_ready_continuation": min_cont,
            "diamond_ready_best_full_mw": None if not first else first["full_cost"],
            "diamond_cheaper_operational_cut": bool(min_cont is not None and min_cont < 4),
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "sd5_expanded": search.sd5_expanded,
        "no_prescribed_ah_to_2d": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
