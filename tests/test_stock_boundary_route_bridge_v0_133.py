"""v0.133 post-stock route-bridge contract.

These tests replay the known route and small fixtures. They do not run the
20,000-state, 45-second bridge.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.human_strategy.incumbent import proof_prune, verify_complete_solution
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import (
    pack_post_stock_symmetry_state,
    pack_state,
    permute_tableau_columns,
)
from spider.research_actions import all_legal_actions, is_deal, step_cost
from spider.stock_boundary_bridge import (
    CANONICAL_TOTAL,
    CEILING,
    EARLY_PREP,
    MAX_UNIQUE,
    RSS_ABORT_MB,
    TIME_LIMIT_S,
    accept_cost,
    bridge_action_order,
    load_verified_bridge_inputs,
    make_reference_stop,
    matching_stops,
    projected_full_cost,
    reference_table,
    replay_remapped_suffix,
    search_route_bridge,
)

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
AUTONOMOUS = ROOT / "solutions" / "4925153_autonomous_185.moves"
CANONICAL_SHA = "18338A08576AD24E9AF1F4BA2E7DB3E28768788DD511E823193B1937F3FEEF33"
AUTONOMOUS_SHA = "B19C56E957AC2666298A80118D54FF7FCA6C8114ED7D27590E2E98A017D4FB73"
DRIVER = ROOT / "tools" / "stock_boundary_route_bridge_v0_133.py"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "") -> SpiderState:
    cols = [Column([], _cards(columns.get(index, ""))) for index in range(10)]
    return SpiderState(cols, _cards(stock), [])


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _canonical():
    return parse_moves_file(CANONICAL)


def _loaded():
    return load_verified_bridge_inputs(_opening(), _canonical())


def _solved_stub() -> SpiderState:
    foundations = [[Card(suit, 1)] for suit in "shdc" for _copy in range(2)]
    return SpiderState([Column([], []) for _ in range(10)], [], foundations)


def _pair() -> SpiderState:
    return _state({0: "kh qh"})


def test_solution_files_and_canonical_ceiling_stay_put():
    assert _sha(CANONICAL) == CANONICAL_SHA
    assert _sha(AUTONOMOUS) == AUTONOMOUS_SHA
    verified = verify_complete_solution(
        _opening(),
        _canonical(),
        expected_cost=CANONICAL_TOTAL,
        source="canonical",
        source_id="4925153",
    )
    assert verified.cost == 172
    assert verified.foundations == 8
    assert accept_cost(171)
    assert not accept_cost(verified.cost)
    assert not accept_cost(172)


def test_early_candidate_and_reference_suffix_replay():
    early, table, targets, checkpoints = _loaded()
    assert early.g == 142
    assert early.h == 24
    assert early.f == 166
    assert early.face_down == 3
    assert early.bonds == 48
    assert early.foundations == 2
    assert early.same_suit_landings == 4
    assert early.prep_costs == (0, 1, 1, 1)
    assert early.checkpoint_140_g == 139
    assert early.checkpoint_140_stock == 10
    assert early.checkpoint_140_empty == 2
    assert early.post_sd5_g == 150
    assert early.post_sd5_h == 18
    assert early.suffix_len == 22
    assert early.suffix_cost == 22
    assert early.already_on_reference is False
    assert not early.state.stock
    prepared = checkpoints[140].state
    assert step_cost(prepared, EARLY_PREP[0]) == 0
    assert [stop.index for stop in table.stops] == list(range(152, 175))
    assert [stop.index for stop in targets] == [152, 160, 170, 171, 172, 173, 174]
    assert all(stop.suffix_cost == 172 - stop.g for stop in table.stops)
    assert not any(is_deal(action) for stop in table.stops for action in stop.suffix)
    identity = replay_remapped_suffix(table.stops[0].state, table.stops[0].state, table.stops[0].suffix)
    assert identity.ok
    assert identity.cost == 22
    assert identity.mapping == tuple(range(10))
    assert matching_stops(table, early.state) == []


def test_permuted_suffix_replays_and_the_unmapped_suffix_does_not():
    _early, table, targets, _checkpoints = _loaded()
    reference = table.stops[0]
    found = None
    for left in range(10):
        for right in range(left + 1, 10):
            perm = list(range(10))
            perm[left], perm[right] = perm[right], perm[left]
            candidate = permute_tableau_columns(reference.state, perm)
            if pack_state(candidate) == pack_state(reference.state):
                continue
            remapped = replay_remapped_suffix(candidate, reference.state, reference.suffix)
            if not remapped.ok:
                continue
            try:
                trial = candidate.clone()
                replay_actions(trial, list(reference.suffix))
                unmapped_solved = bool(trial.is_solved() and len(trial.foundations) == 8 and not trial.stock)
            except ValueError:
                unmapped_solved = False
            if not unmapped_solved:
                found = (left, right, perm, candidate, remapped)
                break
        if found is not None:
            break
    assert found is not None
    left, right, perm, candidate, remapped = found
    assert remapped.cost == 22
    assert remapped.mapping[left] == right
    assert remapped.mapping[right] == left
    assert remapped.actions != reference.suffix
    joined = search_route_bridge(
        candidate,
        g0=149,
        references=table,
        ordering_targets=targets,
        max_unique=5,
        time_limit_s=1.0,
        rss_abort_mb=512,
    )
    assert joined.accepted
    assert joined.searched is False
    assert joined.expanded == 0
    assert joined.kind == "reference rejoin"
    assert joined.reference_g is not None and joined.reference_g > 149
    assert joined.projected_cost == 172 - (joined.reference_g - 149)
    assert joined.projected_cost <= 171
    assert joined.replay_ok
    assert joined.symmetry_only_matches >= 1
    assert joined.physical_matches == 0


def test_different_foundations_do_not_rejoin():
    _early, table, _targets, _checkpoints = _loaded()
    reference = table.stops[0]
    changed = reference.state.clone()
    changed.foundations.append([Card("s", 13)])
    assert matching_stops(table, changed) == []
    rejected = replay_remapped_suffix(changed, reference.state, reference.suffix)
    assert not rejected.ok
    assert rejected.failure == "remap"


def test_stock_bearing_rejoin_is_physical_and_does_not_call_symmetry():
    _early, _table, _targets, checkpoints = _loaded()
    stocked = checkpoints[140].state
    assert stocked.stock
    stop = make_reference_stop(stocked, index=140, g=139, suffix=())
    table = reference_table([stop])
    hits = matching_stops(table, stocked)
    assert len(hits) == 1
    assert hits[0][1] == "physical"
    assert hits[0][0].index == 140
    perm = [1, 0] + list(range(2, 10))
    swapped = permute_tableau_columns(stocked, perm)
    assert swapped.stock
    try:
        pack_post_stock_symmetry_state(swapped)
    except ValueError:
        raised = True
    else:
        raised = False
    assert raised
    assert matching_stops(table, swapped) == []
    rejected = replay_remapped_suffix(swapped, stocked, ())
    assert not rejected.ok
    assert rejected.failure == "remap"


def test_equal_reference_cost_is_not_a_saving_and_does_not_stop_search():
    assert projected_full_cost(142, 150) == 164
    assert projected_full_cost(149, 150) == 171
    assert projected_full_cost(150, 150) is None
    assert projected_full_cost(151, 150) is None
    source = _pair()
    stop = make_reference_stop(source, index=1, g=5, suffix=())
    found = search_route_bridge(
        source,
        g0=5,
        references=reference_table([stop]),
        ordering_targets=(),
        max_unique=1,
        time_limit_s=2.0,
        rss_abort_mb=512,
    )
    assert found.searched
    assert not found.accepted
    assert found.rejected_non_improving >= 1
    assert found.expanded == 1
    assert found.unique == 1
    assert found.node_count == 1
    assert found.stop_reason == "unique limit"
    assert found.inconclusive


def test_proof_bound_keeps_equality_and_rejects_one_above_before_admission():
    source = _state(
        {
            0: "7s 6s",
            1: "7h",
            2: "8c",
            3: "ks",
            4: "kh",
            5: "kd",
            6: "kc",
            7: "qs",
            8: "qh",
            9: "qd",
        }
    )
    root = pack_state(source)
    kept = (0, 1, 1)
    pruned = (0, 2, 2)
    assert step_cost(source, kept) == 1
    assert step_cost(source, pruned) == 1
    kept_state = source.clone()
    pruned_state = source.clone()
    assert step_cost(source, kept) == kept_state.move(0, 1, 1)
    pruned_state.move(0, 2, 2)
    kept_pack = pack_state(kept_state)
    assert kept_pack != pack_state(pruned_state)
    assert kept_pack != root
    # incumbent.proof_prune rejects equality. The bridge ceiling does not.
    assert proof_prune(171, 0, 171)

    def actions(current: SpiderState):
        if pack_state(current) != root:
            return []
        return [kept, pruned]

    def bound(current: SpiderState, _g: int) -> int:
        if pack_state(current) == root or pack_state(current) == kept_pack:
            return 0
        return 1

    found = search_route_bridge(
        source,
        g0=170,
        references=reference_table([]),
        ordering_targets=(),
        ceiling=171,
        max_unique=10,
        time_limit_s=2.0,
        rss_abort_mb=512,
        lower_bound_fn=bound,
        actions_fn=actions,
    )
    assert found.generated == 2
    assert found.unique == 2
    assert found.node_count == 2
    assert found.lower_bound_prunes == 1
    assert found.proof_prune_identities == 1
    assert found.proof_prune_unretained == 1
    assert not found.accepted
    assert found.stop_reason == "complete"
    assert found.negative_within_cap


def test_unique_cap_keeps_the_root_and_a_solved_root_does_not_search():
    source = _pair()
    root = pack_state(source)

    def one_paid(current: SpiderState):
        if pack_state(current) != root:
            return []
        return [(0, 1, 1)]

    capped = search_route_bridge(
        source,
        g0=0,
        references=reference_table([]),
        ordering_targets=(),
        max_unique=1,
        time_limit_s=2.0,
        rss_abort_mb=512,
        actions_fn=one_paid,
    )
    assert capped.searched
    assert capped.unique == 1
    assert capped.node_count == 1
    assert capped.expanded == 1
    assert capped.generated == 1
    assert capped.stop_reason == "unique limit"
    assert not capped.accepted

    def one_free(current: SpiderState):
        if pack_state(current) != root:
            return []
        return [(0, 2, 2)]

    assert step_cost(source, (0, 2, 2)) == 0
    free = search_route_bridge(
        source,
        g0=0,
        references=reference_table([]),
        ordering_targets=(),
        max_unique=5,
        time_limit_s=2.0,
        rss_abort_mb=512,
        actions_fn=one_free,
    )
    assert free.zero_cost_actions >= 1
    assert free.unique == 1
    assert free.node_count == 1
    assert free.duplicate_skips >= 1
    assert not free.accepted

    solved = search_route_bridge(
        _solved_stub(),
        g0=171,
        references=reference_table([]),
        ordering_targets=(),
        max_unique=1,
        time_limit_s=1.0,
        rss_abort_mb=512,
    )
    assert solved.accepted
    assert solved.kind == "solved"
    assert solved.projected_cost == 171
    assert solved.searched is False
    assert solved.expanded == 0
    assert solved.generated == 0
    assert solved.bridge == ()

    over = search_route_bridge(
        _solved_stub(),
        g0=172,
        references=reference_table([]),
        ordering_targets=(),
        max_unique=5,
        time_limit_s=1.0,
        rss_abort_mb=512,
    )
    assert not over.accepted
    assert over.searched
    assert over.expanded == 0


def test_action_order_keeps_every_move_and_does_not_rank_an_empty_column():
    state = _state({0: "4c 2h", 1: "3h"})
    actions = all_legal_actions(state)
    ordered = bridge_action_order(state, actions)
    assert len(ordered) == len(actions)
    assert sorted(map(str, ordered)) == sorted(map(str, actions))
    same = (0, 1, 1)
    onto_empty = (0, 2, 1)
    assert step_cost(state, same) == 1
    assert step_cost(state, onto_empty) == 1
    assert ordered.index(same) < ordered.index(onto_empty)


def test_authorised_caps_and_the_driver_does_not_repeat_post_sd5():
    assert MAX_UNIQUE == 20_000
    assert TIME_LIMIT_S == 45.0
    assert RSS_ABORT_MB == 512.0
    assert CEILING == 171
    text = DRIVER.read_text(encoding="utf-8")
    assert "search_post_sd5" not in text
    assert "80_000" not in text
    assert "80000" not in text
    assert "time_limit_s=90" not in text
    assert "MAX_UNIQUE" in text
