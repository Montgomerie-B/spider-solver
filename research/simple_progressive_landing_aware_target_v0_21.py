#!/usr/bin/env python3
"""v0.21: landing-aware target clearance for column-1 buried stack."""

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
from spider.simple_progressive_solver import format_moves_text
from spider.simple_target_clearance import (
    census_buried_targets,
    face_down_signature,
    signature_key,
    target_directed_plateau,
    target_stack_audit,
)
from spider.simple_workspace_reachability import (
    empty_column_indices,
    face_down_count,
    layered_reachability,
    post_stock_identity,
    stock0_tableau_classifier_complete,
)

EXPERIMENT = "simple_progressive_landing_aware_target_v0_21"
BASE_SHA = "ac60bd3c0a8981b355f0d16cbc5c0f102c7661fb"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
FD13_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_CACHE = (
    ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"
)
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
EXITS_JSONL = OUT_DIR / "target_fd12_exits.jsonl"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_21_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_21_first_foundation.moves.txt"
FD13_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
COL1_KEY = "c10,d12,c6,s8"
V20_BASELINE = {
    "target_fu_root": 9,
    "min_fu": 7,
    "unique": 500000,
    "expansions": 198884,
    "generated": 1392280,
    "target_reveal": False,
    "max_depth": 24,
    "elapsed_s": 406.0,
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def inspect(state: SpiderState) -> dict:
    return {
        "fd": face_down_count(state),
        "stock": len(state.stock),
        "foundations": len(state.foundations),
        "empties": list(empty_column_indices(state)),
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": post_stock_identity(state).hex(),
    }


def replay_full(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        for action in part:
            combined.append(("deal",) if action in (("deal",), ["deal"]) else tuple(action))
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in combined],
            **inspect(end),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined), "full_actions": []}


def load_dead_fd12() -> set[str]:
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


def classify_stall(sample: list[dict]) -> str:
    if not sample:
        return "NO_SINGLE_DOMINANT_BLOCKER"
    n = len(sample)
    no_land = sum(1 for row in sample if not row.get("legal_landing"))
    no_empty = sum(1 for row in sample if not row.get("empty_exists"))
    king = sum(1 for row in sample if row.get("top_block_head") == 13)
    high_blocks = sum(1 for row in sample if (row.get("block_count") or 0) >= 4)
    if king >= n / 2 and no_empty >= n / 2:
        return "NEEDS_EMPTY_FOR_NEXT_BLOCK"
    if no_land >= n / 2 and king < n / 2:
        return "NEEDS_RANK_LANDING_FOR_NEXT_BLOCK"
    if high_blocks >= n / 2:
        return "TARGET_STILL_TOO_FRAGMENTED"
    return "NO_SINGLE_DOMINANT_BLOCKER"


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("foundation"):
        return "LANDING_AWARE_TARGET_REACHES_FOUNDATION", "column-1 target led to a replay-valid foundation"
    if payload.get("fd10"):
        return "LANDING_AWARE_TARGET_REACHES_FD10", "column-1 target was revealed and downstream reached fd10"
    search = payload.get("search") or {}
    if search.get("exit_classes", 0) > 0:
        return (
            "LANDING_AWARE_TARGET_REVEALED_BUT_STALLS",
            "column-1 target was revealed, but harvested downstream regions did not reach fd10",
        )
    min_fu = search.get("min_target_fu")
    if min_fu is not None and min_fu < 7:
        return "LANDING_AWARE_BREAKS_FU7_BARRIER", "target FU fell below 7 but no complete reveal was reached"
    if min_fu is not None and (
        (search.get("min_block_count") is not None and search["min_block_count"] < (payload.get("root_audit") or {}).get("block_count", 99))
        or (search.get("min_obstruction") is not None and search["min_obstruction"] < (payload.get("root_audit") or {}).get("landing_obstruction", 99))
        or min_fu < 7
    ):
        if min_fu <= 7 and (
            search.get("min_block_count", 99) < (payload.get("root_audit") or {}).get("block_count", 99)
            or search.get("min_relaxed", 99) < (payload.get("root_audit") or {}).get("relaxed_clearance", 99)
        ):
            return (
                "LANDING_AWARE_IMPROVES_CLEARANCE_ONLY",
                "the new metric improved block/landing progress but did not break the FU7 barrier",
            )
    if min_fu == 7 and search.get("exit_classes", 0) == 0:
        improved = False
        root = payload.get("root_audit") or {}
        if search.get("min_block_count") is not None and search["min_block_count"] < root.get("block_count", 99):
            improved = True
        if search.get("min_obstruction") is not None and search["min_obstruction"] < root.get("landing_obstruction", 99):
            improved = True
        if search.get("min_relaxed") is not None and search["min_relaxed"] < root.get("relaxed_clearance", 99):
            improved = True
        if improved:
            return (
                "LANDING_AWARE_IMPROVES_CLEARANCE_ONLY",
                "the new metric improved block/landing progress but did not break the FU7 barrier",
            )
        return "LANDING_AWARE_NO_IMPROVEMENT", "no meaningful improvement over the v0.20 column-1 baseline"
    if search.get("stop_reason") in ("time limit", "rss abort") and search.get("unique", 0) < 10000:
        return "LANDING_AWARE_STATE_EXPLOSION", "resource limits prevent a useful causal comparison"
    if min_fu == 7:
        return "LANDING_AWARE_NO_IMPROVEMENT", "no meaningful improvement over the v0.20 column-1 baseline"
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict in ("LANDING_AWARE_TARGET_REACHES_FOUNDATION", "LANDING_AWARE_TARGET_REACHES_FD10"):
        return (
            "Landing-aware clearance of column 1 keeps the deal alive. Next: restart the reveal "
            "ratchet from that fd12; do not add another heuristic here."
        )
    if verdict == "LANDING_AWARE_TARGET_REVEALED_BUT_STALLS":
        return (
            "Column 1 can be uncovered but the resulting fd12 still dies. Next: do not add another "
            "heuristic; a later task may change the search object."
        )
    if verdict in ("LANDING_AWARE_BREAKS_FU7_BARRIER", "LANDING_AWARE_IMPROVES_CLEARANCE_ONLY"):
        return (
            "Landing awareness moved the column-1 metric but did not finish the reveal. Next: do "
            "not add another heuristic or raise this budget; reassess before trying column 7."
        )
    if verdict == "LANDING_AWARE_NO_IMPROVEMENT":
        return (
            "Next-landing awareness does not break the column-1 FU7 stall. Next: do not add another "
            "heuristic, do not test column 7, and do not raise the budget in this line."
        )
    if verdict == "LANDING_AWARE_STATE_EXPLOSION":
        return "Do not raise limits here. Report the bounded comparison and stop."
    return "Reproduce the landing-aware audit before changing target policy."


def write_report(payload: dict) -> None:
    s = payload.get("search") or {}
    root = payload.get("root_audit") or {}
    lines = [
        "# Simple Progressive Search v0.21: Landing-Aware Target Clearance",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "RELAXED_CLEARANCE = TARGET_BLOCK_COUNT + NEXT_LANDING_OBSTRUCTION is a research heuristic.",
        "It does not prune and has no proof authority. Production identity is unchanged. Column 7 was not tested.",
        "",
        "## 2. Root target audit (column-1 signature c10,d12,c6,s8)",
        "",
        f"- FU={root.get('face_up_count')} blocks={root.get('block_count')} "
        f"top={root.get('top_block_head')}x{root.get('top_block_length')} "
        f"legal_landing={root.get('legal_landing')} empties={root.get('empty_columns')} "
        f"obstruction={root.get('landing_obstruction')} relaxed={root.get('relaxed_clearance')}",
        f"- face-up={root.get('face_up')}",
        f"- blocks={root.get('blocks')}",
        "",
        "## 3. v0.20 vs v0.21",
        "",
        "| Metric | v0.20 FU-only | v0.21 landing-aware |",
        "|---|---:|---:|",
        f"| unique | {V20_BASELINE['unique']} | {s.get('unique')} |",
        f"| generated | {V20_BASELINE['generated']} | {s.get('generated')} |",
        f"| expansions | {V20_BASELINE['expansions']} | {s.get('expansions')} |",
        f"| min FU | {V20_BASELINE['min_fu']} | {s.get('min_target_fu')} |",
        f"| min blocks | — | {s.get('min_block_count')} |",
        f"| min obstruction | — | {s.get('min_obstruction')} |",
        f"| min relaxed | — | {s.get('min_relaxed')} |",
        f"| target reveal | no | {bool(s.get('exit_classes'))} |",
        f"| elapsed s | {V20_BASELINE['elapsed_s']} | {s.get('elapsed_s')} |",
        "",
        f"- stall class: {payload.get('stall_class')}",
        f"- FU7 witness: {bool(payload.get('fu7_witness'))}",
        "",
        "## 4. Exits and downstream",
        "",
        f"- target exits={s.get('exit_classes')} known_dead={payload.get('known_dead_exits')} "
        f"new={payload.get('new_exits')} off_target={s.get('off_target_reveals')}",
        f"- fd10={payload.get('fd10')} foundation={payload.get('foundation')}",
        "",
        "## 5. Exactly one next recommendation",
        "",
        payload.get("next_recommendation") or "",
        "",
        "## Integrity",
        "",
        payload.get("interpretation") or "",
        "",
        f"Base SHA `{payload.get('base_sha')}`. Deal `deals/4925153.txt`.",
        "No column-7 arm. No extra heuristic. No production change.",
        "",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening = SpiderState.from_cards(list(load_deal(DEAL_PATH)))
    prefix = parse_moves_file(FD13_FIXTURE)
    fd13 = opening.clone()
    cost = replay_actions(fd13, prefix)
    ok = pack_state(fd13).hex() == FD13_HEX and len(prefix) == 102 and cost == 102
    print(f"FD13_OK {ok}", flush=True)
    if not ok:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "fd13 fixture failed"}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1

    targets = census_buried_targets(fd13)
    col1 = next(row for row in targets if row["signature_key"] == COL1_KEY)
    sig = tuple((s, r) for s, r in col1["signature"])
    assert signature_key(sig) == COL1_KEY
    assert face_down_signature(fd13.columns[0]) == sig
    audit = target_stack_audit(fd13, sig)
    print(f"ROOT_AUDIT blocks={audit['block_count']} obst={audit['landing_obstruction']} relaxed={audit['relaxed_clearance']} fu={audit['face_up_count']}", flush=True)
    print(f"ROOT_BLOCKS {json.dumps(audit['blocks'])}", flush=True)
    clf = stock0_tableau_classifier_complete(fd13)
    print(f"CLASSIFIER complete={clf['complete']}", flush=True)

    print("SEARCH landing-aware column 1", flush=True)
    result = target_directed_plateau(
        fd13,
        sig,
        max_unique=500_000,
        time_limit_s=600.0,
        rss_abort_mb=2 * 1024.0,
        max_exits=32,
        plateau_fd=13,
        mode="landing",
    )
    print(
        f"SEARCH unique={result.unique} gen={result.generated} exp={result.expansions} "
        f"min_fu={result.min_target_fu} min_blocks={result.min_block_count} min_obst={result.min_obstruction} "
        f"min_rel={result.min_relaxed} exits={result.exit_classes} stop={result.stop_reason} "
        f"elapsed={result.elapsed_s:.1f}",
        flush=True,
    )

    dead = load_dead_fd12()
    known, new = [], []
    for rec in result.exits:
        rec = dict(rec)
        rec["class"] = "KNOWN_DEAD_EXIT" if rec["symmetry_digest"] in dead else "NEW_EXIT"
        (known if rec["class"] == "KNOWN_DEAD_EXIT" else new).append(rec)
    EXITS_JSONL.write_text("\n".join(json.dumps(r, sort_keys=True) for r in known + new) + ("\n" if result.exits else ""), encoding="utf-8")

    stall = classify_stall(result.stall_sample)
    print(f"STALL {stall} sample={len(result.stall_sample)}", flush=True)
    if result.fu7_witness:
        w = result.fu7_witness
        print(
            f"FU7 fu={w.get('target_fu')} blocks={w.get('block_count')} obst={w.get('landing_obstruction')} "
            f"head={w.get('top_block_head')} dests={w.get('legal_destinations')} empties={w.get('empty_columns')}",
            flush=True,
        )

    fd10_payload = None
    foundation = None
    downstream = None
    if new:
        sources, origin_paths = [], []
        for rec in new:
            st = fd13.clone()
            path = [tuple(a) for a in rec["actions"]]
            replay_actions(st, path)
            sources.append(st)
            origin_paths.append(path)
        print(f"DOWNSTREAM sources={len(sources)}", flush=True)
        cont = layered_reachability(
            sources=sources,
            origin_paths=origin_paths,
            max_depth=10_000,
            max_unique=750_000,
            time_limit_s=900.0,
            rss_abort_mb=3 * 1024.0,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
            stop_fd=10,
            checkpoints=(8, 12, 16, 24),
        )
        downstream = {
            "unique": cont.unique,
            "stop_reason": cont.stop_reason,
            "min_fd": cont.min_fd,
            "max_foundations": cont.max_foundations,
            "elapsed_s": cont.elapsed_s,
            "peak_rss_mb": cont.peak_rss_mb,
            "source_count": cont.source_count,
        }
        if "foundation" in cont.witnesses:
            w = cont.witnesses["foundation"]
            origin = w.get("origin") or 0
            foundation = {**w, **replay_full(opening, [prefix, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
        if "fd_le_10" in cont.witnesses:
            w = cont.witnesses["fd_le_10"]
            origin = w.get("origin") or 0
            fd10_payload = {**w, **replay_full(opening, [prefix, origin_paths[origin], [tuple(a) for a in w.get("actions") or []]])}
        print(f"DOWNSTREAM unique={cont.unique} stop={cont.stop_reason} min_fd={cont.min_fd}", flush=True)

    if fd10_payload and fd10_payload.get("ok"):
        Path(FD10_FIXTURE).write_text(
            format_moves_text([tuple(a) if a != ["deal"] else ("deal",) for a in fd10_payload["full_actions"]], header="# v0.21 fd10\n"),
            encoding="utf-8",
        )
    if foundation and foundation.get("ok"):
        Path(FOUNDATION_FIXTURE).write_text(
            format_moves_text([tuple(a) if a != ["deal"] else ("deal",) for a in foundation["full_actions"]], header="# v0.21 foundation\n"),
            encoding="utf-8",
        )

    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "fd13": {"replay_ok": True, "path": 102, "cost": cost, **inspect(fd13)},
        "classifier_complete": clf["complete"],
        "root_targets": targets,
        "root_audit": audit,
        "v20_baseline": V20_BASELINE,
        "search": {
            "unique": result.unique,
            "generated": result.generated,
            "duplicate_skips": result.duplicate_skips,
            "expansions": result.expansions,
            "max_depth": result.max_depth,
            "min_target_fu": result.min_target_fu,
            "min_block_count": result.min_block_count,
            "min_obstruction": result.min_obstruction,
            "min_relaxed": result.min_relaxed,
            "exit_classes": result.exit_classes,
            "off_target_reveals": result.off_target_reveals,
            "fu_decreases": result.fu_decreases,
            "fu_increases": result.fu_increases,
            "fu_returns": result.fu_returns,
            "elapsed_s": result.elapsed_s,
            "peak_rss_mb": result.peak_rss_mb,
            "stop_reason": result.stop_reason,
            "first_reveal_depth": result.first_reveal_depth,
            "first_reveal_unique": result.first_reveal_unique,
        },
        "records": result.records,
        "fu7_witness": result.fu7_witness,
        "stall_sample": result.stall_sample,
        "stall_class": stall,
        "known_dead_exits": len(known),
        "new_exits": len(new),
        "downstream": downstream,
        "fd10": bool(fd10_payload and fd10_payload.get("ok")),
        "foundation": bool(foundation and foundation.get("ok")),
        "fd10_witness": fd10_payload,
        "foundation_witness": foundation,
        "production_unchanged": True,
        "column7_tested": False,
        "heuristic_proof_authority": False,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. min_fu={result.min_target_fu} min_blocks={result.min_block_count} "
        f"min_obst={result.min_obstruction} min_rel={result.min_relaxed} exits={result.exit_classes} "
        f"stall={stall}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
