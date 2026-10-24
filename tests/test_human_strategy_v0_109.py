"""Contract tests for v0.109 foundation-directed planning.

The close and earlier checkpoints replay a verified prefix only to reach a
state. The controller does not receive the suffix. Cold tests do not read a
solution file.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    chosen_source_keys,
    load_portfolio,
    propose_foundation_step,
    rank_foundations,
)
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import parse_moves_file, replay_actions, replay_actions_detailed
from spider.research_actions import face_down_count

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


def _opening():
    return SpiderState.from_cards(list(_cards()))


def _prefix(n: int):
    cards = _cards()
    actions = parse_moves_file(CANONICAL)
    state = SpiderState.from_cards(list(cards))
    g = replay_actions(state, list(actions[:n]))
    return cards, actions, state, g


def _views():
    cards = _cards()
    return rank_foundations(_opening(), cards, cache={})


def test_all_suits_and_both_copies_are_ranked():
    views = _views()
    labels = {item.label for item in views}
    assert labels == {"S#1", "H#1", "D#1", "C#1"}
    for item in views:
        assert any("other physical copy" in reason for reason in item.reasons)
        assert item.other_copy_earliest is not None


def test_availability_is_not_the_same_as_accessibility():
    views = {item.label: item for item in _views()}
    spades = views["S#1"]
    clubs = views["C#1"]
    assert spades.theoretically_available is False
    assert spades.earliest_epoch == 2
    assert spades.operationally_attainable is True
    assert spades.economically_attractive is True
    assert clubs.theoretically_available is False
    assert clubs.earliest_epoch == 5
    assert clubs.economically_attractive is False
    assert clubs.target_epoch > spades.target_epoch


def test_priority_is_not_hard_coded_to_one_suit():
    cards = _cards()
    original = rank_foundations(_opening(), cards, cache={})[0].label
    swapped_cards = []
    for card in cards:
        suit = card.suit
        if suit == "s":
            suit = "h"
        elif suit == "h":
            suit = "s"
        swapped_cards.append(Card(suit, card.rank))
    swapped = SpiderState.from_cards(list(swapped_cards))
    winner = rank_foundations(swapped, swapped_cards, cache={})[0]
    assert original == "S#1"
    assert winner.label == "H#1"
    assert winner.suit == "h"


def test_duplicate_physical_sources_are_unique():
    cards = _cards()
    _feasibility, portfolio = load_portfolio(_opening(), cards, {})
    campaign = portfolio.primary
    keys = chosen_source_keys(campaign)
    assert keys
    assert len(keys) == len(set(keys))
    assert any(len(need.sources) >= 2 for need in campaign.rank_needs)
    chosen = {need.rank: need.chosen.source_key for need in campaign.rank_needs if need.chosen}
    for need in campaign.rank_needs:
        if len(need.sources) < 2 or need.chosen is None:
            continue
        others = [source.source_key for source in need.sources if source.source_key != need.chosen.source_key]
        assert others
        assert chosen[need.rank] not in others
        break
    else:
        raise AssertionError("no rank offered two physical copies")


def test_buried_card_becomes_a_prerequisite():
    cards = _cards()
    proposal = propose_foundation_step(
        _opening(), cards, _profile(), 5.0, 0, cache={}, lock={}
    )
    buried = [
        item
        for item in proposal.public["prerequisites"]
        if item["kind"] == "excavate" and item["mandatory_before_deal"] and not item["achieved"]
    ]
    assert buried
    assert all(item["column"] for item in buried)
    assert proposal.public["label"] == "S#1"


def test_opening_pursues_the_prerequisite_before_dealing():
    result = _open_result()
    assert result.decisions
    first = result.decisions[0]
    assert first.chosen_id.startswith("excavate:")
    assert first.status in {"achieved", "partial"}
    assert result.actions[0] != ("deal",)
    assert result.deals == 0
    played = _replay_state(result)
    assert face_down_count(played) < 44


def test_prerequisites_are_legal_corrected_moves():
    result = _open_result()
    detail = replay_actions_detailed(_opening(), list(result.actions))
    assert detail["mobilityware_moves"] == result.suffix_mw
    assert result.replay["ok"] is True


def test_campaign_persists_across_actions():
    result = _open_result()
    continues = [event for event in result.events if event.startswith("foundation: continue")]
    assert continues
    assert all("S#1" in event for event in continues)
    assert len(result.actions) >= 2


def test_tactical_timeout_does_not_retire_the_campaign():
    cards = _cards()
    lock = {}
    first = propose_foundation_step(_opening(), cards, _profile(), 0.0, 0, cache={}, lock=lock)
    assert lock["label"] == "S#1"
    assert any("does not retire" in event for event in first.events)
    assert first.timeout is True
    again = propose_foundation_step(_opening(), cards, _profile(), 0.0, 0, cache={}, lock=lock)
    assert lock["label"] == "S#1"
    assert "impossible" not in " ".join(again.events)
    buried = next(
        item["id"]
        for item in again.public["prerequisites"]
        if item["kind"] == "excavate" and item["mandatory_before_deal"]
    )
    lock["failures"][buried] = 3
    suspended = propose_foundation_step(_opening(), cards, _profile(), 2.0, 0, cache={}, lock=lock)
    assert lock["label"] == "S#1"
    assert any("stays open" in event for event in suspended.events)
    open_ids = [
        item["id"]
        for item in suspended.public["prerequisites"]
        if item["kind"] == "excavate" and item["mandatory_before_deal"] and not item["achieved"]
    ]
    for ident in open_ids:
        lock["failures"][ident] = 3
    held = propose_foundation_step(
        _opening(), cards, _profile(), 2.0, 0, cache={}, lock=lock, blocked=tuple(open_ids)
    )
    assert held.candidate is None or held.candidate.kind != "DEAL_NOW"
    if held.candidate is None:
        assert held.block_deal
        assert any("deal waits" in event for event in held.events)


def test_stock_deal_replans_the_campaign():
    result = _close()
    assert any(event == "replan: foundation campaign after stock" for event in result.events)
    assert result.deals == 1


def test_foundation_removal_replans_the_next_suit():
    result = _close()
    assert result.foundations == 1
    assert any(event.startswith("replan: foundation campaign after removal") for event in result.events)
    assert any(item.get("reason") == "after removal" and item.get("label") for item in result.provenance["foundation"])


def test_protected_run_is_not_split_before_the_deal():
    _cards_deal, reference, _state, g = _prefix(82)
    result = _close()
    assert result.actions[0] == ("deal",)
    assert reference[82] != ("deal",)
    assert (1, 0, 2) not in result.actions
    assert result.actions != tuple(reference[82:])


def test_empty_columns_do_not_choose_the_suit():
    views = _views()
    for item in views:
        assert any("empty columns are shared" in reason for reason in item.reasons)
    assert sum(1 for item in views if item.economically_attractive) == 1


def test_a_temporary_park_can_advance_a_prerequisite():
    result = _open_result()
    state = _opening()
    parked = False
    for action in result.actions:
        if action == ("deal",):
            break
        src, dst, k = action
        moved = state.columns[src].face_up[-k]
        top = state.columns[dst].top()
        if top is not None and (top.suit != moved.suit or top.rank != moved.rank + 1):
            parked = True
        replay_actions(state, [action])
    assert parked
    assert face_down_count(state) < 44


def test_an_expensive_late_suit_is_not_the_target():
    views = _views()
    attractive = [item for item in views if item.economically_attractive]
    assert len(attractive) == 1
    winner = attractive[0]
    later = [item for item in views if item.target_epoch and item.target_epoch > winner.target_epoch]
    assert later
    assert winner.estimated_cost == min(item.estimated_cost for item in views)
    assert all(not item.economically_attractive for item in later)


def test_foundation_preparation_beats_an_immediate_deal():
    result = _open_result()
    assert result.actions
    assert result.actions[0] != ("deal",)
    assert result.decisions[0].reason.startswith("selected: foundation prerequisite")


def test_shape_policy_delays_an_intermediate_deal():
    """The campaign's own stock policy holds a deal that would bury a receiver."""

    from spider.research_actions import apply_action

    cards = _cards()
    state = _opening()
    lock = {}
    cache = {}
    delayed = False
    for _ in range(10):
        proposal = propose_foundation_step(
            state, cards, _profile(), 3.0, 0, cache=cache, lock=lock
        )
        if any("delays the deal" in event for event in proposal.events):
            delayed = True
            assert proposal.candidate is None or proposal.candidate.actions[:1] != (("deal",),)
            assert "is not the next row" in " ".join(proposal.events)
            break
        assert proposal.candidate is not None
        assert proposal.candidate.actions
        assert proposal.candidate.actions[0] != ("deal",)
        apply_action(state, proposal.candidate.actions[0])
    assert delayed
    assert lock["label"] == "S#1"


def test_wasteful_foundation_preparation_is_rejected():
    result = _close()
    assert result.decisions[0].chosen_id == "DEAL:S#1"
    assert result.decisions[0].reason == "selected: foundation plan deals after its prerequisites"
    assert not any(item.chosen_id.startswith("excavate:") for item in result.decisions)
    evidence = " ".join(result.decisions[0].evidence)
    assert "Ks" in evidence or "next row" in evidence
    assert "can cover" in evidence


def test_checkpoint_completes_a_real_foundation():
    _cards_deal, reference, state, g = _prefix(82)
    result = _close()
    assert result.mode == "diagnose"
    assert result.status == "FOUNDATION_REACHED"
    assert result.solved is False
    assert result.foundations == 1
    assert result.provenance["partial_trajectory"] is True
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["assisted_suffix"] is False
    assert "suffix not injected" in result.provenance["note"]
    assert result.actions[0] != reference[82]
    assert result.replay["ok"] is True
    assert result.replay["foundations"] == 1
    assert result.replay["solved"] is False
    assert result.cumulative_g == g + result.suffix_mw
    del state


def test_earlier_checkpoint_still_has_excavation_work():
    cards, _actions, state, g = _prefix(31)
    assert face_down_count(state) > 10
    result = solve(
        state,
        _profile(max_steps=3, time_limit_s=20),
        mode="diagnose",
        opening_g=g,
        goal="first-foundation",
        deal_cards=cards,
        provenance_note="diagnostic canonical prefix 31; suffix not injected",
    )
    assert result.foundations == 0
    assert result.actions[0] != ("deal",)
    assert any(event.startswith("foundation: selected S#1") for event in result.events)
    assert any("does not make S#1 impossible" in event for event in result.events)
    assert any(event.startswith("foundation: continue S#1") for event in result.events)
    assert "suffix not injected" in result.provenance["note"]


def test_cold_mode_does_not_read_solution_files(monkeypatch):
    def _refuse(*_args, **_kwargs):
        raise AssertionError("cold search read a moves file")

    monkeypatch.setattr("spider.metrics.parse_moves_file", _refuse)
    result = solve(
        _opening(),
        _profile(max_steps=1, time_limit_s=8),
        mode="cold",
        goal="first-foundation",
        deal_cards=_cards(),
    )
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["assisted_suffix"] is False
    assert result.provenance["goal"] == "first-foundation"
    try:
        solve(_opening(), _profile(), mode="cold", goal="first-foundation", deal_cards=_cards(), incumbent_actions=(("deal",),))
    except ValueError as exc:
        assert "cold" in str(exc)
    else:
        raise AssertionError("cold mode accepted a sequence")


def test_partial_route_replays_and_limits_stay_distinct():
    result = _close()
    assert result.replay["ok"] is True
    assert result.replay["mobilityware_moves"] == result.suffix_mw
    assert result.solved is False
    assert result.status != "SOLVED_VALID"
    timed = solve(
        _opening(),
        _profile(time_limit_s=0, max_steps=4),
        mode="cold",
        goal="first-foundation",
        deal_cards=_cards(),
    )
    assert timed.status == "TIME_LIMIT"
    assert timed.solved is False
    limited = solve(
        _opening(),
        _profile(rss_abort_mb=-1, time_limit_s=5),
        mode="cold",
        goal="play",
    )
    assert limited.status == "MEMORY_LIMIT"
    assert limited.solved is False


_CACHE = {}


def _open_result():
    if "open" not in _CACHE:
        _CACHE["open"] = solve(
            _opening(),
            _profile(),
            mode="cold",
            goal="first-foundation",
            deal_cards=_cards(),
        )
    return _CACHE["open"]


def _close():
    if "close" not in _CACHE:
        cards, _actions, state, g = _prefix(82)
        _CACHE["close"] = solve(
            state,
            _profile(max_steps=4, time_limit_s=15),
            mode="diagnose",
            opening_g=g,
            goal="first-foundation",
            deal_cards=cards,
            provenance_note="diagnostic canonical prefix 82; suffix not injected",
        )
    return _CACHE["close"]


def _replay_state(result):
    state = _opening()
    replay_actions(state, list(result.actions))
    return state
