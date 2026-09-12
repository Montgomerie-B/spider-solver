"""Research-only v0.41 Diamond missing-core bridge: form C = 6D-5D.

Reconstructs the v0.40 multi-edge frontier by replaying A/B/D witnesses,
exact-deduplicating on ordered pack_state, and searching for the first
current satisfaction of C.  Tableau only.  SD5 never expanded.
Full accumulated MW is g.  Edge history is not part of canonical identity.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spider.cards import Card, rank_str
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.simple_current_horizon import occurrence_counts
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_edges import (
    EDGES,
    diamond_adjacent_pairs,
    diamond_components,
    satisfied_core_edges,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import (
    GOOD_PLAY,
    JOIN_BREAK,
    OTHER,
    PARK,
    suit_foundation_count,
)
from spider.simple_gate1 import gate1_progress
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
V040_EDGE = {
    "A": ROOT / "docs" / "research" / "diamond_core_edge_A_v0_40.json",
    "B": ROOT / "docs" / "research" / "diamond_core_edge_B_v0_40.json",
    "C": ROOT / "docs" / "research" / "diamond_core_edge_C_v0_40.json",
    "D": ROOT / "docs" / "research" / "diamond_core_edge_D_v0_40.json",
}
V040_TWO_EDGE = ROOT / "docs" / "research" / "diamond_core_two_edge_v0_40.json"
V040_SCRIPT = ROOT / "research" / "diamond_core_edge_ratchet_v0_40.py"
GITHUB_CONTENTS_LIMIT = 1_000_000
COST_CEILING = 100
HARVEST_SLACK = 3
HARVEST_LIMIT = 256
MAX_UNIQUE = 300_000
TIME_LIMIT_S = 450.0
GLOBAL_TIME_S = 600.0
RSS_ABORT_MB = 3 * 1024.0
PREVIEW_DEPTH = 6
LOWER_TAIL_RANKS = (6, 5, 4, 3, 2, 1)
EDGE_E = (4, 3)
EXPECTED_CATEGORIES = ("A+B", "A+D", "B+D", "A+B+D")
SOURCE_PORTFOLIOS = ("A", "B", "D")

C_JOIN = "C_JOIN"
C_EXPOSE_6D = "C_EXPOSE_6D"
C_MOBILISE_5D = "C_MOBILISE_5D"
C_RETAIN_D = "C_RETAIN_D"
D_JOIN = "D_JOIN"
C_SUPPORT = "C_SUPPORT"
AB_QUALITY = "AB_QUALITY"

LABEL_RANK = {
    C_JOIN: 0,
    C_EXPOSE_6D: 1,
    C_MOBILISE_5D: 2,
    C_RETAIN_D: 3,
    D_JOIN: 4,
    C_SUPPORT: 5,
    GOOD_PLAY: 6,
    AB_QUALITY: 7,
    PARK: 8,
    OTHER: 9,
    JOIN_BREAK: 10,
    "DEAL": 11,
}

L0_LABELS = {C_JOIN, C_EXPOSE_6D, C_MOBILISE_5D, C_RETAIN_D, D_JOIN, C_SUPPORT, GOOD_PLAY}
L1_LABELS = L0_LABELS | {AB_QUALITY, PARK}


def opening_state() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL_PATH)))


def as_actions(raw) -> List[Action]:
    out: List[Action] = []
    for item in raw:
        if item == "deal" or item == ["deal"] or item == ("deal",):
            out.append(("deal",))
        else:
            out.append((int(item[0]), int(item[1]), int(item[2])))
    return out


def dump_actions(actions: Sequence[Action]):
    return [list(a) if a != ("deal",) else ["deal"] for a in actions]


def pretty_rank(rank: int) -> str:
    return rank_str(rank)


def category_from_edges(edges: Iterable[str]) -> str:
    core = tuple(sorted(e for e in edges if e in EDGES))
    if not core:
        return "NONE"
    return "+".join(core)


def classify_c_boundary(edges: Iterable[str], *, foundation: bool = False) -> str:
    """Current-state classification.  Historical edge satisfaction is ignored."""

    have = set(edges)
    if foundation:
        have = set(EDGES)
    if not {"C"} <= have:
        return "NO_C"
    others = have & {"A", "B", "D"}
    if have >= {"A", "B", "C", "D"}:
        return "CORE4"
    if {"A", "B"} <= have:
        return "C_PLUS_AB"
    if "D" in have:
        return "C_PLUS_D"
    return "C_ONLY_OR_PARTIAL"


def c_is_mandatory_pre_sd5() -> str:
    return (
        "Unique current 5D before SD5 is the only 5D that can enter a Diamond "
        "foundation.  Engine face_up is bottom-to-top descending, so that "
        "foundation's K-to-A run always contains the adjacent pair 6D-5D."
    )


def diamond_run_containing(state: SpiderState, rank: int) -> Optional[dict]:
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        for i, card in enumerate(up):
            if card.suit != "d" or card.rank != rank:
                continue
            lo = i
            while lo > 0 and up[lo - 1].suit == "d" and up[lo - 1].rank == up[lo].rank + 1:
                lo -= 1
            hi = i + 1
            while hi < len(up) and up[hi].suit == "d" and up[hi - 1].rank == up[hi].rank + 1:
                hi += 1
            headed_from_here = up[i:hi]
            below = up[lo:i]
            suffix = up[i + 1 : hi]
            k = len(up) - i
            movable = SpiderState.is_movable_run(up[-k:]) if hi == len(up) else False
            dests = 0
            if movable:
                for action in engine_tableau_actions(state)[0]:
                    if action[0] == col_i and action[2] == k:
                        dests += 1
            return {
                "column_0": col_i,
                "column_1": col_i + 1,
                "up_index": i,
                "top": i == len(up) - 1,
                "exposed": hi == len(up),
                "buried": i < len(up) - 1,
                "ranks": [pretty_card(c) for c in up[lo:hi]],
                "length": hi - lo,
                "below": [pretty_card(c) for c in below],
                "same_suit_suffix": [pretty_card(c) for c in suffix],
                "headed_packet": [pretty_card(c) for c in headed_from_here],
                "headed_k": k if hi == len(up) else None,
                "can_move_now": dests > 0,
                "legal_dests": dests,
                "face_up": True,
            }
        for d_i, card in enumerate(column.face_down):
            if card.suit == "d" and card.rank == rank:
                return {
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "top": False,
                    "exposed": False,
                    "buried": True,
                    "face_up": False,
                    "down_index": d_i,
                    "face_up_above": [pretty_card(c) for c in column.face_up],
                    "face_down_blockers_above": len(column.face_down) - 1 - d_i,
                    "can_move_now": False,
                    "same_suit_suffix": [],
                    "headed_packet": [pretty_card(card)],
                }
    return None


def unique_five_d(state: SpiderState) -> dict:
    occ = occurrence_counts(state, "d", 5)
    run = diamond_run_containing(state, 5)
    d_sat = "D" in satisfied_core_edges(state)
    loc = run or {}
    return {
        "current_count": occ["current_count"],
        "tableau_count": occ["tableau_count"],
        "future_stock_count": occ["future_stock_count"],
        "column_1": loc.get("column_1"),
        "top": bool(loc.get("top")),
        "exposed": bool(loc.get("exposed")),
        "buried": bool(loc.get("buried")),
        "face_up": loc.get("face_up"),
        "component": loc.get("ranks") or loc.get("headed_packet"),
        "d_satisfied": d_sat,
        "can_move_now": bool(loc.get("can_move_now")),
        "same_suit_suffix": loc.get("same_suit_suffix") or [],
        "headed_packet": loc.get("headed_packet") or [],
        "headed_k": loc.get("headed_k"),
    }


def six_d_candidates(state: SpiderState) -> List[dict]:
    occ = occurrence_counts(state, "d", 6)
    five = diamond_run_containing(state, 5)
    out: List[dict] = []
    for rec in occ["tableau"]:
        col_i = rec["column_0"]
        column = state.columns[col_i]
        run = diamond_run_containing(state, 6)
        # diamond_run_containing returns the first 6D; recompute this occurrence.
        component = None
        if rec.get("face_up"):
            up = column.face_up
            idx = rec.get("up_index")
            if idx is None:
                idx = next(i for i, c in enumerate(up) if c.suit == "d" and c.rank == 6)
            lo = idx
            while lo > 0 and up[lo - 1].suit == "d" and up[lo - 1].rank == up[lo].rank + 1:
                lo -= 1
            hi = idx + 1
            while hi < len(up) and up[hi].suit == "d" and up[hi - 1].rank == up[hi].rank + 1:
                hi += 1
            component = [pretty_card(c) for c in up[lo:hi]]
            exposed_dest = idx == len(up) - 1
        else:
            component = None
            exposed_dest = False
        can_receive = False
        receive_k = None
        if exposed_dest and five and five.get("headed_k") and five.get("column_0") != col_i:
            k = int(five["headed_k"])
            if state.can_move(five["column_0"], col_i, k):
                can_receive = True
                receive_k = k
        has_7d6d = bool(component and len(component) >= 2 and component[0].startswith("7D") and "6D" in component)
        out.append(
            {
                "column_1": rec["column_1"],
                "face_up": bool(rec.get("face_up")),
                "top": bool(rec.get("top")),
                "cards_above": rec.get("cards_above"),
                "face_up_above": rec.get("face_up_above") or [],
                "component": component,
                "exposed_destination": exposed_dest,
                "can_receive_5d_packet_now": can_receive,
                "receive_k": receive_k,
                "has_7d_6d": has_7d6d,
            }
        )
    return out


def immediate_c_joins(state: SpiderState) -> List[dict]:
    joins = []
    for rec in six_d_candidates(state):
        if rec.get("can_receive_5d_packet_now"):
            joins.append(rec)
    return joins


def c_dependency_audit(state: SpiderState) -> dict:
    five = unique_five_d(state)
    sixes = six_d_candidates(state)
    joins = immediate_c_joins(state)
    blockers = []
    if five.get("current_count") != 1:
        blockers.append("unique_5D_count")
    if not any(s.get("face_up") for s in sixes):
        blockers.append("no_face_up_6D")
    if not any(s.get("exposed_destination") for s in sixes):
        blockers.append("6D_not_exposed_destination")
    if five.get("buried") and not five.get("can_move_now"):
        blockers.append("5D_packet_not_movable")
    if not joins:
        if five.get("can_move_now") and not any(s.get("exposed_destination") for s in sixes):
            blockers.append("no_legal_6D_landing")
        elif any(s.get("exposed_destination") for s in sixes) and not five.get("can_move_now"):
            blockers.append("5D_cannot_move_onto_exposed_6D")
        else:
            blockers.append("no_immediate_C_join")
    return {
        "five_d": five,
        "six_d": sixes,
        "immediate_c_joins": joins,
        "principal_blockers": blockers,
        "has_7d_6d": any(s.get("has_7d_6d") for s in sixes),
        "d_satisfied": five.get("d_satisfied"),
        "edges": sorted(satisfied_core_edges(state)),
    }


def lower_tail_present(state: SpiderState) -> bool:
    """Engine orientation: face_up bottom-to-top 6D-5D-4D-3D-2D-AD."""

    want = list(LOWER_TAIL_RANKS)
    for column in state.columns:
        up = column.face_up
        for i in range(0, len(up) - 5):
            run = up[i : i + 6]
            if all(c.suit == "d" for c in run) and [c.rank for c in run] == want:
                if all(run[j].rank == run[j + 1].rank + 1 for j in range(5)):
                    return True
    return False


def bridge_e_present(state: SpiderState) -> bool:
    return EDGE_E in diamond_adjacent_pairs(state)


def heart_telemetry(state: SpiderState) -> dict:
    prog = gate1_progress(state)
    ah = occurrence_counts(state, "h", 1)
    qh = occurrence_counts(state, "h", 12)
    jh = occurrence_counts(state, "h", 11)
    h9 = occurrence_counts(state, "h", 9)
    qh_jh = False
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - 1):
            if up[i].suit == "h" and up[i].rank == 12 and up[i + 1].suit == "h" and up[i + 1].rank == 11:
                qh_jh = True
    ah_top = any(o.get("top") for o in ah["tableau"])
    return {
        "ah_current": ah["current_count"],
        "ah_top": ah_top,
        "ah_tableau": [
            {"column_1": o.get("column_1"), "top": o.get("top"), "face_up": o.get("face_up")}
            for o in ah["tableau"]
        ],
        "qh_jh": qh_jh,
        "jh_current": jh["current_count"],
        "h9_current": h9["current_count"],
        "h9_face_up": any(o.get("face_up") for o in h9["tableau"]),
        "original_jh_9h_face_up": bool(prog.get("face_up")),
        "original_top_fd": prog.get("top_fd"),
        "heart_release_plausible": (
            (qh_jh or any(o.get("top") for o in jh["tableau"]))
            and h9["current_count"] >= 1
            and not any(o.get("zone") == "CURRENT_FOUNDATIONS" for o in ah["foundations"])
        ),
    }


def source_invariants(state: SpiderState) -> dict:
    d2 = occurrence_counts(state, "d", 2)
    d5 = occurrence_counts(state, "d", 5)
    spade_foundations = sum(1 for run in state.foundations if run and run[0].suit == "s")
    ok = (
        len(state.foundations) == 1
        and spade_foundations == 1
        and stock_rows(state) == 1
        and d2["current_count"] == 1
        and d5["current_count"] == 1
        and d2["future_stock_count"] == 1
        and d5["future_stock_count"] == 1
    )
    return {
        "ok": ok,
        "foundations": len(state.foundations),
        "spade_foundations": spade_foundations,
        "stock_rows": stock_rows(state),
        "unique_2d": d2["current_count"],
        "unique_5d": d5["current_count"],
        "sd5_2d_copies": d2["future_stock_count"],
        "sd5_5d_copies": d5["future_stock_count"],
        "sd5_excluded": stock_rows(state) == 1,
    }


def audit_v040_two_edge_persistence() -> dict:
    path = V040_TWO_EDGE
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    payload = json.loads(path.read_text(encoding="utf-8")) if exists and size else {}
    states = payload.get("states") or []
    reported_n = payload.get("n")
    unique_digests = len({s.get("ordered_digest") for s in states})
    script = V040_SCRIPT.read_text(encoding="utf-8") if V040_SCRIPT.exists() else ""
    no_pack_dedup = "two.append(rec)" in script and "pack_state" not in script.split("two = []")[-1].split("two_path")[0]
    github_contents_empty = size > GITHUB_CONTENTS_LIMIT
    c_payload = json.loads(V040_EDGE["C"].read_text(encoding="utf-8")) if V040_EDGE["C"].exists() else {}
    return {
        "path": path.relative_to(ROOT).as_posix() if exists else None,
        "exists": exists,
        "local_bytes": size,
        "reported_n": reported_n,
        "states_len": len(states),
        "unique_digests_in_file": unique_digests,
        "github_contents_api_empty": github_contents_empty,
        "github_contents_limit": GITHUB_CONTENTS_LIMIT,
        "appears_empty_via_contents_api": github_contents_empty,
        "c_witnesses": c_payload.get("n", 0),
        "v040_combined_list_lacks_pack_state_dedup": no_pack_dedup,
        "do_not_trust_208_as_unique_count": True,
        "explanation": (
            "v0.40 reports n=208 for diamond_core_two_edge_v0_40.json.  The GitHub "
            "Contents API returns encoding=none and empty content for blobs larger "
            f"than {GITHUB_CONTENTS_LIMIT} bytes (local size {size}).  The v0.40 "
            "script appends every per-edge witness with >=2 current edges and does "
            "not exact-deduplicate the combined list on ordered pack_state.  "
            "Reconstruct from populated A/B/D portfolios; do not trust 208."
        ),
    }


def _source_sort_key(rec: dict) -> tuple:
    """Full accumulated g then digest.  A-ancestry is not a sort key."""

    return (int(rec["full_cost"]), rec["ordered_digest"])


def reconstruct_multi_edge_sources(
    opening: Optional[SpiderState] = None,
) -> dict:
    opening = opening or opening_state()
    persistence = audit_v040_two_edge_persistence()
    raw_records: List[dict] = []
    for name in SOURCE_PORTFOLIOS:
        payload = json.loads(V040_EDGE[name].read_text(encoding="utf-8"))
        for rec in payload.get("states") or []:
            raw_records.append({**rec, "source_portfolio": name})
    before_dedup: List[dict] = []
    replay_failures = 0
    invariant_failures = 0
    seen: Dict[bytes, dict] = {}
    for rec in raw_records:
        full = as_actions(rec.get("full_actions") or [])
        end = opening.clone()
        try:
            cost = replay_actions(end, full)
        except Exception:
            replay_failures += 1
            continue
        ident = pack_state(end)
        edges = sorted(satisfied_core_edges(end))
        inv = source_invariants(end)
        replay_ok = (
            cost == rec.get("full_cost")
            and ident.hex() == rec.get("ordered_digest")
            and inv["ok"]
        )
        if not replay_ok:
            replay_failures += 1
            if not inv["ok"]:
                invariant_failures += 1
            continue
        if len(edges) < 2:
            continue
        category = category_from_edges(edges)
        item = {
            "ordered_digest": ident.hex(),
            "full_cost": cost,
            "full_actions": dump_actions(full),
            "full_path_length": len(full),
            "edges_now": edges,
            "category": category,
            "source_portfolios": [rec["source_portfolio"]],
            "replay_ok": True,
            "stock_rows": stock_rows(end),
            "fd": face_down_count(end),
            "empties": list(empty_column_indices(end)),
            "foundations": len(end.foundations),
            "d2_top": bool(
                occurrence_counts(end, "d", 2)["tableau"]
                and occurrence_counts(end, "d", 2)["tableau"][0].get("top")
            ),
            "d5_top": bool(
                occurrence_counts(end, "d", 5)["tableau"]
                and occurrence_counts(end, "d", 5)["tableau"][0].get("top")
            ),
            "heart": heart_telemetry(end),
            "c_dependency": c_dependency_audit(end),
            "invariants": inv,
            "origin_v040_g": rec.get("g"),
            "origin_v040_edges": rec.get("edges_now") or rec.get("edges"),
        }
        before_dedup.append(item)
        prev = seen.get(ident)
        if prev is None or cost < prev["full_cost"]:
            if prev is not None:
                item["source_portfolios"] = sorted(set(prev["source_portfolios"]) | set(item["source_portfolios"]))
            seen[ident] = item
        else:
            prev["source_portfolios"] = sorted(set(prev["source_portfolios"]) | set(item["source_portfolios"]))
    kept = sorted(seen.values(), key=_source_sort_key)
    cat_rows = defaultdict(list)
    for rec in kept:
        cat_rows[rec["category"]].append(rec)
    categories = {}
    for name in list(EXPECTED_CATEGORIES) + sorted(c for c in cat_rows if c not in EXPECTED_CATEGORIES):
        rows = cat_rows.get(name) or []
        if not rows and name not in EXPECTED_CATEGORIES:
            continue
        costs = [r["full_cost"] for r in rows]
        lineage = Counter(p for r in rows for p in r["source_portfolios"])
        categories[name] = {
            "n": len(rows),
            "mw_range": [min(costs), max(costs)] if costs else None,
            "cheapest_full_mw": min(costs) if costs else None,
            "cost_counts": {str(k): int(v) for k, v in sorted(Counter(costs).items())},
            "source_portfolio_lineage": dict(lineage),
            "all_replay_ok": all(r["replay_ok"] for r in rows),
            "immediate_c_joins": sum(1 for r in rows if r["c_dependency"]["immediate_c_joins"]),
            "principal_blockers": dict(
                Counter(b for r in rows for b in r["c_dependency"]["principal_blockers"])
            ),
        }
    unexpected = [c for c in categories if c not in EXPECTED_CATEGORIES]
    return {
        "persistence_audit": persistence,
        "raw_candidate_count": len(raw_records),
        "multi_edge_before_dedup": len(before_dedup),
        "exact_unique": len(kept),
        "replay_failures": replay_failures,
        "invariant_failures": invariant_failures,
        "all_replay_ok": replay_failures == 0 and bool(kept),
        "categories": categories,
        "unexpected_categories": unexpected,
        "states": kept,
        "source_order": "full_cost, ordered_digest",
        "a_ancestry_preference": False,
        "discrepancy": {
            "v040_reported_n": persistence.get("reported_n"),
            "reconstructed_unique": len(kept),
            "before_dedup": len(before_dedup),
            "explanation": (
                f"v0.40 reported {persistence.get('reported_n')}; reconstructed "
                f"{len(before_dedup)} multi-edge records from A/B/D, "
                f"{len(kept)} exact unique pack_state identities keeping cheapest full g."
            ),
        },
    }


def allowed_at_c_level(label: str, tier: int, level: int) -> bool:
    if level >= 3:
        return True
    if level <= 0:
        return label in L0_LABELS
    if level == 1:
        return label in L1_LABELS
    if level == 2:
        return label != JOIN_BREAK
    return True


def _five_headed_k(state: SpiderState, col_i: int) -> Optional[int]:
    up = state.columns[col_i].face_up
    for i, card in enumerate(up):
        if card.suit == "d" and card.rank == 5:
            k = len(up) - i
            if SpiderState.is_movable_run(up[-k:]):
                return k
            return None
    return None


def _contains_card(run, suit: str, rank: int) -> bool:
    return any(c.suit == suit and c.rank == rank for c in run)


def annotate_c_action(state: SpiderState, action, hot5: Set[int], hot6: Set[int], hot2: Set[int]) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    dest_empty = dst_col.is_empty()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        h = src_col.face_up[-k]
        join_break = left.suit == h.suit and left.rank == h.rank + 1
    d_sat = "D" in satisfied_core_edges(state)
    five_k = _five_headed_k(state, src)

    if (
        dest_top is not None
        and dest_top.suit == "d"
        and dest_top.rank == 6
        and head.suit == "d"
        and head.rank == 5
    ):
        return C_JOIN
    if uncovers and src_col.face_down[-1].suit == "d" and src_col.face_down[-1].rank == 6:
        return C_EXPOSE_6D
    up = src_col.face_up
    for i, card in enumerate(up):
        if card.suit == "d" and card.rank == 6:
            above = len(up) - 1 - i
            if above > 0 and k == above:
                return C_EXPOSE_6D
            if i >= len(up) - k:
                return C_EXPOSE_6D
    if five_k is not None and k == five_k:
        if d_sat and _contains_card(run, "d", 4):
            return C_RETAIN_D
        return C_MOBILISE_5D
    if _contains_card(run, "d", 5):
        return C_MOBILISE_5D
    if dest_top is not None and dest_top.suit == "d" and head.suit == "d" and dest_top.rank == head.rank + 1:
        return D_JOIN
    if src in hot5 or src in hot6 or dst in hot5 or dst in hot6:
        need = None
        if src in hot5 and five_k:
            need = src_col.face_up[-five_k].rank + 1
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
        exposes_need = uncovers and need is not None and src_col.face_down[-1].rank == need
        places_need = need is not None and head.rank == need
        if creates_empty or exposes_need or places_need or (dest_empty and head.rank == 13):
            return C_SUPPORT
        return C_SUPPORT
    if _contains_card(run, "d", 2) or src in hot2 or dst in hot2:
        return AB_QUALITY
    if dest_top is not None and dest_top.suit == "d" and dest_top.rank in (3, 2) and head.rank in (2, 1):
        return AB_QUALITY
    if join_break:
        return JOIN_BREAK
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


def _c_priority(label: str, g: int, depth: int, seq: int, node: int) -> tuple:
    return (LABEL_RANK.get(label, 9), g, depth, seq, node)


@dataclass
class CSearchResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    first_origin: Optional[int] = None
    first_category: Optional[str] = None
    sd5_expanded: bool = False
    levels_reached: List[int] = field(default_factory=list)
    witnesses: List[dict] = field(default_factory=list)
    used_heuristic_prune: bool = False
    foundation_surprise: bool = False
    already_at_source: int = 0
    a_ancestry_preference: bool = False


def search_c_edge(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    source_categories: Sequence[str],
    *,
    max_unique: int = MAX_UNIQUE,
    time_limit_s: float = TIME_LIMIT_S,
    rss_abort_mb: float = RSS_ABORT_MB,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = HARVEST_SLACK,
    harvest_limit: int = HARVEST_LIMIT,
) -> CSearchResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = CSearchResult()
    peak = _rss_mb()
    baseline_d = suit_foundation_count(sources[0], "d") if sources else 0
    ceiling = cost_ceiling
    current_incumbent: Optional[int] = None
    witnesses: Dict[bytes, dict] = {}

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []
    label_of: List[str] = []

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    order = sorted(range(len(sources)), key=lambda i: (int(source_g[i]), pack_state(sources[i])))
    for origin in order:
        src = sources[origin]
        ident = pack_state(src)
        g0 = int(source_g[origin])
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                idx = ident_of.index(ident)
                g_of[idx] = g0
                origin_of[idx] = origin
            continue
        best_g[ident] = g0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        label_of.append("SOURCE")
        if "C" in satisfied_core_edges(src, baseline_d=baseline_d):
            result.already_at_source += 1
            witnesses[ident] = {
                "origin": origin,
                "g": g0,
                "depth": 0,
                "actions": [],
                "ordered_digest": ident.hex(),
                "already": True,
                "foundation": suit_foundation_count(src, "d") > baseline_d,
                "edges": sorted(satisfied_core_edges(src, baseline_d=baseline_d)),
                "source_category": source_categories[origin],
                "classification": classify_c_boundary(
                    satisfied_core_edges(src, baseline_d=baseline_d),
                    foundation=suit_foundation_count(src, "d") > baseline_d,
                ),
            }
            if current_incumbent is None or g0 < current_incumbent:
                current_incumbent = g0
                result.incumbent = g0
                result.first_s = 0.0
                result.first_unique = 1
                result.first_g = g0
                result.first_origin = origin
                result.first_category = source_categories[origin]
    result.unique = len(best_g)
    print(
        f"EDGE_C start unique={result.unique} already={result.already_at_source} "
        f"ceiling={ceiling} sources={len(sources)} a_pref={result.a_ancestry_preference}",
        flush=True,
    )

    for level in range(0, 4):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        result.levels_reached.append(level)
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            if g_of[node] > ceiling:
                continue
            st = unpack_state(ident)
            if "C" in satisfied_core_edges(st, baseline_d=baseline_d) and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(20.0, remaining_s / max(1, levels_left))
        print(
            f"EDGE_C L{level} unique={result.unique} heap={len(heap)} "
            f"budget_s={level_deadline - time.perf_counter():.0f} inc={current_incumbent}",
            flush=True,
        )
        while heap:
            now = time.perf_counter()
            if now >= deadline:
                result.stop_reason = "time limit"
                break
            if now >= level_deadline:
                break
            if (result.expanded & 2047) == 0 and note_rss():
                result.stop_reason = "rss abort"
                break
            if (result.expanded & 8191) == 0 and result.expanded:
                print(
                    f"EDGE_C L{level} exp={result.expanded} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _rk, _g, _d, _s, node = heapq.heappop(heap)
            ident = ident_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident):
                continue
            if g > ceiling:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            parent_edges = satisfied_core_edges(state, baseline_d=baseline_d)
            if "C" in parent_edges and depth > 0:
                continue
            if stock_rows(state) < 1:
                result.sd5_expanded = True
            hot5 = {o["column_0"] for o in occurrence_counts(state, "d", 5)["tableau"]}
            hot6 = {o["column_0"] for o in occurrence_counts(state, "d", 6)["tableau"]}
            hot2 = {o["column_0"] for o in occurrence_counts(state, "d", 2)["tableau"]}
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.sd5_expanded = True
                    continue
                label = annotate_c_action(state, action, hot5, hot6, hot2)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_c_level(label, tier_i, level):
                    continue
                ranked.append((_c_priority(label, g, depth, 0, 0)[0], action, label, tier_i))
            ranked.sort(key=lambda t: (t[0], t[1]))
            result.expanded += 1
            for _rk, action, label, tier_i in ranked:
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > ceiling:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    result.generated += 1
                    if stock_rows(state) < 1:
                        result.sd5_expanded = True
                    child_ident = pack_state(state)
                    child_depth = depth + 1
                    prev = best_g.get(child_ident)
                    if prev is not None and child_g >= prev:
                        result.duplicate_skips += 1
                        continue
                    if prev is None:
                        result.unique += 1
                    if result.unique >= max_unique:
                        result.stop_reason = "unique limit"
                        break
                    best_g[child_ident] = child_g
                    child_node = len(ident_of)
                    ident_of.append(child_ident)
                    parent.append(node)
                    action_of.append(action)
                    depth_of.append(child_depth)
                    origin_of.append(origin_of[node])
                    g_of.append(child_g)
                    label_of.append(label)
                    child_edges = satisfied_core_edges(state, baseline_d=baseline_d)
                    foundation = suit_foundation_count(state, "d") > baseline_d
                    hit = "C" in child_edges and "C" not in parent_edges or foundation
                    if hit:
                        rec = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "depth": child_depth,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ident.hex(),
                            "already": False,
                            "foundation": foundation,
                            "edges": sorted(child_edges),
                            "preserved": sorted(parent_edges & child_edges),
                            "broken": sorted(parent_edges - child_edges),
                            "created": sorted(child_edges - parent_edges),
                            "level": level,
                            "label": label,
                            "fd": face_down_count(state),
                            "empties": list(empty_column_indices(state)),
                            "stock_rows": stock_rows(state),
                            "source_category": source_categories[origin_of[node]],
                            "classification": classify_c_boundary(child_edges, foundation=foundation),
                            "lower_tail": lower_tail_present(state),
                            "bridge_e": bridge_e_present(state),
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if foundation:
                            result.foundation_surprise = True
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_unique = result.unique
                            result.first_g = child_g
                            result.first_origin = origin_of[node]
                            result.first_category = source_categories[origin_of[node]]
                            print(
                                f"FIRST_EDGE_C g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s cat={result.first_category} "
                                f"class={rec['classification']} found={foundation}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
                        continue
                    heapq.heappush(
                        heap,
                        (LABEL_RANK.get(label, 9), child_g, child_depth, seq, child_node),
                    )
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if current_incumbent is not None and len(witnesses) >= 16 and (deadline - time.perf_counter()) < 15:
            result.stop_reason = result.stop_reason or "harvested"
            break

    if not result.stop_reason:
        result.stop_reason = "complete"
    c0 = current_incumbent
    kept = []
    if c0 is not None:
        eligible = [rec for rec in witnesses.values() if rec["g"] <= c0 + harvest_slack]
        kept = harvest_diverse(eligible, harvest_limit)
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result


def harvest_diverse(records: Sequence[dict], limit: int) -> List[dict]:
    ordered = sorted(records, key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
    if len(ordered) <= limit:
        return list(ordered)
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for rec in ordered:
        edges = tuple(rec.get("edges") or [])
        five_suffix = tuple((rec.get("c_dependency") or {}).get("five_d", {}).get("same_suit_suffix") or [])
        key = (
            rec.get("source_category"),
            edges,
            rec.get("classification"),
            bool(rec.get("classification") == "CORE4"),
            bool(rec.get("d2_top")),
            five_suffix[:4],
            bool((rec.get("heart") or {}).get("qh_jh")),
        )
        buckets[key].append(rec)
    out: List[dict] = []
    seen = set()
    while len(out) < limit:
        progressed = False
        for key in sorted(buckets):
            bucket = buckets[key]
            while bucket:
                rec = bucket.pop(0)
                digest = rec.get("ordered_digest")
                if digest in seen:
                    continue
                seen.add(digest)
                out.append(rec)
                progressed = True
                break
            if len(out) >= limit:
                break
        if not progressed:
            break
    return out


def preview_bridge_e(
    state: SpiderState,
    g0: int,
    *,
    max_depth: int = PREVIEW_DEPTH,
    deadline: float,
    rss_abort_mb: float = RSS_ABORT_MB,
    baseline_d: int = 0,
) -> dict:
    ident0 = pack_state(state)
    best = {ident0: g0}
    heap = [(g0, 0, 0, ident0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found_tail = None
    found_e = None
    foundation = None
    exhausted = True
    while heap:
        if time.perf_counter() >= deadline:
            live = True
            exhausted = False
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live = True
            exhausted = False
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            exhausted = False
            continue
        seen[ident] = g
        st = unpack_state(ident)
        actions, _ = engine_tableau_actions(st)
        if not actions and depth < max_depth:
            continue
        for action in actions:
            if action == ("deal",):
                continue
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ident = pack_state(st)
                child_g = g + cost
                prev = best.get(child_ident)
                if prev is not None and child_g >= prev:
                    continue
                best[child_ident] = child_g
                if prev is None:
                    unique += 1
                child_depth = depth + 1
                if suit_foundation_count(st, "d") > baseline_d:
                    foundation = {
                        "g": child_g,
                        "depth": child_depth,
                        "ordered_digest": child_ident.hex(),
                    }
                    break
                if lower_tail_present(st) and found_tail is None:
                    found_tail = {
                        "g": child_g,
                        "depth": child_depth,
                        "ordered_digest": child_ident.hex(),
                        "edges": sorted(satisfied_core_edges(st, baseline_d=baseline_d)),
                    }
                if bridge_e_present(st) and found_e is None:
                    found_e = {
                        "g": child_g,
                        "depth": child_depth,
                        "ordered_digest": child_ident.hex(),
                        "lower_tail": lower_tail_present(st),
                    }
                seq += 1
                heapq.heappush(heap, (child_g, child_depth, seq, child_ident))
            finally:
                _restore(st, cap)
        if foundation:
            exhausted = False
            break
    if foundation:
        status = "FOUNDATION_2"
        dead = False
        live_flag = False
    elif found_tail:
        status = "LOWER_TAIL_WITHIN_6"
        dead = False
        live_flag = False
    elif found_e:
        status = "BRIDGE_E_WITHIN_6"
        dead = False
        live_flag = bool(live or heap)
    elif live or heap:
        status = "LIVE_BEYOND_6"
        dead = False
        live_flag = True
    elif exhausted:
        status = "EXACT_DEAD_TO_BRIDGE"
        dead = True
        live_flag = False
    else:
        status = "LIVE_BEYOND_6"
        dead = False
        live_flag = True
    if status == "LIVE_BEYOND_6" or live:
        # Depth-limited cut-off is never exact-dead.
        if status == "EXACT_DEAD_TO_BRIDGE" and live:
            status = "LIVE_BEYOND_6"
            dead = False
    return {
        "status": status,
        "dead": dead,
        "live": live_flag,
        "unique": unique,
        "lower_tail": found_tail,
        "bridge_e": found_e,
        "foundation": foundation,
        "max_depth": max_depth,
    }


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 10) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock)
