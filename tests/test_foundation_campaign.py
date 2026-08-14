"""Focused tests for the perfect-information foundation campaign analyser."""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner import foundation_campaign as fc
from spider.planner.foundation_campaign import (
    RankSource,
    RankSourceKind,
    SpacePolicy,
    analyze_foundation_campaign,
    analyze_foundation_campaigns,
)


def _two_decks() -> list[Card]:
    return [
        Card(suit, rank)
        for _copy in range(2)
        for suit in "shdc"
        for rank in range(1, 14)
    ]


def _take(pool: list[Card], card: Card) -> Card:
    idx = pool.index(card)
    return pool.pop(idx)


def _deal(
    *,
    tableau_required: list[Card] | None = None,
    forced_stock: dict[tuple[int, int], Card] | None = None,
) -> list[Card]:
    """Make a valid 104-card deal with exact (epoch,column) stock placements."""
    pool = _two_decks()
    rows: list[list[Card | None]] = [[None] * 10 for _ in range(5)]
    for (epoch, column), card in (forced_stock or {}).items():
        rows[epoch - 1][column] = _take(pool, card)
    tableau: list[Card] = []
    for card in tableau_required or []:
        tableau.append(_take(pool, card))
    while len(tableau) < 54:
        tableau.append(pool.pop())
    for row in rows:
        for column in range(10):
            if row[column] is None:
                row[column] = pool.pop()
    assert not pool
    stock: list[Card] = []
    for epoch in range(5, 0, -1):
        stock.extend(card for card in rows[epoch - 1] if card is not None)
    assert len(tableau) == 54 and len(stock) == 50
    return tableau + stock


def _pad(columns: list[Column], stock: list[Card], *, leave_empty: bool = False) -> SpiderState:
    while len(columns) < 10:
        i = len(columns)
        if leave_empty and i == 9:
            columns.append(Column([], []))
        else:
            columns.append(
                Column(
                    [Card("d", 2 if i % 2 else 3)],
                    [Card("c", 12 if i % 2 else 13)],
                )
            )
    return SpiderState(columns, list(stock), [])


def _spade_complete_opening_cards(**kwargs) -> list[Card]:
    required = [Card("s", rank) for rank in range(1, 14)]
    return _deal(tableau_required=required, **kwargs)


def _synthetic_stock(overrides: dict[tuple[int, int], Card] | None = None) -> list[Card]:
    """Five known rows in engine order; intentionally geometry-only inventory."""
    rows = [[Card("d", 2) for _column in range(10)] for _epoch in range(5)]
    for (epoch, column), card in (overrides or {}).items():
        rows[epoch - 1][column] = card
    stock: list[Card] = []
    for epoch in range(5, 0, -1):
        stock.extend(rows[epoch - 1])
    return stock


def test_duplicate_substitution_prefers_exposed_copy():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([], [Card("s", r) for r in range(13, 7, -1)]),
            Column([], [Card("s", r) for r in range(6, 0, -1)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("s", 7)]),
            Column([], [Card("h", 10)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    seven = campaign.rank_need(7)
    assert seven.chosen is not None
    assert seven.chosen.kind == RankSourceKind.ALREADY_USABLE
    assert seven.chosen.column == 3
    assert any(source.column == 2 for source in seven.safe_to_wait)
    assert all(source.card.rank != 7 for source in campaign.tableau_critical_cards)


def test_stock_supplied_rank_avoids_buried_excavation_and_maps_exact_column():
    cards = _deal(
        tableau_required=[Card("s", rank) for rank in range(1, 14) if rank != 7],
        forced_stock={(1, 0): Card("s", 7)},
    )
    state = _pad(
        [
            Column([], [Card("s", r) for r in range(13, 7, -1)]),
            Column([], [Card("s", r) for r in range(6, 0, -1)]),
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("h", 10)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=1
    )
    seven = campaign.rank_need(7)
    assert seven.chosen is not None
    assert seven.chosen.kind == RankSourceKind.STOCK
    assert seven.chosen.stock_epoch == 1
    assert seven.chosen.stock_column == 0
    assert any(source.column == 2 for source in seven.safe_to_wait)
    assert all(source.card.rank != 7 for source in campaign.tableau_critical_cards)
    incoming = next(card for card in campaign.stock_plan[0].incoming if card.card == Card("s", 7))
    assert incoming.column == 0
    assert incoming.selected_source
    assert incoming.landing_now == "same_suit_connect"


def test_unreplaceable_tableau_rank_is_campaign_critical():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 7)], [Card("h", 9)]),
            Column([], [Card("s", r) for r in range(13, 7, -1)]),
            Column([], [Card("s", r) for r in range(6, 0, -1)]),
            Column([], [Card("h", 10)]),
        ],
        [Card("c", ((i % 13) + 1)) for i in range(50)],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    seven = campaign.rank_need(7)
    assert seven.must_excavate
    assert seven.chosen is not None and seven.chosen.column == 0
    assert any(source.card == Card("s", 7) for source in campaign.tableau_critical_cards)
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert 7 in project.required_ranks
    assert not seven.safe_to_wait


def test_campaign_earliest_epoch_respects_late_rank():
    cards = _deal(
        tableau_required=[Card("s", rank) for rank in range(2, 14)],
        forced_stock={(2, 4): Card("s", 1), (5, 7): Card("s", 1)},
    )
    state = _pad(
        [Column([], [Card("s", rank) for rank in range(13, 1, -1)])],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(state, cards=cards, suit="s")
    assert campaign.earliest_theoretical_epoch == 2
    assert campaign.target_removal_epoch is not None
    assert campaign.target_removal_epoch >= 2
    ace = campaign.rank_need(1)
    assert ace.chosen is not None
    assert ace.chosen.stock_epoch is not None
    assert ace.chosen.stock_epoch >= 2


def test_shared_excavation_prefix_is_counted_once_at_max_depth():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column(
                [Card("s", 5), Card("s", 6), Card("s", 7)],
                [Card("h", 9)],
            ),
            Column([], [Card("s", r) for r in range(13, 7, -1)]),
            Column([], [Card("s", r) for r in range(4, 0, -1)]),
            Column([], [Card("h", 10)]),
            Column([], [Card("h", 7)]),
            Column([], [Card("h", 6)]),
        ],
        [Card("c", ((i % 13) + 1)) for i in range(50)],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert set(project.required_ranks) == {5, 6, 7}
    assert project.required_peels == 3
    assert sum(p.column == 0 for p in campaign.prerequisite_excavation_projects) == 1
    # Max-union: the three rank sources do not produce three independent projects.
    assert project.estimated_direct_cost == max(
        campaign.rank_need(rank).chosen.excavation_peels  # type: ignore[union-attr]
        for rank in (5, 6, 7)
    )


def test_one_space_is_spent_on_a_real_campaign_critical_reveal():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 6)], [Card("h", 13)]),
            Column([], [Card("s", r) for r in range(13, 6, -1)]),
            Column([], [Card("s", r) for r in range(5, 0, -1)]),
        ],
        [Card("c", ((i % 13) + 1)) for i in range(50)],
        leave_empty=True,
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    plan = campaign.space_plan
    assert plan.workspace_available_now == 1
    assert plan.policy in (SpacePolicy.SPEND, SpacePolicy.RELOCATE)
    assert plan.action == (0, 9, 1)
    assert plan.enabled_project_column == 0
    assert 6 in plan.enabled_ranks
    assert plan.estimated_regain_cost is not None
    assert plan.estimated_regain_cost <= 2
    assert state.can_move(*plan.action)


def _swap_suits_card(card: Card, a: str, b: str) -> Card:
    suit = b if card.suit == a else a if card.suit == b else card.suit
    return Card(suit, card.rank)


def _swap_suits_state(state: SpiderState, a: str, b: str) -> SpiderState:
    return SpiderState(
        [
            Column(
                [_swap_suits_card(card, a, b) for card in col.face_down],
                [_swap_suits_card(card, a, b) for card in col.face_up],
            )
            for col in state.columns
        ],
        [_swap_suits_card(card, a, b) for card in state.stock],
        [
            [_swap_suits_card(card, a, b) for card in sequence]
            for sequence in state.foundations
        ],
    )


def test_clearly_early_suit_beats_late_suit_and_follows_suit_renaming():
    forced = {(5, 0): Card("h", 1), (5, 1): Card("h", 1)}
    cards = _deal(
        tableau_required=[Card("s", rank) for rank in range(1, 14)]
        + [Card("h", rank) for rank in range(2, 14)],
        forced_stock=forced,
    )
    state = _pad(
        [
            Column([], [Card("s", rank) for rank in range(13, 0, -1)]),
            Column([], [Card("h", rank) for rank in range(13, 1, -1)]),
        ],
        cards[54:],
    )
    portfolio = analyze_foundation_campaigns(state, cards=cards)
    spades = portfolio.campaign_for("s")
    hearts = portfolio.campaign_for("h")
    assert portfolio.primary is not None and portfolio.primary.suit == "s"
    assert spades.target_removal_epoch < hearts.target_removal_epoch
    assert spades.campaign_score > hearts.campaign_score

    swapped_cards = [_swap_suits_card(card, "s", "d") for card in cards]
    swapped_state = _swap_suits_state(state, "s", "d")
    swapped = analyze_foundation_campaigns(swapped_state, cards=swapped_cards)
    assert swapped.primary is not None and swapped.primary.suit == "d"
    assert swapped.primary.target_removal_epoch == spades.target_removal_epoch


def test_only_next_outstanding_ordinal_can_compete():
    cards = _spade_complete_opening_cards()
    sequence = [Card("s", rank) for rank in range(13, 0, -1)]
    state = _pad(
        [Column([], [Card("s", rank) for rank in range(13, 0, -1)])],
        cards[54:],
    )
    state.foundations.append(sequence)
    campaign = analyze_foundation_campaign(state, cards=cards, suit="s")
    assert campaign.copy_index == 2
    try:
        analyze_foundation_campaign(state, cards=cards, suit="s", copy_index=1)
    except ValueError as exc:
        assert "next outstanding ordinal" in str(exc)
    else:
        raise AssertionError("completed ordinal was allowed to compete again")


def test_no_benchmark_or_user_state_constants_in_generic_module():
    source = inspect.getsource(fc)
    for token in (
        "4925153",
        "77d169da",
        "canonical.moves",
        "4s-3s-2s",
        "cost 5",
        "column 6",
    ):
        assert token.lower() not in source.lower()
    assert re.search(r"cmd\d+", source, re.IGNORECASE) is None


def test_one_blocked_rank_preserves_the_other_twelve_source_selections():
    cards = _deal(
        tableau_required=[Card("s", rank) for rank in range(2, 14)],
        forced_stock={(2, 4): Card("s", 1), (3, 5): Card("s", 1)},
    )
    state = _pad(
        [
            Column([], [Card("s", rank) for rank in range(13, 7, -1)]),
            Column([], [Card("s", rank) for rank in range(7, 1, -1)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=1
    )
    assert campaign.rank_need(1).chosen is None
    assert all(campaign.rank_need(rank).chosen is not None for rank in range(2, 14))
    assert "A" in " ".join(campaign.blockers)


def test_future_destination_after_receiver_deadline_blocks_that_prefix():
    cards = _deal(
        tableau_required=[
            Card("s", rank) for rank in range(1, 14) if rank != 6
        ]
        + [Card("s", 7)],
        forced_stock={(2, 4): Card("s", 6), (3, 5): Card("s", 6)},
    )
    state = _pad(
        [
            Column([Card("s", 7), Card("s", 7)], [Card("h", 5)]),
            Column([], [Card("s", rank) for rank in range(13, 7, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=1
    )
    seven = campaign.rank_need(7)
    assert seven.chosen is None
    assert any(source.dependency_blocked for source in seven.sources if source.column == 0)
    assert campaign.rank_need(13).chosen is not None


def test_king_without_empty_is_a_workspace_prerequisite_not_a_hard_block():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 6)], [Card("h", 13)]),
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    six = campaign.rank_need(6)
    assert six.chosen is not None and six.chosen.column == 0
    assert six.chosen.usable_by_target
    assert six.chosen.needs_temp_space
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert project.needs_temp_space
    assert not project.blocked_dependencies


def _tableau_source(
    rank: int,
    column: int,
    peels: int,
    helpers: tuple[tuple[int, int], ...] = (),
) -> RankSource:
    return RankSource(
        source_key=f"test:{column}:{rank}",
        card=Card("s", rank),
        kind=RankSourceKind.DEEP_TABLEAU,
        column=column,
        tableau_zone="face_down",
        depth=max(0, peels - 1),
        stock_epoch=None,
        stock_column=None,
        usable_by_target=True,
        reserved_by_completed_foundation=False,
        excavation_peels=peels,
        closure_prefix_hops=0,
        helper_tasks=helpers,
        needs_temp_space=False,
        dependency_blocked=False,
        reception_status="not_applicable",
        estimated_cost=float(peels),
        note="synthetic work-footprint source",
    )


def test_helper_that_is_also_a_target_project_is_not_charged_twice():
    sources = (
        _tableau_source(7, 0, 1, ((1, 2),)),
        _tableau_source(6, 1, 3),
    )
    projects, shared, saving, aggregate = fc._merge_excavation_projects(
        sources, closures={}, deadline_epoch=0
    )
    assert {project.column for project in projects} == {0, 1}
    assert shared == ()
    assert aggregate == 4  # col0 depth1 + max(col1 direct3, helper2)
    assert saving == 2


def test_stock_receiver_deadline_is_propagated_to_tableau_parent_project():
    cards = _deal(
        tableau_required=[Card("s", rank) for rank in range(1, 14) if rank != 7]
        + [Card("s", 8)],
        forced_stock={(1, 0): Card("s", 7), (5, 0): Card("s", 7)},
    )
    state = _pad(
        [
            Column([], [Card("s", 8), Card("h", 5)]),
            Column([], [Card("s", rank) for rank in range(13, 8, -1)]),
            Column([], [Card("s", rank) for rank in range(6, 0, -1)]),
        ],
        cards[54:],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=2
    )
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert campaign.rank_need(7).chosen is not None
    assert campaign.rank_need(7).chosen.stock_epoch == 1
    assert project.deadline_epoch == 1
    assert project.deadline_before_deal
    assert all(
        not hasattr(plan, "ready_fragments_before") for plan in campaign.stock_plan
    )
    assert hasattr(campaign.stock_plan[0], "available_rank_bands_before")


def test_fill_then_deal_recovery_is_measured_from_the_concrete_action():
    columns = [Column([], [Card("h", 10), Card("h", 13)])]
    columns.extend(Column([], [Card("c", rank)]) for rank in range(1, 9))
    columns.append(Column([], []))
    state = SpiderState(
        columns,
        [Card("d", rank) for rank in range(1, 11)],
        [],
    )
    result = fc._concrete_fill_then_deal(state)
    assert result is not None
    action, regain = result
    assert state.can_move(*action)
    replay = state.clone()
    replay.move(*action)
    replay.deal()
    assert regain == fc._one_move_regain_cost(replay)


def test_normalized_opening_state_runs_as_a_four_campaign_portfolio():
    cards = _deal()
    state = SpiderState.from_cards(list(cards))
    portfolio = analyze_foundation_campaigns(state, cards=cards)
    assert len(portfolio.campaigns) == 4
    assert portfolio.primary is not None
    assert any("independent runner-up" in note.lower() for note in portfolio.notes)


def test_predeal_receiver_cannot_use_destination_arriving_in_that_same_deal():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 8)], [Card("h", 5)]),
            Column([], [Card("s", rank) for rank in range(13, 8, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        _synthetic_stock(
            {
                (1, 0): Card("s", 7),
                (1, 1): Card("d", 6),
                (2, 0): Card("s", 6),
            }
        ),
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=2
    )
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert project.deadline_epoch == 1 and project.deadline_before_deal
    assert project.blocked_dependencies
    assert any("pre-deal receiver deadline" in blocker for blocker in campaign.blockers)


def test_nested_helper_keeps_the_early_predeal_deadline():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 8)], [Card("h", 5)]),
            Column([Card("c", 6)], [Card("h", 10)]),
            Column([], [Card("s", 13), Card("s", 12)]),
            Column([], [Card("s", 10), Card("s", 9)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        _synthetic_stock(
            {
                (1, 0): Card("s", 7),
                (1, 1): Card("d", 11),
                (2, 0): Card("s", 6),
                (2, 1): Card("s", 11),
            }
        ),
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=2
    )
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert project.deadline_before_deal
    assert project.blocked_dependencies


def test_critical_path_never_schedules_work_before_current_epoch():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([], [Card("s", 6), Card("h", 9), Card("c", 7)]),
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        _synthetic_stock()[:-10],
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=1
    )
    assert campaign.current_epoch == 1
    assert all(step.epoch >= campaign.current_epoch for step in campaign.critical_path)


def test_multiple_faceup_blocker_groups_are_conditional_not_high_confidence():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([], [Card("s", 6), Card("h", 9), Card("c", 7)]),
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        _synthetic_stock(),
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    six = campaign.rank_need(6)
    assert six.chosen is not None and six.chosen.is_conditional
    assert six.chosen.reception_status == "unvalidated_tableau_peels"
    assert campaign.confidence != "HIGH"


def test_single_movable_mixed_suit_blocker_run_is_still_conditional():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([], [Card("s", 6), Card("h", 5), Card("c", 4)]),
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ],
        _synthetic_stock(),
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    six = campaign.rank_need(6)
    assert six.chosen is not None and six.chosen.is_conditional
    assert six.chosen.closure_prefix_hops == 0
    assert campaign.confidence != "HIGH"


def test_no_empty_is_not_prescribed_when_selected_prefix_needs_no_space():
    cards = _spade_complete_opening_cards()
    state = _pad(
        [
            Column([Card("s", 6)], [Card("h", 9)]),
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
            Column([], [Card("c", 10)]),
        ],
        _synthetic_stock(),
    )
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    project = next(p for p in campaign.prerequisite_excavation_projects if p.column == 0)
    assert not project.needs_temp_space
    assert campaign.space_plan.policy != SpacePolicy.CREATE_THEN_SPEND
    assert "no empty is required" in campaign.space_plan.enabled_action


def test_unproved_workspace_creation_downgrades_confidence_without_fake_cost():
    cards = _spade_complete_opening_cards()
    columns = [Column([Card("s", 6)], [Card("h", 13)])]
    columns.extend(
        [
            Column([], [Card("s", rank) for rank in range(13, 6, -1)]),
            Column([], [Card("s", rank) for rank in range(5, 0, -1)]),
        ]
    )
    while len(columns) < 10:
        columns.append(Column([Card("d", 3)], [Card("c", 13)]))
    state = SpiderState(columns, _synthetic_stock(), [])
    campaign = analyze_foundation_campaign(
        state, cards=cards, suit="s", target_epoch=0
    )
    assert campaign.space_requirement == 1
    assert campaign.space_plan.cheapest_recoverable_workspace is None
    assert campaign.space_plan.policy != SpacePolicy.CREATE_THEN_SPEND
    assert "did not prove" in campaign.space_plan.enabled_action
    assert campaign.confidence == "LOW"
