"""Bounded tableau preparation before one known stock deal.

This is not a whole-game solver. The search plays tableau moves only.
The real Deal is applied afterwards, on a clone, as an evaluation of that
pre-deal tableau. A bad immediate-deal score does not remove the pre-deal
state: another tableau move might change the landing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.evaluation import (
    admissible_remaining,
    mixed_boundaries,
    same_suit_bonds,
)
from spider.metrics import format_action
from spider.packed_state import pack_state, unpack_state
from spider.planner.space_lifecycle import empty_columns
from spider.research_actions import apply_action, face_down_count, step_cost, tableau_actions
from spider.rules import MW_RULES
from spider.search_kernel import SearchLimits, run_search

PROOF_CEILING = 171
LONG_RUN = 6


def shifted_proof_height(admissible: int, proof_ceiling: int, prep_ceiling: int) -> int:
    """Height passed to a kernel whose ceiling is the preparation budget.

    The kernel rejects ``g + h > prep_ceiling``. Returning
    ``max(0, admissible - (proof_ceiling - prep_ceiling))`` makes that
    rejection match ``g + admissible > proof_ceiling`` for every ``g`` that
    the preparation budget still allows. It does not treat the preparation
    budget as a proof that the game is over.
    """

    gap = int(proof_ceiling) - int(prep_ceiling)
    return max(0, int(admissible) - gap)


def _exposed_run(column) -> int:
    up = column.face_up
    if not up:
        return 0
    length = 1
    for index in range(len(up) - 2, -1, -1):
        above, below = up[index], up[index + 1]
        if above.suit == below.suit and above.rank == below.rank + 1:
            length += 1
        else:
            break
    return length


def landing_kind(column, card) -> str:
    if column.is_empty() or not column.face_up:
        return "empty"
    top = column.face_up[-1]
    if top.rank == card.rank + 1 and top.suit == card.suit:
        return "same_suit"
    if top.rank == card.rank + 1:
        return "mixed"
    return "non_connecting"


@dataclass
class DealAssessment:
    node: int
    g_pre: int
    depth: int
    g_post: Optional[int] = None
    deal_cost: Optional[int] = None
    h_post: Optional[int] = None
    f_post: Optional[int] = None
    cannot_beat_if_deal_now: bool = False
    deal_legal: bool = False
    face_down: Optional[int] = None
    foundations: Optional[int] = None
    bonds: Optional[int] = None
    mixed_boundaries: Optional[int] = None
    landings: Tuple[str, ...] = ()
    same_suit_landings: int = 0
    mixed_landings: int = 0
    empty_landings: int = 0
    non_connecting_landings: int = 0
    buried_long_runs: int = 0
    mobility: int = 0
    zero_cost_available: int = 0
    empty_before: Tuple[int, ...] = ()
    post_pack: str = ""
    path_zero_cost: int = 0
    path: Tuple[str, ...] = ()


def assess_immediate_deal(state: SpiderState, g_pre: int, node: int, depth: int) -> DealAssessment:
    """Simulate one legal deal. The caller's state is not modified."""

    row = tuple(state.stock[-10:]) if len(state.stock) >= 10 else ()
    kinds: List[str] = []
    buried = 0
    for index, card in enumerate(row):
        column = state.columns[index]
        kind = landing_kind(column, card)
        kinds.append(kind)
        if kind == "non_connecting" and _exposed_run(column) >= LONG_RUN:
            buried += 1
    assessed = DealAssessment(
        node=node,
        g_pre=int(g_pre),
        depth=int(depth),
        landings=tuple(kinds),
        same_suit_landings=sum(kind == "same_suit" for kind in kinds),
        mixed_landings=sum(kind == "mixed" for kind in kinds),
        empty_landings=sum(kind == "empty" for kind in kinds),
        non_connecting_landings=sum(kind == "non_connecting" for kind in kinds),
        buried_long_runs=buried,
        empty_before=tuple(empty_columns(state)),
    )
    if not state.can_deal(rules=MW_RULES):
        return assessed
    post = state.clone()
    dealt = int(post.deal(rules=MW_RULES))
    h_post = int(admissible_remaining(post))
    g_post = int(g_pre) + dealt
    legal = tableau_actions(post)
    assessed.deal_legal = True
    assessed.deal_cost = dealt
    assessed.g_post = g_post
    assessed.h_post = h_post
    assessed.f_post = g_post + h_post
    assessed.cannot_beat_if_deal_now = g_post + h_post >= 172
    assessed.face_down = face_down_count(post)
    assessed.foundations = len(post.foundations)
    assessed.bonds = same_suit_bonds(post)
    assessed.mixed_boundaries = mixed_boundaries(post)
    assessed.mobility = len(legal)
    assessed.zero_cost_available = sum(step_cost(post, action) == 0 for action in legal)
    assessed.post_pack = pack_state(post).hex()
    return assessed


def workspace_purpose(state: SpiderState) -> dict:
    """Name a concrete use for each empty column. Two empties are not a score."""

    row = tuple(state.stock[-10:]) if len(state.stock) >= 10 else ()
    empties = list(empty_columns(state))
    incoming = []
    for index in empties:
        card = row[index] if index < len(row) else None
        incoming.append(
            {
                "column": index + 1,
                "incoming": None if card is None else str(card).upper(),
                "would_accept_king": bool(card is not None and card.rank == 13),
            }
        )
    uses = []
    for action in tableau_actions(state):
        if len(action) != 3:
            continue
        src, dst, count = action
        if dst not in empties:
            continue
        source = state.columns[src]
        seated = source.face_up[-1]
        card = row[dst] if dst < len(row) else None
        cost = int(step_cost(state, action))
        uses.append(
            {
                "action": format_action(action),
                "dest_column": dst + 1,
                "cost": cost,
                "reveals_face_down": len(source.face_up) == count and len(source.face_down) > 0,
                "seats_same_suit_receiver": bool(
                    card is not None
                    and seated.suit == card.suit
                    and seated.rank == card.rank + 1
                ),
                "seated_top": str(seated).upper(),
                "zero_cost_transfer": cost == 0,
                "leaves_another_empty": cost == 0 and len(empties) >= 2,
            }
        )
    return {
        "empty_columns": [index + 1 for index in empties],
        "incoming_on_empty": incoming,
        "moves_onto_empty": uses,
        "two_space_leverage": any(item["leaves_another_empty"] for item in uses),
    }


def annotate_paths(
    source: SpiderState,
    g0: int,
    kernel,
    items: Sequence[DealAssessment],
) -> None:
    """Fill path text and zero-cost counts for a short list of nodes."""

    for item in items:
        path = kernel.reconstruct(item.node)
        item.path = tuple(format_action(action) for action in path)
        replay = source.clone()
        free = 0
        spent = int(g0)
        for action in path:
            cost = int(step_cost(replay, action))
            if cost == 0:
                free += 1
            spent += cost
            apply_action(replay, action)
        item.path_zero_cost = free
        if spent != item.g_pre:
            raise RuntimeError(
                f"path cost {spent} does not match search g {item.g_pre} at node {item.node}"
            )


@dataclass
class ParetoResult:
    items: List[DealAssessment]
    front_size: int
    truncated: bool


@dataclass
class PreparationSearch:
    label: str
    stop_reason: str
    expanded: int
    unique: int
    generated: int
    duplicate_skips: int
    ceiling_prunes: int
    lower_bound_prunes: int
    depth_skips: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    hit_depth_limit: bool
    canonical_reached: bool
    canonical_g: Optional[int]
    assessments: List[DealAssessment] = field(default_factory=list)
    eval_s: float = 0.0
    canonical_node: Optional[int] = None
    zero_cost_considered: int = 0


def search_preparation(
    source: SpiderState,
    *,
    g0: int,
    label: str,
    proof_ceiling: int = PROOF_CEILING,
    prep_ceiling: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_unique: int = 20_000,
    time_limit_s: float = 30.0,
    rss_abort_mb: float = 512.0,
    canonical_pack: Optional[bytes] = None,
    proof_bound: Optional[Callable[[SpiderState, int], int]] = None,
) -> PreparationSearch:
    """Tableau search. ``prep_ceiling`` limits ``g``. Proof uses ``proof_ceiling``.

    When both ceilings are set, the bound passed into the kernel is shifted
    so a rejection still means the real admissible total exceeds
    ``proof_ceiling``. Deal-now ``g_post + h_post`` is recorded and is not
    a prune.
    """

    g0 = int(g0)
    bound_fn = proof_bound or (lambda state, _g: int(admissible_remaining(state)))
    kernel_ceiling = int(prep_ceiling) if prep_ceiling is not None else int(proof_ceiling)

    def kernel_bound(state: SpiderState, g: int) -> int:
        admissible = int(bound_fn(state, g))
        if prep_ceiling is None:
            return admissible
        return shifted_proof_height(admissible, proof_ceiling, int(prep_ceiling))

    found = PreparationSearch(
        label=label,
        stop_reason="",
        expanded=0,
        unique=0,
        generated=0,
        duplicate_skips=0,
        ceiling_prunes=0,
        lower_bound_prunes=0,
        depth_skips=0,
        elapsed_s=0.0,
        peak_rss_mb=None,
        hit_depth_limit=False,
        canonical_reached=False,
        canonical_g=None,
    )
    eval_started = [0.0]

    def on_child(state: SpiderState, g: int, node_i: int) -> None:
        started = time.perf_counter()
        item = assess_immediate_deal(state, g, node_i, 0)
        found.assessments.append(item)
        if canonical_pack is not None and pack_state(state) == canonical_pack:
            found.canonical_reached = True
            found.canonical_g = int(g)
            found.canonical_node = int(node_i)
        eval_started[0] += time.perf_counter() - started

    found_kernel = run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": g0}],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=kernel_ceiling,
            max_depth=max_depth,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=lambda _state: False,
        actions_fn=tableau_actions,
        lower_bound_fn=kernel_bound,
        on_child=on_child,
    )
    found.stop_reason = str(found_kernel.stop_reason)
    found.expanded = int(found_kernel.expanded)
    found.unique = int(found_kernel.unique)
    found.generated = int(found_kernel.generated)
    found.duplicate_skips = int(found_kernel.duplicate_skips)
    found.ceiling_prunes = int(found_kernel.ceiling_prunes)
    found.lower_bound_prunes = int(found_kernel.lower_bound_prunes)
    found.depth_skips = int(found_kernel.depth_skips)
    found.elapsed_s = float(found_kernel.elapsed_s)
    found.peak_rss_mb = found_kernel.peak_rss_mb
    found.hit_depth_limit = bool(found_kernel.hit_depth_limit)
    found.eval_s = eval_started[0]
    found.zero_cost_considered = int(found_kernel.zero_cost_actions)
    for item in found.assessments:
        item.depth = int(found_kernel.nodes[item.node].depth)
    found.kernel = found_kernel  # type: ignore[attr-defined]
    return found


def _better(left: int, right: int, direction: str) -> bool:
    return left < right if direction == "min" else left > right


def _not_worse(left: int, right: int, direction: str) -> bool:
    return left <= right if direction == "min" else left >= right


def dominates(left: DealAssessment, right: DealAssessment) -> bool:
    """True when ``left`` is better on one recorded axis and worse on none.

    Empty columns are not an axis. A smaller post-deal bound is not treated
    as a proved completion cost.
    """

    axes = (
        (left.g_pre, right.g_pre, "min"),
        (int(left.h_post or 0), int(right.h_post or 0), "min"),
        (left.same_suit_landings, right.same_suit_landings, "max"),
        (left.mobility, right.mobility, "max"),
    )
    better = False
    for lhs, rhs, direction in axes:
        if not _not_worse(lhs, rhs, direction):
            return False
        if _better(lhs, rhs, direction):
            better = True
    return better


def pareto_shortlist(
    items: Sequence[DealAssessment],
    *,
    limit: int = 8,
    canonical_node: Optional[int] = None,
) -> ParetoResult:
    """Non-dominated deal-now assessments, capped by physical diversity."""

    eligible = [item for item in items if item.deal_legal]
    if not eligible:
        return ParetoResult([], 0, False)
    front: List[DealAssessment] = []
    truncated = False
    for item in eligible:
        if any(dominates(other, item) for other in front):
            continue
        front = [other for other in front if not dominates(item, other)]
        front.append(item)
        if len(front) > 400:
            truncated = True
            break
    pool: List[DealAssessment] = list(front)

    def remember(item: Optional[DealAssessment]) -> None:
        if item is None or any(item.node == other.node for other in pool):
            return
        pool.append(item)

    if canonical_node is not None:
        remember(next((item for item in eligible if item.node == canonical_node), None))
    remember(min(eligible, key=lambda item: (item.g_pre, int(item.h_post or 0), item.node)))
    remember(min(eligible, key=lambda item: (int(item.h_post or 0), item.g_pre, item.node)))
    remember(max(eligible, key=lambda item: (item.same_suit_landings, -item.g_pre, -item.node)))
    remember(max(eligible, key=lambda item: (item.mobility, -item.g_pre, -item.node)))
    if len(pool) <= limit:
        return ParetoResult(pool, len(front), truncated)

    chosen: List[DealAssessment] = []
    seen = set()

    def take(item: Optional[DealAssessment]) -> None:
        if item is None or item.node in seen or len(chosen) >= limit:
            return
        chosen.append(item)
        seen.add(item.node)

    if canonical_node is not None:
        take(next((item for item in pool if item.node == canonical_node), None))
    take(min(pool, key=lambda item: (item.g_pre, item.node)))
    take(min(pool, key=lambda item: (int(item.h_post or 0), item.g_pre, item.node)))
    take(max(pool, key=lambda item: (item.same_suit_landings, -item.g_pre, -item.node)))
    take(max(pool, key=lambda item: (item.mobility, -item.g_pre, -item.node)))
    rest = sorted(
        pool,
        key=lambda item: (item.same_suit_landings, -(item.h_post or 0), -item.g_pre),
        reverse=True,
    )
    for item in rest:
        take(item)
    return ParetoResult(chosen, len(front), truncated)


def public_assessment(item: DealAssessment) -> dict:
    return {
        "node": item.node,
        "g_pre": item.g_pre,
        "depth": item.depth,
        "g_post": item.g_post,
        "deal_cost": item.deal_cost,
        "h_post": item.h_post,
        "f_post": item.f_post,
        "cannot_beat_if_deal_now": item.cannot_beat_if_deal_now,
        "deal_legal": item.deal_legal,
        "face_down": item.face_down,
        "foundations": item.foundations,
        "bonds": item.bonds,
        "mixed_boundaries": item.mixed_boundaries,
        "landings": list(item.landings),
        "same_suit_landings": item.same_suit_landings,
        "mixed_landings": item.mixed_landings,
        "empty_landings": item.empty_landings,
        "non_connecting_landings": item.non_connecting_landings,
        "buried_long_runs": item.buried_long_runs,
        "mobility": item.mobility,
        "zero_cost_available": item.zero_cost_available,
        "empty_before": list(item.empty_before),
        "post_pack": item.post_pack,
        "path_zero_cost": item.path_zero_cost,
        "path": list(item.path),
    }


def public_search(row: PreparationSearch, shortlist: Sequence[DealAssessment]) -> dict:
    legal = [item for item in row.assessments if item.deal_legal]
    rejected = [item for item in legal if item.cannot_beat_if_deal_now]
    return {
        "label": row.label,
        "stop_reason": row.stop_reason,
        "expanded": row.expanded,
        "unique": row.unique,
        "generated": row.generated,
        "duplicate_skips": row.duplicate_skips,
        "ceiling_prunes": row.ceiling_prunes,
        "lower_bound_prunes": row.lower_bound_prunes,
        "depth_skips": row.depth_skips,
        "elapsed_s": round(row.elapsed_s, 3),
        "eval_s": round(row.eval_s, 3),
        "peak_rss_mb": row.peak_rss_mb,
        "hit_depth_limit": row.hit_depth_limit,
        "canonical_reached": row.canonical_reached,
        "canonical_g": row.canonical_g,
        "canonical_node": row.canonical_node,
        "zero_cost_considered": row.zero_cost_considered,
        "assessed": len(row.assessments),
        "deal_legal": len(legal),
        "deal_now_cannot_beat_172": len(rejected),
        "distinct_post_packs": len({item.post_pack for item in legal}),
        "min_f_post": min((int(item.f_post) for item in legal), default=None),
        "min_h_post": min((int(item.h_post) for item in legal), default=None),
        "max_same_suit_landings": max((item.same_suit_landings for item in legal), default=None),
        "shortlist": [public_assessment(item) for item in shortlist],
    }
