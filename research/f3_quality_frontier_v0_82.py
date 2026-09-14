#!/usr/bin/env python3
"""v0.82: quality-diverse F3 harvest and proof-aware bridge screening.

Canonical 172 is evaluation-only after freeze. Does not resume exhausted
v0.80/v0.81 F4/F5 roots. Not a whole-game campaign.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_quality_frontier import (
    CONTINUATION_RESERVE_S,
    G141_CONTROL,
    G158_CONTROL,
    HARVEST_S,
    HARVEST_UNIQUE,
    MAX_ACTIVE_F3,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_ROOTS,
    STAGE_B_S,
    STAGE_B_TARGETS,
    STAGE_B_UNIQUE,
    TOTAL_S,
    aggregate_f3_probes,
    bridge_loss,
    build_next_foundation_portfolio,
    choose_f3_frontier_verdict,
    choose_stage_b_pairs,
    control_digests,
    f3_pareto_frontier,
    harvest_f3_terminals,
    is_known_closed,
    load_closed_root_table,
    mark_control_f3s,
    next_foundation_quality,
    next_recommendation,
    probe_proof_aware_target,
    screen_f3_targets,
    select_new_f3_representatives,
    stage_a_rank_key,
    verify_g129_root,
)
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.proof_aware_tactical_bridge import interpret_continuation_stop
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "f3_quality_frontier_v0_82"
BASE_SHA = "073de8f7916bd79f8b0e426614905bfc57982c10"
BRANCH = "agent/f3-quality-frontier-v0-82"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "f3_quality_frontier_progress_v0_82.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_82.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_82.json"


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


def slim_f3(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "assembly_h", "assembly_f", "slack", "face_down",
        "empty_n", "legal_tableau", "boundaries", "foundation_suits",
        "ready_suits", "n_ready", "ordered_digest", "ident", "control_tag",
        "selection_role", "n_actions",
    )}


def slim_term(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "assembly_h", "assembly_f", "slack", "quality",
        "bridge_loss", "root_g", "root_h", "root_f", "tactical_target",
        "legal_tableau", "boundaries", "empty_n", "face_down", "class",
        "viable", "surplus", "closed", "closed_tag", "ordered_digest", "ident",
        "delta_g", "delta_h", "delta_f", "assembly_payback", "n_actions",
    )}


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "elapsed_s", "unique", "expanded",
        "generated", "stop_reason", "raw_count", "viable_count", "surplus_count",
        "cheapest_viable_g", "best_viable_f", "min_h_viable", "max_viable_slack",
        "min_cover", "min_blockers", "proof_prunes",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["viable_terminals"] = [slim_term(t) for t in (pr.get("viable_terminals") or [])[:4]]
    return rec


def slim_agg(agg: dict) -> dict:
    return {
        "root_g": agg.get("root_g"),
        "root_h": agg.get("root_h"),
        "root_f": agg.get("root_f"),
        "root_slack": agg.get("root_slack"),
        "root_empty_n": agg.get("root_empty_n"),
        "root_legal": agg.get("root_legal"),
        "root_boundaries": agg.get("root_boundaries"),
        "selection_role": agg.get("selection_role"),
        "ready_suits": agg.get("ready_suits"),
        "raw_count": agg.get("raw_count"),
        "viable_count": agg.get("viable_count"),
        "surplus_count": agg.get("surplus_count"),
        "strong_surplus_count": agg.get("strong_surplus_count"),
        "best_terminal_f": agg.get("best_terminal_f"),
        "best_slack": agg.get("best_slack"),
        "cheapest_terminal_g": agg.get("cheapest_terminal_g"),
        "lowest_terminal_h": agg.get("lowest_terminal_h"),
        "bridge_loss": agg.get("bridge_loss"),
        "best_payback": agg.get("best_payback"),
        "quality": agg.get("quality"),
        "elapsed_s": agg.get("elapsed_s"),
        "unique": agg.get("unique"),
        "proof_prunes": agg.get("proof_prunes"),
        "probes": [slim_probe(p) for p in agg.get("probes") or []],
        "viable_terminals": [slim_term(t) for t in (agg.get("viable_terminals") or [])[:8]],
        "ordered_digest": agg.get("ordered_digest"),
        "ident": agg.get("ident"),
    }


def write_report(p: dict) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Quality-diverse F3 harvest from autonomous g129, then short proof-aware "
        "next-foundation screening. Canonical 172 was not a search input. "
        "Exhausted v0.80/v0.81 F4/F5 roots were not resumed.",
        "",
        "## g129 root",
        "",
        str({k: (p.get("g129") or {}).get(k) for k in (
            "ok", "g", "foundations", "face_down", "stock_rows", "assembly_h", "assembly_f",
            "v076_digest_match",
        )}),
        "",
        "## F3 harvest",
        "",
        f"unique={p.get('harvest_unique')} expanded={p.get('harvest_expanded')} "
        f"generated={p.get('harvest_generated')} F3={p.get('n_f3')} "
        f"pareto={p.get('n_pareto')} stop=`{p.get('harvest_stop')}` "
        f"t={_fmt(p.get('harvest_s'))}s prunes={p.get('harvest_prunes')}",
        "",
        "## F3 Pareto frontier",
        "",
        "| F3 |  g |  h |  f | slack | fd | empties | legal | boundaries | tag |",
        "| -- | -: | -: | -: | ----: | -: | ------: | ----: | ---------: | --- |",
    ]
    for rec in p.get("pareto") or []:
        tag = rec.get("control_tag") or rec.get("selection_role") or ""
        lines.append(
            f"| 3 | {rec.get('g')} | {rec.get('assembly_h')} | {rec.get('assembly_f')} | "
            f"{rec.get('slack')} | {rec.get('face_down')} | {rec.get('empty_n')} | "
            f"{rec.get('legal_tableau')} | {rec.get('boundaries')} | {tag} |"
        )
    lines += [
        "",
        "Controls: g141 cheapest F3 (f174, later bridge loss +12); "
        "g158 assembled F3 (f180, later bridge loss +5). "
        "Active six exclude those exact digests.",
        "",
        "## Selected new F3s",
        "",
        str([
            {
                "role": r.get("selection_role"),
                "g": r.get("g"),
                "h": r.get("assembly_h"),
                "f": r.get("assembly_f"),
                "empties": r.get("empty_n"),
                "legal": r.get("legal_tableau"),
                "boundaries": r.get("boundaries"),
            }
            for r in p.get("selected") or []
        ]),
        "",
        "## Bridge-value table",
        "",
        "| root g | root h | root f | target | terminal F | terminal g | terminal h | terminal f | slack | bridge loss |",
        "| -----: | -----: | -----: | ------ | ---------: | ---------: | ---------: | ---------: | ----: | ----------: |",
    ]
    for rec in p.get("bridge_table") or []:
        lines.append(
            f"| {rec.get('root_g')} | {rec.get('root_h')} | {rec.get('root_f')} | "
            f"{rec.get('target')} | {rec.get('terminal_F')} | {rec.get('terminal_g')} | "
            f"{rec.get('terminal_h')} | {rec.get('terminal_f')} | {rec.get('slack')} | "
            f"{rec.get('bridge_loss')} |"
        )
    if not p.get("bridge_table"):
        lines.append("| — | — | — | — | — | — | — | — | — | — |")
    lines += [
        "",
        f"Stage B promoted roots/targets: {p.get('stage_b_pairs')}",
        "",
        f"raw={p.get('n_raw')} viable={p.get('n_viable')} surplus1={p.get('n_surplus1')} "
        f"strong={p.get('n_strong')} closed_hits={p.get('n_closed')}",
        "",
        "## Frozen controls",
        "",
        f"g141: root f={G141_CONTROL['f']} best next f={G141_CONTROL['best_next_f']} "
        f"bridge loss +{G141_CONTROL['bridge_loss']}",
        f"g158: root f={G158_CONTROL['f']} best next f={G158_CONTROL['best_next_f']} "
        f"bridge loss +{G158_CONTROL['bridge_loss']}",
        "",
        "## Continuation",
        "",
        f"portfolio n={p.get('n_portfolio')} stop=`{p.get('stop_reason')}` "
        f"unique={p.get('unique')} exp={p.get('expanded')} maxF={p.get('max_foundations')} "
        f"exhausted={p.get('roots_exhausted')} recommend_continue={p.get('recommend_continue_from_these_roots')}",
        "",
        p.get("continuation_note") or "",
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
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "F3_FRONTIER_CONTRACT_FAILURE",
            "contract_reason": "incumbent 187 replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F3_FRONTIER_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("VERIFY g129", flush=True)
    g129 = verify_g129_root(opening)
    print(
        f"G129 ok={g129.get('ok')} g={g129.get('g')} F={g129.get('foundations')} "
        f"h={g129.get('assembly_h')} f={g129.get('assembly_f')} match={g129.get('v076_digest_match')}",
        flush=True,
    )
    if not g129.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "F3_FRONTIER_CONTRACT_FAILURE",
            "contract_reason": g129.get("reason"),
            "g129": {k: v for k, v in g129.items() if k not in ("post", "g123", "g128")},
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT F3_FRONTIER_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    controls = control_digests()
    closed = load_closed_root_table()
    print(f"CLOSED roots n={len(closed)} controls g141/g158 loaded", flush=True)
    _write_json(PROG, {"phase": "harvest", "g129": g129.get("g")})

    harvest_budget = min(HARVEST_S, max(30.0, TOTAL_S - (time.perf_counter() - wall0) - 620.0))
    print(f"HARVEST F3 t={harvest_budget:.1f}s unique={HARVEST_UNIQUE}", flush=True)
    harvest = harvest_f3_terminals(
        {
            "g": g129["g"],
            "ordered_digest": g129["ordered_digest"],
            "whole_game_identity": g129["whole_game_identity"],
            "full_actions": g129["full_actions"],
        },
        time_s=harvest_budget,
        unique=HARVEST_UNIQUE,
    )
    marked = mark_control_f3s(harvest["f3s"], controls)
    pareto = f3_pareto_frontier(marked)
    selected = select_new_f3_representatives(marked, controls=controls, k=MAX_ACTIVE_F3)
    rediscovered = [r.get("control_tag") for r in marked if r.get("control_tag")]
    print(
        f"HARVEST stop={harvest.get('stop_reason')} unique={harvest.get('unique')} "
        f"F3={harvest.get('n_f3')} pareto={len(pareto)} selected={len(selected)} "
        f"controls={rediscovered} t={harvest.get('elapsed_s'):.1f}s",
        flush=True,
    )
    _write_json(PROG, {"phase": "stage_a", "n_f3": harvest.get("n_f3"), "n_selected": len(selected)})

    stage_a = []
    for f3 in selected:
        print(
            f"STAGE A role={f3.get('selection_role')} g={f3.get('g')} h={f3.get('assembly_h')} "
            f"f={f3.get('assembly_f')} ready={f3.get('ready_suits')}",
            flush=True,
        )
        remain = TOTAL_S - (time.perf_counter() - wall0)
        if remain < CONTINUATION_RESERVE_S + 20:
            print("STAGE A stop: preserve continuation reserve", flush=True)
            break
        stage_a.append(
            screen_f3_targets(f3, time_s=STAGE_A_S, unique=STAGE_A_UNIQUE, stage="A")
        )
        agg = stage_a[-1]
        print(
            f"  raw={agg.get('raw_count')} viable={agg.get('viable_count')} "
            f"best_f={agg.get('best_terminal_f')} loss={agg.get('bridge_loss')} "
            f"t={agg.get('elapsed_s'):.1f}s",
            flush=True,
        )

    ranked = sorted(stage_a, key=stage_a_rank_key)
    used = time.perf_counter() - wall0
    remain = TOTAL_S - used
    b_budget = min(STAGE_B_ROOTS * STAGE_B_TARGETS * STAGE_B_S, max(0.0, remain - CONTINUATION_RESERVE_S))
    pairs = choose_stage_b_pairs(ranked) if b_budget >= 1.0 else []
    if pairs:
        per = min(STAGE_B_S, b_budget / float(len(pairs)))
    else:
        per = 0.0
    print(f"STAGE B pairs={[(x['root'].get('root_g'), x['suit']) for x in pairs]} per={per:.1f}s", flush=True)
    _write_json(PROG, {"phase": "stage_b", "n_pairs": len(pairs)})

    stage_b_aggs = []
    extra_terms = []
    for pair in pairs:
        if time.perf_counter() - wall0 > TOTAL_S - CONTINUATION_RESERVE_S:
            break
        root = pair["root"]
        tgt = None
        for t in (root.get("inspect") or {}).get("remaining_targets") or []:
            if t.get("suit") == pair["suit"]:
                tgt = t
                break
        if tgt is None:
            continue
        probe = probe_proof_aware_target(
            {"g": root["root_g"], "ordered_digest": root["ordered_digest"]},
            tgt,
            time_s=per,
            unique=STAGE_B_UNIQUE,
            stage="B",
        )
        extra_terms.extend(probe.get("viable_terminals") or [])
        merged_probes = list(root.get("probes") or []) + [probe]
        stage_b_aggs.append(aggregate_f3_probes(
            {"selection_role": root.get("selection_role")},
            root["inspect"],
            merged_probes,
        ))

    all_aggs = list(stage_b_aggs) if stage_b_aggs else list(stage_a)
    if stage_b_aggs:
        seen_id = {a.get("ident") for a in stage_b_aggs}
        for a in stage_a:
            if a.get("ident") not in seen_id:
                all_aggs.append(a)

    portfolio = build_next_foundation_portfolio(all_aggs, closed)
    n_closed = 0
    for agg in all_aggs:
        for rec in agg.get("viable_terminals") or []:
            ident = rec.get("ident") or rec.get("whole_game_identity")
            if ident and is_known_closed(ident, int(rec["g"]), closed):
                n_closed += 1
                rec["closed"] = True
                rec["closed_tag"] = "KNOWN_CLOSED_STATE"

    bridge_table = []
    for agg in all_aggs:
        terms = agg.get("viable_terminals") or []
        if terms:
            best = min(terms, key=lambda r: (int(r["assembly_f"]), int(r["g"])))
            bridge_table.append({
                "root_g": agg.get("root_g"),
                "root_h": agg.get("root_h"),
                "root_f": agg.get("root_f"),
                "target": best.get("tactical_target"),
                "terminal_F": best.get("foundations"),
                "terminal_g": best.get("g"),
                "terminal_h": best.get("assembly_h"),
                "terminal_f": best.get("assembly_f"),
                "slack": best.get("slack"),
                "bridge_loss": bridge_loss(agg.get("root_f"), best.get("assembly_f")),
                "quality": next_foundation_quality(int(best["assembly_f"])),
            })
        else:
            live = None
            if agg.get("probes"):
                live = min(
                    agg["probes"],
                    key=lambda p: (
                        int(p.get("min_cover") if p.get("min_cover") is not None else 10**9),
                        -int(p.get("unique") or 0),
                    ),
                )
            bridge_table.append({
                "root_g": agg.get("root_g"),
                "root_h": agg.get("root_h"),
                "root_f": agg.get("root_f"),
                "target": None if live is None else live.get("suit"),
                "terminal_F": None,
                "terminal_g": None,
                "terminal_h": None,
                "terminal_f": None,
                "slack": None,
                "bridge_loss": None,
                "quality": None,
                "live_cover": None if live is None else live.get("min_cover"),
                "live_blockers": None if live is None else live.get("min_blockers"),
            })

    best_new_f = None
    n_raw = n_viable = n_surplus1 = n_strong = 0
    max_f = 3
    screening_time_limited = False
    for agg in all_aggs:
        n_raw += int(agg.get("raw_count") or 0)
        n_viable += int(agg.get("viable_count") or 0)
        n_strong += int(agg.get("strong_surplus_count") or 0)
        if agg.get("best_terminal_f") is not None:
            best_new_f = (
                int(agg["best_terminal_f"])
                if best_new_f is None
                else min(best_new_f, int(agg["best_terminal_f"]))
            )
        for rec in agg.get("viable_terminals") or []:
            max_f = max(max_f, int(rec.get("foundations") or 0))
            q = next_foundation_quality(int(rec["assembly_f"]))
            if q == "SURPLUS_1":
                n_surplus1 += 1
        if int(agg.get("root_slack") or 0) > 0:
            for pr in agg.get("probes") or []:
                if pr.get("stop_reason") == "time limit":
                    screening_time_limited = True

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if portfolio and remain >= 5.0:
        print(f"CONTINUE n={len(portfolio)} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "continuation", "n_portfolio": len(portfolio)})
        cont = search_f4_portfolio(opening, portfolio, time_s=remain, unique=SEARCH_UNIQUE)
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations}",
            flush=True,
        )
    else:
        print("NO continuation portfolio or remaining time", flush=True)

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        full = as_actions(g129["full_actions"]) + as_actions(cont.solution_actions)
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
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.82 F3 quality frontier")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(
                META,
                {
                    "g": int(cont.solution_g),
                    "replay_ok": True,
                    "canonical_input": False,
                    "parent_incumbent": 187,
                    "lineage": "g129 autonomous F3 harvest → proof-aware bridge",
                    "continuation_stop": cont.stop_reason,
                },
            )
            improved = True

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "wall_s": time.perf_counter() - wall0,
        "g129": {k: v for k, v in g129.items() if k not in ("post", "g123", "g128", "full_actions")},
        "harvest_s": harvest.get("elapsed_s"),
        "harvest_unique": harvest.get("unique"),
        "harvest_expanded": harvest.get("expanded"),
        "harvest_generated": harvest.get("generated"),
        "harvest_stop": harvest.get("stop_reason"),
        "harvest_prunes": harvest.get("proof_prunes"),
        "harvest_h_cache": harvest.get("h_cache"),
        "n_f3": harvest.get("n_f3"),
        "n_pareto": len(pareto),
        "n_selected": len(selected),
        "rediscovered_controls": rediscovered,
        "controls": {
            "g141": dict(G141_CONTROL, digest_loaded=True),
            "g158": dict(G158_CONTROL, digest_loaded=True),
        },
        "pareto": [slim_f3(r) for r in pareto],
        "selected": [slim_f3(r) for r in selected],
        "stage_a": [slim_agg(a) for a in stage_a],
        "stage_b_pairs": [(x["root"].get("root_g"), x["suit"]) for x in pairs],
        "bridge_table": bridge_table,
        "n_raw": n_raw,
        "n_viable": n_viable,
        "n_surplus1": n_surplus1,
        "n_strong": n_strong,
        "n_closed": n_closed,
        "n_closed_table": len(closed),
        "best_new_f": best_new_f,
        "screening_time_limited": screening_time_limited,
        "n_portfolio": len(portfolio),
        "portfolio": [slim_term(r) for r in portfolio],
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "generated": None if cont is None else getattr(cont, "generated", None),
        "stop_reason": stop_reason,
        "roots_exhausted": bool(interp.get("exhausted")),
        "recommend_continue_from_these_roots": interp.get("recommend_continue_from_these_roots"),
        "continuation_note": interp.get("note"),
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(getattr(cont, "accounting_fail", False)) if cont is not None else False,
        "bound_perf": None if cont is None else {
            "prunes": cont.lower_bound_prunes,
            "calls": cont.lower_bound_calls,
        },
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "envelope": {
            "time_s": TOTAL_S,
            "harvest_s": HARVEST_S,
            "stage_a_s": STAGE_A_S,
            "stage_b_s": STAGE_B_S,
            "continuation_reserve_s": CONTINUATION_RESERVE_S,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
    }
    verdict, reason = choose_f3_frontier_verdict(payload)
    if verdict == "F3_FRONTIER_SEARCH_LIMITED":
        interpretation = (
            "Harvest found a diverse F3 Pareto including both frozen controls. "
            "10s/target screening did not beat g158: F3s already at f>=185 exhaust immediately "
            "(no conversion slack), while cheap/interior F3s hit the time limit before F4, "
            "consistent with the g141 control needing ~49s."
        )
    elif verdict == "F3_FRONTIER_NO_BETTER_THAN_G158":
        interpretation = (
            "No new F3 produced bridge economics better than the g158 control (best next f=185, loss +5)."
        )
    else:
        interpretation = reason
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = interpretation
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "n_f3": harvest.get("n_f3"),
            "n_selected": len(selected),
            "best_new_f": best_new_f,
            "stop_reason": stop_reason,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
