"""Focused tests for recursive residual-campaign continuation."""

from __future__ import annotations

import inspect
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.planner import foundation_campaign_removal as fcrm
from spider.planner import foundation_campaign_transition as fct
from spider.planner.diagnostics import residual_campaign_continuation_report as report
from spider.planner.diagnostics.residual_campaign_continuation_report import (
    reconstruct_cost47,
    same_campaign_remains_primary,
)
from spider.planner.foundation_campaign import analyze_foundation_campaigns
from spider.planner.foundation_campaign_removal import (
    CampaignTableauSearchResult,
    locate_campaign_bands,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionObligationKind,
    CampaignTransitionStatus,
    campaign_transition_obligations,
    realize_residual_campaign_transition,
    transition_obligation_is_satisfied,
)
from spider.state_identity import states_structurally_equal


@pytest.fixture(scope="module")
def benchmark():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    reconstructed = reconstruct_cost47(cards)
    result = realize_residual_campaign_transition(
        reconstructed.state,
        reconstructed.campaign,
        cards,
        max_added_cost=6,
        max_nodes=100_000,
        time_limit_s=35,
        beam_width=512,
    )
    return cards, reconstructed, result


def _foundation(suit: str):
    return [Card(suit, rank) for rank in range(13, 0, -1)]


def _removal_state():
    columns = [
        Column([], [Card("h", rank) for rank in range(13, 1, -1)]),
        Column([], [Card("h", 1)]),
    ]
    columns.extend(Column([], [Card("c", 9)]) for _ in range(8))
    return SpiderState(
        columns,
        [Card("d", 4) for _ in range(30)],
        [_foundation("s")],
    )


def test_cost47_state_reconstructs_through_public_apis(benchmark):
    _cards, reconstructed, _result = benchmark
    assert reconstructed.total_cost == 47
    assert reconstructed.actions.count(("deal",)) == 2
    assert len(reconstructed.state.stock) == 30
    assert len(reconstructed.state.foundations) == 1
    assert tuple(sequence[0].suit for sequence in reconstructed.state.foundations) == ("s",)
    assert sum(len(column.face_down) for column in reconstructed.state.columns) == 21
    assert reconstructed.replay_verified


def test_second_portfolio_analysis_is_deterministic(benchmark):
    cards, reconstructed, _result = benchmark
    again = analyze_foundation_campaigns(reconstructed.state, cards=cards)
    facts = lambda portfolio: tuple(
        (
            campaign.label,
            campaign.target_removal_epoch,
            campaign.estimated_campaign_cost,
            campaign.campaign_score,
        )
        for campaign in portfolio.campaigns
    )
    assert facts(again) == facts(reconstructed.portfolio)


def test_continuation_requires_same_primary(benchmark, monkeypatch):
    cards, reconstructed, _result = benchmark
    assert same_campaign_remains_primary(
        reconstructed.advanced_identity, reconstructed.portfolio
    )
    changed_primary = reconstructed.portfolio.secondary
    assert changed_primary is not None
    changed = replace(
        reconstructed.portfolio,
        primary=changed_primary,
    )
    assert not same_campaign_remains_primary(reconstructed.advanced_identity, changed)
    changed_reconstruction = replace(
        reconstructed,
        portfolio=changed,
        campaign=changed_primary,
    )
    monkeypatch.setattr(report, "reconstruct_cost47", lambda _cards: changed_reconstruction)
    monkeypatch.setattr(
        report,
        "realize_residual_campaign_transition",
        lambda *_args, **_kwargs: pytest.fail("changed primary must not be forced"),
    )
    frozen = report.freeze_prospective(cards)
    assert frozen.verdict == "PARTIAL"
    assert frozen.bounds == ()
    assert frozen.best is None


def test_fixed_identity_persists_through_continuation(benchmark):
    _cards, reconstructed, result = benchmark
    assert result.identity == reconstructed.advanced_identity
    assert result.campaign_after is not None
    assert result.campaign_after.label == reconstructed.campaign.label
    assert result.campaign_after.target_removal_epoch == reconstructed.campaign.target_removal_epoch


def test_existing_bands_are_rediscovered_structurally(benchmark):
    _cards, reconstructed, _result = benchmark
    bands = locate_campaign_bands(reconstructed.state, reconstructed.campaign)
    intervals = {(band.high_rank, band.low_rank, band.movable) for band in bands}
    assert (13, 12, True) in intervals
    assert (8, 4, True) in intervals
    assert (2, 1, True) in intervals
    assert (10, 10, True) in intervals
    assert (6, 6, True) in intervals


def test_contiguous_bands_are_not_duplicate_rank_obligations(benchmark):
    cards, reconstructed, _result = benchmark
    obligations = campaign_transition_obligations(
        reconstructed.state, reconstructed.campaign, cards
    )
    exposed = [
        obligation
        for obligation in obligations
        if obligation.kind == CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE
    ]
    preserved = [
        obligation
        for obligation in obligations
        if obligation.kind == CampaignTransitionObligationKind.PRESERVE_CAMPAIGN_FRAGMENT
    ]
    assert {obligation.rank for obligation in exposed} == {
        source.card.rank for source in reconstructed.campaign.tableau_critical_cards
    }
    assert len(exposed) == 3
    assert {(item.high_rank, item.low_rank) for item in preserved} == {
        (13, 12),
        (8, 4),
        (2, 1),
    }


def test_equivalent_physical_source_substitution_remains_legal(benchmark):
    cards, reconstructed, _result = benchmark
    obligation = next(
        item
        for item in campaign_transition_obligations(
            reconstructed.state, reconstructed.campaign, cards
        )
        if item.kind == CampaignTransitionObligationKind.EXPOSE_SELECTED_SOURCE
    )
    alternate = SpiderState(
        [Column([], [Card(reconstructed.campaign.suit, obligation.rank)])]
        + [Column([], [Card("c", 9)]) for _ in range(9)],
        [Card("d", 4) for _ in range(30)],
        [_foundation("s")],
    )
    assert transition_obligation_is_satisfied(
        alternate,
        reconstructed.campaign,
        obligation,
        start_epoch=2,
        foundation_suit_before=0,
    )


def test_no_stock_deal_occurs_during_continuation(benchmark):
    _cards, reconstructed, result = benchmark
    assert result.deals_applied == 0
    assert ("deal",) not in result.actions
    assert len(result.resulting_state.stock) == len(reconstructed.state.stock) == 30


def test_automatic_second_foundation_removal_is_detected(benchmark, monkeypatch):
    cards, reconstructed, _result = benchmark
    state = _removal_state()
    portfolio = replace(
        reconstructed.portfolio,
        current_epoch=2,
        campaigns=(reconstructed.campaign,),
        primary=reconstructed.campaign,
        secondary=None,
        deferred=(),
    )
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    removed = realize_residual_campaign_transition(
        state,
        reconstructed.campaign,
        cards,
        max_added_cost=2,
        max_nodes=100,
        time_limit_s=2,
        beam_width=32,
    )
    assert removed.status == CampaignTransitionStatus.FOUNDATION_REMOVED
    assert removed.action_roles[-1] == "removal-trigger"
    assert removed.foundation_count_before == 1
    assert removed.foundation_count_after == 2
    assert removed.foundation_suits_added == (reconstructed.campaign.suit,)
    assert removed.deals_applied == 0


def test_complete_route_replays_at_equal_corrected_cost(benchmark):
    _cards, reconstructed, result = benchmark
    actions = reconstructed.actions + result.actions
    replayed = reconstructed.opening.clone()
    assert replay_actions(replayed, list(actions)) == 47 + result.corrected_added_cost
    assert states_structurally_equal(replayed, result.resulting_state)


def test_bounded_resource_failure_is_not_impossibility(benchmark, monkeypatch):
    cards, reconstructed, _result = benchmark
    state = reconstructed.state
    portfolio = reconstructed.portfolio
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    monkeypatch.setattr(
        fct,
        "_fixed_reanalysis",
        lambda *_a, **_k: reconstructed.campaign,
    )
    monkeypatch.setattr(
        fct,
        "search_campaign_tableau",
        lambda *_a, **_k: CampaignTableauSearchResult(
            False,
            (),
            0,
            state.clone(),
            1,
            0.01,
            True,
            "node limit; bounded miss is not impossibility",
        ),
    )
    result = realize_residual_campaign_transition(
        state,
        reconstructed.campaign,
        cards,
        max_added_cost=1,
        max_nodes=1,
    )
    assert result.status == CampaignTransitionStatus.RESOURCE_LIMIT
    assert "not impossibility" in result.stop_reason


def test_campaign_advancement_is_not_removal_success(benchmark):
    _cards, _reconstructed, result = benchmark
    assert result.status != CampaignTransitionStatus.FOUNDATION_REMOVED
    assert result.foundation_count_before == result.foundation_count_after == 1


def test_generic_production_code_has_no_benchmark_constants():
    source = (inspect.getsource(fct) + inspect.getsource(fcrm)).lower()
    for token in (
        "4925153",
        "canonical.moves",
        "move 3 1 2",
        "column 2",
        "column 5",
        "column 10",
        "hearts",
        "cost-47",
        "47-move",
    ):
        assert token not in source
