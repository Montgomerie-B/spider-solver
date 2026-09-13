"""Material-horizon epoch-portfolio scheduler v0.59."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import apply_action, is_deal, stock_deal_rows, stock_rows, tableau_actions
from spider.search_kernel import SearchLimits, run_search
from spider.structural_analysis import (
    SUITS,
    foundation_readiness,
    next_foundation_material,
    suit_material_horizon,
)
from spider.whole_game_epoch_scheduler import (
    LANES,
    PORTFOLIO_WIDTH,
    allocate_budget,
    choose_verdict,
    epoch_lane_keys,
    harvest_portfolio,
    opening_state,
    search_epoch_portfolio,
)
from spider.whole_game_anytime import opening_root

ROOT = Path(__file__).resolve().parents[1]
GENERIC = (
    ROOT / "src" / "spider" / "structural_analysis.py",
    ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py",
    ROOT / "src" / "spider" / "research_actions.py",
    ROOT / "src" / "spider" / "search_kernel.py",
)
ADAPTER = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("spider.simple_"):
            names.append(node.module)
    return names


def _columns(*runs, foundations=None, stock=None) -> SpiderState:
    cols = [Column([], list(run)) for run in runs]
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _ka(suit: str) -> list[Card]:
    return [Card(suit, r) for r in range(13, 0, -1)]


def test_no_simple_imports():
    for path in GENERIC:
        assert _simple_imports(path) == [], path.name
    assert "simple_foundation_horizon" not in ADAPTER.read_text(encoding="utf-8")


def test_stock_deal_rows_match_engine():
    opening = opening_state()
    rows = stock_deal_rows(opening.stock)
    assert len(rows) == 5
    assert rows[0] == list(opening.stock[-10:])
    clone = opening.clone()
    apply_action(clone, ("deal",))
    assert [col.face_up[-1] for col in clone.columns] == rows[0]


def test_material_horizon_arbitrary_and_after_foundation():
    # Tableau has a full club set; hearts missing Ace until first deal.
    clubs = _ka("c")
    hearts = [Card("h", r) for r in range(13, 1, -1)]  # K-2, no Ace
    stock = [Card("h", 1)] + [Card("d", 5)] * 9
    st = _columns(clubs, hearts, stock=stock)
    c = suit_material_horizon(st, "c")
    h = suit_material_horizon(st, "h")
    assert c["material_complete_now"] is True
    assert c["deals_until_material"] == 0
    assert h["material_complete_now"] is False
    assert h["deals_until_material"] == 1
    assert 1 in h["missing_ranks"]
    founded = _columns(
        [Card("c", r) for r in range(13, 1, -1)],
        foundations=[_ka("c")],
        stock=[Card("c", 1)] + [Card("s", 5)] * 9,
    )
    nxt = suit_material_horizon(founded, "c")
    assert nxt["founded"] == 1
    assert nxt["material_complete_now"] is False
    assert nxt["deals_until_material"] == 1
    assert nxt["another_possible"] is True
    done = _columns(foundations=[_ka("c"), _ka("c")], stock=[])
    over = suit_material_horizon(done, "c")
    assert over["another_possible"] is False
    assert over["material_complete_now"] is False


def test_readiness_no_fabricated_cover_and_ties():
    hearts = [Card("h", r) for r in range(13, 1, -1)]
    spades = [Card("s", r) for r in range(13, 1, -1)]
    stock = [Card("h", 1), Card("s", 1)] + [Card("d", 6)] * 8
    st = _columns(hearts, spades, stock=stock)
    r = foundation_readiness(st)
    assert r["n_ready"] == 0
    assert set(r["nearest_suits"]) == {"s", "h"}
    assert r["nearest_horizon"] == 1
    assert r["by_suit"]["s"]["cover"] is None
    assert r["by_suit"]["h"]["operational"] is False
    clubs = _ka("c")
    ready = _columns(clubs, stock=[])
    r2 = foundation_readiness(ready)
    assert "c" in r2["ready_suits"]
    assert r2["best_ready"]["operational"] is True
    assert r2["best_ready"]["cover"] is not None


def test_4925153_opening_horizons_are_independent_regression():
    mat = next_foundation_material(opening_state())
    got = {s: mat["by_suit"][s]["deals_until_material"] for s in SUITS}
    assert got == {"s": 2, "h": 2, "d": 4, "c": 5}
    assert mat["n_ready"] == 0
    assert set(mat["nearest_suits"]) == {"s", "h"}
    assert mat["nearest_horizon"] == 2


def test_sparse_lane_participation():
    opening = opening_state()
    root = opening_root(opening)

    def keys(state, g):
        return {"cost": (g,), "ready": None}

    kr = run_search(
        [root],
        limits=SearchLimits(max_unique=12, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=5),
        identity_fn=pack_whole_game_identity,
        actions_fn=tableau_actions,
        lane_names=("cost", "ready"),
        lane_keys_fn=keys,
        is_terminal=lambda st: False,
    )
    assert kr.lane_pops["ready"] == 0
    assert kr.lane_exp["ready"] == 0
    assert kr.lane_exp["cost"] >= 1
    assert kr.unique >= 2


def test_epoch_lanes_skip_meaningless_side():
    opening = opening_state()
    keys = epoch_lane_keys(opening, 0)
    assert keys["readiness"] is None
    assert keys["horizon"] is not None
    clubs = _ka("c")
    ready = _columns(clubs, stock=[])
    k2 = epoch_lane_keys(ready, 3)
    assert k2["readiness"] is not None
    assert k2["horizon"] is None
    assert LANES == ("cost", "reveal", "workspace", "construction", "readiness", "horizon")


def test_epoch_search_does_not_change_stock_rows():
    src = inspect.getsource(search_epoch_portfolio)
    assert "tableau_actions" in src
    assert "all_legal_actions" not in src
    opening = opening_state()
    rows = stock_rows(opening)
    res = search_epoch_portfolio(
        opening=opening,
        max_unique=30,
        time_limit_s=2.0,
        rss_abort_mb=4096,
        cost_ceiling=20,
        portfolio_width=8,
    )
    assert res.accounting_fail is False
    assert res.deal_illegal is False
    assert res.epochs
    assert res.epochs[0]["stock_rows"] == rows
    assert "deal_now_kept" in res.epochs[0]


def test_deal_transition_and_provenance():
    opening = opening_state()
    res = search_epoch_portfolio(
        opening=opening,
        max_unique=40,
        time_limit_s=3.0,
        rss_abort_mb=4096,
        cost_ceiling=20,
        portfolio_width=12,
    )
    assert len(res.epochs) >= 2
    nxt = res.epochs[1]
    assert nxt["stock_rows"] == 4
    assert nxt["input_roots"] >= 1
    first = res.epochs[0]
    assert first["after_deal_unique"] == nxt["input_roots"]
    # reconstruct a harvested deal-now path from epoch 0 via a later root
    assert res.unique == sum(ep["unique"] for ep in res.epochs)


def test_budget_is_cumulative_not_per_epoch_reset():
    assert allocate_budget(0, 1, 800_000, 900.0)[0] == 800_000
    u5, t5 = allocate_budget(5, 0, 800_000, 900.0)
    assert u5 < 800_000
    assert t5 < 900.0
    src = inspect.getsource(search_epoch_portfolio)
    assert "remaining_unique" in src


def test_synthetic_solve_replays_from_opening():
    foundations = [_ka(s) for s in ("s", "h", "d", "c", "s", "h", "d")]
    left = _ka("c")
    st = _columns(left[:10], left[10:], foundations=foundations, stock=[])
    assert not st.is_solved()
    res = search_epoch_portfolio(
        opening=st,
        max_unique=80,
        time_limit_s=3.0,
        rss_abort_mb=4096,
        cost_ceiling=30,
        portfolio_width=8,
    )
    assert res.solved is True
    assert res.replay_ok is True
    end = st.clone()
    replay_actions(end, res.solution_actions)
    assert end.is_solved()
    assert stock_rows(end) == 0


def test_verdict_space_and_firewall():
    v, _ = choose_verdict({"solved": True, "replay_ok": True})
    assert v == "EPOCH_PORTFOLIO_AUTONOMOUS_SOLVE"
    v, _ = choose_verdict({"max_foundations": 1})
    assert v == "EPOCH_PORTFOLIO_REDISCOVERS_F1"
    text = ADAPTER.read_text(encoding="utf-8")
    assert "canonical.moves" not in text
    assert "EXPECTED_FIRST" not in text
    assert PORTFOLIO_WIDTH == 256


def test_portfolio_width_and_deal_now_category():
    from spider.whole_game_epoch_scheduler import _Top, harvest_portfolio

    tops = {cat: _Top() for cat in (
        "cheap", "foundations", "min_fd", "workspace", "construction",
        "readiness", "horizon", "ready_div", "pareto", "deal_now",
    )}
    roots = [{"g": 0, "ident": "aa", "whole_game_identity": "aa", "ordered_digest": "00", "foundations": 0, "face_down": 40, "bonds": 0, "empty_n": 0}]
    picked, counts = harvest_portfolio(tops, roots, 0, width=16)
    assert counts.get("deal_now", 0) >= 1
    assert len(picked) >= 1
