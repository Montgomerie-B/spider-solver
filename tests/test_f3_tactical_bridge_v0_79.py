"""F3→F4 tactical bridge v0.79."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    F4_PORTFOLIO_MAX,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_N,
    STAGE_B_S,
    TACTICAL_BUDGET_S,
    assembly_slack,
    expected_g141_digest,
    inspect_f3_state,
    load_g141_record,
    run_tactical_bridge,
    search_f4_portfolio,
    select_f4_portfolio,
    verify_g141_root,
)
from spider.foundation_cashout import (
    TACTICAL_CEILING,
    is_target_cashout,
    search_foundation_cashout,
    suit_foundation_count,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f3_tactical_bridge.py"
SCRIPT = ROOT / "research" / "f3_tactical_bridge_v0_79.py"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_firewalls_and_budgets():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == BRIDGE_CEILING
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert TACTICAL_CEILING == 191
    assert STAGE_A_S == 60.0 and STAGE_A_UNIQUE == 100_000
    assert STAGE_B_N == 2 and STAGE_B_S == 60.0
    assert STAGE_A_S * 4 + STAGE_B_S * STAGE_B_N <= TACTICAL_BUDGET_S
    assert F4_PORTFOLIO_MAX == 16
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    src_b = inspect.getsource(run_tactical_bridge)
    assert "STAGE_A_S" in src_b
    assert "STAGE_B_N" in src_b
    assert "remaining_targets" in src_b
    src_p = inspect.getsource(search_foundation_cashout)
    assert "continuation_table" not in src_p
    src_c = inspect.getsource(search_f4_portfolio)
    assert "continuation_table=None" in src_c
    assert "cost_ceiling=BRIDGE_CEILING" in src_c
    kern = _text(KERN)
    assert "int(g) + h > int(ceiling)" in kern
    script = _text(SCRIPT)
    assert script.find("EVAL 187") > script.find("machine experiment frozen")
    assert "search_rollout_guided" not in script


def test_slack_convention_ceiling_minus_f():
    assert assembly_slack(186, 172) == 14
    assert assembly_slack(186, 174) == 12
    assert assembly_slack(186, 192) == -6
    md = _text(ROOT / "docs" / "research" / "g128_focused_endgame_v0_78.md")
    assert "+14" in md


def test_g141_loaded_from_v078_and_recomputed():
    rec = load_g141_record()
    assert int(rec["g"]) == 141
    digest = expected_g141_digest()
    assert digest == rec["ordered_digest"]
    info = verify_g141_root()
    assert info["ok"]
    assert info["foundations"] == 3
    assert info["face_down"] == 2
    assert info["empty_n"] == 2
    assert info["legal_tableau"] == 41
    assert info["assembly_h"] == 33
    assert info["assembly_f"] == 174
    assert info["slack"] == 12
    assert info["boundaries_recorded"] == 28
    assert info["boundaries"] == 36
    assert info["stock_rows"] == 0
    assert info["g"] == 141
    st = unpack_state(bytes.fromhex(digest))
    assert pack_state(st).hex() == digest
    assert stock_rows(st) == 0
    assert len(st.foundations) == 3
    assert not any(is_deal(a) for a in tableau_actions(st))


def test_ready_targets_generic_and_suit_specific_goal():
    info = inspect_f3_state()
    assert info["n_ready"] >= 1
    ranks = [t["operational_rank"] for t in info["remaining_targets"]]
    assert ranks == list(range(1, len(ranks) + 1))
    suits = [t["suit"] for t in info["remaining_targets"]]
    assert len(suits) == len(set(suits))
    st = unpack_state(bytes.fromhex(info["ordered_digest"]))
    for tgt in info["remaining_targets"]:
        before = suit_foundation_count(st, tgt["suit"])
        assert before == tgt["target_foundations_before"]
        assert is_target_cashout(st, tgt["suit"], before) is False
    src = inspect.getsource(is_target_cashout)
    assert "target_suit" in src
    src_b = inspect.getsource(run_tactical_bridge)
    assert "remaining_targets" in src_b


def test_f4_portfolio_cap_and_absolute_g():
    fake = [
        {
            "g": 163 + i,
            "assembly_f": 192,
            "assembly_h": 29,
            "legal_tableau": 10 + i,
            "boundaries": 20,
            "ident": f"id{i}",
            "whole_game_identity": f"id{i}",
            "ordered_digest": f"d{i}",
            "tactical_target": "h" if i < 8 else "d",
            "foundations": 4,
        }
        for i in range(20)
    ]
    port = select_f4_portfolio(fake, hard_max=16)
    assert len(port) <= 16
    src = inspect.getsource(search_foundation_cashout)
    assert "root_g" in src
    src_p = inspect.getsource(__import__("spider.f3_tactical_bridge", fromlist=["_probe_one"])._probe_one)
    assert "root_g=int(f3[\"g\"])" in src_p
    assert "cost_ceiling=BRIDGE_CEILING" in src_p
    cash = _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    assert "Deal leaked into tactical actions" in cash
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v079 = ROOT / "solutions" / "4925153_autonomous_v0_79.moves"
    if v079.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v079))
        assert g is not None and g < 187
        assert sum(1 for a in parse_moves_file(v079) if is_deal(a)) == 5
    else:
        assert AUTONOMOUS_INCUMBENT_MW == 187
