#!/usr/bin/env python3
"""Sprint 1G opening-to-Deal-1 plan search diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.plan_search_v2 import (
    canonical_opening_to_deal1,
    search_opening_to_first_deal,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.lower_bounds import count_face_down


def _summarize(res, title, human=None):
    print()
    print(title)
    print("-" * len(title))
    s = res.stats
    print(
        f"plan_nodes={s.plan_nodes} realized_try={s.realizations_attempted} "
        f"found={s.realizations_found} already={s.realizations_already} "
        f"miss={s.realizations_miss} resource={s.realizations_resource} "
        f"tt={s.tt_hits} time={s.elapsed_seconds:.2f}s"
    )
    print(f"families_tried={s.families_tried}")
    print(f"terminals={len(res.terminals)} pareto={len(res.pareto_terminals)}")
    costs = sorted({t.g for t in res.terminals})
    print(f"terminal_costs={costs}")
    if human is not None:
        print(
            f"canonical: g={human.g} fd={human.quality.face_down} "
            f"empty={human.quality.empty_count} "
            f"longSS={human.quality.longest_same_suit} "
            f"massSS={human.quality.same_suit_run_mass}"
        )
    print("representative histories (up to 8 terminals):")
    for t in res.terminals[:8]:
        print(
            f"  g={t.g} fd={t.quality.face_down} e={t.quality.empty_count} "
            f"ssL={t.quality.longest_same_suit} "
            f"preSS={t.quality.predeal_same_suit_landings} "
            f"preNC={t.quality.predeal_non_connecting} "
            f"kinds={list(t.objective_kinds)}"
        )
    if res.pareto_terminals:
        print("pareto:")
        for t in res.pareto_terminals[:8]:
            print(
                f"  g={t.g} fd={t.quality.face_down} e={t.quality.empty_count} "
                f"ssL={t.quality.longest_same_suit} kinds={list(t.objective_kinds)}"
            )


def main() -> int:
    deal_path = ROOT / "deals" / "4925153.txt"
    moves_path = ROOT / "solutions" / "4925153_canonical.moves"
    cards = load_deal(deal_path)
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(moves_path)
    human = canonical_opening_to_deal1(start, actions)

    print("SPRINT 1G — OPENING TO DEAL 1")
    print(
        f"canonical opening g={human.g} actions={len(human.actions)} "
        f"fd={human.quality.face_down} empty={human.quality.empty_count}"
    )

    configs = [
        ("TINY depth2/beam20", dict(max_non_deal=2, beam=20, max_plan_nodes=40, time_limit_s=45.0)),
        ("MEDIUM depth3/beam50", dict(max_non_deal=3, beam=50, max_plan_nodes=80, time_limit_s=90.0)),
        ("LARGER depth4/beam100", dict(max_non_deal=4, beam=100, max_plan_nodes=120, time_limit_s=150.0)),
    ]
    for title, kw in configs:
        res = search_opening_to_first_deal(
            start,
            cards=cards,
            tactical_max_cost=3,
            tactical_max_nodes=350,
            tactical_time_s=0.2,
            **kw,
        )
        _summarize(res, title, human)

    # Unrelated
    print()
    print("UNRELATED SYNTHETIC")
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st_u = SpiderState(
        [
            Column([], [Card("s", 8)]),
            Column([], [Card("s", 9)]),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(8)],
        stock,
        [],
    )
    ru = search_opening_to_first_deal(
        st_u, max_non_deal=2, beam=12, max_plan_nodes=25, time_limit_s=20.0
    )
    _summarize(ru, "synthetic 8s/9s + deal")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
