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

import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.human_strategy.evaluation import (
    admissible_remaining,
    mixed_boundaries,
    same_suit_bonds,
)
from spider.metrics import Action, format_action
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.planner.strategic_objectives import evaluate_target
from spider.purposeful_macro import PostDealRoot, compose_discovered_route
from spider.research_actions import (
    apply_action,
    capture_state,
    face_down_count,
    is_deal,
    restore_state,
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
# How many terminals the lower-f policy replays before it selects. A cap is
# truncation, not a claim that an unverified terminal has a worse bound.
PHASE_VERIFY_CAP = 128
SCREEN_SLACK = 1

_SUITS = ("s", "h", "d", "c")
_PHASES = ("both_not_yet", "foundation_only", "reveal_only", "both_achieved")


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
    h: Optional[int] = None
    f: Optional[int] = None

    def public(self) -> dict:
        return {
            "actions": [format_action(action) for action in self.actions],
            "g": self.g,
            "h": self.h,
            "f": self.f,
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
    phase_aware: bool = False
    hit_policy: str = "lowest_g"
    phases_admitted: Dict[str, int] = field(default_factory=dict)
    phases_expanded: Dict[str, int] = field(default_factory=dict)
    first_s: Optional[float] = None
    first_g: Optional[int] = None
    distinct_milestones: int = 0
    queued_entries: int = 0
    hit_truncation: Optional[dict] = None
    cpu_s: float = 0.0
    lower_bound_s: float = 0.0

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
            "phase_aware": self.phase_aware,
            "hit_policy": self.hit_policy,
            "phases_admitted": dict(self.phases_admitted),
            "phases_expanded": dict(self.phases_expanded),
            "first_s": None if self.first_s is None else round(self.first_s, 6),
            "first_g": self.first_g,
            "distinct_milestones": self.distinct_milestones,
            "queued_entries": self.queued_entries,
            "hit_truncation": self.hit_truncation,
            "cpu_s": round(self.cpu_s, 6),
            "lower_bound_s": round(self.lower_bound_s, 6),
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


def objective_status(state: SpiderState, spec: MilestoneSpec) -> Tuple[bool, bool]:
    """Foundation done, reveal done. Both are read from the state and the source."""

    founded = suit_foundation_count(state, spec.suit) >= int(spec.source_foundations) + 1
    if spec.column is None:
        revealed = face_down_count(state) <= int(spec.source_face_down) - 1
    else:
        revealed = bool(
            evaluate_target(
                state,
                "column_face_down_le",
                {"column": int(spec.column), "max_face_down": int(spec.max_face_down)},
            )
        )
    return founded, revealed


def phase_name(founded: bool, revealed: bool) -> str:
    if founded and revealed:
        return "both_achieved"
    if founded:
        return "foundation_only"
    if revealed:
        return "reveal_only"
    return "both_not_yet"


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
    phase_aware: bool = False,
    founded: bool = False,
    revealed: bool = False,
) -> List[Action]:
    """Order every tableau action. None are removed.

    A move that extends the longest run of ``suit``, uncovers that run's
    next card, or reveals a face-down card comes first. Cost breaks the
    remaining ties, so a zero-cost relocation is kept. ``phase_aware``
    puts the unfinished half of the objective first. It does not drop moves.
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
        if not phase_aware:
            return (extends, uncovers, reveal, frees, cost, same, index)
        if founded and not revealed:
            return (reveal, uncovers, extends, frees, cost, same, index)
        if revealed and not founded:
            return (extends, uncovers, same, reveal, frees, cost, index)
        either = 0 if extends == 0 or reveal == 0 or uncovers == 0 else 1
        return (either, extends, reveal, uncovers, frees, cost, same, index)

    ordered = [action for _index, action in sorted(enumerate(actions), key=rank)]
    if len(ordered) != len(list(actions)):
        raise MilestoneContractError("milestone ordering dropped a legal action")
    return ordered


def _lane_keys(
    state: SpiderState,
    g: int,
    suit: str,
    column: Optional[int],
    *,
    phase_aware: bool = False,
) -> Dict[str, tuple]:
    features = _measure(state, suit)
    # A named column is ordering only. Clearing it stays ahead of a run that
    # does not land on that column. The suit-wide search does not use it.
    if phase_aware:
        # Two objective lanes plus the setup lane. Round-robin gives a
        # reveal-only state a turn even when a foundation-only state leads
        # the foundation lane. These tuples are not lower bounds.
        foundation_key: tuple = (
            -features.foundations,
            -features.run,
            features.next_depth,
            features.home_depth,
            int(g),
        )
        reveal_key: tuple = (
            features.face_down,
            features.next_depth,
            features.home_depth,
            -features.run,
            int(g),
        )
        if column is not None:
            focus = len(state.columns[int(column)].face_up)
            foundation_key = foundation_key + (focus,)
            reveal_key = reveal_key + (focus,)
        setup_key = _setup_key(features, g, state, column)
        return {"foundation": foundation_key, "reveal": reveal_key, "setup": setup_key}
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
    return {"progress": progress, "setup": _setup_key(features, g, state, column)}


def _setup_key(features: _Features, g: int, state: SpiderState, column: Optional[int]) -> tuple:
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
    return tuple(setup)


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
    phase_aware: bool = False,
    hit_policy: str = "lowest_g",
) -> MilestoneResult:
    """Search from one physical source. Reference actions are not an input.

    ``phase_aware`` is opt-in. The default lanes and action order stay the
    historical ones. ``hit_policy="lower_f"`` is a separate selection rule:
    it keeps lower admissible ``f`` ahead of lower ``g``. Neither value is
    a proof bound.
    """

    spec = spec_from_source(source, suit, column=column, max_face_down=max_face_down)
    g0 = int(g0)
    cost_ceiling = g0 + int(paid_moves)
    policy = str(hit_policy)
    if policy not in {"lowest_g", "lower_f"}:
        raise MilestoneContractError(f"unknown hit policy: {policy}")
    diagnostics = {
        "max_suit_foundations": spec.source_foundations,
        "min_face_down": spec.source_face_down,
        "foundation_without_reveal": 0,
        "reveal_without_foundation": 0,
    }
    phases = {
        "admitted": {name: 0 for name in _PHASES},
        "expanded": {name: 0 for name in _PHASES},
    }

    def note(bucket: str, state: SpiderState) -> None:
        founded, revealed = objective_status(state, spec)
        phases[bucket][phase_name(founded, revealed)] += 1

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
        note("admitted", state)

    def on_expand(state: SpiderState, _g: int, _node_i: int) -> None:
        note("expanded", state)

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
        founded, revealed = objective_status(state, spec)
        return rank_milestone_actions(
            state,
            actions,
            suit,
            column=spec.column,
            phase_aware=bool(phase_aware),
            founded=founded,
            revealed=revealed,
        )

    def keys(state: SpiderState, g: int) -> Dict[str, tuple]:
        return _lane_keys(state, g, suit, spec.column, phase_aware=bool(phase_aware))

    names = ("foundation", "reveal", "setup") if phase_aware else ("progress", "setup")
    cpu_started = time.process_time()
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
        lane_names=names,
        lane_keys_fn=keys,
        is_terminal=is_goal,
        actions_fn=tableau_actions,
        action_order=order,
        on_child=on_child,
        on_expand=on_expand,
        lower_bound_fn=bound,
        stop_on_first_terminal=bool(stop_on_first),
    )
    cpu_s = time.process_time() - cpu_started
    verify_limit = int(hit_limit) if policy == "lowest_g" else max(int(hit_limit), PHASE_VERIFY_CAP)
    verified = _verify_hits(source, spec, kernel, g0, limit=verify_limit)
    if policy == "lowest_g":
        hits = verified
        truncation = {
            "policy": "lowest_g",
            "verified": len(verified),
            "terminals": len(kernel.terminals),
            "retained": min(len(verified), int(hit_limit)),
            "reason": "lowest g then node index",
            "unverified_terminals": max(0, len(kernel.terminals) - len(verified)),
        }
    else:
        hits, truncation = choose_milestone_hits(
            verified,
            policy="lower_f",
            limit=int(hit_limit),
            require_both=terminal_fn is None,
        )
        truncation["terminals"] = len(kernel.terminals)
        truncation["unverified_terminals"] = max(0, len(kernel.terminals) - len(verified))
        if truncation["unverified_terminals"]:
            truncation["reason"] += (
                "; unverified terminals were not shown to have a worse f"
            )
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
        hits=tuple(hits),
        phase_aware=bool(phase_aware),
        hit_policy=policy,
        phases_admitted=dict(phases["admitted"]),
        phases_expanded=dict(phases["expanded"]),
        first_s=kernel.first_s,
        first_g=kernel.first_g,
        distinct_milestones=len({hit.symmetry for hit in hits if hit.suit_gain >= 1 and hit.face_down_drop >= 1}),
        queued_entries=sum(int(value) for value in kernel.lane_remaining.values()),
        hit_truncation=truncation,
        cpu_s=float(cpu_s),
        lower_bound_s=float(kernel.lower_bound_s),
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


def choose_milestone_hits(
    hits: Sequence[MilestoneHit],
    *,
    policy: str = "lowest_g",
    limit: int = 8,
    require_both: bool = True,
) -> Tuple[List[MilestoneHit], dict]:
    """Pick retained hits. ``lower_f`` is selection, not a lane-order change.

    ``f`` is an admissible lower bound. Keeping a lower ``f`` does not prove
    that state can be finished, and dropping a higher ``f`` does not prove it
    cannot.
    """

    if policy not in {"lowest_g", "lower_f"}:
        raise MilestoneContractError(f"unknown hit policy: {policy}")
    if policy == "lowest_g":
        ordered_g = sorted(hits, key=lambda hit: (int(hit.g), hit.pack))
        kept = ordered_g[: int(limit)]
        return kept, {
            "policy": "lowest_g",
            "verified": len(hits),
            "retained": len(kept),
            "dropped_complete": max(0, len(hits) - len(kept)),
            "reason": "lowest g",
        }
    pool: List[MilestoneHit] = []
    for hit in hits:
        if require_both and (int(hit.suit_gain) < 1 or int(hit.face_down_drop) < 1):
            continue
        if hit.f is None and hit.state is not None:
            hit.h = int(admissible_remaining(hit.state))
            hit.f = int(hit.g) + int(hit.h)
        pool.append(hit)
    pool.sort(key=lambda hit: (int(hit.f if hit.f is not None else 10**9), int(hit.g), hit.pack))
    winners: Dict[str, MilestoneHit] = {}
    dominated = 0
    for hit in pool:
        if hit.symmetry not in winners:
            winners[hit.symmetry] = hit
        else:
            dominated += 1
    ordered = sorted(
        winners.values(),
        key=lambda hit: (int(hit.f if hit.f is not None else 10**9), int(hit.g), hit.pack),
    )
    kept = ordered[: int(limit)]
    reason = "lowest f, then g; one prefix per symmetry"
    if dominated:
        reason += f"; {dominated} symmetry duplicates kept the lower f"
    if len(ordered) > int(limit):
        reason += f"; truncated {len(ordered) - int(limit)} higher-f states"
    return kept, {
        "policy": "lower_f",
        "verified": len(hits),
        "retained": len(kept),
        "dropped_complete": len(ordered) - len(kept),
        "symmetry_dominated": dominated,
        "reason": reason,
    }


def retain_endpoints(
    items: Sequence[MilestoneEndpoint],
    *,
    ceiling: int = ENDPOINT_CEILING,
    limit: int = ENDPOINT_LIMIT,
    order: str = "g",
) -> Tuple[List[MilestoneEndpoint], List[dict]]:
    """Keep at most ``limit`` states with ``g + h <= ceiling``.

    Symmetry duplicates keep the cheaper physical prefix and that prefix's
    root. ``order="g"`` is the historical rule. ``order="f"`` keeps a lower
    admissible bound ahead of a lower ``g``. A tactical cap is not applied
    here, and neither order is a proof.
    """

    if order not in {"g", "f"}:
        raise MilestoneContractError(f"unknown endpoint order: {order}")

    def sort_key(item: MilestoneEndpoint) -> tuple:
        if order == "f":
            return (int(item.f), int(item.g), item.pack)
        return (int(item.g), item.pack)

    eligible = [
        item
        for item in items
        if item.replay_ok
        and int(item.suit_gain) >= 1
        and int(item.face_down_drop) >= 1
        and int(item.f) <= int(ceiling)
    ]
    eligible.sort(key=sort_key)
    winners: Dict[str, MilestoneEndpoint] = {}
    dominated: List[dict] = []
    for item in eligible:
        previous = winners.get(item.symmetry)
        if previous is None:
            winners[item.symmetry] = item
            continue
        dominated.append(_dominance_row(item, previous))
    pool = sorted(winners.values(), key=lambda item: sort_key(item) + (int(item.root_index),))
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


def describe_position(state: SpiderState, g: int) -> dict:
    """Observable tableau facts at one corrected cost. ``h`` is recomputed."""

    hidden_bound = int(admissible_remaining(state))
    suits = [seq[0].suit if seq else "" for seq in state.foundations]
    symmetry = "" if state.stock else pack_whole_game_identity(state).hex()
    return {
        "g": int(g),
        "h": hidden_bound,
        "f": int(g) + hidden_bound,
        "pack": pack_state(state).hex(),
        "symmetry": symmetry,
        "bonds": int(same_suit_bonds(state)),
        "mixed_joins": int(mixed_boundaries(state)),
        "open_columns": sum(1 for column in state.columns if column.is_empty()),
        "mobility": len(tableau_actions(state)),
        "face_down": int(face_down_count(state)),
        "foundations": len(state.foundations),
        "foundation_suits": suits,
        "stock": len(state.stock),
    }


def has_proof_eligible_child(state: SpiderState, g: int, ceiling: int) -> bool:
    """True when some legal child still has ``g + h <= ceiling``.

    Equality stays eligible. This looks at one ply. It is not a search and
    it does not prove a longer line.
    """

    for action in tableau_actions(state):
        child_g = int(g) + int(step_cost(state, action))
        snap = capture_state(state, action)
        try:
            apply_action(state, action)
            if child_g + int(admissible_remaining(state)) <= int(ceiling):
                return True
        except ValueError:
            continue
        finally:
            restore_state(state, snap)
    return False


def screening_milestone(
    endpoint: MilestoneEndpoint,
    *,
    ceiling: int = ENDPOINT_CEILING,
    excluded_packs: Sequence[str] = (),
) -> dict:
    """Whether a milestone is worth a new continuation.

    ``f <= ceiling - 1`` is a screen for this experiment. It is not a proof
    that the state can be finished, and failing the screen is not a proof
    that no other state can.
    """

    screen = int(ceiling) - int(SCREEN_SLACK)
    reasons: List[str] = []
    if endpoint.pack in set(excluded_packs):
        reasons.append("previously exhausted identity")
    if int(endpoint.f) > screen:
        reasons.append("f above screen")
    if not endpoint.replay_ok or int(endpoint.suit_gain) < 1 or int(endpoint.face_down_drop) < 1:
        reasons.append("not a verified two-part milestone")
    affordable = False
    if not reasons:
        affordable = has_proof_eligible_child(endpoint.state, int(endpoint.g), int(ceiling))
        if not affordable:
            reasons.append("no proof-eligible successor")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "screen_f": screen,
        "proof": False,
        "affordable_successor": affordable,
        "f": int(endpoint.f),
        "g": int(endpoint.g),
        "h": int(endpoint.h),
        "pack": endpoint.pack,
        "root_index": int(endpoint.root_index),
    }
