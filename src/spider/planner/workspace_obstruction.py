"""Diagnostic column-evacuation / workspace-obstruction helpers.

Not a strategy layer. Used only to explain why a state can or cannot
create an empty column. No plan-search integration.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.objective_realizer import RealizationStatus
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_tactics import (
    _expand_ws,
    workspace_quotient_key,
)
from spider.rules import MW_RULES


Action = Tuple


def _card(c) -> str:
    return str(c)


def same_suit_top_run(col) -> int:
    up = col.face_up
    if not up:
        return 0
    n = 1
    for i in range(len(up) - 1, 0, -1):
        if up[i - 1].suit == up[i].suit and up[i - 1].rank == up[i].rank + 1:
            n += 1
        else:
            break
    return n


def visible_run_count(col) -> int:
    """Number of same-suit descending fragments in face-up."""
    up = col.face_up
    if not up:
        return 0
    n = 1
    for i in range(1, len(up)):
        cont = up[i - 1].suit == up[i].suit and up[i - 1].rank == up[i].rank + 1
        if not cont:
            n += 1
    return n


def longest_movable_k(state: SpiderState, src: int) -> int:
    up = state.columns[src].face_up
    best = 0
    for k in range(1, len(up) + 1):
        if state.is_movable_run(up[-k:]):
            best = k
        else:
            break
    return best


def dests_for_k(state: SpiderState, src: int, k: int) -> Tuple[int, ...]:
    if k <= 0:
        return ()
    return tuple(d for d in range(10) if d != src and state.can_move(src, d, k))


@dataclass
class ColumnProfile:
    column: int
    face_down: int
    face_up: int
    same_suit_top_run: int
    visible_runs: int
    movable_k: int
    movable_head: Optional[str]
    dests: Tuple[int, ...]
    dests_nonempty: Tuple[int, ...]
    dests_empty: Tuple[int, ...]
    one_move_empty: bool
    one_move_creates: bool
    moving_reveals: bool
    need_rank: Optional[int]
    visible_need_tops: int
    buried_need: int
    stock_need: int
    shortage: str
    cards_total: int


def profile_column(state: SpiderState, col: int) -> ColumnProfile:
    c = state.columns[col]
    k = longest_movable_k(state, col)
    dests = dests_for_k(state, col, k) if k else ()
    dests_empty = tuple(d for d in dests if state.columns[d].is_empty())
    dests_ne = tuple(d for d in dests if not state.columns[d].is_empty())
    open_full = (not c.face_down) and c.face_up and k == len(c.face_up)
    one_empty = bool(open_full and dests)
    one_create = bool(open_full and dests_ne)
    head = c.face_up[-k] if k else None
    need = (head.rank + 1) if head and head.rank < 13 else None
    vis = 0
    buried = 0
    stock_n = 0
    if need is not None:
        for col2 in state.columns:
            if col2.face_up and col2.face_up[-1].rank == need:
                vis += 1
            buried += sum(1 for x in col2.face_down if x.rank == need)
        stock_n = sum(1 for x in state.stock if x.rank == need)
    if c.is_empty():
        shortage = "already_empty"
    elif head and head.rank == 13 and not dests:
        shortage = "king_needs_empty"
    elif need is not None and vis == 0 and not dests:
        shortage = "no_visible_rank_plus_1_top"
    elif dests_empty and not dests_ne and open_full:
        shortage = "only_empty_dest_relocates"
    elif dests:
        shortage = "none"
    else:
        shortage = "no_legal_dest_for_movable_run"
    return ColumnProfile(
        column=col,
        face_down=len(c.face_down),
        face_up=len(c.face_up),
        same_suit_top_run=same_suit_top_run(c),
        visible_runs=visible_run_count(c),
        movable_k=k,
        movable_head=str(head) if head else None,
        dests=dests,
        dests_nonempty=dests_ne,
        dests_empty=dests_empty,
        one_move_empty=one_empty,
        one_move_creates=one_create,
        moving_reveals=bool(k == len(c.face_up) and c.face_down),
        need_rank=need,
        visible_need_tops=vis,
        buried_need=buried,
        stock_need=stock_n,
        shortage=shortage,
        cards_total=len(c.face_down) + len(c.face_up),
    )


def profile_state(state: SpiderState) -> Tuple[ColumnProfile, ...]:
    return tuple(profile_column(state, i) for i in range(10))


def open_column_facts(state: SpiderState) -> Tuple[int, int, int]:
    """(fully_open, fully_open_nonking, min_fd_among_nonempty).

    ``fully_open`` is a structural count. ``fully_open_nonking`` is the
    narrower latent-workspace count: the whole pile must be one legal movable
    same-suit run whose landing card is not a King.
    """
    fully_open = 0
    fully_open_nonking = 0
    min_fd = None
    for col in state.columns:
        if col.is_empty():
            continue
        fd = len(col.face_down)
        if min_fd is None or fd < min_fd:
            min_fd = fd
        if fd == 0 and col.face_up:
            fully_open += 1
            if state.is_movable_run(col.face_up) and col.face_up[0].rank < 13:
                fully_open_nonking += 1
    return fully_open, fully_open_nonking, (min_fd if min_fd is not None else 0)


def workspace_potential(state: SpiderState) -> Dict[str, float]:
    """Cheap diagnostic: is this tableau geometrically close to an empty?

    Not a plan-search score. Higher = more emptyable-looking.
    """
    profs = profile_state(state)
    n_create = sum(1 for p in profs if p.one_move_creates)
    n_reloc = sum(1 for p in profs if p.one_move_empty and not p.one_move_creates)
    open_profs = [p for p in profs if p.face_down == 0 and p.face_up]
    evac_open = [p for p in open_profs if p.need_rank is not None]
    king_open = [p for p in open_profs if p.need_rank is None]
    open_lens = [p.face_up for p in evac_open]
    shortest = min(open_lens) if open_lens else 99
    dest_hits = sum(1 for p in evac_open if p.dests_nonempty)
    dest_miss = sum(1 for p in evac_open if not p.dests)
    score = (
        20.0 * n_create
        + 10.0 * len(evac_open)
        + 5.0 * dest_hits
        + 3.0 * n_reloc
        + max(0.0, 6.0 - float(min(6, shortest)))
        - 1.0 * dest_miss
        - (4.0 * len(king_open) if empty_count(state) == 0 else 0.0)
        + (3.0 if empty_count(state) > 0 else 0.0)
    )
    return {
        "score": score,
        "one_move_creates": float(n_create),
        "one_move_relocates": float(n_reloc),
        "open_columns": float(len(open_profs)),
        "evac_open": float(len(evac_open)),
        "shortest_open": float(shortest if open_lens else -1),
        "dest_hits": float(dest_hits),
        "dest_miss": float(dest_miss),
        "empty_count": float(empty_count(state)),
    }


@dataclass
class NearGoal:
    min_cards_any_open: int
    min_cards_target: Optional[int]
    cost_at_best: int
    target_top: Optional[str]
    target_need: Optional[int]
    blocker: str
    blocker_detail: str


@dataclass
class EvacSearchResult:
    kind: str  # any_workspace | empty_column
    target_column: Optional[int]
    status: str  # FOUND | EXHAUSTED | RESOURCE_LIMIT
    cost: Optional[int]
    ceiling: int
    nodes: int
    elapsed: float
    actions: Tuple[Action, ...]
    near: NearGoal
    notes: Tuple[str, ...]


def _classify_blocker(st: SpiderState, target: Optional[int]) -> Tuple[str, str]:
    if target is None:
        opens = [
            i
            for i, c in enumerate(st.columns)
            if (not c.face_down) and c.face_up
        ]
        if not opens:
            return "buried_card", "no fully-open nonempty column"
        target = min(opens, key=lambda i: len(st.columns[i].face_up))
    p = profile_column(st, target)
    if p.face_down:
        return "buried_card", f"col {target + 1} still has {p.face_down} face-down"
    if p.face_up == 0:
        return "other", "target already empty"
    if p.shortage == "king_needs_empty":
        return "lack_of_temporary_space", "king/open pile needs an empty to park"
    if p.shortage == "no_visible_rank_plus_1_top":
        return (
            "destination_shortage",
            f"need rank {p.need_rank} top; visible={p.visible_need_tops} "
            f"buried={p.buried_need} stock={p.stock_need}",
        )
    if p.visible_runs > 1 and p.movable_k < p.face_up:
        return (
            "mixed_suit_fragmentation",
            f"visible_runs={p.visible_runs} movable_k={p.movable_k}/{p.face_up}",
        )
    if p.shortage == "only_empty_dest_relocates":
        return "destination_shortage", "only empty dests; relocate does not create"
    if not p.dests:
        return "destination_shortage", "no legal dest for current movable run"
    return "other", p.shortage


def _near_from_state(st: SpiderState, target: Optional[int], cost: int) -> NearGoal:
    open_cards = [
        len(c.face_up)
        for c in st.columns
        if (not c.face_down) and c.face_up
    ]
    min_open = min(open_cards) if open_cards else 99
    tcards = None
    ttop = None
    tneed = None
    if target is not None:
        col = st.columns[target]
        tcards = len(col.face_down) + len(col.face_up)
        if col.face_up:
            ttop = str(col.face_up[-1])
            if col.face_up[0].rank < 13:
                # dest needed for whole remaining pile if open
                tneed = col.face_up[0].rank + 1 if not col.face_down else None
    blk, det = _classify_blocker(st, target)
    return NearGoal(
        min_cards_any_open=min_open,
        min_cards_target=tcards,
        cost_at_best=cost,
        target_top=ttop,
        target_need=tneed,
        blocker=blk,
        blocker_detail=det,
    )


def _goal_any(st: SpiderState, e0: int) -> bool:
    return empty_count(st) > e0


def _goal_col(st: SpiderState, col: int) -> bool:
    return st.columns[col].is_empty()


def search_evacuation(
    start: SpiderState,
    *,
    target_column: Optional[int] = None,
    max_cost: int = 12,
    max_nodes: int = 80000,
    time_limit_s: float = 10.0,
) -> EvacSearchResult:
    """Bounded search to raise empty_count or empty one column.

    Status is FOUND / EXHAUSTED / RESOURCE_LIMIT only.
    """
    t0 = time.time()
    e0 = empty_count(start)
    kind = "empty_column" if target_column is not None else "any_workspace"
    best_near = _near_from_state(start, target_column, 0)
    best_score = (
        best_near.min_cards_target
        if target_column is not None
        else best_near.min_cards_any_open
    )

    start_q = workspace_quotient_key(start)
    seen: Dict = {start_q: 0}
    q: deque = deque()
    q.append((0, start, ()))
    nodes = 0
    exhausted = True
    while q:
        if time.time() - t0 > time_limit_s:
            return EvacSearchResult(
                kind=kind,
                target_column=target_column,
                status="RESOURCE_LIMIT",
                cost=None,
                ceiling=max_cost,
                nodes=nodes,
                elapsed=time.time() - t0,
                actions=(),
                near=best_near,
                notes=("fact: time limit", "fact: resource_limit != miss"),
            )
        if nodes >= max_nodes:
            return EvacSearchResult(
                kind=kind,
                target_column=target_column,
                status="RESOURCE_LIMIT",
                cost=None,
                ceiling=max_cost,
                nodes=nodes,
                elapsed=time.time() - t0,
                actions=(),
                near=best_near,
                notes=("fact: node limit", "fact: resource_limit != miss"),
            )
        cost, st, path = q.popleft()
        nodes += 1
        if cost > max_cost:
            continue
        # near-goal
        ng = _near_from_state(st, target_column, cost)
        score = (
            ng.min_cards_target
            if target_column is not None
            else ng.min_cards_any_open
        )
        if score < best_score or (score == best_score and cost < best_near.cost_at_best):
            best_score = score
            best_near = ng

        if path:
            if target_column is None and _goal_any(st, e0):
                return EvacSearchResult(
                    kind=kind,
                    target_column=None,
                    status="FOUND",
                    cost=cost,
                    ceiling=max_cost,
                    nodes=nodes,
                    elapsed=time.time() - t0,
                    actions=path,
                    near=ng,
                    notes=(f"fact: workspace +1 at cost {cost}",),
                )
            if target_column is not None and _goal_col(st, target_column):
                return EvacSearchResult(
                    kind=kind,
                    target_column=target_column,
                    status="FOUND",
                    cost=cost,
                    ceiling=max_cost,
                    nodes=nodes,
                    elapsed=time.time() - t0,
                    actions=path,
                    near=ng,
                    notes=(f"fact: emptied col {target_column + 1} at cost {cost}",),
                )

        e_now = empty_count(st)
        for action, c, st2 in _expand_ws(st):
            ncost = cost + c
            if ncost > max_cost:
                continue
            # 0-cost cannot create a new empty; still allow if targeting a
            # specific column that might need a park (king onto existing empty).
            if c == 0 and target_column is None and empty_count(st2) <= e_now:
                continue
            key = workspace_quotient_key(st2)
            prev = seen.get(key)
            if prev is not None and prev <= ncost:
                continue
            seen[key] = ncost
            npath = path + (action,)
            if c == 0:
                q.appendleft((ncost, st2, npath))
            else:
                q.append((ncost, st2, npath))
    return EvacSearchResult(
        kind=kind,
        target_column=target_column,
        status="EXHAUSTED",
        cost=None,
        ceiling=max_cost,
        nodes=nodes,
        elapsed=time.time() - t0,
        actions=(),
        near=best_near,
        notes=(
            f"fact: exhausted cost<={max_cost} nodes={nodes}",
            "fact: exhausted != impossible",
        ),
    )


def progressive_search(
    start: SpiderState,
    *,
    target_column: Optional[int] = None,
    schedule: Sequence[Tuple[int, int, float]] = (
        (4, 20000, 5.0),
        (8, 80000, 10.0),
        (12, 150000, 15.0),
        (16, 300000, 20.0),
        (20, 500000, 30.0),
    ),
) -> List[EvacSearchResult]:
    """Run increasing ceilings; stop after FOUND."""
    out: List[EvacSearchResult] = []
    for ceil, nodes, tlim in schedule:
        r = search_evacuation(
            start,
            target_column=target_column,
            max_cost=ceil,
            max_nodes=nodes,
            time_limit_s=tlim,
        )
        out.append(r)
        if r.status == "FOUND":
            break
    return out


def promising_columns(state: SpiderState, k: int = 3) -> Tuple[int, ...]:
    """Fully-open nonempty columns, shortest first (best evacuation candidates).

    If none are fully open, fall back to the shortest remaining columns.
    """
    cands = []
    for i, col in enumerate(state.columns):
        if col.is_empty():
            continue
        if col.face_down:
            continue
        cands.append((len(col.face_up), i))
    if not cands:
        for i, col in enumerate(state.columns):
            if col.is_empty():
                continue
            cands.append((len(col.face_down) + len(col.face_up), i))
    cands.sort()
    return tuple(i for _, i in cands[:k])
