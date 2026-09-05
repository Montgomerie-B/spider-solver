"""v0.2 obligation integrity: duplicate rework, duplicate receiver, invariants."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ObligationState,
    OperatorKind,
    ReceiverReservation,
    ResourcePlanResult,
    ReworkDebt,
    WorkspaceObligation,
    apply_operator,
    canonical_outstanding_obligations,
    empty_obligations,
    is_reserved_receiver_misuse,
    local_transposition_key,
    normalize_obligations,
    plan_resource_excavation,
)
from spider.state_identity import canonical_state_key


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


def _join_count(state: SpiderState, suit: str, high: int, low: int) -> int:
    n = 0
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank == high and b.rank == low:
                n += 1
    return n


def duplicate_rework_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Two 10c-9c joins; campaign Jc-10c needs one 10c exposed."""

    target = CampaignTarget("c", 11, 10)
    state = _filled(
        {
            2: [_card("h", 10)],
            5: [_card("c", 11)],
            6: [_card("c", 10), _card("c", 9)],
            8: [_card("c", 10), _card("c", 9)],
        }
    )
    return state, target


def duplicate_receiver_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Two 9h tops; only one is threatened and reserved."""

    target = CampaignTarget("h", 9, 8)
    state = _filled(
        {
            0: [_card("d", 6)],
            1: [_card("h", 9)],
            2: [_card("c", 7)],
            3: [_card("c", 8)],
            4: [_card("c", 4)],
            5: [_card("h", 9)],
            6: [_card("h", 8), _card("s", 3), _card("d", 2)],
        }
    )
    return state, target


def test_duplicate_join_does_not_self_repay_rework_debt():
    state, target = duplicate_rework_fixture()
    assert _join_count(state, "c", 10, 9) == 2
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert OperatorKind.TEMPORARY_REWORK in plan.operators
    assert OperatorKind.REPAY_REWORK in plan.operators
    saw_debt_with_sibling = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.TEMPORARY_REWORK:
            assert obl.rework is not None
            assert _join_count(cur, "c", 10, 9) == 1
            assert normalize_obligations(cur, obl).rework is not None
            saw_debt_with_sibling = True
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert obl.rework is not None
        if kind == OperatorKind.REPAY_REWORK:
            assert obl.rework is None
            assert _join_count(cur, "c", 10, 9) == 2
    assert saw_debt_with_sibling
    end = state.clone()
    assert replay_actions(end, list(plan.actions)) == plan.cost


def test_duplicate_receiver_is_column_anchored():
    state, target = duplicate_receiver_fixture()
    nines = [
        i
        for i, col in enumerate(state.columns)
        if col.top() is not None and col.top().suit == "h" and col.top().rank == 9
    ]
    assert len(nines) == 2
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert OperatorKind.RESERVE_RECEIVER in plan.operators
    reserved_col = None
    other_col = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.RESERVE_RECEIVER:
            assert obl.reservation is not None
            reserved_col = obl.reservation.column
            other_col = next(i for i in nines if i != reserved_col)
            thief = (3, reserved_col, 1)
            assert state.can_move(*thief)
            assert is_reserved_receiver_misuse(state, obl, thief)
            assert other_col is not None
            other_top = cur.columns[other_col].top()
            assert other_top is not None and other_top.suit == "h" and other_top.rank == 9
            still = normalize_obligations(cur, obl)
            assert still.reservation is not None
            assert still.reservation.column == reserved_col
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            acts = next(
                a for k, a in plan.operator_trace if k == OperatorKind.REALISE_CAMPAIGN_EDGE
            )
            assert acts[0][1] == reserved_col
            assert obl.reservation is None
    assert reserved_col is not None
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert plan.replay_ok


def test_normalize_is_idempotent_for_all_debt_kinds():
    from tests.test_resource_excavation_planner_v0_2_w3 import w3_fixture

    cases = []
    w3, t3 = w3_fixture()
    inv = apply_operator(w3, t3, OperatorKind.INVEST_WORKSPACE)
    assert inv is not None and inv.obligations.workspace is not None
    cases.append((inv.state, inv.obligations))

    rw, tr = duplicate_rework_fixture()
    brk = apply_operator(rw, tr, OperatorKind.TEMPORARY_REWORK)
    assert brk is not None and brk.obligations.rework is not None
    cases.append((brk.state, brk.obligations))

    rec, tc = duplicate_receiver_fixture()
    rsv = apply_operator(rec, tc, OperatorKind.RESERVE_RECEIVER)
    assert rsv is not None and rsv.obligations.reservation is not None
    cases.append((rsv.state, rsv.obligations))

    for st, obl in cases:
        n1 = normalize_obligations(st, obl)
        n2 = normalize_obligations(st, n1)
        assert n1 == n2
        assert n1.unresolved_count() >= 1
        key_a = local_transposition_key(st, n1)
        key_b = local_transposition_key(st, n2)
        assert key_a == key_b
        assert key_a != local_transposition_key(st, empty_obligations())


def test_realised_success_never_leaks_obligations():
    from tests.test_resource_excavation_planner_v0_2_w3 import w3_fixture
    from tests.test_resource_excavation_planner_v0_1_workspace_invest import (
        invest_positive_fixture,
    )
    from tests.test_resource_excavation_planner_v0_1_rework import rework_positive_fixture
    from tests.test_resource_excavation_planner_v0_1_reservation import (
        reservation_positive_fixture,
    )

    for factory in (
        w3_fixture,
        invest_positive_fixture,
        rework_positive_fixture,
        reservation_positive_fixture,
        duplicate_rework_fixture,
        duplicate_receiver_fixture,
    ):
        state, target = factory()
        plan = plan_resource_excavation(state, target)
        if plan.result != ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS:
            continue
        end = state.clone()
        replay_actions(end, list(plan.actions))
        final = None
        for kind, cur, obl in _walk(state, target, plan.operator_trace):
            final = obl
            if kind == OperatorKind.REALISE_CAMPAIGN_EDGE and obl.unresolved_count() == 0:
                # realise may still carry workspace/rework; only the returned
                # success node must be clean, checked after the walk.
                pass
        assert final is not None
        assert final.unresolved_count() == 0
        assert canonical_outstanding_obligations(end, final) == ()


def test_workspace_debt_survives_missing_recovery_route():
    from tests.test_resource_excavation_planner_v0_2_w3 import w3_fixture

    state, target = w3_fixture()
    invest = apply_operator(state, target, OperatorKind.INVEST_WORKSPACE)
    assert invest is not None
    obl = invest.obligations
    assert obl.workspace is not None
    parked = obl.workspace.column
    # No rank dest for the parked packet except covering the still-unrealised
    # campaign low, which recover refuses.  Debt must remain.
    assert normalize_obligations(invest.state, obl).workspace is not None
    assert not invest.state.columns[parked].is_empty()
    recover = apply_operator(
        invest.state, target, OperatorKind.RECOVER_WORKSPACE, obligations=obl
    )
    assert recover is None
    assert canonical_outstanding_obligations(invest.state, obl)
