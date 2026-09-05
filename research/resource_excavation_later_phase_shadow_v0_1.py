#!/usr/bin/env python3
"""Later-phase natural-state shadow of the unchanged resource planner.

Production-only continuation forest, then offline resource evaluation.
Does not modify anytime_controller or resource_excavation_planner.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import spider.planner.anytime_controller as controller
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.anytime_controller import (
    _node_priority,
    generate_strategic_successors,
)
from spider.planner.receiver_uncover import _movable_run_length
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    empty_obligations,
    local_transposition_key,
    plan_resource_excavation,
)
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "resource_excavation_later_phase_shadow_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"

WIDTH = 4
MAX_CONTINUATION_GENERATIONS = 6
GATE1_SAMPLE = 8
SAMPLE_CAP = 128
RANDOM_SEED = 0

NONTRIVIAL_OPS = {
    OperatorKind.CREATE_WORKSPACE.value,
    OperatorKind.INVEST_WORKSPACE.value,
    OperatorKind.RECOVER_WORKSPACE.value,
    OperatorKind.RESERVE_RECEIVER.value,
    OperatorKind.PREPAY_DEPENDENCY.value,
    OperatorKind.TEMPORARY_REWORK.value,
    OperatorKind.REPAY_REWORK.value,
}
SUCCESS_RESULTS = {
    ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
    ResourcePlanResult.PREPAID_DEPENDENCY.value,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _shadow():
    return _load(
        "natural_shadow_v0_1",
        ROOT / "research" / "resource_excavation_natural_shadow_v0_1.py",
    )


def _anatomy():
    return _load(
        "coverage_anatomy_v0_1",
        ROOT / "research" / "resource_excavation_coverage_anatomy_v0_1.py",
    )


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _action_json(action) -> list | str:
    if action == ("deal",) or action == "deal":
        return "deal"
    if isinstance(action, str):
        return action
    return list(action)


def _action_key(action) -> tuple | str:
    dumped = _action_json(action)
    return dumped if isinstance(dumped, str) else tuple(dumped)


def successor_signature(successor) -> dict:
    child = successor.end_state
    return {
        "kind": successor.kind.value,
        "actions": [_action_json(a) for a in successor.actions],
        "cost": int(successor.corrected_cost),
        "child": _digest(child),
        "scheduler_effect_rank": int(successor.scheduler_effect_rank),
        "scheduled": None
        if successor.scheduled_objective is None
        else successor.scheduled_objective.objective_id,
    }


def signature_key(row: dict) -> tuple:
    acts = tuple(
        tuple(a) if isinstance(a, list) else a for a in row["actions"]
    )
    return (row["kind"], acts, row["child"], row["cost"])


def compare_successor_sets(original: list[dict], restart: list[dict]) -> dict:
    orig_keys = [signature_key(row) for row in original]
    rest_keys = [signature_key(row) for row in restart]
    return {
        "generated_equal": orig_keys == rest_keys,
        "generated_multiset_equal": Counter(orig_keys) == Counter(rest_keys),
        "original_count": len(original),
        "restart_count": len(restart),
        "kinds_original": [row["kind"] for row in original],
        "kinds_restart": [row["kind"] for row in restart],
        "missing_from_restart": [
            list(key) for key in orig_keys if key not in rest_keys
        ][:8],
        "extra_in_restart": [
            list(key) for key in rest_keys if key not in orig_keys
        ][:8],
    }


def classify_triggers(state: SpiderState) -> dict:
    empties = sum(1 for col in state.columns if col.is_empty())
    zero_fd = 0
    emptying_moves = 0
    fd_nonzero = []
    for src, col in enumerate(state.columns):
        if col.is_empty():
            continue
        fd = len(col.face_down)
        if fd:
            fd_nonzero.append(fd)
        else:
            zero_fd += 1
            k = len(col.face_up)
            if k > 0 and _movable_run_length(state, src) == k:
                for dst in range(10):
                    if dst != src and state.can_move(src, dst, k):
                        emptying_moves += 1
    min_fd = 0 if zero_fd else (min(fd_nonzero) if fd_nonzero else 0)
    g1 = empties > 0
    g2 = zero_fd > 0
    g3 = emptying_moves > 0
    g4 = len(state.foundations) > 0
    g5 = min_fd <= 1
    return {
        "G1": g1,
        "G2": g2,
        "G3": g3,
        "G4": g4,
        "G5": g5,
        "empties": empties,
        "zero_fd_columns": zero_fd,
        "emptying_moves": emptying_moves,
        "foundations": len(state.foundations),
        "min_fd": min_fd,
        "face_down": sum(len(col.face_down) for col in state.columns),
        "stock_rows": len(state.stock) // 10,
        "triggered": g1 or g2 or g3 or g4 or g5,
    }


def classify_overlap(eval_row: dict, production_children: list[dict], *, expanded: bool) -> dict:
    anatomy = _anatomy()
    return anatomy.classify_overlap(eval_row, production_children, expanded=expanded)


def classify_novelty(overlap_class: str, nontrivial: bool, expanded: bool) -> str:
    if overlap_class == "PARENT_NOT_EXPANDED" or not expanded:
        return "PARENT_NOT_EXPANDED"
    if overlap_class == "NOVEL_RESOURCE_SUCCESSOR" and nontrivial:
        return "NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"
    return overlap_class


def select_frontier_roots(
    candidates: list[dict], width: int = WIDTH, used: set[str] | None = None
) -> list[dict]:
    """Highest production priority, digest tie-break. Independent of geometry."""

    used = used or set()
    unique = {}
    for item in candidates:
        ident = item["restart_identity"]
        if ident in used:
            continue
        prev = unique.get(ident)
        if prev is None or tuple(item["priority"]) < tuple(prev["priority"]):
            unique[ident] = item
    ordered = sorted(
        unique.values(),
        key=lambda item: (tuple(item["priority"]), item["digest"]),
    )
    return ordered[:width]


def enumerate_ps_targets(state: SpiderState) -> list[dict]:
    anatomy = _anatomy()
    rows = anatomy.enumerate_pla_targets(state)
    for row in rows:
        row["class"] = "P" if row["class"] == "P" else "S"
    return rows


class ProductionCapture:
    """Passive wrappers around generate_strategic_successors and _record_transition."""

    def __init__(self) -> None:
        self.generated: dict[str, list[dict]] = {}
        self.retained: dict[str, list[dict]] = defaultdict(list)
        self.states: dict[str, SpiderState] = {}
        self.snapshots: dict[str, dict] = {}
        self.priorities: dict[str, list] = {}
        self.paths: dict[str, list] = {}
        self.expanded: list[str] = []
        self.expanded_set: set[str] = set()
        self._orig_generate = None
        self._orig_record = None

    def install(self, root_state: SpiderState) -> None:
        root_digest = _digest(root_state)
        self.states[root_digest] = root_state.clone()
        self.paths[root_digest] = []
        self.priorities.setdefault(root_digest, [0])
        self._orig_generate = controller.generate_strategic_successors
        self._orig_record = controller._record_transition
        capture = self

        def wrapped_generate(node, cards, **kwargs):
            successors = capture._orig_generate(node, cards, **kwargs)
            digest = _digest(node.state)
            if digest not in capture.states:
                capture.states[digest] = node.state.clone()
            capture.generated[digest] = [successor_signature(item) for item in successors]
            capture.snapshots[digest] = {
                "digest": digest,
                "g": int(node.g),
                "depth": int(node.depth),
                "credit_level": int(node.credit_level),
                "incoming_kind": None
                if node.incoming_edge is None
                else node.incoming_edge.kind.value,
                "followup": None
                if node.incoming_edge is None
                or node.incoming_edge.receiver_uncover_followup is None
                else list(node.incoming_edge.receiver_uncover_followup),
                "continuation_live": bool(
                    node.continuation_credit is not None
                    and node.continuation_credit.is_live
                ),
                "lead": _lead_spec(node),
            }
            if digest not in capture.expanded_set:
                capture.expanded.append(digest)
                capture.expanded_set.add(digest)
            return successors

        def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
            parent_digest = _digest(parent.state)
            child_digest = _digest(child.state)
            if parent_digest not in capture.states:
                capture.states[parent_digest] = parent.state.clone()
            if child_digest not in capture.states:
                capture.states[child_digest] = child.state.clone()
            sig = successor_signature(successor)
            capture.retained[parent_digest].append(sig)
            try:
                prio = list(_node_priority(child)[:-1])
            except Exception:  # noqa: BLE001
                prio = [int(child.g), child_digest]
            capture.priorities[child_digest] = prio
            parent_path = capture.paths.get(parent_digest, [])
            capture.paths[child_digest] = parent_path + [_action_json(a) for a in successor.actions]
            return capture._orig_record(
                parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
            )

        controller.generate_strategic_successors = wrapped_generate
        controller._record_transition = wrapped_record

    def restore(self) -> None:
        if self._orig_generate is not None:
            controller.generate_strategic_successors = self._orig_generate
            self._orig_generate = None
        if self._orig_record is not None:
            controller._record_transition = self._orig_record
            self._orig_record = None


def _lead_spec(node) -> dict | None:
    schedule = node.whole_deal_schedule
    if (
        schedule is None
        or schedule.lane_sequence_priority is None
        or schedule.lane_sequence_priority.lead is None
    ):
        return None
    lead = schedule.lane_sequence_priority.lead
    edge = lead.missing_edges[0] if lead.missing_edges else None
    return {
        "suit": lead.suit,
        "family": lead.state.value,
        "edge": None if edge is None else [edge[0], edge[1]],
    }


def _production_config(expansions: int = 25):
    return _shadow()._production_config(expansions=expansions)


def run_production(state: SpiderState, cards, *, expansions: int = 25) -> tuple[object, ProductionCapture]:
    random.seed(RANDOM_SEED)
    capture = ProductionCapture()
    capture.install(state)
    try:
        result = controller.solve_anytime(state.clone(), cards, None, _production_config(expansions))
    finally:
        capture.restore()
    return result, capture


def frontier_candidates(capture: ProductionCapture, used: set[str]) -> list[dict]:
    rows = []
    for parent, children in capture.retained.items():
        for child in children:
            digest = child["child"]
            if digest in capture.expanded_set:
                continue
            ident = digest
            rows.append(
                {
                    "digest": digest,
                    "restart_identity": ident,
                    "priority": capture.priorities.get(digest, [digest]),
                    "parent": parent,
                    "path": capture.paths.get(digest, []),
                    "g": capture.snapshots.get(parent, {}).get("g", 0) + child["cost"],
                }
            )
    return select_frontier_roots(rows, WIDTH, used)


def gate1_restart_fidelity(capture: ProductionCapture, cards) -> list[dict]:
    expanded = sorted(capture.expanded_set)
    selected = expanded[:GATE1_SAMPLE]
    rows = []
    for digest in selected:
        original_generated = capture.generated.get(digest, [])
        original_retained = capture.retained.get(digest, [])
        state = capture.states[digest]
        snap = capture.snapshots.get(digest, {})
        result, restart = run_production(state, cards, expansions=1)
        restart_digest = _digest(state)
        restart_generated = restart.generated.get(restart_digest, [])
        restart_retained = restart.retained.get(restart_digest, [])
        generated = compare_successor_sets(original_generated, restart_generated)
        retained = compare_successor_sets(original_retained, restart_retained)
        equivalent = generated["generated_multiset_equal"]
        rows.append(
            {
                "digest": digest,
                "g": snap.get("g"),
                "credit_level": snap.get("credit_level"),
                "incoming_kind": snap.get("incoming_kind"),
                "original_lead": snap.get("lead"),
                "stop_reason": result.stop_reason,
                "classification": (
                    "STATE_ONLY_RESTART_EQUIVALENT"
                    if equivalent
                    else "STATE_ONLY_RESTART_DIVERGENT"
                ),
                "generated": generated,
                "retained": retained,
            }
        )
    return rows


def evaluate_resource(state: SpiderState, target: CampaignTarget) -> dict:
    before = canonical_state_key(state)
    started = time.perf_counter()
    plan = plan_resource_excavation(state, target)
    elapsed = time.perf_counter() - started
    if canonical_state_key(state) != before:
        raise RuntimeError("resource planner mutated captured state")
    if local_transposition_key(state, empty_obligations())[0] != before:
        raise RuntimeError("local identity leaked into tableau identity")
    if plan.proof_pruning_allowed:
        raise RuntimeError("proof_pruning_allowed must remain False")
    replay_ok = False
    end_digest = _digest(state)
    if plan.actions:
        end = state.clone()
        try:
            paid = replay_actions(end, list(plan.actions))
            replay_ok = paid == plan.cost
        except (ValueError, AssertionError, IndexError):
            replay_ok = False
        end_digest = _digest(end)
        if plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS and not replay_ok:
            raise RuntimeError("false REALISED_CAMPAIGN_PROGRESS")
    ops = [kind.value for kind in plan.operators]
    nontrivial = plan.result.value in SUCCESS_RESULTS and any(
        op in NONTRIVIAL_OPS for op in ops
    )
    family = None
    if nontrivial:
        if OperatorKind.CREATE_WORKSPACE.value in ops:
            family = "CREATE_LED"
        elif (
            OperatorKind.INVEST_WORKSPACE.value in ops
            and OperatorKind.RECOVER_WORKSPACE.value in ops
        ):
            family = "EXISTING_EMPTY_INVESTMENT"
        elif OperatorKind.PREPAY_DEPENDENCY.value in ops:
            family = "DEPENDENCY_PREPAYMENT"
        elif (
            OperatorKind.TEMPORARY_REWORK.value in ops
            and OperatorKind.REPAY_REWORK.value in ops
        ):
            family = "TEMPORARY_REWORK"
        elif OperatorKind.RESERVE_RECEIVER.value in ops:
            family = "RESERVATION"
        else:
            family = "OTHER_NONTRIVIAL"
    return {
        "result": plan.result.value,
        "operators": ops,
        "cost": plan.cost,
        "visited": plan.visited,
        "elapsed_s": round(elapsed, 6),
        "replay_ok": replay_ok,
        "end_digest": end_digest,
        "first_action": None if not plan.actions else _action_json(plan.actions[0]),
        "nontrivial": nontrivial,
        "family": family,
        "proof_pruning_allowed": plan.proof_pruning_allowed,
        "unresolved_count": 0 if plan.result.value in SUCCESS_RESULTS else None,
    }


def _percentile(values, p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    idx = min(len(ordered) - 1, max(0, math.ceil(p / 100.0 * len(ordered)) - 1))
    return float(ordered[idx])


def generation_telemetry(
    capture: ProductionCapture, generation: int, n_roots: int, root_digests: list[str] | None = None
) -> dict:
    fd = []
    trig = Counter()
    stock = Counter()
    foundations = Counter()
    empties = Counter()
    for digest, state in capture.states.items():
        info = classify_triggers(state)
        fd.append(info["face_down"])
        stock[info["stock_rows"]] += 1
        foundations[info["foundations"]] += 1
        empties[info["empties"]] += 1
        for key in ("G1", "G2", "G3", "G4", "G5"):
            if info[key]:
                trig[key] += 1
    unexpanded = [
        child["child"]
        for parent, children in capture.retained.items()
        for child in children
        if child["child"] not in capture.expanded_set
    ]
    return {
        "generation": generation,
        "roots": n_roots,
        "root_digests": list(root_digests or []),
        "retained_states": len(capture.states),
        "expanded": len(capture.expanded_set),
        "unique_frontier": len(set(unexpanded)),
        "face_down_min": min(fd) if fd else 0,
        "face_down_median": statistics.median(fd) if fd else 0,
        "G1": trig["G1"],
        "G2": trig["G2"],
        "G3": trig["G3"],
        "G4": trig["G4"],
        "G5": trig["G5"],
        "stock_rows": {str(k): v for k, v in sorted(stock.items())},
        "foundations": {str(k): v for k, v in sorted(foundations.items())},
        "empties": {str(k): v for k, v in sorted(empties.items())},
    }


def harvest_triggered(capture: ProductionCapture, generation: int, root_digest: str) -> list[dict]:
    rows = []
    for digest, state in capture.states.items():
        info = classify_triggers(state)
        if not info["triggered"]:
            continue
        rows.append(
            {
                "digest": digest,
                "restart_identity": digest,
                "generation": generation,
                "root": root_digest,
                "expanded": digest in capture.expanded_set,
                "path": capture.paths.get(digest, []),
                "priority": capture.priorities.get(digest, [digest]),
                "triggers": {key: info[key] for key in ("G1", "G2", "G3", "G4", "G5")},
                "stage": {
                    "empties": info["empties"],
                    "zero_fd_columns": info["zero_fd_columns"],
                    "foundations": info["foundations"],
                    "min_fd": info["min_fd"],
                    "face_down": info["face_down"],
                    "stock_rows": info["stock_rows"],
                },
                "retained_children": capture.retained.get(digest, []),
            }
        )
    return rows


def generate_continuation_corpus(cards, opening: SpiderState) -> dict:
    """Production-only. Must not call the resource planner."""

    used: set[str] = set()
    telemetry = []
    harvested: dict[str, dict] = {}
    earliest = {key: None for key in ("G1", "G2", "G3", "G4", "G5")}
    restart_mode = "state_only"
    all_captures_expanded = {}

    print("Generation 0: opening", flush=True)
    result0, cap0 = run_production(opening, cards, expansions=25)
    print(
        f"  stop={result0.stop_reason} expanded={result0.strategic_expansions} "
        f"states={len(cap0.states)}",
        flush=True,
    )
    if result0.stop_reason != "strategic expansion limit":
        print(f"WARNING: expected expansion-limit stop, got {result0.stop_reason!r}")
    telemetry.append(generation_telemetry(cap0, 0, 1, [_digest(opening)]))
    for row in harvest_triggered(cap0, 0, _digest(opening)):
        harvested.setdefault(row["restart_identity"], row)
        for key, flag in row["triggers"].items():
            if flag and earliest[key] is None:
                earliest[key] = 0
        all_captures_expanded[row["digest"]] = row["expanded"] or all_captures_expanded.get(
            row["digest"], False
        )
    used.add(_digest(opening))

    print("Gate 1: state-only restart fidelity", flush=True)
    fidelity = gate1_restart_fidelity(cap0, cards)
    n_eq = sum(1 for row in fidelity if row["classification"] == "STATE_ONLY_RESTART_EQUIVALENT")
    n_div = len(fidelity) - n_eq
    print(f"  equivalent={n_eq} divergent={n_div}", flush=True)
    if n_div:
        return {
            "restart_mode": "invalid",
            "fidelity": fidelity,
            "decision_hint": "E",
            "telemetry": telemetry,
            "harvested": [],
        }

    current_roots = frontier_candidates(cap0, used)
    for gen in range(1, MAX_CONTINUATION_GENERATIONS + 1):
        if len(harvested) >= SAMPLE_CAP and any(
            row["triggers"]["G1"] or row["triggers"]["G2"] or row["triggers"]["G3"]
            for row in harvested.values()
        ):
            break
        if not current_roots:
            print(f"Generation {gen}: no frontier roots", flush=True)
            break
        print(
            f"Generation {gen}: {len(current_roots)} roots "
            f"{[item['digest'] for item in current_roots]}",
            flush=True,
        )
        gen_capture = ProductionCapture()
        gen_capture.states = {}
        gen_capture.retained = defaultdict(list)
        gen_capture.expanded_set = set()
        for root in current_roots:
            used.add(root["restart_identity"])
            state = cap0.states.get(root["digest"])
            if state is None:
                # Reconstruct from path if this digest arrived in a later capture.
                state = _state_from_path(opening, root["path"])
            result, cap = run_production(state, cards, expansions=25)
            print(
                f"  root={root['digest']} stop={result.stop_reason} "
                f"expanded={result.strategic_expansions} states={len(cap.states)}",
                flush=True,
            )
            for digest, st in cap.states.items():
                gen_capture.states[digest] = st
                cap0.states[digest] = st
            for digest, rows in cap.retained.items():
                gen_capture.retained[digest].extend(rows)
                cap0.retained[digest].extend(rows)
            gen_capture.expanded_set |= cap.expanded_set
            cap0.expanded_set |= cap.expanded_set
            cap0.generated.update(cap.generated)
            cap0.paths.update(cap.paths)
            cap0.priorities.update(cap.priorities)
            for row in harvest_triggered(cap, gen, root["digest"]):
                prev = harvested.get(row["restart_identity"])
                if prev is None:
                    harvested[row["restart_identity"]] = row
                else:
                    prev["expanded"] = prev["expanded"] or row["expanded"]
                    for key, flag in row["triggers"].items():
                        prev["triggers"][key] = prev["triggers"][key] or flag
                for key, flag in row["triggers"].items():
                    if flag and earliest[key] is None:
                        earliest[key] = gen
        telemetry.append(
            generation_telemetry(
                gen_capture, gen, len(current_roots), [item["digest"] for item in current_roots]
            )
        )
        current_roots = frontier_candidates(cap0, used)

    return {
        "restart_mode": restart_mode,
        "fidelity": fidelity,
        "telemetry": telemetry,
        "earliest_triggers": earliest,
        "harvested": list(harvested.values()),
        "capture": cap0,
        "generations_executed": len(telemetry),
    }


def _state_from_path(opening: SpiderState, path: list) -> SpiderState:
    state = opening.clone()
    actions = []
    for item in path:
        if item == "deal":
            actions.append(("deal",))
        else:
            actions.append(tuple(item))
    if actions:
        replay_actions(state, actions)
    return state


def audit_harvested(corpus: dict, opening: SpiderState) -> dict:
    capture: ProductionCapture = corpus["capture"]
    harvested = corpus["harvested"]
    identities = sorted(row["restart_identity"] for row in harvested)
    if len(identities) > SAMPLE_CAP:
        identities = sorted(identities, key=lambda ident: hashlib.sha256(ident.encode()).hexdigest())[
            :SAMPLE_CAP
        ]
    selected = [row for row in harvested if row["restart_identity"] in set(identities)]
    selected.sort(key=lambda row: row["restart_identity"])

    evaluations = []
    class_stats = {"P": Counter(), "S": Counter()}
    op_freq = {"P": Counter(), "S": Counter()}
    novelty_by_trigger = {key: 0 for key in ("G1", "G2", "G3", "G4", "G5")}
    costs = []
    visited = []
    runtimes = []
    novel_traces = []

    for item in selected:
        state = capture.states.get(item["digest"])
        if state is None:
            state = _state_from_path(opening, item["path"])
        children = [
            {
                "child": row["child"],
                "cost": row["cost"],
                "actions": row["actions"],
            }
            for row in item.get("retained_children") or capture.retained.get(item["digest"], [])
        ]
        expanded = item["expanded"] or item["digest"] in capture.expanded_set
        for spec in enumerate_ps_targets(state):
            target = CampaignTarget(spec["suit"], spec["high"], spec["low"])
            plan = evaluate_resource(state, target)
            overlap = classify_overlap(plan, children, expanded=expanded)
            novelty = classify_novelty(overlap["class"], plan["nontrivial"], expanded)
            row = {
                "digest": item["digest"],
                "class": spec["class"],
                "target": {"suit": spec["suit"], "high": spec["high"], "low": spec["low"]},
                "family": spec["family"],
                "triggers": item["triggers"],
                "expanded_parent": expanded,
                "plan": plan,
                "overlap": overlap,
                "novelty": novelty,
            }
            evaluations.append(row)
            stats = class_stats[spec["class"]]
            stats["targets"] += 1
            stats[plan["result"]] += 1
            if plan["nontrivial"]:
                stats["NONTRIVIAL_RESOURCE_PLAN"] += 1
            if plan["result"] in SUCCESS_RESULTS and expanded:
                stats["expanded_parent_success"] += 1
            if novelty == "NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR":
                stats["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"] += 1
                for key, flag in item["triggers"].items():
                    if flag:
                        novelty_by_trigger[key] += 1
                novel_traces.append(
                    {
                        "digest": item["digest"],
                        "class": spec["class"],
                        "target": row["target"],
                        "operators": plan["operators"],
                        "family": plan["family"],
                        "cost": plan["cost"],
                        "triggers": item["triggers"],
                    }
                )
            stats[overlap["class"]] += 1
            if plan["result"] in SUCCESS_RESULTS:
                for op in plan["operators"]:
                    op_freq[spec["class"]][op] += 1
                costs.append(plan["cost"])
                visited.append(plan["visited"])
                runtimes.append(plan["elapsed_s"])

    def _table(label: str) -> dict:
        c = class_stats[label]
        return {
            "targets": c["targets"],
            "REALISED_CAMPAIGN_PROGRESS": c["REALISED_CAMPAIGN_PROGRESS"],
            "PREPAID_DEPENDENCY": c["PREPAID_DEPENDENCY"],
            "NO_BOUNDED_PLAN": c["NO_BOUNDED_PLAN"],
            "RESOURCE_DEADLOCK": c["RESOURCE_DEADLOCK"],
            "NONTRIVIAL_RESOURCE_PLAN": c["NONTRIVIAL_RESOURCE_PLAN"],
            "expanded_parent_success": c["expanded_parent_success"],
            "NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR": c["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"],
            "EXACT_DUPLICATE": c["EXACT_DUPLICATE"],
            "NOVEL_RESOURCE_SUCCESSOR": c["NOVEL_RESOURCE_SUCCESSOR"],
            "PARENT_NOT_EXPANDED": c["PARENT_NOT_EXPANDED"],
        }

    trigger_counts = Counter()
    for row in selected:
        for key, flag in row["triggers"].items():
            if flag:
                trigger_counts[key] += 1

    return {
        "selected": len(selected),
        "trigger_corpus": dict(trigger_counts),
        "P": _table("P"),
        "S": _table("S"),
        "operator_frequencies": {"P": dict(op_freq["P"]), "S": dict(op_freq["S"])},
        "novelty_by_trigger": novelty_by_trigger,
        "novel_traces": novel_traces,
        "cost": {
            "n": len(costs),
            "median": statistics.median(costs) if costs else 0,
            "p90": _percentile(costs, 90),
            "max": max(costs) if costs else 0,
        },
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
        "evaluations": evaluations,
    }


def main() -> int:
    if "resource_excavation" in CONTROLLER.read_text(encoding="utf-8"):
        raise RuntimeError("anytime_controller mentions resource_excavation")
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("Building production-only continuation forest", flush=True)
    corpus = generate_continuation_corpus(cards, opening)
    if corpus.get("decision_hint") == "E":
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps(
                {
                    "base_sha": "93a2cf9606cc3cfafa4186b92da3907c6237d0e4",
                    "restart_mode": corpus["restart_mode"],
                    "fidelity": corpus["fidelity"],
                    "decision": "E",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        print("STOP: restart fidelity not established")
        return 2
    print(
        f"Harvested {len(corpus['harvested'])} triggered identities; offline resource audit",
        flush=True,
    )
    audit = audit_harvested(corpus, opening)
    payload = {
        "base_sha": "93a2cf9606cc3cfafa4186b92da3907c6237d0e4",
        "restart_mode": corpus["restart_mode"],
        "continuation_context": "state_only_spider_state",
        "root_selection": (
            "4 highest-priority unexpanded retained frontier states using "
            "production _node_priority without node_id; canonical digest tie-break"
        ),
        "width": WIDTH,
        "max_continuation_generations": MAX_CONTINUATION_GENERATIONS,
        "fidelity": corpus["fidelity"],
        "generations_executed": corpus["generations_executed"],
        "telemetry": corpus["telemetry"],
        "earliest_triggers": corpus["earliest_triggers"],
        "harvested_identities": [
            {
                "digest": row["digest"],
                "generation": row["generation"],
                "expanded": row["expanded"],
                "triggers": row["triggers"],
                "stage": row["stage"],
                "path": row["path"],
            }
            for row in corpus["harvested"]
        ],
        "audit": {
            "selected": audit["selected"],
            "trigger_corpus": audit["trigger_corpus"],
            "P": audit["P"],
            "S": audit["S"],
            "operator_frequencies": audit["operator_frequencies"],
            "novelty_by_trigger": audit["novelty_by_trigger"],
            "novel_traces": audit["novel_traces"],
            "cost": audit["cost"],
            "visited": audit["visited"],
            "runtime_s": audit["runtime_s"],
        },
        "evaluations": audit["evaluations"],
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    print("P", audit["P"])
    print("S", audit["S"])
    print("triggers", audit["trigger_corpus"])
    print("earliest", corpus["earliest_triggers"])
    print("novel_P", audit["P"]["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"])
    print("novel_S", audit["S"]["NONTRIVIAL_NOVEL_RESOURCE_SUCCESSOR"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
