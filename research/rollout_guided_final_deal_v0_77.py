#!/usr/bin/env python3
"""v0.77: rollout-guided final-Deal selection with frontier reuse.

Canonical 172 is evaluation only after machine search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.final_deal_rollout import (
    apply_sd5,
    choose_guided_verdict,
    pre_sd5_from_actions,
    run_rollout,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import V073_F2_DIGEST
from spider.tactical_integration import search_rollout_guided
from spider.whole_game_epoch_scheduler import (
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "rollout_guided_final_deal_v0_77"
BASE_SHA = "107263cbb2a849a4f5d56f6432067050985396ac"
BRANCH = "agent/rollout-guided-final-deal-v0-77"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "rollout_guided_final_deal_progress_v0_77.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_77.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_77.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


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


def slim_f(rec: dict) -> dict:
    if not rec:
        return {}
    return {
        "g": rec.get("g"),
        "stock_rows": rec.get("stock_rows"),
        "face_down": rec.get("face_down"),
        "foundations": rec.get("foundations"),
        "empty_n": rec.get("empty_n"),
        "legal_tableau": rec.get("legal_tableau"),
        "assembly_h": rec.get("assembly_h"),
        "assembly_f": rec.get("assembly_f"),
        "elapsed_s": rec.get("elapsed_s"),
        "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
        "portfolio_cat": rec.get("portfolio_cat"),
        "tactical_target": rec.get("tactical_target"),
        "lineage": rec.get("lineage"),
    }


def epoch_split(epochs: list) -> dict:
    out = {}
    for ep in epochs or []:
        rows = ep.get("stock_rows")
        out[str(rows)] = {
            "alloc_s": ep.get("alloc_s"),
            "elapsed_s": ep.get("elapsed_s"),
            "expanded": ep.get("expanded"),
            "unique": ep.get("unique"),
            "generated": ep.get("generated"),
            "max_foundations": ep.get("max_foundations"),
            "input_roots": ep.get("input_roots"),
            "augment": {
                "elapsed_s": (ep.get("augment") or {}).get("elapsed_s"),
                "n_probes": (ep.get("augment") or {}).get("n_probes"),
                "found": (ep.get("augment") or {}).get("found"),
                "control_slot_used": (ep.get("augment") or {}).get("control_slot_used"),
            },
        }
    return out


def _fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def write_report(p: dict) -> None:
    """Compact research markdown. Action lists belong in JSON only if retained."""

    r = p.get("rollout") or {}
    split = p.get("time_split") or {}
    rows0 = p.get("rows0") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Whole-game search from the untouched opening, incumbent 187, ceiling 186.",
        "Bounded final-Deal rollouts select and reuse stock-empty descendants.",
        "Canonical 172 was evaluation-only after freeze.",
        "",
        "## Envelope",
        "",
        f"* wall { _fmt(p.get('elapsed_s')) } s / unique {p.get('unique')} / expanded {p.get('expanded')} / generated {p.get('generated')}",
        f"* ceiling { (p.get('envelope') or {}).get('ceiling') } / unique cap {(p.get('envelope') or {}).get('unique')}",
        f"* stop `{p.get('stop_reason')}` / max F {p.get('max_foundations')} / solution_g {p.get('solution_g')}",
        "",
        "## Wall-time split",
        "",
        "| phase | elapsed s | expanded | unique | max F | roots |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {"5": "rows=5", "4": "rows=4", "3": "rows=3", "2": "rows=2", "1": "rows=1 strategic", "0": "rows=0 main"}
    for k in ("5", "4", "3", "2", "1", "0"):
        ep = split.get(k) or {}
        lines.append(
            f"| {labels[k]} | {_fmt(ep.get('elapsed_s'))} | {ep.get('expanded')} | {ep.get('unique')} | {ep.get('max_foundations')} | {ep.get('input_roots')} |"
        )
    tac = ((split.get("1") or {}).get("augment") or {})
    lines += [
        f"| rows=1 tactical | {_fmt(tac.get('elapsed_s'))} | — | — | found {tac.get('found')} | probes {tac.get('n_probes')} |",
        f"| Stage A | {_fmt(r.get('stage_a_s'))} | — | — | — | {r.get('n_selected')} |",
        f"| Stage B | {_fmt(r.get('stage_b_s'))} | — | — | — | {len(r.get('stage_b') or [])} |",
        f"| rollout total | {_fmt(r.get('elapsed_s'))} | — | — | — | budget {r.get('budget_s')} |",
        "",
        "## Candidate prefilter",
        "",
        f"Harvest rows=1 pool: **{r.get('prefilter_n')}**. Selected **{r.get('n_selected')}** (cap 8).",
        "Not the eight cheapest g. Diversity slots + incumbent/tactical if present.",
        "",
        "| role | pre g | post g | F | fd | legal | h | f | tactical | ckpt |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for s in r.get("selected") or []:
        lines.append(
            f"| {s.get('role')} | {s.get('pre_g')} | {s.get('post_g')} | {s.get('F')} | {s.get('fd')} | {s.get('legal')} | {s.get('h')} | {s.get('f')} | {s.get('tactical_target') or '—'} | {s.get('from_incumbent_ckpt')} |"
        )
    lines += [
        "",
        "## Stage A (10 s / root)",
        "",
        f"Ranking: {', '.join(r.get('ranking_a') or [])}",
        "",
        "| rank | role | max F | g/f at max F | first ΔF | min h | mobility | descendants | unique |",
        "| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for i, s in enumerate(r.get("stage_a") or [], 1):
        mf = s.get("max_F")
        cheap = ((s.get("cheap_F") or {}).get(str(mf)) or {})
        dF = "—" if s.get("time_first_increase") is None else f"{s.get('time_first_increase'):.1f}s / g={s.get('g_first_increase')}"
        lines.append(
            f"| {i} | {s.get('role')} | {mf} | {cheap.get('g')} / {cheap.get('f')} | {dF} | {s.get('min_h')} | {s.get('best_mobility')} | {s.get('n_descendants')} | {s.get('unique')} |"
        )
    lines += [
        "",
        "## Stage B (top 4, +10 s)",
        "",
        f"Promoted: {', '.join(r.get('ranking_b') or [])}",
        "",
        "| rank | role | max F | g/f at max F | first ΔF | min h | mobility | descendants | unique |",
        "| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for i, s in enumerate(r.get("stage_b") or [], 1):
        mf = s.get("max_F")
        cheap = ((s.get("cheap_F") or {}).get(str(mf)) or {})
        dF = "—" if s.get("time_first_increase") is None else f"{s.get('time_first_increase'):.2f}s / g={s.get('g_first_increase')}"
        lines.append(
            f"| {i} | {s.get('role')} | {mf} | {cheap.get('g')} / {cheap.get('f')} | {dF} | {s.get('min_h')} | {s.get('best_mobility')} | {s.get('n_descendants')} | {s.get('unique')} |"
        )
    rf = r.get("root_F") or rows0.get("root_F") or []
    lines += [
        "",
        "## Rows=0 portfolio",
        "",
        f"* n_roots0 **{r.get('n_roots0')}** (target 32, hard max 64); scheduler input_roots **{(split.get('0') or {}).get('input_roots')}**",
        f"* root F: {rf}",
        f"* elapsed {_fmt((split.get('0') or {}).get('elapsed_s') or rows0.get('elapsed_s'))} s / expanded {(split.get('0') or {}).get('expanded') or rows0.get('expanded')} / unique {(split.get('0') or {}).get('unique') or rows0.get('unique')} / max F {(split.get('0') or {}).get('max_foundations') or rows0.get('max_foundations')}",
        "",
        "## F frontier",
        "",
        "| F | g | rows | fd | h/f | legal | lineage | t s |",
        "| ---: | ---: | ---: | ---: | --- | ---: | --- | ---: |",
    ]
    for rec in p.get("frontier") or []:
        lines.append(
            f"| {rec.get('F')} | {rec.get('g')} | {rec.get('stock_rows')} | {rec.get('face_down')} | {rec.get('assembly_h')}/{rec.get('assembly_f')} | {rec.get('legal_tableau')} | {','.join(rec.get('lineage') or []) or ('incumbent' if rec.get('from_incumbent_ckpt') else 'search')} | {_fmt(rec.get('elapsed_s'))} |"
        )
    ct = p.get("continuation") or {}
    bp = p.get("bound_perf") or {}
    can = p.get("canonical") or {}
    ca = can.get("stage_a_like") or {}
    lines += [
        "",
        "## Continuation table / assembly bound",
        "",
        f"* lookups {ct.get('lookups')} / hits {ct.get('hits')} / cheaper-prefix {ct.get('cheaper_prefix_hits')} / splices {ct.get('splices_ok')}",
        f"* proof-prunes {bp.get('prunes')} / calls {bp.get('calls')} / { _fmt(bp.get('seconds'), 3) } s",
        "",
        "## Canonical calibration (after freeze)",
        "",
        f"post g={can.get('post_g')} h={can.get('h')} f={can.get('f')} legal={can.get('legal')}. "
        f"Stage-A-like 10 s: max F={ca.get('max_F')} first ΔF {_fmt(ca.get('time_first_increase'))} s. Would dominate machine Stage A.",
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
    if verdict == "ROLLOUT_GUIDED_COST_IMPROVED":
        return "Promote the new incumbent and compare against 187/172."
    if verdict == "ROLLOUT_GUIDED_REACHES_DEEP_ENDGAME":
        return "Focus next on the best rollout-derived root/continuation rather than adding another pre-Deal heuristic."
    if verdict == "ROLLOUT_GUIDED_SELECTS_STRONG_ROOT_NO_CONVERSION":
        return "Increase search concentration / reuse efficiency, not total wall time."
    if verdict == "ROLLOUT_GUIDED_SIGNAL_LOST_INTEGRATION":
        return "Analyse candidate-generation mismatch between the v0.76 corpus and autonomous harvest."
    if verdict == "ROLLOUT_GUIDED_OVERHEAD_FAILURE":
        return "Optimise progressive rollout scheduling."
    return "Do not promote; diagnose the contract discrepancy."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {
            "experiment": EXPERIMENT,
            "incumbent_fail": True,
            "verdict": "ROLLOUT_GUIDED_CONTRACT_FAILURE",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT ROLLOUT_GUIDED_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("SEARCH rollout-guided whole-game ceiling=186 900s", flush=True)
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_rollout_guided(opening=opening)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    guided = getattr(res, "rollout_guided", None) or {}
    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    frontier = [slim_f(v) | {"F": n} for n, v in sorted(res.foundations_cheap.items())]
    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < 187
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    if improved:
        save_solution(
            res.solution_actions,
            FIX,
            g=int(res.solution_g),
            label="Autonomous v0.77 rollout-guided solution",
        )
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
        )
        _write_json(
            META,
            {
                "g": int(res.solution_g),
                "replay_g": replay_g,
                "replay_ok": replay_ok,
                "canonical_input": False,
                "incumbent_parent": 187,
                "rollout_guided": True,
            },
        )

    rows0_ep = next((ep for ep in res.epochs if int(ep.get("stock_rows") or -1) == 0), {})
    rows1_ep = next((ep for ep in res.epochs if int(ep.get("stock_rows") or -1) == 1), {})
    tac_root = None
    ctrl_root = None
    for s in (guided.get("selected") or []) + (guided.get("stage_a") or []):
        if s.get("role") == "tactical_cashout" or s.get("tactical_target"):
            tac_root = s
        if s.get("from_incumbent_ckpt") or s.get("role") == "incumbent":
            ctrl_root = s
    ct = getattr(res, "continuation_stats", None) or {}
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
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
        "foundations": {"cheap": cheap},
        "frontier": frontier,
        "lanes": {"expansions": res.lane_exp},
        "rollout": guided,
        "time_split": epoch_split(res.epochs),
        "rows0": {
            "input_roots": rows0_ep.get("input_roots"),
            "elapsed_s": rows0_ep.get("elapsed_s"),
            "expanded": rows0_ep.get("expanded"),
            "unique": rows0_ep.get("unique"),
            "generated": rows0_ep.get("generated"),
            "max_foundations": rows0_ep.get("max_foundations"),
            "n_roots": guided.get("n_roots0"),
            "root_F": guided.get("root_F"),
        },
        "tactical_root": tac_root,
        "incumbent_root": ctrl_root,
        "continuation": {
            "lookups": ct.get("lookups"),
            "hits": ct.get("hits"),
            "cheaper_prefix_hits": ct.get("cheaper_prefix_hits"),
            "splices_ok": ct.get("splices_ok"),
        },
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
        "preview_cache": preview_cache_stats(),
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "ceiling": CANDIDATE_CEILING,
        },
        "f2_incumbent_digest": V073_F2_DIGEST,
    }
    if improved:
        payload["improved_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
    verdict, reason = choose_guided_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    _write_json(RESULT, _jsonable({k: v for k, v in payload.items() if k != "canonical"}))
    _write_json(PROG, {"phase": "machine_frozen", "verdict": verdict, "max_foundations": payload.get("max_foundations")})
    write_report(_jsonable(payload))
    print("machine experiment frozen", flush=True)

    print("EVAL canonical after search", flush=True)
    canon_pre = pre_sd5_from_actions(opening, parse_moves_file(CANON))
    canon_pre["tag"] = "canonical"
    canon_post = apply_sd5(opening, canon_pre)
    canon_post["role"] = "canonical"
    canon_sig = run_rollout(opening, canon_post, time_s=10.0, unique=15000)
    payload["canonical"] = {
        "post_g": canon_post.get("post_g"),
        "h": canon_post.get("assembly_h"),
        "f": canon_post.get("assembly_f"),
        "legal": canon_post.get("legal"),
        "stage_a_like": {
            "max_F": canon_sig.get("max_F"),
            "min_f": canon_sig.get("min_f"),
            "cheap_F": canon_sig.get("cheap_F"),
            "time_first_increase": canon_sig.get("time_first_increase"),
            "rollout_key": canon_sig.get("rollout_key"),
        },
    }
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "solution_g": payload.get("solution_g"),
            "max_foundations": payload.get("max_foundations"),
            "n_roots0": guided.get("n_roots0"),
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
