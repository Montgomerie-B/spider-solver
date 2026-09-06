#!/usr/bin/env python3
"""Three-arm one-shot natural empty-state service experiment."""

from __future__ import annotations

import hashlib
import heapq
import inspect
import json
import random
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import one_shot_natural_r3_service_v0_1 as r3
import spider.planner.anytime_controller as controller
import state_local_credit_semantics_v0_1 as state_local
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
    StrategicSearchNode,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


BASE_SHA = "5cda8eaeb6f230113be56d82c8ac0797c85d251a"
RESULT_PATH = ROOT / "docs" / "research" / "one_shot_natural_empty_service_v0_1.json"


def actual_empty_columns(state: SpiderState) -> tuple[int, ...]:
    """Structural engine empties; no digest, path, card, or benchmark facts."""

    return tuple(index for index, column in enumerate(state.columns) if column.is_empty())


def eligible_empty_frontier_items(frontier, origin_by_id) -> list[tuple]:
    """Return live ordinary TT-admitted successors with an actual empty."""

    return [
        item
        for item in frontier
        if common.Observer._is_frontier_item(item)
        and origin_by_id.get(item[2].node_id) == "SUCCESSOR"
        and actual_empty_columns(item[2].state)
    ]


def choose_empty_candidate(frontier, origin_by_id):
    """Select solely by the already stored ordinary queue priority and node id."""

    candidates = eligible_empty_frontier_items(frontier, origin_by_id)
    if not candidates:
        return None, ()
    ordered = sorted(candidates, key=lambda item: (item[0], item[2].node_id))
    return ordered[0], tuple(ordered)


class OneShotEmptyService:
    """Extract one exact existing empty node, then permanently become inert."""

    def __init__(self, *, enabled: bool, origin_by_id) -> None:
        self.enabled = enabled
        self.origin_by_id = origin_by_id
        self.spent = False
        self.services = 0
        self.selected_item = None
        self.candidates = ()
        self.frontier_size_before = None
        self.frontier_size_after = None

    def pop(self, frontier, *, ordinary_pop, ordinary_heapify):
        if not self.enabled or self.spent:
            return ordinary_pop(frontier), False
        selected, candidates = choose_empty_candidate(frontier, self.origin_by_id)
        if selected is None:
            return ordinary_pop(frontier), False
        self.selected_item = selected
        self.candidates = candidates
        self.frontier_size_before = len(frontier)
        index = next(index for index, item in enumerate(frontier) if item is selected)
        popped = frontier[index]
        last = frontier.pop()
        if index < len(frontier):
            frontier[index] = last
            ordinary_heapify(frontier)
        self.frontier_size_after = len(frontier)
        self.spent = True
        self.services += 1
        return popped, True


def _empty_transition(state: SpiderState, actions) -> dict:
    replay = state.clone()
    trace = []
    consumed = False
    restored = False
    used_as_destination = False
    for action in actions:
        before = actual_empty_columns(replay)
        if action == ("deal",):
            cost = replay.deal(MW_RULES)
        else:
            src, dst, count = action
            used_as_destination = used_as_destination or replay.columns[dst].is_empty()
            cost = replay.move(src, dst, count, rules=MW_RULES)
        after = actual_empty_columns(replay)
        consumed = consumed or len(after) < len(before)
        restored = restored or len(after) > len(before)
        trace.append(
            {
                "action": common.action_json(action),
                "cost": int(cost),
                "empty_before": list(before),
                "empty_after": list(after),
            }
        )
    return {
        "empty_trace": trace,
        "empty_consumed": consumed,
        "empty_restored": restored,
        "uses_empty_as_destination": used_as_destination,
        "final_empty_columns": list(actual_empty_columns(replay)),
        "replay_state": replay,
    }


def _positive_existing_delta(successor) -> tuple[bool, list[str]]:
    evidence = []
    delta = successor.progress_delta
    if delta is not None:
        fields = (
            "foundation_delta",
            "critical_dependencies_removed",
            "actionable_high_value_delta",
            "campaign_must_burden_reduction",
            "same_suit_mass_delta",
            "stable_join_delta",
            "mixed_boundary_reduction",
            "rehandling_debt_reduction",
            "exact_receiver_successes",
        )
        for name in fields:
            value = getattr(delta, name, 0)
            if value > 0:
                evidence.append(f"progress_delta.{name}={value}")
    closure = successor.dependency_closure_result
    if closure is not None:
        if closure.dependencies_closed:
            evidence.append(f"dependencies_closed={len(closure.dependencies_closed)}")
        if closure.overlays_cleared:
            evidence.append(f"overlays_cleared={len(closure.overlays_cleared)}")
    investment = successor.structural_investment
    if investment is not None and investment.evidence.campaign_specific_value:
        evidence.append("structural_investment.campaign_specific_value")
    milestone = successor.milestone_result
    if milestone is not None and milestone.status.value == "ACHIEVED":
        evidence.append(f"milestone_achieved={milestone.milestone.kind.value}")
    maturation = successor.maturation_progress_delta
    if maturation is not None and maturation.substantial:
        evidence.append("substantial_lane_maturation")
    if successor.receiver_uncover_followup is not None:
        evidence.append("receiver_uncover_followup")
    return bool(evidence), evidence


def workspace_successor_record(
    successor,
    index: int,
    parent_state: SpiderState,
) -> dict:
    base = r3._successor_record(successor, index, parent_state)
    transition = _empty_transition(parent_state, successor.actions)
    before = controller.analyze_stage0_state(
        parent_state, spent_cost=0, incumbent_cost=None
    )
    after = controller.analyze_stage0_state(
        successor.end_state, spent_cost=successor.corrected_cost, incumbent_cost=None
    )
    explicit, explicit_evidence = _positive_existing_delta(successor)
    evidence = []
    deltas = {
        "face_down_reduction": before.face_down_count - after.face_down_count,
        "foundation_delta": after.foundation_count - before.foundation_count,
        "stable_same_suit_join_delta": (
            after.stable_same_suit_joins - before.stable_same_suit_joins
        ),
        "same_suit_run_mass_delta": after.same_suit_run_mass - before.same_suit_run_mass,
        "longest_same_suit_run_delta": (
            after.longest_same_suit_run - before.longest_same_suit_run
        ),
        "mixed_boundary_reduction": (
            before.mixed_suit_boundaries - after.mixed_suit_boundaries
        ),
        "rehandling_debt_reduction": before.rehandling_debt - after.rehandling_debt,
        "legal_mobility_delta": after.legal_move_count - before.legal_move_count,
    }
    for name, value in deltas.items():
        if value > 0:
            evidence.append(f"stage0.{name}={value}")
    evidence.extend(explicit_evidence)
    measurable_progress = bool(evidence) or explicit
    uses_workspace = transition["uses_empty_as_destination"] or transition["empty_consumed"]
    final_empties = len(transition["final_empty_columns"])
    if measurable_progress and uses_workspace:
        classification = "PRODUCTIVE_EMPTY_USE"
    elif measurable_progress and final_empties > 0:
        classification = "EMPTY_PRESERVED_PROGRESS"
    elif transition["empty_consumed"]:
        classification = "EMPTY_CONSUMED_NO_MEASURED_PROGRESS"
    else:
        classification = "EMPTY_UNUSED"
    operator_functions = []
    if transition["uses_empty_as_destination"]:
        operator_functions.append("invest workspace")
    if successor.kind.value in {
        "LEAD_SOURCE_EXCAVATION",
        "FACE_DOWN_LEAD_EDGE_EXCAVATION",
    } or deltas["face_down_reduction"] > 0:
        operator_functions.append("source excavation")
    if successor.receiver_uncover_followup is not None:
        operator_functions.append("receiver creation/use")
    if transition["empty_consumed"] and transition["empty_restored"]:
        operator_functions.extend(("temporary rework", "workspace recovery"))
    if successor.dependency_closure_result is not None or successor.category in {
        "campaign",
        "campaign_corridor",
        "dependency_closure",
        "residual_conversion",
    }:
        operator_functions.append("campaign-edge realisation")
    replay_state = transition.pop("replay_state")
    return {
        **base,
        "empty_count_before": len(before.empty_columns),
        "empty_count_after": len(after.empty_columns),
        **transition,
        **deltas,
        "measurable_progress": measurable_progress,
        "progress_evidence": evidence,
        "workspace_classification": classification,
        "resource_operator_analogue": list(dict.fromkeys(operator_functions)),
        "campaign_dependency_effect": {
            "progress_delta": None if successor.progress_delta is None else repr(successor.progress_delta),
            "dependency_closure": None if successor.dependency_closure_result is None else repr(successor.dependency_closure_result),
            "structural_investment": None if successor.structural_investment is None else repr(successor.structural_investment),
            "milestone_result": None if successor.milestone_result is None else repr(successor.milestone_result),
            "receiver_uncover_followup": (
                None if successor.receiver_uncover_followup is None
                else list(successor.receiver_uncover_followup)
            ),
        },
        "transition_replay_matches_endpoint": (
            canonical_state_key(replay_state) == canonical_state_key(successor.end_state)
        ),
    }


class EmptyServiceObserver(r3.R3ServiceObserver):
    """Reuse the prior R3 prerequisite and layer one empty-node extraction."""

    def __init__(
        self,
        opening: SpiderState,
        *,
        enable_r3_service: bool,
        enable_empty_service: bool,
    ) -> None:
        super().__init__(opening, enable_service=enable_r3_service)
        self.enable_empty_service = enable_empty_service
        self.empty_service = OneShotEmptyService(
            enabled=enable_empty_service, origin_by_id={}
        )
        self.empty_selection = None
        self.empty_selected_parent_id = None
        self.empty_selected_state = None
        self.empty_pipeline = {}
        self.empty_tt_pipeline = []
        self._empty_pipeline_active = False
        self._empty_tt_active = False
        self._empty_final_successors = ()
        self._empty_originals = {}

    def _record_empty_selection(self, heap, selected, candidates) -> None:
        ordered = sorted(heap)
        rank_by_id = {
            item[2].node_id: rank for rank, item in enumerate(ordered, start=1)
        }
        node = selected[2]
        edge = node.incoming_edge
        parent = self.nodes.get(node.parent_id)
        self.empty_selected_parent_id = node.node_id
        self.empty_selected_state = node.state.clone()
        self.empty_selection = {
            "digest": common.digest(node.state),
            "node_id": node.node_id,
            "g": int(node.g),
            "credit": int(node.credit_level),
            "macro_depth": int(node.depth),
            "total_face_down": sum(len(column.face_down) for column in node.state.columns),
            "actual_empty_columns": list(actual_empty_columns(node.state)),
            "actual_empty_count": len(actual_empty_columns(node.state)),
            "fully_revealed_columns": sum(
                bool(column.face_up) and not column.face_down
                for column in node.state.columns
            ),
            "stock_rows_undealt": len(node.state.stock) // 10,
            "queue_rank_before_intervention": rank_by_id[node.node_id],
            "ordinary_queue_priority": repr(selected[0]),
            "legal_tableau_move_count": len(node.state.enumerate_moves()),
            "scheduler": r3._scheduler_facts(node),
            "created_by": {
                "parent_node_id": node.parent_id,
                "parent_digest": None if parent is None else parent["digest"],
                "kind": None if edge is None else edge.kind.value,
                "category": None if edge is None else edge.category,
                "actions": [] if edge is None else [
                    common.action_json(action) for action in edge.actions
                ],
                "corrected_edge_cost": None if edge is None else int(edge.corrected_cost),
                "tt_admitted_ordinary_successor": self.nodes[node.node_id]["origin"] == "SUCCESSOR",
            },
            "node_object_identity_preserved": True,
            "frontier_size_before": len(heap),
            "eligible_candidates_at_selection": [
                {
                    "digest": common.digest(item[2].state),
                    "node_id": item[2].node_id,
                    "g": int(item[2].g),
                    "credit": int(item[2].credit_level),
                    "empty_columns": list(actual_empty_columns(item[2].state)),
                    "queue_rank": rank_by_id[item[2].node_id],
                    "ordinary_queue_priority": repr(item[0]),
                }
                for item in candidates
            ],
        }

    def install(self) -> None:
        super().install()
        observed_pop = controller.heapq.heappop
        observed_generate = controller.generate_strategic_successors
        self._empty_originals = {
            "pop": observed_pop,
            "generate": observed_generate,
            "deduplicate": controller.deduplicate_strategic_successors,
            "retain_diverse": controller.retain_diverse_portfolio,
            "retain_obligation": controller.retain_obligation_successors,
            "tt_admit": controller.StrategicTranspositionTable.admit,
        }
        obs = self

        def origins():
            return {node_id: row["origin"] for node_id, row in obs.nodes.items()}

        def wrapped_pop(heap):
            if obs._empty_tt_active:
                obs._empty_tt_active = False
            # Empty service is a second-stage treatment. The prior R3 service
            # must first have been spent by the identical inherited wrapper.
            if not obs.service.spent:
                return observed_pop(heap)
            obs.empty_service.origin_by_id = origins()
            selected, candidates = choose_empty_candidate(
                heap, obs.empty_service.origin_by_id
            )
            item, forced = obs.empty_service.pop(
                heap,
                ordinary_pop=observed_pop,
                ordinary_heapify=obs._originals["heapify"],
            )
            if forced:
                obs._record_empty_selection(heap + [item], selected, candidates)
                obs.empty_selection["frontier_size_after"] = len(heap)
                obs._record_forced_pop(heap, item)
            return item

        def wrapped_generate(node, cards, **kwargs):
            selected = node.node_id == obs.empty_selected_parent_id
            obs._empty_pipeline_active = selected
            try:
                successors = observed_generate(node, cards, **kwargs)
            finally:
                obs._empty_pipeline_active = False
            if selected:
                obs._empty_final_successors = tuple(successors)
                obs.empty_pipeline["final"] = [
                    workspace_successor_record(
                        item, index, obs.empty_selected_state
                    )
                    for index, item in enumerate(successors)
                ]
                obs._empty_tt_active = True
            return successors

        def wrapped_deduplicate(successors):
            materialized = tuple(successors)
            if obs._empty_pipeline_active:
                obs.empty_pipeline["raw"] = [
                    workspace_successor_record(
                        item, index, obs.empty_selected_state
                    )
                    for index, item in enumerate(materialized)
                ]
            result = obs._empty_originals["deduplicate"](materialized)
            if obs._empty_pipeline_active:
                obs.empty_pipeline["deduplicated"] = [
                    workspace_successor_record(
                        item, index, obs.empty_selected_state
                    )
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_retain_diverse(successors, *, maximum):
            result = obs._empty_originals["retain_diverse"](
                successors, maximum=maximum
            )
            if obs._empty_pipeline_active:
                obs.empty_pipeline["diverse_portfolio"] = [
                    workspace_successor_record(
                        item, index, obs.empty_selected_state
                    )
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_retain_obligation(node, deduplicated, retained, *, maximum):
            result = obs._empty_originals["retain_obligation"](
                node, deduplicated, retained, maximum=maximum
            )
            if obs._empty_pipeline_active:
                obs.empty_pipeline["obligation_portfolio"] = [
                    workspace_successor_record(
                        item, index, obs.empty_selected_state
                    )
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_tt_admit(table, state, g, *, heuristic_score=None):
            previous = table.best_g(state)
            admitted = obs._empty_originals["tt_admit"](
                table, state, g, heuristic_score=heuristic_score
            )
            if (
                obs._empty_tt_active
                and len(obs.empty_tt_pipeline) < len(obs._empty_final_successors)
            ):
                successor = obs._empty_final_successors[len(obs.empty_tt_pipeline)]
                obs.empty_tt_pipeline.append(
                    {
                        "key": repr(r3._successor_key(successor)),
                        "end_digest": common.digest(state),
                        "candidate_g": int(g),
                        "previous_best_g": previous,
                        "result": "ADMITTED" if admitted else "SUPPRESSED",
                        "reason": None if admitted else "exact state reached at no lower g",
                    }
                )
            return admitted

        heapq.heappop = controller.heapq.heappop = wrapped_pop
        controller.generate_strategic_successors = wrapped_generate
        controller.deduplicate_strategic_successors = wrapped_deduplicate
        controller.retain_diverse_portfolio = wrapped_retain_diverse
        controller.retain_obligation_successors = wrapped_retain_obligation
        controller.StrategicTranspositionTable.admit = wrapped_tt_admit

    def restore(self) -> None:
        controller.deduplicate_strategic_successors = self._empty_originals["deduplicate"]
        controller.retain_diverse_portfolio = self._empty_originals["retain_diverse"]
        controller.retain_obligation_successors = self._empty_originals["retain_obligation"]
        controller.StrategicTranspositionTable.admit = self._empty_originals["tt_admit"]
        super().restore()

    @staticmethod
    def _keys(rows) -> list[str]:
        return [row["key"] for row in rows]

    def empty_production_autopsy(self) -> dict | None:
        if self.empty_selection is None:
            return None
        raw = self.empty_pipeline.get("raw", [])
        dedup = self.empty_pipeline.get("deduplicated", [])
        diverse = self.empty_pipeline.get("diverse_portfolio", [])
        obligation = self.empty_pipeline.get("obligation_portfolio", [])
        final = self.empty_pipeline.get("final", [])
        stage_counts = {
            "raw": len(raw),
            "deduplicated": len(dedup),
            "diverse_portfolio": len(diverse),
            "obligation_portfolio": len(obligation),
            "final": len(final),
        }
        diverse_counts = Counter(self._keys(diverse))
        obligation_counts = Counter(self._keys(obligation))
        final_counts = Counter(self._keys(final))
        tt_by_key = {row["key"]: row for row in self.empty_tt_pipeline}
        events = [
            event
            for event in self.events
            if event["parent_node_id"] == self.empty_selected_parent_id
        ]
        events_by_key = {repr(r3._event_key(event)): event for event in events}
        raw_by_key = {}
        for row in raw:
            raw_by_key.setdefault(row["key"], []).append(row)
        dedup_by_key = {row["key"]: row for row in dedup}
        representative_source_index = {}
        for key, sources in raw_by_key.items():
            representative = dedup_by_key.get(key)
            if representative is None:
                continue
            representative_source_index[key] = max(
                sources,
                key=lambda source: (
                    source["kind"] == representative["kind"],
                    source["category"] == representative["category"],
                    source["index"],
                ),
            )["index"]
        candidates = []
        for row in raw:
            key = row["key"]
            representative = dedup_by_key.get(key)
            survives_dedup = (
                representative is not None
                and row["index"] == representative_source_index.get(key)
            )
            survives_diverse = survives_dedup and bool(diverse_counts[key])
            survives_obligation = survives_dedup and bool(obligation_counts[key])
            survives_final = survives_dedup and bool(final_counts[key])
            if not survives_dedup:
                stage = "deduplication"
                reason = (
                    "exact endpoint merged into the recorded deduplicated "
                    "representative"
                )
            elif not survives_diverse and not survives_obligation:
                stage = "diverse portfolio"
                reason = "category round-robin/fill truncated to unchanged cap"
            elif not survives_obligation:
                stage = "obligation portfolio"
                reason = "replaced by unchanged obligation retention"
            elif not survives_final:
                stage = "final family protection"
                reason = "absent after unchanged final protected-family handling"
            else:
                stage = reason = None
            event = events_by_key.get(key) if survives_final else None
            child_id = None if event is None else event["child_node_id"]
            child = None if child_id is None else self.nodes.get(child_id)
            candidates.append(
                {
                    **row,
                    "exact_endpoint_raw_group_size": len(raw_by_key[key]),
                    "deduplicated_representative": representative,
                    "deduplication_disposition": (
                        "REPRESENTATIVE" if survives_dedup else "MERGED_OR_REPLACED"
                    ),
                    "survives_deduplication": survives_dedup,
                    "survives_diverse_portfolio": survives_diverse,
                    "survives_obligation_portfolio": survives_obligation,
                    "in_final_successor_portfolio": survives_final,
                    "removed_before_final": not survives_final,
                    "removal_stage": stage,
                    "removal_reason": reason,
                    "tt": tt_by_key.get(key) if survives_final else None,
                    "ultimately_retained": bool(event and event["retained"]),
                    "child_node_id": child_id,
                    "subsequently_live": bool(child and child.get("live")),
                    "subsequently_popped": bool(child and child.get("popped")),
                    "subsequently_expanded": bool(child and child.get("expanded")),
                    "subsequently_trimmed": bool(child and child.get("trimmed")),
                }
            )
        retained_progress = [
            row
            for row in candidates
            if row["ultimately_retained"]
            and row["workspace_classification"]
            in {"PRODUCTIVE_EMPTY_USE", "EMPTY_PRESERVED_PROGRESS"}
        ]
        retained_productive = [
            row
            for row in retained_progress
            if row["workspace_classification"] == "PRODUCTIVE_EMPTY_USE"
        ]
        progress_child_lifecycle = []
        for row in retained_progress:
            child_id = row["child_node_id"]
            child = self.nodes.get(child_id)
            digest = row["end_digest"]
            widened = [
                record
                for record in self.nodes.values()
                if record["origin"] == "WIDENING" and record["digest"] == digest
            ]
            child_events = [
                event for event in self.events if event["parent_node_id"] == child_id
            ]
            progress_child_lifecycle.append(
                {
                    "child_node_id": child_id,
                    "digest": digest,
                    "classification": row["workspace_classification"],
                    "popped": bool(child and child.get("popped")),
                    "expanded": bool(child and child.get("expanded")),
                    "live": bool(child and child.get("live")),
                    "trimmed": bool(child and child.get("trimmed")),
                    "widened_node_ids": [item["node_id"] for item in widened],
                    "widened_popped": sum(item["popped"] for item in widened),
                    "widened_expanded": sum(item["expanded"] for item in widened),
                    "further_empty_successors": sum(
                        event["child_geometry"]["empties"] > 0
                        for event in child_events
                    ),
                    "further_empty_retained": sum(
                        event["retained"] and event["child_geometry"]["empties"] > 0
                        for event in child_events
                    ),
                    "face_down_reducing_successors": sum(
                        event["child_geometry"]["face_down"] < row["face_down"]
                        for event in child_events
                    ),
                    "foundation_successors": sum(
                        event["child_geometry"]["foundations"] > 0
                        for event in child_events
                    ),
                    "lower_stock_successors": sum(
                        event["child_geometry"]["stock_rows"] < row["stock_rows"]
                        for event in child_events
                    ),
                }
            )
        return {
            "selected_parent": self.empty_selection,
            "service": {
                "enabled": self.enable_empty_service,
                "spent": self.empty_service.spent,
                "special_services": self.empty_service.services,
                "frontier_capacity": 256,
                "frontier_size_before": self.empty_service.frontier_size_before,
                "frontier_size_after_extraction": self.empty_service.frontier_size_after,
            },
            "stage_counts": stage_counts,
            "pipeline_stages": self.empty_pipeline,
            "candidates": candidates,
            "tt_calls": self.empty_tt_pipeline,
            "classification_counts_raw": dict(
                sorted(Counter(row["workspace_classification"] for row in candidates).items())
            ),
            "classification_counts_retained": dict(
                sorted(
                    Counter(
                        row["workspace_classification"]
                        for row in candidates
                        if row["ultimately_retained"]
                    ).items()
                )
            ),
            "retained_productive_count": len(retained_productive),
            "retained_productive_types": dict(
                sorted(Counter(row["workspace_classification"] for row in retained_productive).items())
            ),
            "retained_progress_count": len(retained_progress),
            "retained_progress_types": dict(
                sorted(Counter(row["workspace_classification"] for row in retained_progress).items())
            ),
            "productive_child_lifecycle": [
                row
                for row in progress_child_lifecycle
                if row["classification"] == "PRODUCTIVE_EMPTY_USE"
            ],
            "retained_progress_child_lifecycle": progress_child_lifecycle,
        }

    def empty_summary(self, result) -> dict:
        summary = self.service_summary(result)
        summary["empty_service"] = {
            "enabled": self.enable_empty_service,
            "spent": self.empty_service.spent,
            "special_services": self.empty_service.services,
            "selected_parent_id": self.empty_selected_parent_id,
        }
        summary["selected_empty_autopsy"] = self.empty_production_autopsy()
        return summary


def run_arm(
    opening,
    cards,
    *,
    enable_r3_service: bool,
    enable_empty_service: bool,
) -> dict:
    random.seed(common.SEED)
    config = common.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    config = replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    state_local.assert_config(config)
    observer = EmptyServiceObserver(
        opening,
        enable_r3_service=enable_r3_service,
        enable_empty_service=enable_empty_service,
    )
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        summary = observer.empty_summary(result)
    finally:
        observer.restore()
    summary["priority_schema"] = config.frontier_priority_schema.value
    summary["credit_propagation"] = config.strategic_credit_propagation.value
    summary["r3_prerequisite_implementation_sha256"] = hashlib.sha256(
        inspect.getsource(r3.OneShotR3Service).encode("utf-8")
    ).hexdigest()
    return summary


def _r3_fingerprint(arm: dict):
    autopsy = arm.get("selected_r3_autopsy")
    if autopsy is None:
        return None
    parent = autopsy["selected_parent"]
    return {
        "digest": parent["digest"],
        "g": parent["g"],
        "credit": parent["credit"],
        "legal_moves": parent["legal_full_column_empty_creating_moves"],
        "special_services": autopsy["service"]["special_services"],
    }


def classify(arms: dict) -> str:
    treatment = arms["R3_THEN_EMPTY"]
    autopsy = treatment.get("selected_empty_autopsy")
    if not autopsy or autopsy["service"]["special_services"] != 1:
        return "EMPTY_SERVICE_INCONCLUSIVE"
    candidates = autopsy["candidates"]
    retained_useful = [
        row
        for row in candidates
        if row["ultimately_retained"]
        and row["independent_replay_check"]
        and row["workspace_classification"] == "PRODUCTIVE_EMPTY_USE"
    ]
    if retained_useful:
        return "EMPTY_SERVICE_SUFFICIENT"
    generated_useful = [
        row
        for row in candidates
        if row["workspace_classification"] == "PRODUCTIVE_EMPTY_USE"
    ]
    if generated_useful:
        return "EMPTY_SUCCESSOR_EXISTS_BUT_IS_SUPPRESSED"
    return "EMPTY_SERVICE_EXPOSES_RESOURCE_GAP"


def main() -> int:
    cards = tuple(load_deal(common.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    definitions = (
        ("CONTROL", False, False),
        ("R3_ONLY", True, False),
        ("R3_THEN_EMPTY", True, True),
    )
    arms = {}
    for label, enable_r3, enable_empty in definitions:
        print(f"Starting {label}", flush=True)
        arms[label] = run_arm(
            opening,
            cards,
            enable_r3_service=enable_r3,
            enable_empty_service=enable_empty,
        )
        arm = arms[label]
        productive = arm.get("selected_empty_autopsy")
        print(
            f"{label}: stop={arm['stop_reason']} expansions={arm['strategic_expansions']} "
            f"elapsed={arm['elapsed_s']:.1f}s tactical={arm['tactical_nodes']} "
            f"credit={[arm['credit'][str(c)]['expansions'] for c in range(5)]} "
            f"r3={arm['R3']['metrics']} empty={arm['actual_empty']} "
            f"productive={0 if productive is None else productive['retained_productive_count']}",
            flush=True,
        )
    verdict = classify(arms)
    treatment = arms["R3_THEN_EMPTY"]
    autopsy = treatment.get("selected_empty_autopsy")
    gates = {
        "control_has_no_intervention": (
            arms["CONTROL"]["one_shot_service"]["special_services"] == 0
            and arms["CONTROL"]["empty_service"]["special_services"] == 0
        ),
        "r3_only_has_exactly_r3_service": (
            arms["R3_ONLY"]["one_shot_service"]["special_services"] == 1
            and arms["R3_ONLY"]["empty_service"]["special_services"] == 0
        ),
        "treatment_has_exactly_one_r3_then_one_empty_service": bool(
            autopsy
            and treatment["one_shot_service"]["special_services"] == 1
            and autopsy["service"]["special_services"] == 1
        ),
        "r3_prerequisite_identical": (
            arms["R3_ONLY"]["r3_prerequisite_implementation_sha256"]
            == treatment["r3_prerequisite_implementation_sha256"]
            and _r3_fingerprint(arms["R3_ONLY"]) == _r3_fingerprint(treatment)
        ),
        "selected_empty_is_structural_natural_successor": bool(
            autopsy
            and autopsy["selected_parent"]["actual_empty_columns"]
            and autopsy["selected_parent"]["created_by"]["tt_admitted_ordinary_successor"]
        ),
        "frontier_capacity_unchanged": bool(
            autopsy and autopsy["service"]["frontier_capacity"] == 256
        ),
        "resource_planner_not_invoked": all(
            arm["resource_planner_calls"] == 0 for arm in arms.values()
        ),
        "replay_and_cost_integrity": all(
            not arm["replay_failures"] and not arm["corrected_cost_inconsistencies"]
            for arm in arms.values()
        ),
        "controller_has_no_resource_planner_reference": (
            "resource_excavation" not in inspect.getsource(controller)
        ),
    }
    payload = {
        "experiment": "one_shot_natural_empty_service_v0_1",
        "base_sha": BASE_SHA,
        "deal": 4925153,
        "seed": common.SEED,
        "design": ["CONTROL", "R3_ONLY", "R3_THEN_EMPTY"],
        "config": {
            "max_strategic_expansions": 400,
            "max_tactical_nodes": 300_000,
            "wall_clock_limit_s": 900.0,
            "max_frontier_size": 256,
            "max_successors_per_expansion": 10,
            "max_credit_level": 4,
            "scheduler": True,
            "tactical_allocation": True,
            "incumbent": None,
            "target_foundation_count": 2,
            "priority_schema": "COMMON_STAGE0",
            "credit_propagation": "STATE_LOCAL",
        },
        "gates": gates,
        "verdict": verdict,
        "arms": arms,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )
    print("Gates", gates, flush=True)
    print("Verdict", verdict, flush=True)
    print("Wrote", RESULT_PATH, flush=True)
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
