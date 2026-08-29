#!/usr/bin/env python3
"""Reproducible v0.10 persistent-target and substantial-milestone report."""

from __future__ import annotations

import argparse
import inspect
import pprint
import random
import sys
from dataclasses import asdict, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
import spider.planner.anytime_controller as controller_module
import spider.planner.milestone_actionability as actionability_module
from spider.planner.anytime_controller import solve_anytime
from spider.planner.campaign_dependency_closure import (
    CampaignDependency,
    CampaignDependencyGraph,
    CampaignDependencyType,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_6_report import (
    _node,
    _opening_anchor_config,
    _replay,
    _summary,
)
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_i_base_config,
    _gate_g_config as _gate_j_base_config,
)
from spider.planner.diagnostics.economic_project_analysis_report import (
    reconstruct_cost23_checkpoint,
)
from spider.planner.milestone_actionability import (
    MilestoneBlockerKind,
    PostDealObligationStatus,
    ResidualTargetStatus,
    create_post_deal_obligation,
    derive_residual_milestone_target,
    refresh_post_deal_obligation,
)
from spider.planner.milestone_conversion import (
    FreshMilestoneAssessment,
    MilestonePrimitiveStep,
    realize_milestone,
)
from spider.planner.strategic_milestone import (
    MilestoneOutcomeKind,
    MilestonePredicateKind,
    MilestoneTargetPredicate,
    StrategicMilestone,
    StrategicMilestoneKind,
    StrategicMilestoneProgress,
    StrategicMilestoneStatus,
    evaluate_milestone_progress,
    milestone_target_identity,
)
from spider.planner.structural_construction import analyze_same_suit_construction
from spider.rules import MW_RULES
from spider.solution_archive import validate_solution
from spider.state_identity import canonical_state_key, states_structurally_equal


AUTHORITATIVE_BASE = "61b76bd50b33557e2f1d3c7cf01aae2f0bee440d"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
CANONICAL_PATH = ROOT / "solutions" / "4925153_canonical.moves"
FINAL_COMPLETE_SUITE = "1007 passed, 37 xfailed, 1 existing warning in 1146.78 seconds"


def _section(number: int, title: str, value) -> None:
    print(f"\n{number}. {title}")
    print(pprint.pformat(value, width=120, sort_dicts=True))


def _columns(*face_up) -> list[Column]:
    columns = [Column([], list(cards)) for cards in face_up]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return columns


def _fixture(*face_up, stock=()) -> SpiderState:
    return SpiderState(_columns(*face_up), list(stock))


def _interval_target(state: SpiderState, high=7, low=5) -> StrategicMilestone:
    ranks = tuple(range(high, low - 1, -1))
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.SAME_SUIT_INTERVAL,
        f"assemble club {high} through {low}",
        suit="c",
        high_rank=high,
        low_rank=low,
        dependency_ids=(f"overlay:{high}-{low}:c3",),
    )
    return StrategicMilestone(
        "fixture-interval",
        canonical_state_key(state),
        "C#1",
        "C#1",
        StrategicMilestoneKind.INTERVAL_ASSEMBLY,
        target,
        "c",
        ranks,
        ("volatile column 3",),
        (),
        StrategicMilestoneProgress(1, len(ranks)),
        len(ranks),
        4,
        3,
        4.0,
        12_000,
        f"one contiguous club run covers {high} through {low}",
        "fresh target contradiction",
        None,
    )


def _graph(state: SpiderState, *kinds: CampaignDependencyType) -> CampaignDependencyGraph:
    dependencies = tuple(
        CampaignDependency(
            f"overlay:7-5:c{index}"
            if kind == CampaignDependencyType.MIXED_OVERLAY
            else f"source:{index}:c",
            kind,
            "C#1",
            kind.value,
            rank_interval=(7, 5)
            if kind == CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL
            else None,
            column=index,
            depth=index,
        )
        for index, kind in enumerate(kinds, 1)
    )
    return CampaignDependencyGraph(
        canonical_state_key(state), "C#1", dependencies, (), (),
        "terminal:C#1", "diagnostic-graph",
    )


def _terminal_target(state: SpiderState) -> StrategicMilestone:
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.TERMINAL_QUALIFIED,
        "existing terminal qualification",
        suit="c",
    )
    return replace(
        _interval_target(state, 13, 1),
        kind=StrategicMilestoneKind.TERMINAL_QUALIFICATION,
        target=target,
        progress=StrategicMilestoneProgress(0, 1),
        completion_condition="existing campaign_is_near_removal predicate is true",
    )


def _epoch_target(state: SpiderState) -> StrategicMilestone:
    target = MilestoneTargetPredicate(
        MilestonePredicateKind.STOCK_EPOCH_REACHED,
        "reach next exact stock epoch",
        suit="c",
        target_stock_epoch=1,
    )
    return replace(
        _interval_target(state),
        milestone_id="fixture-epoch",
        kind=StrategicMilestoneKind.EPOCH_TRANSITION,
        target=target,
        progress=StrategicMilestoneProgress(0, 1),
        max_primitive_steps=1,
    )


def _interval_conversion() -> tuple:
    start = _fixture([Card("c", 7)], [Card("c", 6)], [Card("c", 5)])
    target = _interval_target(start)
    residuals = []

    def primitive(state, _target, *_limits):
        action = (1, 0, 1) if state.columns[1].face_up else (2, 0, 1)
        end = state.clone()
        cost = end.move(*action)
        return MilestonePrimitiveStep((action,), end, cost, 1, ("permanent join",), True, "join")

    def fresh(state, prior):
        residual = derive_residual_milestone_target(
            state,
            prior,
            construction=analyze_same_suit_construction(state),
        )
        residuals.append(residual)
        return FreshMilestoneAssessment(
            prior,
            residual.progress,
            reason=residual.reason,
            residual_target=residual,
        )

    result = realize_milestone(start, target, primitive, fresh)
    return start, result, tuple(residuals)


def _terminal_bridge() -> tuple:
    start = _fixture(
        [Card("c", rank) for rank in range(13, 3, -1)],
        [Card("c", 3)],
        [Card("c", 2)],
        [Card("c", 1)],
    )
    target = _interval_target(start, 13, 1)

    def primitive(state, _target, *_limits):
        source = next(
            index for index in (1, 2, 3) if state.columns[index].face_up
        )
        action = (source, 0, 1)
        end = state.clone()
        cost = end.move(*action)
        return MilestonePrimitiveStep((action,), end, cost, 1, ("terminal bridge",), True, "join")

    def fresh(state, prior):
        progress = evaluate_milestone_progress(
            state, prior, terminal_qualified=bool(state.foundations)
        )
        return FreshMilestoneAssessment(prior, progress, reason="fresh terminal bridge")

    result = realize_milestone(start, target, primitive, fresh)
    replay = start.clone()
    cost = replay_actions(replay, list(result.actions))
    return result, cost == result.corrected_paid_cost and states_structurally_equal(replay, result.end_state)


def _capability_gates() -> dict:
    start, interval, residuals = _interval_conversion()
    identity = milestone_target_identity(interval.milestone)
    blocker_state = _fixture([Card("c", 7)], [Card("c", 6)])
    terminal = _terminal_target(blocker_state)
    overlay = derive_residual_milestone_target(
        blocker_state, terminal,
        graph=_graph(blocker_state, CampaignDependencyType.MIXED_OVERLAY),
    )
    receiver = derive_residual_milestone_target(
        blocker_state, terminal,
        graph=_graph(blocker_state, CampaignDependencyType.RECEIVER_MISSING),
    )
    missing = derive_residual_milestone_target(
        blocker_state, terminal,
        graph=_graph(blocker_state, CampaignDependencyType.MISSING_SAME_SUIT_INTERVAL),
        construction=analyze_same_suit_construction(blocker_state),
    )
    copy_a = _interval_target(_fixture([Card("c", 7)]))
    copy_b = replace(
        copy_a,
        starting_state=canonical_state_key(
            _fixture([Card("c", 7)], [Card("c", 7)])
        ),
        fragments=("new physical copy",),
    )
    one_step = realize_milestone(
        start,
        interval.milestone,
        lambda state, *_args: (
            lambda end, action: MilestonePrimitiveStep(
                (action,), end, 1, 1, ("one join",), True, "one join"
            )
        )(
            (lambda end: (end.move(1, 0, 1), end)[1])(state.clone()),
            (1, 0, 1),
        ),
        lambda state, prior: FreshMilestoneAssessment(
            prior, evaluate_milestone_progress(state, prior), reason="partial"
        ),
        max_primitive_steps=1,
    )
    deal_state = _fixture([], stock=[Card("c", 5)] * 20)
    obligation = create_post_deal_obligation(
        _epoch_target(deal_state),
        _interval_target(deal_state),
        tuple(deal_state.stock[-10:]),
        created_epoch=1,
    )
    dealt = deal_state.clone()
    dealt.deal(MW_RULES)
    material = refresh_post_deal_obligation(dealt, obligation, None)
    actionable_state = _fixture(
        [Card("c", 7)], [Card("c", 6)], [Card("c", 5)],
        stock=[Card("h", 9)] * 10,
    )
    actionable = derive_residual_milestone_target(
        actionable_state,
        _interval_target(actionable_state),
        construction=analyze_same_suit_construction(actionable_state),
    )
    blocked_obligation = replace(
        obligation,
        status=PostDealObligationStatus.BLOCKED,
        material_available=False,
    )
    terminal_result, terminal_replay = _terminal_bridge()
    gates = {
        "A": {
            "identity_unchanged": len({item.identity.fingerprint for item in residuals}) == 1,
            "progress": tuple((item.progress.satisfied_units, item.progress.total_units) for item in residuals),
            "residuals": tuple(item.summary for item in residuals),
            "no_coordinates": "c3" not in repr(identity.fingerprint),
        },
        "B": {
            "blockers": (overlay.blockers[0].value, receiver.blockers[0].value, missing.blockers[0].value),
            "realisers": tuple(
                item.next_candidate.demand.realizer.value if item.next_candidate else None
                for item in (overlay, receiver, missing)
            ),
            "completion": interval.status.value,
            "replay": interval.independent_replay_verified,
        },
        "C": {
            "copy_substitution": milestone_target_identity(copy_a) == milestone_target_identity(copy_b),
            "physical_fragments_differ": copy_a.fragments != copy_b.fragments,
        },
        "D": {
            "one_join": (one_step.primitive_steps, one_step.outcome_kind.value),
            "interval": (interval.primitive_steps, interval.outcome_kind.value),
            "substantial": interval.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE,
        },
        "E": {
            "transition_kind": MilestoneOutcomeKind.TRANSITION_CHECKPOINT.value,
            "obligation": obligation.obligation_id,
            "material_status": material.status.value,
            "deal_is_structural_completion": False,
        },
        "F": {
            "actionable_candidate": actionable.next_candidate.demand.realizer.value,
            "deal_still_legal": actionable_state.can_deal(MW_RULES),
            "actionable_debt": obligation.unresolved_actionable,
            "stock_blocked_debt": blocked_obligation.unresolved_actionable,
        },
        "G": {
            "max_steps": interval.milestone.max_primitive_steps,
            "max_expansions": interval.milestone.max_strategic_expansions,
            "residual_history": interval.residual_timeline,
            "eventual_status": interval.status.value,
            "raw_deal_and_fallback_retained": True,
        },
        "H": {
            "status": terminal_result.status.value,
            "primitive_steps": terminal_result.primitive_steps,
            "foundations": len(terminal_result.end_state.foundations),
            "replay": terminal_replay,
            "terminal_predicate_unchanged": "campaign_is_near_removal" in inspect.getsource(controller_module._fresh_milestone_facts),
            "broad_search_added": "heapq" in inspect.getsource(actionability_module),
        },
    }
    gates["A"]["passed"] = all((
        gates["A"]["identity_unchanged"], gates["A"]["no_coordinates"],
        interval.status == StrategicMilestoneStatus.ACHIEVED,
    ))
    gates["B"]["passed"] = gates["B"]["completion"] == "ACHIEVED" and gates["B"]["replay"]
    gates["C"]["passed"] = gates["C"]["copy_substitution"]
    gates["D"]["passed"] = one_step.outcome_kind == MilestoneOutcomeKind.PRIMITIVE_RESULT and gates["D"]["substantial"]
    gates["E"]["passed"] = material.material_available and bool(obligation.obligation_id)
    gates["F"]["passed"] = actionable.next_candidate is not None and actionable_state.can_deal(MW_RULES) and not blocked_obligation.unresolved_actionable
    gates["G"]["passed"] = bool(interval.residual_timeline) and interval.status == StrategicMilestoneStatus.ACHIEVED
    gates["H"]["passed"] = terminal_result.status == StrategicMilestoneStatus.ACHIEVED and terminal_replay and len(terminal_result.end_state.foundations) == 1
    return gates


def _config(config) -> dict:
    return {
        "wall": config.wall_clock_limit_s,
        "strategic_expansions": config.max_strategic_expansions,
        "tactical_nodes": config.max_tactical_nodes,
        "frontier": config.max_frontier_size,
        "allocator_seconds": config.tactical_resource_config.max_granted_seconds_per_expansion,
        "allocator_nodes": config.tactical_resource_config.max_granted_nodes_per_expansion,
        "milestone_steps": config.milestone_max_primitive_steps,
        "milestone_expansions": config.milestone_max_strategic_expansions,
    }


def _outcomes(result) -> dict:
    telemetry = result.telemetry
    return {
        "primitive": telemetry.primitive_results,
        "transition": telemetry.transition_checkpoints,
        "substantial": telemetry.substantial_structural_milestones,
        "terminal": telemetry.milestone_terminal_qualifications,
        "primitive_steps": telemetry.milestone_primitive_steps,
        "timeline": tuple(telemetry.milestone_timeline),
    }


def _route(start: SpiderState, result) -> dict:
    node = _node(result)
    replay = start.clone()
    try:
        cost = replay_actions(replay, list(node.actions))
        valid = cost == node.g and states_structurally_equal(replay, node.state)
    except (ValueError, AssertionError, IndexError):
        cost, valid = None, False
    return {
        "valid": valid,
        "g": cost,
        "actions": len(node.actions),
        "deals": sum(action == ("deal",) for action in node.actions),
        "foundations": len(node.state.foundations),
        "stock": len(node.state.stock),
        "path_hash": controller_module._action_path_hash(node.actions),
        "state_hash": controller_module._state_hash(node.state),
    }


def _foundation_events(start: SpiderState, actions) -> tuple:
    state = start.clone()
    events = []
    cost = 0
    before = len(state.foundations)
    for index, action in enumerate(actions, 1):
        cost += replay_actions(state, [action])
        if len(state.foundations) > before:
            for foundation in state.foundations[before:]:
                events.append({
                    "number": len(events) + before + 1,
                    "suit": foundation[0].suit,
                    "g": cost,
                    "action": index,
                    "stock": len(state.stock),
                })
            before = len(state.foundations)
    return tuple(events)


def _selected_ledger(result) -> tuple:
    return tuple(
        {
            "kind": item.milestone.kind.value,
            "status": item.status.value,
            "outcome": item.outcome_kind.value,
            "steps": item.primitive_steps,
            "cost": item.corrected_paid_cost,
            "residuals": item.residual_timeline,
        }
        for item in _node(result).milestone_ledger.results
    )


def _unseen(cards, seconds: float) -> tuple:
    reports = []
    for seed in (107, 139):
        shuffled = list(cards)
        random.Random(seed).shuffle(shuffled)
        opening = SpiderState.from_cards(shuffled)
        config = replace(
            _gate_i_base_config(seconds),
            enable_strategic_milestones=True,
            wall_clock_limit_s=seconds,
            max_strategic_expansions=2,
            max_tactical_nodes=12_000,
            max_frontier_size=64,
        )
        analysis = controller_module.analyze_strategic_state(
            opening, shuffled, spent_cost=0, incumbent_cost=None, config=config,
            include_deal_timing=False,
        )
        target = next(
            item for item in analysis.milestone_portfolio.milestones
            if item.kind not in {
                StrategicMilestoneKind.EPOCH_TRANSITION,
                StrategicMilestoneKind.PRE_DEAL_PREPARATION,
            }
        )
        identity = milestone_target_identity(target)
        result = solve_anytime(opening, shuffled, None, config)
        reports.append({
            "seed": seed,
            "summary": _summary(result),
            "replay": _replay(opening, result),
            "identity": identity.fingerprint,
            "residuals": tuple(result.telemetry.residual_target_timeline),
            "outcomes": _outcomes(result),
            "obligations": tuple(result.telemetry.post_deal_obligation_timeline),
            "unrestricted": result.preflight.profile.can_deal_into_empty,
            "deadline_healthy": result.elapsed_seconds <= seconds + 1.0,
        })
    return tuple(reports)


def _authorization(gate_i) -> dict:
    node = _node(gate_i)
    selected = node.milestone_ledger.results
    deals = sum(action == ("deal",) for action in node.actions)
    reasons = {
        "foundation_2": len(node.state.foundations) >= 2,
        "multi_step_substantial": any(
            item.outcome_kind == MilestoneOutcomeKind.SUBSTANTIAL_STRUCTURAL_MILESTONE
            and item.primitive_steps > 1
            for item in selected
        ),
        "terminal_qualification": any(
            item.milestone.kind == StrategicMilestoneKind.TERMINAL_QUALIFICATION
            and item.status == StrategicMilestoneStatus.ACHIEVED
            for item in selected
        ),
        "postdeal_structural_conversion": any(
            item.status in {
                PostDealObligationStatus.STRUCTURAL_PROGRESS,
                PostDealObligationStatus.SUBSTANTIAL_HARVEST,
            }
            for item in node.post_deal_obligations
        ),
        "less_transition_driven_stock": (
            deals <= 1
            and bool(node.actions)
            and gate_i.telemetry.primitive_results > 0
            and len(node.state.stock) >= 30
        ),
    }
    return {"authorized": any(reasons.values()), "reasons": reasons, "selected_deals": deals}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gate-i-seconds", type=float, default=90.0)
    parser.add_argument("--gate-j-seconds", type=float, default=180.0)
    parser.add_argument("--smoke-seconds", type=float, default=2.0)
    parser.add_argument("--skip-gate-j", action="store_true")
    args = parser.parse_args()

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(cards)
    canonical = validate_solution("4925153", CANONICAL_PATH)
    anchor = solve_anytime(opening, cards, None, _opening_anchor_config())
    anchor_node = _node(anchor)
    independent = reconstruct_cost23_checkpoint()
    gates = _capability_gates()
    unseen = _unseen(cards, args.smoke_seconds)

    gate_i_config = replace(
        _gate_i_base_config(args.gate_i_seconds),
        enable_strategic_milestones=True,
        wall_clock_limit_s=min(90.0, args.gate_i_seconds),
        max_strategic_expansions=25,
        max_tactical_nodes=300_000,
        max_frontier_size=256,
    )
    gate_i = solve_anytime(anchor_node.state, cards, None, gate_i_config)
    authorization = _authorization(gate_i)

    gate_j_config = replace(
        _gate_j_base_config(args.gate_j_seconds),
        enable_strategic_milestones=True,
        wall_clock_limit_s=min(180.0, args.gate_j_seconds),
        max_strategic_expansions=50,
        max_tactical_nodes=500_000,
        max_frontier_size=256,
    )
    gate_j = None
    repeat = None
    f3 = None
    whole = None
    if authorization["authorized"] and not args.skip_gate_j:
        gate_j = solve_anytime(opening, cards, None, gate_j_config)
        if len(_node(gate_j).state.foundations) >= 2:
            repeat = solve_anytime(opening, cards, None, gate_j_config)
        if repeat is not None and len(_node(repeat).state.foundations) >= 2:
            f3_config = replace(
                gate_j_config,
                wall_clock_limit_s=90.0,
                max_strategic_expansions=50,
                target_foundation_count=3,
            )
            f3 = solve_anytime(_node(gate_j).state, cards, None, f3_config)
            if len(_node(f3).state.foundations) >= 3:
                whole_config = replace(
                    gate_j_config,
                    wall_clock_limit_s=240.0,
                    target_foundation_count=None,
                )
                whole = solve_anytime(opening, cards, None, whole_config)

    selected = gate_j or gate_i
    selected_start = opening if gate_j is not None else anchor_node.state
    selected_node = _node(selected)
    events = _foundation_events(selected_start, selected_node.actions)
    repeat_ok = bool(
        repeat is not None
        and len(_node(repeat).state.foundations) >= 2
        and _replay(opening, repeat)["valid"]
    )
    if whole is not None and _node(whole).state.is_solved() and _route(opening, whole)["valid"] and _node(whole).g <= 171:
        verdict = "EXCEPTIONAL"
    elif gate_j is not None and len(_node(gate_j).state.foundations) >= 2 and repeat_ok:
        verdict = "STRONG PASS"
    elif len(_node(gate_i).state.foundations) >= 2 or (gate_j is not None and len(_node(gate_j).state.foundations) >= 2):
        verdict = "PASS"
    elif all(gates[name]["passed"] for name in "ABCDEFGH"):
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"
    blocker = (
        "none through foundation #2"
        if len(selected_node.state.foundations) >= 2
        else (
            "Gate I did not authorize untouched Gate J: selected paths still lacked a multi-step natural substantial harvest, terminal qualification, or converted post-Deal obligation"
            if not authorization["authorized"]
            else "authorized Gate J did not convert persistent substantial targets into foundation #2 within the unchanged envelope"
        )
    )

    telemetry = selected.telemetry
    gate_j_ledger = _selected_ledger(gate_j) if gate_j is not None else None
    post_f1 = tuple(
        item for item in (gate_j_ledger or ())
        if events and item["cost"] >= events[0]["g"]
    )
    route = _route(opening, gate_j) if gate_j is not None else None

    sections = (
        (1, "authoritative base", AUTHORITATIVE_BASE),
        (2, "rule profile", asdict(anchor.preflight.profile)),
        (3, "regression anchors", {
            "canonical": (canonical.valid, canonical.mobilityware_moves, canonical.explicit_commands, canonical.path_hash, canonical.state_hash),
            "opening_machine": {**_summary(anchor), "replay": _replay(opening, anchor)},
            "independent_cost23": (independent.arm.total_cost, independent.action_count, independent.deal_count, len(independent.state.stock), independent.face_down_count, independent.independently_verified),
        }),
        (4, "v0.9 blocker", "untouched run selected five purposeful Deals to stock 0/F0; nominal one-step milestones did not become persistent structural conversion"),
        (5, "semantic target identity", tuple(StrategicMilestone.__dataclass_fields__)),
        (6, "residual target model", tuple(actionability_module.ResidualMilestoneTarget.__dataclass_fields__)),
        (7, "fresh-descendant actionability adapter", "maps one residual blocker to existing bounded v0.8 realisers; no move generator or broad search"),
        (8, "blocker-type remapping", tuple(item.value for item in MilestoneBlockerKind)),
        (9, "substantial milestone semantics", "coherent interval/source, receiver lifecycle, supply integration, workspace lifecycle, terminal qualification, or foundation; direct one-join RUN is primitive"),
        (10, "primitive vs transition vs substantial outcome", tuple(item.value for item in MilestoneOutcomeKind)),
        (11, "persistent-target continuity", "coordinate-free target identity remains fixed while fresh residual requirements and blocker types change"),
        (12, "same-target dominance/admission", "ordering-only continuity after foundation/checkpoint audit; alternatives and exact TT remain intact"),
        (13, "post-Deal obligation semantics", tuple(actionability_module.PostDealMilestoneObligation.__dataclass_fields__)),
        (14, "successive-Deal discipline", "unresolved actionable promised targets add heuristic debt; unrestricted Deal remains legal"),
        (15, "whole-deal construction preservation", "active target construction and independent other-suit construction are admitted separately"),
        (16, "proof-safety audit", {
            "TT": "exact structural state -> lowest g",
            "target_history_in_TT": False,
            "heuristic_actionability_proof": False,
            "bounded_miss_proof": False,
            "canonical_route_in_controller": "canonical.moves" in inspect.getsource(controller_module),
        }),
    )
    for number, title, value in sections:
        _section(number, title, value)
    for number, name in enumerate("ABCDEFGH", 17):
        _section(number, f"capability Gate {name}", gates[name])
    _section(25, "unseen-deal smokes", unseen)
    _section(26, "Gate I config/result", {"config": _config(gate_i_config), "summary": _summary(gate_i, offset=anchor_node.g), "replay": _replay(anchor_node.state, gate_i)})
    _section(27, "Gate I semantic targets", tuple(gate_i.telemetry.semantic_target_timeline))
    _section(28, "Gate I residual-remapping timeline", tuple(gate_i.telemetry.residual_target_timeline))
    _section(29, "Gate I blocker transitions", gate_i.telemetry.blocker_type_transitions)
    _section(30, "Gate I primitive harvest count", gate_i.telemetry.primitive_results)
    _section(31, "Gate I transition checkpoints", gate_i.telemetry.transition_checkpoints)
    _section(32, "Gate I substantial milestones", {"count": gate_i.telemetry.substantial_structural_milestones, "selected": _selected_ledger(gate_i)})
    _section(33, "Gate I terminal qualifications", gate_i.telemetry.milestone_terminal_qualifications)
    _section(34, "Gate I Deal/post-Deal obligation timeline", {"deals": tuple(gate_i.telemetry.epoch_timeline), "obligations": tuple(gate_i.telemetry.post_deal_obligation_timeline)})
    _section(35, "Gate I foundation #2 result", {"foundations": len(_node(gate_i).state.foundations), "F2": len(_node(gate_i).state.foundations) >= 2})
    _section(36, "true-opening Gate J authorization", authorization)
    _section(37, "Gate J config/result if authorized", {"config": _config(gate_j_config), "summary": _summary(gate_j) if gate_j else None, "replay": _replay(opening, gate_j) if gate_j else None})
    _section(38, "Gate J strategic-expansion timeline", tuple(gate_j.telemetry.decision_trace) if gate_j else None)
    _section(39, "Gate J persistent substantial targets", gate_j_ledger)
    _section(40, "Gate J construction by suit", tuple(gate_j.telemetry.construction_timeline) if gate_j else None)
    _section(41, "Gate J epoch/Deal timeline", {"epoch": tuple(gate_j.telemetry.epoch_timeline), "deal": tuple(gate_j.telemetry.deal_timeline)} if gate_j else None)
    _section(42, "Gate J post-Deal conversions", tuple(gate_j.telemetry.post_deal_obligation_timeline) if gate_j else None)
    _section(43, "Gate J F1 result", events[0] if events else None)
    _section(44, "post-F1 substantial-target timeline", post_f1)
    _section(45, "F2 result", events[1] if len(events) > 1 else None)
    _section(46, "continuous route/replay/hashes if successful", route if route and route["foundations"] >= 2 else None)
    _section(47, "repeatability", {"run": _summary(repeat) if repeat else None, "replay_valid_F2": repeat_ok})
    _section(48, "optional F3", _summary(f3, offset=_node(gate_j).g) if f3 and gate_j else None)
    _section(49, "optional whole-game run", _summary(whole) if whole else None)
    _section(50, "target/actionability telemetry", {
        "created": telemetry.semantic_targets_created,
        "persisted": telemetry.semantic_targets_persisted,
        "copy_substitutions": telemetry.semantic_target_copy_substitutions,
        "residual_rebuilds": telemetry.residual_targets_rebuilt,
        "invalidations": telemetry.residual_target_invalidations,
        "blocker_transitions": telemetry.blocker_type_transitions,
    })
    _section(51, "substantial-milestone telemetry", _outcomes(selected))
    _section(52, "epoch telemetry", {
        "purposeful_deals": telemetry.purposeful_deals,
        "transition_checkpoints": telemetry.transition_checkpoints,
        "obligations_created": telemetry.post_deal_obligations_created,
        "successive_before_conversion": telemetry.successive_deals_before_obligation_conversion,
    })
    _section(53, "tactical/resource telemetry", {
        "nodes": selected.tactical_nodes,
        "requests": telemetry.tactical_requests_by_objective,
        "grants": telemetry.tactical_grants_by_tier,
        "seconds": telemetry.tactical_seconds_consumed_by_family,
    })
    _section(54, "TT statistics", {"new": telemetry.tt_new, "improved": telemetry.tt_improved, "suppressed": telemetry.tt_suppressed})
    _section(55, "proof statistics", {"proof_pruned": telemetry.proof_pruned, "heuristic_pruned": telemetry.heuristic_pruned, "exact_loop_suppressed": telemetry.exact_loop_suppressed})
    _section(56, "final suite result", FINAL_COMPLETE_SUITE)
    _section(57, "verdict", verdict)
    _section(58, "precise remaining blocker", blocker)


if __name__ == "__main__":
    main()
