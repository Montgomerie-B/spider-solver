"""Integrated whole-game optimisation v0.68."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES, assembly_lane_keys
from spider.autonomous_cost import COST_LANES, checkpoints_from_trace
from spider.cards import Card
from spider.deal_preview import (
    clear_preview_cache,
    preview_cache_stats,
    preview_next_deal,
)
from spider.engine import Column, SpiderState
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    INCUMBENT_MOVES,
    load_autonomous_192,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.operational_policy import OP_LANES, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import is_deal, stock_rows
from spider.search_kernel import SearchLimits, run_search
from spider.whole_game_anytime import opening_root, opening_state
from spider.whole_game_epoch_scheduler import (
    reconcile_lower_bound_telemetry,
    search_epoch_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src" / "spider" / "integrated_policy.py"
SCRIPT = ROOT / "research" / "integrated_whole_game_v0_68.py"
ARTEFACT = ROOT / "docs" / "research" / "integrated_whole_game_v0_68.json"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _ka(suit: str):
    return _run(suit, 13, 1)


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_192_incumbent_replay_and_constants():
    assert AUTONOMOUS_INCUMBENT_MW == 192
    assert CANDIDATE_CEILING == 191
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert AUTONOMOUS_INCUMBENT_MW != CANONICAL_MW_COST
    opening = opening_state()
    v = verify_autonomous_192(opening)
    assert v["ok"]
    assert v["g"] == 192
    assert v["deals"] == 5
    assert v["solved"]
    assert v["foundations"] == 8
    assert v["stock_empty"]
    assert v["tableau_empty"]
    end = opening.clone()
    assert replay_actions(end, parse_moves_file(INCUMBENT_MOVES)) == 192
    assert end.is_solved()


def test_v067_header_fix_does_not_change_moves():
    text = V067.read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("# Autonomous v0.67")
    assert "v0.59" not in text.splitlines()[0]
    opening = opening_state()
    a = parse_moves_file(V067)
    b = verify_autonomous_192(opening)["actions"]
    assert a == b
    end = opening.clone()
    assert replay_actions(end, a) == 192


def test_preview_cache_preserves_exact_result():
    clear_preview_cache()
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    a = preview_next_deal(opening, pre_g=0, detail="harvest")
    b = preview_next_deal(opening, pre_g=0, detail="harvest")
    c = preview_next_deal(opening, pre_g=12, detail="harvest")
    assert a["post_digest"] == b["post_digest"] == c["post_digest"]
    assert a["rank_ok"] == b["rank_ok"] == c["rank_ok"]
    assert a["landings"] == b["landings"]
    assert c["pre_g"] == 12
    assert c["post_g"] == 13
    assert a["pre_g"] == 0
    stats = preview_cache_stats()
    assert stats["hits"] >= 1
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    clone = opening.clone()
    clone.deal()
    assert a["post_digest"] == pack_state(clone).hex()


def test_lower_bound_telemetry_reconciles_on_epochs():
    opening = opening_state()
    root = opening_root(opening)
    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=16,
        time_limit_s=1.0,
        rss_abort_mb=4096,
        cost_ceiling=191,
        portfolio_width=8,
        lower_bound_fn=stock_empty_assembly_h,
        lane_names=COMPLETION_LANES,
        keys_fn=assembly_lane_keys,
    )
    rec = reconcile_lower_bound_telemetry(res)
    assert rec["ok"]
    assert rec["seconds_match"]
    assert all("lower_bound_prunes" in ep for ep in res.epochs)
    four = _columns(
        _run("c", 13, 10),
        _run("c", 9, 7),
        _run("c", 6, 4),
        _run("c", 3, 1),
        foundations=[_ka("s"), _ka("s"), _ka("h"), _ka("h"), _ka("d"), _ka("d"), _ka("c")],
        stock=[],
    )
    root2 = {
        "g": 190,
        "ordered_digest": pack_state(four).hex(),
        "whole_game_identity": pack_whole_game_identity(four).hex(),
        "ident": pack_whole_game_identity(four).hex(),
    }
    kr = run_search(
        [root2],
        limits=SearchLimits(max_unique=20, time_limit_s=0.5, cost_ceiling=191),
        identity_fn=pack_whole_game_identity,
        lower_bound_fn=stock_empty_assembly_h,
    )
    assert kr.lower_bound_prunes >= 1
    assert kr.expanded == 0


def test_completion_inactive_before_stock_empty_and_lanes():
    opening = opening_state()
    keys = assembly_lane_keys(opening, 0)
    assert keys["completion"] is None
    assert stock_rows(opening) > 0
    assert OP_LANES == COST_LANES
    assert "completion" in COMPLETION_LANES
    assert "durability" not in COMPLETION_LANES
    src = inspect.getsource(search_integrated_optimisation)
    assert "stock_empty_assembly_h" in src
    assert "TRANSITION_HARVEST_CATS" in src
    assert "assembly_lane_keys" in src


def test_checkpoints_prefix_g_and_identity_untouched():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    assert set(ck) <= {0, 1, 2, 3, 4, 5}
    for rows, rec in ck.items():
        assert rec["stock_rows"] == rows
        assert rec["g"] == rec["g"]
        assert rec.get("incumbent_control") is True
        end = opening.clone()
        from spider.research_actions import as_actions

        g = replay_actions(end, as_actions(rec["full_actions"]))
        assert g == rec["g"]
        assert pack_state(end).hex() == rec["ordered_digest"]
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident


def test_no_canonical_in_search_ceiling_and_opening_root():
    text = _text(POLICY)
    assert "4925153_canonical.moves" not in text
    assert _simple_imports(POLICY) == []
    src = inspect.getsource(search_operational_optimisation)
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    src_i = inspect.getsource(search_integrated_optimisation)
    assert "cost_ceiling=CANDIDATE_CEILING" in src_i
    assert CANDIDATE_CEILING == 191
    opening = opening_state()
    root = opening_root(opening)
    assert root["g"] == 0
    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=8,
        time_limit_s=0.4,
        rss_abort_mb=4096,
        cost_ceiling=191,
        portfolio_width=4,
    )
    assert res.min_g is None or res.min_g >= 0
    assert res.candidate_ceiling == 191


def test_script_canonical_after_search_and_old_regressions():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_integrated_optimisation(")
        eval_at = script.find("EVAL canonical")
        assert search_at != -1
        assert eval_at > search_at
    opening = opening_state()
    a198 = parse_moves_file(V059)
    e198 = opening.clone()
    assert replay_actions(e198, a198) == 198
    assert e198.is_solved()
    a172 = parse_moves_file(CANON)
    e172 = opening.clone()
    assert replay_actions(e172, a172) == 172
    assert e172.is_solved()


def test_artefact_terminal_from_opening_if_present():
    opening = opening_state()
    if not ARTEFACT.exists():
        return
    import json

    from spider.healthy_f2 import parse_stored_actions

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    if data.get("solved") and data.get("solution_actions"):
        actions = parse_stored_actions(data["solution_actions"])
        end = opening.clone()
        g = replay_actions(end, actions)
        assert end.is_solved()
        assert g == data.get("replay_g") or g == data.get("solution_g")
        assert g < 192
        assert sum(1 for a in actions if is_deal(a)) == 5
        assert data.get("from_untouched_opening") is not False
