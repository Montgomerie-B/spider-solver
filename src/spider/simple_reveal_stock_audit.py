"""Reveal/stock coupling diagnostics for the simple progressive solver.

Telemetry only.  Does not order moves, prune, or insert counterfactual
actions into search.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES, MobilityWareRules

SolverAction = Any


def cheap_structure(state: SpiderState) -> Dict[str, int]:
    empties = fu = fd = same = mixed = 0
    for col in state.columns:
        if col.is_empty():
            empties += 1
        fd += len(col.face_down)
        fu += len(col.face_up)
        up = col.face_up
        for index in range(len(up) - 1):
            left, right = up[index], up[index + 1]
            if left.rank == right.rank + 1:
                if left.suit == right.suit:
                    same += 1
                else:
                    mixed += 1
    return {
        "fd": fd,
        "fu": fu,
        "empties": empties,
        "same_suit_joins": same,
        "mixed_joins": mixed,
        "foundations": len(state.foundations),
        "stock_rows": len(state.stock) // 10,
        "legal_moves": len(state.enumerate_moves()),
    }


def pareto_dominates(a: Tuple[int, int, int], b: Tuple[int, int, int]) -> bool:
    """``a`` dominates ``b`` on (fd, stock_rows, foundations)."""

    fd_a, stock_a, fnd_a = a
    fd_b, stock_b, fnd_b = b
    return (
        fd_a <= fd_b
        and stock_a <= stock_b
        and fnd_a >= fnd_b
        and (fd_a < fd_b or stock_a < stock_b or fnd_a > fnd_b)
    )


def counterfactual_deal_now(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Optional[Dict[str, Any]]:
    """Clone-only Deal-now probe.  Does not mutate ``state``."""

    if not state.can_deal(rules=rules):
        return None
    child = state.clone()
    child.deal(rules=rules)
    return {
        "structure": cheap_structure(child),
        "key": pack_state(child),
        "legal": True,
    }


def counterfactual_prep_then_deal(
    state: SpiderState,
    prep: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> Optional[Dict[str, Any]]:
    """Clone-only one-move prep + Deal.  Does not mutate ``state``."""

    from spider.simple_progressive_solver import is_deal

    child = state.clone()
    if is_deal(prep):
        return None
    src, dst, k = prep  # type: ignore[misc]
    try:
        child.move(src, dst, k, rules=rules)
        if not child.can_deal(rules=rules):
            return {"structure": cheap_structure(child), "dealt": False, "prep": prep}
        child.deal(rules=rules)
    except (ValueError, AssertionError):
        return None
    return {
        "structure": cheap_structure(child),
        "key": pack_state(child),
        "dealt": True,
        "prep": prep,
    }


@dataclass
class ParetoPoint:
    fd: int
    stock_rows: int
    foundations: int
    depth: int
    cost: int
    node: int
    path: List[Action]


class RevealStockAudit:
    """Side-channel collector.  Search must not read these fields."""

    def __init__(self) -> None:
        self.pareto: List[ParetoPoint] = []
        self.pareto_log: List[dict] = []
        self.best_reveal: List[dict] = [
            {"deals": d, "fd": None, "path": [], "key": None, "pass": None, "node": None}
            for d in range(6)
        ]
        self.later_dealt: List[dict] = [
            {"deals": d, "fd": None, "path": [], "key": None} for d in range(6)
        ]
        self.pre_deal: List[dict] = [
            {"deals": d, "fd": None, "path": [], "key": None, "ordinal": None}
            for d in range(6)
        ]
        self.post_deal: List[dict] = [
            {"deals": d, "fd": None, "path": [], "key": None, "structure": None}
            for d in range(6)
        ]
        self.deal_traces: List[dict] = []
        self.deal_parent_keys: List[set] = [set() for _ in range(6)]
        self.deal_ordinals: List[int] = []
        self.continuation: List[dict] = []
        self.strong_order: List[Optional[dict]] = [None for _ in range(6)]
        self._frontier: List[Tuple[int, int, int, int]] = []

    def on_expand(
        self,
        *,
        key: bytes,
        fd: int,
        stock_rows: int,
        foundations: int,
        depth: int,
        cost: int,
        dealt: int,
        node: int,
        pass_level: int,
        path: Sequence[Action],
    ) -> None:
        triple = (fd, stock_rows, foundations)
        dominated = False
        kept: List[Tuple[int, int, int, int]] = []
        for item in self._frontier:
            other = (item[0], item[1], item[2])
            if pareto_dominates(other, triple):
                dominated = True
                kept.append(item)
            elif pareto_dominates(triple, other):
                continue
            elif other == triple:
                if depth < item[3]:
                    continue
                kept.append(item)
                dominated = True
            else:
                kept.append(item)
        if not dominated:
            kept.append((fd, stock_rows, foundations, depth))
            point = ParetoPoint(
                fd, stock_rows, foundations, depth, cost, node, list(path)
            )
            self.pareto.append(point)
            self.pareto_log.append(
                {
                    "node": node,
                    "fd": fd,
                    "stock_rows": stock_rows,
                    "foundations": foundations,
                    "depth": depth,
                    "cost": cost,
                }
            )
        self._frontier = kept
        slot = self.best_reveal[dealt]
        if slot["fd"] is None or fd < slot["fd"] or (
            fd == slot["fd"] and depth < (slot.get("depth") or 10**9)
        ):
            slot.update(
                {
                    "fd": fd,
                    "path": list(path),
                    "key": key,
                    "pass": pass_level,
                    "node": node,
                    "depth": depth,
                    "cost": cost,
                    "stock_rows": stock_rows,
                    "foundations": foundations,
                }
            )

    def on_children(
        self,
        *,
        key: bytes,
        dealt: int,
        children: Sequence[SolverAction],
        pass_level: int,
        deal_tier: Optional[int],
        prep_action: Optional[SolverAction],
    ) -> None:
        slot = self.best_reveal[dealt]
        if slot.get("key") != key:
            return
        deal_index = None
        for index, action in enumerate(children):
            if action == ("deal",) or action == "deal":
                deal_index = index
                break
        self.strong_order[dealt] = {
            "n_children": len(children),
            "deal_index": deal_index,
            "deal_in_pass": deal_index is not None,
            "deal_tier": deal_tier,
            "pass": pass_level,
            "prep_action": prep_action,
        }

    def on_deal(
        self,
        *,
        ancestor_frames: Sequence[Any],
        parent_key: bytes,
        parent_path: Sequence[Action],
        parent_struct: Dict[str, int],
        child_struct: Dict[str, int],
        child_key: bytes,
        ordinal: int,
        n_children: int,
        remaining: int,
        pass_level: int,
        child_novel: bool,
        tt_skip: bool,
        prep_followed: bool,
        dealt: Optional[int] = None,
    ) -> None:
        if dealt is None:
            dealt = 0
        dealt = max(0, min(5, int(dealt)))
        self.deal_parent_keys[dealt].add(parent_key)
        self.deal_ordinals.append(ordinal)
        parent_fd = parent_struct["fd"]
        child_fd = child_struct["fd"]
        self.deal_traces.append(
            {
                "dealt": dealt,
                "parent_fd": parent_fd,
                "child_fd": child_fd,
                "delta_fd": child_fd - parent_fd,
                "parent_empties": parent_struct["empties"],
                "child_empties": child_struct["empties"],
                "parent_same": parent_struct["same_suit_joins"],
                "child_same": child_struct["same_suit_joins"],
                "parent_mixed": parent_struct["mixed_joins"],
                "child_mixed": child_struct["mixed_joins"],
                "parent_legal": parent_struct["legal_moves"],
                "child_legal": child_struct["legal_moves"],
                "parent_fu": parent_struct["fu"],
                "child_fu": child_struct["fu"],
                "foundations": child_struct["foundations"],
                "ordinal": ordinal,
                "n_children": n_children,
                "remaining": remaining,
                "pass": pass_level,
                "child_novel": child_novel,
                "tt_skip": tt_skip,
                "prep_followed": prep_followed,
            }
        )
        for anc_dealt, anc_fd, anc_key, anc_index in ancestor_frames:
            if anc_dealt != dealt:
                continue
            slot = self.later_dealt[dealt]
            if slot["fd"] is None or anc_fd < slot["fd"]:
                slot.update(
                    {
                        "fd": anc_fd,
                        "path": list(parent_path[:anc_index]),
                        "key": anc_key,
                    }
                )
        pre = self.pre_deal[dealt]
        if pre["fd"] is None or parent_fd < pre["fd"]:
            pre.update(
                {
                    "fd": parent_fd,
                    "path": list(parent_path),
                    "key": parent_key,
                    "ordinal": ordinal,
                    "empties": parent_struct["empties"],
                    "same": parent_struct["same_suit_joins"],
                }
            )
            post = self.post_deal[dealt]
            post.update(
                {
                    "fd": child_fd,
                    "path": list(parent_path) + [("deal",)],
                    "key": child_key,
                    "structure": dict(child_struct),
                    "novel": child_novel,
                    "tt_skip": tt_skip,
                }
            )

    def on_deal_finished(self, record: dict) -> None:
        self.continuation.append(record)


def summarize_deal_traces(traces: Sequence[dict]) -> dict:
    if not traces:
        return {
            "count": 0,
            "median_ordinal": None,
            "mean_delta_fd": None,
            "tt_skip": 0,
            "prep_followed": 0,
        }
    ordinals = sorted(item["ordinal"] for item in traces)
    mid = ordinals[len(ordinals) // 2]
    return {
        "count": len(traces),
        "median_ordinal": mid,
        "mean_delta_fd": sum(item["delta_fd"] for item in traces) / len(traces),
        "mean_parent_empties": sum(item["parent_empties"] for item in traces) / len(traces),
        "mean_delta_same": sum(item["child_same"] - item["parent_same"] for item in traces)
        / len(traces),
        "tt_skip": sum(1 for item in traces if item["tt_skip"]),
        "prep_followed": sum(1 for item in traces if item["prep_followed"]),
        "pass_counts": _count_by(traces, "pass"),
    }


def _count_by(traces: Sequence[dict], key: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for item in traces:
        label = str(item.get(key))
        out[label] = out.get(label, 0) + 1
    return out


def build_stock_depth_rows(
    audit: RevealStockAudit,
    opening: SpiderState,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> List[dict]:
    rows = []
    for dealt in range(6):
        best = audit.best_reveal[dealt]
        later = audit.later_dealt[dealt]
        pre = audit.pre_deal[dealt]
        post = audit.post_deal[dealt]
        order = audit.strong_order[dealt]
        counter = None
        if best["path"] is not None and best["fd"] is not None:
            counter = run_strong_reveal_counterfactuals(
                opening, best["path"], rules=rules
            )
        lineage_dealt = False
        if best.get("key") is not None and best["key"] in audit.deal_parent_keys[dealt]:
            lineage_dealt = True
        if later.get("key") is not None and best.get("key") is not None:
            if later["key"] == best["key"]:
                lineage_dealt = True
        if best.get("path") and later.get("path") is not None:
            bp = best["path"]
            lp = later["path"]
            if len(lp) >= len(bp) and lp[: len(bp)] == bp:
                lineage_dealt = True
        prep_followed = False
        if counter and counter.get("prep") is not None:
            for trace in audit.deal_traces:
                if trace["dealt"] == dealt and trace["prep_followed"]:
                    prep_followed = True
                    break
        post_exp = None
        post_tt = post.get("tt_skip")
        for rec in audit.continuation:
            if rec.get("dealt") == dealt and rec.get("parent_key") == pre.get("key"):
                post_exp = rec.get("subtree_exp")
                break
        row = {
            "deals_completed": dealt,
            "best_fd": best.get("fd"),
            "best_depth": best.get("depth"),
            "best_pass": best.get("pass"),
            "later_dealt_fd": later.get("fd"),
            "pre_fd": pre.get("fd"),
            "post_fd": post.get("fd"),
            "deal_legal": None if counter is None else counter["deal_legal"],
            "empties": None if counter is None else counter["empties"],
            "deal_tier": None if counter is None else counter["deal_tier"],
            "deal_index_pass3": None if counter is None else counter["deal_index_pass3"],
            "deal_in_pass": None if order is None else order["deal_in_pass"],
            "deal_index": None if order is None else order["deal_index"],
            "n_children": None if order is None else order["n_children"],
            "prep_preferred": None if counter is None else counter["prep"] is not None,
            "prep_then_deal_followed": prep_followed,
            "lineage_dealt": lineage_dealt,
            "post_tt_skip": post_tt,
            "post_expansions": post_exp,
            "deal_now_fd": None
            if not counter or not counter.get("deal_now")
            else counter["deal_now"]["fd"],
            "prep_then_deal_fd": None
            if not counter or not counter.get("prep_then_deal")
            else counter["prep_then_deal"]["fd"],
            "landing_score": None if counter is None else counter["landing_score"],
        }
        row["primary_loss_reason"] = classify_loss_reason(row)
        rows.append(row)
    return rows


def classify_loss_reason(row: dict) -> str:
    """Pick R1–R8 from one stock-depth audit row."""

    if row.get("best_fd") is None:
        return "R8"
    legal = row.get("deal_legal")
    empties = row.get("empties") or 0
    if legal is False and empties > 0:
        return "R2"
    lineage_dealt = row.get("lineage_dealt")
    if legal and not lineage_dealt:
        if row.get("prep_preferred") and not row.get("prep_then_deal_followed"):
            return "R7"
        if row.get("deal_in_pass") is False:
            return "R3"
        if (row.get("deal_index") or 0) > 8:
            return "R3"
        return "R1"
    if lineage_dealt:
        post = row.get("post_fd")
        pre = row.get("pre_fd")
        cont = row.get("post_expansions")
        if row.get("post_tt_skip"):
            return "R6"
        if pre is not None and post is not None and post > pre + 2:
            return "R4"
        if cont is not None and cont < 20:
            return "R5"
        if pre is not None and post is not None and post >= pre:
            return "R4"
        return "R5"
    return "R8"


def run_strong_reveal_counterfactuals(
    opening: SpiderState,
    path: Sequence[Action],
    *,
    rules: MobilityWareRules = MW_RULES,
) -> Dict[str, Any]:
    """Replay a stored path and probe Deal/prep on a clone."""

    from spider.simple_progressive_solver import (
        classify_tier,
        deal_preparation,
        evaluate_deal_landings,
        is_deal,
        ordered_actions,
    )

    before = pack_state(opening)
    state = opening.clone()
    if path:
        replay_actions(state, list(path))
    structure = cheap_structure(state)
    legal = state.can_deal(rules=rules)
    landing = evaluate_deal_landings(state, rules=rules)
    deal_tier = int(classify_tier(state, ("deal",), landing=landing)) if landing else None
    ordered = ordered_actions(state, 3, rules=rules, prep_ply=1, stats=None)
    deal_index = None
    for index, action in enumerate(ordered):
        if is_deal(action):
            deal_index = index
            break
    prep, _land = deal_preparation(state, rules=rules, prep_ply=1, stats=None)
    now = counterfactual_deal_now(state, rules=rules) if legal else None
    prepared = (
        counterfactual_prep_then_deal(state, prep, rules=rules) if prep is not None else None
    )
    after = pack_state(opening)
    assert before == after
    return {
        "structure": structure,
        "deal_legal": legal,
        "landing_score": None if landing is None else landing.score,
        "landing_same_suit": None if landing is None else landing.same_suit,
        "deal_tier": deal_tier,
        "deal_index_pass3": deal_index,
        "n_legal_pass3": len(ordered),
        "prep": None if prep is None else prep,
        "deal_now": None
        if now is None
        else {"fd": now["structure"]["fd"], "empties": now["structure"]["empties"]},
        "prep_then_deal": None
        if prepared is None or not prepared.get("dealt")
        else {
            "fd": prepared["structure"]["fd"],
            "empties": prepared["structure"]["empties"],
        },
        "empties": structure["empties"],
        "opening_unmutated": before == after,
    }
