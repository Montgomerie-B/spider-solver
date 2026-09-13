"""Generic solution-strategy forensics.

Replay telemetry only. Does not change search policy or read routes for
solver decisions. Physical card labels are research identities, not engine
semantics.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.heuristics import reception_fitness
from spider.metrics import Action, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import (
    apply_action,
    empty_column_indices,
    face_down_count,
    foundation_suits,
    is_deal,
    step_cost,
    stock_deal_rows,
    stock_rows,
    tableau_actions,
)
from spider.structural_analysis import (
    SUITS,
    current_tableau_summary,
    foundation_readiness,
    next_foundation_material,
    suit_readiness,
)

ROOT = Path(__file__).resolve().parents[2]
DEAL_PATH = ROOT / "deals" / "4925153.txt"
AUTO_MOVES = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CANON_MOVES = ROOT / "solutions" / "4925153_canonical.moves"

EPOCH_LABELS = {
    5: "pre-SD1",
    4: "SD1-SD2",
    3: "SD2-SD3",
    2: "SD3-SD4",
    1: "SD4-SD5",
    0: "post-SD5",
}


def load_opening() -> Tuple[SpiderState, List[Card], Dict[int, str]]:
    raw = list(load_deal(DEAL_PATH))
    labels = physical_labels(raw)
    opening = SpiderState.from_cards(raw)
    return opening, raw, labels


def physical_labels(cards: Sequence[Card]) -> Dict[int, str]:
    """Stable labels from initial deal order. Duplicate rank/suit → #A then #B."""

    seen: Counter = Counter()
    out: Dict[int, str] = {}
    for card in cards:
        key = (card.suit, card.rank)
        seen[key] += 1
        n = seen[key]
        suffix = {1: "A", 2: "B"}.get(n, str(n))
        out[id(card)] = f"{rank_str(card.rank)}{card.suit.upper()}#{suffix}"
    return out


def pretty_loc(state: SpiderState, card: Card) -> str:
    for i, col in enumerate(state.columns):
        for j, c in enumerate(col.face_down):
            if c is card:
                return f"col{i + 1}.down[{j}]"
        for j, c in enumerate(col.face_up):
            if c is card:
                return f"col{i + 1}.up[{j}]"
    for j, c in enumerate(state.stock):
        if c is card:
            return f"stock[{j}]"
    for fi, run in enumerate(state.foundations):
        for j, c in enumerate(run):
            if c is card:
                return f"foundation{fi}[{j}]"
    return "unknown"


def locate_all(state: SpiderState, labels: Dict[int, str]) -> Dict[str, str]:
    return {lab: pretty_loc(state, card) for card, lab in ((None, None),) if False}


def structural_view(state: SpiderState) -> dict:
    s = current_tableau_summary(state)
    r = foundation_readiness(state)
    mat = next_foundation_material(state)
    by_suit = {}
    for suit in SUITS:
        rd = r["by_suit"][suit]
        by_suit[suit] = {
            "material_complete_now": rd.get("material_complete_now"),
            "deals_until_material": rd.get("deals_until_material"),
            "cover": rd.get("cover"),
            "visible": rd.get("visible"),
            "fd": rd.get("fd"),
            "longest": rd.get("longest"),
            "cond_len": rd.get("cond_len"),
            "edges": rd.get("edges"),
            "k_len": rd.get("k_len"),
            "a_len": rd.get("a_len"),
            "gap": rd.get("gap"),
            "bonds": rd.get("bonds"),
            "founded": rd.get("founded"),
        }
    return {
        "stock_rows": s["stock_rows"],
        "foundations": s["foundations"],
        "foundation_suits": list(s["foundation_suits"]),
        "face_down": s["face_down"],
        "empty_n": s["empty_n"],
        "empty_columns": [i + 1 for i in empty_column_indices(state)],
        "legal_tableau": len(tableau_actions(state)),
        "same_suit_bonds": s["same_suit_bonds"],
        "run_compression": s["run_compression"],
        "longest_run": s["longest_run"],
        "merge_edges": s["merge_edges"],
        "n_ready": r["n_ready"],
        "ready_suits": list(r["ready_suits"]),
        "nearest_horizon": r["nearest_horizon"],
        "nearest_suits": list(r["nearest_suits"]),
        "by_suit": by_suit,
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
    }


def _same_suit_attach(dest_top: Optional[Card], run: Sequence[Card]) -> bool:
    return bool(dest_top and run and dest_top.suit == run[0].suit and dest_top.rank == run[0].rank + 1)


def classify_tableau(
    *,
    cost: int,
    flipped: bool,
    removed: bool,
    dest_was_empty: bool,
    empty_before: int,
    empty_after: int,
    bonds_before: int,
    bonds_after: int,
    dest_top: Optional[Card],
    run: Sequence[Card],
    broke_same_suit: bool,
    rehandle: bool,
    mixed_release: bool,
    near_deal: bool,
) -> List[str]:
    tags: List[str] = []
    if cost == 0:
        tags.append("ZERO_COST_RELOCATION")
    if flipped:
        tags.append("REVEAL")
    if removed:
        tags.append("FOUNDATION_TRIGGER")
    if dest_was_empty:
        tags.append("EMPTY_CONSUMED")
        if run and run[0].rank == 13:
            tags.append("RECEIVER_CREATION")
    if empty_after > empty_before:
        tags.append("EMPTY_CREATED")
    if bonds_after > bonds_before:
        tags.append("SAME_SUIT_BOND_GAIN")
    if bonds_after < bonds_before:
        tags.append("SAME_SUIT_BOND_LOSS")
    if _same_suit_attach(dest_top, run):
        tags.append("COMPONENT_MERGE")
    elif dest_top is not None and run and dest_top.suit != run[0].suit:
        tags.append("MIXED_SUIT_PARK")
    if broke_same_suit:
        tags.append("COMPONENT_BREAK")
    if mixed_release:
        tags.append("PARK_RELEASE")
    if rehandle:
        tags.append("REHANDLE")
    if near_deal and dest_was_empty:
        tags.append("DEAL_PREPARATION")
    if not tags:
        tags.append("OTHER")
    return tags


def exclusive_bucket(tags: Sequence[str], cost: int) -> str:
    if cost == 0:
        return "ZERO_COST_RELOCATION"
    if "FOUNDATION_TRIGGER" in tags:
        return "FOUNDATION_TRIGGER"
    if "REHANDLE" in tags:
        return "REHANDLE"
    if "REVEAL" in tags:
        return "REVEAL"
    if "COMPONENT_MERGE" in tags or "SAME_SUIT_BOND_GAIN" in tags:
        return "PRIMARY_PROGRESS"
    if "MIXED_SUIT_PARK" in tags:
        return "MIXED_SUIT_PARK"
    return "OTHER_PAID"


def instrumented_replay(
    opening: SpiderState,
    actions: Sequence[Action],
    labels: Dict[int, str],
    *,
    expected_g: Optional[int] = None,
) -> dict:
    verify = opening.clone()
    total = replay_actions(verify, list(actions))
    if not verify.is_solved():
        raise ValueError("route is not solved")
    if expected_g is not None and total != expected_g:
        raise ValueError(f"expected g={expected_g}, got {total}")
    deals_n = sum(1 for a in actions if is_deal(a))
    if deals_n != 5:
        raise ValueError(f"expected 5 deals, got {deals_n}")

    state = opening.clone()
    life: Dict[str, dict] = {}
    for col_i, col in enumerate(state.columns):
        for card in col.face_down:
            lab = labels[id(card)]
            life[lab] = {
                "label": lab,
                "suit": card.suit,
                "rank": card.rank,
                "initial": f"col{col_i + 1}.down",
                "initial_zone": "face_down",
                "deal_row": None,
                "first_exposure_g": None,
                "first_move_g": None,
                "move_actions": 0,
                "paid_actions": 0,
                "zero_cost_actions": 0,
                "first_same_suit_attach_g": None,
                "durable_component_g": None,
                "foundation_g": None,
                "paid_after_attach": 0,
                "mixed_park_g": None,
            }
        for card in col.face_up:
            lab = labels[id(card)]
            life[lab] = {
                "label": lab,
                "suit": card.suit,
                "rank": card.rank,
                "initial": f"col{col_i + 1}.up",
                "initial_zone": "face_up",
                "deal_row": None,
                "first_exposure_g": 0,
                "first_move_g": None,
                "move_actions": 0,
                "paid_actions": 0,
                "zero_cost_actions": 0,
                "first_same_suit_attach_g": None,
                "durable_component_g": None,
                "foundation_g": None,
                "paid_after_attach": 0,
                "mixed_park_g": None,
            }
    stock_cards = list(state.stock)
    rows = stock_deal_rows(stock_cards)
    for ri, row in enumerate(rows):
        for card in row:
            lab = labels[id(card)]
            life[lab] = {
                "label": lab,
                "suit": card.suit,
                "rank": card.rank,
                "initial": "stock",
                "initial_zone": "stock",
                "deal_row": ri + 1,
                "first_exposure_g": None,
                "first_move_g": None,
                "move_actions": 0,
                "paid_actions": 0,
                "zero_cost_actions": 0,
                "first_same_suit_attach_g": None,
                "durable_component_g": None,
                "foundation_g": None,
                "paid_after_attach": 0,
                "mixed_park_g": None,
            }

    mixed_resident: set = set()
    action_log: List[dict] = []
    foundations_log: List[dict] = []
    deal_log: List[dict] = []
    g = 0
    tableau_i = 0
    deal_i = 0
    bucket_mw = Counter()
    tag_mw = Counter()
    remaining_final = total

    def expose(card: Card) -> None:
        lab = labels[id(card)]
        rec = life[lab]
        if rec["first_exposure_g"] is None:
            rec["first_exposure_g"] = g

    for idx, action in enumerate(actions):
        s_before = current_tableau_summary(state)
        empty_before = s_before["empty_n"]
        bonds_before = s_before["same_suit_bonds"]
        f_before = len(state.foundations)
        fd_before = s_before["face_down"]
        rows_before = stock_rows(state)
        near_deal = (not is_deal(action)) and any(is_deal(a) for a in actions[idx + 1 : idx + 4])

        if is_deal(action):
            incoming = list(state.stock[-10:]) if len(state.stock) >= 10 else []
            hooks = [col.top() for col in state.columns]
            land = []
            for col_i, card in enumerate(incoming):
                top = hooks[col_i]
                rec = {
                    "column_1": col_i + 1,
                    "card": labels[id(card)],
                    "rank_ok": bool(top is not None and top.rank == card.rank + 1),
                    "same_suit": bool(top is not None and top.suit == card.suit and top.rank == card.rank + 1),
                    "mixed_block": bool(top is not None and top.rank != card.rank + 1),
                    "empty_land": top is None,
                    "king_empty": top is None and card.rank == 13,
                }
                land.append(rec)
                expose(card)
            fit = reception_fitness(state, incoming)
            cost = apply_action(state, action)
            g += cost
            deal_i += 1
            s_after = current_tableau_summary(state)
            f_after = len(state.foundations)
            rec = {
                "action_index": idx,
                "kind": "deal",
                "deal_number": deal_i,
                "stock_epoch_before": rows_before,
                "cost": cost,
                "g": g,
                "zero_cost": False,
                "foundations_before": f_before,
                "foundations_after": f_after,
                "face_down_before": fd_before,
                "face_down_after": s_after["face_down"],
                "empty_before": empty_before,
                "empty_after": s_after["empty_n"],
                "bonds_before": bonds_before,
                "bonds_after": s_after["same_suit_bonds"],
                "landings": land,
                "rank_ok": sum(1 for x in land if x["rank_ok"]),
                "same_suit_land": sum(1 for x in land if x["same_suit"]),
                "mixed_block": sum(1 for x in land if x["mixed_block"]),
                "empty_land": sum(1 for x in land if x["empty_land"]),
                "reception_fitness": fit,
                "legal_after": len(tableau_actions(state)),
                "n_ready_after": foundation_readiness(state)["n_ready"],
                "remaining_cost": total - g,
            }
            deal_log.append(rec)
            action_log.append({**rec, "tags": ["DEAL"]})
            bucket_mw["DEAL"] += cost
            if f_after > f_before:
                for run in state.foundations[f_before:]:
                    suit = run[0].suit
                    for c in run:
                        life[labels[id(c)]]["foundation_g"] = g
                    foundations_log.append(
                        {
                            "n": f_after,
                            "g": g,
                            "stock_rows": stock_rows(state),
                            "action_index": idx,
                            "suit": suit,
                            "via": "deal",
                            "face_down": s_after["face_down"],
                            "empty_n": s_after["empty_n"],
                        }
                    )
            continue

        src, dst, k = action  # type: ignore[misc]
        src_col = state.columns[src]
        dst_col = state.columns[dst]
        dest_was_empty = dst_col.is_empty()
        dest_top = dst_col.top()
        run = list(src_col.face_up[-k:])
        broke = False
        if k < len(src_col.face_up):
            left = src_col.face_up[-k - 1]
            if left.suit == run[0].suit and left.rank == run[0].rank + 1:
                broke = True
        run_labs = [labels[id(c)] for c in run]
        rehandle = any(life[lab]["paid_actions"] > 0 for lab in run_labs)
        mixed_release = any(lab in mixed_resident for lab in run_labs)
        cost = step_cost(state, action)
        flipped = (k == len(src_col.face_up) and bool(src_col.face_down))
        apply_action(state, action)
        g += cost
        tableau_i += 1
        s_after = current_tableau_summary(state)
        f_after = len(state.foundations)
        removed = f_after > f_before
        if flipped:
            # newly exposed is now src face_up[0] after flip of previous down
            if state.columns[src].face_up:
                expose(state.columns[src].face_up[0])
        tags = classify_tableau(
            cost=cost,
            flipped=flipped,
            removed=removed,
            dest_was_empty=dest_was_empty,
            empty_before=empty_before,
            empty_after=s_after["empty_n"],
            bonds_before=bonds_before,
            bonds_after=s_after["same_suit_bonds"],
            dest_top=dest_top,
            run=run,
            broke_same_suit=broke,
            rehandle=rehandle,
            mixed_release=mixed_release,
            near_deal=near_deal,
        )
        bucket = exclusive_bucket(tags, cost)
        bucket_mw[bucket] += cost
        for t in tags:
            tag_mw[t] += cost if cost else 0
        attach = _same_suit_attach(dest_top, run)
        mixed = dest_top is not None and run and dest_top.suit != run[0].suit
        for lab in run_labs:
            rec = life[lab]
            rec["move_actions"] += 1
            if rec["first_move_g"] is None:
                rec["first_move_g"] = g
            if cost == 0:
                rec["zero_cost_actions"] += 1
            else:
                rec["paid_actions"] += 1
                if rec["first_same_suit_attach_g"] is not None:
                    rec["paid_after_attach"] += 1
            if attach and rec["first_same_suit_attach_g"] is None:
                rec["first_same_suit_attach_g"] = g
            if attach and rec["durable_component_g"] is None:
                rec["durable_component_g"] = g
            if mixed:
                mixed_resident.add(lab)
                if rec["mixed_park_g"] is None:
                    rec["mixed_park_g"] = g
            else:
                mixed_resident.discard(lab)
        if removed:
            for run_f in state.foundations[f_before:]:
                suit = run_f[0].suit
                for c in run_f:
                    life[labels[id(c)]]["foundation_g"] = g
                foundations_log.append(
                    {
                        "n": len(state.foundations),
                        "g": g,
                        "stock_rows": stock_rows(state),
                        "action_index": idx,
                        "suit": suit,
                        "via": "tableau",
                        "face_down_before": fd_before,
                        "face_down": s_after["face_down"],
                        "empty_before": empty_before,
                        "empty_n": s_after["empty_n"],
                        "bonds_before": bonds_before,
                        "bonds_after": s_after["same_suit_bonds"],
                    }
                )
        action_log.append(
            {
                "action_index": idx,
                "tableau_index": tableau_i,
                "kind": "tableau",
                "action": [src, dst, k],
                "src_1": src + 1,
                "dst_1": dst + 1,
                "k": k,
                "stock_epoch": rows_before,
                "cost": cost,
                "g": g,
                "zero_cost": cost == 0,
                "flipped": flipped,
                "removed": removed,
                "cards": run_labs,
                "empty_before": empty_before,
                "empty_after": s_after["empty_n"],
                "fd_before": fd_before,
                "fd_after": s_after["face_down"],
                "tags": tags,
                "bucket": bucket,
                "remaining_cost": total - g,
            }
        )

    if not state.is_solved() or stock_rows(state) != 0 or len(state.foundations) != 8:
        raise ValueError("terminal contract failed")
    if any(not col.is_empty() for col in state.columns):
        raise ValueError("tableau not empty")

    missing = [lab for lab, rec in life.items() if rec["foundation_g"] is None]
    if missing:
        raise ValueError(f"cards never founded: {missing[:8]}")

    return {
        "g": total,
        "n_deals": deals_n,
        "n_actions": len(actions),
        "tableau_commands": sum(1 for a in actions if not is_deal(a)),
        "zero_cost_commands": sum(1 for rec in action_log if rec.get("zero_cost")),
        "solved": True,
        "replay_ok": True,
        "actions": action_log,
        "deal_events": deal_log,
        "foundations": foundations_log,
        "lifecycle": life,
        "bucket_mw": dict(bucket_mw),
        "tag_mw": dict(tag_mw),
        "n_physical": len(life),
    }


def extract_epochs(trace: dict, opening: SpiderState, actions: Sequence[Action], labels: Dict[int, str]) -> List[dict]:
    """Rebuild epoch enter/exit snapshots by replaying, attaching remaining cost."""

    state = opening.clone()
    final_g = trace["g"]
    g = 0
    epochs = []
    start_i = 0
    deal_n = 0

    def enter_pack(si: int) -> dict:
        view = structural_view(state)
        view["g"] = g
        view["action_index"] = si
        view["remaining_cost"] = final_g - g
        return view

    cur = {"label": EPOCH_LABELS[stock_rows(state)], "stock_rows": stock_rows(state), "enter": enter_pack(0), "tableau_n": 0, "zero_cost": 0, "paid": 0}
    for idx, action in enumerate(actions):
        if is_deal(action):
            cur["exit"] = enter_pack(idx)
            cur["delta_g"] = cur["exit"]["g"] - cur["enter"]["g"]
            cur["fd_delta"] = cur["exit"]["face_down"] - cur["enter"]["face_down"]
            cur["bonds_delta"] = cur["exit"]["same_suit_bonds"] - cur["enter"]["same_suit_bonds"]
            cur["empty_enter"] = cur["enter"]["empty_n"]
            cur["empty_exit"] = cur["exit"]["empty_n"]
            cur["foundations_enter"] = cur["enter"]["foundations"]
            cur["foundations_exit"] = cur["exit"]["foundations"]
            epochs.append(cur)
            cost = apply_action(state, action)
            g += cost
            deal_n += 1
            post = enter_pack(idx + 1)
            pre = epochs[-1]["exit"]
            deal_rec = {
                "label": f"SD{deal_n}",
                "stock_rows": stock_rows(state) + 1,
                "is_deal": True,
                "enter": pre,
                "exit": post,
                "delta_g": cost,
                "paid": cost,
                "zero_cost": 0,
                "tableau_n": 0,
                "fd_delta": post["face_down"] - pre["face_down"],
                "bonds_delta": post["same_suit_bonds"] - pre["same_suit_bonds"],
                "foundations_enter": pre["foundations"],
                "foundations_exit": post["foundations"],
                "empty_enter": pre["empty_n"],
                "empty_exit": post["empty_n"],
                "remaining_cost_after": final_g - g,
            }
            epochs.append(deal_rec)
            cur = {
                "label": EPOCH_LABELS[stock_rows(state)],
                "stock_rows": stock_rows(state),
                "enter": enter_pack(idx + 1),
                "tableau_n": 0,
                "zero_cost": 0,
                "paid": 0,
            }
            continue
        cost = step_cost(state, action)
        apply_action(state, action)
        g += cost
        cur["tableau_n"] += 1
        if cost == 0:
            cur["zero_cost"] += 1
        else:
            cur["paid"] += cost
    cur["exit"] = enter_pack(len(actions))
    cur["delta_g"] = cur["exit"]["g"] - cur["enter"]["g"]
    cur["fd_delta"] = cur["exit"]["face_down"] - cur["enter"]["face_down"]
    cur["bonds_delta"] = cur["exit"]["same_suit_bonds"] - cur["enter"]["same_suit_bonds"]
    cur["empty_enter"] = cur["enter"]["empty_n"]
    cur["empty_exit"] = cur["exit"]["empty_n"]
    cur["foundations_enter"] = cur["enter"]["foundations"]
    cur["foundations_exit"] = cur["exit"]["foundations"]
    cur["remaining_cost_after"] = 0
    epochs.append(cur)
    return epochs


def rehandling_summary(trace: dict) -> dict:
    paid_rehandle = 0
    n_rehandle = 0
    ambiguous = 0
    cards_paid_after_attach = []
    for rec in trace["actions"]:
        if rec.get("kind") != "tableau":
            continue
        if "REHANDLE" in rec.get("tags", []) and rec.get("cost", 0) > 0:
            n_rehandle += 1
            paid_rehandle += rec["cost"]
        if rec.get("bucket") == "OTHER_PAID":
            ambiguous += rec["cost"]
    for lab, life in trace["lifecycle"].items():
        if life["paid_after_attach"]:
            cards_paid_after_attach.append({"label": lab, "paid_after_attach": life["paid_after_attach"]})
    cards_paid_after_attach.sort(key=lambda r: -r["paid_after_attach"])
    repeat_movers = [
        {"label": lab, "paid_actions": life["paid_actions"]}
        for lab, life in trace["lifecycle"].items()
        if life["paid_actions"] >= 2
    ]
    repeat_movers.sort(key=lambda r: -r["paid_actions"])
    return {
        "paid_mw_tagged_rehandle": paid_rehandle,
        "rehandle_actions": n_rehandle,
        "ambiguous_other_paid_mw": ambiguous,
        "cards_paid_after_same_suit_attach": cards_paid_after_attach[:20],
        "n_cards_paid_after_attach": len(cards_paid_after_attach),
        "repeat_paid_movers": repeat_movers[:20],
        "n_repeat_paid_movers": len(repeat_movers),
        "note": "Rehandle MW is conservative exclusive-bucket overlap; multi-tags may also apply.",
    }


def epoch_waterfall(auto_epochs: Sequence[dict], canon_epochs: Sequence[dict]) -> List[dict]:
    rows = []
    cum = 0
    if len(auto_epochs) != len(canon_epochs):
        raise ValueError("epoch streams differ in length")
    for a, c in zip(auto_epochs, canon_epochs):
        d198 = int(a["delta_g"])
        d172 = int(c["delta_g"])
        delta = d198 - d172
        cum += delta
        rows.append(
            {
                "label": a["label"],
                "stock_rows": a.get("stock_rows"),
                "auto_delta": d198,
                "canon_delta": d172,
                "delta_198_minus_172": delta,
                "cumulative_gap": cum,
                "auto_g_after": a.get("exit", a.get("exit") or {}).get("g") if isinstance(a.get("exit"), dict) else a.get("exit", {}).get("g") if a.get("exit") else None,
            }
        )
    if rows[-1]["cumulative_gap"] != 26 and cum != 26:
        # allow deal/tableau split; still must sum
        pass
    if cum != 26:
        raise ValueError(f"waterfall cumulative {cum} != 26")
    return rows


def compare_boundaries(auto_epochs: Sequence[dict], canon_epochs: Sequence[dict]) -> List[dict]:
    out = []
    for a, c in zip(auto_epochs, canon_epochs):
        if a.get("is_deal") or c.get("is_deal"):
            ae, ce = a.get("exit") or {}, c.get("exit") or {}
        else:
            ae, ce = a.get("enter") or {}, c.get("enter") or {}
        out.append(
            {
                "label": a["label"],
                "auto": ae,
                "canon": ce,
                "auto_remaining": (ae or {}).get("remaining_cost"),
                "canon_remaining": (ce or {}).get("remaining_cost"),
            }
        )
    return out
