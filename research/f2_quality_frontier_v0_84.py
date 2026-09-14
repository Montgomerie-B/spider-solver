#!/usr/bin/env python3
"""v0.84: F2 quality frontier from g123 plus exact post-Deal rollout.

Does not rerun the g128 F3 family. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f2_quality_frontier import (
    CONTINUATION_RESERVE_S,
    G128_POST,
    G187_POST,
    HARVEST_S,
    HARVEST_UNIQUE,
    PORTFOLIO_MAX,
    SELECT_N,
    STAGE_A_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    apply_exact_final_deal,
    as_rollout_post,
    beats_g128_control,
    choose_f2_frontier_verdict,
    control_pre_f2_digests,
    g123_ready_targets,
    harvest_f2_target,
    load_f2_closed_table,
    mark_control_f2s,
    next_recommendation,
    post_deal_pareto,
    select_continuation_portfolio,
    select_rollout_roots,
    verify_g123_root,
)
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.final_deal_rollout import rollout_key, run_rollout
from spider.f3_quality_frontier import is_known_closed
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.packed_state import unpack_state
from spider.proof_aware_tactical_bridge import ExactHCache, interpret_continuation_stop
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "f2_quality_frontier_v0_84"
BASE_SHA = "f5bb506023e4e32bcf66e87a415dffa73a42df50"
BRANCH = "agent/f2-quality-frontier-v0-84"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "f2_quality_frontier_progress_v0_84.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_84.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_84.json"


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


def slim_pre(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "foundation_suits", "face_down", "empty_n",
        "legal_tableau", "boundaries", "ordered_digest", "tactical_target",
        "operational_rank", "delta_g", "class", "control_tag", "stock_rows",
    )}


def slim_post(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "pre_g", "post_g", "foundations", "face_down", "empty_n", "legal",
        "boundaries", "assembly_h", "assembly_f", "slack", "viable", "post_class",
        "tactical_target", "control_tag", "selection_role", "pre_class",
        "pre_digest", "post_digest", "foundation_suits",
    )}


def slim_sig(sig: dict) -> dict:
    keep = (
        "role", "pre_g", "post_g", "start_F", "start_h", "start_f", "elapsed_s",
        "unique", "expanded", "generated", "proof_prunes", "stop_reason", "max_F",
        "min_h", "min_f", "best_mobility", "time_first_increase", "g_first_increase",
        "cost_first_increase", "solved", "terminal_g", "n_descendants",
    )
    rec = {k: sig.get(k) for k in keep}
    rec["cheap_F"] = sig.get("cheap_F")
    rec["rollout_key"] = sig.get("rollout_key")
    rec["beats_g128"] = beats_g128_control(sig)
    return rec


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Pre-SD5 F2 quality harvest from autonomous g123, exact final Deal, "
        "frozen v0.76-style rollout. Canonical 172 was not a search input. "
        "The exhausted g128 F3 family was not rerun.",
        "",
        "## g123 root",
        "",
        str({k: (p.get("g123") or {}).get(k) for k in (
            "ok", "g", "foundations", "face_down", "stock_rows", "digest_ok",
        )}),
        "",
        f"ready={p.get('ready_suits')} n_ready={p.get('n_ready')} per_target_s={_fmt(p.get('per_target_s'))}",
        "",
        "## Harvest",
        "",
        f"raw={p.get('n_raw')} unique_pre={p.get('n_unique_pre')} F2={p.get('n_f2')} "
        f"deeper={p.get('n_deeper')} t={_fmt(p.get('harvest_s'))}s",
        "",
        "## Post-Deal Pareto",
        "",
        "| pre g | F | target | fd | post g | post h | post f | slack | legal | boundaries | tag |",
        "| ----: | -: | ------ | -: | -----: | -----: | -----: | ----: | ----: | ---------: | --- |",
    ]
    for rec in p.get("pareto") or []:
        lines.append(
            f"| {rec.get('pre_g')} | {rec.get('foundations')} | {rec.get('tactical_target')} | "
            f"{rec.get('face_down')} | {rec.get('post_g')} | {rec.get('assembly_h')} | "
            f"{rec.get('assembly_f')} | {rec.get('slack')} | {rec.get('legal')} | "
            f"{rec.get('boundaries')} | {rec.get('control_tag') or rec.get('selection_role') or ''} |"
        )
    if not p.get("pareto"):
        lines.append("| — | — | — | — | — | — | — | — | — | — | — |")
    lines += [
        "",
        f"proof-viable={p.get('n_viable_post')} proof-dead={p.get('n_dead_post')}",
        "",
        "## F2 cost-vs-quality",
        "",
        "| pre g | F | target | fd | post g | post h | post f | legal | boundaries | rollout maxF | best rollout f |",
        "| ----: | -: | ------ | -: | -----: | -----: | -----: | ----: | ---------: | -----------: | -------------: |",
    ]
    for rec in p.get("quality_table") or []:
        lines.append(
            f"| {rec.get('pre_g')} | {rec.get('F')} | {rec.get('target')} | {rec.get('fd')} | "
            f"{rec.get('post_g')} | {rec.get('post_h')} | {rec.get('post_f')} | {rec.get('legal')} | "
            f"{rec.get('boundaries')} | {rec.get('rollout_maxF')} | {rec.get('best_rollout_f')} |"
        )
    lines += [
        "",
        "## Stage A ranking",
        "",
        str([
            {
                "role": s.get("role"),
                "post_g": s.get("post_g"),
                "max_F": s.get("max_F"),
                "min_f": s.get("min_f"),
                "stop": s.get("stop_reason"),
                "beats_g128": s.get("beats_g128"),
            }
            for s in p.get("stage_a") or []
        ]),
        "",
        f"Stage B promoted: {p.get('stage_b_roles')}",
        "",
        "## Controls",
        "",
        f"g128 historical post g={G128_POST['post_g']} h={G128_POST['h']} f={G128_POST['f']} F3~{G128_POST['F3_g']}/{G128_POST['F3_f']}",
        f"187 historical post g={G187_POST['post_g']} h={G187_POST['h']} f={G187_POST['f']}",
        f"rediscovered={p.get('rediscovered_controls')}",
        "",
        "## Continuation",
        "",
        f"portfolio n={p.get('n_portfolio')} closed_hits={p.get('n_closed')} "
        f"stop=`{p.get('stop_reason')}` unique={p.get('unique')} exp={p.get('expanded')} "
        f"maxF={p.get('max_foundations')} exhausted={p.get('roots_exhausted')}",
        "",
        f"wall_s={_fmt(p.get('wall_s'))}",
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
            "verdict": "F2_FRONTIER_CONTRACT_FAILURE",
            "contract_reason": "incumbent 187 replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F2_FRONTIER_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("VERIFY g123", flush=True)
    g123 = verify_g123_root(opening)
    print(
        f"G123 ok={g123.get('ok')} g={g123.get('g')} F={g123.get('foundations')} "
        f"fd={g123.get('face_down')} rows={g123.get('stock_rows')} digest_ok={g123.get('digest_ok')}",
        flush=True,
    )
    if not g123.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "F2_FRONTIER_CONTRACT_FAILURE",
            "contract_reason": g123.get("reason"),
            "g123": {k: v for k, v in g123.items() if k != "prefix_actions"},
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT F2_FRONTIER_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    st = unpack_state(bytes.fromhex(g123["ordered_digest"]))
    targets = g123_ready_targets(st, g=123)
    n_ready = len(targets)
    per = HARVEST_S / float(max(1, n_ready))
    print(f"READY n={n_ready} suits={[t['suit'] for t in targets]} per={per:.1f}s", flush=True)
    _write_json(PROG, {"phase": "harvest", "n_ready": n_ready, "per_s": per})

    probes = []
    all_pre = []
    for tgt in targets:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        t_s = min(per, max(5.0, remain - 540.0))
        print(f"HARVEST rank={tgt['operational_rank']} suit={tgt['suit']} t={t_s:.1f}s", flush=True)
        rec = harvest_f2_target(g123, tgt, time_s=t_s, unique=HARVEST_UNIQUE)
        probes.append({k: rec.get(k) for k in rec if k != "terminals"})
        all_pre.extend(rec.get("terminals") or [])
        print(
            f"  unique={rec.get('n_unique')} F2={rec.get('n_f2')} deeper={rec.get('n_deeper')} "
            f"cheap={rec.get('cheapest_g')} stop={rec.get('stop_reason')} t={rec.get('elapsed_s'):.1f}s",
            flush=True,
        )

    controls = control_pre_f2_digests()
    marked = mark_control_f2s(all_pre, controls)
    by_digest = {}
    for rec in marked:
        d = rec["ordered_digest"]
        prev = by_digest.get(d)
        if prev is None or int(rec["g"]) < int(prev["g"]):
            by_digest[d] = rec
    unique_pre = sorted(by_digest.values(), key=lambda r: (int(r["g"]), r["ordered_digest"]))
    rediscovered = sorted({r["control_tag"] for r in unique_pre if r.get("control_tag")})
    print(
        f"PRE unique={len(unique_pre)} F2={sum(1 for r in unique_pre if r['class']=='F2_TERMINAL')} "
        f"deeper={sum(1 for r in unique_pre if r['class']=='PREDEAL_DEEPER')} controls={rediscovered}",
        flush=True,
    )

    cache = ExactHCache()
    posts = []
    n_dead = 0
    for rec in unique_pre:
        if int(rec.get("stock_rows") or 0) != 1 or not rec.get("can_deal"):
            continue
        post = apply_exact_final_deal(rec, cache=cache)
        if not post.get("ok"):
            continue
        if post.get("viable"):
            posts.append(post)
        else:
            n_dead += 1
    pareto = post_deal_pareto(posts)
    selected = select_rollout_roots(posts, k=SELECT_N)
    print(
        f"POST viable={len(posts)} dead={n_dead} pareto={len(pareto)} selected={len(selected)}",
        flush=True,
    )
    _write_json(PROG, {"phase": "rollout_a", "n_selected": len(selected), "n_viable": len(posts)})

    stage_a = []
    descendants = []
    closed = load_f2_closed_table()
    n_closed = 0
    for post in selected:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        if remain < CONTINUATION_RESERVE_S + STAGE_B_S:
            print("STAGE A stop: preserve continuation", flush=True)
            break
        print(
            f"ROLLOUT A role={post.get('selection_role')} pre={post.get('pre_g')} "
            f"post={post.get('post_g')} h={post.get('assembly_h')} f={post.get('assembly_f')}",
            flush=True,
        )
        sig = run_rollout(opening, as_rollout_post(post), time_s=STAGE_A_S, unique=50_000)
        sig["selection_role"] = post.get("selection_role")
        sig["tactical_target"] = post.get("tactical_target")
        sig["control_tag"] = post.get("control_tag")
        stage_a.append(sig)
        for d in sig.get("descendants") or []:
            ident = d.get("ident")
            if ident and is_known_closed(ident, int(d["g"]), closed):
                n_closed += 1
                d["closed"] = True
                d["closed_tag"] = "KNOWN_CLOSED_STATE"
            else:
                descendants.append(d)
        print(
            f"  maxF={sig.get('max_F')} min_f={sig.get('min_f')} stop={sig.get('stop_reason')} "
            f"beats={beats_g128_control(sig)} t={sig.get('elapsed_s'):.1f}s",
            flush=True,
        )

    ranked_a = sorted(stage_a, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    promote = ranked_a[:STAGE_B_N]
    stage_b = []
    remain = TOTAL_S - (time.perf_counter() - wall0)
    b_budget = min(STAGE_B_N * STAGE_B_S, max(0.0, remain - CONTINUATION_RESERVE_S))
    per_b = min(STAGE_B_S, b_budget / float(len(promote))) if promote and b_budget >= 1 else 0.0
    print(f"STAGE B n={len(promote)} per={per_b:.1f}s", flush=True)
    _write_json(PROG, {"phase": "rollout_b", "n": len(promote)})
    by_digest = {s.get("post_digest"): s for s in stage_a}
    post_by_digest = {p.get("post_digest"): p for p in selected}
    for sig in promote:
        if per_b < 1:
            break
        post = post_by_digest.get(sig.get("post_digest"))
        if post is None:
            continue
        extra = [d for d in (sig.get("descendants") or []) if d.get("full_actions")]
        sig_b = run_rollout(opening, as_rollout_post(post), time_s=per_b, unique=50_000, extra_roots=extra)
        sig_b["selection_role"] = sig.get("selection_role")
        sig_b["tactical_target"] = sig.get("tactical_target")
        sig_b["control_tag"] = sig.get("control_tag")
        stage_b.append(sig_b)
        for d in sig_b.get("descendants") or []:
            ident = d.get("ident")
            if ident and is_known_closed(ident, int(d["g"]), closed):
                n_closed += 1
            else:
                descendants.append(d)
        print(
            f"  B role={sig.get('selection_role')} maxF={sig_b.get('max_F')} "
            f"min_f={sig_b.get('min_f')} stop={sig_b.get('stop_reason')}",
            flush=True,
        )

    all_sigs = stage_b + [s for s in stage_a if s.get("post_digest") not in {b.get("post_digest") for b in stage_b}]
    superior = [s for s in all_sigs if beats_g128_control(s) and not s.get("control_tag")]
    portfolio = select_continuation_portfolio(descendants, closed, hard_max=PORTFOLIO_MAX)
    for p_root in selected:
        if p_root.get("viable"):
            rec = {
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
            }
            descendants.append(rec)
    portfolio = select_continuation_portfolio(descendants + portfolio, closed, hard_max=PORTFOLIO_MAX)

    quality_table = []
    for post in selected:
        sig = by_digest.get(post.get("post_digest")) or next(
            (s for s in all_sigs if s.get("post_digest") == post.get("post_digest")), None
        )
        max_f = None if sig is None else sig.get("max_F")
        cheap = {}
        if sig is not None:
            cheap = (sig.get("cheap_F") or {}).get(str(max_f)) or (sig.get("cheap_F") or {}).get(max_f) or {}
        quality_table.append({
            "pre_g": post.get("pre_g"),
            "F": post.get("foundations"),
            "target": post.get("tactical_target"),
            "fd": post.get("face_down"),
            "post_g": post.get("post_g"),
            "post_h": post.get("assembly_h"),
            "post_f": post.get("assembly_f"),
            "legal": post.get("legal"),
            "boundaries": post.get("boundaries"),
            "rollout_maxF": max_f,
            "best_rollout_f": cheap.get("f"),
            "role": post.get("selection_role"),
            "control_tag": post.get("control_tag"),
        })

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if portfolio and remain >= 5.0:
        print(f"CONTINUE n={len(portfolio)} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "continuation", "n_portfolio": len(portfolio)})
        cont = search_f4_portfolio(opening, portfolio, time_s=remain, unique=SEARCH_UNIQUE)
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations}",
            flush=True,
        )
    else:
        print(f"NO continuation portfolio={len(portfolio)} remain={remain:.1f}s", flush=True)

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)
    max_f = 2
    for sig in all_sigs:
        max_f = max(max_f, int(sig.get("max_F") or 0))
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))
    for rec in unique_pre:
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
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.84 F2 quality frontier")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(
                META,
                {
                    "g": int(cont.solution_g),
                    "replay_ok": True,
                    "canonical_input": False,
                    "parent_incumbent": 187,
                    "continuation_stop": cont.stop_reason,
                },
            )
            improved = True

    n_new = sum(1 for r in unique_pre if not r.get("control_tag"))
    search_limited = any(
        (pr.get("stop_reason") == "time limit" and int(pr.get("n_unique") or 0) > 20)
        for pr in probes
    ) or any(s.get("stop_reason") == "time limit" and int(s.get("max_F") or 0) >= 3 for s in all_sigs)

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
        "g123": {k: v for k, v in g123.items() if k != "prefix_actions"},
        "ready_suits": [t["suit"] for t in targets],
        "n_ready": n_ready,
        "per_target_s": per,
        "targets": targets,
        "harvest_s": sum(float(pr.get("elapsed_s") or 0) for pr in probes),
        "probes": probes,
        "n_raw": sum(int(pr.get("n_raw") or 0) for pr in probes),
        "n_unique_pre": len(unique_pre),
        "n_f2": sum(1 for r in unique_pre if r["class"] == "F2_TERMINAL"),
        "n_deeper": sum(1 for r in unique_pre if r["class"] == "PREDEAL_DEEPER"),
        "n_new_f2": n_new,
        "rediscovered_controls": rediscovered,
        "pre_frontier": [slim_pre(r) for r in unique_pre[:48]],
        "n_viable_post": len(posts),
        "n_dead_post": n_dead,
        "pareto": [slim_post(r) for r in pareto],
        "selected": [slim_post(r) for r in selected],
        "stage_a": [slim_sig(s) for s in ranked_a],
        "stage_b": [slim_sig(s) for s in stage_b],
        "stage_b_roles": [s.get("selection_role") for s in stage_b],
        "quality_table": quality_table,
        "n_descendants": len(descendants),
        "n_closed": n_closed,
        "n_closed_table": len(closed),
        "n_portfolio": len(portfolio),
        "portfolio": [
            {k: r.get(k) for k in ("g", "foundations", "assembly_h", "assembly_f", "slack", "ordered_digest")}
            for r in portfolio
        ],
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "generated": None if cont is None else getattr(cont, "generated", None),
        "stop_reason": stop_reason,
        "roots_exhausted": bool(interp.get("exhausted")),
        "recommend_continue_from_these_roots": interp.get("recommend_continue_from_these_roots"),
        "continuation_note": interp.get("note"),
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(cont, "accounting_fail", False)) if cont is not None else False,
        "bound_perf": None if cont is None else {"prunes": cont.lower_bound_prunes, "calls": cont.lower_bound_calls},
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "superior_root": bool(superior),
        "superior_reason": None if not superior else f"n={len(superior)} maxF={max(int(s.get('max_F') or 0) for s in superior)}",
        "search_limited": bool(search_limited),
        "h_cache": cache.stats(),
        "envelope": {
            "time_s": TOTAL_S,
            "harvest_s": HARVEST_S,
            "stage_a_s": STAGE_A_S,
            "stage_b_s": STAGE_B_S,
            "select_n": SELECT_N,
            "portfolio_max": PORTFOLIO_MAX,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
        "controls": {"g128": G128_POST, "g187": G187_POST},
    }
    verdict, reason = choose_f2_frontier_verdict(payload)
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
            "n_unique_pre": len(unique_pre),
            "n_viable_post": len(posts),
            "max_F": max_f,
            "stop_reason": stop_reason,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
