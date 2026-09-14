"""Multi-suit operational readiness v0.70."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.assembly_policy import COMPLETION_LANES, MULTI_SUIT_LANES, assembly_lane_keys
from spider.autonomous_cost import COST_LANES, checkpoints_from_trace
from spider.cards import Card
from spider.deal_preview import preview_next_deal
from spider.engine import Column, SpiderState
from spider.integrated_policy import (
    AUTONOMOUS_INCUMBENT_MW,
    CANDIDATE_CEILING,
    load_autonomous_192,
    search_integrated_optimisation,
    verify_autonomous_192,
)
from spider.metrics import parse_moves_file, replay_actions
from spider.multi_suit_readiness import audit_rows1_ready_ranks
from spider.operational_policy import OP_LANES, operational_lane_keys, search_operational_optimisation
from spider.operational_viability import operational_viability_key, rank_ready_suits
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.research_actions import as_actions, is_deal, stock_rows
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
ASM = ROOT / "src" / "spider" / "assembly_policy.py"
MOD = ROOT / "src" / "spider" / "multi_suit_readiness.py"
POLICY = ROOT / "src" / "spider" / "integrated_policy.py"
SCRIPT = ROOT / "research" / "multi_suit_readiness_v0_70.py"
ARTEFACT = ROOT / "docs" / "research" / "multi_suit_readiness_v0_70.json"
V067 = ROOT / "solutions" / "4925153_autonomous_v0_67.moves"
V059 = ROOT / "solutions" / "4925153_autonomous_v0_59.moves"
CANON = ROOT / "solutions" / "4925153_canonical.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _simple_imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("spider.simple_")
    ]


def _run(suit: str, hi: int, lo: int):
    return [Card(suit, r) for r in range(hi, lo - 1, -1)]


def _ka(suit: str):
    return _run(suit, 13, 1)


def _columns(*runs, down=None, foundations=None, stock=None) -> SpiderState:
    downs = list(down or [])
    cols = []
    for i, run in enumerate(runs):
        fd = list(downs[i]) if i < len(downs) else []
        cols.append(Column(fd, list(run)))
    while len(cols) < 10:
        cols.append(Column([], []))
    return SpiderState(cols, list(stock or []), list(foundations or []))


def test_rank_ready_full_ranking_and_primary_unchanged():
    opening = opening_state()
    r = rank_ready_suits(opening, g=0)
    assert "ranked" in r
    assert r["best"] is r["ranked"][0] if r["ranked"] else r["best"] is None
    keys = operational_lane_keys(opening, 0)
    keys2 = assembly_lane_keys(opening, 0)
    assert keys["readiness"] == keys2["readiness"]
    assert keys["cost"] == keys2["cost"]
    assert OP_LANES == COST_LANES


def test_r2_r3_inactive_except_rows1_and_follow_rank():
    opening = opening_state()
    k0 = assembly_lane_keys(opening, 0)
    assert stock_rows(opening) != 1
    assert k0["readiness_r2"] is None
    assert k0["readiness_r3"] is None
    assert k0["completion"] is None
    two = _columns(
        _ka("c"),
        _ka("d"),
        stock=[Card("h", r) for r in range(1, 11)],
    )
    assert stock_rows(two) == 1
    ranked = rank_ready_suits(two, g=9)
    keys = assembly_lane_keys(two, 9)
    assert ranked["n_ready"] >= 2
    assert keys["readiness"] == operational_viability_key(ranked["ranked"][0], 9)
    assert keys["readiness_r2"] == operational_viability_key(ranked["ranked"][1], 9)
    if ranked["n_ready"] >= 3:
        assert keys["readiness_r3"] == operational_viability_key(ranked["ranked"][2], 9)
    else:
        assert keys["readiness_r3"] is None
    one = _columns(_ka("c"), stock=[Card("h", r) for r in range(1, 11)])
    assert stock_rows(one) == 1
    r1 = rank_ready_suits(one, g=4)
    k1 = assembly_lane_keys(one, 4)
    if r1["n_ready"] < 2:
        assert k1["readiness_r2"] is None
    empty = _columns(_ka("c"), _ka("d"))
    assert stock_rows(empty) == 0
    ke = assembly_lane_keys(empty, 10)
    assert ke["readiness_r2"] is None
    assert ke["readiness_r3"] is None
    assert ke["completion"] is not None
    src = inspect.getsource(assembly_lane_keys)
    assert "ranked[1]" in src or "ranked[1]" in inspect.getsource(assembly_lane_keys)
    assert "spades" not in src.lower()
    assert "diamonds" not in src.lower()
    assert "hearts" not in src.lower()
    assert "clubs" not in src.lower()


def test_no_suit_literals_in_policy_tt_preview_bound_192():
    for path in (ASM, MOD, POLICY):
        text = _text(path)
        assert "4925153_canonical.moves" not in text
        assert _simple_imports(path) == []
    src = inspect.getsource(search_operational_optimisation)
    assert "incumbent_g - 1" in src
    assert "durability" not in src
    src_i = inspect.getsource(search_integrated_optimisation)
    assert "assembly_lane_keys" in src_i
    assert "MULTI_SUIT_LANES" in src_i
    assert "readiness_r2" in MULTI_SUIT_LANES
    assert "readiness_r3" in MULTI_SUIT_LANES
    assert "durability" not in MULTI_SUIT_LANES
    assert "completion" in COMPLETION_LANES
    opening = opening_state()
    packed = pack_state(opening)
    ident = pack_whole_game_identity(opening)
    assembly_lane_keys(opening, 0)
    preview_next_deal(opening, pre_g=0)
    assert pack_state(opening) == packed
    assert pack_whole_game_identity(opening) == ident
    v = verify_autonomous_192(opening)
    assert v["ok"] and v["g"] == AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186


def test_checkpoint_prefix_and_audit_is_evaluation_only():
    opening = opening_state()
    trace = load_autonomous_192(opening)
    ck = checkpoints_from_trace(trace)
    rec = ck[1]
    end = opening.clone()
    g = replay_actions(end, as_actions(rec["full_actions"]))
    assert g == rec["g"]
    assert rec["stock_rows"] == 1
    assert pack_state(end).hex() == rec["ordered_digest"]
    actions = verify_autonomous_192(opening)["actions"]
    audit = audit_rows1_ready_ranks(opening, actions)
    assert audit["n_states"] > 0
    assert audit["entry"]["g"] == rec["g"] or audit["entry"]["F"] >= 1
    src_i = inspect.getsource(search_integrated_optimisation)
    assert "audit_rows1_ready_ranks" not in src_i


def test_script_canonical_after_search_and_regressions():
    script = _text(SCRIPT)
    if script:
        search_at = script.find("search_integrated_optimisation(")
        eval_at = script.find("EVAL canonical")
        assert search_at != -1
        assert eval_at > search_at
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V059)) == 198
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    assert replay_actions(opening.clone(), parse_moves_file(V067)) == 192


def test_artefact_terminal_if_present():
    if not ARTEFACT.exists():
        return
    import json

    from spider.healthy_f2 import parse_stored_actions

    data = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    if data.get("solved") and data.get("solution_actions"):
        opening = opening_state()
        actions = parse_stored_actions(data["solution_actions"])
        end = opening.clone()
        g = replay_actions(end, actions)
        assert end.is_solved()
        assert g < 192
        assert sum(1 for a in actions if is_deal(a)) == 5
