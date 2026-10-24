"""Contract tests for v0.108 strategic preparation and objective commitment.

Fixtures are constructed deals. They do not replay the 172 or the 185.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.preparation import (
    abandonment_reason,
    classify_stall,
    compare_before_deal,
    incoming_alignment_notes,
    plan_still_worth_following,
    prefer_preparation,
    soft_failure_id,
)
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import replay_actions_detailed
from spider.planner.objective_realizer import RealizationMode, RealizationStatus, realize_objective
from spider.research_actions import all_legal_actions, apply_action, face_down_count, opening_from_deal

# The recorded v0.107 cold line on deal 4925153. Embedded so the stall test
# does not depend on a gitignored artifact.
V107_LINE = (
    (2, 5, 1),
    (9, 6, 1),
    (9, 2, 1),
    (7, 3, 1),
    (7, 9, 1),
    (5, 3, 2),
    (0, 5, 1),
    (5, 3, 2),
    ("deal",),
    (8, 6, 1),
    (5, 7, 1),
    ("deal",),
    (7, 9, 1),
    ("deal",),
    ("deal",),
    (8, 2, 1),
    (5, 6, 1),
    (7, 5, 1),
    ("deal",),
    (4, 1, 1),
    (3, 4, 1),
    (4, 9, 2),
    (4, 1, 1),
    (4, 2, 1),
    (6, 1, 1),
    (0, 4, 1),
    (7, 3, 1),
)


def _cards(text: str):
    return [Card.parse(tok) for tok in text.split() if tok]


def _state(columns, stock="", foundations=0) -> SpiderState:
    cols = []
    for index in range(10):
        spec = columns.get(index, ("", ""))
        if isinstance(spec, str):
            down, up = "", spec
        else:
            down, up = spec
        cols.append(Column(_cards(down), _cards(up)))
    found = []
    for n in range(foundations):
        suit = "shdc"[n % 4]
        found.append([Card(suit, rank) for rank in range(13, 0, -1)])
    return SpiderState(cols, _cards(stock), found)


def _profile(**kwargs):
    base = dict(
        time_limit_s=8,
        max_steps=6,
        tactical_nodes=80,
        tactical_time_s=0.3,
        tactical_max_cost=1,
        consult_portfolio=False,
        strategic_width=2,
        max_width=3,
        rss_abort_mb=8192,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _kings():
    return {4: "ks", 5: "kd", 6: "kc", 7: "kh", 8: "ks", 9: "kd"}


def _productive():
    columns = {
        0: ("5h", "9c 2s"),
        1: "3d",
        2: "10s",
        3: "3c",
    }
    columns.update(_kings())
    return _state(columns, stock="ah 4c 6d 7c 8d 3s 4h 6s 7d 2s")


def _expensive():
    columns = {
        0: ("5h", "9c 4d 8s 2c"),
        1: "3d",
        2: "9h",
        3: "5s",
        4: "10d",
        5: "ks",
        6: "kd",
        7: "kc",
        8: "kh",
        9: "ks",
    }
    return _state(columns, stock="ah 4c 6d 7c 8d 3s 4h 6s 7d 2s")


def _waste():
    return _state(
        {0: "7h", 1: "ks", 2: "kd", 3: "kc", 4: "2s", 5: "3d", 6: "4c", 7: "5s", 8: "9d"},
        stock="6h 4d 3s 2d 5d 9c 8c 3c ah 2c",
    )


def _covered_but_useful_deal():
    return _state(
        {
            0: ("5h", "kc"),
            1: "7h",
            2: "ks",
            3: "kd",
            4: "2s",
            5: "3d",
            6: "4c",
            7: "5s",
            8: "9d",
            9: "8c",
        },
        stock="as 6h 4d 3s 2d 5d 9c 8s 3c ah",
    )


def _other_column():
    columns = {4: ("4h", "8d 3c"), 5: "4d", 6: "9s"}
    columns.update({0: "ks", 1: "kd", 2: "kc", 3: "kh", 7: "ks", 8: "kd", 9: "kc"})
    return _state(columns, stock="ah 2c 4s 5d 6c 7h 8c 9h 10c js")


def test_controller_commits_to_a_multi_action_objective():
    state = _productive()
    result = solve(state, _profile(max_steps=3))
    assert result.actions[:2] == ((0, 1, 1), (0, 2, 1))
    assert result.decisions[1].reason.startswith("continued: committed plan")
    assert result.decisions[1].chosen_id == result.decisions[0].chosen_id
    assert result.actions[0] != ("deal",)
    trial = state.clone()
    apply_action(trial, result.actions[0])
    apply_action(trial, result.actions[1])
    assert face_down_count(trial) == face_down_count(state) - 1


def test_controller_abandons_a_plan_when_the_benefit_disappears():
    state = _productive()
    useful = ((0, 1, 1), (0, 2, 1))
    assert plan_still_worth_following(state, useful) is True
    assert abandonment_reason(state, useful) is None
    # The park is legal, and the deal is legal without it. Doing both is not
    # better than dealing, so the plan is dropped before the park is played.
    parked = ((0, 1, 1), ("deal",))
    reason = abandonment_reason(state, parked)
    assert reason == "abandoned: committed plan no longer improves on the alternatives"
    assert plan_still_worth_following(state, parked) is False
    illegal = ((0, 2, 1),)
    assert abandonment_reason(state, illegal) == "abandoned: committed plan is no longer legal"


def test_productive_preparation_beats_an_immediate_deal():
    state = _productive()
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    assert compared.choice == "prepare"
    assert compared.option is not None
    assert compared.option.fd_gain >= 1
    assert compared.prep_net > compared.deal_net
    result = solve(state, _profile(max_steps=2))
    assert result.actions[0] != ("deal",)
    played = state.clone()
    for action in result.actions:
        apply_action(played, action)
    assert face_down_count(played) < face_down_count(state)


def test_wasteful_preparation_loses_to_an_immediate_deal():
    state = _waste()
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    assert compared.choice == "deal"
    assert compared.option is None
    result = solve(state, _profile(max_steps=1, strategic_width=3, max_width=3))
    assert result.actions == (("deal",),)
    assert result.decisions[0].chosen_kind == "DEAL_NOW"
    assert "6H" in " ".join(result.decisions[0].evidence)


def test_exact_incoming_column_alignment_is_named():
    state = _waste()
    notes = " ".join(incoming_alignment_notes(state))
    assert "fact: column 1 incoming 6H continues 7H" in notes
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    assert "fact: column 1 incoming 6H continues 7H" in " ".join(compared.evidence)


def test_dealing_that_covers_a_needed_card_is_visible():
    state = _productive()
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    text = " ".join(compared.evidence)
    assert "estimate: dealing covers column 1 before its face-down card is exposed" in text
    assert compared.choice == "prepare"


def test_a_beneficial_deal_may_cover_material():
    state = _covered_but_useful_deal()
    assert face_down_count(state) == 1
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    text = " ".join(compared.evidence)
    assert "fact: column 2 incoming 6H continues 7H" in text
    assert "covers column 1" in text
    assert compared.choice == "deal"
    result = solve(state, _profile(max_steps=1, strategic_width=3, max_width=3))
    assert result.actions[0] == ("deal",)
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    assert face_down_count(dealt) == 1


def test_empty_columns_are_not_rewarded_on_their_own():
    assert prefer_preparation(
        fd_gain=0, bond_gain=0, found_gain=0, tableau_cost=2, prep_net=-3.0, deal_net=-1.0
    ) is False
    state = _state(
        {0: "7h", 1: "ks", 2: "kd", 3: "kc", 4: "2s", 5: "3d", 6: "4c", 7: "5s", 8: "9d"},
        stock="6h 4d 3s 2d 5d 9c 8c 3c ah 2c",
    )
    assert state.columns[9].is_empty()
    assert state.can_move(0, 9, 1)
    result = solve(state, _profile(max_steps=1, strategic_width=4, max_width=4))
    assert result.actions[0] == ("deal",)
    assert result.decisions[0].chosen_kind == "DEAL_NOW"


def test_recoverable_temporary_park_is_used_to_expose():
    state = _productive()
    result = solve(state, _profile(max_steps=2))
    assert result.actions[0] == (0, 1, 1)
    parked = state.clone()
    apply_action(parked, result.actions[0])
    assert parked.can_move(1, 3, 1)
    assert result.actions[1] == (0, 2, 1)
    assert face_down_count(parked) == face_down_count(state)


def test_failed_objective_does_not_suppress_unrelated_moves():
    state = _state(
        {
            0: "9c 5h",
            1: "9d 6c",
            2: "2d kh",
            3: "3c kd",
            4: "4d kc",
            5: "8d ks",
            6: "9s kh",
            7: "8c kd",
            8: "7s kc",
            9: "3s ks",
        }
    )
    result = solve(state, _profile(max_steps=2, strategic_width=2, max_width=2, tactical_max_cost=1))
    assert result.decisions[0].status == "failed"
    failed_id = result.decisions[0].chosen_id
    assert failed_id not in result.decisions[1].considered
    assert result.decisions[1].considered
    assert any(item != failed_id for item in result.decisions[1].considered)


def test_failed_realisation_does_not_make_the_objective_impossible():
    state = _productive()
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None and compared.option is not None and compared.option.objective is not None
    objective = compared.option.objective
    missed = realize_objective(
        state,
        objective,
        mode=RealizationMode.FAST_BOUNDED,
        max_cost=1,
        max_nodes=80,
        time_limit_s=0.3,
        beam=16,
    )
    assert missed.status != RealizationStatus.FOUND
    found = realize_objective(
        state,
        objective,
        mode=RealizationMode.FAST_BOUNDED,
        max_cost=6,
        max_nodes=600,
        time_limit_s=1.0,
        beam=32,
    )
    assert found.status == RealizationStatus.FOUND
    assert found.target_verified is True
    assert soft_failure_id("STRETCH:create_workspace") is True
    assert soft_failure_id("PORTFOLIO:expose_c1_d1") is True
    assert soft_failure_id("PARK:move 1 2 1") is False
    assert soft_failure_id("TACTICAL:move 1 2 1") is False


def test_premature_deal_can_be_revisited():
    state = _expensive()
    before = face_down_count(state)
    compared = compare_before_deal(state, [], _profile(), 8)
    assert compared is not None
    assert compared.choice == "deal"
    assert any(item.fd_gain >= 1 for item in compared.saved)
    result = solve(state, _profile(max_steps=4, time_limit_s=15))
    assert any(event.startswith("revisit:") for event in result.events)
    assert result.actions
    assert result.actions[0] != ("deal",)
    assert ("deal",) not in result.actions
    assert result.actions[:4] == ((0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1))
    trial = state.clone()
    for action in result.actions:
        apply_action(trial, action)
    assert face_down_count(trial) < before
    assert any(decision.reason.startswith("continued: committed plan") for decision in result.decisions)


def test_stock_empty_position_with_legal_moves_is_not_no_actions():
    opening = opening_from_deal(ROOT / "deals" / "4925153.txt")
    trial = opening.clone()
    detail = replay_actions_detailed(trial, list(V107_LINE))
    assert detail["mobilityware_moves"] == 27
    assert face_down_count(trial) == 36
    assert len(trial.foundations) == 0
    assert len(trial.stock) == 0
    legal = all_legal_actions(trial)
    assert len(legal) == 6
    assert classify_stall(legal_count=6, generated_count=15, visible_count=0, suppressed=6) == (
        "objectives suppressed after failure"
    )
    assert classify_stall(legal_count=0, generated_count=0, visible_count=0) == "no legal moves"
    assert classify_stall(legal_count=6, generated_count=0, visible_count=0) == (
        "no strategic objectives generated"
    )
    result = solve(trial, _profile(max_steps=1, time_limit_s=2, consult_portfolio=False))
    assert "no legal continuation" not in result.stop_reason
    assert result.stop_reason != "no legal moves"
    if result.actions:
        assert result.actions[0] in legal


def test_played_moves_stay_legal_and_use_corrected_costs():
    state = _productive()
    result = solve(state, _profile(max_steps=3))
    detail = replay_actions_detailed(state.clone(), list(result.actions))
    assert detail["mobilityware_moves"] == result.cumulative_g
    assert result.replay["ok"] is True
    assert result.replay["mobilityware_moves"] == result.suffix_mw
    for action in result.actions:
        if action != ("deal",):
            assert action[2] >= 1


def test_a_finished_route_is_replay_verified():
    hearts = "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah"
    state = _state({0: hearts, 1: "kh"}, foundations=7)
    result = solve(state, _profile(max_steps=2))
    assert result.status == "SOLVED_VALID"
    assert result.cumulative_g == 1
    assert result.replay["ok"] is True
    assert result.replay["solved"] is True
    assert result.replay["mobilityware_moves"] == 1
    assert result.provenance["prefix_injected"] is False


def test_cold_mode_does_not_load_reference_routes():
    state = _productive()
    try:
        solve(state, _profile(max_steps=1), mode="cold", incumbent_actions=(("deal",),))
    except ValueError as exc:
        assert "cold mode" in str(exc)
    else:
        raise AssertionError("cold mode accepted an incumbent sequence")
    result = solve(state, _profile(max_steps=2), mode="cold")
    assert result.mode == "cold"
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["assisted_suffix"] is False
    assert result.provenance["reproduced_incumbent"] is False


def test_time_and_memory_limits_remain_distinct():
    state = _productive()
    timed = solve(state, _profile(time_limit_s=0, max_steps=4))
    assert timed.status == "TIME_LIMIT"
    assert timed.solved is False
    assert timed.actions == ()
    limited = solve(state, _profile(rss_abort_mb=-1, max_steps=4))
    assert limited.status == "MEMORY_LIMIT"
    assert limited.solved is False
    assert limited.status != "EXHAUSTED"


def test_preparation_generalises_beyond_the_benchmark_deal():
    state = _other_column()
    compared = compare_before_deal(state, [], _profile(), 5)
    assert compared is not None
    assert compared.choice == "prepare"
    assert compared.option is not None
    assert compared.option.actions[0][0] == 4
    result = solve(state, _profile(max_steps=2))
    assert result.actions[0][0] == 4
    assert result.actions[0] != ("deal",)
    assert any(decision.reason.startswith("continued:") for decision in result.decisions)
    played = state.clone()
    for action in result.actions:
        apply_action(played, action)
    assert face_down_count(played) < face_down_count(state)
