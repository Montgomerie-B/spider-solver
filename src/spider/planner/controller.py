"""
Early Layer 5 sketch: tiny plan-level controller loop.

The idea (per the baselined plan): a very small "choose among active plans, realize a few steps toward the chosen one, re-evaluate, possibly switch or decide to 'deal'" loop.

This is deliberately tiny and uses the human pre-deal1 state as the testbed so we can see if the system can autonomously follow something close to the human's own campaign sequence for the opening (the long catalytic work the flat beam struggled with).

It reuses:
- Layer 2 (DependencyReport via the analyser on the current state)
- Layer 3 (propose_campaigns_from_dependencies)
- The realizer stub (to take steps on a chosen plan)
- The scorer idea (to "re-score" after realization steps)

For this first version the "deal now" decision is a simple heuristic on remaining space opportunities + plan progress.

This is the natural next discrete piece after the trace + realizer + scorer stubs.
"""

from __future__ import annotations

from pathlib import Path

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.planner.dependency import DynamicDependencyAnalyser, load_human_pre_deal1_state
from spider.planner.plans import propose_campaigns_from_dependencies
from spider.planner.realizer import simple_realize_plan
from spider.planner.scorer import plan_aware_score


def tiny_plan_controller_demo(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    max_steps: int = 5,
    realize_per_step: int = 4,
    deal_threshold: int = 3,
):
    """Run a tiny autonomous loop on the human pre-deal1 shaped state, with an explicit 'deal now?' decision.

    Loop:
    1. Get current DependencyReport (Layer 2).
    2. Propose campaigns (Layer 3).
    3. Pick the top one.
    4. Realize a few moves toward it (realizer).
    5. Check a simple deal-readiness heuristic (remaining space_opps <= threshold or max steps reached).
    6. If ready, "deal" (stop and report the final shaped state for comparison to human and legacy beam).
    7. Otherwise continue.

    This is the first time the layered system has an explicit 'I have done enough catalytic work on my active campaigns — now deal the known cards' decision, directly attacking the original problem.

    Returns the final number of space opportunities left (lower = better shaped for the deal, matching the human's ~ low space_work at deal points).
    """
    print("=== Tiny Plan-Level Controller with 'Deal Now?' (early Layer 5) ===")
    print(f"Starting from human pre-deal1 state (after the opening catalytic work the human actually did).")
    print(f"Deal threshold: <= {deal_threshold} space opportunities or {max_steps} steps.")
    print("")

    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    state, _ = load_human_pre_deal1_state(deal_path, moves_path)
    initial_report = analyser.analyze(state)
    print(f"Initial (human-shaped) space opportunities: {len(initial_report.space_opportunities)}")

    for step in range(1, max_steps + 1):
        report = analyser.analyze(state)
        plans = propose_campaigns_from_dependencies(report, max_plans=3)

        if not plans:
            print(f"Step {step}: No plans proposed. Stopping.")
            break

        top = plans[0]
        print(f"Step {step}: Chose {top.name} (prio {top.priority})")

        work = state.clone()
        moves, cost, status, _unlock = simple_realize_plan(top, work, max_moves=realize_per_step, analysis=analysis)

        for m in moves:
            try:
                state.move(*m)
            except Exception:
                pass

        remaining = len(analyser.analyze(state).space_opportunities)
        current_sw = sum(len(c.face_up) for c in state.columns if c.face_down)

        # Compute plan progress deltas (rough: depth reduced + spaces gained on active plan)
        # For simplicity, track cumulatively for the top plan
        if 'plan_progress' not in locals():
            plan_progress = {top.name: (0, 0)}
        # Very rough delta from this batch (in real we'd compare before/after depths on targets)
        delta_depth = 1 if any(m[0] in top.target_columns or m[1] in top.target_columns for m in moves) else 0
        delta_spaces = 1 if remaining < locals().get('prev_remaining', 10) else 0
        prev_d, prev_s = plan_progress.get(top.name, (0, 0))
        plan_progress[top.name] = (prev_d + delta_depth, prev_s + delta_spaces)
        locals()['prev_remaining'] = remaining

        # Use real plan-aware scorer (Phase 3) for deal decision
        score = plan_aware_score(
            report,
            [top],
            current_sw,
            remaining,
            plan_progress,
            legacy_post_quality_bonus=0.0,
            unlock_value=float(_unlock),  # real park-unlock count returned by the realizer (off-suit attaches under Gold/Space); credits the analyzer-observed +30..+43 deltas
        )
        print(f"  Realized {len(moves)} moves (cost {cost}). Status: {status}")
        print(f"  After step: spaces={remaining}, sw={current_sw}, scorer={score:.1f}")

        if remaining <= deal_threshold or score > 80:
            print(f"\n*** 'Deal now?' fired (spaces={remaining} or scorer={score:.1f}) ***")
            break

    final_report = analyser.analyze(state)
    final_spaces = len(final_report.space_opportunities)
    final_sw = sum(len(c.face_up) for c in state.columns if c.face_down)
    print(f"\nFinal shaped state after controller run: spaces={final_spaces}, sw={final_sw}")
    print("This is the shaped state the layered system would present for the 'deal the known 10' decision.")
    print("(Compare to the human's actual state at this point in the canonical solution, and to what the legacy beam produced from the same starting state.)")

    return final_spaces, final_sw


def layered_shape_round(
    state: SpiderState,
    analysis: "DealAnalysis",
    max_realize_steps: int = 12,  # bumped from 8 based on analysis of 89 candidate (more catalytic/park work beneficial pre-deal)
    force_plan: Optional["PlanStep"] = None,
    campaign_stats: Optional[dict] = None,
) -> Tuple[SpiderState, int, List[Tuple[int, int, int]], int]:
    """Layered shaper for one round (pre-deal): uses L2 report + L3 proposals + realizer (with scorer influence via controller logic).

    Returns (shaped_state clone, total_mw_cost_for_shaping, list_of_moves_performed, unlock_earned).
    The moves are 0-based (src, dst, k) tuples directly usable as Action for replay/export.
    This is the concrete exposure helper for Phase 6: plug this in before legacy _beam or deal in the old macro flow.
    Caller can combine shape_moves + legacy_res.actions and use metrics.export_actions_to_moves_file for a full replay-valid candidate.

    If force_plan is provided, it is used as the active campaign (for suit-specific Foundation_<Suit> mode)
    instead of the top proposed plan. This allows keeping the layered planner focused on one critical
    suit campaign across multiple rounds (r1/r2/r3) without handing off to legacy.

    campaign_stats (optional mutable dict) is passed through to the realizer for "Do No Harm" tracking:
    considered_damaging, vetoed, allowed_compensated, damaging_details.
    """
    analyser = DynamicDependencyAnalyser(analysis)
    report = analyser.analyze(state)
    if force_plan is not None:
        top = force_plan
    else:
        plans = propose_campaigns_from_dependencies(report, max_plans=3)
        if not plans:
            return state.clone(), 0, [], 0
        top = plans[0]
    work = state.clone()
    moves, cost, status, unlock_earned = simple_realize_plan(top, work, max_moves=max_realize_steps, analysis=analysis, campaign_stats=campaign_stats)
    # Note: simple_realize_plan already mutates 'work' in place and returns the applied moves list + cost + unlock_earned (park counts for L4 scorer).
    # Do NOT re-apply here (would double-apply, causing state mismatch for downstream macro actions + replay validation).
    return work, cost, list(moves), unlock_earned  # shaped, cost, actions, realized unlock credit (for plan_aware_score)


if __name__ == "__main__":
    tiny_plan_controller_demo()