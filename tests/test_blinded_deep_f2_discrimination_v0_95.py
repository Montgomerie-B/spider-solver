"""v0.95 blinded lean F2 discrimination."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.blinded_deep_f2 import (
    STAGE_A_CEILING,
    STAGE_A_S,
    STAGE_B_CEILING,
    STAGE_B_S,
    STAGE_C_CEILING,
    STAGE_C_N,
    STAGE_C_S,
    V094_PROGRESS,
    V094_REPORT,
    V094_RESULT,
    classify_root,
    load_five_root_specs,
    run_blinded_lean,
    search_spec,
    select_stage_c,
)
from spider.consequence_search import run_stockempty_consequence
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_artefacts import artefact_verdicts_agree
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "blinded_deep_f2.py"
SCRIPT = ROOT / "research" / "blinded_deep_f2_discrimination_v0_95.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_v094_progress_and_five_roots():
    agree = artefact_verdicts_agree(V094_RESULT, V094_PROGRESS, V094_REPORT)
    assert agree["ok"], agree
    assert agree["result_verdict"] == "LEAN_EVALUATOR_MAJOR_SPEEDUP"
    specs = load_five_root_specs()
    names = [s.get("name") for s in specs]
    assert names == ["CONTROL_187", "CONTROL_ROOT_A", "NOVEL_A", "NOVEL_B", "NOVEL_C"]
    digests = [s.get("post_digest") for s in specs]
    assert len(set(digests)) == 5
    c187 = specs[0]
    assert c187["pre_g"] == 129 and int(c187.get("post_g") or c187.get("g")) == 130
    assert int(c187.get("assembly_h") or 0) == 41
    ca = specs[1]
    assert int(ca.get("pre_g") or 0) == 128
    assert int(ca.get("post_g") or ca.get("g") or 0) == 129
    assert int(ca.get("assembly_h") or 0) == 42
    na, nb, nc = specs[2], specs[3], specs[4]
    assert na["pre_g"] == 133 and na["post_g"] == 134 and na["assembly_h"] == 40 and na["assembly_f"] == 174
    assert nb["pre_g"] == 133 and nb["post_g"] == 134 and nb["ident"] != na["ident"]
    assert nc["pre_g"] == 138 and nc["post_g"] == 139 and nc["assembly_f"] == 180 and nc["legal"] == 9
    spec = search_spec(c187)
    assert set(spec.keys()) == {"g", "ordered_digest"}
    src_keys = inspect.getsource(strategic_lane_keys)
    assert "CONTROL_187" not in src_keys
    assert "NOVEL_A" not in src_keys
    src_run = inspect.getsource(run_blinded_lean)
    assert "run_stockempty_consequence" in src_run
    assert "search_epoch_portfolio" not in src_run
    assert "search_foundation_cashout" not in src_run
    assert "continuation_table" not in src_run


def test_stages_classes_firewall():
    assert STAGE_A_S == 30.0 and STAGE_A_CEILING == 186
    assert STAGE_B_S == 45.0 and STAGE_B_CEILING == 187
    assert STAGE_C_S == 180.0 and STAGE_C_CEILING == 186 and STAGE_C_N == 1
    assert 5 * STAGE_A_S + 5 * STAGE_B_S + STAGE_C_S <= 555.0
    a_solved = {"solved": True, "terminal_g": 186}
    a_fail = {"solved": False}
    b_187 = {"solved": True, "terminal_g": 187}
    b_fail = {"solved": False, "max_F": 3}
    assert classify_root(a_solved, b_fail) == "CLASS_186"
    assert classify_root(a_fail, b_187) == "CLASS_187"
    assert classify_root(a_fail, b_fail) == "UNRESOLVED_187"
    rows = [
        {"name": "NOVEL_A", "cls": "CLASS_187", "stage_a": a_fail, "stage_b": {"unique": 8000}, "start_g": 134, "start_f": 174, "post_digest": "aa"},
        {"name": "NOVEL_B", "cls": "CLASS_187", "stage_a": a_fail, "stage_b": {"unique": 9000}, "start_g": 134, "start_f": 174, "post_digest": "bb"},
        {"name": "CONTROL_187", "cls": "CLASS_187", "stage_a": a_fail, "stage_b": {"unique": 1000}, "start_g": 130, "start_f": 171, "post_digest": "cc"},
    ]
    pick = select_stage_c(rows)
    assert pick["name"] == "NOVEL_A"
    assert select_stage_c([{"name": "NOVEL_C", "cls": "UNRESOLVED_187", "stage_b": {"max_F": 3}, "start_f": 180, "post_digest": "x"}]) is None
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    script = _text(SCRIPT)
    assert "run_stockempty_consequence" in inspect.getsource(run_blinded_lean)
    assert "STAGE_A_CEILING" in script and "STAGE_B_CEILING" in script
    assert "v0_74.moves" not in inspect.getsource(run_blinded_lean)
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v095 = ROOT / "solutions" / "4925153_autonomous_v0_95.moves"
    if v095.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v095))
        assert g is not None and g <= 186
    assert inspect.getsource(run_stockempty_consequence)
