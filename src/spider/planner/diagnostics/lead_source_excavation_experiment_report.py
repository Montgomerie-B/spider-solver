#!/usr/bin/env python3
"""Natural-gate telemetry for the three-action lead-source excavation macro.

Experiment only.  Not v0.7.  Resource envelopes unchanged.
"""

from __future__ import annotations

import heapq
import pprint
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    StrategicActionKind,
    StrategicCreditLevel,
    StrategicSearchNode,
    analyze_strategic_state,
    generate_strategic_successors,
    solve_anytime,
    _node_priority,
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
from spider.planner.lead_source_excavation import (
    recognise_lead_source_excavation,
)
from spider.planner.receiver_uncover import _lead_ordering_key
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    PreDealOpportunityClass,
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.state_identity import canonical_state_key, states_structurally_equal
import spider.planner.anytime_controller as controller


DEAL_PATH = ROOT / "deals" / "4925153.txt"
MACRO78 = ((3, 0, 1), (3, 9, 1), (2, 3, 1))

POPS: list = []
NODE_OBJ: dict = {}
GENERATED: dict = {}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def _lead(state: SpiderState):
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    if schedule.lane_sequence_priority is None:
        return None
    return schedule.lane_sequence_priority.lead


def _install():
    original_generate = controller.generate_strategic_successors
    original_record = controller._record_transition
    original_pop = heapq.heappop

    def wrapped_generate(node, *args, **kwargs):
        NODE_OBJ[node.node_id] = node
        successors = original_generate(node, *args, **kwargs)
        GENERATED[node.node_id] = tuple(successors)
        return successors

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
            incoming = node.incoming_edge
            sat = None
            must = None
            if node.whole_deal_schedule is not None and node.whole_deal_schedule.saturation is not None:
                sat = node.whole_deal_schedule.saturation.status.value
                must = node.whole_deal_schedule.saturation.must_count
            POPS.append(
                {
                    "id": node.node_id,
                    "parent": node.parent_id,
                    "g": node.g,
                    "stock": len(node.state.stock),
                    "epoch": 5 - len(node.state.stock) // 10,
                    "F": len(node.state.foundations),
                    "fd": sum(len(col.face_down) for col in node.state.columns),
                    "kind": None if incoming is None else incoming.kind.value,
                    "excav": bool(
                        incoming is not None
                        and incoming.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
                    ),
                    "uncover": bool(
                        incoming is not None and incoming.receiver_uncover_followup is not None
                    ),
                    "actions": None if incoming is None else incoming.actions,
                    "debt": controller._milestone_checkpoint_order(node)[0],
                    "sat": sat,
                    "must": must,
                }
            )
        return item

    controller.generate_strategic_successors = wrapped_generate
    controller._record_transition = wrapped_record
    heapq.heappop = wrapped_pop
    return lambda: (
        setattr(controller, "generate_strategic_successors", original_generate),
        setattr(controller, "_record_transition", original_record),
        setattr(heapq, "heappop", original_pop),
    )


def _reset():
    POPS.clear()
    NODE_OBJ.clear()
    GENERATED.clear()


def _run(start, cards, config):
    _reset()
    uninstall = _install()
    try:
        return solve_anytime(start, cards, None, config)
    finally:
        uninstall()


def _clean_successors(state, cards, g=0):
    config = _gate_envelope(_gate_aa_base_config, 8.0, 2, 1_000)
    analysis = analyze_strategic_state(
        state, cards, spent_cost=g, incumbent_cost=None, config=config
    )
    node = StrategicSearchNode(
        0, state, g, (), None, None, 0, StrategicCreditLevel.CLEAN, analysis
    )
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    return successors, telemetry


def _z_safety(result):
    t = result.telemetry
    must_starved = 0
    unauth = 0
    speculative_excav = 0
    for row in POPS:
        node = NODE_OBJ.get(row["id"])
        generated = GENERATED.get(row["id"], ())
        if row["kind"] == "RAW_DEAL" and row["debt"] == 0:
            unauth += 1
        if (
            node is not None
            and node.whole_deal_schedule is not None
            and node.whole_deal_schedule.saturation is not None
            and node.whole_deal_schedule.saturation.status
            == EpochSaturationStatus.PREPARATION_REQUIRED
            and node.whole_deal_schedule.saturation.must_count > 0
            and not any(
                item.scheduler_pre_deal_classification
                == PreDealOpportunityClass.MUST_PRE_DEAL
                or item.category
                in {"permanent_structure", "run_construction", "dependency_closure"}
                for item in generated
            )
        ):
            must_starved += 1
        if row["excav"] and node is not None and node.credit_level != StrategicCreditLevel.CLEAN:
            speculative_excav += 1
    excav_pops = [row for row in POPS if row["excav"]]
    used = []
    for row in excav_pops:
        child = NODE_OBJ.get(row["id"])
        if child is None:
            continue
        lead = _lead(child.state)
        used.append(
            {
                "id": row["id"],
                "g": row["g"],
                "F": row["F"],
                "stock": row["stock"],
                "epoch": row["epoch"],
                "fd": row["fd"],
                "lead": None if lead is None else (lead.suit, lead.state.value),
                "actions": row["actions"],
            }
        )
    return {
        "must_starved": must_starved,
        "unauth_zero_debt_deals": unauth,
        "speculative_excav": speculative_excav,
        "excav_expanded": t.lead_source_excavation_expanded,
        "uncover_generated": t.receiver_uncover_generated,
        "excav_pops": used,
    }


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("LEAD-SOURCE EXCAVATION EXPERIMENT")
    print("Three-action macro. NOT v0.7. Envelopes unchanged.")
    sys.stdout.flush()
    _section(
        0,
        "architecture",
        {
            "kind": "LEAD_SOURCE_EXCAVATION",
            "stock": 0,
            "shape": "two MIXED_SUIT_PARK peels + stable consume",
            "payoff": "consume exposes current-lead first-missing-edge source",
            "canonical": "lead.ordering_key after the complete macro is non-worse",
            "not": (
                "mixed-park cap raise",
                "independent peel emission",
                "generic depth-2/3 search",
                "receiver-uncover widening",
            ),
        },
    )

    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 1

    print("\n== Gate Z ==", flush=True)
    z_config = _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000)
    z_result = _run(anchor.state, cards, z_config)
    seen = {}
    for row in POPS:
        node = NODE_OBJ.get(row["id"])
        if node is None or len(node.state.foundations) != 1 or len(node.state.stock) != 0:
            continue
        key = canonical_state_key(node.state)
        prev = seen.get(key)
        if prev is None or _node_priority(node) < _node_priority(prev):
            seen[key] = node
    stock0 = sorted(seen.values(), key=_node_priority)
    node78 = next((n for n in stock0 if n.node_id == 78), None if not stock0 else stock0[0])
    if node78 is None:
        print("STOP: no stock-empty F1")
        return 2
    macros = recognise_lead_source_excavation(node78.state)
    succ, tel = _clean_successors(node78.state, cards, g=node78.g)
    excav = [item for item in succ if item.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION]
    replay = node78.state.clone()
    replay_ok = False
    exposed = None
    post_lead = None
    if excav:
        cost = replay_actions(replay, list(excav[0].actions))
        replay_ok = cost == excav[0].corrected_cost and states_structurally_equal(
            replay, excav[0].end_state
        )
        exposed = None if replay.columns[2].top() is None else str(replay.columns[2].top())
        lead = _lead(replay)
        post_lead = None if lead is None else (lead.suit, lead.state.value)
    z_replay = anchor.state.clone()
    z_end = z_result.best_progress_node
    z_cost = replay_actions(z_replay, list(z_end.actions))
    safety = _z_safety(z_result)
    safety["replay_ok"] = states_structurally_equal(z_replay, z_end.state) and z_cost == z_end.g
    _section(
        1,
        "node 78",
        {
            "id": node78.node_id,
            "g": node78.g,
            "macros": [item.actions for item in macros],
            "emitted": [item.actions for item in excav],
            "expected": MACRO78,
            "match": bool(excav and excav[0].actions == MACRO78),
            "cost": None if not excav else excav[0].corrected_cost,
            "replay_ok": replay_ok,
            "exposed": exposed,
            "post_lead": post_lead,
            "fd": sum(len(col.face_down) for col in replay.columns) if excav else None,
            "empty": sum(col.is_empty() for col in replay.columns) if excav else None,
            "qualified": tel.lead_source_excavation_qualified,
            "generated": tel.lead_source_excavation_generated,
        },
    )
    _section(
        2,
        "Gate Z",
        {
            "stop": z_result.stop_reason,
            "expansions": z_result.strategic_expansions,
            "considered": z_result.telemetry.lead_source_excavation_considered,
            "qualified": z_result.telemetry.lead_source_excavation_qualified,
            "generated": z_result.telemetry.lead_source_excavation_generated,
            "tt_admitted": z_result.telemetry.lead_source_excavation_tt_admitted,
            "expanded": z_result.telemetry.lead_source_excavation_expanded,
            "replay_ok": safety["replay_ok"],
            "F": z_end.state and len(z_end.state.foundations),
            "stock": len(z_end.state.stock),
            "epoch": 5 - len(z_end.state.stock) // 10,
            "fd": sum(len(col.face_down) for col in z_end.state.columns),
            "uncover_generated": z_result.telemetry.receiver_uncover_generated,
            "envelope": "90s/25/300k",
        },
    )
    _section(3, "Gate Z safety", safety)
    if not excav or excav[0].actions != MACRO78 or not replay_ok:
        print("STOP: node 78 macro not admitted")
        return 3
    if (
        not safety["replay_ok"]
        or safety["must_starved"]
        or safety["unauth_zero_debt_deals"]
        or safety["speculative_excav"]
        or len(z_end.state.foundations) < 1
    ):
        print("STOP: Z safety failed")
        return 4

    print("\n== Gate AA ==", flush=True)
    aa_config = _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000)
    aa_result = _run(opening, cards, aa_config)
    aa_replay = opening.clone()
    aa_end = aa_result.best_progress_node
    aa_cost = replay_actions(aa_replay, list(aa_end.actions))
    aa_excav = [row for row in POPS if row["excav"]]
    subsequent = []
    for row in aa_excav:
        child = NODE_OBJ.get(row["id"])
        if child is None:
            continue
        generated = GENERATED.get(row["id"], ())
        subsequent.append(
            {
                "id": row["id"],
                "g": row["g"],
                "F": row["F"],
                "stock": row["stock"],
                "kinds": tuple(item.kind.value for item in generated[:8]),
            }
        )
    _section(
        4,
        "Gate AA",
        {
            "stop": aa_result.stop_reason,
            "expansions": aa_result.strategic_expansions,
            "considered": aa_result.telemetry.lead_source_excavation_considered,
            "qualified": aa_result.telemetry.lead_source_excavation_qualified,
            "generated": aa_result.telemetry.lead_source_excavation_generated,
            "tt_admitted": aa_result.telemetry.lead_source_excavation_tt_admitted,
            "expanded": aa_result.telemetry.lead_source_excavation_expanded,
            "uncover_generated": aa_result.telemetry.receiver_uncover_generated,
            "replay_ok": states_structurally_equal(aa_replay, aa_end.state)
            and aa_cost == aa_end.g,
            "excav_pops": aa_excav,
            "subsequent": subsequent,
            "envelope": "180s/50/500k",
        },
    )
    if not (
        states_structurally_equal(aa_replay, aa_end.state) and aa_cost == aa_end.g
    ):
        print("STOP: AA replay failed")
        return 5
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
