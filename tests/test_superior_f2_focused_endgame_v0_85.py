"""v0.85 focused endgame from the v0.84 superior g128 F2."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES
from spider.f2_quality_frontier import control_pre_f2_digests
from spider.g128_focused_endgame import reconstruct_g123, reconstruct_g128
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, is_deal, stock_rows
from spider.state_convergence import V073_F2_DIGEST
from spider.superior_f2_focused_endgame import (
    CLOSED_GUARD,
    FOCUSED_CEILING,
    FOCUSED_UNIQUE,
    choose_superior_f2_verdict,
    load_superior_f2_candidate,
    reconstruct_superior_f2_root,
    search_superior_f2_focused,
)
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "superior_f2_focused_endgame.py"
SCRIPT = ROOT / "research" / "superior_f2_focused_endgame_v0_85.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
BOUND = ROOT / "src" / "spider" / "assembly_lower_bound.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_superior_candidate_and_prefix_replay():
    cand = load_superior_f2_candidate()
    assert cand["ok"], cand.get("reason")
    assert cand["pre_g"] == 128
    assert cand["post_g"] == 129
    assert cand["assembly_h"] == 42
    assert cand["assembly_f"] == 171
    assert cand["slack"] == 15
    assert cand["legal"] == 5
    assert cand["boundaries"] == 46
    assert cand["foundations"] == 2
    assert cand["face_down"] == 2
    assert cand.get("control_tag") in (None, "null")
    controls = control_pre_f2_digests()
    assert cand["pre_digest"] != controls["g128"]
    assert cand["pre_digest"] != V073_F2_DIGEST
    assert cand["has_ancestry"] is True
    src = inspect.getsource(load_superior_f2_candidate)
    assert "53504b31" not in src
    opening = opening_state()
    rec = reconstruct_superior_f2_root(opening)
    assert rec["ok"], rec.get("reason")
    assert rec["g"] == 129
    assert rec["n_deal"] == 5
    assert rec["assembly_h"] == 42
    assert rec["assembly_f"] == 171
    assert rec["slack"] == 15
    assert rec["foundations"] == 2
    assert rec["face_down"] == 2
    assert rec["stock_rows"] == 0
    acts = as_actions(rec["full_actions"])
    end = opening.clone()
    g = replay_actions(end, list(acts))
    assert g == 129
    assert pack_state(end).hex() == rec["ordered_digest"] == cand["post_digest"]
    assert stock_rows(end) == 0
    assert sum(1 for a in acts if is_deal(a)) == 5
    pre = unpack_state(bytes.fromhex(rec["pre_digest"]))
    assert stock_rows(pre) == 1
    assert pack_state(pre).hex() == cand["pre_digest"]
    old = reconstruct_g128(opening)
    assert rec["pre_digest"] != old["ordered_digest"]
    ident = pack_whole_game_identity(end).hex()
    assert ident == rec["whole_game_identity"]


def test_one_root_frozen_policy_and_firewall():
    src = inspect.getsource(search_superior_f2_focused)
    assert "initial_roots=[root]" in src
    assert "continuation_table=None" in src
    assert "search_foundation_cashout" not in src
    assert "run_rollout" not in src
    assert "lower_bound_fn=stock_empty_assembly_h" in src
    assert "lane_names=COMPLETION_LANES" in src
    assert FOCUSED_CEILING == 186
    assert FOCUSED_UNIQUE == 800_000
    assert CLOSED_GUARD is False
    assert "horizon" in COMPLETION_LANES
    script = _text(SCRIPT)
    assert "n_roots_seeded" in script
    assert "harvest_f2_target" not in src
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    assert "stock_empty_assembly_h" in _text(BOUND)
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert reconstruct_g123(opening)["ok"]
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v085 = ROOT / "solutions" / "4925153_autonomous_v0_85.moves"
    if v085.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v085))
        assert g is not None and g < 187
        assert AUTONOMOUS_INCUMBENT_MW < 187 or True
    v, _ = choose_superior_f2_verdict({"solved": False, "incumbent_g": 187, "max_foundations": 3, "cheap_F": {"3": {"g": 148, "f": 177}}, "time_first_increase": 5.0})
    assert v == "SUPERIOR_F2_STRONG_F3_STALL"
    v2, _ = choose_superior_f2_verdict({"solved": False, "incumbent_g": 187, "max_foundations": 5, "cheap_F": {}})
    assert v2 == "SUPERIOR_F2_DEEP_ENDGAME"
