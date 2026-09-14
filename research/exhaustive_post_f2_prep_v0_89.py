#!/usr/bin/env python3
"""v0.89: exhaustive post-Deal evaluation of the v0.88 preparation archive.

Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.exhaustive_post_f2_prep import (
    ARCHIVE_EVAL_ALL,
    EXPECTED_A,
    EXPECTED_B,
    EXPECTED_TOTAL,
    PORTFOLIO_MAX,
    ROLLOUT_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    analyze_f171,
    archive_mode,
    attach_full_actions,
    best_post_states,
    bucket_counts,
    bucket_counts_grouped,
    choose_exhaustive_verdict,
    compare_sample_coverage,
    exhaustive_pareto,
    exhaustive_post_deal,
    next_recommendation,
    select_exhaustive_rollout,
    slim_winner,
    v088_sample_digests,
)
from spider.f2_quality_frontier import as_rollout_post, select_continuation_portfolio
from spider.f3_quality_frontier import is_known_closed
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.final_deal_rollout import rollout_key, run_rollout
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.post_f2_predeal_preparation import (
    PREP_S,
    PREP_UNIQUE,
    harvest_preparation,
    immediate_deal_control,
    load_prep_closed_table,
    reconstruct_root_a,
    reconstruct_root_b,
)
from spider.proof_aware_tactical_bridge import ExactHCache, interpret_continuation_stop
from spider.research_actions import as_actions, is_deal, rss_mb
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "exhaustive_post_f2_prep_v0_89"
BASE_SHA = "03c472fb74b92dc44c714ca2866d37fc2118cfd2"
BRANCH = "agent/exhaustive-post-f2-prep-v0-89"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "exhaustive_post_f2_prep_progress_v0_89.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_89.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_89.json"


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


def slim_post(r: dict) -> dict:
    return slim_winner(r)


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        f"Branch: `{p.get('branch')}`",
        f"Base: `{p.get('base_sha')}`",
        f"Archive mode: `{p.get('archive_mode')}`. ARCHIVE_EVAL={ARCHIVE_EVAL_ALL}.",
        "",
        "## Archive",
        "",
        f"- Root A n={p.get('n_a')} expected={p.get('expected_a')}",
        f"- Root B n={p.get('n_b')} expected={p.get('expected_b')}",
        f"- total n={p.get('n_pre')} expected={p.get('expected_total')} ok={p.get('archive_totals_ok')}",
        f"- evaluations={p.get('n_eval')} illegal={p.get('n_illegal')}",
        f"- unique post identities={p.get('n_unique_post')}",
        f"- convergence max={p.get('convergence_max')} mean={_fmt(p.get('convergence_mean'), 2)}",
        f"- proof-viable={p.get('n_viable')} proof-dead={p.get('n_dead')}",
        f"- eval/s={_fmt(p.get('eval_per_s'), 1)} deal_s={_fmt(p.get('t_deal_s'))} h_s={_fmt(p.get('t_h_s'))} dedup_s={_fmt(p.get('t_dedup_s'))}",
        f"- h-cache={p.get('h_cache')} peak_rss_mb={_fmt(p.get('peak_rss_mb'))}",
        "",
        "## f distribution (unique post identities)",
        "",
        str(p.get("f_buckets")),
        "",
        "By source:",
        "",
        str(p.get("f_buckets_by_source")),
        "",
        "By prep band:",
        "",
        str(p.get("f_buckets_by_band")),
        "",
        f"any f<171 = `{p.get('any_f_lt_171')}` min_f={p.get('min_f')} f171={p.get('f171_n')}",
        "",
        "## Absolute best unique post states",
        "",
        str(p.get("best_posts")),
        "",
        "## f=171 analysis",
        "",
        str(p.get("f171")),
        "",
        "## Pareto vs v0.88 80-state sample",
        "",
        f"pareto={p.get('n_pareto')} captured={p.get('pareto_captured')} missed={p.get('pareto_missed')}",
        f"best_f_sampled={p.get('best_f_sampled')} f171_mobility_sampled={p.get('f171_mobility_sampled')}",
        f"sample_n={p.get('sample_n')}",
        "",
        "## Selected rollout roots",
        "",
        str(p.get("selected")),
        "",
        f"closed={p.get('n_closed')} reopened_lower_g={p.get('n_reopen')}",
        "",
        "## Stage A / Stage B",
        "",
        str(p.get("quality_table")),
        "",
        f"stage_a_n={p.get('stage_a_n')} stage_b_n={p.get('stage_b_n')}",
        f"superior_prep={p.get('superior_prep')} reason={p.get('superior_reason')}",
        "",
        "## Continuation",
        "",
        f"portfolio={p.get('n_portfolio')} stop=`{p.get('stop_reason')}` unique={p.get('unique')} expanded={p.get('expanded')} maxF={p.get('max_foundations')} wall={_fmt(p.get('wall_s'))}",
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
    mode = archive_mode()
    print(f"ARCHIVE mode={mode}", flush=True)
    print("VERIFY 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "EXHAUSTIVE_PREP_CONTRACT_FAILURE", "contract_reason": "incumbent 187 failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT EXHAUSTIVE_PREP_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    a = reconstruct_root_a(opening)
    b = reconstruct_root_b(opening)
    print(f"A ok={a.get('ok')} g={a.get('g')} B ok={b.get('ok')} g={b.get('g')}", flush=True)
    if not a.get("ok") or not b.get("ok"):
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "EXHAUSTIVE_PREP_CONTRACT_FAILURE", "contract_reason": "root reconstruct failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT EXHAUSTIVE_PREP_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    cache = ExactHCache()
    ctrl_a = immediate_deal_control(a, cache=cache)
    ctrl_b = immediate_deal_control(b, cache=cache)
    print(f"CTRL A {ctrl_a.get('post_g')}/{ctrl_a.get('assembly_h')}/{ctrl_a.get('assembly_f')}", flush=True)
    print(f"CTRL B {ctrl_b.get('post_g')}/{ctrl_b.get('assembly_h')}/{ctrl_b.get('assembly_f')}", flush=True)
    _write_json(PROG, {"phase": "harvest", "mode": mode})

    print("HARVEST A compact", flush=True)
    ha = harvest_preparation(opening, a, time_s=PREP_S, unique=PREP_UNIQUE, materialize_paths=False)
    print(f"  n={ha.get('n_archive')} unique={ha.get('unique')} stop={ha.get('stop_reason')}", flush=True)
    print("HARVEST B compact", flush=True)
    hb = harvest_preparation(opening, b, time_s=PREP_S, unique=PREP_UNIQUE, materialize_paths=False)
    print(f"  n={hb.get('n_archive')} unique={hb.get('unique')} stop={hb.get('stop_reason')}", flush=True)
    n_a, n_b = int(ha.get("n_archive") or 0), int(hb.get("n_archive") or 0)
    n_pre = n_a + n_b
    print(f"ARCHIVE total={n_pre} expected={EXPECTED_TOTAL}", flush=True)
    _write_json(PROG, {"phase": "eval", "n_pre": n_pre})

    print("EVAL ALL post-Deal", flush=True)
    ev = exhaustive_post_deal(ha["candidates"] + hb["candidates"], cache=cache)
    posts = ev["posts"]
    print(
        f"  eval={ev['n_eval']} unique={ev['n_unique_post']} viable={ev['n_viable']} dead={ev['n_dead']} "
        f"deal_s={ev['t_deal_s']:.1f} h_s={ev['t_h_s']:.1f}",
        flush=True,
    )
    buckets = bucket_counts(posts)
    buckets_src = bucket_counts_grouped(posts, "source")
    buckets_band = bucket_counts_grouped(posts, "prep_band")
    min_f = None if not posts else min(int(r["assembly_f"]) for r in posts)
    any_low = min_f is not None and int(min_f) < 171
    f171 = analyze_f171(posts)
    pareto = exhaustive_pareto(posts)
    sample = v088_sample_digests()
    cov = compare_sample_coverage(pareto, posts, sample, min_f)
    winners = {k: slim_post(v) for k, v in best_post_states(posts).items()}
    f171_rows = [slim_post(r) for r in posts if int(r["assembly_f"]) == 171]
    f172_n = sum(1 for r in posts if int(r["assembly_f"]) == 172)
    print(
        f"  min_f={min_f} any<171={any_low} f171={f171.get('n')} pareto={len(pareto)} "
        f"captured={cov['pareto_captured']}",
        flush=True,
    )
    rel = abs(n_pre - EXPECTED_TOTAL) / float(EXPECTED_TOTAL)
    archive_totals_ok = rel <= 0.05
    archive_contract_fail = rel > 0.10
    if not archive_totals_ok:
        print(f"  archive totals differ by {rel:.3%} from v0.88", flush=True)

    selected = select_exhaustive_rollout(posts, [ctrl_a, ctrl_b], k=ROLLOUT_N)
    harvests = {"NEW_G128_F2": ha, "INCUMBENT_G129_F2": hb}
    closed = load_prep_closed_table()
    live = []
    n_closed = 0
    n_reopen = 0
    for rec in selected:
        ident = rec.get("ident")
        if ident and is_known_closed(ident, int(rec["post_g"]), closed):
            n_closed += 1
            rec["closed"] = True
            continue
        if ident and ident in closed:
            n_reopen += 1
            rec["reopened"] = True
        live.append(attach_full_actions(rec, harvests))
    print(f"ROLLOUT live={len(live)} closed={n_closed} reopen={n_reopen}", flush=True)
    _write_json(PROG, {"phase": "rollout", "n_live": len(live)})

    stage_a = []
    descendants = []
    for post in live:
        remain = TOTAL_S - (time.perf_counter() - wall0)
        if remain < STAGE_A_S:
            print("STAGE A stop remaining", flush=True)
            break
        print(f"A src={post.get('source')} dg={post.get('prep_delta_g')} f={post.get('assembly_f')} legal={post.get('legal')}", flush=True)
        rp = as_rollout_post(post)
        rp["tag"] = post.get("selection_role")
        sig = run_rollout(opening, rp, time_s=STAGE_A_S, unique=50_000)
        sig["source"] = post.get("source")
        sig["prep_delta_g"] = post.get("prep_delta_g")
        sig["selection_role"] = post.get("selection_role")
        stage_a.append(sig)
        descendants.extend(d for d in (sig.get("descendants") or []) if d.get("full_actions"))
        print(f"  maxF={sig.get('max_F')} min_f={sig.get('min_f')}", flush=True)

    ranked = sorted(stage_a, key=lambda s: tuple(s.get("rollout_key") or rollout_key(s)))
    promote = ranked[:STAGE_B_N]
    remain = TOTAL_S - (time.perf_counter() - wall0)
    b_budget = min(STAGE_B_N * STAGE_B_S, max(0.0, remain - 5.0))
    per_b = min(STAGE_B_S, b_budget / float(len(promote))) if promote and b_budget >= 1 else 0.0
    post_by = {p.get("post_digest"): p for p in live}
    stage_b = []
    print(f"STAGE B n={len(promote)} per={per_b:.1f}", flush=True)
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
        descendants.extend(d for d in (sig_b.get("descendants") or []) if d.get("full_actions"))
        print(f"  B maxF={sig_b.get('max_F')} min_f={sig_b.get('min_f')}", flush=True)

    all_sigs = stage_b + [s for s in ranked if s.get("post_digest") not in {x.get("post_digest") for x in stage_b}]
    ctrl_a_sigs = [
        s for s in all_sigs
        if s.get("source") == "NEW_G128_F2" and int(s.get("prep_delta_g") or 0) == 0
    ]
    ctrl_sigs = [s for s in all_sigs if int(s.get("prep_delta_g") or 0) == 0]
    prep_sigs = [s for s in all_sigs if int(s.get("prep_delta_g") or 0) > 0]
    ctrl_cmp = ctrl_a_sigs or ctrl_sigs
    ctrl_key = tuple(ctrl_cmp[0].get("rollout_key") or (99,)) if ctrl_cmp else None
    superior = False
    superior_reason = None
    superior_f = None
    for s in prep_sigs:
        if ctrl_key is not None and tuple(s.get("rollout_key") or (99,)) < ctrl_key:
            superior = True
            superior_reason = (
                f"prep ranked above Root A immediate Deal maxF={s.get('max_F')} "
                f"min_f={s.get('min_f')} role={s.get('selection_role')}"
            )
            post = post_by.get(s.get("post_digest")) or {}
            superior_f = post.get("assembly_f")
            break

    for p_root in live:
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
    portfolio = select_continuation_portfolio(descendants, closed, hard_max=PORTFOLIO_MAX)
    promising = any_low or superior
    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if portfolio and remain >= 5.0:
        t_cont = remain if promising else min(remain, 90.0)
        print(f"CONTINUE n={len(portfolio)} t={t_cont:.1f}s promising={promising}", flush=True)
        cont = search_f4_portfolio(opening, portfolio, time_s=t_cont, unique=SEARCH_UNIQUE)
        print(f"CONTINUE stop={cont.stop_reason} unique={cont.unique} maxF={cont.max_foundations}", flush=True)
    else:
        print(f"NO/modest continuation remain={remain:.1f}", flush=True)

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)
    max_f = 2
    for sig in all_sigs:
        max_f = max(max_f, int(sig.get("max_F") or 0))
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))

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
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.89 exhaustive prep")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(META, {"g": int(cont.solution_g), "replay_ok": True, "canonical_input": False, "parent_incumbent": 187})
            improved = True

    quality = []
    by_d = {s.get("post_digest"): s for s in all_sigs}
    for post in live:
        sig = by_d.get(post.get("post_digest"))
        quality.append({
            "source": post.get("source"),
            "role": post.get("selection_role"),
            "prep_delta_g": post.get("prep_delta_g"),
            "post_g": post.get("post_g"),
            "h": post.get("assembly_h"),
            "f": post.get("assembly_f"),
            "legal": post.get("legal"),
            "maxF": None if sig is None else sig.get("max_F"),
            "min_f": None if sig is None else sig.get("min_f"),
        })

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "archive_mode": mode,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "n_a": n_a,
        "n_b": n_b,
        "n_pre": n_pre,
        "n_predeal_f3": int(ha.get("n_predeal_f3") or 0) + int(hb.get("n_predeal_f3") or 0),
        "expected_a": EXPECTED_A,
        "expected_b": EXPECTED_B,
        "expected_total": EXPECTED_TOTAL,
        "n_eval": ev["n_eval"],
        "n_illegal": ev["n_illegal"],
        "n_unique_post": ev["n_unique_post"],
        "n_viable": ev["n_viable"],
        "n_dead": ev["n_dead"],
        "t_deal_s": ev["t_deal_s"],
        "t_h_s": ev["t_h_s"],
        "t_dedup_s": ev["t_dedup_s"],
        "eval_elapsed_s": ev["elapsed_s"],
        "eval_per_s": ev["eval_per_s"],
        "h_cache": ev["h_cache"],
        "peak_rss_mb": max(
            (x for x in (ev.get("peak_rss_mb"), ha.get("peak_rss_mb"), hb.get("peak_rss_mb"), rss_mb()) if x is not None),
            default=None,
        ),
        "convergence_max": ev["convergence_max"],
        "convergence_mean": ev["convergence_mean"],
        "f_buckets": buckets,
        "f_buckets_by_source": buckets_src,
        "f_buckets_by_band": buckets_band,
        "f_bucket_sum": sum(buckets.values()),
        "min_f": min_f,
        "any_f_lt_171": any_low,
        "f171": f171,
        "f171_n": f171.get("n"),
        "f171_posts": f171_rows,
        "f172_n": f172_n,
        "best_posts": winners,
        "n_pareto": len(pareto),
        "pareto": [slim_post(r) for r in pareto[:40]],
        "pareto_captured": cov["pareto_captured"],
        "pareto_missed": cov["pareto_missed"],
        "best_f_sampled": cov["best_f_sampled"],
        "f171_mobility_sampled": cov["f171_mobility_sampled"],
        "sample_n": cov["sample_n"],
        "selected": [slim_post(r) for r in live],
        "quality_table": quality,
        "stage_a_n": len(stage_a),
        "stage_b_n": len(stage_b),
        "n_closed": n_closed,
        "n_reopen": n_reopen,
        "n_portfolio": len(portfolio),
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "stop_reason": stop_reason,
        "roots_exhausted": bool(interp.get("exhausted")),
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": False,
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "superior_prep": superior,
        "superior_reason": superior_reason,
        "superior_f": superior_f,
        "search_limited_downstream": False,
        "archive_totals_ok": archive_totals_ok,
        "archive_contract_fail": archive_contract_fail,
        "contract_reason": None if not archive_contract_fail else f"archive total {n_pre} vs expected {EXPECTED_TOTAL}",
        "envelope": {
            "time_s": TOTAL_S,
            "prep_s": PREP_S,
            "rollout_n": ROLLOUT_N,
            "rollout_a": STAGE_A_S,
            "rollout_b": STAGE_B_S,
            "stage_b_n": STAGE_B_N,
            "portfolio_max": PORTFOLIO_MAX,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
            "archive_eval": ARCHIVE_EVAL_ALL,
        },
    }
    verdict, reason = choose_exhaustive_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "min_f": min_f, "n_eval": ev["n_eval"], "n_unique_post": ev["n_unique_post"]})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "EXHAUSTIVE_PREP_CONTRACT_FAILURE",
            "contract_reason": f"{type(exc).__name__}: {exc}",
            "archive_mode": "ARCHIVE_REGENERATED",
        }
        try:
            _write_json(RESULT, payload)
            write_report(payload)
        except Exception:
            pass
        print(f"VERDICT EXHAUSTIVE_PREP_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        raise
