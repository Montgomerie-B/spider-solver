"""Sprint 1E — strategic objectives + admissible lower bounds tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.rules import MW_RULES, mw_move_cost
from spider.planner.lower_bounds import (
    budget_diagnostic,
    compute_objective_lower_bound,
    compute_solution_lower_bound,
    count_face_down,
    count_remaining_deals,
    free_move_cannot_reveal_face_down,
    max_reveals_per_paid_tableau_move,
)
from spider.planner.strategic_objectives import (
    ObjectiveKind,
    evaluate_target,
    generate_objective_portfolio,
)


def _pad(cols, stock=None):
    while len(cols) < 10:
        cols.append(Column([], [Card("d", 5 if len(cols) % 2 else 4)]))
    return SpiderState(cols, list(stock or []), [])


def test_free_move_cannot_reveal_and_is_paid_when_fd():
    ok, msg = free_move_cannot_reveal_face_down()
    assert ok, msg
    # Entire face-up to empty with face-down under is paid
    assert (
        mw_move_cost(
            cards_moved=2,
            source_face_up_count=2,
            dest_was_empty=True,
            source_face_down_count=1,
            rules=MW_RULES,
        )
        == 1
    )
    # Free only when no face-down
    assert (
        mw_move_cost(
            cards_moved=2,
            source_face_up_count=2,
            dest_was_empty=True,
            source_face_down_count=0,
            rules=MW_RULES,
        )
        == 0
    )


def test_hidden_revealing_move_is_paid_in_engine():
    st = _pad(
        [
            Column([Card("c", 3)], [Card("s", 9), Card("s", 8)]),
            Column([], []),
        ]
    )
    cost = st.move(0, 1, 2)
    assert cost == 1
    assert st.last_move[3] is True  # flipped


def test_face_down_and_deal_counts():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    st = SpiderState.from_cards(load_deal(deal))
    assert count_face_down(st) == 44  # 54-10 face-up tops? 5*10+4-10=44 yes
    assert count_remaining_deals(st) == 5


def test_solution_lb_admissible_not_naive():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    st = SpiderState.from_cards(load_deal(deal))
    lb = compute_solution_lower_bound(st)
    assert lb.face_down_count == 44
    assert lb.remaining_deals == 5
    # Naive would be 49; admissible must be <= naive and use dual-flip + deal cover
    assert lb.h_naive_face_down_plus_deals == 49
    assert lb.h_admissible <= lb.h_naive_face_down_plus_deals
    assert lb.h_admissible >= lb.remaining_deals
    naive_comp = lb.component("h_naive_face_down_plus_deals")
    assert naive_comp is not None and not naive_comp.admissible
    base = lb.component("h_base_admissible")
    assert base is not None and base.admissible


def test_max_reveals_per_paid_move_is_two():
    assert max_reveals_per_paid_tableau_move() == 2


def test_objective_expose_lb():
    st = _pad([Column([Card("c", 1), Card("c", 2)], [Card("s", 5)])])
    lb = compute_objective_lower_bound(
        kind="EXPOSE_REVEAL_PREFIX", min_reveals=2, state=st
    )
    assert lb.h_admissible >= 0
    # No deals remaining (empty stock) => paid >= 2
    assert count_remaining_deals(st) == 0
    assert lb.h_admissible == 2


def test_heuristics_excluded_from_admissible():
    lb = compute_solution_lower_bound(
        _pad([Column([Card("h", 1)], [Card("s", 2)])], [Card("c", r) for r in range(1, 11)])
    )
    for c in lb.components:
        if c.admissible:
            # names don't include heuristic
            assert "heuristic" not in c.name.lower()
            assert "est" not in c.name.lower()


def test_incumbent_and_target_prune_semantics():
    # g+h >= U prunes improvement
    d = budget_diagnostic(g=100, h=50, incumbent=150, target=149)
    assert d.g_plus_h == 150
    assert d.prune_vs_incumbent is True
    assert d.prune_vs_target is True  # 150 > 149
    d2 = budget_diagnostic(g=100, h=49, incumbent=150, target=149)
    assert d2.prune_vs_incumbent is False  # 149 < 150
    assert d2.prune_vs_target is False  # 149 > 149 is false; 149 == 149 not >
    assert d2.discretionary_slack_incumbent == 1
    assert d2.discretionary_slack_target == 0


def test_target_predicates():
    st = _pad(
        [
            Column([], [Card("c", 9), Card("c", 8)]),
            Column([], []),
        ]
    )
    assert evaluate_target(
        st, "same_suit_run_at_least", {"suit": "c", "min_len": 2}
    )
    assert evaluate_target(st, "empty_count_ge", {"min_empty": 1})
    assert evaluate_target(
        st, "column_top_is", {"column": 0, "suit": "c", "rank": 8}
    )
    assert evaluate_target(st, "column_empty", {"column": 1})
    # expose: column face-down reduction (not duplicate rank/suit elsewhere)
    st2 = _pad(
        [
            Column([Card("s", 3)], [Card("h", 2)]),
            Column([], [Card("s", 3)]),  # duplicate 3s already face-up
        ]
    )
    assert not evaluate_target(
        st2, "column_face_down_le", {"column": 0, "max_face_down": 0}
    )
    # Duplicate face-up elsewhere must NOT satisfy
    assert not evaluate_target(
        st2, "expose_card", {"column": 0, "suit": "s", "rank": 3}
    )
    st2.columns[1] = Column([], [])  # empty dest
    st2.move(0, 1, 1)  # flip 3s on col 0
    assert evaluate_target(
        st2, "column_face_down_le", {"column": 0, "max_face_down": 0}
    )


def test_portfolio_diversity_and_dedupe():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    st = SpiderState.from_cards(load_deal(deal))
    p = generate_objective_portfolio(st, cards=load_deal(deal), max_objectives=12)
    assert 6 <= len(p.objectives) <= 12
    kinds = {o.kind for o in p.objectives}
    # Must include multiple families when available
    assert ObjectiveKind.DEAL_NOW in kinds
    assert ObjectiveKind.CREATE_WORKSPACE in kinds
    assert ObjectiveKind.EXPOSE_REVEAL_PREFIX in kinds
    keys = [o.dedupe_key() for o in p.objectives]
    assert len(keys) == len(set(keys))


def test_portfolio_deterministic():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    p1 = generate_objective_portfolio(st, cards=cards)
    p2 = generate_objective_portfolio(st, cards=cards)
    assert [o.objective_id for o in p1.objectives] == [
        o.objective_id for o in p2.objectives
    ]


def test_remove_foundation_only_when_theo():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    cards = load_deal(deal)
    st = SpiderState.from_cards(list(cards))
    p = generate_objective_portfolio(st, cards=cards)
    # At opening no foundation theoretically available (1A: earliest after deal 2)
    removes = [o for o in p.objectives if o.kind == ObjectiveKind.REMOVE_FOUNDATION]
    assert removes == []


def test_duplicate_card_no_fixed_copy_in_advance_text():
    deal = ROOT / "deals" / "4925153.txt"
    if not deal.exists():
        pytest.skip("no fixture")
    p = generate_objective_portfolio(
        SpiderState.from_cards(load_deal(deal)), cards=load_deal(deal)
    )
    for o in p.objectives:
        if o.kind == ObjectiveKind.ADVANCE_FOUNDATION:
            assert "no fixed physical copy" in o.foundation_relevance


def test_unrelated_fixture_portfolio():
    stock = [Card("h", r) for r in range(1, 11)] * 5
    cols = [
        Column([Card("c", 2)], [Card("s", 9), Card("s", 8)]),
        Column([], []),
    ]
    st = _pad(cols, stock)
    p = generate_objective_portfolio(st, max_objectives=10)
    assert any(o.kind == ObjectiveKind.DEAL_NOW for o in p.objectives)
    assert any(o.kind == ObjectiveKind.CREATE_WORKSPACE for o in p.objectives)
    # CREATE already has empty — still can ask for empty_count >= 2
    assert any(
        o.kind == ObjectiveKind.CREATE_WORKSPACE
        and o.target_params.get("min_empty") == 2
        for o in p.objectives
    )


def test_foundations_predicate():
    ka = [Card("c", r) for r in range(13, 0, -1)]
    st = _pad([Column([], list(ka)), Column([], [])])
    st.move(0, 1, 13)  # relocate + foundation
    assert evaluate_target(
        st, "foundations_of_suit_ge", {"suit": "c", "min_count": 1}
    )
