"""Production CREATE_WORKSPACE singleton-high guard is suit-and-rank.

The protected object is the actual campaign-high card, not every same-rank
singleton.  Tests call real ``_realise_create`` / ``plan_resource_excavation``
with no monkeypatch.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ObligationState,
    OperatorKind,
    ReceiverReservation,
    ResourcePlanResult,
    apply_operator,
    empty_obligations,
    plan_resource_excavation,
    _realise_create,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
DEAL = ROOT / "deals" / "4925153.txt"
COUNTERFACTUAL_JSON = (
    ROOT / "research" / "results" / "create_workspace_suit_aware_guard_counterfactual_v0_1.json"
)
FIRST_R2 = "1c3d3ec77bf164ad"
P_TERMINAL = "554c339c714d204c"
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
P_OPS = (
    OperatorKind.CREATE_WORKSPACE,
    OperatorKind.INVEST_WORKSPACE,
    OperatorKind.REALISE_CAMPAIGN_EDGE,
    OperatorKind.RECOVER_WORKSPACE,
)
P_ACTIONS = ((5, 1, 1), (9, 5, 1), (9, 4, 1), (5, 6, 1))
S_OPS = (
    OperatorKind.CREATE_WORKSPACE,
    OperatorKind.INVEST_WORKSPACE,
    OperatorKind.RECOVER_WORKSPACE,
)
S_ACTIONS = ((5, 1, 1), (9, 5, 1), (5, 6, 1))


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


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def _create_actions(state: SpiderState, target: CampaignTarget, *, obl=None) -> list:
    return [
        step.actions[0]
        for step in _realise_create(state, obl or empty_obligations(), target)
        if step.actions
    ]


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def reconstruct_r2(digest: str) -> SpiderState:
    state = _opening().clone()
    replay_actions(state, list(R2_PATHS[digest]))
    return state


def _walk(state: SpiderState, target: CampaignTarget, trace):
    cur = state.clone()
    obl = empty_obligations()
    yield None, cur.clone(), obl
    for kind, acts in trace:
        step = apply_operator(
            cur,
            target,
            kind,
            obligations=obl,
            candidate=acts[0] if acts else None,
        )
        assert step is not None, (kind, acts)
        cur = step.state
        obl = step.obligations
        yield kind, cur.clone(), obl


def test_c1_actual_campaign_high_remains_protected():
    state = _filled({0: [_card("c", 12)], 1: [_card("h", 13)]})
    emitted = _create_actions(state, P_TARGET)
    assert (0, 1, 1) not in emitted
    plan = plan_resource_excavation(state, P_TARGET)
    assert OperatorKind.CREATE_WORKSPACE not in plan.operators or (0, 1, 1) not in plan.actions


def test_c2_off_suit_same_rank_is_emitted():
    state = _filled(
        {0: [_card("s", 12)], 1: [_card("h", 13)], 2: [_card("c", 12), _card("d", 2)]}
    )
    emitted = _create_actions(state, P_TARGET)
    assert (0, 1, 1) in emitted


def test_c3_unrelated_rank_still_emitted():
    state = _filled({0: [_card("s", 5)], 1: [_card("h", 6)], 2: [_card("c", 12)]})
    emitted = _create_actions(state, P_TARGET)
    assert (0, 1, 1) in emitted


def test_c4_existing_safety_predicates_unchanged():
    buried = _filled({0: [_card("s", 12)], 1: [_card("h", 13)]})
    buried.columns[0].face_down.append(_card("d", 4))
    assert _create_actions(buried, P_TARGET) == []

    mixed = _filled({0: [_card("s", 13), _card("h", 5)], 1: [_card("c", 12)]})
    assert (0, 1, 2) not in _create_actions(mixed, P_TARGET)

    uniq = _filled({0: [_card("s", 11)], 1: [_card("c", 12)]})
    assert (0, 1, 1) not in _create_actions(uniq, P_TARGET)

    reserved = _filled({0: [_card("h", 11)], 1: [_card("c", 12)]})
    obl = ObligationState(reservation=ReceiverReservation(1, "c", 12, "c", 11))
    assert (0, 1, 1) not in _create_actions(reserved, P_TARGET, obl=obl)

    idle = _filled({0: [_card("s", 12)], 1: [_card("h", 13)]}, empty=(3,))
    assert _create_actions(idle, P_TARGET) == []


def test_natural_r3_reconstruction():
    state = reconstruct_r2(FIRST_R2)
    assert _digest(state) == FIRST_R2
    assert sum(len(col.face_down) for col in state.columns) == 39
    assert sum(1 for col in state.columns if col.is_empty()) == 0


def test_corrected_production_p_realises_workspace_lifecycle():
    state = reconstruct_r2(FIRST_R2)
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, P_TARGET)
    assert canonical_state_key(state) == before
    assert plan.result is ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.operators == P_OPS
    assert plan.actions == P_ACTIONS
    assert plan.cost == 4
    assert plan.edge_before == 0
    assert plan.edge_after == 1
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    end = state.clone()
    assert replay_actions(end, list(plan.actions)) == 4
    assert _digest(end) == P_TERMINAL
    assert sum(1 for col in end.columns if col.is_empty()) == 1
    unresolved = 0
    empties = []
    for kind, cur, obl in _walk(state, P_TARGET, plan.operator_trace):
        empties.append(sum(1 for col in cur.columns if col.is_empty()))
        if kind is None:
            assert obl.unresolved_count() == 0
            continue
        unresolved = obl.unresolved_count()
    assert unresolved == 0
    assert empties == [0, 1, 0, 0, 1]


def test_actual_qc_campaign_high_still_protected_hard_gate():
    state = _filled({0: [_card("c", 12)], 1: [_card("h", 13)]})
    assert (0, 1, 1) not in _create_actions(state, P_TARGET)
    qs = _filled({0: [_card("s", 12)], 1: [_card("h", 13)], 2: [_card("c", 12), _card("d", 2)]})
    assert (0, 1, 1) in _create_actions(qs, P_TARGET)


def test_established_s_invariance():
    state = reconstruct_r2(FIRST_R2)
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, S_TARGET)
    assert canonical_state_key(state) == before
    assert plan.result is ResourcePlanResult.PREPAID_DEPENDENCY
    assert plan.operators == S_OPS
    assert plan.actions == S_ACTIONS
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert _digest(end) == S_TERMINAL
    assert plan.replay_ok
    last_obl = None
    for _kind, _cur, obl in _walk(state, S_TARGET, plan.operator_trace):
        last_obl = obl
    assert last_obl is not None
    assert last_obl.unresolved_count() == 0


def test_sixty_nine_pair_r2_ps_matches_g1_and_one_g0_delta():
    payload = json.loads(COUNTERFACTUAL_JSON.read_text(encoding="utf-8"))
    matrix = payload["r2_matrix"]
    assert len(matrix) == 69
    states = {digest: reconstruct_r2(digest) for digest in R2_PATHS}
    g0_deltas = []
    g1_mismatches = []
    for row in matrix:
        state = states[row["digest"]]
        target = CampaignTarget(row["target"]["suit"], row["target"]["high"], row["target"]["low"])
        before = canonical_state_key(state)
        plan = plan_resource_excavation(state, target)
        assert canonical_state_key(state) == before
        got = {
            "result": plan.result.value,
            "ops": [kind.value for kind in plan.operators],
            "end": _digest(state) if not plan.actions else _digest(_replay_end(state, plan.actions)),
        }
        g0_changed = got["result"] != row["g0_result"] or got["ops"] != row["g0_ops"]
        g1_match = got["result"] == row["g1_result"] and got["ops"] == row["g1_ops"]
        if g0_changed:
            g0_deltas.append(
                {
                    "digest": row["digest"],
                    "class": row["class"],
                    "target": row["target"],
                    "g0": row["g0_result"],
                    "got": got["result"],
                    "g0_ops": row["g0_ops"],
                    "got_ops": got["ops"],
                }
            )
        if not g1_match:
            g1_mismatches.append((row, got))
    assert g1_mismatches == []
    assert len(g0_deltas) == 1
    delta = g0_deltas[0]
    assert delta["digest"] == FIRST_R2
    assert delta["class"] == "P"
    assert delta["target"] == {"suit": "c", "high": 12, "low": 11}
    assert delta["g0"] == "NO_BOUNDED_PLAN"
    assert delta["got"] == "REALISED_CAMPAIGN_PROGRESS"


def _replay_end(state: SpiderState, actions) -> SpiderState:
    end = state.clone()
    replay_actions(end, list(actions))
    return end


def test_production_isolation_and_no_deal_special_case():
    controller = CONTROLLER.read_text(encoding="utf-8")
    planner = PLANNER.read_text(encoding="utf-8")
    assert "resource_excavation" not in controller
    create_src = planner.split("def _realise_create")[1].split("def _realise_invest")[0]
    assert "col.face_up[0].suit == target.suit" in create_src
    assert "col.face_up[0].rank == target.high_rank" in create_src
    assert "4925153" not in planner
    assert "1c3d3ec77bf164ad" not in planner
    assert "554c339c714d204c" not in planner
