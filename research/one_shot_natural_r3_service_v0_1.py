#!/usr/bin/env python3
"""Two-arm one-shot natural-R3 service experiment.

The treatment is deliberately a harness-only heap extraction.  It services one
existing naturally admitted R3 node without changing production configuration,
priority, capacity, node metadata, or successor generation.
"""

from __future__ import annotations

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


BASE_SHA = "60d83bd7823aebffed9fe8ecf83e311046641c76"
RESULT_PATH = ROOT / "docs" / "research" / "one_shot_natural_r3_service_v0_1.json"


def legal_full_column_empty_creating_moves(state: SpiderState) -> tuple[tuple[int, int, int], ...]:
    """Enumerate R3 moves through the engine, never through rank inference."""

    if any(column.is_empty() for column in state.columns):
        return ()
    legal = []
    for action in state.enumerate_moves():
        src, _dst, count = action
        source = state.columns[src]
        if source.face_down or not source.face_up or count != len(source.face_up):
            continue
        if not state.can_move(*action):
            continue
        end = state.clone()
        end.move(*action, rules=MW_RULES)
        if end.columns[src].is_empty():
            legal.append(action)
    return tuple(legal)


def eligible_r3_frontier_items(frontier, origin_by_id) -> list[tuple]:
    """Return live, ordinary, naturally admitted R3 heap entries."""

    eligible = []
    for item in frontier:
        if not common.Observer._is_frontier_item(item):
            continue
        node = item[2]
        if origin_by_id.get(node.node_id) != "SUCCESSOR":
            continue
        if legal_full_column_empty_creating_moves(node.state):
            eligible.append(item)
    return eligible


def choose_r3_candidate(frontier, origin_by_id):
    """Use the ordinary heap key and node id; add no R3 score."""

    candidates = eligible_r3_frontier_items(frontier, origin_by_id)
    if not candidates:
        return None, ()
    ordered = sorted(candidates, key=lambda item: (item[0], item[2].node_id))
    return ordered[0], tuple(ordered)


class OneShotR3Service:
    """Extract one exact existing R3 entry, then permanently become inert."""

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
        selected, candidates = choose_r3_candidate(frontier, self.origin_by_id)
        if selected is None:
            return ordinary_pop(frontier), False
        self.candidates = candidates
        self.selected_item = selected
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


def _actions_key(successor) -> tuple:
    return tuple(tuple(action) if not isinstance(action, str) else action for action in successor.actions)


def _successor_key(successor) -> tuple:
    return (common.digest(successor.end_state), _actions_key(successor), int(successor.corrected_cost))


def _event_key(event: dict) -> tuple:
    actions = tuple(
        ("deal",) if action == "deal" else tuple(action)
        for action in event["actions"]
    )
    return (event["child_digest"], actions, int(event["cost"]))


def _successor_record(successor, index: int, parent_state: SpiderState | None = None) -> dict:
    replay_verified = None
    if parent_state is not None:
        replay = parent_state.clone()
        try:
            replay_cost = replay_actions(replay, list(successor.actions))
            replay_verified = (
                replay_cost == successor.corrected_cost
                and canonical_state_key(replay) == canonical_state_key(successor.end_state)
            )
        except (ValueError, AssertionError, IndexError):
            replay_verified = False
    return {
        "index": index,
        "kind": successor.kind.value,
        "category": successor.category,
        "actions": [common.action_json(action) for action in successor.actions],
        "corrected_cost": int(successor.corrected_cost),
        "end_digest": common.digest(successor.end_state),
        "creates_actual_empty": any(column.is_empty() for column in successor.end_state.columns),
        "empty_count": sum(column.is_empty() for column in successor.end_state.columns),
        "face_down": sum(len(column.face_down) for column in successor.end_state.columns),
        "stock_rows": len(successor.end_state.stock) // 10,
        "independent_replay_verified": bool(successor.independent_replay_verified),
        "independent_replay_check": replay_verified,
        "proof_pruning_allowed": bool(successor.proof_pruning_allowed),
        "key": repr(_successor_key(successor)),
    }


def _scheduler_facts(node: StrategicSearchNode) -> dict:
    edge = node.incoming_edge
    objective = None if edge is None else edge.scheduled_objective
    schedule = node.whole_deal_schedule
    lead = None
    if schedule is not None and schedule.lane_sequence_priority is not None:
        lead = schedule.lane_sequence_priority.lead
    return {
        "current_lead_ordering_key": repr(controller._current_lead_ordering_key(node)),
        "lead": None if lead is None else repr(lead),
        "schedule_epoch": None if schedule is None else schedule.epoch,
        "incoming_scheduled_objective": None if objective is None else repr(objective),
        "incoming_scheduler_effect_rank": None if edge is None else edge.scheduler_effect_rank,
        "active_milestone": None if node.active_milestone is None else repr(node.active_milestone),
        "active_residual_target": None if node.active_residual_target is None else repr(node.active_residual_target),
        "continuation_credit": None if node.continuation_credit is None else repr(node.continuation_credit),
    }


class R3ServiceObserver(state_local.CreditFlowObserver):
    def __init__(self, opening: SpiderState, *, enable_service: bool) -> None:
        super().__init__(opening)
        self.enable_service = enable_service
        self.service = OneShotR3Service(enabled=enable_service, origin_by_id={})
        self.selection = None
        self.selected_parent_id = None
        self.selected_state = None
        self.pipeline = {}
        self.tt_pipeline = []
        self.resource_planner_calls = 0
        self._pipeline_active = False
        self._tt_active = False
        self._final_successors = ()
        self._service_originals = {}

    def _record_forced_pop(self, heap, item) -> None:
        record = self._node_record(item[2])
        record["popped"] = True
        record["last_rank"] = 1
        self.pops.append(record["node_id"])
        self.current_popped = record
        self._snapshot_ranks(heap)

    def _record_selection(self, heap, selected, candidates) -> None:
        ordered = sorted(heap)
        rank_by_id = {item[2].node_id: rank for rank, item in enumerate(ordered, start=1)}
        node = selected[2]
        moves = legal_full_column_empty_creating_moves(node.state)
        self.selected_parent_id = node.node_id
        self.selected_state = node.state.clone()
        self.selection = {
            "digest": common.digest(node.state),
            "node_id": node.node_id,
            "g": int(node.g),
            "credit": int(node.credit_level),
            "macro_depth": int(node.depth),
            "total_face_down": sum(len(column.face_down) for column in node.state.columns),
            "fully_revealed_columns": sum(bool(column.face_up) and not column.face_down for column in node.state.columns),
            "actual_empty_count": sum(column.is_empty() for column in node.state.columns),
            "stock_rows_undealt": len(node.state.stock) // 10,
            "queue_rank_before_intervention": rank_by_id[node.node_id],
            "ordinary_queue_priority": repr(selected[0]),
            "scheduler": _scheduler_facts(node),
            "legal_full_column_empty_creating_moves": [list(move) for move in moves],
            "node_object_identity_preserved": True,
            "frontier_size_before": len(heap),
            "eligible_candidates_at_selection": [
                {
                    "digest": common.digest(item[2].state),
                    "node_id": item[2].node_id,
                    "g": int(item[2].g),
                    "credit": int(item[2].credit_level),
                    "queue_rank": rank_by_id[item[2].node_id],
                    "ordinary_queue_priority": repr(item[0]),
                    "legal_moves": [list(move) for move in legal_full_column_empty_creating_moves(item[2].state)],
                }
                for item in candidates
            ],
        }

    def install(self) -> None:
        super().install()
        self.service.origin_by_id = {
            node_id: row["origin"] for node_id, row in self.nodes.items()
        }
        observed_pop = controller.heapq.heappop
        observed_generate = controller.generate_strategic_successors
        self._service_originals = {
            "pop": observed_pop,
            "generate": observed_generate,
            "deduplicate": controller.deduplicate_strategic_successors,
            "retain_diverse": controller.retain_diverse_portfolio,
            "retain_obligation": controller.retain_obligation_successors,
            "tt_admit": controller.StrategicTranspositionTable.admit,
            "resource": common.production_shadow.plan_resource_excavation,
        }
        obs = self

        def origins():
            return {node_id: row["origin"] for node_id, row in obs.nodes.items()}

        self.service.origin_by_id = origins()

        def wrapped_pop(heap):
            # Refresh origins after every admission cycle.
            obs.service.origin_by_id = origins()
            if obs._tt_active:
                obs._tt_active = False
            selected, candidates = choose_r3_candidate(heap, obs.service.origin_by_id)
            item, forced = obs.service.pop(
                heap,
                ordinary_pop=observed_pop,
                ordinary_heapify=obs._originals["heapify"],
            )
            if forced:
                obs._record_selection(heap + [item], selected, candidates)
                obs.selection["frontier_size_after"] = len(heap)
                obs._record_forced_pop(heap, item)
            return item

        def wrapped_generate(node, cards, **kwargs):
            selected = node.node_id == obs.selected_parent_id
            obs._pipeline_active = selected
            try:
                successors = observed_generate(node, cards, **kwargs)
            finally:
                obs._pipeline_active = False
            if selected:
                obs._final_successors = tuple(successors)
                obs.pipeline["final"] = [
                    _successor_record(item, index, obs.selected_state)
                    for index, item in enumerate(successors)
                ]
                obs._tt_active = True
            return successors

        def wrapped_deduplicate(successors):
            materialized = tuple(successors)
            if obs._pipeline_active:
                obs.pipeline["raw"] = [
                    _successor_record(item, index, obs.selected_state)
                    for index, item in enumerate(materialized)
                ]
            result = obs._service_originals["deduplicate"](materialized)
            if obs._pipeline_active:
                obs.pipeline["deduplicated"] = [
                    _successor_record(item, index, obs.selected_state)
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_retain_diverse(successors, *, maximum):
            result = obs._service_originals["retain_diverse"](successors, maximum=maximum)
            if obs._pipeline_active:
                obs.pipeline["diverse_portfolio"] = [
                    _successor_record(item, index, obs.selected_state)
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_retain_obligation(node, deduplicated, retained, *, maximum):
            result = obs._service_originals["retain_obligation"](
                node, deduplicated, retained, maximum=maximum
            )
            if obs._pipeline_active:
                obs.pipeline["obligation_portfolio"] = [
                    _successor_record(item, index, obs.selected_state)
                    for index, item in enumerate(result)
                ]
            return result

        def wrapped_tt_admit(table, state, g, *, heuristic_score=None):
            previous = table.best_g(state)
            admitted = obs._service_originals["tt_admit"](
                table, state, g, heuristic_score=heuristic_score
            )
            if obs._tt_active and len(obs.tt_pipeline) < len(obs._final_successors):
                successor = obs._final_successors[len(obs.tt_pipeline)]
                obs.tt_pipeline.append(
                    {
                        "key": repr(_successor_key(successor)),
                        "end_digest": common.digest(state),
                        "candidate_g": int(g),
                        "previous_best_g": previous,
                        "result": "ADMITTED" if admitted else "SUPPRESSED",
                        "reason": None if admitted else "exact state reached at no lower g",
                    }
                )
            return admitted

        def wrapped_resource(*args, **kwargs):
            obs.resource_planner_calls += 1
            return obs._service_originals["resource"](*args, **kwargs)

        heapq.heappop = controller.heapq.heappop = wrapped_pop
        controller.generate_strategic_successors = wrapped_generate
        controller.deduplicate_strategic_successors = wrapped_deduplicate
        controller.retain_diverse_portfolio = wrapped_retain_diverse
        controller.retain_obligation_successors = wrapped_retain_obligation
        controller.StrategicTranspositionTable.admit = wrapped_tt_admit
        common.production_shadow.plan_resource_excavation = wrapped_resource

    def restore(self) -> None:
        controller.deduplicate_strategic_successors = self._service_originals["deduplicate"]
        controller.retain_diverse_portfolio = self._service_originals["retain_diverse"]
        controller.retain_obligation_successors = self._service_originals["retain_obligation"]
        controller.StrategicTranspositionTable.admit = self._service_originals["tt_admit"]
        common.production_shadow.plan_resource_excavation = self._service_originals["resource"]
        super().restore()

    @staticmethod
    def _keys(rows) -> list[str]:
        return [row["key"] for row in rows]

    def production_autopsy(self) -> dict | None:
        if self.selection is None:
            return None
        raw = self.pipeline.get("raw", [])
        dedup = self.pipeline.get("deduplicated", [])
        diverse = self.pipeline.get("diverse_portfolio", [])
        obligation = self.pipeline.get("obligation_portfolio", [])
        final = self.pipeline.get("final", [])
        dedup_keys, diverse_keys = self._keys(dedup), self._keys(diverse)
        obligation_keys, final_keys = self._keys(obligation), self._keys(final)
        tt_by_key = {row["key"]: row for row in self.tt_pipeline}
        events = [
            event for event in self.events if event["parent_node_id"] == self.selected_parent_id
        ]
        retained_keys = {
            repr(_event_key(event))
            for event in events if event["retained"]
        }
        events_by_key = {
            repr(_event_key(event)): event
            for event in events
        }
        dedup_counts = Counter(dedup_keys)
        diverse_counts = Counter(diverse_keys)
        obligation_counts = Counter(obligation_keys)
        final_counts = Counter(final_keys)
        raw_occurrences = Counter()
        candidates = []
        for row in raw:
            key = row["key"]
            raw_occurrences[key] += 1
            occurrence = raw_occurrences[key]
            survives_dedup = occurrence <= dedup_counts[key]
            survives_diverse = survives_dedup and occurrence <= diverse_counts[key]
            survives_obligation = survives_dedup and occurrence <= obligation_counts[key]
            survives_final = survives_dedup and occurrence <= final_counts[key]
            if not survives_dedup:
                removed_stage = "deduplication"
                reason = "exact endpoint kept an alternate representative"
            elif not survives_diverse and not survives_obligation:
                removed_stage = "diverse portfolio"
                reason = "category round-robin/fill truncated to the unchanged portfolio cap"
            elif not survives_obligation:
                removed_stage = "obligation portfolio"
                reason = "replaced by unchanged obligation retention"
            elif not survives_final:
                removed_stage = "final family protection"
                reason = "not present after unchanged final protected-family handling"
            else:
                removed_stage = None
                reason = None
            event = events_by_key.get(key)
            child_id = None if event is None else event["child_node_id"]
            child = (
                None
                if not survives_final or child_id is None
                else self.nodes.get(child_id)
            )
            candidates.append(
                {
                    **row,
                    "exact_endpoint_occurrence": occurrence,
                    "exact_endpoint_raw_group_size": sum(item["key"] == key for item in raw),
                    "survives_deduplication": survives_dedup,
                    "survives_diverse_portfolio": survives_diverse,
                    "survives_obligation_portfolio": survives_obligation,
                    "in_final_successor_portfolio": survives_final,
                    "removed_before_final": not survives_final,
                    "removal_stage": removed_stage,
                    "removal_reason": reason,
                    "tt": tt_by_key.get(key) if survives_final else None,
                    "ultimately_retained": survives_final and key in retained_keys,
                    "child_node_id": child_id if survives_final else None,
                    "subsequently_live": bool(child and child.get("live")),
                    "subsequently_popped": bool(child and child.get("popped")),
                    "subsequently_expanded": bool(child and child.get("expanded")),
                    "subsequently_trimmed": bool(child and child.get("trimmed")),
                }
            )
        legal_coverage = []
        for action in self.selection["legal_full_column_empty_creating_moves"]:
            exact = [row for row in candidates if row["actions"] == [action]]
            begins = [row for row in candidates if row["actions"] and row["actions"][0] == action]
            relevant = exact or begins
            if exact:
                classification = "generated exactly"
            elif begins:
                classification = "generated as macro prefix"
            else:
                classification = "never generated"
            legal_coverage.append(
                {
                    "move": action,
                    "classification": classification,
                    "raw_candidate_indices": [row["index"] for row in relevant],
                    "final_candidate_indices": [row["index"] for row in relevant if row["in_final_successor_portfolio"]],
                    "tt_results": [row["tt"] for row in relevant if row["tt"] is not None],
                    "retained": any(row["ultimately_retained"] for row in relevant),
                }
            )
        return {
            "selected_parent": self.selection,
            "service": {
                "enabled": self.enable_service,
                "spent": self.service.spent,
                "special_services": self.service.services,
                "frontier_capacity": 256,
                "frontier_size_before": self.service.frontier_size_before,
                "frontier_size_after_extraction": self.service.frontier_size_after,
            },
            "stage_counts": {
                "raw": len(raw),
                "deduplicated": len(dedup),
                "diverse_portfolio": len(diverse),
                "obligation_portfolio": len(obligation),
                "final": len(final),
            },
            "candidates": candidates,
            "tt_calls": self.tt_pipeline,
            "legal_move_coverage": legal_coverage,
            "resource_planner_calls": self.resource_planner_calls,
        }

    def service_summary(self, result) -> dict:
        summary = self.extended_summary(result)
        summary["one_shot_service"] = {
            "enabled": self.enable_service,
            "spent": self.service.spent,
            "special_services": self.service.services,
            "selected_parent_id": self.selected_parent_id,
        }
        summary["selected_r3_autopsy"] = self.production_autopsy()
        summary["resource_planner_calls"] = self.resource_planner_calls
        return summary


def run_arm(opening, cards, *, enable_service: bool) -> dict:
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
    observer = R3ServiceObserver(opening, enable_service=enable_service)
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        summary = observer.service_summary(result)
    finally:
        observer.restore()
    summary["priority_schema"] = config.frontier_priority_schema.value
    summary["credit_propagation"] = config.strategic_credit_propagation.value
    return summary


def classify(control: dict, treatment: dict) -> str:
    autopsy = treatment.get("selected_r3_autopsy")
    if not autopsy or autopsy["service"]["special_services"] != 1:
        return "R3_SERVICE_INCONCLUSIVE"
    empty_candidates = [
        row for row in autopsy["candidates"] if row["creates_actual_empty"]
    ]
    if any(row["ultimately_retained"] and row["independent_replay_verified"] for row in empty_candidates):
        return "R3_SERVICE_SUFFICIENT"
    coverage = autopsy["legal_move_coverage"]
    if coverage and all(row["classification"] == "never generated" for row in coverage):
        return "R3_SERVICE_EXPOSES_COVERAGE_GAP"
    if any(row["classification"] != "never generated" for row in coverage):
        return "R3_SUCCESSOR_EXISTS_BUT_IS_SUPPRESSED"
    return "R3_SERVICE_INCONCLUSIVE"


def main() -> int:
    cards = tuple(load_deal(common.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    arms = {}
    for label, enabled in (("CONTROL", False), ("ONE_SHOT_R3_SERVICE", True)):
        print(f"Starting {label}", flush=True)
        arms[label] = run_arm(opening, cards, enable_service=enabled)
        arm = arms[label]
        print(
            f"{label}: stop={arm['stop_reason']} expansions={arm['strategic_expansions']} "
            f"elapsed={arm['elapsed_s']:.1f}s tactical={arm['tactical_nodes']} "
            f"credit={[arm['credit'][str(c)]['expansions'] for c in range(5)]} "
            f"r3={arm['R3']['metrics']} empty={arm['actual_empty']}",
            flush=True,
        )
    control, treatment = arms["CONTROL"], arms["ONE_SHOT_R3_SERVICE"]
    verdict = classify(control, treatment)
    autopsy = treatment.get("selected_r3_autopsy")
    gates = {
        "control_has_no_intervention": control["one_shot_service"]["special_services"] == 0,
        "treatment_services_exactly_one_natural_r3": bool(
            autopsy
            and autopsy["service"]["special_services"] == 1
            and autopsy["selected_parent"]["actual_empty_count"] == 0
            and autopsy["selected_parent"]["legal_full_column_empty_creating_moves"]
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
        "controller_has_no_resource_planner_reference": "resource_excavation" not in inspect.getsource(controller),
    }
    payload = {
        "experiment": "one_shot_natural_r3_service_v0_1",
        "base_sha": BASE_SHA,
        "deal": 4925153,
        "seed": common.SEED,
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
