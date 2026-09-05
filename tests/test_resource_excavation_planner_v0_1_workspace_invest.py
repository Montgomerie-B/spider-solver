"""v0.1 standalone INVEST/RECOVER-positive gate.

Root already has an idle empty.  Recovery dest is created by REALISE, not
present at invest time.  PREPAY/CREATE/REWORK/RESERVE must not be required.
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    WorkspaceObligation,
    apply_operator,
    canonical_outstanding_obligations,
    empty_obligations,
    local_transposition_key,
    plan_resource_excavation,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "src" / "spider" / "planner" / "resource_excavation_planner.py"
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _filled(slots: dict[int, list[Card]]) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index)
        if cards is None:
            cols.append(Column([], [_card("shdc"[index % 4], 13)]))
        else:
            cols.append(Column([], list(cards)))
    return SpiderState(cols, [])


def _digest(state: SpiderState) -> str:
    return hashlib.sha256(repr(canonical_state_key(state)).encode()).hexdigest()[:16]


def invest_positive_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Idle empty + unique Qs receiver + Js under a mixed 10c blocker."""

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            1: [_card("s", 11), _card("c", 10)],
            3: [],
            7: [_card("s", 12)],
        }
    )
    return state, target


def invest_no_recovery_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Same campaign shape; blocker rank will not match post-REALISE dest."""

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            1: [_card("s", 11), _card("c", 9)],
            3: [],
            7: [_card("s", 12)],
        }
    )
    return state, target


def invest_unnecessary_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Campaign low already top; empty exists; investment is unnecessary."""

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            1: [_card("s", 11)],
            3: [],
            7: [_card("s", 12)],
        }
    )
    return state, target


def _join_present(state: SpiderState, suit: str, high: int, low: int) -> bool:
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank == high and b.rank == low:
                return True
    return False


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
        assert step.actions == acts
        cur = step.state
        obl = step.obligations
        yield kind, cur.clone(), obl


def test_root_idle_empty_and_blocker_only_to_empty():
    state, target = invest_positive_fixture()
    empties = [i for i, col in enumerate(state.columns) if col.is_empty()]
    assert empties == [3]
    stack = 1
    assert state.columns[stack].top().rank == 10
    assert state.columns[stack].face_up[0].rank == target.low_rank
    assert apply_operator(state, target, OperatorKind.REALISE_CAMPAIGN_EDGE) is None
    dests = [dst for dst in range(10) if dst != stack and state.can_move(stack, dst, 1)]
    assert dests == empties
    action = (stack, empties[0], 1)
    assert state.can_move(*action)
    life = assess_tableau_move(state, action, discover_exit=False)
    assert not life.same_suit_joins_broken


def test_invest_disabled_has_no_plan():
    state, target = invest_positive_fixture()
    blocked = plan_resource_excavation(
        state, target, disabled_operators=(OperatorKind.INVEST_WORKSPACE,)
    )
    assert blocked.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.PREPAY_DEPENDENCY not in blocked.operators
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in blocked.operators
    assert apply_operator(state, target, OperatorKind.PREPAY_DEPENDENCY) is None


def test_recover_disabled_has_no_plan():
    state, target = invest_positive_fixture()
    blocked = plan_resource_excavation(
        state, target, disabled_operators=(OperatorKind.RECOVER_WORKSPACE,)
    )
    assert blocked.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in blocked.operators or (
        blocked.result != ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    )
    assert blocked.result != ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert blocked.result != ResourcePlanResult.PREPAID_DEPENDENCY


def test_positive_invest_realise_recover_plan():
    state, target = invest_positive_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    kinds = list(plan.operators)
    assert kinds == [
        OperatorKind.INVEST_WORKSPACE,
        OperatorKind.REALISE_CAMPAIGN_EDGE,
        OperatorKind.RECOVER_WORKSPACE,
    ]
    assert OperatorKind.CREATE_WORKSPACE not in kinds
    assert OperatorKind.PREPAY_DEPENDENCY not in kinds
    assert OperatorKind.TEMPORARY_REWORK not in kinds
    assert OperatorKind.RESERVE_RECEIVER not in kinds
    end = state.clone()
    assert replay_actions(end, list(plan.actions)) == plan.cost
    assert _join_present(end, target.suit, target.high_rank, target.low_rank)
    assert end.columns[3].is_empty()


def test_invest_activates_workspace_obligation():
    state, target = invest_positive_fixture()
    plan = plan_resource_excavation(state, target)
    before = after = None
    obl_ws = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            after = cur
            obl_ws = obl.workspace
            break
        before = cur
    assert before is not None and after is not None
    assert obl_ws is not None
    assert isinstance(obl_ws, WorkspaceObligation)
    src, dst, k = next(
        acts[0]
        for kind, acts in plan.operator_trace
        if kind == OperatorKind.INVEST_WORKSPACE
    )
    assert before.columns[dst].is_empty()
    assert not after.columns[dst].is_empty()
    assert after.columns[src].top().suit == target.suit
    assert after.columns[src].top().rank == target.low_rank
    assert obl_ws.column == dst
    assert obl_ws.occupant_rank == before.columns[src].top().rank
    assert obl_ws.recovery_rank == target.low_rank
    assert obl.rework is None and obl.reservation is None
    assert sum(col.is_empty() for col in before.columns) == 1
    assert sum(col.is_empty() for col in after.columns) == 0
    assert _digest(before) != _digest(after)


def test_realise_keeps_workspace_obligation():
    state, target = invest_positive_fixture()
    plan = plan_resource_excavation(state, target)
    saw_invest = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            saw_invest = True
            assert obl.workspace is not None
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert saw_invest
            assert obl.workspace is not None
            assert obl.reservation is None
            assert obl.rework is None
            assert _join_present(cur, target.suit, target.high_rank, target.low_rank)
            top = cur.columns[7].top()
            assert top is not None and top.rank == target.low_rank
            assert plan.proof_pruning_allowed is False


def test_recover_restores_same_empty_and_clears_obligation():
    state, target = invest_positive_fixture()
    plan = plan_resource_excavation(state, target)
    invest_dst = next(
        acts[0][1]
        for kind, acts in plan.operator_trace
        if kind == OperatorKind.INVEST_WORKSPACE
    )
    recover_acts = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.RECOVER_WORKSPACE
    )
    assert recover_acts
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.RECOVER_WORKSPACE:
            assert obl.workspace is None
            assert obl.reservation is None
            assert obl.rework is None
            assert cur.columns[invest_dst].is_empty()
            assert _join_present(cur, target.suit, target.high_rank, target.low_rank)
            assert canonical_outstanding_obligations(cur, obl) == ()


def test_no_recovery_variant_cannot_succeed():
    state, target = invest_no_recovery_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert plan.result != ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.result != ResourcePlanResult.PREPAID_DEPENDENCY


def test_local_identity_for_workspace_obligation():
    state, target = invest_positive_fixture()
    plan = plan_resource_excavation(state, target)
    post = post_obl = recovered = recovered_obl = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            post, post_obl = cur, obl
        if kind == OperatorKind.RECOVER_WORKSPACE:
            recovered, recovered_obl = cur, obl
    assert post_obl.workspace is not None
    none = empty_obligations()
    key_none = local_transposition_key(post, none)
    key_ws = local_transposition_key(post, post_obl)
    assert key_none[0] == key_ws[0] == canonical_state_key(post)
    assert key_none != key_ws
    assert recovered_obl.workspace is None
    assert local_transposition_key(recovered, recovered_obl)[0] == canonical_state_key(
        recovered
    )
    assert recovered.columns[3].is_empty()


def test_no_gratuitous_invest_when_already_realisable():
    state, target = invest_unnecessary_fixture()
    assert any(col.is_empty() for col in state.columns)
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert OperatorKind.INVEST_WORKSPACE not in plan.operators
    assert OperatorKind.RECOVER_WORKSPACE not in plan.operators
    assert plan.operators == (OperatorKind.REALISE_CAMPAIGN_EDGE,)


def test_replay_and_proof_untouched():
    state, target = invest_positive_fixture()
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, target)
    assert canonical_state_key(state) == before
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert plan.replay_ok
    source = PLANNER.read_text(encoding="utf-8")
    assert "StrategicTranspositionTable" not in source
    assert "from spider.planner.anytime_controller" not in source
    assert "resource_excavation_planner" not in CONTROLLER.read_text(encoding="utf-8")
    assert "proof_pruning_allowed=True" not in inspect.getsource(
        plan_resource_excavation
    )
    assert "4925153" not in source
    for banned in ("invest_positive_fixture", "Qs", "Js", "10c"):
        assert banned not in source
