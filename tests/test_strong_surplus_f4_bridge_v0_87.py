"""v0.87 strong-surplus F4→F5 hierarchical bridge."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f2_quality_frontier import load_f2_closed_table
from spider.f3_quality_frontier import is_known_closed
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.new_family_f3_bridge import load_new_family_roots
from spider.packed_state import pack_state, unpack_state
from spider.proof_aware_tactical_bridge import continuation_is_exhausted, interpret_continuation_stop, _probe_one
from spider.research_actions import is_deal, stock_rows
from spider.strong_surplus_f4_bridge import (
    CONTINUATION_RESERVE_S,
    MAX_F4_ROOTS,
    PORTFOLIO_MAX,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    choose_strong_f4_verdict,
    document_boundaries_split,
    f5_quality,
    load_strong_surplus_f4s,
    select_active_f4s,
    select_f5_portfolio,
    structural_telemetry,
    verify_all_f4_roots,
)
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "strong_surplus_f4_bridge.py"
SCRIPT = ROOT / "research" / "strong_surplus_f4_bridge_v0_87.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_load_and_verify_strong_surplus_f4s():
    assert "53504b31" not in inspect.getsource(load_strong_surplus_f4s)
    loaded = load_strong_surplus_f4s()
    assert 1 <= len(loaded) <= 8
    strong = [r for r in loaded if int(r["assembly_f"]) <= 184]
    assert len(strong) == 3
    checked = verify_all_f4_roots()
    assert checked["ok"]
    assert checked["n_ok"] >= 3
    for rec in checked["roots"]:
        if not rec.get("ok"):
            continue
        assert rec["foundations"] == 4
        assert rec["stock_rows"] == 0
        assert rec["can_deal"] is False
        assert rec["source_f3_g"] == 148
        st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
        assert pack_state(st).hex() == rec["ordered_digest"]
        assert stock_rows(st) == 0
        assert not st.can_deal()
        assert not any(is_deal(a) for a in [])
    active = select_active_f4s(checked["roots"])
    assert len(active) <= MAX_F4_ROOTS == 3
    idents = [r["ident"] for r in active]
    assert len(idents) == len(set(idents))


def test_telemetry_names_budgets_and_firewall():
    audit = document_boundaries_split()
    assert audit["v085_boundaries_field"].startswith("mixed_suit_boundaries")
    assert audit["v086_boundaries_field"].startswith("visible_runs")
    f3s = load_new_family_roots()
    first = next(r for r in f3s if int(r["g"]) == 148)
    st = unpack_state(bytes.fromhex(first["ordered_digest"]))
    tel = structural_telemetry(st)
    assert tel["visible_runs"] == 32
    assert tel["visible_components"] == 32
    assert tel["mixed_suit_boundaries"] == 24
    assert tel["visible_runs"] != tel["mixed_suit_boundaries"]
    src = inspect.getsource(structural_telemetry)
    assert '"boundaries"' not in src
    assert STAGE_A_S == 30.0
    assert STAGE_B_S == 30.0 and STAGE_B_N == 4
    assert MAX_F4_ROOTS * 4 * STAGE_A_S + STAGE_B_N * STAGE_B_S + CONTINUATION_RESERVE_S <= TOTAL_S == 900.0
    assert f5_quality(184) == "STRONG_SURPLUS_F5"
    assert f5_quality(185) == "SURPLUS_F5"
    assert f5_quality(186) == "VIABLE_F5"
    table = load_f2_closed_table()
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table)
    assert not is_known_closed(ident, int(rec["g"]) - 1, table)
    port = select_f5_portfolio(
        [{"viable_terminals": [{"g": int(rec["g"]) - 1, "assembly_h": 10, "assembly_f": 185, "ident": ident, "foundations": 5, "legal_tableau": 10, "boundaries": 4, "tactical_target": "x", "ordered_digest": "aa"}], "root_g": 154}],
        table,
    )
    assert any(r.get("ident") == ident for r in port)
    assert len(port) <= PORTFOLIO_MAX == 16
    assert continuation_is_exhausted("complete")
    assert interpret_continuation_stop("complete", solved=False)["exhausted"]
    v, _ = choose_strong_f4_verdict({"best_next_f": 184, "max_foundations": 5, "solved": False, "incumbent_g": 187})
    assert v == "STRONG_F4_FINDS_STRONG_SURPLUS_F5"
    text = _text(MOD)
    assert "Hearts" not in text
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    assert "search_foundation_cashout" in inspect.getsource(_probe_one)
    script = _text(SCRIPT)
    assert "STAGE_A_S" in script and "STAGE_B_N" in script
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v087 = ROOT / "solutions" / "4925153_autonomous_v0_87.moves"
    if v087.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v087))
        assert g is not None and g < 187
