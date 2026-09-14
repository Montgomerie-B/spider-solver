#!/usr/bin/env python3
"""v0.79: F3→F4 tactical bridge from the v0.78 g141 state.

Canonical 172 is not a search input. Not a whole-game opening campaign.
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
    RECOVER_S,
    TACTICAL_PER_S,
    TOTAL_S,
    choose_bridge_verdict,
    expected_g141_digest,
    inspect_f3_state,
    probe_ready_suits,
    recover_g141,
    search_f4_portfolio,
)
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, replay_actions
from spider.research_actions import as_actions, is_deal
from spider.solution_forensics import load_opening
from spider.state_convergence import foundation_progression
from spider.whole_game_epoch_scheduler import (
    SEARCH_RSS_MB,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

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


def slim_hit(hit: dict) -> dict:
    if not hit:
        return {}
    return {k: hit.get(k) for k in (
        "g", "foundations", "face_down", "empty_n", "legal_tableau",
        "assembly_h", "assembly_f", "ordered_digest",
    )}


def slim_roots(roots: list) -> list:
    out = []
    for r in roots or []:
        out.append({
            "g": r.get("g"),
            "foundations": r.get("foundations"),
            "face_down": r.get("face_down"),
            "h": r.get("assembly_h"),
            "f": r.get("assembly_f"),
            "legal": r.get("legal_tableau"),
            "target": r.get("tactical_target"),
            "ordered_digest": r.get("ordered_digest"),
        })
    return out


def write_report(p: dict) -> None:
    rec = p.get("recover") or {}
    br = p.get("bridge") or {}
    insp = br.get("inspect") or p.get("inspect") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "Focused F3→F4 tactical bridge from the exact v0.78 g141 state.",
        "Not a whole-game opening campaign. Canonical 172 was not a search input.",
        "",
        "## F3 root",
        "",
        f"* recover ok={rec.get('ok')} g={(rec.get('hit') or {}).get('g')} t={_fmt(rec.get('elapsed_s'))}s "
        f"unique={rec.get('unique')} stop=`{rec.get('stop_reason')}`",
        f"* F={insp.get('foundations')} fd={insp.get('face_down')} empty={insp.get('empty_n')} "
        f"legal={insp.get('legal_tableau')} h={insp.get('assembly_h')} f={insp.get('assembly_f')}",
        f"* founded {insp.get('foundation_suits')} ready {insp.get('ready_suits')} best={insp.get('best_suit')}",
        "",
        "## Per-suit probes",
        "",
        "| suit | founded | found | cheapest g | Δg | first s | terminals | unique | t s |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for pr in br.get("probes") or []:
        lines.append(
            f"| {pr.get('suit')} | {pr.get('already_founded')} | {pr.get('found')} | "
            f"{pr.get('cheapest_g')} | {pr.get('delta_g')} | {_fmt(pr.get('first_s'))} | "
            f"{pr.get('n_terminals')} | {pr.get('unique')} | {_fmt(pr.get('elapsed_s'))} |"
        )
    lines += [
        "",
        f"F4 portfolio n={br.get('n_f4')} cheapest g={br.get('cheapest_f4_g')} "
        f"h={br.get('cheapest_f4_h')} target={br.get('cheapest_f4_target')}",
        "",
        "## Continuation",
        "",
        f"max F {p.get('max_foundations')} unique {p.get('unique')} expanded {p.get('expanded')} "
        f"t={_fmt(p.get('elapsed_s'))}s stop=`{p.get('stop_reason')}` solution_g={p.get('solution_g')}",
        "",
        str(p.get("frontier_list") or []),
        "",
        "## Lanes / assembly",
        "",
        str(p.get("lanes") or {}),
        str(p.get("bound_perf") or {}),
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
    if verdict == "F3_BRIDGE_COST_IMPROVED":
        return "Promote the new incumbent and make this F3→F4 bridge the machine control."
    if verdict == "F3_BRIDGE_REACHES_F4":
        return "Concentrate frozen endgame search on the cheapest tactical F4, not another pre-Deal heuristic."
    if verdict == "F3_BRIDGE_SOLVES_NO_GAIN":
        return "Keep the bridge; return to integrated search with better final-epoch time on this lineage."
    if verdict == "F3_BRIDGE_NO_F4":
        return "Diagnose remaining-suit access at g141; do not add wall time by default."
    return "Do not promote; diagnose the g141 reconstruction contract."


def main() -> dict:
    opening, _raw, _labels = load_opening()
    wall0 = time.perf_counter()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != 187:
        payload = {"experiment": EXPERIMENT, "root_fail": True, "verdict": "F3_BRIDGE_CONTRACT_FAILURE"}
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F3_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("RECONSTRUCT g129 then recover g141", flush=True)
    root = reconstruct_g128_root(opening)
    if not root.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "root_fail": True,
            "verdict": "F3_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": "g129 reconstruction failed",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT F3_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    _write_json(PROG, {"phase": "recovering_g141", "digest": expected_g141_digest()[:24]})
    recov = recover_g141(opening, root["post"], time_s=RECOVER_S)
    print(
        f"RECOVER ok={recov.get('ok')} g={(recov.get('hit') or {}).get('g')} "
        f"t={recov.get('elapsed_s'):.1f}s unique={recov.get('unique')} stop={recov.get('stop_reason')}",
        flush=True,
    )
    if not recov.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "branch": BRANCH,
            "root_fail": True,
            "verdict": "F3_BRIDGE_CONTRACT_FAILURE",
            "contract_reason": recov.get("reason"),
            "recover": {**recov, "hit": slim_hit(recov.get("hit") or {})},
            "policy_reads_canonical": False,
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT F3_BRIDGE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    f3 = recov["hit"]
    inspect = inspect_f3_state(f3["ordered_digest"], g=int(f3["g"]))
    print(
        f"F3 ready={inspect.get('ready_suits')} best={inspect.get('best_suit')} "
        f"h={inspect.get('assembly_h')} legal={inspect.get('legal_tableau')}",
        flush=True,
    )
    _write_json(PROG, {"phase": "tactical_probes", "ready": inspect.get("ready_suits")})
    remain = max(8.0, TOTAL_S - (time.perf_counter() - wall0) - 8.0)
    n_suits = max(1, len(inspect.get("ready_suits") or []))
    per_s = min(TACTICAL_PER_S, remain / (n_suits + 0.5))
    print(f"BRIDGE {n_suits} suits x {per_s:.1f}s ceiling=186", flush=True)
    bridge = probe_ready_suits(opening, f3, time_s=per_s)
    print(
        f"BRIDGE n_f4={bridge.get('n_f4')} cheapest={bridge.get('cheapest_f4_g')} "
        f"target={bridge.get('cheapest_f4_target')} t={bridge.get('elapsed_s'):.1f}s",
        flush=True,
    )

    cont = None
    remain = max(0.0, TOTAL_S - (time.perf_counter() - wall0))
    if bridge.get("any_f4") and remain >= 5.0:
        print(f"CONTINUE F4 portfolio n={bridge['n_f4']} t={remain:.1f}s", flush=True)
        _write_json(PROG, {"phase": "f4_continuation", "n_f4": bridge.get("n_f4"), "remain_s": remain})
        cont = search_f4_portfolio(
            opening,
            bridge["f4_roots"],
            time_s=remain,
            unique=SEARCH_UNIQUE,
        )
        print(
            f"CONTINUE stop={cont.stop_reason} unique={cont.unique} exp={cont.expanded} "
            f"best={cont.solution_g} maxF={cont.max_foundations} t={cont.elapsed_s:.1f}s",
            flush=True,
        )

    improved = False
    replay_ok = bool(cont.replay_ok) if cont is not None else False
    replay_g = cont.replay_g if cont is not None else None
    terminal_lineage = None
    if cont is not None and cont.solved and cont.solution_actions:
        end = opening.clone()
        replay_g = replay_actions(end, list(cont.solution_actions))
        replay_ok = (
            replay_g == int(cont.solution_g)
            and end.is_solved()
            and sum(1 for a in cont.solution_actions if is_deal(a)) == 5
            and len(end.foundations) == 8
        )
        terminal_lineage = foundation_progression(opening, list(cont.solution_actions))
        if replay_ok and int(cont.solution_g) < 187:
            save_solution(cont.solution_actions, FIX, g=int(cont.solution_g), label="Autonomous v0.79 F3 tactical bridge")
            _write_json(
                META,
                {
                    "g": int(cont.solution_g),
                    "replay_g": replay_g,
                    "replay_ok": replay_ok,
                    "five_deals": True,
                    "parent_incumbent": 187,
                    "f3_source": "v0.78 g141",
                    "bridge": "per-suit tactical cash-out",
                    "canonical_input": False,
                },
            )
            improved = True

    tracker = getattr(cont, "snapshot_tracker", None) if cont is not None else None
    frontier_list = []
    if tracker is not None:
        for n, rec in sorted((tracker.cheap_F or {}).items()):
            frontier_list.append({"F": int(n), **{k: v for k, v in rec.items() if k != "full_actions"}})
    max_f = 3
    if bridge.get("n_f4"):
        max_f = max(max_f, 4)
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
        "g129": {
            "g": root["post"].get("g"),
            "h": root["post"].get("assembly_h"),
            "legal": root["post"].get("legal_tableau"),
            "ordered_digest": root["post"].get("ordered_digest"),
        },
        "recover": {
            "ok": recov.get("ok"),
            "elapsed_s": recov.get("elapsed_s"),
            "unique": recov.get("unique"),
            "expanded": recov.get("expanded"),
            "stop_reason": recov.get("stop_reason"),
            "hit": slim_hit(f3),
        },
        "inspect": inspect,
        "bridge": {
            "inspect": inspect,
            "probes": bridge.get("probes"),
            "n_f4": bridge.get("n_f4"),
            "any_f4": bridge.get("any_f4"),
            "cheapest_f4_g": bridge.get("cheapest_f4_g"),
            "cheapest_f4_h": bridge.get("cheapest_f4_h"),
            "cheapest_f4_target": bridge.get("cheapest_f4_target"),
            "elapsed_s": bridge.get("elapsed_s"),
            "f4_roots": slim_roots(bridge.get("f4_roots")),
        },
        "frontier_list": frontier_list,
        "snapshots": [] if tracker is None else tracker.snapshots,
        "lanes": None if cont is None else {"expansions": cont.lane_exp},
        "bound_perf": None if cont is None else {
            "prunes": cont.lower_bound_prunes,
            "calls": cont.lower_bound_calls,
            "seconds": cont.lower_bound_s,
            "prunes_by_F": dict(cont.prunes_by_F or {}),
            "reconcile": reconcile_lower_bound_telemetry(cont),
        },
        "terminal_lineage": terminal_lineage,
        "incumbent_updated": improved,
        "envelope": {"time_s": TOTAL_S, "ceiling": BRIDGE_CEILING, "rss_abort_mb": SEARCH_RSS_MB},
    }
    verdict, reason = choose_bridge_verdict(payload)
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
            "n_f4": bridge.get("n_f4"),
            "solution_g": payload.get("solution_g"),
            "max_foundations": max_f,
        },
    )
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
