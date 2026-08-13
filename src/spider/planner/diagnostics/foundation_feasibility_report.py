#!/usr/bin/env python3
"""Human-readable Sprint 1A foundation-feasibility diagnostics.

Runs on:
  1. initial state of deals/4925153.txt (benchmark fixture only);
  2. canonical states immediately before each stock deal when the canonical
     moves file is available;
  3. one synthetic unrelated deal proving generic behaviour.

Does not perform any search.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.foundation_feasibility import (
    analyze_foundation_feasibility,
    earliest_any_foundation_epoch,
    epoch_name,
    format_analysis_report,
    format_availability_table,
    format_frontier_table,
)

# Local import of synthetic builder from tests is avoided; inline a tiny unrelated deal.


def _two_decks() -> list[Card]:
    out: list[Card] = []
    for _ in range(2):
        for s in "shdc":
            for r in range(1, 14):
                out.append(Card(s, r))
    return out


def build_unrelated_synthetic_deal() -> list[Card]:
    """Unrelated deal: both diamond non-Aces open; Aces enter on deals 2 and 4."""
    diamond_non_aces = [Card("d", r) for r in range(2, 14) for _ in range(2)]
    aces = [Card("d", 1), Card("d", 1)]
    others: list[Card] = []
    for s in "shc":
        for _ in range(2):
            for r in range(1, 14):
                others.append(Card(s, r))
    tableau = diamond_non_aces + others[:30]
    rest = others[30:]
    rounds: list[list[Card]] = [[] for _ in range(5)]
    rounds[1].append(aces[0])  # deal 2
    rounds[3].append(aces[1])  # deal 4
    i = 0
    for d in range(5):
        while len(rounds[d]) < 10:
            rounds[d].append(rest[i])
            i += 1
    stock: list[Card] = []
    for d in range(5, 0, -1):
        stock.extend(rounds[d - 1])
    return tableau + stock


def _replay_to_pre_deal_states(
    deal_path: Path, moves_path: Path
) -> List[Tuple[int, SpiderState]]:
    """Return (next_deal_number, state_just_before_that_deal) for each deal."""
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)
    state = SpiderState.from_cards(cards)
    out: List[Tuple[int, SpiderState]] = []
    deals_seen = 0
    for action in actions:
        if action == ("deal",):
            deals_seen += 1
            out.append((deals_seen, state.clone()))
            state.deal()
        else:
            src, dst, k = action
            state.move(src, dst, k)
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv  # unused
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"

    print("=" * 88)
    print("SPRINT 1A — FOUNDATION FEASIBILITY DIAGNOSTIC")
    print("=" * 88)

    # --- 1. Benchmark initial state ---
    cards = load_deal(deal_path)
    initial = analyze_foundation_feasibility(cards)
    print()
    print(
        format_analysis_report(
            initial,
            title="1) Benchmark deal initial state (fixture deals/4925153.txt)",
        )
    )
    earliest = earliest_any_foundation_epoch(initial)
    print()
    print("HYPOTHESIS CHECK (independent calculation):")
    print(
        "  'No foundation can theoretically be removed before stock deal 2'"
    )
    if earliest is None:
        print("  Result: no foundation is ever theoretically available (unexpected).")
    elif earliest >= 2:
        print(
            f"  Result: CONFIRMED — earliest any foundation is {epoch_name(earliest)}."
        )
    elif earliest == 1:
        print(
            f"  Result: REFUTED — at least one foundation is theoretically available "
            f"at {epoch_name(earliest)} (after deal 1, before deal 2)."
        )
    else:
        print(
            f"  Result: REFUTED — at least one foundation is theoretically available "
            f"at {epoch_name(earliest)} (opening, before any stock deal)."
        )

    # --- 2. Canonical pre-deal states ---
    print()
    print("=" * 88)
    if moves_path.exists():
        pre_deals = _replay_to_pre_deal_states(deal_path, moves_path)
        print(
            f"2) Canonical pre-deal states ({len(pre_deals)} stock deals in canonical trace)"
        )
        for deal_no, st in pre_deals:
            analysis = analyze_foundation_feasibility(cards, st)
            print()
            print(f"--- Immediately before stock deal {deal_no} ---")
            print(f"Current epoch: {analysis.current_epoch_name}")
            print(format_frontier_table(analysis))
    else:
        print("2) Canonical moves file not found; skipping pre-deal diagnostics.")

    # --- 3. Unrelated synthetic deal ---
    print()
    print("=" * 88)
    synth = build_unrelated_synthetic_deal()
    synth_analysis = analyze_foundation_feasibility(synth)
    print(
        format_analysis_report(
            synth_analysis,
            title="3) Unrelated synthetic deal (diamond Aces delayed to deals 2 and 4)",
        )
    )
    d1 = synth_analysis.availability_for("d", 1)
    d2 = synth_analysis.availability_for("d", 2)
    print()
    print(
        f"Synthetic sanity: D#1 earliest={d1.earliest_epoch_name}, "
        f"D#2 earliest={d2.earliest_epoch_name}"
    )
    print()
    print("Done (no search performed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
