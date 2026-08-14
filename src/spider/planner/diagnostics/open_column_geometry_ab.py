#!/usr/bin/env python3
"""One-off A/B: latent workspace / open-column geometry through Deal 2.

A = geometry OFF, B = geometry ON.
ACCESS + improved CREATE_WORKSPACE (800 nodes / 0.7s) on both arms.
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
from spider.planner.objective_realizer import RealizationStatus
from spider.planner.plan_search_v2 import (
    ACCESS_KIND,
    PlanNode,
    compute_quality,
    replay_canonical_epochs,
    search_to_stock_epoch,
)
from spider.state_identity import canonical_state_key
from spider.planner.space_lifecycle import empty_count
from spider.planner.workspace_obstruction import open_column_facts, workspace_potential
from spider.planner.workspace_tactics import WorkspaceBackend, realize_workspace


CFG = dict(
    target_deals=2,
    max_non_deal=2,
    beam=16,
    max_plan_nodes=36,
    time_limit_s=80.0,
    tactical_max_cost=3,
    workspace_max_cost=5,
    workspace_max_nodes=800,
    workspace_time_s=0.7,
    use_access_campaigns=True,
    access_max_paid_cost=10,
    access_max_steps=8,
    access_tactical_time_s=0.18,
    use_improved_workspace=True,
)


def _facts(st):
    n_open, n_nonking, min_fd = open_column_facts(st)
    wp = workspace_potential(st)
    return {
        "open": n_open,
        "nonking": n_nonking,
        "min_fd": min_fd,
        "empty": empty_count(st),
        "wp": wp["score"],
    }


def _probe_ws(st):
    res = realize_workspace(
        st,
        backend=WorkspaceBackend.IMPROVED,
        max_cost=8,
        max_nodes=800,
        time_limit_s=0.7,
    )
    if res.status == RealizationStatus.FOUND:
        return res.corrected_mw_cost, int(res.nodes_expanded or 0)
    return None, int(res.nodes_expanded or 0)


def _before_deal(start, node, n=1):
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


def _row(node, label="", extra=""):
    q = node.quality
    print(
        f"  {label}g={node.g} fd={q.face_down} open={q.fully_open_columns} "
        f"nk={q.fully_open_nonking_columns} minfd={q.min_column_fd} "
        f"e={q.empty_count} ssL={q.longest_same_suit} mass={q.same_suit_run_mass} "
        f"found={q.foundations_removed} Hb={q.h1_build:.0f}/{q.h1_removal:.0f} "
        f"Sb={q.s1_build:.0f}/{q.s1_removal:.0f} wp={q.workspace_potential:.1f} "
        f"kinds={list(node.objective_kinds)}{extra}"
    )


def _summarize(name, nodes):
    print(f"  {name} n={len(nodes)}")
    if not nodes:
        return
    best_g = min(nodes, key=lambda n: (n.g, n.quality.face_down))
    best_fd = min(nodes, key=lambda n: (n.quality.face_down, n.g))
    best_geo = max(
        nodes,
        key=lambda n: (
            n.quality.fully_open_nonking_columns,
            -n.quality.min_column_fd,
            n.quality.workspace_potential,
            -n.g,
        ),
    )
    _row(best_g, "cheapest ")
    _row(best_fd, "least_fd ")
    _row(best_geo, "best_geo ")
    acc = sum(1 for n in nodes if ACCESS_KIND in n.objective_kinds)
    any_open = sum(1 for n in nodes if n.quality.fully_open_columns > 0)
    any_nk = sum(1 for n in nodes if n.quality.fully_open_nonking_columns > 0)
    print(f"    with_ACCESS={acc}/{len(nodes)} any_open={any_open} any_nk={any_nk}")


def _snapshot_table(title, triples):
    """triples: list of (label, state, g)."""
    print()
    print(title)
    print(
        f"  {'label':<28} {'g':>4} {'fd':>3} {'open':>4} {'nk':>3} "
        f"{'minfd':>5} {'e':>2} {'ws':>6} {'ssL':>3} {'mass':>4} {'found':>5} {'wp':>6}"
    )
    rows = []
    for label, st, g in triples:
        fd = sum(len(c.face_down) for c in st.columns)
        f = _facts(st)
        cost, nodes = _probe_ws(st)
        ws = f"+{cost}" if cost is not None else "miss"
        q = compute_quality(st, g if g is not None else 0)
        print(
            f"  {label:<28} {g if g is not None else '-':>4} {fd:3d} "
            f"{f['open']:4d} {f['nonking']:3d} {f['min_fd']:5d} {f['empty']:2d} "
            f"{ws:>6} {q.longest_same_suit:3d} {q.same_suit_run_mass:4d} "
            f"{q.foundations_removed:5d} {f['wp']:6.1f}"
        )
        rows.append(
            {
                "label": label,
                "g": g,
                "fd": fd,
                "open": f["open"],
                "nonking": f["nonking"],
                "min_fd": f["min_fd"],
                "empty": f["empty"],
                "ws": cost,
                "ws_nodes": nodes,
                "ssL": q.longest_same_suit,
                "mass": q.same_suit_run_mass,
                "found": q.foundations_removed,
            }
        )
    return rows


def _pick_reps(start, nodes, epoch):
    if not nodes:
        return []
    out = []
    best_g = min(nodes, key=lambda n: (n.g, n.quality.face_down))
    best_fd = min(nodes, key=lambda n: (n.quality.face_down, n.g))
    best_geo = max(
        nodes,
        key=lambda n: (
            n.quality.fully_open_nonking_columns,
            -n.quality.min_column_fd,
            n.quality.workspace_potential,
            -n.g,
        ),
    )
    for tag, n in (("cheapest", best_g), ("least_fd", best_fd), ("best_geo", best_geo)):
        if epoch == "pre-D1":
            st, g = _before_deal(start, n, 1)
        else:
            st, g = n.state, n.g
        out.append((f"{tag}", st, g, n))
    return out


def _run(title, start, cards, geometry):
    print()
    print(title)
    res = search_to_stock_epoch(
        start,
        cards=cards,
        use_open_column_geometry=geometry,
        **CFG,
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
    print(f"  config_geo={res.config.get('use_open_column_geometry')} "
          f"improved_ws={res.config.get('use_improved_workspace')}")
    assert all(t.deals_done == 2 for t in res.terminals)
    assert all(t.actions.count(("deal",)) == 2 for t in res.terminals)
    for t in res.terminals:
        chk = start.clone()
        assert replay_actions(chk, list(t.actions)) == t.g

    pre = []
    for n in res.deal1_nodes:
        st, g = _before_deal(start, n, 1)
        q = compute_quality(st, g)
        pre.append(
            PlanNode(
                state=st,
                g=g,
                actions=n.actions,
                objective_ids=n.objective_ids,
                objective_kinds=n.objective_kinds,
                key=canonical_state_key(st),
                deals_done=0,
                epoch_depth=n.epoch_depth,
                quality=q,
                notes=n.notes,
            )
        )
    _summarize("PRE-D1 (reconstructed)", pre)
    _summarize("POST-D1", res.deal1_nodes)
    _summarize("POST-D2", res.terminals)
    return res, pre


def _keys(nodes):
    return {n.key for n in nodes}


def _max_nk(nodes):
    if not nodes:
        return 0
    return max(n.quality.fully_open_nonking_columns for n in nodes)


def _any_open(nodes):
    return any(n.quality.fully_open_columns > 0 for n in nodes)


def main() -> int:
    t0 = time.time()
    cards = load_deal(ROOT / "deals" / "4925153.txt")
    start = SpiderState.from_cards(list(cards))
    actions = parse_moves_file(ROOT / "solutions" / "4925153_canonical.moves")
    snaps = replay_canonical_epochs(start, actions, up_to_deals=2, cards=cards)

    print("OPEN-COLUMN GEOMETRY A/B — Opening → Deal 2")
    print("ACCESS=ON both. improved CREATE_WORKSPACE 800n/0.7s both.")
    print("A = geometry OFF    B = geometry ON")
    print()
    print("HUMAN REFERENCE (canonical, diagnostic only)")
    human_rows = []
    for key, label in (
        ("pre_deal_1", "human pre-D1"),
        ("post_deal_1", "human post-D1"),
        ("pre_deal_2", "human pre-D2"),
        ("post_deal_2", "human post-D2"),
    ):
        n = snaps.get(key)
        if n is None:
            continue
        _row(n, f"{label} ")
        human_rows.append((label, n.state, n.g))
    _snapshot_table("HUMAN WORKSPACE PROBES", human_rows)

    off, off_pre = _run("A  GEOMETRY-OFF", start, cards, False)
    on, on_pre = _run("B  GEOMETRY-ON", start, cards, True)

    print()
    print("REPRESENTATIVE PROBES")
    probe_rows = []
    for arm, res, pre in (("OFF", off, off_pre), ("ON", on, on_pre)):
        for epoch, nodes in (
            ("pre-D1", pre),
            ("post-D1", res.deal1_nodes),
            ("post-D2", res.terminals),
        ):
            reps = []
            if epoch == "pre-D1":
                if not nodes:
                    continue
                best_g = min(nodes, key=lambda n: (n.g, n.quality.face_down))
                best_geo = max(
                    nodes,
                    key=lambda n: (
                        n.quality.fully_open_nonking_columns,
                        -n.quality.min_column_fd,
                        n.quality.workspace_potential,
                        -n.g,
                    ),
                )
                for tag, n in (("cheapest", best_g), ("best_geo", best_geo)):
                    reps.append((f"{arm} {epoch} {tag}", n.state, n.g))
            else:
                for tag, st, g, _n in _pick_reps(start, nodes, epoch):
                    reps.append((f"{arm} {epoch} {tag}", st, g))
            probe_rows.extend(_snapshot_table(f"{arm} {epoch}", reps))

    print()
    print("PRE-D1 FULLY-OPEN (any reconstructed line)")
    print(f"  OFF any_open={_any_open(off_pre)} max_nk={_max_nk(off_pre)}")
    print(f"  ON  any_open={_any_open(on_pre)} max_nk={_max_nk(on_pre)}")

    print()
    print("STATE-KEY OVERLAP")
    for label, a, b in (
        ("pre-D1", off_pre, on_pre),
        ("post-D1", off.deal1_nodes, on.deal1_nodes),
        ("post-D2", off.terminals, on.terminals),
    ):
        ka, kb = _keys(a), _keys(b)
        print(
            f"  {label}: off={len(ka)} on={len(kb)} "
            f"shared={len(ka & kb)} only_off={len(ka - kb)} only_on={len(kb - ka)}"
        )

    # Hard gate
    print()
    print("SUCCESS GATE")
    reasons = []
    survives = bool(on.deal1_nodes or on.terminals)
    print(f"  ON survives post-D1={bool(on.deal1_nodes)} post-D2={bool(on.terminals)}")

    for label, a, b in (
        ("post-D1", off.deal1_nodes, on.deal1_nodes),
        ("post-D2", off.terminals, on.terminals),
    ):
        off_nk, on_nk = _max_nk(a), _max_nk(b)
        print(f"  max fully-open non-king {label}: OFF={off_nk} ON={on_nk}")
        if on_nk > off_nk:
            reasons.append(f"{label} ON has fully-open non-king {on_nk} vs OFF {off_nk}")

    def cheapest_ws_from_rows(epoch_substr, arm):
        best = None
        for r in probe_rows:
            if arm in r["label"] and epoch_substr in r["label"]:
                cost = r["ws"]
                if cost is None:
                    continue
                if best is None or cost < best:
                    best = cost
        return best

    for epoch in ("post-D1", "post-D2"):
        off_ws = cheapest_ws_from_rows(epoch, "OFF")
        on_ws = cheapest_ws_from_rows(epoch, "ON")
        print(f"  cheapest probed workspace {epoch}: OFF={off_ws} ON={on_ws}")
        if on_ws is not None and (off_ws is None or on_ws <= off_ws - 2):
            reasons.append(f"{epoch} cheaper workspace ON={on_ws} vs OFF={off_ws}")

    same_states = (
        _keys(off.deal1_nodes) == _keys(on.deal1_nodes)
        and _keys(off.terminals) == _keys(on.terminals)
    )
    trivial = same_states and not reasons
    if not survives:
        verdict = "FAILURE"
        note = "ON did not survive to post-D1/D2"
    elif trivial:
        verdict = "FAILURE"
        note = "trivial metric change with the same states"
    elif reasons and survives:
        verdict = "PASS"
        note = "; ".join(reasons)
    else:
        verdict = "FAILURE"
        note = "no material useful-state difference at post-D1/D2"

    print(f"  same_post_states={same_states}")
    print(f"  VERDICT={verdict}")
    print(f"  note={note}")
    print(f"  total_runtime={time.time() - t0:.1f}s")
    print("Done.")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
