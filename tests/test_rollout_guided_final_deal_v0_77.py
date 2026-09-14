"""Rollout-guided final-Deal selection v0.77."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.final_deal_rollout import (
    ROLLOUT_CEILING,
    ROLLOUT_RESERVE_S,
    ROWS0_MAX,
    ROWS0_TARGET,
    STAGE_A_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    apply_sd5,
    build_rows0_portfolio,
    choose_guided_verdict,
    guided_final_deal_transition,
    pre_sd5_from_actions,
    rollout_key,
    run_rollout,
    select_attached_rollout_candidates,
    verify_root_ancestry,
)
from spider.foundation_cashout import TACTICAL_CEILING
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import as_actions, is_deal, stock_rows
from spider.state_convergence import V073_F2_DIGEST, V074_MOVES
from spider.tactical_integration import search_integrated_tactical, search_rollout_guided
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "final_deal_rollout.py"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
SCRIPT = ROOT / "research" / "rollout_guided_final_deal_v0_77.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
CONT = ROOT / "src" / "spider" / "autonomous_continuations.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _attached(i, *, cat, g, F=0, fd=2, ckpt=False, target=None, ident=None):
    return {
        "g": g,
        "stock_rows": 1,
        "ordered_digest": ident or f"{i:064x}",
        "ident": ident or f"id{i}",
        "full_actions": [("deal",)] * 4,
        "foundations": F,
        "face_down": fd,
        "portfolio_cat": cat,
        "from_incumbent_ckpt": ckpt,
        "tactical_target": target,
        "assembly_f": 200 - i,
        "assembly_h": 50,
        "legal_tableau": i,
        "categories": [cat],
    }


def test_constants_and_canonical_firewall():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == ROLLOUT_CEILING
    assert STAGE_A_N == 8 and STAGE_B_N == 4
    assert STAGE_A_S == 10.0 and STAGE_B_S == 10.0
    assert STAGE_A_N * STAGE_A_S + STAGE_B_N * STAGE_B_S <= ROLLOUT_RESERVE_S
    assert ROWS0_TARGET == 32 and ROWS0_MAX == 64
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
    src_i = inspect.getsource(search_integrated_tactical)
    assert "guided_final_deal_transition" not in src_i
    assert "final_deal_rollout" not in src_i
    src_g = inspect.getsource(search_rollout_guided)
    assert "guided_final_deal_transition" in src_g
    src_e = inspect.getsource(search_epoch_portfolio)
    assert "final_deal_rollout_fn=None" in src_e
    assert "rows == 1" in src_e
    assert "rows == 2" not in src_e.split("final_deal_rollout_fn")[1][:800]
    script = _text(SCRIPT)
    if script:
        assert script.find("EVAL canonical") > script.find("search_rollout_guided")
        assert "machine experiment frozen" in script


def test_machine_only_candidate_selection_caps():
    attached = []
    cats = [
        "tactical_cashout",
        "incumbent",
        "post_deal_operational",
        "post_deal_consolidation",
        "post_deal_mobility",
        "post_deal_reception",
        "post_deal_pareto",
        "cheap",
    ]
    for i in range(20):
        cat = cats[i] if i < len(cats) else "cheap"
        attached.append(
            _attached(
                i,
                cat=cat,
                g=100 + i if i else 130,
                F=2 if cat == "tactical_cashout" else i % 3,
                ckpt=cat == "incumbent",
                target="d" if cat == "tactical_cashout" else None,
            )
        )
    sel = select_attached_rollout_candidates(attached, n=8, ceiling=186)
    assert len(sel) <= 8
    roles = [s.get("role") for s in sel]
    assert "tactical_cashout" in roles
    assert "incumbent" in roles
    gs = [s["pre_g"] for s in sel]
    assert gs != sorted(gs)
    assert all(int(s["pre_g"]) <= 186 for s in sel)
    assert len({s["pre_digest"] for s in sel}) == len(sel)


def test_frozen_rollout_key_and_stage_budgets():
    a = {
        "solved": False,
        "max_F": 3,
        "cheap_F": {"3": {"g": 160, "f": 180}},
        "min_h": 20,
        "best_mobility": 10,
        "min_boundaries": 8,
        "post_g": 130,
    }
    assert rollout_key(a) == rollout_key(dict(a))
    better_f = dict(a, max_F=4)
    assert rollout_key(better_f) < rollout_key(a)
    cheaper_f = dict(a, cheap_F={"3": {"g": 160, "f": 179}})
    assert rollout_key(cheaper_f) < rollout_key(a)
    src = inspect.getsource(guided_final_deal_transition)
    assert "STAGE_B_N" in src
    assert "STAGE_A_S" in src
    assert "time_a = min(STAGE_A_S" in src
    assert "time_b = min(STAGE_B_S" in src
    src_r = inspect.getsource(run_rollout)
    assert "continuation_table=None" in src_r
    assert "epoch_augment_fn=None" in src_r
    assert "incumbent_by_rows={}" in src_r
    sched = _text(SCHED)
    assert "min(120.0" in sched
    assert ROLLOUT_RESERVE_S == 120.0


def test_portfolio_cap_static_root_and_descendants_eligible():
    posts = [
        {
            "post_g": 130,
            "post_digest": f"d{i}",
            "whole_game_identity": f"i{i}",
            "ident": f"i{i}",
            "full_actions": [("deal",)],
            "foundations": 2 if i == 0 else 0,
            "face_down": 2,
            "assembly_h": 40,
            "assembly_f": 170,
            "legal": 5,
            "pre_g": 129,
            "pre_digest": f"p{i}",
            "role": "tactical_cashout" if i == 0 else "x",
        }
        for i in range(3)
    ]
    stage_b = [
        {
            "post_digest": "d0",
            "descendants": [
                {
                    "g": 140 + j,
                    "ordered_digest": f"z{j}",
                    "ident": f"zid{j}",
                    "whole_game_identity": f"zid{j}",
                    "full_actions": [("deal",), (0, 1, 1)],
                    "foundations": 2 + (j % 3),
                    "face_down": 1,
                    "assembly_h": 20,
                    "assembly_f": 160,
                    "parent_root": "d0",
                    "lineage": ["rollout_descendant"],
                    "portfolio_cat": "rollout_descendant",
                }
                for j in range(80)
            ],
        }
    ]
    port = build_rows0_portfolio(original_posts=posts, stage_b=stage_b, target=32, hard_max=64)
    assert len(port) <= 64
    assert len(port) <= 32
    idents = {r["ident"] for r in port}
    assert "i0" in idents
    assert any(r.get("parent_root") == "d0" and r["ident"].startswith("zid") for r in port)
    cats = {r.get("portfolio_cat") for r in port}
    assert "post_deal_control" in cats
    assert "rollout_descendant" in cats


def test_proof_prune_continuation_and_incumbent_replay():
    kern = _text(KERN)
    assert "int(g) + h > int(ceiling)" in kern
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    src_r = inspect.getsource(run_rollout)
    assert "continuation_table=None" in src_r
    cont = _text(CONT)
    assert "pack_state" in cont
    assert "canonical" not in cont.lower() or "exclude" in cont.lower() or "AUTONOMOUS_SOURCES" in cont
    assert stock_empty_assembly_h(opening, 0) == 0
    v077 = ROOT / "solutions" / "4925153_autonomous_v0_77.moves"
    if v077.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v077))
        assert g is not None and g < 187


def test_absolute_g_ancestry_and_sps1_replay():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    pre = pre_sd5_from_actions(opening, parse_moves_file(V074_MOVES if V074_MOVES.exists() else V074))
    assert pre["ok"] and pre["stock_rows"] == 1
    post = apply_sd5(opening, pre)
    assert post["ok"] and post["stock_rows"] == 0
    assert post["post_g"] == pre["pre_g"] + post["deal_cost"]
    assert post["post_g"] == 130
    assert post["foundations"] == 2
    root = {
        "g": post["post_g"],
        "ordered_digest": post["post_digest"],
        "full_actions": post["full_actions"],
    }
    assert verify_root_ancestry(opening, root)
    end = opening.clone()
    g = replay_actions(end, as_actions(post["full_actions"]))
    assert g == 130
    assert stock_rows(end) == 0
    assert pack_state(end).hex() == post["post_digest"]
    sps = pack_whole_game_identity(end).hex()
    assert sps == post["whole_game_identity"]
    assert sum(1 for a in as_actions(post["full_actions"]) if is_deal(a)) == 5
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    assert pre["pre_digest"] != V073_F2_DIGEST or post["post_g"] == 130


def test_verdicts_and_no_suffix_in_rollout():
    deep = {
        "elapsed_s": 900,
        "incumbent_g": 187,
        "max_foundations": 3,
        "rows0": {"max_foundations": 3},
        "rollout": {"elapsed_s": 120, "n_selected": 8, "prefilter_n": 264, "stage_a": [{"max_F": 2}]},
    }
    v, _ = choose_guided_verdict(deep)
    assert v == "ROLLOUT_GUIDED_REACHES_DEEP_ENDGAME"
    sel = {
        "elapsed_s": 900,
        "incumbent_g": 187,
        "max_foundations": 2,
        "rows0": {"max_foundations": 2},
        "rollout": {"elapsed_s": 120, "n_selected": 8, "prefilter_n": 264, "stage_a": [{"max_F": 3}]},
    }
    v, _ = choose_guided_verdict(sel)
    assert v == "ROLLOUT_GUIDED_SELECTS_STRONG_ROOT_NO_CONVERSION"
    lost = {
        "elapsed_s": 900,
        "incumbent_g": 187,
        "max_foundations": 2,
        "rows0": {"max_foundations": 2},
        "rollout": {"elapsed_s": 10, "n_selected": 0, "prefilter_n": 10, "stage_a": []},
    }
    v, _ = choose_guided_verdict(lost)
    assert v == "ROLLOUT_GUIDED_SIGNAL_LOST_INTEGRATION"
    over = {
        "elapsed_s": 900,
        "incumbent_g": 187,
        "rollout": {"elapsed_s": 400, "n_selected": 8, "prefilter_n": 10},
    }
    v, _ = choose_guided_verdict(over)
    assert v == "ROLLOUT_GUIDED_OVERHEAD_FAILURE"
    src = inspect.getsource(run_rollout)
    assert "continuation_table=None" in src
    assert "No suffixes" in (run_rollout.__doc__ or src)
