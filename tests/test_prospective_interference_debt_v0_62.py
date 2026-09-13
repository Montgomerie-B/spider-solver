"""Prospective interference-debt optimisation v0.62."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.autonomous_cost import COST_HARVEST_CATS, COST_LANES, INCUMBENT_MOVES
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.prospective_debt import (
    DEBT_HARVEST_CATS,
    DEBT_LANES,
    DebtTracker,
    choose_debt_verdict,
    debt_lane_keys,
    enrich_debt,
    search_debt_optimisation,
)
from spider.research_actions import apply_action, is_deal
from spider.structural_analysis import (
    durability_key,
    interference_debt,
    same_suit_component_spans,
)
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    LANES,
    _Top,
    harvest_portfolio,
    search_epoch_portfolio,
)

ROOT = Path(__file__).resolve().parents[1]
STRUCT = ROOT / "src" / "spider" / "structural_analysis.py"
POLICY = ROOT / "src" / "spider" / "prospective_debt.py"
PACKED = ROOT / "src" / "spider" / "packed_state.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
COST = ROOT / "src" / "spider" / "autonomous_cost.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("spider.simple_"):
            names.append(node.module)
    return names


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    cols = []
    downs = list(down or [])
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _ka(suit: str):
    return [Card(suit, r) for r in range(13, 0, -1)]


def test_interference_is_pure_current_state():
    src = inspect.getsource(interference_debt)
    assert "paid_actions" not in src
    assert "lifecycle" not in src
    assert "physical_labels" not in src
    body = src.split('"""', 2)[-1]
    assert "history" not in body.lower()
    opening = opening_state()
    a = interference_debt(opening)
    b = interference_debt(opening)
    assert a == b
    assert a["boundaries_total"] == a["off_suit_boundaries"] + a["rank_break_boundaries"]


def test_same_state_two_histories_identical_debt():
    start = _columns([Card("s", 8)], [Card("h", 7)], [Card("h", 6)])
    path_a = start.clone()
    apply_action(path_a, (1, 0, 1))
    apply_action(path_a, (2, 0, 1))
    path_b = start.clone()
    apply_action(path_b, (2, 1, 1))
    apply_action(path_b, (1, 0, 2))
    assert pack_state(path_a) == pack_state(path_b)
    assert pack_whole_game_identity(path_a) == pack_whole_game_identity(path_b)
    da = interference_debt(path_a)
    db = interference_debt(path_b)
    assert da == db
    assert da["off_suit_boundaries"] == 1
    assert da["mixed_supports"] == 1
    assert da["accessible_boundaries"] == 1
    rebuilt = _columns([Card("s", 8), Card("h", 7), Card("h", 6)])
    assert interference_debt(rebuilt) == da


def test_mixed_suit_and_rank_break_and_layers():
    mixed = _columns([Card("s", 8), Card("h", 7)])
    d = interference_debt(mixed)
    assert d["off_suit_boundaries"] == 1
    assert d["rank_break_boundaries"] == 0
    assert d["accessible_boundaries"] == 1
    assert d["buried_boundaries"] == 0
    assert d["mixed_supports"] == 1
    assert d["visible_components"] == 2
    spans = same_suit_component_spans(mixed.columns[0].face_up)
    assert spans == [(0, 1), (1, 2)]

    broken = _columns([Card("s", 10), Card("s", 7)])
    r = interference_debt(broken)
    assert r["rank_break_boundaries"] == 1
    assert r["off_suit_boundaries"] == 0
    assert r["accessible_boundaries"] == 1

    stacked = _columns([Card("s", 13), Card("h", 12), Card("d", 11)])
    s = interference_debt(stacked)
    assert s["boundaries_total"] == 2
    assert s["accessible_boundaries"] == 1
    assert s["buried_boundaries"] == 1
    assert s["component_layers"] == 2
    assert s["max_layer_depth"] == 3
    assert s["buried_components"] == 2
    assert s["mixed_supports"] == 1


def test_empty_and_post_foundation_edges():
    empty = _columns()
    z = interference_debt(empty)
    assert z["boundaries_total"] == 0
    assert z["visible_components"] == 0
    assert z["mixed_supports"] == 0
    assert z["max_layer_depth"] == 0

    founded = _columns([Card("h", 5), Card("s", 4)], foundations=[_ka("c")])
    d = interference_debt(founded)
    assert d["foundations"] == 1
    assert d["off_suit_boundaries"] == 1
    key = durability_key(founded, 9)
    assert key[0] == -1
    assert key[-1] == 9


def test_durability_lane_order_and_no_history_cost():
    opening = opening_state()
    keys = debt_lane_keys(opening, 17)
    assert keys["cost"] == (17,)
    assert keys["durability"][0] == 0
    assert keys["durability"][-1] == 17
    assert keys["durability"] == durability_key(opening, 17)
    src = inspect.getsource(debt_lane_keys)
    assert "rehandle" not in src.lower()
    assert "effective_cost" not in src
    assert DEBT_LANES[-1] == "durability"
    assert "durability" not in COST_LANES
    assert LANES == ("cost", "reveal", "workspace", "construction", "readiness", "horizon")


def test_cost_conditioned_durability_harvest():
    tops = {cat: _Top() for cat in DEBT_HARVEST_CATS}
    tracker = DebtTracker()
    class_best = {}
    cheap = {
        "g": 40,
        "foundations": 1,
        "face_down": 8,
        "boundaries_total": 4,
        "component_layers": 2,
        "mixed_supports": 1,
        "n_ready": 1,
        "cover": 3,
        "bonds": 10,
        "empty_n": 0,
        "ordered_digest": "aa",
        "ident": "aa",
        "ready_edges": 1,
        "ready_cond": 5,
        "longest": 6,
    }
    dear = dict(cheap, g=55, ordered_digest="bb", ident="bb", boundaries_total=2)
    tracker(tops, cheap, 0, class_best)
    tracker(tops, dear, 0, class_best)
    dur = tops["durability"].best()
    assert dur
    assert dur[0]["ident"] == "bb"
    cheap_debt = tops["cheap_debt"].best()
    assert cheap_debt[0]["g"] == 40
    roots = [{"g": 0, "ident": "zz", "whole_game_identity": "zz", "ordered_digest": "00"}]
    inc = {"g": 2, "ident": "inc", "whole_game_identity": "inc", "ordered_digest": "11", "incumbent_control": True}
    picked, counts = harvest_portfolio(
        tops, roots, 0, width=24, cats=DEBT_HARVEST_CATS, incumbent=inc
    )
    assert counts.get("deal_now", 0) >= 1
    assert counts.get("incumbent", 0) == 1
    assert "durability" in DEBT_HARVEST_CATS
    assert "cheap_debt" in DEBT_HARVEST_CATS


def test_tt_semantics_and_ceiling_unchanged():
    packed = PACKED.read_text(encoding="utf-8")
    assert "interference" not in packed
    kernel = KERNEL.read_text(encoding="utf-8")
    assert "interference_debt" not in kernel
    src = inspect.getsource(search_debt_optimisation)
    assert "incumbent_g - 1" in src
    assert "harvest_slack=-1" in src
    assert "enrich_fn=enrich_debt" in src
    sched = inspect.getsource(search_epoch_portfolio)
    assert "lane_names: Sequence[str] = LANES" in sched
    assert "identity_fn=pack_whole_game_identity" in sched


def test_canonical_not_read_by_optimiser_and_incumbent_198():
    text = POLICY.read_text(encoding="utf-8")
    assert "4925153_canonical" not in text
    assert "canonical.moves" not in text
    assert _simple_imports(POLICY) == []
    assert _simple_imports(STRUCT) == []
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5
    rec = {"g": 3, "foundations": 0, "face_down": 10}
    enrich_debt(opening, rec)
    assert "boundaries_total" in rec
    assert rec["boundaries_total"] == rec["off_suit_boundaries"] + rec["rank_break_boundaries"]


def test_tiny_search_and_verdicts():
    opening = opening_state()
    res = search_debt_optimisation(
        opening=opening,
        max_unique=24,
        time_limit_s=1.5,
        rss_abort_mb=4096,
        portfolio_width=8,
    )
    assert res.accounting_fail is False
    assert res.candidate_ceiling == 197 or res.incumbent_g == 198
    v, _ = choose_debt_verdict(
        {
            "incumbent_g": 198,
            "solved": res.solved,
            "replay_ok": res.replay_ok,
            "solution_g": res.solution_g,
            "accounting_fail": res.accounting_fail,
        }
    )
    if not res.solved:
        assert v == "INTERFERENCE_DEBT_NO_GAIN"
    v2, _ = choose_debt_verdict(
        {"incumbent_g": 198, "solved": True, "replay_ok": True, "solution_g": 190}
    )
    assert v2 == "INTERFERENCE_DEBT_COST_IMPROVED"
    v3, _ = choose_debt_verdict(
        {"incumbent_g": 198, "rehandling_improved": True, "solved": False}
    )
    assert v3 == "INTERFERENCE_DEBT_REDUCES_REHANDLING_ONLY"
    assert "workspace" not in DEBT_LANES
    assert set(COST_LANES).issubset(DEBT_LANES)
    assert set(COST_HARVEST_CATS).issubset(DEBT_HARVEST_CATS)
