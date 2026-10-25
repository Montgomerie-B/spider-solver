"""v0.111 multi-foundation continuation and exact stock-receiver tests.

Synthetic boards isolate receiver geometry. Real 4925153 positions are
replayed only to reach a state. The controller does not receive a stored
move list as its cold-mode plan.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    FoundationAgenda,
    FoundationView,
    _necessary_deal,
    _proposal,
    adopt_alternative_foundation,
    close_foundation_campaign,
    propose_foundation_step,
    rank_foundations,
    revise_operational_epoch,
    search_post_deal_recovery,
    structural_assessment,
)
from spider.human_strategy.preparation import (
    assess_receiver_move,
    classify_incoming_receiver,
    strategic_stop_status,
)
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import parse_moves_file, replay_actions
from spider.planner.foundation_campaign_realizer import (
    CampaignObligation,
    CampaignObligationKind,
    obligation_is_satisfied,
)
from spider.human_strategy.evaluation import same_suit_bonds
from spider.research_actions import all_legal_actions, apply_action, face_down_count
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"

# The v0.110 cold opening, kept here as the regression oracle. It is not
# loaded by the controller.
G19 = (
    (2, 5, 1),
    (6, 8, 1),
    (9, 8, 1),
    (6, 9, 1),
    (5, 7, 2),
    (5, 7, 1),
    (0, 7, 1),
    (2, 1, 1),
    (7, 2, 5),
    ("deal",),
    (9, 5, 1),
    (1, 9, 1),
    (2, 5, 1),
    (2, 8, 6),
    (8, 6, 7),
    (6, 0, 9),
    (0, 1, 10),
    ("deal",),
    (1, 0, 12),
)


def _profile(**kwargs):
    base = dict(
        time_limit_s=20,
        max_steps=8,
        tactical_nodes=400,
        tactical_time_s=0.8,
        tactical_max_cost=4,
        consult_portfolio=False,
        strategic_width=2,
        max_width=3,
        rss_abort_mb=2048,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _cards():
    return load_deal(DEAL)


def _opening():
    return SpiderState.from_cards(list(_cards()))


def _board(columns, row):
    cols = list(columns)
    while len(cols) < 10:
        cols.append(Column([], [Card("c", 13)]))
    return SpiderState(cols, list(row))


def _obligation(card, column, receiver_rank):
    return CampaignObligation(
        obligation_id=f"receiver:{card.suit}{card.rank}:c{column}:d1",
        kind=CampaignObligationKind.SHAPE_RECEIVER,
        description="test receiver",
        mandatory_before_deal=False,
        deadline_epoch=1,
        rank=card.rank,
        receiver_column=column,
        incoming_card=card,
        receiver_rank=receiver_rank,
    )


def _filled(top, n=10):
    return [Column([], [top if index == 0 else Card("c", 13)]) for index in range(n)]


def test_exact_column_receiver_is_not_card_presence():
    incoming = Card("s", 5)
    ready = _board([Column([], [Card("s", 6)])], [incoming] + [Card("d", 3)] * 9)
    placed = classify_incoming_receiver(ready, incoming, 0)
    assert placed.status == "already_positioned"
    assert placed.direct is True
    assert placed.actions == ()
    assert obligation_is_satisfied(ready, None, _obligation(incoming, 0, 6)) is True

    elsewhere = _board(
        [Column([], [Card("d", 9)]), Column([], [Card("s", 6)])],
        [incoming] + [Card("d", 3)] * 9,
    )
    wrong = classify_incoming_receiver(elsewhere, incoming, 0)
    assert wrong.status != "already_positioned"
    assert wrong.direct is False
    assert wrong.status in {"relocatable", "needs_preparation", "blocked", "post_deal_transfer", "unavailable"}
    assert obligation_is_satisfied(elsewhere, None, _obligation(incoming, 0, 6)) is False
    assert "already the exposed receiver on column 1" not in " ".join(wrong.evidence)


def test_movable_receiver_on_the_wrong_column_can_be_relocated():
    incoming = Card("s", 5)
    state = _board(
        [Column([], [Card("c", 7)]), Column([], [Card("s", 6)])],
        [incoming] + [Card("d", 3)] * 9,
    )
    landing = classify_incoming_receiver(state, incoming, 0)
    assert landing.status == "relocatable"
    assert landing.actions
    trial = state.clone()
    for action in landing.actions:
        assert trial.can_move(*action) if action != ("deal",) else trial.can_deal()
        apply_action(trial, action)
    assert str(trial.columns[0].top()) == "6s"


def test_blocked_receiver_and_multi_step_preparation():
    incoming = Card("s", 5)
    blocked = _board(
        [
            Column([], [Card("d", 9)]),
            Column([], [Card("s", 6), Card("c", 13)]),
        ],
        [incoming] + [Card("d", 4)] * 9,
    )
    buried = classify_incoming_receiver(blocked, incoming, 0)
    assert buried.status == "blocked"
    assert buried.direct is False
    assert obligation_is_satisfied(blocked, None, _obligation(incoming, 0, 6)) is False

    prepared = _board(
        [
            Column([], [Card("c", 7)]),
            Column([], [Card("s", 6), Card("d", 11)]),
            Column([], [Card("c", 12)]),
        ],
        [incoming] + [Card("h", 2)] * 9,
    )
    staged = classify_incoming_receiver(prepared, incoming, 0, max_cost=3, max_expand=400)
    assert staged.status == "needs_preparation"
    assert len(staged.actions) > 1
    trial = prepared.clone()
    for action in staged.actions:
        apply_action(trial, action)
    assert str(trial.columns[0].top()) == "6s"


def test_post_deal_transfer_is_validated_and_a_harmful_move_is_not():
    incoming = Card("s", 5)
    row = [incoming] + [Card("h", 2)] * 9
    row[3] = Card("s", 6)
    state = _board([Column([], [Card("d", 9)])], row)
    landing = classify_incoming_receiver(state, incoming, 0)
    assert landing.status == "post_deal_transfer"
    assert landing.actions
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    apply_action(dealt, landing.actions[0])
    assert str(dealt.columns[landing.actions[0][1]].top()) == "5s"

    already = _board([Column([], [Card("s", 6)]), Column([], [Card("c", 7)])], [incoming] + [Card("d", 3)] * 9)
    harmful = assess_receiver_move(already, incoming, 0, ((0, 1, 1),))
    assert harmful.status == "not_worthwhile"
    untouched = classify_incoming_receiver(already, incoming, 0)
    assert untouched.status == "already_positioned"
    assert untouched.actions == ()


def test_incoming_king_is_neither_a_failed_reception_nor_a_foundation():
    incoming = Card("s", 13)
    row = [incoming] + [Card("h", 2)] * 9
    row[1] = Card("s", 12)
    state = _board(
        [Column([], [Card("d", 4)]), Column([], [Card("h", 13)])],
        row,
    )
    landing = classify_incoming_receiver(state, incoming, 0)
    assert landing.status == "king_anchor"
    assert landing.direct is False
    assert "not a completed foundation" in " ".join(landing.evidence)
    assert "queen-led follow-up is True" in " ".join(landing.evidence)
    assert obligation_is_satisfied(state, None, _obligation(incoming, 0, None)) is False
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    assert dealt.foundations == []


def test_multi_move_recovery_is_searched_and_not_automatic():
    run = [Card("s", 8), Card("s", 7), Card("s", 6)]
    row = [
        Card("d", 13),
        Card("s", 9),
        Card("d", 2),
        Card("h", 12),
        Card("d", 4),
        Card("h", 13),
        Card("c", 6),
        Card("d", 7),
        Card("c", 8),
        Card("h", 9),
    ]
    columns = [
        Column([], run),
        Column([], [Card("s", 10)]),
        Column([], [Card("c", 13)]),
        Column([], []),
        Column([], [Card("c", 13)]),
        Column([], [Card("c", 13)]),
    ]
    state = _board(columns, row)
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    assert search_post_deal_recovery is not None
    one_move = [
        action
        for action in all_legal_actions(dealt)
        if action != ("deal",) and action[0] == 0 and action[2] == 1
    ]
    assert one_move == []
    recovery = search_post_deal_recovery(dealt, run[-1], ())
    assert recovery is not None
    assert len(recovery.actions) >= 2
    trial = dealt.clone()
    paid = 0
    for action in recovery.actions:
        paid += apply_action(trial, action)
    assert paid == recovery.cost
    assert trial.columns[0].top() is run[-1]

    from spider.human_strategy.foundation_direction import measured_stock_connection

    evidence = measured_stock_connection(state, "s", (), operational=2, current=0)
    assert evidence is not None
    text = " ".join(evidence)
    assert "9s onto 10s" in text
    assert "2-move recovery" in text or "move recovery" in text
    assert "was not revised" in text

    blocked_row = list(row)
    blocked_columns = []
    for index in range(10):
        blocked_columns.append(Column([Card("h", 2)], [Card("c", 13)]))
    blocked_columns[0] = Column([], list(run))
    blocked_columns[1] = Column([Card("h", 2)], [Card("s", 10)])
    blocked = SpiderState(blocked_columns, blocked_row)
    assert measured_stock_connection(blocked, "s", (), operational=2, current=0) is None


def test_necessary_deal_does_not_require_a_same_suit_landing_or_an_epoch_bump():
    incoming = Card("h", 5)
    state = _board(
        [Column([], [Card("c", 13)]), Column([], [Card("h", 6)])],
        [incoming] + [Card("d", 2)] * 9,
    )
    need = SimpleNamespace(
        rank=5,
        chosen=SimpleNamespace(
            source_key="stock:1:0",
            stock_epoch=1,
            stock_column=0,
            card=incoming,
        ),
    )
    campaign = SimpleNamespace(
        label="H#1",
        suit="h",
        current_epoch=0,
        estimated_campaign_cost=4.0,
        rank_needs=(need,),
    )
    view = FoundationView(
        suit="h",
        copy_index=1,
        label="H#1",
        target_epoch=1,
        current_epoch=0,
        earliest_epoch=1,
        other_copy_earliest=3,
        estimated_cost=4.0,
        readiness="stock_gated",
        confidence="LOW",
        theoretically_available=False,
        operationally_attainable=True,
        economically_attractive=True,
        face_up=0,
        face_down=0,
        stock_count=1,
        burial=0,
        longest_fragment=0,
        reasons=("fact: test",),
    )
    agenda = FoundationAgenda(view, (), (), (), 4.0, 1, 0, 10, ("fact: test",))
    _proposal.active_lock = None
    refused = set()
    events = []
    deal = _necessary_deal(state, 0, campaign, agenda, {}, events, refused, 1)
    assert deal is not None
    assert deal.candidate.actions == (("deal",),)
    assert "neutral" in deal.reason
    text = " ".join(deal.candidate.evidence)
    assert "analysed-epoch increase is not the reason" in text
    assert "required card has not arrived" in text
    assert _necessary_deal(state, 0, campaign, agenda, {}, [], refused, 0) is None
    drifted = revise_operational_epoch(
        {"original_epoch": 2, "operational_epoch": 2},
        analysed=5,
        theoretical=5,
        stock_changed=False,
        foundation_removed=False,
    )
    assert drifted == "rejected"


def test_completion_drops_the_old_horizon_and_a_stall_can_change_target():
    lock = {
        "label": "S#1",
        "operational_epoch": 2,
        "original_epoch": 2,
        "outstanding": ["excavate:s12"],
        "failures": {"excavate:s12": 3},
        "suspended_notes": {"excavate:s12"},
        "alternatives": ["D#1", "H#1"],
    }
    record = close_foundation_campaign(
        lock,
        reason="S#1 removed at corrected cost 19",
        exact_cost=19,
        cumulative_g=19,
        label="S#1",
    )
    assert record["exact_cost"] == 19
    assert lock.get("operational_epoch") is None
    assert lock.get("outstanding") is None
    assert "excavate:s12" not in lock.get("failures", {})
    assert lock["completed"][0]["label"] == "S#1"

    stalled = {
        "label": "S#1",
        "operational_epoch": 2,
        "failures": {"excavate:s9": 3},
        "alternatives": ["D#1", "C#1"],
    }
    reason = adopt_alternative_foundation(stalled)
    assert reason is not None and "D#1" in reason
    assert stalled["label"] == "D#1"
    assert stalled.get("operational_epoch") is None
    assert "excavate:s9" not in stalled.get("failures", {})
    assert "stalled" in " ".join(stalled["campaign_changes"])


def test_foundation_ranking_is_not_hard_coded_and_copies_stay_distinct():
    cards = _cards()
    opening = _opening()
    views = rank_foundations(opening, cards)
    assert len(views) >= 4
    assert len({item.label for item in views}) == len(views)
    assert all(item.copy_index in {1, 2} for item in views)
    assert all(
        "other physical copy" in " ".join(item.reasons) for item in views
    )
    mapping = {"s": "h", "h": "s"}

    def remap(card: Card) -> Card:
        return Card(mapping.get(card.suit, card.suit), card.rank)

    swapped_cards = [remap(card) for card in cards]
    swapped = SpiderState(
        [
            Column([remap(card) for card in column.face_down], [remap(card) for card in column.face_up])
            for column in opening.columns
        ],
        [remap(card) for card in opening.stock],
    )
    swapped_views = rank_foundations(swapped, swapped_cards)
    assert swapped_views[0].suit == mapping[views[0].suit]
    assert swapped_views[0].label != views[0].label


def test_first_foundation_status_stays_distinct_from_a_later_target():
    cards = _cards()
    actions = parse_moves_file(CANONICAL)
    state = SpiderState.from_cards(list(cards))
    g = replay_actions(state, list(actions[:82]))
    one = solve(
        state.clone(),
        _profile(max_steps=4, time_limit_s=15),
        mode="diagnose",
        opening_g=g,
        goal="foundations",
        target_foundations=1,
        deal_cards=cards,
        provenance_note="diagnostic canonical prefix 82; suffix not injected",
    )
    assert one.status == "FOUNDATION_TARGET_REACHED"
    assert one.solved is False
    assert one.foundations == 1
    assert one.provenance["partial_trajectory"] is True
    assert one.provenance["prefix_injected"] is False
    assert "finished game" in one.stop_reason
    kept = solve(
        state.clone(),
        _profile(max_steps=4, time_limit_s=15),
        mode="diagnose",
        opening_g=g,
        goal="first-foundation",
        deal_cards=cards,
        provenance_note="diagnostic canonical prefix 82; suffix not injected",
    )
    assert kept.status == "FOUNDATION_REACHED"
    assert kept.actions[0] == ("deal",)
    assert kept.actions[1] == (1, 0, 12)
    stall, _reason = strategic_stop_status(
        goal="foundations", legal_count=4, proved_no_legal_continuation=False
    )
    assert stall == "PLANNING_STALL"


def test_multi_foundation_continues_and_does_not_keep_the_old_spade_horizon():
    cards = _cards()
    actions = parse_moves_file(CANONICAL)
    state = SpiderState.from_cards(list(cards))
    g = replay_actions(state, list(actions[:82]))
    result = solve(
        state,
        _profile(max_steps=8, time_limit_s=25),
        mode="diagnose",
        opening_g=g,
        goal="foundations",
        target_foundations=2,
        deal_cards=cards,
        provenance_note="diagnostic canonical prefix 82; suffix not injected",
    )
    assert result.foundations >= 1
    assert result.status != "FOUNDATION_REACHED"
    assert result.solved is False
    assert any(
        "closed completed campaign" in event or "new horizon" in event for event in result.events
    )
    completed = [item for item in result.provenance["foundation"] if item.get("reason") == "foundation completed"]
    assert completed
    assert completed[0]["label"] == "S#1"
    assert completed[0]["exact_cost"] > 0
    assert completed[0]["assessment"]["heuristic_remaining_is_not_a_bound"] is True
    closed = result.provenance["completed_campaigns"]
    assert closed and closed[0]["label"] == "S#1"
    stale = set(closed[0].get("outstanding_at_close") or [])
    live = [
        item.get("campaign_record", {})
        for item in result.provenance["foundation"]
        if item.get("campaign_record") and item.get("reason") != "foundation completed"
    ]
    fresh = [item for item in live if item.get("label") not in {None, "S#1"}]
    if result.foundations == 1 and result.status != "FOUNDATION_TARGET_REACHED":
        assert fresh or any("alternative under test" in event or "selected" in event for event in result.events)
        if fresh:
            assert fresh[0].get("epoch_changes") == []
            assert not stale.intersection(fresh[0].get("outstanding") or [])
    if result.foundations >= 2:
        assert result.status == "FOUNDATION_TARGET_REACHED"
        assert result.provenance["partial_trajectory"] is True


def test_commitment_and_suspension_do_not_deadlock_the_campaign():
    cards = _cards()
    state = _opening()
    lock = {}
    cache = {}
    label = None
    proposal = None
    for _step in range(3):
        proposal = propose_foundation_step(state, cards, _profile(), 6.0, 0, cache=cache, lock=lock)
        assert proposal.candidate is not None
        if label is None:
            label = lock["label"]
        assert lock["label"] == label
        apply_action(state, proposal.candidate.actions[0])
    open_ids = [
        item["id"]
        for item in proposal.public["prerequisites"]
        if item["kind"] == "excavate" and item["mandatory_before_deal"] and not item["achieved"]
    ]
    assert open_ids
    for ident in open_ids:
        lock["failures"][ident] = 3
    suspended = propose_foundation_step(state, cards, _profile(), 4.0, 0, cache=cache, lock=lock)
    assert lock["label"] == label
    assert any("stays open" in event for event in suspended.events)
    assert "impossible" not in " ".join(suspended.events)


def test_corrected_mobilityware_cost_includes_a_free_whole_column_move():
    state = _board(
        [
            Column([], [Card("s", 3), Card("s", 2), Card("s", 1)]),
            Column([], []),
        ],
        [Card("d", rank) for rank in range(1, 11)],
    )
    assert apply_action(state, (0, 1, 3)) == 0
    paid = _board(
        [Column([Card("h", 4)], [Card("s", 3), Card("s", 2)]), Column([], [])],
        [Card("d", rank) for rank in range(1, 11)],
    )
    assert apply_action(paid, (0, 1, 2)) == 1
    assert apply_action(paid, ("deal",)) == 1


def test_cold_mode_refuses_a_stored_prefix():
    cards = _cards()
    try:
        solve(
            _opening(),
            _profile(max_steps=1, time_limit_s=2),
            mode="cold",
            goal="first-foundation",
            deal_cards=cards,
            incumbent_actions=(("deal",),),
        )
    except ValueError as exc:
        assert "cold" in str(exc)
    else:
        raise AssertionError("cold mode accepted an incumbent sequence")


def test_cold_opening_replays_the_spade_foundation_at_g19_and_can_continue():
    cards = _cards()
    opening = _opening()
    before = canonical_state_key(opening)
    result = solve(
        opening,
        _profile(max_steps=80, time_limit_s=70, tactical_nodes=800, tactical_time_s=1.0),
        mode="cold",
        goal="foundations",
        target_foundations=2,
        deal_cards=cards,
    )
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["goal"] == "foundations"
    assert result.actions[:19] == G19
    assert result.status != "FOUNDATION_REACHED"
    assert result.solved is False
    final = _verify_g19(cards, result.actions[:19])
    assert len(final.foundations) == 1
    sequence = final.foundations[0]
    assert [card.rank for card in sequence] == list(range(13, 0, -1))
    assert {card.suit for card in sequence} == {"s"}
    assert face_down_count(final) == 33
    assert len(final.stock) == 30
    assert same_suit_bonds(final) == 1
    assert canonical_state_key(final) == canonical_state_key(final.clone())
    assert canonical_state_key(opening) == before
    _conserve(cards, final)
    if result.foundations >= 2:
        assert result.status == "FOUNDATION_TARGET_REACHED"
        assert result.provenance["partial_trajectory"] is True
        _verify_completed(cards, result.actions, result.foundations)
    else:
        assert len(result.actions) > 19
        assert any("new horizon" in event or "closed completed campaign" in event for event in result.events)
    assessment = structural_assessment(final)
    assert assessment["face_down"] == 33
    assert assessment["heuristic_remaining_is_not_a_bound"] is True
    assert isinstance(assessment["admissible_remaining"], int)


def test_g19_structure_is_not_treated_as_a_finished_game():
    cards = _cards()
    opening = _opening()
    g19 = opening.clone()
    assert replay_actions(g19, list(G19)) == 19
    canonical = opening.clone()
    canon_actions = parse_moves_file(CANONICAL)
    autonomous = opening.clone()
    auto_actions = parse_moves_file(AUTONOMOUS)
    # The reference routes remove their first foundation later. Compare the
    # boards at those removals by structure, not by treating g=19 as better.
    canon_at = _state_at_first_foundation(canonical, canon_actions)
    auto_at = _state_at_first_foundation(autonomous, auto_actions)
    early = structural_assessment(g19)
    later_canon = structural_assessment(canon_at)
    later_auto = structural_assessment(auto_at)
    assert early["foundations"] == later_canon["foundations"] == later_auto["foundations"] == 1
    assert early["face_down"] > later_canon["face_down"]
    assert early["stock_cards"] > 0
    assert early["heuristic_remaining_is_not_a_bound"] is True
    assert later_canon["heuristic_remaining_is_not_a_bound"] is True


def _verify_g19(cards, actions):
    state = SpiderState.from_cards(list(cards))
    paid = 0
    for action in actions:
        if action == ("deal",):
            assert state.can_deal()
        else:
            src, _dst, k = action
            run = state.columns[src].face_up[-k:]
            assert state.is_movable_run(run)
            assert state.can_move(*action)
        paid += apply_action(state, action)
    assert paid == 19
    again = SpiderState.from_cards(list(cards))
    assert replay_actions(again, list(actions)) == 19
    assert canonical_state_key(again) == canonical_state_key(state)
    return state


def _verify_completed(cards, actions, expected_foundations):
    state = SpiderState.from_cards(list(cards))
    seen = 0
    for action in actions:
        if action != ("deal",):
            src, _dst, k = action
            run = state.columns[src].face_up[-k:]
            assert state.is_movable_run(run)
        before = len(state.foundations)
        apply_action(state, action)
        if len(state.foundations) > before:
            seen += 1
            sequence = state.foundations[-1]
            assert len(sequence) == 13
            assert [card.rank for card in sequence] == list(range(13, 0, -1))
            assert len({card.suit for card in sequence}) == 1
    assert seen == expected_foundations
    _conserve(cards, state)
    return state


def _conserve(cards, state):
    remaining = []
    for column in state.columns:
        remaining.extend(column.face_down)
        remaining.extend(column.face_up)
    remaining.extend(state.stock)
    for sequence in state.foundations:
        remaining.extend(sequence)
    assert len(remaining) == 104
    assert sorted((card.suit, card.rank) for card in remaining) == sorted(
        (card.suit, card.rank) for card in cards
    )


def _state_at_first_foundation(state, actions):
    for action in actions:
        before = len(state.foundations)
        apply_action(state, action)
        if len(state.foundations) > before:
            return state
    raise AssertionError("reference solution removed no foundation")
