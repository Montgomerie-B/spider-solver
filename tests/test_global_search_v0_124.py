"""v0.124 legal-state coverage and the isolated global-search experiment.

Synthetic boards, the saved g83 audit, and tiny unique limits. No 40-second
or 150-second search.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.global_search_experiment import (
    SCHEMA,
    classify_objective_coverage,
    search_strategy_guided,
    strategic_action_order,
    strategy_features,
)
from spider.human_strategy import SCHEMA_VERSION
from spider.human_strategy.anchored import AnchoredRefused, optimise_anchored
from spider.human_strategy.evaluation import admissible_remaining
from spider.human_strategy.foundation_direction import _progressive_excavation
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.search_budget import TacticalLimits
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, apply_action, opening_from_deal, step_cost
from spider.search_kernel import SearchLimits, run_search
from spider.state_identity import canonical_state_key
from spider.counterfactual.boundaries import parse_canonical

DEAL = ROOT / "deals" / "4925153.txt"
G83 = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"
AUTONOMOUS_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_172 = ROOT / "solutions" / "4925153_canonical.moves"


def _opening() -> SpiderState:
    return opening_from_deal(DEAL)


def _cycle_board() -> SpiderState:
    columns = [Column([], [Card("s", 13)]), Column([], [])]
    for _ in range(8):
        columns.append(Column([], [Card("h", 1)]))
    stock = [Card("d", (index % 13) + 1) for index in range(10)]
    return SpiderState(columns, stock)


def _ordered_board() -> SpiderState:
    columns = [
        Column([], [Card("s", 13)]),
        Column([], [Card("h", 12)]),
    ]
    for rank in range(1, 9):
        columns.append(Column([], [Card("c", rank)]))
    stock = [Card("d", (index % 13) + 1) for index in range(10)]
    return SpiderState(columns, stock)


def test_authoritative_legal_successors_are_ordered_not_dropped():
    state = _opening()
    legal = all_legal_actions(state)
    ordered = strategic_action_order(state, legal, seed=0)
    assert set(ordered) == set(legal)
    assert len(ordered) == len(legal)
    assert ("deal",) in ordered
    tiny = search_strategy_guided(
        state,
        time_limit_s=5.0,
        max_unique=400,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    assert tiny.heuristic_exclusions == 0
    assert tiny.generated >= len(legal)
    payload = tiny.to_dict()
    assert payload["legal_actions_dropped"] == 0
    json.dumps(payload)


def test_objective_exclusions_are_labelled():
    state = _opening()
    covered = classify_objective_coverage(state, resolve_profile("pilot"), g=0)
    assert covered["legal_count"] == len(all_legal_actions(state))
    assert covered["width"] == 3
    assert len(covered["within_width"]) <= covered["width"]
    assert covered["classes"]["safe_dominance"] == []
    assert covered["classes"]["admissible_incumbent_prune"] == []
    excluded = len(covered["not_scored"]) + len(covered["outside_width"])
    assert excluded > 0
    assert "campaign" in covered["note"]


def test_safe_and_heuristic_pruning_are_distinct():
    assert proof_prune(10, 5, 15) is True
    assert proof_prune(10, 4, 15) is False
    assert proof_prune(10, 4, None) is False
    opening = _opening()
    features = strategy_features(opening)
    assert isinstance(features, tuple)
    assert proof_prune(0, admissible_remaining(opening), 185) is False
    assert proof_prune(0, 10**6, 185) is True
    covered = classify_objective_coverage(opening, resolve_profile("pilot"), g=0)
    assert covered["classes"]["heuristic_rank_cutoff"] or covered["classes"]["not_generated_by_objective_system"]
    assert covered["classes"]["safe_dominance"] == []


def test_stock_deal_is_generated():
    state = _opening()
    legal = all_legal_actions(state)
    assert ("deal",) in legal
    ordered = strategic_action_order(state, legal, seed=1)
    assert ordered.count(("deal",)) == 1
    assert set(ordered) == set(legal)


def test_column_order_is_part_of_identity_while_stock_remains():
    left = _ordered_board()
    right = left.clone()
    right.columns[0], right.columns[1] = right.columns[1], right.columns[0]
    assert canonical_state_key(left) != canonical_state_key(right)
    assert pack_whole_game_identity(left) != pack_whole_game_identity(right)
    left.stock.clear()
    right.stock.clear()
    assert canonical_state_key(left) != canonical_state_key(right)
    assert pack_whole_game_identity(left) == pack_whole_game_identity(right)


def test_duplicate_cards_keep_distinct_positions():
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], [Card("s", 13)])
    columns[2] = Column([], [Card("s", 13)])
    columns[3] = Column([], [Card("h", 5)])
    state = SpiderState(columns, [Card("d", 1)] * 10)
    left = state.clone()
    right = state.clone()
    apply_action(left, (0, 1, 1))
    apply_action(right, (2, 1, 1))
    assert canonical_state_key(left) != canonical_state_key(right)
    assert pack_state(left) != pack_state(right)


def test_zero_cost_transfer():
    state = _cycle_board()
    assert step_cost(state, (0, 1, 1)) == 0
    moved = state.clone()
    assert apply_action(moved, (0, 1, 1)) == 0
    assert step_cost(moved, (1, 0, 1)) == 0
    assert apply_action(moved, (1, 0, 1)) == 0
    assert canonical_state_key(moved) == canonical_state_key(state)


def test_zero_cost_cycle_does_not_loop():
    result = search_strategy_guided(
        _cycle_board(),
        time_limit_s=2.0,
        max_unique=40,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    assert result.duplicate_skips > 0
    assert result.unique <= 40
    assert result.elapsed_s < 2.5
    assert result.solved is False


def test_cheapest_exact_state_ancestry_dominates():
    state = _cycle_board()
    store = pack_state(state).hex()
    result = run_search(
        [
            {"g": 9, "ordered_digest": store},
            {"g": 4, "ordered_digest": store},
        ],
        limits=SearchLimits(max_unique=8, time_limit_s=2.0, rss_abort_mb=1024),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=("cost",),
        lane_keys_fn=lambda board, g: {"cost": (int(g),)},
        actions_fn=all_legal_actions,
        is_terminal=lambda _board: False,
    )
    roots = [node for node in result.nodes if node.parent < 0]
    assert len(roots) == 1
    assert roots[0].g == 4
    assert all(node.g != 9 or node.parent >= 0 for node in result.nodes)


def test_incumbent_bound_uses_admissible_remainder():
    opening = _opening()
    with pytest.raises(ValueError, match="cold search refuses"):
        search_strategy_guided(
            opening,
            time_limit_s=1.0,
            max_unique=5,
            rss_abort_mb=512,
            mode="cold",
            incumbent_cost=185,
        )
    optimised = search_strategy_guided(
        opening,
        time_limit_s=2.0,
        max_unique=20,
        rss_abort_mb=1024,
        mode="optimise",
        incumbent_cost=1,
        cost_ceiling=None,
    )
    assert optimised.imported_incumbent is True
    assert optimised.ceiling_kind == "admissible_incumbent"
    assert optimised.cost_ceiling == 0
    assert optimised.solved is False
    assert optimised.lower_bound_prunes >= 1
    assert optimised.expanded == 0


def test_heuristic_score_is_not_a_proof():
    opening = _opening()
    features = strategy_features(opening)
    assert proof_prune(0, int(features[0]), None) is False
    result = search_strategy_guided(
        opening,
        time_limit_s=2.0,
        max_unique=15,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    payload = result.to_dict()
    assert "do not prove a state impossible" in payload["notes"]
    assert result.lower_bound_prunes == 0
    assert result.max_foundations >= 0


def test_eight_foundation_validation():
    opening = _opening()
    verified = verify_complete_solution(
        opening,
        parse_moves_file(AUTONOMOUS_185),
        expected_cost=185,
        source="imported",
        source_id="autonomous-185",
    )
    assert verified.solved is True
    assert verified.foundations == 8
    assert verified.cost == 185
    g83 = json.loads(G83.read_text(encoding="utf-8"))
    actions = [parse_canonical(item) for item in g83["actions"]]
    with pytest.raises(IncumbentRejected):
        verify_complete_solution(opening, actions, source="g83-reference")


def test_cold_mode_does_not_accept_a_reference_route():
    source = inspect.getsource(search_strategy_guided)
    for banned in (
        "4925153_autonomous_185",
        "4925153_canonical",
        "g83_4925153",
        "experiment_c_policy",
    ):
        assert banned not in source
    assert "incumbent_cost" in source
    opening = _opening()
    with pytest.raises(ValueError):
        search_strategy_guided(
            opening,
            time_limit_s=0.5,
            max_unique=4,
            rss_abort_mb=512,
            incumbent_cost=172,
        )


def test_fixed_seed_is_deterministic():
    opening = _opening()
    kwargs = dict(
        time_limit_s=5.0,
        max_unique=12,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    first = search_strategy_guided(opening, **kwargs).to_dict()
    second = search_strategy_guided(opening.clone(), **kwargs).to_dict()
    for key in ("elapsed_s", "cpu_s", "peak_rss_mb"):
        first.pop(key)
        second.pop(key)
    assert first == second
    assert first["seed"] == 0
    assert first["stop_reason"] == "unique limit"


def test_deadline_and_unique_limit():
    opening = _opening()
    timed = search_strategy_guided(
        opening,
        time_limit_s=0.05,
        max_unique=200000,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    assert timed.stop_reason == "time limit"
    assert timed.elapsed_s < 2.0
    capped = search_strategy_guided(
        opening.clone(),
        time_limit_s=10.0,
        max_unique=4,
        rss_abort_mb=1024,
        seed=0,
        cost_ceiling=None,
    )
    assert capped.stop_reason == "unique limit"
    assert capped.unique == 4


def test_g83_fixture_replays():
    document = json.loads(G83.read_text(encoding="utf-8"))
    actions = [parse_canonical(item) for item in document["actions"]]
    state = _opening()
    cost = replay_actions(state, actions)
    assert cost == 83
    assert document["corrected_g"] == 83
    assert len(state.foundations) == 2
    assert [item[0].suit for item in state.foundations] == ["s", "c"]
    assert state.is_solved() is False


def test_production_excavation_ladder_unchanged():
    limits = TacticalLimits()
    assert limits.ladder[-1] == (4, 8, 4500, 1.25)
    assert callable(_progressive_excavation)
    text = (ROOT / "src" / "spider" / "human_strategy" / "controller.py").read_text(encoding="utf-8")
    assert "global_search_experiment" not in text
    assert SCHEMA_VERSION == "spider-human-strategy-0.123"
    assert SCHEMA == "spider-global-search-0.124"


def test_incumbent_185_and_172_integrity():
    opening = _opening()
    autonomous = verify_complete_solution(
        opening,
        parse_moves_file(AUTONOMOUS_185),
        expected_cost=185,
        source="imported",
    )
    human = verify_complete_solution(
        opening,
        parse_moves_file(CANONICAL_172),
        expected_cost=172,
        source="imported",
    )
    assert autonomous.cost == 185 and autonomous.foundations == 8
    assert human.cost == 172 and human.foundations == 8
    assert autonomous.source == "imported"
    assert human.source == "imported"


def test_anchored_refuses_cold():
    with pytest.raises(AnchoredRefused):
        optimise_anchored(_opening(), [], mode="cold")


def test_experiment_is_isolated_from_production_controller():
    controller = (ROOT / "src" / "spider" / "human_strategy" / "controller.py").read_text(encoding="utf-8")
    package = (ROOT / "src" / "spider" / "human_strategy" / "__init__.py").read_text(encoding="utf-8")
    solver = (ROOT / "tools" / "human_strategy_solver.py").read_text(encoding="utf-8")
    assert "global_search_experiment" not in controller
    assert "global_search_experiment" not in package
    assert "global_search_experiment" not in solver
    assert "admit_ordinary_objective" not in controller
