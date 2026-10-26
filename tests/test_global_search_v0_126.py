"""v0.126 checkpoint continuation. Synthetic boards and the saved g139 prefix.

The 80,000-state continuation is not part of this file.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.assembly_lower_bound import assembly_bound_detail
from spider.cards import Card
from spider.counterfactual.boundaries import parse_canonical
from spider.engine import Column, SpiderState
from spider.global_search_experiment import (
    COMPLETION_SCHEMA,
    SUIT_SCHEMA,
    replay_cost,
    search_original_kernel,
    search_suit_ordered,
    suit_lane_keys,
)
from spider.human_strategy.anchored import optimise_anchored
from spider.human_strategy.evaluation import admissible_remaining
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.metrics import format_action, parse_moves_file
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, apply_action, face_down_count, opening_from_deal, step_cost
from spider.search_kernel import SearchLimits, run_search
from spider.suit_completion import suit_completion_score
from spider.whole_game_anytime import LANES, lane_keys

DEAL = ROOT / "deals" / "4925153.txt"
PREFIX = ROOT / "tests" / "fixtures" / "g139_v0125_partial.json"
SOURCE = ROOT / "artifacts" / "global_search" / "v0_125" / "suit_80000.json"
AUTONOMOUS_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_172 = ROOT / "solutions" / "4925153_canonical.moves"

# face_down is deepest first. face_up is bottom to top.
EXPECTED_COLUMNS = (
    ("10c Qd 6c 8s", "5c 4s 3h"),
    ("5h", "9h 8h 7h 6h"),
    ("", "Kc Qc Jc"),
    ("Ac 2h Kd", "10h 7s"),
    ("", "Ks Qs Js 10s 9s"),
    ("", "9c 8c 7c"),
    ("", "Jd 10d 9d 8d 7d 6d 5d 4d 3d 2d Ad"),
    ("", "Kh Qh Jh"),
    ("", "4c 3c 2c Ah"),
    ("", "6s 5s 4h 3s 2s As"),
)


def _opening() -> SpiderState:
    return opening_from_deal(DEAL)


def _prefix():
    document = json.loads(PREFIX.read_text(encoding="utf-8"))
    return [parse_canonical(item) for item in document["actions"]], document


def _cards(text: str):
    return [Card.parse(token) for token in text.split()] if text.strip() else []


def _g139():
    actions, _document = _prefix()
    state, cost = replay_cost(_opening(), actions)
    return state, cost, actions


def _cycle_board() -> SpiderState:
    columns = [Column([], [Card("s", 13)]), Column([], [])]
    for _ in range(8):
        columns.append(Column([], [Card("h", 1)]))
    return SpiderState(columns, [Card("d", (index % 13) + 1) for index in range(10)])


def _strip_time(value):
    if isinstance(value, dict):
        value.pop("elapsed_s", None)
        for item in value.values():
            _strip_time(item)
    elif isinstance(value, list):
        for item in value:
            _strip_time(item)


def test_g139_prefix_replays_and_matches_the_exported_artifact():
    actions, document = _prefix()
    assert document["deal"] == "4925153"
    assert document["source_sha256"] == "bc0954851d2e8b37bfcdf3e10918b09a163b52898f2c8dc807663c1629ae1a36"
    assert len(actions) == 139
    if SOURCE.is_file():
        saved = json.loads(SOURCE.read_text(encoding="utf-8"))
        assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == document["source_sha256"]
        assert saved["result"]["best_partial"]["actions"] == document["actions"]
        assert saved["result"]["provenance"] == "partial_legal_search"
        assert saved["result"]["solved"] is False
        assert saved["result"]["known_prefix"] is False
    state, cost = replay_cost(_opening(), actions)
    assert cost == 139
    assert [pile[0].suit for pile in state.foundations] == ["s", "c", "d", "h"]
    assert len(state.foundations) == 4
    assert face_down_count(state) == 8
    assert state.stock == []
    assert state.is_solved() is False
    marks = []
    cursor = _opening()
    spent = 0
    for action in actions:
        spent += apply_action(cursor, action)
        if len(cursor.foundations) > len(marks):
            marks.append((cursor.foundations[-1][0].suit, spent, face_down_count(cursor), len(cursor.stock)))
    assert marks == [("s", 76, 13, 0), ("c", 84, 13, 0), ("d", 87, 12, 0), ("h", 133, 9, 0)]
    assert pack_state(state).hex() == pack_state(cursor).hex()


def test_g139_physical_state_and_checkpoint_id():
    state, cost, _actions = _g139()
    assert cost == 139
    for column, (down, up) in zip(state.columns, EXPECTED_COLUMNS):
        assert [str(card) for card in column.face_down] == down.split()
        assert [str(card) for card in column.face_up] == up.split()
    assert [index + 1 for index, column in enumerate(state.columns) if column.is_empty()] == []
    checkpoint = pack_state(state).hex()
    restored = unpack_state(bytes.fromhex(checkpoint))
    assert pack_state(restored).hex() == checkpoint
    assert face_down_count(restored) == 8
    assert len(restored.foundations) == 4
    assert restored.stock == []


def test_g139_legal_successors_are_all_generated():
    state, _cost, actions = _g139()
    legal = all_legal_actions(state)
    assert len(legal) == 14
    assert ("deal",) not in legal
    assert all(step_cost(state, action) == 1 for action in legal)
    reveals = []
    for action in legal:
        src, _dst, k = action
        column = state.columns[src]
        if k == len(column.face_up) and column.face_down:
            reveals.append(action)
    assert reveals == []
    result = run_search(
        [{"g": 139, "ordered_digest": pack_state(state).hex()}],
        limits=SearchLimits(max_unique=16, time_limit_s=5.0, rss_abort_mb=1024, cost_ceiling=300),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
        actions_fn=all_legal_actions,
        is_terminal=lambda _board: False,
    )
    children = [node for node in result.nodes if node.parent == 0]
    assert set(node.action for node in children) == set(legal)
    assert {node.g for node in children} == {140}
    assert result.lower_bound_prunes == 0
    continued = search_suit_ordered(
        _opening(),
        time_limit_s=5.0,
        max_unique=16,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert continued.heuristic_exclusions == 0
    assert continued.to_dict()["legal_actions_dropped"] == 0
    assert continued.to_dict()["proximity_prunes"] == 0
    assert continued.generated >= len(legal)


def test_zero_cost_transfers_stay_available_in_a_continuation():
    board = _cycle_board()
    free = (0, 1, 1)
    assert step_cost(board, free) == 0
    continued = search_suit_ordered(
        board,
        time_limit_s=2.0,
        max_unique=12,
        rss_abort_mb=1024,
        cost_ceiling=None,
        prefix_actions=(free,),
    )
    assert continued.checkpoint_g == 0
    assert continued.replay_ok is True
    assert continued.replay_g == continued.best_partial["g"]
    assert continued.provenance == "checkpoint_continuation"
    parked, spent = replay_cost(board, [free])
    assert spent == 0
    assert step_cost(parked, (1, 0, 1)) == 0
    probed = run_search(
        [{"g": 0, "ordered_digest": pack_state(parked).hex()}],
        limits=SearchLimits(max_unique=8, time_limit_s=2.0, rss_abort_mb=1024),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
        actions_fn=all_legal_actions,
        is_terminal=lambda _board: False,
    )
    assert (1, 0, 1) in [node.action for node in probed.nodes if node.parent == 0]
    assert any(node.g == 0 and node.action == (1, 0, 1) for node in probed.nodes)


def test_remaining_suit_copies_are_not_double_counted():
    state, _cost, _actions = _g139()
    seen = {}
    for column in state.columns:
        for card in list(column.face_down) + list(column.face_up):
            seen[(card.suit, card.rank)] = seen.get((card.suit, card.rank), 0) + 1
    assert len(seen) == 52
    assert set(seen.values()) == {1}
    detail = assembly_bound_detail(state)
    assert detail["copies_remaining"] == {"s": 1, "h": 1, "d": 1, "c": 1}
    assert detail["h"] == 20
    diamonds = detail["by_suit"]["d"]["units"]
    assert [1, 11] in [[int(low), int(high)] for low, high in diamonds] or [11, 1] in [
        [int(a), int(b)] for a, b in diamonds
    ]


def test_prefix_plus_suffix_cost_is_absolute_and_replays_from_the_deal():
    _state, _cost, actions = _g139()
    continued = search_suit_ordered(
        _opening(),
        time_limit_s=5.0,
        max_unique=16,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert continued.replay_ok is True
    assert continued.solved is False
    assert continued.replay_g == continued.best_partial["g"]
    assert continued.replay_g >= 139
    assert continued.actions[:139] == tuple(actions)
    end, spent = replay_cost(_opening(), continued.actions)
    assert spent == continued.replay_g
    assert len(end.foundations) == continued.best_partial["foundations"]
    assert face_down_count(end) == continued.best_partial["face_down"]
    assert continued.provenance == "checkpoint_continuation"
    assert continued.schema == COMPLETION_SCHEMA
    payload = continued.to_dict()
    assert payload["search_kind"] == "checkpoint_continuation"
    assert payload["known_prefix"] is True
    assert payload["imported_substitute"] is False
    assert payload["provenance"] != "independent_cold_complete"


def test_checkpoint_discovery_is_not_labelled_as_a_cold_solve():
    _state, _cost, actions = _g139()
    with pytest.raises(IncumbentRejected):
        verify_complete_solution(_opening(), actions, source="g139-partial")
    cold = search_suit_ordered(
        _opening(),
        time_limit_s=2.0,
        max_unique=8,
        rss_abort_mb=1024,
        cost_ceiling=300,
    )
    assert cold.schema == SUIT_SCHEMA
    assert cold.known_prefix is False
    assert cold.to_dict()["known_prefix"] is False
    assert cold.provenance != "checkpoint_assisted_complete"
    source = inspect.getsource(search_suit_ordered)
    for banned in (
        "4925153_autonomous_185",
        "4925153_canonical",
        "g139_v0125_partial",
        "suit_80000",
        "g83_4925153",
    ):
        assert banned not in source
    with pytest.raises(ValueError, match="refuses an incumbent"):
        search_suit_ordered(
            _opening(),
            time_limit_s=0.5,
            max_unique=4,
            rss_abort_mb=512,
            prefix_actions=actions[:2],
            mode="optimise",
            incumbent_cost=172,
        )


def test_admissible_bound_does_not_reject_g139_and_does_not_prune_the_probe():
    state, cost, actions = _g139()
    assert cost == 139
    remaining = admissible_remaining(state)
    assert remaining == 20
    assert cost + remaining == 159
    assert proof_prune(139, 20, 172) is False
    assert proof_prune(139, 20, 185) is False
    assert proof_prune(139, 20, 159) is True
    continued = search_suit_ordered(
        _opening(),
        time_limit_s=3.0,
        max_unique=12,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert continued.lower_bound_prunes == 0
    assert continued.cost_ceiling == 300
    assert continued.ceiling_kind == "hard_path_cap"
    assert suit_completion_score(state) > remaining


def test_suit_proximity_does_not_drop_a_g139_successor():
    state, _cost, actions = _g139()
    legal = list(all_legal_actions(state))
    ordered_keys = suit_lane_keys(state, 139)
    assert ordered_keys["foundation"][1] == -suit_completion_score(state)
    continued = search_suit_ordered(
        _opening(),
        time_limit_s=5.0,
        max_unique=16,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert continued.heuristic_exclusions == 0
    assert continued.generated >= len(legal)
    assert set(continued.to_dict()["lane_pops"]) == set(LANES)


def test_partial_prefix_is_not_a_completed_game():
    _state, _cost, actions = _g139()
    continued = search_suit_ordered(
        _opening(),
        time_limit_s=2.0,
        max_unique=8,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert continued.solved is False
    assert continued.max_foundations == 4
    assert continued.to_dict()["incompleteness"] == "resource_limited"
    assert continued.provenance == "checkpoint_continuation"


def test_original_seven_lanes_and_v0125_suit_order_stay_selectable():
    state, _cost, _actions = _g139()
    original = lane_keys(state, 139)
    assert list(original) == list(LANES)
    assert original["foundation"] == (-4, 8, 0, 139)
    suited = suit_lane_keys(state, 139)
    foundations, proximity, face_down, rows, g = suited["foundation"]
    assert (foundations, face_down, rows, g) == (-4, 8, 0, 139)
    assert proximity == -suit_completion_score(state)
    for name in LANES:
        if name != "foundation":
            assert suited[name] == original[name]
    source = inspect.getsource(search_original_kernel)
    assert "search_whole_game" in source
    assert "suit_lane_keys" not in source


def test_continuation_ordering_is_deterministic_and_reports_the_limit():
    _state, _cost, actions = _g139()
    kwargs = dict(
        time_limit_s=5.0,
        max_unique=10,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    first = search_suit_ordered(_opening(), **kwargs).to_dict()
    second = search_suit_ordered(_opening(), **kwargs).to_dict()
    for payload in (first, second):
        for key in ("elapsed_s", "cpu_s", "peak_rss_mb"):
            payload.pop(key, None)
        _strip_time(payload)
    assert first == second
    assert first["stop_reason"] == "unique limit"
    assert first["unique"] == 10
    timed = search_suit_ordered(
        _opening(),
        time_limit_s=0.0,
        max_unique=100000,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions[:1],
    )
    assert timed.stop_reason == "time limit"
    assert timed.solved is False


def test_verified_incumbents_and_anchored_optimisation_stay_intact():
    before_185 = AUTONOMOUS_185.read_bytes()
    before_172 = CANONICAL_172.read_bytes()
    opening = _opening()
    _state, _cost, actions = _g139()
    search_suit_ordered(
        opening,
        time_limit_s=1.0,
        max_unique=6,
        rss_abort_mb=1024,
        cost_ceiling=300,
        prefix_actions=actions,
    )
    assert AUTONOMOUS_185.read_bytes() == before_185
    assert CANONICAL_172.read_bytes() == before_172
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
    assert autonomous.solved and autonomous.cost == 185 and autonomous.foundations == 8
    assert human.solved and human.cost == 172 and human.foundations == 8
    report = optimise_anchored(
        opening,
        parse_moves_file(CANONICAL_172),
        mode="anchored",
        source="imported",
        expected_cost=172,
        time_limit_s=2.0,
        window_time_s=0.4,
        max_windows=1,
        max_unique=10,
        rss_abort_mb=1024,
    )
    assert report.solved is True
    assert report.cumulative_g == 172
    assert report.improvements == []
    assert AUTONOMOUS_185.read_bytes() == before_185
    assert CANONICAL_172.read_bytes() == before_172
