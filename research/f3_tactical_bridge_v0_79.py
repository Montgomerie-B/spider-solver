#!/usr/bin/env python3
"""v0.79: F3→F4 tactical bridge from the unpacked v0.78 g141 state.

Canonical 172 is evaluation only after freeze. Not a whole-game opening campaign.
Prefix provenance is recovered only if a complete candidate appears.
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
    STAGE_A_S,
    STAGE_B_N,
    TACTICAL_BUDGET_S,
    TOTAL_S,
    assembly_slack,
    choose_bridge_verdict,
    evaluate_187_f3_f4,
    recover_g141,
    run_tactical_bridge,
    search_f4_portfolio,
    verify_g141_root,
)
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import SEARCH_RSS_MB, SEARCH_UNIQUE, save_solution

EXPERIMENT = "f3_tactical_bridge_v0_79"
BASE_SHA = "30f2a79ee09acc6138c8ae7f8608660c525a5acc"
BRANCH = "agent/f3-tactical-bridge-v0-79"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "f3_tactical_bridge_progress_v0_79.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_79.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_79.json"


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


def slim_terms(roots: list) -> list:
    out = []
    for r in roots or []:
        out.append(
            {
                "g": r.get("g"),
                "foundations": r.get("foundations"),
                "face_down": r.get("face_down"),
                "empty_n": r.get("empty_n"),
                "h": r.get("assembly_h"),
                "f": r.get("assembly_f"),
                "slack": r.get("slack"),
                "legal": r.get("legal_tableau"),
                "boundaries": r.get("boundaries"),
                "target": r.get("tactical_target"),
                "rank": r.get("operational_rank"),
                "n_actions": r.get("n_actions"),
                "ordered_digest": r.get("ordered_digest"),
            }
        )
    return out


def slim_probe(pr: dict) -> dict:
    keep = (
        "suit", "stage", "operational_rank", "already_founded", "target_foundations_before",
        "found", "cheapest_g", "first_g", "first_s", "delta_g", "n_terminals", "n_admitted",
        "elapsed_s", "unique", "expanded", "generated", "stop_reason", "min_cover",
        "min_blockers", "best_k_access", "best_a_access", "min_h", "min_f", "lane_exp",
    )
    rec = {k: pr.get(k) for k in keep}
    rec["terminals"] = slim_terms(pr.get("terminals") or [])
    return rec


def write_report(p: dict) -> None:
    info = p.get("g141") or {}
    br = p.get("bridge") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Focused F3→F4 tactical bridge from the unpacked v0.78 g141 digest.",
        "Not a whole-game opening campaign. Canonical 172 was not a search input.",
        "",
        "## Slack convention",
        "",
        f"`slack = ceiling - f`. F2 186-172 = **+{assembly_slack(186, 172)}**. "
        f"F3 186-174 = **+{assembly_slack(186, 174)}**.",
        "",
        "## g141 root",
        "",
        f"* ok={info.get('ok')} g={info.get('g')} F={info.get('foundations')} fd={info.get('face_down')} "
        f"empty={info.get('empty_n')} legal={info.get('legal_tableau')} bounds={info.get('boundaries')} "
        f"h={info.get('assembly_h')} f={info.get('assembly_f')} slack={info.get('slack')}",
        f"* founded {info.get('foundation_suits')} ready {info.get('ready_suits')} best={info.get('best_suit')}",
        "",
        "## Materially-ready ranking",
        "",
        "| rank | suit | already F | cover | blockers | K | A | gap | merges | buried | exposed |",
        "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for t in info.get("remaining_targets") or []:
        lines.append(
            f"| {t.get('operational_rank')} | {t.get('suit')} | {t.get('already_founded')} | "
            f"{t.get('cover')} | {t.get('blockers')} | {t.get('k_access')} | {t.get('a_access')} | "
            f"{t.get('gap')} | {t.get('merge_edges')} | {t.get('buried_components')} | {t.get('exposed_components')} |"
        )
    lines += [
        "",
        "## Stage A (60 s / target, unique 100k, ceiling 186)",
        "",
        "| rank | suit | found | cheapest g | first s | terminals | unique | exp | min h | min f |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pr in br.get("stage_a") or []:
        lines.append(
            f"| {pr.get('operational_rank')} | {pr.get('suit')} | {pr.get('found')} | "
            f"{pr.get('cheapest_g')} | {_fmt(pr.get('first_s'))} | {pr.get('n_terminals')} | "
            f"{pr.get('unique')} | {pr.get('expanded')} | {pr.get('min_h')} | {pr.get('min_f')} |"
        )
    lines += [
        "",
        f"Stage B promoted: {br.get('promoted_suits')} (+60 s each).",
        "",
        "| suit | found | cheapest g | first s | terminals | unique | t s |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pr in br.get("stage_b") or []:
        lines.append(
            f"| {pr.get('suit')} | {pr.get('found')} | {pr.get('cheapest_g')} | "
            f"{_fmt(pr.get('first_s'))} | {pr.get('n_terminals')} | {pr.get('unique')} | {_fmt(pr.get('elapsed_s'))} |"
        )
    lines += [
        "",
        f"First F4: suit={br.get('first_f4_target')} g={br.get('first_f4_g')} t={_fmt(br.get('first_f4_s'))}s. "
        f"Cheapest F4 g={br.get('cheapest_f4_g')} h={br.get('cheapest_f4_h')} f={br.get('cheapest_f4_f')} "
        f"target={br.get('cheapest_f4_target')}. Portfolio n={br.get('n_f4')}.",
        f"Tactical elapsed {_fmt(br.get('elapsed_s'))}s / budget {TACTICAL_BUDGET_S}s.",
        "",
        "## Continuation",
        "",
        f"max F {p.get('max_foundations')} unique {p.get('unique')} expanded {p.get('expanded')} "
        f"t={_fmt(p.get('elapsed_s'))}s stop=`{p.get('stop_reason')}` solution_g={p.get('solution_g')}",
        "",
        "## Frontier",
        "",
        str(p.get("frontier_list") or []),
        "",
        "## 187 F3→F4 (after freeze)",
        "",
        str(p.get("eval_187") or {}),
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
    if verdict == "F3_TACTICAL_BRIDGE_COST_IMPROVED":
        return "Promote the new incumbent and reuse this hierarchical endgame decomposition."
    if verdict == "F3_TACTICAL_BRIDGE_DEEP_ENDGAME":
        return "Repeat tactical next-foundation decomposition at F4/F5, targeting lower assembly h."
    if verdict == "F3_TACTICAL_BRIDGE_REACHES_F4":
        return "Concentrate frozen endgame on the cheapest tactical F4 family; keep a small target portfolio."
    if verdict == "F3_TACTICAL_BRIDGE_SEARCH_LIMITED":
        return "Analyse remaining-suit access at g141; do not add wall time."
    if verdict == "F3_TACTICAL_BRIDGE_NO_F4":
        return "The missing abstraction is deeper than fixed-suit cash-out; analyse F3 topology."
    return "Do not promote; diagnose the g141 root contract."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "F3_TACTICAL_BRIDGE_CONTRACT_FAILURE"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F3_TACTICAL_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("LOAD g141 from v0.78 artefact", flush=True)
    g141 = verify_g141_root()
    print(
        f"G141 ok={g141.get('ok')} F={g141.get('foundations')} h={g141.get('assembly_h')} "
        f"f={g141.get('assembly_f')} slack={g141.get('slack')} ready={g141.get('ready_suits')}",
        flush=True,
    )
    if not g141.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "F3_TACTICAL_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": g141.get("reason"),
            "g141": g141,
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT F3_TACTICAL_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    _write_json(PROG, {"phase": "stage_a", "ready": g141.get("ready_suits")})
    f3 = {"g": 141, "ordered_digest": g141["ordered_digest"], "full_actions": []}
    print(
        f"BRIDGE Stage A {len(g141.get('ready_suits') or [])} x {STAGE_A_S}s ceiling=186",
        flush=True,
    )
    bridge = run_tactical_bridge(f3)
    print(
        f"BRIDGE n_f4={bridge.get('n_f4')} first={bridge.get('first_f4_target')}@{_fmt(bridge.get('first_f4_s'))}s "
        f"cheap g={bridge.get('cheapest_f4_g')} promoted={bridge.get('promoted_suits')} "
        f"t={bridge.get('elapsed_s'):.1f}s",
        flush=True,
    )

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if bridge.get("any_f4") and remain >= 5.0:
        print(f"CONTINUE F4 n={bridge['n_f4']} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "f4_continuation", "n_f4": bridge.get("n_f4"), "remain_s": remain})
        cont = search_f4_portfolio(opening, bridge["f4_roots"], time_s=remain, unique=SEARCH_UNIQUE)
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations} t={cont.elapsed_s:.1f}s",
            flush=True,
        )
    elif not bridge.get("any_f4"):
        print("NO F4: skip generic F3 continuation", flush=True)

    improved = False
    replay_ok = bool(cont.replay_ok) if cont is not None else False
    replay_g = None if cont is None else cont.replay_g
    terminal_lineage = None
    provenance = None
    if cont is not None and cont.solved and cont.solution_actions and int(cont.solution_g or 10**9) < 187:
        print("PROVENANCE recover g141 after candidate", flush=True)
        root = reconstruct_g128_root(opening)
        provenance = recover_g141(opening, root["post"]) if root.get("ok") else {"ok": False}
        if provenance.get("ok"):
            prefix = as_actions(provenance["hit"]["full_actions"])
            suffix = as_actions(cont.solution_actions)
            full = prefix + suffix
            end = opening.clone()
            replay_g = replay_actions(end, list(full))
            replay_ok = (
                replay_g == int(cont.solution_g)
                and end.is_solved()
                and sum(1 for a in full if is_deal(a)) == 5
            )
            if replay_ok:
                save_solution(full, FIX, g=int(cont.solution_g), label="Autonomous v0.79 F3 tactical bridge")
                terminal_lineage = foundation_progression(opening, list(full))
                _write_json(
                    META,
                    {
                        "g": int(cont.solution_g),
                        "replay_g": replay_g,
                        "replay_ok": True,
                        "parent_incumbent": 187,
                        "g128_tactical_prefix_source": "v0.71",
                        "f3_experimental_root_source": "v0.78",
                        "g141_digest": g141["ordered_digest"],
                        "chosen_f4_target": bridge.get("cheapest_f4_target"),
                        "tactical_bridge_terminal_g": bridge.get("cheapest_f4_g"),
                        "stock_empty_continuation_source": "v0.79",
                        "canonical_input": False,
                    },
                )
                improved = True
        else:
            replay_ok = False

    tracker = getattr(cont, "snapshot_tracker", None) if cont is not None else None
    frontier_list = [
        {
            "F": 3,
            "g": 141,
            "h": 33,
            "f": 174,
            "slack": assembly_slack(186, 174),
            "face_down": 2,
            "empty_n": 2,
            "legal": 41,
            "boundaries": 28,
            "provenance": "v0.78 cheapest F3",
            "elapsed_s": 0.0,
        }
    ]
    if tracker is not None:
        for n, rec in sorted((tracker.cheap_F or {}).items()):
            f = rec.get("f") or rec.get("assembly_f")
            frontier_list.append(
                {
                    "F": int(n),
                    "g": rec.get("g"),
                    "h": rec.get("h") or rec.get("assembly_h"),
                    "f": f,
                    "slack": None if f is None else assembly_slack(186, int(f)),
                    "face_down": rec.get("face_down"),
                    "empty_n": rec.get("empty_n"),
                    "legal": rec.get("legal"),
                    "boundaries": rec.get("boundaries"),
                    "provenance": "v0.79 continuation",
                    "elapsed_s": rec.get("elapsed_s"),
                    "ordered_digest": rec.get("ordered_digest"),
                }
            )
    else:
        for rec in bridge.get("f4_roots") or []:
            frontier_list.append(
                {
                    "F": rec.get("foundations"),
                    "g": rec.get("g"),
                    "h": rec.get("assembly_h"),
                    "f": rec.get("assembly_f"),
                    "slack": rec.get("slack"),
                    "face_down": rec.get("face_down"),
                    "empty_n": rec.get("empty_n"),
                    "legal": rec.get("legal_tableau"),
                    "boundaries": rec.get("boundaries"),
                    "provenance": f"tactical {rec.get('tactical_target')}",
                    "elapsed_s": None,
                }
            )

    max_f = 3
    if bridge.get("n_f4"):
        max_f = max(max_f, max(int(r.get("foundations") or 4) for r in bridge.get("f4_roots") or [{"foundations": 4}]))
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
        "slack_f2": assembly_slack(186, 172),
        "slack_f3": assembly_slack(186, 174),
        "wall_s": time.perf_counter() - wall0,
        "elapsed_s": None if cont is None else cont.elapsed_s,
        "unique": None if cont is None else cont.unique,
        "expanded": None if cont is None else cont.expanded,
        "generated": None if cont is None else cont.generated,
        "stop_reason": None if cont is None else cont.stop_reason,
        "max_foundations": max_f,
        "solved": bool(cont.solved) if cont is not None else False,
        "solution_g": None if cont is None else cont.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": bool(cont.accounting_fail) if cont is not None else False,
        "peak_rss_mb": None if cont is None else cont.peak_rss_mb,
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
            "n_f4": bridge.get("n_f4"),
            "any_f4": bridge.get("any_f4"),
            "cheapest_f4_g": bridge.get("cheapest_f4_g"),
            "cheapest_f4_h": bridge.get("cheapest_f4_h"),
            "cheapest_f4_f": bridge.get("cheapest_f4_f"),
            "cheapest_f4_target": bridge.get("cheapest_f4_target"),
            "first_f4_s": bridge.get("first_f4_s"),
            "first_f4_g": bridge.get("first_f4_g"),
            "first_f4_target": bridge.get("first_f4_target"),
            "f4_roots": slim_terms(bridge.get("f4_roots")),
        },
        "frontier_list": frontier_list,
        "snapshots": [] if tracker is None else tracker.snapshots,
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "bound_perf": None if cont is None else {
            "prunes": cont.lower_bound_prunes,
            "calls": cont.lower_bound_calls,
            "seconds": cont.lower_bound_s,
            "prunes_by_F": dict(cont.prunes_by_F or {}),
        },
        "terminal_lineage": terminal_lineage,
        "provenance_recovered": None if provenance is None else provenance.get("ok"),
        "incumbent_updated": improved,
        "v078_compare": {
            "root": "F2 g129",
            "time_s": 900,
            "unique": 105020,
            "expanded": 9762,
            "cheapest_F3_g": 141,
            "F4": None,
        },
        "envelope": {"time_s": TOTAL_S, "ceiling": BRIDGE_CEILING, "rss_abort_mb": SEARCH_RSS_MB, "stage_a_s": STAGE_A_S, "stage_b_n": STAGE_B_N},
    }
    verdict, reason = choose_bridge_verdict(payload)
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
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "n_f4": bridge.get("n_f4"),
            "cheapest_f4_g": bridge.get("cheapest_f4_g"),
            "max_foundations": max_f,
            "solution_g": payload.get("solution_g"),
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
