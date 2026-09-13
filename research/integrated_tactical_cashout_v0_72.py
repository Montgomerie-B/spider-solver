#!/usr/bin/env python3
"""v0.72: integrate bounded tactical cash-out into rows=1 whole-game search.

Canonical 172 is evaluation only after search. No 192 suffix in policy.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_policy import COMPLETION_LANES
from spider.autonomous_cost import checkpoints_from_trace
from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, load_autonomous_192, verify_autonomous_192
from spider.metrics import parse_moves_file, replay_actions
from spider.research_actions import is_deal
from spider.solution_forensics import load_opening
from spider.tactical_integration import (
    ROWS1_AUGMENT_FRACTION,
    STRATEGIC_LANES,
    TACTICAL_ROOT_LIMIT,
    TACTICAL_TERMINAL_LIMIT,
    choose_integrated_tactical_verdict,
    search_integrated_tactical,
)
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "integrated_tactical_cashout_v0_72"
BASE_SHA = "b6cce48fb58b491ae90135e9ed7931fcd7714856"
BRANCH = "agent/integrated-tactical-cashout-v0-72"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "integrated_tactical_cashout_progress_v0_72.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_72.moves"
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
        k: rec.get(k)
        for k in (
            "g",
            "stock_rows",
            "face_down",
            "foundations",
            "foundation_suits",
            "empty_n",
            "legal_tableau",
            "boundaries_total",
            "best_ready_suit",
            "ready_ranked_suits",
            "from_incumbent_ckpt",
            "portfolio_cat",
            "tactical_target",
            "tactical_delta_g",
            "ordered_digest",
            "post_assembly_h",
            "post_assembly_f",
            "assembly_h",
            "elapsed_s",
        )
    }


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "max_foundations": ep.get("max_foundations"),
        "min_face_down": ep.get("min_face_down"),
        "lane_exp": ep.get("lane_exp"),
        "alloc_s": ep.get("alloc_s"),
        "alloc_s_strategic": ep.get("alloc_s_strategic"),
        "augment": ep.get("augment"),
        "elapsed_s": ep.get("elapsed_s"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "stop_reason": ep.get("stop_reason"),
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "TACTICAL_INTEGRATION_COST_IMPROVED":
        return "Promote the cheaper terminal and analyse the tactical/strategic savings."
    if verdict == "TACTICAL_INTEGRATION_REACHES_PRESD5_F2":
        return (
            "Run a focused continuation from the best integrated tactical F2 "
            "before changing strategy."
        )
    if verdict == "TACTICAL_INTEGRATION_IMPROVES_TRANSITION":
        return "Refine terminal portfolio selection / cost-to-go evaluation, not the tactical planner."
    if verdict == "TACTICAL_INTEGRATION_NO_USEFUL_CASHOUT":
        return "Refine terminal portfolio selection / cost-to-go evaluation, not the tactical planner."
    if verdict == "TACTICAL_INTEGRATION_OVERHEAD_FAILURE":
        return "Optimise the subroutine architecture before any new heuristic."
    if verdict == "TACTICAL_INTEGRATION_NO_GAIN":
        return "Increase tactical efficiency or improve tactical root selection rather than widening whole-game runtime."
    return "Fix the contract before continuing."


def write_report(p: dict) -> None:
    r1 = p.get("rows1") or {}
    tac = p.get("tactical") or {}
    f2 = p.get("best_presd5_f2") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or p.get("interpretation") or "",
        "",
        "## Architecture",
        "",
        "Strategic lanes restored to v0.69/v0.68: COST, REVEAL, CONSTRUCTION, "
        "READINESS, HORIZON, ECONOMY, COMPLETION (stock-empty). "
        "`readiness_r2`/`readiness_r3` are inactive.",
        "",
        "Rows=1 allocation is split 75% strategic / 25% tactical. After ordinary "
        "harvest, a small diverse ready-root set is probed with "
        "`search_foundation_cashout`. Terminals rejoin the pre-Deal set. "
        "Deal-preview and stock-empty assembly are unchanged.",
        "",
        "## Envelope",
        "",
        f"- 900 s / 800,000 unique / 2.5 GiB / width 256 / ceiling 191",
        f"- augment fraction = {p.get('augment_fraction')}",
        f"- tactical roots cap = {TACTICAL_ROOT_LIMIT}",
        f"- terminals per probe cap = {TACTICAL_TERMINAL_LIMIT}",
        "",
        "## Search totals",
        "",
        f"- unique = {p.get('unique')}",
        f"- expanded = {p.get('expanded')}",
        f"- generated = {p.get('generated')}",
        f"- elapsed = {p.get('elapsed_s')}",
        f"- stop = {p.get('stop_reason')}",
        f"- max F = {p.get('max_foundations')}",
        f"- solved = {p.get('solved')} g={p.get('solution_g')}",
        f"- lane expansions = {p.get('lanes', {}).get('expansions')}",
        "",
        "## Rows=1",
        "",
        f"- alloc_s = {r1.get('alloc_s')} (strategic {r1.get('alloc_s_strategic')})",
        f"- expanded = {r1.get('expanded')} unique={r1.get('unique')}",
        f"- max F = {r1.get('max_F')}",
        f"- ready roots in harvest = {(r1.get('augment') or {}).get('n_ready_roots')}",
        f"- selected = {(r1.get('augment') or {}).get('n_selected')}",
        "",
        "## Tactical probes",
        "",
        f"- probes attempted = {tac.get('n_probes')}",
        f"- producing foundation = {tac.get('n_found')}",
        f"- terminals returned = {tac.get('n_terminals')} (raw {tac.get('n_terminals_raw')})",
        f"- unique = {tac.get('unique')} expanded={tac.get('expanded')}",
        f"- elapsed_s = {tac.get('elapsed_s')} of alloc {tac.get('alloc_s')}",
        "",
    ]
    for pr in tac.get("probes") or []:
        lines.append(
            f"- root_g={pr.get('root_g')} target={pr.get('target_suit')} "
            f"found={pr.get('found')} cheapest_g={pr.get('cheapest_g')} "
            f"exp={pr.get('expanded')} t={pr.get('elapsed_s')}"
        )
    ar = p.get("after_run") or {}
    lines.extend(
        [
            "",
            "## Best pre-SD5 F2",
            "",
            f"{f2 or 'none'}",
            "",
            "## After-run comparison",
            "",
            f"- incumbent 192 F2 g = {ar.get('incumbent_f2_g')}",
            f"- v0.71 F2 g = {ar.get('v071_g')}",
            f"- v0.72 best pre-SD5 F2 = {ar.get('v072_best_presd5_f2')}",
            f"- same as v0.71 = {ar.get('same_as_v071')}",
            f"- same as incumbent = {ar.get('same_as_incumbent')}",
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
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("VERIFY autonomous 192", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "incumbent_fail": True,
            "verdict": "TACTICAL_INTEGRATION_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT TACTICAL_INTEGRATION_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    ck1 = dict(ck[1])
    print(
        f"ROWS1 CHECKPOINT g={ck1['g']} fd={ck1.get('face_down')} F={ck1.get('foundations')}",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "phase": "start",
            "lanes": list(STRATEGIC_LANES),
            "fraction": ROWS1_AUGMENT_FRACTION,
            "checkpoint_g": ck1["g"],
        },
    )

    print(
        f"SEARCH integrated tactical ceiling=191 900s fraction={ROWS1_AUGMENT_FRACTION} "
        f"lanes={list(STRATEGIC_LANES)}",
        flush=True,
    )
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_integrated_tactical(opening=opening)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    tracker = getattr(res, "transition_tracker", None)
    r1 = next((ep for ep in res.epochs if ep.get("stock_rows") == 1), {})
    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = []
    for n, rec in sorted(res.foundations_cheap.items()):
        frontier.append(
            {
                "F": n,
                "g": rec.get("g"),
                "rows": rec.get("stock_rows"),
                "fd": rec.get("face_down"),
                "suits": rec.get("foundation_suits"),
                "legal": rec.get("legal_tableau"),
                "cat": rec.get("portfolio_cat"),
                "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )
    cheap_f2 = cheap.get("2") or {}
    best_f2 = None
    if cheap_f2.get("stock_rows") == 1:
        best_f2 = {
            "g": cheap_f2.get("g"),
            "fd": cheap_f2.get("face_down"),
            "F": 2,
            "suits": cheap_f2.get("foundation_suits"),
            "stock_rows": 1,
            "legal": cheap_f2.get("legal_tableau"),
            "from_incumbent_ckpt": cheap_f2.get("from_incumbent_ckpt"),
            "portfolio_cat": cheap_f2.get("portfolio_cat"),
            "tactical_target": cheap_f2.get("tactical_target"),
            "digest": cheap_f2.get("ordered_digest"),
            "tactical_delta_g": cheap_f2.get("tactical_delta_g"),
        }

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < AUTONOMOUS_INCUMBENT_MW
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    if improved:
        save_solution(
            res.solution_actions,
            FIX,
            g=int(res.solution_g),
            label="Autonomous v0.72 integrated tactical cash-out solution",
        )
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

    print("EVAL canonical after search", flush=True)
    canon_g = replay_actions(opening.clone(), parse_moves_file(CANON))
    print("EVAL after-run v0.71 and incumbent suffix", flush=True)
    from spider.foundation_cashout import (
        replay_incumbent_suffix_for_eval,
        replay_to_stock_rows,
        require_eval_phase,
    )
    from spider.research_actions import as_actions as _as

    require_eval_phase("after-run incumbent suffix")
    v067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
    actions_192 = parse_moves_file(v067)
    prefix = replay_to_stock_rows(opening, actions_192, target_rows=1)
    inc_suffix = replay_incumbent_suffix_for_eval(
        opening, actions_192, prefix_n=int(prefix["n_prefix"]), root_g=int(prefix["g"])
    )
    v71_path = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"
    v71 = json.loads(v71_path.read_text(encoding="utf-8")) if v71_path.exists() else {}
    after_run = {
        "incumbent_f2_g": inc_suffix.get("foundation_g"),
        "incumbent_f2_digest": inc_suffix.get("ordered_digest"),
        "incumbent_cashed_suit": inc_suffix.get("cashed_suit"),
        "incumbent_n_actions": inc_suffix.get("n_actions"),
        "incumbent_preview": inc_suffix.get("deal_preview"),
        "v071_g": v71.get("terminal_g"),
        "v071_digest": v71.get("terminal_digest"),
        "v071_delta_g": v71.get("delta_g"),
        "v072_best_presd5_f2": best_f2,
        "same_as_v071": bool(
            best_f2
            and v71.get("terminal_digest")
            and best_f2.get("digest") == v71.get("terminal_digest")
        ),
        "same_as_incumbent": bool(
            best_f2
            and inc_suffix.get("ordered_digest")
            and best_f2.get("digest") == inc_suffix.get("ordered_digest")
        ),
    }
    aug = r1.get("augment") or {}
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "incumbent_verify": {k: inc.get(k) for k in inc if k != "actions"},
        "canonical_eval_g": canon_g,
        "rows1_checkpoint": {
            "g": ck1["g"],
            "fd": ck1.get("face_down"),
            "F": ck1.get("foundations"),
        },
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(STRATEGIC_LANES),
            "completion_lanes": list(COMPLETION_LANES),
        },
        "augment_fraction": ROWS1_AUGMENT_FRACTION,
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "foundations": {"first": first, "cheap": cheap},
        "frontier": frontier,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "rows1": {
            "s": r1.get("elapsed_s"),
            "alloc_s": r1.get("alloc_s"),
            "alloc_s_strategic": r1.get("alloc_s_strategic"),
            "expanded": r1.get("expanded"),
            "generated": r1.get("generated"),
            "unique": r1.get("unique"),
            "max_F": r1.get("max_foundations"),
            "min_fd": r1.get("min_face_down"),
            "lane_exp": r1.get("lane_exp"),
            "portfolio_cats": r1.get("portfolio_cats"),
            "augment": aug,
        },
        "tactical": {
            "n_probes": aug.get("n_probes"),
            "n_selected": aug.get("n_selected"),
            "n_ready_roots": aug.get("n_ready_roots"),
            "n_found": aug.get("found"),
            "n_terminals": aug.get("n_terminals"),
            "n_terminals_raw": aug.get("n_terminals_raw"),
            "unique": aug.get("unique"),
            "expanded": aug.get("expanded"),
            "elapsed_s": aug.get("elapsed_s"),
            "alloc_s": aug.get("alloc_s"),
            "lane_exp": aug.get("lane_exp"),
            "probes": aug.get("probes"),
        },
        "after_run": after_run,
        "lanes": {"expansions": res.lane_exp, "pops": res.lane_pops, "stale": res.lane_stale},
        "tracker": None if tracker is None else tracker.stats(),
        "best_presd5_f2": best_f2,
        "preview_perf": preview_cache_stats(),
        "bound_perf": {
            "prunes": res.lower_bound_prunes,
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "reconcile": reconcile_lower_bound_telemetry(res),
        },
        "checkpoint": {"injected": res.incumbent_injected, "survived": res.incumbent_survived},
        "r2_r3_active": False,
        "readiness_r2_exp": int(res.lane_exp.get("readiness_r2") or 0),
        "readiness_r3_exp": int(res.lane_exp.get("readiness_r3") or 0),
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, reason = choose_integrated_tactical_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "rows1": payload.get("rows1"),
            "tactical": payload.get("tactical"),
            "best_presd5_f2": best_f2,
            "solution_g": payload.get("solution_g"),
            "max_foundations": payload.get("max_foundations"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
