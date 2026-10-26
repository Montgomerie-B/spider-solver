"""v0.125 suit-completion ordering. Synthetic boards and tiny searches.

No 40-second or 80,000-state benchmark belongs in this file.
"""

from __future__ import annotations

import inspect
import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.global_search_experiment import (
    SCHEMA,
    SUIT_SCHEMA,
    search_suit_ordered,
    solve_then_optimise,
    suit_lane_keys,
)
from spider.human_strategy import SCHEMA_VERSION
from spider.human_strategy.anchored import AnchoredRefused, optimise_anchored
from spider.human_strategy.incumbent import IncumbentRejected, proof_prune, verify_complete_solution
from spider.metrics import parse_moves_file
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import all_legal_actions, apply_action, opening_from_deal, step_cost
from spider.search_kernel import SearchLimits, run_search
from spider.state_identity import canonical_state_key
from spider.suit_completion import (
    ACE_BONUS,
    JOIN_BONUS,
    KING_BONUS,
    LENGTH_WEIGHT,
    PENALTY_ABSENT,
    PENALTY_EXPOSED,
    PENALTY_FACE_DOWN,
    PENALTY_STOCK,
    AdviceCache,
    opening_from_seed,
    order_with_advice,
    suit_completion_detail,
)
from spider.whole_game_anytime import LANES, lane_keys
from spider.counterfactual.boundaries import parse_canonical

DEAL = ROOT / "deals" / "4925153.txt"
G83 = ROOT / "tests" / "fixtures" / "g83_4925153_actions.json"
AUTONOMOUS_185 = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_172 = ROOT / "solutions" / "4925153_canonical.moves"


def _opening() -> SpiderState:
    return opening_from_deal(DEAL)


def _columns(specs) -> SpiderState:
    columns = [Column([], []) for _ in range(10)]
    for index, (down, up) in enumerate(specs):
        columns[index] = Column(list(down), list(up))
    return SpiderState(columns, [])


def _run(suit: str, high: int, low: int) -> list:
    return [Card(suit, rank) for rank in range(high, low - 1, -1)]


def _cycle_board() -> SpiderState:
    columns = [Column([], [Card("s", 13)]), Column([], [])]
    for _ in range(8):
        columns.append(Column([], [Card("h", 1)]))
    return SpiderState(columns, [Card("d", (index % 13) + 1) for index in range(10)])


def test_complete_sequence_scores_one_foundation_unit():
    state = _columns([([], _run("h", 13, 1))])
    detail = suit_completion_detail(state)
    assert detail.by_suit["h"] == 13 * LENGTH_WEIGHT + KING_BONUS + ACE_BONUS
    assert detail.by_suit["h"] == 1630
    assert detail.complete_exposed == 1
    assert detail.score == 1630


def test_incomplete_king_run_beats_short_bonds():
    long_run = _columns([([], _run("h", 13, 6))])
    short = _columns(
        [
            ([], _run("h", 13, 12)),
            ([], _run("h", 11, 10)),
            ([], _run("h", 9, 8)),
        ]
    )
    long_score = suit_completion_detail(long_run).by_suit["h"]
    short_score = suit_completion_detail(short).by_suit["h"]
    assert long_score > short_score
    assert suit_completion_detail(long_run).best_length["h"] == 8
    assert suit_completion_detail(short).best_length["h"] == 2


def test_missing_rank_penalties_are_ordered():
    def board(ace_down, ace_up, ace_stock=()):
        state = _columns(
            [
                ([], _run("h", 13, 3)),
                (list(ace_down), list(ace_up)),
                ([Card("h", 2)], []),
            ]
        )
        state.stock = list(ace_stock)
        return suit_completion_detail(state).by_suit["h"]

    absent = board([], [])
    buried = board([Card("h", 1)], [])
    stocked = board([], [], [Card("h", 1)])
    exposed = board([], [Card("h", 1)])
    assert absent == 11 * LENGTH_WEIGHT + KING_BONUS - PENALTY_ABSENT - PENALTY_FACE_DOWN
    assert buried - absent == PENALTY_ABSENT - PENALTY_FACE_DOWN
    assert buried - stocked == PENALTY_STOCK - PENALTY_FACE_DOWN
    assert exposed - buried == PENALTY_FACE_DOWN - PENALTY_EXPOSED
    assert exposed > buried > stocked > absent


def test_accessible_run_outranks_the_same_run_when_blocked():
    accessible = _columns(
        [
            ([], _run("h", 13, 6)),
            ([], [Card("h", 5)]),
            ([], [Card("h", 4)]),
            ([], [Card("h", 3)]),
            ([], [Card("h", 2)]),
            ([], [Card("h", 1)]),
        ]
    )
    blocked = _columns(
        [
            ([], _run("h", 13, 6)),
            ([Card("h", 5)], []),
            ([Card("h", 4)], []),
            ([Card("h", 3)], []),
            ([Card("h", 2)], []),
            ([Card("h", 1)], []),
        ]
    )
    buried = _columns([([], _run("h", 13, 6) + [Card("s", 13)])])
    access = suit_completion_detail(accessible)
    block = suit_completion_detail(blocked)
    cover = suit_completion_detail(buried)
    assert access.by_suit["h"] > block.by_suit["h"]
    assert block.by_suit["h"] > cover.by_suit["h"]
    assert access.near_accessible >= 1 or access.best_length["h"] == 8
    assert block.near_blocked == 0 or block.best_length["h"] == 8
    assert cover.runs[0][2] is False


def test_two_copies_do_not_build_two_scores_and_stay_distinct_states():
    sequence = _run("h", 13, 1)
    doubled = _columns([([], sequence), ([], list(sequence))])
    detail = suit_completion_detail(doubled)
    assert detail.complete_exposed == 2
    assert detail.by_suit["h"] == 1630
    columns = [Column([], []) for _ in range(10)]
    columns[0] = Column([], [Card("h", 13)])
    columns[2] = Column([], [Card("h", 13)])
    columns[3] = Column([], [Card("s", 5)])
    state = SpiderState(columns, [Card("d", 1)] * 10)
    left = state.clone()
    right = state.clone()
    apply_action(left, (0, 1, 1))
    apply_action(right, (2, 1, 1))
    assert canonical_state_key(left) != canonical_state_key(right)
    assert pack_state(left) != pack_state(right)


def test_off_suit_stack_is_not_a_same_suit_run():
    state = _columns([([], [Card("h", 12), Card("s", 13)])])
    detail = suit_completion_detail(state)
    assert not any(suit == "h" and length >= 2 for suit, length, _exposed in detail.runs)
    assert detail.by_suit["h"] == 0


def test_duplicate_missing_rank_uses_the_better_copy_once():
    def score(ace_a, ace_b, ace_a_up=False):
        first = ([], [Card("h", 1)]) if ace_a_up else (ace_a, [])
        state = _columns(
            [
                ([], _run("h", 13, 3)),
                first,
                (ace_b, []),
                ([Card("h", 2)], []),
            ]
        )
        return suit_completion_detail(state).by_suit["h"]

    one_exposed = score([], [Card("h", 1)], ace_a_up=True)
    both_buried = score([Card("h", 1)], [Card("h", 1)])
    assert one_exposed - both_buried == PENALTY_FACE_DOWN - PENALTY_EXPOSED
    assert one_exposed - both_buried != 2 * (PENALTY_FACE_DOWN - PENALTY_EXPOSED)


def test_stock_empty_tableau_has_no_stock_penalty():
    empty = _columns([([], _run("h", 13, 3)), ([], [Card("h", 1)]), ([Card("h", 2)], [])])
    assert empty.stock == []
    stocked = empty.clone()
    stocked.columns[1] = Column([], [])
    stocked.stock = [Card("h", 1)]
    empty_score = suit_completion_detail(empty).by_suit["h"]
    stock_score = suit_completion_detail(stocked).by_suit["h"]
    assert empty_score - stock_score == PENALTY_STOCK - PENALTY_EXPOSED
    assert suit_completion_detail(empty).score >= empty_score


def test_score_ignores_foundation_count_before_the_first_removal():
    state = _columns([([], _run("h", 13, 6))])
    before = suit_completion_detail(state)
    assert state.foundations == []
    keyed = suit_lane_keys(state, 0)
    assert keyed["foundation"][0] == 0
    state.foundations.append(_run("s", 13, 1))
    after = suit_completion_detail(state)
    assert before.by_suit == after.by_suit
    assert suit_lane_keys(state, 0)["foundation"][0] == -1
    assert suit_lane_keys(state, 0)["foundation"][1] == keyed["foundation"][1]


def test_removed_sequence_leaves_the_tableau_score():
    state = _columns([([], _run("h", 13, 1))])
    assert suit_completion_detail(state).by_suit["h"] == 1630
    assert state.check_seq(0) is True
    assert len(state.foundations) == 1
    detail = suit_completion_detail(state)
    assert detail.by_suit["h"] == 0
    assert detail.complete_exposed == 0
    assert state.columns[0].face_up == []


def test_only_the_foundation_lane_changes():
    state = _opening()
    original = lane_keys(state, 4)
    updated = suit_lane_keys(state, 4)
    assert tuple(updated) == LANES
    assert "strategy" not in updated
    for name in LANES:
        if name == "foundation":
            continue
        assert updated[name] == original[name]
    foundations, face_down, rows, cost = original["foundation"]
    detail = suit_completion_detail(state)
    assert updated["foundation"] == (foundations, -detail.score, face_down, rows, cost)


def test_every_legal_successor_is_generated():
    state = _opening()
    legal = all_legal_actions(state)
    result = run_search(
        [{"g": 0, "ordered_digest": pack_state(state).hex()}],
        limits=SearchLimits(max_unique=400, time_limit_s=5.0, rss_abort_mb=1024),
        identity_fn=pack_whole_game_identity,
        store_fn=pack_state,
        unpack_fn=unpack_state,
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
        actions_fn=all_legal_actions,
        is_terminal=lambda _board: False,
    )
    children = [node.action for node in result.nodes if node.parent == 0]
    assert set(children) == set(legal)
    assert ("deal",) in children
    searched = search_suit_ordered(
        state.clone(),
        time_limit_s=5.0,
        max_unique=400,
        rss_abort_mb=1024,
        cost_ceiling=None,
    )
    assert searched.heuristic_exclusions == 0
    assert searched.generated >= len(legal)
    assert searched.stock_deals >= 1
    payload = searched.to_dict()
    assert payload["legal_actions_dropped"] == 0
    assert payload["proximity_prunes"] == 0
    assert set(payload["lane_pops"]) == set(LANES)
    json.dumps(payload)


def test_advice_reorders_without_dropping():
    state = _opening()
    legal = all_legal_actions(state)
    deal = ("deal",)
    ordered = order_with_advice(legal, deal)
    assert ordered[0] == deal
    assert ordered[1:] == [action for action in legal if action != deal]
    assert set(ordered) == set(legal)
    assert order_with_advice(legal, None) == list(legal)
    assert order_with_advice(legal, (0, 0, 99)) == list(legal)


def test_failed_advice_still_explores_every_legal_move():
    state = _opening()
    legal = all_legal_actions(state)

    def nothing(_state):
        return None

    failed = search_suit_ordered(
        state,
        time_limit_s=5.0,
        max_unique=24,
        rss_abort_mb=1024,
        cost_ceiling=None,
        advice_fn=nothing,
        advice_budget=4,
    )
    plain = search_suit_ordered(
        state.clone(),
        time_limit_s=5.0,
        max_unique=24,
        rss_abort_mb=1024,
        cost_ceiling=None,
    )
    assert failed.heuristic_exclusions == 0
    assert failed.generated == plain.generated
    assert failed.census["advice_calls"] >= 1
    assert failed.stock_deals == plain.stock_deals
    assert failed.generated >= 1
    cache = AdviceCache(1)
    assert cache.suggest(state, nothing) is None
    assert cache.suggest(state.clone(), nothing) is None
    assert cache.calls == 1
    assert cache.hits == 1
    assert ("deal",) in legal


def test_corrected_costs_and_zero_cost_transfers_remain():
    state = _cycle_board()
    assert step_cost(state, (0, 1, 1)) == 0
    assert step_cost(state, ("deal",)) == 1
    moved = state.clone()
    assert apply_action(moved, (0, 1, 1)) == 0
    result = search_suit_ordered(
        state,
        time_limit_s=2.0,
        max_unique=40,
        rss_abort_mb=1024,
        cost_ceiling=None,
    )
    assert result.duplicate_skips > 0
    assert result.unique <= 40
    assert result.solved is False


def test_cheaper_ancestry_still_dominates():
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
        lane_names=LANES,
        lane_keys_fn=suit_lane_keys,
        actions_fn=all_legal_actions,
        is_terminal=lambda _board: False,
    )
    roots = [node for node in result.nodes if node.parent < 0]
    assert len(roots) == 1
    assert roots[0].g == 4


def test_proximity_does_not_prune():
    opening = _opening()
    proximity = suit_completion_detail(opening).score
    assert proof_prune(0, proximity, 50) is True
    assert proof_prune(0, proximity, None) is False
    cold = search_suit_ordered(
        opening,
        time_limit_s=2.0,
        max_unique=20,
        rss_abort_mb=1024,
        cost_ceiling=300,
    )
    assert cold.lower_bound_prunes == 0
    assert cold.to_dict()["proximity_prunes"] == 0
    source = inspect.getsource(search_suit_ordered)
    assert "lower_bound_fn=bound" in source
    assert "admissible_remaining" in source
    optimised = search_suit_ordered(
        opening.clone(),
        time_limit_s=2.0,
        max_unique=20,
        rss_abort_mb=1024,
        mode="optimise",
        incumbent_cost=1,
        cost_ceiling=None,
    )
    assert optimised.ceiling_kind == "admissible_incumbent"
    assert optimised.lower_bound_prunes >= 1
    assert optimised.expanded == 0
    assert optimised.imported_incumbent is True


def test_suit_ordering_is_deterministic():
    opening = _opening()
    kwargs = dict(time_limit_s=5.0, max_unique=12, rss_abort_mb=1024, seed=0, cost_ceiling=None)
    first = search_suit_ordered(opening, **kwargs).to_dict()
    second = search_suit_ordered(opening.clone(), **kwargs).to_dict()

    def strip_elapsed(value):
        if isinstance(value, dict):
            value.pop("elapsed_s", None)
            for item in value.values():
                strip_elapsed(item)
        elif isinstance(value, list):
            for item in value:
                strip_elapsed(item)

    for payload in (first, second):
        for key in ("elapsed_s", "cpu_s", "peak_rss_mb"):
            payload.pop(key, None)
        strip_elapsed(payload)
    assert first == second
    assert first["stop_reason"] == "unique limit"
    assert first["schema"] == SUIT_SCHEMA


def test_cold_search_does_not_name_stored_routes():
    source = inspect.getsource(search_suit_ordered)
    factory = inspect.getsource(opening_from_seed)
    heuristic = inspect.getsource(suit_completion_detail)
    for banned in (
        "4925153_autonomous_185",
        "4925153_canonical",
        "g83_4925153",
        "experiment_c_policy",
    ):
        assert banned not in source
        assert banned not in factory
        assert banned not in heuristic
    assert "4925153" not in heuristic
    with pytest.raises(ValueError, match="cold search refuses"):
        search_suit_ordered(
            _opening(),
            time_limit_s=0.5,
            max_unique=4,
            rss_abort_mb=512,
            incumbent_cost=172,
        )
    document = solve_then_optimise(
        _opening(),
        time_limit_s=0.3,
        max_unique=6,
        rss_abort_mb=512,
    )
    assert document["stage2"] is None
    assert document["imported_substitute"] is False
    assert document["known_prefix"] is False
    assert document["provenance"] == "unsuccessful_bounded_search"


def test_eight_foundation_replay_and_partial_rejection():
    opening = _opening()
    autonomous = verify_complete_solution(
        opening,
        parse_moves_file(AUTONOMOUS_185),
        expected_cost=185,
        source="imported",
        source_id="autonomous-185",
    )
    human = verify_complete_solution(
        opening,
        parse_moves_file(CANONICAL_172),
        expected_cost=172,
        source="imported",
    )
    assert autonomous.solved and autonomous.foundations == 8 and autonomous.cost == 185
    assert human.solved and human.foundations == 8 and human.cost == 172
    assert autonomous.source == "imported"
    g83 = json.loads(G83.read_text(encoding="utf-8"))
    with pytest.raises(IncumbentRejected):
        verify_complete_solution(
            opening,
            [parse_canonical(item) for item in g83["actions"]],
            source="g83-reference",
        )


def test_incumbent_and_anchored_regressions_stay_intact():
    opening = _opening()
    with pytest.raises(AnchoredRefused):
        optimise_anchored(opening, [], mode="cold")
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
    controller = (ROOT / "src" / "spider" / "human_strategy" / "controller.py").read_text(encoding="utf-8")
    assert "suit_completion" not in controller
    assert "global_search_experiment" not in controller
    package = ROOT / "src" / "spider" / "human_strategy"
    for path in package.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "suit_completion" not in text
        assert "global_search_experiment" not in text
    assert SCHEMA == "spider-global-search-0.124"
    assert SCHEMA_VERSION == "spider-human-strategy-0.123"
    assert SUIT_SCHEMA == "spider-global-search-0.125"


def test_seeded_second_deal_is_a_full_two_deck_opening():
    first = opening_from_seed(125)
    second = opening_from_seed(125)
    other = opening_from_seed(126)
    assert pack_state(first) == pack_state(second)
    assert pack_state(first) != pack_state(other)
    assert pack_state(first) != pack_state(_opening())
    assert len(first.stock) == 50
    assert suit_completion_detail(first).score == suit_completion_detail(second).score


def test_proximity_scan_stays_inexpensive():
    state = _opening()
    started = time.perf_counter()
    total = 0
    for _ in range(200):
        total += suit_completion_detail(state).score
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0
    assert total == 200 * suit_completion_detail(state).score


def test_join_bonus_requires_a_same_suit_legal_step():
    joined = _columns(
        [
            ([], _run("h", 13, 6)),
            ([], [Card("h", 5)]),
        ]
    )
    offsuit = _columns(
        [
            ([], _run("h", 13, 6)),
            ([], [Card("s", 5)]),
        ]
    )
    assert suit_completion_detail(joined).by_suit["h"] - suit_completion_detail(
        offsuit
    ).by_suit["h"] == (PENALTY_ABSENT - PENALTY_EXPOSED) + JOIN_BONUS
