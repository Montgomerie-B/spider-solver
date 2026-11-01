"""Generic bounded exact best-first search kernel.

No suit, deal, or Foundation-2 knowledge. Callers supply identity, lane keys,
and an engine-derived terminal predicate.
"""

from __future__ import annotations

import array
import heapq
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action
from spider.packed_heap import SEQ_MASK, pack_lane_key
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
    # None preserves the historical unbounded-depth behaviour.
    max_depth: Optional[int] = None
    # None keeps the historical proof rule: g + h is compared with cost_ceiling,
    # including harvest tightening. A separate value prunes only on that proof
    # ceiling and does not change the paid-move cap.
    proof_ceiling: Optional[int] = None


@dataclass
class SearchNode:
    ident: bytes
    store: bytes
    g: int
    origin: int
    parent: int
    action: Optional[Action]
    depth: int = 0


@dataclass(slots=True)
class CompactSearchNode:
    """Same fields as ``SearchNode`` without a per-node ``__dict__``."""

    ident: bytes
    store: bytes
    g: int
    origin: int
    parent: int
    action: Optional[Action]
    depth: int = 0


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
    # Heap sizes at stop. Telemetry only. It does not change admission.
    lane_remaining: Dict[str, int] = field(default_factory=dict)
    terminals: List[dict] = field(default_factory=list)
    nodes: List[SearchNode] = field(default_factory=list)
    first_s: Optional[float] = None
    first_unique: Optional[int] = None
    first_g: Optional[int] = None
    # Proof rejections. ``lower_bound_prunes`` counts every candidate event,
    # including a repeated arrival of an identity that was never retained.
    # ``proof_prune_identities`` counts each such identity once. An identity
    # can be rejected at a high ``g`` and still be retained if a later
    # cheaper arrival passes. ``proof_prune_unretained`` is the subset that
    # is not in the retained best-g map when the search stops.
    lower_bound_prunes: int = 0
    proof_prune_identities: int = 0
    proof_prune_unretained: int = 0
    lower_bound_calls: int = 0
    lower_bound_s: float = 0.0
    min_h: Optional[int] = None
    max_h: Optional[int] = None
    min_f: Optional[int] = None
    prunes_by_F: Dict[int, int] = field(default_factory=dict)
    depth_skips: int = 0
    hit_depth_limit: bool = False
    # Children skipped because their corrected cost already exceeds the ceiling.
    # This is the safe incumbent prune. It is not a lower-bound prune.
    ceiling_prunes: int = 0
    # Legal actions whose corrected step cost is zero, counted when considered.
    zero_cost_actions: int = 0
    expanded_by_g: Dict[int, int] = field(default_factory=dict)
    generated_by_g: Dict[int, int] = field(default_factory=dict)

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
    origin_lane_keys_fn: Optional[Callable[[SpiderState, int, int], Dict[str, Optional[tuple]]]] = None,
    is_terminal: TerminalFn = lambda st: len(st.foundations) >= 8,
    actions_fn: Optional[ActionsFn] = None,
    action_order: Optional[ActionOrderFn] = None,
    on_child: Optional[Callable[[SpiderState, int, int], None]] = None,
    on_progress: Optional[Callable[["KernelResult", SpiderState, int, int], None]] = None,
    on_expand: Optional[Callable[[SpiderState, int, int], None]] = None,
    lower_bound_fn: Optional[Callable[[SpiderState, int], int]] = None,
    stop_on_first_terminal: bool = False,
    diagnostics: Optional[dict] = None,
    representation: str = "reference",
    ceiling_box: Optional[list] = None,
) -> KernelResult:
    """Exact best-g search. ``roots`` need ordered_digest, symmetry_digest, g.

    ``lane_key_fns[i](state, g) -> tuple | None`` is ordering only. ``None``
    skips that lane for this state (sparse participation). One lane with
    ``lambda st, g: (g,)`` is UCS-like. Multiple lanes round-robin.

    ``origin_lane_keys_fn(state, g, origin)`` is opt-in. ``origin`` is
    ``nodes[node_i].origin``. When the hook is omitted, lane selection is
    the existing one. Best-g, proof pruning, and one expansion per identity
    at a given g stay shared either way.

    ``limits.proof_ceiling`` defaults to None. Proof pruning then uses
    ``cost_ceiling``, as before. When it is set, ``g + h > proof_ceiling``
    is the proof rule and ``cost_ceiling`` remains the paid-move cap.
    Equality with the proof ceiling stays eligible.

    ``on_expand`` is optional telemetry. It runs after a node is counted as
    expanded and does not change admission, order, or pruning.

    ``diagnostics`` is optional. When a dict is passed, the kernel stores
    references to the retained maps and heaps after the search stops. It
    does not change admission, order, or pruning. The default is None.

    ``representation`` defaults to ``reference``. ``compact`` keeps the same
    admission, proof, and round-robin rules. It stores a slots node, shares
    an identity with its ordered pack when the bytes are equal, and packs
    each heap key plus the tie sequence into one integer. Stale heap entries
    are still popped, so a lane's turn is not skipped. An out-of-range key
    raises instead of changing the order.
    """

    if representation not in {"reference", "compact"}:
        raise ValueError(f"unknown representation {representation!r}")
    compact = representation == "compact"
    node_cls = CompactSearchNode if compact else SearchNode
    entry_nodes = array.array("I") if compact else None
    started = time.perf_counter()
    deadline = started + limits.time_limit_s
    names = list(lane_names)
    if origin_lane_keys_fn is None and lane_keys_fn is None and lane_key_fns is None:
        lane_key_fns = [lambda st, g: (g,)]
        names = ["cost"]
    if (
        origin_lane_keys_fn is None
        and lane_keys_fn is None
        and lane_key_fns is not None
        and len(lane_key_fns) != len(names)
    ):
        raise ValueError("lane_names and lane_key_fns length mismatch")
    result = KernelResult(
        lane_pops={n: 0 for n in names},
        lane_exp={n: 0 for n in names},
        lane_stale={n: 0 for n in names},
    )
    peak = rss_mb()
    if ceiling_box is None:
        paid_box = [limits.cost_ceiling]
    else:
        if len(ceiling_box) != 1 or ceiling_box[0] != limits.cost_ceiling:
            raise ValueError("ceiling_box holds the paid ceiling")
        paid_box = ceiling_box
    # Paid cap and proof cap are the same object unless the caller splits them.
    # A caller that keeps paid_box can lower the ceiling after a verified win.
    proof_box = [limits.proof_ceiling] if limits.proof_ceiling is not None else paid_box
    incumbent: Optional[int] = None
    slack = limits.harvest_slack

    best_g: Dict[bytes, int] = {}
    nodes: List[SearchNode] = []
    result.nodes = nodes
    # Telemetry only. This set must not block a later cheaper arrival.
    pruned_identities: set = set()
    heaps: Dict[str, list] = {n: [] for n in names}
    seq = 0
    seen_expand: Dict[bytes, int] = {}

    def note_rss() -> bool:
        nonlocal peak
        rss = rss_mb()
        if rss is not None and (peak is None or rss > peak):
            peak = rss
        return rss is not None and rss >= limits.rss_abort_mb

    def bound_h(state: SpiderState, g: int) -> int:
        if lower_bound_fn is None:
            return 0
        t0 = time.perf_counter()
        h = int(lower_bound_fn(state, g) or 0)
        result.lower_bound_s += time.perf_counter() - t0
        result.lower_bound_calls += 1
        result.min_h = h if result.min_h is None else min(result.min_h, h)
        result.max_h = h if result.max_h is None else max(result.max_h, h)
        f = int(g) + h
        result.min_f = f if result.min_f is None else min(result.min_f, f)
        return h

    def proof_dead(state: SpiderState, g: int) -> bool:
        proof_limit = proof_box[0]
        if lower_bound_fn is None or proof_limit is None:
            return False
        h = bound_h(state, g)
        if int(g) + h > int(proof_limit):
            result.lower_bound_prunes += 1
            n_f = len(state.foundations)
            result.prunes_by_F[n_f] = result.prunes_by_F.get(n_f, 0) + 1
            return True
        return False

    def remember(name: str, key, node_i: int) -> None:
        nonlocal seq
        if key is None:
            return
        if compact:
            assert entry_nodes is not None
            ticket = len(entry_nodes)
            entry_nodes.append(node_i)
            heapq.heappush(heaps[name], pack_lane_key(name, key, ticket))
            return
        heapq.heappush(heaps[name], (*key, seq, node_i))
        seq += 1

    def node_index(entry) -> int:
        if compact:
            assert entry_nodes is not None
            return int(entry_nodes[int(entry) & SEQ_MASK])
        return int(entry[-1])

    def push(node_i: int, state: SpiderState, g: int) -> None:
        if origin_lane_keys_fn is not None:
            keys = origin_lane_keys_fn(state, g, int(nodes[node_i].origin)) or {}
            for name in names:
                remember(name, keys.get(name), node_i)
            return
        if lane_keys_fn is not None:
            keys = lane_keys_fn(state, g)
            for name in names:
                remember(name, keys.get(name), node_i)
            return
        assert lane_key_fns is not None
        for name, keyfn in zip(names, lane_key_fns):
            remember(name, keyfn(state, g), node_i)

    order = sorted(range(len(roots)), key=lambda i: (int(roots[i]["g"]), roots[i].get("ordered_digest", "")))
    for origin in order:
        rec = roots[origin]
        store = bytes.fromhex(rec["ordered_digest"])
        st0 = unpack_fn(store)
        ident = identity_fn(st0)
        if compact and ident == store:
            ident = store
        g0 = int(rec["g"])
        if ident in best_g:
            if g0 < best_g[ident]:
                best_g[ident] = g0
                for i, n in enumerate(nodes):
                    if n.ident == ident:
                        nodes[i] = node_cls(ident, store, g0, origin, -1, None)
                        break
            continue
        best_g[ident] = g0
        node_i = len(nodes)
        nodes.append(node_cls(ident, store, g0, origin, -1, None))
        if paid_box[0] is None or g0 <= paid_box[0]:
            if not proof_dead(st0, g0):
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
        node_i = node_index(rec_t)
        node = nodes[node_i]
        g = node.g
        if g != best_g.get(node.ident) or (paid_box[0] is not None and g > paid_box[0]):
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
        if limits.max_depth is not None and node.depth >= int(limits.max_depth):
            result.depth_skips += 1
            result.hit_depth_limit = True
            empty_streak = 0
            continue
        state = unpack_fn(node.store)
        if is_terminal(state):
            continue
        actions = (actions_fn or tableau_actions)(state)
        if action_order is not None:
            actions = action_order(state, actions)
        result.expanded += 1
        result.lane_exp[name] += 1
        result.expanded_by_g[g] = result.expanded_by_g.get(g, 0) + 1
        if on_expand is not None:
            on_expand(state, g, node_i)
        for action in actions:
            cost = step_cost(state, action)
            if cost == 0:
                result.zero_cost_actions += 1
            child_g = g + cost
            if paid_box[0] is not None and child_g > paid_box[0]:
                result.ceiling_prunes += 1
                continue
            cap = capture_state(state, action)
            try:
                apply_action(state, action)
                result.generated += 1
                result.generated_by_g[child_g] = result.generated_by_g.get(child_g, 0) + 1
                child_store = store_fn(state)
                child_ident = identity_fn(state)
                if compact and child_ident == child_store:
                    child_ident = child_store
                prev = best_g.get(child_ident)
                if prev is not None and child_g >= prev:
                    result.duplicate_skips += 1
                    continue
                # Admissible rejection happens before a unique slot, best-g
                # entry, node, or heap entry exists. Equality g+h == ceiling
                # stays eligible. A rejected arrival is not remembered as a
                # dominated state, so a later cheaper g can still be stored.
                if proof_dead(state, child_g):
                    if child_ident not in pruned_identities:
                        pruned_identities.add(child_ident)
                        result.proof_prune_identities += 1
                    continue
                # max_unique is the number of distinct identities admitted.
                # The identity that fills the cap is stored and terminal-checked.
                # The previous code counted that child and dropped it first.
                new_identity = prev is None
                if new_identity and result.unique >= limits.max_unique:
                    result.stop_reason = "unique limit"
                    break
                if new_identity:
                    result.unique += 1
                best_g[child_ident] = child_g
                child_i = len(nodes)
                nodes.append(
                    node_cls(
                        child_ident,
                        child_store,
                        child_g,
                        node.origin,
                        node_i,
                        action,
                        node.depth + 1,
                    )
                )
                result.min_g = child_g if result.min_g is None else min(result.min_g, child_g)
                result.max_g = child_g if result.max_g is None else max(result.max_g, child_g)
                if on_progress is not None:
                    on_progress(result, state, child_g, child_i)
                if on_child is not None:
                    on_child(state, child_g, child_i)
                admitted_last = new_identity and result.unique >= limits.max_unique
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
                        if slack is not None and paid_box[0] is not None:
                            paid_box[0] = min(int(paid_box[0]), incumbent + slack)
                            if limits.proof_ceiling is None:
                                proof_box[0] = paid_box[0]
                    if stop_on_first_terminal:
                        result.stop_reason = "solved"
                        break
                    if admitted_last:
                        result.stop_reason = "unique limit"
                        break
                    continue
                push(child_i, state, child_g)
                if admitted_last:
                    result.stop_reason = "unique limit"
                    break
            finally:
                restore_state(state, cap)
        if result.stop_reason in ("unique limit", "time limit", "rss abort", "abort", "solved"):
            break
        if incumbent is not None and slack is not None:
            live = []
            for n in names:
                if heaps[n]:
                    live.append(nodes[node_index(heaps[n][0])].g)
            if live and min(live) > incumbent + slack:
                result.stop_reason = "harvested"
                break
    result.proof_prune_unretained = sum(
        1 for ident in pruned_identities if ident not in best_g
    )
    if not result.stop_reason:
        result.stop_reason = "depth limit" if result.hit_depth_limit else "complete"
    live_g = [nodes[node_index(heaps[n][0])].g for n in names if heaps[n]]
    if live_g:
        result.min_live_g = min(live_g)
        result.closed_g = min(live_g) - 1
    elif incumbent is not None and slack is not None:
        result.closed_g = incumbent + slack
    else:
        result.closed_g = paid_box[0]
    note_rss()
    result.nodes = nodes
    result.lane_remaining = {name: len(heaps[name]) for name in names}
    result.elapsed_s = time.perf_counter() - started
    result.peak_rss_mb = peak
    if diagnostics is not None:
        # References only. The caller accounts them in place and then drops them.
        diagnostics["best_g"] = best_g
        diagnostics["heaps"] = heaps
        diagnostics["seen_expand"] = seen_expand
        diagnostics["pruned_identities"] = pruned_identities
        diagnostics["nodes"] = nodes
        diagnostics["terminals"] = result.terminals
        diagnostics["expanded_by_g"] = result.expanded_by_g
        diagnostics["generated_by_g"] = result.generated_by_g
        diagnostics["ceiling"] = paid_box[0]
        diagnostics["representation"] = representation
        diagnostics["entry_nodes"] = entry_nodes
        diagnostics["seq_mask"] = SEQ_MASK if compact else None
        diagnostics["proof_prune_identities"] = result.proof_prune_identities
        diagnostics["proof_prune_unretained"] = result.proof_prune_unretained
        diagnostics["ceiling_prunes"] = result.ceiling_prunes
        diagnostics["lower_bound_prunes"] = result.lower_bound_prunes
    return result
