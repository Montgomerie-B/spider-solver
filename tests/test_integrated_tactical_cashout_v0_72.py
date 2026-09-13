"""Integrated strategic/tactical cash-out v0.72."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_policy import COMPLETION_LANES, MULTI_SUIT_LANES, assembly_lane_keys
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.foundation_cashout import search_foundation_cashout, select_tactical_target
from spider.integrated_policy import search_integrated_optimisation
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, dump_actions, is_deal, stock_rows, tableau_actions
from spider.tactical_integration import (
    ROWS1_AUGMENT_FRACTION,
    STRATEGIC_LANES,
    TACTICAL_PER_ROOT_UNIQUE,
    TACTICAL_PORTFOLIO_CAP,
    TACTICAL_ROOT_LIMIT,
    cap_tactical_representation,
    choose_integrated_tactical_verdict,
    rows1_cashout_augment,
    search_integrated_tactical,
    select_tactical_probe_roots,
    strategic_lane_keys,
)
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import (
    AUGMENT_FRACTION,
    search_epoch_portfolio,
)
from spider.search_kernel import run_search

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "tactical_integration.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
SCRIPT = ROOT / "research" / "integrated_tactical_cashout_v0_72.py"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _stock_row(suit: str = "h"):
    return [Card(suit, r) for r in range(1, 11)]


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def _root(state: SpiderState, g: int = 0, **meta) -> dict:
    rec = {
        "g": g,
        "ordered_digest": pack_state(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "ident": pack_whole_game_identity(state).hex(),
        "full_actions": [],
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "face_down": sum(len(c.face_down) for c in state.columns),
        "empty_n": sum(1 for c in state.columns if c.is_empty()),
        "n_ready": rank_ready_suits(state, g=g)["n_ready"],
        "legal_tableau": len(tableau_actions(state)),
        "cover": (rank_ready_suits(state, g=g).get("best") or {}).get("cover"),
    }
    rec.update(meta)
    return rec


def test_active_lanes_drop_r2_r3_and_match_completion():
    assert STRATEGIC_LANES == COMPLETION_LANES
    assert "readiness_r2" not in STRATEGIC_LANES
    assert "readiness_r3" not in STRATEGIC_LANES
    assert "completion" in STRATEGIC_LANES
    assert "economy" in STRATEGIC_LANES
    src = inspect.getsource(strategic_lane_keys)
    assert "readiness_r2" not in src
    assert "readiness_r3" not in src
    opening = opening_state()
    keys = strategic_lane_keys(opening, 0)
    assert keys["completion"] is None
    assert "readiness_r2" not in keys
    two = _columns(_run("c", 13, 1), _run("d", 13, 1), stock=_stock_row())
    k1 = strategic_lane_keys(two, 9)
    assert stock_rows(two) == 1
    assert k1["completion"] is None
    assert k1["readiness"] is not None
    hist = assembly_lane_keys(two, 9)
    assert hist["readiness_r2"] is not None
    src_s = inspect.getsource(search_integrated_tactical)
    assert "STRATEGIC_LANES" in src_s or "COMPLETION_LANES" in src_s
    assert "MULTI_SUIT_LANES" not in src_s
    assert "readiness_r2" in MULTI_SUIT_LANES


def test_v070_integrated_search_still_uses_multi_suit():
    src = inspect.getsource(search_integrated_optimisation)
    assert "MULTI_SUIT_LANES" in src


def test_no_suit_literals_or_canonical_in_policy():
    for path in (MOD, SCHED, KERNEL):
        text = _text(path)
        assert "4925153_canonical.moves" not in text
    src = inspect.getsource(rows1_cashout_augment) + inspect.getsource(select_tactical_probe_roots)
    src += inspect.getsource(search_integrated_tactical) + inspect.getsource(strategic_lane_keys)
    lower = src.lower()
    for word in ("diamonds", "hearts", "spades", "clubs"):
        assert word not in lower
    assert "g=128" not in src
    assert "g=130" not in src
    tree = ast.parse(_text(MOD))
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    kern = _text(KERNEL)
    assert "search_foundation_cashout" not in kern
    assert "tactical_integration" not in kern


def test_generic_target_and_rows1_only():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    ranked = rank_ready_suits(st, g=5)
    chosen = select_tactical_target(st, 5)
    assert chosen["suit"] == ranked["best"]["suit"]
    src = inspect.getsource(rows1_cashout_augment)
    assert "select_tactical_target" in src
    assert 'int(rows) != 1' in src or "rows) != 1" in src
    empty = rows1_cashout_augment(2, [], 4.0, {})
    assert empty["n_probes"] == 0
    assert empty["attached"] == []


def test_probe_root_selection_is_category_diverse_max_eight():
    assert TACTICAL_ROOT_LIMIT == 8
    assert TACTICAL_PER_ROOT_UNIQUE == 20_000
    cats = [
        "incumbent",
        "readiness",
        "cheap_viable",
        "cheap",
        "cheap",
        "cheap",
        "economy",
        "construction",
        "pareto",
        "post_deal_mobility",
        "deal_now",
    ]
    rows = []
    for i, cat in enumerate(cats):
        rows.append(
            {
                "g": 100 + i,
                "ident": f"id{i}",
                "ordered_digest": f"d{i}",
                "stock_rows": 1,
                "n_ready": 1,
                "full_actions": [],
                "portfolio_cat": cat,
                "face_down": 2,
                "foundations": 1,
            }
        )
    picked = select_tactical_probe_roots(rows, limit=8, cost_ceiling=191)
    assert len(picked) == 8
    picked_cats = [r["portfolio_cat"] for r in picked]
    assert "incumbent" in picked_cats
    assert "readiness" in picked_cats
    assert picked_cats.count("cheap") <= 2
    assert not all(c == "cheap" for c in picked_cats)
    over = select_tactical_probe_roots(rows, cost_ceiling=99)
    assert over == []
    none = select_tactical_probe_roots([{**rows[0], "n_ready": 0, "ident": "x"}])
    assert none == []
    too_many = select_tactical_probe_roots(rows * 3, limit=8)
    assert len(too_many) <= 8


def test_scheduler_hook_default_unchanged_and_split_at_rows1():
    assert ROWS1_AUGMENT_FRACTION == AUGMENT_FRACTION == 0.25
    src = inspect.getsource(search_epoch_portfolio)
    assert "epoch_augment_fn=None" in src
    assert "will_augment" in src
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    root = _root(st, g=10)
    calls = []

    def hook(rows, roots, budget_s, context):
        calls.append({"rows": rows, "budget_s": budget_s, "n": len(roots), "unique": context.get("unique_budget")})
        return {"attached": [], "n_probes": 0, "unique": 0, "expanded": 0, "elapsed_s": 0.0}

    res = search_epoch_portfolio(
        initial_roots=[root],
        max_unique=80,
        time_limit_s=1.5,
        rss_abort_mb=2048,
        cost_ceiling=40,
        portfolio_width=8,
        epoch_augment_fn=hook,
        augment_fraction=0.25,
        augment_when=lambda rows, _r: int(rows) == 1,
    )
    assert calls
    assert all(c["rows"] == 1 for c in calls)
    ep = res.epochs[0]
    assert ep["stock_rows"] == 1
    assert ep["alloc_s_strategic"] < ep["alloc_s"]
    assert ep["augment"]["called"] is True
    plain = search_epoch_portfolio(
        initial_roots=[root],
        max_unique=40,
        time_limit_s=0.8,
        rss_abort_mb=2048,
        cost_ceiling=40,
        portfolio_width=8,
    )
    pep = plain.epochs[0]
    assert pep["augment"]["called"] is False
    assert pep["alloc_s_strategic"] == pep["alloc_s"]


def test_augment_feeds_cashout_terminals_before_deal():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    root = _root(st, g=7)
    target = select_tactical_target(st, 7)
    raw = rows1_cashout_augment(
        1,
        [root],
        2.0,
        {"unique_budget": 400, "rss_abort_mb": 2048, "epoch_ceil": 30},
    )
    assert raw["n_probes"] >= 1
    assert raw["n_found"] >= 1
    assert raw["attached"]
    term = raw["attached"][0]
    assert term["portfolio_cat"] == "tactical_cashout"
    assert int(term["foundations"]) >= 1
    assert term["tactical_target"] == target["suit"]
    end = st.clone()
    delta = replay_actions(end, as_actions(term["full_actions"]))
    assert 7 + delta == term["g"]
    assert pack_state(end).hex() == term["ordered_digest"]
    assert not any(is_deal(a) for a in as_actions(term["full_actions"]))
    assert stock_rows(end) == 1
    assert term.get("preview") or term.get("deal_preview")
    assert term["root_g"] == 7
    assert "tactical_cashout" in (term.get("lineage") or [])


def test_cheapest_g_tt_and_corrected_mw_untouched():
    src = inspect.getsource(run_search)
    assert "child_g >= prev" in src
    src_s = inspect.getsource(search_epoch_portfolio)
    assert "pack_whole_game_identity" in src_s
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    assert pack_state(st) == pack_whole_game_identity(st)
    res = search_foundation_cashout(
        root_state=st,
        root_g=4,
        target_suit="c",
        max_unique=200,
        time_limit_s=1.5,
        cost_ceiling=20,
        skip_preview=True,
    )
    assert res.found
    assert res.portfolio and res.portfolio[0].get("actions")


def test_script_eval_after_search_and_regressions():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_integrated_tactical(")
        eval_at = script.find("EVAL canonical")
        assert search_at != -1
        assert eval_at > search_at
        assert "900" in script
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    v, _ = choose_integrated_tactical_verdict(
        {"solved": True, "replay_ok": True, "solution_g": 180, "incumbent_g": 192}
    )
    assert v == "TACTICAL_INTEGRATION_COST_IMPROVED"
    v2, _ = choose_integrated_tactical_verdict(
        {
            "best_presd5_f2": {
                "g": 128,
                "stock_rows": 1,
                "F": 2,
                "portfolio_cat": "tactical_cashout",
                "tactical_target": "x",
            },
            "tactical": {"n_terminals": 4, "n_found": 2},
            "incumbent_g": 192,
        }
    )
    assert v2 == "TACTICAL_INTEGRATION_REACHES_PRESD5_F2"
    src = inspect.getsource(search_integrated_tactical)
    assert "search_foundation_cashout" not in src
    assert "4925153_autonomous_v0_71" not in _text(MOD)
    assert "bounded_foundation_cashout_v0_71_continuation" not in _text(MOD)


def test_tactical_cap_and_ordinary_roots_retained():
    ordinary = [
        {"ident": f"o{i}", "g": 120, "portfolio_cat": "deal_now", "lineage": []}
        for i in range(5)
    ]
    ordinary.append({"ident": "inc", "g": 123, "portfolio_cat": "incumbent", "lineage": []})
    tacs = [
        {
            "ident": f"t{i}",
            "g": 128 + i,
            "portfolio_cat": "tactical_cashout",
            "lineage": ["tactical_cashout"],
            "post_assembly_f": 160 + i,
        }
        for i in range(80)
    ]
    mixed = cap_tactical_representation(ordinary + tacs, cap=64)
    assert TACTICAL_PORTFOLIO_CAP == 64
    assert any(r["portfolio_cat"] == "deal_now" for r in mixed)
    assert any(r["portfolio_cat"] == "incumbent" for r in mixed)
    n_tac = sum(1 for r in mixed if r["portfolio_cat"] == "tactical_cashout")
    assert n_tac == 64
    assert len(mixed) == 6 + 64


def test_incremental_pareto_and_assembly_bound_frozen():
    from spider.final_deal_transition import TransitionTracker
    from spider.assembly_lower_bound import stock_empty_assembly_h

    src = inspect.getsource(TransitionTracker.finalize)
    assert "front.members" in src or "self.front" in src
    src_s = inspect.getsource(search_integrated_tactical)
    assert "stock_empty_assembly_h" in src_s
    assert "TransitionTracker" in src_s
    opening = opening_state()
    assert stock_empty_assembly_h(opening, 0) == 0
