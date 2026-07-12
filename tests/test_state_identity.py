"""Core collision-safe state identity (no Opt011 runner dependency)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal
from spider.engine import SpiderState
from spider.metrics import parse_moves_file
from spider.state_identity import (
    CollisionSafeTT,
    canonical_state_key,
    states_structurally_equal,
)

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"


def _after(n: int) -> SpiderState:
    st = SpiderState.from_cards(load_deal(DEAL))
    for a in parse_moves_file(CANONICAL)[:n]:
        if a == ("deal",):
            st.deal()
        else:
            st.move(*a)
    return st


def test_canonical_key_equality():
    a = _after(42)
    b = a.clone()
    assert canonical_state_key(a) == canonical_state_key(b)
    assert states_structurally_equal(a, b)


def test_tt_structural_dominance_not_hash_alone():
    s0 = _after(42)
    moves = s0.enumerate_moves()
    assert len(moves) >= 2
    sa, sb = s0.clone(), s0.clone()
    sa.move(*moves[0])
    sb.move(*moves[1])
    ka, kb = canonical_state_key(sa), canonical_state_key(sb)
    assert ka != kb
    tt = CollisionSafeTT(hash_fn=lambda _k: 0)
    assert tt.store(ka, 1)
    assert tt.store(kb, 1)
    assert tt.get(ka) == 1 and tt.get(kb) == 1
    assert tt.store(ka, 2) is False
    assert tt.store(ka, 0) is True
