"""v0.83 F3 bridge calibration: slack vs assembly at equal probe cost."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_bridge_calibration import (
    CONTINUATION_RESERVE_S,
    G141_FIRST_VIABLE_S,
    N_ROOTS,
    ROOT_SPECS,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    TOTAL_S,
    choose_calibration_verdict,
    equal_f_composition_differs,
    load_calibration_root,
    load_calibration_roots,
    load_v082_f3_pool,
    select_calibration_portfolio,
    verify_all_calibration_roots,
    verify_calibration_root,
)
from spider.f3_quality_frontier import (
    bridge_loss,
    control_digests,
    is_known_closed,
    load_closed_root_table,
    next_foundation_quality,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.proof_aware_tactical_bridge import (
    continuation_is_exhausted,
    interpret_continuation_stop,
    recommend_continue_from_roots,
)
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f3_bridge_calibration.py"
SCRIPT = ROOT / "research" / "f3_bridge_calibration_v0_83.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_roots_loaded_from_v082_by_metrics_not_hardcoded():
    src = inspect.getsource(load_calibration_root)
    assert "53504b31" not in src
    assert "pareto" in inspect.getsource(load_v082_f3_pool) or "V082_JSON" in inspect.getsource(load_v082_f3_pool)
    assert len(ROOT_SPECS) == N_ROOTS == 3
    assert ROOT_SPECS[0]["g"] == 142
    assert ROOT_SPECS[0]["f"] == 174
    assert ROOT_SPECS[0]["slack"] == 12
    roots = load_calibration_roots()
    assert len(roots) == 3
    controls = control_digests()
    for rec in roots:
        assert rec.get("ordered_digest")
        assert rec["ordered_digest"] not in (controls["g141"], controls["g158"])
    a = load_calibration_root(ROOT_SPECS[0])
    assert int(a["g"]) == 142
    assert int(a["assembly_h"]) == 32
    assert int(a["assembly_f"]) == 174
    assert int(a["empty_n"]) == 2
    assert int(a["legal_tableau"]) == 47
    assert int(a["boundaries"]) == 35


def test_independent_recompute_and_not_controls():
    checked = verify_all_calibration_roots()
    assert checked["ok"], [r.get("mismatches") or r.get("reason") for r in checked["roots"]]
    names = [r["calibration_name"] for r in checked["roots"]]
    assert names == ["A_high_slack", "B_interior", "C_assembled"]
    a = checked["roots"][0]
    assert a["g"] == 142 and a["assembly_h"] == 32 and a["assembly_f"] == 174 and a["slack"] == 12
    st = unpack_state(bytes.fromhex(a["ordered_digest"]))
    assert pack_state(st).hex() == a["ordered_digest"]
    assert stock_rows(st) == 0
    assert len(st.foundations) == 3
    assert not st.can_deal()
    assert not any(is_deal(x) for x in tableau_actions(st))
    b = checked["roots"][1]
    c = checked["roots"][2]
    assert b["g"] == 160 and b["assembly_h"] == 23 and b["assembly_f"] == 183 and b["empty_n"] == 3
    assert c["g"] == 161 and c["assembly_h"] == 22 and c["assembly_f"] == 183 and c["empty_n"] == 4
    assert b["assembly_f"] == c["assembly_f"] == 183
    assert c["assembly_h"] == b["assembly_h"] - 1
    assert all(not r.get("is_control") for r in checked["roots"])


def test_equal_budget_above_g141_first_viable_and_no_harvest():
    assert STAGE_A_S == 60.0
    assert STAGE_A_UNIQUE == 100_000
    assert STAGE_A_S > G141_FIRST_VIABLE_S
    assert CONTINUATION_RESERVE_S == 150.0
    assert N_ROOTS * 4 * STAGE_A_S + CONTINUATION_RESERVE_S <= TOTAL_S == 900.0
    script = _text(SCRIPT)
    assert "harvest_f3_terminals" not in script
    assert "HARVEST F3" not in script
    assert "STAGE B" not in script
    assert "choose_stage_b" not in script
    assert "no_stage_b" in script
    src = inspect.getsource(verify_calibration_root)
    assert "control" in src.lower() or "g141" in src or "g158" in src


def test_quality_closed_guard_complete_firewall():
    assert bridge_loss(174, 186) == 12
    assert bridge_loss(180, 185) == 5
    assert next_foundation_quality(184) == "STRONG_SURPLUS"
    assert next_foundation_quality(185) == "SURPLUS_1"
    assert next_foundation_quality(186) == "ZERO_SLACK"
    table = load_closed_root_table()
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table) is True
    similar = ident[:-2] + ("00" if ident[-2:] != "00" else "ff")
    assert is_known_closed(similar, int(rec["g"]), table) is False
    assert continuation_is_exhausted("complete") is True
    assert recommend_continue_from_roots("complete", solved=False) is False
    note = interpret_continuation_stop("complete", solved=False)
    assert note["exhausted"] is True
    v, _ = choose_calibration_verdict({"best_new_f": 184, "best_bridge_loss": 4, "solved": False, "incumbent_g": 187})
    assert v == "F3_CALIBRATION_FINDS_STRONG_SURPLUS"
    v2, _ = choose_calibration_verdict({"best_new_f": 185, "solved": False, "incumbent_g": 187})
    assert v2 == "F3_CALIBRATION_MATCHES_G158"
    v3, _ = choose_calibration_verdict({"best_new_f": 186, "solved": False, "incumbent_g": 187})
    assert v3 == "F3_CALIBRATION_ZERO_SLACK_ONLY"
    assert equal_f_composition_differs(
        {"best_terminal_f": 186, "bridge_loss": 3},
        {"best_terminal_f": 185, "bridge_loss": 2},
    )
    assert not equal_f_composition_differs(
        {"best_terminal_f": 185, "bridge_loss": 2, "lowest_terminal_h": 10},
        {"best_terminal_f": 185, "bridge_loss": 2, "lowest_terminal_h": 10},
    )
    v5, _ = choose_calibration_verdict({
        "best_new_f": 185,
        "composition_differs": True,
        "solved": False,
        "incumbent_g": 187,
        "max_foundations": 4,
    })
    assert v5 == "F3_CALIBRATION_REVEALS_F_COMPOSITION"
    port = select_calibration_portfolio(
        [{"viable_terminals": [{"g": 170, "assembly_h": 15, "assembly_f": 185, "ident": "x", "legal_tableau": 10, "boundaries": 4, "tactical_target": "d", "ordered_digest": "aa"}], "root_g": 160}],
        {},
    )
    assert len(port) <= 16
    v4, _ = choose_calibration_verdict({"best_new_f": None, "screening_time_limited": True, "solved": False, "incumbent_g": 187})
    assert v4 == "F3_CALIBRATION_SEARCH_LIMITED"
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    cash = _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    assert "Deal leaked into tactical actions" in cash
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v083 = ROOT / "solutions" / "4925153_autonomous_v0_83.moves"
    if v083.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v083))
        assert g is not None and g < 187
