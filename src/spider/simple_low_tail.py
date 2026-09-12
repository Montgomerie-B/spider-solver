"""Research-only generic low-tail helpers.

A k-tail is the contiguous same-suit run k..(k-1)..1.
TAIL_k_READY means a movable (k-1)-tail can legally join an exposed matching k.

Transition classifier covers:

    FOUNDATION_AUTO_REMOVED   engine check_seq removed K-A of the target suit
    LOW_TAIL_PERSISTS         visible k-tail remains
    CONTRACT_FAILURE          neither

Production move/removal semantics are untouched.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from spider.cards import Card
from spider.engine import Column, SpiderState  # Column used by synthetic_columns
from spider.metrics import Action
from spider.packed_state import pack_post_stock_symmetry_state, pack_state
from spider.simple_current_horizon import current_tableau_occurrences
from spider.simple_deal1_preview import stock_rows
from spider.simple_diamond_c_bridge import dump_actions
from spider.simple_foundation_horizon import pretty_card
from spider.simple_foundation_race import suit_foundation_count
from spider.simple_progressive_solver import _capture, _restore, apply_action, step_cost
from spider.simple_tail4_auto_removal import foundation_is_ka, foundation_suits
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

FOUNDATION_AUTO_REMOVED = "FOUNDATION_AUTO_REMOVED"
LOW_TAIL_PERSISTS = "LOW_TAIL_PERSISTS"
CONTRACT_FAILURE = "CONTRACT_FAILURE"

UPPER_LABELS = {
    1: "{r} only",
    2: "{r1}-{r}",
}


def tail_present(state: SpiderState, suit: str, k: int) -> bool:
    want = list(range(k, 0, -1))
    for column in state.columns:
        up = column.face_up
        for i in range(len(up) - k + 1):
            run = up[i : i + k]
            if all(c.suit == suit and c.rank == want[j] for j, c in enumerate(run)):
                return True
    return False


def tail_packets(state: SpiderState, suit: str, k: int) -> List[dict]:
    want = list(range(k, 0, -1))
    actions, _ = engine_tableau_actions(state)
    out = []
    for col, column in enumerate(state.columns):
        up = column.face_up
        for i in range(len(up) - k + 1):
            run = up[i : i + k]
            if not all(c.suit == suit and c.rank == want[j] for j, c in enumerate(run)):
                continue
            above = [pretty_card(c) for c in up[i + k :]]
            exposed = not above
            movable = exposed and SpiderState.is_movable_run(run)
            dests = [act[1] for act in actions if act[0] == col and act[2] == k] if movable else []
            out.append(
                {
                    "column_0": col,
                    "column_1": col + 1,
                    "up_index": i,
                    "k": k,
                    "exposed": exposed,
                    "movable": movable,
                    "cards_above": len(above),
                    "above": above,
                    "dests_1": [d + 1 for d in dests],
                }
            )
    return out


def rank_cards(state: SpiderState, suit: str, rank: int) -> List[dict]:
    out = []
    actions, _ = engine_tableau_actions(state)
    for occ in current_tableau_occurrences(state, suit, rank):
        col = occ["column_0"]
        dests = []
        if occ.get("face_up") and not occ.get("top"):
            above_k = int(occ["cards_above"])
            up = state.columns[col].face_up
            run = up[-above_k:] if above_k else []
            if above_k and SpiderState.is_movable_run(run):
                dests = [act[1] + 1 for act in actions if act[0] == col and act[2] == above_k]
        if not occ.get("face_up"):
            n_up = len(state.columns[col].face_up)
            n_down_above = int(occ.get("face_down_blockers_above") or 0)
            if n_down_above == 0 and n_up and SpiderState.is_movable_run(state.columns[col].face_up):
                dests = [act[1] + 1 for act in actions if act[0] == col and act[2] == n_up]
        out.append(
            {
                "column_0": col,
                "column_1": occ["column_1"],
                "face_up": bool(occ.get("face_up")),
                "top": bool(occ.get("top")),
                "cards_above": int(occ.get("cards_above") or 0),
                "above": list(occ.get("face_up_above") or []),
                "one_move_exposable": bool(dests),
                "cover_dests_1": dests,
            }
        )
    return out


def tail_ready(state: SpiderState, suit: str, k: int) -> bool:
    """Movable (k-1)-tail can legally join an exposed matching rank k."""

    packets = tail_packets(state, suit, k - 1)
    recvs = rank_cards(state, suit, k)
    exposed = {t["column_0"] for t in recvs if t["top"]}
    for p in packets:
        if not p["movable"]:
            continue
        for dst in exposed:
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != k:
                continue
            if state.can_move(p["column_0"], dst, k - 1):
                return True
    return False


def legal_tail_joins(state: SpiderState, suit: str, k: int) -> List[Action]:
    """Legal moves of a (k-1)-tail onto an exposed matching rank k."""

    out = []
    for p in tail_packets(state, suit, k - 1):
        if not p["movable"]:
            continue
        for dst in range(10):
            if dst == p["column_0"]:
                continue
            top = state.columns[dst].top()
            if top is None or top.suit != suit or top.rank != k:
                continue
            if state.can_move(p["column_0"], dst, k - 1):
                out.append((p["column_0"], dst, k - 1))
    return out


def receiving_upper_run(state: SpiderState, dst: int, suit: str, top_rank: int) -> dict:
    up = state.columns[dst].face_up
    if not up or up[-1].suit != suit or up[-1].rank != top_rank:
        return {"length": 0, "ranks": [], "label": "none", "k_through": False, "top_rank": top_rank}
    ranks = [top_rank]
    i = len(up) - 2
    expect = top_rank + 1
    while i >= 0 and expect <= 13 and up[i].suit == suit and up[i].rank == expect:
        ranks.append(expect)
        expect += 1
        i -= 1
    ranks.reverse()
    n = len(ranks)
    k_through = n == (13 - top_rank + 1) and ranks[0] == 13
    if n == 1:
        label = f"{top_rank} only"
    else:
        label = "-".join(str(r) if r <= 10 else {11: "J", 12: "Q", 13: "K"}[r] for r in ranks)
        if k_through:
            label = f"K_THROUGH_{top_rank}"
    return {
        "length": n,
        "ranks": ranks,
        "label": label,
        "k_through": k_through,
        "k_through_5": k_through and top_rank == 5,
        "cards": [pretty_card(c) for c in up[len(up) - n :]],
        "dst_1": dst + 1,
        "top_rank": top_rank,
    }


def classify_low_tail_transition(state: SpiderState, g0: int, suit: str, action: Action, *, packet_head_rank: int) -> dict:
    """Classify one legal (packet_head_rank..A) -> (packet_head_rank+1) move."""

    recv = packet_head_rank + 1
    persist_k = packet_head_rank + 1
    before_n = len(state.foundations)
    before_suits = foundation_suits(state)
    before_target = suit_foundation_count(state, suit)
    upper = receiving_upper_run(state, action[1], suit, recv)
    cost = step_cost(state, action)
    cap = _capture(state, action)
    try:
        apply_action(state, action)
        after_n = len(state.foundations)
        after_suits = foundation_suits(state)
        after_target = suit_foundation_count(state, suit)
        persists = tail_present(state, suit, persist_k)
        auto = after_n == before_n + 1 and after_target == before_target + 1
        ka_ok = False
        if auto and state.foundations:
            ka_ok = foundation_is_ka(state.foundations[-1], suit)
        if auto and ka_ok:
            cls = FOUNDATION_AUTO_REMOVED
        elif not auto and persists:
            cls = LOW_TAIL_PERSISTS
        else:
            cls = CONTRACT_FAILURE
        return {
            "class": cls,
            "persist_name": f"TAIL{persist_k}_PERSISTS" if cls == LOW_TAIL_PERSISTS else cls,
            "g": g0 + cost,
            "join": dump_actions([action])[0],
            "ordered_digest": pack_state(state).hex(),
            "symmetry_digest": pack_post_stock_symmetry_state(state).hex(),
            "foundation_count": after_n,
            "foundation_suits": after_suits,
            "foundation_count_before": before_n,
            "target_foundations": after_target,
            "ka_ok": ka_ok,
            "tail_present": persists,
            "upper_run": upper,
            "fd": face_down_count(state),
            "empties": [i + 1 for i in empty_column_indices(state)],
            "stock": stock_rows(state),
            "packet_head_rank": packet_head_rank,
        }
    finally:
        _restore(state, cap)


def classify_all_joins(state: SpiderState, g0: int, suit: str, *, packet_head_rank: int) -> List[dict]:
    recv = packet_head_rank + 1
    return [
        classify_low_tail_transition(state, g0, suit, action, packet_head_rank=packet_head_rank)
        for action in legal_tail_joins(state, suit, recv)
    ]


def must_cross_tail_ready(k: int) -> str:
    return (
        f"The action which first creates a same-suit {k}-..-A tail must legally move "
        f"the existing {k-1}-..-A packet onto an exposed matching {k}. Immediately before "
        f"that action the state is TAIL{k}_READY."
    )


def synthetic_columns(face_up_runs: Sequence[Sequence[Card]], *, stock_n: int = 0, foundations=None) -> SpiderState:
    cols = [Column([], list(run)) for run in face_up_runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    stock = [Card("h", 3) for _ in range(stock_n)]
    return SpiderState(cols, stock, foundations or [])


def tail_run(suit: str, k: int) -> List[Card]:
    return [Card(suit, r) for r in range(k, 0, -1)]


def k_through_n(suit: str, n: int) -> List[Card]:
    return [Card(suit, r) for r in range(13, n - 1, -1)]
