#!/usr/bin/env python3
"""Fresh two-arm lag-1 workspace grace-lease experiment v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from collections import Counter, defaultdict, deque
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as common
import spider.planner.anytime_controller as controller
import state_local_credit_semantics_v0_1 as state_local
import workspace_opportunity_service_lane_v0_1 as service
import workspace_service_generalisation_panel_v0_1 as general
import workspace_service_stock_synchronous_v0_1 as synchronous
from spider.engine import SpiderState
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)


BASE_SHA = "3fb9d2825aa4aea977fb9b8e26c6db3607787e52"
EXPERIMENT_ID = "workspace_service_lag1_grace_v0_1"
PLAN_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}_plan.json"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT_ID
ACTIVE_DEALS = ("P0", "P2", "P4", "P7")
UNGUARDED = "N8_UNGUARDED"
GRACE = "LAG1_GRACE_LEASE"
ARMS = (UNGUARDED, GRACE)
RUN_SCHEDULE = {
    "P0": (UNGUARDED, GRACE),
    "P2": (GRACE, UNGUARDED),
    "P4": (UNGUARDED, GRACE),
    "P7": (GRACE, UNGUARDED),
}
CONFIG = dict(general.CONFIG)
HISTORICAL_CONTEXT = synchronous.HISTORICAL_CONTEXT


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def arm_order(panel_entry: str) -> tuple[str, str]:
    try:
        return RUN_SCHEDULE[panel_entry]
    except KeyError as exc:
        raise ValueError("panel entry must be one of P0/P2/P4/P7") from exc


def active_definition() -> dict:
    return synchronous.active_definition()


def ordinary_live_frontier_items(frontier, lane) -> tuple:
    return synchronous.ordinary_live_frontier_items(frontier, lane)


def stock_rows(state) -> int:
    return synchronous.stock_rows(state)


def workspace_candidate_snapshot(frontier, lane) -> dict:
    ordinary = ordinary_live_frontier_items(frontier, lane)
    if not ordinary:
        return {
            "best_live_stock_rows": None,
            "ordinary_items": (),
            "workspace_candidates": (),
            "lag_counts": {"lag0": 0, "lag1": 0, "lag2_plus": 0},
        }
    best_rows = min(stock_rows(item[2].state) for item in ordinary)
    candidates = tuple(
        sorted(
            (
                item
                for item in ordinary
                if service.workspace_class(item[2].state) is not None
            ),
            key=lambda item: (item[0], item[2].node_id),
        )
    )
    lags = [stock_rows(item[2].state) - best_rows for item in candidates]
    return {
        "best_live_stock_rows": best_rows,
        "ordinary_items": ordinary,
        "workspace_candidates": candidates,
        "lag_counts": {
            "lag0": sum(lag == 0 for lag in lags),
            "lag1": sum(lag == 1 for lag in lags),
            "lag2_plus": sum(lag >= 2 for lag in lags),
        },
    }


class Lag1GraceWorkspaceServiceLane(service.WorkspaceServiceLane):
    """N8 lane with instrumentation and an optional one-shot lag-1 epoch lease."""

    def __init__(self, *, mode: str) -> None:
        if mode not in ARMS:
            raise ValueError(f"unknown arm {mode}")
        super().__init__(enabled=True, interval=service.SERVICE_INTERVAL)
        self.mode = mode
        self.lag1_grace_spent_epochs: set[int] = set()
        self.reservations_released = 0
        self.release_events: list[dict] = []
        self.scheduled_opportunities: list[dict] = []
        self.service_events: list[dict] = []
        self.epoch_observations: list[dict] = []
        self._pending_policy_event: dict | None = None
        self._last_expansion_count = 0
        self._completed_expansions = 0

    def _record_epoch(self, frontier, expansion_count: int) -> dict:
        snapshot = workspace_candidate_snapshot(frontier, self)
        best_rows = snapshot["best_live_stock_rows"]
        if best_rows is not None:
            observation = {
                "after_completed_expansions": expansion_count,
                "best_live_stock_rows": best_rows,
            }
            if not self.epoch_observations or self.epoch_observations[-1] != observation:
                self.epoch_observations.append(observation)
        return snapshot

    def _selection_record(self, selected, candidates, frontier, expansion_count: int) -> dict:
        ordered = sorted(frontier)
        rank_by_id = {
            item[2].node_id: rank
            for rank, item in enumerate(ordered, start=1)
            if common.Observer._is_frontier_item(item)
        }
        node = selected[2]
        facts = service.workspace_facts(node.state)
        snapshot = workspace_candidate_snapshot(frontier, self)
        best_rows = snapshot["best_live_stock_rows"]
        actual_lag = stock_rows(node.state) - best_rows
        return {
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
            "best_live_stock_rows_at_selection": best_rows,
            "stock_lag_at_selection": actual_lag,
            "lag1_lease_available_at_selection": (
                actual_lag == 1 and best_rows not in self.lag1_grace_spent_epochs
            ),
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

    def _reserve(self, selected, candidates, frontier, expansion_count: int):
        record = self._selection_record(selected, candidates, frontier, expansion_count)
        self.selections.append(record)
        self.current_node_id = selected[2].node_id
        self.current_item = selected
        self.current_selection = record
        self.max_outstanding = max(self.max_outstanding, 1)
        return selected

    def _release(self, *, reason: str, expansion_count: int, snapshot: dict | None = None) -> None:
        if self.current_item is None or self.current_selection is None:
            return
        node = self.current_item[2]
        snapshot = snapshot or {
            "best_live_stock_rows": None,
            "lag_counts": {"lag0": 0, "lag1": 0, "lag2_plus": 0},
        }
        best_rows = snapshot["best_live_stock_rows"]
        lag = None if best_rows is None else stock_rows(node.state) - best_rows
        event = {
            "release_index": len(self.release_events),
            "after_completed_expansions": expansion_count,
            "reason": reason,
            "selection_index": self.current_selection["selection_index"],
            "node_id": node.node_id,
            "digest": common.digest(node.state),
            "g": int(node.g),
            "credit": int(node.credit_level),
            "workspace_class": service.workspace_class(node.state),
            "representative_stock_rows": stock_rows(node.state),
            "best_live_stock_rows": best_rows,
            "actual_lag": lag,
            "frontier_node_left_unchanged": True,
        }
        self.release_events.append(event)
        self.reservations_released += 1
        self.current_selection.update(
            outcome="RELEASED_INELIGIBLE",
            released_after_expansions=expansion_count,
            release_reason=reason,
            release_lag=lag,
        )
        self.current_node_id = None
        self.current_item = None
        self.current_selection = None
        self.pending_pop = None

    def reconcile(self, frontier) -> None:
        if self.mode == UNGUARDED:
            return super().reconcile(frontier)
        if self.current_node_id is None:
            return
        if self.pending_pop is not None:
            self._release(
                reason="PENDING_POP_DID_NOT_EXPAND",
                expansion_count=self._last_expansion_count,
            )
            return
        matches = self._matches(frontier)
        if not matches:
            self._release(
                reason="STALE_OR_NONLIVE",
                expansion_count=self._last_expansion_count,
            )
            return
        qualified = [
            item
            for item in matches
            if service.workspace_class(item[2].state) is not None
            and service.expansion_identity(item[2]) not in self.expanded_state_credits
        ]
        if not qualified:
            self.current_item = min(matches, key=lambda item: (item[0], item[2].node_id))
            self._release(
                reason="STRUCTURAL_OR_EXPANSION_INELIGIBLE",
                expansion_count=self._last_expansion_count,
            )
            return
        self.current_item = min(qualified, key=lambda item: (item[0], item[2].node_id))

    def _eligible(self, item, best_rows: int) -> bool:
        lag = stock_rows(item[2].state) - best_rows
        return lag == 0 or (
            lag == 1 and best_rows not in self.lag1_grace_spent_epochs
        )

    def select(self, frontier, *, expansion_count: int):
        self._last_expansion_count = expansion_count
        if self.mode == UNGUARDED:
            before = len(self.selections)
            selected = super().select(frontier, expansion_count=expansion_count)
            if selected is not None and len(self.selections) > before:
                snapshot = workspace_candidate_snapshot(frontier, self)
                best_rows = snapshot["best_live_stock_rows"]
                self.current_selection.update(
                    best_live_stock_rows_at_selection=best_rows,
                    stock_lag_at_selection=stock_rows(selected[2].state) - best_rows,
                    lag1_lease_available_at_selection=None,
                )
            return selected

        snapshot = self._record_epoch(frontier, expansion_count)
        best_rows = snapshot["best_live_stock_rows"]
        if self.current_item is not None and self.current_selection is not None:
            if best_rows is None:
                self._release(
                    reason="NO_LIVE_ORDINARY_REFERENCE",
                    expansion_count=expansion_count,
                    snapshot=snapshot,
                )
            else:
                lag = stock_rows(self.current_item[2].state) - best_rows
                if lag >= 2:
                    self._release(
                        reason="LAG_2_PLUS",
                        expansion_count=expansion_count,
                        snapshot=snapshot,
                    )
                elif lag == 1 and best_rows in self.lag1_grace_spent_epochs:
                    self._release(
                        reason="LAG1_EPOCH_LEASE_SPENT",
                        expansion_count=expansion_count,
                        snapshot=snapshot,
                    )
                else:
                    return self.current_item

        if best_rows is None:
            return None
        candidates = tuple(
            item
            for item in snapshot["workspace_candidates"]
            if self._eligible(item, best_rows)
        )
        if not candidates:
            return None
        selected = min(candidates, key=lambda item: (item[0], item[2].node_id))
        return self._reserve(selected, candidates, frontier, expansion_count)

    def _opportunity(self, frontier, expansion_count: int, snapshot: dict) -> dict:
        best_rows = snapshot["best_live_stock_rows"]
        node = self.current_item[2] if self.current_item is not None else None
        actual_lag = None if node is None or best_rows is None else stock_rows(node.state) - best_rows
        if node is None:
            decision = "NO_ELIGIBLE_REPRESENTATIVE"
        elif self.mode == GRACE and actual_lag == 1:
            decision = "FORCE_LAG1_GRACE"
        elif actual_lag == 0:
            decision = "FORCE_LAG0"
        elif actual_lag == 1:
            decision = "FORCE_LAG1_UNGUARDED"
        else:
            decision = "FORCE_LAG2_PLUS_UNGUARDED"
        facts = service.workspace_facts(node.state) if node is not None else None
        event = {
            "opportunity_index": len(self.scheduled_opportunities),
            "after_completed_expansions": expansion_count,
            "strategic_expansion_number": expansion_count + 1,
            "stock_epoch": best_rows,
            "lag0_candidate_count": snapshot["lag_counts"]["lag0"],
            "lag1_candidate_count": snapshot["lag_counts"]["lag1"],
            "lag2_plus_candidate_count": snapshot["lag_counts"]["lag2_plus"],
            "lag1_lease_available": (
                best_rows is not None and best_rows not in self.lag1_grace_spent_epochs
            ),
            "lag1_lease_spent_before": best_rows in self.lag1_grace_spent_epochs if best_rows is not None else False,
            "decision": decision,
            "representative_node_id": node.node_id if node is not None else None,
            "representative_selection_index": (
                self.current_selection["selection_index"] if self.current_selection else None
            ),
            "representative_class": facts["workspace_class"] if facts else None,
            "representative_digest": common.digest(node.state) if node else None,
            "representative_g": int(node.g) if node else None,
            "representative_credit": int(node.credit_level) if node else None,
            "representative_stock_rows": stock_rows(node.state) if node else None,
            "representative_foundations": facts["foundations"] if facts else None,
            "actual_lag": actual_lag,
            "forced_service_completed": False,
            "lease_consumed": False,
        }
        self.scheduled_opportunities.append(event)
        return event

    def pop(self, frontier, *, ordinary_pop, ordinary_heapify, expansion_count: int):
        self._last_expansion_count = expansion_count
        self.reconcile(frontier)
        self.select(frontier, expansion_count=expansion_count)
        snapshot = self._record_epoch(frontier, expansion_count)
        due = self.ordinary_expansions_since_service >= self.interval

        if due and (self.mode == GRACE or self.current_item is not None):
            opportunity = self._opportunity(frontier, expansion_count, snapshot)
            if self.current_item is None:
                # A missed service window is spent, not banked for a catch-up burst.
                self.ordinary_expansions_since_service = 0
                item = ordinary_pop(frontier)
                return item, False
        else:
            opportunity = None

        before_id = self.current_node_id
        before_lag = None
        best_rows = snapshot["best_live_stock_rows"]
        if self.current_item is not None and best_rows is not None:
            before_lag = stock_rows(self.current_item[2].state) - best_rows
        item, forced = super().pop(
            frontier,
            ordinary_pop=ordinary_pop,
            ordinary_heapify=ordinary_heapify,
            expansion_count=expansion_count,
        )
        if forced:
            if opportunity is None:
                raise AssertionError("forced service lacked a scheduled opportunity")
            policy_event = {
                "service_index": len(self.service_events),
                "mode": "FORCED",
                **opportunity,
                "node_id": item[2].node_id,
                "expanded_after_expansions": None,
                "successor_count": None,
                "productive_successors_retained": None,
                "productive_successors_later_ordinary": None,
                "productive_successors_later_workspace": None,
                "grace_descendant_lifecycle": None,
                "stock_epoch_subsequently_advances": None,
                "expansions_until_next_stock_epoch": None,
                "stock_progress_censored": None,
            }
            self.service_events.append(policy_event)
            self._pending_policy_event = policy_event
        elif before_id is not None and item[2].node_id == before_id:
            natural_event = {
                "service_index": len(self.service_events),
                "mode": "NATURAL",
                "after_completed_expansions": expansion_count,
                "stock_epoch": best_rows,
                "actual_lag": before_lag,
                "node_id": item[2].node_id,
                "representative_digest": common.digest(item[2].state),
                "representative_class": service.workspace_class(item[2].state),
                "representative_g": int(item[2].g),
                "representative_credit": int(item[2].credit_level),
                "representative_stock_rows": stock_rows(item[2].state),
                "lease_consumed": False,
                "expanded_after_expansions": None,
            }
            self.service_events.append(natural_event)
            self._pending_policy_event = natural_event
        return item, forced

    def on_expansion(self, node) -> str:
        event = self._pending_policy_event
        mode = super().on_expansion(node)
        self._completed_expansions = max(
            self._completed_expansions, self._last_expansion_count + 1
        )
        if event is not None and event["node_id"] == node.node_id:
            event["expanded_after_expansions"] = self._last_expansion_count + 1
            if mode == "WORKSPACE_FORCED":
                event["forced_service_completed"] = True
                if self.mode == GRACE and event["actual_lag"] == 1:
                    epoch = event["stock_epoch"]
                    if epoch in self.lag1_grace_spent_epochs:
                        raise AssertionError("second lag-1 force in an already-spent epoch")
                    self.lag1_grace_spent_epochs.add(epoch)
                    event["lease_consumed"] = True
            self._pending_policy_event = None
        return mode

    def resolve_policy_outcomes(self, node_records: dict, expansion_modes: dict) -> None:
        del node_records, expansion_modes
        observations = sorted(
            self.epoch_observations,
            key=lambda row: row["after_completed_expansions"],
        )
        for event in self.service_events:
            if event.get("mode") != "FORCED" or event.get("actual_lag") != 1:
                continue
            epoch = event["stock_epoch"]
            expanded_at = event["expanded_after_expansions"]
            next_epoch = next(
                (
                    row
                    for row in observations
                    if row["after_completed_expansions"] >= expanded_at
                    and row["best_live_stock_rows"] < epoch
                ),
                None,
            )
            event["stock_epoch_subsequently_advances"] = next_epoch is not None
            event["expansions_until_next_stock_epoch"] = (
                next_epoch["after_completed_expansions"] - expanded_at
                if next_epoch is not None
                else None
            )
            event["stock_progress_censored"] = next_epoch is None

    def enrich_grace_lifecycle(self, observer, lifecycle: dict) -> None:
        expansions = {row["node_id"]: row for row in lifecycle["expansions"]}
        events_by_parent: dict[int, list[dict]] = defaultdict(list)
        for edge in observer.events:
            events_by_parent[edge["parent_node_id"]].append(edge)
        for event in self.service_events:
            if event.get("mode") != "FORCED":
                continue
            expansion = expansions.get(event["node_id"], {"successors": []})
            direct = expansion["successors"]
            productive = [row for row in direct if row["retained_productive"]]
            event["successor_count"] = len(direct)
            event["productive_successors_retained"] = len(productive)
            event["productive_successors_later_ordinary"] = sum(
                row["child_expansion_mode"] == "ORDINARY" for row in productive
            )
            event["productive_successors_later_workspace"] = sum(
                row["child_expansion_mode"] in {"WORKSPACE_FORCED", "WORKSPACE_NATURAL"}
                for row in productive
            )
            if event.get("actual_lag") != 1:
                continue
            root = event["node_id"]
            queue = deque([row["child_node_id"] for row in productive])
            visited: set[int] = set()
            reachable_edges: list[dict] = []
            while queue:
                node_id = queue.popleft()
                if node_id in visited:
                    continue
                visited.add(node_id)
                for edge in events_by_parent.get(node_id, []):
                    if not edge.get("retained"):
                        continue
                    reachable_edges.append(edge)
                    queue.append(edge["child_node_id"])
            root_face_down = expansion.get("parent_facts", {}).get("face_down")
            root_stock = event["representative_stock_rows"]
            geometries = [
                observer.nodes[node_id]["geometry"]
                for node_id in visited
                if node_id in observer.nodes
            ]
            all_edges = productive + reachable_edges
            event["grace_descendant_lifecycle"] = {
                "reachable_retained_descendant_nodes": len(visited),
                "descendants_expanded_ordinary": sum(
                    observer.expansion_modes.get(node_id) == "ORDINARY"
                    for node_id in visited
                ),
                "descendants_expanded_workspace": sum(
                    observer.expansion_modes.get(node_id)
                    in {"WORKSPACE_FORCED", "WORKSPACE_NATURAL"}
                    for node_id in visited
                ),
                "creates_or_preserves_empty": any(
                    edge.get("workspace_effect", {}).get("creates_empty")
                    or edge.get("workspace_effect", {}).get("preserves_empty")
                    for edge in all_edges
                ),
                "minimum_face_down": min(
                    (geometry["face_down"] for geometry in geometries),
                    default=root_face_down,
                ),
                "face_down_reduction": (
                    root_face_down
                    - min(
                        (geometry["face_down"] for geometry in geometries),
                        default=root_face_down,
                    )
                    if root_face_down is not None
                    else None
                ),
                "same_suit_progress": any(
                    edge.get("workspace_effect", {}).get("improves_same_suit_structure")
                    for edge in all_edges
                ),
                "campaign_or_dependency_progress": any(
                    edge.get("workspace_effect", {}).get("closes_dependencies")
                    for edge in all_edges
                ),
                "stock_transition": any(
                    geometry["stock_rows"] < root_stock for geometry in geometries
                ),
                "foundation_progress": any(
                    geometry["foundations"] > event.get("representative_foundations", 0)
                    for geometry in geometries
                ),
            }

    def policy_summary(self) -> dict:
        epochs: dict[int, dict] = {}
        all_epoch_values = {
            row["best_live_stock_rows"] for row in self.epoch_observations
        } | {
            row["stock_epoch"]
            for row in self.scheduled_opportunities
            if row["stock_epoch"] is not None
        }
        for epoch in sorted(all_epoch_values, reverse=True):
            opportunities = [
                row for row in self.scheduled_opportunities if row["stock_epoch"] == epoch
            ]
            services = [
                row for row in self.service_events if row.get("stock_epoch") == epoch
            ]
            epochs[str(epoch)] = {
                "stock_epoch": epoch,
                "scheduled_service_opportunities": len(opportunities),
                "candidate_occurrences": {
                    "lag0": sum(row["lag0_candidate_count"] for row in opportunities),
                    "lag1": sum(row["lag1_candidate_count"] for row in opportunities),
                    "lag2_plus": sum(row["lag2_plus_candidate_count"] for row in opportunities),
                },
                "maximum_candidates_at_one_opportunity": {
                    "lag0": max((row["lag0_candidate_count"] for row in opportunities), default=0),
                    "lag1": max((row["lag1_candidate_count"] for row in opportunities), default=0),
                    "lag2_plus": max((row["lag2_plus_candidate_count"] for row in opportunities), default=0),
                },
                "lag1_lease_spent": epoch in self.lag1_grace_spent_epochs,
                "forced_lag0_services": sum(
                    row.get("mode") == "FORCED" and row.get("actual_lag") == 0
                    for row in services
                ),
                "forced_lag1_services": sum(
                    row.get("mode") == "FORCED" and row.get("actual_lag") == 1
                    for row in services
                ),
                "forced_lag2_plus_services": sum(
                    row.get("mode") == "FORCED" and row.get("actual_lag", 0) >= 2
                    for row in services
                ),
                "natural_workspace_services": sum(row.get("mode") == "NATURAL" for row in services),
                "representative_selection_indices": sorted(
                    {
                        row["representative_selection_index"]
                        for row in opportunities
                        if row["representative_selection_index"] is not None
                    }
                ),
                "stock_epoch_subsequently_advances": any(
                    row["best_live_stock_rows"] < epoch
                    for row in self.epoch_observations
                ),
            }
        return {
            "mode": self.mode,
            "interval": self.interval,
            "lag1_grace_spent_epochs": sorted(self.lag1_grace_spent_epochs, reverse=True),
            "lag1_grace_spent_epoch_count": len(self.lag1_grace_spent_epochs),
            "forced_lag0_services": sum(
                row.get("mode") == "FORCED" and row.get("actual_lag") == 0
                for row in self.service_events
            ),
            "forced_lag1_services": sum(
                row.get("mode") == "FORCED" and row.get("actual_lag") == 1
                for row in self.service_events
            ),
            "forced_lag2_plus_services": sum(
                row.get("mode") == "FORCED" and row.get("actual_lag", 0) >= 2
                for row in self.service_events
            ),
            "natural_lagging_workspace_services": sum(
                row.get("mode") == "NATURAL" and row.get("actual_lag", 0) >= 1
                for row in self.service_events
            ),
            "reservations_released": self.reservations_released,
            "release_events": self.release_events,
            "scheduled_opportunities": self.scheduled_opportunities,
            "service_events": self.service_events,
            "epochs": epochs,
            "no_hold_style_ineligible_ownership": all(
                event["reason"] != "HELD_INELIGIBLE"
                for event in self.release_events
            ),
        }


class Lag1GracePanelObserver(synchronous.StockSynchronousPanelObserver):
    def __init__(self, opening: SpiderState, *, mode: str) -> None:
        super().__init__(opening, mode=synchronous.UNGUARDED)
        self.lane = Lag1GraceWorkspaceServiceLane(mode=mode)

    def workspace_summary(self, result) -> dict:
        output = super().workspace_summary(result)
        output.pop("stock_synchronous_policy", None)
        self.lane.enrich_grace_lifecycle(self, output["workspace_lifecycle"])
        output["lag1_grace_policy"] = self.lane.policy_summary()
        return output


def run_arm(cards: tuple, *, mode: str) -> dict:
    random.seed(CONFIG["controller_seed"])
    config = common.production_shadow._production_config(
        seconds=CONFIG["wall_clock_limit_s"],
        expansions=CONFIG["max_strategic_expansions"],
        nodes=CONFIG["max_tactical_nodes"],
    )
    config = replace(
        config,
        frontier_priority_schema=FrontierPrioritySchema.COMMON_STAGE0,
        strategic_credit_propagation=StrategicCreditPropagation.STATE_LOCAL,
    )
    state_local.assert_config(config)
    opening = SpiderState.from_cards(list(cards))
    observer = Lag1GracePanelObserver(opening, mode=mode)
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        full = observer.workspace_summary(result)
        final_duplicate_node_ids = sorted(
            observer._duplicate_ids(observer.frontier or []).keys()
        )
    finally:
        observer.restore()
    full["priority_schema"] = config.frontier_priority_schema.value
    full["credit_propagation"] = config.strategic_credit_propagation.value
    compact = general.compact_arm(
        full,
        opening,
        result,
        final_duplicate_node_ids=final_duplicate_node_ids,
    )
    compact["lag1_grace_policy"] = full["lag1_grace_policy"]
    compact["structural_progress"] = full["structural_progress"]
    return compact


def frozen_plan() -> dict:
    definition = active_definition()
    return {
        "experiment": EXPERIMENT_ID,
        "status": "FROZEN_PRE_RUN",
        "base_sha": BASE_SHA,
        "panel_definition_path": synchronous.panel.PANEL_PATH.relative_to(ROOT).as_posix(),
        "active_deals": list(ACTIVE_DEALS),
        "panel_fixture_sha256": {
            entry["panel_entry"]: entry["fixture_sha256"]
            for entry in definition["entries"]
        },
        "opening_digests": {
            entry["panel_entry"]: entry["opening_digest"]
            for entry in definition["entries"]
        },
        "config": CONFIG,
        "arms": list(ARMS),
        "run_schedule": {deal: list(order) for deal, order in RUN_SCHEDULE.items()},
        "lease_semantics": {
            "stock_epoch": "minimum stock rows among unique live non-stale ordinary frontier entries",
            "lag0": "normally eligible; does not consume grace",
            "lag1": "eligible only when the integer stock epoch has never spent grace",
            "lag2_plus": "not forced-service eligible",
            "consumption": "only an actual forced lag-1 expansion permanently spends that integer epoch",
            "natural_expansion": "unrestricted and never consumes grace",
            "release": "release only lane ownership when reserved state becomes ineligible; frontier entry is untouched",
            "missed_window": "reset N8 counter and continue ordinary search; no catch-up entitlement",
        },
        "historical_context": HISTORICAL_CONTEXT,
        "classification_rule": {
            "P2_P7_BALANCED_IMPROVEMENT": "B stock < A stock and B face-down <= historical no-workspace face-down",
            "P2_P7_LOCAL_GAIN_PRESERVED": "B stock >= A stock, B face-down < historical no-workspace face-down, and B uses fewer forced lag-1 services than A",
            "P2_P7_OVER_SUPPRESSED": "B productive workspace descendants <=25% of A and B face-down >= historical no-workspace face-down",
            "P2_P7_STILL_STALLED": "B stock is no more than one row better than A after at least one B lag-1 grace service",
            "P0_P4_BALANCED_IMPROVEMENT": "B stock < A stock with face-down <= A+1, or B face-down < A with stock <= A",
            "P0_P4_LOCAL_GAIN_PRESERVED": "B ties or improves both endpoints, retains productive workspace descendants, and uses fewer forced services",
            "NEUTRAL": "all remaining paired outcomes",
            "evaluation_order": [
                "BALANCED_IMPROVEMENT",
                "LOCAL_GAIN_PRESERVED",
                "OVER_SUPPRESSED",
                "STILL_STALLED",
                "NEUTRAL",
            ],
        },
        "verdict_rule": {
            "LAG1_GRACE_EFFECTIVE": "on both P2 and P7 B improves stock, remains below the historical no-workspace face-down reference, performs forced lag-1 service, and retains productive workspace circulation",
            "LAG1_GRACE_TOO_RESTRICTIVE": "on both P2 and P7 B retains <=25% of A productive workspace descendants and loses the historical local advantage",
            "LAG1_GRACE_STILL_OVERINVESTS": "on both P2 and P7 B spends grace but improves stock by at most one row",
            "LAG1_GRACE_INERT": "B performs no forced lag-1 grace service, or all four paired endpoints and workspace expansion counts equal A",
            "LAG1_GRACE_MIXED": "all other valid completed outcomes",
            "evaluation_order": [
                "INCONCLUSIVE",
                "LAG1_GRACE_EFFECTIVE",
                "LAG1_GRACE_TOO_RESTRICTIVE",
                "LAG1_GRACE_STILL_OVERINVESTS",
                "LAG1_GRACE_INERT",
                "LAG1_GRACE_MIXED",
            ],
        },
    }


def write_frozen_plan() -> dict:
    plan = frozen_plan()
    rendered = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    if PLAN_PATH.exists() and PLAN_PATH.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to replace frozen plan {PLAN_PATH}")
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    return plan


def _config_fingerprint() -> str:
    payload = {
        "config": CONFIG,
        "run_schedule": {deal: list(order) for deal, order in RUN_SCHEDULE.items()},
        "lease_semantics": frozen_plan()["lease_semantics"],
        "classification_rule": frozen_plan()["classification_rule"],
        "verdict_rule": frozen_plan()["verdict_rule"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _checkpoint_path(panel_entry: str, arm: str) -> Path:
    return CHECKPOINT_DIR / f"{panel_entry}_{arm.lower()}.json"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _load_checkpoint(entry: dict, arm: str) -> dict | None:
    path = _checkpoint_path(entry["panel_entry"], arm)
    if not path.exists():
        return None
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "experiment": EXPERIMENT_ID,
        "panel_entry": entry["panel_entry"],
        "opening_digest": entry["opening_digest"],
        "arm": arm,
        "config_fingerprint": _config_fingerprint(),
    }
    if {key: checkpoint.get(key) for key in expected} != expected:
        raise RuntimeError(f"incompatible checkpoint {path}")
    return checkpoint


def execute_missing_runs(
    definition: dict, *, stop_after_deals: int | None = None
) -> dict:
    runs: dict[str, dict] = {}
    completed_deals = 0
    for entry in definition["entries"]:
        deal = entry["panel_entry"]
        cards = general.load_entry_cards(entry)
        left = SpiderState.from_cards(list(cards))
        right = SpiderState.from_cards(list(cards))
        if (
            common.digest(left) != common.digest(right)
            or common.digest(left) != entry["opening_digest"]
        ):
            raise RuntimeError(f"initial-state mismatch for {deal}")
        runs[deal] = {}
        for order_index, arm in enumerate(arm_order(deal), start=1):
            checkpoint = _load_checkpoint(entry, arm)
            if checkpoint is None:
                print(
                    f"START {deal} {arm} order={order_index}/2 at {utc_now()}",
                    flush=True,
                )
                started = utc_now()
                summary = run_arm(cards, mode=arm)
                checkpoint = {
                    "experiment": EXPERIMENT_ID,
                    "panel_entry": deal,
                    "opening_digest": entry["opening_digest"],
                    "arm": arm,
                    "run_order_index": order_index,
                    "config_fingerprint": _config_fingerprint(),
                    "started_utc": started,
                    "completed_utc": utc_now(),
                    "summary": summary,
                }
                _write_json_atomic(_checkpoint_path(deal, arm), checkpoint)
                policy = summary["lag1_grace_policy"]
                print(
                    f"DONE {deal} {arm}: exp={summary['strategic_expansions']} "
                    f"fd={summary['minimum_face_down']} "
                    f"stock={summary['minimum_expanded_stock_rows']} "
                    f"lag0={policy['forced_lag0_services']} "
                    f"lag1={policy['forced_lag1_services']} "
                    f"spent={policy['lag1_grace_spent_epoch_count']} "
                    f"released={policy['reservations_released']} "
                    f"productive={summary['workspace']['productive_descendants_retained']} "
                    f"ordinary={summary['workspace']['productive_descendants_ordinary_serviced']} "
                    f"tactical={summary['tactical_nodes']} elapsed={summary['elapsed_s']:.1f}s",
                    flush=True,
                )
            else:
                print(f"RESUME {deal} {arm} from checkpoint", flush=True)
            runs[deal][arm] = checkpoint["summary"]
        completed_deals += 1
        if stop_after_deals is not None and completed_deals >= stop_after_deals:
            break
    return runs


def _workspace_expansions(summary: dict) -> int:
    return summary["EMPTY_CREATABLE"]["expanded"] + summary["ACTUAL_EMPTY"]["expanded"]


def classify_deal(deal: str, baseline: dict, treatment: dict) -> str:
    a_fd = baseline["minimum_face_down"]
    b_fd = treatment["minimum_face_down"]
    a_stock = baseline["minimum_expanded_stock_rows"]
    b_stock = treatment["minimum_expanded_stock_rows"]
    if deal in {"P2", "P7"}:
        historical_fd = HISTORICAL_CONTEXT[deal]["NO_WORKSPACE"]["minimum_face_down"]
        if b_stock < a_stock and b_fd <= historical_fd:
            return "BALANCED_IMPROVEMENT"
        if (
            b_stock >= a_stock
            and b_fd < historical_fd
            and treatment["lag1_grace_policy"]["forced_lag1_services"]
            < baseline["lag1_grace_policy"]["forced_lag1_services"]
        ):
            return "LOCAL_GAIN_PRESERVED"
        if (
            treatment["workspace"]["productive_descendants_retained"]
            <= baseline["workspace"]["productive_descendants_retained"] * 0.25
            and b_fd >= historical_fd
        ):
            return "OVER_SUPPRESSED"
        if (
            treatment["lag1_grace_policy"]["forced_lag1_services"] > 0
            and b_stock >= a_stock - 1
        ):
            return "STILL_STALLED"
        return "NEUTRAL"

    if (b_stock < a_stock and b_fd <= a_fd + 1) or (
        b_fd < a_fd and b_stock <= a_stock
    ):
        return "BALANCED_IMPROVEMENT"
    if (
        b_fd <= a_fd
        and b_stock <= a_stock
        and treatment["workspace"]["productive_descendants_retained"] > 0
        and treatment["workspace"]["forced_services"]
        < baseline["workspace"]["forced_services"]
    ):
        return "LOCAL_GAIN_PRESERVED"
    return "NEUTRAL"


def paired_rows(runs: dict) -> list[dict]:
    rows = []
    for deal in ACTIVE_DEALS:
        if deal not in runs or any(arm not in runs[deal] for arm in ARMS):
            continue
        a = runs[deal][UNGUARDED]
        b = runs[deal][GRACE]
        rows.append(
            {
                "panel_entry": deal,
                "run_order": list(arm_order(deal)),
                "classification": classify_deal(deal, a, b),
                "minimum_face_down": {UNGUARDED: a["minimum_face_down"], GRACE: b["minimum_face_down"]},
                "minimum_expanded_stock_rows": {
                    UNGUARDED: a["minimum_expanded_stock_rows"],
                    GRACE: b["minimum_expanded_stock_rows"],
                },
                "maximum_foundations": {UNGUARDED: a["maximum_foundations"], GRACE: b["maximum_foundations"]},
                "forced_lag1_services": {
                    UNGUARDED: a["lag1_grace_policy"]["forced_lag1_services"],
                    GRACE: b["lag1_grace_policy"]["forced_lag1_services"],
                },
                "lag1_services_by_epoch": {
                    arm: {
                        epoch: data["forced_lag1_services"]
                        for epoch, data in runs[deal][arm]["lag1_grace_policy"]["epochs"].items()
                        if data["forced_lag1_services"]
                    }
                    for arm in ARMS
                },
                "productive_descendants_retained": {
                    arm: runs[deal][arm]["workspace"]["productive_descendants_retained"]
                    for arm in ARMS
                },
                "productive_descendants_ordinary_serviced": {
                    arm: runs[deal][arm]["workspace"]["productive_descendants_ordinary_serviced"]
                    for arm in ARMS
                },
                "tactical_node_ratio": b["tactical_nodes"] / a["tactical_nodes"],
                "elapsed_time_ratio": b["elapsed_s"] / a["elapsed_s"],
                "credit_balance": general._credit_balance(a, b),
            }
        )
    return rows


def aggregate(rows: list[dict], runs: dict) -> dict:
    classes = Counter(row["classification"] for row in rows)
    tactical = [row["tactical_node_ratio"] for row in rows]
    elapsed = [row["elapsed_time_ratio"] for row in rows]
    return {
        "completed_deals": len(rows),
        "completed_runs": sum(len(deal_runs) for deal_runs in runs.values()),
        "classification": {
            name: classes[name]
            for name in (
                "BALANCED_IMPROVEMENT",
                "LOCAL_GAIN_PRESERVED",
                "OVER_SUPPRESSED",
                "STILL_STALLED",
                "NEUTRAL",
            )
        },
        "forced_lag1_services": {
            arm: sum(runs[deal][arm]["lag1_grace_policy"]["forced_lag1_services"] for deal in runs)
            for arm in ARMS
        },
        "grace_spent_epochs": sum(
            runs[deal][GRACE]["lag1_grace_policy"]["lag1_grace_spent_epoch_count"]
            for deal in runs if GRACE in runs[deal]
        ),
        "productive_descendants_retained": {
            arm: sum(runs[deal][arm]["workspace"]["productive_descendants_retained"] for deal in runs)
            for arm in ARMS
        },
        "productive_descendants_ordinary_serviced": {
            arm: sum(runs[deal][arm]["workspace"]["productive_descendants_ordinary_serviced"] for deal in runs)
            for arm in ARMS
        },
        "tactical_node_ratio": {
            "median": statistics.median(tactical) if tactical else None,
            "min": min(tactical) if tactical else None,
            "max": max(tactical) if tactical else None,
        },
        "elapsed_time_ratio": {
            "median": statistics.median(elapsed) if elapsed else None,
            "min": min(elapsed) if elapsed else None,
            "max": max(elapsed) if elapsed else None,
        },
        "credit_balance_flagged": [
            row["panel_entry"] for row in rows if row["credit_balance"]["flagged"]
        ],
    }


def verdict(rows: list[dict], runs: dict, summary: dict) -> str:
    if len(rows) != 4 or summary["completed_runs"] != 8:
        return "INCONCLUSIVE"
    valid = all(
        not arm["replay_failures"]
        and not arm["corrected_cost_inconsistencies"]
        and arm["frontier"]["duplicate_entries"] == 0
        and arm["resource_planner_calls"] == 0
        for deal_runs in runs.values()
        for arm in deal_runs.values()
    )
    if not valid:
        return "INCONCLUSIVE"

    effective = True
    too_restrictive = True
    still_overinvests = True
    for deal in ("P2", "P7"):
        a = runs[deal][UNGUARDED]
        b = runs[deal][GRACE]
        historical_fd = HISTORICAL_CONTEXT[deal]["NO_WORKSPACE"]["minimum_face_down"]
        effective &= (
            b["minimum_expanded_stock_rows"] < a["minimum_expanded_stock_rows"]
            and b["minimum_face_down"] < historical_fd
            and b["lag1_grace_policy"]["forced_lag1_services"] > 0
            and b["workspace"]["productive_descendants_retained"] > 0
        )
        too_restrictive &= (
            b["workspace"]["productive_descendants_retained"]
            <= a["workspace"]["productive_descendants_retained"] * 0.25
            and b["minimum_face_down"] >= historical_fd
        )
        still_overinvests &= (
            b["lag1_grace_policy"]["forced_lag1_services"] > 0
            and b["minimum_expanded_stock_rows"] >= a["minimum_expanded_stock_rows"] - 1
        )
    if effective:
        return "LAG1_GRACE_EFFECTIVE"
    if too_restrictive:
        return "LAG1_GRACE_TOO_RESTRICTIVE"
    if still_overinvests:
        return "LAG1_GRACE_STILL_OVERINVESTS"
    inert = summary["forced_lag1_services"][GRACE] == 0 or all(
        runs[deal][GRACE]["minimum_face_down"] == runs[deal][UNGUARDED]["minimum_face_down"]
        and runs[deal][GRACE]["minimum_expanded_stock_rows"]
        == runs[deal][UNGUARDED]["minimum_expanded_stock_rows"]
        and _workspace_expansions(runs[deal][GRACE]) == _workspace_expansions(runs[deal][UNGUARDED])
        for deal in ACTIVE_DEALS
    )
    if inert:
        return "LAG1_GRACE_INERT"
    return "LAG1_GRACE_MIXED"


def build_result(definition: dict, runs: dict) -> dict:
    rows = paired_rows(runs)
    summary = aggregate(rows, runs)
    gates = {
        "all_eight_runs_complete": len(rows) == 4 and summary["completed_runs"] == 8,
        "frozen_active_fixtures_unchanged": definition == active_definition(),
        "rotation_observed": all(row["run_order"] == list(arm_order(row["panel_entry"])) for row in rows),
        "fixed_N8": service.SERVICE_INTERVAL == 8,
        "one_lag1_force_per_epoch": all(
            epoch["forced_lag1_services"] <= 1
            for deal in runs
            if GRACE in runs[deal]
            for epoch in runs[deal][GRACE]["lag1_grace_policy"]["epochs"].values()
        ),
        "no_lag2plus_treatment_force": all(
            runs[deal][GRACE]["lag1_grace_policy"]["forced_lag2_plus_services"] == 0
            for deal in runs if GRACE in runs[deal]
        ),
        "no_hold_style_ownership": all(
            runs[deal][GRACE]["lag1_grace_policy"]["no_hold_style_ineligible_ownership"]
            for deal in runs if GRACE in runs[deal]
        ),
        "forced_interval_respected": all(
            arm["workspace"]["minimum_forced_interval_respected"]
            for deal_runs in runs.values() for arm in deal_runs.values()
        ),
        "frontier_width_preserved": all(
            arm["frontier"]["size"] <= 256
            for deal_runs in runs.values() for arm in deal_runs.values()
        ),
        "no_final_or_lane_duplicates": all(
            not arm["frontier"]["duplicate_node_ids"]
            and arm["workspace"]["lane_duplicate_entries_introduced"] == 0
            for deal_runs in runs.values() for arm in deal_runs.values()
        ),
        "search_balance": not summary["credit_balance_flagged"],
        "integrity": all(
            not arm["replay_failures"]
            and not arm["corrected_cost_inconsistencies"]
            and arm["independent_replay_false"] == 0
            for deal_runs in runs.values() for arm in deal_runs.values()
        ),
        "resource_planner_not_invoked": all(
            arm["resource_planner_calls"] == 0
            for deal_runs in runs.values() for arm in deal_runs.values()
        ),
    }
    return {
        **frozen_plan(),
        "status": "COMPLETE" if len(rows) == 4 else "PARTIAL",
        "runs": runs,
        "paired_results": rows,
        "aggregate": summary,
        "gates": gates,
        "verdict": verdict(rows, runs, summary),
        "completed_utc": utc_now(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-plan-only", action="store_true")
    parser.add_argument("--stop-after-deals", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan = write_frozen_plan()
    if args.freeze_plan_only:
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    definition = active_definition()
    runs = execute_missing_runs(definition, stop_after_deals=args.stop_after_deals)
    result = build_result(definition, runs)
    _write_json_atomic(RESULT_PATH, result)
    print(
        f"VERDICT {result['verdict']} deals={result['aggregate']['completed_deals']} "
        f"runs={result['aggregate']['completed_runs']}",
        flush=True,
    )
    print(f"WROTE {RESULT_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
