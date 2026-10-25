"""v0.119 multi-target checkpoint shortcuts and probe reuse.

The 185 and 172 files are read and replayed. They are not rewritten.
Improvement fixtures are constructed boards, not deal 4925153.
The solver does not contain the shortcut these tests measure.
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
    _covered_known,
    build_checkpoints,
    optimise_anchored,
    search_segment,
    search_targets,
    segment_lower_bound,
    select_adaptive_regions,
    states_rejoin,
)
from spider.human_strategy.controller import solve
from spider.human_strategy.foundation_direction import (
    _cached_excavation,
    excavation_probe_category,
)
from spider.human_strategy.incumbent import IncumbentRejected, verify_complete_solution
from spider.human_strategy.profiles import resolve_profile
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state, pack_state, permute_tableau_columns
from spider.planner.backward_strategy import (
    _cheap_workspace_cost,
    workspace_probe_cache,
    workspace_probe_seconds,
)
from spider.planner.objective_realizer import RealizationStatus
from spider.research_actions import all_legal_actions, apply_action, opening_from_deal, step_cost

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


def _long_route():
    """Ace tours the empties, the king tours after it, then the suit is removed.

    The paid return sits at span 11. Fixed windows stop at span 8, and the
    single foundation gap is span 12, past the between-foundations cap of 10.
    """

    return (
        (0, 3, 1),
        (3, 4, 1),
        (4, 5, 1),
        (5, 6, 1),
        (6, 7, 1),
        (7, 8, 1),
        (8, 9, 1),
        (1, 2, 1),
        (2, 3, 1),
        (3, 4, 1),
        (9, 0, 1),
        (0, 4, 12),
    )


def _tight():
    """No empty column. The only useful builds are the heart run and two twos."""

    columns = {
        0: ("", "4h 3h 2h ah"),
        1: ("", "3c"),
        2: ("", "2d"),
        3: ("", "2s"),
    }
    for index in range(4, 10):
        columns[index] = ("ac", "kh")
    return _state(columns)


def _park_targets():
    source = _tight()
    early = source.clone()
    apply_action(early, (0, 2, 1))
    later = source.clone()
    apply_action(later, (0, 1, 2))
    return source, early, later


def _zero_buried():
    buried = Card("c", 8)
    cols = [
        Column([buried], [Card("c", 6), Card("h", 1)]),
        Column([], []),
        Column([], [Card("d", 13)]),
    ]
    while len(cols) < 10:
        cols.append(Column([Card("d", 13)], [Card("s", 13)]))
    return SpiderState(cols, []), buried


def _blocked():
    return SpiderState(
        [Column([Card("s", 1)], [Card("d", 13)]) for _ in range(10)],
        [],
    )


class _Probe:
    def __init__(self, status):
        self.status = status
        self.corrected_mw_cost = None
        self.nodes_expanded = 1


def _cli():
    path = ROOT / "tools" / "human_strategy_solver.py"
    spec = importlib.util.spec_from_file_location("human_strategy_solver_v0119", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def test_checkpoint_identity_and_several_later_targets_stay_exact():
    opening = _micro()
    actions = _long_route()
    route = verify_complete_solution(opening, actions, source="imported", source_id="long")
    checkpoints = build_checkpoints(opening, route.actions)
    assert len(checkpoints) == len(actions) + 1
    assert checkpoints[0].g == 0
    assert checkpoints[-1].g == route.cost == 3
    assert checkpoints[-1].foundations == 8
    assert checkpoints[-1].stock_cards == 0
    trial = opening.clone()
    assert states_rejoin(trial, checkpoints[0].state)
    spent = 0
    for index, action in enumerate(route.actions, start=1):
        spent += apply_action(trial, action)
        assert checkpoints[index].g == spent
        assert states_rejoin(trial, checkpoints[index].state)
        assert checkpoints[index].stock_cards == len(trial.stock)
        assert checkpoints[index].foundations == len(trial.foundations)
        assert pack_state(trial) == pack_state(checkpoints[index].state)
    regions = select_adaptive_regions(checkpoints, route.actions, horizon=16, max_regions=4)
    assert regions
    assert any(len(region.targets) > 1 for region in regions)
    spans = [(region.start, region.targets[-1]) for region in regions]
    for index, left in enumerate(spans):
        for right in spans[index + 1 :]:
            assert left[1] <= right[0] or right[1] <= left[0]


def test_multi_target_improves_a_later_checkpoint_fixed_windows_miss():
    opening = _micro()
    actions = _long_route()
    checkpoints = build_checkpoints(opening, actions)
    first = search_segment(
        opening,
        checkpoints[1].state,
        checkpoints[1].g,
        time_limit_s=2,
        max_unique=800,
    )
    assert first.status == "EXHAUSTED"
    assert first.proof is True
    assert first.cost is None
    found = search_targets(
        opening,
        [(item.state, item.g, item.index) for item in checkpoints[1:]],
        time_limit_s=3,
        max_unique=1500,
    )
    assert found.status == "FOUND"
    assert found.target_index is not None and found.target_index > 1
    assert found.cost is not None and found.cost < checkpoints[found.target_index].g
    trial = opening.clone()
    assert replay_actions(trial, list(found.actions)) == found.cost
    assert states_rejoin(trial, checkpoints[found.target_index].state)
    adaptive = optimise_anchored(
        opening,
        actions,
        adaptive=True,
        horizon=16,
        max_regions=4,
        time_limit_s=8,
        window_time_s=2,
        max_unique=1500,
        source="imported",
        source_id="long-adaptive",
    )
    assert adaptive.provenance["improved"] is True
    assert adaptive.provenance["target_mode"] == "multi-checkpoint"
    assert adaptive.cumulative_g == 1
    assert adaptive.cumulative_g < 3
    assert adaptive.actions != actions
    assert adaptive.replay["ok"] is True
    assert adaptive.replay["foundations"] == 8
    assert adaptive.solved is True
    assert adaptive.provenance["incumbent_source"] == "discovered"
    again = verify_complete_solution(opening, adaptive.actions, expected_cost=1)
    assert again.foundations == 8
    fixed = optimise_anchored(
        opening,
        actions,
        adaptive=False,
        max_span=8,
        max_windows=8,
        time_limit_s=8,
        window_time_s=1,
        max_unique=800,
        source="imported",
        source_id="long-fixed",
    )
    assert fixed.provenance["improved"] is False
    assert fixed.provenance["target_mode"] == "fixed-endpoint"
    assert fixed.cumulative_g == 3
    assert fixed.actions == actions


def test_a_move_too_expensive_for_the_early_target_still_improves_a_later_one():
    source, early, later = _park_targets()
    assert step_cost(source, (0, 2, 1)) == 1
    assert step_cost(source, (0, 1, 2)) == 1
    assert not states_rejoin(early, later)
    only_early = search_targets(source, [(early, 1, 1)], time_limit_s=2, max_unique=200)
    assert only_early.status == "EXHAUSTED"
    assert only_early.proof is True
    assert only_early.cost is None
    assert only_early.ceiling == 1
    both = search_targets(
        source,
        [(early, 1, 1), (later, 6, 4)],
        time_limit_s=2,
        max_unique=400,
    )
    assert both.status == "FOUND"
    assert both.ceiling == 6
    assert both.target_index == 4
    assert both.cost == 1
    assert both.cost < 6
    assert both.cost >= 1
    trial = source.clone()
    assert replay_actions(trial, list(both.actions)) == 1
    assert states_rejoin(trial, later)
    assert not states_rejoin(trial, early)


def test_column_stock_and_foundation_differences_cannot_rejoin():
    opening = _micro()
    actions = _long_route()
    checkpoints = build_checkpoints(opening, actions)
    arrived = checkpoints[10].state
    swap = list(range(10))
    swap[1], swap[4] = swap[4], swap[1]
    permuted = permute_tableau_columns(arrived, swap)
    assert not states_rejoin(arrived, permuted)
    assert pack_state(arrived) != pack_state(permuted)
    assert pack_post_stock_symmetry_state(arrived) == pack_post_stock_symmetry_state(permuted)
    missed = search_targets(opening, [(permuted, 5, 10)], time_limit_s=2, max_unique=400)
    if missed.status == "FOUND":
        trial = opening.clone()
        replay_actions(trial, list(missed.actions))
        assert states_rejoin(trial, permuted)
        assert not states_rejoin(trial, arrived)
    suffix = actions[10:]
    real = arrived.clone()
    replay_actions(real, list(suffix))
    assert real.is_solved() and len(real.foundations) == 8
    try:
        wrong = permuted.clone()
        replay_actions(wrong, list(suffix))
        assert not states_rejoin(wrong, real)
    except ValueError:
        pass
    stocked = _state(
        {0: HEARTS, 1: "kh"},
        stock="as ks qs js 10s 9s 8s 7s 6s 5s",
        foundations=7,
    )
    assert not states_rejoin(opening, stocked)
    assert segment_lower_bound(opening, stocked) is None
    blocked = search_targets(opening, [(stocked, 4, 2)], time_limit_s=1, max_unique=50)
    assert blocked.status == "IMPOSSIBLE"
    assert blocked.proof is True
    assert blocked.cost is None
    different = _state(
        {0: HEARTS, 1: "kh"},
        stock="2c 3c 4c 5c 6c 7c 8c 9c 10c jc",
        foundations=7,
    )
    assert segment_lower_bound(stocked, different) is None
    fewer = _state({0: HEARTS, 1: "kh"}, foundations=6)
    assert not states_rejoin(opening, fewer)
    assert segment_lower_bound(opening, fewer) is None
    foundations = search_targets(opening, [(fewer, 3, 1)], time_limit_s=1, max_unique=50)
    assert foundations.status == "IMPOSSIBLE"
    assert foundations.cost is None


def test_zero_cost_moves_are_kept_and_cycles_stay_bounded():
    opening = _micro()
    assert step_cost(opening, (1, 2, 1)) == 0
    assert step_cost(opening, (0, 1, 12)) == 1
    parked = opening.clone()
    assert apply_action(parked, (1, 4, 1)) == 0
    found = search_targets(opening, [(parked, 2, 3)], time_limit_s=2, max_unique=400)
    assert found.status == "FOUND"
    assert found.cost == 0
    trial = opening.clone()
    assert replay_actions(trial, list(found.actions)) == 0
    assert states_rejoin(trial, parked)
    solved = opening.clone()
    apply_action(solved, (0, 1, 12))
    bounded = search_segment(opening, solved, 1, time_limit_s=2, max_unique=500)
    assert bounded.status == "EXHAUSTED"
    assert bounded.proof is True
    assert bounded.cost is None
    assert bounded.duplicate_skips > bounded.expanded
    assert bounded.unique < 500


def test_strict_local_improvement_and_full_replay_gate_the_incumbent():
    source, _early, later = _park_targets()
    equal = search_targets(source, [(later, 1, 4)], time_limit_s=2, max_unique=200)
    assert equal.status in {"EXHAUSTED", "NOT_CHEAPER"}
    assert equal.proof is True
    assert equal.cost is None
    opening = _micro()
    actions = _long_route()
    kept = optimise_anchored(
        opening,
        actions,
        adaptive=True,
        horizon=16,
        max_regions=4,
        time_limit_s=0,
        source="imported",
        source_id="timeout",
    )
    assert kept.provenance["improved"] is False
    assert kept.provenance["search_status"] == "TIME_LIMIT"
    assert kept.cumulative_g == 3
    assert kept.actions == actions
    assert kept.provenance["incumbent_source"] == "imported"
    assert kept.improvements == []
    try:
        verify_complete_solution(opening, actions[:4])
        raised = False
    except IncumbentRejected as exc:
        raised = True
        assert "partial" in str(exc).lower()
    assert raised
    illegal = list(actions) + [(0, 0, 1)]
    try:
        verify_complete_solution(opening, illegal)
        rejected = False
    except IncumbentRejected:
        rejected = True
    assert rejected


def test_successive_improvements_refresh_checkpoints_and_a_cap_stays_inconclusive():
    opening = _micro()
    waste = ((0, 2, 1), (2, 0, 1), (0, 3, 1), (3, 0, 1), (0, 1, 12))
    report = optimise_anchored(
        opening,
        waste,
        adaptive=True,
        horizon=12,
        max_regions=6,
        time_limit_s=6,
        window_time_s=1,
        max_unique=400,
        max_improvements=4,
        source="imported",
        source_id="waste",
    )
    assert report.provenance["improved"] is True
    assert report.cumulative_g == 1
    assert len(report.improvements) >= 2
    assert report.improvements[0]["before"] == 5
    assert report.improvements[0]["adaptive"] is True
    costs = [item["before"] for item in report.improvements] + [report.cumulative_g]
    assert all(costs[index] > costs[index + 1] for index in range(len(costs) - 1))
    assert len(report.checkpoints) < len(waste) + 1
    assert report.replay["foundations"] == 8
    assert report.provenance["segment_proof_is_not_global_optimality"] is True
    source, _early, later = _park_targets()
    capped = search_targets(source, [(later, 6, 4)], time_limit_s=2, max_unique=1)
    assert capped.status == "INCONCLUSIVE"
    assert capped.proof is False
    assert capped.cost is None
    memo = {"hits": 0, "misses": 0, "results": {}}
    stopped = search_targets(source, [(later, 6, 4)], time_limit_s=0, max_unique=10, memo=memo)
    assert stopped.status == "INCONCLUSIVE"
    assert memo["results"] == {}
    found = search_targets(source, [(later, 6, 4)], time_limit_s=2, max_unique=50, memo=memo)
    assert found.status == "FOUND"
    assert found.reused is False
    again = search_targets(source, [(later, 6, 4)], time_limit_s=2, max_unique=50, memo=memo)
    assert again.reused is True
    assert again.status == "FOUND"
    assert again.expanded == 0
    assert again.actions == found.actions
    assert memo["hits"] == 1


def test_workspace_and_excavation_probes_reuse_only_a_matching_budget(monkeypatch):
    calls = []

    def fake(_state, **kwargs):
        calls.append((kwargs.get("time_limit_s"), kwargs.get("max_nodes")))
        return _Probe(RealizationStatus.RESOURCE_LIMIT)

    monkeypatch.setattr("spider.planner.backward_strategy.realize_workspace", fake)
    state = _blocked()
    assert workspace_probe_seconds.get() is None
    direct = _cheap_workspace_cost(state)
    assert direct[0] is None
    assert calls == [(0.35, 400)]
    cache = {"hits": 0, "misses": 0, "negative_hits": 0}
    token_s = workspace_probe_seconds.set(0.08)
    token_c = workspace_probe_cache.set(cache)
    try:
        first = _cheap_workspace_cost(state)
        second = _cheap_workspace_cost(state)
        assert first[0] is None and second == first
        assert "resource_limit" in first[1]
        assert cache["misses"] == 1
        assert cache["hits"] == 1
        assert cache["negative_hits"] == 1
        assert len(calls) == 2
        workspace_probe_seconds.set(0.20)
        third = _cheap_workspace_cost(state)
        assert third[0] is None
        assert cache["misses"] == 2
        assert len(calls) == 3
        assert calls[2][0] != calls[1][0]
    finally:
        workspace_probe_seconds.reset(token_s)
        workspace_probe_cache.reset(token_c)
    buried_state, buried = _zero_buried()
    lock = {}
    limited = _cached_excavation(
        buried_state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert limited.status == "NODE_LIMIT"
    assert excavation_probe_category(limited) == "NODE_LIMIT"
    repeated = _cached_excavation(
        buried_state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=1,
        time_left=5,
    )
    assert repeated is limited
    assert lock["probe_stats"]["hits"] == 1
    assert lock["probe_stats"]["misses"] == 1
    assert lock["probe_stats"]["negative_hits"] == 1
    wider = _cached_excavation(
        buried_state,
        buried,
        (),
        lock,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=80,
        time_left=5,
    )
    assert wider is not limited
    assert lock["probe_stats"]["misses"] == 2
    skipped = _cached_excavation(
        buried_state,
        buried,
        (),
        {},
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=20,
        time_left=0.01,
    )
    assert skipped.status == "TIME_LIMIT"
    fresh = {}
    _cached_excavation(
        buried_state,
        buried,
        (),
        fresh,
        source_key="tableau:0:down:0",
        column=0,
        max_cost=4,
        max_nodes=20,
        time_left=0.01,
    )
    assert fresh["excavation_cache"] == {}


def test_cold_mode_stays_independent_and_the_two_routes_stay_separate():
    opening = _micro()
    try:
        optimise_anchored(opening, ((0, 1, 12),), mode="cold", adaptive=True)
        raised = False
    except AnchoredRefused as exc:
        raised = True
        assert "cold" in str(exc).lower()
    assert raised
    try:
        optimise_anchored(opening, ((0, 1, 12),), mode="solve", adaptive=True)
        solve_raised = False
    except AnchoredRefused:
        solve_raised = True
    assert solve_raised
    cold = solve(opening, _profile(max_steps=2), mode="cold")
    assert cold.provenance["anchored_used"] is False
    assert cold.provenance["approach"] == "global"
    assert cold.provenance["cold_injection"] is False
    assert cold.provenance["adaptive"] is False
    assert cold.provenance["target_mode"] == "global"
    assert cold.provenance["workspace_probe"]["seconds"] == 0.08
    assert cold.provenance["workspace_probe"]["default_seconds"] == 0.35
    assert cold.provenance["workspace_probe"]["resource_limit_is_not_infeasibility"] is True
    assert cold.status == "SOLVED_VALID"
    assert cold.solved is True
    assert cold.foundations == 8
    main = _cli()
    assert main(["--deal", str(DEAL), "--mode", "solve", "--adaptive"]) == 2
    assert main(["--deal", str(DEAL), "--mode", "cold", "--adaptive"]) == 2
    assert main(["--deal", str(DEAL), "--mode", "cold", "--incumbent", str(MOVES_185)]) == 2
    assert main(["--deal", str(DEAL), "--mode", "anchored", "--adaptive"]) == 2

    before_185 = MOVES_185.stat().st_mtime_ns
    before_172 = MOVES_172.stat().st_mtime_ns
    before_registry = REGISTRY.stat().st_mtime_ns
    deal = opening_from_deal(DEAL)
    actions_185 = tuple(parse_moves_file(MOVES_185))
    actions_172 = tuple(parse_moves_file(MOVES_172))
    assert actions_185 != actions_172
    route_185 = verify_complete_solution(deal, actions_185, expected_cost=185, source="imported")
    route_172 = verify_complete_solution(deal, actions_172, expected_cost=172, source="imported")
    assert route_185.foundations == 8 and route_172.foundations == 8
    checkpoints = build_checkpoints(deal, route_185.actions)
    regions = select_adaptive_regions(checkpoints, route_185.actions, horizon=16, max_regions=6)
    assert _covered_known(regions) == [65, 168, 177, 183]
    held_185 = optimise_anchored(
        deal,
        actions_185,
        adaptive=True,
        time_limit_s=0,
        expected_cost=185,
        source="imported",
        source_id="mw185",
    )
    held_172 = optimise_anchored(
        deal,
        actions_172,
        adaptive=True,
        time_limit_s=0,
        expected_cost=172,
        source="imported",
        source_id="mw172",
    )
    assert held_185.cumulative_g == 185
    assert held_172.cumulative_g == 172
    assert held_185.actions == actions_185
    assert held_172.actions == actions_172
    assert held_185.provenance["source_id"] == "mw185"
    assert held_172.provenance["source_id"] == "mw172"
    assert held_185.provenance["production_registry_written"] is False
    assert held_172.provenance["production_registry_written"] is False
    assert MOVES_185.stat().st_mtime_ns == before_185
    assert MOVES_172.stat().st_mtime_ns == before_172
    assert REGISTRY.stat().st_mtime_ns == before_registry


def test_eight_foundations_remain_the_victory_condition_and_fixed_mode_still_improves():
    opening = _micro()
    try:
        verify_complete_solution(opening, ())
        empty_ok = False
    except IncumbentRejected as exc:
        empty_ok = True
        assert "foundations=7" in str(exc)
    assert empty_ok
    detour = ((0, 3, 1), (1, 2, 1), (3, 0, 1), (0, 2, 12))
    fixed = optimise_anchored(
        opening,
        detour,
        adaptive=False,
        time_limit_s=5,
        window_time_s=2,
        max_windows=8,
        max_unique=800,
        source="imported",
        source_id="detour",
    )
    assert fixed.provenance["target_mode"] == "fixed-endpoint"
    assert fixed.cumulative_g == 1
    assert fixed.replay["foundations"] == 8
    assert len(all_legal_actions(opening)) >= 1
