"""Committed excavation-project search (POC).

From a single state, pick a small portfolio of emptyable columns using
``excavation_closure``, then search each with a *fixed* target: that
column must become empty. Auxiliary dest-prep moves are allowed.
The target is never swapped for a higher-scoring reveal.

Not wired into plan_search. Does not deal. No column-identity constants.
Corrected MobilityWare cost. Resource-limit is not impossibility.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.excavation_closure import (
    DestAvailability,
    ProjectClosure,
    close_all_columns,
    close_column,
    column_hops,
    dest_options,
    locate_all_cards,
)
from spider.rules import MW_RULES


Action = Tuple


class ProjectStatus(str, Enum):
    FOUND = "FOUND"
    EXHAUSTED_WITHIN_BOUND = "EXHAUSTED_WITHIN_BOUND"
    RESOURCE_LIMIT = "RESOURCE_LIMIT"


# Heuristic branch cap — truncated expansion cannot claim exhaustion.
DEFAULT_BRANCH = 18

COST_BOUNDS = (12, 16, 19, 22, 25)


@dataclass(frozen=True)
class ProjectProgress:
    target_fd: int
    target_cards: int
    prereqs_satisfied: int
    prereqs_total: int
    unresolved_depth: int
    next_hop_live: bool
    dest_prep_columns: Tuple[int, ...]


@dataclass
class NearGoal:
    cost: int
    progress: ProjectProgress
    actions: Tuple[Action, ...]


@dataclass
class ProjectSearchResult:
    target: int
    status: ProjectStatus
    cost: Optional[int]
    actions: Tuple[Action, ...]
    nodes: int
    elapsed: float
    max_cost: int
    truncated: bool
    progress_trace: Tuple[ProjectProgress, ...]
    near: Optional[NearGoal]
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class PortfolioEntry:
    column: int
    estimated_cost: int
    emptyable: bool
    dest_prep: Tuple[int, ...]
    reasons: Tuple[str, ...]


def select_portfolio(
    state: SpiderState,
    *,
    max_projects: int = 5,
    cost_slack: int = 4,
) -> Tuple[PortfolioEntry, ...]:
    """SMALL set of this-epoch emptyable projects near the cheapest estimate."""
    closures = close_all_columns(state)
    cands = [
        p
        for p in closures
        if p.emptyable_this_epoch and not state.columns[p.column].is_empty()
    ]
    cands.sort(
        key=lambda p: (p.estimated_total_cost, p.dependency_depth, p.column)
    )
    if not cands:
        return ()
    best = cands[0].estimated_total_cost
    band = [p for p in cands if p.estimated_total_cost <= best + cost_slack]
    picked = band[:max_projects]
    return tuple(
        PortfolioEntry(
            p.column,
            p.estimated_total_cost,
            p.emptyable_this_epoch,
            p.dest_prep_columns,
            p.reasons,
        )
        for p in picked
    )


def _target_cards(state: SpiderState, target: int) -> int:
    col = state.columns[target]
    return len(col.face_down) + len(col.face_up)


def measure_progress(state: SpiderState, target: int) -> ProjectProgress:
    col = state.columns[target]
    if col.is_empty():
        return ProjectProgress(0, 0, 0, 0, 0, True, ())
    cl = close_column(state, target)
    sat = sum(1 for h in cl.hop_closures if h.hard_ready)
    nxt = cl.hop_closures[0].hard_ready if cl.hop_closures else True
    return ProjectProgress(
        target_fd=len(col.face_down),
        target_cards=_target_cards(state, target),
        prereqs_satisfied=sat,
        prereqs_total=len(cl.hop_closures),
        unresolved_depth=cl.dependency_depth,
        next_hop_live=nxt,
        dest_prep_columns=cl.dest_prep_columns,
    )


def _needed_dest_ranks(closure: ProjectClosure) -> Set[int]:
    return {
        h.hop.need_rank
        for h in closure.hop_closures
        if h.hop.need_rank is not None and not h.hard_ready
    }


def _move_exposes_needed(
    state: SpiderState,
    src: int,
    k: int,
    needed: Set[int],
) -> bool:
    col = state.columns[src]
    if k != len(col.face_up) or not col.face_down:
        return False
    revealed = col.face_down[-1]
    return revealed.rank in needed


def _column_holds_rank(state: SpiderState, col: int, rank: int) -> bool:
    pile = state.columns[col]
    return any(c.rank == rank for c in pile.face_down) or any(
        c.rank == rank for c in pile.face_up
    )


def light_causal_priority(
    state: SpiderState,
    src: int,
    dst: int,
    k: int,
    target: int,
) -> int:
    """Cheap causal rank for the inner loop. No closure rebuild."""
    if src == target:
        return 0
    hops = column_hops(state, target)
    if not hops:
        return 12
    needs = [h.need_rank for h in hops if h.need_rank is not None]
    if hops[0].need_rank is None:
        # King: workspace create/use.
        src_col = state.columns[src]
        if k == len(src_col.face_up) and not src_col.face_down and not state.columns[dst].is_empty():
            return 4
        if state.columns[dst].is_empty():
            return 5
    if needs and _column_holds_rank(state, src, needs[0]):
        return 1
    if needs and _move_exposes_needed(state, src, k, {needs[0]}):
        return 1
    if len(needs) > 1 and _column_holds_rank(state, src, needs[1]):
        return 2
    dst_top = state.columns[dst].top()
    if dst_top is not None and needs and dst_top.rank == needs[0]:
        return 3
    return 12


def causal_priority(
    state: SpiderState,
    src: int,
    dst: int,
    k: int,
    *,
    target: int,
    closure: ProjectClosure,
) -> int:
    """Lower is more causal. Ordering only — never a prune."""
    if src == target:
        return 0
    needed = _needed_dest_ranks(closure)
    prep = set(closure.dest_prep_columns)
    if src in prep:
        return 1
    if _move_exposes_needed(state, src, k, needed):
        return 1
    # Prerequisite of a dest-prep column: its own first hop dest.
    if prep and src not in prep:
        locs = locate_all_cards(state)
        for pcol in prep:
            ph = column_hops(state, pcol)
            if not ph:
                continue
            opts = dest_options(
                state, ph[0].need_rank, locs=locs, exclude_column=pcol
            )
            for o in opts:
                if (
                    o.availability
                    in (DestAvailability.FACE_DOWN, DestAvailability.FACE_UP_BURIED)
                    and o.loc.column == src
                ):
                    return 2
    # Consolidation that leaves a needed dest as a top (move onto needed rank).
    dst_top = state.columns[dst].top()
    if dst_top is not None and dst_top.rank in needed:
        return 3
    src_col = state.columns[src]
    if k == len(src_col.face_up) and not src_col.face_down and not state.columns[dst].is_empty():
        # Creating temp workspace.
        if closure.needs_temp_space:
            return 4
        return 6
    if state.columns[dst].is_empty() and closure.needs_temp_space:
        return 5
    return 12


def project_tt_key(state: SpiderState, target: int) -> Tuple:
    """Pin the target column; quotient free open piles elsewhere."""
    t = state.columns[target]
    tkey = (
        tuple((c.suit, c.rank) for c in t.face_down),
        tuple((c.suit, c.rank) for c in t.face_up),
    )
    free: List[Tuple] = []
    fixed: List[Tuple] = []
    n_empty = sum(
        i != target and col.is_empty()
        for i, col in enumerate(state.columns)
    )
    has_free_buffer = n_empty > 0
    for i, col in enumerate(state.columns):
        if i == target:
            continue
        if col.is_empty():
            continue
        fu = tuple((c.suit, c.rank) for c in col.face_up)
        if (
            has_free_buffer
            and not col.face_down
            and state.is_movable_run(col.face_up)
        ):
            free.append(fu)
        else:
            fd = tuple((c.suit, c.rank) for c in col.face_down)
            fixed.append((i, fd, fu))
    return (target, tkey, tuple(sorted(free)), tuple(fixed), n_empty)


def _classify_action(
    src: int, target: int, prep: Sequence[int]
) -> str:
    if src == target:
        return "target"
    if src in prep:
        return "preparation"
    return "auxiliary"


def search_empty_column(
    start: SpiderState,
    target: int,
    *,
    max_cost: int = 19,
    max_nodes: int = 8000,
    time_limit_s: float = 15.0,
    branch_cap: int = DEFAULT_BRANCH,
) -> ProjectSearchResult:
    """Bounded search for emptying ``target``. Never deals."""
    t0 = time.time()
    if start.columns[target].is_empty():
        return ProjectSearchResult(
            target, ProjectStatus.FOUND, 0, (), 0, 0.0, max_cost, False,
            (measure_progress(start, target),), None,
            ("fact: already empty",),
        )
    notes: List[str] = [
        "fact: committed target search",
        "fact: no stock deal",
        f"fact: target col {target + 1}",
    ]
    best: Dict[Tuple, int] = {project_tt_key(start, target): 0}
    q: deque = deque()
    q.append((0, start, (), measure_progress(start, target)))
    nodes = 0
    truncated = False
    near: Optional[NearGoal] = None

    def consider_near(cost: int, prog: ProjectProgress, path: Tuple[Action, ...]) -> None:
        nonlocal near
        if near is None:
            near = NearGoal(cost, prog, path)
            return
        a = (prog.target_cards, prog.target_fd, -prog.prereqs_satisfied, cost)
        b = (
            near.progress.target_cards,
            near.progress.target_fd,
            -near.progress.prereqs_satisfied,
            near.cost,
        )
        if a < b:
            near = NearGoal(cost, prog, path)

    while q:
        if time.time() - t0 > time_limit_s:
            notes.append("fact: time limit")
            notes.append("fact: resource_limit != impossible")
            return ProjectSearchResult(
                target, ProjectStatus.RESOURCE_LIMIT, None, (), nodes,
                time.time() - t0, max_cost, True, (), near, tuple(notes),
            )
        if nodes >= max_nodes:
            notes.append("fact: node limit")
            notes.append("fact: resource_limit != impossible")
            return ProjectSearchResult(
                target, ProjectStatus.RESOURCE_LIMIT, None, (), nodes,
                time.time() - t0, max_cost, True, (), near, tuple(notes),
            )
        cost, st, path, _prog0 = q.popleft()
        nodes += 1
        if cost > max_cost:
            continue
        if st.columns[target].is_empty() and path:
            notes.append(f"fact: found cost={cost} nodes={nodes}")
            trace = _trace(start, path, target)
            return ProjectSearchResult(
                target, ProjectStatus.FOUND, cost, path, nodes,
                time.time() - t0, max_cost, truncated, trace, near, tuple(notes),
            )
        scored: List[Tuple] = []
        for src, dst, k in st.enumerate_moves():
            pri = light_causal_priority(st, src, dst, k, target)
            lifecycle = assess_tableau_move(
                st, (src, dst, k), discover_exit=False
            )
            scored.append((pri, lifecycle.ordering_key(), src, dst, k))
        scored.sort()
        causal = [m for m in scored if m[0] <= 5]
        fallback = [m for m in scored if m[0] > 5]
        picked = causal[: max(8, branch_cap - 4)] + fallback[:4]
        if len(picked) < len(scored):
            truncated = True
        for pri, _lifecycle, src, dst, k in picked:
            st2 = st.clone()
            try:
                c = st2.move(src, dst, k, rules=MW_RULES)
            except Exception:
                continue
            ncost = cost + c
            if ncost > max_cost:
                continue
            key = project_tt_key(st2, target)
            prev = best.get(key)
            if prev is not None and prev <= ncost:
                continue
            best[key] = ncost
            npath = path + ((src, dst, k),)
            # Cheap near-goal: card count only. Full closure is diagnostic.
            cheap = ProjectProgress(
                len(st2.columns[target].face_down),
                _target_cards(st2, target),
                0, 0, 0, False, (),
            )
            consider_near(ncost, cheap, npath)
            if c == 0:
                q.appendleft((ncost, st2, npath, cheap))
            else:
                q.append((ncost, st2, npath, cheap))

    if truncated:
        notes.append("fact: branch cap truncated expansion")
        notes.append("fact: resource_limit != impossible")
        status = ProjectStatus.RESOURCE_LIMIT
    else:
        notes.append(f"fact: exhausted cost<={max_cost} nodes={nodes}")
        notes.append("fact: exhausted != impossible beyond this bound")
        status = ProjectStatus.EXHAUSTED_WITHIN_BOUND
    return ProjectSearchResult(
        target, status, None, (), nodes, time.time() - t0, max_cost,
        truncated, (), near, tuple(notes),
    )


def _trace(
    start: SpiderState, actions: Sequence[Action], target: int
) -> Tuple[ProjectProgress, ...]:
    st = start.clone()
    out = [measure_progress(st, target)]
    for a in actions:
        replay_actions(st, [a])
        out.append(measure_progress(st, target))
    return tuple(out)


def iterative_search(
    start: SpiderState,
    target: int,
    *,
    bounds: Sequence[int] = COST_BOUNDS,
    base_nodes: int = 4000,
    base_time: float = 8.0,
) -> Tuple[ProjectSearchResult, ...]:
    """Raise the paid-cost bound until FOUND or the last bound."""
    results: List[ProjectSearchResult] = []
    for i, bound in enumerate(bounds):
        scale = 1.0 + 0.35 * i
        res = search_empty_column(
            start,
            target,
            max_cost=bound,
            max_nodes=int(base_nodes * scale),
            time_limit_s=base_time * scale,
        )
        results.append(res)
        if res.status == ProjectStatus.FOUND:
            break
    return tuple(results)


def search_portfolio(
    start: SpiderState,
    portfolio: Sequence[PortfolioEntry],
    *,
    bounds: Sequence[int] = COST_BOUNDS,
    base_nodes: int = 4000,
    base_time: float = 8.0,
) -> Dict[int, Tuple[ProjectSearchResult, ...]]:
    """Try every committed project at one bound before raising the bound."""
    remaining = [e.column for e in portfolio]
    out: Dict[int, List[ProjectSearchResult]] = {c: [] for c in remaining}
    for i, bound in enumerate(bounds):
        if not remaining:
            break
        scale = 1.0 + 0.35 * i
        still: List[int] = []
        for col in remaining:
            res = search_empty_column(
                start,
                col,
                max_cost=bound,
                max_nodes=int(base_nodes * scale),
                time_limit_s=base_time * scale,
            )
            out[col].append(res)
            if res.status != ProjectStatus.FOUND:
                still.append(col)
        remaining = still
    return {c: tuple(rs) for c, rs in out.items()}


def classify_actions(
    start: SpiderState,
    actions: Sequence[Action],
    target: int,
) -> Tuple[str, ...]:
    st = start.clone()
    labels: List[str] = []
    for a in actions:
        src, dst, k = a
        cl = close_column(st, target)
        labels.append(_classify_action(src, target, cl.dest_prep_columns))
        replay_actions(st, [a])
    return tuple(labels)


def longest_same_suit(state: SpiderState) -> Tuple[int, int]:
    longest = 0
    mass = 0
    for col in state.columns:
        up = col.face_up
        i = 0
        while i < len(up):
            j = i
            while (
                j + 1 < len(up)
                and up[j + 1].suit == up[j].suit
                and up[j].rank - 1 == up[j + 1].rank
            ):
                j += 1
            ln = j - i + 1
            if ln >= 2:
                longest = max(longest, ln)
                mass += ln
            i = j + 1
    return longest, mass
