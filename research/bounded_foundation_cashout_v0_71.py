#!/usr/bin/env python3
"""v0.71: bounded tactical foundation cash-out from the rows=1 epoch entry.

One focused tableau-only probe. Canonical 172 is not read. The autonomous
192 suffix is evaluation-only after search.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal_preview import compact_preview, preview_next_deal
from spider.foundation_cashout import (
    CLASS_SLACK_G,
    PORTFOLIO_LIMIT,
    TACTICAL_CEILING,
    TACTICAL_LANES,
    TACTICAL_RSS_MB,
    TACTICAL_TIME_S,
    TACTICAL_UNIQUE,
    choose_tactical_verdict,
    classify_vs_incumbent,
    replay_incumbent_suffix_for_eval,
    replay_to_stock_rows,
    require_eval_phase,
    search_foundation_cashout,
    select_tactical_target,
    serialized_tactical_root,
    target_metric_snapshot,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, verify_autonomous_192
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, dump_actions, is_deal, stock_rows
from spider.solution_forensics import load_opening
from spider.whole_game_anytime import opening_state

EXPERIMENT = "bounded_foundation_cashout_v0_71"
BASE_SHA = "fef37d19ed17baafa0e5cce55d94f9be7389beaa"
BRANCH = "agent/bounded-foundation-cashout-v0-71"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "bounded_foundation_cashout_progress_v0_71.json"
CONTINUATION = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"


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


def _interpretation(verdict: str) -> str:
    if verdict == "TACTICAL_CASHOUT_FINDS_CHEAPER_F2":
        return (
            "A generic bounded cash-out probe independently completed the "
            "rank-1 ready suit cheaper than the autonomous 192 suffix."
        )
    if verdict == "TACTICAL_CASHOUT_RECOVERS_F2_CLASS":
        return (
            "READINESS already knew the suit. The missing mechanism is a short "
            "goal-directed tactical search that may cross non-monotonic valleys."
        )
    if verdict == "TACTICAL_CASHOUT_FINDS_EXPENSIVE_F2":
        return (
            "The planner can cash out the rank-1 suit but not yet at the "
            "incumbent cost class; ordering, not target selection, is the gap."
        )
    if verdict == "TACTICAL_CASHOUT_SEARCH_LIMITED":
        return (
            "The envelope expired with structural progress and no completed "
            "target foundation. Efficiency, not the readiness model, is next."
        )
    if verdict == "TACTICAL_CASHOUT_NO_FOUNDATION":
        return (
            "Short-horizon tactical search did not convert the ready suit. "
            "The missing knowledge is deeper than a local cash-out probe."
        )
    return "Contract failure; do not interpret search geometry."


def finalize_payload(payload: dict) -> dict:
    search = payload.get("search") or {}
    if payload.get("cheapest_g") is None:
        payload["cheapest_g"] = search.get("cheapest_g")
    if payload.get("unique") is None:
        payload["unique"] = search.get("unique")
    if payload.get("expanded") is None:
        payload["expanded"] = search.get("expanded")
    if not payload.get("stop_reason"):
        payload["stop_reason"] = search.get("stop_reason")
    verdict, reason = choose_tactical_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    payload["next_recommendation"] = _next_recommendation(verdict)
    payload["interpretation"] = _interpretation(verdict)
    return payload


def _next_recommendation(verdict: str) -> str:
    if verdict == "TACTICAL_CASHOUT_FINDS_CHEAPER_F2":
        return (
            "v0.72 should integrate bounded tactical cash-out probes into the "
            "rows=1 whole-game scheduler, using selected ready-state roots."
        )
    if verdict == "TACTICAL_CASHOUT_RECOVERS_F2_CLASS":
        return (
            "v0.72 should integrate bounded tactical cash-out probes into the "
            "rows=1 whole-game scheduler, using selected ready-state roots."
        )
    if verdict == "TACTICAL_CASHOUT_FINDS_EXPENSIVE_F2":
        return (
            "Analyse the tactical path and improve target-search ordering "
            "before whole-game integration."
        )
    if verdict == "TACTICAL_CASHOUT_SEARCH_LIMITED":
        return "Improve tactical search algorithm/efficiency; do not widen whole-game runtime."
    if verdict == "TACTICAL_CASHOUT_NO_FOUNDATION":
        return (
            "The missing knowledge is deeper than short-horizon planning; "
            "revisit operational viability."
        )
    return "Fix the rules/accounting/identity/search-firewall contract before continuing."


def write_report(p: dict) -> None:
    root = p.get("tactical_root") or {}
    tgt = p.get("target") or {}
    search = p.get("search") or {}
    path = p.get("path_trace") or {}
    cmp_ = p.get("incumbent_compare") or {}
    preview = p.get("deal_preview_compare") or {}
    nm = path.get("nonmonotonic_steps") or []
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "## Why this differs from READINESS",
        "",
        "READINESS answers: which currently-ready suit looks best in this state?",
        "TACTICAL CASH-OUT answers: given that suit as a fixed short-term objective, "
        "which sequence of legal actions reaches its foundation?",
        "Intermediate operational keys may worsen. Monotonic improvement is not required.",
        "",
        "## Search firewall",
        "",
        "Search used only the autonomous 192 prefix up to the rows=1 epoch-entry, "
        "that exact state, its prefix g, and generic operational analysis of that state. "
        "The 192 suffix, the known F2 digest, and canonical 172 were not available "
        "during search.",
        "",
        "## Exact tactical root",
        "",
        f"- absolute g = {root.get('g')}",
        f"- F = {root.get('foundations')}",
        f"- fd = {root.get('face_down')}",
        f"- stock rows = {root.get('stock_rows')}",
        f"- deals in prefix = {root.get('deals')}",
        f"- legal mobility = {root.get('legal_mobility')}",
        f"- ordered digest = `{root.get('ordered_digest')}`",
        f"- identity is ordered pre-stock = {root.get('identity_is_ordered')}",
        "",
        "## Generic target selection",
        "",
        f"- rule = `rank_ready_suits(state)['best']['suit']`",
        f"- target suit = `{tgt.get('suit')}` (telemetry only; not a policy literal)",
        f"- n_ready = {tgt.get('n_ready')}",
        f"- ready suits = {tgt.get('ready_suits')}",
        f"- cover = {tgt.get('cover')}",
        f"- blockers = {tgt.get('blockers')}",
        f"- K/A access = {tgt.get('k_access')} / {tgt.get('a_access')}",
        f"- gap = {tgt.get('gap')}",
        f"- merge edges = {tgt.get('merge_edges')}",
        f"- operational key = {tgt.get('operational_key')}",
        "",
        "## Tactical lanes",
        "",
        "- COST: absolute g",
        "- TARGET_ASSEMBLY: cover, inaccessible joins, K/A access, gap, merge edges, blockers, g",
        "- TARGET_ACCESS: K/A blocker burden, buried/exposed components, workspace, g",
        "",
        "## Focused envelope",
        "",
        f"- time = {search.get('time_limit_s')} s",
        f"- unique cap = {search.get('max_unique')}",
        f"- RSS abort = {search.get('rss_abort_mb')} MiB",
        f"- cost ceiling = {search.get('cost_ceiling')}",
        f"- Deal = forbidden",
        f"- harvest_slack = None (continue after first terminal)",
        "",
        "## Search totals",
        "",
        f"- unique = {search.get('unique')}",
        f"- expanded = {search.get('expanded')}",
        f"- generated = {search.get('generated')}",
        f"- duplicate skips = {search.get('duplicate_skips')}",
        f"- stale skips = {search.get('stale_skips')}",
        f"- expansions/sec = {search.get('expansions_per_s')}",
        f"- elapsed = {search.get('elapsed_s')} s",
        f"- stop = {search.get('stop_reason')}",
        f"- lane expansions = {search.get('lane_exp')}",
        f"- first target foundation g = {search.get('first_g')} at t={search.get('first_s')} s",
        f"- cheapest target foundation g = {search.get('cheapest_g')}",
        f"- delta_g = {search.get('delta_g')}",
        f"- distinct terminals = {search.get('n_terminals')}",
        f"- portfolio size = {search.get('portfolio_size')}",
        f"- cheapest action count = {search.get('n_actions')}",
        "",
        "## Cheapest path target-metric evolution",
        "",
    ]
    for step in path.get("steps") or []:
        lines.append(
            f"- g={step.get('absolute_g')} mw={step.get('step_mw')} "
            f"fd={step.get('fd')} empty={step.get('empties')} "
            f"legal={step.get('legal_mobility')} cover={step.get('target_cover')} "
            f"blockers={step.get('target_blockers')} K={step.get('target_k_access')} "
            f"A={step.get('target_a_access')} gap={step.get('target_gap')} "
            f"merge={step.get('target_merge_edges')} worsened={step.get('worsened')}"
        )
    if not path.get("steps"):
        lines.append("- no cash-out path")
    lines.extend(
        [
            "",
            "## Non-monotonic steps",
            "",
            f"n = {path.get('n_nonmonotonic')}",
        ]
    )
    if not nm:
        lines.append("None identified on the cheapest successful path.")
    for step in nm:
        lines.append(
            f"- i={step.get('i')} g={step.get('absolute_g')} action={step.get('action')} "
            f"worsened={step.get('worsened')}"
        )
    lines.extend(
        [
            "",
            "## After-run incumbent comparison",
            "",
            f"- planner target = `{cmp_.get('planner_target')}`",
            f"- incumbent cashed = `{cmp_.get('cashed_suit')}` at g={cmp_.get('foundation_g')}",
            f"- planner cheapest g = {cmp_.get('planner_g')}",
            f"- incumbent action count = {cmp_.get('n_actions')}",
            f"- planner action count = {search.get('n_actions')}",
            f"- terminal same state = {cmp_.get('same_state')}",
            f"- classification = {cmp_.get('classification')}",
            "",
            "## Deal-preview comparison",
            "",
            f"- planner preview = {preview.get('planner')}",
            f"- incumbent preview = {preview.get('incumbent')}",
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
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(str(x) for x in lines) + "\n", encoding="utf-8")


def main() -> dict:
    opening, _raw, _labels = load_opening()
    print("VERIFY autonomous 192 (incumbent file, not search input)", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "contract_fail": True,
            "contract_reason": "autonomous 192 incumbent failed replay",
            "verdict": "TACTICAL_CASHOUT_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT TACTICAL_CASHOUT_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("PREFIX replay to rows=1 epoch entry; discard suffix", flush=True)
    full_actions = list(inc["actions"])
    root = replay_to_stock_rows(opening, full_actions, target_rows=1)
    prefix_n = int(root["n_prefix"])
    root_g = int(root["g"])
    del full_actions
    del inc
    ser = serialized_tactical_root(root)
    state = unpack_state(bytes.fromhex(ser["ordered_digest"]))
    if (
        root_g != 123
        or ser["foundations"] != 1
        or ser["face_down"] != 2
        or ser["stock_rows"] != 1
        or pack_state(state).hex() != ser["ordered_digest"]
        or pack_whole_game_identity(state) != pack_state(state)
    ):
        payload = {
            "experiment": EXPERIMENT,
            "contract_fail": True,
            "contract_reason": "rows=1 tactical root failed verification",
            "tactical_root": ser,
            "verdict": "TACTICAL_CASHOUT_CONTRACT_FAILURE",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT TACTICAL_CASHOUT_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    target = select_tactical_target(state, root_g)
    target_out = {
        k: target.get(k)
        for k in (
            "suit",
            "n_ready",
            "ready_suits",
            "operational_key",
            "cover",
            "blockers",
            "k_access",
            "a_access",
            "gap",
            "merge_edges",
            "compact",
        )
    }
    print(
        f"ROOT g={root_g} F={ser['foundations']} fd={ser['face_down']} "
        f"rows={ser['stock_rows']} deals={ser['deals']} legal={ser['legal_mobility']}",
        flush=True,
    )
    print(
        f"TARGET rank1 suit={target_out['suit']} ready={target_out['ready_suits']} "
        f"cover={target_out['cover']} blockers={target_out['blockers']}",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "phase": "root_verified",
            "g": root_g,
            "foundations": ser["foundations"],
            "face_down": ser["face_down"],
            "target_suit": target_out["suit"],
            "n_ready": target_out["n_ready"],
        },
    )

    last_prog = [0.0]

    def on_progress(progress, _st, g, _node_i):
        now = time.perf_counter()
        if now - last_prog[0] < 10.0 and progress.n_target_terminals == 0:
            return
        if now - last_prog[0] < 5.0 and progress.n_target_terminals > 0:
            return
        last_prog[0] = now
        _write_json(
            PROG,
            {
                "phase": "search",
                "elapsed_s": now - progress.started,
                "g": g,
                "progress": progress.as_dict(),
            },
        )

    print(
        f"SEARCH tactical cash-out ceiling={TACTICAL_CEILING} "
        f"t={TACTICAL_TIME_S}s unique={TACTICAL_UNIQUE} no Deal",
        flush=True,
    )
    t0 = time.perf_counter()
    res = search_foundation_cashout(
        ordered_digest=ser["ordered_digest"],
        root_g=root_g,
        target_suit=target_out["suit"],
        max_unique=TACTICAL_UNIQUE,
        time_limit_s=TACTICAL_TIME_S,
        rss_abort_mb=TACTICAL_RSS_MB,
        cost_ceiling=TACTICAL_CEILING,
        portfolio_limit=PORTFOLIO_LIMIT,
        on_progress=on_progress,
    )
    wall = time.perf_counter() - t0
    exp_s = 0.0 if not res.elapsed_s else res.expanded / float(res.elapsed_s)
    print(
        f"SEARCH stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"first_g={res.first_g} cheapest_g={res.cheapest_g} "
        f"terminals={len(res.terminals)} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    print("EVAL incumbent suffix", flush=True)
    require_eval_phase("incumbent suffix comparison")
    eval_opening = opening_state()
    eval_actions = parse_moves_file(V067)
    prefix_ok = replay_actions(eval_opening.clone(), as_actions(root["prefix_actions"])) == root_g
    inc_suffix = replay_incumbent_suffix_for_eval(
        eval_opening,
        eval_actions,
        prefix_n=prefix_n,
        root_g=root_g,
    )
    planner_preview = None
    if res.cheapest_digest:
        cheapest_state = unpack_state(bytes.fromhex(res.cheapest_digest))
        planner_preview = compact_preview(preview_next_deal(cheapest_state, pre_g=res.cheapest_g))
    compare = {
        "planner_target": res.target_suit,
        "cashed_suit": inc_suffix.get("cashed_suit"),
        "foundation_g": inc_suffix.get("foundation_g"),
        "planner_g": res.cheapest_g,
        "n_actions": inc_suffix.get("n_actions"),
        "planner_n_actions": len(res.path),
        "incumbent_digest": inc_suffix.get("ordered_digest"),
        "planner_digest": res.cheapest_digest,
        "same_state": bool(
            res.cheapest_digest and res.cheapest_digest == inc_suffix.get("ordered_digest")
        ),
        "fd": inc_suffix.get("fd"),
        "planner_fd": None if not res.portfolio else res.portfolio[0].get("fd"),
        "legal_mobility": inc_suffix.get("legal_mobility"),
        "visible_components": inc_suffix.get("visible_components"),
        "classification": classify_vs_incumbent(
            {"cheapest_g": res.cheapest_g, "cheapest_digest": res.cheapest_digest},
            inc_suffix,
        ),
        "target_matches_incumbent": res.target_suit == inc_suffix.get("cashed_suit"),
        "prefix_ok": prefix_ok,
    }
    deal_preview_compare = {
        "planner": planner_preview,
        "incumbent": inc_suffix.get("deal_preview"),
    }

    kernel = res.kernel
    search = {
        "time_limit_s": TACTICAL_TIME_S,
        "max_unique": TACTICAL_UNIQUE,
        "rss_abort_mb": TACTICAL_RSS_MB,
        "cost_ceiling": TACTICAL_CEILING,
        "lanes": list(TACTICAL_LANES),
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "stale_skips": res.stale_skips,
        "expansions_per_s": round(exp_s, 3),
        "elapsed_s": res.elapsed_s,
        "wall_s": wall,
        "stop_reason": res.stop_reason,
        "lane_exp": res.lane_exp,
        "lane_pops": None if kernel is None else dict(kernel.lane_pops),
        "first_g": res.first_g,
        "first_s": res.first_s,
        "cheapest_g": res.cheapest_g,
        "delta_g": res.delta_g,
        "n_terminals": len(res.terminals),
        "portfolio_size": len(res.portfolio),
        "n_actions": len(res.path),
        "peak_rss_mb": None if kernel is None else kernel.peak_rss_mb,
        "min_g": None if kernel is None else kernel.min_g,
        "max_g": None if kernel is None else kernel.max_g,
        "min_live_g": None if kernel is None else kernel.min_live_g,
    }
    path_trace = res.path_trace or {}
    if res.found:
        _write_json(
            CONTINUATION,
            {
                "note": "tactical continuation only; not a complete solution",
                "root_g": root_g,
                "terminal_g": res.cheapest_g,
                "delta_g": res.delta_g,
                "target_suit": res.target_suit,
                "n_prefix": prefix_n,
                "tactical_actions": dump_actions(res.path),
                "terminal_digest": res.cheapest_digest,
            },
        )

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "search_saw_suffix": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "tactical_root": ser,
        "target": target_out,
        "root_cover": target_out.get("cover"),
        "search": search,
        "progress": res.progress,
        "path_trace": path_trace,
        "portfolio": res.portfolio,
        "incumbent_compare": compare,
        "deal_preview_compare": deal_preview_compare,
        "class_slack_g": CLASS_SLACK_G,
        "contract_fail": not prefix_ok,
        "contract_reason": None if prefix_ok else "prefix replay mismatch after search",
        "cheapest_g": res.cheapest_g,
        "unique": res.unique,
        "expanded": res.expanded,
        "stop_reason": res.stop_reason,
    }
    payload = finalize_payload(payload)
    _write_json(RESULT, _jsonable(payload))
    _write_json(
        PROG,
        {"phase": "complete", "verdict": payload["verdict"], "cheapest_g": res.cheapest_g},
    )
    write_report(payload)
    print(f"VERDICT {payload['verdict']}", flush=True)
    print("DONE", flush=True)
    return payload


def reclassify_from_artefact() -> dict:
    """Rebuild verdict/report from a finished search artefact. Does not search."""

    payload = json.loads(RESULT.read_text(encoding="utf-8"))
    root = payload.get("tactical_root") or {}
    if CONTINUATION.exists() and root.get("ordered_digest"):
        from spider.research_actions import as_actions as load_actions
        from spider.foundation_cashout import trace_tactical_path

        cont = json.loads(CONTINUATION.read_text(encoding="utf-8"))
        state = unpack_state(bytes.fromhex(root["ordered_digest"]))
        payload["path_trace"] = trace_tactical_path(
            state,
            int(root["g"]),
            load_actions(cont.get("tactical_actions") or []),
            cont.get("target_suit") or (payload.get("target") or {}).get("suit"),
        )
    payload = finalize_payload(payload)
    _write_json(RESULT, _jsonable(payload))
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": payload["verdict"],
            "cheapest_g": payload.get("cheapest_g"),
        },
    )
    write_report(payload)
    print(f"VERDICT {payload['verdict']}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--reclassify":
        reclassify_from_artefact()
    else:
        main()
