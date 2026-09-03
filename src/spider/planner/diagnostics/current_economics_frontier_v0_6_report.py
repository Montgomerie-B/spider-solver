#!/usr/bin/env python3
"""Natural-gate telemetry for scheduler v0.6 current-state frontier economics."""

from __future__ import annotations

import heapq
import pprint
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.planner.anytime_controller import (
    StrategicActionKind,
    StrategicSearchNode,
    solve_anytime,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
    _gate_g_config as _gate_aa_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
import spider.planner.anytime_controller as controller
from spider.planner.whole_deal_scheduler import EpochTransitionRepresentativeStatus
from spider.metrics import replay_actions
from spider.state_identity import states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
_DEAL_KINDS = {
    StrategicActionKind.DEAL_NOW,
    StrategicActionKind.PREPARE_THEN_DEAL,
    StrategicActionKind.RAW_DEAL,
}
_AUTH = {
    EpochTransitionRepresentativeStatus.RESERVED,
    EpochTransitionRepresentativeStatus.SPENT,
}

POPS: list = []
TRANSITIONS: dict = {}
CHILDREN: dict = {}
AUTHORISED: set = set()
NODE_OBJ: dict = {}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def _is_deal(node: StrategicSearchNode) -> bool:
    incoming = node.incoming_edge
    return incoming is not None and (
        incoming.kind in _DEAL_KINDS or incoming.actions == (("deal",),)
    )


def _fd(state: SpiderState) -> int:
    return sum(len(column.face_down) for column in state.columns)


def _lead(node):
    schedule = node.whole_deal_schedule
    if schedule is None or schedule.lane_sequence_priority is None:
        return None
    lead = schedule.lane_sequence_priority.lead
    if lead is None:
        return None
    cash = lead.cash_out_estimate
    return {
        "suit": lead.suit,
        "state": lead.state.value,
        "fp": lead.lane_fingerprint[:8],
        "cash": cash.ordering_key(),
        "future": cash.future_gate_count,
        "gap": cash.terminal_gap,
        "blocker": cash.blocker_work,
    }


def _remember(node: StrategicSearchNode):
    NODE_OBJ[node.node_id] = node
    opp = node.epoch_transition_opportunity
    if _is_deal(node) and opp is not None and opp.status in _AUTH:
        AUTHORISED.add(node.node_id)


def _ancestors(nid):
    ids = []
    seen = set()
    current = nid
    while current is not None and current not in seen:
        seen.add(current)
        ids.append(current)
        current = TRANSITIONS.get(current)
    ids.reverse()
    return ids


def _install():
    original_record = controller._record_transition
    original_heappop = heapq.heappop

    def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
        TRANSITIONS[child.node_id] = parent.node_id
        CHILDREN.setdefault(parent.node_id, []).append(child.node_id)
        _remember(child)
        return original_record(
            parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
        )

    def wrapped_heappop(heap):
        item = original_heappop(heap)
        try:
            node = item[2]
        except (IndexError, TypeError):
            return item
        if isinstance(node, StrategicSearchNode):
            _remember(node)
            incoming = node.incoming_edge
            POPS.append(
                {
                    "id": node.node_id,
                    "parent": node.parent_id,
                    "kind": None if incoming is None else incoming.kind.value,
                    "deal": _is_deal(node),
                    "g": node.g,
                    "stock": len(node.state.stock),
                    "epoch": 5 - len(node.state.stock) // 10,
                    "F": len(node.state.foundations),
                    "fd": _fd(node.state),
                    "auth": node.node_id in AUTHORISED,
                    "auth_ids": node.authorised_epoch_transition_ids,
                    "debt": controller._milestone_checkpoint_order(node)[0],
                    "lead": _lead(node),
                    "sat": None
                    if node.whole_deal_schedule is None or node.whole_deal_schedule.saturation is None
                    else node.whole_deal_schedule.saturation.status.value,
                    "must": None
                    if node.whole_deal_schedule is None or node.whole_deal_schedule.saturation is None
                    else node.whole_deal_schedule.saturation.must_count,
                }
            )
        return item

    controller._record_transition = wrapped_record
    heapq.heappop = wrapped_heappop
    return lambda: (
        setattr(controller, "_record_transition", original_record),
        setattr(heapq, "heappop", original_heappop),
    )


def _reset():
    POPS.clear()
    TRANSITIONS.clear()
    CHILDREN.clear()
    AUTHORISED.clear()
    NODE_OBJ.clear()


def _run(start, cards, config):
    _reset()
    uninstall = _install()
    try:
        return solve_anytime(start, cards, None, config)
    finally:
        uninstall()


def _lineage_expansions(deal_id):
    expanded = []
    for row in POPS:
        if deal_id in _ancestors(row["id"]) and row["id"] != deal_id:
            expanded.append(row["id"])
    return expanded


def _summarize(name, result, start):
    auth_pops = [row for row in POPS if row["deal"] and row["auth_ids"]]
    deal_pops = [row for row in POPS if row["deal"]]
    lineages = []
    for deal in auth_pops:
        desc = _lineage_expansions(deal["id"])
        children = CHILDREN.get(deal["id"], [])
        lineages.append(
            {
                "deal": deal["id"],
                "g": deal["g"],
                "stock": deal["stock"],
                "epoch": deal["epoch"],
                "lead": deal["lead"],
                "direct_children": len(children),
                "descendant_expansions": len(desc),
                "descendant_ids": tuple(desc),
            }
        )
    deepest = min(POPS, key=lambda row: (row["stock"], -row["g"])) if POPS else None
    best_f = max(POPS, key=lambda row: (row["F"], -row["fd"])) if POPS else None
    replay = start.clone()
    endpoint = result.best_progress_node
    replay_cost = replay_actions(replay, list(endpoint.actions))
    return {
        "stop": result.stop_reason,
        "expansions": result.strategic_expansions,
        "tactical": result.tactical_nodes,
        "pops": len(POPS),
        "deal_pops": len(deal_pops),
        "authorised_deal_pops": tuple(row["id"] for row in auth_pops),
        "lineages_ge2": sum(item["descendant_expansions"] >= 1 for item in lineages),
        "lineages_ge3": sum(item["descendant_expansions"] >= 2 for item in lineages),
        "deepest": None
        if deepest is None
        else (deepest["id"], deepest["stock"], deepest["epoch"], deepest["g"], deepest["F"]),
        "best_F": None if best_f is None else (best_f["id"], best_f["F"], best_f["stock"], best_f["fd"]),
        "replay_ok": states_structurally_equal(replay, endpoint.state) and replay_cost == endpoint.g,
        "timeline": [
            (row["id"], row["kind"], row["deal"], row["stock"], row["F"], row["debt"], row["sat"])
            for row in POPS
        ],
        "lineages": lineages,
        "cash_out_pops": [
            (row["id"], row["lead"])
            for row in POPS
            if row["lead"] is not None
        ][:12],
    }


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("CURRENT-ECONOMICS FRONTIER v0.6")
    sys.stdout.flush()
    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 1

    print("\n== Gate AA ==")
    sys.stdout.flush()
    aa = _run(opening, cards, _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000))
    aa_sum = _summarize("AA", aa, opening)
    _section(1, "Gate AA", aa_sum)
    if aa_sum["lineages_ge2"] < 1:
        print("PRIMARY FAIL: no authorised Deal lineage received a second expansion")
        return 2

    print("\n== Gate Z ==")
    sys.stdout.flush()
    z = _run(anchor.state, cards, _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000))
    z_sum = _summarize("Z", z, anchor.state)
    _section(2, "Gate Z", z_sum)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
