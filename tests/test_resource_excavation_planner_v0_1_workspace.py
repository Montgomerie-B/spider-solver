"""v0.1 workspace CASE W1: recovery dest exists at INVEST time.

Root has no idle empty. CREATE_WORKSPACE must manufacture one. The parked
blocker's recovery rank already has a tableau dest, so INVEST does not depend
on later REALISE. Distinct from CASE W2 (future-REALISE recovery).
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
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


def workspace_invest_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Campaign low under one mixed blocker that has no dest except empty.

    Recovery dest for the parked blocker exists and cannot occupy the
    campaign receiver.  Two mixed blockers are not present, so PREPAY
    cannot fire.  The overlay is not a same-suit join, so REWORK cannot.
    """

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            0: [_card("c", 2)],
            1: [_card("s", 11), _card("c", 9)],
            2: [_card("d", 3)],
            4: [_card("h", 10)],
            7: [_card("s", 12)],
        }
    )
    return state, target


def workspace_no_recovery_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Same shape without a bounded recovery dest for the invested occupant."""

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            0: [_card("c", 2)],
            1: [_card("s", 11), _card("c", 9)],
            2: [_card("d", 3)],
            7: [_card("s", 12)],
        }
    )
    return state, target


def workspace_already_exposed_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Campaign low already top: workspace investment is unnecessary."""

    target = CampaignTarget("s", 12, 11)
    state = _filled(
        {
            1: [_card("s", 11)],
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


def test_invest_is_necessary_when_disabled():
    state, target = workspace_invest_fixture()
    blocked = plan_resource_excavation(
        state, target, disabled_operators=(OperatorKind.INVEST_WORKSPACE,)
    )
    assert blocked.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.INVEST_WORKSPACE not in blocked.operators
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in blocked.operators
    assert OperatorKind.PREPAY_DEPENDENCY not in blocked.operators


def test_recover_is_necessary_when_disabled():
    state, target = workspace_invest_fixture()
    blocked = plan_resource_excavation(
        state, target, disabled_operators=(OperatorKind.RECOVER_WORKSPACE,)
    )
    assert blocked.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
        ResourcePlanResult.PREPAID_DEPENDENCY,
    )
    if blocked.result == ResourcePlanResult.PREPAID_DEPENDENCY:
        raise AssertionError("prepaid must not substitute for recovered workspace")
    assert OperatorKind.RECOVER_WORKSPACE not in blocked.operators
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in blocked.operators


def test_workspace_invest_plan_realises_and_recovers():
    state, target = workspace_invest_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    kinds = list(plan.operators)
    assert OperatorKind.CREATE_WORKSPACE in kinds
    assert OperatorKind.INVEST_WORKSPACE in kinds
    assert OperatorKind.RECOVER_WORKSPACE in kinds
    assert kinds.index(OperatorKind.CREATE_WORKSPACE) < kinds.index(
        OperatorKind.INVEST_WORKSPACE
    )
    assert kinds.index(OperatorKind.INVEST_WORKSPACE) < kinds.index(
        OperatorKind.RECOVER_WORKSPACE
    )
    assert OperatorKind.PREPAY_DEPENDENCY not in kinds
    assert OperatorKind.TEMPORARY_REWORK not in kinds
    assert OperatorKind.REALISE_CAMPAIGN_EDGE in kinds
    assert not any(col.is_empty() for col in state.columns)
    end = state.clone()
    paid = replay_actions(end, list(plan.actions))
    assert paid == plan.cost
    assert _join_present(end, target.suit, target.high_rank, target.low_rank)
    invest_dst = next(
        acts[0][1]
        for kind, acts in plan.operator_trace
        if kind == OperatorKind.INVEST_WORKSPACE
    )
    assert end.columns[invest_dst].is_empty()


def test_invest_records_bounded_recovery_obligation():
    state, target = workspace_invest_fixture()
    plan = plan_resource_excavation(state, target)
    before = None
    after = None
    obligation = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            after = cur
            obligation = obl.workspace
            break
        before = cur
    assert before is not None and after is not None
    assert obligation is not None
    assert isinstance(obligation, WorkspaceObligation)
    invest_acts = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.INVEST_WORKSPACE
    )
    assert len(invest_acts) == 1
    src, dst, k = invest_acts[0]
    assert before.columns[dst].is_empty()
    assert after.columns[dst].top() is not None
    assert not after.columns[src].is_empty()
    assert obligation.column == dst
    assert obligation.recovery_rank == after.columns[dst].top().rank + 1
    assert any(
        col.top() is not None and col.top().rank == obligation.recovery_rank
        for col in before.columns
    ), "W1 recovery dest must exist before INVEST"
    assert before.can_move(src, dst, k)
    assert _digest(before) != _digest(after)


def test_debt_lifecycle_invest_then_recover():
    state, target = workspace_invest_fixture()
    plan = plan_resource_excavation(state, target)
    saw_invest = False
    saw_realise_with_or_after_invest = False
    recovered = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind is None:
            assert obl.workspace is None
            continue
        if kind == OperatorKind.INVEST_WORKSPACE:
            saw_invest = True
            assert obl.workspace is not None
            assert obl.rework is None
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            saw_realise_with_or_after_invest = True
            assert saw_invest
        if kind == OperatorKind.RECOVER_WORKSPACE:
            assert obl.workspace is None
            recovered = True
            invest_dst = next(
                acts[0][1]
                for k, acts in plan.operator_trace
                if k == OperatorKind.INVEST_WORKSPACE
            )
            assert cur.columns[invest_dst].is_empty()
    assert saw_invest and saw_realise_with_or_after_invest and recovered
    recover_acts = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.RECOVER_WORKSPACE
    )
    assert recover_acts, "recover must physically restore workspace"


def test_no_recovery_destination_rejects_invest():
    state, target = workspace_no_recovery_fixture()
    created = apply_operator(state, target, OperatorKind.CREATE_WORKSPACE)
    probe = created.state if created is not None else state
    probe_obl = created.obligations if created is not None else empty_obligations()
    assert (
        apply_operator(
            probe, target, OperatorKind.INVEST_WORKSPACE, obligations=probe_obl
        )
        is None
    )
    plan = plan_resource_excavation(state, target)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.INVEST_WORKSPACE not in plan.operators


def test_local_identity_distinguishes_active_workspace_obligation():
    state, target = workspace_invest_fixture()
    plan = plan_resource_excavation(state, target)
    post = None
    post_obl = None
    recovered = None
    recovered_obl = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            post = cur
            post_obl = obl
        if kind == OperatorKind.RECOVER_WORKSPACE:
            recovered = cur
            recovered_obl = obl
    assert post is not None and post_obl is not None and post_obl.workspace is not None
    none = empty_obligations()
    key_none = local_transposition_key(post, none)
    key_ws = local_transposition_key(post, post_obl)
    assert canonical_state_key(post) == key_none[0] == key_ws[0]
    assert key_none != key_ws
    assert canonical_outstanding_obligations(post, none) == ()
    assert canonical_outstanding_obligations(post, post_obl) != ()
    assert recovered is not None
    assert recovered_obl.workspace is None
    assert canonical_outstanding_obligations(recovered, recovered_obl) == ()


def test_no_gratuitous_invest_when_source_already_exposed():
    state, target = workspace_already_exposed_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert OperatorKind.INVEST_WORKSPACE not in plan.operators
    assert OperatorKind.RECOVER_WORKSPACE not in plan.operators
    assert OperatorKind.CREATE_WORKSPACE not in plan.operators
    assert plan.operators == (OperatorKind.REALISE_CAMPAIGN_EDGE,)


def test_blocker_has_no_non_workspace_operator():
    state, target = workspace_invest_fixture()
    assert apply_operator(state, target, OperatorKind.PREPAY_DEPENDENCY) is None
    assert apply_operator(state, target, OperatorKind.TEMPORARY_REWORK) is None
    assert apply_operator(state, target, OperatorKind.REALISE_CAMPAIGN_EDGE) is None
    created = apply_operator(state, target, OperatorKind.CREATE_WORKSPACE)
    assert created is not None
    assert apply_operator(
        created.state, target, OperatorKind.PREPAY_DEPENDENCY, obligations=created.obligations
    ) is None
    invest = apply_operator(
        created.state, target, OperatorKind.INVEST_WORKSPACE, obligations=created.obligations
    )
    assert invest is not None
    assert invest.obligations.workspace is not None


def test_replay_and_proof_untouched():
    state, target = workspace_invest_fixture()
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, target)
    assert canonical_state_key(state) == before
    end = state.clone()
    assert replay_actions(end, list(plan.actions)) == plan.cost
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    source = PLANNER.read_text(encoding="utf-8")
    assert "StrategicTranspositionTable" not in source
    assert "from spider.planner.anytime_controller" not in source
    assert "resource_excavation_planner" not in CONTROLLER.read_text(encoding="utf-8")
    assert "proof_pruning_allowed=True" not in inspect.getsource(
        plan_resource_excavation
    )
    assert "4925153" not in source
    for banned in ("workspace_invest_fixture", "Qs", "Js", "9c"):
        assert banned not in source


def test_w1_differs_from_w2_future_realise_recovery():
    from tests.test_resource_excavation_planner_v0_1_workspace_invest import (
        invest_positive_fixture,
    )

    w1, t1 = workspace_invest_fixture()
    w2, t2 = invest_positive_fixture()
    assert canonical_state_key(w1) != canonical_state_key(w2)
    assert any(col.is_empty() for col in w2.columns)
    assert not any(col.is_empty() for col in w1.columns)


def test_fixture_layout_differs_from_prior_positives():
    from tests.test_resource_excavation_planner_v0_1 import p1_fixture, p2_fixture, p3_fixture
    from tests.test_resource_excavation_planner_v0_1_rework import rework_positive_fixture
    from tests.test_resource_excavation_planner_v0_1_reservation import (
        reservation_positive_fixture,
    )
    from tests.test_resource_excavation_planner_v0_1_workspace_invest import (
        invest_positive_fixture,
    )

    here, target = workspace_invest_fixture()
    keys = {
        canonical_state_key(here),
        canonical_state_key(p1_fixture()[0]),
        canonical_state_key(p2_fixture()[0]),
        canonical_state_key(p3_fixture()[0]),
        canonical_state_key(rework_positive_fixture()[0]),
        canonical_state_key(reservation_positive_fixture()[0]),
        canonical_state_key(invest_positive_fixture()[0]),
    }
    assert len(keys) == 7
    assert (target.suit, target.high_rank, target.low_rank) not in {
        (t.suit, t.high_rank, t.low_rank)
        for _s, t in (
            p1_fixture(),
            p2_fixture(),
            p3_fixture(),
            rework_positive_fixture(),
            reservation_positive_fixture(),
        )
    }
