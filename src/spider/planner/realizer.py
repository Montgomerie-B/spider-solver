"""
Phase 4 sketch / realizer adapter stub (early, to connect plans to execution).

A realizer takes a PlanStep + current state + a budget (moves or seconds or expansions)
and tries to advance the plan using Layer 1 tactical moves (reusing the legacy engine
and search primitives where possible).

For this first stub we do a very simple greedy loop:
- While budget and plan not "satisfied" (e.g. all its target_columns have depth 0 or a space was gained):
  - Ask the (legacy) order_moves or a tiny beam for the best tactical move that helps
    a target column of the plan (reduce depth on its critical buried, or empty a target col).
  - Apply it.
  - Re-check the plan preconditions/effects.

This is deliberately simple and will be improved (or replaced by calling the existing
_beam_to_next_deal with a plan-specific objective) once we have the full Layer 5 controller.

See the baselined plan for how this fits (Phase 4: Tactical realizer adapter).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.planner.dependency import DynamicDependencyAnalyser, load_human_pre_deal1_state
from spider.planner.plans import PlanStep, propose_campaigns_from_dependencies
from spider.search import order_moves  # legacy tactical ordering, safe to reuse


def simple_realize_plan(
    plan: PlanStep,
    state: SpiderState,
    max_moves: int = 12,
    analysis=None,
) -> Tuple[List[Tuple[int, int, int]], int, str]:
    """Very early realizer stub.

    Returns (list_of_moves_applied, mw_cost_spent, status_message).
    Tries to make measurable progress on the plan's target_columns or effects.
    """
    if analysis is None:
        # caller should pass it, but for standalone we can rebuild
        cards = [c for col in state.columns for c in (col.face_down + col.face_up)]  # not perfect
        # better: the caller passes a fresh state from the deal
        pass

    applied_moves: List[Tuple[int, int, int]] = []
    total_cost = 0
    unlock_earned = 0  # count of explicit park-unlock moves (off-suit attaches under Gold/Space) performed; fed to L4 scorer
    original_state = state.clone()  # we work on the passed state (caller clones if needed)

    for _ in range(max_moves):
        # Re-analyze current state to see if the plan is still relevant / advanced
        # (in real version we would have a proper "plan satisfied" predicate on the effects)
        # For stub: if any target column now has 0 face-up on its face-down (or is empty), we made progress
        progress_made = False
        for col_idx in plan.target_columns:
            col = original_state.columns[col_idx]  # note: we should use the live state
            # Use the passed state
            live_col = state.columns[col_idx]
            if not live_col.face_down and live_col.is_empty():
                progress_made = True
                break
            if live_col.face_down and len(live_col.face_up) == 0:
                progress_made = True
                break

        if progress_made:
            return applied_moves, total_cost, "plan advanced (target column cleared or exposed)", unlock_earned

        # Improved tactical choice: score legal moves by how much they help the current plan.
        # Re-analyze to get current opportunities.
        current_report = None
        if analysis is not None:
            try:
                current_report = DynamicDependencyAnalyser(analysis).analyze(state)
            except Exception:
                current_report = None

        legal_scored = []
        for src in range(10):
            for dst in range(10):
                if src == dst:
                    continue
                for k in range(1, len(state.columns[src].face_up) + 1):
                    if state.can_move(src, dst, k):
                        move = (src, dst, k)
                        score = 0
                        # Base: touching a plan target column is good
                        if src in plan.target_columns or dst in plan.target_columns:
                            score += 10
                        # For space/gold plans: strongly prefer moves that empty a column (0-cost to empty is gold)
                        if "Gold" in plan.name or "Space" in plan.name:
                            if state.columns[dst].is_empty():
                                score += 50  # emptying a column
                            if state.columns[src].face_down and len(state.columns[src].face_up) == k:
                                score += 30  # clearing the face-up from a space_opp column
                        # For clearance plans: prefer reducing depth on the target
                        if plan.target_suit and current_report:
                            for t in current_report.critical_buried:
                                if t.column in plan.target_columns and t.suit == plan.target_suit:
                                    if src == t.column or dst == t.column:
                                        score += 20 - t.depth  # higher for shallower
                        # Park unlock bonus for space/gold plans (fed back from analyzer on the 89-cost layered candidate):
                        # The 89 path was very park-heavy with many "good unlock delta" parks that enabled catalytic pre-deal work.
                        # Current generic reveal bonus was insufficient; add explicit small bonus for off-suit (park) moves
                        # when pursuing Gold_Spaces or space creation, as they frequently unlock the tableau.
                        if ("Gold" in plan.name or "Space" in plan.name) and k > 0:
                            try:
                                if not state.columns[dst].is_empty() and len(state.columns[src].face_up) >= k:
                                    # rough park: the card that will attach (top of moved run) has different suit than dst top
                                    moved_card = state.columns[src].face_up[-k]  # the card that touches dst
                                    dst_top = state.columns[dst].face_up[-1]
                                    if getattr(moved_card, 'suit', None) and getattr(dst_top, 'suit', None) and moved_card.suit != dst_top.suit:
                                        score += 12  # explicit park-for-unlock bonus per 89 analysis
                                        unlock_earned += 1  # real value for L4 plan_aware_score unlock term (credits the +30..+43 good deltas from analyzer on layered candidates)
                            except Exception:
                                pass

                        # === Foundation_C_Clubs specific scoring (Task 1-2) ===
                        # Reward moves that directly reduce Club foundation dependency.
                        if plan.name == "Foundation_C_Clubs" or "Foundation_C" in plan.name:
                            # Base bonus for touching a Club or a column that has buried Clubs
                            src_col = state.columns[src]
                            dst_col = state.columns[dst]
                            moved_run = src_col.face_up[-k:] if k <= len(src_col.face_up) else []
                            is_club_move = any(getattr(c, 'suit', None) == 'c' for c in moved_run) or \
                                           any(getattr(c, 'suit', None) == 'c' for c in dst_col.face_up[-1:]) or \
                                           (src in plan.target_columns or dst in plan.target_columns)

                            if is_club_move:
                                score += 15

                            # Strong bonus for extending same-suit Club run toward K-A
                            if moved_run and all(getattr(c, 'suit', None) == 'c' for c in moved_run):
                                # Check if it continues a Club run on dst
                                if dst_col.face_up:
                                    dst_top = dst_col.face_up[-1]
                                    if dst_top.suit == 'c' and dst_top.rank - 1 == moved_run[0].rank:
                                        score += 25 + k * 3  # extending the run is very high value for foundation

                            # Bonus for reducing depth on buried Clubs (simulate the move effect)
                            # We give credit if the src or dst col has known buried Clubs from the plan or report
                            if current_report:
                                for t in current_report.critical_buried:
                                    if t.suit == 'c' and (src == t.column or dst == t.column):
                                        # Moving from/to a Club-buried column reduces effective depth or exposes
                                        score += 18 - min(t.depth, 12)

                            # Empty column created specifically helps Club clearance (high value for deep blockers)
                            if state.columns[dst].is_empty() and any(t.suit == 'c' for t in (current_report.critical_buried if current_report else [])):
                                score += 20

                            # Penalize burying a Club or breaking a Club fragment (if we had pre-move state)
                            # (simplified: if moving Clubs onto non-Club or non-continuing)
                            if moved_run and all(c.suit == 'c' for c in moved_run):
                                if dst_col.face_up and (dst_col.face_up[-1].suit != 'c' or dst_col.face_up[-1].rank - 1 != moved_run[0].rank):
                                    score -= 8  # mild penalty for parking Clubs in non-ideal spot

                        legal_scored.append((score, move))
                        break

        if not legal_scored:
            chosen = None
        else:
            legal_scored.sort(reverse=True)  # highest score first
            chosen = legal_scored[0][1]

        if not chosen:
            return applied_moves, total_cost, "no more legal moves", unlock_earned

        src, dst, k = chosen
        try:
            cost = state.move(src, dst, k)
            applied_moves.append((src, dst, k))
            total_cost += cost
        except Exception as e:
            return applied_moves, total_cost, f"move failed: {e}"

    return applied_moves, total_cost, "budget exhausted", unlock_earned


def demo_realize_one_campaign_from_human_state(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
) -> None:
    """Demo: take the human pre-deal1 state, propose campaigns, pick the top one,
    and try to realize a few moves toward it using the stub realizer.
    Prints a small trace.
    """
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    human_state, _ = load_human_pre_deal1_state(deal_path, moves_path)
    report = analyser.analyze(human_state)
    plans = propose_campaigns_from_dependencies(report, max_plans=3)

    if not plans:
        print("No plans proposed.")
        return

    top_plan = plans[0]
    print(f"Top proposed plan: {top_plan}")
    print("Attempting simple realization (up to 8 moves) from the human pre-deal1 state...")

    # Clone so we don't mutate the original for the demo
    work_state = human_state.clone()
    moves, cost, status = simple_realize_plan(top_plan, work_state, max_moves=8, analysis=analysis)

    print(f"Applied {len(moves)} moves, cost {cost}. Status: {status}")
    print("Moves:", moves)
    print("(In a full realizer this would be longer sequences and would update the plan's 'progress' metrics.)")


if __name__ == "__main__":
    demo_realize_one_campaign_from_human_state()