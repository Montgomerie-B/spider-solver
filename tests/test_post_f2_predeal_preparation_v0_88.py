"""v0.88 post-F2 pre-Deal preparation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_quality_frontier import is_known_closed
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.post_f2_predeal_preparation import (
    CONTINUATION_RESERVE_S,
    MAX_DG,
    PORTFOLIO_MAX,
    PREP_S,
    SELECT_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    choose_prep_verdict,
    harvest_preparation,
    immediate_deal_control,
    load_prep_closed_table,
    load_v084_g187_f2_pre,
    load_v084_lowest_f_pre,
    prep_cost_band,
    reconstruct_root_a,
    reconstruct_root_b,
    select_prep_rollout_roots,
)
from spider.proof_aware_tactical_bridge import continuation_is_exhausted, interpret_continuation_stop
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.search_kernel import run_search
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "post_f2_predeal_preparation.py"
SCRIPT = ROOT / "research" / "post_f2_predeal_preparation_v0_88.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_roots_controls_and_deal():
    assert "53504b31" not in inspect.getsource(load_v084_lowest_f_pre)
    opening = opening_state()
    a = reconstruct_root_a(opening)
    b = reconstruct_root_b(opening)
    assert a["ok"] and a["g"] == 128 and a["foundations"] == 2 and a["stock_rows"] == 1 and a["face_down"] == 2
    assert b["ok"] and b["g"] == 129 and b["foundations"] == 2 and b["stock_rows"] == 1
    assert a["ordered_digest"] != b["ordered_digest"]
    assert a["can_deal"] and b["can_deal"]
    art_a = load_v084_lowest_f_pre()
    art_b = load_v084_g187_f2_pre()
    assert a["ordered_digest"] == art_a["pre_digest"]
    assert b["ordered_digest"] == art_b["pre_digest"]
    st = unpack_state(bytes.fromhex(a["ordered_digest"]))
    assert pack_state(st).hex() == a["ordered_digest"]
    assert not any(is_deal(x) for x in tableau_actions(st))
    ca = immediate_deal_control(a)
    cb = immediate_deal_control(b)
    assert ca["ok"] and ca["post_g"] == 129 and ca["assembly_h"] == 42 and ca["assembly_f"] == 171
    assert cb["ok"] and cb["post_g"] == 130 and cb["assembly_h"] == 41 and cb["assembly_f"] == 171
    assert ca["stock_rows"] == 0 and cb["stock_rows"] == 0


def test_prep_semantics_budgets_and_firewall():
    src = inspect.getsource(harvest_preparation)
    assert "actions_fn=tableau_actions" in src
    assert "lower_bound_fn=None" in src
    assert "identity_fn=pack_state" in src
    assert "cost_ceiling=int(root_g + max_dg)" in src
    assert MAX_DG == 15
    assert PREP_S == 150.0
    assert STAGE_A_S == 10.0 and STAGE_B_S == 20.0 and STAGE_B_N == 4
    assert SELECT_N == 12 and PORTFOLIO_MAX == 24
    assert 2 * PREP_S + 12 * STAGE_A_S + STAGE_B_N * STAGE_B_S + CONTINUATION_RESERVE_S <= TOTAL_S == 900.0
    assert prep_cost_band(0) == "0"
    assert prep_cost_band(4) == "3-5"
    assert prep_cost_band(15) == "10-15"
    src_sel = inspect.getsource(select_prep_rollout_roots)
    assert "band_" in src_sel and "immediate_deal" in src_sel
    table = load_prep_closed_table()
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table)
    assert not is_known_closed(ident, int(rec["g"]) - 1, table)
    assert continuation_is_exhausted("complete")
    assert interpret_continuation_stop("complete", solved=False)["exhausted"]
    v, _ = choose_prep_verdict({"superior_prep": True, "solved": False, "incumbent_g": 187, "max_foundations": 3})
    assert v == "POST_F2_PREP_FINDS_SUPERIOR_ROOT"
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    assert "is_terminal=lambda st: False" in src
    assert "n_predeal_f3" in src
    script = _text(SCRIPT)
    assert "STAGE_A_S" in script and "canonical" in script.lower()
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v088 = ROOT / "solutions" / "4925153_autonomous_v0_88.moves"
    if v088.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v088))
        assert g is not None and g < 187
    assert inspect.getsource(run_search)
