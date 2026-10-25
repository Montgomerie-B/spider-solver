"""v0.118 incumbent-anchored segment replacement.

The 185 and 172 files are read and replayed. They are not rewritten.
The improvement fixtures are constructed boards, not deal 4925153.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.human_strategy.anchored import (
    AnchoredRefused,
    build_checkpoints,
    optimise_anchored,
    search_segment,
    segment_lower_bound,
    select_windows,
    states_rejoin,
)
from spider.human_strategy.controller import solve
from spider.human_strategy.incumbent import verify_complete_solution
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.strategic_frontier import StrategicFrontier
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, permute_tableau_columns
from spider.research_actions import apply_action, opening_from_deal, step_cost

DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
REGISTRY = ROOT / "solutions" / "4925153_incumbent.json"
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


def _micro():
    return _state({0: HEARTS, 1: "kh"}, foundations=7)


def _profile(**kwargs):
    base = dict(
        time_limit_s=2,
        max_steps=2,
        tactical_nodes=40,
        tactical_time_s=0.2,
        tactical_max_cost=1,
        consult_portfolio=False,
        strategic_width=1,
        max_width=1,
        frontier_limit=1,
        rss_abort_mb=8192,
    )
    base.update(kwargs)
    return resolve_profile("smoke").with_overrides(**base)


def _waste_twice():
    """Two exact returns to the opening, then the completing move."""

    return ((0, 2, 1), (2, 0, 1), (0, 3, 1), (3, 0, 1), (0, 1, 12))


def _detour():
    """A longer route to the same solved board with no repeated checkpoint."""

    return ((0, 3, 1), (1, 2, 1), (3, 0, 1), (0, 2, 12))


def _cli():
    path = ROOT / "tools" / "human_strategy_solver.py"
    spec = importlib.util.spec_from_file_location("human_strategy_solver_v0118", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def test_checkpoints_replay_the_185_route_with_exact_costs():
    opening = opening_from_deal(DEAL)
    actions = tuple(parse_moves_file(MOVES_185))
    before_185 = MOVES_185.stat().st_mtime_ns
    before_172 = MOVES_172.stat().st_mtime_ns
    before_registry = REGISTRY.stat().st_mtime_ns
    route = verify_complete_solution(opening, actions, expected_cost=185, source="imported")
    checkpoints = build_checkpoints(opening, route.actions)
    assert len(checkpoints) == len(route.actions) + 1
    assert checkpoints[0].g == 0
    assert checkpoints[-1].g == 185
    assert checkpoints[-1].foundations == 8
    assert checkpoints[-1].stock_cards == 0
    trial = opening.clone()
    spent = 0
    assert states_rejoin(trial, checkpoints[0].state)
    for index, action in enumerate(route.actions, start=1):
        spent += apply_action(trial, action)
        assert checkpoints[index].g == spent
        assert states_rejoin(trial, checkpoints[index].state)
        assert checkpoints[index].stock_cards == len(trial.stock)
        assert checkpoints[index].foundations == len(trial.foundations)
    assert spent == 185
    assert MOVES_185.stat().st_mtime_ns == before_185
    assert MOVES_172.stat().st_mtime_ns == before_172
    assert REGISTRY.stat().st_mtime_ns == before_registry


def test_replacement_must_start_at_the_source_and_hit_the_target():
    opening = _micro()
    actions = _detour()
    checkpoints = build_checkpoints(opening, actions)
    window = select_windows(checkpoints, actions, max_span=6, max_windows=8)[0]
    source = checkpoints[window.start].state
    target = checkpoints[window.end].state
    found = search_segment(source, target, window.cost, time_limit_s=2, max_unique=500)
    assert found.status == "FOUND"
    assert found.cost is not None and found.cost < window.cost
    trial = source.clone()
    assert replay_actions(trial, list(found.actions)) == found.cost
    assert states_rejoin(trial, target)
    other = opening.clone()
    apply_action(other, (1, 2, 1))
    missed = search_segment(other, target, window.cost, time_limit_s=1, max_unique=200)
    if missed.status == "FOUND":
        check = other.clone()
        replay_actions(check, list(missed.actions))
        assert states_rejoin(check, target)
    drifted = source.clone()
    apply_action(drifted, (0, 4, 1))
    assert not states_rejoin(drifted, source)


def test_column_permutation_stock_and_foundations_block_rejoin():
    opening = _micro()
    moved = opening.clone()
    assert step_cost(moved, (1, 2, 1)) == 0
    apply_action(moved, (1, 2, 1))
    swap = list(range(10))
    swap[1], swap[2] = swap[2], swap[1]
    permuted = permute_tableau_columns(moved, swap)
    assert not states_rejoin(moved, permuted)
    assert pack_state(moved) != pack_state(permuted)
    assert pack_post_stock_symmetry_state(moved) == pack_post_stock_symmetry_state(permuted)
    assert segment_lower_bound(opening, moved) == 0
    suffix = ((0, 2, 12),)
    real = moved.clone()
    replay_actions(real, list(suffix))
    assert real.is_solved()
    try:
        wrong = permuted.clone()
        replay_actions(wrong, list(suffix))
        assert not states_rejoin(wrong, real)
    except ValueError:
        pass
    stocked = _state({0: HEARTS, 1: "kh"}, stock="as ks qs js 10s 9s 8s 7s 6s 5s", foundations=7)
    assert not states_rejoin(opening, stocked)
    # One deal would empty this stock. That deal count is admissible and does
    # not claim the tableau matches the opening.
    assert segment_lower_bound(stocked, opening) == 1
    different = _state(
        {0: HEARTS, 1: "kh"},
        stock="2c 3c 4c 5c 6c 7c 8c 9c 10c jc",
        foundations=7,
    )
    assert segment_lower_bound(stocked, different) is None
    fewer = _state({0: HEARTS, 1: "kh"}, foundations=6)
    assert not states_rejoin(opening, fewer)
    assert segment_lower_bound(opening, fewer) is None
    assert not states_rejoin(moved, permuted)


def test_cheaper_rejoin_updates_and_equal_or_worse_do_not():
    opening = _micro()
    actions = _detour()
    route = verify_complete_solution(opening, actions, source="imported", source_id="detour")
    assert route.cost == 3
    improved = optimise_anchored(
        opening,
        actions,
        source="imported",
        source_id="detour",
        time_limit_s=5,
        window_time_s=2,
        max_windows=8,
        max_unique=800,
    )
    assert improved.provenance["improved"] is True
    assert improved.cumulative_g == 1
    assert improved.solved is True
    assert improved.replay["ok"] is True
    assert improved.provenance["incumbent_source"] == "discovered"
    assert improved.provenance["previous_verified_cost"] == 3
    assert improved.provenance["cold_injection"] is False
    assert improved.actions != actions
    again = verify_complete_solution(opening, improved.actions, expected_cost=1)
    assert again.solved is True

    same = search_segment(opening, build_checkpoints(opening, ((0, 1, 12),))[-1].state, 1, time_limit_s=1)
    assert same.status in {"EXHAUSTED", "NOT_CHEAPER", "INCONCLUSIVE"}
    assert same.cost is None or same.cost >= 1

    held = optimise_anchored(
        opening,
        ((0, 1, 12),),
        source="imported",
        source_id="short",
        time_limit_s=3,
        window_time_s=1,
        max_windows=4,
        max_unique=400,
    )
    assert held.provenance["improved"] is False
    assert held.cumulative_g == 1
    assert held.provenance["best_verified_cost"] == 1
    assert held.actions == ((0, 1, 12),)


def test_zero_cost_transfer_can_replace_a_paid_detour():
    opening = _micro()
    actions = _detour()
    checkpoints = build_checkpoints(opening, actions)
    assert step_cost(opening, (1, 2, 1)) == 0
    target = checkpoints[3].state
    assert checkpoints[3].g == 2
    found = search_segment(opening, target, 2, time_limit_s=2, max_unique=500)
    assert found.status == "FOUND"
    assert found.cost == 0
    assert found.actions == ((1, 2, 1),)
    trial = opening.clone()
    assert replay_actions(trial, list(found.actions)) == 0
    assert states_rejoin(trial, target)


def test_full_replay_is_required_and_an_invalid_candidate_is_kept_out():
    opening = _micro()
    actions = _detour()
    report = optimise_anchored(
        opening,
        actions,
        time_limit_s=4,
        window_time_s=2,
        max_windows=6,
        max_unique=600,
    )
    assert report.replay["foundations"] == 8
    assert report.solved is True
    illegal = list(report.actions) + [(0, 0, 1)]
    try:
        verify_complete_solution(opening, illegal)
    except Exception as exc:
        assert "illegal" in str(exc).lower() or "partial" in str(exc).lower()
    untouched = optimise_anchored(
        opening,
        actions,
        time_limit_s=0,
        source_id="timeout",
    )
    assert untouched.provenance["improved"] is False
    assert untouched.provenance["best_verified_cost"] == 3
    assert untouched.provenance["search_status"] == "TIME_LIMIT"
    assert untouched.actions == actions
    assert untouched.checkpoints


def test_the_incumbent_can_improve_twice_and_a_window_respects_its_ceiling():
    opening = _micro()
    actions = _waste_twice()
    route = verify_complete_solution(opening, actions, expected_cost=5, source="imported")
    assert route.cost == 5
    report = optimise_anchored(
        opening,
        actions,
        time_limit_s=5,
        window_time_s=1,
        max_windows=4,
        max_improvements=4,
        max_unique=400,
    )
    assert report.provenance["improved"] is True
    assert report.cumulative_g == 1
    assert len(report.improvements) >= 2
    assert report.improvements[0]["before"] == 5
    assert report.improvements[0]["after"] == 3
    costs = [item["before"] for item in report.improvements] + [report.cumulative_g]
    assert costs[0] > costs[-1]
    assert all(costs[index] > costs[index + 1] for index in range(len(costs) - 1))
    tight = search_segment(opening, build_checkpoints(opening, actions)[-1].state, 1, time_limit_s=1, max_unique=300)
    assert tight.cost is None or tight.cost < 1
    assert tight.status != "FOUND" or tight.cost < 1
    missed = search_segment(opening, build_checkpoints(opening, actions)[1].state, 1, time_limit_s=0, max_unique=10)
    assert missed.status == "INCONCLUSIVE"
    assert missed.proof is False


def test_cold_mode_does_not_anchor_and_both_modes_keep_provenance():
    opening = _micro()
    try:
        optimise_anchored(opening, ((0, 1, 12),), mode="cold")
        raised = False
    except AnchoredRefused:
        raised = True
    assert raised
    cold = solve(opening, _profile(max_steps=2), mode="cold")
    assert cold.provenance["anchored_used"] is False
    assert cold.provenance["approach"] == "global"
    assert cold.provenance["cold_injection"] is False
    assert cold.status == "SOLVED_VALID"
    anchored = optimise_anchored(
        opening,
        _detour(),
        mode="anchored",
        source="imported",
        source_id="fixture",
        time_limit_s=4,
        max_windows=6,
        max_unique=500,
    )
    assert anchored.provenance["approach"] == "anchored"
    assert anchored.provenance["global_search"] is False
    assert anchored.provenance["explicit_anchor"] is True
    assert anchored.provenance["anchored_used"] is True
    assert anchored.provenance["symmetry_quotient_used"] is False
    assert anchored.provenance["production_registry_written"] is False
    assert anchored.cumulative_g == 1


def test_exact_state_dominance_inside_a_segment_and_frontier_exclusion_kinds():
    opening = _micro()
    moved = opening.clone()
    apply_action(moved, (1, 3, 1))
    found = search_segment(
        opening,
        moved,
        1,
        time_limit_s=2,
        max_unique=400,
        exhaustive=True,
    )
    assert found.status == "FOUND"
    assert found.cost == 0
    assert found.duplicate_skips >= 1
    frontier = StrategicFrontier(limit=2, proposals=1)
    for count, label in enumerate(("a", "b", "c", "d")):
        state = _state({0: "kh"}, foundations=count)
        frontier.consider(
            state=state,
            g=0,
            actions=(),
            lock={},
            force_id=f"obj-{label}",
            reason=f"proposal {label}",
            label=label,
            payload=None,
        )
    assert frontier.dropped_full >= 1
    kinds = {item["kind"] for item in frontier.exclusion_log}
    assert "heuristic_admission" in kinds
    assert all(item["proof"] is False for item in frontier.exclusion_log)
    assert all(item["successor_state"] is None for item in frontier.exclusion_log)
    expensive = _state({0: "kh"}, foundations=0)
    frontier.consider(
        state=expensive,
        g=3,
        actions=(),
        lock={},
        force_id="later",
        reason="dearer ancestry",
        label="extra",
        payload=None,
    )
    assert any(item["kind"] == "transposition_dominance" and item["proof"] is True for item in frontier.exclusion_log)


def test_cli_anchored_timeout_keeps_185_and_cold_still_rejects_it(tmp_path, capsys):
    main = _cli()
    before = REGISTRY.stat().st_mtime_ns
    moves_before = MOVES_185.stat().st_mtime_ns
    assert main(["--deal", str(DEAL), "--mode", "cold", "--incumbent", str(MOVES_185)]) == 2
    assert main(["--deal", str(DEAL), "--mode", "anchored"]) == 2
    out = tmp_path / "anchored.json"
    code = main(
        [
            "--deal",
            str(DEAL),
            "--mode",
            "anchored",
            "--incumbent",
            str(MOVES_185),
            "--time-limit",
            "0",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    captured = capsys.readouterr().out
    assert "BEST_VERIFIED=185" in captured
    assert "IMPROVED=false" in captured
    assert "SEARCH_STATUS=TIME_LIMIT" in captured
    assert "INCUMBENT_SOURCE=imported" in captured
    assert MOVES_185.stat().st_mtime_ns == moves_before
    assert REGISTRY.stat().st_mtime_ns == before
    text = out.read_text(encoding="utf-8")
    assert "anchored" in text
    assert "symmetry_quotient_used" in text
