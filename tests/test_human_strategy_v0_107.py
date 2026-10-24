"""Contract tests for the v0.107 integrated human-strategy controller.

Fixtures are small constructed deals. They do not replay the 172 or the 185.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.human_strategy.context import build_context
from spider.human_strategy.controller import _cycle, _execute, _identity, _Line, solve
from spider.human_strategy.evaluation import (
    admissible_remaining,
    cost_led_action,
    mixed_boundaries,
    same_suit_bonds,
)
from spider.human_strategy.portfolio import Candidate, build_candidates
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.registry import PRINCIPLES
from spider.metrics import format_action, replay_actions_detailed
from spider.planner.lower_bounds import compute_objective_lower_bound
from spider.planner.strategic_objectives import ObjectiveKind, PriorityComponents, StrategicObjective
from spider.research_actions import apply_action, face_down_count, step_cost

HEARTS = "qh jh 10h 9h 8h 7h 6h 5h 4h 3h 2h ah"


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
        time_limit_s=5,
        max_steps=4,
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


def _prep():
    return _state(
        {
            0: "6h",
            1: "7h",
            2: "ks",
            3: "qd",
            4: "jc",
            5: "10s",
            6: "9d",
            7: "8c",
            8: "5s",
            9: "4d",
        },
        stock="9c 2s 4c 3s 2d 5d 4h 3c ah 2c",
    )


def _micro():
    return _state({0: HEARTS, 1: "kh"}, foundations=7)


def test_registry_names_are_real_tests():
    module = sys.modules[__name__]
    for row in PRINCIPLES:
        assert row["status"] in {"ACTIVE", "CONDITIONAL", "OBSERVATIONAL", "NOT IMPLEMENTED"}
        assert callable(getattr(module, row["test"], None)), row["id"]


def test_profiles_keep_one_worker_and_extended_is_explicit():
    assert resolve_profile("smoke").name == "smoke"
    assert resolve_profile("smoke").time_limit_s == 20
    widened = resolve_profile("pilot").with_overrides(workers=4, strategic_width=1, max_width=1)
    assert widened.workers == 1
    try:
        resolve_profile("deep")
    except ValueError as exc:
        assert "extended" in str(exc)
    else:
        raise AssertionError("unknown profile was accepted")


def test_exact_mobilityware_scoring_on_controller_actions():
    state = _state({0: "8h", 2: "ks"}, stock="9c 7h 2c 3c 4c 5c 6c 4d 3d 2d")
    assert step_cost(state, (0, 1, 1)) == 0
    assert step_cost(state, ("deal",)) == 1
    partial = _state({0: ("qs", "5h"), 1: ""})
    assert step_cost(partial, (0, 1, 1)) == 1
    assert state.can_deal() is True


def test_known_hidden_card_is_not_accessible():
    hidden = Card("h", 7)
    visible = Card("h", 7)
    assert hidden == visible
    assert hidden is not visible
    columns = [Column([hidden], [Card("c", 9)]), Column([], [visible])]
    columns.extend(Column([], [Card("s", 13)]) for _ in range(8))
    state = SpiderState(columns, _cards("as 2s 3s 4s 5s 6s 7s 8s 9s 10s"))
    ctx = build_context(state, 0)
    sevens = [card for card in ctx.cards if card.rank == 7 and card.suit == "h"]
    assert len(sevens) == 2
    assert sum(card.accessible for card in sevens) == 1
    assert any(card.zone == "face_down" and not card.accessible for card in sevens)
    assert ctx.known_hidden()
    stock_cards = [card for card in ctx.cards if card.zone == "stock"]
    assert stock_cards and all(not card.accessible for card in stock_cards)
    assert "AS" in ctx.incoming_labels


def test_duplicate_physical_cards_stay_distinct():
    test_known_hidden_card_is_not_accessible()


def test_costly_preparation_beats_immediate_deal():
    state = _prep()
    assert cost_led_action(state) == ("deal",)
    result = solve(state, _profile(max_steps=2))
    assert result.actions[0] == (0, 1, 1)
    assert result.actions[1] == ("deal",)
    assert result.decisions[0].chosen_kind == "PREPARE"
    assert result.decisions[0].cost_led == "deal"
    assert "6H" in " ".join(result.decisions[0].evidence) or "incoming column 1 is 9C" in " ".join(result.decisions[0].evidence)
    assert result.decisions[1].reason.startswith("held") or result.decisions[1].reason.startswith("continued")
    prepared = state.clone()
    apply_action(prepared, (0, 1, 1))
    apply_action(prepared, ("deal",))
    dealt = state.clone()
    apply_action(dealt, ("deal",))
    assert same_suit_bonds(prepared) > same_suit_bonds(dealt)
    assert result.suffix_mw == 2
    assert result.replay["mobilityware_moves"] == 2

    with_empty = _state(
        {0: "6h", 1: "7h", 2: "ks", 3: "qd", 4: "jc", 5: "10s", 6: "9d", 7: "8c"},
        stock="9c 2s 4c 3s 2d 5d 4h 3c ah 2c",
    )
    assert with_empty.can_deal() is True
    led = cost_led_action(with_empty)
    assert led != ("deal",)
    assert step_cost(with_empty, led) == 0
    again = solve(with_empty, _profile(max_steps=2))
    assert again.actions[0] == (0, 1, 1)
    assert again.decisions[0].chosen_kind == "PREPARE"


def test_zero_benefit_shuffle_does_not_delay_the_deal():
    state = _state(
        {
            0: "6c",
            1: "5h",
            2: "2s",
            3: "3d",
            4: "4c",
            5: "9s",
            6: "8d",
            7: "7h",
            8: "ks",
            9: "qd",
        },
        stock="as 2c 3h 4s 5d 6h 7s 9h 9d 10h",
    )
    assert cost_led_action(state) == ("deal",)
    assert state.can_move(1, 0, 1)
    result = solve(state, _profile(max_steps=2, strategic_width=3, max_width=3))
    assert result.actions
    assert result.actions[0] == ("deal",)
    played = [decision for decision in result.decisions if decision.actions]
    assert played[0].chosen_kind == "DEAL_NOW"
    assert played[0].status in {"achieved", "partial"}
    assert any("DEAL_NOW:deal" in decision.considered for decision in result.decisions)
    for decision in result.decisions:
        if decision is played[0]:
            break
        assert decision.status == "failed"
        assert decision.actions == ()


def test_immediate_deal_beats_wasteful_preparation():
    state = _state(
        {0: "7h", 1: "ks", 2: "kd", 3: "kc", 4: "2s", 5: "3d", 6: "4c", 7: "5s", 8: "9d"},
        stock="6h 4d 3s 2d 5d 9c 8c 3c ah 2c",
    )
    result = solve(state, _profile(max_steps=1, strategic_width=3, max_width=3))
    assert result.actions[0] == ("deal",)
    assert result.decisions[0].chosen_kind == "DEAL_NOW"
    text = " ".join(result.decisions[0].evidence)
    assert "6H" in text
    assert state.can_deal() is True


def test_immediate_deal_beats_a_free_giveaway_of_the_landing():
    state = _state(
        {0: "7h", 1: "ks", 2: "kd", 3: "kc", 4: "2s", 5: "3d", 6: "4c", 7: "5s", 8: "9d"},
        stock="6h 4d 3s 2d 5d 9c 8c 3c ah 2c",
    )
    # Column 9 is empty, so giving 7H away is a legal zero-cost mistake.
    assert state.columns[9].is_empty()
    assert state.can_deal() is True
    result = solve(state, _profile(max_steps=1, strategic_width=4, max_width=4))
    assert result.actions[0] == ("deal",)
    assert result.decisions[0].cost_led != "deal"


def test_zero_cost_transfer_is_taken_when_it_improves_the_landing():
    state = _state(
        {0: "8h", 2: "ks", 3: "kd", 4: "kc", 5: "2s", 6: "3d", 7: "4c", 8: "5s", 9: "9d"},
        stock="9c 7h 4d 3s 2d 5d 8c 3c ah 2c",
    )
    assert state.columns[1].is_empty()
    assert state.can_deal() is True
    assert step_cost(state, (0, 1, 1)) == 0
    result = solve(state, _profile(max_steps=2))
    assert result.actions[0] == (0, 1, 1)
    assert result.decisions[0].chosen_kind == "ZERO_COST"
    assert result.decisions[0].actual_cost == 0
    after = state.clone()
    apply_action(after, (0, 1, 1))
    assert after.can_deal() is True
    assert after.columns[0].is_empty()


def test_completion_cost_beats_a_free_relocate():
    state = _micro()
    led = cost_led_action(state)
    assert step_cost(state, led) == 0
    result = solve(state, _profile(max_steps=2))
    assert result.status == "SOLVED_VALID"
    assert result.actions == ((0, 1, 12),)
    assert result.cumulative_g == 1
    assert result.solved is True
    assert result.foundations == 8
    assert result.replay["ok"] is True
    assert result.replay["mobilityware_moves"] == 1
    assert result.replay["solved"] is True
    assert result.decisions[0].chosen_kind == "FOUNDATION"
    assert result.provenance["new_discovery"] is True
    assert result.provenance["prefix_injected"] is False


def test_foundation_removal_replans():
    state = _state({0: HEARTS, 1: "kh", 2: "4c"}, foundations=7)
    result = solve(state, _profile(max_steps=2))
    assert result.decisions[0].chosen_kind == "FOUNDATION"
    assert any(event == "replan: foundation removed" for event in result.events)
    assert len(result.decisions) >= 2
    assert result.solved is False
    assert result.foundations == 8


def test_revealing_mixed_move_beats_a_cosmetic_join():
    state = _state(
        {
            0: "5s",
            1: "6s",
            2: "ks",
            3: "kd",
            4: "kc",
            5: "2d",
            6: "3c",
            7: "4d",
            8: ("4h", "9c"),
            9: "10s",
        }
    )
    assert cost_led_action(state) == (0, 1, 1)
    before = face_down_count(state)
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0] == (8, 9, 1)
    assert result.decisions[0].chosen_kind == "REVEAL"
    after = state.clone()
    apply_action(after, result.actions[0])
    assert face_down_count(after) == before - 1


def test_same_suit_join_beats_a_dead_park():
    state = _state(
        {0: "6h", 1: "5h", 2: "6c", 3: "ks", 4: "qd", 5: "jc", 6: "10s", 7: "9d", 8: "8c", 9: "4d"}
    )
    assert state.can_move(1, 2, 1)
    assert cost_led_action(state) != (1, 0, 1)
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0] == (1, 0, 1)
    assert result.decisions[0].chosen_kind == "SAME_SUIT"


def test_controller_does_not_split_a_built_run():
    state = _state(
        {
            0: "8h 7h 6h",
            1: "7c",
            2: "4d",
            3: "3d",
            4: "ks",
            5: "qc",
            6: "2s",
            7: "9c",
            8: "10d",
            9: "5s",
        }
    )
    assert state.can_move(0, 1, 1)
    assert cost_led_action(state) == (0, 1, 1)
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0] != (0, 1, 1)
    assert result.decisions[0].chosen_kind == "SAME_SUIT"
    kept = state.clone()
    apply_action(kept, result.actions[0])
    assert len(kept.columns[0].face_up) == 3


def test_longer_run_is_extended_first():
    state = _state(
        {
            0: "8h 7h 6h",
            1: "5h",
            2: "4d",
            3: "3d",
            4: "ks",
            5: "qc",
            6: "js",
            7: "2s",
            8: "9c",
            9: "10d",
        }
    )
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0] == (1, 0, 1)
    assert result.decisions[0].chosen_kind == "SAME_SUIT"


def test_king_move_depends_on_what_it_frees():
    useless = _state(
        {0: "kh", 2: "6h", 3: "5h", 4: "qd", 5: "jc", 6: "10s", 7: "9d", 8: "8c", 9: "4s"}
    )
    assert cost_led_action(useless) == (0, 1, 1)
    assert step_cost(useless, (0, 1, 1)) == 0
    result = solve(useless, _profile(max_steps=1))
    assert result.actions[0] == (3, 2, 1)
    assert result.decisions[0].chosen_kind == "SAME_SUIT"

    revealing = _state(
        {
            0: ("3h", "kh"),
            2: "6s",
            3: "5s",
            4: "qd",
            5: "jc",
            6: "10d",
            7: "9c",
            8: "8d",
            9: "4c",
        }
    )
    before = face_down_count(revealing)
    result = solve(revealing, _profile(max_steps=1))
    assert result.actions[0] == (0, 1, 1)
    assert result.decisions[0].chosen_kind == "REVEAL"
    after = revealing.clone()
    apply_action(after, result.actions[0])
    assert face_down_count(after) == before - 1
    assert 16 in result.decisions[0].principles


def test_empty_column_is_spent_to_reveal():
    state = _state(
        {
            0: ("4h", "9c"),
            2: "6s",
            3: "5s",
            4: "kd",
            5: "kc",
            6: "2d",
            7: "3c",
            8: "8d",
            9: "4s",
        }
    )
    assert state.columns[1].is_empty()
    led = cost_led_action(state)
    assert step_cost(state, led) == 0
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0] == (0, 1, 1)
    assert result.decisions[0].actual_cost == 1
    assert result.decisions[0].chosen_kind == "REVEAL"


def test_backward_prerequisite_is_exposed_first():
    state = _state(
        {
            0: ("3h", "9c"),
            1: "2h",
            2: "10s",
            3: "6d",
            4: "5d",
            5: "ks",
            6: "kd",
            7: "kc",
            8: "4c",
            9: "8s",
        }
    )
    ctx = build_context(state, 0)
    assert any("3H" in note and "prerequisite" in note for note in ctx.notes)
    result = solve(state, _profile(max_steps=1))
    assert result.actions[0][0] == 0
    text = " ".join(result.decisions[0].evidence)
    assert "prerequisite" in text
    assert "3H" in text


def test_legal_move_that_misses_its_purpose_is_not_success():
    state = _state({0: "6c", 1: "5h"})
    candidate = Candidate(
        candidate_id="SAME_SUIT:move 2 1 1",
        kind="SAME_SUIT",
        purpose="Extend a same-suit run.",
        principles=(9,),
        actions=((1, 0, 1),),
        objective=None,
        immediate_cost=1,
        cost_is_exact=True,
        expected_benefit=1.0,
        structural_risk=0.0,
        horizon="test",
        feasibility="legal now",
        evidence=(),
        admissible_lb=0,
        projected=1.0,
        solves=False,
    )
    status, _cost, new_state, note, _remaining, applied = _execute(state, candidate, _profile(), 1.0)
    assert status == "failed"
    assert applied == ()
    assert new_state.columns[1].top().suit == "h"
    assert "did not meet" in note


def test_objective_realiser_deals_and_stretch_can_fail():
    state = _prep()
    bound = compute_objective_lower_bound(kind="DEAL_NOW", state=state)
    objective = StrategicObjective(
        kind=ObjectiveKind.DEAL_NOW,
        objective_id="deal_now_test",
        description="Deal the next row",
        target_key="stock_epoch_advanced",
        target_params={"deals_before": len(state.stock) // 10},
        hard_preconditions=("stock has at least 10 cards",),
        hard_evidence=("fact: test objective",),
        admissible_lb=bound.h_admissible,
        admissible_breakdown=bound,
        heuristic_est_cost=1.0,
        heuristic_est_benefit=0.0,
        priority=PriorityComponents(stock=1.0),
        foundation_relevance="none",
        workspace_relevance="none",
        stock_relevance="primary",
        explanation="test",
    )
    candidate = Candidate(
        candidate_id="PORTFOLIO:deal_now_test",
        kind="DEAL_NOW",
        purpose=objective.description,
        principles=(4, 24),
        actions=(),
        objective=objective,
        immediate_cost=1,
        cost_is_exact=False,
        expected_benefit=0.0,
        structural_risk=0.0,
        horizon="test",
        feasibility="predicate",
        evidence=objective.hard_preconditions,
        admissible_lb=bound.h_admissible,
        projected=1.0,
        solves=False,
    )
    status, cost, new_state, _note, _remaining, applied = _execute(state, candidate, _profile(), 1.0)
    assert status == "achieved"
    assert applied == (("deal",),)
    assert cost == 1
    assert len(new_state.stock) == 0


def test_width_limits_the_considered_set():
    result = solve(_prep(), _profile(max_steps=1, strategic_width=2))
    assert len(result.decisions[0].considered) == 2
    assert "WORKSPACE:move 10 9 1" not in result.decisions[0].considered or len(result.decisions[0].considered) == 2


def test_failed_objective_backtracks_then_widens():
    state = _stretch_board()
    narrow = solve(state, _profile(max_steps=2, strategic_width=1, max_width=2, tactical_max_cost=1))
    assert narrow.decisions[0].chosen_id == "STRETCH:create_workspace"
    assert narrow.decisions[0].status == "failed"
    assert any(event.startswith("widen:") for event in narrow.events)
    assert narrow.decisions[1].chosen_id != "STRETCH:create_workspace"
    assert narrow.widens == 1

    wide = solve(state, _profile(max_steps=2, strategic_width=2, max_width=2, tactical_max_cost=1))
    assert wide.decisions[0].chosen_id == "STRETCH:create_workspace"
    assert wide.decisions[0].status == "failed"
    assert any(event.startswith("backtrack:") for event in wide.events)
    assert wide.backtracks >= 1
    assert wide.decisions[1].state_id == wide.decisions[0].state_id
    assert "STRETCH:create_workspace" not in wide.decisions[1].considered


def test_failed_objective_is_not_retried_on_the_same_state():
    result = solve(
        _stretch_board(),
        _profile(max_steps=2, strategic_width=2, max_width=2, tactical_max_cost=1),
    )
    assert result.decisions[0].status == "failed"
    assert result.decisions[1].state_id == result.decisions[0].state_id
    assert "STRETCH:create_workspace" not in result.decisions[1].considered


def test_progressive_widening_starts_at_the_configured_width():
    result = solve(_prep(), _profile(max_steps=1, strategic_width=2, max_width=4))
    assert result.profile["strategic_width"] == 2
    assert len(result.decisions[0].considered) == 2
    assert result.widens == 0


def test_rehandling_does_not_become_an_admissible_bound():
    tidy = _state({0: "7h 6h", 1: "ks"}, stock="as 2s 3s 4s 5s 6s 7s 8s 9s 10s")
    messy = _state({0: "7h 6c", 1: "ks"}, stock="as 2s 3s 4s 5s 6s 7s 8s 9s 10s")
    assert mixed_boundaries(messy) > mixed_boundaries(tidy)
    assert admissible_remaining(tidy) == admissible_remaining(messy)
    ceiling = admissible_remaining(tidy)
    for state in (tidy, messy):
        result = solve(state, _profile(max_steps=2), mode="optimise", incumbent_mw=ceiling)
        assert result.actions == ()
        assert result.status == "EXHAUSTED"
        assert any(event.startswith("incumbent bound:") for event in result.events)
        assert result.solved is False


def test_warm_ceiling_prunes_and_cold_mode_refuses_injection():
    state = _micro()
    try:
        solve(state, _profile(), mode="cold", incumbent_actions=(("deal",),))
    except ValueError as exc:
        assert "cold mode" in str(exc)
    else:
        raise AssertionError("cold mode accepted an incumbent sequence")
    cold = solve(state, _profile(max_steps=2))
    assert cold.status == "SOLVED_VALID"
    assert cold.provenance["new_discovery"] is True
    assert cold.provenance["reproduced_incumbent"] is False
    warm = solve(
        state,
        _profile(max_steps=2),
        mode="optimise",
        incumbent_actions=cold.actions,
        incumbent_mw=10,
    )
    assert warm.status == "SOLVED_VALID"
    assert warm.actions == cold.actions
    assert warm.provenance["reproduced_incumbent"] is True
    assert warm.provenance["new_discovery"] is False
    assert warm.provenance["prefix_injected"] is False
    assert warm.provenance["assisted_suffix"] is False
    pruned = solve(state, _profile(max_steps=2), mode="optimise", incumbent_mw=0)
    assert pruned.actions == ()
    assert pruned.solved is False
    assert any("incumbent bound" in event for event in pruned.events)


def test_time_and_memory_limits_stop_cleanly():
    state = _prep()
    timed = solve(state, _profile(time_limit_s=0, max_steps=4))
    assert timed.status == "TIME_LIMIT"
    assert timed.solved is False
    assert timed.actions == ()
    limited = solve(state, _profile(rss_abort_mb=-1, max_steps=4))
    assert limited.status == "MEMORY_LIMIT"
    assert limited.solved is False


def test_repeat_solve_is_deterministic_and_cache_is_context_sensitive():
    state = _prep()
    first = solve(state, _profile(max_steps=2))
    second = solve(state, _profile(max_steps=2))
    assert first.actions == second.actions
    assert [item.chosen_id for item in first.decisions] == [item.chosen_id for item in second.decisions]
    profile = _profile()
    ctx = build_context(state, 0)
    full = build_candidates(ctx, profile)
    blocked = full[0].candidate_id
    reduced = build_candidates(ctx, profile, blocked_ids=(blocked,))
    assert blocked not in {item.candidate_id for item in reduced}
    later = build_context(state, 5)
    shifted = build_candidates(later, profile)
    assert shifted[0].projected == full[0].projected + 5


def test_cycle_guard_rejects_a_repeat_at_no_better_cost():
    state = _prep()
    other = _micro()
    line = _Line(other, 0, [], {_identity(state): 0, _identity(other): 0})
    assert _cycle(line, state, 0) is True
    assert _cycle(line, other, 1) is False


def test_unrestricted_deal_stays_legal_with_an_empty_column():
    state = _state({0: "7h", 1: "ks"}, stock="6h 5c 4c 3c 2c 9d 8d 7d 6d 5d")
    assert state.columns[2].is_empty()
    assert state.can_deal() is True
    assert ("deal",) in state.enumerate_legal_actions()


def test_opening_cold_step_is_legal_and_does_not_read_a_solution():
    from spider.research_actions import opening_from_deal

    opening = opening_from_deal(ROOT / "deals" / "4925153.txt")
    result = solve(opening, _profile(max_steps=2, consult_portfolio=True, time_limit_s=15))
    assert result.mode == "cold"
    assert result.provenance["prefix_injected"] is False
    assert result.decisions
    assert result.actions
    trial = opening.clone()
    detail = replay_actions_detailed(trial, list(result.actions))
    assert detail["mobilityware_moves"] == result.suffix_mw
    assert result.status != "INVALID"
    assert result.solved is False


def test_portfolio_does_not_displace_a_concrete_preparation():
    state = _prep()
    result = solve(state, _profile(max_steps=1, consult_portfolio=True))
    assert result.decisions[0].chosen_kind == "PREPARE"
    ctx = build_context(state, 0)
    ranked = build_candidates(ctx, _profile(consult_portfolio=True))
    assert any(item.candidate_id.startswith("PORTFOLIO:") for item in ranked)
    assert ranked[0].kind == "PREPARE"


def _stretch_board() -> SpiderState:
    # One mixed peel is legal. No same-suit join, no face-down card, no empty column.
    return _state(
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
