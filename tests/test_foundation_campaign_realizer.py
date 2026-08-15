"""Focused tests for bounded foundation-campaign realisation."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import foundation_campaign_realizer as fcr
from spider.planner.foundation_campaign import (
    RankSourceKind,
    analyze_foundation_campaign,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignObligationKind,
    CampaignRealizationStatus,
    campaign_obligations_for_next_epoch,
    campaign_target_prefix_closure,
    obligation_is_satisfied,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.planner.space_lifecycle import empty_columns
from spider.state_identity import states_structurally_equal


PREFIX_ACTIONS = (
    (5, 7, 1),
    (5, 2, 1),
    (5, 2, 1),
    (5, 1, 1),
    (5, 4, 1),
    (2, 7, 3),
)


@pytest.fixture(scope="module")
def benchmark():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    state = SpiderState.from_cards(list(cards))
    assert replay_actions(state, list(PREFIX_ACTIONS)) == 6
    portfolio = analyze_foundation_campaigns(state, cards=cards)
    campaign = portfolio.primary
    assert campaign is not None
    result = realize_campaign_to_next_epoch(
        state,
        campaign,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20.0,
    )
    return cards, state, portfolio, campaign, result


def _remap_state(state: SpiderState, mapping: dict[str, str]) -> SpiderState:
    def remap(card: Card) -> Card:
        return Card(mapping.get(card.suit, card.suit), card.rank)

    return SpiderState(
        [
            Column(
                [remap(card) for card in column.face_down],
                [remap(card) for card in column.face_up],
            )
            for column in state.columns
        ],
        [remap(card) for card in state.stock],
        [[remap(card) for card in sequence] for sequence in state.foundations],
    )


def test_benchmark_start_fixture_is_exact(benchmark):
    _cards, state, _portfolio, campaign, _result = benchmark
    assert empty_columns(state) == (5,)
    assert [str(card) for card in state.columns[7].face_up[-5:]] == [
        "6s",
        "5s",
        "4s",
        "3s",
        "2s",
    ]
    assert campaign.target_removal_epoch == 2


def test_next_epoch_obligations_derive_from_campaign(benchmark):
    cards, state, _portfolio, campaign, _result = benchmark
    obligations = campaign_obligations_for_next_epoch(state, campaign, cards)
    must_ranks = {
        obligation.rank
        for obligation in obligations
        if obligation.kind == CampaignObligationKind.EXCAVATE_PREFIX
    }
    assert must_ranks == {source.card.rank for source in campaign.tableau_critical_cards}
    assert any(o.kind == CampaignObligationKind.APPLY_DEAL for o in obligations)
    assert any(o.kind == CampaignObligationKind.VERIFY_POST_DEAL for o in obligations)


def test_fixed_campaign_identity_persists(benchmark):
    _cards, _state, _portfolio, campaign, result = benchmark
    assert result.status == CampaignRealizationStatus.FOUND
    assert result.identity.suit == campaign.suit
    assert result.identity.copy_index == campaign.copy_index
    assert result.identity.target_epoch == campaign.target_removal_epoch
    assert result.campaign_after is not None
    assert result.campaign_after.suit == campaign.suit
    assert result.campaign_after.copy_index == campaign.copy_index
    assert result.campaign_after.target_removal_epoch == campaign.target_removal_epoch


def test_interchangeable_source_substitution_is_permitted(benchmark):
    cards, state, _portfolio, campaign, result = benchmark
    old = campaign.rank_need(10).chosen
    assert old is not None and old.kind != RankSourceKind.ALREADY_USABLE
    exposed = state.clone()
    replay_actions(exposed, list(result.actions[:2]))
    reanalysed = analyze_foundation_campaign(
        exposed,
        cards=cards,
        suit=campaign.suit,
        copy_index=campaign.copy_index,
        target_epoch=campaign.target_removal_epoch,
    )
    new = reanalysed.rank_need(10).chosen
    assert new is not None and new.kind == RankSourceKind.ALREADY_USABLE
    assert new.source_key != old.source_key


def test_target_relative_prefix_is_precise(benchmark):
    _cards, state, _portfolio, campaign, _result = benchmark
    rank = campaign.tableau_critical_cards[0].card.rank
    prefix = campaign_target_prefix_closure(state, campaign, rank)
    assert prefix.source_column == campaign.tableau_critical_cards[0].column
    assert prefix.required_reveals == 2
    assert prefix.max_face_down == len(state.columns[prefix.source_column].face_down) - 2
    assert len(prefix.destination_prerequisites) == prefix.required_reveals
    assert prefix.selected_source_key in prefix.interchangeable_source_keys


def test_auxiliary_destination_preparation_moves_are_allowed(benchmark):
    cards, state, _portfolio, campaign, _result = benchmark
    prepared = state.clone()
    # Generic legal perturbation: spend the empty, then place a receiver on the
    # critical column.  The target can only progress after another column moves.
    replay_actions(prepared, [(6, 5, 1), (8, 6, 1)])
    altered = analyze_foundation_campaign(
        prepared,
        cards=cards,
        suit=campaign.suit,
        copy_index=campaign.copy_index,
        target_epoch=campaign.target_removal_epoch,
    )
    target_col = altered.tableau_critical_cards[0].column
    result = realize_campaign_to_next_epoch(
        prepared, altered, cards, max_added_cost=6, max_nodes=50_000, time_limit_s=10
    )
    assert result.status == CampaignRealizationStatus.FOUND
    assert any(
        action != ("deal",) and action[0] != target_col
        for action in result.actions[:-1]
    )


def test_workspace_is_spent_and_regenerated(benchmark):
    _cards, _state, _portfolio, _campaign, result = benchmark
    phases = {progress.phase: progress for progress in result.progress}
    assert phases["initial"].empty_columns
    assert not phases["excavation"].empty_columns
    assert phases["workspace"].empty_columns
    assert any("-> ()" in event for event in result.workspace_events)
    assert any("() ->" in event for event in result.workspace_events)


def test_receiver_predicate_is_machine_testable(benchmark):
    cards, state, _portfolio, campaign, result = benchmark
    obligations = campaign_obligations_for_next_epoch(state, campaign, cards)
    receiver_obligations = [
        obligation
        for obligation in obligations
        if obligation.kind == CampaignObligationKind.SHAPE_RECEIVER
    ]
    assert receiver_obligations
    predeal = state.clone()
    replay_actions(predeal, list(result.actions[:-1]))
    updated = analyze_foundation_campaign(
        predeal,
        cards=cards,
        suit=campaign.suit,
        copy_index=campaign.copy_index,
        target_epoch=campaign.target_removal_epoch,
    )
    assert all(
        isinstance(obligation_is_satisfied(predeal, updated, obligation), bool)
        for obligation in receiver_obligations
    )
    assert all(
        obligation.obligation_id in result.receiver_conditions_satisfied
        for obligation in receiver_obligations
    )


def test_suit_permuted_campaign_reaches_stock_epoch(benchmark):
    cards, state, _portfolio, campaign, _result = benchmark
    mapping = {"s": "h", "h": "s"}
    remapped_state = _remap_state(state, mapping)
    remapped_cards = tuple(
        Card(mapping.get(card.suit, card.suit), card.rank) for card in cards
    )
    remapped = analyze_foundation_campaign(
        remapped_state,
        cards=remapped_cards,
        suit=mapping[campaign.suit],
        copy_index=campaign.copy_index,
        target_epoch=campaign.target_removal_epoch,
    )
    result = realize_campaign_to_next_epoch(
        remapped_state,
        remapped,
        remapped_cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    assert result.status == CampaignRealizationStatus.FOUND
    assert result.identity.suit == "h"
    assert current_stock_epoch(result.resulting_state, 5) == 1


def test_deal_is_applied_only_after_mandatory_work(benchmark):
    _cards, _state, _portfolio, _campaign, result = benchmark
    assert result.actions[-1] == ("deal",)
    assert ("deal",) not in result.actions[:-1]
    predeal = next(progress for progress in result.progress if progress.phase == "pre_deal")
    mandatory_ids = {
        obligation.obligation_id
        for obligation in result.obligations_initial
        if obligation.mandatory_before_deal
    }
    assert mandatory_ids.issubset(predeal.satisfied)


def test_complete_route_independently_replays_at_same_cost(benchmark):
    _cards, state, _portfolio, _campaign, result = benchmark
    checked = state.clone()
    assert replay_actions(checked, list(result.actions)) == result.corrected_added_cost
    assert result.independent_replay_verified
    assert states_structurally_equal(checked, result.resulting_state)


def test_exact_row_uses_engine_column_mapping(benchmark):
    _cards, state, _portfolio, _campaign, result = benchmark
    assert result.exact_row == tuple(state.stock[-10:])
    predeal = state.clone()
    replay_actions(predeal, list(result.actions[:-1]))
    post = result.resulting_state
    for column, card in enumerate(result.exact_row):
        assert post.columns[column].face_up[len(predeal.columns[column].face_up)] == card


def test_bounded_failure_is_not_impossibility(benchmark):
    cards, state, _portfolio, campaign, _result = benchmark
    result = realize_campaign_to_next_epoch(
        state, campaign, cards, max_added_cost=0, max_nodes=10, time_limit_s=0.1
    )
    assert result.status in (
        CampaignRealizationStatus.NOT_FOUND_WITHIN_BOUND,
        CampaignRealizationStatus.PARTIAL,
        CampaignRealizationStatus.RESOURCE_LIMIT,
    )
    assert "impossible" not in result.stop_reason.lower()


def test_resource_failure_is_not_impossibility(benchmark):
    cards, state, _portfolio, campaign, _result = benchmark
    result = realize_campaign_to_next_epoch(
        state, campaign, cards, max_added_cost=6, max_nodes=1, time_limit_s=1.0
    )
    assert result.status == CampaignRealizationStatus.RESOURCE_LIMIT
    assert "miss != impossible" in result.stop_reason.lower()


def test_generic_module_contains_no_benchmark_constants():
    source = inspect.getsource(fcr).lower()
    for token in (
        "4925153",
        "77d169da",
        "column 7",
        "10s",
        "(6, 8, 1)",
        "leaderboard",
        "canonical.moves",
    ):
        assert token not in source
