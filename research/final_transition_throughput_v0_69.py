#!/usr/bin/env python3
"""v0.69: recover rows=1 throughput by incremental transition Pareto.

Canonical 172 is evaluation only after search. Strategic policy is frozen v0.68.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import assembly_bound_detail
from spider.assembly_policy import COMPLETION_LANES, assembly_lane_keys, enrich_assembly
from spider.autonomous_cost import checkpoints_from_trace
from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.final_deal_transition import (
    TRANSITION_HARVEST_CATS,
    TransitionTracker,
    TransitionTrackerLegacy,
    pareto_preview,
    transition_share,
)
from spider.healthy_f2 import parse_stored_actions
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    enrich_integrated,
    load_autonomous_192,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_LANES, search_operational_optimisation
from spider.packed_state import unpack_state
from spider.research_actions import is_deal
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    _Top,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "final_transition_throughput_v0_69"
BASE_SHA = "beafe2fe1acbce40f35c683f2e4b43ee97de42e8"
BRANCH = "agent/final-transition-throughput-v0-69"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "final_transition_throughput_progress_v0_69.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_69.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_69.json"
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
            "cover",
            "assembly_h",
            "assembly_f",
            "from_incumbent_ckpt",
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
        "n_ready": ep.get("n_ready"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "alloc_s": ep.get("alloc_s"),
        "elapsed_s": ep.get("elapsed_s"),
        "lower_bound_prunes": ep.get("lower_bound_prunes"),
        "lower_bound_calls": ep.get("lower_bound_calls"),
        "stop_reason": ep.get("stop_reason"),
        "deal_now_kept": ep.get("deal_now_kept"),
        "after_deal_unique": ep.get("after_deal_unique"),
    }


def choose_throughput_verdict(p: dict) -> tuple:
    if p.get("incumbent_fail") or p.get("accounting_fail") or p.get("pareto_unequal"):
        return "TRANSITION_THROUGHPUT_CONTRACT_FAILURE", "replay, Pareto or accounting failed"
    inc = int(p.get("incumbent_g") or 192)
    best = p.get("solution_g")
    if p.get("solved") and p.get("replay_ok") and best is not None and int(best) < inc:
        return "TRANSITION_THROUGHPUT_COST_IMPROVED", f"solved at g={best}"
    r1 = p.get("rows1") or {}
    exp = int(r1.get("expanded") or 0)
    recovered = exp >= 500
    f2 = p.get("best_presd5_f2") or {}
    healthy = (
        f2.get("g") is not None
        and int(f2.get("stock_rows") or -1) == 1
        and int(f2.get("g") or 999) <= 140
        and int(f2.get("face_down") or 99) <= 4
    )
    if recovered and healthy:
        return (
            "TRANSITION_THROUGHPUT_REDISCOVERS_F2",
            "rows=1 throughput restored and a pre-SD5 F2-class lineage appeared",
        )
    if recovered:
        return (
            "TRANSITION_THROUGHPUT_RECOVERED_NO_F2",
            "rows=1 expansions recovered but no healthy pre-SD5 F2",
        )
    return (
        "TRANSITION_THROUGHPUT_NOT_RECOVERED",
        "rows=1 remains computationally starved",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "TRANSITION_THROUGHPUT_COST_IMPROVED":
        return "Promote the new incumbent and analyse the savings versus 192."
    if verdict == "TRANSITION_THROUGHPUT_REDISCOVERS_F2":
        return (
            "Analyse why the integrated endgame diverges from the v0.67 focused continuation. "
            "Do not widen runtime."
        )
    if verdict == "TRANSITION_THROUGHPUT_RECOVERED_NO_F2":
        return "Next experiment should target rows=1 transition ordering/lineage quality, not more bookkeeping."
    if verdict == "TRANSITION_THROUGHPUT_NOT_RECOVERED":
        return "Continue engineering optimisation before any new heuristic."
    return "Do not widen runtime. Do not copy the canonical route."


def _short_search(opening, ckpt, tracker, finalize, time_s, max_unique):
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_operational_optimisation(
        opening=opening,
        initial_roots=[dict(ckpt)],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=max_unique,
        time_limit_s=time_s,
        rss_abort_mb=SEARCH_RSS_MB,
        portfolio_width=PORTFOLIO_WIDTH,
        harvest_cats=TRANSITION_HARVEST_CATS,
        extra_track=tracker,
        enrich_fn=enrich_integrated,
        on_harvest=tracker.on_harvest,
        finalize_track=finalize,
        lane_names=COMPLETION_LANES,
        keys_fn=assembly_lane_keys,
        lower_bound_fn=None,
    )
    wall = time.perf_counter() - t0
    r1 = next((ep for ep in res.epochs if ep.get("stock_rows") == 1), res.epochs[0] if res.epochs else {})
    return {
        "wall_s": wall,
        "elapsed_s": res.elapsed_s,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "exp_per_s": 0.0 if wall <= 0 else res.expanded / wall,
        "epoch": slim_epoch(r1) if r1 else {},
        "preview": preview_cache_stats(),
        "tracker": tracker.stats() if hasattr(tracker, "stats") else {
            "n_previewed": tracker.n_previewed,
            "pareto_calls": getattr(tracker, "pareto_calls", None),
            "pareto_s": getattr(tracker, "pareto_s", None),
            "cat_s": getattr(tracker, "cat_s", None),
            "n_pool_truncations": getattr(tracker, "n_pool_truncations", None),
        },
    }


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## Rows=1 bottleneck",
        "",
        json.dumps(p.get("microbench") or {}, indent=2, sort_keys=True)[:8000],
        "",
        "## Whole-game rows=1 vs v0.68",
        "",
        json.dumps(p.get("rows1") or {}, indent=2, sort_keys=True),
        "",
        "## F1-F8",
        "",
        json.dumps(p.get("frontier") or [], indent=2, sort_keys=True)[:8000],
        "",
        "## Best pre-SD5 F2",
        "",
        json.dumps(p.get("best_presd5_f2") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
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
            "verdict": "TRANSITION_THROUGHPUT_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT TRANSITION_THROUGHPUT_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload
    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    ck1 = dict(ck[1])
    print(
        f"ROWS1 CHECKPOINT g={ck1['g']} fd={ck1.get('face_down')} F={ck1.get('foundations')} "
        f"ident={str(ck1.get('ident'))[:16]}",
        flush=True,
    )

    print("MICROBENCH old vs new bookkeeping on rows=1 checkpoint 8s", flush=True)
    old_tr = TransitionTrackerLegacy()
    new_tr = TransitionTracker()
    old_b = _short_search(opening, ck1, old_tr, None, 8.0, 50_000)
    new_b = _short_search(opening, ck1, new_tr, new_tr.finalize, 8.0, 50_000)
    print(
        f"OLD exp={old_b['expanded']} exp/s={old_b['exp_per_s']:.2f} pareto_s={old_tr.pareto_s:.2f} "
        f"calls={old_tr.pareto_calls}",
        flush=True,
    )
    print(
        f"NEW exp={new_b['expanded']} exp/s={new_b['exp_per_s']:.2f} pareto_s={new_tr.pareto_s:.2f} "
        f"front={len(new_tr.front.members())}",
        flush=True,
    )
    exact = {r.get("ident") for r in pareto_preview(new_tr.pool)}
    pareto_ok = exact == new_tr.front.ident_set()
    print(f"PARETO incremental==full {pareto_ok} n={len(exact)}", flush=True)

    _write_json(
        PROG,
        {
            "phase": "preflight_ok",
            "checkpoint_rows1": {
                "g": ck1["g"],
                "fd": ck1.get("face_down"),
                "F": ck1.get("foundations"),
            },
            "microbench_old": old_b,
            "microbench_new": new_b,
        },
    )

    print("SEARCH whole-game from opening ceiling=191 900s", flush=True)
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_integrated_optimisation(opening=opening)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    tracker = getattr(res, "transition_tracker", None)
    lb_rec = reconcile_lower_bound_telemetry(res)
    preview_stats = preview_cache_stats()
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
                "boundaries": rec.get("boundaries_total"),
                "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"),
                "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )
    f2s = list(getattr(tracker, "f2_rows1", None) or [])
    best_f2 = None
    if f2s:
        best_f2 = min(f2s, key=lambda r: (int(r.get("g") or 999), int(r.get("fd") or 99)))
    cheap_f2 = cheap.get("2") or {}
    if cheap_f2.get("stock_rows") == 1 and (
        best_f2 is None or int(cheap_f2.get("g") or 999) < int(best_f2.get("g") or 999)
    ):
        best_f2 = {
            "g": cheap_f2.get("g"),
            "fd": cheap_f2.get("face_down"),
            "F": 2,
            "suits": cheap_f2.get("foundation_suits"),
            "stock_rows": 1,
            "legal": cheap_f2.get("legal_tableau"),
            "boundaries": cheap_f2.get("boundaries_total"),
            "from_incumbent_ckpt": cheap_f2.get("from_incumbent_ckpt"),
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
            label="Autonomous v0.69 final-transition throughput solution",
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
        _write_json(
            META,
            {
                "g": res.solution_g,
                "replay_g": replay_g,
                "replay_ok": replay_ok,
                "parent_incumbent": AUTONOMOUS_INCUMBENT_MW,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
            },
        )

    print("EVAL canonical after search", flush=True)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "incumbent_verify": {k: inc.get(k) for k in inc if k != "actions"},
        "rows1_checkpoint": {
            "g": ck1["g"],
            "fd": ck1.get("face_down"),
            "F": ck1.get("foundations"),
            "ident": ck1.get("ident"),
            "note": "epoch-entry after SD4, not the internal g=130 F2",
        },
        "microbench": {
            "old": old_b,
            "new": new_b,
            "pareto_incremental_equals_full": pareto_ok,
            "legacy_pool_truncation": (
                "v0.68 truncated the seen pool at 240 via a 120-slice Pareto; "
                "v0.69 keeps the exact nondominated set of all previewed records."
            ),
        },
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(COMPLETION_LANES),
            "base_lanes": list(OP_LANES),
            "harvest_cats": list(TRANSITION_HARVEST_CATS),
        },
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
            "v068_s": 128.9,
            "v068_expanded": 86,
            "v068_generated": 762,
            "v068_unique": 875,
            "v068_max_F": 1,
            "s": r1.get("elapsed_s"),
            "alloc_s": r1.get("alloc_s"),
            "expanded": r1.get("expanded"),
            "generated": r1.get("generated"),
            "unique": r1.get("unique"),
            "input_roots": r1.get("input_roots"),
            "max_F": r1.get("max_foundations"),
            "min_fd": r1.get("min_face_down"),
            "exp_per_s": None
            if not r1.get("elapsed_s")
            else float(r1.get("expanded") or 0) / float(r1["elapsed_s"]),
            "portfolio_cats": r1.get("portfolio_cats"),
        },
        "tracker": None if tracker is None else tracker.stats(),
        "lineage": {
            "n_ckpt_desc": None if tracker is None else tracker.n_ckpt_desc,
            "n_f2_rows1": None if tracker is None else len(tracker.f2_rows1),
            "n_ckpt_f2_rows1": None if tracker is None else len(tracker.ckpt_f2_rows1),
            "best_ckpt_f2": None
            if tracker is None or not tracker.ckpt_f2_rows1
            else min(tracker.ckpt_f2_rows1, key=lambda r: (r.get("g") or 999, r.get("fd") or 99)),
        },
        "best_presd5_f2": best_f2,
        "preview_perf": preview_stats,
        "bound_perf": {
            "prunes": res.lower_bound_prunes,
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "reconcile": lb_rec,
        },
        "checkpoint": {"injected": res.incumbent_injected, "survived": res.incumbent_survived},
        "pareto_unequal": not pareto_ok,
        "v068_compare": {
            "F1": {"v068": "71/10/rows3", "v069": cheap.get("1")},
            "F2": {"v068": "135/2/rows0", "v069": cheap.get("2")},
        },
        "v067_compare": {
            "F2_presd5": {"v067": "130/2/rows1", "v069": best_f2},
            "F3": {"v067": 173, "v069": (cheap.get("3") or {}).get("g")},
            "F8": {"v067": 192, "v069": (cheap.get("8") or {}).get("g")},
        },
        "lanes": {"expansions": res.lane_exp, "pops": res.lane_pops},
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/").replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    # choose_integrated_verdict is for v0.68 labels; use throughput verdicts
    verdict, interpretation = choose_throughput_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "rows1": payload.get("rows1"),
            "frontier": frontier,
            "best_presd5_f2": best_f2,
            "tracker": payload.get("tracker"),
            "microbench": payload.get("microbench"),
            "solution_g": payload.get("solution_g"),
            "verdict": verdict,
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
