"""v0.90 focused endgame from the v0.89 f172 mobility root."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.assembly_policy import COMPLETION_LANES
from spider.exhaustive_post_f2_prep import select_exhaustive_rollout
from spider.f172_mobility_focused_endgame import (
    CLOSED_GUARD,
    FOCUSED_CEILING,
    FOCUSED_UNIQUE,
    choose_f172_verdict,
    compare_root_identities,
    inspect_f172_post,
    load_f172_mobility_candidate,
    reconstruct_f172_mobility_root,
    search_f172_mobility_focused,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.post_f2_predeal_preparation import immediate_deal_control, reconstruct_root_a, reconstruct_root_b
from spider.research_actions import as_actions, is_deal, stock_rows, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f172_mobility_focused_endgame.py"
SCRIPT = ROOT / "research" / "f172_mobility_focused_endgame_v0_90.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
BOUND = ROOT / "src" / "spider" / "assembly_lower_bound.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_f172_candidate_telemetry_and_distinctness():
    src = inspect.getsource(load_f172_mobility_candidate)
    assert "53504b31" not in src
    assert "selection_role" in src and "f172_mobility" in src
    cand = load_f172_mobility_candidate()
    assert cand["ok"], cand.get("reason")
    assert cand["source"] == "NEW_G128_F2"
    assert cand["prep_delta_g"] == 2
    assert cand["post_g"] == 131
    assert cand["assembly_h"] == 41
    assert cand["assembly_f"] == 172
    assert cand["slack"] == 14
    assert cand["legal"] == 10
    assert cand["foundations"] == 2
    assert cand["face_down"] == 2
    assert cand["viable"] is True
    insp = inspect_f172_post(cand["post_digest"], g=131)
    assert insp["ok"]
    assert insp["g"] == 131
    assert insp["foundations"] == 2
    assert insp["face_down"] == 2
    assert insp["assembly_h"] == 41
    assert insp["assembly_f"] == 172
    assert insp["slack"] == 14
    assert insp["legal"] == 10
    assert insp["stock_rows"] == 0
    assert insp["can_deal"] is False
    assert insp["ordered_digest"] == cand["post_digest"]
    assert insp["ident"] == cand["ident"]
    pre = unpack_state(bytes.fromhex(cand["pre_digest"]))
    assert stock_rows(pre) == 1
    assert pre.can_deal()
    assert pack_state(pre).hex() == cand["pre_digest"]
    opening = opening_state()
    a = reconstruct_root_a(opening)
    b = reconstruct_root_b(opening)
    ca = immediate_deal_control(a)
    cb = immediate_deal_control(b)
    assert cand["post_digest"] != ca["post_digest"]
    assert cand["post_digest"] != cb["post_digest"]
    assert cand["ident"] != ca["ident"]
    assert cand["ident"] != cb["ident"]
    assert ca["post_g"] == 129 and ca["assembly_h"] == 42 and ca["assembly_f"] == 171
    assert cb["post_g"] == 130 and cb["assembly_h"] == 41 and cb["assembly_f"] == 171
    assert "f172_mobility" in inspect.getsource(select_exhaustive_rollout)


def test_prefix_replay_one_root_policy_and_firewall():
    opening = opening_state()
    rec = reconstruct_f172_mobility_root(opening)
    assert rec["ok"], rec.get("reason")
    assert rec["g"] == 131
    assert rec["pre_g"] == 130
    assert rec["prep_delta_g"] == 2
    assert rec["n_deal"] == 5
    assert rec["assembly_h"] == 41
    assert rec["assembly_f"] == 172
    assert rec["slack"] == 14
    assert rec["legal"] == 10
    assert rec["foundations"] == 2
    assert rec["face_down"] == 2
    assert rec["stock_rows"] == 0
    cand = load_f172_mobility_candidate()
    acts = as_actions(rec["full_actions"])
    end = opening.clone()
    g = replay_actions(end, list(acts))
    assert g == 131
    assert pack_state(end).hex() == rec["ordered_digest"] == cand["post_digest"]
    assert pack_whole_game_identity(end).hex() == rec["whole_game_identity"] == cand["ident"]
    assert stock_rows(end) == 0
    assert not end.can_deal()
    assert sum(1 for a in acts if is_deal(a)) == 5
    assert rec["pre_digest"] == cand["pre_digest"]
    cmp_ = compare_root_identities(opening, rec)
    assert cmp_["new_vs_a_digest"] and cmp_["new_vs_a_ident"]
    assert cmp_["new_vs_187_digest"] and cmp_["new_vs_187_ident"]
    src = inspect.getsource(search_f172_mobility_focused)
    assert "initial_roots=[root]" in src
    assert "continuation_table=None" in src
    assert "search_foundation_cashout" not in src
    assert "run_rollout" not in src
    assert "is_known_closed" not in src
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
    assert "Hearts" not in text
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
    opening2 = opening_state()
    assert replay_actions(opening2.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening2.clone(), parse_moves_file(CANON)) == 172
    v090 = ROOT / "solutions" / "4925153_autonomous_v0_90.moves"
    if v090.exists():
        g2 = replay_actions(opening2.clone(), parse_moves_file(v090))
        assert g2 is not None and g2 < 187
    v, _ = choose_f172_verdict({"solved": False, "incumbent_g": 187, "max_foundations": 4, "cheap_F": {"4": {"f": 181, "viable": True}}})
    assert v == "F172_MOBILITY_DEEP_ENDGAME"
    v2, _ = choose_f172_verdict({
        "solved": False,
        "incumbent_g": 187,
        "max_foundations": 3,
        "cheap_F": {"3": {"g": 141, "f": 174}},
        "first_F": {"3": {"g": 148, "f": 177}},
        "minf_F": {"3": {"f": 174}},
    })
    assert v2 == "F172_MOBILITY_ROLLOUT_OVERSTATED"
    assert "replay_ok" in script
    assert inspect.getsource(stock_empty_assembly_h)
    st = unpack_state(bytes.fromhex(cand["post_digest"]))
    assert len(tableau_actions(st)) == 10
