#!/usr/bin/env python3
"""v0.20: alternate buried-stack targeting."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state
from spider.simple_post_deal_audit import census_legal_by_tier, exposed_run_metrics
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_target_clearance import (
    census_buried_targets,
    face_down_signature,
    revealed_target_signature,
    signature_key,
    target_directed_plateau,
    target_face_up_count,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    face_down_count,
    layered_reachability,
    post_stock_identity,
    stock0_tableau_classifier_complete,
)

EXPERIMENT = "simple_progressive_alternate_reveal_target_v0_20"
BASE_SHA = "5af74c3f204f23e92ff8573e833ec66de20c24af"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD13_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
V19_EXITS = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "fd12_exit_classes.jsonl"
)
DEAD_CACHE = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
)
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "target_fd12_exits.jsonl"
VIABLE = ROOT / "solutions" / "4925153_simple_v0_20_viable_fd12.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_20_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_20_first_foundation.moves.txt"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)


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
        "legal": census["legal"],
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": post_stock_identity(state).hex() if not state.stock else None,
    }


def replay_full(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        for action in part:
            combined.append(("deal",) if action in (("deal",), ["deal"]) else tuple(action))
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        return {"ok": True, "cost": paid, "path_length": len(combined), "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in combined], **inspect_state(end)}
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined), "full_actions": []}


def save_route(path: Path, header: str, actions) -> None:
    path.write_text(format_moves_text(actions, header=header), encoding="utf-8")


def load_dead_cache() -> set[str]:
    if not DEAD_CACHE.exists():
        return set()
    out = set()
    for line in DEAD_CACHE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        if rec.get("fd") == 12:
            out.add(rec["symmetry_digest"])
    return out


def compact_arm(result, *, name: str, target_row: dict) -> dict:
    return {
        "name": name,
        "target_key": result.target_key,
        "root_physical_column_1": target_row["physical_column_1"],
        "root_face_up_count": result.root_target_fu,
        "fd_count": target_row["fd_count"],
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "max_depth": result.max_depth,
        "min_target_fu": result.min_target_fu,
        "first_reveal_unique": result.first_reveal_unique,
        "first_reveal_depth": result.first_reveal_depth,
        "first_reveal_expansions": result.first_reveal_expansions,
        "exit_classes": result.exit_classes,
        "off_target_reveals": result.off_target_reveals,
        "fu_decreases": result.fu_decreases,
        "fu_increases": result.fu_increases,
        "fu_returns": result.fu_returns,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "expansions": result.expansions,
    }


def classify_exits(exits, dead_fd12: set[str], arm: str) -> tuple[list, list]:
    known, new = [], []
    for rec in exits:
        rec = dict(rec)
        rec["arm"] = arm
        rec["class"] = "KNOWN_DEAD_EXIT" if rec["symmetry_digest"] in dead_fd12 else "NEW_EXIT"
        rec["viable"] = False
        (known if rec["class"] == "KNOWN_DEAD_EXIT" else new).append(rec)
    return known, new


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("control_failed"):
        return (
            "TARGET_CLEARANCE_HEURISTIC_FAILS_CONTROL",
            "the simple target-face-up-count search could not rediscover the known easy reveal",
        )
    if payload.get("foundation"):
        return "ALTERNATE_REVEAL_TARGET_REACHES_FOUNDATION", "an alternative buried-stack target reached a foundation"
    if payload.get("fd10"):
        return "ALTERNATE_REVEAL_TARGET_REACHES_FD10", "an alternative buried-stack target yielded an fd12 exit that reached fd10"
    alt_new = (payload.get("alt1_new") or 0) + (payload.get("alt2_new") or 0)
    alt_exits = (payload.get("alt1_exits") or 0) + (payload.get("alt2_exits") or 0)
    downstream = payload.get("downstream") or []
    explosion = any(d.get("stop_reason") in ("unique limit", "time limit", "rss abort") for d in downstream)
    exhausted = all(d.get("stop_reason") == "frontier empty" for d in downstream) if downstream else False
    if alt_new > 0 and explosion:
        return "TARGET_CONTINUATION_STATE_EXPLOSION", "alternative exits were found but downstream search could not be resolved"
    if alt_new > 0 and exhausted:
        return (
            "TARGET_DIRECTED_SEARCH_FINDS_NEW_REGIONS_BUT_THEY_STALL",
            "alternative buried-stack reveals were found, but harvested new exits exhaust without fd10",
        )
    if alt_exits > 0:
        return (
            "ALTERNATE_TARGET_REVEALS_FOUND",
            "the target-directed treatment revealed a previously unobserved buried stack, but downstream viability is unresolved",
        )
    return (
        "ALTERNATE_TARGETS_NOT_REACHED",
        "the control succeeded, but neither alternative target could be revealed inside the bounded envelope",
    )


def next_recommendation(verdict: str) -> str:
    if verdict in (
        "ALTERNATE_REVEAL_TARGET_REACHES_FOUNDATION",
        "ALTERNATE_REVEAL_TARGET_REACHES_FD10",
    ):
        return (
            "Deliberate targeting of a harder buried stack keeps the deal alive. Next: restart "
            "the reveal ratchet from that fd12 checkpoint; do not add another heuristic."
        )
    if verdict == "TARGET_DIRECTED_SEARCH_FINDS_NEW_REGIONS_BUT_THEY_STALL":
        return (
            "Harder buried-stack reveals exist and also die. Next: do not add another heuristic; "
            "a later task may backtrack to fd14 or change the search object, not this task."
        )
    if verdict == "ALTERNATE_TARGETS_NOT_REACHED":
        return (
            "Cheap target-clearance cannot expose the harder stacks inside this envelope. Next: "
            "do not raise v0.19's breadth limit here; a later task may try a different treatment."
        )
    if verdict == "TARGET_CLEARANCE_HEURISTIC_FAILS_CONTROL":
        return "The FU-count ordering cannot even recover the known easy reveal. Do not interpret the alternate arms."
    if verdict in ("TARGET_CONTINUATION_STATE_EXPLOSION", "ALTERNATE_TARGET_REVEALS_FOUND"):
        return "Do not raise limits here. Report the bounded target-directed result and stop."
    return "Reproduce the target-directed audit before changing reveal policy."


def write_report(payload: dict) -> None:
    lines = [
        "# Simple Progressive Search v0.20: Alternate Buried-Stack Targeting",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "TARGET_FACE_UP_COUNT ordering is a research heuristic with no proof or pruning authority.",
        "Production `pack_state` / `solve_progressive` are unchanged.",
        "",
        "## 2. Root buried targets",
        "",
    ]
    for row in payload.get("root_targets") or []:
        lines.append(
            f"- 1-based col {row.get('physical_column_1')}: fd={row.get('fd_count')} "
            f"fu={row.get('face_up_count')} run={row.get('exposed_run')} key=`{row.get('signature_key')}`"
        )
    lines.extend(["", "## 3. v0.19 exit audit", ""])
    audit = payload.get("v19_audit") or {}
    lines.append(
        f"- exits={audit.get('exit_count')} by_target={audit.get('by_target')} "
        f"earliest={audit.get('earliest_by_target')} known/new={audit.get('class_by_target')}"
    )
    lines.extend(["", "## 4. Target arms", "", "| Reveal target | Root FU | Unique | FD12 exits | New | Reaches FD10 |", "|---|---:|---:|---:|---:|---:|"])
    for row in payload.get("comparison") or []:
        lines.append(
            f"| {row.get('name')} | {row.get('root_fu')} | {row.get('unique')} | "
            f"{row.get('exits')} | {row.get('new')} | {row.get('reaches_fd10')} |"
        )
    lines.extend(["", "## 5. Downstream", ""])
    if not payload.get("downstream"):
        lines.append(f"- skipped: {payload.get('downstream_skip')}")
    else:
        for d in payload["downstream"]:
            lines.append(
                f"- {d.get('arm')}: sources={d.get('source_count')} unique={d.get('unique')} "
                f"stop={d.get('stop_reason')} min_fd={d.get('min_fd')} fnd={d.get('max_foundations')} "
                f"elapsed={d.get('elapsed_s')}"
            )
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
            "No broad fd13 exhaustion, no fd14 backtrack, no extra heuristic.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def audit_v19(seed: SpiderState, targets: list[dict]) -> dict:
    sig_by_key = {row["signature_key"]: tuple((s, r) for s, r in row["signature"]) for row in targets}
    col_by_key = {row["signature_key"]: row["physical_column_1"] for row in targets}
    rows = [json.loads(line) for line in V19_EXITS.read_text(encoding="utf-8").splitlines() if line.strip()]
    counts = Counter()
    earliest = {}
    classes = Counter()
    for rec in rows:
        state = seed.clone()
        actions = [tuple(a) for a in rec["actions"]]
        parent = state
        revealed = None
        for action in actions:
            nxt = parent.clone()
            apply_action(nxt, action)
            if face_down_count(nxt) < face_down_count(parent):
                sig = revealed_target_signature(parent, nxt)
                revealed = signature_key(sig) if sig else "unknown"
                break
            parent = nxt
        counts[revealed] += 1
        earliest[revealed] = rec["depth"] if revealed not in earliest else min(earliest[revealed], rec["depth"])
        classes[f"{revealed}:{rec.get('class')}"] += 1
    return {
        "exit_count": len(rows),
        "by_target": dict(counts),
        "earliest_by_target": earliest,
        "class_by_target": dict(classes),
        "all_easy_column2": len(counts) == 1 and list(counts)[0] == next(
            row["signature_key"] for row in targets if row["physical_column_1"] == 2
        ),
        "root_column_by_key": col_by_key,
    }


def run_downstream(opening, prefix, fd13, new_exits, arm: str) -> dict:
    if not new_exits:
        return {"arm": arm, "skipped": True, "reason": "no NEW_EXIT"}
    sources, origin_paths = [], []
    for rec in new_exits:
        st = fd13.clone()
        path = [tuple(a) for a in rec["actions"]]
        replay_actions(st, path)
        sources.append(st)
        origin_paths.append(path)
    print(f"DOWNSTREAM {arm} sources={len(sources)}", flush=True)
    result = layered_reachability(
        sources=sources,
        origin_paths=origin_paths,
        max_depth=10_000,
        max_unique=750_000,
        time_limit_s=900.0,
        rss_abort_mb=3 * 1024.0,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        stop_fd=10,
        checkpoints=(8, 12, 16, 24, 32),
    )
    payload = {
        "arm": arm,
        "source_count": result.source_count,
        "unique": result.unique,
        "generated": result.generated,
        "stop_reason": result.stop_reason,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "first_depth": result.first_depth,
    }
    fd10 = None
    foundation = None
    if "foundation" in result.witnesses:
        w = result.witnesses["foundation"]
        origin = w.get("origin") or 0
        foundation = {**w, "origin": origin, **replay_full(opening, [prefix, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
    if "fd_le_10" in result.witnesses:
        w = result.witnesses["fd_le_10"]
        origin = w.get("origin") or 0
        fd10 = {**w, "origin": origin, **replay_full(opening, [prefix, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
    payload["fd10_witness"] = fd10
    payload["foundation_witness"] = foundation
    return payload


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = opening_state()
    prefix = parse_moves_file(FD13_FIXTURE)
    fd13 = opening.clone()
    cost = replay_actions(fd13, prefix)
    ok = (
        pack_state(fd13).hex() == FD13_HEX
        and len(prefix) == 102
        and cost == 102
        and face_down_count(fd13) == 13
        and len(fd13.stock) == 0
        and len(fd13.foundations) == 0
    )
    print(f"FD13_OK {ok}", flush=True)
    if not ok:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "fd13 fixture failed"}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1

    targets = census_buried_targets(fd13)
    print("TARGETS " + json.dumps([{k: r[k] for k in ("physical_column_1", "fd_count", "face_up_count", "signature_key")} for r in targets]), flush=True)
    clf = stock0_tableau_classifier_complete(fd13)
    audit = audit_v19(fd13, targets)
    print(f"V19_AUDIT by_target={audit['by_target']} all_col2={audit['all_easy_column2']}", flush=True)
    dead_fd12 = load_dead_cache()
    print(f"DEAD_CACHE fd12={len(dead_fd12)}", flush=True)

    by_col = {row["physical_column_1"]: row for row in targets}
    easy = by_col[2]
    alt1 = by_col[1]
    alt2 = by_col[7]
    easy_sig = tuple((s, r) for s, r in easy["signature"])
    alt1_sig = tuple((s, r) for s, r in alt1["signature"])
    alt2_sig = tuple((s, r) for s, r in alt2["signature"])

    print("CONTROL easy target col2", flush=True)
    control = target_directed_plateau(
        fd13, easy_sig, max_unique=100_000, time_limit_s=180.0, rss_abort_mb=1024.0, max_exits=16, plateau_fd=13
    )
    print(
        f"CONTROL unique={control.unique} exits={control.exit_classes} first_depth={control.first_reveal_depth} "
        f"stop={control.stop_reason} elapsed={control.elapsed_s:.1f}",
        flush=True,
    )
    control_failed = control.exit_classes == 0
    harvested = []
    ck, cn = classify_exits(control.exits, dead_fd12, "control")
    harvested.extend(ck + cn)

    alt1_res = alt2_res = None
    ak = an = bk = bn = []
    downstream = []
    fd10_payload = None
    foundation = None
    winning_target = None

    if not control_failed:
        print("ALT1 target col1", flush=True)
        alt1_res = target_directed_plateau(
            fd13, alt1_sig, max_unique=500_000, time_limit_s=600.0, rss_abort_mb=2 * 1024.0, max_exits=64, plateau_fd=13
        )
        print(
            f"ALT1 unique={alt1_res.unique} exits={alt1_res.exit_classes} min_fu={alt1_res.min_target_fu} "
            f"first_depth={alt1_res.first_reveal_depth} stop={alt1_res.stop_reason} elapsed={alt1_res.elapsed_s:.1f}",
            flush=True,
        )
        ak, an = classify_exits(alt1_res.exits, dead_fd12, "alt1")
        harvested.extend(ak + an)
        if an:
            down = run_downstream(opening, prefix, fd13, an, "alt1")
            downstream.append(down)
            if down.get("foundation_witness") and down["foundation_witness"].get("ok"):
                foundation = down["foundation_witness"]
                winning_target = "alt1"
            if down.get("fd10_witness") and down["fd10_witness"].get("ok"):
                fd10_payload = down["fd10_witness"]
                winning_target = winning_target or "alt1"

        if not foundation and not fd10_payload:
            print("ALT2 target col7", flush=True)
            alt2_res = target_directed_plateau(
                fd13, alt2_sig, max_unique=500_000, time_limit_s=600.0, rss_abort_mb=2 * 1024.0, max_exits=64, plateau_fd=13
            )
            print(
                f"ALT2 unique={alt2_res.unique} exits={alt2_res.exit_classes} min_fu={alt2_res.min_target_fu} "
                f"first_depth={alt2_res.first_reveal_depth} stop={alt2_res.stop_reason} elapsed={alt2_res.elapsed_s:.1f}",
                flush=True,
            )
            bk, bn = classify_exits(alt2_res.exits, dead_fd12, "alt2")
            harvested.extend(bk + bn)
            if bn:
                down = run_downstream(opening, prefix, fd13, bn, "alt2")
                downstream.append(down)
                if down.get("foundation_witness") and down["foundation_witness"].get("ok"):
                    foundation = down["foundation_witness"]
                    winning_target = "alt2"
                if down.get("fd10_witness") and down["fd10_witness"].get("ok"):
                    fd10_payload = down["fd10_witness"]
                    winning_target = winning_target or "alt2"

    if fd10_payload and fd10_payload.get("ok"):
        save_route(FD10_FIXTURE, "# v0.20 target-directed fd10\n", [tuple(a) if a != ["deal"] else ("deal",) for a in fd10_payload["full_actions"]])
    if foundation and foundation.get("ok"):
        save_route(FOUNDATION_FIXTURE, "# v0.20 target-directed foundation\n", [tuple(a) if a != ["deal"] else ("deal",) for a in foundation["full_actions"]])

    EXITS_JSONL.write_text("\n".join(json.dumps(rec, sort_keys=True) for rec in harvested) + ("\n" if harvested else ""), encoding="utf-8")

    def row(name, arm, known, new, reaches):
        return {
            "name": name,
            "root_fu": None if arm is None else arm.root_target_fu,
            "unique": None if arm is None else arm.unique,
            "exits": None if arm is None else arm.exit_classes,
            "new": len(new),
            "known_dead": len(known),
            "reaches_fd10": reaches,
        }

    comparison = [
        row("Known/easy col2", control, ck, cn, False),
        row("Alternate col1", alt1_res, ak, an, bool(winning_target == "alt1" and fd10_payload)),
        row("Alternate col7", alt2_res, bk, bn, bool(winning_target == "alt2" and fd10_payload)),
    ]
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "fd13": {"replay_ok": True, "path_length": 102, "cost": cost, **inspect_state(fd13)},
        "classifier_complete": clf["complete"],
        "root_targets": targets,
        "v19_audit": audit,
        "control_failed": control_failed,
        "control": compact_arm(control, name="control", target_row=easy),
        "alt1": None if alt1_res is None else compact_arm(alt1_res, name="alt1", target_row=alt1),
        "alt2": None if alt2_res is None else compact_arm(alt2_res, name="alt2", target_row=alt2),
        "alt1_exits": 0 if alt1_res is None else alt1_res.exit_classes,
        "alt2_exits": 0 if alt2_res is None else alt2_res.exit_classes,
        "alt1_new": len(an),
        "alt2_new": len(bn),
        "control_exits": control.exit_classes,
        "control_new": len(cn),
        "comparison": comparison,
        "downstream": downstream,
        "downstream_skip": None if downstream else ("control failed" if control_failed else "no new alternate exits"),
        "fd10": bool(fd10_payload and fd10_payload.get("ok")),
        "foundation": bool(foundation and foundation.get("ok")),
        "fd10_witness": fd10_payload,
        "foundation_witness": foundation,
        "winning_target": winning_target,
        "production_unchanged": True,
        "heuristic": "TARGET_FACE_UP_COUNT then depth then seq",
        "heuristic_proof_authority": False,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. control_exits={control.exit_classes} alt1_exits={payload['alt1_exits']} "
        f"alt2_exits={payload['alt2_exits']} fd10={payload['fd10']} foundation={payload['foundation']}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
