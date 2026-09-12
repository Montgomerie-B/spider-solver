"""Research-only v0.47 Spade 4S final access transaction.

From the retained v0.46 B4=2 frontier (cover 10D, 5S bottom-to-top),
solve the two-gate landing transaction:

    Gate 1: move 5S (needs rank 6 or empty)
    Gate 2: move 10D (needs Jack or empty)

until UNIQUE_4S_EXPOSED.  Canonical identity is post-stock symmetry.
B4, gate number, landing category, intent, and history are not identity.
Tableau only.  Full accumulated MW is g.  Do not search TAIL4.
Do not search Foundation 2.  Do not search Foundation 3.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import (
    GOOD_PLAY,
    JOIN_BREAK,
    OTHER,
    PARK,
    suit_foundation_count,
)
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_spade_4s_ratchet import (
    b4_count,
    four_s_can_move,
    locate_unique_spade,
    unique_4s_exposed,
)
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
V046_B42 = ROOT / "docs" / "research" / "spade_4s_blockers_2_v0_46.json"
DEAL_PATH = ROOT / "deals" / "4925153.txt"

COVER_ABOVE = ("10D", "5S")
TOP_BLOCKER = "5S"
NEXT_BLOCKER = "10D"
EXPECTED_SOURCES = 128
SOURCE_COST_LO = 89
SOURCE_COST_HI = 90
HARD_LB = 91
COST_CEILING = 100
GATE1_UNIQUE = 180_000
GATE2_UNIQUE = 180_000
GLOBAL_TIME_S = 450.0
RSS_ABORT_MB = 2.5 * 1024.0
HARVEST_SLACK = 3
HARVEST_B41 = 192
HARVEST_EXPOSED = 128

GATE_MOVE = "GATE_MOVE"
LANDING_6 = "LANDING_6"
LANDING_J = "LANDING_J"
LANDING_EMPTY = "LANDING_EMPTY"
PRESERVE_NEXT = "PRESERVE_NEXT"
TARGET_JOIN = "TARGET_JOIN"
AB_QUALITY = "AB_QUALITY"
REBURY = "REBURY"

L0_GATE1 = {GATE_MOVE, LANDING_6, LANDING_EMPTY, TARGET_JOIN, GOOD_PLAY}
L0_GATE2 = {GATE_MOVE, LANDING_J, LANDING_EMPTY, TARGET_JOIN, GOOD_PLAY}
L1_EXTRA = {AB_QUALITY, PARK, PRESERVE_NEXT, LANDING_J, LANDING_6}

LABEL_RANK = {
    GATE_MOVE: 0,
    LANDING_6: 1,
    LANDING_J: 1,
    LANDING_EMPTY: 2,
    PRESERVE_NEXT: 3,
    TARGET_JOIN: 4,
    GOOD_PLAY: 5,
    AB_QUALITY: 6,
    PARK: 7,
    OTHER: 8,
    REBURY: 9,
    JOIN_BREAK: 10,
    "DEAL": 11,
}

GATE2_CATS = (
    "J_READY",
    "EMPTY_READY",
    "GATE2_READY",
    "J_ONE_SUPPORT",
    "EMPTY_ONE_SUPPORT",
    "GATE2_NOT_READY",
)


def exposure_lower_bound(source_g: int) -> int:
    """Each blocker-removal costs 1 while 4S remains in the source column."""

    return int(source_g) + 2


def retained_frontier_hard_lb() -> int:
    return HARD_LB


def blocker_order_ok(state: SpiderState) -> dict:
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return {"ok": False, "reason": "unique 4S missing"}
    above = tuple(loc.get("above") or [])
    col = loc["column_0"]
    up = state.columns[col].face_up
    top = pretty_card(up[-1]) if up else None
    expected_top = COVER_ABOVE[-1]
    ok = above == COVER_ABOVE and top == expected_top and loc.get("face_up")
    return {
        "ok": bool(ok),
        "above": list(above),
        "top": top,
        "expected_above": list(COVER_ABOVE),
        "expected_top": expected_top,
        "column_0": col,
        "b4": int(loc["cards_above"]),
    }


def ten_d_five_s_movable_together(state: SpiderState) -> bool:
    loc = locate_unique_spade(state, 4)
    if loc is None or tuple(loc.get("above") or []) != COVER_ABOVE:
        return False
    col = loc["column_0"]
    up = state.columns[col].face_up
    if len(up) < 2:
        return False
    run = up[-2:]
    if [pretty_card(c) for c in run] != ["10D", "5S"]:
        return False
    if not SpiderState.is_movable_run(run):
        return False
    for action in engine_tableau_actions(state)[0]:
        if action[0] == col and action[2] == 2:
            return True
    return False


def exposed_rank_columns(state: SpiderState, rank: int) -> List[int]:
    return [i for i, col in enumerate(state.columns) if col.top() is not None and col.top().rank == rank]


def packet_dests(state: SpiderState, col: int, k: int) -> List[int]:
    out: List[int] = []
    if k <= 0 or k > len(state.columns[col].face_up):
        return out
    if not SpiderState.is_movable_run(state.columns[col].face_up[-k:]):
        return out
    for action in engine_tableau_actions(state)[0]:
        if action[0] == col and action[2] == k:
            out.append(action[1])
    return out


def dest_kind(state: SpiderState, dst: int) -> str:
    top = state.columns[dst].top()
    if top is None:
        return "empty"
    if top.rank == 6:
        return "rank_6"
    if top.rank == 11:
        return "jack"
    return f"rank_{top.rank}"


def five_s_moves(state: SpiderState) -> List[Action]:
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return []
    col = loc["column_0"]
    up = state.columns[col].face_up
    if not up or pretty_card(up[-1]) != TOP_BLOCKER:
        return []
    return [a for a in engine_tableau_actions(state)[0] if a[0] == col and a[2] == 1]


def ten_d_moves(state: SpiderState) -> List[Action]:
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return []
    col = loc["column_0"]
    up = state.columns[col].face_up
    if not up or pretty_card(up[-1]) != NEXT_BLOCKER:
        return []
    return [a for a in engine_tableau_actions(state)[0] if a[0] == col and a[2] == 1]


def five_s_requires_six_or_empty(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, dst, k = action
    loc = locate_unique_spade(state, 4)
    if loc is None or src != loc["column_0"] or k != 1:
        return False
    kind = dest_kind(state, dst)
    return kind in ("empty", "rank_6")


def ten_d_requires_jack_or_empty(state: SpiderState, action: Action) -> bool:
    if action == ("deal",):
        return False
    src, dst, k = action
    loc = locate_unique_spade(state, 4)
    if loc is None or src != loc["column_0"] or k != 1:
        return False
    kind = dest_kind(state, dst)
    return kind in ("empty", "jack")


def blocker_removal_costs_one(state: SpiderState, action: Action) -> bool:
    """5S/10D leaving the 4S column cannot be zero-cost: 4S remains behind."""

    if action == ("deal",):
        return False
    loc = locate_unique_spade(state, 4)
    if loc is None:
        return False
    src, _dst, k = action
    if src != loc["column_0"]:
        return False
    if unique_4s_exposed(state):
        return False
    return step_cost(state, action) == 1 and k >= 1


def low_spade_snapshot(state: SpiderState) -> dict:
    out = {}
    for rank, name in ((3, "3S"), (2, "2S"), (1, "AS")):
        loc = locate_unique_spade(state, rank)
        out[name] = None if loc is None else {
            "column_1": loc["column_1"],
            "top": bool(loc.get("top")),
            "above": list(loc.get("above") or []),
        }
    return out


def source_category(audit: dict) -> str:
    g1 = bool(audit.get("gate1_ready"))
    g2 = bool(audit.get("gate2_would_be_ready"))
    sixes = bool(audit.get("rank6"))
    empties = bool(audit.get("empties"))
    if g1 and g2:
        return "GATE1_READY_GATE2_READY"
    if g1 and not g2:
        return "GATE1_READY_GATE2_BLOCKED"
    if g1:
        return "GATE1_READY"
    if not sixes and not empties:
        return "BOTH_GATES_BLOCKED"
    if not sixes:
        return "NEED_6"
    if not empties:
        return "NEED_EMPTY"
    return "BOTH_GATES_BLOCKED"


def audit_source_landings(state: SpiderState) -> dict:
    loc = locate_unique_spade(state, 4)
    order = blocker_order_ok(state)
    empties = list(empty_column_indices(state))
    sixes = exposed_rank_columns(state, 6)
    jacks = exposed_rank_columns(state, 11)
    moves5 = five_s_moves(state)
    dest5 = []
    for action in moves5:
        dst = action[1]
        dest5.append({"dst_1": dst + 1, "kind": dest_kind(state, dst)})
    gate1_ready = bool(dest5)
    surviving = []
    for action in moves5:
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            surviving.append(
                {
                    "action": dump_actions([action])[0],
                    "jacks": [i + 1 for i in exposed_rank_columns(state, 11)],
                    "empties": [i + 1 for i in empty_column_indices(state)],
                    "ten_d_moves": len(ten_d_moves(state)),
                }
            )
        finally:
            _restore(state, cap)
    gate2_would = any(s["ten_d_moves"] > 0 for s in surviving)
    create_6 = 0
    create_empty = 0
    create_j = 0
    destroy = 0
    parent_six = set(sixes)
    parent_jack = set(jacks)
    parent_empty = set(empties)
    for action in engine_tableau_actions(state)[0]:
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            six2 = set(exposed_rank_columns(state, 6))
            jack2 = set(exposed_rank_columns(state, 11))
            empty2 = set(empty_column_indices(state))
            if six2 - parent_six:
                create_6 += 1
            if empty2 - parent_empty:
                create_empty += 1
            if jack2 - parent_jack:
                create_j += 1
            if (parent_six and not six2) or (parent_jack and not jack2):
                destroy += 1
        finally:
            _restore(state, cap)
    rec = {
        "column_1": None if loc is None else loc["column_1"],
        "b4": b4_count(state),
        "above": list(order["above"]),
        "top": order["top"],
        "order_ok": order["ok"],
        "together": ten_d_five_s_movable_together(state),
        "gate1_ready": gate1_ready,
        "five_s_dests": dest5,
        "rank6": [i + 1 for i in sixes],
        "jacks": [i + 1 for i in jacks],
        "empties": [i + 1 for i in empties],
        "gate2_would_be_ready": gate2_would,
        "five_s_then_gate2": surviving,
        "create_rank6_moves": create_6,
        "create_empty_moves": create_empty,
        "create_jack_moves": create_j,
        "destroy_useful_landing_moves": destroy,
        "fd": face_down_count(state),
        "stock": stock_rows(state),
        "spade_foundations": suit_foundation_count(state, "s"),
        "four_can_move": four_s_can_move(state),
        "low_spades": low_spade_snapshot(state),
    }
    rec["category"] = source_category(rec)
    return rec


def load_b42_sources(opening: Optional[SpiderState] = None, path: Optional[Path] = None) -> dict:
    opening = opening or opening_state()
    path = path or V046_B42
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    replay_fail = 0
    order_fail = 0
    kept: List[dict] = []
    classes: Dict[bytes, dict] = {}
    for rec in rows:
        end = opening.clone()
        full = as_actions(rec["full_actions"])
        cost = replay_actions(end, full)
        expected = int(rec.get("full_cost") if rec.get("full_cost") is not None else rec["g"])
        loc = locate_unique_spade(end, 4)
        order = blocker_order_ok(end)
        ok = (
            cost == expected
            and stock_rows(end) == 0
            and len(end.foundations) == 1
            and suit_foundation_count(end, "s") == 1
            and loc is not None
            and b4_count(end) == 2
            and order["ok"]
            and SOURCE_COST_LO <= expected <= SOURCE_COST_HI
        )
        if not order["ok"]:
            order_fail += 1
        if not ok:
            replay_fail += 1
            continue
        ident_ord = pack_state(end)
        ident_sym = pack_post_stock_symmetry_state(end)
        audit = audit_source_landings(end)
        item = {
            "g": expected,
            "timing": rec.get("timing"),
            "lineages": rec.get("lineages"),
            "origin": rec.get("origin"),
            "full_actions": dump_actions(full),
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "b4": 2,
            "signature": list(COVER_ABOVE),
            "audit": audit,
            "category": audit["category"],
            "fd": audit["fd"],
            "empties": audit["empties"],
        }
        prev = classes.get(ident_sym)
        if prev is None or item["g"] < prev["g"]:
            classes[ident_sym] = item
        kept.append(item)
    unique = sorted(classes.values(), key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "expected": EXPECTED_SOURCES,
        "replayed": len(kept),
        "symmetry_unique": len(unique),
        "replay_fail": replay_fail,
        "order_fail": order_fail,
        "all_replay_ok": replay_fail == 0 and order_fail == 0 and len(rows) == EXPECTED_SOURCES,
        "blocker_order_ok": order_fail == 0 and len(rows) == EXPECTED_SOURCES,
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in unique).items())},
        "timing": dict(Counter(r.get("timing") for r in unique)),
        "categories": dict(Counter(r["category"] for r in unique)),
        "gate1_ready": sum(1 for r in unique if r["audit"]["gate1_ready"]),
        "rank6_any": sum(1 for r in unique if r["audit"]["rank6"]),
        "empty_any": sum(1 for r in unique if r["audit"]["empties"]),
        "jack_any": sum(1 for r in unique if r["audit"]["jacks"]),
        "together_any": sum(1 for r in unique if r["audit"]["together"]),
        "states": unique,
    }


def gate2_capability(state: SpiderState) -> dict:
    loc = locate_unique_spade(state, 4)
    flags = {
        "j_ready": False,
        "empty_ready": False,
        "j_one_support": False,
        "empty_one_support": False,
        "rebury_10d": False,
    }
    if loc is None or int(loc["cards_above"]) != 1:
        return {"primary": "GATE2_NOT_READY", **flags, "jacks": [], "empties": []}
    col = loc["column_0"]
    if pretty_card(state.columns[col].face_up[-1]) != NEXT_BLOCKER:
        return {"primary": "GATE2_NOT_READY", **flags, "jacks": [], "empties": []}
    jacks = exposed_rank_columns(state, 11)
    empties = list(empty_column_indices(state))
    for action in ten_d_moves(state):
        kind = dest_kind(state, action[1])
        if kind == "jack":
            flags["j_ready"] = True
        if kind == "empty":
            flags["empty_ready"] = True
    if flags["j_ready"] or flags["empty_ready"]:
        primary = "GATE2_READY"
        if flags["j_ready"] and not flags["empty_ready"]:
            primary = "J_READY"
        if flags["empty_ready"] and not flags["j_ready"]:
            primary = "EMPTY_READY"
        return {
            "primary": primary,
            **flags,
            "jacks": [i + 1 for i in jacks],
            "empties": [i + 1 for i in empties],
        }
    for action in engine_tableau_actions(state)[0]:
        src, dst, _k = action
        if dst == col:
            flags["rebury_10d"] = True
            continue
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            loc2 = locate_unique_spade(state, 4)
            if loc2 is None or int(loc2["cards_above"]) != 1:
                continue
            if pretty_card(state.columns[loc2["column_0"]].face_up[-1]) != NEXT_BLOCKER:
                continue
            for nxt in ten_d_moves(state):
                kind = dest_kind(state, nxt[1])
                if kind == "jack":
                    flags["j_one_support"] = True
                if kind == "empty":
                    flags["empty_one_support"] = True
        finally:
            _restore(state, cap)
        if flags["j_one_support"] and flags["empty_one_support"]:
            break
    if flags["j_one_support"]:
        primary = "J_ONE_SUPPORT"
    elif flags["empty_one_support"]:
        primary = "EMPTY_ONE_SUPPORT"
    else:
        primary = "GATE2_NOT_READY"
    return {
        "primary": primary,
        **flags,
        "jacks": [i + 1 for i in jacks],
        "empties": [i + 1 for i in empties],
    }


def allowed_at_access_level(label: str, tier: int, level: int, phase: str) -> bool:
    if level >= 3:
        return True
    l0 = L0_GATE1 if phase == "gate1" else L0_GATE2
    if level <= 0:
        return label in l0
    if level == 1:
        return label in (l0 | L1_EXTRA) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def _new_src_top(state: SpiderState, src: int, k: int):
    col = state.columns[src]
    if k < len(col.face_up):
        return col.face_up[-k - 1]
    if col.face_down:
        return col.face_down[-1]
    return None


def annotate_access_action(state: SpiderState, action, loc4: dict, phase: str) -> str:
    if action == ("deal",):
        return "DEAL"
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    dest_empty = dst_col.is_empty()
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        h = src_col.face_up[-k]
        join_break = left.suit == h.suit and left.rank == h.rank + 1
    col4 = loc4["column_0"]
    top4 = src_col.face_up[-1] if src == col4 and src_col.face_up else (
        state.columns[col4].face_up[-1] if state.columns[col4].face_up else None
    )
    b4 = int(loc4["cards_above"])
    if src == col4 and k == 1 and top4 is not None:
        kind = dest_kind(state, dst)
        if phase == "gate1" and pretty_card(top4) == TOP_BLOCKER and kind in ("empty", "rank_6"):
            return GATE_MOVE
        if phase == "gate2" and pretty_card(top4) == NEXT_BLOCKER and kind in ("empty", "jack"):
            return GATE_MOVE
    if dst == col4:
        rebury = True
    else:
        rebury = False
    new_top = _new_src_top(state, src, k)
    creates_empty = k == len(src_col.face_up) and not src_col.face_down
    exposes_6 = new_top is not None and new_top.rank == 6
    exposes_j = new_top is not None and new_top.rank == 11
    parks_6 = dest_empty and head.rank == 6
    parks_j = dest_empty and head.rank == 11
    if phase == "gate1" and (exposes_6 or parks_6):
        return LANDING_6
    if phase == "gate2" and (exposes_j or parks_j):
        return LANDING_J
    if creates_empty:
        return LANDING_EMPTY
    if phase == "gate1" and (exposes_j or parks_j):
        return PRESERVE_NEXT
    if phase == "gate2" and (exposes_6 or parks_6):
        return PRESERVE_NEXT
    if dest_top is not None and dest_top.suit == head.suit and dest_top.rank == head.rank + 1:
        return TARGET_JOIN
    if join_break:
        return JOIN_BREAK
    if rebury:
        return REBURY
    if int(classify_tier(state, action)) == int(Tier.A):
        return GOOD_PLAY
    if int(classify_tier(state, action)) <= int(Tier.B):
        return AB_QUALITY
    if dest_empty:
        return PARK
    return OTHER


def must_cross_b4_one() -> str:
    return (
        "From cover 10D,5S the blockers are not a legal run, so every path "
        "to UNIQUE_4S_EXPOSED must cross B4=1 after 5S leaves, then B4=0 after 10D leaves."
    )


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock, foundations or [])


@dataclass
class AccessResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    deal_expanded: bool = False
    foundation_surprise: bool = False
    witnesses: List[dict] = field(default_factory=list)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    first_b4: Optional[int] = None
    skip_contract_hits: int = 0


def fast_path_two_move(sources: Sequence[dict], opening: SpiderState) -> dict:
    """Exhaust every legal 2->1 5S move and every immediate 1->0 10D continuation."""

    del opening  # replay identity lives on ordered_digest
    n_21 = 0
    n_10 = 0
    skip = 0
    clean: List[dict] = []
    for origin, rec in enumerate(sources):
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        g0 = int(rec["g"])
        for a1 in five_s_moves(st):
            if not five_s_requires_six_or_empty(st, a1):
                continue
            n_21 += 1
            c1 = step_cost(st, a1)
            land5 = dest_kind(st, a1[1])
            cap1 = _capture(st, a1)
            try:
                apply_action(st, a1)
                b = b4_count(st)
                if b == 0:
                    skip += 1
                    continue
                if b != 1:
                    continue
                if pretty_card(st.columns[locate_unique_spade(st, 4)["column_0"]].face_up[-1]) != NEXT_BLOCKER:
                    continue
                for a2 in ten_d_moves(st):
                    if not ten_d_requires_jack_or_empty(st, a2):
                        continue
                    c2 = step_cost(st, a2)
                    land10 = dest_kind(st, a2[1])
                    cap2 = _capture(st, a2)
                    try:
                        apply_action(st, a2)
                        if unique_4s_exposed(st) and b4_count(st) == 0:
                            n_10 += 1
                            child_g = g0 + c1 + c2
                            clean.append(
                                {
                                    "origin": origin,
                                    "g": child_g,
                                    "source_g": g0,
                                    "depth": 2,
                                    "actions": dump_actions([a1, a2]),
                                    "full_actions": dump_actions(as_actions(rec["full_actions"]) + [a1, a2]),
                                    "ordered_digest": pack_state(st).hex(),
                                    "symmetry_digest": pack_post_stock_symmetry_state(st).hex(),
                                    "b4_after": 0,
                                    "exposed": True,
                                    "landing_5s": land5,
                                    "landing_10d": land10,
                                    "empty_used": land5 == "empty" or land10 == "empty",
                                    "timing": rec.get("timing"),
                                    "lineages": rec.get("lineages"),
                                    "lb_matched": child_g == HARD_LB,
                                    "fast_path": True,
                                    "fd": face_down_count(st),
                                    "empties": [i + 1 for i in empty_column_indices(st)],
                                    "low_spades": low_spade_snapshot(st),
                                }
                            )
                    finally:
                        _restore(st, cap2)
            finally:
                _restore(st, cap1)
    mw91 = [w for w in clean if w["g"] == HARD_LB]
    by_sym: Dict[str, dict] = {}
    for w in clean:
        prev = by_sym.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by_sym[w["symmetry_digest"]] = w
    kept = sorted(by_sym.values(), key=lambda w: (w["g"], w["origin"]))
    return {
        "n_sources": len(sources),
        "n_legal_2_to_1": n_21,
        "n_with_immediate_1_to_0": n_10,
        "n_unique_exposures": len(kept),
        "mw91_n": len(mw91),
        "skip_2_to_0": skip,
        "cheapest": None if not kept else min(w["g"] for w in kept),
        "witnesses": kept,
        "mw91": mw91,
    }


def harvest_rows(rows: Sequence[dict], *, limit: int, keyfn) -> List[dict]:
    if not rows:
        return []
    ordered = sorted(rows, key=lambda w: (w["g"], w.get("depth", 0), w.get("origin", 0), w.get("ordered_digest", "")))
    g0 = ordered[0]["g"]
    slack = [w for w in ordered if w["g"] <= g0 + HARVEST_SLACK]
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for w in slack:
        buckets[keyfn(w)].append(w)
    picked: List[dict] = []
    seen = set()
    while len(picked) < limit:
        progressed = False
        for key in sorted(buckets, key=str):
            while buckets[key]:
                w = buckets[key].pop(0)
                ident = w["symmetry_digest"]
                if ident in seen:
                    continue
                seen.add(ident)
                picked.append(w)
                progressed = True
                break
            if len(picked) >= limit:
                break
        if not progressed:
            break
    return picked[:limit]


def search_access(
    sources: Sequence[dict],
    opening: SpiderState,
    *,
    phase: str,
    source_b4: int,
    target_b4: int,
    max_unique: int,
    time_limit_s: float,
    rss_abort_mb: float = RSS_ABORT_MB,
    cost_ceiling: int = COST_CEILING,
) -> AccessResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = AccessResult()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_ord_of: List[bytes] = []
    ident_sym_of: List[bytes] = []
    b4_origin_of: List[int] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        cur = node
        while cur >= 0 and parent[cur] >= 0:
            act = action_of[cur]
            if act is not None:
                path.append(act)
            cur = parent[cur]
        path.reverse()
        return path

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    order = sorted(range(len(sources)), key=lambda i: (int(sources[i]["g"]), sources[i]["ordered_digest"]))
    for origin in order:
        rec = sources[origin]
        ident_ord = bytes.fromhex(rec["ordered_digest"])
        ident_sym = bytes.fromhex(rec["symmetry_digest"])
        g0 = int(rec["g"])
        st0 = unpack_state(ident_ord)
        b0 = b4_count(st0)
        if b0 != source_b4:
            continue
        if ident_sym in best_g:
            if g0 < best_g[ident_sym]:
                best_g[ident_sym] = g0
                idx = ident_sym_of.index(ident_sym)
                g_of[idx] = g0
                origin_of[idx] = origin
                ident_ord_of[idx] = ident_ord
                b4_origin_of[idx] = b0
            continue
        best_g[ident_sym] = g0
        ident_sym_of.append(ident_sym)
        ident_ord_of.append(ident_ord)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(g0)
        b4_origin_of.append(b0)
    result.unique = len(best_g)
    print(f"{phase} start unique={result.unique} sources={len(sources)} target_b4={target_b4}", flush=True)

    for level in range(0, 4):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_sym_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            if g_of[node] > cost_ceiling:
                continue
            st = unpack_state(ident_ord_of[node])
            b_now = b4_count(st)
            if phase == "gate1" and b_now < source_b4 and depth_of[node] > 0:
                continue
            if phase == "gate2" and b_now <= target_b4 and depth_of[node] > 0:
                continue
            heapq.heappush(heap, (0, g_of[node], depth_of[node], seq, node))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = 4 - level
        level_deadline = time.perf_counter() + max(12.0, remaining_s / max(1, levels_left))
        print(
            f"{phase} L{level} unique={result.unique} heap={len(heap)} inc={current_incumbent} "
            f"wit={len(witnesses)} budget={level_deadline - time.perf_counter():.0f}s",
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
                    f"{phase} L{level} exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                    f"wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            _rk, _g, _d, _s, node = heapq.heappop(heap)
            ident_sym = ident_sym_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident_sym):
                continue
            if g > cost_ceiling:
                continue
            if seen_expand.get(ident_sym, 10**9) <= g:
                continue
            seen_expand[ident_sym] = g
            state = unpack_state(ident_ord_of[node])
            b_now = b4_count(state)
            if phase == "gate1" and b_now < source_b4 and depth > 0:
                continue
            if phase == "gate2" and unique_4s_exposed(state) and depth > 0:
                continue
            loc4 = locate_unique_spade(state, 4)
            if loc4 is None:
                continue
            if state.stock:
                result.deal_expanded = True
            actions, _ = engine_tableau_actions(state)
            ranked = []
            for action in actions:
                if action == ("deal",):
                    result.deal_expanded = True
                    continue
                label = annotate_access_action(state, action, loc4, phase)
                tier_i = int(classify_tier(state, action))
                if not allowed_at_access_level(label, tier_i, level, phase):
                    continue
                ranked.append((LABEL_RANK.get(label, 8), action, label))
            ranked.sort(key=lambda t: (t[0], t[1]))
            result.expanded += 1
            for _p, action, label in ranked:
                cost = step_cost(state, action)
                child_g = g + cost
                if child_g > cost_ceiling:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    result.generated += 1
                    if state.stock:
                        result.deal_expanded = True
                    child_ord = pack_state(state)
                    child_sym = pack_post_stock_symmetry_state(state)
                    prev = best_g.get(child_sym)
                    if prev is not None and child_g >= prev:
                        result.duplicate_skips += 1
                        continue
                    if prev is None:
                        result.unique += 1
                    if result.unique >= max_unique:
                        result.stop_reason = "unique limit"
                        break
                    best_g[child_sym] = child_g
                    child_node = len(ident_sym_of)
                    ident_sym_of.append(child_sym)
                    ident_ord_of.append(child_ord)
                    parent.append(node)
                    action_of.append(action)
                    depth_of.append(depth + 1)
                    origin_of.append(origin_of[node])
                    g_of.append(child_g)
                    b4_origin_of.append(source_b4)
                    child_b = b4_count(state)
                    foundation = suit_foundation_count(state, "s") > 1
                    exposed = unique_4s_exposed(state)
                    if foundation:
                        result.foundation_surprise = True
                    skip_hit = phase == "gate1" and child_b == 0 and not foundation
                    if skip_hit:
                        result.skip_contract_hits += 1
                    hit = False
                    if phase == "gate1":
                        hit = (child_b == target_b4) or skip_hit or foundation
                    else:
                        hit = exposed or (child_b == 0) or foundation
                    if hit:
                        src = sources[origin_of[node]]
                        land = dest_kind(unpack_state(ident_ord_of[node]), action[1]) if action != ("deal",) else None
                        moved = pretty_card(unpack_state(ident_ord_of[node]).columns[action[0]].face_up[-action[2]]) if action != ("deal",) else None
                        capab = gate2_capability(state) if child_b == 1 else {"primary": None}
                        rec_w = {
                            "origin": origin_of[node],
                            "g": child_g,
                            "source_g": int(src["g"]),
                            "depth": depth + 1,
                            "actions": dump_actions(reconstruct(child_node)),
                            "ordered_digest": child_ord.hex(),
                            "symmetry_digest": child_sym.hex(),
                            "b4_before": source_b4,
                            "b4_after": 0 if (exposed or foundation) else child_b,
                            "label": label,
                            "landing": land,
                            "moved": moved,
                            "timing": src.get("timing"),
                            "lineages": src.get("lineages"),
                            "foundation": foundation,
                            "exposed": exposed,
                            "gate2_capability": capab.get("primary"),
                            "gate2_flags": {k: capab.get(k) for k in ("j_ready", "empty_ready", "j_one_support", "empty_one_support")},
                            "fd": face_down_count(state),
                            "empties": [i + 1 for i in empty_column_indices(state)],
                            "jacks": [i + 1 for i in exposed_rank_columns(state, 11)],
                            "rank6": [i + 1 for i in exposed_rank_columns(state, 6)],
                            "low_spades": low_spade_snapshot(state),
                            "phase": phase,
                        }
                        if child_sym not in witnesses or child_g < witnesses[child_sym]["g"]:
                            witnesses[child_sym] = rec_w
                        if result.first_s is None:
                            result.first_s = time.perf_counter() - started
                            result.first_g = child_g
                            result.first_b4 = rec_w["b4_after"]
                            print(
                                f"FIRST_{phase} {source_b4}->{rec_w['b4_after']} g={child_g} unique={result.unique} "
                                f"t={result.first_s:.2f}s land={land} moved={moved}",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                        continue
                    heapq.heappush(
                        heap,
                        (LABEL_RANK.get(label, 8), child_g, depth + 1, seq, child_node),
                    )
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break
        if witnesses and (deadline - time.perf_counter()) < 8:
            result.stop_reason = result.stop_reason or "harvested"
            break
    if not result.stop_reason:
        result.stop_reason = "complete"

    if phase == "gate1":
        rows = [w for w in witnesses.values() if w["b4_after"] == 1 and not w.get("exposed")]
        kept = harvest_rows(
            rows,
            limit=HARVEST_B41,
            keyfn=lambda w: (
                w.get("gate2_capability"),
                w.get("timing"),
                w.get("source_g"),
                tuple(w.get("empties") or []),
                w.get("fd"),
                tuple(w.get("jacks") or []),
            ),
        )
    else:
        rows = [w for w in witnesses.values() if w.get("exposed") or w["b4_after"] == 0]
        kept = harvest_rows(
            rows,
            limit=HARVEST_EXPOSED,
            keyfn=lambda w: (
                w.get("landing"),
                w.get("timing"),
                w.get("source_g"),
                tuple(w.get("empties") or []),
                w.get("fd"),
            ),
        )
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result
