"""Simple progressive Spider solver — competing baseline v0.7.

Straightforward backtracking: legal primitive actions, cheap deterministic
ordering, exact-state transposition, cycle cuts, progressive relaxation,
depth-banded DFS, and saturation-aware slice scheduling.

v0.5 adds an optional best-reveal Deal probe: on a strict new face-down
record at a stock depth, explore the engine-legal Deal child first, then
resume the same A–D pass.  Default OFF.  Tiers, scores, bands, saturation,
and TT are unchanged.

v0.6 adds optional post-Deal continuation telemetry.  Default OFF.  Census
and lineage reconstruction do not order moves, prune, or change TT.

v0.7 optionally scopes saturation to ``(depth_band, pass)``.  Default OFF
(cross-band, v0.3–v0.6).  Band-local mode does not clear TT coverage.

v0.8 adds optional ``start_pass`` so a research search may begin at Pass 1.
Default remains 0.  Ordinary whole-deal policy is unchanged.

This module must not import the strategic controller, scheduler, allocator,
campaign, registry, or project machinery.  Search bookkeeping is separate
from canonical identity.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Sequence, Tuple, Union

from spider.engine import SpiderState
from spider.metrics import Action, replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES, MobilityWareRules, deal_cost, mw_move_cost
from spider.simple_post_deal_audit import (
    PostDealAudit,
    _mixed_joins,
    exposed_run_metrics,
    inspect_state,
)
from spider.simple_reveal_stock_audit import RevealStockAudit, cheap_structure


TableauMove = Tuple[int, int, int]
SolverAction = Union[TableauMove, Tuple[str]]
ExactKey = bytes


class Tier(IntEnum):
    """Desirability band.  Controls order and temporary permission, not proof."""

    A = 0  # strongly constructive
    B = 1  # ordinary useful setup
    C = 2  # rework
    D = 3  # unattractive but legal


# Pass p permits tiers 0..p inclusive.  Pass 0 is A (and Deal when Deal is A).
N_PASSES = 4
MAX_DEPTH_GUARD = 5000
PREP_CANDIDATE_CAP = 8
DEFAULT_DEPTH_BANDS: Tuple[int, ...] = (80, 160, 320, 640, 1280)
_INF_REMAINING = 10**9


@dataclass(frozen=True)
class DealLanding:
    same_suit: int
    mixed_adjacent: int
    empty_lands: int
    buried: int
    buried_run3: int
    score: int
    legal: bool


@dataclass
class SearchStats:
    states_expanded: int = 0
    states_generated: int = 0
    unique_exact_states: int = 0
    tt_hits: int = 0
    duplicate_children: int = 0
    path_cycles: int = 0
    inverses: int = 0
    max_depth: int = 0
    considered_by_tier: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    expanded_by_tier: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    deals_considered: int = 0
    deals_executed: int = 0
    deal_now_choices: int = 0
    prepared_deal_choices: int = 0
    prep_calls: int = 0
    prep_nodes: int = 0
    first_foundation_node: Optional[int] = None
    first_foundation_depth: Optional[int] = None
    first_foundation_pass: Optional[int] = None
    max_foundations: int = 0
    peak_rss_mb: Optional[float] = None
    pass_reached: int = 0
    last_prep_action: Optional[SolverAction] = None
    tt_depth_prunes: int = 0
    tt_reopens: int = 0
    expansions_by_depth_bucket: List[int] = field(
        default_factory=lambda: [0, 0, 0, 0, 0]
    )
    states_by_stock_dealt: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    unique_by_stock_dealt: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    deals_executed_from_stock: List[int] = field(
        default_factory=lambda: [0, 0, 0, 0, 0, 0]
    )
    unique_deal_parents: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    depth_band_used: int = 0
    band_pass_reports: List[dict] = field(default_factory=list)
    slices_skipped: int = 0
    expansions_redirected: int = 0
    unique_by_pass: List[int] = field(default_factory=lambda: [0, 0, 0, 0])
    saturated_passes: List[int] = field(default_factory=list)
    saturated_band_passes: List[dict] = field(default_factory=list)
    band_local_saturation: bool = False
    reveal_records: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    probe_fires: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    probe_entered: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    probe_tt_suppressed: List[int] = field(default_factory=lambda: [0, 0, 0, 0, 0, 0])
    probe_events: List[dict] = field(default_factory=list)


@dataclass
class ProgressiveSearchResult:
    solved: bool
    actions: List[Action]
    cost: int
    nodes: int
    elapsed_s: float
    pass_reached: int
    max_foundations: int
    min_face_down: int
    min_stock_rows: int
    foundation_path: List[Action] = field(default_factory=list)
    foundation_cost: int = 0
    stop_reason: str = ""
    replay_ok: bool = False
    stats: SearchStats = field(default_factory=SearchStats)
    first_foundation_actions: List[Action] = field(default_factory=list)
    identified_face_down: int = 0
    identified_stock_rows: int = 0
    states_per_sec: float = 0.0
    depth_bands_used: List[int] = field(default_factory=list)
    best_reveal_actions: List[Action] = field(default_factory=list)
    best_reveal_fd: int = 0
    best_reveal_stock: int = 0
    best_reveal_foundations: int = 0
    best_reveal_depth: int = 0
    best_reveal_cost: int = 0
    best_stock_actions: List[Action] = field(default_factory=list)
    best_stock_fd: int = 0
    best_stock_stock: int = 0
    best_stock_foundations: int = 0
    best_stock_depth: int = 0
    best_stock_cost: int = 0
    best_foundation_actions: List[Action] = field(default_factory=list)
    best_foundation_fd: int = 0
    best_foundation_stock: int = 0
    best_foundation_foundations: int = 0
    best_foundation_depth: int = 0
    best_foundation_cost: int = 0
    best_fd_by_stock_dealt: List[dict] = field(default_factory=list)
    audit: Optional[RevealStockAudit] = None
    probe_events: List[dict] = field(default_factory=list)
    post_deal_audit: Optional[PostDealAudit] = None

    @property
    def stage_reached(self) -> int:
        return self.pass_reached


def _rss_mb() -> Optional[float]:
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = _PMC()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_PMC),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        handle = kernel32.GetCurrentProcess()
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        return counters.PeakWorkingSetSize / (1024.0 * 1024.0)
    except Exception:
        return None


def _face_down(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def _stock_rows(state: SpiderState) -> int:
    return len(state.stock) // 10


def _empty_count(state: SpiderState) -> int:
    return sum(1 for col in state.columns if col.is_empty())


def _same_suit_run_len(face_up: Sequence) -> int:
    if not face_up:
        return 0
    suit = face_up[-1].suit
    n = 0
    for card in reversed(face_up):
        if card.suit != suit:
            break
        n += 1
    return n


def is_deal(action: SolverAction) -> bool:
    return action == ("deal",) or action == "deal"


def enumerate_actions(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> List[SolverAction]:
    """Legal primitives from the engine.  Tiers may order, not omit, these."""

    return list(state.enumerate_legal_actions(rules=rules))


def evaluate_deal_landings(
    state: SpiderState, *, rules: MobilityWareRules = MW_RULES
) -> Optional[DealLanding]:
    """Cheap perfect-information score of the next stock row.

    Next row is ``state.stock[-10:]``, landing left-to-right on columns 0..9.
    """

    if len(state.stock) < 10:
        return None
    row = state.stock[-10:]
    same = mixed = empty = buried = buried3 = 0
    for index, card in enumerate(row):
        col = state.columns[index]
        top = col.top()
        if top is None:
            empty += 1
            continue
        adjacent = top.rank == card.rank + 1
        if adjacent and top.suit == card.suit:
            same += 1
        elif adjacent:
            mixed += 1
        else:
            buried += 1
            if _same_suit_run_len(col.face_up) >= 3:
                buried3 += 1
    score = 3 * same + mixed - buried - 2 * buried3
    return DealLanding(
        same_suit=same,
        mixed_adjacent=mixed,
        empty_lands=empty,
        buried=buried,
        buried_run3=buried3,
        score=score,
        legal=state.can_deal(rules=rules),
    )


def _would_complete_foundation(state: SpiderState, src: int, dst: int, k: int) -> bool:
    run = state.columns[src].face_up[-k:]
    dest = state.columns[dst].face_up
    if not dest:
        return k == 13 and run[0].rank == 13
    combined = dest + run
    if len(combined) < 13:
        return False
    tail = combined[-13:]
    return tail[0].rank == 13 and SpiderState.is_movable_run(tail)


def classify_tier(
    state: SpiderState,
    action: SolverAction,
    *,
    landing: Optional[DealLanding] = None,
) -> Tier:
    """Deterministic local tier.  No campaign analysis."""

    if is_deal(action):
        sig = landing if landing is not None else evaluate_deal_landings(state)
        if sig is None:
            return Tier.D
        if sig.score >= 4:
            return Tier.A
        if sig.score >= 0:
            return Tier.B
        if sig.score >= -4:
            return Tier.C
        return Tier.D

    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    empties_source = k == len(src_col.face_up) and not src_col.face_down
    dest_empty = dest_top is None
    creates_empty = empties_source and not dest_empty
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        join_break = left.suit == head.suit and left.rank == head.rank + 1
    same_suit_extend = dest_top is not None and dest_top.suit == head.suit

    if _would_complete_foundation(state, src, dst, k):
        return Tier.A
    if uncovers:
        return Tier.A
    if same_suit_extend and not join_break:
        return Tier.A
    if creates_empty and not join_break:
        return Tier.A
    if dest_empty and head.rank == 13:
        return Tier.B
    if same_suit_extend and join_break:
        return Tier.B
    if not dest_empty and not same_suit_extend and not join_break:
        return Tier.B
    if join_break:
        return Tier.C
    if dest_empty:
        return Tier.C
    return Tier.D


def action_allowed(tier: Tier, pass_level: int) -> bool:
    return int(tier) <= pass_level


def step_cost(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if is_deal(action):
        return deal_cost()
    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    return mw_move_cost(
        cards_moved=k,
        source_face_up_count=len(src_col.face_up),
        dest_was_empty=dst_col.is_empty(),
        source_face_down_count=len(src_col.face_down),
        rules=rules,
    )


def apply_action(
    state: SpiderState,
    action: SolverAction,
    *,
    rules: MobilityWareRules = MW_RULES,
) -> int:
    if is_deal(action):
        return state.deal(rules=rules)
    src, dst, k = action  # type: ignore[misc]
    return state.move(src, dst, k, rules=rules)


def _order_score(
    state: SpiderState,
    action: SolverAction,
    tier: Tier,
    landing: Optional[DealLanding],
) -> int:
    """Cheaper than expanding the child.  Higher is better."""

    if is_deal(action):
        return 40 + (landing.score if landing is not None else 0) * 8

    src, dst, k = action  # type: ignore[misc]
    src_col = state.columns[src]
    dst_col = state.columns[dst]
    run = src_col.face_up[-k:]
    head = run[0]
    dest_top = dst_col.top()
    uncovers = k == len(src_col.face_up) and bool(src_col.face_down)
    empties_source = k == len(src_col.face_up) and not src_col.face_down
    dest_empty = dest_top is None
    creates_empty = empties_source and not dest_empty
    join_break = False
    if k < len(src_col.face_up):
        left = src_col.face_up[-k - 1]
        join_break = left.suit == head.suit and left.rank == head.rank + 1
    score = 0
    if _would_complete_foundation(state, src, dst, k):
        score += 10_000
    if uncovers:
        score += 500
    if creates_empty:
        score += 200
    if dest_top is not None and dest_top.suit == head.suit:
        score += 50 + 10 * k
    if dest_empty and head.rank == 13:
        score += 40
    if join_break:
        score -= 80
    if dest_empty and not empties_source and _empty_count(state) == 1:
        score -= 60
    if dest_empty and head.rank != 13 and not uncovers:
        score -= 20
    score += k
    return score


def is_direct_inverse(last_move, action: SolverAction) -> bool:
    """A→B→A suppression.  Flip or foundation removal is not invertible."""

    if last_move is None or is_deal(action):
        return False
    if last_move == ("deal",):
        return False
    if not isinstance(last_move, tuple) or len(last_move) < 3:
        return False
    src, dst, k = action  # type: ignore[misc]
    last_src, last_dst, last_k = last_move[0], last_move[1], last_move[2]
    if src != last_dst or dst != last_src or k != last_k:
        return False
    if len(last_move) >= 5:
        flipped, removed = last_move[3], last_move[4]
        if flipped or removed:
            return False
    return True


def _capture(state: SpiderState, action: SolverAction) -> tuple:
    if is_deal(action):
        cols = tuple((col.face_down[:], col.face_up[:]) for col in state.columns)
        return ("d", cols, state.stock[:], state.foundations[:], state.last_move)
    src, dst, _k = action  # type: ignore[misc]
    sc = state.columns[src]
    dc = state.columns[dst]
    return (
        "m",
        src,
        dst,
        sc.face_down[:],
        sc.face_up[:],
        dc.face_down[:],
        dc.face_up[:],
        state.foundations[:],
        state.last_move,
    )


def _restore(state: SpiderState, snap: tuple) -> None:
    if snap[0] == "d":
        _kind, cols, stock, found, last = snap
        for col, (face_down, face_up) in zip(state.columns, cols):
            col.face_down[:] = face_down
            col.face_up[:] = face_up
        state.stock[:] = stock
        state.foundations[:] = found
        state.last_move = last
        return
    _kind, src, dst, sfd, sfu, dfd, dfu, found, last = snap
    sc = state.columns[src]
    dc = state.columns[dst]
    sc.face_down[:] = sfd
    sc.face_up[:] = sfu
    dc.face_down[:] = dfd
    dc.face_up[:] = dfu
    state.foundations[:] = found
    state.last_move = last


def deal_preparation(
    state: SpiderState,
    *,
    rules: MobilityWareRules = MW_RULES,
    prep_ply: int = 1,
    stats: Optional[SearchStats] = None,
) -> Tuple[Optional[SolverAction], Optional[DealLanding]]:
    """Compare Deal-now with at most ``prep_ply`` cheap tableau preps.

    Returns ``(best_prep_or_None, deal_now_landing)``.  None prep means Deal
    now is at least as good as the bounded preparations.
    """

    landing = evaluate_deal_landings(state, rules=rules)
    if landing is None:
        return None, None
    if stats is not None:
        stats.prep_calls += 1
    if prep_ply <= 0 or not landing.legal:
        return None, landing

    best_score = landing.score
    best_action: Optional[SolverAction] = None
    ranked: List[Tuple[int, SolverAction]] = []
    for action in state.enumerate_moves():
        tier = classify_tier(state, action)
        if int(tier) > int(Tier.B):
            continue
        ranked.append((-_order_score(state, action, tier, None), action))
    ranked.sort()
    candidates = [action for _score, action in ranked[:PREP_CANDIDATE_CAP]]

    def consider(action: SolverAction) -> None:
        nonlocal best_score, best_action
        snap = _capture(state, action)
        try:
            apply_action(state, action, rules=rules)
            if stats is not None:
                stats.prep_nodes += 1
            child_land = evaluate_deal_landings(state, rules=rules)
            if child_land is not None and child_land.legal and child_land.score > best_score:
                best_score = child_land.score
                best_action = action
        except (ValueError, AssertionError):
            pass
        finally:
            _restore(state, snap)

    for action in candidates:
        consider(action)

    if prep_ply >= 2 and len(candidates) <= 6:
        for first in candidates[:4]:
            snap1 = _capture(state, first)
            try:
                apply_action(state, first, rules=rules)
                if stats is not None:
                    stats.prep_nodes += 1
                second_moves = [
                    act
                    for act in state.enumerate_moves()
                    if int(classify_tier(state, act)) <= int(Tier.B)
                ][:6]
                for second in second_moves:
                    consider(second)
            except (ValueError, AssertionError):
                pass
            finally:
                _restore(state, snap1)

    return best_action, landing


def ordered_actions(
    state: SpiderState,
    pass_level: int,
    *,
    rules: MobilityWareRules = MW_RULES,
    prep_ply: int = 1,
    stats: Optional[SearchStats] = None,
    last_move=None,
) -> List[SolverAction]:
    """Legal actions permitted at ``pass_level``, cheapest-first within tier."""

    landing = evaluate_deal_landings(state, rules=rules)
    prep_action: Optional[SolverAction] = None
    # Prep is optional and relatively expensive.  Skip it on pass 0 (A-only)
    # and when Deal is not currently legal — still allow it once B+ moves
    # are in play, which is when postponing a mediocre Deal is meaningful.
    want_prep = (
        prep_ply > 0
        and landing is not None
        and pass_level >= 1
        and (landing.legal or _empty_count(state) > 0)
    )
    if want_prep:
        prep_action, landing = deal_preparation(
            state, rules=rules, prep_ply=prep_ply, stats=stats
        )

    scored: List[Tuple[int, int, int, int, int, SolverAction]] = []
    for action in enumerate_actions(state, rules=rules):
        tier = classify_tier(state, action, landing=landing)
        if stats is not None:
            stats.considered_by_tier[int(tier)] += 1
            if is_deal(action):
                stats.deals_considered += 1
        if not action_allowed(tier, pass_level):
            continue
        if is_direct_inverse(last_move, action):
            if stats is not None:
                stats.inverses += 1
            continue
        score = _order_score(state, action, tier, landing)
        if prep_action is not None and action == prep_action:
            score += 1_000
        if is_deal(action) and prep_action is not None:
            score -= 80
        if is_deal(action):
            src = dst = 99
            k = 0
        else:
            src, dst, k = action  # type: ignore[misc]
        scored.append((int(tier), -score, src, dst, k, action))
    if stats is not None:
        stats.last_prep_action = prep_action
    scored.sort()
    return [item[-1] for item in scored]


def _depth_bucket(depth: int) -> int:
    if depth < 80:
        return 0
    if depth < 160:
        return 1
    if depth < 320:
        return 2
    if depth < 640:
        return 3
    return 4


def _stock_dealt_index(opening_rows: int, current_rows: int) -> int:
    dealt = opening_rows - current_rows
    if dealt < 0:
        return 0
    if dealt > 5:
        return 5
    return dealt


class _CoverageTT:
    """Depth-aware exact coverage keyed by packed state and relaxation pass.

    For each ``(state, pass)`` retain the maximum remaining-depth budget
    already started (``seen``) or completely searched (``done``).

    Skip when::

        max_covered_remaining(state, pass) >= current_remaining_depth

    Broader passes subsume narrower at the same remaining depth: exhaustion
    at pass 2 remaining 80 covers pass 0 remaining 80, but not remaining 160.
    A shallow remaining-depth exhaustion never suppresses a later visit with
    more remaining depth.  Incomplete expansions are recorded in ``seen``
    only, not ``done``.
    """

    def __init__(self) -> None:
        self.seen: Dict[ExactKey, List[int]] = {}
        self.done: Dict[ExactKey, List[int]] = {}

    def _slot(self, store: Dict[ExactKey, List[int]], key: ExactKey) -> List[int]:
        slot = store.get(key)
        if slot is None:
            slot = [-1, -1, -1, -1]
            store[key] = slot
        return slot

    def max_covered_remaining(self, key: ExactKey, pass_level: int) -> int:
        best = -1
        for store in (self.done, self.seen):
            slot = store.get(key)
            if slot is None:
                continue
            for index in range(pass_level, N_PASSES):
                if slot[index] > best:
                    best = slot[index]
        return best

    def skip(self, key: ExactKey, pass_level: int, remaining: int = _INF_REMAINING) -> bool:
        return self.max_covered_remaining(key, pass_level) >= remaining

    def mark_start(self, key: ExactKey, pass_level: int, remaining: int = _INF_REMAINING) -> None:
        slot = self._slot(self.seen, key)
        if remaining > slot[pass_level]:
            slot[pass_level] = remaining

    def mark_done(self, key: ExactKey, pass_level: int, remaining: int = _INF_REMAINING) -> None:
        slot = self._slot(self.done, key)
        if remaining > slot[pass_level]:
            slot[pass_level] = remaining

    def __len__(self) -> int:
        return len(self.seen)


class SaturationBook:
    """Scheduling-only saturation.  Not a proof of exhaustion.

    Cross-band (default): a pass marked saturated is skipped in later bands.
    Band-local: saturation is keyed by ``(band, pass)`` and does not inherit.
    The depth-aware TT is never cleared.
    """

    def __init__(self, *, band_local: bool = False) -> None:
        self.band_local = band_local
        self._global: set = set()
        self._cells: set = set()

    def is_saturated(self, pass_level: int, band: int) -> bool:
        if self.band_local:
            return (band, pass_level) in self._cells
        return pass_level in self._global

    def mark(self, pass_level: int, band: int) -> None:
        self._cells.add((band, pass_level))
        self._global.add(pass_level)

    def inherited(self, pass_level: int, band: int) -> bool:
        """True iff a skip would come from a shallower band's global flag."""

        if self.band_local:
            return False
        return pass_level in self._global and (band, pass_level) not in self._cells

    def passes(self) -> List[int]:
        return sorted(self._global)

    def cells(self) -> List[dict]:
        return [
            {"band": band, "pass": pass_level}
            for band, pass_level in sorted(self._cells)
        ]


class _Frame:
    __slots__ = (
        "children",
        "index",
        "key",
        "action",
        "snap",
        "g",
        "tier",
        "started",
        "child_keys",
        "prep_action",
        "remaining",
        "fd",
        "dealt",
        "from_deal",
        "subtree_exp",
        "subtree_best_fd",
        "subtree_another_deal",
        "deal_index",
        "deal_parent_key",
        "probe_deal",
        "from_probe_deal",
        "probe_origin_dealt",
        "probe_event_index",
        "subtree_max_fnd",
        "direct_expanded",
        "exp_before_next_deal",
        "watch_kind",
    )

    def __init__(
        self,
        *,
        children: Optional[List[SolverAction]],
        index: int,
        key: ExactKey,
        action: Optional[SolverAction],
        snap: Optional[tuple],
        g: int,
        tier: int,
        started: bool,
        prep_action: Optional[SolverAction] = None,
        remaining: int = 0,
        from_deal: bool = False,
        from_probe_deal: bool = False,
    ) -> None:
        self.children = children
        self.index = index
        self.key = key
        self.action = action
        self.snap = snap
        self.g = g
        self.tier = tier
        self.started = started
        self.child_keys: set = set()
        self.prep_action = prep_action
        self.remaining = remaining
        self.fd = 0
        self.dealt = 0
        self.from_deal = from_deal
        self.subtree_exp = 0
        self.subtree_best_fd = 10**9
        self.subtree_another_deal = False
        self.deal_index: Optional[int] = None
        self.deal_parent_key: Optional[bytes] = None
        self.probe_deal = False
        self.from_probe_deal = from_probe_deal
        self.probe_origin_dealt = -1
        self.probe_event_index = -1
        self.subtree_max_fnd = 0
        self.direct_expanded = 0
        self.exp_before_next_deal = 0
        self.watch_kind = None


def _path_from_stack(stack: List[_Frame]) -> List[Action]:
    out: List[Action] = []
    for frame in stack[1:]:
        if frame.action is None:
            continue
        out.append(("deal",) if is_deal(frame.action) else frame.action)  # type: ignore[arg-type]
    return out


def format_moves_text(actions: Sequence[Action], *, header: str = "") -> str:
    lines = []
    if header:
        lines.append(header.rstrip())
        if not header.endswith("\n"):
            lines.append("")
    for action in actions:
        if action == ("deal",):
            lines.append("deal")
        else:
            src, dst, k = action  # type: ignore[misc]
            lines.append(f"move {src + 1} {dst + 1} {k}")
    lines.append("")
    return "\n".join(lines)


def unique_successor_actions(
    state: SpiderState,
    actions: Sequence[SolverAction],
    *,
    rules: MobilityWareRules = MW_RULES,
) -> List[SolverAction]:
    """Keep the first action for each exact child state."""

    seen = set()
    unique: List[SolverAction] = []
    for action in actions:
        snap = _capture(state, action)
        try:
            apply_action(state, action, rules=rules)
            key = pack_state(state)
        except (ValueError, AssertionError):
            _restore(state, snap)
            continue
        _restore(state, snap)
        if key in seen:
            continue
        seen.add(key)
        unique.append(action)
    return unique


CoverageTT = _CoverageTT


def _clip_depth_bands(
    depth_bands: Optional[Sequence[int]], max_depth: int
) -> Tuple[int, ...]:
    source = tuple(depth_bands) if depth_bands is not None else DEFAULT_DEPTH_BANDS
    clipped = tuple(band for band in source if 0 < band <= max_depth)
    if clipped:
        return clipped
    return (max(1, min(max_depth, source[-1] if source else 80)),)


def solve_progressive(
    root: SpiderState,
    *,
    max_nodes: int = 100_000,
    time_limit_s: float = 180.0,
    max_pass: int = 3,
    rules: MobilityWareRules = MW_RULES,
    target_foundations: int = 8,
    prep_ply: int = 1,
    max_depth: int = MAX_DEPTH_GUARD,
    depth_bands: Optional[Sequence[int]] = None,
    enable_saturation: bool = True,
    enable_audit: bool = True,
    enable_best_reveal_deal_probe: bool = False,
    enable_post_deal_audit: bool = False,
    enable_band_local_saturation: bool = False,
    audit_watch_keys: Optional[Sequence[bytes]] = None,
    start_pass: int = 0,
) -> ProgressiveSearchResult:
    """Iterative DFS with exact TT, A–D passes, and depth bands."""

    started = time.perf_counter()
    stats = SearchStats()
    memory = _CoverageTT()
    bands = _clip_depth_bands(depth_bands, max_depth)
    root_foundations = len(root.foundations)
    opening_stock = _stock_rows(root)
    opening_fd = _face_down(root)
    reveal_key = (opening_fd, -root_foundations, opening_stock, 0, 0)
    stock_key = (opening_stock, opening_fd, -root_foundations, 0, 0)
    foundation_key = (-root_foundations, opening_fd, opening_stock, 0, 0)
    reveal_path: List[Action] = []
    stock_path: List[Action] = []
    foundation_wit_path: List[Action] = []
    reveal_meta = (opening_fd, opening_stock, root_foundations, 0, 0)
    stock_meta = (opening_fd, opening_stock, root_foundations, 0, 0)
    foundation_meta = (opening_fd, opening_stock, root_foundations, 0, 0)
    first_foundation_path: List[Action] = []
    first_foundation_cost = 0
    solved_path: Optional[List[Action]] = None
    solved_cost = 0
    stop_reason = "band envelope"
    peak_rss = _rss_mb()
    unique_stock_seen = [set() for _ in range(6)]
    unique_deal_parent_seen = [set() for _ in range(6)]
    bands_used: List[int] = []
    fd_stock_meta = [(10**9, opening_stock, 0, 0, 0) for _ in range(6)]
    fd_stock_path: List[List[Action]] = [[] for _ in range(6)]
    fd_stock_meta[0] = (opening_fd, opening_stock, root_foundations, 0, 0)
    audit = RevealStockAudit() if enable_audit else None
    pda = PostDealAudit() if enable_post_deal_audit else None
    if pda is not None:
        pda.track_structure = True
        pda.watch(pack_state(root), origin="root")
        if audit_watch_keys:
            for key in audit_watch_keys:
                pda.watch(bytes(key), origin="seeded")
    stats.band_local_saturation = bool(enable_band_local_saturation)
    reveal_record_fd = [10**9] * 6
    reveal_seen_stock = [False] * 6
    probe_traces: List[dict] = []

    def reached_target(state: SpiderState) -> bool:
        if target_foundations >= 8:
            return state.is_solved()
        return (
            len(state.foundations) >= target_foundations
            and len(state.foundations) > root_foundations
        )

    def unwind(stack: List[_Frame], working_state: SpiderState, path_keys: set) -> None:
        while stack:
            frame = stack.pop()
            path_keys.discard(frame.key)
            if frame.snap is not None:
                _restore(working_state, frame.snap)

    def budget_exhausted(node_cap: int, deadline: float) -> bool:
        return stats.states_expanded >= node_cap or time.perf_counter() >= deadline

    def note_rss() -> None:
        nonlocal peak_rss
        if (stats.states_expanded & 2047) == 0:
            rss = _rss_mb()
            if rss is not None and (peak_rss is None or rss > peak_rss):
                peak_rss = rss

    def consider_tt(key: ExactKey, pass_level: int, remaining: int) -> str:
        covered = memory.max_covered_remaining(key, pass_level)
        if covered >= remaining:
            stats.tt_hits += 1
            stats.tt_depth_prunes += 1
            return "skip"
        if covered >= 0:
            stats.tt_reopens += 1
        return "search"

    def dfs_pass(
        pass_level: int, band: int, node_cap: int, deadline: float
    ) -> str:
        nonlocal reveal_key, stock_key, foundation_key
        nonlocal reveal_path, stock_path, foundation_wit_path
        nonlocal reveal_meta, stock_meta, foundation_meta
        nonlocal first_foundation_path, first_foundation_cost
        nonlocal solved_path, solved_cost, stop_reason

        working_state = root.clone()
        root_key = pack_state(working_state)
        if memory.skip(root_key, pass_level, band):
            return "exhausted"
        stack = [
            _Frame(
                children=None,
                index=0,
                key=root_key,
                action=None,
                snap=None,
                g=0,
                tier=-1,
                started=False,
                remaining=band,
            )
        ]
        path_keys = {root_key}

        while stack:
            if budget_exhausted(node_cap, deadline):
                stop_reason = (
                    "node limit" if stats.states_expanded >= node_cap else "time limit"
                )
                unwind(stack, working_state, path_keys)
                return "budget"

            frame = stack[-1]
            depth = len(stack) - 1
            if not frame.started:
                covered_before = memory.max_covered_remaining(
                    frame.key, pass_level
                )
                if consider_tt(frame.key, pass_level, frame.remaining) == "skip":
                    if pda is not None and pda.is_watched(frame.key):
                        pda.on_tt_skip(
                            key=frame.key,
                            pass_level=pass_level,
                            remaining=frame.remaining,
                            expansion=stats.states_expanded,
                            depth=depth,
                            fd=_face_down(working_state),
                            foundations=len(working_state.foundations),
                            stock_rows=_stock_rows(working_state),
                            covered_remaining=covered_before,
                            where="frame_start",
                        )
                    path_keys.discard(frame.key)
                    if frame.snap is not None:
                        _restore(working_state, frame.snap)
                    stack.pop()
                    continue
                new_key = frame.key not in memory.seen
                memory.mark_start(frame.key, pass_level, frame.remaining)
                frame.started = True
                stats.states_expanded += 1
                stats.max_depth = max(stats.max_depth, depth)
                stats.expansions_by_depth_bucket[_depth_bucket(depth)] += 1
                note_rss()
                foundations = len(working_state.foundations)
                fd = _face_down(working_state)
                stock_rows = _stock_rows(working_state)
                dealt = _stock_dealt_index(opening_stock, stock_rows)
                stats.states_by_stock_dealt[dealt] += 1
                frame.fd = fd
                frame.dealt = dealt
                if pda is not None and pda.is_watched(frame.key):
                    frame.watch_kind = pda.watched[frame.key]["origin"]
                if audit is not None or enable_best_reveal_deal_probe or pda is not None:
                    for ancestor in stack:
                        tracked = (
                            ancestor.from_deal
                            or ancestor.from_probe_deal
                            or ancestor.watch_kind
                        )
                        if not tracked:
                            continue
                        ancestor.subtree_exp += 1
                        if not ancestor.subtree_another_deal:
                            ancestor.exp_before_next_deal += 1
                        if fd < ancestor.subtree_best_fd:
                            ancestor.subtree_best_fd = fd
                        if dealt > ancestor.dealt:
                            ancestor.subtree_another_deal = True
                        if foundations > ancestor.subtree_max_fnd:
                            ancestor.subtree_max_fnd = foundations
                if new_key:
                    unique_stock_seen[dealt].add(frame.key)
                    if 0 <= pass_level < N_PASSES:
                        stats.unique_by_pass[pass_level] += 1
                if foundations > stats.max_foundations:
                    stats.max_foundations = foundations
                path_now = None

                def path() -> List[Action]:
                    nonlocal path_now
                    if path_now is None:
                        path_now = _path_from_stack(stack)
                    return path_now

                if audit is not None:
                    audit.on_expand(
                        key=frame.key,
                        fd=fd,
                        stock_rows=stock_rows,
                        foundations=foundations,
                        depth=depth,
                        cost=frame.g,
                        dealt=dealt,
                        node=stats.states_expanded,
                        pass_level=pass_level,
                        path=path(),
                    )
                if pda is not None and pda.track_structure:
                    runs = exposed_run_metrics(working_state)
                    pda.observe_structure(
                        fd=fd,
                        foundations=foundations,
                        longest_run=runs["longest_exposed_same_suit_run"],
                        adjacencies=runs["exposed_same_suit_adjacencies"],
                        empties=_empty_count(working_state),
                        mixed=_mixed_joins(working_state),
                        depth=depth,
                        expansion=stats.states_expanded,
                        path_fn=path,
                    )

                prev_fd_stock = fd_stock_meta[dealt]
                if fd < prev_fd_stock[0] or (
                    fd == prev_fd_stock[0]
                    and (depth, frame.g) < (prev_fd_stock[3], prev_fd_stock[4])
                ):
                    fd_stock_meta[dealt] = (
                        fd,
                        stock_rows,
                        foundations,
                        depth,
                        frame.g,
                    )
                    fd_stock_path[dealt] = path()
                    if pda is not None:
                        pda.watch(
                            frame.key, origin="best_fd", dealt=dealt, fd=fd
                        )

                r_key = (fd, -foundations, stock_rows, depth, frame.g)
                if r_key < reveal_key:
                    reveal_key = r_key
                    reveal_path = path()
                    reveal_meta = (fd, stock_rows, foundations, depth, frame.g)
                s_key = (stock_rows, fd, -foundations, depth, frame.g)
                if s_key < stock_key:
                    stock_key = s_key
                    stock_path = path()
                    stock_meta = (fd, stock_rows, foundations, depth, frame.g)
                f_key = (-foundations, fd, stock_rows, depth, frame.g)
                if f_key < foundation_key:
                    foundation_key = f_key
                    foundation_wit_path = path()
                    foundation_meta = (fd, stock_rows, foundations, depth, frame.g)
                if (
                    foundations > root_foundations
                    and stats.first_foundation_node is None
                ):
                    stats.first_foundation_node = stats.states_expanded
                    stats.first_foundation_depth = depth
                    stats.first_foundation_pass = pass_level
                    first_foundation_path = path()
                    first_foundation_cost = frame.g
                if reached_target(working_state):
                    solved_path = path()
                    solved_cost = frame.g
                    stop_reason = "target reached"
                    unwind(stack, working_state, path_keys)
                    return "solved"
                checkpoint = False
                if not reveal_seen_stock[dealt]:
                    reveal_seen_stock[dealt] = True
                    reveal_record_fd[dealt] = fd
                    stats.reveal_records[dealt] += 1
                elif fd < reveal_record_fd[dealt]:
                    reveal_record_fd[dealt] = fd
                    stats.reveal_records[dealt] += 1
                    checkpoint = True
                if pda is not None:
                    if checkpoint:
                        pda.watch(
                            frame.key,
                            origin="checkpoint_parent",
                            dealt=dealt,
                            fd=fd,
                        )
                    want_empty = stock_rows == 0 and fd <= pda.best_empty_fd
                    if want_empty or pda.is_watched(frame.key):
                        snap = inspect_state(working_state, rules=rules)
                        if want_empty:
                            pda.on_stock_empty(
                                key=frame.key,
                                pass_level=pass_level,
                                remaining=frame.remaining,
                                expansion=stats.states_expanded,
                                depth=depth,
                                snapshot=snap,
                            )
                        if pda.is_watched(frame.key):
                            frame.watch_kind = pda.watched[frame.key]["origin"]
                            if new_key:
                                tt_status = "novel"
                            elif covered_before >= 0:
                                tt_status = "reopen"
                            else:
                                tt_status = "novel"
                            pda.on_expand(
                                key=frame.key,
                                pass_level=pass_level,
                                remaining=frame.remaining,
                                expansion=stats.states_expanded,
                                depth=depth,
                                fd=fd,
                                foundations=foundations,
                                stock_rows=stock_rows,
                                tt_status=tt_status,
                                covered_remaining=covered_before,
                                snapshot=snap,
                            )
                if frame.remaining <= 0:
                    frame.children = []
                    frame.index = 0
                    continue
                frame.children = ordered_actions(
                    working_state,
                    pass_level,
                    rules=rules,
                    prep_ply=prep_ply,
                    stats=stats,
                    last_move=working_state.last_move,
                )
                frame.prep_action = stats.last_prep_action
                frame.index = 0
                frame.probe_deal = False
                if (
                    enable_best_reveal_deal_probe
                    and checkpoint
                    and working_state.can_deal(rules=rules)
                    and ("deal",) in working_state.enumerate_legal_actions(rules=rules)
                ):
                    without_deal = [
                        action for action in frame.children if not is_deal(action)
                    ]
                    frame.children = [("deal",)] + without_deal
                    frame.probe_deal = True
                    stats.probe_fires[dealt] += 1
                frame.deal_index = None
                for index, child_action in enumerate(frame.children):
                    if is_deal(child_action):
                        frame.deal_index = index
                        break
                if audit is not None:
                    deal_tier = None
                    if frame.deal_index is not None:
                        deal_tier = int(classify_tier(working_state, ("deal",)))
                    audit.on_children(
                        key=frame.key,
                        dealt=dealt,
                        children=frame.children,
                        pass_level=pass_level,
                        deal_tier=deal_tier,
                        prep_action=frame.prep_action,
                    )

            assert frame.children is not None
            if frame.index >= len(frame.children):
                memory.mark_done(frame.key, pass_level, frame.remaining)
                if pda is not None and (
                    frame.from_deal or frame.from_probe_deal or frame.watch_kind
                ):
                    pop_reason = "children_exhausted"
                    if not frame.children and frame.remaining <= 0:
                        pop_reason = "depth_band"
                    best_fd = (
                        frame.fd
                        if frame.subtree_best_fd >= 10**9
                        else frame.subtree_best_fd
                    )
                    pda.on_frame_finished(
                        key=frame.key,
                        pass_level=pass_level,
                        descendant_expansions=frame.subtree_exp,
                        direct_expanded=frame.direct_expanded,
                        exp_before_next_deal=frame.exp_before_next_deal,
                        best_descendant_fd=best_fd,
                        best_descendant_foundations=frame.subtree_max_fnd,
                        next_deal_reached=frame.subtree_another_deal,
                        pop_reason=pop_reason,
                        from_deal=frame.from_deal,
                    )
                if audit is not None and frame.from_deal:
                    audit.on_deal_finished(
                        {
                            "dealt": max(0, frame.dealt - 1),
                            "parent_key": frame.deal_parent_key,
                            "subtree_exp": frame.subtree_exp,
                            "subtree_best_fd": (
                                frame.fd
                                if frame.subtree_best_fd >= 10**9
                                else frame.subtree_best_fd
                            ),
                            "another_deal": frame.subtree_another_deal,
                            "tt_skip": False,
                        }
                    )
                if frame.from_probe_deal and 0 <= frame.probe_event_index < len(
                    probe_traces
                ):
                    event = probe_traces[frame.probe_event_index]
                    event["descendant_expansions"] = frame.subtree_exp
                    best_fd = frame.subtree_best_fd
                    if best_fd < 10**9:
                        event["best_descendant_fd"] = min(
                            event["best_descendant_fd"], best_fd
                        )
                    event["second_deal"] = frame.subtree_another_deal
                    event["deepest_dealt"] = max(event["deepest_dealt"], frame.dealt)
                    event["foundations"] = max(
                        event["foundations"], frame.subtree_max_fnd
                    )
                path_keys.discard(frame.key)
                if frame.snap is not None:
                    _restore(working_state, frame.snap)
                stack.pop()
                continue

            action = frame.children[frame.index]
            frame.index += 1
            child_tier = int(classify_tier(working_state, action))
            parent_stock_rows = _stock_rows(working_state)
            parent_dealt = _stock_dealt_index(opening_stock, parent_stock_rows)
            parent_watched_empty = (
                pda is not None
                and pass_level >= 1
                and parent_stock_rows == 0
                and pda.is_watched(frame.key)
            )
            parent_struct = cheap_structure(working_state) if (
                audit is not None and is_deal(action)
            ) else None
            pre_deal_snap = None
            if pda is not None and is_deal(action) and frame.probe_deal:
                pre_deal_snap = inspect_state(working_state, rules=rules)
            snap = _capture(working_state, action)
            try:
                cost = apply_action(working_state, action, rules=rules)
            except (ValueError, AssertionError):
                _restore(working_state, snap)
                continue
            stats.states_generated += 1
            child_key = pack_state(working_state)
            if child_key in path_keys:
                stats.path_cycles += 1
                if pda is not None:
                    pda.on_child_blocked(
                        key=child_key,
                        pass_level=pass_level,
                        remaining=frame.remaining - 1,
                        expansion=stats.states_expanded,
                        depth=depth,
                        kind="path_cycle",
                    )
                _restore(working_state, snap)
                continue
            if child_key in frame.child_keys:
                stats.duplicate_children += 1
                if pda is not None:
                    pda.on_child_blocked(
                        key=child_key,
                        pass_level=pass_level,
                        remaining=frame.remaining - 1,
                        expansion=stats.states_expanded,
                        depth=depth,
                        kind="child_dedup",
                    )
                _restore(working_state, snap)
                continue
            frame.child_keys.add(child_key)
            child_remaining = frame.remaining - 1
            tt_skip_child = memory.skip(child_key, pass_level, child_remaining)
            if parent_watched_empty and child_tier == int(Tier.B):
                pda.note_empty_b_child(
                    parent_key=frame.key,
                    action=action,
                    child_key=child_key,
                    pass_level=pass_level,
                    band=band,
                    novel=child_key not in memory.seen,
                    tt_skip=tt_skip_child,
                    expanded=not tt_skip_child,
                    fd=_face_down(working_state),
                    foundations=len(working_state.foundations),
                )
            if is_deal(action) and audit is not None and parent_struct is not None:
                child_struct = cheap_structure(working_state)
                ancestors = [
                    (anc.dealt, anc.fd, anc.key, index)
                    for index, anc in enumerate(stack)
                ]
                audit.on_deal(
                    ancestor_frames=ancestors,
                    parent_key=frame.key,
                    parent_path=_path_from_stack(stack),
                    parent_struct=parent_struct,
                    child_struct=child_struct,
                    child_key=child_key,
                    ordinal=frame.deal_index if frame.deal_index is not None else 0,
                    n_children=len(frame.children),
                    remaining=frame.remaining,
                    pass_level=pass_level,
                    child_novel=child_key not in memory.seen,
                    tt_skip=tt_skip_child,
                    prep_followed=False,
                    dealt=parent_dealt,
                )
            if tt_skip_child:
                stats.tt_hits += 1
                stats.tt_depth_prunes += 1
                if pda is not None:
                    pda.on_tt_skip(
                        key=child_key,
                        pass_level=pass_level,
                        remaining=child_remaining,
                        expansion=stats.states_expanded,
                        depth=depth + 1,
                        fd=_face_down(working_state),
                        foundations=len(working_state.foundations),
                        stock_rows=_stock_rows(working_state),
                        covered_remaining=memory.max_covered_remaining(
                            child_key, pass_level
                        ),
                        where="child_gen",
                    )
                    if is_deal(action) and frame.probe_deal and pre_deal_snap is not None:
                        post_snap = inspect_state(working_state, rules=rules)
                        pda.on_checkpoint_deal(
                            parent_key=frame.key,
                            child_key=child_key,
                            dealt=parent_dealt,
                            pass_level=pass_level,
                            depth=depth,
                            remaining=frame.remaining,
                            pre=pre_deal_snap,
                            post=post_snap,
                            child_novel=child_key not in memory.seen,
                            tt_skip=True,
                            expanded=False,
                            n_tableau=max(0, len(frame.children) - 1),
                            probe=True,
                        )
                if is_deal(action) and audit is not None:
                    audit.on_deal_finished(
                        {
                            "dealt": parent_dealt,
                            "parent_key": frame.key,
                            "subtree_exp": 0,
                            "subtree_best_fd": _face_down(working_state),
                            "another_deal": False,
                            "tt_skip": True,
                        }
                    )
                if is_deal(action) and frame.probe_deal:
                    stats.probe_tt_suppressed[parent_dealt] += 1
                    probe_traces.append(
                        {
                            "dealt": parent_dealt,
                            "pre_fd": frame.fd,
                            "post_fd": _face_down(working_state),
                            "pass": pass_level,
                            "depth": depth,
                            "n_tableau": max(0, len(frame.children) - 1),
                            "deal_legal": True,
                            "child_novel": child_key not in memory.seen,
                            "tt_skip": True,
                            "expanded": False,
                            "descendant_expansions": 0,
                            "best_descendant_fd": _face_down(working_state),
                            "deepest_dealt": parent_dealt,
                            "foundations": len(working_state.foundations),
                            "second_deal": False,
                            "path": _path_from_stack(stack),
                            "child_key_hex": child_key.hex(),
                            "parent_key_hex": frame.key.hex(),
                        }
                    )
                _restore(working_state, snap)
                continue
            if is_deal(action):
                stats.deals_executed += 1
                stats.deal_now_choices += 1
                stats.deals_executed_from_stock[parent_dealt] += 1
                if frame.key not in unique_deal_parent_seen[parent_dealt]:
                    unique_deal_parent_seen[parent_dealt].add(frame.key)
                if frame.probe_deal:
                    stats.probe_entered[parent_dealt] += 1
            elif frame.prep_action is not None and action == frame.prep_action:
                stats.prepared_deal_choices += 1
            stats.expanded_by_tier[child_tier] += 1
            path_keys.add(child_key)
            is_probe_child = bool(frame.probe_deal and is_deal(action))
            child_frame = _Frame(
                children=None,
                index=0,
                key=child_key,
                action=action,
                snap=snap,
                g=frame.g + cost,
                tier=child_tier,
                started=False,
                remaining=child_remaining,
                from_deal=is_deal(action),
                from_probe_deal=is_probe_child,
            )
            child_frame.deal_parent_key = frame.key if is_deal(action) else None
            child_frame.probe_origin_dealt = parent_dealt if is_probe_child else -1
            if is_probe_child:
                child_frame.probe_event_index = len(probe_traces)
                probe_traces.append(
                    {
                        "dealt": parent_dealt,
                        "pre_fd": frame.fd,
                        "post_fd": _face_down(working_state),
                        "pass": pass_level,
                        "depth": depth,
                        "n_tableau": max(0, len(frame.children) - 1),
                        "deal_legal": True,
                        "child_novel": child_key not in memory.seen,
                        "tt_skip": False,
                        "expanded": True,
                        "descendant_expansions": 0,
                        "best_descendant_fd": _face_down(working_state),
                        "deepest_dealt": parent_dealt + 1,
                        "foundations": len(working_state.foundations),
                        "second_deal": False,
                        "path": _path_from_stack(stack) + [("deal",)],
                        "child_key_hex": child_key.hex(),
                        "parent_key_hex": frame.key.hex(),
                    }
                )
            if pda is not None and is_deal(action) and frame.probe_deal:
                post_snap = inspect_state(working_state, rules=rules)
                pda.on_checkpoint_deal(
                    parent_key=frame.key,
                    child_key=child_key,
                    dealt=parent_dealt,
                    pass_level=pass_level,
                    depth=depth,
                    remaining=frame.remaining,
                    pre=pre_deal_snap or post_snap,
                    post=post_snap,
                    child_novel=child_key not in memory.seen,
                    tt_skip=False,
                    expanded=True,
                    n_tableau=max(0, len(frame.children) - 1),
                    probe=True,
                )
            frame.direct_expanded += 1
            stack.append(child_frame)
        return "exhausted"

    # Depth bands outer, A–D passes inner.  Remaining node/time budget is
    # split across remaining live (band, pass) cells.  A completed cell with
    # unique_new == 0 saturates that pass.  Cross-band (default) skips the
    # pass in later bands.  Band-local saturation skips only later slices of
    # the same (band, pass).  Saturation is scheduling only; the depth-aware
    # TT is unchanged and is never cleared.
    sat_book = SaturationBook(band_local=enable_band_local_saturation)
    start_pass = max(0, min(int(start_pass), max_pass))
    for band_index, band in enumerate(bands):
        remaining_bands = len(bands) - band_index
        remaining_nodes = max(0, max_nodes - stats.states_expanded)
        if remaining_nodes <= 0:
            stop_reason = "node limit"
            break
        now = time.perf_counter()
        remaining_time = (started + time_limit_s) - now
        if remaining_time <= 0:
            stop_reason = "time limit"
            break
        band_cap = stats.states_expanded + max(1, remaining_nodes // remaining_bands)
        band_deadline = now + remaining_time / remaining_bands
        stats.depth_band_used = band
        bands_used.append(band)
        if pda is not None:
            pda.current_band = band
        for pass_level in range(start_pass, max_pass + 1):
            stats.pass_reached = pass_level
            remaining_passes = max_pass + 1 - pass_level
            remaining_in_band = max(0, band_cap - stats.states_expanded)
            if remaining_in_band <= 0:
                break
            now = time.perf_counter()
            band_time_left = band_deadline - now
            if band_time_left <= 0:
                stop_reason = "time limit"
                break
            would_allocate = max(1, remaining_in_band // remaining_passes)
            inherited = enable_saturation and sat_book.inherited(pass_level, band)
            if enable_saturation and sat_book.is_saturated(pass_level, band):
                stats.slices_skipped += 1
                stats.expansions_redirected += would_allocate
                stats.band_pass_reports.append(
                    {
                        "band": band,
                        "pass": pass_level,
                        "expanded": 0,
                        "generated": 0,
                        "unique_total": len(memory),
                        "unique_new": 0,
                        "unique_new_per_expansion": 0.0,
                        "tt_hits": 0,
                        "depth_prunes": 0,
                        "reopens": 0,
                        "max_depth": stats.max_depth,
                        "stop": "saturated",
                        "face_down_best": reveal_meta[0],
                        "stock_best": stock_meta[1],
                        "max_foundations": stats.max_foundations,
                        "deals_considered": 0,
                        "deals_executed": 0,
                        "saturation_triggered": False,
                        "skipped": True,
                        "scheduled": False,
                        "saturation_inherited": inherited,
                        "band_local": enable_band_local_saturation,
                        "budget_redirected": would_allocate,
                    }
                )
                continue
            remaining_live = sum(
                1
                for index in range(pass_level, max_pass + 1)
                if not enable_saturation or not sat_book.is_saturated(index, band)
            )
            node_cap = stats.states_expanded + max(
                1, remaining_in_band // max(1, remaining_live)
            )
            deadline = now + band_time_left / max(1, remaining_live)
            before = {
                "expanded": stats.states_expanded,
                "generated": stats.states_generated,
                "tt_hits": stats.tt_hits,
                "prunes": stats.tt_depth_prunes,
                "reopens": stats.tt_reopens,
                "deals_c": stats.deals_considered,
                "deals_x": stats.deals_executed,
                "unique": len(memory),
            }
            outcome = dfs_pass(pass_level, band, node_cap, deadline)
            expanded = stats.states_expanded - before["expanded"]
            unique_new = len(memory) - before["unique"]
            saturation_triggered = enable_saturation and unique_new == 0
            if saturation_triggered:
                sat_book.mark(pass_level, band)
            stats.band_pass_reports.append(
                {
                    "band": band,
                    "pass": pass_level,
                    "expanded": expanded,
                    "generated": stats.states_generated - before["generated"],
                    "unique_total": len(memory),
                    "unique_new": unique_new,
                    "unique_new_per_expansion": unique_new / max(1, expanded),
                    "tt_hits": stats.tt_hits - before["tt_hits"],
                    "depth_prunes": stats.tt_depth_prunes - before["prunes"],
                    "reopens": stats.tt_reopens - before["reopens"],
                    "max_depth": stats.max_depth,
                    "stop": outcome,
                    "face_down_best": reveal_meta[0],
                    "stock_best": stock_meta[1],
                    "max_foundations": stats.max_foundations,
                    "deals_considered": stats.deals_considered - before["deals_c"],
                    "deals_executed": stats.deals_executed - before["deals_x"],
                    "saturation_triggered": saturation_triggered,
                    "skipped": False,
                    "scheduled": True,
                    "saturation_inherited": False,
                    "band_local": enable_band_local_saturation,
                    "budget_redirected": 0,
                }
            )
            if outcome == "solved":
                break
            if stats.states_expanded >= max_nodes:
                stop_reason = "node limit"
                break
            if time.perf_counter() - started >= time_limit_s:
                stop_reason = "time limit"
                break
        if solved_path is not None or stats.states_expanded >= max_nodes:
            break
        if time.perf_counter() - started >= time_limit_s:
            break
    stats.saturated_passes = sat_book.passes()
    stats.saturated_band_passes = sat_book.cells()
    stats.probe_events = list(probe_traces)

    for index in range(6):
        stats.unique_by_stock_dealt[index] = len(unique_stock_seen[index])
        stats.unique_deal_parents[index] = len(unique_deal_parent_seen[index])
    stats.unique_exact_states = len(memory)
    stats.peak_rss_mb = peak_rss if peak_rss is not None else _rss_mb()
    elapsed = time.perf_counter() - started
    actions = (
        solved_path
        if solved_path is not None
        else (first_foundation_path or reveal_path)
    )
    cost = (
        solved_cost
        if solved_path is not None
        else (first_foundation_cost if first_foundation_path else reveal_meta[4])
    )
    replay_ok = False
    if actions:
        probe = root.clone()
        try:
            paid = replay_actions(probe, list(actions))
            replay_ok = paid == cost
            if solved_path is not None and target_foundations >= 8:
                replay_ok = replay_ok and probe.is_solved()
            elif solved_path is not None:
                replay_ok = replay_ok and len(probe.foundations) >= target_foundations
            elif stats.max_foundations > root_foundations:
                replay_ok = replay_ok and len(probe.foundations) >= stats.max_foundations
        except (ValueError, AssertionError):
            replay_ok = False

    fd_by_stock: List[dict] = []
    for dealt in range(6):
        meta = fd_stock_meta[dealt]
        if meta[0] >= 10**9:
            fd_by_stock.append(
                {
                    "deals_completed": dealt,
                    "face_down": None,
                    "stock_rows": None,
                    "foundations": None,
                    "depth": None,
                    "cost": None,
                    "actions": [],
                }
            )
        else:
            fd_by_stock.append(
                {
                    "deals_completed": dealt,
                    "face_down": meta[0],
                    "stock_rows": meta[1],
                    "foundations": meta[2],
                    "depth": meta[3],
                    "cost": meta[4],
                    "actions": list(fd_stock_path[dealt]),
                }
            )

    if pda is not None:
        pda.finalize(
            opening=root,
            fd_by_stock=fd_by_stock,
            band_pass_reports=stats.band_pass_reports,
            stop_reason=stop_reason,
            max_pass=max_pass,
            saturated_passes=stats.saturated_passes,
            max_foundations=stats.max_foundations,
            nodes=stats.states_expanded,
            rules=rules,
        )

    return ProgressiveSearchResult(
        solved=solved_path is not None,
        actions=list(actions),
        cost=cost,
        nodes=stats.states_expanded,
        elapsed_s=elapsed,
        pass_reached=stats.pass_reached,
        max_foundations=stats.max_foundations,
        min_face_down=reveal_meta[0],
        min_stock_rows=reveal_meta[1],
        foundation_path=list(first_foundation_path),
        foundation_cost=first_foundation_cost,
        stop_reason=stop_reason,
        replay_ok=replay_ok,
        stats=stats,
        first_foundation_actions=list(first_foundation_path),
        identified_face_down=reveal_meta[0],
        identified_stock_rows=reveal_meta[1],
        states_per_sec=(stats.states_expanded / elapsed if elapsed > 0 else 0.0),
        depth_bands_used=list(bands_used),
        best_reveal_actions=list(reveal_path),
        best_reveal_fd=reveal_meta[0],
        best_reveal_stock=reveal_meta[1],
        best_reveal_foundations=reveal_meta[2],
        best_reveal_depth=reveal_meta[3],
        best_reveal_cost=reveal_meta[4],
        best_stock_actions=list(stock_path),
        best_stock_fd=stock_meta[0],
        best_stock_stock=stock_meta[1],
        best_stock_foundations=stock_meta[2],
        best_stock_depth=stock_meta[3],
        best_stock_cost=stock_meta[4],
        best_foundation_actions=list(foundation_wit_path),
        best_foundation_fd=foundation_meta[0],
        best_foundation_stock=foundation_meta[1],
        best_foundation_foundations=foundation_meta[2],
        best_foundation_depth=foundation_meta[3],
        best_foundation_cost=foundation_meta[4],
        best_fd_by_stock_dealt=fd_by_stock,
        audit=audit,
        probe_events=list(probe_traces),
        post_deal_audit=pda,
    )
