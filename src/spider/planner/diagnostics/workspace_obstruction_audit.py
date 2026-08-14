#!/usr/bin/env python3
"""One-off workspace obstruction audit (no planner integration)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import rank_str
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.plan_search_v2 import replay_canonical_epochs, search_to_stock_epoch
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import (
    promising_columns,
    profile_state,
    progressive_search,
    workspace_potential,
)


def _before_deal(start, node, n=1):
    """Replay until just before the n-th deal (1-based)."""
    st = start.clone()
    g = 0
    deals = 0
    for a in node.actions:
        if a == ("deal",):
            deals += 1
            if deals == n:
                return st, g
        g += replay_actions(st, [a])
    return st, g


def _print_table(name, st, g=None):
    print()
    print("=" * 88)
    extra = f" g={g}" if g is not None else ""
    print(
        f"{name}{extra}  fd={sum(len(c.face_down) for c in st.columns)} "
        f"e={empty_count(st)} stock={len(st.stock)}"
    )
    wp = workspace_potential(st)
    print(
        f"  workspace_potential score={wp['score']:.1f} "
        f"create={wp['one_move_creates']:.0f} reloc={wp['one_move_relocates']:.0f} "
        f"open={wp['open_columns']:.0f} short={wp['shortest_open']:.0f} "
        f"dest_hits={wp['dest_hits']:.0f} dest_miss={wp['dest_miss']:.0f}"
    )
    print(
        f"  {'c':>3} {'fd':>3} {'fu':>3} {'ssT':>3} {'runs':>4} {'movK':>4} "
        f"{'head':>5} {'need':>4} {'1e':>3} {'1c':>3} {'rev':>3} "
        f"{'destNE':>10} {'destE':>8} shortage"
    )
    for p in profile_state(st):
        need = rank_str(p.need_rank) if p.need_rank else "—"
        dne = ",".join(str(d + 1) for d in p.dests_nonempty) or "—"
        de = ",".join(str(d + 1) for d in p.dests_empty) or "—"
        print(
            f"  {p.column + 1:3d} {p.face_down:3d} {p.face_up:3d} "
            f"{p.same_suit_top_run:3d} {p.visible_runs:4d} {p.movable_k:4d} "
            f"{(p.movable_head or '—'):>5} {need:>4} "
            f"{'Y' if p.one_move_empty else '.':>3} "
            f"{'Y' if p.one_move_creates else '.':>3} "
            f"{'Y' if p.moving_reveals else '.':>3} "
            f"{dne:>10} {de:>8} {p.shortage}"
        )
        print(
            f"       need_tops={p.visible_need_tops} buried={p.buried_need} "
            f"stock={p.stock_need} total_cards={p.cards_total}"
        )


def _print_search(tag, results, st):
    for r in results:
        tgt = f"col{r.target_column + 1}" if r.target_column is not None else "any"
        print(
            f"  {tag} {tgt} ceil={r.ceiling} {r.status} "
            f"cost={r.cost} nodes={r.nodes} t={r.elapsed:.1f}s"
        )
        ng = r.near
        print(
            f"    near: min_open={ng.min_cards_any_open} "
            f"target_cards={ng.min_cards_target} @g={ng.cost_at_best} "
            f"top={ng.target_top} need={ng.target_need}"
        )
        print(f"    blocker={ng.blocker} :: {ng.blocker_detail}")
        if r.status == "FOUND" and r.actions:
            print(f"    actions={r.actions[:12]}{'…' if len(r.actions) > 12 else ''}")
            chk = st.clone()
            replay_actions(chk, list(r.actions))
            emptied = [i + 1 for i, c in enumerate(chk.columns) if c.is_empty()]
            print(f"    emptied_cols={emptied} e={empty_count(chk)}")


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    human_actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, human_actions, up_to_deals=2, cards=cards)

    print("WORKSPACE OBSTRUCTION AUDIT")
    print("Collecting 1L machine states (ACCESS-ON, no extra deal)...")
    res = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=3,
        max_non_deal=3,
        beam=16,
        max_plan_nodes=36,
        time_limit_s=45.0,
        use_access_campaigns=True,
        access_max_paid_cost=10,
        access_max_steps=8,
        access_tactical_time_s=0.18,
        tactical_max_cost=3,
        workspace_max_cost=5,
    )
    print(
        f"  d1={len(res.deal1_nodes)} d2={len(res.deal2_nodes)} "
        f"d3={len(res.terminals)} time={res.stats.elapsed_seconds:.1f}s"
    )

    states = []
    if res.deal1_nodes:
        d1 = min(res.deal1_nodes, key=lambda n: (n.quality.face_down, n.g))
        pre, gpre = _before_deal(start, d1, n=1)
        states.append(("MACHINE pre-D1 (before first deal of least-fd D1)", pre, gpre))
        states.append(("MACHINE post-D1 least-fd", d1.state, d1.g))
        print(
            f"  D1 lineage g={d1.g} fd={d1.quality.face_down} "
            f"kinds={list(d1.objective_kinds)} pre_stock={len(pre.stock)} "
            f"post_stock={len(d1.state.stock)}"
        )
    if res.deal2_nodes:
        # 1M: least-fd had cost-4 workspace; best-ss missed. Audit the miss.
        d2_ss = max(
            res.deal2_nodes,
            key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g),
        )
        d2_fd = min(res.deal2_nodes, key=lambda n: (n.quality.face_down, n.g))
        states.append(("MACHINE post-D2 best-ss (1M no cheap workspace)", d2_ss.state, d2_ss.g))
        print(
            f"  post-D2 least-fd g={d2_fd.g} fd={d2_fd.quality.face_down} "
            f"(1M found +4); using best-ss g={d2_ss.g} "
            f"fd={d2_ss.quality.face_down} ssL={d2_ss.quality.longest_same_suit}"
        )
    else:
        print("  WARNING: no post-D2 machine nodes harvested")

    hpre = snaps["pre_deal_1"]
    hd2 = snaps["post_deal_2"]
    states.append(("HUMAN pre-D1", hpre.state, hpre.g))
    states.append(("HUMAN post-D2", hd2.state, hd2.g))

    hard_names = {
        "MACHINE pre-D1 (before first deal of least-fd D1)",
        "MACHINE post-D1 least-fd",
        "MACHINE post-D2 best-ss (1M no cheap workspace)",
    }
    human_names = {"HUMAN pre-D1", "HUMAN post-D2"}

    metrics = []
    for name, st, g in states:
        _print_table(name, st, g)
        metrics.append((name, workspace_potential(st)))

        # Any-workspace progressive search. Humans should find cheaply.
        deep = name in hard_names
        sched = (
            ((4, 30000, 6.0), (8, 100000, 12.0), (12, 200000, 18.0), (16, 350000, 25.0), (20, 500000, 30.0))
            if deep
            else ((4, 8000, 3.0), (8, 20000, 5.0))
        )
        print()
        print(f"  DEEP any-workspace ({name})")
        any_res = progressive_search(st, target_column=None, schedule=sched)
        _print_search("ANY", any_res, st)

        # Target-specific: 2–3 most promising open columns
        cols = promising_columns(st, k=3)
        print(f"  TARGET columns={[c + 1 for c in cols]}")
        tsched = (
            ((8, 80000, 10.0), (12, 150000, 15.0), (20, 300000, 20.0))
            if deep
            else ((4, 8000, 3.0), (8, 20000, 5.0))
        )
        for col in cols:
            tres = progressive_search(st, target_column=col, schedule=tsched)
            _print_search("TGT", tres, st)

    print()
    print("WORKSPACE_POTENTIAL COMPARISON")
    for name, wp in metrics:
        print(
            f"  {name}: score={wp['score']:.1f} create={wp['one_move_creates']:.0f} "
            f"open={wp['open_columns']:.0f} short={wp['shortest_open']:.0f} "
            f"hits={wp['dest_hits']:.0f} miss={wp['dest_miss']:.0f}"
        )

    print(f"\ntotal_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
