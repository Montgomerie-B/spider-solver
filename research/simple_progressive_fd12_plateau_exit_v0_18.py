#!/usr/bin/env python3
"""v0.18: fd12 plateau exit audit."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_post_deal_audit import census_legal_by_tier, exposed_run_metrics
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import (
    empty_column_indices,
    empty_transition_events,
    engine_tableau_actions,
    face_down_count,
    first_empty_use_on_path,
    layered_reachability,
    plateau_reachability,
    post_stock_identity,
    stock0_tableau_classifier_complete,
)

EXPERIMENT = "simple_progressive_fd12_plateau_exit_v0_18"
BASE_SHA = "3392f920d3d0bcffecb20c8c5dbd7182f83afd4e"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "fd11_exit_classes.jsonl"
VIABLE = ROOT / "solutions" / "4925153_simple_v0_18_viable_fd11.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_18_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_18_first_foundation.moves.txt"
FD12_HEX = (
    "53504b3101000000040b3a2c360835042302310b0d1c3b1a29040115191b112800032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
DEAD_HEX = (
    "53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
EXPECTED_DEAD = 1728


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def inspect_state(state: SpiderState) -> dict:
    census = census_legal_by_tier(state)
    runs = exposed_run_metrics(state)
    return {
        "fd": face_down_count(state),
        "stock": len(state.stock),
        "foundations": len(state.foundations),
        "empties": list(empty_column_indices(state)),
        "longest_run": runs["longest_exposed_same_suit_run"],
        "adjacencies": runs["exposed_same_suit_adjacencies"],
        "blocks": runs["movable_same_suit_blocks"],
        "legal": census["legal"],
        "a": census["a"],
        "b": census["b"],
        "c": census["c"],
        "d": census["d"],
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": post_stock_identity(state).hex() if not state.stock else None,
    }


def workspace_on_path(root: SpiderState, actions: list) -> dict:
    first_use = first_empty_use_on_path(root, actions)
    seq = [list(empty_column_indices(root))]
    events: list[str] = []
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
    return {
        "start_empties": seq[0],
        "end_empties": seq[-1],
        "empty_sequence": seq,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "second_empty": events.count("SECOND_EMPTY"),
        "first_empty_use": first_use,
        "events": events,
        "empties_before_reveal": seq[-2] if len(seq) >= 2 else seq[0],
        "empties_after_reveal": seq[-1],
    }


def replay_full(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        for action in part:
            if action == ("deal",) or action == ["deal"]:
                combined.append(("deal",))
            else:
                combined.append(tuple(action))
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        info = inspect_state(end)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in combined],
            **info,
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined), "full_actions": []}


def save_route(path: Path, header: str, actions) -> None:
    path.write_text(format_moves_text(actions, header=header), encoding="utf-8")


def compact_search(result) -> dict:
    return {
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "stop_reason": result.stop_reason,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_empties": result.max_empties,
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "classifier_surprises": getattr(result, "classifier_surprises", 0),
        "first_depth": getattr(result, "first_depth", {}),
        "source_count": getattr(result, "source_count", 1),
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("classifier_surprise"):
        return "CLASSIFIER_CONTRACT_SURPRISE", payload["classifier_surprise"]
    if payload.get("foundation"):
        return "FD12_PLATEAU_REACHES_FOUNDATION", "the fd12 plateau or an fd11 exit reached a replay-valid foundation"
    if payload.get("fd10"):
        return "FD12_PLATEAU_FINDS_VIABLE_FD11", "a new fd11 exit outside the known dead region reached fd10"
    phase1 = payload.get("phase1") or {}
    new_n = payload.get("new_exit_classes") or 0
    exhausted = phase1.get("exhausted")
    if not exhausted and phase1.get("stop_reason") in ("unique limit", "time limit", "rss abort"):
        return "FD12_PLATEAU_ITSELF_STATE_EXPLOSION", "resource limits bound the fd12 plateau before exhaustion"
    phase2 = payload.get("phase2")
    if new_n > 0 and phase2 and phase2.get("stop_reason") in ("unique limit", "time limit", "rss abort"):
        return (
            "FD11_NEW_EXIT_CONTINUATION_STATE_EXPLOSION",
            "new fd11 exits exist but their continuation hit resource limits",
        )
    if new_n > 0:
        return (
            "FD12_PLATEAU_HAS_NEW_FD11_EXITS_BUT_THEY_STALL",
            "new fd11 exit classes exist but their reachable region has no fd10/foundation",
        )
    if exhausted and new_n == 0:
        return (
            "FD12_PLATEAU_ONLY_EXITS_TO_DEAD_FD11",
            "the fd12 plateau exhausts and every fd11 exit belongs to the proven dead region",
        )
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict == "FD12_PLATEAU_REACHES_FOUNDATION":
        return (
            "The fd12 plateau produces a foundation. Next: restart the reveal ratchet from that "
            "witness; do not add a heuristic."
        )
    if verdict == "FD12_PLATEAU_FINDS_VIABLE_FD11":
        return (
            "A live fd11 exit exists. Next: restart the reveal ratchet from that checkpoint; "
            "do not add a heuristic and do not add two-move slack."
        )
    if verdict == "FD12_PLATEAU_HAS_NEW_FD11_EXITS_BUT_THEY_STALL":
        return (
            "This minimum-depth fd12 cannot reach fd10: its plateau exhausts, and every fd11 "
            "exit — including those outside the original 1,728-state dead region — exhausts "
            "without fd10 or a foundation. Next: backtrack one hard-progress level and look "
            "for a different fd12 checkpoint; do not add primitive slack around this same fd12 state."
        )
    if verdict == "FD12_PLATEAU_ONLY_EXITS_TO_DEAD_FD11":
        return (
            "This minimum-depth fd12 cannot reach fd10 by any legal post-stock continuation. "
            "Next: backtrack one hard-progress level and look for a different fd12 checkpoint; "
            "do not add primitive slack around this same fd12 state."
        )
    if verdict == "FD12_PLATEAU_ITSELF_STATE_EXPLOSION":
        return "Do not raise limits here. Report the bounded plateau and stop."
    if verdict == "FD11_NEW_EXIT_CONTINUATION_STATE_EXPLOSION":
        return "Do not raise limits here. Report the partial new-exit continuation and stop."
    if verdict == "CLASSIFIER_CONTRACT_SURPRISE":
        return "Stop. An engine-legal stock0 tableau action fell outside A+B+C. Do not silently compensate."
    return "Reproduce the fd12 plateau audit before changing checkpoint policy."


def write_report(payload: dict) -> None:
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2")
    fd12 = payload.get("fd12") or {}
    dead = payload.get("dead_region") or {}
    lines = [
        "# Simple Progressive Search v0.18: FD12 Plateau Exit Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "The question is whether the minimum-depth fd12 checkpoint can be rearranged, while remaining",
        "at fd12, into a reveal whose fd11 child lies outside the proven-dead fd11 region.",
        "Production `pack_state` / `solve_progressive` are unchanged. Post-stock column symmetry is",
        "research-only. Dead-region pruning is measurement-only and is not integrated.",
        "",
        "## 2. FD12 root",
        "",
        f"- replay_ok={fd12.get('replay_ok')} path={fd12.get('path_length')} cost={fd12.get('cost')} "
        f"fd={fd12.get('fd')} stock={fd12.get('stock')} fnd={fd12.get('foundations')} "
        f"empties={fd12.get('empties')} run={fd12.get('longest_run')}",
        f"- ordered digest: `{fd12.get('ordered_digest')}`",
        f"- symmetry digest: `{fd12.get('symmetry_digest')}`",
        "",
        "## 3. Dead fd11 region",
        "",
        f"- unique={dead.get('unique')} expected={EXPECTED_DEAD} exhausted={dead.get('exhausted')} "
        f"min_fd={dead.get('min_fd')} empty={dead.get('max_empties')} fnd={dead.get('max_foundations')} "
        f"surprises={dead.get('classifier_surprises')} elapsed={dead.get('elapsed_s')}",
        "",
        "Why this set may be pruned: fd cannot increase; stock is empty and cannot return;",
        "the region is completely exhausted over all legal tableau play; it contains no fd10 and",
        "no foundation. Entering it proves this continuation cannot make further hard progress.",
        "This pruning is exact for this bounded graph only.",
        "",
        f"- stock0 A+B+C complete on fd12: {payload.get('classifier_fd12_complete')}",
        f"- stock0 A+B+C complete on dead fd11: {payload.get('classifier_dead_complete')}",
        "",
        "## 4. Phase 1 — fd12 plateau",
        "",
        f"- exhausted={p1.get('exhausted')} stop={p1.get('stop_reason')} unique={p1.get('unique')} "
        f"generated={p1.get('generated')} dups={p1.get('duplicate_skips')} "
        f"max_depth={p1.get('completed_generated_depth')} elapsed={p1.get('elapsed_s')} "
        f"rss={p1.get('peak_rss_mb')}",
        f"- empty0={p1.get('empty0')} empty1={p1.get('empty1')} empty_ge2={p1.get('empty_ge2')} "
        f"max_empties={p1.get('max_empties')} max_run={p1.get('max_run')} "
        f"max_adj={p1.get('max_adjacencies')} max_blocks={p1.get('max_blocks')}",
        f"- classifier_surprises={p1.get('classifier_surprises')}",
        "",
        f"- fd11 exit edges={payload.get('exit_edges')} distinct classes={payload.get('exit_classes')} "
        f"known_dead={payload.get('known_dead_exit_classes')} new={payload.get('new_exit_classes')} "
        f"earliest_new_depth={payload.get('earliest_new_exit_depth')}",
        "",
        "## 5. Direct dead exit vs first new exit",
        "",
        "| Metric | Direct dead exit | New exit |",
        "|---|---:|---:|",
    ]
    table = payload.get("comparison") or {}
    keys = [
        ("start_fd", "Start fd"),
        ("plateau_setup_moves", "Plateau setup moves"),
        ("fd_after_reveal", "FD after reveal"),
        ("empties_before_reveal", "Empties before reveal"),
        ("empties_after_reveal", "Empties after reveal"),
        ("run", "Run"),
        ("legal", "Legal actions"),
        ("in_known_dead_region", "In known dead region"),
        ("reaches_fd10", "Reaches fd10"),
    ]
    for field, label in keys:
        pair = table.get(field) or {}
        lines.append(f"| {label} | {pair.get('direct')} | {pair.get('new')} |")
    lines.extend(["", "## 6. Phase 2 — new fd11 continuation", ""])
    if not p2:
        lines.append(f"- skipped: {payload.get('phase2_skip_reason')}")
    else:
        lines.append(
            f"- sources={p2.get('source_count')} unique={p2.get('unique')} stop={p2.get('stop_reason')} "
            f"min_fd={p2.get('min_fd')} fnd={p2.get('max_foundations')} elapsed={p2.get('elapsed_s')} "
            f"rss={p2.get('peak_rss_mb')}"
        )
        lines.append(f"- fd10={payload.get('fd10')} foundation={payload.get('foundation')}")
    lines.extend(
        [
            "",
            "## 7. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Production pack_state and solve_progressive are unchanged.",
            "Two-move slack was not searched. The quotient and dead-set pruning are not integrated.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    fd12_actions = parse_moves_file(FD12_FIXTURE)
    fd12 = opening.clone()
    fd12_cost = replay_actions(fd12, fd12_actions)
    fd12_info = inspect_state(fd12)
    fd12_ok = (
        pack_state(fd12).hex() == FD12_HEX
        and len(fd12_actions) == 110
        and fd12_cost == 110
        and fd12_info["fd"] == 12
        and fd12_info["stock"] == 0
        and fd12_info["foundations"] == 0
        and fd12_info["empties"] == []
        and fd12_info["longest_run"] == 6
    )
    fd12_info.update({"replay_ok": fd12_ok, "path_length": len(fd12_actions), "cost": fd12_cost})
    print(f"FD12_OK {fd12_ok} digest={fd12_info['ordered_digest'][:16]}", flush=True)
    if not fd12_ok:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "fd12 fixture failed", "fd12": fd12_info}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1

    dead_actions = parse_moves_file(DEAD_FD11)
    dead = opening.clone()
    replay_actions(dead, dead_actions)
    assert pack_state(dead).hex() == DEAD_HEX
    clf_fd12 = stock0_tableau_classifier_complete(fd12)
    clf_dead = stock0_tableau_classifier_complete(dead)
    print(
        f"CLASSIFIER fd12_complete={clf_fd12['complete']} dead_complete={clf_dead['complete']}",
        flush=True,
    )
    classifier_surprise = None
    if not clf_fd12["complete"] or not clf_dead["complete"]:
        classifier_surprise = (
            f"engine-legal stock0 tableau action outside A+B+C: "
            f"fd12={clf_fd12} dead={clf_dead}"
        )

    print("DEAD_REGION exhaust", flush=True)
    dead_run = layered_reachability(
        dead,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=60.0,
        rss_abort_mb=4 * 1024.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
        checkpoints=(),
    )
    dead_region = set(dead_run.visited_identity_hex)
    dead_payload = {
        **compact_search(dead_run),
        "exhausted": dead_run.stop_reason == "frontier empty",
        "size": len(dead_region),
        "matches_expected": dead_run.unique == EXPECTED_DEAD,
    }
    print(
        f"DEAD_REGION unique={dead_run.unique} exhausted={dead_payload['exhausted']} "
        f"surprises={dead_run.classifier_surprises}",
        flush=True,
    )
    if dead_run.classifier_surprises:
        classifier_surprise = f"dead-region search saw {dead_run.classifier_surprises} classifier-D tableau actions"

    print("PHASE1 fd12 plateau", flush=True)
    plateau = plateau_reachability(
        fd12,
        plateau_fd=12,
        identity_fn=post_stock_identity,
        max_unique=1_500_000,
        time_limit_s=1800.0,
        rss_abort_mb=4 * 1024.0,
        checkpoints=(1, 2, 4, 8, 12, 16, 20, 32, 48, 64),
    )
    if plateau.classifier_surprises:
        classifier_surprise = f"plateau search saw {plateau.classifier_surprises} classifier-D tableau actions"
    print(
        f"PHASE1 unique={plateau.unique} stop={plateau.stop_reason} exhausted={plateau.exhausted} "
        f"exits={plateau.exit_classes} edges={plateau.exit_edges} elapsed={plateau.elapsed_s:.1f}",
        flush=True,
    )

    known = []
    new = []
    for rec in plateau.exits:
        rec = dict(rec)
        rec["class"] = "KNOWN_DEAD_EXIT" if rec["symmetry_digest"] in dead_region else "NEW_FD11_EXIT"
        if rec["class"] == "KNOWN_DEAD_EXIT":
            known.append(rec)
        else:
            rec["workspace"] = workspace_on_path(fd12, [tuple(a) for a in rec["actions"]])
            new.append(rec)
    known.sort(key=lambda r: r["depth"])
    new.sort(key=lambda r: r["depth"])
    EXITS_JSONL.write_text(
        "\n".join(json.dumps(rec, sort_keys=True) for rec in known + new) + ("\n" if plateau.exits else ""),
        encoding="utf-8",
    )

    direct = None
    dead_ident = post_stock_identity(dead).hex()
    for rec in known:
        if rec["symmetry_digest"] == dead_ident:
            direct = rec
            break
    if direct is None and known:
        direct = known[0]
    first_new = new[0] if new else None

    def side(rec, reaches=None):
        if rec is None:
            return None
        return {
            "depth": rec.get("depth"),
            "empties": rec.get("empties"),
            "parent_empties": rec.get("parent_empties"),
            "run": rec.get("longest_run"),
            "legal": rec.get("legal"),
            "in_dead": rec.get("class") == "KNOWN_DEAD_EXIT",
        }

    comparison = {
        "start_fd": {"direct": 12, "new": 12 if first_new else None},
        "plateau_setup_moves": {
            "direct": 0 if direct and direct.get("depth") == 1 else (None if not direct else direct.get("depth") - 1),
            "new": None if not first_new else first_new["depth"] - 1,
        },
        "fd_after_reveal": {"direct": 11 if direct else None, "new": 11 if first_new else None},
        "empties_before_reveal": {
            "direct": None if not direct else direct.get("parent_empties"),
            "new": None if not first_new else first_new.get("parent_empties"),
        },
        "empties_after_reveal": {
            "direct": None if not direct else direct.get("empties"),
            "new": None if not first_new else first_new.get("empties"),
        },
        "run": {
            "direct": None if not direct else direct.get("longest_run"),
            "new": None if not first_new else first_new.get("longest_run"),
        },
        "legal": {
            "direct": None if not direct else direct.get("legal"),
            "new": None if not first_new else first_new.get("legal"),
        },
        "in_known_dead_region": {"direct": True if direct else None, "new": False if first_new else None},
        "reaches_fd10": {"direct": False, "new": None},
    }

    foundation = None
    fd10_payload = None
    viable = None
    phase2 = None
    phase2_skip = None
    if plateau.foundation_witness:
        local = [tuple(a) for a in plateau.foundation_witness["actions"]]
        foundation = {
            **plateau.foundation_witness,
            **replay_full(opening, [fd12_actions, local]),
        }
        if foundation.get("ok"):
            save_route(
                FOUNDATION_FIXTURE,
                "# v0.18 fd12-plateau foundation\n",
                fd12_actions + local,
            )
    if plateau.fd_le_10_witness:
        print(
            f"UNEXPECTED fd<=10 from plateau depth={plateau.fd_le_10_witness.get('depth')} "
            f"fd={plateau.fd_le_10_witness.get('fd')}",
            flush=True,
        )

    if new and not foundation:
        print(f"PHASE2 new-exit continuation sources={len(new)}", flush=True)
        sources = []
        origin_paths = []
        for rec in new:
            st = fd12.clone()
            path = [tuple(a) for a in rec["actions"]]
            replay_actions(st, path)
            sources.append(st)
            origin_paths.append(path)
        cont = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=10_000,
            max_unique=1_000_000,
            time_limit_s=1200.0,
            rss_abort_mb=4 * 1024.0,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            stop_fd=10,
            checkpoints=(4, 8, 12, 16, 24, 32),
        )
        phase2 = compact_search(cont)
        print(
            f"PHASE2 unique={cont.unique} stop={cont.stop_reason} min_fd={cont.min_fd} "
            f"fnd={cont.max_foundations} elapsed={cont.elapsed_s:.1f}",
            flush=True,
        )
        if cont.classifier_surprises:
            classifier_surprise = f"phase2 search saw {cont.classifier_surprises} classifier-D tableau actions"
        if "foundation" in cont.witnesses:
            w = cont.witnesses["foundation"]
            origin = w.get("origin") or 0
            prefix_local = list(origin_paths[origin])
            local = [tuple(a) for a in w.get("actions") or []]
            foundation = {
                **w,
                "origin": origin,
                **replay_full(opening, [fd12_actions, prefix_local, local]),
            }
            if foundation.get("ok"):
                save_route(
                    FOUNDATION_FIXTURE,
                    "# v0.18 new-exit foundation\n",
                    fd12_actions + prefix_local + local,
                )
        if "fd_le_10" in cont.witnesses:
            w = cont.witnesses["fd_le_10"]
            origin = w.get("origin") or 0
            prefix_local = list(origin_paths[origin])
            local = [tuple(a) for a in w.get("actions") or []]
            fd10_payload = {
                **w,
                "origin": origin,
                **replay_full(opening, [fd12_actions, prefix_local, local]),
            }
            if fd10_payload.get("ok"):
                save_route(
                    FD10_FIXTURE,
                    "# v0.18 new-exit fd10\n",
                    fd12_actions + prefix_local + local,
                )
                viable = {
                    "origin": origin,
                    "exit": new[origin],
                    **replay_full(opening, [fd12_actions, prefix_local]),
                }
                save_route(
                    VIABLE,
                    "# v0.18 first viable new fd11 exit\n",
                    fd12_actions + prefix_local,
                )
        comparison["reaches_fd10"]["new"] = bool(fd10_payload and fd10_payload.get("ok"))
    elif not new:
        phase2_skip = "no NEW_FD11_EXIT classes"
        comparison["reaches_fd10"]["new"] = False
    else:
        phase2_skip = "foundation already found on the plateau"

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "fd12": fd12_info,
        "dead_region": dead_payload,
        "classifier_fd12_complete": clf_fd12["complete"],
        "classifier_dead_complete": clf_dead["complete"],
        "classifier_fd12": clf_fd12,
        "classifier_dead": clf_dead,
        "classifier_surprise": classifier_surprise,
        "phase1": {
            **compact_search(plateau),
            "exhausted": plateau.exhausted,
            "exit_edges": plateau.exit_edges,
            "exit_classes": plateau.exit_classes,
            "empty0": plateau.empty0,
            "empty1": plateau.empty1,
            "empty_ge2": plateau.empty_ge2,
            "max_run": plateau.max_run,
            "max_adjacencies": plateau.max_adjacencies,
            "max_blocks": plateau.max_blocks,
            "surprise_samples": plateau.surprise_samples,
            "fd_le_10_witness": plateau.fd_le_10_witness,
        },
        "exit_edges": plateau.exit_edges,
        "exit_classes": plateau.exit_classes,
        "known_dead_exit_classes": len(known),
        "new_exit_classes": len(new),
        "earliest_known_dead_depth": None if not known else known[0]["depth"],
        "earliest_new_exit_depth": None if not new else new[0]["depth"],
        "direct_dead_exit": None if not direct else {k: direct[k] for k in direct if k != "workspace"},
        "new_exits": [
            {k: rec[k] for k in rec if k != "actions" or True}
            for rec in new[:20]
        ],
        "comparison": comparison,
        "phase2": phase2,
        "phase2_skip_reason": phase2_skip,
        "fd10": bool(fd10_payload and fd10_payload.get("ok")),
        "foundation": bool(foundation and foundation.get("ok")),
        "fd10_witness": fd10_payload,
        "foundation_witness": foundation,
        "viable_fd11": viable,
        "production_unchanged": True,
        "two_move_slack": False,
        "quotient_integrated": False,
        "dead_pruning_integrated": False,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. plateau unique={plateau.unique} exhausted={plateau.exhausted} "
        f"exit_classes={plateau.exit_classes} known_dead={len(known)} new={len(new)} "
        f"fd10={payload['fd10']} foundation={payload['foundation']}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
