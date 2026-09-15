"""v0.96 deep-guided F1→F2 with lean consequence evaluation."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.deep_guided_f1_f2 import (
    NOVEL_MAX,
    PREP_MAX_DG,
    PREP_SELECT,
    PREP_S,
    STAGE_A_CEILING,
    STAGE_A_S,
    STAGE_B_CEILING,
    STAGE_B_S,
    STAGE_C_S,
    TACTICAL_S,
    TARGETS_PER_F1,
    classify_completion,
    choose_stage_c,
    f1_as_harvest_root,
    f1_prep_band,
    fresh_targets,
    retain_f2_terminals,
    select_novel_posts,
    select_prepared_f1s,
)
from spider.f2_quality_frontier import harvest_f2_target, verify_g123_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.post_f2_predeal_preparation import harvest_preparation
from spider.research_actions import is_deal, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "deep_guided_f1_f2.py"
SCRIPT = ROOT / "research" / "deep_guided_f1_f2_v0_96.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_g123_prep_tactical_contracts():
    opening = opening_state()
    g123 = verify_g123_root(opening)
    assert g123["ok"]
    assert g123["g"] == 123
    assert g123["foundations"] == 1
    assert g123["stock_rows"] == 1
    assert g123["face_down"] == 2
    assert g123.get("prefix_actions")
    src_h = inspect.getsource(harvest_preparation)
    assert "actions_fn=tableau_actions" in src_h
    assert "is_terminal=lambda st: False" in src_h
    assert PREP_MAX_DG == 8
    assert PREP_S == 90.0
    assert PREP_SELECT == 4
    orig = {"g": 123, "ordered_digest": "aa", "legal_tableau": 4, "foundations": 1}
    cands = [
        {"g": 125, "prep_delta_g": 2, "foundations": 1, "ordered_digest": "b1", "legal_tableau": 5},
        {"g": 127, "prep_delta_g": 4, "foundations": 1, "ordered_digest": "b2", "legal_tableau": 6},
        {"g": 129, "prep_delta_g": 6, "foundations": 1, "ordered_digest": "b3", "legal_tableau": 3},
        {"g": 131, "prep_delta_g": 8, "foundations": 1, "ordered_digest": "b4", "legal_tableau": 7},
    ]
    sel = select_prepared_f1s(cands, orig)
    assert len(sel) == 5
    assert sel[0]["source_role"] == "ORIGINAL_G123"
    assert f1_prep_band(2) == "1-2" and f1_prep_band(4) == "3-4"
    src_t = inspect.getsource(harvest_f2_target)
    assert "search_foundation_cashout" in src_t
    assert TACTICAL_S == 12.0
    assert TARGETS_PER_F1 == 2
    src_ft = inspect.getsource(fresh_targets)
    assert "rank_ready_suits" in src_ft
    assert "Hearts" not in src_ft and "Diamonds" not in src_ft
    terms = [
        {"foundations": 2, "stock_rows": 1, "g": 128, "delta_g": 5, "ordered_digest": "x"},
        {"foundations": 2, "stock_rows": 1, "g": 126, "delta_g": 3, "ordered_digest": "y"},
        {"foundations": 2, "stock_rows": 1, "g": 127, "delta_g": 4, "ordered_digest": "z"},
    ]
    keep = retain_f2_terminals(terms)
    assert len(keep) <= 3
    assert {k["ordered_digest"] for k in keep} <= {"x", "y", "z"}


def test_filter_deep_eval_firewall():
    known = {"idA": {"name": "NOVEL_A", "g": 134}}
    posts = [
        {"ident": "idA", "post_g": 134, "assembly_f": 174, "ok": True, "post_digest": "d1", "f1_source": "PREP_1-2"},
        {"ident": "idB", "post_g": 132, "assembly_f": 173, "ok": True, "post_digest": "d2", "f1_source": "ORIGINAL_G123"},
        {"ident": "idC", "post_g": 133, "assembly_f": 175, "ok": True, "post_digest": "d3", "f1_source": "PREP_3-4"},
        {"ident": "idD", "post_g": 131, "assembly_f": 172, "ok": True, "post_digest": "d4", "f1_source": "PREP_1-2"},
        {"ident": "idA", "post_g": 129, "assembly_f": 171, "ok": True, "post_digest": "d5", "f1_source": "PREP_5-6"},
        {"ident": "dead", "post_g": 140, "assembly_f": 188, "ok": True, "proof_dead": True, "post_digest": "dz", "f1_source": "x"},
    ]
    picks, hits, reopen = select_novel_posts(posts, known, k=6)
    assert all(not p.get("proof_dead") for p in picks)
    assert any(p.get("reopened") for p in reopen)
    assert len(picks) <= NOVEL_MAX == 6
    assert classify_completion({"solved": True, "terminal_g": 186}, {"solved": False}) == "CLASS_186"
    assert classify_completion({"solved": False}, {"solved": True, "terminal_g": 187}) == "CLASS_187"
    pick = choose_stage_c(
        [
            {"name": "NOVEL_X", "cls": "CLASS_187", "stage_b": {"unique": 8000}, "post_digest": "aa"},
            {"name": "CONTROL_187", "cls": "CLASS_187", "stage_b": {"unique": 1000}, "post_digest": "cc"},
        ],
        {"NOVEL_X": {"n_f187": 3, "max_run_f187": 2, "first_f187": {"action_index": 10}}},
    )
    assert pick["name"] == "NOVEL_X"
    assert STAGE_A_S == 25.0 and STAGE_A_CEILING == 186
    assert STAGE_B_S == 35.0 and STAGE_B_CEILING == 187
    assert STAGE_C_S == 180.0
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    script = _text(SCRIPT)
    assert "run_blinded_lean" in script
    assert "v0_74.moves" not in inspect.getsource(harvest_f2_target)
    src_b = inspect.getsource(__import__("spider.blinded_deep_f2", fromlist=["run_blinded_lean"]).run_blinded_lean)
    assert "run_stockempty_consequence" in src_b
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v096 = ROOT / "solutions" / "4925153_autonomous_v0_96.moves"
    if v096.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v096))
        assert g is not None and g <= 186
    assert inspect.getsource(f1_as_harvest_root)
    st = opening.clone()
    assert not any(is_deal(a) for a in tableau_actions(st)[:0])
