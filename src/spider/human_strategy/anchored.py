"""Checkpoint optimisation of a verified complete route.

Fixed mode replaces one segment with a cheaper path to that same later
checkpoint. Adaptive mode searches from one checkpoint toward several later
checkpoints at once and keeps the incumbent suffix after the exact rejoin.
A full-game replay has to succeed before the stored route changes. Cold and
solve modes do not call this module.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.metrics import Action, format_action, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.planner.space_lifecycle import empty_count
from spider.research_actions import all_legal_actions, apply_action, face_down_count, rss_mb, step_cost
from spider.search_kernel import SearchLimits, run_search
from spider.state_identity import CanonicalStateKey, canonical_state_key

from .evaluation import admissible_remaining, same_suit_bonds
from .incumbent import IncumbentRejected, verify_complete_solution


# A segment lower bound at or above this value means the target checkpoint
# cannot be reached. It is not a whole-game finishing bound.
_UNREACHABLE = 10**6


class AnchoredRefused(ValueError):
    """Anchored search was asked for from a mode that must stay independent."""


@dataclass(frozen=True)
class Checkpoint:
    """One position on a replayed complete route.

    ``index`` is the number of incumbent actions already applied. ``state``
    is a private clone. Callers compare checkpoints with ``states_rejoin``.
    """

    index: int
    g: int
    stock_cards: int
    stock_rows: int
    foundations: int
    face_down: int
    empty_columns: int
    bonds: int
    admissible_remaining: int
    state_id: str
    state: SpiderState = field(compare=False, repr=False)
    key: CanonicalStateKey = field(compare=False, repr=False)

    def public(self) -> dict:
        return {
            "index": self.index,
            "g": self.g,
            "stock_cards": self.stock_cards,
            "stock_rows": self.stock_rows,
            "foundations": self.foundations,
            "face_down": self.face_down,
            "empty_columns": self.empty_columns,
            "bonds": self.bonds,
            "admissible_remaining": self.admissible_remaining,
            "state_id": self.state_id,
        }


@dataclass(frozen=True)
class Window:
    start: int
    end: int
    cost: int
    kind: str
    budget_class: str


@dataclass
class SegmentResult:
    status: str
    actions: Tuple[Action, ...]
    cost: Optional[int]
    ceiling: int
    expanded: int = 0
    unique: int = 0
    generated: int = 0
    duplicate_skips: int = 0
    lower_bound_prunes: int = 0
    elapsed_s: float = 0.0
    stop_reason: str = ""
    proof: bool = False
    target_index: Optional[int] = None
    targets_considered: int = 0
    targets_touched: int = 0
    reused: bool = False


@dataclass(frozen=True)
class AdaptiveRegion:
    """One source checkpoint and the later checkpoints a single search may rejoin."""

    start: int
    targets: Tuple[int, ...]
    kind: str
    budget_class: str
    reason: str


# v0.118 left these fixed windows unfinished at the 2,500-state cap.
# Adaptive search tries to cover them as targets. It does not raise that cap.
_KNOWN_INCONCLUSIVE = (65, 168, 177, 183)


@dataclass
class AnchorReport:
    status: str
    mode: str
    actions: Tuple[Action, ...]
    cumulative_g: int
    solved: bool
    elapsed_s: float
    peak_rss_mb: Optional[float]
    provenance: dict
    replay: dict
    windows: List[dict] = field(default_factory=list)
    improvements: List[dict] = field(default_factory=list)
    checkpoints: List[dict] = field(default_factory=list)
    objectives_attempted: int = 0
    unique_states: int = 0
    decisions: tuple = ()

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "mode": self.mode,
            "actions": [format_action(action) for action in self.actions],
            "cumulative_g": self.cumulative_g,
            "solved": self.solved,
            "elapsed_s": round(self.elapsed_s, 3),
            "peak_rss_mb": self.peak_rss_mb,
            "provenance": self.provenance,
            "replay": self.replay,
            "windows": self.windows,
            "improvements": self.improvements,
            "checkpoints": self.checkpoints,
            "objectives_attempted": len(self.windows),
            "foundations": 8 if self.solved else None,
            "decisions": [],
        }


def states_rejoin(left: SpiderState, right: SpiderState) -> bool:
    """Exact column-ordered identity.

    Physical column index is part of the key because an incumbent suffix
    names columns by index. Foundation sequences are a multiset. Stock order
    is the deal order. ``pack_post_stock_symmetry_state`` is not used.
    Duplicate suit-rank copies are not distinct objects in this key.
    """

    return canonical_state_key(left) == canonical_state_key(right)


def segment_lower_bound(state: SpiderState, target: SpiderState) -> Optional[int]:
    """Admissible corrected-MW cost to reach ``target``, or None if impossible.

    The only positive term is the exact number of stock deals required to
    leave the target stock. Foundation growth and face-down reveals are not
    added: one action can complete a foundation and reveal more than one
    card, and a whole-column transfer can cost nothing. Those obligations
    overlap, so a sum of them would not be admissible.
    """

    if not _foundations_can_grow(state, target):
        return None
    deals = _required_deals(state, target)
    if deals is None:
        return None
    return deals


def build_checkpoints(opening: SpiderState, actions: Sequence[Action]) -> Tuple[Checkpoint, ...]:
    """Replay ``actions`` and record the state before every action and at the end.

    The caller's opening is not mutated. Costs are the corrected MobilityWare
    values returned by the engine.
    """

    working = opening.clone()
    checkpoints = [_make_checkpoint(0, working, 0)]
    spent = 0
    for action in actions:
        spent += int(apply_action(working, action))
        checkpoints.append(_make_checkpoint(len(checkpoints), working, spent))
    return tuple(checkpoints)


def select_windows(
    checkpoints: Sequence[Checkpoint],
    actions: Sequence[Action],
    *,
    max_span: int = 8,
    max_windows: int = 16,
) -> Tuple[Window, ...]:
    """Order short, high-cost, low-change segments ahead of longer ones.

    An exact return to an earlier checkpoint is first. It needs no search.
    Other windows are a screen, not a proof that skipped segments are optimal.
    """

    cycles: List[Window] = []
    earliest = {}
    for checkpoint in checkpoints:
        previous = earliest.get(checkpoint.key)
        if previous is not None and checkpoint.g > checkpoints[previous].g:
            cycles.append(
                Window(
                    start=previous,
                    end=checkpoint.index,
                    cost=checkpoint.g - checkpoints[previous].g,
                    kind="exact_cycle",
                    budget_class="short",
                )
            )
        else:
            earliest.setdefault(checkpoint.key, checkpoint.index)
    cycles.sort(key=lambda item: (item.end - item.start, -item.cost, item.start))

    screened: List[Window] = []
    span_limit = max(2, int(max_span))
    for span in range(2, span_limit + 1):
        for start in range(0, len(checkpoints) - span):
            end = start + span
            cost = checkpoints[end].g - checkpoints[start].g
            if cost < 1:
                continue
            if checkpoints[start].key == checkpoints[end].key:
                continue
            kind = _window_kind(checkpoints, actions, start, end)
            if kind is None:
                continue
            screened.append(Window(start=start, end=end, cost=cost, kind=kind, budget_class="short"))

    reversals = [item for item in screened if item.kind == "reversal"]
    reversals.sort(key=lambda item: (item.end - item.start, -item.cost, item.start))
    others = [item for item in screened if item.kind != "reversal"]
    others.sort(key=lambda item: (item.end - item.start, -item.cost, item.start))
    medium = _between_foundations(checkpoints, max_span=span_limit)
    # Reserve reversal and endgame slots. Overlapping span-2 pairs would
    # otherwise fill the whole budget at the start of the route.
    chosen: List[Window] = []
    seen = set()

    def _take(window: Window) -> None:
        token = (window.start, window.end)
        if token in seen or len(chosen) >= int(max_windows):
            return
        seen.add(token)
        budget = "medium" if window.kind == "between_foundations" or window.cost >= 4 else "short"
        chosen.append(
            Window(window.start, window.end, window.cost, window.kind, budget)
        )

    for window in cycles:
        _take(window)
    for window in _nonoverlapping(reversals, limit=6):
        _take(window)
    for window in medium:
        _take(window)
    for window in _nonoverlapping(others, limit=int(max_windows)):
        _take(window)
    return tuple(chosen)


def search_segment(
    source: SpiderState,
    target: SpiderState,
    ceiling: int,
    *,
    time_limit_s: float = 2.0,
    max_unique: int = 2500,
    rss_abort_mb: float = 3072.0,
    exhaustive: bool = False,
) -> SegmentResult:
    """Best-first corrected-MW search for a path cheaper than ``ceiling``.

    ``ceiling`` is the incumbent segment cost. A path that has spent that
    much cannot be a strict improvement, so the kernel ceiling is one less.
    Zero-cost whole-column transfers stay in the graph. A time, memory, or
    unique-state stop is inconclusive. Completing the graph without a hit
    is a negative result only inside this cost ceiling.
    """

    ceiling = int(ceiling)
    if states_rejoin(source, target):
        if ceiling <= 0:
            return SegmentResult("NOT_CHEAPER", (), 0, ceiling, stop_reason="already there", proof=True)
        return SegmentResult("FOUND", (), 0, ceiling, stop_reason="empty rejoin", proof=True)
    bound = segment_lower_bound(source, target)
    if bound is None or bound >= ceiling:
        return SegmentResult(
            "IMPOSSIBLE" if bound is None else "NOT_CHEAPER",
            (),
            None,
            ceiling,
            lower_bound_prunes=1,
            stop_reason="segment bound",
            proof=True,
        )
    if time_limit_s <= 0 or max_unique <= 0:
        return SegmentResult(
            "INCONCLUSIVE",
            (),
            None,
            ceiling,
            stop_reason="resource limit",
            proof=False,
        )
    target_key = canonical_state_key(target)
    target_pack = pack_state(target)

    def _bound(state: SpiderState, _g: int) -> int:
        value = segment_lower_bound(state, target)
        if value is None:
            return _UNREACHABLE
        return int(value)

    def _terminal(state: SpiderState) -> bool:
        return pack_state(state) == target_pack and canonical_state_key(state) == target_key

    def _order(state: SpiderState, actions: List[Action]) -> List[Action]:
        return sorted(actions, key=lambda action: (step_cost(state, action), str(action)))

    started = time.perf_counter()
    kernel = run_search(
        [
            {
                "ordered_digest": pack_state(source).hex(),
                "g": 0,
            }
        ],
        limits=SearchLimits(
            max_unique=int(max_unique),
            time_limit_s=float(time_limit_s),
            rss_abort_mb=float(rss_abort_mb),
            cost_ceiling=ceiling - 1,
        ),
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=_terminal,
        actions_fn=all_legal_actions,
        action_order=_order,
        lower_bound_fn=_bound,
        stop_on_first_terminal=not exhaustive,
    )
    elapsed = time.perf_counter() - started
    common = dict(
        ceiling=ceiling,
        expanded=int(kernel.expanded),
        unique=int(kernel.unique),
        generated=int(kernel.generated),
        duplicate_skips=int(kernel.duplicate_skips),
        lower_bound_prunes=int(kernel.lower_bound_prunes),
        elapsed_s=elapsed,
        stop_reason=kernel.stop_reason,
    )
    if kernel.terminals:
        best = min(kernel.terminals, key=lambda item: int(item["g"]))
        actions = tuple(kernel.reconstruct(int(best["node"])))
        cost = int(best["g"])
        if cost >= ceiling or not _replays_to(source, actions, target, cost):
            return SegmentResult("NOT_CHEAPER", (), None, proof=False, **common)
        return SegmentResult("FOUND", actions, cost, proof=True, **common)
    inconclusive = kernel.stop_reason in {"time limit", "unique limit", "rss abort", "abort"}
    status = "INCONCLUSIVE" if inconclusive else "EXHAUSTED"
    return SegmentResult(status, (), None, proof=not inconclusive, **common)


def search_targets(
    source: SpiderState,
    targets: Sequence[Tuple[SpiderState, int, int]],
    *,
    time_limit_s: float = 2.0,
    max_unique: int = 2500,
    rss_abort_mb: float = 3072.0,
    memo: Optional[dict] = None,
) -> SegmentResult:
    """Best-first search from ``source`` toward several later checkpoints.

    Each target is ``(state, original_cost, index)``. The kernel ceiling is
    one below the largest original cost, so a branch that can no longer
    improve an early checkpoint can still improve a later one. A node is
    pruned only when every remaining target is unreachable or already at
    least as expensive as its own original cost. Zero-cost transfers stay
    in the graph. An equal-cost return to a state already reached is not
    expanded again.

    An exhausted graph is negative only for this target set and this
    ceiling. It is not a proof that the incumbent segment is optimal.
    """

    specs = [(state, int(cost), int(index)) for state, cost, index in targets if int(cost) > 0]
    ceiling = max((cost for _state, cost, _index in specs), default=0)
    common_base = dict(ceiling=ceiling, targets_considered=len(specs))
    if not specs:
        return SegmentResult(
            "NOT_CHEAPER", (), None, stop_reason="no eligible target", proof=True, **common_base
        )
    immediate = [
        (state, cost, index)
        for state, cost, index in specs
        if states_rejoin(source, state)
    ]
    if immediate:
        _state, cost, index = max(immediate, key=lambda item: (item[1], -item[2]))
        return SegmentResult(
            "FOUND",
            (),
            0,
            stop_reason="empty rejoin",
            proof=True,
            target_index=index,
            **common_base,
        )
    eligible = []
    impossible = 0
    dominated = 0
    for state, cost, index in specs:
        bound = segment_lower_bound(source, state)
        if bound is None:
            impossible += 1
            continue
        if bound >= cost:
            dominated += 1
            continue
        eligible.append((state, cost, index))
    if not eligible:
        status = "IMPOSSIBLE" if impossible and not dominated else "NOT_CHEAPER"
        return SegmentResult(
            status,
            (),
            None,
            lower_bound_prunes=impossible + dominated,
            stop_reason="segment bound",
            proof=True,
            **common_base,
        )
    if time_limit_s <= 0 or max_unique <= 0:
        return SegmentResult(
            "INCONCLUSIVE",
            (),
            None,
            stop_reason="resource limit",
            proof=False,
            **common_base,
        )
    ceiling = max(cost for _state, cost, _index in eligible)
    packed = []
    by_pack: dict = {}
    for state, cost, index in eligible:
        token = pack_state(state)
        key = canonical_state_key(state)
        packed.append((state, cost, index, token, key))
        by_pack.setdefault(token, []).append((index, cost, key, state))
    memo_key = (
        pack_state(source),
        tuple((token, cost, index) for _state, cost, index, token, _key in packed),
        ceiling,
    )
    if memo is not None:
        stored = memo.setdefault("results", {})
        if memo_key in stored:
            memo["hits"] = int(memo.get("hits", 0)) + 1
            previous = stored[memo_key]
            return SegmentResult(
                previous.status,
                previous.actions,
                previous.cost,
                ceiling=ceiling,
                expanded=0,
                unique=previous.unique,
                generated=0,
                duplicate_skips=previous.duplicate_skips,
                lower_bound_prunes=previous.lower_bound_prunes,
                elapsed_s=0.0,
                stop_reason="reused",
                proof=previous.proof,
                target_index=previous.target_index,
                targets_considered=len(specs),
                targets_touched=previous.targets_touched,
                reused=True,
            )
        memo["misses"] = int(memo.get("misses", 0)) + 1

    def _bound(state: SpiderState, g: int) -> int:
        best = None
        for target, original, _index, _token, _key in packed:
            deal_bound = segment_lower_bound(state, target)
            if deal_bound is None or g + int(deal_bound) >= original:
                continue
            if best is None or deal_bound < best:
                best = int(deal_bound)
        if best is None:
            return _UNREACHABLE
        return best

    def _matches(state: SpiderState):
        group = by_pack.get(pack_state(state))
        if not group:
            return None
        key = canonical_state_key(state)
        return [item for item in group if item[2] == key]

    limits = SearchLimits(
        max_unique=int(max_unique),
        time_limit_s=float(time_limit_s),
        rss_abort_mb=float(rss_abort_mb),
        cost_ceiling=ceiling - 1,
    )

    def _on_child(state: SpiderState, g: int, _node: int) -> None:
        group = _matches(state)
        if group and any(int(g) < original for _index, original, _key, _target in group):
            # The improving state is already stored. Stop before the next new one.
            limits.max_unique = 0

    def _terminal(state: SpiderState) -> bool:
        return _matches(state) is not None

    def _order(state: SpiderState, actions: List[Action]) -> List[Action]:
        return sorted(actions, key=lambda action: (step_cost(state, action), str(action)))

    started = time.perf_counter()
    kernel = run_search(
        [{"ordered_digest": pack_state(source).hex(), "g": 0}],
        limits=limits,
        identity_fn=pack_state,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_key_fns=(lambda _state, g: (int(g),),),
        is_terminal=_terminal,
        actions_fn=all_legal_actions,
        action_order=_order,
        lower_bound_fn=_bound,
        on_child=_on_child,
        stop_on_first_terminal=False,
    )
    elapsed = time.perf_counter() - started
    touched = 0
    best = None
    for terminal in kernel.terminals:
        token = bytes.fromhex(terminal["ident"])
        group = by_pack.get(token)
        if not group:
            continue
        arrival = int(terminal["g"])
        actions = tuple(kernel.reconstruct(int(terminal["node"])))
        for index, original, key, target in group:
            if arrival >= original:
                touched += 1
                continue
            if canonical_state_key(target) != key:
                continue
            if not _replays_to(source, actions, target, arrival):
                continue
            saving = original - arrival
            touched += 1
            if best is None or saving > best[0] or (saving == best[0] and index < best[1]):
                best = (saving, index, arrival, actions, original)
    common = dict(
        ceiling=ceiling,
        expanded=int(kernel.expanded),
        unique=int(kernel.unique),
        generated=int(kernel.generated),
        duplicate_skips=int(kernel.duplicate_skips),
        lower_bound_prunes=int(kernel.lower_bound_prunes) + impossible + dominated,
        elapsed_s=elapsed,
        stop_reason=kernel.stop_reason,
        targets_considered=len(specs),
        targets_touched=touched,
    )
    if best is not None:
        _saving, index, arrival, actions, _original = best
        found = SegmentResult(
            "FOUND",
            actions,
            arrival,
            proof=True,
            target_index=index,
            **common,
        )
    else:
        # max_unique = 0 means an improving state was seen and the search
        # stopped on purpose. If that state then failed replay, the graph
        # was not exhausted.
        early = kernel.stop_reason == "unique limit" and int(limits.max_unique) == 0
        inconclusive = early or kernel.stop_reason in {
            "time limit",
            "unique limit",
            "rss abort",
            "abort",
        }
        status = "INCONCLUSIVE" if inconclusive else "EXHAUSTED"
        found = SegmentResult(status, (), None, proof=status == "EXHAUSTED", **common)
    if memo is not None and found.status in {"FOUND", "EXHAUSTED", "NOT_CHEAPER", "IMPOSSIBLE"}:
        memo.setdefault("results", {})[memo_key] = found
    return found


def select_adaptive_regions(
    checkpoints: Sequence[Checkpoint],
    actions: Sequence[Action],
    *,
    horizon: int = 16,
    max_regions: int = 6,
) -> Tuple[AdaptiveRegion, ...]:
    """Pick a few source checkpoints and the later targets one search may hit.

    Exact cycles come first and need no search. Other regions do not overlap,
    so the same span is not expanded twice. Signals such as reversals and
    stock-empty gaps only order the regions. A skipped span is not a proof.
    """

    if len(checkpoints) < 2:
        return ()
    cycles: List[AdaptiveRegion] = []
    earliest = {}
    for checkpoint in checkpoints:
        previous = earliest.get(checkpoint.key)
        if previous is not None and checkpoint.g > checkpoints[previous].g:
            cycles.append(
                AdaptiveRegion(
                    start=previous,
                    targets=(checkpoint.index,),
                    kind="exact_cycle",
                    budget_class="short",
                    reason="the same column-ordered state returns at a higher cost",
                )
            )
        else:
            earliest.setdefault(checkpoint.key, checkpoint.index)
    cycles.sort(key=lambda item: (item.targets[0] - item.start, -checkpoints[item.targets[0]].g, item.start))

    span = max(2, int(horizon))
    last = checkpoints[-1].index
    ranked = []
    for start in range(0, last):
        end = min(last, start + span)
        targets = []
        for index in range(start + 1, end + 1):
            if checkpoints[index].g <= checkpoints[start].g:
                continue
            if checkpoints[index].key == checkpoints[start].key:
                continue
            targets.append(index)
        if not targets:
            continue
        kind, reason, score = _region_score(checkpoints, actions, start, targets)
        ranked.append((score, start, tuple(targets), kind, reason))
    ranked.sort(key=lambda item: (-item[0], item[1]))

    chosen: List[AdaptiveRegion] = []
    spans: List[Tuple[int, int]] = []
    for region in cycles:
        if len(chosen) >= int(max_regions):
            break
        chosen.append(region)
        spans.append((region.start, region.targets[-1]))
    for _score, start, targets, kind, reason in ranked:
        if len(chosen) >= int(max_regions):
            break
        end = targets[-1]
        if any(start < prev_end and prev_start < end for prev_start, prev_end in spans):
            continue
        cost = checkpoints[end].g - checkpoints[start].g
        budget = (
            "medium"
            if kind in {"known_inconclusive", "stock_empty", "between_foundations"} or cost >= 4
            else "short"
        )
        chosen.append(AdaptiveRegion(start, targets, kind, budget, reason))
        spans.append((start, end))
    return tuple(chosen)


def optimise_anchored(
    opening: SpiderState,
    actions: Sequence[Action],
    *,
    mode: str = "anchored",
    source: str = "imported",
    source_id: str = "",
    time_limit_s: float = 150.0,
    window_time_s: float = 4.0,
    medium_time_s: float = 10.0,
    max_windows: int = 16,
    max_span: int = 8,
    max_unique: int = 2500,
    rss_abort_mb: float = 3072.0,
    max_improvements: int = 6,
    expected_cost: Optional[int] = None,
    adaptive: bool = False,
    horizon: int = 16,
    max_regions: int = 6,
) -> AnchorReport:
    """Search cheaper rejoining segments of one verified complete route.

    ``adaptive`` searches each selected source toward every later checkpoint
    in its horizon. The default keeps the fixed one-endpoint windows.
    ``mode`` cold, solve, and diagnose raise. The production registry is not
    written. A failed or partial candidate leaves the verified route in place.
    """

    if mode in {"cold", "solve", "diagnose"}:
        raise AnchoredRefused(
            f"anchored optimisation is refused in {mode} mode. "
            "Cold solving does not load a known solution."
        )
    started = time.perf_counter()
    deadline = started + max(0.0, float(time_limit_s))
    peak = rss_mb()
    verified = verify_complete_solution(
        opening,
        actions,
        expected_cost=expected_cost,
        source=source,
        source_id=source_id,
    )
    current_actions = tuple(verified.actions)
    current_cost = int(verified.cost)
    imported_cost = current_cost
    improvements: List[dict] = []
    windows_public: List[dict] = []
    checkpoints_public: List[dict] = []
    examined = 0
    rejoins = 0
    segment_prunes = 0
    inconclusive = 0
    exhausted_windows = 0
    search_expansions = 0
    stop = "NO_IMPROVEMENT"
    round_index = 0
    memo_hits = 0
    targets_considered = 0
    exact_matches = 0
    covered_known: List[int] = []

    while len(improvements) < int(max_improvements):
        checkpoints = build_checkpoints(opening, current_actions)
        checkpoints_public = [item.public() for item in checkpoints]
        if checkpoints[-1].g != current_cost:
            stop = "INVALID"
            break
        if time.perf_counter() >= deadline:
            stop = "TIME_LIMIT"
            break
        # Each improvement refreshes checkpoints and may use another window budget.
        # The memo is per route. A refreshed route must not reuse the old graph.
        memo = {"hits": 0, "misses": 0, "results": {}}
        if adaptive:
            batch = select_adaptive_regions(
                checkpoints,
                current_actions,
                horizon=int(horizon),
                max_regions=int(max_regions),
            )
        else:
            batch = select_windows(
                checkpoints,
                current_actions,
                max_span=max_span,
                max_windows=int(max_windows),
            )
        if not batch:
            stop = "EXHAUSTED"
            break
        improved_now = False
        for item in batch:
            if time.perf_counter() >= deadline:
                stop = "TIME_LIMIT"
                break
            if adaptive:
                record = _examine_region(
                    opening,
                    current_actions,
                    checkpoints,
                    item,
                    current_cost=current_cost,
                    time_left=deadline - time.perf_counter(),
                    window_time_s=window_time_s,
                    medium_time_s=medium_time_s,
                    max_unique=max_unique,
                    rss_abort_mb=rss_abort_mb,
                    memo=memo,
                )
                matched_end = record.get("matched_end", item.targets[-1])
                segment_cost = record.get("matched_original_cost", record.get("ceiling"))
            else:
                record = _examine_window(
                    opening,
                    current_actions,
                    checkpoints,
                    item,
                    current_cost=current_cost,
                    time_left=deadline - time.perf_counter(),
                    window_time_s=window_time_s,
                    medium_time_s=medium_time_s,
                    max_unique=max_unique,
                    rss_abort_mb=rss_abort_mb,
                )
                matched_end = item.end
                segment_cost = item.cost
            rss = rss_mb()
            if rss is not None and (peak is None or rss > peak):
                peak = rss
            examined += 1
            if not record.get("reused"):
                search_expansions += int(record.get("expanded") or 0)
            segment_prunes += int(record.get("lower_bound_prunes") or 0)
            targets_considered += int(record.get("targets_considered") or 0)
            exact_matches += int(record.get("targets_touched") or 0)
            if record["status"] == "INCONCLUSIVE":
                inconclusive += 1
            elif record["status"] == "EXHAUSTED":
                exhausted_windows += 1
            elif record["status"] == "IMPOSSIBLE":
                segment_prunes += 1
            new_actions = record.pop("actions", None)
            windows_public.append(record)
            if record["status"] != "IMPROVED" or new_actions is None:
                continue
            rejoins += 1
            improvements.append(
                {
                    "before": current_cost,
                    "after": record["verified_cost"],
                    "start": item.start,
                    "end": matched_end,
                    "segment_cost": segment_cost,
                    "replacement_cost": record["replacement_cost"],
                    "kind": item.kind,
                    "source": "discovered",
                    "adaptive": bool(adaptive),
                }
            )
            current_actions = tuple(new_actions)
            current_cost = int(record["verified_cost"])
            improved_now = True
            round_index += 1
            break
        memo_hits += int(memo.get("hits", 0))
        if adaptive:
            covered_known = sorted(set(covered_known) | set(_covered_known(batch)))
        if stop == "TIME_LIMIT":
            break
        if not improved_now:
            stop = "NO_IMPROVEMENT" if not improvements else "NO_FURTHER_IMPROVEMENT"
            break

    if improvements and stop == "NO_IMPROVEMENT":
        stop = "IMPROVED"
    if improvements and stop == "NO_FURTHER_IMPROVEMENT":
        stop = "IMPROVED"
    if improvements and stop == "TIME_LIMIT":
        pass
    solved = False
    replay = {"ok": False}
    try:
        final = verify_complete_solution(
            opening,
            current_actions,
            expected_cost=current_cost,
            source="discovered" if improvements else source,
            source_id=source_id if not improvements else "anchored-rejoin",
        )
        solved = bool(final.solved)
        replay = {
            "ok": True,
            "cost": final.cost,
            "foundations": final.foundations,
            "solved": final.solved,
        }
        current_cost = int(final.cost)
        current_actions = tuple(final.actions)
    except IncumbentRejected as exc:
        stop = "INVALID"
        replay = {"ok": False, "error": str(exc)}
        current_actions = tuple(verified.actions)
        current_cost = int(verified.cost)
        improvements.clear()
        solved = False
    elapsed = time.perf_counter() - started
    improved = bool(improvements) and current_cost < imported_cost and solved
    if stop == "TIME_LIMIT":
        search_status = "TIME_LIMIT"
    elif improved:
        search_status = "IMPROVED"
    else:
        search_status = stop
    if improved and search_status != "TIME_LIMIT":
        report_status = "SOLVED_VALID"
    elif replay.get("ok") and search_status == "INVALID":
        report_status = "INVALID"
    else:
        report_status = search_status
    provenance = {
        "approach": "anchored",
        "mode": mode,
        "global_search": False,
        "anchored_used": True,
        "cold_injection": False,
        "explicit_anchor": True,
        "prefix_injected": False,
        "assisted_suffix": False,
        "suffix_retained_after_exact_rejoin": bool(improved),
        "incumbent_source": "discovered" if improved else source,
        "imported_cost": imported_cost,
        "best_verified_cost": current_cost if solved else imported_cost,
        "previous_verified_cost": imported_cost,
        "improved": improved,
        "search_status": search_status,
        "ceiling_initial": imported_cost,
        "ceiling_final": current_cost if improved else imported_cost,
        "windows_examined": examined,
        "rejoins": rejoins,
        "inconclusive_windows": inconclusive,
        "exhausted_windows": exhausted_windows,
        "segment_bound_prunes": segment_prunes,
        "search_expansions": search_expansions,
        "checkpoint_count": len(checkpoints_public),
        "improvements": len(improvements),
        "production_registry_written": False,
        "proof_bound": "segment deal count, plus the incumbent segment cost as a local ceiling",
        "heuristic_screen_is_not_a_proof": True,
        "column_ordered_rejoin": True,
        "symmetry_quotient_used": False,
        "source_id": source_id,
        "rounds": round_index,
        "adaptive": bool(adaptive),
        "target_mode": "multi-checkpoint" if adaptive else "fixed-endpoint",
        "memo_hits": memo_hits,
        "targets_considered": targets_considered,
        "exact_matches": exact_matches,
        "known_inconclusive_covered": covered_known,
        "segment_proof_is_not_global_optimality": True,
        "anchored_search_s": round(elapsed, 3),
    }
    return AnchorReport(
        status=report_status,
        mode=mode,
        actions=current_actions if solved else tuple(verified.actions),
        cumulative_g=current_cost if solved else imported_cost,
        solved=solved,
        elapsed_s=elapsed,
        peak_rss_mb=peak,
        provenance=provenance,
        replay=replay,
        windows=windows_public,
        improvements=improvements,
        checkpoints=checkpoints_public,
        objectives_attempted=examined,
        unique_states=search_expansions,
    )


def _examine_window(
    opening: SpiderState,
    actions: Sequence[Action],
    checkpoints: Sequence[Checkpoint],
    window: Window,
    *,
    current_cost: int,
    time_left: float,
    window_time_s: float,
    medium_time_s: float,
    max_unique: int,
    rss_abort_mb: float,
) -> dict:
    source = checkpoints[window.start]
    target = checkpoints[window.end]
    record = {
        "start": window.start,
        "end": window.end,
        "segment_cost": window.cost,
        "kind": window.kind,
        "budget_class": window.budget_class,
        "ceiling": window.cost,
        "source_id": source.state_id,
        "target_id": target.state_id,
        "status": "INCONCLUSIVE",
        "expanded": 0,
        "unique": 0,
        "duplicate_skips": 0,
        "lower_bound_prunes": 0,
        "proof": False,
        "replacement_cost": None,
        "verified_cost": None,
    }
    if not states_rejoin(source.state, _replay_prefix(opening, actions, window.start)):
        record["status"] = "INVALID"
        record["stop_reason"] = "source checkpoint drifted"
        return record
    allowance = medium_time_s if window.budget_class == "medium" else window_time_s
    allowance = max(0.0, min(float(allowance), float(time_left)))
    if window.kind == "exact_cycle":
        found = SegmentResult("FOUND", (), 0, window.cost, stop_reason="exact cycle", proof=True)
    else:
        found = search_segment(
            source.state,
            target.state,
            window.cost,
            time_limit_s=allowance,
            max_unique=max_unique,
            rss_abort_mb=rss_abort_mb,
        )
    record["expanded"] = found.expanded
    record["unique"] = found.unique
    record["duplicate_skips"] = found.duplicate_skips
    record["lower_bound_prunes"] = found.lower_bound_prunes
    record["stop_reason"] = found.stop_reason
    record["proof"] = found.proof and found.status in {"EXHAUSTED", "IMPOSSIBLE", "NOT_CHEAPER"}
    record["search_status"] = found.status
    if found.status != "FOUND" or found.cost is None or found.cost >= window.cost:
        record["status"] = found.status
        return record
    spliced = tuple(actions[: window.start]) + tuple(found.actions) + tuple(actions[window.end :])
    committed = _commit(opening, spliced, current_cost, source.state, found.actions, target.state)
    if committed is None:
        record["status"] = "REJECTED"
        record["proof"] = False
        return record
    record["status"] = "IMPROVED"
    record["proof"] = True
    record["replacement_cost"] = found.cost
    record["verified_cost"] = committed.cost
    record["actions"] = committed.actions
    return record


def _examine_region(
    opening: SpiderState,
    actions: Sequence[Action],
    checkpoints: Sequence[Checkpoint],
    region: AdaptiveRegion,
    *,
    current_cost: int,
    time_left: float,
    window_time_s: float,
    medium_time_s: float,
    max_unique: int,
    rss_abort_mb: float,
    memo: dict,
) -> dict:
    """Search one source against its later checkpoints and splice a strict improvement."""

    source = checkpoints[region.start]
    specs = []
    for index in region.targets:
        target = checkpoints[index]
        original = int(target.g) - int(source.g)
        if original < 1:
            continue
        specs.append((target.state, original, index))
    ceiling = max((cost for _state, cost, _index in specs), default=0)
    record = {
        "start": region.start,
        "end": region.targets[-1] if region.targets else region.start,
        "targets": list(region.targets),
        "segment_cost": ceiling,
        "kind": region.kind,
        "reason": region.reason,
        "budget_class": region.budget_class,
        "ceiling": ceiling,
        "source_id": source.state_id,
        "target_id": checkpoints[region.targets[-1]].state_id if region.targets else source.state_id,
        "status": "INCONCLUSIVE",
        "expanded": 0,
        "unique": 0,
        "duplicate_skips": 0,
        "lower_bound_prunes": 0,
        "proof": False,
        "proof_scope": "selected-targets",
        "replacement_cost": None,
        "verified_cost": None,
        "matched_end": None,
        "matched_original_cost": None,
        "targets_considered": len(specs),
        "targets_touched": 0,
        "reused": False,
        "global_optimal": False,
    }
    if not states_rejoin(source.state, _replay_prefix(opening, actions, region.start)):
        record["status"] = "INVALID"
        record["stop_reason"] = "source checkpoint drifted"
        return record
    if not specs:
        record["status"] = "NOT_CHEAPER"
        record["proof"] = True
        record["stop_reason"] = "no eligible target"
        return record
    allowance = medium_time_s if region.budget_class == "medium" else window_time_s
    allowance = max(0.0, min(float(allowance), float(time_left)))
    if region.kind == "exact_cycle":
        found = SegmentResult(
            "FOUND",
            (),
            0,
            ceiling,
            stop_reason="exact cycle",
            proof=True,
            target_index=region.targets[0],
            targets_considered=1,
        )
    else:
        found = search_targets(
            source.state,
            specs,
            time_limit_s=allowance,
            max_unique=max_unique,
            rss_abort_mb=rss_abort_mb,
            memo=memo,
        )
    record["expanded"] = found.expanded
    record["unique"] = found.unique
    record["duplicate_skips"] = found.duplicate_skips
    record["lower_bound_prunes"] = found.lower_bound_prunes
    record["stop_reason"] = found.stop_reason
    record["targets_touched"] = found.targets_touched
    record["targets_considered"] = found.targets_considered
    record["reused"] = found.reused
    record["search_status"] = found.status
    record["proof"] = bool(found.proof and found.status in {"EXHAUSTED", "IMPOSSIBLE", "NOT_CHEAPER"})
    if found.status != "FOUND" or found.cost is None or found.target_index is None:
        record["status"] = found.status
        return record
    matched = checkpoints[found.target_index]
    original = int(matched.g) - int(source.g)
    record["matched_end"] = found.target_index
    record["matched_original_cost"] = original
    record["end"] = found.target_index
    record["target_id"] = matched.state_id
    if found.cost >= original:
        record["status"] = "NOT_CHEAPER"
        record["proof"] = True
        return record
    spliced = tuple(actions[: region.start]) + tuple(found.actions) + tuple(actions[found.target_index :])
    committed = _commit(
        opening,
        spliced,
        current_cost,
        source.state,
        found.actions,
        matched.state,
    )
    if committed is None:
        record["status"] = "REJECTED"
        record["proof"] = False
        return record
    record["status"] = "IMPROVED"
    record["proof"] = True
    record["replacement_cost"] = found.cost
    record["verified_cost"] = committed.cost
    record["actions"] = committed.actions
    return record


def _region_score(
    checkpoints: Sequence[Checkpoint],
    actions: Sequence[Action],
    start: int,
    targets: Sequence[int],
) -> Tuple[str, str, int]:
    """Order regions. The score is not evidence that the span is wasteful."""

    end = targets[-1]
    left = checkpoints[start]
    right = checkpoints[end]
    cost = int(right.g) - int(left.g)
    span = end - start
    segment = list(actions[start:end])
    stock_empty = left.stock_cards == 0
    foundation_change = right.foundations != left.foundations
    reversal = _contains_reversal(segment)
    covers_known = any(start <= item <= end for item in _KNOWN_INCONCLUSIVE if item <= checkpoints[-1].index)
    parking = (
        left.face_down == right.face_down
        and left.empty_columns != right.empty_columns
        and cost >= 2
    )
    score = min(cost, 12)
    kind = "horizon"
    reason = "later checkpoints inside a bounded horizon"
    if start in _KNOWN_INCONCLUSIVE:
        score += 1000
        kind = "known_inconclusive"
        reason = "source of a v0.118 window that stopped at the unique cap"
    elif covers_known and stock_empty:
        score += 800
        kind = "stock_empty"
        reason = "stock-empty span covering a previously capped window"
    if stock_empty and foundation_change:
        score += 400
        if kind == "horizon":
            kind = "stock_empty"
            reason = "stock-empty interval between foundations"
    if reversal:
        score += 300
        if kind == "horizon":
            kind = "reversal"
            reason = "a move is undone later in the horizon"
    if foundation_change and kind == "horizon":
        score += 150
        kind = "between_foundations"
        reason = "the foundation count changes inside the horizon"
    if parking and kind == "horizon":
        score += 80
        kind = "workspace"
        reason = "empty columns change while the face-down count does not"
    if span <= 2 and cost <= 2 and kind == "horizon":
        score -= 40
    return kind, reason, score


def _covered_known(regions: Sequence[AdaptiveRegion]) -> List[int]:
    covered = []
    for item in _KNOWN_INCONCLUSIVE:
        for region in regions:
            end = region.targets[-1] if region.targets else region.start
            if region.start <= item <= end:
                covered.append(item)
                break
    return covered


def _commit(
    opening: SpiderState,
    spliced: Sequence[Action],
    current_cost: int,
    source: SpiderState,
    replacement: Sequence[Action],
    target: SpiderState,
):
    """Accept a splice only after the segment rejoins and the full game replays."""

    if not _replays_to(source, replacement, target, None):
        return None
    try:
        route = verify_complete_solution(
            opening,
            spliced,
            source="discovered",
            source_id="anchored-rejoin",
        )
    except IncumbentRejected:
        return None
    if int(route.cost) >= int(current_cost):
        return None
    return route


def _replays_to(
    source: SpiderState,
    actions: Sequence[Action],
    target: SpiderState,
    expected_cost: Optional[int],
) -> bool:
    trial = source.clone()
    try:
        spent = int(replay_actions(trial, list(actions))) if actions else 0
    except ValueError:
        return False
    if expected_cost is not None and spent != int(expected_cost):
        return False
    return states_rejoin(trial, target)


def _replay_prefix(opening: SpiderState, actions: Sequence[Action], count: int) -> SpiderState:
    trial = opening.clone()
    if count:
        replay_actions(trial, list(actions[:count]))
    return trial


def _make_checkpoint(index: int, state: SpiderState, g: int) -> Checkpoint:
    snapshot = state.clone()
    return Checkpoint(
        index=index,
        g=int(g),
        stock_cards=len(snapshot.stock),
        stock_rows=len(snapshot.stock) // 10,
        foundations=len(snapshot.foundations),
        face_down=face_down_count(snapshot),
        empty_columns=empty_count(snapshot),
        bonds=same_suit_bonds(snapshot),
        admissible_remaining=admissible_remaining(snapshot),
        state_id=pack_state(snapshot).hex()[:16],
        state=snapshot,
        key=canonical_state_key(snapshot),
    )


def _card_seq(cards) -> Tuple[Tuple[str, int], ...]:
    return tuple((card.suit, int(card.rank)) for card in cards)


def _foundation_multiset(state: SpiderState) -> Tuple[Tuple[Tuple[str, int], ...], ...]:
    sequences = [_card_seq(sequence) for sequence in state.foundations]
    sequences.sort()
    return tuple(sequences)


def _foundations_can_grow(state: SpiderState, target: SpiderState) -> bool:
    have: dict = {}
    need: dict = {}
    for sequence in _foundation_multiset(state):
        have[sequence] = have.get(sequence, 0) + 1
    for sequence in _foundation_multiset(target):
        need[sequence] = need.get(sequence, 0) + 1
    for sequence, count in have.items():
        if need.get(sequence, 0) < count:
            return False
    return True


def _required_deals(state: SpiderState, target: SpiderState) -> Optional[int]:
    """Deals that leave exactly the target stock, or None if no such deals exist."""

    delta = len(state.stock) - len(target.stock)
    if delta < 0 or delta % 10 != 0:
        return None
    if _card_seq(state.stock[: len(state.stock) - delta]) != _card_seq(target.stock):
        return None
    return delta // 10


def _window_kind(
    checkpoints: Sequence[Checkpoint],
    actions: Sequence[Action],
    start: int,
    end: int,
) -> Optional[str]:
    left = checkpoints[start]
    right = checkpoints[end]
    segment = list(actions[start:end])
    if _contains_reversal(segment):
        return "reversal"
    same_structure = (
        left.foundations == right.foundations
        and left.stock_cards == right.stock_cards
        and abs(left.face_down - right.face_down) <= 1
    )
    cost = right.g - left.g
    span = end - start
    if same_structure and cost >= 2:
        return "low_change"
    if left.foundations == right.foundations and cost >= span and span <= 6:
        return "paid_run"
    return None


def _contains_reversal(actions: Sequence[Action]) -> bool:
    for index, action in enumerate(actions):
        for later in actions[index + 1 :]:
            if _inverse(action, later):
                return True
    return False


def _inverse(left: Action, right: Action) -> bool:
    if left == ("deal",) or right == ("deal",):
        return False
    return left[0] == right[1] and left[1] == right[0] and left[2] == right[2]


def _nonoverlapping(windows: Sequence[Window], *, limit: int) -> List[Window]:
    chosen: List[Window] = []
    for window in windows:
        if len(chosen) >= int(limit):
            break
        if any(window.start < item.end and item.start < window.end for item in chosen):
            continue
        chosen.append(window)
    return chosen


def _between_foundations(checkpoints: Sequence[Checkpoint], *, max_span: int) -> List[Window]:
    marks = [0]
    for checkpoint in checkpoints[1:]:
        if checkpoint.foundations != checkpoints[checkpoint.index - 1].foundations:
            marks.append(checkpoint.index)
    if checkpoints[-1].index not in marks:
        marks.append(checkpoints[-1].index)
    found: List[Window] = []
    for left, right in zip(marks, marks[1:]):
        span = right - left
        cost = checkpoints[right].g - checkpoints[left].g
        if span < 4 or span > max(int(max_span), 10) or cost < 2:
            continue
        if checkpoints[left].key == checkpoints[right].key:
            continue
        found.append(
            Window(
                start=left,
                end=right,
                cost=cost,
                kind="between_foundations",
                budget_class="medium",
            )
        )
    found.sort(key=lambda item: (item.end - item.start, -item.cost, item.start))
    return found[:3]
