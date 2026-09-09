"""Simple progressive solver v0.1: spec tests 1–12."""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.rules import MobilityWareRules, MW_RULES
from spider.simple_progressive_solver import (
    CoverageTT,
    Tier,
    action_allowed,
    classify_tier,
    deal_preparation,
    enumerate_actions,
    evaluate_deal_landings,
    format_moves_text,
    is_direct_inverse,
    ordered_actions,
    solve_progressive,
    unique_successor_actions,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
SOLVER = ROOT / "src" / "spider" / "simple_progressive_solver.py"
DEAL = ROOT / "deals" / "4925153.txt"

BLOCKED_IMPORTS = (
    "anytime_controller",
    "whole_deal_scheduler",
    "tactical_resource_allocator",
    "strategic_project",
    "state_service_registry",
    "foundation_campaign",
    "workspace_tactics",
    "resource_excavation_planner",
    "continuation_credit",
    "protected_conversion",
    "spider.planner",
)


def _filled(slots: dict[int, list[Card]], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index, [Card("shdc"[index % 4], 13)])
        cols.append(Column([], list(cards)))
    return SpiderState(cols, stock or [])


def _deal_prep_opening() -> SpiderState:
    """Deal-now buries; one mixed 6s→7h makes the 5s landing same-suit."""

    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("h", 7)]
    cols[1].face_up = [Card("s", 6)]
    for index in range(2, 10):
        cols[index].face_up = [Card("c", 13)]
    stock = [Card("s", 5)] + [Card("d", rank) for rank in range(2, 11)]
    return SpiderState(cols, stock)


def _almost_solved() -> SpiderState:
    foundations = []
    for copy in range(2):
        for suit in "shdc":
            if copy == 1 and suit == "c":
                continue
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("c", rank) for rank in range(13, 1, -1)]
    cols[1].face_up = [Card("c", 1)]
    return SpiderState(cols, [], foundations)


def test_1_deterministic_tier_classification():
    same = _filled({0: [Card("c", 8), Card("c", 7)], 1: [Card("c", 6)]})
    assert classify_tier(same, (1, 0, 1)) is Tier.A

    uncover = _filled({0: [Card("s", 5)], 1: [Card("h", 6)]})
    uncover.columns[0].face_down.append(Card("d", 9))
    assert classify_tier(uncover, (0, 1, 1)) is Tier.A

    mixed = _filled({0: [Card("h", 8)], 1: [Card("d", 10), Card("c", 7)]})
    assert classify_tier(mixed, (1, 0, 1)) is Tier.B

    king_empty = _filled({0: [Card("s", 13)], 1: []})
    assert classify_tier(king_empty, (0, 1, 1)) is Tier.B

    join = _filled({0: [Card("c", 8), Card("c", 7)], 1: [Card("h", 8)]})
    assert classify_tier(join, (0, 1, 1)) is Tier.C

    park = _filled({0: [Card("s", 5), Card("h", 9)], 1: []})
    assert classify_tier(park, (0, 1, 1)) is Tier.C

    clubs = [Card("c", rank) for rank in range(13, 1, -1)]
    finish = _filled({0: clubs, 1: [Card("c", 1)]})
    assert classify_tier(finish, (1, 0, 1)) is Tier.A


def test_2_all_legal_moves_available_at_max_relaxation():
    state = _filled(
        {
            0: [Card("c", 8), Card("c", 7)],
            1: [Card("h", 8)],
            2: [Card("s", 13)],
        },
        stock=[Card("d", rank) for rank in range(1, 11)],
    )
    legal = set(enumerate_actions(state))
    permitted = set(ordered_actions(state, 3, prep_ply=0))
    assert legal == permitted
    join = (0, 1, 1)
    assert join in legal
    assert join not in ordered_actions(state, 1, prep_ply=0)
    assert join in ordered_actions(state, 2, prep_ply=0)


def test_3_exact_child_dedup():
    state = _filled({0: [Card("h", 8)], 1: [Card("c", 7)]})
    unique = unique_successor_actions(state, [(1, 0, 1), (1, 0, 1)])
    assert unique == [(1, 0, 1)]
    result = solve_progressive(state, max_nodes=80, time_limit_s=1.0, target_foundations=8)
    assert result.stats.duplicate_children >= 0
    assert canonical_state_key(state) == canonical_state_key(
        _filled({0: [Card("h", 8)], 1: [Card("c", 7)]})
    )


def test_4_active_path_cycle_prevention():
    state = _filled({0: [Card("h", 7), Card("s", 6)], 1: [Card("d", 7)]})
    result = solve_progressive(state, max_nodes=400, time_limit_s=2.0, target_foundations=8)
    assert result.stats.path_cycles + result.stats.inverses >= 1
    assert result.nodes <= 400
    assert result.stop_reason in {"node limit", "time limit", "pass envelope"}


def test_5_tt_coverage_by_relaxation_level():
    tt = CoverageTT()
    key = b"exact-state"
    assert not tt.skip(key, 0)
    tt.mark_start(key, 0)
    tt.mark_done(key, 0)
    assert tt.skip(key, 0)
    assert not tt.skip(key, 1)
    tt.mark_start(key, 1)
    tt.mark_done(key, 1)
    assert tt.skip(key, 1)
    assert tt.skip(key, 0)


def test_6_direct_undo_suppression():
    last = (0, 1, 1, False, False)
    assert is_direct_inverse(last, (1, 0, 1))
    assert not is_direct_inverse(last, (1, 0, 2))
    assert not is_direct_inverse((0, 1, 1, True, False), (1, 0, 1))
    assert not is_direct_inverse(("deal",), (1, 0, 1))
    state = _filled({0: [Card("h", 7), Card("s", 6)], 1: [Card("d", 7)]})
    result = solve_progressive(state, max_nodes=200, time_limit_s=1.0, prep_ply=0)
    assert result.stats.inverses >= 1


def test_7_deal_legality():
    stock = [Card("c", rank) for rank in range(1, 11)]
    filled = _filled({index: [Card("s", 5)] for index in range(10)}, stock=stock)
    assert ("deal",) in enumerate_actions(filled, rules=MW_RULES)
    empty = filled.clone()
    empty.columns[3].face_up.clear()
    assert empty.columns[3].is_empty()
    assert ("deal",) in enumerate_actions(empty, rules=MW_RULES)
    restricted = MobilityWareRules(can_deal_into_empty=False)
    assert ("deal",) not in enumerate_actions(empty, rules=restricted)
    assert ("deal",) in enumerate_actions(filled, rules=restricted)


def test_8_known_stock_landing_evaluation():
    state = _deal_prep_opening()
    landing = evaluate_deal_landings(state)
    assert landing is not None
    assert landing.legal
    assert landing.same_suit == 0
    assert state.stock[-10:][0] == Card("s", 5)
    child = state.clone()
    child.move(1, 0, 1)
    after = evaluate_deal_landings(child)
    assert after is not None
    assert after.same_suit >= 1
    assert after.score > landing.score


def test_9_one_move_deal_preparation_preference():
    state = _deal_prep_opening()
    prep, landing = deal_preparation(state, prep_ply=1)
    assert landing is not None
    assert prep == (1, 0, 1)
    pass1 = ordered_actions(state, 1, prep_ply=1)
    assert pass1[0] == (1, 0, 1)
    assert ("deal",) not in pass1
    ordered = ordered_actions(state, 3, prep_ply=1)
    assert ordered[0] == (1, 0, 1)
    assert ("deal",) in ordered
    assert ordered.index((1, 0, 1)) < ordered.index(("deal",))


def test_10_prepared_deal_replay():
    state = _deal_prep_opening()
    actions = [(1, 0, 1), ("deal",)]
    end = state.clone()
    paid = replay_actions(end, list(actions))
    assert paid >= 1
    assert end.columns[0].face_up[-1] == Card("s", 5)
    assert end.columns[0].face_up[-2] == Card("s", 6)
    assert canonical_state_key(state) == canonical_state_key(_deal_prep_opening())
    text = format_moves_text(actions)
    assert "move 2 1 1" in text
    assert "deal" in text.splitlines()


def test_11_solution_replay():
    state = _almost_solved()
    result = solve_progressive(state, max_nodes=50, time_limit_s=1.0, target_foundations=8)
    assert result.solved
    assert result.replay_ok
    assert result.actions == [(1, 0, 1)]
    end = state.clone()
    assert replay_actions(end, list(result.actions)) == result.cost
    assert end.is_solved()
    assert len(end.foundations) == 8

    one = _filled(
        {0: [Card("c", rank) for rank in range(13, 1, -1)], 1: [Card("c", 1)]}
    )
    first = solve_progressive(one, max_nodes=50, time_limit_s=1.0, target_foundations=1)
    assert first.max_foundations == 1
    assert first.replay_ok
    assert first.actions == [(1, 0, 1)]


def test_12_no_strategic_controller_dependency():
    source = SOLVER.read_text(encoding="utf-8")
    imports = [
        line
        for line in source.splitlines()
        if line.startswith("from ") or line.startswith("import ")
    ]
    joined = "\n".join(imports)
    for name in BLOCKED_IMPORTS:
        assert name not in joined
    assert "from spider.engine import SpiderState" in source
    assert "anytime_controller" not in inspect.getsource(
        __import__("spider.simple_progressive_solver", fromlist=["solve_progressive"])
    )
    controller = CONTROLLER.read_text(encoding="utf-8")
    assert "simple_progressive_solver" not in controller


def test_source_state_unmodified_and_opening_smoke():
    state = _filled({0: [Card("h", 10)], 1: [Card("h", 9)]})
    before = canonical_state_key(state)
    solve_progressive(state, max_nodes=200, time_limit_s=1.0)
    assert canonical_state_key(state) == before

    cards = list(load_deal(DEAL))
    opening = SpiderState.from_cards(cards)
    result = solve_progressive(opening, max_nodes=200, time_limit_s=2.0, target_foundations=8)
    assert result.nodes <= 200
    assert result.identified_face_down <= 50
    assert result.replay_ok or not result.actions
    assert action_allowed(Tier.A, 0)
    assert not action_allowed(Tier.B, 0)
    assert action_allowed(Tier.D, 3)
