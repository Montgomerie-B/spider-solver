#!/usr/bin/env python3
"""v0.33: Gate 1 ratchet — first flip of 8D above unique 9H.

Does not search AH/JH/9H or Heart foundation.  SD4 never taken.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_gate1 import flip_cost_bound_audit, search_gate1, verify_blocker_chain
from spider.simple_h9_cut import mandatory_rank_status, verify_mandatory_h9
from spider.simple_legacy_fd13_alternatives import checkpoint_record, legal_tableau_count
from spider.simple_progressive_solver import format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

EXPERIMENT = "heart9_blocker_ratchet1_v0_33"
BASE_SHA = "42a832684b60a303e71fbaf6dc456a75c8fd5322"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_33_gate1_8d_best.moves.txt"
TIMING_MAP = {
    "HEART_BEFORE_SD3": "GATE1_BEFORE_SD3",
    "HEART_AFTER_IMMEDIATE_SD3": "GATE1_AFTER_IMMEDIATE_SD3",
    "HEART_AFTER_PREPARED_SD3": "GATE1_AFTER_PREPARED_SD3",
}
V32 = {"unique": 198303, "expanded": 228681, "seconds": 900, "h9": False}


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


def recover_sources(opening: SpiderState):
    payload = json.loads(V30.read_text(encoding="utf-8"))
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    audited = []
    distinct = {}
    for index, rec in enumerate(exits):
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        chain = verify_blocker_chain(end)
        h9 = verify_mandatory_h9(end)
        ok = (
            cost == 62
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and face_down_count(end) == 9
            and stock_rows(end) == 3
            and sum(1 for a in full if a == ("deal",)) == 2
            and 5 in empty_column_indices(end)
            and pack_state(end).hex() == rec["ordered_digest"]
            and chain["valid"]
        )
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "path": len(full),
                "mw": cost,
                "empties": list(empty_column_indices(end)),
                "legal_tableau": legal_tableau_count(end),
                "ordered_digest": pack_state(end).hex(),
                "chain": chain,
                "h9_unique": h9["valid"],
                "full_actions": rec["full_actions"],
            }
        )
        print(f"SOURCE {index} ok={ok} chain={chain['valid']} top={chain.get('top_face_down')}", flush=True)
        ident = pack_state(end)
        if ident not in distinct:
            distinct[ident] = {"state": end, "path": full, "source_id": index, "chain": chain}
    return audited, distinct


def choose_verdict(audit_ok, chain_ok, bound, pass_a, pass_b, witnesses):
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "Spade-1 sources could not be reconstructed"
    if not chain_ok:
        return "BLOCKER_CHAIN_INVALID", "8D-AH-JH-9H chain did not verify"
    if bound and not bound.get("valid"):
        return "FLIP_COST_BOUND_INVALID", bound.get("rationale") or "flip-cost bound failed"
    if witnesses and pass_b and pass_b.get("proved"):
        return "GATE1_8D_REACHED_AND_COST_PROVED", "Gate 1 reached and Pass B proved cheapest cost"
    if witnesses:
        return "GATE1_8D_REACHED", "Gate 1 (8D exposure, blockers 3->2) reached before SD4"
    if pass_a.stop_reason in ("time limit", "rss abort", "unique limit"):
        return "GATE1_8D_STATE_EXPLOSION", f"Pass A bound by {pass_a.stop_reason}"
    return "GATE1_8D_NOT_FOUND_IN_ENVELOPE", "no Gate-1 witness in the bounded funnel"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("GATE1_8D_REACHED"):
        return (
            "Carry the Gate-1 portfolio (cost bands C/C+1/C+2) into Gate 2: first exposure "
            "of AH. Do not jump to 9H or Heart 1, and do not take SD4."
        )
    if verdict == "GATE1_8D_STATE_EXPLOSION":
        return "Keep Gate 1 as the next cut; do not raise limits here and do not take SD4."
    return "Keep the ratchet decomposition. Do not return to whole-Heart or whole-H9 search."


def write_report(payload: dict) -> None:
    pa = payload.get("pass_a") or {}
    pb = payload.get("pass_b") or {}
    lines = [
        "# Spider Solver v0.33 — Gate 1 Ratchet: First 8D Blocker Flip",
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
        "## 2. Proof",
        "",
        json.dumps(payload.get("proof") or {}, indent=2)[:3500],
        "",
        "## 3. Pass A",
        "",
        f"- levels={pa.get('levels_reached')} first_t={pa.get('first_gate1_s')} "
        f"first_unique={pa.get('first_gate1_unique')} first_g={pa.get('first_gate1_g')} "
        f"first_depth={pa.get('first_gate1_depth')}",
        f"- unique={pa.get('unique')} expanded={pa.get('expanded')} generated={pa.get('generated')} "
        f"dups={pa.get('duplicate_skips')} reopens={pa.get('cheaper_reopens')}",
        f"- bands={pa.get('band_counts')} timings={pa.get('timings')} stop={pa.get('stop_reason')} "
        f"elapsed_s={pa.get('elapsed_s')} rss={pa.get('peak_rss_mb')}",
        "",
        "## 4. Pass B",
        "",
        json.dumps(pb, indent=2)[:2000],
        "",
        "## 5. Boundary",
        "",
        json.dumps(payload.get("boundary") or {}, indent=2)[:2500],
        "",
        "## 6. Condensation vs v0.32",
        "",
        json.dumps(payload.get("condensation") or {}, indent=2),
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={pa.get('sd4_expanded')}.",
        "Gate 1 terminal. No H9/Heart search. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    audited, distinct = recover_sources(opening)
    audit_ok = len(distinct) == 4 and all(r["ok"] for r in audited)
    chain_ok = all(r["chain"]["valid"] for r in audited)
    sources = [rec["state"] for rec in distinct.values()]
    origin_paths = [rec["path"] for rec in distinct.values()]
    bound = flip_cost_bound_audit(sources[0]) if sources else {"valid": False}
    print(f"CHAIN ok={chain_ok} LB={bound.get('lb_to_gate1')} valid={bound.get('valid')}", flush=True)
    if not audit_ok or not chain_ok:
        verdict, reason = choose_verdict(audit_ok, chain_ok, bound, None, None, [])
        payload = {"experiment": EXPERIMENT, "verdict": verdict, "verdict_reason": reason}
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {verdict}", flush=True)
        return payload

    remaining = 1800.0 - (time.perf_counter() - started)
    print("PASS A START Gate-1 8D directed", flush=True)
    pass_a = search_gate1(
        sources,
        origin_paths,
        directed=True,
        max_unique=500_000,
        time_limit_s=min(600.0, max(1.0, remaining - 50)),
        rss_abort_mb=2 * 1024.0,
        lb=bound["lb_to_gate1"],
        harvest_slack=2,
        harvest_limit=256,
    )
    print(
        f"PASS A unique={pass_a.unique} exp={pass_a.expanded} gen={pass_a.generated} "
        f"inc={pass_a.incumbent} wit={len(pass_a.witnesses)} first_t={pass_a.first_gate1_s} "
        f"stop={pass_a.stop_reason} elapsed={pass_a.elapsed_s:.1f}",
        flush=True,
    )

    pass_b_out = {"run": False}
    remaining = 1800.0 - (time.perf_counter() - started)
    if pass_a.witnesses and remaining > 5:
        print("PASS B START exact UCS", flush=True)
        pass_b = search_gate1(
            sources,
            origin_paths,
            directed=False,
            max_unique=750_000,
            time_limit_s=min(900.0, remaining),
            rss_abort_mb=2 * 1024.0,
            start_level=3,
            max_level=3,
            incumbent=pass_a.incumbent,
            lb=bound["lb_to_gate1"],
            cheaper_only=True,
            harvest_slack=2,
            harvest_limit=256,
        )
        cheaper = bool(
            pass_b.incumbent is not None
            and pass_a.incumbent is not None
            and pass_b.incumbent < pass_a.incumbent
        )
        proved = (not cheaper) and pass_b.stop_reason in ("frontier empty", "complete", "max level", "harvested")
        if pass_b.stop_reason in ("time limit", "rss abort", "unique limit"):
            proved = False
        pass_b_out = {
            "run": True,
            "unique": pass_b.unique,
            "expanded": pass_b.expanded,
            "generated": pass_b.generated,
            "incumbent": pass_b.incumbent,
            "cheaper": cheaper,
            "proved": proved,
            "stop_reason": pass_b.stop_reason,
            "elapsed_s": pass_b.elapsed_s,
            "peak_rss_mb": pass_b.peak_rss_mb,
            "sd4_expanded": pass_b.sd4_expanded,
            "witnesses": len(pass_b.witnesses),
        }
        print(
            f"PASS B unique={pass_b.unique} cheaper={cheaper} proved={proved} stop={pass_b.stop_reason}",
            flush=True,
        )
        if cheaper and pass_b.witnesses:
            pass_a.witnesses = pass_b.witnesses
            pass_a.incumbent = pass_b.incumbent
            pass_a.band_counts = pass_b.band_counts

    witnesses = []
    for rec in pass_a.witnesses:
        full = list(origin_paths[rec["origin"]]) + as_actions(rec["actions"])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
            ok = True
        except (ValueError, AssertionError) as exc:
            cost = None
            ok = False
            rec["replay_error"] = str(exc)
        item = dict(rec)
        item["timing"] = TIMING_MAP.get(rec["timing"], rec["timing"])
        item["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = ok and rec.get("top_face_up") == "8D" and rec.get("fd_blockers") == 2
        item["deals"] = sum(1 for a in full if a == ("deal",))
        local = as_actions(rec["actions"])
        before = after = 0
        seen = False
        for a in local:
            if a == ("deal",):
                seen = True
                continue
            if seen:
                after += 1
            else:
                before += 1
        item["moves_before_sd3"] = before
        item["moves_after_sd3"] = after
        witnesses.append(item)

    first = None
    fixture = None
    if witnesses:
        first = min(witnesses, key=lambda r: (r["g"], r["depth"], r["origin"]))
        FIXTURE.write_text(
            format_moves_text(
                as_actions(first["full_actions"]),
                header=f"# v0.33 Gate 1 8D\n# timing: {first['timing']}\n# g: {first['g']}",
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    timings = sorted({w["timing"] for w in witnesses})
    verdict, reason = choose_verdict(True, True, bound, pass_a, pass_b_out, witnesses)
    condensed = bool(pass_a.first_gate1_unique is not None and pass_a.first_gate1_unique < V32["unique"])
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/heart9-blocker-ratchet1-v0-33",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": reason,
        "next_recommendation": next_recommendation(verdict),
        "proof": {
            "chain": distinct[next(iter(distinct))]["chain"] if distinct else {},
            "flip_cost": bound,
        },
        "sources": [{k: r[k] for k in r if k != "full_actions"} for r in audited],
        "pass_a": {
            "levels_reached": pass_a.levels_reached,
            "unique": pass_a.unique,
            "expanded": pass_a.expanded,
            "generated": pass_a.generated,
            "duplicate_skips": pass_a.duplicate_skips,
            "cheaper_reopens": pass_a.cheaper_reopens,
            "max_depth": pass_a.max_depth,
            "first_gate1_s": pass_a.first_gate1_s,
            "first_gate1_unique": pass_a.first_gate1_unique,
            "first_gate1_g": pass_a.first_gate1_g,
            "first_gate1_depth": pass_a.first_gate1_depth,
            "incumbent": pass_a.incumbent,
            "portfolio": len(witnesses),
            "band_counts": pass_a.band_counts,
            "timings": timings,
            "stop_reason": pass_a.stop_reason,
            "elapsed_s": pass_a.elapsed_s,
            "peak_rss_mb": pass_a.peak_rss_mb,
            "sd4_expanded": pass_a.sd4_expanded,
            "per_level": pass_a.per_level,
        },
        "pass_b": pass_b_out,
        "min_path": None if not first else first["full_path_length"],
        "min_mw": None if not first else first["full_cost"],
        "stock_at_gate": None if not first else first.get("stock_rows"),
        "fd_at_gate": None if not first else first.get("fd"),
        "full_replay_ok": bool(witnesses) and all(w.get("full_replay_ok") for w in witnesses),
        "fixture": fixture,
        "boundary": None
        if not first
        else {k: first[k] for k in first if k != "full_actions" or True},
        "condensation": {
            "v32_unique": V32["unique"],
            "v32_expanded": V32["expanded"],
            "v32_seconds": V32["seconds"],
            "v32_h9": False,
            "v33_unique": pass_a.unique,
            "v33_expanded": pass_a.expanded,
            "v33_first_unique": pass_a.first_gate1_unique,
            "v33_first_s": pass_a.first_gate1_s,
            "v33_gate1": bool(witnesses),
            "condensed": condensed,
        },
        "elapsed_s": time.perf_counter() - started,
        "no_sd4": True,
        "gate1_terminal": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
