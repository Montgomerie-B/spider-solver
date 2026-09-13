#!/usr/bin/env python3
"""v0.68: integrated whole-game optimisation from the autonomous 192 incumbent.

Canonical 172 is evaluation only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import assembly_bound_detail, assembly_lb
from spider.assembly_policy import COMPLETION_LANES
from spider.deal_preview import clear_preview_cache, compact_preview, preview_cache_stats, preview_next_deal
from spider.final_deal_transition import TRANSITION_HARVEST_CATS, transition_share
from spider.healthy_f2 import canonical_f2_snapshot, parse_stored_actions
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    INCUMBENT_MOVES,
    choose_integrated_verdict,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import CANONICAL_MW_COST, parse_moves_file, replay_actions
from spider.operational_policy import OP_HARVEST_CATS, OP_LANES
from spider.packed_state import unpack_state
from spider.research_actions import apply_action, is_deal, step_cost, stock_rows
from spider.solution_forensics import (
    extract_epochs,
    instrumented_replay,
    load_opening,
    rehandling_summary,
    structural_view,
)
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "integrated_whole_game_v0_68"
BASE_SHA = "a1a935f4bb2c956dc36c06ecbb9e32356b88e56a"
BRANCH = "agent/integrated-whole-game-optimisation-v0-68"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "integrated_whole_game_progress_v0_68.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_68.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_68.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"


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
            "assembly_slack",
            "incumbent_control",
            "portfolio_cat",
            "lineage",
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
        "deal_now_kept": ep.get("deal_now_kept"),
        "after_deal_unique": ep.get("after_deal_unique"),
        "lower_bound_prunes": ep.get("lower_bound_prunes"),
        "lower_bound_calls": ep.get("lower_bound_calls"),
        "lower_bound_s": ep.get("lower_bound_s"),
        "min_h": ep.get("min_h"),
        "max_h": ep.get("max_h"),
        "min_f": ep.get("min_f"),
        "prunes_by_F": ep.get("prunes_by_F"),
        "alloc_s": ep.get("alloc_s"),
        "alloc_unique": ep.get("alloc_unique"),
        "weight": ep.get("weight"),
        "stop_reason": ep.get("stop_reason"),
        "elapsed_s": ep.get("elapsed_s"),
        "lineage_roots": ep.get("lineage_roots"),
        "lineage_after_deal": ep.get("lineage_after_deal"),
    }


def generic_waterfall(left_epochs, right_epochs, left_name, right_name):
    rows = []
    cum = 0
    n = min(len(left_epochs), len(right_epochs))
    for a, c in zip(left_epochs[:n], right_epochs[:n]):
        dl = int(a.get("delta_g") or 0)
        dr = int(c.get("delta_g") or 0)
        delta = dl - dr
        cum += delta
        rows.append(
            {
                "label": a.get("label"),
                "stock_rows": a.get("stock_rows"),
                left_name: dl,
                right_name: dr,
                "delta": delta,
                "cumulative": cum,
            }
        )
    return {"rows": rows, "cumulative": cum, "n": n}


def next_recommendation(verdict: str) -> str:
    if verdict == "INTEGRATED_WHOLE_GAME_COST_IMPROVED":
        return (
            "Promote the new incumbent and forensic-compare it against 192/172 "
            "before adding another strategic mechanism."
        )
    if verdict == "INTEGRATED_WHOLE_GAME_REDISCOVERS_192_CLASS":
        return (
            "The integrated architecture is validated. Next optimisation can target "
            "earlier cross-Deal future-state quality. Do not copy the canonical route."
        )
    if verdict == "INTEGRATED_WHOLE_GAME_LINEAGE_NOT_REDISCOVERED":
        return (
            "Focus on whole-game portfolio survival / Deal-transition reasoning "
            "rather than endgame search."
        )
    if verdict == "INTEGRATED_WHOLE_GAME_CEILING_TOO_TIGHT_NO_TERMINAL":
        return "Do not widen runtime. Report the excluded lineages; keep ceiling = incumbent - 1."
    return "Do not widen runtime. Do not copy the canonical route."


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("interpretation", ""),
        "",
        "## Incumbent 192",
        "",
        json.dumps(p.get("incumbent_verify") or {}, indent=2, sort_keys=True)[:2000],
        "",
        "## Envelope",
        "",
        json.dumps(p.get("envelope") or {}, indent=2, sort_keys=True),
        "",
        "## Epoch allocation",
        "",
        json.dumps(p.get("epochs") or [], indent=2, sort_keys=True)[:8000],
        "",
        "## F1-F8",
        "",
        json.dumps(p.get("frontier") or [], indent=2, sort_keys=True)[:8000],
        "",
        "## Proof-prunes / preview",
        "",
        json.dumps(p.get("bound_perf") or {}, indent=2, sort_keys=True),
        "",
        json.dumps(p.get("preview_perf") or {}, indent=2, sort_keys=True),
        "",
        "## 198 to 192 forensics",
        "",
        json.dumps(p.get("forensics_summary") or {}, indent=2, sort_keys=True)[:8000],
        "",
        "## Next recommendation",
        "",
        p.get("next_recommendation", ""),
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, labels = load_opening()
    print("VERIFY autonomous 192 incumbent", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "incumbent_fail": True,
            "incumbent_verify": {k: inc.get(k) for k in inc if k != "actions"},
            "verdict": "INTEGRATED_WHOLE_GAME_CONTRACT_FAILURE",
            "interpretation": "192 incumbent failed replay",
            "next_recommendation": next_recommendation("INTEGRATED_WHOLE_GAME_CONTRACT_FAILURE"),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT INTEGRATED_WHOLE_GAME_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print(
        f"INCUMBENT ok g={inc['g']} deals={inc['deals']} actions={inc['n_actions']}",
        flush=True,
    )
    _write_json(PROG, {"phase": "preflight_ok", "incumbent_g": inc["g"]})
    clear_preview_cache()

    print("SEARCH whole-game from untouched opening ceiling=191 900s", flush=True)
    t0 = time.perf_counter()
    res = search_integrated_optimisation(opening=opening)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} prunes={res.lower_bound_prunes} "
        f"t={res.elapsed_s:.1f}s",
        flush=True,
    )
    lb_rec = reconcile_lower_bound_telemetry(res)
    preview_stats = preview_cache_stats()

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    first = {str(k): slim_f(v) for k, v in sorted(res.foundations_first.items())}
    frontier = []
    for n, rec in sorted(res.foundations_cheap.items()):
        g = rec.get("g")
        h = rec.get("assembly_h")
        if h is None and rec.get("ordered_digest") and int(rec.get("stock_rows") or 0) == 0:
            st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
            info = assembly_bound_detail(st)
            h = info["h"]
            rec = dict(rec)
            rec["assembly_h"] = h
            rec["assembly_f"] = int(g) + h
            rec["assembly_slack"] = CANDIDATE_CEILING - (int(g) + h)
            cheap[str(n)] = slim_f(rec)
        frontier.append(
            {
                "F": n,
                "g": g,
                "rows": rec.get("stock_rows"),
                "fd": rec.get("face_down"),
                "suits": rec.get("foundation_suits"),
                "legal": rec.get("legal_tableau"),
                "boundaries": rec.get("boundaries_total"),
                "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"),
                "slack": rec.get("assembly_slack"),
                "incumbent_control": rec.get("incumbent_control"),
                "elapsed_s": rec.get("elapsed_s"),
            }
        )

    cat_counts = dict(getattr(res, "transition_cats", None) or {})
    sd5 = next((slim_epoch(ep) for ep in res.epochs if ep.get("stock_rows") == 1), None)
    if sd5 and sd5.get("portfolio_cats"):
        cat_counts = cat_counts or dict(sd5["portfolio_cats"])

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < AUTONOMOUS_INCUMBENT_MW
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    from_checkpoint = False
    if res.solved and res.solution_actions:
        ck_actions = []
        # prefix match against injected checkpoints is reported via incumbent_survived
        pass
    if improved:
        save_solution(
            res.solution_actions,
            FIX,
            g=int(res.solution_g),
            label="Autonomous v0.68 integrated whole-game solution",
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
                "deals": 5,
                "tableau_commands": len(res.solution_actions) - 5,
                "parent_incumbent": AUTONOMOUS_INCUMBENT_MW,
                "from_untouched_opening": True,
                "incumbent_checkpoints_injected": res.incumbent_injected,
                "incumbent_checkpoints_survived": res.incumbent_survived,
                "path": str(FIX.relative_to(ROOT)).replace("\\", "/"),
                "branch": BRANCH,
                "base_sha": BASE_SHA,
            },
        )

    print("EVAL canonical and 192 forensics after search", flush=True)
    a192 = parse_moves_file(INCUMBENT_MOVES)
    a198 = parse_moves_file(V059)
    a172 = parse_moves_file(CANON)
    t192 = instrumented_replay(opening, a192, labels, expected_g=192)
    t198 = instrumented_replay(opening, a198, labels, expected_g=198)
    t172 = instrumented_replay(opening, a172, labels, expected_g=172)
    e192 = extract_epochs(t192, opening, a192, labels)
    e198 = extract_epochs(t198, opening, a198, labels)
    e172 = extract_epochs(t172, opening, a172, labels)
    rh192 = rehandling_summary(t192)
    rh198 = rehandling_summary(t198)
    rh172 = rehandling_summary(t172)
    wf_198_192 = generic_waterfall(e198, e192, "g198", "g192")
    wf_192_172 = generic_waterfall(e192, e172, "g192", "g172")

    def post_sd5_cost(trace):
        deals = [ep for ep in extract_epochs(trace, opening, [], labels)]  # unused
        return None

    post192 = next((ep for ep in e192 if ep.get("label") == "post-SD5"), None)
    post198 = next((ep for ep in e198 if ep.get("label") == "post-SD5"), None)
    post172 = next((ep for ep in e172 if ep.get("label") == "post-SD5"), None)

    def enter_view(ep):
        if not ep:
            return {}
        ent = ep.get("enter") or {}
        return {
            "g": ent.get("g"),
            "fd": ent.get("face_down"),
            "foundations": ent.get("foundations"),
            "legal": ent.get("legal_tableau"),
            "empty_n": ent.get("empty_n"),
            "bonds": ent.get("same_suit_bonds"),
            "remaining": ent.get("remaining_cost"),
        }

    # assembly h along 192 stock-empty suffix
    st = opening.clone()
    g = 0
    h_traj = []
    for action in a192:
        if stock_rows(st) == 0:
            h = assembly_lb(st)
            h_traj.append({"g": g, "h": h, "f": g + h, "remain": 192 - g, "ok": h <= 192 - g})
        cost = 1 if is_deal(action) else step_cost(st, action)
        apply_action(st, action)
        g += cost

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "from_untouched_opening": True,
        "incumbent_verify": {k: inc.get(k) for k in inc if k != "actions"},
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "candidate_ceiling": CANDIDATE_CEILING,
            "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
            "canonical_mw": CANONICAL_MW_COST,
            "portfolio_width": PORTFOLIO_WIDTH,
            "lanes": list(COMPLETION_LANES),
            "base_lanes": list(OP_LANES),
            "harvest_cats": list(TRANSITION_HARVEST_CATS),
            "base_harvest_cats": list(OP_HARVEST_CATS),
            "checkpoints": True,
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
        "lanes": {
            "names": list(COMPLETION_LANES),
            "pops": res.lane_pops,
            "expansions": res.lane_exp,
            "stale": res.lane_stale,
        },
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "max_foundations": res.max_foundations,
        "min_face_down": res.min_face_down,
        "foundations": {"first": first, "cheap": cheap},
        "frontier": frontier,
        "epochs": [slim_epoch(ep) for ep in res.epochs],
        "checkpoint": {
            "injected": res.incumbent_injected,
            "survived": res.incumbent_survived,
        },
        "n_previewed": getattr(res, "n_previewed", 0),
        "portfolio": {
            "width": PORTFOLIO_WIDTH,
            "cats": cat_counts,
            "transition_share": transition_share(cat_counts, PORTFOLIO_WIDTH) if cat_counts else None,
            "deal_now": None if not cat_counts else cat_counts.get("deal_now"),
            "frozen_v066_preview": True,
        },
        "bound_perf": {
            "calls": res.lower_bound_calls,
            "seconds": res.lower_bound_s,
            "prunes": res.lower_bound_prunes,
            "generated": res.generated,
            "prune_fraction": 0.0
            if not res.generated
            else float(res.lower_bound_prunes) / float(res.generated),
            "min_h": res.min_h,
            "max_h": res.max_h,
            "min_f": res.min_f,
            "prunes_by_F": dict(res.prunes_by_F or {}),
            "reconcile": lb_rec,
        },
        "preview_perf": preview_stats,
        "forensics_summary": {
            "saved_vs_198": 6,
            "rehandle_198": rh198.get("paid_mw_tagged_rehandle"),
            "rehandle_192": rh192.get("paid_mw_tagged_rehandle"),
            "rehandle_172": rh172.get("paid_mw_tagged_rehandle"),
            "waterfall_198_minus_192": wf_198_192,
            "waterfall_192_minus_172": wf_192_172,
            "post_sd5_192": enter_view(post192),
            "post_sd5_198": enter_view(post198),
            "post_sd5_172": enter_view(post172),
            "bucket_192": t192.get("bucket_mw"),
            "bucket_198": t198.get("bucket_mw"),
            "bucket_172": t172.get("bucket_mw"),
            "assembly_h_192_stock_empty": h_traj[:40],
            "h_admissible_on_192": all(x["ok"] for x in h_traj),
        },
        "v067_compare": {
            "best_g": {"v067": 192, "v068": res.solution_g},
            "F3": {"v067": 173, "v068": (cheap.get("3") or {}).get("g")},
            "F5": {"v067": 185, "v068": (cheap.get("5") or {}).get("g")},
            "F7": {"v067": 191, "v068": (cheap.get("7") or {}).get("g")},
            "F8": {"v067": 192, "v068": (cheap.get("8") or {}).get("g")},
            "proof_prunes": {"v067": 57270, "v068": res.lower_bound_prunes},
        },
        "no_new_solution_if_not_improved": not improved,
    }
    if improved:
        payload["solution_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
        payload["from_untouched_opening"] = True
    verdict, interpretation = choose_integrated_verdict(payload)
    payload["verdict"] = verdict
    payload["interpretation"] = interpretation
    payload["generality"] = (
        "whole-game: epoch scheduler, operational viability, Deal preview, "
        "and stock-empty assembly bound operate together from move zero"
        if (res.max_foundations or 0) >= 2
        else "integration from opening did not reach late-game focused-experiment structures"
    )
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
            "epochs": payload.get("epochs"),
            "foundations_cheap": cheap,
            "frontier": frontier,
            "bound_perf": payload.get("bound_perf"),
            "preview_perf": preview_stats,
            "solution_g": payload.get("solution_g"),
            "stop_reason": payload.get("stop_reason"),
            "verdict": verdict,
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
