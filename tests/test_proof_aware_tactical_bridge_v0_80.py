"""Proof-aware stock-empty tactical bridge v0.80."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.f3_tactical_bridge import assembly_slack, verify_g141_root
from spider.foundation_cashout import (
    TACTICAL_LANES,
    search_foundation_cashout,
    select_tactical_target,
    tactical_lane_keys,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.proof_aware_tactical_bridge import (
    BRIDGE_CEILING,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_N,
    STAGE_B_S,
    TACTICAL_BUDGET_S,
    ExactHCache,
    assembly_payback,
    is_proof_viable,
    run_proof_aware_bridge,
    target_future_key,
)
from spider.search_kernel import run_search
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
CASH = ROOT / "src" / "spider" / "foundation_cashout.py"
MOD = ROOT / "src" / "spider" / "proof_aware_tactical_bridge.py"
SCRIPT = ROOT / "research" / "proof_aware_tactical_bridge_v0_80.py"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


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


def test_constants_budgets_firewall():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == BRIDGE_CEILING
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert STAGE_A_S == 120.0 and STAGE_A_UNIQUE == 200_000
    assert STAGE_B_N == 2 and STAGE_B_S == 60.0
    assert STAGE_A_S * 4 + STAGE_B_S * STAGE_B_N <= TACTICAL_BUDGET_S == 600.0
    assert TACTICAL_LANES == ("cost", "target_assembly", "target_access")
    assert "target_future" not in TACTICAL_LANES
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    src = inspect.getsource(search_foundation_cashout)
    assert "lower_bound_fn" in src and "future_cost_key_fn" in src and "terminal_viability_fn" in src
    assert "lower_bound_fn=lower_bound_fn" in src
    kern = _text(KERN)
    assert "stock_empty_assembly_h" not in kern
    assert "int(g) + h > int(ceiling)" in kern
    script = _text(SCRIPT)
    assert script.find("EVAL 187") > script.find("machine experiment frozen")
    assert '"h"' not in inspect.getsource(run_proof_aware_bridge)


def test_default_cashout_unchanged_and_v071_fixture():
    st = _columns(_run("c", 13, 2), [Card("c", 1)], stock=_stock_row())
    target = select_tactical_target(st, 5)
    res = search_foundation_cashout(
        root_state=st,
        root_g=5,
        target_suit=target["suit"],
        max_unique=500,
        time_limit_s=2.0,
        cost_ceiling=20,
    )
    assert res.found
    assert res.cheapest_g is not None and res.cheapest_g > 5
    assert res.lower_bound_prunes == 0
    assert tuple(res.lane_names) == TACTICAL_LANES
    assert "target_future" not in res.lane_exp
    keys = tactical_lane_keys(st, 5, target["suit"])
    assert set(keys) == set(TACTICAL_LANES)


def test_proof_hooks_and_dead_not_admitted():
    assert is_proof_viable(163, 29, 186) is False
    assert 163 + 29 == 192
    assert is_proof_viable(141, 33, 186) is True
    assert assembly_slack(186, 174) == 12
    assert assembly_slack(186, 192) == -6
    assert abs(assembly_payback(22, -4) - (4 / 22)) < 1e-9
    src = inspect.getsource(search_foundation_cashout)
    assert 'rec["class"] = "VIABLE_TARGET_CASHOUT" if ok else "RAW_TARGET_CASHOUT"' in src
    assert "production = terminals if terminal_viability_fn is None else viable" in src
    key = target_future_key
    src_k = inspect.getsource(key)
    assert "g + h" in src_k or "int(g) + h" in src_k
    assert "*" not in src_k.split("return")[-1]
    src_c = inspect.getsource(ExactHCache)
    assert "pack_whole_game_identity" in src_c
    cash = _text(CASH)
    assert "Deal leaked into tactical actions" in cash
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    g141 = verify_g141_root()
    assert g141["ok"] and g141["g"] == 141 and g141["slack"] == 12
    info = g141
    assert len(info["remaining_targets"]) >= 1
    src_b = inspect.getsource(run_proof_aware_bridge)
    assert "STAGE_A_S" in src_b and "STAGE_B_N" in src_b
    assert "remaining_targets" in src_b
    assert inspect.getsource(run_search).count("lower_bound_fn") >= 1
    v080 = ROOT / "solutions" / "4925153_autonomous_v0_80.moves"
    if v080.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v080))
        assert g is not None and g < 187
    else:
        assert AUTONOMOUS_INCUMBENT_MW == 187
