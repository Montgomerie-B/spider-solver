"""Research-only Heart-1 backward dependency map.

Labels and obligations are planning signals.  They are not legality,
state identity, or proof except where explicitly marked HARD.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.simple_foundation_horizon import (
    complete_sets,
    count_cards,
    pretty_card,
    stock_deal_rows,
    tableau_cards,
)
from spider.simple_progressive_solver import (
    Tier,
    _would_complete_foundation,
    classify_tier,
    is_deal,
)
from spider.simple_workspace_reachability import engine_tableau_actions

TARGET_DIRECT = "TARGET_DIRECT"
TARGET_SUPPORT = "TARGET_SUPPORT"
GENERAL_GOOD_PLAY = "GENERAL_GOOD_PLAY"
PARK = "PARK"
JOIN_BREAK = "JOIN_BREAK"
OTHER = "OTHER"
SD3_ACTION = "SD3"

LABEL_RANK = {
    TARGET_DIRECT: 0,
    TARGET_SUPPORT: 1,
    SD3_ACTION: 1,
    GENERAL_GOOD_PLAY: 2,
    PARK: 3,
    OTHER: 4,
    JOIN_BREAK: 5,
}


def future_stock_context(state: SpiderState) -> dict:
    rows = stock_deal_rows(state.stock)
    labels = []
    deals_done = 5 - len(rows)
    for index, row in enumerate(rows):
        labels.append(f"SD{deals_done + index + 1}")
    pretty_rows = {label: [pretty_card(card) for card in row] for label, row in zip(labels, rows)}
    counts = count_cards(tableau_cards(state))
    already = {suit: sum(1 for run in state.foundations if run and run[0].suit == suit) for suit in "shdc"}
    current_sets = {suit: already[suit] + complete_sets(suit, counts) for suit in "shdc"}
    unlocks = {}
    running = counts.copy()
    names = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}
    for label, row in zip(labels, rows):
        before = {suit: complete_sets(suit, running) for suit in "shdc"}
        running.update(count_cards(row))
        after = {suit: complete_sets(suit, running) for suit in "shdc"}
        gained = []
        for suit in "shdc":
            for extra in range(before[suit] + 1, after[suit] + 1):
                copy_n = already[suit] + extra
                ordinal = "first" if copy_n == 1 else "second"
                gained.append(f"{ordinal} {names[suit]}")
        unlocks[label] = gained
    return {
        "deals_done": deals_done,
        "stock_rows_remaining": len(rows),
        "rows": pretty_rows,
        "raw_rows": [[(c.suit, c.rank) for c in row] for row in rows],
        "current_complete_sets": current_sets,
        "unlocks": unlocks,
        "sd3": pretty_rows.get("SD3") or [],
        "sd4": pretty_rows.get("SD4") or [],
        "sd5": pretty_rows.get("SD5") or [],
        "sd3_raw": [(c.suit, c.rank) for c in rows[0]] if rows else [],
        "target": "first Hearts",
        "target_reason": (
            "After Spade 1, Heart 1 is the only additional foundation materially "
            "available before SD4. Diamond 1 unlocks at SD4; Clubs and all second "
            "foundations unlock at SD5."
        ),
    }


def _column_cards(column) -> List[Tuple[Card, str, int]]:
    """Bottom-to-top with zone and depth-from-top."""

    stacked = [("down", card) for card in column.face_down] + [("up", card) for card in column.face_up]
    n = len(stacked)
    out = []
    for index, (zone, card) in enumerate(stacked):
        out.append((card, zone, n - 1 - index))
    return out


def heart_occurrences(state: SpiderState, sd3: Sequence[Tuple[str, int]]) -> List[dict]:
    rows: List[dict] = []
    oid = 0
    for col_i, column in enumerate(state.columns):
        n_down = len(column.face_down)
        n_up = len(column.face_up)
        for d_i, card in enumerate(column.face_down):
            if card.suit != "h":
                continue
            depth_from_top = (n_down - 1 - d_i) + n_up
            above_down = [pretty_card(c) for c in column.face_down[d_i + 1 :]]
            above_up = [pretty_card(c) for c in column.face_up]
            rows.append(
                {
                    "id": f"T{oid}",
                    "rank": card.rank,
                    "rank_label": rank_str(card.rank),
                    "physical_column_0": col_i,
                    "physical_column_1": col_i + 1,
                    "depth_from_top": depth_from_top,
                    "zone": "down",
                    "face_up": False,
                    "cards_above": above_down + above_up,
                    "face_down_blockers_above": n_down - 1 - d_i,
                    "same_suit_component": None,
                    "currently_movable": False,
                    "buried": True,
                    "in_sd3": False,
                    "card": pretty_card(card),
                }
            )
            oid += 1
        for u_i, card in enumerate(column.face_up):
            if card.suit != "h":
                continue
            depth_from_top = n_up - 1 - u_i
            run = column.face_up[u_i:]
            heart_run = bool(run) and all(c.suit == "h" for c in run) and SpiderState.is_movable_run(run)
            rows.append(
                {
                    "id": f"T{oid}",
                    "rank": card.rank,
                    "rank_label": rank_str(card.rank),
                    "physical_column_0": col_i,
                    "physical_column_1": col_i + 1,
                    "depth_from_top": depth_from_top,
                    "zone": "up",
                    "face_up": True,
                    "cards_above": [pretty_card(c) for c in column.face_up[u_i + 1 :]],
                    "face_down_blockers_above": 0,
                    "same_suit_component": (
                        f"{rank_str(run[0].rank)}-{rank_str(run[-1].rank)}" if heart_run else None
                    ),
                    "currently_movable": heart_run,
                    "buried": depth_from_top > 0,
                    "in_sd3": False,
                    "card": pretty_card(card),
                }
            )
            oid += 1
    for col_i, (suit, rank) in enumerate(sd3):
        if suit != "h":
            continue
        rows.append(
            {
                "id": f"SD3C{col_i + 1}",
                "rank": rank,
                "rank_label": rank_str(rank),
                "physical_column_0": col_i,
                "physical_column_1": col_i + 1,
                "depth_from_top": None,
                "zone": "sd3",
                "face_up": False,
                "cards_above": [],
                "face_down_blockers_above": 0,
                "same_suit_component": None,
                "currently_movable": False,
                "buried": False,
                "in_sd3": True,
                "sd3_landing_column_1": col_i + 1,
                "card": pretty_card(Card(suit, rank)),
            }
        )
    return rows


def heart_components(state: SpiderState) -> List[dict]:
    components = []
    for col_i, column in enumerate(state.columns):
        up = column.face_up
        i = 0
        while i < len(up):
            if up[i].suit != "h":
                i += 1
                continue
            j = i + 1
            while j < len(up) and up[j].suit == "h" and up[j - 1].rank == up[j].rank + 1:
                j += 1
            run = up[i:j]
            suffix = i == 0 or True
            is_suffix = j == len(up)
            movable = is_suffix and SpiderState.is_movable_run(run)
            components.append(
                {
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "highest": run[0].rank,
                    "lowest": run[-1].rank,
                    "highest_label": rank_str(run[0].rank),
                    "lowest_label": rank_str(run[-1].rank),
                    "length": len(run),
                    "movable_as_block": movable,
                    "is_exposed_suffix": is_suffix,
                    "cards_above": [pretty_card(c) for c in up[j:]],
                    "naturally_joined_ranks": [rank_str(c.rank) for c in run],
                }
            )
            i = j
    return components


def copy_alternatives(occurrences: Sequence[dict]) -> dict:
    by_rank: Dict[int, List[str]] = defaultdict(list)
    for rec in occurrences:
        by_rank[int(rec["rank"])].append(rec["id"])
    ranks = {}
    n_two = 0
    for rank in range(13, 0, -1):
        ids = by_rank.get(rank, [])
        ranks[rank_str(rank)] = {
            "count": len(ids),
            "occurrence_ids": ids,
            "duplicate": len(ids) >= 2,
        }
        if len(ids) >= 2:
            n_two += 1
    enumerable = 1
    for rec in ranks.values():
        enumerable *= max(1, rec["count"]) if rec["count"] else 0
    return {
        "by_rank": ranks,
        "ranks_with_duplicates": n_two,
        "assignment_product": enumerable,
        "enumerated": enumerable <= 4096,
        "note": "Each rank may use any listed occurrence; assignments are not pre-committed.",
    }


def access_obligations(occurrences: Sequence[dict], alternatives: dict) -> dict:
    hard = []
    alt = []
    for rank in range(13, 0, -1):
        label = rank_str(rank)
        ids = alternatives["by_rank"][label]["occurrence_ids"]
        recs = [r for r in occurrences if r["id"] in ids]
        if len(recs) == 1:
            rec = recs[0]
            if rec.get("in_sd3"):
                hard.append(
                    {
                        "rank": label,
                        "kind": "unique_copy_in_sd3",
                        "occurrence": rec["id"],
                        "text": f"Heart {label} unique copy arrives only in SD3 column {rec['physical_column_1']}",
                    }
                )
            elif rec.get("buried") or not rec.get("face_up"):
                hard.append(
                    {
                        "rank": label,
                        "kind": "expose_unique_copy",
                        "occurrence": rec["id"],
                        "column_1": rec["physical_column_1"],
                        "text": (
                            f"Heart {label} unique tableau copy {rec['id']} must be exposed "
                            f"(zone={rec['zone']}, depth={rec['depth_from_top']})"
                        ),
                    }
                )
            else:
                hard.append(
                    {
                        "rank": label,
                        "kind": "use_unique_exposed_copy",
                        "occurrence": rec["id"],
                        "column_1": rec["physical_column_1"],
                        "text": f"Heart {label} unique exposed copy {rec['id']} must be used",
                    }
                )
        elif len(recs) >= 2:
            alt.append(
                {
                    "rank": label,
                    "kind": "choose_copy",
                    "occurrence_ids": ids,
                    "text": f"Heart {label} can come from {' or '.join(ids)}",
                }
            )
    return {"hard": hard, "alternative": alt}


def sd3_reception_analysis(state: SpiderState, sd3: Sequence[Tuple[str, int]], occurrences: Sequence[dict]) -> dict:
    unique_ids = set()
    by_rank = defaultdict(list)
    for rec in occurrences:
        by_rank[rec["rank"]].append(rec)
    for recs in by_rank.values():
        tableau = [r for r in recs if not r.get("in_sd3")]
        if len(tableau) == 1 and tableau[0].get("face_up") and tableau[0].get("depth_from_top") == 0:
            unique_ids.add(tableau[0]["id"])
    by_column = []
    for col_i, (suit, rank) in enumerate(sd3):
        top = state.columns[col_i].top()
        empty = state.columns[col_i].is_empty()
        incoming = pretty_card(Card(suit, rank))
        join = None
        if empty:
            join = "empty"
        elif top is not None and top.rank == rank + 1:
            join = "same_suit" if top.suit == suit else "mixed"
        buries_exposed_heart = bool(top and top.suit == "h" and not empty)
        useful_heart_arrival = suit == "h" and (empty or (top and top.suit == "h" and top.rank == rank + 1))
        by_column.append(
            {
                "column_1": col_i + 1,
                "incoming": incoming,
                "current_top": None if top is None else pretty_card(top),
                "join": join,
                "heart_arrival": suit == "h",
                "useful_heart_landing": useful_heart_arrival,
                "buries_current_top": not empty,
                "buries_exposed_heart": buries_exposed_heart,
            }
        )
    return {
        "by_column": by_column,
        "heart_arrivals": [row for row in by_column if row["heart_arrival"]],
        "useful_heart_landings": [row for row in by_column if row["useful_heart_landing"]],
        "covers_exposed_hearts": [row for row in by_column if row["buries_exposed_heart"]],
        "note": "Reception facts are planning signals, not new legality rules.",
    }


def admissible_lower_bound(state: SpiderState, obligations: dict) -> dict:
    """MW-cost lower bound.  Reveals may be zero-cost, so default is 0."""

    unique_sd3 = [o for o in obligations["hard"] if o["kind"] == "unique_copy_in_sd3"]
    if unique_sd3:
        return {
            "mw_lower_bound": 1,
            "admissible": True,
            "rationale": "at least one unique Heart rank arrives only in SD3, so Deal cost 1 is required",
            "unique_sd3_ranks": [o["rank"] for o in unique_sd3],
        }
    return {
        "mw_lower_bound": 0,
        "admissible": True,
        "rationale": (
            "Heart 1 is already materially present post-SD2.  Required access moves may "
            "be zero-cost whole-column relocates, so no positive MW bound is proved."
        ),
    }


def build_dependency_map(state: SpiderState, sd3: Sequence[Tuple[str, int]]) -> dict:
    occ = heart_occurrences(state, sd3)
    comps = heart_components(state)
    alts = copy_alternatives(occ)
    obl = access_obligations(occ, alts)
    recp = sd3_reception_analysis(state, sd3, occ)
    lb = admissible_lower_bound(state, obl)
    unique_buried_cols = set()
    for rec in occ:
        rank_ids = alts["by_rank"][rec["rank_label"]]["occurrence_ids"]
        if len(rank_ids) == 1 and not rec.get("in_sd3") and rec.get("buried"):
            unique_buried_cols.add(rec["physical_column_0"])
    return {
        "occurrences": occ,
        "components": comps,
        "copy_alternatives": alts,
        "obligations": obl,
        "sd3_reception": recp,
        "lower_bound": lb,
        "unique_buried_columns_0": sorted(unique_buried_cols),
        "hard_obligation_count": len(obl["hard"]),
        "alternative_obligation_count": len(obl["alternative"]),
    }


def _join_break(state: SpiderState, src: int, k: int) -> bool:
    src_col = state.columns[src]
    if k >= len(src_col.face_up):
        return False
    left = src_col.face_up[-k - 1]
    head = src_col.face_up[-k]
    return left.suit == head.suit and left.rank == head.rank + 1


def annotate_action(state: SpiderState, action, dep: dict, sd3: Sequence[Tuple[str, int]]) -> str:
    if is_deal(action) or action == ("deal",):
        return SD3_ACTION
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    dest_empty = dest_top is None
    jb = _join_break(state, src, k)
    same_suit_heart = (
        dest_top is not None
        and dest_top.suit == "h"
        and head.suit == "h"
        and dest_top.rank == head.rank + 1
    )
    completes_heart = False
    if _would_complete_foundation(state, src, dst, k):
        combined = (dst_col.face_up + run)[-13:]
        completes_heart = combined and combined[0].suit == "h"
    uncovers_heart = uncovers and src_col.face_down and src_col.face_down[-1].suit == "h"
    hard_uncover = uncovers and src in dep.get("unique_buried_columns_0", [])
    if completes_heart or same_suit_heart or uncovers_heart or hard_uncover:
        return TARGET_DIRECT
    # moving a non-heart off a heart suffix
    exposes_heart_in_column = uncovers is False and k == len(src_col.face_up) and not src_col.face_down
    heart_suffix_released = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        heart_suffix_released = left.suit == "h"
    sd3_prepare = False
    if dst < len(sd3) and sd3[dst][0] == "h":
        # vacate dst top if it would bury a useful heart landing, or empty dst
        sd3_prepare = dest_empty or (dest_top is not None and dest_top.suit == "h")
    if src < len(sd3) and sd3[src][0] == "h" and uncovers is False:
        sd3_prepare = True
    if heart_suffix_released or sd3_prepare or (dest_empty and head.suit == "h" and head.rank == 13):
        return TARGET_SUPPORT
    if jb:
        return JOIN_BREAK
    tier = classify_tier(state, action)
    if int(tier) == int(Tier.A):
        return GENERAL_GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


def action_allowed_at_level(label: str, tier: int, level: int, is_sd3: bool) -> bool:
    if is_sd3:
        return True
    if level >= 3:
        return True
    if level == 0:
        return label in (TARGET_DIRECT, TARGET_SUPPORT, GENERAL_GOOD_PLAY, SD3_ACTION)
    if level == 1:
        return label in (TARGET_DIRECT, TARGET_SUPPORT, GENERAL_GOOD_PLAY, SD3_ACTION) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK or True  # relaxed workspace includes parks and mixed; join-breaks allowed
    return True
