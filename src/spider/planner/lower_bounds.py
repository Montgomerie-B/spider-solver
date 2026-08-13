"""Admissible lower bounds for corrected MobilityWare cost (Sprint 1E).

FACT / ADMISSIBLE / HEURISTIC layers are explicit.

Proof notes (engine-checked under corrected MW_RULES)
----------------------------------------------------
Free tableau move (cost 0) requires source_face_down_count == 0 and full
face-up relocate to empty. Therefore a free move NEVER reveals a face-down
card on the source (maybe_flip has nothing to flip) and the destination was
empty (no face-down there either).

However the *naive* bound

    h = remaining_face_down + remaining_deals

is NOT admissible as a sum of unit paid events, because:

1. One *paid* tableau move can flip the source AND flip the destination after
   automatic foundation removal (two reveals, one paid move).
2. A *stock deal* (cost 1) can also trigger foundation removal + maybe_flip
   on up to 10 columns, revealing face-down cards without an extra tableau move.

Therefore this module uses a proof-safe combination:

    h_deals = remaining_stock_deals
    max_deal_reveals = 10 * h_deals   # at most one foundation flip per column per deal
    h_reveal_paid = ceil(max(0, face_down - max_deal_reveals) / 2)
    h_base = h_deals + h_reveal_paid

Heuristic estimates must never enter pruning.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from spider.engine import SpiderState
from spider.rules import MW_RULES, mw_move_cost


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LowerBoundComponent:
    """One named bound contribution."""

    name: str
    value: int
    admissible: bool
    rationale: str


@dataclass(frozen=True)
class LowerBoundBreakdown:
    """Collection of components with an admissible combined value."""

    components: Tuple[LowerBoundComponent, ...]
    h_admissible: int
    """Proof-safe combined lower bound on remaining corrected MW cost."""
    h_naive_face_down_plus_deals: int
    """Diagnostic only — NOT for pruning (see module docstring)."""
    face_down_count: int
    remaining_deals: int
    notes: Tuple[str, ...]

    def component(self, name: str) -> Optional[LowerBoundComponent]:
        for c in self.components:
            if c.name == name:
                return c
        return None


@dataclass(frozen=True)
class BudgetDiagnostic:
    """g+h vs incumbent / target."""

    g: int
    h: int
    g_plus_h: int
    incumbent: Optional[int]
    target: Optional[int]
    prune_vs_incumbent: bool
    """True iff g+h >= incumbent (strict improvement impossible)."""
    prune_vs_target: bool
    """True iff g+h > target (target T unachievable)."""
    discretionary_slack_incumbent: Optional[int]
    """incumbent - (g+h) when incumbent set; negative means already pruned."""
    discretionary_slack_target: Optional[int]
    """target - (g+h) when target set."""
    notes: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Engine facts used by the proof
# ---------------------------------------------------------------------------


def count_face_down(state: SpiderState) -> int:
    return sum(len(c.face_down) for c in state.columns)


def count_remaining_deals(state: SpiderState) -> int:
    return len(state.stock) // 10


def free_move_cannot_reveal_face_down() -> Tuple[bool, str]:
    """Structural proof from MW_RULES + engine.move ordering."""
    # Free move requires source_face_down_count == 0 under corrected rules.
    assert MW_RULES.zero_cost_requires_emptying_column
    # Cost-0 sample: full open column to empty
    c0 = mw_move_cost(
        cards_moved=3,
        source_face_up_count=3,
        dest_was_empty=True,
        source_face_down_count=0,
        rules=MW_RULES,
    )
    c1 = mw_move_cost(
        cards_moved=3,
        source_face_up_count=3,
        dest_was_empty=True,
        source_face_down_count=1,
        rules=MW_RULES,
    )
    ok = c0 == 0 and c1 == 1
    msg = (
        "fact: corrected free relocate requires source_face_down_count==0 "
        f"(sample costs free={c0}, with_fd={c1}); free moves cannot source-flip"
    )
    return ok, msg


def max_reveals_per_paid_tableau_move() -> int:
    """Source maybe_flip + dest foundation maybe_flip <= 2."""
    return 2


def max_reveals_per_stock_deal() -> int:
    """deal() calls check_seq on each of 10 columns; each may flip once."""
    return 10


# ---------------------------------------------------------------------------
# Bound computation
# ---------------------------------------------------------------------------


def compute_solution_lower_bound(state: SpiderState) -> LowerBoundBreakdown:
    """Admissible lower bound on remaining corrected MW cost to *any* solution."""
    fd = count_face_down(state)
    deals = count_remaining_deals(state)
    free_ok, free_msg = free_move_cannot_reveal_face_down()

    max_deal_rev = max_reveals_per_stock_deal() * deals
    residual_reveals = max(0, fd - max_deal_rev)
    per_paid = max_reveals_per_paid_tableau_move()
    h_reveal_paid = int(math.ceil(residual_reveals / per_paid)) if residual_reveals else 0
    h_deals = deals
    h_adm = h_deals + h_reveal_paid
    h_naive = fd + deals

    comps = (
        LowerBoundComponent(
            name="remaining_stock_deals",
            value=h_deals,
            admissible=True,
            rationale="each remaining stock row must be dealt; deal_cost=1",
        ),
        LowerBoundComponent(
            name="face_down_count",
            value=fd,
            admissible=False,
            rationale="FACT count of hidden tableau cards (not a move lower bound alone)",
        ),
        LowerBoundComponent(
            name="max_reveals_coverable_by_deals",
            value=max_deal_rev,
            admissible=True,
            rationale=(
                f"at most {max_reveals_per_stock_deal()} foundation-triggered "
                f"flips per deal × {deals} deals"
            ),
        ),
        LowerBoundComponent(
            name="paid_tableau_moves_for_residual_reveals",
            value=h_reveal_paid,
            admissible=True,
            rationale=(
                f"ceil(max(0, face_down - deal_flip_cap) / "
                f"{per_paid}) — at most {per_paid} flips per paid tableau move"
            ),
        ),
        LowerBoundComponent(
            name="h_base_admissible",
            value=h_adm,
            admissible=True,
            rationale="remaining_stock_deals + paid_tableau_moves_for_residual_reveals",
        ),
        LowerBoundComponent(
            name="h_naive_face_down_plus_deals",
            value=h_naive,
            admissible=False,
            rationale=(
                "DIAGNOSTIC ONLY — not admissible: one paid move can flip twice; "
                "deals can flip via foundation"
            ),
        ),
    )
    notes = [
        free_msg,
        (
            "fact: naive face_down+deals is NOT used for pruning"
            if free_ok
            else "ERROR: free-move/reveal proof failed"
        ),
        f"fact: h_admissible={h_adm} (deals={h_deals} + reveal_paid={h_reveal_paid})",
        f"fact: h_naive={h_naive} retained for diagnostics only",
    ]
    if not free_ok:
        # Refuse to claim admissibility
        h_adm = h_deals  # still safe: deals alone
        notes.append("CRITICAL: fell back to deals-only admissible bound")

    return LowerBoundBreakdown(
        components=comps,
        h_admissible=h_adm if free_ok else h_deals,
        h_naive_face_down_plus_deals=h_naive,
        face_down_count=fd,
        remaining_deals=deals,
        notes=tuple(notes),
    )


def compute_objective_lower_bound(
    *,
    kind: str,
    min_reveals: int = 0,
    requires_deal: bool = False,
    state: Optional[SpiderState] = None,
) -> LowerBoundBreakdown:
    """Admissible LB for a single strategic objective (not full solve).

    For EXPOSE_REVEAL_PREFIX: min_reveals is a lower bound on flip events on
    that column. Each such flip on a given column requires a distinct source
    flip (deal foundation flips on that column are at most remaining_deals).
    Paid-move LB = max(0, min_reveals - remaining_deals).
    """
    deals = count_remaining_deals(state) if state is not None else 0
    comps: list[LowerBoundComponent] = []
    h = 0
    notes: list[str] = []

    if kind == "EXPOSE_REVEAL_PREFIX":
        # At most one deal-triggered foundation flip per remaining deal on a column
        cover = deals
        paid = max(0, min_reveals - cover)
        h = paid
        comps.append(
            LowerBoundComponent(
                name="objective_min_reveals",
                value=min_reveals,
                admissible=True,
                rationale="flip-count lower bound from reveal graph",
            )
        )
        comps.append(
            LowerBoundComponent(
                name="objective_paid_moves",
                value=paid,
                admissible=True,
                rationale=(
                    f"max(0, min_reveals - remaining_deals) allowing up to "
                    f"{cover} deal-side foundation flips"
                ),
            )
        )
        notes.append(
            f"fact: objective expose LB={paid} paid moves "
            f"(min_reveals={min_reveals}, deal_cover<={cover})"
        )
    elif kind == "DEAL_NOW":
        h = 1 if requires_deal or True else 0
        # Deal always costs 1 when executed
        h = 1
        comps.append(
            LowerBoundComponent(
                name="deal_cost",
                value=1,
                admissible=True,
                rationale="deal_cost() == 1",
            )
        )
    elif kind == "CREATE_WORKSPACE":
        # No general admissible tableau-move LB without search
        h = 0
        comps.append(
            LowerBoundComponent(
                name="create_workspace",
                value=0,
                admissible=True,
                rationale="no universal positive move LB; creation may be free via foundation",
            )
        )
        notes.append("fact: CREATE_WORKSPACE admissible LB=0 (may be free side-effect)")
    elif kind == "REMOVE_FOUNDATION":
        h = 0
        comps.append(
            LowerBoundComponent(
                name="remove_foundation",
                value=0,
                admissible=True,
                rationale="foundation removal itself costs 0; assembly cost not bounded here",
            )
        )
    else:
        h = 0
        comps.append(
            LowerBoundComponent(
                name="generic_zero",
                value=0,
                admissible=True,
                rationale=f"no stronger admissible LB for kind={kind}",
            )
        )

    if requires_deal and kind != "DEAL_NOW":
        h += 1
        comps.append(
            LowerBoundComponent(
                name="requires_deal",
                value=1,
                admissible=True,
                rationale="objective requires advancing stock epoch",
            )
        )

    return LowerBoundBreakdown(
        components=tuple(comps),
        h_admissible=h,
        h_naive_face_down_plus_deals=h,
        face_down_count=count_face_down(state) if state is not None else 0,
        remaining_deals=deals,
        notes=tuple(notes),
    )


def budget_diagnostic(
    *,
    g: int,
    h: int,
    incumbent: Optional[int] = None,
    target: Optional[int] = None,
) -> BudgetDiagnostic:
    """Incumbent/target pruning diagnostics.

    Strict improvement vs incumbent U: prune iff g+h >= U.
    Explicit target T: prune iff g+h > T.
    """
    gph = g + h
    prune_inc = incumbent is not None and gph >= incumbent
    prune_tgt = target is not None and gph > target
    slack_inc = (incumbent - gph) if incumbent is not None else None
    slack_tgt = (target - gph) if target is not None else None
    notes = [
        f"fact: g={g} h={h} g+h={gph}",
        (
            f"fact: incumbent={incumbent} prune_if_g_plus_h_ge={prune_inc} "
            f"slack={slack_inc}"
            if incumbent is not None
            else "fact: no incumbent"
        ),
        (
            f"fact: target={target} prune_if_g_plus_h_gt={prune_tgt} slack={slack_tgt}"
            if target is not None
            else "fact: no target"
        ),
    ]
    return BudgetDiagnostic(
        g=g,
        h=h,
        g_plus_h=gph,
        incumbent=incumbent,
        target=target,
        prune_vs_incumbent=prune_inc,
        prune_vs_target=prune_tgt,
        discretionary_slack_incumbent=slack_inc,
        discretionary_slack_target=slack_tgt,
        notes=tuple(notes),
    )
