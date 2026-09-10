#!/usr/bin/env python3
"""v0.17: post-stock tableau column-symmetry audit."""

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
from spider.packed_state import (
    column_permutation_mapping,
    pack_post_stock_symmetry_state,
    pack_search_identity,
    pack_state,
    permute_tableau_columns,
    unpack_state,
)
from spider.simple_post_deal_audit import census_legal_by_tier, foundation_proximity
from spider.simple_workspace_reachability import (
    empty_column_indices,
    face_down_count,
    layered_reachability,
)

EXPERIMENT = "simple_progressive_post_stock_column_symmetry_v0_17"
BASE_SHA = "6eb0edc324203725e79e429630b5cd8f46498530"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
SEED_FIXTURE = ROOT / "solutions" / "4925153_simple_fd13_empty1_seed.moves.txt"
DEAD_FD11 = ROOT / "solutions" / "4925153_simple_v0_13_fd11.moves.txt"
TRUE_CROSSING = (
    ROOT / "research" / "results" / "simple_progressive_fd11_first_crossing_v0_16" / "true_first_crossing.jsonl"
)
RESULT = ROOT / "docs" / "research" / f"{EXPERIMENT}.json"
REPORT = ROOT / "docs" / "research" / f"{EXPERIMENT}.md"
OUT_DIR = ROOT / "research" / "results" / EXPERIMENT
CANDIDATES = OUT_DIR / "true_crossing_symmetry_classes.jsonl"
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
ORDERED_LAYERS = [
    {"depth": 0, "frontier": 1, "unique": 23},
    {"depth": 1, "frontier": 22, "unique": 159},
    {"depth": 2, "frontier": 136, "unique": 753},
    {"depth": 3, "frontier": 594, "unique": 3121},
    {"depth": 4, "frontier": 2368, "unique": 11478},
    {"depth": 5, "frontier": 8357, "unique": 38445},
    {"depth": 6, "frontier": 26967, "unique": 123518},
    {"depth": 7, "frontier": 85073, "unique": 384710},
    {"depth": 8, "frontier": 261192, "unique": 1144490},
    {"depth": 9, "frontier": 759780, "unique": 1144490},
]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp.replace(path)


def identity_fn(state: SpiderState) -> bytes:
    return pack_search_identity(state, post_stock_column_symmetry=True)


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
        and len(seed.stock) == 0
        and face_down_count(seed) == 13
        and len(seed.foundations) == 0
    )
    return opening, prefix, seed, {"ok": ok, "digest": digest, "cost": cost, "path_length": len(prefix)}


def compact_search(result) -> dict:
    return {
        "completed_generated_depth": result.completed_generated_depth,
        "completed_expanded_depth": result.completed_expanded_depth,
        "unique": result.unique,
        "generated": result.generated,
        "duplicate_skips": result.duplicate_skips,
        "min_fd": result.min_fd,
        "max_foundations": result.max_foundations,
        "max_empties": result.max_empties,
        "max_run": result.max_run,
        "elapsed_s": result.elapsed_s,
        "peak_rss_mb": result.peak_rss_mb,
        "stop_reason": result.stop_reason,
        "layers": result.layers,
        "first_depth": result.first_depth,
        "fresh_tt": result.fresh_tt,
        "source_count": result.source_count,
    }


def mapping_1based(mapping):
    if mapping is None:
        return None
    return {str(i + 1): mapping[i] + 1 for i in range(len(mapping))}


def swap_pairs_1based(mapping):
    if mapping is None:
        return []
    pairs = []
    seen = set()
    for src, dst in enumerate(mapping):
        if src == dst or src in seen:
            continue
        pairs.append([src + 1, dst + 1])
        seen.add(src)
        seen.add(dst)
    return pairs


def inspect_state(state: SpiderState) -> dict:
    census = census_legal_by_tier(state)
    prox = foundation_proximity(state)
    return {
        "fd": face_down_count(state),
        "stock": len(state.stock),
        "foundations": len(state.foundations),
        "empties": list(empty_column_indices(state)),
        "longest_run": prox["longest_exposed_same_suit_run"],
        "legal": census["legal"],
        "a": census["a"],
        "b": census["b"],
        "c": census["c"],
        "d": census["d"],
        "ordered_digest": pack_state(state).hex(),
        "symmetry_digest": pack_post_stock_symmetry_state(state).hex() if not state.stock else None,
    }


def replay_full(opening: SpiderState, prefix, local) -> dict:
    actions = list(prefix) + [tuple(a) for a in local]
    end = opening.clone()
    try:
        paid = replay_actions(end, actions)
        return {
            "ok": True,
            "cost": paid,
            "path_length": len(actions),
            "fd": face_down_count(end),
            "foundations": len(end.foundations),
            "empties": list(empty_column_indices(end)),
            "digest": pack_state(end).hex(),
            "full_actions": [list(a) if a != ("deal",) else ["deal"] for a in actions],
        }
    except (ValueError, AssertionError) as exc:
        return {"ok": False, "error": str(exc), "path_length": len(actions), "full_actions": []}


def witness_payload(opening, prefix, result, kind: str) -> dict:
    raw = (result.witnesses or {}).get(kind) or {}
    local = raw.get("actions") or []
    replayed = replay_full(opening, prefix, local)
    return {
        "kind": kind,
        "depth": raw.get("depth"),
        "fd": raw.get("fd"),
        "foundations": raw.get("foundations"),
        "empties": raw.get("empties"),
        "local_actions": local,
        "local_cost": raw.get("local_cost"),
        "empty_sequence": raw.get("empty_sequence"),
        "full_actions": replayed.get("full_actions") or [],
        "replay_ok": replayed.get("ok"),
        "replay_cost": replayed.get("cost"),
        "replay_fd": replayed.get("fd"),
        "replay_digest": replayed.get("digest"),
        "replay_error": replayed.get("error"),
    }


def layer_comparison(treatment_layers) -> list:
    by_depth = {row["depth"]: row for row in treatment_layers}
    rows = []
    for ordered in ORDERED_LAYERS:
        depth = ordered["depth"]
        treat = by_depth.get(depth)
        if treat is None:
            rows.append(
                {
                    "depth": depth,
                    "ordered_frontier": ordered["frontier"],
                    "symmetry_frontier": None,
                    "ordered_unique": ordered["unique"],
                    "symmetry_unique": None,
                    "reduction": None,
                    "available": False,
                }
            )
            continue
        sym_front = treat.get("frontier_size")
        sym_unique = treat.get("cumulative_unique")
        reduction = None if not sym_unique else round(ordered["unique"] / sym_unique, 4)
        rows.append(
            {
                "depth": depth,
                "ordered_frontier": ordered["frontier"],
                "symmetry_frontier": sym_front,
                "ordered_unique": ordered["unique"],
                "symmetry_unique": sym_unique,
                "frontier_reduction": None if not sym_front else round(ordered["frontier"] / sym_front, 4),
                "reduction": reduction,
                "available": True,
            }
        )
    return rows


def choose_verdict(payload: dict) -> tuple[str, str]:
    if payload.get("contract_failure"):
        return "SYMMETRY_CONTRACT_FAILURE", payload.get("contract_failure")
    phase5 = payload.get("phase5") or {}
    if payload.get("search_explosion"):
        return "SYMMETRY_SEARCH_STATE_EXPLOSION", payload.get("search_explosion")
    if not phase5:
        return "INCONCLUSIVE", "phase 5 did not run"
    outside_eq = (payload.get("phase2") or {}).get("symmetry_keys_equal")
    completed = phase5.get("completed_generated_depth")
    rows = payload.get("layer_comparison") or []
    available = [row for row in rows if row.get("available") and row.get("reduction")]
    max_reduction = max((row["reduction"] for row in available), default=1.0)
    last = available[-1]["reduction"] if available else 1.0
    substantial = last >= 1.5 or max_reduction >= 2.0
    modest = last < 1.5
    if completed is not None and completed < 8 and phase5.get("stop_reason") not in ("max depth", "frontier empty"):
        if outside_eq:
            return (
                "V016_OUTSIDE_FD11_IS_ONLY_COLUMN_PERMUTATION",
                "the v0.16 outsider is a column permutation of the dead fd11, but the shallow search did not finish",
            )
        return "SYMMETRY_SEARCH_STATE_EXPLOSION", "bounded treatment did not complete enough of the depth envelope"
    if outside_eq and modest:
        return (
            "V016_OUTSIDE_FD11_IS_ONLY_COLUMN_PERMUTATION",
            "the supposed outside-bubble fd11 is an exact whole-column permutation of the dead checkpoint; broader reduction is modest",
        )
    if substantial:
        return (
            "POST_STOCK_COLUMN_SYMMETRY_HIGH_VALUE",
            "the stock=0 column quotient is exact, preserves hard reachability, and substantially reduces the measured search",
        )
    return (
        "POST_STOCK_COLUMN_SYMMETRY_VALID_LOW_VALUE",
        "the stock=0 column quotient is exact but the measured state reduction is modest",
    )


def next_recommendation(verdict: str) -> str:
    if verdict == "SYMMETRY_CONTRACT_FAILURE":
        return "Stop. Do not integrate the quotient. Investigate the failed automorphism before any further slack search."
    if verdict == "POST_STOCK_COLUMN_SYMMETRY_HIGH_VALUE":
        return (
            "The post-stock column quotient is an exact symmetry reduction. Next: keep it research-only "
            "until a dedicated integration task; do not add two-move slack here."
        )
    if verdict == "V016_OUTSIDE_FD11_IS_ONLY_COLUMN_PERMUTATION":
        return (
            "The v0.16 outsider is not a new fd11. Next: do not search two-move slack in this line "
            "until tasked separately; do not integrate the quotient into production."
        )
    if verdict == "POST_STOCK_COLUMN_SYMMETRY_VALID_LOW_VALUE":
        return (
            "The automorphism is real but cheap at the measured depths. Next: do not integrate it; "
            "do not add two-move slack here."
        )
    if verdict == "SYMMETRY_SEARCH_STATE_EXPLOSION":
        return "Contract stands; do not raise limits here. Report the last completed layer and stop."
    return "Reproduce the post-stock symmetry audit before changing identity policy."


def write_report(payload: dict) -> None:
    p2 = payload.get("phase2") or {}
    p3 = payload.get("phase3") or {}
    p4 = payload.get("phase4") or {}
    p5 = payload.get("phase5") or {}
    lines = [
        "# Simple Progressive Search v0.17: Post-Stock Tableau Column-Symmetry Audit",
        "",
        "## 1. Verdict",
        "",
        f"`{payload.get('verdict')}` — {payload.get('note')}.",
        "",
        "Production `pack_state` / `solve_progressive` are unchanged. The post-stock",
        "column quotient is research-only. It is an exact game automorphism at stock=0,",
        "not heuristic pruning, if and only if the equivalence contract holds.",
        "",
        "## 2. Formal stock=0 symmetry contract",
        "",
        "- ORDERED EXACT IDENTITY: `pack_state` serialises columns 0..9 in physical order.",
        "- POST-STOCK SYMMETRY IDENTITY: when stock is empty, encode each complete column",
        "  exactly (face-down order + face-up order), sort the ten encodings, and keep",
        "  canonical foundations. Magic `SPS1`. Never unpack this blob as a SpiderState.",
        "- Stock remaining: `pack_post_stock_symmetry_state` rejects; search identity",
        "  falls back to ordered `pack_state`. Arbitrary column swaps of stock-bearing",
        "  states are not identified.",
        "- Concrete representative: BFS stores ordered `pack_state` for every class and",
        "  generates legal moves on that physical labelling. Replay concatenates the",
        "  original prefix with those physical actions.",
        f"- Contract verified: {payload.get('contract_verified')}",
        "",
        "## 3. Phase 2 — v0.16 outside fd11 vs dead checkpoint",
        "",
        f"- dead ordered digest: `{p2.get('dead_ordered_digest')}`",
        f"- outside ordered digest: `{p2.get('outside_ordered_digest')}`",
        f"- ordered keys equal: {p2.get('ordered_keys_equal')}",
        f"- symmetry keys equal: {p2.get('symmetry_keys_equal')}",
        f"- 0-based mapping dead→outside: {p2.get('mapping_0based')}",
        f"- 1-based mapping dead→outside: {p2.get('mapping_1based')}",
        f"- 1-based swapped pairs: {p2.get('swap_pairs_1based')}",
        "",
        "## 4. Phase 3 — six true depth-10 fd11 states",
        "",
        f"- ordered canonical count: {p3.get('ordered_count')}",
        f"- post-stock symmetry-class count: {p3.get('symmetry_class_count')}",
        f"- class multiplicities: {p3.get('class_multiplicities')}",
        "",
        "| # | bubble | ordered digest prefix | symmetry class |",
        "| ---: | --- | --- | ---: |",
    ]
    for rec in p3.get("members") or []:
        digest = rec.get("ordered_digest") or ""
        lines.append(
            f"| {rec.get('index')} | {rec.get('bubble_member')} | `{digest[:16]}…` | {rec.get('class_id')} |"
        )
    ctrl = p4.get("control") or {}
    treat = p4.get("treatment") or {}
    lines.extend(
        [
            "",
            "## 5. Phase 4 — dead-bubble ordered vs symmetry",
            "",
            f"- control unique={ctrl.get('unique')} stop={ctrl.get('stop_reason')} "
            f"min_fd={ctrl.get('min_fd')} empties={ctrl.get('max_empties')} "
            f"fnd={ctrl.get('max_foundations')} max_depth={ctrl.get('completed_generated_depth')}",
            f"- treatment unique={treat.get('unique')} stop={treat.get('stop_reason')} "
            f"min_fd={treat.get('min_fd')} empties={treat.get('max_empties')} "
            f"fnd={treat.get('max_foundations')} max_depth={treat.get('completed_generated_depth')}",
            f"- quotient of control hexes={p4.get('control_symmetry_classes')} "
            f"reduction={p4.get('reduction')} qualitative_ok={p4.get('qualitative_ok')}",
            "",
            "## 6. Phase 5 — shallow symmetry search from the fd13 seed",
            "",
            f"- stop={p5.get('stop_reason')} unique={p5.get('unique')} generated={p5.get('generated')} "
            f"dups={p5.get('duplicate_skips')} elapsed={p5.get('elapsed_s')} rss={p5.get('peak_rss_mb')}",
            f"- min_fd={p5.get('min_fd')} fd12_depth={p5.get('fd12_depth')} fd11_depth={p5.get('fd11_depth')}",
            f"- fd12 replay={((p5.get('fd12_witness') or {}).get('replay_ok'))} "
            f"fd11 replay={((p5.get('fd11_witness') or {}).get('replay_ok'))}",
            "",
            "| Depth | Ordered frontier | Symmetry frontier | Ordered cumulative unique | Symmetry cumulative unique | Reduction |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload.get("layer_comparison") or []:
        lines.append(
            f"| {row.get('depth')} | {row.get('ordered_frontier')} | {row.get('symmetry_frontier')} | "
            f"{row.get('ordered_unique')} | {row.get('symmetry_unique')} | {row.get('reduction')} |"
        )
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
            "Production pack_state and solve_progressive are unchanged. Two-move slack was not searched.",
            "The quotient is not integrated.",
            "",
        ]
    )
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opening, prefix, seed, seed_info = load_seed()
    if not seed_info["ok"]:
        payload = {"experiment": EXPERIMENT, "verdict": "INCONCLUSIVE", "note": "seed failed", "seed": seed_info}
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1
    print("SEED_OK", flush=True)

    dead_actions = parse_moves_file(DEAD_FD11)
    dead = opening.clone()
    replay_actions(dead, dead_actions)
    assert pack_state(dead).hex() == DEAD_FD11_HEX
    assert len(dead.stock) == 0

    rows = [json.loads(line) for line in TRUE_CROSSING.read_text(encoding="utf-8").splitlines() if line.strip()]
    true_rows = [row for row in rows if row.get("class") == "TRUE_FIRST_CROSSING_DEPTH10"]
    outside_rows = [row for row in true_rows if not row.get("bubble_member")]
    if len(outside_rows) != 1:
        payload = {
            "experiment": EXPERIMENT,
            "verdict": "INCONCLUSIVE",
            "note": f"expected one outside true-crossing, found {len(outside_rows)}",
        }
        _write_json(RESULT, payload)
        print("VERDICT INCONCLUSIVE", flush=True)
        return 1

    outside_state = opening.clone()
    outside_local = [tuple(a) for a in outside_rows[0]["actions"]]
    replay_actions(outside_state, list(prefix) + outside_local)
    assert pack_state(outside_state).hex() == outside_rows[0]["digest"]

    mapping = column_permutation_mapping(dead, outside_state)
    perm = None if mapping is None else [mapping.index(i) for i in range(10)]
    reconstructed = None
    if perm is not None:
        reconstructed = pack_state(permute_tableau_columns(dead, perm)).hex()
    phase2 = {
        "dead_ordered_digest": pack_state(dead).hex(),
        "outside_ordered_digest": pack_state(outside_state).hex(),
        "dead_symmetry_digest": pack_post_stock_symmetry_state(dead).hex(),
        "outside_symmetry_digest": pack_post_stock_symmetry_state(outside_state).hex(),
        "ordered_keys_equal": pack_state(dead) == pack_state(outside_state),
        "symmetry_keys_equal": pack_post_stock_symmetry_state(dead) == pack_post_stock_symmetry_state(outside_state),
        "mapping_0based": mapping,
        "mapping_1based": mapping_1based(mapping),
        "swap_pairs_1based": swap_pairs_1based(mapping),
        "reconstructed_outside_from_perm": reconstructed,
        "reconstruction_matches": reconstructed == pack_state(outside_state).hex(),
        "dead": inspect_state(dead),
        "outside": inspect_state(outside_state),
        "suggested_1based_3_and_5": mapping == [0, 1, 4, 3, 2, 5, 6, 7, 8, 9],
    }
    print(
        f"PHASE2 ordered_eq={phase2['ordered_keys_equal']} symmetry_eq={phase2['symmetry_keys_equal']} "
        f"pairs={phase2['swap_pairs_1based']}",
        flush=True,
    )

    members = []
    ordered_keys = []
    symmetry_keys = []
    for index, rec in enumerate(true_rows, 1):
        st = opening.clone()
        replay_actions(st, list(prefix) + [tuple(a) for a in rec["actions"]])
        ordered = pack_state(st)
        symmetry = pack_post_stock_symmetry_state(st)
        ordered_keys.append(ordered)
        symmetry_keys.append(symmetry)
        members.append(
            {
                "index": index,
                "bubble_member": rec.get("bubble_member"),
                "ordered_digest": ordered.hex(),
                "symmetry_digest": symmetry.hex(),
                "actions": rec.get("actions"),
                "fd": face_down_count(st),
                "empties": list(empty_column_indices(st)),
                "longest_run": rec.get("longest_run"),
            }
        )
    unique_sym = []
    for key in symmetry_keys:
        if key not in unique_sym:
            unique_sym.append(key)
    class_of = {key.hex(): i + 1 for i, key in enumerate(unique_sym)}
    for rec, key in zip(members, symmetry_keys):
        rec["class_id"] = class_of[key.hex()]
    counts = Counter(rec["class_id"] for rec in members)
    phase3 = {
        "ordered_count": len({k.hex() for k in ordered_keys}),
        "symmetry_class_count": len(unique_sym),
        "class_multiplicities": {str(k): v for k, v in sorted(counts.items())},
        "members": members,
    }
    CANDIDATES.write_text("\n".join(json.dumps(rec, sort_keys=True) for rec in members) + "\n", encoding="utf-8")
    print(
        f"PHASE3 ordered={phase3['ordered_count']} symmetry={phase3['symmetry_class_count']} "
        f"mult={phase3['class_multiplicities']}",
        flush=True,
    )

    print("PHASE4 control ordered bubble", flush=True)
    control = layered_reachability(
        dead,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=60.0,
        rss_abort_mb=4 * 1024.0,
        include_visited_hex=True,
        checkpoints=(),
    )
    control_classes = set()
    for hexkey in control.visited_hex:
        control_classes.add(pack_post_stock_symmetry_state(unpack_state(bytes.fromhex(hexkey))).hex())
    print("PHASE4 treatment symmetry bubble", flush=True)
    treatment = layered_reachability(
        dead,
        max_depth=10_000,
        max_unique=100_000,
        time_limit_s=60.0,
        rss_abort_mb=4 * 1024.0,
        identity_fn=identity_fn,
        checkpoints=(),
    )
    qualitative_ok = (
        control.min_fd == treatment.min_fd
        and (control.min_fd <= 10) == (treatment.min_fd <= 10)
        and (control.max_foundations >= 1) == (treatment.max_foundations >= 1)
        and (control.max_empties >= 1) == (treatment.max_empties >= 1)
        and control.max_foundations == treatment.max_foundations
        and treatment.unique == len(control_classes)
    )
    contract_failure = None
    if not qualitative_ok:
        contract_failure = (
            "treatment unique/hard-progress disagrees with the ordered bubble quotient "
            f"(control unique={control.unique} classes={len(control_classes)} "
            f"treatment unique={treatment.unique} min_fd {control.min_fd}->{treatment.min_fd} "
            f"fnd {control.max_foundations}->{treatment.max_foundations} "
            f"empty {control.max_empties}->{treatment.max_empties})"
        )
    phase4 = {
        "control": compact_search(control),
        "treatment": compact_search(treatment),
        "control_symmetry_classes": len(control_classes),
        "reduction": None if not treatment.unique else round(control.unique / treatment.unique, 4),
        "qualitative_ok": qualitative_ok,
    }
    print(
        f"PHASE4 control={control.unique} treatment={treatment.unique} classes={len(control_classes)} "
        f"ok={qualitative_ok}",
        flush=True,
    )
    if contract_failure:
        payload = {
            "experiment": EXPERIMENT,
            "base_sha": BASE_SHA,
            "verdict": "SYMMETRY_CONTRACT_FAILURE",
            "note": contract_failure,
            "contract_failure": contract_failure,
            "contract_verified": False,
            "seed": seed_info,
            "phase2": phase2,
            "phase3": phase3,
            "phase4": phase4,
        }
        payload["next_recommendation"] = next_recommendation("SYMMETRY_CONTRACT_FAILURE")
        _write_json(RESULT, payload)
        write_report(payload)
        print("VERDICT SYMMETRY_CONTRACT_FAILURE", flush=True)
        return 1

    print("PHASE5 symmetry layered search from fd13 seed", flush=True)
    search = layered_reachability(
        seed,
        max_depth=9,
        max_unique=2_000_000,
        time_limit_s=1800.0,
        rss_abort_mb=4 * 1024.0,
        identity_fn=identity_fn,
        checkpoints=(1, 2, 3, 4, 5, 6, 7, 8),
    )
    fd12 = witness_payload(opening, prefix, search, "fd_le_12")
    fd11 = witness_payload(opening, prefix, search, "fd_le_11")
    if search.min_fd <= 12 and (not fd12.get("replay_ok") or fd12.get("depth") != 8):
        contract_failure = f"fd12 regression: depth={fd12.get('depth')} replay={fd12.get('replay_ok')}"
    if search.min_fd <= 11 and (not fd11.get("replay_ok") or fd11.get("depth") != 9):
        contract_failure = f"fd11 regression: depth={fd11.get('depth')} replay={fd11.get('replay_ok')}"
    if search.first_depth.get("fd_le_12") not in (None, 8) and search.min_fd <= 12:
        contract_failure = f"fd12 min depth became {search.first_depth.get('fd_le_12')}"
    if search.first_depth.get("fd_le_11") not in (None, 9) and search.min_fd <= 11:
        contract_failure = f"fd11 min depth became {search.first_depth.get('fd_le_11')}"
    generated = search.generated or 0
    dups = search.duplicate_skips or 0
    phase5 = {
        **compact_search(search),
        "fd12_depth": search.first_depth.get("fd_le_12"),
        "fd11_depth": search.first_depth.get("fd_le_11"),
        "fd12_witness": fd12,
        "fd11_witness": fd11,
        "duplicate_rate": None if not generated else round(dups / generated, 6),
        "ordered_duplicate_rate_v014_depth8_expand": round(1772317 / 2532097, 6),
    }
    comparison = layer_comparison(search.layers)
    search_explosion = None
    if search.stop_reason in ("unique limit", "time limit", "rss abort") and search.completed_generated_depth < 9:
        search_explosion = (
            f"stopped at {search.stop_reason} after generated depth "
            f"{search.completed_generated_depth} unique={search.unique}"
        )
    payload = {
        "experiment": EXPERIMENT,
        "base_sha": BASE_SHA,
        "contract_verified": contract_failure is None,
        "contract_failure": contract_failure,
        "search_explosion": search_explosion,
        "seed": seed_info,
        "phase2": phase2,
        "phase3": phase3,
        "phase4": phase4,
        "phase5": phase5,
        "layer_comparison": comparison,
        "negative_stock_test": "pack_post_stock_symmetry_state raises; pack_search_identity keeps ordered identity",
        "production_unchanged": True,
        "two_move_slack": False,
        "quotient_integrated": False,
    }
    verdict, note = choose_verdict(payload)
    if contract_failure:
        verdict, note = "SYMMETRY_CONTRACT_FAILURE", contract_failure
    payload["verdict"] = verdict
    payload["note"] = note
    payload["next_recommendation"] = next_recommendation(verdict)
    payload["interpretation"] = (
        f"Verdict {verdict}. ordered_eq={phase2['ordered_keys_equal']} "
        f"symmetry_eq={phase2['symmetry_keys_equal']} "
        f"swap_1based={phase2['swap_pairs_1based']} "
        f"true-crossing ordered={phase3['ordered_count']} symmetry={phase3['symmetry_class_count']} "
        f"bubble {control.unique}->{treatment.unique} "
        f"fd12={phase5.get('fd12_depth')} fd11={phase5.get('fd11_depth')} "
        f"search unique={search.unique} stop={search.stop_reason}."
    )
    payload["waste_fraction_unique_through_depth9"] = (
        None if not search.unique else round(1.0 - search.unique / 1_144_490, 4)
    )
    _write_json(RESULT, payload)
    write_report(payload)
    print(
        f"PHASE5 unique={search.unique} stop={search.stop_reason} fd12={phase5.get('fd12_depth')} "
        f"fd11={phase5.get('fd11_depth')} elapsed={search.elapsed_s:.1f}",
        flush=True,
    )
    print(f"VERDICT {verdict}", flush=True)
    return 0 if verdict != "INCONCLUSIVE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
