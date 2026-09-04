#!/usr/bin/env python3
"""Natural-gate telemetry for scheduler v0.8 face-down lead-edge excavation.

Resource envelopes unchanged from v0.7.  The targeted continuation uses a
small fixed strategic limit from the reconstructed post-hearts-peel state.
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
from spider.move_lifecycle import PlacementClass, assess_tableau_move
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
from spider.planner.face_down_lead_edge_excavation import (
    recognise_face_down_lead_edge_excavation,
)
from spider.planner.lead_source_excavation import recognise_lead_source_excavation
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    PreDealOpportunityClass,
)
from spider.rules import MW_RULES
from spider.state_identity import states_structurally_equal
import spider.planner.anytime_controller as controller


DEAL_PATH = ROOT / "deals" / "4925153.txt"
HEARTS_PEEL = (8, 3, 5)
SUFFIX = ((8, 2, 1), (8, 6, 1), (8, 6, 1))
CONTINUATION_EXPANSIONS = 16

POPS: list = []
NODE_OBJ: dict = {}
GENERATED: dict = {}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


def _fd(state: SpiderState) -> int:
    return sum(len(col.face_down) for col in state.columns)


def _empty(state: SpiderState) -> int:
    return sum(col.is_empty() for col in state.columns)


def _qd_jd(state: SpiderState):
    for src in range(10):
        top = state.columns[src].top()
        if top is None or top.suit != "d" or top.rank != 11:
            continue
        for dst in range(10):
            if src == dst:
                continue
            recv = state.columns[dst].top()
            if recv is None or recv.suit != "d" or recv.rank != 12:
                continue
            if state.can_move(src, dst, 1):
                return (src, dst, 1)
    return None


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
            if (
                node.whole_deal_schedule is not None
                and node.whole_deal_schedule.saturation is not None
            ):
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
                    "fd": _fd(node.state),
                    "kind": None if incoming is None else incoming.kind.value,
                    "excav": bool(
                        incoming is not None
                        and incoming.kind == StrategicActionKind.LEAD_SOURCE_EXCAVATION
                    ),
                    "fd_excav": bool(
                        incoming is not None
                        and incoming.kind
                        == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
                    ),
                    "uncover": bool(
                        incoming is not None
                        and incoming.receiver_uncover_followup is not None
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


def _safety(result):
    t = result.telemetry
    must_starved = 0
    unauth = 0
    speculative = 0
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
        if (row["excav"] or row["fd_excav"]) and node is not None:
            if node.credit_level != StrategicCreditLevel.CLEAN:
                speculative += 1
    unauth_rows = [
        row for row in POPS if row["kind"] == "RAW_DEAL" and row["debt"] == 0
    ]
    return {
        "must_starved": must_starved,
        "unauth_zero_debt_deals": unauth,
        "unauth_rows": unauth_rows[:4],
        "speculative_excav": speculative,
        "v07_expanded": t.lead_source_excavation_expanded,
        "v07_generated": t.lead_source_excavation_generated,
        "fd_expanded": t.face_down_lead_edge_excavation_expanded,
        "fd_generated": t.face_down_lead_edge_excavation_generated,
        "uncover_generated": t.receiver_uncover_generated,
    }


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("FACE-DOWN LEAD-EDGE EXCAVATION v0.8")
    print("Three-action macro. Envelopes unchanged.")
    sys.stdout.flush()
    _section(
        0,
        "architecture",
        {
            "kind": "FACE_DOWN_LEAD_EDGE_EXCAVATION",
            "stock": 0,
            "shape": "two MIXED_SUIT_PARK peels + stable consume of flipped X",
            "payoff": "consume flips a schedule-lane missing-edge rank",
            "canonical": "owning lane.ordering_key after the complete macro is non-worse",
            "not": (
                "mixed-park cap raise",
                "independent peel emission",
                "generic depth-3 search",
                "v0.7 lead-source excavation widening",
                "receiver-uncover widening",
            ),
        },
    )

    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 1

    print("\n== reconstruct post-KQ / post-hearts-peel ==", flush=True)
    z_config = _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000)
    z_from_anchor = _run(anchor.state, cards, z_config)
    node86 = NODE_OBJ.get(86)
    if node86 is None:
        print("STOP: no node 86")
        return 2
    z_safety = _safety(z_from_anchor)
    z_replay = anchor.state.clone()
    z_end = z_from_anchor.best_progress_node
    z_cost = replay_actions(z_replay, list(z_end.actions))
    z_safety["replay_ok"] = (
        states_structurally_equal(z_replay, z_end.state) and z_cost == z_end.g
    )
    _section(
        1,
        "Gate Z from cost-21",
        {
            "stop": z_from_anchor.stop_reason,
            "expansions": z_from_anchor.strategic_expansions,
            "v07_considered": z_from_anchor.telemetry.lead_source_excavation_considered,
            "v07_qualified": z_from_anchor.telemetry.lead_source_excavation_qualified,
            "v07_generated": z_from_anchor.telemetry.lead_source_excavation_generated,
            "v07_tt": z_from_anchor.telemetry.lead_source_excavation_tt_admitted,
            "v07_expanded": z_from_anchor.telemetry.lead_source_excavation_expanded,
            "fd_considered": z_from_anchor.telemetry.face_down_lead_edge_excavation_considered,
            "fd_qualified": z_from_anchor.telemetry.face_down_lead_edge_excavation_qualified,
            "fd_generated": z_from_anchor.telemetry.face_down_lead_edge_excavation_generated,
            "fd_tt": z_from_anchor.telemetry.face_down_lead_edge_excavation_tt_admitted,
            "fd_expanded": z_from_anchor.telemetry.face_down_lead_edge_excavation_expanded,
            "uncover_generated": z_from_anchor.telemetry.receiver_uncover_generated,
            "F": len(z_end.state.foundations),
            "envelope": "90s/25/300k",
        },
    )
    _section(2, "Gate Z safety", z_safety)
    if (
        not z_safety["replay_ok"]
        or z_safety["must_starved"]
        or z_safety["unauth_zero_debt_deals"]
        or z_safety["speculative_excav"]
        or len(z_end.state.foundations) < 1
        or z_from_anchor.telemetry.lead_source_excavation_expanded < 1
    ):
        print("STOP: Z safety / v0.7 retention failed")
        return 3

    _run(node86.state, cards, _gate_envelope(_gate_z_base_config, 90.0, 10, 300_000))
    kq_node = None
    kq_action = None
    for row in POPS:
        node = NODE_OBJ.get(row["id"])
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
        print("STOP: no KQ both-tops state")
        return 4
    post_kq = kq_node.state.clone()
    post_kq.move(*kq_action, rules=MW_RULES)
    if not post_kq.can_move(*HEARTS_PEEL):
        print("STOP: hearts peel illegal")
        return 5
    peel = post_kq.clone()
    peel.move(*HEARTS_PEEL, rules=MW_RULES)
    g = node86.g + kq_node.g + 2
    macros = recognise_face_down_lead_edge_excavation(peel)
    succ, tel = _clean_successors(peel, cards, g=g)
    excav = [
        item
        for item in succ
        if item.kind == StrategicActionKind.FACE_DOWN_LEAD_EDGE_EXCAVATION
    ]
    chosen = None
    replay_ok = False
    jd_exposed = False
    qd_jd = None
    if excav:
        chosen = excav[0].actions
        replay = peel.clone()
        cost = replay_actions(replay, list(chosen))
        replay_ok = cost == excav[0].corrected_cost and states_structurally_equal(
            replay, excav[0].end_state
        )
        jd_exposed = bool(replay.columns[8].top() and replay.columns[8].top().rank == 11)
        qd_jd = _qd_jd(replay)
    _section(
        3,
        "post-hearts-peel",
        {
            "g": g,
            "stock": len(peel.stock),
            "fd": _fd(peel),
            "empty": _empty(peel),
            "c9_fu": tuple(str(c) for c in peel.columns[8].face_up),
            "macros": [item.actions for item in macros],
            "emitted": [item.actions for item in excav],
            "expected": SUFFIX,
            "match": bool(excav and excav[0].actions == SUFFIX),
            "cost": None if not excav else excav[0].corrected_cost,
            "replay_ok": replay_ok,
            "jd_exposed": jd_exposed,
            "qd_jd": qd_jd,
            "v07_macros": [item.actions for item in recognise_lead_source_excavation(peel)],
            "qualified": tel.face_down_lead_edge_excavation_qualified,
            "generated": tel.face_down_lead_edge_excavation_generated,
        },
    )
    if not excav or not replay_ok or not jd_exposed or qd_jd is None:
        print("STOP: post-hearts-peel macro failed")
        return 6
    after = peel.clone()
    replay_actions(after, list(chosen))
    after_succ, _ = _clean_successors(after, cards, g=g + 3)
    qd_jd_generated = any(
        item.actions == (qd_jd,) or qd_jd in item.actions for item in after_succ
    )
    if not qd_jd_generated:
        print("STOP: Qd-Jd not generated after suffix")
        return 7

    print("\n== targeted continuation ==", flush=True)
    cont = _run(
        peel,
        cards,
        _gate_envelope(_gate_z_base_config, 90.0, CONTINUATION_EXPANSIONS, 300_000),
    )
    fd_pops = [row for row in POPS if row["fd_excav"]]
    qd_jd_pops = [
        row
        for row in POPS
        if row["actions"] is not None
        and (row["actions"] == (qd_jd,) or qd_jd in row["actions"])
    ]
    expanded_child = None
    if fd_pops:
        expanded_child = NODE_OBJ.get(fd_pops[0]["id"])
    child_generated = ()
    if expanded_child is not None:
        child_generated = GENERATED.get(expanded_child.node_id, ())
    qd_jd_from_child = any(
        item.actions == (qd_jd,) or qd_jd in item.actions for item in child_generated
    )
    _section(
        4,
        "targeted continuation",
        {
            "stop": cont.stop_reason,
            "expansions": cont.strategic_expansions,
            "limit": CONTINUATION_EXPANSIONS,
            "qualified": cont.telemetry.face_down_lead_edge_excavation_qualified,
            "generated": cont.telemetry.face_down_lead_edge_excavation_generated,
            "tt_admitted": cont.telemetry.face_down_lead_edge_excavation_tt_admitted,
            "expanded": cont.telemetry.face_down_lead_edge_excavation_expanded,
            "fd_pops": fd_pops,
            "jd_exposed": bool(
                expanded_child is not None
                and expanded_child.state.columns[8].top() is not None
                and expanded_child.state.columns[8].top().rank == 11
                and expanded_child.state.columns[8].top().suit == "d"
            ),
            "qd_jd_generated_from_child": qd_jd_from_child,
            "qd_jd_popped": bool(qd_jd_pops),
            "qd_jd_pops": qd_jd_pops[:4],
            "v07_expanded": cont.telemetry.lead_source_excavation_expanded,
            "uncover_generated": cont.telemetry.receiver_uncover_generated,
        },
    )
    if (
        cont.telemetry.face_down_lead_edge_excavation_generated < 1
        or cont.telemetry.face_down_lead_edge_excavation_tt_admitted < 1
        or cont.telemetry.face_down_lead_edge_excavation_expanded < 1
        or not qd_jd_from_child
    ):
        print("STOP: targeted continuation did not expand the macro / generate Qd-Jd")
        return 8

    print("\n== Gate AA ==", flush=True)
    aa_config = _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000)
    aa_result = _run(opening, cards, aa_config)
    aa_replay = opening.clone()
    aa_end = aa_result.best_progress_node
    aa_cost = replay_actions(aa_replay, list(aa_end.actions))
    aa_safety = _safety(aa_result)
    aa_safety["replay_ok"] = (
        states_structurally_equal(aa_replay, aa_end.state) and aa_cost == aa_end.g
    )
    _section(
        5,
        "Gate AA",
        {
            "stop": aa_result.stop_reason,
            "expansions": aa_result.strategic_expansions,
            "v07_considered": aa_result.telemetry.lead_source_excavation_considered,
            "v07_generated": aa_result.telemetry.lead_source_excavation_generated,
            "v07_tt": aa_result.telemetry.lead_source_excavation_tt_admitted,
            "v07_expanded": aa_result.telemetry.lead_source_excavation_expanded,
            "fd_considered": aa_result.telemetry.face_down_lead_edge_excavation_considered,
            "fd_qualified": aa_result.telemetry.face_down_lead_edge_excavation_qualified,
            "fd_generated": aa_result.telemetry.face_down_lead_edge_excavation_generated,
            "fd_tt": aa_result.telemetry.face_down_lead_edge_excavation_tt_admitted,
            "fd_expanded": aa_result.telemetry.face_down_lead_edge_excavation_expanded,
            "uncover_generated": aa_result.telemetry.receiver_uncover_generated,
            "replay_ok": aa_safety["replay_ok"],
            "envelope": "180s/50/500k",
        },
    )
    _section(6, "Gate AA safety", aa_safety)
    if (
        not aa_safety["replay_ok"]
        or aa_safety["must_starved"]
        or aa_safety["speculative_excav"]
        or aa_result.telemetry.face_down_lead_edge_excavation_generated
    ):
        print("STOP: AA safety failed")
        return 9
    # AA never reaches stock-empty, so the new capability cannot promote a Deal.
    # RAW_DEAL rows with zero anonymous debt are reported; v0.7 AA gated replay
    # only.  Gate Z remains the stock-empty authorised-Deal check.
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
