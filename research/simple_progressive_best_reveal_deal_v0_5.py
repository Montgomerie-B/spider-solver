#!/usr/bin/env python3
"""v0.5 A/B: best-reveal Deal probe vs control on 4925153."""

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
from spider.simple_progressive_solver import DEFAULT_DEPTH_BANDS, solve_progressive
from spider.simple_reveal_stock_audit import build_stock_depth_rows


EXPERIMENT = "simple_progressive_best_reveal_deal_v0_5"
BASE_SHA = "e43c80040063d27fc2fec5d01221be6f2a8826bf"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
SOLUTION = ROOT / "solutions" / "4925153_simple_v0_5.moves.txt"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
PRIMARY_NODES = 1_000_000
TIME_LIMIT = 1800.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _replay(opening: SpiderState, actions, cost: int | None = None) -> dict:
    end = opening.clone()
    paid = replay_actions(end, list(actions)) if actions else 0
    return {
        "path_length": len(actions or []),
        "cost": paid,
        "cost_matches": cost is None or paid == cost,
        "foundations": len(end.foundations),
        "face_down": sum(len(col.face_down) for col in end.columns),
        "stock_rows": len(end.stock) // 10,
        "solved": end.is_solved(),
    }


def compact(opening: SpiderState, result, arm: str) -> dict:
    audit = result.audit
    rows = build_stock_depth_rows(audit, opening) if audit else []
    fd_by_stock = []
    for cell in result.best_fd_by_stock_dealt:
        replay = _replay(opening, cell.get("actions") or [], cell.get("cost"))
        fd_by_stock.append(
            {
                "deals_completed": cell["deals_completed"],
                "face_down": cell["face_down"],
                "stock_rows": cell["stock_rows"],
                "depth": cell["depth"],
                "cost": cell["cost"],
                "replay": replay,
            }
        )
    probes = []
    for event in result.probe_events:
        probes.append(
            {
                "dealt": event["dealt"],
                "pre_fd": event["pre_fd"],
                "post_fd": event["post_fd"],
                "pass": event["pass"],
                "depth": event["depth"],
                "n_tableau": event["n_tableau"],
                "deal_legal": event["deal_legal"],
                "child_novel": event["child_novel"],
                "tt_skip": event["tt_skip"],
                "expanded": event["expanded"],
                "descendant_expansions": event["descendant_expansions"],
                "best_descendant_fd": event["best_descendant_fd"],
                "deepest_dealt": event["deepest_dealt"],
                "foundations": event["foundations"],
                "second_deal": event["second_deal"],
                "path_length": len(event.get("path") or []),
            }
        )
    strongest = None
    zero = [event for event in probes if event["dealt"] == 0]
    if zero:
        strongest = min(zero, key=lambda item: (item["pre_fd"], item["depth"]))
    stats = result.stats
    return {
        "arm": arm,
        "solved": result.solved,
        "nodes": result.nodes,
        "unique": stats.unique_exact_states,
        "unique_ratio": stats.unique_exact_states / max(1, result.nodes),
        "elapsed_s": result.elapsed_s,
        "states_per_sec": result.states_per_sec,
        "max_foundations": result.max_foundations,
        "max_depth": stats.max_depth,
        "deals_executed": stats.deals_executed,
        "tt_hits": stats.tt_hits,
        "tt_prunes": stats.tt_depth_prunes,
        "tt_reopens": stats.tt_reopens,
        "peak_rss_mb": stats.peak_rss_mb,
        "pass_reached": result.pass_reached,
        "states_by_stock_dealt": list(stats.states_by_stock_dealt),
        "unique_by_stock_dealt": list(stats.unique_by_stock_dealt),
        "reveal_records": list(stats.reveal_records),
        "probe_fires": list(stats.probe_fires),
        "probe_entered": list(stats.probe_entered),
        "probe_tt_suppressed": list(stats.probe_tt_suppressed),
        "fd_by_stock": fd_by_stock,
        "stock_depth_rows": [
            {
                "deals_completed": row["deals_completed"],
                "best_fd": row["best_fd"],
                "later_dealt_fd": row["later_dealt_fd"],
                "pre_fd": row["pre_fd"],
                "post_fd": row["post_fd"],
                "lineage_dealt": row["lineage_dealt"],
                "deal_legal": row["deal_legal"],
                "deal_in_pass": row["deal_in_pass"],
                "primary_loss_reason": row["primary_loss_reason"],
            }
            for row in rows
        ],
        "probes": probes,
        "strongest_zero_probe": strongest,
        "first_foundation_node": stats.first_foundation_node,
        "replay_ok": result.replay_ok,
        "stop_reason": result.stop_reason,
        "reveal": _replay(opening, result.best_reveal_actions, result.best_reveal_cost),
        "stock": _replay(opening, result.best_stock_actions, result.best_stock_cost),
        "path_length": len(result.actions),
        "cost": result.cost,
    }


def run_arm(name: str, probe: bool, opening: SpiderState) -> dict:
    print(f"START {name} probe={probe} nodes={PRIMARY_NODES}", flush=True)
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=PRIMARY_NODES,
        time_limit_s=TIME_LIMIT,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
        enable_saturation=True,
        enable_audit=True,
        enable_best_reveal_deal_probe=probe,
    )
    payload = compact(opening, result, name)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {name} nodes={payload['nodes']} unique={payload['unique']} "
        f"fd0={payload['fd_by_stock'][0]['face_down']} "
        f"deals={payload['deals_executed']} probes={sum(payload['probe_fires'])} "
        f"fnd={payload['max_foundations']} sps={payload['states_per_sec']:.1f}",
        flush=True,
    )
    if result.solved and result.replay_ok:
        from spider.simple_progressive_solver import format_moves_text

        SOLUTION.write_text(
            format_moves_text(
                result.actions,
                header=(
                    f"# v0.5 {name} 4925153\n"
                    f"# primitive_moves: {len(result.actions)}\n"
                    f"# mobilityware_moves: {result.cost}\n"
                ),
            ),
            encoding="utf-8",
        )
        payload["solution_path"] = str(SOLUTION.relative_to(ROOT)).replace("\\", "/")
    return payload


def choose_verdict(control: dict, treat: dict) -> tuple[str, str]:
    if treat.get("solved") and treat.get("replay_ok"):
        return "SIMPLE_SOLVER_COMPLETE_SOLUTION", "treatment solved 4925153"
    if treat["max_foundations"] >= 1:
        return "BEST_REVEAL_DEAL_PROBE_REACHES_FOUNDATION", "replay-valid foundation on probe arm"
    c0 = control["fd_by_stock"][0]["face_down"]
    t_rows = treat["fd_by_stock"]
    coupled = False
    for dealt in range(1, 6):
        cf = control["fd_by_stock"][dealt]["face_down"]
        tf = t_rows[dealt]["face_down"]
        if tf is not None and cf is not None and tf + 4 < cf:
            coupled = True
        if tf is not None and t_rows[0]["face_down"] is not None:
            if tf <= t_rows[0]["face_down"] + 2 and dealt >= 1:
                coupled = True
    strongest = treat.get("strongest_zero_probe")
    if strongest and strongest["expanded"] and strongest["pre_fd"] <= (c0 or 99) + 2:
        if strongest["best_descendant_fd"] <= strongest["pre_fd"] + 2 and strongest[
            "deepest_dealt"
        ] >= 1:
            coupled = True
    if treat["unique"] < int(control["unique"] * 0.7) and treat["max_foundations"] == 0:
        return "BEST_REVEAL_PROBE_HARMS_SEARCH", "unique coverage dropped without foundation"
    if strongest and strongest["expanded"] and not coupled:
        return (
            "DEAL_STARVATION_NOT_CAUSAL_AFTER_PROBE",
            f"stock-0 checkpoint pre_fd={strongest['pre_fd']} dealt but coupled FD did not improve",
        )
    if coupled:
        return (
            "BEST_REVEAL_DEAL_PROBE_RECONNECTS_PROGRESS",
            "reveal quality survives into later stock depth vs control",
        )
    if not treat["probe_fires"] or sum(treat["probe_fires"]) == 0:
        return "INCONCLUSIVE", "treatment fired no probes"
    return (
        "DEAL_STARVATION_NOT_CAUSAL_AFTER_PROBE",
        "probes fired but coupled reveal/stock table did not improve materially",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return "Keep the probe separate from the strategic controller; do not add quotas."
    if verdict == "BEST_REVEAL_DEAL_PROBE_REACHES_FOUNDATION":
        return "Replay the foundation path and continue the same probe from that state; do not add prep-before-Deal yet."
    if verdict == "BEST_REVEAL_DEAL_PROBE_RECONNECTS_PROGRESS":
        return "Keep the probe and measure post-Deal continuation next; do not add preparation-before-Deal yet."
    if verdict == "DEAL_STARVATION_NOT_CAUSAL_AFTER_PROBE":
        return "Stop: the fd-16 lineage now Deals. Next hypothesis is post-Deal stall or known-row damage, not starvation."
    if verdict == "BEST_REVEAL_PROBE_HARMS_SEARCH":
        return "Leave the probe off by default; do not add further Deal promotions."
    return "Reproduce the control fd-16 pattern before another treatment."


def write_report(payload: dict) -> None:
    a = payload["control"]
    b = payload["treatment"]
    lines = [
        "# Simple Progressive Search v0.5: Best-Reveal Deal Probe",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload['note']}.",
        "",
        "## 2. Exact treatment rule",
        "",
        "At each stock depth, the first expanded state establishes the face-down",
        "record and does not probe. A later expanded state with a **strictly smaller**",
        "face-down count is a checkpoint. If `enumerate_legal_actions(MW_RULES)`",
        "contains Deal, Deal is moved to the front of that node's children even in",
        "Pass 0. Equal or worse face-down does not retrigger. After the probe the",
        "search stays in the same pass. Default OFF.",
        "",
        "## 3. Rules-contract compliance",
        "",
        "Deal legality is `state.can_deal(MW_RULES)` plus engine legal-action",
        "enumeration. Unrestricted Deal: empties and remaining tableau moves do not",
        "make Deal illegal. Tiers still classify Deal; the probe is permission/order",
        "only. No empty-column qualification. No 1-ply preparation in the probe.",
        "",
        "## 4. Control reproduction",
        "",
        f"- Control nodes={a['nodes']} unique={a['unique']} deals={a['deals_executed']} "
        f"fnd={a['max_foundations']} stop={a['stop_reason']}.",
        f"- Stock-0 best FD={a['fd_by_stock'][0]['face_down']}; "
        f"lineage_dealt={a['stock_depth_rows'][0].get('lineage_dealt')}; "
        f"deal_in_pass={a['stock_depth_rows'][0].get('deal_in_pass')}; "
        f"later_dealt_fd={a['stock_depth_rows'][0].get('later_dealt_fd')}.",
        "",
        "## 5. Probe frequency",
        "",
        f"- Records by stock depth: {b['reveal_records']}",
        f"- Fires: {b['probe_fires']}",
        f"- Entered: {b['probe_entered']}",
        f"- TT-suppressed: {b['probe_tt_suppressed']}",
        "",
        "## 6. fd-16 causal lineage",
        "",
    ]
    s = b.get("strongest_zero_probe")
    if s:
        lines.append(
            f"- Strongest stock-0 checkpoint: pre_fd={s['pre_fd']} post_fd={s['post_fd']} "
            f"pass={s['pass']} depth={s['depth']} n_tableau={s['n_tableau']} "
            f"legal={s['deal_legal']} novel={s['child_novel']} tt_skip={s['tt_skip']} "
            f"expanded={s['expanded']} descendants={s['descendant_expansions']} "
            f"best_desc_fd={s['best_descendant_fd']} deepest_dealt={s['deepest_dealt']} "
            f"fnd={s['foundations']} second_deal={s['second_deal']}."
        )
    else:
        lines.append("- No stock-0 probe event.")
    lines.extend(
        [
            "",
            "## 7. Coupled reveal/stock progression",
            "",
            "| Deals completed | Best FD — control | Best FD — probe |",
            "| ---: | ---: | ---: |",
        ]
    )
    for dealt in range(6):
        cf = a["fd_by_stock"][dealt]["face_down"]
        tf = b["fd_by_stock"][dealt]["face_down"]
        lines.append(f"| {dealt} | {cf if cf is not None else '—'} | {tf if tf is not None else '—'} |")
    lines.extend(
        [
            "",
            "| Probe originating at stock depth | Pre-Deal FD | Post-Deal FD | Best descendant FD | Deepest deals | Foundation |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    by_depth = {}
    for event in b["probes"]:
        d = event["dealt"]
        cur = by_depth.get(d)
        if cur is None or event["pre_fd"] < cur["pre_fd"]:
            by_depth[d] = event
    for dealt in range(6):
        event = by_depth.get(dealt)
        if not event:
            lines.append(f"| {dealt} | — | — | — | — | — |")
            continue
        lines.append(
            f"| {dealt} | {event['pre_fd']} | {event['post_fd']} | "
            f"{event['best_descendant_fd']} | {event['deepest_dealt']} | "
            f"{event['foundations']} |"
        )
    lines.extend(
        [
            "",
            "## 8. Foundation result",
            "",
            f"Control foundations={a['max_foundations']}; treatment={b['max_foundations']}; "
            f"first treatment node={b['first_foundation_node']}.",
            "",
            "## 9. Complete-solution result",
            "",
            "Yes." if b["solved"] else "No complete solution.",
            "",
            "## 10. Search/runtime effects",
            "",
            "| | Control | Treatment |",
            "| --- | ---: | ---: |",
            f"| Expanded | {a['nodes']} | {b['nodes']} |",
            f"| Unique | {a['unique']} | {b['unique']} |",
            f"| Unique/exp | {a['unique_ratio']:.4f} | {b['unique_ratio']:.4f} |",
            f"| States/s | {a['states_per_sec']:.1f} | {b['states_per_sec']:.1f} |",
            f"| TT hits | {a['tt_hits']} | {b['tt_hits']} |",
            f"| Reopens | {a['tt_reopens']} | {b['tt_reopens']} |",
            f"| Max depth | {a['max_depth']} | {b['max_depth']} |",
            f"| Deals executed | {a['deals_executed']} | {b['deals_executed']} |",
            f"| RSS MiB | {a['peak_rss_mb']} | {b['peak_rss_mb']} |",
            f"| Time s | {a['elapsed_s']:.1f} | {b['elapsed_s']:.1f} |",
            "",
            "## 11. Interpretation",
            "",
            payload["interpretation"],
            "",
            "## 12. Exactly one next recommendation",
            "",
            payload["next_recommendation"],
            "",
            "## Integrity",
            "",
            f"Base SHA `{payload['base_sha']}`. Deal `deals/4925153.txt`.",
            "Probe default OFF. Engine `enumerate_legal_actions` / `can_deal(MW_RULES)`",
            "are the Deal authority. Canonical 4925153 route was not used to guide search.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(verdict: str, control: dict, treat: dict) -> str:
    s = treat.get("strongest_zero_probe")
    return (
        f"Control stock-0 FD={control['fd_by_stock'][0]['face_down']} "
        f"later_dealt={control['stock_depth_rows'][0].get('later_dealt_fd')}. "
        f"Treatment probes={sum(treat['probe_fires'])} entered={sum(treat['probe_entered'])}. "
        f"Strongest stock-0 probe={s}. Verdict {verdict}."
    )


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    control = run_arm("CONTROL", False, opening)
    _write_json(CHECKPOINTS / "CONTROL.json", control)
    treat = run_arm("PROBE", True, opening)
    _write_json(CHECKPOINTS / "PROBE.json", treat)
    verdict, note = choose_verdict(control, treat)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "control": control,
        "treatment": treat,
        "verdict": verdict,
        "note": note,
        "interpretation": interpret(verdict, control, treat),
        "next_recommendation": next_recommendation(verdict),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
