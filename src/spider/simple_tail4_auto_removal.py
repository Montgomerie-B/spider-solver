"""Research-only v0.50 TAIL4 auto-removal audit.

v0.49's optional_tail4_join() recognised success only while 4-3-2-A remained
in tableau.  Engine SpiderState.move() calls check_seq() after the push, so a
3-2-A onto K-through-4 auto-removes Foundation 2 and makes tail4_present false.

This module classifies both:

    visible 4-3-2-A
    automatic complete-foundation removal

as successful target progress.  Production move/removal semantics are unchanged.
v0.49 reports are not rewritten.
"""

from __future__ import annotations

import heapq
import json
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_club_diamond_tail3_ready import (
    PREVIEW_DEPTH,
    PREVIEW_UNIQUE,
    legal_tail4_joins,
    synthetic_columns,
    tail3_already,
    tail4_present,
    tail4_ready,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import _capture, _restore, apply_action, step_cost
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
CLUB_T3 = ROOT / "docs" / "research" / "post_sd5_club_tail3_v0_49.json"
DIA_T3 = ROOT / "docs" / "research" / "post_sd5_diamond_tail3_v0_49.json"
EXPECTED_CLUB = 128
EXPECTED_DIA = 192
HARVEST_SLACK = 3
HARVEST_F2 = 128

FOUNDATION_AUTO_REMOVED = "FOUNDATION_AUTO_REMOVED"
TAIL4_PERSISTS = "TAIL4_PERSISTS"
CONTRACT_FAILURE = "CONTRACT_FAILURE"


def k_through_4(suit: str) -> List[Card]:
    return [Card(suit, r) for r in range(13, 3, -1)]


def tail3_run(suit: str) -> List[Card]:
    return [Card(suit, 3), Card(suit, 2), Card(suit, 1)]


def synthetic_k4_plus_tail3(suit: str = "c") -> SpiderState:
    """KC..4C in one column, 3C-2C-AC exposed in another. Remaining columns blocked."""

    pads = [[Card("s", 13)] for _ in range(8)]
    return synthetic_columns([k_through_4(suit), tail3_run(suit), *pads])


def synthetic_isolated_4_plus_tail3(suit: str = "c") -> SpiderState:
    pads = [[Card("s", 13)] for _ in range(8)]
    return synthetic_columns([[Card(suit, 4)], tail3_run(suit), *pads])


def foundation_suits(state: SpiderState) -> List[str]:
    return [run[0].suit for run in state.foundations if run]


def foundation_is_ka(run: Sequence[Card], suit: str) -> bool:
    if len(run) != 13:
        return False
    if run[0].rank != 13 or run[-1].rank != 1:
        return False
    return all(c.suit == suit and c.rank == 13 - i for i, c in enumerate(run))


def receiving_4_upper_run(state: SpiderState, dst: int, suit: str) -> dict:
    """Contiguous same-suit sequence at dest ending in exposed 4, read toward King."""

    up = state.columns[dst].face_up
    if not up or up[-1].suit != suit or up[-1].rank != 4:
        return {"length": 0, "ranks": [], "label": "none", "k_through_4": False}
    ranks = [4]
    i = len(up) - 2
    expect = 5
    while i >= 0 and up[i].suit == suit and up[i].rank == expect:
        ranks.append(expect)
        expect += 1
        i -= 1
        if expect > 13:
            break
    ranks.reverse()
    labels = {1: "4 only", 2: "5-4", 3: "6-5-4", 4: "7-6-5-4", 5: "8-7-6-5-4", 6: "9-8-7-6-5-4", 7: "10-9-8-7-6-5-4", 8: "J-10-9-8-7-6-5-4", 9: "Q-J-10-9-8-7-6-5-4", 10: "K-Q-J-10-9-8-7-6-5-4"}
    n = len(ranks)
    return {
        "length": n,
        "ranks": ranks,
        "label": labels.get(n, f"len_{n}"),
        "k_through_4": n == 10 and ranks[0] == 13,
        "cards": [pretty_card(c) for c in up[len(up) - n :]],
        "dst_1": dst + 1,
    }


def optional_tail4_join_v049(state: SpiderState, g0: int, suit: str) -> Optional[dict]:
    """Historical v0.49 helper. Success only if 4-3-2-A remains visible."""

    if not tail4_ready(state, suit):
        return None
    for action in legal_tail4_joins(state, suit):
        cost = step_cost(state, action)
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            if tail4_present(state, suit):
                return {
                    "g": g0 + cost,
                    "join": dump_actions([action])[0],
                    "ordered_digest": pack_state(state).hex(),
                    "symmetry_digest": pack_post_stock_symmetry_state(state).hex(),
                }
        finally:
            _restore(state, cap)
    return None


def classify_tail4_transition(state: SpiderState, g0: int, suit: str, action: Action) -> dict:
    """Classify one legal 3-2-A -> same-suit-4 move."""

    before_n = len(state.foundations)
    before_suits = foundation_suits(state)
    before_target = suit_foundation_count(state, suit)
    upper = receiving_4_upper_run(state, action[1], suit)
    cost = step_cost(state, action)
    cap = _capture(state, action)
    try:
        apply_action(state, action)
        after_n = len(state.foundations)
        after_suits = foundation_suits(state)
        after_target = suit_foundation_count(state, suit)
        persists = tail4_present(state, suit)
        auto = after_n == before_n + 1 and after_target == before_target + 1
        ka_ok = False
        if auto and state.foundations:
            ka_ok = foundation_is_ka(state.foundations[-1], suit)
        if auto and ka_ok:
            cls = FOUNDATION_AUTO_REMOVED
        elif not auto and persists:
            cls = TAIL4_PERSISTS
        else:
            cls = CONTRACT_FAILURE
        return {
            "class": cls,
            "g": g0 + cost,
            "join": dump_actions([action])[0],
            "action": dump_actions([action])[0],
            "ordered_digest": pack_state(state).hex(),
            "symmetry_digest": pack_post_stock_symmetry_state(state).hex(),
            "foundation_count": after_n,
            "foundation_suits": after_suits,
            "foundation_count_before": before_n,
            "foundation_suits_before": before_suits,
            "target_foundations": after_target,
            "ka_ok": ka_ok,
            "tail4_present": persists,
            "upper_run": upper,
            "fd": face_down_count(state),
            "empties": [i + 1 for i in empty_column_indices(state)],
            "stock": stock_rows(state),
        }
    finally:
        _restore(state, cap)


def classify_all_tail4_joins(state: SpiderState, g0: int, suit: str) -> List[dict]:
    return [classify_tail4_transition(state, g0, suit, action) for action in legal_tail4_joins(state, suit)]


def optional_tail4_join_corrected(state: SpiderState, g0: int, suit: str) -> Optional[dict]:
    """Future helper: visible TAIL4 or auto-removed foundation both count."""

    if not tail4_ready(state, suit):
        return None
    hits = classify_all_tail4_joins(state, g0, suit)
    ok = [h for h in hits if h["class"] in (FOUNDATION_AUTO_REMOVED, TAIL4_PERSISTS)]
    if not ok:
        return None
    best = min(ok, key=lambda h: (0 if h["class"] == FOUNDATION_AUTO_REMOVED else 1, h["g"]))
    return best


def reproduce_accounting_bug() -> dict:
    st = synthetic_k4_plus_tail3("c")
    before_fdn = len(st.foundations)
    ready = tail4_ready(st, "c")
    joins = legal_tail4_joins(st, "c")
    old = optional_tail4_join_v049(st, 0, "c")
    classified = classify_all_tail4_joins(st, 0, "c")
    new = optional_tail4_join_corrected(st, 0, "c")
    after = st.clone()
    apply_action(after, joins[0])
    return {
        "ready_before": ready,
        "n_joins": len(joins),
        "foundation_before": before_fdn,
        "foundation_after_engine": len(after.foundations),
        "club_foundations_after": suit_foundation_count(after, "c"),
        "tail4_present_after": tail4_present(after, "c"),
        "ka_removed": bool(after.foundations) and foundation_is_ka(after.foundations[-1], "c"),
        "old_helper": old,
        "new_helper_class": None if new is None else new["class"],
        "classified": [c["class"] for c in classified],
        "bug_reproduced": old is None and any(c["class"] == FOUNDATION_AUTO_REMOVED for c in classified),
    }


def load_v049_tail3(path: Path, opening: SpiderState, suit: str, expected: int) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    ready_n = 0
    for rec in rows:
        end = opening.clone()
        try:
            cost = replay_actions(end, as_actions(rec["full_actions"]))
        except Exception:
            fail += 1
            continue
        ok = (
            cost == int(rec["g"])
            and stock_rows(end) == 0
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
            and tail3_already(end, suit)
        )
        if not ok:
            fail += 1
            continue
        ready = tail4_ready(end, suit)
        if ready:
            ready_n += 1
        kept.append(
            {
                **rec,
                "g": int(rec["g"]),
                "full_actions": dump_actions(as_actions(rec["full_actions"])),
                "ordered_digest": pack_state(end).hex(),
                "symmetry_digest": pack_post_stock_symmetry_state(end).hex(),
                "tail4_ready": ready,
                "full_replay_ok": True,
            }
        )
    return {
        "raw": len(rows),
        "expected": expected,
        "replayed": len(kept),
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == expected,
        "tail4_ready_n": ready_n,
        "states": kept,
    }


def audit_immediate_joins(rows: Sequence[dict], opening: SpiderState, suit: str) -> dict:
    classes = Counter()
    upper = Counter()
    transitions = []
    n_ready = 0
    n_joins = 0
    for rec in rows:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        if not rec.get("tail4_ready") and not tail4_ready(st, suit):
            continue
        n_ready += 1
        hits = classify_all_tail4_joins(st, int(rec["g"]), suit)
        n_joins += len(hits)
        for hit in hits:
            classes[hit["class"]] += 1
            upper[hit["upper_run"]["label"]] += 1
            transitions.append(
                {
                    **hit,
                    "source_g": rec["g"],
                    "full_actions": dump_actions(as_actions(rec["full_actions"]) + as_actions([hit["join"]])),
                    "suit": suit,
                }
            )
    f2 = [t for t in transitions if t["class"] == FOUNDATION_AUTO_REMOVED]
    persist = [t for t in transitions if t["class"] == TAIL4_PERSISTS]
    fail = [t for t in transitions if t["class"] == CONTRACT_FAILURE]
    cheapest_f2 = None if not f2 else min(t["g"] for t in f2)
    return {
        "suit": suit,
        "n_states": len(rows),
        "n_ready": n_ready,
        "n_joins": n_joins,
        "classes": dict(classes),
        "upper_runs": dict(upper),
        "foundation2_n": len(f2),
        "persists_n": len(persist),
        "contract_n": len(fail),
        "cheapest_f2": cheapest_f2,
        "transitions": transitions,
        "foundation2": f2,
    }


def reconstruct_tail4_ready_preview(
    rec: dict,
    opening: SpiderState,
    suit: str,
    *,
    max_depth: int = PREVIEW_DEPTH,
    max_unique: int = PREVIEW_UNIQUE,
) -> dict:
    """Bounded 5-ply preview with parent pointers. Persist the READY child path."""

    st0 = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    g0 = int(rec["g"])
    prefix = as_actions(rec["full_actions"])
    if tail4_ready(st0, suit):
        return {
            "status": "TAIL4_READY_IMMEDIATE",
            "g": g0,
            "depth": 0,
            "actions": [],
            "full_actions": dump_actions(prefix),
            "ordered_digest": rec["ordered_digest"],
            "symmetry_digest": rec["symmetry_digest"],
            "source_g": g0,
        }
    ident0 = pack_post_stock_symmetry_state(st0)
    ord0 = pack_state(st0)
    best = {ident0: g0}
    parent: Dict[bytes, Optional[bytes]] = {ident0: None}
    action_of: Dict[bytes, Optional[Action]] = {ident0: None}
    ord_of = {ident0: ord0}
    heap = [(g0, 0, 0, ident0)]
    seq = 0
    seen: Dict[bytes, int] = {}
    unique = 1
    live = False
    found = None
    while heap:
        if unique >= max_unique:
            live = True
            break
        g, depth, _, ident = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live = True
            continue
        seen[ident] = g
        st = unpack_state(ord_of[ident])
        for action in engine_tableau_actions(st)[0]:
            if action == ("deal",):
                continue
            cost = step_cost(st, action)
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                child_ord = pack_state(st)
                child_sym = pack_post_stock_symmetry_state(st)
                child_g = g + cost
                prev = best.get(child_sym)
                if prev is not None and child_g >= prev:
                    continue
                best[child_sym] = child_g
                parent[child_sym] = ident
                action_of[child_sym] = action
                ord_of[child_sym] = child_ord
                if prev is None:
                    unique += 1
                if tail4_ready(st, suit):
                    found = {"g": child_g, "depth": depth + 1, "sym": child_sym}
                    break
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_sym))
            finally:
                _restore(st, cap)
        if found:
            break
    if found:
        path: List[Action] = []
        cur = found["sym"]
        while parent.get(cur) is not None:
            act = action_of[cur]
            if act is not None:
                path.append(act)
            cur = parent[cur]
        path.reverse()
        status = "TAIL4_READY_IMMEDIATE" if found["depth"] <= 1 else "TAIL4_READY_WITHIN_5"
        return {
            "status": status,
            "g": found["g"],
            "depth": found["depth"],
            "actions": dump_actions(path),
            "full_actions": dump_actions(prefix + path),
            "ordered_digest": ord_of[found["sym"]].hex(),
            "symmetry_digest": found["sym"].hex(),
            "source_g": g0,
        }
    if live or heap:
        return {"status": "LIVE_BEYOND_5", "g": None, "depth": None, "actions": [], "source_g": g0}
    return {"status": "EXACT_DEAD_TO_TAIL4_READY", "g": None, "depth": None, "actions": [], "source_g": g0}


def harvest_foundation2(rows: Sequence[dict]) -> List[dict]:
    if not rows:
        return []
    by = {}
    for w in rows:
        prev = by.get(w["symmetry_digest"])
        if prev is None or w["g"] < prev["g"]:
            by[w["symmetry_digest"]] = w
    ordered = sorted(by.values(), key=lambda w: (w["g"], w.get("source_g", 0), w.get("ordered_digest", "")))
    g0 = ordered[0]["g"]
    slack = [w for w in ordered if w["g"] <= g0 + HARVEST_SLACK]
    return slack[:HARVEST_F2]
