"""Mechanism tests for witness-guided play. No official paired episode runs."""

from __future__ import annotations

import sys
from pathlib import Path
from time import perf_counter

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.packed_state import pack_state
from spider.practical_witness_manifest import prepare_manifest
from spider.practical_witness_play import (
    RECOMMENDATIONS,
    Endpoint,
    EpisodeBudget,
    ProbeEvidence,
    allocate_probes,
    arrive,
    audit_replay,
    choose,
    collect_decision,
    compare_endpoints,
    execute_plan,
    independent_cold_complete,
    judge_trial,
    observed_trajectory,
    probe_candidate,
    recommendation,
    reveal_predicate,
    run_episode,
    run_paired_trial,
    tightened_limits,
)
from spider.research_actions import all_legal_actions, face_down_count, is_deal, step_cost
from spider.search_kernel import KernelResult, SearchLimits


def _column(down, up):
    return Column(
        [Card.parse(token) for token in down],
        [Card.parse(token) for token in up],
    )


def _singles(tokens):
    return [_column([], [token]) for token in tokens]


def _two_reveal_state():
    # 3h onto 4c and 8d onto 9c are the only legal moves. The sixes connect to neither.
    columns = [
        _column(["ks"], ["3h"]),
        _column([], ["4c"]),
        _column(["kd"], ["8d"]),
        _column([], ["9c"]),
        *_singles(["6s", "6h", "6d", "6c", "6s", "6h"]),
    ]
    return SpiderState(columns, [])


def _one_reveal_state():
    columns = [
        _column(["ks"], ["3h"]),
        _column([], ["4c"]),
        *_singles(["6s", "6h", "6d", "6c", "6s", "6h", "6d", "6c"]),
    ]
    return SpiderState(columns, [])


def _quiet_state():
    return SpiderState(_singles(["as", "ah", "ad", "ac", "4s", "4h", "4d", "4c", "6s", "6c"]), [])


def _deal_state():
    columns = [Column([], [])]
    columns.extend(_singles(["as", "ah", "ad", "ac", "2s", "2h", "2d", "2c", "3s"]))
    stock = [Card.parse(token) for token in ["4s", "5s", "6s", "7s", "8s", "9s", "10s", "js", "qs", "ks"]]
    return SpiderState(columns, stock)


def _budget(**overrides):
    values = dict(
        wall_s=5.0,
        additional_paid=12,
        primitive_actions=64,
        planning_decisions=8,
        probe_identities=40,
        rss_mb=8192.0,
        probe_max_unique=8,
        probe_time_s=0.5,
        probe_rss_mb=8192.0,
        probe_cost_ceiling=4,
        workers=1,
    )
    values.update(overrides)
    return EpisodeBudget(**values)


def _evidence(option_id, index, status, cost):
    verified = status in ("exact", "upper-unfinished")
    prefix = ((index, 0, 1),)
    return ProbeEvidence(
        option_id=option_id,
        baseline_index=index,
        prefix_actions=prefix,
        plan=prefix + ((0, 1, 1),) if verified else prefix,
        prefix_cost=1,
        continuation=((0, 1, 1),) if verified else (),
        continuation_cost=(None if cost is None else int(cost) - 1),
        total_cost=None if not verified else int(cost),
        status=status,
        stop_reason="unique limit" if status == "upper-unfinished" else status,
        kernel_called=True,
        unique=4,
        admissible_bound=status == "exact",
        scoped_minimum=status == "exact",
        full_game_optimum=False,
        bound_scope="reveal-goal" if status == "exact" else "none",
    )


def test_unfinished_witness_orders_without_becoming_admissible():
    evidence = [
        _evidence("unknown-move", 0, "unknown", None),
        _evidence("capped-witness", 1, "upper-unfinished", 2),
        _evidence("exact-later", 2, "exact", 3),
    ]
    witness = choose("witness", evidence)
    baseline = choose("baseline", evidence)
    assert witness.option_id == "capped-witness"
    assert witness.used_witness is True
    assert witness.witness_status == "upper-unfinished"
    assert witness.admissible_bound is False
    assert witness.scoped_minimum is False
    assert witness.full_game_optimum is False
    assert witness.optimality_claim is False
    assert "unknown-move" in witness.unknown_ids
    assert baseline.option_id == "unknown-move"
    assert baseline.used_witness is False
    assert baseline.actions == evidence[0].prefix_actions
    assert [item.status for item in evidence] == ["unknown", "upper-unfinished", "exact"]


def test_ties_follow_baseline_order_and_no_witness_uses_the_same_fallback():
    tied = [
        _evidence("first", 0, "upper-unfinished", 2),
        _evidence("second", 1, "exact", 2),
    ]
    assert choose("witness", tied).option_id == "first"
    missing = [
        _evidence("baseline", 0, "unknown", None),
        _evidence("other", 1, "exhausted-no-hit", None),
    ]
    baseline = choose("baseline", missing)
    witness = choose("witness", missing)
    assert baseline.actions == witness.actions == missing[0].prefix_actions
    assert baseline.option_id == witness.option_id == "baseline"
    assert witness.reason == "baseline-fallback"


def test_allocate_reserves_the_eighth_slot_for_deal_only():
    class _Option:
        def __init__(self, option_id, actions):
            self.option_id = option_id
            self.actions = actions

    ordered = [_Option(f"move-{index}", ((index, 0, 1),)) for index in range(9)]
    ordered.append(_Option("('deal',)", (("deal",),)))
    probed, unprobed, displaced, reserved = allocate_probes(ordered, slots=8)
    assert reserved is True
    assert probed[-1].option_id == "('deal',)"
    assert probed[0].option_id == "move-0"
    assert displaced.option_id == "move-7"
    assert displaced.option_id in {option.option_id for option in unprobed}
    assert "impossible" not in " ".join(option.option_id for option in unprobed)
    already = allocate_probes(ordered[:8], slots=8)
    assert already[3] is False


def test_real_admission_keeps_deal_legal_and_can_reserve_it():
    state = _deal_state()
    legal = all_legal_actions(state)
    assert ("deal",) in legal
    assert any(column.is_empty() for column in state.columns)
    from spider.practical_witness_play import admit_options

    actions, pick, _elapsed, status = admit_options(state)
    assert status == "matched"
    assert ("deal",) in actions
    probed, unprobed, displaced, reserved = allocate_probes(pick.chosen)
    assert reserved is True
    assert any(is_deal(action) for option in probed for action in option.actions)
    assert displaced is not None
    assert not any(is_deal(action) for action in displaced.actions)
    assert unprobed
    assert probed[0].actions != (("deal",),)


def test_probe_searches_every_legal_action_including_deal_without_a_lower_bound(monkeypatch):
    captured = {}

    def fake_run_search(roots, **kwargs):
        captured["roots"] = roots
        captured["kwargs"] = kwargs
        result = KernelResult()
        result.stop_reason = "complete"
        result.unique = 1
        return result

    monkeypatch.setattr("spider.practical_witness_play.run_search", fake_run_search)
    state = _two_reveal_state()
    from spider.practical_witness_play import admit_options

    _actions, pick, _elapsed, status = admit_options(state)
    assert status == "matched"
    option = pick.chosen[0]
    limits = SearchLimits(
        max_unique=20,
        time_limit_s=2.0,
        rss_abort_mb=512.0,
        cost_ceiling=4,
        harvest_slack=None,
        max_depth=None,
        proof_ceiling=None,
    )
    evidence, _elapsed = probe_candidate(state, option, reveal_predicate(state), limits, 0)
    assert captured["kwargs"]["actions_fn"] is all_legal_actions
    assert captured["kwargs"]["identity_fn"] is pack_state
    assert captured["kwargs"]["stop_on_first_terminal"] is False
    assert "lower_bound_fn" not in captured["kwargs"]
    assert captured["kwargs"]["limits"].cost_ceiling == 4
    assert captured["kwargs"]["limits"].max_depth is None
    assert captured["kwargs"]["limits"].harvest_slack is None
    assert captured["roots"][0]["g"] == evidence.prefix_cost == 1
    assert evidence.full_game_optimum is False


def test_prefix_terminal_does_not_call_the_kernel_or_solve_the_game():
    state = _one_reveal_state()
    assert face_down_count(state) == 1
    draft = collect_decision(
        state,
        _budget(probe_max_unique=4, probe_time_s=0.2),
        remaining_wall=1.0,
        remaining_ids=20,
        remaining_paid=4,
    )
    assert draft.probed
    assert all(item.kernel_called is False for item in draft.probed)
    assert all(item.stop_reason == "prefix-terminal" for item in draft.probed)
    assert all(item.continuation == () for item in draft.probed)
    assert all(item.full_game_optimum is False for item in draft.probed)
    played = run_episode(state, "witness", _budget(probe_max_unique=4, probe_time_s=0.2))
    assert played["reveal_phase_complete"] is True
    assert played["solved"] is False
    assert played["independent_cold_complete"] is False
    assert played["hidden"] == 0
    assert played["primitives"] >= 1


def test_zero_cost_cycle_stops_at_equal_g():
    state = SpiderState(
        [_column([], ["6h"]), Column([], []), *_singles(["as", "ah", "ad", "ac", "4s", "4h", "4d", "4c"])],
        [],
    )
    assert step_cost(state, (0, 1, 1)) == 0
    seen = {}
    assert arrive(seen, pack_state(state).hex(), 0, initial=True) is None
    assert arrive(dict(seen), pack_state(state).hex(), 0) == "repeated-state"
    cheaper = {"pack": 5}
    assert arrive(cheaper, "pack", 4) is None
    assert cheaper["pack"] == 4
    _final, paid, primitives, played, stop, _detail = execute_plan(
        state,
        [(0, 1, 1), (1, 0, 1)],
        _budget(),
        seen,
        paid=0,
        primitives=0,
        started=perf_counter(),
        expected_cost=0,
        predicate=None,
        require_predicate=False,
    )
    assert stop == "repeated-state"
    assert primitives == 1
    assert paid == 0
    assert len(played) == 1


def test_budgets_tighten_probes_and_stop_on_the_identity_cap():
    wide = tightened_limits(
        EpisodeBudget(),
        remaining_wall=100.0,
        remaining_ids=1000,
        remaining_paid=100,
    )
    assert wide.max_unique == 20
    assert wide.time_limit_s == 2.0
    assert wide.cost_ceiling == 4
    tight = tightened_limits(
        EpisodeBudget(),
        remaining_wall=0.25,
        remaining_ids=5,
        remaining_paid=3,
    )
    assert tight.max_unique == 5
    assert tight.time_limit_s == 0.25
    assert tight.cost_ceiling == 3
    assert tight.max_depth is None
    assert tight.harvest_slack is None
    assert tightened_limits(
        EpisodeBudget(), remaining_wall=1.0, remaining_ids=0, remaining_paid=4
    ) is None
    played = run_episode(
        _two_reveal_state(),
        "baseline",
        _budget(probe_identities=1, probe_max_unique=20, probe_cost_ceiling=4, wall_s=10.0),
    )
    assert played["stop_reason"] == "probe-identities"
    assert played["probe_identities"] == 1
    assert played["checks_ok"] is True
    assert played["optimality_claim"] is False
    assert played["decision_records"]
    assert played["decision_records"][0]["unprobed_ids"]


def test_episode_replans_across_real_reveals_without_declaring_a_win():
    played = run_episode(
        _two_reveal_state(),
        "baseline",
        _budget(probe_cost_ceiling=1, probe_max_unique=4, probe_time_s=0.3),
    )
    assert played["decisions"] >= 2
    assert played["primitives"] >= 2
    assert played["hidden"] == 0
    assert played["stop_reason"] == "reveal_phase_complete"
    assert played["solved"] is False
    assert played["goals_completed"] >= 1
    assert played["independent_cold_complete"] is False
    assert all(record["selection"]["full_game_optimum"] is False for record in played["decision_records"])


def test_source_mismatch_executes_nothing():
    played = run_episode(_two_reveal_state(), "witness", _budget(), source_pack="00")
    assert played["stop_reason"] == "correctness-blocker"
    assert played["checks_ok"] is False
    assert played["primitives"] == 0
    assert played["decisions"] == 0
    assert played["continuation_seconds"] == 0.0


def test_reveal_phase_stop_does_not_search(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("search ran after the reveal phase")

    monkeypatch.setattr("spider.practical_witness_play.run_search", boom)
    played = run_episode(_quiet_state(), "witness", _budget(wall_s=0.0))
    assert played["stop_reason"] == "time"
    assert played["decisions"] == 0
    phase = run_episode(_quiet_state(), "baseline", _budget())
    assert phase["stop_reason"] == "reveal_phase_complete"
    assert phase["solved"] is False
    assert phase["foundations"] == 0


def test_authentic_opening_audits_without_an_episode():
    root = prepare_manifest().roots[0]
    ok, reason = audit_replay(root, [], root.pack_hex, 0)
    assert ok, reason
    assert root.prefix_actions == ()


def test_progress_rule_and_verdict_are_predeclared():
    assert compare_endpoints(Endpoint(0, 10, False, 50), Endpoint(0, 10, False, 40)) == "tie"
    assert compare_endpoints(Endpoint(0, 8, False, 40), Endpoint(0, 6, False, 40)) == "witness"
    assert compare_endpoints(Endpoint(1, 8, False, 30), Endpoint(0, 8, False, 20)) == "baseline"
    assert compare_endpoints(Endpoint(0, 4, False, 30), Endpoint(1, 6, False, 20)) == "tradeoff"
    assert compare_endpoints(Endpoint(2, 0, True, 0), Endpoint(1, 3, False, 10)) == "baseline"
    assert judge_trial(["witness", "witness", "tie", "tradeoff"], checks_ok=True) == "PRACTICAL_SIGNAL_FOUND"
    assert judge_trial(["witness", "baseline", "witness", "tie"], checks_ok=True) == "NO_CLEAR_BENEFIT"
    assert judge_trial(["witness", "tie", "tie", "tie"], checks_ok=True) == "NO_CLEAR_BENEFIT"
    assert judge_trial(["witness", "witness"], checks_ok=False) == "CORRECTNESS_BLOCKER"
    rows = observed_trajectory(
        [{"paid": 0, "hidden": 4}, {"paid": 2, "hidden": 2}],
        [{"paid": 0, "hidden": 4}, {"paid": 3, "hidden": 2}],
        4,
    )
    assert rows[0]["optimal"] is False
    assert rows[1]["label"] == "observed-trajectory-cost"
    assert independent_cold_complete(opening_root=False, solved=True, verifier_accepted=True) is False
    assert independent_cold_complete(opening_root=True, solved=False, verifier_accepted=False) is False
    assert recommendation("NO_CLEAR_BENEFIT") == RECOMMENDATIONS["NO_CLEAR_BENEFIT"]
    assert "unchanged" in recommendation("PRACTICAL_SIGNAL_FOUND")


def test_policy_module_has_no_reference_route_and_tests_do_not_launch_one():
    text = Path(run_episode.__code__.co_filename).read_text(encoding="utf-8")
    assert "canonical.moves" not in text
    assert "parse_moves_file" not in text
    assert "4925153_autonomous" not in text
    with pytest.raises(RuntimeError, match="official"):
        run_paired_trial(None, confirm_official=False)
