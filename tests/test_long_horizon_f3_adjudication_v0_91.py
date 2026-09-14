"""v0.91 long-horizon adjudication of the v0.90 F3 basin."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f172_mobility_focused_endgame import (
    V090_F3_SUMMARY_FORMATTING_FIX,
    format_v090_f3_summary,
)
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.long_horizon_f3_adjudication import (
    PORTFOLIO_MAX,
    ROOT_SPECS,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    STAGE_C_N,
    STAGE_C_S,
    STAGE_D_N,
    TACTICAL_MAX_S,
    TOTAL_S,
    choose_long_horizon_verdict,
    fresh_targets,
    gateway_class,
    load_v090_f3_roots,
    select_adjudication_portfolio,
    select_stage_d,
    stage_c_key,
    v090_f3_summary_from_artefact,
    verify_all_v090_f3_roots,
)
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.proof_aware_tactical_bridge import continuation_is_exhausted, interpret_continuation_stop, probe_proof_aware_target, target_future_key
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "long_horizon_f3_adjudication.py"
SCRIPT = ROOT / "research" / "long_horizon_f3_adjudication_v0_91.py"
F172 = ROOT / "src" / "spider" / "f172_mobility_focused_endgame.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_v090_f3_roots_and_summary_not_cross_wired():
    assert V090_F3_SUMMARY_FORMATTING_FIX is True
    summary = v090_f3_summary_from_artefact()
    first = summary["first_F3"]
    cheap = summary["cheap_F3"]
    assert first["g"] == 138 and first["h"] == 35 and first["f"] == 173
    assert cheap["g"] == 134 and cheap["h"] == 40 and cheap["f"] == 174
    assert abs(float(first["elapsed_s"]) - 1.17) < 0.05
    assert abs(float(cheap["elapsed_s"]) - 9.94) < 0.05
    assert first["elapsed_s"] != cheap["elapsed_s"]
    assert summary["cross_wired"] is False
    mixed = format_v090_f3_summary(
        {"g": 138, "h": 35, "f": 173, "elapsed_s": 1.17},
        {"g": 134, "h": 40, "f": 174, "elapsed_s": 1.17},
    )
    assert mixed["cross_wired"] is True
    roots = load_v090_f3_roots()
    assert len(roots) == 2
    assert roots[0]["g"] == 138 and roots[1]["g"] == 134
    assert roots[0]["ordered_digest"] != roots[1]["ordered_digest"]
    checked = verify_all_v090_f3_roots()
    assert checked["ok"], [r.get("reason") for r in checked["roots"]]
    assert checked["distinct"]
    a, b = checked["roots"]
    assert a["vs_g141_ident"] and a["vs_g148_ident"]
    assert b["vs_g141_ident"] and b["vs_g148_ident"]
    assert a["ident"] != b["ident"]
    assert a["n_ready"] is not None
    tg = fresh_targets(a)
    assert isinstance(tg, list)
    src = inspect.getsource(fresh_targets)
    assert "Hearts" not in src and "Diamonds" not in src
    assert "rank_ready_suits" in src


def test_stages_portfolio_adjudication_firewall():
    assert STAGE_A_S == 30.0
    assert STAGE_B_S == 30.0 and STAGE_B_N == 4
    assert 2 * 4 * STAGE_A_S + STAGE_B_N * STAGE_B_S <= TACTICAL_MAX_S == 360.0
    assert STAGE_C_S == 90.0 and STAGE_C_N == 4
    assert STAGE_C_N * STAGE_C_S <= 360.0
    assert STAGE_D_N == 2
    assert PORTFOLIO_MAX == 4
    assert TACTICAL_MAX_S + STAGE_C_N * STAGE_C_S + 180 <= TOTAL_S == 900.0
    src_key = inspect.getsource(target_future_key)
    assert "g+h" in src_key.replace(" ", "") or "int(g) + h" in src_key
    assert src_key.index("cover") < src_key.index("inaccessible")
    src_probe = inspect.getsource(probe_proof_aware_target)
    assert "search_foundation_cashout" not in src_probe
    src_mod = _text(MOD)
    assert "is_deal" not in inspect.getsource(fresh_targets)
    assert continuation_is_exhausted("complete")
    dead = {"status": "LONG_HORIZON_DEAD", "solved": False, "max_F": 4, "deepest": {"f": 181, "slack": 5, "g": 160, "h": 21}, "best_mobility": 10}
    live = {"status": "LONG_HORIZON_LIVE", "solved": False, "max_F": 5, "deepest": {"f": 186, "slack": 0, "g": 172, "h": 14}, "best_mobility": 8}
    pretty = {"status": "LONG_HORIZON_LIVE", "solved": False, "max_F": 4, "deepest": {"f": 180, "slack": 6, "g": 150, "h": 30}, "best_mobility": 40}
    assert stage_c_key(live) < stage_c_key(pretty)
    assert stage_c_key(pretty) < stage_c_key(dead)
    d_sel = select_stage_d([dead, live, pretty], k=2)
    assert all(s["status"] == "LONG_HORIZON_LIVE" for s in d_sel)
    assert dead not in d_sel
    assert len(d_sel) <= 2
    interp = interpret_continuation_stop("complete", solved=False)
    assert interp["exhausted"]
    closed = {"x": {"g": 160}}
    port = select_adjudication_portfolio(
        [
            {"calibration_name": "FIRST_LOWEST_F_F3", "root_g": 138, "root_h": 35, "root_f": 173,
             "viable_terminals": [
                 {"g": 150, "assembly_h": 31, "assembly_f": 181, "slack": 5, "ident": "a", "legal_tableau": 10, "ordered_digest": "d1", "foundations": 4, "face_down": 2, "tactical_target": "s"},
                 {"g": 160, "assembly_h": 20, "assembly_f": 180, "slack": 6, "ident": "x", "legal_tableau": 12, "ordered_digest": "d2", "foundations": 4, "face_down": 2, "tactical_target": "t"},
             ]},
            {"calibration_name": "CHEAPEST_G_F3", "root_g": 134, "root_h": 40, "root_f": 174,
             "viable_terminals": [
                 {"g": 148, "assembly_h": 34, "assembly_f": 182, "slack": 4, "ident": "b", "legal_tableau": 20, "ordered_digest": "d3", "foundations": 4, "face_down": 2, "tactical_target": "u"},
             ]},
        ],
        closed,
        hard_max=4,
    )
    assert all(r.get("ident") != "x" or r.get("closed") for r in port) or "x" not in {r["ident"] for r in port if not r.get("closed")}
    assert len([r for r in port if not r.get("closed")]) <= 4
    v, _ = choose_long_horizon_verdict({"n_viable_f4": 3, "n_live": 0, "n_dead": 3, "max_foundations": 4, "solved": False, "incumbent_g": 187})
    assert v == "LONG_HORIZON_F3_EXHAUSTED"
    v2, _ = choose_long_horizon_verdict({"n_viable_f4": 2, "n_live": 1, "max_foundations": 4, "solved": False, "incumbent_g": 187})
    assert v2 == "LONG_HORIZON_F3_F4_ONLY"
    text = src_mod
    assert "4925153_canonical.moves" not in text
    assert "Hearts" not in text
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    script = _text(SCRIPT)
    assert "STAGE_A_S" in script and "STAGE_C_S" in script
    assert "replay_ok" in script
    assert "is_deal" in script
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v091 = ROOT / "solutions" / "4925153_autonomous_v0_91.moves"
    if v091.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v091))
        assert g is not None and g < 187
    assert inspect.getsource(probe_proof_aware_target)
    assert ROOT_SPECS[0]["json_path"] == ("first_F", "3")
    assert "search_foundation_cashout" in inspect.getsource(__import__("spider.proof_aware_tactical_bridge", fromlist=["_probe_one"])._probe_one)
    assert gateway_class(184) == "STRONG_SURPLUS"
    assert gateway_class(185) == "SURPLUS"
    assert gateway_class(186) == "PROOF_VIABLE"
    assert gateway_class(187) == "RAW_NEXT_FOUNDATION"
    f172 = _text(F172)
    assert "format_v090_f3_summary" in f172
    assert "first F3 g=" in f172
