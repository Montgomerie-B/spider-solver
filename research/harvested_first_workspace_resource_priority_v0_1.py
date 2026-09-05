#!/usr/bin/env python3
"""Harvested R2/R3 first-workspace resource and priority diagnostic.

Natural states only. Unchanged controller and resource planner.
"""

from __future__ import annotations

import hashlib
import heapq
import importlib.util
import json
import random
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
from spider.move_lifecycle import assess_tableau_move
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    _node_priority,
    analyze_stage0_state,
    analyze_strategic_state,
    generate_strategic_successors,
)
from spider.planner.receiver_uncover import _movable_run_length
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    apply_operator,
    empty_obligations,
    is_reserved_receiver_misuse,
    plan_resource_excavation,
    _breaks_join,
    _edge_count,
    _idle_empties,
    _occupies_unique_receiver,
    _play,
    _realise_create,
)
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "harvested_first_workspace_resource_priority_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
FIRST_R2 = "1c3d3ec77bf164ad"
HEADLINE = {
    "expansions": 400,
    "r2_generated": 4,
    "r2_retained": 4,
    "r3_generated": 1,
    "r3_retained": 1,
    "r4_generated": 0,
    "first_r2_digest": FIRST_R2,
    "first_r2_expansion": 116,
    "first_path_len": 5,
}
NONTRIVIAL_OPS = {
    OperatorKind.CREATE_WORKSPACE.value,
    OperatorKind.INVEST_WORKSPACE.value,
    OperatorKind.RECOVER_WORKSPACE.value,
    OperatorKind.RESERVE_RECEIVER.value,
    OperatorKind.PREPAY_DEPENDENCY.value,
    OperatorKind.TEMPORARY_REWORK.value,
    OperatorKind.REPAY_REWORK.value,
}


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _cc():
    return _load(
        "continuous_credit_first_workspace_audit_v0_1",
        ROOT / "research" / "continuous_credit_first_workspace_audit_v0_1.py",
    )


def _anatomy():
    return _load(
        "coverage_anatomy_v0_1",
        ROOT / "research" / "resource_excavation_coverage_anatomy_v0_1.py",
    )


def _fid():
    return _load(
        "continuation_credit_fidelity_v0_1",
        ROOT / "research" / "continuation_credit_fidelity_v0_1.py",
    )


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _action_json(action):
    if action == ("deal",) or action == "deal":
        return "deal"
    if isinstance(action, str):
        return action
    return list(action)


def reconstruct_from_path(opening: SpiderState, path: list) -> SpiderState:
    state = opening.clone()
    actions = []
    for item in path:
        if item == "deal":
            actions.append(("deal",))
        elif isinstance(item, list):
            actions.append(tuple(item))
        else:
            actions.append(item)
    if actions:
        replay_actions(state, actions)
    return state


def reconstruct_first_r2(opening: SpiderState) -> SpiderState:
    path = [[5, 7, 1], [2, 7, 1], [5, 7, 1], [5, 7, 1], [5, 4, 1]]
    return reconstruct_from_path(opening, path)


def legal_first_empty_moves(state: SpiderState) -> list[dict]:
    rows = []
    for src, col in enumerate(state.columns):
        if col.face_down or not col.face_up:
            continue
        k = len(col.face_up)
        if _movable_run_length(state, src) != k:
            continue
        packet = [(c.suit, c.rank) for c in col.face_up]
        for dst in range(10):
            if dst == src or state.columns[dst].is_empty():
                continue
            if not state.can_move(src, dst, k):
                continue
            action = (src, dst, k)
            nxt = state.clone()
            try:
                cost = replay_actions(nxt, [action])
            except (ValueError, AssertionError, IndexError):
                continue
            if not nxt.columns[src].is_empty():
                continue
            life = assess_tableau_move(state, action, discover_exit=False)
            rows.append(
                {
                    "src": src,
                    "dst": dst,
                    "k": k,
                    "packet": packet,
                    "cost": int(cost),
                    "joins_created": len(life.same_suit_joins_created),
                    "joins_broken": len(life.same_suit_joins_broken),
                    "end_digest": _digest(nxt),
                    "empties": sum(1 for c in nxt.columns if c.is_empty()),
                    "face_down": sum(len(c.face_down) for c in nxt.columns),
                    "action": [src, dst, k],
                }
            )
    return rows


def create_reject_reason(state: SpiderState, target: CampaignTarget, action: tuple) -> str | None:
    """Return None if CREATE emits this action, else the first failing predicate."""

    src, dst, k = action
    if _idle_empties(state):
        return "HAS_IDLE_EMPTY"
    col = state.columns[src]
    if col.face_down:
        return "SOURCE_HAS_FACE_DOWN"
    if not col.face_up:
        return "SOURCE_NO_FACE_UP"
    if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:
        return "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
    if _movable_run_length(state, src) != k or k != len(col.face_up):
        return "NOT_ONE_MOVABLE_RUN"
    if dst == src or not state.can_move(src, dst, k):
        return "NO_LEGAL_NONEMPTY_DEST"
    if state.columns[dst].is_empty():
        return "NO_LEGAL_NONEMPTY_DEST"
    if _breaks_join(state, action):
        return "BREAKS_STABLE_JOIN"
    obl = empty_obligations()
    if is_reserved_receiver_misuse(state, obl, action):
        return "RECEIVER_MISUSE_OR_OCCUPY"
    if _occupies_unique_receiver(state, target, action, obl):
        return "OCCUPIES_UNIQUE_RECEIVER"
    nxt, ok = _play(state, (action,))
    if not ok or not nxt.columns[src].is_empty():
        return "DOES_NOT_CREATE_EMPTY"
    if _edge_count(nxt, target) > _edge_count(state, target):
        return "WOULD_REALISE_EDGE"
    emitted = {(s.actions[0] if s.actions else None) for s in _realise_create(state, obl, target)}
    if action not in emitted:
        return "OTHER_EXISTING_PREDICATE"
    return None


def enumerate_ps(state: SpiderState) -> list[dict]:
    rows = _anatomy().enumerate_pla_targets(state)
    for row in rows:
        row["class"] = "P" if row["class"] == "P" else "S"
    return rows


def workspace_pattern(operators: list[str], created_empty: bool, legal_empty: bool, create_accepts: bool) -> str:
    ops = operators
    if OperatorKind.CREATE_WORKSPACE.value in ops:
        if OperatorKind.INVEST_WORKSPACE.value in ops and OperatorKind.RECOVER_WORKSPACE.value in ops:
            return "B"
        if OperatorKind.PREPAY_DEPENDENCY.value in ops:
            return "C"
        if OperatorKind.REALISE_CAMPAIGN_EDGE.value in ops:
            return "A"
        if created_empty:
            return "D"
        return "D"
    if legal_empty and not create_accepts:
        return "E"
    return "NONE"


def cf_overlap(end_digest: str, cost: int, production: list[dict]) -> str:
    same = [row for row in production if row["child"] == end_digest]
    if not same:
        return "CF_NOVEL_RESOURCE_TERMINAL"
    best = min(row["cost"] for row in same)
    if cost == best:
        return "CF_EXACT_DUPLICATE"
    if cost > best:
        return "CF_DOMINATED_DUPLICATE"
    return "CF_BETTER_RESOURCE"


def matched_controls(ordered_live: list, digest: str) -> dict:
    idx = next((i for i, rec in enumerate(ordered_live) if rec["digest"] == digest), None)
    if idx is None:
        return {"index": None, "ahead": [], "behind": []}
    return {
        "index": idx,
        "ahead": ordered_live[max(0, idx - 3) : idx],
        "behind": ordered_live[idx + 1 : idx + 4],
    }


def _priority_summary(rec: dict) -> dict:
    return {
        "digest": rec.get("digest"),
        "g": rec.get("g"),
        "credit": rec.get("credit"),
        "face_down": rec.get("face_down"),
        "scheduler_effect_rank": rec.get("scheduler_effect_rank"),
        "priority": rec.get("priority"),
        "expanded_later": rec.get("expanded_later"),
    }


class HarvestRun:
    """400-expansion continuous capture of R2/R3 capsules and frontier lifespan."""

    def __init__(self) -> None:
        self.cc = _cc()
        self.fid = _fid()
        self.capsules: dict[str, dict] = {}
        self.nodes: dict[str, object] = {}
        self.lifespan: dict[str, dict] = {}
        self.insertion_controls: dict[str, dict] = {}
        self._observer = None
        self._pending_rank = None
        self._last_rank_exp = None

    def _live_ordered(self):
        heap = list(self._observer.base.frontier_list or [])
        ordered = []
        for item in sorted(heap, key=lambda it: it[0]):
            if not self.fid.is_strategic_frontier_item(item):
                continue
            node = item[2]
            geom = self.cc.geometry(node.state)
            ordered.append(
                {
                    "digest": _digest(node.state),
                    "g": int(node.g),
                    "credit": int(node.credit_level),
                    "face_down": geom["face_down"],
                    "scheduler_effect_rank": (
                        node.incoming_edge.scheduler_effect_rank
                        if node.incoming_edge is not None
                        else None
                    ),
                    "priority": self.fid.strip_priority(_node_priority(node)),
                    "expanded_later": False,
                }
            )
        return ordered

    def capture(self, opening: SpiderState, cards):
        observer = self.cc.WorkspaceAuditObserver()
        self._observer = observer
        orig_record = None
        orig_pop = None
        orig_push = None
        harvest = self

        def wrap_after_audit_install():
            nonlocal orig_record, orig_pop, orig_push
            orig_record = controller._record_transition
            orig_pop = heapq.heappop
            orig_push = heapq.heappush

            def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
                out = orig_record(
                    parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
                )
                geom = harvest.cc.geometry(child.state)
                if geom["R2"]:
                    digest = _digest(child.state)
                    if digest not in harvest.capsules:
                        harvest.nodes[digest] = child
                        harvest.capsules[digest] = {
                            "digest": digest,
                            "g": int(child.g),
                            "depth": int(child.depth),
                            "credit": int(child.credit_level),
                            "incoming_kind": None
                            if child.incoming_edge is None
                            else child.incoming_edge.kind.value,
                            "scheduler_effect_rank": (
                                child.incoming_edge.scheduler_effect_rank
                                if child.incoming_edge is not None
                                else None
                            ),
                            "path": [_action_json(a) for a in child.actions],
                            "path_cost": int(child.g),
                            "expansion_created": len(observer.base.expanded),
                            "parent_digest": _digest(parent.state),
                            "parent_credit": int(parent.credit_level),
                            "geometry": geom,
                            "r3": geom["R3"],
                            "priority": harvest.fid.strip_priority(_node_priority(child)),
                        }
                        harvest.lifespan[digest] = {
                            "digest": digest,
                            "retention_expansion": len(observer.base.expanded),
                            "inserted": False,
                            "popped": False,
                            "trimmed": False,
                            "trim_expansion": None,
                            "ranks": [],
                            "best_rank": None,
                            "worst_rank": None,
                            "live_at_200": None,
                            "live_at_400": None,
                            "expansions_live": 0,
                            "clean_ahead_insert": None,
                            "clean_ahead_end": None,
                        }
                return out

            def wrapped_push(heap, item):
                result = orig_push(heap, item)
                if harvest.fid.is_strategic_frontier_item(item):
                    digest = _digest(item[2].state)
                    life = harvest.lifespan.get(digest)
                    if life is not None and not life["inserted"]:
                        ordered = harvest._live_ordered()
                        idx = next(
                            (i for i, rec in enumerate(ordered) if rec["digest"] == digest),
                            None,
                        )
                        life["inserted"] = True
                        life["insertion_rank"] = None if idx is None else idx + 1
                        life["insertion_priority"] = harvest.fid.strip_priority(
                            item[0] if isinstance(item[0], tuple) else item[0]
                        )
                        if idx is not None:
                            life["clean_ahead_insert"] = sum(
                                1 for rec in ordered[:idx] if rec["credit"] == 0
                            )
                            harvest.insertion_controls[digest] = matched_controls(ordered, digest)
                return result

            def wrapped_pop(heap):
                if harvest._pending_rank is not None:
                    harvest._snapshot_ranks(harvest._pending_rank)
                    harvest._pending_rank = None
                item = orig_pop(heap)
                if harvest.fid.is_strategic_frontier_item(item):
                    digest = _digest(item[2].state)
                    if digest in harvest.lifespan:
                        harvest.lifespan[digest]["popped"] = True
                n = len(observer.base.expanded)
                if harvest.capsules and n != harvest._last_rank_exp:
                    harvest._pending_rank = n
                return item

            controller._record_transition = wrapped_record
            heapq.heappush = wrapped_push
            heapq.heappop = wrapped_pop
            controller.heapq.heappush = wrapped_push
            controller.heapq.heappop = wrapped_pop

        shadow = self.fid._load_shadow()
        config = shadow._production_config(seconds=900.0, expansions=400, nodes=300_000)
        random.seed(0)
        observer.install()
        wrap_after_audit_install()
        try:
            result = controller.solve_anytime(opening.clone(), cards, None, config)
            if self._pending_rank is not None:
                self._snapshot_ranks(self._pending_rank)
            self._snapshot_ranks(len(observer.base.expanded), final=True)
            observer.finalize_expanded_geometry()
        finally:
            observer.restore()
        return result, observer

    def _snapshot_ranks(self, expansion: int, final: bool = False) -> None:
        self._last_rank_exp = expansion
        ordered = self._live_ordered()
        live_digests = {rec["digest"] for rec in ordered}
        for digest, life in self.lifespan.items():
            if life["popped"]:
                continue
            if digest in live_digests:
                idx = next(i for i, rec in enumerate(ordered) if rec["digest"] == digest)
                rank = idx + 1
                life["ranks"].append({"expansion": expansion, "rank": rank})
                life["best_rank"] = rank if life["best_rank"] is None else min(life["best_rank"], rank)
                life["worst_rank"] = rank if life["worst_rank"] is None else max(life["worst_rank"], rank)
                life["expansions_live"] += 1
                if expansion == 200:
                    life["live_at_200"] = True
                if final or expansion == 400:
                    life["live_at_400"] = True
                    life["clean_ahead_end"] = sum(
                        1 for rec in ordered[:idx] if rec["credit"] == 0
                    )
            else:
                if life["inserted"] and not life["popped"] and not life["trimmed"]:
                    if life["ranks"]:
                        life["trimmed"] = True
                        life["trim_expansion"] = expansion
                if expansion == 200 and life["live_at_200"] is None:
                    life["live_at_200"] = False
                if final and life["live_at_400"] is None:
                    life["live_at_400"] = False


def analyze_capsule(digest: str, node, rec: dict, cards, opening: SpiderState) -> dict:
    state = node.state
    assert _digest(state) == digest
    geom = rec["geometry"]
    legal = legal_first_empty_moves(state)
    targets = enumerate_ps(state)
    create_rows = []
    plan_rows = []
    fid = _fid()
    shadow = fid._load_shadow()
    config = shadow._production_config(expansions=1)
    # Counterfactual exact-node expansion: production fills analysis at pop.
    analysis = analyze_strategic_state(
        state,
        cards,
        spent_cost=node.g,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
        supply_consumptions=node.supply_consumption_results,
        continuation_objective_id=(
            node.continuation_credit.objective_id
            if node.continuation_credit is not None and node.continuation_credit.is_live
            else None
        ),
    )
    filled = replace(node, analysis=analysis)
    if filled.stage0 is None:
        filled = replace(
            filled,
            stage0=analyze_stage0_state(state, spent_cost=node.g, incumbent_cost=None),
        )
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        filled,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    prod = []
    for item in successors:
        prod.append(
            {
                "kind": item.kind.value,
                "category": item.category,
                "actions": [_action_json(a) for a in item.actions],
                "cost": int(item.corrected_cost),
                "child": _digest(item.end_state),
            }
        )
    prod_first = set()
    prod_actions = set()
    for row in prod:
        if row["actions"]:
            head = row["actions"][0]
            prod_first.add(tuple(head) if isinstance(head, list) else head)
        prod_actions.add(tuple(tuple(a) if isinstance(a, list) else a for a in row["actions"]))

    for spec in targets:
        target = CampaignTarget(spec["suit"], spec["high"], spec["low"])
        accept = []
        reject = Counter()
        for mv in legal:
            action = (mv["src"], mv["dst"], mv["k"])
            reason = create_reject_reason(state, target, action)
            if reason is None:
                accept.append(mv["action"])
            else:
                reject[reason] += 1
        before = canonical_state_key(state)
        started = time.perf_counter()
        plan = plan_resource_excavation(state, target)
        elapsed = time.perf_counter() - started
        if canonical_state_key(state) != before:
            raise RuntimeError("resource planner mutated harvested state")
        if plan.proof_pruning_allowed:
            raise RuntimeError("proof_pruning_allowed must remain False")
        replay_ok = False
        end_digest = _digest(state)
        empties_trace = []
        obl_trace = []
        if plan.actions:
            end = state.clone()
            try:
                paid = replay_actions(end, list(plan.actions))
                replay_ok = paid == plan.cost
            except (ValueError, AssertionError, IndexError):
                replay_ok = False
            end_digest = _digest(end)
        cur = state.clone()
        obl = empty_obligations()
        empties_trace.append(sum(1 for c in cur.columns if c.is_empty()))
        for kind, acts in plan.operator_trace:
            step = apply_operator(cur, target, kind, obligations=obl, candidate=acts[0] if acts else None)
            if step is None:
                obl_trace.append({"op": kind.value, "failed": True})
                break
            cur = step.state
            obl = step.obligations
            empties_trace.append(sum(1 for c in cur.columns if c.is_empty()))
            obl_trace.append(
                {
                    "op": kind.value,
                    "actions": [_action_json(a) for a in acts],
                    "unresolved": obl.unresolved_count(),
                    "workspace": obl.workspace is not None,
                    "rework": obl.rework is not None,
                    "reservation": obl.reservation is not None,
                    "empties": empties_trace[-1],
                }
            )
        ops = [kind.value for kind in plan.operators]
        created_empty = max(empties_trace) > 0 if empties_trace else False
        first_empty = OperatorKind.CREATE_WORKSPACE.value in ops and created_empty
        success = plan.result in {
            ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS,
            ResourcePlanResult.PREPAID_DEPENDENCY,
        }
        if success and plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS and not replay_ok:
            raise RuntimeError("false REALISED_CAMPAIGN_PROGRESS")
        nontrivial = success and any(op in NONTRIVIAL_OPS for op in ops)
        create_accepts = bool(accept)
        pattern = workspace_pattern(ops, created_empty, bool(legal), create_accepts)
        first = None if not plan.actions else _action_json(plan.actions[0])
        first_key = tuple(first) if isinstance(first, list) else first
        plan_rows.append(
            {
                "class": spec["class"],
                "target": {"suit": spec["suit"], "high": spec["high"], "low": spec["low"]},
                "family": spec["family"],
                "create_accepted": accept,
                "create_rejected": dict(reject),
                "result": plan.result.value,
                "operators": ops,
                "actions": [_action_json(a) for a in plan.actions],
                "cost": plan.cost,
                "visited": plan.visited,
                "elapsed_s": round(elapsed, 6),
                "replay_ok": replay_ok,
                "end_digest": end_digest,
                "edge_before": _edge_count(state, target),
                "edge_after": _edge_count(reconstruct_from_path(opening, rec["path"] + [_action_json(a) for a in plan.actions]), target)
                if plan.actions and replay_ok
                else _edge_count(state, target),
                "unresolved": 0 if success else obl.unresolved_count(),
                "empties_trace": empties_trace,
                "obligation_trace": obl_trace,
                "FIRST_EMPTY_CREATED": first_empty,
                "WORKSPACE_INVESTED": OperatorKind.INVEST_WORKSPACE.value in ops,
                "WORKSPACE_RECOVERED": OperatorKind.RECOVER_WORKSPACE.value in ops,
                "NONTRIVIAL_RESOURCE_SUCCESS": nontrivial,
                "pattern": pattern,
                "overlap": cf_overlap(end_digest, plan.cost, prod)
                if success
                else "NO_SUCCESS",
                "first_action": first,
                "first_action_in_production": first_key in prod_first if first_key is not None else False,
            }
        )
        create_rows.append(
            {
                "class": spec["class"],
                "target": {"suit": spec["suit"], "high": spec["high"], "low": spec["low"]},
                "legal": len(legal),
                "accepted": len(accept),
                "rejected": dict(reject),
            }
        )
    return {
        "digest": digest,
        "g": rec["g"],
        "expansion_created": rec["expansion_created"],
        "path_cost": rec["path_cost"],
        "face_down": geom["face_down"],
        "fully_revealed": geom["fully_revealed"],
        "r3": rec["r3"],
        "legal_first_empty": legal,
        "legal_count": len(legal),
        "create": create_rows,
        "plans": plan_rows,
        "production_successors": prod,
    }


def main() -> int:
    if "resource_excavation" in CONTROLLER.read_text(encoding="utf-8"):
        raise RuntimeError("controller mentions resource planner")
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    first = reconstruct_first_r2(opening)
    if _digest(first) != FIRST_R2:
        print("STOP: first R2 digest mismatch", _digest(first))
        return 2
    print("Phase 0: reconstruct first R2 OK", FIRST_R2, flush=True)
    print("Rerun continuous 400-expansion harvest", flush=True)
    run = HarvestRun()
    result, observer = run.capture(opening, cards)
    r2_pos = [row for row in observer.positive if row["flags"]["R2"]]
    r3_pos = [row for row in observer.positive if row["flags"]["R3"]]
    r4_pos = [row for row in observer.positive if row["flags"]["R4"]]
    r2_digests = sorted({row["child"] for row in r2_pos})
    headline = {
        "expansions": result.strategic_expansions,
        "r2_generated": observer.geom_counts["R2"]["generated"],
        "r2_retained": observer.geom_counts["R2"]["retained"],
        "r3_generated": observer.geom_counts["R3"]["generated"],
        "r3_retained": observer.geom_counts["R3"]["retained"],
        "r4_generated": observer.geom_counts["R4"]["generated"],
        "first_r2_digest": None,
        "first_r2_expansion": None,
        "first_path_len": None,
    }
    if r2_pos:
        first_event = min(r2_pos, key=lambda row: row["expansion"])
        headline["first_r2_digest"] = first_event["child"]
        headline["first_r2_expansion"] = first_event["expansion"]
        headline["first_path_len"] = len(first_event["parent_path"]) + len(first_event["actions"])
    print("headline", headline, "capsules", list(run.capsules), flush=True)
    mismatches = {k: (headline[k], HEADLINE[k]) for k in HEADLINE if headline.get(k) != HEADLINE[k]}
    if mismatches or result.stop_reason != "strategic expansion limit":
        print("STOP: headline mismatch", mismatches)
        RESULT_PATH.write_text(json.dumps({"decision": "F", "mismatches": mismatches}, indent=2))
        return 2
    if len(run.capsules) != 4:
        print("STOP: expected 4 R2 capsules", len(run.capsules), r2_digests)
        return 2

    analyses = []
    for digest, rec in sorted(run.capsules.items(), key=lambda kv: kv[1]["expansion_created"]):
        print(f"  analyze {digest} r3={rec['r3']} legal...", flush=True)
        analyses.append(analyze_capsule(digest, run.nodes[digest], rec, cards, opening))

    def _agg(cls: str) -> dict:
        plans = [p for a in analyses for p in a["plans"] if p["class"] == cls]
        return {
            "targets": len(plans),
            "REALISED": sum(1 for p in plans if p["result"] == "REALISED_CAMPAIGN_PROGRESS"),
            "PREPAID": sum(1 for p in plans if p["result"] == "PREPAID_DEPENDENCY"),
            "NO_BOUNDED_PLAN": sum(1 for p in plans if p["result"] == "NO_BOUNDED_PLAN"),
            "RESOURCE_DEADLOCK": sum(1 for p in plans if p["result"] == "RESOURCE_DEADLOCK"),
            "FIRST_EMPTY_CREATED": sum(1 for p in plans if p["FIRST_EMPTY_CREATED"]),
            "WORKSPACE_INVESTED": sum(1 for p in plans if p["WORKSPACE_INVESTED"]),
            "WORKSPACE_RECOVERED": sum(1 for p in plans if p["WORKSPACE_RECOVERED"]),
            "NONTRIVIAL_RESOURCE_SUCCESS": sum(1 for p in plans if p["NONTRIVIAL_RESOURCE_SUCCESS"]),
            "patterns": dict(Counter(p["pattern"] for p in plans)),
            "overlap": dict(Counter(p["overlap"] for p in plans)),
        }

    payload = {
        "base_sha": "c396d96160350bf336422f3652a30eb02f40c041",
        "headline": headline,
        "corpus": [
            {
                "digest": a["digest"],
                "expansion_created": a["expansion_created"],
                "path_cost": a["path_cost"],
                "face_down": a["face_down"],
                "fully_revealed": a["fully_revealed"],
                "legal_first_empty_count": a["legal_count"],
                "r3": a["r3"],
                "legal_first_empty": a["legal_first_empty"],
            }
            for a in analyses
        ],
        "create_coverage": {
            "P": [row for a in analyses for row in a["create"] if row["class"] == "P"],
            "S": [row for a in analyses for row in a["create"] if row["class"] == "S"],
        },
        "resource": {"P": _agg("P"), "S": _agg("S")},
        "analyses": [
            {
                "digest": a["digest"],
                "r3": a["r3"],
                "plans": a["plans"],
                "production_successors": a["production_successors"],
                "create": a["create"],
            }
            for a in analyses
        ],
        "lifespan": run.lifespan,
        "insertion_controls": {
            digest: {
                "ahead": [_priority_summary(x) for x in ctrl.get("ahead", [])],
                "behind": [_priority_summary(x) for x in ctrl.get("behind", [])],
                "index": ctrl.get("index"),
            }
            for digest, ctrl in run.insertion_controls.items()
        },
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    print("P", payload["resource"]["P"])
    print("S", payload["resource"]["S"])
    for digest, life in run.lifespan.items():
        print(
            "life",
            digest,
            "rank",
            life.get("insertion_rank"),
            "best",
            life.get("best_rank"),
            "pop",
            life.get("popped"),
            "trim",
            life.get("trimmed"),
            life.get("trim_expansion"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
