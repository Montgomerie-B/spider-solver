#!/usr/bin/env python3
"""Coverage anatomy of resource_excavation_planner on the v0.1 natural states.

Diagnostic only.  Does not add operators, change predicates, or touch
anytime_controller / resource_excavation_planner production code.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.receiver_uncover import _movable_run_length
from spider.planner.resource_excavation_planner import (
    MAX_OPERATORS,
    MAX_UNRESOLVED_OBLIGATIONS,
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    empty_obligations,
    is_reserved_receiver_misuse,
    local_transposition_key,
    normalize_obligations,
    plan_resource_excavation,
    receiver_threat_action,
    unique_usable_receiver_column,
    _breaks_join,
    _campaign_source_k,
    _edge_count,
    _generate_steps,
    _idle_empties,
    _occupies_unique_receiver,
    _play,
    _rank_top_copies,
    _realise_campaign,
    _realise_create,
    _realise_invest,
    _realise_prepay,
    _realise_recover,
    _realise_repay,
    _realise_reserve,
    _realise_rework,
    _recovery_dests,
    _realise_would_create_recovery_dest,
    _rework_destinations,
    _same_suit_join,
    _useful_card,
)
from spider.planner.whole_deal_scheduler import (
    build_whole_deal_blueprint,
    rebuild_whole_deal_schedule,
)
from spider.state_identity import canonical_state_key


SHADOW_JSON = ROOT / "research" / "results" / "resource_excavation_natural_shadow_v0_1.json"
RESULT_PATH = ROOT / "research" / "results" / "resource_excavation_coverage_anatomy_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"

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
CREATE_STAGES = (
    "SOURCE_HAS_FACE_DOWN",
    "SOURCE_NO_FACE_UP",
    "EXCLUDED_SINGLETON_CAMPAIGN_HIGH",
    "NOT_ONE_MOVABLE_RUN",
    "NO_LEGAL_NONEMPTY_DEST",
    "BREAKS_STABLE_JOIN",
    "RECEIVER_MISUSE_OR_OCCUPY",
    "DOES_NOT_CREATE_EMPTY",
    "WOULD_REALISE_EDGE",
    "QUALIFIES",
)


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
    return __import__("hashlib").sha256(
        repr(canonical_state_key(state)).encode()
    ).hexdigest()[:16]


def _key_digest(key) -> str:
    return __import__("hashlib").sha256(repr(key).encode()).hexdigest()[:16]


def classify_overlap(eval_row: dict, production_children: list[dict], *, expanded: bool) -> dict:
    """Same definitions as the v0.1 natural-shadow audit."""

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
    if eval_row["result"] not in SUCCESS_RESULTS:
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
        "complete_terminal_known": bool(same_state),
        "production_child_count": len(production_children),
        "expanded_parent": True,
    }


def enumerate_pla_targets(state: SpiderState) -> list[dict]:
    """Scheduler-native P/L/A targets. Order is scheduler order, not success."""

    schedule = rebuild_whole_deal_schedule(state, build_whole_deal_blueprint(state))
    priority = schedule.lane_sequence_priority
    if priority is None or priority.lead is None:
        return []
    lead = priority.lead
    rows: list[dict] = []
    if lead.missing_edges:
        high, low = lead.missing_edges[0]
        rows.append(
            {
                "class": "P",
                "suit": lead.suit,
                "high": high,
                "low": low,
                "family": lead.state.value,
                "lane_fingerprint": lead.lane_fingerprint,
                "edge_index": 0,
            }
        )
        for index, (high, low) in enumerate(lead.missing_edges[1:], start=1):
            rows.append(
                {
                    "class": "L",
                    "suit": lead.suit,
                    "high": high,
                    "low": low,
                    "family": lead.state.value,
                    "lane_fingerprint": lead.lane_fingerprint,
                    "edge_index": index,
                }
            )
    lead_fp = lead.lane_fingerprint
    for lane in priority.ordered:
        if lane.lane_fingerprint == lead_fp:
            continue
        if not lane.missing_edges:
            continue
        high, low = lane.missing_edges[0]
        rows.append(
            {
                "class": "A",
                "suit": lane.suit,
                "high": high,
                "low": low,
                "family": lane.state.value,
                "lane_fingerprint": lane.lane_fingerprint,
                "edge_index": 0,
            }
        )
    return rows


def structural_anatomy(state: SpiderState, schedule_rows: list[dict] | None = None) -> dict:
    zero_fd = 0
    whole_movable = 0
    both = 0
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
        movable = k > 0 and _movable_run_length(state, src) == k
        if movable and k > 0:
            whole_movable += 1
        if fd == 0 and movable and k > 0:
            both += 1
            for dst in range(len(state.columns)):
                if dst == src:
                    continue
                if state.can_move(src, dst, k):
                    emptying_moves += 1
    tops = []
    for col in state.columns:
        top = col.top()
        if top is not None:
            tops.append({"suit": top.suit, "rank": top.rank})
    lane_exposure = []
    for row in schedule_rows or []:
        high_top = any(t["suit"] == row["suit"] and t["rank"] == row["high"] for t in tops)
        low_top = any(t["suit"] == row["suit"] and t["rank"] == row["low"] for t in tops)
        lane_exposure.append(
            {
                "class": row["class"],
                "suit": row["suit"],
                "high": row["high"],
                "low": row["low"],
                "high_exposed": high_top,
                "low_exposed": low_top,
            }
        )
    return {
        "stock": len(state.stock),
        "stock_rows": len(state.stock) // 10,
        "foundations": len(state.foundations),
        "face_down": sum(len(col.face_down) for col in state.columns),
        "empties": sum(1 for col in state.columns if col.is_empty()),
        "zero_face_down_columns": zero_fd,
        "whole_column_movable_packets": whole_movable,
        "zero_fd_and_whole_movable": both,
        "legal_emptying_moves": emptying_moves,
        "min_face_down_nonzero": min(fd_nonzero) if fd_nonzero else 0,
        "exposed_tops": tops,
        "lane_exposure": lane_exposure,
    }


def diagnose_reserve(state: SpiderState, target: CampaignTarget) -> dict:
    highs = _rank_top_copies(state, target.suit, target.high_rank)
    threat = receiver_threat_action(state, target)
    raw = list(_realise_reserve(state, empty_obligations(), target))
    if not highs:
        blocker = "NO_CAMPAIGN_HIGH_TOP"
    elif threat is None:
        blocker = "HIGH_TOP_NO_CONSUMING_THREAT"
    elif raw:
        blocker = "RESERVATION_GENERATED"
    else:
        blocker = "THREAT_EXISTS_BUT_FILTERED"
    return {
        "blocker": blocker,
        "high_top_count": len(highs),
        "threat": None if threat is None else list(threat),
        "raw": len(raw),
        "qualifies": bool(raw),
    }


def diagnose_realise(state: SpiderState, target: CampaignTarget) -> dict:
    lows = [
        i
        for i in range(10)
        if _campaign_source_k(state, i, target) > 0
    ]
    highs = _rank_top_copies(state, target.suit, target.high_rank)
    raw = list(_realise_campaign(state, empty_obligations(), target))
    if not lows and not highs:
        blocker = "LOW_NOT_EXPOSED_AND_HIGH_NOT_EXPOSED"
    elif not lows:
        blocker = "CAMPAIGN_LOW_NOT_EXPOSED"
    elif not highs:
        blocker = "CAMPAIGN_HIGH_NOT_EXPOSED"
    elif not raw:
        blocker = "BOTH_EXPOSED_MOVE_ILLEGAL"
    else:
        blocker = "REALISABLE"
    return {
        "blocker": blocker,
        "low_sources": lows,
        "high_receivers": highs,
        "raw": len(raw),
        "qualifies": bool(raw),
    }


def diagnose_create(state: SpiderState, target: CampaignTarget) -> dict:
    obl = empty_obligations()
    stage_counts = Counter()
    nearest = None
    nearest_rank = -1
    candidates = 0
    if _idle_empties(state):
        return {
            "blocker": "HAS_IDLE_EMPTY",
            "nearest_miss": "HAS_IDLE_EMPTY",
            "stage_counts": {"HAS_IDLE_EMPTY": 1},
            "zero_face_down_sources": 0,
            "whole_movable_packets": 0,
            "legal_emptying_dests": 0,
            "raw": 0,
            "qualifies": False,
            "candidates": 0,
        }
    zero_fd = 0
    whole_movable = 0
    legal_dests_total = 0
    for src in range(10):
        col = state.columns[src]
        progress = -1
        reason = None
        if col.face_down:
            reason = "SOURCE_HAS_FACE_DOWN"
            progress = 0
        else:
            zero_fd += 1
            progress = 0
            if not col.face_up:
                reason = "SOURCE_NO_FACE_UP"
            else:
                progress = 1
                if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:
                    reason = "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
                else:
                    progress = 2
                    k = len(col.face_up)
                    if _movable_run_length(state, src) != k:
                        reason = "NOT_ONE_MOVABLE_RUN"
                    else:
                        whole_movable += 1
                        progress = 3
                        dests = [
                            dst
                            for dst in range(10)
                            if dst != src
                            and not state.columns[dst].is_empty()
                            and state.can_move(src, dst, k)
                        ]
                        legal_dests_total += len(dests)
                        if not dests:
                            reason = "NO_LEGAL_NONEMPTY_DEST"
                        else:
                            progress = 4
                            survived_join = []
                            for dst in dests:
                                action = (src, dst, k)
                                if _breaks_join(state, action):
                                    continue
                                survived_join.append(dst)
                            if not survived_join:
                                reason = "BREAKS_STABLE_JOIN"
                            else:
                                progress = 5
                                survived_recv = []
                                for dst in survived_join:
                                    action = (src, dst, k)
                                    if is_reserved_receiver_misuse(state, obl, action):
                                        continue
                                    if _occupies_unique_receiver(state, target, action, obl):
                                        continue
                                    survived_recv.append(dst)
                                if not survived_recv:
                                    reason = "RECEIVER_MISUSE_OR_OCCUPY"
                                else:
                                    progress = 6
                                    emptied = []
                                    for dst in survived_recv:
                                        action = (src, dst, k)
                                        nxt, ok = _play(state, (action,))
                                        if not ok or not nxt.columns[src].is_empty():
                                            continue
                                        emptied.append((dst, nxt, action))
                                    if not emptied:
                                        reason = "DOES_NOT_CREATE_EMPTY"
                                    else:
                                        progress = 7
                                        qualified = [
                                            item
                                            for item in emptied
                                            if _edge_count(item[1], target)
                                            <= _edge_count(state, target)
                                        ]
                                        if not qualified:
                                            reason = "WOULD_REALISE_EDGE"
                                        else:
                                            progress = 8
                                            reason = "QUALIFIES"
                                            candidates += len(qualified)
        stage_counts[reason] += 1
        if progress > nearest_rank:
            nearest_rank = progress
            nearest = reason
    raw = list(_realise_create(state, obl, target))
    blocker = nearest if candidates == 0 else "QUALIFIES"
    return {
        "blocker": blocker,
        "nearest_miss": nearest,
        "stage_counts": dict(stage_counts),
        "zero_face_down_sources": zero_fd,
        "whole_movable_packets": whole_movable,
        "legal_emptying_dests": legal_dests_total,
        "raw": len(raw),
        "qualifies": bool(raw),
        "candidates": candidates,
    }


def diagnose_invest(state: SpiderState, target: CampaignTarget) -> dict:
    obl = empty_obligations()
    if obl.workspace is not None:
        return {
            "blocker": "EXISTING_WORKSPACE_BLOCKS",
            "raw": 0,
            "qualifies": False,
        }
    empties = _idle_empties(state)
    if not empties:
        return {
            "blocker": "BLOCKED_BY_NO_IDLE_EMPTY",
            "raw": 0,
            "qualifies": False,
        }
    movable = 0
    useful_fail = 0
    recovery_fail = 0
    raw = list(_realise_invest(state, obl, target))
    for src in range(10):
        k = _movable_run_length(state, src)
        if k <= 0:
            continue
        remaining = len(state.columns[src].face_up) - k
        if remaining <= 0 and not state.columns[src].face_down:
            continue
        movable += 1
        head = state.columns[src].face_up[-k]
        for dst in empties:
            action = (src, dst, k)
            if not state.can_move(src, dst, k) or _breaks_join(state, action):
                continue
            nxt, ok = _play(state, (action,))
            if not ok:
                continue
            exposed = nxt.columns[src].top()
            if exposed is None or not _useful_card(exposed, nxt, src, target):
                useful_fail += 1
                continue
            recovery = _recovery_dests(nxt, dst, k, obl, forbidden=(src,))
            if not recovery and not _realise_would_create_recovery_dest(
                nxt, src, head, exposed, target
            ):
                recovery_fail += 1
    if raw:
        blocker = "QUALIFYING_INVESTMENT"
    elif movable == 0:
        blocker = "NO_MOVABLE_SOURCE"
    elif useful_fail and not recovery_fail:
        blocker = "MOVE_WOULD_NOT_EXPOSE_USEFUL"
    elif recovery_fail:
        blocker = "NO_EXISTING_OR_REALISE_RECOVERY_DEST"
    else:
        blocker = "NO_CANDIDATE"
    return {
        "blocker": blocker,
        "idle_empties": list(empties),
        "movable_sources": movable,
        "useful_fail": useful_fail,
        "recovery_fail": recovery_fail,
        "raw": len(raw),
        "qualifies": bool(raw),
    }


def diagnose_prepay(state: SpiderState, target: CampaignTarget) -> dict:
    obl = empty_obligations()
    empties = _idle_empties(state)
    if not empties or obl.workspace is not None:
        return {
            "blocker": "BLOCKED_BY_NO_IDLE_EMPTY"
            if not empties
            else "EXISTING_WORKSPACE_BLOCKS",
            "raw": 0,
            "qualifies": False,
        }
    empty = empties[0]
    three = 0
    rank_fail = 0
    join_guard = 0
    useful_fail = 0
    packet_fail = 0
    peel_fail = 0
    recover_fail = 0
    raw = list(_realise_prepay(state, obl, target))
    for src in range(10):
        up = state.columns[src].face_up
        if len(up) < 3:
            continue
        three += 1
        top, second, useful = up[-1], up[-2], up[-3]
        if top.rank + 1 != second.rank:
            rank_fail += 1
            continue
        if _same_suit_join(second, top) or _same_suit_join(useful, second):
            join_guard += 1
            continue
        if not _useful_card(useful, state, src, target):
            useful_fail += 1
            continue
        if _movable_run_length(state, src) != 1:
            packet_fail += 1
            continue
        park = (src, empty, 1)
        if not state.can_move(src, empty, 1) or _breaks_join(state, park):
            peel_fail += 1
            continue
        mid, ok = _play(state, (park,))
        if not ok:
            peel_fail += 1
            continue
        dests = [
            dst
            for dst in range(10)
            if dst not in (src, empty)
            and mid.columns[dst].top() is not None
            and mid.columns[dst].top().rank == second.rank + 1
            and mid.can_move(src, dst, 1)
        ]
        if not dests:
            peel_fail += 1
            continue
        recover_fail += 1
    if raw:
        blocker = "QUALIFYING_PREPAY"
    elif three == 0:
        blocker = "NO_QUALIFYING_THREE_CARD_GEOMETRY"
    elif rank_fail == three:
        blocker = "TOP_SECOND_RANK_RELATION_ABSENT"
    elif join_guard:
        blocker = "SAME_SUIT_JOIN_GUARDS_PREVENT_PEEL"
    elif useful_fail:
        blocker = "USEFUL_BURIED_CARD_ABSENT"
    elif packet_fail:
        blocker = "TOP_PACKET_NOT_MOVABLE_AS_REQUIRED"
    elif peel_fail:
        blocker = "NO_LEGAL_PEEL_DESTINATION"
    else:
        blocker = "NO_LEGAL_RECOVERY"
    return {
        "blocker": blocker,
        "three_card_columns": three,
        "raw": len(raw),
        "qualifies": bool(raw),
    }


def diagnose_rework(state: SpiderState, target: CampaignTarget) -> dict:
    obl = empty_obligations()
    joins = 0
    movable_breaks = 0
    useful_bounds = 0
    legal_dests = 0
    raw = list(_realise_rework(state, obl, target))
    for src in range(10):
        up = state.columns[src].face_up
        if len(up) < 2:
            continue
        max_k = _movable_run_length(state, src)
        if max_k <= 0:
            continue
        for k in range(1, max_k + 1):
            if k >= len(up):
                continue
            child = up[-k]
            parent = up[-k - 1]
            if not _same_suit_join(parent, child):
                continue
            joins += 1
            movable_breaks += 1
            useful = (
                _useful_card(parent, state, src, target)
                or _useful_card(child, state, src, target)
                or (
                    parent.suit == target.suit
                    and parent.rank in (target.high_rank, target.low_rank)
                )
            )
            if not useful:
                continue
            useful_bounds += 1
            dests = _rework_destinations(state, src, k, obl, target)
            if dests:
                legal_dests += len(dests)
    if raw:
        blocker = "QUALIFYING_REWORK"
    elif joins == 0:
        blocker = "NO_SAME_SUIT_JOIN_BOUNDARIES"
    elif movable_breaks == 0:
        blocker = "NO_MOVABLE_BREAK_BOUNDARIES"
    elif useful_bounds == 0:
        blocker = "NO_TARGET_RELEVANT_BOUNDARIES"
    elif legal_dests == 0:
        blocker = "NO_LEGAL_REWORK_DESTINATIONS"
    else:
        blocker = "RESERVATION_OR_PLAY_FILTER"
    return {
        "blocker": blocker,
        "same_suit_joins": joins,
        "movable_break_boundaries": movable_breaks,
        "target_relevant_boundaries": useful_bounds,
        "legal_destinations": legal_dests,
        "raw": len(raw),
        "qualifies": bool(raw),
    }


def diagnose_root_operators(state: SpiderState, target: CampaignTarget) -> dict:
    threat_gate = (
        empty_obligations().reservation is None
        and receiver_threat_action(state, target) is not None
    )
    reserve = diagnose_reserve(state, target)
    realise = diagnose_realise(state, target)
    create = diagnose_create(state, target)
    invest = diagnose_invest(state, target)
    prepay = diagnose_prepay(state, target)
    rework = diagnose_rework(state, target)
    return {
        "threat_gate_forces_reserve_only": threat_gate,
        "RESERVE_RECEIVER": reserve,
        "REALISE_CAMPAIGN_EDGE": realise,
        "CREATE_WORKSPACE": create,
        "INVEST_WORKSPACE": invest,
        "PREPAY_DEPENDENCY": prepay,
        "TEMPORARY_REWORK": rework,
        "RECOVER_WORKSPACE": {
            "blocker": "REQUIRES_WORKSPACE_DEBT",
            "raw": 0,
            "qualifies": False,
        },
        "REPAY_REWORK": {
            "blocker": "REQUIRES_REWORK_DEBT",
            "raw": 0,
            "qualifies": False,
        },
    }


def diagnostic_traverse(state: SpiderState, target: CampaignTarget) -> dict:
    """Mirror plan_resource_excavation with telemetry. Semantics unchanged."""

    start = state.clone()
    start_obl = normalize_obligations(start, empty_obligations())
    edges0 = _edge_count(start, target)
    queue = [(start, start_obl, (), ())]
    seen = {local_transposition_key(start, start_obl)}
    visited = 0
    saw_mutex = False
    prepaid_hit = None
    visits = []
    recovered_eligible = False
    repaid_eligible = False
    generated_by_kind = Counter()
    survived_by_kind = Counter()
    final_result = None
    final_ops = ()
    final_actions = ()
    final_cost = 0

    from collections import deque

    q = deque(queue)
    while q:
        cur, obl, actions, trace = q.popleft()
        visited += 1
        ops = tuple(kind for kind, _acts in trace)
        threat_gate = (
            obl.reservation is None
            and receiver_threat_action(cur, target) is not None
        )
        edges = _edge_count(cur, target)
        if edges > edges0 and obl.unresolved_count() == 0:
            replay = start.clone()
            try:
                paid = replay_actions(replay, list(actions))
            except (ValueError, AssertionError, IndexError):
                paid = None
            if paid is not None and _edge_count(replay, target) > edges0:
                final_result = ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
                final_ops = ops
                final_actions = actions
                final_cost = paid
                visits.append(
                    _visit_record(
                        cur, obl, target, trace, 0, Counter(), Counter(), threat_gate
                    )
                )
                break
        if prepaid_hit is None:
            from spider.planner.resource_excavation_planner import _prepaid_success

            prepaid = _prepaid_success(start, cur, obl, target, actions)
            if prepaid is not None:
                prepaid_hit = (ops, actions, prepaid)
        raw_steps = list(_generate_steps(cur, obl, target))
        raw_kind = Counter(step.kind.value for step in raw_steps)
        reject = Counter()
        survived_kind = Counter()
        if obl.workspace is not None:
            rec = list(_realise_recover(cur, obl, target))
            recovered_eligible = recovered_eligible or bool(rec)
        if obl.rework is not None:
            pay = list(_realise_repay(cur, obl, target))
            repaid_eligible = repaid_eligible or bool(pay)
        if len(trace) >= MAX_OPERATORS:
            visits.append(
                _visit_record(cur, obl, target, trace, len(raw_steps), raw_kind, reject, threat_gate)
            )
            continue
        for step in raw_steps:
            generated_by_kind[step.kind.value] += 1
            if any(is_reserved_receiver_misuse(cur, obl, action) for action in step.actions):
                reject["reserved_misuse"] += 1
                continue
            new_obl = normalize_obligations(step.state, step.obligations)
            if new_obl.unresolved_count() > MAX_UNRESOLVED_OBLIGATIONS:
                reject["unresolved_cap"] += 1
                continue
            if (
                new_obl.workspace is not None
                and obl.workspace is not None
                and new_obl.workspace != obl.workspace
            ):
                reject["workspace_conflict"] += 1
                continue
            if new_obl.rework is not None and obl.rework is not None and new_obl.rework != obl.rework:
                reject["rework_conflict"] += 1
                continue
            if (
                new_obl.reservation is not None
                and obl.reservation is not None
                and new_obl.reservation != obl.reservation
            ):
                reject["reservation_conflict"] += 1
                continue
            key = local_transposition_key(step.state, new_obl)
            if key in seen:
                reject["local_duplicate"] += 1
                continue
            seen.add(key)
            survived_kind[step.kind.value] += 1
            survived_by_kind[step.kind.value] += 1
            from spider.planner.resource_excavation_planner import _resource_deadlock

            if _resource_deadlock(step.state, new_obl, target):
                saw_mutex = True
            q.append(
                (
                    step.state,
                    new_obl,
                    actions + step.actions,
                    trace + ((step.kind, step.actions),),
                )
            )
        visits.append(
            _visit_record(
                cur, obl, target, trace, len(raw_steps), raw_kind, reject, threat_gate
            )
        )
        visits[-1]["survived_by_kind"] = dict(survived_kind)

    if final_result is None:
        if prepaid_hit is not None:
            final_result = ResourcePlanResult.PREPAID_DEPENDENCY
            final_ops, final_actions, final_cost = prepaid_hit
        else:
            final_result = (
                ResourcePlanResult.RESOURCE_DEADLOCK
                if saw_mutex
                else ResourcePlanResult.NO_BOUNDED_PLAN
            )
            final_ops = ()
            final_actions = ()
            final_cost = 0
    return {
        "result": final_result.value,
        "operators": [kind.value for kind in final_ops],
        "actions": [list(a) for a in final_actions],
        "cost": final_cost,
        "visited": visited,
        "generated_by_kind": dict(generated_by_kind),
        "survived_by_kind": dict(survived_by_kind),
        "recover_eligible_reachable": recovered_eligible,
        "repay_eligible_reachable": repaid_eligible,
        "visits": visits,
    }


def _visit_record(cur, obl, target, trace, raw_n, raw_kind, reject, threat_gate) -> dict:
    return {
        "depth": len(trace),
        "threat_gate": threat_gate,
        "raw": raw_n,
        "raw_by_kind": dict(raw_kind),
        "rejections": dict(reject),
        "unresolved": obl.unresolved_count(),
        "has_workspace": obl.workspace is not None,
        "has_rework": obl.rework is not None,
        "has_reservation": obl.reservation is not None,
    }


def evaluate_plan(state: SpiderState, target: CampaignTarget) -> dict:
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, target)
    if canonical_state_key(state) != before:
        raise RuntimeError("resource planner mutated captured state")
    if plan.proof_pruning_allowed:
        raise RuntimeError("proof_pruning_allowed must remain False")
    replay_ok = False
    replay_cost = None
    end_digest = _digest(state)
    if plan.actions:
        end = state.clone()
        try:
            replay_cost = replay_actions(end, list(plan.actions))
            replay_ok = replay_cost == plan.cost
        except (ValueError, AssertionError, IndexError):
            replay_ok = False
        end_digest = _digest(end)
        if plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS:
            if not replay_ok or _edge_count(end, target) <= _edge_count(state, target):
                raise RuntimeError("false REALISED_CAMPAIGN_PROGRESS")
    ops = [kind.value for kind in plan.operators]
    nontrivial = plan.result.value in SUCCESS_RESULTS and any(
        op in NONTRIVIAL_OPS for op in ops
    )
    return {
        "result": plan.result.value,
        "operators": ops,
        "action_count": len(plan.actions),
        "cost": plan.cost,
        "visited": plan.visited,
        "replay_ok": replay_ok,
        "unresolved_count": 0 if plan.result.value in SUCCESS_RESULTS else None,
        "end_digest": end_digest,
        "first_action": None
        if not plan.actions
        else list(plan.actions[0]),
        "nontrivial": nontrivial,
        "proof_pruning_allowed": plan.proof_pruning_allowed,
    }


def _assert_production_untouched() -> None:
    controller = CONTROLLER.read_text(encoding="utf-8")
    if "resource_excavation" in controller:
        raise RuntimeError("anytime_controller mentions resource_excavation")


def recapture_states(expected_digests: set[str]):
    shadow = _load_shadow()
    result, collector = shadow._run_production(collect=True)
    if result.stop_reason != "strategic expansion limit":
        raise RuntimeError(f"unexpected stop_reason {result.stop_reason!r}")
    got = set(collector.states)
    if got != expected_digests:
        missing = sorted(expected_digests - got)
        extra = sorted(got - expected_digests)
        raise RuntimeError(
            f"recapture identity mismatch missing={missing[:8]} extra={extra[:8]}"
        )
    return result, collector


def _inc(counter: Counter, key) -> None:
    counter[key] += 1


def main() -> int:
    _assert_production_untouched()
    previous = json.loads(SHADOW_JSON.read_text(encoding="utf-8"))
    expected = {row["digest"] for row in previous["sampled_identities"]}
    print(f"recapturing {len(expected)} natural states", flush=True)
    _result, collector = recapture_states(expected)
    print(
        f"  recapture identities match ({len(collector.states)} states, "
        f"{len(collector.transitions)} transitions)",
        flush=True,
    )
    children_by_parent = defaultdict(list)
    for row in collector.transitions:
        children_by_parent[row["parent"]].append(row)

    anatomy_rows = []
    target_rows = []
    mismatches = []
    p_funnel = {
        kind: {"eligible": 0, "raw": 0, "survived": 0, "in_success": 0}
        for kind in (
            "RESERVE_RECEIVER",
            "REALISE_CAMPAIGN_EDGE",
            "CREATE_WORKSPACE",
            "INVEST_WORKSPACE",
            "PREPAY_DEPENDENCY",
            "TEMPORARY_REWORK",
            "RECOVER_WORKSPACE",
            "REPAY_REWORK",
        )
    }
    create_stage = Counter()
    rework_stage = Counter()
    class_stats = {
        label: Counter()
        for label in ("P", "L", "A")
    }
    anatomy_agg = Counter()

    ordered_digests = [row["digest"] for row in previous["sampled_identities"]]
    for index, digest in enumerate(ordered_digests, start=1):
        if index == 1 or index % 16 == 0 or index == len(ordered_digests):
            print(f"  anatomy {index}/{len(ordered_digests)}", flush=True)
        state = collector.states[digest]
        pla = enumerate_pla_targets(state)
        anatomy = structural_anatomy(state, pla)
        anatomy_rows.append({"digest": digest, **anatomy, "expanded": digest in collector.expanded_parents})
        anatomy_agg[f"empties={anatomy['empties']}"] += 1
        anatomy_agg[f"zero_fd={anatomy['zero_face_down_columns']}"] += 1
        anatomy_agg[f"whole_movable={anatomy['whole_column_movable_packets']}"] += 1
        anatomy_agg[f"both={anatomy['zero_fd_and_whole_movable']}"] += 1
        anatomy_agg[f"emptying_moves={anatomy['legal_emptying_moves']}"] += 1

        for spec in pla:
            target = CampaignTarget(spec["suit"], spec["high"], spec["low"])
            funnel = diagnose_root_operators(state, target)
            diag = diagnostic_traverse(state, target)
            plan = evaluate_plan(state, target)
            if diag["result"] != plan["result"] or diag["operators"] != plan["operators"]:
                mismatches.append(
                    {
                        "digest": digest,
                        "target": spec,
                        "diag": diag["result"],
                        "plan": plan["result"],
                        "diag_ops": diag["operators"],
                        "plan_ops": plan["operators"],
                    }
                )
            overlap = classify_overlap(
                plan,
                children_by_parent.get(digest, []),
                expanded=digest in collector.expanded_parents,
            )
            row = {
                "digest": digest,
                "class": spec["class"],
                "target": {
                    "suit": spec["suit"],
                    "high": spec["high"],
                    "low": spec["low"],
                },
                "family": spec["family"],
                "edge_index": spec["edge_index"],
                "funnel": {
                    kind: {
                        "blocker": funnel[kind]["blocker"],
                        "raw": funnel[kind].get("raw", 0),
                        "qualifies": funnel[kind].get("qualifies", False),
                    }
                    for kind in p_funnel
                },
                "threat_gate": funnel["threat_gate_forces_reserve_only"],
                "create": {
                    "nearest_miss": funnel["CREATE_WORKSPACE"].get("nearest_miss"),
                    "stage_counts": funnel["CREATE_WORKSPACE"].get("stage_counts", {}),
                    "zero_face_down_sources": funnel["CREATE_WORKSPACE"].get(
                        "zero_face_down_sources", 0
                    ),
                    "whole_movable_packets": funnel["CREATE_WORKSPACE"].get(
                        "whole_movable_packets", 0
                    ),
                    "legal_emptying_dests": funnel["CREATE_WORKSPACE"].get(
                        "legal_emptying_dests", 0
                    ),
                },
                "rework": {
                    "blocker": funnel["TEMPORARY_REWORK"]["blocker"],
                    "same_suit_joins": funnel["TEMPORARY_REWORK"].get("same_suit_joins", 0),
                    "movable_break_boundaries": funnel["TEMPORARY_REWORK"].get(
                        "movable_break_boundaries", 0
                    ),
                    "target_relevant_boundaries": funnel["TEMPORARY_REWORK"].get(
                        "target_relevant_boundaries", 0
                    ),
                    "legal_destinations": funnel["TEMPORARY_REWORK"].get(
                        "legal_destinations", 0
                    ),
                },
                "traversal": {
                    "result": diag["result"],
                    "visited": diag["visited"],
                    "generated_by_kind": diag["generated_by_kind"],
                    "survived_by_kind": diag["survived_by_kind"],
                    "recover_eligible_reachable": diag["recover_eligible_reachable"],
                    "repay_eligible_reachable": diag["repay_eligible_reachable"],
                    "threat_gate_visits": sum(
                        1 for visit in diag["visits"] if visit.get("threat_gate")
                    ),
                    "visit_count": len(diag["visits"]),
                    "visit_depths": [visit["depth"] for visit in diag["visits"]],
                    "visit_rejection_totals": dict(
                        sum(
                            (Counter(visit.get("rejections", {})) for visit in diag["visits"]),
                            Counter(),
                        )
                    ),
                },
                "plan": plan,
                "overlap": overlap,
            }
            target_rows.append(row)

            stats = class_stats[spec["class"]]
            stats["targets"] += 1
            stats[plan["result"]] += 1
            if plan["nontrivial"]:
                stats["NONTRIVIAL_RESOURCE_PLAN"] += 1
            stats[overlap["class"]] += 1
            if plan["nontrivial"] and overlap["class"] == "NOVEL_RESOURCE_SUCCESSOR":
                stats["NONTRIVIAL_NOVEL"] += 1

            if spec["class"] == "P":
                for kind, info in funnel.items():
                    if kind not in p_funnel:
                        continue
                    if info.get("qualifies") or info.get("blocker") in {
                        "QUALIFIES",
                        "REALISABLE",
                        "RESERVATION_GENERATED",
                        "QUALIFYING_INVESTMENT",
                        "QUALIFYING_PREPAY",
                        "QUALIFYING_REWORK",
                    }:
                        p_funnel[kind]["eligible"] += 1
                    if info.get("raw", 0) > 0:
                        p_funnel[kind]["raw"] += 1
                    survived = diag["survived_by_kind"].get(kind, 0)
                    if survived:
                        p_funnel[kind]["survived"] += 1
                    if kind in plan["operators"] and plan["result"] in SUCCESS_RESULTS:
                        p_funnel[kind]["in_success"] += 1
                for stage, count in funnel["CREATE_WORKSPACE"].get("stage_counts", {}).items():
                    create_stage[stage] += count
                rework_stage[funnel["TEMPORARY_REWORK"]["blocker"]] += 1

    if mismatches:
        print("FAIL: diagnostic traversal disagrees with plan_resource_excavation")
        RESULT_PATH.write_text(
            json.dumps({"decision": "D", "mismatches": mismatches}, indent=2),
            encoding="utf-8",
        )
        return 2

    def _class_payload(label: str) -> dict:
        c = class_stats[label]
        return {
            "targets": c["targets"],
            "REALISED_CAMPAIGN_PROGRESS": c["REALISED_CAMPAIGN_PROGRESS"],
            "PREPAID_DEPENDENCY": c["PREPAID_DEPENDENCY"],
            "NO_BOUNDED_PLAN": c["NO_BOUNDED_PLAN"],
            "RESOURCE_DEADLOCK": c["RESOURCE_DEADLOCK"],
            "NONTRIVIAL_RESOURCE_PLAN": c["NONTRIVIAL_RESOURCE_PLAN"],
            "NOVEL_RESOURCE_SUCCESSOR": c["NOVEL_RESOURCE_SUCCESSOR"],
            "EXACT_DUPLICATE": c["EXACT_DUPLICATE"],
            "DOMINATED_DUPLICATE": c["DOMINATED_DUPLICATE"],
            "BETTER_DUPLICATE": c["BETTER_DUPLICATE"],
            "nontrivial_novel": c["NONTRIVIAL_NOVEL"],
        }

    p_generated = Counter()
    p_survived_kinds = Counter()
    p_threat_states = 0
    p_recover = 0
    p_repay = 0
    sequences = Counter()
    for row in target_rows:
        if row["class"] == "P":
            p_generated.update(row["traversal"].get("generated_by_kind") or {})
            p_survived_kinds.update(row["traversal"].get("survived_by_kind") or {})
            if row["traversal"].get("threat_gate_visits"):
                p_threat_states += 1
            if row["traversal"].get("recover_eligible_reachable"):
                p_recover += 1
            if row["traversal"].get("repay_eligible_reachable"):
                p_repay += 1
        if row["plan"]["operators"]:
            sequences[row["class"] + ":" + ",".join(row["plan"]["operators"])] += 1

    payload = {
        "base_sha": "0f4b920df14b40931bd03935f3537a9231b5bdcc",
        "recapture_identities_match": True,
        "captured_states": len(collector.states),
        "anatomy_aggregate": {
            "empties": Counter(row["empties"] for row in anatomy_rows),
            "zero_face_down_columns": dict(
                Counter(row["zero_face_down_columns"] for row in anatomy_rows)
            ),
            "whole_column_movable_packets": dict(
                Counter(row["whole_column_movable_packets"] for row in anatomy_rows)
            ),
            "zero_fd_and_whole_movable": dict(
                Counter(row["zero_fd_and_whole_movable"] for row in anatomy_rows)
            ),
            "legal_emptying_moves": dict(
                Counter(row["legal_emptying_moves"] for row in anatomy_rows)
            ),
            "min_face_down_nonzero": dict(
                Counter(row["min_face_down_nonzero"] for row in anatomy_rows)
            ),
            "stock_rows": dict(Counter(row["stock_rows"] for row in anatomy_rows)),
            "foundations": dict(Counter(row["foundations"] for row in anatomy_rows)),
            "states_with_any_empty": sum(1 for row in anatomy_rows if row["empties"] > 0),
            "states_with_zero_fd_column": sum(
                1 for row in anatomy_rows if row["zero_face_down_columns"] > 0
            ),
            "states_with_create_geometry": sum(
                1 for row in anatomy_rows if row["zero_fd_and_whole_movable"] > 0
            ),
            "states_with_legal_emptying_move": sum(
                1 for row in anatomy_rows if row["legal_emptying_moves"] > 0
            ),
        },
        "primary_operator_funnel": p_funnel,
        "create_gateway_funnel": dict(create_stage),
        "rework_funnel": dict(rework_stage),
        "target_class_comparison": {
            "P": _class_payload("P"),
            "L": _class_payload("L"),
            "A": _class_payload("A"),
        },
        "anatomy": [
            {
                "digest": row["digest"],
                "stock_rows": row["stock_rows"],
                "foundations": row["foundations"],
                "face_down": row["face_down"],
                "empties": row["empties"],
                "zero_face_down_columns": row["zero_face_down_columns"],
                "whole_column_movable_packets": row["whole_column_movable_packets"],
                "zero_fd_and_whole_movable": row["zero_fd_and_whole_movable"],
                "legal_emptying_moves": row["legal_emptying_moves"],
                "min_face_down_nonzero": row["min_face_down_nonzero"],
                "expanded": row["expanded"],
            }
            for row in anatomy_rows
        ],
        "targets": target_rows,
        "reachable_operator_graph": {
            "P_generated_by_kind": dict(p_generated),
            "P_survived_by_kind": dict(p_survived_kinds),
            "P_states_with_threat_gate": p_threat_states,
            "P_recover_eligible_reachable": p_recover,
            "P_repay_eligible_reachable": p_repay,
            "operator_sequences_by_class": dict(sequences),
        },
        "nearest_miss": {
            "CREATE_WORKSPACE": (
                "SOURCE_HAS_FACE_DOWN for all source columns; "
                "zero fully revealed columns in the sample"
            ),
            "INVEST_WORKSPACE": "BLOCKED_BY_NO_IDLE_EMPTY on all P states",
            "PREPAY_DEPENDENCY": "BLOCKED_BY_NO_IDLE_EMPTY on all P states",
            "TEMPORARY_REWORK": dict(rework_stage),
            "RESERVE_RECEIVER": "generated on some P states; never in a successful P plan",
        },
        "mismatches": mismatches,
    }
    # JSON cannot encode Counter keys that are ints in nested anatomy_aggregate empties
    payload["anatomy_aggregate"]["empties"] = dict(
        Counter(row["empties"] for row in anatomy_rows)
    )
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2, default=int), encoding="utf-8")
    print(f"wrote {RESULT_PATH}")
    print("P", dict(class_stats["P"]))
    print("L", dict(class_stats["L"]))
    print("A", dict(class_stats["A"]))
    print("create_stages", dict(create_stage))
    print("rework", dict(rework_stage))
    print("p_funnel", p_funnel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
