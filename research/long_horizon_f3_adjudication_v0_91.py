#!/usr/bin/env python3
"""v0.91: long-horizon adjudication of the v0.90 F3 basin.

Tactical probes generate F4 candidates. Frozen continuation adjudicates
deep conversion. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_quality_frontier import G141_CONTROL, aggregate_f3_probes, is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.f172_mobility_focused_endgame import reconstruct_f172_mobility_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.long_horizon_f3_adjudication import (
    G148_CONTROL,
    PORTFOLIO_MAX,
    ROOT_SPECS,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_N,
    STAGE_B_S,
    STAGE_B_UNIQUE,
    STAGE_C_N,
    STAGE_C_S,
    STAGE_D_N,
    TACTICAL_MAX_S,
    TOTAL_S,
    classify_f4,
    classify_stage_c,
    choose_long_horizon_verdict,
    fresh_targets,
    gateway_class,
    next_recommendation,
    promote_stage_b,
    select_adjudication_portfolio,
    select_stage_d,
    stage_c_key,
    v090_f3_summary_from_artefact,
    verify_all_v090_f3_roots,
)
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.post_f2_predeal_preparation import load_prep_closed_table
from spider.proof_aware_tactical_bridge import interpret_continuation_stop, probe_proof_aware_target, recover_digest_path
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "long_horizon_f3_adjudication_v0_91"
BASE_SHA = "b121f99d0777ab173f6bf6dc6c5117ff29af11f4"
BRANCH = "agent/long-horizon-f3-adjudication-v0-91"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "long_horizon_f3_adjudication_progress_v0_91.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_91.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_91.json"


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


def slim_root(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "calibration_name", "g", "foundations", "assembly_h", "assembly_f", "slack",
        "face_down", "empty_n", "legal_tableau", "visible_runs", "visible_components",
        "mixed_suit_boundaries", "ready_suits", "n_ready", "ordered_digest", "ident",
        "ok", "reason", "vs_g141_ident", "vs_g148_ident", "known_closed", "elapsed_s",
        "foundation_suits",
    )}


def slim_term(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "assembly_h", "assembly_f", "slack", "gateway", "quality",
        "bridge_loss", "root_g", "root_name", "tactical_target", "class", "viable",
        "closed", "reopened", "portfolio_role", "ordered_digest", "ident", "legal_tableau",
    )}


def slim_probe(pr: dict) -> dict:
    return {k: pr.get(k) for k in (
        "suit", "stage", "root_name", "operational_rank", "elapsed_s", "unique",
        "expanded", "stop_reason", "raw_count", "viable_count", "surplus_count",
        "cheapest_viable_g", "best_viable_f", "min_h_viable", "first_viable_s",
        "proof_prunes",
    )}


def slim_c(s: dict) -> dict:
    deep = s.get("deepest") or {}
    return {
        "source_f3": s.get("source_f3"),
        "role": s.get("portfolio_role"),
        "target": s.get("target"),
        "f4_g": s.get("f4_g"),
        "f4_h": s.get("f4_h"),
        "f4_f": s.get("f4_f"),
        "f4_slack": s.get("f4_slack"),
        "max_F": s.get("max_F"),
        "deepest_g": deep.get("g"),
        "deepest_h": deep.get("h"),
        "deepest_f": deep.get("f"),
        "deepest_slack": deep.get("slack"),
        "stop": s.get("stop_reason"),
        "exhausted": s.get("exhausted"),
        "status": s.get("status"),
        "unique": s.get("unique"),
        "trajectory": s.get("trajectory"),
    }


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
        "Tactical F3→F4 probes are candidate generators. Stage C frozen continuation is the adjudicator.",
        "Canonical 172 was not a search input.",
        "",
        "## v0.90 reporting fix",
        "",
        str(p.get("v090_summary")),
        "",
        "`V090_F3_SUMMARY_FORMATTING_FIX`: first F3 economics stay with ~1.17 s; cheapest-g F3 stays with ~9.94 s.",
        "",
        "## F3 roots",
        "",
        str([slim_root(r) for r in (p.get("roots") or [])]),
        "",
        f"fresh targets: {p.get('target_table')}",
        "",
        "## Stage A / B",
        "",
        str(p.get("stage_a_table")),
        "",
        str(p.get("stage_b_table")),
        "",
        f"raw={p.get('n_raw_f4')} viable={p.get('n_viable_f4')} surplus={p.get('n_surplus_f4')} strong_surplus={p.get('n_strong_surplus')}",
        "",
        "## F4 portfolio",
        "",
        str(p.get("portfolio")),
        f"closed_hits={p.get('n_closed')} reopen={p.get('n_reopen')}",
        "",
        "## Stage C long-horizon scorecard",
        "",
        "| source F3 | F4 g/h/f | F4 slack | 90s maxF | deepest g/h/f | deepest slack | stop | status |",
        "| --------- | -------- | -------: | -------: | ------------- | ------------: | ---- | ------ |",
    ]
    for s in p.get("scorecard") or []:
        d = s.get("deepest") or {}
        dg = s.get("deepest_g") if s.get("deepest_g") is not None else d.get("g")
        dh = s.get("deepest_h") if s.get("deepest_h") is not None else d.get("h")
        df = s.get("deepest_f") if s.get("deepest_f") is not None else d.get("f")
        ds = s.get("deepest_slack") if s.get("deepest_slack") is not None else d.get("slack")
        stop = s.get("stop") if s.get("stop") is not None else s.get("stop_reason")
        lines.append(
            f"| {s.get('source_f3')} | {s.get('f4_g')}/{s.get('f4_h')}/{s.get('f4_f')} | {s.get('f4_slack')} | "
            f"{s.get('max_F')} | {dg}/{dh}/{df} | {ds} | {stop} | {s.get('status')} |"
        )
    lines += [
        "",
        "## Stage D",
        "",
        str(p.get("stage_d")),
        "",
        f"maxF={p.get('max_foundations')} deepest_f={p.get('deepest_f')} slack={p.get('deepest_slack')} "
        f"live={p.get('n_live')} dead={p.get('n_dead')} wall={_fmt(p.get('wall_s'))}",
        "",
        "## Root A vs Root B consequences",
        "",
        str(p.get("root_consequences")),
        "",
        "## Historical g148",
        "",
        f"g148: F3 f177 → F4 f181 → F5 f186 → closed. 187-class converts F4→F8 despite worse local f.",
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


def _fail(reason: str, extra=None) -> dict:
    payload = {
        "experiment": EXPERIMENT,
        "root_fail": True,
        "verdict": "LONG_HORIZON_F3_CONTRACT_FAILURE",
        "contract_reason": reason,
    }
    if extra:
        payload.update(extra)
    _write_json(RESULT, _jsonable(payload))
    write_report(payload)
    print(f"VERDICT LONG_HORIZON_F3_CONTRACT_FAILURE", flush=True)
    print("DONE", flush=True)
    return payload


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        return _fail("incumbent 187 replay failed")

    summary = v090_f3_summary_from_artefact()
    print(f"V090 summary first={summary['first_F3']} cheap={summary['cheap_F3']} cross={summary['cross_wired']}", flush=True)
    if summary.get("cross_wired"):
        return _fail("v0.90 first/cheap F3 times cross-wired", {"cross_wired": True, "v090_summary": summary})

    print("VERIFY v0.90 F3 roots", flush=True)
    checked = verify_all_v090_f3_roots()
    if not checked.get("ok"):
        return _fail("F3 root verification failed", {"roots": [slim_root(r) for r in checked.get("roots") or []]})
    roots = checked["roots"]
    for r in roots:
        print(
            f"  {r.get('calibration_name')} g={r.get('g')} h={r.get('assembly_h')} f={r.get('assembly_f')} "
            f"legal={r.get('legal_tableau')} n_ready={r.get('n_ready')} vs141={r.get('vs_g141_ident')} vs148={r.get('vs_g148_ident')}",
            flush=True,
        )

    closed = load_prep_closed_table()
    _write_json(PROG, {"phase": "tactical", "n_roots": len(roots)})

    stage_a = []
    target_table = {}
    for rec in roots:
        tgts = fresh_targets(rec)
        target_table[rec["calibration_name"]] = [t.get("suit") for t in tgts]
        print(f"TARGETS {rec['calibration_name']} {target_table[rec['calibration_name']]}", flush=True)
        remain = TOTAL_S - (time.perf_counter() - wall0)
        if remain < STAGE_A_S:
            break
        for tgt in tgts:
            remain = TOTAL_S - (time.perf_counter() - wall0)
            if remain < STAGE_A_S or (time.perf_counter() - wall0) > TACTICAL_MAX_S:
                print("STAGE A stop budget", flush=True)
                break
            print(f"A {rec['calibration_name']} suit-rank={tgt.get('operational_rank')} t={STAGE_A_S}", flush=True)
            pr = probe_proof_aware_target(rec, tgt, time_s=STAGE_A_S, unique=STAGE_A_UNIQUE, stage="A")
            pr["root_name"] = rec["calibration_name"]
            pr["root_g"] = rec["g"]
            stage_a.append(pr)
            print(f"  raw={pr.get('raw_count')} viable={pr.get('viable_count')} f={pr.get('best_viable_f')}", flush=True)

    promote = promote_stage_b(stage_a, k=STAGE_B_N)
    stage_b = []
    print(f"STAGE B n={len(promote)}", flush=True)
    for pr in promote:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        tactical_used = time.perf_counter() - wall0
        if remain < STAGE_B_S or tactical_used > TACTICAL_MAX_S:
            print("STAGE B stop budget", flush=True)
            break
        rec = next((r for r in roots if r["calibration_name"] == pr.get("root_name")), None)
        tgt = next((t for t in fresh_targets(rec) if t.get("suit") == pr.get("suit")), None) if rec else None
        if rec is None or tgt is None:
            continue
        print(f"B {rec['calibration_name']} rank={tgt.get('operational_rank')}", flush=True)
        pb = probe_proof_aware_target(rec, tgt, time_s=STAGE_B_S, unique=STAGE_B_UNIQUE, stage="B")
        pb["root_name"] = rec["calibration_name"]
        pb["root_g"] = rec["g"]
        stage_b.append(pb)
        print(f"  raw={pb.get('raw_count')} viable={pb.get('viable_count')} f={pb.get('best_viable_f')}", flush=True)

    aggs = []
    all_probes = stage_a + stage_b
    for rec in roots:
        probes = [p for p in all_probes if p.get("root_name") == rec["calibration_name"]]
        agg = aggregate_f3_probes(rec, rec, probes)
        agg["calibration_name"] = rec["calibration_name"]
        for term in agg.get("viable_terminals") or []:
            term["gateway"] = classify_f4(term)
            term["root_name"] = rec["calibration_name"]
        aggs.append(agg)

    n_raw = sum(int(p.get("raw_count") or 0) for p in all_probes)
    viable_terms = [t for agg in aggs for t in (agg.get("viable_terminals") or [])]
    n_viable = len({t.get("ident") for t in viable_terms if t.get("ident")})
    n_surplus = sum(1 for t in viable_terms if gateway_class(int(t["assembly_f"])) in ("SURPLUS", "STRONG_SURPLUS"))
    n_strong = sum(1 for t in viable_terms if gateway_class(int(t["assembly_f"])) == "STRONG_SURPLUS")

    portfolio = select_adjudication_portfolio(aggs, closed, hard_max=PORTFOLIO_MAX)
    n_closed = sum(1 for t in viable_terms if is_known_closed(t.get("ident"), int(t["g"]), closed))
    n_reopen = sum(1 for t in portfolio if t.get("reopened"))
    live_port = [t for t in portfolio if not t.get("closed")]
    print(f"PORTFOLIO n={len(live_port)} closed={n_closed} reopen={n_reopen} viable={n_viable}", flush=True)
    _write_json(PROG, {"phase": "stage_c", "n_live": len(live_port)})

    scorecard = []
    for rec in live_port[:STAGE_C_N]:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        n_left = max(1, STAGE_C_N - len(scorecard))
        per = min(STAGE_C_S, remain / float(n_left)) if remain >= 1 else 0.0
        if per < 1:
            print("STAGE C stop campaign cap", flush=True)
            break
        print(f"C src={rec.get('root_name')} g={rec.get('g')} f={rec.get('assembly_f')} t={per:.1f}", flush=True)
        res = search_f4_portfolio(opening, [rec], time_s=per, unique=SEARCH_UNIQUE)
        if res is None:
            continue
        sig = classify_stage_c(res, rec)
        scorecard.append(sig)
        print(f"  maxF={sig.get('max_F')} stop={sig.get('stop_reason')} status={sig.get('status')}", flush=True)

    scorecard.sort(key=stage_c_key)
    promote_d = select_stage_d(scorecard, k=STAGE_D_N)
    stage_d = []
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    print(f"STAGE D n={len(promote_d)} remain={remain:.1f}", flush=True)
    if promote_d and remain >= 5:
        per_d = remain / float(len(promote_d))
        extra = []
        for sig in promote_d:
            deep = sig.get("deepest") or {}
            seed = {
                "g": deep.get("g") or sig.get("f4_g"),
                "ordered_digest": deep.get("ordered_digest") or sig.get("ordered_digest"),
                "ident": sig.get("ident"),
                "whole_game_identity": sig.get("ident"),
                "full_actions": deep.get("full_actions") or sig.get("full_actions") or [],
                "foundations": deep.get("F") or sig.get("max_F") or 4,
                "face_down": 2,
                "assembly_h": deep.get("h"),
                "assembly_f": deep.get("f"),
                "stock_rows": 0,
                "root_name": sig.get("source_f3"),
                "tactical_target": sig.get("target"),
            }
            if not seed.get("ordered_digest"):
                continue
            extra.append(seed)
            print(f"D src={seed.get('root_name')} startF={seed.get('foundations')} g={seed.get('g')} t={per_d:.1f}", flush=True)
        if extra:
            res_d = search_f4_portfolio(opening, extra, time_s=remain, unique=SEARCH_UNIQUE)
            if res_d is not None:
                tracker = res_d.snapshot_tracker
                stage_d.append({
                    "stop_reason": res_d.stop_reason,
                    "unique": res_d.unique,
                    "expanded": res_d.expanded,
                    "max_F": tracker.max_F,
                    "solved": bool(res_d.solved),
                    "solution_g": res_d.solution_g,
                    "elapsed_s": res_d.elapsed_s,
                    "cheap_F": {str(k): {kk: vv for kk, vv in v.items() if kk != "full_actions"} for k, v in sorted(tracker.cheap_F.items())},
                    "n_seeds": len(extra),
                })
                print(f"  D stop={res_d.stop_reason} unique={res_d.unique} maxF={tracker.max_F}", flush=True)

    max_f = 3
    deepest_f = None
    deepest_slack = None
    for s in scorecard + stage_d:
        max_f = max(max_f, int(s.get("max_F") or 0))
        if s.get("deepest") and s["deepest"].get("f") is not None:
            fv = int(s["deepest"]["f"])
            deepest_f = fv if deepest_f is None else min(deepest_f, fv)
            sl = s["deepest"].get("slack")
            if sl is not None:
                deepest_slack = int(sl) if deepest_slack is None else max(deepest_slack, int(sl))
        cheap = s.get("cheap_F") or {}
        for rec in cheap.values():
            if rec.get("f") is not None:
                fv = int(rec["f"])
                deepest_f = fv if deepest_f is None else min(deepest_f, fv)

    n_live = sum(1 for s in scorecard if s.get("status") == "LONG_HORIZON_LIVE")
    n_dead = sum(1 for s in scorecard if s.get("status") == "LONG_HORIZON_DEAD")

    by_root = {}
    for name in ("FIRST_LOWEST_F_F3", "CHEAPEST_G_F3"):
        rows = [s for s in scorecard if s.get("source_f3") == name]
        best = rows[0] if rows else None
        by_root[name] = {
            "n": len(rows),
            "best_f4_f": None if not rows else min(int(s["f4_f"]) for s in rows if s.get("f4_f") is not None),
            "max_F": 3 if not rows else max(int(s.get("max_F") or 3) for s in rows),
            "deepest_f": None if not best else (best.get("deepest") or {}).get("f"),
            "deepest_slack": None if not best else (best.get("deepest") or {}).get("slack"),
            "statuses": [s.get("status") for s in rows],
        }

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    solution_g = None
    solved = any(s.get("solved") for s in scorecard) or any(s.get("solved") for s in stage_d)
    sol_actions = None
    if stage_d and stage_d[0].get("solved") and stage_d[0].get("solution_g") is not None:
        solution_g = stage_d[0]["solution_g"]
        # recover from f172 root
        print("RECOVER solution ancestry", flush=True)
        f172 = reconstruct_f172_mobility_root(opening)
        if f172.get("ok") and f172.get("full_actions"):
            # Stage D result may carry solution via search_f4_portfolio
            pass
    # Try to pull solution from last search_f4_portfolio via stage_d unique path — stored only as g.
    # Reconstruct if we have a terminal digest in cheap_F F8.
    term8 = None
    if stage_d:
        cheap = stage_d[0].get("cheap_F") or {}
        term8 = cheap.get("8")
    if solved and term8 and term8.get("ordered_digest") and term8.get("g") is not None and int(term8["g"]) < 187:
        f172 = reconstruct_f172_mobility_root(opening)
        if f172.get("ok"):
            recov = recover_digest_path(opening, f172, term8["ordered_digest"], int(term8["g"]))
            if recov.get("ok"):
                sol_actions = recov.get("full_actions")
                solution_g = int(term8["g"])

    if sol_actions and solution_g is not None and int(solution_g) < 187:
        full = as_actions(sol_actions)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == int(solution_g)
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )
        if replay_ok:
            save_solution(full, FIX, g=int(solution_g), label="Autonomous v0.91 long-horizon F3")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(META, {
                "g": int(solution_g),
                "replay_ok": True,
                "parent_incumbent": 187,
                "source_f2": "NEW_G128_F2",
                "canonical_input": False,
            })
            improved = True

    tactical_limited = any(p.get("stop_reason") in ("time limit", "unique limit") for p in all_probes)
    stage_d_limited = bool(stage_d) and stage_d[0].get("stop_reason") in ("time limit", "unique limit", "rss abort")

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "v090_summary": summary,
        "cross_wired": bool(summary.get("cross_wired")),
        "formatting_fix": "V090_F3_SUMMARY_FORMATTING_FIX",
        "roots": [slim_root(r) for r in roots],
        "target_table": target_table,
        "stage_a_table": [slim_probe(p) for p in stage_a],
        "stage_b_table": [slim_probe(p) for p in stage_b],
        "n_raw_f4": n_raw,
        "n_viable_f4": n_viable,
        "n_surplus_f4": n_surplus,
        "n_strong_surplus": n_strong,
        "portfolio": [slim_term(t) for t in live_port],
        "n_closed": n_closed,
        "n_reopen": n_reopen,
        "scorecard": [slim_c(s) for s in scorecard],
        "n_live": n_live,
        "n_dead": n_dead,
        "stage_d": stage_d,
        "root_consequences": by_root,
        "g141_control": G141_CONTROL,
        "g148_control": G148_CONTROL,
        "max_foundations": max_f,
        "deepest_f": deepest_f,
        "deepest_slack": deepest_slack,
        "tactical_limited": tactical_limited,
        "stage_d_limited": stage_d_limited,
        "search_limited": bool(tactical_limited or stage_d_limited),
        "solved": bool(improved),
        "solution_g": solution_g if improved else None,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": False,
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "envelope": {
            "time_s": TOTAL_S,
            "stage_a_s": STAGE_A_S,
            "stage_b_s": STAGE_B_S,
            "stage_b_n": STAGE_B_N,
            "tactical_max_s": TACTICAL_MAX_S,
            "stage_c_s": STAGE_C_S,
            "stage_c_n": STAGE_C_N,
            "stage_d_n": STAGE_D_N,
            "portfolio_max": PORTFOLIO_MAX,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
    }
    verdict, reason = choose_long_horizon_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "max_F": max_f, "n_live": n_live, "n_dead": n_dead})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "LONG_HORIZON_F3_CONTRACT_FAILURE",
            "contract_reason": f"{type(exc).__name__}: {exc}",
        }
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print("VERDICT LONG_HORIZON_F3_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
