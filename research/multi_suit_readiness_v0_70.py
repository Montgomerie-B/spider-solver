#!/usr/bin/env python3
"""v0.70: multi-suit operational readiness at rows=1.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_policy import MULTI_SUIT_LANES, assembly_lane_keys
from spider.autonomous_cost import checkpoints_from_trace
from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    enrich_integrated,
    load_autonomous_192,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.multi_suit_readiness import (
    MultiSuitTracker,
    audit_rows1_ready_ranks,
    choose_multi_suit_verdict,
)
from spider.operational_policy import search_operational_optimisation
from spider.operational_viability import rank_ready_suits
from spider.research_actions import is_deal, stock_rows
from spider.solution_forensics import load_opening
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "multi_suit_readiness_v0_70"
BASE_SHA = "9fd8ef93f34f17851810318714694fc865121704"
BRANCH = "agent/multi-suit-readiness-v0-70"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "multi_suit_readiness_progress_v0_70.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_70.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_70.json"


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
            "assembly_h",
            "assembly_f",
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
        "lane_pops": ep.get("lane_pops"),
        "alloc_s": ep.get("alloc_s"),
        "elapsed_s": ep.get("elapsed_s"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "lower_bound_prunes": ep.get("lower_bound_prunes"),
        "stop_reason": ep.get("stop_reason"),
    }


def slim_audit(audit: dict) -> dict:
    states = []
    for rec in audit.get("states") or []:
        states.append(
            {
                "g": rec.get("g"),
                "F": rec.get("F"),
                "fd": rec.get("fd"),
                "legal": rec.get("legal"),
                "empty": rec.get("empty"),
                "best_suit": rec.get("best_suit"),
                "n_ready": rec.get("n_ready"),
                "ready_suits": rec.get("ready_suits"),
                "eventual_suit": rec.get("eventual_suit"),
                "eventual_suit_rank": rec.get("eventual_suit_rank"),
                "cashed_suit": rec.get("cashed_suit"),
                "cashed_rank": rec.get("cashed_rank"),
                "ranked": [
                    {k: row.get(k) for k in ("rank", "suit", "cover", "relevant_blockers", "k_min_blockers", "a_min_blockers", "gap", "legal_merge_edges")}
                    for row in rec.get("ranked") or []
                ],
            }
        )
    return {
        "entry": audit.get("entry"),
        "n_states": audit.get("n_states"),
        "cashed_suit": audit.get("cashed_suit"),
        "cashed_g": audit.get("cashed_g"),
        "primary_frac": audit.get("primary_frac"),
        "alternate_frac": audit.get("alternate_frac"),
        "rank_set": audit.get("rank_set"),
        "classification": audit.get("classification"),
        "states": states,
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "MULTI_SUIT_READINESS_COST_IMPROVED":
        return "Promote the new incumbent. Do not copy the canonical route."
    if verdict == "MULTI_SUIT_READINESS_REDISCOVERS_F2":
        return "Assess whether v0.67 endgame machinery converts the new F2; if not, analyse that F2 state."
    if verdict == "MULTI_SUIT_READINESS_IMPROVES_TRANSITION":
        return "Use bounded tactical foundation cash-out lookahead. Do not widen runtime."
    if verdict == "MULTI_SUIT_READINESS_HYPOTHESIS_FALSE":
        return "Do not add more suit-diversity lanes. Move to a generic bounded pre-Deal cash-out search."
    if verdict == "MULTI_SUIT_READINESS_NO_GAIN":
        return "Move to a generic bounded pre-Deal cash-out search. Do not widen runtime."
    return "Do not widen runtime. Do not copy the canonical route."


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## 192 rows=1 audit",
        "",
        json.dumps({k: (p.get("audit") or {}).get(k) for k in (
            "classification", "cashed_suit", "cashed_g", "primary_frac", "alternate_frac", "rank_set", "n_states", "entry",
        )}, indent=2, sort_keys=True),
        "",
        "## Preflight",
        "",
        json.dumps(p.get("preflight") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## Rows=1 vs v0.69",
        "",
        json.dumps(p.get("rows1") or {}, indent=2, sort_keys=True)[:4000],
        "",
        "## F1-F8",
        "",
        json.dumps(p.get("frontier") or [], indent=2, sort_keys=True)[:6000],
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
            "verdict": "MULTI_SUIT_READINESS_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT MULTI_SUIT_READINESS_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("AUDIT 192 rows=1 ready-suit ranks (evaluation only)", flush=True)
    audit = audit_rows1_ready_ranks(opening, inc["actions"])
    print(
        f"AUDIT cashed={audit.get('cashed_suit')} g={audit.get('cashed_g')} "
        f"class={audit.get('classification')} primary={audit.get('primary_frac'):.2f} "
        f"alt={audit.get('alternate_frac'):.2f} n={audit.get('n_states')}",
        flush=True,
    )
    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    ck1 = dict(ck[1])
    print(f"ROWS1 CHECKPOINT g={ck1['g']} fd={ck1.get('face_down')} F={ck1.get('foundations')}", flush=True)

    print("PREFLIGHT rows=1 checkpoint 4s multi-suit lanes", flush=True)
    clear_preview_cache()
    pre_tr = MultiSuitTracker()
    t_pre = time.perf_counter()
    pre = search_operational_optimisation(
        opening=opening,
        initial_roots=[dict(ck1)],
        cost_ceiling=CANDIDATE_CEILING,
        incumbent_by_rows={},
        max_unique=8_000,
        time_limit_s=4.0,
        rss_abort_mb=SEARCH_RSS_MB,
        portfolio_width=PORTFOLIO_WIDTH,
        extra_track=pre_tr,
        enrich_fn=enrich_integrated,
        on_harvest=pre_tr.on_harvest,
        finalize_track=pre_tr.finalize,
        lane_names=MULTI_SUIT_LANES,
        keys_fn=assembly_lane_keys,
        lower_bound_fn=None,
    )
    print(
        f"PREFLIGHT exp={pre.expanded} r2={pre.lane_exp.get('readiness_r2', 0)} "
        f"r3={pre.lane_exp.get('readiness_r3', 0)} r1={pre.lane_exp.get('readiness', 0)} "
        f"maxF={pre.max_foundations} t={time.perf_counter()-t_pre:.2f}s",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "phase": "preflight_ok",
            "audit_class": audit.get("classification"),
            "preflight_lane_exp": pre.lane_exp,
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
                "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )
    f2s = list(getattr(tracker, "f2_rows1", None) or [])
    best_f2 = None
    if f2s:
        best_f2 = min(f2s, key=lambda r: (int(r.get("g") or 999), int(r.get("fd") or 99)))
        best_f2 = dict(best_f2)
        best_f2["stock_rows"] = 1
    cheap_f2 = cheap.get("2") or {}
    if cheap_f2.get("stock_rows") == 1:
        cand = {
            "g": cheap_f2.get("g"),
            "fd": cheap_f2.get("face_down"),
            "F": 2,
            "suits": cheap_f2.get("foundation_suits"),
            "stock_rows": 1,
            "legal": cheap_f2.get("legal_tableau"),
            "from_incumbent_ckpt": cheap_f2.get("from_incumbent_ckpt"),
        }
        if best_f2 is None or int(cand["g"] or 999) < int(best_f2.get("g") or 999):
            best_f2 = cand

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
            label="Autonomous v0.70 multi-suit readiness solution",
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
        "audit": slim_audit(audit),
        "rows1_checkpoint": {
            "g": ck1["g"],
            "fd": ck1.get("face_down"),
            "F": ck1.get("foundations"),
            "note": "epoch-entry after SD4, not the internal g=130 F2",
        },
        "preflight": {
            "expanded": pre.expanded,
            "unique": pre.unique,
            "max_foundations": pre.max_foundations,
            "lane_exp": pre.lane_exp,
            "r2_live": int(pre.lane_exp.get("readiness_r2") or 0) > 0,
            "r3_live": int(pre.lane_exp.get("readiness_r3") or 0) > 0,
            "tracker": pre_tr.stats(),
            "elapsed_s": pre.elapsed_s,
        },
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(MULTI_SUIT_LANES),
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
            "v069_expanded": 1600,
            "v069_unique": 9062,
            "s": r1.get("elapsed_s"),
            "alloc_s": r1.get("alloc_s"),
            "expanded": r1.get("expanded"),
            "generated": r1.get("generated"),
            "unique": r1.get("unique"),
            "max_F": r1.get("max_foundations"),
            "min_fd": r1.get("min_face_down"),
            "exp_per_s": None
            if not r1.get("elapsed_s")
            else float(r1.get("expanded") or 0) / float(r1["elapsed_s"]),
            "lane_exp": r1.get("lane_exp"),
            "portfolio_cats": r1.get("portfolio_cats"),
        },
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
        "v069_compare": {
            "rows1_expanded": {"v069": 1600, "v070": r1.get("expanded")},
            "rows1_unique": {"v069": 9062, "v070": r1.get("unique")},
            "pre_sd5_max_F": {"v069": 1, "v070": r1.get("max_foundations")},
            "F2_post_stock": {"v069": 135, "v070": (cheap.get("2") or {}).get("g")},
        },
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, interpretation = choose_multi_suit_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "audit_class": audit.get("classification"),
            "rows1": payload.get("rows1"),
            "frontier": frontier,
            "best_presd5_f2": best_f2,
            "lane_exp": res.lane_exp,
            "preflight": payload.get("preflight"),
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
