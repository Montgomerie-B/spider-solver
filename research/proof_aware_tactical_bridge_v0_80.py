#!/usr/bin/env python3
"""v0.80: proof-aware F3→F4 tactical bridge from the g141 state.

Canonical 172 is evaluation-only after freeze. Not a whole-game campaign.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    assembly_slack,
    evaluate_187_f3_f4,
    recover_g141,
    verify_g141_root,
)
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.proof_aware_tactical_bridge import (
    STAGE_A_S,
    STAGE_B_N,
    TACTICAL_BUDGET_S,
    TOTAL_S,
    choose_proof_aware_verdict,
    run_proof_aware_bridge,
    search_f4_portfolio,
)
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "proof_aware_tactical_bridge_v0_80"
BASE_SHA = "a1018792fd9e263ee9217aa99b61f0330b2216f8"
BRANCH = "agent/proof-aware-tactical-bridge-v0-80"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "proof_aware_tactical_bridge_progress_v0_80.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_80.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_80.json"


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


def slim_term(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "face_down", "empty_n", "assembly_h", "assembly_f", "slack",
        "legal_tableau", "boundaries", "tactical_target", "operational_rank", "class",
        "viable", "delta_g", "delta_h", "delta_f", "assembly_payback", "n_actions",
        "ordered_digest",
    )}


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "already_founded", "elapsed_s", "unique",
        "expanded", "generated", "stop_reason", "lane_exp", "lane_names", "proof_prunes",
        "proof_calls", "h_cache", "min_cover", "min_blockers", "best_k_access",
        "best_a_access", "raw_count", "viable_count", "first_raw_g", "first_raw_f",
        "first_raw_s", "cheapest_raw_g", "best_raw_f", "first_viable_g", "first_viable_s",
        "cheapest_viable_g", "best_viable_f", "min_h_raw", "min_f_raw", "min_h_viable",
        "min_f_viable", "max_slack", "economics_cheapest_raw", "economics_cheapest_viable",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["raw_terminals"] = [slim_term(t) for t in (pr.get("raw_terminals") or [])[:8]]
    rec["viable_terminals"] = [slim_term(t) for t in (pr.get("viable_terminals") or [])[:8]]
    return rec


def write_report(p: dict) -> None:
    br = p.get("bridge") or {}
    g141 = p.get("g141") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Proof-aware stock-empty tactical bridge from unpacked g141. "
        "Canonical 172 was not a search input. Incumbent remains 187 unless improved.",
        "",
        f"Slack convention: `ceiling - f`. F3 slack = {p.get('slack_f3')}.",
        "",
        "## g141",
        "",
        f"ok={g141.get('ok')} g={g141.get('g')} F={g141.get('foundations')} h={g141.get('assembly_h')} "
        f"f={g141.get('assembly_f')} slack={g141.get('slack')} ready={g141.get('ready_suits')}",
        "",
        "## Stage A",
        "",
        "| rank | suit | raw | viable | cheap raw g/f | cheap viable g/f | prunes | unique | t s |",
        "| ---: | --- | ---: | ---: | --- | --- | ---: | ---: | ---: |",
    ]
    for pr in br.get("stage_a") or []:
        lines.append(
            f"| {pr.get('operational_rank')} | {pr.get('suit')} | {pr.get('raw_count')} | "
            f"{pr.get('viable_count')} | {pr.get('cheapest_raw_g')}/{pr.get('best_raw_f')} | "
            f"{pr.get('cheapest_viable_g')}/{pr.get('best_viable_f')} | {pr.get('proof_prunes')} | "
            f"{pr.get('unique')} | {_fmt(pr.get('elapsed_s'))} |"
        )
    lines += [
        "",
        f"Stage B promoted: {br.get('promoted_suits')}",
        "",
        str([(pr.get("suit"), pr.get("viable_count"), pr.get("cheapest_viable_g")) for pr in br.get("stage_b") or []]),
        "",
        f"Tactical { _fmt(br.get('elapsed_s')) }s / budget {TACTICAL_BUDGET_S}. "
        f"h-cache calls={br.get('h_cache_calls')} hits={br.get('h_cache_hits')} prunes={br.get('proof_prunes')}.",
        f"Viable portfolio n={br.get('n_viable')} raw n={br.get('n_raw')}.",
        "",
        "## Continuation",
        "",
        f"maxF={p.get('max_foundations')} unique={p.get('unique')} exp={p.get('expanded')} "
        f"stop=`{p.get('stop_reason')}` solution_g={p.get('solution_g')}",
        "",
        "## Frontiers",
        "",
        "raw: " + str(p.get("raw_frontier") or []),
        "viable: " + str(p.get("viable_frontier") or []),
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
    if verdict == "PROOF_AWARE_BRIDGE_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "PROOF_AWARE_BRIDGE_FINDS_VIABLE_F4":
        return "Repeat hierarchical decomposition from the viable F4, not from dead states."
    if verdict == "PROOF_AWARE_BRIDGE_DEEP_ENDGAME":
        return "Continue hierarchical decomposition from the viable F4/F5, targeting remaining slack."
    if verdict == "PROOF_AWARE_BRIDGE_ONLY_DEAD_F4":
        return "Do not search onward from proof-dead F4s; analyse F3→F4 cost vs assembly reduction on the g128 branch."
    if verdict == "PROOF_AWARE_BRIDGE_SEARCH_LIMITED":
        return "Keep proof-aware targeting; do not add wall time."
    if verdict == "PROOF_AWARE_BRIDGE_NO_F4":
        return "The g141 branch may be an F3 trap; do not return to pre-Deal heuristics yet."
    return "Do not promote; diagnose the contract."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "PROOF_AWARE_BRIDGE_CONTRACT_FAILURE"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT PROOF_AWARE_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("LOAD g141", flush=True)
    g141 = verify_g141_root()
    print(
        f"G141 ok={g141.get('ok')} slack={g141.get('slack')} ready={g141.get('ready_suits')}",
        flush=True,
    )
    if not g141.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "PROOF_AWARE_BRIDGE_CONTRACT_FAILURE",
            "g141": g141,
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT PROOF_AWARE_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    _write_json(PROG, {"phase": "stage_a", "ready": g141.get("ready_suits")})
    f3 = {"g": 141, "ordered_digest": g141["ordered_digest"], "full_actions": []}
    print(f"BRIDGE proof-aware Stage A {len(g141.get('ready_suits') or [])} x {STAGE_A_S}s", flush=True)
    bridge = run_proof_aware_bridge(f3)
    print(
        f"BRIDGE viable={bridge.get('n_viable')} raw={bridge.get('n_raw')} "
        f"promoted={bridge.get('promoted_suits')} t={bridge.get('elapsed_s'):.1f}s "
        f"prunes={bridge.get('proof_prunes')}",
        flush=True,
    )

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if bridge.get("any_viable") and remain >= 5.0:
        print(f"CONTINUE viable F4 n={bridge['n_viable']} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "continuation", "n_viable": bridge.get("n_viable")})
        cont = search_f4_portfolio(opening, bridge["f4_roots"], time_s=remain, unique=SEARCH_UNIQUE)
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations}",
            flush=True,
        )
    else:
        print("NO viable F4: skip global continuation from proof-dead roots", flush=True)

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        print("PROVENANCE recover g141 after candidate", flush=True)
        root = reconstruct_g128_root(opening)
        provenance = recover_g141(opening, root["post"]) if root.get("ok") else {"ok": False}
        if provenance.get("ok"):
            full = as_actions(provenance["hit"]["full_actions"]) + as_actions(cont.solution_actions)
            end = opening.clone()
            replay_g = replay_actions(end, list(full))
            replay_ok = replay_g == int(cont.solution_g) and end.is_solved() and sum(1 for a in full if is_deal(a)) == 5
            if replay_ok:
                save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.80 proof-aware bridge")
                terminal_lineage = foundation_progression(opening, list(full))
                _write_json(META, {"g": int(cont.solution_g), "replay_ok": True, "canonical_input": False, "parent_incumbent": 187})
                improved = True

    tracker = getattr(cont, "snapshot_tracker", None) if cont is not None else None
    raw_front = [{"F": 3, "g": 141, "h": 33, "f": 174, "slack": 12, "raw_or_viable": "viable", "time": 0}]
    viable_front = [dict(raw_front[0])]
    for pr in (bridge.get("stage_a") or []) + (bridge.get("stage_b") or []):
        for rec in (pr.get("raw_terminals") or [])[:1]:
            raw_front.append({
                "F": rec.get("foundations"), "g": rec.get("g"), "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"), "slack": rec.get("slack"),
                "target": rec.get("tactical_target"), "raw_or_viable": rec.get("class"),
                "time": pr.get("first_raw_s"),
            })
        for rec in (pr.get("viable_terminals") or [])[:1]:
            viable_front.append({
                "F": rec.get("foundations"), "g": rec.get("g"), "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"), "slack": rec.get("slack"),
                "target": rec.get("tactical_target"), "raw_or_viable": "viable",
                "time": pr.get("first_viable_s"),
            })
    max_f = 3
    if bridge.get("n_raw"):
        max_f = max(max_f, max((int(r.get("foundations") or 4) for r in (bridge.get("stage_a") or [{}])[0:1] for r in ((bridge.get("stage_a") or [{}])[0].get("raw_terminals") or [{"foundations": 3}])), default=3))
    for pr in (bridge.get("stage_a") or []) + (bridge.get("stage_b") or []):
        for rec in (pr.get("raw_terminals") or []):
            max_f = max(max_f, int(rec.get("foundations") or 0))
        for rec in (pr.get("viable_terminals") or []):
            max_f = max(max_f, int(rec.get("foundations") or 0))
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "slack_convention": "ceiling - f",
        "slack_f3": assembly_slack(186, 174),
        "wall_s": time.perf_counter() - wall0,
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "stop_reason": None if cont is None else cont.stop_reason,
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(cont, "accounting_fail", False)) if cont is not None else False,
        "g141": {k: v for k, v in g141.items() if k not in ("record", "state")},
        "bridge": {
            "inspect": bridge.get("inspect"),
            "stage_a": [slim_probe(pr) for pr in bridge.get("stage_a") or []],
            "stage_b": [slim_probe(pr) for pr in bridge.get("stage_b") or []],
            "promoted_suits": bridge.get("promoted_suits"),
            "elapsed_s": bridge.get("elapsed_s"),
            "stage_a_s": bridge.get("stage_a_s"),
            "stage_b_s": bridge.get("stage_b_s"),
            "budget_s": TACTICAL_BUDGET_S,
            "n_viable": bridge.get("n_viable"),
            "n_raw": bridge.get("n_raw"),
            "any_viable": bridge.get("any_viable"),
            "cheapest_raw_g": bridge.get("cheapest_raw_g"),
            "cheapest_viable_g": bridge.get("cheapest_viable_g"),
            "best_viable_f": bridge.get("best_viable_f"),
            "h_cache_calls": bridge.get("h_cache_calls"),
            "h_cache_hits": bridge.get("h_cache_hits"),
            "proof_prunes": bridge.get("proof_prunes"),
            "f4_roots": [slim_term(r) for r in bridge.get("f4_roots") or []],
        },
        "raw_frontier": raw_front,
        "viable_frontier": viable_front,
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "bound_perf": None if cont is None else {
            "prunes": cont.lower_bound_prunes,
            "calls": cont.lower_bound_calls,
        },
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "v079_compare": {
            "tactical_lower_bound": False,
            "future_cost_lane": False,
            "raw_F4": True,
            "viable_F4": False,
            "raw_F5": True,
            "viable_F5": False,
            "tactical_unique": "~75k",
            "global_roots": "16 dead",
        },
        "envelope": {"time_s": TOTAL_S, "tactical_budget_s": TACTICAL_BUDGET_S, "stage_a_s": STAGE_A_S, "stage_b_n": STAGE_B_N, "ceiling": BRIDGE_CEILING, "rss_abort_mb": SEARCH_RSS_MB},
    }
    verdict, reason = choose_proof_aware_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    _write_json(RESULT, _jsonable({k: v for k, v in payload.items() if k != "eval_187"}))
    write_report(_jsonable(payload))
    print("machine experiment frozen", flush=True)
    print("EVAL 187 F3→F4 after freeze", flush=True)
    payload["eval_187"] = evaluate_187_f3_f4(opening)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "n_viable": bridge.get("n_viable"), "n_raw": bridge.get("n_raw")})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
