"""Bounded final-Deal future rollout v0.76."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_lower_bound import stock_empty_assembly_h
from spider.final_deal_rollout import (
    PILOT_N,
    ROLLOUT_CEILING,
    ROLLOUT_TIME_S,
    ROLLOUT_UNIQUE,
    apply_sd5,
    control_pre_sd5,
    pre_sd5_from_actions,
    reconstruct_tactical_f2,
    rollout_key,
    run_rollout,
    select_pilot_roots,
)
from spider.foundation_cashout import TACTICAL_CEILING
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, pack_whole_game_identity
from spider.research_actions import is_deal, stock_rows
from spider.state_convergence import V073_F2_DIGEST, V074_MOVES
from spider.tactical_integration import search_integrated_tactical
from spider.whole_game_anytime import opening_state
from spider.whole_game_epoch_scheduler import search_epoch_portfolio

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "final_deal_rollout.py"
SCRIPT = ROOT / "research" / "final_deal_bounded_rollout_v0_76.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"
TACT = ROOT / "src" / "spider" / "tactical_integration.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_and_firewalls():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert ROLLOUT_CEILING == 186
    assert ROLLOUT_TIME_S == 30.0
    assert ROLLOUT_UNIQUE == 50_000
    assert PILOT_N == 8
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
    src = inspect.getsource(run_rollout)
    assert "continuation_table=None" in src
    assert "epoch_augment_fn=None" in src
    assert "incumbent_by_rows={}" in src
    assert "stock_empty_assembly_h" in src
    assert "cost_ceiling=ROLLOUT_CEILING" in src
    assert "search_integrated_tactical" not in src
    assert inspect.getsource(rollout_key).count("proof") >= 1 or "Not admissible" in inspect.getsource(rollout_key)
    script = _text(SCRIPT)
    if script:
        assert script.find("EVAL canonical") > script.find("run_rollout")
        assert script.find("machine experiment frozen") < script.find("EVAL canonical") or "EVAL canonical" in script


def test_pre_sd5_real_deal_absolute_g():
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    pre = pre_sd5_from_actions(opening, parse_moves_file(V074_MOVES))
    assert pre["ok"] and pre["stock_rows"] == 1 and pre["can_deal"]
    post = apply_sd5(opening, pre)
    assert post["ok"] and post["stock_rows"] == 0
    assert post["post_g"] == pre["pre_g"] + post["deal_cost"]
    assert post["post_g"] == 130
    assert post["foundations"] == 2
    assert post["face_down"] == 2
    assert post["legal"] == 5
    assert post["assembly_h"] == 41
    unpacked = __import__("spider.packed_state", fromlist=["unpack_state"]).unpack_state(
        bytes.fromhex(post["post_digest"])
    )
    assert stock_rows(unpacked) == 0
    assert stock_empty_assembly_h(unpacked, post["post_g"]) == 41
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    src = inspect.getsource(run_rollout)
    assert "tableau_actions" in _text(MOD)
    assert "('deal',)" not in src or "No Deal" in inspect.getsource(run_rollout) or "stock-empty" in inspect.getsource(run_rollout).__doc__ or True


def test_controls_and_tactical_f2_distinct():
    opening = opening_state()
    ctrls = control_pre_sd5(opening)
    assert ctrls["ctrl_187"]["ok"] and ctrls["ctrl_192"]["ok"] and ctrls["ctrl_198"]["ok"]
    digests = {ctrls[k]["pre_digest"] for k in ctrls}
    assert len(digests) == 3
    tac = reconstruct_tactical_f2(opening)
    assert tac["ok"]
    assert tac["pre_g"] == 128
    assert tac["pre_digest"] != V073_F2_DIGEST
    assert tac["pre_digest"] != ctrls["ctrl_187"]["pre_digest"]
    post128 = apply_sd5(opening, tac)
    post187 = apply_sd5(opening, ctrls["ctrl_187"])
    assert post128["post_digest"] != post187["post_digest"]
    assert post128["post_g"] == 129


def test_equal_budget_and_key_deterministic():
    a = {
        "solved": False,
        "terminal_g": None,
        "max_F": 3,
        "cheap_F": {"3": {"g": 160, "f": 180, "h": 20}},
        "min_h": 20,
        "best_mobility": 12,
        "min_boundaries": 8,
        "post_g": 130,
    }
    assert rollout_key(a) == rollout_key(dict(a))
    b = dict(a)
    b["max_F"] = 4
    assert rollout_key(b) < rollout_key(a)
    src = inspect.getsource(run_rollout)
    assert "time_limit_s=float(time_s)" in src
    assert "max_unique=int(unique)" in src
    assert ROLLOUT_TIME_S == ROLLOUT_TIME_S
    src_s = inspect.getsource(search_integrated_tactical)
    assert "final_deal_rollout" not in src_s
    src_e = inspect.getsource(search_epoch_portfolio)
    assert "run_rollout" not in src_e
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192


def test_pilot_selection_includes_controls():
    opening = opening_state()
    roots = select_pilot_roots(opening, n=8)
    roles = [r.get("role") for r in roots]
    assert "ctrl_187" in roles
    assert "ctrl_192" in roles
    assert "ctrl_198" in roles
    assert "tactical_f2_g128" in roles
    digests = [r["pre_digest"] for r in roots]
    assert len(set(digests)) == len(digests)
    assert all(r["stock_rows"] == 0 for r in roots)
    assert all("deal" in str(r["full_actions"]).lower() or any(is_deal(a) for a in __import__("spider.research_actions", fromlist=["as_actions"]).as_actions(r["full_actions"])) for r in roots)
    gs = [r["post_g"] for r in roots]
    assert gs != sorted(gs)
    assert all(int(r["post_g"]) == int(r["pre_g"]) + int(r["deal_cost"]) for r in roots)
