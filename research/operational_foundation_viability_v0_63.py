#!/usr/bin/env python3
"""v0.63: operational foundation viability / excavation-gated cash-out.

One policy, one 900 s run. Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_cost import load_machine_incumbent
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import (
    OP_HARVEST_CATS,
    OP_LANES,
    choose_operational_verdict,
    search_operational_optimisation,
)
from spider.operational_viability import compact_operational, rank_ready_suits
from spider.packed_state import unpack_state
from spider.research_actions import apply_action, is_deal, stock_rows, tableau_actions
from spider.solution_forensics import AUTO_MOVES, CANON_MOVES, load_opening
from spider.structural_analysis import current_tableau_summary, foundation_readiness
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)

EXPERIMENT = "operational_foundation_viability_v0_63"
BASE_SHA = "20c0388a211ee728e152fff44f1bd90479b8ebd0"
BRANCH = "agent/operational-foundation-viability-v0-63"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "operational_foundation_progress_v0_63.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_63.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_63.json"
V060 = ROOT / "docs" / "research" / "autonomous_cost_optimisation_v0_60.json"


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


def slim_op(v):
    if not v:
        return None
    return compact_operational(v)


def snapshot_operational(state, g=None):
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    ranked = rank_ready_suits(state, readiness=r, summary=s, g=int(g or 0))
    return {
        "g": g,
        "stock_rows": stock_rows(state),
        "face_down": s["face_down"],
        "empty_n": s["empty_n"],
        "foundations": s["foundations"],
        "foundation_suits": list(s["foundation_suits"]),
        "legal_tableau": len(tableau_actions(state)),
        "n_ready": ranked["n_ready"],
        "ready_suits": ranked["ready_suits"],
        "best_suit": ranked["best_suit"],
        "second_suit": ranked["second_suit"],
        "best": slim_op(ranked["best"]),
        "second": slim_op(ranked["second"]),
        "all_ready": [slim_op(v) for v in ranked["ranked"]],
    }


def eval_route_foundations(opening, actions):
    state = opening.clone()
    g = 0
    events = []
    last_f = 0
    deal_n = 0
    sd5 = None
    from spider.research_actions import step_cost

    for action in actions:
        pre = snapshot_operational(state, g)
        cost = 1 if is_deal(action) else step_cost(state, action)
        if is_deal(action):
            deal_n += 1
        apply_action(state, action)
        g += cost
        f = len(state.foundations)
        if deal_n == 5 and sd5 is None and is_deal(action):
            sd5 = snapshot_operational(state, g)
            sd5["label"] = "post-SD5"
        if f > last_f:
            founded = state.foundations[-1][0].suit if state.foundations else None
            pre["n"] = f
            pre["founded"] = founded
            pre["g_after"] = g
            pre["fd_after"] = current_tableau_summary(state)["face_down"]
            pre["via"] = "deal" if is_deal(action) else "tableau"
            events.append(pre)
            last_f = f
    return {"foundations": events, "post_sd5": sd5, "final_g": g, "solved": state.is_solved()}


def cheap_f1_v060():
    if not V060.exists():
        return None
    data = json.loads(V060.read_text(encoding="utf-8"))
    rec = ((data.get("foundations") or {}).get("cheap") or {}).get("1")
    if not rec or not rec.get("ordered_digest"):
        return None
    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    snap = snapshot_operational(st, rec.get("g"))
    snap["note"] = "v0.60 cheapest F1 digest"
    return snap


def lineage_improved(cheap: dict, max_f: int) -> bool:
    f1 = cheap.get("1") or cheap.get(1) or {}
    f2 = cheap.get("2") or cheap.get(2) or {}
    fd1 = f1.get("face_down")
    fd2 = f2.get("face_down")
    healthier_f1 = fd1 is not None and int(fd1) <= 14
    healthier_f2 = fd2 is not None and int(fd2) <= 12
    farther = int(max_f or 0) >= 5
    return bool(healthier_f1 and (farther or healthier_f2))


def slim_epoch(ep: dict) -> dict:
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "min_face_down": ep.get("min_face_down"),
        "max_foundations": ep.get("max_foundations"),
        "n_ready": ep.get("n_ready"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": ep.get("portfolio_cats"),
        "best_readiness": None
        if not ep.get("best_readiness")
        else {
            k: ep["best_readiness"].get(k)
            for k in (
                "g",
                "foundations",
                "face_down",
                "n_ready",
                "cover",
                "ready_fd",
                "best_ready_suit",
                "op_blockers",
                "k_min_blockers",
                "anchor_contention",
            )
        },
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
    }


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
            "n_ready",
            "cover",
            "ready_fd",
            "best_ready_suit",
            "second_ready_suit",
            "op_blockers",
            "k_min_blockers",
            "a_min_blockers",
            "anchor_contention",
            "boundaries_total",
            "empty_n",
            "elapsed_s",
            "op_global_fd",
            "op_cover",
            "op_relevant_blockers",
            "op_suit",
        )
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "OPERATIONAL_VIABILITY_COST_IMPROVED":
        return "Continue autonomous cost optimisation from the new incumbent."
    if verdict == "OPERATIONAL_VIABILITY_IMPROVES_LINEAGE":
        return "Analyse the surviving lineage and post-stock conversion before changing anything else."
    if verdict == "OPERATIONAL_VIABILITY_SIGNAL_INVALID":
        return "Do not increase weighting. Revisit the viability features or move to Deal-reception shaping."
    if verdict == "OPERATIONAL_VIABILITY_CONTRACT_FAILURE":
        return "Stop solver work until the contract failure is diagnosed."
    return (
        "Do not increase weighting or runtime. Next remaining v0.61 hypothesis: "
        "Deal-reception shaping. Do not copy the 172 route."
    )


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## Envelope",
        "",
        json.dumps(p.get("envelope"), indent=2, sort_keys=True),
        "",
        "## Totals",
        "",
        json.dumps(
            {k: p.get(k) for k in (
                "elapsed_s", "unique", "expanded", "generated", "states_per_s",
                "stop_reason", "solution_g", "incumbent_g", "max_foundations",
                "min_face_down", "incumbent_injected", "incumbent_survived",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Lanes",
        "",
        json.dumps(p.get("lanes"), indent=2, sort_keys=True),
        "",
        "## Foundations",
        "",
        json.dumps(p.get("foundations"), indent=2, sort_keys=True)[:8000],
        "",
        "## Canonical evaluation",
        "",
        json.dumps(p.get("canonical_eval"), indent=2, sort_keys=True)[:8000],
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, labels = load_opening()
    inc = load_machine_incumbent(opening)
    print(f"SEARCH ceiling={inc['g'] - 1} 900s lanes={OP_LANES}", flush=True)
    t0 = time.perf_counter()
    res = search_operational_optimisation(opening=opening, incumbent_trace=inc)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} minfd={res.min_face_down} t={res.elapsed_s:.1f}s",
        flush=True,
    )
    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    _write_json(
        PROG,
        {
            "stop_reason": res.stop_reason,
            "unique": res.unique,
            "expanded": res.expanded,
            "generated": res.generated,
            "solution_g": res.solution_g,
            "elapsed_s": res.elapsed_s,
            "lane_exp": res.lane_exp,
            "lane_pops": res.lane_pops,
            "max_foundations": res.max_foundations,
            "min_face_down": res.min_face_down,
            "incumbent_injected": res.incumbent_injected,
            "incumbent_survived": res.incumbent_survived,
            "epochs": [slim_epoch(ep) for ep in res.epochs],
            "foundations_cheap": cheap,
            "foundations_first": first,
        },
    )
    print("WROTE progress snapshot", flush=True)

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < int(inc["g"])
        and res.solution_actions
    )
    if improved:
        deals = sum(1 for a in res.solution_actions if is_deal(a))
        save_solution(res.solution_actions, FIX, g=int(res.solution_g))
        _write_json(
            META,
            {
                "g": res.solution_g,
                "previous_incumbent": inc["g"],
                "replay_g": res.replay_g,
                "replay_ok": True,
                "deals": deals,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
            },
        )

    print("EVAL canonical 172 (after search)", flush=True)
    canon_actions = parse_moves_file(CANON_MOVES)
    assert replay_actions(opening.clone(), canon_actions) == 172
    canon_eval = eval_route_foundations(opening, canon_actions)
    auto_eval = eval_route_foundations(opening, parse_moves_file(AUTO_MOVES))
    v060_f1 = cheap_f1_v060()

    f1 = (canon_eval["foundations"] or [{}])[0] if canon_eval["foundations"] else {}
    metric_ok = True
    if f1.get("founded") and f1.get("all_ready"):
        founded = f1.get("founded")
        best_suit = f1.get("best_suit")
        hearts = next((x for x in f1["all_ready"] if x.get("suit") == "h"), None)
        chosen = next((x for x in f1["all_ready"] if x.get("suit") == founded), None)
        if founded != "h" and hearts and chosen:
            hb = int(hearts.get("relevant_blockers") or 0)
            cb = int(chosen.get("relevant_blockers") or 0)
            hc = hearts.get("cover")
            cc = chosen.get("cover")
            if hb < cb and hc is not None and cc is not None and int(hc) < int(cc):
                metric_ok = False
        if best_suit and founded and best_suit != founded and len(f1.get("ready_suits") or []) >= 2:
            if best_suit == "h" and founded in (f1.get("ready_suits") or []):
                metric_ok = False

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "durability_lane_active": False,
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling_initial": inc["g"] - 1,
            "portfolio_width": PORTFOLIO_WIDTH,
            "harvest_slack": -1,
            "remaining_deal_bound": True,
            "lanes": list(OP_LANES),
            "harvest_cats": list(OP_HARVEST_CATS),
        },
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {"names": list(OP_LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "class_displaced": res.class_displaced,
        "incumbent_injected": res.incumbent_injected,
        "incumbent_survived": res.incumbent_survived,
        "candidate_ceiling": res.candidate_ceiling,
        "incumbent_g": inc["g"],
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": res.replay_ok,
        "replay_g": res.replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {"first": first, "cheap": cheap},
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "lineage_improved": lineage_improved(cheap, res.max_foundations),
        "metric_signal": "ok" if metric_ok else "invalid",
        "canonical_eval": {
            "g": canon_eval["final_g"],
            "foundations": canon_eval["foundations"],
            "post_sd5": canon_eval["post_sd5"],
        },
        "incumbent_eval": {
            "g": auto_eval["final_g"],
            "foundations": auto_eval["foundations"],
            "post_sd5": auto_eval["post_sd5"],
        },
        "v060_cheap_f1": v060_f1,
        "baselines": {
            "v060_f1": {"g": 41, "fd": 17},
            "v062_f1": {"g": 60, "fd": 23},
            "v062_f2": {"g": 94, "fd": 19},
            "v062_f3": {"g": 120, "fd": 17},
            "v062_f4": {"g": 148, "fd": 11},
        },
        "production_unchanged": True,
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["improvement"] = int(inc["g"]) - int(res.solution_g)
    verdict, interpretation = choose_operational_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
