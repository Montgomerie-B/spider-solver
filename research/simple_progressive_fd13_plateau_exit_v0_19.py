#!/usr/bin/env python3
"""v0.19: fd13 plateau alternative-fd12 exit audit."""

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

EXPERIMENT = "simple_progressive_fd13_plateau_exit_v0_19"
BASE_SHA = "b9927e50596996903aed3e0acd148fe6f84676ab"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD13_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "fd12_exit_classes.jsonl"
DEAD_JSONL = OUT_DIR / "known_dead_from_fd12.jsonl"
VIABLE = ROOT / "solutions" / "4925153_simple_v0_19_viable_fd12.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_19_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_19_first_foundation.moves.txt"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
FD12_HEX = (
    "53504b3101000000040b3a2c360835042302310b0d1c3b1a29040115191b112800032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
EXPECTED_FD12_PLATEAU = 20736


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
        "known_dead_prunes": getattr(result, "known_dead_prunes", 0),
        "first_depth": getattr(result, "first_depth", {}),
        "source_count": getattr(result, "source_count", 1),
    }


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("foundation"):
        return "FD13_PLATEAU_REACHES_FOUNDATION", "a replay-valid foundation is reached from this fd13 region"
    if payload.get("fd10"):
        return "FD13_PLATEAU_FINDS_VIABLE_FD12", "an fd12 exit outside the known dead fd12 region reached fd10"
    phase1 = payload.get("phase1") or {}
    new_n = payload.get("new_fd12_exits") or 0
    if not phase1.get("exhausted") and phase1.get("stop_reason") in ("unique limit", "time limit", "rss abort"):
        return "FD13_PLATEAU_STATE_EXPLOSION", "resource limits bound the fd13 plateau before exhaustion"
    phase2 = payload.get("phase2")
    if new_n > 0 and phase2 and phase2.get("stop_reason") in ("unique limit", "time limit", "rss abort"):
        return (
            "NEW_FD12_CONTINUATION_STATE_EXPLOSION",
            "the fd13 plateau completed but new fd12 continuation hit resource limits",
        )
    if phase1.get("exhausted") and new_n == 0:
        return (
            "FD13_PLATEAU_ONLY_EXITS_TO_KNOWN_DEAD_FD12",
            "the plateau exhausts and every fd12 exit enters the already proven dead fd12 region",
        )
    phase2_exhausted = bool(phase2 and phase2.get("stop_reason") == "frontier empty")
    if phase1.get("exhausted") and new_n > 0 and phase2_exhausted:
        return (
            "FD13_ROOT_PROVEN_DEAD_TO_FD10",
            "the fd13 plateau and every alternative fd12 future exhaust without fd10 or a foundation",
        )
    if new_n > 0 and phase2_exhausted:
        return (
            "FD13_PLATEAU_NEW_FD12_EXITS_BUT_THEY_STALL",
            "new fd12 regions exist, but their shared reachable graph exhausts without fd10/foundation",
        )
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict == "FD13_PLATEAU_REACHES_FOUNDATION":
        return "A foundation is reachable from this fd13 region. Next: harvest that witness; do not add a heuristic."
    if verdict == "FD13_PLATEAU_FINDS_VIABLE_FD12":
        return (
            "An alternative fd12 keeps the game alive. Next: restart the reveal ratchet from that "
            "checkpoint; do not add a heuristic."
        )
    if verdict in (
        "FD13_ROOT_PROVEN_DEAD_TO_FD10",
        "FD13_PLATEAU_ONLY_EXITS_TO_KNOWN_DEAD_FD12",
        "FD13_PLATEAU_NEW_FD12_EXITS_BUT_THEY_STALL",
    ):
        return (
            "This fd13/empty1 root cannot reach fd10 under the audited legal graph. Next: a later "
            "task may backtrack one hard-progress level to an fd14 checkpoint; do not add slack "
            "or heuristics here, and do not start that fd14 search in this task."
        )
    if verdict == "FD13_PLATEAU_STATE_EXPLOSION":
        return "Do not raise limits here. Report the bounded fd13 plateau and stop."
    if verdict == "NEW_FD12_CONTINUATION_STATE_EXPLOSION":
        return "Do not raise limits here. Report the partial new-fd12 continuation and stop."
    return "Reproduce the fd13 plateau audit before changing checkpoint policy."


def write_report(payload: dict) -> None:
    p0 = payload.get("known_dead_from_fd12") or {}
    p1 = payload.get("phase1") or {}
    p2 = payload.get("phase2")
    fd13 = payload.get("fd13") or {}
    lines = [
        "# Simple Progressive Search v0.19: FD13 Plateau Alternative-FD12 Exit Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        f"FD13 root proven dead to fd10: **{payload.get('fd13_proven_dead_to_fd10')}**.",
        "",
        "Production `pack_state` / `solve_progressive` are unchanged. Post-stock column symmetry",
        "and the known-dead fd12 cache are research-only exact tools, not production features.",
        "",
        "## 2. FD13 root",
        "",
        f"- replay_ok={fd13.get('replay_ok')} path={fd13.get('path_length')} cost={fd13.get('cost')} "
        f"fd={fd13.get('fd')} stock={fd13.get('stock')} fnd={fd13.get('foundations')} "
        f"empties={fd13.get('empties')} run={fd13.get('longest_run')}",
        f"- ordered digest: `{fd13.get('ordered_digest')}`",
        f"- symmetry digest: `{fd13.get('symmetry_digest')}`",
        f"- stock0 A+B+C complete: {payload.get('classifier_fd13_complete')}",
        "",
        "## 3. Phase 0 — KNOWN_DEAD_FROM_FD12",
        "",
        f"- unique={p0.get('unique')} exhausted={p0.get('exhausted')} min_fd={p0.get('min_fd')} "
        f"fnd={p0.get('max_foundations')} empty={p0.get('max_empties')} "
        f"fd12_plateau={p0.get('fd12_plateau_classes')} expected_plateau={EXPECTED_FD12_PLATEAU} "
        f"elapsed={p0.get('elapsed_s')}",
        "",
        "## 4. Phase 1 — fd13 plateau",
        "",
        f"- exhausted={p1.get('exhausted')} stop={p1.get('stop_reason')} unique={p1.get('unique')} "
        f"generated={p1.get('generated')} dups={p1.get('duplicate_skips')} "
        f"max_depth={p1.get('completed_generated_depth')} elapsed={p1.get('elapsed_s')} "
        f"rss={p1.get('peak_rss_mb')}",
        f"- empty0={p1.get('empty0')} empty1={p1.get('empty1')} empty_ge2={p1.get('empty_ge2')} "
        f"max_empties={p1.get('max_empties')} max_run={p1.get('max_run')} "
        f"max_adj={p1.get('max_adjacencies')} max_blocks={p1.get('max_blocks')}",
        f"- fd13->fd12 edges={payload.get('exit_edges')} classes={payload.get('exit_classes')} "
        f"known_dead={payload.get('known_dead_fd12_exits')} new={payload.get('new_fd12_exits')} "
        f"earliest_new_depth={payload.get('earliest_new_fd12_depth')}",
        "",
        "## 5. Phase 2 — new fd12 continuation",
        "",
    ]
    if not p2:
        lines.append(f"- skipped: {payload.get('phase2_skip_reason')}")
    else:
        lines.append(
            f"- sources={p2.get('source_count')} unique={p2.get('unique')} stop={p2.get('stop_reason')} "
            f"min_fd={p2.get('min_fd')} fnd={p2.get('max_foundations')} "
            f"known_dead_prunes={p2.get('known_dead_prunes')} elapsed={p2.get('elapsed_s')} "
            f"rss={p2.get('peak_rss_mb')}"
        )
        lines.append(f"- fd10={payload.get('fd10')} foundation={payload.get('foundation')}")
    lines.extend(
        [
            "",
            "## 6. Exactly one next recommendation",
            "",
            payload.get("next_recommendation") or "",
            "",
            "## Integrity",
            "",
            payload.get("interpretation") or "",
            "",
            f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
            "Production pack_state and solve_progressive are unchanged.",
            "An fd14 backtrack was not started. Heuristics and slack were not added.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    fd13_actions = parse_moves_file(FD13_FIXTURE)
    fd13 = opening.clone()
    fd13_cost = replay_actions(fd13, fd13_actions)
    fd13_info = inspect_state(fd13)
    fd13_ok = (
        pack_state(fd13).hex() == FD13_HEX
        and len(fd13_actions) == 102
        and fd13_cost == 102
        and fd13_info["fd"] == 13
        and fd13_info["stock"] == 0
        and fd13_info["foundations"] == 0
        and fd13_info["empties"] == [2]
        and fd13_info["longest_run"] == 6
    )
    fd13_info.update({"replay_ok": fd13_ok, "path_length": len(fd13_actions), "cost": fd13_cost})
    print(f"FD13_OK {fd13_ok}", flush=True)
    if not fd13_ok:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "fd13 fixture failed", "fd13": fd13_info}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1

    clf_fd13 = stock0_tableau_classifier_complete(fd13)
    print(f"CLASSIFIER fd13_complete={clf_fd13['complete']}", flush=True)

    fd12_actions = parse_moves_file(FD12_FIXTURE)
    fd12 = opening.clone()
    replay_actions(fd12, fd12_actions)
    assert pack_state(fd12).hex() == FD12_HEX
    print("PHASE0 regenerate KNOWN_DEAD_FROM_FD12", flush=True)
    dead_run = layered_reachability(
        fd12,
        max_depth=10_000,
        max_unique=200_000,
        time_limit_s=180.0,
        rss_abort_mb=4 * 1024.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
        checkpoints=(8, 12, 16, 20),
    )
    plateau_keys = set()
    all_dead_hex = []
    for concrete_hex, ident_hex in zip(dead_run.visited_hex, dead_run.visited_identity_hex):
        st = unpack_state(bytes.fromhex(concrete_hex))
        fd = face_down_count(st)
        all_dead_hex.append({"symmetry_digest": ident_hex, "fd": fd, "foundations": len(st.foundations)})
        if fd == 12 and len(st.foundations) == 0:
            plateau_keys.add(ident_hex)
    DEAD_JSONL.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in all_dead_hex) + "\n",
        encoding="utf-8",
    )
    dead_identities = {bytes.fromhex(h) for h in dead_run.visited_identity_hex}
    dead_payload = {
        **compact_search(dead_run),
        "exhausted": dead_run.stop_reason == "frontier empty",
        "fd12_plateau_classes": len(plateau_keys),
        "matches_expected_plateau": len(plateau_keys) == EXPECTED_FD12_PLATEAU,
        "stock_nonzero": any(len(unpack_state(bytes.fromhex(h)).stock) for h in dead_run.visited_hex[:1]),
    }
    print(
        f"PHASE0 unique={dead_run.unique} plateau={len(plateau_keys)} exhausted={dead_payload['exhausted']} "
        f"min_fd={dead_run.min_fd} fnd={dead_run.max_foundations}",
        flush=True,
    )

    print("PHASE1 fd13 plateau", flush=True)
    plateau = plateau_reachability(
        fd13,
        plateau_fd=13,
        identity_fn=post_stock_identity,
        max_unique=2_500_000,
        time_limit_s=1800.0,
        rss_abort_mb=4 * 1024.0,
        checkpoints=(1, 2, 4, 8, 12, 16, 20, 32, 48, 64),
    )
    print(
        f"PHASE1 unique={plateau.unique} stop={plateau.stop_reason} exhausted={plateau.exhausted} "
        f"exits={plateau.exit_classes} edges={plateau.exit_edges} elapsed={plateau.elapsed_s:.1f}",
        flush=True,
    )

    known = []
    new = []
    for rec in plateau.exits:
        rec = dict(rec)
        rec["class"] = "KNOWN_DEAD_FD12" if rec["symmetry_digest"] in plateau_keys else "NEW_FD12_EXIT"
        rec["viable"] = False
        if rec["class"] == "KNOWN_DEAD_FD12":
            known.append(rec)
        else:
            rec["workspace"] = workspace_on_path(fd13, [tuple(a) for a in rec["actions"]])
            new.append(rec)
    known.sort(key=lambda r: r["depth"])
    new.sort(key=lambda r: r["depth"])
    EXITS_JSONL.write_text(
        "\n".join(json.dumps(rec, sort_keys=True) for rec in known + new) + ("\n" if plateau.exits else ""),
        encoding="utf-8",
    )

    foundation = None
    fd10_payload = None
    viable = None
    phase2 = None
    phase2_skip = None
    if plateau.foundation_witness:
        local = [tuple(a) for a in plateau.foundation_witness["actions"]]
        foundation = {**plateau.foundation_witness, **replay_full(opening, [fd13_actions, local])}
        if foundation.get("ok"):
            save_route(FOUNDATION_FIXTURE, "# v0.19 fd13-plateau foundation\n", fd13_actions + local)
    if plateau.fd_le_10_witness:
        print(
            f"UNEXPECTED fd<=11 from fd13 plateau depth={plateau.fd_le_10_witness.get('depth')} "
            f"fd={plateau.fd_le_10_witness.get('fd')}",
            flush=True,
        )

    if new and not foundation:
        print(f"PHASE2 new-fd12 continuation sources={len(new)}", flush=True)
        sources = []
        origin_paths = []
        for rec in new:
            st = fd13.clone()
            path = [tuple(a) for a in rec["actions"]]
            replay_actions(st, path)
            sources.append(st)
            origin_paths.append(path)
        cont = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=10_000,
            max_unique=2_000_000,
            time_limit_s=1800.0,
            rss_abort_mb=4 * 1024.0,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            dead_identities=dead_identities,
            stop_fd=10,
            checkpoints=(4, 8, 12, 16, 24, 32, 48),
        )
        phase2 = compact_search(cont)
        print(
            f"PHASE2 unique={cont.unique} stop={cont.stop_reason} min_fd={cont.min_fd} "
            f"fnd={cont.max_foundations} prunes={cont.known_dead_prunes} elapsed={cont.elapsed_s:.1f}",
            flush=True,
        )
        if "foundation" in cont.witnesses:
            w = cont.witnesses["foundation"]
            origin = w.get("origin") or 0
            prefix_local = list(origin_paths[origin])
            local = [tuple(a) for a in w.get("actions") or []]
            foundation = {**w, "origin": origin, **replay_full(opening, [fd13_actions, prefix_local, local])}
            if foundation.get("ok"):
                save_route(FOUNDATION_FIXTURE, "# v0.19 new-fd12 foundation\n", fd13_actions + prefix_local + local)
        if "fd_le_10" in cont.witnesses:
            w = cont.witnesses["fd_le_10"]
            origin = w.get("origin") or 0
            prefix_local = list(origin_paths[origin])
            local = [tuple(a) for a in w.get("actions") or []]
            fd10_payload = {**w, "origin": origin, **replay_full(opening, [fd13_actions, prefix_local, local])}
            if fd10_payload.get("ok"):
                save_route(FD10_FIXTURE, "# v0.19 new-fd12 fd10\n", fd13_actions + prefix_local + local)
                viable = {
                    "origin": origin,
                    "exit": {k: new[origin][k] for k in new[origin] if k != "workspace"},
                    "workspace": workspace_on_path(fd13, prefix_local + local),
                    **replay_full(opening, [fd13_actions, prefix_local]),
                }
                save_route(VIABLE, "# v0.19 first viable new fd12 exit\n", fd13_actions + prefix_local)
    elif not new:
        phase2_skip = "no NEW_FD12_EXIT classes"
    else:
        phase2_skip = "foundation already found on the fd13 plateau"

    proven = bool(
        plateau.exhausted
        and not (fd10_payload and fd10_payload.get("ok"))
        and not (foundation and foundation.get("ok"))
        and (not new or (phase2 and phase2.get("stop_reason") == "frontier empty"))
    )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "fd13": fd13_info,
        "classifier_fd13_complete": clf_fd13["complete"],
        "classifier_fd13": clf_fd13,
        "known_dead_from_fd12": dead_payload,
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
        "known_dead_fd12_exits": len(known),
        "new_fd12_exits": len(new),
        "earliest_known_dead_depth": None if not known else known[0]["depth"],
        "earliest_new_fd12_depth": None if not new else new[0]["depth"],
        "new_exits": new[:20],
        "phase2": phase2,
        "phase2_skip_reason": phase2_skip,
        "fd10": bool(fd10_payload and fd10_payload.get("ok")),
        "foundation": bool(foundation and foundation.get("ok")),
        "fd10_witness": fd10_payload,
        "foundation_witness": foundation,
        "viable_fd12": viable,
        "fd13_proven_dead_to_fd10": proven,
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
        f"Verdict {verdict}. dead_from_fd12={dead_run.unique} plateau_subset={len(plateau_keys)} "
        f"fd13_unique={plateau.unique} exhausted={plateau.exhausted} "
        f"exits={plateau.exit_classes} known_dead={len(known)} new={len(new)} "
        f"fd10={payload['fd10']} foundation={payload['foundation']} proven_dead={proven}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
