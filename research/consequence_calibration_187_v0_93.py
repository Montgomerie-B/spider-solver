#!/usr/bin/env python3
"""v0.93: ceiling-187 calibration of the consequence evaluator on CONTROL_187.

Production ceiling remains 186. Canonical 172 is not a search input.
The known 187 route is audit/truth only and does not guide search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_policy import COMPLETION_LANES
from spider.consequence_calibration_187 import (
    CALIBRATION_CEILING,
    FOCUSED_UNIQUE,
    KNOWN_ROUTE_GUIDANCE_USED,
    PRODUCTION_CEILING,
    V092_CEILING186,
    audit_known_187_bound,
    choose_calibration_verdict,
    next_recommendation,
    replay_autonomous_187,
    resolve_control_187,
    retrospective_route_hits,
    search_control_187_ceiling187,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S, save_solution

EXPERIMENT = "consequence_calibration_187_v0_93"
BASE_SHA = "3089b43ba76f27c9624e79c107f8414853b1cf82"
BRANCH = "agent/consequence-calibration-187-v0-93"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "consequence_calibration_187_progress_v0_93.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_93.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_93.json"


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
        "g", "h", "f", "slack_187", "elapsed_s", "legal", "visible_runs",
        "mixed_suit_boundaries", "face_down", "empty_n", "foundations",
        "ordered_digest", "ident",
    )}


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        f"Branch: `{p.get('branch')}`  Base: `{p.get('base_sha')}`",
        "",
        "Calibration ceiling **187** (not production 186). One CONTROL_187 root. "
        "Known 187 route used only for replay/bound audit and retrospective identity. "
        f"`known_route_guidance_used={p.get('known_route_guidance_used')}`. Canonical 172 absent.",
        "",
        "## CONTROL_187",
        "",
        str(p.get("control")),
        "",
        "## Autonomous 187 replay",
        "",
        str(p.get("replay_187")),
        "",
        "## Bound audit (post-SD5, ceiling 187)",
        "",
        f"ok={p.get('audit', {}).get('ok')} n={p.get('audit', {}).get('n_post_sd5')} "
        f"max_f={p.get('audit', {}).get('max_f')} min_slack={p.get('audit', {}).get('min_slack')} "
        f"violations={p.get('audit', {}).get('n_violations')}",
        "",
        str(p.get("audit", {}).get("by_F")),
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
        "## F2–F8 first / cheapest / lowest-f",
        "",
        "| F | first t | first g/h/f | cheapest g | lowest f | slack |",
        "| -: | ------: | ----------- | ---------: | -------: | ----: |",
    ]
    first = p.get("first_F") or {}
    cheap = p.get("cheap_F") or {}
    minf = p.get("minf_F") or {}
    for n in range(2, 9):
        fr = first.get(str(n)) or {}
        cr = cheap.get(str(n)) or {}
        mr = minf.get(str(n)) or {}
        if not fr and not cr:
            continue
        lines.append(
            f"| {n} | {_fmt(fr.get('elapsed_s'))} | {fr.get('g')}/{fr.get('h')}/{fr.get('f')} | "
            f"{cr.get('g')} | {mr.get('f')} | {mr.get('slack_187')} |"
        )
    lines += [
        "",
        "## Ceiling 186 vs 187",
        "",
        f"v0.92 ceiling186 @150–300s: maxF={V092_CEILING186['max_F']} g={V092_CEILING186['g']}/h={V092_CEILING186['h']}/f={V092_CEILING186['f']}",
        f"v0.93 ceiling187: 150s/300s snapshots in table above.",
        "",
        f"prunes={p.get('proof_prunes')} calls={p.get('proof_calls')} horizon_exp={p.get('horizon_exp')}",
        "",
        "## Retrospective known-route hits",
        "",
        str(p.get("route_hits")),
        "",
        f"stop=`{p.get('stop_reason')}` unique={p.get('unique')} maxF={p.get('max_foundations')} "
        f"solved={p.get('solved')} g={p.get('solution_g')} wall={_fmt(p.get('wall_s'))}",
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


def _fail(reason: str, verdict: str = "CALIBRATION_187_CONTRACT_FAILURE", extra=None) -> dict:
    payload = {
        "experiment": EXPERIMENT,
        "root_fail": verdict == "CALIBRATION_187_CONTRACT_FAILURE",
        "bound_failure": verdict == "CALIBRATION_187_BOUND_FAILURE",
        "verdict": verdict,
        "contract_reason": reason,
        "known_route_guidance_used": KNOWN_ROUTE_GUIDANCE_USED,
    }
    if extra:
        payload.update(extra)
    _write_json(RESULT, _jsonable(payload))
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187 incumbent", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        return _fail("incumbent 187 replay failed")

    print("REPLAY v0.74 autonomous 187", flush=True)
    replay = replay_autonomous_187(opening)
    print(f"  ok={replay.get('ok')} g={replay.get('g')} deals={replay.get('n_deal')}", flush=True)
    if not replay.get("ok"):
        return _fail(replay.get("reason") or "187 replay failed")

    print("RESOLVE CONTROL_187", flush=True)
    ctrl = resolve_control_187(opening)
    print(
        f"  ok={ctrl.get('ok')} g={ctrl.get('g')} h={ctrl.get('assembly_h')} f={ctrl.get('assembly_f')} "
        f"slack187={ctrl.get('slack_187')} deals={ctrl.get('n_deal')}",
        flush=True,
    )
    if not ctrl.get("ok"):
        return _fail(ctrl.get("reason") or "CONTROL_187 failed")

    print("AUDIT bound along known 187 route", flush=True)
    audit = audit_known_187_bound(opening)
    print(
        f"  ok={audit.get('ok')} n={audit.get('n_post_sd5')} max_f={audit.get('max_f')} "
        f"min_slack={audit.get('min_slack')} violations={audit.get('n_violations')}",
        flush=True,
    )
    if not audit.get("ok"):
        return _fail(
            f"g+h>187 on known route; first={audit.get('first_violation')} over={audit.get('max_violation_over')}",
            verdict="CALIBRATION_187_BOUND_FAILURE",
            extra={"audit": audit, "replay_187": replay, "control": {
                "g": ctrl.get("g"), "h": ctrl.get("assembly_h"), "f": ctrl.get("assembly_f"),
            }},
        )

    assert KNOWN_ROUTE_GUIDANCE_USED is False
    _write_json(PROG, {"phase": "search", "ceiling": CALIBRATION_CEILING, "guidance": False})
    print(
        f"SEARCH ceiling={CALIBRATION_CEILING} unique={FOCUSED_UNIQUE} t={SEARCH_TIME_S}s "
        f"guidance={KNOWN_ROUTE_GUIDANCE_USED} lanes={COMPLETION_LANES}",
        flush=True,
    )
    res = search_control_187_ceiling187(opening=opening, post=ctrl)
    tracker = res.snapshot_tracker
    print(
        f"SEARCH stop={res.stop_reason} unique={res.unique} exp={res.expanded} "
        f"maxF={tracker.max_F} best={res.solution_g} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    print("RETROSPECTIVE known-route identity", flush=True)
    hits = retrospective_route_hits(tracker, audit)
    print(f"  hits={ {k: v.get('status') for k, v in hits.items()} }", flush=True)

    improved = False
    replay_ok = False
    replay_g = None
    g_le_186 = bool(res.solved and res.solution_g is not None and int(res.solution_g) <= 186)
    if res.solved and res.solution_actions and res.solution_g is not None:
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
        if replay_ok and g_le_186:
            save_solution(full, FIX, g=int(res.solution_g), label="Autonomous v0.93 ceiling-187 calibration")
            _write_json(META, {
                "g": int(res.solution_g),
                "replay_ok": True,
                "parent_incumbent": 187,
                "calibration_ceiling": 187,
                "canonical_input": False,
            })
            improved = True

    snap150 = next((s for s in tracker.snapshots if s.get("label") == "t150"), {})
    snap300 = next((s for s in tracker.snapshots if s.get("label") == "t300"), {})
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "known_route_guidance_used": KNOWN_ROUTE_GUIDANCE_USED,
        "production_ceiling": PRODUCTION_CEILING,
        "calibration_ceiling": CALIBRATION_CEILING,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "control": {
            "g": ctrl.get("g"),
            "pre_g": ctrl.get("pre_g"),
            "assembly_h": ctrl.get("assembly_h"),
            "assembly_f": ctrl.get("assembly_f"),
            "slack_187": ctrl.get("slack_187"),
            "n_deal": ctrl.get("n_deal"),
            "legal": ctrl.get("legal"),
            "face_down": ctrl.get("face_down"),
            "foundations": ctrl.get("foundations"),
            "foundation_suits": ctrl.get("foundation_suits"),
            "visible_runs": ctrl.get("visible_runs"),
            "mixed_suit_boundaries": ctrl.get("mixed_suit_boundaries"),
            "post_digest": ctrl.get("post_digest"),
            "ident": ctrl.get("ident"),
        },
        "replay_187": replay,
        "audit": {k: audit.get(k) for k in (
            "ok", "n_post_sd5", "max_f", "min_slack", "max_f_state", "by_F",
            "n_violations", "first_violation", "max_violation_over",
        )},
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": FOCUSED_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "ceiling": CALIBRATION_CEILING,
            "n_roots": 1,
        },
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "peak_rss_mb": res.peak_rss_mb,
        "stop_reason": res.stop_reason,
        "proof_prunes": res.lower_bound_prunes,
        "proof_calls": res.lower_bound_calls,
        "lanes": dict(res.lane_exp or {}),
        "horizon_exp": int((res.lane_exp or {}).get("horizon") or 0),
        "snapshots": tracker.snapshots,
        "cheap_F": {str(k): slim_F(v) for k, v in sorted(tracker.cheap_F.items())},
        "first_F": {str(k): slim_F(v) for k, v in sorted(tracker.first_F.items())},
        "minf_F": {str(k): slim_F(v) for k, v in sorted(tracker.minf_F.items())},
        "max_foundations": tracker.max_F,
        "min_h": tracker.min_h,
        "min_f": tracker.min_f,
        "v092": V092_CEILING186,
        "at_150s": {"max_F": snap150.get("max_F"), "min_f": snap150.get("min_f"), "cheap_F": snap150.get("cheap_F")},
        "at_300s": {"max_F": snap300.get("max_F"), "min_f": snap300.get("min_f"), "cheap_F": snap300.get("cheap_F")},
        "route_hits": hits,
        "solved": bool(res.solved),
        "solution_g": res.solution_g,
        "g_le_186": g_le_186,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "time_to_terminal": None if not tracker.terminal_snap else tracker.terminal_snap.get("elapsed_s"),
        "accounting_fail": bool(getattr(res, "accounting_fail", False)),
        "incumbent_updated": improved,
        "terminal_lineage": None if not (improved and replay_ok) else foundation_progression(opening, as_actions(res.solution_actions)),
    }
    verdict, reason = choose_calibration_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "max_F": tracker.max_F, "solved": bool(res.solved)})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "CALIBRATION_187_CONTRACT_FAILURE",
            "contract_reason": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT CALIBRATION_187_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
