"""
Early Layer 5: minimal plan beam search skeleton.

Per the baselined plan, this is a small beam over high-level decisions:
"choose this PlanStep and realize N steps toward it", scored by the plan-aware scorer,
with backtracking on low progress.

This allows exploring sequences of campaigns (the human's long catalytic work) without exploding on raw moves.

Tested on the human pre-deal1 checkpoint.

This closes more of the Layer 5 gate (plan-level search over the generator's proposals).

See plan for how it fits with realizer (for realizing a chosen plan) and scorer (as the heuristic).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.planner.dependency import DynamicDependencyAnalyser, load_human_pre_deal1_state
from spider.planner.plans import PlanStep, propose_campaigns_from_dependencies
from spider.planner.realizer import simple_realize_plan
from spider.planner.scorer import plan_aware_score


@dataclass
class PlanBeamNode:
    state: SpiderState
    active_plan: PlanStep
    steps_taken: int
    total_cost: int
    score: float
    history: List[str]  # e.g. ["chose Clearance_C, realized 5", ...]


def minimal_plan_beam_search(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    beam_width: int = 3,
    max_steps: int = 3,
    realize_per_choice: int = 4,
) -> List[PlanBeamNode]:
    """Minimal beam search over plan choices.

    At each level:
    - From current states, propose campaigns.
    - For top K, realize N steps (using realizer).
    - Score the resulting state with plan_aware_score.
    - Keep top beam_width nodes.
    - Stop at max_steps or when a node has low remaining space_opps (good for deal).

    Returns the best nodes at the end (can 'deal' from the best).

    This is the first skeleton for Layer 5 proper.
    """
    print("=== Minimal Plan Beam Search (early Layer 5) ===")

    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    start_state, _ = load_human_pre_deal1_state(deal_path, moves_path)
    start_report = analyser.analyze(start_state)

    # Initial proposals
    initial_plans = propose_campaigns_from_dependencies(start_report, max_plans=4)
    print(f"Initial plans from human checkpoint: {[p.name for p in initial_plans]}")

    beam: List[PlanBeamNode] = []
    for p in initial_plans[:beam_width]:
        work = start_state.clone()
        moves, cost, status, _u = simple_realize_plan(p, work, max_moves=realize_per_choice, analysis=analysis)
        for m in moves:
            try:
                work.move(*m)
            except Exception:
                pass
        final_report = analyser.analyze(work)
        sw = sum(len(c.face_up) for c in work.columns if c.face_down)
        spaces = len(final_report.space_opportunities)
        # Rough progress for scorer
        prog = {p.name: (1 if any(mm[0] in p.target_columns or mm[1] in p.target_columns for mm in moves) else 0, 0)}
        sc = plan_aware_score(final_report, [p], sw, spaces, prog)
        beam.append(PlanBeamNode(
            state=work,
            active_plan=p,
            steps_taken=len(moves),
            total_cost=cost,
            score=sc,
            history=[f"chose {p.name}, realized {len(moves)} (status: {status})"]
        ))

    # Simple 'search': for a few more 'levels', expand the current best
    for level in range(1, max_steps):
        beam.sort(key=lambda n: n.score, reverse=True)
        current_best = beam[0]
        print(f"Level {level}: best so far {current_best.active_plan.name} score={current_best.score:.1f}, spaces={len(analyser.analyze(current_best.state).space_opportunities)}")

        # Expand: re-propose from current best state, realize more on top one
        curr_report = analyser.analyze(current_best.state)
        new_plans = propose_campaigns_from_dependencies(curr_report, max_plans=3)
        if not new_plans:
            break
        top_new = new_plans[0]
        work = current_best.state.clone()
        moves, cost, status, _u = simple_realize_plan(top_new, work, max_moves=realize_per_choice, analysis=analysis)
        for m in moves:
            try:
                work.move(*m)
            except Exception:
                pass
        final_report = analyser.analyze(work)
        sw = sum(len(c.face_up) for c in work.columns if c.face_down)
        spaces = len(final_report.space_opportunities)
        prog = {top_new.name: (current_best.steps_taken + 1, 0)}
        sc = plan_aware_score(final_report, [top_new], sw, spaces, prog)
        new_node = PlanBeamNode(
            state=work,
            active_plan=top_new,
            steps_taken=current_best.steps_taken + len(moves),
            total_cost=current_best.total_cost + cost,
            score=sc,
            history=current_best.history + [f"level{level}: chose {top_new.name}, realized {len(moves)}"]
        )
        beam.append(new_node)
        beam = sorted(beam, key=lambda n: n.score, reverse=True)[:beam_width]

    print("\nBeam search complete. Top nodes:")
    for i, n in enumerate(beam[:3]):
        final_spaces = len(analyser.analyze(n.state).space_opportunities)
        print(f"  {i+1}. {n.active_plan.name} steps={n.steps_taken} cost={n.total_cost} score={n.score:.1f} final_spaces={final_spaces}")
        for h in n.history:
            print(f"     {h}")

    return beam


if __name__ == "__main__":
    minimal_plan_beam_search()