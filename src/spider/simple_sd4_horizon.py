"""Research-only SD4 operational-horizon pivot: unlock JH then unique 9H.

SD4 is legal.  SD5 is never expanded.  Gate 4 (first 9H exposure) is terminal.
Predicted four-action macros are engine-tested, not special-cased into legality.
"""

from __future__ import annotations

import heapq
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES, deal_cost
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_gate1 import gate1_progress, is_gate3, is_gate4
from spider.simple_h9_cut import pre_sd4_hearts
from spider.simple_progressive_solver import _capture, _restore, _rss_mb, apply_action, step_cost
from spider.simple_workspace_reachability import empty_column_indices, engine_tableau_actions, face_down_count

EXPECTED_SD4 = ("9D", "JS", "QH", "2D", "4C", "QC", "KC", "8C", "JH", "9S")
MACRO_A = (("deal",), (1, 5, 1), (1, 3, 1), (1, 2, 1))  # JS->QC, AH->2D, JH->QH
MACRO_B = (("deal",), (1, 2, 1), (1, 3, 1), (1, 5, 1))  # JS->QH, AH->2D, JH->QC
MAX_CONTINUATION_DEPTH = 6


def legal_sd4_episode_actions(state: SpiderState) -> List[Action]:
    """Tableau plus SD4.  SD5 (stock_rows==1) is withheld."""

    actions, _ = engine_tableau_actions(state)
    if stock_rows(state) == 2 and state.can_deal(MW_RULES):
        actions.append(("deal",))
    return actions


def sd4_row_cards(state: SpiderState) -> Optional[List[str]]:
    if stock_rows(state) != 2:
        return None
    return [pretty_card(c) for c in state.stock[-10:]]


def verify_sd4_row(state: SpiderState) -> dict:
    names = sd4_row_cards(state)
    ok = names == list(EXPECTED_SD4)
    return {
        "valid": ok,
        "row": names,
        "expected": list(EXPECTED_SD4),
        "c2": None if not names else names[1],
        "c3": None if not names else names[2],
        "c4": None if not names else names[3],
        "c6": None if not names else names[5],
        "c2_is_js": bool(names) and names[1] == "JS",
        "c3_is_qh": bool(names) and names[2] == "QH",
        "c4_is_2d": bool(names) and names[3] == "2D",
        "c6_is_qc": bool(names) and names[5] == "QC",
        "stock_rows": stock_rows(state),
        "mismatch": None if ok else "engine SD4 row differs from predicted orientation",
    }


def jack_onto_any_queen_ok() -> dict:
    from spider.cards import Card
    from spider.engine import Column

    def build(src_up, dst_up):
        cols = [Column([], [Card("s", 13)]) for _ in range(10)]
        cols[0] = Column([], list(src_up))
        cols[1] = Column([], list(dst_up))
        return SpiderState(cols, [], [])

    js = [Card("s", 11)]
    qh = build(js, [Card("h", 12)])
    qc = build(js, [Card("c", 12)])
    qd = build(js, [Card("d", 12)])
    qs = build(js, [Card("s", 12)])
    king = build(js, [Card("h", 13)])
    any_q = qh.can_move(0, 1, 1) and qc.can_move(0, 1, 1) and qd.can_move(0, 1, 1) and qs.can_move(0, 1, 1)
    return {
        "valid": any_q and not king.can_move(0, 1, 1),
        "any_suit_queen": any_q,
        "king_rejected": not king.can_move(0, 1, 1),
    }


def continuation_lb_audit(state: SpiderState) -> dict:
    """From a tableau-dead Gate-2 state, SD4 then JS, AH, JH each cost >= 1."""

    prog = gate1_progress(state)
    col = prog.get("column_0")
    reasons = []
    deal_c = deal_cost()
    if deal_c < 1:
        reasons.append("deal_cost < 1")
    if stock_rows(state) != 2:
        reasons.append("SD4 is not the next row")
    if col is None:
        reasons.append("no target column")
        return {"valid": False, "lb": None, "reasons": reasons}

    after = state.clone()
    apply_action(after, ("deal",))
    target = after.columns[col]
    if not target.face_up or pretty_card(target.face_up[-1]) != "JS":
        reasons.append(f"after SD4 top of target is {pretty_card(target.face_up[-1]) if target.face_up else None}, expected JS")
    if len(target.face_up) < 2 or pretty_card(target.face_up[-2]) != "AH":
        reasons.append("AH is not immediately under JS after SD4")
    run = target.face_up[-2:] if len(target.face_up) >= 2 else []
    if run and SpiderState.is_movable_run(run):
        reasons.append("JS+AH is a movable run, so JS and AH might leave together")
    # One action flips at most one face-down card.
    # JS leave does not flip (AH already up). AH leave flips JH. JH leave flips 9H.
    # Target still has face-down under every uncover, so none of the three tableau
    # moves can be a zero-cost whole-column relocate.
    js_costs = []
    ah_costs = []
    for action in engine_tableau_actions(after)[0]:
        src, dst, k = action
        if src != col:
            continue
        cost = step_cost(after, action)
        if k == 1 and pretty_card(after.columns[src].face_up[-1]) == "JS":
            js_costs.append(cost)
    if not js_costs or min(js_costs) < 1:
        reasons.append(f"JS leave costs {js_costs}")

    # After a legal JS-off, AH is top; its uncover of JH cannot be free.
    js_action = next((a for a in engine_tableau_actions(after)[0] if a[0] == col and a[2] == 1), None)
    if js_action is None:
        reasons.append("no legal JS move")
    else:
        mid = after.clone()
        apply_action(mid, js_action)
        if pretty_card(mid.columns[col].face_up[-1]) != "AH":
            reasons.append("moving JS did not expose AH")
        for action in engine_tableau_actions(mid)[0]:
            src, dst, k = action
            if src == col and k == len(mid.columns[src].face_up):
                ah_costs.append(step_cost(mid, action))
        if not ah_costs or min(ah_costs) < 1:
            reasons.append(f"AH uncover costs {ah_costs}")
        ah_action = next(
            (a for a in engine_tableau_actions(mid)[0] if a[0] == col and a[2] == len(mid.columns[col].face_up)),
            None,
        )
        if ah_action is not None:
            end = mid.clone()
            apply_action(end, ah_action)
            child = gate1_progress(end)
            parent = gate1_progress(mid)
            if not is_gate3(parent, child, end):
                reasons.append("AH leave did not produce Gate 3")
            jh_costs = []
            for action in engine_tableau_actions(end)[0]:
                src, dst, k = action
                if src == col and k == len(end.columns[src].face_up):
                    jh_costs.append(step_cost(end, action))
            if not jh_costs or min(jh_costs) < 1:
                reasons.append(f"JH uncover costs {jh_costs}")

    valid = not reasons
    return {
        "valid": valid,
        "lb": 4 if valid else None,
        "deal_cost": deal_c,
        "js_costs": js_costs,
        "ah_costs": ah_costs,
        "reasons": reasons,
        "rationale": (
            "SD4 always costs 1. It places JS on AH in the still-buried 9H column. "
            "JS+AH is not a movable run, so JS must leave in its own action (cost >= 1). "
            "AH must then leave to flip original JH (cost >= 1; column still has face-down). "
            "JH must then leave to flip unique 9H (cost >= 1). One action flips at most one "
            "face-down card. Therefore continuation to H9 from this exact Gate-2 state is >= 4."
            if valid
            else "Lower bound withdrawn: " + "; ".join(reasons)
        ),
    }


def apply_macro(state: SpiderState, macro: Sequence[Action]) -> dict:
    parent = gate1_progress(state)
    step_costs = []
    gate3 = False
    gate4 = False
    fail = None
    total = 0
    for i, action in enumerate(macro):
        if action == ("deal",):
            legal = stock_rows(state) == 2 and state.can_deal(MW_RULES)
        else:
            src, dst, k = action
            legal = state.can_move(src, dst, k)
        if not legal:
            fail = {"index": i, "action": ["deal"] if action == ("deal",) else list(action)}
            break
        if action == ("deal",) and stock_rows(state) != 2:
            fail = {"index": i, "action": ["deal"], "reason": "not SD4"}
            break
        cost = step_cost(state, action)
        apply_action(state, action)
        total += cost
        step_costs.append(cost)
        child = gate1_progress(state)
        if is_gate3(parent, child, state):
            gate3 = True
        if is_gate4(parent, child, state):
            gate4 = True
        parent = child
    col = gate1_progress(state).get("column_0")
    same_suit = False
    if col is not None:
        c3 = state.columns[2].face_up
        if len(c3) >= 2 and pretty_card(c3[-1]) == "JH" and pretty_card(c3[-2]) == "QH":
            same_suit = True
    return {
        "legal": fail is None,
        "failure": fail,
        "step_costs": step_costs,
        "continuation": total,
        "gate3": gate3,
        "gate4": gate4,
        "h9_face_up": bool(gate1_progress(state).get("face_up")),
        "fd": face_down_count(state),
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "empties": list(empty_column_indices(state)),
        "ordered_digest": pack_state(state).hex() if fail is None else None,
        "face_up_col": [pretty_card(c) for c in state.columns[col].face_up] if col is not None else [],
        "face_down_col": [pretty_card(c) for c in state.columns[col].face_down] if col is not None else [],
        "qh_jh_same_suit": same_suit,
        "c3_top": pretty_card(state.columns[2].face_up[-1]) if state.columns[2].face_up else None,
        "c4_top": pretty_card(state.columns[3].face_up[-1]) if state.columns[3].face_up else None,
        "c6_top": pretty_card(state.columns[5].face_up[-1]) if state.columns[5].face_up else None,
    }


def diamond_2d_telemetry(opening: SpiderState, h9_state: Optional[SpiderState]) -> dict:
    def count_2d(st: SpiderState) -> dict:
        tab = 0
        for col in st.columns:
            tab += sum(1 for c in col.face_down + col.face_up if pretty_card(c) == "2D")
        stock = [pretty_card(c) for c in st.stock]
        rows = []
        remaining = list(st.stock)
        while len(remaining) >= 10:
            rows.append([pretty_card(c) for c in remaining[-10:]])
            remaining = remaining[:-10]
        return {"tableau": tab, "stock": stock.count("2D"), "rows": rows}

    base = count_2d(opening)
    after = None
    ah_on_2d = False
    recoverable = None
    if h9_state is not None:
        after = count_2d(h9_state)
        c4 = h9_state.columns[3].face_up
        ah_on_2d = len(c4) >= 2 and pretty_card(c4[-1]) == "AH" and pretty_card(c4[-2]) == "2D"
        # AH leaves a 2 only onto empty or another 2.
        if ah_on_2d:
            dests = []
            for dst in range(10):
                if dst == 3:
                    continue
                if h9_state.can_move(3, dst, 1):
                    top = h9_state.columns[dst].top()
                    dests.append("empty" if top is None else pretty_card(top))
            recoverable = {"legal_ah_dests": dests, "can_release_now": bool(dests)}
    sd4_2d_unique_pre_sd5 = False
    if stock_rows(opening) >= 2:
        # From a Gate-2 source, SD4 is next; SD5 is the row after.
        pass
    return {
        "opening_2d": base,
        "h9_2d": after,
        "sd4_2d_is_unique_pre_sd5": sd4_2d_unique_pre_sd5,
        "ah_temporarily_on_2d": ah_on_2d,
        "ah_release_from_2d": recoverable,
        "note": "Telemetry only. Diamond foundation is not searched.",
    }


@dataclass
class HorizonResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_h9_s: Optional[float] = None
    first_h9_unique: Optional[int] = None
    first_h9_g: Optional[int] = None
    sd5_expanded: bool = False
    max_depth: int = 0
    witnesses: List[dict] = field(default_factory=list)
    complete_depth: bool = False


def search_h9_from_gate2(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    *,
    max_depth: int = MAX_CONTINUATION_DEPTH,
    max_unique: int = 250_000,
    time_limit_s: float = 300.0,
    rss_abort_mb: float = 1024.0,
    harvest_slack: int = 3,
    harvest_limit: int = 256,
) -> HorizonResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = HorizonResult()
    peak = _rss_mb()
    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    for origin, src in enumerate(sources):
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
    result.unique = len(best_g)

    heap: List[tuple] = []
    seq = 0
    for node in range(len(ident_of)):
        heapq.heappush(heap, (g_of[node], depth_of[node], seq, node))
        seq += 1
    seen_expand: Dict[bytes, int] = {}
    print(f"H9_SEARCH start unique={result.unique} depth<={max_depth}", flush=True)

    while heap:
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        g, depth, _, node = heapq.heappop(heap)
        ident = ident_of[node]
        if g != best_g.get(ident):
            continue
        if seen_expand.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            continue
        seen_expand[ident] = g
        state = unpack_state(ident)
        prog = gate1_progress(state)
        if prog.get("face_up"):
            continue
        result.expanded += 1
        for action in legal_sd4_episode_actions(state):
            if action == ("deal",) and stock_rows(state) != 2:
                result.sd5_expanded = True
                continue
            cost = step_cost(state, action)
            child_g = g + cost
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                if stock_rows(state) < 1:
                    result.sd5_expanded = True
                child_ident = pack_state(state)
                child_depth = depth + 1
                result.max_depth = max(result.max_depth, child_depth)
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
                child_prog = gate1_progress(state)
                if is_gate4(prog, child_prog, state):
                    rec = {
                        "origin": origin_of[node],
                        "g": child_g,
                        "depth": child_depth,
                        "continuation": child_g - source_g[origin_of[node]],
                        "actions": [list(a) if a != ("deal",) else ["deal"] for a in reconstruct(child_node)],
                        "ordered_digest": child_ident.hex(),
                        "h9_face_up": True,
                        "top_face_up": pretty_card(state.columns[child_prog["column_0"]].face_up[-1]),
                        "stock_rows": stock_rows(state),
                    }
                    if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                        witnesses[child_ident] = rec
                    if result.first_h9_s is None:
                        result.first_h9_s = time.perf_counter() - started
                        result.first_h9_unique = result.unique
                        result.first_h9_g = child_g
                        print(
                            f"FIRST_H9 g={child_g} depth={child_depth} unique={result.unique} "
                            f"t={result.first_h9_s:.3f}s",
                            flush=True,
                        )
                    if current_incumbent is None or child_g < current_incumbent:
                        current_incumbent = child_g
                        result.incumbent = child_g
                    continue
                heapq.heappush(heap, (child_g, child_depth, seq, child_node))
                seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break

    if not result.stop_reason:
        result.stop_reason = "frontier empty" if not heap else "complete"
        result.complete_depth = not heap
    c = current_incumbent
    kept = []
    if c is not None:
        for rec in witnesses.values():
            if rec["g"] <= c + harvest_slack:
                kept.append(rec)
        kept.sort(key=lambda w: (w["g"], w["depth"], w["origin"]))
        kept = kept[:harvest_limit]
    result.witnesses = kept
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result
