#!/usr/bin/env python3
"""v0.32: dynamic mandatory cut — first exposure of unique pre-SD4 9H.

Does not search for the Heart foundation.  SD4 is never taken.
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
from spider.packed_state import pack_state, permute_tableau_columns
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import material_horizon_audit
from spider.simple_h9_cut import (
    JOIN_BREAK,
    allowed_at_level,
    annotate_h9_action,
    dynamic_blockers,
    h9_progress,
    mandatory_rank_status,
    search_h9_cut,
    verify_mandatory_h9,
)
from spider.simple_heart_backward import action_allowed_at_level as v31_allowed
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_legacy_fd13_alternatives import checkpoint_record, legal_tableau_count
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

EXPERIMENT = "dynamic_heart9_mandatory_cut_v0_32"
BASE_SHA = "5ca21738d399b9faa99662e7fe7800cea560a2a3"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V30 = ROOT / "docs" / "research" / "simple_progressive_foundation_horizon_v0_30.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
FIXTURE = ROOT / "solutions" / "4925153_v0_32_h9_boundary.moves.txt"
TIMING_MAP = {
    "HEART_BEFORE_SD3": "H9_BEFORE_SD3",
    "HEART_AFTER_IMMEDIATE_SD3": "H9_AFTER_IMMEDIATE_SD3",
    "HEART_AFTER_PREPARED_SD3": "H9_AFTER_PREPARED_SD3",
}


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


def v31_audit() -> dict:
    static = True  # v0.31 builds deps from sources once; see simple_heart_funnel.py
    level2_full = v31_allowed(JOIN_BREAK, 3, 2, False) is True
    return {
        "static_dependency_map": static,
        "static_finding": (
            "v0.31 builds build_dependency_map(src) once per origin and reuses "
            "deps[origin] for every descendant. Blocker columns therefore go stale."
        ),
        "level2_unconditional": level2_full,
        "level2_finding": (
            "v0.31 action_allowed_at_level Level 2 is `return label != JOIN_BREAK or True`, "
            "which is unconditionally True, so Level 2 is already full-legal."
        ),
        "v32_fix": (
            "v0.32 recomputes h9_progress from the current unpacked state and "
            "Level 2 excludes JOIN_BREAK while Level 3 admits every engine-legal action."
        ),
    }


def recover_sources(opening: SpiderState):
    payload = json.loads(V30.read_text(encoding="utf-8"))
    exits = ((payload.get("groups") or {}).get("MIDDLE") or {}).get("foundation_exits") or []
    audited = []
    distinct = {}
    for index, rec in enumerate(exits):
        full = as_actions(rec["full_actions"])
        end = opening.clone()
        cost = replay_actions(end, full)
        ok = (
            cost == 62
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and face_down_count(end) == 9
            and stock_rows(end) == 3
            and sum(1 for a in full if a == ("deal",)) == 2
            and 5 in empty_column_indices(end)
            and pack_state(end).hex() == rec["ordered_digest"]
        )
        cp = checkpoint_record(end, arm=f"s1_{index}", path_length=len(full), cost=cost, kind="SPADE1")
        proof = verify_mandatory_h9(end)
        audited.append(
            {
                "source_id": index,
                "ok": ok,
                "cut_valid": proof["valid"],
                "path": len(full),
                "mw": cost,
                "fd": cp["fd"],
                "stock_rows": stock_rows(end),
                "empties": list(empty_column_indices(end)),
                "legal_tableau": legal_tableau_count(end),
                "ordered_digest": pack_state(end).hex(),
                "h9": proof["h9"],
                "jh": proof["jh"],
                "jh_must_flip_before_h9": proof["jh_must_flip_before_h9"],
                "full_actions": rec["full_actions"],
            }
        )
        print(
            f"SOURCE {index} ok={ok} cut={proof['valid']} h9={proof['h9']} "
            f"jh_before={proof['jh_must_flip_before_h9']}",
            flush=True,
        )
        ident = pack_state(end)
        if ident not in distinct:
            distinct[ident] = {"state": end, "path": full, "source_id": index, "proof": proof}
    return audited, distinct


def remap_timing(name: str) -> str:
    return TIMING_MAP.get(name, name)


def choose_verdict(audit_ok, cut_valid, pass_a, pass_b, witnesses) -> tuple[str, str]:
    if not audit_ok:
        return "SOURCE_REPLAY_FAILURE", "the four Spade-1 sources could not be reconstructed"
    if not cut_valid:
        return "BACKWARD_CUT_INVALID", "unique pre-SD4 9H is not a mandatory Heart-1 card"
    if witnesses and pass_b and pass_b.get("proved"):
        return "H9_MANDATORY_CUT_REACHED_AND_COST_PROVED", "H9 exposed and Pass B proved the cheapest cut"
    if witnesses:
        return "H9_MANDATORY_CUT_REACHED", "replay-valid unique 9H exposure reached before SD4"
    if pass_a.stop_reason in ("time limit", "rss abort", "unique limit"):
        return "H9_MANDATORY_CUT_STATE_EXPLOSION", f"Pass A bound by {pass_a.stop_reason}"
    return "H9_MANDATORY_CUT_NOT_FOUND_IN_ENVELOPE", "no H9 exposure in the bounded funnel"


def next_recommendation(verdict: str) -> str:
    if verdict.startswith("H9_MANDATORY_CUT_REACHED"):
        return (
            "The unique 9H gateway is reached. Next: resume Heart-1 search from the H9 "
            "boundary portfolio, still before SD4. Do not assemble the whole Heart from "
            "Spade-1 in one leap, and do not take SD4."
        )
    if verdict == "H9_MANDATORY_CUT_NOT_FOUND_IN_ENVELOPE":
        return "Keep the 9H cut; do not raise limits and do not take SD4."
    if verdict == "H9_MANDATORY_CUT_STATE_EXPLOSION":
        return "Keep the dynamic 9H cut; do not raise these limits here and do not take SD4."
    if verdict == "BACKWARD_CUT_INVALID":
        return "Re-verify uniqueness of 9H before treating it as a mandatory gateway."
    return "Keep backward decomposition. Do not return to whole-Heart search from Spade-1."


def write_report(payload: dict) -> None:
    pa = payload.get("pass_a") or {}
    pb = payload.get("pass_b") or {}
    lines = [
        "# Spider Solver v0.32 — Dynamic Backward Cut: Mandatory 9H Exposure",
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
        "## 2. Implementation audit",
        "",
        json.dumps(payload.get("v31_audit") or {}, indent=2),
        "",
        "## 3. Mandatory cut",
        "",
        json.dumps(payload.get("cut") or {}, indent=2)[:4000],
        "",
        "## 4. Pass A",
        "",
        f"- levels={pa.get('levels_reached')} unique={pa.get('unique')} expanded={pa.get('expanded')} "
        f"generated={pa.get('generated')} dups={pa.get('duplicate_skips')} reopens={pa.get('cheaper_reopens')}",
        f"- first_g={pa.get('first_g')} best_g={pa.get('incumbent')} portfolio={pa.get('portfolio')} "
        f"timings={pa.get('timings')} stop={pa.get('stop_reason')} elapsed_s={pa.get('elapsed_s')} rss={pa.get('peak_rss_mb')}",
        "",
        "## 5. Pass B",
        "",
        json.dumps(pb, indent=2)[:2000],
        "",
        "## 6. Boundary",
        "",
        json.dumps(payload.get("boundary") or {}, indent=2)[:3000],
        "",
        "## 7. Exactly one next recommendation",
        "",
        payload.get("next_recommendation", ""),
        "",
        "## Integrity",
        "",
        f"Verdict {payload.get('verdict')}. SD4 expanded={pa.get('sd4_expanded')}.",
        "No Heart-foundation search. No production change. No human-route guidance.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    started = time.perf_counter()
    audit = v31_audit()
    print(f"AUDIT static={audit['static_dependency_map']} level2_full={audit['level2_unconditional']}", flush=True)
    horizon = material_horizon_audit(opening)
    audited, distinct = recover_sources(opening)
    audit_ok = len(distinct) == 4 and all(r["ok"] for r in audited)
    cut_valid = all(r["cut_valid"] for r in audited) and all(
        rec["proof"]["valid"] for rec in distinct.values()
    )
    sources = [rec["state"] for rec in distinct.values()]
    origin_paths = [rec["path"] for rec in distinct.values()]
    cut = distinct[next(iter(distinct))]["proof"] if distinct else {}
    print(f"CUT valid={cut_valid} h9={cut.get('h9')} jh_before={cut.get('jh_must_flip_before_h9')}", flush=True)
    if not audit_ok or not cut_valid:
        verdict, reason = choose_verdict(audit_ok, cut_valid, None, None, [])
        payload = {"experiment": EXPERIMENT, "verdict": verdict, "verdict_reason": reason, "v31_audit": audit}
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {verdict}", flush=True)
        return payload

    remaining = 1800.0 - (time.perf_counter() - started)
    print("PASS A START directed 9H exposure SD3 legal SD4 forbidden", flush=True)
    pass_a = search_h9_cut(
        sources,
        origin_paths,
        directed=True,
        max_unique=1_000_000,
        time_limit_s=min(900.0, max(1.0, remaining - 50)),
        rss_abort_mb=2 * 1024.0,
        harvest_limit=64,
    )
    print(
        f"PASS A unique={pass_a.unique} exp={pass_a.expanded} gen={pass_a.generated} "
        f"inc={pass_a.incumbent} wit={len(pass_a.witnesses)} stop={pass_a.stop_reason} "
        f"elapsed={pass_a.elapsed_s:.1f} rss={pass_a.peak_rss_mb}",
        flush=True,
    )

    pass_b_out = {"run": False}
    remaining = 1800.0 - (time.perf_counter() - started)
    if pass_a.witnesses and remaining > 5:
        print("PASS B START exact UCS cheaper-cut check", flush=True)
        pass_b = search_h9_cut(
            sources,
            origin_paths,
            directed=False,
            max_unique=1_000_000,
            time_limit_s=min(800.0, remaining),
            rss_abort_mb=2 * 1024.0,
            start_level=3,
            max_level=3,
            incumbent=pass_a.incumbent,
            harvest_limit=16,
            cheaper_only=True,
        )
        cheaper = bool(pass_b.incumbent is not None and pass_a.incumbent is not None and pass_b.incumbent < pass_a.incumbent)
        proved = (not cheaper) and pass_b.stop_reason in ("frontier empty", "complete", "max level", "harvested")
        if pass_b.stop_reason in ("time limit", "rss abort", "unique limit"):
            proved = False
        pass_b_out = {
            "run": True,
            "unique": pass_b.unique,
            "expanded": pass_b.expanded,
            "generated": pass_b.generated,
            "duplicate_skips": pass_b.duplicate_skips,
            "incumbent": pass_b.incumbent,
            "cheaper": cheaper,
            "proved": proved,
            "stop_reason": pass_b.stop_reason,
            "elapsed_s": pass_b.elapsed_s,
            "peak_rss_mb": pass_b.peak_rss_mb,
            "sd4_expanded": pass_b.sd4_expanded,
        }
        print(
            f"PASS B unique={pass_b.unique} cheaper={cheaper} proved={proved} "
            f"stop={pass_b.stop_reason} elapsed={pass_b.elapsed_s:.1f}",
            flush=True,
        )
        if cheaper:
            pass_a.witnesses = pass_b.witnesses or pass_a.witnesses
            pass_a.incumbent = pass_b.incumbent

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
        prog = h9_progress(end) if ok else {}
        item = dict(rec)
        item["timing"] = remap_timing(rec["timing"])
        item["full_actions"] = [list(a) if a != ("deal",) else ["deal"] for a in full]
        item["full_path_length"] = len(full)
        item["full_cost"] = cost
        item["full_replay_ok"] = ok and bool(prog.get("face_up"))
        item["deals"] = sum(1 for a in full if a == ("deal",))
        item["mandatory_ranks"] = mandatory_rank_status(end) if ok else rec.get("mandatory_ranks")
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
                header=f"# v0.32 unique 9H boundary\n# timing: {first['timing']}\n# g: {first['g']}",
            ),
            encoding="utf-8",
        )
        first["fixture"] = FIXTURE.relative_to(ROOT).as_posix()
        fixture = first["fixture"]

    timings = sorted({w["timing"] for w in witnesses})
    verdict, reason = choose_verdict(True, True, pass_a, pass_b_out, witnesses)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/dynamic-heart9-mandatory-cut-v0-32",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": reason,
        "next_recommendation": next_recommendation(verdict),
        "v31_audit": audit,
        "horizon_ok": horizon["expected_ok"],
        "cut": {
            "valid": True,
            "proof": cut.get("proof"),
            "h9": cut.get("h9"),
            "jh": cut.get("jh"),
            "jh_must_flip_before_h9": cut.get("jh_must_flip_before_h9"),
        },
        "sources": [{k: r[k] for k in r if k != "full_actions"} for r in audited],
        "pass_a": {
            "levels_reached": pass_a.levels_reached,
            "unique": pass_a.unique,
            "expanded": pass_a.expanded,
            "generated": pass_a.generated,
            "duplicate_skips": pass_a.duplicate_skips,
            "cheaper_reopens": pass_a.cheaper_reopens,
            "zero_cost_moves": pass_a.zero_cost_moves,
            "max_depth": pass_a.max_depth,
            "first_g": None if not witnesses else min(w["g"] for w in witnesses),
            "incumbent": pass_a.incumbent,
            "portfolio": len(witnesses),
            "timings": timings,
            "stop_reason": pass_a.stop_reason,
            "elapsed_s": pass_a.elapsed_s,
            "peak_rss_mb": pass_a.peak_rss_mb,
            "sd4_expanded": pass_a.sd4_expanded,
            "per_level": pass_a.per_level,
            "priority": "fd_blockers, fu_blockers, landing_depth, label, tier, g, depth",
        },
        "pass_b": pass_b_out,
        "heart": False,
        "h9": bool(witnesses),
        "min_path": None if not first else first["full_path_length"],
        "min_mw": None if not first else first["full_cost"],
        "stock_at_cut": None if not first else first.get("stock_rows"),
        "fd_at_cut": None if not first else first.get("fd"),
        "full_replay_ok": bool(witnesses) and all(w.get("full_replay_ok") for w in witnesses),
        "fixture": fixture,
        "boundary": first,
        "elapsed_s": time.perf_counter() - started,
        "no_sd4": True,
        "no_heart_search": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    main()
