#!/usr/bin/env python3
"""Sprint 1E diagnostics: objective portfolios + lower bounds.

172 and 119 are diagnostic parameters only — not strategy constants.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.lower_bounds import budget_diagnostic, compute_solution_lower_bound
from spider.planner.strategic_objectives import (
    format_portfolio,
    generate_objective_portfolio,
)


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
            st.move(action[0], action[1], action[2])
    raise RuntimeError("deal not found")


def _replay_n_commands(cards, actions, n: int) -> SpiderState:
    st = SpiderState.from_cards(list(cards))
    for i, action in enumerate(actions):
        if i >= n:
            break
        if action == ("deal",):
            st.deal()
        else:
            st.move(action[0], action[1], action[2])
    return st


def main(argv: Optional[Sequence[str]] = None) -> int:
    del argv
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)
    actions = parse_moves_file(moves_path)

    print("=" * 88)
    print("SPRINT 1E — STRATEGIC OBJECTIVES + LOWER BOUNDS")
    print("=" * 88)

    # Initial
    st0 = SpiderState.from_cards(list(cards))
    t0 = time.time()
    p0 = generate_objective_portfolio(st0, cards=cards)
    dt = time.time() - t0
    print()
    print(format_portfolio(p0, title="1) INITIAL benchmark portfolio"))
    print(f"generation_runtime_s={dt:.3f}")

    lb0 = p0.solution_lower_bound
    print()
    print("LOWER BOUND (initial, g=0)")
    print(f"  face_down={lb0.face_down_count} deals={lb0.remaining_deals}")
    print(f"  h_admissible={lb0.h_admissible}")
    print(f"  h_naive(NOT for pruning)={lb0.h_naive_face_down_plus_deals}")
    for note in lb0.notes:
        print(f"  {note}")
    for U in (172, 119):
        b = budget_diagnostic(g=0, h=lb0.h_admissible, incumbent=U, target=U)
        print(
            f"  vs {U}: g+h={b.g_plus_h} slack_inc={b.discretionary_slack_incumbent} "
            f"prune_inc={b.prune_vs_incumbent}"
        )

    # Pre D1, post D1, pre D2, mid
    def _post_deal1():
        s = _replay_to_pre_deal(cards, actions, 1)
        s.deal()
        return s

    for label, builder in [
        ("2) PRE-DEAL 1", lambda: _replay_to_pre_deal(cards, actions, 1)),
        ("3) POST-DEAL 1", _post_deal1),
        ("4) PRE-DEAL 2", lambda: _replay_to_pre_deal(cards, actions, 2)),
        ("5) MID-GAME (~cmd 80)", lambda: _replay_n_commands(cards, actions, 80)),
    ]:
        st = builder()
        t0 = time.time()
        p = generate_objective_portfolio(st, cards=cards)
        dt = time.time() - t0
        print()
        print(format_portfolio(p, title=label))
        print(f"generation_runtime_s={dt:.3f}")
        # human coverage at pre-deal1: any EXPOSE or DEAL
        if "PRE-DEAL 1" in label:
            kinds = {o.kind.value for o in p.objectives}
            print(f"human-coverage kinds present: {sorted(kinds)}")
            print(
                "note: human opening uses reveals + eventual deal; "
                "portfolio includes EXPOSE_REVEAL_PREFIX and DEAL_NOW when legal"
            )

    # Unrelated fixtures
    print()
    print("=" * 88)
    print("6) UNRELATED FIXTURES")
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st_a = SpiderState(
        [
            Column([Card("c", 2)], [Card("s", 9), Card("s", 8)]),
            Column([], []),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(8)],
        stock,
        [],
    )
    print(format_portfolio(generate_objective_portfolio(st_a), title="Fixture A (empty+run)"))

    st_b = SpiderState(
        [Column([Card("s", r) for r in range(5, 1, -1)], [Card("h", 6)]) for _ in range(10)],
        [Card("c", r) for r in range(1, 11)] * 3 + [Card("d", r) for r in range(1, 11)] * 2,
        [],
    )
    print()
    print(format_portfolio(generate_objective_portfolio(st_b), title="Fixture B (deep hidden)"))

    # Later budget example
    print()
    print("7) LATER BUDGET EXAMPLE (after 80 commands)")
    st_m = _replay_n_commands(cards, actions, 80)
    # approximate g: replay cost
    from spider.metrics import replay_actions

    st_g = SpiderState.from_cards(list(cards))
    g = replay_actions(st_g, actions[:80])
    lb_m = compute_solution_lower_bound(st_m)
    for U in (172, 119):
        b = budget_diagnostic(g=g, h=lb_m.h_admissible, incumbent=U, target=U)
        print(
            f"  g≈{g} h={lb_m.h_admissible} g+h={b.g_plus_h} vs {U}: "
            f"slack={b.discretionary_slack_incumbent} prune={b.prune_vs_incumbent}"
        )

    print()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
