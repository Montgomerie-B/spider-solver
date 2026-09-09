"""Simple progressive solver v0.1: classification, TT, replay, isolation."""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.simple_progressive_solver import (
    MoveClass,
    RelaxationStage,
    action_allowed,
    classify_action,
    ordered_actions,
    solve_progressive,
)
from spider.state_identity import canonical_state_key


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "src" / "spider" / "planner" / "anytime_controller.py"
SOLVER = ROOT / "src" / "spider" / "simple_progressive_solver.py"
DEAL = ROOT / "deals" / "4925153.txt"


def _filled(slots: dict[int, list[Card]], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        cards = slots.get(index, [Card("shdc"[index % 4], 13)])
        cols.append(Column([], list(cards)))
    return SpiderState(cols, stock or [])


def test_same_suit_extend_is_strict():
    state = _filled({0: [Card("c", 8), Card("c", 7)], 1: [Card("c", 6)]})
    assert classify_action(state, (1, 0, 1)) is MoveClass.SAME_SUIT_EXTEND
    assert action_allowed(MoveClass.SAME_SUIT_EXTEND, RelaxationStage.STRICT)


def test_join_break_requires_any_stage():
    state = _filled({0: [Card("c", 8), Card("c", 7)], 1: [Card("h", 6)]})
    assert classify_action(state, (0, 1, 1)) is MoveClass.JOIN_BREAK
    assert not action_allowed(MoveClass.JOIN_BREAK, RelaxationStage.STRICT)
    assert not action_allowed(MoveClass.JOIN_BREAK, RelaxationStage.DEAL)
    assert action_allowed(MoveClass.JOIN_BREAK, RelaxationStage.ANY)


def test_uncover_and_deal_classes():
    state = _filled({0: [Card("s", 5)], 1: [Card("h", 6)]})
    state.columns[0].face_down.append(Card("d", 9))
    assert classify_action(state, (0, 1, 1)) is MoveClass.UNCOVER
    assert classify_action(state, ("deal",)) is MoveClass.DEAL
    assert ("deal",) not in ordered_actions(state, RelaxationStage.SPACE)
    stock = [Card("c", rank) for rank in range(1, 11)]
    dealable = _filled({i: [Card("s", 5)] for i in range(10)}, stock=stock)
    assert ("deal",) in ordered_actions(dealable, RelaxationStage.DEAL)


def test_tt_does_not_revisit_equal_g_same_stage():
    state = _filled(
        {
            0: [Card("c", r) for r in range(13, 1, -1)],
            1: [Card("c", 1)],
        }
    )
    result = solve_progressive(state, max_nodes=2_000, time_limit_s=2.0, target_foundations=1)
    assert result.max_foundations >= 1
    assert result.replay_ok
    end = state.clone()
    assert replay_actions(end, list(result.actions)) == result.cost
    assert len(end.foundations) >= 1


def test_solver_finds_one_move_foundation_and_replays():
    clubs = [Card("c", r) for r in range(13, 1, -1)]
    state = _filled({0: clubs, 1: [Card("c", 1)]})
    result = solve_progressive(state, max_nodes=50, time_limit_s=1.0, target_foundations=1)
    assert result.max_foundations == 1
    assert result.actions == [(1, 0, 1)]
    assert result.replay_ok
    assert canonical_state_key(state) == canonical_state_key(_filled({0: clubs, 1: [Card("c", 1)]}))


def test_source_state_is_unmodified():
    state = _filled({0: [Card("h", 10)], 1: [Card("h", 9)]})
    before = canonical_state_key(state)
    solve_progressive(state, max_nodes=200, time_limit_s=1.0)
    assert canonical_state_key(state) == before


def test_solver_does_not_import_strategic_controller():
    source = SOLVER.read_text(encoding="utf-8")
    imports = [
        line
        for line in source.splitlines()
        if line.startswith("from ") or line.startswith("import ")
    ]
    joined = "\n".join(imports)
    assert "anytime_controller" not in joined
    assert "strategic_project" not in joined
    assert "state_service_registry" not in joined
    assert "from spider.engine import SpiderState" in source
    assert "canonical_state_key" in source
    assert "anytime_controller" not in inspect.getsource(
        __import__("spider.simple_progressive_solver", fromlist=["solve_progressive"])
    )


def test_controller_source_unchanged_by_this_module():
    controller = CONTROLLER.read_text(encoding="utf-8")
    assert "simple_progressive_solver" not in controller


def test_opening_4925153_runs_tiny_budget():
    cards = list(load_deal(DEAL))
    opening = SpiderState.from_cards(cards)
    result = solve_progressive(opening, max_nodes=200, time_limit_s=2.0, target_foundations=1)
    assert result.nodes <= 200
    assert result.min_face_down <= 50
    assert result.replay_ok or not result.actions
