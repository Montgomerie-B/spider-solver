"""Research-only two-gate preview: Gate 2 is internal; target is Gate 3 / JH.

AH release is an empty column or a face-up rank-2 of any suit (engine
can_move is suit-independent).  SD4 is never expanded.  Full accumulated
MW is the search g.  Exact v0.35 components may be memoised as dead;
structural overgeneralisation is forbidden.
"""

from __future__ import annotations

import heapq
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_state, unpack_state
from spider.simple_deal1_preview import stock_rows
from spider.simple_foundation_horizon import pretty_card, stock_deal_rows
from spider.simple_gate1 import gate1_progress, is_gate2, is_gate3
from spider.simple_gate3 import one_move_gate3
from spider.simple_h9_cut import DIRECT, GOOD_PLAY, JOIN_BREAK, LANDING_SUPPORT, PARK, SD3, annotate_h9_action
from spider.simple_heart_funnel import legal_episode_actions
from spider.simple_progressive_solver import (
    _capture,
    _restore,
    _rss_mb,
    apply_action,
    classify_tier,
    step_cost,
)
from spider.simple_workspace_reachability import empty_column_indices, face_down_count

COST_CEILING = 82
PROBE_DEPTH = 6
GATE1_PROVED_MIN = 70
SD3_EXPECTED = ("2C", "10S", "QD", "KH", "8H", "9C", "3S", "5S", "5D", "4H")
AH_RELEASE_NOW = "AH_RELEASE_NOW"
SD3_AVAILABLE = "SD3_AVAILABLE"
POST_SD3_RELEASE_NOT_IMMEDIATE = "POST_SD3_RELEASE_NOT_IMMEDIATE"
EXACT_DEAD_KNOWN = "EXACT_DEAD_KNOWN"
PROBE_FOUND = "GATE3_FOUND"
PROBE_LIVE = "LIVE_BEYOND_PROBE"
PROBE_DEAD = "EXACT_DEAD"
PROBE_SKIPPED = "SKIPPED_KNOWN_DEAD"


def ah_release_destinations_from_engine(state: SpiderState, src: int, k: int) -> List[dict]:
    """Legal destinations for a specific packet; records empty vs rank-2."""

    out = []
    if k <= 0 or src < 0:
        return out
    run = state.columns[src].face_up[-k:]
    if not run or not SpiderState.is_movable_run(run):
        return out
    head = run[0]
    for dst in range(10):
        if dst == src:
            continue
        if not state.can_move(src, dst, k):
            continue
        top = state.columns[dst].top()
        kind = "empty" if top is None else f"rank_{top.rank}"
        out.append(
            {
                "dst": dst,
                "kind": "empty" if top is None else ("rank_2" if top.rank == 2 else kind),
                "dest_rank": None if top is None else int(top.rank),
                "dest_suit": None if top is None else top.suit,
                "head_rank": int(head.rank),
                "suit_used": False,
            }
        )
    return out


def verify_ah_release_legality() -> dict:
    """Ace (rank 1) lands on empty or any-suit rank 2. Engine ignores suit."""

    from spider.cards import Card
    from spider.engine import Column

    def build(src_up, dst_up):
        cols = []
        for i in range(10):
            if i == 0:
                cols.append(Column([], list(src_up)))
            elif i == 1:
                cols.append(Column([], list(dst_up)))
            else:
                cols.append(Column([], [Card("s", 13)]))
        return SpiderState(cols, [], [])

    ace = [Card("h", 1)]
    onto_empty = build(ace, [])
    onto_2c = build(ace, [Card("c", 2)])
    onto_2s = build(ace, [Card("s", 2)])
    onto_2h = build(ace, [Card("h", 2)])
    onto_3h = build(ace, [Card("h", 3)])
    onto_2_buried = build(ace, [Card("c", 2), Card("d", 13)])
    empty_ok = onto_empty.can_move(0, 1, 1)
    two_any = onto_2c.can_move(0, 1, 1) and onto_2s.can_move(0, 1, 1) and onto_2h.can_move(0, 1, 1)
    not_three = not onto_3h.can_move(0, 1, 1)
    not_buried = not onto_2_buried.can_move(0, 1, 1)
    dests = ah_release_destinations_from_engine(onto_2c, 0, 1)
    kinds = {d["kind"] for d in dests}
    valid = empty_ok and two_any and not_three and not_buried and "rank_2" in kinds
    return {
        "valid": valid,
        "empty_ok": empty_ok,
        "rank2_any_suit": two_any,
        "rank3_rejected": not_three,
        "buried_rank2_rejected": not_buried,
        "suit_independent": True,
        "rationale": (
            "SpiderState.can_move allows a movable run onto an empty column or onto a "
            "face-up card whose rank is exactly one higher than the run head. Suit is "
            "not consulted. A single-card Ace therefore requires an empty or any-suit 2."
        ),
    }


def exposed_rank2_columns(state: SpiderState) -> List[int]:
    return [i for i, col in enumerate(state.columns) if col.top() is not None and col.top().rank == 2]


def sd3_row_cards(state: SpiderState) -> Optional[List[str]]:
    if stock_rows(state) != 3:
        return None
    return [pretty_card(c) for c in state.stock[-10:]]


def verify_sd3_row(state: SpiderState) -> dict:
    row = sd3_row_cards(state)
    names = list(row) if row is not None else None
    ok = names == list(SD3_EXPECTED)
    return {
        "valid": ok,
        "row": names,
        "expected": list(SD3_EXPECTED),
        "col1_card": None if not names else names[0],
        "col2_card": None if not names else names[1],
        "col1_is_2c": bool(names) and names[0] == "2C",
        "col2_is_10s": bool(names) and names[1] == "10S",
        "stock_rows": stock_rows(state),
    }


def sd3_reception_preview(state: SpiderState) -> dict:
    """Actual next-row landings. Not a take/save policy."""

    if stock_rows(state) != 3:
        return {"available": False}
    row = state.stock[-10:]
    names = [pretty_card(c) for c in row]
    target = gate1_progress(state).get("column_0")
    return {
        "available": True,
        "row": names,
        "col1_2c": names[0] == "2C",
        "col2_10s": names[1] == "10S",
        "creates_rank2_on_col1": names[0][0] == "2" if names else False,
        "covers_target_column": target == 1,
        "covers_column_2": True,
        "fills_empties": [i for i, c in enumerate(state.columns) if c.is_empty()],
    }


def ah_immediate_release(state: SpiderState) -> List[dict]:
    hits = one_move_gate3(state)
    annotated = []
    parent = gate1_progress(state)
    col = parent.get("column_0")
    for hit in hits:
        action = hit["action"]
        if action == ["deal"]:
            annotated.append({**hit, "release_kind": "sd3"})
            continue
        src, dst, k = int(action[0]), int(action[1]), int(action[2])
        dests = ah_release_destinations_from_engine(state, src, k)
        kind = next((d["kind"] for d in dests if d["dst"] == dst), "other")
        annotated.append({**hit, "release_kind": kind, "src": src, "dst": dst, "k": k, "target_col": col})
    return annotated


def classify_gate2_state(state: SpiderState, dead_memo: Set[bytes]) -> dict:
    ident = pack_state(state)
    prog = gate1_progress(state)
    empties = list(empty_column_indices(state))
    rank2 = exposed_rank2_columns(state)
    sd3_avail = stock_rows(state) == 3
    ah_hits = ah_immediate_release(state)
    ah_movable = bool(ah_hits) or bool(prog.get("can_move_packet"))
    if ident in dead_memo:
        cls = EXACT_DEAD_KNOWN
    elif ah_hits:
        cls = AH_RELEASE_NOW
    elif sd3_avail:
        cls = SD3_AVAILABLE
    else:
        cls = POST_SD3_RELEASE_NOT_IMMEDIATE
    return {
        "class": cls,
        "ordered_digest": ident.hex(),
        "ident": ident,
        "sd3_available": sd3_avail,
        "sd3_done": not sd3_avail,
        "ah_immediately_movable": bool(ah_hits),
        "ah_packet_movable": bool(prog.get("can_move_packet")),
        "empty_available": bool(empties),
        "empty_count": len(empties),
        "exposed_rank2": bool(rank2),
        "rank2_columns": rank2,
        "fu_blockers": prog.get("fu_blockers"),
        "fd_blockers": prog.get("fd_blockers"),
        "stock_rows": stock_rows(state),
        "immediate_hits": len(ah_hits),
    }


def category_key(rec: dict, probe_status: str, cost: int) -> str:
    return "|".join(
        [
            rec["class"],
            "sd3" if rec["sd3_available"] else "post",
            "ah_now" if rec["ah_immediately_movable"] else "ah_blocked",
            "empty" if rec["empty_available"] else "noempty",
            "r2" if rec["exposed_rank2"] else "nor2",
            probe_status,
            str(int(cost)),
        ]
    )


def load_v035_dead_memo(path: Path) -> Set[bytes]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    dead: Set[bytes] = set()
    for rec in payload.get("states") or []:
        digest = rec.get("ordered_digest")
        if digest:
            dead.add(bytes.fromhex(digest))
    return dead


def nested_gate3_probe(
    state: SpiderState,
    g0: int,
    *,
    dead_memo: Set[bytes],
    max_depth: int = PROBE_DEPTH,
    deadline: float,
    rss_abort_mb: float,
) -> dict:
    """Exact local probe to Gate 3. Dead only on frontier exhaustion."""

    ident0 = pack_state(state)
    if ident0 in dead_memo:
        return {
            "status": PROBE_SKIPPED,
            "class": EXACT_DEAD_KNOWN,
            "found": False,
            "dead": True,
            "live": False,
            "unique": 0,
            "expanded": 0,
            "sd4_expanded": False,
            "reason": "exact v0.35/known dead identity",
        }
    parent_prog = gate1_progress(state)
    if parent_prog.get("fd_blockers") != 1:
        return {"status": "NOT_GATE2", "found": False, "dead": False, "live": False, "unique": 0, "expanded": 0}

    started = time.perf_counter()
    best: Dict[bytes, int] = {ident0: g0}
    heap: List[tuple] = []
    seq = 0
    heapq.heappush(heap, (g0, 0, seq, ident0, tuple()))
    seen_expand: Dict[bytes, int] = {}
    unique = 1
    expanded = 0
    generated = 0
    sd4 = False
    found = None
    live_frontier = False
    visited: Set[bytes] = {ident0}

    while heap:
        if time.perf_counter() >= deadline:
            live_frontier = True
            break
        rss = _rss_mb()
        if rss is not None and rss >= rss_abort_mb:
            live_frontier = True
            break
        g, depth, _, ident, path = heapq.heappop(heap)
        if g != best.get(ident):
            continue
        if seen_expand.get(ident, 10**9) <= g:
            continue
        if depth >= max_depth:
            live_frontier = True
            continue
        seen_expand[ident] = g
        st = unpack_state(ident)
        prog = gate1_progress(st)
        if prog.get("fd_blockers") != 1 or prog.get("face_up"):
            continue
        expanded += 1
        for action in legal_episode_actions(st):
            if action == ("deal",):
                if stock_rows(st) != 3:
                    sd4 = True
                    continue
            cost = step_cost(st, action)
            child_g = g + cost
            cap = _capture(st, action)
            try:
                apply_action(st, action)
                generated += 1
                if stock_rows(st) < 2:
                    sd4 = True
                child_prog = gate1_progress(st)
                child_ident = pack_state(st)
                child_path = path + (action,)
                if is_gate3(prog, child_prog, st):
                    found = {
                        "g": child_g,
                        "depth": depth + 1,
                        "actions": [list(a) if a != ("deal",) else ["deal"] for a in child_path],
                        "ordered_digest": child_ident.hex(),
                        "top_face_up": pretty_card(st.columns[child_prog["column_0"]].face_up[-1]),
                        "fd_blockers": child_prog["fd_blockers"],
                        "h9_face_down": not child_prog.get("face_up"),
                        "stock_rows": stock_rows(st),
                    }
                    break
                if child_prog.get("face_up") or child_prog.get("fd_blockers", 99) == 0:
                    continue
                prev = best.get(child_ident)
                if prev is not None and child_g >= prev:
                    continue
                best[child_ident] = child_g
                visited.add(child_ident)
                if prev is None:
                    unique += 1
                seq += 1
                heapq.heappush(heap, (child_g, depth + 1, seq, child_ident, child_path))
            finally:
                _restore(st, cap)
        if found:
            break

    if found:
        status = PROBE_FOUND
        dead = False
        live = False
    elif live_frontier or heap:
        status = PROBE_LIVE
        dead = False
        live = True
    else:
        status = PROBE_DEAD
        dead = True
        live = False
        dead_memo.update(visited)

    return {
        "status": status,
        "found": bool(found),
        "dead": dead,
        "live": live,
        "hit": found,
        "unique": unique,
        "expanded": expanded,
        "generated": generated,
        "sd4_expanded": sd4,
        "elapsed_s": time.perf_counter() - started,
        "visited": len(visited),
        "exact_dead_added": len(visited) if dead else 0,
    }


def _label_rank(label: str) -> int:
    return {
        DIRECT: 0,
        LANDING_SUPPORT: 1,
        GOOD_PLAY: 2,
        SD3: 2,
        PARK: 3,
        "OTHER": 4,
        JOIN_BREAK: 5,
    }.get(label, 4)


def _outer_priority(state: SpiderState, prog: dict, g: int, depth: int, label: str, seq: int, node: int, origin: int):
    # Lower fd_blockers first so LIVE Gate-2 continuations outrank more pre-Gate-2 wandering.
    fd = int(prog.get("fd_blockers") or 9)
    empties = 0 if any(c.is_empty() for c in state.columns) else 1
    rank2 = 0 if exposed_rank2_columns(state) else 1
    sd3 = 0 if stock_rows(state) == 3 else 1
    can_move = 0 if prog.get("can_move_packet") else 1
    fu = int(prog.get("fu_blockers") or 9)
    preview = sd3_reception_preview(state)
    cover = 1 if preview.get("covers_target_column") else 0
    rank2_gift = 0 if preview.get("col1_2c") else 1
    return (fd, fu, can_move, empties, rank2, sd3, cover, rank2_gift, _label_rank(label), g, depth, seq, node, origin)


@dataclass
class TwoGateResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    cheaper_reopens: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    incumbent: Optional[int] = None
    first_gate3_s: Optional[float] = None
    first_gate3_unique: Optional[int] = None
    first_gate3_g: Optional[int] = None
    sd4_expanded: bool = False
    used_heuristic_prune: bool = False
    cost_ceiling: int = COST_CEILING
    probes: int = 0
    probe_found: int = 0
    probe_live: int = 0
    probe_dead: int = 0
    probe_skipped_known: int = 0
    gate2_encounters: int = 0
    gate2_records: List[dict] = field(default_factory=list)
    witnesses: List[dict] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    known_dead_hits: int = 0
    max_g_seen: int = 0
    gate2_class_all: Dict[str, int] = field(default_factory=dict)
    gate2_probe_all: Dict[str, int] = field(default_factory=dict)
    gate2_pre_sd3_all: int = 0
    gate2_post_sd3_all: int = 0
    gate2_cost_min: Optional[int] = None
    gate2_cost_max: Optional[int] = None


def search_two_gate(
    sources: Sequence[SpiderState],
    origin_paths: Sequence[Sequence[Action]],
    source_g: Sequence[int],
    *,
    dead_memo: Optional[Set[bytes]] = None,
    max_unique: int = 750_000,
    time_limit_s: float = 750.0,
    rss_abort_mb: float = 3 * 1024.0,
    cost_ceiling: int = COST_CEILING,
    harvest_slack: int = 3,
    harvest_limit: int = 256,
    gate2_portfolio_limit: int = 256,
    per_category_cap: int = 32,
    probe_depth: int = PROBE_DEPTH,
) -> TwoGateResult:
    """Gate-1 -> Gate-3 search. Gate 2 is internal. No Gate-2 incumbent+2 prune."""

    started = time.perf_counter()
    deadline = started + time_limit_s
    result = TwoGateResult(cost_ceiling=cost_ceiling)
    memo: Set[bytes] = set(dead_memo or [])
    peak = _rss_mb()
    probed: Set[bytes] = set()
    gate2_store: Dict[str, List[dict]] = {}
    witnesses: Dict[bytes, dict] = {}
    current_incumbent: Optional[int] = None
    ceiling = cost_ceiling

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
    for node, ident in enumerate(ident_of):
        st = unpack_state(ident)
        prog = gate1_progress(st)
        heapq.heappush(heap, _outer_priority(st, prog, g_of[node], 0, GOOD_PLAY, seq, node, origin_of[node]))
        seq += 1

    seen_expand: Dict[bytes, int] = {}

    def keep_gate2(rec: dict) -> None:
        key = rec["category"]
        bucket = gate2_store.setdefault(key, [])
        if any(x["ordered_digest"] == rec["ordered_digest"] for x in bucket):
            return
        if len(bucket) >= per_category_cap:
            return
        total = sum(len(v) for v in gate2_store.values())
        if total >= gate2_portfolio_limit:
            if bucket:
                return
            # New operational category: evict from the largest homogeneous bucket.
            largest_key = max(gate2_store, key=lambda k: len(gate2_store[k]))
            if largest_key == key or len(gate2_store[largest_key]) <= 1:
                return
            gate2_store[largest_key].pop()
        bucket.append(rec)

    def note_gate3(child_ident: bytes, rec: dict) -> None:
        nonlocal current_incumbent, ceiling
        prev = witnesses.get(child_ident)
        if prev is None or rec["g"] < prev["g"]:
            witnesses[child_ident] = rec
        if result.first_gate3_s is None:
            result.first_gate3_s = time.perf_counter() - started
            result.first_gate3_unique = result.unique
            result.first_gate3_g = rec["g"]
            print(
                f"FIRST_GATE3 g={rec['g']} unique={result.unique} t={result.first_gate3_s:.2f}s "
                f"via={rec.get('predecessor_class')}",
                flush=True,
            )
        if current_incumbent is None or rec["g"] < current_incumbent:
            current_incumbent = rec["g"]
            result.incumbent = rec["g"]
            ceiling = min(cost_ceiling, current_incumbent + harvest_slack)
            print(f"INCUMBENT g={current_incumbent} ceiling={ceiling}", flush=True)

    print(
        f"TWO_GATE start unique={result.unique} ceiling={ceiling} known_dead={len(memo)}",
        flush=True,
    )

    while heap:
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        if (result.expanded & 8191) == 0 and result.expanded:
            print(
                f"TWO_GATE exp={result.expanded} unique={result.unique} inc={current_incumbent} "
                f"g2={result.gate2_encounters} probes={result.probes} wit={len(witnesses)} heap={len(heap)}",
                flush=True,
            )
        *_, node, origin = heapq.heappop(heap)
        ident = ident_of[node]
        g = g_of[node]
        depth = depth_of[node]
        if g != best_g.get(ident):
            continue
        if g > ceiling:
            continue
        if seen_expand.get(ident, 10**9) <= g:
            continue
        seen_expand[ident] = g
        state = unpack_state(ident)
        prog = gate1_progress(state)
        fd = int(prog.get("fd_blockers") or 99)
        if fd <= 0 or prog.get("face_up"):
            continue
        actions = legal_episode_actions(state)
        result.expanded += 1
        for action in actions:
            is_sd3 = action == ("deal",)
            if is_sd3:
                if stock_rows(state) != 3:
                    result.sd4_expanded = True
                    continue
            label = annotate_h9_action(state, action, prog)
            cost = step_cost(state, action)
            child_g = g + cost
            result.max_g_seen = max(result.max_g_seen, child_g)
            if child_g > ceiling:
                continue
            cap = _capture(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                if stock_rows(state) < 2:
                    result.sd4_expanded = True
                child_ident = pack_state(state)
                child_depth = depth + 1
                prev = best_g.get(child_ident)
                if prev is not None and child_g >= prev:
                    result.duplicate_skips += 1
                    continue
                if prev is not None:
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
                local = reconstruct(child_node)

                if is_gate3(prog, child_prog, state):
                    rec = {
                        "origin": origin,
                        "g": child_g,
                        "depth": child_depth,
                        "actions": [list(a) if a != ("deal",) else ["deal"] for a in local],
                        "ordered_digest": child_ident.hex(),
                        "fd_blockers": child_prog["fd_blockers"],
                        "h9_face_down": not child_prog.get("face_up"),
                        "top_face_up": pretty_card(state.columns[child_prog["column_0"]].face_up[-1]),
                        "stock_rows": stock_rows(state),
                        "fd": face_down_count(state),
                        "foundations": len(state.foundations),
                        "empties": list(empty_column_indices(state)),
                        "predecessor_class": "OUTER_EXPANSION",
                        "via_probe": False,
                        "sd3_available_at_end": stock_rows(state) == 3,
                    }
                    note_gate3(child_ident, rec)
                    continue

                if is_gate2(prog, child_prog, state) and child_ident not in probed:
                    probed.add(child_ident)
                    result.gate2_encounters += 1
                    g2 = classify_gate2_state(state, memo)
                    if g2["class"] == EXACT_DEAD_KNOWN:
                        result.probe_skipped_known += 1
                        result.known_dead_hits += 1
                        probe = {
                            "status": PROBE_SKIPPED,
                            "found": False,
                            "dead": True,
                            "live": False,
                        }
                    else:
                        result.probes += 1
                        probe = nested_gate3_probe(
                            state,
                            child_g,
                            dead_memo=memo,
                            max_depth=probe_depth,
                            deadline=deadline,
                            rss_abort_mb=rss_abort_mb,
                        )
                        if probe["status"] == PROBE_FOUND:
                            result.probe_found += 1
                        elif probe["status"] == PROBE_LIVE:
                            result.probe_live += 1
                        elif probe["status"] == PROBE_DEAD:
                            result.probe_dead += 1
                        result.sd4_expanded = result.sd4_expanded or bool(probe.get("sd4_expanded"))
                    g2_rec = {
                        **{k: v for k, v in g2.items() if k != "ident"},
                        "g": child_g,
                        "origin": origin,
                        "probe_status": probe.get("status"),
                        "category": category_key(g2, probe.get("status") or "NA", child_g),
                        "actions_to_gate2": [list(a) if a != ("deal",) else ["deal"] for a in local],
                    }
                    keep_gate2(g2_rec)
                    result.category_counts[g2_rec["category"]] = result.category_counts.get(g2_rec["category"], 0) + 1
                    cls = g2["class"]
                    result.gate2_class_all[cls] = result.gate2_class_all.get(cls, 0) + 1
                    pst = probe.get("status") or "NA"
                    result.gate2_probe_all[pst] = result.gate2_probe_all.get(pst, 0) + 1
                    if g2["sd3_available"]:
                        result.gate2_pre_sd3_all += 1
                    else:
                        result.gate2_post_sd3_all += 1
                    result.gate2_cost_min = child_g if result.gate2_cost_min is None else min(result.gate2_cost_min, child_g)
                    result.gate2_cost_max = child_g if result.gate2_cost_max is None else max(result.gate2_cost_max, child_g)
                    if probe.get("found") and probe.get("hit"):
                        hit = probe["hit"]
                        full_local = local + [
                            tuple(a) if a != ["deal"] and a != "deal" else ("deal",)
                            for a in hit["actions"]
                        ]
                        rec = {
                            "origin": origin,
                            "g": hit["g"],
                            "depth": child_depth + hit["depth"],
                            "actions": [list(a) if a != ("deal",) else ["deal"] for a in full_local],
                            "ordered_digest": hit["ordered_digest"],
                            "fd_blockers": 0,
                            "h9_face_down": True,
                            "top_face_up": hit.get("top_face_up"),
                            "stock_rows": hit.get("stock_rows"),
                            "predecessor_class": g2["class"],
                            "predecessor_g": child_g,
                            "via_probe": True,
                            "sd3_available_at_gate2": g2["sd3_available"],
                        }
                        note_gate3(bytes.fromhex(hit["ordered_digest"]), rec)
                        continue
                    if probe.get("dead") or g2["class"] == EXACT_DEAD_KNOWN:
                        continue
                    # LIVE_BEYOND_PROBE or AH_RELEASE_NOW without hit (shouldn't happen):
                    # keep expanding this Gate-2 state in the outer search.
                elif child_prog.get("fd_blockers") == 1 and child_ident in probed:
                    # Already classified; if it was dead we would not be generating a
                    # cheaper reopen into a dead ident often. Allow expansion if not dead.
                    if child_ident in memo:
                        continue

                if child_prog.get("fd_blockers") in (1, 2) and not child_prog.get("face_up"):
                    heapq.heappush(
                        heap,
                        _outer_priority(state, child_prog, child_g, child_depth, label, seq, child_node, origin),
                    )
                    seq += 1
            finally:
                _restore(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort"):
            break

    if not result.stop_reason:
        result.stop_reason = "frontier empty" if not heap else "complete"

    c = current_incumbent
    kept = []
    if c is not None:
        for rec in witnesses.values():
            if rec["g"] <= c + harvest_slack:
                kept.append(rec)
        kept.sort(key=lambda w: (w["g"], w["depth"], w["origin"]))
        kept = kept[:harvest_limit]
    result.witnesses = kept
    result.incumbent = current_incumbent
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    flat = []
    for bucket in gate2_store.values():
        flat.extend(bucket)
    result.gate2_records = flat[:gate2_portfolio_limit]
    return result


def stratify_gate1(state: SpiderState) -> dict:
    prog = gate1_progress(state)
    return {
        "sd3_available": stock_rows(state) == 3,
        "sd3_used": stock_rows(state) < 3,
        "empty_count": len(list(empty_column_indices(state))),
        "exposed_rank2": bool(exposed_rank2_columns(state)),
        "rank2_columns": exposed_rank2_columns(state),
        "fd_blockers": prog.get("fd_blockers"),
        "top_fd": prog.get("top_fd"),
        "stock_rows": stock_rows(state),
    }
