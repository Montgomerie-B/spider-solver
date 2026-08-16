"""Opt013B — performance-preserving correctness + checkpoint gates."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.planner.diagnostics.opt012_compact_search import (
    ALGORITHM_ID,
    BACKEND_ID,
    CHECKPOINT_SCHEMA,
    audit_checkpoint,
    load_checkpoint,
    search_quotient,
    write_checkpoint_atomic,
    build_checkpoint_payload,
)
from spider.planner.diagnostics.opt012_free_quotient import component_key_from_state
from spider.planner.diagnostics.experiment_4925153_opt011_cmd43_51_corridor import (
    build_corridor_endpoints,
)
from spider.planner.diagnostics.opt013_algebraic_expansion import (
    differential_corpus_through_ceiling,
    expand_component_algebraic,
    expand_component_bruteforce,
    free_closure,
)
from spider.engine import SpiderState


def test_engine_clone_is_structural_not_deepcopy():
    """Regression: deepcopy clone dominated Opt013 runtime before Opt013B."""
    import inspect
    import textwrap
    from spider.engine import SpiderState as SS

    src = textwrap.dedent(inspect.getsource(SS.clone))
    # Body must be a structural list-copy, not a library deep copy call.
    body = src.split('"""', 2)[-1] if '"""' in src else src
    assert "deepcopy" not in body
    assert "list(c.face_down)" in body
    assert "list(c.face_up)" in body


def test_algebraic_c6_exhausts_corrected_467_under_budget():
    r = search_quotient(ceiling=6, expand_mode="algebraic")
    assert r.termination == "exhausted"
    assert r.tt_entries == 467
    assert r.runtime_seconds <= 120.0
    assert r.improvements == [] or r.segment_mw is None or r.segment_mw >= 8


def test_bruteforce_and_algebraic_c6_same_node_count():
    ra = search_quotient(ceiling=6, expand_mode="algebraic")
    rb = search_quotient(ceiling=6, expand_mode="bruteforce")
    assert ra.tt_entries == rb.tt_entries == 467
    assert ra.termination == rb.termination == "exhausted"
    assert ra.prune_stats["accepted"] == rb.prune_stats["accepted"]


def test_differential_corpus_c6_still_exact():
    r = differential_corpus_through_ceiling(6)
    assert r["n_components"] == 467
    assert r["ok"] is True, r["mismatches"]


def test_corrected_cost7_exhaustion_agrees_across_backends():
    algebraic = search_quotient(ceiling=7, expand_mode="algebraic")
    brute = search_quotient(ceiling=7, expand_mode="bruteforce")
    assert algebraic.termination == brute.termination == "exhausted"
    assert algebraic.status == brute.status == "exhaustive_failure"
    assert algebraic.tt_entries == brute.tt_entries == 3_677
    assert algebraic.generated_raw == brute.generated_raw == 44_118
    assert algebraic.improvements == brute.improvements == []


def test_n_empty_zero_singleton_still_holds():
    from spider.cards import Card
    from spider.engine import Column
    from spider.planner.diagnostics.opt012_free_quotient import free_slot_analysis

    cols = [Column([], []) for _ in range(10)]
    cols[0] = Column([], [Card("s", 3), Card("s", 2), Card("s", 1)])
    cols[1] = Column([], [Card("h", 5), Card("h", 4)])
    for i in range(2, 10):
        cols[i] = Column([Card("d", 13)], [Card("c", 1)])
    st = SpiderState(cols, [Card("s", 1)] * 50, [])
    assert free_slot_analysis(st)["n_empty"] == 0
    assert len(free_closure(st)) == 1
    b = {r["succ_component_key"] for r in expand_component_bruteforce(st)}
    a = {r["succ_component_key"] for r in expand_component_algebraic(st)}
    assert a == b


def test_checkpoint_audit_algebraic(tmp_path):
    a = audit_checkpoint(ceiling=6, expand_mode="algebraic", checkpoint_dir=tmp_path)
    assert a["schema"] == CHECKPOINT_SCHEMA
    assert a["backend_id"] == BACKEND_ID
    assert a["checkpoint_bytes"] > 0
    assert a["tmp_left"] is False
    assert a["tt_match"] is True
    assert a["n_nodes"] == a["n_nodes_restored"] == 467
    assert a["second_complete_graph"] is False
    assert a["cross_backend_resume_refused"] is True
    # bounded: write should not roughly double RSS into multi-GiB
    before = a["rss_before_write"] or 0
    after = a["rss_after_write"] or 0
    assert after < before + 200 * 1024 * 1024


def test_bruteforce_checkpoint_refuses_algebraic_resume(tmp_path):
    """Opt012 brute-force checkpoints must not silently resume as algebraic."""
    ep = build_corridor_endpoints()
    start = ep["start_state"]
    target = ep["target_state"]
    start_ck = component_key_from_state(start).to_bytes()
    target_comp = component_key_from_state(target).to_bytes()
    # Minimal fake brute checkpoint
    payload = build_checkpoint_payload(
        nodes=[],
        tt={},
        queue=[],
        expanded=0,
        generated_raw=0,
        unique_paid=0,
        ceiling=6,
        expand_mode="bruteforce",
        start_ck=start_ck,
        target_comp=target_comp,
        prune_stats={},
    )
    path = tmp_path / "brute.json"
    write_checkpoint_atomic(path, payload)
    with pytest.raises(RuntimeError, match="backend_id"):
        load_checkpoint(
            path,
            expect_backend_id=BACKEND_ID,
            expect_expand_mode="algebraic",
            expect_ceiling=6,
            expect_start_ck=start_ck,
            expect_target_comp=target_comp,
        )


def test_algorithm_id_documents_opt013():
    assert "opt013" in ALGORITHM_ID
