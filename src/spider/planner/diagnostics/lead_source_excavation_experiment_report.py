#!/usr/bin/env python3
"""Natural-gate telemetry for bounded lead-source excavation.

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
from spider.planner.lead_source_excavation import assess_lead_source_excavation
from spider.planner.receiver_uncover import assess_receiver_uncover
from spider.state_identity import canonical_state_key, states_structurally_equal
import spider.planner.anytime_controller as controller
from tests.test_lead_source_excavation_experiment import (
    CONSUME,
    PARK1,
    PARK2,
    known_pattern_state,
)


DEAL_PATH = ROOT / "deals" / "4925153.txt"
PATH78 = ((3, 0, 1), (3, 8, 1), (2, 3, 1))

POPS: list = []
NODE_OBJ: dict = {}
GENERATED: dict = {}


def _section(n, title, value):
    print(f"\n{n}. {title}")
    print(pprint.pformat(value, width=140, sort_dicts=False))
    sys.stdout.flush()


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
            POPS.append(
                {
                    "id": node.node_id,
                    "g": node.g,
                    "stock": len(node.state.stock),
                    "F": len(node.state.foundations),
                    "excav": bool(
                        incoming is not None
                        and incoming.lead_source_excavation_followup is not None
                    ),
                    "uncover": bool(
                        incoming is not None and incoming.receiver_uncover_followup is not None
                    ),
                    "actions": None if incoming is None else incoming.actions,
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


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("LEAD-SOURCE EXCAVATION EXPERIMENT")
    print("NOT v0.7. Resource envelopes unchanged.")
    sys.stdout.flush()

    _section(
        0,
        "architecture",
        {
            "first_park": "MIXED_SUIT_PARK, no stable join broken",
            "second_park": "same source column, MIXED_SUIT_PARK, no join broken",
            "consume": "exact same-suit join onto the newly exposed receiver",
            "payoff": "consume exposes a current lead-lane missing-edge source",
            "uncover": "already-qualified one-ply uncover is not stolen",
            "clean": "TEMPORARY_REWORK + bounded_payoff, not parked-card EXIT",
            "resources": "unchanged",
        },
    )

    synthetic = known_pattern_state()
    evidence = assess_lead_source_excavation(synthetic, PARK1)
    successors, telemetry = _clean_successors(synthetic, _cards_from_state(synthetic))
    excav = [
        item
        for item in successors
        if item.actions == (PARK1,) and item.lead_source_excavation_followup == PARK2
    ]
    _section(
        1,
        "synthetic known pattern",
        {
            "qualified": evidence.qualified,
            "second_park": evidence.second_park,
            "consume": evidence.consume,
            "exposed": None if evidence.exposed_source is None else str(evidence.exposed_source),
            "canonical_non_worse": evidence.canonical_non_worse,
            "emitted": bool(excav),
            "admitted_clean": telemetry.lead_source_excavation_admitted_clean,
            "uncover_not_stolen": assess_receiver_uncover(synthetic, PARK1).qualified is False,
        },
    )
    if not evidence.qualified or not excav:
        print("STOP: synthetic pattern not admitted at CLEAN")
        return 1

    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 2

    print("\n== Gate Z node 78 ==", flush=True)
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
        return 3
    ev78 = assess_lead_source_excavation(node78.state, PATH78[0])
    succ78, tel78 = _clean_successors(node78.state, cards, g=node78.g)
    emitted = [
        item
        for item in succ78
        if item.actions == (PATH78[0],) and item.lead_source_excavation_followup is not None
    ]
    replay = node78.state.clone()
    replay_cost = replay_actions(replay, list(PATH78))
    replay_ok = ev78.qualified and ev78.exposed_source is not None
    _section(
        2,
        "node 78",
        {
            "id": node78.node_id,
            "g": node78.g,
            "qualified": ev78.qualified,
            "reject": None if ev78.reject is None else ev78.reject.value,
            "second_park": ev78.second_park,
            "consume": ev78.consume,
            "exposed": None if ev78.exposed_source is None else str(ev78.exposed_source),
            "canonical_non_worse": ev78.canonical_non_worse,
            "emitted_clean": bool(emitted),
            "followup": None if not emitted else emitted[0].lead_source_excavation_followup,
            "consume_edge": None if not emitted else emitted[0].lead_source_excavation_consume,
            "replay_cost": replay_cost,
            "replay_ok": replay_ok,
            "z_expansions": z_result.strategic_expansions,
            "z_excav_generated": z_result.telemetry.lead_source_excavation_generated,
            "z_excav_expanded": z_result.telemetry.lead_source_excavation_expanded,
            "z_uncover_generated": z_result.telemetry.receiver_uncover_generated,
        },
    )
    if not ev78.qualified or not emitted:
        print("STOP: node 78 valley not admitted at CLEAN")
        return 4

    print("\n== Gate AA ==")
    sys.stdout.flush()
    aa_config = _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000)
    aa_result = _run(opening, cards, aa_config)
    aa_replay = opening.clone()
    endpoint = aa_result.best_progress_node
    aa_cost = replay_actions(aa_replay, list(endpoint.actions))
    aa = {
        "stop": aa_result.stop_reason,
        "expansions": aa_result.strategic_expansions,
        "excav_generated": aa_result.telemetry.lead_source_excavation_generated,
        "excav_expanded": aa_result.telemetry.lead_source_excavation_expanded,
        "uncover_generated": aa_result.telemetry.receiver_uncover_generated,
        "replay_ok": states_structurally_equal(aa_replay, endpoint.state)
        and aa_cost == endpoint.g,
    }
    _section(3, "Gate AA", aa)
    z_replay = anchor.state.clone()
    z_end = z_result.best_progress_node
    z_cost = replay_actions(z_replay, list(z_end.actions))
    z_sum = {
        "stop": z_result.stop_reason,
        "expansions": z_result.strategic_expansions,
        "replay_ok": states_structurally_equal(z_replay, z_end.state) and z_cost == z_end.g,
        "envelope": "90s/25/300k unchanged",
    }
    _section(4, "Gate Z envelope", z_sum)
    if not aa["replay_ok"] or not z_sum["replay_ok"]:
        print("STOP: gate replay failed")
        return 5
    print("Done.")
    return 0


def _cards_from_state(state: SpiderState):
    from spider.cards import Card

    return [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]


if __name__ == "__main__":
    raise SystemExit(main())
