#!/usr/bin/env python3
"""Reveal/stock coupling audit v0.4 — diagnostics only, v0.3 search unchanged."""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import DEFAULT_DEPTH_BANDS, solve_progressive
from spider.simple_reveal_stock_audit import (
    build_stock_depth_rows,
    classify_loss_reason,
    summarize_deal_traces,
)


EXPERIMENT = "simple_progressive_reveal_stock_audit_v0_4"
BASE_SHA = "cb4c5bfecc874542dc01b06a1dece59b454fa1e5"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
PRIMARY = ("P1", 1_000_000, 1800.0)


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
    }


def compact(opening: SpiderState, result) -> dict:
    audit = result.audit
    rows = build_stock_depth_rows(audit, opening) if audit else []
    reasons = Counter(row["primary_loss_reason"] for row in rows if row["best_fd"] is not None)
    traces = audit.deal_traces if audit else []
    summary = summarize_deal_traces(traces)
    legal_strong = sum(1 for row in rows if row.get("deal_legal"))
    blocked_empty = sum(
        1
        for row in rows
        if row.get("deal_legal") is False and (row.get("empties") or 0) > 0
    )
    post_exp = [row.get("post_expansions") for row in rows]
    post_tt = sum(1 for row in rows if row.get("post_tt_skip"))
    post_expanded = sum(
        1 for rec in (audit.continuation if audit else []) if not rec.get("tt_skip")
    )
    post_not = sum(1 for rec in (audit.continuation if audit else []) if rec.get("tt_skip"))
    return {
        "solved": result.solved,
        "nodes": result.nodes,
        "elapsed_s": result.elapsed_s,
        "states_per_sec": result.states_per_sec,
        "max_foundations": result.max_foundations,
        "unique": result.stats.unique_exact_states,
        "deals_executed": result.stats.deals_executed,
        "peak_rss_mb": result.stats.peak_rss_mb,
        "replay_ok": result.replay_ok,
        "pareto_log": (audit.pareto_log if audit else [])[:80],
        "pareto_count": 0 if audit is None else len(audit.pareto_log),
        "stock_depth_rows": rows,
        "reason_counts": dict(reasons),
        "deal_summary": summary,
        "strong_legal_deal": legal_strong,
        "strong_blocked_empty": blocked_empty,
        "median_deal_ordinal": summary.get("median_ordinal"),
        "prep_preferred_depths": [
            row["deals_completed"] for row in rows if row.get("prep_preferred")
        ],
        "prep_followed_depths": [
            row["deals_completed"] for row in rows if row.get("prep_then_deal_followed")
        ],
        "post_deal_expanded": post_expanded,
        "post_deal_tt_skipped": post_not,
        "post_deal_expansions_by_depth": post_exp,
        "post_tt_skip_rows": post_tt,
        "reveal": _replay(opening, result.best_reveal_actions, result.best_reveal_cost),
        "stock": _replay(opening, result.best_stock_actions, result.best_stock_cost),
    }


def dominant_verdict(compacted: dict) -> tuple[str, str]:
    rows = compacted["stock_depth_rows"]
    counts = compacted["reason_counts"]
    if not counts:
        return "INCONCLUSIVE", "no stock-depth rows"
    zero = next((row for row in rows if row["deals_completed"] == 0), None)
    if (
        zero
        and zero.get("best_fd") is not None
        and zero.get("deal_legal")
        and not zero.get("lineage_dealt")
        and (zero.get("empties") or 0) == 0
    ):
        return (
            "REVEAL_BRANCH_DEAL_STARVATION",
            "0-deal best-reveal lineage never Deals though Deal is legal and "
            f"deal_now_fd={zero.get('deal_now_fd')}; later_dealt fd="
            f"{zero.get('later_dealt_fd')}",
        )
    ranked = sorted(counts.items(), key=lambda item: -item[1])
    top, n = ranked[0]
    total = sum(counts.values())
    mapping = {
        "R1": "REVEAL_BRANCH_DEAL_STARVATION",
        "R2": "EMPTY_WORKSPACE_BLOCKS_DEAL",
        "R3": "REVEAL_BRANCH_DEAL_STARVATION",
        "R4": "KNOWN_DEAL_DESTROYS_REVEAL_STRUCTURE",
        "R5": "POST_DEAL_CONTINUATION_STARVATION",
        "R6": "TT_COVERAGE_BLOCKS_GOOD_POST_DEAL_LINES",
        "R7": "PREPARATION_NOT_CONVERTED",
        "R8": "MULTIPLE_CAUSES",
    }
    starve = counts.get("R1", 0) + counts.get("R3", 0)
    if starve > total / 2:
        return (
            "REVEAL_BRANCH_DEAL_STARVATION",
            f"R1+R3={starve}/{total}; Deal late or never on strong-reveal lineages",
        )
    if n <= total / 2 and len(ranked) > 1:
        detail = ", ".join(f"{k}:{v}" for k, v in ranked)
        return "MULTIPLE_CAUSES", detail
    return mapping.get(top, "MULTIPLE_CAUSES"), f"{top} on {n}/{total} stock depths"


def next_recommendation(verdict: str) -> str:
    if verdict == "REVEAL_BRANCH_DEAL_STARVATION":
        return (
            "Keep the solver unchanged except one bounded experiment: when a new "
            "best-reveal exact state has legal Deal, try Deal (or its 1-ply prep) "
            "before remaining tableau siblings in that node only. Do not add quotas."
        )
    if verdict == "EMPTY_WORKSPACE_BLOCKS_DEAL":
        return (
            "Measure fill-then-Deal from strong-reveal empties as a one-node "
            "counterfactual policy; do not add a workspace service."
        )
    if verdict == "KNOWN_DEAL_DESTROYS_REVEAL_STRUCTURE":
        return (
            "Keep search order; the next measurement is whether a cheap known-row "
            "veto of Deal from strong-reveal states preserves uncovering without "
            "blocking stock progress elsewhere."
        )
    if verdict == "PREPARATION_NOT_CONVERTED":
        return (
            "From a strong-reveal state, force the existing 1-ply prep then Deal "
            "as a single diagnostic arm; do not retune prep scoring."
        )
    if verdict == "POST_DEAL_CONTINUATION_STARVATION":
        return (
            "Give Deal children a one-time continuation bump (search remaining "
            "depth only); do not change Deal scoring."
        )
    if verdict == "TT_COVERAGE_BLOCKS_GOOD_POST_DEAL_LINES":
        return (
            "Log which pass/remaining-depth coverage suppresses post-Deal children "
            "of strong reveals; do not weaken TT globally."
        )
    return (
        "Report per-depth R-codes and pick the first transition (pre-Deal vs Deal "
        "vs post-Deal) that appears on the fd=16 lineage; do not add heuristics."
    )


def write_report(payload: dict) -> None:
    c = payload["compact"]
    rows = c["stock_depth_rows"]
    lines = [
        "# Simple Progressive Search v0.4: Reveal/Stock Coupling Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload['note']}.",
        "",
        "Diagnostics only. Search order, saturation, TT, and Deal policy match v0.3.",
        "",
        "## 2. Pareto progression",
        "",
        f"{c['pareto_count']} frontier improvements. First/last:",
        "",
    ]
    log = c["pareto_log"]
    if log:
        lines.append(f"- first: {log[0]}")
        lines.append(f"- last: {log[-1]}")
    lines.extend(
        [
            "",
            "## 3. Reveal quality by stock depth",
            "",
            "| Stock depth | Best FD | Best FD that later dealt | Immediate pre-Deal FD | Post-Deal FD | Primary loss reason |",
            "| ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        def _s(value):
            return "—" if value is None else str(value)

        lines.append(
            f"| {row['deals_completed']} | {_s(row['best_fd'])} | "
            f"{_s(row['later_dealt_fd'])} | {_s(row['pre_fd'])} | "
            f"{_s(row['post_fd'])} | {row['primary_loss_reason']} |"
        )
    lines.extend(["", "## 4. Strong-reveal Deal legality", ""])
    for row in rows:
        lines.append(
            f"- depth {row['deals_completed']}: legal={row['deal_legal']} "
            f"tier={row['deal_tier']} landing={row['landing_score']} "
            f"pass3_index={row['deal_index_pass3']} empties={row['empties']} "
            f"deal_now_fd={row['deal_now_fd']} prep_fd={row['prep_then_deal_fd']}."
        )
    lines.extend(
        [
            "",
            "## 5. Empty-column effects",
            "",
            f"Strong-reveal states with legal Deal: {c['strong_legal_deal']}. "
            f"Blocked by empties under search rules: {c['strong_blocked_empty']}.",
            "MW_RULES.can_deal_into_empty is True, so empties do not make Deal illegal",
            "in this profile unless a restricted rule set is used.",
            "",
            "## 6. Deal ordering",
            "",
            f"Median Deal ordinal among ordered children: {c['median_deal_ordinal']}.",
            f"Deal summary: {c['deal_summary']}.",
            "",
            "## 7. Deal-transition structural deltas",
            "",
            f"Executed Deals: {c['deals_executed']}. "
            f"Mean Δfd={c['deal_summary'].get('mean_delta_fd')}, "
            f"mean Δsame-suit joins={c['deal_summary'].get('mean_delta_same')}, "
            f"mean parent empties={c['deal_summary'].get('mean_parent_empties')}.",
            "",
            "## 8. Preparation conversion",
            "",
            f"Depths where prep preferred: {c['prep_preferred_depths']}.",
            f"Depths where prep then Deal followed: {c['prep_followed_depths']}.",
            "",
            "## 9. Post-Deal continuation",
            "",
            f"Deal children expanded: {c['post_deal_expanded']}; "
            f"TT-skipped: {c['post_deal_tt_skipped']}.",
            f"Subtree expansions on linked pre-Deal parents: {c['post_deal_expansions_by_depth']}.",
            "",
            "## 10. Dominant causal diagnosis",
            "",
            f"Reason counts: {c['reason_counts']}.",
            payload["note"],
            "",
            "## 11. Search/runtime overhead",
            "",
            f"Expanded {c['nodes']} in {c['elapsed_s']:.1f}s ({c['states_per_sec']:.1f}/s), "
            f"RSS {c['peak_rss_mb']} MiB. v0.3 P1 was 800k in 828s at 967.6/s.",
            "",
            "## 12. Exactly one next recommendation",
            "",
            payload["next_recommendation"],
            "",
            "## Integrity",
            "",
            f"Base SHA `{payload['base_sha']}`. Deal `deals/4925153.txt`.",
            "Audit hooks do not insert counterfactual moves into search.",
            "Witness paths replay through `replay_actions`.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    name, nodes, limit = PRIMARY
    print(f"START {name} nodes={nodes} audit=on saturation=on", flush=True)
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=nodes,
        time_limit_s=limit,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
        enable_saturation=True,
        enable_audit=True,
    )
    elapsed = time.perf_counter() - started
    compacted = compact(opening, result)
    compacted["elapsed_wall_s"] = elapsed
    _write_json(CHECKPOINTS / f"{name}.json", compacted)
    verdict, note = dominant_verdict(compacted)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "verdict": verdict,
        "note": note,
        "next_recommendation": next_recommendation(verdict),
        "compact": compacted,
        "foundations": result.max_foundations,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(
        f"DONE unique={compacted['unique']} deals={compacted['deals_executed']} "
        f"reasons={compacted['reason_counts']} sps={compacted['states_per_sec']:.1f}",
        flush=True,
    )
    print(f"VERDICT {verdict}")
    print(f"WROTE {RESULT}")
    print(f"WROTE {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
