"""Generic bounded exact best-first search kernel.

No suit, deal, or Foundation-2 knowledge. Callers supply identity, lane keys,
and an engine-derived terminal predicate.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, unpack_state
from spider.research_actions import (
    apply_action,
    capture_state,
    restore_state,
    rss_mb,
    step_cost,
    tableau_actions,
)

IdentityFn = Callable[[SpiderState], bytes]
LaneKeyFn = Callable[[SpiderState, int], Optional[tuple]]
TerminalFn = Callable[[SpiderState], bool]
ActionOrderFn = Callable[[SpiderState, List[Action]], List[Action]]
ActionsFn = Callable[[SpiderState], List[Action]]


@dataclass
class SearchLimits:
    max_unique: int = 600_000
    time_limit_s: float = 420.0
    rss_abort_mb: float = 2.5 * 1024.0
    cost_ceiling: Optional[int] = None
    harvest_slack: Optional[int] = None


@dataclass
class SearchNode:
    ident: bytes
    store: bytes
    g: int
    origin: int
    parent: int
    action: Optional[Action]


@dataclass
class KernelResult:
    unique: int = 0
    expanded: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    stale_skips: int = 0
    elapsed_s: float = 0.0
    peak_rss_mb: Optional[float] = None
    stop_reason: str = ""
    min_g: Optional[int] = None
    max_g: Optional[int] = None
    min_live_g: Optional[int] = None
    closed_g: Optional[int] = None
    incumbent_g: Optional[int] = None
    lane_pops: Dict[str, int] = field(default_factory=dict)
    lane_exp: Dict[str, int] = field(default_factory=dict)
    lane_stale: Dict[str, int] = field(default_factory=dict)
    terminals: List[dict] = field(default_factory=list)
    nodes: List[SearchNode] = field(default_factory=list)
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None

    def reconstruct(self, node: int) -> List[Action]:
        path: List[Action] = []
        cur = node
        while cur >= 0:
            rec = self.nodes[cur]
            if rec.action is not None:
                path.append(rec.action)
            cur = rec.parent
        path.reverse()
        return path


def reconstruct_path(nodes: Sequence[SearchNode], node: int) -> List[Action]:
    path: List[Action] = []
    cur = node
    while cur >= 0:
        rec = nodes[cur]
        if rec.action is not None:
            path.append(rec.action)
        cur = rec.parent
    path.reverse()
    return path


def run_search(
    roots: Sequence[dict],
    *,
    limits: SearchLimits,
    identity_fn: IdentityFn = pack_post_stock_symmetry_state,
    store_fn: Callable[[SpiderState], bytes] = pack_state,
    unpack_fn: Callable[[bytes], SpiderState] = unpack_state,
    lane_names: Sequence[str] = ("cost",),
    lane_key_fns: Optional[Sequence[LaneKeyFn]] = None,
    lane_keys_fn: Optional[Callable[[SpiderState, int], Dict[str, tuple]]] = None,
    is_terminal: TerminalFn = lambda st: len(st.foundations) >= 8,
    actions_fn: Optional[ActionsFn] = None,
    action_order: Optional[ActionOrderFn] = None,
    on_child: Optional[Callable[[SpiderState, int, int], None]] = None,
    on_progress: Optional[Callable[["KernelResult", SpiderState, int, int], None]] = None,
) -> KernelResult:
    """Exact best-g search. ``roots`` need ordered_digest, symmetry_digest, g.

    ``lane_key_fns[i](state, g) -> tuple | None`` is ordering only. ``None``
    skips that lane for this state (sparse participation). One lane with
    ``lambda st, g: (g,)`` is UCS-like. Multiple lanes round-robin.
    """

    started = time.perf_counter()
    deadline = started + limits.time_limit_s
    names = list(lane_names)
    if lane_keys_fn is None and lane_key_fns is None:
        lane_key_fns = [lambda st, g: (g,)]
        names = ["cost"]
    if lane_keys_fn is None and lane_key_fns is not None and len(lane_key_fns) != len(names):
        raise ValueError("lane_names and lane_key_fns length mismatch")
    result = KernelResult(
        lane_pops={n: 0 for n in names},
        lane_exp={n: 0 for n in names},
        lane_stale={n: 0 for n in names},
    )
    peak = rss_mb()
    ceiling = limits.cost_ceiling
    incumbent: Optional[int] = None
    slack = limits.harvest_slack

    best_g: Dict[bytes, int] = {}
    nodes: List[SearchNode] = []
    result.nodes = nodes
    heaps: Dict[str, list] = {n: [] for n in names}
    seq = 0
    seen_expand: Dict[bytes, int] = {}

    def note_rss() -> bool:
        nonlocal peak
        rss = rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= limits.rss_abort_mb

    def push(node_i: int, state: SpiderState, g: int) -> None:
        nonlocal seq
        if lane_keys_fn is not None:
            keys = lane_keys_fn(state, g)
            for name in names:
                key = keys.get(name)
                if key is None:
                    continue
                heapq.heappush(heaps[name], (*key, seq, node_i))
                seq += 1
            return
        assert lane_key_fns is not None
        for name, keyfn in zip(names, lane_key_fns):
            key = keyfn(state, g)
            if key is None:
                continue
            heapq.heappush(heaps[name], (*key, seq, node_i))
            seq += 1

    order = sorted(range(len(roots)), key=lambda i: (int(roots[i]["g"]), roots[i].get("ordered_digest", "")))
    for origin in order:
        rec = roots[origin]
        store = bytes.fromhex(rec["ordered_digest"])
        st0 = unpack_fn(store)
        ident = identity_fn(st0)
        g0 = int(rec["g"])
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                for i, n in enumerate(nodes):
                    if n.ident == ident:
                        nodes[i] = SearchNode(ident, store, g0, origin, -1, None)
                        break
            continue
        best_g[ident] = g0
        node_i = len(nodes)
        nodes.append(SearchNode(ident, store, g0, origin, -1, None))
        if ceiling is None or g0 <= ceiling:
            push(node_i, st0, g0)
        result.min_g = g0 if result.min_g is None else min(result.min_g, g0)
        result.max_g = g0 if result.max_g is None else max(result.max_g, g0)
        result.unique = len(best_g)
        if on_progress is not None:
            on_progress(result, st0, g0, node_i)
        if on_child is not None:
            on_child(st0, g0, node_i)

    lane_i = 0
    empty_streak = 0
    while empty_streak < len(names):
        now = time.perf_counter()
        if now >= deadline:
            result.stop_reason = "time limit"
            break
        if (result.expanded & 2047) == 0 and note_rss():
            result.stop_reason = "rss abort"
            break
        name = names[lane_i % len(names)]
        lane_i += 1
        heap = heaps[name]
        if not heap:
            empty_streak += 1
            continue
        result.lane_pops[name] += 1
        rec_t = heapq.heappop(heap)
        node_i = rec_t[-1]
        node = nodes[node_i]
        g = node.g
        if g != best_g.get(node.ident) or (ceiling is not None and g > ceiling):
            result.stale_skips += 1
            result.lane_stale[name] += 1
            empty_streak = 0
            continue
        if seen_expand.get(node.ident, 10**9) <= g:
            result.stale_skips += 1
            result.lane_stale[name] += 1
            empty_streak = 0
            continue
        empty_streak = 0
        seen_expand[node.ident] = g
        state = unpack_fn(node.store)
        if is_terminal(state):
            continue
        actions = (actions_fn or tableau_actions)(state)
        if action_order is not None:
            actions = action_order(state, actions)
        result.expanded += 1
        result.lane_exp[name] += 1
        for action in actions:
            cost = step_cost(state, action)
            child_g = g + cost
            if ceiling is not None and child_g > ceiling:
                continue
            cap = capture_state(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                child_store = store_fn(state)
                child_ident = identity_fn(state)
                prev = best_g.get(child_ident)
                if prev is not None and child_g >= prev:
                    result.duplicate_skips += 1
                    continue
                if prev is None:
                    result.unique += 1
                if result.unique >= limits.max_unique:
                    result.stop_reason = "unique limit"
                    break
                best_g[child_ident] = child_g
                child_i = len(nodes)
                nodes.append(
                    SearchNode(child_ident, child_store, child_g, node.origin, node_i, action)
                )
                result.min_g = child_g if result.min_g is None else min(result.min_g, child_g)
                result.max_g = child_g if result.max_g is None else max(result.max_g, child_g)
                if on_progress is not None:
                    on_progress(result, state, child_g, child_i)
                if on_child is not None:
                    on_child(state, child_g, child_i)
                if is_terminal(state):
                    result.terminals.append(
                        {
                            "node": child_i,
                            "g": child_g,
                            "origin": node.origin,
                            "ident": child_ident.hex(),
                            "store": child_store.hex(),
                            "action": action,
                        }
                    )
                    if result.first_s is None:
                        result.first_s = time.perf_counter() - started
                        result.first_unique = result.unique
                        result.first_g = child_g
                    if incumbent is None or child_g < incumbent:
                        incumbent = child_g
                        result.incumbent_g = child_g
                        if slack is not None and ceiling is not None:
                            ceiling = min(ceiling, incumbent + slack)
                    continue
                push(child_i, state, child_g)
            finally:
                restore_state(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort", "abort"):
            break
        if incumbent is not None and slack is not None:
            live = []
            for n in names:
                if heaps[n]:
                    live.append(nodes[heaps[n][0][-1]].g)
            if live and min(live) > incumbent + slack:
                result.stop_reason = "harvested"
                break
    if not result.stop_reason:
        result.stop_reason = "complete"
    live_g = [nodes[heaps[n][0][-1]].g for n in names if heaps[n]]
    if live_g:
        result.min_live_g = min(live_g)
        result.closed_g = min(live_g) - 1
    elif incumbent is not None and slack is not None:
        result.closed_g = incumbent + slack
    else:
        result.closed_g = ceiling
    result.nodes = nodes
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    return result
