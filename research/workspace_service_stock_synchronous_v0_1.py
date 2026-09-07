#!/usr/bin/env python3
"""Fresh three-arm stock-synchronous workspace-service experiment v0.1."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from collections import Counter
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
import workspace_service_panel_v0_1 as panel
import workspace_service_stock_guard_v0_1 as previous
from spider.engine import SpiderState
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)


BASE_SHA = "8f9e181d28bc2e46e2b9a52c4199ec3acd84c0bc"
EXPERIMENT_ID = "workspace_service_stock_synchronous_v0_1"
PLAN_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}_plan.json"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT_ID
ACTIVE_DEALS = ("P0", "P2", "P4", "P7")
ARMS = ("N8_UNGUARDED", "ZERO_TOLERANCE_HOLD", "STOCK_SYNCHRONOUS_RESELECT")
UNGUARDED, HOLD, RESELECT = ARMS
ZERO_TOLERANCE = 0
CONFIG = {**general.CONFIG, "stock_lag_tolerance": ZERO_TOLERANCE}
RUN_SCHEDULE = {
    "P0": (UNGUARDED, HOLD, RESELECT),
    "P2": (HOLD, RESELECT, UNGUARDED),
    "P4": (RESELECT, UNGUARDED, HOLD),
    "P7": (UNGUARDED, RESELECT, HOLD),
}
HISTORICAL_CONTEXT = previous.HISTORICAL_CONTEXT


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def arm_order(panel_entry: str) -> tuple[str, str, str]:
    try:
        return RUN_SCHEDULE[panel_entry]
    except KeyError as exc:
        raise ValueError("panel entry must be one of P0/P2/P4/P7") from exc


def active_definition() -> dict:
    full = general.panel_definition()
    entries = [
        entry for entry in full["entries"] if entry["panel_entry"] in ACTIVE_DEALS
    ]
    if [entry["panel_entry"] for entry in entries] != list(ACTIVE_DEALS):
        raise RuntimeError("frozen active entries are missing or reordered")
    return {**full, "entries": entries}


def ordinary_live_frontier_items(frontier, lane) -> tuple:
    return previous.ordinary_live_frontier_items(frontier, lane)


def stock_rows(state) -> int:
    return previous.stock_rows(state)


def stock_lag(workspace_item, ordinary_items) -> tuple[int, int, int]:
    return previous.stock_lag(workspace_item, ordinary_items)


def stock_synchronous_workspace_candidates(frontier, lane) -> tuple[int | None, tuple]:
    ordinary = ordinary_live_frontier_items(frontier, lane)
    if not ordinary:
        return None, ()
    best_rows = min(stock_rows(item[2].state) for item in ordinary)
    candidates = tuple(
        sorted(
            (
                item
                for item in ordinary
                if stock_rows(item[2].state) == best_rows
                and service.workspace_class(item[2].state) is not None
            ),
            key=lambda item: (item[0], item[2].node_id),
        )
    )
    return best_rows, candidates


class StockSynchronousWorkspaceServiceLane(service.WorkspaceServiceLane):
    """N8 lane with frozen UNGUARDED, HOLD, or RELEASE/RESELECT semantics."""

    def __init__(self, *, mode: str) -> None:
        if mode not in ARMS:
            raise ValueError(f"unknown arm {mode}")
        super().__init__(enabled=True, interval=service.SERVICE_INTERVAL)
        self.mode = mode
        self.services_withheld = 0
        self.reservations_released = 0
        self.reselections = 0
        self.lagging_events: list[dict] = []
        self.reservation_blocks: list[dict] = []
        self.current_epoch_blocked_events: list[dict] = []
        self._active_block: dict | None = None
        self._held_selection_indices: set[int] = set()
        self._awaiting_reselection = False
        self._last_expansion_count = 0
        self._completed_expansions = 0

    def _close_block(self, expansion_count: int, reason: str) -> None:
        if self._active_block is None:
            return
        self._active_block.update(
            end_after_expansions=expansion_count,
            span=max(0, expansion_count - self._active_block["start_after_expansions"]),
            end_reason=reason,
        )
        self.reservation_blocks.append(self._active_block)
        self._active_block = None

    def _update_block(self, frontier, expansion_count: int) -> tuple[int, int, int] | None:
        if self.current_item is None or self.current_selection is None:
            self._close_block(expansion_count, "NO_RESERVED_REPRESENTATIVE")
            return None
        ordinary = ordinary_live_frontier_items(frontier, self)
        workspace_rows, best_rows, lag = stock_lag(self.current_item, ordinary)
        selection_index = self.current_selection["selection_index"]
        if lag <= ZERO_TOLERANCE:
            self._close_block(expansion_count, "STOCK_SYNCHRONOUS_AGAIN")
            return workspace_rows, best_rows, lag
        if (
            self._active_block is None
            or self._active_block["selection_index"] != selection_index
        ):
            self._close_block(expansion_count, "REPRESENTATIVE_CHANGED")
            node = self.current_item[2]
            self._active_block = {
                "selection_index": selection_index,
                "node_id": node.node_id,
                "digest": common.digest(node.state),
                "start_after_expansions": expansion_count,
                "workspace_stock_rows_at_start": workspace_rows,
                "best_live_stock_rows_at_start": best_rows,
                "maximum_lag": lag,
                "end_after_expansions": None,
                "span": None,
                "end_reason": None,
            }
        else:
            self._active_block["maximum_lag"] = max(
                self._active_block["maximum_lag"], lag
            )
        return workspace_rows, best_rows, lag

    def _invalidate(self, reason: str) -> None:
        self._close_block(self._completed_expansions, f"INVALIDATED: {reason}")
        super()._invalidate(reason)

    def _selection_record(self, selected, candidates, frontier, expansion_count: int) -> dict:
        ordered = sorted(frontier)
        rank_by_id = {
            item[2].node_id: rank
            for rank, item in enumerate(ordered, start=1)
            if common.Observer._is_frontier_item(item)
        }
        node = selected[2]
        facts = service.workspace_facts(node.state)
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
            "queue_rank": rank_by_id[node.node_id],
            "ordinary_priority": repr(selected[0]),
            "eligible_count": len(candidates),
            "expanded_naturally": False,
            "expanded_via_workspace_service": False,
            "invalidated": False,
            "invalidation_reason": None,
            "trimmed_before_protection": False,
            "survived_to_end": False,
            "released_stock_lag": False,
            "outcome": "RESERVED",
            "ordinary_expansions_before_service": None,
        }

    def _reserve(self, selected, candidates, frontier, expansion_count: int):
        record = self._selection_record(
            selected, candidates, frontier, expansion_count
        )
        self.selections.append(record)
        self.current_node_id = selected[2].node_id
        self.current_item = selected
        self.current_selection = record
        self.max_outstanding = max(self.max_outstanding, 1)
        if self._awaiting_reselection:
            self.reselections += 1
            record["reselection_after_release"] = True
            self._awaiting_reselection = False
        else:
            record["reselection_after_release"] = False
        return selected

    def _lag_event(
        self,
        *,
        action: str,
        expansion_count: int,
        workspace_rows: int,
        best_rows: int,
        lag: int,
    ) -> dict:
        node = self.current_item[2]
        event = {
            "event_id": len(self.lagging_events),
            "after_completed_expansions": expansion_count,
            "strategic_expansion_number": expansion_count + 1,
            "selection_index": self.current_selection["selection_index"],
            "representative_node_id": node.node_id,
            "representative_digest": common.digest(node.state),
            "representative_g": int(node.g),
            "representative_credit": int(node.credit_level),
            "representative_stock_rows": workspace_rows,
            "best_live_stock_rows": best_rows,
            "stock_lag": lag,
            "action": action,
            "eventual_natural_expansion": None,
            "eventual_forced_expansion": None,
            "end_of_run_status": None,
        }
        self.lagging_events.append(event)
        return event

    def _release(self, expansion_count: int) -> None:
        selection = self.current_selection
        if selection is None:
            return
        selection.update(
            outcome="RELEASED_STOCK_LAG",
            released_stock_lag=True,
            released_after_expansions=expansion_count,
        )
        self._close_block(expansion_count, "RELEASED_STOCK_LAG")
        self.services_withheld += 1
        self.reservations_released += 1
        self.current_node_id = None
        self.current_item = None
        self.current_selection = None
        self.pending_pop = None
        self._awaiting_reselection = True

    def select(self, frontier, *, expansion_count: int):
        self._last_expansion_count = expansion_count
        if self.mode != RESELECT:
            return super().select(frontier, expansion_count=expansion_count)

        if self.current_item is not None and self.current_selection is not None:
            ordinary = ordinary_live_frontier_items(frontier, self)
            workspace_rows, best_rows, lag = stock_lag(self.current_item, ordinary)
            if lag > ZERO_TOLERANCE:
                self._update_block(frontier, expansion_count)
                self._lag_event(
                    action="RELEASE",
                    expansion_count=expansion_count,
                    workspace_rows=workspace_rows,
                    best_rows=best_rows,
                    lag=lag,
                )
                self._release(expansion_count)
            else:
                return self.current_item

        best_rows, candidates = stock_synchronous_workspace_candidates(frontier, self)
        if best_rows is None or not candidates:
            return None
        return self._reserve(candidates[0], candidates, frontier, expansion_count)

    def _record_blocked_current_epoch(self, frontier, expansion_count: int) -> None:
        if (
            self.mode != HOLD
            or self.current_selection is None
            or self.current_selection["selection_index"] not in self._held_selection_indices
        ):
            return
        best_rows, candidates = stock_synchronous_workspace_candidates(frontier, self)
        if best_rows is None:
            return
        for item in candidates:
            node = item[2]
            if node.node_id == self.current_node_id:
                continue
            facts = service.workspace_facts(node.state)
            self.current_epoch_blocked_events.append(
                {
                    "occurrence_id": len(self.current_epoch_blocked_events),
                    "after_completed_expansions": expansion_count,
                    "held_selection_index": self.current_selection["selection_index"],
                    "held_node_id": self.current_node_id,
                    "candidate_node_id": node.node_id,
                    "candidate_digest": common.digest(node.state),
                    "candidate_g": int(node.g),
                    "candidate_credit": int(node.credit_level),
                    "candidate_workspace_class": facts["workspace_class"],
                    "candidate_stock_rows": stock_rows(node.state),
                    "best_live_stock_rows": best_rows,
                    "later_expanded_naturally": None,
                }
            )

    def pop(self, frontier, *, ordinary_pop, ordinary_heapify, expansion_count: int):
        self._last_expansion_count = expansion_count
        self.reconcile(frontier)
        self.select(frontier, expansion_count=expansion_count)
        lag_values = self._update_block(frontier, expansion_count)
        due = (
            self.current_item is not None
            and self.ordinary_expansions_since_service >= self.interval
        )
        if not due:
            self._record_blocked_current_epoch(frontier, expansion_count)
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )

        if self.mode == UNGUARDED:
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )

        if lag_values is None:
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )
        workspace_rows, best_rows, lag = lag_values
        if lag <= ZERO_TOLERANCE:
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )

        # RESELECT releases during select(), so only HOLD can reach this branch.
        if self.mode != HOLD:
            raise AssertionError("lagging RESELECT representative was not released")
        self._lag_event(
            action="HOLD",
            expansion_count=expansion_count,
            workspace_rows=workspace_rows,
            best_rows=best_rows,
            lag=lag,
        )
        self.services_withheld += 1
        self._held_selection_indices.add(self.current_selection["selection_index"])
        self._record_blocked_current_epoch(frontier, expansion_count)

        # Spend the entitlement without banking a catch-up pop.  The exact
        # reserved item remains untouched in the ordinary frontier.
        self.ordinary_expansions_since_service = 0
        item = ordinary_pop(frontier)
        if self.current_node_id is not None and item[2].node_id == self.current_node_id:
            self.pending_pop = {
                "node_id": item[2].node_id,
                "mode": "WORKSPACE_NATURAL",
            }
            if self.current_selection is not None:
                self.current_selection["outcome"] = (
                    "POPPED_NATURALLY_PENDING_EXPANSION"
                )
        return item, False

    def on_expansion(self, node) -> str:
        self._completed_expansions = max(
            self._completed_expansions, self._last_expansion_count + 1
        )
        if self.pending_pop is not None and self.pending_pop["node_id"] == node.node_id:
            self._close_block(self._last_expansion_count, self.pending_pop["mode"])
        return super().on_expansion(node)

    def finalize(self, frontier) -> None:
        super().finalize(frontier)
        self._close_block(self._completed_expansions, "END_OF_RUN")

    def resolve_policy_outcomes(self, node_records: dict, expansion_modes: dict) -> None:
        selections = {
            selection["selection_index"]: selection for selection in self.selections
        }
        for event in self.lagging_events:
            selection = selections[event["selection_index"]]
            node_id = event["representative_node_id"]
            mode = expansion_modes.get(node_id)
            event["eventual_natural_expansion"] = mode in {
                "ORDINARY",
                "WORKSPACE_NATURAL",
            }
            event["eventual_forced_expansion"] = mode == "WORKSPACE_FORCED"
            if mode == "WORKSPACE_FORCED":
                status = "EXPANDED_FORCED"
            elif mode in {"ORDINARY", "WORKSPACE_NATURAL"}:
                status = "EXPANDED_NATURALLY"
            elif node_records.get(node_id, {}).get("live"):
                status = "LIVE_AT_END"
            elif node_records.get(node_id, {}).get("trimmed"):
                status = "TRIMMED"
            elif selection["outcome"] == "RELEASED_STOCK_LAG":
                status = "RELEASED_NOT_LIVE_AT_END"
            else:
                status = selection["outcome"]
            event["end_of_run_status"] = status

        for event in self.current_epoch_blocked_events:
            mode = expansion_modes.get(event["candidate_node_id"])
            event["later_expanded_naturally"] = mode in {
                "ORDINARY",
                "WORKSPACE_NATURAL",
            }

    def policy_summary(self) -> dict:
        spans = [row["span"] for row in self.reservation_blocks]
        blocked_digests = {
            row["candidate_digest"] for row in self.current_epoch_blocked_events
        }
        natural_digests = {
            row["candidate_digest"]
            for row in self.current_epoch_blocked_events
            if row["later_expanded_naturally"]
        }
        return {
            "mode": self.mode,
            "zero_tolerance": ZERO_TOLERANCE,
            "services_withheld": self.services_withheld,
            "reservations_released": self.reservations_released,
            "reselections": self.reselections,
            "lagging_events": self.lagging_events,
            "reservation_block_span": {
                "maximum": max(spans) if spans else 0,
                "median": statistics.median(spans) if spans else 0,
                "count_exceeding_32": sum(span > 32 for span in spans),
                "count_surviving_to_end": sum(
                    row["end_reason"] == "END_OF_RUN"
                    for row in self.reservation_blocks
                ),
                "blocks": self.reservation_blocks,
            },
            "current_epoch_opportunity_loss": {
                "occurrences": len(self.current_epoch_blocked_events),
                "unique_candidate_states": len(blocked_digests),
                "unique_candidate_states_later_expanded_naturally": len(
                    natural_digests
                ),
                "events": self.current_epoch_blocked_events,
            },
        }


class StockSynchronousPanelObserver(general.PanelWorkspaceServiceObserver):
    def __init__(self, opening: SpiderState, *, mode: str) -> None:
        super().__init__(opening, enable_service=True)
        self.lane = StockSynchronousWorkspaceServiceLane(mode=mode)
        self.structural_expansions: list[dict] = []

    def install(self) -> None:
        super().install()
        observed_generate = controller.generate_strategic_successors
        observer = self

        def wrapped_generate(node, cards, **kwargs):
            facts = service.workspace_facts(node.state)
            observer.structural_expansions.append(
                {
                    "node_id": node.node_id,
                    "digest": common.digest(node.state),
                    "R2": facts["fully_revealed_columns"] > 0,
                    "stable_same_suit_joins": facts["stable_same_suit_joins"],
                    "same_suit_run_mass": facts["same_suit_run_mass"],
                }
            )
            return observed_generate(node, cards, **kwargs)

        controller.generate_strategic_successors = wrapped_generate

    def workspace_summary(self, result) -> dict:
        output = super().workspace_summary(result)
        self.lane.resolve_policy_outcomes(self.nodes, self.expansion_modes)
        output["stock_synchronous_policy"] = self.lane.policy_summary()
        output["structural_progress"] = {
            "R2_expansions": sum(row["R2"] for row in self.structural_expansions),
            "maximum_stable_same_suit_joins": max(
                (row["stable_same_suit_joins"] for row in self.structural_expansions),
                default=0,
            ),
            "maximum_same_suit_run_mass": max(
                (row["same_suit_run_mass"] for row in self.structural_expansions),
                default=0,
            ),
        }
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
    observer = StockSynchronousPanelObserver(opening, mode=mode)
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
    compact["stock_synchronous_policy"] = full["stock_synchronous_policy"]
    compact["structural_progress"] = full["structural_progress"]
    return compact


def balance_classification(face_down_delta: int, stock_delta: int) -> str:
    """Frozen exhaustive rule; treatment-minus-A deltas, negative is better."""

    if (stock_delta < 0 and face_down_delta <= 1) or (
        face_down_delta < 0 and stock_delta <= 0
    ):
        return "BALANCED_WIN"
    if face_down_delta > 0 and stock_delta > 0:
        return "LOSS"
    if face_down_delta < 0 and stock_delta > 0:
        return "LOCAL_TRADEOFF"
    if stock_delta < 0 and face_down_delta > 1:
        return "STOCK_TRADEOFF"
    return "NEUTRAL"


def frozen_plan() -> dict:
    definition = active_definition()
    return {
        "experiment": EXPERIMENT_ID,
        "status": "FROZEN_PRE_RUN",
        "base_sha": BASE_SHA,
        "panel_definition_path": panel.PANEL_PATH.relative_to(ROOT).as_posix(),
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
        "balance_rule": {
            "delta_definition": "B/C minus A; negative is improvement",
            "BALANCED_WIN": "stock_delta < 0 and face_down_delta <= 1, or face_down_delta < 0 and stock_delta <= 0",
            "LOSS": "face_down_delta > 0 and stock_delta > 0",
            "LOCAL_TRADEOFF": "face_down_delta < 0 and stock_delta > 0",
            "STOCK_TRADEOFF": "stock_delta < 0 and face_down_delta > 1",
            "NEUTRAL": "all remaining outcomes",
            "evaluation_order": [
                "BALANCED_WIN",
                "LOSS",
                "LOCAL_TRADEOFF",
                "STOCK_TRADEOFF",
                "NEUTRAL",
            ],
        },
        "stale_block_definition": {
            "span": "completed strategic expansions from first lagging ownership observation until synchrony, expansion, invalidation, release, or end",
            "current_epoch_occurrence": "one candidate occurrence at one pre-expansion ordinary-frontier snapshot while a previously withheld HOLD representative owns the lane",
            "unique_candidate_state": "candidate structural digest",
        },
        "verdict_rule": {
            "STALE_RESERVATION_BLOCKING_CONFIRMED": "B has a span >32 and blocked lag-0 opportunities, and C restores more forced/natural service, ordinary reintegration, or a better FD/stock endpoint on an affected deal",
            "STOCK_SYNCHRONOUS_SERVICE_EFFECTIVE": "C has BALANCED_WIN on at least two deals and retains at least half of A's total productive workspace descendants",
            "ZERO_TOLERANCE_OVER_SUPPRESSES": "on both P2 and P7, B and C each retain at most 25% of A workspace expansions and erase the historical N8 face-down advantage",
            "STOCK_SYNCHRONY_INERT": "C is NEUTRAL on all four deals",
            "STOCK_SYNCHRONY_MIXED": "all other valid completed outcomes",
            "evaluation_order": [
                "INCONCLUSIVE",
                "STALE_RESERVATION_BLOCKING_CONFIRMED",
                "STOCK_SYNCHRONOUS_SERVICE_EFFECTIVE",
                "ZERO_TOLERANCE_OVER_SUPPRESSES",
                "STOCK_SYNCHRONY_INERT",
                "STOCK_SYNCHRONY_MIXED",
            ],
        },
        "historical_context": HISTORICAL_CONTEXT,
    }


def write_frozen_plan() -> dict:
    plan_data = frozen_plan()
    rendered = json.dumps(plan_data, indent=2, sort_keys=True) + "\n"
    if PLAN_PATH.exists() and PLAN_PATH.read_text(encoding="utf-8") != rendered:
        raise RuntimeError(f"refusing to replace frozen plan {PLAN_PATH}")
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    return plan_data


def _config_fingerprint() -> str:
    payload = {
        "config": CONFIG,
        "run_schedule": {deal: list(order) for deal, order in RUN_SCHEDULE.items()},
        "balance_rule": frozen_plan()["balance_rule"],
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
    all_runs: dict[str, dict] = {}
    completed_deals = 0
    for entry in definition["entries"]:
        panel_entry = entry["panel_entry"]
        cards = general.load_entry_cards(entry)
        left = SpiderState.from_cards(list(cards))
        right = SpiderState.from_cards(list(cards))
        if (
            common.digest(left) != common.digest(right)
            or common.digest(left) != entry["opening_digest"]
        ):
            raise RuntimeError(f"initial-state mismatch for {panel_entry}")
        all_runs[panel_entry] = {}
        for order_index, arm in enumerate(arm_order(panel_entry), start=1):
            checkpoint = _load_checkpoint(entry, arm)
            if checkpoint is None:
                print(
                    f"START {panel_entry} {arm} order={order_index}/3 at {utc_now()}",
                    flush=True,
                )
                started = utc_now()
                summary = run_arm(cards, mode=arm)
                for event in summary["stock_synchronous_policy"]["lagging_events"]:
                    event["deal"] = panel_entry
                checkpoint = {
                    "experiment": EXPERIMENT_ID,
                    "panel_entry": panel_entry,
                    "opening_digest": entry["opening_digest"],
                    "arm": arm,
                    "run_order_index": order_index,
                    "config_fingerprint": _config_fingerprint(),
                    "started_utc": started,
                    "completed_utc": utc_now(),
                    "summary": summary,
                }
                _write_json_atomic(_checkpoint_path(panel_entry, arm), checkpoint)
                policy = summary["stock_synchronous_policy"]
                print(
                    f"DONE {panel_entry} {arm}: exp={summary['strategic_expansions']} "
                    f"fd={summary['minimum_face_down']} "
                    f"stock={summary['minimum_expanded_stock_rows']} "
                    f"EC={summary['EMPTY_CREATABLE']['expanded']} "
                    f"AE={summary['ACTUAL_EMPTY']['expanded']} "
                    f"forced={summary['workspace']['forced_services']} "
                    f"natural={summary['workspace']['natural_services']} "
                    f"withheld={policy['services_withheld']} "
                    f"released={policy['reservations_released']} "
                    f"blocked={policy['current_epoch_opportunity_loss']['occurrences']} "
                    f"span={policy['reservation_block_span']['maximum']} "
                    f"tactical={summary['tactical_nodes']} "
                    f"elapsed={summary['elapsed_s']:.1f}s",
                    flush=True,
                )
            else:
                print(f"RESUME {panel_entry} {arm} from checkpoint", flush=True)
            all_runs[panel_entry][arm] = checkpoint["summary"]
        completed_deals += 1
        if stop_after_deals is not None and completed_deals >= stop_after_deals:
            break
    return all_runs


def paired_rows(runs: dict) -> list[dict]:
    rows = []
    for panel_entry in ACTIVE_DEALS:
        if panel_entry not in runs or any(arm not in runs[panel_entry] for arm in ARMS):
            continue
        arms = runs[panel_entry]
        baseline = arms[UNGUARDED]
        comparisons = {}
        for arm in (HOLD, RESELECT):
            face_down_delta = arms[arm]["minimum_face_down"] - baseline[
                "minimum_face_down"
            ]
            stock_delta = (
                arms[arm]["minimum_expanded_stock_rows"]
                - baseline["minimum_expanded_stock_rows"]
            )
            comparisons[arm] = {
                "face_down_delta": face_down_delta,
                "stock_delta": stock_delta,
                "classification": balance_classification(
                    face_down_delta, stock_delta
                ),
                "tactical_node_ratio": arms[arm]["tactical_nodes"]
                / baseline["tactical_nodes"],
                "elapsed_time_ratio": arms[arm]["elapsed_s"]
                / baseline["elapsed_s"],
                "credit_balance": general._credit_balance(baseline, arms[arm]),
            }
        rows.append(
            {
                "panel_entry": panel_entry,
                "run_order": list(arm_order(panel_entry)),
                "minimum_face_down": {
                    arm: arms[arm]["minimum_face_down"] for arm in ARMS
                },
                "minimum_expanded_stock_rows": {
                    arm: arms[arm]["minimum_expanded_stock_rows"] for arm in ARMS
                },
                "maximum_foundations": {
                    arm: arms[arm]["maximum_foundations"] for arm in ARMS
                },
                "comparisons_to_A": comparisons,
                "policy": {
                    arm: arms[arm]["stock_synchronous_policy"] for arm in ARMS
                },
                "workspace": {arm: arms[arm]["workspace"] for arm in ARMS},
                "structural_progress": {
                    arm: arms[arm]["structural_progress"] for arm in ARMS
                },
            }
        )
    return rows


def aggregate(rows: list[dict], runs: dict) -> dict:
    classification_names = (
        "BALANCED_WIN",
        "LOCAL_TRADEOFF",
        "STOCK_TRADEOFF",
        "NEUTRAL",
        "LOSS",
    )
    output = {
        "completed_deals": len(rows),
        "completed_runs": sum(len(deal_runs) for deal_runs in runs.values()),
        "ordinary_serviced_productive_descendants": {
            arm: sum(
                runs[deal][arm]["workspace"][
                    "productive_descendants_ordinary_serviced"
                ]
                for deal in runs
                if arm in runs[deal]
            )
            for arm in ARMS
        },
        "maximum_stale_reservation_span": {
            arm: max(
                (
                    runs[deal][arm]["stock_synchronous_policy"][
                        "reservation_block_span"
                    ]["maximum"]
                    for deal in runs
                    if arm in runs[deal]
                ),
                default=0,
            )
            for arm in ARMS
        },
        "hold_current_epoch_opportunity_loss": {
            "occurrences": sum(
                runs[deal][HOLD]["stock_synchronous_policy"][
                    "current_epoch_opportunity_loss"
                ]["occurrences"]
                for deal in runs
                if HOLD in runs[deal]
            ),
            "unique_candidate_states": len(
                {
                    event["candidate_digest"]
                    for deal in runs
                    if HOLD in runs[deal]
                    for event in runs[deal][HOLD]["stock_synchronous_policy"][
                        "current_epoch_opportunity_loss"
                    ]["events"]
                }
            ),
            "unique_candidate_states_later_expanded_naturally": len(
                {
                    event["candidate_digest"]
                    for deal in runs
                    if HOLD in runs[deal]
                    for event in runs[deal][HOLD]["stock_synchronous_policy"][
                        "current_epoch_opportunity_loss"
                    ]["events"]
                    if event["later_expanded_naturally"]
                }
            ),
        },
        "comparisons_to_A": {},
        "credit_balance_flagged": [],
    }
    for arm in (HOLD, RESELECT):
        comparisons = [row["comparisons_to_A"][arm] for row in rows]
        counts = Counter(row["classification"] for row in comparisons)
        tactical = [row["tactical_node_ratio"] for row in comparisons]
        elapsed = [row["elapsed_time_ratio"] for row in comparisons]
        output["comparisons_to_A"][arm] = {
            "classification": {name: counts[name] for name in classification_names},
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
        }
        output["credit_balance_flagged"].extend(
            {"deal": row["panel_entry"], "arm": arm}
            for row in rows
            if row["comparisons_to_A"][arm]["credit_balance"]["flagged"]
        )
    return output


def _workspace_expansions(summary: dict) -> int:
    return summary["EMPTY_CREATABLE"]["expanded"] + summary["ACTUAL_EMPTY"][
        "expanded"
    ]


def _endpoint_better(left: dict, right: dict) -> bool:
    return (
        left["minimum_face_down"] < right["minimum_face_down"]
        and left["minimum_expanded_stock_rows"]
        <= right["minimum_expanded_stock_rows"]
    ) or (
        left["minimum_expanded_stock_rows"]
        < right["minimum_expanded_stock_rows"]
        and left["minimum_face_down"] <= right["minimum_face_down"] + 1
    )


def classify(rows: list[dict], runs: dict, summary: dict) -> str:
    if len(rows) != 4 or summary["completed_runs"] != 12:
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

    b_long = summary["maximum_stale_reservation_span"][HOLD] > 32
    b_blocked = summary["hold_current_epoch_opportunity_loss"]["occurrences"] > 0
    affected = [
        deal
        for deal in ACTIVE_DEALS
        if runs[deal][HOLD]["stock_synchronous_policy"][
            "current_epoch_opportunity_loss"
        ]["occurrences"]
        > 0
    ]
    c_restores = any(
        runs[deal][RESELECT]["workspace"]["forced_services"]
        + runs[deal][RESELECT]["workspace"]["natural_services"]
        > runs[deal][HOLD]["workspace"]["forced_services"]
        + runs[deal][HOLD]["workspace"]["natural_services"]
        or runs[deal][RESELECT]["workspace"][
            "productive_descendants_ordinary_serviced"
        ]
        > runs[deal][HOLD]["workspace"][
            "productive_descendants_ordinary_serviced"
        ]
        or _endpoint_better(runs[deal][RESELECT], runs[deal][HOLD])
        for deal in affected
    )
    if b_long and b_blocked and c_restores:
        return "STALE_RESERVATION_BLOCKING_CONFIRMED"

    c_counts = summary["comparisons_to_A"][RESELECT]["classification"]
    a_productive = sum(
        runs[deal][UNGUARDED]["workspace"]["productive_descendants_retained"]
        for deal in ACTIVE_DEALS
    )
    c_productive = sum(
        runs[deal][RESELECT]["workspace"]["productive_descendants_retained"]
        for deal in ACTIVE_DEALS
    )
    if c_counts["BALANCED_WIN"] >= 2 and c_productive >= a_productive / 2:
        return "STOCK_SYNCHRONOUS_SERVICE_EFFECTIVE"

    oversuppressed = True
    for deal in ("P2", "P7"):
        control_fd = HISTORICAL_CONTEXT[deal]["NO_WORKSPACE"]["minimum_face_down"]
        a_workspace = _workspace_expansions(runs[deal][UNGUARDED])
        for arm in (HOLD, RESELECT):
            if not (
                _workspace_expansions(runs[deal][arm]) <= a_workspace * 0.25
                and runs[deal][arm]["minimum_face_down"] >= control_fd
            ):
                oversuppressed = False
    if oversuppressed:
        return "ZERO_TOLERANCE_OVER_SUPPRESSES"
    if c_counts["NEUTRAL"] == 4:
        return "STOCK_SYNCHRONY_INERT"
    return "STOCK_SYNCHRONY_MIXED"


def build_result(definition: dict, runs: dict) -> dict:
    rows = paired_rows(runs)
    summary = aggregate(rows, runs)
    gates = {
        "all_twelve_runs_complete": len(rows) == 4
        and summary["completed_runs"] == 12,
        "frozen_active_fixtures_unchanged": definition == active_definition(),
        "latin_rotation_observed": all(
            row["run_order"] == list(arm_order(row["panel_entry"])) for row in rows
        ),
        "fixed_N8_and_zero_tolerance": service.SERVICE_INTERVAL == 8
        and ZERO_TOLERANCE == 0,
        "reselect_has_no_persistent_lagging_ownership": all(
            runs[deal][RESELECT]["stock_synchronous_policy"][
                "reservation_block_span"
            ]["maximum"]
            == 0
            for deal in runs
            if RESELECT in runs[deal]
        ),
        "forced_interval_respected": all(
            arm["workspace"]["minimum_forced_interval_respected"]
            for deal_runs in runs.values()
            for arm in deal_runs.values()
        ),
        "frontier_width_preserved": all(
            arm["frontier"]["size"] <= 256
            for deal_runs in runs.values()
            for arm in deal_runs.values()
        ),
        "no_final_or_lane_duplicates": all(
            not arm["frontier"]["duplicate_node_ids"]
            and arm["workspace"]["lane_duplicate_entries_introduced"] == 0
            for deal_runs in runs.values()
            for arm in deal_runs.values()
        ),
        "search_balance": not summary["credit_balance_flagged"],
        "integrity": all(
            not arm["replay_failures"]
            and not arm["corrected_cost_inconsistencies"]
            and arm["independent_replay_false"] == 0
            for deal_runs in runs.values()
            for arm in deal_runs.values()
        ),
        "resource_planner_not_invoked": all(
            arm["resource_planner_calls"] == 0
            for deal_runs in runs.values()
            for arm in deal_runs.values()
        ),
    }
    return {
        **frozen_plan(),
        "status": "COMPLETE" if len(rows) == 4 else "PARTIAL",
        "runs": runs,
        "paired_results": rows,
        "aggregate": summary,
        "gates": gates,
        "verdict": classify(rows, runs, summary),
        "completed_utc": utc_now(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-plan-only", action="store_true")
    parser.add_argument("--stop-after-deals", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan_data = write_frozen_plan()
    if args.freeze_plan_only:
        print(json.dumps(plan_data, indent=2, sort_keys=True))
        return 0
    definition = active_definition()
    runs = execute_missing_runs(
        definition, stop_after_deals=args.stop_after_deals
    )
    result = build_result(definition, runs)
    _write_json_atomic(RESULT_PATH, result)
    print(
        f"VERDICT {result['verdict']} deals={result['aggregate']['completed_deals']} "
        f"runs={result['aggregate']['completed_runs']}",
        flush=True,
    )
    print(f"WROTE {RESULT_PATH}", flush=True)
    return 0 if all(result["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
