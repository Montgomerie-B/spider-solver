#!/usr/bin/env python3
"""Sprint 1L — A/B ACCESS-integrated epoch search through Deal 3."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file
from spider.planner.plan_search_v2 import (
    ACCESS_KIND,
    replay_canonical_epochs,
    search_to_stock_epoch,
)


def _row(t, label=""):
    q = t.quality
    inv = t.investment_per_fd
    inv_s = f"{inv:.2f}" if inv is not None else "—"
    print(
        f"  {label}g={t.g} fd={q.face_down} e={q.empty_count} "
        f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
        f"found={q.foundations_removed} "
        f"Hb={q.h1_build:.0f}/{q.h1_removal:.0f} "
        f"Sb={q.s1_build:.0f}/{q.s1_removal:.0f} "
        f"stockSS={q.predeal_same_suit_landings} "
        f"inv={t.investment_paid}/{t.investment_fd} per={inv_s} "
        f"kinds={list(t.objective_kinds)}"
    )


def _run(title, start, cards, use_access):
    print()
    print(title)
    res = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=3,
        max_non_deal=3,
        beam=16,
        tactical_max_cost=3,
        workspace_max_cost=5,
        max_plan_nodes=32,
        time_limit_s=40.0,
        use_access_campaigns=use_access,
        access_max_paid_cost=10,
        access_max_steps=8,
        access_tactical_time_s=0.18,
    )
    s = res.stats
    print(
        f"  nodes={s.plan_nodes} try={s.realizations_attempted} "
        f"found={s.realizations_found} miss={s.realizations_miss} "
        f"res={s.realizations_resource} "
        f"acc_try={s.access_macros_attempted} acc_ok={s.access_macros_applied} "
        f"acc_zero={s.access_macros_zero} acc_cache={s.access_cache_hits} "
        f"acc_paid={s.access_paid} acc_fd={s.access_fd_reduced} "
        f"d1={s.deal1_frontier} d2={s.deal2_frontier} "
        f"time={s.elapsed_seconds:.1f}s terminals={len(res.terminals)}"
    )
    print(f"  families={s.families_tried}")
    assert all(t.deals_done == 3 for t in res.terminals)
    assert all(t.actions.count(("deal",)) == 3 for t in res.terminals)
    assert all(ACCESS_KIND not in t.objective_kinds or use_access for t in res.terminals)
    if res.terminals:
        best_fd = min(res.terminals, key=lambda n: (n.quality.face_down, n.g))
        best_g = min(res.terminals, key=lambda n: (n.g, n.quality.face_down))
        best_ss = max(
            res.terminals,
            key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g),
        )
        best_found = max(res.terminals, key=lambda n: (n.quality.foundations_removed, -n.g))
        _row(best_g, "cheapest ")
        _row(best_fd, "least_fd ")
        _row(best_ss, "best_ss  ")
        _row(best_found, "best_rm  ")
        acc_n = sum(1 for t in res.terminals if ACCESS_KIND in t.objective_kinds)
        print(f"  terminals_with_ACCESS={acc_n}/{len(res.terminals)}")
        print(f"  pareto={len(res.pareto_terminals)} stratified={len(res.stratified_terminals)}")
        print("  stratified:")
        for t in res.stratified_terminals[:6]:
            _row(t)
    return res


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, actions, up_to_deals=3, cards=cards)

    print("SPRINT 1L — ACCESS-INTEGRATED EPOCH PLANNING THROUGH DEAL 3")
    print("HUMAN REFERENCE (canonical, diagnostic only)")
    for k in (
        "initial",
        "pre_deal_1",
        "post_deal_1",
        "pre_deal_2",
        "post_deal_2",
        "pre_deal_3",
        "post_deal_3",
    ):
        n = snaps.get(k)
        if not n:
            continue
        q = n.quality
        print(
            f"  {k}: g={n.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
            f"found={q.foundations_removed} "
            f"H1t={q.h1_theo} Hb={q.h1_build:.0f}/{q.h1_removal:.0f} "
            f"S1t={q.s1_theo} Sb={q.s1_build:.0f}/{q.s1_removal:.0f}"
        )

    off = _run("A. WITHOUT ACCESS (baseline)", start, cards, False)
    on = _run("B. WITH ACCESS", start, cards, True)

    print()
    print("A/B COMPARISON (Deal-3 terminals)")
    if off.terminals and on.terminals:
        off_fd = min(t.quality.face_down for t in off.terminals)
        on_fd = min(t.quality.face_down for t in on.terminals)
        off_g = min(t.g for t in off.terminals)
        on_g = min(t.g for t in on.terminals)
        print(f"  least_fd  off={off_fd} on={on_fd} Δ={off_fd - on_fd}")
        print(f"  cheapest  off={off_g} on={on_g}")
        print(
            f"  ACCESS applied={on.stats.access_macros_applied} "
            f"paid={on.stats.access_paid} fdΔ={on.stats.access_fd_reduced}"
        )
        print(
            f"  foundations off={max(t.quality.foundations_removed for t in off.terminals)} "
            f"on={max(t.quality.foundations_removed for t in on.terminals)}"
        )
    human_d3 = snaps.get("post_deal_3") or snaps.get("pre_deal_3")
    if human_d3:
        print(
            f"  human around D3: g={human_d3.g} fd={human_d3.quality.face_down} "
            f"ssL={human_d3.quality.longest_same_suit} "
            f"found={human_d3.quality.foundations_removed}"
        )

    print()
    print("UNRELATED SYNTHETIC")
    stock = [Card("h", r) for r in range(1, 11)] * 3
    st_u = SpiderState(
        [
            Column([Card("c", 2), Card("c", 3)], [Card("c", 4)]),
            Column([], [Card("c", 5)]),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(8)],
        stock,
        [],
    )
    u = search_to_stock_epoch(
        st_u,
        target_deals=3,
        max_non_deal=2,
        beam=8,
        max_plan_nodes=16,
        time_limit_s=10.0,
        use_access_campaigns=True,
        access_max_paid_cost=6,
    )
    print(
        f"  terminals={len(u.terminals)} acc={u.stats.access_macros_applied} "
        f"time={u.stats.elapsed_seconds:.1f}s"
    )
    if u.terminals:
        b = min(u.terminals, key=lambda n: (n.quality.face_down, n.g))
        print(
            f"  best fd={b.quality.face_down} g={b.g} "
            f"kinds={list(b.objective_kinds)} inv_fd={b.investment_fd}"
        )
        assert b.deals_done == 3

    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
