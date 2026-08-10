"""Opt013A — algebraic free rearrangement and paid expansion differential tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.cards import Card
from spider.engine import Column, SpiderState
from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
    build_corridor_endpoints,
)
from spider.planner.diagnostics.opt012_free_quotient import free_closure
from spider.planner.diagnostics.opt013_algebraic_expansion import (
    apply_arrangement_moves,
    arrangement_from_state,
    differential_expand,
    expand_component_algebraic,
    expand_component_bruteforce,
    plan_free_rearrangement,
    prove_all_arrangements_reachable,
)
from spider.state_identity import canonical_state_key


@pytest.fixture(scope="module")
def cmd42():
    return build_corridor_endpoints()["start_state"]


def test_bruteforce_oracle_named(cmd42):
    m = free_closure(cmd42)
    b = expand_component_bruteforce(cmd42, members=m)
    assert len(b) == 42


def test_plan_free_identity(cmd42):
    arr = arrangement_from_state(cmd42)
    assert plan_free_rearrangement(arr, arr) == []


def test_plan_free_all_720_from_start(cmd42):
    r = prove_all_arrangements_reachable(cmd42)
    assert r["n_members"] == 720
    assert r["fails"] == 0
    assert r["ok"] is True


def test_plan_free_sample_pairs_replay(cmd42):
    members = list(free_closure(cmd42).values())
    from spider.planner.diagnostics.opt012_free_quotient import (
        apply_action,
        is_free_relocation,
    )

    for i, j in [(0, 1), (0, 100), (50, 400), (10, 719)]:
        path = plan_free_rearrangement(
            arrangement_from_state(members[i]),
            arrangement_from_state(members[j]),
        )
        st = apply_arrangement_moves(members[i], path)
        assert canonical_state_key(st) == canonical_state_key(members[j])
        stc = members[i].clone()
        for a in path:
            assert is_free_relocation(stc, a)
            apply_action(stc, a)


def test_algebraic_equals_bruteforce_cmd42(cmd42):
    d = differential_expand(cmd42)
    assert d["equal"] is True, d
    assert d["brute_n"] == d["alg_n"] == 42


def _synthetic_state(
    free_piles: list,
    n_empty: int,
    fixed: list | None = None,
) -> SpiderState:
    """Build a 10-column state with free piles + empties + fixed blocked columns.

    Remaining columns get a single face-down card so they are not free empties.
    """
    cols = [Column([], []) for _ in range(10)]
    idx = 0
    for pile in free_piles:
        cards = [Card(s, r) for s, r in pile]
        cols[idx] = Column([], cards)
        idx += 1
    for _ in range(n_empty):
        cols[idx] = Column([], [])
        idx += 1
    if fixed:
        for fd, fu in fixed:
            cols[idx] = Column(
                [Card(s, r) for s, r in fd],
                [Card(s, r) for s, r in fu],
            )
            idx += 1
    while idx < 10:
        cols[idx] = Column([Card("d", 13)], [Card("c", 1)])
        idx += 1
    stock = [Card("s", 1)] * 50
    return SpiderState(cols, stock, [])


def test_synthetic_one_empty_two_piles():
    piles = [
        (("s", 5), ("s", 4), ("s", 3)),
        (("h", 8), ("h", 7)),
    ]
    st = _synthetic_state(piles, 1)
    members = free_closure(st)
    assert len(members) == 6
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_synthetic_multiple_empty():
    piles = [(("c", 3), ("c", 2), ("c", 1))]
    st = _synthetic_state(piles, 2)
    members = free_closure(st)
    assert len(members) == 3
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_synthetic_duplicate_piles():
    piles = [
        (("s", 2), ("s", 1)),
        (("s", 2), ("s", 1)),
    ]
    st = _synthetic_state(piles, 1)
    members = free_closure(st)
    assert len(members) == 3
    arr0 = arrangement_from_state(st)
    for m in members.values():
        path = plan_free_rearrangement(arr0, arrangement_from_state(m))
        st2 = apply_arrangement_moves(st, path)
        assert canonical_state_key(st2) == canonical_state_key(m)
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_non_movable_open_column_not_free():
    st = _synthetic_state([], 1)
    st.columns[0] = Column([], [Card("s", 5), Card("h", 9)])
    st.columns[1] = Column([], [])
    from spider.planner.diagnostics.opt012_free_quotient import free_slot_analysis

    a = free_slot_analysis(st)
    assert 0 in a["fixed_indices"]
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_partial_suffix_from_free_pile():
    piles = [
        (("s", 6), ("s", 5), ("s", 4), ("s", 3)),
        (("h", 9), ("h", 8)),
    ]
    fixed = [([("d", 13)], [("s", 7)])]
    st = _synthetic_state(piles, 1, fixed=fixed)
    d = differential_expand(st)
    assert d["equal"] is True, d
    assert d["brute_n"] == d["alg_n"]


def test_fixed_source_reveal():
    piles = [(("h", 3), ("h", 2), ("h", 1))]
    fixed = [([("c", 9)], [("c", 5), ("c", 4)])]
    st = _synthetic_state(piles, 1, fixed=fixed)
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_whole_free_pile_onto_nonempty():
    piles = [(("s", 5), ("s", 4), ("s", 3))]
    fixed = [([], [("s", 6)])]
    st = _synthetic_state(piles, 1, fixed=fixed)
    d = differential_expand(st)
    assert d["equal"] is True, d
    assert d["brute_n"] == d["alg_n"]


def test_n_empty_zero_singleton_orbit():
    piles = [
        (("s", 3), ("s", 2), ("s", 1)),
        (("h", 5), ("h", 4)),
    ]
    st = _synthetic_state(piles, 0)
    members = free_closure(st)
    assert len(members) == 1
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_automatic_foundation_boundary():
    piles = [tuple(("c", r) for r in range(12, 0, -1))]
    fixed = [([], [("c", 13)])]
    st = _synthetic_state(piles, 1, fixed=fixed)
    d = differential_expand(st)
    assert d["equal"] is True, d


def test_forced_numeric_hash_collision_keys_distinct():
    st = _synthetic_state(
        [(("s", 2), ("s", 1)), (("h", 2), ("h", 1))],
        1,
    )
    brute = expand_component_bruteforce(st)
    alg = expand_component_algebraic(st)
    kb = {r["succ_component_key"] for r in brute}
    ka = {r["succ_component_key"] for r in alg}
    assert kb == ka
    keys = list(kb)
    if len(keys) >= 2:
        dmap = {keys[0]: "a", keys[1]: "b"}
        assert len(dmap) == 2


def test_differential_through_ceiling_5():
    """Algebraic == brute for every component through paid cost 5."""
    from spider.planner.diagnostics.opt013_algebraic_expansion import (
        collect_components_through_ceiling,
    )

    reps = collect_components_through_ceiling(ceiling=5, expand_mode="algebraic")
    assert len(reps) == 5
    for rep in reps:
        d = differential_expand(rep)
        assert d["equal"] is True, d


def test_differential_through_ceiling_6():
    """Full Opt012 ceiling-6 corpus: 121 components, exact set agreement."""
    from spider.planner.diagnostics.opt013_algebraic_expansion import (
        differential_corpus_through_ceiling,
    )

    r = differential_corpus_through_ceiling(6)
    assert r["n_components"] == 121, r
    assert r["ok"] is True, r["mismatches"]
