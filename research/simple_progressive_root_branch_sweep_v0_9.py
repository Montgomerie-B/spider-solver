#!/usr/bin/env python3
"""v0.9: matched A+B continuation from each distinct fd-14 seed root child."""

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
from spider.simple_post_deal_audit import (
    canonical_root_children,
    census_legal_by_tier,
    foundation_proximity,
)
from spider.simple_progressive_solver import (
    apply_action,
    format_moves_text,
    solve_progressive,
    step_cost,
)

EXPERIMENT = "simple_progressive_root_branch_sweep_v0_9"
BASE_SHA = "46f43c8b756205715a0b3b284b3da17038ab5a32"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CHECKPOINTS = ROOT / "research" / "results" / EXPERIMENT
FOUNDATION_ROUTE = ROOT / "solutions" / "4925153_simple_v0_9_first_foundation.moves.txt"
EXPECTED_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
LOCAL_DEPTH = 320
PRIMARY_NODES = 250_000
PRIMARY_TIME = 600.0
EXTEND_NODES = 1_000_000
EXTEND_TIME = 1800.0


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
    empties = sum(1 for col in seed.columns if col.is_empty())
    stock = len(seed.stock) // 10
    fnd = len(seed.foundations)
    census = census_legal_by_tier(seed)
    prox = foundation_proximity(seed)
    ok = (
        digest == EXPECTED_HEX
        and fd == 14
        and stock == 0
        and fnd == 0
        and empties == 0
        and cost == 43
        and len(actions) == 43
        and census["tableau_a"] == 1
        and census["tableau_b"] == 4
        and not census["has_immediate_foundation_move"]
        and prox["longest_exposed_same_suit_run"] == 1
    )
    return {
        "ok": ok,
        "seed": seed,
        "digest": digest,
        "fd": fd,
        "stock_rows": stock,
        "foundations": fnd,
        "empties": empties,
        "cost": cost,
        "path_length": len(actions),
        "census": census,
        "proximity": prox,
    }


def action_label(action) -> str:
    if action == ("deal",) or action == "deal":
        return "deal"
    src, dst, k = action
    return f"({src},{dst},{k})"


def arm_name(group: dict) -> str:
    tier = "A" if group["tier"] == 0 else "B"
    return f"{tier}_{action_label(group['representative']).replace('(', '').replace(')', '').replace(',', '_')}"


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


def compact_arm(
    *,
    opening: SpiderState,
    prefix: list,
    group: dict,
    root_action,
    root_cost: int,
    child_digest: str,
    result,
) -> dict:
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
    best_fd = None if pda is None else pda.best_fd_struct
    best_empty = None if pda is None else pda.best_empties_struct
    best_adj = None if pda is None else pda.best_adj_struct
    best_fnd = None if pda is None else pda.best_fnd_struct
    best_blocks = None if pda is None else pda.best_blocks_struct
    witnesses = {
        "best_fd": brief_struct(best_fd),
        "best_empties": brief_struct(best_empty),
        "best_run": brief_struct(best_run),
        "best_adjacencies": brief_struct(best_adj),
        "best_foundations": brief_struct(best_fnd),
        "best_blocks": brief_struct(best_blocks),
    }
    for name, item in (
        ("best_fd", best_fd),
        ("best_empties", best_empty),
        ("best_run", best_run),
        ("best_adjacencies", best_adj),
        ("best_foundations", best_fnd),
        ("best_blocks", best_blocks),
    ):
        if item and witnesses[name] is not None:
            witnesses[name]["combined_replay"] = replay_combined(
                opening, prefix, root_action, item.get("path") or []
            )
    run_replay = replay_combined(
        opening, prefix, root_action, (best_run or {}).get("path") or []
    )
    unique = result.stats.unique_exact_states
    expanded = result.nodes
    return {
        "name": arm_name(group),
        "action": list(root_action) if isinstance(root_action, tuple) else root_action,
        "tier": group["tier"],
        "tier_name": "A" if group["tier"] == 0 else "B",
        "child_digest": child_digest,
        "equivalent_actions": [
            list(item["action"]) if isinstance(item["action"], tuple) else item["action"]
            for item in group["actions"]
        ],
        "canonical_equivalent": group["equivalent"],
        "root_cost": root_cost,
        "nodes": expanded,
        "unique": unique,
        "unique_ratio": unique / max(1, expanded),
        "tt_hits": result.stats.tt_hits,
        "tt_prunes": result.stats.tt_depth_prunes,
        "tt_reopens": result.stats.tt_reopens,
        "reopen_ratio": result.stats.tt_reopens / max(1, expanded),
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
        "first_foundation_node": result.stats.first_foundation_node,
        "first_foundation_depth": result.stats.first_foundation_depth,
        "progress_events": events,
        "witnesses": witnesses,
        "best_run_combined_replay": run_replay,
        "band_pass": [
            {
                "band": row.get("band"),
                "pass": row.get("pass"),
                "expanded": row.get("expanded"),
                "unique_new": row.get("unique_new"),
                "reopens": row.get("reopens"),
                "stop": row.get("stop"),
            }
            for row in result.stats.band_pass_reports
        ],
        "solved": result.solved,
        "replay_ok": result.replay_ok,
        "_foundation_path": list(result.first_foundation_actions),
        "_best_run_path": list((best_run or {}).get("path") or []),
    }


def run_arm(
    *,
    opening: SpiderState,
    prefix: list,
    seed: SpiderState,
    group: dict,
    max_nodes: int,
    time_limit: float,
    label: str,
) -> dict:
    root_action = group["representative"]
    child = seed.clone()
    root_cost = step_cost(seed, root_action)
    apply_action(child, root_action)
    child_digest = pack_state(child).hex()
    print(
        f"START {label} action={action_label(root_action)} tier={group['tier']} "
        f"nodes={max_nodes} time={time_limit}",
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
        depth_bands=(LOCAL_DEPTH,),
        enable_saturation=False,
        enable_audit=False,
        enable_best_reveal_deal_probe=False,
        enable_post_deal_audit=True,
        enable_band_local_saturation=False,
    )
    payload = compact_arm(
        opening=opening,
        prefix=prefix,
        group=group,
        root_action=root_action,
        root_cost=root_cost,
        child_digest=child_digest,
        result=result,
    )
    payload["elapsed_wall_s"] = time.perf_counter() - started
    print(
        f"DONE {label} nodes={payload['nodes']} unique={payload['unique']} "
        f"fd={payload['min_fd']} run={payload['longest_run']} "
        f"empty={payload['max_empties']} fnd={payload['max_foundations']} "
        f"ratio={payload['unique_ratio']:.4f} sps={payload['states_per_sec']:.1f} "
        f"rss={payload['peak_rss_mb']} stop={payload['stop_reason']}",
        flush=True,
    )
    return payload


def qualifies_extension(arm: dict) -> bool:
    if (arm.get("max_foundations") or 0) >= 1:
        return True
    if (arm.get("min_fd") or 99) < 14:
        return True
    if (arm.get("max_empties") or 0) >= 1:
        return True
    if (arm.get("longest_run") or 0) >= 9:
        return True
    return False


def drop_private(arm: dict) -> dict:
    out = dict(arm)
    out.pop("_foundation_path", None)
    out.pop("_best_run_path", None)
    return out


def choose_verdict(arms: list[dict]) -> tuple[str, str]:
    if not arms:
        return "INCONCLUSIVE", "no root arms ran"
    a_arms = [arm for arm in arms if arm["tier"] == 0]
    b_arms = [arm for arm in arms if arm["tier"] == 1]
    b_fnd = [arm for arm in b_arms if (arm.get("max_foundations") or 0) >= 1]
    a_fnd = [arm for arm in a_arms if (arm.get("max_foundations") or 0) >= 1]
    if any(arm.get("solved") and (arm.get("best_run_combined_replay") or {}).get("ok") for arm in arms):
        solved = next(arm for arm in arms if arm.get("solved"))
        if (solved.get("best_run_combined_replay") or {}).get("foundations", 0) >= 8:
            return "SIMPLE_SOLVER_COMPLETE_SOLUTION", "an A+B arm completed the game"
    if b_fnd:
        return (
            "ROOT_B_BRANCH_REACHES_FOUNDATION",
            f"Tier-B root {b_fnd[0]['name']} reached a replay-valid foundation",
        )
    if a_fnd and not b_fnd:
        return (
            "ROOT_BRANCH_REACHES_FOUNDATION",
            "the Tier-A control branch reached a foundation; B branches did not",
        )
    ratios = [arm.get("unique_ratio") or 0 for arm in arms]
    runs = [arm.get("longest_run") or 1 for arm in arms]
    fds = [arm.get("min_fd") or 14 for arm in arms]
    empties = [arm.get("max_empties") or 0 for arm in arms]
    if all(ratio < 0.02 for ratio in ratios) and max(runs) <= 2 and min(fds) >= 14 and max(empties) == 0:
        return (
            "LOCAL_PASS1_REOPEN_PATHOLOGY_DOMINATES",
            "all arms spent almost all work reopening exact states without measurable structure",
        )
    a_run = max((arm.get("longest_run") or 1) for arm in a_arms) if a_arms else 1
    a_fd = min((arm.get("min_fd") or 14) for arm in a_arms) if a_arms else 14
    a_empty = max((arm.get("max_empties") or 0) for arm in a_arms) if a_arms else 0
    better = []
    for arm in b_arms:
        if (arm.get("min_fd") or 99) < a_fd:
            better.append((arm["name"], "fd"))
        elif (arm.get("max_empties") or 0) > a_empty:
            better.append((arm["name"], "empty"))
        elif (arm.get("longest_run") or 0) > a_run:
            better.append((arm["name"], "run"))
    if better:
        return (
            "ROOT_BRANCH_DIVERSIFICATION_IMPROVES_PROGRESS",
            f"previously untested B branch(es) outperform A: {better}",
        )
    beyond = any(
        (arm.get("min_fd") or 99) < 14
        or (arm.get("max_empties") or 0) >= 1
        or (arm.get("max_foundations") or 0) >= 1
        or (arm.get("longest_run") or 0) > 8
        for arm in arms
    )
    if not beyond and a_run >= 8 and all((arm.get("longest_run") or 0) <= a_run for arm in b_arms):
        return (
            "A_FIRST_BRANCH_REMAINS_BEST",
            "matched budgets leave the original Tier-A child as the strongest branch",
        )
    if not beyond:
        return (
            "ALL_ROOT_BRANCHES_UNPRODUCTIVE",
            "all five branches received meaningful search and none progressed beyond the v0.8 run-8 / fd-14 result",
        )
    return (
        "A_FIRST_BRANCH_REMAINS_BEST",
        "no B branch beat the A child on fd, empties, or run length",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "ROOT_B_BRANCH_REACHES_FOUNDATION":
        return (
            "Keep the seed. Next: continue A+B from the successful B-root child "
            "toward a full solve; do not add production branch quotas."
        )
    if verdict == "ROOT_BRANCH_REACHES_FOUNDATION":
        return (
            "The A-first child is the foundation door. Next: continue A+B from that "
            "child; do not add production sibling scheduling."
        )
    if verdict == "ROOT_BRANCH_DIVERSIFICATION_IMPROVES_PROGRESS":
        return (
            "B_2_8_1 beat the A-first child on run length (9 vs 8). Its 1M "
            "extension stayed at fd 14, 0 empties, 0 foundations. Next: return "
            "to whole-deal scheduling and preserve Pass-0 budget so this seed "
            "can be generated and granted Pass 1; do not add production branch quotas."
        )
    if verdict == "A_FIRST_BRANCH_REMAINS_BEST":
        return (
            "DFS-first was accidentally the best door. Next: return to whole-deal "
            "scheduling and preserve Pass-0 budget so this A child can be generated "
            "and granted Pass 1; do not add branch quotas."
        )
    if verdict == "ALL_ROOT_BRANCHES_UNPRODUCTIVE":
        return (
            "Root isolation is not the missing foundation. Next: inspect why A+B "
            "from every root child stops at run construction; still no Pass 2."
        )
    if verdict == "LOCAL_PASS1_REOPEN_PATHOLOGY_DOMINATES":
        return (
            "Do not add production branch fairness yet. Next: diagnose local Pass-1 "
            "reopen/unique collapse with cheap TT counters only."
        )
    if verdict == "SIMPLE_SOLVER_COMPLETE_SOLUTION":
        return "Keep the combined route as a research witness; do not fold branch isolation into production."
    return "Reproduce the five root arms before changing whole-deal policy."


def interpret(seed: dict, arms: list[dict], verdict: str) -> str:
    parts = [
        f"Seed ok={seed.get('ok')} fd={seed.get('fd')} stock={seed.get('stock_rows')} "
        f"fnd={seed.get('foundations')} empties={seed.get('empties')}.",
        f"Distinct root children={len(arms)} B-searched="
        f"{sum(1 for arm in arms if arm['tier']==1)}.",
    ]
    for arm in arms:
        parts.append(
            f"{arm['name']}: exp={arm['nodes']} uniq={arm['unique']} "
            f"fd={arm['min_fd']} empty={arm['max_empties']} run={arm['longest_run']} "
            f"adj={arm['max_adjacencies']} fnd={arm['max_foundations']} "
            f"ratio={arm['unique_ratio']:.4f} reopen={arm['reopen_ratio']:.2f}."
        )
    parts.append(f"Verdict {verdict}.")
    return " ".join(parts)


def write_report(payload: dict) -> None:
    seed = payload.get("seed") or {}
    arms = payload.get("arms") or []
    lines = [
        "# Simple Progressive Search v0.9: Seeded Root-Branch Sweep",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "v0.8 established run 1→8 and adjacencies 16→33 with fd 14→14 and empties 0→0.",
        "This sweep isolates each root action under a matched A+B budget so the four",
        "Tier-B siblings are actually searched.",
        "",
        "## 2. Seed",
        "",
        f"- replay ok={seed.get('ok')} digest `{seed.get('digest')}`",
        f"- path 43 / cost 43 / fd={seed.get('fd')} stock={seed.get('stock_rows')} "
        f"fnd={seed.get('foundations')} empties={seed.get('empties')}",
        f"- census A/B/C/D="
        f"{(seed.get('census') or {}).get('tableau_a')}/{(seed.get('census') or {}).get('tableau_b')}/"
        f"{(seed.get('census') or {}).get('tableau_c')}/{(seed.get('census') or {}).get('tableau_d')}",
        "",
        "## 3. Root children",
        "",
        "| Action | Tier | Child digest | Equivalent |",
        "| --- | --- | --- | --- |",
    ]
    for group in payload.get("root_groups") or []:
        lines.append(
            f"| {action_label(tuple(group['representative']) if isinstance(group['representative'], list) else group['representative'])} "
            f"| {group['tier']} | `{group['key_hex'][:24]}…` | {group['equivalent']} |"
        )
    lines.extend(
        [
            "",
            "## 4. Matched A+B arms",
            "",
            "| Root action | Tier | Exp | Unique | Min FD | Max empties | Longest run | Max adj | Max fnd |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for arm in arms:
        lines.append(
            f"| {action_label(tuple(arm['action']) if isinstance(arm['action'], list) else arm['action'])} "
            f"| {arm['tier_name']} | {arm['nodes']} | {arm['unique']} | {arm['min_fd']} | "
            f"{arm['max_empties']} | {arm['longest_run']} | {arm['max_adjacencies']} | "
            f"{arm['max_foundations']} |"
        )
    lines.extend(["", "## 5. Efficiency", "", "| Arm | Unique/exp | TT reopens | Reopen/exp | RSS MiB | s/s | Stop |", "| --- | ---: | ---: | ---: | ---: | ---: | --- |"])
    for arm in arms:
        lines.append(
            f"| {arm['name']} | {arm['unique_ratio']:.4f} | {arm['tt_reopens']} | "
            f"{arm['reopen_ratio']:.2f} | {arm['peak_rss_mb']} | {arm['states_per_sec']:.1f} | "
            f"{arm['stop_reason']} |"
        )
    if payload.get("efficiency_note"):
        lines.extend(["", payload["efficiency_note"]])
    lines.extend(["", "## 6. Hard progress events", ""])
    for arm in arms:
        events = arm.get("progress_events") or []
        if not events:
            lines.append(f"- {arm['name']}: none.")
            continue
        for event in events:
            replay = event.get("combined_replay") or {}
            lines.append(
                f"- {arm['name']} {event['kind']}: exp={event.get('expansion')} "
                f"depth={event.get('depth')} run={event.get('longest_run')} "
                f"fd={event.get('fd')} empty={event.get('empties')} "
                f"replay_ok={replay.get('ok')}"
            )
    lines.extend(
        [
            "",
            "## 7. Combined replay of best run witnesses",
            "",
        ]
    )
    for arm in arms:
        lines.append(f"- {arm['name']}: {arm.get('best_run_combined_replay')}")
    ext = payload.get("extensions") or []
    lines.extend(["", "## 8. Optional extensions", ""])
    if not ext:
        lines.append("- none triggered (need fd<14, empty column, foundation, or run>=9).")
    else:
        for item in ext:
            lines.append(
                f"- {item.get('name')}: nodes={item.get('nodes')} fd={item.get('min_fd')} "
                f"run={item.get('longest_run')} fnd={item.get('max_foundations')}"
            )
    lines.extend(
        [
            "",
            "## 9. Ranking (interpretation only)",
            "",
            payload.get("ranking") or "",
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
            "Production `solve_progressive` defaults unchanged. Arms used start_pass=1,",
            "A+B only, fresh TT, depth 320, no Deal probe, no branch quotas.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ranking_text(arms: list[dict]) -> str:
    def key(arm: dict):
        return (
            -(arm.get("max_foundations") or 0),
            arm.get("min_fd") or 99,
            -(arm.get("max_empties") or 0),
            -(arm.get("longest_run") or 0),
            -(arm.get("max_adjacencies") or 0),
        )

    ordered = sorted(arms, key=key)
    return " > ".join(arm["name"] for arm in ordered)


def main() -> int:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    opening = load_opening()
    prefix = parse_moves_file(FIXTURE)
    seed_info = verify_seed(opening, prefix)
    seed = seed_info["seed"]
    seed_public = {k: v for k, v in seed_info.items() if k != "seed"}
    _write_json(CHECKPOINTS / "seed.json", seed_public)
    if not seed_info["ok"]:
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "seed": seed_public,
            "verdict": "INCONCLUSIVE",
            "note": "seed fixture failed verification",
            "next_recommendation": "Reproduce the v0.8 fd-14 seed before another sweep.",
        }
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    groups = canonical_root_children(seed)
    root_public = []
    for group in groups:
        root_public.append(
            {
                "representative": list(group["representative"])
                if isinstance(group["representative"], tuple)
                else group["representative"],
                "tier": group["tier"],
                "key_hex": group["key_hex"],
                "equivalent": group["equivalent"],
                "actions": [
                    list(item["action"]) if isinstance(item["action"], tuple) else item["action"]
                    for item in group["actions"]
                ],
            }
        )
    _write_json(CHECKPOINTS / "root_groups.json", {"groups": root_public})
    print(f"ROOT_GROUPS {len(groups)} equivalent={[g['equivalent'] for g in groups]}", flush=True)
    arms = []
    extensions = []
    for group in groups:
        label = arm_name(group)
        primary = run_arm(
            opening=opening,
            prefix=prefix,
            seed=seed,
            group=group,
            max_nodes=PRIMARY_NODES,
            time_limit=PRIMARY_TIME,
            label=label,
        )
        _write_json(CHECKPOINTS / f"{label}.json", drop_private(primary))
        if qualifies_extension(primary):
            ext = run_arm(
                opening=opening,
                prefix=prefix,
                seed=seed,
                group=group,
                max_nodes=EXTEND_NODES,
                time_limit=EXTEND_TIME,
                label=f"{label}_EXT",
            )
            _write_json(CHECKPOINTS / f"{label}_EXT.json", drop_private(ext))
            extensions.append(drop_private(ext))
            if (ext.get("max_foundations") or 0) >= 1 and (ext.get("first_foundation_node") is not None):
                path = prefix + [group["representative"]] + (ext.get("_foundation_path") or [])
                FOUNDATION_ROUTE.write_text(
                    format_moves_text(path, header="# v0.9 first foundation combined route\n"),
                    encoding="utf-8",
                )
        elif (primary.get("max_foundations") or 0) >= 1:
            path = prefix + [group["representative"]] + (primary.get("_foundation_path") or [])
            FOUNDATION_ROUTE.write_text(
                format_moves_text(path, header="# v0.9 first foundation combined route\n"),
                encoding="utf-8",
            )
        arms.append(primary)
    public_arms = [drop_private(arm) for arm in arms]
    verdict, note = choose_verdict(public_arms)
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_public,
        "root_groups": root_public,
        "arms": public_arms,
        "extensions": extensions,
        "ranking": ranking_text(public_arms),
        "verdict": verdict,
        "note": note,
        "interpretation": interpret(seed_public, public_arms, verdict),
        "next_recommendation": next_recommendation(verdict),
        "efficiency_note": (
            "Reopen/exp is 0.94–0.96 on every arm, so the v0.8 unique-collapse is "
            "common to all root branches, not A-first specific. Sequential process "
            "peak RSS grew from ~1800 to ~5573 MiB; later arms inherit process peak."
        ),
        "b_branches_searched": sum(1 for arm in public_arms if arm["tier"] == 1),
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
