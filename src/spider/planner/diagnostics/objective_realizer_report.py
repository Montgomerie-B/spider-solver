#!/usr/bin/env python3
"""Sprint 1F one-step portfolio realization diagnostic (no whole-deal search)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.objective_realizer import (
    RealizationMode,
    realize_objective,
)
from spider.planner.strategic_objectives import generate_objective_portfolio


def _replay_to_pre_deal(cards, actions, deal_n):
    st = SpiderState.from_cards(list(cards))
    deals = 0
    for a in actions:
        if a == ("deal",):
            deals += 1
            if deals == deal_n:
                return st
            st.deal()
        else:
            st.move(a[0], a[1], a[2])
    raise RuntimeError("missing deal")


def _table(st, cards, title, mode=RealizationMode.EXACT_BOUNDED):
    print()
    print(title)
    print("-" * len(title))
    p = generate_objective_portfolio(st, cards=cards)
    print(
        f"{'Kind':<22} {'est':>4} {'LB':>3} {'Found':<22} "
        f"{'cost':>4} {'nodes':>6} Result"
    )
    for o in p.objectives:
        r = realize_objective(
            st, o, mode=mode, max_nodes=2500, time_limit_s=1.5
        )
        print(
            f"{o.kind.value:<22} {o.heuristic_est_cost:>4.1f} {o.admissible_lb:>3} "
            f"{r.status.value:<22} "
            f"{str(r.corrected_mw_cost) if r.corrected_mw_cost is not None else '—':>4} "
            f"{r.nodes_expanded:>6} {o.description[:40]}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)

    print("SPRINT 1F — ONE-STEP OBJECTIVE REALIZATION")
    _table(SpiderState.from_cards(list(cards)), cards, "1) INITIAL")
    _table(_replay_to_pre_deal(cards, actions, 1), cards, "2) PRE-DEAL 1")
    _table(_replay_to_pre_deal(cards, actions, 2), cards, "3) PRE-DEAL 2")

    st_m = SpiderState.from_cards(list(cards))
    for i, a in enumerate(actions):
        if i >= 80:
            break
        if a == ("deal",):
            st_m.deal()
        else:
            st_m.move(a[0], a[1], a[2])
    _table(st_m, cards, "4) MID ~cmd 80")

    print()
    print("5) UNRELATED")
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st_u = SpiderState(
        [
            Column([Card("c", 2)], [Card("s", 9), Card("s", 8)]),
            Column([], []),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(8)],
        stock,
        [],
    )
    _table(st_u, None, "Fixture empty+run")

    print()
    print("HUMAN CHECKPOINT NOTE (pre-D1):")
    print("  Portfolio includes EXPOSE of high-1B chains and DEAL_NOW.")
    print("  Compare Found/cost vs human continuing excavation vs dealing.")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
