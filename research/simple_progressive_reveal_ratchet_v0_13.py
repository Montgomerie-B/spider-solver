#!/usr/bin/env python3
"""v0.13: hard-progress reveal ratchet from the fd13/empty1 seed."""

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
from spider.simple_post_deal_audit import foundation_proximity
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    first_empty_use_on_path,
    is_hard_progress,
    layered_reachability,
)

EXPERIMENT = "simple_progressive_reveal_ratchet_v0_13"
BASE_SHA = "4e6b452a85b52d45f4c9a168995c5f843a45bdbd"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD11_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_13_fd10.moves.txt"
FD9_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_13_fd9.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_13_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
PHASE2_UNIQUE_FOR_PHASE3 = 250_000


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def load_seed():
    opening = opening_state()
    prefix = parse_moves_file(SEED_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    digest = pack_state(seed).hex()
    empties = empty_column_indices(seed)
    prox = foundation_proximity(seed)
    ok = (
        digest == EXPECTED_HEX
        and cost == 102
        and len(prefix) == 102
        and sum(len(col.face_down) for col in seed.columns) == 13
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
        and list(empties) == [2]
        and prox["longest_exposed_same_suit_run"] == 6
    )
    return opening, prefix, seed, {
        "ok": ok,
        "digest": digest,
        "cost": cost,
        "path_length": len(prefix),
        "fd": 13,
        "stock_rows": 0,
        "foundations": 0,
        "empties": list(empties),
        "longest_run": prox["longest_exposed_same_suit_run"],
    }


def replay_combined(opening: SpiderState, prefix: list, local: list) -> dict:
    combined = list(prefix) + [tuple(item) for item in local]
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        prox = foundation_proximity(end)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "fd": sum(len(col.face_down) for col in end.columns),
            "stock_rows": len(end.stock) // 10,
            "foundations": len(end.foundations),
            "empties": list(empty_column_indices(end)),
            "longest_run": prox["longest_exposed_same_suit_run"],
            "adjacencies": prox["exposed_same_suit_adjacencies"],
            "blocks": prox["movable_same_suit_blocks"],
            "digest": pack_state(end).hex(),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def workspace_on_path(root: SpiderState, actions: list) -> dict:
    start_empty = list(empty_column_indices(root))
    first_use = first_empty_use_on_path(root, actions)
    seq = [start_empty]
    events = []
    state = root.clone()
    for action in actions:
        before = empty_column_indices(state)
        dest_was_empty = False
        source_became = False
        if action != ("deal",):
            src, dst, k = action
            dest_was_empty = state.columns[dst].is_empty()
            source_became = k == len(state.columns[src].face_up) and not state.columns[src].face_down
        apply_action(state, action)
        after = empty_column_indices(state)
        seq.append(list(after))
        events.extend(
            empty_transition_events(
                before, after, dest_was_empty=dest_was_empty, source_became_empty=source_became
            )
        )
    timing = "never"
    if first_use:
        if first_use.get("immediate"):
            timing = "immediate"
        elif first_use.get("after_ab_setup"):
            timing = "delayed A/B setup"
        elif first_use.get("after_c_rework"):
            timing = "delayed after C rework"
        else:
            timing = "delayed"
    return {
        "start_empties": start_empty,
        "end_empties": seq[-1],
        "empty_sequence": seq,
        "events": events,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "second_empty": events.count("SECOND_EMPTY"),
        "first_empty_use": first_use,
        "timing": timing,
    }


def save_fixture(path: Path, combined: list, replay: dict, header_lines: list[str]) -> None:
    header = "\n".join(header_lines)
    path.write_text(format_moves_text(combined, header=header), encoding="utf-8")


def compact_search(result) -> dict:
    return {
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_run": result.max_run,
        "max_empties": result.max_empties,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "layers": result.layers,
        "fresh_tt": result.fresh_tt,
        "imported_keys": result.imported_keys,
        "root_digest": result.root_digest,
        "first_depth": result.first_depth,
    }


def stage_from_witness(opening, prefix, root, result, kind: str, start_fd: int) -> dict | None:
    raw = result.witnesses.get(kind)
    if not raw:
        return None
    local = [tuple(a) for a in raw.get("actions") or []]
    replay = replay_combined(opening, prefix, local)
    space = workspace_on_path(root, local)
    return {
        "kind": kind,
        "local_depth": raw.get("depth"),
        "local_cost": raw.get("local_cost"),
        "actions": [list(a) for a in local],
        "combined_replay": replay,
        "workspace": space,
        "search": compact_search(result),
        "hard_progress": is_hard_progress(
            start_fd=start_fd,
            start_foundations=len(root.foundations),
            fd=replay.get("fd", 99),
            foundations=replay.get("foundations", 0),
            empties=len(replay.get("empties") or []),
            longest_run=replay.get("longest_run") or 0,
            adjacencies=replay.get("adjacencies") or 0,
            blocks=replay.get("blocks") or 0,
        ),
        "fresh_tt": result.fresh_tt,
        "imported_keys": result.imported_keys,
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("phase1_failed"):
        return "FD11_REPRODUCTION_FAILED", payload.get("phase1_failed") or "fd11 not found"
    if payload.get("foundation"):
        return "REVEAL_RATCHET_REACHES_FOUNDATION", "a replay-valid foundation was reached"
    phase3 = payload.get("phase3") or {}
    if (phase3.get("combined_replay") or {}).get("ok") and (phase3.get("combined_replay") or {}).get("fd", 99) <= 9:
        return "REVEAL_RATCHET_CONTINUES_TO_FD9", "optional third stage reached fd9"
    phase2 = payload.get("phase2") or {}
    if (phase2.get("combined_replay") or {}).get("ok") and (phase2.get("combined_replay") or {}).get("fd", 99) <= 10:
        return "REVEAL_RATCHET_CONTINUES_TO_FD10", "fresh search from fd11 reached fd10"
    search2 = (phase2.get("search") if phase2 else None) or payload.get("phase2_search") or {}
    if search2.get("stop_reason") in ("unique limit", "time limit", "rss abort") and not phase2:
        return "REVEAL_RATCHET_STATE_EXPLOSION", f"phase 2 stopped ({search2.get('stop_reason')}) without fd10"
    if payload.get("phase1") and not phase2:
        note = search2.get("stop_reason") or "fd10 not reached"
        if note in ("unique limit", "time limit", "rss abort"):
            return "REVEAL_RATCHET_STATE_EXPLOSION", f"phase 2 {note} before fd10"
        return "REVEAL_RATCHET_STALLS_AT_FD11", "fd11 harvested but fd10 not reached in the bounded envelope"
    return "INCONCLUSIVE", "methodological or incomplete ratchet"


def next_recommendation(verdict: str) -> str:
    if verdict == "REVEAL_RATCHET_REACHES_FOUNDATION":
        return (
            "Keep the foundation route as a research fixture. Next: do not add a "
            "heuristic yet; inspect whether later ratchet stages stay short."
        )
    if verdict == "REVEAL_RATCHET_CONTINUES_TO_FD9":
        return (
            "The reveal ratchet is cascading. Next: continue one more shallow "
            "restart from fd9 toward fd8; do not add scoring or Pass 3."
        )
    if verdict == "REVEAL_RATCHET_CONTINUES_TO_FD10":
        return (
            "Fresh shallow search from fd11 reached fd10. Next: run the optional "
            "fd10→fd9 restart if not already done, or continue the ratchet one "
            "stage further; do not integrate it into production yet."
        )
    if verdict == "REVEAL_RATCHET_STALLS_AT_FD11":
        return (
            "The minimum-depth fd11 consumed the last empty, and A+B+C from that "
            "empty-less checkpoint is a closed bubble with no fd10. Next: do not "
            "add a heuristic and do not deepen DFS from this checkpoint; if another "
            "ratchet is tried, compare same-depth fd11 children that still hold an empty."
        )
    if verdict == "FD11_REPRODUCTION_FAILED":
        return "Stop. Reproduce the v0.12 fd11 child before another ratchet stage."
    if verdict == "REVEAL_RATCHET_STATE_EXPLOSION":
        return (
            "The fresh stage exploded before a useful next reveal. Next: report "
            "the completed layers and stop; do not raise limits or add a heuristic."
        )
    return "Reproduce the fd11 harvest before changing search policy."


def write_report(payload: dict) -> None:
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2") or {}
    p3 = payload.get("phase3") or {}
    rows = payload.get("checkpoint_table") or []
    lines = [
        "# Simple Progressive Search v0.13: Hard-Progress Reveal Ratchet",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "Each stage uses a fresh exact first-visit table. Production `solve_progressive` is unchanged.",
        "",
        "## 2. Seed",
        "",
        f"- ok={(payload.get('seed') or {}).get('ok')} digest `{(payload.get('seed') or {}).get('digest')}`",
        f"- empty columns={(payload.get('seed') or {}).get('empties')}",
        "",
        "## 3. Checkpoint comparison",
        "",
        "| Start FD | Target FD | Local depth | Unique searched | Local MW cost | Start empties | End empties | Foundation |",
        "| ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('start_fd')} | {row.get('target_fd')} | {row.get('local_depth')} | "
            f"{row.get('unique')} | {row.get('local_cost')} | {row.get('start_empties')} | "
            f"{row.get('end_empties')} | {row.get('foundations')} |"
        )
    lines.extend(["", "## 4. Phase 1 — harvest fd11", ""])
    if not p1:
        lines.append(f"- FAILED: {payload.get('phase1_failed')}")
    else:
        r = p1.get("combined_replay") or {}
        w = p1.get("workspace") or {}
        s = p1.get("search") or {}
        lines.append(
            f"- stop={s.get('stop_reason')} unique={s.get('unique')} depth={p1.get('local_depth')} "
            f"local_cost={p1.get('local_cost')} rss={s.get('peak_rss_mb')} elapsed={s.get('elapsed_s')}"
        )
        lines.append(
            f"- replay ok={r.get('ok')} total_path={r.get('path_length')} cost={r.get('cost')} "
            f"fd={r.get('fd')} stock={r.get('stock_rows')} fnd={r.get('foundations')} "
            f"empties={r.get('empties')} run={r.get('longest_run')}"
        )
        lines.append(
            f"- workspace timing={w.get('timing')} consumed={w.get('consumed')} "
            f"transferred={w.get('transferred')} recreated={w.get('recreated')} "
            f"second_empty={w.get('second_empty')} sequence={w.get('empty_sequence')}"
        )
        lines.append(f"- fixture `{payload.get('fd11_fixture')}`")
        lines.append(f"- fresh_tt={p1.get('fresh_tt')} imported_keys={p1.get('imported_keys')}")
    lines.extend(["", "## 5. Phase 2 — restart from fd11", ""])
    if not p2 and not payload.get("phase2_search"):
        lines.append("- not run.")
    elif not p2:
        s = payload.get("phase2_search") or {}
        lines.append(
            f"- no fd10. stop={s.get('stop_reason')} unique={s.get('unique')} "
            f"min_fd={s.get('min_fd')} max_fnd={s.get('max_foundations')} "
            f"gen_depth={s.get('completed_generated_depth')} rss={s.get('peak_rss_mb')}"
        )
        lines.append("")
        lines.append("| Depth | Frontier | Unique | Generated | Dup | A | B | C | empty0 | empty1 | empty>=2 | min fd | max run |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for layer in s.get("layers") or []:
            lines.append(
                f"| {layer.get('depth')} | {layer.get('frontier_size')} | {layer.get('cumulative_unique')} | "
                f"{layer.get('generated_successors')} | {layer.get('exact_duplicate_skips')} | "
                f"{layer.get('a_children')} | {layer.get('b_children')} | {layer.get('c_children')} | "
                f"{layer.get('states_empty_0')} | {layer.get('states_empty_1')} | {layer.get('states_empty_ge2')} | "
                f"{layer.get('min_fd')} | {layer.get('max_run')} |"
            )
    else:
        r = p2.get("combined_replay") or {}
        w = p2.get("workspace") or {}
        s = p2.get("search") or {}
        lines.append(
            f"- stop={s.get('stop_reason')} unique={s.get('unique')} depth={p2.get('local_depth')} "
            f"local_cost={p2.get('local_cost')} rss={s.get('peak_rss_mb')} elapsed={s.get('elapsed_s')}"
        )
        lines.append(
            f"- replay ok={r.get('ok')} total_path={r.get('path_length')} cost={r.get('cost')} "
            f"fd={r.get('fd')} fnd={r.get('foundations')} empties={r.get('empties')} run={r.get('longest_run')}"
        )
        lines.append(
            f"- workspace timing={w.get('timing')} consumed={w.get('consumed')} "
            f"transferred={w.get('transferred')} recreated={w.get('recreated')} "
            f"sequence={w.get('empty_sequence')}"
        )
        lines.append(f"- fresh_tt={p2.get('fresh_tt')} imported_keys={p2.get('imported_keys')}")
        lines.append(f"- fixture `{payload.get('fd10_fixture')}`")
        lines.append("")
        lines.append("| Depth | Frontier | Unique | Generated | Dup | A | B | C | empty0 | empty1 | empty>=2 | min fd | max run |")
        lines.append("| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for layer in s.get("layers") or []:
            lines.append(
                f"| {layer.get('depth')} | {layer.get('frontier_size')} | {layer.get('cumulative_unique')} | "
                f"{layer.get('generated_successors')} | {layer.get('exact_duplicate_skips')} | "
                f"{layer.get('a_children')} | {layer.get('b_children')} | {layer.get('c_children')} | "
                f"{layer.get('states_empty_0')} | {layer.get('states_empty_1')} | {layer.get('states_empty_ge2')} | "
                f"{layer.get('min_fd')} | {layer.get('max_run')} |"
            )
    lines.extend(["", "## 6. Optional Phase 3 — fd10 to fd9", ""])
    if not p3 and not payload.get("phase3_skipped"):
        lines.append("- not run.")
    elif payload.get("phase3_skipped"):
        lines.append(f"- skipped: {payload.get('phase3_skipped')}")
    else:
        r = p3.get("combined_replay") or {}
        w = p3.get("workspace") or {}
        s = p3.get("search") or {}
        lines.append(
            f"- stop={s.get('stop_reason')} unique={s.get('unique')} depth={p3.get('local_depth')} "
            f"fd={r.get('fd')} replay={r.get('ok')} timing={w.get('timing')}"
        )
        lines.append(f"- fixture `{payload.get('fd9_fixture')}`")
    fnd = payload.get("foundation")
    lines.extend(["", "## 7. Foundation", ""])
    if not fnd:
        lines.append("- no foundation reached.")
    else:
        r = fnd.get("combined_replay") or {}
        lines.append(
            f"- replay ok={r.get('ok')} path={r.get('path_length')} cost={r.get('cost')} "
            f"fd={r.get('fd')} fnd={r.get('foundations')} fixture `{payload.get('foundation_fixture')}`"
        )
    lines.extend(
        [
            "",
            "## 8. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Ratchet restarts use a fresh TT. Production solve_progressive is unchanged.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    opening, prefix, seed, seed_info = load_seed()
    if not seed_info["ok"]:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "INCONCLUSIVE",
            "note": "seed failed",
            "seed": seed_info,
        }
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print(f"SEED_OK empty={seed_info['empties']}", flush=True)

    print("PHASE1 harvest fd<=11", flush=True)
    phase1_result = layered_reachability(
        seed,
        max_depth=12,
        max_unique=1_000_000,
        time_limit_s=1800.0,
        rss_abort_mb=8 * 1024.0,
        stop_fd=11,
        checkpoints=(4, 8, 12),
    )
    print(
        f"PHASE1 stop={phase1_result.stop_reason} unique={phase1_result.unique} "
        f"min_fd={phase1_result.min_fd} depth_gen={phase1_result.completed_generated_depth} "
        f"rss={phase1_result.peak_rss_mb} elapsed={phase1_result.elapsed_s:.1f}",
        flush=True,
    )
    phase1 = stage_from_witness(opening, prefix, seed, phase1_result, "fd_le_11", 13)
    if phase1 is None or not (phase1.get("combined_replay") or {}).get("ok"):
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "seed": seed_info,
            "phase1_failed": phase1_result.stop_reason,
            "phase1_search": compact_search(phase1_result),
            "verdict": "FD11_REPRODUCTION_FAILED",
            "note": "no replay-valid fd<=11 witness",
        }
        payload["next_recommendation"] = next_recommendation("FD11_REPRODUCTION_FAILED")
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT FD11_REPRODUCTION_FAILED", flush=True)
        return 1
    if (phase1["combined_replay"].get("fd") or 99) > 11:
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "seed": seed_info,
            "phase1": phase1,
            "phase1_failed": "fd11 witness fd > 11",
            "verdict": "FD11_REPRODUCTION_FAILED",
        }
        payload["next_recommendation"] = next_recommendation("FD11_REPRODUCTION_FAILED")
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT FD11_REPRODUCTION_FAILED", flush=True)
        return 1

    local1 = [tuple(a) for a in phase1["actions"]]
    combined1 = list(prefix) + local1
    save_fixture(
        FD11_FIXTURE,
        combined1,
        phase1["combined_replay"],
        [
            "# v0.13 fd<=11 reveal-ratchet checkpoint 4925153",
            f"# local_depth: {phase1['local_depth']}",
            f"# primitive_moves: {phase1['combined_replay']['path_length']}",
            f"# mobilityware_moves: {phase1['combined_replay']['cost']}",
            f"# digest: {phase1['combined_replay']['digest']}",
            f"# fd: {phase1['combined_replay']['fd']}",
            f"# empties: {phase1['combined_replay']['empties']}",
        ],
    )
    print(f"WROTE {FD11_FIXTURE}", flush=True)

    fd11_state = opening.clone()
    replay_actions(fd11_state, combined1)
    table = [
        {
            "start_fd": 13,
            "target_fd": 11,
            "local_depth": phase1["local_depth"],
            "unique": phase1["search"]["unique"],
            "local_cost": phase1["local_cost"],
            "start_empties": phase1["workspace"]["start_empties"],
            "end_empties": phase1["workspace"]["end_empties"],
            "foundations": phase1["combined_replay"]["foundations"],
        }
    ]

    foundation = None
    if phase1_result.max_foundations >= 1 and "foundation" in phase1_result.witnesses:
        foundation = stage_from_witness(opening, prefix, seed, phase1_result, "foundation", 13)

    phase2 = None
    phase2_search = None
    phase3 = None
    phase3_skipped = None
    if foundation is None:
        print("PHASE2 fresh search from fd11, target fd<=10", flush=True)
        phase2_result = layered_reachability(
            fd11_state,
            max_depth=12,
            max_unique=1_000_000,
            time_limit_s=1200.0,
            rss_abort_mb=4 * 1024.0,
            stop_fd=10,
            checkpoints=(4, 8, 12),
        )
        print(
            f"PHASE2 stop={phase2_result.stop_reason} unique={phase2_result.unique} "
            f"min_fd={phase2_result.min_fd} fnd={phase2_result.max_foundations} "
            f"fresh_tt={phase2_result.fresh_tt} imported={phase2_result.imported_keys} "
            f"root={phase2_result.root_digest[:16]} "
            f"rss={phase2_result.peak_rss_mb} elapsed={phase2_result.elapsed_s:.1f}",
            flush=True,
        )
        phase2_search = compact_search(phase2_result)
        if phase1["search"]["root_digest"] == phase2_result.root_digest:
            raise SystemExit("phase2 reused phase1 root digest")
        if "foundation" in phase2_result.witnesses:
            foundation = stage_from_witness(
                opening, combined1, fd11_state, phase2_result, "foundation", 11
            )
        phase2 = stage_from_witness(opening, combined1, fd11_state, phase2_result, "fd_le_10", 11)
        if phase2 and (phase2.get("combined_replay") or {}).get("ok"):
            local2 = [tuple(a) for a in phase2["actions"]]
            combined2 = combined1 + local2
            save_fixture(
                FD10_FIXTURE,
                combined2,
                phase2["combined_replay"],
                [
                    "# v0.13 fd<=10 reveal-ratchet checkpoint 4925153",
                    f"# local_depth: {phase2['local_depth']}",
                    f"# primitive_moves: {phase2['combined_replay']['path_length']}",
                    f"# mobilityware_moves: {phase2['combined_replay']['cost']}",
                    f"# digest: {phase2['combined_replay']['digest']}",
                    f"# fd: {phase2['combined_replay']['fd']}",
                ],
            )
            print(f"WROTE {FD10_FIXTURE}", flush=True)
            table.append(
                {
                    "start_fd": 11,
                    "target_fd": 10,
                    "local_depth": phase2["local_depth"],
                    "unique": phase2["search"]["unique"],
                    "local_cost": phase2["local_cost"],
                    "start_empties": phase2["workspace"]["start_empties"],
                    "end_empties": phase2["workspace"]["end_empties"],
                    "foundations": phase2["combined_replay"]["foundations"],
                }
            )
            if foundation is None and phase2_result.unique <= PHASE2_UNIQUE_FOR_PHASE3:
                fd10_state = opening.clone()
                replay_actions(fd10_state, combined2)
                print("PHASE3 fresh search from fd10, target fd<=9", flush=True)
                phase3_result = layered_reachability(
                    fd10_state,
                    max_depth=12,
                    max_unique=1_000_000,
                    time_limit_s=1200.0,
                    rss_abort_mb=4 * 1024.0,
                    stop_fd=9,
                    checkpoints=(4, 8, 12),
                )
                print(
                    f"PHASE3 stop={phase3_result.stop_reason} unique={phase3_result.unique} "
                    f"min_fd={phase3_result.min_fd} imported={phase3_result.imported_keys}",
                    flush=True,
                )
                if "foundation" in phase3_result.witnesses:
                    foundation = stage_from_witness(
                        opening, combined2, fd10_state, phase3_result, "foundation", 10
                    )
                phase3 = stage_from_witness(
                    opening, combined2, fd10_state, phase3_result, "fd_le_9", 10
                )
                if phase3 and (phase3.get("combined_replay") or {}).get("ok"):
                    local3 = [tuple(a) for a in phase3["actions"]]
                    combined3 = combined2 + local3
                    save_fixture(
                        FD9_FIXTURE,
                        combined3,
                        phase3["combined_replay"],
                        [
                            "# v0.13 fd<=9 reveal-ratchet checkpoint 4925153",
                            f"# local_depth: {phase3['local_depth']}",
                            f"# primitive_moves: {phase3['combined_replay']['path_length']}",
                            f"# mobilityware_moves: {phase3['combined_replay']['cost']}",
                            f"# fd: {phase3['combined_replay']['fd']}",
                        ],
                    )
                    table.append(
                        {
                            "start_fd": 10,
                            "target_fd": 9,
                            "local_depth": phase3["local_depth"],
                            "unique": phase3["search"]["unique"],
                            "local_cost": phase3["local_cost"],
                            "start_empties": phase3["workspace"]["start_empties"],
                            "end_empties": phase3["workspace"]["end_empties"],
                            "foundations": phase3["combined_replay"]["foundations"],
                        }
                    )
            elif foundation is None:
                phase3_skipped = f"phase2 unique {phase2_result.unique} > {PHASE2_UNIQUE_FOR_PHASE3}"
        elif phase2_search and not phase2:
            table.append(
                {
                    "start_fd": 11,
                    "target_fd": 10,
                    "local_depth": None,
                    "unique": phase2_search["unique"],
                    "local_cost": None,
                    "start_empties": list(empty_column_indices(fd11_state)),
                    "end_empties": None,
                    "foundations": phase2_search["max_foundations"],
                }
            )

    if foundation and (foundation.get("combined_replay") or {}).get("ok"):
        fnd_local = [tuple(a) for a in foundation["actions"]]
        # foundation.combined_replay already includes the prefix used in stage_from_witness
        fnd_path = parse_moves_file(FD11_FIXTURE) if FD11_FIXTURE.exists() else combined1
        # Recompute from original deal using reported combined length
        fnd_replay = foundation["combined_replay"]
        save_fixture(
            FOUNDATION_FIXTURE,
            list(prefix) + local1 + fnd_local
            if foundation is not phase1
            else list(prefix) + fnd_local,
            fnd_replay,
            [
                "# v0.13 first-foundation reveal-ratchet 4925153",
                f"# primitive_moves: {fnd_replay.get('path_length')}",
                f"# mobilityware_moves: {fnd_replay.get('cost')}",
                f"# fd: {fnd_replay.get('fd')}",
                f"# foundations: {fnd_replay.get('foundations')}",
            ],
        )

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "phase1": phase1,
        "phase2": phase2,
        "phase2_search": phase2_search,
        "phase3": phase3,
        "phase3_skipped": phase3_skipped,
        "foundation": foundation,
        "checkpoint_table": table,
        "fd11_fixture": str(FD11_FIXTURE.relative_to(ROOT)).replace("\\", "/"),
        "fd10_fixture": str(FD10_FIXTURE.relative_to(ROOT)).replace("\\", "/") if FD10_FIXTURE.exists() else None,
        "fd9_fixture": str(FD9_FIXTURE.relative_to(ROOT)).replace("\\", "/") if FD9_FIXTURE.exists() else None,
        "foundation_fixture": str(FOUNDATION_FIXTURE.relative_to(ROOT)).replace("\\", "/")
        if FOUNDATION_FIXTURE.exists()
        else None,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. fd11 depth={None if not phase1 else phase1.get('local_depth')} "
        f"fd10={'yes' if phase2 else 'no'} fd9={'yes' if phase3 else 'no'} "
        f"foundation={'yes' if foundation else 'no'}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
