#!/usr/bin/env python3
"""v0.16: true one-move-slack fd11 first-crossing audit."""

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
from spider.packed_state import pack_state, unpack_state
from spider.simple_post_deal_audit import census_legal_by_tier, describe_legal_actions, foundation_proximity
from spider.simple_progressive_solver import apply_action, format_moves_text
from spider.simple_workspace_reachability import (
    classify_first_crossing,
    empty_column_indices,
    empty_transition_events,
    face_down_count,
    fd_trace,
    first_empty_use_on_path,
    first_fd_leq_depth,
    layered_reachability,
)

EXPERIMENT = "simple_progressive_fd11_first_crossing_v0_16"
BASE_SHA = "062f7b4ff034fec1aaee3d4afaca1c5b9bce87f8"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
V15_JSONL = (
    ROOT / "research" / "results" / "simple_progressive_fd11_one_move_slack_v0_15" / "depth10_fd11_candidates.jsonl"
)
VIABLE = ROOT / "solutions" / "4925153_simple_v0_16_fd11_viable.moves.txt"
FD10_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_16_fd10.moves.txt"
FOUNDATION_FIXTURE = ROOT / "solutions" / "4925153_simple_v0_16_first_foundation.moves.txt"
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
CANDIDATES = ROOT / "research" / "results" / EXPERIMENT / "true_first_crossing.jsonl"
EXPECTED_HEX = (
    "53504b310100000004093a2c360835042302310b0d1c3b050515191b11282d0c2b1a290000"
    "00121413121d071d1c1b1a19181716153433323100022d2c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
DEAD_FD11_HEX = (
    "53504b3101000000040c3a2c360835042302310b0d1c3b1a2928030115191b1100032d2c2b"
    "00121413121d071d1c1b1a19181716153433323100022d0c00080d0c262139383706041118"
    "360a2a280706050403020911033d3c0b0a290827000812272a0524133201000d3d3c3b3a39"
    "3837262524232221000b1716352b14092534332201"
)
EXPECTED_BUBBLE = 1728


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
    ok = (
        digest == EXPECTED_HEX
        and cost == 102
        and len(prefix) == 102
        and list(empty_column_indices(seed)) == [2]
    )
    return opening, prefix, seed, {"ok": ok, "digest": digest, "cost": cost}


def replay_combined(opening: SpiderState, parts: list) -> dict:
    combined = []
    for part in parts:
        combined.extend(tuple(a) if not isinstance(a, tuple) else a for a in part)
    end = opening.clone()
    try:
        paid = replay_actions(end, combined)
        prox = foundation_proximity(end)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(combined),
            "fd": face_down_count(end),
            "stock_rows": len(end.stock) // 10,
            "foundations": len(end.foundations),
            "empties": list(empty_column_indices(end)),
            "longest_run": prox["longest_exposed_same_suit_run"],
            "digest": pack_state(end).hex(),
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(combined)}


def inspect_state(state: SpiderState) -> dict:
    census = census_legal_by_tier(state)
    rows = describe_legal_actions(state)
    prox = foundation_proximity(state)
    return {
        "empties": list(empty_column_indices(state)),
        "empty_count": sum(1 for col in state.columns if col.is_empty()),
        "longest_run": prox["longest_exposed_same_suit_run"],
        "adjacencies": prox["exposed_same_suit_adjacencies"],
        "blocks": prox["movable_same_suit_blocks"],
        "legal": census["legal"],
        "a": census["a"],
        "b": census["b"],
        "c": census["c"],
        "d": census["d"],
        "immediate_uncover": any(row.get("uncovers_face_down") for row in rows),
        "immediate_empty_create": any(row.get("creates_empty") for row in rows),
        "immediate_foundation": census["has_immediate_foundation_move"],
    }


def workspace_on_path(root: SpiderState, actions: list) -> dict:
    first_use = first_empty_use_on_path(root, actions)
    seq = [list(empty_column_indices(root))]
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
    return {
        "start_empties": seq[0],
        "end_empties": seq[-1],
        "empty_sequence": seq,
        "consumed": events.count("EMPTY_CONSUMED"),
        "transferred": events.count("EMPTY_TRANSFERRED"),
        "recreated": events.count("EMPTY_RECREATED"),
        "first_empty_use": first_use,
        "timing": "immediate" if first_use and first_use.get("immediate") else ("delayed" if first_use else "never"),
    }


def compact_search(result) -> dict:
    return {
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "unique": result.unique,
        "generated": result.generated,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_empties": result.max_empties,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "layers": result.layers,
        "collected_complete": result.collected_complete,
        "collect_partial": result.collect_partial,
        "parent_fd_counts": {str(k): v for k, v in (result.parent_fd_counts or {}).items()},
        "skipped_expand_parents": result.skipped_expand_parents,
        "stream_discarded": result.stream_discarded,
        "keys_before_stream": result.keys_before_stream,
        "last_layer_generated": result.last_layer_generated,
        "source_count": result.source_count,
        "cross_origin_dups": result.cross_origin_dups,
        "fresh_tt": result.fresh_tt,
        "imported_keys": result.imported_keys,
        "first_depth": result.first_depth,
        "depth_expanded_frac": result.depth_expanded_frac,
    }


def audit_candidate(seed: SpiderState, rec: dict, bubble: set[str]) -> dict:
    actions = [tuple(a) for a in rec["actions"]]
    try:
        trace = fd_trace(seed, actions)
        cls = classify_first_crossing(trace)
        end = seed.clone()
        replay_actions(end, actions)
        digest = pack_state(end).hex()
    except (ValueError, AssertionError) as exc:
        return {"class": "INVALID_OR_REPLAY_FAILURE", "error": str(exc), "actions": rec["actions"]}
    info = inspect_state(end)
    return {
        "digest": digest,
        "actions": rec["actions"],
        "class": cls,
        "first_fd11_depth": first_fd_leq_depth(trace, 11),
        "parent_fd": None if len(trace) < 10 else trace[9],
        "child_fd": None if len(trace) < 11 else trace[10],
        "fd_trace": trace,
        "bubble_member": digest in bubble,
        "is_dead_min_depth": digest == DEAD_FD11_HEX,
        **info,
    }


def continue_from(state: SpiderState, *, cap_unique: int, cap_time: float, cap_rss: float, max_depth: int):
    return layered_reachability(
        state,
        max_depth=max_depth,
        max_unique=cap_unique,
        time_limit_s=cap_time,
        rss_abort_mb=cap_rss,
        stop_fd=10,
        checkpoints=(),
    )


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("foundation"):
        if payload.get("early_confirmed"):
            return "EXISTING_PARTIAL_TRUE_SLACK_REACHES_FD10", "an already-harvested true first-crossing reached a foundation"
        return "TRUE_ONE_MOVE_SLACK_REACHES_FOUNDATION", "a genuine first-crossing depth-10 fd11 reached a foundation"
    if payload.get("fd10"):
        if payload.get("early_confirmed"):
            return "EXISTING_PARTIAL_TRUE_SLACK_REACHES_FD10", "an already-harvested true first-crossing reached fd10"
        return "TRUE_ONE_MOVE_SLACK_REACHES_FD10", "a genuine first-crossing depth-10 fd11 reached fd10"
    phase2 = payload.get("phase2") or {}
    if payload.get("phase2_needed") and not phase2.get("collected_complete"):
        return "TRUE_DEPTH10_CENSUS_INCOMPLETE", "fd12-parent enumeration did not complete"
    outside = payload.get("outside_bubble_count") or 0
    true_n = payload.get("true_first_crossing_count") or 0
    if true_n > 0 and outside == 0 and (not payload.get("phase2_needed") or phase2.get("collected_complete")):
        return "ALL_TRUE_DEPTH10_FD11_IN_DEAD_BUBBLE", "all true first-crossing depth-10 fd11 states lie in the dead bubble"
    if payload.get("phase2_ran") and phase2.get("collected_complete") and true_n == 0:
        return "NO_TRUE_DEPTH10_FD11_ALTERNATIVE", "complete census finds no genuine new depth-10 first-crossing fd11"
    if outside > 0 and not payload.get("fd10"):
        return "TRUE_ONE_MOVE_SLACK_CANDIDATES_EXIST_BUT_STALL", "outside-bubble first-crossing candidates stall without fd10"
    if not payload.get("phase2_needed") and true_n == 0:
        return "NO_TRUE_DEPTH10_FD11_ALTERNATIVE", "existing partial harvest has no true first-crossing; full census not required by early stop"
    return "INCONCLUSIVE", "methodological or incomplete"


def next_recommendation(verdict: str) -> str:
    if verdict in (
        "TRUE_ONE_MOVE_SLACK_REACHES_FOUNDATION",
        "TRUE_ONE_MOVE_SLACK_REACHES_FD10",
        "EXISTING_PARTIAL_TRUE_SLACK_REACHES_FD10",
    ):
        return (
            "Delaying the fd11 reveal by one true primitive helps. Next: restart "
            "the reveal ratchet from that first-crossing checkpoint; do not add a heuristic."
        )
    if verdict == "TRUE_ONE_MOVE_SLACK_CANDIDATES_EXIST_BUT_STALL":
        return (
            "One-move slack produces one outside-bubble fd11, and it still stalls. "
            "Next: do not add a heuristic and do not search two-move slack in this "
            "line until that question is tasked separately."
        )
    if verdict == "ALL_TRUE_DEPTH10_FD11_IN_DEAD_BUBBLE":
        return (
            "Every true depth-10 fd11 crossing re-enters the known dead bubble. Next: "
            "do not add a heuristic; one-move slack does not create a live checkpoint."
        )
    if verdict == "NO_TRUE_DEPTH10_FD11_ALTERNATIVE":
        return (
            "No delayed-reveal fd11 exists at depth 10. Next: do not add a heuristic; "
            "a separate v0.17 may test two-move slack."
        )
    if verdict == "TRUE_DEPTH10_CENSUS_INCOMPLETE":
        return "Do not raise limits here. Report the partial fd12-parent harvest and stop."
    return "Reproduce the first-crossing audit before changing checkpoint policy."


def write_report(payload: dict) -> None:
    p0 = payload.get("phase0") or {}
    lines = [
        "# Simple Progressive Search v0.16: True One-Move-Slack FD11 First-Crossing",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "A true one-move-slack candidate has parent fd=12 and child fd=11 at primitive 10.",
        "Post-reveal rearrangements of the known dead fd11 are not slack.",
        "",
        "## 2. Phase 0 — dead fd11 bubble",
        "",
        f"- unique={p0.get('unique')} expected={EXPECTED_BUBBLE} exhausted={p0.get('exhausted')} "
        f"fd10={p0.get('fd10')} empty={p0.get('empty')} fnd={p0.get('foundation')} "
        f"elapsed={p0.get('elapsed_s')} rss={p0.get('peak_rss_mb')}",
        "",
        "## 3. Phase 1 — classify the six v0.15 candidates",
        "",
        "| # | class | first_fd11_depth | parent_fd | bubble | empties | run | legal |",
        "| ---: | --- | ---: | ---: | --- | --- | ---: | ---: |",
    ]
    for index, rec in enumerate(payload.get("v15_audit") or [], 1):
        lines.append(
            f"| {index} | {rec.get('class')} | {rec.get('first_fd11_depth')} | {rec.get('parent_fd')} | "
            f"{rec.get('bubble_member')} | {rec.get('empties')} | {rec.get('longest_run')} | {rec.get('legal')} |"
        )
    lines.extend(
        [
            "",
            f"- POST_REVEAL={payload.get('post_reveal_count')} TRUE_FIRST_CROSSING={payload.get('v15_true_count')} "
            f"outside_bubble={payload.get('v15_outside_bubble')}",
            "",
            "## 4. Early continuation",
            "",
            payload.get("early_note") or "- no genuine outside-bubble candidate among the six.",
            "",
            "## 5. Phase 2 — complete fd12-parent harvest",
            "",
        ]
    )
    p2 = payload.get("phase2")
    if not p2:
        lines.append(f"- skipped: {payload.get('phase2_skip_reason')}")
    else:
        lines.append(
            f"- complete={p2.get('collected_complete')} unique={p2.get('unique')} "
            f"keys_before_stream={p2.get('keys_before_stream')} "
            f"parent_fd_counts={p2.get('parent_fd_counts')} "
            f"skipped_non_fd12={p2.get('skipped_expand_parents')} "
            f"true_candidates={payload.get('true_first_crossing_count')} "
            f"outside_bubble={payload.get('outside_bubble_count')} "
            f"elapsed={p2.get('elapsed_s')} rss={p2.get('peak_rss_mb')}"
        )
    p3 = payload.get("phase3")
    lines.extend(["", "## 6. Phase 3 — continuation", ""])
    if not p3:
        lines.append(f"- skipped: {payload.get('phase3_skip_reason')}")
    else:
        lines.append(
            f"- sources={p3.get('source_count')} unique={p3.get('unique')} stop={p3.get('stop_reason')} "
            f"min_fd={p3.get('min_fd')} fnd={p3.get('max_foundations')} elapsed={p3.get('elapsed_s')}"
        )
    lines.extend(
        [
            "",
            "## 7. Comparison table",
            "",
            "| Candidate class | Count | In dead bubble | Outside bubble | Reaches fd10 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload.get("class_table") or []:
        lines.append(
            f"| {row.get('class')} | {row.get('count')} | {row.get('in_bubble')} | "
            f"{row.get('outside')} | {row.get('reaches_fd10')} |"
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
            "Production solve_progressive is unchanged. Depth-11 slack was not searched.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    opening, prefix, seed, seed_info = load_seed()
    if not seed_info["ok"]:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "seed failed", "seed": seed_info}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print("SEED_OK", flush=True)

    dead_actions = parse_moves_file(DEAD_FD11)
    dead_state = opening.clone()
    replay_actions(dead_state, dead_actions)
    assert pack_state(dead_state).hex() == DEAD_FD11_HEX
    print("PHASE0 regenerate dead fd11 bubble", flush=True)
    bubble_run = layered_reachability(
        dead_state,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=60.0,
        rss_abort_mb=4 * 1024.0,
        include_visited_hex=True,
        checkpoints=(),
    )
    bubble = set(bubble_run.visited_hex)
    phase0 = {
        "unique": bubble_run.unique,
        "exhausted": bubble_run.stop_reason == "frontier empty",
        "fd10": bubble_run.min_fd <= 10,
        "empty": bubble_run.max_empties >= 1,
        "foundation": bubble_run.max_foundations >= 1,
        "elapsed_s": bubble_run.elapsed_s,
        "peak_rss_mb": bubble_run.peak_rss_mb,
        "matches_expected": bubble_run.unique == EXPECTED_BUBBLE,
    }
    print(
        f"PHASE0 unique={bubble_run.unique} exhausted={phase0['exhausted']} "
        f"fd10={phase0['fd10']} elapsed={bubble_run.elapsed_s:.1f}",
        flush=True,
    )

    print("PHASE1 audit six v0.15 candidates", flush=True)
    raw = [json.loads(line) for line in V15_JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]
    audits = [audit_candidate(seed, rec, bubble) for rec in raw]
    post_n = sum(1 for a in audits if a["class"] == "POST_REVEAL_DEPTH10")
    true_n = sum(1 for a in audits if a["class"] == "TRUE_FIRST_CROSSING_DEPTH10")
    genuine = [
        a
        for a in audits
        if a["class"] == "TRUE_FIRST_CROSSING_DEPTH10" and not a["bubble_member"]
    ]
    print(
        f"PHASE1 post_reveal={post_n} true_crossing={true_n} outside_bubble={len(genuine)}",
        flush=True,
    )

    early_note = "- no genuine outside-bubble candidate among the six."
    early_confirmed = False
    fd10_payload = None
    foundation = None
    winner = None
    phase2_needed = True
    phase2_skip = None
    phase3_skip = None
    phase2_compact = None
    phase3_compact = None
    true_complete = []
    outside = []

    if genuine:
        for index, cand in enumerate(genuine):
            state = unpack_state(bytes.fromhex(cand["digest"]))
            print(f"EARLY continue genuine {index} digest={cand['digest'][:16]}...", flush=True)
            run = continue_from(state, cap_unique=100_000, cap_time=120.0, cap_rss=1024.0, max_depth=13)
            early_note = (
                f"- genuine {index}: stop={run.stop_reason} unique={run.unique} "
                f"min_fd={run.min_fd} fnd={run.max_foundations} elapsed={run.elapsed_s:.1f}"
            )
            print(f"EARLY {early_note}", flush=True)
            local_path = [tuple(a) for a in cand["actions"]]
            if run.max_foundations >= 1 and "foundation" in run.witnesses:
                wit = run.witnesses["foundation"]
                cont = [tuple(a) for a in wit.get("actions") or []]
                foundation = {
                    "combined_replay": replay_combined(opening, [prefix, local_path, cont]),
                    "workspace": workspace_on_path(state, cont),
                    "local_depth": wit.get("depth"),
                }
                winner = cand
                early_confirmed = True
                phase2_needed = False
                break
            if run.min_fd <= 10 and "fd_le_10" in run.witnesses:
                wit = run.witnesses["fd_le_10"]
                cont = [tuple(a) for a in wit.get("actions") or []]
                fd10_payload = {
                    "combined_replay": replay_combined(opening, [prefix, local_path, cont]),
                    "workspace": workspace_on_path(state, cont),
                    "local_depth": wit.get("depth"),
                }
                winner = cand
                early_confirmed = True
                phase2_needed = False
                break

    if early_confirmed and winner is not None:
        local_path = [tuple(a) for a in winner["actions"]]
        VIABLE.write_text(
            format_moves_text(list(prefix) + local_path, header="# v0.16 true first-crossing fd11 4925153\n"),
            encoding="utf-8",
        )
        dest = FOUNDATION_FIXTURE if foundation else FD10_FIXTURE
        extra = (foundation or fd10_payload or {}).get("combined_replay") or {}
        # rewrite complete route from replay path_length via stored actions in payload later
        print(f"WROTE {VIABLE}", flush=True)
        phase2_skip = "early genuine candidate confirmed viability"
        phase3_skip = phase2_skip

    if phase2_needed:
        print("PHASE2 harvest true first-crossing from fd12 depth-9 parents only", flush=True)
        harvest = layered_reachability(
            seed,
            max_depth=10,
            max_unique=5_000_000,
            time_limit_s=1800.0,
            rss_abort_mb=4 * 1024.0,
            collect_fd=11,
            collect_exact_depth=10,
            stream_last=True,
            expand_only_fd=12,
            checkpoints=(4, 8),
        )
        phase2_compact = compact_search(harvest)
        print(
            f"PHASE2 stop={harvest.stop_reason} unique={harvest.unique} complete={harvest.collected_complete} "
            f"parents={harvest.parent_fd_counts} skipped={harvest.skipped_expand_parents} "
            f"n={len(harvest.collected)} elapsed={harvest.elapsed_s:.1f}",
            flush=True,
        )
        CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
        with CANDIDATES.open("w", encoding="utf-8") as fh:
            for item in harvest.collected:
                rec = {
                    **item,
                    "bubble_member": item["digest"] in bubble,
                    "is_dead_min_depth": item["digest"] == DEAD_FD11_HEX,
                    "class": (
                        "TRUE_FIRST_CROSSING_DEPTH10"
                        if item.get("parent_fd") == 12 and item.get("fd") == 11
                        else "INVALID_OR_REPLAY_FAILURE"
                    ),
                }
                true_complete.append(rec)
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        outside = [
            rec
            for rec in true_complete
            if rec["class"] == "TRUE_FIRST_CROSSING_DEPTH10"
            and not rec["bubble_member"]
            and not rec["is_dead_min_depth"]
        ]
        if not harvest.collected_complete:
            phase3_skip = "census incomplete"
        elif not outside:
            phase3_skip = "no outside-bubble true first-crossing candidates"
        else:
            sources = [unpack_state(bytes.fromhex(rec["digest"])) for rec in outside]
            origin_paths = [[tuple(a) for a in rec["actions"]] for rec in outside]
            print(f"PHASE3 multi-source n={len(sources)}", flush=True)
            phase3 = layered_reachability(
                sources=sources,
                origin_paths=origin_paths,
                max_depth=13,
                max_unique=1_000_000,
                time_limit_s=1800.0,
                rss_abort_mb=4 * 1024.0,
                stop_fd=10,
                checkpoints=(4, 8, 12),
            )
            phase3_compact = compact_search(phase3)
            print(
                f"PHASE3 stop={phase3.stop_reason} unique={phase3.unique} min_fd={phase3.min_fd} "
                f"fnd={phase3.max_foundations}",
                flush=True,
            )
            kind = "foundation" if "foundation" in phase3.witnesses else "fd_le_10" if "fd_le_10" in phase3.witnesses else None
            if kind:
                wit = phase3.witnesses[kind]
                origin = wit.get("origin", 0)
                winner = outside[origin]
                local = [tuple(a) for a in winner["actions"]]
                cont = [tuple(a) for a in wit.get("actions") or []]
                replay = replay_combined(opening, [prefix, local, cont])
                payload_cont = {
                    "combined_replay": replay,
                    "workspace": workspace_on_path(sources[origin], cont),
                    "local_depth": wit.get("depth"),
                }
                if kind == "foundation":
                    foundation = payload_cont
                else:
                    fd10_payload = payload_cont
                VIABLE.write_text(
                    format_moves_text(list(prefix) + local, header="# v0.16 true first-crossing fd11 4925153\n"),
                    encoding="utf-8",
                )
                dest = FOUNDATION_FIXTURE if kind == "foundation" else FD10_FIXTURE
                dest.write_text(
                    format_moves_text(list(prefix) + local + cont, header=f"# v0.16 {kind} 4925153\n"),
                    encoding="utf-8",
                )

    if early_confirmed and winner is not None and (foundation or fd10_payload):
        local = [tuple(a) for a in winner["actions"]]
        cont = []
        # continuation actions already in combined replay via fixtures if written
        extra = foundation or fd10_payload
        dest = FOUNDATION_FIXTURE if foundation else FD10_FIXTURE
        # We may not have continuation action list in extra; skip rewrite if file exists

    class_table = [
        {
            "class": "v0.15 POST_REVEAL",
            "count": post_n,
            "in_bubble": sum(1 for a in audits if a["class"] == "POST_REVEAL_DEPTH10" and a.get("bubble_member")),
            "outside": sum(1 for a in audits if a["class"] == "POST_REVEAL_DEPTH10" and not a.get("bubble_member")),
            "reaches_fd10": False,
        },
        {
            "class": "v0.15 TRUE_FIRST_CROSSING",
            "count": true_n,
            "in_bubble": sum(1 for a in audits if a["class"] == "TRUE_FIRST_CROSSING_DEPTH10" and a.get("bubble_member")),
            "outside": len(genuine),
            "reaches_fd10": bool(early_confirmed and fd10_payload),
        },
        {
            "class": "complete TRUE_FIRST_CROSSING",
            "count": len(true_complete) if true_complete else (true_n if not phase2_needed else None),
            "in_bubble": sum(1 for r in true_complete if r.get("bubble_member")),
            "outside": len(outside) if true_complete else (len(genuine) if not phase2_needed else None),
            "reaches_fd10": bool(fd10_payload or foundation),
        },
    ]
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "deal": "deals/4925153.txt",
        "seed": seed_info,
        "phase0": phase0,
        "v15_audit": audits,
        "post_reveal_count": post_n,
        "v15_true_count": true_n,
        "v15_outside_bubble": len(genuine),
        "early_note": early_note,
        "early_confirmed": early_confirmed,
        "phase2_needed": phase2_needed,
        "phase2_skip_reason": phase2_skip,
        "phase2": phase2_compact,
        "phase2_ran": phase2_compact is not None,
        "phase3": phase3_compact,
        "phase3_skip_reason": phase3_skip,
        "true_first_crossing_count": len(true_complete) if true_complete else true_n,
        "outside_bubble_count": len(outside) if true_complete else len(genuine),
        "fd10": fd10_payload,
        "foundation": foundation,
        "winner": winner,
        "class_table": class_table,
    }
    verdict, note = choose_verdict(payload)
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. v15 true={true_n} post={post_n} outside={payload['outside_bubble_count']} "
        f"fd10={'yes' if fd10_payload else 'no'}."
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(f"VERDICT {verdict}", flush=True)
    print(f"WROTE {RESULT}", flush=True)
    print(f"WROTE {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
