"""Proof-aware g158 F3 tactical bridge v0.81."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.f3_tactical_bridge import (
    F4_PORTFOLIO_MAX,
    assembly_slack,
    inspect_f3_state,
    select_f4_portfolio,
    verify_g141_root,
)
from spider.foundation_cashout import TACTICAL_LANES, search_foundation_cashout
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.proof_aware_tactical_bridge import (
    BRIDGE_CEILING,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    STAGE_B_N,
    STAGE_B_S,
    TACTICAL_BUDGET_S,
    cashout_class,
    choose_g158_verdict,
    continuation_is_exhausted,
    inspect_stock_empty_root,
    interpret_continuation_stop,
    is_proof_viable,
    is_surplus,
    load_g158_record,
    recommend_continue_from_roots,
    root_relative_economics,
    run_proof_aware_bridge,
    verify_g158_root,
)
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.search_kernel import run_search
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "proof_aware_tactical_bridge.py"
SCRIPT = ROOT / "research" / "g158_proof_aware_f4_v0_81.py"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
BOUND = ROOT / "src" / "spider" / "assembly_lower_bound.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
V078 = ROOT / "docs" / "research" / "g128_focused_endgame_v0_78.json"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def test_g158_loaded_from_v078_and_recomputed():
    rec = load_g158_record()
    assert int(rec["g"]) == 158
    assert rec.get("ordered_digest")
    src = inspect.getsource(load_g158_record)
    assert "53504b31" not in src
    assert "cheap_F" in src
    info = verify_g158_root()
    assert info["ok"], info.get("mismatches") or info.get("reason")
    assert info["foundations"] == 3
    assert info["g"] == 158
    assert info["assembly_h"] == 22
    assert info["assembly_f"] == 180
    assert info["slack"] == 6
    assert assembly_slack(186, 180) == 6
    assert info["face_down"] == 2
    assert info["empty_n"] == 3
    assert info["legal_tableau"] == 80
    assert info["stock_rows"] == 0
    assert info["can_deal"] is False
    assert info["boundaries_recorded"] == 18
    digest = rec["ordered_digest"]
    st = unpack_state(bytes.fromhex(digest))
    assert pack_state(st).hex() == digest
    assert stock_rows(st) == 0
    assert len(st.foundations) == 3
    assert not st.can_deal()
    assert not any(is_deal(a) for a in tableau_actions(st))
    g141_ok = inspect_f3_state(digest, g=158).get("ok")
    assert g141_ok is False
    generic = inspect_stock_empty_root(digest, g=158)
    assert generic["ok"] is True
    assert generic["empty_n"] == 3


def test_generic_root_economics_and_v080_g141_unchanged():
    e141 = root_relative_economics(161, 25, root_g=141, root_h=33, ceiling=186)
    e158 = root_relative_economics(161, 25, root_g=158, root_h=22, ceiling=186)
    assert e141["delta_g"] == 20 and e141["delta_h"] == -8 and e141["delta_f"] == 12
    assert e141["remaining_slack"] == 0
    assert e158["delta_g"] == 3 and e158["delta_h"] == 3 and e158["delta_f"] == 6
    assert e141 != e158
    g141 = verify_g141_root()
    assert g141["ok"] and g141["g"] == 141 and g141["slack"] == 12
    src_b = inspect.getsource(run_proof_aware_bridge)
    assert "STAGE_A_S" in src_b and "STAGE_B_N" in src_b
    assert "remaining_targets" in src_b
    assert '"h"' not in src_b
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == BRIDGE_CEILING
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172


def test_ready_suits_generic_surplus_and_portfolio_caps():
    info = verify_g158_root()
    ranks = [t["operational_rank"] for t in info["remaining_targets"]]
    assert ranks == list(range(1, len(ranks) + 1))
    suits = [t["suit"] for t in info["remaining_targets"]]
    assert len(suits) == len(set(suits))
    src = _text(MOD)
    assert "Hearts" not in src
    tree = ast.parse(src)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    assert "4925153_canonical.moves" not in src
    assert "4925153_canonical.moves" not in _text(SCRIPT)
    assert cashout_class(163, 29, 186) == "RAW_TARGET_CASHOUT"
    assert is_proof_viable(163, 29, 186) is False
    assert cashout_class(161, 25, 186) == "VIABLE_TARGET_CASHOUT"
    assert is_proof_viable(161, 25, 186) is True
    assert is_surplus(161, 25, 186) is False
    assert cashout_class(170, 15, 186) == "SURPLUS_TARGET_CASHOUT"
    assert is_surplus(170, 15, 186) is True
    assert 170 + 15 == 185
    dead = {
        "g": 163,
        "assembly_h": 29,
        "assembly_f": 192,
        "ident": "dead",
        "ordered_digest": "aa",
        "legal_tableau": 10,
        "boundaries": 4,
        "tactical_target": "x",
        "viable": False,
    }
    live = {
        "g": 170,
        "assembly_h": 15,
        "assembly_f": 185,
        "slack": 1,
        "ident": "live",
        "ordered_digest": "bb",
        "legal_tableau": 20,
        "boundaries": 3,
        "tactical_target": "y",
        "viable": True,
    }
    port = select_f4_portfolio(
        [r for r in (dead, live) if is_proof_viable(int(r["g"]), int(r["assembly_h"]))],
        hard_max=F4_PORTFOLIO_MAX,
    )
    assert all(int(r["assembly_f"]) <= 186 for r in port)
    assert all(r.get("ident") != "dead" for r in port)
    assert len(port) <= 16
    assert STAGE_A_S == 120.0 and STAGE_A_UNIQUE == 200_000
    assert STAGE_B_N == 2 and STAGE_B_S == 60.0
    assert STAGE_A_S * 4 + STAGE_B_S * STAGE_B_N <= TACTICAL_BUDGET_S == 600.0
    src_b = inspect.getsource(run_proof_aware_bridge)
    assert "targets[:4]" in src_b
    assert "[:STAGE_B_N]" in src_b
    assert "F4_PORTFOLIO_MAX" in src_b


def test_complete_means_exhaustion_and_no_continue():
    assert continuation_is_exhausted("complete") is True
    assert continuation_is_exhausted("time limit") is False
    assert continuation_is_exhausted("unique limit") is False
    assert recommend_continue_from_roots("complete", solved=False) is False
    assert recommend_continue_from_roots("time limit", solved=False) is True
    assert recommend_continue_from_roots("unique limit", solved=False) is True
    note = interpret_continuation_stop("complete", solved=False)
    assert note["exhausted"] is True
    assert note["recommend_continue_from_these_roots"] is False
    assert "exhausted" in (note["note"] or "")
    kern = _text(KERN)
    assert 'result.stop_reason = "complete"' in kern
    payload = {
        "bridge": {"n_viable": 2, "n_surplus": 0, "best_viable_f": 186, "best_slack": 0},
        "max_foundations": 4,
        "stop_reason": "complete",
        "solved": False,
        "incumbent_g": 187,
    }
    verdict, _reason = choose_g158_verdict(payload)
    assert verdict == "G158_BRIDGE_F4_EXHAUSTED"
    surplus_payload = dict(payload, bridge={"n_viable": 1, "n_surplus": 1, "best_viable_f": 185})
    v2, _ = choose_g158_verdict(surplus_payload)
    assert v2 == "G158_BRIDGE_FINDS_SURPLUS_F4"
    deep = dict(payload, max_foundations=5, bridge={"n_viable": 16, "n_surplus": 5, "best_viable_f": 185})
    v3, _ = choose_g158_verdict(deep)
    assert v3 == "G158_BRIDGE_DEEP_ENDGAME"


def test_firewall_no_deal_bound_unchanged_replay_if_present():
    cash = _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    assert "Deal leaked into tactical actions" in cash
    assert TACTICAL_LANES == ("cost", "target_assembly", "target_access")
    src_k = inspect.getsource(run_search)
    assert "int(g) + h > int(ceiling)" in _text(KERN)
    assert "stock_empty_assembly_h" not in _text(KERN)
    bound = _text(BOUND)
    assert "stock_empty_assembly_h" in bound
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v081 = ROOT / "solutions" / "4925153_autonomous_v0_81.moves"
    if v081.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v081))
        assert g is not None and g < 187
    else:
        assert AUTONOMOUS_INCUMBENT_MW == 187
    script = _text(SCRIPT)
    assert "canonical" in script.lower()
    assert "g161" in script and "g162" in script
    assert "run_proof_aware_bridge" in script
    assert V078.exists()
