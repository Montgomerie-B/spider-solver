"""v0.112 campaign feasibility and recovery tests.

The g32 board is the v0.111 stall, replayed from the recorded actions.
Those actions are an oracle for the fixture. Cold solves do not receive them.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    adopt_alternative_foundation,
    campaign_may_displace,
    campaign_near_term_status,
    load_portfolio,
    planning_stall_detail,
    propose_foundation_step,
)
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import format_action, replay_actions
from spider.research_actions import all_legal_actions, apply_action, face_down_count

DEAL = ROOT / "deals" / "4925153.txt"

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
G32_SUFFIX = (
    (7, 9, 1),
    (0, 2, 1),
    (3, 0, 1),
    (8, 3, 1),
    (3, 1, 1),
    (9, 1, 2),
    (0, 9, 2),
    (2, 0, 1),
    (0, 7, 2),
    (1, 0, 2),
    (1, 3, 1),
    (0, 1, 3),
    (7, 8, 2),
)


def _cards():
    return load_deal(DEAL)


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


def _replay(actions):
    state = SpiderState.from_cards(list(_cards()))
    g = 0
    for action in actions:
        g += apply_action(state, action)
    return state, g


def _g19():
    return _replay(G19)


def _g32():
    return _replay(G19 + G32_SUFFIX)


def test_g19_prefix_is_legal_and_costs_19():
    cards = _cards()
    state = SpiderState.from_cards(list(cards))
    g = replay_actions(state, list(G19))
    assert g == 19
    assert len(state.foundations) == 1
    assert [str(card) for card in state.foundations[0]][0] == "Ks"
    assert face_down_count(state) == 33
    assert len(state.stock) == 30
    assert sum(len(column.face_down) + len(column.face_up) for column in state.columns) + len(state.stock) + 13 == 104


def test_elapsed_epoch_cannot_displace_an_operational_campaign():
    state, _g = _g19()
    _feasibility, portfolio = load_portfolio(state, _cards(), {})
    by_label = {item.label: item for item in portfolio.campaigns}
    diamonds = by_label["D#1"]
    hearts = by_label["H#1"]
    assert campaign_near_term_status(state, diamonds) == "REQUIRES_PREPARATION"
    assert hearts.current_epoch >= hearts.target_removal_epoch
    assert campaign_may_displace(state, hearts, diamonds) is False
    assert "S#2" in by_label
    assert by_label["S#2"].copy_index == 2


def test_g32_accounts_for_every_legal_action_and_continues():
    state, g = _g32()
    assert g == 32
    legal = list(all_legal_actions(state))
    tableau = [action for action in legal if action != ("deal",)]
    # The v0.111 stall counted every legal action, including the deal.
    assert len(legal) == 7
    assert len(tableau) == 6
    detail = planning_stall_detail(state, {"label": "H#1", "alternatives": ["D#1", "C#1", "S#2"], "tried_labels": ["H#1"]})
    for action in tableau:
        assert format_action(action) in detail
    assert "S#2" in detail
    assert "not infeasibility" in detail
    result = solve(
        state.clone(),
        _profile(max_steps=8, time_limit_s=30),
        mode="diagnose",
        opening_g=g,
        goal="foundations",
        target_foundations=1,
        deal_cards=_cards(),
        provenance_note="diagnostic g32 replay; suffix not injected",
    )
    assert result.provenance["prefix_injected"] is False
    assert result.solved is False
    assert result.actions
    assert result.actions[0] in legal
    text = "\n".join(result.events)
    assert "already dealt" in text
    assert "PROBE_LIMIT" in text
    assert "not infeasibility" in text
    assert "S#2 stays eligible" in text
    assert "trying D#1" in text
    assert "D#1 is the alternative under test" in text
    assert "trying C#1" in text
    assert "C#1 is the alternative under test" in text
    assert "keep D#1" in text
    assert any(item == ("deal",) for item in result.actions)
    deal = next(item for item in result.decisions if item.actions[:1] == ("deal",))
    assert "future stock event" in " ".join(deal.evidence)
    assert "not revised" in " ".join(deal.evidence)


def test_historical_alignment_is_not_a_current_obligation():
    state, g = _g32()
    lock = {"label": "H#1", "operational_epoch": 2, "original_epoch": 2, "epoch_label": "H#1"}
    proposal = propose_foundation_step(state, _cards(), _profile(), 8.0, g, cache={}, lock=lock)
    text = " ".join(proposal.events)
    assert "historical row" in text
    assert "past landing column" in text
    if proposal.candidate is None:
        assert lock.get("yield_to_alternative") is True
        assert lock.get("feasibility_status") in {"PROBE_LIMIT", "DEFERRED_BY_STOCK", "SUSPENDED"}


def test_a_failed_hearts_probe_does_not_block_diamonds():
    state, g = _g32()
    lock = {"label": "D#1", "hold_label": "D#1"}
    proposal = propose_foundation_step(
        state,
        _cards(),
        _profile(),
        8.0,
        g,
        cache={},
        lock=lock,
        blocked=("access:tableau:3:up:1",),
    )
    assert "D#1 is the alternative under test" in " ".join(proposal.events)
    assert proposal.candidate is None or "H#1" not in proposal.candidate.candidate_id
    assert lock["label"] == "D#1"


def test_switch_cap_and_cold_refusal():
    lock = {"label": "H#1", "alternatives": ["D#1", "C#1", "S#2"], "alternative_switches": 0}
    first = adopt_alternative_foundation(lock)
    second = adopt_alternative_foundation(lock)
    third = adopt_alternative_foundation(lock)
    assert first and "D#1" in first
    assert second and "C#1" in second
    assert third is None
    try:
        solve(
            SpiderState.from_cards(list(_cards())),
            _profile(max_steps=1, time_limit_s=2),
            mode="cold",
            goal="play",
            incumbent_actions=(("deal",),),
        )
    except ValueError as exc:
        assert "cold" in str(exc).lower()
    else:
        raise AssertionError("cold mode accepted a stored prefix")


def test_cold_opening_still_reaches_the_spade_foundation():
    result = solve(
        SpiderState.from_cards(list(_cards())),
        _profile(max_steps=40, time_limit_s=40),
        mode="cold",
        goal="first-foundation",
        deal_cards=_cards(),
    )
    assert result.provenance["prefix_injected"] is False
    assert result.status == "FOUNDATION_REACHED"
    assert result.solved is False
    assert result.cumulative_g == 19
    assert tuple(result.actions) == G19
