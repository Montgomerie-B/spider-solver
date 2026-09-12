"""Research-only v0.53 SD5 resource-runway replan.

Reconstruct the v0.43 103,513-state preparation envelope, apply SD5 once,
and audit Ace-ending foundation runways.  No generic UCS, no suit winner,
no Foundation-3 search.  Identity is ordered pack_state before Deal and
pack_post_stock_symmetry_state after stock is empty.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import as_actions, dump_actions, opening_state
from spider.simple_final_deal_timing import (
    PREP_COST,
    PREP_DEPTH,
    PREP_TIME_S,
    PREP_UNIQUE,
    deal_is_legal,
    enumerate_preparation,
    verify_sd5_row,
)
from spider.simple_foundation_horizon import pretty_card
from spider.simple_low_tail import (
    CONTRACT_FAILURE,
    FOUNDATION_AUTO_REMOVED,
    classify_low_tail_transition,
    rank_cards,
)
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action, step_cost
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

ROOT = Path(__file__).resolve().parents[2]
V043_SOURCES = ROOT / "docs" / "research" / "final_deal_sources_v0_43.json"
EXPECTED_SOURCES = 720
EXPECTED_PREP = 103_513
EXPECTED_DEAL_NOW = 720
EXPECTED_PREP_THEN = 102_793
SUPPORT_CHILD_CAP = 250_000
PORTFOLIO_LIMIT = 512
GLOBAL_TIME_S = 600.0
RSS_ABORT_MB = 3 * 1024.0
SUITS = ("s", "h", "d", "c")
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}

ACCESS_ORDER = (
    "NEXT_READY",
    "NEXT_ONE_MOVE",
    "NEXT_SHALLOW",
    "NEXT_MEDIUM",
    "NEXT_DEEP",
    "NEXT_FACE_DOWN",
    "NEXT_ABSENT",
)
ACCESS_RANK = {name: i for i, name in enumerate(ACCESS_ORDER)}  # lower is better


def next_required_rank(length: int) -> int:
    return length + 1


def ace_ending_packets(state: SpiderState, suit: Optional[str] = None) -> List[dict]:
    """Every contiguous same-suit Ace-ending packet. Duplicate copies included."""

    wanted = [suit] if suit else list(SUITS)
    out: List[dict] = []
    for col, column in enumerate(state.columns):
        up = column.face_up
        for i, card in enumerate(up):
            if card.rank != 1 or card.suit not in wanted:
                continue
            length = 1
            j = i - 1
            expect = 2
            while j >= 0 and up[j].suit == card.suit and up[j].rank == expect:
                length += 1
                expect += 1
                j -= 1
            start = i - length + 1
            run = up[start : i + 1]
            above = [pretty_card(c) for c in up[i + 1 :]]
            exposed = i == len(up) - 1
            movable = exposed and SpiderState.is_movable_run(run)
            dests_0: List[int] = []
            if movable:
                recv = next_required_rank(length)
                if recv <= 13:
                    for dst in range(10):
                        if dst == col:
                            continue
                        top = state.columns[dst].top()
                        if (
                            top is not None
                            and top.suit == card.suit
                            and top.rank == recv
                            and state.can_move(col, dst, length)
                        ):
                            dests_0.append(dst)
            out.append(
                {
                    "suit": card.suit,
                    "column_0": col,
                    "column_1": col + 1,
                    "length": length,
                    "ranks": [c.rank for c in run],
                    "cards": [pretty_card(c) for c in run],
                    "exposed": exposed,
                    "movable": movable,
                    "cards_above": len(above),
                    "above": above,
                    "dests_0": dests_0,
                    "dests_1": [d + 1 for d in dests_0],
                }
            )
    return out


def max_ace_length(state: SpiderState, suit: str) -> int:
    pk = ace_ending_packets(state, suit)
    return 0 if not pk else max(p["length"] for p in pk)


def direct_join_actions(state: SpiderState, suit: str) -> List[Action]:
    return [(p["column_0"], dst, p["length"]) for p in ace_ending_packets(state, suit) if p["movable"] for dst in p["dests_0"]]


def access_class_from_copies(state: SpiderState, suit: str, length: int, copies: Sequence[dict]) -> dict:
    """Best next-receiver class after a maximal direct runway of `length`."""

    recv = next_required_rank(length)
    if length <= 0:
        return {
            "class": "NEXT_ABSENT",
            "rank": recv,
            "min_depth": None,
            "n_copies": 0,
            "copies": [],
        }
    if recv > 13:
        return {
            "class": "NEXT_ABSENT",
            "rank": recv,
            "min_depth": None,
            "n_copies": 0,
            "copies": [],
        }
    if not copies:
        return {
            "class": "NEXT_ABSENT",
            "rank": recv,
            "min_depth": None,
            "n_copies": 0,
            "copies": [],
        }
    ready = False
    packets = [p for p in ace_ending_packets(state, suit) if p["movable"] and p["length"] == length]
    exposed_cols = {t["column_0"] for t in copies if t["top"] and t["face_up"]}
    for p in packets:
        for dst in exposed_cols:
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != recv:
                continue
            if state.can_move(p["column_0"], dst, length):
                ready = True
                break
        if ready:
            break
    one_move = any(t.get("one_move_exposable") for t in copies)
    fu = [t for t in copies if t.get("face_up")]
    fd_only = copies and not fu
    min_fu = None if not fu else min(int(t["cards_above"]) for t in fu)
    if ready:
        cls = "NEXT_READY"
    elif one_move:
        cls = "NEXT_ONE_MOVE"
    elif min_fu is not None and min_fu <= 2:
        cls = "NEXT_SHALLOW"
    elif min_fu is not None and min_fu <= 4:
        cls = "NEXT_MEDIUM"
    elif fu:
        cls = "NEXT_DEEP"
    elif fd_only:
        cls = "NEXT_FACE_DOWN"
    else:
        cls = "NEXT_ABSENT"
    slim_copies = [
        {
            "column_1": t["column_1"],
            "face_up": t["face_up"],
            "top": t["top"],
            "cards_above": t["cards_above"],
            "above": t.get("above") or t.get("covering_packet") or [],
            "one_move_exposable": bool(t.get("one_move_exposable")),
            "cover_dests_1": t.get("cover_dests_1") or t.get("covering_dests_1") or [],
        }
        for t in copies
    ]
    return {
        "class": cls,
        "rank": recv,
        "min_depth": min_fu if min_fu is not None else (0 if ready else None),
        "n_copies": len(copies),
        "copies": slim_copies,
        "ready": ready,
        "one_move": one_move,
    }


def direct_runway(state: SpiderState, suit: str, *, g0: int = 0) -> dict:
    """Maximal Ace-ending tail reachable by target-suit direct joins only."""

    start = max_ace_length(state, suit)
    best = {
        "suit": suit,
        "start_len": start,
        "direct_len": start,
        "joins": 0,
        "g_add": 0,
        "g": g0,
        "f2": False,
        "auto": False,
        "path": [],
        "class": None,
        "contract_fail": False,
    }
    seen: Dict[bytes, int] = {pack_state(state): 0}

    def dfs(joins: int, g_add: int, path: List[Action]) -> None:
        cur = max_ace_length(state, suit)
        f2 = len(state.foundations) >= 2
        better = False
        if f2 and not best["f2"]:
            better = True
        elif (not best["f2"]) and (
            cur > best["direct_len"] or (cur == best["direct_len"] and joins < best["joins"])
        ):
            better = True
        if better:
            best.update(
                direct_len=cur,
                joins=joins,
                g_add=g_add,
                g=g0 + g_add,
                f2=f2,
                auto=f2,
                path=dump_actions(path),
            )
        if f2:
            return
        for action in direct_join_actions(state, suit):
            cls = classify_low_tail_transition(
                state, g0 + g_add, suit, action, packet_head_rank=action[2]
            )
            if cls["class"] == CONTRACT_FAILURE:
                best["contract_fail"] = True
                continue
            cost = step_cost(state, action)
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                ident = pack_state(state)
                child_g = g_add + cost
                prev = seen.get(ident)
                if prev is not None and child_g >= prev:
                    continue
                seen[ident] = child_g
                if cls["class"] == FOUNDATION_AUTO_REMOVED:
                    best.update(
                        direct_len=13,
                        joins=joins + 1,
                        g_add=child_g,
                        g=g0 + child_g,
                        f2=len(state.foundations) >= 2,
                        auto=True,
                        path=dump_actions(path + [action]),
                    )
                    continue
                dfs(joins + 1, child_g, path + [action])
            finally:
                _restore(state, cap)

    dfs(0, 0, [])
    # apply best path to classify next receiver at the terminal
    path_act = as_actions(best["path"])
    caps = []
    for action in path_act:
        cap = _capture(state, action)
        apply_action(state, action)
        caps.append(cap)
    try:
        best["f2"] = len(state.foundations) >= 2 or bool(best["auto"])
        if best["f2"]:
            best["access"] = {
                "class": "FOUNDATION_REMOVED",
                "rank": None,
                "min_depth": 0,
                "n_copies": 0,
                "copies": [],
            }
        else:
            copies = rank_cards(state, suit, next_required_rank(best["direct_len"])) if best["direct_len"] else []
            best["access"] = access_class_from_copies(state, suit, best["direct_len"], copies)
        best["class"] = best["access"]["class"]
        best["min_depth"] = best["access"].get("min_depth")
        best["end_digest"] = pack_state(state).hex()
        best["end_sym"] = pack_post_stock_symmetry_state(state).hex()
        best["foundation_count"] = len(state.foundations)
        best["foundation_suits"] = [run[0].suit for run in state.foundations if run]
    finally:
        for cap in reversed(caps):
            _restore(state, cap)
    return best


def workspace_audit(state: SpiderState) -> dict:
    n_empty = sum(1 for c in state.columns if c.is_empty())
    fd0 = face_down_count(state)
    empty_in_one = False
    fd_reveal = False
    for action in engine_tableau_actions(state)[0]:
        if action == ("deal",):
            continue
        if empty_in_one and fd_reveal:
            break
        cap = _capture(state, action)
        try:
            apply_action(state, action)
            if sum(1 for c in state.columns if c.is_empty()) > n_empty:
                empty_in_one = True
            if face_down_count(state) < fd0:
                fd_reveal = True
        finally:
            _restore(state, cap)
    return {
        "empty_now": n_empty > 0,
        "empty_n": n_empty,
        "empty_in_one": empty_in_one,
        "fd": fd0,
        "fd_reveal_in_one": fd_reveal,
        "empties_1": [i + 1 for i in empty_column_indices(state)],
    }


def load_v043_sources(opening: Optional[SpiderState] = None) -> dict:
    opening = opening or opening_state()
    raw = json.loads(V043_SOURCES.read_text(encoding="utf-8"))
    rows = list(raw.get("states") or [])
    fail = 0
    kept = []
    for rec in rows:
        end = opening.clone()
        try:
            cost = replay_actions(end, as_actions(rec["full_actions"]))
        except Exception:
            fail += 1
            continue
        ident = pack_state(end)
        ok = (
            cost == int(rec.get("full_cost", rec.get("g", -1)))
            and ident.hex() == rec["ordered_digest"]
            and stock_rows(end) == 1
            and deal_is_legal(end)
            and len(end.foundations) == 1
            and end.foundations[0][0].suit == "s"
        )
        if not ok:
            fail += 1
            continue
        kept.append(
            {
                "g": cost,
                "full_cost": cost,
                "full_actions": dump_actions(as_actions(rec["full_actions"])),
                "ordered_digest": ident.hex(),
                "lineages": list(rec.get("lineages") or []),
                "stock_rows": 1,
            }
        )
    kept.sort(key=lambda r: (r["g"], r["ordered_digest"]))
    return {
        "raw": len(rows),
        "expected": EXPECTED_SOURCES,
        "replay_fail": fail,
        "all_replay_ok": fail == 0 and len(rows) == EXPECTED_SOURCES,
        "n": len(kept),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
        "sd5": verify_sd5_row(unpack_state(bytes.fromhex(kept[0]["ordered_digest"]))) if kept else {},
    }


def reconstruct_prep(sources: Sequence[dict]) -> dict:
    states = [unpack_state(bytes.fromhex(r["ordered_digest"])) for r in sources]
    paths = [as_actions(r["full_actions"]) for r in sources]
    gs = [int(r["g"]) for r in sources]
    lins = [list(r["lineages"]) for r in sources]
    res = enumerate_preparation(
        states,
        paths,
        gs,
        lins,
        max_unique=PREP_UNIQUE,
        time_limit_s=PREP_TIME_S,
        max_depth=PREP_DEPTH,
        max_cost=PREP_COST,
    )
    return {
        "unique": res.unique,
        "expanded": res.expanded,
        "generated": res.generated,
        "duplicate_skips": res.duplicate_skips,
        "elapsed_s": res.elapsed_s,
        "stop_reason": res.stop_reason,
        "n": len(res.candidates),
        "expected": EXPECTED_PREP,
        "matches_v043": len(res.candidates) == EXPECTED_PREP,
        "timing": dict(Counter(c["timing"] for c in res.candidates)),
        "depth": dict(Counter(c["prep_depth"] for c in res.candidates)),
        "sd5_expanded": res.sd5_expanded,
        "peak_rss_mb": res.peak_rss_mb,
        "candidates": res.candidates,
    }


def apply_sd5_frontier(candidates: Sequence[dict]) -> dict:
    """Apply SD5 once via unpack+deal. Exact post-stock symmetry dedup."""

    classes: Dict[bytes, dict] = {}
    illegal = 0
    auto = 0
    for rec in candidates:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        if stock_rows(st) != 1 or not deal_is_legal(st):
            illegal += 1
            continue
        before_f = len(st.foundations)
        dcost = apply_action(st, ("deal",))
        if stock_rows(st) != 0:
            illegal += 1
            continue
        if len(st.foundations) > before_f:
            auto += 1
        ident_ord = pack_state(st)
        ident_sym = pack_post_stock_symmetry_state(st)
        g = int(rec["g"]) + int(dcost)
        child = {
            "g": g,
            "source_g": rec.get("source_g"),
            "prep_depth": rec["prep_depth"],
            "prep_cost": rec["prep_cost"],
            "timing": rec["timing"],
            "lineages": rec["lineages"],
            "ordered_digest": ident_ord.hex(),
            "symmetry_digest": ident_sym.hex(),
            "origin": rec["origin"],
            "deal_cost": dcost,
            "prep_actions": rec.get("prep_actions") or [],
            "full_actions": dump_actions(as_actions(rec["full_actions_pre"]) + [("deal",)]),
            "auto_removed": len(st.foundations) - before_f,
            "foundations": len(st.foundations),
        }
        prev = classes.get(ident_sym)
        if prev is None or g < prev["g"]:
            classes[ident_sym] = child
    kept = sorted(classes.values(), key=lambda r: (r["g"], r["prep_depth"], r["ordered_digest"]))
    return {
        "ordered_before_symmetry": len(candidates),
        "n": len(kept),
        "symmetry_classes": len(kept),
        "reduction": None if not candidates else round(len(candidates) / max(1, len(kept)), 3),
        "illegal": illegal,
        "auto_removed": auto,
        "timing": dict(Counter(r["timing"] for r in kept)),
        "depth": dict(Counter(r["prep_depth"] for r in kept)),
        "cost_counts": {str(k): int(v) for k, v in sorted(Counter(r["g"] for r in kept).items())},
        "states": kept,
    }


def _suit_tuple(s: dict) -> tuple:
    access = s.get("class") or "NEXT_ABSENT"
    depth = s.get("min_depth")
    depth_key = 99 if depth is None else depth
    return (
        1 if s.get("f2") else 0,
        int(s.get("direct_len") or 0),
        int(s.get("support_len") or s.get("direct_len") or 0),
        -ACCESS_RANK.get(access, len(ACCESS_ORDER)),
        -depth_key,
        int(s.get("joins") or 0),
    )


def audit_state(rec: dict) -> dict:
    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    ws = workspace_audit(st)
    by_suit = {}
    contract = False
    for suit in SUITS:
        rw = direct_runway(st, suit, g0=int(rec["g"]))
        contract = contract or bool(rw.get("contract_fail"))
        by_suit[suit] = {
            "suit": suit,
            "start_len": rw["start_len"],
            "direct_len": rw["direct_len"],
            "support_len": rw["direct_len"],
            "joins": rw["joins"],
            "g_add": rw["g_add"],
            "f2": rw["f2"],
            "auto": rw["auto"],
            "path": rw["path"],
            "class": rw["class"],
            "min_depth": rw.get("min_depth"),
            "access": rw.get("access"),
            "foundation_count": rw.get("foundation_count"),
            "foundation_suits": rw.get("foundation_suits"),
        }
    best_suit = max(SUITS, key=lambda s: _suit_tuple(by_suit[s]))
    best = by_suit[best_suit]
    qualify = (
        any(by_suit[s]["direct_len"] >= 2 for s in SUITS)
        or any(by_suit[s]["class"] == "NEXT_ONE_MOVE" for s in SUITS)
        or ws["empty_in_one"]
    )
    return {
        "g": rec["g"],
        "timing": rec["timing"],
        "prep_depth": rec["prep_depth"],
        "prep_cost": rec["prep_cost"],
        "lineages": rec.get("lineages") or [],
        "origin": rec.get("origin"),
        "ordered_digest": rec["ordered_digest"],
        "symmetry_digest": rec["symmetry_digest"],
        "full_actions": rec.get("full_actions"),
        "best_suit": best_suit,
        "direct_len": best["direct_len"],
        "support_len": best["direct_len"],
        "joins": best["joins"],
        "access": best["class"],
        "min_depth": best.get("min_depth"),
        "f2": any(by_suit[s]["f2"] for s in SUITS),
        "f2_suit": next((s for s in SUITS if by_suit[s]["f2"]), None),
        "f2_path": next((by_suit[s]["path"] for s in SUITS if by_suit[s]["f2"]), []),
        "empty_now": ws["empty_now"],
        "empty_in_one": ws["empty_in_one"],
        "fd_reveal_in_one": ws["fd_reveal_in_one"],
        "fd": ws["fd"],
        "qualify_support": qualify,
        "contract_fail": contract,
        "by_suit": {s: {k: by_suit[s][k] for k in ("start_len", "direct_len", "joins", "class", "min_depth", "f2")} for s in SUITS},
        "improved_support": False,
        "support_examined": False,
    }


def one_support_probe(rec: dict, *, child_budget: int) -> Tuple[dict, int]:
    """At most one arbitrary legal support action, then unrestricted direct joins."""

    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    g0 = int(rec["g"])
    used = 0
    best_len = int(rec["direct_len"])
    best_suit = rec["best_suit"]
    best_access = rec["access"]
    best_f2 = bool(rec["f2"])
    best_path: List = []
    improved = False
    for action in engine_tableau_actions(st)[0]:
        if action == ("deal",):
            continue
        if used >= child_budget:
            break
        used += 1
        cost = step_cost(st, action)
        cap = _capture(st, action)
        try:
            apply_action(st, action)
            for suit in SUITS:
                rw = direct_runway(st, suit, g0=g0 + cost)
                if rw["f2"] and not best_f2:
                    best_f2 = True
                    best_len = max(best_len, rw["direct_len"])
                    best_suit = suit
                    best_access = "FOUNDATION_REMOVED"
                    best_path = dump_actions([action]) + list(rw["path"] or [])
                    improved = True
                elif (not best_f2) and rw["direct_len"] > best_len:
                    best_len = rw["direct_len"]
                    best_suit = suit
                    best_access = rw["class"]
                    best_path = dump_actions([action]) + list(rw["path"] or [])
                    improved = True
        finally:
            _restore(st, cap)
    rec = dict(rec)
    rec["support_examined"] = True
    rec["support_len"] = best_len
    rec["support_suit"] = best_suit
    rec["support_access"] = best_access
    rec["support_path"] = best_path
    rec["improved_support"] = improved
    rec["f2"] = best_f2 or bool(rec["f2"])
    if best_f2:
        rec["f2_suit"] = rec.get("f2_suit") or best_suit
        rec["f2_path"] = rec.get("f2_path") or best_path
    return rec, used


def support_probe_order(rows: Sequence[dict]) -> List[dict]:
    deal_now = [r for r in rows if r["timing"] == "DEAL_NOW"]
    prep = [r for r in rows if r["timing"] != "DEAL_NOW"]
    buckets: Dict[tuple, List[dict]] = defaultdict(list)
    for r in prep:
        buckets[(r.get("best_suit"), r.get("access"), r.get("prep_depth"))].append(r)
    for b in buckets.values():
        b.sort(key=lambda r: (r["g"], r["ordered_digest"]))
    order = list(sorted(deal_now, key=lambda r: (r["g"], r["ordered_digest"])))
    keys = sorted(buckets)
    while any(buckets[k] for k in keys):
        for k in keys:
            if buckets[k]:
                order.append(buckets[k].pop(0))
    return order


def tally_group(rows: Sequence[dict]) -> dict:
    n = len(rows)
    by_suit_run = {s: 0 for s in SUITS}
    by_suit_ready = {s: 0 for s in SUITS}
    access = Counter()
    for r in rows:
        access[r.get("access") or "NEXT_ABSENT"] += 1
        bs = r.get("best_suit")
        if bs in by_suit_run:
            by_suit_run[bs] += 1
        for s in SUITS:
            info = (r.get("by_suit") or {}).get(s) or {}
            if info.get("class") == "NEXT_READY":
                by_suit_ready[s] += 1
    return {
        "n": n,
        "f2": sum(1 for r in rows if r.get("f2")),
        "runway_ge_6": sum(1 for r in rows if int(r.get("direct_len") or 0) >= 6),
        "runway_ge_5": sum(1 for r in rows if int(r.get("direct_len") or 0) >= 5),
        "runway_ge_4": sum(1 for r in rows if int(r.get("direct_len") or 0) >= 4),
        "runway_ge_3": sum(1 for r in rows if int(r.get("direct_len") or 0) >= 3),
        "next_ready": sum(1 for r in rows if r.get("access") == "NEXT_READY"),
        "next_one_move": sum(1 for r in rows if r.get("access") == "NEXT_ONE_MOVE"),
        "next_shallow": sum(1 for r in rows if r.get("access") == "NEXT_SHALLOW"),
        "next_medium": sum(1 for r in rows if r.get("access") == "NEXT_MEDIUM"),
        "next_deep": sum(1 for r in rows if r.get("access") == "NEXT_DEEP"),
        "next_face_down": sum(1 for r in rows if r.get("access") in ("NEXT_FACE_DOWN", "NEXT_ABSENT")),
        "empty_in_one": sum(1 for r in rows if r.get("empty_in_one")),
        "fd_reveal_in_one": sum(1 for r in rows if r.get("fd_reveal_in_one")),
        "improved_support": sum(1 for r in rows if r.get("improved_support")),
        "best_direct": 0 if not rows else max(int(r.get("direct_len") or 0) for r in rows),
        "best_support": 0 if not rows else max(int(r.get("support_len") or 0) for r in rows),
        "access": dict(access),
        "best_suit_counts": by_suit_run,
        "suit_next_ready": by_suit_ready,
        "direct_by_suit": {
            s: 0 if not rows else max(int(((r.get("by_suit") or {}).get(s) or {}).get("direct_len") or 0) for r in rows)
            for s in SUITS
        },
    }


def pareto_prep_improvements(deal_now: Sequence[dict], prep: Sequence[dict]) -> List[dict]:
    """Prep states whose continuation class is strictly better than every DEAL_NOW."""

    if not deal_now:
        return []
    dn_f2 = any(r.get("f2") for r in deal_now)
    dn_max = max(int(r.get("direct_len") or 0) for r in deal_now)
    dn_best_access = min(ACCESS_RANK.get(r.get("access") or "NEXT_ABSENT", 99) for r in deal_now)
    dn_ready = any(r.get("access") == "NEXT_READY" for r in deal_now)
    dn_one = any(r.get("access") == "NEXT_ONE_MOVE" for r in deal_now)
    dn_support = max(int(r.get("support_len") or 0) for r in deal_now)
    dn_min_g = min(int(r["g"]) for r in deal_now)
    out = []
    for r in prep:
        reasons = []
        if r.get("f2") and not dn_f2:
            reasons.append("local_foundation2")
        if int(r.get("direct_len") or 0) > dn_max and int(r["g"]) <= dn_min_g + 8:
            reasons.append("longer_direct_runway")
        acc = ACCESS_RANK.get(r.get("access") or "NEXT_ABSENT", 99)
        if int(r.get("direct_len") or 0) >= dn_max and acc < dn_best_access:
            if r.get("access") == "NEXT_READY" and not dn_ready:
                reasons.append("next_ready_vs_deal_now")
            elif r.get("access") == "NEXT_ONE_MOVE" and not dn_one and not dn_ready:
                reasons.append("next_one_move_vs_deal_now")
            elif acc < dn_best_access:
                reasons.append("better_next_access")
        if int(r.get("support_len") or 0) > dn_support and r.get("improved_support"):
            reasons.append("one_support_runway_unavailable_in_deal_now")
        if reasons:
            out.append(
                {
                    "g": r["g"],
                    "suit": r.get("best_suit"),
                    "direct_len": r.get("direct_len"),
                    "access": r.get("access"),
                    "timing": r["timing"],
                    "prep_depth": r["prep_depth"],
                    "prep_cost": r["prep_cost"],
                    "reasons": reasons,
                    "symmetry_digest": r["symmetry_digest"],
                }
            )
    out.sort(key=lambda w: (w["g"], w.get("direct_len") or 0))
    return out


def harvest_portfolio(rows: Sequence[dict]) -> List[dict]:
    """Operationally distinct 512-state future-search portfolio. No weighted score."""

    picked: List[dict] = []
    seen = set()

    def take(cands: Sequence[dict], n: int, cat: str) -> None:
        ordered = sorted(cands, key=lambda r: (r["g"], r.get("prep_depth", 0), r["ordered_digest"]))
        got = 0
        suits_used = Counter()
        for w in ordered:
            if got >= n or len(picked) >= PORTFOLIO_LIMIT:
                return
            ident = w["symmetry_digest"]
            if ident in seen:
                continue
            if suits_used[w.get("best_suit")] >= max(2, n // 2) and n >= 8:
                continue
            seen.add(ident)
            item = dict(w)
            item["portfolio_cat"] = cat
            picked.append(item)
            suits_used[w.get("best_suit")] += 1
            got += 1

    f2 = [r for r in rows if r.get("f2")]
    take(f2, 64, "A_F2")
    max_len = 0 if not rows else max(int(r.get("direct_len") or 0) for r in rows)
    take([r for r in rows if int(r.get("direct_len") or 0) >= max(max_len, 1)], 80, "B_LONGEST")
    take([r for r in rows if r.get("access") == "NEXT_READY" and int(r.get("direct_len") or 0) >= 2], 64, "C_READY")
    take([r for r in rows if r.get("access") == "NEXT_ONE_MOVE" and int(r.get("direct_len") or 0) >= 2], 64, "D_ONE_MOVE")
    take([r for r in rows if r.get("access") == "NEXT_SHALLOW" and int(r.get("direct_len") or 0) >= 2], 48, "E_SHALLOW")
    take([r for r in rows if r.get("empty_in_one") and int(r.get("direct_len") or 0) < max(3, max_len)], 48, "F_EMPTY")
    take([r for r in rows if r.get("fd_reveal_in_one") and int(r.get("direct_len") or 0) < max(3, max_len)], 48, "G_FD")
    for suit in SUITS:
        take([r for r in rows if r.get("best_suit") == suit], 16, "H_CHEAP_SUIT")
    take([r for r in rows if r.get("timing") == "DEAL_NOW"], 64, "I_DEAL_NOW")
    if len(picked) < PORTFOLIO_LIMIT:
        take(rows, PORTFOLIO_LIMIT - len(picked), "J_FILL")
    return picked[:PORTFOLIO_LIMIT]


def choose_verdict(p: dict) -> Tuple[str, str]:
    if not p.get("all_replay_ok"):
        return "SOURCE_REPLAY_FAILURE", "v0.43 pre-SD5 sources failed replay"
    if p.get("contract_fail"):
        return "RUNWAY_TRANSITION_CONTRACT_FAILURE", "a direct join was neither persist nor auto-removal"
    if not p.get("direct_complete"):
        return "SD5_RUNWAY_AUDIT_RESOURCE_LIMIT", "direct-runway audit did not finish inside 600s / 3 GiB"
    if p.get("f2"):
        return "PREP_CREATES_FOUNDATION2_LOCAL_TRANSACTION", "local K-A auto-removal produced Foundation 2"
    improvements = p.get("improvements") or []
    deal = p.get("deal_now") or {}
    prep = p.get("prep") or {}
    if improvements:
        reasons = {r for w in improvements for r in w.get("reasons") or []}
        if len(reasons) >= 2 or prep.get("next_ready", 0) > deal.get("next_ready", 0) + 10:
            return "PREP_CREATES_SUPERIOR_SD5_RUNWAY", "PREP_THEN_DEAL creates resource classes absent from DEAL_NOW"
        return "PREP_CREATES_SUPERIOR_SD5_RUNWAY", "PREP_THEN_DEAL strictly dominates DEAL_NOW on at least one runway class"
    good_prep = (
        (prep.get("next_ready") or 0)
        + (prep.get("next_one_move") or 0)
        + (prep.get("runway_ge_4") or 0)
    )
    good_deal = (
        (deal.get("next_ready") or 0)
        + (deal.get("next_one_move") or 0)
        + (deal.get("runway_ge_4") or 0)
    )
    if good_prep >= 20 and (prep.get("next_ready") or 0) and (prep.get("next_one_move") or 0):
        return "MULTIPLE_PREP_RUNWAY_CLASSES_VIABLE", "several distinct prep runway/access classes exist"
    if good_deal >= good_prep and (deal.get("best_direct") or 0) >= (prep.get("best_direct") or 0):
        return "DEAL_NOW_REMAINS_BEST_RESOURCE_TOPOLOGY", "just-in-time prep does not beat DEAL_NOW receiving quality"
    return (
        "JUST_IN_TIME_PREP_INSUFFICIENT",
        "depth<=4 / MW<=4 prep does not create a self-propelling post-Deal runway",
    )
