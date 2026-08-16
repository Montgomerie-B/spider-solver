"""Permanent-move lifecycle classification and ordering regressions."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.move_lifecycle import (
    BoundedCompensatingBenefit,
    PlacementClass,
    assess_tableau_move,
    stable_join_dominates,
    with_bounded_compensation,
)
from spider.search import order_moves


def _card(suit: str, rank: int) -> Card:
    return Card(suit, rank)


def _state(*face_up_columns) -> SpiderState:
    columns = [Column([], list(cards)) for cards in face_up_columns]
    columns.extend(Column([], []) for _ in range(10 - len(columns)))
    return SpiderState(columns, [])


def test_four_placement_classes_are_explicit():
    same = _state([_card("d", 7)], [_card("d", 8)])
    stable = assess_tableau_move(same, (0, 1, 1))
    provisional = assess_tableau_move(
        same,
        (0, 1, 1),
        provisional_reason="receiver column must be cleared before the next deal",
    )
    mixed_state = _state(
        [_card("d", 7)],
        [_card("c", 8)],
        [_card("d", 8)],
    )
    mixed = assess_tableau_move(mixed_state, (0, 1, 1))
    workspace = assess_tableau_move(
        _state([_card("s", 7)], []),
        (0, 1, 1),
    )

    assert stable.placement_class == PlacementClass.STABLE_SAME_SUIT_JOIN
    assert provisional.placement_class == PlacementClass.PROVISIONAL_SAME_SUIT_JOIN
    assert mixed.placement_class == PlacementClass.MIXED_SUIT_PARK
    assert workspace.placement_class == PlacementClass.WORKSPACE_PARK


def test_boundary_changes_exit_and_rehandling_are_recorded():
    state = _state(
        [_card("c", 8), _card("d", 7)],
        [_card("d", 8)],
    )
    result = assess_tableau_move(state, (0, 1, 1))
    assert result.same_suit_joins_created == ("8d-7d@c2",)
    assert result.same_suit_joins_broken == ()
    assert result.mixed_suit_boundaries_created == ()
    assert result.mixed_suit_boundaries_removed == ("8c-7d@c1",)
    assert result.estimated_rehandling_cost == 0
    assert result.future_exit_route
    assert result.proof_pruning_allowed is False


def test_mixed_park_has_concrete_exit_and_minimum_debt():
    state = _state(
        [_card("d", 7)],
        [_card("c", 8)],
        [_card("d", 8)],
    )
    result = assess_tableau_move(state, (0, 1, 1))
    assert result.mixed_suit_boundaries_created == ("8c-7d@c2",)
    assert result.future_exit_route == "move 7d-7d from c2 to c3 on same-suit 8d"
    assert result.exit_route_bounded
    assert result.estimated_rehandling_cost == 1
    assert result.projected_lifecycle_cost == 2


def test_stable_join_dominates_equal_comparable_uncompensated_park():
    stable = assess_tableau_move(
        _state([_card("d", 7)], [_card("d", 8)]),
        (0, 1, 1),
    )
    mixed = assess_tableau_move(
        _state([_card("d", 7)], [_card("c", 8)], [_card("d", 8)]),
        (0, 1, 1),
    )
    assert stable.immediate_cost == mixed.immediate_cost == 1
    assert stable_join_dominates(stable, mixed, comparable_effects=True)
    assert not stable_join_dominates(stable, mixed, comparable_effects=False)


def test_park_override_requires_bounded_saving_greater_than_debt():
    stable = assess_tableau_move(
        _state([_card("d", 7)], [_card("d", 8)]),
        (0, 1, 1),
    )
    mixed = assess_tableau_move(
        _state([_card("d", 7)], [_card("c", 8)], [_card("d", 8)]),
        (0, 1, 1),
    )
    insufficient = with_bounded_compensation(
        mixed,
        BoundedCompensatingBenefit(1, "one saved move", "bounded alternative"),
    )
    sufficient = with_bounded_compensation(
        mixed,
        BoundedCompensatingBenefit(2, "two saved moves", "bounded alternative"),
    )
    assert not insufficient.can_override_permanent_join
    assert stable_join_dominates(stable, insufficient, comparable_effects=True)
    assert sufficient.can_override_permanent_join
    assert not stable_join_dominates(stable, sufficient, comparable_effects=True)
    assert sufficient.ordering_key() < stable.ordering_key()


def test_park_without_bounded_exit_cannot_override_permanent_join():
    columns = [
        Column([], [_card("h", 9), _card("d", 7)]),
        Column([], [_card("c", 8)]),
    ]
    columns.extend(Column([], [_card("s", 5)]) for _ in range(8))
    mixed = assess_tableau_move(SpiderState(columns, []), (0, 1, 1))
    assert not mixed.exit_route_bounded
    attempted = with_bounded_compensation(
        mixed,
        BoundedCompensatingBenefit(3, "three saved moves", "claimed override"),
    )
    assert not attempted.can_override_permanent_join


def test_core_ordering_prefers_permanent_join_for_equal_local_effects():
    state = _state(
        [_card("d", 7)],
        [_card("d", 8)],
        [_card("c", 8)],
    )
    ordered = order_moves(state, [(0, 2, 1), (0, 1, 1)], depth=0)
    assert ordered == [(0, 1, 1), (0, 2, 1)]
