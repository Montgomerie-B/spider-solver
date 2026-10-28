"""Origin-fair continuation across the v0.134 post-deal roots.

The macro generator is unchanged. This module only changes how one shared
search spends the existing 20,000-state, 45-second, 512 MB budget. Each
admitted root gets a goal lane and a cost lane. The lanes use the v0.133
keys. One transposition table, one ceiling, and one proof prune stay global.

Lane order is every root's goal lane, in caller index order, then every
root's cost lane in that same order. The kernel round-robins that list.
An empty lane does not expand a node. A node that sits on both of its
origin's lanes is expanded once at a given g.

The cost lane's nearest-displacement record is per origin. A closer tableau
found under one root does not remove another root's cost lane. Within a
root, a worse displacement than that root's own nearest stays on the goal
lane only, which is the v0.133 rule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.anchored import target_displacement
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.purposeful_macro import (
    _Hit,
    _accumulate,
    _better_hit,
    _prepare_roots,
    _rejoin,
)
from spider.research_actions import all_legal_actions
from spider.search_kernel import KernelResult, SearchLimits, run_search
from spider.stock_boundary_bridge import (
    CEILING,
    MAX_UNIQUE,
    RSS_ABORT_MB,
    TIME_LIMIT_S,
    bridge_action_order,
    select_ordering_targets,
)
from spider.stock_boundary_bridge import ReferenceTable


SCHEMA = "spider-origin-fair-continuation-0.135"
CONTINUATION_UNIQUE = MAX_UNIQUE
CONTINUATION_TIME_S = TIME_LIMIT_S
CONTINUATION_RSS_MB = RSS_ABORT_MB

# The v0.134 eight-root continuation. It is not rerun here.
HISTORICAL_V0134 = {
    "source": "v0.134 purposeful macro continuation",
    "rerun": False,
    "stop_reason": "time limit",
    "outcome": "inconclusive",
    "unique": 3182,
    "expanded": 2192,
    "generated": 124294,
    "lower_bound_prunes": 104769,
    "min_f": 166,
    "max_foundations": 3,
    "reference_checkpoint_matches": 0,
    "elapsed_s": 45.036258,
    "lane_exp_goal": 2180,
    "lane_exp_cost": 12,
    "expansions_by_origin": (1, 1, 0, 0, 0, 0, 0, 2190),
    "max_unique": 20_000,
    "time_limit_s": 45.0,
    "rss_abort_mb": 512.0,
}


def fair_lane_names(count: int) -> Tuple[str, ...]:
    """Goal lanes for every root, then cost lanes for every root."""

    indexes = range(int(count))
    return tuple(f"{index}.goal" for index in indexes) + tuple(
        f"{index}.cost" for index in indexes
    )


def goal_lane_key(g: int, displacement: int) -> Tuple[int, int]:
    """Unchanged v0.133 goal order. Lower displacement, then lower g."""

    return (int(displacement), int(g))


def cost_lane_key(g: int, displacement: int, nearest: int) -> Tuple[int, Optional[Tuple[int, int]]]:
    """v0.133 cost eligibility against one nearest displacement.

    Returns the updated nearest and the key. A worse displacement returns
    ``None`` and stays off this lane. Ties and new records stay on it.
    """

    best = int(displacement) if int(displacement) < int(nearest) else int(nearest)
    if int(displacement) <= best:
        return best, (int(g), int(displacement))
    return best, None


@dataclass
class FairResult:
    """One shared continuation, plus per-origin coverage."""

    accepted: bool
    kind: str
    stop_reason: str
    searched: bool
    ceiling: int
    origin: Optional[int]
    macro: Tuple[Action, ...]
    continuation: Tuple[Action, ...]
    remapped_suffix: Tuple[Action, ...]
    g: Optional[int]
    reference_index: Optional[int]
    reference_g: Optional[int]
    projected_cost: Optional[int]
    mapping: Optional[Tuple[int, ...]]
    replay_ok: bool
    expanded: int
    unique: int
    generated: int
    lower_bound_prunes: int
    proof_prune_identities: int
    proof_prune_unretained: int
    zero_cost_actions: int
    ceiling_prunes: int
    duplicate_skips: int
    stale_skips: int
    min_f: Optional[int]
    min_h: Optional[int]
    max_h: Optional[int]
    max_foundations: int
    reference_checkpoint_matches: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    affinity_s: float
    affinity_calls: int
    lane_exp: Tuple[Tuple[str, int], ...]
    expanded_by_g: Tuple[Tuple[int, int], ...]
    expansions_by_origin: Tuple[int, ...]
    dominated: Tuple[dict, ...]
    inconclusive: bool
    negative_within_cap: bool
    terminal_hits: int
    origins: Tuple[dict, ...]
    goal_expansions: int
    cost_expansions: int
    lane_order: Tuple[str, ...]
    cross_origin_better_g: int
    independent_cold_complete: bool = False

    def public(self) -> dict:
        return {
            "accepted": self.accepted,
            "kind": self.kind,
            "stop_reason": self.stop_reason,
            "searched": self.searched,
            "ceiling": self.ceiling,
            "origin": self.origin,
            "macro": [format_action(action) for action in self.macro],
            "continuation": [format_action(action) for action in self.continuation],
            "remapped_suffix": [format_action(action) for action in self.remapped_suffix],
            "g": self.g,
            "reference_index": self.reference_index,
            "reference_g": self.reference_g,
            "projected_cost": self.projected_cost,
            "mapping": None if self.mapping is None else list(self.mapping),
            "replay_ok": self.replay_ok,
            "expanded": self.expanded,
            "unique": self.unique,
            "generated": self.generated,
            "lower_bound_prunes": self.lower_bound_prunes,
            "proof_prune_identities": self.proof_prune_identities,
            "proof_prune_unretained": self.proof_prune_unretained,
            "zero_cost_actions": self.zero_cost_actions,
            "ceiling_prunes": self.ceiling_prunes,
            "duplicate_skips": self.duplicate_skips,
            "stale_skips": self.stale_skips,
            "min_f": self.min_f,
            "min_h": self.min_h,
            "max_h": self.max_h,
            "max_foundations": self.max_foundations,
            "reference_checkpoint_matches": self.reference_checkpoint_matches,
            "elapsed_s": round(self.elapsed_s, 6),
            "peak_rss_mb": self.peak_rss_mb,
            "affinity_s": round(self.affinity_s, 6),
            "affinity_calls": self.affinity_calls,
            "lane_exp": [list(item) for item in self.lane_exp],
            "expanded_by_g": [list(item) for item in self.expanded_by_g],
            "expansions_by_origin": list(self.expansions_by_origin),
            "dominated": list(self.dominated),
            "inconclusive": self.inconclusive,
            "negative_within_cap": self.negative_within_cap,
            "terminal_hits": self.terminal_hits,
            "origins": list(self.origins),
            "goal_expansions": self.goal_expansions,
            "cost_expansions": self.cost_expansions,
            "lane_order": list(self.lane_order),
            "cross_origin_better_g": self.cross_origin_better_g,
            "independent_cold_complete": False,
        }


def search_origin_fair(
    roots: Sequence,
    *,
    references: ReferenceTable,
    ordering_targets: Optional[Sequence] = None,
    ceiling: int = CEILING,
    max_unique: int = CONTINUATION_UNIQUE,
    time_limit_s: float = CONTINUATION_TIME_S,
    rss_abort_mb: float = CONTINUATION_RSS_MB,
    lower_bound_fn=None,
    actions_fn=None,
    progress: bool = False,
) -> FairResult:
    """One shared post-deal search with a goal lane and a cost lane per root.

    Symmetry-dominated physical chains are omitted and counted. Their caller
    indexes are not renumbered onto a different survivor: survivors keep the
    order they were passed in, and the kernel origin is that index.
    """

    ceiling = int(ceiling)
    prepared, dominated = _prepare_roots(roots)
    targets = (
        tuple(ordering_targets)
        if ordering_targets is not None
        else select_ordering_targets(references.stops)
    )
    names = fair_lane_names(len(prepared))
    if not prepared:
        return _empty(ceiling, dominated, names)

    preview = None
    preview_origin = None
    for index, root in enumerate(prepared):
        hit = _rejoin(root.state, int(root.g), references, ceiling)
        if hit.accepted and (preview is None or _better_hit(hit, preview)):
            preview = hit
            preview_origin = index
    if preview is not None and preview_origin is not None:
        root = prepared[preview_origin]
        return _from_preview(
            preview,
            prepared,
            dominated,
            names,
            ceiling,
            origin=preview_origin,
            macro=tuple(root.macro),
        )

    return _search(
        prepared,
        dominated,
        names,
        targets,
        references,
        ceiling,
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
        lower_bound_fn=lower_bound_fn,
        actions_fn=actions_fn,
        progress=progress,
    )


def _empty(ceiling: int, dominated: Sequence[dict], names: Sequence[str]) -> FairResult:
    return _result(
        accepted=False,
        kind="",
        stop_reason="no root",
        searched=False,
        ceiling=ceiling,
        prepared=(),
        dominated=dominated,
        names=names,
        kernel=None,
        origin_rows=(),
    )


def _from_preview(hit: _Hit, prepared, dominated, names, ceiling: int, *, origin: int, macro) -> FairResult:
    rows = []
    for index, root in enumerate(prepared):
        status = "admitted rejoin" if index == origin else "not searched"
        rows.append(_row(index, root, status=status))
    found = _result(
        accepted=True,
        kind=hit.kind,
        stop_reason=hit.kind,
        searched=False,
        ceiling=ceiling,
        prepared=prepared,
        dominated=dominated,
        names=names,
        kernel=None,
        origin_rows=tuple(rows),
        origin=origin,
        macro=tuple(macro),
        remapped_suffix=tuple(hit.suffix),
        g=hit.g,
        reference_index=hit.reference_index,
        reference_g=hit.reference_g,
        projected_cost=hit.projected,
        mapping=hit.mapping,
        replay_ok=True,
        unique=len(prepared),
        max_foundations=max(len(root.state.foundations) for root in prepared),
        reference_checkpoint_matches=hit.matches,
        terminal_hits=1,
    )
    return found


def _search(
    prepared,
    dominated,
    names,
    targets,
    references,
    ceiling: int,
    *,
    max_unique: int,
    time_limit_s: float,
    rss_abort_mb: float,
    lower_bound_fn,
    actions_fn,
    progress: bool,
) -> FairResult:
    count = len(prepared)
    selected = [0] * count
    admitted = [0] * count
    terminal_hits = [0] * count
    nearest = [10**9] * count
    origin_of: Dict[bytes, int] = {}
    seen_best: Dict[bytes, Tuple[int, int]] = {}
    cross = [0]
    accepted = _Hit()
    accepted_node = [-1]
    affinity_s = [0.0]
    affinity_calls = [0]
    max_foundations = max(len(root.state.foundations) for root in prepared)
    seen_foundations = [max_foundations]
    match_counts = _Hit()

    def bound(state: SpiderState, g: int) -> int:
        if lower_bound_fn is None:
            return int(admissible_remaining(state))
        return int(lower_bound_fn(state, g))

    def origin_lane_keys(state: SpiderState, g: int, origin: int) -> Dict[str, Optional[tuple]]:
        started = time.perf_counter()
        if targets:
            displacement = min(target_displacement(state, stop.state) for stop in targets)
        else:
            displacement = 0
        affinity_s[0] += time.perf_counter() - started
        affinity_calls[0] += 1
        if origin < 0 or origin >= count:
            return {}
        best, cost_key = cost_lane_key(g, displacement, nearest[origin])
        nearest[origin] = best
        goal_name = f"{origin}.goal"
        cost_name = f"{origin}.cost"
        if goal_name in names:
            selected[origin] += 1
        if cost_key is not None and cost_name in names:
            selected[origin] += 1
        return {goal_name: goal_lane_key(g, displacement), cost_name: cost_key}

    def on_progress(result: KernelResult, state: SpiderState, g: int, node_i: int) -> None:
        node = result.nodes[node_i]
        origin_of[pack_state(state)] = int(node.origin)
        if node.parent >= 0 and 0 <= node.origin < count:
            admitted[node.origin] += 1
        previous = seen_best.get(node.ident)
        if previous is not None and int(node.g) < previous[0] and int(node.origin) != previous[1]:
            cross[0] += 1
        if previous is None or int(node.g) < previous[0]:
            seen_best[node.ident] = (int(node.g), int(node.origin))
        if progress and result.unique and result.unique % 5000 == 0:
            print(
                f"PROGRESS unique={result.unique} expanded={result.expanded} "
                f"g={g} f={result.min_f} foundations={len(state.foundations)}",
                flush=True,
            )

    def on_child(state: SpiderState, g: int, node_i: int) -> None:
        seen_foundations[0] = max(seen_foundations[0], len(state.foundations))
        origin = origin_of.get(pack_state(state), -1)
        hit = _rejoin(state, g, references, ceiling)
        _accumulate(match_counts, hit)
        if hit.accepted and 0 <= origin < count:
            terminal_hits[origin] += 1
        if hit.accepted and not accepted.accepted:
            accepted.accepted = True
            accepted.kind = hit.kind
            accepted.reference_index = hit.reference_index
            accepted.reference_g = hit.reference_g
            accepted.projected = hit.projected
            accepted.mapping = hit.mapping
            accepted.suffix = hit.suffix
            accepted.suffix_cost = hit.suffix_cost
            accepted.pack = hit.pack
            accepted.g = int(g)
            accepted_node[0] = int(node_i)

    def is_terminal(state: SpiderState) -> bool:
        return accepted.pack is not None and pack_state(state) == accepted.pack

    def counted_actions(state: SpiderState) -> List[Action]:
        if actions_fn is not None:
            return list(actions_fn(state))
        return all_legal_actions(state)

    for index, root in enumerate(prepared):
        origin_of[pack_state(root.state)] = index

    kernel = run_search(
        [{"ordered_digest": pack_state(root.state).hex(), "g": int(root.g)} for root in prepared],
        limits=SearchLimits(
            max_unique=max_unique,
            time_limit_s=time_limit_s,
            rss_abort_mb=rss_abort_mb,
            cost_ceiling=ceiling,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=names,
        origin_lane_keys_fn=origin_lane_keys,
        is_terminal=is_terminal,
        actions_fn=counted_actions,
        action_order=bridge_action_order,
        on_child=on_child,
        on_progress=on_progress,
        lower_bound_fn=bound,
        stop_on_first_terminal=True,
    )
    rows = tuple(
        _coverage(index, root, kernel, selected, admitted, terminal_hits)
        for index, root in enumerate(prepared)
    )
    reason = str(kernel.stop_reason)
    continuation: Tuple[Action, ...] = ()
    replay_ok = False
    kind = ""
    projected = None
    reference_index = None
    reference_g = None
    mapping = None
    suffix: Tuple[Action, ...] = ()
    found_g = None
    origin = None
    macro: Tuple[Action, ...] = ()
    hits = 0
    if accepted.accepted and accepted_node[0] >= 0:
        node_i = accepted_node[0]
        origin = int(kernel.nodes[node_i].origin)
        if 0 <= origin < count:
            macro = tuple(prepared[origin].macro)
            start = prepared[origin].state
            g_root = int(prepared[origin].g)
            continuation = tuple(kernel.reconstruct(node_i))
            trial = start.clone()
            try:
                played = int(replay_actions(trial, list(continuation)))
            except ValueError:
                played = -1
            found_g = int(accepted.g) if accepted.g is not None else None
            replay_ok = bool(
                found_g is not None
                and played == found_g - g_root
                and pack_state(trial) == accepted.pack
            )
            if replay_ok:
                kind = accepted.kind
                projected = accepted.projected
                reference_index = accepted.reference_index
                reference_g = accepted.reference_g
                mapping = accepted.mapping
                suffix = accepted.suffix
                hits = 1
                if kind == "reference rejoin":
                    reason = "reference rejoin"
                elif kind == "solved":
                    reason = "solved"
            else:
                reason = "replay rejected"
                replay_ok = False
                continuation = ()
                suffix = ()
                macro = ()
                origin = None
                found_g = None
    accepted_now = bool(replay_ok and kind)
    return _result(
        accepted=accepted_now,
        kind=kind if accepted_now else "",
        stop_reason=reason,
        searched=True,
        ceiling=ceiling,
        prepared=prepared,
        dominated=dominated,
        names=names,
        kernel=kernel,
        origin_rows=rows,
        origin=origin if accepted_now else None,
        macro=macro if accepted_now else (),
        continuation=continuation if accepted_now else (),
        remapped_suffix=suffix if accepted_now else (),
        g=found_g if accepted_now else None,
        reference_index=reference_index if accepted_now else None,
        reference_g=reference_g if accepted_now else None,
        projected_cost=projected if accepted_now else None,
        mapping=mapping if accepted_now else None,
        replay_ok=replay_ok,
        max_foundations=seen_foundations[0],
        reference_checkpoint_matches=match_counts.matches,
        affinity_s=affinity_s[0],
        affinity_calls=affinity_calls[0],
        terminal_hits=hits,
        cross_origin_better_g=cross[0],
    )


def _coverage(index: int, root, kernel: KernelResult, selected, admitted, terminal_hits) -> dict:
    goal = f"{index}.goal"
    cost = f"{index}.cost"
    popped = int(kernel.lane_pops.get(goal, 0)) + int(kernel.lane_pops.get(cost, 0))
    expanded = int(kernel.lane_exp.get(goal, 0)) + int(kernel.lane_exp.get(cost, 0))
    remaining = int(kernel.lane_remaining.get(goal, 0)) + int(kernel.lane_remaining.get(cost, 0))
    if popped == 0 and expanded == 0 and remaining == 0:
        status = "no viable frontier"
    elif remaining == 0:
        status = "exhausted"
    else:
        status = "live"
    row = _row(index, root, status=status)
    row["selected"] = int(selected[index])
    row["popped"] = popped
    row["expanded"] = expanded
    row["admitted"] = int(admitted[index])
    row["goal_expanded"] = int(kernel.lane_exp.get(goal, 0))
    row["cost_expanded"] = int(kernel.lane_exp.get(cost, 0))
    row["terminal_hits"] = int(terminal_hits[index])
    row["goal_remaining"] = int(kernel.lane_remaining.get(goal, 0))
    row["cost_remaining"] = int(kernel.lane_remaining.get(cost, 0))
    return row


def _row(index: int, root, *, status: str) -> dict:
    return {
        "index": int(index),
        "g": int(root.g),
        "h": root.h,
        "f": root.f,
        "hits": int(root.hits),
        "pack": pack_state(root.state).hex(),
        "symmetry": "" if root.state.stock else pack_whole_game_identity(root.state).hex(),
        "macro": [format_action(action) for action in root.macro],
        "selected": 0,
        "popped": 0,
        "expanded": 0,
        "admitted": 0,
        "goal_expanded": 0,
        "cost_expanded": 0,
        "terminal_hits": 0,
        "goal_remaining": 0,
        "cost_remaining": 0,
        "status": status,
    }


def _result(
    *,
    accepted: bool,
    kind: str,
    stop_reason: str,
    searched: bool,
    ceiling: int,
    prepared,
    dominated,
    names,
    kernel: Optional[KernelResult],
    origin_rows,
    origin=None,
    macro=(),
    continuation=(),
    remapped_suffix=(),
    g=None,
    reference_index=None,
    reference_g=None,
    projected_cost=None,
    mapping=None,
    replay_ok=False,
    unique=None,
    max_foundations=0,
    reference_checkpoint_matches=0,
    affinity_s=0.0,
    affinity_calls=0,
    terminal_hits=0,
    cross_origin_better_g=0,
) -> FairResult:
    expansions = tuple(int(row["expanded"]) for row in origin_rows)
    goal_expansions = sum(int(row["goal_expanded"]) for row in origin_rows)
    cost_expansions = sum(int(row["cost_expanded"]) for row in origin_rows)
    reason = str(stop_reason)
    accepted_now = bool(accepted)
    inconclusive = bool(searched and not accepted_now and reason in {"time limit", "unique limit", "rss abort", "abort"})
    negative = bool(searched and not accepted_now and reason == "complete")
    return FairResult(
        accepted=accepted_now,
        kind=kind if accepted_now else "",
        stop_reason=reason,
        searched=bool(searched),
        ceiling=int(ceiling),
        origin=origin if accepted_now else None,
        macro=tuple(macro) if accepted_now else (),
        continuation=tuple(continuation) if accepted_now else (),
        remapped_suffix=tuple(remapped_suffix) if accepted_now else (),
        g=g if accepted_now else None,
        reference_index=reference_index if accepted_now else None,
        reference_g=reference_g if accepted_now else None,
        projected_cost=projected_cost if accepted_now else None,
        mapping=mapping if accepted_now else None,
        replay_ok=bool(replay_ok),
        expanded=0 if kernel is None else int(kernel.expanded),
        unique=len(prepared) if unique is None and kernel is None else (int(kernel.unique) if kernel is not None else int(unique)),
        generated=0 if kernel is None else int(kernel.generated),
        lower_bound_prunes=0 if kernel is None else int(kernel.lower_bound_prunes),
        proof_prune_identities=0 if kernel is None else int(kernel.proof_prune_identities),
        proof_prune_unretained=0 if kernel is None else int(kernel.proof_prune_unretained),
        zero_cost_actions=0 if kernel is None else int(kernel.zero_cost_actions),
        ceiling_prunes=0 if kernel is None else int(kernel.ceiling_prunes),
        duplicate_skips=0 if kernel is None else int(kernel.duplicate_skips),
        stale_skips=0 if kernel is None else int(kernel.stale_skips),
        min_f=None if kernel is None else kernel.min_f,
        min_h=None if kernel is None else kernel.min_h,
        max_h=None if kernel is None else kernel.max_h,
        max_foundations=int(max_foundations),
        reference_checkpoint_matches=int(reference_checkpoint_matches),
        elapsed_s=0.0 if kernel is None else float(kernel.elapsed_s),
        peak_rss_mb=None if kernel is None else kernel.peak_rss_mb,
        affinity_s=float(affinity_s),
        affinity_calls=int(affinity_calls),
        lane_exp=() if kernel is None else tuple(sorted(kernel.lane_exp.items())),
        expanded_by_g=() if kernel is None else tuple(sorted(kernel.expanded_by_g.items())),
        expansions_by_origin=expansions,
        dominated=tuple(dominated),
        inconclusive=inconclusive,
        negative_within_cap=negative,
        terminal_hits=int(terminal_hits),
        origins=tuple(origin_rows),
        goal_expansions=int(goal_expansions),
        cost_expansions=int(cost_expansions),
        lane_order=tuple(names),
        cross_origin_better_g=int(cross_origin_better_g),
    )
