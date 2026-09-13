"""Operational foundation viability v0.63."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.autonomous_cost import COST_LANES, INCUMBENT_MOVES
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_policy import (
    OP_HARVEST_CATS,
    OP_LANES,
    choose_operational_verdict,
    operational_lane_keys,
    search_operational_optimisation,
)
from spider.operational_viability import (
    foundation_operational_viability,
    operational_viability_key,
    rank_ready_suits,
)
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.prospective_debt import DEBT_LANES
from spider.research_actions import apply_action, is_deal
from spider.structural_analysis import INF, foundation_readiness
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import LANES, search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "src" / "spider" / "operational_policy.py"
VIAB = ROOT / "src" / "spider" / "operational_viability.py"
PACKED = ROOT / "src" / "spider" / "packed_state.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _ka(suit: str):
    return _run(suit, 13, 1)


def test_material_ready_high_vs_low_burden_ordering():
    low = _run("c", 13, 7)
    low_a = _run("c", 6, 1)
    buried_h = _run("h", 13, 4)
    st = _columns(
        low,
        low_a,
        buried_h + [Card("s", 9), Card("d", 8), Card("s", 7)],
        down=[
            [],
            [],
            [Card("h", 1), Card("h", 2), Card("h", 3)],
        ],
    )
    r = foundation_readiness(st)
    assert r["by_suit"]["c"]["material_complete_now"]
    assert r["by_suit"]["h"]["material_complete_now"]
    clubs = foundation_operational_viability(st, "c", readiness=r)
    hearts = foundation_operational_viability(st, "h", readiness=r)
    assert clubs["material_ready"] and hearts["material_ready"]
    assert clubs["global_fd"] == hearts["global_fd"]
    assert clubs["relevant_blockers"] < hearts["relevant_blockers"]
    assert clubs["max_blocker_depth"] < hearts["max_blocker_depth"]
    assert clubs["k_min_blockers"] < hearts["k_min_blockers"]
    assert operational_viability_key(clubs, 10) < operational_viability_key(hearts, 10)
    ranked = rank_ready_suits(st, readiness=r)
    assert ranked["best_suit"] == "c"
    assert "h" in ranked["ready_suits"]
    assert ranked["second_suit"] == "h"


def test_duplicate_anchor_contention_vs_independent_columns():
    tangled = _columns(
        [Card("c", 13), Card("h", 12), Card("c", 13)] + _run("c", 12, 7),
        _run("c", 6, 1),
    )
    split = _columns(
        [Card("c", 13)] + _run("c", 12, 7),
        [Card("c", 13)] + _run("c", 6, 1),
    )
    t = foundation_operational_viability(tangled, "c")
    s = foundation_operational_viability(split, "c")
    assert t["material_ready"] and s["material_ready"]
    assert t["anchor_contention"] >= 1
    assert s["anchor_contention"] == 0
    assert t["k_access"]["n"] >= 2 and s["k_access"]["n"] >= 2


def test_blocker_depth_and_suit_fd_burden():
    shallow = _columns(_run("d", 13, 1))
    deep = _columns(
        _run("d", 13, 5),
        down=[[Card("d", 4), Card("d", 3), Card("d", 2), Card("d", 1), Card("s", 12)]],
    )
    a = foundation_operational_viability(shallow, "d")
    b = foundation_operational_viability(deep, "d")
    assert a["suit_fd"] == 0
    assert b["suit_fd"] == 4
    assert b["max_blocker_depth"] > a["max_blocker_depth"]
    assert b["relevant_blockers"] > a["relevant_blockers"]
    assert a["k_access"]["exposed"] >= 0
    assert a["exposed_components"] >= 1


def test_mobility_and_component_access():
    mergeable = _columns(_run("s", 13, 8), _run("s", 7, 1))
    v = foundation_operational_viability(mergeable, "s")
    assert v["legal_merge_edges"] >= 1
    assert v["movable_exposed"] >= 1
    assert v["empty_n"] >= 1
    blocked = _columns(
        _run("s", 13, 8),
        _run("s", 7, 1) + [Card("h", 6)],
    )
    w = foundation_operational_viability(blocked, "s")
    assert w["legal_merge_edges"] == 0
    assert w["inaccessible_joins"] >= v["inaccessible_joins"]


def test_viability_is_state_local():
    start = _columns(_run("c", 13, 8), [Card("c", 7)], [Card("c", 6)])
    a = start.clone()
    apply_action(a, (1, 0, 1))
    apply_action(a, (2, 0, 1))
    b = start.clone()
    apply_action(b, (2, 1, 1))
    apply_action(b, (1, 0, 2))
    assert pack_state(a) == pack_state(b)
    assert pack_whole_game_identity(a) == pack_whole_game_identity(b)
    assert foundation_operational_viability(a, "c") == foundation_operational_viability(b, "c")
    src = inspect.getsource(foundation_operational_viability)
    assert "paid_actions" not in src
    assert "canonical" not in src


def test_no_suit_names_or_fd_threshold_in_policy():
    text = POLICY.read_text(encoding="utf-8")
    assert "4925153_canonical" not in text
    assert "canonical.moves" not in text
    assert "fd <= 8" not in text
    assert "fd > 12" not in text
    assert "hearts" not in text.lower()
    assert "spades" not in text.lower()
    body = VIAB.read_text(encoding="utf-8")
    assert "fd <= 8" not in body
    assert "4925153_canonical" not in body
    assert _simple_imports(POLICY) == []
    assert _simple_imports(VIAB) == []


def test_readiness_inactive_before_material_and_all_ready_evaluated():
    opening = opening_state()
    keys = operational_lane_keys(opening, 4)
    r = foundation_readiness(opening)
    if r["n_ready"] == 0:
        assert keys["readiness"] is None
        assert keys["horizon"] is not None
    st = _columns(_run("c", 13, 1), _run("d", 13, 1))
    keys2 = operational_lane_keys(st, 9)
    assert keys2["readiness"] is not None
    assert keys2["horizon"] is None
    ranked = rank_ready_suits(st)
    assert set(ranked["ready_suits"]) >= {"c", "d"}
    assert ranked["best"] is not None
    assert ranked["second"] is not None
    assert ranked["best_suit"] != ranked["second_suit"]


def test_durability_removed_tt_ceiling_incumbent():
    assert "durability" not in OP_LANES
    assert OP_LANES == COST_LANES
    assert "durability" in DEBT_LANES
    assert "cheap_debt" not in OP_HARVEST_CATS
    assert "cheap_viable" in OP_HARVEST_CATS
    assert "cheap_fd" in OP_HARVEST_CATS
    assert LANES == ("cost", "reveal", "workspace", "construction", "readiness", "horizon")
    packed = PACKED.read_text(encoding="utf-8")
    assert "operational_viability" not in packed
    assert "interference_debt" not in KERNEL.read_text(encoding="utf-8")
    src = inspect.getsource(search_operational_optimisation)
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    end = opening.clone()
    assert replay_actions(end, actions) == 198
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5
    sched = inspect.getsource(search_epoch_portfolio)
    assert "lane_names: Sequence[str] = LANES" in sched
    assert "identity_fn=pack_whole_game_identity" in sched


def test_tiny_search_and_verdicts():
    opening = opening_state()
    res = search_operational_optimisation(
        opening=opening,
        max_unique=24,
        time_limit_s=1.5,
        rss_abort_mb=4096,
        portfolio_width=8,
    )
    assert res.accounting_fail is False
    assert res.incumbent_g == 198
    v, _ = choose_operational_verdict(
        {
            "incumbent_g": 198,
            "solved": res.solved,
            "replay_ok": res.replay_ok,
            "solution_g": res.solution_g,
            "accounting_fail": res.accounting_fail,
        }
    )
    if not res.solved:
        assert v == "OPERATIONAL_VIABILITY_NO_GAIN"
    v2, _ = choose_operational_verdict(
        {"incumbent_g": 198, "solved": True, "replay_ok": True, "solution_g": 190}
    )
    assert v2 == "OPERATIONAL_VIABILITY_COST_IMPROVED"
    v3, _ = choose_operational_verdict({"incumbent_g": 198, "lineage_improved": True})
    assert v3 == "OPERATIONAL_VIABILITY_IMPROVES_LINEAGE"
    keys = operational_lane_keys(opening, 3)
    assert keys["cost"] == (3,)
    assert "workspace" not in keys or keys.get("workspace") is None
