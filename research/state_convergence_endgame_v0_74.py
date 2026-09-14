#!/usr/bin/env python3
"""v0.74: exact autonomous state-convergence to 191, then focused stock-empty search.

Canonical 172 is evaluation only after search. The v0.67 suffix is not a
search target.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.autonomous_cost import checkpoints_from_trace, replay_solution_trace
from spider.metrics import AUTONOMOUS_INCUMBENT_MW, CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import (
    FOCUSED_ROOT_G,
    NEW_F2_G,
    OLD_F2_G,
    PARENT_INCUMBENT_G,
    SPLICED_G,
    V074_MOVES,
    V074_SPLICE_MOVES,
    build_verified_191,
    choose_convergence_verdict,
    foundation_progression,
    search_focused_endgame,
)
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "state_convergence_endgame_v0_74"
BASE_SHA = "7ea8583bcd691cdf70524b70b18180baf15f8ffb"
BRANCH = "agent/state-convergence-endgame-v0-74"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "state_convergence_endgame_progress_v0_74.json"
META = ROOT / "solutions" / "4925153_autonomous_v0_74.json"
BEST = ROOT / "solutions" / "4925153_autonomous_v0_74_best.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V073 = ROOT / "docs" / "research" / "maturity_aware_tactical_roots_v0_73.json"


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
    g = rec.get("g")
    h = rec.get("assembly_h")
    return {
        "g": g,
        "stock_rows": rec.get("stock_rows"),
        "face_down": rec.get("face_down"),
        "foundations": rec.get("foundations"),
        "empty_n": rec.get("empty_n"),
        "legal_tableau": rec.get("legal_tableau"),
        "boundaries_total": rec.get("boundaries_total"),
        "assembly_h": h,
        "assembly_f": rec.get("assembly_f") if rec.get("assembly_f") is not None else (
            None if g is None or h is None else int(g) + int(h)
        ),
        "slack_190": None if g is None or h is None else 190 - (int(g) + int(h)),
        "elapsed_s": rec.get("elapsed_s"),
        "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
    }


def next_recommendation(verdict: str) -> str:
    if verdict == "STATE_CONVERGENCE_ENDGAME_COST_IMPROVED":
        return "Promote the new stock-empty saving and analyse the continuation."
    if verdict == "STATE_CONVERGENCE_PROMOTES_191":
        return "191 is the autonomous incumbent; return to whole-game optimisation with ceiling 190."
    if verdict == "STATE_CONVERGENCE_191_VERIFIED_SEARCH_LIMITED":
        return "Analyse the remaining assembly/cost gap before changing strategic policy."
    if verdict == "STATE_CONVERGENCE_DIGEST_MISMATCH":
        return "Do not promote anything; diagnose the claimed F2 digest equality."
    if verdict == "STATE_CONVERGENCE_PREFIX_PROVENANCE_FAILURE":
        return "Do not promote anything; recover the exact g129 prefix provenance."
    return "Do not promote anything; diagnose the contract discrepancy."


def _row(rec: dict) -> str:
    if not rec:
        return "(none)"
    return (
        f"g={rec.get('g')} F={rec.get('F', rec.get('foundations'))} "
        f"fd={rec.get('face_down')} rows={rec.get('stock_rows')} "
        f"h={rec.get('assembly_h')} f={rec.get('assembly_f')} "
        f"slack={rec.get('slack_190')} empty={rec.get('empty_n')} "
        f"legal={rec.get('legal_tableau')} bounds={rec.get('boundaries_total')}"
    )


def write_report(p: dict) -> None:
    bp = p.get("bound_perf") or {}
    v073 = ((p.get("v073_vs_focused") or {}).get("v073_rows0") or {})
    foc = ((p.get("v073_vs_focused") or {}).get("focused") or {})
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or p.get("interpretation") or "",
        "",
        "## Why this is still autonomous",
        "",
        "The two route portions were independently solver-generated.",
        "",
        "- Prefix (v0.73): whole-game strategic search, machine-incumbent checkpoint,",
        "  generic maturity-aware root selection, generic rank-1 tactical target,",
        "  bounded tactical planner. No canonical input.",
        "- Suffix (v0.67): autonomous stock-empty solver. No canonical route.",
        "",
        "They are spliced only because the complete F2 states are byte-identical.",
        "No human move or canonical move is inserted. This is ordinary exact-state",
        "transposition relaxation: a cheaper path to an existing node inherits the",
        "known legal suffix from that node.",
        "",
        "## 192 verification",
        "",
        f"- ok={((p.get('old_192') or {}).get('ok'))} g={((p.get('old_192') or {}).get('g'))} "
        f"deals={((p.get('old_192') or {}).get('deals'))} solved={((p.get('old_192') or {}).get('solved'))}",
        "",
        "## Exact old F2 splice point",
        "",
        f"- action_index={((p.get('locate') or {}).get('action_index'))}",
        f"- n_prefix={((p.get('locate') or {}).get('n_prefix'))} n_suffix={((p.get('locate') or {}).get('n_suffix'))}",
        f"- g={((p.get('locate') or {}).get('g'))} rows={((p.get('locate') or {}).get('stock_rows'))} "
        f"fd={((p.get('locate') or {}).get('face_down'))} F={((p.get('locate') or {}).get('foundations'))}",
        f"- suits={((p.get('locate') or {}).get('foundation_suits'))}",
        f"- n_hits={((p.get('locate') or {}).get('n_hits'))}",
        f"- digest=`{p.get('digest')}`",
        "",
        "## g129 prefix reconstruction",
        "",
        f"- ok={((p.get('prefix') or {}).get('ok'))} g={((p.get('prefix') or {}).get('g'))}",
        f"- checkpoint_g={((p.get('prefix') or {}).get('checkpoint_g'))} "
        f"n_tactical={((p.get('prefix') or {}).get('n_tactical'))} "
        f"target={((p.get('prefix') or {}).get('target_suit'))}",
        f"- digest match={((p.get('prefix') or {}).get('digest')) == p.get('digest')}",
        "",
        "## 191 splice replay",
        "",
        f"- ok={((p.get('replay') or {}).get('ok'))} g={((p.get('replay') or {}).get('g'))} "
        f"deals={((p.get('replay') or {}).get('deals'))} solved={((p.get('replay') or {}).get('solved'))}",
        f"- splice_ok={((p.get('replay') or {}).get('splice_ok'))} splice_g={((p.get('replay') or {}).get('splice_g'))}",
        f"- suffix sequence ok={((p.get('suffix_sequence') or {}).get('ok'))}",
        f"- suffix cost={p.get('suffix_cost')} expected 129+62={p.get('expected_g')}",
        f"- split_ok={p.get('split_ok')} n_prefix={p.get('n_prefix')} n_suffix={p.get('n_suffix')}",
        f"- promoted incumbent={p.get('incumbent_g')} ceiling={p.get('candidate_ceiling')}",
        f"- RECORD_MW={p.get('record_mw')} CANONICAL_MW={p.get('canonical_mw')}",
        "",
        "## Focused root (F2 + real engine Deal)",
        "",
        _row(p.get("focused") or {}),
        f"- post-SD5 g={((p.get('focused') or {}).get('g'))} rows={((p.get('focused') or {}).get('stock_rows'))}",
        f"- immediate-Deal digest match with old F2+Deal={p.get('post_sd5_match')} "
        f"(old immediate g={((p.get('old_post_sd5') or {}).get('g'))})",
        f"- 192 actual Deal is not immediate: suffix Deal index="
        f"{((p.get('old_actual_post_sd5') or {}).get('deal_suffix_index'))} "
        f"actual_g={((p.get('old_actual_post_sd5') or {}).get('g'))} "
        f"same_as_focused={p.get('actual_post_sd5_same')}",
        "",
        "The focused search root is F2 then Deal, not the 192 suffix's later Deal.",
        "The old suffix is evaluation-only after search. It is not a search target.",
        "",
        "## Focused envelope",
        "",
        str(p.get("envelope") or {}),
        "",
        "## Focused search totals",
        "",
        f"- unique={p.get('unique')} expanded={p.get('expanded')} generated={p.get('generated')}",
        f"- elapsed={p.get('elapsed_s')} stop={p.get('stop_reason')} maxF={p.get('max_foundations')}",
        f"- solved={p.get('solved')} best_g={p.get('solution_g')} replay_ok={p.get('replay_ok')}",
        f"- lane expansions={p.get('lanes', {}).get('expansions')}",
        f"- proof-prunes={bp.get('prunes')} calls={bp.get('calls')} seconds={bp.get('seconds')}",
        f"- prunes_by_F={bp.get('prunes_by_F')} min_h={bp.get('min_h')} max_h={bp.get('max_h')} min_f={bp.get('min_f')}",
        "",
        "## F2–F8 frontier",
        "",
    ]
    for rec in p.get("frontier") or []:
        lines.append(f"- {_row(rec)}")
    lines += [
        "",
        "## Economically viable frontier",
        "",
        str(p.get("viability") or {}),
        "",
        "## Inherited 191 suffix foundation progression (evaluation only)",
        "",
        str(p.get("inherited_suffix_foundations") or []),
        "",
        "## v0.73 integrated vs focused endgame",
        "",
        f"- v0.73 rows=0: roots={v073.get('input_roots')} alloc_s={v073.get('alloc_s')} "
        f"exp={v073.get('expanded')} gen={v073.get('generated')} unique={v073.get('unique')} "
        f"maxF={v073.get('max_foundations')} lane_exp={v073.get('lane_exp')}",
        f"- focused rows=0: roots={foc.get('input_roots')} alloc_s={foc.get('alloc_s')} "
        f"exp={foc.get('expanded')} gen={foc.get('generated')} unique={foc.get('unique')} "
        f"maxF={foc.get('max_foundations')} min_f={foc.get('min_f')} prunes={foc.get('lower_bound_prunes')}",
        "",
        p.get("v073_diagnosis") or "",
        "",
        "## 191 checkpoints",
        "",
        str(p.get("checkpoints_191") or {}),
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


def v073_rows0(data: dict) -> dict:
    for ep in data.get("epochs") or []:
        rows = ep.get("stock_rows")
        if rows is not None and int(rows) == 0:
            return {
                "input_roots": ep.get("input_roots"),
                "alloc_s": ep.get("alloc_s"),
                "elapsed_s": ep.get("elapsed_s"),
                "expanded": ep.get("expanded"),
                "generated": ep.get("generated"),
                "unique": ep.get("unique"),
                "max_foundations": ep.get("max_foundations"),
                "lower_bound_prunes": (ep.get("augment") or {}).get("n_probes"),
                "lane_exp": ep.get("lane_exp"),
                "stop_reason": ep.get("stop_reason"),
            }
    return {}


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("BUILD verified 191 splice", flush=True)
    built = build_verified_191(opening)
    if not built.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "verdict": built.get("verdict") or "STATE_CONVERGENCE_CONTRACT_FAILURE",
            "verdict_pre": built.get("verdict"),
            "built": {k: built.get(k) for k in built if k not in ("prefix_actions", "spliced_actions", "suffix")},
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT", payload["verdict"], flush=True)
        print("DONE", flush=True)
        return payload

    print(
        f"191 VERIFIED prefix_g={NEW_F2_G} old_f2_g={OLD_F2_G} "
        f"suffix_cost={built['suffix_cost']} n={built['replay']['n_actions']}",
        flush=True,
    )
    spliced = as_actions(built["spliced_actions"])
    save_solution(
        spliced,
        V074_SPLICE_MOVES,
        g=SPLICED_G,
        label="Autonomous v0.74 state-convergence splice (v0.73 prefix + v0.67 suffix)",
    )
    save_solution(
        spliced,
        V074_MOVES,
        g=SPLICED_G,
        label="Autonomous v0.74 state-convergence splice (v0.73 prefix + v0.67 suffix)",
    )
    ck = checkpoints_from_trace(replay_solution_trace(opening, spliced))
    _write_json(
        META,
        {
            "g": SPLICED_G,
            "replay_g": SPLICED_G,
            "replay_ok": True,
            "prefix_source": "v0.73",
            "suffix_source": "v0.67",
            "splice_digest": built["digest"],
            "old_f2_prefix_g": OLD_F2_G,
            "new_f2_prefix_g": NEW_F2_G,
            "inherited_suffix_cost": built["suffix_cost"],
            "canonical_input": False,
            "route_construction": "exact autonomous state convergence",
            "n_actions": len(spliced),
            "deals": sum(1 for a in spliced if is_deal(a)),
            "checkpoints": {
                str(rows): {
                    "g": rec.get("g"),
                    "stock_rows": rec.get("stock_rows"),
                    "foundations": rec.get("foundations"),
                    "face_down": rec.get("face_down"),
                    "ordered_digest": rec.get("ordered_digest"),
                }
                for rows, rec in ck.items()
            },
        },
    )
    _write_json(
        PROG,
        {"phase": "191_promoted", "g": 191, "focused_g": built["focused"]["g"]},
    )

    print(
        f"SEARCH focused stock-empty root_g={built['focused']['g']} ceiling=190 900s",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_focused_endgame(
        opening=opening, focused=built["focused"], progress_path=PROG
    )
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    frontier = []
    for n, rec in sorted(res.foundations_cheap.items()):
        frontier.append(slim_f(rec) | {"F": n})

    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) <= 190
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    if improved:
        save_solution(
            res.solution_actions,
            BEST,
            g=int(res.solution_g),
            label="Autonomous v0.74 focused stock-empty improvement",
        )
        save_solution(
            res.solution_actions,
            V074_MOVES,
            g=int(res.solution_g),
            label="Autonomous v0.74 focused stock-empty solution (prefix v0.73 F2 + independent post-SD5 search)",
        )
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
        )

    print("EVAL canonical after search", flush=True)
    canon_g = replay_actions(opening.clone(), parse_moves_file(CANON))
    v073 = json.loads(V073.read_text(encoding="utf-8")) if V073.exists() else {}
    focused_ep = next(
        (ep for ep in res.epochs if ep.get("stock_rows") is not None and int(ep.get("stock_rows")) == 0),
        {},
    )
    v073_r0 = v073_rows0(v073)
    focused_cmp = {
        "input_roots": focused_ep.get("input_roots"),
        "alloc_s": focused_ep.get("alloc_s"),
        "elapsed_s": focused_ep.get("elapsed_s") or res.elapsed_s,
        "expanded": focused_ep.get("expanded") or res.expanded,
        "generated": focused_ep.get("generated") or res.generated,
        "unique": focused_ep.get("unique") or res.unique,
        "max_foundations": focused_ep.get("max_foundations") or res.max_foundations,
        "lower_bound_prunes": res.lower_bound_prunes,
        "lane_exp": res.lane_exp,
        "min_f": res.min_f,
        "stop_reason": res.stop_reason,
    }
    v073_vs = {"v073_rows0": v073_r0, "focused": focused_cmp}
    causes = []
    if int(v073_r0.get("input_roots") or 0) > 8 and int(focused_cmp.get("input_roots") or 0) <= 2:
        causes.append("256-root dilution")
    v073_t = float(v073_r0.get("alloc_s") or v073_r0.get("elapsed_s") or 0)
    foc_t = float(focused_cmp.get("elapsed_s") or 0)
    if v073_t and foc_t and v073_t < 0.5 * foc_t:
        causes.append("too little stock-empty search time")
    if int(v073_r0.get("input_roots") or 0) >= 64:
        causes.append("transition portfolio competition")
    v073_diagnosis = (
        "v0.73 integrated stock-empty failed to rediscover the 192 suffix because: "
        + (", ".join(causes) if causes else "measured telemetry does not isolate a single cause")
        + f". v0.73 rows=0 used {v073_r0.get('input_roots')} roots in {v073_t:.1f}s "
        f"(expanded={v073_r0.get('expanded')}, maxF={v073_r0.get('max_foundations')}); "
        f"focused used {focused_cmp.get('input_roots')} root(s) in {foc_t:.1f}s "
        f"(expanded={focused_cmp.get('expanded')}, maxF={focused_cmp.get('max_foundations')}, "
        f"min_f={focused_cmp.get('min_f')})."
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "old_192": built["old"],
        "locate": built["locate"],
        "prefix": built["prefix"],
        "replay": built["replay"],
        "suffix_sequence": built.get("suffix_sequence"),
        "digest": built["digest"],
        "suffix_cost": built["suffix_cost"],
        "expected_g": built["expected_g"],
        "spliced_ok": True,
        "split_ok": built.get("split_ok"),
        "n_prefix": built.get("n_prefix"),
        "n_suffix": built.get("n_suffix"),
        "n_spliced": built.get("n_spliced"),
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": AUTONOMOUS_INCUMBENT_MW - 1,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "focused": {k: built["focused"].get(k) for k in built["focused"] if k != "full_actions"},
        "old_post_sd5": built["old_post_sd5"],
        "old_actual_post_sd5": built.get("old_actual_post_sd5"),
        "post_sd5_match": built["post_sd5_match"],
        "actual_post_sd5_same": built.get("actual_post_sd5_same"),
        "inherited_suffix_foundations": foundation_progression(opening, spliced),
        "viability": getattr(res, "viability", None).summary()
        if getattr(res, "viability", None) is not None
        else {},
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "min_f": res.min_f,
        "min_h": res.min_h,
        "max_h": res.max_h,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "foundations": {"cheap": cheap},
        "frontier": frontier,
        "lanes": {"expansions": res.lane_exp, "pops": res.lane_pops},
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
        "checkpoints_191": {
            str(rows): {
                "g": rec.get("g"),
                "stock_rows": rec.get("stock_rows"),
                "foundations": rec.get("foundations"),
                "face_down": rec.get("face_down"),
                "ordered_digest": rec.get("ordered_digest"),
            }
            for rows, rec in ck.items()
        },
        "v073_vs_focused": v073_vs,
        "v073_diagnosis": v073_diagnosis,
        "canonical_eval_g": canon_g,
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "ceiling": 190,
            "root_g": FOCUSED_ROOT_G,
        },
    }
    if improved:
        payload["improved_file"] = str(BEST.relative_to(ROOT)).replace("\\", "/")
        payload["solution_actions"] = [
            list(a) if a != ("deal",) else ["deal"] for a in res.solution_actions
        ]
    verdict, reason = choose_convergence_verdict(payload)
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
            "spliced_g": 191,
            "solution_g": payload.get("solution_g"),
            "max_foundations": payload.get("max_foundations"),
            "min_f": payload.get("min_f"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
