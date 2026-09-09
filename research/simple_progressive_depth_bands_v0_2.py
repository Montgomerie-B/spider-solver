#!/usr/bin/env python3
"""Depth-banded simple solver v0.2 on deal 4925153."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import (
    DEFAULT_DEPTH_BANDS,
    format_moves_text,
    solve_progressive,
)


EXPERIMENT = "simple_progressive_depth_bands_v0_2"
BASE_SHA = "de33d1468301afdb9072d6454ae68cf5a8297898"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOLUTION = ROOT / "solutions" / "4925153_simple_v0_2.moves.txt"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT

V01_E2 = {
    "expanded": 1_000_000,
    "unique": 999_478,
    "states_per_sec": 865.7,
    "max_depth": 5000,
    "first_foundation": False,
    "max_foundations": 0,
    "path_length": 80,
    "face_down": 6,
    "stock_rows": 4,
    "cost": 78,
    "deals_considered": 697_597,
    "deals_executed": 244,
}

PRIMARY = ("P1", 1_000_000, 1800.0)
OPTIONAL = ("P2", 3_000_000, 3600.0)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _replay_witness(opening: SpiderState, actions, cost: int) -> dict:
    if not actions:
        return {
            "path_length": 0,
            "cost": 0,
            "cost_matches": True,
            "foundations": len(opening.foundations),
            "face_down": sum(len(col.face_down) for col in opening.columns),
            "stock_rows": len(opening.stock) // 10,
            "solved": opening.is_solved(),
        }
    end = opening.clone()
    paid = replay_actions(end, list(actions))
    return {
        "path_length": len(actions),
        "cost": paid,
        "cost_matches": paid == cost,
        "foundations": len(end.foundations),
        "face_down": sum(len(col.face_down) for col in end.columns),
        "stock_rows": len(end.stock) // 10,
        "solved": end.is_solved(),
    }


def compact(opening: SpiderState, result) -> dict:
    stats = result.stats
    deals_per_100k = (
        100_000.0 * stats.deals_executed / max(1, stats.states_expanded)
    )
    return {
        "solved": result.solved,
        "stop_reason": result.stop_reason,
        "nodes": result.nodes,
        "elapsed_s": result.elapsed_s,
        "states_per_sec": result.states_per_sec,
        "pass_reached": result.pass_reached,
        "depth_bands_used": list(result.depth_bands_used),
        "max_foundations": result.max_foundations,
        "replay_ok": result.replay_ok,
        "stats": {
            "states_expanded": stats.states_expanded,
            "states_generated": stats.states_generated,
            "unique_exact_states": stats.unique_exact_states,
            "tt_hits": stats.tt_hits,
            "tt_hit_rate": stats.tt_hits / max(1, stats.tt_hits + stats.states_expanded),
            "tt_depth_prunes": stats.tt_depth_prunes,
            "tt_reopens": stats.tt_reopens,
            "duplicate_children": stats.duplicate_children,
            "path_cycles": stats.path_cycles,
            "inverses": stats.inverses,
            "max_depth": stats.max_depth,
            "considered_by_tier": list(stats.considered_by_tier),
            "expanded_by_tier": list(stats.expanded_by_tier),
            "deals_considered": stats.deals_considered,
            "deals_executed": stats.deals_executed,
            "deals_executed_per_100k": deals_per_100k,
            "deal_now_choices": stats.deal_now_choices,
            "prepared_deal_choices": stats.prepared_deal_choices,
            "prep_calls": stats.prep_calls,
            "prep_nodes": stats.prep_nodes,
            "first_foundation_node": stats.first_foundation_node,
            "first_foundation_depth": stats.first_foundation_depth,
            "first_foundation_pass": stats.first_foundation_pass,
            "peak_rss_mb": stats.peak_rss_mb,
            "expansions_by_depth_bucket": list(stats.expansions_by_depth_bucket),
            "states_by_stock_dealt": list(stats.states_by_stock_dealt),
            "unique_by_stock_dealt": list(stats.unique_by_stock_dealt),
            "deals_executed_from_stock": list(stats.deals_executed_from_stock),
            "unique_deal_parents": list(stats.unique_deal_parents),
            "band_pass_reports": list(stats.band_pass_reports),
        },
        "witnesses": {
            "reveal": _replay_witness(
                opening, result.best_reveal_actions, result.best_reveal_cost
            )
            | {
                "search_fd": result.best_reveal_fd,
                "search_stock": result.best_reveal_stock,
                "search_foundations": result.best_reveal_foundations,
                "search_depth": result.best_reveal_depth,
                "search_cost": result.best_reveal_cost,
            },
            "stock": _replay_witness(
                opening, result.best_stock_actions, result.best_stock_cost
            )
            | {
                "search_fd": result.best_stock_fd,
                "search_stock": result.best_stock_stock,
                "search_foundations": result.best_stock_foundations,
                "search_depth": result.best_stock_depth,
                "search_cost": result.best_stock_cost,
            },
            "foundation": _replay_witness(
                opening, result.best_foundation_actions, result.best_foundation_cost
            )
            | {
                "search_fd": result.best_foundation_fd,
                "search_stock": result.best_foundation_stock,
                "search_foundations": result.best_foundation_foundations,
                "search_depth": result.best_foundation_depth,
                "search_cost": result.best_foundation_cost,
            },
        },
        "first_foundation_path_length": len(result.first_foundation_actions),
        "opening_face_down": sum(len(col.face_down) for col in opening.columns),
        "opening_stock_rows": len(opening.stock) // 10,
    }


def run_envelope(name: str, max_nodes: int, time_limit_s: float, opening: SpiderState) -> dict:
    print(f"START {name} nodes={max_nodes} time={time_limit_s} bands={DEFAULT_DEPTH_BANDS}", flush=True)
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
    )
    payload = compact(opening, result)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    payload["envelope"] = name
    payload["max_nodes"] = max_nodes
    payload["time_limit_s"] = time_limit_s
    rev = payload["witnesses"]["reveal"]
    print(
        f"DONE {name} solved={payload['solved']} fnd={payload['max_foundations']} "
        f"fd={rev['face_down']} stock={rev['stock_rows']} "
        f"nodes={payload['nodes']} sps={payload['states_per_sec']:.1f} "
        f"depth={payload['stats']['max_depth']} bands={payload['depth_bands_used']} "
        f"deals={payload['stats']['deals_executed']} reopens={payload['stats']['tt_reopens']} "
        f"stop={payload['stop_reason']} replay={payload['replay_ok']}",
        flush=True,
    )
    if result.solved and result.replay_ok:
        header = (
            f"# Simple progressive depth-banded solver v0.2 — deal 4925153 {name}\n"
            f"# primitive_moves: {len(result.actions)}\n"
            f"# mobilityware_moves: {result.cost}\n"
            f"# states_expanded: {result.nodes}\n"
            f"# bands: {list(result.depth_bands_used)}\n"
        )
        SOLUTION.write_text(format_moves_text(result.actions, header=header), encoding="utf-8")
        payload["solution_path"] = str(SOLUTION.relative_to(ROOT)).replace("\\", "/")
        print(f"WROTE {SOLUTION}", flush=True)
    return payload


def material_progress(row: dict) -> bool:
    rev = row["witnesses"]["reveal"]
    stock = row["witnesses"]["stock"]
    if row["max_foundations"] >= 1:
        return True
    if stock["stock_rows"] <= 3:
        return True
    if rev["face_down"] <= 4:
        return True
    if row["stats"]["deals_executed"] >= 5 * V01_E2["deals_executed"]:
        return True
    return False


def choose_verdict(primary: dict) -> tuple[str, str]:
    if primary.get("solved") and primary.get("replay_ok"):
        return (
            "SIMPLE_SOLVER_COMPLETE_SOLUTION",
            f"{primary['envelope']} solved 4925153 in {primary['witnesses']['reveal']['path_length']} moves",
        )
    if primary["max_foundations"] >= 1 and primary.get("replay_ok"):
        return (
            "SIMPLE_SOLVER_FOUNDATION_PROGRESS",
            f"reached {primary['max_foundations']} replay-valid foundation(s)",
        )
    rev = primary["witnesses"]["reveal"]
    stock = primary["witnesses"]["stock"]
    buckets = primary["stats"]["expansions_by_depth_bucket"]
    shallow = sum(buckets[:2])
    deep = buckets[4]
    more_deals = primary["stats"]["deals_executed"] > V01_E2["deals_executed"]
    better_stock = stock["stock_rows"] < V01_E2["stock_rows"]
    better_fd = rev["face_down"] < V01_E2["face_down"]
    diversified = shallow > 0.5 * primary["nodes"] and primary["stats"]["max_depth"] < 2000
    if primary["nodes"] < 20_000 and primary["states_per_sec"] < 50:
        return "INCONCLUSIVE", "envelope too small or too slow to judge depth banding"
    if diversified and (better_stock or better_fd or more_deals or primary["stats"]["tt_reopens"] > 0):
        return (
            "DEPTH_BANDING_CORRECTS_DFS_DIVE",
            f"max depth {primary['stats']['max_depth']} vs v0.1 5000; "
            f"reveal fd={rev['face_down']} stock={stock['stock_rows']}; "
            f"deals executed {primary['stats']['deals_executed']}",
        )
    if shallow > 0.9 * primary["nodes"] and stock["stock_rows"] >= 5 and rev["face_down"] >= 20:
        return (
            "DEPTH_BANDED_STATE_EXPLOSION",
            "shallow combinatorics consumed the budget without useful penetration",
        )
    if diversified and not (better_stock or better_fd or more_deals):
        return (
            "DEPTH_BANDING_NOT_CAUSAL",
            "search redistributed but joint game progress did not improve on v0.1 E2",
        )
    if deep > 0.5 * primary["nodes"]:
        return (
            "DEPTH_BANDING_NOT_CAUSAL",
            "budget still concentrated on deep lineages",
        )
    return (
        "DEPTH_BANDING_NOT_CAUSAL",
        "depth bands ran but did not clearly correct the v0.1 DFS dive",
    )


def next_recommendation(verdict: str, primary: dict) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return (
            "Keep this solver separate and do not fold depth banding into the strategic controller."
        )
    if verdict == "SIMPLE_SOLVER_FOUNDATION_PROGRESS":
        return (
            "Continue the same depth-banded solver from the first-foundation witness with a fresh "
            "1M envelope; do not add Deal quotas or new heuristics."
        )
    if verdict == "DEPTH_BANDING_CORRECTS_DFS_DIVE":
        return (
            "Keep depth banding. The next bounded change is to skip later-band A/B "
            "(Pass 0-2) slices once unique_new is 0, so leftover nodes stay on Pass 3 "
            "/ unseen states. Do not add Deal quotas or new heuristic weights."
        )
    deals = primary["stats"]["deals_executed"]
    if deals <= V01_E2["deals_executed"] and primary["witnesses"]["stock"]["stock_rows"] >= 4:
        return (
            "Report Deal reluctance as the next limiter: measure why A/B tableau shuffles still "
            "outrank Deal inside a depth band, but do not change Deal policy in that measurement."
        )
    if verdict == "DEPTH_BANDED_STATE_EXPLOSION":
        return (
            "Keep depth bands and add only a cheap transposition-on-g or iterative-deepening "
            "step inside the first band; do not restore unbounded DFS."
        )
    return (
        "Treat depth banding as non-causal and inspect Deal/move-ordering imbalance next, "
        "without adding controller machinery."
    )


def write_report(result: dict) -> None:
    primary = result["runs"][result["primary_envelope"]]
    st = primary["stats"]
    rev = primary["witnesses"]["reveal"]
    stock = primary["witnesses"]["stock"]
    fnd = primary["witnesses"]["foundation"]
    buckets = st["expansions_by_depth_bucket"]
    lines = [
        "# Simple Progressive Search v0.2: Depth-Banded Backtracking",
        "",
        "## 1. Verdict",
        "",
        f"`{result['verdict']}` — {result['note']}.",
        "",
        "Depth discipline only.  A–D tiers, ordering, Deal scoring, and preparation",
        "are unchanged from v0.1.  Competing solver, not a controller patch.",
        "",
        "## 2. Depth-aware TT contract",
        "",
        "Exact key is packed canonical identity (tableau, stock, foundations).",
        "For each `(state, relaxation pass)` the TT stores the maximum remaining",
        "depth budget already started (`seen`) and completely searched (`done`).",
        "A revisit is pruned only when `covered_remaining >= current_remaining`.",
        "Broader passes subsume narrower at the same remaining depth.  Shallow",
        "exhaustion does not suppress a later visit with more remaining depth.",
        "Active-path cycle suppression is a separate `path_keys` set.",
        "",
        "## 3. Band/pass schedule",
        "",
        f"Bands: `{list(DEFAULT_DEPTH_BANDS)}`.  For each band, Pass 0→3.",
        "Remaining node/time budget is split across remaining (band, pass) cells.",
        f"Used: {primary['depth_bands_used']}.",
        "",
    ]
    for row in st["band_pass_reports"]:
        lines.append(
            f"- band {row['band']} pass {row['pass']}: expanded={row['expanded']} "
            f"gen={row['generated']} unique_new={row['unique_new']} "
            f"tt_hits={row['tt_hits']} prunes={row['depth_prunes']} "
            f"reopens={row['reopens']} max_depth={row['max_depth']} "
            f"fd={row['face_down_best']} stock={row['stock_best']} "
            f"fnd={row['max_foundations']} deals {row['deals_considered']}/"
            f"{row['deals_executed']} stop={row['stop']}."
        )
    lines.extend(
        [
            "",
            "## 4. Throughput",
            "",
            f"- Expanded: {primary['nodes']}",
            f"- Unique: {st['unique_exact_states']}",
            f"- Generated: {st['states_generated']}",
            f"- Time: {primary['elapsed_s']:.1f}s",
            f"- States/s: {primary['states_per_sec']:.1f}",
            f"- TT hits: {st['tt_hits']} (rate {st['tt_hit_rate']:.3f})",
            f"- Depth-aware prunes: {st['tt_depth_prunes']}",
            f"- Deeper-budget reopens: {st['tt_reopens']}",
            f"- Peak RSS: {st.get('peak_rss_mb')}",
            f"- Max depth: {st['max_depth']}",
            "",
            "## 5. Depth distribution",
            "",
            f"- 0–79: {buckets[0]}",
            f"- 80–159: {buckets[1]}",
            f"- 160–319: {buckets[2]}",
            f"- 320–639: {buckets[3]}",
            f"- 640+: {buckets[4]}",
            "",
            "## 6. Deal-depth distribution",
            "",
            f"- Deals considered/executed: {st['deals_considered']}/{st['deals_executed']}",
            f"- Deals per 100k expansions: {st['deals_executed_per_100k']:.2f}",
            f"- v0.1 E2: considered {V01_E2['deals_considered']}, executed {V01_E2['deals_executed']}",
            f"- Expansions by deals already done 0..5: {st['states_by_stock_dealt']}",
            f"- Unique states by deals done 0..5: {st['unique_by_stock_dealt']}",
            f"- Deal executions from stock-dealt 0..5: {st['deals_executed_from_stock']}",
            f"- Unique Deal-parent states 0..5: {st['unique_deal_parents']}",
            "",
            "## 7. Joint replayable game progress",
            "",
            f"- Best reveal: fd={rev['face_down']} foundations={rev['foundations']} "
            f"stock={rev['stock_rows']} depth={rev['path_length']} MW={rev['cost']} "
            f"replay_match={rev['cost_matches']}",
            f"- Best stock-progress: fd={stock['face_down']} foundations={stock['foundations']} "
            f"stock={stock['stock_rows']} depth={stock['path_length']} MW={stock['cost']} "
            f"replay_match={stock['cost_matches']}",
            f"- Best foundation: fd={fnd['face_down']} foundations={fnd['foundations']} "
            f"stock={fnd['stock_rows']} depth={fnd['path_length']} MW={fnd['cost']} "
            f"replay_match={fnd['cost_matches']}",
            "",
            "## 8. First foundation",
            "",
        ]
    )
    if st["first_foundation_node"] is None:
        lines.append("No replay-valid foundation.")
    else:
        lines.append(
            f"Node {st['first_foundation_node']}, depth {st['first_foundation_depth']}, "
            f"pass {st['first_foundation_pass']}, path length "
            f"{primary['first_foundation_path_length']}."
        )
    lines.extend(
        [
            "",
            "## 9. Complete solution",
            "",
            "Yes." if primary["solved"] else "No complete solution in the completed envelopes.",
            "",
            "## 10. Comparison with v0.1",
            "",
            "| | v0.1 E2 | v0.2 primary |",
            "| --- | ---: | ---: |",
            f"| Expanded | {V01_E2['expanded']} | {primary['nodes']} |",
            f"| Unique | {V01_E2['unique']} | {st['unique_exact_states']} |",
            f"| States/s | {V01_E2['states_per_sec']} | {primary['states_per_sec']:.1f} |",
            f"| Max depth | {V01_E2['max_depth']} | {st['max_depth']} |",
            f"| Foundations | {V01_E2['max_foundations']} | {primary['max_foundations']} |",
            f"| Best fd | {V01_E2['face_down']} | {rev['face_down']} |",
            f"| Best stock remaining | {V01_E2['stock_rows']} | {stock['stock_rows']} |",
            f"| Best path length | {V01_E2['path_length']} | {rev['path_length']} |",
            f"| Best MW cost | {V01_E2['cost']} | {rev['cost']} |",
            f"| Deals executed | {V01_E2['deals_executed']} | {st['deals_executed']} |",
            "",
            "## 11. Search-space interpretation",
            "",
            result["interpretation"],
            "",
            "## 12. Exactly one next recommendation",
            "",
            result["next_recommendation"],
            "",
            "## Integrity",
            "",
            f"Base SHA `{result['base_sha']}`. Deal `deals/4925153.txt`.",
            "Human canonical line was not used to seed or guide search.",
            "Witness paths replay through `replay_actions`. Solver does not import",
            "planner policy. Anytime controller is unchanged.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(verdict: str, primary: dict) -> str:
    buckets = primary["stats"]["expansions_by_depth_bucket"]
    rev = primary["witnesses"]["reveal"]
    stock = primary["witnesses"]["stock"]
    return (
        f"Expansions by depth 0–79/80–159/160–319/320–639/640+ = {buckets}. "
        f"Max depth {primary['stats']['max_depth']} (v0.1 hit 5000). "
        f"Reopens {primary['stats']['tt_reopens']}; depth prunes "
        f"{primary['stats']['tt_depth_prunes']}. "
        f"Reveal fd {rev['face_down']} vs v0.1 6; stock remaining "
        f"{stock['stock_rows']} vs v0.1 4; deals executed "
        f"{primary['stats']['deals_executed']} vs v0.1 244. "
        f"Verdict {verdict} follows from those joint witnesses, not mixed extrema."
    )


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    runs: dict = {}
    name, nodes, limit = PRIMARY
    measured = run_envelope(name, nodes, limit, opening)
    _write_json(CHECKPOINTS / f"{name}.json", measured)
    runs[name] = measured
    if (
        not measured.get("solved")
        and material_progress(measured)
        and measured["elapsed_s"] < 1200
        and measured["states_per_sec"] >= 400
    ):
        oname, onodes, olimit = OPTIONAL
        print(f"OPTIONAL {oname} after material progress", flush=True)
        optional = run_envelope(oname, onodes, olimit, opening)
        _write_json(CHECKPOINTS / f"{oname}.json", optional)
        runs[oname] = optional
        primary_name = oname
    else:
        primary_name = name
        print("SKIP P2 (no material progress, slow, or already solved)", flush=True)
    primary = runs[primary_name]
    verdict, note = choose_verdict(primary)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "depth_bands": list(DEFAULT_DEPTH_BANDS),
        "v01_e2": V01_E2,
        "runs": runs,
        "primary_envelope": primary_name,
        "verdict": verdict,
        "note": note,
        "interpretation": interpret(verdict, primary),
        "next_recommendation": next_recommendation(verdict, primary),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
