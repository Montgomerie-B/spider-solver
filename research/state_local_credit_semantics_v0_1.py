#!/usr/bin/env python3
"""Three-arm state-local strategic-credit experiment.

This extends the common-priority A/B harness; it does not duplicate the
controller, successor generator, or base lifecycle instrumentation.
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "research"))

import common_priority_schema_ab_v0_1 as prior
import spider.planner.anytime_controller as controller
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.planner.anytime_controller import (
    FrontierPrioritySchema,
    StrategicCreditPropagation,
)


BASE_SHA = "20383df3567cef7823c463c35fb8c773ff285f0b"
RESULT_PATH = ROOT / "docs" / "research" / "state_local_credit_semantics_v0_1.json"


def _counter_json(counter: Counter) -> dict:
    return {str(key): value for key, value in sorted(counter.items(), key=lambda item: str(item[0]))}


class CreditFlowObserver(prior.Observer):
    """Add credit provenance and generated structural lifecycle to the prior observer."""

    def __init__(self, opening: SpiderState) -> None:
        super().__init__(opening)
        self.tactical_nodes_by_expansion_credit = Counter()

    def install(self) -> None:
        super().install()
        observed_generate = controller.generate_strategic_successors
        obs = self

        def wrapped_generate(node, cards, **kwargs):
            telemetry = kwargs.get("telemetry")
            before = telemetry.tactical_nodes if telemetry is not None else 0
            successors = observed_generate(node, cards, **kwargs)
            after = telemetry.tactical_nodes if telemetry is not None else before
            obs.tactical_nodes_by_expansion_credit[int(node.credit_level)] += after - before
            return successors

        controller.generate_strategic_successors = wrapped_generate

    def _event_lifecycle(self, event: dict) -> dict:
        node_id = event["child_node_id"]
        node = self.nodes.get(node_id) if node_id is not None else None
        return {
            **event,
            "child_credit": None if node is None else node["credit"],
            "live": False if node is None else node.get("live", False),
            "popped": False if node is None else node["popped"],
            "expanded": False if node is None else node["expanded"],
            "trimmed": False if node is None else node["trimmed"],
            "trim_expansion": None if node is None else node["trim_expansion"],
            "insertion_rank": None if node is None else node["insertion_rank"],
            "best_rank": None if node is None else node["best_rank"],
            "last_rank": None if node is None else node["last_rank"],
        }

    def _structural_metrics(self, flag: str) -> dict:
        rows = [self._event_lifecycle(event) for event in self.events if event["child_geometry"][flag]]
        metrics = {"generated": len(rows)}
        for stage in ("retained", "live", "popped", "expanded", "trimmed"):
            metrics[stage] = sum(bool(row[stage]) for row in rows)
        metrics["unique"] = {
            "generated": len({row["child_digest"] for row in rows}),
            "retained": len({row["child_digest"] for row in rows if row["retained"]}),
            "popped": len({row["child_digest"] for row in rows if row["popped"]}),
            "expanded": len({row["child_digest"] for row in rows if row["expanded"]}),
        }
        return {"metrics": metrics, "lifecycle": rows}

    def _credit_flow_chain(self, novel: list[dict]) -> dict | None:
        if not novel:
            return None
        first = min(novel, key=lambda row: (row["generated_expansion"], row["event_id"]))
        first = self._event_lifecycle(first)
        chain = []
        child_id = first["child_node_id"]
        for generation in range(1, 3):
            if child_id is None or child_id not in self.nodes:
                break
            node = self.nodes[child_id]
            children = [
                self._event_lifecycle(event)
                for event in self.events
                if event["parent_node_id"] == child_id and event["retained"]
            ]
            serviced = bool(node["expanded"])
            preferred = next(
                (
                    event for event in children
                    if event["child_node_id"] is not None
                    and self.nodes[event["child_node_id"]]["expanded"]
                ),
                children[0] if children else None,
            )
            chain.append(
                {
                    "generation": generation,
                    "node_id": child_id,
                    "digest": node["digest"],
                    "g": node["g"],
                    "credit": node["credit"],
                    "popped": node["popped"],
                    "expanded": serviced,
                    "selected_natural_child": preferred,
                }
            )
            if not serviced or preferred is None:
                break
            child_id = preferred["child_node_id"]
        return {"first_broader_successor": first, "natural_descendant_chain": chain}

    def extended_summary(self, result) -> dict:
        base = self.summary(result)
        clean_generated = {
            event["child_digest"] for event in self.events if event["parent_credit"] == 0
        }
        novel = [
            event for event in self.events
            if event["retained"]
            and event["parent_credit"] > 0
            and event["child_digest"] not in clean_generated
        ]
        expanded_clean = {
            record["digest"]
            for record in self.nodes.values()
            if record["credit"] == 0 and record["expanded"]
        }
        novel_clean_expanded = {
            event["child_digest"]
            for event in novel
            if event["child_digest"] in expanded_clean
        }
        by_parent_credit = Counter(event["parent_credit"] for event in novel)
        by_family = Counter(event["kind"] for event in novel)
        transition_counts = Counter()
        ordinary_pushes = Counter()
        unique_retained_by_parent_credit = defaultdict(set)
        unique_retained_by_child_credit = defaultdict(set)
        for event in self.events:
            if not event["retained"] or event["child_node_id"] is None:
                continue
            child_credit = self.nodes[event["child_node_id"]]["credit"]
            transition_counts[(event["parent_credit"], child_credit)] += 1
            ordinary_pushes[child_credit] += 1
            unique_retained_by_parent_credit[event["parent_credit"]].add(event["child_digest"])
            unique_retained_by_child_credit[child_credit].add(event["child_digest"])
        widening_pushes = Counter(
            self.nodes[node_id]["credit"]
            for node_id in self.pushes
            if self.nodes[node_id]["origin"] == "WIDENING"
        )
        ordinary_origin_pushes = Counter(
            self.nodes[node_id]["credit"]
            for node_id in self.pushes
            if self.nodes[node_id]["origin"] == "SUCCESSOR"
        )
        actual_empty = dict(base["actual_empty"])
        actual_empty["popped"] = sum(
            self.nodes[node_id]["geometry"]["empties"] > 0 for node_id in self.pops
        )
        r2 = self._structural_metrics("R2")
        r3 = self._structural_metrics("R3")
        r3_expanded_ids = {
            event["child_node_id"]
            for event in self.events
            if event["child_geometry"]["R3"]
            and event["child_node_id"] is not None
            and self.nodes[event["child_node_id"]]["expanded"]
        }
        r3_successors = {
            str(node_id): [
                self._event_lifecycle(event)
                for event in self.events
                if event["parent_node_id"] == node_id
            ]
            for node_id in sorted(r3_expanded_ids)
        }
        base.update(
            {
                "actual_empty": actual_empty,
                "credit_flow": {
                    "widening_pushes_by_result_credit": _counter_json(widening_pushes),
                    "ordinary_pushes_by_child_credit": _counter_json(ordinary_origin_pushes),
                    "ordinary_parent_to_child": {
                        f"{parent}->{child}": count
                        for (parent, child), count in sorted(transition_counts.items())
                    },
                    "unique_retained_child_digests_by_parent_credit": {
                        str(credit): len(unique_retained_by_parent_credit[credit])
                        for credit in range(5)
                    },
                    "unique_retained_child_digests_by_child_credit": {
                        str(credit): len(unique_retained_by_child_credit[credit])
                        for credit in range(5)
                    },
                    "tactical_nodes_by_expansion_credit_available": {
                        str(credit): self.tactical_nodes_by_expansion_credit[credit]
                        for credit in range(5)
                    },
                },
                "novel_broader_coverage": {
                    "total": len(novel),
                    "unique_digests": len({event["child_digest"] for event in novel}),
                    "by_parent_credit": _counter_json(by_parent_credit),
                    "by_successor_family": dict(sorted(by_family.items())),
                    "subsequently_received_clean_expansion": len(novel_clean_expanded),
                    "unique_digests_subsequently_clean_expanded": len(novel_clean_expanded),
                    "clean_expanded_digests": sorted(novel_clean_expanded),
                },
                "first_useful_broader_credit": self._credit_flow_chain(novel),
                "R2": r2,
                "R3": r3,
                "R3_expansion_successors": r3_successors,
            }
        )
        return base


def assert_config(config) -> None:
    prior.assert_config(config)
    if config.strategic_credit_propagation not in StrategicCreditPropagation:
        raise AssertionError(config.strategic_credit_propagation)


def run_arm(
    opening: SpiderState,
    cards,
    *,
    schema: FrontierPrioritySchema,
    propagation: StrategicCreditPropagation,
):
    random.seed(prior.SEED)
    config = prior.production_shadow._production_config(
        seconds=900.0, expansions=400, nodes=300_000
    )
    config = replace(
        config,
        frontier_priority_schema=schema,
        strategic_credit_propagation=propagation,
    )
    assert_config(config)
    observer = CreditFlowObserver(opening)
    observer.install()
    try:
        result = controller.solve_anytime(opening.clone(), cards, None, config)
        summary = observer.extended_summary(result)
    finally:
        observer.restore()
    summary["priority_schema"] = schema.value
    summary["credit_propagation"] = propagation.value
    return summary


def expansion_share(arm: dict, credit: int) -> float:
    return arm["credit"][str(credit)]["expansions"] / arm["strategic_expansions"]


def classify(arms: dict) -> str:
    inherited = arms["COMMON_STAGE0_INHERITED"]
    local = arms["COMMON_STAGE0_STATE_LOCAL"]
    local_wider = sum(local["credit"][str(c)]["expansions"] for c in range(1, 5))
    local_novel = local["novel_broader_coverage"]["total"]
    reset_ok = all(
        child == "0"
        for transition in local["credit_flow"]["ordinary_parent_to_child"]
        for parent, child in [transition.split("->")]
        if parent != "0"
    )
    redistributed = (
        expansion_share(local, 4) <= expansion_share(inherited, 4) - 0.25
        and expansion_share(local, 4) <= 0.50
        and expansion_share(local, 0) >= expansion_share(inherited, 0) + 0.15
    )
    if local_wider == 0 or local_novel == 0:
        return "STATE_LOCAL_CREDIT_COLLAPSES_TO_CLEAN"
    if expansion_share(local, 4) >= 0.75:
        return "STATE_LOCAL_CREDIT_STILL_AVALANCHES"
    if reset_ok and redistributed:
        return "STATE_LOCAL_CREDIT_CONFIRMED"
    if local["novel_broader_coverage"]["subsequently_received_clean_expansion"] == 0:
        return "STATE_LOCAL_CREDIT_LOSES_USEFUL_COVERAGE"
    return "INCONCLUSIVE"


def main() -> int:
    cards = tuple(load_deal(prior.DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    definitions = (
        (
            "LEGACY",
            FrontierPrioritySchema.LEGACY,
            StrategicCreditPropagation.INHERITED,
        ),
        (
            "COMMON_STAGE0_INHERITED",
            FrontierPrioritySchema.COMMON_STAGE0,
            StrategicCreditPropagation.INHERITED,
        ),
        (
            "COMMON_STAGE0_STATE_LOCAL",
            FrontierPrioritySchema.COMMON_STAGE0,
            StrategicCreditPropagation.STATE_LOCAL,
        ),
    )
    arms = {}
    for label, schema, propagation in definitions:
        print(f"Starting {label}", flush=True)
        arms[label] = run_arm(
            opening,
            cards,
            schema=schema,
            propagation=propagation,
        )
        arm = arms[label]
        print(
            f"{label}: stop={arm['stop_reason']} expansions={arm['strategic_expansions']} "
            f"elapsed={arm['elapsed_s']:.1f}s tactical={arm['tactical_nodes']} "
            f"credit={[arm['credit'][str(c)]['expansions'] for c in range(5)]} "
            f"novel={arm['novel_broader_coverage']['total']}",
            flush=True,
        )
    legacy = arms["LEGACY"]
    inherited = arms["COMMON_STAGE0_INHERITED"]
    local = arms["COMMON_STAGE0_STATE_LOCAL"]
    gates = {
        "legacy_reproduces_clean_starvation": (
            legacy["strategic_expansions"] == 400
            and legacy["credit"]["0"]["expansions"] == 400
        ),
        "inherited_reproduces_credit4_avalanche": (
            inherited["credit"]["4"]["expansions"] >= 350
        ),
        "all_replay_and_cost_integrity": all(
            not arm["replay_failures"] and not arm["corrected_cost_inconsistencies"]
            for arm in arms.values()
        ),
        "state_local_ordinary_broad_children_reset_clean": all(
            child == "0"
            for transition in local["credit_flow"]["ordinary_parent_to_child"]
            for parent, child in [transition.split("->")]
            if parent != "0"
        ),
        "state_local_widens": sum(
            local["credit"][str(c)]["expansions"] for c in range(1, 5)
        ) > 0,
        "state_local_novel_broader_coverage": local["novel_broader_coverage"]["total"] > 0,
        "state_local_materially_redistributes_from_credit4": (
            expansion_share(local, 4) <= 0.50
            and expansion_share(local, 4) <= expansion_share(inherited, 4) - 0.25
            and expansion_share(local, 0) >= expansion_share(inherited, 0) + 0.15
        ),
    }
    verdict = classify(arms)
    payload = {
        "experiment": "state_local_credit_semantics_v0_1",
        "base_sha": BASE_SHA,
        "deal": 4925153,
        "seed": prior.SEED,
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
    return 0 if gates["all_replay_and_cost_integrity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
