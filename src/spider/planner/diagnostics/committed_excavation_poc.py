#!/usr/bin/env python3
"""POC: committed excavation from the true opening.

Portfolio and search never see canonical moves or a target-column constant.
Comparison with the human first-empty happens only after discovery.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.committed_excavation import (
    COST_BOUNDS,
    ProjectStatus,
    classify_actions,
    longest_same_suit,
    measure_progress,
    search_portfolio,
    select_portfolio,
)
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import open_column_facts
from spider.planner.workspace_tactics import WorkspaceBackend, realize_workspace


def _fmt_act(a):
    return f"{a[0] + 1}->{a[1] + 1} k={a[2]}"


def _progress_table(start, actions, target):
    st = start.clone()
    print(
        f"    {'i':>3} {'act':<16} {'role':<12} {'g':>3} {'t_fd':>4} "
        f"{'t_n':>4} {'prereq':>7} {'live':>4} {'dep':>3}"
    )
    g = 0
    roles = classify_actions(start, actions, target)
    p0 = measure_progress(st, target)
    print(
        f"    {0:3d} {'(start)':<16} {'—':<12} {0:3d} {p0.target_fd:4d} "
        f"{p0.target_cards:4d} {p0.prereqs_satisfied}/{p0.prereqs_total:<5} "
        f"{int(p0.next_hop_live):4d} {p0.unresolved_depth:3d}"
    )
    for i, a in enumerate(actions, 1):
        g += replay_actions(st, [a])
        p = measure_progress(st, target)
        print(
            f"    {i:3d} {_fmt_act(a):<16} {roles[i - 1]:<12} {g:3d} "
            f"{p.target_fd:4d} {p.target_cards:4d} "
            f"{p.prereqs_satisfied}/{p.prereqs_total:<5} "
            f"{int(p.next_hop_live):4d} {p.unresolved_depth:3d}"
        )


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    print("COMMITTED EXCAVATION PROJECT SEARCH — true opening")
    print("No deal. Target identity is not a code constant.")
    n_open, n_nk, min_fd = open_column_facts(start)
    print(
        f"  start fd={sum(len(c.face_down) for c in start.columns)} "
        f"e={empty_count(start)} open={n_open} nk={n_nk} minfd={min_fd}"
    )

    port = select_portfolio(start, max_projects=5, cost_slack=4)
    print()
    print("PORTFOLIO (before any canonical comparison)")
    if not port:
        print("  empty — FAIL")
        return 1
    for e in port:
        print(
            f"  col {e.column + 1}: est_cost={e.estimated_cost} "
            f"emptyable={e.emptyable} dest_prep={[c + 1 for c in e.dest_prep]}"
        )
        for r in e.reasons[:2]:
            print(f"    {r}")

    print()
    print("SEARCH (all projects at each bound before raising the bound)")
    sys.stdout.flush()
    by_col = search_portfolio(
        start, port, bounds=COST_BOUNDS, base_nodes=4000, base_time=8.0
    )
    found = []
    for e in port:
        series = by_col[e.column]
        print(f"  -- committed target col {e.column + 1} --")
        for res in series:
            print(
                f"    bound={res.max_cost} {res.status.value} "
                f"cost={res.cost} nodes={res.nodes} t={res.elapsed:.2f}s "
                f"trunc={res.truncated}"
            )
        last = series[-1]
        if last.status == ProjectStatus.FOUND:
            found.append(last)
            print(f"    FOUND col {last.target + 1} cost={last.cost}")
        sys.stdout.flush()

    print()
    print("GATE")
    if not found:
        best = None
        verdict = "FAIL"
        note = "no project found <=25"
    else:
        best = min(found, key=lambda r: (r.cost, r.nodes))
        c = best.cost
        if c < 19:
            verdict = "EXCEPTIONAL"
        elif c <= 19:
            verdict = "STRONG PASS"
        elif c <= 25:
            verdict = "PASS"
        else:
            verdict = "FAIL"
        note = f"best col {best.target + 1} cost={c}"
    print(f"  {verdict}: {note}")

    if best and best.status == ProjectStatus.FOUND:
        print()
        print("BEST ROUTE")
        chk = start.clone()
        recost = replay_actions(chk, list(best.actions))
        assert recost == best.cost
        assert ("deal",) not in best.actions
        assert chk.columns[best.target].is_empty()
        ss, mass = longest_same_suit(chk)
        empties = [i + 1 for i, c in enumerate(chk.columns) if c.is_empty()]
        roles = classify_actions(start, best.actions, best.target)
        n_tgt = sum(1 for r in roles if r == "target")
        n_prep = sum(1 for r in roles if r == "preparation")
        n_aux = sum(1 for r in roles if r == "auxiliary")
        print(f"  target col {best.target + 1}")
        print(f"  cost={best.cost} replay={recost} nodes={best.nodes} t={best.elapsed:.2f}s")
        print(f"  actions: {[_fmt_act(a) for a in best.actions]}")
        print(f"  roles: target={n_tgt} preparation={n_prep} auxiliary={n_aux}")
        print(f"  empties now={empties} ssL={ss} mass={mass}")
        print("  progression:")
        _progress_table(start, best.actions, best.target)

        print()
        print("FOLLOW-ON (new space)")
        from spider.planner.workspace_tactics import productive_follow_on

        follow = productive_follow_on(start, best.actions, max_cost=4, max_nodes=300)
        if not follow:
            print("  none attempted / none found")
        for f in follow:
            print(f"  {f.kind} found={f.found} cost={f.cost} {f.notes}")

        print()
        print("ABLATION vs generic CREATE_WORKSPACE")
        gen = realize_workspace(
            start,
            backend=WorkspaceBackend.IMPROVED,
            max_cost=best.max_cost,
            max_nodes=max(8000, best.nodes * 2),
            time_limit_s=max(8.0, best.elapsed * 2),
        )
        print(
            f"  generic {gen.status.value} cost={gen.corrected_mw_cost} "
            f"nodes={gen.nodes_expanded} t={gen.elapsed_seconds:.2f}s"
        )
        if gen.corrected_mw_cost is not None:
            print(f"  generic actions={len(gen.actions)} vs project {best.cost}")

        print()
        print("CANONICAL COMPARISON (after discovery only)")
        actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
        hs = start.clone()
        hg = 0
        h_empty_at = None
        h_col = None
        prefix = []
        for i, a in enumerate(actions):
            if a == ("deal",):
                break
            hg += replay_actions(hs, [a])
            prefix.append(a)
            if empty_count(hs) > 0:
                h_empty_at = hg
                h_col = next(j for j, c in enumerate(hs.columns) if c.is_empty())
                break
        print(
            f"  human first empty: col {h_col + 1 if h_col is not None else '—'} "
            f"cost={h_empty_at} moves={len(prefix)}"
        )
        print(f"  machine target col {best.target + 1} cost={best.cost} moves={len(best.actions)}")
        same_tgt = h_col == best.target
        print(
            f"  same target={same_tgt} cheaper={best.cost < (h_empty_at or 99)} "
            f"same_length={len(best.actions) == len(prefix)}"
        )

    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0 if verdict in ("EXCEPTIONAL", "STRONG PASS", "PASS") else 1


if __name__ == "__main__":
    raise SystemExit(main())
