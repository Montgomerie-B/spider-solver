"""v0.1 rework-positive gate.

One synthetic fixture where dest-before-break is necessary.
Planner code must not grow fixture constants; layout lives here only.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    ObligationState,
    OperatorKind,
    ResourcePlanResult,
    ReworkDebt,
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


def rework_positive_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Campaign low is buried under a same-suit join; dest for the child exists.

    Layout is disjoint from P1/P2/P3 (clubs jack-ten, columns 5/8/2).
    """

    target = CampaignTarget("c", 11, 10)
    state = _filled(
        {
            5: [_card("c", 11)],
            8: [_card("c", 10), _card("c", 9)],
            2: [_card("h", 10)],
        }
    )
    return state, target


def rework_without_dest_fixture() -> tuple[SpiderState, CampaignTarget]:
    """Same shape with the rework destination removed."""

    target = CampaignTarget("c", 11, 10)
    state = _filled(
        {
            5: [_card("c", 11)],
            8: [_card("c", 10), _card("c", 9)],
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


def test_rework_is_necessary_when_disabled():
    state, target = rework_positive_fixture()
    blocked = plan_resource_excavation(
        state, target, disabled_operators=(OperatorKind.TEMPORARY_REWORK,)
    )
    assert blocked.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.TEMPORARY_REWORK not in blocked.operators
    assert OperatorKind.REALISE_CAMPAIGN_EDGE not in blocked.operators


def test_rework_positive_plan_realises_and_repays():
    state, target = rework_positive_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    kinds = plan.operators
    assert OperatorKind.TEMPORARY_REWORK in kinds
    assert OperatorKind.REPAY_REWORK in kinds
    assert kinds.index(OperatorKind.TEMPORARY_REWORK) < kinds.index(
        OperatorKind.REPAY_REWORK
    )
    assert OperatorKind.REALISE_CAMPAIGN_EDGE in kinds
    end = state.clone()
    paid = replay_actions(end, list(plan.actions))
    assert paid == plan.cost
    assert _join_present(end, target.suit, target.high_rank, target.low_rank)
    assert _join_present(end, "c", 10, 9)


def test_dest_exists_before_break_and_one_debt():
    state, target = rework_positive_fixture()
    plan = plan_resource_excavation(state, target)
    before_break = None
    after_break = None
    debt = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.TEMPORARY_REWORK:
            after_break = cur
            debt = obl.rework
            break
        before_break = cur
    assert before_break is not None and after_break is not None
    assert _join_present(before_break, "c", 10, 9)
    assert not _join_present(after_break, "c", 10, 9)
    rework_actions = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.TEMPORARY_REWORK
    )
    assert len(rework_actions) == 1
    src, dst, k = rework_actions[0]
    assert before_break.can_move(src, dst, k)
    dest_top = before_break.columns[dst].top()
    assert dest_top is not None or before_break.columns[dst].is_empty()
    assert dest_top is not None
    assert debt is not None
    assert isinstance(debt, ReworkDebt)
    assert (debt.suit, debt.high_rank, debt.low_rank) == ("c", 10, 9)
    assert debt.origin_column == src
    assert debt.parked_column == dst
    assert after_break.columns[dst].top() is not None
    # Exactly one debt, no second.
    assert obl_count_rework(plan, state, target) == 1
    assert plan.proof_pruning_allowed is False
    pre_hash = canonical_state_key(before_break)
    post_hash = canonical_state_key(after_break)
    assert pre_hash != post_hash
    # hashes recorded for the gate report
    assert hash(pre_hash) != hash(post_hash)


def obl_count_rework(plan, start, target) -> int:
    seen = []
    for kind, _cur, obl in _walk(start, target, plan.operator_trace):
        if obl.rework is not None:
            seen.append(obl.rework)
    return len({seen[0], *seen}) if seen else 0


def test_debt_lifecycle_requires_explicit_repay():
    state, target = rework_positive_fixture()
    plan = plan_resource_excavation(state, target)
    saw_rework = False
    saw_realise_with_debt = False
    repaid = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind is None:
            assert obl.rework is None
            continue
        if kind == OperatorKind.TEMPORARY_REWORK:
            saw_rework = True
            assert obl.rework is not None
            assert (obl.rework.suit, obl.rework.high_rank, obl.rework.low_rank) == (
                "c",
                10,
                9,
            )
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert saw_rework
            assert obl.rework is not None
            saw_realise_with_debt = True
        if kind == OperatorKind.REPAY_REWORK:
            assert obl.rework is None
            repaid = True
            assert _join_present(cur, "c", 10, 9)
            assert _join_present(cur, target.suit, target.high_rank, target.low_rank)
    assert saw_rework and saw_realise_with_debt and repaid
    repay_acts = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.REPAY_REWORK
    )
    assert repay_acts, "repay must be a physical repair, not a silent no-op"


def test_remove_destination_blocks_rework():
    state, target = rework_without_dest_fixture()
    assert apply_operator(state, target, OperatorKind.TEMPORARY_REWORK) is None
    plan = plan_resource_excavation(state, target)
    assert plan.result in (
        ResourcePlanResult.NO_BOUNDED_PLAN,
        ResourcePlanResult.RESOURCE_DEADLOCK,
    )
    assert OperatorKind.TEMPORARY_REWORK not in plan.operators
    for _kind, _cur, obl in _walk(state, target, plan.operator_trace):
        assert obl.rework is None


def test_local_identity_distinguishes_active_rework_debt():
    state, target = rework_positive_fixture()
    plan = plan_resource_excavation(state, target)
    pre = None
    post = None
    post_obl = None
    repaid_state = None
    repaid_obl = None
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.TEMPORARY_REWORK:
            post = cur
            post_obl = obl
            break
        pre = cur
    assert post is not None and post_obl is not None and post_obl.rework is not None
    none = empty_obligations()
    key_none = local_transposition_key(post, none)
    key_debt = local_transposition_key(post, post_obl)
    assert canonical_state_key(post) == key_none[0] == key_debt[0]
    assert key_none != key_debt
    assert canonical_outstanding_obligations(post, none) == ()
    assert canonical_outstanding_obligations(post, post_obl) != ()
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.REPAY_REWORK:
            repaid_state = cur
            repaid_obl = obl
    assert repaid_state is not None
    assert repaid_obl.rework is None
    assert canonical_outstanding_obligations(repaid_state, repaid_obl) == ()
    assert local_transposition_key(repaid_state, repaid_obl)[0] == canonical_state_key(
        repaid_state
    )


def test_replay_exact_and_proof_untouched():
    state, target = rework_positive_fixture()
    before = canonical_state_key(state)
    plan = plan_resource_excavation(state, target)
    assert canonical_state_key(state) == before
    end = state.clone()
    replay_actions(end, list(plan.actions))
    assert plan.replay_ok
    assert plan.proof_pruning_allowed is False
    source = PLANNER.read_text(encoding="utf-8")
    assert "StrategicTranspositionTable" not in source
    assert "from spider.planner.anytime_controller" not in source
    assert "resource_excavation_planner" not in CONTROLLER.read_text(encoding="utf-8")
    assert "proof_pruning_allowed=True" not in inspect.getsource(
        plan_resource_excavation
    )


def test_planner_has_no_rework_fixture_constants():
    source = PLANNER.read_text(encoding="utf-8")
    assert "4925153" not in source
    for banned in ("rework_positive_fixture", "Jc", "Tc", "9c", "10h"):
        assert banned not in source


def test_fixture_layout_differs_from_p1_p2_p3():
    from tests.test_resource_excavation_planner_v0_1 import (
        p1_fixture,
        p2_fixture,
        p3_fixture,
    )

    rework_state, rework_target = rework_positive_fixture()
    keys = {
        canonical_state_key(rework_state),
        canonical_state_key(p1_fixture()[0]),
        canonical_state_key(p2_fixture()[0]),
        canonical_state_key(p3_fixture()[0]),
    }
    assert len(keys) == 4
    assert (rework_target.suit, rework_target.high_rank, rework_target.low_rank) not in {
        (t.suit, t.high_rank, t.low_rank)
        for _s, t in (p1_fixture(), p2_fixture(), p3_fixture())
    }
