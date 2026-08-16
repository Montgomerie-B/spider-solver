"""Focused tests for fixed-campaign realisation through foundation removal."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner import foundation_campaign_removal as fcrm
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.planner.foundation_campaign_realizer import (
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalObligationKind,
    CampaignRemovalStatus,
    bands_can_join,
    campaign_band_recovery,
    campaign_interval_exists,
    campaign_removal_obligations,
    campaign_receiver_conditions,
    locate_campaign_bands,
    realize_campaign_to_removal_epoch,
)
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.state_identity import states_structurally_equal


SIX_MOVE_FIXTURE = (
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
    opening = SpiderState.from_cards(list(cards))
    six = opening.clone()
    assert replay_actions(six, list(SIX_MOVE_FIXTURE)) == 6
    initial = analyze_foundation_campaigns(six, cards=cards)
    deal1 = realize_campaign_to_next_epoch(
        six,
        initial.primary,
        cards,
        max_added_cost=6,
        max_nodes=50_000,
        time_limit_s=20,
    )
    assert deal1.status == CampaignRealizationStatus.FOUND
    post_deal1 = deal1.resulting_state
    portfolio = analyze_foundation_campaigns(post_deal1, cards=cards)
    campaign = portfolio.primary
    assert campaign is not None
    result = realize_campaign_to_removal_epoch(
        post_deal1,
        campaign,
        cards,
        max_added_cost=12,
        max_nodes=80_000,
        time_limit_s=30,
        beam_width=256,
    )
    return cards, opening, six, deal1, post_deal1, portfolio, campaign, result


def test_fixed_identity_survives_both_deals(benchmark):
    _cards, _opening, _six, deal1, post1, _portfolio, campaign, result = benchmark
    assert deal1.campaign_after is not None
    assert result.identity.suit == campaign.suit == deal1.identity.suit
    assert result.identity.copy_index == campaign.copy_index == 1
    assert result.identity.target_epoch == campaign.target_removal_epoch == 2
    assert current_stock_epoch(post1, 5) == 1
    assert current_stock_epoch(result.end_state, 5) == 2


def test_received_stock_produces_explicit_join_obligations(benchmark):
    cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    obligations = campaign_removal_obligations(post1, campaign, cards)
    joins = [
        obligation
        for obligation in obligations
        if obligation.kind == CampaignRemovalObligationKind.JOIN_RECEIVED_STOCK
    ]
    assert len(joins) >= 2
    assert all(obligation.source_columns for obligation in joins)


def test_campaign_band_detection_is_exact(benchmark):
    _cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    bands = locate_campaign_bands(post1, campaign)
    assert all(
        [card.rank for card in band.cards]
        == list(range(band.high_rank, band.low_rank - 1, -1))
        for band in bands
    )
    assert all(all(card.suit == campaign.suit for card in band.cards) for band in bands)
    assert any(band.length >= 5 and band.covered for band in bands)


def test_covered_band_is_one_structural_project(benchmark):
    cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    lower = max(locate_campaign_bands(post1, campaign), key=lambda band: band.length)
    recovery = campaign_band_recovery(lower)
    assert lower.covered and recovery.covering_groups == 1
    obligations = campaign_removal_obligations(post1, campaign, cards)
    preserves = [
        obligation
        for obligation in obligations
        if obligation.kind
        == CampaignRemovalObligationKind.PRESERVE_CAMPAIGN_FRAGMENT
        and obligation.high_rank == lower.high_rank
        and obligation.low_rank == lower.low_rank
    ]
    assert len(preserves) == 1


def test_two_compatible_bands_have_a_legal_join(benchmark):
    _cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    bands = locate_campaign_bands(post1, campaign)
    pair = next(
        (upper, lower)
        for upper in bands
        for lower in bands
        if bands_can_join(upper, lower)
    )
    upper, lower = pair
    assert post1.can_move(lower.column, upper.column, lower.length)


def test_deal2_receivers_derive_from_exact_next_row(benchmark):
    _cards, _opening, _six, _deal1, post1, _portfolio, campaign, result = benchmark
    assert result.exact_row == tuple(post1.stock[-10:])
    conditions = campaign_receiver_conditions(post1, campaign)
    selected = {
        (incoming.card, incoming.column)
        for plan in campaign.stock_plan
        if plan.epoch == campaign.target_removal_epoch
        for incoming in plan.incoming
        if incoming.selected_source and incoming.card.suit == campaign.suit
    }
    assert {(item.incoming_card, item.incoming_column) for item in conditions} == selected


def test_equivalent_receiver_geometry_is_accepted(benchmark):
    _cards, _opening, _six, _deal1, _post1, _portfolio, _campaign, result = benchmark
    assert result.pre_deal_state is not None
    assert any(condition.direct for condition in result.receiver_conditions)
    equivalent = [
        condition
        for condition in result.receiver_conditions
        if condition.bounded_walkoff
    ]
    assert equivalent
    assert all(condition.walkoff_actions for condition in equivalent)


def test_workspace_can_be_consumed_and_regenerated(benchmark):
    _cards, _opening, _six, deal1, _post1, _portfolio, _campaign, _result = benchmark
    phases = {progress.phase: progress for progress in deal1.progress}
    assert phases["initial"].empty_columns
    assert not phases["excavation"].empty_columns
    assert phases["workspace"].empty_columns


def test_deal2_waits_for_mandatory_predeal_obligations(benchmark):
    _cards, _opening, _six, _deal1, _post1, _portfolio, _campaign, result = benchmark
    deal_index = result.actions.index(("deal",))
    assert deal_index > 0
    pre = next(progress for progress in result.progress if progress.phase == "pre_deal")
    mandatory_pre = {
        obligation.obligation_id
        for obligation in result.obligations
        if obligation.mandatory and obligation.phase == "pre_deal"
    }
    assert mandatory_pre.issubset(pre.obligations_satisfied)


def test_postdeal_join_obligations_are_generated(benchmark):
    _cards, _opening, _six, _deal1, _post1, _portfolio, _campaign, result = benchmark
    kinds = {obligation.kind for obligation in result.obligations}
    assert CampaignRemovalObligationKind.CONNECT_CAMPAIGN_BANDS in kinds
    assert CampaignRemovalObligationKind.REMOVE_FOUNDATION in kinds
    assert CampaignRemovalObligationKind.VERIFY_FOUNDATION_REMOVAL in kinds


def test_q_to_a_band_exists_before_removal_trigger(benchmark):
    _cards, _opening, _six, _deal1, post1, _portfolio, campaign, result = benchmark
    before_final = post1.clone()
    replay_actions(before_final, list(result.actions[:-1]))
    assert campaign_interval_exists(before_final, campaign.suit, 12, 1, movable=True)
    assert len(before_final.foundations) == result.foundation_count_before


def test_automatic_foundation_removal_is_detected(benchmark):
    _cards, _opening, _six, _deal1, _post1, _portfolio, campaign, result = benchmark
    assert result.status == CampaignRemovalStatus.FOUNDATION_REMOVED
    assert result.action_roles[-1] == "removal-trigger"
    assert result.foundation_count_after == result.foundation_count_before + 1
    assert result.foundation_suits_added == (campaign.suit,)


def test_complete_route_replays_with_identical_cost(benchmark):
    _cards, _opening, _six, _deal1, post1, _portfolio, _campaign, result = benchmark
    replayed = post1.clone()
    assert replay_actions(replayed, list(result.actions)) == result.corrected_added_cost
    assert result.independent_replay_verified
    assert states_structurally_equal(replayed, result.end_state)


def test_true_opening_replay_has_two_deals_and_no_third(benchmark):
    _cards, opening, _six, deal1, _post1, _portfolio, _campaign, result = benchmark
    actions = SIX_MOVE_FIXTURE + deal1.actions + result.actions
    assert sum(1 for action in actions if action == ("deal",)) == 2
    replayed = opening.clone()
    total = replay_actions(replayed, list(actions))
    assert total == 6 + deal1.corrected_added_cost + result.corrected_added_cost
    assert len(replayed.stock) == 30
    assert states_structurally_equal(replayed, result.end_state)


def test_bounded_failure_is_not_impossibility(benchmark):
    cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    result = realize_campaign_to_removal_epoch(
        post1,
        campaign,
        cards,
        max_added_cost=0,
        max_nodes=20,
        time_limit_s=0.2,
        beam_width=16,
    )
    assert result.status in (
        CampaignRemovalStatus.NOT_FOUND_WITHIN_BOUND,
        CampaignRemovalStatus.PARTIAL,
        CampaignRemovalStatus.RESOURCE_LIMIT,
    )
    assert "impossibility" in result.stop_reason.lower() or result.status == CampaignRemovalStatus.PARTIAL


def test_resource_failure_is_not_impossibility(benchmark):
    cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    result = realize_campaign_to_removal_epoch(
        post1,
        campaign,
        cards,
        max_added_cost=12,
        max_nodes=1,
        time_limit_s=1.0,
        beam_width=8,
    )
    assert result.status == CampaignRemovalStatus.RESOURCE_LIMIT
    assert "not impossibility" in result.stop_reason.lower()


def test_non_next_epoch_campaign_is_invalid(benchmark):
    cards, _opening, _six, _deal1, post1, _portfolio, campaign, _result = benchmark
    invalid = replace(campaign, target_removal_epoch=campaign.target_removal_epoch + 1)
    result = realize_campaign_to_removal_epoch(post1, invalid, cards)
    assert result.status == CampaignRemovalStatus.INVALID_CAMPAIGN
    assert not result.actions


def test_production_module_has_no_benchmark_constants():
    source = inspect.getsource(fcrm).lower()
    for token in (
        "4925153",
        "column 7",
        "10s",
        "(6, 0, 2)",
        "canonical.moves",
        "leaderboard",
    ):
        assert token not in source
