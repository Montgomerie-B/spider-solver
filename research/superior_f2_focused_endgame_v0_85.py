#!/usr/bin/env python3
"""v0.85: focused stock-empty search from the v0.84 superior g128 F2.

One exact root. Frozen global policy. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.superior_f2_focused_endgame import (
    CLOSED_GUARD,
    FOCUSED_CEILING,
    FOCUSED_UNIQUE,
    V074_FOCUSED,
    V078_OLD,
    choose_superior_f2_verdict,
    compare_root_identities,
    next_recommendation,
    reconstruct_superior_f2_root,
    search_superior_f2_focused,
)
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, save_solution

EXPERIMENT = "superior_f2_focused_endgame_v0_85"
BASE_SHA = "8e7c050857822a9e08a5204d4c27a5496dc68490"
BRANCH = "agent/superior-f2-focused-endgame-v0-85"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "superior_f2_focused_endgame_progress_v0_85.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_85.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_85.json"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _jsonable(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def slim_F(rec: dict) -> dict:
    if not rec:
        return {}
    return {k: rec.get(k) for k in (
        "g", "h", "f", "slack", "elapsed_s", "legal", "boundaries", "face_down",
        "empty_n", "foundations", "ordered_digest",
    )}


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Focused stock-empty search from the v0.84 superior g128 F2. "
        "One root. Frozen COST/REVEAL/CONSTRUCTION/READINESS/ECONOMY/COMPLETION. "
        "Canonical 172 was not a search input. Closed-state skip omitted for v0.74 comparability.",
        "",
        "## Root",
        "",
        f"ok={p.get('root_ok')} pre_g={p.get('pre_g')} post_g={p.get('g')} "
        f"h={p.get('assembly_h')} f={p.get('assembly_f')} slack={p.get('slack')} "
        f"deals={p.get('n_deal')} fd={p.get('face_down')}",
        "",
        f"vs old g128 digest_diff={p.get('new_vs_old_digest')} ident_diff={p.get('new_vs_old_ident')}",
        f"vs 187 digest_diff={p.get('new_vs_187_digest')} ident_diff={p.get('new_vs_187_ident')}",
        "",
        "## Snapshots",
        "",
        "| t | maxF | unique | exp | prunes | min_f | min_h |",
        "| -: | ---: | -----: | --: | -----: | ----: | ----: |",
    ]
    for snap in p.get("snapshots") or []:
        lines.append(
            f"| {snap.get('label')} | {snap.get('max_F')} | {snap.get('unique')} | "
            f"{snap.get('expanded')} | {snap.get('proof_prunes')} | {snap.get('min_f')} | {snap.get('min_h')} |"
        )
    lines += [
        "",
        "## F2–F8 frontier (cheapest g)",
        "",
        "| F | g | h | f | slack | fd | empties | legal | boundaries | time |",
        "| -: | -: | -: | -: | ----: | -: | ------: | ----: | ---------: | ---: |",
    ]
    cheap = p.get("cheap_F") or {}
    for f in range(2, 9):
        rec = cheap.get(str(f)) or {}
        if not rec:
            continue
        lines.append(
            f"| {f} | {rec.get('g')} | {rec.get('h')} | {rec.get('f')} | {rec.get('slack')} | "
            f"{rec.get('face_down')} | {rec.get('empty_n')} | {rec.get('legal')} | "
            f"{rec.get('boundaries')} | {_fmt(rec.get('elapsed_s'))} |"
        )
    first3 = (p.get("first_F") or {}).get("3") or {}
    cheap3 = cheap.get("3") or {}
    lines += [
        "",
        f"first F3 g={first3.get('g')} f={first3.get('f')} t={_fmt(first3.get('elapsed_s'))}",
        f"cheapest F3 g={cheap3.get('g')} f={cheap3.get('f')} t={_fmt(cheap3.get('elapsed_s'))}",
        "",
        "## Comparisons",
        "",
        f"v0.78 old g128: first F3 g={V078_OLD['first_F3_g']}/f={V078_OLD['first_F3_f']}, cheapest F3 g={V078_OLD['cheapest_F3_g']}/f={V078_OLD['cheapest_F3_f']}, maxF={V078_OLD['max_F']}",
        f"v0.74 187 root: post 130/h41/f171 terminal 187; F3 156/183",
        "",
        f"stop=`{p.get('stop_reason')}` unique={p.get('unique')} exp={p.get('expanded')} "
        f"prunes={p.get('proof_prunes')} wall={_fmt(p.get('wall_s'))}",
        f"lanes={p.get('lanes')}",
        f"closed_guard={CLOSED_GUARD}",
        "",
        "## Interpretation",
        "",
        p.get("interpretation") or "",
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation") or "",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "SUPERIOR_F2_CONTRACT_FAILURE",
            "contract_reason": "incumbent 187 replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SUPERIOR_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RECONSTRUCT superior F2 root", flush=True)
    root = reconstruct_superior_f2_root(opening)
    print(
        f"ROOT ok={root.get('ok')} g={root.get('g')} h={root.get('assembly_h')} "
        f"f={root.get('assembly_f')} slack={root.get('slack')} deals={root.get('n_deal')}",
        flush=True,
    )
    if not root.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "SUPERIOR_F2_CONTRACT_FAILURE",
            "contract_reason": root.get("reason") or root.get("verdict"),
            "root": {k: v for k, v in root.items() if k != "full_actions"},
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT SUPERIOR_F2_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    cmp_ = compare_root_identities(opening, root)
    print(
        f"CMP vs_old_digest={cmp_.get('new_vs_old_digest')} vs_187_digest={cmp_.get('new_vs_187_digest')} "
        f"vs_old_ident={cmp_.get('new_vs_old_ident')} vs_187_ident={cmp_.get('new_vs_187_ident')}",
        flush=True,
    )
    _write_json(PROG, {"phase": "search", "g": 129, "h": 42, "f": 171})

    print(f"SEARCH unique={FOCUSED_UNIQUE} t={SEARCH_TIME_S}s ceiling={FOCUSED_CEILING} roots=1", flush=True)
    res = search_superior_f2_focused(opening=opening, post=root)
    tracker = res.snapshot_tracker
    print(
        f"SEARCH stop={res.stop_reason} unique={res.unique} exp={res.expanded} "
        f"maxF={tracker.max_F} best={res.solution_g} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    if res.solved and res.solution_actions and int(res.solution_g or 10**9) < 187:
        full = as_actions(res.solution_actions)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )
        if replay_ok:
            save_solution(full, FIX, g=int(res.solution_g), label="Autonomous v0.85 superior F2 focused")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(
                META,
                {
                    "g": int(res.solution_g),
                    "replay_g": replay_g,
                    "replay_ok": True,
                    "parent_incumbent": 187,
                    "root_source": "v0.84 F2 frontier",
                    "pre_f2_g": 128,
                    "post_sd5_g": 129,
                    "root_h": 42,
                    "root_f": 171,
                    "pre_digest": root.get("pre_digest"),
                    "post_digest": root.get("ordered_digest"),
                    "canonical_input": False,
                },
            )
            improved = True

    first3 = tracker.first_F.get(3) or {}
    cheap3 = tracker.cheap_F.get(3) or {}
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "closed_guard": CLOSED_GUARD,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "root_ok": True,
        "pre_g": 128,
        "g": 129,
        "assembly_h": 42,
        "assembly_f": 171,
        "slack": 15,
        "n_deal": root.get("n_deal"),
        "face_down": root.get("face_down"),
        "pre_digest": root.get("pre_digest"),
        "ordered_digest": root.get("ordered_digest"),
        "whole_game_identity": root.get("whole_game_identity"),
        "autonomy": root.get("autonomy"),
        "new_vs_old_digest": cmp_.get("new_vs_old_digest"),
        "new_vs_old_ident": cmp_.get("new_vs_old_ident"),
        "new_vs_187_digest": cmp_.get("new_vs_187_digest"),
        "new_vs_187_ident": cmp_.get("new_vs_187_ident"),
        "identity_compare": cmp_,
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": FOCUSED_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "ceiling": FOCUSED_CEILING,
            "n_roots": 1,
        },
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "states_per_s": None if not res.elapsed_s else float(res.unique) / float(res.elapsed_s),
        "peak_rss_mb": res.peak_rss_mb,
        "stop_reason": res.stop_reason,
        "proof_prunes": res.lower_bound_prunes,
        "proof_calls": res.lower_bound_calls,
        "proof_seconds": getattr(res, "lower_bound_seconds", None),
        "lanes": dict(res.lane_exp or {}),
        "horizon_exp": int((res.lane_exp or {}).get("horizon") or 0),
        "snapshots": tracker.snapshots,
        "cheap_F": {str(k): slim_F(v) for k, v in sorted(tracker.cheap_F.items())},
        "first_F": {str(k): slim_F(v) for k, v in sorted(tracker.first_F.items())},
        "time_first_increase": tracker.time_first_increase,
        "g_first_increase": tracker.g_first_increase,
        "min_h": tracker.min_h,
        "min_f": tracker.min_f,
        "best_mobility": tracker.best_mobility,
        "min_boundaries": tracker.min_boundaries,
        "max_foundations": tracker.max_F,
        "v084_signal": {
            "expected_F3_g": 148,
            "expected_F3_f": 177,
            "expected_t": 5.0,
            "observed_first_F3_g": first3.get("g"),
            "observed_first_F3_f": first3.get("f"),
            "observed_first_F3_t": first3.get("elapsed_s") or tracker.time_first_increase,
        },
        "v078_old": V078_OLD,
        "v074_187": V074_FOCUSED,
        "solved": bool(res.solved),
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(res, "accounting_fail", False)),
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "n_roots_seeded": 1,
    }
    verdict, reason = choose_superior_f2_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "max_F": tracker.max_F,
            "stop_reason": res.stop_reason,
            "unique": res.unique,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
