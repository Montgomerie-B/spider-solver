"""Generic one-step deterministic Deal preview.

Clones the supplied state, applies the real engine Deal, and returns
telemetry. Never mutates the caller's state. Uses canonical MW_RULES
(Unrestricted Deal). Not a search heuristic and not a fitted scalar.
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from spider.engine import SpiderState
from spider.operational_viability import (
    compact_operational,
    foundation_operational_viability,
    operational_viability_key,
    rank_ready_suits,
)
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import pretty_card, stock_rows, tableau_actions
from spider.rules import MW_RULES, MobilityWareRules, deal_cost
from spider.structural_analysis import (
    SUITS,
    compact_interference,
    current_tableau_summary,
    foundation_readiness,
    foundation_suits,
    interference_debt,
)


def _structure(state: SpiderState, g: Optional[int]) -> dict:
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    ranked = rank_ready_suits(state, readiness=r, summary=s, g=int(g or 0))
    debt = compact_interference(interference_debt(state))
    founded = Counter(foundation_suits(state))
    unfinished = [suit for suit in SUITS if founded[suit] < 2]
    by_suit = {
        suit: compact_operational(
            foundation_operational_viability(state, suit, readiness=r, summary=s)
        )
        for suit in unfinished
    }
    best = ranked["best"]
    op_defined = best is not None and bool(best.get("material_ready"))
    return {
        "g": g,
        "stock_rows": stock_rows(state),
        "face_down": s["face_down"],
        "foundations": s["foundations"],
        "foundation_suits": list(s["foundation_suits"]),
        "empty_n": s["empty_n"],
        "legal_tableau": len(tableau_actions(state)),
        "same_suit_bonds": s["same_suit_bonds"],
        "visible_components": s["visible_runs"],
        "run_compression": s["run_compression"],
        "longest_run": s["longest_run"],
        "merge_edges": s["merge_edges"],
        "n_ready": ranked["n_ready"],
        "ready_suits": ranked["ready_suits"],
        "best_suit": ranked["best_suit"],
        "best": compact_operational(best) if best is not None else None,
        "op_defined": op_defined,
        "op_key": list(best["key"]) if op_defined and best is not None else None,
        "by_suit": by_suit,
        "unfinished_suits": unfinished,
        "interference": debt,
        "boundaries": int(debt.get("boundaries_total") or 0),
        "component_layers": int(debt.get("component_layers") or 0),
        "mixed_supports": int(debt.get("mixed_supports") or 0),
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "solved": state.is_solved(),
    }


def _landings(pre: SpiderState, incoming: list) -> list:
    hooks = [col.top() for col in pre.columns]
    rows = []
    for col_i, card in enumerate(incoming):
        top = hooks[col_i]
        rank_ok = bool(top is not None and top.rank == card.rank + 1)
        same_suit = bool(rank_ok and top is not None and top.suit == card.suit)
        empty_land = top is None
        mixed = bool(top is not None and not rank_ok)
        rows.append(
            {
                "column_1": col_i + 1,
                "card": pretty_card(card),
                "rank": card.rank,
                "suit": card.suit,
                "previous_top": None if top is None else pretty_card(top),
                "empty": empty_land,
                "rank_compatible": rank_ok,
                "same_suit_compatible": same_suit,
                "mixed_landing": mixed,
                "foundation_triggered": False,
            }
        )
    return rows


def _mark_foundations(pre_fu, pre_fd, pre_f, post: SpiderState, landings: list) -> None:
    if len(post.foundations) <= pre_f:
        return
    for i, row in enumerate(landings):
        fu = len(post.columns[i].face_up)
        fd = len(post.columns[i].face_down)
        if fu < pre_fu[i] or fd < pre_fd[i]:
            row["foundation_triggered"] = True


def preview_next_deal(
    state: SpiderState,
    pre_g: Optional[int] = None,
    *,
    rules: MobilityWareRules = MW_RULES,
    detail: str = "full",
) -> dict:
    """Return telemetry for the exact next engine Deal. Does not mutate ``state``.

    ``detail="harvest"`` omits per-suit topology; ``detail="full"`` reports
    unfinished-suit operational facts. Deal cost is always 1 when legal.
    """

    clone = state.clone()
    pre_digest = pack_state(clone).hex()
    pre_ident = pack_whole_game_identity(clone).hex()
    if len(clone.stock) < 10 or not clone.can_deal(rules):
        return {
            "ok": False,
            "can_deal": False,
            "pre_g": pre_g,
            "deal_cost": 0,
            "post_g": pre_g,
            "pre_digest": pre_digest,
            "post_digest": pre_digest,
            "reason": "cannot_deal",
        }
    incoming = list(clone.stock[-10:])
    landings = _landings(clone, incoming)
    pre_fu = [len(col.face_up) for col in clone.columns]
    pre_fd = [len(col.face_down) for col in clone.columns]
    pre_f = len(clone.foundations)
    pre_legal = len(tableau_actions(clone))
    pre_struct = _structure(clone, pre_g) if detail == "full" else None
    paid = clone.deal(rules)
    _mark_foundations(pre_fu, pre_fd, pre_f, clone, landings)
    post_g = None if pre_g is None else int(pre_g) + int(paid)
    post = _structure(clone, post_g) if detail == "full" else None
    if detail != "full":
        s = current_tableau_summary(clone)
        r = foundation_readiness(clone)
        ranked = rank_ready_suits(clone, readiness=r, summary=s, g=int(post_g or 0))
        debt = compact_interference(interference_debt(clone))
        best = ranked["best"]
        op_defined = best is not None and bool(best.get("material_ready"))
        post = {
            "g": post_g,
            "stock_rows": stock_rows(clone),
            "face_down": s["face_down"],
            "foundations": s["foundations"],
            "foundation_suits": list(s["foundation_suits"]),
            "empty_n": s["empty_n"],
            "legal_tableau": len(tableau_actions(clone)),
            "same_suit_bonds": s["same_suit_bonds"],
            "visible_components": s["visible_runs"],
            "run_compression": s["run_compression"],
            "longest_run": s["longest_run"],
            "merge_edges": s["merge_edges"],
            "n_ready": ranked["n_ready"],
            "ready_suits": ranked["ready_suits"],
            "best_suit": ranked["best_suit"],
            "best": compact_operational(best) if best is not None else None,
            "op_defined": op_defined,
            "op_key": list(best["key"]) if op_defined and best is not None else None,
            "by_suit": {},
            "unfinished_suits": [],
            "interference": debt,
            "boundaries": int(debt.get("boundaries_total") or 0),
            "component_layers": int(debt.get("component_layers") or 0),
            "mixed_supports": int(debt.get("mixed_supports") or 0),
            "ordered_digest": pack_state(clone).hex(),
            "whole_game_identity": pack_whole_game_identity(clone).hex(),
            "solved": clone.is_solved(),
        }
    rank_ok = sum(1 for x in landings if x["rank_compatible"])
    same_suit = sum(1 for x in landings if x["same_suit_compatible"])
    mixed = sum(1 for x in landings if x["mixed_landing"])
    empty_land = sum(1 for x in landings if x["empty"])
    auto_f = sum(1 for x in landings if x["foundation_triggered"])
    return {
        "ok": True,
        "can_deal": True,
        "pre_g": pre_g,
        "deal_cost": int(paid),
        "post_g": post_g,
        "pre_digest": pre_digest,
        "pre_identity": pre_ident,
        "post_digest": post["ordered_digest"],
        "post_identity": post["whole_game_identity"],
        "incoming": [pretty_card(c) for c in incoming],
        "landings": landings,
        "rank_ok": rank_ok,
        "same_suit": same_suit,
        "mixed": mixed,
        "empty_land": empty_land,
        "auto_foundations": auto_f,
        "pre_legal": pre_legal,
        "legal_tableau": post["legal_tableau"],
        "face_down": post["face_down"],
        "foundations": post["foundations"],
        "foundation_suits": post["foundation_suits"],
        "empty_n": post["empty_n"],
        "visible_components": post["visible_components"],
        "same_suit_bonds": post["same_suit_bonds"],
        "run_compression": post["run_compression"],
        "merge_edges": post["merge_edges"],
        "boundaries": post["boundaries"],
        "component_layers": post["component_layers"],
        "mixed_supports": post["mixed_supports"],
        "n_ready": post["n_ready"],
        "best_suit": post["best_suit"],
        "op_defined": post["op_defined"],
        "op_key": post["op_key"],
        "stock_rows": post["stock_rows"],
        "pre": pre_struct,
        "post": post,
        "solved": post["solved"],
        "expected_deal_cost": deal_cost(),
    }


def compact_preview(preview: dict) -> dict:
    if not preview:
        return {}
    return {
        k: preview.get(k)
        for k in (
            "ok",
            "pre_g",
            "deal_cost",
            "post_g",
            "post_digest",
            "rank_ok",
            "same_suit",
            "mixed",
            "empty_land",
            "auto_foundations",
            "pre_legal",
            "legal_tableau",
            "face_down",
            "foundations",
            "empty_n",
            "visible_components",
            "boundaries",
            "component_layers",
            "mixed_supports",
            "n_ready",
            "best_suit",
            "op_defined",
            "stock_rows",
        )
    }
