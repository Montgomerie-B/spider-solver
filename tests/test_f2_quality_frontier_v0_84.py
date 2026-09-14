"""v0.84 F2 quality frontier and post-Deal rollout."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f2_quality_frontier import (
    HARVEST_S,
    PORTFOLIO_MAX,
    SELECT_N,
    STAGE_A_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    apply_exact_final_deal,
    beats_g128_control,
    choose_f2_frontier_verdict,
    control_pre_f2_digests,
    g123_ready_targets,
    harvest_f2_target,
    load_f2_closed_table,
    mark_control_f2s,
    post_deal_pareto,
    select_continuation_portfolio,
    select_rollout_roots,
    verify_g123_root,
)
from spider.f3_quality_frontier import is_known_closed as closed_fn
from spider.final_deal_rollout import run_rollout
from spider.foundation_cashout import search_foundation_cashout
from spider.g128_focused_endgame import reconstruct_g128
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.proof_aware_tactical_bridge import continuation_is_exhausted, interpret_continuation_stop
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.state_convergence import V073_F2_DIGEST
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f2_quality_frontier.py"
SCRIPT = ROOT / "research" / "f2_quality_frontier_v0_84.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_g123_root_ready_suits_and_firewall():
    opening = opening_state()
    rec = verify_g123_root(opening)
    assert rec["ok"], rec.get("mismatches") or rec.get("reason")
    assert rec["g"] == 123
    assert rec["foundations"] == 1
    assert rec["face_down"] == 2
    assert rec["stock_rows"] == 1
    st = unpack_state(bytes.fromhex(rec["ordered_digest"]))
    assert pack_state(st).hex() == rec["ordered_digest"]
    assert stock_rows(st) == 1
    assert rec["identity_is_ordered"] is True
    targets = g123_ready_targets(st, g=123)
    assert targets
    ranks = [t["operational_rank"] for t in targets]
    assert ranks == list(range(1, len(ranks) + 1))
    src = _text(MOD)
    assert "Hearts" not in src
    assert "Diamonds" not in src
    assert "4925153_canonical.moves" not in src
    tree = ast.parse(src)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    cash = inspect.getsource(search_foundation_cashout)
    assert "Deal leaked" in _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    harvest = inspect.getsource(harvest_f2_target)
    assert "lower_bound_fn" not in harvest
    assert "future_cost_key_fn" not in harvest
    assert "skip_preview=True" in harvest
    assert "cost_ceiling=int(ceiling)" in harvest


def test_equal_budget_caps_deal_and_post_h():
    assert HARVEST_S == 360.0
    assert STAGE_A_S == 10.0 and STAGE_A_N == 12
    assert STAGE_B_S == 20.0 and STAGE_B_N == 4
    assert STAGE_A_N * STAGE_A_S + STAGE_B_N * STAGE_B_S <= 200.0
    assert HARVEST_S + 200.0 <= TOTAL_S == 900.0
    assert SELECT_N == 12
    assert PORTFOLIO_MAX == 24
    script = _text(SCRIPT)
    assert "HARVEST_S / float(max(1, n_ready))" in script
    assert "continuation_table=None" in inspect.getsource(run_rollout)
    opening = opening_state()
    g128 = reconstruct_g128(opening)
    assert g128["ok"] and g128["g"] == 128
    controls = control_pre_f2_digests()
    assert g128["ordered_digest"] == controls["g128"]
    assert controls["g187"] == V073_F2_DIGEST
    marked = mark_control_f2s([{"ordered_digest": g128["ordered_digest"], "g": 128}])
    assert marked[0]["control_tag"] == "g128_tactical"
    post = apply_exact_final_deal(
        {
            "g": 128,
            "ordered_digest": g128["ordered_digest"],
            "full_actions": g128["full_actions"],
        }
    )
    assert post["ok"]
    assert post["post_g"] == 129
    assert post["stock_rows"] == 0
    assert post["assembly_h"] == 43
    assert post["assembly_f"] == 172
    assert post["viable"] is True
    assert post["deal_cost"] == 1
    dead = {
        "post_g": 170,
        "assembly_h": 20,
        "assembly_f": 190,
        "slack": -4,
        "foundations": 2,
        "face_down": 2,
        "empty_n": 1,
        "legal": 10,
        "boundaries": 20,
        "viable": False,
        "ok": True,
        "post_digest": "dead",
        "ident": "dead",
    }
    live = {
        "post_g": 129,
        "assembly_h": 43,
        "assembly_f": 172,
        "slack": 14,
        "foundations": 2,
        "face_down": 2,
        "empty_n": 2,
        "legal": 5,
        "boundaries": 30,
        "viable": True,
        "ok": True,
        "post_digest": "aa",
        "ident": "live",
        "tactical_target": "x",
        "foundation_suits": ["s", "d"],
    }
    live2 = dict(live, post_g=131, assembly_h=40, assembly_f=171, slack=15, post_digest="bb", ident="live2", empty_n=3, legal=20, boundaries=10)
    pareto = post_deal_pareto([dead, live, live2])
    assert all(r.get("ident") != "dead" for r in pareto)
    selected = select_rollout_roots([dead, live, live2], k=12)
    assert len(selected) <= 12
    assert all(r.get("viable") for r in selected)
    src_sel = inspect.getsource(select_rollout_roots)
    assert "lowest_f" in src_sel and "pareto_balanced" in src_sel


def test_closed_guard_portfolio_complete_and_replay():
    table = load_f2_closed_table()
    assert table
    ident = next(iter(table))
    rec = table[ident]
    assert closed_fn(ident, int(rec["g"]), table) is True
    assert closed_fn(ident, int(rec["g"]) - 1, table) is False
    similar = ident[:-2] + ("00" if ident[-2:] != "00" else "ff")
    assert closed_fn(similar, int(rec["g"]), table) is False
    port = select_continuation_portfolio(
        [
            {
                "g": 170,
                "assembly_h": 15,
                "assembly_f": 185,
                "slack": 1,
                "foundations": 4,
                "ident": "p1",
                "ordered_digest": "cc",
                "full_actions": [("x",)],
                "legal_tableau": 10,
            }
        ],
        {},
        hard_max=24,
    )
    assert len(port) <= 24
    assert continuation_is_exhausted("complete") is True
    note = interpret_continuation_stop("complete", solved=False)
    assert note["exhausted"] is True
    v, _ = choose_f2_frontier_verdict({"solved": False, "incumbent_g": 187, "max_foundations": 4, "superior_root": True, "n_new_f2": 8})
    assert v == "F2_FRONTIER_FINDS_SUPERIOR_ROOT"
    v2, _ = choose_f2_frontier_verdict({"solved": False, "incumbent_g": 187, "max_foundations": 3, "n_new_f2": 10, "n_unique_pre": 20})
    assert v2 == "F2_FRONTIER_NEW_F2_NO_FUTURE_GAIN"
    assert beats_g128_control({"max_F": 4, "cheap_F": {}})
    assert beats_g128_control({"max_F": 3, "cheap_F": {"3": {"f": 178}}})
    assert not beats_g128_control({"max_F": 3, "cheap_F": {"3": {"f": 186}}, "time_first_increase": 20})
    harvest_src = inspect.getsource(harvest_f2_target)
    assert 'n_f == 2 else "PREDEAL_DEEPER"' in harvest_src
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v084 = ROOT / "solutions" / "4925153_autonomous_v0_84.moves"
    if v084.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v084))
        assert g is not None and g < 187
    script = _text(SCRIPT)
    assert "canonical" in script.lower()
    assert "g128 F3" in script or "g128" in script
    assert "STAGE_A_S" in script and "STAGE_B_N" in script
