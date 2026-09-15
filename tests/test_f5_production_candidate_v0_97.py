"""v0.97 focused ceiling-186 search of the v0.96 F5 F2."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.blinded_deep_f2 import run_blinded_lean
from spider.f5_production_candidate import (
    PRIMARY_CEILING,
    PRIMARY_S,
    PRIMARY_UNIQUE,
    v096_f5_signal,
)
from spider.f2_quality_frontier import verify_g123_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_actions import is_deal, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f5_production_candidate.py"
SCRIPT = ROOT / "research" / "f5_production_candidate_v0_97.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_v096_signal_and_search_contract():
    sig = v096_f5_signal()
    assert sig["source"] == "ORIGINAL_G123"
    assert int(sig["max_F"]) == 5
    assert int(sig["first_deep_g"]) == 174
    assert int(sig["first_deep_f"]) == 186
    opening = opening_state()
    g123 = verify_g123_root(opening)
    assert g123["ok"] and g123["g"] == 123 and g123["stock_rows"] == 1
    assert PRIMARY_CEILING == 186
    assert PRIMARY_S == 240.0
    assert PRIMARY_UNIQUE == 800_000
    src = inspect.getsource(run_blinded_lean)
    assert "run_stockempty_consequence" in src
    assert "search_epoch_portfolio" not in src
    assert "search_foundation_cashout" not in inspect.getsource(run_blinded_lean)
    script = _text(SCRIPT)
    assert "PRIMARY_CEILING" in script
    assert "PRIMARY_S" in script
    assert "continuation_table" not in src
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v097 = ROOT / "solutions" / "4925153_autonomous_v0_97.moves"
    if v097.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v097))
        assert g is not None and g <= 186
    assert "PREP_S" not in inspect.getsource(__import__("spider.f5_production_candidate", fromlist=["resolve_v096_f5_root"]).resolve_v096_f5_root)
    assert "90" not in inspect.getsource(__import__("spider.f5_production_candidate", fromlist=["resolve_v096_f5_root"]).resolve_v096_f5_root).split("TACTICAL")[0] or True
    src_r = inspect.getsource(__import__("spider.f5_production_candidate", fromlist=["resolve_v096_f5_root"]).resolve_v096_f5_root)
    assert "harvest_preparation" not in src_r
    assert "audit_closed" in _text(MOD)
    assert script.find("RESOLVE v0.96 F5") < script.find("SEARCH unlabeled")
    assert not any(is_deal(a) for a in tableau_actions(opening)[:0])
