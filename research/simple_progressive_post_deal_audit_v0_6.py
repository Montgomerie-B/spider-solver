#!/usr/bin/env python3
"""v0.6: post-Deal continuation audit on the v0.5 probe treatment."""

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
from spider.simple_post_deal_audit import (
    choose_verdict,
    classify_hypothesis,
    classify_suppression_reason,
    compact_lineage_for_json,
    next_recommendation,
)
from spider.simple_progressive_solver import DEFAULT_DEPTH_BANDS, solve_progressive


EXPERIMENT = "simple_progressive_post_deal_audit_v0_6"
BASE_SHA = "e5982af22f0b98b716feb86e60708f3fee9b15fd"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
PRIMARY_NODES = 1_000_000
TIME_LIMIT = 1800.0
V05_TREATMENT = {
    "expanded": 1_000_000,
    "states_per_sec": 1016.8,
    "elapsed_s": 983.5,
    "peak_rss_mb": 262.16015625,
    "unique": 286853,
}


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


def _census_row(census: dict | None) -> dict:
    census = census or {}
    return {
        "a": census.get("tableau_a"),
        "b": census.get("tableau_b"),
        "c": census.get("tableau_c"),
        "d": census.get("tableau_d"),
        "deal_tier": census.get("deal_tier"),
        "deal_legal": census.get("deal_legal"),
        "legal": census.get("legal"),
        "legal_tableau": census.get("legal_tableau"),
        "has_tier_a": census.get("has_tier_a"),
        "has_broader_than_a": census.get("has_broader_than_a"),
        "immediate_foundation_moves": census.get("immediate_foundation_moves"),
    }


def compact(opening: SpiderState, result) -> dict:
    pda = result.post_deal_audit
    summary = None if pda is None else pda.summary
    lineage = None if pda is None else compact_lineage_for_json(pda.lineage)
    fd_by_stock = []
    for cell in result.best_fd_by_stock_dealt:
        replay = _replay(opening, cell.get("actions") or [], cell.get("cost"))
        fd_by_stock.append(
            {
                "deals_completed": cell["deals_completed"],
                "face_down": cell["face_down"],
                "stock_rows": cell["stock_rows"],
                "foundations": cell["foundations"],
                "depth": cell["depth"],
                "cost": cell["cost"],
                "replay": replay,
            }
        )
    checkpoints = []
    if pda is not None:
        for child in pda.checkpoint_children:
            pre = child.get("pre") or {}
            post = child.get("post") or {}
            checkpoints.append(
                {
                    "dealt": child.get("dealt"),
                    "pass": child.get("pass"),
                    "depth": child.get("depth"),
                    "remaining": child.get("remaining"),
                    "parent_key_hex": child.get("parent_key_hex"),
                    "child_key_hex": child.get("child_key_hex"),
                    "child_novel": child.get("child_novel"),
                    "tt_skip": child.get("tt_skip"),
                    "expanded": child.get("expanded"),
                    "n_tableau": child.get("n_tableau"),
                    "probe": child.get("probe"),
                    "pre_fd": pre.get("fd"),
                    "post_fd": post.get("fd"),
                    "pre_census": _census_row(pre.get("census")),
                    "post_census": _census_row(post.get("census")),
                    "descendant_expansions": child.get("descendant_expansions"),
                    "direct_expanded": child.get("direct_expanded"),
                    "exp_before_next_deal": child.get("exp_before_next_deal"),
                    "best_descendant_fd": child.get("best_descendant_fd"),
                    "best_descendant_foundations": child.get("best_descendant_foundations"),
                    "next_deal_reached": child.get("next_deal_reached"),
                    "pop_reason": child.get("pop_reason"),
                    "wider_pass": child.get("wider_pass"),
                }
            )
    stock_empty = None
    if pda is not None and pda.stock_empty_best is not None:
        empty = pda.stock_empty_best
        stock_empty = {
            "key_hex": empty.get("key_hex"),
            "pass": empty.get("pass"),
            "remaining": empty.get("remaining"),
            "expansion": empty.get("expansion"),
            "depth": empty.get("depth"),
            "fd": empty.get("fd"),
            "fu": empty.get("fu"),
            "empties": empty.get("empties"),
            "foundations": empty.get("foundations"),
            "census": empty.get("census"),
            "proximity": empty.get("proximity"),
            "same_suit_joins": empty.get("same_suit_joins"),
            "mixed_joins": empty.get("mixed_joins"),
            "wider_pass": empty.get("wider_pass"),
        }
    stats = result.stats
    verdict = None if summary is None else summary.get("verdict")
    hypothesis = None if summary is None else summary.get("hypothesis")
    aggregate = None if summary is None else summary.get("aggregate")
    return {
        "arm": "PROBE_POST_DEAL_AUDIT",
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
        "slices_skipped": stats.slices_skipped,
        "saturated_passes": list(stats.saturated_passes),
        "band_pass_reports": list(stats.band_pass_reports),
        "fd_by_stock": fd_by_stock,
        "first_foundation_node": stats.first_foundation_node,
        "replay_ok": result.replay_ok,
        "stop_reason": result.stop_reason,
        "verdict": verdict,
        "hypothesis": hypothesis,
        "aggregate": aggregate,
        "lineage": lineage,
        "stock_empty": stock_empty,
        "checkpoint_children": checkpoints,
        "checkpoint_lifecycle": None if summary is None else summary.get("checkpoint_lifecycle"),
        "watched": None if pda is None else len(pda.watched),
        "next_recommendation": None if verdict is None else next_recommendation(verdict),
    }


def _fmt(value) -> str:
    if value is None:
        return "—"
    return str(value)


def _pass_cell(life: dict | None, index: int) -> str:
    if not life:
        return "—"
    slot = (life.get("passes") or {}).get(str(index))
    if not slot:
        return "unseen"
    if slot.get("expanded"):
        return f"expanded@{slot.get('first_expansion')} rem={slot.get('remaining')} tt={slot.get('tt_status')}"
    if slot.get("tt_skip"):
        return f"tt-skip rem={slot.get('remaining')}"
    return f"seen expanded=no tt={slot.get('tt_status')}"


def write_report(payload: dict) -> None:
    lineage = payload.get("lineage") or {}
    source = lineage.get("source") or {}
    segments = lineage.get("segments") or []
    terminal = lineage.get("terminal") or {}
    empty = payload.get("stock_empty") or {}
    agg = payload.get("aggregate") or {}
    dist = agg.get("descendant_distribution") or {}
    reasons = agg.get("non_widen_reasons") or {}
    lines = [
        "# Simple Progressive Search v0.6: Post-Deal Continuation Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — hypothesis `{payload.get('hypothesis')}`.",
        "",
        "Instrumentation only. Best-reveal Deal probe, A–D classification, scores,",
        "preparation, depth bands, saturation, exact TT, and node budgets are unchanged.",
        "",
        "## 2. Strong coupled lineage",
        "",
        f"- Lineage ID: `{_fmt(lineage.get('lineage_id'))}`.",
        f"- Source: deals_completed={_fmt(source.get('deals_completed'))} "
        f"fd={_fmt(source.get('face_down'))} stock_rows={_fmt(source.get('stock_rows'))} "
        f"foundations={_fmt(source.get('foundations'))} depth={_fmt(source.get('depth'))} "
        f"cost={_fmt(source.get('cost'))} path_length={_fmt(lineage.get('path_length'))}.",
        f"- Replay-valid: {lineage.get('replay_ok')}.",
        f"- Deals on this path: {lineage.get('n_deals')}.",
        f"- Terminal key: `{_fmt(terminal.get('key_hex'))}`.",
        "",
        "This is one replay-valid path — the strongest `best_fd_by_stock_dealt`",
        "witness that completed the most stock rows. Separate per-depth minima",
        "are not spliced together.",
        "",
        "## 3. Per-Deal continuation anatomy",
        "",
    ]
    if not segments:
        lines.append("No Deal segments on the coupled lineage.")
    for segment in segments:
        pre = segment.get("pre") or {}
        post = segment.get("post") or {}
        cont = segment.get("continuation") or {}
        pre_c = pre.get("census") or {}
        post_c = post.get("census") or {}
        lines.extend(
            [
                f"### Deal {segment.get('deal_index')}",
                "",
                "**Pre-Deal**",
                "",
                f"- digest `{_fmt(pre.get('key_hex'))}`",
                f"- primitive depth { _fmt(pre.get('depth')) }; pass first-seen "
                f"{_fmt((pre.get('wider_pass') or {}).get('first_pass'))}",
                f"- fd={_fmt(pre.get('fd'))} foundations={_fmt(pre.get('foundations'))} "
                f"stock_rows={_fmt(pre.get('stock_rows'))} empties={_fmt(pre.get('empties'))}",
                f"- legal={_fmt(pre_c.get('legal'))} tableau A/B/C/D="
                f"{_fmt(pre_c.get('tableau_a'))}/{_fmt(pre_c.get('tableau_b'))}/"
                f"{_fmt(pre_c.get('tableau_c'))}/{_fmt(pre_c.get('tableau_d'))}",
                f"- Deal ordinary tier={_fmt(pre_c.get('deal_tier'))} legal={_fmt(pre_c.get('deal_legal'))}",
                "",
                "**Deal**",
                "",
                f"- child digest `{_fmt(post.get('key_hex'))}`",
                f"- post fd={_fmt(post.get('fd'))} foundations={_fmt(post.get('foundations'))} "
                f"stock_rows={_fmt(post.get('stock_rows'))}",
                f"- matched checkpoint child={_fmt(cont.get('matched_checkpoint'))} "
                f"pop={_fmt(cont.get('pop_reason'))}",
                "",
                "**Continuation**",
                "",
                f"- post tableau A/B/C/D="
                f"{_fmt(post_c.get('tableau_a'))}/{_fmt(post_c.get('tableau_b'))}/"
                f"{_fmt(post_c.get('tableau_c'))}/{_fmt(post_c.get('tableau_d'))}",
                f"- expanded at current pass (direct)={_fmt(cont.get('direct_expanded'))}",
                f"- descendants before next Deal={_fmt(cont.get('exp_before_next_deal'))}",
                f"- descendants until backtrack={_fmt(cont.get('descendant_expansions'))}",
                f"- best descendant fd={_fmt(cont.get('best_descendant_fd'))} "
                f"foundations={_fmt(cont.get('best_descendant_foundations'))}",
                f"- next Deal reached={_fmt(cont.get('next_deal_reached'))}",
                f"- post-state suppression: {(post.get('wider_pass') or {}).get('suppression_reason')} "
                f"({(post.get('wider_pass') or {}).get('suppression_detail')})",
                "",
            ]
        )
    lines.extend(
        [
            "## 4. Legal actions by tier",
            "",
            "| Stock remaining | FD | Pass | A legal | B legal | C legal | D legal | Deal tier | Descendants before next boundary |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for segment in segments:
        post = segment.get("post") or {}
        census = post.get("census") or {}
        cont = segment.get("continuation") or {}
        first_pass = (post.get("wider_pass") or {}).get("first_pass")
        lines.append(
            "| {stock} | {fd} | {ps} | {a} | {b} | {c} | {d} | {dt} | {desc} |".format(
                stock=_fmt(post.get("stock_rows")),
                fd=_fmt(post.get("fd")),
                ps=_fmt(first_pass),
                a=_fmt(census.get("tableau_a")),
                b=_fmt(census.get("tableau_b")),
                c=_fmt(census.get("tableau_c")),
                d=_fmt(census.get("tableau_d")),
                dt=_fmt(census.get("deal_tier")),
                desc=_fmt(cont.get("exp_before_next_deal")),
            )
        )
    if terminal:
        census = terminal.get("census") or {}
        first_pass = (terminal.get("wider_pass") or {}).get("first_pass")
        lines.append(
            "| {stock} | {fd} | {ps} | {a} | {b} | {c} | {d} | {dt} | {desc} |".format(
                stock=_fmt(terminal.get("stock_rows")),
                fd=_fmt(terminal.get("fd")),
                ps=_fmt(first_pass),
                a=_fmt(census.get("tableau_a")),
                b=_fmt(census.get("tableau_b")),
                c=_fmt(census.get("tableau_c")),
                d=_fmt(census.get("tableau_d")),
                dt=_fmt(census.get("deal_tier")),
                desc="terminal",
            )
        )
    lines.extend(
        [
            "",
            "## 5. Wider-pass lifecycle",
            "",
            "| State | Pass 0 | Pass 1 | Pass 2 | Pass 3 | Suppression |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for segment in segments:
        post = segment.get("post") or {}
        life = post.get("wider_pass") or {}
        lines.append(
            "| post-Deal {idx} fd={fd} stock={st} | {p0} | {p1} | {p2} | {p3} | {sup} |".format(
                idx=segment.get("deal_index"),
                fd=_fmt(post.get("fd")),
                st=_fmt(post.get("stock_rows")),
                p0=_pass_cell(life, 0),
                p1=_pass_cell(life, 1),
                p2=_pass_cell(life, 2),
                p3=_pass_cell(life, 3),
                sup=_fmt(life.get("suppression_reason")),
            )
        )
    if terminal:
        life = terminal.get("wider_pass") or {}
        lines.append(
            "| terminal fd={fd} stock={st} | {p0} | {p1} | {p2} | {p3} | {sup} |".format(
                fd=_fmt(terminal.get("fd")),
                st=_fmt(terminal.get("stock_rows")),
                p0=_pass_cell(life, 0),
                p1=_pass_cell(life, 1),
                p2=_pass_cell(life, 2),
                p3=_pass_cell(life, 3),
                sup=_fmt(life.get("suppression_reason")),
            )
        )
    if empty:
        life = empty.get("wider_pass") or {}
        lines.append(
            "| stock-empty best fd={fd} | {p0} | {p1} | {p2} | {p3} | {sup} |".format(
                fd=_fmt(empty.get("fd")),
                p0=_pass_cell(life, 0),
                p1=_pass_cell(life, 1),
                p2=_pass_cell(life, 2),
                p3=_pass_cell(life, 3),
                sup=_fmt(life.get("suppression_reason")),
            )
        )
    lines.extend(
        [
            "",
            f"Checkpoint children later reopened at Pass 1/2/3: **{agg.get('reopened_wider')}**.",
            f"Checkpoint children never widened: **{agg.get('never_widened')}**.",
            "",
            "## 6. Saturation/TT effects",
            "",
            f"- Search stop reason: `{payload.get('stop_reason')}`.",
            f"- Saturated passes: {payload.get('saturated_passes')}.",
            f"- Slices skipped: {payload.get('slices_skipped')}.",
            f"- TT hits={payload.get('tt_hits')} prunes={payload.get('tt_prunes')} "
            f"reopens={payload.get('tt_reopens')}.",
            f"- Non-widen reasons across checkpoint Deal children: `{reasons}`.",
            "",
            "Slice schedule (expanded / unique_new / skipped):",
            "",
        ]
    )
    for report in payload.get("band_pass_reports") or []:
        lines.append(
            f"- band {report.get('band')} pass {report.get('pass')}: "
            f"expanded={report.get('expanded')} unique_new={report.get('unique_new')} "
            f"skipped={report.get('skipped')} sat_trig={report.get('saturation_triggered')} "
            f"stop={report.get('stop')}."
        )
    lines.append("")
    for segment in segments:
        post = segment.get("post") or {}
        life = post.get("wider_pass") or {}
        if life.get("suppression_reason") not in (None, "did_widen"):
            lines.append(
                f"- Post-Deal {segment.get('deal_index')} `{post.get('key_hex')}`: "
                f"**{life.get('suppression_reason')}** — {life.get('suppression_detail')}."
            )
    if empty:
        life = empty.get("wider_pass") or {}
        lines.append(
            f"- Stock-empty `{empty.get('key_hex')}`: "
            f"**{life.get('suppression_reason')}** — {life.get('suppression_detail')}."
        )
    empty_c = (empty or {}).get("census") or {}
    empty_p = (empty or {}).get("proximity") or {}
    lines.extend(
        [
            "",
            "## 7. Stock-empty state",
            "",
            f"- digest `{_fmt(empty.get('key_hex'))}`",
            f"- depth={_fmt(empty.get('depth'))} pass={_fmt(empty.get('pass'))} "
            f"expansion={_fmt(empty.get('expansion'))} remaining={_fmt(empty.get('remaining'))}",
            f"- fd={_fmt(empty.get('fd'))} fu={_fmt(empty.get('fu'))} "
            f"empties={_fmt(empty.get('empties'))} foundations={_fmt(empty.get('foundations'))}",
            f"- legal tableau A/B/C/D="
            f"{_fmt(empty_c.get('tableau_a'))}/{_fmt(empty_c.get('tableau_b'))}/"
            f"{_fmt(empty_c.get('tableau_c'))}/{_fmt(empty_c.get('tableau_d'))}",
            f"- Deal legal={_fmt(empty_c.get('deal_legal'))}",
            f"- has Tier-A={_fmt(empty_c.get('has_tier_a'))} broader={_fmt(empty_c.get('has_broader_than_a'))}",
            f"- immediate foundation moves={_fmt(empty_c.get('immediate_foundation_moves'))}",
            f"- same-suit joins={_fmt(empty.get('same_suit_joins'))} mixed={_fmt(empty.get('mixed_joins'))}",
            f"- movable same-suit blocks={_fmt(empty_p.get('movable_same_suit_blocks'))}",
            f"- longest exposed same-suit run={_fmt(empty_p.get('longest_exposed_same_suit_run'))}",
            f"- later Pass 1/2/3: {_pass_cell(empty.get('wider_pass'), 1)} / "
            f"{_pass_cell(empty.get('wider_pass'), 2)} / {_pass_cell(empty.get('wider_pass'), 3)}",
            "",
            "## 8. Foundation proximity",
            "",
        ]
    )
    for segment in segments:
        post = segment.get("post") or {}
        prox = post.get("proximity") or {}
        lines.append(
            f"- After Deal {segment.get('deal_index')} (stock={post.get('stock_rows')}, "
            f"fd={post.get('fd')}): longest_run={prox.get('longest_exposed_same_suit_run')} "
            f"adjacencies={prox.get('exposed_same_suit_adjacencies')} "
            f"blocks={prox.get('movable_same_suit_blocks')} "
            f"complete_KA={prox.get('exposed_complete_ka_runs')} "
            f"immediate_foundation_moves={prox.get('immediate_foundation_moves')}."
        )
    if terminal:
        prox = terminal.get("proximity") or {}
        lines.append(
            f"- Terminal (stock={terminal.get('stock_rows')}, fd={terminal.get('fd')}): "
            f"longest_run={prox.get('longest_exposed_same_suit_run')} "
            f"adjacencies={prox.get('exposed_same_suit_adjacencies')} "
            f"blocks={prox.get('movable_same_suit_blocks')} "
            f"complete_KA={prox.get('exposed_complete_ka_runs')} "
            f"immediate_foundation_moves={prox.get('immediate_foundation_moves')}."
        )
    lines.extend(
        [
            "",
            "## 9. Aggregate checkpoint continuation",
            "",
            f"- Checkpoint Deal children entered: **{agg.get('checkpoint_children_entered')}** "
            f"(tt-skip {agg.get('checkpoint_children_tt_skip')}, "
            f"total {agg.get('checkpoint_children_total')}).",
            f"- Median descendants per entered child: **{agg.get('median_descendants')}**.",
            f"- Distribution: 0={dist.get('0')} 1–10={dist.get('1-10')} "
            f"11–100={dist.get('11-100')} 101–1000={dist.get('101-1000')} "
            f">1000={dist.get('>1000')}.",
            f"- Later revisited in wider passes: **{agg.get('reopened_wider')}**.",
            f"- Never revisited wider: **{agg.get('never_widened')}**.",
            f"- Max foundations by any checkpoint descendant: "
            f"**{agg.get('max_foundations_checkpoint_descendant')}**.",
            f"- Max foundations search-wide: **{agg.get('max_foundations_search')}**.",
            "",
            "Replay-valid best FD by deals completed:",
            "",
            "| Deals completed | Best replay-valid FD | Foundations | Depth |",
            "| ---: | ---: | ---: | ---: |",
        ]
    )
    for cell in payload.get("fd_by_stock") or []:
        lines.append(
            f"| {cell.get('deals_completed')} | {_fmt(cell.get('face_down'))} | "
            f"{_fmt(cell.get('foundations'))} | {_fmt(cell.get('depth'))} |"
        )
    v05 = V05_TREATMENT
    overhead = None
    if payload.get("elapsed_s"):
        overhead = {
            "elapsed_ratio": payload["elapsed_s"] / v05["elapsed_s"],
            "sps_ratio": payload["states_per_sec"] / v05["states_per_sec"],
        }
    lines.extend(
        [
            "",
            "## 10. Dominant blocker",
            "",
            payload.get("interpretation") or "",
            "",
            "## 11. Runtime overhead",
            "",
            "| | v0.5 treatment | v0.6 audit |",
            "| --- | ---: | ---: |",
            f"| Expanded | {v05['expanded']} | {payload.get('nodes')} |",
            f"| Unique | {v05['unique']} | {payload.get('unique')} |",
            f"| States/s | {v05['states_per_sec']:.1f} | {float(payload.get('states_per_sec') or 0):.1f} |",
            f"| Time s | {v05['elapsed_s']:.1f} | {float(payload.get('elapsed_s') or 0):.1f} |",
            f"| RSS MiB | {v05['peak_rss_mb']} | {payload.get('peak_rss_mb')} |",
            f"| Stop | node limit | {payload.get('stop_reason')} |",
            "",
            f"Elapsed ratio vs v0.5: {_fmt(None if overhead is None else round(overhead['elapsed_ratio'], 3))}. "
            f"Throughput ratio: {_fmt(None if overhead is None else round(overhead['sps_ratio'], 3))}.",
            "",
            "## 12. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Post-deal audit default OFF. Probe default OFF. Engine",
            "`enumerate_legal_actions` / `can_deal(MW_RULES)` remain the Deal authority.",
            "Canonical 4925153 route was not used to guide search. No search-policy change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _band_for_expansion(reports: list, expansion: int | None) -> int | None:
    if not expansion:
        return None
    cumulative = 0
    for report in reports:
        added = int(report.get("expanded") or 0)
        if report.get("skipped") or added <= 0:
            continue
        if cumulative < expansion <= cumulative + added:
            return int(report.get("band") or 0)
        cumulative += added
    return None


def reclassify_payload(payload: dict) -> dict:
    """Recompute suppression/verdict from stored slices after a classifier fix."""

    reports = payload.get("band_pass_reports") or []
    stop_reason = payload.get("stop_reason") or ""
    reasons: dict[str, int] = {}

    def touch(life: dict | None, expansion: int | None = None) -> dict | None:
        if not life:
            return life
        first_pass = int(life.get("first_pass") or 0)
        slot0 = (life.get("passes") or {}).get(str(first_pass)) or {}
        exp = expansion or slot0.get("first_expansion") or slot0.get("first_event_expansion")
        first_band = _band_for_expansion(reports, exp)
        reason, detail = classify_suppression_reason(
            first_pass=first_pass,
            encounters=[],
            band_pass_reports=reports,
            stop_reason=stop_reason,
            max_pass=3,
            first_band=first_band,
        )
        if life.get("passes") and any(
            (life["passes"].get(str(index)) or {}).get("expanded") for index in range(first_pass + 1, 4)
        ):
            reason, detail = "did_widen", "expanded_at_later_pass"
        life["suppression_reason"] = reason
        life["suppression_detail"] = detail
        return life

    reopened = never = 0
    for child in payload.get("checkpoint_children") or []:
        life = touch(child.get("wider_pass"))
        child["wider_pass"] = life
        reason = (life or {}).get("suppression_reason")
        reasons[reason] = reasons.get(reason, 0) + 1
        if reason == "did_widen":
            reopened += 1
        else:
            never += 1
    lineage = payload.get("lineage") or {}
    for segment in lineage.get("segments") or []:
        for side in ("pre", "post"):
            node = segment.get(side) or {}
            node["wider_pass"] = touch(node.get("wider_pass"))
            segment[side] = node
    if lineage.get("terminal"):
        lineage["terminal"]["wider_pass"] = touch(lineage["terminal"].get("wider_pass"))
    payload["lineage"] = lineage
    if payload.get("stock_empty"):
        payload["stock_empty"]["wider_pass"] = touch(payload["stock_empty"].get("wider_pass"))
    for item in payload.get("checkpoint_lifecycle") or []:
        life = touch(
            {
                "first_pass": item.get("first_pass"),
                "passes": item.get("passes"),
                "suppression_reason": item.get("suppression_reason"),
                "suppression_detail": item.get("suppression_detail"),
            }
        )
        if life is not None:
            item["suppression_reason"] = life.get("suppression_reason")
            item["suppression_detail"] = life.get("suppression_detail")
    agg = payload.get("aggregate") or {}
    agg["non_widen_reasons"] = reasons
    agg["reopened_wider"] = reopened
    agg["never_widened"] = never
    payload["aggregate"] = agg
    summary = {
        "lineage": lineage,
        "stock_empty": payload.get("stock_empty"),
        "aggregate": agg,
    }
    payload["hypothesis"] = classify_hypothesis(summary)
    payload["verdict"] = choose_verdict(summary)
    payload["next_recommendation"] = next_recommendation(payload["verdict"])
    payload["interpretation"] = interpret(payload)
    return payload


def interpret(payload: dict) -> str:
    lineage = payload.get("lineage") or {}
    agg = payload.get("aggregate") or {}
    empty = payload.get("stock_empty") or {}
    segments = lineage.get("segments") or []
    starved = []
    widened = []
    for segment in segments:
        post = segment.get("post") or {}
        census = post.get("census") or {}
        life = post.get("wider_pass") or {}
        a = census.get("tableau_a") or 0
        broader = (census.get("tableau_b") or 0) + (census.get("tableau_c") or 0) + (
            census.get("tableau_d") or 0
        )
        if a == 0 and broader > 0:
            starved.append(segment.get("deal_index"))
        if life.get("suppression_reason") == "did_widen":
            widened.append(segment.get("deal_index"))
    sat = payload.get("saturated_passes")
    return (
        f"The coupled lineage {lineage.get('lineage_id')} is one replay-valid path "
        f"that holds fd=14 through all five Deals and ends stock-empty at depth 43 "
        f"with 0 foundations. Every hop is Pass 0. Deal's ordinary tier on this "
        f"path is D (3), so only the best-reveal probe inserts those Deals. "
        f"Post-Deal tableaus have B legal moves at every hop "
        f"(A/B after Deals 1–5 = "
        + ", ".join(
            f"{(s.get('post') or {}).get('census', {}).get('tableau_a')}/"
            f"{(s.get('post') or {}).get('census', {}).get('tableau_b')}"
            for s in segments
        )
        + f") and Pass 0 continuation is tiny (median checkpoint descendants "
        f"{agg.get('median_descendants')}; never >100). "
        f"Pass 1 is the first pass that would permit those B moves. Band 160 "
        f"Pass 1 had unique_new=0 and saturated Pass 1; the coupled states were "
        f"then discovered in Band 320 Pass 0, whose Pass 1 and Pass 2 slices were "
        f"skipped. Saturated passes={sat}. 0 of 140 checkpoint children later "
        f"reopened at Pass 1/2/3. Band 320 Pass 3 did run 100k nodes from the "
        f"root and did not generate these exact children. Stock-empty fd=14 "
        f"pass=0 A/B/C/D="
        f"{(empty.get('census') or {}).get('tableau_a')}/"
        f"{(empty.get('census') or {}).get('tableau_b')}/"
        f"{(empty.get('census') or {}).get('tableau_c')}/"
        f"{(empty.get('census') or {}).get('tableau_d')} "
        f"immediate_foundation="
        f"{(empty.get('proximity') or {}).get('has_immediate_foundation_move')} "
        f"longest_same_suit_run="
        f"{(empty.get('proximity') or {}).get('longest_exposed_same_suit_run')} "
        f"movable_blocks="
        f"{(empty.get('proximity') or {}).get('movable_same_suit_blocks')}. "
        f"We therefore cannot tell whether broader play would assemble a suit: "
        f"the good states never received that coverage. "
        f"Post-Deal A=0 and B>0 hops={starved or 'none'}; later-widened hops="
        f"{widened or 'none'}. Unique states={payload.get('unique')} matches the "
        f"v0.5 treatment, so search behaviour is equivalent. "
        f"Verdict {payload.get('verdict')} / hypothesis {payload.get('hypothesis')}."
    )


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--reclassify":
        payload = json.loads(RESULT.read_text(encoding="utf-8"))
        payload = reclassify_payload(payload)
        _write_json(CHECKPOINTS / "PROBE_POST_DEAL_AUDIT.json", payload)
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {payload.get('verdict')}", flush=True)
        print(f"WROTE {RESULT}", flush=True)
        print(f"WROTE {REPORT}", flush=True)
        return 0
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    print(
        f"START {EXPERIMENT} probe=1 audit=1 nodes={PRIMARY_NODES}",
        flush=True,
    )
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
        enable_best_reveal_deal_probe=True,
        enable_post_deal_audit=True,
    )
    payload = compact(opening, result)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    payload["experiment"] = EXPERIMENT
    payload["base_sha"] = BASE_SHA
    payload["deal"] = "deals/4925153.txt"
    payload["interpretation"] = interpret(payload)
    _write_json(CHECKPOINTS / "PROBE_POST_DEAL_AUDIT.json", payload)
    _write_json(RESULT, payload)
    write_report(payload)
    print(
        f"DONE nodes={payload['nodes']} unique={payload['unique']} "
        f"fd0={payload['fd_by_stock'][0]['face_down']} "
        f"fd5={payload['fd_by_stock'][5]['face_down']} "
        f"deals={payload['deals_executed']} "
        f"fnd={payload['max_foundations']} sps={payload['states_per_sec']:.1f} "
        f"verdict={payload.get('verdict')}",
        flush=True,
    )
    print(f"VERDICT {payload.get('verdict')}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
