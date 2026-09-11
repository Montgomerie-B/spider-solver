"""Research-only dynamic mandatory cut: first exposure of unique pre-SD4 9H.

v0.31 leftover defects this module avoids:
- dependency is recomputed from the CURRENT expanded state;
- Level 2 excludes JOIN_BREAK, so it is not equivalent to Level 3.

Labels are search guidance.  They are not legality, identity, or proof.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.cards import Card, rank_str
from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.rules import MW_RULES
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card, stock_deal_rows
from spider.simple_heart_funnel import classify_sd3_timing, legal_episode_actions
from spider.simple_progressive_solver import (
    Tier,
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_workspace_reachability import engine_tableau_actions, face_down_count

MANDATORY_RANKS = (12, 11, 10, 9, 7, 3)  # Q, J, 10, 9, 7, 3
DIRECT = "H9_DIRECT"
LANDING_SUPPORT = "H9_LANDING_SUPPORT"
GOOD_PLAY = "GOOD_PLAY"
PARK = "PARK"
JOIN_BREAK = "JOIN_BREAK"
OTHER = "OTHER"
SD3 = "SD3"


def pre_sd4_hearts(state: SpiderState, rank: int) -> List[dict]:
    """Tableau + SD3 occurrences of a Heart rank (material before SD4)."""

    found: List[dict] = []
    for col_i, column in enumerate(state.columns):
        n_down = len(column.face_down)
        n_up = len(column.face_up)
        for d_i, card in enumerate(column.face_down):
            if card.suit != "h" or card.rank != rank:
                continue
            found.append(
                {
                    "zone": "down",
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "down_index": d_i,
                    "face_down_len": n_down,
                    "face_down_blockers_above": n_down - 1 - d_i,
                    "face_down_above": [pretty_card(c) for c in column.face_down[d_i + 1 :]],
                    "face_up_above": [pretty_card(c) for c in column.face_up],
                    "face_up_count": n_up,
                    "face_up": False,
                    "in_sd3": False,
                }
            )
        for u_i, card in enumerate(column.face_up):
            if card.suit != "h" or card.rank != rank:
                continue
            found.append(
                {
                    "zone": "up",
                    "column_0": col_i,
                    "column_1": col_i + 1,
                    "up_index": u_i,
                    "face_up_above": [pretty_card(c) for c in column.face_up[u_i + 1 :]],
                    "face_up": True,
                    "face_down_blockers_above": 0,
                    "in_sd3": False,
                }
            )
    rows = stock_deal_rows(state.stock)
    if rows:
        for col_i, card in enumerate(rows[0]):
            if card.suit == "h" and card.rank == rank:
                found.append(
                    {
                        "zone": "sd3",
                        "column_0": col_i,
                        "column_1": col_i + 1,
                        "face_up": False,
                        "in_sd3": True,
                    }
                )
    return found


def verify_mandatory_h9(state: SpiderState) -> dict:
    nines = pre_sd4_hearts(state, 9)
    jacks = pre_sd4_hearts(state, 11)
    valid = len(nines) == 1 and nines[0]["zone"] == "down" and not nines[0].get("in_sd3")
    h9 = nines[0] if nines else None
    jh = jacks[0] if jacks else None
    jh_before_h9 = False
    if valid and jh and jh.get("zone") == "down" and jh.get("column_0") == h9["column_0"]:
        jh_before_h9 = jh["down_index"] > h9["down_index"]
    proof = (
        "Heart 1 before SD4 needs one 9H. Tableau+SD3 contains exactly one 9H, "
        "currently face-down. Every such route therefore crosses the first state "
        "in which that 9H is face-up. This is a trajectory cut, not a licence to "
        "prune moves that do not immediately expose 9H."
    )
    return {
        "valid": valid,
        "count_pre_sd4": len(nines),
        "h9": h9,
        "jh": jh,
        "jh_must_flip_before_h9": jh_before_h9,
        "proof": proof,
        "reason_invalid": None if valid else "9H is not a unique face-down pre-SD4 copy",
    }


def h9_progress(state: SpiderState) -> dict:
    nines = pre_sd4_hearts(state, 9)
    if not nines:
        return {
            "present": False,
            "face_up": False,
            "fd_blockers": 99,
            "fu_blockers": 99,
            "movable_above": 0,
            "landing_depth": 99,
            "column_0": None,
            "legal_dests": 0,
            "sd3_done": stock_rows(state) < 3,
        }
    rec = nines[0]
    face_up = bool(rec.get("face_up"))
    col = rec.get("column_0")
    fd_b = 0 if face_up else int(rec.get("face_down_blockers_above") or 0)
    fu_b = 0 if face_up else int(rec.get("face_up_count") or len(rec.get("face_up_above") or []))
    movable_above = 0
    dests = 0
    landing_depth = 0 if face_up else 9
    if col is not None and not face_up:
        column = state.columns[col]
        if column.face_up:
            k = 1
            while k < len(column.face_up) and SpiderState.is_movable_run(column.face_up[-k - 1 :]):
                k += 1
            movable_above = 1
            for action in engine_tableau_actions(state)[0]:
                if action[0] == col and action[2] == k:
                    dests += 1
            if dests:
                landing_depth = 0
            else:
                landing_depth = _landing_support_depth(state, col, column.face_up[-k].rank)
        elif fd_b == 0:
            landing_depth = 0
    return {
        "present": True,
        "face_up": face_up,
        "fd_blockers": fd_b,
        "fu_blockers": fu_b,
        "movable_above": movable_above,
        "landing_depth": landing_depth,
        "column_0": col,
        "legal_dests": dests,
        "sd3_done": stock_rows(state) < 3,
        "raw": rec,
    }


def _landing_support_depth(state: SpiderState, blocked_col: int, head_rank: int) -> int:
    """0 = can move now; 1 = a legal move creates dest/empty; else 2 (bounded)."""

    need = head_rank + 1
    empties = [i for i, c in enumerate(state.columns) if c.is_empty()]
    if empties:
        return 1
    actions = engine_tableau_actions(state)[0]
    for action in actions:
        src, dst, k = action
        src_col = state.columns[src]
        dst_col = state.columns[dst]
        uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
        creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dst_col.is_empty()
        if creates_empty:
            return 1
        if uncovers and src_col.face_down[-1].rank == need:
            return 1
        if not dst_col.is_empty() and dst_col.top() is not None:
            pass
        run_head = src_col.face_up[-k]
        if run_head.rank == need:
            return 1
    return 2


def dynamic_blockers(state: SpiderState) -> dict:
    prog = h9_progress(state)
    rec = prog.get("raw") or {}
    col = prog.get("column_0")
    support = []
    if col is not None and not prog["face_up"]:
        column = state.columns[col]
        if column.face_up:
            k = 1
            while k < len(column.face_up) and SpiderState.is_movable_run(column.face_up[-k - 1 :]):
                k += 1
            head = column.face_up[-k]
            dests = []
            for action in engine_tableau_actions(state)[0]:
                if action[0] == col and action[2] == k:
                    dests.append([action[0] + 1, action[1] + 1, action[2]])
            support.append(
                {
                    "packet": [pretty_card(c) for c in column.face_up[-k:]],
                    "need_dest_rank": head.rank + 1,
                    "need_empty": True,
                    "legal_dests": dests,
                    "empty_available": any(c.is_empty() for c in state.columns),
                }
            )
    return {
        "progress": {k: v for k, v in prog.items() if k != "raw"},
        "h9": rec,
        "support": support,
        "prevents": (
            "already face-up"
            if prog["face_up"]
            else f"{prog['fu_blockers']} face-up and {prog['fd_blockers']} face-down cards still cover 9H"
        ),
    }


def annotate_h9_action(state: SpiderState, action, prog: dict) -> str:
    if action == ("deal",):
        return SD3
    src, dst, k = action
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    col = prog.get("column_0")
    dest_empty = dst_col.is_empty()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        head = src_col.face_up[-k]
        join_break = left.suit == head.suit and left.rank == head.rank + 1
    if col is not None and src == col:
        return DIRECT
    if col is not None and not prog.get("face_up"):
        column = state.columns[col]
        if column.face_up:
            pkt_k = 1
            while pkt_k < len(column.face_up) and SpiderState.is_movable_run(column.face_up[-pkt_k - 1 :]):
                pkt_k += 1
            need = column.face_up[-pkt_k].rank + 1
            creates_empty = k == len(src_col.face_up) and not src_col.face_down and not dest_empty
            exposes_need = uncovers and src_col.face_down[-1].rank == need
            places_need = src_col.face_up[-k].rank == need
            if creates_empty or exposes_need or places_need or dest_empty and src_col.face_up[-k].rank == 13:
                return LANDING_SUPPORT
    if join_break:
        return JOIN_BREAK
    tier = classify_tier(state, action)
    if int(tier) == int(Tier.A):
        return GOOD_PLAY
    if dest_empty:
        return PARK
    return OTHER


def allowed_at_level(label: str, tier: int, level: int, is_sd3: bool) -> bool:
    """Genuine widening. Level 2 is NOT full-legal: JOIN_BREAK stays Level 3."""

    if is_sd3:
        return True
    if level >= 3:
        return True
    if level <= 0:
        return label in (DIRECT, LANDING_SUPPORT, GOOD_PLAY, SD3)
    if level == 1:
        return label in (DIRECT, LANDING_SUPPORT, GOOD_PLAY, SD3) or tier <= int(Tier.B)
    if level == 2:
        return label != JOIN_BREAK
    return True


def mandatory_rank_status(state: SpiderState) -> dict:
    out = {}
    for rank in MANDATORY_RANKS:
        locs = pre_sd4_hearts(state, rank)
        label = rank_str(rank)
        if not locs:
            out[label] = {"status": "absent_pre_sd4"}
            continue
        rec = locs[0]
        if rec.get("in_sd3"):
            status = "in_sd3"
        elif rec.get("face_up") and not rec.get("face_up_above"):
            status = "exposed_top"
        elif rec.get("face_up"):
            status = "face_up_buried"
        else:
            status = "face_down"
        out[label] = {
            "status": status,
            "count": len(locs),
            "column_1": rec.get("column_1"),
            "zone": rec.get("zone"),
        }
    return out


@dataclass
class CutResult:
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
    witnesses: List[dict] = field(default_factory=list)
    sd4_expanded: bool = False
    used_heuristic_prune: bool = False
    deal_expanded_as_sd3: bool = False
    all_legal_at_level3: bool = False
    directed: bool = False


def _priority(prog: dict, g: int, depth: int, label: str, tier: int, seq: int, node: int, origin: int):
    # Directed cut: fewer blockers first. g is secondary. Not an optimality proof.
    label_rank = {
        DIRECT: 0,
        LANDING_SUPPORT: 1,
        GOOD_PLAY: 2,
        SD3: 2,
        PARK: 3,
        OTHER: 4,
        JOIN_BREAK: 5,
    }.get(label, 4)
    return (
        int(prog.get("fd_blockers", 9)),
        int(prog.get("fu_blockers", 9)),
        int(prog.get("landing_depth", 9)),
        label_rank,
        int(tier),
        g,
        depth,
        seq,
        node,
        origin,
    )


def search_h9_cut(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    *,
    directed: bool,
    max_unique: int = 1_000_000,
    time_limit_s: float = 900.0,
    rss_abort_mb: float = 2 * 1024.0,
    start_level: int = 0,
    max_level: int = 3,
    incumbent: Optional[int] = None,
    harvest_limit: int = 64,
    cheaper_only: bool = False,
) -> CutResult:
    started = time.perf_counter()
    deadline = started + time_limit_s
    result = CutResult(directed=directed)
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

    for origin, src in enumerate(sources):
        ident = pack_state(src)
        if ident in best_g:
            continue
        best_g[ident] = 0
        ident_of.append(ident)
        parent.append(-1)
        action_of.append(None)
        depth_of.append(0)
        origin_of.append(origin)
        g_of.append(0)
    result.unique = len(best_g)

    for level in range(start_level, max_level + 1):
        if time.perf_counter() >= deadline:
            result.stop_reason = "time limit"
            break
        if note_rss():
            result.stop_reason = "rss abort"
            break
        result.levels_reached.append(level)
        if level >= 3:
            result.all_legal_at_level3 = True
        heap: List[tuple] = []
        seq = 0
        best_node: Dict[bytes, int] = {}
        for i, ident in enumerate(ident_of):
            if best_g.get(ident) == g_of[i]:
                best_node[ident] = i
        for ident, node in best_node.items():
            state = unpack_state(ident)
            prog = h9_progress(state)
            if prog["face_up"]:
                continue
            if directed:
                heapq.heappush(heap, _priority(prog, g_of[node], depth_of[node], GOOD_PLAY, 9, seq, node, origin_of[node]))
            else:
                heapq.heappush(heap, (g_of[node], depth_of[node], seq, node, origin_of[node]))
            seq += 1
        seen_expand: Dict[bytes, int] = {}
        unique_start = result.unique
        levels_left = max_level - level + 1
        remaining_s = deadline - time.perf_counter()
        level_deadline = time.perf_counter() + max(20.0, remaining_s / max(1, levels_left))
        print(
            f"{'PASS_A' if directed else 'PASS_B'} LEVEL {level} unique={result.unique} "
            f"heap={len(heap)} budget_s={level_deadline - time.perf_counter():.0f} inc={current_incumbent}",
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
                g_pop, _d, _s, node, origin = heapq.heappop(heap)
            ident = ident_of[node]
            g = g_of[node]
            depth = depth_of[node]
            if g != best_g.get(ident):
                continue
            if current_incumbent is not None and g >= current_incumbent:
                continue
            if seen_expand.get(ident, 10**9) <= g:
                continue
            seen_expand[ident] = g
            state = unpack_state(ident)
            prog = h9_progress(state)
            if prog["face_up"]:
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
                if current_incumbent is not None and child_g > current_incumbent:
                    continue
                if cheaper_only and current_incumbent is not None and child_g >= current_incumbent:
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
                    child_prog = h9_progress(state)
                    if child_prog["face_up"] and not prog["face_up"]:
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
                            "progress": {k: v for k, v in child_prog.items() if k != "raw"},
                            "mandatory_ranks": mandatory_rank_status(state),
                        }
                        if child_ident not in witnesses or child_g < witnesses[child_ident]["g"]:
                            witnesses[child_ident] = rec
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
        if directed and current_incumbent is not None and len(witnesses) >= min(8, harvest_limit):
            remaining = deadline - time.perf_counter()
            if remaining < 30:
                result.stop_reason = result.stop_reason or "harvested"
                break
        if level == max_level and not result.stop_reason:
            result.stop_reason = "frontier empty" if not heap else "max level"

    ranked = sorted(witnesses.values(), key=lambda w: (w["g"], w["depth"], w["origin"]))
    result.witnesses = ranked[:harvest_limit]
    result.incumbent = current_incumbent
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    if not result.stop_reason:
        result.stop_reason = "complete"
    return result
