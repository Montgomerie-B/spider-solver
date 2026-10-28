"""Post-deal tactical search for one reveal-and-foundation milestone.

The predicate is relative to the source: one more foundation of the requested
suit, and at least one face-down card actually exposed. Ordering prefers a
longer same-suit run and a shallower copy of the next card in that run.
It does not score empty columns, and it does not receive a reference action
list. A column-specific face-down target uses ordered ``pack_state``;
otherwise post-stock symmetry is the transposition identity.

``proof_ceiling`` is independent of the paid-move cap. Equality ``g + h``
stays eligible. Callers that omit it keep the historical kernel rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import Action, format_action
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.planner.strategic_objectives import evaluate_target
from spider.purposeful_macro import PostDealRoot, compose_discovered_route
from spider.research_actions import (
    apply_action,
    face_down_count,
    is_deal,
    step_cost,
    tableau_actions,
)
from spider.search_kernel import SearchLimits, run_search

SCHEMA = "spider-post-deal-milestone-0.136"
WORKERS = 1

# Gate A positive control. The proof ceiling is 172, not 171.
CONTROL_PAID = 8
CONTROL_DEPTH = 12
CONTROL_UNIQUE = 12_000
CONTROL_TIME_S = 12.0
CONTROL_RSS_MB = 512.0
CONTROL_PROOF = 172

# Gate B tactic searches. These are not full-game continuations.
TACTIC_PAID = 12
TACTIC_DEPTH = 18
TACTIC_UNIQUE = 6_000
TACTIC_TIME_S = 6.0
TACTIC_RSS_MB = 512.0
TACTIC_PROOF = 171

ENDPOINT_LIMIT = 8
ENDPOINT_CEILING = 171

_SUITS = ("s", "h", "d", "c")


class MilestoneContractError(RuntimeError):
    """Ordering or identity contract was broken."""


@dataclass(frozen=True)
class MilestoneSpec:
    """Observable baseline. No card name and no deal id."""

    suit: str
    source_foundations: int
    source_face_down: int
    column: Optional[int] = None
    max_face_down: Optional[int] = None

    @property
    def column_specific(self) -> bool:
        return self.column is not None


@dataclass(frozen=True)
class _Features:
    foundations: int
    run: int
    low: int
    run_column: int
    next_depth: int
    home_depth: int
    face_down: int


@dataclass
class MilestoneHit:
    """One replay-checked path. ``state`` is a private unpack, not a live node."""

    actions: Tuple[Action, ...]
    g: int
    paid: int
    zero_cost: int
    suit_gain: int
    face_down_drop: int
    pack: str
    symmetry: str
    replay_ok: bool
    state: Optional[SpiderState] = None

    def public(self) -> dict:
        return {
            "actions": [format_action(action) for action in self.actions],
            "g": self.g,
            "paid": self.paid,
            "zero_cost": self.zero_cost,
            "suit_gain": self.suit_gain,
            "face_down_drop": self.face_down_drop,
            "pack": self.pack,
            "symmetry": self.symmetry,
            "replay_ok": self.replay_ok,
        }


@dataclass
class MilestoneResult:
    met: bool
    replay_ok: bool
    stop_reason: str
    outcome: str
    suit: str
    g0: int
    g: Optional[int]
    paid: int
    zero_cost: int
    actions: Tuple[Action, ...]
    suit_before: int
    suit_after: int
    face_down_before: int
    face_down_after: Optional[int]
    pack: str
    column_specific: bool
    proof_ceiling: Optional[int]
    cost_ceiling: int
    max_depth: int
    max_unique: int
    time_limit_s: float
    rss_abort_mb: float
    unique: int
    expanded: int
    generated: int
    elapsed_s: float
    peak_rss_mb: Optional[float]
    lower_bound_prunes: int
    proof_prune_identities: int
    ceiling_prunes: int
    depth_skips: int
    zero_cost_actions: int
    min_f: Optional[int]
    min_h: Optional[int]
    max_h: Optional[int]
    lane_exp: Tuple[Tuple[str, int], ...]
    diagnostics: Dict[str, int]
    hits: Tuple[MilestoneHit, ...] = field(default_factory=tuple)

    def public(self) -> dict:
        return {
            "met": self.met,
            "replay_ok": self.replay_ok,
            "stop_reason": self.stop_reason,
            "outcome": self.outcome,
            "suit": self.suit,
            "g0": self.g0,
            "g": self.g,
            "paid": self.paid,
            "zero_cost": self.zero_cost,
            "actions": [format_action(action) for action in self.actions],
            "suit_before": self.suit_before,
            "suit_after": self.suit_after,
            "face_down_before": self.face_down_before,
            "face_down_after": self.face_down_after,
            "pack": self.pack,
            "column_specific": self.column_specific,
            "proof_ceiling": self.proof_ceiling,
            "cost_ceiling": self.cost_ceiling,
            "max_depth": self.max_depth,
            "max_unique": self.max_unique,
            "time_limit_s": self.time_limit_s,
            "rss_abort_mb": self.rss_abort_mb,
            "workers": WORKERS,
            "unique": self.unique,
            "expanded": self.expanded,
            "generated": self.generated,
            "elapsed_s": round(self.elapsed_s, 6),
            "peak_rss_mb": self.peak_rss_mb,
            "lower_bound_prunes": self.lower_bound_prunes,
            "proof_prune_identities": self.proof_prune_identities,
            "ceiling_prunes": self.ceiling_prunes,
            "depth_skips": self.depth_skips,
            "zero_cost_actions": self.zero_cost_actions,
            "min_f": self.min_f,
            "min_h": self.min_h,
            "max_h": self.max_h,
            "lane_exp": [list(item) for item in self.lane_exp],
            "diagnostics": dict(self.diagnostics),
            "hits": [hit.public() for hit in self.hits],
        }


@dataclass
class MilestoneEndpoint:
    """A verified milestone plus the pre-deal macro of the root that found it."""

    root_index: int
    g: int
    h: int
    actions: Tuple[Action, ...]
    pre_deal_macro: Tuple[Action, ...]
    state: SpiderState
    pack: str
    symmetry: str
    suit_gain: int
    face_down_drop: int
    zero_cost: int
    paid: int
    replay_ok: bool = True

    @property
    def f(self) -> int:
        return int(self.g) + int(self.h)

    def public(self) -> dict:
        return {
            "root_index": self.root_index,
            "g": self.g,
            "h": self.h,
            "f": self.f,
            "actions": [format_action(action) for action in self.actions],
            "pre_deal_macro": [format_action(action) for action in self.pre_deal_macro],
            "pack": self.pack,
            "symmetry": self.symmetry,
            "suit_gain": self.suit_gain,
            "face_down_drop": self.face_down_drop,
            "zero_cost": self.zero_cost,
            "paid": self.paid,
            "replay_ok": self.replay_ok,
        }


def suit_foundation_count(state: SpiderState, suit: str) -> int:
    """Foundations of ``suit``. Same rule as ``foundations_of_suit_ge``."""

    count = 0
    for seq in state.foundations:
        if len(seq) == 13 and seq and all(card.suit == suit for card in seq):
            count += 1
    return count


def milestone_met(state: SpiderState, spec: MilestoneSpec) -> bool:
    """Both a new suit foundation and a real expose. Either one alone fails."""

    gained = evaluate_target(
        state,
        "foundations_of_suit_ge",
        {"suit": spec.suit, "min_count": int(spec.source_foundations) + 1},
    )
    if spec.column is None:
        revealed = face_down_count(state) <= int(spec.source_face_down) - 1
    else:
        revealed = evaluate_target(
            state,
            "column_face_down_le",
            {"column": int(spec.column), "max_face_down": int(spec.max_face_down)},
        )
    return bool(gained and revealed)


def milestone_identity(state: SpiderState, *, column: Optional[int] = None) -> bytes:
    """Symmetry only while the predicate ignores physical columns."""

    if column is not None:
        return pack_state(state)
    return pack_whole_game_identity(state)


def spec_from_source(
    source: SpiderState,
    suit: str,
    *,
    column: Optional[int] = None,
    max_face_down: Optional[int] = None,
) -> MilestoneSpec:
    if column is None:
        return MilestoneSpec(suit, suit_foundation_count(source, suit), face_down_count(source))
    if max_face_down is None:
        max_face_down = len(source.columns[int(column)].face_down) - 1
    return MilestoneSpec(
        suit,
        suit_foundation_count(source, suit),
        face_down_count(source),
        int(column),
        int(max_face_down),
    )


def control_succeeded(result: MilestoneResult) -> bool:
    """Gate B and Gate C stay closed until the positive control replays."""

    return bool(result.met and result.replay_ok)


def _card_depth(column, suit: str, rank: int) -> Optional[int]:
    best = None
    up = column.face_up
    for index, card in enumerate(up):
        if card.suit == suit and card.rank == rank:
            depth = len(up) - index - 1
            best = depth if best is None else min(best, depth)
    down = column.face_down
    for index, card in enumerate(down):
        if card.suit == suit and card.rank == rank:
            depth = (len(down) - index - 1) + len(up)
            best = depth if best is None else min(best, depth)
    return best


def _shallowest(state: SpiderState, suit: str, rank: int) -> Tuple[int, int]:
    """Return ``(depth, column)`` for the least buried copy. Missing is deep."""

    best_depth = 80
    best_column = -1
    for index, column in enumerate(state.columns):
        depth = _card_depth(column, suit, rank)
        if depth is not None and depth < best_depth:
            best_depth = depth
            best_column = index
    return best_depth, best_column


def _measure(state: SpiderState, suit: str) -> _Features:
    best_len = 0
    best_high = 0
    best_low = 0
    best_column = -1
    for index, column in enumerate(state.columns):
        up = column.face_up
        if not up or up[-1].suit != suit:
            continue
        end = len(up) - 1
        start = end
        while (
            start > 0
            and up[start - 1].suit == suit
            and up[start - 1].rank == up[start].rank + 1
        ):
            start -= 1
        length = end - start + 1
        high = up[start].rank
        low = up[end].rank
        if length > best_len or (length == best_len and high > best_high):
            best_len = length
            best_high = high
            best_low = low
            best_column = index
    if best_len == 0 or best_low <= 1:
        next_depth, next_column = (0 if best_len else 80), -1
    else:
        next_depth, next_column = _shallowest(state, suit, best_low - 1)
    home = 0
    if next_depth > 0 and next_column >= 0:
        home = _home_depth(state, next_column)
    return _Features(
        foundations=suit_foundation_count(state, suit),
        run=best_len,
        low=best_low,
        run_column=best_column,
        next_depth=next_depth,
        home_depth=home,
        face_down=face_down_count(state),
    )


def _home_depth(state: SpiderState, column_index: int) -> int:
    """How buried a landing is for the top card covering the needed card.

    An empty column is a legal landing for that one card. This is not a
    score for the number of empty columns.
    """

    column = state.columns[column_index]
    top = column.top()
    if top is None:
        return 0
    if any(other.is_empty() for other in state.columns):
        return 0
    need = top.rank + 1
    if need > 13:
        return 50
    best = 50
    for other in state.columns:
        for suit in _SUITS:
            depth = _card_depth(other, suit, need)
            if depth is not None and depth < best:
                best = depth
    return best


def _exposed_after(column, count: int):
    up = column.face_up
    if count < len(up):
        return up[-count - 1]
    if count == len(up) and column.face_down:
        return column.face_down[-1]
    return None


def rank_milestone_actions(
    state: SpiderState,
    actions: Sequence[Action],
    suit: str,
    *,
    column: Optional[int] = None,
) -> List[Action]:
    """Order every tableau action. None are removed.

    A move that extends the longest run of ``suit``, uncovers that run's
    next card, or reveals a face-down card comes first. Cost breaks the
    remaining ties, so a zero-cost relocation is kept.
    """

    features = _measure(state, suit)

    def rank(item: Tuple[int, Action]) -> tuple:
        index, action = item
        cost = step_cost(state, action)
        extends = 1
        uncovers = 1
        reveal = 1
        same = 1
        frees = 1
        if not is_deal(action):
            src, dst, count = action
            source = state.columns[src]
            run = source.face_up[-count:] if 0 < count <= len(source.face_up) else []
            top = state.columns[dst].top()
            if (
                features.run_column == dst
                and features.low > 1
                and run
                and run[0].suit == suit
                and run[0].rank == features.low - 1
                and top is not None
                and top.suit == suit
                and top.rank == features.low
            ):
                extends = 0
            exposed = _exposed_after(source, count) if run or count == len(source.face_up) else None
            if (
                features.low > 1
                and exposed is not None
                and exposed.suit == suit
                and exposed.rank == features.low - 1
            ):
                uncovers = 0
            if len(source.face_up) == count and source.face_down:
                reveal = 0
            if (
                top is not None
                and run
                and top.suit == run[0].suit
                and top.rank == run[0].rank + 1
            ):
                same = 0
            if column is not None and src == int(column):
                frees = 0
        return (extends, uncovers, reveal, frees, cost, same, index)

    ordered = [action for _index, action in sorted(enumerate(actions), key=rank)]
    if len(ordered) != len(list(actions)):
        raise MilestoneContractError("milestone ordering dropped a legal action")
    return ordered


def _lane_keys(state: SpiderState, g: int, suit: str, column: Optional[int]) -> Dict[str, tuple]:
    features = _measure(state, suit)
    # A named column is ordering only. Clearing it stays ahead of a run that
    # does not land on that column. The suit-wide search does not use it.
    if column is None:
        progress: tuple = (
            -features.foundations,
            -features.run,
            features.next_depth,
            features.home_depth,
            features.face_down,
            int(g),
        )
    else:
        progress = (
            -features.foundations,
            len(state.columns[int(column)].face_up),
            -features.run,
            features.next_depth,
            features.home_depth,
            features.face_down,
            int(g),
        )
    setup: List[int] = [int(g)]
    if column is not None:
        setup.append(len(state.columns[int(column)].face_up))
    setup.extend(
        [
            features.next_depth,
            features.home_depth,
            features.face_down,
            -features.run,
            -features.foundations,
        ]
    )
    return {"progress": progress, "setup": tuple(setup)}


def _replay(source: SpiderState, actions: Sequence[Action]) -> Tuple[SpiderState, int, int]:
    state = source.clone()
    spent = 0
    zeros = 0
    for action in actions:
        cost = int(step_cost(state, action))
        got = int(apply_action(state, action))
        if got != cost:
            raise MilestoneContractError("replay cost disagreed with step_cost")
        spent += got
        if cost == 0:
            zeros += 1
    return state, spent, zeros


def search_milestone(
    source: SpiderState,
    *,
    g0: int,
    suit: str,
    paid_moves: int,
    max_depth: int,
    max_unique: int,
    time_limit_s: float,
    rss_abort_mb: float = CONTROL_RSS_MB,
    proof_ceiling: Optional[int] = None,
    column: Optional[int] = None,
    max_face_down: Optional[int] = None,
    terminal_fn: Optional[Callable[[SpiderState], bool]] = None,
    stop_on_first: bool = True,
    lower_bound_fn: Optional[Callable[[SpiderState, int], int]] = None,
    hit_limit: int = 8,
) -> MilestoneResult:
    """Search from one physical source. Reference actions are not an input."""

    spec = spec_from_source(source, suit, column=column, max_face_down=max_face_down)
    g0 = int(g0)
    cost_ceiling = g0 + int(paid_moves)
    diagnostics = {
        "max_suit_foundations": spec.source_foundations,
        "min_face_down": spec.source_face_down,
        "foundation_without_reveal": 0,
        "reveal_without_foundation": 0,
    }

    def is_goal(state: SpiderState) -> bool:
        if terminal_fn is not None:
            return bool(terminal_fn(state))
        return milestone_met(state, spec)

    def on_child(state: SpiderState, _g: int, _node_i: int) -> None:
        foundations = suit_foundation_count(state, suit)
        hidden = face_down_count(state)
        diagnostics["max_suit_foundations"] = max(diagnostics["max_suit_foundations"], foundations)
        diagnostics["min_face_down"] = min(diagnostics["min_face_down"], hidden)
        gained = foundations >= spec.source_foundations + 1
        if spec.column is None:
            revealed = hidden <= spec.source_face_down - 1
        else:
            revealed = evaluate_target(
                state,
                "column_face_down_le",
                {"column": int(spec.column), "max_face_down": int(spec.max_face_down)},
            )
        if gained and not revealed:
            diagnostics["foundation_without_reveal"] += 1
        elif revealed and not gained:
            diagnostics["reveal_without_foundation"] += 1

    bound = lower_bound_fn
    if bound is None and proof_ceiling is not None:
        cache: Dict[bytes, int] = {}

        def bound(state: SpiderState, _g: int, _cache: Dict[bytes, int] = cache) -> int:
            key = pack_state(state)
            value = _cache.get(key)
            if value is None:
                value = int(admissible_remaining(state))
                _cache[key] = value
            return value

    def identity(state: SpiderState) -> bytes:
        return milestone_identity(state, column=spec.column)

    def order(state: SpiderState, actions: List[Action]) -> List[Action]:
        return rank_milestone_actions(state, actions, suit, column=spec.column)

    def keys(state: SpiderState, g: int) -> Dict[str, tuple]:
        return _lane_keys(state, g, suit, spec.column)

    kernel = run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": g0}],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=cost_ceiling,
            max_depth=int(max_depth),
            proof_ceiling=None if proof_ceiling is None else int(proof_ceiling),
        ),
        identity_fn=identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("progress", "setup"),
        lane_keys_fn=keys,
        is_terminal=is_goal,
        actions_fn=tableau_actions,
        action_order=order,
        on_child=on_child,
        lower_bound_fn=bound,
        stop_on_first_terminal=bool(stop_on_first),
    )
    hits = _verify_hits(source, spec, kernel, g0, limit=int(hit_limit))
    best = hits[0] if hits else None
    if best is None or not best.replay_ok or best.state is None:
        met = False
    elif terminal_fn is not None:
        met = bool(terminal_fn(best.state))
    else:
        met = milestone_met(best.state, spec)
    return MilestoneResult(
        met=bool(met),
        replay_ok=bool(best.replay_ok) if best is not None else False,
        stop_reason=str(kernel.stop_reason),
        outcome="milestone" if met else "not_met",
        suit=suit,
        g0=g0,
        g=None if best is None or not met else int(best.g),
        paid=0 if best is None or not met else int(best.paid),
        zero_cost=0 if best is None or not met else int(best.zero_cost),
        actions=() if best is None or not met else tuple(best.actions),
        suit_before=spec.source_foundations,
        suit_after=spec.source_foundations if best is None else spec.source_foundations + int(best.suit_gain),
        face_down_before=spec.source_face_down,
        face_down_after=None if best is None else spec.source_face_down - int(best.face_down_drop),
        pack="" if best is None or not met else best.pack,
        column_specific=spec.column_specific,
        proof_ceiling=None if proof_ceiling is None else int(proof_ceiling),
        cost_ceiling=cost_ceiling,
        max_depth=int(max_depth),
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
        unique=int(kernel.unique),
        expanded=int(kernel.expanded),
        generated=int(kernel.generated),
        elapsed_s=float(kernel.elapsed_s),
        peak_rss_mb=kernel.peak_rss_mb,
        lower_bound_prunes=int(kernel.lower_bound_prunes),
        proof_prune_identities=int(kernel.proof_prune_identities),
        ceiling_prunes=int(kernel.ceiling_prunes),
        depth_skips=int(kernel.depth_skips),
        zero_cost_actions=int(kernel.zero_cost_actions),
        min_f=kernel.min_f,
        min_h=kernel.min_h,
        max_h=kernel.max_h,
        lane_exp=tuple(sorted(kernel.lane_exp.items())),
        diagnostics=diagnostics,
        hits=tuple(hits if met or terminal_fn is None else hits),
    )


def _verify_hits(source, spec: MilestoneSpec, kernel, g0: int, *, limit: int) -> List[MilestoneHit]:
    ordered = sorted(kernel.terminals, key=lambda item: (int(item["g"]), int(item["node"])))
    hits: List[MilestoneHit] = []
    seen = set()
    for item in ordered:
        if len(hits) >= int(limit):
            break
        node_i = int(item["node"])
        actions = tuple(kernel.reconstruct(node_i))
        key = (actions, int(item["g"]))
        if key in seen:
            continue
        seen.add(key)
        try:
            final, spent, zeros = _replay(source, actions)
        except (ValueError, MilestoneContractError):
            continue
        if g0 + spent != int(item["g"]) or pack_state(final).hex() != item["store"]:
            continue
        gain = suit_foundation_count(final, spec.suit) - spec.source_foundations
        drop = spec.source_face_down - face_down_count(final)
        hits.append(
            MilestoneHit(
                actions=actions,
                g=int(item["g"]),
                paid=int(spent),
                zero_cost=int(zeros),
                suit_gain=int(gain),
                face_down_drop=int(drop),
                pack=pack_state(final).hex(),
                symmetry=pack_whole_game_identity(final).hex(),
                replay_ok=True,
                state=final,
            )
        )
    return hits


def retain_endpoints(
    items: Sequence[MilestoneEndpoint],
    *,
    ceiling: int = ENDPOINT_CEILING,
    limit: int = ENDPOINT_LIMIT,
) -> Tuple[List[MilestoneEndpoint], List[dict]]:
    """Keep at most ``limit`` states with ``g + h <= ceiling``.

    Symmetry duplicates keep the cheaper physical prefix and that prefix's
    root. A tactical cap is not applied here.
    """

    eligible = [
        item
        for item in items
        if item.replay_ok
        and int(item.suit_gain) >= 1
        and int(item.face_down_drop) >= 1
        and int(item.f) <= int(ceiling)
    ]
    eligible.sort(key=lambda item: (int(item.g), item.pack))
    winners: Dict[str, MilestoneEndpoint] = {}
    dominated: List[dict] = []
    for item in eligible:
        previous = winners.get(item.symmetry)
        if previous is None:
            winners[item.symmetry] = item
            continue
        dominated.append(_dominance_row(item, previous))
    pool = sorted(winners.values(), key=lambda item: (int(item.g), int(item.f), int(item.root_index), item.pack))
    chosen: List[MilestoneEndpoint] = []
    seen_roots = set()
    for item in pool:
        if item.root_index in seen_roots:
            continue
        chosen.append(item)
        seen_roots.add(item.root_index)
        if len(chosen) >= int(limit):
            return chosen, dominated
    for item in pool:
        if item in chosen:
            continue
        chosen.append(item)
        if len(chosen) >= int(limit):
            break
    return chosen, dominated


def _dominance_row(dropped: MilestoneEndpoint, kept: MilestoneEndpoint) -> dict:
    return {
        "reason": "symmetry-dominated",
        "dropped_g": dropped.g,
        "kept_g": kept.g,
        "dropped_root": dropped.root_index,
        "kept_root": kept.root_index,
        "dropped_pack": dropped.pack,
        "kept_pack": kept.pack,
        "dropped_macro": [format_action(action) for action in dropped.pre_deal_macro],
        "kept_macro": [format_action(action) for action in kept.pre_deal_macro],
        "dropped_tactical": [format_action(action) for action in dropped.actions],
        "kept_tactical": [format_action(action) for action in kept.actions],
    }


def as_continuation_roots(endpoints: Sequence[MilestoneEndpoint]) -> List[PostDealRoot]:
    """Physical milestone states. The macro is only the pre-deal prefix."""

    roots = []
    for item in endpoints:
        roots.append(
            PostDealRoot(
                state=item.state,
                g=int(item.g),
                macro=tuple(item.pre_deal_macro),
                h=int(item.h),
                f=int(item.f),
                purpose="post-deal club milestone",
                pack=item.pack,
                symmetry=item.symmetry,
            )
        )
    return roots


def route_for_endpoint(
    canonical_actions: Sequence[Action],
    endpoint: MilestoneEndpoint,
    continuation: Sequence[Action] = (),
    suffix: Sequence[Action] = (),
) -> List[Action]:
    """Checkpoint-140 prefix, that root's pre-deal macro, the deal, then tactics.

    The tactical actions and any later continuation stay on this endpoint.
    Another root's macro is not substituted.
    """

    return compose_discovered_route(
        canonical_actions,
        endpoint.pre_deal_macro,
        list(endpoint.actions) + list(continuation),
        suffix,
    )
