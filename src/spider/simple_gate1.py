"""Research-only Gate 1: first flip of the top face-down blocker (8D) above unique 9H.

Terminal at blockers_above 3 -> 2.  Does not search AH/JH/9H/Heart foundation.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card
from spider.simple_h9_cut import (
    DIRECT,
    GOOD_PLAY,
    JOIN_BREAK,
    LANDING_SUPPORT,
    PARK,
    SD3,
    allowed_at_level,
    annotate_h9_action,
    mandatory_rank_status,
    pre_sd4_hearts,
)
from spider.simple_heart_funnel import classify_sd3_timing, legal_episode_actions
from spider.simple_progressive_solver import (
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

CHAIN_ABOVE_9H = ("JH", "AH", "8D")  # bottom-to-top above 9H


def verify_blocker_chain(state: SpiderState) -> dict:
    nines = pre_sd4_hearts(state, 9)
    if len(nines) != 1 or nines[0].get("zone") != "down":
        return {"valid": False, "reason": "unique face-down 9H not found"}
    h9 = nines[0]
    if h9.get("column_1") != 2:
        return {"valid": False, "reason": f"9H not in column 2 (got {h9.get('column_1')})"}
    above = h9.get("face_down_above") or []
    if above != list(CHAIN_ABOVE_9H):
        return {"valid": False, "reason": f"face-down above 9H is {above}, expected {list(CHAIN_ABOVE_9H)}"}
    if h9.get("face_down_blockers_above") != 3:
        return {"valid": False, "reason": "expected 3 face-down blockers"}
    col = state.columns[h9["column_0"]]
    top_fd = col.face_down[-1] if col.face_down else None
    if top_fd is None or pretty_card(top_fd) != "8D":
        return {"valid": False, "reason": f"top face-down is {pretty_card(top_fd) if top_fd else None}, expected 8D"}
    return {
        "valid": True,
        "h9": h9,
        "column_0": h9["column_0"],
        "column_1": 2,
        "chain_bottom_to_top": list(CHAIN_ABOVE_9H),
        "top_face_down": "8D",
        "flip_sequence": ["8D", "AH", "JH", "9H"],
        "gate1_proof": (
            "Every path that later exposes 9H must first flip the current top face-down "
            "card above it. That card is 8D, which is the 3->2 blockers_above transition."
        ),
    }


def flip_cost_bound_audit(state: SpiderState) -> dict:
    """Admissible LB=1 for Gate 1 iff uncovering a still-buried column always costs >= 1."""

    rules = MW_RULES
    zero_needs_empty_column = bool(rules.zero_cost_requires_emptying_column)
    chain = verify_blocker_chain(state)
    col_i = chain.get("column_0")
    uncover_costs = []
    if col_i is not None:
        column = state.columns[col_i]
        if column.face_up and column.face_down:
            for action in engine_tableau_actions(state)[0]:
                if action[0] == col_i and action[2] == len(column.face_up):
                    uncover_costs.append(step_cost(state, action))
    valid = (
        zero_needs_empty_column
        and all(c >= 1 for c in uncover_costs)
        and (not uncover_costs or min(uncover_costs) >= 1)
    )
    # Whole-column zero-cost requires source_face_down_count == 0. Target column
    # still has face-down cards, so the uncover that flips 8D cannot be free.
    return {
        "valid": valid,
        "lb_to_gate1": 1 if valid else 0,
        "lb_to_h9": 3 if valid else 0,
        "zero_cost_requires_empty_column": zero_needs_empty_column,
        "uncover_costs_from_target_column": uncover_costs,
        "rationale": (
            "Corrected MW zero-cost relocate applies only when the source column becomes "
            "empty and has no remaining face-down cards. The 9H column still has face-down "
            "cards under every Gate-1 uncover, so that uncover costs >= 1. One action flips "
            "at most one face-down card."
            if valid
            else "Bound withdrawn: a zero-cost uncover of the target column is possible."
        ),
    }


def gate1_progress(state: SpiderState) -> dict:
    nines = pre_sd4_hearts(state, 9)
    if not nines or nines[0].get("in_sd3"):
        return {
            "present": False,
            "face_up": True,
            "fd_blockers": 99,
            "fu_blockers": 99,
            "column_0": None,
            "top_fd": None,
            "can_move_packet": False,
            "landing_depth": 99,
            "sd3_done": stock_rows(state) < 3,
        }
    rec = nines[0]
    face_up = bool(rec.get("face_up"))
    col = rec.get("column_0")
    fd_b = 0 if face_up else int(rec.get("face_down_blockers_above") or 0)
    fu_b = 0 if face_up else int(rec.get("face_up_count") or len(rec.get("face_up_above") or []))
    top_fd = None
    can_move = False
    dests = 0
    landing = 0 if face_up or fd_b < 3 else 9
    if col is not None and not face_up:
        column = state.columns[col]
        if column.face_down:
            top_fd = pretty_card(column.face_down[-1])
        if column.face_up:
            k = 1
            while k < len(column.face_up) and SpiderState.is_movable_run(column.face_up[-k - 1 :]):
                k += 1
            for action in engine_tableau_actions(state)[0]:
                if action[0] == col and action[2] == k:
                    dests += 1
            can_move = dests > 0
            if can_move:
                landing = 0
            else:
                need = column.face_up[-k].rank + 1
                landing = 1 if any(c.is_empty() for c in state.columns) else 2
                for action in engine_tableau_actions(state)[0]:
                    src, dst, kk = action
                    sc = state.columns[src]
                    if kk == len(sc.face_up) and not sc.face_down and not state.columns[dst].is_empty():
                        landing = 1
                        break
                    if kk == len(sc.face_up) and sc.face_down and sc.face_down[-1].rank == need:
                        landing = 1
                        break
        elif fd_b >= 1:
            landing = 0
            can_move = True
    return {
        "present": True,
        "face_up": face_up,
        "fd_blockers": fd_b,
        "fu_blockers": fu_b,
        "column_0": col,
        "top_fd": top_fd,
        "can_move_packet": can_move,
        "legal_dests": dests,
        "landing_depth": landing,
        "sd3_done": stock_rows(state) < 3,
    }


def is_gate1(parent: dict, child: dict, child_state: SpiderState) -> bool:
    if parent.get("fd_blockers") != 3 or child.get("fd_blockers") != 2:
        return False
    if child.get("face_up"):
        return False
    col = child.get("column_0")
    if col is None:
        return False
    up = child_state.columns[col].face_up
    if not up:
        return False
    return pretty_card(up[-1]) == "8D"


def is_gate2(parent: dict, child: dict, child_state: SpiderState) -> bool:
    if parent.get("fd_blockers") != 2 or child.get("fd_blockers") != 1:
        return False
    if child.get("face_up"):
        return False
    col = child.get("column_0")
    if col is None:
        return False
    up = child_state.columns[col].face_up
    if not up:
        return False
    return pretty_card(up[-1]) == "AH"


def is_gate3(parent: dict, child: dict, child_state: SpiderState) -> bool:
    if parent.get("fd_blockers") != 1 or child.get("fd_blockers") != 0:
        return False
    if child.get("face_up"):
        return False
    col = child.get("column_0")
    if col is None:
        return False
    up = child_state.columns[col].face_up
    if not up:
        return False
    return pretty_card(up[-1]) == "JH"


def is_gate4(parent: dict, child: dict, child_state: SpiderState) -> bool:
    """First exposure of unique 9H. Parent still has 9H face-down with JH already up."""

    if parent.get("face_up") or not child.get("face_up"):
        return False
    if parent.get("fd_blockers") != 0:
        return False
    col = child.get("column_0")
    if col is None:
        return False
    up = child_state.columns[col].face_up
    if not up:
        return False
    return pretty_card(up[-1]) == "9H"


def _gate_hit(mode: str, parent: dict, child: dict, child_state: SpiderState) -> bool:
    if mode == "gate1":
        return is_gate1(parent, child, child_state)
    if mode == "gate2":
        return is_gate2(parent, child, child_state)
    if mode == "gate3":
        return is_gate3(parent, child, child_state)
    raise ValueError(f"unknown gate mode {mode}")


def _priority(prog: dict, g: int, depth: int, label: str, tier: int, seq: int, node: int, origin: int):
    label_rank = {
        DIRECT: 0,
        LANDING_SUPPORT: 1,
        GOOD_PLAY: 2,
        SD3: 2,
        PARK: 3,
        "OTHER": 4,
        JOIN_BREAK: 5,
    }.get(label, 4)
    can_move = 0 if prog.get("can_move_packet") else 1
    return (
        int(prog.get("fu_blockers", 9)),
        can_move,
        int(prog.get("landing_depth", 9)),
        label_rank,
        int(tier),
        g,
        depth,
        seq,
        node,
        origin,
    )


@dataclass
class Gate1Result:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    cheaper_reopens: int = 0
    zero_cost_moves: int = 0
    max_depth: int = 0
    levels_reached: List[int] = field(default_factory=list)
    per_level: List[dict] = field(default_factory=list)
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_gate1_s: Optional[float] = None
    first_gate1_unique: Optional[int] = None
    first_gate1_g: Optional[int] = None
    first_gate1_depth: Optional[int] = None
    witnesses: List[dict] = field(default_factory=list)
    band_counts: Dict[str, int] = field(default_factory=dict)
    sd4_expanded: bool = False
    used_heuristic_prune: bool = False
    deal_expanded_as_sd3: bool = False
    directed: bool = False


def search_gate1(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    *,
    directed: bool,
    max_unique: int = 500_000,
    time_limit_s: float = 600.0,
    rss_abort_mb: float = 2 * 1024.0,
    start_level: int = 0,
    max_level: int = 3,
    incumbent: Optional[int] = None,
    harvest_slack: int = 2,
    harvest_limit: int = 256,
    lb: int = 0,
    cheaper_only: bool = False,
    source_g: Optional[Sequence[int]] = None,
    mode: str = "gate1",
    harvest_stop_at: Optional[int] = None,
) -> Gate1Result:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = Gate1Result(directed=directed)
    peak = _rss_mb()

    def note_rss() -> bool:
        nonlocal peak
        rss = _rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= rss_abort_mb

    best_g: Dict[bytes, int] = {}
    parent: List[int] = []
    action_of: List[Optional[Action]] = []
    depth_of: List[int] = []
    origin_of: List[int] = []
    g_of: List[int] = []
    ident_of: List[bytes] = []
    witnesses: Dict[bytes, dict] = {}
    current_incumbent = incumbent

    def reconstruct(node: int) -> List[Action]:
        path: List[Action] = []
        while node >= 0 and parent[node] >= 0:
            act = action_of[node]
            if act is not None:
                path.append(act)
            node = parent[node]
        path.reverse()
        return path

    skip_le = {"gate1": 2, "gate2": 1, "gate3": 0}.get(mode, 1)
    for origin, src in enumerate(sources):
        ident = pack_state(src)
        g0 = 0 if source_g is None else int(source_g[origin])
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

    for level in range(start_level, max_level + 1):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        result.levels_reached.append(level)
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            state = unpack_state(ident)
            prog = gate1_progress(state)
            if prog["fd_blockers"] <= skip_le:
                continue
            if directed:
                heapq.heappush(heap, _priority(prog, g_of[node], depth_of[node], GOOD_PLAY, 9, seq, node, origin_of[node]))
            else:
                heapq.heappush(heap, (g_of[node], depth_of[node], seq, node, origin_of[node]))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        remaining_s = deadline - time.perf_counter()
        levels_left = max_level - level + 1
        level_deadline = time.perf_counter() + max(15.0, remaining_s / max(1, levels_left))
        print(
            f"{'PASS_A' if directed else 'PASS_B'} L{level} unique={result.unique} heap={len(heap)} "
            f"budget_s={level_deadline - time.perf_counter():.0f} inc={current_incumbent}",
            flush=True,
        )
        level_exp = level_gen = level_dups = level_reopen = 0
        while heap:
            now = time.perf_counter()
            if now >= deadline:
                result.stop_reason = "time limit"
                break
            if now >= level_deadline:
                break
            if (level_exp & 2047) == 0 and note_rss():
                result.stop_reason = "rss abort"
                break
            if (level_exp & 8191) == 0 and level_exp:
                print(
                    f"{'PASS_A' if directed else 'PASS_B'} L{level} exp={level_exp} unique={result.unique} "
                    f"inc={current_incumbent} wit={len(witnesses)} heap={len(heap)}",
                    flush=True,
                )
            if directed:
                *_, node, origin = heapq.heappop(heap)
            else:
                _g, _d, _s, node, origin = heapq.heappop(heap)
            ident = ident_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident):
                continue
            if cheaper_only and current_incumbent is not None and g + lb > current_incumbent:
                continue
            if (not cheaper_only) and current_incumbent is not None and g > current_incumbent + harvest_slack:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            prog = gate1_progress(state)
            if prog["fd_blockers"] <= skip_le:
                continue
            actions = legal_episode_actions(state)
            level_exp += 1
            result.expanded += 1
            for action in actions:
                is_sd3 = action == ("deal",)
                if is_sd3:
                    if stock_rows(state) != 3:
                        result.sd4_expanded = True
                        continue
                    result.deal_expanded_as_sd3 = True
                label = annotate_h9_action(state, action, prog)
                tier_i = 0 if is_sd3 else int(classify_tier(state, action))
                if directed and not allowed_at_level(label, tier_i, level, is_sd3):
                    continue
                cost = step_cost(state, action)
                if cost == 0:
                    result.zero_cost_moves += 1
                child_g = g + cost
                if cheaper_only and current_incumbent is not None and child_g >= current_incumbent:
                    continue
                if (not cheaper_only) and current_incumbent is not None and child_g > current_incumbent + harvest_slack:
                    continue
                cap = _capture(state, action)
                try:
                    apply_action(state, action)
                    level_gen += 1
                    result.generated += 1
                    if stock_rows(state) < 2:
                        result.sd4_expanded = True
                    child_ident = pack_state(state)
                    child_depth = depth + 1
                    result.max_depth = max(result.max_depth, child_depth)
                    prev = best_g.get(child_ident)
                    if prev is not None and child_g >= prev:
                        level_dups += 1
                        result.duplicate_skips += 1
                        continue
                    if prev is not None:
                        level_reopen += 1
                        result.cheaper_reopens += 1
                    else:
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
                    origin_of.append(origin)
                    g_of.append(child_g)
                    child_prog = gate1_progress(state)
                    if mode == "gate1":
                        hit = is_gate1(prog, child_prog, state)
                    elif mode == "gate2":
                        hit = is_gate2(prog, child_prog, state)
                    elif mode == "gate3":
                        hit = is_gate3(prog, child_prog, state)
                    else:
                        hit = _gate_hit(mode, prog, child_prog, state)
                    if hit:
                        local = reconstruct(child_node)
                        rec = {
                            "origin": origin,
                            "g": child_g,
                            "depth": child_depth,
                            "actions": [list(a) if a != ("deal",) else ["deal"] for a in local],
                            "timing": classify_sd3_timing(local, state),
                            "fd": face_down_count(state),
                            "stock_rows": stock_rows(state),
                            "foundations": len(state.foundations),
                            "empties": [i for i, c in enumerate(state.columns) if c.is_empty()],
                            "ordered_digest": child_ident.hex(),
                            "level": level,
                            "top_face_up": pretty_card(state.columns[child_prog["column_0"]].face_up[-1]),
                            "face_up_col": [pretty_card(c) for c in state.columns[child_prog["column_0"]].face_up],
                            "face_down_col": [pretty_card(c) for c in state.columns[child_prog["column_0"]].face_down],
                            "fd_blockers": child_prog["fd_blockers"],
                            "progress": child_prog,
                            "mandatory_ranks": mandatory_rank_status(state),
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
                        if result.first_gate1_s is None:
                            result.first_gate1_s = time.perf_counter() - started
                            result.first_gate1_unique = result.unique
                            result.first_gate1_g = child_g
                            result.first_gate1_depth = child_depth
                            print(
                                f"FIRST_{mode.upper()} g={child_g} depth={child_depth} unique={result.unique} "
                                f"t={result.first_gate1_s:.2f}s",
                                flush=True,
                            )
                        if current_incumbent is None or child_g < current_incumbent:
                            current_incumbent = child_g
                            result.incumbent = child_g
                        continue
                    if directed:
                        heapq.heappush(
                            heap,
                            _priority(child_prog, child_g, child_depth, label, tier_i, seq, child_node, origin),
                        )
                    else:
                        heapq.heappush(heap, (child_g, child_depth, seq, child_node, origin))
                    seq += 1
                finally:
                    _restore(state, cap)
            if result.stop_reason in ("unique limit", "time limit", "rss abort"):
                break
        result.per_level.append(
            {
                "level": level,
                "expanded": level_exp,
                "generated": level_gen,
                "duplicate_skips": level_dups,
                "cheaper_reopens": level_reopen,
                "unique": result.unique,
                "incumbent": current_incumbent,
                "witnesses": len(witnesses),
                "heap_empty": not heap,
            }
        )
        if result.stop_reason in ("time limit", "rss abort", "unique limit"):
            break
        in_band = 0
        if current_incumbent is not None:
            in_band = sum(1 for rec in witnesses.values() if rec["g"] <= current_incumbent + harvest_slack)
        if harvest_stop_at is not None and in_band >= harvest_stop_at:
            result.stop_reason = result.stop_reason or "harvested"
            break
        if directed and current_incumbent is not None and len(witnesses) >= 32:
            remaining = deadline - time.perf_counter()
            if remaining < 20:
                result.stop_reason = result.stop_reason or "harvested"
                break
        if level == max_level and not result.stop_reason:
            result.stop_reason = "frontier empty" if not heap else "max level"

    c = current_incumbent
    kept = []
    if c is not None:
        for rec in witnesses.values():
            if rec["g"] <= c + harvest_slack:
                kept.append(rec)
        kept.sort(key=lambda w: (w["g"], w["depth"], w["origin"]))
        kept = kept[:harvest_limit]
        bands = {str(c): 0, str(c + 1): 0, str(c + 2): 0}
        for rec in kept:
            key = str(rec["g"])
            if key in bands:
                bands[key] += 1
        result.band_counts = bands
    result.witnesses = kept
    result.incumbent = current_incumbent
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    if not result.stop_reason:
        result.stop_reason = "complete"
    return result
