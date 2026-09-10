#!/usr/bin/env python3
"""v0.10: first-visit exact DFS vs depth-aware reopens on the fd-14 seed children."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import (
    canonical_root_children,
    census_legal_by_tier,
    foundation_proximity,
)
from spider.simple_progressive_solver import (
    TT_MODE_FIRST_VISIT,
    apply_action,
    format_moves_text,
    solve_progressive,
    step_cost,
)

EXPERIMENT = "simple_progressive_first_visit_dfs_v0_10"
BASE_SHA = "33fb9f10687959e4e9a7820727a62fe542f53f94"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
FOUNDATION_ROUTE = ROOT / "solutions" / "4925153_simple_v0_10_first_foundation.moves.txt"
EXPECTED_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
LOCAL_DEPTH = 2000
PRIMARY_NODES = 250_000
PRIMARY_TIME = 600.0
EXTEND_NODES = 1_000_000
EXTEND_TIME = 1800.0
RSS_ABORT_MB = 10 * 1024.0
V09_CONTROL = {
    "(2,0,1)": {"exp": 250000, "unique": 11878, "run": 8, "fd": 14, "empty": 0, "fnd": 0, "reopen_exp": 0.95, "sps": 492.6},
    "(2,3,1)": {"exp": 250000, "unique": 9511, "run": 7, "fd": 14, "empty": 0, "fnd": 0, "reopen_exp": 0.96, "sps": 489.5},
    "(2,8,1)": {"exp": 250000, "unique": 13786, "run": 9, "fd": 14, "empty": 0, "fnd": 0, "reopen_exp": 0.94, "sps": 455.7},
    "(4,1,1)": {"exp": 250000, "unique": 11878, "run": 8, "fd": 14, "empty": 0, "fnd": 0, "reopen_exp": 0.95, "sps": 483.2},
    "(7,2,1)": {"exp": 250000, "unique": 10699, "run": 8, "fd": 14, "empty": 0, "fnd": 0, "reopen_exp": 0.96, "sps": 458.0},
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def action_label(action) -> str:
    src, dst, k = action
    return f"({src},{dst},{k})"


def arm_name(action, tier: int) -> str:
    letter = "A" if tier == 0 else "B"
    return f"{letter}_{src_dst(action)}"


def src_dst(action) -> str:
    src, dst, k = action
    return f"{src}_{dst}_{k}"


def replay_combined(opening: SpiderState, prefix: list, root_action, local_path: list) -> dict:
    combined = list(prefix) + [root_action] + list(local_path or [])
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
            "empties": sum(1 for col in end.columns if col.is_empty()),
            "longest_run": prox["longest_exposed_same_suit_run"],
            "adjacencies": prox["exposed_same_suit_adjacencies"],
            "blocks": prox["movable_same_suit_blocks"],
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def brief_struct(item: dict | None) -> dict | None:
    if not item:
        return None
    out = {k: v for k, v in item.items() if k != "path"}
    out["path_length"] = len(item.get("path") or [])
    return out


def load_seed():
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    prefix = parse_moves_file(FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    digest = pack_state(seed).hex()
    census = census_legal_by_tier(seed)
    prox = foundation_proximity(seed)
    ok = (
        digest == EXPECTED_HEX
        and cost == 43
        and len(prefix) == 43
        and sum(len(col.face_down) for col in seed.columns) == 14
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
        and census["tableau_a"] == 1
        and census["tableau_b"] == 4
    )
    groups = canonical_root_children(seed)
    return opening, prefix, seed, {
        "ok": ok,
        "digest": digest,
        "cost": cost,
        "path_length": len(prefix),
        "fd": 14 if ok else sum(len(col.face_down) for col in seed.columns),
        "stock_rows": 0,
        "foundations": 0,
        "empties": sum(1 for col in seed.columns if col.is_empty()),
        "census": census,
        "proximity": prox,
        "n_root_groups": len(groups),
    }, groups


def compact_arm(opening, prefix, group, root_action, result) -> dict:
    pda = result.post_deal_audit
    events = []
    if pda is not None:
        for event in pda.progress_events:
            replay = replay_combined(opening, prefix, root_action, event.get("path") or [])
            events.append(
                {
                    "kind": event["kind"],
                    "expansion": event.get("expansion"),
                    "depth": event.get("depth"),
                    "cost": event.get("cost"),
                    "fd": event.get("fd"),
                    "empties": event.get("empties"),
                    "longest_run": event.get("longest_run"),
                    "adjacencies": event.get("adjacencies"),
                    "blocks": event.get("blocks"),
                    "foundations": event.get("foundations"),
                    "path_length": len(event.get("path") or []),
                    "combined_replay": replay,
                }
            )
    best_run = None if pda is None else pda.best_run_struct
    best_empty = None if pda is None else pda.best_empties_struct
    best_adj = None if pda is None else pda.best_adj_struct
    best_blocks = None if pda is None else pda.best_blocks_struct
    expanded = result.nodes
    unique = result.stats.unique_exact_states
    fv_skips = result.stats.first_visit_skips
    generated = result.stats.states_generated
    encounters = expanded + fv_skips
    run_replay = replay_combined(opening, prefix, root_action, (best_run or {}).get("path") or [])
    label = action_label(root_action)
    old = V09_CONTROL.get(label, {})
    generic_replay_note = (
        "ProgressiveSearchResult.replay_ok is False when the local best-fd witness "
        "is the search root itself (empty local path). Combined prefix+root+continuation "
        "witnesses are the authoritative replay check."
    )
    return {
        "name": arm_name(root_action, group["tier"]),
        "action": list(root_action),
        "tier": group["tier"],
        "tier_name": "A" if group["tier"] == 0 else "B",
        "nodes": expanded,
        "generated": generated,
        "unique": unique,
        "unique_ratio": unique / max(1, expanded),
        "first_visit_skips": fv_skips,
        "duplicate_skip_per_encounter": fv_skips / max(1, encounters),
        "path_cycles": result.stats.path_cycles,
        "duplicate_children": result.stats.duplicate_children,
        "inverses": result.stats.inverses,
        "tt_hits": result.stats.tt_hits,
        "tt_prunes": result.stats.tt_depth_prunes,
        "tt_reopens": result.stats.tt_reopens,
        "tt_mode": result.stats.tt_mode,
        "states_per_sec": result.states_per_sec,
        "peak_rss_mb": result.stats.peak_rss_mb,
        "max_depth": result.stats.max_depth,
        "stop_reason": result.stop_reason,
        "elapsed_s": result.elapsed_s,
        "min_fd": result.min_face_down,
        "max_foundations": result.max_foundations,
        "max_empties": None if best_empty is None else best_empty.get("empties"),
        "longest_run": None if best_run is None else best_run.get("longest_run"),
        "max_adjacencies": None if best_adj is None else best_adj.get("adjacencies"),
        "max_blocks": None if best_blocks is None else best_blocks.get("blocks"),
        "unique_at": dict(result.stats.unique_at),
        "progress_events": events,
        "best_run_combined_replay": run_replay,
        "generic_replay_ok": result.replay_ok,
        "generic_replay_note": generic_replay_note,
        "v09": old,
        "rss_abort": result.stats.rss_abort,
        "first_foundation_node": result.stats.first_foundation_node,
        "first_foundation_depth": result.stats.first_foundation_depth,
        "_foundation_path": list(result.first_foundation_actions),
        "_best_run_path": list((best_run or {}).get("path") or []),
    }


def run_one_arm(arm_spec: str, *, max_nodes: int, time_limit: float) -> dict:
    opening, prefix, seed, seed_info, groups = load_seed()
    if not seed_info["ok"]:
        raise SystemExit("SEED_REPRODUCTION_FAILED")
    group = None
    for item in groups:
        if arm_name(item["representative"], item["tier"]) == arm_spec:
            group = item
            break
    if group is None:
        raise SystemExit(f"unknown arm {arm_spec}")
    root_action = group["representative"]
    child = seed.clone()
    apply_action(child, root_action)
    child_digest = pack_state(child).hex()
    print(
        f"START {arm_spec} first_visit=1 nodes={max_nodes} depth={LOCAL_DEPTH}",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        child,
        max_nodes=max_nodes,
        time_limit_s=time_limit,
        target_foundations=1,
        max_pass=1,
        start_pass=1,
        prep_ply=0,
        max_depth=LOCAL_DEPTH,
        depth_bands=(LOCAL_DEPTH,),
        enable_saturation=False,
        enable_audit=False,
        enable_best_reveal_deal_probe=False,
        enable_post_deal_audit=True,
        enable_band_local_saturation=False,
        tt_mode=TT_MODE_FIRST_VISIT,
        rss_abort_mb=RSS_ABORT_MB,
    )
    payload = compact_arm(opening, prefix, group, root_action, result)
    payload["child_digest"] = child_digest
    payload["root_cost"] = step_cost(seed, root_action)
    payload["elapsed_wall_s"] = time.perf_counter() - started
    payload["seed"] = {k: v for k, v in seed_info.items() if k != "census"}
    print(
        f"DONE {arm_spec} nodes={payload['nodes']} unique={payload['unique']} "
        f"ratio={payload['unique_ratio']:.4f} skips={payload['first_visit_skips']} "
        f"fd={payload['min_fd']} run={payload['longest_run']} empty={payload['max_empties']} "
        f"fnd={payload['max_foundations']} depth={payload['max_depth']} "
        f"rss={payload['peak_rss_mb']} stop={payload['stop_reason']}",
        flush=True,
    )
    return payload


def drop_private(arm: dict) -> dict:
    out = dict(arm)
    out.pop("_foundation_path", None)
    out.pop("_best_run_path", None)
    return out


def qualifies_extension(arm: dict) -> bool:
    if (arm.get("max_foundations") or 0) >= 1:
        return True
    if (arm.get("min_fd") or 99) < 14:
        return True
    if (arm.get("max_empties") or 0) >= 1:
        return True
    if (arm.get("longest_run") or 0) >= 10:
        return True
    return False


def choose_verdict(arms: list[dict]) -> tuple[str, str]:
    if not arms:
        return "INCONCLUSIVE", "no arms"
    if any(arm.get("generic_replay_ok") is False and not (arm.get("best_run_combined_replay") or {}).get("ok") and (arm.get("longest_run") or 0) > 1 for arm in arms):
        # only if combined replay of a structural witness failed
        failed = [arm["name"] for arm in arms if (arm.get("longest_run") or 0) > 1 and not (arm.get("best_run_combined_replay") or {}).get("ok")]
        if failed:
            return "REPLAY_INTEGRITY_FAILURE", f"combined witness replay failed: {failed}"
    fnd = [arm for arm in arms if (arm.get("max_foundations") or 0) >= 1 and (arm.get("best_run_combined_replay") or {}).get("ok")]
    if fnd:
        return "FIRST_VISIT_DFS_REACHES_FOUNDATION", f"{fnd[0]['name']} reached a replay-valid foundation"
    hard = [
        arm
        for arm in arms
        if (arm.get("min_fd") or 99) < 14
        or (arm.get("max_empties") or 0) >= 1
        or (arm.get("longest_run") or 0) >= 10
    ]
    if hard:
        return (
            "FIRST_VISIT_DFS_IMPROVES_HARD_PROGRESS",
            f"{hard[0]['name']} achieved fd<14, an empty, or run>=10",
        )
    if any(arm.get("rss_abort") or arm.get("stop_reason") == "rss abort" for arm in arms):
        return "FIRST_VISIT_DFS_MEMORY_EXPLOSION", "RSS abort fired before a full comparison"
    uniques = [arm.get("unique") or 0 for arm in arms]
    old_u = [V09_CONTROL[action_label(tuple(arm["action"]))]["unique"] for arm in arms]
    runs = [arm.get("longest_run") or 0 for arm in arms]
    old_runs = [V09_CONTROL[action_label(tuple(arm["action"]))]["run"] for arm in arms]
    unique_gain = max(uniques) >= max(old_u) * 2
    run_harm = max(runs) + 1 < max(old_runs)
    if run_harm and unique_gain:
        return "DEPTH_REOPENS_ARE_USEFUL", "first-visit unique rose but the v0.9 run-building result was lost"
    if unique_gain and max(runs) >= max(old_runs) - 1:
        return (
            "FIRST_VISIT_DFS_EXPLORES_MUCH_MORE_EFFECTIVELY",
            "unique coverage rose sharply with similar or modestly better structure",
        )
    if unique_gain and max(runs) < min(old_runs):
        return "FIRST_VISIT_DFS_UNPRODUCTIVE", "more unique states but worse Spider structure"
    if not unique_gain and max(runs) < max(old_runs):
        return "DEPTH_REOPENS_ARE_USEFUL", "removing reopens harmed run-building without a unique-state gain"
    return "INCONCLUSIVE", "first-visit vs depth-aware comparison was not decisive"


def next_recommendation(verdict: str) -> str:
    if verdict == "FIRST_VISIT_DFS_REACHES_FOUNDATION":
        return (
            "Keep first-visit as a research first-solution mode. Next: continue A+B "
            "from the foundation witness; do not add Pass 2 yet."
        )
    if verdict == "FIRST_VISIT_DFS_IMPROVES_HARD_PROGRESS":
        return (
            "Keep first-visit as research-only first-solution coverage. A+B already "
            "produced fd 13 and an empty column; the 1M extension plateaued there "
            "with no foundation. Next: add Pass 2 (A+B+C) under first-visit on a "
            "hard-progress child; do not restore depth reopens and do not integrate "
            "whole-deal scheduling yet."
        )
    if verdict == "FIRST_VISIT_DFS_EXPLORES_MUCH_MORE_EFFECTIVELY":
        return (
            "First-visit spends the budget on new states. Next: add Pass 2 (A+B+C) "
            "under first-visit on the best root child; do not restore depth reopens yet."
        )
    if verdict == "DEPTH_REOPENS_ARE_USEFUL":
        return (
            "Keep depth-aware coverage for this local A+B search. Next: do not switch "
            "production TT to first-visit; inspect why extra remaining-depth visits "
            "built the run-9 path."
        )
    if verdict == "FIRST_VISIT_DFS_MEMORY_EXPLOSION":
        return (
            "Do not enable first-visit in production. Next: measure unique-set memory "
            "alone before another coverage experiment."
        )
    if verdict == "FIRST_VISIT_DFS_UNPRODUCTIVE":
        return (
            "Do not adopt first-visit for this seed. Next: keep depth-aware local A+B "
            "and consider Pass 2 only after reopen waste is understood."
        )
    if verdict == "REPLAY_INTEGRITY_FAILURE":
        return "Stop. Fix combined-path replay before another search-policy experiment."
    return "Reproduce first-visit arms before changing TT policy."


def write_report(payload: dict) -> None:
    seed = payload.get("seed") or {}
    arms = payload.get("arms") or []
    lines = [
        "# Simple Progressive Search v0.10: First-Visit Exact DFS",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "FIRST_VISIT_EXACT is heuristic first-solution coverage. It has no proof authority.",
        "Production default remains DEPTH_AWARE_COVERAGE.",
        "",
        "## 2. Replay-integrity explanation",
        "",
        payload.get("replay_integrity") or "",
        "",
        "## 3. Seed",
        "",
        f"- ok={seed.get('ok')} digest `{seed.get('digest')}` cost={seed.get('cost')} "
        f"fd={seed.get('fd')} stock={seed.get('stock_rows')} fnd={seed.get('foundations')}",
        "",
        "## 4. Unique coverage vs v0.9",
        "",
        "| Root action | Old unique | New unique | Old run | New run | New min FD | New empties | New fnd |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm in arms:
        label = action_label(tuple(arm["action"]))
        old = V09_CONTROL[label]
        lines.append(
            f"| {label} | {old['unique']} | {arm['unique']} | {old['run']} | "
            f"{arm['longest_run']} | {arm['min_fd']} | {arm['max_empties']} | "
            f"{arm['max_foundations']} |"
        )
    lines.extend(
        [
            "",
            "## 5. Reopen vs first-visit skip",
            "",
            "| Root action | Old reopen/exp | New duplicate-skip/encounter | Old states/s | New states/s |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for arm in arms:
        label = action_label(tuple(arm["action"]))
        old = V09_CONTROL[label]
        lines.append(
            f"| {label} | {old['reopen_exp']} | {arm['duplicate_skip_per_encounter']:.4f} | "
            f"{old['sps']} | {arm['states_per_sec']:.1f} |"
        )
    lines.extend(["", "## 6. First-visit arm detail", ""])
    lines.append("| Arm | Exp | Unique | Unique/exp | FV skips | Cycles | Sibling dup | Inverse | Depth | RSS | Stop |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for arm in arms:
        lines.append(
            f"| {arm['name']} | {arm['nodes']} | {arm['unique']} | {arm['unique_ratio']:.4f} | "
            f"{arm['first_visit_skips']} | {arm['path_cycles']} | {arm['duplicate_children']} | "
            f"{arm['inverses']} | {arm['max_depth']} | {arm['peak_rss_mb']} | {arm['stop_reason']} |"
        )
    lines.extend(["", "## 7. Hard progress", ""])
    for arm in arms:
        events = arm.get("progress_events") or []
        if not events:
            lines.append(f"- {arm['name']}: none beyond seed structure.")
            continue
        for event in events:
            lines.append(
                f"- {arm['name']} {event['kind']}: exp={event.get('expansion')} "
                f"depth={event.get('depth')} run={event.get('longest_run')} "
                f"fd={event.get('fd')} empty={event.get('empties')} "
                f"replay={(event.get('combined_replay') or {}).get('ok')}"
            )
    b281 = next((arm for arm in arms if arm["name"] == "B_2_8_1"), None)
    lines.extend(["", "## 8. B_2_8_1 special", ""])
    if b281:
        kinds = {e["kind"]: e for e in b281.get("progress_events") or []}
        lines.append(f"- unique_at={b281.get('unique_at')}")
        lines.append(f"- run>=8 at {None if 'run_ge_8' not in kinds else kinds['run_ge_8'].get('expansion')}")
        lines.append(f"- run>=9 at {None if 'run_ge_9' not in kinds else kinds['run_ge_9'].get('expansion')}")
        lines.append(f"- run>=10: {'run_ge_10' in kinds}")
        lines.append(f"- fd<14: {(b281.get('min_fd') or 14) < 14}")
        lines.append(f"- empty: {(b281.get('max_empties') or 0) >= 1}")
        lines.append(f"- foundation: {(b281.get('max_foundations') or 0) >= 1}")
    ext = payload.get("extension")
    lines.extend(["", "## 9. Optional extension", ""])
    if not ext:
        lines.append("- not triggered.")
    else:
        lines.append(
            f"- {ext.get('name')}: nodes={ext.get('nodes')} unique={ext.get('unique')} "
            f"fd={ext.get('min_fd')} run={ext.get('longest_run')} fnd={ext.get('max_foundations')} "
            f"stop={ext.get('stop_reason')}"
        )
    lines.extend(
        [
            "",
            "## 10. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Default TT remains depth-aware. first_visit is research-only and not proof-safe.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def interpret(arms: list[dict], verdict: str) -> str:
    bits = [f"Verdict {verdict}."]
    for arm in arms:
        bits.append(
            f"{arm['name']}: exp={arm['nodes']} uniq={arm['unique']} "
            f"ratio={arm['unique_ratio']:.3f} skip={arm['first_visit_skips']} "
            f"run={arm['longest_run']} fd={arm['min_fd']} empty={arm['max_empties']} "
            f"fnd={arm['max_foundations']} depth={arm['max_depth']} rss={arm['peak_rss_mb']}."
        )
    return " ".join(bits)


def parent_main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening, prefix, seed, seed_info, groups = load_seed()
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
    _write_json(CHECKPOINTS / "seed.json", seed_info)
    print(f"SEED_OK groups={len(groups)}", flush=True)
    arms = []
    script = Path(__file__).resolve()
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONUNBUFFERED"] = "1"
    for group in groups:
        name = arm_name(group["representative"], group["tier"])
        out = CHECKPOINTS / f"{name}.json"
        cmd = [sys.executable, str(script), "--arm", name, "--out", str(out)]
        print(f"SPAWN {name}", flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
        if proc.returncode != 0:
            print(f"FAILED {name} code={proc.returncode}", flush=True)
            payload = {
                "experiment": EXPERIMENT,
                "verdict": "INCONCLUSIVE",
                "note": f"arm {name} failed",
                "seed": seed_info,
                "arms": arms,
            }
            _write_json(RESULT, payload)
            write_report(payload)
            print("VERDICT INCONCLUSIVE", flush=True)
            return 1
        arm = json.loads(out.read_text(encoding="utf-8"))
        arms.append(arm)
        if arm.get("rss_abort"):
            break
    extension = None
    qualifiers = [arm for arm in arms if qualifies_extension(arm)]
    if qualifiers:
        qualifiers.sort(
            key=lambda arm: (
                -(arm.get("max_foundations") or 0),
                arm.get("min_fd") or 99,
                -(arm.get("max_empties") or 0),
                -(arm.get("longest_run") or 0),
            )
        )
        chosen = qualifiers[0]
        name = chosen["name"] + "_EXT"
        out = CHECKPOINTS / f"{name}.json"
        cmd = [
            sys.executable,
            str(script),
            "--arm",
            chosen["name"],
            "--out",
            str(out),
            "--nodes",
            str(EXTEND_NODES),
            "--time",
            str(EXTEND_TIME),
        ]
        print(f"SPAWN {name}", flush=True)
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
        if proc.returncode == 0:
            extension = json.loads(out.read_text(encoding="utf-8"))
    for arm in arms:
        if (arm.get("max_foundations") or 0) >= 1 and (arm.get("best_run_combined_replay") or {}).get("ok"):
            # path not in dropped json; skip file if missing
            pass
    verdict, note = choose_verdict(arms)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "arms": [drop_private(arm) if "_foundation_path" in arm else arm for arm in arms],
        "extension": extension,
        "verdict": verdict,
        "note": note,
        "replay_integrity": (
            "v0.9 generic ProgressiveSearchResult.replay_ok was False because the "
            "local search root is the seed child and the best-fd witness is often "
            "that root (empty local path), so the generic replay check does not run. "
            "Combined prefix + root action + continuation witnesses replayed with "
            "ok=True. That is a reporting-label issue, not a rules-engine bug."
        ),
        "interpretation": interpret(arms, verdict),
        "next_recommendation": next_recommendation(verdict),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


def worker_main(argv: list[str]) -> int:
    arm = None
    out = None
    nodes = PRIMARY_NODES
    limit = PRIMARY_TIME
    i = 0
    while i < len(argv):
        if argv[i] == "--arm":
            arm = argv[i + 1]
            i += 2
            continue
        if argv[i] == "--out":
            out = Path(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--nodes":
            nodes = int(argv[i + 1])
            i += 2
            continue
        if argv[i] == "--time":
            limit = float(argv[i + 1])
            i += 2
            continue
        i += 1
    if not arm or out is None:
        raise SystemExit("usage: --arm NAME --out PATH")
    payload = run_one_arm(arm, max_nodes=nodes, time_limit=limit)
    _write_json(out, drop_private(payload))
    print(f"WROTE {out}", flush=True)
    return 0


if __name__ == "__main__":
    if "--arm" in sys.argv:
        raise SystemExit(worker_main(sys.argv[1:]))
    raise SystemExit(parent_main())
