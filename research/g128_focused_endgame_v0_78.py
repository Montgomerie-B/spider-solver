#!/usr/bin/env python3
"""v0.78: focused stock-empty search from the autonomous g128 tactical F2.

Canonical 172 is evaluation context only after the machine search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.g128_focused_endgame import (
    FOCUSED_CEILING,
    V074_FOCUSED,
    choose_g128_verdict,
    choose_rollout_assessment,
    continuation_impact,
    reconstruct_g128_root,
    search_g128_focused,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import (
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "g128_focused_endgame_v0_78"
BASE_SHA = "e6e33061c539f32a10bfda597c4e5c57270fffe3"
BRANCH = "agent/g128-focused-endgame-v0-78"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "g128_focused_endgame_progress_v0_78.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_78.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_78.json"


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


def slim_g123(ck: dict) -> dict:
    return {
        "ok": ck.get("ok"),
        "g": ck.get("g"),
        "foundations": ck.get("foundations"),
        "face_down": ck.get("face_down"),
        "stock_rows": ck.get("stock_rows"),
        "n_prefix": ck.get("n_prefix"),
        "digest_match": ck.get("digest_match"),
        "ordered_digest": ck.get("ordered_digest"),
        "reason": ck.get("reason"),
    }


def slim_g128(rec: dict) -> dict:
    return {
        "ok": rec.get("ok"),
        "g": rec.get("g"),
        "foundations": rec.get("foundations"),
        "face_down": rec.get("face_down"),
        "stock_rows": rec.get("stock_rows"),
        "n_tactical": rec.get("n_tactical"),
        "delta_g": rec.get("delta_g"),
        "target_suit": rec.get("target_suit"),
        "ordered_digest": rec.get("ordered_digest"),
        "same_as_187_f2": rec.get("same_as_187_f2"),
        "reason": rec.get("reason"),
    }


def slim_post(rec: dict) -> dict:
    keys = (
        "ok",
        "g",
        "deal_cost",
        "stock_rows",
        "foundations",
        "face_down",
        "empty_n",
        "legal_tableau",
        "boundaries_total",
        "visible_components",
        "assembly_h",
        "assembly_f",
        "ordered_digest",
        "whole_game_identity",
        "v076_digest_available",
        "v076_digest_match",
        "reason",
    )
    return {k: rec.get(k) for k in keys}


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        f"Rollout assessment: `{p.get('rollout_assessment')}`",
        "",
        p.get("rollout_assessment_reason") or "",
        "",
        "Focused stock-empty search from the autonomous v0.71 g128 tactical F2.",
        "No whole-game campaign. Canonical 172 was not a search input.",
        "",
        "## Autonomy",
        "",
        "1. opening → g123 is the replay-valid 187 incumbent rows=1 checkpoint.",
        "2. g123 → g128 is the stored generic v0.71 tactical planner continuation",
        "   (five tableau actions, rank-1 target, no Deal).",
        "3. SD5 is one real engine Deal. v0.78 only evaluates that future.",
        "",
        "## g123 / g128 / post-SD5",
        "",
        f"* g123 ok={ (p.get('g123') or {}).get('ok') } g={(p.get('g123') or {}).get('g')} "
        f"F={(p.get('g123') or {}).get('foundations')} fd={(p.get('g123') or {}).get('face_down')} "
        f"digest_match={(p.get('g123') or {}).get('digest_match')}",
        f"* g128 ok={ (p.get('g128') or {}).get('ok') } g={(p.get('g128') or {}).get('g')} "
        f"F={(p.get('g128') or {}).get('foundations')} Δg={(p.get('g128') or {}).get('delta_g')} "
        f"same_as_187_f2={(p.get('g128') or {}).get('same_as_187_f2')}",
        f"* post-SD5 g={(p.get('post') or {}).get('g')} F={(p.get('post') or {}).get('foundations')} "
        f"fd={(p.get('post') or {}).get('face_down')} legal={(p.get('post') or {}).get('legal_tableau')} "
        f"h={(p.get('post') or {}).get('assembly_h')} f={(p.get('post') or {}).get('assembly_f')} "
        f"v0.76 digest match={(p.get('post') or {}).get('v076_digest_match')}",
        "",
        "## Envelope",
        "",
        f"* wall {_fmt(p.get('elapsed_s'))} s / unique {p.get('unique')} / expanded {p.get('expanded')} / generated {p.get('generated')}",
        f"* ceiling {FOCUSED_CEILING} / unique cap {SEARCH_UNIQUE} / RSS abort {SEARCH_RSS_MB} MiB",
        f"* stop `{p.get('stop_reason')}` / max F {p.get('max_foundations')} / solution_g {p.get('solution_g')}",
        f"* peak RSS {_fmt(p.get('peak_rss_mb'), 1)} MiB",
        "",
        "## Snapshots",
        "",
        "| t | max F | F3 g/f | min h | min f | mobility | bounds | unique | exp | prunes |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for s in p.get("snapshots") or []:
        cheap = (s.get("cheap_F") or {}).get("3") or {}
        f3 = "—" if not cheap else f"{cheap.get('g')} / {cheap.get('f')}"
        lines.append(
            f"| {s.get('label')} | {s.get('max_F')} | {f3} | {s.get('min_h')} | {s.get('min_f')} | "
            f"{s.get('best_mobility')} | {s.get('min_boundaries')} | {s.get('unique')} | "
            f"{s.get('expanded')} | {s.get('proof_prunes')} |"
        )
    lines += [
        "",
        "## F2–F8 cheapest frontier",
        "",
        "| F | g | h | f | slack | fd | empty | legal | bounds | t s |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for rec in p.get("frontier_list") or []:
        g = rec.get("g")
        h = rec.get("h")
        f = rec.get("f")
        slack = None if g is None or h is None else FOCUSED_CEILING - (int(g) + int(h))
        lines.append(
            f"| {rec.get('F')} | {g} | {h} | {f} | {slack} | {rec.get('face_down')} | "
            f"{rec.get('empty_n')} | {rec.get('legal')} | {rec.get('boundaries')} | {_fmt(rec.get('elapsed_s'))} |"
        )
    bp = p.get("bound_perf") or {}
    lines += [
        "",
        "## Lanes / assembly",
        "",
        str(p.get("lanes") or {}),
        f"proof-prunes {bp.get('prunes')} / calls {bp.get('calls')} / {_fmt(bp.get('seconds'), 3)} s",
        "",
        "## v0.74 focused 187-root comparison",
        "",
        str(V074_FOCUSED),
        "",
        "## Terminal lineage",
        "",
        str(p.get("terminal_lineage") or "none"),
        "",
        "## Continuation-table impact",
        "",
        str(p.get("continuation_impact") or "n/a (no improved complete route)"),
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


def next_recommendation(verdict: str) -> str:
    if verdict == "G128_FOCUSED_COST_IMPROVED":
        return "Promote the new incumbent and make its final-Deal lineage the machine control."
    if verdict == "G128_FOCUSED_SOLVES_NO_GAIN":
        return "Return to integrated search with better final-epoch time allocation on this 187-class future."
    if verdict == "G128_FOCUSED_DEEPER_NO_TERMINAL":
        return "Improve stock-empty search efficiency / assembly reasoning rather than pre-Deal selection."
    if verdict == "G128_FOCUSED_ROLLOUT_OVERSTATED":
        return "Keep rollout as a short-horizon selector; do not treat 30 s rank as true endgame value."
    if verdict == "G128_FOCUSED_SEARCH_LIMITED":
        return "Improve stock-empty conversion efficiency on this root; do not increase total wall time."
    return "Do not promote; diagnose the g128 prefix/root contract."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "G128_FOCUSED_CONTRACT_FAILURE",
            "contract_reason": "187 incumbent replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT G128_FOCUSED_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RECONSTRUCT g123 -> g128 -> SD5", flush=True)
    root = reconstruct_g128_root(opening)
    g123 = slim_g123(root.get("g123") or {})
    g128 = slim_g128(root.get("g128") or {})
    post = slim_post(root.get("post") or {})
    _write_json(
        PROG,
        {"phase": "reconstructed", "g123": g123, "g128": g128, "post_g": post.get("g")},
    )
    if not root.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "root_fail": True,
            "verdict": root.get("verdict") or "G128_FOCUSED_CONTRACT_FAILURE",
            "g123": g123,
            "g128": g128,
            "post": post,
            "policy_reads_canonical": False,
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {payload['verdict']}", flush=True)
        print("DONE", flush=True)
        return payload

    print(
        f"SEARCH focused g129 ceiling=186 900s post_h={post.get('assembly_h')} legal={post.get('legal_tableau')}",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_g128_focused(opening=opening, post=root["post"])
    tracker = res.snapshot_tracker
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    frontier_list = []
    for n, rec in sorted((tracker.cheap_F or {}).items()):
        frontier_list.append({"F": int(n), **{k: v for k, v in rec.items() if k != "full_actions"}})
    snapshots = list(tracker.snapshots)
    if tracker.terminal_snap:
        snapshots = [s for s in snapshots if s.get("label") != "terminal"] + [tracker.terminal_snap] + [
            s for s in snapshots if s.get("label") == "end"
        ]
        # keep a single end
        seen_end = False
        ordered = []
        for s in snapshots:
            if s.get("label") == "end":
                if seen_end:
                    continue
                seen_end = True
            ordered.append(s)
        snapshots = ordered

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < 187
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    terminal_lineage = None
    impact = None
    if res.solved and res.solution_actions:
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )
        terminal_lineage = foundation_progression(opening, list(res.solution_actions))
        if replay_ok and int(res.solution_g) < 187:
            save_solution(
                res.solution_actions,
                FIX,
                g=int(res.solution_g),
                label="Autonomous v0.78 g128 focused solution",
            )
            _write_json(
                META,
                {
                    "g": int(res.solution_g),
                    "replay_g": replay_g,
                    "replay_ok": replay_ok,
                    "five_deals": True,
                    "parent_incumbent": 187,
                    "prefix_source": "current autonomous incumbent to g123",
                    "tactical_source": "v0.71 machine continuation",
                    "tactical_terminal_g": 128,
                    "post_sd5_root_g": 129,
                    "stock_empty_continuation_source": "v0.78 focused search",
                    "canonical_input": False,
                },
            )
            impact = continuation_impact(opening, as_actions(res.solution_actions), int(res.solution_g))
            improved = True

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "focused_ceiling": FOCUSED_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "peak_rss_mb": res.peak_rss_mb,
        "g123": g123,
        "g128": g128,
        "post": post,
        "snapshots": snapshots,
        "frontier_list": frontier_list,
        "time_first_increase": tracker.time_first_increase,
        "g_first_increase": tracker.g_first_increase,
        "lanes": {"expansions": res.lane_exp},
        "bound_perf": {
            "prunes": res.lower_bound_prunes,
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "min_h": res.min_h,
            "max_h": res.max_h,
            "min_f": res.min_f,
            "reconcile": reconcile_lower_bound_telemetry(res),
        },
        "v074_control": V074_FOCUSED,
        "terminal_lineage": terminal_lineage,
        "continuation_impact": impact,
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "ceiling": FOCUSED_CEILING,
        },
    }
    if improved:
        payload["improved_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["incumbent_updated"] = True
        payload["new_incumbent_g"] = int(res.solution_g)
        payload["new_ceiling"] = int(res.solution_g) - 1
    else:
        payload["incumbent_updated"] = False
    verdict, reason = choose_g128_verdict(payload)
    assess, assess_reason = choose_rollout_assessment(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["rollout_assessment"] = assess
    payload["rollout_assessment_reason"] = assess_reason
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
            "rollout_assessment": assess,
            "solution_g": payload.get("solution_g"),
            "max_foundations": payload.get("max_foundations"),
            "elapsed_s": payload.get("elapsed_s"),
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print(f"ROLLOUT_ASSESSMENT {assess}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
