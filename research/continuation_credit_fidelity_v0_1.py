#!/usr/bin/env python3
"""Continuation-credit fidelity of the previous later-phase forest.

Research-only. Does not modify anytime_controller or the resource planner.
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
from spider.move_lifecycle import assess_tableau_move
from spider.planner.anytime_controller import (
    ControllerTelemetry,
    StrategicCreditLevel,
    StrategicSearchNode,
    _node_priority,
    analyze_stage0_state,
    analyze_strategic_state,
    generate_strategic_successors,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.rules import MW_RULES
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "continuation_credit_fidelity_v0_1.json"
PREVIOUS_JSON = ROOT / "research" / "results" / "resource_excavation_later_phase_shadow_v0_1.json"
LATER_HARNESS = ROOT / "research" / "resource_excavation_later_phase_shadow_v0_1.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
RANDOM_SEED = 0


def _load_shadow():
    spec = importlib.util.spec_from_file_location(
        "natural_shadow_v0_1",
        ROOT / "research" / "resource_excavation_natural_shadow_v0_1.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def continuation_identity(digest: str, credit: int) -> str:
    return f"{digest}|c{credit}"


def strip_priority(priority: tuple) -> list:
    """Drop only the transient trailing node_id."""

    return list(priority[:-1])


def is_strategic_frontier_item(item) -> bool:
    return (
        isinstance(item, tuple)
        and len(item) == 3
        and isinstance(item[2], StrategicSearchNode)
    )


def _action_json(action):
    if action == ("deal",) or action == "deal":
        return "deal"
    if isinstance(action, str):
        return action
    return list(action)


def successor_sig(successor) -> dict:
    return {
        "kind": successor.kind.value,
        "actions": [_action_json(a) for a in successor.actions],
        "cost": int(successor.corrected_cost),
        "child": _digest(successor.end_state),
        "scheduler_effect_rank": int(successor.scheduler_effect_rank),
    }


def sig_key(row: dict) -> tuple:
    acts = tuple(tuple(a) if isinstance(a, list) else a for a in row["actions"])
    return (row["kind"], acts, row["child"], row["cost"])


def compare_sigs(left: list[dict], right: list[dict]) -> dict:
    a = [sig_key(row) for row in left]
    b = [sig_key(row) for row in right]
    return {
        "equal": Counter(a) == Counter(b),
        "left": len(left),
        "right": len(right),
        "kinds_left": [row["kind"] for row in left],
        "kinds_right": [row["kind"] for row in right],
        "missing_from_right": [row["kind"] for row in left if sig_key(row) not in b],
        "extra_in_right": [row["kind"] for row in right if sig_key(row) not in a],
    }


def static_audit() -> dict:
    src = CONTROLLER.read_text(encoding="utf-8")
    harness = LATER_HARNESS.read_text(encoding="utf-8")
    widening = (
        "Revisit the same exact state at a broader credit" in src
        and "widened = replace(node, node_id=uid, credit_level=next_credit)" in src
        and "heapq.heappush(frontier, (_node_priority(widened), uid, widened))" in src
    )
    uses_record = False
    # The widened push block does not call _record_transition.
    block_start = src.find("# Revisit the same exact state at a broader credit")
    block = src[block_start:block_start + 900]
    uses_record = "_record_transition" in block
    uses_tt = "tt.admit" in block
    raw_rule = "return credit == StrategicCreditLevel.RAW_LEGAL_FALLBACK" in src
    harness_identity = 'ident = digest' in harness or 'restart_identity": ident' in harness
    harness_retained_only = "for parent, children in capture.retained.items()" in harness
    harness_clean = "solve_anytime(state.clone(), cards, None" in harness
    verdict = (
        "PREVIOUS_FOREST_PRESERVED_CREDIT"
        if not harness_retained_only and not harness_clean
        else "PREVIOUS_FOREST_DROPPED_CREDIT"
    )
    return {
        "widening_located": widening,
        "widening_uses_record_transition": uses_record,
        "widening_uses_tt_admit": uses_tt,
        "widening_changes_tableau": False,
        "widening_preserves_g_actions_context": True,
        "raw_fallback_credit": 4,
        "raw_fallback_predicate": "raw_fallback_enabled(credit) iff credit == RAW_LEGAL_FALLBACK",
        "previous_harness_restart_identity": "canonical tableau digest only",
        "previous_harness_frontier_from_retained_children_only": harness_retained_only,
        "previous_harness_solve_anytime_clean_root": harness_clean,
        "previous_harness_identity_is_digest": harness_identity,
        "verdict": verdict,
    }


class FrontierObserver:
    """Passive heap + generate + transition observation."""

    def __init__(self) -> None:
        self.pushes: list[dict] = []
        self.pops: list[dict] = []
        self.expanded: list[dict] = []
        self.generated: dict[str, list[dict]] = {}
        self.retained: dict[str, list[dict]] = defaultdict(list)
        self.states: dict[tuple[str, int], SpiderState] = {}
        self.nodes: dict[str, dict] = {}
        self.last_popped: dict | None = None
        self.frontier_list = None
        self._orig_push = None
        self._orig_pop = None
        self._orig_heapify = None
        self._orig_generate = None
        self._orig_record = None

    def _record_node(self, node: StrategicSearchNode, *, origin: str) -> dict:
        digest = _digest(node.state)
        credit = int(node.credit_level)
        ident = continuation_identity(digest, credit)
        rec = {
            "identity": ident,
            "digest": digest,
            "credit": credit,
            "g": int(node.g),
            "depth": int(node.depth),
            "incoming_kind": None
            if node.incoming_edge is None
            else node.incoming_edge.kind.value,
            "followup": None
            if node.incoming_edge is None
            or node.incoming_edge.receiver_uncover_followup is None
            else list(node.incoming_edge.receiver_uncover_followup),
            "continuation_live": bool(
                node.continuation_credit is not None and node.continuation_credit.is_live
            ),
            "priority": strip_priority(_node_priority(node)),
            "origin": origin,
            "node_id": int(node.node_id),
        }
        existing = self.nodes.get(ident)
        if existing is not None:
            if existing.get("origin") in {"credit_widening", "transition", "root"}:
                rec["origin"] = existing["origin"]
            rec = {**existing, **{k: v for k, v in rec.items() if k != "origin"}, "origin": rec["origin"]}
        self.nodes[ident] = rec
        if (digest, credit) not in self.states:
            self.states[(digest, credit)] = node.state.clone()
        return rec

    def _origin_for_push(self, node: StrategicSearchNode) -> str:
        if not self.last_popped:
            return "root"
        last = self.last_popped
        digest = _digest(node.state)
        if (
            digest == last["digest"]
            and int(node.credit_level) == last["credit"] + 1
            and int(node.g) == last["g"]
            and int(node.depth) == last["depth"]
        ):
            return "credit_widening"
        return "transition"

    def install(self) -> None:
        obs = self
        self._orig_push = heapq.heappush
        self._orig_pop = heapq.heappop
        self._orig_heapify = heapq.heapify
        self._orig_generate = controller.generate_strategic_successors
        self._orig_record = controller._record_transition

        def wrapped_push(heap, item):
            if is_strategic_frontier_item(item):
                obs.frontier_list = heap
                origin = obs._origin_for_push(item[2])
                rec = obs._record_node(item[2], origin=origin)
                rec["event"] = "push"
                obs.pushes.append(rec)
            return obs._orig_push(heap, item)

        def wrapped_pop(heap):
            item = obs._orig_pop(heap)
            if is_strategic_frontier_item(item):
                obs.frontier_list = heap
                rec = obs._record_node(item[2], origin="pop")
                rec["event"] = "pop"
                obs.pops.append(rec)
                obs.last_popped = rec
            return item

        def wrapped_heapify(heap):
            if heap and is_strategic_frontier_item(heap[0]):
                obs.frontier_list = heap
            return obs._orig_heapify(heap)

        def wrapped_generate(node, cards, **kwargs):
            successors = obs._orig_generate(node, cards, **kwargs)
            digest = _digest(node.state)
            credit = int(node.credit_level)
            ident = continuation_identity(digest, credit)
            obs.generated[ident] = [successor_sig(item) for item in successors]
            rec = obs._record_node(node, origin=obs.nodes.get(ident, {}).get("origin", "expanded"))
            rec["expanded"] = True
            obs.expanded.append(rec)
            return successors

        def wrapped_record(parent, successor, child, telemetry, config, *, elapsed_seconds):
            parent_ident = continuation_identity(
                _digest(parent.state), int(parent.credit_level)
            )
            obs.retained[parent_ident].append(successor_sig(successor))
            return obs._orig_record(
                parent, successor, child, telemetry, config, elapsed_seconds=elapsed_seconds
            )

        heapq.heappush = wrapped_push
        heapq.heappop = wrapped_pop
        heapq.heapify = wrapped_heapify
        controller.heapq.heappush = wrapped_push
        controller.heapq.heappop = wrapped_pop
        controller.heapq.heapify = wrapped_heapify
        controller.generate_strategic_successors = wrapped_generate
        controller._record_transition = wrapped_record

    def restore(self) -> None:
        if self._orig_push is not None:
            heapq.heappush = self._orig_push
            controller.heapq.heappush = self._orig_push
        if self._orig_pop is not None:
            heapq.heappop = self._orig_pop
            controller.heapq.heappop = self._orig_pop
        if self._orig_heapify is not None:
            heapq.heapify = self._orig_heapify
            controller.heapq.heapify = self._orig_heapify
        if self._orig_generate is not None:
            controller.generate_strategic_successors = self._orig_generate
        if self._orig_record is not None:
            controller._record_transition = self._orig_record
        self._orig_push = self._orig_pop = self._orig_heapify = None
        self._orig_generate = self._orig_record = None

    def live_nodes(self) -> list[dict]:
        if not self.frontier_list:
            return []
        live = []
        for item in list(self.frontier_list):
            if not is_strategic_frontier_item(item):
                continue
            rec = self._record_node(
                item[2], origin=self.nodes.get(
                    continuation_identity(_digest(item[2].state), int(item[2].credit_level)),
                    {},
                ).get("origin", "live")
            )
            rec["live"] = True
            live.append(rec)
        return live


def run_observed(state: SpiderState, cards, *, expansions: int = 25):
    random.seed(RANDOM_SEED)
    shadow = _load_shadow()
    config = shadow._production_config(expansions=expansions)
    observer = FrontierObserver()
    observer.install()
    try:
        result = controller.solve_anytime(state.clone(), cards, None, config)
        live = observer.live_nodes()
    finally:
        observer.restore()
    return result, observer, live


def reconstruct_and_generate(state: SpiderState, cards, *, credit: int, g: int):
    shadow = _load_shadow()
    config = shadow._production_config(expansions=1)
    analysis = analyze_strategic_state(
        state,
        cards,
        spent_cost=g,
        incumbent_cost=None,
        config=config,
        include_deal_timing=False,
    )
    node = StrategicSearchNode(
        0,
        state.clone(),
        g,
        (),
        None,
        None,
        0,
        StrategicCreditLevel(credit),
        analysis,
        analyze_stage0_state(state, spent_cost=g, incumbent_cost=None),
    )
    if config.enable_whole_deal_scheduler:
        blueprint = build_whole_deal_blueprint(state)
        schedule = rebuild_whole_deal_schedule(
            state,
            blueprint,
            config=config.whole_deal_scheduler_config,
        )
        node = replace(node, whole_deal_schedule=schedule)
    telemetry = ControllerTelemetry()
    successors = generate_strategic_successors(
        node,
        cards,
        incumbent_cost=None,
        config=config,
        telemetry=telemetry,
        actionability_cache={},
        started=time.perf_counter(),
    )
    return [successor_sig(item) for item in successors]


def classify_raw_move(parent: SpiderState, action: tuple) -> dict:
    src, dst, k = action
    before_fd = sum(len(col.face_down) for col in parent.columns)
    before_empty = sum(1 for col in parent.columns if col.is_empty())
    before_zero = sum(
        1 for col in parent.columns if not col.is_empty() and not col.face_down
    )
    fd_nonzero = [len(col.face_down) for col in parent.columns if not col.is_empty() and col.face_down]
    before_min = min(fd_nonzero) if fd_nonzero else 0
    src_fd_before = len(parent.columns[src].face_down)
    life = assess_tableau_move(parent, action, discover_exit=False)
    end = parent.clone()
    end.move(src, dst, k, rules=MW_RULES)
    after_fd = sum(len(col.face_down) for col in end.columns)
    after_empty = sum(1 for col in end.columns if col.is_empty())
    after_zero = sum(
        1 for col in end.columns if not col.is_empty() and not col.face_down
    )
    fd_nz = [len(col.face_down) for col in end.columns if not col.is_empty() and col.face_down]
    after_min = min(fd_nz) if fd_nz else 0
    flipped = len(end.columns[src].face_down) < src_fd_before
    return {
        "action": list(action),
        "flips_face_down_immediately": flipped,
        "reduces_total_face_down": after_fd < before_fd,
        "empties_column": after_empty > before_empty,
        "creates_fully_revealed_column": after_zero > before_zero,
        "reduces_min_face_down_depth": after_min < before_min,
        "rearranges_exposed_only": after_fd == before_fd and after_empty == before_empty,
        "breaks_same_suit_join": bool(life.same_suit_joins_broken),
    }


def _hist(values) -> dict:
    counts = Counter(int(v) for v in values)
    return {str(i): counts[i] for i in range(5)}


def main() -> int:
    static = static_audit()
    print("Gate A", static["verdict"], flush=True)
    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    print("Gate B: observed 25-expansion production run", flush=True)
    result, observer, live = run_observed(opening, cards, expansions=25)
    print(
        f"  stop={result.stop_reason} expansions={result.strategic_expansions} "
        f"pushes={len(observer.pushes)} pops={len(observer.pops)} live={len(live)}",
        flush=True,
    )
    if result.stop_reason != "strategic expansion limit":
        print("WARNING: expected expansion-limit stop")

    expanded_credits = [row["credit"] for row in observer.expanded]
    live_credits = [row["credit"] for row in live]
    widened_pushed = [row for row in observer.pushes if row["origin"] == "credit_widening"]
    widened_popped = [
        row for row in observer.pops
        if observer.nodes.get(row["identity"], {}).get("origin") == "credit_widening"
        or any(
            p["identity"] == row["identity"] and p["origin"] == "credit_widening"
            for p in observer.pushes
        )
    ]
    widened_ids = {row["identity"] for row in widened_pushed}
    widened_expanded = [row for row in observer.expanded if row["identity"] in widened_ids]
    widened_live = [row for row in live if row["identity"] in widened_ids]

    by_state = defaultdict(set)
    for rec in list(observer.nodes.values()) + live:
        by_state[rec["digest"]].add(rec["credit"])
    multi = {digest: sorted(credits) for digest, credits in by_state.items() if len(credits) > 1}

    print("Gate C", "expanded", _hist(expanded_credits), "live", _hist(live_credits), flush=True)
    print(
        f"  widened pushed={len(widened_pushed)} popped={len(widened_popped)} "
        f"expanded={len(widened_expanded)} live={len(widened_live)} multi_states={len(multi)}",
        flush=True,
    )

    previous = json.loads(PREVIOUS_JSON.read_text(encoding="utf-8"))
    gen_roots = {
        str(item["generation"]): item.get("root_digests", [])
        for item in previous["telemetry"]
    }
    frontier_by_digest = defaultdict(list)
    for rec in list(observer.nodes.values()) + live:
        frontier_by_digest[rec["digest"]].append(rec)

    def classify_previous_root(digest: str) -> dict:
        actual = frontier_by_digest.get(digest, [])
        credits = sorted({row["credit"] for row in actual})
        origins = sorted({row["origin"] for row in actual})
        previous_credit = 0  # state-only CLEAN restart
        if not actual:
            bucket = "C3"
            reason = "digest not on observed frontier as a distinct credit identity match"
        elif all(c == 0 for c in credits) and previous_credit == 0:
            bucket = "C1"
            reason = "production identities are CLEAN; restart preserved credit 0"
        elif any(c > 0 for c in credits) and previous_credit == 0:
            bucket = "C2"
            reason = "production had credit>0 identities; restart forced CLEAN"
        else:
            bucket = "C1"
            reason = "credit match"
        widened_same = any(row["origin"] == "credit_widening" for row in actual)
        return {
            "digest": digest,
            "previous_restart_identity": digest,
            "previous_restart_credit": previous_credit,
            "actual_credits": credits,
            "actual_origins": origins,
            "widened_same_tableau": widened_same,
            "bucket": bucket,
            "reason": reason,
        }

    gen1 = [classify_previous_root(d) for d in gen_roots.get("1", [])]
    later = {
        gen: [classify_previous_root(d) for d in digests]
        for gen, digests in gen_roots.items()
        if gen != "0"
    }
    # C3 omitted widened nodes: live or unexpanded widened identities never selectable
    # by digest-only retained-child selection.
    retained_child_digests = set()
    for rows in observer.retained.values():
        for row in rows:
            retained_child_digests.add(row["child"])
    omitted_widened = [
        row for row in widened_pushed
        if row["digest"] not in retained_child_digests
        or row["credit"] > 0
    ]
    c1 = sum(1 for row in gen1 if row["bucket"] == "C1")
    c2 = sum(1 for row in gen1 if row["bucket"] == "C2")
    c3_roots = sum(1 for row in gen1 if row["bucket"] == "C3")
    print("Gate D gen1", {"C1": c1, "C2": c2, "C3": c3_roots}, "omitted_widened", len(omitted_widened), flush=True)

    # Gate E: up to 4 expanded nodes per credit > 0, digest order
    fidelity = []
    extra_context = []
    reset_losses = []
    by_credit_expanded = defaultdict(list)
    for rec in observer.expanded:
        by_credit_expanded[rec["credit"]].append(rec)
    for credit in range(1, 5):
        chosen = sorted(by_credit_expanded[credit], key=lambda row: row["digest"])[:4]
        for rec in chosen:
            ident = rec["identity"]
            original = observer.generated.get(ident, [])
            state = observer.states[(rec["digest"], rec["credit"])]
            replay = reconstruct_and_generate(state, cards, credit=rec["credit"], g=rec["g"])
            cmp = compare_sigs(original, replay)
            fidelity.append(
                {
                    "identity": ident,
                    "digest": rec["digest"],
                    "credit": rec["credit"],
                    "g": rec["g"],
                    "incoming_kind": rec["incoming_kind"],
                    "comparison": cmp,
                }
            )
            if not cmp["equal"]:
                extra_context.append(ident)
            clean = reconstruct_and_generate(state, cards, credit=0, g=rec["g"])
            lost_kinds = [
                row["kind"]
                for row in original
                if sig_key(row) not in {sig_key(item) for item in clean}
            ]
            reset_losses.append(
                {
                    "identity": ident,
                    "credit": rec["credit"],
                    "original_kinds": [row["kind"] for row in original],
                    "clean_kinds": [row["kind"] for row in clean],
                    "lost_kinds": lost_kinds,
                    "lost_raw": lost_kinds.count("RAW_TABLEAU_MOVE"),
                    "lost_count": len(lost_kinds),
                }
            )

    print(
        f"Gate E fixtures={len(fidelity)} exact_match={sum(1 for row in fidelity if row['comparison']['equal'])}",
        flush=True,
    )

    # Live non-CLEAN nodes were never expanded. Reconstruct same-credit vs CLEAN
    # to measure coverage the previous forest omitted.
    live_deltas = []
    live_nonclean = sorted(
        [row for row in live if row["credit"] > 0],
        key=lambda row: (row["credit"], row["digest"]),
    )
    for rec in live_nonclean[:8]:
        state = observer.states.get((rec["digest"], rec["credit"]))
        if state is None:
            continue
        at_credit = reconstruct_and_generate(state, cards, credit=rec["credit"], g=rec["g"])
        at_clean = reconstruct_and_generate(state, cards, credit=0, g=rec["g"])
        cmp = compare_sigs(at_credit, at_clean)
        live_deltas.append(
            {
                "identity": rec["identity"],
                "credit": rec["credit"],
                "g": rec["g"],
                "credit_kinds": [row["kind"] for row in at_credit],
                "clean_kinds": [row["kind"] for row in at_clean],
                "equal_to_clean": cmp["equal"],
                "raw_at_credit": sum(1 for row in at_credit if row["kind"] == "RAW_TABLEAU_MOVE"),
                "raw_at_clean": sum(1 for row in at_clean if row["kind"] == "RAW_TABLEAU_MOVE"),
            }
        )
    print(
        f"  live non-CLEAN reconstructed={len(live_deltas)} "
        f"differ_from_clean={sum(1 for row in live_deltas if not row['equal_to_clean'])}",
        flush=True,
    )

    # Gate F: every expanded or live credit-4 node
    raw_rows = []
    credit4 = [
        rec for rec in observer.expanded + live if rec["credit"] == 4
    ]
    seen4 = set()
    unique4 = []
    for rec in credit4:
        if rec["identity"] in seen4:
            continue
        seen4.add(rec["identity"])
        unique4.append(rec)
    for rec in unique4:
        ident = rec["identity"]
        state = observer.states.get((rec["digest"], rec["credit"]))
        if state is None:
            continue
        if ident in observer.generated:
            succs = observer.generated[ident]
        else:
            succs = reconstruct_and_generate(state, cards, credit=4, g=rec["g"])
        lower = []
        for c in range(0, 4):
            lower.extend(observer.generated.get(continuation_identity(rec["digest"], c), []))
        lower_actions = {
            sig_key(row)[1]
            for row in lower
        }
        raws = [row for row in succs if row["kind"] == "RAW_TABLEAU_MOVE"]
        for row in raws:
            action = row["actions"][0]
            if not isinstance(action, list) or len(action) != 3:
                continue
            anatomy = classify_raw_move(state, tuple(action))
            act_key = tuple(action)
            anatomy["already_at_lower_credit"] = (act_key,) in lower_actions
            anatomy["parent"] = ident
            raw_rows.append(anatomy)

    n_reveal = sum(1 for row in raw_rows if row["flips_face_down_immediately"] or row["reduces_total_face_down"])
    n_empty = sum(1 for row in raw_rows if row["empties_column"])
    n_depth = sum(1 for row in raw_rows if row["reduces_min_face_down_depth"])
    n_overlap = sum(1 for row in raw_rows if row["already_at_lower_credit"])
    print(
        f"Gate F credit4_nodes={len(unique4)} raw={len(raw_rows)} reveal={n_reveal} empty={n_empty} depth={n_depth}",
        flush=True,
    )

    payload = {
        "base_sha": "debabe17359c2f986252220aae8ed8c113c352e6",
        "static": static,
        "production_run": {
            "stop_reason": result.stop_reason,
            "expansions": result.strategic_expansions,
            "status": result.status.value,
        },
        "expanded_credit_histogram": _hist(expanded_credits),
        "terminal_frontier_credit_histogram": _hist(live_credits),
        "widened": {
            "pushed": len(widened_pushed),
            "popped": len(widened_popped),
            "expanded": len(widened_expanded),
            "live": len(widened_live),
        },
        "tableau_states_with_multiple_credits": len(multi),
        "multi_credit_examples": [
            {"digest": digest, "credits": credits}
            for digest, credits in list(sorted(multi.items()))[:12]
        ],
        "previous_gen1_roots": gen1,
        "previous_later_roots": later,
        "c_counts": {
            "C1": c1,
            "C2": c2,
            "C3_gen1_roots": c3_roots,
            "C3_omitted_widened_pushes": len(omitted_widened),
        },
        "exact_credit_fidelity": {
            "n": len(fidelity),
            "equal": sum(1 for row in fidelity if row["comparison"]["equal"]),
            "rows": fidelity,
        },
        "additional_context_required": extra_context,
        "clean_reset_losses": reset_losses,
        "live_nonclean_vs_clean": live_deltas,
        "raw_fallback": {
            "credit4_nodes": len(unique4),
            "raw_move_count": len(raw_rows),
            "reveal": n_reveal,
            "empty": n_empty,
            "reduces_buried_depth": n_depth,
            "already_at_lower_credit": n_overlap,
            "moves": raw_rows[:80],
        },
        "expanded_nodes": [
            {k: rec[k] for k in ("identity", "digest", "credit", "g", "origin", "incoming_kind")}
            for rec in observer.expanded
        ],
        "live_nodes": [
            {k: rec[k] for k in ("identity", "digest", "credit", "g", "origin", "incoming_kind")}
            for rec in live
        ],
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
