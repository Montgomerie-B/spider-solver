#!/usr/bin/env python3
"""v0.64: reconstruct the v0.63 healthy F1 and continue autonomously.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.healthy_f1 import (
    CANDIDATE_CEILING,
    F1_G,
    INCUMBENT_G,
    LINEAGE_TAG,
    audit_v063_ancestry,
    choose_f1_verdict,
    incumbent_epoch_snapshots,
    reconstruct_v063_f1,
    search_f1_continuation,
    snapshot_f1,
    verify_f1_prefix,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, OP_LANES
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import CANON_MOVES, load_opening
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    save_solution,
)

EXPERIMENT = "healthy_f1_lineage_v0_64"
BASE_SHA = "62bfe99f3168076e721e2681e45b6bd38f42d045"
BRANCH = "agent/healthy-f1-lineage-continuation-v0-64"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "healthy_f1_lineage_progress_v0_64.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_64.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_64.json"


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


def slim_epoch(ep: dict) -> dict:
    cats = ep.get("portfolio_cats") or {}
    return {
        "stock_rows": ep.get("stock_rows"),
        "input_roots": ep.get("input_roots"),
        "lineage_roots": ep.get("lineage_roots"),
        "unique": ep.get("unique"),
        "expanded": ep.get("expanded"),
        "generated": ep.get("generated"),
        "min_g": ep.get("min_g"),
        "max_g": ep.get("max_g"),
        "min_face_down": ep.get("min_face_down"),
        "max_foundations": ep.get("max_foundations"),
        "n_ready": ep.get("n_ready"),
        "lane_exp": ep.get("lane_exp"),
        "portfolio_cats": cats,
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
        "budget_left_197": None if ep.get("min_g") is None else CANDIDATE_CEILING - int(ep["min_g"]),
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
            "op_blockers",
            "k_min_blockers",
            "anchor_contention",
            "boundaries_total",
            "empty_n",
            "elapsed_s",
            "lineage",
        )
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "HEALTHY_F1_CONTINUATION_COST_IMPROVED":
        return "Promote the new autonomous incumbent and analyse where the savings occurred."
    if verdict == "HEALTHY_F1_LINEAGE_LOST_BY_PORTFOLIO":
        return "Next: generic lineage preservation / portfolio survival. Do not copy 172."
    if verdict == "HEALTHY_F1_LINEAGE_LATE_COST_FAILURE":
        return "If cost jumps after a Deal: Deal-reception shaping. If post-stock: assembly/cost-to-go."
    if verdict == "HEALTHY_F1_LINEAGE_REACHES_DEEP_ENDGAME":
        return "Analyse post-stock conversion of this F1 lineage before changing policy."
    if verdict == "HEALTHY_F1_PROVENANCE_FAILURE":
        return "Stop until the v0.63 F1 path can be stored with full_actions."
    return "Do not widen runtime. Do not copy the 172 route."


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## F1 reconstruction",
        "",
        json.dumps(p.get("f1"), indent=2, sort_keys=True)[:4000],
        "",
        "## Ancestry",
        "",
        json.dumps(p.get("ancestry"), indent=2, sort_keys=True)[:2000],
        "",
        "## Continuation totals",
        "",
        json.dumps(
            {k: p.get(k) for k in (
                "elapsed_s", "unique", "expanded", "generated", "states_per_s",
                "stop_reason", "solution_g", "max_foundations", "min_face_down",
            )},
            indent=2,
            sort_keys=True,
        ),
        "",
        "## Epochs",
        "",
        json.dumps(p.get("epochs"), indent=2, sort_keys=True)[:8000],
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    ancestry = audit_v063_ancestry()
    print("ANCESTRY", ancestry.get("status"), flush=True)
    print("RECONSTRUCT v0.63 F1", flush=True)
    recon = reconstruct_v063_f1(opening)
    if not recon.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "provenance_fail": True,
            "ancestry": ancestry,
            "debug": recon.get("debug"),
            "snap": recon.get("snap"),
            "verdict": "HEALTHY_F1_PROVENANCE_FAILURE",
            "interpretation": recon.get("reason"),
            "next_recommendation": next_recommendation("HEALTHY_F1_PROVENANCE_FAILURE"),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT HEALTHY_F1_PROVENANCE_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    prefix = recon["actions"]
    snap = recon["snap"]
    print(
        f"F1 ok g={snap['g']} fd={snap['face_down']} rows={snap['stock_rows']} "
        f"F={snap['foundations']} suits={snap['foundation_suits']} actions={len(prefix)}",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "f1_g": snap["g"],
            "f1_digest": snap["ordered_digest"],
            "f1_ident": snap["whole_game_identity"],
            "reconstruct_s": recon.get("elapsed_s"),
            "ancestry": ancestry,
        },
    )

    print("SEARCH continuation ceiling=197 900s", flush=True)
    t0 = time.perf_counter()
    res = search_f1_continuation(opening=opening, recon=recon)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} minfd={res.min_face_down} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    lineage_epochs = []
    lost = False
    min_rows = 3
    for ep in res.epochs:
        n_lin = ep.get("lineage_roots")
        if n_lin is None:
            n_lin = 1
        min_rows = min(min_rows, int(ep.get("stock_rows") if ep.get("stock_rows") is not None else 3))
        lineage_epochs.append(slim_epoch(ep))
        if int(ep.get("input_roots") or 0) > 0 and n_lin == 0 and ep.get("stock_rows") not in (None, 3):
            lost = True

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < INCUMBENT_G
        and res.solution_actions
    )
    replay_ok = False
    replay_g = None
    if improved:
        save_solution(res.solution_actions, FIX, g=int(res.solution_g))
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
                "g": res.solution_g,
                "prefix_g": F1_G,
                "replay_g": replay_g,
                "replay_ok": replay_ok,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
                "lineage": LINEAGE_TAG,
            },
        )

    print("COMPARE incumbent 198 epochs", flush=True)
    inc_snaps = incumbent_epoch_snapshots(opening)
    print("EVAL canonical after search", flush=True)
    canon_actions = parse_moves_file(CANON_MOVES)
    canon_g = replay_actions(opening.clone(), canon_actions)

    post_stock = next((ep for ep in res.epochs if ep.get("stock_rows") == 0), None)
    late_fail = (
        not improved
        and post_stock is not None
        and int(post_stock.get("min_g") or 0) >= 71
    )
    if not improved and res.max_foundations >= 2 and (post_stock is None or int(post_stock.get("min_g") or 198) > 160):
        late_fail = True

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "ancestry": ancestry,
        "f1": snap,
        "f1_prefix_actions": recon["root"]["full_actions"],
        "f1_digest": snap["ordered_digest"],
        "f1_ident": snap["whole_game_identity"],
        "reconstruct_s": recon.get("elapsed_s"),
        "reconstruct_unique": recon.get("unique"),
        "reconstruct_stop": recon.get("stop_reason"),
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "portfolio_width": PORTFOLIO_WIDTH,
            "prefix_g": F1_G,
            "remaining_budget": CANDIDATE_CEILING - F1_G,
            "lanes": list(OP_LANES),
            "harvest_cats": list(OP_HARVEST_CATS),
        },
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "peak_rss_mb": res.peak_rss_mb,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "min_g": res.min_g,
        "max_g": res.max_g,
        "lanes": {"names": list(OP_LANES), "pops": res.lane_pops, "expansions": res.lane_exp, "stale": res.lane_stale},
        "incumbent_g": INCUMBENT_G,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok if improved else res.replay_ok,
        "replay_g": replay_g if improved else res.replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {"first": first, "cheap": cheap},
        "epochs": lineage_epochs,
        "cost_map": {
            "F1": F1_G,
            "continuation_min_g": res.min_g,
            "continuation_max_g": res.max_g,
            "max_F": res.max_foundations,
            "terminal": res.solution_g,
        },
        "lineage_lost": lost,
        "late_cost_failure": late_fail,
        "min_stock_rows_reached": min_rows,
        "incumbent_epochs": [
            {k: s.get(k) for k in ("label", "g", "stock_rows", "face_down", "foundations", "legal_tableau", "best_suit", "n_ready")}
            for s in inc_snaps
        ],
        "canonical_g_eval_only": canon_g,
        "best_state": res.best_state,
        "best_readiness": res.best_readiness,
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
    verdict, interpretation = choose_f1_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "f1_digest": payload.get("f1_digest"),
            "epochs": payload.get("epochs"),
            "foundations_cheap": cheap,
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
