"""Research-only current-horizon occurrence API.

After SD4, stock_rows==1 and stock_deal_rows(state.stock)[0] is SD5.
pre_sd4_hearts() labels that row as in_sd3 and therefore leaks future cards
into current occurrence counts.  This module does not modify that helper.

CURRENT_TABLEAU     cards physically in tableau now
CURRENT_FOUNDATIONS cards already removed
NEXT_STOCK_ROW      SD5: known by perfect information, not yet material
"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

from spider.cards import rank_str
from spider.engine import SpiderState
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import (
    complete_sets,
    count_cards,
    missing_ranks,
    pretty_card,
    stock_deal_rows,
    tableau_cards,
)
from spider.simple_h9_cut import pre_sd4_hearts
from spider.simple_workspace_reachability import engine_tableau_actions

SUITS = ("s", "h", "d", "c")
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}


def next_stock_row(state: SpiderState) -> List:
    rows = stock_deal_rows(state.stock)
    return list(rows[0]) if rows else []


def current_tableau_occurrences(state: SpiderState, suit: str, rank: int) -> List[dict]:
    found: List[dict] = []
    for col_i, column in enumerate(state.columns):
        n_down = len(column.face_down)
        n_up = len(column.face_up)
        for d_i, card in enumerate(column.face_down):
            if card.suit != suit or card.rank != rank:
                continue
            found.append(
                {
                    "zone": "CURRENT_TABLEAU",
                    "face_up": False,
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "down_index": d_i,
                    "face_down_blockers_above": n_down - 1 - d_i,
                    "face_up_above": [pretty_card(c) for c in column.face_up],
                    "cards_above": (n_down - 1 - d_i) + n_up,
                    "top": False,
                }
            )
        for u_i, card in enumerate(column.face_up):
            if card.suit != suit or card.rank != rank:
                continue
            above = column.face_up[u_i + 1 :]
            found.append(
                {
                    "zone": "CURRENT_TABLEAU",
                    "face_up": True,
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "up_index": u_i,
                    "face_up_above": [pretty_card(c) for c in above],
                    "cards_above": len(above),
                    "top": u_i == n_up - 1,
                }
            )
    return found


def current_foundation_occurrences(state: SpiderState, suit: str, rank: int) -> List[dict]:
    found = []
    for i, run in enumerate(state.foundations):
        for card in run:
            if card.suit == suit and card.rank == rank:
                found.append({"zone": "CURRENT_FOUNDATIONS", "foundation_index": i, "face_up": True})
    return found


def next_stock_occurrences(state: SpiderState, suit: str, rank: int) -> List[dict]:
    found = []
    row = next_stock_row(state)
    for col_i, card in enumerate(row):
        if card.suit == suit and card.rank == rank:
            found.append(
                {
                    "zone": "NEXT_STOCK_ROW",
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "card": pretty_card(card),
                    "available_now": False,
                }
            )
    return found


def occurrence_counts(state: SpiderState, suit: str, rank: int) -> dict:
    tab = current_tableau_occurrences(state, suit, rank)
    found = current_foundation_occurrences(state, suit, rank)
    future = next_stock_occurrences(state, suit, rank)
    current = len(tab) + len(found)
    return {
        "suit": suit,
        "rank": rank,
        "rank_str": rank_str(rank),
        "current_count": current,
        "tableau_count": len(tab),
        "foundation_count": len(found),
        "future_stock_count": len(future),
        "future_after_SD5_count": current + len(future),
        "hard": current == 1,
        "alternative": current >= 2,
        "absent_now": current == 0,
        "tableau": tab,
        "foundations": found,
        "next_stock": future,
    }


def audit_pre_sd4_hearts_leak(state: SpiderState, rank: int = 9) -> dict:
    """Confirm whether pre_sd4_hearts includes the next stock row after SD4."""

    leaked = pre_sd4_hearts(state, rank)
    current = occurrence_counts(state, "h", rank)
    sd3_flags = [rec.get("in_sd3") for rec in leaked]
    leak = stock_rows(state) == 1 and any(sd3_flags) and current["future_stock_count"] > 0
    return {
        "confirmed": leak,
        "stock_rows": stock_rows(state),
        "legacy_count": len(leaked),
        "legacy_zones": [rec.get("zone") for rec in leaked],
        "current_tableau_count": current["tableau_count"],
        "future_stock_count": current["future_stock_count"],
        "reason": (
            "After SD4, stock_deal_rows(state.stock)[0] is SD5. pre_sd4_hearts() still "
            "appends that row as zone='sd3', so post-SD4 occurrence telemetry includes "
            "cards that are not yet materially available."
            if leak
            else "No post-SD4 SD5 leak observed for this rank."
        ),
    }


def current_material_counts(state: SpiderState) -> Counter:
    counts = count_cards(tableau_cards(state))
    counts.update(count_cards(c for run in state.foundations for c in run))
    return counts


def current_horizon_material_audit(state: SpiderState) -> dict:
    now = current_material_counts(state)
    future_row = next_stock_row(state)
    after = Counter(now)
    after.update(count_cards(future_row))
    suits = {}
    for suit in SUITS:
        first_now = complete_sets(suit, now)
        second_now = 1 if complete_sets(suit, now) >= 2 else 0
        suits[suit] = {
            "name": SUIT_NAMES[suit],
            "complete_sets_now": complete_sets(suit, now),
            "complete_sets_after_sd5": complete_sets(suit, after),
            "first_available_now": complete_sets(suit, now) >= 1,
            "second_available_now": complete_sets(suit, now) >= 2,
            "missing_for_first_now": [rank_str(r) for r in missing_ranks(suit, now, 1)],
            "missing_for_second_now": [rank_str(r) for r in missing_ranks(suit, now, 2)],
            "missing_for_first_after_sd5": [rank_str(r) for r in missing_ranks(suit, after, 1)],
            "sd5_supplies": [pretty_card(c) for c in future_row if c.suit == suit],
        }
    return {
        "stock_rows": stock_rows(state),
        "next_row": [pretty_card(c) for c in future_row],
        "suits": suits,
        "candidate_first_foundations_now": [
            SUIT_NAMES[s] for s in SUITS if suits[s]["first_available_now"] and s != "s" or (s == "s" and suits[s]["second_available_now"])
        ],
        "heart_1_now": suits["h"]["first_available_now"],
        "diamond_1_now": suits["d"]["first_available_now"],
        "spade_2_now": suits["s"]["second_available_now"],
        "club_1_now": suits["c"]["first_available_now"],
    }


def packet_movable(state: SpiderState, col: int) -> dict:
    column = state.columns[col]
    if not column.face_up:
        return {"movable": False, "k": 0, "dests": []}
    k = 1
    while k < len(column.face_up) and SpiderState.is_movable_run(column.face_up[-k - 1 :]):
        k += 1
    dests = []
    for action in engine_tableau_actions(state)[0]:
        if action[0] == col and action[2] == k:
            dests.append(action[1])
    return {"movable": bool(dests), "k": k, "dests": dests}


def same_suit_components(state: SpiderState, suit: str) -> List[dict]:
    out = []
    for col_i, column in enumerate(state.columns):
        run = []
        for card in reversed(column.face_up):
            if card.suit != suit:
                break
            if run and run[-1].rank != card.rank - 1:
                break
            run.append(card)
        run.reverse()
        if len(run) >= 2:
            out.append(
                {
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "cards": [pretty_card(c) for c in run],
                    "length": len(run),
                    "head": pretty_card(run[0]),
                    "tail": pretty_card(run[-1]),
                }
            )
    return out


def backward_map(state: SpiderState, suit: str) -> dict:
    ranks = {}
    hard = []
    alt = []
    absent = []
    for rank in range(1, 14):
        rec = occurrence_counts(state, suit, rank)
        copies = []
        for occ in rec["tableau"]:
            col = occ["column_0"]
            mov = packet_movable(state, col) if occ.get("top") else {"movable": False, "k": 0, "dests": []}
            copies.append({**occ, **mov, "obligation": "HARD" if rec["hard"] else "ALTERNATIVE"})
        ranks[rank_str(rank)] = {
            "current_count": rec["current_count"],
            "future_after_SD5_count": rec["future_after_SD5_count"],
            "hard": rec["hard"],
            "copies": copies,
        }
        if rec["hard"]:
            hard.append(rank_str(rank))
        elif rec["alternative"]:
            alt.append(rank_str(rank))
        elif rec["absent_now"]:
            absent.append(rank_str(rank))
    gates = []
    for label in hard:
        rank = {"A": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10, "J": 11, "Q": 12, "K": 13}[label]
        rec = ranks[label]
        for occ in rec["copies"]:
            if occ.get("top") and occ.get("movable"):
                status = "exposed_movable"
            elif occ.get("top"):
                status = "exposed_blocked"
            elif occ.get("face_up"):
                status = "face_up_buried"
            else:
                status = "face_down"
            gates.append(
                {
                    "card": f"{label}{suit.upper()}",
                    "status": status,
                    "column_1": occ.get("column_1"),
                    "cards_above": occ.get("cards_above"),
                    "face_up_above": occ.get("face_up_above"),
                    "movable": occ.get("movable"),
                    "requires_reveal": not occ.get("face_up"),
                    "requires_landing": occ.get("top") and not occ.get("movable"),
                }
            )
    return {
        "suit": suit,
        "hard_ranks": hard,
        "alternative_ranks": alt,
        "absent_now": absent,
        "components": same_suit_components(state, suit),
        "ranks": ranks,
        "nearest_gates": gates,
    }
