#!/usr/bin/env python3
"""One-off diagnostic: excavation dependency closure.

Canonical tape is used only after ranking, as validation.
plan_search is not modified; a tiny search is used only to fetch one
weak machine pre-D1 snapshot if cheap.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.backward_strategy import analyze_buried_cards
from spider.planner.excavation_closure import (
    close_all_columns,
    rank_closures,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import open_column_facts


PREVIOUS_TIED = (3, 4, 6, 7, 8, 10)  # 1-based; report-only, not a ranker input


def _walk(start: SpiderState, actions):
    st = start.clone()
    g = 0
    deals = 0
    snaps = {"opening": (st.clone(), 0, 0)}
    prev_e = empty_count(st)
    for i, a in enumerate(actions):
        e_before = empty_count(st)
        if a == ("deal",):
            deals += 1
            if deals == 1:
                snaps["pre_d1"] = (st.clone(), g, i)
            elif deals == 2:
                snaps["pre_d2"] = (st.clone(), g, i)
            g += replay_actions(st, [a])
        else:
            g += replay_actions(st, [a])
        e_after = empty_count(st)
        if "first_space" not in snaps and e_after > prev_e:
            snaps["first_space"] = (st.clone(), g, i + 1)
            snaps["first_empty_col"] = (
                next(
                    (j for j, c in enumerate(st.columns) if c.is_empty()),
                    None,
                ),
            )
        prev_e = e_after
    return snaps


def _print_table(title, closures, ranked, first_empty=None):
    print()
    print(title)
    by = {p.column: p for p in closures}
    print(
        f"  {'rk':>2} {'col':>3} {'fd':>3} {'hops':>4} {'prep':>4} {'tot':>4} "
        f"{'dep':>3} {'blk':>3} {'stk':>3} {'spc':>3} {'emp':>3} "
        f"{'fwd':>5} {'bwd':>5} {'comb':>5} dest-prep"
    )
    for i, r in enumerate(ranked, 1):
        p = by[r.column]
        prep_s = ",".join(str(c + 1) for c in p.dest_prep_columns) or "—"
        mark = " <-- first-empty" if first_empty == r.column else ""
        print(
            f"  {i:2d} {r.column + 1:3d} {p.face_down:3d} {p.direct_target_moves:4d} "
            f"{p.estimated_prep_cost:4d} {p.estimated_total_cost:4d} "
            f"{p.dependency_depth:3d} {p.blocked_deps:3d} {p.future_stock_deps:3d} "
            f"{int(p.needs_temp_space):3d} {int(p.emptyable_this_epoch):3d} "
            f"{r.forward:5.2f} {r.backward:5.2f} {r.combined:5.2f} {prep_s}{mark}"
        )
    return ranked


def _explain(closures, ranked, n=3):
    by = {p.column: p for p in closures}
    print("  why top projects:")
    for r in ranked[:n]:
        p = by[r.column]
        print(f"    col {r.column + 1}: {r.label}")
        for note in p.reasons:
            print(f"      {note}")
        ready = sum(1 for h in p.hop_closures if h.hard_ready)
        print(
            f"      hops ready now {ready}/{len(p.hop_closures)}; "
            f"valuable={list(p.valuable_en_route)[:4]}"
        )
        for h in p.hop_closures:
            ch = ""
            if h.chosen is not None:
                ch = f" -> {h.chosen.loc.card} {h.chosen.availability.value}"
            print(
                f"      hop {h.hop.card} need={h.hop.need_rank} "
                f"ready={h.hard_ready} blk={h.blocked} stock={h.future_stock} "
                f"space={h.needs_space}{ch}"
            )


def _machine_pre_d1(start, cards):
    try:
        from spider.planner.plan_search_v2 import search_to_stock_epoch
    except Exception:
        return None
    res = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=1,
        max_non_deal=2,
        beam=8,
        max_plan_nodes=16,
        time_limit_s=12.0,
        use_access_campaigns=True,
        access_max_paid_cost=8,
    )
    pool = list(res.deal1_nodes) or list(res.terminals)
    if not pool:
        return None
    node = min(pool, key=lambda n: (n.quality.face_down, n.g))
    st = start.clone()
    g = 0
    for a in node.actions:
        if a == ("deal",):
            break
        g += replay_actions(st, [a])
    return st, g, node.quality.face_down


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = _walk(start, actions)
    first_empty = None
    if "first_empty_col" in snaps:
        first_empty = snaps["first_empty_col"][0]
    print("EXCAVATION DEPENDENCY CLOSURE")
    print("Canonical identity is validation only; not a ranker input.")
    print(f"  previous six-way tied set (1-based): {list(PREVIOUS_TIED)}")
    print(f"  canonical first-empty column (validation): {None if first_empty is None else first_empty + 1}")

    results = {}
    for key in ("opening", "first_space", "pre_d1", "pre_d2"):
        if key not in snaps:
            print(f"\n{key} MISSING")
            continue
        st, g, idx = snaps[key]
        fd = sum(len(c.face_down) for c in st.columns)
        n_open, n_nk, min_fd = open_column_facts(st)
        print()
        print("=" * 96)
        print(
            f"{key} g={g} fd={fd} e={empty_count(st)} "
            f"open={n_open} nk={n_nk} minfd={min_fd} stock={len(st.stock)}"
        )
        buried = analyze_buried_cards(st, cards=cards)
        closures = close_all_columns(st, buried=buried)
        ranked = rank_closures(closures, epoch=current_stock_epoch(st, 5))
        _print_table(f"  {key} rank", closures, ranked, first_empty if key == "opening" else None)
        _explain(closures, ranked, 3)
        results[key] = (closures, ranked, st, g)

    print()
    print("=" * 96)
    print("OPENING vs PREVIOUS TIE / FIRST-EMPTY")
    closures, ranked, _, _ = results["opening"]
    order = [r.column + 1 for r in ranked]
    print(f"  new rank (1-based): {order}")
    tied_scores = []
    for col1 in PREVIOUS_TIED:
        r = next((x for x in ranked if x.column == col1 - 1), None)
        if r:
            tied_scores.append((col1, r.combined, r.est_cost, r.emptyable))
    print("  previous tied set in new rank:")
    for col1, comb, cost, emp in tied_scores:
        rk = next(i for i, r in enumerate(ranked, 1) if r.column == col1 - 1)
        print(f"    col {col1}: rank {rk} comb={comb:.2f} cost~{cost} emptyable={emp}")
    scores = [r.combined for r in ranked[:6]]
    spread = max(scores) - min(scores) if scores else 0
    print(f"  top-6 combined spread={spread:.3f} (old tie was ~0.00)")

    fe_rank = None
    if first_empty is not None:
        fe_rank = next(i for i, r in enumerate(ranked, 1) if r.column == first_empty)
        bucket = "top-1" if fe_rank == 1 else ("top-3" if fe_rank <= 3 else "outside top-3")
        print(f"  canonical first-empty col {first_empty + 1} is {bucket} (rank {fe_rank})")

    print()
    print("WEAK MACHINE PRE-D1")
    mach = _machine_pre_d1(start, cards)
    if mach is None:
        print("  (not available)")
    else:
        st, g, fd = mach
        n_open, n_nk, min_fd = open_column_facts(st)
        print(f"  g={g} fd={fd} e={empty_count(st)} open={n_open} nk={n_nk} minfd={min_fd}")
        buried = analyze_buried_cards(st, cards=cards)
        closures = close_all_columns(st, buried=buried)
        ranked_m = rank_closures(closures, epoch=current_stock_epoch(st, 5))
        _print_table("  machine pre-D1 rank", closures, ranked_m)
        _explain(closures, ranked_m, 3)
        if first_empty is not None:
            if any(r.column == first_empty for r in ranked_m):
                rk = next(i for i, r in enumerate(ranked_m, 1) if r.column == first_empty)
                print(f"  first-empty col {first_empty + 1} still rank {rk} on machine state")
            else:
                print("  first-empty column already gone / empty on machine state")

    print()
    print("GATE")
    # STRONG: first-empty in top-3 AND opening no longer a flat six-way tie.
    if first_empty is None:
        verdict = "FAIL"
        note = "could not locate first empty"
    elif fe_rank is None:
        verdict = "FAIL"
        note = "first-empty not ranked"
    elif fe_rank <= 3 and spread >= 0.06:
        verdict = "STRONG PASS"
        note = (
            f"first-empty col {first_empty + 1} is rank {fe_rank}; "
            f"top-6 spread {spread:.3f} breaks the old tie"
        )
    elif fe_rank <= 5 or spread >= 0.04:
        verdict = "PARTIAL"
        note = (
            f"some differentiation (first-empty rank {fe_rank}, "
            f"spread {spread:.3f}) but opening still broadly ambiguous"
        )
    else:
        verdict = "FAIL"
        note = f"still flat (first-empty rank {fe_rank}, spread {spread:.3f})"
    print(f"  {verdict}: {note}")
    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0 if verdict == "STRONG PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
