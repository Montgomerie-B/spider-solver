"""
Phase 3: Plan-Aware Scorer (composition of legacy signals + new plan progress).

Per the baselined plan, this scorer evaluates a state with respect to active PlanSteps
so that "how much am I advancing my current campaigns?" is a first-class term
alongside the strong legacy signals we developed earlier (space_work, post-deal
quality on known stock, reception, etc.).

The controller can use this for better "deal now?" decisions (higher plan-aware
score + low remaining space_opps = good time to deal the known cards).
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from spider.planner.dependency import DependencyReport
from spider.planner.plans import PlanStep


def plan_aware_score(
    report: DependencyReport,
    active_plans: List[PlanStep],
    current_space_work: int,
    current_space_opportunities: int,
    plan_progress: Dict[str, Tuple[int, int]] = None,  # {plan.name: (depth_reduced_total, spaces_gained_this_step)}
    legacy_post_quality_bonus: float = 0.0,
    unlock_value: float = 0.0,  # explicit credit for catalytic "good unlock delta" parks (e.g. +30/+34/+41/+43 valuable deltas observed in analyzer on layered 89/124/127 candidates during Gold_Spaces/Clearance campaigns)
) -> float:
    """
    Higher score = better state for the active campaigns + shaped for the known stock.

    Composition:
    - Heavy legacy space_work penalty (the signal that worked well in the flat beam).
    - Penalty for remaining easy space opportunities (we want to convert them to real empties).
    - Positive term for progress on active plans (depth reduced on their targets, spaces gained).
    - Small bonus from legacy post-deal / reception quality (passed in).
    - Explicit unlock_value term (fed from analyzer "good unlock delta" parks + realizer park bias) to credit temporary off-suit parks that open the tableau for later fast solution / strong deal decisions (the original X-factor request).
    """
    score = 0.0

    # Legacy space_work (lower is better — we liked -30*sw in the beam)
    score -= 30 * current_space_work

    # Remaining easy space opportunities (fewer = we have done more of the gold work)
    score -= 5 * current_space_opportunities

    # Plan progress (the new signal)
    if active_plans and plan_progress:
        for p in active_plans:
            if p.name in plan_progress:
                depth_red, sp_gained = plan_progress[p.name]
                # Completing targets on a high-priority campaign is very valuable
                score += 10 * depth_red + 15 * sp_gained
                if depth_red > 0 or sp_gained > 0:
                    score += 5  # ongoing "we are working the plan" bonus

    # Legacy post-deal / reception quality (passed from evaluate_post_deal or report)
    score += legacy_post_quality_bonus

    # Small ongoing bonus for having active high-priority plans (keeps us on the global agenda)
    if active_plans:
        top_prio = max(p.priority for p in active_plans)
        score += top_prio * 0.5

    # Explicit unlock / catalytic value (cross-candidate analyzer 2026-06-06 carry-on):
    # Credit the large positive delta_valuable from off-suit parks that were key to the human ck + layered shaper delta
    # (e.g. +30/+34/+35/+41/+43 in 89/124/127/122 paths during Clearance_C / Gold_Spaces). These are the "park to open
    # the tableau for fast solution" moves that need rectification later but enable the strong low-sw best_deal@7 and sw=11 post-deal1.
    # Scale modestly (2.0*) so it augments rather than overrides the dominant -30*sw and plan progress.
    if unlock_value > 0:
        score += 2.0 * unlock_value

    # === Generic Foundation_<Suit> term + campaign-mode sw de-emphasis ===
    # Foundation progress for the active suit can outweigh moderate sw deterioration.
    is_foundation_campaign = False
    active_suit = None
    if active_plans:
        for p in active_plans:
            if p.name.startswith("Foundation_"):
                is_foundation_campaign = True
                parts = p.name.split("_")
                active_suit = parts[1].lower() if len(parts) > 1 else None
                prog = 0.0
                if plan_progress and "foundation" in plan_progress:
                    prog = plan_progress["foundation"][0]
                elif plan_progress and p.name in plan_progress:
                    prog = plan_progress[p.name][0] * 0.5
                score += 15 * prog
                score += 5.0

    if is_foundation_campaign:
        if current_space_work < 20:
            score += 12 * (current_space_work - 8)

    return score


def demo_plan_aware_scoring():
    """Quick demo of the scorer shape (called from controller or tests)."""
    print("plan_aware_score ready: legacy space penalty + plan progress + space_opp conversion + post bonus.")


# For easy import in controller
__all__ = ["plan_aware_score", "demo_plan_aware_scoring"]