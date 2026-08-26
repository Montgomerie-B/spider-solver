"""Proof-safe incumbent budgets with separate heuristic economics.

Only :func:`spider.planner.lower_bounds.compute_solution_lower_bound` may
contribute to ``proof_prunable`` here.  Estimated remaining work is useful for
ordering and diagnosis, but it is deliberately kept out of every hard bound.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from spider.engine import SpiderState
from spider.planner.lower_bounds import (
    LowerBoundBreakdown,
    compute_solution_lower_bound,
)


@dataclass(frozen=True)
class IncumbentBudget:
    """One branch-and-bound budget at a planner state.

    ``incumbent_cost`` must be the cost of a replay-verified complete solution.
    When it is absent, no incumbent cap exists and proof pruning is disabled.
    """

    incumbent_cost: Optional[int]
    improvement_target: Optional[int]
    spent_cost: int
    lower_bound: LowerBoundBreakdown
    admissible_remaining_lower_bound: int
    hard_min_total: int
    hard_headroom: Optional[int]
    heuristic_remaining_work: float
    heuristic_economic_slack: Optional[float]
    can_improve_incumbent: bool
    proof_prunable: bool
    proof_reason: str

    @property
    def h_deals(self) -> int:
        component = self.lower_bound.component("remaining_stock_deals")
        return component.value if component is not None else 0

    @property
    def h_reveal_paid(self) -> int:
        component = self.lower_bound.component(
            "paid_tableau_moves_for_residual_reveals"
        )
        return component.value if component is not None else 0

    @property
    def maximum_improving_total(self) -> Optional[int]:
        return self.improvement_target

    def install_incumbent(self, incumbent_cost: int) -> "IncumbentBudget":
        """Return the same state budget under a newly verified incumbent."""
        return _assemble_budget(
            incumbent_cost=incumbent_cost,
            spent_cost=self.spent_cost,
            lower_bound=self.lower_bound,
            heuristic_remaining_work=self.heuristic_remaining_work,
        )


def _assemble_budget(
    *,
    incumbent_cost: Optional[int],
    spent_cost: int,
    lower_bound: LowerBoundBreakdown,
    heuristic_remaining_work: float,
) -> IncumbentBudget:
    if spent_cost < 0:
        raise ValueError("spent_cost must be non-negative")
    if incumbent_cost is not None and incumbent_cost < 0:
        raise ValueError("incumbent_cost must be non-negative")
    if heuristic_remaining_work < 0:
        raise ValueError("heuristic_remaining_work must be non-negative")

    h = lower_bound.h_admissible
    hard_min = spent_cost + h
    target = incumbent_cost - 1 if incumbent_cost is not None else None
    headroom = target - hard_min if target is not None else None
    heuristic_slack = (
        target - spent_cost - heuristic_remaining_work
        if target is not None
        else None
    )
    proof_prunable = incumbent_cost is not None and hard_min >= incumbent_cost
    can_improve = not proof_prunable
    reason = (
        f"g+h={hard_min} >= verified incumbent {incumbent_cost}"
        if proof_prunable
        else (
            f"g+h={hard_min} remains below verified incumbent {incumbent_cost}"
            if incumbent_cost is not None
            else "no verified incumbent: incumbent proof pruning disabled"
        )
    )
    return IncumbentBudget(
        incumbent_cost=incumbent_cost,
        improvement_target=target,
        spent_cost=spent_cost,
        lower_bound=lower_bound,
        admissible_remaining_lower_bound=h,
        hard_min_total=hard_min,
        hard_headroom=headroom,
        heuristic_remaining_work=float(heuristic_remaining_work),
        heuristic_economic_slack=heuristic_slack,
        can_improve_incumbent=can_improve,
        proof_prunable=proof_prunable,
        proof_reason=reason,
    )


def build_incumbent_budget(
    state: SpiderState,
    *,
    spent_cost: int,
    incumbent_cost: Optional[int] = None,
    heuristic_remaining_work: float = 0.0,
) -> IncumbentBudget:
    """Build a budget using only the repository's proven-safe lower bound."""
    return _assemble_budget(
        incumbent_cost=incumbent_cost,
        spent_cost=spent_cost,
        lower_bound=compute_solution_lower_bound(state),
        heuristic_remaining_work=heuristic_remaining_work,
    )


def update_heuristic_remaining_work(
    budget: IncumbentBudget, heuristic_remaining_work: float
) -> IncumbentBudget:
    """Update ordering-only economics without changing hard proof semantics."""
    updated = _assemble_budget(
        incumbent_cost=budget.incumbent_cost,
        spent_cost=budget.spent_cost,
        lower_bound=budget.lower_bound,
        heuristic_remaining_work=heuristic_remaining_work,
    )
    # Make the separation executable: heuristic changes cannot alter proof.
    assert updated.hard_min_total == budget.hard_min_total
    assert updated.proof_prunable == budget.proof_prunable
    return updated
