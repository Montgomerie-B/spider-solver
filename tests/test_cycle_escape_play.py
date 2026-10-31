"""Opt-in cycle-escape checks. These tests do not launch an official episode."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from time import perf_counter

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.packed_state import pack_state
from spider.practical_witness_manifest import (
    CANONICAL_SHA256_CRLF,
    CANONICAL_SHA256_LF,
    DEAL_SHA256_CRLF,
    DEAL_SHA256_LF,
    FrozenRoot,
    materialize_root,
    policy_specification,
    prepare_manifest,
)
from spider.practical_witness_play import (
    DecisionDraft,
    Endpoint,
    EpisodeBudget,
    Selection,
    admit_options,
    arrive,
    consider_cycle_escape,
    escape_label,
    execute_plan,
    judge_escape,
    recommendation,
    run_cycle_escape_trial,
    run_episode,
)
from spider.research_actions import all_legal_actions, apply_action, is_deal, step_cost

CONTROL = ROOT / "docs" / "practical_witness_play_pilot.json"
SPEC = ROOT / "docs" / "cycle_escape_play_manifest.json"
TRACE = ROOT / "docs" / "practical_witness_play_pilot.json"


def _column(down, up):
    return Column(
        [Card.parse(token) for token in down],
        [Card.parse(token) for token in up],
    )


def _singles(tokens):
    return [_column([], [token]) for token in tokens]


def _park_state():
    columns = [
        _column([], ["6h"]),
        Column([], []),
        _column([], ["5c"]),
        _column(["ks"], ["4s"]),
        *_singles(["as", "ah", "ad", "ac", "4h", "4d"]),
    ]
    stock = [
        Card.parse(token)
        for token in ["js", "jh", "jd", "jc", "qs", "qh", "qd", "qc", "ks", "kh"]
    ]
    return SpiderState(columns, stock)


def _budget(**overrides):
    values = dict(
        wall_s=5.0,
        additional_paid=12,
        primitive_actions=64,
        planning_decisions=8,
        probe_identities=40,
        rss_mb=8192.0,
        probe_max_unique=4,
        probe_time_s=0.2,
        probe_rss_mb=8192.0,
        probe_cost_ceiling=4,
        workers=1,
    )
    values.update(overrides)
    return EpisodeBudget(**values)


def _selection(action, *, used_witness=False, reason="baseline-fallback", actions=None):
    chosen = tuple(actions) if actions is not None else (action,)
    return Selection(
        mode="witness",
        option_id=str(action),
        actions=chosen,
        reason=reason,
        used_witness=used_witness,
        witness_status="upper-unfinished" if used_witness else None,
        total_cost=1 if used_witness else None,
        admissible_bound=False,
        scoped_minimum=False,
        full_game_optimum=False,
        optimality_claim=False,
        unknown_ids=(),
    )


def _order(*actions):
    return tuple((str(action), action) for action in actions)


def _call(state, selection, ordered, seen, budget=None, **overrides):
    values = dict(
        paid=0,
        primitives=0,
        started=perf_counter(),
        probed_status={},
        unprobed_ids=(),
        remaining_ids=40,
        decisions_used=1,
    )
    values.update(overrides)
    return consider_cycle_escape(
        state,
        selection,
        ordered,
        seen,
        _budget() if budget is None else budget,
        **values,
    )


def _faces(state):
    return (
        [list(column.face_down) for column in state.columns],
        [list(column.face_up) for column in state.columns],
        list(state.stock),
        [list(seq) for seq in state.foundations],
    )


def _destination(state, action, paid):
    clone = state.clone()
    cost = int(step_cost(clone, action))
    apply_action(clone, action)
    return pack_state(clone).hex(), cost, paid + cost


def test_default_episode_stops_and_the_opt_in_plays_the_next_fresh_action(monkeypatch):
    state = _park_state()
    start = pack_state(state).hex()
    park = (0, 1, 1)
    other = (2, 1, 1)
    back = (1, 0, 1)
    side = (2, 0, 1)
    assert step_cost(state, park) == 0

    def collect(current, _budget, **_kwargs):
        draft = DecisionDraft()
        if pack_state(current).hex() == start:
            actions = (park, other)
        else:
            actions = (back, side)
        draft.ordered_ids = tuple(str(action) for action in actions)
        draft.action_by_id = {str(action): action for action in actions}
        draft.legal_ids = draft.ordered_ids
        draft.obligations_status = "matched"
        return draft

    monkeypatch.setattr("spider.practical_witness_play.collect_decision", collect)
    monkeypatch.setattr(
        "spider.practical_witness_play.run_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("probe")),
    )
    budget = _budget(planning_decisions=2, probe_identities=8)
    default = run_episode(state, "witness", budget)
    assert default["stop_reason"] == "repeated-state"
    assert default["primitives"] == 1
    assert default["preview_count"] == 0
    assert default["probe_identities"] == 0
    assert default["cycle_escape"] is False
    assert all("recovery" not in record for record in default["decision_records"])
    assert pack_state(state).hex() == start

    escaped = run_episode(state, "witness", budget, cycle_escape=True)
    assert [tuple(step["action"]) for step in escaped["actions"]] == [park, side]
    assert escaped["stop_reason"] == "decisions"
    assert escaped["primitives"] == 2
    assert escaped["probe_identities"] == 0
    assert escaped["preview_count"] >= 2
    assert escaped["preview_seconds"] >= 0.0
    assert escaped["decision_records"][0]["recovery"]["triggered"] is False
    second = escaped["decision_records"][1]["recovery"]
    assert second["triggered"] is True
    assert second["selected_action"] == [2, 0, 1]
    assert second["proved_strategy"] is False
    assert second["admissible_bound"] is False
    assert second["used_witness"] is False
    assert second["optimality_claim"] is False
    assert second["preview_identities"] == 0
    assert escaped["decision_records"][1]["selection"]["actions"] == [[1, 0, 1]]
    assert pack_state(state).hex() == start


def test_witness_plans_are_not_replaced():
    state = _park_state()
    seen = {}
    arrive(seen, pack_state(state).hex(), 0, initial=True)
    repeat = (0, 1, 1)
    fresh = (2, 1, 1)
    destination, _cost, arrival = _destination(state, repeat, 0)
    seen[destination] = arrival
    ordered = _order(repeat, fresh)
    for actions in ((repeat,), (repeat, fresh)):
        outcome = _call(
            state,
            _selection(repeat, used_witness=True, actions=actions),
            ordered,
            seen,
        )
        assert outcome["replacement"] is None
        assert outcome["halt"] is None
        assert outcome["log"]["triggered"] is False
        assert outcome["preview_count"] == 0
        assert outcome["log"]["reason"] == "not-a-single-original-action-fallback"


def test_several_repeats_are_skipped_before_a_fresh_action_and_previews_do_not_mutate():
    state = _park_state()
    actions = [(0, 1, 1), (2, 1, 1), (4, 1, 1), (5, 1, 1)]
    for action in actions:
        assert action in all_legal_actions(state)
    seen = {pack_state(state).hex(): 0}
    for action in actions[:3]:
        destination, _cost, _arrival = _destination(state, action, 0)
        seen[destination] = 0
    before_seen = dict(seen)
    before_faces = _faces(state)
    before_pack = pack_state(state).hex()
    outcome = _call(state, _selection(actions[0]), _order(*actions), seen)
    assert outcome["halt"] is None
    assert outcome["replacement"] is not None
    assert outcome["replacement"].option_id == str(actions[3])
    assert outcome["replacement"].used_witness is False
    assert outcome["replacement"].admissible_bound is False
    assert outcome["replacement"].optimality_claim is False
    rejected = [
        row["option_id"]
        for row in outcome["log"]["checked"]
        if row["disposition"] == "repeat"
    ]
    assert rejected == [str(action) for action in actions[:3]]
    assert seen == before_seen
    assert _faces(state) == before_faces
    assert pack_state(state).hex() == before_pack
    assert actions[0] in all_legal_actions(state)
    assert outcome["log"]["preview_identities"] == 0
    assert outcome["preview_count"] == 4


def test_deal_is_an_ordinary_candidate_and_an_unprobed_fallback_stays_uncertain():
    state = _park_state()
    repeat = (0, 1, 1)
    tableau = (2, 1, 1)
    deal = ("deal",)
    assert is_deal(deal)
    assert deal in all_legal_actions(state)
    destination, _cost, _arrival = _destination(state, repeat, 0)
    seen = {pack_state(state).hex(): 0, destination: 0}
    deal_first = _call(state, _selection(repeat), _order(repeat, deal, tableau), seen)
    assert deal_first["replacement"].actions == (deal,)
    assert deal_first["log"]["deal_available"] is True
    assert deal_first["log"]["uncertainty"] == "unprobed-legal-fallback"
    assert deal_first["replacement"].admissible_bound is False
    assert deal_first["replacement"].full_game_optimum is False
    tableau_first = _call(
        state,
        _selection(repeat),
        _order(repeat, tableau, deal),
        seen,
        unprobed_ids=(str(tableau), str(deal)),
    )
    assert tableau_first["replacement"].actions == (tableau,)
    assert tableau_first["log"]["deal_available"] is True
    assert tableau_first["log"]["uncertainty"] == "unprobed-legal-fallback"


def test_unknown_probe_status_is_not_a_witness_or_a_lower_bound():
    state = _park_state()
    repeat = (0, 1, 1)
    fresh = (2, 1, 1)
    destination, _cost, _arrival = _destination(state, repeat, 0)
    seen = {pack_state(state).hex(): 0, destination: 0}
    outcome = _call(
        state,
        _selection(repeat),
        _order(repeat, fresh),
        seen,
        probed_status={str(fresh): "unknown"},
    )
    assert outcome["replacement"].actions == (fresh,)
    assert outcome["replacement"].used_witness is False
    assert outcome["replacement"].admissible_bound is False
    assert outcome["replacement"].scoped_minimum is False
    assert outcome["log"]["uncertainty"] == "unknown-legal-fallback"
    assert outcome["log"]["proved_strategy"] is False
    assert str(fresh) in outcome["replacement"].unknown_ids


def test_unseen_zero_cost_parking_is_eligible_and_an_equal_return_is_a_repeat():
    state = _park_state()
    park = (0, 1, 1)
    other = (2, 1, 1)
    assert step_cost(state, park) == 0
    assert step_cost(state, other) == 0
    seen = {pack_state(state).hex(): 0}
    unseen = _call(state, _selection(park), _order(park, other), seen)
    assert unseen["log"]["triggered"] is False
    assert unseen["log"]["reason"] == "original-fallback-is-not-a-repeat"
    assert unseen["replacement"] is None
    park_dest, _cost, _arrival = _destination(state, park, 0)
    seen[park_dest] = 0
    other_dest, _cost, _arrival = _destination(state, other, 0)
    seen[other_dest] = 0
    later = (4, 1, 1)
    equal = _call(state, _selection(park), _order(park, other, later), seen)
    dispositions = [row["disposition"] for row in equal["log"]["checked"]]
    assert dispositions[:2] == ["repeat", "repeat"]
    assert equal["replacement"].actions == (later,)
    assert step_cost(state, later) == 0


def test_a_cheaper_arrival_is_eligible():
    state = _park_state()
    repeat = (0, 1, 1)
    cheaper = (2, 1, 1)
    repeat_dest, _cost, _arrival = _destination(state, repeat, 0)
    cheaper_dest, cost, _arrival = _destination(state, cheaper, 0)
    assert cost == 0
    seen = {pack_state(state).hex(): 0, repeat_dest: 0, cheaper_dest: 5}
    outcome = _call(state, _selection(repeat), _order(repeat, cheaper), seen)
    assert outcome["replacement"].actions == (cheaper,)
    selected = outcome["log"]["checked"][-1]
    assert selected["disposition"] == "selected"
    assert selected["arrival_g"] == 0
    assert selected["earlier_g"] == 5
    assert selected["fresh"] is True


def test_no_fresh_successor_is_an_episode_local_stop_and_caps_bind_first(monkeypatch):
    state = _park_state()
    actions = [(0, 1, 1), (2, 1, 1), (4, 1, 1)]
    seen = {pack_state(state).hex(): 0}
    for action in actions:
        destination, _cost, _arrival = _destination(state, action, 0)
        seen[destination] = 0
    before = _faces(state)
    none = _call(state, _selection(actions[0]), _order(*actions), seen)
    assert none["replacement"] is None
    assert none["halt"] == "no-fresh-successor"
    assert "episode-local" in none["detail"]
    assert "not global exhaustion" in none["detail"]
    assert "not an unsolvable" in none["detail"]
    assert _faces(state) == before
    assert none["preview_count"] == len(actions)

    expired = _call(
        state,
        _selection(actions[0]),
        _order(*actions),
        seen,
        budget=_budget(wall_s=1.0),
        started=perf_counter() - 5.0,
    )
    assert expired["halt"] == "time"
    assert expired["replacement"] is None
    assert expired["log"]["triggered"] is False
    assert expired["preview_count"] == 0

    at_cap = _call(
        state,
        _selection(actions[0]),
        _order(*actions),
        {pack_state(state).hex(): 0},
        budget=_budget(additional_paid=0),
        paid=0,
    )
    assert at_cap["halt"] == "paid-moves"
    assert at_cap["replacement"] is None

    real_cost = step_cost
    real_apply = apply_action
    expensive = (2, 1, 1)
    affordable = (4, 1, 1)

    def priced(current, action, **kwargs):
        if tuple(action) == expensive:
            return 5
        return real_cost(current, action)

    def applied(current, action, **kwargs):
        if tuple(action) == expensive:
            real_apply(current, action)
            return 5
        return real_apply(current, action)

    monkeypatch.setattr("spider.practical_witness_play.step_cost", priced)
    monkeypatch.setattr("spider.practical_witness_play.apply_action", applied)
    repeat = (0, 1, 1)
    destination, _cost, _arrival = _destination(state, repeat, 0)
    limited = _call(
        state,
        _selection(repeat),
        _order(repeat, expensive, affordable),
        {pack_state(state).hex(): 0, destination: 0},
        budget=_budget(additional_paid=1),
    )
    assert [row["disposition"] for row in limited["log"]["checked"]] == [
        "repeat",
        "unaffordable",
        "selected",
    ]
    assert limited["replacement"].actions == (affordable,)


def test_recorded_warm_stops_escape_without_probing(monkeypatch):
    monkeypatch.setattr(
        "spider.practical_witness_play.run_search",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("probe")),
    )
    saved = json.loads(TRACE.read_text(encoding="utf-8"))
    episodes = {
        episode["root_id"]: episode
        for episode in saved["episodes"]
        if episode["mode"] == "witness" and episode["root_id"] != "opening"
    }
    assert set(episodes) == {"after-deal-1", "after-deal-2", "after-deal-3"}
    for root_id, episode in episodes.items():
        start = episode["progress"][0]
        root = FrozenRoot(
            root_id=root_id,
            deal_ordinal=int(episode["deal_ordinal"]),
            prefix_actions=tuple(
                ("deal",) if action == ["deal"] else tuple(action)
                for action in episode["imported_prefix"]
            ),
            corrected_cost=int(episode["imported_cost"]),
            pack_hex=episode["source_pack"],
            stock=int(start["stock"]),
            foundations=int(start["foundations"]),
            hidden=int(start["hidden"]),
            duplicate_of=None,
            counts_as_evidence=True,
        )
        state = materialize_root(root)
        seen = {}
        arrive(seen, pack_state(state).hex(), 0, initial=True)
        paid = 0
        for step in episode["actions"]:
            action = ("deal",) if step["action"] == ["deal"] else tuple(step["action"])
            paid += int(step_cost(state, action))
            apply_action(state, action)
            arrive(seen, pack_state(state).hex(), paid)
        assert paid == episode["paid"]
        last = episode["decision_records"][-1]
        assert last["selection"]["used_witness"] is False
        assert len(last["selection"]["actions"]) == 1
        original = tuple(last["selection"]["actions"][0])
        _legal, pick, _elapsed, status = admit_options(state)
        assert status == "matched"
        ordered = tuple((option.option_id, tuple(option.actions[0])) for option in pick.chosen)
        assert [item[0] for item in ordered] == last["ordered_ids"]
        assert ordered[0][0] == str(original)
        assert len(last["unprobed_ids"]) > 0
        before_seen = dict(seen)
        before_pack = pack_state(state).hex()
        outcome = _call(
            state,
            _selection(original),
            ordered,
            seen,
            probed_status={
                item["option_id"]: item["status"] for item in last["candidates"]
            },
            unprobed_ids=tuple(last["unprobed_ids"]),
            paid=paid,
        )
        assert outcome["log"]["triggered"] is True
        assert outcome["halt"] is None
        replacement = outcome["replacement"]
        assert replacement is not None
        assert replacement.option_id != str(original)
        assert replacement.used_witness is False
        assert replacement.admissible_bound is False
        assert replacement.optimality_claim is False
        assert replacement.full_game_optimum is False
        assert outcome["log"]["proved_strategy"] is False
        assert outcome["log"]["deal_available"] is True
        assert outcome["log"]["preview_identities"] == 0
        destination, cost, arrival = _destination(state, replacement.actions[0], paid)
        assert destination not in seen or arrival < seen[destination]
        assert cost >= 0
        checked = outcome["log"]["checked"]
        assert checked[0]["option_id"] == str(original)
        assert checked[0]["disposition"] == "repeat"
        assert checked[-1]["disposition"] == "selected"
        assert seen == before_seen
        assert pack_state(state).hex() == before_pack
        assert original in {tuple(action) for action in all_legal_actions(state)}
        _final, _paid, primitives, played, stop, _detail = execute_plan(
            state,
            (original,),
            _budget(),
            dict(seen),
            paid=paid,
            primitives=0,
            started=perf_counter(),
            expected_cost=int(step_cost(state, original)),
            predicate=None,
            require_predicate=False,
        )
        assert stop == "repeated-state"
        assert primitives == 0
        assert played == []


def test_escape_benefit_rule_is_separate_from_recovery_and_the_runner_stays_gated():
    same = Endpoint(0, 12, False, 40)
    revealed = Endpoint(0, 10, False, 30)
    assert escape_label(same, same) == "tie"
    assert escape_label(same, revealed) == "improved"
    assert escape_label(revealed, same) == "regressed"
    assert judge_escape(["tie", "improved", "improved", "tie"], checks_ok=True) == (
        "PROGRESS_AFTER_ESCAPE"
    )
    assert judge_escape(["tie", "improved", "tie", "tie"], checks_ok=True) == (
        "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT"
    )
    assert judge_escape(["regressed", "improved", "improved", "tie"], checks_ok=True) == (
        "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT"
    )
    assert judge_escape(["tie", "improved", "tradeoff", "improved"], checks_ok=True) == (
        "ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT"
    )
    assert judge_escape(["tie", "improved", "improved", "tie"], checks_ok=False) == (
        "CORRECTNESS_BLOCKER"
    )
    assert "default cycle guard" in recommendation("PROGRESS_AFTER_ESCAPE")
    assert "default cycle guard" in recommendation("ESCAPE_ONLY_NO_CLEAR_GAME_BENEFIT")
    spec = policy_specification()
    assert spec["cycle_escape"]["default_enabled"] is False
    assert spec["cycle_escape"]["official_opt_in"] is True
    with pytest.raises(RuntimeError, match="official"):
        run_cycle_escape_trial(None, confirm_official=False)
    text = Path(run_episode.__code__.co_filename).read_text(encoding="utf-8")
    assert "canonical.moves" not in text
    assert "practical_witness_play_pilot" not in text
    assert "4925153_autonomous" not in text


def test_pre_run_manifest_locks_the_four_roots_and_the_control_hash():
    document = json.loads(SPEC.read_text(encoding="utf-8"))
    assert "outcome" not in document
    assert document["opt_in_cycle_escape"] is True
    assert document["default_cycle_escape"] is False
    assert document["official_mode"] == "witness"
    assert document["runs_per_root"] == 1
    assert document["parent_sha"] == "6a469a5aa10058423d98be57fecd057071023774"
    assert document["control_verdict_left_unchanged"] == "NO_CLEAR_BENEFIT"
    # Historical pin stays the CRLF digest recorded in the spec. LF and CRLF
    # bytes of the same control JSON both validate. The file is not rewritten.
    control_sha256_crlf = "CB3679168F2E90F3D24D870AA060300CD5B8D6292335B0C491460B7ECEA39BB6"
    control_sha256_lf = "E736A8A37828554A4C5064FC58C147DA36F1699D73A3BE4222AC37C11D76351F"
    raw_control = CONTROL.read_bytes()
    raw_hash = hashlib.sha256(raw_control).hexdigest().upper()
    assert raw_hash in {control_sha256_crlf, control_sha256_lf}
    assert document["control_sha256"] == control_sha256_crlf
    lf_control = raw_control.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    crlf_control = lf_control.replace(b"\n", b"\r\n")
    assert hashlib.sha256(lf_control).hexdigest().upper() == control_sha256_lf
    assert hashlib.sha256(crlf_control).hexdigest().upper() == control_sha256_crlf
    assert document["accepted_hashes"] == {
        "deal_lf": DEAL_SHA256_LF,
        "deal_crlf": DEAL_SHA256_CRLF,
        "canonical_lf": CANONICAL_SHA256_LF,
        "canonical_crlf": CANONICAL_SHA256_CRLF,
    }
    policy = policy_specification()
    assert document["probe"] == policy["probe"]
    assert document["episode"] == policy["episode"]
    assert document["cycle_escape"] == policy["cycle_escape"]
    assert document["metric"]["escape_progress"] == policy["metric"]["escape_progress"]
    assert document["metric"]["escape_benefit"] == policy["metric"]["escape_benefit"]
    manifest = prepare_manifest()
    assert [root["root_id"] for root in document["roots"]] == [
        root.root_id for root in manifest.roots
    ]
    for recorded, root in zip(document["roots"], manifest.roots):
        assert recorded["pack_hex"] == root.pack_hex
        assert recorded["corrected_cost"] == root.corrected_cost
        assert recorded["prefix_length"] == len(root.prefix_actions)
        assert recorded["stock"] == root.stock
        assert recorded["hidden"] == root.hidden
        assert recorded["foundations"] == root.foundations
