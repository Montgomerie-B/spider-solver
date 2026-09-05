#!/usr/bin/env python3
"""One continuous v0.8 search: does the credit ladder reach workspace geometry?

Research-only. Does not modify the controller or resource planner, and does
not invoke plan_resource_excavation.
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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import spider.planner.anytime_controller as controller
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.anytime_controller import (
    StrategicCreditLevel,
    StrategicSearchNode,
    _node_priority,
    _raw_move_successors,
)
from spider.planner.receiver_uncover import _movable_run_length
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "continuous_credit_first_workspace_audit_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
RANDOM_SEED = 0
MILESTONES = (25, 50, 100, 200, 400)
CONTROL = {
    "expansions": 25,
    "stop_reason": "strategic expansion limit",
    "expanded_credit": {"0": 25, "1": 0, "2": 0, "3": 0, "4": 0},
    "live_credit": {"0": 33, "1": 25, "2": 0, "3": 0, "4": 0},
    "widened_pushed": 25,
    "widened_popped": 0,
    "generated": 65,
    "retained": 57,
    "tt_new": 58,
    "tt_suppressed": 8,
    "successor_kinds": {
        "CAMPAIGN_DEPENDENCY_CLOSURE": 3,
        "ECONOMIC_PROJECT": 29,
        "RAW_DEAL": 25,
    },
}


def _load_fid():
    spec = importlib.util.spec_from_file_location(
        "continuation_credit_fidelity_v0_1",
        ROOT / "research" / "continuation_credit_fidelity_v0_1.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _action_json(action):
    if action == ("deal",) or action == "deal":
        return "deal"
    if isinstance(action, str):
        return action
    return list(action)


def _action_key(action):
    dumped = _action_json(action)
    return dumped if isinstance(dumped, str) else tuple(dumped)


def geometry(state: SpiderState) -> dict:
    fd = 0
    empties = 0
    fully = 0
    col_fd = []
    nonempty_fd = []
    empty_creatable = False
    for src, col in enumerate(state.columns):
        nfd = len(col.face_down)
        col_fd.append(nfd)
        if col.is_empty():
            empties += 1
            continue
        fd += nfd
        nonempty_fd.append(nfd)
        if nfd == 0:
            fully += 1
            k = len(col.face_up)
            if k > 0 and _movable_run_length(state, src) == k:
                for dst in range(10):
                    if dst == src or state.columns[dst].is_empty():
                        continue
                    if state.can_move(src, dst, k):
                        empty_creatable = True
    return {
        "face_down": fd,
        "empties": empties,
        "fully_revealed": fully,
        "foundations": len(state.foundations),
        "stock_rows": len(state.stock) // 10,
        "col_fd": col_fd,
        "min_col_fd": min(nonempty_fd) if nonempty_fd else 0,
        "empty_creatable": empty_creatable,
        "R2": fully > 0,
        "R3": empty_creatable,
        "R4": empties > 0,
        "R5": len(state.foundations) > 0,
    }


def classify_transition(parent: SpiderState, child: SpiderState) -> dict:
    pg = geometry(parent)
    cg = geometry(child)
    flags = {
        "R1": cg["face_down"] < pg["face_down"],
        "R2": cg["R2"],
        "R3": cg["R3"],
        "R4": cg["R4"],
        "R5": cg["R5"],
    }
    return {
        "parent": pg,
        "child": cg,
        "flags": flags,
        "face_down_delta": cg["face_down"] - pg["face_down"],
    }


def successor_lifecycle(*, generated: bool, retained: bool, expanded: bool) -> str:
    if expanded:
        return "EXPANDED"
    if retained:
        return "RETAINED"
    if generated:
        return "GENERATED"
    return "CANDIDATE"


def classify_raw_stage(*, in_raw: bool, in_final: bool, retained: bool, expanded: bool) -> str:
    if expanded:
        return "P3"
    if retained:
        return "P2"
    if in_final:
        return "P1"
    if in_raw:
        return "P0"
    return "ABSENT"


def starvation_ranking(live_items: list) -> dict:
    """live_items: (priority, uid, node) heap triples."""

    ordered = sorted(
        [item for item in live_items if isinstance(item, tuple) and len(item) == 3],
        key=lambda item: item[0],
    )
    credits = [int(item[2].credit_level) for item in ordered]
    best = {}
    for credit in range(1, 5):
        idx = next((i for i, c in enumerate(credits) if c == credit), None)
        if idx is None:
            best[str(credit)] = None
            continue
        ahead = Counter(credits[:idx])
        best[str(credit)] = {
            "rank": idx + 1,
            "ahead": dict(ahead),
            "lower_credit_ahead": sum(ahead[c] for c in ahead if c < credit),
            "credit0_ahead": ahead[0],
        }
    return {"frontier_size": len(ordered), "credit_order_prefix": credits[:16], "best": best}


def _hist(values) -> dict:
    counts = Counter(int(v) for v in values)
    return {str(i): counts[i] for i in range(5)}


class WorkspaceAuditObserver:
    """FrontierObserver plus successor geometry, milestones, and paths."""

    def __init__(self) -> None:
        fid = _load_fid()
        self._fid = fid
        self.base = fid.FrontierObserver()
        self.transitions: list[dict] = []
        self.milestones: dict[int, dict] = {}
        self.telemetry = None
        self.expanded_identities: set[str] = set()
        self.retained_keys: set[tuple] = set()
        self.child_paths: dict[str, list] = {}
        self.parent_paths: dict[str, list] = {}
        self.credit4_nodes: list[tuple] = []
        self.first_push = {}
        self.first_pop = {}
        self.first_expand = {}
        self.progress = {
            "min_face_down": 10**9,
            "min_col_fd": 10**9,
            "max_fully_revealed": 0,
            "max_empties": 0,
            "max_foundations": 0,
            "stock_rows": Counter(),
        }
        self.geom_counts = {
            flag: {"generated": 0, "retained": 0, "expanded": 0} for flag in "R1 R2 R3 R4 R5".split()
        }
        self.credit_kind = defaultdict(Counter)
        self.credit_geom = {
            c: {flag: {"generated": 0, "retained": 0, "expanded": 0} for flag in "R1 R2 R3 R4 R5".split()}
            for c in range(5)
        }
        self.positive: list[dict] = []
        self._pending_milestone = None

    def install(self) -> None:
        self.base.install()
        obs = self
        orig_generate = controller.generate_strategic_successors
        orig_record = controller._record_transition
        orig_push = heapq.heappush
        orig_pop = heapq.heappop

        def wrapped_generate(node, cards, **kwargs):
            if obs.telemetry is None:
                obs.telemetry = kwargs.get("telemetry")
            successors = orig_generate(node, cards, **kwargs)
            credit = int(node.credit_level)
            parent_digest = _digest(node.state)
            parent_ident = f"{parent_digest}|c{credit}"
            parent_path = [_action_json(a) for a in node.actions]
            obs.parent_paths[parent_ident] = parent_path
            obs.expanded_identities.add(parent_ident)
            if credit not in obs.first_expand:
                obs.first_expand[credit] = len(obs.base.expanded)
            if credit == 4:
                obs.credit4_nodes.append((node.state.clone(), credit, int(node.g), parent_ident, parent_path))
            pg = geometry(node.state)
            obs._note_progress(pg)
            for successor in successors:
                child = successor.end_state
                cg_pack = classify_transition(node.state, child)
                child_digest = _digest(child)
                actions = [_action_json(a) for a in successor.actions]
                act_key = tuple(_action_key(a) for a in successor.actions)
                row = {
                    "parent": parent_digest,
                    "parent_credit": credit,
                    "child": child_digest,
                    "kind": successor.kind.value,
                    "category": successor.category,
                    "actions": actions,
                    "cost": int(successor.corrected_cost),
                    "flags": cg_pack["flags"],
                    "face_down_delta": cg_pack["face_down_delta"],
                    "parent_geom": {
                        k: pg[k]
                        for k in (
                            "face_down",
                            "empties",
                            "fully_revealed",
                            "foundations",
                            "stock_rows",
                            "col_fd",
                            "min_col_fd",
                        )
                    },
                    "child_geom": {
                        k: cg_pack["child"][k]
                        for k in (
                            "face_down",
                            "empties",
                            "fully_revealed",
                            "foundations",
                            "stock_rows",
                            "col_fd",
                            "min_col_fd",
                            "empty_creatable",
                        )
                    },
                    "parent_path": parent_path,
                    "expansion": len(obs.base.expanded),
                }
                obs._note_progress(cg_pack["child"])
                obs.credit_kind[credit][successor.kind.value] += 1
                for flag, hit in cg_pack["flags"].items():
                    if hit:
                        obs.geom_counts[flag]["generated"] += 1
                        obs.credit_geom[credit][flag]["generated"] += 1
                if any(cg_pack["flags"].values()):
                    obs.positive.append(row)
                obs.child_paths[child_digest] = parent_path + actions
                obs.transitions.append(
                    {
                        "parent_ident": parent_ident,
                        "child": child_digest,
                        "act_key": act_key,
                        "kind": successor.kind.value,
                        "row": row if any(cg_pack["flags"].values()) else None,
                    }
                )
            n = len(obs.base.expanded)
            if n in MILESTONES:
                obs._pending_milestone = n
            return successors

        def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
            parent_ident = f"{_digest(parent.state)}|c{int(parent.credit_level)}"
            child_digest = _digest(child.state)
            act_key = tuple(_action_key(a) for a in successor.actions)
            obs.retained_keys.add((parent_ident, child_digest, act_key))
            credit = int(parent.credit_level)
            flags = classify_transition(parent.state, child.state)["flags"]
            for flag, hit in flags.items():
                if hit:
                    obs.geom_counts[flag]["retained"] += 1
                    obs.credit_geom[credit][flag]["retained"] += 1
            return orig_record(
                parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
            )

        def wrapped_push(heap, item):
            result = orig_push(heap, item)
            if obs._fid.is_strategic_frontier_item(item):
                credit = int(item[2].credit_level)
                if credit not in obs.first_push:
                    obs.first_push[credit] = len(obs.base.expanded)
                if obs._pending_milestone is not None:
                    # Wait until widening from that expansion has been pushed.
                    origin = obs.base._origin_for_push(item[2]) if False else None
                    _ = origin
            return result

        def wrapped_pop(heap):
            if obs._pending_milestone is not None and obs.telemetry is not None:
                obs._take_snapshot(obs._pending_milestone)
                obs._pending_milestone = None
            item = orig_pop(heap)
            if obs._fid.is_strategic_frontier_item(item):
                credit = int(item[2].credit_level)
                if credit not in obs.first_pop:
                    obs.first_pop[credit] = len(obs.base.expanded)
            return item

        controller.generate_strategic_successors = wrapped_generate
        controller._record_transition = wrapped_record
        heapq.heappush = wrapped_push
        heapq.heappop = wrapped_pop
        controller.heapq.heappush = wrapped_push
        controller.heapq.heappop = wrapped_pop

    def restore(self) -> None:
        self.base.restore()

    def _note_progress(self, geom: dict) -> None:
        self.progress["min_face_down"] = min(self.progress["min_face_down"], geom["face_down"])
        self.progress["min_col_fd"] = min(self.progress["min_col_fd"], geom["min_col_fd"])
        self.progress["max_fully_revealed"] = max(
            self.progress["max_fully_revealed"], geom["fully_revealed"]
        )
        self.progress["max_empties"] = max(self.progress["max_empties"], geom["empties"])
        self.progress["max_foundations"] = max(
            self.progress["max_foundations"], geom["foundations"]
        )
        self.progress["stock_rows"][geom["stock_rows"]] += 1

    def _take_snapshot(self, n: int) -> None:
        if n in self.milestones:
            return
        live = self.base.live_nodes()
        widened_pushed = [row for row in self.base.pushes if row["origin"] == "credit_widening"]
        widened_ids = {row["identity"] for row in widened_pushed}
        t = self.telemetry
        live_items = list(self.base.frontier_list or [])
        self.milestones[n] = {
            "expansions": n,
            "expanded_credit": _hist(row["credit"] for row in self.base.expanded),
            "live_credit": _hist(row["credit"] for row in live),
            "widened": {
                "pushed": len(widened_pushed),
                "popped": sum(1 for row in self.base.pops if row["identity"] in widened_ids),
                "expanded": sum(1 for row in self.base.expanded if row["identity"] in widened_ids),
                "live": sum(1 for row in live if row["identity"] in widened_ids),
            },
            "frontier_size": len(live),
            "tt_new": getattr(t, "tt_new", 0) if t is not None else 0,
            "tt_improved": getattr(t, "tt_improved", 0) if t is not None else 0,
            "tt_suppressed": getattr(t, "tt_suppressed", 0) if t is not None else 0,
            "progress": {
                "min_face_down": self.progress["min_face_down"],
                "min_col_fd": self.progress["min_col_fd"],
                "max_fully_revealed": self.progress["max_fully_revealed"],
                "max_empties": self.progress["max_empties"],
                "max_foundations": self.progress["max_foundations"],
                "stock_rows": {str(k): v for k, v in sorted(self.progress["stock_rows"].items())},
            },
            "starvation": starvation_ranking(live_items),
        }

    def finalize_expanded_geometry(self) -> None:
        expanded_child = self.expanded_identities
        for rec in self.positive:
            child_ident = f"{rec['child']}|c{rec['parent_credit']}"
            if child_ident in expanded_child:
                rec["lifecycle"] = "EXPANDED"
                for flag, hit in rec["flags"].items():
                    if hit:
                        self.geom_counts[flag]["expanded"] += 1
                        self.credit_geom[rec["parent_credit"]][flag]["expanded"] += 1
            else:
                key = (
                    f"{rec['parent']}|c{rec['parent_credit']}",
                    rec["child"],
                    tuple(_action_key(a) if not isinstance(a, str) else a for a in rec["actions"]),
                )
                # actions already jsonified
                act_key = tuple(
                    tuple(a) if isinstance(a, list) else a for a in rec["actions"]
                )
                retained = (
                    f"{rec['parent']}|c{rec['parent_credit']}",
                    rec["child"],
                    act_key,
                ) in self.retained_keys
                rec["lifecycle"] = "RETAINED" if retained else "GENERATED"


def calibration_ok(result, observer: WorkspaceAuditObserver, live) -> tuple[bool, dict]:
    widened_pushed = [row for row in observer.base.pushes if row["origin"] == "credit_widening"]
    widened_ids = {row["identity"] for row in widened_pushed}
    widened_popped = sum(1 for row in observer.base.pops if row["identity"] in widened_ids)
    metrics = {
        "expansions": result.strategic_expansions,
        "stop_reason": result.stop_reason,
        "expanded_credit": _hist(row["credit"] for row in observer.base.expanded),
        "live_credit": _hist(row["credit"] for row in live),
        "widened_pushed": len(widened_pushed),
        "widened_popped": widened_popped,
        "generated": result.telemetry.generated,
        "retained": result.telemetry.retained,
        "tt_new": result.telemetry.tt_new,
        "tt_suppressed": result.telemetry.tt_suppressed,
        "successor_kinds": dict(sorted(result.telemetry.successor_kinds.items())),
    }
    mismatches = {
        key: (metrics[key], CONTROL[key]) for key in CONTROL if metrics.get(key) != CONTROL[key]
    }
    return not mismatches, {"metrics": metrics, "mismatches": mismatches}


def first_events(observer: WorkspaceAuditObserver) -> dict:
    found = {}
    for rec in observer.positive:
        for flag, hit in rec["flags"].items():
            if hit and flag not in found:
                act_key = tuple(
                    tuple(a) if isinstance(a, list) else a for a in rec["actions"]
                )
                retained = (
                    f"{rec['parent']}|c{rec['parent_credit']}",
                    rec["child"],
                    act_key,
                ) in observer.retained_keys
                child_ident = f"{rec['child']}|c{rec['parent_credit']}"
                expanded = child_ident in observer.expanded_identities
                found[flag] = {
                    "expansion": rec["expansion"],
                    "parent_credit": rec["parent_credit"],
                    "parent_digest": rec["parent"],
                    "kind": rec["kind"],
                    "category": rec["category"],
                    "actions": rec["actions"],
                    "cost": rec["cost"],
                    "child_digest": rec["child"],
                    "lifecycle": successor_lifecycle(
                        generated=True, retained=retained, expanded=expanded
                    ),
                    "stock_rows_before": rec["parent_geom"]["stock_rows"],
                    "stock_rows_after": rec["child_geom"]["stock_rows"],
                    "face_down_before": rec["parent_geom"]["face_down"],
                    "face_down_after": rec["child_geom"]["face_down"],
                    "col_fd_before": rec["parent_geom"]["col_fd"],
                    "col_fd_after": rec["child_geom"]["col_fd"],
                    "empties_before": rec["parent_geom"]["empties"],
                    "empties_after": rec["child_geom"]["empties"],
                    "parent_path": rec["parent_path"],
                }
    return found


def replay_first_event(opening: SpiderState, event: dict) -> dict:
    path = list(event.get("parent_path") or []) + list(event.get("actions") or [])
    actions = []
    for item in path:
        if item == "deal":
            actions.append(("deal",))
        elif isinstance(item, list):
            actions.append(tuple(item))
        else:
            actions.append(item)
    end = opening.clone()
    try:
        cost = replay_actions(end, actions) if actions else 0
        ok = True
    except (ValueError, AssertionError, IndexError) as exc:
        cost = None
        ok = False
        return {"replay_ok": False, "error": f"{type(exc).__name__}: {exc}", "path_len": len(actions)}
    return {
        "replay_ok": ok,
        "replay_cost": cost,
        "end_digest": _digest(end),
        "matches_child": _digest(end) == event["child_digest"],
        "path_len": len(actions),
    }


def raw_anatomy(observer: WorkspaceAuditObserver) -> dict:
    pcounts = Counter()
    rcounts = Counter()
    samples = []
    expanded_digests = {ident.split("|c")[0] for ident in observer.expanded_identities}
    for state, credit, g, ident, path in observer.credit4_nodes:
        node = StrategicSearchNode(
            0,
            state.clone(),
            g,
            (),
            None,
            None,
            0,
            StrategicCreditLevel.RAW_LEGAL_FALLBACK,
            None,
        )
        raw_succ = _raw_move_successors(node)
        final = observer.base.generated.get(ident, [])
        final_keys = {
            tuple(tuple(a) if isinstance(a, list) else a for a in row["actions"])
            for row in final
        }
        retained_for_parent = {
            key[2] for key in observer.retained_keys if key[0] == ident
        }
        for succ in raw_succ:
            act_key = tuple(_action_key(a) for a in succ.actions)
            in_final = act_key in final_keys
            retained = act_key in retained_for_parent
            child_digest = _digest(succ.end_state)
            expanded = any(
                f"{child_digest}|c{c}" in observer.expanded_identities for c in range(5)
            )
            stage = classify_raw_stage(
                in_raw=True, in_final=in_final, retained=retained, expanded=expanded
            )
            pcounts[stage] += 1
            pack = classify_transition(state, succ.end_state)
            for flag, hit in pack["flags"].items():
                if hit:
                    rcounts[flag] += 1
            if pack["flags"]["R1"] or pack["flags"]["R2"] or pack["flags"]["R3"] or pack["flags"]["R4"]:
                samples.append(
                    {
                        "parent": ident,
                        "stage": stage,
                        "flags": pack["flags"],
                        "cost": int(succ.corrected_cost),
                        "actions": [_action_json(a) for a in succ.actions],
                    }
                )
        for row in final:
            if row["kind"] != "RAW_TABLEAU_MOVE":
                continue
            act_key = tuple(tuple(a) if isinstance(a, list) else a for a in row["actions"])
            if act_key not in {
                tuple(_action_key(a) for a in succ.actions) for succ in raw_succ
            }:
                pcounts["P1_NOT_IN_RAW_HELPER"] += 1
    return {
        "credit4_expanded": len(observer.credit4_nodes),
        "p_counts": dict(pcounts),
        "raw_flag_counts": dict(rcounts),
        "geometry_samples": samples[:40],
    }


def run_observed_audit(state, cards, *, expansions: int, seconds: float):
    fid = _load_fid()
    shadow = fid._load_shadow()
    config = shadow._production_config(seconds=seconds, expansions=expansions, nodes=300_000)
    random.seed(RANDOM_SEED)
    observer = WorkspaceAuditObserver()
    observer.install()
    try:
        result = controller.solve_anytime(state.clone(), cards, None, config)
        if observer._pending_milestone is not None:
            observer._take_snapshot(observer._pending_milestone)
        n = len(observer.base.expanded)
        if n not in observer.milestones:
            observer._take_snapshot(n)
        live = observer.base.live_nodes()
        observer.finalize_expanded_geometry()
    finally:
        observer.restore()
    return result, observer, live


def main() -> int:
    if "resource_excavation" in CONTROLLER.read_text(encoding="utf-8"):
        raise RuntimeError("controller mentions resource_excavation")
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("Gate 1: 25-expansion calibration", flush=True)
    result25, obs25, live25 = run_observed_audit(opening, cards, expansions=25, seconds=180.0)
    ok, calib = calibration_ok(result25, obs25, live25)
    print("  calibration", "PASS" if ok else "FAIL", calib["metrics"], flush=True)
    if not ok:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(
            json.dumps({"decision": "F", "calibration": calib}, indent=2),
            encoding="utf-8",
        )
        print("STOP: calibration mismatch")
        return 2

    print("Gate 2: continuous 400-expansion run", flush=True)
    result, observer, live = run_observed_audit(opening, cards, expansions=400, seconds=900.0)
    print(
        f"  stop={result.stop_reason} expansions={result.strategic_expansions} "
        f"elapsed={result.elapsed_seconds:.1f}s live={len(live)}",
        flush=True,
    )
    events = first_events(observer)
    for flag, event in events.items():
        event["replay"] = replay_first_event(opening, event)
        print(
            f"  first {flag}: exp={event['expansion']} credit={event['parent_credit']} "
            f"kind={event['kind']} replay={event['replay'].get('replay_ok')}",
            flush=True,
        )
    raw = raw_anatomy(observer)
    widened_pushed = [row for row in observer.base.pushes if row["origin"] == "credit_widening"]
    widened_ids = {row["identity"] for row in widened_pushed}
    payload = {
        "base_sha": "e7342067e22696600ec92696a3b325f26849d8b0",
        "calibration": calib,
        "long_run": {
            "max_strategic_expansions": 400,
            "max_tactical_nodes": 300000,
            "wall_clock_limit_s": 900,
            "stop_reason": result.stop_reason,
            "expansions": result.strategic_expansions,
            "elapsed_s": round(result.elapsed_seconds, 3),
            "tactical_nodes": result.tactical_nodes,
            "tt_new": result.telemetry.tt_new,
            "tt_improved": result.telemetry.tt_improved,
            "tt_suppressed": result.telemetry.tt_suppressed,
            "generated": result.telemetry.generated,
            "retained": result.telemetry.retained,
            "maximum_credit_reached": result.maximum_credit_reached,
        },
        "milestones": {str(k): v for k, v in sorted(observer.milestones.items())},
        "first_credit": {
            "push": {str(k): v for k, v in sorted(observer.first_push.items())},
            "pop": {str(k): v for k, v in sorted(observer.first_pop.items())},
            "expand": {str(k): v for k, v in sorted(observer.first_expand.items())},
        },
        "terminal_live_credit": _hist(row["credit"] for row in live),
        "widened": {
            "pushed": len(widened_pushed),
            "popped": sum(1 for row in observer.base.pops if row["identity"] in widened_ids),
            "expanded": sum(1 for row in observer.base.expanded if row["identity"] in widened_ids),
            "live": sum(1 for row in live if row["identity"] in widened_ids),
        },
        "geometry": observer.geom_counts,
        "credit_kind": {str(k): dict(v) for k, v in observer.credit_kind.items()},
        "credit_geometry": {
            str(c): observer.credit_geom[c] for c in range(5)
        },
        "first_events": events,
        "raw": raw,
        "progress": {
            "min_face_down": observer.progress["min_face_down"],
            "min_col_fd": observer.progress["min_col_fd"],
            "max_fully_revealed": observer.progress["max_fully_revealed"],
            "max_empties": observer.progress["max_empties"],
            "max_foundations": observer.progress["max_foundations"],
        },
        "starvation_terminal": observer.milestones.get(
            result.strategic_expansions, {}
        ).get("starvation")
        or starvation_ranking(list(observer.base.frontier_list or [])),
        "positive_successors": len(observer.positive),
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    print("geometry", observer.geom_counts)
    print("first_credit", payload["first_credit"])
    print("raw", raw["p_counts"], "c4", raw["credit4_expanded"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
