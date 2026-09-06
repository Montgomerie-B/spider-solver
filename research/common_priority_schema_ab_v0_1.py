#!/usr/bin/env python3
"""Causal A/B harness for legacy versus common Stage-0 frontier keys."""

from __future__ import annotations

import hashlib
import heapq
import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import resource_excavation_natural_shadow_v0_1 as production_shadow
import spider.planner.anytime_controller as controller
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicSearchNode,
    _node_priority,
)
from spider.planner.receiver_uncover import _movable_run_length
from spider.state_identity import canonical_state_key


BASE_SHA = "9e3240cdd30fbfdc8bf9f3cbc324caad2c91085b"
DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "docs" / "research" / "common_priority_schema_ab_v0_1.json"
SEED = 0
TARGET_DIGESTS = ("1c3d3ec77bf164ad", "edb1f739a3100867")


def digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def action_json(action):
    if action == ("deal",) or action == "deal":
        return "deal"
    return list(action) if not isinstance(action, str) else action


def action_key(actions) -> tuple:
    return tuple(tuple(a) if not isinstance(a, str) else a for a in actions)


def geometry(state: SpiderState) -> dict:
    face_down = sum(len(col.face_down) for col in state.columns)
    fully_revealed = sum(bool(col.face_up) and not col.face_down for col in state.columns)
    empties = sum(col.is_empty() for col in state.columns)
    empty_creatable = False
    for src, col in enumerate(state.columns):
        if col.face_down or not col.face_up:
            continue
        count = len(col.face_up)
        if _movable_run_length(state, src) != count:
            continue
        if any(
            dst != src
            and not state.columns[dst].is_empty()
            and state.can_move(src, dst, count)
            for dst in range(len(state.columns))
        ):
            empty_creatable = True
            break
    return {
        "face_down": face_down,
        "fully_revealed": fully_revealed,
        "empties": empties,
        "empty_creatable": empty_creatable,
        "foundations": len(state.foundations),
        "stock_rows": len(state.stock) // 10,
        "R2": fully_revealed > 0,
        "R3": empty_creatable,
    }


def histogram(values) -> dict:
    counts = Counter(int(value) for value in values)
    return {str(credit): counts[credit] for credit in range(5)}


class Observer:
    def __init__(self, opening: SpiderState) -> None:
        self.opening = opening
        self.nodes: dict[int, dict] = {}
        self.events: list[dict] = []
        self.events_by_signature = defaultdict(list)
        self.pushes: list[int] = []
        self.pops: list[int] = []
        self.expansions: list[int] = []
        self.frontier = None
        self.current_popped = None
        self.trims_by_credit = Counter()
        self.retained_by_parent_credit = Counter()
        self.replay_failures: list[dict] = []
        self.cost_inconsistencies: list[dict] = []
        self._originals = {}

    @staticmethod
    def _is_frontier_item(item) -> bool:
        return (
            isinstance(item, tuple)
            and len(item) == 3
            and isinstance(item[2], StrategicSearchNode)
        )

    def _origin(self, node: StrategicSearchNode) -> str:
        parent = self.current_popped
        if parent is None:
            return "ROOT"
        if (
            digest(node.state) == parent["digest"]
            and int(node.credit_level) == parent["credit"] + 1
            and node.g == parent["g"]
            and node.depth == parent["depth"]
        ):
            return "WIDENING"
        return "SUCCESSOR"

    def _node_record(self, node: StrategicSearchNode, *, origin: str | None = None) -> dict:
        record = self.nodes.get(node.node_id)
        if record is None:
            geom = geometry(node.state)
            record = {
                "node_id": node.node_id,
                "digest": digest(node.state),
                "g": int(node.g),
                "depth": int(node.depth),
                "credit": int(node.credit_level),
                "origin": origin or "REKEY",
                "schema": node.frontier_priority_schema.value,
                "analysis_attached_at_last_key": node.analysis is not None,
                "geometry": geom,
                "insertion_expansion": len(self.expansions),
                "insertion_rank": None,
                "best_rank": None,
                "last_rank": None,
                "popped": False,
                "expanded": False,
                "trimmed": False,
                "trim_expansion": None,
            }
            self.nodes[node.node_id] = record
        else:
            record["analysis_attached_at_last_key"] = node.analysis is not None
        return record

    def _snapshot_ranks(self, heap) -> None:
        if not heap or not all(self._is_frontier_item(item) for item in heap):
            return
        self.frontier = heap
        ordered = sorted(heap)
        for rank, item in enumerate(ordered, start=1):
            record = self._node_record(item[2])
            if record["insertion_rank"] is None:
                record["insertion_rank"] = rank
            record["best_rank"] = rank if record["best_rank"] is None else min(record["best_rank"], rank)
            record["last_rank"] = rank

    def install(self) -> None:
        self._originals = {
            "push": heapq.heappush,
            "pop": heapq.heappop,
            "heapify": heapq.heapify,
            "generate": controller.generate_strategic_successors,
            "record": controller._record_transition,
            "trim": controller._trim_frontier_with_checkpoint_diversity,
        }
        obs = self

        def wrapped_push(heap, item):
            result = obs._originals["push"](heap, item)
            if obs._is_frontier_item(item):
                record = obs._node_record(item[2], origin=obs._origin(item[2]))
                obs.pushes.append(record["node_id"])
                obs._snapshot_ranks(heap)
            return result

        def wrapped_pop(heap):
            item = obs._originals["pop"](heap)
            if obs._is_frontier_item(item):
                record = obs._node_record(item[2])
                record["popped"] = True
                record["last_rank"] = 1
                obs.pops.append(record["node_id"])
                obs.current_popped = record
                obs._snapshot_ranks(heap)
            return item

        def wrapped_heapify(heap):
            result = obs._originals["heapify"](heap)
            obs._snapshot_ranks(heap)
            return result

        def wrapped_generate(node, cards, **kwargs):
            successors = obs._originals["generate"](node, cards, **kwargs)
            record = obs._node_record(node)
            record["expanded"] = True
            obs.expansions.append(node.node_id)
            for successor in successors:
                actions = tuple(successor.actions)
                child_digest = digest(successor.end_state)
                event = {
                    "event_id": len(obs.events),
                    "parent_node_id": node.node_id,
                    "parent_digest": record["digest"],
                    "parent_credit": int(node.credit_level),
                    "kind": successor.kind.value,
                    "category": successor.category,
                    "actions": [action_json(action) for action in actions],
                    "cost": int(successor.corrected_cost),
                    "child_digest": child_digest,
                    "child_geometry": geometry(successor.end_state),
                    "generated_expansion": len(obs.expansions),
                    "independent_replay_verified": bool(successor.independent_replay_verified),
                    "proof_pruning_allowed": bool(successor.proof_pruning_allowed),
                    "retained": False,
                    "child_node_id": None,
                }
                obs.events.append(event)
                sig = (node.node_id, child_digest, action_key(actions), int(successor.corrected_cost))
                obs.events_by_signature[sig].append(event)
            return successors

        def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
            actions = tuple(successor.actions)
            sig = (
                parent.node_id,
                digest(successor.end_state),
                action_key(actions),
                int(successor.corrected_cost),
            )
            candidates = obs.events_by_signature.get(sig, ())
            event = next((row for row in reversed(candidates) if not row["retained"]), None)
            if event is not None:
                event["retained"] = True
                event["child_node_id"] = child.node_id
            obs.retained_by_parent_credit[int(parent.credit_level)] += 1
            if child.g != parent.g + successor.corrected_cost:
                obs.cost_inconsistencies.append(
                    {"parent": parent.node_id, "child": child.node_id, "parent_g": parent.g,
                     "edge_cost": successor.corrected_cost, "child_g": child.g}
                )
            replay = obs.opening.clone()
            try:
                replay_cost = replay_actions(replay, list(child.actions))
                if replay_cost != child.g or digest(replay) != digest(child.state):
                    raise ValueError(
                        f"replay cost/digest mismatch: cost={replay_cost} expected={child.g}"
                    )
            except (ValueError, AssertionError, IndexError) as exc:
                obs.replay_failures.append(
                    {"child": child.node_id, "digest": digest(child.state), "error": str(exc)}
                )
            return obs._originals["record"](
                parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
            )

        def wrapped_trim(frontier, **kwargs):
            before = Counter(item[1] for item in frontier)
            by_id = {item[1]: item[2] for item in frontier}
            kept = obs._originals["trim"](frontier, **kwargs)
            after = Counter(item[1] for item in kept)
            for node_id, count in (before - after).items():
                node = by_id[node_id]
                obs.trims_by_credit[int(node.credit_level)] += count
                if after[node_id] == 0:
                    record = obs._node_record(node)
                    record["trimmed"] = True
                    record["trim_expansion"] = len(obs.expansions)
            obs._snapshot_ranks(kept)
            return kept

        heapq.heappush = controller.heapq.heappush = wrapped_push
        heapq.heappop = controller.heapq.heappop = wrapped_pop
        heapq.heapify = controller.heapq.heapify = wrapped_heapify
        controller.generate_strategic_successors = wrapped_generate
        controller._record_transition = wrapped_record
        controller._trim_frontier_with_checkpoint_diversity = wrapped_trim

    def restore(self) -> None:
        heapq.heappush = controller.heapq.heappush = self._originals["push"]
        heapq.heappop = controller.heapq.heappop = self._originals["pop"]
        heapq.heapify = controller.heapq.heapify = self._originals["heapify"]
        controller.generate_strategic_successors = self._originals["generate"]
        controller._record_transition = self._originals["record"]
        controller._trim_frontier_with_checkpoint_diversity = self._originals["trim"]

    def summary(self, result) -> dict:
        live_items = list(self.frontier or [])
        live_ids = [item[1] for item in live_items if self._is_frontier_item(item)]
        live_set = set(live_ids)
        for node_id, record in self.nodes.items():
            record["live"] = node_id in live_set
        clean_generated = {
            event["child_digest"] for event in self.events if event["parent_credit"] == 0
        }
        novel_broad = [
            event for event in self.events
            if event["retained"]
            and event["parent_credit"] > 0
            and event["child_digest"] not in clean_generated
        ]
        structural = [
            record for record in self.nodes.values()
            if record["geometry"]["R2"] or record["geometry"]["R3"]
        ]
        targets = {
            target: [record for record in self.nodes.values() if record["digest"] == target]
            for target in TARGET_DIGESTS
        }
        actual_empty = {
            "generated": sum(event["child_geometry"]["empties"] > 0 for event in self.events),
            "retained": sum(
                event["retained"] and event["child_geometry"]["empties"] > 0
                for event in self.events
            ),
            "expanded": sum(
                self.nodes[node_id]["geometry"]["empties"] > 0 for node_id in self.expansions
            ),
        }
        stock = {}
        for stage, rows in (
            ("generated", [event["child_geometry"] for event in self.events]),
            ("retained", [event["child_geometry"] for event in self.events if event["retained"]]),
            ("expanded", [self.nodes[node_id]["geometry"] for node_id in self.expansions]),
        ):
            stock[stage] = dict(sorted(Counter(row["stock_rows"] for row in rows).items()))
        credit = {}
        for value in range(5):
            credit[str(value)] = {
                "pushes": sum(self.nodes[node_id]["credit"] == value for node_id in self.pushes),
                "pops": sum(self.nodes[node_id]["credit"] == value for node_id in self.pops),
                "expansions": sum(self.nodes[node_id]["credit"] == value for node_id in self.expansions),
                "trims": self.trims_by_credit[value],
                "retained_successors_produced": self.retained_by_parent_credit[value],
            }
        t = result.telemetry
        return {
            "schema": next(iter(self.nodes.values()))["schema"],
            "elapsed_s": round(result.elapsed_seconds, 6),
            "stop_reason": result.stop_reason,
            "strategic_expansions": result.strategic_expansions,
            "tactical_nodes": result.tactical_nodes,
            "successors_generated": t.generated,
            "successors_retained": t.retained,
            "tt": {"new": t.tt_new, "improved": t.tt_improved, "suppressed": t.tt_suppressed},
            "proof_pruned": t.proof_pruned,
            "frontier": {
                "size": len(live_ids),
                "distinct_node_ids": len(set(live_ids)),
                "duplicate_entries": len(live_ids) - len(set(live_ids)),
                "credit_histogram": histogram(self.nodes[node_id]["credit"] for node_id in live_ids),
            },
            "minimum_face_down": min(
                [geometry(self.opening)["face_down"]]
                + [event["child_geometry"]["face_down"] for event in self.events]
            ),
            "maximum_foundations": max(
                [0] + [event["child_geometry"]["foundations"] for event in self.events]
            ),
            "actual_empty": actual_empty,
            "stock_progression": stock,
            "credit": credit,
            "broader_retained_novel_vs_all_clean_generated": novel_broad,
            "structural_nodes": structural,
            "target_digests": targets,
            "replay_failures": self.replay_failures,
            "corrected_cost_inconsistencies": self.cost_inconsistencies,
            "independent_replay_false": sum(
                not event["independent_replay_verified"] for event in self.events
            ),
            "proof_pruning_successor_flags": sum(
                event["proof_pruning_allowed"] for event in self.events
            ),
        }


def assert_config(config) -> None:
    actual = (
        config.max_strategic_expansions,
        config.max_tactical_nodes,
        config.wall_clock_limit_s,
        config.max_frontier_size,
        config.max_successors_per_expansion,
        int(config.max_credit_level),
        config.enable_whole_deal_scheduler,
        config.enable_tactical_resource_allocation,
        config.target_foundation_count,
    )
    expected = (400, 300_000, 900.0, 256, 10, 4, True, True, 2)
    if actual != expected:
        raise AssertionError({"actual": actual, "expected": expected})


def comparator_invariant(opening: SpiderState, schema: FrontierPrioritySchema) -> bool:
    stage0 = controller.analyze_stage0_state(opening, spent_cost=0, incumbent_cost=None)
    base = StrategicSearchNode(
        77, opening.clone(), 0, (), None, None, 0,
        controller.StrategicCreditLevel.CLEAN, None, stage0,
        frontier_priority_schema=schema,
    )
    analysed = replace(
        base,
        analysis=SimpleNamespace(
            progress=SimpleNamespace(ordering_key=lambda: (1,) + (0,) * 21)
        ),
    )
    if schema is FrontierPrioritySchema.COMMON_STAGE0:
        return _node_priority(base) == _node_priority(analysed)
    return _node_priority(base) != _node_priority(analysed)


def run_arm(opening, cards, schema: FrontierPrioritySchema):
    random.seed(SEED)
    config = production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    config = replace(config, frontier_priority_schema=schema)
    assert_config(config)
    observer = Observer(opening)
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        summary = observer.summary(result)
    finally:
        observer.restore()
    return summary


def main() -> int:
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    gates = {
        "control_has_legacy_difference": comparator_invariant(
            opening, FrontierPrioritySchema.LEGACY
        ),
        "common_stage0_analysis_invariant": comparator_invariant(
            opening, FrontierPrioritySchema.COMMON_STAGE0
        ),
    }
    print("Comparator gates", gates, flush=True)
    if not all(gates.values()):
        raise AssertionError(gates)
    arms = {}
    for label, schema in (
        ("CONTROL", FrontierPrioritySchema.LEGACY),
        ("COMMON_STAGE0", FrontierPrioritySchema.COMMON_STAGE0),
    ):
        print(f"Starting {label}", flush=True)
        arms[label] = run_arm(opening, cards, schema)
        arm = arms[label]
        print(
            f"{label}: stop={arm['stop_reason']} expansions={arm['strategic_expansions']} "
            f"elapsed={arm['elapsed_s']:.1f}s frontier={arm['frontier']['size']} "
            f"credits={arm['credit']}",
            flush=True,
        )
    control = arms["CONTROL"]
    treatment = arms["COMMON_STAGE0"]
    gates.update(
        {
            "control_400_clean_expansions": (
                control["strategic_expansions"] == 400
                and control["credit"]["0"]["expansions"] == 400
                and sum(control["credit"][str(c)]["expansions"] for c in range(1, 5)) == 0
            ),
            "replay_and_cost_integrity": all(
                not arm["replay_failures"] and not arm["corrected_cost_inconsistencies"]
                for arm in arms.values()
            ),
            "common_expands_broader_credit": sum(
                treatment["credit"][str(c)]["expansions"] for c in range(1, 5)
            ) > 0,
            "common_produces_novel_broader_retained": bool(
                treatment["broader_retained_novel_vs_all_clean_generated"]
            ),
        }
    )
    if gates["common_expands_broader_credit"] and gates["common_produces_novel_broader_retained"]:
        verdict = "REPRESENTATION_STARVATION_CONFIRMED"
    elif gates["common_expands_broader_credit"]:
        verdict = "REPRESENTATION_DEFECT_REAL_BUT_NOT_CAUSALLY_IMPORTANT"
    elif treatment["strategic_expansions"]:
        verdict = "COMMON_SCHEMA_INSUFFICIENT"
    else:
        verdict = "INCONCLUSIVE"
    payload = {
        "experiment": "common_priority_schema_ab_v0_1",
        "base_sha": BASE_SHA,
        "deal": 4925153,
        "seed": SEED,
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
        },
        "gates": gates,
        "verdict": verdict,
        "arms": arms,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("Gates", gates, flush=True)
    print("Verdict", verdict, flush=True)
    print("Wrote", RESULT_PATH, flush=True)
    return 0 if gates["replay_and_cost_integrity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
