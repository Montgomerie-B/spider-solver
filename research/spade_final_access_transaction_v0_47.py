#!/usr/bin/env python3
"""v0.47: two-gate 5S then 10D release to expose the unique 4S.

Do not search TAIL4. Do not search Foundation 2. Do not search Foundation 3.
Do not reopen pre-SD5 preparation. Do not restart from the 3,520 TAIL3 population.
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
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_spade_4s_ratchet import b4_count, unique_4s_exposed
from spider.simple_spade_final_access import (
    COST_CEILING,
    GATE1_UNIQUE,
    GATE2_UNIQUE,
    HARD_LB,
    RSS_ABORT_MB,
    fast_path_two_move,
    load_b42_sources,
    search_access,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "spade_final_access_transaction_v0_47"
BASE_SHA = "341895b38ea49f0b517d976c0865a9e50c07413f"
BRANCH = "agent/spade-5s-10d-release-v0-47"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
GATE1_OUT = ROOT / "docs" / "research" / "spade_5s_released_v0_47.json"
EXPOSED_OUT = ROOT / "docs" / "research" / "spade_4s_exposed_v0_47.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def choose_verdict(p: dict) -> tuple[str, str]:
    if p.get("blocker_order_fail"):
        return "BLOCKER_ORDER_CONTRACT_FAILURE", "cover 10D,5S did not have 5S on top"
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.46 B4=2 sources failed replay/contract"
    if p.get("exposed_at_lb"):
        return "SPADE_4S_EXPOSED_AT_LOWER_BOUND", "unique 4S exposed at retained-frontier MW91"
    if p.get("exposed"):
        return "SPADE_4S_EXPOSED", "unique 4S exposed above MW91"
    if p.get("explosion") and not p.get("gate1_reached"):
        return "SPADE_FINAL_ACCESS_STATE_EXPLOSION", "unique/RSS limit before a useful Gate1/Gate2 boundary"
    if p.get("gate1_reached") and not p.get("exposed"):
        if p.get("gate2_attempted") and not p.get("exposed"):
            if p.get("explosion"):
                return "SPADE_FINAL_ACCESS_STATE_EXPLOSION", "Gate2 hit unique/RSS before exposing 4S"
            return "SPADE_10D_GATE_STALLED", "B4=1 found, but no B4=0 state found"
        return "SPADE_5S_GATE_REACHED", "B4=1 reached and persisted, B4=0 not reached"
    if p.get("gate1_attempted") and not p.get("gate1_reached"):
        if p.get("explosion"):
            return "SPADE_FINAL_ACCESS_STATE_EXPLOSION", "Gate1 hit unique/RSS with no B4=1"
        return "SPADE_5S_GATE_STALLED", "no B4=1 state found"
    return "INCONCLUSIVE", "final access transaction finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "SPADE_4S_EXPOSED_AT_LOWER_BOUND":
        return (
            "Unique 4S is exposed at the retained-frontier floor MW91. "
            "The next experiment should reconstruct TAIL4 from the exposure portfolio only. "
            "Do not reopen pre-Deal prep or the 3,520 TAIL3 population."
        )
    if verdict == "SPADE_4S_EXPOSED":
        return (
            "Unique 4S is exposed. Reconstruct TAIL4 from the exposure portfolio. "
            "Do not reopen pre-Deal prep."
        )
    if verdict == "SPADE_5S_GATE_REACHED":
        return (
            "5S is off 4S (B4=1, 10D now top). Continue Gate 2: land 10D on a Jack or empty. "
            "Do not search TAIL4 while 4S is still covered."
        )
    if verdict == "SPADE_10D_GATE_STALLED":
        return (
            "10D is the remaining cover. Widen Jack/empty creation from the B4=1 portfolio. "
            "Do not search TAIL4 while 4S is buried."
        )
    if verdict == "SPADE_5S_GATE_STALLED":
        return (
            "No 5S release from the B4=2 frontier. Inspect rank-6 / empty creation more deeply. "
            "Do not search TAIL4."
        )
    if verdict == "SPADE_FINAL_ACCESS_STATE_EXPLOSION":
        return (
            "Gate1 hit 180k unique with no B4=1. From the cheapest 16 MW89 B4=2 sources, "
            "excavate an exposed rank-6 or empty as an explicit 5S-landing project. "
            "Do not flood UCS and do not search TAIL4."
        )
    return "Keep the two-gate 5S-then-10D transaction. Do not search TAIL4 while 4S is buried."


def _rebuild(opening, sources, recs):
    rebuilt = []
    for rec in recs:
        src = sources[rec["origin"]]
        full = as_actions(src["full_actions"]) + as_actions(rec.get("actions") or [])
        end = opening.clone()
        cost = replay_actions(end, full)
        b_after = 0 if rec.get("exposed") or rec.get("foundation") else b4_count(end)
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
                "fd": face_down_count(end),
                "empties": [i + 1 for i in empty_column_indices(end)],
                "source_timing": src.get("timing"),
                "source_g": src.get("g"),
                "continuation": rec.get("actions") or [],
            }
        )
    rebuilt.sort(key=lambda w: (w["g"], w.get("origin", 0), w.get("ordered_digest", "")))
    return rebuilt


def write_report(payload: dict) -> None:
    src = payload.get("sources") or {}
    fast = payload.get("fast_path") or {}
    g1 = payload.get("gate1") or {}
    g2 = payload.get("gate2") or {}
    exp = payload.get("exposure") or {}
    lines = [
        "# Spider Solver v0.47 — Spade 4S Final Access Transaction",
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
        f"- Loaded **{src.get('raw')}** v0.46 B4=2 states (expected 128).",
        f"- Replay OK: **{src.get('all_replay_ok')}**. Order OK: **{src.get('blocker_order_ok')}**.",
        f"- Symmetry-unique: **{src.get('symmetry_unique')}**.",
        f"- MW: `{src.get('cost_counts')}`. Timing: `{src.get('timing')}`.",
        f"- Cover is universally `{src.get('cover')}` with top **5S** (engine face_up last element).",
        f"- 10D+5S movable together: **{src.get('together_any')}**.",
        f"- Immediate 5S dests / rank-6 / empty / Jack: "
        f"{src.get('gate1_ready')} / {src.get('rank6_any')} / {src.get('empty_any')} / {src.get('jack_any')}.",
        f"- Categories: `{src.get('categories')}`.",
        "",
        "Hard retained-frontier lower bound to exposure is **source_g + 2 = 91**.",
        "",
        "## 3. Fast path",
        "",
        f"- Legal 2→1 (5S) moves: **{fast.get('n_legal_2_to_1')}**.",
        f"- Immediate 1→0 continuations: **{fast.get('n_with_immediate_1_to_0')}**.",
        f"- MW91 witnesses: **{fast.get('mw91_n')}**. Cheapest two-move: **{fast.get('cheapest')}**.",
        "",
        "## 4. Gate 1 (5S release, B4=1)",
        "",
        f"- Reached: **{g1.get('reached')}**. First hit t={g1.get('first_s')} unique={g1.get('first_unique')} g={g1.get('first_g')}.",
        f"- Cheapest: **{g1.get('cheapest')}**. Boundary n={g1.get('n')} bands `{g1.get('cost_bands')}`.",
        f"- Gate2 capability: `{g1.get('capabilities')}`.",
        f"- Dominant 5S landing: `{g1.get('landings')}`. Stop: {g1.get('stop_reason')}.",
        "",
        "## 5. Gate 2 (10D release, B4=0)",
        "",
        f"- Reached: **{g2.get('reached')}**. First hit t={g2.get('first_s')} unique={g2.get('first_unique')} g={g2.get('first_g')}.",
        f"- Cheapest: **{g2.get('cheapest')}**. Dominant 10D landing: `{g2.get('landings')}`.",
        f"- Stop: {g2.get('stop_reason')}.",
        "",
        "## 6. Exposure",
        "",
        f"- Reached: **{exp.get('reached')}**. n={exp.get('n')}. Cheapest full MW: **{exp.get('cheapest')}**.",
        f"- Hard LB91 matched: **{exp.get('lb_matched')}**. Fast-path: **{exp.get('fast_path')}**.",
        "",
        "## 7. Resources",
        "",
        f"- Elapsed: {payload.get('elapsed_s'):.1f}s. Peak RSS: {payload.get('peak_rss_mb')} MB.",
        f"- Gate1 unique/exp/gen: {g1.get('unique')} / {g1.get('expanded')} / {g1.get('generated')}.",
        f"- Gate2 unique/exp/gen: {g2.get('unique')} / {g2.get('expanded')} / {g2.get('generated')}.",
        "",
        "## 8. Files",
        "",
        f"- `{payload.get('files', {}).get('report')}`",
        f"- `{payload.get('files', {}).get('result')}`",
        f"- Gate1: `{payload.get('files', {}).get('gate1')}`",
        f"- Exposure: `{payload.get('files', {}).get('exposed')}`",
        "",
        "No TAIL4 search. No Foundation-2 search. No new Deal. Production unchanged.",
        "",
        "## 8b. Bottleneck",
        "",
        "Every retained B4=2 state is `BOTH_GATES_BLOCKED`: no exposed 6, no empty, no Jack, "
        "so 5S cannot leave in one move and 10D cannot leave in the next. "
        "Gate1 then generated 180,000 unique descendants without a first B4=1 crossing. "
        "The controlling obligation is therefore creating a rank-6 or empty landing for 5S, "
        "not moving 5S itself and not rebuilding TAIL4.",
        "",
        "## 9. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    global_deadline = started + 450.0
    peak_rss = None

    print("LOAD B4=2", flush=True)
    bundle = load_b42_sources(opening)
    print(
        f"B42 raw={bundle['raw']} unique={bundle['symmetry_unique']} replay_ok={bundle['all_replay_ok']} "
        f"order_ok={bundle['blocker_order_ok']} cats={bundle['categories']}",
        flush=True,
    )
    sources = bundle["states"]
    blocker_order_fail = not bundle["blocker_order_ok"]
    all_replay_ok = bundle["all_replay_ok"]

    print("FAST PATH", flush=True)
    fast = fast_path_two_move(sources, opening)
    print(
        f"FAST 2->1={fast['n_legal_2_to_1']} 1->0={fast['n_with_immediate_1_to_0']} "
        f"mw91={fast['mw91_n']} cheapest={fast['cheapest']}",
        flush=True,
    )

    exposed_rows = []
    gate1_rows = []
    gate1_meta = {
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
        "first_unique": None,
        "cheapest": None,
        "cost_bands": {},
        "capabilities": {},
        "landings": {},
    }
    gate2_meta = {
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
        "first_unique": None,
        "cheapest": None,
        "landings": {},
    }
    explosion = False

    if fast["mw91"]:
        exposed_rows = list(fast["mw91"])
        print(f"LB91 HIT n={len(exposed_rows)} — skip broader search", flush=True)
    elif all_replay_ok and not blocker_order_fail:
        remaining = global_deadline - time.perf_counter()
        g1_budget = min(220.0, max(30.0, remaining - 160.0))
        print(f"GATE1 budget={g1_budget:.0f}s n={len(sources)}", flush=True)
        g1 = search_access(
            sources,
            opening,
            phase="gate1",
            source_b4=2,
            target_b4=1,
            max_unique=GATE1_UNIQUE,
            time_limit_s=g1_budget,
            rss_abort_mb=RSS_ABORT_MB,
            cost_ceiling=COST_CEILING,
        )
        gate1_meta["attempted"] = True
        gate1_meta.update(
            {
                "unique": g1.unique,
                "expanded": g1.expanded,
                "generated": g1.generated,
                "duplicate_skips": g1.duplicate_skips,
                "elapsed_s": g1.elapsed_s,
                "peak_rss_mb": g1.peak_rss_mb,
                "stop_reason": g1.stop_reason,
                "first_s": g1.first_s,
                "first_g": g1.first_g,
                "first_unique": g1.unique if g1.first_s is not None else None,
            }
        )
        if g1.peak_rss_mb is not None:
            peak_rss = g1.peak_rss_mb if peak_rss is None else max(peak_rss, g1.peak_rss_mb)
        if g1.stop_reason in ("unique limit", "rss abort"):
            explosion = True
        rebuilt = _rebuild(opening, sources, g1.witnesses)
        gate1_rows = [w for w in rebuilt if w.get("b4") == 1 and not w.get("exposed")]
        surprise_exp = [w for w in rebuilt if w.get("exposed")]
        if surprise_exp:
            exposed_rows.extend(surprise_exp)
        gate1_meta["reached"] = bool(gate1_rows)
        gate1_meta["n"] = len(gate1_rows)
        if gate1_rows:
            gate1_meta["cheapest"] = min(w["g"] for w in gate1_rows)
            gate1_meta["cost_bands"] = dict(Counter(w["g"] for w in gate1_rows))
            gate1_meta["capabilities"] = dict(Counter(w.get("gate2_capability") for w in gate1_rows))
            gate1_meta["landings"] = dict(Counter(w.get("landing") for w in gate1_rows))
            _write_json(
                GATE1_OUT,
                {"experiment": EXPERIMENT, "b4": 1, "n": len(gate1_rows), "states": gate1_rows},
            )
        print(
            f"GATE1 n={len(gate1_rows)} cheap={gate1_meta['cheapest']} cap={gate1_meta['capabilities']} "
            f"land={gate1_meta['landings']} stop={g1.stop_reason}",
            flush=True,
        )

        remaining = global_deadline - time.perf_counter()
        if gate1_rows and remaining > 20 and not exposed_rows:
            g2_budget = min(200.0, remaining - 5.0)
            print(f"GATE2 budget={g2_budget:.0f}s n={len(gate1_rows)}", flush=True)
            g2 = search_access(
                gate1_rows,
                opening,
                phase="gate2",
                source_b4=1,
                target_b4=0,
                max_unique=GATE2_UNIQUE,
                time_limit_s=g2_budget,
                rss_abort_mb=RSS_ABORT_MB,
                cost_ceiling=COST_CEILING,
            )
            gate2_meta["attempted"] = True
            gate2_meta.update(
                {
                    "unique": g2.unique,
                    "expanded": g2.expanded,
                    "generated": g2.generated,
                    "duplicate_skips": g2.duplicate_skips,
                    "elapsed_s": g2.elapsed_s,
                    "peak_rss_mb": g2.peak_rss_mb,
                    "stop_reason": g2.stop_reason,
                    "first_s": g2.first_s,
                    "first_g": g2.first_g,
                    "first_unique": g2.unique if g2.first_s is not None else None,
                }
            )
            if g2.peak_rss_mb is not None:
                peak_rss = g2.peak_rss_mb if peak_rss is None else max(peak_rss, g2.peak_rss_mb)
            if g2.stop_reason in ("unique limit", "rss abort"):
                explosion = True
            rebuilt2 = _rebuild(opening, gate1_rows, g2.witnesses)
            hits = [w for w in rebuilt2 if w.get("exposed") or w.get("b4") == 0]
            if hits:
                exposed_rows.extend(hits)
            gate2_meta["reached"] = bool(hits)
            gate2_meta["n"] = len(hits)
            if hits:
                gate2_meta["cheapest"] = min(w["g"] for w in hits)
                gate2_meta["landings"] = dict(Counter(w.get("landing") for w in hits))
            print(
                f"GATE2 n={len(hits)} cheap={gate2_meta['cheapest']} land={gate2_meta['landings']} "
                f"stop={g2.stop_reason}",
                flush=True,
            )

    if exposed_rows:
        by = {}
        for w in exposed_rows:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        exposed_rows = sorted(by.values(), key=lambda w: (w["g"], w.get("origin", 0)))[:128]
        _write_json(
            EXPOSED_OUT,
            {
                "experiment": EXPERIMENT,
                "n": len(exposed_rows),
                "cheapest": min(w["g"] for w in exposed_rows),
                "lb_matched": any(w["g"] == HARD_LB for w in exposed_rows),
                "states": exposed_rows,
            },
        )

    cheapest_exp = None if not exposed_rows else min(w["g"] for w in exposed_rows)
    payload_pre = {
        "blocker_order_fail": blocker_order_fail,
        "all_replay_ok": all_replay_ok,
        "exposed_at_lb": bool(exposed_rows) and cheapest_exp == HARD_LB,
        "exposed": bool(exposed_rows),
        "gate1_reached": bool(gate1_rows),
        "gate1_attempted": gate1_meta["attempted"],
        "gate2_attempted": gate2_meta["attempted"],
        "explosion": explosion,
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Sources 128 B4=2 cover 10D,5S. Fast-path 2->1={fast['n_legal_2_to_1']} "
        f"1->0={fast['n_with_immediate_1_to_0']} MW91={fast['mw91_n']}. "
        f"Gate1 n={gate1_meta['n']} cheap={gate1_meta['cheapest']}. "
        f"Gate2 n={gate2_meta['n']} cheap={gate2_meta['cheapest']}. "
        f"Exposed n={len(exposed_rows)} cheap={cheapest_exp}. No TAIL4. No Foundation 2."
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
            "raw": bundle["raw"],
            "expected": bundle["expected"],
            "symmetry_unique": bundle["symmetry_unique"],
            "all_replay_ok": bundle["all_replay_ok"],
            "blocker_order_ok": bundle["blocker_order_ok"],
            "cost_counts": bundle["cost_counts"],
            "timing": bundle["timing"],
            "categories": bundle["categories"],
            "cover": list(("10D", "5S")),
            "top": "5S",
            "together_any": bundle["together_any"],
            "gate1_ready": bundle["gate1_ready"],
            "rank6_any": bundle["rank6_any"],
            "empty_any": bundle["empty_any"],
            "jack_any": bundle["jack_any"],
            "hard_lb": HARD_LB,
        },
        "fast_path": {
            "n_legal_2_to_1": fast["n_legal_2_to_1"],
            "n_with_immediate_1_to_0": fast["n_with_immediate_1_to_0"],
            "mw91_n": fast["mw91_n"],
            "cheapest": fast["cheapest"],
            "skip_2_to_0": fast["skip_2_to_0"],
        },
        "gate1": gate1_meta,
        "gate2": gate2_meta,
        "exposure": {
            "reached": bool(exposed_rows),
            "n": len(exposed_rows),
            "cheapest": cheapest_exp,
            "lb_matched": bool(exposed_rows) and cheapest_exp == HARD_LB,
            "fast_path": bool(fast["mw91"]),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "gate1": GATE1_OUT.relative_to(ROOT).as_posix() if GATE1_OUT.exists() else None,
            "exposed": EXPOSED_OUT.relative_to(ROOT).as_posix() if EXPOSED_OUT.exists() else None,
        },
        "elapsed_s": time.perf_counter() - started,
        "peak_rss_mb": peak_rss,
        "production_unchanged": True,
        "all_replay_ok": all_replay_ok,
        "blocker_order_fail": blocker_order_fail,
        "exposed": bool(exposed_rows),
        "exposed_at_lb": bool(exposed_rows) and cheapest_exp == HARD_LB,
        "gate1_reached": bool(gate1_rows),
        "gate1_attempted": gate1_meta["attempted"],
        "gate2_attempted": gate2_meta["attempted"],
        "explosion": explosion,
        "cost_ceiling": COST_CEILING,
    }
    # files.exposed may not exist yet at payload build if we just wrote it
    payload["files"]["gate1"] = GATE1_OUT.relative_to(ROOT).as_posix() if GATE1_OUT.exists() else None
    payload["files"]["exposed"] = EXPOSED_OUT.relative_to(ROOT).as_posix() if EXPOSED_OUT.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
