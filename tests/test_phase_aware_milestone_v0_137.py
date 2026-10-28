"""v0.137 phase-aware milestone ordering.

The recorded five-move shortcut is a forensic subject. It is not a search
seed. The 12,000-state control and the eight tactic searches stay in the driver.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import format_action, parse_moves_file
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.post_deal_milestone import (
    ENDPOINT_CEILING,
    MilestoneEndpoint,
    MilestoneHit,
    MilestoneSpec,
    choose_milestone_hits,
    describe_position,
    milestone_met,
    objective_status,
    phase_name,
    rank_milestone_actions,
    retain_endpoints,
    screening_milestone,
    search_milestone,
    spec_from_source,
)
from spider.research_actions import apply_action, face_down_count, step_cost, tableau_actions

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
DRIVER = ROOT / "tools" / "phase_aware_milestone_v0_137.py"
MODULE = ROOT / "src" / "spider" / "post_deal_milestone.py"

# Recorded v0.136 discovery. Audit only.
RECORDED_SHORTCUT = ((4, 1, 1), (4, 8, 1), (3, 4, 1), (3, 0, 2), (3, 8, 1))


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "", downs=None, foundations=None) -> SpiderState:
    downs = downs or {}
    cols = [
        Column(_cards(downs.get(index, "")), _cards(columns.get(index, "")))
        for index in range(10)
    ]
    return SpiderState(cols, _cards(stock), foundations or [])


def _ranks(high: int, low: int, suit: str) -> str:
    names = {1: "a", 10: "10", 11: "j", 12: "q", 13: "k"}
    return " ".join(names.get(rank, str(rank)) + suit for rank in range(high, low - 1, -1))


def _foundation_board():
    columns = {0: _ranks(13, 2, "c"), 1: "5d", 2: "4d"}
    downs = {2: "ac"}
    for index in range(3, 10):
        columns[index] = "kh"
        downs[index] = "qs"
    return _state(columns, downs=downs)


def _split_board():
    """One free club completion, and a separate paid reveal."""

    columns = {0: _ranks(13, 1, "c"), 2: "4d", 3: "5d"}
    downs = {2: "qs"}
    for index in range(4, 10):
        columns[index] = "kh"
        downs[index] = "qs"
    return _state(columns, downs=downs)


def _park_board():
    columns = {0: "kh", 2: "4c", 3: "5c"}
    downs = {2: "qs"}
    for index in range(4, 10):
        columns[index] = "kd"
        downs[index] = "qs"
    return _state(columns, downs=downs)


def _endpoint(state, g, h, root=0):
    return MilestoneEndpoint(
        root_index=root,
        g=g,
        h=h,
        actions=((0, 1, 1),),
        pre_deal_macro=((1, 2, 1),),
        state=state,
        pack=pack_state(state).hex(),
        symmetry=pack_whole_game_identity(state).hex() if not state.stock else "sym",
        suit_gain=1,
        face_down_drop=1,
        zero_cost=0,
        paid=1,
    )


def _hit(g, h, symmetry, pack):
    return MilestoneHit(
        actions=((0, 1, 1),),
        g=g,
        paid=1,
        zero_cost=0,
        suit_gain=1,
        face_down_drop=1,
        pack=pack,
        symmetry=symmetry,
        replay_ok=True,
        h=h,
        f=g + h,
    )


def test_shortcut_is_a_different_tableau_from_the_canonical_milestone():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(CANONICAL)
    checkpoints = build_checkpoints(opening, actions)
    source = checkpoints[152].state.clone()
    canon = source.clone()
    for action in actions[152:160]:
        apply_action(canon, action)
    short = source.clone()
    for action in RECORDED_SHORTCUT:
        apply_action(short, action)
    canon_pos = describe_position(canon, 158)
    short_pos = describe_position(short, 155)
    assert canon_pos["g"] == 158
    assert short_pos["g"] == 155
    assert canon_pos["h"] == admissible_remaining(canon)
    assert short_pos["h"] == admissible_remaining(short)
    assert canon_pos["h"] == checkpoints[160].admissible_remaining
    assert canon_pos["f"] == 169
    assert short_pos["pack"] != canon_pos["pack"]
    assert short_pos["symmetry"] != canon_pos["symmetry"]
    assert short_pos["face_down"] == 0
    assert short_pos["foundations"] == 3
    assert "c" in short_pos["foundation_suits"]
    saved = canon_pos["g"] - short_pos["g"]
    assert saved == 3
    # 155 plus the canonical 14-move remainder is 169 only if that suffix
    # still applies. The replay below shows that it does not.
    assert short_pos["g"] + (172 - 158) == 169
    probe = short.clone()
    failed = None
    for index, action in enumerate(actions[160:]):
        try:
            apply_action(probe, action)
        except ValueError as exc:
            failed = (index, format_action(action), str(exc))
            break
    assert failed is not None
    assert "illegal move" in failed[2]
    source_text = MODULE.read_text(encoding="utf-8")
    for action in list(actions[152:160]) + list(RECORDED_SHORTCUT):
        assert repr(action) not in source_text


def test_phase_aware_is_opt_in_and_legacy_lanes_stay():
    source = _foundation_board()
    legacy = search_milestone(
        source,
        g0=0,
        suit="c",
        paid_moves=3,
        max_depth=4,
        max_unique=40,
        time_limit_s=2.0,
        stop_on_first=True,
    )
    assert legacy.phase_aware is False
    assert legacy.hit_policy == "lowest_g"
    assert [name for name, _count in legacy.lane_exp] == ["progress", "setup"]
    assert legacy.met
    phased = search_milestone(
        source,
        g0=0,
        suit="c",
        paid_moves=3,
        max_depth=4,
        max_unique=40,
        time_limit_s=2.0,
        stop_on_first=True,
        phase_aware=True,
    )
    assert phased.met and phased.replay_ok
    assert [name for name, _count in phased.lane_exp] == ["foundation", "reveal", "setup"]
    assert phased.phases_expanded["both_not_yet"] >= 1


def test_reveal_first_then_foundation_and_a_partial_is_not_terminal():
    source = _foundation_board()
    spec = spec_from_source(source, "c")
    found = search_milestone(
        source,
        g0=4,
        suit="c",
        paid_moves=3,
        max_depth=4,
        max_unique=80,
        time_limit_s=2.0,
        phase_aware=True,
        stop_on_first=True,
    )
    assert found.met
    state = source.clone()
    reveal_step = None
    foundation_step = None
    for step, action in enumerate(found.actions, start=1):
        before_hidden = face_down_count(state)
        before_clubs = state.foundations[:]
        apply_action(state, action)
        if reveal_step is None and face_down_count(state) < before_hidden:
            reveal_step = step
            assert not milestone_met(state, spec) or foundation_step is not None
        if foundation_step is None and len(state.foundations) > len(before_clubs):
            foundation_step = step
    assert reveal_step is not None and foundation_step is not None
    assert reveal_step < foundation_step
    assert milestone_met(state, spec)


def test_club_only_options_do_not_consume_the_only_lane():
    source = _split_board()
    spec = spec_from_source(source, "c")
    done = source.clone()
    apply_action(done, (0, 1, 13))
    assert suit_only(done, spec)
    assert not milestone_met(done, spec)
    # 40 identities leaves a turn for the club-only child after the root
    # frontier fills. 30 admits that child and then stops on the next reveal.
    found = search_milestone(
        source,
        g0=0,
        suit="c",
        paid_moves=2,
        max_depth=3,
        max_unique=40,
        time_limit_s=2.0,
        phase_aware=True,
        stop_on_first=False,
    )
    assert found.phases_expanded["foundation_only"] >= 1
    assert found.phases_expanded["reveal_only"] >= 1
    assert found.phases_admitted["foundation_only"] >= found.phases_expanded["foundation_only"]
    assert not found.met or found.face_down_after < found.face_down_before


def suit_only(state, spec) -> bool:
    founded, revealed = objective_status(state, spec)
    return phase_name(founded, revealed) == "foundation_only"


def test_phase_flags_follow_the_state_not_the_action_names():
    spec = MilestoneSpec("c", 0, 3)
    left = _state({0: "5c", 1: "4d"}, downs={2: "ac", 3: "ad"})
    right = _state({4: "9h", 6: "2s"}, downs={0: "kc", 8: "qd"})
    assert face_down_count(left) == face_down_count(right) == 2
    assert objective_status(left, spec) == objective_status(right, spec)
    assert phase_name(*objective_status(left, spec)) == "reveal_only"
    founded, revealed = objective_status(left, spec)
    assert revealed and not founded


def test_zero_cost_setup_still_precedes_a_paid_action():
    source = _park_board()
    hidden = face_down_count(source)

    def joined(state: SpiderState) -> bool:
        up = state.columns[0].face_up
        return (
            len(up) >= 2
            and up[-2].rank == 5
            and up[-2].suit == "c"
            and up[-1].rank == 4
            and up[-1].suit == "c"
            and face_down_count(state) < hidden
        )

    ordered = rank_milestone_actions(
        source,
        tableau_actions(source),
        "c",
        column=0,
        phase_aware=True,
        founded=False,
        revealed=False,
    )
    assert len(ordered) == len(tableau_actions(source))
    assert (0, 1, 1) in ordered
    found = search_milestone(
        source,
        g0=4,
        suit="c",
        paid_moves=2,
        max_depth=4,
        max_unique=400,
        time_limit_s=2.0,
        column=0,
        terminal_fn=joined,
        phase_aware=True,
        stop_on_first=True,
    )
    assert found.met
    trial = source.clone()
    saw_free = False
    saw_paid_after = False
    for action in found.actions:
        cost = step_cost(trial, action)
        if cost == 0:
            saw_free = True
        elif saw_free:
            saw_paid_after = True
        apply_action(trial, action)
    assert saw_free and saw_paid_after
    assert joined(trial)


def test_lower_f_selection_is_not_the_lane_order():
    cheaper_g = _hit(150, 21, "sym-a", "pack-a")
    lower_f = _hit(154, 16, "sym-b", "pack-b")
    by_g, g_info = choose_milestone_hits([lower_f, cheaper_g], policy="lowest_g", limit=1)
    by_f, f_info = choose_milestone_hits([cheaper_g, lower_f], policy="lower_f", limit=1)
    assert by_g[0].g == 150
    assert by_f[0].g == 154
    assert by_f[0].f == 170
    assert "lowest f" in f_info["reason"]
    assert "proof" not in f_info["reason"]
    assert g_info["policy"] != f_info["policy"]
    state = _state({0: "5c"})
    high_g = _endpoint(state, 154, 16, root=1)
    low_g = _endpoint(state.clone(), 150, 21, root=2)
    low_g_pack = pack_state(state.clone()).hex()
    # Distinct symmetry so retention can see both orders.
    low_g = MilestoneEndpoint(
        root_index=2,
        g=150,
        h=21,
        actions=((0, 1, 1),),
        pre_deal_macro=((1, 2, 1),),
        state=state,
        pack="pack-low-g",
        symmetry="sym-low-g",
        suit_gain=1,
        face_down_drop=1,
        zero_cost=0,
        paid=1,
    )
    high_g = MilestoneEndpoint(
        root_index=1,
        g=154,
        h=16,
        actions=((2, 3, 1),),
        pre_deal_macro=((3, 4, 1),),
        state=state,
        pack="pack-low-f",
        symmetry="sym-low-f",
        suit_gain=1,
        face_down_drop=1,
        zero_cost=0,
        paid=1,
    )
    assert low_g.f == 171
    assert high_g.f == 170
    by_endpoint_g, _dominated = retain_endpoints([high_g, low_g], limit=1)
    by_endpoint_f, _dominated_f = retain_endpoints([low_g, high_g], limit=1, order="f")
    assert by_endpoint_g[0].g == 150
    assert by_endpoint_f[0].f == 170
    assert low_g_pack


def test_screening_is_not_a_proof_and_skips_the_exhausted_identity():
    state = _state({0: "kh qh"})
    blocked = _endpoint(state, 5, 0)
    rejected = screening_milestone(blocked, ceiling=6, excluded_packs=())
    assert rejected["accepted"] is False
    assert rejected["proof"] is False
    assert "no proof-eligible successor" in rejected["reasons"]
    wide = screening_milestone(blocked, ceiling=1000)
    assert wide["accepted"] is True
    assert wide["proof"] is False
    assert wide["screen_f"] == 999
    exhausted = _endpoint(state, 154, 17)
    skipped = screening_milestone(exhausted, ceiling=171, excluded_packs=(exhausted.pack,))
    assert skipped["accepted"] is False
    assert "previously exhausted identity" in skipped["reasons"]
    assert skipped["proof"] is False
    above = _endpoint(state.clone(), 154, 17)
    above_screen = screening_milestone(above, ceiling=ENDPOINT_CEILING)
    assert above_screen["screen_f"] == 170
    assert above_screen["accepted"] is False
    assert "f above screen" in above_screen["reasons"]


def test_unfinished_reveal_is_ordered_ahead_of_another_extension():
    source = _split_board()
    actions = tableau_actions(source)
    reveal = (2, 3, 1)
    assert reveal in actions
    assert step_cost(source, reveal) == 1
    ordered = rank_milestone_actions(
        source,
        actions,
        "c",
        phase_aware=True,
        founded=True,
        revealed=False,
    )
    assert ordered.index(reveal) < ordered.index((0, 1, 13))


def test_driver_stops_before_later_gates_and_does_not_raise_caps():
    text = DRIVER.read_text(encoding="utf-8")
    assert text.rindex("RECORDED_SHORTCUT") < text.index("search_milestone(")
    assert text.index("if not control_succeeded") < text.index("discover_macros(")
    assert text.index("discover_macros(") < text.index("if not opened")
    assert text.index("if not opened") < text.index("search_origin_fair(")
    assert "phase_aware=True" in text
    for banned in (
        "search_bridge_roots",
        "search_post_sd5",
        "search_route_bridge",
        "80_000",
        "80000",
        "time_limit_s=90",
    ):
        assert banned not in text
