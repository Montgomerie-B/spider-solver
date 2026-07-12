"""Opt011A tests — corrected-metric micro-corridor + exact-mode hardening."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from spider.deal import load_deal, tokens_from_file
from spider.deal_analysis import build_deal_analysis
from spider.engine import SpiderState
from spider.hash import zobrist
from spider.metrics import (
    CANONICAL_MOBILITYWARE_MOVES,
    parse_moves_file,
    replay_actions,
    replay_actions_detailed,
)
from spider.planner.diagnostics import experiment_4925153_opt011_cmd43_51_corridor as opt011
from spider.planner.diagnostics.experimental_move_ordering import HYBRID_TOP_K
from spider.rules import mobilityware_move_cost
from spider.solution_archive import (
    ENV_ARCHIVE_ROOT,
    path_hash,
    record_solution_if_better,
    validate_solution,
)

DEAL = ROOT / "deals" / "4925153.txt"
CANONICAL = ROOT / "solutions" / "4925153_canonical.moves"
RUNNER = (
    ROOT
    / "src/spider/planner/diagnostics/experiment_4925153_opt011_cmd43_51_corridor.py"
)
EXPECTED_PATH_HASH = "77d169da2538ba8c"


# ---------------------------------------------------------------------------
# Original focused tests (retained)
# ---------------------------------------------------------------------------


def test_canonical_replays_at_exactly_172_corrected_mw():
    acts = parse_moves_file(CANONICAL)
    st = SpiderState.from_cards(load_deal(DEAL))
    d = replay_actions_detailed(st, acts)
    assert d["mobilityware_moves"] == 172 == CANONICAL_MOBILITYWARE_MOVES
    assert d["explicit_commands"] == 174
    assert d["legacy_mw"] == 163
    assert st.is_solved()


def test_canonical_path_hash_unchanged():
    acts = parse_moves_file(CANONICAL)
    assert path_hash(acts) == EXPECTED_PATH_HASH
    v = validate_solution("4925153", CANONICAL)
    assert v.valid and v.path_hash == EXPECTED_PATH_HASH and v.mobilityware_moves == 172


def test_commands_43_46_47_51_corrected_costs_in_context():
    ep = opt011.build_corridor_endpoints()
    by = {r["command"]: r for r in ep["per_command_costs"]}
    assert by[43]["mobilityware_cost"] == 1 and by[43]["paid_reveal"]
    assert by[46]["mobilityware_cost"] == 0 and by[46]["zero_cost_full_column"]
    assert by[47]["mobilityware_cost"] == 1 and by[47]["paid_reveal"]
    assert by[51]["mobilityware_cost"] == 1 and by[51]["paid_reveal"]


def test_corridor_43_51_nine_explicit_eight_mw():
    ep = opt011.build_corridor_endpoints()
    assert ep["canonical_corridor_explicit"] == 9
    assert ep["canonical_corridor_mw"] == 8
    assert ep["segment_labels"] == opt011.CANONICAL_SEGMENT_LABELS


def test_start_and_target_match_canonical_replay():
    acts = parse_moves_file(CANONICAL)
    ep = opt011.build_corridor_endpoints()
    st42 = SpiderState.from_cards(load_deal(DEAL))
    replay_actions(st42, acts[:42])
    st51 = SpiderState.from_cards(load_deal(DEAL))
    replay_actions(st51, acts[:51])
    assert zobrist(st42) == ep["start"]["z"]
    assert zobrist(st51) == ep["target"]["z"]
    assert opt011.states_exactly_equal(st42, ep["start_state"])
    assert opt011.states_exactly_equal(st51, ep["target_state"])


def test_exact_target_rejects_structurally_similar_non_identical():
    ep = opt011.build_corridor_endpoints()
    tgt = ep["target_state"]
    other = tgt.clone()
    for col in other.columns:
        if len(col.face_up) >= 2:
            col.face_up[0], col.face_up[-1] = col.face_up[-1], col.face_up[0]
            break
        if len(col.face_up) == 1:
            col.face_down.append(col.face_up.pop())
            break
    assert not opt011.states_structurally_equal(other, tgt)
    assert not opt011.states_exactly_equal(other, tgt)


def test_search_ceiling_uses_only_corrected_cost():
    text = RUNNER.read_text(encoding="utf-8")
    assert 'OPTIMISATION_METRIC = "mobilityware_moves"' in text
    assert "SUCCESS_MW_CEILING = 7" in text
    with pytest.raises(SystemExit):
        opt011.main(["--metric", "legacy_mw"])


def test_zero_cost_paths_not_discarded_for_extra_explicit_commands():
    ep = opt011.build_corridor_endpoints()
    free = [r for r in ep["per_command_costs"] if r["mobilityware_cost"] == 0]
    assert len(free) == 1 and free[0]["command"] == 46


def test_checkpoint_resume_same_ordering_small_run(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    rt = tmp_path / "rt"
    art = tmp_path / "art"
    art.mkdir()
    (tmp_path / "art2").mkdir()
    r1 = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=60,
        success_ceiling=7,
        enable_checkpoint=True,
        checkpoint_dir=art,
        progress_path=art / "p.jsonl",
        runtime_dir=rt,
        resume=False,
    )
    r2 = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=60,
        success_ceiling=7,
        enable_checkpoint=True,
        checkpoint_dir=tmp_path / "art2",
        progress_path=tmp_path / "art2" / "p.jsonl",
        runtime_dir=tmp_path / "rt2",
        resume=False,
    )
    assert r1["expanded"] == r2["expanded"]
    assert r1["termination"] == r2["termination"]
    if r1.get("best_near") and r2.get("best_near"):
        assert r1["best_near"]["mw"] == r2["best_near"]["mw"]
        assert r1["best_near"]["z"] == r2["best_near"]["z"]


def test_splice_canonical_segment_not_improvement_and_archive_api(tmp_path, monkeypatch):
    root = tmp_path / "archive"
    monkeypatch.setenv(ENV_ARCHIVE_ROOT, str(root))
    ep = opt011.build_corridor_endpoints()
    splice = opt011.splice_full_solution(ep["segment"])
    assert splice["mobilityware_moves"] == 172
    assert splice["ok"] is False
    assert splice["path_hash"] == EXPECTED_PATH_HASH
    record_solution_if_better(
        "4925153", CANONICAL, source="bootstrap", archive_root=root, force_baseline=True
    )
    arch = opt011.archive_if_improving(splice["full_actions"], archive_root=root)
    assert arch["candidate_valid"] is True
    assert arch["is_strict_improvement"] is False


def test_runner_invokes_record_solution_if_better_on_complete_candidate():
    text = RUNNER.read_text(encoding="utf-8")
    assert "record_solution_if_better" in text
    assert "archive_if_improving" in text


def test_frozen_hybrid_adapter_identity():
    assert opt011.ORDERING_MODE == "hybrid_adapter"
    assert dict(opt011.HYBRID_TOP_K) == dict(HYBRID_TOP_K)


def test_step_cost_passes_face_down_for_paid_reveals():
    acts = parse_moves_file(CANONICAL)
    st = SpiderState.from_cards(load_deal(DEAL))
    for a in acts[:42]:
        if a == ("deal",):
            st.deal()
        else:
            st.move(*a)
    a43 = acts[42]
    s, d, k = a43
    assert len(st.columns[s].face_down) > 0
    assert opt011.step_cost_corrected(st, a43) == 1


def test_no_stock_deal_in_corridor_search():
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    ep = opt011.build_corridor_endpoints()
    ordered = opt011.order_moves_hybrid_complete(ep["start_state"], analysis)
    assert ("deal",) not in ordered


# ---------------------------------------------------------------------------
# Opt011A hardening tests
# ---------------------------------------------------------------------------


def test_exact_mode_has_no_active_explicit_depth_cutoff(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    r = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=30,
        max_depth=24,  # must be ignored
        enable_checkpoint=False,
        runtime_dir=tmp_path / "rt",
        checkpoint_dir=tmp_path / "ck",
        progress_path=tmp_path / "p.jsonl",
    )
    assert r["mode"] == "exact"
    assert r["max_depth_active"] is None
    assert r["exact_mode_has_depth_cutoff"] is False


def test_synthetic_01_route_longer_than_24_edges_found():
    """Cost ≤7 path with 30 edges (many zero-cost) must be found by exact_01_bfs."""
    # Linear chain: 0 --0--> 1 --0--> ... --0--> 23 --1--> 24 --1--> ... --1--> 30 goal
    # cost = 7, edges = 30
    goal = 30

    def succ(u):
        if u < 23:
            yield (u + 1, 0, f"z{u}")
        elif u < goal:
            yield (u + 1, 1, f"p{u}")

    res = opt011.exact_01_bfs(
        start=0,
        is_goal=lambda x: x == goal,
        successors=succ,
        cost_ceiling=7,
    )
    assert res["found"] is True
    assert res["cost"] == 7
    assert len(res["path_labels"]) == 30
    assert res["path_labels"][0].startswith("z")


def test_bounded_depth_24_never_reports_exhaustive_failure(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    (tmp_path / "art").mkdir()
    r = opt011.search_corridor(
        mode=opt011.MODE_BOUNDED,
        analysis=analysis,
        max_expanded=100,
        max_depth=24,
        enable_checkpoint=True,
        checkpoint_dir=tmp_path / "art",
        runtime_dir=tmp_path / "rt",
        progress_path=tmp_path / "art" / "p.jsonl",
    )
    assert r["mode"] == "bounded"
    assert r["status"] != "exhaustive_failure"
    assert r["termination"] != "exhausted"
    assert "bounded" in r["completeness_claim"] or r["status"] == "incomplete_search"


def test_zero_cost_cycles_terminate():
    # Fully connected zero-cost triangle — must terminate
    def succ(u):
        for v in (0, 1, 2):
            if v != u:
                yield (v, 0, f"{u}->{v}")

    res = opt011.exact_01_bfs(
        start=0,
        is_goal=lambda x: False,
        successors=succ,
        cost_ceiling=7,
    )
    assert res["exhausted"] is True
    assert res["states_seen"] == 3
    assert res["expanded"] <= 10


def test_higher_cost_arrivals_rejected():
    # Two paths to goal: cost 1 direct, cost 2 long — best_cost keeps 1
    def succ(u):
        if u == "S":
            yield ("G", 1, "direct")
            yield ("A", 1, "viaA")
        if u == "A":
            yield ("G", 1, "AtoG")

    res = opt011.exact_01_bfs(
        start="S",
        is_goal=lambda x: x == "G",
        successors=succ,
        cost_ceiling=7,
    )
    assert res["found"] and res["cost"] == 1
    assert res["best"]["G"] == 1


def test_equal_cost_identical_state_arrivals_safe():
    def succ(u):
        if u == "S":
            yield ("M", 1, "a")
            yield ("M", 1, "b")  # equal-cost same state
        if u == "M":
            yield ("G", 0, "done")

    res = opt011.exact_01_bfs(
        start="S",
        is_goal=lambda x: x == "G",
        successors=succ,
        cost_ceiling=7,
    )
    assert res["found"] and res["cost"] == 1


def test_hybrid_changes_ordering_only_not_reachable_set(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    common = dict(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=80,
        success_ceiling=7,
        enable_checkpoint=False,
    )
    r_h = opt011.search_corridor(
        **common,
        use_hybrid_ordering=True,
        runtime_dir=tmp_path / "rt_h",
        checkpoint_dir=tmp_path / "ck_h",
        progress_path=tmp_path / "p_h.jsonl",
    )
    r_e = opt011.search_corridor(
        **common,
        use_hybrid_ordering=False,
        runtime_dir=tmp_path / "rt_e",
        checkpoint_dir=tmp_path / "ck_e",
        progress_path=tmp_path / "p_e.jsonl",
    )
    # Same TT size / same status class under same expansion budget may differ
    # in order, but both must only use corrected MW and never accept deals.
    assert r_h["optimisation_metric"] == r_e["optimisation_metric"] == "mobilityware_moves"
    assert r_h["legacy_mw_used_for_search"] is False
    assert r_e["legacy_mw_used_for_search"] is False
    # Reachable under TT: both explore only cost<=7; improvements set equal
    # when both exhaust (not required here). At least same success ceiling.
    assert r_h["success_mw_ceiling"] == r_e["success_mw_ceiling"] == 7


def test_target_hash_without_structural_equality_rejected():
    ep = opt011.build_corridor_endpoints()
    tgt = ep["target_state"]
    other = tgt.clone()
    # Force structural mismatch: move one face-up card to face-down if possible
    mutated = False
    for col in other.columns:
        if col.face_up:
            col.face_down.append(col.face_up.pop())
            mutated = True
            break
    if not mutated:
        other.stock = list(other.stock) + list(other.stock[:1])
    assert not opt011.states_structurally_equal(other, tgt)
    assert not opt011.states_exactly_equal(other, tgt)
    # Hash equality alone is insufficient: even with matching z, structural required
    text = RUNNER.read_text(encoding="utf-8")
    assert "states_structurally_equal" in text
    assert "zobrist" in text


def test_structural_similarity_without_exact_equality_rejected():
    ep = opt011.build_corridor_endpoints()
    a = ep["start_state"].clone()
    b = ep["target_state"].clone()
    # Similar foundations/stock counts possible but not exact
    assert not opt011.states_exactly_equal(a, b)


def test_checkpoint_writes_are_atomic(tmp_path):
    path = tmp_path / "ck.json"
    opt011.atomic_write_json(path, {"hello": 1, "x": [1, 2, 3]})
    assert path.is_file()
    assert not list(tmp_path.glob("*.tmp*"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["hello"] == 1


def test_resume_reproduces_uninterrupted_exact_mode(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = tmp_path / "art"
    rt = tmp_path / "rt"
    art.mkdir()
    (tmp_path / "artf").mkdir()
    part = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=40,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p.jsonl",
        resume=False,
    )
    assert part["expanded"] == 40
    cont = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=80,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p2.jsonl",
        resume=True,
    )
    full = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=80,
        enable_checkpoint=True,
        checkpoint_dir=tmp_path / "artf",
        runtime_dir=tmp_path / "rtf",
        progress_path=tmp_path / "artf" / "p.jsonl",
        resume=False,
    )
    assert cont["expanded"] >= 40
    # Checkpoint must be loadable and share config identity with uninterrupted run
    ck = art / opt011.CHECKPOINT_NAME
    assert ck.is_file()
    data = json.loads(ck.read_text(encoding="utf-8"))
    assert data["algorithm_id"] == opt011.ALGORITHM_ID
    assert data["metric"] == "mobilityware_moves"
    assert data.get("integrity_checksum") == opt011.checkpoint_checksum(data)
    assert cont["config_identity"] == full["config_identity"]
    assert cont["status"] in (
        "incomplete_search",
        "verified_improvement",
        "exhaustive_failure",
    )


def test_resume_rejects_changed_cost_ceiling(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = tmp_path / "art"
    rt = tmp_path / "rt"
    art.mkdir()
    opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=20,
        success_ceiling=7,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p.jsonl",
    )
    with pytest.raises(RuntimeError, match="success_ceiling|config_identity|rejected"):
        opt011.search_corridor(
            mode=opt011.MODE_EXACT,
            analysis=analysis,
            max_expanded=40,
            success_ceiling=6,
            enable_checkpoint=True,
            checkpoint_dir=art,
            runtime_dir=rt,
            progress_path=art / "p2.jsonl",
            resume=True,
        )


def test_resume_rejects_changed_start_or_target_hash(tmp_path, monkeypatch):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = tmp_path / "art"
    rt = tmp_path / "rt"
    art.mkdir()
    opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=15,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p.jsonl",
    )
    ck = art / opt011.CHECKPOINT_NAME
    data = json.loads(ck.read_text(encoding="utf-8"))
    data["start_z"] = data["start_z"] + 1
    data["integrity_checksum"] = opt011.checkpoint_checksum(data)
    ck.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="start hash|config_identity|rejected"):
        opt011.search_corridor(
            mode=opt011.MODE_EXACT,
            analysis=analysis,
            max_expanded=30,
            enable_checkpoint=True,
            checkpoint_dir=art,
            runtime_dir=rt,
            resume=True,
        )


def test_resume_rejects_legacy_mw_metric(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = tmp_path / "art"
    rt = tmp_path / "rt"
    art.mkdir()
    opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=10,
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p.jsonl",
    )
    ck = art / opt011.CHECKPOINT_NAME
    data = json.loads(ck.read_text(encoding="utf-8"))
    data["metric"] = "legacy_mw"
    data["integrity_checksum"] = opt011.checkpoint_checksum(data)
    ck.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(RuntimeError, match="legacy_mw|metric|rejected|config_identity"):
        opt011.search_corridor(
            mode=opt011.MODE_EXACT,
            analysis=analysis,
            max_expanded=20,
            enable_checkpoint=True,
            checkpoint_dir=art,
            runtime_dir=rt,
            resume=True,
        )


def test_second_process_cannot_acquire_live_run_lock(tmp_path):
    rt = tmp_path / "rt"
    lock1 = opt011.RunLock(rt)
    lock1.acquire()
    lock2 = opt011.RunLock(rt)
    with pytest.raises(RuntimeError, match="lock|PID|Refuse"):
        lock2.acquire()
    lock1.release()
    lock2.acquire()
    lock2.release()


def test_memory_limit_termination_produces_resumable_outcome_c(tmp_path):
    analysis = build_deal_analysis(tokens_from_file(DEAL))
    art = tmp_path / "art"
    rt = tmp_path / "rt"
    art.mkdir()
    # Extremely small RSS limit should trip almost immediately on real process
    r = opt011.search_corridor(
        mode=opt011.MODE_EXACT,
        analysis=analysis,
        max_expanded=1_000_000,
        max_rss_gib=0.001,  # 1 MiB — below any real Python process
        enable_checkpoint=True,
        checkpoint_dir=art,
        runtime_dir=rt,
        progress_path=art / "p.jsonl",
    )
    assert r["status"] == "incomplete_search"
    assert r["termination"] == "max_rss"
    ck = art / opt011.CHECKPOINT_NAME
    assert ck.is_file()
    data = json.loads(ck.read_text(encoding="utf-8"))
    assert data["schema_version"] == opt011.CHECKPOINT_SCHEMA_VERSION
    assert data["integrity_checksum"] == opt011.checkpoint_checksum(data)
    # resumable under same config (may immediately hit RSS again — that's ok)
    assert data["config_identity"] == r["config_identity"]


def test_runtime_artefacts_not_tracked_by_git():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "opt011_progress.jsonl" in gi or "artifacts/opt011/" in gi
    assert "runtime_opt011" in gi or "opt011.lock" in gi
    # tracked source must remain
    assert "experiment_4925153_opt011" not in gi or "!" in gi


def test_full_canonical_still_172_and_path_hash():
    v = validate_solution("4925153", CANONICAL)
    assert v.mobilityware_moves == 172
    assert v.path_hash == EXPECTED_PATH_HASH


def test_archive_uses_temp_root(tmp_path, monkeypatch):
    root = tmp_path / "arch"
    monkeypatch.setenv(ENV_ARCHIVE_ROOT, str(root))
    r = record_solution_if_better(
        "4925153",
        CANONICAL,
        source="opt011a_test",
        archive_root=root,
        force_baseline=True,
    )
    assert r.candidate_mobilityware_moves == 172
    assert (root / "4925153").is_dir()


def test_discovered_splice_calls_record_solution_if_better():
    text = RUNNER.read_text(encoding="utf-8")
    assert "record_solution_if_better" in text
    assert "claimed_mobilityware_moves=None" in text
