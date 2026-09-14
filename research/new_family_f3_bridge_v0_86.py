#!/usr/bin/env python3
"""v0.86: proof-aware bridge on the new-family F3s from v0.85.

Does not search the old g141. Canonical 172 is not a search input.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.f3_quality_frontier import (
    G141_CONTROL,
    aggregate_f3_probes,
    bridge_loss,
    is_known_closed,
    next_foundation_quality,
    probe_proof_aware_target,
)
from spider.f3_tactical_bridge import BRIDGE_CEILING, search_f4_portfolio
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.new_family_f3_bridge import (
    CONTINUATION_RESERVE_S,
    N_ROOTS,
    OLD_G141,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    TOTAL_S,
    choose_new_family_verdict,
    load_new_family_closed_table,
    next_recommendation,
    select_new_family_portfolio,
    verify_all_new_family_roots,
)
from spider.proof_aware_tactical_bridge import interpret_continuation_stop, recover_digest_path
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.superior_f2_focused_endgame import reconstruct_superior_f2_root
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "new_family_f3_bridge_v0_86"
BASE_SHA = "48e0bf7baf1a38119d3304360f0121fd1ea76ca2"
BRANCH = "agent/new-family-f3-bridge-v0-86"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "new_family_f3_bridge_progress_v0_86.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_86.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_86.json"


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
        "calibration_name", "g", "foundations", "assembly_h", "assembly_f", "slack",
        "face_down", "empty_n", "legal_tableau", "boundaries", "ready_suits",
        "n_ready", "ordered_digest", "ident", "ok", "reason", "differs_from_old_digest",
        "differs_from_old_ident", "foundation_suits",
    )}


def slim_term(r: dict) -> dict:
    return {k: r.get(k) for k in (
        "g", "foundations", "assembly_h", "assembly_f", "slack", "quality",
        "bridge_loss", "root_g", "tactical_target", "class", "viable", "closed",
        "closed_tag", "ordered_digest", "ident", "delta_g", "delta_h", "delta_f",
        "assembly_payback",
    )}


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "elapsed_s", "unique", "expanded",
        "stop_reason", "raw_count", "viable_count", "surplus_count",
        "cheapest_viable_g", "best_viable_f", "min_h_viable", "first_viable_s",
        "proof_prunes",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["viable_terminals"] = [slim_term(t) for t in (pr.get("viable_terminals") or [])[:4]]
    return rec


def slim_agg(agg: dict) -> dict:
    return {
        "name": agg.get("calibration_name"),
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
        "Equal 90s proof-aware probes of the v0.85 new-family F3s. "
        "Old g141 is a frozen control, not a search root. Canonical 172 was not a search input.",
        "",
        "## Roots",
        "",
        "| name | g | h | f | slack | legal | boundaries | old digest? | ok |",
        "| --- | -: | -: | -: | ----: | ----: | ---------: | --- | --- |",
    ]
    for r in p.get("roots") or []:
        lines.append(
            f"| {r.get('calibration_name')} | {r.get('g')} | {r.get('assembly_h')} | "
            f"{r.get('assembly_f')} | {r.get('slack')} | {r.get('legal_tableau')} | "
            f"{r.get('boundaries')} | differs={r.get('differs_from_old_digest')} | {r.get('ok')} |"
        )
    lines += [
        "",
        "## Root/target probes",
        "",
        "| root g | h | f | rank | target | stop | unique | exp | raw | viable | best g | h | f | slack |",
        "| -----: | -: | -: | ---: | ------ | ---- | -----: | --: | --: | -----: | -----: | -: | -: | ----: |",
    ]
    for rec in p.get("probe_table") or []:
        lines.append(
            f"| {rec.get('root_g')} | {rec.get('root_h')} | {rec.get('root_f')} | "
            f"{rec.get('target_rank')} | {rec.get('target')} | {rec.get('stop')} | "
            f"{rec.get('unique')} | {rec.get('expanded')} | {rec.get('raw')} | {rec.get('viable')} | "
            f"{rec.get('best_g')} | {rec.get('best_h')} | {rec.get('best_f')} | {rec.get('slack')} |"
        )
    cmp_ = p.get("old_vs_new_g141") or {}
    lines += [
        "",
        "## Old g141 vs new g141",
        "",
        "| metric | old g141 | new g141 |",
        "| --- | ---: | ---: |",
    ]
    for key, label in (
        ("g", "g"), ("h", "h"), ("f", "f"), ("slack", "slack"), ("fd", "fd"),
        ("empties", "empties"), ("legal", "legal"), ("boundaries", "boundaries"),
        ("foundation_suits", "foundation suits"), ("best_next_F", "best next F"),
        ("best_next_g", "best next g"), ("best_next_h", "best next h"),
        ("best_next_f", "best next f"), ("bridge_loss", "bridge loss"),
        ("remaining_slack", "remaining slack"),
    ):
        pair = cmp_.get(key) or {}
        lines.append(f"| {label} | {pair.get('old', '—')} | {pair.get('new', '—')} |")
    cmp2 = p.get("g141_vs_g148") or {}
    lines += [
        "",
        "## New g141 vs new g148",
        "",
        "| metric | new g141 | new g148 |",
        "| --- | ---: | ---: |",
    ]
    for key, label in (
        ("root_g", "root g"), ("h", "h"), ("f", "f"), ("slack", "slack"),
        ("boundaries", "boundaries"), ("legal", "legal"), ("best_next_f", "best next f"),
        ("bridge_loss", "bridge loss"), ("terminal_slack", "terminal slack"),
        ("first_viable_s", "time to first viable"),
    ):
        pair = cmp2.get(key) or {}
        lines.append(f"| {label} | {pair.get('g141', '—')} | {pair.get('g148', '—')} |")
    lines += [
        "",
        f"raw={p.get('n_raw')} viable={p.get('n_viable')} surplus1={p.get('n_surplus1')} "
        f"strong={p.get('n_strong')} closed_hits={p.get('n_closed')} lower_g_reopen={p.get('n_lower_g_reopen')}",
        "",
        "## Continuation",
        "",
        f"portfolio n={p.get('n_portfolio')} stop=`{p.get('stop_reason')}` "
        f"unique={p.get('unique')} exp={p.get('expanded')} maxF={p.get('max_foundations')} "
        f"exhausted={p.get('roots_exhausted')}",
        "",
        f"wall_s={_fmt(p.get('wall_s'))} reserve={CONTINUATION_RESERVE_S}s no_stage_b=True",
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
            "verdict": "NEW_F3_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": "incumbent 187 replay failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT NEW_F3_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("LOAD new-family F3s from v0.85", flush=True)
    checked = verify_all_new_family_roots()
    for r in checked["roots"]:
        print(
            f"  {r.get('calibration_name')} ok={r.get('ok')} g={r.get('g')} h={r.get('assembly_h')} "
            f"f={r.get('assembly_f')} legal={r.get('legal_tableau')} bounds={r.get('boundaries')} "
            f"vs_old_digest={r.get('differs_from_old_digest')} ready={r.get('ready_suits')}",
            flush=True,
        )
    if not checked.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "NEW_F3_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": "NEW_F3_BRIDGE_CONTRACT_FAILURE",
            "roots": [slim_root(r) for r in checked["roots"]],
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT NEW_F3_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    closed = load_new_family_closed_table()
    print(f"CLOSED n={len(closed)}; Stage A {STAGE_A_S}s/target unique={STAGE_A_UNIQUE}", flush=True)
    _write_json(PROG, {"phase": "stage_a", "n_roots": N_ROOTS})

    stage_a = []
    for rec in checked["roots"]:
        targets = list(rec.get("remaining_targets") or [])[:4]
        print(
            f"PROBE {rec.get('calibration_name')} g={rec.get('g')} f={rec.get('assembly_f')} "
            f"targets={[t.get('suit') for t in targets]} cap={STAGE_A_S}s",
            flush=True,
        )
        probes = []
        for tgt in targets:
            remain = TOTAL_S - (time.perf_counter() - wall0)
            if remain < CONTINUATION_RESERVE_S + 5:
                print("PROBE skip: preserve continuation reserve", flush=True)
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
                f"  rank={tgt.get('operational_rank')} suit={tgt.get('suit')} "
                f"stop={probe.get('stop_reason')} unique={probe.get('unique')} "
                f"viable={probe.get('viable_count')} best_f={probe.get('best_viable_f')} "
                f"t={probe.get('elapsed_s'):.1f}s",
                flush=True,
            )
        agg = aggregate_f3_probes(rec, rec, probes)
        agg["calibration_name"] = rec.get("calibration_name")
        agg["inspect"] = rec
        stage_a.append(agg)

    n_closed = 0
    n_reopen = 0
    screening_time_limited = False
    n_raw = n_viable = n_surplus1 = n_strong = 0
    best_new_f = None
    max_f = 3
    for agg in stage_a:
        n_raw += int(agg.get("raw_count") or 0)
        n_viable += int(agg.get("viable_count") or 0)
        n_strong += int(agg.get("strong_surplus_count") or 0)
        if agg.get("best_terminal_f") is not None:
            bf = int(agg["best_terminal_f"])
            best_new_f = bf if best_new_f is None else min(best_new_f, bf)
        for rec in agg.get("viable_terminals") or []:
            max_f = max(max_f, int(rec.get("foundations") or 0))
            if next_foundation_quality(int(rec["assembly_f"])) == "SURPLUS_1":
                n_surplus1 += 1
            ident = rec.get("ident") or rec.get("whole_game_identity")
            if ident and ident in closed:
                closed_g = int(closed[ident]["g"])
                if int(rec["g"]) >= closed_g:
                    n_closed += 1
                    rec["closed"] = True
                    rec["closed_tag"] = "KNOWN_CLOSED_STATE"
                else:
                    n_reopen += 1
                    rec["lower_g_reopen"] = True
        if int(agg.get("root_slack") or 0) > 0:
            for pr in agg.get("probes") or []:
                if pr.get("stop_reason") == "time limit":
                    screening_time_limited = True

    probe_table = []
    for agg in stage_a:
        for pr in agg.get("probes") or []:
            best = None
            terms = pr.get("viable_terminals") or []
            if terms:
                best = min(terms, key=lambda r: (int(r["assembly_f"]), int(r["g"])))
            probe_table.append({
                "root_g": agg.get("root_g"),
                "root_h": agg.get("root_h"),
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

    by_g = {int(a.get("root_g")): a for a in stage_a if a.get("root_g") is not None}
    a141, a148 = by_g.get(141), by_g.get(148)
    cheap_root = next((r for r in checked["roots"] if r.get("g") == 141), {})
    old_vs_new = {
        "g": {"old": 141, "new": 141},
        "h": {"old": 33, "new": 33},
        "f": {"old": 174, "new": 174},
        "slack": {"old": 12, "new": 12},
        "fd": {"old": 2, "new": cheap_root.get("face_down")},
        "empties": {"old": 2, "new": cheap_root.get("empty_n")},
        "legal": {"old": 41, "new": cheap_root.get("legal_tableau")},
        "boundaries": {"old": 36, "new": cheap_root.get("boundaries")},
        "foundation_suits": {"old": "historical", "new": cheap_root.get("foundation_suits")},
        "best_next_F": {"old": 4, "new": None if not (a141 and a141.get("viable_terminals")) else max(int(t["foundations"]) for t in a141["viable_terminals"])},
        "best_next_g": {"old": OLD_G141["best_next_g"], "new": None if a141 is None else a141.get("cheapest_terminal_g")},
        "best_next_h": {"old": OLD_G141["best_next_h"], "new": None if a141 is None else a141.get("lowest_terminal_h")},
        "best_next_f": {"old": OLD_G141["best_next_f"], "new": None if a141 is None else a141.get("best_terminal_f")},
        "bridge_loss": {"old": OLD_G141["bridge_loss"], "new": None if a141 is None else a141.get("bridge_loss")},
        "remaining_slack": {"old": 0, "new": None if a141 is None else a141.get("best_slack")},
    }

    def _first_viable(agg):
        if not agg:
            return None
        times = [p.get("first_viable_s") for p in (agg.get("probes") or []) if p.get("first_viable_s") is not None]
        return None if not times else min(times)

    g141_vs_g148 = {
        "root_g": {"g141": 141, "g148": 148},
        "h": {"g141": 33, "g148": 29},
        "f": {"g141": 174, "g148": 177},
        "slack": {"g141": 12, "g148": 9},
        "boundaries": {"g141": cheap_root.get("boundaries"), "g148": next((r.get("boundaries") for r in checked["roots"] if r.get("g") == 148), None)},
        "legal": {"g141": 43, "g148": 43},
        "best_next_f": {"g141": None if a141 is None else a141.get("best_terminal_f"), "g148": None if a148 is None else a148.get("best_terminal_f")},
        "bridge_loss": {"g141": None if a141 is None else a141.get("bridge_loss"), "g148": None if a148 is None else a148.get("bridge_loss")},
        "terminal_slack": {"g141": None if a141 is None else a141.get("best_slack"), "g148": None if a148 is None else a148.get("best_slack")},
        "first_viable_s": {"g141": _first_viable(a141), "g148": _first_viable(a148)},
    }

    portfolio = select_new_family_portfolio(stage_a, closed)
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
        for rec in portfolio:
            digest = rec.get("ordered_digest")
            if not digest or not sup.get("ok"):
                continue
            recovered = recover_digest_path(opening, {
                "g": sup["g"],
                "ordered_digest": sup["ordered_digest"],
                "whole_game_identity": sup["whole_game_identity"],
                "full_actions": sup["full_actions"],
                "foundations": 2,
                "face_down": sup["face_down"],
            }, digest, int(rec["g"]), time_s=180.0, unique=200_000)
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
            save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.86 new-family F3 bridge")
            terminal_lineage = foundation_progression(opening, list(full))
            _write_json(
                META,
                {
                    "g": int(cont.solution_g),
                    "replay_ok": True,
                    "canonical_input": False,
                    "parent_incumbent": 187,
                    "root_source": "v0.84 superior F2 / v0.85 F3",
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
        "stage_a_s": STAGE_A_S,
        "no_stage_b": True,
        "roots": [slim_root(r) for r in checked["roots"]],
        "old_g141_control": OLD_G141,
        "stage_a": [slim_agg(a) for a in stage_a],
        "probe_table": probe_table,
        "old_vs_new_g141": old_vs_new,
        "g141_vs_g148": g141_vs_g148,
        "new_g141": slim_agg(a141) if a141 else None,
        "new_g148": slim_agg(a148) if a148 else None,
        "n_raw": n_raw,
        "n_viable": n_viable,
        "n_surplus1": n_surplus1,
        "n_strong": n_strong,
        "n_closed": n_closed,
        "n_lower_g_reopen": n_reopen,
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
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "envelope": {
            "time_s": TOTAL_S,
            "stage_a_s": STAGE_A_S,
            "n_roots": N_ROOTS,
            "continuation_reserve_s": CONTINUATION_RESERVE_S,
            "ceiling": BRIDGE_CEILING,
            "rss_abort_mb": SEARCH_RSS_MB,
        },
    }
    verdict, reason = choose_new_family_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["interpretation"] = reason
    payload["next_recommendation"] = next_recommendation(verdict)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    write_report(payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "best_new_f": best_new_f,
            "stop_reason": stop_reason,
            "n_closed": n_closed,
            "n_reopen": n_reopen,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
