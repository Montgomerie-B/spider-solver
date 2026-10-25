"""v0.117 complete-solution and incumbent-ceiling tests.

The 185 and 172 files are replayed, not rewritten. The improvement fixture
is a constructed board, not deal 4925153.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.human_strategy.controller import solve
from spider.human_strategy.evaluation import (
    admissible_remaining,
    estimate_remaining,
    stock_rows,
    tableau_assembly_estimate,
)
from spider.human_strategy.foundation_direction import (
    _cached_excavation,
    _cover_depth,
    _legally_movable_head,
    excavation_probe_category,
    plan_obstructed_access,
)
from spider.human_strategy.incumbent import (
    IncumbentRejected,
    excavation_cost_cap,
    proof_prune,
    verify_complete_solution,
)
from spider.human_strategy.profiles import resolve_profile
from spider.human_strategy.strategic_frontier import StrategicFrontier
from spider.metrics import export_actions_to_moves_file, parse_moves_file, replay_actions
from spider.planner.lower_bounds import compute_solution_lower_bound
from spider.research_actions import apply_action, opening_from_deal, step_cost
from spider.state_identity import canonical_state_key

DEAL = ROOT / "deals" / "4925153.txt"
MOVES_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
MOVES_172 = ROOT / "solutions" / "4925153_canonical.moves"
REGISTRY = ROOT / "solutions" / "4925153_incumbent.json"
G83_PATH = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"
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


def _micro():
    return _state({0: HEARTS, 1: "kh"}, foundations=7)


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


def _pad(columns):
    cols = list(columns)
    while len(cols) < 10:
        cols.append(Column([Card("d", 13)], [Card("s", 13)]))
    return SpiderState(cols, [])


def _clubs_board():
    buried = Card("c", 8)
    state = _pad(
        [
            Column([buried], [Card("c", 6), Card("s", 3)]),
            Column([], [Card("d", 4)]),
            Column([], [Card("d", 7)]),
        ]
    )
    return state, buried


def _g83_actions():
    payload = json.loads(G83_PATH.read_text(encoding="utf-8"))
    actions = []
    for text in payload["actions"]:
        parts = text.split()
        if parts[0] == "deal":
            actions.append(("deal",))
        else:
            actions.append((int(parts[1]) - 1, int(parts[2]) - 1, int(parts[3])))
    return tuple(actions)


def _cli():
    path = ROOT / "tools" / "human_strategy_solver.py"
    spec = importlib.util.spec_from_file_location("human_strategy_solver_v0117", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def _short():
    result = solve(_micro(), _profile(max_steps=2))
    assert result.status == "SOLVED_VALID"
    assert result.cumulative_g == 1
    assert result.actions == ((0, 1, 12),)
    return result


def _long_route():
    short = _short()
    actions = ((0, 2, 1), (2, 0, 1)) + tuple(short.actions)
    route = verify_complete_solution(_micro(), actions, source="imported", source_id="waste")
    assert route.cost == 3
    return route


def test_complete_185_solution_replays_as_a_verified_incumbent():
    opening = opening_from_deal(DEAL)
    before = REGISTRY.stat().st_mtime_ns
    route = verify_complete_solution(
        opening,
        parse_moves_file(MOVES_185),
        expected_cost=185,
        source="imported",
        source_id=str(MOVES_185),
    )
    assert route.cost == 185
    assert route.foundations == 8
    assert route.solved is True
    assert route.source == "imported"
    assert REGISTRY.stat().st_mtime_ns == before
    assert MOVES_185.stat().st_size > 0


def test_partial_solution_is_rejected_as_an_incumbent():
    opening = opening_from_deal(DEAL)
    partial = parse_moves_file(MOVES_185)[:8]
    try:
        verify_complete_solution(opening, partial, expected_cost=8)
    except IncumbentRejected as exc:
        assert "partial trajectory" in str(exc)
    else:
        raise AssertionError("a partial trajectory was accepted")


def test_incorrect_cost_is_rejected():
    opening = opening_from_deal(DEAL)
    try:
        verify_complete_solution(
            opening,
            parse_moves_file(MOVES_185),
            expected_cost=184,
        )
    except IncumbentRejected as exc:
        assert "incorrect cost" in str(exc)
        assert "185" in str(exc)
    else:
        raise AssertionError("a mis-costed complete route was accepted")


def test_illegal_incumbent_is_rejected():
    opening = _micro()
    try:
        verify_complete_solution(opening, ((0, 0, 1),))
    except IncumbentRejected as exc:
        assert "illegal incumbent" in str(exc)
    else:
        raise AssertionError("an illegal action was accepted")


def test_cold_and_solve_modes_do_not_load_a_known_solution():
    main = _cli()
    assert main(["--deal", str(DEAL), "--mode", "cold", "--incumbent", str(MOVES_185)]) == 2
    assert main(["--deal", str(DEAL), "--mode", "solve", "--incumbent", str(MOVES_172)]) == 2
    state = _micro()
    try:
        solve(state, _profile(), mode="cold", incumbent_actions=(("deal",),))
    except ValueError as exc:
        assert "cold mode" in str(exc)
    else:
        raise AssertionError("cold mode accepted an incumbent sequence")
    try:
        solve(state, _profile(), mode="solve", incumbent_actions=(("deal",),))
    except ValueError as exc:
        assert "solve mode" in str(exc)
    else:
        raise AssertionError("solve mode accepted an incumbent sequence")
    found = solve(state, _profile(max_steps=2), mode="solve")
    assert found.provenance["prefix_injected"] is False
    assert found.provenance["assisted_suffix"] is False
    assert found.provenance["incumbent_source"] == "discovered"
    assert found.provenance["new_discovery"] is True
    assert found.cumulative_g == 1
    assert len(found.actions) != len(parse_moves_file(MOVES_185))


def test_optimise_initialises_the_verified_cost_and_keeps_a_loose_ceiling():
    route = _long_route()
    state = _micro()
    result = solve(
        state,
        _profile(max_steps=0),
        mode="optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cost,
    )
    assert result.solved is False
    assert result.provenance["best_verified_cost"] == 3
    assert result.provenance["ceiling_initial"] == 3
    assert result.provenance["improved"] is False
    assert result.provenance["incumbent_source"] == "imported"
    assert result.provenance["search_status"] == "STEP_LIMIT"
    assert result.cumulative_g == 0
    assert result.provenance["partial_g_is_not_the_best_complete_route"] is True


def test_branch_is_pruned_when_g_plus_bound_meets_the_incumbent():
    state = _micro()
    bound = admissible_remaining(state)
    assert bound == 1
    assert proof_prune(0, bound, bound) is True
    result = solve(state, _profile(max_steps=2), mode="optimise", incumbent_mw=bound)
    assert result.actions == ()
    assert result.solved is False
    assert result.status == "EXHAUSTED"
    assert result.provenance["safe_prunes"] >= 1
    assert result.provenance["pruned_by_admissible_bound"] == result.provenance["safe_prunes"]
    assert any(event.startswith("incumbent bound:") for event in result.events)
    assert "admissible 1" in " ".join(result.events)


def test_branch_is_kept_when_g_plus_bound_is_below_the_incumbent():
    state = _micro()
    bound = admissible_remaining(state)
    assert proof_prune(0, bound, bound + 1) is False
    result = solve(state, _profile(max_steps=2), mode="optimise", incumbent_mw=bound + 1)
    assert result.status == "SOLVED_VALID"
    assert result.cumulative_g == 1
    assert result.cumulative_g + 0 < bound + 1
    assert not any(event.startswith("incumbent bound: g 0") for event in result.events)


def test_zero_cost_move_does_not_spend_corrected_cost():
    state = _micro()
    assert step_cost(state, (1, 2, 1)) == 0
    trial = state.clone()
    assert apply_action(trial, (1, 2, 1)) == 0
    bound = admissible_remaining(state)
    assert proof_prune(0, bound, bound + 1) is False
    assert proof_prune(1, bound, bound + 1) is True
    assert admissible_remaining(trial) >= 0


def test_lower_bound_domain_keeps_stock_empty_assembly_off_the_opening():
    stocked = _prep()
    assert stock_rows(stocked) > 0
    assert stock_empty_assembly_h(stocked, 0) == 0
    proof = compute_solution_lower_bound(stocked).h_admissible
    assert admissible_remaining(stocked) == proof
    assert tableau_assembly_estimate(stocked) >= 0
    estimate = estimate_remaining(stocked)
    assert estimate > proof
    pruned = solve(stocked, _profile(max_steps=1), mode="optimise", incumbent_mw=proof)
    assert pruned.actions == ()
    assert any(f"admissible {proof}" in event for event in pruned.events)
    kept = solve(stocked, _profile(max_steps=1), mode="optimise", incumbent_mw=proof + 1)
    assert kept.actions
    assert not any(event.startswith("incumbent bound: g 0") for event in kept.events)
    empty = _micro()
    assert stock_rows(empty) == 0
    base = compute_solution_lower_bound(empty).h_admissible
    assembly = stock_empty_assembly_h(empty, 0)
    assert admissible_remaining(empty) == max(base, assembly)
    assert assembly >= 1


def test_heuristic_exclusion_is_not_reported_as_a_proof():
    frontier = StrategicFrontier(limit=2, proposals=1)
    states = [_state({0: "kh"}, foundations=count) for count in range(4)]
    for index, item in enumerate(states):
        frontier.consider(
            state=item,
            g=0,
            actions=(),
            lock={"label": f"L{index}"},
            force_id=str(index),
            reason=f"line {index}",
            label=f"L{index}",
            payload=None,
        )
    assert frontier.dropped_full >= 1
    assert frontier.limit == 2
    pruned = solve(_micro(), _profile(max_steps=2), mode="optimise", incumbent_mw=0)
    assert pruned.provenance["heuristic_exclusion_is_not_proof"] is True
    assert pruned.provenance["safe_prunes"] >= 1
    assert pruned.provenance["heuristic_exclusions"] == 0
    assert "proof" in pruned.provenance["safe_prune_rule"]


def test_exact_state_dominance_keeps_the_cheaper_ancestry():
    state = _micro()
    frontier = StrategicFrontier(limit=4, proposals=2)
    first, _event = frontier.consider(
        state=state.clone(),
        g=1,
        actions=(),
        lock={"label": "short"},
        force_id=None,
        reason="short",
        label="short",
        payload=None,
    )
    second, event = frontier.consider(
        state=state.clone(),
        g=3,
        actions=((0, 2, 1),),
        lock={"label": "long"},
        force_id=None,
        reason="long",
        label="long",
        payload=None,
    )
    assert first is True
    assert second is False
    assert frontier.transpositions == 1
    assert "transposition" in event
    assert all(node.g <= 1 for node in frontier.queue)
    same = frontier.consider(
        state=state.clone(),
        g=1,
        actions=(),
        lock={"label": "other"},
        force_id=None,
        reason="other",
        label="other",
        payload=None,
    )
    assert same[0] is True
    assert {node.label for node in frontier.queue} >= {"short", "other"}


def test_equivalent_physical_state_keeps_distinct_labels_and_distinct_structure():
    state = _micro()
    clone = state.clone()
    assert canonical_state_key(state) == canonical_state_key(clone)
    assert state.columns[1].face_up[0] is clone.columns[1].face_up[0]
    other = _state({0: HEARTS, 1: "kh"}, foundations=7)
    assert state.columns[1].face_up[0] == other.columns[1].face_up[0]
    assert state.columns[1].face_up[0] is not other.columns[1].face_up[0]
    assert canonical_state_key(state) == canonical_state_key(other)
    fewer = _state({0: HEARTS, 1: "kh"}, foundations=6)
    assert canonical_state_key(state) != canonical_state_key(fewer)
    hidden = _state({0: ("kh", "ah")})
    visible = _state({0: "kh ah"})
    assert canonical_state_key(hidden) != canonical_state_key(visible)
    stocked = _state({0: "kh"}, stock="as 2s 3s 4s 5s 6s 7s 8s 9s 10s")
    bare = _state({0: "kh"})
    assert canonical_state_key(stocked) != canonical_state_key(bare)


def test_unsuccessful_search_retains_the_previous_incumbent():
    route = _long_route()
    result = solve(
        _micro(),
        _profile(time_limit_s=0, max_steps=4),
        mode="optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cost,
    )
    assert result.status == "TIME_LIMIT"
    assert result.solved is False
    assert result.actions == ()
    assert result.provenance["best_verified_cost"] == 3
    assert result.provenance["improved"] is False
    assert result.provenance["search_status"] == "TIME_LIMIT"
    assert result.provenance["incumbent_source"] == "imported"
    assert result.provenance["retained_actions"]
    assert result.cumulative_g < result.provenance["best_verified_cost"]
    assert result.provenance["partial_g_is_not_the_best_complete_route"] is True


def test_incumbent_is_replaced_only_by_a_strictly_cheaper_replayed_route():
    route = _long_route()
    state = _micro()
    improved = solve(
        state,
        _profile(max_steps=4),
        mode="optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cost,
    )
    assert improved.status == "SOLVED_VALID"
    assert improved.solved is True
    assert improved.cumulative_g == 1
    assert improved.cumulative_g < route.cost
    assert improved.actions == ((0, 1, 12),)
    assert improved.replay and improved.replay.get("ok")
    assert improved.provenance["improved"] is True
    assert improved.provenance["best_verified_cost"] == 1
    assert improved.provenance["incumbent_source"] == "discovered"
    assert improved.provenance["new_discovery"] is True
    assert improved.provenance["reproduced_incumbent"] is False
    again = verify_complete_solution(state, improved.actions, expected_cost=1)
    assert again.solved is True

    same = solve(
        state,
        _profile(max_steps=2),
        mode="optimise",
        incumbent_actions=improved.actions,
        incumbent_mw=10,
    )
    assert same.cumulative_g == 1
    assert same.provenance["improved"] is False
    assert same.provenance["best_verified_cost"] == 1
    assert same.provenance["reproduced_incumbent"] is True


def test_partial_trajectory_is_not_a_better_solution_than_the_incumbent():
    route = _short()
    result = solve(
        _micro(),
        _profile(max_steps=0),
        mode="optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cumulative_g,
    )
    assert result.provenance["reported_trajectory"] == "empty"
    assert result.cumulative_g == 0
    assert result.provenance["best_verified_cost"] == 1
    assert result.provenance["improved"] is False
    assert result.solved is False
    assert result.provenance["partial_g_is_not_the_best_complete_route"] is True


def test_timeout_reports_the_verified_incumbent():
    route = _short()
    result = solve(
        _micro(),
        _profile(time_limit_s=0),
        mode="optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cumulative_g,
    )
    assert result.provenance["best_verified_cost"] == 1
    assert result.provenance["improved"] is False
    assert result.provenance["search_status"] == "TIME_LIMIT"
    assert result.status == "TIME_LIMIT"
    assert result.solved is False
    assert result.provenance["resource_stops"] >= 1


def test_solution_export_replays_independently(tmp_path):
    found = _short()
    path = tmp_path / "micro.moves"
    export_actions_to_moves_file(list(found.actions), path, header="v0.117 micro")
    route = verify_complete_solution(_micro(), parse_moves_file(path), expected_cost=1)
    assert route.cost == 1
    assert route.solved is True
    text = path.read_text(encoding="utf-8")
    assert "move 1 2 12" in text


def test_nested_search_honours_the_remaining_budget_and_a_cost_ceiling():
    assert excavation_cost_cap(4, None) == 4
    assert excavation_cost_cap(4, 9) == 4
    assert excavation_cost_cap(4, 0) == 0
    state, buried = _clubs_board()
    rushed = _cached_excavation(
        state,
        buried,
        (),
        {},
        source_key="clubs",
        column=0,
        max_cost=4,
        max_nodes=800,
        time_left=0.01,
    )
    assert rushed is not None
    assert rushed.status == "TIME_LIMIT"
    assert excavation_probe_category(rushed) != "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"
    capped = _cached_excavation(
        state,
        buried,
        (),
        {"cost_ceiling": 0},
        source_key="clubs-capped",
        column=0,
        max_cost=4,
        max_nodes=40,
        time_left=2.0,
    )
    assert capped is not None
    assert capped.max_cost_limit == 0
    assert excavation_probe_category(capped) != "PROVEN_INFEASIBLE_UNDER_EXPLICIT_CONDITIONS"
    quick = solve(_micro(), _profile(time_limit_s=0), mode="cold")
    assert "remaining global deadline" in quick.provenance["nested_budget"]
    assert quick.provenance["heuristic_remainder_is_not_a_proof"] is True
    assert quick.status == "TIME_LIMIT"


def test_g19_g83_and_clubs_excavation_stay_available():
    actions = _g83_actions()
    assert len(actions) == 83
    opening = opening_from_deal(DEAL)
    early = opening.clone()
    assert replay_actions(early, list(actions[:19])) == 19
    assert len(early.foundations) == 1
    assert early.foundations[0][0].suit == "s"
    assert early.is_solved() is False
    full = opening.clone()
    assert replay_actions(full, list(actions)) == 83
    assert [item[0].suit for item in full.foundations] == ["s", "c"]
    assert full.is_solved() is False
    state, buried = _clubs_board()
    revealed = plan_obstructed_access(state, buried, (), max_cost=4, max_nodes=40)
    assert revealed is not None
    assert revealed.status == "exposed"
    assert revealed.depth_after == 0
    assert revealed.cost == 2
    assert _cover_depth(state, buried) == 2
    trial = state.clone()
    for action in revealed.actions:
        apply_action(trial, action)
    assert buried in trial.columns[0].face_up
    assert _legally_movable_head(trial, buried) is False


def test_solve_then_optimise_improves_a_worse_incumbent_without_using_it_as_the_solve():
    route = _long_route()
    result = solve(
        _micro(),
        _profile(max_steps=4, time_limit_s=4),
        mode="solve-optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cost,
    )
    assert result.mode == "solve-optimise"
    assert result.solved is True
    assert result.cumulative_g == 1
    assert result.cumulative_g < route.cost
    assert result.provenance["incumbent_source"] == "discovered"
    assert result.provenance["prefix_injected"] is False
    assert result.provenance["assisted_suffix"] is False
    assert result.provenance["improved"] is False
    assert result.provenance["best_verified_cost"] == 1
    assert result.provenance["solve_stage_completed"] is True
    stalled = solve(
        _micro(),
        _profile(max_steps=0, time_limit_s=2),
        mode="solve-optimise",
        incumbent_actions=route.actions,
        incumbent_mw=route.cost,
    )
    assert stalled.solved is False
    assert stalled.provenance["best_verified_cost"] == 3
    assert stalled.provenance["improved"] is False
    assert stalled.provenance["incumbent_source"] == "imported"
    assert stalled.provenance["solve_stage_completed"] is False
    assert stalled.provenance["search_status"] in {"STEP_LIMIT", "TIME_LIMIT", "EXHAUSTED"}


def test_canonical_172_is_a_separate_verified_complete_route():
    opening = opening_from_deal(DEAL)
    route = verify_complete_solution(
        opening,
        parse_moves_file(MOVES_172),
        expected_cost=172,
        source="imported",
        source_id=str(MOVES_172),
    )
    assert route.cost == 172
    assert route.solved is True
    assert route.actions != tuple(parse_moves_file(MOVES_185))


def test_cli_optimise_rejects_a_partial_file_and_a_timeout_keeps_185(tmp_path, capsys):
    main = _cli()
    partial = tmp_path / "partial.moves"
    partial.write_text("move 3 6 1\n", encoding="utf-8")
    assert main(["--deal", str(DEAL), "--mode", "optimise", "--incumbent", str(partial)]) == 2
    illegal = tmp_path / "illegal.moves"
    illegal.write_text("move 1 1 1\n", encoding="utf-8")
    assert main(["--deal", str(DEAL), "--mode", "optimise", "--incumbent", str(illegal)]) == 2
    out = tmp_path / "opt.json"
    before = REGISTRY.stat().st_mtime_ns
    code = main(
        [
            "--deal",
            str(DEAL),
            "--mode",
            "optimise",
            "--incumbent",
            str(MOVES_185),
            "--time-limit",
            "0",
            "--max-steps",
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
    document = json.loads(out.read_text(encoding="utf-8"))
    provenance = document["result"]["provenance"]
    assert provenance["best_verified_cost"] == 185
    assert provenance["improved"] is False
    assert provenance["incumbent_source"] == "imported"
    assert provenance["prefix_injected"] is False
    assert document["result"]["solved"] is False
    assert document["schema"] == "spider-human-strategy-0.118"
    assert REGISTRY.stat().st_mtime_ns == before
