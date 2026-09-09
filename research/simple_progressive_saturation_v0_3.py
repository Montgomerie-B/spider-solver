#!/usr/bin/env python3
"""Saturation-aware depth-banded simple solver v0.3 on deal 4925153."""

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


EXPERIMENT = "simple_progressive_saturation_v0_3"
BASE_SHA = "1aa42a3b969947992807ad52ab2c9fbfd83504e8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOLUTION = ROOT / "solutions" / "4925153_simple_v0_3.moves.txt"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT

V01_E2 = {
    "expanded": 1_000_000,
    "unique": 999_478,
    "states_per_sec": 865.7,
    "max_depth": 5000,
    "deals_executed": 244,
    "reveal_fd": 6,
    "stock_remaining": 4,
    "foundations": 0,
}
V02_P1 = {
    "expanded": 1_000_000,
    "unique": 147_139,
    "states_per_sec": 958.0,
    "max_depth": 356,
    "deals_executed": 15_928,
    "reveal_fd": 16,
    "stock_fd": 24,
    "stock_remaining": 0,
    "foundations": 0,
    "tt_prunes": 1_862_606,
    "reopens": 852_339,
    "unique_ratio": 0.147139,
}
V02_P2 = {
    "expanded": 3_000_000,
    "unique": 453_956,
    "max_depth": 1221,
    "deals_executed": 51_770,
    "reveal_fd": 14,
    "stock_remaining": 0,
    "foundations": 0,
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
            "cost": cost,
            "cost_matches": cost == 0,
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
    deals_per_100k = 100_000.0 * stats.deals_executed / max(1, stats.states_expanded)
    unique_ratio = stats.unique_exact_states / max(1, stats.states_expanded)
    fd_stock = []
    for cell in result.best_fd_by_stock_dealt:
        actions = cell.get("actions") or []
        cost = cell.get("cost") or 0
        replay = _replay_witness(opening, actions, cost)
        fd_stock.append(
            {
                "deals_completed": cell["deals_completed"],
                "face_down": cell["face_down"],
                "stock_rows": cell["stock_rows"],
                "foundations": cell["foundations"],
                "depth": cell["depth"],
                "cost": cell["cost"],
                "path_length": len(actions),
                "replay": replay,
            }
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
            "unique_ratio": unique_ratio,
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
            "first_foundation_node": stats.first_foundation_node,
            "first_foundation_depth": stats.first_foundation_depth,
            "first_foundation_pass": stats.first_foundation_pass,
            "peak_rss_mb": stats.peak_rss_mb,
            "expansions_by_depth_bucket": list(stats.expansions_by_depth_bucket),
            "states_by_stock_dealt": list(stats.states_by_stock_dealt),
            "unique_by_stock_dealt": list(stats.unique_by_stock_dealt),
            "unique_by_pass": list(stats.unique_by_pass),
            "slices_skipped": stats.slices_skipped,
            "expansions_redirected": stats.expansions_redirected,
            "saturated_passes": list(stats.saturated_passes),
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
        "fd_by_stock_dealt": fd_stock,
        "first_foundation_path_length": len(result.first_foundation_actions),
        "opening_face_down": sum(len(col.face_down) for col in opening.columns),
        "opening_stock_rows": len(opening.stock) // 10,
    }


def run_envelope(name: str, max_nodes: int, time_limit_s: float, opening: SpiderState) -> dict:
    print(
        f"START {name} nodes={max_nodes} time={time_limit_s} bands={DEFAULT_DEPTH_BANDS} saturation=on",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=max_nodes,
        time_limit_s=time_limit_s,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
        enable_saturation=True,
    )
    payload = compact(opening, result)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    payload["envelope"] = name
    payload["max_nodes"] = max_nodes
    payload["time_limit_s"] = time_limit_s
    rev = payload["witnesses"]["reveal"]
    print(
        f"DONE {name} solved={payload['solved']} fnd={payload['max_foundations']} "
        f"fd={rev['face_down']} unique={payload['stats']['unique_exact_states']} "
        f"ratio={payload['stats']['unique_ratio']:.4f} "
        f"nodes={payload['nodes']} sps={payload['states_per_sec']:.1f} "
        f"skipped={payload['stats']['slices_skipped']} "
        f"redir={payload['stats']['expansions_redirected']} "
        f"deals={payload['stats']['deals_executed']} "
        f"stop={payload['stop_reason']} replay={payload['replay_ok']}",
        flush=True,
    )
    if result.solved and result.replay_ok:
        header = (
            f"# Simple progressive saturation solver v0.3 — deal 4925153 {name}\n"
            f"# primitive_moves: {len(result.actions)}\n"
            f"# mobilityware_moves: {result.cost}\n"
            f"# states_expanded: {result.nodes}\n"
        )
        SOLUTION.write_text(format_moves_text(result.actions, header=header), encoding="utf-8")
        payload["solution_path"] = str(SOLUTION.relative_to(ROOT)).replace("\\", "/")
    return payload


def material_unique(row: dict) -> bool:
    unique = row["stats"]["unique_exact_states"]
    rss = row["stats"].get("peak_rss_mb") or 0.0
    if unique <= V02_P1["unique"] * 1.15:
        return False
    if rss and rss > 2048:
        return False
    return True


def choose_verdict(primary: dict) -> tuple[str, str]:
    if primary.get("solved") and primary.get("replay_ok"):
        return (
            "SIMPLE_SOLVER_COMPLETE_SOLUTION",
            "complete replay-valid solve under saturation-aware bands",
        )
    if primary["max_foundations"] >= 1 and primary.get("replay_ok"):
        return (
            "SATURATION_SKIP_REACHES_FOUNDATION",
            f"reached {primary['max_foundations']} replay-valid foundation(s)",
        )
    unique = primary["stats"]["unique_exact_states"]
    ratio = primary["stats"]["unique_ratio"]
    skipped = primary["stats"]["slices_skipped"]
    better = unique > V02_P1["unique"]
    much = unique >= int(V02_P1["unique"] * 1.25) or ratio >= V02_P1["unique_ratio"] * 1.25
    stock = primary["witnesses"]["stock"]["stock_rows"]
    if skipped == 0:
        return (
            "NARROW_PASSES_NOT_THE_WASTE",
            "no (band, pass) slice was skipped; unique_new=0 did not recur",
        )
    if unique < int(V02_P1["unique"] * 0.85) or (
        stock > 0 and primary["stats"]["deals_executed"] < V02_P1["deals_executed"] * 0.25
    ):
        return (
            "SATURATION_SKIP_HARMS_SEARCH",
            f"unique {unique} vs v0.2 {V02_P1['unique']}; stock remaining {stock}",
        )
    if much and better:
        return (
            "SATURATION_SKIP_IMPROVES_COVERAGE",
            f"unique {unique} ({ratio:.3f}/exp) vs v0.2 {V02_P1['unique']} "
            f"(0.147/exp); skipped {skipped} slices",
        )
    if better:
        return (
            "SATURATION_SKIP_IMPROVES_COVERAGE",
            f"unique {unique} vs v0.2 {V02_P1['unique']}; skipped {skipped} slices",
        )
    return (
        "NARROW_PASSES_NOT_THE_WASTE",
        f"skipped {skipped} slices but unique {unique} is not materially above v0.2 {V02_P1['unique']}",
    )


def next_recommendation(verdict: str, primary: dict) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return "Keep this solver separate; do not fold saturation skipping into the strategic controller."
    if verdict == "SATURATION_SKIP_REACHES_FOUNDATION":
        return (
            "Continue the same saturation-aware solver from the first-foundation witness; "
            "do not add Deal quotas."
        )
    rev = primary["witnesses"]["reveal"]["face_down"]
    stock = primary["witnesses"]["stock"]["stock_rows"]
    if rev > V02_P1["reveal_fd"] - 2 and stock == 0:
        return (
            "Keep saturation skipping. The remaining divergence is reveal vs stock "
            "progression on the same trajectory; measure that without adding heuristics."
        )
    if verdict == "SATURATION_SKIP_IMPROVES_COVERAGE":
        return (
            "Keep saturation skipping and inspect the joint face-down-by-stock table "
            "as the next limiter; do not add Deal quotas or new move weights."
        )
    if verdict == "SATURATION_SKIP_HARMS_SEARCH":
        return "Revert saturation skipping to v0.2 scheduling; do not add heuristics to compensate."
    return (
        "Saturation skipping is not the remaining waste; inspect Pass-3 Deal dumping "
        "versus uncovering without changing classification."
    )


def write_report(result: dict) -> None:
    primary = result["runs"][result["comparison_envelope"]]
    st = primary["stats"]
    rev = primary["witnesses"]["reveal"]
    stock = primary["witnesses"]["stock"]
    fnd = primary["witnesses"]["foundation"]
    lines = [
        "# Simple Progressive Search v0.3: Saturation-Aware Depth Bands",
        "",
        "## 1. Verdict",
        "",
        f"`{result['verdict']}` — {result['note']}.",
        "",
        "Scheduling only. A–D classification, ordering, Deal policy, depth bands,",
        "and the depth-aware TT contract are unchanged from v0.2.",
        "",
        "## 2. Saturation contract",
        "",
        "The accounting unit is the existing v0.2 `(depth band, relaxation pass)`",
        "budget cell (remaining band nodes split across remaining live passes).",
        "No extra micro-quantum is used, and none was tuned on 4925153.",
        "If a completed cell has `unique_new == 0`, that pass is saturated:",
        "later equivalent slices of the same pass are not allocated; leftover",
        "band budget goes to broader unsaturized passes. Saturation does not",
        "mark states exhausted beyond the depth-aware TT.",
        "",
        f"Skipped slices: {st['slices_skipped']}. Redirected allocation: "
        f"{st['expansions_redirected']}. Saturated passes: {st['saturated_passes']}.",
        "",
        "## 3. Coverage efficiency",
        "",
        f"- Expanded: {primary['nodes']}",
        f"- Unique: {st['unique_exact_states']}",
        f"- Unique/expanded: {st['unique_ratio']:.4f} (v0.2 P1: 0.1471)",
        f"- States/s: {primary['states_per_sec']:.1f}",
        f"- Max depth: {st['max_depth']}",
        f"- Peak RSS MiB: {st.get('peak_rss_mb')}",
        f"- Unique by pass A–D: {st['unique_by_pass']}",
        "",
        "## 4. Band/pass productivity",
        "",
    ]
    for row in st["band_pass_reports"]:
        lines.append(
            f"- band {row['band']} pass {row['pass']}: expanded={row['expanded']} "
            f"unique_new={row['unique_new']} "
            f"rate={row.get('unique_new_per_expansion', 0):.4f} "
            f"sat={row.get('saturation_triggered')} skipped={row.get('skipped')} "
            f"redir={row.get('budget_redirected', 0)} "
            f"reopens={row.get('reopens', 0)} stop={row['stop']}."
        )
    lines.extend(
        [
            "",
            "## 5. TT reopening behaviour",
            "",
            f"- Depth-aware prunes: {st['tt_depth_prunes']}",
            f"- Deeper-budget reopens: {st['tt_reopens']}",
            f"- TT hits: {st['tt_hits']} (rate {st['tt_hit_rate']:.3f})",
            f"- v0.2 P1 prunes/reopens: {V02_P1['tt_prunes']} / {V02_P1['reopens']}",
            "",
            "## 6. Stock-depth distribution",
            "",
            f"- Deals considered/executed: {st['deals_considered']}/{st['deals_executed']}",
            f"- Deals per 100k: {st['deals_executed_per_100k']:.2f}",
            f"- Unique states by deals 0..5: {st['unique_by_stock_dealt']}",
            f"- Expansions by deals 0..5: {st['states_by_stock_dealt']}",
            "",
            "## 7. Joint face-down-by-stock-depth table",
            "",
            "| Deals completed | Best face-down | Stock remaining | Depth | MW | Replay |",
            "| ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for cell in primary["fd_by_stock_dealt"]:
        replay = cell.get("replay") or {}
        fd = cell["face_down"]
        fd_s = "—" if fd is None else str(fd)
        stock_s = "—" if cell["stock_rows"] is None else str(cell["stock_rows"])
        depth_s = "—" if cell["depth"] is None else str(cell["depth"])
        cost_s = "—" if cell["cost"] is None else str(cell["cost"])
        ok = replay.get("cost_matches")
        lines.append(
            f"| {cell['deals_completed']} | {fd_s} | {stock_s} | {depth_s} | {cost_s} | {ok} |"
        )
    lines.extend(
        [
            "",
            f"- Best reveal: fd={rev['face_down']} stock={rev['stock_rows']} "
            f"fnd={rev['foundations']} depth={rev['path_length']} MW={rev['cost']} "
            f"replay={rev['cost_matches']}",
            f"- Best stock: fd={stock['face_down']} stock={stock['stock_rows']} "
            f"fnd={stock['foundations']} depth={stock['path_length']} MW={stock['cost']} "
            f"replay={stock['cost_matches']}",
            f"- Best foundation: fd={fnd['face_down']} stock={fnd['stock_rows']} "
            f"fnd={fnd['foundations']} depth={fnd['path_length']} MW={fnd['cost']}",
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
            "Yes." if primary["solved"] else "No complete solution.",
            "",
            "## 10. v0.1/v0.2/v0.3 comparison",
            "",
            "| | v0.1 E2 | v0.2 P1 | v0.3 P1 |",
            "| --- | ---: | ---: | ---: |",
            f"| Expanded | {V01_E2['expanded']} | {V02_P1['expanded']} | {primary['nodes']} |",
            f"| Unique | {V01_E2['unique']} | {V02_P1['unique']} | {st['unique_exact_states']} |",
            f"| Unique/exp | {V01_E2['unique']/V01_E2['expanded']:.3f} | {V02_P1['unique_ratio']:.3f} | {st['unique_ratio']:.3f} |",
            f"| States/s | {V01_E2['states_per_sec']} | {V02_P1['states_per_sec']} | {primary['states_per_sec']:.1f} |",
            f"| Max depth | {V01_E2['max_depth']} | {V02_P1['max_depth']} | {st['max_depth']} |",
            f"| Deals executed | {V01_E2['deals_executed']} | {V02_P1['deals_executed']} | {st['deals_executed']} |",
            f"| Best reveal fd | {V01_E2['reveal_fd']} | {V02_P1['reveal_fd']} | {rev['face_down']} |",
            f"| Best stock remaining | {V01_E2['stock_remaining']} | {V02_P1['stock_remaining']} | {stock['stock_rows']} |",
            f"| Foundations | 0 | 0 | {primary['max_foundations']} |",
            "",
            "## 11. Search interpretation",
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
    if "P2" in result["runs"] and result["comparison_envelope"] != "P2":
        p2 = result["runs"]["P2"]
        lines.extend(
            [
                "## Optional 3M",
                "",
                f"P2 unique={p2['stats']['unique_exact_states']} "
                f"deals={p2['stats']['deals_executed']} "
                f"fd={p2['witnesses']['reveal']['face_down']} "
                f"stock={p2['witnesses']['stock']['stock_rows']} "
                f"fnd={p2['max_foundations']}.",
                "",
            ]
        )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(verdict: str, primary: dict) -> str:
    st = primary["stats"]
    rev = primary["witnesses"]["reveal"]
    stock = primary["witnesses"]["stock"]
    return (
        f"Saturation skipped {st['slices_skipped']} slices and redirected "
        f"{st['expansions_redirected']} allocated nodes. Unique "
        f"{st['unique_exact_states']} / {primary['nodes']} = {st['unique_ratio']:.4f} "
        f"(v0.2 P1 0.1471). Reveal fd {rev['face_down']} vs v0.2 16; stock remaining "
        f"{stock['stock_rows']} vs 0; deals {st['deals_executed']} vs 15928. "
        f"Verdict {verdict}."
    )


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    runs: dict = {}
    name, nodes, limit = PRIMARY
    measured = run_envelope(name, nodes, limit, opening)
    _write_json(CHECKPOINTS / f"{name}.json", measured)
    runs[name] = measured
    comparison = name
    if (
        not measured.get("solved")
        and material_unique(measured)
        and measured["elapsed_s"] < 1200
        and measured["states_per_sec"] >= 400
    ):
        oname, onodes, olimit = OPTIONAL
        print(f"OPTIONAL {oname} after unique-coverage gain", flush=True)
        optional = run_envelope(oname, onodes, olimit, opening)
        _write_json(CHECKPOINTS / f"{oname}.json", optional)
        runs[oname] = optional
    else:
        print("SKIP P2 (unique coverage not materially above v0.2, slow, or solved)", flush=True)
    primary = runs[comparison]
    verdict, note = choose_verdict(primary)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "depth_bands": list(DEFAULT_DEPTH_BANDS),
        "saturation_unit": "existing v0.2 (band, pass) budget cell",
        "v01_e2": V01_E2,
        "v02_p1": V02_P1,
        "v02_p2": V02_P2,
        "runs": runs,
        "comparison_envelope": comparison,
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
