#!/usr/bin/env python3
"""CREATE_WORKSPACE suit-aware singleton-high guard counterfactual.

Research only. Production planner and controller are not modified.
G1 is a temporary monkeypatch of ``_realise_create`` that adds off-suit
same-rank singleton CREATE candidates; every other CREATE predicate is
the unchanged production function.
"""

from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import sys
import time
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.receiver_uncover import _movable_run_length
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ReceiverReservation,
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
import spider.planner.resource_excavation_planner as planner_mod
from spider.state_identity import canonical_state_key


DEAL_PATH = ROOT / "deals" / "4925153.txt"
RESULT_PATH = ROOT / "research" / "results" / "create_workspace_suit_aware_guard_counterfactual_v0_1.json"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
FIRST_R2 = "1c3d3ec77bf164ad"
FIRST_EMPTY_DIGEST = "19e9e5d1326854ed"
S_TERMINAL = "db8ff65b9ffe468d"
R2_PATHS = {
    "1c3d3ec77bf164ad": [(5, 7, 1), (2, 7, 1), (5, 7, 1), (5, 7, 1), (5, 4, 1)],
    "edb1f739a3100867": [(5, 7, 1), (2, 7, 1), (5, 7, 1), (5, 7, 1), (5, 4, 1), (2, 1, 1)],
    "de13114dc57870d7": [
        (5, 7, 1),
        (2, 7, 1),
        (5, 7, 1),
        (5, 7, 1),
        (5, 4, 1),
        (2, 1, 1),
        (7, 2, 5),
    ],
    "f729fad6e19cb5b5": [
        (5, 7, 1),
        (2, 7, 1),
        (5, 7, 1),
        (5, 7, 1),
        (5, 4, 1),
        (2, 1, 1),
        (7, 2, 5),
        (2, 7, 2),
    ],
}
P_TARGET = CampaignTarget("c", 12, 11)
S_TARGET = CampaignTarget("c", 11, 10)
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
    ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS,
    ResourcePlanResult.PREPAID_DEPENDENCY,
}
_ORIG_REALISE_CREATE = planner_mod._realise_create
assert _ORIG_REALISE_CREATE is _realise_create


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _harvest():
    return _load(
        "harvested_ws_v0_1",
        ROOT / "research" / "harvested_first_workspace_resource_priority_v0_1.py",
    )


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _action_json(action):
    if action == ("deal",) or action == "deal":
        return "deal"
    if isinstance(action, str):
        return action
    return list(action)


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _filled(slots: dict[int, list[Card]], *, empty: tuple[int, ...] = ()) -> SpiderState:
    cols = []
    for index in range(10):
        if index in empty:
            cols.append(Column([], []))
        elif index in slots:
            cols.append(Column([], list(slots[index])))
        else:
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
    return SpiderState(cols, [])


def reconstruct_r2(opening: SpiderState, digest: str) -> SpiderState:
    state = opening.clone()
    replay_actions(state, list(R2_PATHS[digest]))
    return state


def reconstruct_first_r2(opening: SpiderState) -> SpiderState:
    return reconstruct_r2(opening, FIRST_R2)


def verify_natural_r3(state: SpiderState) -> dict:
    harvest = _harvest()
    geom = harvest._cc().geometry(state)
    legal = harvest.legal_first_empty_moves(state)
    fd = sum(len(col.face_down) for col in state.columns)
    empties = sum(1 for col in state.columns if col.is_empty())
    revealed = sum(1 for col in state.columns if not col.face_down and col.face_up)
    row = {
        "digest": _digest(state),
        "face_down": fd,
        "fully_revealed": revealed,
        "empties": empties,
        "legal_count": len(legal),
        "legal": legal,
        "r2": geom["R2"],
        "r3": geom["R3"],
    }
    ok = (
        row["digest"] == FIRST_R2
        and fd == 39
        and revealed == 1
        and empties == 0
        and len(legal) == 1
        and legal[0]["action"] == [5, 1, 1]
        and [list(card) for card in legal[0]["packet"]] == [["s", 12]]
        and legal[0]["end_digest"] == FIRST_EMPTY_DIGEST
        and legal[0]["empties"] == 1
        and geom["R2"]
        and geom["R3"]
    )
    row["ok"] = ok
    return row


def _singleton_high_excluded(col, target: CampaignTarget, mode: str) -> bool:
    if len(col.face_up) != 1:
        return False
    card = col.face_up[0]
    if mode == "G0":
        return card.rank == target.high_rank
    if mode == "G1":
        return card.suit == target.suit and card.rank == target.high_rank
    raise ValueError(mode)


def create_reject_reason(
    state: SpiderState,
    target: CampaignTarget,
    action: tuple,
    mode: str = "G0",
    *,
    obl=None,
) -> str | None:
    """Return None if CREATE emits this action under ``mode``."""

    src, dst, k = action
    if obl is None:
        obl = empty_obligations()
    if _idle_empties(state):
        return "HAS_IDLE_EMPTY"
    if obl.workspace is not None:
        return "WORKSPACE_ALREADY_LIVE"
    col = state.columns[src]
    if col.face_down:
        return "SOURCE_HAS_FACE_DOWN"
    if not col.face_up:
        return "SOURCE_NO_FACE_UP"
    if _singleton_high_excluded(col, target, mode):
        return "EXCLUDED_SINGLETON_CAMPAIGN_HIGH"
    if _movable_run_length(state, src) != k or k != len(col.face_up):
        return "NOT_ONE_MOVABLE_RUN"
    if dst == src or not state.can_move(src, dst, k):
        return "NO_LEGAL_NONEMPTY_DEST"
    if state.columns[dst].is_empty():
        return "NO_LEGAL_NONEMPTY_DEST"
    if _breaks_join(state, action):
        return "BREAKS_STABLE_JOIN"
    if is_reserved_receiver_misuse(state, obl, action):
        return "RECEIVER_MISUSE_OR_OCCUPY"
    if _occupies_unique_receiver(state, target, action, obl):
        return "OCCUPIES_UNIQUE_RECEIVER"
    nxt, ok = _play(state, (action,))
    if not ok or not nxt.columns[src].is_empty():
        return "DOES_NOT_CREATE_EMPTY"
    if _edge_count(nxt, target) > _edge_count(state, target):
        return "WOULD_REALISE_EDGE"
    return None


def _remaining_create_predicates(
    state: SpiderState, obl, target: CampaignTarget, src: int, col
):
    k = len(col.face_up)
    if _movable_run_length(state, src) != k:
        return
    for dst in range(len(state.columns)):
        if dst == src or not state.can_move(src, dst, k):
            continue
        if state.columns[dst].is_empty():
            continue
        action = (src, dst, k)
        if _breaks_join(state, action):
            continue
        if is_reserved_receiver_misuse(state, obl, action):
            continue
        if _occupies_unique_receiver(state, target, action, obl):
            continue
        nxt, ok = _play(state, (action,))
        if not ok or not nxt.columns[src].is_empty():
            continue
        if _edge_count(nxt, target) > _edge_count(state, target):
            continue
        yield planner_mod.OperatorRealisation(
            OperatorKind.CREATE_WORKSPACE,
            (action,),
            nxt,
            obl,
        )


def _realise_create_g1(state: SpiderState, obl, target: CampaignTarget):
    """Production CREATE plus off-suit singleton same-rank sources."""

    yield from _ORIG_REALISE_CREATE(state, obl, target)
    if _idle_empties(state) or obl.workspace is not None:
        return
    for src, col in enumerate(state.columns):
        if col.face_down or not col.face_up:
            continue
        if not (len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank):
            continue
        if col.face_up[0].suit == target.suit:
            continue
        yield from _remaining_create_predicates(state, obl, target, src, col)


@contextmanager
def create_guard_mode(mode: str):
    if mode not in {"G0", "G1"}:
        raise ValueError(mode)
    planner_mod._realise_create = (
        _ORIG_REALISE_CREATE if mode == "G0" else _realise_create_g1
    )
    try:
        yield
    finally:
        planner_mod._realise_create = _ORIG_REALISE_CREATE


def production_create_restored() -> bool:
    return planner_mod._realise_create is _ORIG_REALISE_CREATE


def create_actions(state: SpiderState, target: CampaignTarget, mode: str) -> list:
    with create_guard_mode(mode):
        steps = list(planner_mod._realise_create(state, empty_obligations(), target))
    if not production_create_restored():
        raise RuntimeError("CREATE generator leaked")
    return [step.actions[0] for step in steps if step.actions]


def enumerate_ps(state: SpiderState) -> list[dict]:
    return _harvest().enumerate_ps(state)


def _plan_payload(state: SpiderState, target: CampaignTarget, plan, mode: str) -> dict:
    ops = [kind.value for kind in plan.operators]
    replay_ok = False
    end_digest = _digest(state)
    empties_trace = [sum(1 for col in state.columns if col.is_empty())]
    obl_trace = []
    unresolved = 0
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
    with create_guard_mode(mode):
        for kind, acts in plan.operator_trace:
            step = apply_operator(
                cur, target, kind, obligations=obl, candidate=acts[0] if acts else None
            )
            if step is None:
                obl_trace.append({"op": kind.value, "failed": True})
                break
            cur = step.state
            obl = step.obligations
            empties_trace.append(sum(1 for col in cur.columns if col.is_empty()))
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
            unresolved = obl.unresolved_count()
    success = plan.result in SUCCESS_RESULTS
    if success and plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS and not replay_ok:
        raise RuntimeError("false REALISED_CAMPAIGN_PROGRESS")
    if success and unresolved != 0:
        raise RuntimeError("obligation leakage on success")
    created_empty = max(empties_trace) > 0
    return {
        "result": plan.result.value,
        "operators": ops,
        "actions": [_action_json(a) for a in plan.actions],
        "cost": plan.cost,
        "visited": plan.visited,
        "replay_ok": replay_ok,
        "end_digest": end_digest,
        "edge_before": plan.edge_before,
        "edge_after": plan.edge_after,
        "unresolved": 0 if success else unresolved,
        "empties_trace": empties_trace,
        "obligation_trace": obl_trace,
        "FIRST_EMPTY_CREATED": OperatorKind.CREATE_WORKSPACE.value in ops and created_empty,
        "WORKSPACE_INVESTED": OperatorKind.INVEST_WORKSPACE.value in ops,
        "WORKSPACE_RECOVERED": OperatorKind.RECOVER_WORKSPACE.value in ops,
        "NONTRIVIAL_RESOURCE_SUCCESS": success and any(op in NONTRIVIAL_OPS for op in ops),
        "prepaid": plan.result is ResourcePlanResult.PREPAID_DEPENDENCY,
        "proof_pruning_allowed": plan.proof_pruning_allowed,
    }


def run_plan(state: SpiderState, target: CampaignTarget, mode: str) -> dict:
    before = canonical_state_key(state)
    started = time.perf_counter()
    with create_guard_mode(mode):
        plan = plan_resource_excavation(state, target)
    elapsed = time.perf_counter() - started
    if canonical_state_key(state) != before:
        raise RuntimeError("resource planner mutated source state")
    if not production_create_restored():
        raise RuntimeError("CREATE generator leaked after plan")
    if plan.proof_pruning_allowed:
        raise RuntimeError("proof_pruning_allowed must remain False")
    payload = _plan_payload(state, target, plan, mode)
    payload["elapsed_s"] = round(elapsed, 6)
    payload["mode"] = mode
    payload["create_actions"] = [_action_json(a) for a in create_actions(state, target, mode)]
    return payload


def classify_p_g1(g0: dict, g1: dict) -> str:
    g0_create = {tuple(a) if isinstance(a, list) else a for a in g0["create_actions"]}
    g1_create = {tuple(a) if isinstance(a, list) else a for a in g1["create_actions"]}
    new_create = g1_create - g0_create
    useful = g1["result"] in {
        ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS.value,
        ResourcePlanResult.PREPAID_DEPENDENCY.value,
    } and g1["NONTRIVIAL_RESOURCE_SUCCESS"]
    workspaceish = OperatorKind.CREATE_WORKSPACE.value in g1["operators"] and (
        g1["WORKSPACE_INVESTED"]
        or g1["WORKSPACE_RECOVERED"]
        or OperatorKind.PREPAY_DEPENDENCY.value in g1["operators"]
    )
    if useful and workspaceish and new_create:
        return "P_FULL_WORKSPACE_SUCCESS"
    if new_create and OperatorKind.CREATE_WORKSPACE.value in g1["operators"] and not useful:
        return "P_CREATE_ONLY"
    if new_create and g1["result"] == g0["result"] and g1["operators"] == g0["operators"]:
        return "P_NO_EFFECT"
    if new_create and not useful:
        return "P_CREATE_ONLY"
    return "P_NO_EFFECT"


def classify_delta(g0_create, g1_create, g0_plan, g1_plan) -> str:
    g0_set = {tuple(a) if isinstance(a, list) else a for a in g0_create}
    g1_set = {tuple(a) if isinstance(a, list) else a for a in g1_create}
    dropped = g0_set - g1_set
    added = g1_set - g0_set
    plan_changed = (
        g0_plan["result"] != g1_plan["result"]
        or g0_plan["operators"] != g1_plan["operators"]
        or g0_plan["end_digest"] != g1_plan["end_digest"]
        or g0_plan["actions"] != g1_plan["actions"]
    )
    if dropped:
        return "UNEXPECTED_DELTA"
    if not added and not plan_changed:
        return "UNCHANGED"
    if added and not dropped:
        return "EXPECTED_DELTA"
    if plan_changed and not added:
        return "UNEXPECTED_DELTA"
    return "EXPECTED_DELTA"


def synthetic_controls() -> dict:
    target = CampaignTarget("c", 12, 11)
    rows = {}

    c1 = _filled({0: [_card("c", 12)], 1: [_card("h", 13)]})
    rows["C1"] = _control_row("C1", c1, target, (0, 1, 1), "EXCLUDED_SINGLETON_CAMPAIGN_HIGH", "EXCLUDED_SINGLETON_CAMPAIGN_HIGH")

    c2 = _filled({0: [_card("s", 12)], 1: [_card("h", 13)], 2: [_card("c", 12), _card("d", 2)]})
    rows["C2"] = _control_row("C2", c2, target, (0, 1, 1), "EXCLUDED_SINGLETON_CAMPAIGN_HIGH", None)

    c3 = _filled({0: [_card("s", 5)], 1: [_card("h", 6)], 2: [_card("c", 12)]})
    g0_c3 = create_reject_reason(c3, target, (0, 1, 1), "G0")
    g1_c3 = create_reject_reason(c3, target, (0, 1, 1), "G1")
    rows["C3"] = {
        "name": "C3",
        "action": [0, 1, 1],
        "g0": g0_c3,
        "g1": g1_c3,
        "agree": g0_c3 == g1_c3,
        "create_g0": [_action_json(a) for a in create_actions(c3, target, "G0")],
        "create_g1": [_action_json(a) for a in create_actions(c3, target, "G1")],
    }

    join_state = _filled(
        {
            0: [_card("s", 12)],
            1: [_card("h", 8), _card("h", 7)],
            2: [_card("c", 12)],
        }
    )
    join_action = (1, 0, 1)
    rows["C4_JOIN"] = {
        "name": "C4_JOIN",
        "note": "partial packet off a hearts join; not a singleton-high source",
        "g0": create_reject_reason(join_state, target, join_action, "G0"),
        "g1": create_reject_reason(join_state, target, join_action, "G1"),
        "agree": create_reject_reason(join_state, target, join_action, "G0")
        == create_reject_reason(join_state, target, join_action, "G1"),
    }

    uniq = _filled({0: [_card("s", 11)], 1: [_card("c", 12)]})
    g0_u = create_reject_reason(uniq, target, (0, 1, 1), "G0")
    g1_u = create_reject_reason(uniq, target, (0, 1, 1), "G1")
    rows["C4_UNIQUE_RECEIVER"] = {
        "name": "C4_UNIQUE_RECEIVER",
        "action": [0, 1, 1],
        "g0": g0_u,
        "g1": g1_u,
        "agree": g0_u == g1_u == "OCCUPIES_UNIQUE_RECEIVER",
        "expected": "OCCUPIES_UNIQUE_RECEIVER",
        "note": "Js onto unique Qc; singleton-high guard does not apply (rank 11)",
    }

    reserved = _filled({0: [_card("h", 11)], 1: [_card("c", 12)]})
    obl = planner_mod.ObligationState(
        reservation=ReceiverReservation(1, "c", 12, "c", 11)
    )
    g0_r = create_reject_reason(reserved, target, (0, 1, 1), "G0", obl=obl)
    g1_r = create_reject_reason(reserved, target, (0, 1, 1), "G1", obl=obl)
    rows["C4_RESERVATION"] = {
        "name": "C4_RESERVATION",
        "g0": g0_r,
        "g1": g1_r,
        "agree": g0_r == g1_r == "RECEIVER_MISUSE_OR_OCCUPY",
        "expected": "RECEIVER_MISUSE_OR_OCCUPY",
    }

    mixed = _filled({0: [_card("s", 13), _card("h", 5)], 1: [_card("c", 12)]})
    rows["C4_NOT_ONE_RUN"] = {
        "name": "C4_NOT_ONE_RUN",
        "g0": create_reject_reason(mixed, target, (0, 1, 2), "G0"),
        "g1": create_reject_reason(mixed, target, (0, 1, 2), "G1"),
        "agree": create_reject_reason(mixed, target, (0, 1, 2), "G0")
        == create_reject_reason(mixed, target, (0, 1, 2), "G1"),
        "expected": "NOT_ONE_MOVABLE_RUN",
    }

    buried = _filled({0: [_card("s", 12)], 1: [_card("h", 13)]})
    buried.columns[0].face_down.append(_card("d", 4))
    rows["C4_FACE_DOWN"] = {
        "name": "C4_FACE_DOWN",
        "g0": create_reject_reason(buried, target, (0, 1, 1), "G0"),
        "g1": create_reject_reason(buried, target, (0, 1, 1), "G1"),
        "agree": create_reject_reason(buried, target, (0, 1, 1), "G0")
        == create_reject_reason(buried, target, (0, 1, 1), "G1"),
        "expected": "SOURCE_HAS_FACE_DOWN",
    }

    idle = _filled({0: [_card("s", 12)], 1: [_card("h", 13)]}, empty=(3,))
    rows["C4_IDLE_EMPTY"] = {
        "name": "C4_IDLE_EMPTY",
        "g0": create_reject_reason(idle, target, (0, 1, 1), "G0"),
        "g1": create_reject_reason(idle, target, (0, 1, 1), "G1"),
        "agree": create_reject_reason(idle, target, (0, 1, 1), "G0")
        == create_reject_reason(idle, target, (0, 1, 1), "G1"),
        "expected": "HAS_IDLE_EMPTY",
    }

    return rows


def _control_row(name, state, target, action, expect_g0, expect_g1) -> dict:
    g0 = create_reject_reason(state, target, action, "G0")
    g1 = create_reject_reason(state, target, action, "G1")
    emitted_g0 = create_actions(state, target, "G0")
    emitted_g1 = create_actions(state, target, "G1")
    return {
        "name": name,
        "action": list(action),
        "g0": g0,
        "g1": g1,
        "expect_g0": expect_g0,
        "expect_g1": expect_g1,
        "match": g0 == expect_g0 and g1 == expect_g1,
        "create_g0": [_action_json(a) for a in emitted_g0],
        "create_g1": [_action_json(a) for a in emitted_g1],
        "same_suit_high_emitted_g1": any(
            _is_same_suit_high_move(state, target, a) for a in emitted_g1
        ),
    }


def _is_same_suit_high_move(state: SpiderState, target: CampaignTarget, action) -> bool:
    src, _dst, k = action
    col = state.columns[src]
    if k != 1 or len(col.face_up) != 1:
        return False
    card = col.face_up[0]
    return card.suit == target.suit and card.rank == target.high_rank


def natural_create_compare(state: SpiderState, target: CampaignTarget, action) -> dict:
    g0 = create_reject_reason(state, target, action, "G0")
    g1 = create_reject_reason(state, target, action, "G1")
    nxt = state.clone()
    cost = replay_actions(nxt, [action])
    life = assess_tableau_move(state, action, discover_exit=False)
    return {
        "action": list(action),
        "g0": g0,
        "g1": g1,
        "g0_emits": g0 is None,
        "g1_emits": g1 is None,
        "end_digest": _digest(nxt),
        "empties": sum(1 for col in nxt.columns if col.is_empty()),
        "cost": int(cost),
        "joins_created": len(life.same_suit_joins_created),
        "joins_broken": len(life.same_suit_joins_broken),
        "replay_ok": nxt.columns[action[0]].is_empty(),
        "create_g0": [_action_json(a) for a in create_actions(state, target, "G0")],
        "create_g1": [_action_json(a) for a in create_actions(state, target, "G1")],
    }


def fixture_regression() -> list[dict]:
    from tests.test_resource_excavation_planner_v0_1 import p1_fixture, p2_fixture, p3_fixture
    from tests.test_resource_excavation_planner_v0_1_reservation import (
        reservation_positive_fixture,
        reservation_unthreatened_fixture,
    )
    from tests.test_resource_excavation_planner_v0_1_rework import rework_positive_fixture
    from tests.test_resource_excavation_planner_v0_1_workspace import (
        workspace_already_exposed_fixture,
        workspace_invest_fixture,
        workspace_no_recovery_fixture,
    )
    from tests.test_resource_excavation_planner_v0_1_workspace_invest import (
        invest_no_recovery_fixture,
        invest_positive_fixture,
        invest_unnecessary_fixture,
    )
    from tests.test_resource_excavation_planner_v0_2_w3 import w3_fixture

    cases = [
        ("W1", workspace_invest_fixture),
        ("W1_NO_RECOVERY", workspace_no_recovery_fixture),
        ("W1_ALREADY_EXPOSED", workspace_already_exposed_fixture),
        ("W2", invest_positive_fixture),
        ("W2_NO_RECOVERY", invest_no_recovery_fixture),
        ("W2_UNNECESSARY", invest_unnecessary_fixture),
        ("W3", w3_fixture),
        ("P1", p1_fixture),
        ("P2", p2_fixture),
        ("P3", p3_fixture),
        ("REWORK", rework_positive_fixture),
        ("RESERVATION", reservation_positive_fixture),
        ("RESERVATION_UNTHREATENED", reservation_unthreatened_fixture),
    ]
    rows = []
    for name, factory in cases:
        state, target = factory()
        g0 = run_plan(state, target, "G0")
        g1 = run_plan(state, target, "G1")
        label = classify_delta(g0["create_actions"], g1["create_actions"], g0, g1)
        rows.append(
            {
                "name": name,
                "target": {"suit": target.suit, "high": target.high_rank, "low": target.low_rank},
                "g0_result": g0["result"],
                "g1_result": g1["result"],
                "g0_ops": g0["operators"],
                "g1_ops": g1["operators"],
                "g0_create": g0["create_actions"],
                "g1_create": g1["create_actions"],
                "g0_end": g0["end_digest"],
                "g1_end": g1["end_digest"],
                "delta": label,
            }
        )
    return rows


def r2_matrix(opening: SpiderState) -> list[dict]:
    harvest = _harvest()
    rows = []
    for digest, path in R2_PATHS.items():
        state = reconstruct_r2(opening, digest)
        if _digest(state) != digest:
            raise RuntimeError(f"R2 digest mismatch {digest} != {_digest(state)}")
        geom = harvest._cc().geometry(state)
        legal = harvest.legal_first_empty_moves(state)
        for spec in enumerate_ps(state):
            target = CampaignTarget(spec["suit"], spec["high"], spec["low"])
            g0 = run_plan(state, target, "G0")
            g1 = run_plan(state, target, "G1")
            label = classify_delta(g0["create_actions"], g1["create_actions"], g0, g1)
            rows.append(
                {
                    "digest": digest,
                    "r3": geom["R3"],
                    "class": spec["class"],
                    "target": {"suit": spec["suit"], "high": spec["high"], "low": spec["low"]},
                    "legal_first_empty": len(legal),
                    "g0_create": g0["create_actions"],
                    "g1_create": g1["create_actions"],
                    "g0_result": g0["result"],
                    "g1_result": g1["result"],
                    "g0_ops": g0["operators"],
                    "g1_ops": g1["operators"],
                    "g0_end": g0["end_digest"],
                    "g1_end": g1["end_digest"],
                    "delta": label,
                }
            )
    return rows


def guard_hits_for_state(state: SpiderState, digest: str, source: str) -> list[dict]:
    rows = []
    targets = enumerate_ps(state)
    if not targets:
        return rows
    for spec in targets:
        target = CampaignTarget(spec["suit"], spec["high"], spec["low"])
        for src, col in enumerate(state.columns):
            if col.face_down or len(col.face_up) != 1:
                continue
            card = col.face_up[0]
            if card.rank != target.high_rank:
                continue
            same_suit = card.suit == target.suit
            k = len(col.face_up)
            dests = []
            other_pass = False
            g1_accept = False
            reasons = []
            for dst in range(10):
                action = (src, dst, k)
                g0 = create_reject_reason(state, target, action, "G0")
                g1 = create_reject_reason(state, target, action, "G1")
                if g0 == "EXCLUDED_SINGLETON_CAMPAIGN_HIGH":
                    dests.append(dst)
                    if g1 is None:
                        g1_accept = True
                        other_pass = True
                    elif g1 != "EXCLUDED_SINGLETON_CAMPAIGN_HIGH":
                        other_pass = g1 is None
                        reasons.append(g1)
            rows.append(
                {
                    "source": source,
                    "digest": digest,
                    "target": {"suit": spec["suit"], "high": spec["high"], "low": spec["low"]},
                    "class": spec["class"],
                    "src": src,
                    "card": [card.suit, card.rank],
                    "same_suit": same_suit,
                    "g1_would_accept": g1_accept,
                    "other_predicates_pass": other_pass or g1_accept,
                    "other_reject": reasons,
                }
            )
    return rows


def recapture_shadow_guard_hits() -> tuple[list[dict], dict]:
    shadow = _load(
        "natural_shadow_v0_1",
        ROOT / "research" / "resource_excavation_natural_shadow_v0_1.py",
    )
    result, collector = shadow._run_production(True)
    hits = []
    try:
        for digest, state in collector.states.items():
            hits.extend(guard_hits_for_state(state, digest, "natural_shadow_25"))
    finally:
        collector.restore()
    meta = {
        "expansions": result.strategic_expansions,
        "captured_states": len(collector.states),
        "stop_reason": result.stop_reason,
    }
    return hits, meta


def intent_evidence() -> dict:
    source = PLANNER.read_text(encoding="utf-8")
    create_src = inspect.getsource(planner_mod._realise_create)
    unique_src = inspect.getsource(planner_mod.unique_usable_receiver_column)
    occupy_src = inspect.getsource(planner_mod._occupies_unique_receiver)
    useful_src = inspect.getsource(planner_mod._useful_card)
    h2_markers = [
        "all suits of the high rank",
        "rank-class",
        "every suit copy",
        "suit-blind",
        "any queen",
    ]
    return {
        "create_guard_line": "if len(col.face_up) == 1 and col.face_up[0].rank == target.high_rank:",
        "create_has_comment": "campaign high" in create_src.lower() and "suit" in create_src.lower(),
        "create_source": create_src,
        "unique_receiver_is_suit_aware": "target.suit" in unique_src,
        "occupies_unique_is_suit_aware": "target.suit" in occupy_src,
        "useful_card_is_suit_aware": "card.suit == target.suit" in useful_src,
        "h2_literal_markers_in_planner": [m for m in h2_markers if m in source.lower()],
        "introduced_in": "a244206397691843beca91ff6f83b10bd606010c",
        "introduced_without_docstring": True,
        "hypothesis": "H1",
        "h2_supported": False,
        "rationale": (
            "The singleton exclusion is rank-only and uncommented. Every neighbouring "
            "campaign-high helper (unique receiver, occupy-unique, useful-card, edge-count, "
            "find-top) is suit-aware. No test or docstring states that every suit copy of "
            "target.high_rank is a protected rank-class resource."
        ),
    }


def decide(payload: dict) -> tuple[str, str]:
    if payload.get("hard_fail"):
        return "E", "Stop. Counterfactual unsound."
    p_g1_class = payload["p_g1_class"]
    c1_ok = payload["controls"]["C1"]["match"]
    c2_ok = payload["controls"]["C2"]["match"]
    unexpected = payload["unexpected_delta_count"]
    same_suit_consumed = payload["controls"]["C1"].get("same_suit_high_emitted_g1")
    s_equal = payload["s_equivalence"]["equal"]
    if not c1_ok or same_suit_consumed:
        return "E", "Stop. Counterfactual unsound."
    if unexpected:
        return "E", "Stop. Counterfactual unsound."
    g1_accepts_p = payload["natural_p_create"]["g1_emits"]
    if g1_accepts_p and p_g1_class == "P_FULL_WORKSPACE_SUCCESS" and c1_ok and c2_ok and s_equal:
        return (
            "A",
            "bounded production-quality CREATE singleton-high guard correction with regression shadow",
        )
    if g1_accepts_p and p_g1_class in {"P_CREATE_ONLY", "P_NO_EFFECT"}:
        if payload["p_g1"]["FIRST_EMPTY_CREATED"] and not payload["p_g1"]["NONTRIVIAL_RESOURCE_SUCCESS"]:
            return "B", "P post-CREATE continuation anatomy"
        return "C", "bounded scheduler target-selection experiment"
    if not g1_accepts_p:
        return "C", "bounded scheduler target-selection experiment"
    return "C", "bounded scheduler target-selection experiment"


def main() -> int:
    if "resource_excavation" in CONTROLLER.read_text(encoding="utf-8"):
        raise RuntimeError("controller mentions resource planner")
    if planner_mod._realise_create is not _ORIG_REALISE_CREATE:
        raise RuntimeError("CREATE generator already patched")

    cards = tuple(load_deal(DEAL_PATH))
    opening = SpiderState.from_cards(list(cards))
    r3 = reconstruct_first_r2(opening)
    r3_check = verify_natural_r3(r3)
    print("Phase 2 R3", r3_check["digest"], "ok", r3_check["ok"], flush=True)
    if not r3_check["ok"]:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps({"decision": "E", "r3": r3_check}, indent=2), encoding="utf-8")
        print("STOP: natural R3 reconstruction mismatch")
        return 2

    controls = synthetic_controls()
    print("Phase 4 controls", {k: (v.get("g0"), v.get("g1"), v.get("match", v.get("agree"))) for k, v in controls.items()}, flush=True)
    if not controls["C1"]["match"] or controls["C1"]["same_suit_high_emitted_g1"]:
        print("STOP: C1 same-suit high not protected")
        RESULT_PATH.write_text(json.dumps({"decision": "E", "controls": controls}, indent=2), encoding="utf-8")
        return 2

    p_create = natural_create_compare(r3, P_TARGET, (5, 1, 1))
    print("Phase 5 P CREATE", p_create["g0"], p_create["g1"], flush=True)

    p_g0 = run_plan(r3, P_TARGET, "G0")
    p_g1 = run_plan(r3, P_TARGET, "G1")
    p_class = classify_p_g1(p_g0, p_g1)
    print("Phase 6 P-G0", p_g0["result"], p_g0["operators"], flush=True)
    print("Phase 6 P-G1", p_g1["result"], p_g1["operators"], p_g1["end_digest"], p_class, flush=True)

    s_g0 = run_plan(r3, S_TARGET, "G0")
    s_g1 = run_plan(r3, S_TARGET, "G1")
    s_equal = (
        s_g0["result"] == s_g1["result"]
        and s_g0["operators"] == s_g1["operators"]
        and s_g0["actions"] == s_g1["actions"]
        and s_g0["end_digest"] == s_g1["end_digest"]
        and s_g0["end_digest"] == S_TERMINAL
        and s_g0["operators"]
        == [
            OperatorKind.CREATE_WORKSPACE.value,
            OperatorKind.INVEST_WORKSPACE.value,
            OperatorKind.RECOVER_WORKSPACE.value,
        ]
        and s_g0["actions"] == [[5, 1, 1], [9, 5, 1], [5, 6, 1]]
    )
    print("Phase 7 S equal", s_equal, s_g0["result"], s_g0["end_digest"], flush=True)

    matrix = r2_matrix(opening)
    fixtures = fixture_regression()
    print("Phase 8/9 matrix", len(matrix), "fixtures", len(fixtures), flush=True)

    harvest_hits = []
    for digest in R2_PATHS:
        harvest_hits.extend(guard_hits_for_state(reconstruct_r2(opening, digest), digest, "harvest_r2"))
    shadow_hits, shadow_meta = recapture_shadow_guard_hits()
    all_hits = harvest_hits + shadow_hits
    off_suit = [h for h in all_hits if not h["same_suit"]]
    same_suit = [h for h in all_hits if h["same_suit"]]
    g1_new = [h for h in off_suit if h["g1_would_accept"]]
    incidence = {
        "current_guard_hits": len(all_hits),
        "true_same_suit_campaign_high_hits": len(same_suit),
        "off_suit_same_rank_hits": len(off_suit),
        "off_suit_g1_new_create_candidates": len(g1_new),
        "harvest_hits": harvest_hits,
        "shadow_meta": shadow_meta,
        "shadow_hits": len(shadow_hits),
    }
    print("Phase 10 incidence", {k: incidence[k] for k in incidence if k != "harvest_hits"}, flush=True)

    unexpected = [row for row in matrix + fixtures if row["delta"] == "UNEXPECTED_DELTA"]
    expected = [row for row in matrix + fixtures if row["delta"] == "EXPECTED_DELTA"]

    payload = {
        "base_sha": "df7e858a3e749b0ff7e7393f2405d1835a140800",
        "intent": intent_evidence(),
        "r3": r3_check,
        "controls": controls,
        "natural_p_create": p_create,
        "p_g0": p_g0,
        "p_g1": p_g1,
        "p_g1_class": p_class,
        "s_g0": s_g0,
        "s_g1": s_g1,
        "s_equivalence": {
            "equal": s_equal,
            "g0_result": s_g0["result"],
            "g1_result": s_g1["result"],
            "g0_ops": s_g0["operators"],
            "g1_ops": s_g1["operators"],
            "g0_end": s_g0["end_digest"],
            "g1_end": s_g1["end_digest"],
        },
        "r2_matrix": matrix,
        "fixture_regression": fixtures,
        "guard_incidence": incidence,
        "expected_delta_count": len(expected),
        "unexpected_delta_count": len(unexpected),
        "unexpected_deltas": unexpected,
        "production_restored": production_create_restored(),
        "hard_fail": False,
    }
    decision, nxt = decide(payload)
    payload["decision"] = decision
    payload["recommended_next"] = nxt
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("decision", decision, nxt)
    print("wrote", RESULT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
