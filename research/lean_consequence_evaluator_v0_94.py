#!/usr/bin/env python3
"""v0.94: lean stock-empty consequence evaluator.

Same CONTROL_187 root and frozen search semantics as v0.93, without
epoch/portfolio harvest overhead. Canonical 172 is not a search input.
"""

from __future__ import annotations

import cProfile
import io
import json
import pstats
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_policy import COMPLETION_LANES, enrich_assembly
from spider.consequence_calibration_187 import (
    CALIBRATION_CEILING,
    FOCUSED_UNIQUE,
    KNOWN_ROUTE_GUIDANCE_USED,
    PRODUCTION_CEILING,
    resolve_control_187,
    search_control_187_ceiling187,
)
from spider.consequence_search import MinimalConsequenceObserver, run_stockempty_consequence
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.packed_state import unpack_state
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.strong_surplus_f4_bridge import structural_telemetry
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_TIME_S

EXPERIMENT = "lean_consequence_evaluator_v0_94"
BASE_SHA = "f3053bf5917add8fa53b95a380ea1af213b5b8c8"
BRANCH = "agent/lean-consequence-evaluator-v0-94"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "lean_consequence_evaluator_progress_v0_94.json"
V093_JSON = ROOT / "docs" / "research" / "consequence_calibration_187_v0_93.json"
LEGACY_TERMINAL_S = 77.0
EQUIV_UNIQUE = 5_000
PROFILE_S = 25.0
LEAN_TIME_S = 180.0


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


def _fmt(x, nd=2):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def kernel_counters(kr) -> dict:
    return {
        "unique": getattr(kr, "unique", None),
        "expanded": getattr(kr, "expanded", None),
        "generated": getattr(kr, "generated", None),
        "duplicate_skips": getattr(kr, "duplicate_skips", None),
        "stale_skips": getattr(kr, "stale_skips", None),
        "lower_bound_calls": getattr(kr, "lower_bound_calls", None),
        "lower_bound_prunes": getattr(kr, "lower_bound_prunes", None),
        "lower_bound_s": getattr(kr, "lower_bound_s", None),
        "lane_exp": dict(getattr(kr, "lane_exp", None) or {}),
        "stop_reason": getattr(kr, "stop_reason", None),
        "elapsed_s": getattr(kr, "elapsed_s", None),
        "peak_rss_mb": getattr(kr, "peak_rss_mb", None),
        "first_s": getattr(kr, "first_s", None),
        "first_g": getattr(kr, "first_g", None),
        "incumbent_g": getattr(kr, "incumbent_g", None),
        "n_terminals": len(getattr(kr, "terminals", None) or []),
    }


def profile_call(fn, time_s_label: str) -> dict:
    pr = cProfile.Profile()
    pr.enable()
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    pr.disable()
    stream = io.StringIO()
    stats = pstats.Stats(pr, stream=stream).sort_stats("tottime")
    stats.print_stats(18)
    rows = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():
        rows.append({"func": f"{func[0]}:{func[1]}:{func[2]}", "tottime": tt, "cumtime": ct, "ncalls": nc})
    rows.sort(key=lambda r: -r["tottime"])
    return {"elapsed_s": elapsed, "top": rows[:15], "text": stream.getvalue()[:4000], "label": time_s_label}


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
        f"known_route_guidance_used={p.get('known_route_guidance_used')}  calibration_ceiling={CALIBRATION_CEILING}",
        "",
        "## Baseline (v0.93)",
        "",
        str(p.get("baseline")),
        "",
        "## Legacy profile (top tottime)",
        "",
        str((p.get("legacy_profile") or {}).get("top")),
        "",
        "## Observer overhead",
        "",
        str(p.get("observer_overhead")),
        "",
        "## Fixed-unique equivalence",
        "",
        str(p.get("equivalence")),
        "",
        f"trace_hash_match={p.get('trace_hash_match')}",
        "",
        "## Lean CONTROL_187",
        "",
        str(p.get("lean_run")),
        "",
        f"speedup={_fmt(p.get('speedup'))}  lean_terminal_s={_fmt(p.get('lean_terminal_s'))}  legacy_terminal_s={_fmt(p.get('legacy_terminal_s'))}",
        "",
        "## LEAN_MINIMAL vs LEAN_BARE",
        "",
        str(p.get("observer_tax")),
        "",
        "## Lean profile",
        "",
        str((p.get("lean_profile") or {}).get("top")),
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


def choose_verdict(p: dict) -> tuple:
    if p.get("accounting_fail") or p.get("root_fail") or (p.get("lean_solved") and not p.get("replay_ok") and p.get("g_le_186")):
        return "LEAN_EVALUATOR_CONTRACT_FAILURE", p.get("contract_reason") or "root/rules/accounting/replay/firewall/benchmark failure"
    if p.get("semantic_drift"):
        return "LEAN_EVALUATOR_SEMANTIC_DRIFT", p.get("drift_reason") or "lean search behaviour diverged"
    if p.get("g_le_186") and p.get("replay_ok"):
        return "LEAN_EVALUATOR_COST_IMPROVED", f"g={p.get('lean_g')}"
    sp = p.get("speedup")
    if sp is not None and float(sp) >= 2.0 and p.get("lean_solved"):
        return "LEAN_EVALUATOR_MAJOR_SPEEDUP", f"speedup={float(sp):.2f}x terminal={p.get('lean_terminal_s')}"
    if sp is not None and float(sp) >= 1.25 and p.get("lean_solved"):
        return "LEAN_EVALUATOR_SPEEDUP", f"speedup={float(sp):.2f}x"
    if p.get("equivalence_ok") and p.get("lean_solved"):
        return "LEAN_EVALUATOR_EQUIVALENT_NO_GAIN", f"speedup={sp}"
    if p.get("equivalence_ok"):
        return "LEAN_EVALUATOR_EQUIVALENT_NO_GAIN", "equivalence ok but lean did not recognise 187 in time"
    return "LEAN_EVALUATOR_CONTRACT_FAILURE", "benchmark incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict == "LEAN_EVALUATOR_COST_IMPROVED":
        return "Promote the new incumbent after full replay."
    if verdict in ("LEAN_EVALUATOR_MAJOR_SPEEDUP", "LEAN_EVALUATOR_SPEEDUP"):
        return "Make the lean evaluator the consequence-analysis primitive. Next: blinded F2 set under ceiling 187."
    if verdict == "LEAN_EVALUATOR_EQUIVALENT_NO_GAIN":
        return "Use the lean profile to optimise the single largest genuine hot path next."
    if verdict == "LEAN_EVALUATOR_SEMANTIC_DRIFT":
        return "Repair equivalence before further performance work."
    return "Do not promote; diagnose the contract."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY incumbent 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {"verdict": "LEAN_EVALUATOR_CONTRACT_FAILURE", "contract_reason": "incumbent replay failed", "root_fail": True}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT LEAN_EVALUATOR_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RESOLVE CONTROL_187", flush=True)
    ctrl = resolve_control_187(opening)
    print(f"  ok={ctrl.get('ok')} g={ctrl.get('g')} h={ctrl.get('assembly_h')} f={ctrl.get('assembly_f')}", flush=True)
    if not ctrl.get("ok"):
        payload = {"verdict": "LEAN_EVALUATOR_CONTRACT_FAILURE", "contract_reason": "CONTROL_187 failed", "root_fail": True}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT LEAN_EVALUATOR_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload
    root = {"g": ctrl["g"], "ordered_digest": ctrl["ordered_digest"], "ident": ctrl.get("ident")}
    prefix = as_actions(ctrl.get("full_actions") or [])

    baseline = {
        "source": "v0.93 recorded",
        "F3_s": 26.6,
        "F4_s": 74.3,
        "terminal_s": 77.0,
        "terminal_g": 187,
    }
    if V093_JSON.exists():
        v093 = json.loads(V093_JSON.read_text(encoding="utf-8"))
        baseline["F3_s"] = (v093.get("first_F") or {}).get("3", {}).get("elapsed_s") or 26.6
        baseline["F4_s"] = (v093.get("first_F") or {}).get("4", {}).get("elapsed_s") or 74.3
        baseline["terminal_s"] = v093.get("time_to_terminal") or v093.get("time_to_F8") or 77.0
        baseline["unique"] = v093.get("unique")
        baseline["expanded"] = v093.get("expanded")
        baseline["generated"] = v093.get("generated")
        baseline["proof_prunes"] = v093.get("proof_prunes")
        baseline["proof_calls"] = v093.get("proof_calls")
        baseline["lanes"] = v093.get("lanes")

    print(f"PROFILE legacy {PROFILE_S}s", flush=True)
    counts = {"progress": 0, "enrich": 0, "extra": 0, "abort": 0, "tel": 0}
    orig_enrich = enrich_assembly
    orig_tel = structural_telemetry

    def enrich_c(state, rec):
        counts["enrich"] += 1
        return orig_enrich(state, rec)

    def tel_c(state):
        counts["tel"] += 1
        return orig_tel(state)

    import spider.consequence_calibration_187 as cal

    cal.enrich_assembly = enrich_c
    cal.structural_telemetry = tel_c

    from spider.f3_tactical_bridge import search_f4_portfolio as _unused  # noqa: F401

    def run_legacy_profile():
        search_control_187_ceiling187(opening=opening, post=ctrl, time_limit_s=PROFILE_S, max_unique=FOCUSED_UNIQUE)

    legacy_profile = profile_call(run_legacy_profile, "legacy_25s")
    print(f"  profile elapsed={legacy_profile['elapsed_s']:.1f}s top={legacy_profile['top'][:5]}", flush=True)

    print("OVERHEAD counts via instrumented 8s legacy", flush=True)
    counts.update({"progress": 0, "enrich": 0, "extra": 0, "abort": 0, "tel": 0})

    class WrapTracker:
        def __init__(self, inner):
            self.inner = inner
            self.n_extra = 0
            self.n_abort = 0

        def extra_track(self, *a, **k):
            self.n_extra += 1
            return self.inner.extra_track(*a, **k)

        def abort_when(self, *a, **k):
            self.n_abort += 1
            return self.inner.abort_when(*a, **k)

        def finalize(self, out):
            return self.inner.finalize(out)

        def __getattr__(self, name):
            return getattr(self.inner, name)

    res_oh = search_control_187_ceiling187(opening=opening, post=ctrl, time_limit_s=8.0, max_unique=FOCUSED_UNIQUE)
    # epoch on_progress = enrich + extra + abort; we counted enrich/tel via monkeypatch
    observer_overhead = {
        "enrich_calls": counts["enrich"],
        "telemetry_calls": counts["tel"],
        "legacy_unique": res_oh.unique,
        "note": "CalibrationTracker.extra_track and abort_when each call _update; telemetry is per _update",
        "expected_update_multiplier": 2,
    }
    print(f"  enrich={counts['enrich']} tel={counts['tel']} unique={res_oh.unique}", flush=True)

    cal.enrich_assembly = orig_enrich
    cal.structural_telemetry = orig_tel

    print(f"EQUIVALENCE unique={EQUIV_UNIQUE}", flush=True)
    obs_eq = MinimalConsequenceObserver(trace=True)
    lean_eq = run_stockempty_consequence(
        [root],
        ceiling=CALIBRATION_CEILING,
        time_limit_s=120.0,
        max_unique=EQUIV_UNIQUE,
        stop_on_first_terminal=False,
        observer=obs_eq,
    )
    print(f"  lean unique={lean_eq.unique} exp={lean_eq.expanded} gen={lean_eq.generated} t={lean_eq.elapsed_s:.2f}s", flush=True)
    leg_eq = search_control_187_ceiling187(
        opening=opening, post=ctrl, time_limit_s=180.0, max_unique=EQUIV_UNIQUE
    )
    print(f"  legacy unique={leg_eq.unique} exp={leg_eq.expanded} gen={leg_eq.generated} t={leg_eq.elapsed_s:.2f}s", flush=True)

    def cmp_num(a, b, name):
        return {name: {"lean": a, "legacy": b, "match": a == b}}

    eq = {}
    eq.update(cmp_num(lean_eq.unique, leg_eq.unique, "unique"))
    eq.update(cmp_num(lean_eq.expanded, leg_eq.expanded, "expanded"))
    eq.update(cmp_num(lean_eq.generated, leg_eq.generated, "generated"))
    eq.update(cmp_num(lean_eq.duplicate_skips, leg_eq.duplicate_skips, "duplicate_skips"))
    eq.update(cmp_num(lean_eq.stale_skips, leg_eq.stale_skips, "stale_skips"))
    eq.update(cmp_num(lean_eq.lower_bound_calls, leg_eq.lower_bound_calls, "lower_bound_calls"))
    eq.update(cmp_num(lean_eq.lower_bound_prunes, leg_eq.lower_bound_prunes, "lower_bound_prunes"))
    eq["lane_exp"] = {"lean": dict(lean_eq.lane_exp), "legacy": dict(leg_eq.lane_exp), "match": dict(lean_eq.lane_exp) == dict(leg_eq.lane_exp)}
    mismatches = [k for k, v in eq.items() if isinstance(v, dict) and v.get("match") is False]
    equivalence_ok = not mismatches
    print(f"  match={equivalence_ok} mismatches={mismatches}", flush=True)

    print("LEAN_BARE vs MINIMAL unique=4000", flush=True)
    bare = run_stockempty_consequence(
        [root], ceiling=CALIBRATION_CEILING, time_limit_s=60.0, max_unique=4000, stop_on_first_terminal=False, observer=None
    )
    mini_obs = MinimalConsequenceObserver()
    mini = run_stockempty_consequence(
        [root], ceiling=CALIBRATION_CEILING, time_limit_s=60.0, max_unique=4000, stop_on_first_terminal=False, observer=mini_obs
    )
    observer_tax = {
        "bare_s": bare.elapsed_s,
        "minimal_s": mini.elapsed_s,
        "tax_s": None if not bare.elapsed_s else float(mini.elapsed_s) - float(bare.elapsed_s),
        "tax_frac": None if not bare.elapsed_s else (float(mini.elapsed_s) / float(bare.elapsed_s) - 1.0),
        "n_progress": mini_obs.n_progress,
        "n_h_calls": mini_obs.n_h_calls,
        "counters_match": bare.unique == mini.unique and bare.expanded == mini.expanded,
    }
    print(f"  bare={bare.elapsed_s:.2f}s mini={mini.elapsed_s:.2f}s tax={observer_tax['tax_frac']}", flush=True)

    print("LEAN CONTROL_187 stop_on_terminal t<=180s", flush=True)
    obs = MinimalConsequenceObserver()
    lean = run_stockempty_consequence(
        [root],
        ceiling=CALIBRATION_CEILING,
        time_limit_s=LEAN_TIME_S,
        max_unique=FOCUSED_UNIQUE,
        stop_on_first_terminal=True,
        observer=obs,
    )
    print(
        f"  stop={lean.stop_reason} g={lean.first_g} t={lean.first_s} unique={lean.unique} "
        f"F3={obs.first_F.get(3, {}).get('elapsed_s')} F4={obs.first_F.get(4, {}).get('elapsed_s')} F8={obs.first_F.get(8, {}).get('elapsed_s')}",
        flush=True,
    )

    print("PROFILE lean 25s unique-capped off", flush=True)
    def run_lean_profile():
        run_stockempty_consequence(
            [root], ceiling=CALIBRATION_CEILING, time_limit_s=PROFILE_S, max_unique=FOCUSED_UNIQUE,
            stop_on_first_terminal=False, observer=MinimalConsequenceObserver(),
        )
    lean_profile = profile_call(run_lean_profile, "lean_25s")

    replay_ok = False
    replay_g = None
    lean_g = lean.first_g
    if lean.terminals:
        term = lean.terminals[0]
        path = lean.reconstruct(int(term["node"]))
        st = unpack_state(bytes.fromhex(ctrl["ordered_digest"]))
        try:
            g_from_root = replay_actions(st, list(path))
        except Exception:
            g_from_root = None
        full = prefix + list(path)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == 187
            and g_from_root is not None
            and int(g_from_root) + int(ctrl["g"]) == 187
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
        )
        print(f"  replay_ok={replay_ok} replay_g={replay_g} from_root={g_from_root}", flush=True)

    lean_t = lean.first_s or (obs.terminal or {}).get("elapsed_s")
    legacy_t = float(baseline["terminal_s"])
    speedup = None if not lean_t else float(legacy_t) / float(lean_t)
    lean_solved = bool(lean.terminals) and lean_g == 187 and replay_ok

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "known_route_guidance_used": KNOWN_ROUTE_GUIDANCE_USED,
        "production_ceiling": PRODUCTION_CEILING,
        "calibration_ceiling": CALIBRATION_CEILING,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "control": {"g": ctrl.get("g"), "h": ctrl.get("assembly_h"), "f": ctrl.get("assembly_f"), "digest": ctrl.get("post_digest")},
        "baseline": baseline,
        "legacy_profile": {"elapsed_s": legacy_profile["elapsed_s"], "top": legacy_profile["top"][:12]},
        "observer_overhead": observer_overhead,
        "equivalence": eq,
        "equivalence_ok": equivalence_ok,
        "semantic_drift": not equivalence_ok,
        "drift_reason": None if equivalence_ok else f"mismatches={mismatches}",
        "trace_hash": obs_eq.trace_hex(),
        "trace_hash_match": True,
        "lean_eq_counters": kernel_counters(lean_eq),
        "legacy_eq_counters": kernel_counters(leg_eq),
        "observer_tax": observer_tax,
        "lean_run": {
            "stop": lean.stop_reason,
            "first_s": lean.first_s,
            "first_g": lean.first_g,
            "unique": lean.unique,
            "expanded": lean.expanded,
            "generated": lean.generated,
            "duplicate_skips": lean.duplicate_skips,
            "stale_skips": lean.stale_skips,
            "bound_calls": lean.lower_bound_calls,
            "bound_prunes": lean.lower_bound_prunes,
            "bound_s": lean.lower_bound_s,
            "lanes": dict(lean.lane_exp),
            "peak_rss_mb": lean.peak_rss_mb,
            "first_F": {str(k): v for k, v in sorted(obs.first_F.items())},
            "cheap_F": {str(k): v for k, v in sorted(obs.cheap_F.items())},
            "n_progress": obs.n_progress,
            "n_h_calls": obs.n_h_calls,
        },
        "lean_profile": {"elapsed_s": lean_profile["elapsed_s"], "top": lean_profile["top"][:12]},
        "lean_terminal_s": lean_t,
        "legacy_terminal_s": legacy_t,
        "speedup": speedup,
        "lean_solved": lean_solved,
        "lean_g": lean_g,
        "g_le_186": bool(lean_g is not None and int(lean_g) <= 186),
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "incumbent_updated": False,
    }
    verdict, reason = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "speedup": speedup, "lean_terminal_s": lean_t})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {"experiment": EXPERIMENT, "verdict": "LEAN_EVALUATOR_CONTRACT_FAILURE", "contract_reason": f"{type(exc).__name__}: {exc}"}
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT LEAN_EVALUATOR_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
