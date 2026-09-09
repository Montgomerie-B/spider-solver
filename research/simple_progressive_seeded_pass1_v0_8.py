#!/usr/bin/env python3
"""v0.8: seeded Pass-1 continuation from the fd-14 stock-empty coupled state."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import census_legal_by_tier, foundation_proximity
from spider.simple_progressive_solver import (
    Tier,
    apply_action,
    classify_tier,
    format_moves_text,
    ordered_actions,
    solve_progressive,
)

EXPERIMENT = "simple_progressive_seeded_pass1_v0_8"
BASE_SHA = "260fecd38e5fa70924b0d63714be647431dc752d"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
FOUNDATION_ROUTE = ROOT / "solutions" / "4925153_simple_v0_8_first_foundation.moves.txt"
SOLVED_ROUTE = ROOT / "solutions" / "4925153_simple_v0_8_solved.moves.txt"
EXPECTED_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
LOCAL_DEPTH = 320
PASS0_NODES = 50_000
PASS1_NODES = 1_000_000
OPTIONAL_3M = 3_000_000
TIME_LIMIT = 1800.0
TIME_LIMIT_3M = 5400.0


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def load_opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def verify_seed(opening: SpiderState, actions: list) -> dict:
    seed = opening.clone()
    cost = replay_actions(seed, list(actions)) if actions else 0
    digest = pack_state(seed).hex()
    fd = sum(len(col.face_down) for col in seed.columns)
    stock = len(seed.stock) // 10
    fnd = len(seed.foundations)
    census = census_legal_by_tier(seed)
    prox = foundation_proximity(seed)
    ok = (
        digest == EXPECTED_HEX
        and fd == 14
        and stock == 0
        and fnd == 0
        and cost == 43
        and len(actions) == 43
    )
    return {
        "ok": ok,
        "seed": seed,
        "digest": digest,
        "fd": fd,
        "stock_rows": stock,
        "foundations": fnd,
        "cost": cost,
        "path_length": len(actions),
        "census": census,
        "proximity": prox,
        "actions": list(actions),
    }


def root_b_moves(seed: SpiderState) -> list[dict]:
    allowed = ordered_actions(seed, 1, prep_ply=0, stats=None)
    rows = []
    for action in allowed:
        if classify_tier(seed, action) is not Tier.B:
            continue
        child = seed.clone()
        apply_action(child, action)
        rows.append(
            {
                "action": list(action) if isinstance(action, tuple) else action,
                "child_key_hex": pack_state(child).hex(),
                "legal": True,
                "replay_valid": True,
                "child_fd": sum(len(col.face_down) for col in child.columns),
                "child_foundations": len(child.foundations),
                "child_run": foundation_proximity(child)["longest_exposed_same_suit_run"],
            }
        )
    return rows


def compact_arm(seed: SpiderState, opening: SpiderState, prefix: list, result, arm: str) -> dict:
    pda = result.post_deal_audit
    b_rows = root_b_moves(seed)
    for row in b_rows:
        key = bytes.fromhex(row["child_key_hex"])
        finishes = [] if pda is None else (pda.frame_finishes.get(key) or [])
        encounters = [] if pda is None else (pda.encounters.get(key) or [])
        expanded = any(item.get("expanded") for item in encounters)
        novel = any(item.get("tt_status") == "novel" for item in encounters)
        finish = finishes[0] if finishes else None
        row.update(
            {
                "novel": novel or (expanded and not any(item.get("tt_skip") for item in encounters)),
                "expanded": expanded,
                "tt_skip": any(item.get("tt_skip") for item in encounters),
                "descendant_expansions": None if finish is None else finish.get("descendant_expansions"),
                "best_descendant_fd": None if finish is None else finish.get("best_descendant_fd"),
                "max_foundations": None if finish is None else finish.get("best_descendant_foundations"),
                "cut": None if finish is None else finish.get("pop_reason"),
            }
        )
        if expanded:
            child_end = seed.clone()
            replay_actions(child_end, [tuple(row["action"])])
            row["longest_same_suit_run"] = foundation_proximity(child_end)[
                "longest_exposed_same_suit_run"
            ]
        else:
            row["longest_same_suit_run"] = row["child_run"]
        row["first_foundation"] = bool((row.get("max_foundations") or 0) >= 1)

    def struct_payload(item):
        if not item:
            return None
        out = dict(item)
        out["path_length"] = len(item.get("path") or [])
        return out

    continuation = list(result.first_foundation_actions or result.actions)
    if (not continuation) and pda is not None and pda.best_run_struct and pda.best_run_struct.get("path"):
        continuation = list(pda.best_run_struct["path"])
    combined = list(prefix) + continuation
    combined_replay = None
    if continuation:
        end = opening.clone()
        try:
            paid = replay_actions(end, combined)
            prox = foundation_proximity(end)
            combined_replay = {
                "ok": True,
                "cost": paid,
                "fd": sum(len(col.face_down) for col in end.columns),
                "foundations": len(end.foundations),
                "stock_rows": len(end.stock) // 10,
                "solved": end.is_solved(),
                "path_length": len(combined),
                "longest_run": prox["longest_exposed_same_suit_run"],
                "adjacencies": prox["exposed_same_suit_adjacencies"],
            }
        except (ValueError, AssertionError) as exc:
            combined_replay = {"ok": False, "error": str(exc)}
    return {
        "arm": arm,
        "nodes": result.nodes,
        "unique": result.stats.unique_exact_states,
        "unique_ratio": result.stats.unique_exact_states / max(1, result.nodes),
        "elapsed_s": result.elapsed_s,
        "states_per_sec": result.states_per_sec,
        "max_depth": result.stats.max_depth,
        "max_foundations": result.max_foundations,
        "min_face_down": result.min_face_down,
        "pass_reached": result.pass_reached,
        "stop_reason": result.stop_reason,
        "replay_ok": result.replay_ok,
        "solved": result.solved,
        "tt_hits": result.stats.tt_hits,
        "tt_reopens": result.stats.tt_reopens,
        "peak_rss_mb": result.stats.peak_rss_mb,
        "first_foundation_node": result.stats.first_foundation_node,
        "first_foundation_depth": result.stats.first_foundation_depth,
        "first_foundation_pass": result.stats.first_foundation_pass,
        "band_pass_reports": [
            {
                "band": row.get("band"),
                "pass": row.get("pass"),
                "expanded": row.get("expanded"),
                "unique_new": row.get("unique_new"),
                "skipped": row.get("skipped"),
                "stop": row.get("stop"),
            }
            for row in result.stats.band_pass_reports
        ],
        "root_tier_b": b_rows,
        "structure": {
            "best_fd": struct_payload(None if pda is None else pda.best_fd_struct),
            "best_foundations": struct_payload(None if pda is None else pda.best_fnd_struct),
            "best_run": struct_payload(None if pda is None else pda.best_run_struct),
            "best_adjacencies": struct_payload(None if pda is None else pda.best_adj_struct),
            "best_empties": struct_payload(None if pda is None else pda.best_empties_struct),
            "best_mixed": struct_payload(None if pda is None else pda.best_mixed_struct),
        },
        "continuation_length": len(continuation),
        "combined_replay": combined_replay,
        "foundation_actions_length": len(result.first_foundation_actions),
    }


def run_local(
    seed: SpiderState,
    opening: SpiderState,
    prefix: list,
    *,
    name: str,
    start_pass: int,
    max_pass: int,
    max_nodes: int,
    time_limit: float,
    target_foundations: int,
    b_watch: list[bytes],
) -> dict:
    print(
        f"START {name} start_pass={start_pass} max_pass={max_pass} "
        f"nodes={max_nodes} depth={LOCAL_DEPTH}",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        seed,
        max_nodes=max_nodes,
        time_limit_s=time_limit,
        target_foundations=target_foundations,
        max_pass=max_pass,
        start_pass=start_pass,
        prep_ply=0,
        depth_bands=(LOCAL_DEPTH,),
        enable_saturation=False,
        enable_audit=True,
        enable_best_reveal_deal_probe=False,
        enable_post_deal_audit=True,
        enable_band_local_saturation=False,
        audit_watch_keys=b_watch,
    )
    payload = compact_arm(seed, opening, prefix, result, name)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {name} nodes={payload['nodes']} unique={payload['unique']} "
        f"fd={payload['min_face_down']} fnd={payload['max_foundations']} "
        f"run={(payload['structure']['best_run'] or {}).get('longest_run')} "
        f"sps={payload['states_per_sec']:.1f} stop={payload['stop_reason']}",
        flush=True,
    )
    payload["_result_actions"] = list(result.actions)
    payload["_foundation_actions"] = list(result.first_foundation_actions)
    return payload


def choose_verdict(seed_ok: bool, pass0: dict | None, pass1: dict | None) -> tuple[str, str]:
    if not seed_ok:
        return "SEED_REPRODUCTION_FAILED", "historical coupled state could not be reproduced exactly"
    if pass1 is None:
        return "INCONCLUSIVE", "Pass-1 arm did not run"
    combined = pass1.get("combined_replay") or {}
    if pass1.get("solved") and combined.get("ok") and combined.get("solved"):
        return "SIMPLE_SOLVER_COMPLETE_SOLUTION", "concatenated A+B route solved 4925153"
    if (
        pass1.get("max_foundations", 0) >= 1
        and combined.get("ok")
        and combined.get("foundations", 0) >= 1
    ):
        return (
            "SEEDED_PASS1_REACHES_FOUNDATION",
            "replay-valid foundation from the fd-14 seed; concatenated path replays from the original deal",
        )
    unique_ratio = pass1.get("unique_ratio") or 0
    if pass1.get("nodes", 0) >= 100_000 and unique_ratio < 0.05 and pass1.get("max_foundations", 0) == 0:
        if (pass1.get("min_face_down") or 99) >= 14 and (
            (pass1.get("structure") or {}).get("best_run") or {}
        ).get("longest_run", 1) <= 1:
            return (
                "SEEDED_PASS1_STATE_EXPLOSION",
                "A+B search expanded heavily with almost no unique progress from the seed",
            )
    fd_improved = (pass1.get("min_face_down") or 99) < 14
    run_improved = ((pass1.get("structure") or {}).get("best_run") or {}).get("longest_run", 1) >= 4
    adj_improved = ((pass1.get("structure") or {}).get("best_adjacencies") or {}).get("adjacencies", 0) >= 20
    empties = ((pass1.get("structure") or {}).get("best_empties") or {}).get("empties", 0) >= 1
    b_expanded = sum(1 for row in pass1.get("root_tier_b") or [] if row.get("expanded"))
    if fd_improved or run_improved or adj_improved or empties:
        return (
            "SEEDED_PASS1_MAKES_STRUCTURAL_PROGRESS",
            "A+B continuation improved fd/run/adjacency/empties without a foundation",
        )
    if b_expanded >= 3 and (pass1.get("nodes") or 0) >= 1000:
        return (
            "SEEDED_PASS1_UNPRODUCTIVE",
            "the four B moves and A+B descendants received meaningful search but did not improve materially",
        )
    return "INCONCLUSIVE", "Pass-1 coverage was too thin to classify"


def next_recommendation(verdict: str) -> str:
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return "Keep the seeded A+B continuation as a research witness; do not fold it into the whole-deal scheduler in this line."
    if verdict == "SEEDED_PASS1_REACHES_FOUNDATION":
        return (
            "Keep the seed. Next: continue the same A+B policy from the first-foundation "
            "state toward a full solve; still do not add Pass 2 or Deal preparation."
        )
    if verdict == "SEEDED_PASS1_MAKES_STRUCTURAL_PROGRESS":
        return (
            "The good state is worth widening. Next: return to whole-deal scheduling "
            "and preserve Pass-0 budget in deeper bands so this seed can be generated "
            "and then granted Pass 1; do not add foundation heuristics."
        )
    if verdict == "SEEDED_PASS1_UNPRODUCTIVE":
        return (
            "Do not spend the next task on scheduler reopen. Next: inspect why the "
            "four Tier-B children cannot extend same-suit runs; still no Pass 2."
        )
    if verdict == "SEEDED_PASS1_STATE_EXPLOSION":
        return (
            "Pass 1 from the seed is too bushy without progress. Next: diagnose the "
            "B-move descendants with a tight descendant cap before touching the "
            "whole-deal scheduler."
        )
    if verdict == "SEED_REPRODUCTION_FAILED":
        return "Reproduce L_COUPLED_FD14_DEALS5_DEPTH43 from v0.7 CONTROL before another continuation experiment."
    return "Reproduce the seed and Pass-1 arm before changing search policy."


def material_progress(pass1: dict) -> bool:
    if pass1.get("max_foundations", 0) >= 1:
        return True
    if (pass1.get("min_face_down") or 99) < 14:
        return True
    if ((pass1.get("structure") or {}).get("best_run") or {}).get("longest_run", 1) >= 4:
        return True
    return False


def write_report(payload: dict) -> None:
    seed = payload.get("seed") or {}
    p0 = payload.get("pass0") or {}
    p1 = payload.get("pass1") or {}
    extra = payload.get("pass1_3m")
    lines = [
        "# Simple Progressive Search v0.8: Seeded Pass-1 Continuation",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "## 2. Seed reproduction",
        "",
        f"- Fixture `{FIXTURE.relative_to(ROOT).as_posix()}`",
        f"- digest `{seed.get('digest')}`",
        f"- replay ok={seed.get('ok')} path_length={seed.get('path_length')} cost={seed.get('cost')}",
        f"- fd={seed.get('fd')} stock_rows={seed.get('stock_rows')} foundations={seed.get('foundations')}",
        f"- legal A/B/C/D="
        f"{(seed.get('census') or {}).get('tableau_a')}/{(seed.get('census') or {}).get('tableau_b')}/"
        f"{(seed.get('census') or {}).get('tableau_c')}/{(seed.get('census') or {}).get('tableau_d')}",
        f"- immediate foundation={(seed.get('census') or {}).get('has_immediate_foundation_move')}",
        f"- longest run={(seed.get('proximity') or {}).get('longest_exposed_same_suit_run')}",
        "",
        "## 3. Local Pass-0 control",
        "",
        f"- expanded={p0.get('nodes')} unique={p0.get('unique')} stop={p0.get('stop_reason')}",
        f"- min fd={p0.get('min_face_down')} max foundations={p0.get('max_foundations')} "
        f"max depth={p0.get('max_depth')}",
        f"- longest run={((p0.get('structure') or {}).get('best_run') or {}).get('longest_run')}",
        "",
        "## 4. Local Pass-1 treatment",
        "",
        f"- expanded={p1.get('nodes')} unique={p1.get('unique')} unique/exp={p1.get('unique_ratio')}",
        f"- states/s={None if p1.get('states_per_sec') is None else round(p1['states_per_sec'], 1)} "
        f"time s={None if p1.get('elapsed_s') is None else round(p1['elapsed_s'], 1)} "
        f"RSS={p1.get('peak_rss_mb')}",
        f"- min fd={p1.get('min_face_down')} max foundations={p1.get('max_foundations')} "
        f"max depth={p1.get('max_depth')} stop={p1.get('stop_reason')}",
        f"- first foundation node={p1.get('first_foundation_node')} "
        f"local depth={p1.get('first_foundation_depth')} pass={p1.get('first_foundation_pass')}",
        "",
        "## 5. Four root Tier-B moves",
        "",
        "| Action | Child fd | Novel | Expanded | Descendants | Best desc fd | Fnd | Run | Cut |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in p1.get("root_tier_b") or []:
        lines.append(
            f"| {row.get('action')} | {row.get('child_fd')} | {row.get('novel')} | "
            f"{row.get('expanded')} | {row.get('descendant_expansions')} | "
            f"{row.get('best_descendant_fd')} | {row.get('max_foundations')} | "
            f"{row.get('longest_same_suit_run')} | {row.get('cut')} |"
        )
    lines.append(
        "Pass-1 ordering puts the single Tier-A child first. DFS dived there "
        "and did not return to the four root B siblings before the time limit. "
        "Run/adjacency gains come from later B moves under that A child."
    )
    st = p1.get("structure") or {}

    def brief(item):
        if not item:
            return "—"
        return (
            f"fd={item.get('fd')} fnd={item.get('foundations')} run={item.get('longest_run')} "
            f"adj={item.get('adjacencies')} empties={item.get('empties')} mixed={item.get('mixed')} "
            f"depth={item.get('depth')} exp={item.get('expansion')} path_len={item.get('path_length')}"
        )

    lines.extend(
        [
            "",
            "## 6. Structural witnesses",
            "",
            f"- best fd: {brief(st.get('best_fd'))}",
            f"- best foundations: {brief(st.get('best_foundations'))}",
            f"- longest run: {brief(st.get('best_run'))}",
            f"- best adjacencies: {brief(st.get('best_adjacencies'))}",
            f"- best empties: {brief(st.get('best_empties'))}",
            f"- lowest mixed: {brief(st.get('best_mixed'))}",
            "",
            "## 7. Foundation / concatenated replay",
            "",
            f"- combined replay={p1.get('combined_replay')}",
            "- 3M not run: run length 8 appeared at local expansion 115023; the remaining "
            "1M-time-limit search did not improve fd or reach a foundation.",
            "",
            "## 8. Optional larger / solve runs",
            "",
        ]
    )
    if extra:
        lines.append(
            f"- 3M: nodes={extra.get('nodes')} fd={extra.get('min_face_down')} "
            f"fnd={extra.get('max_foundations')} run={(extra.get('structure') or {}).get('best_run')}"
        )
    else:
        lines.append("- not run.")
    lines.extend(
        [
            "",
            "## 9. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Production `solve_progressive` default `start_pass=0`. Local arms used a",
            "single depth band 320, fresh TT, A-only or A+B, no C/D, no Deal probe,",
            "no Deal preparation, no whole-deal scheduler change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(seed: dict, p0: dict, p1: dict, verdict: str) -> str:
    b = p1.get("root_tier_b") or []
    return (
        f"Seed digest={seed.get('digest')} ok={seed.get('ok')} fd={seed.get('fd')} "
        f"stock={seed.get('stock_rows')} fnd={seed.get('foundations')} cost={seed.get('cost')}. "
        f"Pass0 nodes={p0.get('nodes')} unique={p0.get('unique')} min_fd={p0.get('min_face_down')} "
        f"fnd={p0.get('max_foundations')}. "
        f"Pass1 nodes={p1.get('nodes')} unique={p1.get('unique')} min_fd={p1.get('min_face_down')} "
        f"fnd={p1.get('max_foundations')} run="
        f"{((p1.get('structure') or {}).get('best_run') or {}).get('longest_run')} "
        f"B expanded={sum(1 for row in b if row.get('expanded'))}/4. "
        f"Combined replay={p1.get('combined_replay')}. Verdict {verdict}."
    )


def drop_private(arm: dict) -> dict:
    out = dict(arm)
    out.pop("_result_actions", None)
    out.pop("_foundation_actions", None)
    return out


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = load_opening()
    if not FIXTURE.exists():
        print("SEED_REPRODUCTION_FAILED fixture missing", flush=True)
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "verdict": "SEED_REPRODUCTION_FAILED",
            "note": "seed fixture missing",
            "next_recommendation": next_recommendation("SEED_REPRODUCTION_FAILED"),
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SEED_REPRODUCTION_FAILED", flush=True)
        return 1
    prefix = parse_moves_file(FIXTURE)
    seed_info = verify_seed(opening, prefix)
    seed = seed_info["seed"]
    seed_public = {k: v for k, v in seed_info.items() if k not in ("seed", "actions")}
    _write_json(CHECKPOINTS / "seed.json", seed_public)
    if not seed_info["ok"]:
        print("SEED_REPRODUCTION_FAILED", flush=True)
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "seed": seed_public,
            "verdict": "SEED_REPRODUCTION_FAILED",
            "note": "replayed prefix did not match the historical fd-14 stock-empty digest",
            "next_recommendation": next_recommendation("SEED_REPRODUCTION_FAILED"),
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SEED_REPRODUCTION_FAILED", flush=True)
        return 1
    b_watch = [bytes.fromhex(row["child_key_hex"]) for row in root_b_moves(seed)]
    pass0 = run_local(
        seed,
        opening,
        prefix,
        name="PASS0",
        start_pass=0,
        max_pass=0,
        max_nodes=PASS0_NODES,
        time_limit=120.0,
        target_foundations=1,
        b_watch=b_watch,
    )
    _write_json(CHECKPOINTS / "PASS0.json", drop_private(pass0))
    pass1 = run_local(
        seed,
        opening,
        prefix,
        name="PASS1",
        start_pass=1,
        max_pass=1,
        max_nodes=PASS1_NODES,
        time_limit=TIME_LIMIT,
        target_foundations=1,
        b_watch=b_watch,
    )
    _write_json(CHECKPOINTS / "PASS1.json", drop_private(pass1))
    extra = None
    if (
        pass1.get("max_foundations", 0) >= 1
        and (pass1.get("combined_replay") or {}).get("ok")
        and (pass1.get("combined_replay") or {}).get("foundations", 0) >= 1
        and (pass1.get("first_foundation_node") or 10**9) < 200_000
        and material_progress(pass1)
    ):
        extra = run_local(
            seed,
            opening,
            prefix,
            name="PASS1_SOLVE",
            start_pass=1,
            max_pass=1,
            max_nodes=OPTIONAL_3M,
            time_limit=TIME_LIMIT_3M,
            target_foundations=8,
            b_watch=b_watch,
        )
        _write_json(CHECKPOINTS / "PASS1_SOLVE.json", drop_private(extra))
        if extra.get("solved") and (extra.get("combined_replay") or {}).get("solved"):
            SOLVED_ROUTE.write_text(
                format_moves_text(
                    prefix + extra["_result_actions"],
                    header="# v0.8 seeded A+B complete solution 4925153\n",
                ),
                encoding="utf-8",
            )
    elif (
        pass1.get("max_foundations", 0) == 0
        and material_progress(pass1)
        and not (
            pass1.get("nodes", 0) >= 100_000
            and (pass1.get("unique_ratio") or 1) < 0.05
        )
    ):
        extra = run_local(
            seed,
            opening,
            prefix,
            name="PASS1_3M",
            start_pass=1,
            max_pass=1,
            max_nodes=OPTIONAL_3M,
            time_limit=TIME_LIMIT_3M,
            target_foundations=1,
            b_watch=b_watch,
        )
        _write_json(CHECKPOINTS / "PASS1_3M.json", drop_private(extra))
        pass1 = extra
    if pass1.get("max_foundations", 0) >= 1 and (pass1.get("combined_replay") or {}).get("ok"):
        FOUNDATION_ROUTE.write_text(
            format_moves_text(
                prefix + (pass1.get("_foundation_actions") or pass1.get("_result_actions") or []),
                header="# v0.8 seeded A+B first foundation 4925153\n",
            ),
            encoding="utf-8",
        )
    source = extra if extra and extra.get("arm") == "PASS1_SOLVE" else pass1
    verdict, note = choose_verdict(True, pass0, source)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_public,
        "pass0": drop_private(pass0),
        "pass1": drop_private(pass1),
        "pass1_3m": None if extra is None else drop_private(extra),
        "verdict": verdict,
        "note": note,
        "interpretation": interpret(seed_public, pass0, source, verdict),
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
