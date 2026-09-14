#!/usr/bin/env python3
"""v0.75: autonomous continuation table + whole-game optimisation.

Canonical 172 is evaluation only after search. Strategic/tactical policy
is unchanged; exact-state remaining-cost matching is added.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.autonomous_continuations import (
    build_autonomous_continuation_table,
    choose_continuation_verdict,
    search_with_continuation_table,
    table_built_ok,
)
from spider.deal_preview import clear_preview_cache, preview_cache_stats
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING, verify_autonomous_192
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import unpack_state
from spider.research_actions import is_deal
from spider.solution_forensics import (
    extract_epochs,
    instrumented_replay,
    load_opening,
    rehandling_summary,
)
from spider.state_convergence import V073_F2_DIGEST
from spider.whole_game_epoch_scheduler import (
    PORTFOLIO_WIDTH,
    SEARCH_RSS_MB,
    SEARCH_TIME_S,
    SEARCH_UNIQUE,
    reconcile_lower_bound_telemetry,
    save_solution,
)

EXPERIMENT = "autonomous_continuation_table_v0_75"
BASE_SHA = "0f4b55e433e8ad6722b2fc0266da5f590c81956f"
BRANCH = "agent/autonomous-continuation-table-v0-75"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
PROG = ROOT / "docs" / "research" / "autonomous_continuation_table_progress_v0_75.json"
FIX = ROOT / "solutions" / "4925153_autonomous_v0_75.moves"
META = ROOT / "solutions" / "4925153_autonomous_v0_75.json"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


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
        "g": rec.get("g"),
        "stock_rows": rec.get("stock_rows"),
        "face_down": rec.get("face_down"),
        "foundations": rec.get("foundations"),
        "empty_n": rec.get("empty_n"),
        "legal_tableau": rec.get("legal_tableau"),
        "assembly_h": rec.get("assembly_h"),
        "assembly_f": rec.get("assembly_f"),
        "elapsed_s": rec.get("elapsed_s"),
        "from_incumbent_ckpt": rec.get("from_incumbent_ckpt"),
        "portfolio_cat": rec.get("portfolio_cat"),
        "tactical_target": rec.get("tactical_target"),
    }


def forensic_route(opening, labels, path: Path, expected_g: int, name: str) -> dict:
    actions = parse_moves_file(path)
    trace = instrumented_replay(opening, actions, labels, expected_g=expected_g)
    epochs = extract_epochs(trace, opening, actions, labels)
    rehandle = rehandling_summary(trace)
    post = next((ep for ep in epochs if ep.get("label") == "post-SD5"), None)
    enter = (post or {}).get("enter") or {}
    post_g = enter.get("g")
    remaining = None if post_g is None else expected_g - int(post_g)
    h = None
    if enter.get("ordered_digest"):
        st = unpack_state(bytes.fromhex(enter["ordered_digest"]))
        h = int(stock_empty_assembly_h(st, int(post_g or 0)))
    waterfall = [
        {
            "label": ep.get("label"),
            "stock_rows": ep.get("stock_rows"),
            "enter_g": (ep.get("enter") or {}).get("g"),
            "exit_g": (ep.get("exit") or {}).get("g"),
            "delta_g": ep.get("delta_g"),
            "paid": ep.get("paid"),
            "foundations_enter": ep.get("foundations_enter"),
            "foundations_exit": ep.get("foundations_exit"),
            "fd_enter": (ep.get("enter") or {}).get("face_down"),
            "fd_exit": (ep.get("exit") or {}).get("face_down"),
            "legal_enter": (ep.get("enter") or {}).get("legal_tableau"),
            "empty_enter": ep.get("empty_enter"),
            "is_deal": bool(ep.get("is_deal")),
        }
        for ep in epochs
    ]
    return {
        "name": name,
        "g": expected_g,
        "post_sd5_g": post_g,
        "post_sd5_remaining": remaining,
        "post_sd5_fd": enter.get("face_down"),
        "post_sd5_F": enter.get("foundations"),
        "post_sd5_legal": enter.get("legal_tableau"),
        "post_sd5_empty": enter.get("empty_n"),
        "post_sd5_bonds": enter.get("same_suit_bonds"),
        "post_sd5_assembly_h": h,
        "post_sd5_assembly_f": None if h is None or post_g is None else int(post_g) + h,
        "rehandle_paid": rehandle.get("paid_mw_tagged_rehandle"),
        "rehandle_actions": rehandle.get("rehandle_actions"),
        "waterfall": waterfall,
    }


def write_report(p: dict) -> None:
    tbl = p.get("table") or {}
    foc = p.get("forensics") or {}
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"Verdict: `{p.get('verdict')}`",
        "",
        p.get("verdict_reason") or "",
        "",
        "## Continuation table",
        "",
        f"- sources={tbl.get('sources')}",
        f"- excluded={tbl.get('excluded')}",
        f"- n_entries={tbl.get('n_entries')} min_V={tbl.get('min_V')} build_s={tbl.get('build_s')}",
        f"- by_rows={tbl.get('by_stock_rows')} by_F={tbl.get('by_F')}",
        f"- F2 remaining={p.get('f2_V')} source={p.get('f2_source')}",
        "",
        "Keyed by ordered pack_state. Not SPS1. Not canonical. Not move ordering.",
        "",
        "## Envelope",
        "",
        str(p.get("envelope") or {}),
        "",
        "## Search",
        "",
        f"- unique={p.get('unique')} expanded={p.get('expanded')} generated={p.get('generated')}",
        f"- elapsed={p.get('elapsed_s')} stop={p.get('stop_reason')} maxF={p.get('max_foundations')}",
        f"- solved={p.get('solved')} g={p.get('solution_g')} replay_ok={p.get('replay_ok')}",
        f"- lookups={tbl.get('lookups')} hits={tbl.get('hits')} unique_matched={tbl.get('unique_matched')}",
        f"- equal_cost={tbl.get('equal_cost_hits')} cheaper_prefix={tbl.get('cheaper_prefix_hits')} worse={tbl.get('worse_prefix_hits')}",
        f"- best_prefix_saving={tbl.get('best_prefix_saving')} best_candidate={tbl.get('best_candidate')}",
        f"- splices_attempted={tbl.get('splices_attempted')} splices_ok={tbl.get('splices_ok')}",
        f"- lookup_s={tbl.get('lookup_s')} pct={p.get('lookup_pct')}",
        f"- lane expansions={p.get('lanes', {}).get('expansions')}",
        "",
        "## F frontier",
        "",
        str(p.get("frontier") or []),
        "",
        "## Improving splices",
        "",
        str(p.get("improving_hits") or []),
        "",
        "## 187 vs 172 forensics (evaluation only)",
        "",
        str({k: {kk: vv for kk, vv in (row or {}).items() if kk != "waterfall"} for k, row in foc.items()}),
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


def next_recommendation(verdict: str, p: dict) -> str:
    if verdict == "CONTINUATION_TABLE_COST_IMPROVED":
        return "Promote the cheaper continuation-table splice and rebuild V(S) from the new incumbent."
    if verdict == "CONTINUATION_TABLE_FINDS_CHEAPER_PREFIX_NO_BEST":
        return "Analyse why suffix economics prevent a sub-187 complete candidate."
    remaining = ((p.get("forensics") or {}).get("v0.74") or {}).get("post_sd5_remaining")
    canon_rem = ((p.get("forensics") or {}).get("canonical") or {}).get("post_sd5_remaining")
    if remaining and canon_rem and int(remaining) - int(canon_rem) >= 20:
        return (
            "The 187→172 gap is overwhelmingly post-SD5 conversion; next evaluate final-Deal "
            "roots by bounded stock-empty rollout / future cost rather than only one-step preview."
        )
    if verdict == "CONTINUATION_TABLE_NO_MATCHES":
        return "Keep the table; next optimisation should address post-SD5 future-state quality rather than exact convergence."
    if verdict == "CONTINUATION_TABLE_VALID_NO_IMPROVEMENT":
        return "Table matching is live; next optimisation should address post-SD5 future-state quality rather than exact convergence."
    return "Do not promote; diagnose the contract discrepancy."


def main() -> dict:
    opening, _raw, labels = load_opening()
    print("VERIFY autonomous 187", flush=True)
    inc = verify_autonomous_192(opening)
    if not inc.get("ok") or int(inc.get("g") or 0) != AUTONOMOUS_INCUMBENT_MW:
        payload = {
            "experiment": EXPERIMENT,
            "incumbent_fail": True,
            "verdict": "CONTINUATION_TABLE_CONTRACT_FAILURE",
            "contract_reason": "autonomous 187 incumbent failed replay",
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT CONTINUATION_TABLE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload

    print("BUILD continuation table from autonomous 198/192/191/187", flush=True)
    table = build_autonomous_continuation_table(
        opening, ceiling=CANDIDATE_CEILING, incumbent_g=AUTONOMOUS_INCUMBENT_MW
    )
    if not table_built_ok(table):
        payload = {
            "experiment": EXPERIMENT,
            "table_fail": True,
            "verdict": "CONTINUATION_TABLE_CONTRACT_FAILURE",
            "contract_reason": "autonomous continuation table failed to build",
            "table": table.stats(),
        }
        _write_json(RESULT, _jsonable(payload))
        write_report(payload)
        print("VERDICT CONTINUATION_TABLE_CONTRACT_FAILURE", flush=True)
        print("DONE", flush=True)
        return payload
    f2 = table.get(V073_F2_DIGEST)
    print(
        f"TABLE n={len(table.entries)} sources={len(table.sources)} build_s={table.build_s:.3f} "
        f"F2_V={None if f2 is None else f2.remaining_cost} F2_src={None if f2 is None else f2.source_solution}",
        flush=True,
    )
    _write_json(
        PROG,
        {
            "phase": "table_built",
            "n_entries": len(table.entries),
            "f2_V": None if f2 is None else f2.remaining_cost,
            "build_s": table.build_s,
        },
    )

    print("SEARCH whole-game + continuation table incumbent=187 ceiling=186 900s", flush=True)
    clear_preview_cache()
    t0 = time.perf_counter()
    res = search_with_continuation_table(opening=opening, table=table)
    print(
        f"DONE stop={res.stop_reason} unique={res.unique} expanded={res.expanded} "
        f"best={res.solution_g} maxF={res.max_foundations} hits={table.hits} "
        f"cheaper={table.cheaper_prefix_hits} t={res.elapsed_s:.1f}s",
        flush=True,
    )

    cheap = {str(k): slim_f(v) for k, v in sorted(res.foundations_cheap.items())}
    frontier = [slim_f(v) | {"F": n} for n, v in sorted(res.foundations_cheap.items())]
    improved = (
        res.solved
        and res.replay_ok
        and res.solution_g is not None
        and int(res.solution_g) < AUTONOMOUS_INCUMBENT_MW
        and res.solution_actions
    )
    replay_ok = bool(res.replay_ok)
    replay_g = res.replay_g
    hit = table.improving_hits[-1] if table.improving_hits else getattr(res, "continuation_hit", None)
    if improved:
        save_solution(
            res.solution_actions,
            FIX,
            g=int(res.solution_g),
            label="Autonomous v0.75 continuation-table solution",
        )
        end = opening.clone()
        replay_g = replay_actions(end, list(res.solution_actions))
        replay_ok = (
            replay_g == int(res.solution_g)
            and end.is_solved()
            and sum(1 for a in res.solution_actions if is_deal(a)) == 5
        )
        _write_json(
            META,
            {
                "g": int(res.solution_g),
                "replay_g": replay_g,
                "replay_ok": replay_ok,
                "route_construction": "continuation table splice"
                if table.improving_hits
                else "ordinary whole-game / tactical / endgame search",
                "continuation_table_contributed": bool(table.improving_hits),
                "continuation_source": None if not hit else hit.get("source"),
                "matched_digest": None if not hit else hit.get("digest"),
                "prefix_saving": None if not hit else hit.get("prefix_saving"),
                "known_suffix_cost": None if not hit else hit.get("remaining_cost"),
                "incumbent_parent": 187,
                "canonical_input": False,
            },
        )

    print("EVAL canonical and historical routes after search", flush=True)
    forensics = {
        "v0.59": forensic_route(opening, labels, V059, 198, "v0.59"),
        "v0.67": forensic_route(opening, labels, V067, 192, "v0.67"),
        "v0.74": forensic_route(opening, labels, V074, 187, "v0.74"),
        "canonical": forensic_route(opening, labels, CANON, 172, "canonical"),
    }
    lookup_pct = None if not res.elapsed_s else table.lookup_s / float(res.elapsed_s)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": BRANCH,
        "policy_reads_canonical": False,
        "incumbent_g": AUTONOMOUS_INCUMBENT_MW,
        "candidate_ceiling": CANDIDATE_CEILING,
        "record_mw": RECORD_MW_COST,
        "canonical_mw": CANONICAL_MW_COST,
        "table": table.stats(),
        "f2_V": None if f2 is None else f2.remaining_cost,
        "f2_source": None if f2 is None else f2.source_solution,
        "improving_hits": table.improving_hits,
        "useful_hits": table.useful_hits,
        "elapsed_s": res.elapsed_s,
        "wall_s": time.perf_counter() - t0,
        "lookup_pct": lookup_pct,
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "states_per_s": res.states_per_s,
        "stop_reason": res.stop_reason,
        "max_foundations": res.max_foundations,
        "min_f": res.min_f,
        "solved": res.solved,
        "solution_g": res.solution_g,
        "replay_ok": replay_ok,
        "replay_g": replay_g,
        "accounting_fail": res.accounting_fail,
        "foundations": {"cheap": cheap},
        "frontier": frontier,
        "lanes": {"expansions": res.lane_exp, "pops": res.lane_pops},
        "tactical": (res.epochs or [{}])[0].get("augment")
        if False
        else next((ep.get("augment") for ep in res.epochs if int(ep.get("stock_rows") or -1) == 1), {}),
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
        "preview_cache": preview_cache_stats(),
        "forensics": forensics,
        "envelope": {
            "time_s": SEARCH_TIME_S,
            "unique": SEARCH_UNIQUE,
            "rss_abort_mb": SEARCH_RSS_MB,
            "width": PORTFOLIO_WIDTH,
            "ceiling": CANDIDATE_CEILING,
        },
    }
    if improved:
        payload["improved_file"] = str(FIX.relative_to(ROOT)).replace("\\", "/")
    verdict, reason = choose_continuation_verdict(payload)
    payload["verdict"] = verdict
    payload["verdict_reason"] = reason
    a187 = forensics["v0.74"]
    a172 = forensics["canonical"]
    gap = None
    if a187.get("post_sd5_remaining") is not None and a172.get("post_sd5_remaining") is not None:
        gap = int(a187["post_sd5_remaining"]) - int(a172["post_sd5_remaining"])
    payload["interpretation"] = (
        reason
        + f" Autonomous post-SD5 remaining={a187.get('post_sd5_remaining')} (g={a187.get('post_sd5_g')}, h={a187.get('post_sd5_assembly_h')}); "
        f"canonical remaining={a172.get('post_sd5_remaining')} (g={a172.get('post_sd5_g')}, h={a172.get('post_sd5_assembly_h')}); "
        f"conversion-gap={gap}."
    )
    payload["next_recommendation"] = next_recommendation(verdict, payload)
    payload = _jsonable(payload)
    _write_json(RESULT, payload)
    _write_json(
        PROG,
        {
            "phase": "complete",
            "verdict": verdict,
            "solution_g": payload.get("solution_g"),
            "hits": table.hits,
            "cheaper_prefix_hits": table.cheaper_prefix_hits,
            "max_foundations": payload.get("max_foundations"),
        },
    )
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print("DONE", flush=True)
    return payload


if __name__ == "__main__":
    main()
