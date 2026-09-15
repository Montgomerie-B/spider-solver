"""v0.93 ceiling-187 calibration of the consequence evaluator."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_policy import COMPLETION_LANES
from spider.consequence_calibration_187 import (
    CALIBRATION_CEILING,
    FOCUSED_UNIQUE,
    KNOWN_ROUTE_GUIDANCE_USED,
    PRODUCTION_CEILING,
    audit_known_187_bound,
    choose_calibration_verdict,
    replay_autonomous_187,
    resolve_control_187,
    search_control_187_ceiling187,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.research_actions import is_deal
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "consequence_calibration_187.py"
SCRIPT = ROOT / "research" / "consequence_calibration_187_v0_93.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_control_replay_and_bound_audit():
    opening = opening_state()
    replay = replay_autonomous_187(opening)
    assert replay["ok"]
    assert replay["g"] == 187
    assert replay["n_deal"] == 5
    acts = parse_moves_file(V074)
    assert sum(1 for a in acts if is_deal(a)) == 5
    assert replay_actions(opening.clone(), list(acts)) == 187
    ctrl = resolve_control_187(opening)
    assert ctrl["ok"]
    assert ctrl["g"] == 130
    assert ctrl["pre_g"] == 129
    assert ctrl["assembly_h"] == 41
    assert ctrl["assembly_f"] == 171
    assert ctrl["slack_187"] == 16
    assert ctrl["n_deal"] == 5
    assert ctrl["foundations"] == 2
    assert ctrl["known_route_guidance_used"] is False
    audit = audit_known_187_bound(opening)
    assert audit["n_post_sd5"] > 0
    assert audit["max_f"] is not None
    assert int(audit["max_f"]) <= 187
    assert audit["n_violations"] == 0
    assert audit["ok"]
    assert audit["known_route_guidance_used"] is False
    assert KNOWN_ROUTE_GUIDANCE_USED is False


def test_search_contract_firewall_and_verdicts():
    assert CALIBRATION_CEILING == 187
    assert PRODUCTION_CEILING == 186
    assert FOCUSED_UNIQUE == 800_000
    src = inspect.getsource(search_control_187_ceiling187)
    assert "cost_ceiling=int(cost_ceiling)" in src
    assert "190" not in src
    assert "parse_moves_file" not in src
    assert "V074" not in src
    assert "4925153_autonomous_v0_74" not in src
    assert "continuation_table=None" in src
    assert "search_foundation_cashout" not in src
    assert "lane_names=COMPLETION_LANES" in src
    assert "horizon" in COMPLETION_LANES
    assert KNOWN_ROUTE_GUIDANCE_USED is False
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    script = _text(SCRIPT)
    assert "NOVEL_A" not in script
    assert "CALIBRATION_CEILING" in script
    assert "retrospective_route_hits" in script
    assert script.find("print(\"AUDIT bound") < script.find("print(\n        f\"SEARCH ceiling") or (
        "AUDIT bound along known 187 route" in script
        and script.find("AUDIT bound along known 187 route") < script.find("SEARCH ceiling=")
    )
    assert "replay_ok" in script
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v093 = ROOT / "solutions" / "4925153_autonomous_v0_93.moves"
    if v093.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v093))
        assert g is not None and g <= 186
    v, _ = choose_calibration_verdict({"bound_failure": True, "solved": False})
    assert v == "CALIBRATION_187_BOUND_FAILURE"
    v2, _ = choose_calibration_verdict({"solved": True, "replay_ok": True, "solution_g": 187, "incumbent_g": 187})
    assert v2 == "CALIBRATION_187_REDISCOVERED"
    v3, _ = choose_calibration_verdict({"solved": False, "max_foundations": 3, "incumbent_g": 187})
    assert v3 == "CALIBRATION_187_DEPTH_LIMITED"
    assert inspect.getsource(strategic_lane_keys)
    assert "abort_when=tracker.abort_when" in src
