"""Post-Deal continuation audit v0.6: telemetry only, search unchanged."""

from __future__ import annotations

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state
from spider.rules import MW_RULES
from spider.simple_post_deal_audit import (
    census_legal_by_tier,
    classify_suppression_reason,
    foundation_proximity,
    permission_delta,
    reconstruct_coupled_lineage,
)
from spider.simple_progressive_solver import (
    classify_tier,
    enumerate_actions,
    is_deal,
    ordered_actions,
    solve_progressive,
)


def _ten(slots: dict[int, tuple], stock: list[Card] | None = None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, stock or [Card("c", rank) for rank in range(1, 11)])


def _uncover_state() -> SpiderState:
    return _ten(
        {
            0: ([Card("d", 9)], [Card("h", 6)]),
            1: ([], [Card("c", 7)]),
            2: ([Card("s", 8)], [Card("d", 5)]),
            3: ([], [Card("h", 6)]),
        }
    )


def _almost_solved() -> SpiderState:
    foundations = []
    for copy in range(2):
        for suit in "shdc":
            if copy == 1 and suit == "c":
                continue
            foundations.append([Card(suit, rank) for rank in range(13, 0, -1)])
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("c", rank) for rank in range(13, 1, -1)]
    cols[1].face_up = [Card("c", 1)]
    return SpiderState(cols, [], foundations)


def _run_state() -> SpiderState:
    cols = [Column([], []) for _ in range(10)]
    cols[0].face_up = [Card("h", 13), Card("h", 12), Card("h", 11)]
    cols[1].face_up = [Card("s", 10)]
    cols[2].face_up = [Card("d", 9), Card("c", 8)]
    for index in range(3, 10):
        cols[index].face_up = [Card("s", 13)]
    return SpiderState(cols, [])


def test_1_census_does_not_alter_ordering():
    state = _uncover_state()
    before = ordered_actions(state, 3, stats=None, prep_ply=0)
    census = census_legal_by_tier(state)
    after = ordered_actions(state, 3, stats=None, prep_ply=0)
    assert before == after
    packed = pack_state(state)
    census_legal_by_tier(state)
    assert pack_state(state) == packed
    actions = enumerate_actions(state)
    counted = [0, 0, 0, 0]
    for action in actions:
        counted[int(classify_tier(state, action))] += 1
    assert census["a"] == counted[0]
    assert census["b"] == counted[1]
    assert census["c"] == counted[2]
    assert census["d"] == counted[3]
    assert census["legal"] == len(actions)
    assert before == ordered_actions(state, 3, stats=None, prep_ply=0)


def test_2_post_deal_lineage_identity_replayable():
    state = _uncover_state()
    result = solve_progressive(
        state,
        max_nodes=120,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
        enable_post_deal_audit=True,
    )
    assert result.post_deal_audit is not None
    lineage = result.post_deal_audit.lineage
    assert lineage is not None
    assert lineage["replay_ok"]
    rebuilt = reconstruct_coupled_lineage(state, lineage["actions"])
    assert rebuilt["terminal"]["key_hex"] == lineage["terminal"]["key_hex"]
    end = state.clone()
    if lineage["actions"]:
        replay_actions(end, list(lineage["actions"]))
    assert pack_state(end).hex() == lineage["terminal"]["key_hex"]
    for segment in rebuilt["segments"]:
        assert segment["pre"]["key_hex"]
        assert segment["post"]["key_hex"]
        assert segment["pre"]["stock_rows"] == segment["post"]["stock_rows"] + 1


def test_3_same_exact_state_tracked_across_passes():
    state = _uncover_state()
    root_key = pack_state(state)
    result = solve_progressive(
        state,
        max_nodes=250,
        time_limit_s=2.0,
        depth_bands=(8, 16),
        max_pass=1,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
        enable_post_deal_audit=True,
    )
    pda = result.post_deal_audit
    assert pda is not None
    assert root_key in pda.encounters
    expanded_passes = {
        item["pass"] for item in pda.encounters[root_key] if item.get("expanded")
    }
    assert 0 in expanded_passes
    assert 1 in expanded_passes
    life = pda._pass_lifecycle(root_key, None, result.stats.band_pass_reports, result.stop_reason, 1)
    assert life["passes"]["0"] is not None
    assert life["passes"]["1"] is not None
    assert life["passes"]["0"]["expanded"]
    assert life["passes"]["1"]["expanded"]


def test_4_wider_pass_permission_delta():
    census = {
        "tableau_a": 2,
        "tableau_b": 3,
        "tableau_c": 4,
        "tableau_d": 5,
        "deal_legal": True,
        "deal_tier": 3,
    }
    delta_01 = permission_delta(census, 0, 1)
    assert delta_01["newly_permitted"] == 3
    assert delta_01["permitted_from"] == 2
    assert delta_01["permitted_to"] == 5
    delta_03 = permission_delta(census, 0, 3)
    assert delta_03["newly_permitted"] == 3 + 4 + 5 + 1
    assert delta_03["permitted_to"] == 2 + 3 + 4 + 5 + 1
    state = _uncover_state()
    real = census_legal_by_tier(state)
    delta_real = permission_delta(real, 0, 3)
    assert delta_real["newly_permitted"] == (
        real["tableau_b"] + real["tableau_c"] + real["tableau_d"]
        + (1 if real["deal_legal"] and (real["deal_tier"] or 0) > 0 else 0)
    )


def test_5_saturation_tt_stop_reason_classification():
    reason, detail = classify_suppression_reason(
        first_pass=0,
        encounters=[
            {
                "pass": 1,
                "expanded": False,
                "tt_skip": True,
                "remaining": 10,
                "covered_remaining": 40,
                "where": "frame_start",
            }
        ],
        band_pass_reports=[{"pass": 1, "skipped": False, "expanded": 20}],
        stop_reason="node limit",
        max_pass=3,
    )
    assert reason == "depth coverage TT prune"
    assert "frame_start" in detail

    reason, _ = classify_suppression_reason(
        first_pass=0,
        encounters=[],
        band_pass_reports=[
            {"pass": 1, "skipped": True, "expanded": 0, "stop": "saturated", "band": 80}
        ],
        stop_reason="band envelope",
        max_pass=3,
    )
    assert reason == "slice saturated/skipped"

    reason, _ = classify_suppression_reason(
        first_pass=0,
        encounters=[{"pass": 1, "expanded": True, "tt_skip": False}],
        band_pass_reports=[{"pass": 1, "skipped": False, "expanded": 50}],
        stop_reason="node limit",
        max_pass=3,
    )
    assert reason == "did_widen"

    reason, _ = classify_suppression_reason(
        first_pass=0,
        encounters=[],
        band_pass_reports=[],
        stop_reason="node limit",
        max_pass=3,
    )
    assert reason == "node budget ended"

    reason, _ = classify_suppression_reason(
        first_pass=0,
        encounters=[{"pass": 1, "expanded": False, "tt_skip": False, "child_dedup": True, "where": "child_gen"}],
        band_pass_reports=[{"pass": 1, "skipped": False, "expanded": 10}],
        stop_reason="band envelope",
        max_pass=3,
    )
    assert reason == "child dedup"

    reason, _ = classify_suppression_reason(
        first_pass=0,
        encounters=[{"pass": 1, "expanded": False, "tt_skip": False, "path_cycle": True, "where": "child_gen"}],
        band_pass_reports=[{"pass": 1, "skipped": False, "expanded": 10}],
        stop_reason="band envelope",
        max_pass=3,
    )
    assert reason == "active-path recurrence"

    reason, detail = classify_suppression_reason(
        first_pass=0,
        encounters=[{"pass": 0, "expanded": True, "tt_skip": False, "band": 320, "where": "expand"}],
        band_pass_reports=[
            {"pass": 1, "band": 80, "skipped": False, "expanded": 50, "stop": "budget"},
            {"pass": 1, "band": 160, "skipped": False, "expanded": 50, "stop": "budget"},
            {"pass": 1, "band": 320, "skipped": True, "expanded": 0, "stop": "saturated"},
            {"pass": 1, "band": 640, "skipped": True, "expanded": 0, "stop": "saturated"},
            {"pass": 3, "band": 320, "skipped": False, "expanded": 100000, "stop": "budget"},
        ],
        stop_reason="node limit",
        max_pass=3,
        first_band=320,
    )
    assert reason == "slice saturated/skipped"
    assert "pass=1" in detail


def test_6_stock_empty_state_telemetry():
    state = _almost_solved()
    assert len(state.stock) == 0
    result = solve_progressive(
        state,
        max_nodes=40,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=False,
        enable_audit=False,
        enable_post_deal_audit=True,
    )
    pda = result.post_deal_audit
    assert pda is not None
    empty = pda.stock_empty_best
    assert empty is not None
    assert empty["fd"] >= 0
    assert "census" in empty
    assert set(empty["census"]) >= {"tableau_a", "tableau_b", "tableau_c", "tableau_d"}
    assert "empties" in empty
    assert "fu" in empty
    assert "proximity" in empty
    assert "has_immediate_foundation_move" in empty["proximity"]
    assert empty["pass"] == 0


def test_7_diagnostic_foundation_proximity_facts():
    state = _run_state()
    prox = foundation_proximity(state)
    assert prox["longest_exposed_same_suit_run"] == 3
    assert prox["exposed_same_suit_adjacencies"] == 2
    assert prox["movable_same_suit_blocks"] == 1
    assert prox["exposed_complete_ka_runs"] == 0
    almost = _almost_solved()
    almost_prox = foundation_proximity(almost)
    assert almost_prox["has_immediate_foundation_move"] is True
    assert almost_prox["immediate_foundation_moves"] >= 1
    census = census_legal_by_tier(almost)
    assert census["has_tier_a"] is True


def test_8_instrumentation_off_on_same_search():
    state = _uncover_state()
    kwargs = dict(
        max_nodes=150,
        time_limit_s=2.0,
        depth_bands=(8, 16),
        max_pass=1,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
        enable_saturation=True,
        prep_ply=1,
    )
    off = solve_progressive(state, enable_post_deal_audit=False, **kwargs)
    on = solve_progressive(state, enable_post_deal_audit=True, **kwargs)
    assert off.nodes == on.nodes
    assert off.stats.unique_exact_states == on.stats.unique_exact_states
    assert off.stats.deals_executed == on.stats.deals_executed
    assert off.min_face_down == on.min_face_down
    assert off.actions == on.actions
    assert off.best_reveal_actions == on.best_reveal_actions
    assert off.stats.tt_hits == on.stats.tt_hits
    assert off.stats.probe_fires == on.stats.probe_fires
    assert off.post_deal_audit is None
    assert on.post_deal_audit is not None
    assert on.post_deal_audit.summary is not None


def test_9_deal_remains_engine_legal_under_audit():
    state = _uncover_state()
    state.columns[9] = Column([], [])
    assert state.columns[9].is_empty()
    assert state.can_deal(MW_RULES)
    assert ("deal",) in state.enumerate_legal_actions(MW_RULES)
    census = census_legal_by_tier(state)
    assert census["deal_legal"] is True
    result = solve_progressive(
        state,
        max_nodes=80,
        time_limit_s=2.0,
        depth_bands=(8,),
        max_pass=0,
        enable_best_reveal_deal_probe=True,
        enable_audit=False,
        enable_post_deal_audit=True,
    )
    assert result.stats.probe_fires[0] >= 1
    for action in enumerate_actions(state):
        if is_deal(action):
            assert census["deal_legal"] is True
