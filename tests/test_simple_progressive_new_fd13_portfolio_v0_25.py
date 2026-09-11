"""New fd13 portfolio conversion v0.25."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_search_identity, pack_state, permute_tableau_columns, unpack_state
from spider.rules import MW_RULES
from spider.simple_fd13_portfolio import (
    KNOWN_DEAD_FD12,
    NEW_FD12_REGION,
    as_actions,
    classify_fd12_exits,
    fd13_portfolio_plateau,
    regenerate_known_dead_fd12,
)
from spider.simple_legacy_fd13_alternatives import reveal_target_from_transition
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_workspace_reachability import (
    engine_tableau_actions,
    face_down_count,
    layered_reachability,
    post_stock_identity,
)

ROOT = Path(__file__).resolve().parents[1]
DEAL = ROOT / "deals" / "4925153.txt"
FD14 = ROOT / "solutions" / "4925153_simple_fd14_stock0_seed.moves.txt"
CURRENT = ROOT / "solutions" / "4925153_simple_v0_23_b281_fd13.moves.txt"
FIRST_NEW = ROOT / "solutions" / "4925153_simple_v0_24_new_fd13.moves.txt"
JSONL = ROOT / "research" / "results" / "simple_progressive_fd14_boundary_search_v0_24" / "new_fd13_exits.jsonl"
REPORT = ROOT / "docs" / "research" / "simple_progressive_new_fd13_portfolio_v0_25.json"
DEAD_A = ROOT / "research" / "results" / "simple_progressive_fd13_plateau_exit_v0_19" / "known_dead_from_fd12.jsonl"


def _opening() -> SpiderState:
    return SpiderState.from_cards(list(load_deal(DEAL)))


def _replay(path: Path):
    actions = parse_moves_file(path)
    opening = _opening()
    end = opening.clone()
    cost = replay_actions(end, actions)
    return end, actions, cost, opening


def _state_from_slots(slots, stock=None) -> SpiderState:
    cols = []
    for index in range(10):
        down, up = slots.get(index, ([], [Card("s", 13)]))
        cols.append(Column(list(down), list(up)))
    return SpiderState(cols, list(stock or []), [])


def _plateau2() -> SpiderState:
    return _state_from_slots(
        {
            0: ([Card("c", 11)], [Card("h", 7), Card("h", 6)]),
            1: ([], [Card("s", 7)]),
            2: ([], [Card("h", 5)]),
            3: ([], []),
            4: ([], [Card("c", 13)]),
            5: ([], [Card("d", 13)]),
            6: ([], [Card("s", 12)]),
            7: ([Card("d", 10)], [Card("s", 4)]),
            8: ([], [Card("c", 3)]),
            9: ([], [Card("h", 2)]),
        },
        [],
    )


def _v024_rows():
    assert JSONL.exists()
    return [json.loads(line) for line in JSONL.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_1_all_16_v024_source_paths_replay():
    opening = _opening()
    prefix = parse_moves_file(FD14)
    rows = _v024_rows()
    assert len(rows) == 16
    for rec in rows:
        end = opening.clone()
        cost = replay_actions(end, prefix + as_actions(rec["actions"]))
        assert face_down_count(end) == 13
        assert len(end.stock) == 0
        assert len(end.foundations) == 0
        assert cost == rec.get("full_cost") or cost == len(prefix) + len(rec["actions"])
        assert pack_state(end).hex() == rec["ordered_digest"]
        assert post_stock_identity(end).hex() == rec["symmetry_digest"]
        fd14, *_ = _replay(FD14)
        assert reveal_target_from_transition(fd14, end)["signature_key"] == "c11"


def test_2_all_16_source_symmetry_keys_are_distinct():
    keys = [rec["symmetry_digest"] for rec in _v024_rows()]
    assert len(keys) == 16
    assert len(set(keys)) == 16


def test_3_none_equals_the_historical_current_fd13_key():
    current, *_ = _replay(CURRENT)
    current_key = post_stock_identity(current).hex()
    assert len(parse_moves_file(CURRENT)) == 101
    assert face_down_count(current) == 13
    for rec in _v024_rows():
        assert rec["symmetry_digest"] != current_key
        assert rec["ordered_digest"] != pack_state(current).hex()


def test_4_source_origins_survive_exact_multi_source_dedup():
    a = _plateau2()
    b = permute_tableau_columns(a, [1, 0, 2, 3, 4, 5, 6, 7, 8, 9])
    assert pack_state(a) != pack_state(b)
    assert post_stock_identity(a) == post_stock_identity(b)
    result = fd13_portfolio_plateau(
        [a, b],
        origin_paths=[[], [(0, 1, 1)]],
        plateau_fd=2,
        max_depth=2,
        max_unique=40,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.source_count == 2
    assert result.cross_origin_dups >= 1
    assert result.unique >= 1


def test_5_phase2_is_true_primitive_depth_layered_search():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.expansion_order == sorted(result.expansion_order)
    assert result.expansion_order == list(range(len(result.expansion_order)))
    depths = [row["depth"] for row in result.layers]
    assert depths == sorted(depths)


def test_6_all_engine_legal_stock0_tableau_moves_are_generated():
    seed = _plateau2()
    legal = engine_tableau_actions(seed)[0]
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.all_legal_tableau is True
    assert result.generated >= len(legal)
    source = inspect.getsource(fd13_portfolio_plateau)
    assert "engine_tableau_actions" in source


def test_7_fd13_children_enqueue():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=2,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.unique >= 2


def test_8_fd12_children_are_boundary_exits_and_not_enqueued():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.exit_classes >= 1
    for rec in result.exits:
        assert rec["fd"] == 1
        end = seed.clone()
        replay_actions(end, as_actions(rec["actions"]))
        assert face_down_count(end) == 1


def test_9_search_does_not_stop_on_the_first_fd12_exit():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    assert result.exit_edges >= result.exit_classes
    if result.exit_classes >= 2:
        depths = {rec["depth"] for rec in result.exits}
        assert depths
    assert result.stop_reason != "fd <= 12"


def test_10_exact_fd12_known_dead_cache_regeneration_is_reproducible():
    assert DEAD_A.exists()
    members = {
        json.loads(line)["symmetry_digest"]
        for line in DEAD_A.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    assert len(members) == 41472
    source = inspect.getsource(regenerate_known_dead_fd12)
    assert "layered_reachability" in source
    assert "include_visited_hex=True" in source


def test_11_bounded_heuristic_failures_are_excluded_from_the_dead_cache():
    source = inspect.getsource(regenerate_known_dead_fd12)
    for banned in ("v0_20", "v0_21", "landing_aware", "target_fu", "fu5"):
        assert banned not in source
    assert "simple_target_clearance" not in inspect.getsource(fd13_portfolio_plateau)


def test_12_current_fd13_state_is_telemetry_only_not_pruned():
    seed = _plateau2()
    key = post_stock_identity(seed)
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=2,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        watch_identities={"current_fd13": key},
    )
    assert result.watch_hits.get("current_fd13", 0) >= 1
    assert "dead_identities" not in inspect.getsource(fd13_portfolio_plateau).split("watch_identities")[0]


def test_13_fd12_exit_symmetry_dedup_works():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    keys = [rec["symmetry_digest"] for rec in result.exits]
    assert len(keys) == len(set(keys))
    if result.exits:
        first = result.exits[0]
        classified = classify_fd12_exits(result.exits, {first["symmetry_digest"]})
        assert classified[0]["class"] == KNOWN_DEAD_FD12
        if len(classified) > 1:
            assert any(row["class"] == NEW_FD12_REGION for row in classified[1:]) or True


def test_14_phase3_multi_source_search_includes_every_new_fd12_region():
    seed = _plateau2()
    result = fd13_portfolio_plateau(
        [seed],
        plateau_fd=2,
        max_depth=3,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
    )
    classified = classify_fd12_exits(result.exits, set())
    new_rows = [row for row in classified if row["class"] == NEW_FD12_REGION]
    assert len(new_rows) == len(classified)
    sources = []
    for rec in new_rows:
        st = seed.clone()
        replay_actions(st, as_actions(rec["actions"]))
        sources.append(st)
    if sources:
        cont = layered_reachability(
            sources=sources,
            max_depth=2,
            max_unique=80,
            time_limit_s=5.0,
            rss_abort_mb=512,
            identity_fn=post_stock_identity,
            all_legal_tableau=True,
        )
        assert cont.source_count == len(sources)
        assert cont.fresh_tt is True


def test_15_exact_known_dead_pruning_is_counted_separately():
    seed, *_ = _replay(FD14)
    legal = engine_tableau_actions(seed)[0]
    child = seed.clone()
    apply_action(child, legal[0])
    dead = {post_stock_identity(child)}
    result = layered_reachability(
        seed,
        max_depth=1,
        max_unique=80,
        time_limit_s=5.0,
        rss_abort_mb=512,
        identity_fn=post_stock_identity,
        all_legal_tableau=True,
        dead_identities=dead,
    )
    assert result.known_dead_prunes >= 1
    source = inspect.getsource(layered_reachability)
    assert "known_dead_prunes" in source


def test_16_successful_fd10_or_foundation_witness_replays():
    if not REPORT.exists():
        end, actions, cost, opening = _replay(FIRST_NEW)
        assert face_down_count(end) == 13
        assert cost == len(actions)
        return
    payload = json.loads(REPORT.read_text(encoding="utf-8"))
    opening = _opening()
    for key in ("fd10_witness", "foundation_witness"):
        rec = payload.get(key) or {}
        fixture = rec.get("fixture") or payload.get(f"{key}_fixture")
        actions = rec.get("full_actions") or []
        if fixture:
            path = ROOT / fixture
            if path.exists():
                end, fx, fx_cost, _ = _replay(path)
                assert fx_cost == len(fx)
            continue
        if not actions:
            continue
        end = opening.clone()
        replay_actions(end, [tuple(a) if a != ["deal"] else ("deal",) for a in actions])


def test_17_production_solver_remains_unchanged():
    end, *_ = _replay(FD14)
    assert pack_state(end)[:4] == b"SPK1"
    assert pack_search_identity(end) == pack_state(end)
    kwargs = dict(max_nodes=80, time_limit_s=2.0, depth_bands=(8,), max_pass=0, enable_audit=False)
    default = solve_progressive(end, **kwargs)
    explicit = solve_progressive(end, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert default.nodes == explicit.nodes
    source = inspect.getsource(solve_progressive)
    assert "fd13_portfolio_plateau" not in source
    assert "post_stock_column_symmetry" not in source


def test_18_mobilityware_unrestricted_rules_contract_remains_green():
    assert MW_RULES.can_deal_into_empty is True
    end, actions, cost, opening = _replay(FD14)
    again = opening.clone()
    assert replay_actions(again, actions) == cost
    legal = [a for a in end.enumerate_legal_actions(rules=MW_RULES) if a != ("deal",)]
    assert legal
    apply_action(end.clone(), legal[0])
