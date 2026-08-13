#!/usr/bin/env python3
"""Sprint 1I — post-Deal-2 maturation / deferred-work diagnostic."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.plan_search_v2 import (
    replay_canonical_epochs,
    search_epoch_maturation,
    search_to_stock_epoch,
    select_stratified_seeds,
)
from spider.planner.strategic_analysis import analyze_strategic


def _row(n, label=""):
    q = n.quality
    fd0 = getattr(n, "_seed_fd", None)
    add = n.added_cost
    red = (fd0 - q.face_down) if fd0 is not None else None
    eff = (red / add) if add and red is not None else None
    print(
        f"  {label}g={n.g} +{add} fd={q.face_down} e={q.empty_count} "
        f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
        f"found={q.foundations_removed} "
        f"H1b={q.h1_build:.0f}/{q.h1_removal:.0f} "
        f"S1b={q.s1_build:.0f}/{q.s1_removal:.0f} "
        f"D3ss={q.predeal_same_suit_landings} "
        f"eff={eff if eff is not None else '—'}"
    )
    print(f"    kinds={list(n.objective_kinds)}")


def _attach_seed_fd(nodes, seeds):
    by = {s.key: s.quality.face_down for s in seeds}
    for n in nodes:
        # match longest seed prefix
        fd = None
        for s in seeds:
            if n.actions[: len(s.actions)] == s.actions:
                fd = s.quality.face_down
                break
        object.__setattr__(n, "_seed_fd", fd) if False else setattr(n, "_seed_fd", fd)


def main() -> int:
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, actions, up_to_deals=3, cards=cards)
    print("SPRINT 1I — POST-DEAL-2 MATURATION")
    print("HUMAN REFERENCE")
    for k in ("post_deal_2", "pre_deal_3"):
        n = snaps.get(k)
        if n:
            q = n.quality
            print(
                f"  {k}: g={n.g} fd={q.face_down} e={q.empty_count} "
                f"ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
                f"H1t={q.h1_theo} S1t={q.s1_theo} "
                f"Hb={q.h1_build:.0f} Hr={q.h1_removal:.0f} "
                f"Sb={q.s1_build:.0f} Sr={q.s1_removal:.0f}"
            )

    print()
    print("Collecting machine Deal-2 seeds (short 1H)...")
    d2 = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=2,
        max_non_deal=3,
        beam=24,
        tactical_max_cost=3,
        workspace_max_cost=5,
        max_plan_nodes=40,
        time_limit_s=40.0,
    )
    seeds = select_stratified_seeds(d2.terminals, limit=5)
    print(f"deal2_terminals={len(d2.terminals)} seeds={len(seeds)}")
    print("SEEDS")
    for i, s in enumerate(seeds):
        q = s.quality
        print(
            f"  [{i}] g={s.g} fd={q.face_down} e={q.empty_count} "
            f"ssL={q.longest_same_suit} Hb={q.h1_build:.0f} Sb={q.s1_build:.0f} "
            f"kinds={list(s.objective_kinds)}"
        )

    human_d2 = snaps["post_deal_2"]
    human_d3 = snaps.get("pre_deal_3")

    for budget in (5, 10, 15):
        print()
        print(f"MATURATION +{budget}")
        mat = search_epoch_maturation(
            seeds,
            cards=cards,
            deals_done=2,
            max_added_cost=budget,
            max_objectives=5,
            beam=14,
            tactical_max_cost=4,
            workspace_max_cost=6,
            cheap_reveal_max=2,
            max_plan_nodes=28,
            time_limit_s=50.0,
        )
        stt = mat.stats
        print(
            f"  nodes={stt.plan_nodes} try={stt.realizations_attempted} "
            f"found={stt.realizations_found} miss={stt.realizations_miss} "
            f"res={stt.realizations_resource} ws_ex={stt.workspace_then_expose} "
            f"time={stt.elapsed_seconds:.1f}s survivors={len(mat.terminals)}"
        )
        _attach_seed_fd(mat.terminals, seeds)
        # best catch-up: min fd, then min g
        best_fd = min(mat.terminals, key=lambda n: (n.quality.face_down, n.g))
        best_ss = max(mat.terminals, key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g))
        best_hs = max(mat.terminals, key=lambda n: (n.quality.h1_build + n.quality.s1_build, -n.g))
        _row(best_fd, "least_fd ")
        _row(best_ss, "best_ss  ")
        _row(best_hs, "best_HS  ")
        print("  stratified:")
        for n in mat.stratified_terminals[:6]:
            _attach_seed_fd([n], seeds)
            _row(n)
        # compare human
        print(
            f"  vs human post-D2 g={human_d2.g} fd={human_d2.quality.face_down} "
            f"ssL={human_d2.quality.longest_same_suit}"
        )
        if human_d3:
            print(
                f"  vs human pre-D3 g={human_d3.g} fd={human_d3.quality.face_down} "
                f"ssL={human_d3.quality.longest_same_suit}"
            )
        found_rm = sum(1 for n in mat.terminals if n.quality.foundations_removed > 0)
        print(f"  terminals_with_foundation_removed={found_rm}")

    # Human-only maturation (separate beam)
    print()
    print("HUMAN POST-D2 MATURATION +10 (separate)")
    hseed = snaps["post_deal_2"]
    hm = search_epoch_maturation(
        [hseed],
        cards=cards,
        deals_done=2,
        max_added_cost=10,
        max_objectives=4,
        beam=10,
        max_plan_nodes=18,
        time_limit_s=30.0,
    )
    print(
        f"  survivors={len(hm.terminals)} found={hm.stats.realizations_found} "
        f"time={hm.stats.elapsed_seconds:.1f}s"
    )
    if hm.terminals:
        best = min(hm.terminals, key=lambda n: (n.quality.face_down, n.g))
        print(
            f"  best fd={best.quality.face_down} +{best.added_cost} "
            f"ssL={best.quality.longest_same_suit} found={best.quality.foundations_removed}"
        )

    print()
    print("UNRELATED SYNTHETIC")
    stock = [Card("h", r) for r in range(1, 11)] * 3
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
    u2 = search_to_stock_epoch(
        st_u, target_deals=2, max_non_deal=2, beam=8, max_plan_nodes=16, time_limit_s=12.0
    )
    useeds = select_stratified_seeds(u2.terminals, limit=3)
    um = search_epoch_maturation(
        useeds, deals_done=2, max_added_cost=8, beam=8, max_plan_nodes=16, time_limit_s=12.0
    )
    print(
        f"  seeds={len(useeds)} matured={len(um.terminals)} "
        f"ws_ex={um.stats.workspace_then_expose} time={um.stats.elapsed_seconds:.1f}s"
    )
    if um.terminals:
        b = min(um.terminals, key=lambda n: (n.quality.face_down, n.g))
        print(f"  best fd={b.quality.face_down} +{b.added_cost} kinds={list(b.objective_kinds)}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
