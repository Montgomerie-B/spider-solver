"""v0.110 prerequisite realisation and stock-reception tests.

Real 4925153 checkpoints are replayed only to reach a state. The controller
does not receive the reference suffix. Synthetic boards cover reception
cases the real prefixes do not isolate.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    load_portfolio,
    locate_source,
    measured_stock_connection,
    plan_obstructed_access,
    plan_receiver_alignment,
    propose_foundation_step,
    revise_operational_epoch,
)
from spider.human_strategy.preparation import compare_exact_reception, queen_run_lands_on, strategic_stop_status
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.stock_reception import PreDealShapingObjective, next_stock_row, run_bounded_shaping_probe
from spider.research_actions import all_legal_actions, apply_action, face_down_count

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


def _profile(**kwargs):
    base = dict(
        time_limit_s=20,
        max_steps=6,
        tactical_nodes=400,
        tactical_time_s=0.8,
        tactical_max_cost=4,
        consult_portfolio=False,
        strategic_width=2,
        max_width=3,
        rss_abort_mb=8192,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _cards():
    return load_deal(DEAL)


def _prefix(n: int):
    cards = _cards()
    actions = parse_moves_file(CANONICAL)
    state = SpiderState.from_cards(list(cards))
    g = replay_actions(state, list(actions[:n]))
    return cards, state, g


def _queen_on_column_two(state):
    column = state.columns[1]
    for index, card in enumerate(column.face_up):
        if card.suit == "s" and card.rank == 12:
            return card, index
    return None, None


def _movable_as_head(state, column, index):
    run = len(state.columns[column].face_up) - index
    return any(state.can_move(column, dst, run) for dst in range(10) if dst != column)


def _board(columns, row):
    cols = list(columns)
    while len(cols) < 10:
        cols.append(Column([], [Card("c", 13)]))
    return SpiderState(cols, list(row))


def test_early_queen_is_face_up_but_not_movable():
    cards, state, g = _prefix(31)
    card, index = _queen_on_column_two(state)
    assert card is not None
    assert index is not None
    above = [str(item) for item in state.columns[1].face_up[index + 1 :]]
    assert above == ["Jd", "10d"]
    assert _movable_as_head(state, 1, index) is False
    proposal = propose_foundation_step(state, cards, _profile(), 8.0, g, cache={}, lock={})
    record = proposal.public["campaign_record"]
    text = " ".join(proposal.events)
    assert "does not make S#1 impossible" in text
    assert record["operational_epoch"] == record["original_epoch"] == 2
    assert record["epoch_changes"] == []
    assert proposal.candidate is not None
    assert proposal.candidate.actions[0] != ("deal",)
    assert proposal.candidate.kind == "ACCESS"
    assert "does not move the operational epoch" in text
    assert "one stock row is tried" not in text
    assert "one more stock row" not in text
    evidence = " ".join(proposal.candidate.evidence)
    assert "Jd" in evidence and "10d" in evidence
    _feasibility, portfolio = load_portfolio(state, cards, {})
    campaign = next(item for item in portfolio.campaigns if item.label == "S#1")
    located = locate_source(state, "tableau:1:up:1")
    assert located is not None
    plan = plan_obstructed_access(
        state,
        located[0],
        (),
        source_key="tableau:1:up:1",
        column=1,
    )
    assert plan is not None
    assert len(plan.actions) >= 2
    assert plan.depth_before > plan.depth_after
    assert plan.actions[0] == proposal.candidate.actions[0]
    trial = state.clone()
    cost = 0
    for action in plan.actions:
        assert trial.can_move(*action)
        cost += apply_action(trial, action)
    assert cost == plan.cost
    assert _cover(trial, located[0]) == 0
    assert _longest_spade_run(trial) >= 6
    del campaign


def test_close_checkpoint_still_deals_then_removes_spades():
    cards, state, g = _prefix(82)
    row = next_stock_row(state)
    assert row is not None and str(row[0]) == "Ks"
    result = solve(
        state,
        _profile(max_steps=4, time_limit_s=15),
        mode="diagnose",
        opening_g=g,
        goal="first-foundation",
        deal_cards=cards,
        provenance_note="diagnostic canonical prefix 82; suffix not injected",
    )
    assert result.actions[0] == ("deal",)
    assert result.actions[1] == (1, 0, 12)
    assert result.decisions[0].chosen_id == "DEAL:S#1"
    assert result.decisions[0].reason == "selected: foundation plan deals after its prerequisites"
    assert result.status == "FOUNDATION_REACHED"
    assert result.solved is False
    assert result.foundations == 1
    assert result.provenance["partial_trajectory"] is True
    assert result.provenance["prefix_injected"] is False
    assert result.cumulative_g == g + result.suffix_mw
    assert result.replay["ok"] is True
    assert result.replay["mobilityware_moves"] == result.suffix_mw
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    assert queen_run_lands_on(dealt, 0, "s") is True
    assert len(dealt.foundations) == len(state.foundations)


def test_receiver_alignment_places_a_legal_parent_and_rejects_a_trapped_one():
    row = [Card("s", 5)] + [Card("d", 3)] * 9
    ready = _board(
        [Column([], [Card("h", 7)]), Column([], [Card("s", 6)])],
        row,
    )
    objective = PreDealShapingObjective(
        code="same_suit_receiver",
        description="put 6s on column 1",
        target_column=0,
        incoming=row[0],
        predicate_key="same_suit_receiver",
        max_cost=3,
    )
    found = run_bounded_shaping_probe(ready, objective, max_cost=3, max_expand=200)
    assert found.found is True
    assert found.path
    compared = compare_exact_reception(ready, found.path, 0, "s")
    assert compared.choice == "prepare"
    assert compared.immediate_connects is False
    assert compared.prepared_connects is True
    assert compared.preparation_cost == compared.deal_only_cost + sum(1 for _ in found.path)
    trial = ready.clone()
    paid = 0
    for action in found.path:
        paid += apply_action(trial, action)
    paid += apply_action(trial, ("deal",))
    assert paid == compared.preparation_cost
    landed = trial.columns[0].face_up[-2:]
    assert [str(card) for card in landed] == ["6s", "5s"]

    trapped = _board(
        [Column([], [Card("h", 7)]), Column([], [Card("s", 6), Card("c", 13)])],
        row,
    )
    missed = run_bounded_shaping_probe(trapped, objective, max_cost=3, max_expand=200)
    assert missed.found is False
    assert missed.status == "not_found_within_bound"
    rejected = compare_exact_reception(trapped, ((1, 0, 2),), 0, "s")
    assert rejected.choice == "reject"
    assert "not legal" in " ".join(rejected.evidence)


def test_incoming_king_still_deals_when_the_locked_horizon_is_the_next_row():
    cards, state, g = _prefix(82)
    lock = {}
    proposal = propose_foundation_step(state, cards, _profile(), 8.0, g, cache={}, lock=lock)
    assert proposal.candidate is not None
    assert proposal.candidate.actions == (("deal",),)
    assert lock["operational_epoch"] == 2
    assert lock["analysed_epoch"] == 2
    assert "one more stock row" not in " ".join(proposal.events)


def test_wasteful_receiver_relocation_loses_to_dealing_now():
    row = [Card("s", 5)] + [Card("d", 4)] * 9
    state = _board(
        [
            Column([], [Card("s", 6)]),
            Column([], [Card("d", 4)]),
            Column([], [Card("c", 5)]),
        ],
        row,
    )
    compared = compare_exact_reception(state, ((1, 2, 1),), 0, "s")
    assert compared.choice == "deal_now"
    assert compared.immediate_connects is True
    assert compared.prepared_connects is True
    assert compared.preparation_cost > compared.deal_only_cost


def test_a_failed_reveal_does_not_walk_the_epoch_forward():
    lock = {"label": "S#1"}
    assert (
        revise_operational_epoch(
            lock,
            analysed=2,
            theoretical=2,
            stock_changed=False,
            foundation_removed=False,
            note="first selection",
        )
        == "unchanged"
    )
    assert lock["operational_epoch"] == 2
    assert lock["original_epoch"] == 2
    rejected = revise_operational_epoch(
        lock,
        analysed=4,
        theoretical=2,
        stock_changed=False,
        foundation_removed=False,
        note="tactical miss",
    )
    assert rejected == "rejected"
    assert lock["operational_epoch"] == 2
    assert lock["rejected_revisions"][-1]["old"] == 2
    assert lock["rejected_revisions"][-1]["new"] == 4
    assert "does not authorise" in lock["rejected_revisions"][-1]["stock_timing"]
    revised = revise_operational_epoch(
        lock,
        analysed=1,
        theoretical=1,
        stock_changed=True,
        foundation_removed=False,
        arrived=((12, "stock:2:0", "tableau:1:up:1"),),
        note="the dealt row exposed the card",
    )
    assert revised == "revised"
    assert lock["operational_epoch"] == 1
    change = lock["epoch_changes"][-1]
    assert change["old"] == 2 and change["new"] == 1
    assert change["stock_timing"]

    cards, state, g = _prefix(31)
    live = {}
    first = propose_foundation_step(state, cards, _profile(), 8.0, g, cache={}, lock=live)
    assert live["operational_epoch"] == 2
    blocked = []
    for item in first.public["prerequisites"]:
        if item["kind"] == "excavate" and not item["achieved"]:
            live.setdefault("failures", {})[item["id"]] = 3
            blocked.append(item["id"])
    if first.candidate is not None:
        blocked.append(first.candidate.candidate_id)
    second = propose_foundation_step(
        state, cards, _profile(), 8.0, g, cache={}, lock=live, blocked=tuple(blocked)
    )
    assert live["operational_epoch"] == 2
    assert second.candidate is None or second.candidate.kind != "DEAL_NOW"
    assert "one stock row is tried" not in " ".join(second.events)
    assert "one more stock row" not in " ".join(second.events)


def test_multi_step_unblock_is_more_than_one_legal_action():
    cards, state, _g = _prefix(31)
    located = locate_source(state, "tableau:1:up:1")
    assert located is not None
    plan = plan_obstructed_access(state, located[0], (), source_key="tableau:1:up:1", column=1)
    assert plan is not None
    assert len(plan.actions) > 1
    assert plan.depth_after < plan.depth_before
    trial = state.clone()
    for action in plan.actions:
        apply_action(trial, action)
    assert _cover(trial, located[0]) == plan.depth_after
    del cards


def test_remaining_legal_moves_are_a_planning_stall():
    status, reason = strategic_stop_status(
        goal="first-foundation", legal_count=8, proved_no_legal_continuation=False
    )
    assert status == "PLANNING_STALL"
    assert "not a proof" in reason
    empty, empty_reason = strategic_stop_status(
        goal="first-foundation", legal_count=0, proved_no_legal_continuation=True
    )
    assert empty == "EXHAUSTED"
    assert "no legal continuation" in empty_reason
    play, play_reason = strategic_stop_status(
        goal="play", legal_count=8, proved_no_legal_continuation=False
    )
    assert play == "EXHAUSTED"
    assert play_reason.startswith("principal objective failed")

    from spider.human_strategy import controller as controller_module
    from spider.human_strategy.foundation_direction import FoundationProposal

    def _block(*_args, **_kwargs):
        return FoundationProposal(
            None,
            "",
            ("foundation: deal waits on an open prerequisite",),
            False,
            True,
            None,
            {},
        )

    original_propose = controller_module.propose_foundation_step
    original_useful = controller_module._moves_that_meet_their_purpose
    original_deals = controller_module._choice_deals
    controller_module.propose_foundation_step = _block
    controller_module._moves_that_meet_their_purpose = lambda *_args, **_kwargs: []
    controller_module._choice_deals = lambda _choice: True
    try:
        cards = _cards()
        opening = SpiderState.from_cards(list(cards))
        assert all_legal_actions(opening)
        result = solve(
            opening,
            _profile(max_steps=2, time_limit_s=8),
            mode="cold",
            goal="first-foundation",
            deal_cards=cards,
        )
    finally:
        controller_module.propose_foundation_step = original_propose
        controller_module._moves_that_meet_their_purpose = original_useful
        controller_module._choice_deals = original_deals
    assert result.status == "PLANNING_STALL"
    assert result.solved is False
    assert "planning stall" in result.stop_reason
    assert face_down_count(opening) == 44


def test_measured_connection_deals_inside_the_locked_horizon():
    """Shaping that cannot move a receiver may still deal when the row connects.

    The authorisation is the landing itself. The operational epoch stays put.
    """

    cards = _cards()
    state = SpiderState.from_cards(list(cards))
    lock = {}
    cache = {}
    profile = _profile(time_limit_s=8)
    dealt = None
    for step in range(12):
        proposal = propose_foundation_step(
            state, cards, profile, 8.0, 0, cache=cache, lock=lock
        )
        assert lock.get("operational_epoch") == 2
        assert not lock.get("epoch_changes")
        if proposal.candidate is not None and proposal.candidate.actions[:1] == (("deal",),):
            assert step > 0
            dealt = proposal
            break
        assert proposal.candidate is not None
        assert proposal.candidate.actions[0] != ("deal",)
        apply_action(state, proposal.candidate.actions[0])
    assert dealt is not None
    assert dealt.reason == (
        "selected: a known incoming card enables a same-suit connection after preparation was tried"
    )
    text = " ".join(dealt.candidate.evidence)
    assert "was not revised" in text
    assert "same-suit landing" in text or "extends the suit" in text
    assert "cannot reveal" not in dealt.reason
    assert "one more stock row" not in " ".join(dealt.events)
    assert "cannot legally reach column 7" not in " ".join(dealt.events)
    _feasibility, portfolio = load_portfolio(state, cards, cache)
    campaign = next(item for item in portfolio.campaigns if item.label == lock["label"])
    _comparison, notes = plan_receiver_alignment(state, campaign)
    assert any("already the top" in note for note in notes)
    assert not any("9s" in note and "cannot legally reach" in note for note in notes)
    apply_action(state, ("deal",))
    assert any(
        len(column.face_up) >= 2
        and str(column.face_up[-2]) == "10s"
        and str(column.face_up[-1]) == "9s"
        for column in state.columns
    )


def test_an_unrecoverable_long_run_blocks_a_cosmetic_deal():
    run = [Card("s", rank) for rank in (7, 6, 5, 4, 3, 2)]
    row = [
        Card("d", 4),
        Card("s", 9),
        Card("h", 13),
        Card("d", 13),
        Card("c", 12),
        Card("d", 2),
        Card("h", 3),
        Card("h", 6),
        Card("h", 8),
        Card("c", 7),
    ]
    buried = _board(
        [Column([], run), Column([], [Card("s", 10)])],
        row,
    )
    assert measured_stock_connection(buried, "s", (), operational=2, current=0) is None
    row[2] = Card("c", 5)
    recoverable = _board(
        [Column([], run), Column([], [Card("s", 10)])],
        row,
    )
    evidence = measured_stock_connection(recoverable, "s", (), operational=2, current=0)
    assert evidence is not None
    text = " ".join(evidence)
    assert "9s onto 10s" in text
    assert "lifts that cover" in text
    assert "was not revised" in text
    assert measured_stock_connection(recoverable, "s", (), operational=0, current=0) is None


def _cover(state, card):
    for column in state.columns:
        for index, item in enumerate(column.face_up):
            if item is card:
                return len(column.face_up) - 1 - index
        for index, item in enumerate(column.face_down):
            if item is card:
                return len(column.face_up) + (len(column.face_down) - 1 - index)
    raise AssertionError("card left the tableau")


def _longest_spade_run(state):
    best = 0
    for column in state.columns:
        up = column.face_up
        index = 0
        while index < len(up):
            if up[index].suit != "s":
                index += 1
                continue
            end = index
            while (
                end + 1 < len(up)
                and up[end + 1].suit == "s"
                and up[end].rank - 1 == up[end + 1].rank
            ):
                end += 1
            best = max(best, end - index + 1)
            index = end + 1
    return best
