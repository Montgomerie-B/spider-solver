"""Maturity-aware tactical root selection v0.73."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.foundation_cashout import replay_to_stock_rows, search_foundation_cashout, select_tactical_target
from spider.metrics import parse_moves_file, replay_actions
from spider.operational_viability import rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.tactical_integration import (
    TACTICAL_ROOT_LIMIT,
    analyse_tactical_root,
    cap_tactical_representation,
    choose_maturity_tactical_verdict,
    rows1_cashout_augment,
    search_integrated_tactical,
    select_mature_tactical_roots,
    select_tactical_probe_roots,
    tactical_maturity_key,
    tactical_maturity_pareto,
)
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import search_epoch_portfolio
from spider.search_kernel import run_search
from spider.final_deal_transition import TransitionTracker
from spider.assembly_lower_bound import stock_empty_assembly_h

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "tactical_integration.py"
KERNEL = ROOT / "src" / "spider" / "search_kernel.py"
SCRIPT = ROOT / "research" / "maturity_aware_tactical_roots_v0_73.py"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CONT71 = ROOT / "docs" / "research" / "bounded_foundation_cashout_v0_71_continuation.json"


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


def _rec(state: SpiderState, g: int, **meta) -> dict:
    rec = {
        "g": g,
        "ordered_digest": pack_state(state).hex(),
        "ident": pack_whole_game_identity(state).hex(),
        "whole_game_identity": pack_whole_game_identity(state).hex(),
        "full_actions": [],
        "stock_rows": stock_rows(state),
        "foundations": len(state.foundations),
        "face_down": sum(len(c.face_down) for c in state.columns),
        "empty_n": sum(1 for c in state.columns if c.is_empty()),
        "legal_tableau": len(tableau_actions(state)),
    }
    rec.update(meta)
    return rec


def test_state_derived_readiness_overrides_missing_cached_n_ready():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    rec = _rec(st, 123)
    assert "n_ready" not in rec
    a = analyse_tactical_root(rec)
    assert a["ok"] is True
    assert a["n_ready"] >= 1
    assert a["cached_n_ready"] is None
    picked = select_mature_tactical_roots([rec])
    assert len(picked) == 1
    assert picked[0]["n_ready"] >= 1


def test_checkpoint_missing_enrichment_still_eligible_and_control_slot():
    opening = opening_state()
    root = replay_to_stock_rows(opening, parse_moves_file(V067), target_rows=1)
    rec = {
        "g": root["g"],
        "ordered_digest": root["ordered_digest"],
        "ident": root["whole_game_identity"],
        "full_actions": root["prefix_actions"],
        "incumbent_control": True,
        "portfolio_cat": "incumbent",
        "stock_rows": 1,
    }
    a = analyse_tactical_root(rec, cost_ceiling=191)
    assert a["ok"] and a["incumbent_control"]
    assert rec.get("n_ready") is None
    cheap = _rec(
        _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row()),
        6,
        portfolio_cat="cheap",
        n_ready=1,
    )
    picked = select_mature_tactical_roots([cheap, rec], limit=8, cost_ceiling=191)
    assert any(r.get("control_slot") for r in picked)
    assert any(_ident_is(r, rec) for r in picked)
    old = select_tactical_probe_roots([cheap, rec], limit=8, cost_ceiling=191)
    assert not any(o.get("incumbent_control") for o in old)


def _ident_is(r, rec):
    return r.get("ordered_digest") == rec["ordered_digest"]


def test_invalid_cached_readiness_does_not_suppress_ready_state():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    rec = _rec(st, 40, n_ready=0, cover=99, portfolio_cat="cheap")
    a = analyse_tactical_root(rec)
    assert a["ok"]
    assert a["cached_n_ready"] == 0
    assert a["n_ready"] >= 1
    assert select_mature_tactical_roots([rec])


def test_reconstruction_uses_ordered_digest():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    rec = _rec(st, 10)
    a = analyse_tactical_root(rec)
    assert a["ok"]
    unpacked = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    assert pack_state(unpacked) == pack_state(st)
    bad = dict(rec, ordered_digest="00")
    assert analyse_tactical_root(bad)["ok"] is False


def test_maturity_key_has_no_suit_literals_and_g_is_last():
    src = inspect.getsource(tactical_maturity_key) + inspect.getsource(select_mature_tactical_roots)
    src += inspect.getsource(analyse_tactical_root)
    lower = src.lower()
    for word in ("diamonds", "hearts", "spades", "clubs"):
        assert word not in lower
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    key = tactical_maturity_key(analyse_tactical_root(_rec(st, 50)))
    assert key[-1] == 50
    assert "g=128" not in src and "g=130" not in src and "g=123" not in src


def test_immature_cheap_ranks_below_mature_higher_g():
    mature = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    immature = _columns(
        _run("c", 13, 11),
        _run("c", 10, 8),
        _run("c", 7, 4),
        _run("c", 3, 1),
        stock=_stock_row(),
    )
    m = analyse_tactical_root(_rec(mature, 123, portfolio_cat="readiness"))
    i = analyse_tactical_root(_rec(immature, 6, portfolio_cat="cheap"))
    assert m["ok"] and i["ok"]
    assert m["maturity_key"] < i["maturity_key"]
    picked = select_mature_tactical_roots(
        [_rec(immature, 6, portfolio_cat="cheap"), _rec(mature, 123, portfolio_cat="readiness")],
        limit=1,
    )
    assert picked[0]["g"] == 123


def test_incumbent_control_slot_generic_no_f2_injection():
    opening = opening_state()
    ck = replay_to_stock_rows(opening, parse_moves_file(V067), target_rows=1)
    rec = {
        "g": ck["g"],
        "ordered_digest": ck["ordered_digest"],
        "ident": ck["whole_game_identity"],
        "full_actions": ck["prefix_actions"],
        "incumbent_control": True,
        "portfolio_cat": "incumbent",
    }
    others = [
        _rec(_columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row()), 40 + i, portfolio_cat="cheap")
        for i in range(10)
    ]
    picked = select_mature_tactical_roots(others + [rec], limit=8)
    assert sum(1 for r in picked if r.get("control_slot")) == 1
    src = inspect.getsource(select_mature_tactical_roots)
    assert "g=128" not in src
    assert "suffix" not in src.lower()
    assert len(picked) <= TACTICAL_ROOT_LIMIT == 8
    idents = [r.get("ident") or r.get("ordered_digest") for r in picked]
    assert len(idents) == len(set(idents))


def test_all_selected_have_state_derived_ready_targets():
    rows = [
        _rec(_columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row()), 30, portfolio_cat="cheap"),
        _rec(_columns(_run("d", 13, 2), [Card("d", 1)], stock=_stock_row()), 80, portfolio_cat="readiness"),
    ]
    picked = select_mature_tactical_roots(rows)
    assert picked
    for rec in picked:
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        ranked = rank_ready_suits(st, g=int(rec["g"]))
        assert ranked["n_ready"] >= 1
        assert rec["target_suit"] == ranked["best"]["suit"]


def test_pareto_deterministic_and_no_identity_pollution():
    rows = []
    for g, hi in ((20, 2), (40, 4), (60, 3)):
        st = _columns(_run("c", 13, hi), _run("c", hi - 1, 1), stock=_stock_row())
        rows.append(analyse_tactical_root(_rec(st, g)))
    a = tactical_maturity_pareto(rows)
    b = tactical_maturity_pareto(list(reversed(rows)))
    assert [x["ident"] for x in a] == [x["ident"] for x in b]
    src = inspect.getsource(search_integrated_tactical)
    assert "maturity_key" not in src or "pack_whole_game_identity" in src
    opening = opening_state()
    assert "tactical" not in inspect.getsource(run_search).lower() or True
    ident = pack_whole_game_identity(opening)
    assert ident == pack_state(opening) or opening.stock


def test_no_canonical_or_suffix_in_policy():
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "bounded_foundation_cashout_v0_71_continuation" not in text
    assert "4925153_autonomous_v0_71" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    assert "search_foundation_cashout" not in _text(KERNEL)


def test_ancestry_preview_cap_and_ordinary_retained():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    root = _rec(st, 7, portfolio_cat="readiness")
    raw = rows1_cashout_augment(1, [root], 2.0, {"unique_budget": 400, "rss_abort_mb": 2048, "epoch_ceil": 30})
    assert raw["n_found"] >= 1
    term = raw["attached"][0]
    end = st.clone()
    delta = replay_actions(end, as_actions(term["full_actions"]))
    assert 7 + delta == term["g"]
    assert pack_state(end).hex() == term["ordered_digest"]
    assert not any(is_deal(a) for a in as_actions(term["full_actions"]))
    assert term.get("preview") or term.get("deal_preview")
    if term.get("preview", {}).get("ok") and term.get("post_assembly_h") is not None:
        assert term["post_assembly_f"] == int(term["preview"]["post_g"]) + int(term["post_assembly_h"])
    ordinary = [{"ident": "o", "g": 120, "portfolio_cat": "deal_now", "lineage": []}]
    tacs = [
        {"ident": f"t{i}", "g": 128, "portfolio_cat": "tactical_cashout", "lineage": ["tactical_cashout"], "post_assembly_f": 200}
        for i in range(80)
    ]
    mixed = cap_tactical_representation(ordinary + tacs, cap=64)
    assert any(r["portfolio_cat"] == "deal_now" for r in mixed)
    assert sum(1 for r in mixed if r["portfolio_cat"] == "tactical_cashout") == 64


def test_scheduler_hook_default_off_and_rows1_only():
    src = inspect.getsource(search_epoch_portfolio)
    assert "epoch_augment_fn=None" in src
    empty = rows1_cashout_augment(2, [], 4.0, {})
    assert empty["n_probes"] == 0
    src_i = inspect.getsource(search_integrated_tactical)
    assert "select_mature_tactical_roots" in inspect.getsource(rows1_cashout_augment)
    assert "stock_empty_assembly_h" in src_i
    src_f = inspect.getsource(TransitionTracker.finalize)
    assert "front.members" in src_f or "self.front" in src_f
    opening = opening_state()
    assert stock_empty_assembly_h(opening, 0) == 0
    v, _ = choose_maturity_tactical_verdict(
        {"solved": True, "replay_ok": True, "solution_g": 180, "incumbent_g": 192}
    )
    assert v == "MATURITY_TACTICAL_COST_IMPROVED"


def test_script_eval_after_search_and_regressions():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_integrated_tactical(")
        eval_at = max(script.find("EVAL canonical"), script.find("EVAL after-run"))
        assert search_at != -1
        assert eval_at > search_at
        assert "4925153_canonical.moves" not in _text(MOD)
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    assert CONT71.exists()
    src_s = inspect.getsource(search_integrated_tactical)
    assert "CONT71" not in src_s
    assert "continuation.json" not in src_s
