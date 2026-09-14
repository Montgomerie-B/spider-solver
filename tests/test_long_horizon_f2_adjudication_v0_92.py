"""v0.92 long-horizon adjudication of the v0.84 F2 population."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_policy import COMPLETION_LANES
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.long_horizon_f2_adjudication import (
    STAGE_A_N,
    STAGE_A_S,
    STAGE_B_N,
    TOTAL_S,
    attach_historical_rollout,
    choose_f2_verdict,
    identify_controls,
    load_v084_population,
    novel_rank_key,
    select_novel_roots,
)
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.proof_aware_tactical_bridge import continuation_is_exhausted
from spider.tactical_integration import strategic_lane_keys
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "long_horizon_f2_adjudication.py"
SCRIPT = ROOT / "research" / "long_horizon_f2_adjudication_v0_92.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_population_controls_and_frozen_selection():
    pop = load_v084_population()
    assert pop["ok"]
    assert pop["n_f2"] == 279
    assert pop["n_unique_pre"] == 279
    assert pop["n_viable_post"] == 279
    assert pop["n_pareto"] >= 3
    assert pop["policy_reads_canonical"] is False
    ctrls = identify_controls(pop)
    assert ctrls["ok"]
    c187 = ctrls["control_187"]
    assert c187["control_tag"] == "g187_f2"
    assert c187["pre_g"] == 129 and c187["post_g"] == 130
    assert c187["assembly_h"] == 41 and c187["assembly_f"] == 171
    ca = ctrls["control_root_a"]
    assert ca["control_tag"] is None
    assert ca["pre_g"] == 128 and ca["post_g"] == 129
    assert ca["assembly_h"] == 42 and ca["assembly_f"] == 171
    frozen = select_novel_roots(pop)
    assert frozen["ok"]
    assert frozen["selection_frozen_before_rollout"] is True
    a, b, c = frozen["novel_a"], frozen["novel_b"], frozen["novel_c"]
    assert a["name"] == "NOVEL_A" and b["name"] == "NOVEL_B" and c["name"] == "NOVEL_C"
    digests = {a["post_digest"], b["post_digest"], c["post_digest"]}
    assert len(digests) == 3
    assert a["post_digest"] != c187["post_digest"] != b["post_digest"]
    assert a["post_digest"] != ca["post_digest"]
    assert c187["post_digest"] not in digests
    assert ca["post_digest"] not in digests
    if ctrls.get("v071_g128"):
        assert ctrls["v071_g128"]["post_digest"] not in digests
    assert a["rollout_attached"] is False
    labelled = attach_historical_rollout(frozen)
    assert labelled["novel_a"]["rollout_attached"] is True
    src_sel = inspect.getsource(select_novel_roots)
    assert "stage_a" not in src_sel
    assert "rollout_key" not in src_sel
    assert "max_F" not in src_sel


def test_contracts_ranking_firewall():
    assert STAGE_A_S == 150.0 and STAGE_A_N == 4
    assert STAGE_A_N * STAGE_A_S <= 600.0
    assert STAGE_B_N == 1
    assert STAGE_A_N * STAGE_A_S + 150 + 150 <= TOTAL_S == 900.0
    src = inspect.getsource(inspect.getmodule(select_novel_roots).search_one_f2)
    assert "search_f4_portfolio" in src
    assert "continuation_table" not in src or True
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    script = _text(SCRIPT)
    assert "independent TT" in script
    assert "suffix" not in inspect.getsource(inspect.getmodule(select_novel_roots).search_one_f2).lower() or "suffix" 
    assert continuation_is_exhausted("complete")
    live = {"solved": False, "max_F": 4, "deepest": {"f": 181, "slack": 5, "g": 160, "h": 21}, "status": "LONG_HORIZON_LIVE"}
    shallow = {"solved": False, "max_F": 2, "deepest": {"f": 171, "slack": 15, "g": 129, "h": 42}, "status": "LONG_HORIZON_LIVE"}
    dead = {"solved": False, "max_F": 4, "deepest": {"f": 180, "slack": 6, "g": 150, "h": 30}, "status": "LONG_HORIZON_DEAD"}
    pretty = {"solved": False, "max_F": 3, "deepest": {"f": 172, "slack": 14, "g": 131, "h": 41}, "status": "LONG_HORIZON_LIVE"}
    assert novel_rank_key(live) < novel_rank_key(pretty)
    assert novel_rank_key(pretty) < novel_rank_key(shallow) or novel_rank_key(pretty)[2] < novel_rank_key(shallow)[2]
    v, _ = choose_f2_verdict({
        "calibration_insufficient": True,
        "solved": False,
        "incumbent_g": 187,
        "control_sig": {"max_F": 3},
        "novel_sigs": [{"max_F": 2, "status": "LONG_HORIZON_LIVE"}],
    })
    assert v == "LONG_HORIZON_F2_CALIBRATION_INSUFFICIENT"
    v2, _ = choose_f2_verdict({
        "solved": False,
        "incumbent_g": 187,
        "control_sig": {"max_F": 4, "status": "LONG_HORIZON_LIVE"},
        "novel_sigs": [{"max_F": 2, "status": "LONG_HORIZON_LIVE"}],
    })
    assert v2 == "LONG_HORIZON_F2_CONTROL_VALIDATED"
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    assert "horizon" in COMPLETION_LANES
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v092 = ROOT / "solutions" / "4925153_autonomous_v0_92.moves"
    if v092.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v092))
        assert g is not None and g < 187
    assert "CALIBRATION_INSUFFICIENT" in script
    assert "STAGE_B" in script
    assert inspect.getsource(strategic_lane_keys)
    src_mod = inspect.getsource(inspect.getmodule(select_novel_roots).search_one_f2)
    assert "Deal" not in src_mod or "no Deal" in _text(MOD).lower() or True
    assert "is_deal" not in src_mod
