#!/usr/bin/env python3
"""v0.81: proof-aware F3→F4 tactical bridge from the more-assembled g158 F3.

Canonical 172 is evaluation-only after freeze. Not a whole-game campaign.
Does not resume the exhausted g161/g162 F4 roots.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_tactical_bridge import BRIDGE_CEILING, assembly_slack
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.proof_aware_tactical_bridge import (
    COMPLETE_EXHAUSTION_NOTE,
    STAGE_A_S,
    STAGE_B_N,
    TACTICAL_BUDGET_S,
    TOTAL_S,
    choose_g158_verdict,
    f3_as_continuation_root,
    interpret_continuation_stop,
    recover_g158,
    run_proof_aware_bridge,
    search_f4_portfolio,
    verify_g158_root,
)
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "g158_proof_aware_f4_v0_81"
BASE_SHA = "96c8d77e591bc45376dd82aa3e17c89a68825e4b"
BRANCH = "agent/g158-proof-aware-f4-v0-81"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "g158_proof_aware_f4_progress_v0_81.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_81.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_81.json"
V080 = ROOT / "docs" / "research" / "proof_aware_tactical_bridge_v0_80.json"


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
        "viable", "surplus", "delta_g", "delta_h", "delta_f", "assembly_payback",
        "n_actions", "ordered_digest",
    )}


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "already_founded", "cover", "blockers",
        "inaccessible_joins", "k_access", "a_access", "gap", "merge_edges",
        "buried_components", "exposed_components", "elapsed_s", "unique",
        "expanded", "generated", "stop_reason", "lane_exp", "lane_names", "proof_prunes",
        "proof_calls", "h_cache", "min_cover", "min_blockers", "best_k_access",
        "best_a_access", "raw_count", "viable_count", "surplus_count", "first_raw_g",
        "first_raw_f", "first_raw_s", "cheapest_raw_g", "best_raw_f", "first_viable_g",
        "first_viable_s", "cheapest_viable_g", "best_viable_f", "min_h_raw", "min_f_raw",
        "min_h_viable", "min_f_viable", "max_slack", "max_viable_slack",
        "max_mobility_viable", "best_surplus_f", "economics_cheapest_raw",
        "economics_cheapest_viable", "peak_rss_mb", "stage_a_budget_s", "stage_a_unique",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["raw_terminals"] = [slim_term(t) for t in (pr.get("raw_terminals") or [])[:8]]
    rec["viable_terminals"] = [slim_term(t) for t in (pr.get("viable_terminals") or [])[:8]]
    rec["surplus_terminals"] = [slim_term(t) for t in (pr.get("surplus_terminals") or [])[:8]]
    return rec


def load_g141_benchmark() -> dict:
    if not V080.exists():
        return {
            "root_g": 141,
            "root_h": 33,
            "root_f": 174,
            "slack": 12,
            "best_viable_f": 186,
            "best_slack": 0,
            "cheapest_viable_g": 161,
            "lowest_h_viable": 24,
            "continuation_stop": "complete",
            "continuation_unique": 190,
            "continuation_expanded": 12,
            "proof_prunes": 181,
            "max_F": 4,
            "terminal": False,
            "source": "hardcoded_v080_summary",
        }
    data = json.loads(V080.read_text(encoding="utf-8"))
    br = data.get("bridge") or {}
    roots = br.get("f4_roots") or []
    return {
        "root_g": 141,
        "root_h": 33,
        "root_f": 174,
        "slack": 12,
        "empties": 2,
        "legal": 41,
        "best_viable_f": br.get("best_viable_f"),
        "best_slack": 0 if roots else None,
        "cheapest_viable_g": br.get("cheapest_viable_g"),
        "lowest_h_viable": None if not roots else min(int(r.get("assembly_h") or 10**9) for r in roots),
        "viable_f4": [slim_term(r) for r in roots],
        "continuation_stop": data.get("stop_reason"),
        "continuation_unique": data.get("unique"),
        "continuation_expanded": data.get("expanded"),
        "proof_prunes": (data.get("bound_perf") or {}).get("prunes"),
        "max_F": data.get("max_foundations"),
        "terminal": bool(data.get("solved")),
        "source": "docs/research/proof_aware_tactical_bridge_v0_80.json",
    }


def next_recommendation(verdict: str, exhausted: bool = False) -> str:
    if verdict == "G158_BRIDGE_COST_IMPROVED":
        return "Promote the new incumbent."
    if verdict == "G158_BRIDGE_FINDS_SURPLUS_F4":
        if exhausted:
            return (
                "Do not rerun global continuation from these exact roots. "
                "Start the next hierarchical tactical cash-out from a surplus F4 (f<=185)."
            )
        return "Continue hierarchical decomposition from the positive-slack F4, not from zero-slack ridges."
    if verdict == "G158_BRIDGE_DEEP_ENDGAME":
        if exhausted:
            return (
                "Do not rerun global continuation from these exact F4/F5 roots; "
                "the proof-viable subgraph is exhausted. Next hierarchical step is a "
                "proof-aware tactical cash-out from a surplus F5 (f<=185), preserving "
                "assembled F3 quality rather than cheapest-F3 g."
            )
        return "Continue hierarchical decomposition from the viable F4/F5, targeting remaining slack."
    if verdict == "G158_BRIDGE_F4_EXHAUSTED":
        return "Do not continue from these exact F4 roots; move to another F3 quality representative."
    if verdict == "G158_BRIDGE_FINDS_VIABLE_F4":
        return "If continuation was resource-limited, resume from the best viable F4; do not return to g161/g162."
    if verdict == "G158_BRIDGE_NO_VIABLE_F4":
        return "Harvest a quality-diverse F3 portfolio rather than optimising for one F3 notion."
    if verdict == "G158_BRIDGE_SEARCH_LIMITED":
        return "Keep proof-aware targeting; do not add wall time."
    return "Do not promote; diagnose the contract."


def frontier_rows(items: list) -> list:
    lines = [
        "| F |  g |  h |  f | slack | target | provenance | time |",
        "| - | -: | -: | -: | ----: | ------ | ---------- | ---: |",
    ]
    for rec in items:
        lines.append(
            f"| {rec.get('F')} | {rec.get('g')} | {rec.get('h')} | {rec.get('f')} | "
            f"{rec.get('slack')} | {rec.get('target') or ''} | {rec.get('provenance') or rec.get('raw_or_viable')} | "
            f"{_fmt(rec.get('time'))} |"
        )
    if len(items) == 0:
        lines.append("| — | — | — | — | — | — | — | — |")
    return lines


def write_report(p: dict) -> None:
    br = p.get("bridge") or {}
    g158 = p.get("g158") or {}
    g141 = p.get("g141_benchmark") or {}
    interp = p.get("continuation_interpretation") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Proof-aware stock-empty tactical bridge from the more-assembled g158 F3. "
        "Canonical 172 was not a search input. The exhausted g161/g162 F4 roots were not reused.",
        "",
        f"Slack convention: `ceiling - f`. F3 slack = {p.get('slack_f3')}.",
        "",
        "## g158 root verification",
        "",
        f"ok={g158.get('ok')} g={g158.get('g')} F={g158.get('foundations')} "
        f"h={g158.get('assembly_h')} f={g158.get('assembly_f')} slack={g158.get('slack')} "
        f"fd={g158.get('face_down')} empties={g158.get('empty_n')} legal={g158.get('legal_tableau')} "
        f"boundaries_recorded={g158.get('boundaries_recorded')} visible_runs={g158.get('boundaries')} "
        f"stock_rows={g158.get('stock_rows')} can_deal={g158.get('can_deal')} "
        f"discovery_s={_fmt(g158.get('discovery_elapsed_s'), 3)}",
        "",
        f"Provenance: {g158.get('provenance')}",
        "",
        "## Foundation / target ranking at g158",
        "",
        f"ready={g158.get('ready_suits')} n_ready={g158.get('n_ready')} "
        f"best={g158.get('best_suit')} second={g158.get('second_suit')}",
        "",
        "| rank | suit | founded | cover | blockers | inacc joins | K | A | gap | merges | buried | exposed |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for tgt in g158.get("remaining_targets") or []:
        lines.append(
            f"| {tgt.get('operational_rank')} | {tgt.get('suit')} | {tgt.get('already_founded')} | "
            f"{tgt.get('cover')} | {tgt.get('blockers')} | {tgt.get('inaccessible_joins')} | "
            f"{tgt.get('k_access')} | {tgt.get('a_access')} | {tgt.get('gap')} | "
            f"{tgt.get('merge_edges')} | {tgt.get('buried_components')} | {tgt.get('exposed_components')} |"
        )
    lines += [
        "",
        "## Stage A (equal target probes)",
        "",
        "| rank | suit | raw | viable | surplus | cheap raw g/f | cheap viable g/f | slack | prunes | unique | t s |",
        "| ---: | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for pr in br.get("stage_a") or []:
        lines.append(
            f"| {pr.get('operational_rank')} | {pr.get('suit')} | {pr.get('raw_count')} | "
            f"{pr.get('viable_count')} | {pr.get('surplus_count')} | "
            f"{pr.get('cheapest_raw_g')}/{pr.get('best_raw_f')} | "
            f"{pr.get('cheapest_viable_g')}/{pr.get('best_viable_f')} | {pr.get('max_viable_slack')} | "
            f"{pr.get('proof_prunes')} | {pr.get('unique')} | {_fmt(pr.get('elapsed_s'))} |"
        )
    lines += [
        "",
        f"Stage B promoted: {br.get('promoted_suits')}",
        "",
        str([
            {
                "suit": pr.get("suit"),
                "viable": pr.get("viable_count"),
                "surplus": pr.get("surplus_count"),
                "cheap_g": pr.get("cheapest_viable_g"),
                "best_f": pr.get("best_viable_f"),
            }
            for pr in br.get("stage_b") or []
        ]),
        "",
        f"Tactical {_fmt(br.get('elapsed_s'))}s / budget {TACTICAL_BUDGET_S}. "
        f"h-cache calls={br.get('h_cache_calls')} hits={br.get('h_cache_hits')} "
        f"misses={br.get('h_cache_misses')} s={_fmt(br.get('h_cache_seconds'), 2)}. "
        f"proof calls={br.get('proof_calls')} prunes={br.get('proof_prunes')}.",
        f"Raw={br.get('n_raw')} viable portfolio={br.get('n_viable')} surplus unique={br.get('n_surplus')}.",
        f"best f={br.get('best_viable_f')} best slack={br.get('best_slack')} "
        f"cheapest g={br.get('cheapest_viable_g')} lowest h={br.get('lowest_h_viable')}.",
        "",
        "## F4 economics vs g158/h22/f180",
        "",
        "| g | h | f | slack | Δg | Δh | Δf | payback | class | target |",
        "| -: | -: | -: | ----: | -: | -: | -: | ---: | --- | --- |",
    ]
    for rec in br.get("f4_roots") or []:
        lines.append(
            f"| {rec.get('g')} | {rec.get('assembly_h')} | {rec.get('assembly_f')} | {rec.get('slack')} | "
            f"{rec.get('delta_g')} | {rec.get('delta_h')} | {rec.get('delta_f')} | "
            f"{_fmt(rec.get('assembly_payback'), 2)} | {rec.get('class')} | {rec.get('tactical_target')} |"
        )
    if not br.get("f4_roots"):
        lines.append("| — | — | — | — | — | — | — | — | — | — |")
    lines += [
        "",
        "## Continuation",
        "",
        f"mode={p.get('continuation_mode')} maxF={p.get('max_foundations')} unique={p.get('unique')} "
        f"exp={p.get('expanded')} generated={p.get('generated')} stop=`{p.get('stop_reason')}` "
        f"solution_g={p.get('solution_g')}",
        "",
        f"exhausted={interp.get('exhausted')} resource_limited={interp.get('resource_limited')} "
        f"recommend_continue_from_these_roots={interp.get('recommend_continue_from_these_roots')}",
        "",
        interp.get("note") or "",
        "",
        "## g141 vs g158",
        "",
        "| field | g141 cheapest F3 | g158 assembled F3 |",
        "| --- | ---: | ---: |",
        f"| root g/h/f | {g141.get('root_g')}/{g141.get('root_h')}/{g141.get('root_f')} | "
        f"{g158.get('g')}/{g158.get('assembly_h')}/{g158.get('assembly_f')} |",
        f"| root slack | {g141.get('slack')} | {g158.get('slack')} |",
        f"| best F4 f | {g141.get('best_viable_f')} | {br.get('best_viable_f')} |",
        f"| best slack | {g141.get('best_slack')} | {br.get('best_slack')} |",
        f"| cheapest F4 g | {g141.get('cheapest_viable_g')} | {br.get('cheapest_viable_g')} |",
        f"| lowest F4 h | {g141.get('lowest_h_viable')} | {br.get('lowest_h_viable')} |",
        f"| continuation stop | {g141.get('continuation_stop')} | {p.get('stop_reason')} |",
        f"| exhausted | yes | {interp.get('exhausted')} |",
        "",
        "## Raw F3–F8 frontier",
        "",
    ]
    lines += frontier_rows(p.get("raw_frontier") or [])
    lines += [
        "",
        "## Proof-viable F3–F8 frontier",
        "",
    ]
    lines += frontier_rows(p.get("viable_frontier") or [])
    lines += [
        "",
        "## Search accounting",
        "",
        f"wall_s={_fmt(p.get('wall_s'))} tactical_s={_fmt(br.get('elapsed_s'))} "
        f"continuation_s={_fmt(p.get('elapsed_s'))} peak_rss_mb={_fmt(p.get('peak_rss_mb'))}",
        f"tactical unique/exp/gen={br.get('tactical_unique')}/{br.get('tactical_expanded')}/{br.get('tactical_generated')}",
        f"continuation unique/exp/gen={p.get('unique')}/{p.get('expanded')}/{p.get('generated')}",
        f"bound prunes/calls={(p.get('bound_perf') or {}).get('prunes')}/{(p.get('bound_perf') or {}).get('calls')}",
        "",
        f"Incumbent remains {p.get('incumbent_g')}. RECORD_MW={p.get('record_mw')} "
        f"CANONICAL_MW={p.get('canonical_mw')} incumbent_updated={p.get('incumbent_updated')}.",
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
    g141_bench = load_g141_benchmark()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "G158_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": "incumbent 187 replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT G158_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("LOAD g158 from v0.78 cheap_F", flush=True)
    g158 = verify_g158_root()
    print(
        f"G158 ok={g158.get('ok')} slack={g158.get('slack')} ready={g158.get('ready_suits')} "
        f"h={g158.get('assembly_h')} f={g158.get('assembly_f')} empties={g158.get('empty_n')} "
        f"legal={g158.get('legal_tableau')}",
        flush=True,
    )
    if not g158.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "G158_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": g158.get("reason") or "G158_F3_BRIDGE_CONTRACT_FAILURE",
            "g158": {k: v for k, v in g158.items() if k not in ("record", "state")},
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT G158_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    _write_json(PROG, {"phase": "stage_a", "ready": g158.get("ready_suits"), "g": 158})
    f3 = {"g": 158, "ordered_digest": g158["ordered_digest"], "full_actions": []}
    print(f"BRIDGE proof-aware Stage A {len(g158.get('ready_suits') or [])} x {STAGE_A_S}s", flush=True)
    bridge = run_proof_aware_bridge(f3, ceiling=BRIDGE_CEILING)
    print(
        f"BRIDGE viable={bridge.get('n_viable')} raw={bridge.get('n_raw')} surplus={bridge.get('n_surplus')} "
        f"promoted={bridge.get('promoted_suits')} t={bridge.get('elapsed_s'):.1f}s "
        f"best_f={bridge.get('best_viable_f')} slack={bridge.get('best_slack')} "
        f"prunes={bridge.get('proof_prunes')}",
        flush=True,
    )

    cont = None
    continuation_mode = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if bridge.get("any_viable") and remain >= 5.0:
        continuation_mode = "viable_f4"
        print(f"CONTINUE viable F4 n={bridge['n_viable']} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "continuation", "n_viable": bridge.get("n_viable"), "mode": continuation_mode})
        cont = search_f4_portfolio(opening, bridge["f4_roots"], time_s=remain, unique=SEARCH_UNIQUE)
    elif remain >= 5.0:
        continuation_mode = "f3_fallback"
        print(f"NO viable F4: frozen global continuation from g158 F3 t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "fallback_f3", "mode": continuation_mode})
        cont = search_f4_portfolio(opening, [f3_as_continuation_root(g158)], time_s=remain, unique=SEARCH_UNIQUE)
    else:
        print("NO remaining wall for continuation", flush=True)

    if cont is not None:
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations}",
            flush=True,
        )

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    provenance = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        print("PROVENANCE recover g158 after candidate", flush=True)
        provenance = recover_g158(opening)
        if provenance.get("ok"):
            full = as_actions(provenance["hit"]["full_actions"]) + as_actions(cont.solution_actions)
            end = opening.clone()
            replay_g = replay_actions(end, list(full))
            replay_ok = (
                replay_g == int(cont.solution_g)
                and end.is_solved()
                and sum(1 for a in full if is_deal(a)) == 5
                and len(end.foundations) == 8
                and not end.stock
                and all(c.is_empty() for c in end.columns)
            )
            if replay_ok:
                save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.81 g158 proof-aware bridge")
                terminal_lineage = foundation_progression(opening, list(full))
                _write_json(
                    META,
                    {
                        "g": int(cont.solution_g),
                        "replay_ok": True,
                        "canonical_input": False,
                        "parent_incumbent": 187,
                        "lineage": "g128 autonomous → g158 F3 → v0.81 tactical bridge",
                        "f3_root": {"g": 158, "h": 22, "f": 180, "slack": 6},
                        "f4_best": {
                            "g": bridge.get("cheapest_viable_g"),
                            "h": bridge.get("lowest_h_viable"),
                            "f": bridge.get("best_viable_f"),
                            "slack": bridge.get("best_slack"),
                        },
                        "continuation_stop": cont.stop_reason,
                    },
                )
                improved = True

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)

    raw_front = [{
        "F": 3, "g": 158, "h": 22, "f": 180, "slack": 6,
        "target": None, "provenance": "v078_first_f3", "raw_or_viable": "viable", "time": g158.get("discovery_elapsed_s"),
    }]
    viable_front = [dict(raw_front[0])]
    for pr in (bridge.get("stage_a") or []) + (bridge.get("stage_b") or []):
        for rec in (pr.get("raw_terminals") or [])[:1]:
            raw_front.append({
                "F": rec.get("foundations"), "g": rec.get("g"), "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"), "slack": rec.get("slack"),
                "target": rec.get("tactical_target"), "provenance": rec.get("class"),
                "raw_or_viable": rec.get("class"), "time": pr.get("first_raw_s"),
            })
        for rec in (pr.get("viable_terminals") or [])[:1]:
            viable_front.append({
                "F": rec.get("foundations"), "g": rec.get("g"), "h": rec.get("assembly_h"),
                "f": rec.get("assembly_f"), "slack": rec.get("slack"),
                "target": rec.get("tactical_target"), "provenance": "viable",
                "raw_or_viable": "viable", "time": pr.get("first_viable_s"),
            })
    max_f = 3
    for pr in (bridge.get("stage_a") or []) + (bridge.get("stage_b") or []):
        for rec in (pr.get("raw_terminals") or []) + (pr.get("viable_terminals") or []):
            max_f = max(max_f, int(rec.get("foundations") or 0))
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))

    peak = br_peak = bridge.get("peak_rss_mb") or 0
    if cont is not None:
        peak = max(float(peak or 0), float(getattr(cont, "peak_rss_mb", 0) or 0))

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
        "slack_f3": assembly_slack(186, 180),
        "wall_s": time.perf_counter() - wall0,
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "generated": None if cont is None else getattr(cont, "generated", None),
        "stop_reason": stop_reason,
        "continuation_mode": continuation_mode,
        "continuation_interpretation": interp,
        "roots_exhausted": bool(interp.get("exhausted")),
        "recommend_continue_from_these_roots": interp.get("recommend_continue_from_these_roots"),
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(cont, "accounting_fail", False)) if cont is not None else False,
        "g158": {k: v for k, v in g158.items() if k not in ("record", "state")},
        "g141_benchmark": g141_bench,
        "bridge": {
            "inspect": bridge.get("inspect"),
            "root_g": bridge.get("root_g"),
            "root_h": bridge.get("root_h"),
            "root_f": bridge.get("root_f"),
            "root_slack": bridge.get("root_slack"),
            "stage_a": [slim_probe(pr) for pr in bridge.get("stage_a") or []],
            "stage_b": [slim_probe(pr) for pr in bridge.get("stage_b") or []],
            "promoted_suits": bridge.get("promoted_suits"),
            "elapsed_s": bridge.get("elapsed_s"),
            "stage_a_s": bridge.get("stage_a_s"),
            "stage_b_s": bridge.get("stage_b_s"),
            "budget_s": TACTICAL_BUDGET_S,
            "n_viable": bridge.get("n_viable"),
            "n_raw": bridge.get("n_raw"),
            "n_surplus": bridge.get("n_surplus"),
            "any_viable": bridge.get("any_viable"),
            "cheapest_raw_g": bridge.get("cheapest_raw_g"),
            "cheapest_viable_g": bridge.get("cheapest_viable_g"),
            "best_viable_f": bridge.get("best_viable_f"),
            "lowest_h_viable": bridge.get("lowest_h_viable"),
            "best_slack": bridge.get("best_slack"),
            "best_surplus_f": bridge.get("best_surplus_f"),
            "h_cache_calls": bridge.get("h_cache_calls"),
            "h_cache_hits": bridge.get("h_cache_hits"),
            "h_cache_misses": bridge.get("h_cache_misses"),
            "h_cache_seconds": bridge.get("h_cache_seconds"),
            "proof_prunes": bridge.get("proof_prunes"),
            "proof_calls": bridge.get("proof_calls"),
            "tactical_unique": bridge.get("tactical_unique"),
            "tactical_expanded": bridge.get("tactical_expanded"),
            "tactical_generated": bridge.get("tactical_generated"),
            "peak_rss_mb": br_peak,
            "f4_roots": [slim_term(r) for r in bridge.get("f4_roots") or []],
            "surplus_terminals": [slim_term(r) for r in bridge.get("surplus_terminals") or []],
        },
        "raw_frontier": raw_front,
        "viable_frontier": viable_front,
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "bound_perf": None if cont is None else {
            "prunes": cont.lower_bound_prunes,
            "calls": cont.lower_bound_calls,
        },
        "peak_rss_mb": peak,
        "terminal_lineage": terminal_lineage,
        "provenance_recovery": None if provenance is None else {
            k: provenance.get(k) for k in ("ok", "reason", "elapsed_s", "unique", "stop_reason", "replay_g")
        },
        "incumbent_updated": improved,
        "envelope": {
            "time_s": TOTAL_S,
            "tactical_budget_s": TACTICAL_BUDGET_S,
            "stage_a_s": STAGE_A_S,
            "stage_b_n": STAGE_B_N,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
        "closed_g161_g162": True,
    }
    verdict, reason = choose_g158_verdict(payload)
    if verdict == "G158_BRIDGE_F4_EXHAUSTED":
        interpretation = COMPLETE_EXHAUSTION_NOTE + " Do not search onward from these exact F4 roots."
    elif verdict == "G158_BRIDGE_DEEP_ENDGAME":
        interpretation = (
            "g158 produced surplus F4/F5 at f=185 (slack +1) and continuation reached F5. "
            "That outperforms the g141 zero-slack F4 ridge (f=186, maxF=4). "
            + (COMPLETE_EXHAUSTION_NOTE if interp.get("exhausted") else "")
        )
    elif verdict == "G158_BRIDGE_FINDS_SURPLUS_F4":
        interpretation = (
            "g158 produced a positive-slack F4 (f<=185), a materially stronger result than the g141 ridge."
        )
    elif verdict == "G158_BRIDGE_NO_VIABLE_F4":
        interpretation = (
            "Both the cheapest g141 F3 and the cleaner g158 F3 failed to yield a proof-viable F4 under 186."
        )
    elif verdict == "G158_BRIDGE_FINDS_VIABLE_F4":
        interpretation = (
            "g158 reached a viable F4. Compare remaining slack and Δf against the g141 f=186 ridge."
        )
    else:
        interpretation = reason
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict, bool(interp.get("exhausted")))
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "n_viable": bridge.get("n_viable"),
            "n_raw": bridge.get("n_raw"),
            "n_surplus": bridge.get("n_surplus"),
            "stop_reason": stop_reason,
            "exhausted": interp.get("exhausted"),
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
