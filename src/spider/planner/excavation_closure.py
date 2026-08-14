"""Bounded AND/OR excavation-dependency closure.

Diagnostic only. Not a search layer and not wired into plan_search.

For each target column, walk the known excavation order and estimate the
*causal* difficulty of peeling it: every hop needs a rank+1 destination
(or an empty, for a King). Destinations are OR-nodes (duplicate copies
are interchangeable). Exposing a buried destination is an AND of the
peels that uncover it.

HARD facts: locations, currently legal dests, stock epoch, empty count,
hop sequence, whether a dest exists at all.

HEURISTIC: paid prep / total excavation cost, derived from peel counts
and shared (memoised) expose tasks. Not a proof bound.

No deal-id or column-id strategy constants.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Set, Tuple

from spider.cards import Card
from spider.engine import SpiderState
from spider.planner.backward_strategy import (
    BuriedCardFact,
    CardLocation,
    LocationKind,
    analyze_buried_cards,
    locate_all_cards,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import longest_movable_k


MAX_RECURSE = 5
SPACE_PENALTY = 8  # HEURISTIC peels-equivalent if a King needs an empty we do not have


class DestAvailability(str, Enum):
    EXPOSED_TOP = "exposed_top"
    FACE_UP_BURIED = "face_up_buried"
    FACE_DOWN = "face_down"
    FUTURE_STOCK = "future_stock"
    EMPTY = "empty"
    NONE = "none"


@dataclass(frozen=True)
class Hop:
    """HARD: one known peel in a column's excavation order."""

    column: int
    index: int  # 0 = current face-up run
    card: Card
    k: int
    need_rank: Optional[int]  # rank+1 dest, or None for King (needs empty)


@dataclass(frozen=True)
class DestOption:
    """HARD location of one interchangeable destination copy."""

    loc: CardLocation
    availability: DestAvailability
    note: str


@dataclass(frozen=True)
class HopClosure:
    """AND/OR result for one hop."""

    hop: Hop
    options: Tuple[DestOption, ...]
    chosen: Optional[DestOption]
    hard_ready: bool
    blocked: bool
    future_stock: bool
    needs_space: bool
    # HEURISTIC
    prep_cost: int
    prep_tasks: Tuple[Tuple[int, int], ...]  # (column, hops_to_expose)
    notes: Tuple[str, ...]


@dataclass(frozen=True)
class ProjectClosure:
    """Dependency closure of fully excavating one column."""

    column: int
    face_down: int
    hops: Tuple[Hop, ...]
    hop_closures: Tuple[HopClosure, ...]
    # HARD
    direct_target_moves: int
    dest_prep_columns: Tuple[int, ...]
    dependency_depth: int
    branching: int
    blocked_deps: int
    future_stock_deps: int
    needs_temp_space: bool
    earliest_epoch: int
    last_hop_ready_or_prepable: bool
    emptyable_this_epoch: bool
    # HEURISTIC
    estimated_prep_cost: int
    estimated_total_cost: int
    latent_workspace: bool
    valuable_en_route: Tuple[str, ...]
    unlock_value: float
    reasons: Tuple[str, ...]


@dataclass(frozen=True)
class RankedClosure:
    column: int
    combined: float
    forward: float
    backward: float
    est_cost: int
    depth: int
    emptyable: bool
    needs_space: bool
    label: str
    reasons: Tuple[str, ...]


def column_hops(state: SpiderState, col: int) -> Tuple[Hop, ...]:
    """Known excavation order: current movable run, then each hidden card."""
    pile = state.columns[col]
    hops: List[Hop] = []
    if pile.face_up:
        k = longest_movable_k(state, col) or 1
        head = pile.face_up[-k]
        need = (head.rank + 1) if head.rank < 13 else None
        hops.append(Hop(col, 0, head, k, need))
    for i, card in enumerate(reversed(pile.face_down)):
        need = (card.rank + 1) if card.rank < 13 else None
        hops.append(Hop(col, i + 1, card, 1, need))
    return tuple(hops)


def _availability(loc: CardLocation) -> DestAvailability:
    if loc.kind == LocationKind.FACE_UP_TOP:
        return DestAvailability.EXPOSED_TOP
    if loc.kind == LocationKind.FACE_UP_BURIED:
        return DestAvailability.FACE_UP_BURIED
    if loc.kind == LocationKind.FACE_DOWN:
        return DestAvailability.FACE_DOWN
    if loc.kind == LocationKind.STOCK:
        return DestAvailability.FUTURE_STOCK
    return DestAvailability.NONE


def dest_options(
    state: SpiderState,
    need_rank: Optional[int],
    *,
    locs: Sequence[CardLocation],
    exclude_column: Optional[int] = None,
) -> Tuple[DestOption, ...]:
    """OR-node: every interchangeable copy that could receive this hop."""
    if need_rank is None:
        # King: only an empty (now or later).
        if empty_count(state) > 0:
            dummy = CardLocation(Card("s", 13), LocationKind.FACE_UP_TOP, None, 0, None, "empty")
            return (
                DestOption(dummy, DestAvailability.EMPTY, "fact: empty exists now"),
            )
        return (
            DestOption(
                CardLocation(Card("s", 13), LocationKind.STOCK, None, 0, None, "need empty"),
                DestAvailability.NONE,
                "fact: King needs empty; none now",
            ),
        )
    opts: List[DestOption] = []
    for loc in locs:
        if loc.card.rank != need_rank:
            continue
        if loc.kind == LocationKind.FOUNDATION:
            continue
        if loc.column is not None and loc.column == exclude_column:
            # Same-column dest is only useful after earlier hops leave it
            # as a top of the *target* — not a receiver for this peel.
            continue
        av = _availability(loc)
        if av == DestAvailability.NONE:
            continue
        opts.append(
            DestOption(
                loc,
                av,
                f"fact: {loc.card} {av.value} {loc.note}",
            )
        )
    return tuple(opts)


def _hops_to_make_top(state: SpiderState, loc: CardLocation) -> Optional[int]:
    """HARD peel-count to make this copy a column top. None if not tableau."""
    if loc.kind == LocationKind.FACE_UP_TOP:
        return 0
    if loc.column is None:
        return None
    pile = state.columns[loc.column]
    if loc.kind == LocationKind.FACE_UP_BURIED:
        # One hop if the suffix above it is a single descending run (usual).
        return 1 if loc.depth > 0 else 0
    if loc.kind == LocationKind.FACE_DOWN:
        n_fu = 1 if pile.face_up else 0
        return n_fu + loc.depth  # depth == reveal_order
    return None


class _Closer:
    def __init__(self, state: SpiderState, locs: Sequence[CardLocation]):
        self.state = state
        self.locs = tuple(locs)
        self.epoch = current_stock_epoch(state, 5)
        self.memo_or: Dict[Tuple[int, int], HopClosure] = {}

    def _or_score(self, loc: CardLocation) -> int:
        n = _hops_to_make_top(self.state, loc)
        if n is None or loc.column is None:
            return 99
        hops = column_hops(self.state, loc.column)
        extra = 0
        if hops:
            opts = dest_options(
                self.state, hops[0].need_rank, locs=self.locs,
                exclude_column=loc.column,
            )
            if not any(
                o.availability in (DestAvailability.EXPOSED_TOP, DestAvailability.EMPTY)
                for o in opts
            ):
                extra = 2
        return n + extra

    def collect_tasks(
        self,
        col: int,
        n_peels: int,
        depth: int,
        acc: Dict[int, int],
        visiting: Set[int],
    ) -> None:
        """AND-union of dest-prep peels. Each helper column kept at max depth."""
        if n_peels <= 0 or depth >= MAX_RECURSE or col in visiting:
            return
        visiting.add(col)
        for hop in column_hops(self.state, col)[:n_peels]:
            hc = self._close_hop(hop, depth)
            for tcol, n in hc.prep_tasks:
                if tcol == col:
                    continue
                if n > acc.get(tcol, 0):
                    acc[tcol] = n
                    self.collect_tasks(tcol, n, depth + 1, acc, visiting)
        visiting.discard(col)

    def _close_hop(self, hop: Hop, depth: int) -> HopClosure:
        opts = dest_options(
            self.state, hop.need_rank, locs=self.locs, exclude_column=hop.column
        )
        notes: List[str] = []
        needs_space = hop.need_rank is None and empty_count(self.state) == 0
        future = any(o.availability == DestAvailability.FUTURE_STOCK for o in opts)
        exposed = [o for o in opts if o.availability in (
            DestAvailability.EXPOSED_TOP, DestAvailability.EMPTY
        )]
        if exposed:
            chosen = min(exposed, key=lambda o: (o.loc.column is None, o.loc.column or 0))
            return HopClosure(
                hop, opts, chosen, True, False, False, False, 0, (),
                ("fact: destination currently a top or empty",),
            )
        if needs_space:
            return HopClosure(
                hop, opts, None, False, True, False, True, SPACE_PENALTY, (),
                ("fact: King has no empty; HEURISTIC space penalty",),
            )
        buried = [o for o in opts if o.availability in (
            DestAvailability.FACE_DOWN, DestAvailability.FACE_UP_BURIED
        )]
        if not buried and future:
            stock_eps = [
                o.loc.stock_epoch for o in opts
                if o.loc.stock_epoch is not None
            ]
            ep = min(stock_eps) if stock_eps else self.epoch + 1
            return HopClosure(
                hop, opts, None, False, False, True, False, 6, (),
                (f"fact: dest only in stock from epoch {ep}",),
            )
        if not buried:
            return HopClosure(
                hop, opts, None, False, True, False, False, 12, (),
                ("fact: no remaining dest copy in tableau or stock",),
            )
        # OR: cheapest interchangeable copy to expose.
        best: Optional[DestOption] = None
        best_n = 99
        best_score = 99
        for o in buried:
            n = _hops_to_make_top(self.state, o.loc)
            if n is None or o.loc.column is None or o.loc.column == hop.column:
                continue
            score = self._or_score(o.loc)
            if score < best_score:
                best_score = score
                best_n = n
                best = o
        if best is None:
            if future:
                return HopClosure(
                    hop, opts, None, False, False, True, False, 6, (),
                    ("fact: no off-column tableau dest; stock remains",),
                )
            return HopClosure(
                hop, opts, None, False, True, False, False, 10, (),
                ("heuristic: dest options not independently exposable",),
            )
        notes.append(
            f"heuristic: choose {best.loc.card} ({best.availability.value}) "
            f"on col {best.loc.column + 1}, {best_n} peel(s)"
        )
        return HopClosure(
            hop, opts, best, False, False, False, False,
            0, ((best.loc.column, best_n),), tuple(notes),
        )


def close_column(
    state: SpiderState,
    col: int,
    *,
    locs: Optional[Sequence[CardLocation]] = None,
    buried: Sequence[BuriedCardFact] = (),
    closer: Optional[_Closer] = None,
) -> ProjectClosure:
    locs = tuple(locs) if locs is not None else locate_all_cards(state)
    hops = column_hops(state, col)
    cl = closer or _Closer(state, locs)
    hcs = tuple(cl._close_hop(h, 0) for h in hops)
    acc: Dict[int, int] = {}
    for hc in hcs:
        for tcol, n in hc.prep_tasks:
            if tcol == col:
                continue
            if n > acc.get(tcol, 0):
                acc[tcol] = n
    visiting: Set[int] = {col}
    for tcol, n in list(acc.items()):
        cl.collect_tasks(tcol, n, 1, acc, visiting)
    tasks = tuple(sorted(acc.items()))
    # Shared dest-prep: charge each helper column once at its max peel depth.
    prep = sum(n for _c, n in tasks)
    depth = max((n for _c, n in tasks), default=0)
    extra = 0
    for hc in hcs:
        if not hc.prep_tasks:
            extra += hc.prep_cost
    # Direct peels of the target.
    direct = len(hops)
    total = direct + prep + extra
    blocked = sum(1 for hc in hcs if hc.blocked)
    stock_n = sum(1 for hc in hcs if hc.future_stock)
    space = any(hc.needs_space for hc in hcs)
    branch = 0
    for hc in hcs:
        branch += max(0, len(hc.options) - 1)
    epoch = cl.epoch
    if stock_n:
        eps = []
        for hc in hcs:
            if not hc.future_stock:
                continue
            for o in hc.options:
                if o.loc.stock_epoch is not None:
                    eps.append(o.loc.stock_epoch)
        if eps:
            epoch = max(epoch, min(eps))
    if space and empty_count(state) == 0:
        epoch = max(epoch, cl.epoch)  # still this epoch if we create space
    last_ok = True
    if hops:
        last_ok = (not hcs[-1].blocked) or bool(hcs[-1].prep_tasks)
    emptyable = (
        (not space)
        and stock_n == 0
        and blocked == 0
        and last_ok
    )
    pile = state.columns[col]
    deepest = pile.face_down[0] if pile.face_down else (
        pile.face_up[0] if pile.face_up else None
    )
    latent = bool(pile.face_down) and (deepest is None or deepest.rank < 13)
    if emptyable:
        latent = True
    val_cards = tuple(
        f"{b.card} {b.urgency.value}"
        for b in buried
        if b.column == col and b.value_score >= 16
    )
    unlock = sum(max(0.0, b.value_score) for b in buried if b.column == col)
    reasons = [
        f"fact: hops={direct} fd={len(pile.face_down)}",
        f"fact: blocked={blocked} stock_deps={stock_n} space={space} "
        f"branch={branch} depth={depth}",
        f"heuristic: prep={prep} extra={extra} total={total} emptyable={emptyable}",
    ]
    if tasks:
        reasons.append(
            "heuristic: shared dest-prep "
            + ", ".join(f"col {c+1}×{n}" for c, n in tasks)
        )
    return ProjectClosure(
        column=col,
        face_down=len(pile.face_down),
        hops=hops,
        hop_closures=hcs,
        direct_target_moves=direct,
        dest_prep_columns=tuple(c for c, _n in tasks),
        dependency_depth=depth,
        branching=branch,
        blocked_deps=blocked,
        future_stock_deps=stock_n,
        needs_temp_space=space,
        earliest_epoch=epoch,
        last_hop_ready_or_prepable=last_ok,
        emptyable_this_epoch=emptyable,
        estimated_prep_cost=prep + extra,
        estimated_total_cost=total,
        latent_workspace=latent,
        valuable_en_route=val_cards,
        unlock_value=unlock,
        reasons=tuple(reasons),
    )


def close_all_columns(
    state: SpiderState,
    *,
    buried: Optional[Sequence[BuriedCardFact]] = None,
) -> Tuple[ProjectClosure, ...]:
    locs = locate_all_cards(state)
    buried = buried if buried is not None else analyze_buried_cards(state)
    closer = _Closer(state, locs)
    out = [
        close_column(state, i, locs=locs, buried=buried, closer=closer)
        for i in range(10)
        if not state.columns[i].is_empty()
    ]
    return tuple(out)


def rank_closures(
    closures: Sequence[ProjectClosure],
    *,
    epoch: int,
) -> Tuple[RankedClosure, ...]:
    """Forward feasibility (closure) first, backward value second.

    Diagnostic only. Does not replace ACCESS or plan search.
    """
    ranked: List[RankedClosure] = []
    for p in closures:
        if p.face_down == 0 and not p.hops:
            continue
        # FORWARD: cheaper, shallower, this-epoch, no forced space.
        cost = max(1, p.estimated_total_cost)
        fwd = 1.0 / (1.0 + 0.22 * cost)
        fwd *= 1.0 / (1.0 + 0.15 * p.dependency_depth)
        if p.blocked_deps:
            fwd *= 0.45 ** p.blocked_deps
        if p.future_stock_deps:
            fwd *= 0.6 ** p.future_stock_deps
        if p.needs_temp_space:
            fwd *= 0.4
        if p.earliest_epoch > epoch:
            fwd *= 0.35
        if p.emptyable_this_epoch:
            fwd *= 1.15
        # BACKWARD: buried value + completion prize.
        bwd = min(1.0, p.unlock_value / 50.0)
        if p.latent_workspace:
            bwd += 0.12
        if p.emptyable_this_epoch:
            bwd += 0.18
        if p.valuable_en_route:
            bwd += min(0.15, 0.04 * len(p.valuable_en_route))
        # Feasibility is the point of this diagnostic.
        combined = 0.62 * fwd + 0.38 * bwd
        label = (
            f"col {p.column + 1} fd={p.face_down} cost~{p.estimated_total_cost} "
            f"depth={p.dependency_depth} emptyable={int(p.emptyable_this_epoch)}"
        )
        ranked.append(
            RankedClosure(
                p.column, combined, fwd, bwd, p.estimated_total_cost,
                p.dependency_depth, p.emptyable_this_epoch, p.needs_temp_space,
                label, p.reasons,
            )
        )
    return tuple(sorted(ranked, key=lambda r: (-r.combined, r.est_cost, r.column)))
