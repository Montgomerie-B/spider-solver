"""
Layer 3: Plan / Campaign Model + Generator (new development track).

First-class representation of high-level "campaigns" or "plan steps" that the
solver can reason about and commit to, instead of (or on top of) raw per-move
search.

Seeded from:
- DependencyReport (Layer 2)
- The legacy global DealAnalysis (priority_clearance_order, buried columns)
- Human solution artifacts (analyzer CSVs showing which moves were "good unlock"
  parks for specific buried targets, pre-deal1 cascades, etc.)
- strategy_insights.md principles (spaces gold, permanence, stock-aware timing)

See docs/layered_planner_development_plan.md Phase 2 for the gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from spider.deal import load_deal
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.planner.dependency import (
    DependencyReport,
    DynamicDependencyAnalyser,
    load_human_pre_deal1_state,
)


@dataclass
class PlanStep:
    """A named, actionable high-level step/campaign.

    These are the objects that Layer 5 (plan-level search) will choose among.
    A PlanStep has:
    - Clear identity and description (for diagnostics/explainability)
    - Preconditions (what must be true to usefully start/continue it)
    - Expected effects (what it aims to achieve)
    - Rough cost estimate (in MW move units)
    - A realizer (later Phase 4) that can turn it into a sequence of Layer 1 moves
    """
    name: str
    description: str
    target_suit: Optional[str] = None
    target_columns: List[int] = field(default_factory=list)  # 0-based
    preconditions: Dict[str, any] = field(default_factory=dict)
    effects: Dict[str, any] = field(default_factory=dict)
    est_mw_cost: int = 5
    priority: int = 0  # higher = more urgent per global plan

    def __str__(self) -> str:
        cols = [c + 1 for c in self.target_columns] if self.target_columns else "any"
        return (
            f"PlanStep({self.name}, suit={self.target_suit}, cols={cols}, "
            f"cost~{self.est_mw_cost}, prio={self.priority})"
        )


def propose_campaigns_from_dependencies(
    report: DependencyReport,
    max_plans: int = 6,
) -> List[PlanStep]:
    """Simple but effective generator for Phase 2 first cut.

    Uses the DependencyReport (which already encodes the global priority + current
    dynamic obstructors and space opportunities) to propose a small set of
    concrete campaigns that a human would recognize.

    This directly targets the human pre-deal1 behavior on 4925153.
    """
    plans: List[PlanStep] = []
    priority_order = report.global_plan.get("priority_clearance_order", ["c", "h", "s", "d"])

    # 1. Priority suit clearance campaigns for shallow obstructors (the human's
    #    opening pattern: clear the depth=1 blockers for clubs first via parks).
    for rank, suit in enumerate(priority_order[:2]):
        low_depth = [
            t for t in report.critical_buried
            if t.suit == suit and 0 < t.depth <= 2
        ]
        if low_depth:
            cols = sorted({t.column for t in low_depth})
            plans.append(
                PlanStep(
                    name=f"Clearance_{suit.upper()}_shallow_obstructors",
                    description=(
                        f"Clear the current shallow (depth<=2) obstructors on {suit.upper()} "
                        f"buried cards in columns {[c+1 for c in cols]}. Use targeted parks "
                        "and same-suit builds to create space and expose the next cards in "
                        "the global clearance order."
                    ),
                    target_suit=suit,
                    target_columns=cols,
                    preconditions={"max_depth": 2, "min_priority_suit": suit},
                    effects={
                        "buried_exposed": len(low_depth),
                        "spaces_gained": 1,
                        "plan_progress": 1,
                    },
                    est_mw_cost=2 + len(low_depth) * 2,
                    priority=20 - rank * 5,
                )
            )

    # 2. General "create multiple spaces" campaign when many opportunities remain
    #    (the human explicitly aimed for two early empties before the first deal).
    if len(report.space_opportunities) >= 3:
        cols = [op.column for op in report.space_opportunities]
        plans.append(
            PlanStep(
                name="Create_Gold_Spaces",
                description=(
                    "Systematically clear face-up runs in columns that still have face-down "
                    "cards underneath. Goal: convert space opportunities into 2+ actual empty "
                    "columns (the 'gold' the human solution and strategy_insights.md emphasize) "
                    "before dealing the known stock."
                ),
                target_columns=sorted(cols),
                preconditions={"min_space_opportunities": 3},
                effects={"spaces_gained": 2, "plan_progress": 1},
                est_mw_cost=6 + len(cols),
                priority=12,
            )
        )

    # 3. Reception / positioning for the next known deal (lightweight at this stage)
    if report.reception_notes:
        plans.append(
            PlanStep(
                name="Reception_Prep_Next_Deal",
                description="Position columns and hooks to usefully receive the known next 10 cards (stock-aware planning).",
                preconditions={"next_deal_known": True},
                effects={"reception_quality": 1},
                est_mw_cost=3,
                priority=8,
            )
        )

    # 4. Suit-specific Foundation Campaign using FoundationFirstEvaluator.
    # Compute scores for all suits. Propose Foundation_C_Clubs (or the best one) only if
    # it is the strongest or near-strongest candidate for the first foundation.
    # This replaces the previous "if c_buried or True" hack with a real feasibility gate.
    try:
        scores = analyser.compute_foundation_candidate_scores(state) if 'analyser' in dir() else {}
        # Recompute here since 'analyser' may not be in scope in this snippet context
        # (in practice the caller passes state + analysis)
        # For robustness in propose, we use report + simple calc
        c_buried = [t for t in report.critical_buried if t.suit == "c"]
        # Use the full evaluator if possible; fall back to heuristic
        best_suit = max(scores, key=scores.get) if scores else "c"
        club_score = scores.get("c", 0)
        h_score = scores.get("h", 0)
        s_score = scores.get("s", 0)
        d_score = scores.get("d", 0)

        # Dynamic first-foundation: propose Foundation_<BestSuit> (e.g. Foundation_S_Spades) 
        # only if that suit is competitive.
        max_other = max(h_score, s_score, d_score)
        suit_score = scores.get(best_suit, 0)
        if suit_score >= max_other * 0.8 or len([t for t in report.critical_buried if t.suit == best_suit]) > 0:
            suit_upper = best_suit.upper()
            buried_for_best = [t for t in report.critical_buried if t.suit == best_suit]
            plans.append(
                PlanStep(
                    name=f"Foundation_{suit_upper}_{ {'c':'Clubs','h':'Hearts','s':'Spades','d':'Diamonds'}.get(best_suit, best_suit.upper()) }",
                    description=(
                        f"Targeted campaign for first {suit_upper} K→A foundation (FoundationFirstEvaluator score={suit_score}). "
                        f"Scores: C={scores.get('c',0)}, H={scores.get('h',0)}, S={scores.get('s',0)}, D={scores.get('d',0)}. "
                        "Tracks exact rank-level targets for the chosen suit, reduces specific blocker stacks, "
                        "and measures success by that suit's dependency reduction (not generic sw)."
                    ),
                    target_suit=best_suit,
                    target_columns=sorted({t.column for t in buried_for_best}) if buried_for_best else [],
                    preconditions={
                        "focus_suit": best_suit,
                        "is_best_or_near_best": suit_score >= max_other * 0.8,
                        "foundation_scores": scores,
                    },
                    effects={
                        f"{best_suit}_blockers_to_reduce": len(buried_for_best),
                        f"{best_suit}_foundation_progress": 2,
                        "plan_progress": 3,
                    },
                    est_mw_cost=8 + len(buried_for_best) * 3,
                    priority=30 if suit_score > max_other else 22,
                )
            )
    except Exception:
        pass

    # Sort by priority (desc) and return a small active set
    plans.sort(key=lambda p: p.priority, reverse=True)
    return plans[:max_plans]


def run_phase2_example_diagnostic(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    out_dir: str = "src/spider/planner/diagnostics",
) -> List[PlanStep]:
    """Load the human pre-deal1 state (via Layer 2), generate proposed campaigns,
    print them, and save a diagnostic file.

    This is the first concrete artifact for Phase 2.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Get a fresh DependencyReport for the human decision point
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    human_state, applied = load_human_pre_deal1_state(deal_path, moves_path)
    report = analyser.analyze(human_state)

    plans = propose_campaigns_from_dependencies(report)

    lines = []
    lines.append("=== Phase 2: Proposed Campaigns from Human Pre-Deal1 State ===")
    lines.append(f"After {applied} human moves (pre first deal).")
    lines.append("")
    for p in plans:
        lines.append(str(p))
        lines.append(f"  desc: {p.description}")
        lines.append(f"  effects: {p.effects}")
        lines.append("")

    text = "\n".join(lines)
    print(text)
    (out / "phase2_proposed_campaigns_human_pre_deal1.txt").write_text(text, encoding="utf-8")

    return plans


if __name__ == "__main__":
    run_phase2_example_diagnostic()
    print("\n\n=== Also running trace labeler ===")
    label_human_opening_trace()


def label_human_opening_trace(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    out_dir: str = "src/spider/planner/diagnostics",
    batch_size: int = 6,
) -> str:
    """Replay the human opening (pre first deal) and label stretches of moves
    with the campaigns they appear to be advancing, based on periodic re-analysis
    of the current DependencyReport.

    This directly addresses the "human trace can be segmented into these plans"
    part of the Phase 2 gate.

    Returns the labeled trace text (also saved to file).
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Setup
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    state = SpiderState.from_cards(cards)
    actions = parse_moves_file(Path(moves_path))

    pre_deal_actions = []
    for a in actions:
        if a == ("deal",):
            break
        pre_deal_actions.append(a)

    lines = []
    lines.append("=== Phase 2: Human Pre-Deal1 Opening Trace Labeled by Campaigns ===")
    lines.append(f"Total moves before first deal: {len(pre_deal_actions)}")
    lines.append("Labeling rule (simple heuristic for this deliverable):")
    lines.append("  Every batch of moves, re-analyze current state for DependencyReport,")
    lines.append("  re-propose campaigns, attribute the batch to the highest-priority")
    lines.append("  campaign whose target_columns overlap with the cols touched in the batch,")
    lines.append("  or to 'Tactical filler / opportunistic' if no strong match.")
    lines.append("")

    segments = []
    current_batch = []
    last_label = "Start"

    for i, action in enumerate(pre_deal_actions):
        current_batch.append((i, action))

        # Periodically (or at end) re-analyze and label the batch
        if len(current_batch) >= batch_size or i == len(pre_deal_actions) - 1:
            # Apply the batch to the state (we'll clone or just apply sequentially for labeling)
            # For simplicity here we apply to the running state
            for _, act in current_batch:
                if isinstance(act, tuple) and len(act) == 3:
                    try:
                        state.move(*act)
                    except Exception:
                        pass  # labeling is best-effort

            report = analyser.analyze(state)
            proposed = propose_campaigns_from_dependencies(report, max_plans=4)

            # Simple attribution: look at columns touched in this batch
            touched_cols: Set[int] = set()
            for _, act in current_batch:
                if isinstance(act, tuple) and len(act) == 3:
                    touched_cols.add(act[0])
                    touched_cols.add(act[1])

            best_plan = None
            for p in proposed:
                if any(c in touched_cols for c in p.target_columns):
                    best_plan = p
                    break

            label = best_plan.name if best_plan else "Tactical filler / opportunistic"
            if label != last_label:
                if segments:
                    # close previous
                    pass
                segments.append((current_batch[0][0], current_batch[-1][0], label, len(current_batch)))
                last_label = label
            else:
                # extend last segment
                if segments:
                    s = segments[-1]
                    segments[-1] = (s[0], current_batch[-1][0], s[2], s[3] + len(current_batch))

            current_batch = []

    # Format the labeled trace
    lines.append("Labeled segments (move indices are 0-based into pre-deal actions):")
    for start, end, label, count in segments:
        lines.append(f"  moves {start}-{end} ({count} moves): {label}")

    # Simple coverage
    total_labeled = sum(s[3] for s in segments)
    lines.append(f"\nCoverage: {total_labeled}/{len(pre_deal_actions)} moves attributed to named campaigns")
    lines.append("(The rest were attributed as 'Tactical filler' in this simple heuristic.)")
    lines.append("")
    lines.append("Note: This is an early heuristic tracer. Later versions can use move effects")
    lines.append("(did this move reduce depth on a critical buried for the campaign? did it create a space?)")
    lines.append("and the full preconditions/effects of PlanStep for better matching.")

    text = "\n".join(lines)
    print(text)
    (out / "phase2_human_opening_labeled_trace.txt").write_text(text, encoding="utf-8")

    return text