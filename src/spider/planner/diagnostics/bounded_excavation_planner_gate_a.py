#!/usr/bin/env python3
"""Hard Gate A: bounded planner on the post-Qd-Jd Jd-Td fixture.

Diagnostic/experiment runner.  Does not modify production search.
"""

from __future__ import annotations

import heapq
import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    StrategicSearchNode,
    solve_anytime,
)
from spider.planner.bounded_excavation_planner import plan_scheduled_lane_edge
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
from spider.rules import MW_RULES
import spider.planner.anytime_controller as controller


DEAL_PATH = ROOT / "deals" / "4925153.txt"
HEARTS_PEEL = (8, 3, 5)

POPS = []
NODE_OBJ = {}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=160, sort_dicts=False))
    sys.stdout.flush()


def _install():
    original_record = controller._record_transition
    original_pop = heapq.heappop

    def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
        NODE_OBJ[child.node_id] = child
        return original_record(
            parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
        )

    def wrapped_pop(heap):
        item = original_pop(heap)
        try:
            node = item[2]
        except (IndexError, TypeError):
            return item
        if isinstance(node, StrategicSearchNode):
            NODE_OBJ[node.node_id] = node
            POPS.append(node.node_id)
        return item

    controller._record_transition = wrapped_record
    heapq.heappop = wrapped_pop
    return lambda: (
        setattr(controller, "_record_transition", original_record),
        setattr(heapq, "heappop", original_pop),
    )


def _reset():
    POPS.clear()
    NODE_OBJ.clear()


def _run(start, cards, config):
    _reset()
    uninstall = _install()
    try:
        return solve_anytime(start, cards, None, config)
    finally:
        uninstall()


def _is_qd_jd(state, actions):
    if not actions:
        return False
    act = actions[0]
    if not isinstance(act, tuple) or len(act) != 3:
        return False
    src, dst, k = act
    if k != 1 or not state.can_move(src, dst, k):
        return False
    a = state.columns[src].top()
    b = state.columns[dst].top()
    return bool(a and b and a.suit == "d" and b.suit == "d" and a.rank == 11 and b.rank == 12)


def reconstruct_post_qd_jd():
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        return None, "cost-21"
    _run(anchor.state, cards, _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000))
    node86 = NODE_OBJ.get(86)
    if node86 is None:
        return None, "no-node-86"
    _run(node86.state, cards, _gate_envelope(_gate_z_base_config, 90.0, 10, 300_000))
    kq_node = None
    kq_action = None
    for nid in POPS:
        node = NODE_OBJ.get(nid)
        if node is None:
            continue
        tops = [(ci, col.top()) for ci, col in enumerate(node.state.columns) if col.top()]
        kd = [ci for ci, t in tops if t.suit == "d" and t.rank == 13]
        qd = [ci for ci, t in tops if t.suit == "d" and t.rank == 12]
        if kd and qd and node.state.can_move(qd[0], kd[0], 1):
            kq_node = node
            kq_action = (qd[0], kd[0], 1)
            break
    if kq_node is None:
        return None, "no-kq"
    post = kq_node.state.clone()
    post.move(*kq_action, rules=MW_RULES)
    peel = post.clone()
    peel.move(*HEARTS_PEEL, rules=MW_RULES)
    peel_g = node86.g + kq_node.g + 2
    _run(peel, cards, _gate_envelope(_gate_z_base_config, 90.0, 16, 300_000))
    node17 = None
    for nid in POPS:
        node = NODE_OBJ.get(nid)
        if node is None or node.incoming_edge is None:
            continue
        parent = NODE_OBJ.get(node.parent_id)
        if parent is None:
            continue
        if _is_qd_jd(parent.state, node.incoming_edge.actions):
            node17 = node
            break
    if node17 is None:
        return None, "no-qd-jd-child"
    return node17.state, None


def main() -> int:
    print("HARD GATE A — bounded planner on post-Qd-Jd Jd-Td")
    print("No controller integration until this solves within 8 / 5000.")
    sys.stdout.flush()
    state, err = reconstruct_post_qd_jd()
    if state is None:
        print("STOP: reconstruct", err)
        return 2
    print(" reconstructed stock", len(state.stock), "F", len(state.foundations), "fd", sum(len(c.face_down) for c in state.columns), flush=True)
    plan = plan_scheduled_lane_edge(state, suit="d", high_rank=11, low_rank=10)
    _section(
        1,
        "plan",
        {
            "solved": plan.solved,
            "reject": plan.reject,
            "visited": plan.visited,
            "max_depth": plan.max_depth,
            "actions": plan.actions,
            "n": len(plan.actions),
            "cost": plan.cost,
            "chosen_low_column": None if plan.chosen_low_column is None else plan.chosen_low_column + 1,
            "replay_ok": plan.replay_ok,
            "edge_satisfied": plan.edge_satisfied,
            "joins": (plan.joins_before, plan.joins_after),
            "fd": (plan.fd_before, plan.fd_after),
            "mixed_parks": plan.mixed_parks,
            "elapsed_s": round(plan.elapsed_seconds, 3),
        },
    )
    if not plan.solved or not plan.replay_ok or not plan.edge_satisfied:
        print("STOP: Hard Gate A failed. No controller integration.")
        return 1
    if len(plan.actions) > 8 or plan.visited > 5000:
        print("STOP: Hard Gate A exceeded bounds. No controller integration.")
        return 1
    print("Hard Gate A PASS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
