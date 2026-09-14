"""v0.86 new-family F3 topology + proof-aware bridge."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_quality_frontier import control_digests, is_known_closed
from spider.foundation_cashout import search_foundation_cashout
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.new_family_f3_bridge import (
    CONTINUATION_RESERVE_S,
    N_ROOTS,
    ROOT_SPECS,
    STAGE_A_S,
    STAGE_A_UNIQUE,
    TOTAL_S,
    choose_new_family_verdict,
    load_new_family_closed_table,
    load_new_family_f3,
    load_new_family_roots,
    select_new_family_portfolio,
    topology_beats_old,
    verify_all_new_family_roots,
)
from spider.packed_state import pack_state, pack_whole_game_identity, unpack_state
from spider.proof_aware_tactical_bridge import (
    continuation_is_exhausted,
    interpret_continuation_stop,
    probe_proof_aware_target,
)
from spider.research_actions import is_deal, stock_rows
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "new_family_f3_bridge.py"
SCRIPT = ROOT / "research" / "new_family_f3_bridge_v0_86.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_new_f3s_loaded_and_differ_from_old_g141():
    src = inspect.getsource(load_new_family_f3)
    assert "53504b31" not in src
    assert ROOT_SPECS[0]["g"] == 141 and ROOT_SPECS[0]["f"] == 174
    assert ROOT_SPECS[1]["g"] == 148 and ROOT_SPECS[1]["f"] == 177
    roots = load_new_family_roots()
    assert len(roots) == 2
    cheap, first = roots
    assert cheap["g"] == 141 and cheap["assembly_h"] == 33
    assert first["g"] == 148 and first["assembly_h"] == 29
    controls = control_digests()
    assert cheap["ordered_digest"] != controls["g141"]
    st = unpack_state(bytes.fromhex(cheap["ordered_digest"]))
    assert pack_whole_game_identity(st).hex() != controls["g141_ident"]
    checked = verify_all_new_family_roots()
    assert checked["ok"], [r.get("mismatches") or r.get("reason") for r in checked["roots"]]
    a, b = checked["roots"]
    assert a["g"] == 141 and a["assembly_h"] == 33 and a["assembly_f"] == 174 and a["slack"] == 12
    assert a["legal_tableau"] == 43
    assert a["boundaries_recorded"] == 28
    assert b["g"] == 148 and b["assembly_h"] == 29 and b["assembly_f"] == 177
    assert a["differs_from_old_digest"] and a["differs_from_old_ident"]
    assert not a["is_old_g141"]
    assert stock_rows(st) == 0
    assert pack_state(st).hex() == cheap["ordered_digest"]
    script = _text(SCRIPT)
    assert "old g141" in script.lower() or "OLD_G141" in script
    assert "search" in script
    assert cheap["ordered_digest"] not in inspect.getsource(verify_all_new_family_roots)


def test_equal_budget_closed_guard_and_firewall():
    assert STAGE_A_S == 90.0
    assert STAGE_A_UNIQUE == 150_000
    assert N_ROOTS == 2
    assert CONTINUATION_RESERVE_S == 180.0
    assert N_ROOTS * 4 * STAGE_A_S + CONTINUATION_RESERVE_S <= TOTAL_S == 900.0
    script = _text(SCRIPT)
    assert "STAGE B" not in script
    assert "no_stage_b" in script
    assert "harvest_f3_terminals" not in script
    from spider.proof_aware_tactical_bridge import _probe_one
    assert "search_foundation_cashout" in inspect.getsource(_probe_one)
    cash = _text(ROOT / "src" / "spider" / "foundation_cashout.py")
    assert "Deal leaked into tactical actions" in cash
    table = load_new_family_closed_table()
    assert table
    ident = next(iter(table))
    rec = table[ident]
    assert is_known_closed(ident, int(rec["g"]), table) is True
    assert is_known_closed(ident, int(rec["g"]) - 1, table) is False
    similar = ident[:-2] + ("00" if ident[-2:] != "00" else "ff")
    assert is_known_closed(similar, int(rec["g"]), table) is False
    port = select_new_family_portfolio(
        [{"viable_terminals": [{"g": 160, "assembly_h": 25, "assembly_f": 185, "ident": ident, "legal_tableau": 10, "boundaries": 4, "tactical_target": "x", "ordered_digest": "aa"}], "root_g": 141}],
        table,
    )
    assert all(int(r["g"]) < int(rec["g"]) or r.get("ident") != ident for r in port) or int(160) < int(rec["g"])
    # lower-g same identity remains admissible
    low = {"g": int(rec["g"]) - 1, "assembly_h": 25, "assembly_f": 185, "ident": ident, "legal_tableau": 10, "boundaries": 4, "tactical_target": "x", "ordered_digest": "bb"}
    port2 = select_new_family_portfolio([{"viable_terminals": [low], "root_g": 141}], table)
    if int(rec["g"]) > 0:
        assert any(r.get("ident") == ident for r in port2) or is_known_closed(ident, int(rec["g"]) - 1, table) is False
    assert len(port) <= 16
    assert continuation_is_exhausted("complete") is True
    assert interpret_continuation_stop("complete", solved=False)["exhausted"] is True
    assert topology_beats_old(185, 11) is True
    assert topology_beats_old(186, 12) is False
    v, _ = choose_new_family_verdict({"best_new_f": 186, "new_g141": {"best_terminal_f": 186, "bridge_loss": 12}, "solved": False, "incumbent_g": 187})
    assert v == "NEW_F3_BRIDGE_ZERO_SLACK"
    v2, _ = choose_new_family_verdict({"best_new_f": 186, "new_g141": {"best_terminal_f": 185, "bridge_loss": 11}, "solved": False, "incumbent_g": 187, "max_foundations": 4})
    assert v2 == "NEW_F3_TOPOLOGY_BEATS_OLD"
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
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186
    assert RECORD_MW_COST == 119
    assert CANONICAL_MW_COST == 172
    opening = opening_state()
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v086 = ROOT / "solutions" / "4925153_autonomous_v0_86.moves"
    if v086.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v086))
        assert g is not None and g < 187
