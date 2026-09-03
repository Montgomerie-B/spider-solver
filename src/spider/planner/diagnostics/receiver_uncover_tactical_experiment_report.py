#!/usr/bin/env python3
"""Natural-gate telemetry for the bounded receiver-uncover tactical experiment."""

from __future__ import annotations

import heapq
import pprint
import sys
import time
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

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
from spider.planner.receiver_uncover import assess_receiver_uncover
from spider.planner.whole_deal_scheduler import (
    EpochSaturationStatus,
    EpochTransitionRepresentativeStatus,
    PreDealOpportunityClass,
    SUITS,
    _stable_fragments,
    build_whole_deal_blueprint,
    lead_maturation_legal_step,
    rebuild_whole_deal_schedule,
)
import spider.planner.anytime_controller as controller
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key, states_structurally_equal


DEAL_PATH = ROOT / "deals" / "4925153.txt"
PARK = (8, 0, 1)
FOLLOW = (3, 8, 1)
CHILD = (7, 9, 1)
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
GENERATED: dict = {}


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


def _frag(state: SpiderState) -> int:
    return sum(len(_stable_fragments(state, suit)) for suit in SUITS)


def _lead_key(state: SpiderState):
    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    if schedule.lane_sequence_priority is None or schedule.lane_sequence_priority.lead is None:
        return None
    return schedule.lane_sequence_priority.lead.ordering_key()


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
        GENERATED.setdefault(parent.node_id, []).append(successor)
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
            sat = None
            must = None
            if node.whole_deal_schedule is not None and node.whole_deal_schedule.saturation is not None:
                sat = node.whole_deal_schedule.saturation.status.value
                must = node.whole_deal_schedule.saturation.must_count
            POPS.append(
                {
                    "id": node.node_id,
                    "parent": node.parent_id,
                    "kind": None if incoming is None else incoming.kind.value,
                    "uncover": bool(
                        incoming is not None and incoming.receiver_uncover_followup is not None
                    ),
                    "followup": None
                    if incoming is None
                    else incoming.receiver_uncover_followup,
                    "actions": None if incoming is None else incoming.actions,
                    "deal": _is_deal(node),
                    "g": node.g,
                    "stock": len(node.state.stock),
                    "epoch": 5 - len(node.state.stock) // 10,
                    "F": len(node.state.foundations),
                    "fd": _fd(node.state),
                    "auth": node.node_id in AUTHORISED,
                    "auth_ids": node.authorised_epoch_transition_ids,
                    "debt": controller._milestone_checkpoint_order(node)[0],
                    "sat": sat,
                    "must": must,
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
    GENERATED.clear()


def _run(start, cards, config):
    _reset()
    uninstall = _install()
    try:
        return solve_anytime(start, cards, None, config)
    finally:
        uninstall()


def _collect_known_ten(opening: SpiderState):
    queue = deque([(opening, 0, ())])
    seen = {canonical_state_key(opening)}
    found = []
    found_keys = set()
    expanded = 0
    while queue and len(found) < 10 and expanded < 20_000:
        state, g, actions = queue.popleft()
        expanded += 1
        if (
            len(state.stock) == 30
            and len(state.foundations) == 0
            and state.can_move(*CHILD)
        ):
            parked = state.clone()
            parked.move(*CHILD, rules=MW_RULES)
            evidence = assess_receiver_uncover(parked, PARK)
            if evidence.qualified and evidence.followup == FOLLOW:
                key = canonical_state_key(parked)
                if key not in found_keys:
                    found_keys.add(key)
                    found.append(
                        {
                            "g": g + 1,
                            "prefix": actions + (CHILD,),
                            "state": parked,
                            "evidence": evidence,
                        }
                    )
        if g >= 8:
            continue
        moves = []
        if state.can_deal(MW_RULES):
            moves.append(("deal",))
        moves.extend(
            action for action in state.enumerate_moves() if action != ("deal",)
        )
        for action in moves:
            nxt = state.clone()
            if action == ("deal",):
                nxt.deal(rules=MW_RULES)
                ng = g + 1
                extra = (("deal",),)
            else:
                cost = nxt.move(*action, rules=MW_RULES)
                ng = g + cost
                extra = (action,)
            if len(nxt.foundations) > 0 or len(nxt.stock) < 30:
                continue
            key = canonical_state_key(nxt)
            if key in seen:
                continue
            seen.add(key)
            queue.append((nxt, ng, actions + extra))
    return found, expanded


def _verify_known_state(item, cards, config):
    state = item["state"]
    telemetry = ControllerTelemetry()
    analysis = analyze_strategic_state(
        state,
        cards,
        spent_cost=item["g"],
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
        telemetry=telemetry,
    )
    node = StrategicSearchNode(
        0,
        state,
        item["g"],
        item["prefix"],
        None,
        None,
        0,
        StrategicCreditLevel.CLEAN,
        analysis,
    )
    successors = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    matched = [
        successor
        for successor in successors
        if successor.actions == (PARK,) and successor.receiver_uncover_followup == FOLLOW
    ]
    if not matched:
        return {
            "ok": False,
            "reason": "uncover missing at CLEAN",
            "actions": tuple(item.actions for item in successors),
        }
    edge = matched[0]
    replay = state.clone()
    try:
        cost = replay_actions(replay, list(edge.actions))
    except (ValueError, AssertionError, IndexError) as exc:
        return {"ok": False, "reason": f"park replay failed: {exc}"}
    if cost != edge.corrected_cost or not states_structurally_equal(replay, edge.end_state):
        return {"ok": False, "reason": "park replay mismatch"}
    post = state.clone()
    post.move(*PARK, rules=MW_RULES)
    schedule = rebuild_whole_deal_schedule(post, build_whole_deal_blueprint(post))
    step = lead_maturation_legal_step(schedule)
    if step is None or FOLLOW not in step[2].actions:
        return {
            "ok": False,
            "reason": "scheduler missed follow-up",
            "step": None if step is None else step[2].actions,
        }
    post_analysis = analyze_strategic_state(
        post,
        cards,
        spent_cost=item["g"] + edge.corrected_cost,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    post_node = StrategicSearchNode(
        1,
        post,
        item["g"] + edge.corrected_cost,
        item["prefix"] + (PARK,),
        None,
        edge,
        1,
        StrategicCreditLevel.CLEAN,
        post_analysis,
    )
    post_successors = generate_strategic_successors(
        post_node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=ControllerTelemetry(),
        actionability_cache={},
        started=time.perf_counter(),
    )
    if not any(FOLLOW in successor.actions for successor in post_successors):
        return {
            "ok": False,
            "reason": "follow-up not generated",
            "actions": tuple(item.actions for item in post_successors),
        }
    both = state.clone()
    both.move(*PARK, rules=MW_RULES)
    both.move(*FOLLOW, rules=MW_RULES)
    before_key = _lead_key(state)
    after_key = _lead_key(both)
    reduction = _frag(state) - _frag(both)
    if reduction < 1:
        return {"ok": False, "reason": "no fragment reduction", "reduction": reduction}
    if before_key is None or after_key is None or after_key > before_key:
        return {
            "ok": False,
            "reason": "canonical regression",
            "before": before_key,
            "after": after_key,
        }
    project = next(project for project in analysis.economic.projects if project.action == PARK)
    rework = project.rework_investment
    return {
        "ok": True,
        "generated": telemetry.receiver_uncover_generated,
        "admitted_clean": telemetry.receiver_uncover_admitted_clean,
        "tier": int(project.assessment.frontier_tier),
        "kind": project.kind.value,
        "exit_bounded": False if rework is None else rework.exit_route_bounded,
        "payoff": False if rework is None else rework.bounded_payoff,
        "reduction": reduction,
        "lifecycle": assess_tableau_move(state, PARK, discover_exit=False).placement_class.value,
    }


def _lineage_expansions(deal_id):
    expanded = []
    for row in POPS:
        if deal_id in _ancestors(row["id"]) and row["id"] != deal_id:
            expanded.append(row["id"])
    return expanded


def _summarize_gate(name, result, start):
    t = result.telemetry
    auth_pops = [row for row in POPS if row["deal"] and row["auth"]]
    deal_pops = [row for row in POPS if row["deal"]]
    lineages = []
    for deal in auth_pops:
        desc = _lineage_expansions(deal["id"])
        lineages.append(
            {
                "deal": deal["id"],
                "g": deal["g"],
                "stock": deal["stock"],
                "epoch": deal["epoch"],
                "descendant_expansions": len(desc),
            }
        )
    deepest = min(POPS, key=lambda row: (row["stock"], -row["g"])) if POPS else None
    best_f = max(POPS, key=lambda row: (row["F"], -row["fd"])) if POPS else None
    replay = start.clone()
    endpoint = result.best_progress_node
    replay_cost = replay_actions(replay, list(endpoint.actions))
    kinds = {}
    for row in POPS:
        kinds[row["kind"]] = kinds.get(row["kind"], 0) + 1
    followups_realised = 0
    for row in POPS:
        if not row["uncover"] or row["followup"] is None:
            continue
        for successor in GENERATED.get(row["id"], ()):
            if row["followup"] in successor.actions:
                followups_realised += 1
                break
    return {
        "stop": result.stop_reason,
        "expansions": result.strategic_expansions,
        "tactical": result.tactical_nodes,
        "runtime_s": round(result.elapsed_seconds, 3),
        "pops": len(POPS),
        "deal_pops": len(deal_pops),
        "authorised_deal_pops": tuple(row["id"] for row in auth_pops),
        "lineages_ge2": sum(item["descendant_expansions"] >= 1 for item in lineages),
        "lineages_ge3": sum(item["descendant_expansions"] >= 2 for item in lineages),
        "deepest": None
        if deepest is None
        else (deepest["id"], deepest["stock"], deepest["epoch"], deepest["g"], deepest["F"]),
        "best_F": None if best_f is None else (best_f["id"], best_f["F"], best_f["stock"], best_f["fd"]),
        "replay_ok": states_structurally_equal(replay, endpoint.state)
        and replay_cost == endpoint.g,
        "expansion_kinds": kinds,
        "uncover_expanded": sum(row["uncover"] for row in POPS),
        "receiver_uncover": {
            "considered": t.receiver_uncover_considered,
            "qualified": t.receiver_uncover_qualified,
            "rejected_join_broken": t.receiver_uncover_rejected_join_broken,
            "rejected_no_fragment": t.receiver_uncover_rejected_no_fragment,
            "rejected_canonical_worse": t.receiver_uncover_rejected_canonical_worse,
            "admitted_clean": t.receiver_uncover_admitted_clean,
            "generated": t.receiver_uncover_generated,
            "tt_admitted": t.receiver_uncover_tt_admitted,
            "expanded": t.receiver_uncover_expanded,
            "followup_generated": t.receiver_uncover_followup_generated,
            "followup_realised_on_expansion": followups_realised,
        },
        "lineages": lineages,
    }


def _z_safety(result, cards, config):
    t = result.telemetry
    prep_nodes = [row for row in POPS if row["sat"] == EpochSaturationStatus.PREPARATION_REQUIRED.value]
    issues = []
    join_ahead = 0
    uncover_before_join = 0
    speculative_uncover_fallback = 0
    must_starved = 0
    for row in POPS:
        node = NODE_OBJ.get(row["id"])
        if node is None or node.analysis is None:
            continue
        generated = GENERATED.get(row["id"], ())
        actions = [item.actions for item in generated]
        join_actions = []
        uncover_actions = []
        for successor in generated:
            if successor.receiver_uncover_followup is not None:
                uncover_actions.append(successor)
                continue
            if successor.category == "permanent_structure":
                join_actions.append(successor)
        if join_actions and uncover_actions:
            join_ahead += 1
            first_uncover = next(
                index
                for index, successor in enumerate(generated)
                if successor.receiver_uncover_followup is not None
            )
            first_join = next(
                (
                    index
                    for index, successor in enumerate(generated)
                    if successor.category == "permanent_structure"
                ),
                None,
            )
            if first_join is not None and first_uncover < first_join:
                uncover_before_join += 1
                issues.append(("uncover_before_join", row["id"]))
        if node.credit_level == StrategicCreditLevel.CLEAN:
            for successor in uncover_actions:
                project_id = successor.source_project_id
                projects = [
                    project
                    for project in node.analysis.economic.projects
                    if project.project_id == project_id
                ]
                if not projects:
                    continue
                rework = projects[0].rework_investment
                if rework is None or not rework.bounded_payoff:
                    speculative_uncover_fallback += 1
                    issues.append(("speculative_fallback", row["id"]))
        sat = None if node.whole_deal_schedule is None else node.whole_deal_schedule.saturation
        if (
            sat is not None
            and sat.status == EpochSaturationStatus.PREPARATION_REQUIRED
            and sat.must_count > 0
            and not any(
                successor.scheduler_pre_deal_classification
                == PreDealOpportunityClass.MUST_PRE_DEAL
                or (
                    successor.scheduled_objective is not None
                    and "PREPARE" in successor.scheduled_objective.family.value
                )
                or successor.category in {"permanent_structure", "run_construction", "dependency_closure"}
                for successor in generated
            )
            and uncover_actions
            and not join_actions
        ):
            must_starved += 1
            issues.append(("must_starved", row["id"]))
    prep_sample = None
    if prep_nodes:
        analog = max(prep_nodes, key=lambda row: (row["must"] or 0, -row["id"]))
        node = NODE_OBJ.get(analog["id"])
        generated = GENERATED.get(analog["id"], ())
        prep_sample = {
            "id": analog["id"],
            "g": analog["g"],
            "stock": analog["stock"],
            "must": analog["must"],
            "kinds": tuple(item.kind.value for item in generated),
            "categories": tuple(item.category for item in generated),
            "uncover": tuple(
                item.actions for item in generated if item.receiver_uncover_followup is not None
            ),
            "joins": tuple(
                item.actions for item in generated if item.category == "permanent_structure"
            ),
            "must_class": tuple(
                None
                if item.scheduler_pre_deal_classification is None
                else item.scheduler_pre_deal_classification.value
                for item in generated
            ),
        }
    unauth_credit = sum(
        1
        for row in POPS
        if row["deal"] and not row["auth"] and row["debt"] == 0
    )
    return {
        "replay_ok": True,
        "prep_required_pops": len(prep_nodes),
        "join_and_uncover_together": join_ahead,
        "uncover_before_join": uncover_before_join,
        "speculative_uncover_fallback": speculative_uncover_fallback,
        "must_starved": must_starved,
        "unauth_zero_debt_deals": unauth_credit,
        "prep_analog": prep_sample,
        "issues": issues,
        "generated_uncover": t.receiver_uncover_generated,
        "admitted_clean": t.receiver_uncover_admitted_clean,
    }


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("RECEIVER-UNCOVER TACTICAL EXPERIMENT")
    sys.stdout.flush()
    anchor = _node(solve_anytime(opening, cards, None, _opening_anchor_config()))
    if (anchor.g, len(anchor.state.foundations), len(anchor.state.stock)) != (21, 1, 30):
        print("STOP: cost-21 regression")
        return 1

    print("\n== Targeted known-ten ==")
    sys.stdout.flush()
    found, bfs_expanded = _collect_known_ten(opening)
    _section(1, "known-ten collection", {"found": len(found), "bfs_expanded": bfs_expanded})
    if len(found) < 10:
        print(f"STOP: known-ten collection {len(found)}/10")
        return 2
    config = _gate_envelope(_gate_aa_base_config, 180.0, 50, 500_000)
    verified = []
    for index, item in enumerate(found[:10], start=1):
        result = _verify_known_state(item, cards, config)
        verified.append(result)
        print(f" known {index}/10 ok={result.get('ok')} {result.get('reason', '')}", flush=True)
        if not result.get("ok"):
            _section("X", f"known {index} failure", result)
            print("STOP: known-ten verification failed")
            return 3
    passed = sum(1 for item in verified if item.get("ok"))
    _section(2, "known-ten verification", {"passed": f"{passed}/10", "details": verified})
    if passed < 10:
        print("STOP: known-ten < 10/10")
        return 3

    print("\n== Natural Gate AA ==")
    sys.stdout.flush()
    aa_result = _run(opening, cards, config)
    aa = _summarize_gate("AA", aa_result, opening)
    _section(3, "Gate AA", aa)
    uncover = aa["receiver_uncover"]
    natural_generated = uncover["generated"]
    natural_expanded = uncover["expanded"]
    follow_realised = uncover["followup_realised_on_expansion"]
    if natural_generated <= 0:
        aa_verdict = "INCONCLUSIVE NATURAL COVERAGE"
    elif follow_realised > 0:
        aa_verdict = "STRONG PASS"
    else:
        aa_verdict = "PRIMARY PASS"
    print(f" AA natural verdict: {aa_verdict}", flush=True)

    print("\n== Natural Gate Z safety ==")
    sys.stdout.flush()
    z_config = _gate_envelope(_gate_z_base_config, 90.0, 25, 300_000)
    z_result = _run(anchor.state, cards, z_config)
    z = _summarize_gate("Z", z_result, anchor.state)
    z_safety = _z_safety(z_result, cards, z_config)
    z_safety["replay_ok"] = z["replay_ok"]
    _section(4, "Gate Z", z)
    _section(5, "Gate Z safety", z_safety)
    z_fail = bool(
        not z["replay_ok"]
        or z_safety["uncover_before_join"]
        or z_safety["speculative_uncover_fallback"]
        or z_safety["must_starved"]
        or z_safety["unauth_zero_debt_deals"]
    )
    if z_fail:
        print("STOP: Z safety failed")
        return 4
    print(" Z safety PASS", flush=True)
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
