#!/usr/bin/env python3
"""v0.7 A/B: band-local saturation vs cross-band, probe ON."""

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
from spider.simple_post_deal_audit import compact_lineage_for_json, foundation_proximity
from spider.simple_progressive_solver import DEFAULT_DEPTH_BANDS, format_moves_text, solve_progressive


EXPERIMENT = "simple_progressive_band_local_saturation_v0_7"
BASE_SHA = "bcb2d872fbcbc7b790645a269bc4d79eb463a0b8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V06_JSON = ROOT / "docs" / "research" / "simple_progressive_post_deal_audit_v0_6.json"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
SOLUTION = ROOT / "solutions" / "4925153_simple_v0_7.moves.txt"
PRIMARY_NODES = 1_000_000
OPTIONAL_3M = 3_000_000
TIME_LIMIT = 1800.0
TIME_LIMIT_3M = 5400.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def _replay(opening: SpiderState, actions, cost: int | None = None) -> dict:
    end = opening.clone()
    paid = replay_actions(end, list(actions)) if actions else 0
    prox = foundation_proximity(end)
    return {
        "path_length": len(actions or []),
        "cost": paid,
        "cost_matches": cost is None or paid == cost,
        "foundations": len(end.foundations),
        "face_down": sum(len(col.face_down) for col in end.columns),
        "stock_rows": len(end.stock) // 10,
        "solved": end.is_solved(),
        "longest_run": prox["longest_exposed_same_suit_run"],
        "adjacencies": prox["exposed_same_suit_adjacencies"],
        "blocks": prox["movable_same_suit_blocks"],
    }


def load_seed_keys() -> list[bytes]:
    if not V06_JSON.exists():
        return []
    data = json.loads(V06_JSON.read_text(encoding="utf-8"))
    hexes = []
    lineage = data.get("lineage") or {}
    for segment in lineage.get("segments") or []:
        for side in ("pre", "post"):
            value = (segment.get(side) or {}).get("key_hex")
            if value:
                hexes.append(value)
    for blob in (lineage.get("terminal"), data.get("stock_empty")):
        value = (blob or {}).get("key_hex")
        if value:
            hexes.append(value)
    out = []
    seen = set()
    for value in hexes:
        if value in seen:
            continue
        seen.add(value)
        out.append(bytes.fromhex(value))
    return out


def _pass_expanded(life: dict | None, pass_level: int) -> bool:
    if not life:
        return False
    slot = (life.get("passes") or {}).get(str(pass_level))
    return bool(slot and slot.get("expanded"))


def checkpoint_coverage(pda) -> dict:
    children = [] if pda is None else pda.checkpoint_children
    only0 = p1 = p2 = p3 = 0
    first_broader_band = {320: 0, 640: 0, 1280: 0}
    for child in children:
        life = child.get("wider_pass") or {}
        e0 = _pass_expanded(life, 0)
        e1 = _pass_expanded(life, 1)
        e2 = _pass_expanded(life, 2)
        e3 = _pass_expanded(life, 3)
        if e0 and not (e1 or e2 or e3):
            only0 += 1
        if e1:
            p1 += 1
        if e2:
            p2 += 1
        if e3:
            p3 += 1
        for pass_level in (1, 2, 3):
            slot = (life.get("passes") or {}).get(str(pass_level)) or {}
            if slot.get("expanded"):
                band = None
                # first_expansion maps via reports later; store remaining as proxy
                break
    return {
        "total": len(children),
        "pass0_only": only0,
        "later_pass1": p1,
        "later_pass2": p2,
        "later_pass3": p3,
        "never_widened": sum(
            1
            for child in children
            if (child.get("wider_pass") or {}).get("suppression_reason") != "did_widen"
        ),
        "reopened_wider": sum(
            1
            for child in children
            if (child.get("wider_pass") or {}).get("suppression_reason") == "did_widen"
        ),
        "first_broader_band": first_broader_band,
    }


def first_broader_bands(pda, reports: list) -> dict:
    counts = {80: 0, 160: 0, 320: 0, 640: 0, 1280: 0}

    def band_for(expansion: int | None) -> int | None:
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

    if pda is None:
        return counts
    for child in pda.checkpoint_children:
        life = child.get("wider_pass") or {}
        for pass_level in (1, 2, 3):
            slot = (life.get("passes") or {}).get(str(pass_level)) or {}
            if slot.get("expanded"):
                band = band_for(slot.get("first_expansion"))
                if band in counts:
                    counts[band] += 1
                break
    return counts


def seeded_lifecycle(pda, seed_keys: list[bytes]) -> list[dict]:
    rows = []
    if pda is None:
        return rows
    for key in seed_keys:
        life = pda._pass_lifecycle(key, None, [], "node limit", 3)
        rows.append(
            {
                "key_hex": key.hex(),
                "seen": life.get("seen"),
                "first_pass": life.get("first_pass"),
                "suppression_reason": life.get("suppression_reason"),
                "passes": {
                    str(index): None
                    if not (life.get("passes") or {}).get(str(index))
                    else {
                        "expanded": (life["passes"][str(index)] or {}).get("expanded"),
                        "first_expansion": (life["passes"][str(index)] or {}).get(
                            "first_expansion"
                        ),
                        "remaining": (life["passes"][str(index)] or {}).get("remaining"),
                        "tt_status": (life["passes"][str(index)] or {}).get("tt_status"),
                    }
                    for index in range(4)
                },
            }
        )
    return rows


def compact(opening: SpiderState, result, arm: str, seed_keys: list[bytes]) -> dict:
    pda = result.post_deal_audit
    stats = result.stats
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
    coverage = checkpoint_coverage(pda)
    coverage["first_broader_band"] = first_broader_bands(pda, stats.band_pass_reports)
    empty = None if pda is None else pda.stock_empty_best
    b_children = [] if pda is None else list(pda.empty_pass_b_children)
    if pda is not None:
        for child in b_children:
            key = bytes.fromhex(child["child_key_hex"])
            finishes = pda.frame_finishes.get(key) or []
            child["descendant_expansions"] = (
                None if not finishes else finishes[0].get("descendant_expansions")
            )
            child["productive"] = bool(
                (child.get("descendant_expansions") or 0) > 0
                or (child.get("fd") is not None and empty and child["fd"] < empty.get("fd", 99))
            )
    schedule = []
    for report in stats.band_pass_reports:
        schedule.append(
            {
                "band": report.get("band"),
                "pass": report.get("pass"),
                "scheduled": report.get("scheduled", not report.get("skipped")),
                "skipped": report.get("skipped"),
                "saturation_inherited": report.get("saturation_inherited"),
                "saturation_triggered": report.get("saturation_triggered"),
                "expanded": report.get("expanded"),
                "unique_new": report.get("unique_new"),
                "tt_hits": report.get("tt_hits"),
                "depth_prunes": report.get("depth_prunes"),
                "reopens": report.get("reopens"),
                "stop": report.get("stop"),
                "budget_redirected": report.get("budget_redirected"),
            }
        )
    return {
        "arm": arm,
        "band_local": bool(stats.band_local_saturation),
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
        "slices_skipped": stats.slices_skipped,
        "saturated_passes": list(stats.saturated_passes),
        "saturated_band_passes": list(stats.saturated_band_passes),
        "probe_fires": list(stats.probe_fires),
        "probe_entered": list(stats.probe_entered),
        "first_foundation_node": stats.first_foundation_node,
        "first_foundation_depth": stats.first_foundation_depth,
        "first_foundation_pass": stats.first_foundation_pass,
        "stop_reason": result.stop_reason,
        "replay_ok": result.replay_ok,
        "fd_by_stock": fd_by_stock,
        "schedule": schedule,
        "checkpoint_coverage": coverage,
        "lineage": None if pda is None else compact_lineage_for_json(pda.lineage),
        "stock_empty": None
        if empty is None
        else {
            "key_hex": empty.get("key_hex"),
            "fd": empty.get("fd"),
            "pass": empty.get("pass"),
            "depth": empty.get("depth"),
            "expansion": empty.get("expansion"),
            "fu": empty.get("fu"),
            "empties": empty.get("empties"),
            "foundations": empty.get("foundations"),
            "census": empty.get("census"),
            "proximity": empty.get("proximity"),
            "wider_pass": empty.get("wider_pass"),
        },
        "seeded_lifecycle": seeded_lifecycle(pda, seed_keys),
        "empty_tier_b_children": b_children,
        "foundation_replay": _replay(
            opening, result.first_foundation_actions, result.foundation_cost
        )
        if result.first_foundation_actions
        else None,
    }


def run_arm(
    name: str,
    opening: SpiderState,
    *,
    band_local: bool,
    seed_keys: list[bytes],
    max_nodes: int,
    time_limit: float,
) -> dict:
    print(
        f"START {name} band_local={band_local} probe=1 nodes={max_nodes}",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        opening,
        max_nodes=max_nodes,
        time_limit_s=time_limit,
        target_foundations=8,
        max_pass=3,
        prep_ply=1,
        depth_bands=DEFAULT_DEPTH_BANDS,
        enable_saturation=True,
        enable_audit=True,
        enable_best_reveal_deal_probe=True,
        enable_post_deal_audit=True,
        enable_band_local_saturation=band_local,
        audit_watch_keys=seed_keys,
    )
    payload = compact(opening, result, name, seed_keys)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {name} nodes={payload['nodes']} unique={payload['unique']} "
        f"fd0={payload['fd_by_stock'][0]['face_down']} "
        f"fd5={payload['fd_by_stock'][5]['face_down']} "
        f"fnd={payload['max_foundations']} skipped={payload['slices_skipped']} "
        f"sps={payload['states_per_sec']:.1f}",
        flush=True,
    )
    if result.solved and result.replay_ok:
        SOLUTION.write_text(
            format_moves_text(
                result.actions,
                header=(
                    f"# v0.7 {name} 4925153\n"
                    f"# primitive_moves: {len(result.actions)}\n"
                    f"# mobilityware_moves: {result.cost}\n"
                ),
            ),
            encoding="utf-8",
        )
        payload["solution_path"] = str(SOLUTION.relative_to(ROOT)).replace("\\", "/")
    return payload


def _schedule_row(payload: dict, band: int, pass_level: int) -> dict | None:
    for row in payload.get("schedule") or []:
        if row.get("band") == band and row.get("pass") == pass_level:
            return row
    return None


def seeded_widened(payload: dict) -> bool:
    for row in payload.get("seeded_lifecycle") or []:
        passes = row.get("passes") or {}
        for index in (1, 2, 3):
            slot = passes.get(str(index)) or {}
            if slot.get("expanded"):
                return True
    empty = payload.get("stock_empty") or {}
    life = empty.get("wider_pass") or {}
    for index in (1, 2, 3):
        slot = (life.get("passes") or {}).get(str(index)) or {}
        if slot.get("expanded"):
            return True
    return False


def material_progress(control: dict, treat: dict) -> bool:
    if treat.get("max_foundations", 0) > control.get("max_foundations", 0):
        return True
    for dealt in range(6):
        cf = (control["fd_by_stock"][dealt] or {}).get("face_down")
        tf = (treat["fd_by_stock"][dealt] or {}).get("face_down")
        if tf is not None and cf is not None and tf < cf:
            return True
        if tf is not None and tf < 14:
            return True
    empty = treat.get("stock_empty") or {}
    prox = empty.get("proximity") or {}
    if (prox.get("longest_exposed_same_suit_run") or 0) >= 4:
        return True
    if (prox.get("movable_same_suit_blocks") or 0) >= 2:
        return True
    return False


def choose_verdict(control: dict, treat: dict) -> tuple[str, str]:
    if treat.get("solved") and treat.get("replay_ok"):
        return "SIMPLE_SOLVER_COMPLETE_SOLUTION", "treatment solved 4925153"
    if treat.get("max_foundations", 0) >= 1 and (
        treat.get("foundation_replay") or {}
    ).get("foundations", 0) >= 1:
        return (
            "BAND_LOCAL_SATURATION_REACHES_FOUNDATION",
            "replay-valid first foundation on band-local arm",
        )
    row320 = _schedule_row(treat, 320, 1)
    control_skip = (_schedule_row(control, 320, 1) or {}).get("skipped")
    treat_ran = bool(row320 and row320.get("scheduled") and not row320.get("skipped"))
    cov = treat.get("checkpoint_coverage") or {}
    widened = int(cov.get("later_pass1") or 0) + int(cov.get("later_pass2") or 0) + int(
        cov.get("later_pass3") or 0
    )
    seeded = seeded_widened(treat)
    b_kids = treat.get("empty_tier_b_children") or []
    b_expanded = sum(1 for child in b_kids if child.get("expanded"))
    unique_drop = treat["unique"] < int(control["unique"] * 0.7)
    treat_p0 = _schedule_row(treat, 320, 0) or {}
    control_p0 = _schedule_row(control, 320, 0) or {}
    reopen_starvation = (
        int(treat_p0.get("unique_new") or 0) == 0
        and int(control_p0.get("unique_new") or 0) > 0
        and int(treat_p0.get("reopens") or 0) >= int(treat_p0.get("expanded") or 0) * 0.9
    )
    if treat_ran and (unique_drop or reopen_starvation) and not seeded and widened == 0:
        return (
            "BAND_LOCAL_SATURATION_CAUSES_STATE_EXPLOSION",
            "deeper-band slices spent their budget reopening shallower coverage and never generated the fd-14 coupled states",
        )
    if treat_ran and (seeded or widened > 0 or b_expanded > 0):
        if material_progress(control, treat):
            return (
                "BAND_LOCAL_SATURATION_RESTORES_WIDER_COVERAGE",
                "coupled/checkpoint states received Pass 1+ and made structural progress",
            )
        return (
            "WIDER_COVERAGE_RESTORED_BUT_UNPRODUCTIVE",
            "Pass 1+ reached the target states but fd/run/foundation did not improve",
        )
    if treat_ran and not seeded and widened == 0:
        return (
            "CROSS_BAND_SATURATION_NOT_CAUSAL",
            "band 320 Pass 1 ran but coupled/checkpoint states were still not expanded at Pass 1+",
        )
    if control_skip and not treat_ran:
        return "INCONCLUSIVE", "treatment did not schedule band 320 Pass 1"
    return (
        "CROSS_BAND_SATURATION_NOT_CAUSAL",
        "changing saturation scope did not materially change wider coverage",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return "Keep band-local saturation and the probe; do not fold this solver into the controller."
    if verdict == "BAND_LOCAL_SATURATION_REACHES_FOUNDATION":
        return (
            "Keep band-local saturation. Next: continue from the replay-valid first "
            "foundation without adding Deal preparation."
        )
    if verdict == "BAND_LOCAL_SATURATION_RESTORES_WIDER_COVERAGE":
        return (
            "Keep band-local saturation. Next: measure whether Pass 1 continuation "
            "from the fd-14 stock-empty state can assemble a same-suit run; still "
            "no foundation heuristic."
        )
    if verdict == "WIDER_COVERAGE_RESTORED_BUT_UNPRODUCTIVE":
        return (
            "Keep band-local saturation. Do not add Pass 2 service automatically. "
            "Next: diagnose why the newly explored Tier-B children of the fd-14 "
            "stock-empty state do not extend same-suit runs."
        )
    if verdict == "CROSS_BAND_SATURATION_NOT_CAUSAL":
        return (
            "Keep band-local saturation as the correct scheduling contract. Next: "
            "the remaining blocker is reaching the Deal-D coupled path under Pass 1; "
            "do not add Deal preparation in the next step without a new causal test."
        )
    if verdict == "BAND_LOCAL_SATURATION_CAUSES_STATE_EXPLOSION":
        return (
            "Keep band-local saturation as the correct contract and keep the probe. "
            "Do not restore cross-band saturation. Next: stop deeper-band slices "
            "from spending their node budget reopening shallower remaining-depth "
            "coverage before they can generate the fd-14 coupled states."
        )
    return "Reproduce band 320 Pass 1 scheduling before another treatment."


def interpret(control: dict, treat: dict, verdict: str) -> str:
    c320 = _schedule_row(control, 320, 1) or {}
    t320 = _schedule_row(treat, 320, 1) or {}
    empty = treat.get("stock_empty") or {}
    b_kids = treat.get("empty_tier_b_children") or []
    return (
        f"Control band 320 Pass 1 skipped={c320.get('skipped')} inherited="
        f"{c320.get('saturation_inherited')} expanded={c320.get('expanded')}. "
        f"Treatment band 320 Pass 1 scheduled={t320.get('scheduled')} skipped="
        f"{t320.get('skipped')} inherited={t320.get('saturation_inherited')} "
        f"expanded={t320.get('expanded')} unique_new={t320.get('unique_new')} "
        f"reopens={t320.get('reopens')}. "
        f"Checkpoint later Pass 1/2/3 control="
        f"{(control.get('checkpoint_coverage') or {}).get('later_pass1')}/"
        f"{(control.get('checkpoint_coverage') or {}).get('later_pass2')}/"
        f"{(control.get('checkpoint_coverage') or {}).get('later_pass3')} "
        f"treatment="
        f"{(treat.get('checkpoint_coverage') or {}).get('later_pass1')}/"
        f"{(treat.get('checkpoint_coverage') or {}).get('later_pass2')}/"
        f"{(treat.get('checkpoint_coverage') or {}).get('later_pass3')}. "
        f"Seeded coupled states widened={seeded_widened(treat)}. "
        f"Stock-empty fd={empty.get('fd')} pass={empty.get('pass')} "
        f"A/B/C/D={(empty.get('census') or {}).get('tableau_a')}/"
        f"{(empty.get('census') or {}).get('tableau_b')}/"
        f"{(empty.get('census') or {}).get('tableau_c')}/"
        f"{(empty.get('census') or {}).get('tableau_d')} "
        f"Tier-B children recorded={len(b_kids)} expanded="
        f"{sum(1 for child in b_kids if child.get('expanded'))}. "
        f"Max foundations control={control.get('max_foundations')} "
        f"treatment={treat.get('max_foundations')}. Verdict {verdict}."
    )


def _fmt(value) -> str:
    if value is None:
        return "—"
    return str(value)


def write_report(payload: dict) -> None:
    a = payload["control"]
    b = payload["treatment"]
    lines = [
        "# Simple Progressive Search v0.7: Band-Local Saturation",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload['note']}.",
        "",
        "## 2. Saturation contract before/after",
        "",
        "Before (control, v0.3–v0.6): a pass with `unique_new=0` is saturated",
        "globally. Later depth bands skip that pass.",
        "",
        "After (treatment): saturation is keyed by `(depth_band, pass)`. A zero-novel",
        "slice at band 160 Pass 1 saturates only that cell. Band 320 Pass 1 is",
        "schedulable again. Depth-aware TT is not cleared.",
        "",
        f"Control slices skipped={a.get('slices_skipped')} saturated_passes={a.get('saturated_passes')}.",
        f"Treatment slices skipped={b.get('slices_skipped')} saturated_band_passes={b.get('saturated_band_passes')}.",
        "",
        "## 3. Control reproduction",
        "",
        f"- nodes={a['nodes']} unique={a['unique']} deals={a['deals_executed']} "
        f"fnd={a['max_foundations']} stop={a['stop_reason']}.",
        f"- Best FD by deals: "
        + ", ".join(
            f"{cell['deals_completed']}={cell['face_down']}" for cell in a["fd_by_stock"]
        )
        + ".",
        f"- Band 320 Pass 1: {_schedule_row(a, 320, 1)}.",
        f"- Checkpoint later Pass 1/2/3: {(a.get('checkpoint_coverage') or {}).get('later_pass1')}/"
        f"{(a.get('checkpoint_coverage') or {}).get('later_pass2')}/"
        f"{(a.get('checkpoint_coverage') or {}).get('later_pass3')}.",
        "",
        "## 4. Band/pass scheduling",
        "",
        "| Band | Pass | Control scheduled | Treatment scheduled | Control unique_new | Treatment unique_new | Treatment inherited |",
        "| ---: | ---: | --- | --- | ---: | ---: | --- |",
    ]
    seen = []
    for row in b.get("schedule") or []:
        seen.append((row["band"], row["pass"]))
        cr = _schedule_row(a, row["band"], row["pass"]) or {}
        lines.append(
            f"| {row['band']} | {row['pass']} | {_fmt(not cr.get('skipped') if cr else None)} | "
            f"{row.get('scheduled')} | {_fmt(cr.get('unique_new'))} | {row.get('unique_new')} | "
            f"{row.get('saturation_inherited')} |"
        )
    lines.extend(
        [
            "",
            "## 5. TT interaction",
            "",
            f"- Control TT hits={a['tt_hits']} prunes={a['tt_prunes']} reopens={a['tt_reopens']}.",
            f"- Treatment TT hits={b['tt_hits']} prunes={b['tt_prunes']} reopens={b['tt_reopens']}.",
            "- Treatment does not clear TT. Deeper remaining-depth still reopens; equal or",
            "  shallower remaining-depth is still pruned.",
            "",
            "## 6. Checkpoint wider coverage",
            "",
            "| | Control | Treatment |",
            "| --- | ---: | ---: |",
            f"| Checkpoint children | {(a.get('checkpoint_coverage') or {}).get('total')} | {(b.get('checkpoint_coverage') or {}).get('total')} |",
            f"| Pass 0 only | {(a.get('checkpoint_coverage') or {}).get('pass0_only')} | {(b.get('checkpoint_coverage') or {}).get('pass0_only')} |",
            f"| Later Pass 1 | {(a.get('checkpoint_coverage') or {}).get('later_pass1')} | {(b.get('checkpoint_coverage') or {}).get('later_pass1')} |",
            f"| Later Pass 2 | {(a.get('checkpoint_coverage') or {}).get('later_pass2')} | {(b.get('checkpoint_coverage') or {}).get('later_pass2')} |",
            f"| Later Pass 3 | {(a.get('checkpoint_coverage') or {}).get('later_pass3')} | {(b.get('checkpoint_coverage') or {}).get('later_pass3')} |",
            f"| First broader @320 | {(a.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(320)} | {(b.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(320)} |",
            f"| First broader @640 | {(a.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(640)} | {(b.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(640)} |",
            f"| First broader @1280 | {(a.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(1280)} | {(b.get('checkpoint_coverage') or {}).get('first_broader_band', {}).get(1280)} |",
            "",
            "## 7. fd-14 stock-empty lifecycle",
            "",
        ]
    )
    empty = b.get("stock_empty") or {}
    census = empty.get("census") or {}
    prox = empty.get("proximity") or {}
    life = empty.get("wider_pass") or {}
    lines.extend(
        [
            f"- digest `{_fmt(empty.get('key_hex'))}`",
            f"- fd={_fmt(empty.get('fd'))} depth={_fmt(empty.get('depth'))} pass={_fmt(empty.get('pass'))}",
            f"- A/B/C/D={_fmt(census.get('tableau_a'))}/{_fmt(census.get('tableau_b'))}/"
            f"{_fmt(census.get('tableau_c'))}/{_fmt(census.get('tableau_d'))}",
            f"- longest run={_fmt(prox.get('longest_exposed_same_suit_run'))} "
            f"adjacencies={_fmt(prox.get('exposed_same_suit_adjacencies'))} "
            f"foundations={_fmt(empty.get('foundations'))}",
            f"- Pass 1/2/3 expanded: {_pass_expanded(life, 1)}/{_pass_expanded(life, 2)}/{_pass_expanded(life, 3)}",
            f"- suppression: {life.get('suppression_reason')} ({life.get('suppression_detail')})",
            f"- v0.6 fd-14 coupled keys seen in treatment: "
            f"{sum(1 for row in b.get('seeded_lifecycle') or [] if row.get('seen'))}/"
            f"{len(b.get('seeded_lifecycle') or [])}.",
            "",
            "Tier-B children from stock-empty at Pass 1+:",
            "",
        ]
    )
    kids = b.get("empty_tier_b_children") or []
    if not kids:
        lines.append("- none recorded.")
    else:
        lines.append("| Action | Novel | TT-covered | Expanded | Descendants | Productive |")
        lines.append("| --- | --- | --- | --- | ---: | --- |")
        for child in kids:
            lines.append(
                f"| {child.get('action')} | {child.get('novel')} | {child.get('tt_covered')} | "
                f"{child.get('expanded')} | {_fmt(child.get('descendant_expansions'))} | "
                f"{child.get('productive')} |"
            )
    lines.extend(
        [
            "",
            "## 8. Coupled progress",
            "",
            "| Deals completed | Best FD control | Best FD treatment | Fnd control | Fnd treatment |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for dealt in range(6):
        ca = a["fd_by_stock"][dealt]
        tb = b["fd_by_stock"][dealt]
        lines.append(
            f"| {dealt} | {_fmt(ca.get('face_down'))} | {_fmt(tb.get('face_down'))} | "
            f"{_fmt(ca.get('foundations'))} | {_fmt(tb.get('foundations'))} |"
        )
    fr = b.get("foundation_replay")
    lines.extend(
        [
            "",
            "## 9. Foundation result",
            "",
            f"Control foundations={a['max_foundations']}; treatment={b['max_foundations']}; "
            f"first treatment node={b.get('first_foundation_node')}.",
        ]
    )
    if fr and fr.get("foundations", 0) >= 1:
        lines.append(
            f"Replay-valid foundation path length={fr.get('path_length')} cost={fr.get('cost')} "
            f"fd={fr.get('face_down')} stock={fr.get('stock_rows')}."
        )
    else:
        lines.append("No replay-valid foundation.")
    extra = payload.get("treatment_3m")
    lines.extend(
        [
            "",
            "## 10. Complete solution result",
            "",
            "Yes." if b.get("solved") and b.get("replay_ok") else "No complete solution.",
            "",
            "## 11. Runtime/coverage trade-off",
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
            f"| Deals | {a['deals_executed']} | {b['deals_executed']} |",
            f"| RSS MiB | {a['peak_rss_mb']} | {b['peak_rss_mb']} |",
            f"| Time s | {a['elapsed_s']:.1f} | {b['elapsed_s']:.1f} |",
            "",
        ]
    )
    if extra:
        lines.append(
            f"Optional 3M treatment: nodes={extra.get('nodes')} unique={extra.get('unique')} "
            f"fd5={extra['fd_by_stock'][5]['face_down']} fnd={extra.get('max_foundations')} "
            f"later_pass1={(extra.get('checkpoint_coverage') or {}).get('later_pass1')}."
        )
        lines.append("")
    lines.extend(
        [
            "## 12. Exactly one next recommendation",
            "",
            payload["next_recommendation"],
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Probe ON both arms. Band-local saturation default OFF. Engine",
            "`enumerate_legal_actions` / `can_deal(MW_RULES)` remain the Deal authority.",
            "No post-Deal service, Deal preparation, or foundation heuristic was added.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def should_run_3m(control: dict, treat: dict, verdict: str) -> bool:
    if verdict in (
        "INCONCLUSIVE",
        "CROSS_BAND_SATURATION_NOT_CAUSAL",
        "BAND_LOCAL_SATURATION_CAUSES_STATE_EXPLOSION",
    ):
        return False
    if not seeded_widened(treat) and int(
        (treat.get("checkpoint_coverage") or {}).get("later_pass1") or 0
    ) == 0:
        return False
    if not material_progress(control, treat) and not (treat.get("empty_tier_b_children") or []):
        return False
    return True


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--reclassify":
        payload = json.loads(RESULT.read_text(encoding="utf-8"))
        control = payload["control"]
        treat = payload["treatment"]
        extra = payload.get("treatment_3m")
        source = extra or treat
        verdict, note = choose_verdict(control, source)
        payload["verdict"] = verdict
        payload["note"] = note
        payload["interpretation"] = interpret(control, source, verdict)
        payload["next_recommendation"] = next_recommendation(verdict)
        _write_json(RESULT, payload)
        write_report(payload)
        print(f"VERDICT {verdict}", flush=True)
        print(f"WROTE {RESULT}", flush=True)
        print(f"WROTE {REPORT}", flush=True)
        return 0
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    seed_keys = load_seed_keys()
    print(f"SEEDED_KEYS {len(seed_keys)}", flush=True)
    control = run_arm(
        "CONTROL",
        opening,
        band_local=False,
        seed_keys=seed_keys,
        max_nodes=PRIMARY_NODES,
        time_limit=TIME_LIMIT,
    )
    _write_json(CHECKPOINTS / "CONTROL.json", control)
    treat = run_arm(
        "BAND_LOCAL",
        opening,
        band_local=True,
        seed_keys=seed_keys,
        max_nodes=PRIMARY_NODES,
        time_limit=TIME_LIMIT,
    )
    _write_json(CHECKPOINTS / "BAND_LOCAL.json", treat)
    verdict, note = choose_verdict(control, treat)
    extra = None
    if should_run_3m(control, treat, verdict):
        extra = run_arm(
            "BAND_LOCAL_3M",
            opening,
            band_local=True,
            seed_keys=seed_keys,
            max_nodes=OPTIONAL_3M,
            time_limit=TIME_LIMIT_3M,
        )
        _write_json(CHECKPOINTS / "BAND_LOCAL_3M.json", extra)
        verdict, note = choose_verdict(control, extra)
        treat_for_verdict = extra
    else:
        treat_for_verdict = treat
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "control": control,
        "treatment": treat,
        "treatment_3m": extra,
        "verdict": verdict,
        "note": note,
        "interpretation": interpret(control, treat_for_verdict, verdict),
        "next_recommendation": next_recommendation(verdict),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
