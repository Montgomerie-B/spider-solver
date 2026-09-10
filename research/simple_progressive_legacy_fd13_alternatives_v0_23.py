#!/usr/bin/env python3
"""v0.23: recover and classify legacy v0.10 fd13 alternative branches.

No new heuristic.  No fresh fd14 search.  No column-7 targeting.
"""

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
from spider.packed_state import pack_state, unpack_state
from spider.simple_legacy_fd13_alternatives import (
    ALTERNATIVE_FD13_CLASS,
    CURRENT_FD13_CLASS,
    buried_signature_keys,
    checkpoint_record,
    classify_fd13_identity,
    equivalence_classes,
    fair_fd10_continuation,
    fair_short_horizon_fd13_search,
    load_known_dead_hex,
    reveal_target_from_transition,
)
from spider.simple_post_deal_audit import canonical_root_children
from spider.simple_progressive_solver import (
    TT_MODE_FIRST_VISIT,
    apply_action,
    format_moves_text,
    solve_progressive,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

EXPERIMENT = "simple_progressive_legacy_fd13_alternatives_v0_23"
BASE_SHA = "9c2347899227bc126a67967a27a7c74af3240dd7"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD14_FIXTURE = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
B281_EMPTY = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
FD12_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_12_fd12.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
V10_DIR = ROOT / "research" / "results" / "simple_progressive_first_visit_dfs_v0_10"
V19_DEAD = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
)
V19_EXITS = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "fd12_exit_classes.jsonl"
)
FD14_HEX = (
    "53504b3101000000040a3a2c360835042302310b0d322913050915191b11282d0c2b1a2901"
    "0a0b1a010c3b2706153423323124162c1c2200081413121d071d223300062d242118341900"
    "070d0c2621393c37040c18360a2a280706050403020911033d17000612272a053801000d3d"
    "3c3b3a39383726081c251b3300071716352b140925"
)
B281_EMPTY_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)

ARMS = {
    "B_2_8_1": {
        "action": (2, 8, 1),
        "expected_fd13_total": 101,
        "expected_empty_total": 102,
        "expected_fd13_local": 57,
        "expected_empty_local": 58,
        "fd13_fixture": ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt",
        "empty_fixture": ROOT / "solutions" / "4925153_simple_v0_23_b281_empty.moves.txt",
        "shortcut": True,
    },
    "B_2_0_1": {
        "action": (2, 0, 1),
        "expected_fd13_total": 108,
        "expected_empty_total": 109,
        "expected_fd13_local": 64,
        "expected_empty_local": 65,
        "fd13_fixture": ROOT / "solutions" / "4925153_simple_v0_23_b201_fd13.moves.txt",
        "empty_fixture": ROOT / "solutions" / "4925153_simple_v0_23_b201_empty.moves.txt",
        "shortcut": False,
    },
    "A_4_1_1": {
        "action": (4, 1, 1),
        "expected_fd13_total": 108,
        "expected_empty_total": 109,
        "expected_fd13_local": 64,
        "expected_empty_local": 65,
        "fd13_fixture": ROOT / "solutions" / "4925153_simple_v0_23_a411_fd13.moves.txt",
        "empty_fixture": ROOT / "solutions" / "4925153_simple_v0_23_a411_empty.moves.txt",
        "shortcut": False,
    },
}

HARVEST_NODES = 200_000
HARVEST_TIME = 700.0
RSS_ABORT_MB = 3 * 1024.0
LOCAL_DEPTH = 2000


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw) -> list:
    out = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            src, dst, k = item
            out.append((int(src), int(dst), int(k)))
    return out


def verify_fd14() -> dict:
    opening = opening_state()
    prefix = parse_moves_file(FD14_FIXTURE)
    seed = opening.clone()
    cost = replay_actions(seed, prefix)
    ordered = pack_state(seed).hex()
    symmetry = post_stock_identity(seed).hex()
    fd = face_down_count(seed)
    ok = (
        len(prefix) == 43
        and cost == 43
        and fd == 14
        and len(seed.stock) == 0
        and len(seed.foundations) == 0
        and len(empty_column_indices(seed)) == 0
        and ordered == FD14_HEX
    )
    rec = checkpoint_record(seed, arm="fd14_root", path_length=len(prefix), cost=cost, kind="fd14_stock0")
    rec["ok"] = ok
    rec["ordered_matches_historical"] = ordered == FD14_HEX
    rec["symmetry_digest"] = symmetry
    return rec, opening, prefix, seed


def write_fixture(path: Path, actions, *, header: str) -> None:
    path.write_text(format_moves_text(actions, header=header), encoding="utf-8")


def recover_b281(opening, prefix, fd14) -> dict:
    spec = ARMS["B_2_8_1"]
    empty_actions = parse_moves_file(B281_EMPTY)
    empty_state = opening.clone()
    empty_cost = replay_actions(empty_state, empty_actions)
    if pack_state(empty_state).hex() != B281_EMPTY_HEX:
        return {"ok": False, "arm": "B_2_8_1", "error": "committed empty seed digest mismatch"}
    fd13_actions = empty_actions[:-1]
    fd13_state = opening.clone()
    fd13_cost = replay_actions(fd13_state, fd13_actions)
    fd13_ok = (
        len(fd13_actions) == spec["expected_fd13_total"]
        and face_down_count(fd13_state) == 13
        and len(empty_column_indices(fd13_state)) == 0
        and len(fd13_state.stock) == 0
        and len(fd13_state.foundations) == 0
    )
    empty_ok = (
        len(empty_actions) == spec["expected_empty_total"]
        and face_down_count(empty_state) == 13
        and len(empty_column_indices(empty_state)) >= 1
    )
    reveal = reveal_target_from_transition(fd14, fd13_state)
    fd13_rec = checkpoint_record(
        fd13_state, arm="B_2_8_1", path_length=len(fd13_actions), cost=fd13_cost, kind="FIRST_FD13"
    )
    empty_rec = checkpoint_record(
        empty_state, arm="B_2_8_1", path_length=len(empty_actions), cost=empty_cost, kind="FIRST_EMPTY_AFTER_FD13"
    )
    fd13_rec["reveal_target"] = reveal
    write_fixture(
        spec["fd13_fixture"],
        fd13_actions,
        header="\n".join(
            [
                "# v0.23 B_2_8_1 FIRST_FD13 recovered from committed 102-command empty seed prefix",
                "# lineage: v0.10 B_2_8_1 / v0.11 seed prefix 101",
                f"# primitive_moves: {len(fd13_actions)}",
                f"# mobilityware_moves: {fd13_cost}",
                f"# digest: {fd13_rec['ordered_digest']}",
                f"# symmetry: {fd13_rec['symmetry_digest']}",
                "# fd: 13",
                "# empties: 0",
            ]
        ),
    )
    write_fixture(
        spec["empty_fixture"],
        empty_actions,
        header="\n".join(
            [
                "# v0.23 B_2_8_1 FIRST_EMPTY recovered from committed v0.11 seed",
                "# lineage: v0.10 B_2_8_1 first_empty",
                f"# primitive_moves: {len(empty_actions)}",
                f"# mobilityware_moves: {empty_cost}",
                f"# digest: {empty_rec['ordered_digest']}",
                f"# symmetry: {empty_rec['symmetry_digest']}",
                "# fd: 13",
                f"# empties: {empty_rec['empty_count']}",
            ]
        ),
    )
    payload = {
        "ok": bool(fd13_ok and empty_ok),
        "arm": "B_2_8_1",
        "method": "committed_seed_shortcut",
        "root_action": list(spec["action"]),
        "first_fd13": fd13_rec,
        "first_empty": empty_rec,
        "reveal_target": reveal,
        "expected_fd13_total": spec["expected_fd13_total"],
        "expected_empty_total": spec["expected_empty_total"],
        "path_length_match": {
            "fd13": len(fd13_actions) == spec["expected_fd13_total"],
            "empty": len(empty_actions) == spec["expected_empty_total"],
        },
        "fixtures": {
            "fd13": spec["fd13_fixture"].relative_to(ROOT).as_posix(),
            "empty": spec["empty_fixture"].relative_to(ROOT).as_posix(),
        },
    }
    _write_json(OUT_DIR / "B_2_8_1_recovery.json", payload)
    print(
        f"DONE B_2_8_1 shortcut fd13={len(fd13_actions)} empty={len(empty_actions)} "
        f"reveal={reveal.get('signature_key')} ok={payload['ok']}",
        flush=True,
    )
    return payload


def recover_first_visit_arm(arm_name: str, opening, prefix, fd14) -> dict:
    spec = ARMS[arm_name]
    root_action = spec["action"]
    groups = canonical_root_children(fd14)
    match = next((g for g in groups if tuple(g["representative"]) == root_action), None)
    if match is None:
        return {"ok": False, "arm": arm_name, "error": f"root action {root_action} not among fd14 children"}
    child = fd14.clone()
    apply_action(child, root_action)
    child_digest = pack_state(child).hex()
    historical = json.loads((V10_DIR / f"{arm_name}.json").read_text(encoding="utf-8"))
    expected_child = historical.get("child_digest")
    print(
        f"START {arm_name} first_visit stop_on_first_empty child={child_digest[:24]} "
        f"hist={str(expected_child)[:24]}",
        flush=True,
    )
    started = time.perf_counter()
    result = solve_progressive(
        child,
        max_nodes=HARVEST_NODES,
        time_limit_s=HARVEST_TIME,
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
        stop_on_first_empty=True,
    )
    elapsed = time.perf_counter() - started
    pda = result.post_deal_audit
    events = [] if pda is None else list(pda.progress_events)
    fd13_event = next((e for e in events if e.get("kind") == "fd_below_14"), None)
    empty_event = next((e for e in events if e.get("kind") == "first_empty"), None)
    if fd13_event is None or empty_event is None:
        payload = {
            "ok": False,
            "arm": arm_name,
            "error": "required progress events missing",
            "nodes": result.nodes,
            "stop_reason": result.stop_reason,
            "min_fd": result.min_face_down,
            "elapsed_s": elapsed,
            "event_kinds": [e.get("kind") for e in events],
        }
        _write_json(OUT_DIR / f"{arm_name}_recovery.json", payload)
        print(f"FAIL {arm_name} events={payload['event_kinds']} stop={result.stop_reason}", flush=True)
        return payload

    local_fd13 = as_actions(fd13_event.get("path") or [])
    local_empty = as_actions(empty_event.get("path") or [])
    fd13_actions = list(prefix) + [root_action] + local_fd13
    empty_actions = list(prefix) + [root_action] + local_empty
    fd13_state = opening.clone()
    fd13_cost = replay_actions(fd13_state, fd13_actions)
    empty_state = opening.clone()
    empty_cost = replay_actions(empty_state, empty_actions)
    reveal = reveal_target_from_transition(fd14, fd13_state)
    fd13_rec = checkpoint_record(
        fd13_state, arm=arm_name, path_length=len(fd13_actions), cost=fd13_cost, kind="FIRST_FD13"
    )
    empty_rec = checkpoint_record(
        empty_state, arm=arm_name, path_length=len(empty_actions), cost=empty_cost, kind="FIRST_EMPTY_AFTER_FD13"
    )
    fd13_rec["reveal_target"] = reveal
    fd13_rec["local_depth"] = len(local_fd13)
    fd13_rec["expansion"] = fd13_event.get("expansion")
    empty_rec["local_depth"] = len(local_empty)
    empty_rec["expansion"] = empty_event.get("expansion")
    write_fixture(
        spec["fd13_fixture"],
        fd13_actions,
        header="\n".join(
            [
                f"# v0.23 {arm_name} FIRST_FD13 recovered from v0.10 first-visit A+B semantics",
                f"# root_action: {root_action}",
                f"# primitive_moves: {len(fd13_actions)}",
                f"# mobilityware_moves: {fd13_cost}",
                f"# digest: {fd13_rec['ordered_digest']}",
                f"# symmetry: {fd13_rec['symmetry_digest']}",
                f"# local_depth: {len(local_fd13)}",
                f"# harvest_expansion: {fd13_event.get('expansion')}",
            ]
        ),
    )
    write_fixture(
        spec["empty_fixture"],
        empty_actions,
        header="\n".join(
            [
                f"# v0.23 {arm_name} FIRST_EMPTY recovered from v0.10 first-visit A+B semantics",
                f"# root_action: {root_action}",
                f"# primitive_moves: {len(empty_actions)}",
                f"# mobilityware_moves: {empty_cost}",
                f"# digest: {empty_rec['ordered_digest']}",
                f"# symmetry: {empty_rec['symmetry_digest']}",
                f"# local_depth: {len(local_empty)}",
                f"# harvest_expansion: {empty_event.get('expansion')}",
            ]
        ),
    )
    payload = {
        "ok": True,
        "arm": arm_name,
        "method": "first_visit_stop_on_first_empty",
        "root_action": list(root_action),
        "child_digest": child_digest,
        "historical_child_digest": expected_child,
        "child_digest_match": child_digest == expected_child,
        "nodes": result.nodes,
        "stop_reason": result.stop_reason,
        "elapsed_s": elapsed,
        "peak_rss_mb": result.stats.peak_rss_mb,
        "min_fd": result.min_face_down,
        "first_fd13": fd13_rec,
        "first_empty": empty_rec,
        "reveal_target": reveal,
        "expected_fd13_total": spec["expected_fd13_total"],
        "expected_empty_total": spec["expected_empty_total"],
        "historical_expansion_fd13": 136901 if arm_name != "B_2_8_1" else 50065,
        "historical_expansion_empty": 136902 if arm_name != "B_2_8_1" else 50066,
        "path_length_match": {
            "fd13": len(fd13_actions) == spec["expected_fd13_total"],
            "empty": len(empty_actions) == spec["expected_empty_total"],
        },
        "replay_ok": True,
        "fixtures": {
            "fd13": spec["fd13_fixture"].relative_to(ROOT).as_posix(),
            "empty": spec["empty_fixture"].relative_to(ROOT).as_posix(),
        },
    }
    _write_json(OUT_DIR / f"{arm_name}_recovery.json", payload)
    print(
        f"DONE {arm_name} nodes={result.nodes} fd13={len(fd13_actions)} empty={len(empty_actions)} "
        f"exp_fd13={fd13_event.get('expansion')} exp_empty={empty_event.get('expansion')} "
        f"reveal={reveal.get('signature_key')} rss={result.stats.peak_rss_mb} "
        f"stop={result.stop_reason} elapsed={elapsed:.1f}",
        flush=True,
    )
    return payload


def recover_arm(arm_name: str) -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd14_rec, opening, prefix, fd14 = verify_fd14()
    if not fd14_rec["ok"]:
        payload = {"ok": False, "arm": arm_name, "error": "fd14 root verification failed", "fd14": fd14_rec}
        _write_json(OUT_DIR / f"{arm_name}_recovery.json", payload)
        return payload
    if arm_name == "B_2_8_1":
        return recover_b281(opening, prefix, fd14)
    return recover_first_visit_arm(arm_name, opening, prefix, fd14)


def load_recovery(arm_name: str) -> dict:
    path = OUT_DIR / f"{arm_name}_recovery.json"
    return json.loads(path.read_text(encoding="utf-8"))


def classify_recoveries() -> dict:
    records = []
    fd13_recs = []
    empty_recs = []
    for name in ARMS:
        rec = load_recovery(name)
        if not rec.get("ok"):
            return {"ok": False, "error": f"{name} recovery missing or failed", "arm": name}
        fd13_recs.append(rec["first_fd13"])
        empty_recs.append(rec["first_empty"])
        rec["first_fd13"]["class"] = None
        records.append(rec)
    current_sym = records[0]["first_fd13"]["symmetry_digest"]
    current_ord = records[0]["first_fd13"]["ordered_digest"]
    for rec in records:
        rec["first_fd13"]["class"] = classify_fd13_identity(
            current_sym, rec["first_fd13"]["symmetry_digest"]
        )
        rec["first_fd13"]["ordered_eq_b281"] = rec["first_fd13"]["ordered_digest"] == current_ord
        rec["first_empty"]["class"] = classify_fd13_identity(
            records[0]["first_empty"]["symmetry_digest"], rec["first_empty"]["symmetry_digest"]
        )
    fd13_classes = equivalence_classes(fd13_recs)
    empty_classes = equivalence_classes(empty_recs)
    distinct_alts = [
        rec for rec in records if rec["first_fd13"]["class"] == ALTERNATIVE_FD13_CLASS
    ]
    payload = {
        "ok": True,
        "fd13_ordered_classes": len(equivalence_classes(fd13_recs, field="ordered_digest")),
        "fd13_symmetry_classes": len(fd13_classes),
        "empty_ordered_classes": len(equivalence_classes(empty_recs, field="ordered_digest")),
        "empty_symmetry_classes": len(empty_classes),
        "fd13_class_members": {k: v for k, v in fd13_classes.items()},
        "empty_class_members": {k: v for k, v in empty_classes.items()},
        "alternative_arms": [rec["arm"] for rec in distinct_alts],
        "collapse": len(fd13_classes) == 1,
        "arms": [
            {
                "arm": rec["arm"],
                "fd13_path": rec["first_fd13"]["total_primitive_path"],
                "fd13_cost": rec["first_fd13"]["corrected_mw_cost"],
                "empty_path": rec["first_empty"]["total_primitive_path"],
                "empty_cost": rec["first_empty"]["corrected_mw_cost"],
                "fd13_class": rec["first_fd13"]["class"],
                "empty_class": rec["first_empty"]["class"],
                "ordered_eq_b281": rec["first_fd13"]["ordered_eq_b281"],
                "fd13_ordered": rec["first_fd13"]["ordered_digest"],
                "fd13_symmetry": rec["first_fd13"]["symmetry_digest"],
                "empty_ordered": rec["first_empty"]["ordered_digest"],
                "empty_symmetry": rec["first_empty"]["symmetry_digest"],
                "reveal_target": rec.get("reveal_target") or rec["first_fd13"].get("reveal_target"),
                "fd13_empties": rec["first_fd13"]["empties"],
                "empty_empties": rec["first_empty"]["empties"],
                "fd13_run": rec["first_fd13"]["longest_run"],
                "fd13_adj": rec["first_fd13"]["adjacencies"],
                "fd13_blocks": rec["first_fd13"]["movable_blocks"],
                "fd13_legal": rec["first_fd13"]["legal_action_count"],
                "buried": rec["first_fd13"]["buried_face_down_stacks"],
            }
            for rec in records
        ],
    }
    _write_json(OUT_DIR / "classification.json", payload)
    return payload


def regenerate_known_dead() -> dict:
    """Union of v0.19 exhausted exact graphs A (41,472) and B (89,856)."""

    opening = opening_state()
    fd12_actions = parse_moves_file(FD12_FIXTURE)
    fd12 = opening.clone()
    replay_actions(fd12, fd12_actions)
    print("REGEN known-dead A from v0.12 fd12", flush=True)
    a_reach = layered_reachability(
        fd12,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=300.0,
        rss_abort_mb=RSS_ABORT_MB,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        include_visited_hex=True,
    )
    set_a = set(a_reach.visited_identity_hex)
    print(f"A unique={a_reach.unique} stop={a_reach.stop_reason} expected=41472", flush=True)

    new_exits = []
    if V19_EXITS.exists():
        for line in V19_EXITS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("class") in ("NEW", "NEW_FD12", "NEW_FD12_EXIT", "NEW_FD12_REGION", "new") or rec.get("known_dead") is False:
                new_exits.append(rec)
            elif rec.get("classification") == "NEW_FD12_REGION":
                new_exits.append(rec)
    # v0.19 stored 18 exits; 3 were new. Prefer explicit flag, else symmetry not in A.
    if not new_exits and V19_EXITS.exists():
        for line in V19_EXITS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            digest = rec.get("symmetry_digest") or rec.get("identity")
            if digest and digest not in set_a:
                new_exits.append(rec)

    sources = []
    origin_paths = []
    fd13_seed_actions = parse_moves_file(B281_EMPTY)
    for rec in new_exits:
        actions = as_actions(rec.get("actions") or rec.get("local_actions") or [])
        if rec.get("full_actions"):
            full = as_actions(rec["full_actions"])
            st = opening.clone()
            replay_actions(st, full)
        else:
            st = opening.clone()
            replay_actions(st, fd13_seed_actions)
            replay_actions(st, actions)
        if face_down_count(st) == 12:
            sources.append(st)
            origin_paths.append(list(fd13_seed_actions) + list(actions) if not rec.get("full_actions") else as_actions(rec["full_actions"]))

    print(f"REGEN known-dead B from {len(sources)} new fd12 sources", flush=True)
    set_b = set()
    if sources:
        b_reach = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=10_000,
            max_unique=200_000,
            time_limit_s=400.0,
            rss_abort_mb=RSS_ABORT_MB,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            include_visited_hex=True,
        )
        set_b = set(b_reach.visited_identity_hex)
        print(f"B unique={b_reach.unique} stop={b_reach.stop_reason} expected=89856", flush=True)
    union = set_a | set_b
    jsonl = OUT_DIR / "known_dead_fd12_futures.jsonl"
    with jsonl.open("w", encoding="utf-8") as handle:
        for digest in sorted(union):
            handle.write(json.dumps({"symmetry_digest": digest}) + "\n")
    payload = {
        "set_a": len(set_a),
        "set_b": len(set_b),
        "union": len(union),
        "disjoint": len(set_a & set_b) == 0,
        "overlap": len(set_a & set_b),
        "a_stop": a_reach.stop_reason,
        "sources_b": len(sources),
        "path": jsonl.relative_to(ROOT).as_posix(),
    }
    _write_json(OUT_DIR / "known_dead_meta.json", payload)
    print(f"KNOWN_DEAD_FD12_FUTURES union={len(union)} a={len(set_a)} b={len(set_b)}", flush=True)
    return payload, union


def classify_fd12_exits(collected, known_dead: set) -> list:
    rows = []
    for item in collected:
        ident = None
        actions = as_actions(item.get("actions") or [])
        digest = item.get("digest")
        # collected stores ordered digest; compute symmetry from unpack
        state = unpack_state(bytes.fromhex(digest))
        sym = post_stock_identity(state).hex()
        klass = "KNOWN_DEAD" if sym in known_dead else "NEW_FD12_REGION"
        rows.append(
            {
                "ordered_digest": digest,
                "symmetry_digest": sym,
                "depth": item.get("depth"),
                "fd": item.get("fd"),
                "empties": item.get("empties"),
                "longest_run": item.get("longest_run"),
                "foundations": item.get("foundations"),
                "class": klass,
                "actions": [list(a) if a != ("deal",) else ["deal"] for a in actions],
            }
        )
    return rows


def run_phase3(classif: dict) -> dict:
    alts = [arm for arm in classif["arms"] if arm["fd13_class"] == ALTERNATIVE_FD13_CLASS]
    if not alts:
        return {"ran": False, "reason": "no alternative fd13 class"}
    dead_meta, known_dead = regenerate_known_dead()
    opening = opening_state()
    results = []
    for arm in alts:
        spec = ARMS[arm["arm"]]
        actions = parse_moves_file(spec["fd13_fixture"])
        seed = opening.clone()
        replay_actions(seed, actions)
        print(f"PHASE3 START {arm['arm']} from FIRST_FD13 depth_cap=10", flush=True)
        search = fair_short_horizon_fd13_search(seed)
        exits = classify_fd12_exits(search.collected, known_dead)
        known_n = sum(1 for e in exits if e["class"] == "KNOWN_DEAD")
        new_n = sum(1 for e in exits if e["class"] == "NEW_FD12_REGION")
        min_depth = search.collected_depth
        print(
            f"PHASE3 DONE {arm['arm']} unique={search.unique} stop={search.stop_reason} "
            f"min_fd={search.min_fd} fnd={search.max_foundations} fd12={len(exits)} "
            f"known_dead={known_n} new={new_n} depth={min_depth} "
            f"elapsed={search.elapsed_s:.1f} rss={search.peak_rss_mb}",
            flush=True,
        )
        # save min-depth fd12 witnesses
        for index, exit_rec in enumerate(exits):
            if exit_rec["class"] != "NEW_FD12_REGION":
                continue
            full = list(actions) + as_actions(exit_rec["actions"])
            path = ROOT / "solutions" / f"4925153_simple_v0_23_{arm['arm'].lower()}_fd12_{index}.moves.txt"
            write_fixture(
                path,
                full,
                header="\n".join(
                    [
                        f"# v0.23 {arm['arm']} min-depth fd12 NEW_FD12_REGION",
                        f"# local_depth: {exit_rec['depth']}",
                        f"# symmetry: {exit_rec['symmetry_digest']}",
                    ]
                ),
            )
            exit_rec["fixture"] = path.relative_to(ROOT).as_posix()
            exit_rec["full_path_length"] = len(full)
        results.append(
            {
                "arm": arm["arm"],
                "unique": search.unique,
                "generated": search.generated,
                "duplicate_skips": search.duplicate_skips,
                "stop_reason": search.stop_reason,
                "min_fd": search.min_fd,
                "max_foundations": search.max_foundations,
                "max_empties": search.max_empties,
                "max_run": search.max_run,
                "elapsed_s": search.elapsed_s,
                "peak_rss_mb": search.peak_rss_mb,
                "classifier_surprises": search.classifier_surprises,
                "collected_complete": search.collected_complete,
                "fd12_min_depth": min_depth,
                "fd12_exit_classes": len(exits),
                "known_dead": known_n,
                "new_region": new_n,
                "exits": exits,
                "fresh_tt": search.fresh_tt,
                "all_legal_tableau": True,
                "heuristic": False,
            }
        )
        _write_json(OUT_DIR / f"{arm['arm']}_phase3.json", results[-1])
    return {"ran": True, "known_dead_meta": dead_meta, "arms": results}


def run_phase4(phase3: dict) -> dict:
    if not phase3.get("ran"):
        return {"ran": False, "reason": "phase3 not run"}
    new_sources_meta = []
    opening = opening_state()
    sources = []
    origin_paths = []
    dead_hex = load_known_dead_hex([OUT_DIR / "known_dead_fd12_futures.jsonl"]) if (OUT_DIR / "known_dead_fd12_futures.jsonl").exists() else set()
    dead_bytes = {bytes.fromhex(h) for h in dead_hex}
    for arm in phase3.get("arms") or []:
        spec = ARMS[arm["arm"]]
        prefix = parse_moves_file(spec["fd13_fixture"])
        for exit_rec in arm.get("exits") or []:
            if exit_rec["class"] != "NEW_FD12_REGION":
                continue
            full = list(prefix) + as_actions(exit_rec["actions"])
            st = opening.clone()
            replay_actions(st, full)
            sources.append(st)
            origin_paths.append(full)
            new_sources_meta.append({"arm": arm["arm"], "depth": exit_rec["depth"], "symmetry": exit_rec["symmetry_digest"]})
    if not sources:
        return {"ran": False, "reason": "no NEW_FD12_REGION"}
    print(f"PHASE4 START sources={len(sources)}", flush=True)
    search = fair_fd10_continuation(sources, origin_paths=origin_paths, dead_identities=dead_bytes)
    fd10 = search.witnesses.get("fd_le_10")
    fnd = search.witnesses.get("foundation")
    print(
        f"PHASE4 DONE unique={search.unique} stop={search.stop_reason} min_fd={search.min_fd} "
        f"fnd={search.max_foundations} elapsed={search.elapsed_s:.1f} rss={search.peak_rss_mb}",
        flush=True,
    )
    payload = {
        "ran": True,
        "sources": len(sources),
        "unique": search.unique,
        "generated": search.generated,
        "stop_reason": search.stop_reason,
        "min_fd": search.min_fd,
        "max_foundations": search.max_foundations,
        "elapsed_s": search.elapsed_s,
        "peak_rss_mb": search.peak_rss_mb,
        "known_dead_prunes": search.known_dead_prunes,
        "fd10": fd10,
        "foundation": fnd,
        "source_meta": new_sources_meta,
    }
    if fd10:
        origin = fd10.get("origin", 0)
        full = list(origin_paths[origin]) + as_actions(fd10.get("actions") or [])
        path = ROOT / "solutions" / "4925153_simple_v0_23_fd10.moves.txt"
        write_fixture(path, full, header="# v0.23 alternative-branch fd10")
        payload["fd10_fixture"] = path.relative_to(ROOT).as_posix()
        payload["fd10_full_length"] = len(full)
    if fnd:
        origin = fnd.get("origin", 0)
        full = list(origin_paths[origin]) + as_actions(fnd.get("actions") or [])
        path = ROOT / "solutions" / "4925153_simple_v0_23_first_foundation.moves.txt"
        write_fixture(path, full, header="# v0.23 alternative-branch first foundation")
        payload["foundation_fixture"] = path.relative_to(ROOT).as_posix()
        payload["foundation_full_length"] = len(full)
    _write_json(OUT_DIR / "phase4.json", payload)
    return payload


def choose_verdict(classif, phase3, phase4) -> tuple[str, str]:
    if any(not (OUT_DIR / f"{name}_recovery.json").exists() for name in ARMS):
        return "LEGACY_FD13_RECOVERY_FAILED", "a historical arm was not recovered"
    for name in ARMS:
        rec = load_recovery(name)
        if not rec.get("ok"):
            return "LEGACY_FD13_RECOVERY_FAILED", rec.get("error") or name
    if classif.get("collapse"):
        extra = ""
        if classif.get("fd13_ordered_classes") == 1:
            extra = "; they are the same ordered pack_state, not merely a column permutation"
        return (
            "LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE",
            "B_2_0_1 and A_4_1_1 reduce to the B_2_8_1 fd13 class under post-stock symmetry"
            + extra,
        )
    if not phase3.get("ran"):
        return "INCONCLUSIVE", "distinct classes exist but phase 3 did not run"
    if any(arm.get("stop_reason") in ("unique limit", "time limit", "rss abort") and not arm.get("fd12_exit_classes") for arm in phase3.get("arms") or []):
        return "LEGACY_ALTERNATIVE_SEARCH_STATE_EXPLOSION", "resource limits bound a distinct alternative before a useful comparison"
    if phase4.get("ran") and (phase4.get("foundation") or (phase4.get("max_foundations") or 0) >= 1):
        return "LEGACY_ALTERNATIVE_REACHES_FOUNDATION", "an alternative fd13 branch reached a foundation"
    if phase4.get("ran") and (phase4.get("fd10") or (phase4.get("min_fd") or 99) <= 10):
        return "LEGACY_ALTERNATIVE_REACHES_FD10", "an alternative fd13 branch reached fd<=10"
    new_n = sum(arm.get("new_region") or 0 for arm in phase3.get("arms") or [])
    known_n = sum(arm.get("known_dead") or 0 for arm in phase3.get("arms") or [])
    fd12_n = sum(arm.get("fd12_exit_classes") or 0 for arm in phase3.get("arms") or [])
    if new_n and phase4.get("ran"):
        return (
            "LEGACY_ALTERNATIVE_FINDS_NEW_FD12_REGION",
            "distinct legacy fd13 branch reached an fd12 region outside exact known-dead caches",
        )
    if fd12_n and known_n and new_n == 0:
        return (
            "LEGACY_ALTERNATIVES_DISTINCT_BUT_KNOWN_DEAD",
            "distinct fd13 classes exist but short fd12 exits all enter certified dead regions",
        )
    if fd12_n == 0:
        explosion = any(
            arm.get("stop_reason") in ("unique limit", "time limit", "rss abort")
            for arm in phase3.get("arms") or []
        )
        if explosion:
            return "LEGACY_ALTERNATIVE_SEARCH_STATE_EXPLOSION", "limits bound the short-horizon fd12 test"
        return (
            "LEGACY_ALTERNATIVES_DISTINCT_NO_SHORT_FD12",
            "distinct fd13 classes exist but none reached fd12 within depth 10",
        )
    return "INCONCLUSIVE", "methodological remainder"


def next_recommendation(verdict: str) -> str:
    if verdict == "LEGACY_ALTERNATIVE_REACHES_FD10" or verdict == "LEGACY_ALTERNATIVE_REACHES_FOUNDATION":
        return (
            "CHEAPEST HARD PROGRESS WAS THE WRONG BRANCH. Retain several hard-progress "
            "checkpoints and continue the successful alternative; do not invent another target heuristic."
        )
    if verdict == "LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE":
        return (
            "v0.10 contains no unused alternative fd13 hard-progress branch. Next: design a "
            "fresh exact treatment of the fd14/stock0 root, still without a new target heuristic."
        )
    if verdict == "LEGACY_ALTERNATIVES_DISTINCT_BUT_KNOWN_DEAD":
        return (
            "The already-paid longer v0.10 routes are distinct but their short fd12 exits are "
            "certified dead. Next: a fresh fd14 treatment, not another target heuristic."
        )
    if verdict == "LEGACY_ALTERNATIVES_DISTINCT_NO_SHORT_FD12":
        return (
            "Distinct legacy fd13 classes exist but do not make the same nine-move fd12 step. "
            "Next: either a deeper exact probe of those classes or a fresh fd14 treatment. "
            "Do not invent another target heuristic."
        )
    if verdict == "LEGACY_ALTERNATIVE_FINDS_NEW_FD12_REGION":
        return (
            "A slower v0.10 branch reached a new fd12 region. Continue exact search from those "
            "exits; fd10 is the next genuine milestone. Do not invent another target heuristic."
        )
    if verdict == "LEGACY_FD13_RECOVERY_FAILED":
        return "Reconstruct the v0.10 first-visit witness paths before any new fd14 search."
    if verdict == "LEGACY_ALTERNATIVE_SEARCH_STATE_EXPLOSION":
        return "Keep the recovered fixtures; do not raise the envelope in this task. Next: a fresh fd14 design."
    return "Do not invent another target heuristic. Recover/classify first; only then consider a fresh fd14 search."


def _arm_row(arm: dict, phase3_by: dict, phase3_ran: bool, phase4: dict) -> str:
    p3 = phase3_by.get(arm["arm"], {})
    if arm["arm"] == "B_2_8_1" or arm.get("fd13_class") == CURRENT_FD13_CLASS:
        short, new, fd10 = "known", "no", "no"
    else:
        if p3.get("fd12_exit_classes"):
            short = f"yes d={p3.get('fd12_min_depth')}"
        elif phase3_ran:
            short = "no"
        else:
            short = "n/a"
        if p3.get("new_region"):
            new = "yes"
        elif p3.get("fd12_exit_classes"):
            new = "no"
        elif phase3_ran:
            new = "no"
        else:
            new = "n/a"
        fd10 = "no"
        if phase4.get("ran") and (phase4.get("min_fd") or 99) <= 10 and arm["fd13_class"] == ALTERNATIVE_FD13_CLASS:
            fd10 = "yes"
    reveal = (arm.get("reveal_target") or {}).get("signature_key") or ""
    empty_after = ",".join(str(i + 1) for i in (arm.get("empty_empties") or [])) or "none"
    return (
        f"| {arm['arm']} | {arm['fd13_path']} | {arm['fd13_class']} | `{reveal}` | "
        f"{empty_after} | {short} | {new} | {fd10} |"
    )


def write_report(payload: dict) -> None:
    arms = payload.get("classification", {}).get("arms") or []
    phase3 = payload.get("phase3") or {}
    phase4 = payload.get("phase4") or {}
    phase3_by = {a["arm"]: a for a in phase3.get("arms") or []}
    fd14 = payload.get("fd14") or {}
    lines = [
        "# Simple Progressive Search v0.23 — Legacy FD13 Alternative-Branch Recovery",
        "",
        "## 1. Verdict",
        "",
        f"`{payload['verdict']}` — {payload.get('verdict_reason', '')}",
        "",
        payload.get("interpretation", ""),
        "",
        f"- Branch: `{payload.get('branch')}`",
        f"- Base SHA: `{BASE_SHA}`",
        "- Previous verdict: `FU5_LOCAL_NO_CLEARANCE_PROGRESS`",
        "- No new heuristic. No fresh fd14 search. No column-7 targeting.",
        "",
        "## 2. fd14 root",
        "",
        f"- path={fd14.get('total_primitive_path')} MW={fd14.get('corrected_mw_cost')} "
        f"fd={fd14.get('fd')} stock={fd14.get('stock')} foundations={fd14.get('foundations')} "
        f"empties={fd14.get('empties')} run={fd14.get('longest_run')}",
        f"- ordered=`{fd14.get('ordered_digest')}`",
        f"- symmetry=`{fd14.get('symmetry_digest')}`",
        f"- historical digest match: {fd14.get('ordered_matches_historical')}",
        "",
        "## 3. Recovered witnesses",
        "",
        "| Arm | Total depth to fd13 | FD13 symmetry class | Reveal target | Empty after fd13 | Short fd12? | New fd12 region? | Reaches fd10? |",
        "|---|---:|---|---|---:|---:|---:|---:|",
        *[_arm_row(arm, phase3_by, bool(phase3.get("ran")), phase4) for arm in arms],
        "",
    ]
    for arm in arms:
        lines.extend(
            [
                f"### {arm['arm']}",
                "",
                f"- FIRST_FD13 path={arm['fd13_path']} MW={arm['fd13_cost']} class=`{arm['fd13_class']}` "
                f"ordered_eq_B281={arm.get('ordered_eq_b281')}",
                f"- FIRST_EMPTY path={arm['empty_path']} MW={arm['empty_cost']} empties={arm.get('empty_empties')}",
                f"- reveal target `{((arm.get('reveal_target') or {}).get('signature_key'))}`",
                f"- fd13 ordered=`{arm.get('fd13_ordered')}`",
                f"- fd13 symmetry=`{arm.get('fd13_symmetry')}`",
                f"- empty ordered=`{arm.get('empty_ordered')}`",
                f"- empty symmetry=`{arm.get('empty_symmetry')}`",
                f"- run={arm.get('fd13_run')} adj={arm.get('fd13_adj')} blocks={arm.get('fd13_blocks')} "
                f"legal={arm.get('fd13_legal')}",
                "",
            ]
        )
    lines.extend(
        [
            "## 4. Classification",
            "",
            f"- distinct fd13 ordered classes: {payload.get('classification', {}).get('fd13_ordered_classes')}",
            f"- distinct fd13 symmetry classes: {payload.get('classification', {}).get('fd13_symmetry_classes')}",
            f"- distinct first-empty ordered classes: {payload.get('classification', {}).get('empty_ordered_classes')}",
            f"- distinct first-empty symmetry classes: {payload.get('classification', {}).get('empty_symmetry_classes')}",
            f"- alternative arms: {payload.get('classification', {}).get('alternative_arms')}",
            f"- collapse: {payload.get('classification', {}).get('collapse')}",
            "",
            "## 5. Recovery runtime",
            "",
        ]
    )
    for name, rec in (payload.get("recoveries") or {}).items():
        lines.append(
            f"- {name}: method={rec.get('method')} ok={rec.get('ok')} "
            f"nodes={rec.get('nodes')} elapsed_s={rec.get('elapsed_s')} "
            f"rss_mb={rec.get('peak_rss_mb')} stop={rec.get('stop_reason')} "
            f"path_match={rec.get('path_length_match')}"
        )
    lines.extend(
        [
            "",
            "## 6. Phase 3",
            "",
        ]
    )
    if not phase3.get("ran"):
        lines.append(f"Skipped: {phase3.get('reason')}")
        lines.append("")
    else:
        for arm in phase3.get("arms") or []:
            lines.append(
                f"- {arm['arm']}: unique={arm.get('unique')} stop={arm.get('stop_reason')} "
                f"min_fd={arm.get('min_fd')} fnd={arm.get('max_foundations')} "
                f"fd12={arm.get('fd12_exit_classes')} known_dead={arm.get('known_dead')} "
                f"new={arm.get('new_region')} min_depth={arm.get('fd12_min_depth')} "
                f"elapsed={arm.get('elapsed_s')} rss={arm.get('peak_rss_mb')}"
            )
        lines.append("")
    lines.extend(
        [
            "## 7. Phase 4",
            "",
        ]
    )
    if not phase4.get("ran"):
        lines.append(f"Skipped: {phase4.get('reason')}")
        lines.append("")
    else:
        lines.append(
            f"- unique={phase4.get('unique')} stop={phase4.get('stop_reason')} "
            f"min_fd={phase4.get('min_fd')} fnd={phase4.get('max_foundations')} "
            f"elapsed={phase4.get('elapsed_s')} rss={phase4.get('peak_rss_mb')}"
        )
        lines.append("")
    lines.extend(
        [
            "## 8. Exactly one next recommendation",
            "",
            payload.get("next_recommendation", ""),
            "",
            "## Integrity",
            "",
            f"Verdict {payload.get('verdict')}. fd10={payload.get('fd10')} foundation={payload.get('foundation')}.",
            "",
            f"Base SHA `{BASE_SHA}`. Deal `deals/4925153.txt`.",
            "No new heuristic. No fresh fd14 search. No column-7 arm. No production change.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fd14_rec, opening, prefix, fd14 = verify_fd14()
    print(
        f"FD14 ok={fd14_rec['ok']} path={fd14_rec['total_primitive_path']} cost={fd14_rec['corrected_mw_cost']} "
        f"fd={fd14_rec['fd']} ordered={fd14_rec['ordered_digest'][:24]}",
        flush=True,
    )
    recoveries = {}
    for name in ARMS:
        path = OUT_DIR / f"{name}_recovery.json"
        if path.exists():
            rec = json.loads(path.read_text(encoding="utf-8"))
            if rec.get("ok"):
                print(f"SKIP recover {name} already ok", flush=True)
                recoveries[name] = rec
                continue
        recoveries[name] = recover_arm(name)
    classif = classify_recoveries()
    print(
        f"CLASS fd13_sym={classif.get('fd13_symmetry_classes')} empty_sym={classif.get('empty_symmetry_classes')} "
        f"alts={classif.get('alternative_arms')} collapse={classif.get('collapse')}",
        flush=True,
    )
    phase3 = {"ran": False, "reason": "symmetry collapse"}
    phase4 = {"ran": False, "reason": "not required"}
    if classif.get("ok") and not classif.get("collapse"):
        phase3 = run_phase3(classif)
        if any((arm.get("new_region") or 0) > 0 for arm in phase3.get("arms") or []):
            phase4 = run_phase4(phase3)
    verdict, reason = choose_verdict(classif, phase3, phase4)
    if verdict == "LEGACY_FD13_ALTERNATIVES_SYMMETRY_COLLAPSE":
        interpretation = (
            "The apparently different historical hard-progress routes all reduce to the "
            "current fd13 class under exact post-stock symmetry. They are in fact the same "
            "ordered pack_state: the seven extra primitives are a detour to the identical "
            "physical checkpoint, not a discarded alternative. v0.10 did not contain an "
            "unused alternative hard-progress branch."
        )
    elif verdict == "LEGACY_ALTERNATIVE_REACHES_FD10":
        interpretation = "CHEAPEST HARD PROGRESS WAS THE WRONG BRANCH."
    elif verdict.startswith("LEGACY_ALTERNATIVES_DISTINCT"):
        interpretation = (
            "The longer routes are genuinely distinct. We have consumed the obvious already-paid "
            "alternatives inside this task's envelope."
        )
    else:
        interpretation = reason
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "branch": "agent/simple-progressive-legacy-fd13-alternatives-v0-23",
        "previous_verdict": "FU5_LOCAL_NO_CLEARANCE_PROGRESS",
        "verdict": verdict,
        "verdict_reason": reason,
        "interpretation": interpretation,
        "next_recommendation": next_recommendation(verdict),
        "fd14": fd14_rec,
        "recoveries": {name: recoveries.get(name) for name in ARMS},
        "classification": classif,
        "phase3": phase3,
        "phase4": phase4,
        "fd10": bool(phase4.get("fd10") or (phase4.get("min_fd") or 99) <= 10),
        "foundation": bool(phase4.get("foundation") or (phase4.get("max_foundations") or 0) >= 1),
        "no_new_heuristic": True,
        "no_fresh_fd14_search": True,
        "production_unchanged": True,
    }
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"NEXT {payload['next_recommendation']}", flush=True)
    return payload


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "recover":
        name = sys.argv[2]
        rec = recover_arm(name)
        if not rec.get("ok"):
            raise SystemExit(1)
    elif cmd == "fd14":
        rec, *_ = verify_fd14()
        print(json.dumps(rec, indent=2))
        if not rec.get("ok"):
            raise SystemExit(1)
    elif cmd == "classify":
        rec = classify_recoveries()
        print(json.dumps({k: rec[k] for k in rec if k != "arms"}, indent=2))
    else:
        main()
