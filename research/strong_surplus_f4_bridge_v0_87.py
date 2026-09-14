#!/usr/bin/env python3
"""v0.87: F4→F5 proof-aware bridge from v0.86 strong-surplus Hearts F4s.

Canonical 172 is not a search input. Does not seed the v0.86 F5 path.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f2_quality_frontier import load_f2_closed_table
from spider.f3_quality_frontier import (
    aggregate_f3_probes,
    is_known_closed,
    next_foundation_quality,
    probe_proof_aware_target,
)
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.proof_aware_tactical_bridge import interpret_continuation_stop, recover_digest_path
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.strong_surplus_f4_bridge import (
    CONTINUATION_RESERVE_S,
    F3_CONTROL,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    choose_stage_b_pairs,
    choose_strong_f4_verdict,
    document_boundaries_split,
    next_recommendation,
    select_active_f4s,
    select_f5_portfolio,
    verify_all_f4_roots,
)
from spider.superior_f2_focused_endgame import reconstruct_superior_f2_root
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "strong_surplus_f4_bridge_v0_87"
BASE_SHA = "011c8245bad8910c53248d9360111d5e0df274c7"
BRANCH = "agent/strong-surplus-f4-bridge-v0-87"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "strong_surplus_f4_bridge_progress_v0_87.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_87.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_87.json"


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


def slim_root(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "selection_role", "g", "foundations", "assembly_h", "assembly_f", "slack",
        "face_down", "empty_n", "legal_tableau", "visible_runs", "visible_components",
        "mixed_suit_boundaries", "foundation_suits", "ready_suits", "n_ready",
        "ordered_digest", "ident", "ok", "delta_g", "delta_h", "delta_f",
        "assembly_payback", "n_actions", "tactical_target",
    )}


def slim_term(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "assembly_h", "assembly_f", "slack", "quality",
        "bridge_loss", "root_g", "tactical_target", "class", "viable", "closed",
        "ordered_digest", "ident", "delta_g", "delta_h", "delta_f", "assembly_payback",
    )}


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "elapsed_s", "unique", "expanded",
        "stop_reason", "raw_count", "viable_count", "surplus_count",
        "cheapest_viable_g", "best_viable_f", "min_h_viable", "first_viable_s",
        "max_viable_slack", "proof_prunes",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["viable_terminals"] = [slim_term(t) for t in (pr.get("viable_terminals") or [])[:4]]
    return rec


def slim_agg(agg: dict) -> dict:
    return {
        "name": agg.get("selection_role") or agg.get("calibration_name"),
        "root_g": agg.get("root_g"),
        "root_h": agg.get("root_h"),
        "root_f": agg.get("root_f"),
        "root_slack": agg.get("root_slack"),
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
        "Hierarchical F4→F5 proof-aware bridge from v0.86 strong-surplus F4s. "
        "Canonical 172 was not a search input. v0.86 F5 path was not seeded.",
        "",
        "## Structural telemetry",
        "",
        str(p.get("telemetry_audit") or {}),
        "",
        "## Active F4 roots",
        "",
        "| root | g | h | f | slack | fd | empties | legal | visible_runs | mixed_suit_boundaries |",
        "| ---- | -: | -: | -: | ----: | -: | ------: | ----: | -----------: | --------------------: |",
    ]
    for r in p.get("roots") or []:
        lines.append(
            f"| {r.get('selection_role')} | {r.get('g')} | {r.get('assembly_h')} | "
            f"{r.get('assembly_f')} | {r.get('slack')} | {r.get('face_down')} | "
            f"{r.get('empty_n')} | {r.get('legal_tableau')} | {r.get('visible_runs')} | "
            f"{r.get('mixed_suit_boundaries')} |"
        )
    lines += [
        "",
        "## Stage A probes",
        "",
        "| root g | f | rank | target | stop | unique | raw | viable | best g | h | f | slack |",
        "| -----: | -: | ---: | ------ | ---- | -----: | --: | -----: | -----: | -: | -: | ----: |",
    ]
    for rec in p.get("probe_table") or []:
        if rec.get("stage") == "B":
            continue
        lines.append(
            f"| {rec.get('root_g')} | {rec.get('root_f')} | {rec.get('target_rank')} | "
            f"{rec.get('target')} | {rec.get('stop')} | {rec.get('unique')} | {rec.get('raw')} | "
            f"{rec.get('viable')} | {rec.get('best_g')} | {rec.get('best_h')} | {rec.get('best_f')} | "
            f"{rec.get('slack')} |"
        )
    lines += [
        "",
        f"Stage B pairs: {p.get('stage_b_pairs')}",
        "",
        f"raw={p.get('n_raw')} viable={p.get('n_viable')} surplus={p.get('n_surplus')} "
        f"strong={p.get('n_strong')} closed={p.get('n_closed')} reopen={p.get('n_reopen')}",
        "",
        "## Slack trajectory",
        "",
        str(p.get("slack_trajectory") or {}),
        "",
        "## Continuation",
        "",
        f"portfolio n={p.get('n_portfolio')} stop=`{p.get('stop_reason')}` "
        f"unique={p.get('unique')} exp={p.get('expanded')} maxF={p.get('max_foundations')} "
        f"exhausted={p.get('roots_exhausted')}",
        "",
        f"wall_s={_fmt(p.get('wall_s'))}",
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


def _probe_table(aggs, stage):
    rows = []
    for agg in aggs:
        for pr in agg.get("probes") or []:
            if pr.get("stage") != stage:
                continue
            best = None
            terms = pr.get("viable_terminals") or []
            if terms:
                best = min(terms, key=lambda r: (int(r["assembly_f"]), int(r["g"])))
            rows.append({
                "stage": stage,
                "root_g": agg.get("root_g"),
                "root_f": agg.get("root_f"),
                "target_rank": pr.get("operational_rank"),
                "target": pr.get("suit"),
                "stop": pr.get("stop_reason"),
                "unique": pr.get("unique"),
                "expanded": pr.get("expanded"),
                "raw": pr.get("raw_count"),
                "viable": pr.get("viable_count"),
                "best_g": None if best is None else best.get("g"),
                "best_h": None if best is None else best.get("assembly_h"),
                "best_f": None if best is None else best.get("assembly_f"),
                "slack": None if best is None else best.get("slack"),
            })
    return rows


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "STRONG_F4_BRIDGE_CONTRACT_FAILURE", "contract_reason": "incumbent 187 replay failed"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT STRONG_F4_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("LOAD strong-surplus F4s", flush=True)
    checked = verify_all_f4_roots()
    print(f"loaded={checked.get('n_loaded')} ok={checked.get('n_ok')}", flush=True)
    if not checked.get("ok"):
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "STRONG_F4_BRIDGE_CONTRACT_FAILURE", "contract_reason": checked.get("reason")}
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT STRONG_F4_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    active = select_active_f4s(checked["roots"])
    for r in active:
        print(
            f"  {r.get('selection_role')} g={r.get('g')} h={r.get('assembly_h')} f={r.get('assembly_f')} "
            f"slack={r.get('slack')} legal={r.get('legal_tableau')} vis={r.get('visible_runs')} "
            f"mixed={r.get('mixed_suit_boundaries')} ready={r.get('ready_suits')}",
            flush=True,
        )
    closed = load_f2_closed_table()
    _write_json(PROG, {"phase": "stage_a", "n_roots": len(active)})

    stage_a = []
    for rec in active:
        targets = list(rec.get("remaining_targets") or [])[:4]
        print(f"STAGE A g={rec.get('g')} f={rec.get('assembly_f')} targets={[t.get('suit') for t in targets]}", flush=True)
        probes = []
        for tgt in targets:
            remain = TOTAL_S - (time.perf_counter() - wall0)
            if remain < CONTINUATION_RESERVE_S + 5:
                print("STAGE A skip: preserve continuation", flush=True)
                break
            t_s = min(STAGE_A_S, remain - CONTINUATION_RESERVE_S)
            probe = probe_proof_aware_target(
                {"g": rec["g"], "ordered_digest": rec["ordered_digest"]},
                tgt,
                time_s=t_s,
                unique=STAGE_A_UNIQUE,
                stage="A",
            )
            probes.append(probe)
            print(
                f"  rank={tgt.get('operational_rank')} suit={tgt.get('suit')} stop={probe.get('stop_reason')} "
                f"viable={probe.get('viable_count')} best_f={probe.get('best_viable_f')} t={probe.get('elapsed_s'):.1f}s",
                flush=True,
            )
        agg = aggregate_f3_probes(rec, rec, probes)
        agg["selection_role"] = rec.get("selection_role")
        agg["inspect"] = rec
        stage_a.append(agg)

    remain = TOTAL_S - (time.perf_counter() - wall0)
    b_budget = min(STAGE_B_N * STAGE_B_S, max(0.0, remain - CONTINUATION_RESERVE_S))
    pairs = choose_stage_b_pairs(stage_a, n_pairs=STAGE_B_N) if b_budget >= 1 else []
    per_b = min(STAGE_B_S, b_budget / float(len(pairs))) if pairs else 0.0
    print(f"STAGE B n={len(pairs)} per={per_b:.1f}s", flush=True)
    _write_json(PROG, {"phase": "stage_b", "n_pairs": len(pairs)})
    stage_b_aggs = []
    for pair in pairs:
        if per_b < 1:
            break
        root = pair["root"]
        tgt = next((t for t in (root.get("inspect") or {}).get("remaining_targets") or [] if t.get("suit") == pair["suit"]), None)
        if tgt is None:
            continue
        probe = probe_proof_aware_target(
            {"g": root["root_g"], "ordered_digest": root["ordered_digest"]},
            tgt,
            time_s=per_b,
            unique=STAGE_A_UNIQUE,
            stage="B",
        )
        merged = [p for p in (root.get("probes") or []) if not (p.get("suit") == pair["suit"] and p.get("stage") == "B")] + [probe]
        agg = aggregate_f3_probes({"selection_role": root.get("selection_role")}, root["inspect"], merged)
        agg["selection_role"] = root.get("selection_role")
        agg["inspect"] = root["inspect"]
        stage_b_aggs.append(agg)
        print(
            f"  B g={root.get('root_g')} suit={pair.get('suit')} viable={probe.get('viable_count')} "
            f"best_f={probe.get('best_viable_f')}",
            flush=True,
        )

    all_aggs = list(stage_b_aggs) if stage_b_aggs else list(stage_a)
    if stage_b_aggs:
        seen = {a.get("ident") for a in stage_b_aggs}
        for a in stage_a:
            if a.get("ident") not in seen:
                all_aggs.append(a)

    n_raw = n_viable = n_surplus = n_strong = n_closed = n_reopen = 0
    best_next_f = None
    max_f = 4
    screening_time_limited = False
    for agg in all_aggs:
        n_raw += int(agg.get("raw_count") or 0)
        n_viable += int(agg.get("viable_count") or 0)
        n_strong += int(agg.get("strong_surplus_count") or 0)
        if agg.get("best_terminal_f") is not None:
            bf = int(agg["best_terminal_f"])
            best_next_f = bf if best_next_f is None else min(best_next_f, bf)
        for rec in agg.get("viable_terminals") or []:
            max_f = max(max_f, int(rec.get("foundations") or 0))
            q = next_foundation_quality(int(rec["assembly_f"]))
            if q == "SURPLUS_1":
                n_surplus += 1
            ident = rec.get("ident")
            if ident and ident in closed:
                if int(rec["g"]) >= int(closed[ident]["g"]):
                    n_closed += 1
                    rec["closed"] = True
                else:
                    n_reopen += 1
        for pr in agg.get("probes") or []:
            if pr.get("stop_reason") == "time limit":
                screening_time_limited = True

    probe_table = _probe_table(stage_a, "A") + _probe_table(all_aggs, "B")
    bridge_loss_table = []
    for agg in all_aggs:
        bridge_loss_table.append({
            "root_g": agg.get("root_g"),
            "root_f": agg.get("root_f"),
            "best_next_f": agg.get("best_terminal_f"),
            "bridge_loss": agg.get("bridge_loss"),
            "best_slack": agg.get("best_slack"),
        })
    slack_traj = {
        "F3": {"g": 148, "f": 177, "slack": 9},
        "F4": {"f": 181, "slack": 5},
        "F5": {"f": best_next_f, "slack": None if best_next_f is None else 186 - int(best_next_f)},
    }

    portfolio = select_f5_portfolio(all_aggs, closed)
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
        print(f"NO continuation portfolio={len(portfolio)} remain={remain:.1f}s", flush=True)

    stop_reason = None if cont is None else cont.stop_reason
    interp = interpret_continuation_stop(stop_reason, solved=bool(cont.solved) if cont is not None else False)
    if cont is not None:
        max_f = max(max_f, int(cont.max_foundations or 0))

    improved = False
    replay_ok = False
    replay_g = None
    terminal_lineage = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        sup = reconstruct_superior_f2_root(opening)
        recovered = None
        if sup.get("ok"):
            for rec in portfolio:
                digest = rec.get("ordered_digest")
                if not digest:
                    continue
                recovered = recover_digest_path(
                    opening,
                    {
                        "g": sup["g"],
                        "ordered_digest": sup["ordered_digest"],
                        "whole_game_identity": sup["whole_game_identity"],
                        "full_actions": sup["full_actions"],
                        "foundations": 2,
                        "face_down": sup["face_down"],
                    },
                    digest,
                    int(rec["g"]),
                    time_s=180.0,
                    unique=200_000,
                )
                if recovered.get("ok"):
                    break
        if recovered and recovered.get("ok"):
            full = as_actions(recovered["hit"]["full_actions"]) + as_actions(cont.solution_actions)
        else:
            full = as_actions(cont.solution_actions)
        end = opening.clone()
        try:
            replay_g = replay_actions(end, list(full))
        except Exception:
            replay_g = None
        replay_ok = (
            replay_g == int(cont.solution_g)
            and end.is_solved()
            and sum(1 for a in full if is_deal(a)) == 5
            and len(end.foundations) == 8
            and not end.stock
            and all(c.is_empty() for c in end.columns)
        )
        if replay_ok:
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.87 strong-surplus F4 bridge")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(META, {"g": int(cont.solution_g), "replay_ok": True, "canonical_input": False, "parent_incumbent": 187})
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
        "telemetry_audit": document_boundaries_split(),
        "n_loaded": checked.get("n_loaded"),
        "roots": [slim_root(r) for r in active],
        "stage_a": [slim_agg(a) for a in stage_a],
        "stage_b_pairs": [(x["root"].get("root_g"), x["suit"]) for x in pairs],
        "probe_table": probe_table,
        "bridge_loss_table": bridge_loss_table,
        "slack_trajectory": slack_traj,
        "n_raw": n_raw,
        "n_viable": n_viable,
        "n_surplus": n_surplus,
        "n_strong": n_strong,
        "n_closed": n_closed,
        "n_reopen": n_reopen,
        "best_next_f": best_next_f,
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
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "v086_f5_control": {"note": "v0.86 mixed continuation reached maxF=5; g/h/f not stored in artefact; not seeded"},
        "f3_control": F3_CONTROL,
        "envelope": {
            "time_s": TOTAL_S,
            "stage_a_s": STAGE_A_S,
            "stage_b_s": STAGE_B_S,
            "continuation_reserve_s": CONTINUATION_RESERVE_S,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
    }
    verdict, reason = choose_strong_f4_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(PROG, {"phase": "complete", "verdict": verdict, "best_next_f": best_next_f, "stop_reason": stop_reason, "max_F": max_f})
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
