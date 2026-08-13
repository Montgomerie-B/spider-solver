#!/usr/bin/env python3
"""Sprint 1M — CREATE_WORKSPACE old vs new on 1L stratified states."""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.objective_realizer import RealizationStatus
from spider.planner.plan_search_v2 import replay_canonical_epochs, search_to_stock_epoch
from spider.planner.space_lifecycle import empty_count
from spider.planner.strategic_analysis import analyze_strategic
from spider.planner.workspace_tactics import (
    WorkspaceBackend,
    compare_workspace_backends,
    productive_follow_on,
    realize_workspace,
)


CEILINGS = (3, 5, 8, 12)


def _label_state(name, st, g=None):
    extra = f" g={g}" if g is not None else ""
    print(f"  {name}{extra} fd={sum(len(c.face_down) for c in st.columns)} "
          f"e={empty_count(st)} stock={len(st.stock)}")


def _best_found(attempts):
    found = [a for a in attempts if a.status == RealizationStatus.FOUND]
    if not found:
        return None
    return min(found, key=lambda a: (a.cost if a.cost is not None else 99, a.nodes))


def _print_backend(name, attempts):
    bits = []
    for a in attempts:
        if a.status == RealizationStatus.FOUND:
            bits.append(f"+{a.cost} n={a.nodes} t={a.elapsed:.2f}s")
        else:
            bits.append(f"{a.status.value} n={a.nodes}")
    print(f"    {name}: " + " | ".join(bits))
    best = _best_found(attempts)
    if best:
        fo = [f"{x.kind}:{'Y' if x.found else 'n'}" for x in best.follow_on]
        print(f"      cheapest={best.cost} follow-on={fo or '—'}")
    return best


def _eval_state(name, st, g=None, foundation=False, cards=None):
    print()
    _label_state(name, st, g)
    cmp = compare_workspace_backends(
        st, ceilings=CEILINGS, max_nodes=1800, time_limit_s=0.7
    )
    old = _print_backend("legacy", cmp["legacy"])
    new = _print_backend("improved", cmp["improved"])
    gate = []
    if new and not old:
        gate.append("A_new_finds_where_old_fails")
    if new and old and new.cost is not None and old.cost is not None and new.cost < old.cost:
        gate.append("B_cheaper")
    if new and any(f.found for f in new.follow_on):
        gate.append("C_productive_follow_on")
    print(f"    gate={gate or ['none']}")
    found_delta = None
    if foundation and new and new.actions:
        before = analyze_strategic(st, cards=cards, run_shaping_probe=False)
        after_st = st.clone()
        replay_actions(after_st, list(new.actions))
        after = analyze_strategic(after_st, cards=cards, run_shaping_probe=False)
        if before.foundation and after.foundation:
            def top(an):
                cands = [c for c in an.foundation.frontier.candidates if not c.already_completed]
                if not cands:
                    return None
                return max(
                    cands,
                    key=lambda c: (
                        c.heuristic_removal_readiness if c.theoretically_available else 0.0,
                        c.heuristic_build_readiness,
                    ),
                )
            tb, ta = top(before), top(after)
            if tb and ta:
                print(
                    f"    foundation top {tb.label}->{ta.label} "
                    f"build {tb.heuristic_build_readiness:.0f}->{ta.heuristic_build_readiness:.0f} "
                    f"rem {tb.heuristic_removal_readiness:.0f}->{ta.heuristic_removal_readiness:.0f}"
                )
                found_delta = (
                    ta.heuristic_build_readiness - tb.heuristic_build_readiness,
                    ta.heuristic_removal_readiness - tb.heuristic_removal_readiness,
                    ta.label,
                )
    return {
        "name": name,
        "old": old,
        "new": new,
        "gate": gate,
        "foundation": found_delta,
    }


def _pre_deal_state(start, node):
    st = start.clone()
    acts = list(node.actions)
    if acts and acts[-1] == ("deal",):
        acts = acts[:-1]
    if acts:
        replay_actions(st, acts)
    return st, node.g - (1 if node.actions and node.actions[-1] == ("deal",) else 0)


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    human_actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, human_actions, up_to_deals=3, cards=cards)

    print("SPRINT 1M — TACTICAL WORKSPACE BREAKTHROUGH")
    print("Collecting 1L stratified machine states (short ACCESS-ON)...")
    res = search_to_stock_epoch(
        start,
        cards=cards,
        target_deals=3,
        max_non_deal=3,
        beam=16,
        max_plan_nodes=32,
        time_limit_s=40.0,
        use_access_campaigns=True,
        access_max_paid_cost=10,
        access_max_steps=8,
        access_tactical_time_s=0.18,
        tactical_max_cost=3,
        workspace_max_cost=5,
    )
    print(
        f"  terminals={len(res.terminals)} d1={len(res.deal1_nodes)} "
        f"d2={len(res.deal2_nodes)} time={res.stats.elapsed_seconds:.1f}s"
    )

    states = []
    # strong pre-D1
    if res.deal1_nodes:
        d1_strong = min(res.deal1_nodes, key=lambda n: (n.quality.face_down, n.g))
        pre, gpre = _pre_deal_state(start, d1_strong)
        states.append(("pre-D1 (from best D1)", pre, gpre, False))
        states.append(("post-D1 least-fd", d1_strong.state, d1_strong.g, False))
    if res.deal2_nodes:
        d2_fd = min(res.deal2_nodes, key=lambda n: (n.quality.face_down, n.g))
        d2_ss = max(
            res.deal2_nodes,
            key=lambda n: (n.quality.longest_same_suit, n.quality.same_suit_run_mass, -n.g),
        )
        states.append(("post-D2 least-fd", d2_fd.state, d2_fd.g, True))
        states.append(("post-D2 best-ss", d2_ss.state, d2_ss.g, False))
    if res.terminals:
        d3 = min(res.terminals, key=lambda n: (n.quality.face_down, n.g))
        states.append(("post-D3 least-fd", d3.state, d3.g, False))

    print("HUMAN CHECKPOINTS (comparison only)")
    for key in ("pre_deal_1", "post_deal_1", "post_deal_2", "post_deal_3"):
        n = snaps.get(key)
        if n:
            states.append((f"human {key}", n.state, n.g, False))

    synth = SpiderState(
        [
            Column([Card("c", 2)], [Card("s", 13)]),
            Column([], [Card("s", 9), Card("s", 8)]),
            Column([], [Card("s", 7)]),
        ]
        + [Column([], [Card("d", 5 if i % 2 else 4)]) for i in range(7)],
        [Card("h", r) for r in range(1, 11)] * 3,
        [],
    )
    states.append(("synthetic workspace", synth, 0, False))

    reports = []
    for name, st, g, fdiag in states:
        reports.append(_eval_state(name, st, g, foundation=fdiag, cards=cards))

    print()
    print("SUCCESS GATE")
    a = any("A_new_finds_where_old_fails" in r["gate"] for r in reports)
    b = any("B_cheaper" in r["gate"] for r in reports)
    c = any("C_productive_follow_on" in r["gate"] for r in reports)
    passed = a or b or c
    print(f"  A_new_on_1F_miss={a} B_cheaper={b} C_productive={c}")
    print(f"  RESULT={'PASS' if passed else 'FAILURE TO BREAK WORKSPACE BOTTLENECK'}")
    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
