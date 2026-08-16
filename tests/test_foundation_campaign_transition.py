"""Focused tests for a bounded post-primary campaign transition."""

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
from spider.planner.foundation_campaign import (
    CampaignEpochPlan,
    CampaignIncomingCard,
    FoundationCampaignPortfolio,
    RankSourceKind,
    SpacePolicy,
    analyze_foundation_campaigns,
)
from spider.planner.foundation_campaign_realizer import (
    CampaignRealizationStatus,
    realize_campaign_to_next_epoch,
)
from spider.planner.foundation_campaign_removal import (
    CampaignRemovalStatus,
    CampaignTableauSearchResult,
    CampaignTableauTarget,
    realize_campaign_to_removal_epoch,
    search_campaign_tableau,
)
from spider.planner.foundation_campaign_transition import (
    CampaignTransitionMode,
    CampaignTransitionObligationKind,
    CampaignTransitionStatus,
    audit_residual_state,
    campaign_transition_obligations,
    derive_transition_mode,
    realize_residual_campaign_transition,
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
    pytest.xfail(
        "historical Deal-2 S-removal benchmark is invalid under same-suit "
        "multi-card legality; see docs/same_suit_block_legality_audit.md"
    )
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
    post1 = analyze_foundation_campaigns(deal1.resulting_state, cards=cards)
    first = realize_campaign_to_removal_epoch(
        deal1.resulting_state,
        post1.primary,
        cards,
        max_added_cost=12,
        max_nodes=80_000,
        time_limit_s=30,
        beam_width=256,
    )
    assert first.status == CampaignRemovalStatus.FOUNDATION_REMOVED
    residual = first.end_state
    portfolio = analyze_foundation_campaigns(residual, cards=cards)
    transition = realize_residual_campaign_transition(
        residual,
        portfolio.primary,
        cards,
        max_added_cost=8,
        max_nodes=80_000,
        time_limit_s=20,
        beam_width=256,
    )
    return {
        "cards": cards,
        "opening": opening,
        "six": six,
        "deal1": deal1,
        "first": first,
        "residual": residual,
        "portfolio": portfolio,
        "primary": portfolio.primary,
        "transition": transition,
    }


def _single_campaign_portfolio(campaign, epoch: int):
    return FoundationCampaignPortfolio(
        current_epoch=epoch,
        campaigns=(campaign,),
        primary=campaign,
        secondary=None,
        deferred=(),
        notes=("synthetic fixed-campaign fixture",),
    )


def _foundation(suit: str):
    return [Card(suit, rank) for rank in range(13, 0, -1)]


def _current_epoch_removal_state():
    columns = [
        Column([], [Card("h", rank) for rank in range(13, 1, -1)]),
        Column([], [Card("h", 1)]),
    ]
    columns.extend(Column([], [Card("c", 9)]) for _ in range(8))
    stock = [Card("d", 4) for _ in range(30)]
    return SpiderState(columns, stock, [_foundation("s")])


def _next_epoch_removal_state():
    columns = [Column([], [Card("c", 9)]) for _ in range(10)]
    columns[9] = Column([], [Card("h", rank) for rank in range(12, 0, -1)])
    later = [Card("d", 8) for _ in range(20)]
    row = [
        Card("h", 13),
        Card("c", 2),
        Card("d", 3),
        Card("c", 4),
        Card("d", 7),
        Card("c", 8),
        Card("d", 9),
        Card("c", 10),
        Card("c", 6),
        Card("d", 5),
    ]
    return SpiderState(columns, later + row, [_foundation("s")]), tuple(row)


@pytest.fixture(scope="module")
def synthetic_context():
    cards = tuple(load_deal(ROOT / "deals" / "4925153.txt"))
    state = _current_epoch_removal_state()
    campaign = analyze_foundation_campaigns(state, cards=cards).primary
    assert campaign.suit == "h"
    return {"cards": cards, "state": state, "campaign": campaign}


def test_post_s1_residual_is_reconstructed_through_public_apis(benchmark):
    result = benchmark["first"]
    actions = SIX_MOVE_FIXTURE + benchmark["deal1"].actions + result.actions
    replayed = benchmark["opening"].clone()
    assert replay_actions(replayed, list(actions)) == 23
    assert actions.count(("deal",)) == 2
    assert len(replayed.stock) == 30
    assert len(replayed.foundations) == 1
    assert tuple(sequence[0].suit for sequence in replayed.foundations) == ("s",)
    assert states_structurally_equal(replayed, benchmark["residual"])


def test_completed_spade_cards_are_reserved_not_reused(benchmark):
    campaign = benchmark["portfolio"].campaign_for("s", 2)
    sources = tuple(source for need in campaign.rank_needs for source in need.sources)
    assert any(source.kind == RankSourceKind.COMPLETED_FOUNDATION for source in sources)
    assert all(
        need.chosen is None or not need.chosen.reserved_by_completed_foundation
        for need in campaign.rank_needs
    )


def test_s2_is_next_outstanding_spade_ordinal(benchmark):
    assert benchmark["portfolio"].campaign_for("s").copy_index == 2


def test_residual_portfolio_is_deterministic(benchmark):
    again = analyze_foundation_campaigns(
        benchmark["residual"], cards=benchmark["cards"]
    )
    frozen = tuple(
        (item.label, item.target_removal_epoch, item.estimated_campaign_cost, item.campaign_score)
        for item in benchmark["portfolio"].campaigns
    )
    assert frozen == tuple(
        (item.label, item.target_removal_epoch, item.estimated_campaign_cost, item.campaign_score)
        for item in again.campaigns
    )


def test_transition_mode_is_derived_from_epochs():
    assert derive_transition_mode(2, 2) == CampaignTransitionMode.REMOVE_BEFORE_NEXT_DEAL
    assert derive_transition_mode(2, 3) == CampaignTransitionMode.REMOVE_AT_NEXT_DEAL
    assert derive_transition_mode(2, 4) == CampaignTransitionMode.ADVANCE_ONE_EPOCH


def test_fixed_campaign_identity_persists(benchmark):
    result = benchmark["transition"]
    campaign = benchmark["primary"]
    assert result.identity.suit == campaign.suit
    assert result.identity.copy_index == campaign.copy_index
    assert result.identity.target_epoch == campaign.target_removal_epoch
    assert result.campaign_after is not None
    assert result.campaign_after.label == campaign.label


def test_equivalent_physical_source_substitution_remains_legal(benchmark):
    result = benchmark["transition"]
    before = {
        need.rank: need.chosen.source_key
        for need in result.campaign_before.rank_needs
        if need.chosen is not None
    }
    after = {
        need.rank: need.chosen.source_key
        for need in result.campaign_after.rank_needs
        if need.chosen is not None
    }
    assert result.independent_replay_verified
    assert any(before[rank] != after[rank] for rank in before.keys() & after.keys())


def test_exact_next_row_obligations_derive_from_later_campaign(benchmark):
    campaign = benchmark["portfolio"].campaign_for("d", 1)
    obligations = campaign_transition_obligations(
        benchmark["residual"], campaign, benchmark["cards"]
    )
    assert any(
        item.kind == CampaignTransitionObligationKind.APPLY_EXACT_ROW
        for item in obligations
    )
    receivers = [
        item
        for item in obligations
        if item.kind == CampaignTransitionObligationKind.SHAPE_RECEIVER
    ]
    assert receivers
    assert all(item.deadline_epoch == 3 for item in obligations)


def test_transition_never_applies_more_than_one_new_deal(benchmark):
    result = benchmark["transition"]
    assert result.deals_applied == result.actions.count(("deal",)) <= 1


def test_deal4_is_never_reached(benchmark):
    result = benchmark["transition"]
    assert current_stock_epoch(result.resulting_state, 5) <= 3
    assert len(result.resulting_state.stock) >= 20


def test_current_epoch_synthetic_campaign_removes_without_deal(synthetic_context, monkeypatch):
    campaign = synthetic_context["campaign"]
    state = _current_epoch_removal_state()
    portfolio = _single_campaign_portfolio(campaign, 2)
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    result = realize_residual_campaign_transition(
        state,
        campaign,
        synthetic_context["cards"],
        max_added_cost=2,
        max_nodes=100,
        time_limit_s=2,
        beam_width=32,
    )
    assert result.status == CampaignTransitionStatus.FOUNDATION_REMOVED
    assert result.deals_applied == 0
    assert result.foundation_count_before == 1
    assert result.foundation_count_after == 2
    assert result.foundation_suits_added == ("h",)
    assert result.independent_replay_verified


def test_next_epoch_synthetic_campaign_removes_after_one_deal(synthetic_context, monkeypatch):
    base = synthetic_context["campaign"]
    state, row = _next_epoch_removal_state()
    incoming = CampaignIncomingCard(
        Card("h", 13),
        0,
        True,
        "incoming King is the final campaign base",
        "known row",
        "snapshot_exact_extractable",
        True,
    )
    plan = CampaignEpochPlan(
        epoch=3,
        epoch_label="after deal 3",
        incoming=(incoming,),
        campaign_ranks_arriving=(13,),
        selected_ranks_arriving=(13,),
        available_rank_bands_before=((12, 1),),
        receiver_requirements=(),
        useful_same_suit_joins=(),
        carry_empty_policy="none",
        expected_workspace_after_deal=0,
        unlocks=("King base",),
        geometry_is_exact=True,
    )
    campaign = replace(base, target_removal_epoch=3, stock_plan=(plan,))
    portfolio = _single_campaign_portfolio(campaign, 2)
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    monkeypatch.setattr(fcrm, "analyze_foundation_campaign", lambda *_a, **_k: campaign)
    result = realize_residual_campaign_transition(
        state,
        campaign,
        synthetic_context["cards"],
        max_added_cost=4,
        max_nodes=2_000,
        time_limit_s=5,
        beam_width=128,
    )
    assert result.status == CampaignTransitionStatus.FOUNDATION_REMOVED
    assert result.exact_row == row
    assert result.deals_applied == 1
    assert result.foundation_suits_added == ("h",)
    assert current_stock_epoch(result.resulting_state, 5) == 3


def test_later_epoch_synthetic_campaign_advances_once_and_stops(synthetic_context, monkeypatch):
    state, row = _next_epoch_removal_state()
    base = synthetic_context["campaign"]
    no_space = replace(
        base.space_plan,
        policy=SpacePolicy.NONE,
        estimated_regain_cost=None,
    )
    campaign = replace(
        base,
        target_removal_epoch=4,
        prerequisite_excavation_projects=(),
        current_same_suit_fragments=(),
        space_plan=no_space,
        stock_plan=(),
    )
    after = replace(campaign, current_epoch=3)
    portfolio = _single_campaign_portfolio(campaign, 2)
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    monkeypatch.setattr(fct, "_fixed_reanalysis", lambda *_a, **_k: after)
    import spider.planner.foundation_campaign_realizer as realizer

    monkeypatch.setattr(realizer, "analyze_foundation_campaign", lambda *_a, **_k: after)
    result = realize_residual_campaign_transition(
        state,
        campaign,
        synthetic_context["cards"],
        max_added_cost=2,
        max_nodes=100,
        time_limit_s=2,
    )
    assert result.status == CampaignTransitionStatus.NEXT_EPOCH_REACHED
    assert result.mode == CampaignTransitionMode.ADVANCE_ONE_EPOCH
    assert result.exact_row == row
    assert result.deals_applied == 1
    assert len(result.resulting_state.stock) == 20
    assert current_stock_epoch(result.resulting_state, 5) == 3


def test_foundation_count_and_suit_are_verified_by_engine(synthetic_context):
    state = _current_epoch_removal_state()
    result = search_campaign_tableau(
        state,
        synthetic_context["campaign"],
        target=CampaignTableauTarget.REMOVE_FOUNDATION,
        max_cost=2,
        max_nodes=100,
        time_limit_s=2,
        beam_width=32,
        foundation_suit_before=0,
    )
    assert result.found
    assert len(result.state.foundations) == 2
    assert result.state.foundations[-1][0].suit == synthetic_context["campaign"].suit


def test_complete_route_replays_at_equal_corrected_cost(benchmark):
    transition = benchmark["transition"]
    actions = (
        SIX_MOVE_FIXTURE
        + benchmark["deal1"].actions
        + benchmark["first"].actions
        + transition.actions
    )
    replayed = benchmark["opening"].clone()
    assert replay_actions(replayed, list(actions)) == 23 + transition.corrected_added_cost
    assert states_structurally_equal(replayed, transition.resulting_state)


def test_bounded_resource_failure_is_not_impossibility(synthetic_context, monkeypatch):
    state = synthetic_context["state"]
    campaign = synthetic_context["campaign"]
    portfolio = _single_campaign_portfolio(campaign, 2)
    monkeypatch.setattr(fct, "analyze_foundation_campaigns", lambda *_a, **_k: portfolio)
    monkeypatch.setattr(fct, "_fixed_reanalysis", lambda *_a, **_k: campaign)
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
        state, campaign, synthetic_context["cards"], max_added_cost=1, max_nodes=1
    )
    assert result.status == CampaignTransitionStatus.RESOURCE_LIMIT
    assert "not impossibility" in result.stop_reason


def test_residual_quality_audit_reports_actual_structure(benchmark):
    audit = audit_residual_state(
        benchmark["residual"], benchmark["primary"], benchmark["cards"]
    )
    assert audit.face_down_cards == 32
    assert audit.stock_size == 30
    assert audit.foundation_suits == ("s",)
    assert audit.empty_columns == ()
    assert audit.fully_open_columns == 2
    assert audit.fully_open_nonking_columns == 2
    assert audit.cheapest_workspace_cost == 2
    assert audit.legal_move_count > 0
    assert audit.total_same_suit_run_mass >= audit.longest_same_suit_run


def test_benchmark_transition_materially_lowers_primary_burden(benchmark):
    result = benchmark["transition"]
    assert result.status == CampaignTransitionStatus.CAMPAIGN_ADVANCED
    assert result.corrected_added_cost == 8
    assert len(result.must_sources_after) < len(result.must_sources_before)
    assert result.campaign_after.estimated_campaign_cost < result.campaign_before.estimated_campaign_cost
    assert result.deals_applied == 0


def test_generic_production_modules_have_no_benchmark_constants():
    source = (inspect.getsource(fct) + inspect.getsource(fcrm.search_campaign_tableau)).lower()
    for token in (
        "4925153",
        "canonical.moves",
        "leaderboard",
        "column 7",
        "move 9 4 1",
        "67-move",
    ):
        assert token not in source
