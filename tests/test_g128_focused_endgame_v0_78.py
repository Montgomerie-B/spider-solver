"""Focused g128 tactical-F2 endgame v0.78."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.foundation_cashout import TACTICAL_CEILING
from spider.g128_focused_endgame import (
    CONT71,
    FOCUSED_CEILING,
    POST_SD5_G,
    V071_JSON,
    apply_g128_deal,
    expected_g123_digest,
    expected_v076_post_digest,
    load_v071_continuation,
    reconstruct_g123,
    reconstruct_g128,
    reconstruct_g128_root,
    search_g128_focused,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.state_convergence import V073_F2_DIGEST
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "g128_focused_endgame.py"
SCRIPT = ROOT / "research" / "g128_focused_endgame_v0_78.py"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
V077_SOL = ROOT / "solutions" / "4925153_autonomous_v0_77.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_firewall_and_caps():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == FOCUSED_CEILING
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    assert TACTICAL_CEILING == 191
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    src = inspect.getsource(search_g128_focused)
    assert "continuation_table=None" in src
    assert "incumbent_by_rows={}" in src
    assert "epoch_augment_fn=None" in src
    assert "cost_ceiling=FOCUSED_CEILING" in src
    assert "stock_empty_assembly_h" in src
    kern = _text(KERN)
    assert "int(g) + h > int(ceiling)" in kern
    script = _text(SCRIPT)
    if script:
        assert "search_rollout_guided" not in script
        assert "EVAL canonical" not in script or script.find("SEARCH focused") < script.find("EVAL canonical")


def test_g123_matches_v071_root():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    ck = reconstruct_g123(opening)
    assert ck["ok"]
    assert ck["g"] == 123
    assert ck["foundations"] == 1
    assert ck["face_down"] == 2
    assert ck["stock_rows"] == 1
    assert ck["ordered_digest"] == expected_g123_digest()
    v071 = json.loads(V071_JSON.read_text(encoding="utf-8"))
    root = v071.get("tactical_root") or (v071.get("path_trace") or {}).get("root")
    assert ck["ordered_digest"] == root["ordered_digest"]
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187


def test_stored_tactical_five_tableau_actions():
    cont = load_v071_continuation()
    tac = as_actions(cont["tactical_actions"])
    assert len(tac) == 5
    assert all(not is_deal(a) for a in tac)
    assert cont["root_g"] == 123
    assert cont["terminal_g"] == 128
    assert cont["delta_g"] == 5
    assert cont["target_suit"] == "d"


def test_g128_replay_and_digest():
    opening = opening_state()
    rec = reconstruct_g128(opening)
    assert rec["ok"]
    assert rec["g"] == 128
    assert rec["foundations"] == 2
    assert rec["face_down"] == 2
    assert rec["stock_rows"] == 1
    assert rec["n_tactical"] == 5
    assert rec["delta_g"] == 5
    assert rec["ordered_digest"] == load_v071_continuation()["terminal_digest"]
    assert rec["same_as_187_f2"] is False
    assert rec["ordered_digest"] != V073_F2_DIGEST
    end = opening.clone()
    g = replay_actions(end, as_actions(rec["full_actions"]))
    assert g == 128
    assert stock_rows(end) == 1
    assert len(tableau_actions(end)) >= 1


def test_exact_sd5_and_v076_post_root():
    opening = opening_state()
    post = apply_g128_deal(opening)
    assert post["ok"]
    assert post["g"] == POST_SD5_G == 129
    assert post["deal_cost"] == 1
    assert post["stock_rows"] == 0
    assert post["foundations"] == 2
    assert post["face_down"] == 2
    assert post["legal_tableau"] == 5
    assert post["assembly_h"] == 43
    assert post["assembly_f"] == 172
    hist = expected_v076_post_digest()
    assert hist is not None
    assert post["ordered_digest"] == hist
    assert post["v076_digest_match"] is True
    root = reconstruct_g128_root(opening)
    assert root["ok"]
    ident = pack_whole_game_identity
    end = opening.clone()
    g = replay_actions(end, as_actions(post["full_actions"]))
    assert g == 129
    assert stock_rows(end) == 0
    assert ident(end).hex() == post["whole_game_identity"]
    assert stock_empty_assembly_h(end, 129) == 43
    deals = sum(1 for a in as_actions(post["full_actions"]) if is_deal(a))
    assert deals == 5


def test_verdict_classifiers():
    from spider.g128_focused_endgame import choose_g128_verdict, choose_rollout_assessment

    limited = {
        "incumbent_g": 187,
        "max_foundations": 3,
        "solved": False,
        "frontier_list": [{"F": 3, "g": 141}],
        "snapshots": [{"label": "t30", "max_F": 3}],
    }
    v, _ = choose_g128_verdict(limited)
    assert v == "G128_FOCUSED_SEARCH_LIMITED"
    a, _ = choose_rollout_assessment(limited)
    assert a == "LONG_SEARCH_STILL_INCONCLUSIVE"
    improved = dict(limited, solved=True, replay_ok=True, solution_g=180)
    v, _ = choose_g128_verdict(improved)
    assert v == "G128_FOCUSED_COST_IMPROVED"


def test_incumbent_unchanged_without_verified_improvement():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    v078 = ROOT / "solutions" / "4925153_autonomous_v0_78.moves"
    if v078.exists():
        opening = opening_state()
        g = replay_actions(opening.clone(), parse_moves_file(v078))
        assert g is not None and g < 187
        end = opening.clone()
        replay_actions(end, parse_moves_file(v078))
        assert end.is_solved()
        assert sum(1 for a in parse_moves_file(v078) if is_deal(a)) == 5
    else:
        assert AUTONOMOUS_INCUMBENT_MW == 187
    assert not V077_SOL.exists()
    assert replay_actions(opening_state(), parse_moves_file(CANON)) == 172
