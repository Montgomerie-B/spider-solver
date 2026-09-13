"""Incumbent-aware autonomous cost optimisation v0.60."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.autonomous_cost import (
    COST_HARVEST_CATS,
    COST_LANES,
    INCUMBENT_MOVES,
    checkpoints_from_trace,
    choose_cost_verdict,
    cost_lane_keys,
    cost_pareto_vec,
    epoch_savings_table,
    load_machine_incumbent,
    replay_solution_trace,
    search_cost_optimisation,
    structural_class_key,
)
from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.metrics import parse_moves_file, replay_actions
from spider.research_actions import is_deal, step_cost
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import harvest_portfolio, search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "autonomous_cost.py"
SCRIPT = ROOT / "research" / "autonomous_cost_optimisation_v0_60.py"


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


def _ka(suit: str):
    return [Card(suit, r) for r in range(13, 0, -1)]


def test_no_simple_or_canonical_policy():
    assert _simple_imports(MOD) == []
    text = MOD.read_text(encoding="utf-8")
    assert "canonical.moves" not in text
    assert "4925153_canonical" not in text
    if SCRIPT.exists():
        st = SCRIPT.read_text(encoding="utf-8")
        # after-run evaluation may mention 172; search call must not load canonical
        assert "parse_moves_file" in st or "INCUMBENT" in st


def test_incumbent_replay_and_epoch_prefix_costs():
    opening = opening_state()
    actions = parse_moves_file(INCUMBENT_MOVES)
    end = opening.clone()
    cost = replay_actions(end, actions)
    assert cost == 198
    assert end.is_solved()
    assert sum(1 for a in actions if is_deal(a)) == 5
    trace = replay_solution_trace(opening, actions)
    assert trace["g"] == 198
    assert trace["deals"] == 5
    assert trace["replay_ok"]
    assert len(trace["epochs"]) == 6
    assert trace["prefix_g_by_rows"][5] == 0
    assert trace["exit_g_by_rows"][0] == 198
    zeros = 0
    st = opening.clone()
    for a in actions:
        if is_deal(a):
            st.deal()
            continue
        if step_cost(st, a) == 0:
            zeros += 1
        st.move(*a)
    assert trace["zero_cost_total"] == zeros
    assert zeros > 0
    assert trace["tableau_commands"] != trace["g"]


def test_candidate_ceiling_strictly_below_incumbent():
    opening = opening_state()
    trace = load_machine_incumbent(opening)
    assert trace["g"] - 1 == 197
    src = inspect.getsource(search_cost_optimisation)
    assert "incumbent_g - 1" in src
    assert "harvest_slack=-1" in src


def test_one_incumbent_checkpoint_per_epoch():
    opening = opening_state()
    trace = load_machine_incumbent(opening)
    ck = checkpoints_from_trace(trace)
    assert set(ck) == {5, 4, 3, 2, 1, 0}
    assert ck[5]["g"] == 0
    for rows, rec in ck.items():
        assert rec["incumbent_control"] is True
        assert rec["stock_rows"] == rows
    assert inspect.getsource(search_cost_optimisation).count("incumbent_by_rows") >= 1


def test_economy_lane_puts_g_first():
    opening = opening_state()
    keys = cost_lane_keys(opening, 12)
    assert "economy" in keys
    assert keys["economy"][0] == 12
    assert keys["cost"] == (12,)
    assert "readiness" in COST_LANES
    assert "economy" in COST_LANES
    assert "s" not in COST_LANES


def test_cost_pareto_and_class_cheaper_representative():
    cheap = {"g": 40, "foundations": 1, "face_down": 20, "empty_n": 0, "bonds": 10, "n_ready": 1, "cover": 4, "ready_edges": 1, "ready_cond": 6, "longest": 5, "ordered_digest": "a"}
    dear = dict(cheap, g=48, ordered_digest="b")
    assert cost_pareto_vec(cheap) < cost_pareto_vec(dear)
    assert structural_class_key(cheap) == structural_class_key(dear)
    unready = {"g": 10, "foundations": 0, "face_down": 30, "empty_n": 1, "bonds": 4, "n_ready": 0, "longest": 3}
    assert len(cost_pareto_vec(unready)) == 6


def test_portfolio_keeps_deal_now_and_incumbent_slot():
    from spider.whole_game_epoch_scheduler import _Top

    tops = {cat: _Top() for cat in COST_HARVEST_CATS}
    roots = [{"g": 0, "ident": "aa", "whole_game_identity": "aa", "ordered_digest": "00", "foundations": 0, "face_down": 40, "bonds": 0, "empty_n": 0}]
    inc = {"g": 2, "ident": "bb", "whole_game_identity": "bb", "ordered_digest": "11", "incumbent_control": True}
    picked, counts = harvest_portfolio(tops, roots, 0, width=16, cats=COST_HARVEST_CATS, incumbent=inc)
    assert counts.get("deal_now", 0) >= 1
    assert counts.get("incumbent", 0) == 1


def test_incumbent_retained_when_no_improvement():
    opening = opening_state()
    res = search_cost_optimisation(
        opening=opening,
        max_unique=20,
        time_limit_s=1.5,
        rss_abort_mb=4096,
        portfolio_width=8,
    )
    v, _ = choose_cost_verdict(
        {
            "incumbent_g": 198,
            "solved": res.solved,
            "replay_ok": res.replay_ok,
            "solution_g": res.solution_g,
            "accounting_fail": res.accounting_fail,
        }
    )
    if not res.solved:
        assert v == "AUTONOMOUS_INCUMBENT_HELD"
    v2, _ = choose_cost_verdict({"incumbent_g": 198, "solved": True, "replay_ok": True, "solution_g": 194})
    assert v2 == "AUTONOMOUS_COST_IMPROVED"
    v3, _ = choose_cost_verdict({"incumbent_g": 198})
    assert v3 == "AUTONOMOUS_INCUMBENT_HELD"


def test_v59_defaults_unchanged():
    src = inspect.getsource(search_epoch_portfolio)
    assert "lane_names: Sequence[str] = LANES" in src
    opening = opening_state()
    res = search_epoch_portfolio(
        opening=opening,
        max_unique=24,
        time_limit_s=2.0,
        rss_abort_mb=4096,
        portfolio_width=8,
    )
    assert res.accounting_fail is False


def test_savings_table_uses_replayed_prefixes():
    opening = opening_state()
    inc = load_machine_incumbent(opening)
    table = epoch_savings_table(inc, inc)
    assert table[-1]["saving"] == 0
    assert table[-1]["incumbent_g"] == 198
    fake = dict(inc, g=190, exit_g_by_rows={**inc["exit_g_by_rows"], 0: 190})
    t2 = epoch_savings_table(inc, fake)
    assert t2[-1]["saving"] == 8


def test_synthetic_strict_ceiling_and_replay():
    foundations = [_ka(s) for s in ("s", "h", "d", "c", "s", "h", "d")]
    left = _ka("c")
    st = _columns(left[:10], left[10:], foundations=foundations, stock=[])
    from spider.whole_game_epoch_scheduler import search_epoch_portfolio as sep

    res = sep(opening=st, max_unique=40, time_limit_s=2.0, rss_abort_mb=4096, cost_ceiling=20, portfolio_width=4)
    assert res.solved
    assert res.replay_ok
    assert res.solution_g <= 20
