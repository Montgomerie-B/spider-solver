"""v0.89 exhaustive evaluation of the v0.88 post-F2 preparation archive."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.exhaustive_post_f2_prep import (
    ARCHIVE_EVAL_ALL,
    EXPECTED_TOTAL,
    PORTFOLIO_MAX,
    ROLLOUT_N,
    STAGE_A_S,
    STAGE_B_N,
    STAGE_B_S,
    TOTAL_S,
    analyze_f171,
    any_f_lt_171,
    archive_mode,
    bucket_counts,
    choose_exhaustive_verdict,
    compare_sample_coverage,
    exhaustive_pareto,
    exhaustive_post_deal,
    next_recommendation,
    posts_at_f,
    select_exhaustive_rollout,
)
from spider.f3_quality_frontier import is_known_closed
from spider.final_deal_rollout import rollout_key
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.post_f2_predeal_preparation import (
    ARCHIVE_EVAL,
    MAX_DG,
    PREP_S,
    harvest_preparation,
    immediate_deal_control,
    load_prep_closed_table,
    reconstruct_root_a,
    reconstruct_root_b,
    select_predeal_for_eval,
)
from spider.proof_aware_tactical_bridge import continuation_is_exhausted, interpret_continuation_stop
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.search_kernel import run_search
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "exhaustive_post_f2_prep.py"
PREP_MOD = ROOT / "src" / "spider" / "post_f2_predeal_preparation.py"
SCRIPT = ROOT / "research" / "exhaustive_post_f2_prep_v0_89.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _post(**kw):
    rec = {
        "ok": True,
        "viable": True,
        "post_g": 129,
        "assembly_h": 42,
        "assembly_f": 171,
        "slack": 15,
        "foundations": 2,
        "face_down": 2,
        "empty_n": 0,
        "legal": 5,
        "visible_runs": 46,
        "mixed_suit_boundaries": 36,
        "post_digest": "d",
        "ident": "i",
        "source": "NEW_G128_F2",
        "prep_band": "0",
        "prep_delta_g": 0,
        "pre_g": 128,
    }
    rec.update(kw)
    return rec


def test_archive_eval_all_and_mode():
    assert ARCHIVE_EVAL_ALL == "ALL"
    assert ARCHIVE_EVAL == 80
    src = inspect.getsource(exhaustive_post_deal)
    assert "select_predeal_for_eval" not in src
    assert "ARCHIVE_EVAL" not in src
    script = _text(SCRIPT)
    assert "select_predeal_for_eval" not in script
    assert "ARCHIVE_EVAL_ALL" in script
    assert archive_mode() in ("ARCHIVE_REUSED", "ARCHIVE_REGENERATED")
    assert archive_mode() == "ARCHIVE_REGENERATED"
    src_h = inspect.getsource(harvest_preparation)
    assert "actions_fn=tableau_actions" in src_h
    assert "lower_bound_fn=None" in src_h
    assert "identity_fn=pack_state" in src_h
    assert "cost_ceiling=int(root_g + max_dg)" in src_h
    assert MAX_DG == 15
    assert PREP_S == 150.0
    sig = inspect.signature(harvest_preparation)
    assert sig.parameters["materialize_paths"].default is True


def test_roots_controls_exact_deal_and_dedup():
    opening = opening_state()
    a = reconstruct_root_a(opening)
    b = reconstruct_root_b(opening)
    assert a["ok"] and a["g"] == 128 and a["foundations"] == 2 and a["stock_rows"] == 1
    assert b["ok"] and b["g"] == 129 and b["foundations"] == 2 and b["stock_rows"] == 1
    ca = immediate_deal_control(a)
    cb = immediate_deal_control(b)
    assert ca["ok"] and ca["post_g"] == 129 and ca["assembly_h"] == 42 and ca["assembly_f"] == 171
    assert cb["ok"] and cb["post_g"] == 130 and cb["assembly_h"] == 41 and cb["assembly_f"] == 171
    from spider.packed_state import unpack_state

    pre = unpack_state(bytes.fromhex(a["ordered_digest"]))
    assert stock_rows(pre) == 1 and pre.can_deal()
    assert not any(is_deal(x) for x in tableau_actions(pre))
    cands = [
        {"ordered_digest": a["ordered_digest"], "g": 128, "source": "NEW_G128_F2", "prep_delta_g": 0, "prep_band": "0", "node": 0},
        {"ordered_digest": a["ordered_digest"], "g": 130, "source": "NEW_G128_F2", "prep_delta_g": 2, "prep_band": "1-2", "node": 0},
        {"ordered_digest": b["ordered_digest"], "g": 129, "source": "INCUMBENT_G129_F2", "prep_delta_g": 0, "prep_band": "0", "node": 0},
    ]
    ev = exhaustive_post_deal(cands)
    assert ev["n_eval"] == 3
    assert ev["n_illegal"] == 0
    assert ev["n_unique_post"] == 2
    by_src = {r["source"]: r for r in ev["posts"]}
    assert by_src["NEW_G128_F2"]["post_g"] == 129
    assert by_src["NEW_G128_F2"]["convergence"] == 2
    assert by_src["NEW_G128_F2"]["assembly_h"] == 42
    assert by_src["NEW_G128_F2"]["assembly_f"] == 171
    assert by_src["INCUMBENT_G129_F2"]["post_g"] == 130
    assert by_src["INCUMBENT_G129_F2"]["assembly_f"] == 171
    assert all(r.get("ok") and r.get("stock_rows") == 0 for r in ev["posts"])
    assert all("boundaries" in r for r in ev["posts"])
    from spider.f2_quality_frontier import as_rollout_post

    rp = as_rollout_post(by_src["NEW_G128_F2"])
    assert rp["boundaries"] is not None
    assert ev["h_cache"]["calls"] == 2
    assert sum(1 for r in ev["posts"] if r.get("assembly_h") is None) == 0


def test_f_distribution_query_and_f171_retention():
    posts = [
        _post(assembly_f=171, ident="a", post_digest="pa", legal=5),
        _post(assembly_f=171, ident="b", post_digest="pb", legal=9, source="INCUMBENT_G129_F2"),
        _post(assembly_f=172, ident="c", post_digest="pc"),
        _post(assembly_f=186, ident="d", post_digest="pd", viable=True),
        _post(assembly_f=187, ident="e", post_digest="pe", viable=False, ok=True),
    ]
    buckets = bucket_counts(posts)
    assert sum(buckets.values()) == len(posts)
    assert buckets["171"] == 2
    assert buckets["172"] == 1
    assert buckets["gt186"] == 1
    assert not any_f_lt_171(posts)
    assert any_f_lt_171(posts + [_post(assembly_f=170, ident="z", post_digest="pz")])
    f171 = posts_at_f(posts, 171)
    assert len(f171) == 2
    stats = analyze_f171(posts)
    assert stats["n"] == 2
    assert stats["legal_max"] == 9
    assert stats["sources"]["NEW_G128_F2"] == 1


def test_pareto_sample_selection_and_rollout_contract():
    a = _post(ident="ia", post_digest="da", legal=5, assembly_f=171, assembly_h=42, post_g=129)
    b = _post(ident="ib", post_digest="db", legal=8, assembly_f=171, assembly_h=41, post_g=130, empty_n=1, mixed_suit_boundaries=30, visible_runs=40)
    c = _post(ident="ic", post_digest="dc", legal=20, assembly_f=172, assembly_h=42, post_g=130)
    d = _post(ident="id", post_digest="dd", legal=3, assembly_f=180, assembly_h=50, post_g=130, empty_n=0, mixed_suit_boundaries=40, visible_runs=50)
    p1 = exhaustive_pareto([a, b, c, d])
    p2 = exhaustive_pareto([d, c, b, a])
    assert [r["ident"] for r in p1] == [r["ident"] for r in p2]
    assert all(r["ident"] != "id" for r in p1)
    cov = compare_sample_coverage(p1, [a, b, c, d], {"da"}, 171)
    assert cov["best_f_sampled"] is True
    assert cov["pareto_captured"] >= 1
    ctrls = [dict(a), dict(_post(ident="ib2", post_digest="db2", source="INCUMBENT_G129_F2", post_g=130, assembly_h=41))]
    ctrls[0]["ident"] = "ctrlA"
    ctrls[1]["ident"] = "ctrlB"
    picks = select_exhaustive_rollout([a, b, c, d], ctrls, k=ROLLOUT_N)
    assert len(picks) <= ROLLOUT_N == 16
    roles = {p["selection_role"] for p in picks}
    assert "immediate_deal" in roles
    assert "lowest_f" in roles
    src = inspect.getsource(rollout_key)
    assert src.index("solved") < src.index("-max_f")
    assert src.index("-max_f") < src.index("int(f_at)")
    assert src.index("int(f_at)") < src.index("int(g_at)")
    assert STAGE_A_S == 10.0 and STAGE_B_S == 20.0 and STAGE_B_N == 4
    assert ROLLOUT_N == 16 and PORTFOLIO_MAX == 24
    assert 2 * PREP_S + ROLLOUT_N * STAGE_A_S + STAGE_B_N * STAGE_B_S <= TOTAL_S == 900.0
    table = load_prep_closed_table()
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table)
    assert not is_known_closed(ident, int(rec["g"]) - 1, table)
    v, _ = choose_exhaustive_verdict({"any_f_lt_171": True, "min_f": 170, "solved": False, "incumbent_g": 187})
    assert v == "EXHAUSTIVE_PREP_FINDS_LOWER_F"
    v, _ = choose_exhaustive_verdict({"superior_prep": True, "superior_f": 171, "solved": False, "incumbent_g": 187})
    assert v == "EXHAUSTIVE_PREP_SAME_F_TOPOLOGY_WINS"
    v, _ = choose_exhaustive_verdict({"solved": False, "incumbent_g": 187})
    assert v == "EXHAUSTIVE_PREP_NO_GAIN"
    assert "rows=1" in next_recommendation("EXHAUSTIVE_PREP_NO_GAIN")
    assert continuation_is_exhausted("complete")
    assert interpret_continuation_stop("complete", solved=False)["exhausted"]
    assert inspect.getsource(select_predeal_for_eval)


def test_firewall_replay_and_promotion_guard():
    text = _text(MOD)
    script = _text(SCRIPT)
    prep = _text(PREP_MOD)
    for blob in (text, script):
        assert "4925153_canonical.moves" not in blob
        assert "Hearts" not in blob
    tree = ast.parse(text)
    simple = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple == []
    tree_s = ast.parse(script)
    simple_s = [n.module for n in ast.walk(tree_s) if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")]
    assert simple_s == []
    assert "replay_ok" in script
    assert "is_solved" in script
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v089 = ROOT / "solutions" / "4925153_autonomous_v0_89.moves"
    if v089.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v089))
        assert g is not None and g < 187
    assert "materialize_paths" in prep
    assert inspect.getsource(run_search)
    assert EXPECTED_TOTAL == 87527
