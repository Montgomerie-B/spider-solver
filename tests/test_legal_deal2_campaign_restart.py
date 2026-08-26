"""Focused gates for the corrected legal Deal-2 campaign restart."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import replay_actions
from spider.move_lifecycle import PlacementClass
from spider.planner import foundation_campaign_removal as removal
from spider.planner.diagnostics import legal_deal2_campaign_restart_report as report
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    campaign_removal_obligations,
)
from spider.planner.stock_reception import next_stock_row
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="module")
def frozen():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    return cards, report.freeze_experiment(cards)


def _assert_route_multicard_same_suit(start: SpiderState, actions) -> None:
    state = start.clone()
    for action in actions:
        if action == ("deal",):
            state.deal()
            continue
        src, dst, k = action
        run = state.columns[src].face_up[-k:]
        if k > 1:
            assert SpiderState.is_movable_run(run)
        state.move(src, dst, k)


def test_preferred_six_move_opening_is_legal_under_corrected_rules(frozen):
    _cards, experiment = frozen
    arm = experiment.preferred
    checked = arm.opening_state.clone()
    assert replay_actions(checked, list(report.PREFERRED_B_OPENING)) == 6
    assert states_structurally_equal(checked, arm.six_move_state)
    _assert_route_multicard_same_suit(arm.opening_state, report.PREFERRED_B_OPENING)


def test_preferred_qc_to_kc_is_stable_same_suit_structure(frozen):
    _cards, experiment = frozen
    record = next(
        item
        for item in experiment.preferred.opening_variant_lifecycle.records
        if item.action_index == 4
    )
    assert record.assessment.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert record.assessment.same_suit_joins_created == ("Kc-Qc@c5",)


def test_control_queen_placements_have_greater_lifecycle_debt(frozen):
    _cards, experiment = frozen
    preferred = experiment.preferred.opening_variant_lifecycle
    control = experiment.control.opening_variant_lifecycle
    assert preferred.immediate_cost == control.immediate_cost == 3
    assert preferred.stable_joins_created == 2
    assert control.stable_joins_created == 1
    assert preferred.mixed_boundaries_created == 1
    assert control.mixed_boundaries_created == 2
    assert preferred.estimated_rehandling_debt == 1
    assert control.estimated_rehandling_debt == 2


def test_both_openings_independently_replay(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        state = SpiderState.from_cards(list(_cards))
        assert replay_actions(state, list(arm.opening_actions)) == 6
        assert states_structurally_equal(state, arm.six_move_state)


def test_deal1_realizer_emits_only_legal_same_suit_blocks(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        assert arm.deal1.independent_replay_verified
        _assert_route_multicard_same_suit(arm.six_move_state, arm.deal1.actions)


def test_post_deal1_reconstruction_is_deterministic(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        checked = arm.six_move_state.clone()
        assert replay_actions(checked, list(arm.deal1.actions)) == 5
        assert states_structurally_equal(checked, arm.post_deal1)


def test_campaign_portfolio_reanalysis_is_deterministic(frozen):
    cards, experiment = frozen
    arm = experiment.preferred
    again = analyze_foundation_campaigns(arm.post_deal1, cards=cards)
    observed = [
        (
            campaign.label,
            campaign.target_removal_epoch,
            campaign.campaign_score,
            campaign.estimated_campaign_cost,
        )
        for campaign in arm.post_deal1_portfolio.campaigns
    ]
    repeated = [
        (
            campaign.label,
            campaign.target_removal_epoch,
            campaign.campaign_score,
            campaign.estimated_campaign_cost,
        )
        for campaign in again.campaigns
    ]
    assert repeated == observed
    assert again.primary is not None and again.primary.label == "S#1"


def test_invalid_historical_post_command14_fixture_is_not_used():
    source = inspect.getsource(report)
    assert "(7, 6, 2)" not in source
    assert "move 8 7 2" not in source.lower()


def test_deal2_obligations_are_derived_from_current_state(frozen):
    cards, experiment = frozen
    arm = experiment.preferred
    assert arm.obligations == campaign_removal_obligations(
        arm.post_deal1, arm.campaign, cards
    )
    assert any("assemble a movable 12-8s band" in item.description for item in arm.obligations)
    assert any("assemble a movable 6-2s band" in item.description for item in arm.obligations)


def test_exact_next_row_comes_from_deal_data(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        assert arm.best.exact_row == next_stock_row(arm.post_deal1)
        assert tuple(arm.post_deal1.stock[-10:]) == arm.best.exact_row


def test_every_generated_multicard_move_is_same_suit(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        _assert_route_multicard_same_suit(arm.opening_state, arm.full_actions)


def test_no_deal3_occurs(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        assert arm.full_actions.count(("deal",)) == 2
        assert len(arm.best.end_state.stock) == 30


def test_foundation_removal_verifies_suit_and_count(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        assert arm.best.status == CampaignRemovalStatus.FOUNDATION_REMOVED
        assert arm.best.foundation_count_after == arm.best.foundation_count_before + 1
        assert arm.best.foundation_suits_added == ("s",)


def test_successful_route_replays_at_equal_corrected_cost(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        replayed = arm.opening_state.clone()
        assert replay_actions(replayed, list(arm.full_actions)) == arm.total_cost == 23
        assert states_structurally_equal(replayed, arm.best.end_state)
        assert arm.independent_replay_verified


def test_bounded_miss_is_not_impossibility(frozen):
    _cards, experiment = frozen
    for arm in (experiment.preferred, experiment.control):
        bound, result = arm.bound_results[0]
        assert bound == 8
        assert result.status in (
            CampaignRemovalStatus.PARTIAL,
            CampaignRemovalStatus.NOT_FOUND_WITHIN_BOUND,
            CampaignRemovalStatus.RESOURCE_LIMIT,
        )
        assert "impossibility" in result.stop_reason.lower()


def test_production_strategy_contains_no_benchmark_move_constants():
    source = inspect.getsource(removal).lower()
    for token in (
        "4925153",
        "move 8 7 2",
        "(7, 6, 2)",
        "qc -> kc",
        "canonical.moves",
    ):
        assert token not in source


def test_lifecycle_debt_is_ordering_only_never_proof_pruning():
    source = inspect.getsource(removal)
    assert "lifecycle_key" in source
    assert "proof_pruning_allowed" not in source
    assert "never rejects a successor" in source
    assert all(
        not record.assessment.proof_pruning_allowed
        for actions in (report.PREFERRED_B_OPENING, report.CONTROL_A_OPENING)
        for record in report._route_lifecycle(
            SpiderState.from_cards(
                list(load_deal(ROOT / "deals" / "4925153.txt"))
            ),
            actions,
        ).records
    )


def test_control_resources_are_comparable_and_b_freezes_first(frozen):
    _cards, experiment = frozen
    assert experiment.preferred.prospective_frozen
    assert experiment.control.prospective_frozen
    assert experiment.preferred.resources == experiment.control.resources
    assert [bound for bound, _result in experiment.preferred.bound_results] == [8, 12]
    assert [bound for bound, _result in experiment.control.bound_results] == [8, 12]
    assert not experiment.canonical_loaded
