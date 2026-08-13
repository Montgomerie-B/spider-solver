#!/usr/bin/env python3
"""Sprint 1L — tiny/medium/larger A/B ACCESS epoch search through Deal 3."""

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
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.strategic_campaigns import CampaignKind, generate_campaigns


CONFIGS = (
    (
        "tiny",
        dict(
            max_non_deal=1,
            beam=8,
            max_plan_nodes=16,
            time_limit_s=15.0,
            access_max_paid_cost=6,
            access_max_steps=5,
        ),
    ),
    (
        "medium",
        dict(
            max_non_deal=2,
            beam=16,
            max_plan_nodes=32,
            time_limit_s=40.0,
            access_max_paid_cost=10,
            access_max_steps=8,
        ),
    ),
    (
        "larger",
        dict(
            max_non_deal=3,
            beam=20,
            max_plan_nodes=48,
            time_limit_s=70.0,
            access_max_paid_cost=12,
            access_max_steps=10,
        ),
    ),
)


def _row(t, label=""):
    q = t.quality
    inv = t.investment_per_fd
    inv_s = f"{inv:.2f}" if inv is not None else "—"
    print(
        f"  {label}g={t.g} fd={q.face_down} e={q.empty_count} "
        f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
        f"found={q.foundations_removed} "
        f"H1t={q.h1_theo} Hb={q.h1_build:.0f}/{q.h1_removal:.0f} "
        f"S1t={q.s1_theo} Sb={q.s1_build:.0f}/{q.s1_removal:.0f} "
        f"stockSS={q.predeal_same_suit_landings} "
        f"inv={t.investment_paid}/{t.investment_fd} per={inv_s} "
        f"kinds={list(t.objective_kinds)}"
    )


def _frontier(name, nodes):
    print(f"  {name} n={len(nodes)}")
    if not nodes:
        return
    best_g = min(nodes, key=lambda n: (n.g, n.quality.face_down))
    best_fd = min(nodes, key=lambda n: (n.quality.face_down, n.g))
    best_ss = max(
        nodes,
        key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g),
    )
    best_rm = max(nodes, key=lambda n: (n.quality.foundations_removed, -n.g))
    _row(best_g, "cheapest ")
    _row(best_fd, "least_fd ")
    _row(best_ss, "best_ss  ")
    _row(best_rm, "best_rm  ")
    acc = sum(1 for n in nodes if ACCESS_KIND in n.objective_kinds)
    print(f"    with_ACCESS={acc}/{len(nodes)}")


def _run(title, start, cards, use_access, cfg):
    print()
    print(title)
    res = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=3,
        tactical_max_cost=3,
        workspace_max_cost=5,
        use_access_campaigns=use_access,
        access_tactical_time_s=0.18,
        **cfg,
    )
    s = res.stats
    print(
        f"  nodes={s.plan_nodes} try={s.realizations_attempted} "
        f"found={s.realizations_found} miss={s.realizations_miss} "
        f"res={s.realizations_resource} "
        f"acc_try={s.access_macros_attempted} acc_ok={s.access_macros_applied} "
        f"acc_zero={s.access_macros_zero} acc_cache={s.access_cache_hits} "
        f"acc_paid={s.access_paid} acc_fd={s.access_fd_reduced} "
        f"acc_by_epoch={dict(s.access_applied_by_epoch)} "
        f"acc_paid_ep={dict(s.access_paid_by_epoch)} "
        f"acc_fd_ep={dict(s.access_fd_by_epoch)} "
        f"d1={s.deal1_frontier} d2={s.deal2_frontier} "
        f"time={s.elapsed_seconds:.1f}s terminals={len(res.terminals)}"
    )
    print(f"  families={s.families_tried}")
    assert all(t.deals_done == 3 for t in res.terminals)
    assert all(t.actions.count(("deal",)) == 3 for t in res.terminals)
    assert all(ACCESS_KIND not in t.objective_kinds or use_access for t in res.terminals)
    _frontier("POST-D1", res.deal1_nodes)
    _frontier("POST-D2", res.deal2_nodes)
    _frontier("POST-D3", res.terminals)
    if res.stratified_terminals:
        print("  stratified D3:")
        for t in res.stratified_terminals[:6]:
            _row(t)
    return res


def _foundation_selector(title, state, cards):
    print()
    print(title)
    analysis = analyze_strategic(state, cards=cards, run_shaping_probe=False)
    if analysis.foundation is None:
        print("  no foundation analysis")
        return
    cands = [c for c in analysis.foundation.frontier.candidates if not c.already_completed]
    cands.sort(
        key=lambda c: (
            -c.heuristic_removal_readiness if c.theoretically_available else 0.0,
            -c.heuristic_build_readiness,
            c.earliest_epoch if c.earliest_epoch is not None else 99,
            c.suit,
            c.copy_index,
        )
    )
    print("  independent 1A rank (not a forced campaign):")
    for i, c in enumerate(cands[:6]):
        print(
            f"    [{i}] {c.label} theo={c.theoretically_available} "
            f"epoch={c.earliest_epoch} build={c.heuristic_build_readiness:.1f} "
            f"rem={c.heuristic_removal_readiness:.1f} frag={c.longest_same_suit_fragment}"
        )
    camps = generate_campaigns(state, cards=cards, analysis=analysis)
    founds = [c for c in camps if c.kind == CampaignKind.FOUNDATION_BUILD]
    print("  generated FOUNDATION_BUILD (not plan edges in 1L):")
    for c in founds:
        print(f"    {c.campaign_id} pri={c.heuristic_priority:.1f} :: {c.reason}")


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

    _foundation_selector(
        "INDEPENDENT FOUNDATION RANK @ human post-D2 (not forced)",
        snaps["post_deal_2"].state,
        cards,
    )

    results = {}
    for name, cfg in CONFIGS:
        off = _run(f"{name.upper()} ACCESS-OFF", start, cards, False, cfg)
        on = _run(f"{name.upper()} ACCESS-ON", start, cards, True, cfg)
        results[name] = (off, on)
        print()
        print(f"{name.upper()} A/B")
        for label, off_nodes, on_nodes in (
            ("D1", off.deal1_nodes, on.deal1_nodes),
            ("D2", off.deal2_nodes, on.deal2_nodes),
            ("D3", off.terminals, on.terminals),
        ):
            off_fd = min((n.quality.face_down for n in off_nodes), default=None)
            on_fd = min((n.quality.face_down for n in on_nodes), default=None)
            print(f"  least_fd {label}: off={off_fd} on={on_fd}")

    print()
    print("CANONICAL COMPARISON")
    human = {
        "D1": snaps.get("post_deal_1"),
        "D2": snaps.get("post_deal_2"),
        "D3": snaps.get("post_deal_3"),
    }
    for epoch, key in (("D1", "post_deal_1"), ("D2", "post_deal_2"), ("D3", "post_deal_3")):
        h = snaps.get(key)
        if not h:
            continue
        print(
            f"  human {epoch}: g={h.g} fd={h.quality.face_down} "
            f"ssL={h.quality.longest_same_suit} found={h.quality.foundations_removed}"
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
        f"by_epoch={dict(u.stats.access_applied_by_epoch)} "
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
