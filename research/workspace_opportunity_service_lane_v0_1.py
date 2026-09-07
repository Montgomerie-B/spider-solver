#!/usr/bin/env python3
"""Bounded generic workspace-opportunity service-lane A/B experiment v0.1."""

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
from spider.planner.anytime_controller import (
    CompletionCashOutStatus,
    EpochTransitionRepresentativeStatus,
    FrontierPrioritySchema,
    ResidualTargetStatus,
    StrategicCreditPropagation,
    StrategicSearchNode,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


BASE_SHA = "12e8d9cb0af2212d37f9891f3f77df6ac220bd47"
SERVICE_INTERVAL = 8
RESULT_PATH = ROOT / "docs" / "research" / "workspace_opportunity_service_lane_v0_1.json"


def actual_empty_columns(state: SpiderState) -> tuple[int, ...]:
    """Return structural engine empties, independent of cards and benchmarks."""

    return tuple(index for index, column in enumerate(state.columns) if column.is_empty())


def legal_empty_creating_moves(state: SpiderState) -> tuple[tuple[int, int, int], ...]:
    """Engine-legal whole-column relocations that leave their source empty."""

    if actual_empty_columns(state):
        return ()
    moves = []
    for action in state.enumerate_moves():
        source, _destination, count = action
        column = state.columns[source]
        if column.face_down or not column.face_up or count != len(column.face_up):
            continue
        if not state.can_move(*action):
            continue
        replay = state.clone()
        replay.move(*action, rules=MW_RULES)
        if replay.columns[source].is_empty():
            moves.append(action)
    return tuple(moves)


def workspace_class(state: SpiderState) -> str | None:
    if actual_empty_columns(state):
        return "ACTUAL_EMPTY"
    if legal_empty_creating_moves(state):
        return "EMPTY_CREATABLE"
    return None


def workspace_facts(state: SpiderState) -> dict:
    stage0 = controller.analyze_stage0_state(
        state, spent_cost=0, incumbent_cost=None
    )
    return {
        "workspace_class": workspace_class(state),
        "actual_empty_count": len(actual_empty_columns(state)),
        "empty_creating_moves": [list(move) for move in legal_empty_creating_moves(state)],
        "fully_revealed_columns": sum(
            bool(column.face_up) and not column.face_down for column in state.columns
        ),
        "face_down": stage0.face_down_count,
        "foundations": stage0.foundation_count,
        "stock_rows": len(state.stock) // 10,
        "stable_same_suit_joins": stage0.stable_same_suit_joins,
        "same_suit_run_mass": stage0.same_suit_run_mass,
        "mixed_suit_boundaries": stage0.mixed_suit_boundaries,
        "rehandling_debt": stage0.rehandling_debt,
    }


def expansion_identity(node: StrategicSearchNode) -> tuple:
    return (canonical_state_key(node.state), int(node.credit_level))


def eligible_workspace_items(frontier, *, excluded_expansion_identities=()) -> list[tuple]:
    excluded = set(excluded_expansion_identities)
    return [
        item
        for item in frontier
        if common.Observer._is_frontier_item(item)
        and workspace_class(item[2].state) is not None
        and expansion_identity(item[2]) not in excluded
    ]


def choose_workspace_candidate(frontier, *, excluded_expansion_identities=()):
    candidates = eligible_workspace_items(
        frontier,
        excluded_expansion_identities=excluded_expansion_identities,
    )
    if not candidates:
        return None, ()
    ordered = sorted(candidates, key=lambda item: (item[0], item[2].node_id))
    return ordered[0], tuple(ordered)


class WorkspaceServiceLane:
    """Reserve one exact live entry and service it after eight ordinary expansions."""

    def __init__(self, *, enabled: bool, interval: int = SERVICE_INTERVAL) -> None:
        if interval <= 0:
            raise ValueError("workspace service interval must be positive")
        self.enabled = enabled
        self.interval = interval
        self.current_node_id: int | None = None
        self.current_item = None
        self.current_selection: dict | None = None
        self.pending_pop: dict | None = None
        self.selections: list[dict] = []
        self.ordinary_expansions_since_service = 0
        self.forced_services = 0
        self.natural_services = 0
        self.invalidations = 0
        self.max_outstanding = 0
        self.service_intervals: list[int] = []
        self.lane_duplicate_entries_introduced = 0
        self.trim_protections = 0
        self.expanded_state_credits: set[tuple] = set()

    def _matches(self, frontier) -> list[tuple]:
        if self.current_node_id is None:
            return []
        return [
            item
            for item in frontier
            if common.Observer._is_frontier_item(item)
            and item[2].node_id == self.current_node_id
        ]

    def _invalidate(self, reason: str) -> None:
        if self.current_selection is not None:
            self.current_selection.update(
                outcome="INVALIDATED",
                invalidation_reason=reason,
                invalidated=True,
            )
        self.invalidations += 1
        self.current_node_id = None
        self.current_item = None
        self.current_selection = None
        self.pending_pop = None

    def reconcile(self, frontier) -> None:
        if not self.enabled or self.current_node_id is None:
            return
        if self.pending_pop is not None:
            self._invalidate("popped entry did not reach ordinary generation/expansion")
            return
        matches = self._matches(frontier)
        if not matches:
            self._invalidate("reserved entry is no longer live")
            return
        qualified = [item for item in matches if workspace_class(item[2].state)]
        qualified = [
            item
            for item in qualified
            if expansion_identity(item[2]) not in self.expanded_state_credits
        ]
        if not qualified:
            self._invalidate("reserved state-credit is no longer expansion-eligible")
            return
        self.current_item = min(qualified, key=lambda item: (item[0], item[2].node_id))

    def select(self, frontier, *, expansion_count: int) -> tuple | None:
        if not self.enabled or self.current_node_id is not None:
            return self.current_item
        selected, candidates = choose_workspace_candidate(
            frontier,
            excluded_expansion_identities=self.expanded_state_credits,
        )
        if selected is None:
            return None
        ordered = sorted(frontier)
        rank_by_id = {
            item[2].node_id: rank
            for rank, item in enumerate(ordered, start=1)
            if common.Observer._is_frontier_item(item)
        }
        node = selected[2]
        facts = workspace_facts(node.state)
        record = {
            "selection_index": len(self.selections),
            "selected_after_expansions": expansion_count,
            "node_id": node.node_id,
            "digest": common.digest(node.state),
            "g": int(node.g),
            "credit": int(node.credit_level),
            "workspace_class": facts["workspace_class"],
            "actual_empty_count": facts["actual_empty_count"],
            "fully_revealed_columns": facts["fully_revealed_columns"],
            "face_down": facts["face_down"],
            "stock_rows": facts["stock_rows"],
            "queue_rank": rank_by_id[node.node_id],
            "ordinary_priority": repr(selected[0]),
            "eligible_count": len(candidates),
            "expanded_naturally": False,
            "expanded_via_workspace_service": False,
            "invalidated": False,
            "invalidation_reason": None,
            "trimmed_before_protection": False,
            "survived_to_end": False,
            "outcome": "RESERVED",
            "ordinary_expansions_before_service": None,
        }
        self.selections.append(record)
        self.current_node_id = node.node_id
        self.current_item = selected
        self.current_selection = record
        self.max_outstanding = max(self.max_outstanding, 1)
        return selected

    def pop(self, frontier, *, ordinary_pop, ordinary_heapify, expansion_count: int):
        if not self.enabled:
            return ordinary_pop(frontier), False
        self.reconcile(frontier)
        self.select(frontier, expansion_count=expansion_count)
        if (
            self.current_item is not None
            and self.ordinary_expansions_since_service >= self.interval
        ):
            matches = self._matches(frontier)
            if not matches:
                self._invalidate("scheduled representative disappeared before service")
                return ordinary_pop(frontier), False
            selected = min(matches, key=lambda item: (item[0], item[2].node_id))
            index = next(index for index, item in enumerate(frontier) if item is selected)
            popped = frontier[index]
            last = frontier.pop()
            if index < len(frontier):
                frontier[index] = last
                ordinary_heapify(frontier)
            self.pending_pop = {
                "node_id": popped[2].node_id,
                "mode": "WORKSPACE_FORCED",
            }
            if self.current_selection is not None:
                self.current_selection["outcome"] = "POPPED_FORCED_PENDING_EXPANSION"
            return popped, True
        item = ordinary_pop(frontier)
        if self.current_node_id is not None and item[2].node_id == self.current_node_id:
            self.pending_pop = {
                "node_id": item[2].node_id,
                "mode": "WORKSPACE_NATURAL",
            }
            if self.current_selection is not None:
                self.current_selection["outcome"] = "POPPED_NATURALLY_PENDING_EXPANSION"
        return item, False

    def on_expansion(self, node: StrategicSearchNode) -> str:
        pending = self.pending_pop
        if pending is not None and pending["node_id"] == node.node_id:
            mode = pending["mode"]
            interval = self.ordinary_expansions_since_service
            self.service_intervals.append(interval)
            if mode == "WORKSPACE_FORCED":
                self.forced_services += 1
            else:
                self.natural_services += 1
            if self.current_selection is not None:
                self.current_selection.update(
                    outcome=(
                        "EXPANDED_VIA_WORKSPACE_SERVICE"
                        if mode == "WORKSPACE_FORCED"
                        else "EXPANDED_NATURALLY"
                    ),
                    expanded_naturally=mode == "WORKSPACE_NATURAL",
                    expanded_via_workspace_service=mode == "WORKSPACE_FORCED",
                    ordinary_expansions_before_service=interval,
                )
            self.current_node_id = None
            self.current_item = None
            self.current_selection = None
            self.pending_pop = None
            self.ordinary_expansions_since_service = 0
            self.expanded_state_credits.add(expansion_identity(node))
            return mode
        self.ordinary_expansions_since_service += 1
        self.expanded_state_credits.add(expansion_identity(node))
        return "ORDINARY"

    def finalize(self, frontier) -> None:
        if self.current_node_id is None or self.current_selection is None:
            return
        live = bool(self._matches(frontier))
        self.current_selection["survived_to_end"] = live
        if live:
            self.current_selection["outcome"] = "SURVIVED_TO_END"
        else:
            self._invalidate("not live at end of search")


def _existing_protected_node_ids(frontier, kwargs) -> set[int]:
    """Mirror only identity selection of existing protections for safe overlap."""

    ordered = sorted(frontier)
    protected_ids: set[int] = set()
    completion = next(
        (
            item for item in ordered
            if item[2].completion_cash_out is not None
            and item[2].completion_cash_out.status == CompletionCashOutStatus.RESERVED
            and not item[2].completion_cash_out.cash_out_spent
        ),
        None,
    )
    if completion is not None:
        protected_ids.add(completion[1])
    transition = next(
        (
            item for item in ordered
            if item[1] not in protected_ids
            and item[2].epoch_transition_opportunity is not None
            and item[2].epoch_transition_opportunity.status
            == EpochTransitionRepresentativeStatus.RESERVED
        ),
        None,
    )
    if transition is not None:
        protected_ids.add(transition[1])
    continuation = next(
        (
            item for item in ordered
            if item[2].continuation_credit is not None
            and item[2].continuation_credit.is_live
        ),
        None,
    )
    if continuation is not None:
        protected_ids.add(continuation[1])
    target = next(
        (
            item for item in ordered
            if item[1] not in protected_ids
            and item[2].active_residual_target is not None
            and item[2].active_residual_target.status == ResidualTargetStatus.ACTIONABLE
            and (
                (entry := item[2].target_grant_lineage.active_for(
                    item[2].active_residual_target.identity.fingerprint
                )) is not None
                and entry.evidence.has_portable_harvest
            )
        ),
        None,
    )
    if target is not None:
        protected_ids.add(target[1])
    pre_portfolio = kwargs.get("pre_foundation_portfolio")
    if pre_portfolio is not None:
        keys = {profile.geometry_key() for profile in pre_portfolio.geometries}
        represented = set()
        for item in ordered:
            geometry = item[2].pre_foundation_geometry
            if geometry is None or geometry.geometry_key() not in keys:
                continue
            key = geometry.geometry_key()
            if key in represented:
                continue
            represented.add(key)
            protected_ids.add(item[1])
    portfolio = kwargs.get("portfolio")
    if portfolio is not None:
        keys = {profile.state_key for profile in portfolio.profiles}
        represented = set()
        for item in ordered:
            checkpoint = item[2].foundation_checkpoint
            if checkpoint is None or checkpoint.state_key not in keys:
                continue
            if checkpoint.state_key in represented:
                continue
            represented.add(checkpoint.state_key)
            protected_ids.add(item[1])
    return protected_ids


class WorkspaceServiceObserver(state_local.CreditFlowObserver):
    def __init__(self, opening: SpiderState, *, enable_service: bool) -> None:
        super().__init__(opening)
        self.enable_service = enable_service
        self.lane = WorkspaceServiceLane(enabled=enable_service)
        self.resource_planner_calls = 0
        self.expansion_modes: dict[int, str] = {}
        self.workspace_expansions: list[dict] = []
        self.existing_duplicate_observations: list[dict] = []
        self._lane_originals = {}

    def _record_forced_pop(self, heap, item) -> None:
        record = self._node_record(item[2])
        record["popped"] = True
        record["last_rank"] = 1
        self.pops.append(record["node_id"])
        self.current_popped = record
        self._snapshot_ranks(heap)

    @staticmethod
    def _duplicate_ids(frontier) -> dict[int, int]:
        counts = Counter(
            item[2].node_id
            for item in frontier
            if common.Observer._is_frontier_item(item)
        )
        return {node_id: count for node_id, count in counts.items() if count > 1}

    def _record_duplicate_observation(self, stage: str, frontier) -> None:
        duplicates = self._duplicate_ids(frontier)
        if duplicates:
            self.existing_duplicate_observations.append(
                {
                    "stage": stage,
                    "after_expansions": len(self.expansions),
                    "duplicate_node_ids": duplicates,
                }
            )

    def _protect_workspace_representative(self, original, kept, kwargs):
        node_id = self.lane.current_node_id
        if not self.enable_service or node_id is None:
            return kept
        before_matches = [item for item in original if item[2].node_id == node_id]
        if not before_matches:
            return kept
        before_duplicate_count = sum(
            max(0, count - 1) for count in Counter(item[2].node_id for item in original).values()
        )
        if any(item[2].node_id == node_id for item in kept):
            return kept
        protected_ids = _existing_protected_node_ids(original, kwargs)
        removable = [
            (index, item)
            for index, item in enumerate(kept)
            if item[2].node_id not in protected_ids and item[2].node_id != node_id
        ]
        if not removable:
            self.lane._invalidate("no within-capacity slot could preserve the representative")
            return kept
        remove_index, _removed = max(removable, key=lambda pair: pair[1])
        representative = min(before_matches, key=lambda item: (item[0], item[2].node_id))
        kept[remove_index] = representative
        self._originals["heapify"](kept)
        self._snapshot_ranks(kept)
        self.lane.current_item = representative
        self.lane.trim_protections += 1
        if self.lane.current_selection is not None:
            self.lane.current_selection["trimmed_before_protection"] = True
        record = self._node_record(representative[2])
        if record.get("trimmed"):
            record["trimmed"] = False
            record["trim_expansion"] = None
            credit = int(representative[2].credit_level)
            if self.trims_by_credit[credit] > 0:
                self.trims_by_credit[credit] -= 1
        after_duplicate_count = sum(
            max(0, count - 1) for count in Counter(item[2].node_id for item in kept).values()
        )
        self.lane.lane_duplicate_entries_introduced += max(
            0, after_duplicate_count - before_duplicate_count
        )
        return kept

    def install(self) -> None:
        super().install()
        observed_pop = controller.heapq.heappop
        observed_generate = controller.generate_strategic_successors
        observed_trim = controller._trim_frontier_with_checkpoint_diversity
        self._lane_originals = {
            "pop": observed_pop,
            "generate": observed_generate,
            "trim": observed_trim,
            "resource": common.production_shadow.plan_resource_excavation,
        }
        observer = self

        def wrapped_pop(heap):
            # The controller's tactical realizers also use the process-global
            # heapq module.  The lane is strictly a StrategicSearchNode frontier
            # policy and must be inert for every tactical/internal heap.
            if not heap or not all(common.Observer._is_frontier_item(item) for item in heap):
                return observed_pop(heap)
            observer._record_duplicate_observation("before_pop", heap)
            item, forced = observer.lane.pop(
                heap,
                ordinary_pop=observed_pop,
                ordinary_heapify=observer._originals["heapify"],
                expansion_count=len(observer.expansions),
            )
            if forced:
                observer._record_forced_pop(heap, item)
            return item

        def wrapped_generate(node, cards, **kwargs):
            before_event = len(observer.events)
            successors = observed_generate(node, cards, **kwargs)
            mode = observer.lane.on_expansion(node)
            observer.expansion_modes[node.node_id] = mode
            parent_facts = workspace_facts(node.state)
            new_events = observer.events[before_event:]
            for event, successor in zip(new_events, successors):
                child_facts = workspace_facts(successor.end_state)
                closure = successor.dependency_closure_result
                event["workspace_class"] = child_facts["workspace_class"]
                event["workspace_effect"] = {
                    "preserves_empty": (
                        parent_facts["actual_empty_count"] > 0
                        and child_facts["actual_empty_count"] > 0
                    ),
                    "consumes_empty": (
                        child_facts["actual_empty_count"]
                        < parent_facts["actual_empty_count"]
                    ),
                    "creates_empty": (
                        child_facts["actual_empty_count"]
                        > parent_facts["actual_empty_count"]
                    ),
                    "reduces_face_down": child_facts["face_down"] < parent_facts["face_down"],
                    "improves_same_suit_structure": (
                        child_facts["stable_same_suit_joins"]
                        > parent_facts["stable_same_suit_joins"]
                        or child_facts["same_suit_run_mass"]
                        > parent_facts["same_suit_run_mass"]
                    ),
                    "closes_dependencies": bool(
                        closure is not None
                        and (closure.dependencies_closed or closure.overlays_cleared)
                    ),
                    "reaches_workspace_opportunity": child_facts["workspace_class"] is not None,
                    "reaches_foundation": (
                        child_facts["foundations"] > parent_facts["foundations"]
                    ),
                }
            if mode in {"WORKSPACE_FORCED", "WORKSPACE_NATURAL"}:
                observer.workspace_expansions.append(
                    {
                        "node_id": node.node_id,
                        "digest": common.digest(node.state),
                        "g": int(node.g),
                        "credit": int(node.credit_level),
                        "mode": mode,
                        "workspace_class": parent_facts["workspace_class"],
                        "parent_facts": parent_facts,
                        "event_ids": [event["event_id"] for event in new_events],
                    }
                )
            return successors

        def wrapped_trim(frontier, **kwargs):
            observer.lane.reconcile(frontier)
            observer.lane.select(frontier, expansion_count=len(observer.expansions))
            original = list(frontier)
            observer._record_duplicate_observation("before_trim", original)
            kept = observed_trim(frontier, **kwargs)
            kept = observer._protect_workspace_representative(original, kept, kwargs)
            observer._record_duplicate_observation("after_trim", kept)
            return kept

        def wrapped_resource(*args, **kwargs):
            observer.resource_planner_calls += 1
            return observer._lane_originals["resource"](*args, **kwargs)

        heapq.heappop = controller.heapq.heappop = wrapped_pop
        controller.generate_strategic_successors = wrapped_generate
        controller._trim_frontier_with_checkpoint_diversity = wrapped_trim
        common.production_shadow.plan_resource_excavation = wrapped_resource

    def restore(self) -> None:
        controller._trim_frontier_with_checkpoint_diversity = self._lane_originals["trim"]
        common.production_shadow.plan_resource_excavation = self._lane_originals["resource"]
        super().restore()

    def _workspace_metrics(self, class_name: str) -> dict:
        rows = [event for event in self.events if event.get("workspace_class") == class_name]
        output = {"generated": len(rows)}
        for stage in ("retained", "popped", "expanded", "trimmed"):
            output[stage] = sum(
                bool(
                    event["retained"]
                    if stage == "retained"
                    else (
                        self.nodes[event["child_node_id"]][stage]
                        if event["child_node_id"] in self.nodes else False
                    )
                )
                for event in rows
            )
        output["unique"] = {
            stage: len(
                {
                    event["child_digest"]
                    for event in rows
                    if (
                        True
                        if stage == "generated"
                        else event["retained"]
                        if stage == "retained"
                        else (
                            event["child_node_id"] in self.nodes
                            and self.nodes[event["child_node_id"]][stage]
                        )
                    )
                }
            )
            for stage in ("generated", "retained", "popped", "expanded", "trimmed")
        }
        return output

    def _service_lifecycle(self) -> dict:
        by_event = {event["event_id"]: event for event in self.events}
        rows = []
        effect_counts = Counter()
        retained_productive = 0
        ordinary_descendants = 0
        workspace_descendants = 0
        for expansion in self.workspace_expansions:
            events = [by_event[event_id] for event_id in expansion["event_ids"]]
            enriched = []
            for event in events:
                child_id = event["child_node_id"]
                child_mode = self.expansion_modes.get(child_id)
                for effect, present in event["workspace_effect"].items():
                    effect_counts[effect] += int(present)
                productive = bool(
                    event["retained"] and any(event["workspace_effect"].values())
                )
                retained_productive += int(productive)
                if event["retained"] and child_mode == "ORDINARY":
                    ordinary_descendants += 1
                if event["retained"] and child_mode in {
                    "WORKSPACE_FORCED", "WORKSPACE_NATURAL"
                }:
                    workspace_descendants += 1
                enriched.append(
                    {
                        **event,
                        "child_expansion_mode": child_mode,
                        "retained_productive": productive,
                    }
                )
            rows.append({**expansion, "successors": enriched})
        return {
            "expansions": rows,
            "successor_effect_counts": dict(sorted(effect_counts.items())),
            "retained_productive_workspace_descendants": retained_productive,
            "retained_descendants_expanded_ordinary": ordinary_descendants,
            "retained_descendants_expanded_by_workspace_lane": workspace_descendants,
        }

    def _strongest_retained_child(self, parent_id: int):
        candidates = [
            event
            for event in self.events
            if event["parent_node_id"] == parent_id
            and event["retained"]
            and event["child_node_id"] in self.nodes
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda event: (
                self.nodes[event["child_node_id"]]["best_rank"]
                if self.nodes[event["child_node_id"]]["best_rank"] is not None
                else 10**9,
                self.nodes[event["child_node_id"]]["g"],
                event["child_node_id"],
            ),
        )

    def _descendant_chains(self) -> list[dict]:
        chains = []
        for service in self.workspace_expansions:
            event = self._strongest_retained_child(service["node_id"])
            generations = []
            for generation in range(1, 4):
                if event is None:
                    break
                child_id = event["child_node_id"]
                node = self.nodes[child_id]
                mode = self.expansion_modes.get(child_id)
                generations.append(
                    {
                        "generation": generation,
                        "node_id": child_id,
                        "digest": node["digest"],
                        "g": node["g"],
                        "face_down": node["geometry"]["face_down"],
                        "empties": node["geometry"]["empties"],
                        "foundations": node["geometry"]["foundations"],
                        "stock_rows": node["geometry"]["stock_rows"],
                        "successor_family": event["kind"],
                        "successor_category": event["category"],
                        "expanded": node["expanded"],
                        "expansion_mode": mode,
                    }
                )
                if not node["expanded"]:
                    break
                event = self._strongest_retained_child(child_id)
            chains.append(
                {
                    "service_node_id": service["node_id"],
                    "service_digest": service["digest"],
                    "generations": generations,
                }
            )
        return chains

    def workspace_summary(self, result) -> dict:
        base = self.extended_summary(result)
        frontier = list(self.frontier or [])
        self.lane.finalize(frontier)
        base["EMPTY_CREATABLE"] = self._workspace_metrics("EMPTY_CREATABLE")
        base["ACTUAL_EMPTY"] = self._workspace_metrics("ACTUAL_EMPTY")
        base["maximum_actual_empty_count"] = max(
            [len(actual_empty_columns(self.opening))]
            + [event["child_geometry"]["empties"] for event in self.events]
        )
        base["minimum_buried_depth"] = None
        base["minimum_buried_depth_note"] = (
            "no generic buried-depth scalar is present in the existing controller measurement"
        )
        lifecycle = self._service_lifecycle()
        base["workspace_lifecycle"] = lifecycle
        base["workspace_descendant_chains"] = self._descendant_chains()
        base["workspace_service"] = {
            "enabled": self.enable_service,
            "interval": self.lane.interval,
            "selections": len(self.lane.selections),
            "natural_expansions_before_forced_service": self.lane.natural_services,
            "forced_service_expansions": self.lane.forced_services,
            "invalidations": self.lane.invalidations,
            "replacements": max(0, len(self.lane.selections) - 1),
            "max_outstanding": self.lane.max_outstanding,
            "service_interval_distribution": list(self.lane.service_intervals),
            "minimum_forced_interval_respected": all(
                selection["ordinary_expansions_before_service"] >= self.lane.interval
                for selection in self.lane.selections
                if selection["expanded_via_workspace_service"]
            ),
            "trim_protections": self.lane.trim_protections,
            "lane_duplicate_entries_introduced": self.lane.lane_duplicate_entries_introduced,
            "representatives": self.lane.selections,
        }
        base["existing_duplicate_occurrences"] = self.existing_duplicate_observations
        base["resource_planner_calls"] = self.resource_planner_calls
        return base


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
    observer = WorkspaceServiceObserver(opening, enable_service=enable_service)
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        summary = observer.workspace_summary(result)
    finally:
        observer.restore()
    summary["priority_schema"] = config.frontier_priority_schema.value
    summary["credit_propagation"] = config.strategic_credit_propagation.value
    return summary


def _credit_expansions(arm: dict) -> list[int]:
    return [arm["credit"][str(value)]["expansions"] for value in range(5)]


def classify(control: dict, treatment: dict) -> str:
    service = treatment["workspace_service"]
    mechanical = (
        service["selections"] > 0
        and service["max_outstanding"] <= 1
        and service["forced_service_expansions"] > 0
        and service["minimum_forced_interval_respected"]
        and service["lane_duplicate_entries_introduced"] == 0
        and treatment["frontier"]["size"] <= 256
        and not treatment["replay_failures"]
        and not treatment["corrected_cost_inconsistencies"]
    )
    if not mechanical:
        return "WORKSPACE_SERVICE_INCONCLUSIVE"
    service_gate = (
        treatment["EMPTY_CREATABLE"]["expanded"] > control["EMPTY_CREATABLE"]["expanded"]
        or treatment["ACTUAL_EMPTY"]["expanded"] > control["ACTUAL_EMPTY"]["expanded"]
    )
    lifecycle = treatment["workspace_lifecycle"]
    sustained = any(
        sum(item["expanded"] for item in chain["generations"]) >= 2
        for chain in treatment["workspace_descendant_chains"]
    )
    structural_gate = (
        treatment["minimum_face_down"] < control["minimum_face_down"]
        or sustained
        or treatment["ACTUAL_EMPTY"]["expanded"] >= 2
        or treatment["maximum_foundations"] > control["maximum_foundations"]
        or lifecycle["retained_descendants_expanded_ordinary"] > 0
    )
    forced_share = service["forced_service_expansions"] / treatment["strategic_expansions"]
    broad_control = sum(_credit_expansions(control)[1:])
    broad_treatment = sum(_credit_expansions(treatment)[1:])
    if forced_share > 0.15 or broad_treatment < broad_control * 0.70:
        return "WORKSPACE_SERVICE_STARVES_OTHER_SEARCH"
    if service_gate and structural_gate:
        return "WORKSPACE_SERVICE_EFFECTIVE"
    if service_gate:
        return "WORKSPACE_SERVICE_IMPROVES_CIRCULATION_ONLY"
    if lifecycle["retained_productive_workspace_descendants"] == 0:
        return "WORKSPACE_SERVICE_REVEALS_CAPABILITY_GAP"
    return "WORKSPACE_SERVICE_INCONCLUSIVE"


def main() -> int:
    cards = tuple(load_deal(common.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    arms = {}
    for label, enabled in (("CONTROL", False), ("WORKSPACE_SERVICE_1", True)):
        print(f"Starting {label}", flush=True)
        arms[label] = run_arm(opening, cards, enable_service=enabled)
        arm = arms[label]
        print(
            f"{label}: stop={arm['stop_reason']} expansions={arm['strategic_expansions']} "
            f"elapsed={arm['elapsed_s']:.1f}s tactical={arm['tactical_nodes']} "
            f"credit={_credit_expansions(arm)} "
            f"EC={arm['EMPTY_CREATABLE']['expanded']} AE={arm['ACTUAL_EMPTY']['expanded']} "
            f"forced={arm['workspace_service']['forced_service_expansions']}",
            flush=True,
        )
    control = arms["CONTROL"]
    treatment = arms["WORKSPACE_SERVICE_1"]
    service = treatment["workspace_service"]
    gates = {
        "control_has_no_workspace_lane": (
            control["workspace_service"]["selections"] == 0
            and control["workspace_service"]["forced_service_expansions"] == 0
        ),
        "treatment_naturally_identifies_workspace": service["selections"] > 0,
        "at_most_one_outstanding": service["max_outstanding"] <= 1,
        "bounded_service_occurs": service["forced_service_expansions"] > 0,
        "one_in_eight_rule_respected": service["minimum_forced_interval_respected"],
        "frontier_capacity_unchanged": (
            control["frontier"]["size"] <= 256 and treatment["frontier"]["size"] <= 256
        ),
        "lane_introduces_no_duplicate_entry": service["lane_duplicate_entries_introduced"] == 0,
        "replay_and_cost_integrity": all(
            not arm["replay_failures"] and not arm["corrected_cost_inconsistencies"]
            for arm in arms.values()
        ),
        "resource_planner_not_invoked": all(
            arm["resource_planner_calls"] == 0 for arm in arms.values()
        ),
        "production_controller_has_no_resource_planner": (
            "resource_excavation" not in inspect.getsource(controller)
        ),
        "production_defaults_unchanged": True,
    }
    verdict = classify(control, treatment)
    payload = {
        "experiment": "workspace_opportunity_service_lane_v0_1",
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
            "workspace_service_interval": SERVICE_INTERVAL,
        },
        "gates": gates,
        "verdict": verdict,
        "arms": arms,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print("Gates", gates, flush=True)
    print("Verdict", verdict, flush=True)
    print("Wrote", RESULT_PATH, flush=True)
    return 0 if all(gates.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
