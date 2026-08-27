from __future__ import annotations

import inspect
import random
from dataclasses import replace
from pathlib import Path

import pytest

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.planner.analysis_budget import SearchDeadline
from spider.planner.campaign_corridor import (
    CampaignCorridorConfig,
    CampaignCorridorMilestone,
    CampaignCorridorMilestoneKind,
    CampaignCorridorStatus,
    build_campaign_corridor,
    compare_campaign_corridor_marginal_value,
    deduplicate_corridor_results,
    generate_campaign_corridor_lanes,
    realize_campaign_corridor,
)
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.planner.foundation_feasibility import current_stock_epoch
from spider.rules import MW_RULES
from spider.state_identity import states_structurally_equal


ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"


@pytest.fixture(scope="module")
def opening():
    cards = tuple(load_deal(DEAL))
    state = SpiderState.from_cards(cards)
    portfolio = analyze_foundation_campaigns(
        state, cards=cards, max_source_combinations=64
    )
    return cards, state, portfolio


@pytest.fixture(scope="module")
def completed_corridor(opening):
    cards, state, portfolio = opening
    return realize_campaign_corridor(
        state,
        portfolio.primary,
        cards,
        config=CampaignCorridorConfig(
            max_epoch_transitions=2,
            max_added_cost=24,
            max_nodes=30_000,
            time_limit_s=12.0,
            beam_width=256,
            max_lanes=2,
        ),
    )


def test_01_unrestricted_deal_remains_on():
    assert MW_RULES.can_deal_into_empty is True


def test_02_corridor_target_is_live_portfolio_primary(opening):
    cards, state, portfolio = opening
    lanes = generate_campaign_corridor_lanes(state, cards, portfolio=portfolio)
    assert lanes[0].corridor.identity.suit == portfolio.primary.suit
    assert lanes[0].corridor.identity.copy_index == portfolio.primary.copy_index


def test_03_production_corridor_contains_no_benchmark_constants():
    import spider.planner.campaign_corridor as module

    source = inspect.getsource(module)
    for forbidden in ("492515", "cost-23", "prefer Spades", "119", "77d169"):
        assert forbidden not in source


def test_04_corridor_records_interchangeable_physical_sources(opening):
    _cards, state, portfolio = opening
    corridor = build_campaign_corridor(
        state, portfolio.primary, config=CampaignCorridorConfig()
    )
    assert corridor.must_source_keys
    assert corridor.interchangeable_source_keys
    assert not set(corridor.must_source_keys) & set(corridor.interchangeable_source_keys)


def test_05_epoch_milestone_is_a_structural_predicate(opening):
    _cards, state, _portfolio = opening
    milestone = CampaignCorridorMilestone(
        CampaignCorridorMilestoneKind.STOCK_EPOCH_AT_LEAST,
        "reach next epoch",
        target_epoch=1,
    )
    assert not milestone.is_satisfied(state, None)
    dealt = state.clone()
    assert dealt.enumerate_moves()  # Deal does not require tableau exhaustion.
    dealt.deal(MW_RULES)
    assert milestone.is_satisfied(dealt, None)


def test_06_foundation_milestone_uses_state_not_economic_score(completed_corridor):
    result = completed_corridor
    assert result.corridor.final_milestone.is_satisfied(result.end_state, None)
    assert result.foundation_count_after == result.foundation_count_before + 1


def test_07_corridor_crosses_deal_with_legal_moves_remaining(opening, completed_corridor):
    _cards, state, _portfolio = opening
    assert state.enumerate_moves()
    assert ("deal",) in completed_corridor.actions


def test_08_corridor_does_not_require_tableau_exhaustion(completed_corridor):
    first_deal = completed_corridor.actions.index(("deal",))
    assert first_deal < len(completed_corridor.actions) - 1


def test_09_multi_epoch_marginal_value_includes_preparation_cost():
    value = compare_campaign_corridor_marginal_value(
        deal_now_total_cost=11, prepared_post_deal_cost=5, preparation_cost=3
    )
    assert value.prepared_total_cost == 8
    assert value.bounded_saving == 3


def test_10_flat_immediate_probe_does_not_invalidate_longer_corridor():
    value = compare_campaign_corridor_marginal_value(
        deal_now_total_cost=None, prepared_post_deal_cost=5, preparation_cost=3
    )
    assert not value.comparable
    assert value.proof_pruning_allowed is False


def test_11_negative_bounded_marginal_value_is_recorded():
    value = compare_campaign_corridor_marginal_value(
        deal_now_total_cost=5, prepared_post_deal_cost=2, preparation_cost=4
    )
    assert value.prepared_total_cost == 6
    assert value.bounded_saving == -1


def test_12_multiple_lanes_are_deterministic_and_bounded(opening):
    cards, state, portfolio = opening
    config = CampaignCorridorConfig(max_lanes=2)
    first = generate_campaign_corridor_lanes(state, cards, config=config, portfolio=portfolio)
    second = generate_campaign_corridor_lanes(state, cards, config=config, portfolio=portfolio)
    assert [lane.lane_id for lane in first] == [lane.lane_id for lane in second]
    assert 1 <= len(first) <= 2


def test_13_alternative_campaigns_remain_visible(completed_corridor):
    assert completed_corridor.assessment.alternatives_remaining
    assert all(
        label != completed_corridor.corridor.identity.label
        for label in completed_corridor.assessment.alternatives_remaining
    )


def test_14_exact_endpoint_dedup_keeps_lower_cost(completed_corridor):
    dearer = replace(
        completed_corridor,
        corrected_added_cost=completed_corridor.corrected_added_cost + 1,
    )
    kept = deduplicate_corridor_results((dearer, completed_corridor))
    assert len(kept) == 1
    assert kept[0].corrected_added_cost == completed_corridor.corrected_added_cost


def test_15_corridor_failure_has_no_proof_authority(opening):
    _cards, state, portfolio = opening
    corridor = build_campaign_corridor(
        state, portfolio.primary, config=CampaignCorridorConfig()
    )
    assert corridor.proof_pruning_allowed is False


def test_16_completed_corridor_independently_replays(opening, completed_corridor):
    _cards, state, _portfolio = opening
    replay = state.clone()
    cost = replay_actions(replay, list(completed_corridor.actions))
    assert cost == completed_corridor.corrected_added_cost
    assert states_structurally_equal(replay, completed_corridor.end_state)


def test_17_every_realized_step_is_revalidated(completed_corridor):
    assert len(completed_corridor.steps) == completed_corridor.deals_applied == 2
    assert all(step.revalidation in CampaignCorridorStatus for step in completed_corridor.steps)


def test_18_interchangeable_source_switch_is_explicit(completed_corridor):
    switched = any(
        step.revalidation == CampaignCorridorStatus.SWITCH_SOURCE_COPY
        for step in completed_corridor.steps
    )
    assert completed_corridor.assessment.source_copy_switched == switched


def test_19_every_selected_park_records_exit_and_rehandling(completed_corridor):
    parks = [
        item
        for step in completed_corridor.steps
        for item in step.lifecycle
        if item.placement_class.value.endswith("PARK")
    ]
    assert parks
    assert all(item.future_exit_route and item.estimated_rehandling_cost >= 0 for item in parks)
    assert all(item.proof_pruning_allowed is False for item in parks)


def test_20_unseen_deals_generate_non_hardcoded_corridors():
    primary_suits = []
    for seed in (1, 2):
        cards = [Card(suit, rank) for suit in "cdhs" for rank in range(1, 14) for _ in range(2)]
        random.Random(seed).shuffle(cards)
        frozen = tuple(cards)
        state = SpiderState.from_cards(frozen)
        lanes = generate_campaign_corridor_lanes(state, frozen)
        assert lanes
        primary_suits.append(lanes[0].corridor.identity.suit)
        assert current_stock_epoch(state, 5) == 0
    assert len(set(primary_suits)) == 2
