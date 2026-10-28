"""Purposeful workspace macros and one multi-root fifth-deal continuation.

A macro is a short sequence of legal tableau primitives. It is not a new
engine action and it does not change corrected MobilityWare costs. Empty
columns are workspace that a manoeuvre may spend or recover. An empty
column count is not an objective, and a zero-cost whole-column transfer
stays legal even when nothing improves on that ply.

Discovery orders by the incoming stock row: a column-specific same-suit
receiver, then a one-ply follow-through for a zero-cost or space-moving
setup. The continuation reuses the v0.133 bridge order, goal and cost
lanes, strict admissible prune, and post-stock remapping. It does not
retune those lanes and it does not repeat the canonical post-SD5 search.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.anchored import target_displacement
from spider.human_strategy.evaluation import admissible_remaining
from spider.human_strategy.incumbent import IncumbentRejected, VerifiedRoute, verify_complete_solution
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import (
    pack_state,
    pack_whole_game_identity,
    unpack_state,
)
from spider.planner.space_lifecycle import empty_columns
from spider.planner.stock_reception import next_stock_row
from spider.planner.strategic_objectives import ObjectiveKind, evaluate_target
from spider.pre_sd5_preparation import assess_immediate_deal, landing_kind
from spider.research_actions import (
    all_legal_actions,
    apply_action,
    face_down_count,
    is_deal,
    step_cost,
    tableau_actions,
)
from spider.search_kernel import KernelResult, SearchLimits, run_search
from spider.stock_boundary_bridge import (
    CEILING,
    CHECKPOINT_PREP,
    MAX_UNIQUE,
    RSS_ABORT_MB,
    TIME_LIMIT_S,
    accept_cost,
    bridge_action_order,
    matching_stops,
    projected_full_cost,
    replay_remapped_suffix,
    select_ordering_targets,
)
from spider.stock_boundary_bridge import ReferenceTable


SCHEMA = "spider-purposeful-macro-portfolio-0.134"
RECEIVER_OBJECTIVE = ObjectiveKind.SHAPE_STOCK_RECEIVER
RECEIVER_TARGET = "column_top_is"
PROVENANCE = (
    "incumbent-guided prefix + discovered macro + fifth deal "
    "+ discovered continuation + remapped verified suffix"
)

# Discovery budgets. The continuation budgets are the v0.133 bridge caps.
DISCOVERY_DEPTH = 8
DISCOVERY_PAID = 4
DISCOVERY_UNIQUE = 4_000
DISCOVERY_TIME_S = 6.0
DISCOVERY_RSS_MB = 512.0
SHORTLIST_LIMIT = 64
PORTFOLIO_LIMIT = 8
CONTINUATION_UNIQUE = MAX_UNIQUE
CONTINUATION_TIME_S = TIME_LIMIT_S
CONTINUATION_RSS_MB = RSS_ABORT_MB
GATE_B_LANDINGS = 4
GATE_B_G_POST = 142

# Receiver lane, then a cheap-g setup lane so a zero-cost transfer with no
# immediate gain is still expanded. Neither key contains an empty count.
ORDERING_COMPONENTS = (
    "same_suit_hits",
    "follow_through",
    "corrected_g",
    "face_down",
)

# Recorded v0.133 single-root bridge. Not a control to rerun.
HISTORICAL_SINGLE_ROOT = {
    "source": "v0.133 stock-boundary route bridge",
    "rerun": False,
    "comparison_limit": "different root and a single post-deal state",
    "time_limit_s": 45.0,
    "elapsed_s": 45.036737,
    "unique": 3317,
    "expanded": 2765,
    "generated": 129336,
    "lower_bound_prunes": 107775,
    "proof_prune_identities": 78284,
    "proof_prune_unretained": 76945,
    "zero_cost_actions": 7233,
    "reference_checkpoint_matches": 0,
    "max_foundations": 3,
    "min_f": 166,
    "min_h": 12,
    "lane_exp_goal": 2751,
    "lane_exp_cost": 14,
    "peak_rss_mb": 47.34375,
    "caps_not_raised": True,
    "canonical_post_sd5_not_repeated": True,
}


class MacroContractError(RuntimeError):
    """A macro or a continuation could not be replayed as claimed."""


@dataclass
class WorkspaceAudit:
    """How spaces were used on one replayed route. Counts are telemetry."""

    empty_at_start: int
    empty_at_end: int
    max_empty: int
    two_spaces_available: bool
    temporary_spaces: int
    zero_cost_transfers: Tuple[str, ...]
    spaces_spent_at: Tuple[int, ...]
    spaces_recovered_at: Tuple[int, ...]
    relocated_holding_two: Tuple[int, ...]

    def public(self) -> dict:
        return {
            "empty_at_start": self.empty_at_start,
            "empty_at_end": self.empty_at_end,
            "max_empty": self.max_empty,
            "two_spaces_available": self.two_spaces_available,
            "temporary_spaces": self.temporary_spaces,
            "zero_cost_transfers": list(self.zero_cost_transfers),
            "spaces_spent_at": list(self.spaces_spent_at),
            "spaces_recovered_at": list(self.spaces_recovered_at),
            "relocated_holding_two": list(self.relocated_holding_two),
        }


@dataclass
class MacroCandidate:
    """One replay-verified pre-deal manoeuvre and its real fifth-deal result."""

    actions: Tuple[Action, ...]
    cost: int
    g_pre: int
    g_post: Optional[int]
    h_post: Optional[int]
    f_post: Optional[int]
    hits: int
    mask: int
    landings: Tuple[str, ...]
    purpose_ok: bool
    purpose: str
    seated_columns: Tuple[int, ...]
    exposed_cards: Tuple[str, ...]
    workspace: WorkspaceAudit
    face_down: Optional[int]
    bonds: Optional[int]
    foundations: Optional[int]
    pre_pack: str
    post_pack: str
    symmetry: str
    post_state: Optional[SpiderState] = field(default=None, repr=False, compare=False)
    complete_game: bool = False

    def public(self) -> dict:
        return {
            "actions": [format_action(action) for action in self.actions],
            "cost": self.cost,
            "g_pre": self.g_pre,
            "g_post": self.g_post,
            "h_post": self.h_post,
            "f_post": self.f_post,
            "hits": self.hits,
            "landings": list(self.landings),
            "purpose_ok": self.purpose_ok,
            "purpose": self.purpose,
            "seated_columns": list(self.seated_columns),
            "exposed_cards": list(self.exposed_cards),
            "workspace": self.workspace.public(),
            "face_down": self.face_down,
            "bonds": self.bonds,
            "foundations": self.foundations,
            "pre_pack": self.pre_pack,
            "post_pack": self.post_pack,
            "symmetry": self.symmetry,
            "complete_game": False,
            "objective": RECEIVER_OBJECTIVE.value,
            "target_key": RECEIVER_TARGET,
        }


@dataclass
class DiscoveryResult:
    searched: bool
    stop_reason: str
    elapsed_s: float
    scoring_s: float
    unique: int
    expanded: int
    generated: int
    zero_cost_actions: int
    lower_bound_prunes: int
    lane_exp: Tuple[Tuple[str, int], ...]
    candidates: Tuple[MacroCandidate, ...]
    gate_b: bool
    witness: Optional[MacroCandidate]
    portfolio: Tuple[MacroCandidate, ...]
    dominated: Tuple[dict, ...]
    peak_rss_mb: Optional[float]
    depth_limit: int
    paid_limit: int
    unique_limit: int

    def public(self) -> dict:
        return {
            "searched": self.searched,
            "stop_reason": self.stop_reason,
            "elapsed_s": round(self.elapsed_s, 6),
            "scoring_s": round(self.scoring_s, 6),
            "unique": self.unique,
            "expanded": self.expanded,
            "generated": self.generated,
            "zero_cost_actions": self.zero_cost_actions,
            "lower_bound_prunes": self.lower_bound_prunes,
            "lane_exp": [list(item) for item in self.lane_exp],
            "candidate_count": len(self.candidates),
            "candidates": [item.public() for item in self.candidates],
            "gate_b": self.gate_b,
            "witness": None if self.witness is None else self.witness.public(),
            "portfolio": [item.public() for item in self.portfolio],
            "dominated": list(self.dominated),
            "peak_rss_mb": self.peak_rss_mb,
            "depth_limit": self.depth_limit,
            "paid_limit": self.paid_limit,
            "unique_limit": self.unique_limit,
            "empty_count_is_objective": False,
            "complete_game": False,
        }


@dataclass
class PostDealRoot:
    """One physical tableau after a discovered macro and the real fifth deal."""

    state: SpiderState
    g: int
    macro: Tuple[Action, ...] = ()
    h: Optional[int] = None
    f: Optional[int] = None
    hits: int = 0
    mask: int = 0
    landings: Tuple[str, ...] = ()
    purpose: str = ""
    pack: str = ""
    symmetry: str = ""


@dataclass
class ContinuationResult:
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
            "independent_cold_complete": False,
        }


def macro_identity(state: SpiderState) -> bytes:
    """Ordered physical identity. Column permutation is not a deal identity."""

    return pack_state(state)


def stock_row(state: SpiderState) -> Tuple:
    row = next_stock_row(state)
    return tuple(row) if row is not None else ()


def hit_mask(state: SpiderState, row: Optional[Sequence] = None) -> Tuple[int, int]:
    """Column-specific same-suit receivers for the next stock row.

    An empty column is not a hit, including when the incoming card is a king.
    """

    cards = tuple(row) if row is not None else stock_row(state)
    mask = 0
    for index, card in enumerate(cards):
        if index >= len(state.columns):
            break
        if landing_kind(state.columns[index], card) == "same_suit":
            mask |= 1 << index
    return _popcount(mask), mask


def same_suit_hits(state: SpiderState, row: Optional[Sequence] = None) -> int:
    hits, _mask = hit_mask(state, row)
    return hits


def ordering_key(state: SpiderState, g: int, row: Optional[Sequence] = None) -> tuple:
    """Receiver-lane order. Lower is expanded sooner. Empty count is absent."""

    cards = tuple(row) if row is not None else stock_row(state)
    hits, follow, face_down = _features(state, cards)
    return (-hits, -follow, int(g), face_down)


def rank_macro_actions(
    state: SpiderState,
    actions: Sequence[Action],
    row: Optional[Sequence] = None,
) -> List[Action]:
    """Order every tableau action. None are removed.

    A receiver gain comes first. A zero-cost or space-moving action with no
    immediate gain is then ranked by the best receiver gain on the next ply,
    so the setup is not dropped. Cost and a reveal are the remaining ties.
    """

    cards = tuple(row) if row is not None else stock_row(state)
    _hits, base_mask = hit_mask(state, cards)
    decorated = []
    for index, action in enumerate(actions):
        gain = _predicted_gain(state, action, cards, base_mask)
        cost = int(step_cost(state, action))
        setup = 0
        if gain <= 0 and cards and _setup_action(state, action, cost):
            setup = _one_ply_gain(state, action, cards)
        reveal = 1
        if not is_deal(action):
            src, _dst, count = action
            source = state.columns[src]
            if len(source.face_up) == count and source.face_down:
                reveal = 0
        decorated.append(((-gain, -setup, cost, reveal, index), action))
    decorated.sort(key=lambda item: item[0])
    ordered = [action for _key, action in decorated]
    if len(ordered) != len(list(actions)):
        raise MacroContractError("macro ordering dropped a legal action")
    return ordered


def audit_workspace(source: SpiderState, actions: Sequence[Action]) -> WorkspaceAudit:
    """Replay ``actions`` and record space use. The caller is not mutated."""

    _final, _spent, audit = _replay_audit(source, actions)
    return audit


def discover_macros(
    source: SpiderState,
    *,
    g0: int,
    max_depth: int = DISCOVERY_DEPTH,
    paid_moves: int = DISCOVERY_PAID,
    max_unique: int = DISCOVERY_UNIQUE,
    time_limit_s: float = DISCOVERY_TIME_S,
    rss_abort_mb: float = DISCOVERY_RSS_MB,
    shortlist_limit: int = SHORTLIST_LIMIT,
    portfolio_limit: int = PORTFOLIO_LIMIT,
) -> DiscoveryResult:
    """Bounded tableau search, then an authoritative deal on the shortlist.

    ``assess_immediate_deal`` is not called on the generated graph. A state
    whose only change is the empty-column count is not a candidate.
    """

    g0 = int(g0)
    row = stock_row(source)
    started = time.perf_counter()
    kernel, slots = _search_tableau_macros(
        source,
        g0=g0,
        row=row,
        max_depth=int(max_depth),
        paid_moves=int(paid_moves),
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
        shortlist_limit=int(shortlist_limit),
    )
    scoring_started = time.perf_counter()
    candidates = _score_shortlist(source, g0, row, kernel, slots)
    scoring_s = time.perf_counter() - scoring_started
    portfolio, dominated = select_portfolio(candidates, limit=int(portfolio_limit))
    witnesses = gate_b_witnesses(candidates)
    witness = None
    if witnesses:
        witnesses.sort(key=lambda item: (item.g_post if item.g_post is not None else 10**9, item.h_post or 0, -item.hits))
        witness = witnesses[0]
    return DiscoveryResult(
        searched=True,
        stop_reason=str(kernel.stop_reason),
        elapsed_s=time.perf_counter() - started,
        scoring_s=scoring_s,
        unique=int(kernel.unique),
        expanded=int(kernel.expanded),
        generated=int(kernel.generated),
        zero_cost_actions=int(kernel.zero_cost_actions),
        lower_bound_prunes=int(kernel.lower_bound_prunes),
        lane_exp=tuple(sorted(kernel.lane_exp.items())),
        candidates=tuple(candidates),
        gate_b=witness is not None,
        witness=witness,
        portfolio=tuple(portfolio),
        dominated=tuple(dominated),
        peak_rss_mb=kernel.peak_rss_mb,
        depth_limit=int(max_depth),
        paid_limit=int(paid_moves),
        unique_limit=int(max_unique),
    )


def gate_b_witnesses(candidates: Sequence[MacroCandidate]) -> List[MacroCandidate]:
    """Replay-verified plans with the known feasible landing quality."""

    found = []
    for item in candidates:
        if not item.purpose_ok or item.g_post is None:
            continue
        if item.hits >= GATE_B_LANDINGS and int(item.g_post) <= GATE_B_G_POST:
            found.append(item)
    return found


def select_portfolio(
    candidates: Sequence[MacroCandidate],
    *,
    limit: int = PORTFOLIO_LIMIT,
    ceiling: int = CEILING,
) -> Tuple[List[MacroCandidate], List[dict]]:
    """At most ``limit`` purposeful post-deal roots with ``f <= ceiling``.

    Symmetry duplicates keep the cheaper physical chain. The dropped chain
    is reported. Among the survivors, a four-landing plan at ``g <= 142``
    and the lowest post-deal ``g`` are kept even when assembly ``h`` is higher.
    """

    eligible = [
        item
        for item in candidates
        if item.purpose_ok
        and item.post_state is not None
        and item.f_post is not None
        and int(item.f_post) <= int(ceiling)
        and item.symmetry
    ]
    eligible.sort(key=lambda item: (int(item.g_post or 0), item.post_pack))
    survivors: List[MacroCandidate] = []
    dominated: List[dict] = []
    seen: Dict[str, MacroCandidate] = {}
    for item in eligible:
        previous = seen.get(item.symmetry)
        if previous is None:
            seen[item.symmetry] = item
            survivors.append(item)
            continue
        dominated.append(_dominance_row(item, previous))
    chosen: List[MacroCandidate] = []

    def take(item: Optional[MacroCandidate]) -> None:
        if item is None or item in chosen or len(chosen) >= int(limit):
            return
        chosen.append(item)

    witnesses = [
        item
        for item in survivors
        if item.hits >= GATE_B_LANDINGS and item.g_post is not None and int(item.g_post) <= GATE_B_G_POST
    ]
    witnesses.sort(key=lambda item: (int(item.g_post or 0), int(item.h_post or 0), -item.hits))
    if witnesses:
        take(witnesses[0])
    if survivors:
        take(min(survivors, key=lambda item: (int(item.g_post or 0), int(item.h_post or 0), -item.hits)))
    rest = sorted(survivors, key=lambda item: (-item.hits, int(item.g_post or 0), int(item.h_post or 0)))
    seen_masks = {item.mask for item in chosen}
    for item in rest:
        if item.mask not in seen_masks:
            take(item)
            seen_masks.add(item.mask)
    for item in rest:
        take(item)
    return chosen, dominated


def roots_from_portfolio(portfolio: Sequence[MacroCandidate]) -> List[PostDealRoot]:
    roots = []
    for item in portfolio:
        if item.post_state is None or item.g_post is None:
            continue
        roots.append(
            PostDealRoot(
                state=item.post_state,
                g=int(item.g_post),
                macro=tuple(item.actions),
                h=item.h_post,
                f=item.f_post,
                hits=item.hits,
                mask=item.mask,
                landings=tuple(item.landings),
                purpose=item.purpose,
                pack=item.post_pack,
                symmetry=item.symmetry,
            )
        )
    return roots


def search_bridge_roots(
    roots: Sequence[PostDealRoot],
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
) -> ContinuationResult:
    """One shared post-deal search from already generated physical roots.

    Lanes, action order, and the strict ``g + h > ceiling`` prune match the
    v0.133 bridge. A root that already rejoins or is solved is recorded
    without spending the search budget. Symmetry-dominated physical chains
    are not passed in and stay at zero expansions.
    """

    ceiling = int(ceiling)
    prepared, dominated = _prepare_roots(roots)
    targets = (
        tuple(ordering_targets)
        if ordering_targets is not None
        else select_ordering_targets(references.stops)
    )
    blank = _blank_continuation(ceiling, prepared, dominated)
    if not prepared:
        return blank

    preview = None
    preview_origin = None
    for index, root in enumerate(prepared):
        hit = _rejoin(root.state, int(root.g), references, ceiling)
        if hit.accepted and (preview is None or _better_hit(hit, preview)):
            preview = hit
            preview_origin = index
    if preview is not None and preview_origin is not None:
        root = prepared[preview_origin]
        return _from_hit(
            blank,
            preview,
            origin=preview_origin,
            macro=tuple(root.macro),
            continuation=(),
            searched=False,
            stop_reason=preview.kind,
            unique=len(prepared),
            replay_ok=True,
        )

    expansions = [0] * len(prepared)
    origin_of: Dict[bytes, int] = {}
    accepted = _Hit()
    accepted_node = [-1]
    accepted_origin = [-1]
    affinity_s = [0.0]
    affinity_calls = [0]
    nearest = [10**9]
    max_foundations = max(len(root.state.foundations) for root in prepared)
    seen_foundations = [max_foundations]
    match_counts = _Hit()

    def bound(state: SpiderState, g: int) -> int:
        if lower_bound_fn is None:
            return int(admissible_remaining(state))
        return int(lower_bound_fn(state, g))

    def lane_keys_fn(state: SpiderState, g: int) -> Dict[str, Optional[tuple]]:
        # Unchanged v0.133 schedule. Worse-than-nearest states stay on the
        # goal lane only. Empty count is not a term.
        started = time.perf_counter()
        if targets:
            displacement = min(target_displacement(state, stop.state) for stop in targets)
        else:
            displacement = 0
        affinity_s[0] += time.perf_counter() - started
        affinity_calls[0] += 1
        if displacement < nearest[0]:
            nearest[0] = displacement
        cost_key = (int(g), int(displacement)) if displacement <= nearest[0] else None
        return {"goal": (int(displacement), int(g)), "cost": cost_key}

    def note(state: SpiderState, g: int, node_i: int, result: Optional[KernelResult] = None) -> None:
        seen_foundations[0] = max(seen_foundations[0], len(state.foundations))
        if result is not None:
            origin_of[pack_state(state)] = int(result.nodes[node_i].origin)
        hit = _rejoin(state, g, references, ceiling)
        _accumulate(match_counts, hit)
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
            accepted_origin[0] = int(origin_of.get(pack_state(state), result.nodes[node_i].origin if result is not None else -1))

    def on_child(state: SpiderState, g: int, node_i: int) -> None:
        note(state, g, node_i, None)

    def on_progress(result: KernelResult, state: SpiderState, g: int, node_i: int) -> None:
        origin_of[pack_state(state)] = int(result.nodes[node_i].origin)
        if progress and result.unique and result.unique % 5000 == 0:
            print(
                f"PROGRESS unique={result.unique} expanded={result.expanded} "
                f"g={g} f={result.min_f} foundations={len(state.foundations)}",
                flush=True,
            )

    def counted_actions(state: SpiderState) -> List[Action]:
        origin = origin_of.get(pack_state(state))
        if origin is not None and 0 <= origin < len(expansions):
            expansions[origin] += 1
        if actions_fn is not None:
            return list(actions_fn(state))
        return all_legal_actions(state)

    def is_terminal(state: SpiderState) -> bool:
        return accepted.pack is not None and pack_state(state) == accepted.pack

    kernel_roots = [
        {"ordered_digest": pack_state(root.state).hex(), "g": int(root.g)}
        for root in prepared
    ]
    # Roots call on_child before on_progress has stored the origin. Seed the
    # map from the same packs the kernel will unpack.
    for index, root in enumerate(prepared):
        origin_of[pack_state(root.state)] = index

    kernel = run_search(
        kernel_roots,
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling,
        ),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("goal", "cost"),
        lane_keys_fn=lane_keys_fn,
        is_terminal=is_terminal,
        actions_fn=counted_actions,
        action_order=bridge_action_order,
        on_child=on_child,
        on_progress=on_progress,
        lower_bound_fn=bound,
        stop_on_first_terminal=True,
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
    terminal_hits = 0
    if accepted.accepted and accepted_node[0] >= 0:
        node_i = accepted_node[0]
        origin = int(kernel.nodes[node_i].origin)
        if origin < 0 or origin >= len(prepared):
            origin = accepted_origin[0] if accepted_origin[0] >= 0 else None
        if origin is not None and 0 <= origin < len(prepared):
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
                terminal_hits = 1
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
    inconclusive = bool(not accepted_now and reason in {"time limit", "unique limit", "rss abort", "abort"})
    negative = bool(not accepted_now and reason == "complete")
    return ContinuationResult(
        accepted=accepted_now,
        kind=kind if accepted_now else "",
        stop_reason=reason,
        searched=True,
        ceiling=ceiling,
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
        expanded=int(kernel.expanded),
        unique=int(kernel.unique),
        generated=int(kernel.generated),
        lower_bound_prunes=int(kernel.lower_bound_prunes),
        proof_prune_identities=int(kernel.proof_prune_identities),
        proof_prune_unretained=int(kernel.proof_prune_unretained),
        zero_cost_actions=int(kernel.zero_cost_actions),
        ceiling_prunes=int(kernel.ceiling_prunes),
        duplicate_skips=int(kernel.duplicate_skips),
        stale_skips=int(kernel.stale_skips),
        min_f=kernel.min_f,
        min_h=kernel.min_h,
        max_h=kernel.max_h,
        max_foundations=seen_foundations[0],
        reference_checkpoint_matches=match_counts.matches,
        elapsed_s=float(kernel.elapsed_s),
        peak_rss_mb=kernel.peak_rss_mb,
        affinity_s=affinity_s[0],
        affinity_calls=affinity_calls[0],
        lane_exp=tuple(sorted(kernel.lane_exp.items())),
        expanded_by_g=tuple(sorted(kernel.expanded_by_g.items())),
        expansions_by_origin=tuple(expansions),
        dominated=tuple(dominated),
        inconclusive=inconclusive,
        negative_within_cap=negative,
        terminal_hits=terminal_hits,
    )


def compose_discovered_route(
    canonical_actions: Sequence[Action],
    macro: Sequence[Action],
    continuation: Sequence[Action],
    remapped_suffix: Sequence[Action],
) -> List[Action]:
    """Canonical prefix, discovered macro, the fifth deal, continuation, suffix.

    The prefix and the macro stay in checkpoint coordinates. Only the suffix
    has been remapped into the post-deal tableau.
    """

    return (
        list(canonical_actions[:CHECKPOINT_PREP])
        + list(macro)
        + [("deal",)]
        + list(continuation)
        + list(remapped_suffix)
    )


def accept_improved_route(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    expected_cost: Optional[int] = None,
    ceiling: int = CEILING,
) -> Optional[VerifiedRoute]:
    """Full eight-foundation replay. A tactical macro is not a complete game."""

    try:
        verified = verify_complete_solution(
            opening,
            actions,
            expected_cost=expected_cost,
            source=PROVENANCE,
            source_id="4925153-purposeful-macro",
        )
    except IncumbentRejected:
        return None
    if not accept_cost(verified.cost, ceiling) or verified.foundations != 8 or not verified.solved:
        return None
    return verified


def _search_tableau_macros(
    source: SpiderState,
    *,
    g0: int,
    row: Sequence,
    max_depth: int,
    paid_moves: int,
    max_unique: int,
    time_limit_s: float,
    rss_abort_mb: float,
    shortlist_limit: int,
):
    start_hits, _start_mask = hit_mask(source, row)
    start_exposed = _exposed_needed(source, _needed_keys(row))
    slots: List[Tuple[int, int, int, int]] = []

    def consider(hits: int, g: int, node_i: int, mask: int) -> None:
        slot = (hits, g, node_i, mask)
        if len(slots) < int(shortlist_limit):
            slots.append(slot)
            return
        worst = min(range(len(slots)), key=lambda index: (slots[index][0], -slots[index][1]))
        current = slots[worst]
        if hits > current[0] or (hits == current[0] and g < current[1]):
            slots[worst] = slot

    def on_child(state: SpiderState, g: int, node_i: int) -> None:
        hits, mask = hit_mask(state, row)
        exposed = _exposed_needed(state, _needed_keys(row))
        if hits > start_hits or exposed > start_exposed:
            consider(hits, int(g), int(node_i), mask)

    def lane_keys_fn(state: SpiderState, g: int) -> Dict[str, tuple]:
        hits, follow, face_down = _features(state, row)
        return {
            "receiver": (-hits, -follow, int(g), face_down),
            "setup": (int(g), -follow, -hits, face_down),
        }

    def order(state: SpiderState, actions: List[Action]) -> List[Action]:
        return rank_macro_actions(state, actions, row)

    kernel = run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": int(g0)}],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=int(g0) + int(paid_moves),
            max_depth=int(max_depth),
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("receiver", "setup"),
        lane_keys_fn=lane_keys_fn,
        is_terminal=lambda _state: False,
        actions_fn=tableau_actions,
        action_order=order,
        on_child=on_child,
        lower_bound_fn=None,
        stop_on_first_terminal=False,
    )
    return kernel, slots


def _score_shortlist(source, g0, row, kernel, slots) -> List[MacroCandidate]:
    ranked = sorted(slots, key=lambda slot: (-slot[0], slot[1], slot[2]))
    found: List[MacroCandidate] = []
    seen = set()
    for hits, g, node_i, _mask in ranked:
        if node_i < 0 or node_i >= len(kernel.nodes):
            continue
        node = kernel.nodes[node_i]
        actions = tuple(kernel.reconstruct(node_i))
        if any(is_deal(action) for action in actions):
            continue
        key = (actions, int(g))
        if key in seen:
            continue
        seen.add(key)
        candidate = _verify_candidate(
            source,
            g0,
            row,
            actions,
            expected_g=int(g),
            store=node.store,
            depth=int(node.depth),
            node_i=int(node_i),
        )
        if candidate is None or not candidate.purpose_ok:
            continue
        found.append(candidate)
    found.sort(key=lambda item: (-item.hits, item.g_post if item.g_post is not None else 10**9, item.cost))
    return found


def _verify_candidate(source, g0, row, actions, *, expected_g, store, depth, node_i):
    try:
        final, spent, audit = _replay_audit(source, actions)
    except ValueError:
        return None
    if int(g0) + spent != int(expected_g) or pack_state(final) != store:
        return None
    purpose = _purpose(source, final, row)
    assessed = None
    post = None
    g_post = None
    h_post = None
    f_post = None
    hits = purpose["hits"]
    mask = purpose["mask"]
    landings: Tuple[str, ...] = ()
    face_down = None
    bonds = None
    foundations = None
    post_pack = ""
    symmetry = ""
    if len(final.stock) >= 10 and final.can_deal():
        assessed = assess_immediate_deal(final, int(expected_g), int(node_i), int(depth))
        if assessed.deal_legal and assessed.g_post is not None:
            post = final.clone()
            apply_action(post, ("deal",))
            g_post = int(assessed.g_post)
            h_post = int(assessed.h_post) if assessed.h_post is not None else None
            f_post = int(assessed.f_post) if assessed.f_post is not None else None
            hits = int(assessed.same_suit_landings)
            _post_hits, mask = hit_mask(final, row)
            landings = tuple(assessed.landings)
            face_down = assessed.face_down
            bonds = assessed.bonds
            foundations = assessed.foundations
            post_pack = pack_state(post).hex()
            symmetry = pack_whole_game_identity(post).hex()
            if g_post != int(expected_g) + int(step_cost(final, ("deal",))):
                return None
    if not purpose["ok"] and hits <= same_suit_hits(source, row):
        return None
    purpose_ok = bool(purpose["ok"] or hits > same_suit_hits(source, row))
    return MacroCandidate(
        actions=tuple(actions),
        cost=int(spent),
        g_pre=int(expected_g),
        g_post=g_post,
        h_post=h_post,
        f_post=f_post,
        hits=int(hits),
        mask=int(mask),
        landings=landings,
        purpose_ok=purpose_ok,
        purpose=purpose["text"] if purpose_ok else "",
        seated_columns=tuple(purpose["seated"]),
        exposed_cards=tuple(purpose["exposed"]),
        workspace=audit,
        face_down=face_down,
        bonds=bonds,
        foundations=foundations,
        pre_pack=pack_state(final).hex(),
        post_pack=post_pack,
        symmetry=symmetry,
        post_state=post,
        complete_game=False,
    )


def _purpose(start: SpiderState, end: SpiderState, row: Sequence) -> dict:
    seated = []
    for index, card in enumerate(row):
        if card.rank >= 13:
            continue
        params = {"column": index, "suit": card.suit, "rank": card.rank + 1}
        now = evaluate_target(end, RECEIVER_TARGET, params)
        before = evaluate_target(start, RECEIVER_TARGET, params)
        if now and not before:
            seated.append(index)
    exposed = []
    needed = _needed_keys(row)
    start_tops = _top_keys(start)
    for column in end.columns:
        top = column.top()
        if top is None:
            continue
        key = (top.suit, top.rank)
        if key in needed and key not in start_tops:
            label = str(top).upper()
            if label not in exposed:
                exposed.append(label)
    hits, mask = hit_mask(end, row)
    parts = []
    if seated:
        parts.append("seated column-specific receiver")
    if exposed:
        parts.append("exposed needed receiver")
    return {
        "ok": bool(seated or exposed),
        "text": "; ".join(parts),
        "seated": seated,
        "exposed": exposed,
        "hits": hits,
        "mask": mask,
    }


def _replay_audit(source: SpiderState, actions: Sequence[Action]):
    state = source.clone()
    start_empty = set(empty_columns(state))
    max_empty = len(start_empty)
    spent_at = []
    recovered_at = []
    relocated = []
    zeros = []
    used_spaces = 0
    spent_cost = 0
    for index, action in enumerate(actions):
        if is_deal(action):
            raise ValueError("macro discovery does not deal")
        before = set(empty_columns(state))
        cost = int(step_cost(state, action))
        _src, dst, _count = action
        if state.columns[dst].is_empty():
            used_spaces += 1
        spent_cost += int(apply_action(state, action))
        after = set(empty_columns(state))
        max_empty = max(max_empty, len(after))
        if cost == 0:
            zeros.append(format_action(action))
        if len(after) < len(before):
            spent_at.append(index)
        elif len(after) > len(before):
            recovered_at.append(index)
        elif cost == 0 and before != after and len(after) >= 2:
            relocated.append(index)
        elif cost == 0 and before != after and len(before) >= 2 and len(after) == len(before):
            relocated.append(index)
    audit = WorkspaceAudit(
        empty_at_start=len(start_empty),
        empty_at_end=len(empty_columns(state)),
        max_empty=max_empty,
        two_spaces_available=len(start_empty) >= 2 or max_empty >= 2,
        temporary_spaces=used_spaces,
        zero_cost_transfers=tuple(zeros),
        spaces_spent_at=tuple(spent_at),
        spaces_recovered_at=tuple(recovered_at),
        relocated_holding_two=tuple(relocated),
    )
    return state, spent_cost, audit


def _features(state: SpiderState, row: Sequence) -> Tuple[int, int, int]:
    hits, mask = hit_mask(state, row)
    follow = 0
    if row:
        for action in tableau_actions(state):
            gain = _predicted_gain(state, action, row, mask)
            if gain > follow:
                follow = gain
    return hits, follow, face_down_count(state)


def _predicted_gain(state: SpiderState, action: Action, row: Sequence, base_mask: int) -> int:
    if is_deal(action) or not row:
        return 0
    src, dst, count = action
    if src == dst or count <= 0:
        return 0
    source = state.columns[src]
    if count > len(source.face_up):
        return 0
    new_mask = base_mask & ~(1 << src) & ~(1 << dst)
    src_card, src_empty = _source_top_after(source, count)
    if _matches(src_card, src_empty, row[src] if src < len(row) else None):
        new_mask |= 1 << src
    dest_card = source.face_up[-1]
    if _matches(dest_card, False, row[dst] if dst < len(row) else None):
        new_mask |= 1 << dst
    return _popcount(new_mask) - _popcount(base_mask)


def _source_top_after(column, count: int):
    if len(column.face_up) > count:
        return column.face_up[-(count + 1)], False
    if column.face_down:
        return column.face_down[-1], False
    return None, True


def _matches(card, empty: bool, incoming) -> bool:
    if empty or card is None or incoming is None:
        return False
    return card.suit == incoming.suit and card.rank == incoming.rank + 1


def _setup_action(state: SpiderState, action: Action, cost: int) -> bool:
    if is_deal(action):
        return False
    if cost == 0:
        return True
    src, dst, count = action
    source = state.columns[src]
    dest_empty = state.columns[dst].is_empty()
    opens_source = len(source.face_up) == count and not source.face_down
    return dest_empty or opens_source


def _one_ply_gain(state: SpiderState, action: Action, row: Sequence) -> int:
    trial = state.clone()
    apply_action(trial, action)
    _hits, mask = hit_mask(trial, row)
    best = 0
    for child in tableau_actions(trial):
        gain = _predicted_gain(trial, child, row, mask)
        if gain > best:
            best = gain
    return best


def _needed_keys(row: Sequence) -> set:
    keys = set()
    for card in row:
        if card.rank >= 13:
            continue
        keys.add((card.suit, card.rank + 1))
    return keys


def _exposed_needed(state: SpiderState, needed: set) -> int:
    return len(_top_keys(state) & needed)


def _top_keys(state: SpiderState) -> set:
    keys = set()
    for column in state.columns:
        top = column.top()
        if top is not None:
            keys.add((top.suit, top.rank))
    return keys


def _popcount(mask: int) -> int:
    return bin(int(mask)).count("1")


def _dominance_row(dropped: MacroCandidate, kept: MacroCandidate) -> dict:
    return {
        "reason": "symmetry-dominated",
        "dropped_g": dropped.g_post,
        "kept_g": kept.g_post,
        "dropped_macro": [format_action(action) for action in dropped.actions],
        "kept_macro": [format_action(action) for action in kept.actions],
        "dropped_pack": dropped.post_pack,
        "kept_pack": kept.post_pack,
        "symmetry": dropped.symmetry,
    }


@dataclass
class _Hit:
    accepted: bool = False
    kind: str = ""
    reference_index: Optional[int] = None
    reference_g: Optional[int] = None
    projected: Optional[int] = None
    mapping: Optional[Tuple[int, ...]] = None
    suffix: Tuple[Action, ...] = ()
    suffix_cost: Optional[int] = None
    g: Optional[int] = None
    pack: Optional[bytes] = None
    matches: int = 0
    physical: int = 0
    symmetry: int = 0
    rejected: int = 0
    attempts: int = 0
    remap_failures: int = 0
    replay_failures: int = 0


def _rejoin(state: SpiderState, g: int, table: ReferenceTable, ceiling: int) -> _Hit:
    """Public bridge helpers only. Equality at the ceiling stays eligible."""

    hit = _Hit(g=int(g), pack=pack_state(state))
    solved = bool(state.is_solved() and len(state.foundations) == 8 and not state.stock)
    if solved and accept_cost(g, ceiling):
        hit.accepted = True
        hit.kind = "solved"
        hit.projected = int(g)
        hit.suffix = ()
        hit.suffix_cost = 0
        return hit
    matches = matching_stops(table, state)
    hit.matches = len(matches)
    for _stop, kind in matches:
        if kind == "physical":
            hit.physical += 1
        else:
            hit.symmetry += 1
    improving = [(stop, kind) for stop, kind in matches if int(g) < int(stop.g)]
    hit.rejected = len(matches) - len(improving)
    improving.sort(key=lambda item: (-int(item[0].g), item[0].index))
    for stop, _kind in improving:
        hit.attempts += 1
        projected = projected_full_cost(g, stop.g, table.canonical_total)
        replayed = replay_remapped_suffix(state, stop.state, stop.suffix)
        if not replayed.ok:
            if replayed.failure == "remap":
                hit.remap_failures += 1
            else:
                hit.replay_failures += 1
            continue
        if replayed.cost != stop.suffix_cost or projected is None or int(g) + int(replayed.cost) != projected:
            hit.replay_failures += 1
            continue
        if not accept_cost(projected, ceiling):
            hit.rejected += 1
            continue
        hit.accepted = True
        hit.kind = "reference rejoin"
        hit.reference_index = stop.index
        hit.reference_g = stop.g
        hit.projected = projected
        hit.mapping = replayed.mapping
        hit.suffix = replayed.actions
        hit.suffix_cost = replayed.cost
        return hit
    return hit


def _accumulate(total: _Hit, item: _Hit) -> None:
    total.matches += item.matches
    total.physical += item.physical
    total.symmetry += item.symmetry
    total.rejected += item.rejected
    total.attempts += item.attempts
    total.remap_failures += item.remap_failures
    total.replay_failures += item.replay_failures


def _better_hit(left: _Hit, right: _Hit) -> bool:
    left_cost = left.projected if left.projected is not None else 10**9
    right_cost = right.projected if right.projected is not None else 10**9
    if left_cost != right_cost:
        return left_cost < right_cost
    return int(left.g or 0) < int(right.g or 0)


def _prepare_roots(roots: Sequence[PostDealRoot]) -> Tuple[List[PostDealRoot], List[dict]]:
    """Drop a worse physical chain that shares a post-stock symmetry identity.

    Survivors keep the caller's order. The kernel origin is that index.
    """

    winner = {}
    identity = []
    for index, root in enumerate(roots):
        ident = pack_whole_game_identity(root.state)
        identity.append(ident)
        key = (int(root.g), pack_state(root.state).hex())
        previous = winner.get(ident)
        if previous is None or key < previous[0]:
            winner[ident] = (key, index)
    kept_indexes = {index for _key, index in winner.values()}
    kept = []
    dominated = []
    for index, root in enumerate(roots):
        if index in kept_indexes:
            kept.append(root)
            continue
        victor = roots[winner[identity[index]][1]]
        dominated.append(
            {
                "reason": "symmetry-dominated",
                "dropped_g": root.g,
                "kept_g": victor.g,
                "dropped_macro": [format_action(action) for action in root.macro],
                "kept_macro": [format_action(action) for action in victor.macro],
                "dropped_pack": pack_state(root.state).hex(),
                "kept_pack": pack_state(victor.state).hex(),
            }
        )
    return kept, dominated


def _blank_continuation(ceiling: int, prepared: Sequence[PostDealRoot], dominated: Sequence[dict]) -> ContinuationResult:
    return ContinuationResult(
        accepted=False,
        kind="",
        stop_reason="no root",
        searched=False,
        ceiling=int(ceiling),
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
        expanded=0,
        unique=len(prepared),
        generated=0,
        lower_bound_prunes=0,
        proof_prune_identities=0,
        proof_prune_unretained=0,
        zero_cost_actions=0,
        ceiling_prunes=0,
        duplicate_skips=0,
        stale_skips=0,
        min_f=None,
        min_h=None,
        max_h=None,
        max_foundations=0,
        reference_checkpoint_matches=0,
        elapsed_s=0.0,
        peak_rss_mb=None,
        affinity_s=0.0,
        affinity_calls=0,
        lane_exp=(),
        expanded_by_g=(),
        expansions_by_origin=tuple(0 for _root in prepared),
        dominated=tuple(dominated),
        inconclusive=False,
        negative_within_cap=False,
        terminal_hits=0,
    )


def _from_hit(blank: ContinuationResult, hit: _Hit, *, origin: int, macro, continuation, searched: bool, stop_reason: str, unique: int, replay_ok: bool) -> ContinuationResult:
    blank.accepted = True
    blank.kind = hit.kind
    blank.stop_reason = stop_reason
    blank.searched = searched
    blank.origin = origin
    blank.macro = tuple(macro)
    blank.continuation = tuple(continuation)
    blank.remapped_suffix = tuple(hit.suffix)
    blank.g = hit.g
    blank.reference_index = hit.reference_index
    blank.reference_g = hit.reference_g
    blank.projected_cost = hit.projected
    blank.mapping = hit.mapping
    blank.replay_ok = replay_ok
    blank.unique = unique
    blank.terminal_hits = 1
    blank.reference_checkpoint_matches = hit.matches
    return blank
