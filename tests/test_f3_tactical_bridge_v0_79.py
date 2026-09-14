"""F3→F4 tactical bridge v0.79."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from spider.f3_tactical_bridge import (
    BRIDGE_CEILING,
    expected_g141_digest,
    inspect_f3_state,
    probe_ready_suits,
    recover_g141,
    search_f4_portfolio,
)
from spider.foundation_cashout import TACTICAL_CEILING, search_foundation_cashout
from spider.g128_focused_endgame import reconstruct_g128_root
from spider.integrated_policy import AUTONOMOUS_INCUMBENT_MW, CANDIDATE_CEILING
from spider.metrics import CANONICAL_MW_COST, RECORD_MW_COST, parse_moves_file, replay_actions
from spider.packed_state import pack_state, unpack_state
from spider.research_actions import is_deal, stock_rows
from spider.whole_game_anytime import opening_state

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "src" / "spider" / "f3_tactical_bridge.py"
SCRIPT = ROOT / "research" / "f3_tactical_bridge_v0_79.py"
CANON = ROOT / "solutions" / "4925153_canonical.moves"
V074 = ROOT / "solutions" / "4925153_autonomous_v0_74.moves"
SCHED = ROOT / "src" / "spider" / "whole_game_epoch_scheduler.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_constants_and_firewalls():
    assert AUTONOMOUS_INCUMBENT_MW == 187
    assert CANDIDATE_CEILING == 186 == BRIDGE_CEILING
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
    src_p = inspect.getsource(probe_ready_suits)
    assert "search_foundation_cashout" in src_p
    assert "cost_ceiling=BRIDGE_CEILING" in src_p
    assert "skip_preview=True" in src_p
    src_r = inspect.getsource(recover_g141)
    assert "continuation_table=None" in src_r
    assert "incumbent_by_rows={}" in src_r
    src_c = inspect.getsource(search_f4_portfolio)
    assert "continuation_table=None" in src_c
    script = _text(SCRIPT)
    assert "search_rollout_guided" not in script
    assert "reconstruct_g128_root" in script


def test_g141_digest_is_stock_empty_f3():
    digest = expected_g141_digest()
    info = inspect_f3_state(digest, g=141)
    assert info["ok"]
    assert info["foundations"] == 3
    assert info["face_down"] == 2
    assert info["stock_rows"] == 0
    assert info["empty_n"] == 2
    assert info["legal_tableau"] == 41
    assert info["assembly_h"] == 33
    assert info["assembly_f"] == 174
    assert info["n_ready"] >= 1
    assert "h" in info["ready_suits"]
    assert set(info["foundation_suits"]) == {"c", "d", "s"}
    assert info["can_deal"] is False
    st = unpack_state(bytes.fromhex(digest))
    assert pack_state(st).hex() == digest
    assert stock_rows(st) == 0
    src = inspect.getsource(search_foundation_cashout)
    assert "Deal leaked" in _text(ROOT / "src" / "spider" / "foundation_cashout.py")


def test_g129_reconstruction_and_no_deal_in_tactical():
    opening = opening_state()
    root = reconstruct_g128_root(opening)
    assert root["ok"]
    post = root["post"]
    assert post["g"] == 129
    assert post["foundations"] == 2
    assert post["stock_rows"] == 0
    src = inspect.getsource(probe_ready_suits)
    assert "is_deal" in src
    assert replay_actions(opening.clone(), parse_moves_file(V074)) == 187
    assert replay_actions(opening.clone(), parse_moves_file(CANON)) == 172
    v079 = ROOT / "solutions" / "4925153_autonomous_v0_79.moves"
    if v079.exists():
        g = replay_actions(opening.clone(), parse_moves_file(v079))
        assert g is not None and g < 187
        assert sum(1 for a in parse_moves_file(v079) if is_deal(a)) == 5
    else:
        assert AUTONOMOUS_INCUMBENT_MW == 187
    sched = _text(SCHED)
    assert "final_deal_rollout_fn=None" in sched
