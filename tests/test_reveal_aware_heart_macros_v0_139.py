"""v0.139 reveal-aware heart macros.

The checkpoint-158 window is a feasibility oracle. Portfolio search and the
continuation stay in the driver, behind that control.
"""

from __future__ import annotations

import sys
from collections import deque
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.heart_run_followthrough import heart_goal, screen_heart_endpoint
from spider.human_strategy.anchored import build_checkpoints
from spider.human_strategy.evaluation import admissible_remaining
from spider.metrics import parse_moves_file
from spider.origin_fair_continuation import CONTINUATION_RSS_MB, CONTINUATION_TIME_S, CONTINUATION_UNIQUE
from spider.packed_state import pack_state, pack_whole_game_identity, permute_tableau_columns
from spider.post_deal_milestone import (
    PHASE_VERIFY_CAP,
    MilestoneContractError,
    MilestoneEndpoint,
    MilestoneHit,
    _keep_best_g,
    _verify_hits,
    choose_milestone_hits,
    rank_milestone_actions,
    search_milestone,
    select_exhaustive_lower_f,
    spec_from_source,
)
from spider.purposeful_macro import CEILING, CHECKPOINT_PREP
from spider.research_actions import apply_action, face_down_count, step_cost, tableau_actions
from spider.reveal_aware_heart import (
    CONTROL_DEPTH,
    CONTROL_PAID,
    CONTROL_PROOF,
    CONTROL_TIME_S,
    CONTROL_UNIQUE,
    HEART_RUN,
    TACTIC_DEPTH,
    TACTIC_PAID,
    TACTIC_PROOF,
    TACTIC_TIME_S,
    TACTIC_UNIQUE,
    compound_heart_reveal,
    compound_route_actions,
    top_heart_span,
)
from spider.search_kernel import KernelResult, SearchNode

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
DRIVER = ROOT / "tools" / "reveal_aware_heart_macros_v0_139.py"
ADAPTER = ROOT / "src" / "spider" / "reveal_aware_heart.py"


def _cards(text: str):
    return [Card.parse(token) for token in text.split() if token]


def _state(columns, stock: str = "", downs=None) -> SpiderState:
    downs = downs or {}
    cols = [
        Column(_cards(downs.get(index, "")), _cards(columns.get(index, "")))
        for index in range(10)
    ]
    return SpiderState(cols, _cards(stock), [])


def _hearts(high: int, low: int) -> str:
    names = {1: "ah", 10: "10h", 11: "jh", 12: "qh", 13: "kh"}
    return " ".join(names.get(rank, str(rank) + "h") for rank in range(high, low - 1, -1))


def _seq(suit: str, high: int, low: int) -> str:
    names = {1: "a", 10: "10", 11: "j", 12: "q", 13: "k"}
    return " ".join(names.get(rank, str(rank)) + suit for rank in range(high, low - 1, -1))


def _occupied(columns, start: int) -> dict:
    fillers = ("kd", "kc", "qd", "qc", "js", "jd", "qh", "qs", "10s", "9s")
    built = dict(columns)
    for index, token in enumerate(fillers):
        column = start + index
        if column > 9:
            break
        if column not in built:
            built[column] = token
    return built


def _endpoint(state, g, h, root=0, macro=((1, 2, 1),), tactical=((2, 3, 1),), pack="p", symmetry="s"):
    return MilestoneEndpoint(
        root_index=root,
        g=g,
        h=h,
        actions=tuple(tactical),
        pre_deal_macro=tuple(macro),
        state=state,
        pack=pack,
        symmetry=symmetry,
        suit_gain=0,
        face_down_drop=0,
        zero_cost=0,
        paid=1,
    )


def _hit(g, h, symmetry, pack) -> MilestoneHit:
    return MilestoneHit(
        actions=((0, 1, 1),),
        g=g,
        paid=1,
        zero_cost=0,
        suit_gain=1,
        face_down_drop=1,
        pack=pack,
        symmetry=symmetry,
        replay_ok=True,
        h=h,
        f=g + h,
    )


def _foundation_board() -> SpiderState:
    columns = {0: _seq("c", 13, 2), 1: "ac", 3: "ks"}
    for index, token in enumerate(("kh", "qh", "jh", "10h", "9h", "8h")):
        columns[4 + index] = token
    return _state(columns)


def _kernel_from_paths(source: SpiderState, paths) -> KernelResult:
    nodes = [SearchNode(b"", pack_state(source), 0, 0, -1, None, 0)]
    terminals = []
    for path, final, g in paths:
        parent = 0
        cursor = source
        spent = 0
        for depth, action in enumerate(path, start=1):
            spent += int(step_cost(cursor, action))
            cursor = cursor.clone()
            apply_action(cursor, action)
            store = pack_state(cursor)
            nodes.append(SearchNode(store, store, spent, 0, parent, action, depth))
            parent = len(nodes) - 1
        assert spent == g
        assert pack_state(cursor) == pack_state(final)
        terminals.append({"node": parent, "g": g, "store": pack_state(final).hex()})
    return KernelResult(nodes=nodes, terminals=terminals)


def _cost1_split(source: SpiderState):
    """Paid-1 paths. The foundation join is the low ``f``. Worse paths are many."""

    ace = (1, 0, 1)
    assert ace in tableau_actions(source)
    assert step_cost(source, ace) == 1
    joined = source.clone()
    apply_action(joined, ace)
    best_f = 1 + int(admissible_remaining(joined))
    worse = []
    same = []
    seen = set()
    queue = deque([(source, 0, ())])
    pops = 0
    while queue and len(worse) < 140:
        pops += 1
        if pops > 20000:
            break
        state, g, path = queue.popleft()
        key = pack_state(state)
        if key in seen:
            continue
        seen.add(key)
        if path and g == 1:
            score = g + int(admissible_remaining(state))
            row = (path, state, g, score)
            if score == best_f:
                same.append(row)
            elif score > best_f:
                worse.append(row)
        if len(path) >= 2 or g > 1:
            continue
        for action in tableau_actions(state):
            nxt = state.clone()
            cost = int(step_cost(state, action))
            apply_action(nxt, action)
            queue.append((nxt, g + cost, path + (action,)))
    return best_f, worse, same, pops


def test_legacy_window_misses_a_later_lower_f_and_exhaustive_keeps_it():
    source = _foundation_board()
    assert admissible_remaining(source) == 8
    best_f, worse, same, _pops = _cost1_split(source)
    assert len(worse) > PHASE_VERIFY_CAP
    assert same
    assert any(path == ((1, 0, 1),) for path, _state, _g, score in same if score == best_f)
    ordered = [(path, state, g) for path, state, g, _score in worse[: PHASE_VERIFY_CAP + 8]]
    ordered.extend((path, state, g) for path, state, g, _score in same)
    kernel = _kernel_from_paths(source, ordered)
    spec = spec_from_source(source, "c")
    legacy = _verify_hits(source, spec, kernel, 0, limit=PHASE_VERIFY_CAP)
    assert len(legacy) == PHASE_VERIFY_CAP
    legacy_f = [hit.g + int(admissible_remaining(hit.state)) for hit in legacy]
    assert all(score > best_f for score in legacy_f)
    assert ((1, 0, 1),) not in [hit.actions for hit in legacy]
    kept, info = select_exhaustive_lower_f(source, spec, kernel, 0, limit=8)
    assert info["verification"] == "complete"
    assert info["exhaustive"] is True
    assert info["unverified_terminals"] == 0
    assert info["terminals"] == len(kernel.terminals)
    assert info["terminals"] > PHASE_VERIFY_CAP
    assert info["verified"] + info["replay_rejected"] + info["screened"] == info["terminals"]
    assert kept
    assert kept[0].f == best_f
    assert kept[0].f < min(legacy_f)
    assert kept[0].h == kept[0].f - kept[0].g


def test_incomplete_verification_returns_no_best_and_legacy_policy_is_unchanged():
    source = _state({0: _hearts(7, 2), 1: "ah"})
    joined = source.clone()
    apply_action(joined, (1, 0, 1))
    kernel = _kernel_from_paths(source, [(((1, 0, 1),), joined, 1)])
    spec = spec_from_source(source, "h")

    def boom(_state):
        raise RuntimeError("verification failed")

    hits, info = select_exhaustive_lower_f(source, spec, kernel, 0, limit=8, terminal_fn=boom)
    assert hits == []
    assert info["verification"] == "INCOMPLETE VERIFICATION"
    assert info["exhaustive"] is False
    broken = KernelResult(
        nodes=kernel.nodes,
        terminals=[{"node": 1, "g": 99, "store": "00"}],
    )
    rejected, rejected_info = select_exhaustive_lower_f(source, spec, broken, 0, limit=8)
    assert rejected == []
    assert rejected_info["verification"] == "complete"
    assert rejected_info["replay_rejected"] == 1
    assert rejected_info["verified"] == 0
    cheaper_g = _hit(150, 21, "sym-a", "pack-a")
    lower_f = _hit(154, 16, "sym-b", "pack-b")
    by_g, g_info = choose_milestone_hits([lower_f, cheaper_g], policy="lowest_g", limit=1)
    by_f, f_info = choose_milestone_hits([cheaper_g, lower_f], policy="lower_f", limit=1)
    assert by_g[0].g == 150
    assert by_f[0].f == 170
    assert g_info["policy"] == "lowest_g"
    assert "proof" not in f_info["reason"]
    dominated_hit = MilestoneHit(
        actions=((2, 3, 1),),
        g=4,
        paid=4,
        zero_cost=0,
        suit_gain=0,
        face_down_drop=0,
        pack="same-pack",
        symmetry="same-sym",
        replay_ok=True,
        h=5,
        f=9,
    )
    cheaper_hit = MilestoneHit(
        actions=((1, 0, 1),),
        g=1,
        paid=1,
        zero_cost=0,
        suit_gain=0,
        face_down_drop=0,
        pack="same-pack",
        symmetry="same-sym",
        replay_ok=True,
        h=7,
        f=8,
    )
    winners, dominated = _keep_best_g([dominated_hit, cheaper_hit], lambda hit: hit.pack)
    assert dominated == 1
    assert winners[0].g == 1
    assert winners[0].f == 8


def test_checkpoint_158_lacks_the_compound_and_163_has_both():
    opening = SpiderState.from_cards(list(load_deal(DEAL)))
    actions = parse_moves_file(CANONICAL)
    checkpoints = build_checkpoints(opening, actions)
    start = checkpoints[158]
    end = checkpoints[163]
    goal = compound_heart_reveal(face_down_count(start.state))
    assert start.g == 156
    assert face_down_count(start.state) == 1
    assert not heart_goal(start.state)
    assert top_heart_span(start.state)["length"] == 5
    assert not goal(start.state)
    state = start.state.clone()
    costs = []
    for action in actions[158:163]:
        costs.append(int(step_cost(state, action)))
        apply_action(state, action)
    assert costs == [1, 1, 1, 1, 1]
    assert start.g + sum(costs) == 161
    assert end.g == 161
    assert face_down_count(state) == 0
    assert heart_goal(state)
    assert top_heart_span(state)["length"] >= HEART_RUN
    assert goal(state)
    assert pack_state(state) == pack_state(end.state)
    revealed = start.state.clone()
    apply_action(revealed, actions[158])
    assert face_down_count(revealed) == 0
    assert not heart_goal(revealed)
    adapter = ADAPTER.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")
    for action in actions[158:163]:
        assert repr(action) not in adapter
        assert repr(action) not in driver


def test_compound_requires_a_top_run_and_a_real_reveal_together():
    goal = compound_heart_reveal(1)
    buried = _state({0: _hearts(7, 1) + " ks"})
    assert not heart_goal(buried)
    assert not goal(buried)
    reveal_only = _state({0: _hearts(6, 1)})
    assert face_down_count(reveal_only) < 1
    assert not heart_goal(reveal_only)
    assert not goal(reveal_only)
    run_only = _state({0: _hearts(7, 1)}, downs={1: "qc"})
    assert heart_goal(run_only)
    assert face_down_count(run_only) == 1
    assert not goal(run_only)
    both = _state({0: _hearts(7, 1), 1: "ks"})
    assert goal(both)
    swapped = permute_tableau_columns(both, (1, 0, 2, 3, 4, 5, 6, 7, 8, 9))
    assert not both.stock
    assert goal(swapped)
    assert pack_state(both) != pack_state(swapped)
    assert pack_whole_game_identity(both) == pack_whole_game_identity(swapped)


def test_run_reveal_orders_the_unfinished_component_and_searches_both_orders():
    heart_first = _state(
        _occupied({0: _hearts(7, 2), 1: "ah", 2: "ks"}, 4),
        downs={2: "qc"},
    )
    extend = (1, 0, 1)
    reveal = (2, 3, 1)
    assert extend in tableau_actions(heart_first)
    assert reveal in tableau_actions(heart_first)
    assert face_down_count(heart_first) == 1
    assert top_heart_span(heart_first)["length"] == 6
    both_open = rank_milestone_actions(
        heart_first,
        tableau_actions(heart_first),
        "h",
        run_reveal=True,
        run_min=7,
        source_face_down=1,
    )
    assert both_open.index(extend) < both_open.index(reveal)
    assert len(both_open) == len(tableau_actions(heart_first))
    reveal_first = _state(
        _occupied({0: _hearts(13, 7), 1: "6h", 2: "ks"}, 4),
        downs={2: "qc"},
    )
    longer = (1, 0, 1)
    uncover = (2, 3, 1)
    assert top_heart_span(reveal_first)["length"] == 7
    assert longer in tableau_actions(reveal_first)
    assert uncover in tableau_actions(reveal_first)
    run_done = rank_milestone_actions(
        reveal_first,
        tableau_actions(reveal_first),
        "h",
        run_reveal=True,
        run_min=7,
        source_face_down=1,
    )
    plain = rank_milestone_actions(reveal_first, tableau_actions(reveal_first), "h")
    assert run_done.index(uncover) < run_done.index(longer)
    assert plain.index(longer) < plain.index(uncover)
    hidden = face_down_count(heart_first)
    heart_goal_fn = compound_heart_reveal(hidden)
    found_heart = search_milestone(
        heart_first,
        g0=4,
        suit="h",
        paid_moves=2,
        max_depth=4,
        max_unique=400,
        time_limit_s=2.0,
        terminal_fn=heart_goal_fn,
        stop_on_first=True,
        hit_policy="lower_f",
        run_reveal=True,
        run_min=7,
    )
    assert found_heart.met and found_heart.replay_ok
    assert found_heart.verification == "complete"
    assert found_heart.hit_truncation["exhaustive"] is True
    assert found_heart.hit_truncation["unverified_terminals"] == 0
    assert found_heart.hit_truncation["verified"] == found_heart.hit_truncation["terminals"]
    assert found_heart.verify_wall_s >= 0
    trial = heart_first.clone()
    for action in found_heart.actions:
        apply_action(trial, action)
    assert heart_goal_fn(trial)
    assert all(count == 0 for count in found_heart.phases_admitted.values())
    assert all(count == 0 for count in found_heart.phases_expanded.values())
    assert {name for name, _count in found_heart.lane_exp} <= {"run", "reveal", "setup"}
    reveal_source = _state(
        _occupied({0: _hearts(7, 1), 1: "ks"}, 3),
        downs={1: "ad"},
    )
    assert heart_goal(reveal_source)
    assert face_down_count(reveal_source) == 1
    found_reveal = search_milestone(
        reveal_source,
        g0=4,
        suit="h",
        paid_moves=1,
        max_depth=3,
        max_unique=200,
        time_limit_s=2.0,
        terminal_fn=compound_heart_reveal(1),
        stop_on_first=True,
        hit_policy="lower_f",
        run_reveal=True,
        run_min=7,
    )
    assert found_reveal.met and found_reveal.replay_ok
    assert found_reveal.face_down_after == 0
    assert heart_goal(found_reveal.hits[0].state)
    with pytest.raises(MilestoneContractError):
        search_milestone(
            reveal_source,
            g0=4,
            suit="h",
            paid_moves=1,
            max_depth=2,
            max_unique=10,
            time_limit_s=1.0,
            phase_aware=True,
            run_reveal=True,
        )


def test_zero_cost_park_stays_on_a_compound_path():
    columns = _occupied({0: "kh", 2: _hearts(7, 2), 3: "ah", 4: "qs", 5: "ks"}, 6)
    source = _state(columns, stock="ad", downs={4: "ac"})
    park = (0, 1, 1)
    assert park in tableau_actions(source)
    assert step_cost(source, park) == 0
    assert source.stock
    hidden = face_down_count(source)

    def parked(state: SpiderState) -> bool:
        top = state.columns[1].face_up[-1:]
        return bool(top) and top[0] == _cards("kh")[0] and compound_heart_reveal(hidden)(state)

    found = search_milestone(
        source,
        g0=3,
        suit="h",
        paid_moves=2,
        max_depth=4,
        max_unique=500,
        time_limit_s=2.0,
        terminal_fn=parked,
        stop_on_first=True,
        run_reveal=True,
        run_min=7,
    )
    assert found.met and found.replay_ok
    trial = source.clone()
    costs = []
    for action in found.actions:
        costs.append(int(step_cost(trial, action)))
        apply_action(trial, action)
    assert 0 in costs
    assert parked(trial)
    assert face_down_count(trial) < hidden
    assert heart_goal(trial)


def test_proof_equality_stays_eligible_under_run_reveal():
    source = _state({0: _hearts(7, 2), 1: "ah"})
    root_pack = pack_state(source)

    def bound(state: SpiderState, _g: int) -> int:
        if pack_state(state) == root_pack:
            return 1
        return 0

    kept = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=1,
        lower_bound_fn=bound,
        hit_policy="lower_f",
        run_reveal=True,
        run_min=7,
    )
    assert kept.met
    assert kept.g == 1
    assert kept.verification == "complete"
    pruned = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
        proof_ceiling=0,
        lower_bound_fn=bound,
        hit_policy="lower_f",
        run_reveal=True,
        run_min=7,
    )
    assert not pruned.met
    assert pruned.expanded == 0
    legacy = search_milestone(
        source,
        g0=0,
        suit="h",
        paid_moves=1,
        max_depth=2,
        max_unique=20,
        time_limit_s=2.0,
        terminal_fn=heart_goal,
        stop_on_first=True,
    )
    assert legacy.verification == "legacy"
    assert legacy.hit_truncation["exhaustive"] is False
    body = kept.public()
    assert "verify_wall_s" in body and "verify_cpu_s" in body


def test_screen_rejects_an_exhausted_pack_before_a_child_and_f_171():
    state = _state({0: _hearts(7, 1), 1: "ks"})
    exhausted = _endpoint(state, 150, 10, pack="exhausted-pack", symmetry="exhausted-sym")
    skipped = screen_heart_endpoint(
        exhausted,
        ceiling=171,
        excluded_packs=("exhausted-pack",),
        goal=lambda _state: True,
    )
    assert skipped["accepted"] is False
    assert skipped["proof"] is False
    assert skipped["affordable_successor"] is False
    assert "previously exhausted identity" in skipped["reasons"]
    above = _endpoint(state, 154, 17, pack="pack-171", symmetry="sym-171")
    above_screen = screen_heart_endpoint(above, ceiling=TACTIC_PROOF, goal=lambda _state: True)
    assert above.f == 171
    assert above_screen["screen_f"] == 170
    assert above_screen["accepted"] is False
    assert "f above screen" in above_screen["reasons"]
    assert above_screen["proof"] is False
    canonical = [(0, 1, 1)] * 145
    route = compound_route_actions(canonical, exhausted, ((6, 7, 1),), ((7, 8, 1),))
    assert route[:CHECKPOINT_PREP] == canonical[:CHECKPOINT_PREP]
    assert tuple(route[CHECKPOINT_PREP:CHECKPOINT_PREP + 1]) == exhausted.pre_deal_macro
    assert route[CHECKPOINT_PREP + 1] == ("deal",)
    assert tuple(route[CHECKPOINT_PREP + 2:CHECKPOINT_PREP + 3]) == exhausted.actions
    assert route[CHECKPOINT_PREP + 3:] == [(6, 7, 1), (7, 8, 1)]


def test_driver_stops_at_the_control_and_does_not_raise_caps():
    text = DRIVER.read_text(encoding="utf-8")
    adapter = ADAPTER.read_text(encoding="utf-8")
    assert text.index("if not control_ready") < text.index("discover_macros(")
    assert text.index("if not opened") < text.index("search_origin_fair(")
    assert 'hit_policy="lower_f"' in text
    assert "run_reveal=True" in text
    assert "phase_aware=True" not in text
    assert CONTROL_PAID == 5 and CONTROL_DEPTH == 8 and CONTROL_UNIQUE == 12_000
    assert CONTROL_TIME_S == 12.0 and CONTROL_PROOF == 172
    assert TACTIC_PAID == 12 and TACTIC_DEPTH == 18 and TACTIC_UNIQUE == 6_000
    assert TACTIC_TIME_S == 6.0 and TACTIC_PROOF == 171
    assert CONTINUATION_UNIQUE == 20_000
    assert CONTINUATION_TIME_S == 45.0
    assert CONTINUATION_RSS_MB == 512.0
    assert CEILING == 171
    for banned in (
        "search_bridge_roots",
        "search_post_sd5",
        "search_route_bridge",
        "80_000",
        "80000",
        "time_limit_s=90",
    ):
        assert banned not in text
        assert banned not in adapter
