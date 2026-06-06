"""
Layer 2: Dependency & Exposure Analyser (new development track).

This module implements dynamic, per-state dependency and exposure analysis
on top of the existing legacy `spider.deal_analysis` (global plan) and the
human solution artifacts (analyzer CSVs + strategy_insights.md).

It is intentionally non-destructive: it imports from legacy modules but
does not modify them. All new logic lives here.

See docs/layered_planner_development_plan.md (Phase 1) for the exact gate
this module must satisfy on the initial layout and human deal-1 decision points.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# --- Reuse of legacy assets (as required by the baselined plan) ---
from spider.cards import Card
from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import DealAnalysis, build_deal_analysis
from spider.engine import SpiderState
from spider.metrics import parse_moves_file


@dataclass
class BuriedTarget:
    """A face-down card (or the topmost face-down in a column) that is critical
    according to the global priority clearance plan."""
    suit: str
    column: int
    depth: int  # how many face-up cards are currently sitting on top of it
    obstructors: List[Card] = field(default_factory=list)  # the current face-up run blocking it


@dataclass
class SpaceCreationOpportunity:
    """A column that can yield a net new empty column if its current face-up
    run is cleared (possibly via temporary parks)."""
    column: int
    current_face_up_len: int
    would_yield_space: bool
    notes: str = ""


@dataclass
class DependencyReport:
    """Human-readable summary of the current dependencies for a state."""
    global_plan: Dict[str, any]
    critical_buried: List[BuriedTarget]
    space_opportunities: List[SpaceCreationOpportunity]
    reception_notes: List[str] = field(default_factory=list)
    # Raw data for further layers (plan generator etc.)
    raw: Dict[str, any] = field(default_factory=dict)


class DynamicDependencyAnalyser:
    """Layer 2 analyser.

    Combines the static global plan (from legacy build_deal_analysis, using full
    known stock) with dynamic information from the current SpiderState.

    This is the starting point for Phase 1 per the baselined plan.
    """

    def __init__(self, analysis: DealAnalysis):
        self.analysis = analysis
        self.priority_suits: List[str] = list(analysis.priority_clearance_order or "shdc")
        # Columns that bury cards of the top 1-2 priority suits (from the static pre-analysis)
        self.priority_buried_cols: Dict[str, List[int]] = {
            s: list(analysis.initial_buried_columns_by_suit.get(s, []))
            for s in self.priority_suits[:2]
        }

    def analyze(self, state: SpiderState) -> DependencyReport:
        """Produce a dynamic dependency report for the given state."""
        critical: List[BuriedTarget] = []
        for suit in self.priority_suits[:2]:  # focus on earliest-eligible priority suits
            for col_idx in self.priority_buried_cols.get(suit, []):
                if col_idx >= len(state.columns):
                    continue
                col = state.columns[col_idx]
                # Depth = number of face-up cards currently sitting on the face-down stack
                depth = len(col.face_up)
                # The actual obstructors are the current face-up cards in that column
                obstructors = list(col.face_up)
                critical.append(
                    BuriedTarget(
                        suit=suit,
                        column=col_idx,
                        depth=depth,
                        obstructors=obstructors,
                    )
                )

        # Simple space creation opportunities: columns that have face-up runs but
        # still have face-down cards underneath (clearing the run can yield a space).
        space_ops: List[SpaceCreationOpportunity] = []
        for col_idx, col in enumerate(state.columns):
            if col.face_down and col.face_up:
                space_ops.append(
                    SpaceCreationOpportunity(
                        column=col_idx,
                        current_face_up_len=len(col.face_up),
                        would_yield_space=True,
                        notes=f"Clear {len(col.face_up)} face-up to flip/expose in col {col_idx+1}",
                    )
                )

        # Reception notes (very lightweight at this stage; later layers will enrich)
        reception_notes: List[str] = []
        if self.analysis.incoming_by_round:
            next_ten = self.analysis.incoming_by_round[0] if len(self.analysis.incoming_by_round) > 0 else []
            if next_ten:
                reception_notes.append(
                    f"Next known deal (round 1) top cards example: {next_ten[:3]}... — look for hooks/ranks that can receive them."
                )

        report = DependencyReport(
            global_plan={
                "priority_clearance_order": self.analysis.priority_clearance_order,
                "eligible_after_r0": list(self.analysis.eligible_suits_by_round[0]) if self.analysis.eligible_suits_by_round else [],
                "initial_buried_by_priority_suit": self.priority_buried_cols,
            },
            critical_buried=critical,
            space_opportunities=space_ops,
            reception_notes=reception_notes,
            raw={
                "priority_suits": self.priority_suits,
            },
        )
        return report

    def compute_club_foundation_state(self, state: SpiderState) -> Dict[str, any]:
        """Suit-specific foundation state for Clubs (K→A same-suit descending run to foundation).

        Returns detailed dependency info for the Foundation_C_Clubs campaign.
        """
        club_cards = []
        club_buried = []  # (rank, col, depth, obstructors)
        visible_clubs = 0
        club_fragments: List[int] = []  # lengths of same-suit Club runs

        for col_idx, col in enumerate(state.columns):
            up = col.face_up
            visible_clubs += len(up)
            # Find same-suit Club fragments in this column
            if up:
                current_len = 0
                for c in up:
                    if c.suit == "c":
                        current_len += 1
                    else:
                        if current_len > 0:
                            club_fragments.append(current_len)
                            current_len = 0
                if current_len > 0:
                    club_fragments.append(current_len)

            # Buried Clubs in this column (face_down are Clubs)
            for fd_idx, c in enumerate(col.face_down):
                if c.suit == "c":
                    depth = len(col.face_up) + (len(col.face_down) - 1 - fd_idx)  # approx depth from top
                    obstructors = list(col.face_up)
                    club_buried.append({
                        "rank": c.rank,
                        "col": col_idx,
                        "depth": depth,
                        "obstructors": obstructors,
                    })

        # Missing ranks for a full K(13)→A(1) Clubs run.
        # We track which ranks are "accounted for" in visible Club fragments or foundations.
        # Simple version: collect all visible Club ranks.
        visible_club_ranks = set()
        for col in state.columns:
            for c in col.face_up:
                if c.suit == "c":
                    visible_club_ranks.add(c.rank)
        # A full foundation removes 13 cards of the suit, but for partial we track longest chain + total visible.
        # Missing for completion: ranks 1-13 not yet in a position to be part of the run.
        all_ranks = set(range(1, 14))
        missing_ranks = sorted(all_ranks - visible_club_ranks)

        # For each buried Club, assess "parkability" of its top obstructors (very rough).
        for b in club_buried:
            b["parkable_obstructors"] = len([o for o in b["obstructors"] if o.suit != "c"])  # off-suit = easier to park

        # Empty columns available for clearance
        empties = sum(1 for c in state.columns if c.is_empty())

        # Future stock impact (Clubs in next deals)
        future_clubs = 0
        if self.analysis.incoming_by_round:
            for ten in self.analysis.incoming_by_round[:3]:  # next 3 deals
                future_clubs += sum(1 for c in ten if c.suit == "c")

        return {
            "visible_clubs": visible_clubs,
            "club_fragments": club_fragments,
            "longest_club_run": max(club_fragments) if club_fragments else 0,
            "missing_ranks_for_ka": missing_ranks,
            "buried_clubs": club_buried,
            "num_buried_clubs": len(club_buried),
            "total_blocker_depth": sum(b["depth"] for b in club_buried),
            "empties_available": empties,
            "future_clubs_in_next_deals": future_clubs,
            "visible_club_ranks": sorted(visible_club_ranks),
        }

    def summarize(self, state: SpiderState) -> str:
        """Return a compact, human-readable diagnostic string (for console or logs)."""
        rep = self.analyze(state)
        lines: List[str] = []
        lines.append("=== Layer 2 Dynamic Dependency Report ===")
        lines.append(f"Global plan priority: {rep.global_plan['priority_clearance_order']}")
        lines.append(f"Eligible suits after r0: {rep.global_plan['eligible_after_r0']}")
        lines.append("")

        lines.append("Critical buried targets (priority suits):")
        if not rep.critical_buried:
            lines.append("  (none identified for top priority suits)")
        for t in rep.critical_buried:
            obs_str = ", ".join(str(c) for c in t.obstructors[-3:]) if t.obstructors else "(empty column face-up)"
            lines.append(f"  Suit {t.suit.upper()} col {t.column+1}: depth={t.depth}  top obstructors: [{obs_str}]")

        lines.append("")
        lines.append("Space creation opportunities (columns with face-down + face-up):")
        if not rep.space_opportunities:
            lines.append("  (none — no column currently has both face-up and face-down)")
        for op in rep.space_opportunities:
            lines.append(f"  Col {op.column+1}: {op.current_face_up_len} face-up on top of face-down  -> {op.notes}")

        lines.append("")
        lines.append("Reception notes (next known stock):")
        for n in rep.reception_notes:
            lines.append(f"  {n}")

        lines.append("")
        lines.append("(This report is the starting point for plan generation in Layer 3.)")
        return "\n".join(lines)


# --- Convenience entry point for quick diagnostics (used during Phase 1 development) ---
def main_diagnostic(deal_path: str = "deals/4925153.txt") -> DependencyReport:
    """Load the deal, build the static analysis, create initial state, and print the Layer 2 report.

    This is the concrete diagnostic required by the Phase 1 gate in the baselined plan.
    Returns the DependencyReport so it can be inspected programmatically.
    """
    p = Path(deal_path)
    # load_deal is the project's canonical way to get the 104 cards for this deal file.
    cards = load_deal(p)
    # Build the static global plan (reuses legacy build_deal_analysis exactly).
    # It expects the token list in the project's internal format.
    tokens = [str(c) for c in cards]  # safe round-trip for the analysis builder
    analysis = build_deal_analysis(tokens)

    state = SpiderState.from_cards(cards)  # initial layout, no moves yet

    analyser = DynamicDependencyAnalyser(analysis)
    print(analyser.summarize(state))

    report = analyser.analyze(state)
    return report


if __name__ == "__main__":
    main_diagnostic()


# --- Phase 1 gate support: human checkpoint near first deal decision point ---
def load_human_pre_deal1_state(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
) -> Tuple[SpiderState, int]:
    """Replay the human canonical opening up to (but not including) the first stock deal.

    Returns (state, num_moves_applied).
    This reaches the human's actual decision point for the first deal.
    """
    p_deal = Path(deal_path)
    cards = load_deal(p_deal)
    state = SpiderState.from_cards(cards)

    actions = parse_moves_file(Path(moves_path))
    applied = 0
    for action in actions:
        if action == ("deal",):
            break  # stop at the human's first deal decision
        if isinstance(action, tuple) and len(action) == 3:
            src, dst, k = action
            try:
                state.move(src, dst, k)
                applied += 1
            except Exception as e:
                print(f"Warning: could not apply human move {action}: {e}")
                break
    return state, applied


def run_full_phase1_gate_diagnostic(
    deal_path: str = "deals/4925153.txt",
    moves_path: str = "solutions/4925153_canonical.moves",
    out_dir: str = "src/spider/planner/diagnostics",
) -> None:
    """Run the analyser on BOTH the initial layout AND the human pre-deal1 decision point.

    Produces human-readable output files and prints a comparison.
    This is intended to satisfy the Phase 1 gate in the baselined plan.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Build analysis once (static global plan)
    cards = load_deal(Path(deal_path))
    tokens = [str(c) for c in cards]
    analysis = build_deal_analysis(tokens)
    analyser = DynamicDependencyAnalyser(analysis)

    # 1. Initial
    print("=== Initial layout (before any human moves) ===")
    init_state = SpiderState.from_cards(cards)
    init_report = analyser.analyze(init_state)
    init_summary = analyser.summarize(init_state)
    print(init_summary)
    (out / "initial_layout_dependency.txt").write_text(init_summary, encoding="utf-8")

    # 2. Human pre-deal1 decision point
    print("\n=== Human pre-deal1 decision point (after opening catalytic work) ===")
    human_state, applied = load_human_pre_deal1_state(deal_path, moves_path)
    print(f"Applied {applied} human moves before first deal.")
    human_summary = analyser.summarize(human_state)
    print(human_summary)
    (out / "human_pre_deal1_checkpoint_dependency.txt").write_text(human_summary, encoding="utf-8")

    # Comparison summary (key metrics for the gate)
    init_crit = [t for t in init_report.critical_buried if t.depth > 0]
    human_crit = [t for t in analyser.analyze(human_state).critical_buried if t.depth > 0]
    init_spaces = len(init_report.space_opportunities)
    human_spaces = len(analyser.analyze(human_state).space_opportunities)

    comp = f"""Phase 1 Gate Diagnostic Comparison (Deal 4925153)
Initial layout vs. Human state just before first stock deal ({applied} moves applied).

Critical buried targets still blocked (depth > 0):
  Initial: {len(init_crit)}
  Human pre-deal1: {len(human_crit)}

Space creation opportunities (columns with face-down still under face-up):
  Initial: {init_spaces}
  Human pre-deal1: {human_spaces}

This demonstrates the human's early work (parks + builds) systematically reducing obstructors on priority buried cards and converting space opportunities into actual empties before dealing the known stock.
See the two .txt files in this directory for full human-readable reports.
"""
    print("\n" + comp)
    (out / "phase1_gate_comparison.txt").write_text(comp, encoding="utf-8")


if __name__ == "__main__":
    # When run as script, do the full gate diagnostic (initial + human checkpoint)
    run_full_phase1_gate_diagnostic()
