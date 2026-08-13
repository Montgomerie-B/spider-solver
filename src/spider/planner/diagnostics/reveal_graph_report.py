#!/usr/bin/env python3
"""Sprint 1B diagnostics: reveal chains, top opportunities, human opening trace.

Uses the canonical 172 trace only as diagnostic evidence — never as strategy
training. No search is performed.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.foundation_feasibility import analyze_foundation_feasibility
from spider.planner.reveal_graph import (
    analyze_reveal_graph,
    format_opportunity,
    format_reveal_report,
)


@dataclass
class HumanRevealEvent:
    command_index: int  # 1-based explicit command number in the trace
    action_label: str
    column: int  # 0-based source column that flipped
    card_revealed: Card
    rank_among_opportunities: Optional[int]  # 1 = best
    n_opportunities: int
    best_alternative_summary: str
    chain_summary: str
    interest: float
    continued_same_column_later: bool


def _best_column_opportunity(analysis, column: int):
    for opp in analysis.opportunities:
        if opp.prefix.column == column:
            return opp
    return None


def _rank_column(analysis, column: int) -> Tuple[Optional[int], int, float]:
    """Rank columns by each column's best opportunity interest (1 = strongest)."""
    best_by_col = {}
    for opp in analysis.opportunities:
        c = opp.prefix.column
        prev = best_by_col.get(c)
        if prev is None or opp.heuristic_interest > prev.heuristic_interest:
            best_by_col[c] = opp
    ordered = sorted(
        best_by_col.items(),
        key=lambda kv: (-kv[1].heuristic_interest, kv[0]),
    )
    for i, (c, opp) in enumerate(ordered, start=1):
        if c == column:
            return i, len(ordered), opp.heuristic_interest
    return None, len(ordered), 0.0


def human_opening_reveal_trace(
    deal_path: Path, moves_path: Path
) -> List[HumanRevealEvent]:
    """Replay canonical moves until first stock deal; record human reveals."""
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)
    state = SpiderState.from_cards(list(cards))
    events: List[HumanRevealEvent] = []
    fa = analyze_foundation_feasibility(cards, state)

    # Track which columns human excavated (for continuation flag)
    human_reveal_cols: List[int] = []

    for cmd_i, action in enumerate(actions, start=1):
        if action == ("deal",):
            break
        src, dst, k = action
        # Analyse *before* the move
        analysis = analyze_reveal_graph(state, cards=cards, foundation_analysis=fa)
        n_fd_before = len(state.columns[src].face_down)
        top_fd_before = (
            state.columns[src].face_down[-1] if state.columns[src].face_down else None
        )
        rank, n_opp_cols, interest = _rank_column(analysis, src)
        chain = analysis.chain_for_column(src)
        chain_summary = (
            " -> ".join(str(h.card) for h in chain.hidden_cards) if chain else "(none)"
        )
        best_alt = analysis.opportunities[0] if analysis.opportunities else None
        alt_txt = (
            f"col {best_alt.prefix.column + 1} "
            f"seq={' -> '.join(str(c) for c in best_alt.prefix.cards_unlocked)} "
            f"interest={best_alt.heuristic_interest}"
            if best_alt
            else "n/a"
        )

        state.move(src, dst, k)
        flipped = bool(state.last_move and state.last_move[3])
        if not flipped:
            continue

        # Card revealed is former top of face-down
        revealed = top_fd_before
        assert revealed is not None
        human_reveal_cols.append(src)
        events.append(
            HumanRevealEvent(
                command_index=cmd_i,
                action_label=f"move {src + 1} {dst + 1} {k}",
                column=src,
                card_revealed=revealed,
                rank_among_opportunities=rank,
                n_opportunities=n_opp_cols,
                best_alternative_summary=alt_txt,
                chain_summary=chain_summary,
                interest=interest,
                continued_same_column_later=False,  # filled below
            )
        )
        # Recompute foundation epoch if needed (no deals yet, stable)
        fa = analyze_foundation_feasibility(cards, state)

    # Continuation flags
    for i, ev in enumerate(events):
        later = any(e.column == ev.column for e in events[i + 1 :])
        events[i] = HumanRevealEvent(
            **{**ev.__dict__, "continued_same_column_later": later}
        )
    return events


def build_synthetic_unrelated_state() -> Tuple[list[Card], SpiderState]:
    """Tiny synthetic layout for generic behaviour evidence (not full 104 needed for graph)."""
    # Full deal not required for pure graph; still build a legal multi-column layout
    cols = [
        Column(
            [Card("c", 3), Card("s", 13), Card("h", 7)],
            [Card("d", 9)],
        ),
        Column([Card("c", 8), Card("c", 2)], [Card("c", 10), Card("c", 9)]),
        Column([Card("d", 5)], [Card("h", 4)]),
    ] + [Column([], []) for _ in range(7)]
    stock = [Card("s", r) for r in range(1, 14)] * 3 + [Card("h", 1)] * 11
    stock = stock[:50]
    state = SpiderState(cols, stock, [])
    # Fake 104-card deal for foundation optional path: not used if we skip cards=
    return [], state


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)

    print("=" * 88)
    print("SPRINT 1B — REVEAL / UNLOCK GRAPH DIAGNOSTIC")
    print("=" * 88)

    # 1. Initial benchmark
    st0 = SpiderState.from_cards(list(cards))
    fa0 = analyze_foundation_feasibility(cards, st0)
    a0 = analyze_reveal_graph(st0, cards=cards, foundation_analysis=fa0)
    print()
    print(format_reveal_report(a0, title="1) Benchmark initial state", top_n=8))

    # 2 & 3. Pre-deal 1 and pre-deal 2 via canonical replay
    if moves_path.exists():
        actions = parse_moves_file(moves_path)
        st = SpiderState.from_cards(list(cards))
        deals = 0
        pre_states = {}
        for action in actions:
            if action == ("deal",):
                deals += 1
                pre_states[deals] = st.clone()
                st.deal()
                if deals >= 2:
                    break
            else:
                src, dst, k = action
                st.move(src, dst, k)

        for deal_no in (1, 2):
            if deal_no not in pre_states:
                continue
            st_pre = pre_states[deal_no]
            fa = analyze_foundation_feasibility(cards, st_pre)
            analysis = analyze_reveal_graph(st_pre, cards=cards, foundation_analysis=fa)
            print()
            print("=" * 88)
            print(
                format_reveal_report(
                    analysis,
                    title=f"{1 + deal_no}) Canonical state immediately before Deal {deal_no}",
                    top_n=6,
                )
            )

        # 4. Human opening reveal trace
        print()
        print("=" * 88)
        print("5) HUMAN OPENING REVEAL TRACE (canonical, up to Deal 1)")
        print("-" * 88)
        events = human_opening_reveal_trace(deal_path, moves_path)
        if not events:
            print("No human reveals recorded before Deal 1.")
        for ev in events:
            rank_txt = (
                f"#{ev.rank_among_opportunities} of {ev.n_opportunities} columns"
                if ev.rank_among_opportunities is not None
                else "unranked"
            )
            print(
                f"cmd {ev.command_index:>3} {ev.action_label}: "
                f"revealed {ev.card_revealed} in col {ev.column + 1}"
            )
            print(f"  chain: {ev.chain_summary}")
            print(
                f"  column rank before move: {rank_txt} "
                f"(best interest for col={ev.interest})"
            )
            print(f"  analyser top alt: {ev.best_alternative_summary}")
            print(f"  continued same column later: {ev.continued_same_column_later}")
            if (
                ev.rank_among_opportunities is not None
                and ev.rank_among_opportunities > 3
            ):
                print("  ** FLAG: human pursued a relatively low-ranked reveal column")
            print()
    else:
        print("Canonical moves not found; skipping pre-deal / human trace.")

    # Unrelated synthetic
    print("=" * 88)
    print("6) UNRELATED SYNTHETIC LAYOUT")
    print("-" * 88)
    _cards, st_syn = build_synthetic_unrelated_state()
    a_syn = analyze_reveal_graph(st_syn)
    print(format_reveal_report(a_syn, title="Synthetic multi-column layout", top_n=5))

    print()
    print("Done (no search performed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
