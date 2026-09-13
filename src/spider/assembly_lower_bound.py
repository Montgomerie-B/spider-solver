"""Admissible stock-empty assembly cost-to-go.

Current-state facts only. No route history, no canonical, no suit
preference. Active only when the stock is empty.

Physical remaining suit material is represented as disjoint rank
intervals (visible same-suit descending components, including
singletons, plus face-down singleton cards). For each unfinished
suit we compute the minimum number of those intervals needed to
multicover demand ``m`` copies of ranks 1..13, then convert units
to a paid-move lower bound.

Admissibility argument
----------------------
Stock-empty engine facts (see move-effect tests):

* a legal tableau action moves one same-suit movable block;
* it can merge that block with at most one same-suit destination;
* ``check_seq(dst)`` removes at most one foundation;
* Deal is unavailable, so a foundation cannot be removed for free.

For a suit with ``m`` remaining foundations and ``u`` physical
interval units minimally required to supply the needed rank
multiplicity:

* at least ``m`` tableau actions are required (one foundation
  trigger per action);
* assembling ``u`` units into ``m`` sequences requires at least
  ``u - m`` same-suit joins, and each action supplies at most one
  join.

The last join may also trigger the foundation, so the two counts
must not be added. Therefore::

    suit_lb = max(m, u - m)

One action belongs to one suit (one block, one destination, at most
one foundation), so::

    assembly_lb = sum(suit_lb)

The bound ignores blockers, parking, off-suit receivers, and
geometry. That is intentional: it is a lower bound. If covering is
infeasible or any subcase is undefined, the suit contributes only
``m`` (still admissible) and never a fabricated high number.

Interval multicover
-------------------
Ranks are a line. Given intervals, the leftmost-residual /
farthest-reaching greedy is optimal for interval multicover
(standard exchange: any interval chosen to cover the leftmost
unsatisfied rank may be replaced by a farthest-reaching alternative
without losing coverage to the right; points left of the residual
are already satisfied). Tests cross-check greedy against brute-force
subset search on many small instances.
"""

from __future__ import annotations

from collections import Counter
from typing import List, Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.research_actions import foundation_suits, stock_rows
from spider.structural_analysis import SUITS

Interval = Tuple[int, int]
RANKS = tuple(range(1, 14))


def copies_remaining(state: SpiderState) -> dict:
    founded = Counter(foundation_suits(state))
    return {suit: max(0, 2 - int(founded.get(suit) or 0)) for suit in SUITS}


def physical_units(state: SpiderState, suit: str) -> List[Interval]:
    """Disjoint remaining intervals of ``suit``. Face-down cards are singletons."""

    units: List[Interval] = []
    for col in state.columns:
        for card in col.face_down:
            if card.suit == suit:
                units.append((card.rank, card.rank))
        up = col.face_up
        i = 0
        while i < len(up):
            j = i + 1
            while (
                j < len(up)
                and up[j].suit == up[i].suit
                and up[j - 1].rank == up[j].rank + 1
            ):
                j += 1
            if up[i].suit == suit:
                high = int(up[i].rank)
                low = int(up[j - 1].rank)
                if low > high:
                    low, high = high, low
                units.append((low, high))
            i = j
    return units


def min_interval_multicover(
    intervals: Sequence[Interval],
    demand: Sequence[int],
) -> Optional[int]:
    """Minimum intervals to meet per-rank demand. ``None`` if infeasible.

    ``demand[r]`` is required coverage of rank ``r`` for ``r`` in 1..13.
    Greedy leftmost-residual / farthest-reach. Optimal for intervals.
    """

    need = [0] + [int(demand[r]) if r < len(demand) else 0 for r in RANKS]
    unused = [(int(lo), int(hi), i) for i, (lo, hi) in enumerate(intervals)]
    used = [False] * len(unused)
    chosen = 0
    for p in RANKS:
        while need[p] > 0:
            best_i = -1
            best_hi = -1
            for i, (lo, hi, _orig) in enumerate(unused):
                if used[i] or lo > p or hi < p:
                    continue
                if hi > best_hi:
                    best_hi = hi
                    best_i = i
            if best_i < 0:
                return None
            lo, hi, _orig = unused[best_i]
            used[best_i] = True
            chosen += 1
            for r in range(lo, hi + 1):
                if 1 <= r <= 13 and need[r] > 0:
                    need[r] -= 1
    return chosen


def brute_min_interval_multicover(
    intervals: Sequence[Interval],
    demand: Sequence[int],
) -> Optional[int]:
    """Exact subset enumeration. For tests only (n <= 16)."""

    n = len(intervals)
    if n > 16:
        raise ValueError("brute-force limited to 16 intervals")
    need = [int(demand[r]) if r < len(demand) else 0 for r in range(14)]
    best: Optional[int] = None
    for mask in range(1 << n):
        cov = [0] * 14
        cnt = 0
        m = mask
        i = 0
        while m:
            if m & 1:
                lo, hi = intervals[i]
                cnt += 1
                for r in range(int(lo), int(hi) + 1):
                    if 1 <= r <= 13:
                        cov[r] += 1
            m >>= 1
            i += 1
        if all(cov[r] >= need[r] for r in RANKS):
            if best is None or cnt < best:
                best = cnt
    return best


def suit_lower_bound(m: int, u: Optional[int]) -> Tuple[int, bool]:
    """Return ``(suit_lb, defined)``. Undefined cover falls back to ``m``."""

    m = max(0, int(m))
    if m == 0:
        return 0, True
    if u is None:
        return m, False
    u = int(u)
    return max(m, u - m), True


def assembly_bound_detail(state: SpiderState) -> dict:
    """Full telemetry. Inactive (h=0) while stock remains."""

    rows = stock_rows(state)
    remaining = copies_remaining(state)
    by_suit = {}
    total = 0
    u_total = 0
    defined = True
    if rows != 0:
        for suit in SUITS:
            by_suit[suit] = {
                "m": remaining[suit],
                "u": None,
                "suit_lb": 0,
                "units": [],
                "feasible": None,
                "active": False,
            }
        return {
            "h": 0,
            "active": False,
            "stock_rows": rows,
            "defined": True,
            "u_total": 0,
            "by_suit": by_suit,
            "copies_remaining": remaining,
            "foundations": len(state.foundations),
        }
    for suit in SUITS:
        m = remaining[suit]
        units = physical_units(state, suit) if m else []
        if m <= 0:
            by_suit[suit] = {
                "m": 0,
                "u": 0,
                "suit_lb": 0,
                "units": [],
                "feasible": True,
                "active": False,
            }
            continue
        demand = [0] + [m] * 13
        u = min_interval_multicover(units, demand)
        lb, ok = suit_lower_bound(m, u)
        if not ok:
            defined = False
        total += lb
        if u is not None:
            u_total += u
        by_suit[suit] = {
            "m": m,
            "u": u,
            "suit_lb": lb,
            "units": list(units),
            "n_units": len(units),
            "feasible": u is not None,
            "active": True,
        }
    return {
        "h": int(total),
        "active": True,
        "stock_rows": rows,
        "defined": defined,
        "u_total": u_total,
        "by_suit": by_suit,
        "copies_remaining": remaining,
        "foundations": len(state.foundations),
    }


def assembly_lb(state: SpiderState) -> int:
    """Admissible remaining paid-move lower bound. 0 if stock remains."""

    return int(assembly_bound_detail(state)["h"])


def stock_empty_assembly_h(state: SpiderState, g: int = 0) -> int:
    """Kernel callback. ``g`` unused; identity is cheapest-g without h."""

    if stock_rows(state) != 0:
        return 0
    return assembly_lb(state)


def completion_key(state: SpiderState, g: int, *, detail: Optional[dict] = None) -> Optional[tuple]:
    """COMPLETION lane key. Inactive before stock exhaustion.

    Primary term is ``f = g + admissible_lb``. No fitted weights.
    """

    if stock_rows(state) != 0:
        return None
    info = detail if detail is not None else assembly_bound_detail(state)
    h = int(info["h"])
    from spider.research_actions import tableau_actions
    from spider.structural_analysis import current_tableau_summary, interference_debt
    from spider.operational_viability import rank_ready_suits

    s = current_tableau_summary(state)
    ranked = rank_ready_suits(state, summary=s, g=g)
    best = ranked.get("best") or {}
    debt = interference_debt(state)
    legal = len(tableau_actions(state))
    blockers = int(best.get("relevant_blockers") or 0)
    bounds = int(debt.get("boundaries_total") or 0)
    return (
        int(g) + h,
        h,
        -int(s["foundations"]),
        int(info.get("u_total") or 0),
        blockers,
        bounds,
        -legal,
        int(g),
    )
