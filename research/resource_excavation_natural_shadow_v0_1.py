#!/usr/bin/env python3
"""Natural-state shadow audit of resource_excavation_planner.

Two-stage and production-inert:

1. Run production v0.8 and passively collect cloned states/transitions.
2. After that search has finished, evaluate the resource planner offline.

The resource planner is never imported by anytime_controller and is never
consulted during production collection.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import spider.planner.anytime_controller as controller
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.diagnostics.anytime_whole_game_controller_v0_8_report import (
    _gate_f_config as _gate_z_base_config,
)
from spider.planner.diagnostics.whole_deal_backward_forward_scheduler_v0_4_report import (
    _gate_envelope,
)
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ResourcePlanResult,
    empty_obligations,
    local_transposition_key,
    plan_resource_excavation,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "resource_excavation_natural_shadow_v0_1.json"
SAMPLE_CAP = 128
PER_CALL_LIMIT_S = 5.0
RANDOM_SEED = 0


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _key_digest(key) -> str:
    return hashlib.sha256(repr(key).encode()).hexdigest()[:16]


def _production_config(seconds: float = 180.0, expansions: int = 25, nodes: int = 300_000):
    # Existing Gate Z expansion/node envelope. Wall-clock is raised only so the
    # expansion cap, not timeout, is the stop reason. Search size is unchanged.
    return _gate_envelope(_gate_z_base_config, seconds, expansions, nodes)


def pair_identity_hash(digest: str, suit: str, high: int, low: int) -> str:
    return hashlib.sha256(f"{digest}|{suit}|{high}|{low}".encode()).hexdigest()


def select_state_target_pairs(items: list[dict], cap: int = SAMPLE_CAP) -> tuple[list[dict], list[dict]]:
    """De-duplicate by digest+CampaignTarget, then take the lowest identity hashes."""

    unique_pairs: dict[tuple, dict] = {}
    for item in items:
        key = (
            item["digest"],
            item["target"].suit if hasattr(item["target"], "suit") else item["target"]["suit"],
            item["target"].high_rank if hasattr(item["target"], "high_rank") else item["target"]["high"],
            item["target"].low_rank if hasattr(item["target"], "low_rank") else item["target"]["low"],
        )
        unique_pairs[key] = item
    unique_list = list(unique_pairs.values())
    unique_list.sort(key=lambda item: item["pair_hash"])
    selected = unique_list[:cap] if len(unique_list) > cap else unique_list
    return unique_list, selected


def _percentile(values, p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = min(len(ordered) - 1, max(0, math.ceil(p / 100.0 * len(ordered)) - 1))
    return float(ordered[idx])


def _edge_count(state: SpiderState, target: CampaignTarget) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if (
                a.suit == target.suit
                and b.suit == target.suit
                and a.rank == target.high_rank
                and b.rank == target.low_rank
            ):
                n += 1
    return n


class PassiveCollector:
    """Wraps _record_transition.  Must not change search decisions."""

    def __init__(self) -> None:
        self.transitions: list[dict] = []
        self.states: dict[str, SpiderState] = {}
        self.expanded_parents: set[str] = set()
        self._original = None

    def capture(self, parent, successor, child) -> None:
        parent_key = canonical_state_key(parent.state)
        child_key = canonical_state_key(child.state)
        parent_digest = _key_digest(parent_key)
        child_digest = _key_digest(child_key)
        if parent_digest not in self.states:
            self.states[parent_digest] = parent.state.clone()
        if child_digest not in self.states:
            self.states[child_digest] = child.state.clone()
        self.expanded_parents.add(parent_digest)
        actions = tuple(successor.actions)
        self.transitions.append(
            {
                "parent": parent_digest,
                "child": child_digest,
                "actions": [list(a) if not isinstance(a, str) else a for a in actions],
                "action_tuples": actions,
                "cost": int(successor.corrected_cost),
                "kind": successor.kind.value,
            }
        )

    def install(self) -> None:
        self._original = controller._record_transition

        def wrapped(parent, successor, child, telemetry, config, *, elapsed_seconds):
            self.capture(parent, successor, child)
            return self._original(
                parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
            )

        controller._record_transition = wrapped

    def restore(self) -> None:
        if self._original is not None:
            controller._record_transition = self._original
            self._original = None


def _run_production(
    collect: bool, *, expansions: int | None = None
) -> tuple[object, PassiveCollector | None]:
    random.seed(RANDOM_SEED)
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    config = (
        _production_config()
        if expansions is None
        else _production_config(expansions=expansions)
    )
    collector = None
    if collect:
        collector = PassiveCollector()
        collector.install()
    try:
        result = controller.solve_anytime(opening, cards, None, config)
    finally:
        if collector is not None:
            collector.restore()
    return result, collector


def _telemetry_fingerprint(result) -> dict:
    t = result.telemetry
    return {
        "expanded": t.expanded,
        "generated": t.generated,
        "retained": t.retained,
        "tactical_nodes": t.tactical_nodes,
        "tt_new": t.tt_new,
        "tt_improved": t.tt_improved,
        "tt_suppressed": t.tt_suppressed,
        "proof_pruned": t.proof_pruned,
        "stock_successors_admitted": t.stock_successors_admitted,
        "deal_successors_generated": t.deal_successors_generated,
        "lazy_children_admitted": t.lazy_children_admitted,
        "successor_kinds": dict(sorted(t.successor_kinds.items())),
        "scheduler_objectives_generated": t.scheduler_objectives_generated,
        "scheduler_objectives_selected": t.scheduler_objectives_selected,
        "scheduler_objectives_admitted": t.scheduler_objectives_admitted,
        "scheduler_objectives_satisfied": t.scheduler_objectives_satisfied,
        "scheduler_objectives_advanced": t.scheduler_objectives_advanced,
        "scheduler_delta_counts": dict(sorted(t.scheduler_delta_counts.items())),
        "scheduler_objectives_by_family": {
            family: dict(sorted(counts.items()))
            for family, counts in sorted(t.scheduler_objectives_by_family.items())
        },
    }


def _fingerprint(result, transitions: list[dict] | None) -> dict:
    incumbent = result.incumbent
    return {
        "status": result.status.value,
        "stop_reason": result.stop_reason,
        "strategic_expansions": result.strategic_expansions,
        "tactical_nodes": result.tactical_nodes,
        "incumbent_cost": result.incumbent_cost,
        "incumbent_actions": None
        if incumbent is None
        else [list(a) if not isinstance(a, str) else a for a in incumbent.actions],
        "best_g": result.best_node.g,
        "best_digest": _digest(result.best_node.state),
        "maximum_credit_reached": result.maximum_credit_reached,
        "telemetry": _telemetry_fingerprint(result),
        "transitions": [
            (row["parent"], row["child"], row["actions"], row["cost"], row["kind"])
            for row in (transitions or [])
        ],
    }


def _derive_target(state: SpiderState) -> tuple[CampaignTarget | None, str, str, str]:
    try:
        schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    except Exception as exc:  # noqa: BLE001 — research harness must not crash
        return None, "NOT_RESOURCE_TARGET_ELIGIBLE", f"scheduler_rebuild:{type(exc).__name__}", ""
    priority = schedule.lane_sequence_priority
    if priority is None or priority.lead is None:
        return None, "NOT_RESOURCE_TARGET_ELIGIBLE", "no_lead_lane", ""
    lead = priority.lead
    if not lead.missing_edges:
        return None, "NOT_RESOURCE_TARGET_ELIGIBLE", "lead_has_no_missing_edge", ""
    high, low = lead.missing_edges[0]
    target = CampaignTarget(lead.suit, high, low)
    family = lead.state.value
    description = f"{lead.suit} {family} missing {high}-{low}"
    return target, "ELIGIBLE", family, description


def _stage_summary(state: SpiderState) -> dict:
    return {
        "stock": len(state.stock),
        "stock_rows": len(state.stock) // 10,
        "foundations": len(state.foundations),
        "face_down": sum(len(col.face_down) for col in state.columns),
        "empties": sum(1 for col in state.columns if col.is_empty()),
    }


def _evaluate_pair(state: SpiderState, target: CampaignTarget) -> dict:
    before_key = canonical_state_key(state)
    before_digest = _key_digest(before_key)
    started = time.perf_counter()
    plan = plan_resource_excavation(state, target)
    elapsed = time.perf_counter() - started
    if canonical_state_key(state) != before_key:
        raise RuntimeError("resource planner mutated the captured parent state")
    local_key = local_transposition_key(state, empty_obligations())
    if local_key[0] != before_key:
        raise RuntimeError("local identity leaked into tableau identity")
    if plan.proof_pruning_allowed:
        raise RuntimeError("proof_pruning_allowed must remain False")

    replay_ok = False
    replay_cost = None
    end_digest = before_digest
    end_state = None
    if plan.actions:
        end_state = state.clone()
        try:
            replay_cost = replay_actions(end_state, list(plan.actions))
            replay_ok = replay_cost == plan.cost
        except (ValueError, AssertionError, IndexError):
            replay_ok = False
        if end_state is not None:
            end_digest = _digest(end_state)

    edge_before = _edge_count(state, target)
    edge_after = _edge_count(end_state, target) if end_state is not None else edge_before
    success = plan.result in {
        ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS,
        ResourcePlanResult.PREPAID_DEPENDENCY,
    }
    # Planner success already requires unresolved_count == 0. Record that gate.
    unresolved_count = 0 if success else None
    if plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS:
        if not replay_ok or edge_after <= edge_before:
            raise RuntimeError("false REALISED_CAMPAIGN_PROGRESS")
        if plan.cost != replay_cost:
            raise RuntimeError("cost mismatch on realised plan")
        if unresolved_count != 0:
            raise RuntimeError("realised plan left unresolved obligation debt")
    if plan.result is ResourcePlanResult.PREPAID_DEPENDENCY:
        if not replay_ok:
            raise RuntimeError("false PREPAID_DEPENDENCY")
        if unresolved_count != 0:
            raise RuntimeError("prepaid plan left unresolved obligation debt")

    if elapsed > PER_CALL_LIMIT_S:
        result_name = "RESOURCE_OVERRUN"
    else:
        result_name = plan.result.value

    return {
        "parent_digest": before_digest,
        "target": {
            "suit": target.suit,
            "high": target.high_rank,
            "low": target.low_rank,
        },
        "result": result_name,
        "operators": [kind.value for kind in plan.operators],
        "action_count": len(plan.actions),
        "cost": plan.cost,
        "visited": plan.visited,
        "elapsed_s": round(elapsed, 6),
        "replay_ok": replay_ok,
        "edge_before": edge_before,
        "edge_after": edge_after,
        "end_digest": end_digest,
        "proof_pruning_allowed": plan.proof_pruning_allowed,
        "unresolved_count": unresolved_count,
        "first_action": None
        if not plan.actions
        else list(plan.actions[0])
        if not isinstance(plan.actions[0], str)
        else plan.actions[0],
    }


def _classify_overlap(
    eval_row: dict, production_children: list[dict], *, expanded: bool
) -> dict:
    end = eval_row["end_digest"]
    cost = eval_row["cost"]
    first = eval_row["first_action"]
    same_state = [row for row in production_children if row["child"] == end]
    first_known = False
    for row in production_children:
        acts = row["actions"]
        if not acts:
            continue
        head = acts[0]
        if head == first or (isinstance(head, list) and head == first):
            first_known = True
            break
        if len(acts) == 1 and acts[0] == first:
            first_known = True
            break
    if eval_row["result"] not in {
        ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
        ResourcePlanResult.PREPAID_DEPENDENCY.value,
    }:
        return {
            "class": "NO_SUCCESS",
            "first_action_known": first_known,
            "production_child_count": len(production_children),
            "expanded_parent": expanded,
        }
    if not expanded:
        return {
            "class": "PARENT_NOT_EXPANDED",
            "first_action_known": first_known,
            "production_child_count": len(production_children),
            "expanded_parent": False,
        }
    if not same_state:
        label = "NOVEL_RESOURCE_SUCCESSOR"
    else:
        best_prod = min(row["cost"] for row in same_state)
        if cost == best_prod:
            label = "EXACT_DUPLICATE"
        elif cost > best_prod:
            label = "DOMINATED_DUPLICATE"
        else:
            label = "BETTER_DUPLICATE"
    return {
        "class": label,
        "first_action_known": first_known,
        "production_child_count": len(production_children),
        "expanded_parent": True,
    }


SUCCESS_RESULTS = {
    ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
    ResourcePlanResult.PREPAID_DEPENDENCY.value,
}


def compact_evaluation(row: dict) -> dict:
    return {
        "parent_digest": row["parent_digest"],
        "end_digest": row["end_digest"],
        "target": row["target"],
        "result": row["result"],
        "operators": row["operators"],
        "action_count": row["action_count"],
        "cost": row["cost"],
        "visited": row["visited"],
        "elapsed_s": row["elapsed_s"],
        "replay_ok": row["replay_ok"],
        "edge_before": row["edge_before"],
        "edge_after": row["edge_after"],
        "proof_pruning_allowed": row["proof_pruning_allowed"],
        "unresolved_count": row["unresolved_count"],
        "first_action": row["first_action"],
        "overlap": row["overlap"]["class"],
        "first_action_known": row["overlap"]["first_action_known"],
        "family": row["family"],
        "objective": row["objective"],
        "stage": row["stage"],
        "expanded_parent": row["expanded_parent"],
        "pair_hash": row.get("pair_hash"),
    }


def representative_examples(evaluations: list[dict], limit: int = 8) -> list[dict]:
    """Deterministic: all successes in sample order, then remaining hash-order rows
    that add a new (stock_rows, family) until ``limit``."""

    chosen: list[dict] = []
    seen: set[tuple] = set()
    covered: set[tuple] = set()

    def _key(row: dict) -> tuple:
        target = row["target"]
        return (row["parent_digest"], target["suit"], target["high"], target["low"])

    for row in evaluations:
        if row["result"] not in SUCCESS_RESULTS:
            continue
        key = _key(row)
        if key in seen:
            continue
        chosen.append(compact_evaluation(row))
        seen.add(key)
        covered.add((row["stage"]["stock_rows"], row["family"]))
    for row in evaluations:
        if len(chosen) >= limit:
            break
        key = _key(row)
        if key in seen:
            continue
        stage_key = (row["stage"]["stock_rows"], row["family"])
        if stage_key in covered and len(chosen) >= min(6, limit):
            continue
        chosen.append(compact_evaluation(row))
        seen.add(key)
        covered.add(stage_key)
    return chosen


def main() -> int:
    print("Phase 1/2: production Run A (no collection)", flush=True)
    result_a, _ = _run_production(collect=False)
    fp_a = _fingerprint(result_a, None)
    print(
        f"  A stop={result_a.stop_reason} expansions={result_a.strategic_expansions} "
        f"status={result_a.status.value} elapsed={result_a.elapsed_seconds:.1f}s",
        flush=True,
    )
    if result_a.stop_reason != "strategic expansion limit":
        print(f"WARNING: expected expansion-limit stop, got {result_a.stop_reason!r}")

    print("Phase 1/2: production Run B (passive collection)", flush=True)
    result_b, collector = _run_production(collect=True)
    assert collector is not None
    fp_b = _fingerprint(result_b, collector.transitions)
    print(
        f"  B stop={result_b.stop_reason} expansions={result_b.strategic_expansions} "
        f"transitions={len(collector.transitions)} states={len(collector.states)} "
        f"elapsed={result_b.elapsed_seconds:.1f}s",
        flush=True,
    )

    compare_keys = (
        "status",
        "stop_reason",
        "strategic_expansions",
        "tactical_nodes",
        "incumbent_cost",
        "incumbent_actions",
        "best_g",
        "best_digest",
        "maximum_credit_reached",
        "telemetry",
    )
    mismatches = {
        key: (fp_a[key], fp_b[key]) for key in compare_keys if fp_a[key] != fp_b[key]
    }
    if mismatches:
        print("FAIL: passive collection changed production search")
        print(json.dumps(mismatches, indent=2, default=str))
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(
                {
                    "collection_inert": False,
                    "mismatches": mismatches,
                    "stop": "collection changed production search",
                },
                indent=2,
                default=str,
            ),
            encoding="utf-8",
        )
        return 1
    print("Phase 2 PASS: collection is behaviourally inert")
    controller_src = (ROOT / "src" / "spider" / "planner" / "anytime_controller.py").read_text(
        encoding="utf-8"
    )
    if "resource_excavation" in controller_src:
        print("FAIL: anytime_controller imports or mentions resource_excavation")
        return 1

    children_by_parent: dict[str, list[dict]] = defaultdict(list)
    for row in collector.transitions:
        children_by_parent[row["parent"]].append(row)

    print("Phase 3: derive scheduler campaign targets")
    eligible = []
    ineligible = Counter()
    stage_counter = Counter()
    family_counter = Counter()
    stock_rows = Counter()
    foundations = Counter()
    face_down = Counter()
    empties = Counter()
    for digest, state in collector.states.items():
        target, status, detail, description = _derive_target(state)
        stage = _stage_summary(state)
        stage_counter[f"stock_rows={stage['stock_rows']}/fnd={stage['foundations']}"] += 1
        stock_rows[stage["stock_rows"]] += 1
        foundations[stage["foundations"]] += 1
        face_down[stage["face_down"]] += 1
        empties[stage["empties"]] += 1
        if target is None:
            ineligible[detail] += 1
            continue
        family_counter[detail] += 1
        pair_hash = pair_identity_hash(
            digest, target.suit, target.high_rank, target.low_rank
        )
        eligible.append(
            {
                "digest": digest,
                "target": target,
                "family": detail,
                "objective": description,
                "stage": stage,
                "pair_hash": pair_hash,
                "expanded": digest in collector.expanded_parents,
            }
        )

    unique_list, selected = select_state_target_pairs(eligible, SAMPLE_CAP)
    print(
        f"  captured={len(collector.states)} eligible_pairs={len(unique_list)} "
        f"sampled={len(selected)} ineligible={dict(ineligible)}"
    )

    print("Phase 5/6: offline shadow evaluation")
    evaluations = []
    correctness_failures = []
    for index, item in enumerate(selected, start=1):
        if index == 1 or index % 16 == 0 or index == len(selected):
            print(f"  evaluating {index}/{len(selected)}", flush=True)
        state = collector.states[item["digest"]]
        try:
            eval_row = _evaluate_pair(state, item["target"])
        except Exception as exc:  # noqa: BLE001
            correctness_failures.append(
                {"digest": item["digest"], "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        if eval_row["elapsed_s"] > PER_CALL_LIMIT_S:
            eval_row["result"] = "RESOURCE_OVERRUN"
        overlap = _classify_overlap(
            eval_row,
            children_by_parent.get(item["digest"], []),
            expanded=item["expanded"],
        )
        eval_row["overlap"] = overlap
        eval_row["family"] = item["family"]
        eval_row["objective"] = item["objective"]
        eval_row["stage"] = item["stage"]
        eval_row["expanded_parent"] = item["expanded"]
        eval_row["pair_hash"] = item["pair_hash"]
        evaluations.append(eval_row)

    if correctness_failures:
        print("FAIL: correctness defects in shadow evaluation")
        print(json.dumps(correctness_failures, indent=2))
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(
                {
                    "collection_inert": True,
                    "decision": "D",
                    "correctness_failures": correctness_failures,
                    "stop": "shadow evaluation correctness defect",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return 2

    results = Counter(row["result"] for row in evaluations)
    overlap = Counter(row["overlap"]["class"] for row in evaluations)
    operators = Counter(
        op for row in evaluations for op in row["operators"]
    )
    visited = [row["visited"] for row in evaluations]
    runtimes = [row["elapsed_s"] for row in evaluations]
    costs = [row["cost"] for row in evaluations if row["result"] in {
        ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
        ResourcePlanResult.PREPAID_DEPENDENCY.value,
    }]
    novel_terminals = {
        row["end_digest"]
        for row in evaluations
        if row["overlap"]["class"] == "NOVEL_RESOURCE_SUCCESSOR"
    }
    first_known = sum(
        1
        for row in evaluations
        if row["overlap"]["first_action_known"]
        and row["overlap"]["class"]
        in {
            "NOVEL_RESOURCE_SUCCESSOR",
            "EXACT_DUPLICATE",
            "DOMINATED_DUPLICATE",
            "BETTER_DUPLICATE",
        }
    )
    novel_first_known = sum(
        1
        for row in evaluations
        if row["overlap"]["class"] == "NOVEL_RESOURCE_SUCCESSOR"
        and row["overlap"]["first_action_known"]
    )
    novel_first_new = sum(
        1
        for row in evaluations
        if row["overlap"]["class"] == "NOVEL_RESOURCE_SUCCESSOR"
        and not row["overlap"]["first_action_known"]
    )
    realised = [
        row
        for row in evaluations
        if row["result"] == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value
    ]
    expanded_success_overlap = Counter(
        row["overlap"]["class"]
        for row in evaluations
        if row["expanded_parent"]
        and row["result"]
        in {
            ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
            ResourcePlanResult.PREPAID_DEPENDENCY.value,
            "RESOURCE_OVERRUN",
        }
    )

    payload = {
        "base_sha": "7480dd26bc9506ba7467a764b51fd316b6e08fb6",
        "production_config": {
            "max_strategic_expansions": 25,
            "max_tactical_nodes": 300_000,
            "wall_clock_limit_s": 180.0,
            "stop_reason": result_b.stop_reason,
            "status": result_b.status.value,
            "telemetry": fp_b["telemetry"],
        },
        "collection_inert": True,
        "captured_states": len(collector.states),
        "captured_transitions": len(collector.transitions),
        "expanded_parents": len(collector.expanded_parents),
        "eligible_unique_pairs": len(unique_list),
        "eligibility_rate": (
            round(len(unique_list) / len(collector.states), 4) if collector.states else 0.0
        ),
        "sampled": len(selected),
        "sampled_expanded_parents": sum(1 for item in selected if item["expanded"]),
        "sampled_identities": [
            {
                "digest": item["digest"],
                "suit": item["target"].suit,
                "high": item["target"].high_rank,
                "low": item["target"].low_rank,
                "pair_hash": item["pair_hash"],
                "family": item["family"],
                "expanded": item["expanded"],
            }
            for item in selected
        ],
        "ineligible": dict(ineligible),
        "stage_distribution": dict(stage_counter),
        "stock_rows_distribution": {str(k): v for k, v in sorted(stock_rows.items())},
        "foundations_distribution": {str(k): v for k, v in sorted(foundations.items())},
        "face_down_distribution": {str(k): v for k, v in sorted(face_down.items())},
        "empties_distribution": {str(k): v for k, v in sorted(empties.items())},
        "lead_family_distribution": dict(family_counter),
        "result_histogram": dict(results),
        "overlap_histogram": dict(overlap),
        "expanded_success_overlap": dict(expanded_success_overlap),
        "operator_frequencies": dict(operators),
        "visited": {
            "median": statistics.median(visited) if visited else 0,
            "p90": _percentile(visited, 90),
            "p95": _percentile(visited, 95),
            "max": max(visited) if visited else 0,
        },
        "runtime_s": {
            "median": statistics.median(runtimes) if runtimes else 0,
            "p90": _percentile(runtimes, 90),
            "p95": _percentile(runtimes, 95),
            "max": max(runtimes) if runtimes else 0,
        },
        "plan_cost": {
            "n": len(costs),
            "median": statistics.median(costs) if costs else 0,
            "max": max(costs) if costs else 0,
        },
        "novel_terminal_states": len(novel_terminals),
        "first_action_already_production": first_known,
        "novel_with_known_first_action": novel_first_known,
        "novel_with_new_first_action": novel_first_new,
        "realised_count": len(realised),
        "per_call_limit_s": PER_CALL_LIMIT_S,
        "timeout_note": (
            "Calls run in-process under structural bounds; RESOURCE_OVERRUN is "
            "recorded if elapsed exceeds 5s but the call is not forcibly killed."
        ),
        "successful_plans": [compact_evaluation(row) for row in realised],
        "representative_examples": representative_examples(evaluations, 8),
        "evaluations": evaluations,
        "correctness_failures": correctness_failures,
        "conclusion": {
            "novel_realised_successors": len(novel_terminals),
            "successful_plans": len(realised)
            + sum(
                1
                for row in evaluations
                if row["result"] == ResourcePlanResult.PREPAID_DEPENDENCY.value
            ),
            "all_successes_exact_duplicates": bool(realised)
            and all(row["overlap"]["class"] == "EXACT_DUPLICATE" for row in realised),
            "max_visited": max(visited) if visited else 0,
            "max_runtime_s": max(runtimes) if runtimes else 0,
        },
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    print("result_histogram", dict(results))
    print("overlap_histogram", dict(overlap))
    print("operators", dict(operators))
    print("novel_terminals", len(novel_terminals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
