"""Healthy F2 cost-to-go isolation v0.65."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.healthy_f1 import verify_f1_prefix
from spider.healthy_f2 import (
    CANDIDATE_CEILING,
    F2_FD,
    F2_G,
    F2_N,
    F2_ROWS,
    F2_SUITS,
    REMAINING_BUDGET,
    f2_abort,
    load_v064_f1_prefix,
    parse_stored_actions,
    verify_f2_prefix,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import OP_LANES, search_operational_optimisation
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import is_deal
from spider.whole_game_anytime import opening_root, opening_state
from spider.whole_game_epoch_scheduler import search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "healthy_f2.py"
OP = ROOT / "src" / "spider" / "operational_policy.py"
SCRIPT = ROOT / "research" / "healthy_f2_cost_to_go_v0_65.py"
ARTEFACT = ROOT / "docs" / "research" / "healthy_f2_cost_to_go_v0_65.json"
INCUMBENT = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_no_canonical_no_new_heuristic_remaining_budget():
    for path in (MOD, OP):
        text = _text(path)
        assert "4925153_canonical.moves" not in text or path == MOD
        assert "durability_key" not in text
    # evaluation-only helper may mention canonical path as a constant
    assert "search_operational_optimisation" in _text(MOD)
    src = inspect.getsource(search_operational_optimisation)
    assert "operational_lane_keys" in src
    assert "durability" not in OP_LANES
    assert REMAINING_BUDGET == 67
    assert CANDIDATE_CEILING == 197
    assert F2_G + REMAINING_BUDGET == CANDIDATE_CEILING
    assert F2_SUITS == frozenset({"s", "d"})
    if SCRIPT.exists():
        st = _text(SCRIPT)
        # search call must not parse canonical
        assert "search_f2_continuation" in st


def test_canonical_comparison_is_after_search_only():
    src = inspect.getsource(__import__("spider.healthy_f2", fromlist=["canonical_f2_snapshot"]).canonical_f2_snapshot)
    assert "parse_moves_file" in src
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_f2_continuation(")
        canon_at = script.find("canonical_f2_snapshot(")
        assert search_at != -1
        assert canon_at > search_at
        assert "EVAL canonical F2 after search" in script


def test_f2_abort_and_identity_untouched():
    rec = {
        "foundations": 2,
        "g": 130,
        "face_down": 2,
        "stock_rows": 1,
        "foundation_suits": ["s", "d"],
    }
    assert f2_abort(None, rec) is True
    assert f2_abort(None, dict(rec, g=131)) is False
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    root = opening_root(opening)
    root["lineage"] = ["v064_f2_g130"]
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident


def test_absolute_g_and_ceiling_from_f2_root():
    opening = opening_state()
    root = opening_root(opening)
    root["g"] = 130
    res = search_epoch_portfolio(
        opening=opening,
        initial_roots=[root],
        max_unique=12,
        time_limit_s=1.0,
        rss_abort_mb=4096,
        cost_ceiling=197,
        portfolio_width=8,
    )
    assert res.min_g is None or res.min_g >= 130
    assert res.candidate_ceiling == 197


def test_v064_f1_prefix_replays():
    actions = load_v064_f1_prefix()
    assert actions
    opening = opening_state()
    snap = verify_f1_prefix(opening, actions)
    assert snap["replay_ok"]
    assert snap["g"] == 71
    assert snap["foundations"] == 1


def test_incumbent_198_and_f2_artefact_if_present():
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert sum(1 for a in actions if is_deal(a)) == 5
    if not ARTEFACT.exists():
        return
    import json

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    raw = data.get("f2_prefix_actions")
    if not raw:
        return
    snap = verify_f2_prefix(opening, parse_stored_actions(raw))
    assert snap["replay_ok"]
    assert snap["g"] == 130
    assert snap["stock_rows"] == 1
    assert snap["face_down"] == 2
    assert snap["foundations"] == 2
    assert set(snap["suits"]) == {"s", "d"}
    if data.get("f2_digest"):
        assert snap["ordered_digest"] == data["f2_digest"]
    if data.get("solved") and data.get("solution_actions"):
        term = opening.clone()
        g = replay_actions(term, parse_stored_actions(data["solution_actions"]))
        assert term.is_solved()
        assert g == data.get("replay_g") or g == data.get("solution_g")
