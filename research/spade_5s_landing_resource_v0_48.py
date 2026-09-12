#!/usr/bin/env python3
"""v0.48: manufacture LAND5_READY (exposed 6 or empty) from the B4=2 frontier.

Do not search TAIL4. Do not search Foundation 2. Do not search Foundation 3.
Do not move 5S in the primary search. Use all 128 B4=2 sources.
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
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_spade_4s_ratchet import b4_count, unique_4s_exposed
from spider.simple_spade_5s_landing import (
    COST_CEILING,
    HARD_LB,
    RSS_ABORT_MB,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    first_support_zero_cost_possible,
    five_s_moves,
    jack_ready,
    land5_kind,
    land5_ready,
    load_land5_sources,
    one_move_fast_path,
    preview_5s_10d,
    search_land5,
    structural_resource_audit,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "spade_5s_landing_resource_v0_48"
BASE_SHA = "3b520c38366c93366925f4da9b787c6a3f6f0b36"
BRANCH = "agent/spade-5s-landing-resource-v0-48"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
AUDIT = ROOT / "docs" / "research" / "spade_5s_resource_audit_v0_48.json"
LAND5_OUT = ROOT / "docs" / "research" / "spade_5s_land5_ready_v0_48.json"
EXPOSED_OUT = ROOT / "docs" / "research" / "spade_4s_exposed_v0_48.json"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def choose_verdict(p: dict) -> tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "B4=2 sources failed replay or LAND5-absence contract"
    if p.get("contract_fail"):
        return "LAND5_CONTRACT_FAILURE", "LAND5_READY held but physical 5S could not legally move"
    if p.get("exposed_at_lb"):
        return "SPADE_4S_EXPOSED_AT_MW92", "unique 4S exposed at retained-frontier MW92"
    if p.get("exposed"):
        return "SPADE_4S_EXPOSED_AFTER_LANDING_PROJECT", "unique 4S exposed above MW92"
    if p.get("land5_at_one_move_floor") and not p.get("exposed"):
        return "SPADE_LAND5_RESOURCE_AT_ONE_MOVE_FLOOR", "LAND5 at MW90 from an MW89 source; exposure not completed"
    if p.get("land5_reached"):
        return "SPADE_LAND5_RESOURCE_REACHED", "exposed 6 / empty reached but 4S not exposed in micro-preview"
    if p.get("explosion"):
        return "SPADE_LAND5_RESOURCE_STATE_EXPLOSION", "unique/RSS/time limit before a LAND5 boundary"
    if p.get("search_attempted") and not p.get("land5_reached"):
        return "SPADE_LAND5_RESOURCE_NOT_FOUND", "no LAND5_READY boundary inside the envelope"
    return "INCONCLUSIVE", "landing-resource experiment finished without a classified outcome"


def next_recommendation(verdict: str) -> str:
    if verdict == "SPADE_4S_EXPOSED_AT_MW92":
        return (
            "Unique 4S is exposed at MW92. Reconstruct TAIL4 from the exposure portfolio only. "
            "Do not reopen pre-Deal prep."
        )
    if verdict == "SPADE_4S_EXPOSED_AFTER_LANDING_PROJECT":
        return (
            "Unique 4S is exposed after the landing project. Reconstruct TAIL4 from the exposure "
            "portfolio. Do not reopen pre-Deal prep."
        )
    if verdict in ("SPADE_LAND5_RESOURCE_REACHED", "SPADE_LAND5_RESOURCE_AT_ONE_MOVE_FLOOR"):
        return (
            "LAND5_READY is in hand. Run the 5S then 10D transaction from the LAND5 portfolio, "
            "including Jack/empty creation for Gate 2. Do not search TAIL4 while 4S is covered."
        )
    if verdict == "SPADE_LAND5_RESOURCE_NOT_FOUND":
        return (
            "No exposed 6 or empty from the B4=2 frontier inside the envelope. "
            "Inspect the nearest buried 6 covering packets. Do not search TAIL4."
        )
    if verdict == "SPADE_LAND5_RESOURCE_STATE_EXPLOSION":
        return (
            "Nearest 6s sit at depth 3 (6H under KH-QS-3C; 6C under KC-QH-7H) and are not "
            "one-move packets. Next: a directed peel of those depth-3 6-covers from all 128 "
            "B4=2 sources. Do not flood UCS and do not search TAIL4."
        )
    return "Keep the LAND5 resource cut. Do not search TAIL4 while 4S is buried."


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
                "land5": land5_ready(end),
                "kind": land5_kind(end),
                "jack_ready": jack_ready(end),
                "five_s_can_move": bool(five_s_moves(end)),
                "b4": b4_count(end),
                "exposed": unique_4s_exposed(end),
                "fd": face_down_count(end),
                "empties": [i + 1 for i in empty_column_indices(end)],
                "source_timing": src.get("timing"),
                "source_g": src.get("g"),
            }
        )
    rebuilt.sort(key=lambda w: (w["g"], w.get("origin", 0), w.get("ordered_digest", "")))
    return rebuilt


def write_report(payload: dict) -> None:
    src = payload.get("sources") or {}
    audit = payload.get("audit_summary") or {}
    fast = payload.get("fast_path") or {}
    search = payload.get("search") or {}
    prev = payload.get("preview") or {}
    exp = payload.get("exposure") or {}
    lines = [
        "# Spider Solver v0.48 — Spade 5S Landing-Resource Cut",
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
        f"- Loaded **{src.get('raw')}** B4=2 states. Replay OK: **{src.get('all_replay_ok')}**.",
        f"- MW: `{src.get('cost_counts')}`. Timing: `{src.get('timing')}`.",
        f"- LAND5 absent / no Jack: **{src.get('land5_absent')}**.",
        f"- Hard exposure LB from this frontier: **source_g + 3**, global **MW{HARD_LB}**.",
        "",
        "## 3. Rank-6 / empty / Jack audit",
        "",
        "```json",
        json.dumps(audit, indent=2)[:4500],
        "```",
        "",
        "## 4. One-move fast path",
        "",
        f"- Actions enumerated: **{fast.get('n_actions')}**. Unique LAND5 hits: **{fast.get('n_unique')}**.",
        f"- Kinds: `{fast.get('kinds')}`. Simultaneous JACK_READY: **{fast.get('jack_ready')}**.",
        f"- Cheapest: **{fast.get('cheapest')}**. From MW89: **{fast.get('from_89')}**. From MW90: **{fast.get('from_90')}**.",
        f"- MW90-from-89: **{fast.get('mw90_from_89')}**.",
        "",
        "## 5. Resource search",
        "",
        f"- Reached: **{search.get('reached')}**. First t={search.get('first_s')} g={search.get('first_g')} kind={search.get('first_kind')}.",
        f"- Cheapest: **{search.get('cheapest')}**. n={search.get('n')} bands `{search.get('cost_bands')}`.",
        f"- Kinds: `{search.get('kinds')}`. Stop: {search.get('stop_reason')}.",
        f"- Unique/exp/gen/dups: {search.get('unique')} / {search.get('expanded')} / {search.get('generated')} / {search.get('duplicate_skips')}.",
        f"- Runtime/RSS: {search.get('elapsed_s')}s / {search.get('peak_rss_mb')} MB.",
        "",
        "## 6. 5S / 10D micro-preview",
        "",
        f"- 5S releases: **{prev.get('n_5s_releases')}**. Destinations: `{prev.get('destinations')}`.",
        f"- Gate2: `{prev.get('gate2')}`. Immediate exposures: **{prev.get('immediate_n')}**. One-support: **{prev.get('one_support_n')}**.",
        f"- Blocked: **{prev.get('blocked')}**. Contract fail: **{prev.get('contract_fail')}**.",
        "",
        "## 7. Exposure / cost-band comparison",
        "",
        f"- Reached: **{exp.get('reached')}**. Cheapest: **{exp.get('cheapest')}**. MW92 matched: **{exp.get('lb_matched')}**.",
        f"- Best from MW89 source: **{exp.get('from_89')}**. Best from MW90 source: **{exp.get('from_90')}**.",
        "",
        "## 8. Files",
        "",
        f"- `{payload.get('files', {}).get('report')}`",
        f"- `{payload.get('files', {}).get('result')}`",
        f"- `{payload.get('files', {}).get('audit')}`",
        f"- LAND5: `{payload.get('files', {}).get('land5')}`",
        f"- Exposure: `{payload.get('files', {}).get('exposed')}`",
        "",
        "No TAIL4 search. No Foundation-2 search. No new Deal. Production unchanged.",
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
    global_deadline = started + 400.0

    print("LOAD B4=2", flush=True)
    bundle = load_land5_sources(opening)
    sources = bundle["states"]
    print(
        f"B42 raw={bundle['raw']} unique={bundle['symmetry_unique']} replay_ok={bundle['all_replay_ok']} "
        f"land5_absent={bundle['land5_absent']} costs={bundle['cost_counts']}",
        flush=True,
    )
    zero_cost = sum(
        1
        for rec in sources
        if first_support_zero_cost_possible(unpack_state(bytes.fromhex(rec["ordered_digest"])))
    )
    print(f"ZERO_COST_FIRST {zero_cost}", flush=True)

    print("STRUCTURAL AUDIT", flush=True)
    audit = structural_resource_audit(sources)
    slim_audit = {
        "n_sources": audit["n_sources"],
        "rank6": {k: v for k, v in audit["rank6"].items() if k != "signatures"},
        "rank6_top_signatures": dict(list(audit["rank6"]["signatures"].items())[:8]),
        "empty": audit["empty"],
        "jack": audit["jack"],
    }
    _write_json(AUDIT, {"experiment": EXPERIMENT, **audit})
    print(
        f"AUDIT six_occ={audit['rank6']['occurrences']} one_move6={audit['rank6']['one_move_exposable']} "
        f"empty_one={audit['empty']['one_move_clearable']} jack_top={audit['jack']['already_top']}",
        flush=True,
    )

    print("ONE-MOVE FAST PATH", flush=True)
    fast = one_move_fast_path(sources)
    print(
        f"FAST actions={fast['n_actions']} hits={fast['n_unique']} kinds={fast['kinds']} "
        f"cheap={fast['cheapest']} jack={fast['jack_ready']}",
        flush=True,
    )

    land5_rows = []
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
        "first_kind": None,
        "cheapest": None,
        "cost_bands": {},
        "kinds": {},
        "from_89": None,
        "from_90": None,
    }
    explosion = False
    if fast["witnesses"]:
        land5_rows = list(fast["witnesses"])
    remaining = global_deadline - time.perf_counter()
    # Always run exact search unless fast path already filled a diverse portfolio
    # and remaining time is tiny. Spec: run search if fast path is not adequate.
    adequate = len(land5_rows) >= 64
    if remaining > 20 and not adequate:
        budget = min(SEARCH_TIME_S, remaining - 15.0)
        print(f"SEARCH LAND5 budget={budget:.0f}s n={len(sources)}", flush=True)
        res = search_land5(
            sources,
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
                "first_kind": res.first_kind,
            }
        )
        if res.stop_reason in ("unique limit", "rss abort"):
            explosion = True
        rebuilt = _rebuild(opening, sources, res.witnesses)
        land5_rows = rebuilt or land5_rows
        if res.contract_fail:
            print(f"CONTRACT_FAIL primary {res.contract_fail}", flush=True)

    if land5_rows:
        by = {}
        for w in land5_rows:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        land5_rows = sorted(by.values(), key=lambda w: (w["g"], w.get("origin", 0)))
        search_meta["reached"] = True
        search_meta["n"] = len(land5_rows)
        search_meta["cheapest"] = min(w["g"] for w in land5_rows)
        search_meta["cost_bands"] = dict(Counter(w["g"] for w in land5_rows))
        search_meta["kinds"] = dict(Counter(w.get("kind") for w in land5_rows))
        search_meta["from_89"] = min((w["g"] for w in land5_rows if w.get("source_g") == 89), default=None)
        search_meta["from_90"] = min((w["g"] for w in land5_rows if w.get("source_g") == 90), default=None)
        _write_json(
            LAND5_OUT,
            {"experiment": EXPERIMENT, "n": len(land5_rows), "states": land5_rows},
        )
        print(
            f"LAND5 n={len(land5_rows)} cheap={search_meta['cheapest']} kinds={search_meta['kinds']} "
            f"bands={search_meta['cost_bands']}",
            flush=True,
        )

    preview = {
        "n_land5": 0,
        "n_5s_releases": 0,
        "destinations": {},
        "gate2": {},
        "contract_fail": 0,
        "immediate_n": 0,
        "one_support_n": 0,
        "blocked": 0,
        "cheapest_exposure": None,
        "mw92_n": 0,
        "from_89": None,
        "from_90": None,
        "immediate": [],
        "one_support": [],
    }
    if land5_rows and (global_deadline - time.perf_counter()) > 5:
        print(f"PREVIEW 5S/10D n={len(land5_rows)}", flush=True)
        preview = preview_5s_10d(sources, land5_rows, opening)
        print(
            f"PREVIEW 5s={preview['n_5s_releases']} dest={preview['destinations']} g2={preview['gate2']} "
            f"imm={preview['immediate_n']} one={preview['one_support_n']} blocked={preview['blocked']} "
            f"cfail={preview['contract_fail']}",
            flush=True,
        )

    exposed_rows = list(preview.get("immediate") or []) + list(preview.get("one_support") or [])
    if exposed_rows:
        by = {}
        for w in exposed_rows:
            prev = by.get(w["symmetry_digest"])
            if prev is None or w["g"] < prev["g"]:
                by[w["symmetry_digest"]] = w
        exposed_rows = sorted(by.values(), key=lambda w: (w["g"], w.get("source_g") or 0))[:128]
        _write_json(
            EXPOSED_OUT,
            {
                "experiment": EXPERIMENT,
                "n": len(exposed_rows),
                "cheapest": min(w["g"] for w in exposed_rows),
                "lb_matched": any(w.get("lb_matched") for w in exposed_rows),
                "states": exposed_rows,
            },
        )

    cheapest_exp = None if not exposed_rows else min(w["g"] for w in exposed_rows)
    land5_at_floor = bool(fast.get("mw90_from_89")) or any(
        w.get("source_g") == 89 and w.get("g") == 90 for w in land5_rows
    )
    payload_pre = {
        "all_replay_ok": bundle["all_replay_ok"],
        "contract_fail": preview.get("contract_fail", 0) > 0,
        "exposed_at_lb": bool(exposed_rows) and cheapest_exp == HARD_LB,
        "exposed": bool(exposed_rows),
        "land5_at_one_move_floor": land5_at_floor and not exposed_rows,
        "land5_reached": bool(land5_rows),
        "explosion": explosion and not land5_rows,
        "search_attempted": search_meta["attempted"],
    }
    verdict, reason = choose_verdict(payload_pre)
    interpretation = (
        f"{reason}. Sources 128 B4=2. Fast LAND5 unique={fast['n_unique']} cheap={fast['cheapest']}. "
        f"Search n={search_meta['n']} cheap={search_meta['cheapest']} stop={search_meta['stop_reason']}. "
        f"Preview imm={preview.get('immediate_n')} one={preview.get('one_support_n')}. "
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
            "symmetry_unique": bundle["symmetry_unique"],
            "all_replay_ok": bundle["all_replay_ok"],
            "land5_absent": bundle["land5_absent"],
            "cost_counts": bundle["cost_counts"],
            "timing": bundle["timing"],
            "zero_cost_first": zero_cost,
            "hard_lb": HARD_LB,
        },
        "audit_summary": slim_audit,
        "fast_path": {
            "n_actions": fast["n_actions"],
            "n_unique": fast["n_unique"],
            "kinds": fast["kinds"],
            "jack_ready": fast["jack_ready"],
            "cheapest": fast["cheapest"],
            "from_89": fast["from_89"],
            "from_90": fast["from_90"],
            "mw90_from_89": fast["mw90_from_89"],
        },
        "search": search_meta,
        "preview": {
            "n_land5": preview.get("n_land5"),
            "n_5s_releases": preview.get("n_5s_releases"),
            "destinations": preview.get("destinations"),
            "gate2": preview.get("gate2"),
            "immediate_n": preview.get("immediate_n"),
            "one_support_n": preview.get("one_support_n"),
            "blocked": preview.get("blocked"),
            "contract_fail": preview.get("contract_fail"),
            "cheapest_exposure": preview.get("cheapest_exposure"),
        },
        "exposure": {
            "reached": bool(exposed_rows),
            "n": len(exposed_rows),
            "cheapest": cheapest_exp,
            "lb_matched": bool(exposed_rows) and cheapest_exp == HARD_LB,
            "from_89": preview.get("from_89"),
            "from_90": preview.get("from_90"),
        },
        "files": {
            "report": REPORT.relative_to(ROOT).as_posix(),
            "result": RESULT.relative_to(ROOT).as_posix(),
            "audit": AUDIT.relative_to(ROOT).as_posix(),
            "land5": LAND5_OUT.relative_to(ROOT).as_posix() if LAND5_OUT.exists() else None,
            "exposed": EXPOSED_OUT.relative_to(ROOT).as_posix() if EXPOSED_OUT.exists() else None,
        },
        "elapsed_s": time.perf_counter() - started,
        "production_unchanged": True,
        "all_replay_ok": bundle["all_replay_ok"],
        "contract_fail": preview.get("contract_fail", 0) > 0,
        "exposed": bool(exposed_rows),
        "exposed_at_lb": bool(exposed_rows) and cheapest_exp == HARD_LB,
        "land5_reached": bool(land5_rows),
        "land5_at_one_move_floor": land5_at_floor and not exposed_rows,
        "explosion": explosion and not land5_rows,
        "search_attempted": search_meta["attempted"],
        "cost_ceiling": COST_CEILING,
    }
    payload["files"]["land5"] = LAND5_OUT.relative_to(ROOT).as_posix() if LAND5_OUT.exists() else None
    payload["files"]["exposed"] = EXPOSED_OUT.relative_to(ROOT).as_posix() if EXPOSED_OUT.exists() else None
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
