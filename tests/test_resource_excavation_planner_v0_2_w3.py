"""Gate A — W3 multi-card workspace investment.

Campaign low sits under a same-suit movable run of length >= 2.  INVEST must
park that whole run on an idle empty.  The stored occupant is the run head;
the column top is a lower card.  Normalisation must not treat that mismatch
as repayment.
"""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import assess_tableau_move
from spider.planner.resource_excavation_planner import (
    CampaignTarget,
    OperatorKind,
    ResourcePlanResult,
    apply_operator,
    canonical_outstanding_obligations,
    empty_obligations,
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


def w3_fixture() -> tuple[SpiderState, CampaignTarget]:
    """8s receiver; 7s under a clubs 6-5 packet; idle empty at col 3."""

    target = CampaignTarget("s", 8, 7)
    state = _filled(
        {
            1: [_card("s", 7), _card("c", 6), _card("c", 5)],
            3: [],
            7: [_card("s", 8)],
        }
    )
    return state, target


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


def _join_present(state: SpiderState, suit: str, high: int, low: int) -> bool:
    for col in state.columns:
        up = col.face_up
        for a, b in zip(up, up[1:]):
            if a.suit == suit and b.suit == suit and a.rank == high and b.rank == low:
                return True
    return False


def test_w3_invest_moves_multi_card_run():
    state, target = w3_fixture()
    assert apply_operator(state, target, OperatorKind.REALISE_CAMPAIGN_EDGE) is None
    assert apply_operator(state, target, OperatorKind.PREPAY_DEPENDENCY) is None
    stack = 1
    empties = [i for i, col in enumerate(state.columns) if col.is_empty()]
    assert empties == [3]
    dests = [dst for dst in range(10) if dst != stack and state.can_move(stack, dst, 2)]
    assert dests == empties
    life = assess_tableau_move(state, (stack, empties[0], 2), discover_exit=False)
    assert not life.same_suit_joins_broken


def test_w3_normalize_must_not_clear_multicard_workspace():
    """Focused proof of the suspected top-vs-head defect.  Run on unmodified code first."""

    state, target = w3_fixture()
    invest = apply_operator(state, target, OperatorKind.INVEST_WORKSPACE)
    assert invest is not None
    src, dst, k = invest.actions[0]
    assert k >= 2
    ws = invest.obligations.workspace
    assert ws is not None
    col = invest.state.columns[ws.column]
    top = col.top()
    assert top is not None
    head = col.face_up[-k]
    assert (head.suit, head.rank) == (ws.occupant_suit, ws.occupant_rank)
    assert (top.suit, top.rank) != (ws.occupant_suit, ws.occupant_rank)
    assert not col.is_empty()
    normalised = normalize_obligations(invest.state, invest.obligations)
    assert normalised.workspace is not None, (
        "WorkspaceObligation must survive top != stored run-head while the "
        "borrowed column is still occupied"
    )
    assert canonical_outstanding_obligations(invest.state, invest.obligations)
    key_live = local_transposition_key(invest.state, invest.obligations)
    key_none = local_transposition_key(invest.state, empty_obligations())
    assert key_live[0] == key_none[0] == canonical_state_key(invest.state)
    assert key_live != key_none


def test_w3_plan_keeps_workspace_until_physical_recover():
    state, target = w3_fixture()
    plan = plan_resource_excavation(state, target)
    assert plan.result == ResourcePlanResult.REALISED_CAMPAIGN_PROGRESS
    kinds = list(plan.operators)
    assert OperatorKind.INVEST_WORKSPACE in kinds
    assert OperatorKind.RECOVER_WORKSPACE in kinds
    invest_acts = next(
        acts for kind, acts in plan.operator_trace if kind == OperatorKind.INVEST_WORKSPACE
    )
    assert invest_acts[0][2] >= 2
    invested_col = invest_acts[0][1]
    saw_realise_with_ws = False
    for kind, cur, obl in _walk(state, target, plan.operator_trace):
        if kind == OperatorKind.INVEST_WORKSPACE:
            assert obl.workspace is not None
            assert not cur.columns[invested_col].is_empty()
            assert normalize_obligations(cur, obl).workspace is not None
        if kind == OperatorKind.REALISE_CAMPAIGN_EDGE:
            assert obl.workspace is not None
            assert not cur.columns[invested_col].is_empty()
            saw_realise_with_ws = True
        if kind == OperatorKind.RECOVER_WORKSPACE:
            assert cur.columns[invested_col].is_empty()
            assert obl.workspace is None
    assert saw_realise_with_ws
    assert kinds.index(OperatorKind.INVEST_WORKSPACE) < kinds.index(
        OperatorKind.REALISE_CAMPAIGN_EDGE
    )
    assert kinds.index(OperatorKind.REALISE_CAMPAIGN_EDGE) < kinds.index(
        OperatorKind.RECOVER_WORKSPACE
    )
    end = state.clone()
    paid = replay_actions(end, list(plan.actions))
    assert paid == plan.cost
    assert plan.replay_ok
    assert end.columns[invested_col].is_empty()
    assert _join_present(end, target.suit, target.high_rank, target.low_rank)
    assert OperatorKind.PREPAY_DEPENDENCY not in kinds
    assert OperatorKind.TEMPORARY_REWORK not in kinds
    assert OperatorKind.RESERVE_RECEIVER not in kinds
