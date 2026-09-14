#!/usr/bin/env python3
"""v0.88: tableau preparation after F2, before the final Deal.

Two autonomous F2 roots. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f2_quality_frontier import as_rollout_post, beats_g128_control, post_deal_pareto, select_continuation_portfolio
from spider.f3_quality_frontier import is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.final_deal_rollout import rollout_key, run_rollout
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.post_f2_predeal_preparation import (
    CONTINUATION_RESERVE_S,
    PREP_S,
    PREP_UNIQUE,
    SELECT_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    choose_prep_verdict,
    evaluate_prepared,
    harvest_preparation,
    immediate_deal_control,
    load_prep_closed_table,
    next_recommendation,
    reconstruct_root_a,
    reconstruct_root_b,
    select_predeal_for_eval,
    select_prep_rollout_roots,
)
from spider.proof_aware_tactical_bridge import ExactHCache, interpret_continuation_stop
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "post_f2_predeal_preparation_v0_88"
BASE_SHA = "1e3f4cb1a441f1c08c0a30d03b017f133361e03a"
BRANCH = "agent/post-f2-predeal-preparation-v0-88"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "post_f2_predeal_preparation_progress_v0_88.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_88.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_88.json"


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
        "name", "ok", "g", "foundations", "face_down", "stock_rows", "empty_n",
        "legal_tableau", "visible_runs", "mixed_suit_boundaries", "can_deal",
        "ordered_digest", "ident", "n_deal", "n_ready",
    )}


def slim_post(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "source", "prep_delta_g", "prep_band", "pre_g", "post_g", "foundations",
        "assembly_h", "assembly_f", "slack", "legal", "empty_n", "visible_runs",
        "mixed_suit_boundaries", "viable", "post_class", "post_delta_h", "post_delta_f",
        "prep_payback", "selection_role", "post_digest", "ident",
    )}


def slim_sig(sig: dict) -> dict:
    rec = {k: sig.get(k) for k in (
        "role", "pre_g", "post_g", "start_F", "start_h", "start_f", "elapsed_s",
        "unique", "expanded", "stop_reason", "max_F", "min_h", "min_f",
        "time_first_increase", "g_first_increase", "solved", "proof_prunes",
    )}
    rec["cheap_F"] = {str(k): {kk: vv for kk, vv in (v or {}).items() if kk != "full_actions"} for k, v in (sig.get("cheap_F") or {}).items()}
    rec["beats_g128"] = beats_g128_control(sig)
    rec["prep_delta_g"] = sig.get("prep_delta_g")
    rec["source"] = sig.get("source")
    return rec


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Tableau-only preparation after F2, then exact SD5. Canonical 172 was not a search input.",
        "",
        "## Roots",
        "",
        str(p.get("root_a")),
        str(p.get("root_b")),
        "",
        "## Immediate-Deal controls",
        "",
        str(p.get("control_a")),
        str(p.get("control_b")),
        "",
        f"prep unique A/B={p.get('prep_a_n')}/{p.get('prep_b_n')} predeal_f3={p.get('n_predeal_f3')} "
        f"eval={p.get('n_eval')} viable_post={p.get('n_viable')} dead={p.get('n_dead')}",
        "",
        "## Selected rollout",
        "",
        "| src | prep Δg | post g | h | f | slack | maxF | best f |",
        "| --- | ------: | -----: | -: | -: | ----: | ---: | -----: |",
    ]
    for rec in p.get("quality_table") or []:
        lines.append(
            f"| {rec.get('source')} | {rec.get('prep_delta_g')} | {rec.get('post_g')} | "
            f"{rec.get('post_h')} | {rec.get('post_f')} | {rec.get('slack')} | "
            f"{rec.get('rollout_maxF')} | {rec.get('best_rollout_f')} |"
        )
    lines += [
        "",
        f"continuation n={p.get('n_portfolio')} stop=`{p.get('stop_reason')}` "
        f"unique={p.get('unique')} exp={p.get('expanded')} maxF={p.get('max_foundations')} "
        f"exhausted={p.get('roots_exhausted')} wall={_fmt(p.get('wall_s'))}",
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
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "POST_F2_PREP_CONTRACT_FAILURE", "contract_reason": "incumbent 187 replay failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT POST_F2_PREP_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RECONSTRUCT F2 roots", flush=True)
    a = reconstruct_root_a(opening)
    b = reconstruct_root_b(opening)
    print(f"A ok={a.get('ok')} g={a.get('g')} F={a.get('foundations')} rows={a.get('stock_rows')} digest_ok={a.get('ordered_digest')==a.get('artefact_pre_digest')}", flush=True)
    print(f"B ok={b.get('ok')} g={b.get('g')} F={b.get('foundations')} rows={b.get('stock_rows')} digest_ok={b.get('ordered_digest')==b.get('artefact_pre_digest')}", flush=True)
    if not a.get("ok") or not b.get("ok") or a["ordered_digest"] == b["ordered_digest"]:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "POST_F2_PREP_CONTRACT_FAILURE", "contract_reason": "POST_F2_PREP_CONTRACT_FAILURE", "root_a": slim_root(a), "root_b": slim_root(b)}
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT POST_F2_PREP_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    cache = ExactHCache()
    ctrl_a = immediate_deal_control(a, cache=cache)
    ctrl_b = immediate_deal_control(b, cache=cache)
    print(f"CTRL A post {ctrl_a.get('post_g')}/{ctrl_a.get('assembly_h')}/{ctrl_a.get('assembly_f')} ok={ctrl_a.get('ok')}", flush=True)
    print(f"CTRL B post {ctrl_b.get('post_g')}/{ctrl_b.get('assembly_h')}/{ctrl_b.get('assembly_f')} ok={ctrl_b.get('ok')}", flush=True)
    _write_json(PROG, {"phase": "prep", "a": a.get("g"), "b": b.get("g")})

    print(f"PREP A t={PREP_S}s", flush=True)
    ha = harvest_preparation(opening, a, time_s=PREP_S, unique=PREP_UNIQUE)
    print(f"  archive={ha.get('n_archive')} f3+={ha.get('n_predeal_f3')} unique={ha.get('unique')} stop={ha.get('stop_reason')}", flush=True)
    print(f"PREP B t={PREP_S}s", flush=True)
    hb = harvest_preparation(opening, b, time_s=PREP_S, unique=PREP_UNIQUE)
    print(f"  archive={hb.get('n_archive')} f3+={hb.get('n_predeal_f3')} unique={hb.get('unique')} stop={hb.get('stop_reason')}", flush=True)

    eval_pre = select_predeal_for_eval(ha["candidates"] + hb["candidates"])
    print(f"EVAL n={len(eval_pre)}", flush=True)
    posts = []
    n_dead = 0
    ident_best: dict = {}
    for pre in eval_pre:
        ctrl = ctrl_a if pre.get("source") == "NEW_G128_F2" else ctrl_b
        post = evaluate_prepared(pre, ctrl, cache=cache)
        if not post.get("ok"):
            continue
        if not post.get("viable"):
            n_dead += 1
            continue
        ident = post.get("ident")
        prev = ident_best.get(ident)
        if prev is None or int(post["post_g"]) < int(prev["post_g"]):
            ident_best[ident] = post
            post["convergence"] = 1 if prev is None else int(prev.get("convergence") or 1) + 1
        else:
            prev["convergence"] = int(prev.get("convergence") or 1) + 1
    posts = list(ident_best.values())
    pareto = post_deal_pareto(posts)
    selected = select_prep_rollout_roots(posts, [ctrl_a, ctrl_b], k=SELECT_N)
    print(f"POST viable={len(posts)} dead={n_dead} pareto={len(pareto)} selected={len(selected)}", flush=True)
    _write_json(PROG, {"phase": "rollout_a", "n_selected": len(selected)})

    closed = load_prep_closed_table()
    stage_a = []
    descendants = []
    n_closed = 0
    n_reopen = 0
    for post in selected:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        if remain < CONTINUATION_RESERVE_S + STAGE_B_S:
            print("STAGE A stop: preserve continuation", flush=True)
            break
        print(f"ROLLOUT A src={post.get('source')} dg={post.get('prep_delta_g')} post={post.get('post_g')}/{post.get('assembly_h')}/{post.get('assembly_f')}", flush=True)
        rp = as_rollout_post(post)
        rp["tag"] = post.get("selection_role") or post.get("source")
        sig = run_rollout(opening, rp, time_s=STAGE_A_S, unique=50_000)
        sig["source"] = post.get("source")
        sig["prep_delta_g"] = post.get("prep_delta_g")
        sig["selection_role"] = post.get("selection_role")
        stage_a.append(sig)
        for d in sig.get("descendants") or []:
            ident = d.get("ident")
            if ident and is_known_closed(ident, int(d["g"]), closed):
                n_closed += 1
            else:
                descendants.append(d)
        print(f"  maxF={sig.get('max_F')} min_f={sig.get('min_f')} stop={sig.get('stop_reason')}", flush=True)

    ranked_a = sorted(stage_a, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    promote = ranked_a[:STAGE_B_N]
    remain = TOTAL_S - (time.perf_counter() - wall0)
    b_budget = min(STAGE_B_N * STAGE_B_S, max(0.0, remain - CONTINUATION_RESERVE_S))
    per_b = min(STAGE_B_S, b_budget / float(len(promote))) if promote and b_budget >= 1 else 0.0
    print(f"STAGE B n={len(promote)} per={per_b:.1f}s", flush=True)
    post_by = {p.get("post_digest"): p for p in selected}
    stage_b = []
    for sig in promote:
        if per_b < 1:
            break
        post = post_by.get(sig.get("post_digest"))
        if post is None:
            continue
        extra = [d for d in (sig.get("descendants") or []) if d.get("full_actions")]
        sig_b = run_rollout(opening, as_rollout_post(post), time_s=per_b, unique=50_000, extra_roots=extra)
        sig_b["source"] = sig.get("source")
        sig_b["prep_delta_g"] = sig.get("prep_delta_g")
        sig_b["selection_role"] = sig.get("selection_role")
        stage_b.append(sig_b)
        for d in sig_b.get("descendants") or []:
            ident = d.get("ident")
            if ident and is_known_closed(ident, int(d["g"]), closed):
                n_closed += 1
            else:
                descendants.append(d)
        print(f"  B maxF={sig_b.get('max_F')} min_f={sig_b.get('min_f')}", flush=True)

    all_sigs = stage_b + [s for s in ranked_a if s.get("post_digest") not in {x.get("post_digest") for x in stage_b}]
    ctrl_sigs = [s for s in all_sigs if int(s.get("prep_delta_g") or 0) == 0]
    prep_sigs = [s for s in all_sigs if int(s.get("prep_delta_g") or 0) > 0]
    superior = False
    superior_reason = None
    for s in prep_sigs:
        if beats_g128_control(s) and (not ctrl_sigs or tuple(s.get("rollout_key") or ()) < tuple(ctrl_sigs[0].get("rollout_key") or (99,))):
            superior = True
            superior_reason = f"prep dg={s.get('prep_delta_g')} maxF={s.get('max_F')} min_f={s.get('min_f')}"
            break
        if s.get("min_f") is not None and ctrl_sigs:
            best_ctrl_f = min(int(c.get("min_f") or 10**9) for c in ctrl_sigs)
            if int(s["min_f"]) < best_ctrl_f:
                superior = True
                superior_reason = f"prep min_f={s.get('min_f')} < control {best_ctrl_f}"
                break
    productive = False
    for post in posts:
        if int(post.get("prep_delta_g") or 0) > 0 and int(post.get("assembly_f") or 999) < 171:
            productive = True
        if int(post.get("prep_delta_g") or 0) > 0 and post.get("post_delta_f") is not None and int(post["post_delta_f"]) < 0:
            productive = True

    for p_root in selected:
        if p_root.get("viable"):
            descendants.append({
                "g": p_root["post_g"],
                "ordered_digest": p_root["post_digest"],
                "ident": p_root.get("ident"),
                "whole_game_identity": p_root.get("ident"),
                "full_actions": p_root.get("full_actions"),
                "foundations": p_root.get("foundations"),
                "face_down": p_root.get("face_down"),
                "assembly_h": p_root.get("assembly_h"),
                "assembly_f": p_root.get("assembly_f"),
                "slack": p_root.get("slack"),
                "legal_tableau": p_root.get("legal"),
                "stock_rows": 0,
            })
    portfolio = select_continuation_portfolio(descendants, closed, hard_max=24)

    quality_table = []
    by_d = {s.get("post_digest"): s for s in all_sigs}
    for post in selected:
        sig = by_d.get(post.get("post_digest"))
        maxf = None if sig is None else sig.get("max_F")
        cheap = {}
        if sig is not None:
            cheap = (sig.get("cheap_F") or {}).get(str(maxf)) or (sig.get("cheap_F") or {}).get(maxf) or {}
        quality_table.append({
            "source": post.get("source"),
            "prep_delta_g": post.get("prep_delta_g"),
            "post_g": post.get("post_g"),
            "post_h": post.get("assembly_h"),
            "post_f": post.get("assembly_f"),
            "slack": post.get("slack"),
            "rollout_maxF": maxf,
            "best_rollout_f": cheap.get("f"),
            "role": post.get("selection_role"),
        })

    bands = {}
    for rec in ha["candidates"] + hb["candidates"]:
        bands[rec["prep_band"]] = bands.get(rec["prep_band"], 0) + 1

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if portfolio and remain >= 5.0:
        print(f"CONTINUE n={len(portfolio)} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "continuation", "n_portfolio": len(portfolio)})
        cont = search_f4_portfolio(opening, portfolio, time_s=remain, unique=SEARCH_UNIQUE)
        print(f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} maxF={cont.max_foundations}", flush=True)
    else:
        print(f"NO continuation n={len(portfolio)} remain={remain:.1f}s", flush=True)

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)
    max_f = 2
    for sig in all_sigs:
        max_f = max(max_f, int(sig.get("max_F") or 0))
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))
    for rec in ha["candidates"] + hb["candidates"]:
        max_f = max(max_f, int(rec.get("foundations") or 0))

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        full = as_actions(cont.solution_actions)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == int(cont.solution_g)
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )
        if replay_ok:
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.88 post-F2 pre-Deal prep")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(META, {"g": int(cont.solution_g), "replay_ok": True, "canonical_input": False, "parent_incumbent": 187})
            improved = True

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
        "root_a": slim_root(a),
        "root_b": slim_root(b),
        "control_a": slim_post(ctrl_a),
        "control_b": slim_post(ctrl_b),
        "prep_a_n": ha.get("n_archive"),
        "prep_b_n": hb.get("n_archive"),
        "prep_a": {k: ha.get(k) for k in ("elapsed_s", "unique", "expanded", "stop_reason", "n_predeal_f3", "lane_exp")},
        "prep_b": {k: hb.get(k) for k in ("elapsed_s", "unique", "expanded", "stop_reason", "n_predeal_f3", "lane_exp")},
        "n_predeal_f3": int(ha.get("n_predeal_f3") or 0) + int(hb.get("n_predeal_f3") or 0),
        "n_eval": len(eval_pre),
        "n_viable": len(posts),
        "n_dead": n_dead,
        "cost_bands": bands,
        "pareto": [slim_post(r) for r in pareto[:24]],
        "selected": [slim_post(r) for r in selected],
        "stage_a": [slim_sig(s) for s in ranked_a],
        "stage_b": [slim_sig(s) for s in stage_b],
        "quality_table": quality_table,
        "n_closed": n_closed,
        "n_reopen": n_reopen,
        "n_portfolio": len(portfolio),
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "generated": None if cont is None else getattr(cont, "generated", None),
        "stop_reason": stop_reason,
        "roots_exhausted": bool(interp.get("exhausted")),
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(cont, "accounting_fail", False)) if cont is not None else False,
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "superior_prep": superior,
        "superior_reason": superior_reason,
        "productive": productive,
        "search_limited": any(s.get("stop_reason") == "time limit" and int(s.get("max_F") or 0) >= 3 for s in prep_sigs),
        "h_cache": cache.stats(),
        "envelope": {"time_s": TOTAL_S, "prep_s": PREP_S, "stage_a_s": STAGE_A_S, "stage_b_s": STAGE_B_S, "ceiling": BRIDGE_CEILING, "rss_abort_mb": SEARCH_RSS_MB},
    }
    verdict, reason = choose_prep_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "max_F": max_f, "stop_reason": stop_reason})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
