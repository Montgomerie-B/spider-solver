#!/usr/bin/env python3
"""Sprint 1D diagnostics: stock reception, shaping, foundation timing, 1B revisit.

Canonical 172 is evidence only. No long search.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.foundation_feasibility import analyze_foundation_feasibility
from spider.planner.reveal_graph import analyze_reveal_graph
from spider.planner.space_lifecycle import analyze_space_lifecycle, empty_count
from spider.planner.stock_reception import (
    LandingKind,
    analyze_stock_reception,
    format_reception_report,
)
from spider.planner.strategic_analysis import analyze_strategic


def _replay_to_pre_deal(cards, actions, deal_target: int) -> SpiderState:
    st = SpiderState.from_cards(list(cards))
    deals = 0
    for action in actions:
        if action == ("deal",):
            deals += 1
            if deals == deal_target:
                return st
            st.deal()
        else:
            src, dst, k = action
            st.move(src, dst, k)
    raise RuntimeError(f"deal {deal_target} not found")


def _replay_to_post_deal(cards, actions, deal_target: int) -> SpiderState:
    st = _replay_to_pre_deal(cards, actions, deal_target)
    st.deal()
    return st


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)

    print("=" * 88)
    print("SPRINT 1D — KNOWN-STOCK RECEPTION DIAGNOSTIC")
    print("=" * 88)

    print()
    print(
        f"{'Deal':<5} {'Incoming row':<55} "
        f"{'SS':>3} {'MX':>3} {'NC':>3} {'Out':>3} "
        f"{'Lim':>3} {'En':>3} {'Shape?'}"
    )
    print("-" * 100)

    for deal_no in range(1, 6):
        st = _replay_to_pre_deal(cards, actions, deal_no)
        a = analyze_stock_reception(
            st, cards=cards, shaping_max_cost=3, run_shaping_probe=True
        )
        row = " ".join(str(f.card) for f in a.incoming_row)
        s = a.row_summary
        found = [r for r in a.shaping_results if r.found and r.status == "found"]
        shape = f"yes({len(found)})" if found else "no"
        print(
            f"{deal_no:<5} {row:<55} "
            f"{s.n_same_suit_landings:>3} {s.n_mixed_rank_landings:>3} "
            f"{s.n_non_connecting:>3} {s.n_with_immediate_out:>3} "
            f"{s.n_foundation_limiting:>3} {s.n_enables_foundation_epoch:>3} "
            f"{shape}"
        )

    for deal_no in range(1, 6):
        print()
        print("=" * 88)
        st = _replay_to_pre_deal(cards, actions, deal_no)
        a = analyze_stock_reception(
            st, cards=cards, shaping_max_cost=3, run_shaping_probe=True
        )
        print(format_reception_report(a, title=f"Deal {deal_no} PRE-DEAL reception"))

        # Foundation significance for 2,4,5
        if deal_no in (2, 4, 5):
            print()
            print(f"FOUNDATION-TIMING (epoch {a.current_epoch}->{a.epoch_after_deal})")
            for c in a.columns:
                if c.is_foundation_limiting_card or c.enables_foundation_this_epoch:
                    print(
                        f"  col {c.column + 1} {c.incoming}: "
                        f"limiting={c.is_foundation_limiting_card} "
                        f"enables={c.enables_foundation_this_epoch}"
                    )
                    for n in c.foundation_notes[:3]:
                        print(f"    {n}")

        st_post = st.clone()
        st_post.deal()
        print()
        print(f"POST-DEAL quick: empties={empty_count(st_post)}")
        ss = sum(1 for c in a.columns if c.landing == LandingKind.SAME_SUIT_CONNECT)
        print(f"  same-suit landings this row: {ss}")
        for c in a.columns:
            if c.immediate_out_moves:
                print(
                    f"  col {c.column + 1} {c.incoming} immediate outs -> "
                    f"{[m.dst + 1 for m in c.immediate_out_moves]}"
                )

    # Multi-factor 1B revisit at pre-deal1
    print()
    print("=" * 88)
    print("MULTI-FACTOR REVISIT (pre-Deal 1): reveal vs space vs stock")
    print("-" * 88)
    st1 = _replay_to_pre_deal(cards, actions, 1)
    sa = analyze_strategic(st1, cards=cards, run_shaping_probe=False)
    stock = sa.stock_reception
    print(
        f"empty_count={sa.space.workspace.empty_count} "
        f"same_suit_recv={stock.row_summary.n_same_suit_landings} "
        f"mixed={stock.row_summary.n_mixed_rank_landings} "
        f"non_connect={stock.row_summary.n_non_connecting}"
    )
    print(f"incoming: {' '.join(str(f.card) for f in stock.incoming_row)}")
    if sa.reveal:
        for opp in sa.reveal.top_opportunities(5):
            col = opp.prefix.column
            seq = " -> ".join(str(c) for c in opp.prefix.cards_unlocked[:4])
            # stock reception for that column
            cf = stock.columns[col]
            print(
                f"  1B col {col + 1} interest={opp.heuristic_interest} "
                f"prefix={opp.prefix.unavoidable_reveal_count} [{seq}...] "
                f"| landing={cf.landing.value} in={cf.incoming} "
                f"empties={sa.space.workspace.empty_count}"
            )

    # Unrelated fixtures
    print()
    print("=" * 88)
    print("UNRELATED FIXTURES")
    print("-" * 88)
    # GOOD
    row = [Card("c", 8), Card("s", 6), Card("h", 4), Card("d", 10)] + [
        Card("h", r) for r in range(5, 11)
    ]
    filler = [Card("h", r) for r in range(1, 11)] * 4
    stock_cards = filler + row
    cols = [
        Column([], [Card("c", 9)]),
        Column([], [Card("s", 7)]),
        Column([], [Card("h", 5)]),
        Column([], [Card("d", 11)]),
    ]
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    stg = SpiderState(cols, stock_cards, [])
    ag = analyze_stock_reception(stg, run_shaping_probe=False)
    print(
        f"GOOD fixture same_suit_landings={ag.row_summary.n_same_suit_landings}"
    )

    # BAD/SHAPABLE
    rowb = [Card("c", 8)] + [Card("h", r) for r in range(2, 11)]
    stockb = [Card("h", r) for r in range(1, 11)] * 4 + rowb
    colsb = [
        Column([], [Card("c", 9), Card("d", 5)]),
        Column([], [Card("d", 6)]),
    ]
    while len(colsb) < 10:
        colsb.append(Column([], [Card("s", 5 if len(colsb) % 2 else 4)]))
    stb = SpiderState(colsb, stockb, [])
    ab = analyze_stock_reception(stb, shaping_max_cost=2, run_shaping_probe=True)
    print(
        f"BAD fixture pre landing={ab.columns[0].landing.value} "
        f"shaping_found={any(r.found and r.status=='found' for r in ab.shaping_results)}"
    )

    print()
    print("Done (no long search).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
