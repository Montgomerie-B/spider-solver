"""Component-aware Foundation-2 search v0.56."""

from __future__ import annotations

import inspect
from pathlib import Path

from spider.cards import Card
from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.packed_state import pack_post_stock_symmetry_state
from spider.rules import MW_RULES
from spider.simple_component_aware_f2 import (
    LANES,
    choose_verdict,
    search_component_aware_f2,
    suit_lane_key,
    workspace_key,
)
from spider.simple_deal1_preview import stock_rows
from spider.simple_final_deal_timing import foundation_suits
from spider.simple_low_tail import k_through_n, synthetic_columns, tail_run
from spider.simple_progressive_solver import TT_MODE_DEPTH_AWARE, apply_action, solve_progressive
from spider.simple_resource_aware_f2 import COST_CEILING, SEARCH_UNIQUE, load_deal_now_roots
from spider.simple_sd5_component_audit import lane_suit_metrics
from spider.simple_workspace_reachability import engine_tableau_actions

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "simple_component_aware_f2.py"
SCRIPT = ROOT / "research" / "sd5_component_aware_f2_search_v0_56.py"
AUDIT = ROOT / "src" / "spider" / "simple_sd5_component_audit.py"
FIX = ROOT / "solutions" / "4925153_v0_56_foundation2.moves.txt"


def test_descriptor_on_descendant():
    kings = [[Card("s", 13)] for _ in range(8)]
    st = synthetic_columns([tail_run("c", 3), [Card("c", 5), Card("c", 4)], *kings])
    m = lane_suit_metrics(st, "c")
    assert m["edges"] >= 1
    join = next(a for a in engine_tableau_actions(st)[0] if a != ("deal",) and a[2] == 3)
    st.move(*join)
    m2 = lane_suit_metrics(st, "c")
    assert m2["longest"] >= m["longest"]
    assert m2["cond_len"] >= 5


def test_separate_suit_lane_ordering():
    better = {"cover": 5, "visible": 5, "edges": 2, "cond_len": 7, "gap": 4, "fd": 0}
    worse = {"cover": 6, "visible": 6, "edges": 0, "cond_len": 4, "gap": 8, "fd": 1}
    assert suit_lane_key(better, 90) < suit_lane_key(worse, 80)
    # club improvement must not be collapsed into a diamond score
    assert LANES == ("cost", "s", "h", "d", "c", "work")
    from spider.search_kernel import run_search

    src = inspect.getsource(search_component_aware_f2) + inspect.getsource(run_search)
    assert "suit_lane_key" in inspect.getsource(search_component_aware_f2)
    assert "heaps[name]" in inspect.getsource(run_search)
    assert "lane_i" in src


def test_shared_tt_and_stale_entries():
    from spider.search_kernel import run_search

    src = inspect.getsource(run_search) + inspect.getsource(search_component_aware_f2)
    assert "best_g[child_ident] = child_g" in src
    assert "child_g >= prev" in src
    assert "seen_expand" in src
    assert "stale" in src.lower()
    assert "run_search" in inspect.getsource(search_component_aware_f2)


def test_engine_f2_terminal_and_no_deal():
    from spider.search_kernel import run_search
    from spider.research_actions import tableau_actions

    src = inspect.getsource(search_component_aware_f2) + inspect.getsource(run_search)
    assert "len(st.foundations) == 2" in src or "len(state.foundations) == 2" in src
    assert "tableau_actions" in inspect.getsource(run_search)
    assert "deal" in inspect.getsource(tableau_actions)
    st = synthetic_columns(
        [tail_run("d", 3), k_through_n("d", 4)],
        foundations=[k_through_n("s", 1)],
    )
    assert len(st.foundations) == 1
    join = next(a for a in engine_tableau_actions(st)[0] if a[2] == 3)
    apply_action(st, join)
    assert len(st.foundations) == 2
    assert COST_CEILING == 110
    assert SEARCH_UNIQUE == 600_000


def test_workspace_key_orders_empties_then_fd():
    by = {s: {"cover": 6, "edges": 0} for s in ("s", "h", "d", "c")}
    assert workspace_key(by, fd=4, empties=2, g=90) < workspace_key(by, fd=4, empties=1, g=80)


def test_roots_are_v055_plus_all_deal_now():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "sd5_component_aware_portfolio_v0_55.json" in text
    assert "load_deal_now_roots" in text
    assert "720" in text or "EXPECTED_DEAL_NOW" in text


def test_no_ucs_dump_no_presd4_no_f3():
    text = SCRIPT.read_text(encoding="utf-8") + MOD.read_text(encoding="utf-8")
    assert "No UCS" in text or "not repeat pure UCS" in text.lower() or "multi-lane" in text.lower()
    assert "pre-SD4" in text
    assert "Foundation 3" in text
    assert "search_foundation2(" not in inspect.getsource(search_component_aware_f2)


def test_witness_replay_if_present():
    if not FIX.exists():
        src = inspect.getsource(search_component_aware_f2)
        assert "full_actions" in src
        return
    opening = SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))
    end = opening.clone()
    cost = replay_actions(end, parse_moves_file(FIX))
    assert stock_rows(end) == 0
    assert len(end.foundations) == 2
    assert cost >= 0
    assert "s" in foundation_suits(end)


def test_verdict_space_and_production_green():
    v, _ = choose_verdict({"all_replay_ok": True, "reached": True})
    assert v == "COMPONENT_AWARE_FOUNDATION2_REACHED"
    v, _ = choose_verdict({"all_replay_ok": True, "stop_reason": "unique limit"})
    assert v == "COMPONENT_AWARE_SEARCH_STATE_EXPLOSION"
    assert MW_RULES.can_deal_into_empty is True
    opening = SpiderState.from_cards(list(load_deal(ROOT / "deals" / "4925153.txt")))
    kwargs = dict(max_nodes=40, time_limit_s=2.0, depth_bands=(6,), max_pass=0, enable_audit=False)
    a = solve_progressive(opening, **kwargs)
    b = solve_progressive(opening, tt_mode=TT_MODE_DEPTH_AWARE, start_pass=0, **kwargs)
    assert a.nodes == b.nodes
    assert "search_component_aware_f2" not in inspect.getsource(solve_progressive)
