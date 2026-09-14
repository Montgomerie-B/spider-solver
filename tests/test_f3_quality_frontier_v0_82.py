"""F3 quality frontier and proof-aware bridge screening v0.82."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_quality_frontier import (
    CONTINUATION_RESERVE_S,
    HARVEST_LANES,
    HARVEST_S,
    MAX_ACTIVE_F3,
    STAGE_A_S,
    STAGE_B_ROOTS,
    STAGE_B_S,
    STAGE_B_TARGETS,
    TOTAL_S,
    bridge_loss,
    choose_f3_frontier_verdict,
    choose_stage_b_pairs,
    control_digests,
    f3_harvest_terminal_fn,
    f3_pareto_frontier,
    harvest_f3_terminals,
    is_known_closed,
    load_closed_root_table,
    mark_control_f3s,
    next_foundation_quality,
    select_new_f3_representatives,
    stage_a_rank_key,
    verify_g129_root,
)
from spider.f3_tactical_bridge import load_g141_record
from spider.foundation_cashout import TACTICAL_LANES
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_whole_game_identity, unpack_state
from spider.proof_aware_tactical_bridge import (
    continuation_is_exhausted,
    interpret_continuation_stop,
    load_g158_record,
    recommend_continue_from_roots,
)
from spider.research_actions import is_deal, stock_rows, tableau_actions
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f3_quality_frontier.py"
SCRIPT = ROOT / "research" / "f3_quality_frontier_v0_82.py"
KERN = ROOT / "src" / "spider" / "search_kernel.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _fake_f3(**kw) -> dict:
    rec = {
        "g": 150,
        "assembly_h": 25,
        "assembly_f": 175,
        "slack": 11,
        "empty_n": 2,
        "legal_tableau": 40,
        "boundaries": 20,
        "face_down": 2,
        "foundations": 3,
        "ordered_digest": kw.pop("ordered_digest", "aa"),
        "ident": kw.pop("ident", "id-aa"),
        "viable": True,
    }
    rec.update(kw)
    rec["assembly_f"] = rec["g"] + rec["assembly_h"]
    rec["slack"] = 186 - rec["assembly_f"]
    return rec


def test_g129_root_and_firewall():
    opening = opening_state()
    info = verify_g129_root(opening)
    assert info["ok"], info.get("mismatches") or info.get("reason")
    assert info["g"] == 129
    assert info["foundations"] == 2
    assert info["face_down"] == 2
    assert info["stock_rows"] == 0
    assert info["assembly_h"] == 43
    assert info["assembly_f"] == 172
    assert info["v076_digest_match"] is True
    st = unpack_state(bytes.fromhex(info["ordered_digest"]))
    assert stock_rows(st) == 0
    assert not st.can_deal()
    assert not any(is_deal(a) for a in tableau_actions(st))
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    text = _text(MOD)
    assert "4925153_canonical.moves" not in text
    tree = ast.parse(text)
    simple = [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]
    assert simple == []
    assert "horizon" not in HARVEST_LANES
    assert HARVEST_S + 6 * 4 * STAGE_A_S + STAGE_B_ROOTS * STAGE_B_TARGETS * STAGE_B_S + CONTINUATION_RESERVE_S <= TOTAL_S == 900.0
    src = inspect.getsource(harvest_f3_terminals)
    assert "is_terminal=f3_harvest_terminal_fn" in src
    assert "tableau_actions" in src
    assert TACTICAL_LANES == ("cost", "target_assembly", "target_access")


def test_harvester_stops_expansion_at_f3():
    assert f3_harvest_terminal_fn(unpack_state(bytes.fromhex(load_g158_record()["ordered_digest"]))) is True
    g129 = verify_g129_root()
    st2 = unpack_state(bytes.fromhex(g129["ordered_digest"]))
    assert f3_harvest_terminal_fn(st2) is False
    rec = load_g158_record()
    out = harvest_f3_terminals(
        {"g": 158, "ordered_digest": rec["ordered_digest"], "whole_game_identity": "", "full_actions": []},
        time_s=0.4,
        unique=200,
    )
    assert out["expanded"] == 0
    kern = _text(KERN)
    assert "if is_terminal(state):" in kern
    assert "push(child_i, state, child_g)" in kern


def test_proof_viable_dedup_pareto_and_selection_excludes_controls():
    controls = control_digests()
    g141 = load_g141_record()
    g158 = load_g158_record()
    assert controls["g141"] == g141["ordered_digest"]
    assert controls["g158"] == g158["ordered_digest"]
    pool = [
        _fake_f3(g=141, assembly_h=33, ident="c141", ordered_digest=controls["g141"]),
        _fake_f3(g=158, assembly_h=22, ident="c158", ordered_digest=controls["g158"]),
        _fake_f3(g=145, assembly_h=28, ident="a", ordered_digest="na", empty_n=1, legal_tableau=30, boundaries=25),
        _fake_f3(g=150, assembly_h=20, ident="b", ordered_digest="nb", empty_n=4, legal_tableau=90, boundaries=12),
        _fake_f3(g=155, assembly_h=24, ident="c", ordered_digest="nc", empty_n=3, legal_tableau=70, boundaries=15),
        _fake_f3(g=148, assembly_h=26, ident="d", ordered_digest="nd", empty_n=2, legal_tableau=55, boundaries=10),
        _fake_f3(g=160, assembly_h=18, ident="e", ordered_digest="ne", empty_n=3, legal_tableau=40, boundaries=18),
        _fake_f3(g=152, assembly_h=22, ident="f", ordered_digest="nf", empty_n=2, legal_tableau=60, boundaries=16),
        _fake_f3(g=152, assembly_h=22, ident="f", ordered_digest="nf2"),
    ]
    marked = mark_control_f3s(pool, controls)
    tags = {r["ident"]: r.get("control_tag") for r in marked}
    assert tags["c141"] == "g141_control"
    assert tags["c158"] == "g158_control"
    from spider.f3_quality_frontier import dedup_f3_by_identity

    deduped = dedup_f3_by_identity(pool)
    assert sum(1 for r in deduped if r["ident"] == "f") == 1
    pareto = f3_pareto_frontier([r for r in pool if r["ident"] not in ("c141", "c158")])
    assert pareto
    selected = select_new_f3_representatives(marked, controls=controls, k=MAX_ACTIVE_F3)
    assert len(selected) <= 6
    digests = {r["ordered_digest"] for r in selected}
    assert controls["g141"] not in digests
    assert controls["g158"] not in digests
    roles = {r["selection_role"] for r in selected}
    assert "lowest_f" in roles
    assert all(r.get("viable", True) for r in selected)


def test_bridge_loss_quality_classes_stage_caps_and_closed_guard():
    assert bridge_loss(174, 186) == 12
    assert bridge_loss(180, 185) == 5
    assert next_foundation_quality(184) == "STRONG_SURPLUS"
    assert next_foundation_quality(185) == "SURPLUS_1"
    assert next_foundation_quality(186) == "ZERO_SLACK"
    assert next_foundation_quality(187) == "RAW"
    assert STAGE_A_S == 10.0
    assert STAGE_B_ROOTS == 4 and STAGE_B_TARGETS == 2
    src = inspect.getsource(select_new_f3_representatives)
    assert "g141" in src and "g158" in src
    ranked = [
        {"best_terminal_f": 186, "best_slack": 0, "bridge_loss": 8, "lowest_terminal_h": 20, "best_mobility": 10, "root_g": 1, "probes": [{"viable_count": 1, "best_viable_f": 186, "suit": "x"}]},
        {"best_terminal_f": 185, "best_slack": 1, "bridge_loss": 4, "lowest_terminal_h": 12, "best_mobility": 40, "root_g": 2, "probes": [{"viable_count": 2, "best_viable_f": 185, "suit": "y"}, {"viable_count": 1, "best_viable_f": 186, "suit": "z"}, {"viable_count": 0, "suit": "w"}]},
        {"best_terminal_f": None, "root_g": 3, "probes": [{"viable_count": 0, "suit": "q"}]},
        {"best_terminal_f": 185, "best_slack": 1, "bridge_loss": 5, "lowest_terminal_h": 14, "best_mobility": 20, "root_g": 4, "probes": [{"viable_count": 1, "best_viable_f": 185, "suit": "r"}]},
        {"best_terminal_f": 186, "best_slack": 0, "bridge_loss": 6, "lowest_terminal_h": 18, "best_mobility": 15, "root_g": 5, "probes": [{"viable_count": 1, "best_viable_f": 186, "suit": "s"}]},
    ]
    ranked_sorted = sorted(ranked, key=stage_a_rank_key)
    assert ranked_sorted[0]["root_g"] == 2
    pairs = choose_stage_b_pairs(ranked_sorted)
    assert len({p["root"]["root_g"] for p in pairs}) <= 4
    assert all(sum(1 for p in pairs if p["root"]["root_g"] == rg) <= 2 for rg in {p["root"]["root_g"] for p in pairs})
    table = load_closed_root_table()
    assert table
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table) is True
    assert is_known_closed(ident, int(rec["g"]) - 1, table) is False
    assert is_known_closed("not-a-real-identity", int(rec["g"]), table) is False
    similar = ident[:-2] + ("00" if ident[-2:] != "00" else "ff")
    assert similar != ident
    assert is_known_closed(similar, int(rec["g"]), table) is False
    assert continuation_is_exhausted("complete") is True
    assert recommend_continue_from_roots("complete", solved=False) is False
    note = interpret_continuation_stop("complete", solved=False)
    assert note["exhausted"] is True
    assert "exhausted" in (note["note"] or "")
    payload = {"bridge": {}, "best_new_f": 184, "max_foundations": 4, "solved": False, "incumbent_g": 187}
    v, _ = choose_f3_frontier_verdict(payload)
    assert v == "F3_FRONTIER_FINDS_STRONG_SURPLUS"
    v2, _ = choose_f3_frontier_verdict({"best_new_f": 185, "max_foundations": 5, "solved": False, "incumbent_g": 187, "n_selected": 6})
    assert v2 == "F3_FRONTIER_FINDS_NEW_SURPLUS"
    v3, _ = choose_f3_frontier_verdict({"best_new_f": 186, "max_foundations": 4, "solved": False, "incumbent_g": 187, "n_selected": 6})
    assert v3 == "F3_FRONTIER_NO_BETTER_THAN_G158"
    v4, _ = choose_f3_frontier_verdict({
        "best_new_f": None,
        "max_foundations": 3,
        "solved": False,
        "incumbent_g": 187,
        "n_selected": 6,
        "screening_time_limited": True,
    })
    assert v4 == "F3_FRONTIER_SEARCH_LIMITED"
    none_term = [
        {"best_terminal_f": None, "root_f": 174, "root_h": 32, "root_slack": 12, "root_g": 142},
        {"best_terminal_f": None, "root_f": 186, "root_h": 19, "root_slack": 0, "root_g": 167},
    ]
    assert sorted(none_term, key=stage_a_rank_key)[0]["root_g"] == 142
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v082 = ROOT / "solutions" / "4925153_autonomous_v0_82.moves"
    if v082.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v082))
        assert g is not None and g < 187
    src_s = _text(SCRIPT)
    assert "canonical" in src_s.lower()
    assert "run_proof_aware_bridge" not in inspect.getsource(harvest_f3_terminals)
    cash = _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    assert "Deal leaked into tactical actions" in cash
