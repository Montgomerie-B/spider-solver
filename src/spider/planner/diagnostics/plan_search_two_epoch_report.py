#!/usr/bin/env python3
"""Sprint 1H diagnostics: Opening → Deal 2 plan search."""

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
    replay_canonical_epochs,
    search_to_stock_epoch,
)


def _print_human(snaps):
    print("CANONICAL SNAPSHOTS")
    for name in ("initial", "pre_deal_1", "post_deal_1", "pre_deal_2", "post_deal_2"):
        n = snaps.get(name)
        if n is None:
            continue
        q = n.quality
        print(
            f"  {name}: g={n.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
            f"H1theo={q.h1_theo} S1theo={q.s1_theo} "
            f"H1b={q.h1_build:.0f} S1b={q.s1_build:.0f} "
            f"H1r={q.h1_removal:.0f} S1r={q.s1_removal:.0f}"
        )


def _summarize(res, title, human_post=None):
    print()
    print(title)
    print("-" * len(title))
    s = res.stats
    print(
        f"plan_nodes={s.plan_nodes} try={s.realizations_attempted} "
        f"found={s.realizations_found} miss={s.realizations_miss} "
        f"resource={s.realizations_resource} tt={s.tt_hits} "
        f"deal1_expand={s.deal1_frontier} ws_then_expose={s.workspace_then_expose} "
        f"time={s.elapsed_seconds:.2f}s"
    )
    print(f"families={s.families_tried}")
    print(
        f"deal1_nodes={len(res.deal1_nodes)} "
        f"deal2_terminals={len(res.terminals)} "
        f"pareto={len(res.pareto_terminals)} "
        f"stratified={len(res.stratified_terminals)}"
    )
    print(f"terminal_costs={sorted({t.g for t in res.terminals})}")
    if human_post is not None:
        hq = human_post.quality
        print(
            f"human post-D2: g={human_post.g} fd={hq.face_down} e={hq.empty_count} "
            f"ssL={hq.longest_same_suit} H1theo={hq.h1_theo} S1theo={hq.s1_theo}"
        )
    print("terminals (up to 10):")
    for t in res.terminals[:10]:
        q = t.quality
        print(
            f"  g={t.g} fd={q.face_down} e={q.empty_count} ssL={q.longest_same_suit} "
            f"H1t={q.h1_theo} S1t={q.s1_theo} Hb={q.h1_build:.0f} Sb={q.s1_build:.0f} "
            f"kinds={list(t.objective_kinds)}"
        )
        for d in q.deferred_notes()[:3]:
            print(f"    {d}")
    print("stratified:")
    for t in res.stratified_terminals:
        print(
            f"  g={t.g} fd={t.quality.face_down} e={t.quality.empty_count} "
            f"ssL={t.quality.longest_same_suit} kinds={list(t.objective_kinds)}"
        )


def main() -> int:
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, actions, up_to_deals=2, cards=cards)
    print("SPRINT 1H — TWO-EPOCH PLAN SEARCH")
    _print_human(snaps)
    human = snaps["post_deal_2"]

    configs = [
        (
            "TINY",
            dict(
                max_non_deal=2,
                beam=16,
                max_plan_nodes=30,
                time_limit_s=40.0,
                workspace_max_cost=5,
            ),
        ),
        (
            "MEDIUM",
            dict(
                max_non_deal=3,
                beam=32,
                max_plan_nodes=50,
                time_limit_s=80.0,
                workspace_max_cost=5,
            ),
        ),
        (
            "LARGER",
            dict(
                max_non_deal=3,
                beam=48,
                max_plan_nodes=70,
                time_limit_s=120.0,
                workspace_max_cost=6,
            ),
        ),
    ]
    for title, kw in configs:
        res = search_to_stock_epoch(
            start,
            cards=cards,
            target_deals=2,
            tactical_max_cost=3,
            tactical_max_nodes=300,
            tactical_time_s=0.18,
            workspace_attempts_per_node=1,
            cheap_reveal_max=2,
            **kw,
        )
        _summarize(res, title, human)

    print()
    print("UNRELATED SYNTHETIC")
    stock = [Card("h", r) for r in range(1, 11)] * 5
    st_u = SpiderState(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(7)],
        stock,
        [],
    )
    ru = search_to_stock_epoch(
        st_u,
        target_deals=2,
        max_non_deal=2,
        beam=12,
        workspace_max_cost=5,
        max_plan_nodes=25,
        time_limit_s=25.0,
    )
    _summarize(ru, "synthetic Ks-buried + 8s/9s")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
