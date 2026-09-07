#!/usr/bin/env python3
"""Fresh N8 versus N8+stock-guard panel experiment v0.1."""

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
from spider.engine import SpiderState
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)


BASE_SHA = "7444850e158619353df6e6ea18b190ef22d56b37"
EXPERIMENT_ID = "workspace_service_stock_guard_v0_1"
PLAN_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}_plan.json"
RESULT_PATH = ROOT / "docs" / "research" / f"{EXPERIMENT_ID}.json"
CHECKPOINT_DIR = ROOT / "research" / "results" / EXPERIMENT_ID
ARMS = ("WORKSPACE_N8", "WORKSPACE_N8_STOCK_GUARD")
ACTIVE_DEALS = ("P0", "P2", "P4", "P7")
TRADEOFF_DEALS = ("P2", "P7")
STOCK_LAG_THRESHOLD = 1
CONFIG = {**general.CONFIG, "stock_lag_threshold": STOCK_LAG_THRESHOLD}
HISTORICAL_CONTEXT = {
    "P2": {
        "N8": {"minimum_face_down": 26, "minimum_expanded_stock_rows": 4},
        "NO_WORKSPACE": {"minimum_face_down": 39, "minimum_expanded_stock_rows": 0},
    },
    "P7": {
        "N8": {"minimum_face_down": 32, "minimum_expanded_stock_rows": 5},
        "NO_WORKSPACE": {"minimum_face_down": 34, "minimum_expanded_stock_rows": 1},
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def arm_order(panel_index: int) -> tuple[str, str]:
    if not 0 <= panel_index <= 9:
        raise ValueError("panel index must be P0..P9")
    return (
        ("WORKSPACE_N8_STOCK_GUARD", "WORKSPACE_N8")
        if panel_index % 2 == 0
        else ("WORKSPACE_N8", "WORKSPACE_N8_STOCK_GUARD")
    )


def ordinary_live_frontier_items(frontier, lane) -> tuple:
    """Unique, live, non-stale entries that retain ordinary-pop eligibility."""

    best_by_node_id = {}
    for item in frontier:
        if not common.Observer._is_frontier_item(item):
            continue
        node = item[2]
        if service.expansion_identity(node) in lane.expanded_state_credits:
            continue
        previous = best_by_node_id.get(node.node_id)
        if previous is None or item[0] < previous[0]:
            best_by_node_id[node.node_id] = item
    return tuple(sorted(best_by_node_id.values()))


def stock_rows(state) -> int:
    if len(state.stock) % 10:
        raise AssertionError("stock must contain complete ten-card rows")
    return len(state.stock) // 10


def stock_lag(workspace_item, ordinary_items) -> tuple[int, int, int]:
    workspace_rows = stock_rows(workspace_item[2].state)
    best_live_rows = min(
        (stock_rows(item[2].state) for item in ordinary_items),
        default=workspace_rows,
    )
    return workspace_rows, best_live_rows, workspace_rows - best_live_rows


class StockGuardWorkspaceServiceLane(service.WorkspaceServiceLane):
    """The exact N8 lane with one guard immediately before forced service."""

    def __init__(self, *, stock_guard_enabled: bool) -> None:
        super().__init__(enabled=True, interval=service.SERVICE_INTERVAL)
        self.stock_guard_enabled = stock_guard_enabled
        self.guard_events: list[dict] = []

    def pop(self, frontier, *, ordinary_pop, ordinary_heapify, expansion_count: int):
        self.reconcile(frontier)
        self.select(frontier, expansion_count=expansion_count)
        due = (
            self.current_item is not None
            and self.ordinary_expansions_since_service >= self.interval
        )
        if not due:
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )

        ordinary_items = ordinary_live_frontier_items(frontier, self)
        workspace_rows, best_live_rows, lag = stock_lag(
            self.current_item, ordinary_items
        )
        node = self.current_item[2]
        facts = service.workspace_facts(node.state)
        decision = (
            "WITHHOLD_STOCK_LAG"
            if self.stock_guard_enabled and lag > STOCK_LAG_THRESHOLD
            else "SERVICE"
        )
        event = {
            "event_id": len(self.guard_events),
            "after_completed_expansions": expansion_count,
            "strategic_expansion_number": expansion_count + 1,
            "workspace_node_id": node.node_id,
            "workspace_digest": common.digest(node.state),
            "workspace_class": facts["workspace_class"],
            "workspace_g": int(node.g),
            "workspace_credit": int(node.credit_level),
            "workspace_stock_rows": workspace_rows,
            "best_live_ordinary_stock_rows": best_live_rows,
            "stock_lag": lag,
            "decision": decision,
            "representative_selection_index": self.current_selection["selection_index"],
            "later_representative_outcome": None,
        }
        self.guard_events.append(event)

        if decision == "SERVICE":
            return super().pop(
                frontier,
                ordinary_pop=ordinary_pop,
                ordinary_heapify=ordinary_heapify,
                expansion_count=expansion_count,
            )

        # The missed entitlement is spent, not banked.  The same exact frontier
        # entry remains reserved and the next N ordinary expansions start now.
        self.ordinary_expansions_since_service = 0
        item = ordinary_pop(frontier)
        if self.current_node_id is not None and item[2].node_id == self.current_node_id:
            self.pending_pop = {
                "node_id": item[2].node_id,
                "mode": "WORKSPACE_NATURAL",
            }
            if self.current_selection is not None:
                self.current_selection["outcome"] = "POPPED_NATURALLY_PENDING_EXPANSION"
        return item, False

    def resolve_guard_outcomes(self, node_records: dict[int, dict]) -> None:
        by_selection = {
            selection["selection_index"]: selection for selection in self.selections
        }
        for event in self.guard_events:
            selection = by_selection[event["representative_selection_index"]]
            outcome = selection["outcome"]
            if outcome == "EXPANDED_NATURALLY":
                resolved = "NATURALLY_EXPANDED"
            elif outcome == "EXPANDED_VIA_WORKSPACE_SERVICE":
                resolved = "EVENTUALLY_FORCED"
            elif outcome == "SURVIVED_TO_END":
                resolved = "LIVE_AT_END"
            elif node_records.get(selection["node_id"], {}).get("trimmed"):
                resolved = "TRIMMED"
            else:
                resolved = "REPLACED"
            event["later_representative_outcome"] = resolved

    def guard_summary(self) -> dict:
        lags = [event["stock_lag"] for event in self.guard_events]
        withheld = [
            event
            for event in self.guard_events
            if event["decision"] == "WITHHOLD_STOCK_LAG"
        ]
        affected = {
            event["representative_selection_index"] for event in withheld
        }
        outcomes = {
            event["representative_selection_index"]: event[
                "later_representative_outcome"
            ]
            for event in withheld
        }
        return {
            "enabled": self.stock_guard_enabled,
            "threshold": STOCK_LAG_THRESHOLD,
            "scheduled_opportunities": len(self.guard_events),
            "forced_services_executed": sum(
                event["decision"] == "SERVICE" for event in self.guard_events
            ),
            "forced_services_withheld": len(withheld),
            "distinct_representatives_affected": len(affected),
            "maximum_observed_stock_lag": max(lags) if lags else None,
            "median_stock_lag": statistics.median(lags) if lags else None,
            "withheld_representative_later_naturally_expanded": sum(
                outcome == "NATURALLY_EXPANDED" for outcome in outcomes.values()
            ),
            "withheld_representative_later_forced": sum(
                outcome == "EVENTUALLY_FORCED" for outcome in outcomes.values()
            ),
            "withheld_representative_never_serviced": sum(
                outcome in {"REPLACED", "TRIMMED", "LIVE_AT_END"}
                for outcome in outcomes.values()
            ),
            "events": self.guard_events,
        }


class StockGuardPanelObserver(general.PanelWorkspaceServiceObserver):
    def __init__(self, opening: SpiderState, *, stock_guard_enabled: bool) -> None:
        super().__init__(opening, enable_service=True)
        self.lane = StockGuardWorkspaceServiceLane(
            stock_guard_enabled=stock_guard_enabled
        )

    def workspace_summary(self, result) -> dict:
        output = super().workspace_summary(result)
        self.lane.resolve_guard_outcomes(self.nodes)
        output["stock_guard"] = self.lane.guard_summary()
        return output


def run_arm(
    cards: tuple, *, panel_entry: str, stock_guard_enabled: bool
) -> dict:
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
    observer = StockGuardPanelObserver(
        opening, stock_guard_enabled=stock_guard_enabled
    )
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
    compact["stock_guard"] = full["stock_guard"]
    for event in compact["stock_guard"]["events"]:
        event["deal"] = panel_entry
    return compact


def combined_endpoint(face_down_delta: int, stock_delta: int) -> str:
    """Frozen exhaustive rule; deltas are guarded minus unguarded N8."""

    if (stock_delta < 0 and face_down_delta <= 1) or (
        face_down_delta < 0 and stock_delta <= 0
    ):
        return "WIN"
    if face_down_delta > 0 and stock_delta > 0:
        return "LOSS"
    if (stock_delta < 0 and face_down_delta > 1) or (
        face_down_delta < 0 and stock_delta > 0
    ):
        return "TRADEOFF"
    return "NEUTRAL"


def frozen_plan() -> dict:
    definition = general.panel_definition()
    return {
        "experiment": EXPERIMENT_ID,
        "status": "FROZEN_PRE_RUN",
        "base_sha": BASE_SHA,
        "panel_definition_path": panel.PANEL_PATH.relative_to(ROOT).as_posix(),
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
        "run_schedule": {
            f"P{index}": list(arm_order(index)) for index in range(10)
        },
        "active_deals_for_stratified_reporting": list(ACTIVE_DEALS),
        "tradeoff_diagnostic_deals": list(TRADEOFF_DEALS),
        "combined_endpoint_rule": {
            "delta_definition": "guarded minus N8; negative is improvement",
            "WIN": "stock_delta < 0 and face_down_delta <= 1, or face_down_delta < 0 and stock_delta <= 0",
            "LOSS": "face_down_delta > 0 and stock_delta > 0",
            "TRADEOFF": "stock_delta < 0 and face_down_delta > 1, or face_down_delta < 0 and stock_delta > 0",
            "NEUTRAL": "all remaining paired outcomes",
            "evaluation_order": ["WIN", "LOSS", "TRADEOFF", "NEUTRAL"],
        },
        "verdict_rule": {
            "BALANCES": "P2 and P7 both improve stock, both retain at least half their historical face-down advantage, and active subset has at least two WINs",
            "OVER_SUPPRESSES": "at least one P2/P7 stock recovery, but every recovered deal loses its entire historical face-down advantage",
            "INERT": "no withheld events, or both P2 and P7 are NEUTRAL",
            "HARMS": "at least two active deals are LOSS",
            "MIXED": "all other valid completed outcomes",
            "evaluation_order": [
                "INCONCLUSIVE",
                "BALANCES",
                "OVER_SUPPRESSES",
                "HARMS",
                "INERT",
                "MIXED",
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
        "run_schedule": {f"P{i}": list(arm_order(i)) for i in range(10)},
        "combined_endpoint": frozen_plan()["combined_endpoint_rule"],
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
    definition: dict, *, stop_after_pairs: int | None = None
) -> dict:
    all_runs: dict[str, dict] = {}
    completed_pairs = 0
    for index, entry in enumerate(definition["entries"]):
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
        for order_index, arm in enumerate(arm_order(index), start=1):
            checkpoint = _load_checkpoint(entry, arm)
            if checkpoint is None:
                print(
                    f"START {panel_entry} {arm} order={order_index}/2 at {utc_now()}",
                    flush=True,
                )
                started = utc_now()
                summary = run_arm(
                    cards,
                    panel_entry=panel_entry,
                    stock_guard_enabled=arm == "WORKSPACE_N8_STOCK_GUARD",
                )
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
                guard = summary["stock_guard"]
                print(
                    f"DONE {panel_entry} {arm}: exp={summary['strategic_expansions']} "
                    f"fd={summary['minimum_face_down']} "
                    f"stock={summary['minimum_expanded_stock_rows']} "
                    f"EC={summary['EMPTY_CREATABLE']['expanded']} "
                    f"AE={summary['ACTUAL_EMPTY']['expanded']} "
                    f"forced={summary['workspace']['forced_services']} "
                    f"withheld={guard['forced_services_withheld']} "
                    f"ordinary={summary['workspace']['productive_descendants_ordinary_serviced']} "
                    f"tactical={summary['tactical_nodes']} elapsed={summary['elapsed_s']:.1f}s",
                    flush=True,
                )
            else:
                print(f"RESUME {panel_entry} {arm} from checkpoint", flush=True)
            all_runs[panel_entry][arm] = checkpoint["summary"]
        completed_pairs += 1
        if stop_after_pairs is not None and completed_pairs >= stop_after_pairs:
            break
    return all_runs


def paired_rows(runs: dict) -> list[dict]:
    rows = []
    for index in range(10):
        panel_entry = f"P{index}"
        if panel_entry not in runs or any(arm not in runs[panel_entry] for arm in ARMS):
            continue
        n8 = runs[panel_entry]["WORKSPACE_N8"]
        guarded = runs[panel_entry]["WORKSPACE_N8_STOCK_GUARD"]
        face_down_delta = guarded["minimum_face_down"] - n8["minimum_face_down"]
        stock_delta = (
            guarded["minimum_expanded_stock_rows"]
            - n8["minimum_expanded_stock_rows"]
        )
        rows.append(
            {
                "panel_entry": panel_entry,
                "active_predeclared": panel_entry in ACTIVE_DEALS,
                "run_order": list(arm_order(index)),
                "minimum_face_down": {
                    "N8": n8["minimum_face_down"],
                    "STOCK_GUARD": guarded["minimum_face_down"],
                    "delta": face_down_delta,
                },
                "minimum_expanded_stock_rows": {
                    "N8": n8["minimum_expanded_stock_rows"],
                    "STOCK_GUARD": guarded["minimum_expanded_stock_rows"],
                    "delta": stock_delta,
                },
                "combined_endpoint": combined_endpoint(face_down_delta, stock_delta),
                "guard": guarded["stock_guard"],
                "ordinary_serviced_productive_descendants": {
                    "N8": n8["workspace"]["productive_descendants_ordinary_serviced"],
                    "STOCK_GUARD": guarded["workspace"][
                        "productive_descendants_ordinary_serviced"
                    ],
                },
                "tactical_node_ratio": guarded["tactical_nodes"] / n8["tactical_nodes"],
                "elapsed_time_ratio": guarded["elapsed_s"] / n8["elapsed_s"],
                "maximum_foundations": {
                    "N8": n8["maximum_foundations"],
                    "STOCK_GUARD": guarded["maximum_foundations"],
                },
                "credit_balance": general._credit_balance(n8, guarded),
            }
        )
    return rows


def _paired_counts(rows: list[dict], key: str) -> dict:
    deltas = [row[key]["delta"] for row in rows]
    return {
        "improve": sum(delta < 0 for delta in deltas),
        "tie": sum(delta == 0 for delta in deltas),
        "worsen": sum(delta > 0 for delta in deltas),
        "median_delta": statistics.median(deltas) if deltas else None,
    }


def aggregate(rows: list[dict], runs: dict) -> dict:
    tactical = [row["tactical_node_ratio"] for row in rows]
    elapsed = [row["elapsed_time_ratio"] for row in rows]
    active = [row for row in rows if row["active_predeclared"]]
    decisions = Counter(row["combined_endpoint"] for row in rows)
    active_decisions = Counter(row["combined_endpoint"] for row in active)

    def ordinary_total(selected_rows, arm):
        return sum(
            runs[row["panel_entry"]][arm]["workspace"][
                "productive_descendants_ordinary_serviced"
            ]
            for row in selected_rows
        )

    return {
        "completed_pairs": len(rows),
        "face_down": _paired_counts(rows, "minimum_face_down"),
        "stock_progression": _paired_counts(rows, "minimum_expanded_stock_rows"),
        "ordinary_serviced_productive_descendants": {
            arm: ordinary_total(rows, arm) for arm in ARMS
        },
        "guard_firing_count": sum(
            row["guard"]["forced_services_withheld"] for row in rows
        ),
        "active_deals_guard_fired": [
            row["panel_entry"]
            for row in active
            if row["guard"]["forced_services_withheld"] > 0
        ],
        "all_deals_guard_fired": [
            row["panel_entry"]
            for row in rows
            if row["guard"]["forced_services_withheld"] > 0
        ],
        "combined_endpoint": {
            name: decisions[name] for name in ("WIN", "TRADEOFF", "NEUTRAL", "LOSS")
        },
        "active_subset": {
            "face_down": _paired_counts(active, "minimum_face_down"),
            "stock_progression": _paired_counts(active, "minimum_expanded_stock_rows"),
            "ordinary_serviced_productive_descendants": {
                arm: ordinary_total(active, arm) for arm in ARMS
            },
            "combined_endpoint": {
                name: active_decisions[name]
                for name in ("WIN", "TRADEOFF", "NEUTRAL", "LOSS")
            },
        },
        "cost": {
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
        },
        "credit_balance_flagged_deals": [
            row["panel_entry"] for row in rows if row["credit_balance"]["flagged"]
        ],
    }


def _retains_half_historical_advantage(panel_entry: str, guarded_fd: int) -> bool:
    context = HISTORICAL_CONTEXT[panel_entry]
    prior_advantage = (
        context["NO_WORKSPACE"]["minimum_face_down"]
        - context["N8"]["minimum_face_down"]
    )
    required_advantage = max(1, prior_advantage / 2)
    remaining_advantage = (
        context["NO_WORKSPACE"]["minimum_face_down"] - guarded_fd
    )
    return remaining_advantage >= required_advantage


def classify(rows: list[dict], runs: dict, summary: dict) -> str:
    if len(rows) != 10:
        return "STOCK_GUARD_INCONCLUSIVE"
    valid = all(
        not arm["replay_failures"]
        and not arm["corrected_cost_inconsistencies"]
        and arm["frontier"]["duplicate_entries"] == 0
        and arm["resource_planner_calls"] == 0
        for deal_runs in runs.values()
        for arm in deal_runs.values()
    )
    if not valid:
        return "STOCK_GUARD_INCONCLUSIVE"
    by_id = {row["panel_entry"]: row for row in rows}
    recovered = [
        panel_entry
        for panel_entry in TRADEOFF_DEALS
        if by_id[panel_entry]["minimum_expanded_stock_rows"]["delta"] < 0
    ]
    retained = [
        panel_entry
        for panel_entry in recovered
        if _retains_half_historical_advantage(
            panel_entry,
            by_id[panel_entry]["minimum_face_down"]["STOCK_GUARD"],
        )
    ]
    active_outcomes = summary["active_subset"]["combined_endpoint"]
    if (
        set(recovered) == set(TRADEOFF_DEALS)
        and set(retained) == set(TRADEOFF_DEALS)
        and active_outcomes["WIN"] >= 2
    ):
        return "STOCK_GUARD_BALANCES_WORKSPACE_SERVICE"
    if recovered and not retained:
        return "STOCK_GUARD_OVER_SUPPRESSES_WORKSPACE"
    if active_outcomes["LOSS"] >= 2:
        return "STOCK_GUARD_HARMS_SEARCH"
    if summary["guard_firing_count"] == 0 or all(
        by_id[panel_entry]["combined_endpoint"] == "NEUTRAL"
        for panel_entry in TRADEOFF_DEALS
    ):
        return "STOCK_GUARD_INERT"
    return "STOCK_GUARD_MIXED"


def build_result(definition: dict, runs: dict) -> dict:
    rows = paired_rows(runs)
    summary = aggregate(rows, runs)
    gates = {
        "all_twenty_runs_complete": len(rows) == 10,
        "frozen_panel_unchanged": definition == general.panel_definition(),
        "alternating_order_observed": all(
            row["run_order"] == list(arm_order(index))
            for index, row in enumerate(rows)
        ),
        "fixed_N8_and_threshold_one": (
            service.SERVICE_INTERVAL == 8 and STOCK_LAG_THRESHOLD == 1
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
        "status": "COMPLETE" if len(rows) == 10 else "PARTIAL",
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
    parser.add_argument("--stop-after-pairs", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plan_data = write_frozen_plan()
    if args.freeze_plan_only:
        print(json.dumps(plan_data, indent=2, sort_keys=True))
        return 0
    definition = general.panel_definition()
    runs = execute_missing_runs(definition, stop_after_pairs=args.stop_after_pairs)
    result = build_result(definition, runs)
    _write_json_atomic(RESULT_PATH, result)
    print(
        f"VERDICT {result['verdict']} pairs={result['aggregate']['completed_pairs']} "
        f"withheld={result['aggregate']['guard_firing_count']}",
        flush=True,
    )
    print(f"WROTE {RESULT_PATH}", flush=True)
    return 0 if all(result["gates"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
